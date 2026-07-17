from __future__ import annotations

import importlib.util
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

UTC = timezone.utc
MODULE_PATH = (
    Path(__file__).resolve().parent
    / "v22_037_r2f_direction_aware_liquid_option_contract_ranking_and_no_trade_gate_research_only.py"
)


def load_module():
    name = "v22_037_r2f_r1c_under_test"
    spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def set_mtime(path: Path, dt: datetime) -> None:
    ts = dt.timestamp()
    os.utime(path, (ts, ts))


def panel_row(underlying: str = "QQQ") -> dict[str, str]:
    return {
        "underlying": underlying,
        "option_type": "PUT",
        "contract_code": f"US.{underlying}P",
        "expiry_timestamp_et": "2026-07-17T16:00:00-04:00",
        "valuation_timestamp_et": "2026-07-10T10:00:00-04:00",
        "dte_bucket": "1_7DTE",
        "strike": "500",
        "underlying_price": "505",
        "bid": "1.00",
        "ask": "1.05",
        "option_market_price": "1.025",
        "spread_ratio_mid": "0.0487804878",
        "quote_alignment_seconds": "1",
        "volume": "1000",
        "open_interest": "5000",
        "synthetic_iv": "0.25",
        "delta": "-0.45",
        "gamma": "0.05",
        "theta_per_day": "-0.50",
        "vega_per_1vol_point": "0.10",
        "liquidity_score": "90",
    }


def build(tmp_path: Path, explicit_scope: str | None):
    r2f = load_module()
    now = datetime(2026, 7, 10, 14, 5, tzinfo=UTC)
    direction_path = tmp_path / "v22_042_r2_summary.json"
    direction_path.write_text("{}", encoding="utf-8")
    set_mtime(direction_path, datetime(2026, 7, 10, 14, 0, tzinfo=UTC))

    mode = {
        "gate_mode": "relaxed_broad_shadow_gate",
        "direction_label": "BEAR_SEMICONDUCTOR",
        "wait_state": False,
        "reason_code": "SHADOW_RELAXED_BROAD_DIRECTION_AVAILABLE",
        "official_gate": False,
        "shadow_only": True,
    }
    if explicit_scope is not None:
        mode["direction_scope"] = explicit_scope

    return r2f.build_outputs(
        [panel_row()],
        {"underlyings": "QQQ"},
        {},
        [mode],
        direction_path,
        now,
        r2f.Config(max_panel_age_minutes=10),
    )


def test_explicit_scope_source_is_written_to_no_trade_row(tmp_path):
    _, _, no_trade, _, _ = build(tmp_path, "BROAD")
    assert len(no_trade) == 1
    assert no_trade[0]["direction_scope"] == "BROAD"
    assert no_trade[0]["direction_scope_source"] == (
        "EXPLICIT_DIRECTION_MODE_INPUT"
    )


def test_fallback_scope_source_is_written_to_no_trade_row(tmp_path):
    _, _, no_trade, _, _ = build(tmp_path, None)
    assert len(no_trade) == 1
    assert no_trade[0]["direction_scope"] == "SEMICONDUCTOR"
    assert no_trade[0]["direction_scope_source"] == (
        "INFERRED_FROM_DIRECTION_LABEL"
    )


def test_no_trade_schema_contains_scope_source():
    r2f = load_module()
    assert "direction_scope_source" in r2f.NO_TRADE_FIELDS


def test_r1c_does_not_change_authorization_or_scope_policy():
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert '"official_adoption_allowed": False' in source
    assert '"broker_action_allowed": False' in source
    assert 'SEMICONDUCTOR_UNDERLYINGS = {"SOXX", "SMH", "SOXL", "SOXS"}' in source
