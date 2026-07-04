from __future__ import annotations

import csv
import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_220_post_aggressive_delete_remaining_footprint_and_final_prune_plan.py")
spec = importlib.util.spec_from_file_location("v21_220", MODULE_PATH)
v220 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(v220)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def touch(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_repo(tmp_path: Path, *, protected: bool = True) -> Path:
    root = tmp_path / "repo"
    touch(root / ".venv/Scripts/python.exe")
    touch(root / ".venv_moomoo_py312/Scripts/python.exe")
    touch(root / "scripts/v21/current.py")
    if protected:
        touch(root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")
        for name in [
            "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
            "V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
            "V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
            "V21.219_DELETE_ARCHIVE_AND_HISTORICAL_OUTPUTS_AFTER_APPROVAL",
            "V21.220_POST_AGGRESSIVE_DELETE_REMAINING_FOOTPRINT_AND_FINAL_PRUNE_PLAN",
        ]:
            touch(root / "outputs/v21" / name / "summary.json")
    return root


def test_protected_current_chain_canonical_paths_excluded(tmp_path):
    root = make_repo(tmp_path)
    summary = v220.run(root, out_dir=root / "out")
    rows = read_csv(root / "out/final_prune_candidate_plan.csv")
    assert all("V21.197" not in r["candidate_path"] for r in rows if r["candidate_type"] != "NOT_CANDIDATE_PROTECTED")
    assert all("V20_199D_CANONICAL" not in r["candidate_path"] for r in rows)
    assert summary["protected_path_missing_count"] == 0


def test_scripts_and_venv_are_excluded(tmp_path):
    root = make_repo(tmp_path)
    v220.run(root, out_dir=root / "out")
    rows = read_csv(root / "out/final_prune_candidate_plan.csv")
    assert all(not r["candidate_path"].startswith("scripts") for r in rows if r["candidate_type"] != "NOT_CANDIDATE_PROTECTED")
    assert all(r["candidate_path"] != ".venv" for r in rows)


def test_failed_v21_177_pytest_tmp_residue_becomes_retry_candidate(tmp_path):
    root = make_repo(tmp_path)
    touch(root / "outputs/v21/V21.177_R1A_STALENESS_SEMANTIC_REPAIR/pytest_tmp_abc/file.tmp")
    v220.run(root, out_dir=root / "out")
    rows = read_csv(root / "out/failed_delete_retry_plan.csv")
    assert any(r["candidate_type"] == "FAILED_DELETE_RETRY_CACHE_RESIDUE" for r in rows)


def test_non_current_state_cache_becomes_candidate(tmp_path):
    root = make_repo(tmp_path)
    touch(root / "state/cache/old.tmp")
    v220.run(root, out_dir=root / "out")
    rows = read_csv(root / "out/non_current_state_cache_prune_plan.csv")
    assert any(r["candidate_type"] == "NON_CURRENT_STATE_CACHE" for r in rows)


def test_old_cleanup_proof_outputs_candidate_except_v219_v220(tmp_path):
    root = make_repo(tmp_path)
    touch(root / "outputs/v21/V21.216_AGGRESSIVE_COMPACT_AND_DELETE_EXPANDED_OUTPUTS_AFTER_APPROVAL/summary.json")
    v220.run(root, out_dir=root / "out")
    rows = read_csv(root / "out/proof_chain_compaction_plan.csv")
    assert any("V21.216" in r["candidate_path"] for r in rows)
    assert all("V21.219" not in r["candidate_path"] for r in rows)
    assert all("V21.220" not in r["candidate_path"] for r in rows)


def test_non_current_residual_outputs_v21_candidate(tmp_path):
    root = make_repo(tmp_path)
    touch(root / "outputs/v21/V21.123_OLD_RESIDUAL/summary.json")
    v220.run(root, out_dir=root / "out")
    rows = read_csv(root / "out/final_prune_candidate_plan.csv")
    assert any(r["candidate_type"] == "NON_CURRENT_OUTPUTS_V21_RESIDUAL" for r in rows)


def test_alt_venv_is_review_candidate_not_deletion_in_this_stage(tmp_path):
    root = make_repo(tmp_path)
    v220.run(root, out_dir=root / "out")
    rows = read_csv(root / "out/final_prune_candidate_plan.csv")
    alt = next(r for r in rows if r["candidate_path"] == ".venv_moomoo_py312")
    assert alt["candidate_type"] in {"ALT_VENV_RETIREMENT_REVIEW", "NOT_CANDIDATE_PROTECTED"}
    assert alt["deletion_allowed_in_this_run"] == "False"


def test_deletion_allowed_always_false_and_projection_calculated(tmp_path):
    root = make_repo(tmp_path)
    touch(root / "outputs/v21/V21.123_OLD_RESIDUAL/summary.json")
    summary = v220.run(root, out_dir=root / "out")
    rows = read_csv(root / "out/final_prune_candidate_plan.csv")
    assert all(r["deletion_allowed_in_this_run"] == "False" for r in rows)
    assert summary["projected_repo_size_after_final_prune"] >= 0
    assert summary["required_manual_approval_phrase"] == v220.APPROVAL_PHRASE


def test_protected_path_missing_produces_fail(tmp_path):
    root = make_repo(tmp_path, protected=False)
    summary = v220.run(root, out_dir=root / "out")
    assert summary["final_status"] == "FAIL_V21_220_PROTECTED_PATH_MISSING"


def test_summary_report_artifacts_written_and_no_mutation(tmp_path):
    root = make_repo(tmp_path)
    out = root / "out"
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
    summary = v220.run(root, out_dir=out)
    after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if not p.is_relative_to(out))
    for name in [
        "v21_220_summary.json",
        "V21.220_post_aggressive_delete_remaining_footprint_report.txt",
        "remaining_repo_top_level_size.csv",
        "remaining_largest_directories.csv",
        "remaining_largest_files.csv",
        "remaining_outputs_v21_stage_size.csv",
        "final_prune_candidate_plan.csv",
        "current_chain_minimal_keep_manifest.csv",
        "non_current_state_cache_prune_plan.csv",
        "failed_delete_retry_plan.csv",
        "proof_chain_compaction_plan.csv",
        "projected_repo_size_after_final_prune.csv",
        "protected_path_presence_check.csv",
        "manual_approval_checklist.csv",
    ]:
        assert (out / name).exists()
    assert [p for p in before if not p.startswith("out/")] == after
    assert summary["deletion_performed"] is False
    assert summary["moomoo_broker_connection_performed"] is False


def test_unhandled_exception_produces_fail(tmp_path):
    root = make_repo(tmp_path)
    summary = v220.run(root, out_dir=root / "out", simulate_exception=True)
    assert summary["final_status"] == "FAIL_V21_220_FINAL_PRUNE_PLAN_EXCEPTION"
    assert summary["deletion_performed"] is False
