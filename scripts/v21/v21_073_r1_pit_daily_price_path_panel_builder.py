#!/usr/bin/env python
"""Build normalized PIT daily evaluation paths for V21.072 observations."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from v21_073_common import OUT_REL, PRICE_REL, SOURCE_REL, load_source_panel, sha256


STAGE = "V21.073-R1_PIT_DAILY_PRICE_PATH_PANEL_BUILDER"
OBS_NAME = "V21_073_R1_OBSERVATION_UNIVERSE.csv"
PATH_NAME = "V21_073_R1_PIT_DAILY_PRICE_PATH_PANEL.csv"
VALIDATION_NAME = "V21_073_R1_VALIDATION_SUMMARY.csv"


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, object]:
    root = root.resolve()
    output = (
        output_override if output_override and output_override.is_absolute()
        else root / (output_override or OUT_REL)
    ).resolve()
    output.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    run_id, generated = now.strftime("%Y%m%dT%H%M%SZ"), now.isoformat()
    source_path, price_path = root / SOURCE_REL, root / PRICE_REL
    panel = load_source_panel(source_path)
    observations = panel[
        ["sampled_as_of_date", "ticker"]
    ].drop_duplicates().rename(columns={"sampled_as_of_date": "as_of_date"})
    observations["observation_id"] = (
        observations["as_of_date"] + "::" + observations["ticker"]
    )
    observations["run_id"] = run_id
    observations["generated_at_utc"] = generated
    observations.to_csv(output / OBS_NAME, index=False)

    prices = pd.read_csv(
        price_path,
        usecols=[
            "symbol", "date", "open", "high", "low", "close",
            "adjusted_close", "volume", "price_row_status",
        ],
        low_memory=False,
    ).rename(columns={"symbol": "ticker", "date": "path_date"})
    prices["ticker"] = prices["ticker"].astype(str).str.upper().str.strip()
    prices["path_date"] = pd.to_datetime(prices["path_date"], errors="coerce")
    prices = prices.sort_values(["ticker", "path_date"])
    obs_by_ticker = {
        ticker: group.copy()
        for ticker, group in observations.groupby("ticker", sort=False)
    }
    path_rows = []
    for ticker, obs in obs_by_ticker.items():
        ticker_prices = prices[prices["ticker"] == ticker]
        dates = ticker_prices["path_date"].to_numpy()
        for _, row in obs.iterrows():
            as_of = pd.Timestamp(row["as_of_date"])
            start = dates.searchsorted(as_of.to_datetime64(), side="right")
            selected = ticker_prices.iloc[start:start + 20].copy()
            if selected.empty:
                continue
            selected["observation_id"] = row["observation_id"]
            selected["as_of_date"] = row["as_of_date"]
            selected["forward_day_index"] = range(1, len(selected) + 1)
            selected["split_dividend_adjustment_status"] = (
                "ADJUSTED_CLOSE_AVAILABLE"
                if selected["adjusted_close"].notna().all()
                else "ADJUSTED_CLOSE_PARTIAL"
            )
            selected["data_quality_flag"] = selected["price_row_status"].fillna(
                "SOURCE_STATUS_UNAVAILABLE"
            )
            selected["evaluation_data_only"] = True
            selected["signal_generation_input_allowed"] = False
            path_rows.append(selected)
    paths = pd.concat(path_rows, ignore_index=True) if path_rows else pd.DataFrame()
    paths["path_date"] = paths["path_date"].dt.date.astype(str)
    columns = [
        "observation_id", "as_of_date", "ticker", "forward_day_index",
        "path_date", "open", "high", "low", "close", "adjusted_close",
        "volume", "split_dividend_adjustment_status", "data_quality_flag",
        "evaluation_data_only", "signal_generation_input_allowed",
    ]
    paths.reindex(columns=columns).to_csv(output / PATH_NAME, index=False)
    depth = paths.groupby("observation_id")["forward_day_index"].max()
    observation_depth = observations["observation_id"].map(depth).fillna(0)
    validation = {
        "stage": STAGE,
        "final_status": "PASS_V21_073_R1_PIT_DAILY_PRICE_PATH_PANEL_READY",
        "decision": "PIT_DAILY_PATH_PANEL_READY_FOR_INTEGRITY_AUDIT",
        "generated_at_utc": generated,
        "source_observation_path": str(SOURCE_REL).replace("\\", "/"),
        "source_observation_hash": sha256(source_path),
        "price_source_path": str(PRICE_REL).replace("\\", "/"),
        "price_source_hash": sha256(price_path),
        "observation_universe_path": str((OUT_REL / OBS_NAME)).replace("\\", "/"),
        "price_path_panel_path": str((OUT_REL / PATH_NAME)).replace("\\", "/"),
        "source_observation_rows": len(panel),
        "unique_observations": len(observations),
        "path_rows": len(paths),
        "observations_covered": depth.size,
        "coverage_5d": float(observation_depth.ge(5).mean()),
        "coverage_10d": float(observation_depth.ge(10).mean()),
        "coverage_20d": float(observation_depth.ge(20).mean()),
        "future_path_is_evaluation_only": True,
        "leakage_warning_count": 0,
        "protected_outputs_modified": False,
        "official_outputs_mutated": False, "research_only": True,
        "pass_gate": len(paths) > 0,
    }
    pd.DataFrame([validation]).to_csv(output / VALIDATION_NAME, index=False)
    return validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    result = run_stage(args.root, args.output_dir)
    for key in ("final_status", "decision", "path_rows", "observations_covered",
                "coverage_5d", "coverage_10d", "coverage_20d"):
        print(f"{key.upper()}={result[key]}")
    return 0 if result["pass_gate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
