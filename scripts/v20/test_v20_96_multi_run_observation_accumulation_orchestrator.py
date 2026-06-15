from __future__ import annotations

import csv
import importlib.util
import py_compile
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_96_multi_run_observation_accumulation_orchestrator.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_96_multi_run_observation_accumulation_orchestrator.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_96_multi_run_observation_accumulation_orchestrator.ps1"
EVIDENCE = ROOT / "outputs" / "v20" / "evidence"

DETAIL = EVIDENCE / "V20_96_MULTI_RUN_OBSERVATION_ACCUMULATION_DETAIL.csv"
SUMMARY = EVIDENCE / "V20_96_MULTI_RUN_OBSERVATION_ACCUMULATION_SUMMARY.md"
DETAIL_ALIAS = EVIDENCE / "V20_CURRENT_MULTI_RUN_OBSERVATION_ACCUMULATION_DETAIL.csv"
SUMMARY_ALIAS = EVIDENCE / "V20_CURRENT_MULTI_RUN_OBSERVATION_ACCUMULATION_SUMMARY.md"


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def load_module():
    spec = importlib.util.spec_from_file_location("v20_96", SCRIPT)
    assert_true(spec is not None and spec.loader is not None, "could not load V20.96 module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_wrapper() -> None:
    command = (
        "$tokens=$null;$errors=$null;"
        f"[System.Management.Automation.Language.Parser]::ParseFile('{WRAPPER.as_posix()}', [ref]$tokens, [ref]$errors) > $null;"
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }"
    )
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command])
    assert_true(result.returncode == 0, f"PowerShell parser failed: {result.stdout}\n{result.stderr}")


def assert_safety(row: dict[str, str]) -> None:
    assert_true(row["research_only"] == "TRUE", f"research_only invariant failed: {row}")
    for field in ["promotion_allowed", "official_recommendation_created", "official_weight_mutated", "trade_action_created"]:
        assert_true(row[field] == "FALSE", f"{field} invariant failed: {row}")


def valid_row(run_id: str, date: str = "2026-06-09", status: str = "PASS") -> dict[str, str]:
    return {
        "run_id": run_id,
        "run_timestamp": date,
        "daily_runner_status": status,
        "research_only": "TRUE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
    }


def run_with_observations(rows: list[dict[str, str]], required: int = 5) -> tuple[list[dict[str, str]], str, dict[str, str]]:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        obs = Path(tmp) / "observations.csv"
        ledger = Path(tmp) / "ledger.csv"
        fields = ["run_id", "run_timestamp", "daily_runner_status", "research_only", "official_recommendation_created", "official_weight_mutated", "trade_action_created"]
        write_csv(obs, rows, fields)
        write_csv(ledger, [{"run_id": row.get("run_id", ""), "run_timestamp": row.get("run_timestamp", "")} for row in rows], ["run_id", "run_timestamp"])
        return module.run_orchestrator(observation_paths=[obs], ledger_paths=[ledger])


def ledger_row(run_id: str, timestamp: str = "2026-06-13T04:13:02Z") -> dict[str, str]:
    return {
        "run_id": run_id,
        "observation_timestamp": timestamp,
        "observation_date": timestamp[:10],
        "v20_55_status": "WARN_V20_55_RESEARCH_ONLY_READY_PROMOTION_BLOCKED",
        "daily_conclusion_mode": "RESEARCH_ONLY_DAILY_CONCLUSION_READY_OFFICIAL_PROMOTION_BLOCKED",
        "current_daily_research_lane_status": "WARN",
        "forward_outcome_validation_lane_status": "PENDING_FORWARD_TARGET_DATES",
        "observation_class": "RESEARCH_ONLY_READY_PROMOTION_BLOCKED",
        "research_observation_valid": "TRUE",
        "official_promotion_eligible": "FALSE",
        "promotion_blocker_present": "TRUE",
        "promotion_blocked_reason": "V20.27 pending forward target dates",
        "v20_27_forward_pending": "TRUE",
        "research_only": "TRUE",
        "promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutated": "FALSE",
        "weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "source_artifact_path": "outputs/v20/evidence/V20_CURRENT_DAILY_RUNNER_OBSERVATION_BRIDGE.csv",
        "provenance_status": "OK",
        "ledger_write_timestamp": "2026-06-13T04:20:00Z",
    }


