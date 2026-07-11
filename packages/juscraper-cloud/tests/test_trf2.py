from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from juscraper_cloud.errors import BrowserChallengeError
from juscraper_cloud.trf2 import TRF2_DEPLOYMENTS, fetch_trf2_detail


DETAIL_HTML = "<title>Detalhes do Processo</title><legend>Capa do Processo</legend>"
NO_RESULTS_HTML = """<form>
<label for="txtNumABC">Nº Processo</label><input id="txtNumABC">
<input type="hidden" name="cf-turnstile-response">
<span>Proteção captcha ativa</span>
<input id="url_log_erro_javascript">
</form>"""
TRF6_SAMPLES = Path(__file__).parents[3] / "tests" / "trf6" / "samples" / "cpopg"


class FakeElement:
    def __init__(self, page: FakePage, selector: str, count: int = 1) -> None:
        self.page = page
        self.selector = selector
        self._count = count

    def count(self) -> int:
        self.page.calls.append(("count", self.selector))
        return self._count

    def fill(self, value: str) -> None:
        self.page.calls.append(("fill", self.selector, value))

    def click(self) -> None:
        self.page.calls.append(("click", self.selector))


class FakePage:
    def __init__(
        self,
        html: str = DETAIL_HTML,
        *,
        label_count: int = 1,
        timeout: bool = False,
        timeout_error: Exception | None = None,
    ) -> None:
        self.html = html
        self.label_count = label_count
        self.timeout = timeout
        self.timeout_error = timeout_error
        self.calls: list[tuple[Any, ...]] = []

    def goto(self, url: str) -> None:
        self.calls.append(("goto", url))

    def get_by_label(self, label: str, *, exact: bool = False) -> FakeElement:
        self.calls.append(("get_by_label", label, exact))
        return FakeElement(self, f"label:{label}", self.label_count)

    def locator(self, selector: str) -> FakeElement:
        self.calls.append(("locator", selector))
        return FakeElement(self, selector)

    def wait_for_function(self, expression: str, *, timeout: float) -> None:
        self.calls.append(("wait_for_function", expression, timeout))
        if self.timeout:
            raise self.timeout_error or TimeoutError("challenge timed out")

    def content(self) -> str:
        self.calls.append(("content",))
        return self.html


class FakeProvider:
    def __init__(self, page: FakePage) -> None:
        self.page = page

    @contextmanager
    def open_page(self):  # type: ignore[no-untyped-def]
        yield self.page


def test_trf2_deployments_have_canonical_browser_urls() -> None:
    assert TRF2_DEPLOYMENTS["rj"].name == "rj"
    assert TRF2_DEPLOYMENTS["rj"].base_url == "https://eproc-consulta.jfrj.jus.br/eproc/"
    assert TRF2_DEPLOYMENTS["es"].name == "es"
    assert TRF2_DEPLOYMENTS["es"].base_url == "https://eproc-consulta.jfes.jus.br/eproc/"


def test_fetch_trf2_uses_accessible_label_turnstile_and_returns_content() -> None:
    page = FakePage()

    result = fetch_trf2_detail(page, TRF2_DEPLOYMENTS["rj"], "0000123-45.2024.4.02.5101")

    assert result == DETAIL_HTML
    assert ("goto", "https://eproc-consulta.jfrj.jus.br/eproc/") in page.calls
    assert ("get_by_label", "Nº Processo", True) in page.calls
    assert ("fill", "label:Nº Processo", "0000123-45.2024.4.02.5101") in page.calls
    assert any(call[0] == "wait_for_function" and "cf-turnstile-response" in call[1] for call in page.calls)
    assert ("click", "#sbmNovo") in page.calls


def test_fetch_trf2_falls_back_to_dynamic_process_id_prefix() -> None:
    page = FakePage(label_count=0)

    fetch_trf2_detail(page, TRF2_DEPLOYMENTS["es"], "0000123-45.2024.4.02.5001")

    assert ("locator", 'input[id^="txtNum"]') in page.calls
    assert ("fill", 'input[id^="txtNum"]', "0000123-45.2024.4.02.5001") in page.calls


def test_fetch_trf2_returns_none_when_search_form_is_returned() -> None:
    page = FakePage(NO_RESULTS_HTML)

    assert fetch_trf2_detail(page, TRF2_DEPLOYMENTS["rj"], "0000123-45.2024.4.02.5101") is None


def test_fetch_trf2_classifies_upstream_eproc_no_result_fixture() -> None:
    page = FakePage((TRF6_SAMPLES / "search_no_results.html").read_text(encoding="latin-1"))

    assert fetch_trf2_detail(page, TRF2_DEPLOYMENTS["rj"], "0000123-45.2024.4.02.5101") is None


def test_fetch_trf2_classifies_upstream_eproc_bad_captcha_fixture() -> None:
    page = FakePage((TRF6_SAMPLES / "search_bad_captcha.html").read_text(encoding="latin-1"))

    with pytest.raises(BrowserChallengeError, match="challenge"):
        fetch_trf2_detail(page, TRF2_DEPLOYMENTS["rj"], "0000123-45.2024.4.02.5101")


def test_fetch_trf2_maps_turnstile_timeout_to_browser_challenge_error() -> None:
    page = FakePage(timeout=True)

    with pytest.raises(BrowserChallengeError, match="Turnstile"):
        fetch_trf2_detail(page, TRF2_DEPLOYMENTS["rj"], "0000123-45.2024.4.02.5101")


def test_fetch_trf2_maps_playwright_timeout_without_importing_playwright() -> None:
    playwright_timeout = type("TimeoutError", (Exception,), {})("playwright timed out")
    page = FakePage(timeout=True, timeout_error=playwright_timeout)

    with pytest.raises(BrowserChallengeError, match="Turnstile"):
        fetch_trf2_detail(page, TRF2_DEPLOYMENTS["rj"], "0000123-45.2024.4.02.5101")


def test_fetch_trf2_maps_explicit_challenge_failure_to_browser_challenge_error() -> None:
    page = FakePage("<p>Falha na validação do captcha Cloudflare Turnstile</p>")

    with pytest.raises(BrowserChallengeError, match="challenge"):
        fetch_trf2_detail(page, TRF2_DEPLOYMENTS["rj"], "0000123-45.2024.4.02.5101")
