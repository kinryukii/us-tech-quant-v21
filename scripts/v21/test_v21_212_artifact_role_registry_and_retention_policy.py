from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_212_artifact_role_registry_and_retention_policy.py"
WRAPPER = ROOT / "scripts/v21/run_v21_212_artifact_role_registry_and_retention_policy.ps1"


def load_module():
    spec = importlib.util.spec_from_file_location("v21_212", SCRIPT)
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


def add_repo(root: Path, alias_201: bool = False, unknown: bool = False, protected: bool = True):
    if protected:
        touch(root / ".venv/pyvenv.cfg", "version = 3.12.0")
        touch(root / ".venv/Scripts/python.exe", "python")
        touch(root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv", "date,close")
        touch(root / "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT/ranking.csv", "rank")
        touch(root / "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME/moomoo_kline_summary.json", "{}")
        if alias_201:
            touch(root / "outputs/v21/V21.201_DAILY_DRAM_PLAN_ALIAS/dram_plan.json", "{}")
        else:
            touch(root / "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH/dram_plan.json", "{}")
        for stage in [
            "V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION",
            "V21.208_ORIGINAL_REMOVAL_DRY_RUN_APPROVAL_GATE",
            "V21.209_DELETE_ORIGINALS_AFTER_ZIP_VERIFICATION",
            "V21.210_POST_CLEANUP_SIZE_AND_INTEGRITY_RECONCILIATION",
            "V21.211_SECOND_PASS_CLEANUP_TARGET_DISCOVERY_AND_RISK_BUDGET",
        ]:
            touch(root / f"outputs/v21/{stage}/summary.json", "{}")
        touch(root / "archive/v21_compressed_stage_copies/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION/V21.139_MULTI_STRATEGY_RANDOM_ASOF_BACKTEST__V21.207_COMPRESS_ONLY_COPY.zip", "zip")
        touch(root / "archive/v21_compressed_stage_copies/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION/V21.141_EXTENDED_2020_MULTI_STRATEGY_RANDOM_BACKTEST__V21.207_COMPRESS_ONLY_COPY.zip", "zip")
        touch(root / "archive/v21_compressed_stage_copies/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION/V21.148_E_R1_A1_PIT_LITE_REPLAY_DIAGNOSTIC_ONLY__V21.207_COMPRESS_ONLY_COPY.zip", "zip")
    touch(root / ".venv_moomoo_py312/pyvenv.cfg", "version = 3.12.0")
    touch(root / ".venv_moomoo_py312/Scripts/python.exe", "python")
    touch(root / "state/runtime_state.json", "{}")
    touch(root / "outputs/v21/V21.154_E_R1_INVALID_TRIAL_REPAIR_AND_REPLAY_REAUDIT/invalid_trial_replay_report.txt", "audit")
    touch(root / "outputs/v21/V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020/price_history_panel.csv", "price")
    if unknown:
        touch(root / "outputs/v21/V21.999_MISC/thing.bin", "unknown")


def run_repo(tmp_path: Path, **kwargs):
    module = load_module()
    root = tmp_path / "repo"
    add_repo(root, **kwargs)
    summary = module.run(root)
    reg = rows(root / module.OUT_REL / "artifact_registry.csv")
    return module, root, summary, reg


def find(reg, contains: str):
    matches = [row for row in reg if contains in row["artifact_path"]]
    assert matches, contains
    return matches[0]


def test_canonical_price_file_classified(tmp_path):
    _m, _r, _s, reg = run_repo(tmp_path)
    row = find(reg, "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")
    assert row["artifact_role"] == "CANONICAL_PRICE_SOURCE"
    assert row["retention_class"] == "RETAIN_CANONICAL_SOURCE"


def test_venv_classified_current_environment(tmp_path):
    _m, _r, _s, reg = run_repo(tmp_path)
    row = find(reg, ".venv")
    assert row["artifact_role"] == "CURRENT_ENVIRONMENT"
    assert row["retention_class"] == "RETAIN_PROTECTED_CURRENT_CHAIN"


def test_alt_venv_classified_review(tmp_path):
    _m, _r, _s, reg = run_repo(tmp_path)
    row = find(reg, ".venv_moomoo_py312")
    assert row["artifact_role"] == "ALTERNATE_ENVIRONMENT_REVIEW"


def test_v21_197_classified_abcde_or_current_protected(tmp_path):
    _m, _r, _s, reg = run_repo(tmp_path)
    row = find(reg, "V21.197")
    assert row["artifact_role"] in {"ABCDE_RERUN_OUTPUT", "CURRENT_CHAIN_OUTPUT"}
    assert row["protected_flag"] == "True"


def test_v21_199_classified_broker_source(tmp_path):
    _m, _r, _s, reg = run_repo(tmp_path)
    row = find(reg, "V21.199")
    assert row["artifact_role"] == "BROKER_DATA_SOURCE"
    assert row["protected_flag"] == "True"


def test_v21_201_alias_support(tmp_path):
    module, root, summary, reg = run_repo(tmp_path, alias_201=True)
    presence = rows(root / module.OUT_REL / "protected_path_presence_check.csv")
    row201 = [row for row in presence if row["protected_key"].startswith("V21.201")][0]
    alias = find(reg, "V21.201_DAILY_DRAM_PLAN_ALIAS")
    assert row201["resolution_method"] == "ALIAS_DISCOVERY_NEWEST_MODIFIED"
    assert alias["protected_flag"] == "True"
    assert summary["final_status"] == "WARN_V21_212_PROTECTED_ALIAS_USED"


def test_v21_154_audit_critical(tmp_path):
    _m, _r, _s, reg = run_repo(tmp_path)
    row = find(reg, "V21.154")
    assert row["artifact_role"] == "AUDIT_CRITICAL_HISTORY"
    assert row["retention_class"] == "RETAIN_AUDIT_CRITICAL"


def test_v21_140_never_deletion_candidate(tmp_path):
    _m, _r, _s, reg = run_repo(tmp_path)
    row = find(reg, "V21.140")
    assert row["safe_to_delete_now"] == "False"
    assert row["retention_class"] != "SAFE_DELETE_CACHE"


def test_deleted_sources_with_retained_zip_represented(tmp_path):
    _m, _r, _s, reg = run_repo(tmp_path)
    row = find(reg, "V21.139_MULTI_STRATEGY_RANDOM_ASOF_BACKTEST__V21.207_COMPRESS_ONLY_COPY.zip")
    assert row["artifact_role"] == "ZIP_ARCHIVE_BACKUP"
    assert row["retention_class"] == "RETAIN_ZIP_BACKUP"
    assert row["source_deleted_but_zip_retained_flag"] == "True"


def test_cleanup_chain_classified_cleanup_evidence(tmp_path):
    _m, _r, _s, reg = run_repo(tmp_path)
    row = find(reg, "V21.207")
    assert row["artifact_role"] == "CLEANUP_AUDIT_ARTIFACT"
    assert row["retention_class"] == "RETAIN_CLEANUP_EVIDENCE"


def test_dependency_edges_generated(tmp_path):
    module, root, summary, _reg = run_repo(tmp_path)
    edges = rows(root / module.OUT_REL / "artifact_dependency_edges.csv")
    assert summary["dependency_edge_count"] > 0
    assert edges


def test_safe_to_delete_defaults_false(tmp_path):
    _m, _r, _s, reg = run_repo(tmp_path)
    assert all(row["safe_to_delete_now"] == "False" for row in reg if row["artifact_role"] != "LOW_VALUE_CACHE")


def test_protected_path_missing_produces_fail(tmp_path):
    _m, _r, summary, _reg = run_repo(tmp_path, protected=False)
    assert summary["final_status"] == "FAIL_V21_212_PROTECTED_PATH_MISSING"


def test_unknown_items_produce_warn(tmp_path):
    _m, _r, summary, _reg = run_repo(tmp_path, unknown=True)
    assert summary["final_status"] == "WARN_V21_212_REGISTRY_HAS_UNKNOWN_REVIEW_ITEMS"


def test_summary_report_artifacts_written(tmp_path):
    module, root, summary, _reg = run_repo(tmp_path)
    out = root / module.OUT_REL
    for name in [
        "v21_212_summary.json", "V21.212_artifact_role_registry_report.txt", "artifact_registry.csv",
        "artifact_retention_policy_rules.csv", "artifact_dependency_edges.csv", "stage_role_summary.csv",
        "current_chain_artifact_manifest.csv", "audit_critical_artifact_manifest.csv",
        "reproducibility_artifact_manifest.csv", "cold_archive_candidate_manifest.csv",
        "deletion_candidate_manifest.csv", "protected_path_presence_check.csv", "registry_validation_warnings.csv",
    ]:
        assert (out / name).is_file()
    payload = json.loads((out / "v21_212_summary.json").read_text(encoding="utf-8"))
    assert payload["final_status"] == summary["final_status"]


def test_no_mutation_behavior(tmp_path):
    module, root, _summary, _reg = run_repo(tmp_path)
    watched = root / "state/runtime_state.json"
    before = watched.read_text(encoding="utf-8")
    module.run(root)
    assert watched.read_text(encoding="utf-8") == before


def test_unhandled_exception_produces_fail(tmp_path):
    module = load_module()
    root = tmp_path / "repo"
    summary = module.run(root, simulate_exception=True)
    assert summary["final_status"] == "FAIL_V21_212_ARTIFACT_REGISTRY_EXCEPTION"


def test_wrapper_exists_and_uses_venv_python():
    assert WRAPPER.is_file()
    text = WRAPPER.read_text(encoding="utf-8")
    assert ".venv\\Scripts\\python.exe" in text
    assert "v21_212_artifact_role_registry_and_retention_policy.py" in text
