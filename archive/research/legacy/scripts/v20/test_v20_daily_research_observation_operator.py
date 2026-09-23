from __future__ import annotations

import csv
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "run_v20_daily_research_observation_operator.ps1"
V97_WRAPPER = ROOT / "scripts" / "v20" / "run_v20_97_daily_runner_observation_bridge_repair.ps1"
V96_WRAPPER = ROOT / "scripts" / "v20" / "run_v20_96_multi_run_observation_accumulation_orchestrator.ps1"
EVIDENCE = ROOT / "outputs" / "v20" / "evidence"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

STATUS = EVIDENCE / "V20_DAILY_RESEARCH_OBSERVATION_OPERATOR_STATUS.csv"
STATUS_ALIAS = EVIDENCE / "V20_CURRENT_DAILY_RESEARCH_OBSERVATION_OPERATOR_STATUS.csv"
SUMMARY = EVIDENCE / "V20_DAILY_RESEARCH_OBSERVATION_OPERATOR_SUMMARY.md"
SUMMARY_ALIAS = EVIDENCE / "V20_CURRENT_DAILY_RESEARCH_OBSERVATION_OPERATOR_SUMMARY.md"
BRIDGE = EVIDENCE / "V20_CURRENT_DAILY_RUNNER_OBSERVATION_BRIDGE.csv"
ACCUMULATION = EVIDENCE / "V20_CURRENT_MULTI_RUN_OBSERVATION_ACCUMULATION.csv"
ACCUMULATION_SUMMARY = EVIDENCE / "V20_CURRENT_MULTI_RUN_OBSERVATION_ACCUMULATION_SUMMARY.md"
LEDGER = EVIDENCE / "V20_DAILY_RESEARCH_OBSERVATION_LEDGER.csv"
LEDGER_ALIAS = EVIDENCE / "V20_CURRENT_DAILY_RESEARCH_OBSERVATION_LEDGER.csv"
LEDGER_SUMMARY = EVIDENCE / "V20_DAILY_RESEARCH_OBSERVATION_LEDGER_SUMMARY.md"
CONCLUSION = READ_CENTER / "V20_CURRENT_DAILY_CONCLUSION.md"


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
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) > $null;"
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }"
    )
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command])
    assert_true(result.returncode == 0, f"PowerShell parser failed: {result.stdout}\n{result.stderr}")


def run_operator(*extra: str) -> subprocess.CompletedProcess[str]:
    return run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), *extra])


def refresh_observation_artifacts() -> None:
    for wrapper in [V97_WRAPPER, V96_WRAPPER]:
        result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(wrapper)])
        assert_true(result.returncode == 0, f"artifact refresh failed for {wrapper.name}: {result.stdout}\n{result.stderr}")


def current_status_row() -> dict[str, str]:
    rows = read_csv(STATUS)
    assert_true(len(rows) == 1, f"operator status should contain one row: {rows}")
    return rows[0]


def test_operator_runs_and_writes_artifacts() -> None:
    refresh_observation_artifacts()
    result = run_operator("-SkipStageExecution")
    assert_true(result.returncode == 0, f"operator wrapper failed: {result.stdout}\n{result.stderr}")
    assert_true(
        "WARN_V20_DAILY_RESEARCH_OBSERVATION_ACCUMULATION_IN_PROGRESS" in result.stdout
        or "PASS_V20_DAILY_RESEARCH_OBSERVATIONS_READY_PROMOTION_BLOCKED" in result.stdout,
        f"unexpected operator status: {result.stdout}",
    )
    for path in [STATUS, STATUS_ALIAS, SUMMARY, SUMMARY_ALIAS, BRIDGE, ACCUMULATION, ACCUMULATION_SUMMARY, LEDGER, LEDGER_ALIAS, LEDGER_SUMMARY]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing artifact: {path}")
    assert_true(STATUS.read_bytes() == STATUS_ALIAS.read_bytes(), "status alias differs")
    assert_true(SUMMARY.read_bytes() == SUMMARY_ALIAS.read_bytes(), "summary alias differs")


