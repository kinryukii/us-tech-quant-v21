from __future__ import annotations

import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_104_random_asof_backtest_batch_runner.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_104_random_asof_backtest_batch_runner.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_104_random_asof_backtest_batch_runner.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"

OUT_BATCH = CONSOLIDATION / "V20_104_RANDOM_ASOF_BACKTEST_BATCH_RUNS.csv"
OUT_INPUT_AUDIT = CONSOLIDATION / "V20_104_RANDOM_ASOF_SNAPSHOT_INPUT_AUDIT.csv"
OUT_OUTCOME = CONSOLIDATION / "V20_104_RANDOM_ASOF_FORWARD_OUTCOME_MATRIX.csv"
OUT_BENCHMARK = CONSOLIDATION / "V20_104_RANDOM_ASOF_BENCHMARK_COMPARISON.csv"
OUT_PIT = CONSOLIDATION / "V20_104_RANDOM_ASOF_PIT_SAFETY_AUDIT.csv"
REPORT = READ_CENTER / "V20_104_RANDOM_ASOF_BACKTEST_BATCH_REPORT.md"

ACCEPTED_STATUSES = {
    "PASS_V20_104_RANDOM_ASOF_BACKTEST_BATCH_RUNNER",
    "PARTIAL_PASS_V20_104_RANDOM_ASOF_BACKTEST_BATCH_RUNNER_WITH_LIMITED_HISTORICAL_COVERAGE",
    "BLOCKED_V20_104_NO_PIT_SAFE_RANDOM_ASOF_INPUTS",
}
FORWARD_WINDOWS = {"5D", "10D", "20D", "60D", "120D"}


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_wrapper() -> None:
    command = (
        "$tokens=$null;$errors=$null;"
        f"[System.Management.Automation.Language.Parser]::ParseFile('{WRAPPER.as_posix()}', [ref]$tokens, [ref]$errors) > $null;"
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }"
    )
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command])
    assert_true(result.returncode == 0, f"PowerShell parser failed: {result.stdout}\n{result.stderr}")


def assert_safety(row: dict[str, str]) -> None:
    assert_true(row["research_only"] == "TRUE", f"research_only false: {row}")
    assert_true(row["official_promotion_allowed"] == "FALSE", f"promotion allowed: {row}")
    assert_true(row["official_recommendation_created"] == "FALSE", f"recommendation created: {row}")
    assert_true(row["weight_mutated"] == "FALSE", f"weight mutation claimed: {row}")
    assert_true(row["trade_action_created"] == "FALSE", f"trade action claimed: {row}")
    assert_true(row["broker_execution_supported"] == "FALSE", f"broker execution claimed: {row}")
    if "is_official_weight" in row:
        assert_true(row["is_official_weight"] == "FALSE", f"official weight claimed: {row}")
    if "dynamic_factor_weight_created" in row:
        assert_true(row["dynamic_factor_weight_created"] == "FALSE", f"dynamic weight claimed: {row}")
    if "v20_107_execution_status" in row:
        assert_true(row["v20_107_execution_status"] == "NOT_RUN", f"V20.107 executed: {row}")


