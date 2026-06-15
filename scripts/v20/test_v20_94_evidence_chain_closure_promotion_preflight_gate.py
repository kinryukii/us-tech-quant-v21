from __future__ import annotations

import csv
import importlib.util
import json
import py_compile
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_94_evidence_chain_closure_promotion_preflight_gate.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_94_evidence_chain_closure_promotion_preflight_gate.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_94_evidence_chain_closure_promotion_preflight_gate.ps1"
EVIDENCE = ROOT / "outputs" / "v20" / "evidence"

DETAIL = EVIDENCE / "V20_94_EVIDENCE_CHAIN_CLOSURE_PROMOTION_PREFLIGHT_DETAIL.csv"
SUMMARY = EVIDENCE / "V20_94_EVIDENCE_CHAIN_CLOSURE_PROMOTION_PREFLIGHT_SUMMARY.md"
DETAIL_ALIAS = EVIDENCE / "V20_CURRENT_EVIDENCE_CHAIN_CLOSURE_PROMOTION_PREFLIGHT_DETAIL.csv"
SUMMARY_ALIAS = EVIDENCE / "V20_CURRENT_EVIDENCE_CHAIN_CLOSURE_PROMOTION_PREFLIGHT_SUMMARY.md"

EXPECTED_STATUS = "PASS_EVIDENCE_CHAIN_CLOSED_PROMOTION_STILL_BLOCKED"
EXPECTED_CLOSURE = "PASS_EVIDENCE_CHAIN_CLOSED_WITH_OPTIONAL_WARN"
EXPECTED_COUNTS = {
    "regime_conditioned_evidence": 24,
    "downside_risk_evidence": 24,
    "benchmark_comparison_evidence": 24,
    "acceptance_proof_evidence": 2,
    "ranking_delta_diagnostic_evidence": 40,
}


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


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_wrapper() -> None:
    command = (
        "$tokens=$null;$errors=$null;"
        f"[System.Management.Automation.Language.Parser]::ParseFile('{WRAPPER.as_posix()}', [ref]$tokens, [ref]$errors) > $null;"
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }"
    )
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command])
    assert_true(result.returncode == 0, f"PowerShell wrapper parse failed: {result.stdout}\n{result.stderr}")