def test_v20_55_warn_counts_as_valid_research_observation() -> None:
    row = current_status_row()
    assert_true(row["v20_55_status"] == "WARN_V20_55_RESEARCH_ONLY_READY_PROMOTION_BLOCKED", f"unexpected V20.55 status: {row}")
    assert_true(int(row["research_observation_count"]) >= 1, f"research-only WARN did not count: {row}")
    bridge_rows = read_csv(BRIDGE)
    valid_warn_rows = [
        item for item in bridge_rows
        if item.get("v20_55_status") == "WARN_V20_55_RESEARCH_ONLY_READY_PROMOTION_BLOCKED"
        and item.get("research_observation_valid") == "TRUE"
    ]
    assert_true(valid_warn_rows, f"bridge lacks valid research-only WARN row: {bridge_rows}")


def test_v20_96_warn_insufficient_is_acceptable_under_required_count() -> None:
    row = current_status_row()
    research_count = int(row["research_observation_count"])
    required_count = int(row["required_run_count"])
    assert_true(row["v20_96_status"] == "WARN_V20_96_INSUFFICIENT_VALID_OBSERVATION_RUNS", f"unexpected V20.96 status: {row}")
    assert_true(research_count < required_count, f"fixture should still be below required count: {row}")
    assert_true(row["final_status"] == "WARN_V20_DAILY_RESEARCH_OBSERVATION_ACCUMULATION_IN_PROGRESS", f"wrong operator status: {row}")


def test_official_promotion_and_safety_remain_blocked() -> None:
    row = current_status_row()
    assert_true(row["official_promotion_eligible_count"] == "0", f"official promotion eligible count changed: {row}")
    assert_true(row["v20_27_forward_pending"] == "TRUE", f"V20.27 pending flag missing: {row}")
    assert_true(row["official_promotion_allowed"] == "FALSE", f"official promotion allowed unexpectedly: {row}")
    assert_true(row["official_recommendation_created"] == "FALSE", f"official recommendation created: {row}")
    assert_true(row["weight_mutated"] == "FALSE", f"weight mutation created: {row}")
    assert_true(row["trade_action_created"] == "FALSE", f"trade action created: {row}")


def test_duplicate_run_id_current_alias_does_not_inflate_count() -> None:
    row = current_status_row()
    ledger_rows = read_csv(LEDGER)
    valid_rows = [item for item in ledger_rows if item.get("research_observation_valid") == "TRUE"]
    unique_run_ids = {item.get("run_id") or item.get("observation_run_id") for item in valid_rows}
    assert_true(len(valid_rows) == len(unique_run_ids), f"duplicate current aliases inflated ledger rows: {valid_rows}")
    assert_true(int(row["research_observation_count"]) == len(unique_run_ids), f"operator count differs from canonical bridge ids: {row}, {valid_rows}")


def test_daily_operator_writes_one_ledger_row_for_current_run_and_preserves_safety() -> None:
    ledger_rows = read_csv(LEDGER)
    bridge_rows = read_csv(BRIDGE)
    current_run_id = next(item.get("run_id") for item in bridge_rows if item.get("research_observation_valid") == "TRUE")
    current_run_rows = [item for item in ledger_rows if item["run_id"] == current_run_id]
    assert_true(len(current_run_rows) == 1, f"current run should have one ledger row: {ledger_rows}")
    item = current_run_rows[0]
    assert_true(item["v20_55_status"] == "WARN_V20_55_RESEARCH_ONLY_READY_PROMOTION_BLOCKED", f"bad ledger status: {item}")
    assert_true(item["research_observation_valid"] == "TRUE", f"ledger row not research valid: {item}")
    assert_true(item["official_promotion_eligible"] == "FALSE", f"ledger row became promotion eligible: {item}")
    for field in ["official_recommendation_created", "official_weight_mutated", "weight_mutated", "trade_action_created"]:
        assert_true(item[field] == "FALSE", f"{field} not false in ledger: {item}")
    assert_true(LEDGER.read_bytes() == LEDGER_ALIAS.read_bytes(), "ledger alias differs")


