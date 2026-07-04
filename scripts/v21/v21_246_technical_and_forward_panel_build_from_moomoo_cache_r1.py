#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

NAN = float("nan")

STAGE = "V21.246_TECHNICAL_AND_FORWARD_PANEL_BUILD_FROM_MOOMOO_CACHE_R1"
OUT_REL = Path("outputs/v21") / STAGE
DEFAULT_CACHE_ROOT = Path(r"D:\us-tech-quant-cache")
DEFAULT_R1A_REL = Path("outputs/v21/V21.245_R1A_MOOMOO_CACHE_CURRENTNESS_AND_FAILURE_TRIAGE")
PROVIDER = "MOOMOO"
BASE_COLS = ["date", "ticker", "moomoo_symbol", "open", "high", "low", "close", "volume", "turnover", "price_type", "provider"]
INDICATORS = [
    ("RSI_14", "RSI", 14, "ENTRY_TIMING_ONLY_RESEARCH_ONLY"),
    ("KDJ_K_9_3_3", "KDJ", 9, "ENTRY_TIMING_ONLY_RESEARCH_ONLY"),
    ("KDJ_D_9_3_3", "KDJ", 9, "ENTRY_TIMING_ONLY_RESEARCH_ONLY"),
    ("KDJ_J_9_3_3", "KDJ", 9, "ENTRY_TIMING_ONLY_RESEARCH_ONLY"),
    ("MACD_DIF_12_26", "MACD", 26, "CONFIRMATION_SIGNAL_RESEARCH_ONLY"),
    ("MACD_DEA_9", "MACD", 35, "CONFIRMATION_SIGNAL_RESEARCH_ONLY"),
    ("MACD_HIST_12_26_9", "MACD", 35, "CONFIRMATION_SIGNAL_RESEARCH_ONLY"),
    ("BB_MID_20", "BOLLINGER_BANDS", 20, "ENTRY_TIMING_ONLY_RESEARCH_ONLY"),
    ("BB_UPPER_20_2", "BOLLINGER_BANDS", 20, "ENTRY_TIMING_ONLY_RESEARCH_ONLY"),
    ("BB_LOWER_20_2", "BOLLINGER_BANDS", 20, "ENTRY_TIMING_ONLY_RESEARCH_ONLY"),
    ("BB_WIDTH_20", "BOLLINGER_BANDS", 20, "RISK_FILTER_RESEARCH_ONLY"),
    ("BB_PCTB_20", "BOLLINGER_BANDS", 20, "ENTRY_TIMING_ONLY_RESEARCH_ONLY"),
    ("MA20", "MOVING_AVERAGE", 20, "CONFIRMATION_SIGNAL_RESEARCH_ONLY"),
    ("MA50", "MOVING_AVERAGE", 50, "CONFIRMATION_SIGNAL_RESEARCH_ONLY"),
    ("EMA12", "MOVING_AVERAGE", 12, "CONFIRMATION_SIGNAL_RESEARCH_ONLY"),
    ("EMA26", "MOVING_AVERAGE", 26, "CONFIRMATION_SIGNAL_RESEARCH_ONLY"),
    ("EMA50", "MOVING_AVERAGE", 50, "CONFIRMATION_SIGNAL_RESEARCH_ONLY"),
    ("VOLUME_MA20", "VOLUME", 20, "CONFIRMATION_SIGNAL_RESEARCH_ONLY"),
    ("VOLUME_RATIO_20", "VOLUME", 20, "CONFIRMATION_SIGNAL_RESEARCH_ONLY"),
    ("VOLATILITY_20", "VOLATILITY", 20, "RISK_FILTER_RESEARCH_ONLY"),
    ("MOMENTUM_20", "MOMENTUM", 20, "PRIMARY_ALPHA_CANDIDATE_RESEARCH_ONLY"),
    ("MOMENTUM_60", "MOMENTUM", 60, "PRIMARY_ALPHA_CANDIDATE_RESEARCH_ONLY"),
    ("RELATIVE_STRENGTH_20_VS_QQQ", "RELATIVE_STRENGTH", 20, "CONFIRMATION_SIGNAL_RESEARCH_ONLY"),
    ("BREAKOUT_20", "BREAKOUT_PULLBACK", 20, "ENTRY_TIMING_ONLY_RESEARCH_ONLY"),
    ("PULLBACK_FROM_20D_HIGH", "BREAKOUT_PULLBACK", 20, "ENTRY_TIMING_ONLY_RESEARCH_ONLY"),
    ("DISTANCE_TO_MA20", "PRICE_DISTANCE", 20, "ENTRY_TIMING_ONLY_RESEARCH_ONLY"),
    ("DISTANCE_TO_MA50", "PRICE_DISTANCE", 50, "ENTRY_TIMING_ONLY_RESEARCH_ONLY"),
]


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def cache_file(cache_root: Path, ticker: str, price_type: str) -> Path:
    return cache_root / "market_data/moomoo/daily" / ("qfq" if price_type == "QFQ_DAILY" else "raw") / f"{ticker}.csv"


