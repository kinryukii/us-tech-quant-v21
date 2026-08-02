"""Synthetic-only FAST3-005 abstention smoke; no market, model, or Confirmation access."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from fast3.src.fast3.models.abstention_policy import apply_abstention_policy, load_abstention_policy, safety_summary


REPO = Path(__file__).resolve().parents[3]
POLICY = REPO / "fast3" / "configs" / "models" / "FAST3_005_ABSTENTION_POLICY.json"


def synthetic_scored_events() -> pd.DataFrame:
    base = {"opportunity_score": .8, "direction_score_up": .8, "direction_model_score_spread": .1,
            "data_trust_ok": True, "expected_net_return_10bps": .01, "expected_net_return_20bps": .009}
    variants = [
        {"event_id": "data", "data_trust_ok": False}, {"event_id": "opportunity", "opportunity_score": .59},
        {"event_id": "confidence", "direction_score_up": .55}, {"event_id": "disagreement", "direction_model_score_spread": .21},
        {"event_id": "cost10", "expected_net_return_10bps": 0.0}, {"event_id": "cost20", "expected_net_return_20bps": -.001},
        {"event_id": "eligible"},
    ]
    return pd.DataFrame([{**base, **row} for row in variants])


def main() -> int:
    decisions = apply_abstention_policy(synthetic_scored_events(), load_abstention_policy(POLICY))
    result = {"stage": "FAST3-005", "purpose": "synthetic abstention logic smoke only", "synthetic_research_fit_executed": False,
              "final_model_training_executed": False, "real_development_run_executed": False, "frozen_validation_run_executed": False,
              "confirmation_read_count": 0, "live_trading_allowed": False, "empirical_validation_status": "NOT_RUN",
              "reason_codes": decisions.abstention_reason.dropna().tolist(), "safety": safety_summary(decisions)}
    print(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
