import argparse
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


HORIZONS = [1, 3, 5, 10, 20]


def stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def read_csv_safe(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.read_csv(path, encoding="utf-8-sig")


def write_csv(df: pd.DataFrame, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def to_bool_value(x):
    return str(x).strip().lower() in {"true", "1", "yes", "y"}


def normalize_current_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()

    required = ["ticker", "price_date", "close"]
    missing = [c for c in required if c not in x.columns]
    if missing:
        raise RuntimeError(f"Missing required columns in V18.6A current technical timing CSV: {missing}")

    x["ticker"] = x["ticker"].astype(str).str.strip()
    x["snapshot_price_date"] = x["price_date"].astype(str).str.strip()
    x["baseline_close"] = pd.to_numeric(x["close"], errors="coerce")

    x["technical_timing_score"] = pd.to_numeric(x.get("technical_timing_score", np.nan), errors="coerce")
    x["overheat_penalty"] = pd.to_numeric(x.get("overheat_penalty", np.nan), errors="coerce")
    x["pullback_timing_bonus"] = pd.to_numeric(x.get("pullback_timing_bonus", np.nan), errors="coerce")
    x["breakout_confirmation_bonus"] = pd.to_numeric(x.get("breakout_confirmation_bonus", np.nan), errors="coerce")
    x["volume_ratio_5_20"] = pd.to_numeric(x.get("volume_ratio_5_20", np.nan), errors="coerce")
    x["rsi_14"] = pd.to_numeric(x.get("rsi_14", np.nan), errors="coerce")
    x["kdj_k"] = pd.to_numeric(x.get("kdj_k", np.nan), errors="coerce")
    x["kdj_d"] = pd.to_numeric(x.get("kdj_d", np.nan), errors="coerce")
    x["kdj_j"] = pd.to_numeric(x.get("kdj_j", np.nan), errors="coerce")
    x["bb_percent_b"] = pd.to_numeric(x.get("bb_percent_b", np.nan), errors="coerce")
    x["bb_bandwidth"] = pd.to_numeric(x.get("bb_bandwidth", np.nan), errors="coerce")

    if "bb_squeeze_flag" in x.columns:
        x["signal_bb_squeeze"] = x["bb_squeeze_flag"].apply(to_bool_value)
    else:
        x["signal_bb_squeeze"] = False

    tech_signal = x.get("technical_signal", "").astype(str)

    x["signal_watch_positive"] = tech_signal.eq("TECH_TIMING_WATCH_POSITIVE")
    x["signal_pullback_watch"] = tech_signal.eq("TECH_TIMING_PULLBACK_WATCH")
    x["signal_overheat_old"] = tech_signal.eq("TECH_TIMING_OVERHEAT_AVOID_CHASE")

    bb_status = x.get("bb_status", "").astype(str)
    rsi_status = x.get("rsi_status", "").astype(str)
    kdj_status = x.get("kdj_status", "").astype(str)

    # Strong overheat with volume confirmation: do not treat as bearish automatically.
    x["signal_breakout_continuation"] = (
        bb_status.isin(["BB_ABOVE_UPPER", "BB_NEAR_UPPER"])
        & (x["rsi_14"] >= 60)
        & (x["rsi_14"] <= 78)
        & (x["volume_ratio_5_20"] >= 1.15)
        & (~kdj_status.isin(["KDJ_HIGH_DEAD_CROSS"]))
    )

    # Possible exhaustion: extreme heat with weak volume confirmation.
    x["signal_exhaustion_risk"] = (
        (x["rsi_14"] >= 75)
        & kdj_status.isin(["KDJ_EXTREME_OVERHEAT", "KDJ_HIGH_DEAD_CROSS"])
        & ((x["volume_ratio_5_20"] < 1.0) | x["volume_ratio_5_20"].isna())
    )

    x["signal_overheat_unclassified"] = (
        x["signal_overheat_old"]
        & (~x["signal_breakout_continuation"])
        & (~x["signal_exhaustion_risk"])
    )

    keep_cols = [
        "snapshot_price_date",
        "ticker",
        "yf_ticker",
        "baseline_close",
        "technical_timing_score",
        "technical_signal",
        "bb_status",
        "rsi_status",
        "kdj_status",
        "bb_percent_b",
        "bb_bandwidth",
        "signal_bb_squeeze",
        "rsi_14",
        "kdj_k",
        "kdj_d",
        "kdj_j",
        "volume_ratio_5_20",
        "overheat_penalty",
        "pullback_timing_bonus",
        "breakout_confirmation_bonus",
        "technical_warning_label",
        "vix_date",
        "vix_close",
        "vix_regime",
        "signal_watch_positive",
        "signal_pullback_watch",
        "signal_overheat_old",
        "signal_breakout_continuation",
        "signal_exhaustion_risk",
        "signal_overheat_unclassified",
        "official_decision_impact",
    ]

    for c in keep_cols:
        if c not in x.columns:
            x[c] = np.nan

    out = x[keep_cols].copy()
    out["tracker_added_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out["official_decision_impact"] = "NONE"

    out = out.dropna(subset=["snapshot_price_date", "ticker", "baseline_close"])
    out = out[out["ticker"].astype(str).str.len() > 0]
    return out


def initialize_outcome_columns(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    for h in HORIZONS:
        for c in [
            f"obs_price_date_{h}",
            f"obs_close_{h}",
            f"ret_fwd_{h}",
            f"completed_{h}",
        ]:
            if c not in x.columns:
                if c.startswith("completed"):
                    x[c] = False
                else:
                    x[c] = np.nan
    return x


def update_forward_outcomes(tracker: pd.DataFrame) -> pd.DataFrame:
    x = tracker.copy()
    x = initialize_outcome_columns(x)

    x["snapshot_price_date"] = x["snapshot_price_date"].astype(str)
    x["ticker"] = x["ticker"].astype(str)
    x["baseline_close"] = pd.to_numeric(x["baseline_close"], errors="coerce")

    dates = sorted(x["snapshot_price_date"].dropna().unique().tolist())
    date_to_idx = {d: i for i, d in enumerate(dates)}

    close_lookup = {}
    for _, row in x.iterrows():
        key = (str(row["snapshot_price_date"]), str(row["ticker"]))
        close_lookup[key] = row["baseline_close"]

    for i, row in x.iterrows():
        base_date = str(row["snapshot_price_date"])
        ticker = str(row["ticker"])
        base_close = pd.to_numeric(row["baseline_close"], errors="coerce")

        if base_date not in date_to_idx or pd.isna(base_close) or base_close <= 0:
            continue

        base_idx = date_to_idx[base_date]

        for h in HORIZONS:
            target_idx = base_idx + h
            completed_col = f"completed_{h}"
            ret_col = f"ret_fwd_{h}"
            obs_date_col = f"obs_price_date_{h}"
            obs_close_col = f"obs_close_{h}"

            if target_idx >= len(dates):
                x.at[i, completed_col] = False
                continue

            target_date = dates[target_idx]
            target_close = close_lookup.get((target_date, ticker), np.nan)

            if pd.isna(target_close) or target_close <= 0:
                x.at[i, completed_col] = False
                continue

            x.at[i, obs_date_col] = target_date
            x.at[i, obs_close_col] = target_close
            x.at[i, ret_col] = target_close / base_close - 1
            x.at[i, completed_col] = True

    return x


def summarize_tracker(tracker: pd.DataFrame) -> pd.DataFrame:
    signal_defs = [
        ("signal_watch_positive", "WATCH_POSITIVE"),
        ("signal_pullback_watch", "PULLBACK_WATCH"),
        ("signal_bb_squeeze", "BB_SQUEEZE"),
        ("signal_breakout_continuation", "BREAKOUT_CONTINUATION"),
        ("signal_exhaustion_risk", "EXHAUSTION_RISK"),
        ("signal_overheat_unclassified", "OVERHEAT_UNCLASSIFIED"),
        ("signal_overheat_old", "OLD_OVERHEAT"),
    ]

    rows = []
    for sig_col, label in signal_defs:
        if sig_col not in tracker.columns:
            continue

        sig_mask = tracker[sig_col].apply(to_bool_value) if tracker[sig_col].dtype != bool else tracker[sig_col].fillna(False)
        sig = tracker[sig_mask].copy()

        for h in HORIZONS:
            completed_col = f"completed_{h}"
            ret_col = f"ret_fwd_{h}"

            if completed_col not in sig.columns or ret_col not in sig.columns:
                obs = pd.Series(dtype=float)
            else:
                comp = sig[completed_col].apply(to_bool_value) if sig[completed_col].dtype != bool else sig[completed_col].fillna(False)
                obs = pd.to_numeric(sig.loc[comp, ret_col], errors="coerce").dropna()

            rows.append({
                "signal": label,
                "horizon_days": h,
                "completed_obs": int(len(obs)),
                "avg_ret": round(float(obs.mean()), 6) if len(obs) else np.nan,
                "median_ret": round(float(obs.median()), 6) if len(obs) else np.nan,
                "win_rate": round(float((obs > 0).mean()), 6) if len(obs) else np.nan,
                "avg_win": round(float(obs[obs > 0].mean()), 6) if len(obs[obs > 0]) else np.nan,
                "avg_loss": round(float(obs[obs <= 0].mean()), 6) if len(obs[obs <= 0]) else np.nan,
            })

    return pd.DataFrame(rows)


def make_report(
    tracker: pd.DataFrame,
    summary: pd.DataFrame,
    current_rows: int,
    new_rows: int,
    out_report: Path,
    read_first: Path,
    tracker_path: Path,
    summary_path: Path,
):
    snapshot_dates = sorted(tracker["snapshot_price_date"].astype(str).dropna().unique().tolist())
    latest_date = snapshot_dates[-1] if snapshot_dates else ""

    completed_counts = {}
    for h in HORIZONS:
        col = f"completed_{h}"
        if col in tracker.columns:
            vals = tracker[col]
            comp = vals.apply(to_bool_value) if vals.dtype != bool else vals.fillna(False)
            completed_counts[h] = int(comp.sum())
        else:
            completed_counts[h] = 0

    def table(df):
        if df is None or df.empty:
            return "_EMPTY_"
        return df.to_markdown(index=False)

    md = f"""# V18.6C Technical Timing Forward Tracker

## 1. Status

- V18_6C_STATUS: `OK_TECHNICAL_TIMING_FORWARD_TRACKER_READY`
- CURRENT_SNAPSHOT_ROWS: `{current_rows}`
- NEW_TRACKER_ROWS_ADDED_OR_REFRESHED: `{new_rows}`
- TRACKER_TOTAL_ROWS: `{len(tracker)}`
- SNAPSHOT_DATE_COUNT: `{len(snapshot_dates)}`
- LATEST_SNAPSHOT_PRICE_DATE: `{latest_date}`
- COMPLETED_1D_COUNT: `{completed_counts.get(1, 0)}`
- COMPLETED_3D_COUNT: `{completed_counts.get(3, 0)}`
- COMPLETED_5D_COUNT: `{completed_counts.get(5, 0)}`
- COMPLETED_10D_COUNT: `{completed_counts.get(10, 0)}`
- COMPLETED_20D_COUNT: `{completed_counts.get(20, 0)}`
- OFFICIAL_DECISION_IMPACT: `NONE`

## 2. Purpose

This module tracks V18.6A technical timing signals forward.
It records the daily technical timing snapshot and later updates 1/3/5/10/20-day outcomes.

## 3. Signal Outcome Summary

{table(summary)}

## 4. Output Files

- TRACKER: `{tracker_path}`
- SUMMARY: `{summary_path}`

## 5. Interpretation

- Completed counts will be low at the beginning.
- Promotion is not allowed from this module until enough forward observations mature.
- `OFFICIAL_DECISION_IMPACT` remains `NONE`.
"""

    out_report.write_text(md, encoding="utf-8")

    rf = f"""V18.6C TECHNICAL TIMING FORWARD TRACKER READ FIRST

STATUS:
OK_TECHNICAL_TIMING_FORWARD_TRACKER_READY

LATEST_SNAPSHOT_PRICE_DATE:
{latest_date}

TRACKER_TOTAL_ROWS:
{len(tracker)}

SNAPSHOT_DATE_COUNT:
{len(snapshot_dates)}

COMPLETED_COUNTS:
1D={completed_counts.get(1, 0)}
3D={completed_counts.get(3, 0)}
5D={completed_counts.get(5, 0)}
10D={completed_counts.get(10, 0)}
20D={completed_counts.get(20, 0)}

OFFICIAL_DECISION_IMPACT:
NONE

READ:
{out_report}

TRACKER:
{tracker_path}

SUMMARY:
{summary_path}
"""
    read_first.write_text(rf, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()

    root = Path(args.root)

    current_path = root / "outputs" / "v18" / "technical_timing" / "V18_6A_CURRENT_TECHNICAL_TIMING.csv"
    state_dir = root / "state" / "v18"
    out_dir = root / "outputs" / "v18" / "technical_timing_forward"

    state_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    tracker_path = state_dir / "V18_6C_CURRENT_TECHNICAL_TIMING_FORWARD_TRACKER.csv"
    stamped_tracker_path = state_dir / f"V18_6C_TECHNICAL_TIMING_FORWARD_TRACKER_{stamp()}.csv"

    summary_path = out_dir / "V18_6C_CURRENT_TECHNICAL_TIMING_FORWARD_SUMMARY.csv"
    report_path = out_dir / "V18_6C_CURRENT_TECHNICAL_TIMING_FORWARD_REPORT.md"
    global_report_path = out_dir / "V18_CURRENT_TECHNICAL_TIMING_FORWARD.md"
    read_first_path = out_dir / "V18_6C_READ_FIRST.txt"

    current_raw = read_csv_safe(current_path)
    if current_raw.empty:
        raise RuntimeError(f"Missing or empty current V18.6A technical timing file: {current_path}")

    current = normalize_current_snapshot(current_raw)
    current_rows = len(current)

    existing = read_csv_safe(tracker_path)
    if existing.empty:
        combined = current.copy()
        existing_keys = set()
    else:
        existing_keys = set(zip(existing["snapshot_price_date"].astype(str), existing["ticker"].astype(str)))
        combined = pd.concat([existing, current], ignore_index=True, sort=False)

    new_keys = set(zip(current["snapshot_price_date"].astype(str), current["ticker"].astype(str)))
    new_rows = len(new_keys - existing_keys)

    combined["snapshot_price_date"] = combined["snapshot_price_date"].astype(str)
    combined["ticker"] = combined["ticker"].astype(str)
    combined = combined.drop_duplicates(subset=["snapshot_price_date", "ticker"], keep="last")
    combined = combined.sort_values(["snapshot_price_date", "ticker"]).reset_index(drop=True)

    updated = update_forward_outcomes(combined)
    summary = summarize_tracker(updated)

    write_csv(updated, tracker_path)
    write_csv(updated, stamped_tracker_path)
    write_csv(summary, summary_path)

    make_report(
        tracker=updated,
        summary=summary,
        current_rows=current_rows,
        new_rows=new_rows,
        out_report=report_path,
        read_first=read_first_path,
        tracker_path=tracker_path,
        summary_path=summary_path,
    )

    global_report_path.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")

    snapshot_dates = sorted(updated["snapshot_price_date"].astype(str).dropna().unique().tolist())
    latest_date = snapshot_dates[-1] if snapshot_dates else ""

    print("")
    print("=== V18.6C TECHNICAL TIMING FORWARD TRACKER READY ===")
    print(f"CURRENT_SNAPSHOT_ROWS: {current_rows}")
    print(f"NEW_TRACKER_ROWS_ADDED: {new_rows}")
    print(f"TRACKER_TOTAL_ROWS: {len(updated)}")
    print(f"SNAPSHOT_DATE_COUNT: {len(snapshot_dates)}")
    print(f"LATEST_SNAPSHOT_PRICE_DATE: {latest_date}")
    for h in HORIZONS:
        col = f"completed_{h}"
        vals = updated[col]
        comp = vals.apply(to_bool_value) if vals.dtype != bool else vals.fillna(False)
        print(f"COMPLETED_{h}D_COUNT: {int(comp.sum())}")
    print("OFFICIAL_DECISION_IMPACT: NONE")
    print(f"TRACKER: {tracker_path}")
    print(f"SUMMARY: {summary_path}")
    print(f"REPORT: {report_path}")
    print(f"READ_FIRST: {read_first_path}")


if __name__ == "__main__":
    main()
