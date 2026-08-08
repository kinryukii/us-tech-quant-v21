import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


SOURCE = Path(__file__).parents[2] / "src" / "fast3" / "r28_multisignal.py"
SPEC = importlib.util.spec_from_file_location("r28_multisignal", SOURCE)
R28 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R28)


def bars(rows=240, start="2024-01-02 14:30:00+00:00"):
    timestamp = pd.date_range(start, periods=rows, freq="min", tz="UTC")
    close = 100.0 + np.linspace(0.0, 3.0, rows) + np.sin(np.arange(rows) / 3.0)
    return pd.DataFrame({"timestamp_utc": timestamp, "open": close - 0.02, "high": close + 0.2,
                         "low": close - 0.2, "close": close, "volume": 1000 + (np.arange(rows) % 17)})


def test_contract_has_fixed_baseline_and_eight_new_features():
    assert len(R28.BASELINE_FEATURES) == 10
    assert len(R28.R28_FEATURES) == 8
    assert set(R28.FEATURE_FAMILIES) == {"volatility_risk", "trend_structure", "flow", "cross_asset"}


def test_pit_audit_accepts_bar_close_lineage():
    out = R28.build_features(bars(), bars().assign(close=lambda x: x.close * 1.01))
    audit = R28.pit_audit(out.dropna(subset=list(R28.R28_FEATURES)))
    assert audit["pit_pass"] is True


def test_future_peer_bars_cannot_change_earlier_feature_values():
    primary, peer = bars(), bars().assign(close=lambda x: x.close * 1.01)
    anchor = 180
    before = R28.build_features(primary, peer).iloc[:anchor].copy()
    peer.loc[anchor:, "close"] = peer.loc[anchor:, "close"] * 10.0
    after = R28.build_features(primary, peer).iloc[:anchor]
    pd.testing.assert_frame_equal(before, after)


def test_duplicate_peer_timestamp_is_rejected_before_feature_generation():
    peer = pd.concat([bars(), bars().iloc[[100]]], ignore_index=True).sort_values("timestamp_utc", kind="mergesort")
    with pytest.raises(R28.R28ContractError, match="DUPLICATE_SOURCE_TIMESTAMP"):
        R28.build_features(bars(), peer)


def test_feature_engine_is_deterministic():
    first = R28.build_features(bars(), bars().assign(close=lambda x: x.close * 1.01))
    second = R28.build_features(bars(), bars().assign(close=lambda x: x.close * 1.01))
    pd.testing.assert_frame_equal(first, second)


def test_unsupported_external_factor_families_are_explicitly_blocked():
    assert {"vix_level_or_term_structure", "spy_relative_return", "external_flow_or_options_metrics"} == set(R28.BLOCKED_FACTORS)
