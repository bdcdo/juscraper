import os
from pathlib import Path
from typing import Any

import pytest
import requests

import juscraper
from juscraper_cloud.errors import ProxyConfigurationError
from juscraper_cloud.factory import scraper
from juscraper_cloud.network import ProxyRoute


class UpstreamScraper:
    def __init__(self) -> None:
        self.session = requests.Session()


def install_upstream_factory(
    monkeypatch: pytest.MonkeyPatch, result: Any
) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fake_scraper(*args: Any, **kwargs: Any) -> Any:
        calls.append((args, kwargs))
        return result

    monkeypatch.setattr(juscraper, "scraper", fake_scraper)
    return calls


def test_scraper_delegates_sigla_and_api_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream = UpstreamScraper()
    calls = install_upstream_factory(monkeypatch, upstream)

    result = scraper("tjsp", download_path="downloads", verbose=True)

    assert result is upstream
    assert calls == [(("tjsp",), {"download_path": "downloads", "verbose": True})]


def test_scraper_applies_route_to_whole_session_and_returns_same_object(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream = UpstreamScraper()
    install_upstream_factory(monkeypatch, upstream)
    route = ProxyRoute("https://proxy.example:8443")

    result = scraper("tjrs", route=route)

    assert result is upstream
    assert upstream.session.proxies == {
        "http": "https://proxy.example:8443",
        "https": "https://proxy.example:8443",
    }


def test_scraper_uses_environment_route_when_explicit_route_is_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    upstream = UpstreamScraper()
    install_upstream_factory(monkeypatch, upstream)
    ca_bundle = tmp_path / "proxy-ca.pem"
    ca_bundle.write_text("certificate")
    monkeypatch.setenv("JUSCRAPER_PROXY_URL", "http://proxy.example:8080")
    monkeypatch.setenv("JUSCRAPER_PROXY_CA_BUNDLE", str(ca_bundle))

    scraper("tjdf", route=None)

    assert upstream.session.proxies == {
        "http": "http://proxy.example:8080",
        "https": "http://proxy.example:8080",
    }
    assert upstream.session.verify == str(ca_bundle)


def test_scraper_fails_helpfully_when_route_target_has_no_requests_session(monkeypatch: pytest.MonkeyPatch) -> None:
    install_upstream_factory(monkeypatch, object())

    with pytest.raises(ProxyConfigurationError, match=r"requests\.Session"):
        scraper("tjsp", route=ProxyRoute("http://proxy.example:8080"))


@pytest.mark.parametrize("sigla", ["trf2", "TRF4"])
def test_scraper_rejects_proxy_route_for_future_browser_only_scrapers(
    monkeypatch: pytest.MonkeyPatch, sigla: str
) -> None:
    calls = install_upstream_factory(monkeypatch, UpstreamScraper())

    with pytest.raises(ProxyConfigurationError, match="browser"):
        scraper(sigla, route=ProxyRoute("http://proxy.example:8080"))

    assert calls == []


def test_scraper_rejects_browser_argument_for_upstream_scraper(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_upstream_factory(monkeypatch, UpstreamScraper())

    with pytest.raises(NotImplementedError, match="browser"):
        scraper("tjsp", browser=object())

    assert calls == []


def test_scraper_does_not_mutate_proxy_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream = UpstreamScraper()
    install_upstream_factory(monkeypatch, upstream)
    monkeypatch.setenv("HTTP_PROXY", "http://existing-http.example")
    monkeypatch.setenv("HTTPS_PROXY", "http://existing-https.example")

    scraper("tjsp", route=ProxyRoute("http://route.example:8080"))

    assert os.environ["HTTP_PROXY"] == "http://existing-http.example"
    assert os.environ["HTTPS_PROXY"] == "http://existing-https.example"