def load_r1a(repo: Path, root_arg: Path) -> tuple[Path, dict[str, Any], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    root = root_arg if root_arg.is_absolute() else repo / root_arg
    summary = json.loads((root / "v21_245_r1a_summary.json").read_text(encoding="utf-8")) if (root / "v21_245_r1a_summary.json").exists() else {}
    gate = read_rows(root / "moomoo_cache_ready_for_v21_246_gate.csv")
    current = read_rows(root / "moomoo_cache_currentness_audit.csv")
    integrity = read_rows(root / "moomoo_cache_file_integrity_audit.csv")
    return root, summary, gate, current, integrity


def truthy(v: Any) -> bool:
    return str(v).strip().lower() in {"true", "1", "yes"}


def input_gate_rows(root: Path, gate: list[dict[str, str]], summary: dict[str, Any], expected: str) -> list[dict[str, Any]]:
    g = gate[0] if gate else {}
    status = g.get("gate_status") or summary.get("ready_for_v21_246_gate_status", "")
    decision = g.get("gate_decision") or summary.get("ready_for_v21_246_gate_decision", "")
    proceed = decision in {"PROCEED_TO_V21_246_TECHNICAL_AND_FORWARD_PANEL_BUILD", "PROCEED_TO_V21_246_WITH_EXCLUSION_LIST"} or "READY" in status
    return [{"gate_status": status, "gate_decision": decision, "expected_latest_completed_date": expected, "universe_count": summary.get("universe_count", g.get("universe_count", 0)), "both_price_types_usable_count": summary.get("both_price_types_usable_count", g.get("both_price_types_usable_count", 0)), "no_data_count": summary.get("no_data_count", g.get("no_data_ticker_count", 0)), "failed_entry_count": summary.get("failed_entry_count", g.get("failed_entry_count", 0)), "invalid_cache_file_count": summary.get("invalid_cache_file_count", g.get("invalid_cache_file_count", 0)), "missing_cache_file_count": summary.get("missing_cache_file_count", 0), "proceed_to_v21_246": proceed, "exclusion_list_required": decision == "PROCEED_TO_V21_246_WITH_EXCLUSION_LIST", "source_v21_245_r1a_root": str(root)}]


def inspect_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "valid": False, "rows": 0, "first": "", "latest": "", "issue": "MISSING"}
    try:
        df = pd.read_csv(path)
    except Exception:
        return {"exists": True, "valid": False, "rows": 0, "first": "", "latest": "", "issue": "READ_ERROR"}
    if df.empty:
        return {"exists": True, "valid": False, "rows": 0, "first": "", "latest": "", "issue": "EMPTY"}
    cols_ok = all(c in df.columns for c in BASE_COLS)
    if not cols_ok:
        return {"exists": True, "valid": False, "rows": len(df), "first": "", "latest": "", "issue": "SCHEMA"}
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    ohlc_ok = ((df["high"] >= df["low"]) & (df["high"] >= df["open"]) & (df["high"] >= df["close"]) & (df["low"] <= df["open"]) & (df["low"] <= df["close"]) & (df["close"] > 0)).all()
    dup = df.duplicated(["ticker", "date"]).sum()
    mono = df["date"].is_monotonic_increasing
    valid = bool(ohlc_ok and dup == 0 and mono)
    issue = "" if valid else "DUPLICATE_OR_OHLC_OR_DATE"
    return {"exists": True, "valid": valid, "rows": len(df), "first": df["date"].min().strftime("%Y-%m-%d"), "latest": df["date"].max().strftime("%Y-%m-%d"), "issue": issue}


