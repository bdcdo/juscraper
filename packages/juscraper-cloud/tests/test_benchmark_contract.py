from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from typing import Any
from types import ModuleType

import pytest


BENCHMARK_PATH = Path(__file__).parents[3] / "experiments" / "juscraper_cloud" / "benchmark.py"
SPEC = importlib.util.spec_from_file_location("juscraper_cloud_benchmark", BENCHMARK_PATH)
assert SPEC is not None and SPEC.loader is not None
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


def test_hash_is_deterministic_keyed_and_does_not_contain_cnj() -> None:
    cnj = "5000123-45.2024.4.02.5101"

    first = benchmark.hash_cnj(cnj, b"research-secret")
    second = benchmark.hash_cnj(cnj, b"research-secret")

    assert first == second
    assert first != benchmark.hash_cnj(cnj, b"different-secret")
    assert len(first) == 64
    assert cnj not in first
    assert "50001234520244025101" not in first


def test_run_cases_writes_only_the_public_jsonl_schema_and_redacts_failures(tmp_path: Path) -> None:
    cnj = "5000123-45.2024.4.02.5101"
    secret = "user:password@example.invalid/token-value"
    response_body = "<html>private response body</html>"
    cases = [
        benchmark.BenchmarkCase("trf2", "rj", cnj),
        benchmark.BenchmarkCase("trf4", "rs", "5000456-78.2024.4.04.7100"),
    ]

    def execute(case: Any) -> Any:
        if case.court == "trf2":
            return response_body
        raise RuntimeError(f"request failed for {cnj}: {secret}; body={response_body}")

    output = tmp_path / "results.jsonl"
    sleeps: list[float] = []
    records = benchmark.run_cases(
        cases,
        execute,
        output,
        hash_key=b"research-secret",
        cost_metadata={"request_cost": 0.012, "billable_seconds": 3},
        clock=iter([10.0, 10.25, 20.0, 20.75]).__next__,
        sleeper=sleeps.append,
    )

    lines = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert lines == records
    assert set(lines[0]) == {
        "court",
        "deployment",
        "cnj_hash",
        "success",
        "elapsed_seconds",
        "error_category",
        "cost_metadata",
    }
    assert lines[0]["success"] is True
    assert lines[0]["error_category"] is None
    assert lines[0]["elapsed_seconds"] == 0.25
    assert lines[1]["success"] is False
    assert lines[1]["error_category"] == "unexpected_error"
    assert sleeps == [1.0]
    serialized = output.read_text(encoding="utf-8")
    for forbidden in (cnj, "50001234520244025101", secret, "password", "token-value", response_body, "RuntimeError"):
        assert forbidden not in serialized


def test_cost_metadata_rejects_strings_that_could_carry_secrets(tmp_path: Path) -> None:
    case = benchmark.BenchmarkCase("tjsp", "proxy", "1000149-71.2024.8.26.0346")

    with pytest.raises(ValueError, match="numeric"):
        benchmark.run_cases(
            [case],
            lambda _: object(),
            tmp_path / "result.jsonl",
            hash_key=b"research-secret",
            cost_metadata={"request_cost": "secret vendor name"},
        )


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            benchmark.BenchmarkCase("user:password@example.invalid", "proxy", "10001497120248260346"),
            id="secret-in-court",
        ),
        pytest.param(
            benchmark.BenchmarkCase("trf2", "private-provider-name", "50001234520244025101"),
            id="provider-in-deployment",
        ),
    ],
)
def test_case_dimensions_are_allowlisted_before_output_is_created(case: Any, tmp_path: Path) -> None:
    output = tmp_path / "result.jsonl"

    with pytest.raises(ValueError, match="court or deployment"):
        benchmark.run_cases([case], lambda _: object(), output, hash_key=b"research-secret")

    assert not output.exists()


def test_cost_metadata_keys_are_allowlisted_to_prevent_provider_names(tmp_path: Path) -> None:
    output = tmp_path / "result.jsonl"
    case = benchmark.BenchmarkCase("tjsp", "proxy", "10001497120248260346")

    with pytest.raises(ValueError, match="keys"):
        benchmark.run_cases(
            [case],
            lambda _: object(),
            output,
            hash_key=b"research-secret",
            cost_metadata={"private_provider_name": 12.3},
        )

    assert not output.exists()


def test_dotted_provider_factory_constructs_private_provider_without_serializing_its_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_module = ModuleType("private_research_adapter")
    expected = object()
    private_module.make_provider = lambda: expected  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, private_module.__name__, private_module)

    result = benchmark.build_browser_provider(
        {"JUSCRAPER_BROWSER_PROVIDER_FACTORY": "private_research_adapter.make_provider"}
    )

    assert result is expected


def test_trf2_benchmark_measures_download_without_calling_unavailable_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    class Client:
        def cpopg_download(self, cnj: str) -> list[str]:
            calls.append(("download", cnj))
            return ["<html>download succeeded</html>"]

        def cpopg(self, cnj: str) -> Any:
            raise AssertionError(f"parser must not be called for {cnj}")

    monkeypatch.setattr(benchmark, "scraper", lambda *args, **kwargs: Client())
    case = benchmark.BenchmarkCase("trf2", "rj", "50001234520244025101")
    result = benchmark._build_executor(None, object())(case)

    assert result == ["<html>download succeeded</html>"]
    assert calls == [("download", "50001234520244025101")]


