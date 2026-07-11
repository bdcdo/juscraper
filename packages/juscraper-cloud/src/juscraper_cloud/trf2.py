"""Fluxo browser da consulta processual eproc do TRF2."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, cast

from .browser import is_browser_timeout
from .errors import BrowserChallengeError


@dataclass(frozen=True)
class TRF2Deployment:
    """Uma implantação pública eproc do TRF2."""

    name: str
    base_url: str


TRF2_DEPLOYMENTS = {
    "rj": TRF2Deployment("rj", "https://eproc-consulta.jfrj.jus.br/eproc/"),
    "es": TRF2Deployment("es", "https://eproc-consulta.jfes.jus.br/eproc/"),
}

_TURNSTILE_COMPLETE = """() => {
    const response = document.querySelector('[name="cf-turnstile-response"]');
    return response && response.value.length > 0;
}"""
_RESULT_READY = """() => {
    const text = document.body.innerText;
    return (text.includes('Detalhes do Processo') && text.includes('Capa do Processo'))
        || text.toLowerCase().includes('captcha')
        || document.querySelector('input[id^="txtNum"]');
}"""
_CHALLENGE_FAILURE = re.compile(
    r"(?:captcha|turnstile).{0,100}(?:incorret|inv[aá]lid|falh|expir|timeout)"
    r"|(?:incorret|inv[aá]lid|falh|expir|timeout).{0,100}(?:captcha|turnstile)",
    re.IGNORECASE | re.DOTALL,
)


def fetch_trf2_detail(
    page: Any,
    deployment: TRF2Deployment,
    formatted_cnj: str,
    *,
    timeout_ms: float = 30_000,
) -> str | None:
    """Consulta um CNJ no eproc e devolve o HTML de detalhe ou ``None``."""
    page.goto(deployment.base_url)
    process_input = page.get_by_label("Nº Processo", exact=True)
    if process_input.count() == 0:
        process_input = page.locator('input[id^="txtNum"]')
    process_input.fill(formatted_cnj)

    try:
        page.wait_for_function(_TURNSTILE_COMPLETE, timeout=timeout_ms)
    except Exception as exc:
        if not is_browser_timeout(exc):
            raise
        raise BrowserChallengeError("TRF2 Turnstile challenge timed out") from exc

    page.locator("#sbmNovo").click()
    try:
        page.wait_for_function(_RESULT_READY, timeout=timeout_ms)
    except Exception as exc:
        if not is_browser_timeout(exc):
            raise
        raise BrowserChallengeError("TRF2 result did not follow the Turnstile challenge") from exc

    html = cast(str, page.content())
    lowered = html.lower()
    if _CHALLENGE_FAILURE.search(html):
        raise BrowserChallengeError("TRF2 browser challenge failed")
    if "detalhes do processo" in lowered and "capa do processo" in lowered:
        return html
    if "nº processo" in lowered or 'input id="txtnum' in lowered:
        return None
    return None


__all__ = ["TRF2_DEPLOYMENTS", "TRF2Deployment", "fetch_trf2_detail"]