def load_module():
    spec = importlib.util.spec_from_file_location("v20_94", SCRIPT)
    assert_true(spec is not None and spec.loader is not None, "could not load V20.94 module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def assert_safety(row: dict[str, str]) -> None:
    for field in ["promotion_allowed", "nasdaq_hurdle_passed", "official_recommendation_created", "official_weight_mutated", "trade_action_created"]:
        assert_true(row[field] == "FALSE", f"{field} invariant failed: {row}")


def assert_all_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        assert_safety(row)


def write_synthetic_inputs(
    tmpdir: Path,
    *,
    acceptance_count: int = 2,
    ranking_status: str = "WARN",
    ranking_count: int = 40,
    high_counts: bool = False,
) -> tuple[Path, Path, Path, Path]:
    module = load_module()
    r5_rows = read_csv(module.V20_82_R5_DETAIL)
    r2_rows = read_csv(module.V20_84_R2_DETAIL)
    if high_counts:
        category_counts = {
            "regime_conditioned_evidence": 30,
            "downside_risk_evidence": 31,
            "benchmark_comparison_evidence": 32,
            "acceptance_proof_evidence": max(acceptance_count, 3),
        }
    else:
        category_counts = {
            "regime_conditioned_evidence": 24,
            "downside_risk_evidence": 24,
            "benchmark_comparison_evidence": 24,
            "acceptance_proof_evidence": acceptance_count,
        }
    for row in r5_rows:
        category = row["validation_category"]
        if category in category_counts:
            row["attached_row_count"] = str(category_counts[category])
            row["certified_row_count"] = str(category_counts[category])
            row["validation_status"] = "PASSED"
            row["category_blocker_reason"] = "NA"
        if category == "ranking_delta_diagnostic_evidence":
            row["attached_row_count"] = str(ranking_count)
            row["certified_row_count"] = "0"
            row["partial_row_count"] = str(ranking_count)
            row["required_level"] = "OPTIONAL"
            row["validation_status"] = ranking_status
            row["category_blocker_reason"] = "OPTIONAL_RANKING_DELTA_PARTIAL_DIAGNOSTIC_READABLE"
    for row in r2_rows:
        category = row["integration_category"]
        if category in category_counts:
            row["attached_row_count"] = str(category_counts[category])
            row["certified_row_count"] = str(category_counts[category])
            row["integration_status"] = "INTEGRATED"
            row["integration_blocker_reason"] = "NA"
        if category == "ranking_delta_diagnostic_evidence":
            row["attached_row_count"] = str(ranking_count)
            row["certified_row_count"] = "0"
            row["partial_row_count"] = str(ranking_count)
            row["required_level"] = "OPTIONAL"
            row["integration_status"] = ranking_status
            row["integration_blocker_reason"] = "OPTIONAL_RANKING_DELTA_PARTIAL_DIAGNOSTIC_READABLE"
    r5_detail = tmpdir / "r5_detail.csv"
    r2_detail = tmpdir / "r2_detail.csv"
    r5_manifest = tmpdir / "r5_manifest.json"
    r2_manifest = tmpdir / "r2_manifest.json"
    write_csv(r5_detail, r5_rows, list(r5_rows[0].keys()))
    write_csv(r2_detail, r2_rows, list(r2_rows[0].keys()))
    write_json(r5_manifest, {"status": "PASS_V20_82_R5_MULTI_PATH_EVIDENCE_VALIDATED", "missing_required_evidence_categories": []})
    write_json(r2_manifest, {"status": "PASS_V20_84_R2_REQUIRED_EVIDENCE_PATHS_INTEGRATED", "missing_required_evidence_categories": []})
    return r5_detail, r2_detail, r5_manifest, r2_manifest


def synthetic_evidence_rows(**kwargs: object) -> tuple[list[dict[str, str]], str, list[str], dict[str, int]]:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        paths = write_synthetic_inputs(Path(tmp), **kwargs)
        return module.build_evidence_rows(
            r5_detail_path=paths[0],
            r2_detail_path=paths[1],
            r5_manifest_path=paths[2],
            r2_manifest_path=paths[3],
        )


def test_outputs_and_summary() -> None:
    for path in [DETAIL, SUMMARY, DETAIL_ALIAS, SUMMARY_ALIAS]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing or empty output: {path}")
    assert_true(DETAIL.read_bytes() == DETAIL_ALIAS.read_bytes(), "detail alias differs")
    assert_true(SUMMARY.read_bytes() == SUMMARY_ALIAS.read_bytes(), "summary alias differs")
    rows = read_csv(DETAIL)
    assert_true(rows, "detail output empty")
    by_check = {row["check_name"]: row for row in rows}
    assert_true(by_check["v20_93_schema_repair_detail_readable"]["check_status"] == "PASSED", "V20.93 detail not audited as readable")
    assert_true(by_check["v20_82_r5_passed"]["check_status"] == "PASSED", "V20.82 R5 pass not recognized")
    assert_true(by_check["v20_84_r2_passed"]["check_status"] == "PASSED", "V20.84 R2 pass not recognized")
    for category, minimum in EXPECTED_COUNTS.items():
        row = by_check[category]
        assert_true(int(row["readable_count"]) >= minimum, f"{category} count too low: {row}")
    for category in ["regime_conditioned_evidence", "downside_risk_evidence", "benchmark_comparison_evidence", "acceptance_proof_evidence"]:
        assert_true(by_check[category]["check_status"] == "PASSED", f"required category not passed: {by_check[category]}")
    ranking = by_check["ranking_delta_diagnostic_evidence"]
    assert_true(ranking["required_level"] == "OPTIONAL", f"ranking diagnostic not optional: {ranking}")
    assert_true(ranking["check_status"] == "WARN", f"ranking diagnostic partial WARN should not block: {ranking}")
    assert_true(all(row["evidence_chain_closure_status"] == EXPECTED_CLOSURE for row in rows), "evidence chain closure status mismatch")
    assert_true(all(row["promotion_preflight_status"] == EXPECTED_STATUS for row in rows), "promotion preflight status mismatch")
    for row in rows:
        assert_safety(row)
    summary = SUMMARY.read_text(encoding="utf-8")
    for token in [
        "## Evidence Chain Status",
        "## Required Evidence Category Counts",
        "## Optional WARN Diagnostics",
        "## Remaining Promotion Blockers",
        "## Safety Confirmation",
        "## Recommended Next Stages",
        "missing_optional_upstream_file_warns:",
        "WARN multi_run_history_sufficiency",
        "WARN candidate_dynamic_weight_promotion_readiness",
        "readable_regime_evidence_count: 24",
        "readable_downside_risk_evidence_count: 24",
        "readable_benchmark_comparison_evidence_count: 24",
        "readable_acceptance_proof_evidence_count: 2",
        "readable_ranking_delta_diagnostic_evidence_count: 40",
        "promotion_allowed: FALSE",
        "nasdaq_hurdle_passed: FALSE",
        "official_recommendation_created: FALSE",
        "official_weight_mutated: FALSE",
        "trade_action_created: FALSE",
    ]:
        assert_true(token in summary, f"summary missing token: {token}")


def test_chain_closed_but_promotion_blocked_fixture() -> None:
    rows, closure, missing, counts = synthetic_evidence_rows()
    promotion_rows, promotion_status, _blockers = load_module().build_promotion_rows(closure)
    combined = rows + promotion_rows
    assert_true(closure == EXPECTED_CLOSURE, f"closed evidence chain not recognized: {closure}")
    assert_true(promotion_status == EXPECTED_STATUS, f"promotion was not still blocked: {promotion_status}")
    assert_true(missing == [], f"unexpected missing required categories: {missing}")
    for category, minimum in EXPECTED_COUNTS.items():
        assert_true(counts[category] >= minimum, f"{category} below expected count: {counts}")
    assert_all_safety(combined)


def test_high_evidence_counts_do_not_enable_promotion_or_mutation() -> None:
    rows, closure, missing, counts = synthetic_evidence_rows(high_counts=True)
    promotion_rows, promotion_status, _blockers = load_module().build_promotion_rows(closure)
    assert_true(closure == EXPECTED_CLOSURE, f"high-count fixture did not close chain: {closure}")
    assert_true(promotion_status == EXPECTED_STATUS, f"high counts enabled promotion: {promotion_status}")
    assert_true(missing == [], f"high-count fixture has missing categories: {missing}")
    assert_true(counts["regime_conditioned_evidence"] >= 24, f"regime count low: {counts}")
    assert_true(counts["downside_risk_evidence"] >= 24, f"downside count low: {counts}")
    assert_true(counts["benchmark_comparison_evidence"] >= 24, f"benchmark count low: {counts}")
    assert_true(counts["acceptance_proof_evidence"] >= 2, f"acceptance count low: {counts}")
    assert_true(counts["ranking_delta_diagnostic_evidence"] >= 40, f"ranking count low: {counts}")
    assert_all_safety(rows + promotion_rows)


def test_missing_acceptance_proof_blocks_chain_and_keeps_safety() -> None:
    rows, closure, missing, counts = synthetic_evidence_rows(acceptance_count=0)
    by_check = {row["check_name"]: row for row in rows}
    assert_true(not closure.startswith("PASS_"), f"missing acceptance proof falsely passed closure: {closure}")
    assert_true("acceptance_proof_evidence" in missing, f"missing acceptance proof not reported: {missing}")
    assert_true(by_check["acceptance_proof_evidence"]["check_status"] == "BLOCKED", f"acceptance row not blocked: {by_check['acceptance_proof_evidence']}")
    assert_true(counts["acceptance_proof_evidence"] == 0, f"acceptance count should be zero: {counts}")
    assert_all_safety(rows)


def test_optional_ranking_delta_warn_is_non_blocking_and_reported() -> None:
    rows, closure, missing, counts = synthetic_evidence_rows(ranking_status="WARN", ranking_count=40)
    by_check = {row["check_name"]: row for row in rows}
    ranking = by_check["ranking_delta_diagnostic_evidence"]
    assert_true(closure == EXPECTED_CLOSURE, f"optional ranking WARN blocked closure: {closure}")
    assert_true(missing == [], f"ranking WARN created missing required category: {missing}")
    assert_true(ranking["required_level"] == "OPTIONAL", f"ranking diagnostic is not optional: {ranking}")
    assert_true(ranking["check_status"] == "WARN", f"ranking diagnostic WARN not reported: {ranking}")
    assert_true(counts["ranking_delta_diagnostic_evidence"] >= 40, f"ranking count low: {counts}")
    promotion_rows, promotion_status, _blockers = load_module().build_promotion_rows(closure)
    assert_true(promotion_status == EXPECTED_STATUS, f"ranking WARN enabled promotion: {promotion_status}")
    assert_all_safety(rows + promotion_rows)


def test_missing_required_category_blocks_chain() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        r5_missing = tmpdir / "r5_missing.csv"
        r2_missing = tmpdir / "r2_missing.csv"
        r5_rows = [row for row in read_csv(module.V20_82_R5_DETAIL) if row["validation_category"] != "regime_conditioned_evidence"]
        r2_rows = [row for row in read_csv(module.V20_84_R2_DETAIL) if row["integration_category"] != "regime_conditioned_evidence"]
        write_csv(r5_missing, r5_rows, list(r5_rows[0].keys()))
        write_csv(r2_missing, r2_rows, list(r2_rows[0].keys()))
        rows, closure, missing, counts = module.build_evidence_rows(r5_detail_path=r5_missing, r2_detail_path=r2_missing)
    by_check = {row["check_name"]: row for row in rows}
    assert_true(closure == module.BLOCKED_EVIDENCE_CHAIN_STATUS, f"missing required category did not block: {closure}")
    assert_true("regime_conditioned_evidence" in missing, f"missing category not reported: {missing}")
    assert_true(by_check["regime_conditioned_evidence"]["check_status"] == "BLOCKED", f"missing category row not blocked: {by_check['regime_conditioned_evidence']}")
    assert_true(counts["regime_conditioned_evidence"] == 0, f"missing category count should be zero: {counts}")
    assert_all_safety(rows)


def test_missing_optional_promotion_inputs_warn_not_crash() -> None:
    module = load_module()
    original_inputs = module.PREFLIGHT_INPUTS
    with tempfile.TemporaryDirectory() as tmp:
        missing = Path(tmp) / "missing.csv"
        try:
            module.PREFLIGHT_INPUTS = {key: [missing] for key in original_inputs}
            rows, status, blockers = module.build_promotion_rows(module.EXPECTED_CLOSURE if hasattr(module, "EXPECTED_CLOSURE") else EXPECTED_CLOSURE)
        finally:
            module.PREFLIGHT_INPUTS = original_inputs
    assert_true(status == EXPECTED_STATUS, f"missing optional promotion inputs changed status: {status}")
    optional_rows = [row for row in rows if row["required_level"] == "OPTIONAL_UPSTREAM"]
    assert_true(optional_rows, "optional promotion rows missing")
    assert_true(all(row["source_status"] == "MISSING_OPTIONAL" for row in optional_rows), f"missing optional sources not reported: {optional_rows}")
    assert_true(all(row["check_status"] == "WARN" for row in optional_rows), f"missing optional sources did not WARN: {optional_rows}")
    assert_true("multi_run_history_sufficiency" in blockers, f"blocker list missing multi-run history: {blockers}")
    assert_all_safety(rows)


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    assert_true(result.returncode == 0, f"wrapper failed: {result.stdout}\n{result.stderr}")
    assert_true(EXPECTED_STATUS in result.stdout, f"unexpected wrapper status: {result.stdout}")
    assert_true(f"EVIDENCE_CHAIN_CLOSURE_STATUS={EXPECTED_CLOSURE}" in result.stdout, f"closure status missing: {result.stdout}")
    test_outputs_and_summary()
    test_chain_closed_but_promotion_blocked_fixture()
    test_high_evidence_counts_do_not_enable_promotion_or_mutation()
    test_missing_acceptance_proof_blocks_chain_and_keeps_safety()
    test_optional_ranking_delta_warn_is_non_blocking_and_reported()
    test_missing_required_category_blocks_chain()
    test_missing_optional_promotion_inputs_warn_not_crash()
    print("PASS_V20_94_EVIDENCE_CHAIN_CLOSURE_PROMOTION_PREFLIGHT_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