def test_run_cases_applies_configurable_delay_only_between_cases(tmp_path: Path) -> None:
    cases = [benchmark.BenchmarkCase("trf2", "rj", f"5000000002024402500{index}") for index in range(3)]
    sleeps: list[float] = []

    benchmark.run_cases(
        cases,
        lambda _: object(),
        tmp_path / "results.jsonl",
        hash_key=b"research-secret",
        inter_case_delay=1.5,
        sleeper=sleeps.append,
    )

    assert sleeps == [1.5, 1.5]


def test_run_cases_rejects_an_aggressive_inter_case_delay_before_creating_output(tmp_path: Path) -> None:
    output = tmp_path / "results.jsonl"
    case = benchmark.BenchmarkCase("trf2", "rj", "50000000020244025001")

    with pytest.raises(ValueError, match=r"at least 1.0"):
        benchmark.run_cases(
            [case],
            lambda _: object(),
            output,
            hash_key=b"research-secret",
            inter_case_delay=0.5,
        )

    assert not output.exists()


def _record(court: str, deployment: str, success: bool) -> dict[str, Any]:
    return {
        "court": court,
        "deployment": deployment,
        "cnj_hash": "a" * 64,
        "success": success,
        "elapsed_seconds": 0.1,
        "error_category": None if success else "remote_transport",
    }


def _passing_browser_records() -> list[dict[str, Any]]:
    records = [_record("trf2", "rj" if index < 5 else "es", index < 9) for index in range(10)]
    records += [_record("trf4", "pr" if index < 5 else "rs", index < 9) for index in range(10)]
    return records


def test_proxy_threshold_accepts_nine_of_ten_and_rejects_eight_of_ten() -> None:
    passing = _passing_browser_records() + [_record("tjsp", "proxy", index < 9) for index in range(10)]
    benchmark.assert_thresholds(passing)

    failing = _passing_browser_records() + [_record("tjsp", "proxy", index < 8) for index in range(10)]
    with pytest.raises(benchmark.BenchmarkThresholdError, match="proxy"):
        benchmark.assert_thresholds(failing)


@pytest.mark.parametrize("count", [0, 1, 9])
def test_proxy_threshold_requires_a_present_cohort_of_at_least_ten(count: int) -> None:
    records = _passing_browser_records() + [_record("tjsp", "proxy", True) for _ in range(count)]

    with pytest.raises(benchmark.BenchmarkThresholdError, match="proxy cohort"):
        benchmark.assert_thresholds(records)


def test_browser_threshold_aggregates_mixed_deployments_by_court() -> None:
    records = _passing_browser_records() + [_record("tjsp", "proxy", True) for _ in range(10)]

    benchmark.assert_thresholds(records)


def test_browser_threshold_rejects_eight_of_ten_aggregated_by_court() -> None:
    records = _passing_browser_records() + [_record("tjsp", "proxy", True) for _ in range(10)]
    records[8]["success"] = False

    with pytest.raises(benchmark.BenchmarkThresholdError, match="browser court cohort success rate"):
        benchmark.assert_thresholds(records)


def test_browser_threshold_rejects_fewer_than_ten_observations_per_court() -> None:
    records = [_record("tjsp", "proxy", True) for _ in range(10)]
    records += [_record("trf2", "rj" if index < 5 else "es", True) for index in range(9)]
    records += [_record("trf4", "pr", True) for _ in range(10)]

    with pytest.raises(benchmark.BenchmarkThresholdError, match="browser court cohort requires at least 10"):
        benchmark.assert_thresholds(records)


def test_required_browser_court_cannot_be_missing() -> None:
    records = [_record("tjsp", "proxy", True) for _ in range(10)]
    records += [_record("trf2", "rj", True) for _ in range(10)]

    with pytest.raises(benchmark.BenchmarkThresholdError, match="required browser court cohort is missing"):
        benchmark.assert_thresholds(records)


def test_any_systematic_zero_success_court_fails_even_when_other_cohorts_pass() -> None:
    records = [_record("tjsp", "proxy", True) for _ in range(10)]
    records += [_record("trf2", "rj", True) for _ in range(10)]
    records += [_record("trf4", "sc" if index < 5 else "rs", False) for index in range(10)]

    with pytest.raises(benchmark.BenchmarkThresholdError, match="browser court cohort has zero successes"):
        benchmark.assert_thresholds(records)


@pytest.mark.parametrize(
    "record,secret",
    [
        pytest.param(_record("user:password@example.invalid", "proxy", True), "password", id="court"),
        pytest.param(_record("trf2", "private-provider-name", True), "private-provider-name", id="deployment"),
    ],
)
def test_threshold_validation_never_echoes_untrusted_dimensions(record: dict[str, Any], secret: str) -> None:
    with pytest.raises(benchmark.BenchmarkThresholdError) as captured:
        benchmark.assert_thresholds([record])

    message = str(captured.value)
    assert message == "benchmark record dimensions are invalid"
    assert secret not in message
