from __future__ import annotations

import csv
import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_217_global_historical_output_retention_prune_plan.py")
spec = importlib.util.spec_from_file_location("v21_217", MODULE_PATH)
v217 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(v217)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_stage(root: Path, name: str, files: dict[str, int]) -> None:
    stage = root / "outputs/v21" / name
    stage.mkdir(parents=True, exist_ok=True)
    for relpath, size in files.items():
        file = stage / relpath
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"x" * size)


def make_repo(tmp_path: Path, *, protected: bool = True) -> Path:
    root = tmp_path / "repo"
    (root / "outputs/v21").mkdir(parents=True)
    (root / ".venv/Scripts").mkdir(parents=True)
    (root / ".venv/Scripts/python.exe").write_text("python", encoding="utf-8")
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
            "V21.215_COLD_ARCHIVE_ZIP_COPY_CREATION_FOR_V21_154",
            "V21.215_AGGRESSIVE_COMPACT_OUTPUT_POLICY_AND_STORAGE_BUDGET_ENFORCER",
            "V21.216_AGGRESSIVE_COMPACT_AND_DELETE_EXPANDED_OUTPUTS_AFTER_APPROVAL",
        ]:
            (root / "outputs/v21" / name).mkdir(parents=True, exist_ok=True)
    return root


