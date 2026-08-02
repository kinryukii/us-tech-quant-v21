import pandas as pd
import pytest

from generation3r2_research import action_frame, candidate_contract, feature_contract, fixed_contract, label_contract, nonoverlap, sha256_json


def common_dates(end="2026-07-28"):
    return pd.date_range("2023-03-01", end, freq="B", tz="America/New_York")


def test_frozen_contract_uses_authorized_dates_and_confirmation_minimum():
    c = fixed_contract(common_dates(), pd.Timestamp("2026-07-28 11:16", tz="America/New_York"))
    assert str(c["development_start"]).startswith("2023-03-01")
    assert str(c["validation_start"]).startswith("2026-04-01")
    assert c["confirmation_minimum_independent_trading_days"] == 15
    assert c["confirmation_read_count"] == 0
    assert c["broker_action_allowed"] is False


def test_contract_rejects_inadequate_confirmation_metadata():
    dates = common_dates("2026-06-30")
    with pytest.raises(RuntimeError, match="INADEQUATE_CONFIRMATION"):
        fixed_contract(dates, pd.Timestamp("2026-06-30", tz="America/New_York"))


def test_candidate_set_is_exactly_six_and_deterministic():
    candidates = candidate_contract()
    assert len(candidates) == 6
    assert [x["candidate_id"] for x in candidates] == [f"C{i}_" + x["candidate_id"].split("_", 1)[1] for i, x in enumerate(candidates, 1)]
    assert sha256_json(candidates) == sha256_json(candidate_contract())


def test_action_requires_probability_expected_return_and_risk_gate():
    rows = pd.DataFrame({"decision_timestamp": pd.date_range("2025-01-02", periods=2, freq="5min", tz="America/New_York"), "calendar_date": pd.date_range("2025-01-02", periods=2, freq="5min", tz="America/New_York").normalize(), "soxl_gross_60m": [.01, .01], "soxs_gross_60m": [.01, .01], **{f"{s}_gross_60m_delay{d}": [.01, .01] for s in ("soxl", "soxs") for d in (0, 1, 3, 5)}})
    result = action_frame(rows, [0.9, 0.1], [0.9, 0.5], .5)
    assert result.action.tolist() == ["LONG", "FLAT"]
    assert {"expected_net_return_long", "expected_MFE", "expected_MAE", "uncertainty", "cost_and_delay_buffer"}.issubset(result)


def test_nonoverlap_rejects_overlapping_positions():
    frame = pd.DataFrame({"decision_timestamp": pd.to_datetime(["2025-01-02 10:00", "2025-01-02 10:05", "2025-01-02 11:00"]).tz_localize("America/New_York"), "action": ["LONG"]*3, "net_10bps_delay0": [.01]*3})
    assert len(nonoverlap(frame)) == 2


def test_feature_and_label_contracts_enforce_pit_and_three_layers():
    features, labels = feature_contract(), label_contract()
    assert all(x["maximum_source_timestamp"] == "decision_timestamp - 1 minute" for x in features["features"])
    assert labels["horizons_minutes"] == [30, 60, 120]
    assert "LONG=SOXL" in labels["execution"] and "FLAT" in labels["execution"]
