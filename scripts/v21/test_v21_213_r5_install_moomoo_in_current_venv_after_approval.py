from __future__ import annotations

import csv
import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_213_r5_install_moomoo_in_current_venv_after_approval.py")
spec = importlib.util.spec_from_file_location("v21_213_r5", MODULE_PATH)
r5 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(r5)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def make_repo(tmp_path: Path, *, protected: bool = True, r4_version: str = "10.8.6808") -> Path:
    root = tmp_path / "repo"
    (root / ".venv/Scripts").mkdir(parents=True)
    (root / ".venv/Scripts/python.exe").write_text("fake current python", encoding="utf-8")
    (root / ".venv_moomoo_py312/Scripts").mkdir(parents=True)
    (root / ".venv_moomoo_py312/Scripts/python.exe").write_text("fake alt python", encoding="utf-8")
    if protected:
        (root / "outputs/v20/price_history").mkdir(parents=True)
        (root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv").write_text("x\n", encoding="utf-8")
        for name in [
            "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
            "V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
            "V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
            "V21.212_ARTIFACT_ROLE_REGISTRY_AND_RETENTION_POLICY",
            "V21.213_R4_CURRENT_VENV_MOOMOO_PACKAGE_IDENTITY_AND_REPAIR_DRY_RUN",
        ]:
            (root / "outputs/v21" / name).mkdir(parents=True, exist_ok=True)
    r4_dir = root / "outputs/v21/V21.213_R4_CURRENT_VENV_MOOMOO_PACKAGE_IDENTITY_AND_REPAIR_DRY_RUN"
    r4_dir.mkdir(parents=True, exist_ok=True)
    with (r4_dir / "current_venv_distribution_metadata_check.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["distribution_name", "found", "version"], lineterminator="\n")
        writer.writeheader()
        writer.writerow({"distribution_name": "moomoo-api", "found": "true", "version": r4_version})
    return root


def stub_package_state(monkeypatch, *, pre_ok: bool = False, post_ok: bool = True) -> None:
    calls = []

    def fake_state(root: Path, phase: str) -> dict[str, object]:
        calls.append(phase)
        ok = pre_ok if phase == "pre_install" else post_ok
        return {
            "phase": phase,
            "python_executable": str(root / ".venv/Scripts/python.exe"),
            "python_exists": (root / ".venv/Scripts/python.exe").exists(),
            "python_version": "3.14.4",
            "pip_version": "pip 25.0",
            "pip_show_moomoo_api": "Name: moomoo-api\nVersion: 10.8.6808",
            "pip_show_moomoo": "",
            "pip_freeze_filtered": "moomoo-api==10.8.6808",
            "moomoo_import_ok": ok,
            "moomoo_version": "10.8.6808" if ok else "",
            "exception_type": "" if ok else "PermissionError",
            "exception_message": "" if ok else "blocked",
        }

    monkeypatch.setattr(r5, "package_state", fake_state)


def test_missing_approval_blocks_install(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    stub_package_state(monkeypatch)
    summary = r5.run(root, approval_phrase="", out_dir=root / "out")
    assert summary["final_status"] == "FAIL_V21_213_R5_MANUAL_APPROVAL_MISSING"
    assert summary["install_attempted"] is False
    assert summary["package_install_performed"] is False


def test_wrong_approval_blocks_install(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    stub_package_state(monkeypatch)
    summary = r5.run(root, approval_phrase="WRONG", out_dir=root / "out")
    assert summary["final_status"] == "FAIL_V21_213_R5_MANUAL_APPROVAL_MISSING"
    assert summary["package_reinstall_performed"] is False


def test_exact_approval_constructs_reinstall_command_with_current_venv_only(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    stub_package_state(monkeypatch, post_ok=True)
    summary = r5.run(
        root,
        approval_phrase=r5.APPROVAL_PHRASE,
        out_dir=root / "out",
        simulate_install={"return_code": 0, "post_import_ok": True, "post_version": "10.8.6808"},
    )
    command = summary["install_command"]
    assert "moomoo-api==10.8.6808" in command
    assert ".venv" in command
    assert ".venv_moomoo_py312" not in command
    assert "--force-reinstall" in command


def test_protected_path_missing_blocks_install(tmp_path, monkeypatch):
    root = make_repo(tmp_path, protected=False)
    stub_package_state(monkeypatch)
    summary = r5.run(root, approval_phrase=r5.APPROVAL_PHRASE, out_dir=root / "out")
    assert summary["final_status"] == "FAIL_V21_213_R5_PROTECTED_PATH_MISSING"
    assert summary["install_attempted"] is False


def test_pip_command_failure_produces_fail(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    stub_package_state(monkeypatch, post_ok=False)
    summary = r5.run(
        root,
        approval_phrase=r5.APPROVAL_PHRASE,
        out_dir=root / "out",
        simulate_install={"return_code": 2, "stderr": "pip failed", "post_import_ok": False},
    )
    assert summary["final_status"] == "FAIL_V21_213_R5_INSTALL_COMMAND_FAILED"
    assert summary["install_success"] is False


def test_post_install_import_success_produces_pass_and_alt_gate_true(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    stub_package_state(monkeypatch, post_ok=True)
    summary = r5.run(
        root,
        approval_phrase=r5.APPROVAL_PHRASE,
        out_dir=root / "out",
        simulate_install={"return_code": 0, "post_import_ok": True, "post_version": "10.8.6808"},
    )
    assert summary["final_status"] == "PASS_V21_213_R5_CURRENT_VENV_MOOMOO_IMPORT_REPAIRED"
    assert summary["alt_venv_retirement_allowed_now"] is True
    assert summary["moomoo_broker_connection_performed"] is False


def test_post_install_import_failure_produces_warn_and_alt_gate_false(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    stub_package_state(monkeypatch, post_ok=False)
    summary = r5.run(
        root,
        approval_phrase=r5.APPROVAL_PHRASE,
        out_dir=root / "out",
        simulate_install={"return_code": 0, "post_import_ok": False},
    )
    assert summary["final_status"] == "WARN_V21_213_R5_INSTALL_COMPLETED_IMPORT_STILL_FAILS"
    assert summary["alt_venv_retirement_allowed_now"] is False
    assert summary["alt_venv_retirement_blocker"] == "CURRENT_VENV_MOOMOO_IMPORT_NOT_OK_AFTER_REPAIR"


def test_no_deletion_compression_archive_or_broker_flags(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    stub_package_state(monkeypatch, post_ok=True)
    summary = r5.run(
        root,
        approval_phrase=r5.APPROVAL_PHRASE,
        out_dir=root / "out",
        simulate_install={"return_code": 0, "post_import_ok": True},
    )
    assert summary["deletion_performed"] is False
    assert summary["compression_performed"] is False
    assert summary["archive_movement_performed"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False


def test_summary_and_report_artifacts_written(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    out = root / "out"
    stub_package_state(monkeypatch, post_ok=True)
    r5.run(
        root,
        approval_phrase=r5.APPROVAL_PHRASE,
        out_dir=out,
        simulate_install={"return_code": 0, "post_import_ok": True},
    )
    expected = [
        "v21_213_r5_summary.json",
        "V21.213_R5_install_moomoo_in_current_venv_report.txt",
        "manual_approval_check.csv",
        "pre_install_current_venv_package_state.csv",
        "install_execution_log.csv",
        "post_install_import_check.csv",
        "post_install_current_venv_package_state.csv",
        "alt_venv_retirement_gate_status.csv",
        "protected_path_presence_check.csv",
    ]
    for name in expected:
        assert (out / name).exists()
    install_rows = read_csv(out / "install_execution_log.csv")
    assert install_rows[0]["install_attempted"] == "True"


def test_unhandled_exception_produces_fail(tmp_path):
    root = make_repo(tmp_path)
    summary = r5.run(
        root,
        approval_phrase=r5.APPROVAL_PHRASE,
        out_dir=root / "out",
        simulate_exception=True,
    )
    assert summary["final_status"] == "FAIL_V21_213_R5_INSTALL_EXCEPTION"
    assert summary["deletion_performed"] is False
