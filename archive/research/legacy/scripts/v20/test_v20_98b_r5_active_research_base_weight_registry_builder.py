from __future__ import annotations

import csv
import py_compile
import subprocess
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_98b_r5_active_research_base_weight_registry_builder.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_98b_r5_active_research_base_weight_registry_builder.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_98b_r5_active_research_base_weight_registry_builder.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
VALIDATION = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_VALIDATION.csv"
REPORT = READ_CENTER / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REPORT.md"

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


def test_wrapper_passes_and_outputs_created() -> None:
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    assert_true(result.returncode == 0, f"wrapper failed: {result.stdout}\n{result.stderr}")
    assert_true("PASS_V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY_BUILT" in result.stdout, f"missing pass status: {result.stdout}")
    assert_true("ACTIVE_RESEARCH_BASE_WEIGHT_COUNT=6" in result.stdout, f"wrong active count: {result.stdout}")
    assert_true("WEIGHT_SUM=1.00" in result.stdout, f"wrong weight sum: {result.stdout}")
    assert_true("V20_107_PRECONDITION_STATUS=ACTIVE_RESEARCH_BASE_WEIGHTS_AVAILABLE" in result.stdout, "V20.107 precondition not ready")
    assert_true("V20_107_EXECUTION_STATUS=NOT_RUN" in result.stdout, "V20.107 execution status not preserved")
    for path in [REGISTRY, VALIDATION, REPORT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")


def test_registry_contract_and_safety() -> None:
    rows = read_csv(REGISTRY)
    assert_true(len(rows) == 6, f"registry row count not six: {len(rows)}")
    families = {row["factor_family"] for row in rows}
    assert_true(families == REQUIRED_FAMILIES, f"unexpected families: {families}")
    weights = {row["factor_family"]: Decimal(row["active_research_base_weight"]) for row in rows}
    assert_true(sum(weights.values(), Decimal("0")) == Decimal("1.00"), f"weights do not sum to 1.00: {weights}")
    assert_true(all(weight <= Decimal("0.35") for weight in weights.values()), f"family cap exceeded: {weights}")
    assert_true(weights["RISK"] > 0, "RISK weight not positive")
    assert_true(weights["MARKET_REGIME"] > 0, "MARKET_REGIME weight not positive")
    assert_true(weights["DATA_TRUST"] > 0, "DATA_TRUST weight not positive")
    for row in rows:
        assert_safety(row)
        assert_true(row["operator_approved"] == "TRUE", f"operator approval missing: {row}")
        assert_true(row["activation_scope"] == "RESEARCH_ONLY_BASE_WEIGHT_ACTIVATION", f"wrong activation scope: {row}")
        assert_true(row["active_for_research_ranking"] == "TRUE", f"not active for ranking: {row}")
        assert_true(row["active_for_shadow_dynamic_reweighting"] == "TRUE", f"not active for shadow dynamic reweighting: {row}")
        assert_true(row["active_for_entry_exit_research"] == "TRUE", f"not active for entry/exit research: {row}")
        assert_true(row["validation_status"] == "PASS", f"row validation failed: {row}")


def test_validation_marks_v20_107_ready_not_run() -> None:
    rows = read_csv(VALIDATION)
    checks = {row["validation_check"]: row for row in rows}
    for row in rows:
        assert_safety(row)
        assert_true(row["validation_status"].startswith("PASS"), f"validation did not pass: {row}")
        assert_true(row["v20_107_precondition_status"] == "ACTIVE_RESEARCH_BASE_WEIGHTS_AVAILABLE", f"V20.107 precondition not ready: {row}")
        assert_true(row["v20_107_execution_status"] == "NOT_RUN", f"V20.107 executed: {row}")
    assert_true(checks["exactly_six_required_factor_families"]["validation_status"] == "PASS", f"family validation failed: {checks}")
    assert_true(checks["active_research_base_weight_count"]["details"] == "active_research_base_weight_count=6", f"active count validation failed: {checks}")
    assert_true(checks["weight_sum_equals_1_00"]["details"] == "weight_sum=1.00", f"sum validation failed: {checks}")
    assert_true(checks["family_weight_cap_0_35"]["validation_status"] == "PASS", f"cap validation failed: {checks}")
    assert_true(checks["risk_market_regime_data_trust_positive"]["validation_status"] == "PASS", f"protective weights failed: {checks}")
    assert_true(checks["official_and_trade_paths_disabled"]["validation_status"] == "PASS", f"official/trade safety failed: {checks}")
    assert_true(checks["v20_107_precondition_ready_not_executed"]["validation_status"] == "PASS", f"V20.107 validation missing: {checks}")


def test_report_does_not_claim_official_paths_or_v20_107_execution() -> None:
    text = REPORT.read_text(encoding="utf-8")
    assert_true("wrapper_status: PASS_V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY_BUILT" in text, "report missing pass status")
    assert_true("v20_107_precondition_status: ACTIVE_RESEARCH_BASE_WEIGHTS_AVAILABLE" in text, "report missing V20.107 precondition")
    assert_true("v20_107_execution_status: NOT_RUN" in text, "report missing V20.107 not-run status")
    assert_true("official_promotion_allowed: FALSE" in text, "report missing promotion safety")
    assert_true("official_promotion_allowed: TRUE" not in text, "report claims official promotion")
    assert_true("is_official_weight: FALSE" in text, "report missing official weight safety")
    assert_true("trade_action_created: FALSE" in text, "report missing trade safety")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    test_wrapper_passes_and_outputs_created()
    test_registry_contract_and_safety()
    test_validation_marks_v20_107_ready_not_run()
    test_report_does_not_claim_official_paths_or_v20_107_execution()
    print("PASS_V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY_BUILDER_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
