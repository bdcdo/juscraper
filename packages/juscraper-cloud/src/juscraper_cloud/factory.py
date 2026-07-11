from __future__ import annotations

from typing import Any

import requests

from .browser import BrowserProvider
from .errors import ProxyConfigurationError
from .network import ProxyRoute


def scraper(
    sigla: str,
    *,
    route: ProxyRoute | None = None,
    browser: BrowserProvider | None = None,
    **kwargs: Any,
) -> Any:
    normalized_sigla = sigla.lower()
    resolved_route = route if route is not None else ProxyRoute.from_env()
    if resolved_route is not None and normalized_sigla in {"trf2", "trf4"}:
        raise ProxyConfigurationError(f"{normalized_sigla} is a browser-only scraper and does not accept a proxy route")

    if normalized_sigla in {"trf2", "trf4"}:
        deployment = kwargs.pop("deployment", None)
        if browser is None:
            raise ValueError(f"{normalized_sigla} requires a browser provider")
        if deployment is None:
            raise ValueError(f"{normalized_sigla} requires an explicit deployment")
        if normalized_sigla == "trf2":
            from .trf import TRF2CloudScraper

            return TRF2CloudScraper(browser, deployment, **kwargs)
        from .trf import TRF4CloudScraper

        return TRF4CloudScraper(browser, deployment, **kwargs)

    if browser is not None:
        raise NotImplementedError("browser providers are not supported for upstream scrapers yet")

    from juscraper import scraper as upstream_scraper

    result = upstream_scraper(sigla, **kwargs)
    if resolved_route is not None:
        session = getattr(result, "session", None)
        if not isinstance(session, requests.Session):
            raise ProxyConfigurationError(
                f"Cannot apply proxy route: scraper {sigla!r} does not expose a requests.Session as 'session'"
            )
        resolved_route.apply(session)

    return result
