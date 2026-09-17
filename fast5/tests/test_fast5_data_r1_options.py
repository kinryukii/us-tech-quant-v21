from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fast5.options_data_r1 import (  # noqa: E402
    DataFirewallError, Firewall, FORBIDDEN_COLUMNS, build_snapshots, coverage_frame,
    feature_contract, load_candidates, normalize_daily_statistics, config,
)


def test_firewall_and_candidate_projection_are_outcome_blind() -> None:
    firewall = Firewall()
    with pytest.raises(DataFirewallError, match="TARGET_VALUE_READ_DETECTED"):
        firewall.assert_projection(["candidate_id", "y_primary"])
    candidates = load_candidates(firewall)
    assert len(candidates) == 1197
    assert not (set(x.lower() for x in candidates.columns) & FORBIDDEN_COLUMNS)
    assert firewall.target_value_read_count == 0


def test_baseline_reproduces_exactly_and_safe_projection_adds_one() -> None:
    candidates = load_candidates(Firewall()); normalized = normalize_daily_statistics(); cfg = config()
    baseline = coverage_frame(candidates, normalized, True, cfg["maximum_daily_staleness_calendar_days"])
    final = coverage_frame(candidates, normalized, False, cfg["maximum_daily_staleness_calendar_days"])
    assert int(baseline.covered.sum()) == 401
    assert float(baseline.covered.mean()) == pytest.approx(0.33500417710944025)
    assert int(final.covered.sum()) == 402
    added = set(final.loc[final.covered, "candidate_id"]) - set(baseline.loc[baseline.covered, "candidate_id"])
    assert added == {"SOXX|DOWN|2023-06-26 08:25:00+00:00"}


def test_normalized_and_snapshots_are_pit_deterministic() -> None:
    candidates = load_candidates(Firewall()); normalized = normalize_daily_statistics(); cfg = config()
    coverage = coverage_frame(candidates, normalized, False, cfg["maximum_daily_staleness_calendar_days"])
    first = build_snapshots(candidates, normalized, coverage); second = build_snapshots(candidates, normalized, coverage)
    pd.testing.assert_frame_equal(first, second)
    available = first.source_available_timestamp_utc.notna()
    assert (pd.to_datetime(first.loc[available, "source_available_timestamp_utc"], utc=True) <= first.loc[available, "decision_timestamp_utc"]).all()
    assert not first.current_option_surface_used.any()
    assert not any(x in first.columns for x in FORBIDDEN_COLUMNS)


def test_feature_contract_budget_and_unsafe_field_exclusions() -> None:
    contract = feature_contract(config())
    assert contract["contract_name"] == "FAST5_OPTION_FEATURE_CONTRACT_R1"
    assert contract["future_feature_count"] <= 60
    assert not contract["modeling_authorized"]
    excluded = contract["explicitly_excluded_raw_columns"]
    assert "open_interest" in excluded and "iv" in excluded and "delta_gamma_theta_vega_rho" in excluded
