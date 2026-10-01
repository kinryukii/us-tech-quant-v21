"""Frozen feature names for the mechanically exported pre-2026 panel."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE_FEATURES = ["ret_1d", "ret_5d", "ret_20d", "realized_vol_20d",
                 "downside_vol_20d", "max_drawdown_20d", "volume_ratio_5d_20d",
                 "price_vs_ma20", "distance_from_high_20d"]
FEATURES = ["raw_rank_strength", "raw_score_z", *BASE_FEATURES,
            *[f"lag_ret_{i:02d}" for i in range(10)]]
