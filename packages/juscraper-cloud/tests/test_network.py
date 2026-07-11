from pathlib import Path

import pytest
import requests

from juscraper_cloud.errors import ProxyConfigurationError
from juscraper_cloud.network import ProxyRoute


def test_proxy_route_accepts_explicit_values(tmp_path: Path) -> None:
    ca_bundle = tmp_path / "proxy-ca.pem"
    ca_bundle.write_text("certificate")

    route = ProxyRoute("https://user:secret@proxy.example:8443/path?token=private", ca_bundle)

    assert route.url == "https://user:secret@proxy.example:8443/path?token=private"
    assert route.ca_bundle == ca_bundle


def test_proxy_route_loads_values_from_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ca_bundle = tmp_path / "proxy-ca.pem"
    ca_bundle.write_text("certificate")
    monkeypatch.setenv("JUSCRAPER_PROXY_URL", "http://proxy.example:8080")
    monkeypatch.setenv("JUSCRAPER_PROXY_CA_BUNDLE", str(ca_bundle))

    assert ProxyRoute.from_env() == ProxyRoute("http://proxy.example:8080", ca_bundle)


def test_proxy_route_from_env_returns_none_when_url_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JUSCRAPER_PROXY_URL", raising=False)
    monkeypatch.setenv("JUSCRAPER_PROXY_CA_BUNDLE", "/ignored/without/url.pem")

    assert ProxyRoute.from_env() is None


@pytest.mark.parametrize("url", ["proxy.example:8080", "socks5://proxy.example:1080", "http:///missing-host"])
def test_proxy_route_rejects_missing_or_invalid_scheme_and_hostname(url: str) -> None:
    with pytest.raises(ProxyConfigurationError):
        ProxyRoute(url)


def test_proxy_route_rejects_missing_ca_bundle(tmp_path: Path) -> None:
    with pytest.raises(ProxyConfigurationError, match="CA bundle"):
        ProxyRoute("https://proxy.example", tmp_path / "missing.pem")


def test_apply_configures_whole_requests_session(tmp_path: Path) -> None:
    ca_bundle = tmp_path / "proxy-ca.pem"
    ca_bundle.write_text("certificate")
    route = ProxyRoute("https://user:secret@proxy.example:8443", ca_bundle)
    session = requests.Session()

    result = route.apply(session)

    assert result is None
    assert session.proxies == {
        "http": "https://user:secret@proxy.example:8443",
        "https": "https://user:secret@proxy.example:8443",
    }
    assert session.verify == str(ca_bundle)


def test_repr_redacts_credentials_and_query_values() -> None:
    route = ProxyRoute("https://alice:secret@proxy.example:8443/path?token=private&region=br")

    rendered = repr(route)

    assert "alice" not in rendered
    assert "secret" not in rendered
    assert "private" not in rendered
    assert "br" not in rendered
    assert "proxy.example:8443/path" in rendered
    assert "token=***" in rendered
    assert "region=***" in rendered
