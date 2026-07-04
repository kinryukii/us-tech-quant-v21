from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_213_r3_current_venv_moomoo_import_failure_diagnosis_and_repair_plan.py"
WRAPPER = ROOT / "scripts/v21/run_v21_213_r3_current_venv_moomoo_import_failure_diagnosis_and_repair_plan.ps1"


def load_module():
    spec = importlib.util.spec_from_file_location("v21_213_r3", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def add_repo(root: Path, current: bool = True, alt: bool = True, protected: bool = True) -> None:
    if current:
        touch(root / ".venv/Scripts/python.exe", "python")
    if alt:
        touch(root / ".venv_moomoo_py312/Scripts/python.exe", "python")
    if protected:
        touch(root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv", "date,close")
        touch(root / "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT/summary.json", "{}")
        touch(root / "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME/summary.json", "{}")
        touch(root / "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH/summary.json", "{}")
        touch(root / "outputs/v21/V21.212_ARTIFACT_ROLE_REGISTRY_AND_RETENTION_POLICY/summary.json", "{}")
        touch(root / "outputs/v21/V21.213_R2_MOOMOO_ALT_ENV_REFERENCE_RESOLUTION_AUDIT/summary.json", "{}")


def patch_checks(monkeypatch, module, current_import, alt_import, pip_found=True, py_exists=True, sys_exe_contains_venv=True):
    def fake_python_check(root, env_name):
        return {
            "venv_path": env_name,
            "venv_exists": py_exists,
            "python_executable": str(root / env_name / "Scripts/python.exe"),
            "python_exists": py_exists,
            "sys_executable": str(root / env_name / "Scripts/python.exe") if sys_exe_contains_venv else "C:/Python/python.exe",
            "python_version": "3.12.0",
            "sys_path_short_summary": "x",
            "site_packages_paths": "site-packages",
            "pip_available": True,
            "pip_version_output": "pip 1",
        }

    def fake_import(root, env_name):
        return current_import if env_name == ".venv" else alt_import

    def fake_pip(root):
        return {"pip_show_found": pip_found, "pip_show_output": "Name: moomoo" if pip_found else "", "pip_freeze_filtered": ""}

    monkeypatch.setattr(module, "python_check", fake_python_check)
    monkeypatch.setattr(module, "import_trace", fake_import)
    monkeypatch.setattr(module, "pip_moomoo_check", fake_pip)


def ok_import(version="1.0"):
    return {"env_name": ".venv", "python_executable": "py", "import_ok": True, "version": version, "exception_type": "", "exception_message": "", "traceback_tail": ""}


def bad_import(exc="ModuleNotFoundError", msg="No module named moomoo"):
    return {"env_name": ".venv", "python_executable": "py", "import_ok": False, "version": "", "exception_type": exc, "exception_message": msg, "traceback_tail": msg}


def make_repo(tmp_path, current=True, alt=True, protected=True):
    module = load_module()
    root = tmp_path / "repo"
    add_repo(root, current=current, alt=alt, protected=protected)
    return module, root


def test_current_venv_import_ok_produces_pass(tmp_path, monkeypatch):
    module, root = make_repo(tmp_path)
    patch_checks(monkeypatch, module, ok_import("9.9"), ok_import("9.9"))
    summary = module.run(root)
    assert summary["final_status"] == "PASS_V21_213_R3_CURRENT_VENV_MOOMOO_IMPORT_OK"


def test_current_venv_missing_moomoo_warns(tmp_path, monkeypatch):
    module, root = make_repo(tmp_path)
    patch_checks(monkeypatch, module, bad_import(), bad_import(), pip_found=False)
    summary = module.run(root)
    assert summary["final_status"] == "WARN_V21_213_R3_CURRENT_VENV_MOOMOO_IMPORT_REPAIR_NEEDED"
    assert summary["diagnosed_root_cause"] == "MOOMOO_PACKAGE_NOT_INSTALLED_IN_CURRENT_VENV"


def test_dependency_import_error_classified(tmp_path, monkeypatch):
    module, root = make_repo(tmp_path)
    patch_checks(monkeypatch, module, bad_import("ImportError", "protobuf error"), bad_import("ImportError", "protobuf error"), pip_found=True)
    summary = module.run(root)
    assert summary["diagnosed_root_cause"] == "MOOMOO_IMPORT_DEPENDENCY_ERROR"


def test_wrong_executable_classified(tmp_path, monkeypatch):
    module, root = make_repo(tmp_path)
    patch_checks(monkeypatch, module, bad_import(), ok_import(), pip_found=True, sys_exe_contains_venv=False)
    summary = module.run(root)
    assert summary["diagnosed_root_cause"] == "WRONG_CURRENT_PYTHON_EXECUTABLE"


def test_alt_has_moomoo_current_missing_classified(tmp_path, monkeypatch):
    module, root = make_repo(tmp_path)
    patch_checks(monkeypatch, module, bad_import(), ok_import("1.2"), pip_found=False)
    summary = module.run(root)
    assert summary["diagnosed_root_cause"] == "ALT_ENV_HAS_MOOMOO_CURRENT_VENV_MISSING"


def test_both_envs_fail_classified(tmp_path, monkeypatch):
    module, root = make_repo(tmp_path)
    patch_checks(monkeypatch, module, bad_import("RuntimeError", "bad"), bad_import("RuntimeError", "bad"), pip_found=True)
    summary = module.run(root)
    assert summary["diagnosed_root_cause"] == "BOTH_ENVS_IMPORT_FAIL"


def test_missing_current_or_alt_env_fails(tmp_path, monkeypatch):
    module, root = make_repo(tmp_path, current=False)
    patch_checks(monkeypatch, module, bad_import(), ok_import(), py_exists=False)
    summary = module.run(root)
    assert summary["final_status"] == "FAIL_V21_213_R3_CURRENT_OR_ALT_ENV_MISSING"


def test_protected_path_missing_fails(tmp_path, monkeypatch):
    module, root = make_repo(tmp_path, protected=False)
    patch_checks(monkeypatch, module, ok_import(), ok_import())
    summary = module.run(root)
    assert summary["final_status"] == "FAIL_V21_213_R3_PROTECTED_PATH_MISSING"


def test_no_package_install_or_broker_connection(tmp_path, monkeypatch):
    module, root = make_repo(tmp_path)
    patch_checks(monkeypatch, module, bad_import(), ok_import(), pip_found=False)
    summary = module.run(root)
    assert summary["package_install_performed"] is False
    assert summary["moomoo_broker_connection_performed"] is False


def test_alt_retirement_allowed_false_when_current_import_fails(tmp_path, monkeypatch):
    module, root = make_repo(tmp_path)
    patch_checks(monkeypatch, module, bad_import(), ok_import(), pip_found=False)
    summary = module.run(root)
    assert summary["alt_venv_retirement_allowed_now"] is False


def test_summary_report_artifacts_written(tmp_path, monkeypatch):
    module, root = make_repo(tmp_path)
    patch_checks(monkeypatch, module, bad_import(), ok_import(), pip_found=False)
    summary = module.run(root)
    out = root / module.OUT_REL
    for name in [
        "v21_213_r3_summary.json",
        "V21.213_R3_current_venv_moomoo_import_failure_diagnosis_report.txt",
        "current_venv_python_check.csv",
        "current_venv_moomoo_import_trace.csv",
        "current_venv_pip_moomoo_check.csv",
        "alternate_venv_moomoo_comparison_check.csv",
        "moomoo_repair_plan.csv",
        "protected_path_presence_check.csv",
        "alt_venv_retirement_gate_status.csv",
    ]:
        assert (out / name).is_file()
    payload = json.loads((out / "v21_213_r3_summary.json").read_text(encoding="utf-8"))
    assert payload["final_status"] == summary["final_status"]


def test_unhandled_exception_produces_fail(tmp_path):
    module, root = make_repo(tmp_path)
    summary = module.run(root, simulate_exception=True)
    assert summary["final_status"] == "FAIL_V21_213_R3_DIAGNOSIS_EXCEPTION"


def test_wrapper_exists_and_uses_venv_python():
    assert WRAPPER.is_file()
    text = WRAPPER.read_text(encoding="utf-8")
    assert ".venv\\Scripts\\python.exe" in text
    assert "v21_213_r3_current_venv_moomoo_import_failure_diagnosis_and_repair_plan.py" in text
