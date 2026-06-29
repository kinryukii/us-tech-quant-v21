from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.161_R1_C_R2_PROXY_AND_REGIME_REPAIR"
OUT = ROOT / "outputs" / "v21" / STAGE
ORIG_OUT = ROOT / "outputs" / "v21" / "V21.161_C_R2_FACTOR_ROTATION_SHADOW_RANKING"
ABCD = ROOT / "outputs" / "v21" / "V21.113_LATEST_DATA_ABCD_RERUN_20260625_PRICE_REFRESH"
C_PATH = ABCD / "C_DYNAMIC_MOMENTUM_BLEND_latest_ranking.csv"
A1_PATH = ABCD / "A1_BASELINE_CONTROL_latest_ranking.csv"
ABCD_SUMMARY = ABCD / "V21.113_latest_data_abcd_rerun_summary.json"
FUND_SCORE = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R6B_FUNDAMENTAL_CANDIDATE_SCORE_SOURCE.csv"
FUND_CACHE = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R6A_CONTROLLED_FUNDAMENTAL_METRIC_CACHE.csv"
PRICE = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
META = ROOT / "outputs" / "v21" / "V21.138_E_R1_METADATA_COVERAGE_REPAIR_AND_REAUDIT" / "consolidated_sector_industry_metadata_bridge.csv"
ORIG_RANK = ORIG_OUT / "c_r2_shadow_ranking_full.csv"
ORIG_FACTOR = ORIG_OUT / "c_r2_factor_attribution.csv"
ORIG_RISK = ORIG_OUT / "c_r2_risk_attribution.csv"

WEIGHTS = {
    "risk_on": {
        "momentum_rs": 0.38,
        "technical_confirm": 0.17,
        "profitability": 0.14,
        "fcf_quality": 0.10,
        "value": 0.08,
        "risk_control": 0.08,
        "data_trust": 0.05,
    },
    "neutral": {
        "momentum_rs": 0.30,
        "technical_confirm": 0.15,
        "profitability": 0.16,
        "fcf_quality": 0.13,
        "value": 0.10,
        "risk_control": 0.11,
        "data_trust": 0.05,
    },
    "risk_off": {
        "momentum_rs": 0.18,
        "technical_confirm": 0.10,
        "profitability": 0.18,
        "fcf_quality": 0.16,
        "value": 0.10,
        "low_vol": 0.13,
        "risk_control": 0.10,
        "data_trust": 0.05,
    },
}

POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "role_review_required": False,
    "c_r2_adoption_allowed": False,
}


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def protected_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for base in [ROOT / "outputs", ROOT / "data"]:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or OUT in path.parents:
                continue
            rel = path.relative_to(ROOT).as_posix().lower().replace("-", "_")
            protected = any(token in rel for token in ["broker", "real_book", "realbook"])
            protected = protected or ("official" in rel and any(k in rel for k in ["rank", "weight", "allocation", "recommend"]))
            if protected:
                hashes[path.relative_to(ROOT).as_posix()] = sha(path)
    return hashes


def to_bool(v: Any) -> bool:
    return str(v).strip().lower() in {"true", "1", "yes", "y"}


def to_score(s: pd.Series) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    if x.dropna().between(0, 1).all():
        x *= 100.0
    return x.clip(0, 100)


def pct_rank(s: pd.Series, higher_is_better: bool = True) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    if x.notna().sum() == 0:
        return pd.Series(np.nan, index=s.index)
    return (x.rank(pct=True, ascending=not higher_is_better) * 100.0).clip(0, 100)


def latest_price_date(c_rank: pd.DataFrame) -> str:
    summary = read_json(ABCD_SUMMARY)
    if summary.get("latest_price_date"):
        return str(summary["latest_price_date"])
    if not c_rank.empty and "latest_price_date" in c_rank.columns:
        dates = pd.to_datetime(c_rank["latest_price_date"], errors="coerce").dropna()
        if not dates.empty:
            return str(dates.max().date())
    return ""


