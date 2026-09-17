from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


SOURCE = Path(__file__).with_name("a2_earnings_fundamental_change_alpha_r1.py")


def module(name: str = "fundamental_r1_test"):
    spec = importlib.util.spec_from_file_location(name, SOURCE)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_filing_unavailable_before_next_full_session() -> None:
    m = module()
    sessions = pd.bdate_range("2025-01-02", "2025-01-10")
    accepted = pd.Timestamp("2025-01-03 21:30:00", tz="UTC")
    assert m.next_full_session(accepted, sessions) == pd.Timestamp("2025-01-06")
    facts = pd.DataFrame([{
        "cik": 1, "fiscal_period": "2024Q4", "tag": "Revenues", "accession": "A",
        "effective_date": pd.Timestamp("2025-01-06"), "value": 10.0,
    }])
    assert m.effective_facts(facts, pd.Timestamp("2025-01-03")).empty
    assert len(m.effective_facts(facts, pd.Timestamp("2025-01-06"))) == 1


def test_amendment_does_not_rewrite_earlier_pit_history() -> None:
    m = module("fundamental_restatement_test")
    facts = pd.DataFrame([
        {"cik": 1, "fiscal_period": "2024Q3", "tag": "Revenues", "accession": "ORIGINAL", "effective_date": "2024-11-05", "value": 100.0},
        {"cik": 1, "fiscal_period": "2024Q3", "tag": "Revenues", "accession": "AMENDMENT", "effective_date": "2025-02-03", "value": 90.0},
    ])
    before = m.effective_facts(facts, pd.Timestamp("2024-12-31"))
    after = m.effective_facts(facts, pd.Timestamp("2025-02-03"))
    assert before.iloc[0].accession == "ORIGINAL" and before.iloc[0].value == 100.0
    assert after.iloc[0].accession == "AMENDMENT" and after.iloc[0].value == 90.0


def test_q2_q3_ytd_to_quarter_conversion_and_invalid_reconciliation() -> None:
    m = module("fundamental_ytd_test")
    prior = {"value": 100.0, "start": "2024-01-01", "end": "2024-03-31", "unit": "USD", "fiscal_year": 2024}
    q2_ytd = {"value": 230.0, "start": "2024-01-01", "end": "2024-06-30", "unit": "USD", "fiscal_year": 2024}
    q3_ytd = {"value": 390.0, "start": "2024-01-01", "end": "2024-09-30", "unit": "USD", "fiscal_year": 2024}
    assert m.duration_to_quarter(q2_ytd, prior) == 130.0
    assert m.duration_to_quarter(q3_ytd, q2_ytd) == 160.0
    assert m.duration_to_quarter({**q2_ytd, "unit": "EUR"}, prior) is None


def test_q4_annual_minus_three_quarters_only_when_valid() -> None:
    m = module("fundamental_q4_test")
    annual = {"value": 1000.0, "unit": "USD", "fiscal_year": 2024}
    quarters = [{"value": value, "unit": "USD", "fiscal_year": 2024} for value in (200.0, 230.0, 260.0)]
    assert m.annual_to_q4(annual, quarters) == 310.0
    assert m.annual_to_q4(annual, quarters[:2]) is None
    assert m.annual_to_q4(annual, [{**quarter, "fiscal_year": 2023} for quarter in quarters]) is None


def test_deterministic_xbrl_tag_precedence() -> None:
    m = module("fundamental_tag_test")
    available = {"SalesRevenueNet", "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"}
    assert m.fixed_tag_choice(available, "revenue") == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert m.fixed_tag_choice({"ProfitLoss", "NetIncomeLoss"}, "net_income") == "NetIncomeLoss"
    assert m.fixed_tag_choice(set(), "revenue") is None


def test_component_formulas_and_directions_are_fixed() -> None:
    m = module("fundamental_component_test")
    history = pd.DataFrame({
        "fiscal_quarter": range(6),
        "revenue": [100, 110, 120, 130, 132, 150],
        "operating_income": [10, 11, 12, 13, 15, 24],
        "net_income": [5, 6, 7, 8, 10, 15],
        "cfo": [12, 13, 14, 15, 18, 25],
        "capex": [2, 2, 3, 3, 3, 4],
    })
    values = m.compute_component_values(history)
    assert all(values[name] > 0 for name in m.COMPONENTS)
    assert set(m.COMPONENT_DIRECTION.values()) == {1}


def test_near_zero_revenue_guard_is_deterministic() -> None:
    m = module("fundamental_denominator_test")
    history = pd.DataFrame({
        "fiscal_quarter": range(6), "revenue": [0, 1, 1, 1, 1, 2],
        "operating_income": 1.0, "net_income": 1.0, "cfo": 1.0, "capex": 0.0,
    })
    values = m.compute_component_values(history)
    assert values["REVENUE_GROWTH_ACCELERATION"] is None