def run_with_ledger(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], str, dict[str, str]]:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Path(tmp) / "V20_DAILY_RESEARCH_OBSERVATION_LEDGER.csv"
        fields = list(rows[0].keys()) if rows else ["run_id"]
        write_csv(ledger, rows, fields)
        return module.run_orchestrator(observation_paths=[ledger], ledger_paths=[ledger])


def test_outputs_aliases_and_summary() -> None:
    for path in [DETAIL, SUMMARY, DETAIL_ALIAS, SUMMARY_ALIAS]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")
    assert_true(DETAIL.read_bytes() == DETAIL_ALIAS.read_bytes(), "detail alias differs")
    assert_true(SUMMARY.read_bytes() == SUMMARY_ALIAS.read_bytes(), "summary alias differs")
    rows = read_csv(DETAIL)
    assert_true(rows, "detail rows empty")
    for row in rows:
        assert_safety(row)
    summary = SUMMARY.read_text(encoding="utf-8")
    for token in [
        "## Inherited V20.95 Status",
        "## Observation Run Counts",
        "discovered_run_count:",
        "valid_observation_run_count:",
        "invalid_observation_run_count:",
        "duplicate_run_count:",
        "multi_run_sufficiency_met:",
        "## Rejected Run Reasons",
        "## Rolling Ledger Status",
        "## Safety Confirmation",
        "promotion_allowed: FALSE",
        "official_recommendation_created: FALSE",
        "official_weight_mutated: FALSE",
        "trade_action_created: FALSE",
    ]:
        assert_true(token in summary, f"summary missing {token}")


def test_blocks_when_v20_95_missing() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        missing = Path(tmp) / "missing.csv"
        rows, status, summary = module.run_orchestrator(v20_95_detail=missing, v20_95_summary=missing, observation_paths=[], ledger_paths=[])
    assert_true(status == module.BLOCKED_STATUS, f"missing V20.95 did not block: {status}")
    assert_true(rows[0]["row_status"] == "BLOCKED", f"blocked audit row missing: {rows}")
    assert_true(summary["remaining_run_count"] == "5", f"missing V20.95 remaining count wrong: {summary}")
    for row in rows:
        assert_safety(row)


def test_zero_discovered_warns() -> None:
    module = load_module()
    rows, status, summary = module.run_orchestrator(observation_paths=[], ledger_paths=[])
    assert_true(status == module.WARN_STATUS, f"zero observations did not WARN: {status}")
    assert_true(summary["discovered_run_count"] == "0", f"discovered count should be zero: {summary}")
    assert_true(summary["valid_observation_run_count"] == "0", f"valid count should be zero: {summary}")
    assert_true(summary["required_run_count"] == "5", f"required count should be five: {summary}")
    assert_true(summary["remaining_run_count"] == "5", f"remaining count should be five: {summary}")
    assert_true(summary["multi_run_sufficiency_met"] == "FALSE", f"sufficiency incorrectly met: {summary}")
    for row in rows:
        assert_safety(row)


def test_valid_duplicate_and_invalid_runs() -> None:
    rows, status, summary = run_with_observations(
        [
            valid_row("RUN_A", "2026-06-01", "PASS"),
            valid_row("RUN_A", "2026-06-02", "PASS"),
            {**valid_row("RUN_BAD_REC"), "official_recommendation_created": "TRUE"},
            {**valid_row("RUN_BAD_WEIGHT"), "official_weight_mutated": "TRUE"},
            {**valid_row("RUN_BAD_TRADE"), "trade_action_created": "TRUE"},
            {**valid_row(""), "run_id": ""},
        ]
    )
    assert_true(status == load_module().WARN_STATUS, f"partial invalid run set should WARN: {status}")
    assert_true(summary["discovered_run_count"] == "6", f"bad discovered count: {summary}")
    assert_true(summary["valid_observation_run_count"] == "1", f"bad valid count: {summary}")
    assert_true(summary["invalid_observation_run_count"] == "5", f"bad invalid count: {summary}")
    assert_true(summary["duplicate_run_count"] == "1", f"bad duplicate count: {summary}")
    for reason in ["DUPLICATE_RUN_ID", "OFFICIAL_RECOMMENDATION_CREATED_NOT_FALSE", "OFFICIAL_WEIGHT_MUTATED_NOT_FALSE", "TRADE_ACTION_CREATED_NOT_FALSE", "MISSING_RUN_ID"]:
        assert_true(reason in summary["rejection_reasons"], f"missing rejection reason {reason}: {summary}")
    for row in rows:
        assert_safety(row)


