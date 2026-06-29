#!/usr/bin/env python
"""V21.114 true latest-data ABCD full recompute from canonical OHLCV.

Research-only. All outputs are isolated under the V21.114 stage directory.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.114_TRUE_LATEST_DATA_ABCD_FULL_RECOMPUTE_20260625"
OUT_REL = Path("outputs/v21/V21.114_TRUE_LATEST_DATA_ABCD_FULL_RECOMPUTE_20260625")
OUT = ROOT / OUT_REL

PRICE = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
UNIVERSE_CANDIDATES = [
    ROOT / "outputs/v18/candidates/V18_CURRENT_RANKED_CANDIDATES.csv",
    ROOT / "outputs/v18/candidates/V18_CURRENT_FULL_RANKED_CANDIDATES.csv",
    ROOT / "configs/v21/etf_universe_seed.csv",
]
V108_R2 = ROOT / "outputs/v21/V21.108_latest_data_multi_strategy_rerun/R2_archived_latest_strategy_rankings"
V112_R1 = ROOT / "outputs/v21/V21.112_R1_LATEST_DATA_ABCD_RERUN_20260624_PRICE_REFRESH"
V112 = ROOT / "outputs/v21/V21.112_LATEST_DATA_ABCD_RERUN"
V113 = ROOT / "outputs/v21/V21.113_LATEST_DATA_ABCD_RERUN_20260625_PRICE_REFRESH"

EXPECTED_DATE = "2026-06-25"
STRATEGIES = [
    "A1_BASELINE_CONTROL",
    "B_STATIC_MOMENTUM_BLEND",
    "C_DYNAMIC_MOMENTUM_BLEND",
    "D_WEIGHT_OPTIMIZED_R1",
]
SHORT = {
    "A1_BASELINE_CONTROL": "A1",
    "B_STATIC_MOMENTUM_BLEND": "B",
    "C_DYNAMIC_MOMENTUM_BLEND": "C",
    "D_WEIGHT_OPTIMIZED_R1": "D",
}


def clean(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text.lower() in {"nan", "nat", "none"} else text


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str] | None = None) -> None:
    rows = list(rows)
    if fields is None:
        fields = list(rows[0].keys()) if rows else ["empty"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def pct_rank(series: pd.Series, ascending: bool = True) -> pd.Series:
    return series.rank(pct=True, ascending=ascending) * 100.0


def clip_score(series: pd.Series) -> pd.Series:
    return series.clip(lower=0.0, upper=100.0)


def load_universe() -> tuple[set[str], list[dict[str, Any]]]:
    tickers: set[str] = set()
    rows: list[dict[str, Any]] = []
    for path in UNIVERSE_CANDIDATES:
        if not path.is_file():
            rows.append({"path": rel(path), "role": "universe_source", "exists": False, "rows": 0, "sha256": ""})
            continue
        frame = pd.read_csv(path, low_memory=False)
        ticker_col = "ticker" if "ticker" in frame.columns else "symbol" if "symbol" in frame.columns else ""
        if ticker_col:
            values = set(frame[ticker_col].astype(str).str.upper().str.strip())
            values = {v for v in values if v and v != "NAN"}
            tickers.update(values)
        rows.append({"path": rel(path), "role": "universe_source", "exists": True, "rows": len(frame), "sha256": sha256(path)})
    return tickers, rows


def load_price_panel(universe: set[str]) -> tuple[pd.DataFrame, str, list[dict[str, Any]]]:
    if not PRICE.is_file():
        raise FileNotFoundError(rel(PRICE))
    usecols = ["symbol", "date", "open", "high", "low", "close", "adjusted_close", "volume"]
    frame = pd.read_csv(PRICE, usecols=usecols, low_memory=False)
    frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame[frame["date"].notna()].copy()
    frame = frame[frame["symbol"].isin(universe)].copy()
    for col in ["open", "high", "low", "close", "adjusted_close", "volume"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["px"] = frame["adjusted_close"].where(frame["adjusted_close"].notna(), frame["close"])
    latest = frame["date"].max().strftime("%Y-%m-%d") if len(frame) else ""
    manifest = [{"path": rel(PRICE), "role": "canonical_price_panel", "exists": True, "rows": len(frame), "sha256": sha256(PRICE), "latest_date": latest}]
    return frame.sort_values(["symbol", "date"]), latest, manifest


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def compute_features(price: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    rows: list[pd.Series] = []
    blockers: list[dict[str, Any]] = []
    qqq = price[price["symbol"].eq("QQQ")].copy()
    benchmark_ret_63 = math.nan
    if len(qqq) >= 64:
        benchmark_ret_63 = float(qqq["px"].iloc[-1] / qqq["px"].iloc[-64] - 1)

    for symbol, group in price.groupby("symbol", sort=True):
        g = group.sort_values("date").copy()
        if len(g) < 60:
            blockers.append({"ticker": symbol, "reason": "INSUFFICIENT_PRICE_HISTORY_LT_60", "price_rows": len(g)})
            continue
        close = g["px"]
        high = g["high"]
        low = g["low"]
        volume = g["volume"]
        g["return_5d"] = close.pct_change(5)
        g["return_20d"] = close.pct_change(20)
        g["return_63d"] = close.pct_change(63)
        g["return_126d"] = close.pct_change(126)
        g["volatility_20d"] = close.pct_change().rolling(20).std() * math.sqrt(252)
        g["ma20"] = close.rolling(20).mean()
        g["ma50"] = close.rolling(50).mean()
        g["ema12"] = close.ewm(span=12, adjust=False).mean()
        g["ema26"] = close.ewm(span=26, adjust=False).mean()
        g["macd"] = g["ema12"] - g["ema26"]
        g["macd_signal"] = g["macd"].ewm(span=9, adjust=False).mean()
        g["macd_hist"] = g["macd"] - g["macd_signal"]
        g["rsi14"] = rsi(close)
        low9 = low.rolling(9).min()
        high9 = high.rolling(9).max()
        g["kdj_k"] = ((close - low9) / (high9 - low9).replace(0, pd.NA)) * 100
        g["kdj_d"] = g["kdj_k"].rolling(3).mean()
        g["kdj_j"] = 3 * g["kdj_k"] - 2 * g["kdj_d"]
        mid = close.rolling(20).mean()
        sd = close.rolling(20).std()
        g["bb_mid"] = mid
        g["bb_upper_1"] = mid + sd
        g["bb_lower_1"] = mid - sd
        g["bb_upper_2"] = mid + 2 * sd
        g["bb_lower_2"] = mid - 2 * sd
        g["bb_upper_3"] = mid + 3 * sd
        g["bb_lower_3"] = mid - 3 * sd
        g["bb_position"] = (close - g["bb_lower_2"]) / (g["bb_upper_2"] - g["bb_lower_2"]).replace(0, pd.NA)
        g["volume_20d_avg"] = volume.rolling(20).mean()
        g["volume_ratio_20d"] = volume / g["volume_20d_avg"].replace(0, pd.NA)
        g["breakout_63d"] = close / high.rolling(63).max().replace(0, pd.NA) - 1
        g["pullback_from_20d_high"] = close / high.rolling(20).max().replace(0, pd.NA) - 1
        g["relative_strength_63d"] = g["return_63d"] - benchmark_ret_63 if not math.isnan(benchmark_ret_63) else pd.NA
        latest = g.iloc[-1].copy()
        required = [
            "rsi14", "kdj_k", "kdj_d", "kdj_j", "macd", "macd_signal", "macd_hist",
            "bb_mid", "bb_upper_1", "bb_lower_1", "bb_upper_2", "bb_lower_2", "bb_upper_3", "bb_lower_3",
            "ma20", "ma50", "ema12", "ema26", "volume_ratio_20d", "volatility_20d",
            "return_20d", "return_63d", "relative_strength_63d", "breakout_63d", "pullback_from_20d_high",
        ]
        missing = [col for col in required if pd.isna(latest.get(col))]
        if missing:
            blockers.append({"ticker": symbol, "reason": "REQUIRED_FEATURE_NA", "missing_features": "|".join(missing), "price_rows": len(g)})
            continue
        rows.append(latest)

    features = pd.DataFrame(rows)
    if features.empty:
        return features, features, blockers
    features = features.rename(columns={"symbol": "ticker"})
    features["latest_price_date"] = features["date"].dt.strftime("%Y-%m-%d")

    features["rsi_score"] = clip_score(100 - (features["rsi14"] - 55).abs() * 2)
    features["trend_score"] = clip_score((features["px"] / features["ma20"] - 1) * 400 + (features["px"] / features["ma50"] - 1) * 300 + 50)
    features["macd_score"] = pct_rank(features["macd_hist"], ascending=True)
    features["bb_score"] = clip_score(100 - (features["bb_position"] - 0.65).abs() * 130)
    features["volume_score"] = clip_score(features["volume_ratio_20d"] * 50)
    features["volatility_score"] = 100 - pct_rank(features["volatility_20d"], ascending=True)
    features["breakout_score"] = pct_rank(features["breakout_63d"], ascending=True)
    features["pullback_score"] = clip_score((features["pullback_from_20d_high"] + 0.20) * 350)
    features["absolute_momentum_score"] = pct_rank(features["return_63d"], ascending=True)
    features["relative_momentum_score"] = pct_rank(features["relative_strength_63d"], ascending=True)
    features["momentum_acceleration_score"] = pct_rank(features["return_20d"] - features["return_63d"] / 3.0, ascending=True)
    features["trend_persistence_score"] = pct_rank((features["px"] > features["ma20"]).astype(int) + (features["ma20"] > features["ma50"]).astype(int), ascending=True)
    features["exhaustion_risk_score"] = 100 - clip_score(features["rsi14"] - 70).fillna(0) * 2
    features["technical_score"] = (
        features["rsi_score"] * 0.12
        + features["trend_score"] * 0.18
        + features["macd_score"] * 0.14
        + features["bb_score"] * 0.10
        + features["volume_score"] * 0.08
        + features["volatility_score"] * 0.10
        + features["breakout_score"] * 0.14
        + features["pullback_score"] * 0.14
    )
    features["momentum_score"] = (
        features["absolute_momentum_score"] * 0.35
        + features["relative_momentum_score"] * 0.30
        + features["momentum_acceleration_score"] * 0.20
        + features["trend_persistence_score"] * 0.10
        + features["exhaustion_risk_score"] * 0.05
    )
    tech_cols = [
        "ticker", "latest_price_date", "px", "rsi14", "kdj_k", "kdj_d", "kdj_j", "macd", "macd_signal",
        "macd_hist", "bb_mid", "bb_upper_1", "bb_lower_1", "bb_upper_2", "bb_lower_2", "bb_upper_3",
        "bb_lower_3", "ma20", "ma50", "ema12", "ema26", "volume", "volume_ratio_20d", "volatility_20d",
        "return_20d", "return_63d", "relative_strength_63d", "breakout_63d", "pullback_from_20d_high",
        "technical_score",
    ]
    mom_cols = [
        "ticker", "latest_price_date", "absolute_momentum_score", "relative_momentum_score",
        "momentum_acceleration_score", "trend_persistence_score", "exhaustion_risk_score",
        "return_5d", "return_20d", "return_63d", "return_126d", "relative_strength_63d", "momentum_score",
    ]
    return features[tech_cols].copy(), features[mom_cols].copy(), blockers


def risk_regime_weight(tech: pd.DataFrame) -> tuple[float, str]:
    qqq = tech[tech["ticker"].eq("QQQ")]
    if qqq.empty:
        return 0.15, "UNKNOWN"
    row = qqq.iloc[0]
    if row["px"] > row["ma20"] > row["ma50"] and row["return_20d"] > 0:
        return 0.25, "RISK_ON"
    if row["px"] < row["ma50"]:
        return 0.05, "RISK_OFF"
    return 0.15, "NEUTRAL"


def build_rankings(tech: pd.DataFrame, momentum: pd.DataFrame) -> dict[str, pd.DataFrame]:
    base = tech.merge(momentum[["ticker", "momentum_score", "absolute_momentum_score", "relative_momentum_score", "momentum_acceleration_score", "trend_persistence_score", "exhaustion_risk_score"]], on="ticker", how="inner")
    dyn_weight, regime = risk_regime_weight(tech)
    base["base_score"] = base["technical_score"]
    variants = {
        "A1_BASELINE_CONTROL": (0.0, "A1_BASELINE_CONTROL", "fresh_technical_baseline"),
        "B_STATIC_MOMENTUM_BLEND": (0.20, "B_STATIC_MOMENTUM_BLEND", "fresh_static_momentum_blend"),
        "C_DYNAMIC_MOMENTUM_BLEND": (dyn_weight, "C_DYNAMIC_MOMENTUM_BLEND", f"fresh_dynamic_momentum_blend_{regime}"),
        "D_WEIGHT_OPTIMIZED_R1": (0.40, "D_WEIGHT_OPTIMIZED_R1", "fresh_d_weight_optimized_0.60_base_0.40_momentum"),
    }
    rankings: dict[str, pd.DataFrame] = {}
    for strategy, (weight, variant, lineage) in variants.items():
        out = base.copy()
        out["strategy"] = strategy
        out["applied_momentum_weight"] = weight
        out["final_score"] = out["base_score"] * (1 - weight) + out["momentum_score"] * weight
        out["rank"] = out["final_score"].rank(method="first", ascending=False).astype(int)
        out["latest_price_date"] = out["latest_price_date"].astype(str)
        out["eligible_flag"] = True
        out["eligibility_exclusion_reason"] = ""
        out["market_regime"] = regime
        out["score_lineage"] = lineage
        out["research_only"] = True
        ordered = [
            "strategy", "rank", "ticker", "final_score", "base_score", "momentum_score",
            "absolute_momentum_score", "relative_momentum_score", "momentum_acceleration_score",
            "trend_persistence_score", "exhaustion_risk_score", "market_regime", "applied_momentum_weight",
            "latest_price_date", "eligible_flag", "eligibility_exclusion_reason", "score_lineage", "research_only",
        ]
        rankings[strategy] = out.sort_values(["rank", "ticker"])[ordered].reset_index(drop=True)
    return rankings


def topn(frame: pd.DataFrame, n: int) -> pd.DataFrame:
    eligible = frame[frame["eligible_flag"].astype(str).str.upper().isin(["TRUE", "1"])]
    return eligible.nsmallest(n, "rank")


def overlap_matrix(rankings: dict[str, pd.DataFrame], n: int) -> list[dict[str, Any]]:
    sets = {s: set(topn(df, n)["ticker"]) for s, df in rankings.items()}
    rows = []
    for left in STRATEGIES:
        row = {"strategy": SHORT[left]}
        for right in STRATEGIES:
            row[SHORT[right]] = len(sets[left] & sets[right])
        rows.append(row)
    return rows


def write_top_summary(rankings: dict[str, pd.DataFrame], n: int, path: Path) -> None:
    rows: list[dict[str, Any]] = []
    for strategy, frame in rankings.items():
        for row in topn(frame, n).to_dict("records"):
            rows.append({"strategy": strategy, "rank": row["rank"], "ticker": row["ticker"], "final_score": row["final_score"], "latest_price_date": row["latest_price_date"]})
    write_csv(path, rows)


def comparator_path(label: str) -> Path | None:
    if label == "V21_108_R2":
        return V108_R2 / "D_WEIGHT_OPTIMIZED_R1/full_ranking.csv"
    if label == "V21_112_R1":
        p = V112_R1 / "D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv"
        return p if p.is_file() else V112 / "D_WEIGHT_OPTIMIZED_R1_full_ranking.csv"
    if label == "V21_113":
        return V113 / "D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv"
    return None


def load_comp(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    frame["rank"] = pd.to_numeric(frame["rank"], errors="coerce")
    if "final_score" in frame:
        frame["final_score"] = pd.to_numeric(frame["final_score"], errors="coerce")
    return frame.sort_values(["rank", "ticker"], na_position="last")


def entrants_removals(current: pd.DataFrame, label: str) -> list[dict[str, Any]]:
    path = comparator_path(label)
    if not path or not path.is_file():
        return [{"comparison": label, "view": "D_TOP20_AND_TOP50", "change_type": "MISSING_COMPARATOR", "ticker": ""}]
    old = load_comp(path)
    rows: list[dict[str, Any]] = []
    for n in [20, 50]:
        cur = set(topn(current, n)["ticker"])
        prev = set(old.nsmallest(n, "rank")["ticker"])
        for ticker in sorted(cur - prev):
            rows.append({"comparison": label, "view": f"top{n}", "change_type": "ENTRANT", "ticker": ticker})
        for ticker in sorted(prev - cur):
            rows.append({"comparison": label, "view": f"top{n}", "change_type": "REMOVAL", "ticker": ticker})
    if not rows:
        return [{"comparison": label, "view": "D_TOP20_AND_TOP50", "change_type": "NO_MEANINGFUL_RANK_MOVEMENT", "ticker": ""}]
    return rows


def score_delta_vs_v113(current: pd.DataFrame) -> list[dict[str, Any]]:
    path = comparator_path("V21_113")
    if not path or not path.is_file():
        return [{"ticker": "", "status": "MISSING_V21_113_COMPARATOR"}]
    old = load_comp(path)
    merged = current.merge(old[["ticker", "rank", "final_score"]], on="ticker", how="outer", suffixes=("_v21_114", "_v21_113"))
    rows = []
    for row in merged.to_dict("records"):
        new_score = row.get("final_score_v21_114")
        old_score = row.get("final_score_v21_113")
        rows.append({
            "ticker": row.get("ticker", ""),
            "rank_v21_114": row.get("rank_v21_114", ""),
            "rank_v21_113": row.get("rank_v21_113", ""),
            "final_score_v21_114": new_score,
            "final_score_v21_113": old_score,
            "score_delta": "" if pd.isna(new_score) or pd.isna(old_score) else float(new_score - old_score),
        })
    return rows


def stale_reports(price: pd.DataFrame, universe: set[str], blockers: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    latest = price.groupby("symbol")["date"].max().dt.strftime("%Y-%m-%d").to_dict() if len(price) else {}
    stale = []
    for ticker in sorted(universe):
        d = clean(latest.get(ticker))
        if d < EXPECTED_DATE:
            stale.append({"ticker": ticker, "latest_price_date": d, "expected_min_latest_price_date": EXPECTED_DATE, "reason": "STALE_OR_MISSING_CANONICAL_PRICE"})
    factor = []
    for row in blockers:
        factor.append({**row, "stale_factor_cache_flag": False, "required_action": "RECOMPUTE_FEATURE_INPUT_OR_BLOCK_PASS"})
    return stale, factor


def write_report(summary: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    if summary["FINAL_STATUS"].startswith("PASS"):
        answer = "V21.114 recomputed A1/B/C/D from the 2026-06-25 canonical OHLCV panel without V21.112/V21.113 ranking inputs."
    else:
        answer = "V21.114 did not archive as a true latest-data recompute. See blocker details below."
    lines = [
        f"# {STAGE}",
        "",
        f"FINAL_STATUS={summary['FINAL_STATUS']}",
        f"DECISION={summary['DECISION']}",
        "",
        "## Direct Answer",
        answer,
        "",
        "## Freshness",
        f"- canonical_price_panel_latest_date={summary['canonical_price_panel_latest_date']}",
        f"- technical_features_latest_date={summary['technical_features_latest_date']}",
        f"- momentum_features_latest_date={summary['momentum_features_latest_date']}",
        f"- stale_factor_input_count={summary['stale_factor_input_count']}",
        "",
        "## Reuse Controls",
        f"- read_v21_112_ranking_as_input={str(summary['read_v21_112_ranking_as_input']).lower()}",
        f"- read_v21_113_ranking_as_input={str(summary['read_v21_113_ranking_as_input']).lower()}",
        f"- copied_prior_ranking_files={str(summary['copied_prior_ranking_files']).lower()}",
        "",
        "## Blockers",
    ]
    if blockers:
        lines.extend([f"- {clean(b.get('ticker'))}: {clean(b.get('reason')) or clean(b.get('missing_features'))}" for b in blockers[:100]])
    else:
        lines.append("- none")
    lines.extend([
        "",
        "## Controls",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "protected_outputs_modified=false",
    ])
    (OUT / "V21.114_true_latest_data_abcd_full_recompute_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    universe, manifest = load_universe()
    price, latest_price, price_manifest = load_price_panel(universe)
    manifest.extend(price_manifest)
    tech, momentum, blockers = compute_features(price)
    technical_latest = max(tech["latest_price_date"], default="") if not tech.empty else ""
    momentum_latest = max(momentum["latest_price_date"], default="") if not momentum.empty else ""

    write_csv(OUT / "recompute_input_manifest.csv", manifest)
    write_csv(OUT / "technical_feature_recompute_latest.csv", tech.to_dict("records") if not tech.empty else [])
    write_csv(OUT / "momentum_feature_recompute_latest.csv", momentum.to_dict("records") if not momentum.empty else [])

    stale_tickers, factor_blockers = stale_reports(price, universe, blockers)
    rankings: dict[str, pd.DataFrame] = {}
    stale_factor_count = len(factor_blockers)
    if latest_price >= EXPECTED_DATE and technical_latest >= EXPECTED_DATE and momentum_latest >= EXPECTED_DATE and stale_factor_count == 0:
        rankings = build_rankings(tech, momentum)
    elif latest_price >= EXPECTED_DATE and technical_latest >= EXPECTED_DATE and momentum_latest >= EXPECTED_DATE:
        # Partial rankings are useful evidence, but pass remains blocked.
        rankings = build_rankings(tech, momentum)

    if rankings:
        for strategy, frame in rankings.items():
            frame.to_csv(OUT / f"{strategy}_true_latest_ranking.csv", index=False)
        write_top_summary(rankings, 20, OUT / "ABCD_top20_summary.csv")
        write_top_summary(rankings, 50, OUT / "ABCD_top50_summary.csv")
        write_csv(OUT / "ABCD_top20_overlap_matrix.csv", overlap_matrix(rankings, 20))
        write_csv(OUT / "ABCD_top50_overlap_matrix.csv", overlap_matrix(rankings, 50))
        d = rankings["D_WEIGHT_OPTIMIZED_R1"]
        for label, filename in [
            ("V21_108_R2", "D_entrants_removals_vs_V21_108_R2.csv"),
            ("V21_112_R1", "D_entrants_removals_vs_V21_112_R1.csv"),
            ("V21_113", "D_entrants_removals_vs_V21_113.csv"),
        ]:
            write_csv(OUT / filename, entrants_removals(d, label))
        write_csv(OUT / "D_score_delta_vs_V21_113.csv", score_delta_vs_v113(d))
    else:
        for strategy in STRATEGIES:
            write_csv(OUT / f"{strategy}_true_latest_ranking.csv", [], ["empty"])
        for name in [
            "ABCD_top20_summary.csv", "ABCD_top50_summary.csv", "ABCD_top20_overlap_matrix.csv",
            "ABCD_top50_overlap_matrix.csv", "D_entrants_removals_vs_V21_108_R2.csv",
            "D_entrants_removals_vs_V21_112_R1.csv", "D_entrants_removals_vs_V21_113.csv",
            "D_score_delta_vs_V21_113.csv",
        ]:
            write_csv(OUT / name, [], ["empty"])

    write_csv(OUT / "stale_or_missing_ticker_report.csv", stale_tickers, ["ticker", "latest_price_date", "expected_min_latest_price_date", "reason"])
    write_csv(OUT / "stale_factor_cache_report.csv", factor_blockers, list(factor_blockers[0].keys()) if factor_blockers else ["ticker", "reason", "stale_factor_cache_flag", "required_action"])

    copied_prior = False
    if rankings:
        current_hashes = {strategy: sha256(OUT / f"{strategy}_true_latest_ranking.csv") for strategy in STRATEGIES}
        prior_paths = [
            V112 / f"{s}_full_ranking.csv" for s in STRATEGIES
        ] + [
            V113 / f"{s}_latest_ranking.csv" for s in STRATEGIES
        ]
        prior_hashes = {sha256(p) for p in prior_paths if p.is_file()}
        copied_prior = any(h in prior_hashes for h in current_hashes.values())

    dates_ok = latest_price >= EXPECTED_DATE and technical_latest >= EXPECTED_DATE and momentum_latest >= EXPECTED_DATE
    ranking_dates = {s: (max(rankings[s]["latest_price_date"], default="") if rankings else "") for s in STRATEGIES}
    full_recompute = bool(dates_ok and stale_factor_count == 0 and rankings and not copied_prior)
    if copied_prior:
        final_status = "BLOCKED_V21_114_PRIOR_RANKING_REUSE_DETECTED"
        decision = "DO_NOT_ARCHIVE_AS_TRUE_LATEST_DATA"
    elif not dates_ok or not rankings:
        final_status = "BLOCKED_V21_114_MISSING_RECOMPUTE_PRODUCER"
        decision = "DO_NOT_ARCHIVE_AS_TRUE_LATEST_DATA"
    elif stale_factor_count:
        final_status = "BLOCKED_V21_114_STALE_FACTOR_CACHE"
        decision = "DO_NOT_ARCHIVE_AS_TRUE_LATEST_DATA"
    else:
        final_status = "PASS_V21_114_TRUE_LATEST_DATA_ABCD_FULL_RECOMPUTE"
        decision = "TRUE_LATEST_DATA_ABCD_FULL_RECOMPUTE_READY_RESEARCH_ONLY"

    d_top20 = []
    d_top50 = []
    row_counts = {s: {"rows": 0, "eligible": 0, "excluded": 0} for s in STRATEGIES}
    if rankings:
        for s, frame in rankings.items():
            eligible = int(frame["eligible_flag"].astype(str).str.upper().isin(["TRUE", "1"]).sum())
            row_counts[s] = {"rows": int(len(frame)), "eligible": eligible, "excluded": int(len(frame) - eligible)}
        d_top20 = [{"ticker": r["ticker"], "final_score": r["final_score"]} for r in topn(rankings["D_WEIGHT_OPTIMIZED_R1"], 20).to_dict("records")]
        d_top50 = list(topn(rankings["D_WEIGHT_OPTIMIZED_R1"], 50)["ticker"])

    summary = {
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "latest_price_date": latest_price,
        "canonical_price_panel_latest_date": latest_price,
        "technical_features_latest_date": technical_latest,
        "momentum_features_latest_date": momentum_latest,
        "A1_ranking_latest_date": ranking_dates["A1_BASELINE_CONTROL"],
        "B_ranking_latest_date": ranking_dates["B_STATIC_MOMENTUM_BLEND"],
        "C_ranking_latest_date": ranking_dates["C_DYNAMIC_MOMENTUM_BLEND"],
        "D_ranking_latest_date": ranking_dates["D_WEIGHT_OPTIMIZED_R1"],
        "stale_or_missing_ticker_count": len(stale_tickers),
        "stale_factor_input_count": stale_factor_count,
        "read_v21_112_ranking_as_input": False,
        "read_v21_113_ranking_as_input": False,
        "copied_prior_ranking_files": copied_prior,
        "full_recompute_confirmed": full_recompute,
        "A1_rows": row_counts["A1_BASELINE_CONTROL"]["rows"],
        "B_rows": row_counts["B_STATIC_MOMENTUM_BLEND"]["rows"],
        "C_rows": row_counts["C_DYNAMIC_MOMENTUM_BLEND"]["rows"],
        "D_rows": row_counts["D_WEIGHT_OPTIMIZED_R1"]["rows"],
        "A1_eligible": row_counts["A1_BASELINE_CONTROL"]["eligible"],
        "B_eligible": row_counts["B_STATIC_MOMENTUM_BLEND"]["eligible"],
        "C_eligible": row_counts["C_DYNAMIC_MOMENTUM_BLEND"]["eligible"],
        "D_eligible": row_counts["D_WEIGHT_OPTIMIZED_R1"]["eligible"],
        "A1_excluded": row_counts["A1_BASELINE_CONTROL"]["excluded"],
        "B_excluded": row_counts["B_STATIC_MOMENTUM_BLEND"]["excluded"],
        "C_excluded": row_counts["C_DYNAMIC_MOMENTUM_BLEND"]["excluded"],
        "D_excluded": row_counts["D_WEIGHT_OPTIMIZED_R1"]["excluded"],
        "D_top20": d_top20,
        "D_top50": d_top50,
        "protected_outputs_modified": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
        "report_path": rel(OUT / "V21.114_true_latest_data_abcd_full_recompute_report.md"),
    }
    write_json(OUT / "V21.114_true_latest_data_abcd_full_recompute_summary.json", summary)
    write_report(summary, factor_blockers)
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    run()
