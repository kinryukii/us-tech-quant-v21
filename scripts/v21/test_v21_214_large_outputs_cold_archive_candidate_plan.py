from __future__ import annotations

import csv
import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_214_large_outputs_cold_archive_candidate_plan.py")
spec = importlib.util.spec_from_file_location("v21_214", MODULE_PATH)
v214 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(v214)


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
    if protected:
        (root / "outputs/v20/price_history").mkdir(parents=True)
        (root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv").write_text("x\n", encoding="utf-8")
        for name in [
            "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
            "V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
            "V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
            "V21.212_ARTIFACT_ROLE_REGISTRY_AND_RETENTION_POLICY",
        ]:
            (root / "outputs/v21" / name).mkdir(parents=True, exist_ok=True)
    return root


def write_registry(root: Path, rows: list[dict[str, object]]) -> None:
    reg = root / v214.REGISTRY_REL
    reg.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "artifact_path", "artifact_type", "stage_name", "recursive_size_bytes", "file_count",
        "artifact_role", "retention_class", "current_chain_required", "audit_required",
        "reproducibility_required", "protected_flag", "manual_approval_required",
    ]
    with reg.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def registry_row(stage: str, role: str, retention: str, *, current: bool = False, protected: bool = False, manual: bool = True) -> dict[str, object]:
    return {
        "artifact_path": f"outputs/v21/{stage}",
        "artifact_type": "stage_directory",
        "stage_name": stage,
        "recursive_size_bytes": 2048,
        "file_count": 1,
        "artifact_role": role,
        "retention_class": retention,
        "current_chain_required": current,
        "audit_required": role == "AUDIT_CRITICAL_HISTORY",
        "reproducibility_required": role == "REPRODUCIBILITY_SUPPORT",
        "protected_flag": protected,
        "manual_approval_required": manual,
    }


def run_with_low_threshold(monkeypatch, root: Path, out: Path):
    monkeypatch.setattr(v214, "MIN_SIZE_BYTES", 100)
    return v214.run(root, out_dir=out)


