from __future__ import annotations

import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_107_shadow_dynamic_factor_weight_recalibrator.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_107_shadow_dynamic_factor_weight_recalibrator.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_107_shadow_dynamic_factor_weight_recalibrator.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"

OUT_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
OUT_CHANGE = CONSOLIDATION / "V20_107_SHADOW_WEIGHT_CHANGE_AUDIT.csv"
OUT_INPUT = CONSOLIDATION / "V20_107_SHADOW_REWEIGHTING_EVIDENCE_INPUT_AUDIT.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_WEIGHT_VALIDATION.csv"
REPORT = READ_CENTER / "V20_107_SHADOW_DYNAMIC_FACTOR_WEIGHT_REPORT.md"

FAMILIES = {"FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"}
SCOPE = "RESEARCH_ONLY_SHADOW_FACTOR_FAMILY"
ACCEPTED = {
    "PASS_V20_107_SHADOW_DYNAMIC_FACTOR_WEIGHT_RECALIBRATOR",
    "PARTIAL_PASS_V20_107_SHADOW_DYNAMIC_FACTOR_WEIGHT_RECALIBRATOR_WITH_LIMITED_FACTOR_GRANULARITY",
    "PARTIAL_PASS_V20_107_SHADOW_DYNAMIC_FACTOR_WEIGHT_RECALIBRATOR_WITH_LIMITED_EVIDENCE",
}


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


def assert_safety(row: dict[str, str], dynamic_expected: bool = False) -> None:
    assert_true(row["research_only"] == "TRUE", f"research_only false: {row}")
    assert_true(row["official_promotion_allowed"] == "FALSE", f"promotion allowed: {row}")
    assert_true(row["official_recommendation_created"] == "FALSE", f"recommendation created: {row}")
    assert_true(row["weight_mutated"] == "FALSE", f"weight mutation claimed: {row}")
    assert_true(row["trade_action_created"] == "FALSE", f"trade action claimed: {row}")
    assert_true(row["broker_execution_supported"] == "FALSE", f"broker execution claimed: {row}")
    if "is_official_weight" in row:
        assert_true(row["is_official_weight"] == "FALSE", f"official weight claimed: {row}")
    if "dynamic_factor_weight_created" in row:
        assert_true(row["dynamic_factor_weight_created"] == ("TRUE" if dynamic_expected else "FALSE"), f"dynamic flag wrong: {row}")
    if "dynamic_factor_weight_scope" in row:
        assert_true(row["dynamic_factor_weight_scope"] == SCOPE, f"dynamic scope wrong: {row}")
    if "v20_107_execution_status" in row:
        assert_true(row["v20_107_execution_status"] == "RUN_SHADOW_ONLY", f"V20.107 status wrong: {row}")


