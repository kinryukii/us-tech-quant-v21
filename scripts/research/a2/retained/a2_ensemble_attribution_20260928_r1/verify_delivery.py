"""Read-only integrity verification of the frozen batch and attribution delivery."""
from pathlib import Path
from datetime import datetime, timezone
import csv
import hashlib
import json

ROOT = Path(__file__).resolve().parent


def read(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def verify_map(mapping, base=None):
    for path, expected in mapping.items():
        target = (base / path) if base else Path(path)
        digest = expected["sha256"] if isinstance(expected, dict) else expected
        assert sha(target) == digest, f"HASH_DRIFT: {target}"
    return len(mapping)


def main():
    freeze = read("FREEZE_VERIFICATION.json")
    manifest = read("FROZEN_BATCH_MANIFEST.json")
    cash = read("cash_receipt.json")
    execution = read("execution_receipt.json")
    qualification = read("qualification_verification.json")
    independent = read("qualification_independent_checks.json")
    cash_test = read("cash_tests_receipt.json")
    execution_test = read("execution_test_receipt.json")
    identity = read("qualification_original_a2_identity.json")

    assert freeze["status"] == cash["status"] == execution["status"] == "PASS"
    assert qualification["status"] == "PASS_READ_ONLY_INVENTORY_WITH_UNRESOLVED_ECONOMIC_QUALIFICATION"
    assert independent["status"] == "PASS" and all(independent["checks"].values())
    assert sha(ROOT / "qualification_controls.py") == independent["script_sha256"]
    assert sha(ROOT / "CONTROL_PLAN.md") == independent["control_plan_sha256"]
    assert sha(ROOT / "FROZEN_BATCH_MANIFEST.json") == freeze["manifest_sha256"]
    assert sha(manifest["archive"]) == freeze["snapshot_sha256"] == manifest["archive_sha256"]
    verify_map({str(Path(manifest["source"]) / x["relative_path"]): x["sha256"] for x in manifest["files"]})
    dependency_count = verify_map(manifest["bound_dependency_sha256"])

    input_checks = {
        "cash": verify_map(cash["source_sha256"]),
        "execution": verify_map(execution["input_sha256"]),
    }
    with (ROOT / "qualification_source_manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        sources = list(csv.DictReader(handle))
    assert all(row["unchanged_after_inventory"].lower() == "true" for row in sources)
    input_checks["qualification"] = verify_map({row["path"]: row["sha256"] for row in sources})
    assert input_checks["qualification"] == qualification["source_count"]
    output_checks = {
        "cash": verify_map(cash["output_sha256"], ROOT),
        "execution": verify_map(execution["output_sha256"], ROOT),
        "qualification": verify_map(qualification["outputs"], ROOT),
    }

    assert cash_test["status"] == "PASS" and cash_test["tests"] == 12
    assert cash_test["failures"] == cash_test["errors"] == cash_test["skipped"] == 0
    assert sha(ROOT / "cash_attribution.py") == cash_test["code_sha256"] == cash["code_sha256"]
    assert sha(ROOT / "tests_cash_attribution.py") == cash_test["tests_sha256"]
    assert sha(ROOT / "cash_receipt.json") == cash_test["analysis_receipt_sha256"]
    assert sha(ROOT / "cash_tests.log") == cash_test["log_sha256"]
    assert execution_test["exit_code"] == 0 and "Ran 6 tests" in execution_test["stderr"]
    assert sha(ROOT / "execution_attribution.py") == execution_test["attribution_code_sha256"]
    assert sha(ROOT / "test_execution_attribution.py") == execution_test["test_file_sha256"]

    assert cash["scenario_count"] == execution["scenario_count"] == 14
    assert cash["signal_rows"] == cash["reconstructed_signals"] == 2503
    assert cash["omitted_signals"] == 0 and cash["max_projection_error"] == 0
    assert cash["max_identity_error"] < 1e-12
    assert all(cash[k] == 0 for k in ["fit_calls", "predictor_loads", "trajectory_replays", "model_or_weight_searches"])
    assert execution["fit_calls"] == execution["replay_calls"] == 0
    assert all(qualification[k] == 0 for k in ["new_fits", "new_predictions", "new_replays", "downloads"])
    assert qualification["candidate_counts"] == {
        "candidate_rows": 111868, "qualified_rows": 62393,
        "unknown_rows": 47271, "proven_ineligible_rows": 2204,
    }
    assert qualification["all_account_days_preserved"] == 9333
    assert qualification["complete_original_pool_signal_days"] == 0
    assert qualification["original_A2_saved_2025_oof_hash_matches_historical_freeze"]
    assert not qualification["original_A2_current_prereg_source_hash_matches_historical_freeze"]
    assert not qualification["original_A2_common_basis_economic_comparison_complete"]
    assert not identity["economic_increment_over_original_A2_certified"]
    for required in ["REPORT.md", "CONTROL_PLAN.md", "ANALYSIS_CONTRACT.md"]:
        assert (ROOT / required).stat().st_size > 0

    delivery_files = sorted(p for p in ROOT.iterdir() if p.is_file() and p.name != "VERIFICATION.json")
    result = {
        "status": "PASS_READ_ONLY_ATTRIBUTION_NOT_ECONOMIC_ACCEPTANCE",
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "frozen_original_files": len(manifest["files"]),
        "frozen_original_dependency_bindings": dependency_count,
        "source_and_snapshot_unchanged": True,
        "component_source_bindings_rechecked": input_checks,
        "component_output_bindings_rechecked": output_checks,
        "cash_and_execution_behavior_tests_passed": 18,
        "test_evidence": ["cash_tests_receipt.json", "execution_test_receipt.json"],
        "new_fits": 0, "new_model_predictions": 0, "new_trajectory_replays": 0,
        "new_weight_or_seed_searches": 0, "closed_capacity_experiment_reopened": False,
        "original_scenario_count": 70, "scenarios_are_independent_samples": False,
        "new_independent_samples": 0,
        "signals_preserved": 2503,
        "candidate_counts": qualification["candidate_counts"],
        "all_2026_account_days_preserved": 9333,
        "complete_original_pool_certified_signal_days": 0,
        "original_A2_oof_identity_verified": True,
        "original_A2_current_prereg_source_drift_disclosed": True,
        "common_account_control_executed": False,
        "increment_over_original_A2_proven": False,
        "economic_2026_qualification_passed": False,
        "causal_complementarity_identified": False,
        "delivery_sha256": {p.name: sha(p) for p in delivery_files},
    }
    (ROOT / "VERIFICATION.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "delivery_sha256"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