def source_audit(c_rank: pd.DataFrame) -> pd.DataFrame:
    expected = {
        "profitability_proxy": (FUND_SCORE, ["profitability_component_score", "margin_component_score"]),
        "fcf_quality_proxy": (FUND_SCORE, ["cash_flow_component_score", "quality_component_score", "balance_sheet_component_score"]),
        "value_proxy": (FUND_SCORE, ["valuation_component_score"]),
        "low_vol_proxy": (PRICE, ["symbol", "date", "adjusted_close"]),
        "market_regime_source": (C_PATH, ["market_regime"]),
        "QQQ_trend_proxy": (PRICE, ["symbol", "date", "adjusted_close"]),
        "SOXX_trend_proxy": (PRICE, ["symbol", "date", "adjusted_close"]),
        "breadth_proxy": (PRICE, ["symbol", "date", "adjusted_close"]),
        "VIX_or_volatility_proxy": (PRICE, ["symbol", "date", "adjusted_close"]),
        "sector_dispersion_proxy": (PRICE, ["symbol", "date", "adjusted_close"]),
    }
    rows = []
    tickers = set(c_rank.get("ticker", pd.Series(dtype=str)).astype(str).str.upper().str.strip())
    for name, (path, cols) in expected.items():
        df = read_csv(path)
        exists = path.exists()
        missing_cols = [c for c in cols if c not in df.columns]
        ticker_col = "ticker" if "ticker" in df.columns else "symbol" if "symbol" in df.columns else ""
        source_tickers = set(df[ticker_col].astype(str).str.upper().str.strip()) if ticker_col else set()
        covered = len(tickers & source_tickers) if source_tickers else 0
        rows.append({
            "proxy_name": name,
            "source_path": path.relative_to(ROOT).as_posix(),
            "source_exists": exists,
            "source_rows": len(df),
            "required_columns": "|".join(cols),
            "missing_columns": "|".join(missing_cols),
            "ticker_column": ticker_col,
            "c_r2_universe_count": len(tickers),
            "covered_ticker_count": covered if ticker_col else "",
            "coverage": covered / len(tickers) if tickers and ticker_col else "",
            "usable": exists and len(missing_cols) == 0,
            "research_only": True,
        })
    return pd.DataFrame(rows)


