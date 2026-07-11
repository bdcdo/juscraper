from __future__ import annotations

from contextlib import contextmanager
import math
from pathlib import Path
from typing import Any
from unittest.mock import ANY

import pandas as pd
import pytest
from pydantic import ValidationError

import juscraper
from juscraper_cloud.factory import scraper
from juscraper_cloud.trf import InputCpopgCloud, TRF2CloudScraper, TRF4CloudScraper


TRF2_FIXTURE_REQUIRED = "sanitized TRF2 deployment fixtures are required before parsing is available"


class FakeProvider:
    def __init__(self) -> None:
        self.open_calls = 0

    @contextmanager
    def open_page(self):  # type: ignore[no-untyped-def]
        self.open_calls += 1
        yield object()


@pytest.mark.parametrize("sigla,deployment", [("trf2", "rj"), ("trf4", "rs")])
def test_factory_builds_browser_scrapers(sigla: str, deployment: str) -> None:
    provider = FakeProvider()

    result = scraper(sigla, browser=provider, deployment=deployment, sleep_time=1.25)

    assert isinstance(result, TRF2CloudScraper if sigla == "trf2" else TRF4CloudScraper)
    assert result.browser is provider
    assert result.deployment.name == deployment
    assert result.sleep_time == 1.25


@pytest.mark.parametrize("sleep_time", [0, 0.25, 0.5, True, math.nan, math.inf, "1.0", None])
def test_browser_scrapers_reject_invalid_or_aggressive_sleep_time(sleep_time: Any) -> None:
    with pytest.raises(ValueError, match=r"finite real number.*at least 1\.0"):
        TRF4CloudScraper(FakeProvider(), "rs", sleep_time=sleep_time)


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"deployment": "rj"}, "browser"),
        ({"browser": FakeProvider()}, "deployment"),
        ({"browser": FakeProvider(), "deployment": "mg"}, "deployment"),
    ],
)
def test_factory_requires_browser_and_allowed_explicit_deployment(kwargs: dict[str, Any], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        scraper("trf2", **kwargs)


def test_factory_preserves_upstream_delegation(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = object()
    calls: list[tuple[str, dict[str, Any]]] = []

    def upstream(sigla: str, **kwargs: Any) -> object:
        calls.append((sigla, kwargs))
        return expected

    monkeypatch.setattr(juscraper, "scraper", upstream)

    assert scraper("tjsp", download_path="downloads", deployment="upstream-value") is expected
    assert calls == [("tjsp", {"download_path": "downloads", "deployment": "upstream-value"})]


def test_package_local_input_schema_forbids_unknown_fields_and_invalid_types() -> None:
    with pytest.raises(ValidationError):
        InputCpopgCloud(id_cnj=123)
    with pytest.raises(ValidationError) as captured:
        InputCpopgCloud(id_cnj="50001234520244047000", desconhecido=True)

    assert captured.value.errors()[0]["type"] == "extra_forbidden"


def test_trf2_download_formats_single_cnj_and_preserves_alignment(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider()
    scraper_obj = TRF2CloudScraper(provider, "rj", sleep_time=1.0)
    calls: list[tuple[Any, str, str]] = []

    def fake_fetch(page: Any, deployment: Any, cnj: str) -> str:
        calls.append((page, deployment.name, cnj))
        return f"<html>{cnj}</html>"

    monkeypatch.setattr("juscraper_cloud.trf2.fetch_trf2_detail", fake_fetch)

    result = scraper_obj.cpopg_download("50001234520244025101")

    assert result == ["<html>5000123-45.2024.4.02.5101</html>"]
    assert calls == [(ANY, "rj", "5000123-45.2024.4.02.5101")]
    assert provider.open_calls == 1


def test_trf4_download_sleeps_between_list_items(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider()
    scraper_obj = TRF4CloudScraper(provider, "pr", sleep_time=1.5)
    sleeps: list[float] = []
    responses = iter(["<html>primeiro</html>", None])
    monkeypatch.setattr("juscraper_cloud.trf4.fetch_trf4_detail", lambda *_: next(responses))
    monkeypatch.setattr("juscraper_cloud.trf.time.sleep", sleeps.append)

    result = scraper_obj.cpopg_download(["50001234520244047000", "50004567820244047000"])

    assert result == ["<html>primeiro</html>", None]
    assert provider.open_calls == 2
    assert sleeps == [1.5]


def test_cpopg_parse_returns_one_aligned_row_per_process_including_none() -> None:
    scraper_obj = TRF4CloudScraper(FakeProvider(), "sc")
    html = (Path(__file__).parent / "samples" / "trf4" / "cpopg" / "detail_normal.html").read_text()

    frame = scraper_obj.cpopg_parse([html, None], ["50001234520244047000", "50004567820244047000"])

    assert isinstance(frame, pd.DataFrame)
    assert len(frame) == 2
    assert frame["id_cnj"].tolist() == ["50001234520244047000", "50004567820244047000"]
    assert frame.loc[0, "processo"] == "5000123-45.2024.4.04.7000"
    assert pd.isna(frame.loc[1, "processo"])


def test_trf2_parser_fails_explicitly_until_deployment_fixtures_exist() -> None:
    with pytest.raises(NotImplementedError, match=TRF2_FIXTURE_REQUIRED):
        TRF2CloudScraper(FakeProvider(), "es").cpopg_parse(["<html></html>"], ["50001234520244025001"])


def test_trf2_high_level_cpopg_fails_before_downloading_until_parser_is_available() -> None:
    provider = FakeProvider()

    with pytest.raises(NotImplementedError, match=TRF2_FIXTURE_REQUIRED):
        TRF2CloudScraper(provider, "rj").cpopg("50001234520244025101")

    assert provider.open_calls == 0


def test_cpopg_validates_once_and_returns_dataframe(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper_obj = TRF4CloudScraper(FakeProvider(), "rs", sleep_time=1.0)
    html = (Path(__file__).parent / "samples" / "trf4" / "cpopg" / "detail_normal.html").read_text()
    monkeypatch.setattr("juscraper_cloud.trf4.fetch_trf4_detail", lambda *_: html)

    frame = scraper_obj.cpopg("50001234520244047100")

    assert frame["id_cnj"].tolist() == ["50001234520244047100"]
    assert frame["processo"].tolist() == ["5000123-45.2024.4.04.7000"]
