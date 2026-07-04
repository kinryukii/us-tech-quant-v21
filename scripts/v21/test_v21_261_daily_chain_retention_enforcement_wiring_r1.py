from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
from pathlib import Path

P = Path(__file__).with_name("v21_261_daily_chain_retention_enforcement_wiring_r1.py")
S = importlib.util.spec_from_file_location("m261", P)
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# wrapper", encoding="utf-8")


def rows(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def seed(tmp_path: Path, daily_wrapper: bool = True, retention_wrapper: bool = True, v260_status: str = "PASS_V21_260_RETENTION_GUARD_DRYRUN_READY") -> Path:
    repo = tmp_path / "repo"
    if daily_wrapper:
        touch(repo / m.DAILY_WRAPPER_REL)
    if retention_wrapper:
        touch(repo / m.RETENTION_WRAPPER_REL)
    write_json(repo / m.V256_SUMMARY_REL, {"final_status": "PASS_V21_256_DAILY_MASTER_WRAPPER_READY", "final_decision": "READY"})
    write_json(repo / m.V260_SUMMARY_REL, {"final_status": v260_status, "final_decision": "RETENTION_GUARD_DRYRUN_READY"})
    return repo


def runner_factory(calls: list[str], fail_step: str | None = None, verify_warn: bool = False):
    def runner(cmd: list[str], cwd: Path, log_path: Path):
        text = " ".join(cmd)
        if "run_v21_256" in text:
            calls.append("daily")
            if fail_step == "daily":
                return 1, "daily failed"
            write_json(cwd / m.V256_SUMMARY_REL, {"final_status": "PASS_V21_256_DAILY_MASTER_WRAPPER_READY", "final_decision": "READY"})
        elif "-Execute" in cmd:
            calls.append("retention_execute")
            if fail_step == "retention_execute":
                return 1, "retention execute failed"
            write_json(cwd / m.V260_SUMMARY_REL, {"final_status": "PASS_V21_260_RETENTION_ENFORCEMENT_COMPLETED", "final_decision": "DONE"})
        else:
            calls.append("retention_verify")
            if fail_step == "retention_verify":
                write_json(cwd / m.V260_SUMMARY_REL, {"final_status": "FAIL_V21_260_RETENTION_ENFORCEMENT_ERROR", "final_decision": "FAIL"})
                return 1, "verify failed"
            status = "WARN_V21_260_RETENTION_VIOLATIONS_FOUND_DRYRUN_READY" if verify_warn else "PASS_V21_260_RETENTION_GUARD_DRYRUN_READY"
            write_json(cwd / m.V260_SUMMARY_REL, {"final_status": status, "final_decision": "VERIFY"})
        return 0, ""
    return runner


def test_dryrun_does_not_execute_child_wrappers(tmp_path):
    repo = seed(tmp_path)
    calls: list[str] = []
    s = m.run(repo, mode="DryRun", runner=runner_factory(calls))
    assert calls == []
    assert s["child_step_attempted_count"] == 0


def test_missing_daily_wrapper_fails_safely(tmp_path):
    repo = seed(tmp_path, daily_wrapper=False)
    s = m.run(repo, mode="DryRun")
    assert s["final_status"] == "FAIL_V21_261_DAILY_CHAIN_OR_RETENTION_FAILED"


def test_missing_retention_wrapper_fails_safely(tmp_path):
    repo = seed(tmp_path, retention_wrapper=False)
    s = m.run(repo, mode="DryRun")
    assert s["final_status"] == "FAIL_V21_261_DAILY_CHAIN_OR_RETENTION_FAILED"


def test_execute_calls_daily_before_retention_and_verify_after(tmp_path):
    repo = seed(tmp_path)
    calls: list[str] = []
    s = m.run(repo, mode="Execute", runner=runner_factory(calls))
    assert calls == ["daily", "retention_execute", "retention_verify"]
    assert s["final_status"] == "PASS_V21_261_DAILY_CHAIN_RETENTION_ENFORCED"


def test_retention_verify_runs_after_retention_execute(tmp_path):
    repo = seed(tmp_path)
    calls: list[str] = []
    m.run(repo, mode="Execute", runner=runner_factory(calls))
    assert calls.index("retention_verify") > calls.index("retention_execute")


def test_violation_after_execute_returns_warn_or_fail(tmp_path):
    repo = seed(tmp_path)
    calls: list[str] = []
    s = m.run(repo, mode="Execute", runner=runner_factory(calls, verify_warn=True))
    assert s["final_status"] == "WARN_V21_261_DAILY_CHAIN_DONE_RETENTION_WARN"


def test_summary_schema_and_gates(tmp_path):
    repo = seed(tmp_path)
    s = m.run(repo)
    payload = json.loads((repo / m.OUT_REL / "v21_261_summary.json").read_text(encoding="utf-8"))
    for key in ["final_status", "final_decision", "run_mode", "accepted_daily_wrapper_exists", "retention_wrapper_exists", "daily_chain_final_status", "retention_final_status", "retention_verify_clean", "child_step_count", "research_only", "broker_action_allowed", "official_adoption_allowed", "factor_promotion_allowed", "market_data_fetch_allowed", "output_root", "warning_count", "error_count"]:
        assert key in payload
    assert s["broker_action_allowed"] is False
    assert s["official_adoption_allowed"] is False
    assert s["factor_promotion_allowed"] is False


def test_v21_260_clean_status_accepted(tmp_path):
    repo = seed(tmp_path, v260_status="PASS_V21_260_RETENTION_GUARD_DRYRUN_READY")
    s = m.run(repo)
    assert s["retention_verify_clean"] is True


def test_manifests_generated(tmp_path):
    repo = seed(tmp_path)
    m.run(repo)
    assert rows(repo / m.OUT_REL / "daily_chain_retention_wiring_manifest.csv")
    assert rows(repo / m.OUT_REL / "post_run_retention_enforcement_manifest.csv")


def test_wrapper_dryrun_exits_zero():
    proc = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", "scripts\\v21\\run_v21_261_daily_chain_retention_enforcement_wiring_r1.ps1", "-DryRun"],
        cwd=Path(__file__).parents[2],
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert proc.returncode == 0


def test_wrapper_execute_can_be_mocked_without_real_access(tmp_path):
    repo = seed(tmp_path)
    calls: list[str] = []
    s = m.run(repo, mode="Execute", runner=runner_factory(calls))
    assert s["child_step_attempted_count"] == 3
    assert calls == ["daily", "retention_execute", "retention_verify"]
