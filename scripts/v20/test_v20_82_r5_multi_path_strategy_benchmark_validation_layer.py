from __future__ import annotations

import csv
import importlib.util
import json
import py_compile
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "scripts" / "v20"
STAGE_SCRIPT = SCRIPT_DIR / "v20_82_r5_multi_path_strategy_benchmark_validation_layer.py"
CANONICAL_SCRIPT = SCRIPT_DIR / "v20_82_multi_path_strategy_benchmark_validation_layer.py"
TEST_SCRIPT = SCRIPT_DIR / "test_v20_82_r5_multi_path_strategy_benchmark_validation_layer.py"
WRAPPER = SCRIPT_DIR / "run_v20_82_r5_multi_path_strategy_benchmark_validation_layer.ps1"
EVIDENCE = ROOT / "outputs" / "v20" / "evidence"
OPS = ROOT / "outputs" / "v20" / "ops"

DETAIL = EVIDENCE / "V20_82_R5_MULTI_PATH_VALIDATION_DETAIL.csv"
DETAIL_ALIAS = EVIDENCE / "V20_CURRENT_MULTI_PATH_VALIDATION_DETAIL.csv"
MANIFEST = OPS / "V20_82_MULTI_PATH_STRATEGY_BENCHMARK_VALIDATION_MANIFEST.json"

EXPECTED_COUNTS = {
    "regime_conditioned_evidence": 24,
    "downside_risk_evidence": 24,
    "benchmark_comparison_evidence": 24,
    "acceptance_proof_evidence": 2,
    "ranking_delta_diagnostic_evidence": 40,
}
REPAIRED_ALIAS_SOURCES = {
    "regime_conditioned_evidence": "outputs/v20/consolidation/V20_CURRENT_REGIME_CONDITIONED_EVIDENCE_EXPORT.csv",
    "downside_risk_evidence": "outputs/v20/consolidation/V20_CURRENT_DOWNSIDE_RISK_EVIDENCE_EXPORT.csv",
    "benchmark_comparison_evidence": "outputs/v20/consolidation/V20_CURRENT_CERTIFIED_BENCHMARK_COMPARISON_EVIDENCE_EXPORT.csv",
    "acceptance_proof_evidence": "outputs/v20/evidence/V20_CURRENT_ACCEPTANCE_PROOF_EVIDENCE_REPAIR.csv",
    "ranking_delta_diagnostic_evidence": "outputs/v20/evidence/V20_CURRENT_RANKING_DELTA_DIAGNOSTIC_EVIDENCE_REPAIR.csv",
}


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_canonical_module():
    spec = importlib.util.spec_from_file_location("v20_82_r5_regression_module", CANONICAL_SCRIPT)
    assert_true(spec is not None and spec.loader is not None, "could not load canonical V20.82 module")
    module = importlib.util.module_from_spec(spec)
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


def assert_safety_flags(mapping: dict[str, object]) -> None:
    for field in ["promotion_allowed", "nasdaq_hurdle_passed", "official_recommendation_created", "official_weight_mutated", "trade_action_created"]:
        assert_true(mapping.get(field) is False or mapping.get(field) == "FALSE", f"{field} invariant failed: {mapping}")


def test_repaired_alias_sources(rows: list[dict[str, str]]) -> None:
    by_category = {row["validation_category"]: row for row in rows}
    for category, expected_source in REPAIRED_ALIAS_SOURCES.items():
        assert_true(by_category[category]["source_file"] == expected_source, f"{category} did not read repaired alias: {by_category[category]}")
    module = load_canonical_module()
    source_by_category = {entry["validation_category"]: entry["source"] for entry in module.R5_CATEGORIES}
    assert_true(source_by_category["acceptance_proof_evidence"] == module.V20_93_ACCEPTANCE_PROOF_REPAIR, "canonical V20.82 acceptance source is not V20.93 repair alias")
    assert_true(source_by_category["ranking_delta_diagnostic_evidence"] == module.V20_93_RANKING_DELTA_REPAIR, "canonical V20.82 ranking source is not V20.93 repair alias")
    assert_true("v20_82_multi_path_strategy_benchmark_validation_layer import main" in STAGE_SCRIPT.read_text(encoding="utf-8"), "R5 entrypoint no longer delegates to canonical V20.82")


