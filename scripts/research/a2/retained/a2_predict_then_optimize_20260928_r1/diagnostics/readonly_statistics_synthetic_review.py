"""Read-only statistical audit using fabricated paths, never evaluation results."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
from comparison_analysis import comparison, factor_decomposition, hac_mean
from common import RISKS, OPTIMIZERS


def paired(n):
    keys = list(range(n))
    left = pd.DataFrame({"cell": keys, "strategy_id": [f"L{i}" for i in keys], "net_return": .05})
    right = pd.DataFrame({"cell": keys, "strategy_id": [f"R{i}" for i in keys], "net_return": .03})
    day = np.array([.002, -.001, .004, -.003, .001, .005, -.002, .003, -.001, .006, -.004, .002])
    dates = pd.bdate_range("2000-01-03", periods=len(day))
    daily = pd.DataFrame({**{f"L{i}": day for i in keys}, **{f"R{i}": np.zeros(len(day)) for i in keys}}, index=dates)
    return left, right, daily, day


def calendar_hac_reference(values, lag=5):
    """Only contrasts lag indexing; no claim about missingness inference."""
    x = np.asarray(values, float)
    finite = np.isfinite(x)
    n = int(finite.sum())
    z = x - x[finite].mean()
    total = float(z[finite] @ z[finite])
    for k in range(1, min(lag, len(x) - 1) + 1):
        mask = finite[k:] & finite[:-k]
        total += 2 * (1 - k / (lag + 1)) * float(z[k:][mask] @ z[:-k][mask])
    return float(np.sqrt(max(0., total)) / n)


def main():
    # All statistics below are fabricated. Guard against accidental table reads.
    def forbidden(*args, **kwargs):
        raise AssertionError("REAL_TABLE_READ_FORBIDDEN_IN_SYNTHETIC_REVIEW")
    pd.read_csv = forbidden
    pd.read_parquet = forbidden

    observations = {}
    small = paired(30)
    large = paired(300)
    a = comparison(*small[:3], ["cell"], comparison="synthetic")
    b = comparison(*large[:3], ["cell"], comparison="synthetic")
    assert a["days"] == b["days"] == 12
    assert np.isclose(a["mean_daily_log_difference"], small[3].mean(), rtol=0, atol=1e-15)
    assert np.isclose(a["hac_se_lag5"], b["hac_se_lag5"], rtol=0, atol=1e-15)
    observations["day_unit_and_replication"] = {"status": "PASS", "small_cells": a["matched_cells"],
        "large_cells": b["matched_cells"], "days_both": 12, "se_small": a["hac_se_lag5"], "se_large": b["hac_se_lag5"]}

    rows = []
    for i, forecast in enumerate(["synthetic_a", "synthetic_b"]):
        for j, risk in enumerate(RISKS):
            for k, optimizer in enumerate(OPTIMIZERS):
                rows.append({"forecast_id": forecast, "risk": risk, "optimizer": optimizer,
                             "net_return": .1 + .01 * i + .002 * j + .005 * k})
    frame = pd.DataFrame(rows)
    factors = factor_decomposition(frame)
    assert np.abs(factors[["forecast_risk_interaction", "forecast_optimizer_interaction",
                          "risk_optimizer_interaction", "three_way_interaction"]].to_numpy()).max() < 1e-12
    observations["complete_additive_grid"] = {"status": "PASS", "cells": len(frame)}

    altered = frame.copy()
    altered.loc[(altered.forecast_id == "synthetic_a") & (altered.risk == RISKS[0]), "risk"] = "UNREGISTERED_RISK"
    try:
        factor_decomposition(altered)
    except (ValueError, AssertionError) as error:
        observations["noncartesian_30_per_forecast"] = {"behavior": "REJECTED", "reason": str(error)}
    else:
        observations["noncartesian_30_per_forecast"] = {"behavior": "ACCEPTED", "reason": "30 unique cells per forecast alone does not prove common Cartesian grid"}

    unmatched = comparison(small[0], small[1].iloc[:-1], small[2], ["cell"], comparison="synthetic_missing")
    observations["one_missing_partner"] = unmatched
    both_missing = comparison(small[0].iloc[:-2], small[1].iloc[:-2], small[2], ["cell"],
                              expected_cells=30, comparison="synthetic_both_missing")
    assert both_missing["expected_cells"] == 30 and both_missing["matched_cells"] == 28
    assert both_missing["both_missing_cells"] == 2 and not both_missing["complete_matched_grid"]
    observations["both_missing_prespecified_cells"] = {key: both_missing[key] for key in
        ["expected_cells", "matched_cells", "both_missing_cells", "complete_matched_grid", "days"]}
    none_available = comparison(small[0].iloc[:0], small[1].iloc[:0], small[2], ["cell"],
                                expected_cells=30, comparison="synthetic_all_failed")
    assert none_available["matched_cells"] == 0 and none_available["both_missing_cells"] == 30
    assert none_available["days"] == 0 and none_available["mean_daily_log_difference"] is None
    observations["all_failed_no_imputation"] = {key: none_available[key] for key in
        ["expected_cells", "matched_cells", "both_missing_cells", "days", "mean_daily_log_difference"]}
    disjoint = small[1].copy()
    disjoint["cell"] += 1000
    observations["zero_matching_cells"] = comparison(small[0], disjoint, small[2], ["cell"], comparison="synthetic_no_matches")

    with_gap = np.array([.01, -.005, np.nan, np.nan, .012, -.002, .015, -.004])
    compressed = hac_mean(with_gap)
    reference = calendar_hac_reference(with_gap)
    assert compressed["days"] == 6
    assert not np.isclose(compressed["hac_se_lag5"], reference, rtol=0, atol=1e-12)
    observations["missing_calendar_lag_semantics"] = {"finite_days": 6, "calendar_rows": 8,
        "compressed_valid_observation_lag5_se": compressed["hac_se_lag5"],
        "original_calendar_lag5_contrast_se": reference,
        "inference": "Existing HAC filters finite observations; its lag counts retained observations if internal gaps occur."}

    receipt = {"status": "SYNTHETIC_READONLY_REVIEW_COMPLETE", "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                          for name in ["comparison_analysis.py", "build_delivery.py", "DIMENSION_ANALYSIS_INTERPRETATION.md"]},
        "evaluation_result_reads": 0, "fit_calls": 0, "frozen_artifacts_modified": False,
        "learning_selection_or_search": False, "observations": observations}
    path = ROOT / "diagnostics/READONLY_STATISTICS_SYNTHETIC_RECEIPT.json"
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "observations": observations}, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
