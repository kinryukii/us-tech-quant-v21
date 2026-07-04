from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_213_r6_current_venv_moomoo_post_repair_retirement_readiness_check.py")
spec = importlib.util.spec_from_file_location("v21_213_r6", MODULE_PATH)
r6 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(r6)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def make_repo(
    tmp_path: Path,
    *,
    r5_pass: bool = True,
    blocker_count: int = 0,
    protected: bool = True,
    v196_required: bool = False,
    v196_superseded: bool = True,
) -> Path:
    root = tmp_path / "repo"
    (root / ".venv/Scripts").mkdir(parents=True)
    (root / ".venv/Scripts/python.exe").write_text("fake current python", encoding="utf-8")
    (root / ".venv_moomoo_py312/Scripts").mkdir(parents=True)
    (root / ".venv_moomoo_py312/Scripts/python.exe").write_text("fake alt python", encoding="utf-8")
    (root / ".venv_moomoo_py312/Lib/site-packages/demo.py").parent.mkdir(parents=True, exist_ok=True)
    (root / ".venv_moomoo_py312/Lib/site-packages/demo.py").write_text("x = 1\n", encoding="utf-8")
    if protected:
        (root / "outputs/v20/price_history").mkdir(parents=True)
        (root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv").write_text("x\n", encoding="utf-8")
        for name in [
            "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
            "V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
            "V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
            "V21.212_ARTIFACT_ROLE_REGISTRY_AND_RETENTION_POLICY",
            "V21.213_R2_MOOMOO_ALT_ENV_REFERENCE_RESOLUTION_AUDIT",
            "V21.213_R5_INSTALL_MOOMOO_IN_CURRENT_VENV_AFTER_APPROVAL",
        ]:
            (root / "outputs/v21" / name).mkdir(parents=True, exist_ok=True)
    r5_summary = {
        "final_status": "PASS_V21_213_R5_CURRENT_VENV_MOOMOO_IMPORT_REPAIRED" if r5_pass else "WARN_V21_213_R5_INSTALL_COMPLETED_IMPORT_STILL_FAILS",
        "post_install_moomoo_import_ok": r5_pass,
        "alt_venv_retirement_allowed_now": r5_pass,
    }
    write_json(root / r6.R5_SUMMARY_REL, r5_summary)
    r2_summary = {
        "remaining_blocking_count": blocker_count,
        "v21_196_current_chain_required_flag": v196_required,
        "v21_196_superseded_by_v21_199_r4_or_v21_201_flag": v196_superseded,
    }
    write_json(root / r6.R2_SUMMARY_REL, r2_summary)
    r2_csv = root / r6.R2_RESOLUTION_REL
    r2_csv.parent.mkdir(parents=True, exist_ok=True)
    with r2_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["blocks_deletion_after_resolution"], lineterminator="\n")
        writer.writeheader()
        for _ in range(blocker_count):
            writer.writerow({"blocks_deletion_after_resolution": "True"})
    return root


def test_r5_pass_import_ok_no_blockers_produces_pass(tmp_path):
    root = make_repo(tmp_path)
    summary = r6.run(root, out_dir=root / "out", simulate_import={"import_ok": True, "moomoo_version": "10.08.6808"})
    assert summary["final_status"] == "PASS_V21_213_R6_ALT_VENV_RETIREMENT_READY"
    assert summary["alt_venv_retirement_ready"] is True


def test_r5_missing_or_not_pass_produces_warn(tmp_path):
    root = make_repo(tmp_path, r5_pass=False)
    summary = r6.run(root, out_dir=root / "out", simulate_import={"import_ok": True, "moomoo_version": "10.08.6808"})
    assert summary["final_status"] == "WARN_V21_213_R6_ALT_VENV_RETIREMENT_NOT_READY"
    assert summary["r5_pass_confirmed"] is False


def test_import_failure_produces_warn(tmp_path):
    root = make_repo(tmp_path)
    summary = r6.run(root, out_dir=root / "out", simulate_import={"import_ok": False, "exception_type": "ImportError"})
    assert summary["final_status"] == "WARN_V21_213_R6_ALT_VENV_RETIREMENT_NOT_READY"
    assert summary["current_venv_moomoo_import_ok"] is False


def test_active_runtime_blocker_produces_warn(tmp_path):
    root = make_repo(tmp_path, blocker_count=1)
    summary = r6.run(root, out_dir=root / "out", simulate_import={"import_ok": True, "moomoo_version": "10.08.6808"})
    assert summary["final_status"] == "WARN_V21_213_R6_ALT_VENV_RETIREMENT_NOT_READY"
    assert summary["active_runtime_blocker_count"] == 1


def test_missing_protected_path_produces_fail(tmp_path):
    root = make_repo(tmp_path, protected=False)
    summary = r6.run(root, out_dir=root / "out", simulate_import={"import_ok": True, "moomoo_version": "10.08.6808"})
    assert summary["final_status"] == "FAIL_V21_213_R6_PROTECTED_PATH_MISSING"
    assert summary["protected_path_missing_count"] > 0


def test_policy_flags_are_non_mutating(tmp_path):
    root = make_repo(tmp_path)
    summary = r6.run(root, out_dir=root / "out", simulate_import={"import_ok": True, "moomoo_version": "10.08.6808"})
    assert summary["deletion_allowed_in_this_run"] is False
    assert summary["deletion_performed"] is False
    assert summary["package_install_performed"] is False
    assert summary["package_uninstall_performed"] is False
    assert summary["moomoo_broker_connection_performed"] is False


def test_required_approval_phrase_present(tmp_path):
    root = make_repo(tmp_path)
    summary = r6.run(root, out_dir=root / "out", simulate_import={"import_ok": True, "moomoo_version": "10.08.6808"})
    assert summary["required_manual_approval_phrase"] == "APPROVE_V21_214_DELETE_ALTERNATE_VENV_MOOMOO_PY312"


def test_summary_report_artifacts_written(tmp_path):
    root = make_repo(tmp_path)
    out = root / "out"
    r6.run(root, out_dir=out, simulate_import={"import_ok": True, "moomoo_version": "10.08.6808"})
    for name in [
        "v21_213_r6_summary.json",
        "V21.213_R6_current_venv_moomoo_post_repair_retirement_readiness_report.txt",
        "current_venv_moomoo_import_recheck.csv",
        "alt_venv_retirement_readiness_check.csv",
        "prior_stage_gate_check.csv",
        "protected_path_presence_check.csv",
        "manual_approval_checklist.csv",
    ]:
        assert (out / name).exists()


def test_unhandled_exception_produces_fail(tmp_path):
    root = make_repo(tmp_path)
    summary = r6.run(root, out_dir=root / "out", simulate_exception=True)
    assert summary["final_status"] == "FAIL_V21_213_R6_READINESS_EXCEPTION"
    assert summary["deletion_performed"] is False
