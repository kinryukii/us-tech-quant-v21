from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


OUT = Path("outputs/v21/V21.149_E_R1_DEFENSIVE_OVERLAY_AND_INVALID_TRIAL_AUDIT")
V148 = Path("outputs/v21/V21.148_E_R1_A1_PIT_LITE_REPLAY_DIAGNOSTIC_ONLY")

REQUIRED_FILES = [
    "V21.149_summary.json",
    "V21.149_invalid_trial_root_cause_audit.csv",
    "V21.149_invalid_trial_by_ticker.csv",
    "V21.149_invalid_trial_by_regime_year.csv",
    "V21.149_valid_only_replay_robustness.csv",
    "V21.149_e_r1_defensive_overlay_tests.csv",
    "V21.149_overlay_return_tail_tradeoff.csv",
    "V21.149_overlay_classification.csv",
    "V21.149_a1_primary_control_confirmation.csv",
    "V21.149_forward_maturity_interaction.csv",
    "V21.149_remaining_blockers.csv",
    "V21.149_readable_report.txt",
]


def test_required_outputs_exist() -> None:
    assert OUT.exists()
    for name in REQUIRED_FILES:
        assert (OUT / name).exists(), name


def test_controls_remain_research_only() -> None:
    summary = json.loads((OUT / "V21.149_summary.json").read_text(encoding="utf-8"))
    assert summary["research_only"] is True
    assert summary["official_adoption_allowed"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["protected_outputs_modified"] is False
    assert summary["strategy_adoption_allowed"] is False
    assert summary["overlay_adoption_allowed"] is False
    assert summary["pit_strict_claim_allowed"] is False
    assert summary["adoption_grade_backtest"] is False
    assert summary["replay_diagnostic_only"] is True


def test_v21_148_inputs_exist() -> None:
    assert (V148 / "V21.148_summary.json").exists()
    assert (V148 / "V21.148_trial_level_replay_returns.csv").exists()
    assert (V148 / "V21.148_invalid_trials.csv").exists()


def test_invalid_trial_root_cause_audit_exists() -> None:
    df = pd.read_csv(OUT / "V21.149_invalid_trial_root_cause_audit.csv")
    assert not df.empty
    expected = {
        "strategy",
        "portfolio_size",
        "horizon",
        "regime",
        "sampled_asof_year",
        "root_cause",
        "invalid_trial_count",
    }
    assert expected.issubset(df.columns)


def test_valid_only_and_overlay_outputs_exist() -> None:
    robust = pd.read_csv(OUT / "V21.149_valid_only_replay_robustness.csv")
    overlays = pd.read_csv(OUT / "V21.149_e_r1_defensive_overlay_tests.csv")
    assert not robust.empty
    assert not overlays.empty
    assert {"E_R1_win_rate_vs_A1", "E_R1_left_tail_advantage"}.issubset(robust.columns)
    assert {"overlay_rule", "left_tail_improvement_vs_A1", "return_sacrifice"}.issubset(overlays.columns)


def test_a1_primary_control_confirmation_exists() -> None:
    df = pd.read_csv(OUT / "V21.149_a1_primary_control_confirmation.csv")
    assert not df.empty
    status = dict(zip(df["item"], df["status"]))
    assert str(status["A1_primary_control_reconfirmed"]).lower() == "true"
    assert str(status["E_R1_is_A1_replacement_candidate"]).lower() == "false"


def test_report_has_status_and_decision() -> None:
    report = (OUT / "V21.149_readable_report.txt").read_text(encoding="utf-8")
    assert "FINAL_STATUS=" in report
    assert "DECISION=" in report
