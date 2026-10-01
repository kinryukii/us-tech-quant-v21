"""Read-only existing-position eligibility diagnostic; no replay."""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
panel = pd.read_parquet(ROOT / "test2026" / "predictions.parquet", columns=["signal_date", "ticker"])
targets = pd.read_parquet(ROOT / "test2026" / "rl_ensemble_targets.parquet")
joined = targets.merge(panel.assign(in_top40=True), on=["signal_date", "ticker"], how="left", validate="many_to_one")
outside = joined.loc[joined.in_top40.isna()]
assert outside.held_before.all()
result = {"dates_total": int(targets.signal_date.nunique()),
          "dates_with_held_outside_top40": int(outside.signal_date.nunique()),
          "held_outside_top40_records": int(len(outside)),
          "positive_target_records": int(outside.target_weight.gt(0).sum()),
          "sum_target_weight_across_dates": float(outside.target_weight.sum()),
          "mean_target_exposure_per_all_dates": float(outside.target_weight.sum() / targets.signal_date.nunique())}
(OUT / "rl_held_outside_top40.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, indent=2))
