"""Synthetic proofs for audited V22.080B label/execution contract facts."""
import importlib.util
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "scripts" / "v22" / "v22_080b_fast3_one_percent_move_predictability_preflight_r1.py"
SPEC = importlib.util.spec_from_file_location("fast3_080b", SOURCE)
m = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(m)


def test_one_percent_underlying_label_is_not_the_three_percent_etf_economic_target():
    """A correct 1% first-passage label can still fail the distinct ETF target."""
    t0 = pd.Timestamp("2024-01-02 14:30:00", tz="UTC")
    selected = pd.DataFrame([{
        "execution_etf": "SOXL", "entry_timestamp_utc": t0,
        "horizon_timestamp_utc": t0 + pd.Timedelta(minutes=2), "year": 2024,
        "session_code": 2,
    }])
    etf = pd.DataFrame({
        "timestamp_utc": pd.Series([t0.value, t0.value + 60_000_000_000, t0.value + 120_000_000_000], dtype="datetime64[ns, UTC]"),
        "open": [100.0, 100.0, 100.0], "high": [102.0, 102.0, 102.0],
        "low": [99.0, 99.0, 99.0], "close": [100.0, 100.0, 100.0], "valid": [True, True, True],
    })
    result = m.etf_outcomes(selected, {"SOXL": etf}).iloc[0]
    assert not bool(result.etf_target_hit)
    assert result.gross_return == 0.0
    assert result.net_return_10bps == -0.001


def test_selected_candidates_are_evaluated_independently_without_a_position_overlap_gate():
    t0 = pd.Timestamp("2024-01-02 14:30:00", tz="UTC")
    selected = pd.DataFrame([{
        "execution_etf": "SOXL", "entry_timestamp_utc": t0,
        "horizon_timestamp_utc": t0 + pd.Timedelta(minutes=2), "year": 2024, "session_code": 2,
    }, {
        "execution_etf": "SOXL", "entry_timestamp_utc": t0 + pd.Timedelta(minutes=1),
        "horizon_timestamp_utc": t0 + pd.Timedelta(minutes=2), "year": 2024, "session_code": 2,
    }])
    etf = pd.DataFrame({
        "timestamp_utc": pd.Series([t0.value, t0.value + 60_000_000_000, t0.value + 120_000_000_000], dtype="datetime64[ns, UTC]"),
        "open": [100.0, 100.0, 100.0], "high": [100.0, 100.0, 100.0],
        "low": [100.0, 100.0, 100.0], "close": [100.0, 100.0, 100.0], "valid": [True, True, True],
    })
    assert len(m.etf_outcomes(selected, {"SOXL": etf})) == 2


def test_same_bar_dual_underlying_barrier_is_detectable_not_ordered_favourably():
    highs, size = m.build_tree(pd.Series([100.0, 101.0]).to_numpy(), True)
    lows, _ = m.build_tree(pd.Series([100.0, 99.0]).to_numpy(), False)
    assert m.first_cross(highs, size, 1, 1, 101.0, True) == 1
    assert m.first_cross(lows, size, 1, 1, 99.0, False) == 1


def test_v22_080b_canonical_root_is_read_only_by_source_contract():
    source = SOURCE.read_text(encoding="utf-8")
    assert "pd.read_parquet" in source
    assert "to_parquet" not in source
    assert "to_csv" not in source[source.index("CANONICAL="):source.index("def write_json")]
