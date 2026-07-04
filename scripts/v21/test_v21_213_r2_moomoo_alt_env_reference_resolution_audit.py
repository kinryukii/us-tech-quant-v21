from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_213_r2_moomoo_alt_env_reference_resolution_audit.py"
WRAPPER = ROOT / "scripts/v21/run_v21_213_r2_moomoo_alt_env_reference_resolution_audit.ps1"


def load_module():
    spec = importlib.util.spec_from_file_location("v21_213_r2", SCRIPT)
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


def write_refs(root: Path, refs: list[dict[str, str]]) -> Path:
    path = root / "r1_refs.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["reference_file", "line_number", "matched_text", "surrounding_context_short", "reference_category", "blocking_reference_flag", "classification_reason"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(refs)
    return path


def ref(file: str, context: str, category: str = "UNKNOWN_REFERENCE") -> dict[str, str]:
    return {
        "reference_file": file,
        "line_number": "1",
        "matched_text": ".venv_moomoo_py312",
        "surrounding_context_short": context,
        "reference_category": category,
        "blocking_reference_flag": "True",
        "classification_reason": "test",
    }


def add_protected(root: Path, daily_uses_196: bool = False) -> None:
    touch(root / ".venv/Scripts/python.exe", "python")
    touch(root / ".venv_moomoo_py312/Scripts/python.exe", "python")
    touch(root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv", "date,close")
    touch(root / "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT/summary.json", "{}")
    touch(root / "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME/summary.json", "{}")
    touch(root / "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH/summary.json", "{}")
    touch(root / "outputs/v21/V21.212_ARTIFACT_ROLE_REGISTRY_AND_RETENTION_POLICY/artifact_registry.csv", "x")
    touch(root / "outputs/v21/V21.213_ALTERNATE_VENV_RETIREMENT_DRY_RUN_GATE_FROM_REGISTRY/v21_213_summary.json", "{}")
    chain = "scripts/v21/run_v21_199_r4_rate_limited_history_kline_fetch_and_resume.ps1\nscripts/v21/run_v21_201_dram_moomoo_r4_date_alignment_and_plan_refresh.ps1"
    if daily_uses_196:
        chain += "\nscripts/v21/run_v21_196_r4_moomoo_sdk_opend_bootstrap_and_daily_kline_healthcheck.ps1"
    touch(root / "scripts/run_daily_moomoo_research_chain.ps1", chain)
    touch(root / "scripts/v21/v21_196_r4_moomoo_sdk_opend_bootstrap_and_daily_kline_healthcheck.py", "x")
    touch(root / "outputs/v21/V21.196_R4A_MOOMOO_API_PACKAGE_NAME_AND_PY311_ENV_REPAIR/summary.json", "{}")


def make_repo(tmp_path: Path, refs: list[dict[str, str]], protected: bool = True, daily_uses_196: bool = False):
    module = load_module()
    root = tmp_path / "repo"
    if protected:
        add_protected(root, daily_uses_196=daily_uses_196)
    ref_csv = write_refs(root, refs)
    registry = root / "registry.csv"
    registry.write_text("artifact_path,artifact_role,retention_class\n.venv_moomoo_py312,ALTERNATE_ENVIRONMENT_REVIEW,REVIEW_ALTERNATE_ENV_RETIREMENT\n", encoding="utf-8")
    return module, root, ref_csv, registry


def test_active_moomoo_runtime_reference_remains_blocking(tmp_path):
    refs = [ref("scripts/live_runner.py", "subprocess.run(['.venv_moomoo_py312\\\\Scripts\\\\python.exe','opend'])")]
    module, root, ref_csv, registry = make_repo(tmp_path, refs)
    summary = module.run(root, r1_reference_csv=ref_csv, registry_csv=registry, simulate_moomoo_import_ok=True)
    assert summary["remaining_blocking_count"] == 1
    assert summary["active_moomoo_runtime_keep_alt_env_count"] == 1


def test_unknown_reference_remains_blocking(tmp_path):
    refs = [ref("scripts/unclear.py", "ALT='.venv_moomoo_py312'")]
    module, root, ref_csv, registry = make_repo(tmp_path, refs)
    summary = module.run(root, r1_reference_csv=ref_csv, registry_csv=registry, simulate_moomoo_import_ok=True)
    assert summary["final_status"] == "WARN_V21_213_R2_ALT_ENV_REFERENCES_REMAIN_BLOCKING"
    assert summary["unknown_keep_blocking_count"] == 1


def test_obsolete_configured_reference_nonblocking(tmp_path):
    refs = [ref("outputs/v21/V21.196_R4A_MOOMOO_API_PACKAGE_NAME_AND_PY311_ENV_REPAIR/summary.json", '"dedicated_python_executable": ".venv_moomoo_py312\\\\Scripts\\\\python.exe"', "CONFIGURED_EXECUTION_REFERENCE")]
    module, root, ref_csv, registry = make_repo(tmp_path, refs)
    summary = module.run(root, r1_reference_csv=ref_csv, registry_csv=registry, simulate_moomoo_import_ok=True)
    assert summary["configured_obsolete_reference_count"] + summary["historical_frozen_artifact_reference_count"] >= 1
    assert summary["remaining_blocking_count"] == 0


def test_historical_frozen_v21_196_artifact_nonblocking(tmp_path):
    refs = [ref("outputs/v21/V21.196_R4A_MOOMOO_API_PACKAGE_NAME_AND_PY311_ENV_REPAIR/audit.json", '"dedicated_env_path": ".venv_moomoo_py312"')]
    module, root, ref_csv, registry = make_repo(tmp_path, refs)
    summary = module.run(root, r1_reference_csv=ref_csv, registry_csv=registry, simulate_moomoo_import_ok=True)
    assert summary["historical_frozen_artifact_reference_count"] == 1
    assert summary["remaining_blocking_count"] == 0


def test_migration_candidate_nonblocking(tmp_path):
    refs = [ref("scripts/v21/v21_196_r4_moomoo_sdk_opend_bootstrap_and_daily_kline_healthcheck.py", 'return ROOT / ".venv_moomoo_py312"')]
    module, root, ref_csv, registry = make_repo(tmp_path, refs)
    summary = module.run(root, r1_reference_csv=ref_csv, registry_csv=registry, simulate_moomoo_import_ok=True)
    audit = rows(root / module.OUT_REL / "blocking_reference_resolution_audit.csv")
    assert summary["migrate_to_current_venv_candidate_count"] == 1
    assert audit[0]["recommended_action"] == "MANUAL_REVIEW_MIGRATE_OR_FREEZE_V21_196_SCRIPT"


def test_current_venv_moomoo_import_ok_supports_retirement_review(tmp_path):
    refs = [ref("outputs/v21/V21.196_R4A_MOOMOO_API_PACKAGE_NAME_AND_PY311_ENV_REPAIR/audit.json", '"dedicated_env_path": ".venv_moomoo_py312"')]
    module, root, ref_csv, registry = make_repo(tmp_path, refs)
    summary = module.run(root, r1_reference_csv=ref_csv, registry_csv=registry, simulate_moomoo_import_ok=True)
    assert summary["final_status"] == "PASS_V21_213_R2_ALT_ENV_REFERENCES_RESOLVED_NONBLOCKING"
    assert summary["alt_venv_retirement_recommended_after_manual_review"] is True


def test_current_venv_moomoo_import_failure_warns(tmp_path):
    refs = [ref("outputs/v21/V21.196_R4A_MOOMOO_API_PACKAGE_NAME_AND_PY311_ENV_REPAIR/audit.json", '"dedicated_env_path": ".venv_moomoo_py312"')]
    module, root, ref_csv, registry = make_repo(tmp_path, refs)
    summary = module.run(root, r1_reference_csv=ref_csv, registry_csv=registry, simulate_moomoo_import_ok=False)
    assert summary["final_status"] == "WARN_V21_213_R2_CURRENT_VENV_MOOMOO_IMPORT_FAILED"


def test_v21_196_superseded_recorded(tmp_path):
    refs = [ref("scripts/v21/v21_196_r4_moomoo_sdk_opend_bootstrap_and_daily_kline_healthcheck.py", 'return ROOT / ".venv_moomoo_py312"')]
    module, root, ref_csv, registry = make_repo(tmp_path, refs)
    summary = module.run(root, r1_reference_csv=ref_csv, registry_csv=registry, simulate_moomoo_import_ok=True)
    assert summary["v21_196_superseded_by_v21_199_r4_or_v21_201_flag"] is True
    dep = rows(root / module.OUT_REL / "v21_196_dependency_audit.csv")
    assert dep


def test_protected_path_missing_fails(tmp_path):
    refs = [ref("outputs/v21/V21.196_R4A/audit.json", '"dedicated_env_path": ".venv_moomoo_py312"')]
    module, root, ref_csv, registry = make_repo(tmp_path, refs, protected=False)
    summary = module.run(root, r1_reference_csv=ref_csv, registry_csv=registry, simulate_moomoo_import_ok=True)
    assert summary["final_status"] == "FAIL_V21_213_R2_PROTECTED_PATH_MISSING"


def test_no_mutation_behavior(tmp_path):
    refs = [ref("outputs/v21/V21.196_R4A/audit.json", '"dedicated_env_path": ".venv_moomoo_py312"')]
    module, root, ref_csv, registry = make_repo(tmp_path, refs)
    watched = root / "scripts/run_daily_moomoo_research_chain.ps1"
    before = watched.read_text(encoding="utf-8")
    module.run(root, r1_reference_csv=ref_csv, registry_csv=registry, simulate_moomoo_import_ok=True)
    assert watched.read_text(encoding="utf-8") == before


def test_summary_report_artifacts_written(tmp_path):
    refs = [ref("outputs/v21/V21.196_R4A/audit.json", '"dedicated_env_path": ".venv_moomoo_py312"')]
    module, root, ref_csv, registry = make_repo(tmp_path, refs)
    summary = module.run(root, r1_reference_csv=ref_csv, registry_csv=registry, simulate_moomoo_import_ok=True)
    out = root / module.OUT_REL
    for name in [
        "v21_213_r2_summary.json",
        "V21.213_R2_moomoo_alt_env_reference_resolution_report.txt",
        "blocking_reference_resolution_audit.csv",
        "v21_196_dependency_audit.csv",
        "current_moomoo_execution_env_check.csv",
        "migration_candidate_check.csv",
        "protected_path_presence_check.csv",
        "deletion_gate_recommendation.csv",
    ]:
        assert (out / name).is_file()
    payload = json.loads((out / "v21_213_r2_summary.json").read_text(encoding="utf-8"))
    assert payload["final_status"] == summary["final_status"]


def test_unhandled_exception_produces_fail(tmp_path):
    module, root, ref_csv, registry = make_repo(tmp_path, [])
    summary = module.run(root, r1_reference_csv=ref_csv, registry_csv=registry, simulate_exception=True)
    assert summary["final_status"] == "FAIL_V21_213_R2_REFERENCE_RESOLUTION_EXCEPTION"


def test_wrapper_exists_and_uses_venv_python():
    assert WRAPPER.is_file()
    text = WRAPPER.read_text(encoding="utf-8")
    assert ".venv\\Scripts\\python.exe" in text
    assert "v21_213_r2_moomoo_alt_env_reference_resolution_audit.py" in text
