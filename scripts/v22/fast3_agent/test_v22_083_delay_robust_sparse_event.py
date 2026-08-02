import json
from pathlib import Path

import pandas as pd

import v22_083_delay_robust_sparse_event as engine


def test_safety_and_caps_and_pit():
    c = engine.candidate(1, 0)
    assert c["model_type"] in engine.cfg()["model_families"]
    assert len(c["features"]) <= 25
    assert engine.SAFETY["broker_action_allowed"] is False
    assert engine.SAFETY["paper_trading_allowed"] is False
    assert engine.SAFETY["official_adoption_allowed"] is False
    assert engine.SAFETY["order_generation_allowed"] is False


def test_delay_cost_mapping_nonoverlap_and_risk():
    ts = pd.date_range("2022-02-01 09:30", periods=4, freq="60min", tz="America/New_York")
    a = pd.DataFrame({"decision_timestamp": ts, "entry_timestamp": ts, "calendar_date": ts.normalize(), "action": ["LONG_SOXL", "LONG_SOXS", "NO_TRADE", "LONG_SOXL"], "selected_symbol": ["soxl", "soxs", "", "soxl"], "horizon": [30, 30, 30, 30], "gross_delay1": [.01, .02, float("nan"), -.03], "gross_delay3": [.009, .015, float("nan"), -.02], "gross_delay5": [.008, .01, float("nan"), -.01]})
    m, trades = engine.metrics(a, {})
    assert len(trades) == 3 and m["long_soxl_count"] == 2 and m["long_soxs_count"] == 1
    assert m["DELAY_WORST_CASE_NET"] == min(m["DELAY_1M_NET"], m["DELAY_3M_NET"], m["DELAY_5M_NET"])
    assert m["NET_RETURN_20BPS"] == m["mean_net_20bps_delay5"]
    assert engine.failure({**m, "trade_count": 10, "unique_trade_days": 10}, {"single_validation_fold_max_drawdown": .25}) in {"SIGN_REVERSAL", "COST_SENSITIVITY", "PROFIT_CONCENTRATION", None}


def test_manifest_and_resume_lock_contract(tmp_path):
    manifest = {"generations": [{"validation_consumed": False, "confirmation_consumed": False}], "global_final_holdout": {"consumed": False}}
    manifest["split_sha256"] = engine.digest(manifest)
    assert engine.digest({k:v for k,v in manifest.items() if k != "split_sha256"}) != ""
    engine.checkpoint(tmp_path, state="TEST", validation_read_count=0, confirmation_read_count=0, global_final_holdout_read_count=0)
    first = json.loads((tmp_path / "v22_083_checkpoint.json").read_text())
    engine.checkpoint(tmp_path, state="TEST")
    second = json.loads((tmp_path / "v22_083_checkpoint.json").read_text())
    assert first["validation_read_count"] == second["validation_read_count"] == 0