def build_exclusions(cache_root: Path, current: list[dict[str, str]], expected: str, min_rows: int = 60) -> tuple[list[dict[str, Any]], list[str]]:
    tickers = sorted({r["ticker"] for r in current if r.get("ticker")})
    rows, usable = [], []
    for t in tickers:
        raw = inspect_cache(cache_file(cache_root, t, "RAW_DAILY"))
        qfq = inspect_cache(cache_file(cache_root, t, "QFQ_DAILY"))
        reason = "NOT_EXCLUDED"
        if not raw["exists"]:
            reason = "MISSING_RAW_CACHE"
        if not qfq["exists"]:
            reason = "MISSING_QFQ_CACHE"
        if raw["exists"] and not raw["valid"]:
            reason = "INVALID_RAW_CACHE"
        if qfq["exists"] and not qfq["valid"]:
            reason = "INVALID_QFQ_CACHE"
        if not raw["exists"] and not qfq["exists"]:
            reason = "NO_DATA"
        if qfq["valid"] and qfq["rows"] < min_rows:
            reason = "INSUFFICIENT_ROWS_FOR_TECHNICAL_LOOKBACK"
        if reason == "NOT_EXCLUDED":
            usable.append(t)
        rows.append({"ticker": t, "moomoo_symbol": f"US.{t}", "exclusion_reason": reason, "raw_status": "VALID" if raw["valid"] else raw["issue"], "qfq_status": "VALID" if qfq["valid"] else qfq["issue"], "cache_file_issue": "|".join(x for x in [raw["issue"], qfq["issue"]] if x), "source_audit_file": "moomoo_cache_currentness_audit.csv", "excluded_from_technical_panel": reason != "NOT_EXCLUDED", "excluded_from_forward_return_panel": reason != "NOT_EXCLUDED"})
    return rows, usable


def load_ohlcv(cache_root: Path, tickers: list[str], expected: str, use_qfq: bool) -> pd.DataFrame:
    frames = []
    pt = "QFQ_DAILY" if use_qfq else "RAW_DAILY"
    for t in tickers:
        path = cache_file(cache_root, t, pt)
        df = pd.read_csv(path, usecols=lambda c: c in BASE_COLS)
        df["source_cache_file"] = str(path)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df[df["date"].notna() & (df["date"] <= pd.to_datetime(expected))]
        for c in ["open", "high", "low", "close", "volume", "turnover"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=BASE_COLS + ["source_cache_file"])
    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(["ticker", "date"]).sort_values(["ticker", "date"]).reset_index(drop=True)
    return out


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    parts = []
    qqq = df[df["ticker"] == "QQQ"][["date", "close"]].rename(columns={"close": "qqq_close"})
    for _, g in df.groupby("ticker", sort=False):
        g = g.sort_values("date").copy()
        close, high, low, vol = g["close"], g["high"], g["low"], g["volume"]
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14, min_periods=14).mean()
        loss = (-delta.clip(upper=0)).rolling(14, min_periods=14).mean()
        rs = gain / loss.replace(0, NAN)
        g["RSI_14"] = 100 - (100 / (1 + rs))
        low9 = low.rolling(9, min_periods=9).min()
        high9 = high.rolling(9, min_periods=9).max()
        rsv = (close - low9) / (high9 - low9).replace(0, NAN) * 100
        g["KDJ_K_9_3_3"] = rsv.ewm(alpha=1 / 3, adjust=False, min_periods=3).mean()
        g["KDJ_D_9_3_3"] = g["KDJ_K_9_3_3"].ewm(alpha=1 / 3, adjust=False, min_periods=3).mean()
        g["KDJ_J_9_3_3"] = 3 * g["KDJ_K_9_3_3"] - 2 * g["KDJ_D_9_3_3"]
        ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
        ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
        g["MACD_DIF_12_26"] = ema12 - ema26
        g["MACD_DEA_9"] = g["MACD_DIF_12_26"].ewm(span=9, adjust=False, min_periods=9).mean()
        g["MACD_HIST_12_26_9"] = g["MACD_DIF_12_26"] - g["MACD_DEA_9"]
        mid = close.rolling(20, min_periods=20).mean()
        sd = close.rolling(20, min_periods=20).std()
        g["BB_MID_20"] = mid
        g["BB_UPPER_20_2"] = mid + 2 * sd
        g["BB_LOWER_20_2"] = mid - 2 * sd
        g["BB_WIDTH_20"] = (g["BB_UPPER_20_2"] - g["BB_LOWER_20_2"]) / mid.replace(0, NAN)
        g["BB_PCTB_20"] = (close - g["BB_LOWER_20_2"]) / (g["BB_UPPER_20_2"] - g["BB_LOWER_20_2"]).replace(0, NAN)
        g["MA20"] = mid
        g["MA50"] = close.rolling(50, min_periods=50).mean()
        g["EMA12"] = ema12
        g["EMA26"] = ema26
        g["EMA50"] = close.ewm(span=50, adjust=False, min_periods=50).mean()
        g["VOLUME_MA20"] = vol.rolling(20, min_periods=20).mean()
        g["VOLUME_RATIO_20"] = vol / g["VOLUME_MA20"].replace(0, NAN)
        g["VOLATILITY_20"] = close.pct_change().rolling(20, min_periods=20).std()
        g["MOMENTUM_20"] = close / close.shift(20) - 1
        g["MOMENTUM_60"] = close / close.shift(60) - 1
        h20 = high.rolling(20, min_periods=20).max()
        g["BREAKOUT_20"] = close / h20 - 1
        g["PULLBACK_FROM_20D_HIGH"] = close / h20 - 1
        g["DISTANCE_TO_MA20"] = close / g["MA20"] - 1
        g["DISTANCE_TO_MA50"] = close / g["MA50"] - 1
        parts.append(g)
    wide = pd.concat(parts, ignore_index=True) if parts else df.copy()
    if not qqq.empty:
        q = qqq.sort_values("date").copy()
        q["QQQ_MOM20"] = q["qqq_close"] / q["qqq_close"].shift(20) - 1
        wide = wide.merge(q[["date", "QQQ_MOM20"]], on="date", how="left")
        wide["RELATIVE_STRENGTH_20_VS_QQQ"] = wide["MOMENTUM_20"] - wide["QQQ_MOM20"]
    else:
        wide["RELATIVE_STRENGTH_20_VS_QQQ"] = pd.NA
    return wide.drop(columns=[c for c in ["QQQ_MOM20"] if c in wide])


