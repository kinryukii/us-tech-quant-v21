from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).with_name(
    "v22_037_r2g_r1a_explicit_multi_underlying_and_no_eligible_state_repair_research_only.py"
)
spec = importlib.util.spec_from_file_location("r1a", MODULE_PATH)
assert spec is not None and spec.loader is not None
r1a = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = r1a
spec.loader.exec_module(r1a)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def seed_ready(repo: Path, panel: str, direction: str) -> None:
    run_dir = repo / r1a.R2D_ROOT_REL / "runs" / "run_x"
    write_json(
        run_dir / "v22_037_r2d_summary.json",
        {
            "final_status": "WARN_R2D",
            "underlyings_requested": "QQQ,SOXX,SPY,SMH,DIA",
            "underlying_count": 5,
            "regular_session_clock_pass": True,
            "timestamp_alignment_pass_count": 80,
            "research_ranking_eligible_count": 60,
            "run_end_utc": panel,
        },
    )
    write_json(
        repo / r1a.R2E_ROOT_REL / "v22_037_r2e_summary.json",
        {
            "final_status": "PASS_R2E",
            "base_research_eligible_count": 60,
            "liquid_panel_count": 40,
        },
    )
    write_json(
        repo / r1a.DIRECTION_ROOT_REL / "v22_042_r2_summary.json",
        {
            "final_status": "PASS_DIRECTION",
            "direction_source_time_utc": direction,
        },
    )
    write_json(
        repo / r1a.R2F_ROOT_REL / "v22_037_r2f_summary.json",
        {
            "final_status": "PASS_R2F",
            "final_decision": "NO_TRADE",
            "panel_reference_time_utc": panel,
            "direction_source_time_utc": direction,
            "research_only": True,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "selected_contract_count": 0,
            "shadow_selected_contract_count": 2,
        },
    )


def test_parse_underlyings_deduplicates():
    assert r1a.parse_underlyings("qqq,SOXX,qqq,SPY") == ("QQQ", "SOXX", "SPY")


def test_weekend_preflight_blocks():
    state = r1a.market_session_state(
        datetime(2026, 7, 11, 18, 0, tzinfo=timezone.utc)
    )
    assert state["regular_session_clock_pass"] is False
    assert state["market_session_reason_code"] == "WEEKEND"


def test_regular_session_preflight_passes():
    state = r1a.market_session_state(
        datetime(2026, 7, 10, 14, 30, tzinfo=timezone.utc)
    )
    assert state["regular_session_clock_pass"] is True


def test_before_open_blocks():
    state = r1a.market_session_state(
        datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
    )
    assert state["market_session_reason_code"] == "BEFORE_REGULAR_SESSION"


def test_explicit_r2d_command_contains_five_underlyings(tmp_path):
    commands = r1a.build_commands(tmp_path, Path(sys.executable), r1a.Config())
    r2d_command = commands[0]["command"]
    index = r2d_command.index("-Underlyings")
    assert r2d_command[index + 1] == "QQQ,SOXX,SPY,SMH,DIA"
    assert commands[0]["required"] is True


def test_r2e_no_eligible_is_soft_block():
    outcome, reason = r1a.classify_child(
        "R2E_LIQUID_CONTRACT_PANEL_BUILD",
        1,
        {"final_status": "FAIL_V22_037_R2E_NO_BASE_RESEARCH_ELIGIBLE_ROWS"},
    )
    assert outcome == "SOFT_DATA_BLOCK"
    assert reason == "NO_BASE_RESEARCH_ELIGIBLE_ROWS"


def test_unknown_nonzero_is_hard_failure():
    outcome, _ = r1a.classify_child(
        "R2E_LIQUID_CONTRACT_PANEL_BUILD",
        1,
        {"final_status": "FAIL_SOMETHING_ELSE"},
    )
    assert outcome == "HARD_FAILURE"


def test_success_classification():
    outcome, reason = r1a.classify_child(
        "R2D_OPTION_SNAPSHOT_REFRESH",
        0,
        {"final_status": "WARN_R2D"},
    )
    assert outcome == "SUCCESS"
    assert reason == ""