def test_wrapper_runs_and_outputs_created() -> str:
    before = R5_REGISTRY.read_text(encoding="utf-8")
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    after = R5_REGISTRY.read_text(encoding="utf-8")
    assert_true(result.returncode == 0, f"wrapper failed: {result.stdout}\n{result.stderr}")
    assert_true(any(status in result.stdout for status in ACCEPTED_STATUSES), f"missing accepted status: {result.stdout}")
    assert_true("RANDOM_SEED=20104" in result.stdout, "random seed not recorded")
    assert_true("V20_107_EXECUTION_STATUS=NOT_RUN" in result.stdout, "V20.107 not preserved")
    assert_true("DYNAMIC_FACTOR_WEIGHT_CREATED=FALSE" in result.stdout, "dynamic weight safety missing")
    assert_true(before == after, "R5 active research base weights were mutated")
    for path in [OUT_BATCH, OUT_INPUT_AUDIT, OUT_OUTCOME, OUT_BENCHMARK, OUT_PIT, REPORT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")
    return result.stdout


def test_batch_runs_and_seed_are_deterministic() -> None:
    first_rows = read_csv(OUT_BATCH)
    first_dates = [row["as_of_date"] for row in first_rows]
    run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    second_rows = read_csv(OUT_BATCH)
    second_dates = [row["as_of_date"] for row in second_rows]
    assert_true(first_dates == second_dates, "deterministic random seed did not reproduce as-of sample")
    assert_true(first_rows, "batch rows empty")
    assert_true(all(row["random_seed"] == "20104" for row in second_rows), "seed not recorded on every row")
    assert_true(len(second_rows) >= 10 or len(second_rows) == 0, f"sample count below minimum without block: {len(second_rows)}")
    for row in second_rows:
        assert_safety(row)
        assert_true(set(row["forward_windows_requested"].split("|")) == FORWARD_WINDOWS, f"forward windows missing: {row}")
        assert_true(row["pit_safety_status"] == "PASS", f"PIT batch row failed: {row}")


def test_forward_outcomes_and_benchmarks_contract() -> None:
    outcome_rows = read_csv(OUT_OUTCOME)
    benchmark_rows = read_csv(OUT_BENCHMARK)
    assert_true(outcome_rows, "forward outcome matrix empty")
    assert_true(benchmark_rows, "benchmark comparison empty")
    assert_true(FORWARD_WINDOWS.issubset({row["forward_window"] for row in outcome_rows}), "forward windows not represented")
    assert_true({"SPY", "QQQ"}.issubset({row["benchmark_ticker"] for row in benchmark_rows}), "benchmark targets missing")
    for row in outcome_rows[:1000]:
        assert_safety(row)
        assert_true(row["candidate_rank"] == "UNRANKED", f"current rank leaked into historical rank: {row}")
        assert_true(row["candidate_score_source"] == "NO_HISTORICAL_RANK_OR_SCORE_USED", f"historical score fabricated: {row}")
        if row["outcome_available"] == "TRUE":
            assert_true(row["entry_price_asof"] and row["exit_price_forward"] and row["forward_return"], f"available outcome missing price/return: {row}")
            assert_true(row["pit_safe"] == "TRUE", f"available outcome not PIT safe: {row}")
        else:
            assert_true(row["missing_reason"], f"missing outcome lacks reason: {row}")
    for row in benchmark_rows[:1000]:
        assert_safety(row)
        if row["benchmark_data_available"] == "TRUE" and row["ticker_forward_return"]:
            assert_true(row["benchmark_forward_return"] != "" and row["alpha_vs_benchmark"] != "", f"benchmark row missing computed fields: {row}")
        elif row["benchmark_data_available"] != "TRUE":
            assert_true(row["benchmark_missing_reason"], f"missing benchmark lacks reason: {row}")


def test_pit_safety_audit_and_input_audit() -> None:
    pit_rows = read_csv(OUT_PIT)
    input_rows = read_csv(OUT_INPUT_AUDIT)
    assert_true(pit_rows, "PIT safety audit empty")
    assert_true(input_rows, "input audit empty")
    assert_true(any(row["historical_price_source"] == "TRUE" for row in input_rows), "historical source not audited")
    for row in input_rows:
        assert_safety(row)
    for row in pit_rows[:1000]:
        assert_safety(row)
        assert_true(row["future_factor_data_used"] == "FALSE", f"future factor data used: {row}")
        if row["pit_safety_status"] == "PASS":
            assert_true(row["snapshot_date_lte_asof"] == "TRUE", f"snapshot date after as-of: {row}")
            assert_true(row["forward_date_gt_asof"] == "TRUE", f"forward date not after as-of: {row}")


def test_report_boundaries() -> None:
    text = REPORT.read_text(encoding="utf-8")
    assert_true(any(f"wrapper_status: {status}" in text for status in ACCEPTED_STATUSES), "report missing accepted status")
    assert_true("dynamic_factor_weight_created: FALSE" in text, "report missing dynamic weight safety")
    assert_true("v20_107_execution_status: NOT_RUN" in text, "report missing V20.107 safety")
    assert_true("official_promotion_allowed: FALSE" in text, "report missing promotion safety")
    assert_true("official_recommendation_created: FALSE" in text, "report missing recommendation safety")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    test_wrapper_runs_and_outputs_created()
    test_batch_runs_and_seed_are_deterministic()
    test_forward_outcomes_and_benchmarks_contract()
    test_pit_safety_audit_and_input_audit()
    test_report_boundaries()
    print("PASS_V20_104_RANDOM_ASOF_BACKTEST_BATCH_RUNNER_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
