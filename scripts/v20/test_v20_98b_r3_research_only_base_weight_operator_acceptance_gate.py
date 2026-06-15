from __future__ import annotations

import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_98b_r3_research_only_base_weight_operator_acceptance_gate.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_98b_r3_research_only_base_weight_operator_acceptance_gate.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_98b_r3_research_only_base_weight_operator_acceptance_gate.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

ACCEPTANCE_GATE = CONSOLIDATION / "V20_98B_R3_BASE_WEIGHT_OPERATOR_ACCEPTANCE_GATE.csv"
ACTIVE_REGISTRY = CONSOLIDATION / "V20_98B_R3_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
VALIDATION_AUDIT = CONSOLIDATION / "V20_98B_R3_BASE_WEIGHT_VALIDATION_AUDIT.csv"
REPORT = READ_CENTER / "V20_98B_R3_BASE_WEIGHT_OPERATOR_ACCEPTANCE_REPORT.md"

REQUIRED_FAMILIES = {"FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"}


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
    assert_true(row["is_official_weight"] == "FALSE", f"official weight claimed: {row}")
    assert_true(row["weight_mutated"] == "FALSE", f"weight mutation claimed: {row}")
    assert_true(row["trade_action_created"] == "FALSE", f"trade action claimed: {row}")
    assert_true(row["broker_execution_supported"] == "FALSE", f"broker execution claimed: {row}")


def test_wrapper_passes_and_outputs_created() -> str:
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    assert_true(result.returncode == 0, f"wrapper failed: {result.stdout}\n{result.stderr}")
    assert_true("PASS_V20_98B_R3_RESEARCH_ONLY_BASE_WEIGHT_OPERATOR_ACCEPTANCE_GATE" in result.stdout, f"missing pass status: {result.stdout}")
    assert_true("V20_49_RESEARCH_ONLY_GATE_STATUS=PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE" in result.stdout, "research-only gate not preserved")
    assert_true("V20_49_OFFICIAL_PROMOTION_GATE_STATUS=BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE" in result.stdout, "official blocked gate not preserved")
    for path in [ACCEPTANCE_GATE, ACTIVE_REGISTRY, VALIDATION_AUDIT, REPORT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")
    return result.stdout


def test_default_acceptance_is_blocked() -> None:
    gate = read_csv(ACCEPTANCE_GATE)[0]
    assert_safety(gate)
    assert_true(gate["acceptance_status"] == "BLOCKED_OPERATOR_APPROVAL_REQUIRED", f"unexpected acceptance status: {gate}")
    assert_true(gate["v20_49_official_promotion_gate_status"] == "BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE", f"official gate not blocked: {gate}")
    assert_true(gate["active_research_base_weight_count"] == "0", f"active research weights created: {gate}")
    assert_true(gate["official_promotion_allowed"] == "FALSE", f"promotion allowed: {gate}")
    assert_true(gate["is_official_weight"] == "FALSE", f"official weight created: {gate}")
    assert_true(gate["trade_action_created"] == "FALSE", f"trade action created: {gate}")
    assert_true(gate["missing_template_weight_count"] != "0", f"blank template weights not detected: {gate}")
    assert_true(gate["v20_107_dynamic_reweighting_status"] == "BLOCKED_UNTIL_ACCEPTED_ACTIVE_RESEARCH_BASE_WEIGHTS_EXIST", f"V20.107 not blocked: {gate}")


def test_active_registry_does_not_create_weights() -> None:
    rows = read_csv(ACTIVE_REGISTRY)
    families = {row["factor_family"] for row in rows}
    assert_true(REQUIRED_FAMILIES.issubset(families), f"missing required families: {REQUIRED_FAMILIES - families}")
    for row in rows:
        assert_safety(row)
        assert_true(row["active_research_base_weight"] == "", f"active research weight created: {row}")
        assert_true(row["active_research_base_weight_created"] == "FALSE", f"active weight creation claimed: {row}")
        assert_true(row["operator_approved"] == "FALSE", f"operator approval forced: {row}")
        assert_true(row["activation_status"] == "BLOCKED_OPERATOR_APPROVAL_REQUIRED", f"unexpected activation status: {row}")


def test_validation_audit_contains_expected_blockers() -> None:
    rows = read_csv(VALIDATION_AUDIT)
    checks = {row["validation_check"]: row for row in rows}
    for row in rows:
        assert_safety(row)
    assert_true(checks["required_factor_families_present"]["validation_status"] == "PASS", f"required families missing: {checks}")
    assert_true(checks["operator_approval_required_before_activation"]["blocker_id"] == "BLOCKED_OPERATOR_APPROVAL_REQUIRED", f"approval blocker missing: {checks}")
    assert_true(checks["template_weight_present"]["blocker_id"] == "BLOCKED_MISSING_TEMPLATE_WEIGHT", f"template weight blocker missing: {checks}")
    assert_true(checks["v20_49_official_promotion_gate_preserved"]["details"] == "BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE", f"official gate not preserved: {checks}")
    assert_true(checks["official_weight_not_created"]["validation_status"] == "PASS", f"official weight claimed: {checks}")
    assert_true(checks["v20_107_dynamic_reweighting_status"]["blocker_id"] == "BLOCKED_UNTIL_ACCEPTED_ACTIVE_RESEARCH_BASE_WEIGHTS_EXIST", f"V20.107 blocker missing: {checks}")


def test_report_does_not_claim_promotion_or_trade_action() -> None:
    text = REPORT.read_text(encoding="utf-8")
    assert_true("acceptance_status: BLOCKED_OPERATOR_APPROVAL_REQUIRED" in text, "report missing blocked acceptance status")
    assert_true("official_promotion_allowed: FALSE" in text, "report missing promotion blocked status")
    assert_true("official_promotion_allowed: TRUE" not in text, "report claims official promotion allowed")
    assert_true("is_official_weight: FALSE" in text, "report missing official weight safety")
    assert_true("trade_action_created: FALSE" in text, "report missing trade safety")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    test_wrapper_passes_and_outputs_created()
    test_default_acceptance_is_blocked()
    test_active_registry_does_not_create_weights()
    test_validation_audit_contains_expected_blockers()
    test_report_does_not_claim_promotion_or_trade_action()
    print("PASS_V20_98B_R3_RESEARCH_ONLY_BASE_WEIGHT_OPERATOR_ACCEPTANCE_GATE_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