def test_missing_component_numerator_is_unavailable_not_imputed() -> None:
    m = module("fundamental_missing_numerator_test")
    history = pd.DataFrame({
        "fiscal_quarter": range(6), "revenue": [100, 110, 120, 130, 132, 150],
        "operating_income": [10, None, 12, 13, 15, None],
        "net_income": [5, 6, 7, 8, 10, 15], "cfo": [12, 13, 14, 15, 18, 25],
        "capex": [2, 2, 3, 3, 3, 4],
    })
    values = m.compute_component_values(history)
    assert values["OPERATING_MARGIN_CHANGE"] is None
    assert values["NET_MARGIN_CHANGE"] is not None


def test_missing_values_receive_neutral_rank() -> None:
    m = module("fundamental_neutral_test")
    values = pd.Series([1.0, np.nan, 3.0], index=["A", "B", "C"])
    ranks = m.neutral_percentile(values)
    assert ranks["B"] == 0.50
    assert ranks["A"] == 0.50
    assert ranks["C"] == 1.00


def test_equal_component_weights() -> None:
    m = module("fundamental_equal_weight_test")
    frame = pd.DataFrame({"a": [0.2, 0.8], "b": [0.6, 0.4]})
    np.testing.assert_allclose(m.equal_weight_composite(frame, ["a", "b"]), [0.4, 0.6])


def test_fixed_score_blend_80_20() -> None:
    m = module("fundamental_score_blend_test")
    a2 = pd.Series([0.1, 0.9])
    fundamental = pd.Series([0.9, 0.1])
    np.testing.assert_allclose(m.fixed_score_blend(a2, fundamental), [0.26, 0.74])


def test_fixed_sleeve_80_20_and_target_level_netting() -> None:
    m = module("fundamental_sleeve_test")
    date = pd.Timestamp("2025-01-02")
    a2 = {date: {"OVERLAP": 0.05, **{f"A{i}": 0.05 for i in range(19)}}}
    fundamental = {date: {"OVERLAP": 0.05, **{f"F{i}": 0.05 for i in range(19)}}}
    combined = m.combine_sleeve_targets(a2, fundamental)
    assert combined[date]["OVERLAP"] == pytest.approx(0.05)
    assert combined[date]["A0"] == pytest.approx(0.04)
    assert combined[date]["F0"] == pytest.approx(0.01)
    assert sum(combined[date].values()) == pytest.approx(1.0)


def test_2026_outcome_is_rejected() -> None:
    m = module("fundamental_boundary_test")
    m.validate_outcome_boundary(pd.DataFrame({"target_end_date": [pd.Timestamp("2025-12-31")]}))
    with pytest.raises(m.FundamentalContractError, match="POST2025_OUTCOME_USED"):
        m.validate_outcome_boundary(pd.DataFrame({"target_end_date": [pd.Timestamp("2026-01-02")]}))


def test_raw_a2_feature_inventory_has_exactly_32_nonfundamental_inputs() -> None:
    m = module("fundamental_feature_inventory_test")
    a2 = m.import_file("a2_features_for_test", m.A2_SOURCE)
    inventory = m.feature_inventory(a2.FEATURE_COLUMNS)
    assert len(inventory) == 32
    assert set(inventory.category) <= {"price / momentum", "volatility", "liquidity", "technical", "other"}
    assert inventory.category.value_counts().to_dict() == {"technical": 13, "price / momentum": 8, "volatility": 6, "liquidity": 5}
    assert not inventory[["fundamental_level", "fundamental_change", "earnings_event", "analyst_revision"]].any().any()


def test_saved_raw_a2_control_is_exact_pre2026() -> None:
    m = module("fundamental_control_test")
    ledger = json.loads((m.RESULTS / "A2_13F_INSTITUTIONAL_CHANGE_ALPHA_R1" / "trial_ledger.json").read_text(encoding="utf-8"))
    assert ledger["control_reconciliation"]["status"] == "PASS_EXACT_OR_MACHINE_PRECISION"
    assert ledger["post_2025_outcome_used"] is False


def test_deterministic_outputs_for_same_inputs() -> None:
    m = module("fundamental_determinism_test")
    frame = pd.DataFrame({"a": [0.2, np.nan, 0.8], "b": [0.4, 0.5, 0.6]})
    first = m.equal_weight_composite(pd.DataFrame({"a": m.neutral_percentile(frame.a), "b": m.neutral_percentile(frame.b)}), ["a", "b"])
    second = m.equal_weight_composite(pd.DataFrame({"a": m.neutral_percentile(frame.a), "b": m.neutral_percentile(frame.b)}), ["a", "b"])
    pd.testing.assert_series_equal(first, second)


