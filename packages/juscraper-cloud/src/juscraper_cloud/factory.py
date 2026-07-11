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
    if browser is not None:
        raise NotImplementedError("browser providers are not supported for upstream scrapers yet")

    resolved_route = route if route is not None else ProxyRoute.from_env()
    if resolved_route is not None and sigla.lower() in {"trf2", "trf4"}:
        raise ProxyConfigurationError(f"{sigla.lower()} is reserved for a future browser-only scraper")

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