def test_required_counts_and_blockers(rows: list[dict[str, str]], manifest: dict[str, object]) -> None:
    by_category = {row["validation_category"]: row for row in rows}
    for category, minimum in EXPECTED_COUNTS.items():
        row = by_category[category]
        count_field = "attached_row_count" if category == "ranking_delta_diagnostic_evidence" else "certified_row_count"
        assert_true(int(row[count_field]) >= minimum, f"{category} count too low: {row}")
    for category in ["regime_conditioned_evidence", "downside_risk_evidence", "benchmark_comparison_evidence", "acceptance_proof_evidence"]:
        assert_true(by_category[category]["validation_status"] == "PASSED", f"{category} not passed: {by_category[category]}")
    ranking = by_category["ranking_delta_diagnostic_evidence"]
    assert_true(ranking["required_level"] == "OPTIONAL", f"ranking diagnostic is not optional: {ranking}")
    assert_true(ranking["validation_status"] == "WARN", f"ranking diagnostic should remain optional WARN: {ranking}")
    assert_true(manifest["status"] == "PASS_V20_82_R5_MULTI_PATH_EVIDENCE_VALIDATED", f"R5 did not pass: {manifest}")
    assert_true(manifest["missing_required_evidence_categories"] == [], f"missing required categories: {manifest}")
    assert_true(manifest["readable_regime_evidence_count"] >= 24, f"manifest regime count too low: {manifest}")
    assert_true(manifest["readable_downside_risk_evidence_count"] >= 24, f"manifest downside count too low: {manifest}")
    assert_true(manifest["readable_benchmark_comparison_evidence_count"] >= 24, f"manifest benchmark count too low: {manifest}")
    assert_true(manifest["readable_acceptance_proof_evidence_count"] >= 2, f"manifest acceptance count too low: {manifest}")
    assert_true(manifest["readable_ranking_delta_diagnostic_evidence_count"] >= 40, f"manifest ranking count too low: {manifest}")


def test_missing_required_repaired_category_blocks_without_mutation() -> None:
    module = load_canonical_module()
    original_categories = module.R5_CATEGORIES
    with tempfile.TemporaryDirectory() as tmp:
        missing_path = Path(tmp) / "missing_regime_repair.csv"
        patched = []
        for entry in original_categories:
            clone = dict(entry)
            if clone["validation_category"] == "regime_conditioned_evidence":
                clone["source"] = missing_path
            patched.append(clone)
        try:
            module.R5_CATEGORIES = patched
            rows, status = module.build_r5_detail_rows()
        finally:
            module.R5_CATEGORIES = original_categories
    by_category = {row["validation_category"]: row for row in rows}
    missing = by_category["regime_conditioned_evidence"]
    assert_true(status == "PARTIAL_PASS_V20_82_R5_MULTI_PATH_EVIDENCE_ATTACHED_WITH_CATEGORY_BLOCKERS", f"missing required category falsely full-passed: {status}")
    assert_true(missing["validation_status"] == "BLOCKED", f"missing regime category not blocked: {missing}")
    missing_required = [row["validation_category"] for row in rows if row["required_level"] == "REQUIRED" and row["validation_status"] == "BLOCKED"]
    assert_true("regime_conditioned_evidence" in missing_required, f"missing category not reported: {missing_required}")
    for row in rows:
        assert_true(row["official_recommendation_created"] == "FALSE", f"synthetic failure created recommendation: {row}")
        assert_true(row["official_weight_mutated"] == "FALSE", f"synthetic failure mutated weight: {row}")
        assert_true(row["trade_action_created"] == "FALSE", f"synthetic failure created trade: {row}")


def main() -> int:
    for path in [STAGE_SCRIPT, CANONICAL_SCRIPT, TEST_SCRIPT]:
        py_compile.compile(str(path), doraise=True)
    parse_wrapper()
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    assert_true(result.returncode == 0, f"wrapper failed: {result.stdout}\n{result.stderr}")
    assert_true("PASS_V20_82_R5_MULTI_PATH_EVIDENCE_VALIDATED" in result.stdout, result.stdout)
    rows = read_csv(DETAIL)
    assert_true(DETAIL.read_bytes() == DETAIL_ALIAS.read_bytes(), "current R5 alias differs")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    test_repaired_alias_sources(rows)
    test_required_counts_and_blockers(rows, manifest)
    assert_safety_flags(manifest)
    test_missing_required_repaired_category_blocks_without_mutation()
    print("PASS_V20_82_R5_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
