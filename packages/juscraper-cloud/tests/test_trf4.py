from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from juscraper_cloud.errors import BrowserChallengeError
from juscraper_cloud.trf4 import TRF4_DEPLOYMENTS, fetch_trf4_detail, parse_trf4_detail


SAMPLES = Path(__file__).parent / "samples" / "trf4" / "cpopg"


class FakeElement:
    def __init__(self, page: FakePage, selector: str) -> None:
        self.page = page
        self.selector = selector

    def fill(self, value: str) -> None:
        self.page.calls.append(("fill", self.selector, value))

    def select_option(self, value: str) -> None:
        self.page.calls.append(("select_option", self.selector, value))

    def click(self) -> None:
        self.page.calls.append(("click", self.selector))


class FakePage:
    def __init__(
        self,
        html: str,
        *,
        timeout: bool = False,
        timeout_error: Exception | None = None,
        evaluate_post_continuation: bool = False,
    ) -> None:
        self.html = html
        self.timeout = timeout
        self.timeout_error = timeout_error
        self.evaluate_post_continuation = evaluate_post_continuation
        self.calls: list[tuple[Any, ...]] = []

    def goto(self, url: str) -> None:
        self.calls.append(("goto", url))

    def locator(self, selector: str) -> FakeElement:
        self.calls.append(("locator", selector))
        return FakeElement(self, selector)

    def wait_for_function(self, expression: str, *, timeout: float) -> None:
        self.calls.append(("wait_for_function", expression, timeout))
        if self.timeout:
            raise self.timeout_error or TimeoutError("challenge timed out")
        if (
            self.evaluate_post_continuation
            and len([call for call in self.calls if call[0] == "wait_for_function"]) == 3
        ):
            lowered = self.html.lower()
            if "text.includes('captcha')" in expression or "text.includes('turnstile')" in expression:
                return
            terminal = (
                "detalhes do processo" in lowered
                or "nenhum processo encontrado" in lowered
                or "turnstile verification failed" in lowered
            )
            if not terminal:
                raise TimeoutError("post-continuation result timed out")

    def content(self) -> str:
        self.calls.append(("content",))
        return self.html


def test_trf4_deployments_map_to_uppercase_origins() -> None:
    assert set(TRF4_DEPLOYMENTS) == {"pr", "sc", "rs"}
    assert {name: item.origin for name, item in TRF4_DEPLOYMENTS.items()} == {
        "pr": "PR",
        "sc": "SC",
        "rs": "RS",
    }
    assert {item.base_url for item in TRF4_DEPLOYMENTS.values()} == {"https://www2.trf4.jus.br/trf4/controlador.php"}


def test_fetch_trf4_submits_unified_form_and_turnstile_continuation() -> None:
    html = (SAMPLES / "detail_normal.html").read_text()
    page = FakePage(html)

    result = fetch_trf4_detail(page, TRF4_DEPLOYMENTS["rs"], "5000123-45.2024.4.04.7100")

    assert result == html
    assert ("goto", "https://www2.trf4.jus.br/trf4/controlador.php") in page.calls
    assert ("select_option", "#selFormaI", "NU") in page.calls
    assert ("fill", "#txtValorI", "5000123-45.2024.4.04.7100") in page.calls
    assert ("select_option", "#selOrigemI", "RS") in page.calls
    assert ("click", "#botaoEnviar") in page.calls
    assert any(call[0] == "wait_for_function" and "cf-turnstile-response" in call[1] for call in page.calls)
    assert ("click", 'input[name="sbmContinuar"]') in page.calls


def test_fetch_trf4_maps_turnstile_timeout_to_browser_challenge_error() -> None:
    page = FakePage("", timeout=True)

    with pytest.raises(BrowserChallengeError, match="Turnstile"):
        fetch_trf4_detail(page, TRF4_DEPLOYMENTS["pr"], "5000123-45.2024.4.04.7000")


def test_fetch_trf4_maps_playwright_timeout_without_importing_playwright() -> None:
    playwright_timeout = type("TimeoutError", (Exception,), {})("playwright timed out")
    page = FakePage("", timeout=True, timeout_error=playwright_timeout)

    with pytest.raises(BrowserChallengeError, match="Turnstile"):
        fetch_trf4_detail(page, TRF4_DEPLOYMENTS["pr"], "5000123-45.2024.4.04.7000")


def test_fetch_trf4_returns_none_for_no_results_page() -> None:
    page = FakePage((SAMPLES / "no_results.html").read_text())

    assert fetch_trf4_detail(page, TRF4_DEPLOYMENTS["sc"], "5000123-45.2024.4.04.7200") is None


def test_fetch_trf4_neutral_turnstile_markup_waits_until_result_timeout() -> None:
    page = FakePage(
        '<form><input name="cf-turnstile-response"><span>Turnstile protected</span></form>',
        evaluate_post_continuation=True,
    )

    with pytest.raises(BrowserChallengeError, match="did not follow"):
        fetch_trf4_detail(page, TRF4_DEPLOYMENTS["pr"], "5000123-45.2024.4.04.7000")


def test_fetch_trf4_explicit_turnstile_failure_is_challenge_error() -> None:
    page = FakePage(
        "<div>Turnstile verification failed. Please retry.</div>",
        evaluate_post_continuation=True,
    )

    with pytest.raises(BrowserChallengeError, match="browser challenge failed"):
        fetch_trf4_detail(page, TRF4_DEPLOYMENTS["pr"], "5000123-45.2024.4.04.7000")


def test_fetch_trf4_captcha_with_unrelated_error_identifier_is_not_challenge_failure() -> None:
    page = FakePage(
        '<form><span>captcha protected</span><input id="url_log_erro_javascript"></form>',
        evaluate_post_continuation=True,
    )

    with pytest.raises(BrowserChallengeError, match="did not follow"):
        fetch_trf4_detail(page, TRF4_DEPLOYMENTS["pr"], "5000123-45.2024.4.04.7000")


def test_parse_trf4_detail_extracts_normalized_metadata() -> None:
    record = parse_trf4_detail((SAMPLES / "detail_normal.html").read_text())

    assert record == {
        "processo": "5000123-45.2024.4.04.7000",
        "classe": "Procedimento Comum Cível",
        "assunto": "Direito Administrativo",
        "data_distribuicao": "02/01/2024",
        "orgao_julgador": "1ª Vara Federal Sintética",
        "polo_ativo": ["PARTE AUTORA SINTÉTICA"],
        "polo_passivo": ["PARTE RÉ SINTÉTICA"],
        "movimentacoes": [{"data": "03/01/2024", "descricao": "Distribuído por sorteio"}],
    }


def test_parse_trf4_detail_uses_stable_defaults_for_absent_fields() -> None:
    record = parse_trf4_detail("<html><h1>Detalhes do Processo</h1></html>")

    assert record == {
        "processo": None,
        "classe": None,
        "assunto": None,
        "data_distribuicao": None,
        "orgao_julgador": None,
        "polo_ativo": [],
        "polo_passivo": [],
        "movimentacoes": [],
    }
