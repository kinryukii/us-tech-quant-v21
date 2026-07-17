from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


MODULE_PATH = Path(__file__).with_name("v22_036_r3a_moomoo_quote_context_import_and_log_permission_diagnostic_research_only.py")
SPEC = importlib.util.spec_from_file_location("v22_036_r3a", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def seed_r3(repo: Path, error: str = "PermissionError: [Errno 13] Permission denied: 'C:\\Users\\Lenovo\\AppData\\Roaming\\com.moomoo.OpenD\\Log\\py_2026_07_06.log'") -> Path:
    root = repo / module.V22_036_R3_DIR
    root.mkdir(parents=True, exist_ok=True)
    path = root / "option_underlying_quote_refresh_live_audit.csv"
    pd.DataFrame([{"provider_call_attempted": True, "provider_call_succeeded": False, "quote_refresh_status": "PROVIDER_PACKAGE_UNAVAILABLE", "quote_refresh_error": error}]).to_csv(path, index=False)
    (root / "v22_036_r3_summary.json").write_text(json.dumps({"final_status": "WARN_V22_036_R3_UNDERLYING_REFRESH_FAILED_SYNTHETIC_BLOCKED", "quote_refresh_status": "PROVIDER_PACKAGE_UNAVAILABLE"}), encoding="utf-8")
    return path


def import_success(name: str):
    return SimpleNamespace(__version__="1.2.3")


def import_permission(name: str):
    raise PermissionError("Permission denied: C:\\log\\py.log")


def import_missing(name: str):
    raise ModuleNotFoundError("No module named 'moomoo'")


def test_prior_failure_extraction_detects_permission_error_and_log_path(tmp_path):
    repo = tmp_path / "repo"
    seed_r3(repo)
    audit = module.extract_prior_failure(repo)
    row = audit[audit["quote_refresh_status"] == "PROVIDER_PACKAGE_UNAVAILABLE"].iloc[0]
    assert row["inferred_failure_type"] in {"OPEND_LOG_PATH_PERMISSION_ERROR", "MOOMOO_PACKAGE_IMPORT_PERMISSION_ERROR"}
    assert str(row["extracted_log_path"]).endswith(".log")


def test_prior_failure_extraction_opend_log_permission_inference(tmp_path):
    repo = tmp_path / "repo"
    seed_r3(repo, "Permission denied while opening OpenD Log C:\\tmp\\py.log")
    row = module.extract_prior_failure(repo).iloc[0]
    assert row["inferred_failure_type"] == "OPEND_LOG_PATH_PERMISSION_ERROR"


def test_package_audit_success_and_permission_error():
    ok = module.audit_python_environment(import_success).iloc[0]
    assert ok["moomoo_import_succeeded"] == True
    assert ok["environment_status"] == "MOOMOO_IMPORT_OK"
    bad = module.audit_python_environment(import_permission).iloc[0]
    assert bad["moomoo_import_succeeded"] == False
    assert bad["environment_status"] == "MOOMOO_IMPORT_PERMISSION_ERROR"


def test_log_path_permission_audit_writable_and_invalid(tmp_path):
    writable = module.probe_path(tmp_path, "tmp")
    assert writable["permission_status"] == "WRITABLE"
    file_path = tmp_path / "not_dir.txt"
    file_path.write_text("x", encoding="utf-8")
    invalid = module.probe_path(file_path, "file")
    assert invalid["permission_status"] == "NOT_A_DIRECTORY"


def test_fallback_dir_created_and_prefix_contains_both_env_vars(tmp_path):
    output = tmp_path / "out"
    fallback = module.build_fallback(output).iloc[0]
    assert fallback["fallback_dir_writable"] == True
    assert "FUTU_OPEND_LOG_DIR" in fallback["recommended_powershell_prefix"]
    assert "MOOMOO_LOG_DIR" in fallback["recommended_powershell_prefix"]


def test_import_retry_dry_run_and_execute():
    dry = module.retry_import_with_fallback(False, "x", import_success).iloc[0]
    assert dry["retry_status"] == "IMPORT_RETRY_NOT_EXECUTED_DRY_RUN"
    exe = module.retry_import_with_fallback(True, "x", import_success).iloc[0]
    assert exe["import_retry_attempted"] == True
    assert exe["import_retry_succeeded"] == True


def test_repair_policy_rerun_only_when_fallback_ready_and_retry_succeeds():
    good = module.build_repair_policy("OPEND_LOG_PATH_PERMISSION_ERROR", "MOOMOO_IMPORT_PERMISSION_ERROR", True, True, True).iloc[0]
    assert good["v22_036_r3_rerun_recommended"] == True
    bad = module.build_repair_policy("OPEND_LOG_PATH_PERMISSION_ERROR", "MOOMOO_IMPORT_PERMISSION_ERROR", True, False, True).iloc[0]
    assert bad["v22_036_r3_rerun_recommended"] == False


def test_policy_never_enables_forbidden_actions():
    row = module.build_repair_policy("X", "MOOMOO_IMPORT_OK", True, True, True).iloc[0]
    for key in ["option_chain_refresh_allowed", "option_quote_refresh_allowed", "iv_greeks_calculation_allowed", "full_option_candidate_generation_allowed", "broker_action_allowed", "official_adoption_allowed", "trade_order_allowed"]:
        assert row[key] == False


def test_missing_input_returns_fail_and_exit_one(tmp_path):
    repo = tmp_path / "repo"
    summary = module.run(repo, import_func=import_success)
    assert summary["final_status"] == "FAIL_V22_036_R3A_INPUT_NOT_FOUND"
    assert module.main(["--repo-root", str(repo)]) == 1


def test_pass_warn_exit_zero_and_previous_artifacts_not_mutated(tmp_path):
    repo = tmp_path / "repo"
    r3 = seed_r3(repo)
    before = r3.read_bytes()
    summary = module.run(repo, execute=True, import_func=import_success)
    assert summary["final_status"] == "PASS_V22_036_R3A_MOOMOO_IMPORT_READY_WITH_SAFE_LOG_DIR"
    assert r3.read_bytes() == before
    assert module.main(["--repo-root", str(repo)]) == 0
