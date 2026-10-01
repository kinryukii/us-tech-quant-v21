"""Seal delivery references only; no training, strategy selection, or source edits."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8-sig"))
def sha(path):
    h = hashlib.sha256()
    with (ROOT / path).open("rb") as f:
        for chunk in iter(lambda: f.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()

analysis = read("results/analysis/ANALYSIS_RECEIPT.json")
assert analysis["status"] == "COMPLETE_FIXED_ROSTER_DESCRIPTIVE_ANALYSIS"
assert analysis["resolved_path_years"] == 16388
assert analysis["frozen_parameter_updates"] == analysis["seed_or_weight_searches"] == 0
references = {}
for name, expected in analysis["outputs_sha256"].items():
    path = f"results/analysis/{name}"
    assert sha(path) == expected
    references[path] = expected
ledger_rows = 0
for year in (2025, 2026):
    annual = read(f"results/evaluation_{year}/COMPLETE.json")
    assert annual["status"] == "ALL_DECLARED_PATHS_RESOLVED"
    assert (annual["declared"], annual["replayed"], annual["failed_prediction_paths"]) == (8194, 6712, 1482)
    assert all(r["fit_calls"] == 0 for r in annual["receipts"])
    coverage_path = f"results/evaluation_{year}/independent_audit/AUDIT_COVERAGE_RECEIPT.json"
    coverage = read(coverage_path)
    assert coverage["status"] == "PASS"
    for category in ("pto", "rl_control"):
        p = f"results/evaluation_{year}/independent_audit/{category}_ledger_audit.json"
        a = read(p)
        assert a["status"] == "PASS" and a["mismatch_count"] == 0
        assert a["independent_reconstruction"] and a["shared_price_verification"]
        references[p] = sha(p)
        ledger_rows += sum(coverage["categories"][category]["ledger_rows_from_parquet_footer"].values())
    references[coverage_path] = sha(coverage_path)
assert ledger_rows == 153152976
integrity_path = "results/audits/FINAL_BATCH_INTEGRITY_REVIEW.json"
integrity = read(integrity_path)
assert integrity["status"] == "PASS_FINAL_BATCH_INTEGRITY"
assert integrity["freeze"]["matching_bindings"] == 668
assert integrity["freeze"]["missing_or_changed_bindings"] == 0
references[integrity_path] = sha(integrity_path)
for path in ("results/analysis/ANALYSIS_RECEIPT.json", "results/ANALYSIS_FINDINGS.md", "results/ANALYSIS_VERIFICATION.json",
             "results/delivery/DELIVERY.md", "results/delivery/RAM_AND_RUNTIME.md", "results/delivery/FIXED_CONTEXT_EXAMPLES.json",
             "results/delivery/risk_optimizer_comparison.png", "results/delivery/risk_optimizer_comparison.svg",
             "results/delivery/VISUALIZATION_RECEIPT.json", "results/diagnostics/RESOURCE_FINAL_20260928_161527.json"):
    references[path] = sha(path)
now = datetime.now(timezone.utc).isoformat()
receipt = {
    "status": "DECLARED_RESEARCH_LIST_COMPLETE_FORMAL_FULLPOOL_BLOCKED_DATA",
    "completed_utc": now,
    "declared_path_years": 16388, "replayed_path_years": 13424, "failed_prediction_path_years": 2964,
    "independently_audited_ledger_rows": ledger_rows, "independent_audit_mismatches": 0,
    "analysis_rows": {k: analysis[k] for k in ("main_rows", "paired_rows", "interaction_rows", "prediction_metric_rows")},
    "frozen_bindings_match": 668, "protected_inputs_match": 29,
    "formal_fullpool_status": "BLOCKED_DATA", "unknown_candidate_keys": 47271,
    "first_blind_test": False, "shareholder_total_return_certified": False,
    "approximate_path_years": 3863, "iteration_limit_decisions": 710749,
    "target_fusion_replayed": 0, "all_target_fusion_dependencies_failed": True,
    "new_evaluation_fits": 0, "additional_searches": 0, "remaining_fixed_batch_computations": 0,
    "all_declared_results_retained": True, "automatic_candidate_expansion_allowed": False,
    "artifact_sha256": references,
}
(OUT / "FINAL_DELIVERY_RECEIPT.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
state = {
    "state": receipt["status"], "phase": "stopped_at_end_of_predeclared_list", "updated_utc": now,
    "batch_frozen": True, "prediction_years_complete": [2025, 2026], "account_years_complete": [2025, 2026],
    "independent_ledger_audit_years_complete": [2025, 2026], "analysis_complete": True,
    "declared_paths_total": 16388, "replayed_paths_total": 13424, "failed_prediction_paths_total": 2964,
    "formal_fullpool_status": "BLOCKED_DATA", "search_expansion_allowed": False,
    "remaining_fixed_batch_computations": 0, "delivery": str(OUT / "DELIVERY.md"),
    "resume_from": "Fixed research list finished; read sealed results. No automatic model/seed/horizon/weight extension.",
}
(ROOT / "RUN_STATE.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"status": receipt["status"], "ledger_rows": ledger_rows, "verified_artifacts": len(references)}))
