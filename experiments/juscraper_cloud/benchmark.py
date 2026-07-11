#!/usr/bin/env python3
"""Reproducible, privacy-preserving benchmark for juscraper-cloud transports."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import importlib
import json
import math
import os
import sys
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, NamedTuple, cast

from juscraper_cloud import (
    BrowserChallengeError,
    CdpPlaywrightProvider,
    PlaywrightWsProvider,
    ProxyConfigurationError,
    ProxyRoute,
    RemoteQuotaError,
    RemoteTransportError,
    scraper,
)


PROXY_DEPLOYMENT = "proxy"
MIN_COHORT_CASES = 10
DEFAULT_INTER_CASE_DELAY = 1.0
ALLOWED_COURTS = frozenset(
    {
        "tjac",
        "tjal",
        "tjam",
        "tjap",
        "tjba",
        "tjce",
        "tjdft",
        "tjes",
        "tjgo",
        "tjmg",
        "tjms",
        "tjmt",
        "tjpa",
        "tjpb",
        "tjpe",
        "tjpi",
        "tjpr",
        "tjrj",
        "tjrn",
        "tjro",
        "tjrr",
        "tjrs",
        "tjsc",
        "tjsp",
        "tjto",
        "trf1",
        "trf2",
        "trf3",
        "trf4",
        "trf5",
    }
)
BROWSER_DEPLOYMENTS = {"trf2": frozenset({"rj", "es"}), "trf4": frozenset({"pr", "sc", "rs"})}
REQUIRED_BROWSER_COURTS = frozenset(BROWSER_DEPLOYMENTS)
ALLOWED_COST_KEYS = frozenset({"request_cost", "billable_seconds", "units"})
PUBLIC_FIELDS = (
    "court",
    "deployment",
    "cnj_hash",
    "success",
    "elapsed_seconds",
    "error_category",
)


class BenchmarkCase(NamedTuple):
    """One private benchmark input. The CNJ is never serialized to output."""

    court: str
    deployment: str
    cnj: str


class BenchmarkThresholdError(RuntimeError):
    """Raised when benchmark success criteria are not met."""


def hash_cnj(cnj: str, key: bytes) -> str:
    """Return a deterministic, keyed digest without retaining the raw CNJ."""
    if not key:
        raise ValueError("The benchmark hash key must not be empty")
    normalized = "".join(character for character in cnj if character.isdigit())
    return hmac.new(key, normalized.encode("ascii"), hashlib.sha256).hexdigest()


def run_cases(
    cases: Iterable[BenchmarkCase],
    execute: Callable[[BenchmarkCase], Any],
    output: str | Path,
    *,
    hash_key: bytes,
    cost_metadata: Mapping[str, int | float] | None = None,
    clock: Callable[[], float] = time.perf_counter,
    inter_case_delay: float = DEFAULT_INTER_CASE_DELAY,
    sleeper: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    """Execute cases sequentially and persist only the public JSONL contract."""
    safe_cost = _validate_cost_metadata(cost_metadata)
    safe_cases = [_validate_case(case) for case in cases]
    _validate_inter_case_delay(inter_case_delay)
    records: list[dict[str, Any]] = []
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as stream:
        for index, case in enumerate(safe_cases):
            started = clock()
            success = False
            error_category: str | None = None
            try:
                result = execute(case)
                success = _has_result(result)
                if not success:
                    error_category = "no_result"
            except Exception as exc:  # benchmark failures become closed categories
                error_category = _error_category(exc)
            elapsed = max(0.0, clock() - started)
            record: dict[str, Any] = {
                "court": case.court.lower(),
                "deployment": case.deployment.lower(),
                "cnj_hash": hash_cnj(case.cnj, hash_key),
                "success": success,
                "elapsed_seconds": round(elapsed, 6),
                "error_category": error_category,
            }
            if safe_cost is not None:
                record["cost_metadata"] = safe_cost
            stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            stream.flush()
            records.append(record)
            if index + 1 < len(safe_cases):
                sleeper(inter_case_delay)
    return records


def assert_thresholds(records: Iterable[Mapping[str, Any]]) -> None:
    """Require complete proxy and per-court browser cohorts with 90% success."""
    proxy_results: list[bool] = []
    proxy_by_court: dict[str, list[bool]] = defaultdict(list)
    browser_by_court: dict[str, list[bool]] = defaultdict(list)
    for record in records:
        court, deployment, success = _validate_threshold_record(record)
        if deployment == PROXY_DEPLOYMENT:
            proxy_results.append(success)
            proxy_by_court[court].append(success)
        else:
            browser_by_court[court].append(success)

    if not proxy_results:
        raise BenchmarkThresholdError("proxy cohort is required")
    if len(proxy_results) < MIN_COHORT_CASES:
        raise BenchmarkThresholdError("proxy cohort requires at least 10 results")
    if any(not any(successes) for successes in proxy_by_court.values()):
        raise BenchmarkThresholdError("proxy court cohort has zero successes")
    if sum(proxy_results) / len(proxy_results) < 0.9:
        raise BenchmarkThresholdError("proxy cohort success rate is below 90%")

    for court in sorted(REQUIRED_BROWSER_COURTS):
        successes = browser_by_court.get(court)
        if not successes:
            raise BenchmarkThresholdError("required browser court cohort is missing")
        if len(successes) < MIN_COHORT_CASES:
            raise BenchmarkThresholdError("browser court cohort requires at least 10 results")
        if not any(successes):
            raise BenchmarkThresholdError("browser court cohort has zero successes")
        if sum(successes) / len(successes) < 0.9:
            raise BenchmarkThresholdError("browser court cohort success rate is below 90%")


def load_cases(path: str | Path) -> list[BenchmarkCase]:
    """Load private JSONL inputs without echoing invalid content in errors."""
    cases: list[BenchmarkCase] = []
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            try:
                item = json.loads(line)
                case = _validate_case(BenchmarkCase(str(item["court"]), str(item["deployment"]), str(item["cnj"])))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                raise ValueError(f"Invalid benchmark case on line {line_number}") from None
            cases.append(case)
    return cases


def build_browser_provider(env: Mapping[str, str] = os.environ) -> Any | None:
    """Build a neutral browser provider from environment configuration."""
    factory_path = env.get("JUSCRAPER_BROWSER_PROVIDER_FACTORY")
    ws_endpoint = env.get("JUSCRAPER_BROWSER_WS_ENDPOINT")
    cdp_endpoint = env.get("JUSCRAPER_BROWSER_CDP_ENDPOINT")
    configured = [value for value in (factory_path, ws_endpoint, cdp_endpoint) if value]
    if len(configured) > 1:
        raise ValueError("Configure only one browser provider source")
    if factory_path:
        return _load_provider_factory(factory_path)()

    headers = _load_secret_headers(env.get("JUSCRAPER_BROWSER_HEADERS_JSON"))
    if ws_endpoint:
        return PlaywrightWsProvider(ws_endpoint, headers=headers)
    if cdp_endpoint:
        return CdpPlaywrightProvider(cdp_endpoint, headers=headers)
    return None


def _load_provider_factory(path: str) -> Callable[[], Any]:
    module_name, separator, attribute = path.rpartition(".")
    if not separator or not module_name or not attribute:
        raise ValueError("The provider factory must be a dotted import path")
    factory = getattr(importlib.import_module(module_name), attribute)
    if not callable(factory):
        raise TypeError("The configured provider factory is not callable")
    return cast(Callable[[], Any], factory)


def _load_secret_headers(raw: str | None) -> Mapping[str, str] | None:
    if raw is None:
        return None
    value = json.loads(raw)
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise ValueError("Browser headers must be a JSON object of strings")
    return value


def _load_cost_metadata(raw: str | None) -> Mapping[str, int | float] | None:
    if raw is None:
        return None
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Cost metadata must be a JSON object")
    return _validate_cost_metadata(value)


def _validate_cost_metadata(metadata: Mapping[str, Any] | None) -> dict[str, int | float] | None:
    if metadata is None:
        return None
    safe: dict[str, int | float] = {}
    for key, value in metadata.items():
        if key not in ALLOWED_COST_KEYS:
            raise ValueError("Cost metadata keys must use the public allowlist")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("Cost metadata values must be finite numeric scalars")
        safe[key] = value
    return safe


def _validate_case(case: BenchmarkCase) -> BenchmarkCase:
    court = case.court.lower()
    deployment = case.deployment.lower()
    valid_browser_deployments = BROWSER_DEPLOYMENTS.get(court, frozenset())
    if court not in ALLOWED_COURTS or (deployment != PROXY_DEPLOYMENT and deployment not in valid_browser_deployments):
        raise ValueError("Benchmark court or deployment is not allowed")
    return BenchmarkCase(court, deployment, case.cnj)


def _validate_inter_case_delay(delay: float) -> None:
    if isinstance(delay, bool) or not isinstance(delay, (int, float)) or not math.isfinite(delay) or delay < 1.0:
        raise ValueError("Inter-case delay must be at least 1.0 second")


def _validate_threshold_record(record: Mapping[str, Any]) -> tuple[str, str, bool]:
    try:
        court = record["court"]
        deployment = record["deployment"]
        success = record["success"]
        if not isinstance(court, str) or not isinstance(deployment, str) or not isinstance(success, bool):
            raise ValueError
        safe_case = _validate_case(BenchmarkCase(court, deployment, ""))
    except Exception:
        raise BenchmarkThresholdError("benchmark record dimensions are invalid") from None
    return safe_case.court, safe_case.deployment, success


def _has_result(result: Any) -> bool:
    if result is None:
        return False
    try:
        return len(result) > 0
    except TypeError:
        return True


def _error_category(exc: BaseException) -> str:
    if isinstance(exc, BrowserChallengeError):
        return "browser_challenge"
    if isinstance(exc, RemoteQuotaError):
        return "remote_quota"
    if isinstance(exc, RemoteTransportError):
        return "remote_transport"
    if isinstance(exc, ProxyConfigurationError):
        return "configuration"
    if isinstance(exc, TimeoutError) or type(exc).__name__ == "TimeoutError":
        return "timeout"
    return "unexpected_error"


def _build_executor(route: ProxyRoute | None, browser: Any | None) -> Callable[[BenchmarkCase], Any]:
    def execute(case: BenchmarkCase) -> Any:
        if case.deployment.lower() == PROXY_DEPLOYMENT:
            if route is None:
                raise ProxyConfigurationError("Proxy benchmark requires a configured route")
            client = scraper(case.court, route=route)
        else:
            if browser is None:
                raise ProxyConfigurationError("Browser benchmark requires a configured provider")
            client = scraper(case.court, browser=browser, deployment=case.deployment)
        return client.cpopg(case.cnj)

    return execute


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a privacy-preserving juscraper-cloud benchmark")
    parser.add_argument("--cases", required=True, help="Private input JSONL path")
    parser.add_argument("--output", required=True, help="Public result JSONL path")
    args = parser.parse_args(argv)

    hash_key = os.environ.get("JUSCRAPER_BENCHMARK_HASH_KEY")
    if not hash_key:
        raise ValueError("JUSCRAPER_BENCHMARK_HASH_KEY is required")
    cases = load_cases(args.cases)
    route = ProxyRoute.from_env()
    browser = build_browser_provider()
    records = run_cases(
        cases,
        _build_executor(route, browser),
        args.output,
        hash_key=hash_key.encode("utf-8"),
        cost_metadata=_load_cost_metadata(os.environ.get("JUSCRAPER_BENCHMARK_COST_JSON")),
        inter_case_delay=float(os.environ.get("JUSCRAPER_BENCHMARK_DELAY_SECONDS", DEFAULT_INTER_CASE_DELAY)),
    )
    assert_thresholds(records)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BenchmarkThresholdError as exc:
        print(f"Benchmark threshold failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except Exception:
        print("Benchmark configuration or execution failed; inspect private inputs locally.", file=sys.stderr)
        raise SystemExit(2) from None
