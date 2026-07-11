from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager as ContextManager
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from urllib.parse import parse_qsl, quote, urlparse, urlunparse

Page = Any


@runtime_checkable
class BrowserProvider(Protocol):
    """Vendor-neutral source of managed browser pages."""

    def open_page(self) -> ContextManager[Page]:
        """Open a page and release every owned resource on context exit."""
        ...


@dataclass(frozen=True, repr=False)
class LocalPlaywrightProvider:
    """Open pages in a locally launched Chromium browser."""

    headless: bool = True
    proxy_server: str | None = None

    @contextmanager
    def open_page(self) -> Iterator[Page]:
        sync_playwright = _load_sync_playwright()
        with ExitStack() as stack:
            playwright = stack.enter_context(sync_playwright())
            launch_options: dict[str, Any] = {"headless": self.headless}
            if self.proxy_server is not None:
                launch_options["proxy"] = {"server": self.proxy_server}
            browser = playwright.chromium.launch(**launch_options)
            stack.callback(browser.close)
            context = browser.new_context()
            stack.callback(context.close)
            page = context.new_page()
            stack.callback(page.close)
            yield page

    def __repr__(self) -> str:
        proxy_server = _redact_url(self.proxy_server) if self.proxy_server is not None else None
        return f"{type(self).__name__}(headless={self.headless!r}, proxy_server={proxy_server!r})"


@dataclass(frozen=True, repr=False)
class PlaywrightWsProvider:
    """Open pages through a Playwright WebSocket endpoint."""

    endpoint: str
    headers: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        _validate_remote_endpoint(self.endpoint)
        if self.headers is not None:
            object.__setattr__(self, "headers", dict(self.headers))

    @contextmanager
    def open_page(self) -> Iterator[Page]:
        sync_playwright = _load_sync_playwright()
        with ExitStack() as stack:
            playwright = stack.enter_context(sync_playwright())
            options = _header_options(self.headers)
            browser = playwright.chromium.connect(self.endpoint, **options)
            stack.callback(browser.close)
            context = browser.new_context()
            stack.callback(context.close)
            page = context.new_page()
            stack.callback(page.close)
            yield page

    def __repr__(self) -> str:
        return _remote_repr(type(self).__name__, self.endpoint, self.headers)


@dataclass(frozen=True, repr=False)
class CdpPlaywrightProvider:
    """Open pages through a Chrome DevTools Protocol endpoint."""

    endpoint: str
    headers: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        _validate_remote_endpoint(self.endpoint)
        if self.headers is not None:
            object.__setattr__(self, "headers", dict(self.headers))

    @contextmanager
    def open_page(self) -> Iterator[Page]:
        sync_playwright = _load_sync_playwright()
        with ExitStack() as stack:
            playwright = stack.enter_context(sync_playwright())
            options = _header_options(self.headers)
            browser = playwright.chromium.connect_over_cdp(self.endpoint, **options)
            stack.callback(browser.close)

            owns_context = not browser.contexts
            context = browser.new_context() if owns_context else browser.contexts[0]
            if owns_context:
                stack.callback(context.close)

            owns_page = not context.pages
            page = context.new_page() if owns_page else context.pages[0]
            if owns_page:
                stack.callback(page.close)
            yield page

    def __repr__(self) -> str:
        return _remote_repr(type(self).__name__, self.endpoint, self.headers)


def _load_sync_playwright() -> Any:
    try:
        from playwright.sync_api import sync_playwright
    except (ImportError, ModuleNotFoundError):
        raise ImportError("Playwright is required to open browser pages; install juscraper-cloud[browser]") from None
    return sync_playwright


def _header_options(headers: Mapping[str, str] | None) -> dict[str, Any]:
    return {"headers": dict(headers)} if headers is not None else {}


def _validate_remote_endpoint(endpoint: str) -> None:
    try:
        parsed = urlparse(endpoint)
        _ = parsed.port
    except ValueError:
        raise ValueError("Browser endpoint is invalid") from None


def _redact_url(url: str) -> str:
    try:
        parsed = urlparse(url)
    except ValueError:
        return "<invalid-url>"
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port is not None:
        netloc = f"{netloc}:{port}"
    query = "&".join(f"{quote(key, safe='')}=***" for key, _ in parse_qsl(parsed.query, keep_blank_values=True))
    return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, query, ""))


def _remote_repr(name: str, endpoint: str, headers: Mapping[str, str] | None) -> str:
    header_names = tuple(headers) if headers is not None else None
    return f"{name}(endpoint={_redact_url(endpoint)!r}, headers={header_names!r})"


__all__ = [
    "BrowserProvider",
    "CdpPlaywrightProvider",
    "LocalPlaywrightProvider",
    "PlaywrightWsProvider",
]
