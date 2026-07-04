from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_213_r4_current_venv_moomoo_package_identity_and_repair_dry_run.py"
WRAPPER = ROOT / "scripts/v21/run_v21_213_r4_current_venv_moomoo_package_identity_and_repair_dry_run.ps1"


def load_module():
    spec = importlib.util.spec_from_file_location("v21_213_r4", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def add_repo(root: Path, protected: bool = True) -> None:
    touch(root / ".venv/Scripts/python.exe", "python")
    touch(root / ".venv_moomoo_py312/Scripts/python.exe", "python")
    if protected:
        touch(root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv", "date,close")
        touch(root / "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT/summary.json", "{}")
        touch(root / "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME/summary.json", "{}")
        touch(root / "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH/summary.json", "{}")
        touch(root / "outputs/v21/V21.212_ARTIFACT_ROLE_REGISTRY_AND_RETENTION_POLICY/summary.json", "{}")
        touch(root / "outputs/v21/V21.213_R2_MOOMOO_ALT_ENV_REFERENCE_RESOLUTION_AUDIT/summary.json", "{}")
        touch(root / "outputs/v21/V21.213_R3_CURRENT_VENV_MOOMOO_IMPORT_FAILURE_DIAGNOSIS_AND_REPAIR_PLAN/summary.json", "{}")


def make_repo(tmp_path, protected=True):
    module = load_module()
    root = tmp_path / "repo"
    add_repo(root, protected=protected)
    return module, root


def dist(name, found=True):
    return {"distribution_name": name, "found": found, "version": "1.0", "package_location": "site", "top_level": name, "requires_python": "", "direct_url": ""}


def imports(moomoo=False, moomoo_api=False, futu=False):
    return [
        {"import_name": "moomoo", "import_ok": moomoo, "version_attr": "1" if moomoo else "", "exception_type": "" if moomoo else "ModuleNotFoundError", "exception_message": "", "traceback_tail": ""},
        {"import_name": "moomoo_api", "import_ok": moomoo_api, "version_attr": "1" if moomoo_api else "", "exception_type": "" if moomoo_api else "ModuleNotFoundError", "exception_message": "", "traceback_tail": ""},
        {"import_name": "futu", "import_ok": futu, "version_attr": "1" if futu else "", "exception_type": "" if futu else "ModuleNotFoundError", "exception_message": "", "traceback_tail": ""},
    ]


def patch(monkeypatch, module, dists, imps, usage=None, py_ver="3.14.4"):
    monkeypatch.setattr(module, "distribution_metadata", lambda root: (dists, py_ver))
    monkeypatch.setattr(module, "import_checks", lambda root: imps)
    monkeypatch.setattr(module, "project_usage", lambda root: usage or [])


def test_import_moomoo_ok_produces_pass(tmp_path, monkeypatch):
    module, root = make_repo(tmp_path)
    patch(monkeypatch, module, [dist("moomoo")], imports(moomoo=True))
    summary = module.run(root)
    assert summary["final_status"] == "PASS_V21_213_R4_CURRENT_VENV_MOOMOO_IMPORT_ALREADY_OK"


def test_moomoo_api_dist_import_moomoo_fails_classified(tmp_path, monkeypatch):
    module, root = make_repo(tmp_path)
    patch(monkeypatch, module, [dist("moomoo-api")], imports(moomoo=False, moomoo_api=True))
    summary = module.run(root)
    assert summary["diagnosed_repair_class"] == "DIST_INSTALLED_BUT_TOP_LEVEL_IMPORT_MISMATCH"


def test_no_matching_distribution_classified_dist_not_installed(tmp_path, monkeypatch):
    module, root = make_repo(tmp_path)
    patch(monkeypatch, module, [], imports())
    summary = module.run(root)
    assert summary["diagnosed_repair_class"] == "DIST_NOT_INSTALLED"


def test_project_usage_audit_detects_import_moomoo(tmp_path):
    module, root = make_repo(tmp_path)
    touch(root / "scripts/v21/example.py", "import moomoo\nfrom futu import OpenQuoteContext")
    usage = module.project_usage(root)
    assert any(row["import_style"] == "import_moomoo" for row in usage)


def test_selected_candidate_not_blind_when_metadata_insufficient(tmp_path, monkeypatch):
    module, root = make_repo(tmp_path)
    patch(monkeypatch, module, [], imports(), usage=[])
    summary = module.run(root)
    assert summary["selected_candidate_package"] == ""


def test_install_allowed_false_and_approval_phrase(tmp_path, monkeypatch):
    module, root = make_repo(tmp_path)
    patch(monkeypatch, module, [dist("moomoo-api")], imports())
    summary = module.run(root)
    assert summary["package_install_allowed_in_this_run"] is False
    assert summary["required_manual_approval_phrase"] == module.APPROVAL_PHRASE


def test_alt_retirement_false_when_import_fails(tmp_path, monkeypatch):
    module, root = make_repo(tmp_path)
    patch(monkeypatch, module, [dist("moomoo-api")], imports())
    summary = module.run(root)
    assert summary["alt_venv_retirement_allowed_now"] is False


def test_protected_path_missing_fails(tmp_path, monkeypatch):
    module, root = make_repo(tmp_path, protected=False)
    patch(monkeypatch, module, [dist("moomoo")], imports(moomoo=True))
    summary = module.run(root)
    assert summary["final_status"] == "FAIL_V21_213_R4_PROTECTED_PATH_MISSING"


def test_no_install_or_broker_connection(tmp_path, monkeypatch):
    module, root = make_repo(tmp_path)
    patch(monkeypatch, module, [dist("moomoo-api")], imports())
    summary = module.run(root)
    assert summary["package_install_performed"] is False
    assert summary["package_uninstall_performed"] is False
    assert summary["moomoo_broker_connection_performed"] is False


def test_summary_report_artifacts_written(tmp_path, monkeypatch):
    module, root = make_repo(tmp_path)
    patch(monkeypatch, module, [dist("moomoo-api")], imports())
    summary = module.run(root)
    out = root / module.OUT_REL
    for name in [
        "v21_213_r4_summary.json",
        "V21.213_R4_current_venv_moomoo_package_identity_and_repair_report.txt",
        "current_venv_distribution_metadata_check.csv",
        "current_venv_top_level_import_check.csv",
        "project_moomoo_import_usage_audit.csv",
        "moomoo_repair_command_dry_run_plan.csv",
        "alt_venv_retirement_gate_status.csv",
        "protected_path_presence_check.csv",
        "manual_approval_checklist.csv",
    ]:
        assert (out / name).is_file()
    payload = json.loads((out / "v21_213_r4_summary.json").read_text(encoding="utf-8"))
    assert payload["final_status"] == summary["final_status"]


def test_unhandled_exception_produces_fail(tmp_path):
    module, root = make_repo(tmp_path)
    summary = module.run(root, simulate_exception=True)
    assert summary["final_status"] == "FAIL_V21_213_R4_REPAIR_DRY_RUN_EXCEPTION"


def test_wrapper_exists_and_uses_venv_python():
    assert WRAPPER.is_file()
    text = WRAPPER.read_text(encoding="utf-8")
    assert ".venv\\Scripts\\python.exe" in text
    assert "v21_213_r4_current_venv_moomoo_package_identity_and_repair_dry_run.py" in text
