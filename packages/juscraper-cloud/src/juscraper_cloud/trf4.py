"""Fluxo browser e parser da consulta processual unificada do TRF4."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, cast

from bs4 import BeautifulSoup

from .browser import is_browser_timeout
from .errors import BrowserChallengeError

TRF4_BASE_URL = "https://www2.trf4.jus.br/trf4/controlador.php"


@dataclass(frozen=True)
class TRF4Deployment:
    """Uma origem da consulta processual unificada do TRF4."""

    name: str
    origin: str

    @property
    def base_url(self) -> str:
        return TRF4_BASE_URL


TRF4_DEPLOYMENTS = {name: TRF4Deployment(name, name.upper()) for name in ("pr", "sc", "rs")}

_INTERMEDIATE_READY = """() => Boolean(document.querySelector('input[name="sbmContinuar"]'))"""
_TURNSTILE_COMPLETE = """() => {
    const response = document.querySelector('[name="cf-turnstile-response"]');
    return response && response.value.length > 0;
}"""
_RESULT_READY = """() => {
    const text = document.body.innerText.toLowerCase();
    return text.includes('detalhes do processo')
        || text.includes('nenhum processo encontrado')
        || text.includes('captcha') || text.includes('turnstile');
}"""


def fetch_trf4_detail(
    page: Any,
    deployment: TRF4Deployment,
    formatted_cnj: str,
    *,
    timeout_ms: float = 30_000,
) -> str | None:
    """Consulta um CNJ no portal unificado e devolve o HTML ou ``None``."""
    page.goto(deployment.base_url)
    page.locator("#selFormaI").select_option("NU")
    page.locator("#txtValorI").fill(formatted_cnj)
    page.locator("#selOrigemI").select_option(deployment.origin)
    page.locator("#botaoEnviar").click()

    try:
        page.wait_for_function(_INTERMEDIATE_READY, timeout=timeout_ms)
        page.wait_for_function(_TURNSTILE_COMPLETE, timeout=timeout_ms)
    except Exception as exc:
        if not is_browser_timeout(exc):
            raise
        raise BrowserChallengeError("TRF4 Turnstile challenge timed out") from exc

    page.locator('input[name="sbmContinuar"]').click()
    try:
        page.wait_for_function(_RESULT_READY, timeout=timeout_ms)
    except Exception as exc:
        if not is_browser_timeout(exc):
            raise
        raise BrowserChallengeError("TRF4 result did not follow the Turnstile challenge") from exc

    html = cast(str, page.content())
    lowered = html.lower()
    if "captcha" in lowered and ("falha" in lowered or "erro" in lowered):
        raise BrowserChallengeError("TRF4 browser challenge failed")
    if "nenhum processo encontrado" in lowered:
        return None
    if "detalhes do processo" in lowered:
        return html
    return None


def _normalized_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized or None


def _definition_fields(soup: BeautifulSoup) -> dict[str, str | None]:
    fields: dict[str, str | None] = {}
    for term in soup.find_all("dt"):
        definition = term.find_next_sibling("dd")
        if definition is not None:
            label = (_normalized_text(term.get_text(" ")) or "").casefold()
            fields[label] = _normalized_text(definition.get_text(" "))
    return fields


def parse_trf4_detail(html: str) -> dict[str, Any]:
    """Extrai um registro normalizado de uma página de detalhe do TRF4."""
    soup = BeautifulSoup(html, "html.parser")
    fields = _definition_fields(soup)
    field_aliases = {
        "processo": ("processo", "número do processo", "numero do processo"),
        "classe": ("classe", "classe processual"),
        "assunto": ("assunto", "assunto principal"),
        "data_distribuicao": ("data de distribuição", "data de distribuicao"),
        "orgao_julgador": ("órgão julgador", "orgao julgador"),
    }
    record: dict[str, Any] = {}
    for output, labels in field_aliases.items():
        record[output] = next((fields[label] for label in labels if label in fields), None)

    record["polo_ativo"] = [
        text
        for node in soup.select('[data-polo="ativo"]')
        if (text := _normalized_text(node.get_text(" "))) is not None
    ]
    record["polo_passivo"] = [
        text
        for node in soup.select('[data-polo="passivo"]')
        if (text := _normalized_text(node.get_text(" "))) is not None
    ]
    movements: list[dict[str, str | None]] = []
    for row in soup.select("#movimentacoes tbody tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) >= 2:
            movements.append(
                {
                    "data": _normalized_text(cells[0].get_text(" ")),
                    "descricao": _normalized_text(cells[1].get_text(" ")),
                }
            )
    record["movimentacoes"] = movements
    return record


__all__ = [
    "TRF4_DEPLOYMENTS",
    "TRF4Deployment",
    "fetch_trf4_detail",
    "parse_trf4_detail",
]
