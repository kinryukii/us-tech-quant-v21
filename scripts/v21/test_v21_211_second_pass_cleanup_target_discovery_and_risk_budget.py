from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import csv


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_211_second_pass_cleanup_target_discovery_and_risk_budget.py"
WRAPPER = ROOT / "scripts/v21/run_v21_211_second_pass_cleanup_target_discovery_and_risk_budget.ps1"


def load_module():
    spec = importlib.util.spec_from_file_location("v21_211", SCRIPT)
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


def add_venv(root: Path, name: str, version: str = "3.12.0", payload: int = 100) -> None:
    touch(root / f"{name}/pyvenv.cfg", f"version = {version}\n")
    touch(root / f"{name}/Scripts/python.exe", "python")
    touch(root / f"{name}/Lib/site-packages/pkg/payload.bin", "x" * payload)


def add_protected(root: Path, alias_201: bool = False) -> None:
    add_venv(root, ".venv", payload=50)
    touch(root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv", "date,close")
    touch(root / "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT/summary.json", "{}")
    touch(root / "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME/summary.json", "{}")
    if alias_201:
        touch(root / "outputs/v21/V21.201_DAILY_DRAM_PLAN_ALIAS/summary.json", "{}")
    else:
        touch(root / "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH/summary.json", "{}")
    for stage in [
        "V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION",
        "V21.208_ORIGINAL_REMOVAL_DRY_RUN_APPROVAL_GATE",
        "V21.209_DELETE_ORIGINALS_AFTER_ZIP_VERIFICATION",
        "V21.210_POST_CLEANUP_SIZE_AND_INTEGRITY_RECONCILIATION",
    ]:
        touch(root / f"outputs/v21/{stage}/summary.json", "{}")
    for stage in [
        "V21.141_EXTENDED_2020_MULTI_STRATEGY_RANDOM_BACKTEST",
        "V21.139_MULTI_STRATEGY_RANDOM_ASOF_BACKTEST",
        "V21.148_E_R1_A1_PIT_LITE_REPLAY_DIAGNOSTIC_ONLY",
    ]:
        touch(root / f"archive/v21_compressed_stage_copies/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION/{stage}__V21.207_COMPRESS_ONLY_COPY.zip", "zip")


def add_outputs(root: Path) -> None:
    touch(root / "outputs/v21/V21.154_E_R1_INVALID_TRIAL_REPAIR_AND_REPLAY_REAUDIT/invalid_trial_replay_report.txt", "audit" * 200)
    touch(root / "outputs/v21/V21.120_OLD_HISTORICAL_RESEARCH_STAGE/summary.json", "{}")
    touch(root / "outputs/v21/V21.120_OLD_HISTORICAL_RESEARCH_STAGE/report.txt", "report")
    touch(root / "outputs/v21/V21.120_OLD_HISTORICAL_RESEARCH_STAGE/intermediate.csv", "a,b\n" + "1,2\n" * 500)
    touch(root / "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT/ranking.csv", "rank")


def add_state_archive(root: Path) -> None:
    touch(root / "state/cache.tmp", "cache")
    touch(root / "state/current_state_manifest.json", "{}")
    touch(root / "archive/manual_backup.zip", "zip")


def make_repo(tmp_path: Path, protected: bool = True, alias_201: bool = False, alt_venv: bool = True):
    module = load_module()
    root = tmp_path / "repo"
    if protected:
        add_protected(root, alias_201=alias_201)
    if alt_venv:
        add_venv(root, ".venv_moomoo_py312", payload=75)
    add_outputs(root)
    add_state_archive(root)
    return module, root


def test_venv_classified_as_must_keep_current_env(tmp_path):
    module, root = make_repo(tmp_path)
    module.run(root)
    venv = rows(root / module.OUT_REL / "virtualenv_retirement_candidate_audit.csv")
    current = [row for row in venv if row["path"] == ".venv"][0]
    assert current["risk_class"] == "MUST_KEEP_CURRENT_ENV"
    assert current["current_project_env_flag"] == "True"


def test_alt_venv_classified_possible_unused_review(tmp_path):
    module, root = make_repo(tmp_path)
    summary = module.run(root)
    venv = rows(root / module.OUT_REL / "virtualenv_retirement_candidate_audit.csv")
    alt = [row for row in venv if row["path"] == ".venv_moomoo_py312"][0]
    assert alt["risk_class"] == "POSSIBLE_UNUSED_VIRTUALENV_REVIEW"
    assert alt["retirement_candidate_flag"] == "True"
    assert summary["alternate_venv_candidate_count"] == 1


def test_protected_canonical_price_file_excluded_from_deletion(tmp_path):
    module, root = make_repo(tmp_path)
    module.run(root)
    targets = rows(root / module.OUT_REL / "cleanup_target_risk_budget.csv")
    assert all(row["deletion_candidate_now"] == "False" for row in targets)
    presence = rows(root / module.OUT_REL / "protected_path_presence_check.csv")
    canonical = [row for row in presence if row["protected_key"] == "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"][0]
    assert canonical["resolved_exists"] == "True"


def test_protected_stages_and_v21_201_alias_excluded(tmp_path):
    module, root = make_repo(tmp_path, alias_201=True)
    summary = module.run(root)
    presence = rows(root / module.OUT_REL / "protected_path_presence_check.csv")
    row201 = [row for row in presence if row["protected_key"].startswith("V21.201")][0]
    assert summary["final_status"] == "PASS_V21_211_SECOND_PASS_TARGET_DISCOVERY_READY"
    assert row201["resolution_method"] == "ALIAS_DISCOVERY_NEWEST_MODIFIED"
    historical = rows(root / module.OUT_REL / "large_historical_output_cold_archive_candidate_audit.csv")
    protected_rows = [row for row in historical if row["stage_name"].startswith(("V21.197", "V21.199", "V21.201"))]
    assert all(row["risk_class"] == "MUST_KEEP_CURRENT_CHAIN_OUTPUT" for row in protected_rows)


def test_archive_v21_207_zip_copies_kept(tmp_path):
    module, root = make_repo(tmp_path)
    module.run(root)
    archive = rows(root / module.OUT_REL / "archive_directory_retention_audit.csv")
    assert archive[0]["risk_class"] == "ARCHIVE_BACKUP_KEEP"
    assert archive[0]["v21_207_zip_copies_present"] == "True"
    assert archive[0]["deletion_candidate_now"] == "False"


def test_state_directory_audited_not_deleted(tmp_path):
    module, root = make_repo(tmp_path)
    module.run(root)
    state = rows(root / module.OUT_REL / "state_directory_cleanup_candidate_audit.csv")
    assert state[0]["risk_class"] == "STATE_CACHE_REVIEW"
    assert state[0]["deletion_candidate_now"] == "False"
    assert (root / "state/cache.tmp").is_file()


def test_v21_154_classified_audit_critical_history(tmp_path):
    module, root = make_repo(tmp_path)
    module.run(root)
    historical = rows(root / module.OUT_REL / "large_historical_output_cold_archive_candidate_audit.csv")
    row154 = [row for row in historical if row["stage_name"].startswith("V21.154")][0]
    assert row154["risk_class"] == "KEEP_AUDIT_CRITICAL_HISTORY"


def test_large_historical_output_can_be_cold_archive_candidate(tmp_path):
    module, root = make_repo(tmp_path)
    summary = module.run(root)
    historical = rows(root / module.OUT_REL / "large_historical_output_cold_archive_candidate_audit.csv")
    old = [row for row in historical if row["stage_name"].startswith("V21.120")][0]
    assert old["risk_class"] == "COLD_ARCHIVE_COMPRESSION_REVIEW"
    assert old["cold_archive_review_candidate_flag"] == "True"
    assert summary["cold_archive_review_candidate_count"] >= 1


def test_no_immediate_deletion_candidates_by_default(tmp_path):
    module, root = make_repo(tmp_path)
    summary = module.run(root)
    targets = rows(root / module.OUT_REL / "cleanup_target_risk_budget.csv")
    assert summary["immediate_deletion_candidate_count"] == 0
    assert all(row["deletion_candidate_now"] == "False" for row in targets)
    assert all(row["compression_candidate_now"] == "False" for row in targets)


def test_protected_path_missing_produces_warn(tmp_path):
    module, root = make_repo(tmp_path, protected=False)
    summary = module.run(root)
    assert summary["final_status"] == "WARN_V21_211_PROTECTED_PATH_MISSING"
    assert summary["final_decision"] == "SECOND_PASS_CLEANUP_WARN_PROTECTED_PATH_MISSING"


def test_summary_report_artifacts_written(tmp_path):
    module, root = make_repo(tmp_path)
    summary = module.run(root)
    out = root / module.OUT_REL
    for name in [
        "v21_211_summary.json",
        "V21.211_second_pass_cleanup_target_discovery_report.txt",
        "repo_second_pass_top_level_size.csv",
        "repo_second_pass_largest_directories.csv",
        "repo_second_pass_largest_files.csv",
        "cleanup_target_risk_budget.csv",
        "virtualenv_retirement_candidate_audit.csv",
        "state_directory_cleanup_candidate_audit.csv",
        "archive_directory_retention_audit.csv",
        "large_historical_output_cold_archive_candidate_audit.csv",
        "protected_path_presence_check.csv",
    ]:
        assert (out / name).is_file()
    payload = json.loads((out / "v21_211_summary.json").read_text(encoding="utf-8"))
    assert payload["final_status"] == summary["final_status"]


def test_no_mutation_behavior(tmp_path):
    module, root = make_repo(tmp_path)
    watched = root / "state/current_state_manifest.json"
    before = watched.read_text(encoding="utf-8")
    module.run(root)
    assert watched.read_text(encoding="utf-8") == before
    assert (root / ".venv").is_dir()
    assert (root / ".venv_moomoo_py312").is_dir()


def test_unhandled_exception_produces_fail(tmp_path):
    module, root = make_repo(tmp_path)
    summary = module.run(root, simulate_exception=True)
    assert summary["final_status"] == "FAIL_V21_211_SECOND_PASS_DISCOVERY_EXCEPTION"
    assert summary["final_decision"] == "SECOND_PASS_CLEANUP_DISCOVERY_FAILED"


def test_wrapper_exists_and_uses_venv_python():
    assert WRAPPER.is_file()
    text = WRAPPER.read_text(encoding="utf-8")
    assert ".venv\\Scripts\\python.exe" in text
    assert "v21_211_second_pass_cleanup_target_discovery_and_risk_budget.py" in text
