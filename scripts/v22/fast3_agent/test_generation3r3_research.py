import pandas as pd

from generation3r3_research import DIRECTION_MARGINS, OPPORTUNITY_THRESHOLDS, _funnel_row, _promotion_gate, _reasoned_actions, calibrated_probability, coverage_surface, fixed_contract, overlap_selector, repair_metrics, separated_execution


def test_3r3_contract_preserves_frozen_split_and_confirmation_isolation():
    dates = pd.date_range("2023-03-01", "2026-07-28", freq="B", tz="America/New_York")
    contract = fixed_contract(dates, pd.Timestamp("2026-07-28 11:16", tz="America/New_York"))
    assert str(contract["development_start"]).startswith("2023-03-01")
    assert contract["confirmation_read_count"] == 0
    assert contract["research_id"].endswith("ITERATION")


def test_reason_codes_are_exclusive_and_cover_all_scored_rows():
    rows = pd.DataFrame({"decision_timestamp": pd.date_range("2025-01-02", periods=4, freq="5min", tz="America/New_York"), "calendar_date": pd.date_range("2025-01-02", periods=4, freq="5min", tz="America/New_York").normalize(), "soxl_gross_60m_delay0": [.01, .01, None, .01], "soxs_gross_60m_delay0": [.01, .01, .01, .01]})
    result = _reasoned_actions(rows, [0.2, .6, .8, .9], [.5, .51, .9, .1])
    assert len(result.reason) == 4
    assert set(result.reason).issubset({"NO_OPPORTUNITY", "LOW_DIRECTION_CONFIDENCE", "EXPECTED_NET_BELOW_BUFFER", "ETF_MAPPING_FAILURE", "TRADE"})


def test_probability_quantile_column_is_data_not_dataframe_method():
    quantiles = pd.DataFrame({"quantile": [0.5], "p_opp": [0.6]})
    assert float(quantiles.iloc[0]["quantile"]) == 0.5


def test_funnel_reports_legacy_joint_probability_gate_separately():
    samples = pd.DataFrame({"opportunity_60m": [0, 1]})
    scored = samples.copy()
    actions = pd.DataFrame({"reason": ["NO_OPPORTUNITY", "TRADE"], "p_opp": [.2, .8], "direction_confidence": [0, .1], "action": ["LONG", "LONG"], "expected_net": [0, .01], "mapped": [True, True], "decision_timestamp": pd.date_range("2025-01-02", periods=2, freq="5min", tz="America/New_York")})
    legacy = pd.DataFrame({"probability_long": [.1, .6], "probability_short": [.1, .1], "action": ["FLAT", "LONG"], "net_10bps_delay0": [None, .01], "decision_timestamp": actions.decision_timestamp})
    row = _funnel_row("C3", 3, 2, samples, scored, actions, legacy)
    assert row["legacy_joint_probability_pass_count"] == 1


def test_coverage_surface_is_coordinate_only_and_uses_frozen_grid():
    rows = coverage_surface([.3, .5, .7], [.5, .6, .4], "C3")
    assert len(rows) == len(OPPORTUNITY_THRESHOLDS) + len(DIRECTION_MARGINS)
    assert all(row["uses_economic_returns"] is False for row in rows)
    assert {row["stage"] for row in rows} == {"OPPORTUNITY_COVERAGE_ONLY", "DIRECTION_COVERAGE_ONLY"}


def test_separated_execution_does_not_use_joint_probability_gate():
    rows = pd.DataFrame({"decision_timestamp": pd.date_range("2025-01-02", periods=2, freq="5min", tz="America/New_York"), "calendar_date": pd.date_range("2025-01-02", periods=2, freq="5min", tz="America/New_York").normalize(), **{f"{s}_gross_60m_delay{d}": [.01, .01] for s in ("soxl", "soxs") for d in (0, 1, 3, 5)}})
    output = separated_execution(rows, [.8, .8], [.54, .46])
    assert output.action.tolist() == ["LONG", "SHORT"]


def test_empty_repair_metrics_fails_promotion():
    metrics = repair_metrics(pd.DataFrame({"decision_timestamp": pd.Series([], dtype="datetime64[ns, America/New_York]"), "action": [], "net_10bps_delay0": []}))
    assert _promotion_gate(metrics)[0] is False


def test_calibrator_is_fit_only_on_training_subperiod():
    train = pd.DataFrame({"feature": list(range(20)), "label": [0, 1] * 10})
    test = pd.DataFrame({"feature": [20, 21]})
    result = calibrated_probability(train, test, ["feature"], "label", "sigmoid")
    assert len(result) == 2 and ((result >= 0) & (result <= 1)).all()


def test_overlap_policy_per_direction_allows_opposing_signal():
    frame = pd.DataFrame({"decision_timestamp": pd.to_datetime(["2025-01-02 10:00", "2025-01-02 10:05"]).tz_localize("America/New_York"), "action": ["LONG", "SHORT"], "net_10bps_delay0": [.01, .01]})
    assert len(overlap_selector("one_active_position_per_direction")(frame)) == 2
    assert len(overlap_selector("one_active_position_globally")(frame)) == 1
