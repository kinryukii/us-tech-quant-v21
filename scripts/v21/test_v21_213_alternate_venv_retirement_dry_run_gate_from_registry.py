from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_213_alternate_venv_retirement_dry_run_gate_from_registry.py"
WRAPPER = ROOT / "scripts/v21/run_v21_213_alternate_venv_retirement_dry_run_gate_from_registry.ps1"


def load_module():
    spec = importlib.util.spec_from_file_location("v21_213", SCRIPT)
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


def write_registry(root: Path, role: str = "ALTERNATE_ENVIRONMENT_REVIEW", retention: str = "REVIEW_ALTERNATE_ENV_RETIREMENT") -> Path:
    path = root / "registry.csv"
    fields = ["artifact_path", "artifact_role", "retention_class", "future_action_allowed"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerow({"artifact_path": ".venv_moomoo_py312", "artifact_role": role, "retention_class": retention, "future_action_allowed": "REVIEW_BEFORE_ACTION"})
        writer.writerow({"artifact_path": ".venv", "artifact_role": "CURRENT_ENVIRONMENT", "retention_class": "RETAIN_PROTECTED_CURRENT_CHAIN", "future_action_allowed": "NO_ACTION_PROTECTED"})
    return path


def add_env(root: Path, name: str) -> None:
    touch(root / f"{name}/pyvenv.cfg", "version = 3.12.0")
    touch(root / f"{name}/Scripts/python.exe", "python")
    touch(root / f"{name}/Lib/site-packages/pkg/payload.txt", "payload")


def add_protected(root: Path) -> None:
    touch(root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv", "date,close")
    touch(root / "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT/summary.json", "{}")
    touch(root / "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME/summary.json", "{}")
    touch(root / "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH/summary.json", "{}")
    touch(root / "outputs/v21/V21.212_ARTIFACT_ROLE_REGISTRY_AND_RETENTION_POLICY/artifact_registry.csv", "x")


def make_repo(tmp_path: Path, alt: bool = True, current: bool = True, protected: bool = True, registry_role: str = "ALTERNATE_ENVIRONMENT_REVIEW"):
    module = load_module()
    root = tmp_path / "repo"
    if current:
        add_env(root, ".venv")
    if alt:
        add_env(root, ".venv_moomoo_py312")
    if protected:
        add_protected(root)
    registry = write_registry(root, role=registry_role)
    return module, root, registry


def test_registry_confirms_alternate_environment(tmp_path):
    module, root, registry = make_repo(tmp_path)
    summary = module.run(root, registry_csv=registry)
    assert summary["registry_confirms_alternate_env_review"] is True


def test_venv_is_never_eligible(tmp_path):
    module, root, registry = make_repo(tmp_path)
    module.run(root, registry_csv=registry)
    plan = rows(root / module.OUT_REL / "alternate_venv_retirement_dry_run_plan.csv")
    assert plan[0]["path"] == ".venv_moomoo_py312"
    assert plan[0]["current_project_env_flag"] == "False"


def test_alt_present_unreferenced_becomes_eligible(tmp_path):
    module, root, registry = make_repo(tmp_path)
    summary = module.run(root, registry_csv=registry)
    plan = rows(root / module.OUT_REL / "alternate_venv_retirement_dry_run_plan.csv")
    assert summary["final_status"] == "PASS_V21_213_ALTERNATE_VENV_RETIREMENT_DRY_RUN_READY"
    assert plan[0]["eligible_for_future_deletion"] == "True"


def test_self_audit_references_do_not_block(tmp_path):
    module, root, registry = make_repo(tmp_path)
    touch(root / "scripts/v21/v21_213_example.py", "ALT_ENV = '.venv_moomoo_py312'")
    summary = module.run(root, registry_csv=registry)
    refs = rows(root / module.OUT_REL / "alternate_venv_reference_classification.csv")
    assert summary["final_status"] == "PASS_V21_213_ALTERNATE_VENV_RETIREMENT_DRY_RUN_READY"
    assert refs[0]["reference_category"] == "SELF_AUDIT_REFERENCE"
    assert refs[0]["blocking_reference_flag"] == "False"


def test_test_references_do_not_block(tmp_path):
    module, root, registry = make_repo(tmp_path)
    touch(root / "scripts/v21/test_v21_213_example.py", "ALT_ENV = '.venv_moomoo_py312'")
    summary = module.run(root, registry_csv=registry)
    refs = rows(root / module.OUT_REL / "alternate_venv_reference_classification.csv")
    assert summary["final_status"] == "PASS_V21_213_ALTERNATE_VENV_RETIREMENT_DRY_RUN_READY"
    assert refs[0]["reference_category"] == "TEST_REFERENCE"


def test_report_registry_references_do_not_block(tmp_path):
    module, root, registry = make_repo(tmp_path)
    touch(root / "outputs/v21/V21.213_ALTERNATE_VENV_RETIREMENT_DRY_RUN_GATE_FROM_REGISTRY/report.txt", ".venv_moomoo_py312")
    summary = module.run(root, registry_csv=registry)
    refs = rows(root / module.OUT_REL / "alternate_venv_reference_classification.csv")
    assert summary["final_status"] == "PASS_V21_213_ALTERNATE_VENV_RETIREMENT_DRY_RUN_READY"
    assert refs[0]["reference_category"] == "REPORT_OR_REGISTRY_REFERENCE"


def test_powershell_invocation_blocks(tmp_path):
    module, root, registry = make_repo(tmp_path)
    touch(root / "run_alt.ps1", "& .venv_moomoo_py312\\Scripts\\python.exe script.py")
    summary = module.run(root, registry_csv=registry)
    assert summary["final_status"] == "WARN_V21_213_ALTERNATE_VENV_HAS_BLOCKING_REFERENCES"
    assert summary["configured_execution_reference_count"] == 1


def test_config_interpreter_reference_blocks(tmp_path):
    module, root, registry = make_repo(tmp_path)
    touch(root / "scheduler.json", '{"python": ".venv_moomoo_py312\\\\Scripts\\\\python.exe"}')
    summary = module.run(root, registry_csv=registry)
    assert summary["final_status"] == "WARN_V21_213_ALTERNATE_VENV_HAS_BLOCKING_REFERENCES"
    assert summary["configured_execution_reference_count"] == 1


def test_subprocess_invocation_blocks(tmp_path):
    module, root, registry = make_repo(tmp_path)
    touch(root / "scripts/use_alt.py", "import subprocess\nsubprocess.run(['.venv_moomoo_py312\\\\Scripts\\\\python.exe'])")
    summary = module.run(root, registry_csv=registry)
    assert summary["final_status"] == "WARN_V21_213_ALTERNATE_VENV_HAS_BLOCKING_REFERENCES"
    assert summary["active_runtime_reference_count"] == 1


def test_unknown_references_block(tmp_path):
    module, root, registry = make_repo(tmp_path)
    touch(root / "notes.json", '{"note": "use .venv_moomoo_py312 sometimes"}')
    summary = module.run(root, registry_csv=registry)
    assert summary["final_status"] == "WARN_V21_213_ALTERNATE_VENV_HAS_BLOCKING_REFERENCES"
    assert summary["unknown_reference_count"] == 1


def test_no_blocking_references_produces_pass_and_eligible(tmp_path):
    module, root, registry = make_repo(tmp_path)
    touch(root / "scripts/v21/v21_213_example.py", "ALT_ENV = '.venv_moomoo_py312'")
    summary = module.run(root, registry_csv=registry)
    plan = rows(root / module.OUT_REL / "alternate_venv_retirement_dry_run_plan.csv")
    assert summary["blocking_reference_count"] == 0
    assert summary["final_status"] == "PASS_V21_213_ALTERNATE_VENV_RETIREMENT_DRY_RUN_READY"
    assert plan[0]["eligible_for_future_deletion"] == "True"


def test_blocking_references_produce_warn_and_not_eligible(tmp_path):
    module, root, registry = make_repo(tmp_path)
    touch(root / "run_alt.ps1", "& .venv_moomoo_py312\\Scripts\\python.exe script.py")
    summary = module.run(root, registry_csv=registry)
    plan = rows(root / module.OUT_REL / "alternate_venv_retirement_dry_run_plan.csv")
    assert summary["blocking_reference_count"] == 1
    assert summary["final_status"] == "WARN_V21_213_ALTERNATE_VENV_HAS_BLOCKING_REFERENCES"
    assert plan[0]["eligible_for_future_deletion"] == "False"


def test_missing_alternate_venv_produces_warn(tmp_path):
    module, root, registry = make_repo(tmp_path, alt=False)
    summary = module.run(root, registry_csv=registry)
    assert summary["final_status"] == "WARN_V21_213_ALTERNATE_VENV_NOT_FOUND"


def test_missing_current_venv_produces_fail(tmp_path):
    module, root, registry = make_repo(tmp_path, current=False)
    summary = module.run(root, registry_csv=registry)
    assert summary["final_status"] == "FAIL_V21_213_CURRENT_ENV_OR_PROTECTED_PATH_MISSING"


def test_missing_protected_path_produces_fail(tmp_path):
    module, root, registry = make_repo(tmp_path, protected=False)
    summary = module.run(root, registry_csv=registry)
    assert summary["final_status"] == "FAIL_V21_213_CURRENT_ENV_OR_PROTECTED_PATH_MISSING"


def test_registry_mismatch_produces_fail(tmp_path):
    module, root, registry = make_repo(tmp_path, registry_role="CURRENT_ENVIRONMENT")
    summary = module.run(root, registry_csv=registry)
    assert summary["final_status"] == "FAIL_V21_213_REGISTRY_DOES_NOT_CONFIRM_ALTERNATE_ENV"


def test_deletion_allowed_always_false(tmp_path):
    module, root, registry = make_repo(tmp_path)
    summary = module.run(root, registry_csv=registry)
    plan = rows(root / module.OUT_REL / "alternate_venv_retirement_dry_run_plan.csv")
    assert summary["deletion_allowed_in_this_run"] is False
    assert plan[0]["deletion_allowed_in_this_run"] == "False"


def test_required_manual_approval_phrase_present(tmp_path):
    module, root, registry = make_repo(tmp_path)
    summary = module.run(root, registry_csv=registry)
    assert summary["required_manual_approval_phrase"] == module.APPROVAL_PHRASE
    checklist = rows(root / module.OUT_REL / "manual_approval_checklist.csv")
    assert any(row["required_value"] == module.APPROVAL_PHRASE for row in checklist)


def test_no_mutation_behavior(tmp_path):
    module, root, registry = make_repo(tmp_path)
    watched = root / ".venv_moomoo_py312/pyvenv.cfg"
    before = watched.read_text(encoding="utf-8")
    module.run(root, registry_csv=registry)
    assert watched.read_text(encoding="utf-8") == before
    assert watched.exists()


def test_summary_report_artifacts_written(tmp_path):
    module, root, registry = make_repo(tmp_path)
    summary = module.run(root, registry_csv=registry)
    out = root / module.OUT_REL
    for name in [
        "v21_213_summary.json",
        "V21.213_alternate_venv_retirement_dry_run_report.txt",
        "alternate_venv_retirement_dry_run_plan.csv",
        "alternate_venv_file_manifest.csv",
        "alternate_venv_reference_classification.csv",
        "registry_reference_check.csv",
        "current_env_safety_check.csv",
        "protected_path_presence_check.csv",
        "deletion_blocker_check.csv",
        "manual_approval_checklist.csv",
    ]:
        assert (out / name).is_file()
    payload = json.loads((out / "v21_213_summary.json").read_text(encoding="utf-8"))
    assert payload["final_status"] == summary["final_status"]


def test_unhandled_exception_produces_fail(tmp_path):
    module, root, registry = make_repo(tmp_path)
    summary = module.run(root, registry_csv=registry, simulate_exception=True)
    assert summary["final_status"] == "FAIL_V21_213_DRY_RUN_EXCEPTION"


def test_wrapper_exists_and_uses_venv_python():
    assert WRAPPER.is_file()
    text = WRAPPER.read_text(encoding="utf-8")
    assert ".venv\\Scripts\\python.exe" in text
    assert "v21_213_alternate_venv_retirement_dry_run_gate_from_registry.py" in text