def test_fsds_cache_validation_uses_manifest_and_zip_members() -> None:
    m = module("fundamental_fsds_cache_test")
    valid, audit = m.validate_fsds_cache()
    assert len(valid) == 20
    assert audit["fsds_quarters_cache_hit"] == 20
    assert audit["fsds_quarters_downloaded_this_run"] == 0
    assert audit["network_used"] is False


def test_fsds_num_filters_by_adsh_tag_unit_and_consolidated_scope() -> None:
    m = module("fundamental_fsds_filter_test")
    rows = [
        ["A", "Revenues", "us-gaap/2025", "20250930", "1", "USD", "", "", "100"],
        ["A", "Revenues", "us-gaap/2025", "20250930", "1", "EUR", "", "", "90"],
        ["A", "OperatingIncomeLoss", "us-gaap/2025", "20250930", "1", "USD", "segment=x", "", "10"],
        ["B", "Revenues", "us-gaap/2025", "20250930", "1", "USD", "", "", "999"],
    ]
    chunk = pd.DataFrame(rows, columns=m.NUM_REQUIRED_COLUMNS)
    filtered, audit = m.filter_num_chunk(chunk, {"A"})
    assert len(filtered) == 1
    assert filtered.iloc[0].adsh == "A" and filtered.iloc[0].value == 100.0
    assert audit["unit_conflict_rows"] == 1
    assert audit["segmented_or_coreg_rows"] == 1


def test_materialized_quarter_facts_use_next_session_and_fixed_components() -> None:
    m = module("fundamental_materialize_test")
    periods = [
        (2023, "Q3", "20230930"), (2023, "FY", "20231231"),
        (2024, "Q1", "20240331"), (2024, "Q2", "20240630"),
        (2024, "Q3", "20240930"), (2024, "FY", "20241231"),
    ]
    values = {
        "revenue": [100, 110, 120, 130, 132, 150],
        "operating_income": [10, 11, 12, 13, 15, 24],
        "net_income": [5, 6, 7, 8, 10, 15],
        "cfo": [12, 13, 14, 15, 18, 25],
        "capex": [2, 2, 3, 3, 3, 4],
    }
    rows = []
    accepted = pd.date_range("2023-11-01", periods=len(periods), freq="60D", tz="UTC")
    for position, ((fy, fp, period), timestamp) in enumerate(zip(periods, accepted)):
        for semantic, tag_names in m.TAG_PRECEDENCE.items():
            rows.append({
                "adsh": f"A{position}", "tag": tag_names[0], "version": "us-gaap/2024",
                "ddate": pd.Timestamp(period), "qtrs": 1, "uom": "USD", "segments": "", "coreg": "",
                "value": values[semantic][position], "cik": 1, "form": "10-Q" if fp != "FY" else "10-K",
                "period": period, "fy": fy, "fp": fp, "filed": int(timestamp.strftime("%Y%m%d")),
                "accepted_timestamp_utc": timestamp, "quarter": "fixture",
            })
    sessions = pd.bdate_range("2023-01-01", "2025-12-31")
    quarterly, snapshots, audit = m.materialize_quarterly_facts(pd.DataFrame(rows), sessions)
    assert len(quarterly) == 6 and audit["quarter_fact_securities"] == 1
    accepted_local_dates = quarterly.accepted_timestamp_utc.dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
    assert (quarterly.effective_date > accepted_local_dates).all()
    final = snapshots.iloc[-1]
    assert all(final[name] > 0 for name in m.COMPONENTS)


def test_authoritative_cik_bridge_applies_by_verified_ticker_not_top20_proof_window() -> None:
    m = module("fundamental_cik_bridge_test")
    panel = pd.DataFrame({"signal_date": pd.to_datetime(["2023-01-03", "2025-12-31"]), "ticker": ["AAA", "AAA"]})
    bridge = pd.DataFrame({
        "ticker": ["AAA"], "cik": [123],
        "cik_effective_start": [pd.Timestamp("2024-01-01")],
        "cik_effective_end": [pd.Timestamp("2024-12-31")],
    })
    attached = m.attach_cik_identity(panel, bridge)
    assert attached.cik.astype(int).tolist() == [123, 123]


def test_raw_a2_signal_diagnostics_do_not_duplicate_rank_column() -> None:
    m = module("fundamental_raw_diagnostic_test")
    frame = pd.DataFrame({
        "signal_date": [pd.Timestamp("2025-01-02")] * 20,
        "ticker": [f"T{i:02d}" for i in range(20)],
        "a2_rank_pct": np.linspace(0.05, 1.0, 20),
        "target": np.linspace(-0.02, 0.03, 20),
    })
    result = m._diagnostics(frame, "a2_rank_pct")
    assert result["date_count"] == 1
    assert np.isfinite(result["spearman_ic"])
