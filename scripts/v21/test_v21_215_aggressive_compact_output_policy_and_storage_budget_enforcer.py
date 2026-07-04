from __future__ import annotations

import csv
import importlib.util
import os
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_215_aggressive_compact_output_policy_and_storage_budget_enforcer.py")
spec = importlib.util.spec_from_file_location("v21_215_aggressive", MODULE_PATH)
aggressive = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(aggressive)

HELPER_PATH = Path(__file__).with_name("v21_storage_policy.py")
helper_spec = importlib.util.spec_from_file_location("v21_storage_policy", HELPER_PATH)
storage_policy = importlib.util.module_from_spec(helper_spec)
assert helper_spec.loader is not None
helper_spec.loader.exec_module(storage_policy)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_stage(root: Path, name: str, size: int = 300) -> None:
    stage = root / "outputs/v21" / name
    stage.mkdir(parents=True, exist_ok=True)
    (stage / "artifact.csv").write_bytes(b"x" * size)


def registry_row(stage: str, role: str, retention: str, *, current: bool = False, protected: bool = False, manual: bool = True) -> dict[str, object]:
    return {
        "artifact_path": f"outputs/v21/{stage}",
        "artifact_type": "stage_directory",
        "stage_name": stage,
        "artifact_role": role,
        "retention_class": retention,
        "current_chain_required": current,
        "protected_flag": protected,
        "manual_approval_required": manual,
    }


