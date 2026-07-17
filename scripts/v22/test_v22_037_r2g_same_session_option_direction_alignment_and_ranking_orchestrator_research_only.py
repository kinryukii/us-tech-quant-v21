from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).with_name(
    "v22_037_r2g_same_session_option_direction_alignment_and_ranking_orchestrator_research_only.py"
)
spec = importlib.util.spec_from_file_location("r2g", MODULE_PATH)
assert spec is not None and spec.loader is not None
r2g = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = r2g
spec.loader.exec_module(r2g)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def seed(
    repo: Path,
    panel: str,
    direction: str,
    *,
    r2e_status: str = "PASS_R2E",
    direction_status: str = "PASS_DIRECTION",
    r2f_status: str = "PASS_R2F",
) -> None:
    write_json(
        repo / r2g.R2E_REL / "v22_037_r2e_summary.json",
        {"final_status": r2e_status, "research_only": True},
    )
    write_json(
        repo / r2g.DIRECTION_REL / "v22_042_r2_summary.json",
        {
            "final_status": direction_status,
            "direction_source_time_utc": direction,
            "research_only": True,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
        },
    )
    write_json(
        repo / r2g.R2F_REL / "v22_037_r2f_summary.json",
        {
            "final_status": r2f_status,
            "final_decision": "NO_TRADE",
            "panel_reference_time_utc": panel,
            "direction_source_time_utc": direction,
            "research_only": True,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "selected_contract_count": 0,
            "shadow_selected_contract_count": 0,
        },
    )


def test_parse_datetime_z():
    assert r2g.parse_datetime("2026-07-10T20:00:00Z") == datetime(
        2026, 7, 10, 20, 0, tzinfo=timezone.utc
    )


def test_minutes_between_absolute():
    a = datetime(2026, 7, 10, 20, 0, tzinfo=timezone.utc)
    b = datetime(2026, 7, 10, 19, 30, tzinfo=timezone.utc)
    assert r2g.minutes_between(a, b) == 30.0


def test_auto_resolution_prefers_ps1(tmp_path):
    py = tmp_path / "scripts/v22/v22_037_r2e_x.py"
    ps1 = tmp_path / "scripts/v22/run_v22_037_r2e_x.ps1"
    py.parent.mkdir(parents=True)
    py.write_text("", encoding="utf-8")
    ps1.write_text("", encoding="utf-8")
    found = r2g.resolve_auto_path(
        tmp_path, ["scripts/v22/*r2e*.py", "scripts/v22/*r2e*.ps1"]
    )
    assert found == ps1.resolve()


def test_audit_passes_when_aligned_and_fresh(tmp_path):
    seed(tmp_path, "2026-07-10T20:00:00+00:00", "2026-07-10T20:10:00+00:00")
    _, context = r2g.audit_state(
        r2g.load_state(tmp_path),
        r2g.Config(
            max_direction_panel_gap_minutes=30,
            max_panel_age_minutes=90,
            max_direction_age_minutes=90,
        ),
        datetime(2026, 7, 10, 20, 20, tzinfo=timezone.utc),
    )
    assert context["integrity_checks_passed"] is True
    assert context["freshness_checks_passed"] is True
    assert context["direction_panel_gap_minutes"] == 10.0


def test_gap_blocks_freshness(tmp_path):
    seed(tmp_path, "2026-07-10T14:30:00+00:00", "2026-07-10T20:00:00+00:00")
    _, context = r2g.audit_state(
        r2g.load_state(tmp_path),
        r2g.Config(
            max_direction_panel_gap_minutes=30,
            max_panel_age_minutes=1000,
            max_direction_age_minutes=1000,
        ),
        datetime(2026, 7, 10, 20, 5, tzinfo=timezone.utc),
    )
    assert context["freshness_checks_passed"] is False
    assert context["direction_panel_gap_minutes"] == 330.0


def test_stale_panel_blocks_freshness(tmp_path):
    seed(tmp_path, "2026-07-10T18:00:00+00:00", "2026-07-10T20:00:00+00:00")
    _, context = r2g.audit_state(
        r2g.load_state(tmp_path),
        r2g.Config(
            max_direction_panel_gap_minutes=180,
            max_panel_age_minutes=30,
            max_direction_age_minutes=30,
        ),
        datetime(2026, 7, 10, 20, 10, tzinfo=timezone.utc),
    )
    assert context["freshness_checks_passed"] is False
    assert context["panel_age_minutes"] == 130.0


def test_failed_r2f_breaks_integrity(tmp_path):
    seed(
        tmp_path,
        "2026-07-10T20:00:00+00:00",
        "2026-07-10T20:00:00+00:00",
        r2f_status="FAIL_R2F",
    )
    _, context = r2g.audit_state(
        r2g.load_state(tmp_path),
        r2g.Config(),
        datetime(2026, 7, 10, 20, 10, tzinfo=timezone.utc),
    )
    assert context["integrity_checks_passed"] is False


def test_execute_audit_only_pass(tmp_path):
    seed(tmp_path, "2026-07-10T20:00:00+00:00", "2026-07-10T20:00:00+00:00")
    out = tmp_path / "out"
    summary = r2g.execute(
        tmp_path,
        out,
        None,
        False,
        r2g.Config(
            max_direction_panel_gap_minutes=30,
            max_panel_age_minutes=90,
            max_direction_age_minutes=90,
        ),
        now=datetime(2026, 7, 10, 20, 10, tzinfo=timezone.utc),
    )
    assert summary["final_status"] == r2g.PASS_STATUS
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False
    assert (out / "stage_ledger.csv").exists()
    assert (out / "timestamp_alignment_audit.csv").exists()


def test_missing_inputs_fail_closed(tmp_path):
    summary = r2g.execute(tmp_path, tmp_path / "out", None, False, r2g.Config())
    assert summary["final_status"] == r2g.FAIL_STATUS
    assert summary["final_decision"] == r2g.FAIL_DECISION
    assert summary["broker_action_allowed"] is False


def test_invalid_manifest_fails(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text("{}", encoding="utf-8")
    try:
        r2g.resolve_manifest(path)
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError")


def test_replace_tokens():
    values = r2g.replace_tokens(
        ["{repo_root}/x", "{n}"], {"repo_root": "D:/repo", "n": "30"}
    )
    assert values == ["D:/repo/x", "30"]


def test_no_trade_safety_contract():
    assert r2g.WARN_DECISION.startswith("NO_TRADE")
    assert r2g.FAIL_DECISION.startswith("BLOCKED")
    assert r2g.PASS_DECISION.endswith("RESEARCH_ONLY")
