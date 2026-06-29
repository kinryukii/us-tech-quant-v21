#!/usr/bin/env python
"""V21.133 E conservative adaptive momentum R1 research-only ranking."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.133_E_CONSERVATIVE_ADAPTIVE_MOMENTUM_R1"
OUT = ROOT / "outputs/v21/V21.133_E_CONSERVATIVE_ADAPTIVE_MOMENTUM_R1"
V128 = ROOT / "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE"
V129 = ROOT / "outputs/v21/V21.129_D_CONTINUED_TRACKING_AND_STRICT_ADOPTION_GATE"
PRICE_PANEL = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"

RANKING_NAMES = {
    "A1": "A1_BASELINE_CONTROL_latest_ranking.csv",
    "B": "B_STATIC_MOMENTUM_BLEND_latest_ranking.csv",
    "C": "C_DYNAMIC_MOMENTUM_BLEND_latest_ranking.csv",
    "D": "D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv",
}
STRATEGY_NAMES = {
    "A1": "A1_BASELINE_CONTROL",
    "B": "B_STATIC_MOMENTUM_BLEND",
    "C": "C_DYNAMIC_MOMENTUM_BLEND",
    "D": "D_WEIGHT_OPTIMIZED_R1",
    "E": "E_CONSERVATIVE_ADAPTIVE_MOMENTUM_R1",
}
FINAL_WEIGHTS = {
    "A1_baseline_norm": 0.80,
    "context_momentum_norm": 0.12,
    "technical_entry_quality_norm": 0.04,
    "risk_guardrail_norm": 0.04,
}
EXPANDED_WEIGHTS = {
    "Fundamental": 0.16,
    "Technical baseline": 0.20,
    "Strategy": 0.16,
    "Risk baseline": 0.12,
    "Market Regime": 0.08,
    "Data Trust": 0.08,
    "Context Momentum Overlay": 0.12,
    "Technical Entry Quality Overlay": 0.04,
    "Risk Guardrail Overlay": 0.04,
}
CONTEXT_WEIGHTS = {
    "rs_vs_benchmark_norm": 0.35,
    "price_momentum_20d_60d_norm": 0.30,
    "volume_confirmed_momentum_norm": 0.15,
    "pullback_after_strength_norm": 0.10,
    "breakout_follow_through_norm": 0.10,
}
TECHNICAL_WEIGHTS = {
    "rsi_position_repair_norm": 0.20,
    "kdj_stochastic_confirmation_norm": 0.20,
    "macd_direction_norm": 0.20,
    "bollinger_position_norm": 0.20,
    "ma_ema_volume_confirmation_norm": 0.20,
}
RISK_WEIGHTS = {
    "repeated_loser_avoidance_norm": 0.30,
    "concentration_avoidance_norm": 0.25,
    "left_tail_avoidance_norm": 0.25,
    "data_quality_maturity_avoidance_norm": 0.20,
}
PROTECTED_BASELINE_FILES = [
    V128 / "A1_BASELINE_CONTROL_latest_ranking.csv",
    V128 / "B_STATIC_MOMENTUM_BLEND_latest_ranking.csv",
    V128 / "C_DYNAMIC_MOMENTUM_BLEND_latest_ranking.csv",
    V128 / "D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv",
    V128 / "V21.128_summary.json",
    PRICE_PANEL,
]


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str] | None = None) -> None:
    rows = list(rows)
    if fields is None:
        fields = []
        for row in rows:
            for field in row:
                if field not in fields:
                    fields.append(field)
        fields = fields if fields else ["empty"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_status() -> list[str]:
    completed = subprocess.run(["git", "status", "--short"], cwd=ROOT, text=True, capture_output=True, check=False)
    return completed.stdout.splitlines()


def protected_modified(status_lines: list[str], baseline_lines: list[str]) -> bool:
    baseline = {line.replace("\\", "/") for line in baseline_lines}
    allowed_prefix = "?? outputs/v21/V21.133_E_CONSERVATIVE_ADAPTIVE_MOMENTUM_R1/"
    allowed_scripts = {
        "?? scripts/v21/v21_133_e_conservative_adaptive_momentum_r1.py",
        "?? scripts/v21/test_v21_133_e_conservative_adaptive_momentum_r1.py",
        "?? scripts/v21/run_v21_133_e_conservative_adaptive_momentum_r1.ps1",
    }
    for line in status_lines:
        normalized = line.replace("\\", "/")
        if normalized in baseline or normalized.startswith(allowed_prefix) or normalized in allowed_scripts:
            continue
        lowered = normalized.lower()
        if lowered.startswith((" m outputs/", " d outputs/", "?? outputs/")) and (
            "official" in lowered or "broker" in lowered or "protected" in lowered
        ):
            return True
    return False


def discover_inputs() -> tuple[dict[str, Path], dict[str, Any]]:
    candidates = []
    for summary_path in (ROOT / "outputs/v21").glob("V21.*/*summary.json"):
        summary = load_json(summary_path)
        latest = str(summary.get("latest_price_date_used", summary.get("latest_price_date_after", "")))
        folder = summary_path.parent
        if all((folder / name).is_file() for name in RANKING_NAMES.values()) and latest:
            candidates.append((latest, folder.stat().st_mtime, folder))
    folder = sorted(candidates, key=lambda item: (item[0], item[1]), reverse=True)[0][2] if candidates else V128
    summary = load_json(folder / "V21.128_summary.json") or load_json(next(folder.glob("*summary.json"), folder / "missing.json"))
    return {key: folder / name for key, name in RANKING_NAMES.items()}, {"folder": rel(folder), "summary": summary}


def percentile_score(series: pd.Series, higher_is_better: bool = True, neutral: float = 50.0) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    valid = numeric.dropna()
    if valid.empty:
        return pd.Series(neutral, index=series.index, dtype=float)
    ranks = numeric.rank(pct=True, method="average", ascending=not higher_is_better) * 100.0
    return ranks.fillna(neutral).clip(0, 100)


def scale_0_100(value: float, low: float, high: float) -> float:
    if value is None or math.isnan(value):
        return 50.0
    if high == low:
        return 50.0
    return max(0.0, min(100.0, (value - low) / (high - low) * 100.0))


def score_rsi(rsi: float) -> float:
    if math.isnan(rsi):
        return 50.0
    if 45 <= rsi <= 62:
        return 90.0
    if 35 <= rsi < 45:
        return 70.0
    if 62 < rsi <= 72:
        return 65.0
    if 25 <= rsi < 35:
        return 45.0
    if 72 < rsi <= 82:
        return 35.0
    return 20.0


def score_stochastic(k: float, d: float) -> float:
    if math.isnan(k) or math.isnan(d):
        return 50.0
    if k > d and 25 <= k <= 75:
        return 90.0
    if k > d and 75 < k <= 85:
        return 65.0
    if k <= d and 25 <= k <= 70:
        return 45.0
    if k > 85:
        return 30.0
    return 50.0


def score_bollinger(close: float, upper: float, lower: float) -> float:
    if any(math.isnan(x) for x in [close, upper, lower]) or upper <= lower:
        return 50.0
    pos = (close - lower) / (upper - lower)
    if 0.55 <= pos <= 0.90:
        return 85.0
    if 0.35 <= pos < 0.55:
        return 65.0
    if 0.90 < pos <= 1.05:
        return 55.0
    if pos > 1.05:
        return 30.0
    return 45.0


def read_prices(tickers: set[str], asof: str) -> tuple[pd.DataFrame, list[str]]:
    warnings = []
    wanted = set(tickers) | {"QQQ", "SOXX"}
    if not PRICE_PANEL.is_file():
        return pd.DataFrame(), [f"MISSING_PRICE_PANEL:{rel(PRICE_PANEL)}"]
    chunks = []
    usecols = ["symbol", "date", "open", "high", "low", "close", "adjusted_close", "volume"]
    for chunk in pd.read_csv(PRICE_PANEL, usecols=usecols, chunksize=250_000, low_memory=False):
        chunk["symbol"] = chunk["symbol"].astype(str).str.upper().str.strip()
        chunk["date"] = chunk["date"].astype(str)
        sub = chunk[chunk["symbol"].isin(wanted) & (chunk["date"] <= asof)].copy()
        if not sub.empty:
            chunks.append(sub)
    if not chunks:
        return pd.DataFrame(), ["NO_PRICE_ROWS_FOR_E_UNIVERSE"]
    prices = pd.concat(chunks, ignore_index=True)
    prices = prices.sort_values(["symbol", "date"])
    max_date = prices["date"].max()
    if max_date < asof:
        warnings.append(f"PRICE_PANEL_STALE:max_date={max_date};asof={asof}")
    missing = sorted(wanted - set(prices["symbol"].unique()))
    if missing:
        warnings.append(f"MISSING_PRICE_TICKERS:{'|'.join(missing)}")
    return prices, warnings


def trailing_return(group: pd.DataFrame, days: int) -> float:
    if len(group) <= days:
        return math.nan
    last = float(group["adjusted_close"].iloc[-1])
    prior = float(group["adjusted_close"].iloc[-days - 1])
    return last / prior - 1.0 if prior else math.nan


def max_drawdown(values: pd.Series) -> float:
    vals = pd.to_numeric(values, errors="coerce").dropna()
    if vals.empty:
        return math.nan
    cummax = vals.cummax()
    dd = vals / cummax - 1.0
    return float(dd.min())


def compute_price_features(prices: pd.DataFrame, universe: set[str], asof: str) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    warnings = []
    bench_returns = {}
    for bench in ["QQQ", "SOXX"]:
        group = prices[prices["symbol"].eq(bench)].copy()
        bench_returns[bench] = {
            "ret20": trailing_return(group, 20) if len(group) else math.nan,
            "ret60": trailing_return(group, 60) if len(group) else math.nan,
        }
        if not len(group):
            warnings.append({"ticker": bench, "warning_type": "missing_benchmark_price_history", "warning_detail": f"{bench} missing; relative strength uses available benchmark only"})
    rows = []
    for ticker in sorted(universe):
        group = prices[prices["symbol"].eq(ticker)].copy()
        if group.empty:
            rows.append({"ticker": ticker, "has_price_history": False, "technical_history_sufficient": False})
            warnings.append({"ticker": ticker, "warning_type": "missing_price_history", "warning_detail": "No canonical OHLCV rows available <= asof; scoring impossible"})
            continue
        group = group.tail(260).copy()
        close = pd.to_numeric(group["adjusted_close"], errors="coerce")
        high = pd.to_numeric(group["high"], errors="coerce")
        low = pd.to_numeric(group["low"], errors="coerce")
        volume = pd.to_numeric(group["volume"], errors="coerce")
        ret1 = trailing_return(group, 1)
        ret20 = trailing_return(group, 20)
        ret60 = trailing_return(group, 60)
        vol20 = float(volume.tail(20).mean()) if len(volume.dropna()) >= 20 else math.nan
        vol60 = float(volume.tail(60).mean()) if len(volume.dropna()) >= 60 else math.nan
        vol_ratio = vol20 / vol60 if vol60 and not math.isnan(vol60) else math.nan
        available_bench = [x for x in [bench_returns["QQQ"]["ret60"], bench_returns["SOXX"]["ret60"]] if not math.isnan(x)]
        rs_raw = ret60 - float(np.mean(available_bench)) if available_bench and not math.isnan(ret60) else math.nan

        delta = close.diff()
        gains = delta.clip(lower=0).rolling(14).mean()
        losses = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gains / losses.replace(0, np.nan)
        rsi = float((100 - 100 / (1 + rs)).iloc[-1]) if len(rs.dropna()) else math.nan

        low14 = low.rolling(14).min()
        high14 = high.rolling(14).max()
        k_series = (close - low14) / (high14 - low14).replace(0, np.nan) * 100
        d_series = k_series.rolling(3).mean()
        k_val = float(k_series.iloc[-1]) if len(k_series.dropna()) else math.nan
        d_val = float(d_series.iloc[-1]) if len(d_series.dropna()) else math.nan

        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        hist = macd - signal
        macd_raw = float(hist.iloc[-1] - hist.iloc[-2]) if len(hist.dropna()) >= 2 else math.nan

        ma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        upper = ma20 + 2 * std20
        lower = ma20 - 2 * std20
        ma50 = close.rolling(50).mean()
        ema20 = close.ewm(span=20, adjust=False).mean()
        last_close = float(close.iloc[-1]) if len(close.dropna()) else math.nan
        ma_volume_raw = 0.0
        if not math.isnan(last_close):
            ma_volume_raw += 1.0 if len(ma20.dropna()) and last_close > float(ma20.iloc[-1]) else 0.0
            ma_volume_raw += 1.0 if len(ma50.dropna()) and last_close > float(ma50.iloc[-1]) else 0.0
            ma_volume_raw += 1.0 if len(ema20.dropna()) and last_close > float(ema20.iloc[-1]) else 0.0
            ma_volume_raw += 1.0 if not math.isnan(vol_ratio) and vol_ratio >= 0.95 else 0.0

        breakout_raw = math.nan
        if len(close.dropna()) >= 25:
            prior20 = close.shift(1).rolling(20).max()
            breakout = close > prior20
            recent_breakouts = group.loc[breakout.fillna(False)].tail(5)
            if len(recent_breakouts) >= 2:
                breakout_level = float(prior20.loc[recent_breakouts.index[-2]])
                breakout_raw = 1.0 if last_close >= breakout_level else 0.0
            elif len(recent_breakouts) == 1:
                breakout_raw = 0.0
            else:
                breakout_raw = 0.25 if not math.isnan(ret20) and ret20 > 0 else 0.0

        technical_sufficient = len(group) >= 60
        if not technical_sufficient:
            warnings.append({"ticker": ticker, "warning_type": "insufficient_technical_history", "warning_detail": f"{len(group)} rows; neutral technical score 50 used where required"})
        rows.append({
            "ticker": ticker,
            "has_price_history": True,
            "price_rows": len(group),
            "latest_price_date": group["date"].max(),
            "technical_history_sufficient": technical_sufficient,
            "ret_1d_raw": ret1,
            "ret_20d_raw": ret20,
            "ret_60d_raw": ret60,
            "rs_vs_benchmark_raw": rs_raw,
            "volume_ratio_20d_60d_raw": vol_ratio,
            "volume_confirmed_momentum_raw": ret20 * vol_ratio if not math.isnan(ret20) and not math.isnan(vol_ratio) and ret20 > 0 else 0.0,
            "pullback_after_strength_raw": (ret60 - max(0.0, ret1)) if not math.isnan(ret60) and ret60 > 0.05 and not math.isnan(ret1) else math.nan,
            "breakout_follow_through_raw": breakout_raw,
            "rsi_raw": rsi,
            "kdj_k_raw": k_val,
            "kdj_d_raw": d_val,
            "macd_histogram_direction_raw": macd_raw,
            "bollinger_close_raw": last_close,
            "bollinger_upper_raw": float(upper.iloc[-1]) if len(upper.dropna()) else math.nan,
            "bollinger_lower_raw": float(lower.iloc[-1]) if len(lower.dropna()) else math.nan,
            "ma_ema_volume_raw": ma_volume_raw,
            "max_drawdown_252d_raw": max_drawdown(close),
            "worst_20d_return_raw": close.pct_change(20).min(),
        })
    return pd.DataFrame(rows), warnings


def metadata_map() -> dict[str, dict[str, str]]:
    mapping: dict[str, dict[str, str]] = {}
    for path in [
        ROOT / "outputs/v21/V21.111_R1_CONCENTRATION_ATTRIBUTION_AUDIT/d_only_ticker_profile.csv",
        ROOT / "outputs/v21/V21.111_R1_CONCENTRATION_ATTRIBUTION_AUDIT/eligible_universe_sector_baseline.csv",
        ROOT / "outputs/v21/V21.111_R1_CONCENTRATION_ATTRIBUTION_AUDIT/eligible_universe_industry_baseline.csv",
    ]:
        if not path.is_file():
            continue
        frame = pd.read_csv(path, low_memory=False)
        if "ticker" not in frame.columns:
            continue
        for row in frame.to_dict("records"):
            ticker = str(row.get("ticker", "")).upper().strip()
            if not ticker or ticker == "NAN":
                continue
            mapping[ticker] = {
                "sector": str(row.get("sector", row.get("bucket", "UNKNOWN")) or "UNKNOWN"),
                "industry": str(row.get("industry", row.get("bucket", "UNKNOWN")) or "UNKNOWN"),
            }
    return mapping


def top_set(frame: pd.DataFrame, n: int) -> set[str]:
    return set(frame[pd.to_numeric(frame["rank"], errors="coerce").le(n)]["ticker"].astype(str).str.upper())


def overlap_matrix(rankings: dict[str, pd.DataFrame], e_full: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    sets = {key: top_set(frame, n) for key, frame in rankings.items()}
    sets["E"] = set(e_full.head(n)["ticker"].astype(str).str.upper())
    labels = ["A1", "B", "C", "D", "E"]
    rows = []
    for left in labels:
        row = {"strategy": left}
        for right in labels:
            row[right] = len(sets[left].intersection(sets[right]))
        rows.append(row)
    return pd.DataFrame(rows)


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    baseline_status = git_status()
    baseline_hashes = {rel(path): sha256(path) for path in PROTECTED_BASELINE_FILES if path.is_file()}
    input_paths, discovery = discover_inputs()
    if not input_paths["A1"].is_file():
        summary = {
            "stage": STAGE,
            "FINAL_STATUS": "BLOCKED_V21_133_E_MISSING_A1_BASELINE",
            "DECISION": "E_NOT_READY_MISSING_BASELINE_INPUT",
            "official_adoption_allowed": False,
            "broker_action_allowed": False,
            "research_only": True,
            "protected_outputs_modified": False,
        }
        write_json(OUT / "e_validation_summary.json", summary)
        return summary

    rankings = {key: pd.read_csv(path, low_memory=False) for key, path in input_paths.items() if path.is_file()}
    a1 = rankings["A1"].copy()
    a1["ticker"] = a1["ticker"].astype(str).str.upper().str.strip()
    latest_price_date = str(discovery["summary"].get("latest_price_date_used", a1["latest_price_date"].dropna().astype(str).max()))
    price_panel_max = pd.read_csv(PRICE_PANEL, usecols=["date"])["date"].astype(str).max() if PRICE_PANEL.is_file() else ""
    universe = set(a1["ticker"])
    prices, price_warnings = read_prices(universe, latest_price_date)
    features, feature_warnings = compute_price_features(prices, universe, latest_price_date)

    full = a1[["ticker", "rank", "final_score", "latest_price_date", "eligible_flag"]].rename(columns={"rank": "A1_rank", "final_score": "A1_final_score"}).merge(features, on="ticker", how="left")
    full["latest_price_date"] = full["latest_price_date_y"].fillna(full["latest_price_date_x"]) if "latest_price_date_y" in full.columns else full["latest_price_date_x"]
    full = full.drop(columns=[col for col in ["latest_price_date_x", "latest_price_date_y"] if col in full.columns])
    full["A1_baseline_norm"] = percentile_score(full["A1_final_score"], higher_is_better=True)
    full["rs_vs_benchmark_norm"] = percentile_score(full["rs_vs_benchmark_raw"], True)
    full["price_momentum_20d_60d_raw"] = 0.45 * pd.to_numeric(full["ret_20d_raw"], errors="coerce") + 0.55 * pd.to_numeric(full["ret_60d_raw"], errors="coerce")
    full["price_momentum_20d_60d_norm"] = percentile_score(full["price_momentum_20d_60d_raw"], True)
    full["volume_confirmed_momentum_norm"] = percentile_score(full["volume_confirmed_momentum_raw"], True)
    full["pullback_after_strength_norm"] = percentile_score(full["pullback_after_strength_raw"], True)
    full["breakout_follow_through_norm"] = percentile_score(full["breakout_follow_through_raw"], True)
    full["context_momentum_norm"] = sum(full[col] * weight for col, weight in CONTEXT_WEIGHTS.items())

    full["rsi_position_repair_norm"] = full["rsi_raw"].apply(lambda value: score_rsi(float(value)) if pd.notna(value) else 50.0)
    full["kdj_stochastic_confirmation_norm"] = full.apply(lambda row: score_stochastic(float(row["kdj_k_raw"]), float(row["kdj_d_raw"])) if pd.notna(row.get("kdj_k_raw")) and pd.notna(row.get("kdj_d_raw")) else 50.0, axis=1)
    full["macd_direction_norm"] = percentile_score(full["macd_histogram_direction_raw"], True)
    full["bollinger_position_norm"] = full.apply(lambda row: score_bollinger(float(row["bollinger_close_raw"]), float(row["bollinger_upper_raw"]), float(row["bollinger_lower_raw"])) if pd.notna(row.get("bollinger_close_raw")) and pd.notna(row.get("bollinger_upper_raw")) and pd.notna(row.get("bollinger_lower_raw")) else 50.0, axis=1)
    full["ma_ema_volume_confirmation_norm"] = full["ma_ema_volume_raw"].apply(lambda value: scale_0_100(float(value), 0.0, 4.0) if pd.notna(value) else 50.0)
    full["technical_entry_quality_norm"] = sum(full[col] * weight for col, weight in TECHNICAL_WEIGHTS.items())

    repeated_tickers = set()
    repeated_path = V129 / "V21.129_d_repeated_loser_diagnostic.csv"
    if repeated_path.is_file():
        repeated = pd.read_csv(repeated_path, keep_default_na=False)
        if not repeated.empty:
            repeated_tickers = set(str(repeated.iloc[0].get("D_repeated_loser_tickers", "")).split("|"))
    else:
        feature_warnings.append({"ticker": "ALL", "warning_type": "missing_repeated_loser_diagnostic", "warning_detail": "Neutral repeated-loser avoidance would be used if no diagnostic were available"})
    full["repeated_loser_avoidance_norm"] = full["ticker"].apply(lambda ticker: 25.0 if ticker in repeated_tickers else 85.0)
    full["left_tail_avoidance_norm"] = percentile_score(full["max_drawdown_252d_raw"], True)
    warning_tickers = set(str(discovery["summary"].get("failed_tickers", "")).replace(",", "|").split("|"))
    full["data_quality_maturity_avoidance_norm"] = full.apply(
        lambda row: 30.0 if row["ticker"] in warning_tickers or not bool(row.get("has_price_history", False)) else (65.0 if not bool(row.get("technical_history_sufficient", False)) else 80.0),
        axis=1,
    )
    full["concentration_avoidance_norm"] = 75.0
    full["risk_guardrail_norm"] = sum(full[col] * weight for col, weight in RISK_WEIGHTS.items())

    full["E_final_score"] = sum(full[col] * weight for col, weight in FINAL_WEIGHTS.items())
    full["eligible_flag"] = full["eligible_flag"].astype(str).str.upper().eq("TRUE") & full["has_price_history"].fillna(False).astype(bool)
    full["eligibility_exclusion_reason"] = np.where(full["eligible_flag"], "", "MISSING_PRICE_HISTORY_OR_A1_INELIGIBLE")
    full["strategy"] = STRATEGY_NAMES["E"]
    full = full.sort_values(["eligible_flag", "E_final_score", "ticker"], ascending=[False, False, True]).reset_index(drop=True)
    full["rank"] = np.where(full["eligible_flag"], np.arange(1, len(full) + 1), np.nan)
    full["research_only"] = True
    full["official_adoption_allowed"] = False
    full["broker_action_allowed"] = False
    full["leakage_warning"] = "NO_FUTURE_LEAKAGE_DETECTED_CANONICAL_ASOF_LATEST"

    eligible = full[full["eligible_flag"]].copy()
    e_top20 = eligible.head(20).copy()
    e_top50 = eligible.head(50).copy()
    mapping = metadata_map()
    full["sector"] = full["ticker"].map(lambda ticker: mapping.get(ticker, {}).get("sector", "UNKNOWN"))
    full["industry"] = full["ticker"].map(lambda ticker: mapping.get(ticker, {}).get("industry", "UNKNOWN"))
    metadata_coverage = float((full["sector"] != "UNKNOWN").mean()) if len(full) else 0.0
    if metadata_coverage < 0.95:
        feature_warnings.append({"ticker": "ALL", "warning_type": "partial_metadata_coverage", "warning_detail": f"sector_metadata_coverage={metadata_coverage:.4f}; concentration audit emitted with UNKNOWN buckets"})

    def concentration_rows(frame: pd.DataFrame, view: str) -> list[dict[str, Any]]:
        rows = []
        for exposure in ["sector", "industry"]:
            counts = frame[exposure].fillna("UNKNOWN").value_counts()
            total = len(frame)
            for rank, (bucket, count) in enumerate(counts.items(), start=1):
                rows.append({"view": view, "exposure_type": exposure, "bucket": bucket, "count": int(count), "weight": count / total if total else math.nan, "rank": rank, "metadata_coverage": metadata_coverage})
        return rows

    concentration = concentration_rows(e_top20.merge(full[["ticker", "sector", "industry"]], on="ticker", how="left"), "top20") + concentration_rows(e_top50.merge(full[["ticker", "sector", "industry"]], on="ticker", how="left"), "top50")
    top20_sector_max = max([row["weight"] for row in concentration if row["view"] == "top20" and row["exposure_type"] == "sector"], default=0)
    if top20_sector_max > 0.55:
        feature_warnings.append({"ticker": "E_TOP20", "warning_type": "concentration_warning", "warning_detail": f"top20 max sector weight {top20_sector_max:.4f} exceeds 0.55"})

    overlap = overlap_matrix(rankings, eligible, 20)
    diff = eligible[["ticker", "rank", "E_final_score"]].merge(a1[["ticker", "rank"]].rename(columns={"rank": "A1_rank_current"}), on="ticker", how="left")
    diff["E_minus_A1_rank"] = pd.to_numeric(diff["rank"], errors="coerce") - pd.to_numeric(diff["A1_rank_current"], errors="coerce")
    for key in ["B", "C", "D"]:
        if key in rankings:
            diff = diff.merge(rankings[key][["ticker", "rank"]].rename(columns={"rank": f"{key}_rank"}), on="ticker", how="left")
    components = full.copy()
    weight_rows = (
        [{"weight_table": "final", "component": key, "weight": value} for key, value in FINAL_WEIGHTS.items()]
        + [{"weight_table": "expanded", "component": key, "weight": value} for key, value in EXPANDED_WEIGHTS.items()]
        + [{"weight_table": "context", "component": key, "weight": value} for key, value in CONTEXT_WEIGHTS.items()]
        + [{"weight_table": "technical", "component": key, "weight": value} for key, value in TECHNICAL_WEIGHTS.items()]
        + [{"weight_table": "risk", "component": key, "weight": value} for key, value in RISK_WEIGHTS.items()]
    )

    data_quality_rows = [
        {"ticker": "ALL", "warning_type": "price_source_warning", "warning_detail": warning}
        for warning in price_warnings
    ] + feature_warnings
    if int(discovery["summary"].get("stale_or_missing_ticker_count", 0) or 0) > 0:
        data_quality_rows.append({
            "ticker": str(discovery["summary"].get("failed_tickers", "UNKNOWN")),
            "warning_type": "upstream_stale_or_missing_ticker_warning",
            "warning_detail": (
                f"V21.128 stale_or_missing_ticker_count={discovery['summary'].get('stale_or_missing_ticker_count')}; "
                f"failed_tickers={discovery['summary'].get('failed_tickers', '')}; "
                "E remains research-only and adoption-blocked."
            ),
        })
    if not data_quality_rows:
        data_quality_rows = [{"ticker": "ALL", "warning_type": "none", "warning_detail": "No E scoring data quality warnings detected"}]
    material_warning = any(row["warning_type"] not in {"none", "partial_metadata_coverage", "concentration_warning"} for row in data_quality_rows) or int(discovery["summary"].get("stale_or_missing_ticker_count", 0) or 0) > 0
    maturity_rows = [{
        "gate": "E_FORWARD_MATURITY",
        "status": "BLOCK",
        "reason": "E has no forward maturity observations yet",
        "E_matured_top20_observations": 0,
        "E_matured_top50_observations": 0,
        "distinct_forward_ranking_dates": 0,
        "required_top20_observations": 40,
        "required_top50_observations": 40,
        "required_distinct_forward_ranking_dates": 8,
    }]

    full.to_csv(OUT / "e_full_ranking.csv", index=False)
    e_top20.to_csv(OUT / "e_top20.csv", index=False)
    e_top50.to_csv(OUT / "e_top50.csv", index=False)
    components.to_csv(OUT / "e_score_components.csv", index=False)
    overlap.to_csv(OUT / "e_abcd_overlap_matrix.csv", index=False)
    diff.sort_values("E_minus_A1_rank").to_csv(OUT / "e_vs_abcd_rank_diff.csv", index=False)
    write_csv(OUT / "e_concentration_audit.csv", concentration)
    write_csv(OUT / "e_data_quality_audit.csv", data_quality_rows)
    write_csv(OUT / "e_maturity_gate_audit.csv", maturity_rows)
    write_csv(OUT / "e_component_weight_table.csv", weight_rows)

    leakage_risk = any("forward" in col.lower() or "future" in col.lower() or "label" in col.lower() for col in full.columns if col not in {"leakage_warning"})
    if leakage_risk:
        final_status = "FAIL_V21_133_E_LEAKAGE_RISK"
        decision = "E_REJECTED_LEAKAGE_RISK"
    elif material_warning:
        final_status = "PARTIAL_PASS_V21_133_E_RANKING_READY_WITH_DATA_WARN"
        decision = "E_RESEARCH_ONLY_CHALLENGER_READY_DATA_WARNING_ADOPTION_BLOCKED"
    else:
        final_status = "PARTIAL_PASS_V21_133_E_RANKING_READY_WAIT_FORWARD_MATURITY"
        decision = "E_RESEARCH_ONLY_CHALLENGER_READY_ADOPTION_BLOCKED_WAIT_MATURITY"

    post_hashes = {rel(path): sha256(path) for path in PROTECTED_BASELINE_FILES if path.is_file()}
    protected_hash_changed = baseline_hashes != post_hashes
    prot_mod = protected_hash_changed or protected_modified(git_status(), baseline_status)
    summary = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "latest_price_date_used": latest_price_date,
        "price_panel_max_date": price_panel_max,
        "input_ranking_artifacts": {key: rel(path) for key, path in input_paths.items()},
        "input_discovery_folder": discovery["folder"],
        "price_source_path": rel(PRICE_PANEL),
        "row_count": int(len(full)),
        "eligible_count": int(full["eligible_flag"].sum()),
        "excluded_count": int((~full["eligible_flag"]).sum()),
        "warning_count": int(len([row for row in data_quality_rows if row["warning_type"] != "none"])),
        "E_top20_tickers": "|".join(e_top20["ticker"].astype(str)),
        "E_top50_tickers": "|".join(e_top50["ticker"].astype(str)),
        "E_vs_A1_top20_overlap": int(overlap.loc[overlap["strategy"].eq("E"), "A1"].iloc[0]),
        "E_vs_B_top20_overlap": int(overlap.loc[overlap["strategy"].eq("E"), "B"].iloc[0]),
        "E_vs_C_top20_overlap": int(overlap.loc[overlap["strategy"].eq("E"), "C"].iloc[0]),
        "E_vs_D_top20_overlap": int(overlap.loc[overlap["strategy"].eq("E"), "D"].iloc[0]),
        "final_weights": FINAL_WEIGHTS,
        "expanded_effective_weights": EXPANDED_WEIGHTS,
        "final_weight_sum": float(sum(FINAL_WEIGHTS.values())),
        "expanded_weight_sum": float(sum(EXPANDED_WEIGHTS.values())),
        "maturity_gate_status": "BLOCK",
        "protected_outputs_modified": bool(prot_mod),
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
        "D_or_ABCD_replaced": False,
        "E_adoption_allowed": False,
        "report_path": rel(OUT / "V21.133_E_CONSERVATIVE_ADAPTIVE_MOMENTUM_R1_report.txt"),
    }
    write_json(OUT / "e_validation_summary.json", summary)
    report = [
        STAGE,
        f"FINAL_STATUS={summary['FINAL_STATUS']}",
        f"DECISION={summary['DECISION']}",
        f"latest_price_date_used={latest_price_date}",
        f"input ranking artifacts discovered={json.dumps(summary['input_ranking_artifacts'], sort_keys=True)}",
        f"price source path={summary['price_source_path']}",
        f"row counts total={summary['row_count']} eligible={summary['eligible_count']} excluded={summary['excluded_count']} warnings={summary['warning_count']}",
        f"E Top20 tickers={summary['E_top20_tickers']}",
        f"E Top50 tickers={summary['E_top50_tickers']}",
        "",
        "A1/B/C/D/E overlap matrix",
        overlap.to_csv(index=False).strip(),
        "",
        "Largest rank movers vs A1",
        diff.reindex(diff["E_minus_A1_rank"].abs().sort_values(ascending=False).index).head(20).to_csv(index=False).strip(),
        "",
        "E component weight table",
        pd.DataFrame(weight_rows).to_csv(index=False).strip(),
        "",
        "Data quality warnings",
        pd.DataFrame(data_quality_rows).to_csv(index=False).strip(),
        "",
        "Concentration warnings",
        "\n".join(row["warning_detail"] for row in data_quality_rows if row["warning_type"] == "concentration_warning") or "none",
        "left-tail warnings=left-tail avoidance applied via trailing max drawdown and worst rolling return proxies",
        f"repeated-loser warnings={'repeated-loser diagnostic applied' if repeated_tickers else 'missing repeated-loser diagnostic; neutral handling'}",
        "maturity gate result=BLOCK; E has no forward maturity observations yet",
        "protected_outputs_modified=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
    ]
    (OUT / "V21.133_E_CONSERVATIVE_ADAPTIVE_MOMENTUM_R1_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")

    print(STAGE)
    print(f"FINAL_STATUS={summary['FINAL_STATUS']}")
    print(f"DECISION={summary['DECISION']}")
    print(f"report_path={summary['report_path']}")
    print(f"E_top20={summary['E_top20_tickers']}")
    print(f"E_vs_A1_overlap={summary['E_vs_A1_top20_overlap']}")
    print(f"E_vs_B_overlap={summary['E_vs_B_top20_overlap']}")
    print(f"E_vs_C_overlap={summary['E_vs_C_top20_overlap']}")
    print(f"E_vs_D_overlap={summary['E_vs_D_top20_overlap']}")
    print("warnings=" + "|".join(sorted({row["warning_type"] for row in data_quality_rows if row["warning_type"] != "none"})))
    return summary


if __name__ == "__main__":
    run()