def write_registry(root: Path, rows: list[dict[str, object]]) -> None:
    path = root / aggressive.REGISTRY_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["artifact_path", "artifact_type", "stage_name", "artifact_role", "retention_class", "current_chain_required", "protected_flag", "manual_approval_required"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def make_repo(tmp_path: Path, *, protected: bool = True) -> Path:
    root = tmp_path / "repo"
    (root / ".venv/Scripts").mkdir(parents=True)
    (root / ".venv/Scripts/python.exe").write_text("python", encoding="utf-8")
    (root / "scripts/v21").mkdir(parents=True)
    (root / "scripts/v21/v21_130_old_backtest.py").write_text("df.to_csv(out)\n", encoding="utf-8")
    if protected:
        (root / "outputs/v20/price_history").mkdir(parents=True)
        (root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv").write_text("x\n", encoding="utf-8")
        for name in [
            "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
            "V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
            "V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
            "V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION",
            "V21.208_ORIGINAL_REMOVAL_DRY_RUN_APPROVAL_GATE",
            "V21.209_DELETE_ORIGINALS_AFTER_ZIP_VERIFICATION",
            "V21.210_POST_CLEANUP_SIZE_AND_INTEGRITY_RECONCILIATION",
            "V21.211_SECOND_PASS_CLEANUP_TARGET_DISCOVERY_AND_RISK_BUDGET",
            "V21.212_ARTIFACT_ROLE_REGISTRY_AND_RETENTION_POLICY",
        ]:
            (root / "outputs/v21" / name).mkdir(parents=True, exist_ok=True)
    return root


def run_low_threshold(monkeypatch, root: Path, out: Path):
    monkeypatch.setattr(aggressive, "LARGE_THRESHOLD_BYTES", 100)
    monkeypatch.setattr(aggressive, "COMPACT_RETAIN_ESTIMATE_BYTES", 25)
    return aggressive.run(root, out_dir=out)


def test_compact_mode_defaults_to_true(monkeypatch):
    monkeypatch.delenv("V21_OUTPUT_MODE", raising=False)
    monkeypatch.delenv("V21_KEEP_FULL_ARTIFACTS", raising=False)
    assert storage_policy.get_output_mode() == "compact"
    assert storage_policy.keep_full_artifacts() is False


def test_full_artifact_writing_disabled_by_default(monkeypatch):
    monkeypatch.delenv("V21_OUTPUT_MODE", raising=False)
    monkeypatch.delenv("V21_KEEP_FULL_ARTIFACTS", raising=False)
    assert storage_policy.should_write_full_artifact("old_backtest", "full_panel.csv") is False


def test_env_override_can_enable_full_artifact_writing(monkeypatch):
    monkeypatch.setenv("V21_OUTPUT_MODE", "full")
    assert storage_policy.keep_full_artifacts() is True
    assert storage_policy.should_write_full_artifact("old_backtest", "full_panel.csv") is True


def test_storage_policy_helper_blocks_large_full_artifacts_in_compact_mode(monkeypatch):
    monkeypatch.setenv("V21_OUTPUT_MODE", "compact")
    assert storage_policy.should_write_full_artifact("diagnostic", "full_trial_ledger.csv") is False
    budget = storage_policy.enforce_output_budget(200, 100, "diagnostic")
    assert budget["within_budget"] is False
    assert budget["over_budget_bytes"] == 100


def test_protected_current_chain_artifacts_never_delete_candidates(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    stage = "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT"
    write_stage(root, stage, 300)
    write_registry(root, [registry_row(stage, "ABCDE_RERUN_OUTPUT", "RETAIN_PROTECTED_CURRENT_CHAIN", current=True, protected=True)])
    run_low_threshold(monkeypatch, root, root / "out")
    rows = read_csv(root / "out/historical_expanded_output_delete_plan.csv")
    assert all(stage not in row["source_path"] for row in rows)


def test_canonical_price_file_never_delete_candidate(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    write_registry(root, [])
    run_low_threshold(monkeypatch, root, root / "out")
    rows = read_csv(root / "out/historical_expanded_output_delete_plan.csv")
    assert all("V20_199D_CANONICAL_HISTORICAL_OHLCV" not in row["source_path"] for row in rows)


def test_v21_154_can_be_zip_then_delete_candidate(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    stage = "V21.154_E_R1_INVALID_TRIAL_REPAIR_AND_REPLAY_REAUDIT"
    write_stage(root, stage, 300)
    write_registry(root, [registry_row(stage, "AUDIT_CRITICAL_HISTORY", "RETAIN_AUDIT_CRITICAL")])
    run_low_threshold(monkeypatch, root, root / "out")
    rows = read_csv(root / "out/historical_expanded_output_delete_plan.csv")
    assert any(stage in row["source_path"] and row["proposed_action"] == "ZIP_THEN_DELETE_EXPANDED_ORIGINAL" for row in rows)


def test_historical_large_backtest_becomes_aggressive_candidate(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    stage = "V21.130_OLD_RANDOM_BACKTEST"
    write_stage(root, stage, 300)
    write_registry(root, [registry_row(stage, "BACKTEST_RESULT", "REVIEW_COLD_ARCHIVE")])
    run_low_threshold(monkeypatch, root, root / "out")
    rows = read_csv(root / "out/historical_expanded_output_delete_plan.csv")
    assert any(stage in row["source_path"] for row in rows)


def test_current_chain_dram_abcde_moomoo_outputs_excluded(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    stage = "V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH"
    write_stage(root, stage, 300)
    write_registry(root, [registry_row(stage, "DRAM_PLAN_OUTPUT", "RETAIN_PROTECTED_CURRENT_CHAIN", current=True, protected=True)])
    run_low_threshold(monkeypatch, root, root / "out")
    rows = read_csv(root / "out/historical_expanded_output_delete_plan.csv")
    assert all(stage not in row["source_path"] for row in rows)


def test_no_delete_or_compress_in_this_run_and_approval_phrase(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    write_registry(root, [])
    summary = run_low_threshold(monkeypatch, root, root / "out")
    assert summary["deletion_allowed_in_this_run"] is False
    assert summary["compression_allowed_in_this_run"] is False
    assert summary["required_manual_approval_phrase"] == aggressive.REQUIRED_APPROVAL_PHRASE


def test_projected_repo_size_is_calculated(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    stage = "V21.130_OLD_RANDOM_BACKTEST"
    write_stage(root, stage, 300)
    write_registry(root, [registry_row(stage, "BACKTEST_RESULT", "REVIEW_COLD_ARCHIVE")])
    summary = run_low_threshold(monkeypatch, root, root / "out")
    assert summary["repo_total_size_bytes_before"] > 0
    assert summary["projected_repo_size_after_aggressive_cleanup"] >= 0


def test_protected_path_missing_produces_fail(tmp_path, monkeypatch):
    root = make_repo(tmp_path, protected=False)
    write_registry(root, [])
    summary = run_low_threshold(monkeypatch, root, root / "out")
    assert summary["final_status"] == "FAIL_V21_215_PROTECTED_PATH_MISSING"


def test_summary_report_artifacts_written_and_policy_flags(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    write_registry(root, [])
    out = root / "out"
    summary = run_low_threshold(monkeypatch, root, out)
    for name in [
        "v21_215_summary.json",
        "V21.215_aggressive_compact_output_policy_report.txt",
        "storage_budget_policy.csv",
        "compact_output_policy_rules.csv",
        "script_output_behavior_patch_plan.csv",
        "large_artifact_rewrite_or_suppress_plan.csv",
        "aggressive_cleanup_candidate_plan.csv",
        "protected_artifact_keep_manifest.csv",
        "compact_artifact_keep_manifest.csv",
        "historical_expanded_output_delete_plan.csv",
        "registry_unknown_reclassification_plan.csv",
        "projected_repo_size_after_aggressive_cleanup.csv",
        "protected_path_presence_check.csv",
        "manual_approval_checklist.csv",
    ]:
        assert (out / name).exists()
    assert summary["moomoo_broker_connection_performed"] is False
    assert summary["price_refresh_performed"] is False
    assert summary["canonical_mutation_performed"] is False


def test_unhandled_exception_produces_fail(tmp_path):
    root = make_repo(tmp_path)
    summary = aggressive.run(root, out_dir=root / "out", simulate_exception=True)
    assert summary["final_status"] == "FAIL_V21_215_STORAGE_POLICY_EXCEPTION"
    assert summary["deletion_performed"] is False
