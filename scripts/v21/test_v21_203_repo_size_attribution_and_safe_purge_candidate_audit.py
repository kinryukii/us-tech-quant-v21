from __future__ import annotations

import csv
import importlib.util
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_203_repo_size_attribution_and_safe_purge_candidate_audit.py"
WRAPPER = ROOT / "scripts/v21/run_v21_203_repo_size_attribution_and_safe_purge_candidate_audit.ps1"


def load_module():
    spec = importlib.util.spec_from_file_location("v21_203", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def make_repo(tmp_path: Path, include_all_protected: bool = True, v21_201_name: str = "V21.201_DRAM_MOOMOO_R4_PLAN_READY") -> Path:
    root = tmp_path / "repo"
    touch(root / ".venv/pyvenv.cfg")
    touch(root / ".pytest_cache/CACHEDIR.TAG")
    touch(root / "pkg/__pycache__/x.pyc")
    touch(root / "outputs/v21/pytest_tmp_abc/foo.tmp")
    touch(root / ".mypy_cache/meta.json")
    touch(root / ".ruff_cache/cache")
    touch(root / "not_protected.tmp", "")
    touch(root / "outputs/v21/V21.150_OLD/history.csv", "old")
    touch(root / "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT/ranking.csv")
    touch(root / "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME/summary.json")
    touch(root / "outputs/v21/V21.202_REPO_SAFE_CLEANUP_AUDIT_AND_CACHE_PURGE/v21_202_summary.json")
    touch(root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")
    if include_all_protected:
        touch(root / f"outputs/v21/{v21_201_name}/plan.json")
    return root


def test_no_mutation_behavior(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    protected = root / "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT/ranking.csv"
    before = protected.read_text(encoding="utf-8")
    summary = module.run(root)
    assert summary["deletion_performed"] is False
    assert protected.read_text(encoding="utf-8") == before
    assert (root / ".pytest_cache").exists()


def test_protected_path_detection(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    protected, reason = module.is_protected_path(root / "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME/summary.json", root)
    assert protected is True
    assert "protected" in reason


def test_venv_never_classified_as_safe_purge_candidate(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    candidates = module.safe_purge_candidate_audit(root)
    assert not any(row["path"].startswith(".venv") for row in candidates)


def test_canonical_price_file_never_classified_as_safe_purge_candidate(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    candidates = module.safe_purge_candidate_audit(root)
    assert not any("V20_199D_CANONICAL_HISTORICAL_OHLCV.csv" in row["path"] for row in candidates)


def test_pycache_classified_as_candidate(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    candidates = module.safe_purge_candidate_audit(root)
    assert any(row["candidate_type"] == "__pycache__" for row in candidates)


def test_pytest_cache_classified_as_candidate(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    candidates = module.safe_purge_candidate_audit(root)
    assert any(row["candidate_type"] == ".pytest_cache" for row in candidates)


def test_pytest_tmp_classified_as_candidate(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    candidates = module.safe_purge_candidate_audit(root)
    assert any(row["candidate_type"] == "pytest_tmp" for row in candidates)


def test_current_protected_v21_stage_dirs_excluded(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    candidates = module.safe_purge_candidate_audit(root)
    assert not any("V21.197_FINAL" in row["path"] or "V21.199_R4" in row["path"] or "V21.201_DRAM" in row["path"] for row in candidates)


def test_report_artifacts_written(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    module.run(root)
    out = root / module.OUT_REL
    for name in [
        "v21_203_summary.json",
        "V21.203_repo_size_attribution_report.txt",
        "repo_top_level_size_summary.csv",
        "repo_largest_directories.csv",
        "repo_largest_files.csv",
        "outputs_v21_stage_size_summary.csv",
        "safe_purge_candidate_audit.csv",
        "protected_path_presence_check.csv",
    ]:
        assert (out / name).is_file()


def test_summary_fields_valid(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    summary = module.run(root)
    assert summary["final_status"] == "PASS_V21_203_REPO_SIZE_ATTRIBUTION_READY"
    assert summary["final_decision"] == "REPO_SIZE_ATTRIBUTION_READY_NO_MUTATION"
    assert summary["research_only"] is True
    assert summary["mutation_allowed"] is False
    assert summary["deletion_performed"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False
    assert summary["protected_outputs_modified"] is False
    assert summary["protected_missing_expected_count"] == 0
    assert summary["protected_missing_after_alias_resolution_count"] == 0


def test_exact_protected_path_exists_pass(tmp_path):
    module = load_module()
    root = make_repo(tmp_path, include_all_protected=True)
    summary = module.run(root)
    presence = rows(root / module.OUT_REL / "protected_path_presence_check.csv")
    row = next(r for r in presence if r["protected_key"] == "V21.201_DRAM_MOOMOO_R4_PLAN_READY")
    assert summary["final_status"] == "PASS_V21_203_REPO_SIZE_ATTRIBUTION_READY"
    assert row["exact_exists"] == "True"
    assert row["resolution_method"] == "EXACT_PATH"


def test_exact_missing_but_v21_201_dram_alias_exists_pass(tmp_path):
    module = load_module()
    root = make_repo(tmp_path, include_all_protected=False)
    touch(root / "outputs/v21/V21.201_DAILY_DRAM_MOOMOO_R4_PLAN_REFRESH/plan.json")
    summary = module.run(root)
    presence = rows(root / module.OUT_REL / "protected_path_presence_check.csv")
    row = next(r for r in presence if r["protected_key"] == "V21.201_DRAM_MOOMOO_R4_PLAN_READY")
    assert summary["final_status"] == "PASS_V21_203_REPO_SIZE_ATTRIBUTION_READY"
    assert summary["protected_missing_expected_count"] == 1
    assert summary["protected_missing_after_alias_resolution_count"] == 0
    assert summary["protected_alias_resolved_count"] == 1
    assert summary["protected_alias_resolution_used"] is True
    assert row["exact_exists"] == "False"
    assert row["resolved_exists"] == "True"
    assert row["resolution_method"] == "ALIAS_DISCOVERY_NEWEST_MODIFIED"
    assert row["resolved_protected_path"].endswith("V21.201_DAILY_DRAM_MOOMOO_R4_PLAN_REFRESH")


def test_multiple_alias_candidates_newest_selected_and_all_logged(tmp_path):
    module = load_module()
    root = make_repo(tmp_path, include_all_protected=False)
    old_file = touch(root / "outputs/v21/V21.201_DRAM_OLD/plan.json")
    new_file = touch(root / "outputs/v21/V21.201_MOOMOO_R4_DAILY_NEW/plan.json")
    old_ts = 1000
    new_ts = 2000
    os.utime(old_file.parent, (old_ts, old_ts))
    os.utime(new_file.parent, (new_ts, new_ts))
    summary = module.run(root)
    presence = rows(root / module.OUT_REL / "protected_path_presence_check.csv")
    row = next(r for r in presence if r["protected_key"] == "V21.201_DRAM_MOOMOO_R4_PLAN_READY")
    assert summary["final_status"] == "PASS_V21_203_REPO_SIZE_ATTRIBUTION_READY"
    assert row["alias_candidate_count"] == "2"
    assert "V21.201_DRAM_OLD" in row["alias_candidates"]
    assert "V21.201_MOOMOO_R4_DAILY_NEW" in row["alias_candidates"]
    assert row["resolved_protected_path"].endswith("V21.201_MOOMOO_R4_DAILY_NEW")


def test_missing_protected_path_produces_warn(tmp_path):
    module = load_module()
    root = make_repo(tmp_path, include_all_protected=False)
    summary = module.run(root)
    assert summary["final_status"] == "WARN_V21_203_PROTECTED_PATH_MISSING"
    assert summary["final_decision"] == "REPO_SIZE_ATTRIBUTION_WARN_PROTECTED_PATH_MISSING"
    assert summary["protected_missing_after_alias_resolution_count"] >= 1


def test_unrelated_v21_201_temp_cache_alias_not_accepted(tmp_path):
    module = load_module()
    root = make_repo(tmp_path, include_all_protected=False)
    touch(root / "outputs/v21/V21.201_TMP_CACHE/junk.txt")
    summary = module.run(root)
    presence = rows(root / module.OUT_REL / "protected_path_presence_check.csv")
    row = next(r for r in presence if r["protected_key"] == "V21.201_DRAM_MOOMOO_R4_PLAN_READY")
    assert summary["final_status"] == "WARN_V21_203_PROTECTED_PATH_MISSING"
    assert row["alias_candidate_count"] == "0"
    assert row["resolved_exists"] == "False"


def test_audit_exception_produces_fail(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    summary = module.run(root, simulate_exception=True)
    assert summary["final_status"] == "FAIL_V21_203_AUDIT_EXCEPTION"
    assert summary["final_decision"] == "REPO_SIZE_ATTRIBUTION_FAILED"
    assert summary["deletion_performed"] is False


def test_wrapper_exists_and_references_venv_python():
    assert WRAPPER.is_file()
    text = WRAPPER.read_text(encoding="utf-8")
    assert ".venv\\Scripts\\python.exe" in text
    assert "v21_203_repo_size_attribution_and_safe_purge_candidate_audit.py" in text


def test_outputs_v21_stage_size_summary_generated(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    module.run(root)
    stage_rows = rows(root / module.OUT_REL / "outputs_v21_stage_size_summary.csv")
    assert any(row["stage_name"] == "V21.150_OLD" for row in stage_rows)
