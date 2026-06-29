#!/usr/bin/env python
"""Audit V21.073 PIT daily price paths."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from v21_073_common import OUT_REL
from v21_073_r1_pit_daily_price_path_panel_builder import (
    OBS_NAME, PATH_NAME, run_stage as run_r1,
)


STAGE = "V21.073-R2_PRICE_PATH_INTEGRITY_AUDIT"
DETAIL_NAME = "V21_073_R2_PRICE_PATH_INTEGRITY_DETAIL.csv"
COVERAGE_NAME = "V21_073_R2_PRICE_PATH_COVERAGE.csv"
VALIDATION_NAME = "V21_073_R2_VALIDATION_SUMMARY.csv"


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, object]:
    root = root.resolve()
    output = (
        output_override if output_override and output_override.is_absolute()
        else root / (output_override or OUT_REL)
    ).resolve()
    if not (output / PATH_NAME).is_file():
        run_r1(root, output)
    paths = pd.read_csv(output / PATH_NAME, low_memory=False)
    observations = pd.read_csv(output / OBS_NAME)
    now = datetime.now(timezone.utc).isoformat()
    numeric = {
        column: pd.to_numeric(paths[column], errors="coerce")
        for column in ("open", "high", "low", "close")
    }
    duplicate = paths.duplicated(["observation_id", "forward_day_index"]).sum()
    missing_ohlc = pd.DataFrame(numeric).isna().any(axis=1)
    impossible = (
        (numeric["high"] < numeric["low"])
        | (numeric["high"] < numeric["open"])
        | (numeric["high"] < numeric["close"])
        | (numeric["low"] > numeric["open"])
        | (numeric["low"] > numeric["close"])
    )
    path_date = pd.to_datetime(paths["path_date"], errors="coerce")
    as_of = pd.to_datetime(paths["as_of_date"], errors="coerce")
    pit_boundary = path_date.le(as_of)
    stale = paths.groupby("observation_id")["close"].transform(
        lambda series: series.eq(series.shift()).rolling(5, min_periods=5).sum().ge(5)
    )
    adjusted = pd.to_numeric(paths["adjusted_close"], errors="coerce")
    close = pd.to_numeric(paths["close"], errors="coerce")
    adjustment_ratio = adjusted / close.replace(0, pd.NA)
    split_anomaly = adjustment_ratio.groupby(paths["ticker"]).pct_change().abs().gt(0.5)
    issue = pd.DataFrame({
        "observation_id": paths["observation_id"],
        "forward_day_index": paths["forward_day_index"],
        "path_date": paths["path_date"],
        "duplicate_flag": paths.duplicated(
            ["observation_id", "forward_day_index"], keep=False
        ),
        "missing_ohlc_flag": missing_ohlc,
        "impossible_ohlc_flag": impossible,
        "stale_price_flag": stale.fillna(False),
        "split_adjustment_anomaly_flag": split_anomaly.fillna(False),
        "pit_boundary_violation_flag": pit_boundary,
    })
    issue = issue[issue.iloc[:, 3:].any(axis=1)]
    issue.to_csv(output / DETAIL_NAME, index=False)
    depth = paths.groupby("observation_id")["forward_day_index"].max()
    coverage = observations[["observation_id", "as_of_date", "ticker"]].copy()
    coverage["max_forward_day"] = coverage["observation_id"].map(depth).fillna(0)
    for window in (5, 10, 20):
        coverage[f"coverage_{window}d"] = coverage["max_forward_day"].ge(window)
    coverage["missing_path_day_count"] = (20 - coverage["max_forward_day"]).clip(lower=0)
    coverage.to_csv(output / COVERAGE_NAME, index=False)
    critical = int(duplicate + missing_ohlc.sum() + impossible.sum() + pit_boundary.sum())
    validation = {
        "stage": STAGE,
        "final_status": (
            "PASS_V21_073_R2_PRICE_PATH_INTEGRITY_READY"
            if critical == 0 else
            "BLOCKED_V21_073_R2_PRICE_PATH_INTEGRITY_RISK"
        ),
        "decision": (
            "PRICE_PATH_READY_FOR_CAUSAL_EXIT_SIMULATION"
            if critical == 0 else "REPAIR_PATH_PANEL_BEFORE_EXIT_SIMULATION"
        ),
        "generated_at_utc": now, "path_rows": len(paths),
        "observations_expected": len(observations),
        "observations_covered": depth.size,
        "duplicate_count": int(duplicate),
        "missing_ohlc_count": int(missing_ohlc.sum()),
        "impossible_ohlc_count": int(impossible.sum()),
        "stale_price_count": int(stale.fillna(False).sum()),
        "split_adjustment_anomaly_count": int(split_anomaly.fillna(False).sum()),
        "pit_boundary_violation_count": int(pit_boundary.sum()),
        "coverage_5d": float(coverage["coverage_5d"].mean()),
        "coverage_10d": float(coverage["coverage_10d"].mean()),
        "coverage_20d": float(coverage["coverage_20d"].mean()),
        "leakage_warning_count": int(pit_boundary.sum()),
        "integrity_audit_result": "PASS" if critical == 0 else "BLOCKED",
        "protected_outputs_modified": False,
        "official_outputs_mutated": False, "research_only": True,
        "pass_gate": critical == 0,
    }
    pd.DataFrame([validation]).to_csv(output / VALIDATION_NAME, index=False)
    return validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    result = run_stage(args.root, args.output_dir)
    for key in ("final_status", "decision", "duplicate_count",
                "missing_ohlc_count", "integrity_audit_result"):
        print(f"{key.upper()}={result[key]}")
    return 0 if result["pass_gate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