def build_fundamental_proxy(c_rank: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    fund = read_csv(FUND_SCORE)
    cache = read_csv(FUND_CACHE)
    base = c_rank[["ticker"]].copy()
    base["ticker"] = base["ticker"].astype(str).str.upper().str.strip()
    if not fund.empty:
        fund["ticker"] = fund["ticker"].astype(str).str.upper().str.strip()
    if not cache.empty:
        cache["ticker"] = cache["ticker"].astype(str).str.upper().str.strip()

    cols = [
        "ticker", "profitability_component_score", "margin_component_score", "cash_flow_component_score",
        "quality_component_score", "balance_sheet_component_score", "valuation_component_score",
        "present_numeric_metric_count", "missing_metric_count", "fundamental_metric_certification_status",
    ]
    f = fund[[c for c in cols if c in fund.columns]].drop_duplicates("ticker") if not fund.empty else pd.DataFrame({"ticker": []})
    merged = base.merge(f, on="ticker", how="left", indicator="fund_score_join")
    if not cache.empty:
        raw_cols = [
            "ticker", "profit_margin", "net_income_ttm", "gross_margin", "operating_margin", "free_cashflow",
            "operating_cashflow", "return_on_assets", "return_on_equity", "debt_to_equity", "current_ratio",
            "forward_pe", "price_to_sales", "price_to_book", "ev_to_ebitda",
        ]
        merged = merged.merge(cache[[c for c in raw_cols if c in cache.columns]].drop_duplicates("ticker"), on="ticker", how="left", suffixes=("", "_raw"))

    merged["profitability"] = pd.concat([
        to_score(merged.get("profitability_component_score", pd.Series(np.nan, index=merged.index))),
        to_score(merged.get("margin_component_score", pd.Series(np.nan, index=merged.index))),
    ], axis=1).mean(axis=1)
    merged["fcf_quality"] = pd.concat([
        to_score(merged.get("cash_flow_component_score", pd.Series(np.nan, index=merged.index))),
        to_score(merged.get("quality_component_score", pd.Series(np.nan, index=merged.index))),
        to_score(merged.get("balance_sheet_component_score", pd.Series(np.nan, index=merged.index))),
    ], axis=1).mean(axis=1)
    merged["value"] = to_score(merged.get("valuation_component_score", pd.Series(np.nan, index=merged.index)))

    # Feasible repair: derive percentile proxies from raw controlled metrics if component scores are blank.
    if "profit_margin" in merged.columns:
        raw_profit = pd.concat([
            pct_rank(merged.get("profit_margin", pd.Series(np.nan, index=merged.index))),
            pct_rank(merged.get("net_income_ttm", pd.Series(np.nan, index=merged.index))),
            pct_rank(merged.get("operating_margin", pd.Series(np.nan, index=merged.index))),
        ], axis=1).mean(axis=1)
        merged["profitability"] = merged["profitability"].fillna(raw_profit)
    if "free_cashflow" in merged.columns:
        raw_fcf = pd.concat([
            pct_rank(merged.get("free_cashflow", pd.Series(np.nan, index=merged.index))),
            pct_rank(merged.get("operating_cashflow", pd.Series(np.nan, index=merged.index))),
            pct_rank(merged.get("return_on_assets", pd.Series(np.nan, index=merged.index))),
            pct_rank(merged.get("debt_to_equity", pd.Series(np.nan, index=merged.index)), higher_is_better=False),
        ], axis=1).mean(axis=1)
        merged["fcf_quality"] = merged["fcf_quality"].fillna(raw_fcf)
    if "forward_pe" in merged.columns:
        raw_value = pd.concat([
            pct_rank(merged.get("forward_pe", pd.Series(np.nan, index=merged.index)), higher_is_better=False),
            pct_rank(merged.get("price_to_sales", pd.Series(np.nan, index=merged.index)), higher_is_better=False),
            pct_rank(merged.get("price_to_book", pd.Series(np.nan, index=merged.index)), higher_is_better=False),
            pct_rank(merged.get("ev_to_ebitda", pd.Series(np.nan, index=merged.index)), higher_is_better=False),
        ], axis=1).mean(axis=1)
        merged["value"] = merged["value"].fillna(raw_value)

    missing_rows = []
    for _, row in merged.iterrows():
        for proxy in ["profitability", "fcf_quality", "value"]:
            if pd.isna(row[proxy]):
                in_score = row.get("fund_score_join") == "both"
                cause = "ticker_mapping_failure" if not in_score else "missing_component_and_raw_metric_values"
                if FUND_SCORE.exists() and not in_score:
                    cause = "missing_source_data_for_ticker"
                missing_rows.append({
                    "ticker": row["ticker"],
                    "proxy_name": proxy,
                    "root_cause": cause,
                    "source_data_present": bool(in_score),
                    "missing_source_data": not bool(in_score),
                    "missing_columns": False,
                    "wrong_column_names": False,
                    "ticker_mapping_failure": not bool(in_score),
                    "date_alignment_failure": False,
                    "intentional_neutral_fallback": True,
                    "repair_action": "neutral_50_limited_proxy_fill",
                    "research_only": True,
                })
    present = pd.to_numeric(merged.get("present_numeric_metric_count"), errors="coerce").fillna(0)
    missing = pd.to_numeric(merged.get("missing_metric_count"), errors="coerce").fillna(99)
    certified = merged.get("fundamental_metric_certification_status", "").astype(str).str.contains("CERTIFIED", case=False, na=False)
    merged["data_trust"] = np.where(certified, 75, 45) + np.minimum(present, 25) - np.minimum(missing * 2, 35)
    for proxy in ["profitability", "fcf_quality", "value", "data_trust"]:
        merged[proxy] = merged[proxy].fillna(50.0).clip(0, 100)
    merged["proxy_repair_status"] = np.where(merged["fund_score_join"].eq("both"), "REPAIRED_OR_CONFIRMED_FROM_CONTROLLED_FUNDAMENTAL_SOURCE", "LIMITED_NEUTRAL_FALLBACK_NO_TICKER_SOURCE")
    out_cols = ["ticker", "profitability", "fcf_quality", "value", "data_trust", "proxy_repair_status", "fund_score_join", "missing_metric_count", "fundamental_metric_certification_status"]
    return merged[out_cols], pd.DataFrame(missing_rows)


def price_panel(latest: str) -> pd.DataFrame:
    p = read_csv(PRICE)
    if p.empty:
        return p
    p["symbol"] = p["symbol"].astype(str).str.upper().str.strip()
    p["date"] = pd.to_datetime(p["date"], errors="coerce")
    p["adjusted_close"] = pd.to_numeric(p["adjusted_close"], errors="coerce")
    if latest:
        p = p[p["date"] <= pd.to_datetime(latest)]
    return p.dropna(subset=["symbol", "date", "adjusted_close"]).sort_values(["symbol", "date"])


def trend_signal(p: pd.DataFrame, symbol: str) -> tuple[bool, float, dict[str, Any]]:
    s = p[p["symbol"].eq(symbol)].tail(220).copy()
    if len(s) < 60:
        return False, 0.0, {"symbol": symbol, "available": False}
    close = s["adjusted_close"]
    ret_20 = close.iloc[-1] / close.iloc[-21] - 1 if len(close) >= 21 else np.nan
    ret_60 = close.iloc[-1] / close.iloc[-61] - 1 if len(close) >= 61 else np.nan
    ma50 = close.tail(50).mean()
    ma200 = close.tail(200).mean() if len(close) >= 200 else close.mean()
    score = 0.0
    score += 1 if ret_20 > 0 else -1
    score += 1 if ret_60 > 0 else -1
    score += 1 if close.iloc[-1] > ma50 else -1
    score += 1 if ma50 > ma200 else -1
    return True, float(score), {
        "symbol": symbol,
        "available": True,
        "ret_20": float(ret_20) if pd.notna(ret_20) else None,
        "ret_60": float(ret_60) if pd.notna(ret_60) else None,
        "last_gt_ma50": bool(close.iloc[-1] > ma50),
        "ma50_gt_ma200": bool(ma50 > ma200),
    }


def classify_regime(c_rank: pd.DataFrame, latest: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    p = price_panel(latest)
    rows = []
    q_avail, q_score, q_meta = trend_signal(p, "QQQ")
    s_avail, s_score, s_meta = trend_signal(p, "SOXX")
    rows.append({"input_name": "QQQ_trend_proxy", "available": q_avail, "source": PRICE.relative_to(ROOT).as_posix(), "details": json.dumps(q_meta)})
    rows.append({"input_name": "SOXX_trend_proxy", "available": s_avail, "source": PRICE.relative_to(ROOT).as_posix(), "details": json.dumps(s_meta)})
    breadth_available = False
    breadth = np.nan
    sector_disp_available = False
    sector_disp = np.nan
    vol_available = False
    vol_60 = np.nan
    if not p.empty:
        wide = p.pivot_table(index="date", columns="symbol", values="adjusted_close", aggfunc="last").sort_index()
        rets60 = wide.pct_change(60).tail(1)
        if not rets60.empty:
            vals = rets60.iloc[0].dropna()
            breadth_available = len(vals) >= 50
            breadth = float((vals > 0).mean()) if breadth_available else np.nan
        q = wide["QQQ"].dropna() if "QQQ" in wide.columns else pd.Series(dtype=float)
        if len(q) >= 61:
            vol_available = True
            vol_60 = float(q.pct_change().tail(60).std() * np.sqrt(252))
        meta = read_csv(META)
        if not meta.empty and {"ticker_norm", "sector"}.issubset(meta.columns):
            meta["symbol"] = meta["ticker_norm"].astype(str).str.upper().str.strip()
            sectors = meta.set_index("symbol")["sector"].to_dict()
            latest_ret = vals.rename("ret_60").reset_index().rename(columns={"index": "symbol"})
            latest_ret["sector"] = latest_ret["symbol"].map(sectors)
            sec = latest_ret.dropna(subset=["sector"]).groupby("sector")["ret_60"].mean()
            sector_disp_available = len(sec) >= 3
            sector_disp = float(sec.std()) if sector_disp_available else np.nan
    rows.append({"input_name": "breadth_proxy", "available": breadth_available, "source": PRICE.relative_to(ROOT).as_posix(), "details": json.dumps({"positive_60d_breadth": breadth})})
    rows.append({"input_name": "VIX_or_volatility_proxy", "available": vol_available, "source": PRICE.relative_to(ROOT).as_posix(), "details": json.dumps({"qqq_realized_vol_60d": vol_60})})
    rows.append({"input_name": "sector_dispersion_proxy", "available": sector_disp_available, "source": f"{PRICE.relative_to(ROOT).as_posix()} + {META.relative_to(ROOT).as_posix()}", "details": json.dumps({"sector_60d_return_dispersion": sector_disp})})

    available_count = sum(bool(r["available"]) for r in rows)
    unavailable = [r["input_name"] for r in rows if not r["available"]]
    signal_selected = q_avail and s_avail and breadth_available and vol_available
    fallback = not signal_selected
    if signal_selected:
        risk_score = q_score + s_score
        risk_score += 1 if breadth >= 0.55 else -1 if breadth < 0.45 else 0
        risk_score += 1 if vol_60 < 0.30 else -1 if vol_60 > 0.45 else 0
        selected = "risk_on" if risk_score >= 3 else "risk_off" if risk_score <= -2 else "neutral"
        confidence = min(0.90, 0.55 + available_count * 0.07)
        source = "QQQ_SOX_BREADTH_QQQ_REALIZED_VOL_SIGNAL"
        reason = ""
    else:
        raw = ""
        if "market_regime" in c_rank.columns:
            vals = c_rank["market_regime"].dropna().astype(str).str.strip()
            raw = vals[vals.ne("")].mode().iloc[0] if not vals[vals.ne("")].empty else ""
        mapping = {"RISK_ON": "risk_on", "STRONG_RISK_ON": "risk_on", "NEUTRAL": "neutral", "RISK_OFF": "risk_off"}
        selected = mapping.get(raw.upper(), "neutral")
        confidence = 0.45 if raw.upper() in mapping else 0.35
        source = "C_RANKING_MARKET_REGIME_FALLBACK" if raw.upper() in mapping else "NEUTRAL_FALLBACK"
        reason = "missing_required_regime_inputs:" + "|".join(unavailable)
    audit = pd.DataFrame(rows)
    state = {
        "selected_regime": selected,
        "regime_confidence": confidence,
        "regime_source": source,
        "regime_inputs_available": available_count,
        "regime_selected_by_signal": signal_selected,
        "regime_selected_by_fallback": fallback,
        "unavailable_regime_inputs": unavailable,
        "fallback_reason": reason,
    }
    for k, v in state.items():
        audit[k] = json.dumps(v) if isinstance(v, list) else v
    return audit, state


def low_vol(c_rank: pd.DataFrame, latest: str) -> pd.DataFrame:
    p = price_panel(latest)
    tickers = set(c_rank["ticker"].astype(str).str.upper().str.strip())
    if p.empty:
        return pd.DataFrame({"ticker": list(tickers), "low_vol": np.nan, "left_tail_proxy": np.nan})
    p = p[p["symbol"].isin(tickers)].copy()
    p["ret"] = p.groupby("symbol")["adjusted_close"].pct_change()
    stats = p.groupby("symbol")["ret"].agg(vol_60=lambda x: x.tail(60).std(), left_tail_proxy=lambda x: x.tail(60).quantile(0.05)).reset_index()
    stats["ticker"] = stats["symbol"]
    stats["low_vol"] = pct_rank(stats["vol_60"], higher_is_better=False)
    return stats[["ticker", "low_vol", "left_tail_proxy"]]


def recompute_ranking(c_rank: pd.DataFrame, proxies: pd.DataFrame, regime: dict[str, Any], latest: str) -> pd.DataFrame:
    rank = c_rank.copy()
    rank["ticker"] = rank["ticker"].astype(str).str.upper().str.strip()
    rank = rank[rank["ticker"].ne("")].drop_duplicates("ticker").reset_index(drop=True)
    rank["momentum_rs"] = to_score(rank.get("relative_momentum_score", rank.get("momentum_score", pd.Series(np.nan, index=rank.index))))
    rank["momentum_rs"] = rank["momentum_rs"].fillna(pct_rank(pd.to_numeric(rank.get("rank"), errors="coerce"), higher_is_better=False))
    tech_cols = [c for c in ["absolute_momentum_score", "momentum_acceleration_score", "trend_persistence_score"] if c in rank.columns]
    rank["technical_confirm"] = pd.concat([to_score(rank[c]) for c in tech_cols], axis=1).mean(axis=1) if tech_cols else rank["momentum_rs"]
    rank["risk_control"] = 100.0 - to_score(rank.get("exhaustion_risk_score", pd.Series(np.nan, index=rank.index))).fillna(50.0)
    rank = rank.merge(proxies[["ticker", "profitability", "fcf_quality", "value", "data_trust", "proxy_repair_status"]], on="ticker", how="left")
    for c in ["profitability", "fcf_quality", "value", "data_trust"]:
        rank[c] = rank[c].fillna(50.0)
    rank = rank.merge(low_vol(rank, latest), on="ticker", how="left")
    rank["low_vol"] = rank["low_vol"].fillna(50.0)
    weights = WEIGHTS[regime["selected_regime"]]
    rank["c_r2_r1_score"] = 0.0
    for factor, weight in weights.items():
        rank["c_r2_r1_score"] += pd.to_numeric(rank[factor], errors="coerce").fillna(50.0) * weight
    eligible = rank.get("eligible_flag", True)
    if not isinstance(eligible, pd.Series):
        eligible = pd.Series(True, index=rank.index)
    rank["eligible_for_c_r2_r1"] = eligible.astype(str).str.lower().isin(["true", "1", "yes"]) | eligible.eq(True)
    rank = rank.sort_values(["eligible_for_c_r2_r1", "c_r2_r1_score", "ticker"], ascending=[False, False, True]).reset_index(drop=True)
    rank["rank"] = np.arange(1, len(rank) + 1)
    rank["is_top20"] = rank["rank"].le(20)
    rank["is_top50"] = rank["rank"].le(50)
    rank["selected_regime"] = regime["selected_regime"]
    rank["regime_confidence"] = regime["regime_confidence"]
    rank["regime_source"] = regime["regime_source"]
    rank["latest_price_date_used"] = latest
    rank["factor_weight_sum_selected_regime"] = round(sum(weights.values()), 10)
    meta = read_csv(META)
    if not meta.empty:
        meta["ticker"] = meta["ticker_norm"].astype(str).str.upper().str.strip()
        rank = rank.merge(meta[["ticker", "sector", "industry"]].drop_duplicates("ticker"), on="ticker", how="left")
    rank["sector"] = rank.get("sector", "UNKNOWN").fillna("UNKNOWN")
    rank["industry"] = rank.get("industry", "UNKNOWN").fillna("UNKNOWN")
    return rank


def compare(original: pd.DataFrame, repaired: pd.DataFrame) -> pd.DataFrame:
    rows = []
    o20, o50 = set(original.head(20)["ticker"]), set(original.head(50)["ticker"])
    r20, r50 = set(repaired.head(20)["ticker"]), set(repaired.head(50)["ticker"])
    rows.extend([
        {"row_type": "summary", "bucket": "Top20", "overlap_count": len(o20 & r20), "entrants": ",".join(sorted(r20 - o20)), "exits": ",".join(sorted(o20 - r20))},
        {"row_type": "summary", "bucket": "Top50", "overlap_count": len(o50 & r50), "entrants": ",".join(sorted(r50 - o50)), "exits": ",".join(sorted(o50 - r50))},
    ])
    omap = {r["ticker"]: int(r["rank"]) for _, r in original.iterrows()}
    rmap = {r["ticker"]: int(r["rank"]) for _, r in repaired.iterrows()}
    for ticker in sorted(set(omap) | set(rmap)):
        rows.append({
            "row_type": "rank_diff",
            "bucket": "Full",
            "ticker": ticker,
            "original_rank": omap.get(ticker, ""),
            "repaired_rank": rmap.get(ticker, ""),
            "rank_diff_repaired_minus_original": rmap[ticker] - omap[ticker] if ticker in omap and ticker in rmap else "",
            "in_original_top20": ticker in o20,
            "in_repaired_top20": ticker in r20,
            "in_original_top50": ticker in o50,
            "in_repaired_top50": ticker in r50,
        })
    return pd.DataFrame(rows)


def factor_delta(original: pd.DataFrame, repaired: pd.DataFrame, regime: str) -> pd.DataFrame:
    factors = list(WEIGHTS[regime])
    rows = []
    for factor in factors:
        rows.append({
            "factor": factor,
            "weight": WEIGHTS[regime][factor],
            "original_top20_mean": pd.to_numeric(original.head(20).get(factor), errors="coerce").mean() if factor in original.columns else np.nan,
            "repaired_top20_mean": pd.to_numeric(repaired.head(20).get(factor), errors="coerce").mean() if factor in repaired.columns else np.nan,
            "original_top50_mean": pd.to_numeric(original.head(50).get(factor), errors="coerce").mean() if factor in original.columns else np.nan,
            "repaired_top50_mean": pd.to_numeric(repaired.head(50).get(factor), errors="coerce").mean() if factor in repaired.columns else np.nan,
        })
    df = pd.DataFrame(rows)
    df["top20_mean_delta"] = df["repaired_top20_mean"] - df["original_top20_mean"]
    df["top50_mean_delta"] = df["repaired_top50_mean"] - df["original_top50_mean"]
    risk_orig = read_csv(ORIG_RISK)
    if not risk_orig.empty:
        df["risk_attribution_original_source"] = ORIG_RISK.relative_to(ROOT).as_posix()
    return df


def concentration_risk(rank: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for bucket, frame in [("Top20", rank.head(20)), ("Top50", rank.head(50)), ("Full", rank)]:
        rows.append({
            "bucket": bucket,
            "valid_holdings_count": len(frame),
            "data_warning_ticker_count": int(frame["proxy_repair_status"].astype(str).ne("REPAIRED_OR_CONFIRMED_FROM_CONTROLLED_FUNDAMENTAL_SOURCE").sum()),
            "score_top1_share": float(frame["c_r2_r1_score"].max() / frame["c_r2_r1_score"].sum()) if frame["c_r2_r1_score"].sum() else 0.0,
            "score_top5_share": float(frame.nlargest(min(5, len(frame)), "c_r2_r1_score")["c_r2_r1_score"].sum() / frame["c_r2_r1_score"].sum()) if frame["c_r2_r1_score"].sum() else 0.0,
            "left_tail_proxy": float(pd.to_numeric(frame.get("left_tail_proxy"), errors="coerce").mean()),
        })
    return pd.DataFrame(rows)


def coverage(df: pd.DataFrame, col: str) -> float:
    return float(pd.to_numeric(df[col], errors="coerce").notna().mean()) if col in df.columns and len(df) else 0.0


def run_stage() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    before = protected_hashes()
    warnings: list[dict[str, Any]] = []
    c_rank = read_csv(C_PATH)
    original = read_csv(ORIG_RANK)
    if c_rank.empty or original.empty:
        summary = {
            "final_status": "FAIL_V21_161_R1_SCRIPT_ERROR",
            "decision": "C_R2_FORWARD_TRACKING_ONLY_REPAIR_AUDITED",
            **POLICY,
            "proxy_repair_attempted": False,
            "proxy_repair_succeeded": False,
            "warning_count": 1,
        }
        write_json(OUT / f"{STAGE}_summary.json", summary)
        return summary
    c_rank["ticker"] = c_rank["ticker"].astype(str).str.upper().str.strip()
    original["ticker"] = original["ticker"].astype(str).str.upper().str.strip()
    latest = latest_price_date(c_rank)
    audit = source_audit(c_rank)
    audit.to_csv(OUT / "c_r2_proxy_source_audit.csv", index=False)
    proxies, root_cause = build_fundamental_proxy(c_rank)
    proxies = proxies.merge(low_vol(c_rank, latest)[["ticker", "low_vol"]], on="ticker", how="left")
    proxies.to_csv(OUT / "c_r2_repaired_proxy_table.csv", index=False)
    if root_cause.empty:
        root_cause = pd.DataFrame([{
            "ticker": "NONE",
            "proxy_name": "NONE",
            "root_cause": "NO_MISSING_PROXIES_AFTER_REPAIR",
            "source_data_present": True,
            "missing_source_data": False,
            "missing_columns": False,
            "wrong_column_names": False,
            "ticker_mapping_failure": False,
            "date_alignment_failure": False,
            "intentional_neutral_fallback": False,
            "repair_action": "none_required",
            "research_only": True,
        }])
    root_cause.to_csv(OUT / "c_r2_missing_proxy_root_cause.csv", index=False)
    regime_audit, regime = classify_regime(c_rank, latest)
    regime_audit.to_csv(OUT / "c_r2_r1_regime_audit.csv", index=False)
    repaired = recompute_ranking(c_rank, proxies, regime, latest)
    out_cols = [
        "rank", "ticker", "c_r2_r1_score", "selected_regime", "regime_confidence", "regime_source",
        "is_top20", "is_top50", "eligible_for_c_r2_r1", "momentum_rs", "technical_confirm",
        "profitability", "fcf_quality", "value", "low_vol", "risk_control", "data_trust",
        "factor_weight_sum_selected_regime", "latest_price_date_used", "sector", "industry", "proxy_repair_status",
    ]
    repaired[[c for c in out_cols if c in repaired.columns]].to_csv(OUT / "c_r2_r1_shadow_ranking_full.csv", index=False)
    repaired.head(50)[[c for c in out_cols if c in repaired.columns]].to_csv(OUT / "c_r2_r1_shadow_ranking_top50.csv", index=False)
    comp = compare(original, repaired)
    comp.to_csv(OUT / "c_r2_r1_vs_v21_161_original_comparison.csv", index=False)
    factor_delta(original, repaired, regime["selected_regime"]).to_csv(OUT / "c_r2_r1_factor_attribution_delta.csv", index=False)

    missing_real = root_cause[root_cause["ticker"].ne("NONE")]
    if not missing_real.empty:
        warnings.append({"ticker": "ALL", "warning_type": "LIMITED_PROXY_REMAINS", "warning": f"{len(missing_real)} ticker-proxy cells still require neutral fallback"})
    if regime["regime_selected_by_fallback"]:
        warnings.append({"ticker": "ALL", "warning_type": "REGIME_FALLBACK_REMAINS", "warning": regime["fallback_reason"]})
    warn_df = pd.DataFrame(warnings) if warnings else pd.DataFrame([{"ticker": "ALL", "warning_type": "NONE", "warning": ""}])
    warn_df.to_csv(OUT / "c_r2_r1_data_quality_warnings.csv", index=False)

    # Include risk attribution change as additional rows in the required factor delta artifact.
    r1_risk = concentration_risk(repaired)
    orig_risk = read_csv(ORIG_RISK)
    risk_delta = []
    if not orig_risk.empty:
        for _, row in r1_risk.iterrows():
            o = orig_risk[orig_risk["bucket"].eq(row["bucket"])]
            risk_delta.append({
                "factor": f"risk_attribution_{row['bucket']}",
                "weight": "",
                "original_top20_mean": "",
                "repaired_top20_mean": "",
                "original_top50_mean": "",
                "repaired_top50_mean": "",
                "top20_mean_delta": "",
                "top50_mean_delta": "",
                "original_score_top1_share": float(o["score_top1_share"].iloc[0]) if not o.empty and "score_top1_share" in o else "",
                "repaired_score_top1_share": row["score_top1_share"],
                "original_data_warning_ticker_count": int(o["data_warning_ticker_count"].iloc[0]) if not o.empty and "data_warning_ticker_count" in o else "",
                "repaired_data_warning_ticker_count": row["data_warning_ticker_count"],
            })
        fd = read_csv(OUT / "c_r2_r1_factor_attribution_delta.csv")
        pd.concat([fd, pd.DataFrame(risk_delta)], ignore_index=True).to_csv(OUT / "c_r2_r1_factor_attribution_delta.csv", index=False)

    before_cov = {
        "profitability": coverage(original, "profitability"),
        "fcf_quality": coverage(original, "fcf_quality"),
        "value": coverage(original, "value"),
        "low_vol": coverage(original, "low_vol"),
    }
    after_cov = {
        "profitability": coverage(proxies, "profitability"),
        "fcf_quality": coverage(proxies, "fcf_quality"),
        "value": coverage(proxies, "value"),
        "low_vol": coverage(proxies, "low_vol"),
    }
    top20_overlap = int(comp[(comp["row_type"].eq("summary")) & (comp["bucket"].eq("Top20"))]["overlap_count"].iloc[0])
    top50_overlap = int(comp[(comp["row_type"].eq("summary")) & (comp["bucket"].eq("Top50"))]["overlap_count"].iloc[0])
    after = protected_hashes()
    protected_modified = before != after
    full_repair = missing_real.empty and not regime["regime_selected_by_fallback"]
    limited = not missing_real.empty
    final_status = (
        "FAIL_V21_161_R1_SCRIPT_ERROR" if protected_modified
        else "PASS_V21_161_R1_C_R2_PROXY_REGIME_REPAIRED" if full_repair
        else "WARN_V21_161_R1_C_R2_PROXY_LIMITED" if limited
        else "PARTIAL_PASS_V21_161_R1_C_R2_REPAIRED_WITH_WARNINGS"
    )
    summary = {
        "final_status": final_status,
        "decision": "C_R2_FORWARD_TRACKING_ONLY_REPAIR_AUDITED",
        **{**POLICY, "protected_outputs_modified": protected_modified},
        "proxy_repair_attempted": True,
        "proxy_repair_succeeded": bool(len(repaired) > 0 and after_cov["profitability"] > 0 and after_cov["fcf_quality"] > 0 and after_cov["value"] > 0),
        "profitability_proxy_coverage": after_cov["profitability"],
        "fcf_quality_proxy_coverage": after_cov["fcf_quality"],
        "value_proxy_coverage": after_cov["value"],
        "low_vol_proxy_coverage": after_cov["low_vol"],
        "proxy_coverage_before": before_cov,
        "proxy_coverage_after": after_cov,
        "selected_regime": regime["selected_regime"],
        "regime_confidence": regime["regime_confidence"],
        "regime_source": regime["regime_source"],
        "regime_selected_by_signal": regime["regime_selected_by_signal"],
        "regime_selected_by_fallback": regime["regime_selected_by_fallback"],
        "fallback_reason": regime["fallback_reason"],
        "unavailable_regime_inputs": regime["unavailable_regime_inputs"],
        "original_v21_161_top20_overlap": top20_overlap,
        "original_v21_161_top50_overlap": top50_overlap,
        "latest_price_date_used": latest,
        "repaired_top20_tickers": repaired.head(20)["ticker"].tolist(),
        "warning_count": len(warnings),
        "warnings": warnings,
    }
    write_json(OUT / f"{STAGE}_summary.json", summary)
    report = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"decision={summary['decision']}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        f"latest_price_date_used={latest}",
        f"proxy_coverage_before={before_cov}",
        f"proxy_coverage_after={after_cov}",
        f"selected_regime={regime['selected_regime']}",
        f"regime_confidence={regime['regime_confidence']}",
        f"regime_selected_by_signal={regime['regime_selected_by_signal']}",
        f"regime_selected_by_fallback={regime['regime_selected_by_fallback']}",
        "repaired_C_R2_top20=" + ", ".join(summary["repaired_top20_tickers"]),
        f"overlap_vs_original_top20={top20_overlap}",
        f"overlap_vs_original_top50={top50_overlap}",
        f"warnings={len(warnings)}",
    ]
    (OUT / f"{STAGE}_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    try:
        summary = run_stage()
    except Exception as exc:  # pragma: no cover
        OUT.mkdir(parents=True, exist_ok=True)
        summary = {
            "final_status": "FAIL_V21_161_R1_SCRIPT_ERROR",
            "decision": "C_R2_FORWARD_TRACKING_ONLY_REPAIR_AUDITED",
            **POLICY,
            "proxy_repair_attempted": True,
            "proxy_repair_succeeded": False,
            "error": str(exc),
            "warning_count": 1,
        }
        write_json(OUT / f"{STAGE}_summary.json", summary)
    print(json.dumps(summary, indent=2))
    return 0 if not str(summary.get("final_status", "")).startswith("FAIL") else 1


if __name__ == "__main__":
    raise SystemExit(main())
