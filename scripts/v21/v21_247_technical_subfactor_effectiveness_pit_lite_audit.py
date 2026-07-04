#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

STAGE = "V21.247_TECHNICAL_SUBFACTOR_EFFECTIVENESS_PIT_LITE_AUDIT"
OUT_REL = Path("outputs/v21") / STAGE
DEFAULT_INPUT_REL = Path("outputs/v21/V21.246_TECHNICAL_AND_FORWARD_PANEL_BUILD_FROM_MOOMOO_CACHE_R1")
PROVIDER = "MOOMOO"
HORIZONS = ["1D", "5D", "10D", "20D"]
REGIMES = ["FULL_SAMPLE", "PRE_20260616", "POST_20260616_TO_NOW", "RANDOM_START_TO_NOW", "HIGH_VOL", "LOW_VOL", "MOMENTUM_UP", "MOMENTUM_DOWN"]
MIN_IC_NAMES = 10
MIN_BUCKET_NAMES = 20


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n", encoding="utf-8")


def read_summary(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def discover_panel(input_root: Path) -> Path | None:
    candidates = [input_root / "technical_forward_join_panel.csv"]
    candidates.extend(sorted(input_root.glob("*technical*forward*join*.csv")))
    for p in candidates:
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename = {}
    lower = {str(c).strip().lower(): c for c in df.columns}
    aliases = {
        "ticker": ["ticker", "symbol"],
        "asof_date": ["asof_date", "date", "ranking_date"],
        "technical_subfactor_name": ["technical_subfactor_name", "technical_indicator", "indicator_name", "subfactor_name"],
        "technical_group": ["technical_group", "indicator_group", "subfactor_group"],
        "raw_value": ["raw_value", "technical_indicator_value", "indicator_value", "value"],
        "rank_pct_by_date": ["rank_pct_by_date", "rank_pct", "rank_percentile"],
        "forward_return_1d": ["forward_return_1d", "forward_1d_return", "return_1d"],
        "forward_return_5d": ["forward_return_5d", "forward_5d_return", "return_5d"],
        "forward_return_10d": ["forward_return_10d", "forward_10d_return", "return_10d"],
        "forward_return_20d": ["forward_return_20d", "forward_20d_return", "return_20d"],
        "maturity_1d": ["maturity_1d", "matured_1d"],
        "maturity_5d": ["maturity_5d", "matured_5d"],
        "maturity_10d": ["maturity_10d", "matured_10d"],
        "maturity_20d": ["maturity_20d", "matured_20d"],
    }
    for target, opts in aliases.items():
        for o in opts:
            if o in lower:
                rename[lower[o]] = target
                break
    df = df.rename(columns=rename)
    if "technical_group" not in df:
        df["technical_group"] = ""
    if "rank_pct_by_date" not in df:
        df["rank_pct_by_date"] = pd.NA
    for h in HORIZONS:
        m = f"maturity_{h.lower()}"
        if m not in df:
            df[m] = df[f"forward_return_{h.lower()}"].notna() if f"forward_return_{h.lower()}" in df else False
    return df


def required_columns_present(df: pd.DataFrame) -> tuple[bool, list[str]]:
    required = ["ticker", "asof_date", "technical_subfactor_name", "raw_value"] + [f"forward_return_{h.lower()}" for h in HORIZONS]
    missing = [c for c in required if c not in df.columns]
    return not missing, missing


def load_panel(path: Path) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0)
    header = normalize_columns(header)
    ok, missing = required_columns_present(header)
    if not ok:
        raise ValueError(f"required columns missing: {missing}")
    cols = ["ticker", "asof_date", "technical_subfactor_name", "technical_group", "raw_value", "rank_pct_by_date"]
    for h in HORIZONS:
        cols.extend([f"forward_return_{h.lower()}", f"maturity_{h.lower()}"])
    raw_header = pd.read_csv(path, nrows=0)
    normalized = normalize_columns(raw_header.copy())
    reverse = {new: old for old, new in zip(raw_header.columns, normalized.columns)}
    usecols = [reverse.get(c, c) for c in cols if reverse.get(c, c) in raw_header.columns]
    df = pd.read_csv(path, usecols=usecols)
    df = normalize_columns(df)
    for c in ["raw_value", "rank_pct_by_date"] + [f"forward_return_{h.lower()}" for h in HORIZONS]:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    for h in HORIZONS:
        m = f"maturity_{h.lower()}"
        df[m] = df[m].astype(str).str.lower().isin({"true", "1", "yes"})
    df["asof_date"] = pd.to_datetime(df["asof_date"], errors="coerce")
    df = df[df["asof_date"].notna()].copy()
    df["asof_date"] = df["asof_date"].dt.strftime("%Y-%m-%d")
    return df


