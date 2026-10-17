"""Technical inference checks on a pre-2026 day, never a performance estimate."""
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from predict import predict_panel, predict_state, score_rl, load_model, registry, HERE
from register_models import STATE, write


def main():
    features = registry()["feature_order"]
    source = Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\A\score_rank_ledger.parquet")
    day = pd.read_parquet(source, filters=[("signal_date", "==", pd.Timestamp("2025-12-29"))], columns=["signal_date", "ticker", *features])
    assert day.signal_date.lt("2026-01-01").all() and len(day) >= 20
    result = predict_panel(day)
    assert result[["signal_date", "ticker"]].equals(day[["signal_date", "ticker"]])
    assert result.logistic.between(0, 1).all()
    initial = predict_state(day)
    policy = score_rl(day)
    assert len(policy) == len(day) and policy["rank"].is_unique
    held = set(policy.head(20).ticker)
    second = score_rl(day, held)
    aligned = second.merge(policy, on=["signal_date", "ticker"], suffixes=("_held", "_empty"))
    expected = aligned.ticker.isin(held).to_numpy(float) * float(load_model("rl_policy")["weight"][-1])
    assert np.allclose(aligned.rl_held - aligned.rl_empty, expected, rtol=0, atol=1e-10)
    state_cols = registry()["daily_state_columns"]
    frozen_state = pd.read_parquet(STATE / "pre2026_daily_state_inputs.parquet", filters=[("signal_date", "==", pd.Timestamp("2025-12-29"))])
    assert int(load_model("cluster").predict(frozen_state[state_cols].to_numpy(float))[0]) == initial["cluster_id"]
    noisy = day.copy()
    noisy["target"] = 999.0
    noisy["next_open_return"] = -999.0
    assert predict_panel(noisy).equals(result)
    duplicate_rejected = False
    try:
        predict_panel(pd.concat([day, day.iloc[:1]], ignore_index=True))
    except ValueError:
        duplicate_rejected = True
    assert duplicate_rejected
    receipt = {"status": "PASS", "scope": "technical smoke test only; final models were trained through this date",
               "sample_date": "2025-12-29", "rows": len(day), "prediction_columns": list(result.columns),
               "state": initial, "outcome_column_perturbation_invariant": True, "duplicate_keys_rejected": True,
               "rl_previous_target_membership_verified": True, "test_outcomes_read": 0, "fit_calls": 0}
    write(HERE / "SMOKE_TEST_RECEIPT.json", receipt)
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