def formula_rows() -> list[dict[str, Any]]:
    desc = {
        "RSI_14": "100 - 100/(1+average_gain_14/average_loss_14)",
        "KDJ_K_9_3_3": "EMA-smoothed RSV over 9 rows with alpha 1/3",
        "KDJ_D_9_3_3": "EMA-smoothed K with alpha 1/3",
        "KDJ_J_9_3_3": "3*K - 2*D",
        "MACD_DIF_12_26": "EMA12 - EMA26",
        "MACD_DEA_9": "EMA9 of DIF",
        "MACD_HIST_12_26_9": "DIF - DEA",
        "BB_MID_20": "20-row moving average of close",
        "BB_UPPER_20_2": "BB_MID_20 + 2*rolling_std_20",
        "BB_LOWER_20_2": "BB_MID_20 - 2*rolling_std_20",
        "BB_WIDTH_20": "(upper-lower)/mid",
        "BB_PCTB_20": "(close-lower)/(upper-lower)",
        "MA20": "20-row moving average of close",
        "MA50": "50-row moving average of close",
        "EMA12": "12-row exponential moving average of close",
        "EMA26": "26-row exponential moving average of close",
        "EMA50": "50-row exponential moving average of close",
        "VOLUME_MA20": "20-row moving average of volume",
        "VOLUME_RATIO_20": "volume / volume_ma20",
        "VOLATILITY_20": "20-row rolling std of daily close returns",
        "MOMENTUM_20": "close / close.shift(20) - 1",
        "MOMENTUM_60": "close / close.shift(60) - 1",
        "RELATIVE_STRENGTH_20_VS_QQQ": "ticker MOMENTUM_20 minus QQQ MOMENTUM_20 by same date",
        "BREAKOUT_20": "close / rolling_high_20 - 1",
        "PULLBACK_FROM_20D_HIGH": "close / rolling_high_20 - 1",
        "DISTANCE_TO_MA20": "close / MA20 - 1",
        "DISTANCE_TO_MA50": "close / MA50 - 1",
    }
    return [{"indicator_name": n, "formula_description": desc[n], "input_columns": "open|high|low|close|volume", "lookback_days": lb, "warmup_rows_required": lb, "output_column": n, "intended_signal_role_preliminary": role, "research_only": True} for n, _, lb, role in INDICATORS]