def load_wide_forward(input_root: Path) -> pd.DataFrame | None:
    wide_path = input_root / "technical_subfactor_panel_wide.csv"
    fwd_path = input_root / "forward_return_panel_aligned.csv"
    if not wide_path.exists() or not fwd_path.exists():
        return None
    wide_head = pd.read_csv(wide_path, nrows=0)
    base = ["asof_date", "ticker", "price_type", "provider"]
    indicators = [c for c in wide_head.columns if c not in set(base + ["source_cache_file", "close", "volume"])]
    wide = pd.read_csv(wide_path, usecols=base + indicators)
    fwd_cols = ["asof_date", "ticker"]
    for h in HORIZONS:
        fwd_cols.extend([f"forward_return_{h.lower()}", f"maturity_{h.lower()}"])
    fwd = pd.read_csv(fwd_path, usecols=lambda c: c in fwd_cols)
    df = wide.merge(fwd, on=["asof_date", "ticker"], how="left")
    for c in indicators + [f"forward_return_{h.lower()}" for h in HORIZONS]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for h in HORIZONS:
        m = f"maturity_{h.lower()}"
        df[m] = df[m].astype(str).str.lower().isin({"true", "1", "yes"})
    df["asof_date"] = pd.to_datetime(df["asof_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df.attrs["indicator_columns"] = indicators
    return df


def corr(x: pd.Series, y: pd.Series) -> float:
    if len(x) < 3 or x.nunique(dropna=True) < 2 or y.nunique(dropna=True) < 2:
        return math.nan
    return float(x.corr(y, method="pearson"))


def rank_corr(x: pd.Series, y: pd.Series) -> float:
    if len(x) < 3 or x.nunique(dropna=True) < 2 or y.nunique(dropna=True) < 2:
        return math.nan
    return float(x.rank().corr(y.rank(), method="pearson"))


def bucket_for_group(g: pd.DataFrame, ret_col: str) -> tuple[list[dict[str, Any]], int, float, float, float]:
    if len(g) < MIN_BUCKET_NAMES or g["raw_value"].nunique(dropna=True) < 5:
        return [], 1, math.nan, math.nan, math.nan
    try:
        work = g.copy()
        work["bucket"] = pd.qcut(work["raw_value"], 5, labels=False, duplicates="drop") + 1
    except Exception:
        return [], 1, math.nan, math.nan, math.nan
    if work["bucket"].nunique() < 5:
        return [], 1, math.nan, math.nan, math.nan
    means = work.groupby("bucket", observed=True)[ret_col].mean().to_dict()
    rows = [{"bucket": int(b), "bucket_forward_return": float(v), "bucket_count": int((work["bucket"] == b).sum())} for b, v in means.items()]
    top = float(means.get(5, math.nan))
    bottom = float(means.get(1, math.nan))
    vals = [means.get(i, math.nan) for i in range(1, 6)]
    monotonic = sum(1 for a, b in zip(vals, vals[1:]) if pd.notna(a) and pd.notna(b) and b >= a) / 4.0
    return rows, 0, top, bottom, monotonic


def date_regime_map(df: pd.DataFrame) -> dict[str, set[str]]:
    dates = sorted(df["asof_date"].dropna().unique())
    if "technical_subfactor_name" in df.columns:
        vol = df[df["technical_subfactor_name"].eq("VOLATILITY_20")].groupby("asof_date")["raw_value"].median()
    elif "VOLATILITY_20" in df.columns:
        vol = df.groupby("asof_date")["VOLATILITY_20"].median()
    else:
        vol = pd.Series(dtype=float)
    if vol.empty:
        vol = df.groupby("asof_date")["forward_return_20d"].std()
    if "technical_subfactor_name" in df.columns:
        mom = df[df["technical_subfactor_name"].eq("MOMENTUM_20")].groupby("asof_date")["raw_value"].median()
    elif "MOMENTUM_20" in df.columns:
        mom = df.groupby("asof_date")["MOMENTUM_20"].median()
    else:
        mom = pd.Series(dtype=float)
    if mom.empty:
        mom = df.groupby("asof_date")["forward_return_20d"].median()
    random_start = dates[len(dates) // 3] if dates else ""
    return {
        "FULL_SAMPLE": set(dates),
        "PRE_20260616": {d for d in dates if d < "2026-06-16"},
        "POST_20260616_TO_NOW": {d for d in dates if d >= "2026-06-16"},
        "RANDOM_START_TO_NOW": {d for d in dates if d >= random_start},
        "HIGH_VOL": set(vol[vol >= vol.median()].index.astype(str)) if not vol.empty else set(),
        "LOW_VOL": set(vol[vol <= vol.median()].index.astype(str)) if not vol.empty else set(),
        "MOMENTUM_UP": set(mom[mom >= mom.median()].index.astype(str)) if not mom.empty else set(),
        "MOMENTUM_DOWN": set(mom[mom <= mom.median()].index.astype(str)) if not mom.empty else set(),
    }


def compute_effectiveness_wide(df: pd.DataFrame, indicators: list[str], regime_dates: dict[str, set[str]], regime_name: str = "FULL_SAMPLE") -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    dates_allowed = regime_dates.get(regime_name, set(df["asof_date"].unique()))
    data = df[df["asof_date"].isin(dates_allowed)].copy()
    master, ts_rows, bucket_rows = [], [], []
    total_possible = max(1, len(data))
    for indicator in sorted(indicators):
        group_name = group_for_indicator(indicator)
        ind_df = data[["asof_date", "ticker", indicator] + [f"forward_return_{h.lower()}" for h in HORIZONS] + [f"maturity_{h.lower()}" for h in HORIZONS]].rename(columns={indicator: "raw_value"})
        for h in HORIZONS:
            ret_col = f"forward_return_{h.lower()}"
            mat_col = f"maturity_{h.lower()}"
            daily_ics, daily_rics = [], []
            bucket_top, bucket_bottom, monotonic_scores = [], [], []
            skipped_bucket = 0
            obs_count = 0
            for asof, g0 in ind_df.groupby("asof_date", sort=True):
                g = g0[g0[mat_col] & g0["raw_value"].notna() & g0[ret_col].notna()][["ticker", "raw_value", ret_col]]
                if len(g) < MIN_IC_NAMES:
                    if len(g) > 0:
                        skipped_bucket += 1
                    continue
                ic = corr(g["raw_value"], g[ret_col])
                ric = rank_corr(g["raw_value"], g[ret_col])
                if pd.notna(ic):
                    daily_ics.append(ic)
                if pd.notna(ric):
                    daily_rics.append(ric)
                obs_count += len(g)
                ts_rows.append({"asof_date": asof, "technical_indicator": indicator, "forward_horizon": h, "observation_count": len(g), "ic": ic, "rank_ic": ric, "regime": regime_name})
                b_rows, skipped, top, bottom, mono = bucket_for_group(g, ret_col)
                skipped_bucket += skipped
                if b_rows:
                    bucket_top.append(top)
                    bucket_bottom.append(bottom)
                    monotonic_scores.append(mono)
                    for br in b_rows:
                        bucket_rows.append({"technical_indicator": indicator, "technical_group": group_name, "forward_horizon": h, "asof_date": asof, "bucket": br["bucket"], "bucket_forward_return": br["bucket_forward_return"], "bucket_count": br["bucket_count"], "regime": regime_name})
            mean_ic = float(pd.Series(daily_ics).mean()) if daily_ics else math.nan
            med_ic = float(pd.Series(daily_ics).median()) if daily_ics else math.nan
            pos_ic = float((pd.Series(daily_ics) > 0).mean()) if daily_ics else math.nan
            mean_ric = float(pd.Series(daily_rics).mean()) if daily_rics else math.nan
            med_ric = float(pd.Series(daily_rics).median()) if daily_rics else math.nan
            pos_ric = float((pd.Series(daily_rics) > 0).mean()) if daily_rics else math.nan
            top = float(pd.Series(bucket_top).mean()) if bucket_top else math.nan
            bottom = float(pd.Series(bucket_bottom).mean()) if bucket_bottom else math.nan
            mono = float(pd.Series(monotonic_scores).mean()) if monotonic_scores else math.nan
            master.append({"technical_indicator": indicator, "technical_group": group_name, "forward_horizon": h, "regime": regime_name, "observation_count": obs_count, "ticker_count": int(ind_df["ticker"].nunique()), "asof_count": len(daily_ics), "mean_ic": mean_ic, "median_ic": med_ic, "positive_ic_ratio": pos_ic, "mean_rank_ic": mean_ric, "median_rank_ic": med_ric, "positive_rank_ic_ratio": pos_ric, "top_bucket_forward_return": top, "bottom_bucket_forward_return": bottom, "top_minus_bottom_return": top - bottom if pd.notna(top) and pd.notna(bottom) else math.nan, "monotonicity_score": mono, "coverage_ratio": obs_count / total_possible, "bucket_skipped_date_count": skipped_bucket, "effectiveness_label": effectiveness_label(mean_ric, pos_ric, mono if pd.notna(mono) else 0, obs_count)})
    return master, ts_rows, bucket_rows


def group_for_indicator(indicator: str) -> str:
    if indicator.startswith("RSI"):
        return "RSI"
    if indicator.startswith("KDJ"):
        return "KDJ"
    if indicator.startswith("MACD"):
        return "MACD"
    if indicator.startswith("BB"):
        return "BOLLINGER_BANDS"
    if indicator.startswith(("MA", "EMA")):
        return "MOVING_AVERAGE"
    if indicator.startswith("VOLUME"):
        return "VOLUME"
    if indicator.startswith("VOLATILITY"):
        return "VOLATILITY"
    if indicator.startswith("MOMENTUM"):
        return "MOMENTUM"
    if indicator.startswith("RELATIVE"):
        return "RELATIVE_STRENGTH"
    if indicator.startswith(("BREAKOUT", "PULLBACK")):
        return "BREAKOUT_PULLBACK"
    if indicator.startswith("DISTANCE"):
        return "PRICE_DISTANCE"
    return ""


def redundancy_audit_wide(df: pd.DataFrame, indicators: list[str]) -> list[dict[str, Any]]:
    rows = []
    for i, a in enumerate(sorted(indicators)):
        for b in sorted(indicators)[i + 1:]:
            pair = df[[a, b]].dropna()
            if len(pair) < 100:
                pc = sc = math.nan
            else:
                pc = float(pair[a].corr(pair[b], method="pearson"))
                sc = float(pair[a].rank().corr(pair[b].rank(), method="pearson"))
            abs_sc = abs(sc) if pd.notna(sc) else 0
            label = "HIGH_REDUNDANCY" if abs_sc >= 0.85 else "MEDIUM_REDUNDANCY" if abs_sc >= 0.65 else "LOW_REDUNDANCY"
            rows.append({"indicator_a": a, "indicator_b": b, "pearson_corr": pc, "spearman_corr": sc, "redundancy_label": label})
    return rows


def effectiveness_label(mean_rank_ic: float, pos_ratio: float, monotonicity: float, obs: int) -> str:
    if obs < 1000:
        return "INSUFFICIENT_DATA"
    if pd.notna(mean_rank_ic) and mean_rank_ic > 0.03 and pos_ratio >= 0.55 and monotonicity >= 0.55:
        return "POSITIVE_PIT_LITE_SIGNAL"
    if pd.notna(mean_rank_ic) and mean_rank_ic < -0.03 and pos_ratio <= 0.45:
        return "NEGATIVE_OR_INVERSE_SIGNAL"
    return "MIXED_OR_WEAK_SIGNAL"


def compute_effectiveness(df: pd.DataFrame, regime_dates: dict[str, set[str]], regime_name: str = "FULL_SAMPLE") -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    dates_allowed = regime_dates.get(regime_name, set(df["asof_date"].unique()))
    data = df[df["asof_date"].isin(dates_allowed)].copy()
    master, ts_rows, bucket_rows = [], [], []
    total_possible = max(1, len(data))
    for indicator, ind_df in data.groupby("technical_subfactor_name", sort=True):
        group_name = str(ind_df["technical_group"].dropna().iloc[0]) if "technical_group" in ind_df and ind_df["technical_group"].notna().any() else ""
        for h in HORIZONS:
            ret_col = f"forward_return_{h.lower()}"
            mat_col = f"maturity_{h.lower()}"
            daily_ics, daily_rics = [], []
            bucket_top, bucket_bottom, monotonic_scores = [], [], []
            skipped_bucket = 0
            obs_count = 0
            for asof, g0 in ind_df.groupby("asof_date", sort=True):
                g = g0[g0[mat_col] & g0["raw_value"].notna() & g0[ret_col].notna()][["ticker", "raw_value", ret_col]]
                if len(g) < MIN_IC_NAMES:
                    if len(g) > 0:
                        skipped_bucket += 1
                    continue
                ic = corr(g["raw_value"], g[ret_col])
                ric = rank_corr(g["raw_value"], g[ret_col])
                if pd.notna(ic):
                    daily_ics.append(ic)
                if pd.notna(ric):
                    daily_rics.append(ric)
                obs_count += len(g)
                ts_rows.append({"asof_date": asof, "technical_indicator": indicator, "forward_horizon": h, "observation_count": len(g), "ic": ic, "rank_ic": ric, "regime": regime_name})
                b_rows, skipped, top, bottom, mono = bucket_for_group(g, ret_col)
                skipped_bucket += skipped
                if b_rows:
                    bucket_top.append(top)
                    bucket_bottom.append(bottom)
                    monotonic_scores.append(mono)
                    for br in b_rows:
                        bucket_rows.append({"technical_indicator": indicator, "technical_group": group_name, "forward_horizon": h, "asof_date": asof, "bucket": br["bucket"], "bucket_forward_return": br["bucket_forward_return"], "bucket_count": br["bucket_count"], "regime": regime_name})
            mean_ic = float(pd.Series(daily_ics).mean()) if daily_ics else math.nan
            med_ic = float(pd.Series(daily_ics).median()) if daily_ics else math.nan
            pos_ic = float((pd.Series(daily_ics) > 0).mean()) if daily_ics else math.nan
            mean_ric = float(pd.Series(daily_rics).mean()) if daily_rics else math.nan
            med_ric = float(pd.Series(daily_rics).median()) if daily_rics else math.nan
            pos_ric = float((pd.Series(daily_rics) > 0).mean()) if daily_rics else math.nan
            top = float(pd.Series(bucket_top).mean()) if bucket_top else math.nan
            bottom = float(pd.Series(bucket_bottom).mean()) if bucket_bottom else math.nan
            mono = float(pd.Series(monotonic_scores).mean()) if monotonic_scores else math.nan
            master.append({"technical_indicator": indicator, "technical_group": group_name, "forward_horizon": h, "regime": regime_name, "observation_count": obs_count, "ticker_count": int(ind_df["ticker"].nunique()), "asof_count": len(daily_ics), "mean_ic": mean_ic, "median_ic": med_ic, "positive_ic_ratio": pos_ic, "mean_rank_ic": mean_ric, "median_rank_ic": med_ric, "positive_rank_ic_ratio": pos_ric, "top_bucket_forward_return": top, "bottom_bucket_forward_return": bottom, "top_minus_bottom_return": top - bottom if pd.notna(top) and pd.notna(bottom) else math.nan, "monotonicity_score": mono, "coverage_ratio": obs_count / total_possible, "bucket_skipped_date_count": skipped_bucket, "effectiveness_label": effectiveness_label(mean_ric, pos_ric, mono if pd.notna(mono) else 0, obs_count)})
    return master, ts_rows, bucket_rows


def redundancy_audit(df: pd.DataFrame) -> list[dict[str, Any]]:
    pivot = df.pivot_table(index=["asof_date", "ticker"], columns="technical_subfactor_name", values="raw_value", aggfunc="mean")
    cols = sorted(pivot.columns)
    rows = []
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            pair = pivot[[a, b]].dropna()
            if len(pair) < 100:
                pc = sc = math.nan
            else:
                pc = float(pair[a].corr(pair[b], method="pearson"))
                sc = float(pair[a].rank().corr(pair[b].rank(), method="pearson"))
            abs_sc = abs(sc) if pd.notna(sc) else 0
            label = "HIGH_REDUNDANCY" if abs_sc >= 0.85 else "MEDIUM_REDUNDANCY" if abs_sc >= 0.65 else "LOW_REDUNDANCY"
            rows.append({"indicator_a": a, "indicator_b": b, "pearson_corr": pc, "spearman_corr": sc, "redundancy_label": label})
    return rows


def candidate_rows(master: list[dict[str, Any]], redundancy: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_ind: dict[str, list[dict[str, Any]]] = {}
    for r in master:
        if r["regime"] == "FULL_SAMPLE":
            by_ind.setdefault(r["technical_indicator"], []).append(r)
    high = {r["indicator_a"] for r in redundancy if r["redundancy_label"] == "HIGH_REDUNDANCY"} | {r["indicator_b"] for r in redundancy if r["redundancy_label"] == "HIGH_REDUNDANCY"}
    out = []
    for ind, rows in sorted(by_ind.items()):
        best = max(rows, key=lambda r: (abs(r["mean_rank_ic"]) if pd.notna(r["mean_rank_ic"]) else -1, r["observation_count"]))
        stable = "STABLE_POSITIVE" if best["mean_rank_ic"] > 0.03 and best["positive_rank_ic_ratio"] >= 0.55 else "STABLE_INVERSE" if best["mean_rank_ic"] < -0.03 and best["positive_rank_ic_ratio"] <= 0.45 else "MIXED"
        red = "HIGH_REDUNDANCY" if ind in high else "LOW_OR_MEDIUM_REDUNDANCY"
        cand = stable != "MIXED" and red != "HIGH_REDUNDANCY"
        out.append({"technical_indicator": ind, "candidate_for_v21_248": cand, "reason": f"best_mean_rank_ic={best['mean_rank_ic']}; label={best['effectiveness_label']}", "best_forward_horizon": best["forward_horizon"], "best_regime": best["regime"], "stability_label": stable, "redundancy_risk_label": red, "promotion_allowed": False})
    return out


def regime_rows_from_timeseries(ts_rows: list[dict[str, Any]], master_full: list[dict[str, Any]], regime_dates: dict[str, set[str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    by_meta = {(r["technical_indicator"], r["forward_horizon"]): r for r in master_full if r["regime"] == "FULL_SAMPLE"}
    ts = pd.DataFrame(ts_rows)
    if ts.empty:
        return out
    for regime, dates in regime_dates.items():
        sub = ts[ts["asof_date"].isin(dates)]
        for (indicator, horizon), g in sub.groupby(["technical_indicator", "forward_horizon"], sort=True):
            meta = by_meta.get((indicator, horizon), {})
            ic = pd.to_numeric(g["ic"], errors="coerce").dropna()
            ric = pd.to_numeric(g["rank_ic"], errors="coerce").dropna()
            obs = pd.to_numeric(g["observation_count"], errors="coerce").fillna(0)
            mean_ric = float(ric.mean()) if len(ric) else math.nan
            pos_ric = float((ric > 0).mean()) if len(ric) else math.nan
            out.append({
                "technical_indicator": indicator,
                "technical_group": meta.get("technical_group", group_for_indicator(indicator)),
                "forward_horizon": horizon,
                "regime": regime,
                "observation_count": int(obs.sum()),
                "ticker_count": meta.get("ticker_count", 0),
                "asof_count": int(g["asof_date"].nunique()),
                "mean_ic": float(ic.mean()) if len(ic) else math.nan,
                "median_ic": float(ic.median()) if len(ic) else math.nan,
                "positive_ic_ratio": float((ic > 0).mean()) if len(ic) else math.nan,
                "mean_rank_ic": mean_ric,
                "median_rank_ic": float(ric.median()) if len(ric) else math.nan,
                "positive_rank_ic_ratio": pos_ric,
                "top_bucket_forward_return": math.nan,
                "bottom_bucket_forward_return": math.nan,
                "top_minus_bottom_return": math.nan,
                "monotonicity_score": math.nan,
                "coverage_ratio": int(obs.sum()) / max(1, int(meta.get("observation_count") or 1)),
                "bucket_skipped_date_count": 0,
                "effectiveness_label": effectiveness_label(mean_ric, pos_ric, 0, int(obs.sum())),
            })
    return out


def write_outputs(out: Path, master: list[dict[str, Any]], by_regime: list[dict[str, Any]], buckets: list[dict[str, Any]], ts: list[dict[str, Any]], redundancy: list[dict[str, Any]], candidates: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    master_fields = ["technical_indicator", "technical_group", "forward_horizon", "regime", "observation_count", "ticker_count", "asof_count", "mean_ic", "median_ic", "positive_ic_ratio", "mean_rank_ic", "median_rank_ic", "positive_rank_ic_ratio", "top_bucket_forward_return", "bottom_bucket_forward_return", "top_minus_bottom_return", "monotonicity_score", "coverage_ratio", "bucket_skipped_date_count", "effectiveness_label"]
    write_csv(out / "technical_subfactor_effectiveness_master.csv", [r for r in master if r["regime"] == "FULL_SAMPLE"], master_fields)
    write_csv(out / "technical_subfactor_effectiveness_by_regime.csv", by_regime, master_fields)
    write_csv(out / "technical_subfactor_bucket_returns.csv", buckets, ["technical_indicator", "technical_group", "forward_horizon", "asof_date", "bucket", "bucket_forward_return", "bucket_count", "regime"])
    write_csv(out / "technical_subfactor_ic_timeseries.csv", ts, ["asof_date", "technical_indicator", "forward_horizon", "observation_count", "ic", "rank_ic", "regime"])
    write_csv(out / "technical_subfactor_redundancy_audit.csv", redundancy, ["indicator_a", "indicator_b", "pearson_corr", "spearman_corr", "redundancy_label"])
    write_csv(out / "technical_subfactor_candidate_for_v21_248.csv", candidates, ["technical_indicator", "candidate_for_v21_248", "reason", "best_forward_horizon", "best_regime", "stability_label", "redundancy_risk_label", "promotion_allowed"])
    write_json(out / "v21_247_summary.json", summary)
    (out / "V21.247_technical_subfactor_effectiveness_report.txt").write_text(
        f"{STAGE}\nfinal_status={summary['final_status']}\nfinal_decision={summary['final_decision']}\nprovider=MOOMOO\nresearch_only=True\nofficial_adoption_allowed=False\nbroker_action_allowed=False\nfactor_promotion_allowed=False\nweight_update_allowed=False\nranking_mutation_allowed=False\n",
        encoding="utf-8",
    )


def run(repo: Path, input_root: Path | None = None, output_dir: Path | None = None) -> dict[str, Any]:
    inp = input_root or repo / DEFAULT_INPUT_REL
    if not inp.is_absolute():
        inp = repo / inp
    out = output_dir or repo / OUT_REL
    panel = discover_panel(inp)
    wide_df = load_wide_forward(inp)
    if panel is None and wide_df is None:
        summary = fail_summary(inp, out, "joined panel not found")
        write_outputs(out, [], [], [], [], [], [], summary)
        return summary
    try:
        source_summary = read_summary(inp / "v21_246_summary.json")
        if wide_df is not None:
            df = wide_df
            indicators = sorted(df.attrs.get("indicator_columns", []))
            regime_dates = date_regime_map(df)
            full, ts, buckets = compute_effectiveness_wide(df, indicators, regime_dates, "FULL_SAMPLE")
            by_regime = regime_rows_from_timeseries(ts, full, regime_dates)
            redundancy = redundancy_audit_wide(df, indicators)
            total_obs = int(df[indicators].notna().sum().sum()) if indicators else 0
        else:
            df = load_panel(panel)
            indicators = sorted(df["technical_subfactor_name"].dropna().unique())
            regime_dates = date_regime_map(df)
            full, ts, buckets = compute_effectiveness(df, regime_dates, "FULL_SAMPLE")
            by_regime = regime_rows_from_timeseries(ts, full, regime_dates)
            redundancy = redundancy_audit(df)
            total_obs = int(df["raw_value"].notna().sum())
        candidates = candidate_rows(full, redundancy)
        tested_h = sorted({r["forward_horizon"] for r in full})
        signal_mixed = any(r["effectiveness_label"] == "MIXED_OR_WEAK_SIGNAL" for r in full)
        insufficient = any(r["effectiveness_label"] == "INSUFFICIENT_DATA" for r in full)
        expected_count = int(source_summary.get("technical_indicator_count") or 27)
        if len(indicators) >= expected_count and len(tested_h) == 4 and not insufficient and not signal_mixed:
            status = "PASS_V21_247_TECHNICAL_EFFECTIVENESS_AUDIT_READY"
            decision = "TECHNICAL_EFFECTIVENESS_AUDIT_READY_FOR_V21_248_RESEARCH_ONLY"
        elif insufficient:
            status = "WARN_V21_247_TECHNICAL_EFFECTIVENESS_INSUFFICIENT_FORWARD_MATURITY"
            decision = "TECHNICAL_EFFECTIVENESS_AUDIT_LIMITED_BY_FORWARD_MATURITY"
        else:
            status = "PARTIAL_PASS_V21_247_TECHNICAL_EFFECTIVENESS_SIGNAL_MIXED"
            decision = "TECHNICAL_EFFECTIVENESS_AUDIT_READY_WITH_MIXED_SIGNALS"
        summary = {"final_status": status, "final_decision": decision, "input_root": str(inp), "output_root": str(out), "provider": PROVIDER, "source_version": "V21.246", "technical_indicator_count": len(indicators), "forward_horizon_count": 4, "tested_indicator_count": len({r["technical_indicator"] for r in full}), "tested_horizon_count": len(tested_h), "total_observation_count": total_obs, "total_ic_rows": len(ts), "total_bucket_rows": len(buckets), "total_regime_rows": len(by_regime), "redundancy_pair_count": len(redundancy), "high_redundancy_pair_count": sum(1 for r in redundancy if r["redundancy_label"] == "HIGH_REDUNDANCY"), "candidate_for_v21_248_count": sum(1 for r in candidates if r["candidate_for_v21_248"]), "official_adoption_allowed": False, "broker_action_allowed": False, "factor_promotion_allowed": False, "weight_update_allowed": False, "ranking_mutation_allowed": False}
        write_outputs(out, full, by_regime, buckets, ts, redundancy, candidates, summary)
        return summary
    except Exception as exc:
        summary = fail_summary(inp, out, repr(exc))
        write_outputs(out, [], [], [], [], [], [], summary)
        return summary


def fail_summary(inp: Path, out: Path, reason: str) -> dict[str, Any]:
    return {"final_status": "FAIL_V21_247_TECHNICAL_EFFECTIVENESS_AUDIT_BLOCKED", "final_decision": f"TECHNICAL_EFFECTIVENESS_AUDIT_BLOCKED: {reason}", "input_root": str(inp), "output_root": str(out), "provider": PROVIDER, "source_version": "V21.246", "technical_indicator_count": 0, "forward_horizon_count": 0, "tested_indicator_count": 0, "tested_horizon_count": 0, "total_observation_count": 0, "total_ic_rows": 0, "total_bucket_rows": 0, "total_regime_rows": 0, "redundancy_pair_count": 0, "high_redundancy_pair_count": 0, "candidate_for_v21_248_count": 0, "official_adoption_allowed": False, "broker_action_allowed": False, "factor_promotion_allowed": False, "weight_update_allowed": False, "ranking_mutation_allowed": False}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_REL)
    p.add_argument("--output-dir", type=Path)
    a = p.parse_args(argv)
    s = run(a.repo_root.resolve(), a.input_root, a.output_dir)
    for k in ["final_status", "final_decision", "technical_indicator_count", "tested_indicator_count", "tested_horizon_count", "total_ic_rows", "total_bucket_rows", "candidate_for_v21_248_count", "official_adoption_allowed", "broker_action_allowed", "factor_promotion_allowed", "weight_update_allowed", "ranking_mutation_allowed", "output_root"]:
        print(f"{k}={s.get(k)}")
    return 1 if str(s.get("final_status")) == "FAIL_V21_247_TECHNICAL_EFFECTIVENESS_AUDIT_BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
