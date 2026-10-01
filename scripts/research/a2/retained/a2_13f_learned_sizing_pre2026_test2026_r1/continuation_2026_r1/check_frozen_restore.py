"""Load saved final coefficients/scalers; no fitting or outcome access."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from finalize_pre2026 import model_weights  # noqa: E402
from train_pre2026 import load_data  # noqa: E402

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    manifest = json.loads((BASE / "RUN_MANIFEST.json").read_text(encoding="utf-8"))
    model_path = BASE / "MODEL_FROZEN.json"
    assert sha(model_path) == manifest["model_frozen_sha256"]
    model = json.loads(model_path.read_text(encoding="utf-8"))
    panel, dates, _, _, usable, raw, _, _, _, _ = load_data()
    saved = pd.read_parquet(BASE / "PRE2026_FINAL_FIT_INSAMPLE_WEIGHTS.parquet")
    sample_days = [0, 1, 2, 249, 500, 747, 748, 749]
    checks = {}
    for name in ("M_FULL", "M_NO13F"):
        predicted = model_weights(model, name, raw, usable)
        comparison = saved.loc[saved.policy.eq(name), ["signal_date", "ticker", "target_weight", "fallback"]]
        comparison = comparison.merge(panel[["signal_date", "ticker", "a2_rank"]],
                                      on=["signal_date", "ticker"], validate="one_to_one")
        comparison = comparison.sort_values(["signal_date", "a2_rank"])
        expected = comparison.target_weight.to_numpy().reshape(-1, 20)
        assert len(dates) == len(predicted) == len(expected)
        error = float(np.max(np.abs(predicted[sample_days] - expected[sample_days])))
        assert error <= 1e-14
        assert np.allclose(predicted.sum(axis=1), 1.0, atol=1e-10, rtol=0)
        assert np.max(predicted) <= 0.1 + 1e-10
        checks[name] = {"sample_days": len(sample_days), "max_abs_weight_error": error,
                        "columns": model["fits"][name]["columns"]}
    result = {"status": "PASS_FINAL_MODELS_EXACTLY_RESTORED", "model_sha256": sha(model_path),
              "sample_signal_dates": [str(dates[i].date()) for i in sample_days], "checks": checks,
              "fit_calls": 0, "scaler_fit_calls": 0}
    (Path(__file__).parent / "MODEL_RESTORE_CHECK.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
