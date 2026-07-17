from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_046_daily_research_full_cycle_controller_r1.py")
SPEC = importlib.util.spec_from_file_location("v22_046", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def seed_wrappers(repo: Path, refresh: bool = True, archive: bool = True) -> None:
    if refresh:
        path = repo / module.REFRESH_WRAPPER_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# fake V22.044 wrapper\n", encoding="utf-8")
    if archive:
        path = repo / module.ARCHIVE_WRAPPER_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# fake V22.045 wrapper\n", encoding="utf-8")


def refresh_summary(**overrides) -> dict:
    payload = {
        "final_status": "PASS_V22_044_DAILY_SINGLE_ENTRYPOINT_FROZEN",
        "final_decision": "V22_040_ACCEPTED_AS_ONLY_CURRENT_DAILY_RESEARCH_ENTRYPOINT",
        "child_v22_040_command": r".\scripts\v22\run_v22_040_daily_moomoo_oneclick_refresh_orchestrator_r1.ps1 -Execute",
        "canonical_latest_date": "2026-07-08",
        "abcde_latest_date": "2026-07-08",
        "dram_latest_price_date": "2026-07-08",
        "same_date_comparable_all_strategies": True,
        "data_gap_days": 0,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "factor_promotion_allowed": False,
    }
    payload.update(overrides)
    return payload


def archive_summary(repo: Path, **overrides) -> dict:
    archive_root = repo / "outputs/v22/daily_research_archives/2026-07-08/V22.045_TEST"
    paths = {
        "archive_zip_path": archive_root / "daily_research_archive.zip",
        "markdown_report_path": archive_root / "daily_research_audit_report.md",
        "pdf_report_path": archive_root / "daily_research_audit_report.pdf",
        "archive_manifest_csv_path": archive_root / "archive_manifest.csv",
        "archive_manifest_json_path": archive_root / "archive_manifest.json",
        "source_inventory_path": archive_root / "source_inventory.csv",
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n", encoding="utf-8")
    payload = {
        "final_status": "PASS_V22_045_DAILY_RESEARCH_ARCHIVE_CREATED",
        "final_decision": "DAILY_RESEARCH_ARCHIVE_CREATED_RESEARCH_ONLY",
        "archive_accepted": True,
        "latest_research_date": "2026-07-08",
        "archive_root": str(archive_root),
        "copied_file_count": 7,
        "total_archived_bytes": 100,
        "warning_count": 2,
        "warnings": ["optional forward missing", "optional option missing"],
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "direct_market_data_fetch_attempted": False,
        "direct_child_strategy_invocation_attempted": False,
        "source_files_mutated": False,
    }
    payload.update({key: str(value) for key, value in paths.items()})
    payload.update(overrides)
    return payload


def seed_repo(tmp_path: Path, refresh_wrapper: bool = True, archive_wrapper: bool = True) -> Path:
    repo = tmp_path / "repo"
    seed_wrappers(repo, refresh_wrapper, archive_wrapper)
    return repo


def runner_factory(
    repo: Path,
    *,
    refresh_exit: int = 0,
    archive_exit: int = 0,
    write_refresh: bool = True,
    write_archive: bool = True,
    refresh_payload: dict | None = None,
    archive_payload: dict | None = None,
    calls: list[str] | None = None,
):
    def runner(cmd, cwd, stdout_path, stderr_path):
        name = Path(cmd[-2]).name.lower()
        stdout_path.write_text(f"stdout {name}\n", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        if "v22_044" in name:
            if calls is not None:
                calls.append("V22.044")
            if write_refresh:
                write_json(repo / module.V22_044_SUMMARY_REL, refresh_payload or refresh_summary())
            return refresh_exit
        if "v22_045" in name:
            if calls is not None:
                calls.append("V22.045")
            if write_archive:
                write_json(repo / module.V22_045_SUMMARY_REL, archive_payload or archive_summary(repo))
            return archive_exit
        raise AssertionError(f"Unexpected command: {cmd}")

    return runner


def run_execute(tmp_path: Path, **kwargs):
    repo = seed_repo(tmp_path)
    calls: list[str] = []
    result = module.run(repo, execute=True, child_runner=runner_factory(repo, calls=calls, **kwargs))
    return repo, result, calls


def interrupting_runner_factory(repo: Path, stage: str, calls: list[str] | None = None):
    def runner(cmd, cwd, stdout_path, stderr_path):
        name = Path(cmd[-2]).name.lower()
        stdout_path.write_text(f"stdout {name}\n", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        if "v22_044" in name:
            if calls is not None:
                calls.append("V22.044")
            if stage == "V22.044":
                raise KeyboardInterrupt()
            write_json(repo / module.V22_044_SUMMARY_REL, refresh_summary())
            return 0
        if "v22_045" in name:
            if calls is not None:
                calls.append("V22.045")
            if stage == "V22.045":
                raise KeyboardInterrupt()
            write_json(repo / module.V22_045_SUMMARY_REL, archive_summary(repo))
            return 0
        raise AssertionError(f"Unexpected command: {cmd}")

    return runner


def test_pass_when_fake_wrappers_both_pass_and_summaries_satisfy_gates(tmp_path):
    _, result, calls = run_execute(tmp_path)
    assert result["final_status"] == "PASS_V22_046_DAILY_RESEARCH_FULL_CYCLE_COMPLETE"
    assert result["final_decision"] == "DAILY_RESEARCH_REFRESH_AND_ARCHIVE_COMPLETE_RESEARCH_ONLY"
    assert result["full_cycle_accepted"] is True
    assert calls == ["V22.044", "V22.045"]


def test_dry_run_validates_wrappers_but_does_not_execute_children(tmp_path):
    repo = seed_repo(tmp_path)
    calls: list[str] = []
    result = module.run(repo, execute=False, child_runner=runner_factory(repo, calls=calls))
    assert result["final_status"] == "PASS_V22_046_DAILY_RESEARCH_FULL_CYCLE_DRY_RUN_VALIDATED"
    assert calls == []


def test_fail_when_v22_044_wrapper_is_missing(tmp_path):
    repo = seed_repo(tmp_path, refresh_wrapper=False)
    result = module.run(repo, execute=True)
    assert result["final_status"] == "FAIL_V22_046_REFRESH_WRAPPER_MISSING"


def test_fail_when_v22_045_wrapper_is_missing(tmp_path):
    repo = seed_repo(tmp_path, archive_wrapper=False)
    result = module.run(repo, execute=True)
    assert result["final_status"] == "FAIL_V22_046_ARCHIVE_WRAPPER_MISSING"


def test_fail_when_v22_044_child_exit_code_is_nonzero(tmp_path):
    _, result, calls = run_execute(tmp_path, refresh_exit=9)
    assert result["final_status"] == "FAIL_V22_046_REFRESH_CHILD_EXIT_NONZERO"
    assert calls == ["V22.044"]


def test_v22_045_is_not_executed_if_v22_044_fails(tmp_path):
    _, result, calls = run_execute(tmp_path, refresh_exit=1)
    assert result["v22_045_child_exit_code"] is None
    assert calls == ["V22.044"]


def test_fail_when_v22_044_summary_is_missing(tmp_path):
    _, result, _ = run_execute(tmp_path, write_refresh=False)
    assert result["final_status"] == "FAIL_V22_046_REFRESH_SUMMARY_MISSING"


def test_fail_when_v22_044_final_status_is_not_pass(tmp_path):
    _, result, _ = run_execute(tmp_path, refresh_payload=refresh_summary(final_status="FAIL"))
    assert result["final_status"] == "FAIL_V22_046_REFRESH_GATE_FAILED"


def test_fail_when_v22_044_date_alignment_fails(tmp_path):
    _, result, _ = run_execute(tmp_path, refresh_payload=refresh_summary(dram_latest_price_date="2026-07-07"))
    assert result["final_status"] == "FAIL_V22_046_REFRESH_GATE_FAILED"
    assert "v22_044_dates_aligned" in result["failed_gate_names"]


def test_fail_when_v22_044_broker_action_allowed_is_true(tmp_path):
    _, result, _ = run_execute(tmp_path, refresh_payload=refresh_summary(broker_action_allowed=True))
    assert result["final_status"] == "FAIL_V22_046_RESEARCH_ONLY_GATE_FAILED"


def test_fail_when_v22_044_official_adoption_allowed_is_true(tmp_path):
    _, result, _ = run_execute(tmp_path, refresh_payload=refresh_summary(official_adoption_allowed=True))
    assert result["final_status"] == "FAIL_V22_046_RESEARCH_ONLY_GATE_FAILED"


def test_fail_when_v22_045_child_exit_code_is_nonzero(tmp_path):
    _, result, calls = run_execute(tmp_path, archive_exit=8)
    assert result["final_status"] == "FAIL_V22_046_ARCHIVE_CHILD_EXIT_NONZERO"
    assert calls == ["V22.044", "V22.045"]


def test_fail_when_v22_045_summary_is_missing(tmp_path):
    _, result, _ = run_execute(tmp_path, write_archive=False)
    assert result["final_status"] == "FAIL_V22_046_ARCHIVE_SUMMARY_MISSING"


def test_fail_when_v22_045_final_status_is_not_pass(tmp_path):
    repo = tmp_path / "repo"
    payload = archive_summary(repo, final_status="FAIL")
    _, result, _ = run_execute(tmp_path, archive_payload=payload)
    assert result["final_status"] == "FAIL_V22_046_ARCHIVE_GATE_FAILED"


def test_fail_when_v22_045_archive_accepted_is_false(tmp_path):
    repo = tmp_path / "repo"
    payload = archive_summary(repo, archive_accepted=False)
    _, result, _ = run_execute(tmp_path, archive_payload=payload)
    assert result["final_status"] == "FAIL_V22_046_ARCHIVE_GATE_FAILED"


def test_fail_when_v22_045_archive_zip_is_missing(tmp_path):
    repo = tmp_path / "repo"
    payload = archive_summary(repo)
    Path(payload["archive_zip_path"]).unlink()
    _, result, _ = run_execute(tmp_path, archive_payload=payload)
    assert result["final_status"] == "FAIL_V22_046_ARCHIVE_GATE_FAILED"
    assert "v22_045_archive_zip_path_exists" in result["failed_gate_names"]


def test_fail_when_v22_045_pdf_report_is_missing(tmp_path):
    repo = tmp_path / "repo"
    payload = archive_summary(repo)
    Path(payload["pdf_report_path"]).unlink()
    _, result, _ = run_execute(tmp_path, archive_payload=payload)
    assert "v22_045_pdf_report_path_exists" in result["failed_gate_names"]


def test_fail_when_v22_045_manifest_files_are_missing(tmp_path):
    repo = tmp_path / "repo"
    payload = archive_summary(repo)
    Path(payload["archive_manifest_csv_path"]).unlink()
    Path(payload["archive_manifest_json_path"]).unlink()
    _, result, _ = run_execute(tmp_path, archive_payload=payload)
    assert "v22_045_archive_manifest_csv_path_exists" in result["failed_gate_names"]
    assert "v22_045_archive_manifest_json_path_exists" in result["failed_gate_names"]


def test_fail_when_v22_045_latest_research_date_differs_from_v22_044(tmp_path):
    repo = tmp_path / "repo"
    payload = archive_summary(repo, latest_research_date="2026-07-07")
    _, result, _ = run_execute(tmp_path, archive_payload=payload)
    assert result["final_status"] == "FAIL_V22_046_DATE_MISMATCH_BETWEEN_REFRESH_AND_ARCHIVE"


def test_fail_when_v22_045_direct_market_data_fetch_attempted_is_true(tmp_path):
    repo = tmp_path / "repo"
    payload = archive_summary(repo, direct_market_data_fetch_attempted=True)
    _, result, _ = run_execute(tmp_path, archive_payload=payload)
    assert result["final_status"] == "FAIL_V22_046_RESEARCH_ONLY_GATE_FAILED"


def test_fail_when_v22_045_direct_child_strategy_invocation_attempted_is_true(tmp_path):
    repo = tmp_path / "repo"
    payload = archive_summary(repo, direct_child_strategy_invocation_attempted=True)
    _, result, _ = run_execute(tmp_path, archive_payload=payload)
    assert result["final_status"] == "FAIL_V22_046_RESEARCH_ONLY_GATE_FAILED"


def test_fail_when_v22_045_source_files_mutated_is_true(tmp_path):
    repo = tmp_path / "repo"
    payload = archive_summary(repo, source_files_mutated=True)
    _, result, _ = run_execute(tmp_path, archive_payload=payload)
    assert result["final_status"] == "FAIL_V22_046_RESEARCH_ONLY_GATE_FAILED"


def test_child_execution_order_is_v22_044_then_v22_045(tmp_path):
    _, result, calls = run_execute(tmp_path)
    assert calls == ["V22.044", "V22.045"]
    assert result["child_execution_order"] == ["V22.044", "V22.045"]
    assert result["v22_045_ran_after_v22_044_passed"] is True


def test_warnings_from_v22_045_are_carried_into_v22_046_summary(tmp_path):
    _, result, _ = run_execute(tmp_path)
    assert result["warning_count"] == 2
    assert result["warnings"] == ["optional forward missing", "optional option missing"]


def test_summary_is_written_on_pass(tmp_path):
    repo, result, _ = run_execute(tmp_path)
    path = repo / module.OUT_REL / "v22_046_summary.json"
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["final_status"] == result["final_status"]


def test_summary_is_written_on_fail(tmp_path):
    repo, result, _ = run_execute(tmp_path, refresh_exit=2)
    assert result["final_status"].startswith("FAIL_")
    assert (repo / module.OUT_REL / "v22_046_summary.json").exists()


def test_markdown_full_cycle_report_is_written_on_pass(tmp_path):
    repo, _, _ = run_execute(tmp_path)
    report = repo / module.OUT_REL / module.REPORT_NAME
    assert report.exists()
    assert "Daily Research Full Cycle Report" in report.read_text(encoding="utf-8")


def test_no_forbidden_direct_invocation_or_market_imports_are_present():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    constants: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            constants.append(node.value.lower())
    banned_imports = {"moomoo", "futu", "yfinance", "requests", "urllib", "socket", "http"}
    assert imported.isdisjoint(banned_imports)
    text = " ".join(constants)
    forbidden = ["run_v21", "run_v22_040", "abcde_rerun", "run_v22_020", "run_v22_032", "run_v22_043"]
    assert all(token not in text for token in forbidden)
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "capture_output=True" not in source


def test_stdout_stderr_child_logs_are_written(tmp_path):
    repo, result, _ = run_execute(tmp_path)
    assert Path(result["v22_044_stdout_log_path"]).exists()
    assert Path(result["v22_044_stderr_log_path"]).exists()
    assert Path(result["v22_045_stdout_log_path"]).exists()
    assert Path(result["v22_045_stderr_log_path"]).exists()


def test_default_child_runner_streams_stdout_stderr_to_files(tmp_path):
    stdout_path = tmp_path / "stdout.log"
    stderr_path = tmp_path / "stderr.log"
    exit_code = module.default_child_runner(
        [
            sys.executable,
            "-c",
            "import sys; print('streamed stdout'); print('streamed stderr', file=sys.stderr)",
        ],
        tmp_path,
        stdout_path,
        stderr_path,
    )
    assert exit_code == 0
    assert stdout_path.read_text(encoding="utf-8").strip() == "streamed stdout"
    assert stderr_path.read_text(encoding="utf-8").strip() == "streamed stderr"


def test_keyboard_interrupt_during_v22_044_writes_interrupted_summary(tmp_path):
    repo = seed_repo(tmp_path)
    calls: list[str] = []
    result = module.run(repo, execute=True, child_runner=interrupting_runner_factory(repo, "V22.044", calls))
    assert result["final_status"] == "FAIL_V22_046_INTERRUPTED_BY_USER"
    assert result["final_decision"] == "DAILY_RESEARCH_FULL_CYCLE_INTERRUPTED_NOT_ACCEPTED"
    assert result["interrupted"] is True
    assert result["interrupted_stage"] == "V22.044"
    assert result["full_cycle_accepted"] is False
    assert (repo / module.OUT_REL / "v22_046_summary.json").exists()


def test_keyboard_interrupt_during_v22_044_does_not_run_v22_045(tmp_path):
    repo = seed_repo(tmp_path)
    calls: list[str] = []
    result = module.run(repo, execute=True, child_runner=interrupting_runner_factory(repo, "V22.044", calls))
    assert calls == ["V22.044"]
    assert result["v22_045_child_exit_code"] is None
    assert result["v22_045_ran_after_v22_044_passed"] is False


def test_keyboard_interrupt_during_v22_045_preserves_v22_044_pass_information(tmp_path):
    repo = seed_repo(tmp_path)
    calls: list[str] = []
    result = module.run(repo, execute=True, child_runner=interrupting_runner_factory(repo, "V22.045", calls))
    assert calls == ["V22.044", "V22.045"]
    assert result["final_status"] == "FAIL_V22_046_INTERRUPTED_BY_USER"
    assert result["interrupted_stage"] == "V22.045"
    assert result["v22_044_final_status"] == "PASS_V22_044_DAILY_SINGLE_ENTRYPOINT_FROZEN"
    assert result["latest_research_date"] == "2026-07-08"
    assert result["full_cycle_accepted"] is False


def test_child_launch_failure_writes_summary_and_returns_nonzero(tmp_path):
    repo = seed_repo(tmp_path)

    def runner(cmd, cwd, stdout_path, stderr_path):
        raise module.ChildProcessLaunchError("cannot launch child")

    result = module.run(repo, execute=True, child_runner=runner)
    assert result["final_status"] == "FAIL_V22_046_CHILD_PROCESS_LAUNCH_FAILED"
    assert result["child_process_launch_error"] == "cannot launch child"
    assert (repo / module.OUT_REL / "v22_046_summary.json").exists()
    original = module.default_child_runner
    try:
        module.default_child_runner = runner
        assert module.main(["--repo-root", str(repo), "--execute"]) == 1
    finally:
        module.default_child_runner = original


def test_exit_code_is_zero_only_for_pass_and_nonzero_for_fail(tmp_path):
    pass_repo = seed_repo(tmp_path / "pass")
    pass_runner = runner_factory(pass_repo)
    original = module.default_child_runner
    try:
        module.default_child_runner = pass_runner
        assert module.main(["--repo-root", str(pass_repo), "--execute"]) == 0
    finally:
        module.default_child_runner = original

    fail_repo = seed_repo(tmp_path / "fail")
    fail_runner = runner_factory(fail_repo, refresh_exit=1)
    try:
        module.default_child_runner = fail_runner
        assert module.main(["--repo-root", str(fail_repo), "--execute"]) == 1
    finally:
        module.default_child_runner = original
