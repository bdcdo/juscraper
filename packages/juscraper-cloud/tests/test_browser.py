from __future__ import annotations

import sys
from collections.abc import Mapping
from contextlib import AbstractContextManager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import ModuleType
from typing import Any

import pytest

from juscraper_cloud.browser import (
    BrowserProvider,
    CdpPlaywrightProvider,
    LocalPlaywrightProvider,
    PlaywrightWsProvider,
)
from juscraper_cloud.factory import BrowserProvider as FactoryBrowserProvider


class FakePage:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class FakeContext:
    def __init__(self, pages: list[FakePage] | None = None) -> None:
        self.pages = pages or []
        self.new_page_calls = 0
        self.close_calls = 0

    def new_page(self) -> FakePage:
        self.new_page_calls += 1
        page = FakePage()
        self.pages.append(page)
        return page

    def close(self) -> None:
        self.close_calls += 1


class FakeBrowser:
    def __init__(self, contexts: list[FakeContext] | None = None) -> None:
        self.contexts = contexts or []
        self.new_context_calls = 0
        self.close_calls = 0

    def new_context(self) -> FakeContext:
        self.new_context_calls += 1
        context = FakeContext()
        self.contexts.append(context)
        return context

    def close(self) -> None:
        self.close_calls += 1


class FakeChromium:
    def __init__(self) -> None:
        self.launched_browser = FakeBrowser()
        self.connected_browser = FakeBrowser()
        self.cdp_browser = FakeBrowser()
        self.launch_calls: list[dict[str, Any]] = []
        self.connect_calls: list[tuple[str, dict[str, Any]]] = []
        self.cdp_calls: list[tuple[str, dict[str, Any]]] = []

    def launch(self, **kwargs: Any) -> FakeBrowser:
        self.launch_calls.append(kwargs)
        return self.launched_browser

    def connect(self, endpoint: str, **kwargs: Any) -> FakeBrowser:
        self.connect_calls.append((endpoint, kwargs))
        return self.connected_browser

    def connect_over_cdp(self, endpoint: str, **kwargs: Any) -> FakeBrowser:
        self.cdp_calls.append((endpoint, kwargs))
        return self.cdp_browser


class FakePlaywrightManager(AbstractContextManager[Any]):
    def __init__(self, chromium: FakeChromium) -> None:
        self.playwright = type("FakePlaywright", (), {"chromium": chromium})()
        self.exit_calls = 0

    def __enter__(self) -> Any:
        return self.playwright

    def __exit__(self, *exc_info: object) -> None:
        self.exit_calls += 1


def install_fake_playwright(monkeypatch: pytest.MonkeyPatch) -> tuple[FakeChromium, FakePlaywrightManager]:
    chromium = FakeChromium()
    manager = FakePlaywrightManager(chromium)
    package = ModuleType("playwright")
    sync_api = ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: manager  # type: ignore[attr-defined]
    package.sync_api = sync_api  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "playwright", package)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)
    return chromium, manager


def test_browser_provider_is_runtime_checkable_and_factory_alias_is_preserved() -> None:
    provider = LocalPlaywrightProvider()

    assert BrowserProvider is FactoryBrowserProvider
    assert isinstance(provider, BrowserProvider)


@pytest.mark.parametrize("raises", [False, True])
def test_local_provider_launches_fresh_page_and_cleans_up(monkeypatch: pytest.MonkeyPatch, raises: bool) -> None:
    chromium, manager = install_fake_playwright(monkeypatch)
    provider = LocalPlaywrightProvider(headless=False, proxy_server="http://proxy.example:8080")

    with pytest.raises(RuntimeError) if raises else _does_not_raise(), provider.open_page() as page:
        assert page is chromium.launched_browser.contexts[0].pages[0]
        if raises:
            raise RuntimeError("falha durante o uso")

    context = chromium.launched_browser.contexts[0]
    assert chromium.launch_calls == [{"headless": False, "proxy": {"server": "http://proxy.example:8080"}}]
    assert chromium.launched_browser.new_context_calls == 1
    assert context.new_page_calls == 1
    assert page.close_calls == 1
    assert context.close_calls == 1
    assert chromium.launched_browser.close_calls == 1
    assert manager.exit_calls == 1