def test_wrapper_runs_and_outputs_created() -> None:
    before = R5_REGISTRY.read_text(encoding="utf-8")
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    after = R5_REGISTRY.read_text(encoding="utf-8")
    assert_true(result.returncode == 0, f"wrapper failed: {result.stdout}\n{result.stderr}")
    assert_true(any(status in result.stdout for status in ACCEPTED), f"missing accepted status: {result.stdout}")
    assert_true("LIMITED_FACTOR_GRANULARITY_RECOGNIZED=TRUE" in result.stdout, "limited factor granularity not recognized")
    assert_true("FACTOR_LEVEL_WEIGHTS_CREATED=FALSE" in result.stdout, "factor-level weights created")
    assert_true("OFFICIAL_WEIGHTS_CREATED=FALSE" in result.stdout, "official weights created")
    assert_true("DYNAMIC_FACTOR_WEIGHT_CREATED=TRUE" in result.stdout, "shadow dynamic weights not created")
    assert_true(f"DYNAMIC_FACTOR_WEIGHT_SCOPE={SCOPE}" in result.stdout, "wrong dynamic scope")
    assert_true("V20_107_EXECUTION_STATUS=RUN_SHADOW_ONLY" in result.stdout, "wrong execution status")
    assert_true(before == after, "R5 active research base weights mutated")
    for path in [OUT_WEIGHTS, OUT_CHANGE, OUT_INPUT, OUT_VALIDATION, REPORT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")


def test_shadow_weights_contract() -> None:
    rows = read_csv(OUT_WEIGHTS)
    assert_true({row["factor_family"] for row in rows} == FAMILIES, "not all families represented")
    weights = {row["factor_family"]: float(row["normalized_shadow_dynamic_weight"]) for row in rows}
    assert_true(abs(sum(weights.values()) - 1.0) <= 1e-8, f"weights do not sum to 1: {weights}")
    assert_true(max(weights.values()) <= 0.35 + 1e-8, f"family cap exceeded: {weights}")
    assert_true(weights["RISK"] > 0, "RISK not positive")
    assert_true(weights["MARKET_REGIME"] > 0, "MARKET_REGIME not positive")
    assert_true(weights["DATA_TRUST"] > 0, "DATA_TRUST not positive")
    for row in rows:
        assert_safety(row)
        assert_true(row["shadow_weight_activation_scope"] == "RESEARCH_ONLY_SHADOW", f"wrong activation scope: {row}")
        assert_true(row["factor_granularity_status"] == "LIMITED_FACTOR_GRANULARITY", f"limited granularity not recorded: {row}")
        assert_true(row["shadow_weight_confidence"] == "PARTIAL", f"partial confidence not recorded: {row}")
        assert_true(abs(float(row["weight_change_pct"])) <= 0.2000001, f"relative change cap exceeded: {row}")


def test_change_audit_and_validation() -> None:
    changes = read_csv(OUT_CHANGE)
    validation = read_csv(OUT_VALIDATION)
    assert_true({row["factor_family"] for row in changes} == FAMILIES, "change audit missing families")
    for row in changes:
        assert_safety(row)
        assert_true(row["family_weight_cap_passed"] == "TRUE", f"cap failed: {row}")
        assert_true(row["nonzero_required_family_passed"] == "TRUE", f"required nonzero failed: {row}")
        assert_true(row["validation_status"] == "PASS", f"change validation failed: {row}")
    assert_true(len(validation) == 1, "validation should have one row")
    row = validation[0]
    assert_safety(row, dynamic_expected=True)
    assert_true(row["factor_family_count"] == "6", f"wrong family count: {row}")
    assert_true(row["required_family_count"] == "6", f"wrong required count: {row}")
    assert_true(row["weight_sum_valid"] == "TRUE", f"weight sum invalid: {row}")
    assert_true(row["family_cap_valid"] == "TRUE", f"family cap invalid: {row}")
    assert_true(row["risk_weight_positive"] == "TRUE", f"risk not positive: {row}")
    assert_true(row["market_regime_weight_positive"] == "TRUE", f"market regime not positive: {row}")
    assert_true(row["data_trust_weight_positive"] == "TRUE", f"data trust not positive: {row}")
    assert_true(row["factor_level_weights_created"] == "FALSE", f"factor-level weights created: {row}")
    assert_true(row["official_weights_created"] == "FALSE", f"official weights created: {row}")
    assert_true(row["active_base_weights_mutated"] == "FALSE", f"base weights mutated: {row}")


def test_input_audit_and_report() -> None:
    inputs = read_csv(OUT_INPUT)
    assert_true(inputs, "input audit empty")
    assert_true(any(row["limited_factor_granularity_recognized"] == "TRUE" for row in inputs), "limited granularity not audited")
    assert_true(all(row["source_rank_or_score_used_as_weight"] == "FALSE" for row in inputs), "source rank used as weight")
    assert_true(all(row["factor_level_dynamic_weights_created"] == "FALSE" for row in inputs), "factor-level dynamic weights created")
    for row in inputs:
        assert_safety(row, dynamic_expected=True)
    text = REPORT.read_text(encoding="utf-8")
    assert_true(any(f"wrapper_status: {status}" in text for status in ACCEPTED), "report missing status")
    assert_true("dynamic_factor_weight_scope: RESEARCH_ONLY_SHADOW_FACTOR_FAMILY" in text, "report missing scope")
    assert_true("factor_level_weights_created: FALSE" in text, "report claims factor-level weights")
    assert_true("official_weights_created: FALSE" in text, "report claims official weights")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    test_wrapper_runs_and_outputs_created()
    test_shadow_weights_contract()
    test_change_audit_and_validation()
    test_input_audit_and_report()
    print("PASS_V20_107_SHADOW_DYNAMIC_FACTOR_WEIGHT_RECALIBRATOR_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
