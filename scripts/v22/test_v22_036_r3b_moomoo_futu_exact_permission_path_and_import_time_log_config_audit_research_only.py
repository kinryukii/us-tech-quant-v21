from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


MODULE_PATH = Path(__file__).with_name("v22_036_r3b_moomoo_futu_exact_permission_path_and_import_time_log_config_audit_research_only.py")
SPEC = importlib.util.spec_from_file_location("v22_036_r3b", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def seed_r3a(repo: Path) -> Path:
    root = repo / module.V22_036_R3A_DIR
    root.mkdir(parents=True, exist_ok=True)
    path = root / "v22_036_r3a_summary.json"
    path.write_text(json.dumps({"final_status": "WARN", "prior_failure_type": "OPEND_LOG_PATH_PERMISSION_ERROR", "moomoo_import_error_message_initial": "PermissionError: [WinError 5] Access denied: C:\\Users\\Lenovo\\AppData\\Roaming\\com.moomoo.OpenD\\Log\\py.log"}), encoding="utf-8")
    return path


def test_extract_windows_paths_and_permission_paths():
    text = "PermissionError: [WinError 5] Access denied: C:\\tmp\\py.log"
    assert module.extract_windows_paths(text) == ["C:\\tmp\\py.log"]
    assert module.permission_paths(text) == ["C:\\tmp\\py.log"]


def test_static_package_discovery_found_and_missing(monkeypatch, tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    init = pkg / "__init__.py"
    init.write_text("__version__='x'", encoding="utf-8")
    monkeypatch.setattr(module.importlib.util, "find_spec", lambda name: SimpleNamespace(origin=str(init)) if name == "pkg" else None)
    monkeypatch.setattr(module.importlib.metadata, "version", lambda name: "1.0")
    found = module.static_package_discovery("pkg")
    assert found["spec_found"] is True
    missing = module.static_package_discovery("missing")
    assert missing["discovery_status"] == "PACKAGE_SPEC_NOT_FOUND"


def test_source_scan_detects_log_patterns(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "a.py").write_text("import logging\nFUTU_OPEND_LOG_DIR='x'\nlogging.FileHandler('x.log')\n", encoding="utf-8")
    disc = pd.DataFrame([{"package_name": "pkg", "package_dir": str(pkg)}])
    scan = module.source_scan(disc)
    assert not scan.empty
    assert scan.iloc[0]["has_env_var_reference"] == True


def test_env_support_marks_referenced_vars(tmp_path):
    scan = pd.DataFrame([{"candidate_config_names": "FUTU_OPEND_LOG_DIR", "source_file": "a.py"}])
    env = module.env_support(scan, str(tmp_path))
    row = env[env["env_var_name"] == "FUTU_OPEND_LOG_DIR"].iloc[0]
    assert row["support_status"] == "SUPPORTED_BY_PACKAGE_SOURCE"


def test_permission_path_reconstruction_writable(tmp_path):
    errors = pd.DataFrame([{"extracted_permission_denied_paths": "", "extracted_log_like_paths": ""}])
    recon = module.reconstruct_paths(tmp_path, errors, pd.DataFrame())
    assert "WRITABLE" in set(recon["permission_status"])


def test_import_experiment_dry_run_and_success(tmp_path):
    dry = module.run_import_experiment("sys", "baseline", tmp_path, {}, False)
    assert dry["experiment_status"] == "EXPERIMENT_NOT_EXECUTED_DRY_RUN"
    ok = module.run_import_experiment("sys", "baseline", tmp_path, {}, True)
    assert ok["experiment_status"] == "IMPORT_SUCCEEDED"


def test_import_experiment_permission_error(tmp_path):
    script_dir = tmp_path / "badpkg"
    script_dir.mkdir()
    (script_dir / "badpkg.py").write_text("raise PermissionError('Permission denied: C:\\\\bad\\\\py.log')", encoding="utf-8")
    result = module.run_import_experiment("badpkg", "bad", tmp_path, {"PYTHONPATH": str(script_dir)}, True)
    assert result["experiment_status"] == "IMPORT_FAILED_PERMISSION_ERROR"
    assert "C:\\bad\\py.log" in result["extracted_permission_paths"]


def test_repair_wrapper_prefers_env_success(tmp_path):
    matrix = pd.DataFrame([
        {"experiment_name": "cwd_output_dir", "import_succeeded": True, "env_overrides": "{}", "cwd": str(tmp_path), "experiment_status": "IMPORT_SUCCEEDED", "extracted_permission_paths": ""},
        {"experiment_name": "env_supported_log_vars", "import_succeeded": True, "env_overrides": '{"A":"B"}', "cwd": str(tmp_path), "experiment_status": "IMPORT_SUCCEEDED", "extracted_permission_paths": ""},
    ])
    repair = module.repair_wrapper(matrix, tmp_path).iloc[0]
    assert repair["successful_experiment_name"] == "env_supported_log_vars"


def test_repair_wrapper_manual_when_no_success():
    matrix = pd.DataFrame([{"experiment_name": "x", "import_succeeded": False, "experiment_status": "IMPORT_FAILED_PERMISSION_ERROR", "extracted_permission_paths": "C:\\bad\\py.log"}])
    repair = module.repair_wrapper(matrix, Path("x")).iloc[0]
    assert repair["repair_status"] == "MANUAL_PERMISSION_REPAIR_REQUIRED"


def test_policy_allows_rerun_only_on_experiment_success():
    repair = pd.DataFrame([{"repair_strategy": "env", "v22_036_r3_rerun_recommended": True, "repair_status": "REPAIR_READY_RERUN_V22_036_R3"}])
    policy = module.next_step_policy(pd.DataFrame([{"exact_permission_path_found": True}]), pd.DataFrame([{"spec_found": True}]), pd.DataFrame([{"x": 1}]), pd.DataFrame([{"referenced_in_package_source": True}]), pd.DataFrame([{"import_succeeded": True}]), repair, True).iloc[0]
    assert policy["read_only_underlying_quote_refresh_allowed_next_step"] == True
    assert policy["option_chain_refresh_allowed"] == False
    assert policy["broker_action_allowed"] == False


def test_policy_manual_spot_gate_when_auto_repair_fails():
    repair = pd.DataFrame([{"repair_strategy": "manual", "repair_status": "MANUAL_PERMISSION_REPAIR_REQUIRED"}])
    policy = module.next_step_policy(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame([{"import_succeeded": False}]), repair, True).iloc[0]
    assert policy["fallback_to_manual_spot_gate_allowed_next_step"] == True
    assert policy["full_option_candidate_generation_allowed"] == False


def test_missing_input_exit_one_and_existing_artifacts_not_mutated(tmp_path):
    repo = tmp_path / "repo"
    assert module.run(repo)["final_status"] == "FAIL_V22_036_R3B_INPUT_NOT_FOUND"
    assert module.main(["--repo-root", str(repo)]) == 1
    seed = seed_r3a(repo)
    before = seed.read_bytes()
    assert module.main(["--repo-root", str(repo)]) == 0
    assert seed.read_bytes() == before