@pytest.mark.parametrize("raises", [False, True])
def test_websocket_provider_connects_with_headers_and_cleans_up(monkeypatch: pytest.MonkeyPatch, raises: bool) -> None:
    chromium, manager = install_fake_playwright(monkeypatch)
    headers: Mapping[str, str] = {"Authorization": "Bearer private"}
    provider = PlaywrightWsProvider("wss://browser.example/playwright", headers=headers)

    with pytest.raises(ValueError) if raises else _does_not_raise(), provider.open_page() as page:
        assert page is chromium.connected_browser.contexts[0].pages[0]
        if raises:
            raise ValueError("falha durante o uso")

    context = chromium.connected_browser.contexts[0]
    assert chromium.connect_calls == [
        ("wss://browser.example/playwright", {"headers": {"Authorization": "Bearer private"}})
    ]
    assert chromium.connected_browser.new_context_calls == 1
    assert context.new_page_calls == 1
    assert page.close_calls == 1
    assert context.close_calls == 1
    assert chromium.connected_browser.close_calls == 1
    assert manager.exit_calls == 1


def test_cdp_provider_reuses_existing_default_page_and_only_closes_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chromium, manager = install_fake_playwright(monkeypatch)
    existing_page = FakePage()
    default_context = FakeContext([existing_page])
    chromium.cdp_browser = FakeBrowser([default_context])
    provider = CdpPlaywrightProvider("https://browser.example/cdp", headers={"X-Session": "session-id"})

    with provider.open_page() as page:
        assert page is existing_page

    assert chromium.cdp_calls == [("https://browser.example/cdp", {"headers": {"X-Session": "session-id"}})]
    assert chromium.cdp_browser.new_context_calls == 0
    assert default_context.new_page_calls == 0
    assert existing_page.close_calls == 0
    assert default_context.close_calls == 0
    assert chromium.cdp_browser.close_calls == 1
    assert manager.exit_calls == 1


def test_cdp_provider_creates_and_closes_page_when_default_context_has_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chromium, _ = install_fake_playwright(monkeypatch)
    default_context = FakeContext()
    chromium.cdp_browser = FakeBrowser([default_context])

    with CdpPlaywrightProvider("http://browser.example:9222").open_page() as page:
        assert page is default_context.pages[0]

    assert default_context.new_page_calls == 1
    assert page.close_calls == 1
    assert default_context.close_calls == 0
    assert chromium.cdp_browser.close_calls == 1


def test_cdp_provider_creates_fresh_context_when_connection_has_no_contexts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chromium, _ = install_fake_playwright(monkeypatch)

    with CdpPlaywrightProvider("http://browser.example:9222").open_page() as page:
        assert page is chromium.cdp_browser.contexts[0].pages[0]

    context = chromium.cdp_browser.contexts[0]
    assert chromium.cdp_browser.new_context_calls == 1
    assert context.new_page_calls == 1
    assert page.close_calls == 1
    assert context.close_calls == 1
    assert chromium.cdp_browser.close_calls == 1


@pytest.mark.parametrize("provider_type", [PlaywrightWsProvider, CdpPlaywrightProvider])
def test_remote_provider_repr_redacts_userinfo_and_query_values(provider_type: type[Any]) -> None:
    provider = provider_type(
        "wss://alice:secret@browser.example/session?token=private&region=br",
        headers={"Authorization": "Bearer also-private"},
    )

    rendered = repr(provider)

    assert "alice" not in rendered
    assert "secret" not in rendered
    assert "private" not in rendered
    assert "also-private" not in rendered
    assert "=br" not in rendered
    assert "browser.example/session" in rendered
    assert "token=***" in rendered
    assert "region=***" in rendered


def test_open_page_explains_how_to_install_optional_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.delitem(sys.modules, "playwright.sync_api", raising=False)

    with pytest.raises(ImportError, match=r"juscraper-cloud\[browser\]"), LocalPlaywrightProvider().open_page():
        pass


class _does_not_raise(AbstractContextManager[None]):
    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc_info: object) -> None:
        return None


@pytest.mark.browser_integration
def test_local_playwright_opens_static_page(tmp_path: Path) -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    (tmp_path / "index.html").write_text("<title>juscraper cloud</title>")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _quiet_handler(tmp_path))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with LocalPlaywrightProvider().open_page() as page:
            page.goto(f"http://127.0.0.1:{server.server_port}/")
            assert page.title() == "juscraper cloud"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()

    assert playwright is not None


def _quiet_handler(directory: Path) -> type[SimpleHTTPRequestHandler]:
    class QuietHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(directory), **kwargs)

        def log_message(self, format: str, *args: object) -> None:
            pass

    return QuietHandler