def test_current_alias_overwrite_does_not_delete_old_ledger_rows() -> None:
    before_rows = read_csv(LEDGER)
    historical = dict(before_rows[0])
    historical["run_id"] = "V20_55_SYNTHETIC_HISTORICAL_TEST"
    historical["observation_timestamp"] = "2026-06-01T00:00:00Z"
    historical["observation_date"] = "2026-06-01"
    fields = list(before_rows[0].keys())
    with LEDGER.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerow(historical)
        writer.writerows(before_rows)
    try:
        result = run_operator("-SkipStageExecution")
        assert_true(result.returncode == 0, f"operator failed after historical ledger seed: {result.stdout}\n{result.stderr}")
        after_rows = read_csv(LEDGER)
        assert_true(any(item["run_id"] == "V20_55_SYNTHETIC_HISTORICAL_TEST" for item in after_rows), f"historical ledger row was deleted: {after_rows}")
    finally:
        with LEDGER.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
            writer.writeheader()
            writer.writerows(before_rows)
        shutil.copyfile(LEDGER, LEDGER_ALIAS)
        run_operator("-SkipStageExecution")


def test_missing_historical_artifact_not_fabricated_in_ledger_summary() -> None:
    text = LEDGER_SUMMARY.read_text(encoding="utf-8")
    assert_true("V20_55_20260612T170722Z" in text, "ledger summary must record known unrecoverable run id")
    assert_true("recovery_status:" in text, "ledger summary missing recovery status")


def test_missing_daily_conclusion_artifact_blocks_operator_status() -> None:
    assert_true(CONCLUSION.exists(), f"daily conclusion missing before test: {CONCLUSION}")
    with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
        backup = Path(tmp) / "V20_CURRENT_DAILY_CONCLUSION.md"
        shutil.copyfile(CONCLUSION, backup)
        CONCLUSION.unlink()
        try:
            result = run_operator("-SkipStageExecution")
            assert_true(result.returncode != 0, f"missing conclusion did not block: {result.stdout}\n{result.stderr}")
            rows = read_csv(STATUS)
            assert_true(rows[0]["final_status"] == "BLOCKED_V20_DAILY_RESEARCH_OBSERVATION_OPERATOR", f"wrong blocked status: {rows[0]}")
            assert_true(rows[0]["daily_conclusion_artifact_exists"] == "FALSE", f"missing conclusion flag wrong: {rows[0]}")
            assert_true("MISSING_DAILY_CONCLUSION_ARTIFACT" in rows[0]["blocker_reason"], f"missing blocker reason: {rows[0]}")
        finally:
            shutil.copyfile(backup, CONCLUSION)
    result = run_operator("-SkipStageExecution")
    assert_true(result.returncode == 0, f"operator did not recover after restoring conclusion: {result.stdout}\n{result.stderr}")


def main() -> int:
    parse_wrapper()
    test_operator_runs_and_writes_artifacts()
    test_v20_55_warn_counts_as_valid_research_observation()
    test_v20_96_warn_insufficient_is_acceptable_under_required_count()
    test_official_promotion_and_safety_remain_blocked()
    test_duplicate_run_id_current_alias_does_not_inflate_count()
    test_daily_operator_writes_one_ledger_row_for_current_run_and_preserves_safety()
    test_current_alias_overwrite_does_not_delete_old_ledger_rows()
    test_missing_historical_artifact_not_fabricated_in_ledger_summary()
    test_missing_daily_conclusion_artifact_blocks_operator_status()
    print("PASS_V20_DAILY_RESEARCH_OBSERVATION_OPERATOR_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