def test_v21_154_can_be_tier_a_not_deletion(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    stage = "V21.154_E_R1_INVALID_TRIAL_REPAIR_AND_REPLAY_REAUDIT"
    write_stage(root, stage, {"audit.csv": 300})
    write_registry(root, [registry_row(stage, "AUDIT_CRITICAL_HISTORY", "RETAIN_AUDIT_CRITICAL")])
    run_with_low_threshold(monkeypatch, root, root / "out")
    rows = read_csv(root / "out/large_outputs_cold_archive_candidate_plan.csv")
    assert rows[0]["stage_dir"] == stage
    assert rows[0]["cold_archive_candidate_tier"] == "TIER_A_COLD_ARCHIVE_RETAIN_EVIDENCE"
    assert rows[0]["deletion_allowed_in_this_run"] == "False"
    assert rows[0]["deletion_allowed_after_zip"] == "False"


def test_v21_140_excluded_as_sensitive_historical_price_panel(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    stage = "V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020"
    write_stage(root, stage, {"price_history.csv": 300})
    write_registry(root, [registry_row(stage, "REPRODUCIBILITY_SUPPORT", "RETAIN_REPRODUCIBILITY")])
    run_with_low_threshold(monkeypatch, root, root / "out")
    rows = read_csv(root / "out/large_outputs_cold_archive_candidate_plan.csv")
    assert rows == []
    exclusions = read_csv(root / "out/large_outputs_cold_archive_exclusion_check.csv")
    assert any(r["stage_dir"] == stage and "SENSITIVE_HISTORICAL_PRICE_PANEL" in r["exclusion_reasons"] for r in exclusions)


def test_protected_current_chain_stages_excluded(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    stage = "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT"
    write_stage(root, stage, {"ranking.csv": 300})
    write_registry(root, [registry_row(stage, "ABCDE_RERUN_OUTPUT", "RETAIN_PROTECTED_CURRENT_CHAIN", current=True, protected=True)])
    run_with_low_threshold(monkeypatch, root, root / "out")
    rows = read_csv(root / "out/large_outputs_cold_archive_candidate_plan.csv")
    assert all(r["stage_dir"] != stage for r in rows)


def test_cleanup_chain_v21_202_plus_excluded(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    stage = "V21.212_ARTIFACT_ROLE_REGISTRY_AND_RETENTION_POLICY"
    write_stage(root, stage, {"artifact_registry.csv": 300})
    write_registry(root, [registry_row(stage, "CLEANUP_AUDIT_ARTIFACT", "RETAIN_CLEANUP_EVIDENCE")])
    run_with_low_threshold(monkeypatch, root, root / "out")
    rows = read_csv(root / "out/large_outputs_cold_archive_candidate_plan.csv")
    assert all(r["stage_dir"] != stage for r in rows)


def test_already_archived_deleted_originals_not_included(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    stage = "V21.139_MULTI_STRATEGY_RANDOM_ASOF_BACKTEST"
    write_stage(root, stage, {"result.csv": 300})
    write_registry(root, [registry_row(stage, "BACKTEST_RESULT", "REVIEW_COLD_ARCHIVE")])
    run_with_low_threshold(monkeypatch, root, root / "out")
    rows = read_csv(root / "out/large_outputs_cold_archive_candidate_plan.csv")
    assert all(r["stage_dir"] != stage for r in rows)


def test_large_backtest_output_becomes_tier_b(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    stage = "V21.130_OLD_RANDOM_BACKTEST"
    write_stage(root, stage, {"result.csv": 300})
    write_registry(root, [registry_row(stage, "BACKTEST_RESULT", "REVIEW_COLD_ARCHIVE")])
    run_with_low_threshold(monkeypatch, root, root / "out")
    rows = read_csv(root / "out/large_outputs_cold_archive_candidate_plan.csv")
    assert rows[0]["cold_archive_candidate_tier"] == "TIER_B_COLD_ARCHIVE_REVIEW"


def test_large_unknown_becomes_tier_c(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    stage = "V21.099_OLD_UNKNOWN_OUTPUT"
    write_stage(root, stage, {"blob.bin": 300})
    write_registry(root, [registry_row(stage, "UNKNOWN_REVIEW_REQUIRED", "UNKNOWN_MANUAL_REVIEW")])
    run_with_low_threshold(monkeypatch, root, root / "out")
    rows = read_csv(root / "out/large_outputs_cold_archive_candidate_plan.csv")
    assert rows[0]["cold_archive_candidate_tier"] == "TIER_C_UNKNOWN_REVIEW_LARGE"
    assert rows[0]["compression_allowed_in_this_run"] == "False"
    assert rows[0]["deletion_allowed_in_this_run"] == "False"


def test_missing_protected_path_produces_fail(tmp_path, monkeypatch):
    root = make_repo(tmp_path, protected=False)
    stage = "V21.099_OLD_UNKNOWN_OUTPUT"
    write_stage(root, stage, {"blob.bin": 300})
    write_registry(root, [registry_row(stage, "UNKNOWN_REVIEW_REQUIRED", "UNKNOWN_MANUAL_REVIEW")])
    summary = run_with_low_threshold(monkeypatch, root, root / "out")
    assert summary["final_status"] == "FAIL_V21_214_PROTECTED_PATH_MISSING"


def test_summary_report_artifacts_written_and_no_mutation(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    stage = "V21.130_OLD_RANDOM_BACKTEST"
    write_stage(root, stage, {"result.csv": 300})
    write_registry(root, [registry_row(stage, "BACKTEST_RESULT", "REVIEW_COLD_ARCHIVE")])
    out = root / "out"
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
    summary = run_with_low_threshold(monkeypatch, root, out)
    after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if not p.is_relative_to(out))
    assert summary["final_status"] == "PASS_V21_214_COLD_ARCHIVE_CANDIDATE_PLAN_READY"
    for name in [
        "v21_214_summary.json",
        "V21.214_large_outputs_cold_archive_candidate_plan_report.txt",
        "large_outputs_cold_archive_candidate_plan.csv",
        "large_outputs_cold_archive_exclusion_check.csv",
        "large_outputs_candidate_file_manifest_preview.csv",
        "projected_savings_by_candidate.csv",
        "protected_path_presence_check.csv",
        "registry_input_check.csv",
    ]:
        assert (out / name).exists()
    assert [p for p in before if not p.startswith("out/")] == after
    assert summary["compression_performed"] is False
    assert summary["deletion_performed"] is False


def test_unhandled_exception_produces_fail(tmp_path):
    root = make_repo(tmp_path)
    summary = v214.run(root, out_dir=root / "out", simulate_exception=True)
    assert summary["final_status"] == "FAIL_V21_214_COLD_ARCHIVE_PLAN_EXCEPTION"
    assert summary["deletion_performed"] is False
