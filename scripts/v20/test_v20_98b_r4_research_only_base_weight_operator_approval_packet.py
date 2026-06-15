from __future__ import annotations

import csv
import py_compile
import subprocess
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_98b_r4_research_only_base_weight_operator_approval_packet.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_98b_r4_research_only_base_weight_operator_approval_packet.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_98b_r4_research_only_base_weight_operator_approval_packet.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

PACKET = CONSOLIDATION / "V20_98B_R4_RESEARCH_ONLY_BASE_WEIGHT_OPERATOR_APPROVAL_PACKET.csv"
VALIDATION = CONSOLIDATION / "V20_98B_R4_BASE_WEIGHT_APPROVAL_VALIDATION.csv"
REPORT = READ_CENTER / "V20_98B_R4_RESEARCH_ONLY_BASE_WEIGHT_OPERATOR_APPROVAL_REPORT.md"

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
    assert_true("PASS_V20_98B_R4_RESEARCH_ONLY_BASE_WEIGHT_OPERATOR_APPROVAL_PACKET" in result.stdout, f"missing pass status: {result.stdout}")
    assert_true("WEIGHT_SUM=1.00" in result.stdout, f"unexpected weight sum: {result.stdout}")
    for path in [PACKET, VALIDATION, REPORT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")
    return result.stdout


def test_packet_weights_and_safety() -> None:
    rows = read_csv(PACKET)
    families = {row["factor_family"] for row in rows}
    assert_true(families == REQUIRED_FAMILIES, f"unexpected families: {families}")
    weights = {row["factor_family"]: Decimal(row["approved_research_base_weight"]) for row in rows}
    assert_true(sum(weights.values(), Decimal("0")) == Decimal("1.00"), f"weights do not sum to 1.00: {weights}")
    assert_true(all(weight <= Decimal("0.35") for weight in weights.values()), f"family cap exceeded: {weights}")
    assert_true(weights["RISK"] > 0, "RISK weight not positive")
    assert_true(weights["MARKET_REGIME"] > 0, "MARKET_REGIME weight not positive")
    assert_true(weights["DATA_TRUST"] > 0, "DATA_TRUST weight not positive")
    for row in rows:
        assert_safety(row)
        assert_true(row["operator_approved"] == "TRUE", f"operator approval missing: {row}")
        assert_true(row["weight_activation_allowed"] == "TRUE", f"research activation not allowed: {row}")
        assert_true(row["activation_scope"] == "RESEARCH_ONLY_BASE_WEIGHT_ACTIVATION", f"wrong activation scope: {row}")
        assert_true(row["validation_status"] == "PASS", f"row validation failed: {row}")


def test_validation_rows_pass_and_preserve_safety() -> None:
    rows = read_csv(VALIDATION)
    checks = {row["validation_check"]: row for row in rows}
    for row in rows:
        assert_safety(row)
        assert_true(row["validation_status"].startswith("PASS"), f"validation did not pass: {row}")
    assert_true(checks["weight_sum_equals_1_00"]["details"] == "weight_sum=1.00", f"sum validation wrong: {checks}")
    assert_true(checks["family_weight_cap_0_35"]["validation_status"] == "PASS", f"cap validation failed: {checks}")
    assert_true(checks["risk_market_regime_data_trust_positive"]["validation_status"] == "PASS", f"protective weights failed: {checks}")
    assert_true(checks["source_rank_or_score_not_used_as_factor_weight_source"]["validation_status"] == "PASS", f"rank source used as weight: {checks}")
    assert_true(checks["official_and_trade_paths_remain_disabled"]["validation_status"] == "PASS", f"official/trade safety failed: {checks}")


def test_report_does_not_claim_official_paths() -> None:
    text = REPORT.read_text(encoding="utf-8")
    assert_true("wrapper_status: PASS_V20_98B_R4_RESEARCH_ONLY_BASE_WEIGHT_OPERATOR_APPROVAL_PACKET" in text, "report missing pass status")
    assert_true("official_promotion_allowed: FALSE" in text, "report missing official promotion safety")
    assert_true("official_promotion_allowed: TRUE" not in text, "report claims official promotion")
    assert_true("is_official_weight: FALSE" in text, "report missing official weight safety")
    assert_true("trade_action_created: FALSE" in text, "report missing trade safety")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    test_wrapper_passes_and_outputs_created()
    test_packet_weights_and_safety()
    test_validation_rows_pass_and_preserve_safety()
    test_report_does_not_claim_official_paths()
    print("PASS_V20_98B_R4_RESEARCH_ONLY_BASE_WEIGHT_OPERATOR_APPROVAL_PACKET_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
