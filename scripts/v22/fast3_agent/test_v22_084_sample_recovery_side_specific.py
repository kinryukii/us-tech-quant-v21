import json
import numpy as np
import pandas as pd

import v22_084_sample_recovery_side_specific as engine


def _actions():
    ts = pd.date_range("2022-03-01 09:30", periods=4, freq="15min", tz="America/New_York")
    return pd.DataFrame({"decision_timestamp": ts, "entry_timestamp": ts, "calendar_date": ts.normalize(), "action": ["LONG_SOXL", "LONG_SOXL", "LONG_SOXS", "NO_TRADE"], "final_confidence": [.8, .7, .9, .1], "horizon": [30] * 4, "gross_delay1": [.01, .02, .03, np.nan], "gross_delay3": [.009, .018, .025, np.nan], "gross_delay5": [.008, .016, .02, np.nan]})


def test_safety_models_and_budget():
    assert engine.SAFETY["broker_action_allowed"] is False
    assert engine.SAFETY["official_adoption_allowed"] is False
    assert len(engine.FEATURES) <= 20
    assert {x["model_type"] for x in engine.candidates(1)} == {"elastic_net_logistic", "hist_gradient_boosting"}


def test_absolute_floor_topk_caps_and_no_forced_trade():
    out = engine.ranked_actions(_actions())
    trade = out[out.action.ne("NO_TRADE")]
    assert len(trade) == 1  # second SOXL overlaps and SOXS is also blocked by horizon independence
    assert out.loc[out.final_confidence.eq(.1), "action"].item() == "NO_TRADE"


def test_nan_label_regression_and_alignment_contract():
    # Regression for V22.083: reset/eligibility precedes label construction;
    # an incomplete future path cannot survive into labels or metrics.
    cols = {f: [1., 1.] for f in engine.FEATURES}
    f = pd.DataFrame(cols); f["decision_timestamp"] = pd.date_range("2022-01-03 10:00", periods=2, freq="5min", tz="America/New_York"); f["entry_timestamp"] = f.decision_timestamp; f["calendar_date"] = f.decision_timestamp.dt.normalize()
    for side in ("soxl", "soxs"):
        for h in engine.HORIZONS:
            for d in engine.DELAYS:
                stem = f"{side}_{h}m_d{d}"; f[stem + "_entry_price"] = [10., 10.]; f[stem + "_exit_price"] = [10.2, np.nan]; f[stem + "_gross"] = [.02, np.nan]; f[stem + "_entry_timestamp"] = f.entry_timestamp; f[stem + "_exit_timestamp"] = f.entry_timestamp + pd.Timedelta(minutes=h)
    kept, contract = engine.eligibility(f)
    assert len(kept) == 1 and contract["LABEL_NAN_COUNT"] == 0 and contract["INELIGIBLE_SAMPLE_COUNT"] == 1


def test_metrics_power_delay_costs():
    m, trade = engine.metrics(_actions().iloc[[0, 2]].copy())
    assert m["DELAY_WORST_CASE_NET"] == min(m["DELAY_1M_NET"], m["DELAY_3M_NET"], m["DELAY_5M_NET"])
    assert m["NET_RETURN_20BPS"] == m["mean_net_20bps_delay5"]
    assert m["max_drawdown"] >= 0
    assert engine.failure(m, {"minimum_validation_trades": 20, "minimum_validation_unique_days": 10, "single_validation_fold_max_drawdown": .25}) == "INSUFFICIENT_STATISTICAL_POWER"


def test_checkpoint_resume_and_holdout_lock(tmp_path):
    engine.checkpoint(tmp_path, state="TEST", validation_read_count=0, confirmation_read_count=0, global_final_holdout_read_count=0)
    first = json.loads((tmp_path / "v22_084_checkpoint.json").read_text())
    engine.checkpoint(tmp_path, state="TEST")
    second = json.loads((tmp_path / "v22_084_checkpoint.json").read_text())
    assert first["validation_read_count"] == second["validation_read_count"] == 0
