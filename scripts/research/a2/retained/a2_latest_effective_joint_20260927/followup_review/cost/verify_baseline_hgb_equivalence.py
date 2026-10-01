"""Compare the thin HGB baseline readout with the original full adapter.

Uses one synthetic day only; it does not open market data or evaluate a policy.
"""
from pathlib import Path
import hashlib
import json
import sys

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from models.predict import predict_panel  # noqa: E402
from replay_2026_sampling_v2 import baseline_hgb_scores, FEATURES  # noqa: E402


def main() -> None:
    panel = pd.DataFrame({"signal_date": pd.Timestamp("2025-01-02"),
                          "ticker": [f"SYN{i:03d}" for i in range(40)]})
    for col in FEATURES:
        panel[col] = .03 if "vol" in col else 30_000_000.0 if col == "avg_dollar_volume_20d" else .01
    original = predict_panel(panel)[["signal_date", "ticker", "hgb"]]
    thin = baseline_hgb_scores(panel)
    assert original[["signal_date", "ticker"]].equals(thin[["signal_date", "ticker"]])
    difference = np.max(np.abs(original.hgb.to_numpy(float) - thin.baseline_hgb.to_numpy(float)))
    assert difference == 0.0
    record = dict(status="PASS", synthetic_only=True, rows=len(panel), max_abs_hgb_difference=0.0,
                  original_adapter="models.predict.predict_panel()['hgb']",
                  versioned_runner_adapter="replay_2026_sampling_v2.baseline_hgb_scores",
                  no_market_data_read=True, no_2026_input_read=True,
                  code_sha256={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                               for path in (ROOT / "models" / "predict.py",
                                            ROOT / "followup_review" / "cost" / "replay_2026_sampling_v2.py")})
    (Path(__file__).resolve().parent / "V2_BASELINE_HGB_EQUIVALENCE.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    print("V2_BASELINE_HGB_SYNTHETIC_EQUIVALENCE_PASS", len(panel), difference)


if __name__ == "__main__":
    main()
