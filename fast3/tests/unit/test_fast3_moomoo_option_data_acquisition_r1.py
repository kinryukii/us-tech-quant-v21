from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


PATH=Path(r"D:\us-tech-quant\fast3\src\fast3\options\moomoo_option_shadow_r1.py")
spec=importlib.util.spec_from_file_location("moomoo_shadow_helpers_test",PATH); assert spec and spec.loader
m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m)


def test_canonical_alignment_monotonicity_and_changes() -> None:
    now=datetime(2026,8,11,14,59,tzinfo=timezone.utc); assert m.canonical_slot(now).minute==55
    history=[{"iv":.20+i*.01} for i in range(4)]
    assert m.derive_changes(history,"iv")=={"5m":pytest.approx(.01),"10m":pytest.approx(.02),"15m":pytest.approx(.03)}


def test_stale_future_and_missing_fields_are_fail_safe() -> None:
    now=datetime(2026,8,11,14,0,tzinfo=timezone.utc)
    assert m.quote_is_stale(now+timedelta(seconds=1),now,900)
    assert m.quote_is_stale(None,now,900)
    surface=m.materialize_surface([{"role":"mid_atm_call","implied_volatility":.2},{"role":"mid_atm_put","implied_volatility":None},{"role":"mid_delta_filtered_put","implied_volatility":.3,"delta":None}])
    assert surface["option_downside_skew_30d"] is None
    assert surface["option_iv_term_slope"] is None


def test_no_fast3_mutation_or_position_application() -> None:
    now=datetime.now(timezone.utc)
    valid={"snapshot_timestamp_utc":now,"retrieved_at_utc":now,"position_multiplier_applied":False,"fast3_signal_changed":False,"direction_reversal_allowed":False}
    m.validate_snapshot(valid)
    with pytest.raises(ValueError): m.validate_snapshot(valid | {"position_multiplier_applied":True})
    runner=Path(r"D:\us-tech-quant\fast3\scripts\audit\run_fast3_moomoo_option_data_acquisition_r1.py").read_text(encoding="utf-8")
    assert "OpenSecTradeContext" not in runner and "unlock_trade" not in runner and ".fit(" not in runner
