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
    records = benchmark.run_cases(
        cases,
        execute,
        output,
        hash_key=b"research-secret",
        cost_metadata={"request_cost": 0.012, "billable_seconds": 3},
        clock=iter([10.0, 10.25, 20.0, 20.75]).__next__,
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


def _record(court: str, deployment: str, success: bool) -> dict[str, Any]:
    return {
        "court": court,
        "deployment": deployment,
        "cnj_hash": "a" * 64,
        "success": success,
        "elapsed_seconds": 0.1,
        "error_category": None if success else "remote_transport",
    }


def test_proxy_threshold_accepts_nine_of_ten_and_rejects_eight_of_ten() -> None:
    passing = [_record("tjsp", "proxy", index < 9) for index in range(10)]
    benchmark.assert_thresholds(passing)

    failing = [_record("tjsp", "proxy", index < 8) for index in range(10)]
    with pytest.raises(benchmark.BenchmarkThresholdError, match="proxy"):
        benchmark.assert_thresholds(failing)


def test_browser_threshold_is_nine_of_ten_for_each_court_deployment() -> None:
    records = [_record("trf2", "rj", index < 9) for index in range(10)]
    records += [_record("trf4", "rs", index < 8) for index in range(10)]

    with pytest.raises(benchmark.BenchmarkThresholdError, match="trf4/rs"):
        benchmark.assert_thresholds(records)

    records[-2]["success"] = True
    benchmark.assert_thresholds(records)


def test_browser_threshold_rejects_fewer_than_ten_observations() -> None:
    records = [_record("trf2", "rj", True) for _ in range(9)]

    with pytest.raises(benchmark.BenchmarkThresholdError, match=r"at least 10.*trf2/rj"):
        benchmark.assert_thresholds(records)


def test_any_systematic_zero_success_group_fails_even_when_other_groups_pass() -> None:
    records = [_record("trf2", "rj", True) for _ in range(10)]
    records += [_record("trf4", "sc", False) for _ in range(10)]

    with pytest.raises(benchmark.BenchmarkThresholdError, match=r"zero successes.*trf4/sc"):
        benchmark.assert_thresholds(records)
