from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import ParseResult, parse_qsl, quote, urlparse, urlunparse

import requests

from .errors import ProxyConfigurationError


@dataclass(frozen=True, repr=False)
class ProxyRoute:
    url: str
    ca_bundle: str | Path | None = None
    _parsed_url: ParseResult = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        parsed = urlparse(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ProxyConfigurationError("Proxy URL must use http or https and include a hostname")

        if self.ca_bundle is not None:
            ca_bundle = Path(self.ca_bundle)
            if not ca_bundle.is_file():
                raise ProxyConfigurationError(f"CA bundle does not exist: {ca_bundle}")

        object.__setattr__(self, "_parsed_url", parsed)

    @classmethod
    def from_env(cls) -> ProxyRoute | None:
        url = os.getenv("JUSCRAPER_PROXY_URL")
        if not url:
            return None
        ca_bundle = os.getenv("JUSCRAPER_PROXY_CA_BUNDLE")
        return cls(url, Path(ca_bundle) if ca_bundle else None)

    def apply(self, session: requests.Session) -> None:
        session.proxies.update({"http": self.url, "https": self.url})
        if self.ca_bundle is not None:
            session.verify = str(self.ca_bundle)

    def __repr__(self) -> str:
        parsed = self._parsed_url
        hostname = parsed.hostname or ""
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        netloc = hostname
        if parsed.port is not None:
            netloc = f"{netloc}:{parsed.port}"
        query = "&".join(f"{quote(key, safe='')}=***" for key, _ in parse_qsl(parsed.query, keep_blank_values=True))
        redacted_url = urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, query, parsed.fragment))
        return f"ProxyRoute(url={redacted_url!r}, ca_bundle={self.ca_bundle!r})"
