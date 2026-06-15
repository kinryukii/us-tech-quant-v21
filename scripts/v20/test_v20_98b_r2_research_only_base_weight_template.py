from __future__ import annotations

import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_98b_r2_research_only_base_weight_template.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_98b_r2_research_only_base_weight_template.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_98b_r2_research_only_base_weight_template.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

TEMPLATE = CONSOLIDATION / "V20_98B_R2_RESEARCH_ONLY_BASE_WEIGHT_TEMPLATE.csv"
VALIDATION = CONSOLIDATION / "V20_98B_R2_BASE_WEIGHT_TEMPLATE_VALIDATION.csv"
REVIEW_QUEUE = CONSOLIDATION / "V20_98B_R2_BASE_WEIGHT_OPERATOR_REVIEW_QUEUE.csv"
REPORT = READ_CENTER / "V20_98B_R2_RESEARCH_ONLY_BASE_WEIGHT_TEMPLATE_REPORT.md"

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


def test_wrapper_passes_and_outputs_created() -> None:
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    assert_true(result.returncode == 0, f"wrapper failed: {result.stdout}\n{result.stderr}")
    assert_true("PASS_V20_98B_R2_RESEARCH_ONLY_BASE_WEIGHT_TEMPLATE" in result.stdout, f"missing pass status: {result.stdout}")
    assert_true("V20_49_RESEARCH_ONLY_GATE_STATUS=PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE" in result.stdout, "research-only gate not preserved")
    assert_true("V20_49_OFFICIAL_PROMOTION_GATE_STATUS=BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE" in result.stdout, "official blocked gate not preserved")
    for path in [TEMPLATE, VALIDATION, REVIEW_QUEUE, REPORT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")


def assert_safety(row: dict[str, str]) -> None:
    assert_true(row["research_only"] == "TRUE", f"research_only false: {row}")
    assert_true(row["official_promotion_allowed"] == "FALSE", f"promotion allowed: {row}")
    assert_true(row["official_recommendation_created"] == "FALSE", f"recommendation created: {row}")
    assert_true(row["is_official_weight"] == "FALSE", f"official weight claimed: {row}")
    assert_true(row["weight_mutated"] == "FALSE", f"weight mutation claimed: {row}")
    assert_true(row["trade_action_created"] == "FALSE", f"trade action claimed: {row}")
    assert_true(row["broker_execution_supported"] == "FALSE", f"broker execution claimed: {row}")


def test_required_families_and_inactive_template_flags() -> None:
    rows = read_csv(TEMPLATE)
    families = {row["factor_family"] for row in rows}
    assert_true(REQUIRED_FAMILIES.issubset(families), f"missing required families: {REQUIRED_FAMILIES - families}")
    for row in rows:
        assert_safety(row)
        assert_true(row["active_weight"] in {"", "FALSE"}, f"active weight enabled: {row}")
        assert_true(row["operator_review_required"] == "TRUE", f"operator review not required: {row}")
        assert_true(row["operator_approved"] == "FALSE", f"operator approved unexpectedly: {row}")
        assert_true(row["weight_activation_allowed"] == "FALSE", f"weight activation allowed: {row}")
        assert_true(row["used_in_dynamic_reweighting"] == "FALSE", f"dynamic reweighting used: {row}")
        assert_true(row["source_rank_or_score_used_as_weight"] == "FALSE", f"source_rank_or_score used as weight: {row}")


def test_review_queue_and_validation_keep_v20_107_blocked() -> None:
    review_rows = read_csv(REVIEW_QUEUE)
    validation_rows = read_csv(VALIDATION)
    assert_true(review_rows, "review queue empty")
    for row in review_rows:
        assert_safety(row)
        assert_true(row["operator_review_required"] == "TRUE", f"review not required: {row}")
        assert_true(row["operator_approved"] == "FALSE", f"operator approved unexpectedly: {row}")
        assert_true(row["weight_activation_allowed"] == "FALSE", f"activation allowed: {row}")
        assert_true(row["used_in_dynamic_reweighting"] == "FALSE", f"dynamic reweighting used: {row}")
    checks = {row["validation_check"]: row for row in validation_rows}
    assert_true(checks["required_factor_families_present"]["validation_status"] == "PASS", f"family validation failed: {checks}")
    assert_true(checks["template_rows_not_active_weights"]["validation_status"] == "PASS", f"active weight validation failed: {checks}")
    assert_true(checks["source_rank_or_score_not_used_as_weight"]["validation_status"] == "PASS", f"rank score validation failed: {checks}")
    assert_true(checks["v20_107_dynamic_reweighting_blocked"]["validation_status"] == "PASS", f"V20.107 block validation failed: {checks}")


def test_report_does_not_claim_promotion_or_weight_activation() -> None:
    text = REPORT.read_text(encoding="utf-8")
    assert_true("official_promotion_allowed: FALSE" in text, "report missing promotion blocked status")
    assert_true("official_promotion_allowed: TRUE" not in text, "report claims official promotion allowed")
    assert_true("weight_mutated: FALSE" in text, "report missing weight mutation safety")
    assert_true("active_weight_enabled: FALSE" in text, "report missing inactive weight status")
    assert_true("V20.107 shadow dynamic reweighting remains blocked" in text, "report missing V20.107 blocked status")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    test_wrapper_passes_and_outputs_created()
    test_required_families_and_inactive_template_flags()
    test_review_queue_and_validation_keep_v20_107_blocked()
    test_report_does_not_claim_promotion_or_weight_activation()
    print("PASS_V20_98B_R2_RESEARCH_ONLY_BASE_WEIGHT_TEMPLATE_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
