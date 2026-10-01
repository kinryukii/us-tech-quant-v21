"""Compare the thin account against the frozen original numerical replay."""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from policy_engine import HERE

sys.path.insert(0, str(HERE.parent / "a2_13f_learned_sizing_pre2026_test2026_r1"))
from train_pre2026 import load_data, replay  # noqa: E402


def main() -> None:
    panel, dates, _, _, _, _, ids, opens, calendar, _ = load_data()
    weights = np.full((len(dates), 20), .05)
    files = {"D1": HERE / "DEVELOPMENT_D1_POLICY_DAILY.parquet",
             "D2": HERE / "DEVELOPMENT_D2_POLICY_DAILY.parquet",
             "V25": HERE / "V25_POLICY_DAILY.parquet",
             "FINAL": HERE / "FINAL_INSAMPLE_POLICY_DAILY.parquet"}
    comparisons = {}
    for fold, path in files.items():
        frame = pd.read_parquet(path)
        actual = frame.loc[frame.policy.eq("B0")].sort_values("execution_date")
        signals = pd.DatetimeIndex(actual.signal_date.dropna())
        indices = dates.get_indexer(signals)
        if (indices < 0).any() or not np.array_equal(indices, np.arange(indices[0], indices[-1] + 1)):
            raise RuntimeError(f"NONCONTIGUOUS_B0_PATH:{fold}")
        expected, old_detail = replay(indices, weights, ids, opens, calendar, dates, detailed=True)
        observed = float(actual.net_nav_at_execution.iloc[-1])
        delta = observed - expected
        if abs(delta) > 1e-10:
            raise RuntimeError(f"B0_ACCOUNTING_MISMATCH:{fold}:{delta}")
        comparisons[fold] = {"signal_days": len(signals), "native_replay_terminal": expected,
                             "new_entry_terminal": observed, "absolute_delta": abs(delta),
                             "original_replay_steps": len(old_detail),
                             "new_entry_steps": len(actual)}
    result = {"status": "PASS", "comparison": comparisons,
              "scope": "same pre-2026 price surface and same exact signal-date windows; no model fit or new test reveal"}
    (HERE / "B0_ACCOUNTING_COMPARISON.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({fold: info["absolute_delta"] for fold, info in comparisons.items()}))


if __name__ == "__main__":
    main()