def test_partial_and_sufficient_counts() -> None:
    partial_rows, partial_status, partial = run_with_observations([valid_row("RUN_1"), valid_row("RUN_2", "2026-06-10")])
    assert_true(partial_status == load_module().WARN_STATUS, f"partial observations should WARN: {partial_status}")
    assert_true(partial["valid_observation_run_count"] == "2", f"partial valid count wrong: {partial}")
    assert_true(partial["remaining_run_count"] == "3", f"partial remaining count wrong: {partial}")
    assert_true(partial["multi_run_sufficiency_met"] == "FALSE", f"partial sufficiency incorrectly met: {partial}")
    for row in partial_rows:
        assert_safety(row)

    sufficient_rows, sufficient_status, sufficient = run_with_observations([valid_row(f"RUN_{index}", f"2026-06-{index + 1:02d}") for index in range(5)])
    assert_true(sufficient_status == load_module().PASS_STATUS, f"sufficient observations should PASS: {sufficient_status}")
    assert_true(sufficient["valid_observation_run_count"] == "5", f"sufficient valid count wrong: {sufficient}")
    assert_true(sufficient["remaining_run_count"] == "0", f"sufficient remaining count wrong: {sufficient}")
    assert_true(sufficient["multi_run_sufficiency_met"] == "TRUE", f"sufficiency not met: {sufficient}")
    for row in sufficient_rows:
        assert_safety(row)


def test_malformed_rows_rejected() -> None:
    rows, _status, summary = run_with_observations([{**valid_row("RUN_NO_DATE"), "run_timestamp": ""}, {**valid_row("RUN_BAD_STATUS"), "daily_runner_status": "FAIL"}, {**valid_row("RUN_NO_RESEARCH"), "research_only": "FALSE"}])
    assert_true(summary["valid_observation_run_count"] == "0", f"malformed rows counted valid: {summary}")
    for reason in ["MISSING_RUN_TIMESTAMP", "RUNNER_STATUS_NOT_PASS_OR_ACCEPTABLE_WARN", "RESEARCH_ONLY_NOT_TRUE"]:
        assert_true(reason in summary["rejection_reasons"], f"missing malformed rejection reason {reason}: {summary}")
    for row in rows:
        assert_safety(row)


def test_v20_55_research_only_warn_counts_but_not_promotion_eligible() -> None:
    rows, status, summary = run_with_observations(
        [valid_row("WARN_RESEARCH_ONLY", "2026-06-12T17:07:22Z", "WARN_V20_55_RESEARCH_ONLY_READY_PROMOTION_BLOCKED")]
    )
    assert_true(status == load_module().WARN_STATUS, f"single research-only observation should warn for sufficiency only: {status}")
    assert_true(summary["valid_observation_run_count"] == "1", f"WARN V20.55 not counted as research observation: {summary}")
    assert_true(summary["official_promotion_eligible_count"] == "0", f"WARN V20.55 became promotion eligible: {summary}")
    by_id = {row["run_id"]: row for row in rows}
    assert_true(by_id["WARN_RESEARCH_ONLY"]["observation_class"] == "RESEARCH_ONLY_READY_PROMOTION_BLOCKED", f"wrong class: {by_id['WARN_RESEARCH_ONLY']}")
    assert_true(by_id["WARN_RESEARCH_ONLY"]["research_observation_valid"] == "TRUE", f"research validity missing: {by_id['WARN_RESEARCH_ONLY']}")
    assert_true(by_id["WARN_RESEARCH_ONLY"]["official_promotion_eligible"] == "FALSE", f"promotion eligibility not blocked: {by_id['WARN_RESEARCH_ONLY']}")


def test_blocked_v20_55_does_not_count() -> None:
    _rows, _status, summary = run_with_observations(
        [valid_row("BLOCKED_RESEARCH", "2026-06-12T17:07:22Z", "BLOCKED_V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER")]
    )
    assert_true(summary["valid_observation_run_count"] == "0", f"BLOCKED V20.55 counted valid: {summary}")
    assert_true("RUNNER_STATUS_NOT_PASS_OR_ACCEPTABLE_WARN" in summary["rejection_reasons"], f"blocked rejection missing: {summary}")


