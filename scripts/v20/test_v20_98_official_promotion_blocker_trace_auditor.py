from __future__ import annotations

import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_98_official_promotion_blocker_trace_auditor.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_98_official_promotion_blocker_trace_auditor.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_98_official_promotion_blocker_trace_auditor.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

TRACE = CONSOLIDATION / "V20_98_OFFICIAL_PROMOTION_BLOCKER_TRACE.csv"
LINEAGE = CONSOLIDATION / "V20_98_PROMOTION_LINEAGE_SOURCE_AUDIT.csv"
COUNT = CONSOLIDATION / "V20_98_CANDIDATE_COUNT_CONTRACT_AUDIT.csv"
OPTIONAL = CONSOLIDATION / "V20_98_V20_52_53_OPTIONALITY_AUDIT.csv"
REPORT = READ_CENTER / "V20_98_OFFICIAL_PROMOTION_BLOCKER_TRACE_REPORT.md"

REQUIRED_BLOCKERS = {
    "formal_tests_failed",
    "candidate_refreshed_count_mismatch",
    "lineage_contract_validation_failed",
    "v20_27_missing_pit_safe_active_outcome_benchmark_staged_inputs",
    "upstream_v20_48_tests_status_fail",
    "missing_promotion_lineage_sources",
}

REQUIRED_LINEAGE = {"V20.35-R2", "V20.36", "V20.37", "V20.38", "V20.39", "V20.40", "V20.41", "V20.42"}


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


def test_outputs_and_gate_statuses() -> None:
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    assert_true(result.returncode == 0, f"wrapper failed: {result.stdout}\n{result.stderr}")
    assert_true("PASS_V20_98_OFFICIAL_PROMOTION_BLOCKER_TRACE_AUDITOR" in result.stdout, f"missing pass status: {result.stdout}")
    assert_true("V20_54_STATUS=PASS_V20_54_USER_READABLE_CURRENT_DECISION_REPORT" in result.stdout, "V20.54 PASS not recognized")
    assert_true("V20_49_RESEARCH_ONLY_GATE_STATUS=PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE" in result.stdout, "V20.49 research-only PASS not recognized")
    assert_true("V20_49_OFFICIAL_PROMOTION_GATE_STATUS=BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE" in result.stdout, "V20.49 official BLOCKED not recognized")
    for path in [TRACE, LINEAGE, COUNT, OPTIONAL, REPORT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")


def test_required_blockers_and_safety() -> None:
    rows = read_csv(TRACE)
    by_id = {row["blocker_id"]: row for row in rows}
    assert_true(REQUIRED_BLOCKERS.issubset(by_id), f"missing blocker rows: {REQUIRED_BLOCKERS - set(by_id)}")
    for blocker in REQUIRED_BLOCKERS:
        row = by_id[blocker]
        assert_true(row["blocker_present"] == "TRUE", f"blocker not marked present: {row}")
        assert_true(row["research_only_allowed"] == "TRUE", f"research-only should be allowed: {row}")
        assert_true(row["official_promotion_allowed"] == "FALSE", f"promotion allowed in trace: {row}")
        for field in ["official_recommendation_created", "weight_mutated", "trade_action_created", "broker_execution_supported"]:
            assert_true(row[field] == "FALSE", f"{field} claimed TRUE: {row}")


def test_lineage_sources_captured() -> None:
    rows = read_csv(LINEAGE)
    by_source = {row["lineage_source"]: row for row in rows}
    assert_true(REQUIRED_LINEAGE.issubset(by_source), f"missing lineage rows: {REQUIRED_LINEAGE - set(by_source)}")
    for source in REQUIRED_LINEAGE:
        row = by_source[source]
        assert_true(row["official_gate_lists_missing"] == "TRUE", f"lineage source not captured as missing: {row}")
        assert_true(row["official_promotion_allowed"] == "FALSE", f"promotion allowed in lineage audit: {row}")


def test_candidate_count_audit_sources() -> None:
    rows = read_csv(COUNT)
    stages = {row["source_stage"] for row in rows}
    assert_true({"V20.48", "V20.49", "V20.50"}.issubset(stages), f"candidate count audit missing stages: {stages}")
    for row in rows:
        assert_true(row["exists_non_empty"] == "TRUE", f"candidate count source missing: {row}")
        assert_true(int(row["row_count"]) > 0, f"candidate count source empty: {row}")
        assert_true(row["official_promotion_allowed"] == "FALSE", f"promotion allowed in candidate audit: {row}")


def test_v20_52_53_optionality() -> None:
    rows = read_csv(OPTIONAL)
    assert_true(rows, "optionality audit empty")
    assert_true(any(row["stage"] == "V20.52" for row in rows), "V20.52 optionality rows missing")
    assert_true(any(row["stage"] == "V20.53" for row in rows), "V20.53 optionality rows missing")
    assert_true(any(row["exists_non_empty"] == "FALSE" for row in rows), "missing optional artifacts not classified")
    for row in rows:
        assert_true("SUCCESSFUL_OFFICIAL_PROMOTION" not in row["official_promotion_evidence_classification"], f"optional artifact treated as promotion evidence: {row}")
        assert_true(row["official_promotion_allowed"] == "FALSE", f"promotion allowed in optionality audit: {row}")


def test_report_does_not_claim_promotion_allowed() -> None:
    text = REPORT.read_text(encoding="utf-8")
    assert_true("official_promotion_allowed: FALSE" in text, "report missing promotion blocked safety field")
    assert_true("official_promotion_allowed: TRUE" not in text, "report claims official promotion allowed")
    assert_true("broker_execution_supported: FALSE" in text, "report missing broker safety field")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    test_outputs_and_gate_statuses()
    test_required_blockers_and_safety()
    test_lineage_sources_captured()
    test_candidate_count_audit_sources()
    test_v20_52_53_optionality()
    test_report_does_not_claim_promotion_allowed()
    print("PASS_V20_98_OFFICIAL_PROMOTION_BLOCKER_TRACE_AUDITOR_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
