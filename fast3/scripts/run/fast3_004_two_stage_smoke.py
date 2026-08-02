"""Synthetic-only FAST3-004 architecture smoke; never reads market or Confirmation data."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from fast3.src.fast3.models.two_stage_pipeline import TwoStageResearchPipeline, load_fast3_004_config


REPO = Path(__file__).resolve().parents[3]
CONFIG = REPO / "fast3" / "configs" / "models" / "FAST3_004_TWO_STAGE_RESEARCH.json"


def synthetic_events(rows: int = 48) -> pd.DataFrame:
    timestamp = pd.date_range("2024-01-02 09:30", periods=rows, freq="D", tz="America/New_York")
    index = np.arange(rows)
    return pd.DataFrame({"event_id": [f"synthetic-{i}" for i in index], "decision_timestamp_et": timestamp,
                         "label_end_timestamp_et": timestamp + pd.Timedelta(hours=24),
                         "feature_available_at_et": timestamp - pd.Timedelta(minutes=1),
                         "feature_ret_1": np.sin(index / 3), "feature_volume_z": np.cos(index / 5),
                         "opportunity_target": (index % 3 != 0).astype(int), "direction_target": (index % 2 == 0).astype(int),
                         "underlying_symbol": "SOXX", "regime": np.where(index % 2 == 0, "TREND", "RANGE")})


def main() -> int:
    config = load_fast3_004_config(CONFIG)
    pipeline = TwoStageResearchPipeline(config)
    scored, folds = pipeline.run_nested(synthetic_events())
    result = {"stage": "FAST3-004", "purpose": "synthetic architecture smoke only; no market, validation, or Confirmation rows read",
              "confirmation_read_count": 0, "live_trading_allowed": False,
              "research_fit_call_count": len(pipeline.ledger.entries), "synthetic_research_fit_executed": True,
              "final_model_training_executed": False, "real_development_run_executed": False,
              "frozen_validation_run_executed": False, "fast3_004_empirical_validation_status": "NOT_RUN",
              "outer_test_rows": len(scored), "fold_count": len(folds),
              "eligible_count": int(scored.opportunity_eligible.sum()) if not scored.empty else 0,
              "diagnostics": pipeline.concentration_diagnostics(scored)}
    print(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
