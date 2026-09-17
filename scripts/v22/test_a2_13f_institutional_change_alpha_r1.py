from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


SOURCE = Path(__file__).with_name("a2_13f_institutional_change_alpha_r1.py")
SPEC = importlib.util.spec_from_file_location("a2_13f_change_under_test", SOURCE)
assert SPEC is not None and SPEC.loader is not None
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def selected_fixture() -> pd.DataFrame:
    rows = []
    values = {
        "2024Q1": {"m1": {"A": 90.0, "B": 10.0}, "m2": {"A": 10.0, "C": 90.0}},
        "2024Q2": {"m1": {"A": 50.0, "D": 50.0}, "m2": {"A": 20.0, "C": 80.0}},
        "2024Q3": {"m1": {"A": 70.0, "D": 30.0}, "m2": {"A": 40.0, "E": 60.0}},
    }
    for quarter, managers in values.items():
        for manager, securities in managers.items():
            for cusip, value in securities.items():
                rows.append({
                    "quarter": quarter, "manager_id": manager, "cusip": cusip,
                    "reported_value_usd": value,
                })
    return pd.DataFrame(rows)


def ranking_fixture() -> pd.DataFrame:
    rows = []
    for index in range(25):
        rows.append({
            "signal_date": pd.Timestamp("2025-06-02"),
            "ticker": f"T{index:02d}",
            "a2_rank": index + 1,
            "holder_breadth_change": index / 100.0,
            "top100_entry_exit_balance": index / 100.0,
            "consensus_top100_position_weight_change": index / 1000.0,
            "accumulation_persistence": index / 100.0,
        })
    return pd.DataFrame(rows)


def test_information_is_unavailable_before_canonical_effective_date() -> None:
    tickers = [f"T{index:02d}" for index in range(21)]
    oof = pd.DataFrame({
        "signal_date": pd.Timestamp("2025-05-14"), "ticker": tickers,
        "a2_rank": np.arange(1, 22), "target": 0.01, "split": "FINAL",
    })
    eligible = pd.DataFrame({
        "signal_date": pd.Timestamp("2025-05-14"), "ticker": tickers,
        "active_13f_quarter": "2025Q1", "cusip": tickers,
    })
    active = pd.DataFrame({
        "signal_date": [pd.Timestamp("2025-05-14")],
        "active_13f_quarter": ["2025Q1"],
        "quarter_effective_date": [pd.Timestamp("2025-05-15")],
    })
    targets = pd.DataFrame({
        "signal_date": pd.Timestamp("2025-05-14"), "ticker": tickers,
        "target": 0.01, "target_end_date": pd.Timestamp("2025-06-13"),
    })
    changes = pd.DataFrame({
        "quarter": "2025Q1", "cusip": tickers,
        **{column: 0.1 for column in MOD.COMPONENT_COLUMNS},
    })
    with pytest.raises(MOD.ResearchContractError, match="PREMATURE_13F_INFORMATION"):
        MOD.attach_change_panel(
            {"oof": oof, "eligible": eligible, "active": active, "targets": targets}, changes
        )


def test_quarter_transition_uses_current_and_immediately_prior_vintage() -> None:
    got = MOD.build_quarter_change_features(
        selected_fixture(), ["2024Q1", "2024Q2", "2024Q3"], ["m1", "m2"]
    )
    q2_a = got.loc[got.quarter.eq("2024Q2") & got.cusip.eq("A")].iloc[0]
    # Equal-manager normalized A weight: Q1=(.9+.1)/2=.5, Q2=(.5+.2)/2=.35.
    assert q2_a.consensus_top100_position_weight_change == pytest.approx(-0.15)
    assert q2_a.holder_breadth_change == pytest.approx(0.0)
    assert q2_a.top100_entry_exit_balance == pytest.approx(0.0)
    q3_a = got.loc[got.quarter.eq("2024Q3") & got.cusip.eq("A")].iloc[0]
    assert np.isfinite(q3_a.accumulation_persistence)


def test_post_2025_realized_outcome_is_rejected() -> None:
    bad = pd.DataFrame({
        "target": [0.1], "target_end_date": [pd.Timestamp("2026-01-02")]
    })
    with pytest.raises(MOD.ResearchContractError, match="POST2025_OUTCOME_USED"):
        MOD.validate_outcome_boundary(bad)


