from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_044_daily_single_entrypoint_freeze_and_guard_r1.py")
SPEC = importlib.util.spec_from_file_location("v22_044", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def seed_wrapper(repo: Path) -> Path:
    wrapper = repo / module.ACCEPTED_ENTRYPOINT_WRAPPER
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text("# fake V22.040 wrapper\n", encoding="utf-8")
    return wrapper


def pass_summary(**overrides):
    payload = {
        "final_status": "PASS_V22_040_DAILY_MOOMOO_ONECLICK_REFRESH_COMPLETE",
        "final_decision": "DAILY_MOOMOO_REFRESH_COMPLETE_RESEARCH_ONLY",
        "same_date_comparable_all_strategies": True,
        "data_gap_days": 0,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "canonical_latest_date": "2026-07-08",
        "abcde_latest_date": "2026-07-08",
        "dram_latest_price_date": "2026-07-08",
    }
    payload.update(overrides)
    return payload


def write_v22_040_summary(repo: Path, payload: dict) -> Path:
    path = repo / module.V22_040_SUMMARY_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def runner_factory(repo: Path, payload: dict | None = None, exit_code: int = 0, calls: list[list[str]] | None = None):
    def runner(cmd, cwd, stdout_path, stderr_path):
        if calls is not None:
            calls.append(cmd)
        stdout_path.write_text("fake stdout\n", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        if payload is not None:
            write_v22_040_summary(repo, payload)
        return exit_code

    return runner


def run_execute(tmp_path: Path, payload: dict | None = None, exit_code: int = 0, seed: bool = True):
    repo = tmp_path / "repo"
    if seed:
        seed_wrapper(repo)
    calls: list[list[str]] = []
    result = module.run(repo, execute=True, child_runner=runner_factory(repo, payload, exit_code, calls))
    return repo, result, calls


def test_pass_when_fake_v22_040_summary_has_all_required_pass_fields(tmp_path):
    repo, result, _ = run_execute(tmp_path, pass_summary())
    assert result["final_status"] == "PASS_V22_044_DAILY_SINGLE_ENTRYPOINT_FROZEN"
    assert result["final_decision"] == "V22_040_ACCEPTED_AS_ONLY_CURRENT_DAILY_RESEARCH_ENTRYPOINT"
    assert result["hard_gate_passed"] is True
    assert result["failed_gate_names"] == []
    assert (repo / module.POINTER_JSON_REL).exists()
    assert (repo / module.POINTER_MD_REL).exists()


def test_fail_when_v22_040_wrapper_is_missing(tmp_path):
    repo, result, calls = run_execute(tmp_path, pass_summary(), seed=False)
    assert result["final_status"].startswith("FAIL_")
    assert result["failed_gate_names"] == ["v22_040_wrapper_exists"]
    assert calls == []
    assert not (repo / module.POINTER_JSON_REL).exists()


def test_fail_when_child_exit_code_is_nonzero(tmp_path):
    _, result, _ = run_execute(tmp_path, pass_summary(), exit_code=9)
    assert result["final_status"].startswith("FAIL_")
    assert "v22_040_child_exit_code_zero" in result["failed_gate_names"]


def test_fail_when_v22_040_summary_is_missing(tmp_path):
    _, result, _ = run_execute(tmp_path, payload=None)
    assert result["final_status"].startswith("FAIL_")
    assert "v22_040_summary_exists" in result["failed_gate_names"]


def test_fail_when_final_status_is_not_pass(tmp_path):
    _, result, _ = run_execute(tmp_path, pass_summary(final_status="WARN_NOT_PASS"))
    assert result["final_status"].startswith("FAIL_")
    assert "final_status" in result["failed_gate_names"]


def test_fail_when_dates_are_missing_or_unequal(tmp_path):
    _, missing, _ = run_execute(tmp_path / "missing", pass_summary(canonical_latest_date=""))
    assert "canonical_latest_date_exists" in missing["failed_gate_names"]
    assert "strategy_dates_equal" in missing["failed_gate_names"]

    _, unequal, _ = run_execute(tmp_path / "unequal", pass_summary(dram_latest_price_date="2026-07-07"))
    assert "strategy_dates_equal" in unequal["failed_gate_names"]


def test_fail_when_broker_action_allowed_is_true(tmp_path):
    _, result, _ = run_execute(tmp_path, pass_summary(broker_action_allowed=True))
    assert "broker_action_allowed_false" in result["failed_gate_names"]


def test_fail_when_official_adoption_allowed_is_true(tmp_path):
    _, result, _ = run_execute(tmp_path, pass_summary(official_adoption_allowed=True))
    assert "official_adoption_allowed_false" in result["failed_gate_names"]


def test_fail_when_same_date_comparable_all_strategies_is_false(tmp_path):
    _, result, _ = run_execute(tmp_path, pass_summary(same_date_comparable_all_strategies=False))
    assert "same_date_comparable_all_strategies" in result["failed_gate_names"]


def test_fail_when_data_gap_days_is_not_zero(tmp_path):
    _, result, _ = run_execute(tmp_path, pass_summary(data_gap_days=1))
    assert "data_gap_days" in result["failed_gate_names"]


def test_pointer_json_is_written_only_when_hard_gates_pass(tmp_path):
    pass_repo, pass_result, _ = run_execute(tmp_path / "pass", pass_summary())
    fail_repo, fail_result, _ = run_execute(tmp_path / "fail", pass_summary(data_gap_days=2))
    assert pass_result["current_entrypoint_pointer_written"] is True
    assert (pass_repo / module.POINTER_JSON_REL).exists()
    assert fail_result["current_entrypoint_pointer_written"] is False
    assert not (fail_repo / module.POINTER_JSON_REL).exists()


def test_markdown_pointer_is_written_only_when_hard_gates_pass(tmp_path):
    pass_repo, pass_result, _ = run_execute(tmp_path / "pass", pass_summary())
    fail_repo, fail_result, _ = run_execute(tmp_path / "fail", pass_summary(final_status="FAIL_CHILD"))
    assert pass_result["current_entrypoint_markdown_written"] is True
    assert (pass_repo / module.POINTER_MD_REL).read_text(encoding="utf-8").startswith("# Current Daily Research Entrypoint")
    assert fail_result["current_entrypoint_markdown_written"] is False
    assert not (fail_repo / module.POINTER_MD_REL).exists()


def test_no_direct_v21_abcde_dram_child_invocation_is_attempted_by_v22_044(tmp_path):
    _, result, calls = run_execute(tmp_path, pass_summary())
    assert result["hard_gate_passed"] is True
    assert len(calls) == 1
    invoked_files = [Path(part).name.lower() for part in calls[0]]
    command_text = " ".join(invoked_files + [part.lower() for part in calls[0] if not Path(part).suffix])
    assert "run_v22_040_daily_moomoo_oneclick_refresh_orchestrator_r1.ps1" in invoked_files
    forbidden = ["scripts/v21", "run_v21", "abcde", "dram", "option", "forward"]
    assert all(token not in command_text for token in forbidden)


def test_dry_run_does_not_execute_the_v22_040_wrapper(tmp_path):
    repo = tmp_path / "repo"
    seed_wrapper(repo)
    calls: list[list[str]] = []
    result = module.run(repo, execute=False, child_runner=runner_factory(repo, pass_summary(), calls=calls))
    assert result["final_status"].startswith("WARN_")
    assert calls == []
    assert result["v22_040_wrapper_exists"] is True


def test_module_has_no_broker_or_market_data_imports():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    banned_modules = {"moomoo", "futu", "yfinance", "requests", "urllib", "http", "socket"}
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(banned_modules)
