"""Contrato compartilhado pelos clientes browser de TRF2 e TRF4."""

from __future__ import annotations

import time
from typing import Any, cast

import pandas as pd
from pydantic import BaseModel, ConfigDict, field_validator

from juscraper.utils.cnj import clean_cnj, format_cnj

from .browser import BrowserProvider
from .trf2 import TRF2Deployment, TRF2_DEPLOYMENTS
from .trf4 import TRF4Deployment, TRF4_DEPLOYMENTS


class InputCpopgCloud(BaseModel):
    """Entrada local para consultas browser de primeiro grau."""

    model_config = ConfigDict(extra="forbid")

    id_cnj: str | list[str]

    @field_validator("id_cnj")
    @classmethod
    def validate_cnjs(cls, value: str | list[str]) -> str | list[str]:
        values = value if isinstance(value, list) else [value]
        if not values:
            raise ValueError("id_cnj must contain at least one CNJ")
        for cnj in values:
            format_cnj(cnj)
        return value


class _TRFCloudScraper:
    """Validação, batching e alinhamento comuns aos transportes browser."""

    def __init__(self, browser: BrowserProvider, sleep_time: float = 1.0) -> None:
        if sleep_time < 0:
            raise ValueError("sleep_time must be non-negative")
        self.browser = browser
        self.sleep_time = sleep_time

    def _coerce_id_cnj(self, id_cnj: str | list[str], **kwargs: Any) -> list[str]:
        validated = InputCpopgCloud(id_cnj=id_cnj, **kwargs).id_cnj
        values = validated if isinstance(validated, list) else [validated]
        return [clean_cnj(value) for value in values]

    def _fetch_one(self, page: Any, formatted_cnj: str) -> str | None:
        raise NotImplementedError

    def _parse_one(self, html: str) -> dict[str, Any]:
        raise NotImplementedError

    def _download_clean(self, cnjs: list[str]) -> list[str | None]:
        results: list[str | None] = []
        for index, cnj in enumerate(cnjs):
            with self.browser.open_page() as page:
                results.append(self._fetch_one(page, format_cnj(cnj)))
            if index + 1 < len(cnjs) and self.sleep_time:
                time.sleep(self.sleep_time)
        return results

    def cpopg_download(self, id_cnj: str | list[str], **kwargs: Any) -> list[str | None]:
        """Baixa HTMLs alinhados à ordem dos CNJs informados."""
        return self._download_clean(self._coerce_id_cnj(id_cnj, **kwargs))

    def cpopg_parse(self, htmls: list[str | None], id_cnj_list: list[str]) -> pd.DataFrame:
        """Converte HTMLs alinhados em uma linha por processo."""
        if len(htmls) != len(id_cnj_list):
            raise ValueError(f"htmls and id_cnj_list must have the same length ({len(htmls)} != {len(id_cnj_list)})")
        rows: list[dict[str, Any]] = []
        for cnj, html in zip(id_cnj_list, htmls, strict=True):
            record = {} if html is None else self._parse_one(html)
            record["id_cnj"] = cnj
            rows.append(record)
        return pd.DataFrame(rows)

    def cpopg(self, id_cnj: str | list[str], **kwargs: Any) -> pd.DataFrame:
        """Executa download e parsing em lote para um ou mais CNJs."""
        cnjs = self._coerce_id_cnj(id_cnj, **kwargs)
        return self.cpopg_parse(self._download_clean(cnjs), cnjs)


class TRF2CloudScraper(_TRFCloudScraper):
    """Cliente browser das implantações eproc do TRF2."""

    def __init__(self, browser: BrowserProvider, deployment: str, sleep_time: float = 1.0) -> None:
        super().__init__(browser, sleep_time)
        try:
            self.deployment: TRF2Deployment = TRF2_DEPLOYMENTS[deployment.lower()]
        except KeyError:
            raise ValueError(f"unknown TRF2 deployment: {deployment!r}") from None

    def _fetch_one(self, page: Any, formatted_cnj: str) -> str | None:
        from .trf2 import fetch_trf2_detail

        return fetch_trf2_detail(page, self.deployment, formatted_cnj)

    def _parse_one(self, html: str) -> dict[str, Any]:
        from juscraper.courts.trf6.parse import parse_detail

        return cast(dict[str, Any], parse_detail(html))


class TRF4CloudScraper(_TRFCloudScraper):
    """Cliente browser das origens do portal unificado do TRF4."""

    def __init__(self, browser: BrowserProvider, deployment: str, sleep_time: float = 1.0) -> None:
        super().__init__(browser, sleep_time)
        try:
            self.deployment: TRF4Deployment = TRF4_DEPLOYMENTS[deployment.lower()]
        except KeyError:
            raise ValueError(f"unknown TRF4 deployment: {deployment!r}") from None

    def _fetch_one(self, page: Any, formatted_cnj: str) -> str | None:
        from .trf4 import fetch_trf4_detail

        return fetch_trf4_detail(page, self.deployment, formatted_cnj)

    def _parse_one(self, html: str) -> dict[str, Any]:
        from .trf4 import parse_trf4_detail

        return parse_trf4_detail(html)


__all__ = ["InputCpopgCloud", "TRF2CloudScraper", "TRF4CloudScraper"]
