from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_219_delete_archive_and_historical_outputs_after_approval.py")
spec = importlib.util.spec_from_file_location("v21_219", MODULE_PATH)
v219 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(v219)


def touch(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    touch(root / ".venv/Scripts/python.exe")
    touch(root / ".venv_moomoo_py312/Scripts/python.exe")
    touch(root / "scripts/v21/current.py")
    touch(root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")
    for name in [
        "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
        "V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
        "V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
        "V21.215_AGGRESSIVE_COMPACT_OUTPUT_POLICY_AND_STORAGE_BUDGET_ENFORCER",
        "V21.216_AGGRESSIVE_COMPACT_AND_DELETE_EXPANDED_OUTPUTS_AFTER_APPROVAL",
        "V21.217_GLOBAL_HISTORICAL_OUTPUT_RETENTION_PRUNE_PLAN",
        "V21.219_DELETE_ARCHIVE_AND_HISTORICAL_OUTPUTS_AFTER_APPROVAL",
        "V21.190_OLD_HISTORICAL_STAGE",
        "V21.185_DRAM_INTRADAY_TRIGGER_EVENT_ARCHIVE_AND_DAILY_APPEND",
        "FULL_SYSTEM_LATEST_RERUN_ABCDEF",
    ]:
        touch(root / "outputs/v21" / name / "summary.json")
    touch(root / "archive/v21_cold_archive_stage_copies/old.zip")
    touch(root / "state/cache/tmp.bin")
    touch(root / ".pytest_cache/CACHEDIR.TAG")
    touch(root / "scripts/v21/__pycache__/x.pyc")
    return root


def test_missing_approval_blocks_deletion(tmp_path):
    root = make_repo(tmp_path)
    summary = v219.run(root, approval_phrase="", out_dir=root / "out")
    assert summary["final_status"] == "FAIL_V21_219_MANUAL_APPROVAL_MISSING"
    assert summary["deletion_performed"] is False
    assert (root / "archive").exists()
    assert (root / "outputs/v21/V21.190_OLD_HISTORICAL_STAGE").exists()


def test_wrong_approval_blocks_deletion(tmp_path):
    root = make_repo(tmp_path)
    summary = v219.run(root, approval_phrase="WRONG", out_dir=root / "out")
    assert summary["final_status"] == "FAIL_V21_219_MANUAL_APPROVAL_MISSING"
    assert (root / "archive").exists()


def test_exact_approval_allows_archive_deletion(tmp_path):
    root = make_repo(tmp_path)
    summary = v219.run(root, approval_phrase=v219.APPROVAL_PHRASE, out_dir=root / "out")
    assert summary["archive_deleted"] is True
    assert not (root / "archive").exists()


def test_exact_approval_allows_non_current_historical_outputs_deletion(tmp_path):
    root = make_repo(tmp_path)
    summary = v219.run(root, approval_phrase=v219.APPROVAL_PHRASE, out_dir=root / "out")
    assert summary["historical_outputs_deleted_count"] >= 1
    assert not (root / "outputs/v21/V21.190_OLD_HISTORICAL_STAGE").exists()


def test_protected_current_chain_stages_are_never_deleted(tmp_path):
    root = make_repo(tmp_path)
    v219.run(root, approval_phrase=v219.APPROVAL_PHRASE, out_dir=root / "out")
    assert (root / "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT").exists()
    assert (root / "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME").exists()
    assert (root / "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH").exists()


def test_canonical_ohlcv_is_never_deleted(tmp_path):
    root = make_repo(tmp_path)
    v219.run(root, approval_phrase=v219.APPROVAL_PHRASE, out_dir=root / "out")
    assert (root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv").exists()


def test_scripts_and_venv_are_never_deleted(tmp_path):
    root = make_repo(tmp_path)
    v219.run(root, approval_phrase=v219.APPROVAL_PHRASE, out_dir=root / "out")
    assert (root / "scripts/v21/current.py").exists()
    assert (root / ".venv/Scripts/python.exe").exists()


def test_alt_venv_retained_for_now(tmp_path):
    root = make_repo(tmp_path)
    v219.run(root, approval_phrase=v219.APPROVAL_PHRASE, out_dir=root / "out")
    assert (root / ".venv_moomoo_py312/Scripts/python.exe").exists()


def test_latest_dram_abcde_moomoo_outputs_retained(tmp_path):
    root = make_repo(tmp_path)
    v219.run(root, approval_phrase=v219.APPROVAL_PHRASE, out_dir=root / "out")
    assert (root / "outputs/v21/V21.185_DRAM_INTRADAY_TRIGGER_EVENT_ARCHIVE_AND_DAILY_APPEND").exists()
    assert (root / "outputs/v21/FULL_SYSTEM_LATEST_RERUN_ABCDEF").exists()


def test_v21_215_plus_cleanup_proof_chain_retained(tmp_path):
    root = make_repo(tmp_path)
    v219.run(root, approval_phrase=v219.APPROVAL_PHRASE, out_dir=root / "out")
    assert (root / "outputs/v21/V21.215_AGGRESSIVE_COMPACT_OUTPUT_POLICY_AND_STORAGE_BUDGET_ENFORCER").exists()
    assert (root / "outputs/v21/V21.216_AGGRESSIVE_COMPACT_AND_DELETE_EXPANDED_OUTPUTS_AFTER_APPROVAL").exists()
    assert (root / "outputs/v21/V21.217_GLOBAL_HISTORICAL_OUTPUT_RETENTION_PRUNE_PLAN").exists()
    assert (root / "outputs/v21/V21.219_DELETE_ARCHIVE_AND_HISTORICAL_OUTPUTS_AFTER_APPROVAL").exists()


def test_hard_keep_overlap_blocks_candidate(tmp_path):
    root = make_repo(tmp_path)
    presence = v219.protected_presence(root)
    plan, _keep = v219.build_plan(root, presence)
    protected_rows = [row for row in plan if row["current_chain_overlap_flag"] or row["hard_keep_overlap_flag"] or row["canonical_overlap_flag"]]
    assert all(not row["deletion_allowed_after_checks"] for row in protected_rows)


def test_partial_access_denied_returns_warn(tmp_path):
    root = make_repo(tmp_path)
    summary = v219.run(root, approval_phrase=v219.APPROVAL_PHRASE, out_dir=root / "out", simulate_access_denied="V21.190_OLD_HISTORICAL_STAGE")
    assert summary["final_status"] == "WARN_V21_219_PARTIAL_DELETE_WITH_PROTECTED_SAFE"
    assert (root / "outputs/v21/V21.190_OLD_HISTORICAL_STAGE").exists()


def test_protected_paths_remain_present_after_deletion(tmp_path):
    root = make_repo(tmp_path)
    summary = v219.run(root, approval_phrase=v219.APPROVAL_PHRASE, out_dir=root / "out")
    assert summary["protected_path_missing_count_after"] == 0


def test_repo_size_snapshot_and_artifacts_written(tmp_path):
    root = make_repo(tmp_path)
    out = root / "out"
    v219.run(root, approval_phrase=v219.APPROVAL_PHRASE, out_dir=out)
    for name in [
        "v21_219_summary.json",
        "V21.219_delete_archive_and_historical_outputs_report.txt",
        "manual_approval_check.csv",
        "aggressive_delete_plan.csv",
        "protected_keep_manifest.csv",
        "deleted_path_manifest.csv",
        "deletion_execution_result.csv",
        "post_delete_repo_size_snapshot.csv",
        "post_delete_protected_path_presence_check.csv",
        "post_delete_current_chain_sanity_check.csv",
        "rollback_not_available_notice.txt",
    ]:
        assert (out / name).exists()


def test_unhandled_exception_produces_fail(tmp_path):
    root = make_repo(tmp_path)
    summary = v219.run(root, approval_phrase=v219.APPROVAL_PHRASE, out_dir=root / "out", simulate_exception=True)
    assert summary["final_status"] == "FAIL_V21_219_DELETE_EXCEPTION"