def test_authoritative_stable_24_manager_set_is_used() -> None:
    selected = pd.read_parquet(MOD.SELECTED_PATH, columns=["quarter", "manager_id"])
    manifest = pd.read_csv(MOD.MANAGER_MANIFEST_PATH)
    managers = manifest.normalized_manager_id.astype(str).unique()
    assert len(managers) == 24
    got = MOD.validate_manager_contract(selected, managers, ["2023Q1", "2024Q1", "2025Q1"])
    assert len(got) == 24


def test_top100_semantics_are_explicit_and_not_true_buys_or_sells() -> None:
    assert MOD.COMPONENT_LABELS["top100_entry_exit_balance"] == "TOP100_ENTRY_EXIT_BALANCE"
    assert "true" not in MOD.COMPONENT_LABELS["top100_entry_exit_balance"].lower()


def test_equal_manager_weighting_and_no_manager_quality_weight_input() -> None:
    selected = selected_fixture()
    assert "manager_quality_weight" not in selected.columns
    got = MOD.build_quarter_change_features(selected, ["2024Q1", "2024Q2"], ["m1", "m2"])
    q2_d = got.loc[got.quarter.eq("2024Q2") & got.cusip.eq("D")].iloc[0]
    # D is 50% of m1's eligible Top100 and absent for m2: equal-manager consensus +25%.
    assert q2_d.consensus_top100_position_weight_change == pytest.approx(0.25)
    assert q2_d.top100_entry_exit_balance == pytest.approx(0.5)


def test_fixed_80_20_blend_and_top20_contract() -> None:
    got = MOD.add_cross_sectional_scores(ranking_fixture())
    expected = 0.8 * got.a2_rank_pct + 0.2 * got.institutional_change_rank_pct
    assert np.allclose(got.fixed_blend_score, expected, atol=0.0, rtol=0.0)
    for rank_column in MOD.STRATEGY_RANKS.values():
        assert int(got[rank_column].le(20).sum()) == 20
        mapping = MOD.target_map(got, rank_column)
        target = next(iter(mapping.values()))
        assert len(target) == 20
        assert sum(target.values()) == pytest.approx(1.0)


def test_ranking_is_deterministic_and_changes_only_top20_membership() -> None:
    first = MOD.add_cross_sectional_scores(ranking_fixture())
    second = MOD.add_cross_sectional_scores(ranking_fixture().sample(frac=1.0, random_state=7))
    columns = ["signal_date", "ticker", "institutional_rank", "fixed_blend_rank", "fixed_blend_score"]
    pd.testing.assert_frame_equal(first[columns], second[columns], check_exact=True)
    assert set(first.columns).issuperset({"a2_rank", "institutional_rank", "fixed_blend_rank"})


def test_quarter_feature_output_is_deterministic() -> None:
    source = selected_fixture()
    first = MOD.build_quarter_change_features(source, ["2024Q1", "2024Q2", "2024Q3"], ["m1", "m2"])
    second = MOD.build_quarter_change_features(
        source.sample(frac=1.0, random_state=11), ["2024Q1", "2024Q2", "2024Q3"], ["m2", "m1"]
    )
    pd.testing.assert_frame_equal(first, second, check_exact=True)


def test_raw_a2_diagnostic_does_not_duplicate_its_own_column() -> None:
    rows = []
    for date in (pd.Timestamp("2025-01-02"), pd.Timestamp("2025-01-03")):
        for index in range(25):
            rows.append({
                "signal_date": date, "ticker": f"T{index:02d}",
                "a2_rank_pct": (25 - index) / 25.0, "target": index / 100.0,
            })
    got = MOD.cross_sectional_diagnostics(pd.DataFrame(rows), "a2_rank_pct")
    assert got["date_count"] == 2
    assert np.isfinite(got["mean_spearman_ic"])


def test_markdown_report_formatter_has_no_optional_dependency() -> None:
    rendered = MOD.markdown_table(pd.DataFrame([{"strategy": "C0", "sharpe": 1.25}]))
    assert "| strategy | sharpe |" in rendered
    assert "| C0 | 1.250000 |" in rendered
