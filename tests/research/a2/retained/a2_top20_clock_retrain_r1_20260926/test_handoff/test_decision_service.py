"""Synthetic, no-market check of the curated R1 decision service."""
from __future__ import annotations

import sys
from pathlib import Path

import decision_service as service


def main():
    sys.dont_write_bytecode = True
    root = Path(__file__).resolve().parent / "decision_bundle"
    identity_sha = service.verify_projection(root)
    assert len(identity_sha) == 64
    features = ["raw_rank_strength", "raw_score_z", "ret_1d", "ret_5d",
                "ret_20d", "realized_vol_20d", "downside_vol_20d",
                "max_drawdown_20d", "volume_ratio_5d_20d", "price_vs_ma20",
                "distance_from_high_20d", *[f"lag_ret_{i:02d}" for i in range(10)]]
    rows = [dict(signal_date="2026-01-02", ticker=f"T{i:02d}",
                 security_id=f"S{i:02d}", raw_rank=i + 1,
                 **{name: 0.0 for name in features}) for i in range(40)]
    predictor = service.DecisionEngine("predict", None, root, root)
    predicted = predictor.handle({"op": "predict", "rows": rows})["rows"]
    assert len(predicted) == 40 and all("pred_hgb" in row for row in predicted)
    assert all("pred_q10" in row and "pred_q90" in row for row in predicted)
    day = [{**original, **prediction} for original, prediction in zip(rows, predicted)]
    def target(candidate, *, shadow=None):
        engine = service.DecisionEngine("target", candidate, root, root)
        return engine.handle({"op": "target", "candidate": candidate,
                              "signal_date": "2026-01-02", "rows": day,
                              "shares": {}, "values": {}, "nav": 100_000.0,
                              **({"shadow": shadow} if shadow is not None else {})})
    raw = target("Raw")
    assert len(raw["target"]) == 20 and abs(sum(raw["target"].values()) - 1.0) < 1e-12
    factor = target("HGB_FACTOR_5")
    assert sum(factor["target"].values()) <= 1.0 + 1e-8
    equal = target("HGB_CONTROL_B_SHADOW_SET_GROSS_EQUAL_WEIGHT", shadow=factor["target"])
    assert abs(sum(equal["target"].values()) - sum(factor["target"].values())) < 1e-8
    rl = target("RL_C_SELECTED_TARGET_MEAN")
    assert sum(rl["target"].values()) <= .95 + 1e-6
    assert all("raw_action_logit_20260925" in value for value in rl["metadata"].values())
    try:
        predictor.handle({"op": "predict", "rows": rows})
    except ValueError as exc:
        assert "MONOTONE" in str(exc)
    else:
        raise AssertionError("Repeated signal date accepted")
    print("SYNTHETIC_R1_DECISION_SERVICE_PASS")


if __name__ == "__main__":
    main()