def test_missing_daily_conclusion_artifact_blocks_root_research_observation() -> None:
    module = load_module()
    original_conclusion = module.CURRENT_DAILY_CONCLUSION
    with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
        tmpdir = Path(tmp)
        module.CURRENT_DAILY_CONCLUSION = tmpdir / "missing_daily_conclusion.md"
        obs = tmpdir / "observations.csv"
        ledger = tmpdir / "ledger.csv"
        row = valid_row("ROOT_WARN_NO_CONCLUSION", "2026-06-12T17:07:22Z", "WARN_V20_55_RESEARCH_ONLY_READY_PROMOTION_BLOCKED")
        write_csv(obs, [row], ["run_id", "run_timestamp", "daily_runner_status", "research_only", "official_recommendation_created", "official_weight_mutated", "trade_action_created"])
        write_csv(ledger, [{"run_id": row["run_id"], "run_timestamp": row["run_timestamp"]}], ["run_id", "run_timestamp"])
        rows, _status, summary = module.run_orchestrator(observation_paths=[obs], ledger_paths=[ledger])
    module.CURRENT_DAILY_CONCLUSION = original_conclusion
    assert_true(summary["valid_observation_run_count"] == "0", f"missing conclusion artifact did not block: {summary}")
    assert_true(rows[0]["provenance_status"] == "MISSING_DAILY_CONCLUSION_ARTIFACT", f"missing conclusion provenance absent: {rows[0]}")


def test_persistent_ledger_two_run_ids_count_two_and_duplicates_do_not_inflate() -> None:
    rows, _status, summary = run_with_ledger(
        [
            ledger_row("V20_55_LEDGER_A", "2026-06-13T04:13:02Z"),
            ledger_row("V20_55_LEDGER_B", "2026-06-14T04:13:02Z"),
            ledger_row("V20_55_LEDGER_A", "2026-06-13T04:13:02Z"),
        ]
    )
    assert_true(summary["valid_observation_run_count"] == "2", f"ledger unique count wrong: {summary}")
    assert_true(summary["research_observation_count"] == "2", f"ledger research count wrong: {summary}")
    assert_true(summary["duplicate_run_count"] == "1", f"ledger duplicate not detected: {summary}")
    assert_true(summary["official_promotion_eligible_count"] == "0", f"pending V20.27 should keep promotion count zero: {summary}")
    valid_ids = {row["run_id"] for row in rows if row["row_status"] == "VALID"}
    assert_true(valid_ids == {"V20_55_LEDGER_A", "V20_55_LEDGER_B"}, f"valid ids wrong: {valid_ids}")


def test_missing_historical_artifact_is_not_fabricated_in_ledger_input() -> None:
    _rows, _status, summary = run_with_ledger([ledger_row("V20_55_20260613T041302Z", "2026-06-13T04:13:02Z")])
    assert_true(summary["valid_observation_run_count"] == "1", f"single recoverable ledger row should count once: {summary}")
    assert_true("V20_55_20260612T170722Z" not in summary["valid_run_ids"], f"unrecoverable historical run was fabricated: {summary}")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    assert_true(result.returncode == 0, f"wrapper failed: {result.stdout}\n{result.stderr}")
    assert_true(
        "PASS_V20_96_MULTI_RUN_OBSERVATIONS_ACCUMULATED_RESEARCH_ONLY" in result.stdout
        or "WARN_V20_96_INSUFFICIENT_VALID_OBSERVATION_RUNS" in result.stdout,
        f"unexpected wrapper status: {result.stdout}",
    )
    test_outputs_aliases_and_summary()
    test_blocks_when_v20_95_missing()
    test_zero_discovered_warns()
    test_valid_duplicate_and_invalid_runs()
    test_partial_and_sufficient_counts()
    test_malformed_rows_rejected()
    test_v20_55_research_only_warn_counts_but_not_promotion_eligible()
    test_blocked_v20_55_does_not_count()
    test_missing_daily_conclusion_artifact_blocks_root_research_observation()
    test_persistent_ledger_two_run_ids_count_two_and_duplicates_do_not_inflate()
    test_missing_historical_artifact_is_not_fabricated_in_ledger_input()
    print("PASS_V20_96_MULTI_RUN_OBSERVATION_ACCUMULATION_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