def write_registry(root: Path, rows: list[dict[str, object]]) -> None:
    path = root / v217.REGISTRY_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["artifact_type", "stage_name", "artifact_role", "retention_class", "current_chain_required", "protected_flag"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def reg(stage: str, role: str = "UNKNOWN_REVIEW_REQUIRED", retention: str = "UNKNOWN_MANUAL_REVIEW", current: bool = False, protected: bool = False) -> dict[str, object]:
    return {"artifact_type": "stage_directory", "stage_name": stage, "artifact_role": role, "retention_class": retention, "current_chain_required": current, "protected_flag": protected}


def run_low_threshold(monkeypatch, root: Path, out: Path):
    monkeypatch.setattr(v217, "LARGE_INTERMEDIATE_BYTES", 100)
    monkeypatch.setattr(v217, "COMPACT_KEEP_ESTIMATE_BYTES", 25)
    return v217.run(root, out_dir=out)


def test_protected_current_chain_stages_excluded(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    stage = "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT"
    write_stage(root, stage, {"summary.json": 10, "full.csv": 300})
    write_registry(root, [reg(stage, "ABCDE_RERUN_OUTPUT", "RETAIN_PROTECTED_CURRENT_CHAIN", True, True)])
    run_low_threshold(monkeypatch, root, root / "out")
    rows = read_csv(root / "out/global_historical_stage_prune_plan.csv")
    row = next(r for r in rows if r["stage_dir"] == stage)
    assert row["proposed_action"] == "KEEP_EXPANDED_PROTECTED_CURRENT_CHAIN"


def test_canonical_ohlcv_excluded(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    write_registry(root, [])
    run_low_threshold(monkeypatch, root, root / "out")
    rows = read_csv(root / "out/global_historical_stage_prune_plan.csv")
    assert all("V20_199D_CANONICAL_HISTORICAL_OHLCV" not in r["source_path"] for r in rows)


def test_cleanup_chain_v21_207_plus_excluded(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    stage = "V21.216_AGGRESSIVE_COMPACT_AND_DELETE_EXPANDED_OUTPUTS_AFTER_APPROVAL"
    write_stage(root, stage, {"summary.json": 10, "proof.csv": 300})
    write_registry(root, [reg(stage, "CLEANUP_AUDIT_ARTIFACT", "RETAIN_CLEANUP_EVIDENCE")])
    run_low_threshold(monkeypatch, root, root / "out")
    rows = read_csv(root / "out/global_historical_stage_prune_plan.csv")
    row = next(r for r in rows if r["stage_dir"] == stage)
    assert row["proposed_action"] == "KEEP_EXPANDED_RECENT_CLEANUP_CHAIN"


def test_already_deleted_archived_v21_140_and_v21_154_recognized(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    write_registry(root, [])
    run_low_threshold(monkeypatch, root, root / "out")
    rows = read_csv(root / "out/already_archived_stage_check.csv")
    found = {r["stage_dir"]: r for r in rows}
    assert found[v217.ALREADY_ARCHIVED.pop() if False else "V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020"]["already_archived_or_deleted"] == "True"
    assert found["V21.154_E_R1_INVALID_TRIAL_REPAIR_AND_REPLAY_REAUDIT"]["already_archived_or_deleted"] == "True"


def test_historical_large_stage_with_summary_report_becomes_zip_then_delete(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    stage = "V21.130_OLD_BACKTEST"
    write_stage(root, stage, {"run_summary.json": 10, "final_report.txt": 10, "panel.csv": 300})
    write_registry(root, [reg(stage, "BACKTEST_RESULT", "REVIEW_COLD_ARCHIVE")])
    summary = run_low_threshold(monkeypatch, root, root / "out")
    rows = read_csv(root / "out/global_historical_stage_prune_plan.csv")
    row = next(r for r in rows if r["stage_dir"] == stage)
    assert row["proposed_action"] in {"ZIP_THEN_DELETE_EXPANDED_STAGE", "DELETE_LARGE_INTERMEDIATE_FILES_AFTER_COMPACT_KEEP"}
    assert summary["projected_repo_size_after_global_prune"] >= 0


def test_historical_stage_with_large_intermediate_csv_becomes_delete_large_intermediate(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    stage = "V21.131_REPLAY_DIAGNOSTIC"
    write_stage(root, stage, {"summary.json": 10, "huge_intermediate.csv": 300})
    write_registry(root, [reg(stage, "DIAGNOSTIC_ONLY", "REVIEW_COLD_ARCHIVE")])
    run_low_threshold(monkeypatch, root, root / "out")
    row = next(r for r in read_csv(root / "out/global_historical_stage_prune_plan.csv") if r["stage_dir"] == stage)
    assert row["proposed_action"] == "DELETE_LARGE_INTERMEDIATE_FILES_AFTER_COMPACT_KEEP"


def test_unknown_registry_items_can_be_compact_only(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    stage = "V21.090_UNKNOWN_SMALL"
    write_stage(root, stage, {"summary.json": 10, "report.txt": 10})
    write_registry(root, [reg(stage)])
    run_low_threshold(monkeypatch, root, root / "out")
    row = next(r for r in read_csv(root / "out/global_historical_stage_prune_plan.csv") if r["stage_dir"] == stage)
    assert row["proposed_action"] == "KEEP_COMPACT_SUMMARY_ONLY"


def test_delete_and_compress_allowed_flags_always_false(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    write_registry(root, [])
    summary = run_low_threshold(monkeypatch, root, root / "out")
    assert summary["deletion_performed"] is False
    assert summary["compression_performed"] is False
    rows = read_csv(root / "out/global_historical_stage_prune_plan.csv")
    assert all(r["deletion_allowed_in_this_run"] == "False" for r in rows)
    assert all(r["compression_allowed_in_this_run"] == "False" for r in rows)


def test_protected_path_missing_produces_fail(tmp_path, monkeypatch):
    root = make_repo(tmp_path, protected=False)
    write_registry(root, [])
    summary = run_low_threshold(monkeypatch, root, root / "out")
    assert summary["final_status"] == "FAIL_V21_217_PROTECTED_PATH_MISSING"


def test_required_approval_phrase_and_projection_present(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    write_registry(root, [])
    summary = run_low_threshold(monkeypatch, root, root / "out")
    assert summary["required_manual_approval_phrase"] == v217.APPROVAL_PHRASE
    assert summary["repo_total_size_bytes_now"] >= summary["projected_repo_size_after_global_prune"]


def test_summary_report_artifacts_written_and_no_mutation(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    write_registry(root, [])
    out = root / "out"
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
    summary = run_low_threshold(monkeypatch, root, out)
    after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if not p.is_relative_to(out))
    for name in [
        "v21_217_summary.json",
        "V21.217_global_historical_output_retention_prune_plan_report.txt",
        "repo_post_v21_216_size_snapshot.csv",
        "global_historical_stage_prune_plan.csv",
        "keep_current_chain_manifest.csv",
        "keep_protected_manifest.csv",
        "keep_compact_summary_manifest.csv",
        "zip_then_delete_stage_plan.csv",
        "delete_large_intermediate_file_plan.csv",
        "already_archived_stage_check.csv",
        "projected_repo_size_after_global_prune.csv",
        "protected_path_presence_check.csv",
        "manual_approval_checklist.csv",
    ]:
        assert (out / name).exists()
    assert [p for p in before if not p.startswith("out/")] == after
    assert summary["broker_action_allowed"] is False
    assert summary["canonical_mutation_performed"] is False


def test_unhandled_exception_produces_fail(tmp_path):
    root = make_repo(tmp_path)
    summary = v217.run(root, out_dir=root / "out", simulate_exception=True)
    assert summary["final_status"] == "FAIL_V21_217_GLOBAL_PRUNE_PLAN_EXCEPTION"
    assert summary["deletion_performed"] is False