def long_panel(wide: pd.DataFrame) -> pd.DataFrame:
    id_cols = ["asof_date", "ticker", "source_cache_file", "price_type", "provider"]
    meta = {n: (grp, lb, role) for n, grp, lb, role in INDICATORS}
    long = wide.melt(id_vars=id_cols, value_vars=[n for n, *_ in INDICATORS], var_name="technical_subfactor_name", value_name="raw_value")
    long["raw_value"] = pd.to_numeric(long["raw_value"], errors="coerce")
    long["technical_group"] = long["technical_subfactor_name"].map(lambda x: meta[x][0])
    long["lookback_days"] = long["technical_subfactor_name"].map(lambda x: meta[x][1])
    long["intended_signal_role_preliminary"] = long["technical_subfactor_name"].map(lambda x: meta[x][2])
    long["warmup_valid"] = long["raw_value"].notna()
    long["data_quality_flag"] = long["raw_value"].map(lambda x: "OK" if pd.notna(x) else "WARMUP_OR_MISSING")
    g = long.groupby(["asof_date", "technical_subfactor_name"])["raw_value"]
    mu = g.transform("mean")
    sd = g.transform("std")
    long["normalized_value_by_date"] = (long["raw_value"] - mu) / sd.replace(0, NAN)
    long["rank_pct_by_date"] = g.rank(pct=True)
    return long[["asof_date", "ticker", "technical_subfactor_name", "technical_group", "raw_value", "normalized_value_by_date", "rank_pct_by_date", "source_cache_file", "price_type", "provider", "lookback_days", "warmup_valid", "data_quality_flag", "intended_signal_role_preliminary"]]