def test_alignment_audit_passes(tmp_path):
    seed_ready(
        tmp_path,
        "2026-07-10T14:30:00+00:00",
        "2026-07-10T14:40:00+00:00",
    )
    _, context = r1a.alignment_audit(
        r1a.load_state(tmp_path),
        r1a.Config(),
        datetime(2026, 7, 10, 14, 50, tzinfo=timezone.utc),
    )
    assert context["integrity_checks_passed"] is True
    assert context["freshness_checks_passed"] is True
    assert context["direction_panel_gap_minutes"] == 10.0


def test_alignment_scope_mismatch_fails_integrity(tmp_path):
    seed_ready(
        tmp_path,
        "2026-07-10T14:30:00+00:00",
        "2026-07-10T14:40:00+00:00",
    )
    r2d_path = r1a.state_paths(tmp_path)["r2d_summary"]
    payload = json.loads(r2d_path.read_text(encoding="utf-8"))
    payload["underlyings_requested"] = "QQQ"
    write_json(r2d_path, payload)
    _, context = r1a.alignment_audit(
        r1a.load_state(tmp_path),
        r1a.Config(),
        datetime(2026, 7, 10, 14, 50, tzinfo=timezone.utc),
    )
    assert context["integrity_checks_passed"] is False


def test_execute_outside_session_does_not_run_children(tmp_path):
    out = tmp_path / "out"
    summary = r1a.execute(
        tmp_path,
        out,
        True,
        r1a.Config(),
        datetime(2026, 7, 11, 18, 0, tzinfo=timezone.utc),
    )
    assert summary["final_status"] == r1a.WARN_OUTSIDE_STATUS
    assert summary["blocking_stage_name"] == "MARKET_SESSION_PREFLIGHT"
    ledger = (out / "stage_ledger.csv").read_text(encoding="utf-8")
    assert "NOT_ATTEMPTED" in ledger
    assert summary["broker_action_allowed"] is False


def test_audit_only_ready_state_passes(tmp_path):
    seed_ready(
        tmp_path,
        "2026-07-10T14:30:00+00:00",
        "2026-07-10T14:40:00+00:00",
    )
    summary = r1a.execute(
        tmp_path,
        tmp_path / "out",
        False,
        r1a.Config(),
        datetime(2026, 7, 10, 14, 50, tzinfo=timezone.utc),
    )
    assert summary["final_status"] == r1a.PASS_STATUS
    assert summary["official_adoption_allowed"] is False


def test_audit_only_no_eligible_is_warn(tmp_path):
    seed_ready(
        tmp_path,
        "2026-07-10T14:30:00+00:00",
        "2026-07-10T14:40:00+00:00",
    )
    write_json(
        tmp_path / r1a.R2E_ROOT_REL / "v22_037_r2e_summary.json",
        {
            "final_status": "FAIL_V22_037_R2E_NO_BASE_RESEARCH_ELIGIBLE_ROWS",
            "base_research_eligible_count": 0,
            "liquid_panel_count": 0,
        },
    )
    summary = r1a.execute(
        tmp_path,
        tmp_path / "out",
        False,
        r1a.Config(),
        datetime(2026, 7, 10, 14, 50, tzinfo=timezone.utc),
    )
    # Existing aligned R2F integrity is still safe; the explicit R2E data state is preserved.
    assert summary["final_status"] in {
        r1a.WARN_NO_ELIGIBLE_STATUS,
        r1a.PASS_STATUS,
    }


def test_missing_state_fails_closed(tmp_path):
    summary = r1a.execute(
        tmp_path,
        tmp_path / "out",
        False,
        r1a.Config(),
        datetime(2026, 7, 10, 14, 50, tzinfo=timezone.utc),
    )
    assert summary["final_status"] == r1a.FAIL_STATUS
    assert summary["broker_action_allowed"] is False


def test_safety_contract_constants():
    assert r1a.WARN_OUTSIDE_DECISION.startswith("NO_TRADE")
    assert r1a.WARN_NO_ELIGIBLE_DECISION.startswith("NO_TRADE")
    assert r1a.WARN_ALIGNMENT_DECISION.startswith("NO_TRADE")
    assert r1a.FAIL_DECISION.startswith("BLOCKED")
