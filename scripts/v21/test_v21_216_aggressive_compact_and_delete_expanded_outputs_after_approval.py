from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_216_aggressive_compact_and_delete_expanded_outputs_after_approval.py")
spec = importlib.util.spec_from_file_location("v21_216", MODULE_PATH)
v216 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(v216)


def make_repo(tmp_path: Path, *, protected: bool = True, v154_zip: bool = True) -> Path:
    root = tmp_path / "repo"
    (root / ".venv/Scripts").mkdir(parents=True)
    (root / ".venv/Scripts/python.exe").write_text("python", encoding="utf-8")
    (root / ".venv_moomoo_py312/Scripts").mkdir(parents=True)
    (root / ".venv_moomoo_py312/Scripts/python.exe").write_text("python", encoding="utf-8")
    if protected:
        (root / "outputs/v20/price_history").mkdir(parents=True)
        (root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv").write_text("x\n", encoding="utf-8")
        for name in [
            "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
            "V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
            "V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
        ]:
            (root / "outputs/v21" / name).mkdir(parents=True, exist_ok=True)
    for stage in [v216.V154, v216.V140]:
        d = root / "outputs/v21" / stage
        d.mkdir(parents=True, exist_ok=True)
        (d / "a.csv").write_text(stage + "\n", encoding="utf-8")
        (d / "nested").mkdir(exist_ok=True)
        (d / "nested/b.txt").write_text("detail\n", encoding="utf-8")
    (root / v216.V215_AGG_SUMMARY_REL).parent.mkdir(parents=True, exist_ok=True)
    (root / v216.V215_AGG_SUMMARY_REL).write_text('{"projected_repo_size_after_aggressive_cleanup": 123}\n', encoding="utf-8")
    if v154_zip:
        v216.create_zip(root / "outputs/v21" / v216.V154, root / v216.V154_ZIP_REL, v216.V154)
    return root


def test_missing_approval_blocks_all_compression_deletion(tmp_path):
    root = make_repo(tmp_path)
    summary = v216.run(root, approval_phrase="", out_dir=root / "out")
    assert summary["final_status"] == "FAIL_V21_216_MANUAL_APPROVAL_MISSING"
    assert summary["deletion_performed"] is False
    assert summary["compression_performed"] is False
    assert (root / "outputs/v21" / v216.V154).exists()
    assert (root / "outputs/v21" / v216.V140).exists()


def test_wrong_approval_blocks_all_compression_deletion(tmp_path):
    root = make_repo(tmp_path)
    summary = v216.run(root, approval_phrase="WRONG", out_dir=root / "out")
    assert summary["final_status"] == "FAIL_V21_216_MANUAL_APPROVAL_MISSING"
    assert summary["deleted_count"] == 0


def test_exact_approval_allows_only_v21_154_and_v21_140(tmp_path):
    root = make_repo(tmp_path)
    summary = v216.run(root, approval_phrase=v216.APPROVAL_PHRASE, out_dir=root / "out")
    assert summary["approved_candidate_count"] == 2
    assert not (root / "outputs/v21" / v216.V154).exists()
    assert not (root / "outputs/v21" / v216.V140).exists()


def test_v21_154_requires_existing_valid_v215_zip(tmp_path):
    root = make_repo(tmp_path, v154_zip=False)
    summary = v216.run(root, approval_phrase=v216.APPROVAL_PHRASE, out_dir=root / "out")
    assert summary["final_status"] == "FAIL_V21_216_ZIP_INTEGRITY_FAILED"
    assert (root / "outputs/v21" / v216.V154).exists()


def test_v21_154_zip_integrity_failure_blocks_deletion(tmp_path):
    root = make_repo(tmp_path)
    (root / v216.V154_ZIP_REL).write_text("bad zip", encoding="utf-8")
    summary = v216.run(root, approval_phrase=v216.APPROVAL_PHRASE, out_dir=root / "out")
    assert summary["final_status"] == "FAIL_V21_216_ZIP_INTEGRITY_FAILED"
    assert (root / "outputs/v21" / v216.V154).exists()


def test_v21_140_is_zipped_before_deletion(tmp_path):
    root = make_repo(tmp_path)
    summary = v216.run(root, approval_phrase=v216.APPROVAL_PHRASE, out_dir=root / "out")
    assert summary["zip_created_count"] == 1
    assert (root / v216.ZIP_REL / v216.V140_ZIP_NAME).exists()


def test_v21_140_zip_integrity_failure_blocks_deletion(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    original = v216.zip_manifest

    def fake_zip_manifest(zip_path: Path, stage: str):
        if stage == v216.V140:
            return "", False, 0, 0
        return original(zip_path, stage)

    monkeypatch.setattr(v216, "zip_manifest", fake_zip_manifest)
    summary = v216.run(root, approval_phrase=v216.APPROVAL_PHRASE, out_dir=root / "out")
    assert summary["final_status"] == "FAIL_V21_216_ZIP_INTEGRITY_FAILED"
    assert (root / "outputs/v21" / v216.V140).exists()


def test_protected_current_chain_canonical_outputs_are_blocked(tmp_path):
    root = make_repo(tmp_path, protected=False)
    summary = v216.run(root, approval_phrase=v216.APPROVAL_PHRASE, out_dir=root / "out")
    assert summary["final_status"] == "FAIL_V21_216_PROTECTED_PATH_MISSING"


def test_zip_archives_are_not_deleted(tmp_path):
    root = make_repo(tmp_path)
    summary = v216.run(root, approval_phrase=v216.APPROVAL_PHRASE, out_dir=root / "out")
    assert summary["final_status"] == "PASS_V21_216_AGGRESSIVE_EXPANDED_OUTPUTS_DELETED_ZIPS_VERIFIED"
    assert (root / v216.V154_ZIP_REL).exists()
    assert (root / v216.ZIP_REL / v216.V140_ZIP_NAME).exists()


def test_successful_run_deletes_expanded_originals_but_keeps_zips(tmp_path):
    root = make_repo(tmp_path)
    summary = v216.run(root, approval_phrase=v216.APPROVAL_PHRASE, out_dir=root / "out")
    assert summary["deleted_count"] == 2
    assert summary["deleted_size_bytes"] > 0
    assert not (root / "outputs/v21" / v216.V154).exists()
    assert not (root / "outputs/v21" / v216.V140).exists()


def test_partial_windows_access_denied_returns_warn(tmp_path):
    root = make_repo(tmp_path)
    summary = v216.run(root, approval_phrase=v216.APPROVAL_PHRASE, out_dir=root / "out", simulate_access_denied_stage=v216.V140)
    assert summary["final_status"] == "WARN_V21_216_PARTIAL_DELETE_OR_ZIP_REUSE_ISSUE"
    assert not (root / "outputs/v21" / v216.V154).exists()
    assert (root / "outputs/v21" / v216.V140).exists()


def test_protected_paths_and_canonical_remain_present(tmp_path):
    root = make_repo(tmp_path)
    summary = v216.run(root, approval_phrase=v216.APPROVAL_PHRASE, out_dir=root / "out")
    assert summary["all_protected_paths_present_after"] is True
    assert summary["canonical_ohlcv_present_after"] is True
    assert (root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv").exists()


def test_summary_report_artifacts_written(tmp_path):
    root = make_repo(tmp_path)
    out = root / "out"
    v216.run(root, approval_phrase=v216.APPROVAL_PHRASE, out_dir=out)
    for name in [
        "v21_216_summary.json",
        "V21.216_aggressive_compact_and_delete_expanded_outputs_report.txt",
        "manual_approval_check.csv",
        "aggressive_candidate_execution_plan.csv",
        "pre_delete_source_manifest.csv",
        "zip_creation_or_reuse_result.csv",
        "zip_integrity_check.csv",
        "deletion_execution_result.csv",
        "post_delete_presence_check.csv",
        "protected_path_presence_check.csv",
        "compact_evidence_retention_manifest.csv",
        "aggressive_cleanup_reconciliation.csv",
    ]:
        assert (out / name).exists()


def test_unhandled_exception_produces_fail(tmp_path):
    root = make_repo(tmp_path)
    summary = v216.run(root, approval_phrase=v216.APPROVAL_PHRASE, out_dir=root / "out", simulate_exception=True)
    assert summary["final_status"] == "FAIL_V21_216_AGGRESSIVE_CLEANUP_EXCEPTION"
    assert summary["zip_archives_deleted"] is False
