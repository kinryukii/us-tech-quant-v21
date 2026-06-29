from __future__ import annotations

from pathlib import Path

import pandas as pd


OUT = Path("outputs/v21/V21.150_ENTRY_EXIT_EXECUTION_OVERLAY_GRID")
REQUIRED = [
    "execution_overlay_summary.csv",
    "strategy_by_execution_variant_metrics.csv",
    "top20_execution_comparison.csv",
    "top50_execution_comparison.csv",
    "invalid_trial_audit.csv",
    "skipped_entry_reason_audit.csv",
    "left_tail_comparison.csv",
    "profit_giveback_comparison.csv",
    "V21.150_ENTRY_EXIT_EXECUTION_OVERLAY_GRID_REPORT.md",
    "compact_readable_report.txt",
]


def test_required_outputs_created() -> None:
    assert OUT.exists()
    for name in REQUIRED:
        assert (OUT / name).exists(), name


def test_controls_and_no_adoption() -> None:
    s = pd.read_csv(OUT / "execution_overlay_summary.csv").iloc[0]
    assert bool(s["research_only"]) is True
    assert bool(s["official_adoption_allowed"]) is False
    assert bool(s["broker_action_allowed"]) is False
    assert bool(s["protected_outputs_modified"]) is False


def test_no_broker_or_official_mutation_claimed() -> None:
    report = (OUT / "compact_readable_report.txt").read_text(encoding="utf-8")
    assert "protected_outputs_modified=false" in report
    assert "official_adoption_allowed=false" in report
    assert "broker_action_allowed=false" in report


def test_no_lookahead_execution_proxy() -> None:
    s = pd.read_csv(OUT / "execution_overlay_summary.csv").iloc[0]
    assert bool(s["intraday_data_available"]) is False
    report = (OUT / "V21.150_ENTRY_EXIT_EXECUTION_OVERLAY_GRID_REPORT.md").read_text(encoding="utf-8")
    assert "intraday_data_available=false" in report


def test_invalid_trials_are_audited() -> None:
    invalid = pd.read_csv(OUT / "invalid_trial_audit.csv")
    assert {"strategy_id", "portfolio_size", "execution_variant", "horizon", "invalid_reason", "invalid_trial_count"}.issubset(invalid.columns)


def test_e_r1_remains_diagnostic_only() -> None:
    s = pd.read_csv(OUT / "execution_overlay_summary.csv").iloc[0]
    assert bool(s["E_R1_diagnostic_only_unresolved_invalid_replay_lineage"]) is True


def test_baseline_execution_reproduces_hold_only_internal_baseline() -> None:
    m = pd.read_csv(OUT / "strategy_by_execution_variant_metrics.csv")
    base = m[m["execution_variant"].eq("EXEC_BASELINE")]
    assert not base.empty
    assert base["win_rate_vs_hold_only"].dropna().isin([False, 0.0]).all()


def test_required_variants_and_buckets_present() -> None:
    m = pd.read_csv(OUT / "strategy_by_execution_variant_metrics.csv")
    assert {"Top20", "Top50"}.issubset(set(m["portfolio_size"]))
    expected = {
        "EXEC_BASELINE",
        "EXEC_PULLBACK_SAFE",
        "EXEC_BREAKOUT_CONFIRM",
        "EXEC_REVERSAL_EARLY",
        "EXEC_OVERHEAT_SKIP",
        "EXEC_COMBINED_R1",
    }
    assert expected.issubset(set(m["execution_variant"]))