def forward_panel(df: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for _, g in df.groupby("ticker", sort=False):
        g = g.sort_values("date").copy()
        for h in [1, 5, 10, 20]:
            g[f"forward_close_{h}d"] = g["close"].shift(-h)
            g[f"forward_return_{h}d"] = g[f"forward_close_{h}d"] / g["close"] - 1
            g[f"maturity_{h}d"] = g[f"forward_close_{h}d"].notna()
        parts.append(g)
    out = pd.concat(parts, ignore_index=True) if parts else df.copy()
    out["asof_date"] = out["date"].dt.strftime("%Y-%m-%d")
    cols = ["asof_date", "ticker", "close", "forward_close_1d", "forward_close_5d", "forward_close_10d", "forward_close_20d", "forward_return_1d", "forward_return_5d", "forward_return_10d", "forward_return_20d", "maturity_1d", "maturity_5d", "maturity_10d", "maturity_20d", "source_cache_file", "price_type", "provider"]
    return out[cols]


def quality_audits(long: pd.DataFrame, fwd: pd.DataFrame, ticker_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    tq = []
    for name, grp, *_ in INDICATORS:
        s = long[long["technical_subfactor_name"] == name]
        nn = int(s["raw_value"].notna().sum())
        status = "PASS_USABLE_FOR_V21_247_EFFECTIVENESS_RERUN" if nn > 10000 else "PARTIAL_USABLE_WITH_WARNINGS" if nn > 1000 else "WARN_TOO_SPARSE" if nn > 0 else "FAIL_NOT_USABLE"
        tq.append({"technical_subfactor_name": name, "technical_group": grp, "row_count": len(s), "non_null_row_count": nn, "null_ratio": 1 - nn / max(1, len(s)), "unique_date_count": s["asof_date"].nunique(), "unique_ticker_count": s["ticker"].nunique(), "earliest_asof_date": s["asof_date"].min() if len(s) else "", "latest_asof_date": s["asof_date"].max() if len(s) else "", "warmup_valid_ratio": float(s["warmup_valid"].mean()) if len(s) else 0, "normalized_value_available_ratio": float(s["normalized_value_by_date"].notna().mean()) if len(s) else 0, "rank_pct_available_ratio": float(s["rank_pct_by_date"].notna().mean()) if len(s) else 0, "quality_status": status, "primary_warning": "" if status.startswith("PASS") else "sparse or warmup-null rows"})
    fq = []
    for h in [1, 5, 10, 20]:
        m = fwd[f"maturity_{h}d"]
        matured = fwd[m]
        status = "PASS_USABLE_FOR_V21_247_EFFECTIVENESS_RERUN" if int(m.sum()) > 10000 else "PARTIAL_USABLE_WITH_WARNINGS" if int(m.sum()) > 1000 else "WARN_TOO_SPARSE" if int(m.sum()) > 0 else "FAIL_NOT_USABLE"
        fq.append({"horizon": f"{h}D", "row_count": len(fwd), "matured_row_count": int(m.sum()), "maturity_ratio": float(m.mean()) if len(fwd) else 0, "unique_date_count": fwd["asof_date"].nunique(), "unique_ticker_count": fwd["ticker"].nunique(), "earliest_asof_date": fwd["asof_date"].min() if len(fwd) else "", "latest_matured_asof_date": matured["asof_date"].max() if len(matured) else "", "null_forward_return_ratio": float(fwd[f"forward_return_{h}d"].isna().mean()) if len(fwd) else 1, "quality_status": status, "primary_warning": "" if status.startswith("PASS") else "limited matured rows"})
    return tq, fq, ticker_rows


def run(repo: Path, output_dir: Path | None = None, cache_root: Path = DEFAULT_CACHE_ROOT, r1a_root: Path = DEFAULT_R1A_REL, expected_latest_date: str = "2026-07-02", use_qfq: bool = True, respect_exclusion_list: bool = True, min_usable_ticker_count: int = 250) -> dict[str, Any]:
    out = output_dir or repo / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    try:
        r1a, r1a_summary, gate, current, integrity = load_r1a(repo, r1a_root)
        input_gate = input_gate_rows(r1a, gate, r1a_summary, expected_latest_date)
        exclusions, usable = build_exclusions(cache_root, current, expected_latest_date)
        if len(usable) < min_usable_ticker_count:
            # Fall back to actual cache scan when prior audit was run with an overly late expected date.
            tickers = sorted({p.stem for p in (cache_root / "market_data/moomoo/daily/qfq").glob("*.csv")})
            exclusions, usable = build_exclusions(cache_root, [{"ticker": t} for t in tickers], expected_latest_date)
        df = load_ohlcv(cache_root, usable, expected_latest_date, use_qfq)
        wide = compute_indicators(df)
        wide["asof_date"] = wide["date"].dt.strftime("%Y-%m-%d")
        wide_cols = ["asof_date", "ticker", "price_type", "provider", "source_cache_file", "close", "volume"] + [n for n, *_ in INDICATORS]
        wide_out = wide[wide_cols].copy()
        long = long_panel(wide_out)
        fwd = forward_panel(df)
        join_cols = ["asof_date", "ticker", "forward_return_1d", "forward_return_5d", "forward_return_10d", "forward_return_20d", "maturity_1d", "maturity_5d", "maturity_10d", "maturity_20d"]
        joined = long.merge(fwd[join_cols], on=["asof_date", "ticker"], how="left")
        joined["join_quality_flag"] = joined["forward_return_1d"].map(lambda x: "JOINED" if pd.notna(x) else "JOINED_NO_MATURED_1D")
        joined = joined[["asof_date", "ticker", "technical_subfactor_name", "technical_group", "raw_value", "normalized_value_by_date", "rank_pct_by_date", "forward_return_1d", "forward_return_5d", "forward_return_10d", "forward_return_20d", "maturity_1d", "maturity_5d", "maturity_10d", "maturity_20d", "price_type", "provider", "warmup_valid", "data_quality_flag", "join_quality_flag", "intended_signal_role_preliminary"]]
        ticker_audit = []
        for t in sorted(set([*usable, *[r["ticker"] for r in exclusions if r["exclusion_reason"] != "NOT_EXCLUDED"]])):
            sub = df[df["ticker"] == t]
            ex = next((r for r in exclusions if r["ticker"] == t), {})
            fsub = fwd[fwd["ticker"] == t] if len(fwd) else pd.DataFrame()
            ticker_audit.append({"ticker": t, "included_in_technical_panel": t in usable, "included_in_forward_panel": t in usable, "raw_cache_available": cache_file(cache_root, t, "RAW_DAILY").exists(), "qfq_cache_available": cache_file(cache_root, t, "QFQ_DAILY").exists(), "row_count": len(sub), "first_date": sub["date"].min().strftime("%Y-%m-%d") if len(sub) else "", "latest_date": sub["date"].max().strftime("%Y-%m-%d") if len(sub) else "", "technical_non_null_indicator_count": int(wide_out[wide_out["ticker"] == t][[n for n, *_ in INDICATORS]].notna().sum().sum()) if t in usable else 0, "forward_matured_1d_count": int(fsub["maturity_1d"].sum()) if len(fsub) else 0, "forward_matured_5d_count": int(fsub["maturity_5d"].sum()) if len(fsub) else 0, "forward_matured_10d_count": int(fsub["maturity_10d"].sum()) if len(fsub) else 0, "forward_matured_20d_count": int(fsub["maturity_20d"].sum()) if len(fsub) else 0, "exclusion_reason": ex.get("exclusion_reason", "NOT_EXCLUDED"), "build_status": "PASS_BUILT" if t in usable else "EXCLUDED_NO_DATA" if ex.get("exclusion_reason") in {"NO_DATA", "MISSING_QFQ_CACHE", "MISSING_RAW_CACHE"} else "EXCLUDED_INVALID_CACHE"})
        tq, fq, ta = quality_audits(long, fwd, ticker_audit)
        write_csv(out / "v21_246_input_cache_gate.csv", input_gate, ["gate_status", "gate_decision", "expected_latest_completed_date", "universe_count", "both_price_types_usable_count", "no_data_count", "failed_entry_count", "invalid_cache_file_count", "missing_cache_file_count", "proceed_to_v21_246", "exclusion_list_required", "source_v21_245_r1a_root"])
        write_csv(out / "v21_246_exclusion_list_used.csv", exclusions, ["ticker", "moomoo_symbol", "exclusion_reason", "raw_status", "qfq_status", "cache_file_issue", "source_audit_file", "excluded_from_technical_panel", "excluded_from_forward_return_panel"])
        wide_out.to_csv(out / "technical_subfactor_panel_wide.csv", index=False, lineterminator="\n")
        long.to_csv(out / "technical_subfactor_panel_long.csv", index=False, lineterminator="\n")
        fwd.to_csv(out / "forward_return_panel_aligned.csv", index=False, lineterminator="\n")
        joined.to_csv(out / "technical_forward_join_panel.csv", index=False, lineterminator="\n")
        write_csv(out / "technical_indicator_formula_audit.csv", formula_rows(), ["indicator_name", "formula_description", "input_columns", "lookback_days", "warmup_rows_required", "output_column", "intended_signal_role_preliminary", "research_only"])
        write_csv(out / "technical_panel_quality_audit.csv", tq, ["technical_subfactor_name", "technical_group", "row_count", "non_null_row_count", "null_ratio", "unique_date_count", "unique_ticker_count", "earliest_asof_date", "latest_asof_date", "warmup_valid_ratio", "normalized_value_available_ratio", "rank_pct_available_ratio", "quality_status", "primary_warning"])
        write_csv(out / "forward_return_quality_audit.csv", fq, ["horizon", "row_count", "matured_row_count", "maturity_ratio", "unique_date_count", "unique_ticker_count", "earliest_asof_date", "latest_matured_asof_date", "null_forward_return_ratio", "quality_status", "primary_warning"])
        write_csv(out / "ticker_panel_build_audit.csv", ta, ["ticker", "included_in_technical_panel", "included_in_forward_panel", "raw_cache_available", "qfq_cache_available", "row_count", "first_date", "latest_date", "technical_non_null_indicator_count", "forward_matured_1d_count", "forward_matured_5d_count", "forward_matured_10d_count", "forward_matured_20d_count", "exclusion_reason", "build_status"])
        t_pass = sum(1 for r in tq if r["quality_status"].startswith("PASS"))
        t_part = sum(1 for r in tq if r["quality_status"].startswith("PARTIAL"))
        f_pass = sum(1 for r in fq if r["quality_status"].startswith("PASS"))
        f_part = sum(1 for r in fq if r["quality_status"].startswith("PARTIAL"))
        ready = len(usable) >= min_usable_ticker_count and f_pass >= 4 and t_pass >= 20
        status = "PASS_V21_246_TECHNICAL_FORWARD_PANEL_READY" if ready and not any(r["exclusion_reason"] != "NOT_EXCLUDED" for r in exclusions) else "PARTIAL_PASS_V21_246_TECHNICAL_FORWARD_PANEL_READY_WITH_WARNINGS" if len(usable) >= min_usable_ticker_count else "WARN_V21_246_TECHNICAL_FORWARD_PANEL_TOO_SPARSE"
        decision = "TECHNICAL_FORWARD_PANEL_READY_FOR_V21_247_EFFECTIVENESS_RERUN" if status.startswith("PASS") else "TECHNICAL_FORWARD_PANEL_READY_WITH_EXCLUSIONS_FOR_V21_247" if status.startswith("PARTIAL") else "TECHNICAL_FORWARD_PANEL_TOO_SPARSE_WAIT_MORE_CACHE_HISTORY"
        summary = {"version": STAGE, "final_status": status, "final_decision": decision, "research_only": True, "official_adoption_allowed": False, "broker_action_allowed": False, "provider": PROVIDER, "cache_root": str(cache_root), "source_v21_245_r1a_root": str(r1a), "expected_latest_completed_date": expected_latest_date, "universe_count": len(exclusions), "usable_ticker_count": len(usable), "excluded_ticker_count": sum(1 for r in exclusions if r["exclusion_reason"] != "NOT_EXCLUDED"), "technical_indicator_count": len(INDICATORS), "technical_wide_row_count": len(wide_out), "technical_long_row_count": len(long), "forward_panel_row_count": len(fwd), "technical_forward_join_row_count": len(joined), "technical_subfactor_pass_count": t_pass, "technical_subfactor_partial_count": t_part, "forward_horizon_pass_count": f_pass, "forward_horizon_partial_count": f_part, "earliest_panel_date": wide_out["asof_date"].min() if len(wide_out) else "", "latest_panel_date": wide_out["asof_date"].max() if len(wide_out) else "", "latest_matured_20d_asof_date": next((r["latest_matured_asof_date"] for r in fq if r["horizon"] == "20D"), ""), "ready_for_v21_247": ready, "output_root": str(out), "provider_fetch_attempted": False}
        write_json(out / "v21_246_summary.json", summary)
        (out / "V21.246_technical_and_forward_panel_report.txt").write_text(f"{STAGE}\nfinal_status={status}\nfinal_decision={decision}\nprovider={PROVIDER}\nresearch_only=True\nofficial_adoption_allowed=False\nbroker_action_allowed=False\nNo provider fetch, effectiveness test, promotion decision, ranking/weight mutation, or broker action was performed.\n", encoding="utf-8")
        return summary
    except Exception as exc:
        summary = {"version": STAGE, "final_status": "FAIL_V21_246_TECHNICAL_FORWARD_PANEL_BUILD_ERROR", "final_decision": "TECHNICAL_FORWARD_PANEL_BUILD_FAILED_REPAIR_REQUIRED", "research_only": True, "official_adoption_allowed": False, "broker_action_allowed": False, "provider": PROVIDER, "error": repr(exc), "output_root": str(out)}
        write_json(out / "v21_246_summary.json", summary)
        raise


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--output-dir", type=Path)
    p.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    p.add_argument("--v21-245-r1a-root", type=Path, default=DEFAULT_R1A_REL)
    p.add_argument("--expected-latest-date", default="2026-07-02")
    p.add_argument("--use-qfq", action="store_true")
    p.add_argument("--respect-exclusion-list", action="store_true")
    p.add_argument("--fail-on-too-sparse", action="store_true")
    p.add_argument("--min-usable-ticker-count", type=int, default=250)
    p.add_argument("--build", action="store_true")
    a = p.parse_args(argv)
    try:
        s = run(a.repo_root.resolve(), a.output_dir, a.cache_root.resolve(), a.v21_245_r1a_root, a.expected_latest_date, use_qfq=True if a.use_qfq else True, respect_exclusion_list=a.respect_exclusion_list, min_usable_ticker_count=a.min_usable_ticker_count)
    except Exception:
        return 1
    for k in ["final_status", "final_decision", "provider", "expected_latest_completed_date", "universe_count", "usable_ticker_count", "excluded_ticker_count", "technical_indicator_count", "technical_wide_row_count", "technical_long_row_count", "forward_panel_row_count", "technical_forward_join_row_count", "technical_subfactor_pass_count", "technical_subfactor_partial_count", "forward_horizon_pass_count", "forward_horizon_partial_count", "earliest_panel_date", "latest_panel_date", "latest_matured_20d_asof_date", "ready_for_v21_247", "official_adoption_allowed", "broker_action_allowed", "output_root"]:
        print(f"{k}={s.get(k)}")
    return 1 if a.fail_on_too_sparse and str(s.get("final_status", "")).startswith("WARN") else 0


if __name__ == "__main__":
    raise SystemExit(main())
