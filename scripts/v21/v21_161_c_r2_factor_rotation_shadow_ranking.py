from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.161_C_R2_FACTOR_ROTATION_SHADOW_RANKING"
OUT = ROOT / "outputs" / "v21" / STAGE
ABCD = ROOT / "outputs" / "v21" / "V21.113_LATEST_DATA_ABCD_RERUN_20260625_PRICE_REFRESH"
A1_PATH = ABCD / "A1_BASELINE_CONTROL_latest_ranking.csv"
C_PATH = ABCD / "C_DYNAMIC_MOMENTUM_BLEND_latest_ranking.csv"
ABCD_SUMMARY = ABCD / "V21.113_latest_data_abcd_rerun_summary.json"
FUND_PATH = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R6B_FUNDAMENTAL_CANDIDATE_SCORE_SOURCE.csv"
PRICE_PATH = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
META_PATH = ROOT / "outputs" / "v21" / "V21.138_E_R1_METADATA_COVERAGE_REPAIR_AND_REAUDIT" / "consolidated_sector_industry_metadata_bridge.csv"

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

POLICY_FLAGS = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "role_review_required": False,
    "c_r2_adoption_blocked_by_default": True,
}


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


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
            is_protected = any(token in rel for token in ["broker", "real_book", "realbook"])
            is_protected = is_protected or ("official" in rel and any(k in rel for k in ["rank", "weight", "allocation", "recommend"]))
            if is_protected:
                hashes[path.relative_to(ROOT).as_posix()] = sha(path)
    return hashes


def pct_rank(s: pd.Series, higher_is_better: bool = True) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    if x.notna().sum() == 0:
        return pd.Series(np.nan, index=s.index)
    ranked = x.rank(pct=True, ascending=not higher_is_better)
    return (ranked * 100.0).clip(0, 100)


def to_score(s: pd.Series) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    if x.dropna().between(0, 1).all():
        x = x * 100.0
    return x.clip(0, 100)


def tf(v: Any) -> bool:
    return str(v).strip().lower() in {"true", "1", "yes", "y"}


def select_regime(c_rank: pd.DataFrame, warnings: list[dict[str, Any]]) -> tuple[str, float, str]:
    raw = ""
    if "market_regime" in c_rank.columns:
        vals = c_rank["market_regime"].dropna().astype(str).str.strip()
        raw = vals[vals.ne("")].mode().iloc[0] if not vals[vals.ne("")].empty else ""
    mapping = {
        "RISK_ON": "risk_on",
        "STRONG_RISK_ON": "risk_on",
        "NEUTRAL": "neutral",
        "RISK_OFF": "risk_off",
        "DEFENSIVE": "risk_off",
    }
    selected = mapping.get(raw.upper(), "neutral")
    confidence = 0.75 if raw.upper() in mapping else 0.35
    if raw.upper() not in mapping:
        warnings.append({
            "ticker": "ALL",
            "warning_type": "REGIME_FALLBACK",
            "warning": "market_regime unavailable or unmapped; selected neutral with reduced confidence",
        })
    return selected, confidence, raw or "UNKNOWN"


def low_vol_scores(tickers: set[str], latest_price_date: str, warnings: list[dict[str, Any]]) -> pd.DataFrame:
    prices = read_csv(PRICE_PATH)
    if prices.empty or not {"symbol", "date", "adjusted_close"}.issubset(prices.columns):
        warnings.append({"ticker": "ALL", "warning_type": "LOW_VOL_UNAVAILABLE", "warning": "canonical OHLCV panel missing required fields"})
        return pd.DataFrame({"ticker": list(tickers), "low_vol": np.nan, "left_tail_proxy": np.nan})
    p = prices[prices["symbol"].astype(str).str.upper().isin(tickers)].copy()
    p["date"] = pd.to_datetime(p["date"], errors="coerce")
    p["adjusted_close"] = pd.to_numeric(p["adjusted_close"], errors="coerce")
    if latest_price_date:
        p = p[p["date"] <= pd.to_datetime(latest_price_date)]
    p = p.sort_values(["symbol", "date"])
    p["ret"] = p.groupby("symbol")["adjusted_close"].pct_change()
    stats = p.groupby("symbol")["ret"].agg(vol_60=lambda x: x.tail(60).std(), left_tail_proxy=lambda x: x.tail(60).quantile(0.05)).reset_index()
    stats["ticker"] = stats["symbol"].astype(str).str.upper()
    stats["low_vol"] = pct_rank(stats["vol_60"], higher_is_better=False)
    return stats[["ticker", "low_vol", "left_tail_proxy"]]


def normalize_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[dict[str, Any]], str]:
    warnings: list[dict[str, Any]] = []
    a1 = read_csv(A1_PATH)
    c = read_csv(C_PATH)
    fund = read_csv(FUND_PATH)
    if a1.empty:
        warnings.append({"ticker": "ALL", "warning_type": "INPUT_MISSING", "warning": f"missing A1 source: {A1_PATH}"})
    if c.empty:
        warnings.append({"ticker": "ALL", "warning_type": "INPUT_MISSING", "warning": f"missing C source: {C_PATH}"})
    if fund.empty:
        warnings.append({"ticker": "ALL", "warning_type": "FUNDAMENTAL_INPUT_MISSING", "warning": f"missing fundamental source: {FUND_PATH}"})
    for df in [a1, c, fund]:
        if not df.empty and "ticker" in df.columns:
            df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    latest = ""
    summary = read_json(ABCD_SUMMARY)
    latest = str(summary.get("latest_price_date", ""))
    if not latest and not c.empty and "latest_price_date" in c.columns:
        dates = pd.to_datetime(c["latest_price_date"], errors="coerce").dropna()
        latest = str(dates.max().date()) if not dates.empty else ""
    return a1, c, fund, warnings, latest


def build_ranking() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    before = protected_hashes()
    a1, c, fund, warnings, latest_price_date = normalize_inputs()
    if c.empty:
        summary = {
            "FINAL_STATUS": "FAIL_V21_161_C_R2_SCRIPT_ERROR",
            "DECISION": "C_R2_FORWARD_TRACKING_ONLY",
            **POLICY_FLAGS,
            "error": "C source ranking is missing or empty",
        }
        (OUT / f"{STAGE}_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        return summary

    selected_regime, regime_confidence, source_regime = select_regime(c, warnings)
    weights = WEIGHTS[selected_regime]
    c = c.copy()
    c["ticker"] = c["ticker"].astype(str).str.upper().str.strip()
    c = c[c["ticker"].ne("")].drop_duplicates("ticker").reset_index(drop=True)
    c["rank"] = pd.to_numeric(c.get("rank"), errors="coerce")
    c["final_score"] = pd.to_numeric(c.get("final_score"), errors="coerce")
    c["momentum_rs"] = to_score(c.get("relative_momentum_score", c.get("momentum_score")))
    if c["momentum_rs"].isna().all():
        c["momentum_rs"] = pct_rank(c["rank"], higher_is_better=False)
        warnings.append({"ticker": "ALL", "warning_type": "MOMENTUM_PROXY", "warning": "relative momentum unavailable; used C rank percentile proxy"})
    tech_cols = [col for col in ["absolute_momentum_score", "momentum_acceleration_score", "trend_persistence_score"] if col in c.columns]
    c["technical_confirm"] = pd.concat([to_score(c[col]) for col in tech_cols], axis=1).mean(axis=1) if tech_cols else pct_rank(c["rank"], higher_is_better=False)
    c["risk_control"] = 100.0 - to_score(c.get("exhaustion_risk_score", pd.Series(np.nan, index=c.index))).fillna(50.0)

    f = fund.copy()
    if not f.empty:
        f["ticker"] = f["ticker"].astype(str).str.upper().str.strip()
        f["profitability"] = pd.concat([
            to_score(f.get("profitability_component_score", pd.Series(np.nan, index=f.index))),
            to_score(f.get("margin_component_score", pd.Series(np.nan, index=f.index))),
        ], axis=1).mean(axis=1)
        f["fcf_quality"] = pd.concat([
            to_score(f.get("cash_flow_component_score", pd.Series(np.nan, index=f.index))),
            to_score(f.get("quality_component_score", pd.Series(np.nan, index=f.index))),
            to_score(f.get("balance_sheet_component_score", pd.Series(np.nan, index=f.index))),
        ], axis=1).mean(axis=1)
        f["value"] = to_score(f.get("valuation_component_score", pd.Series(np.nan, index=f.index)))
        missing = pd.to_numeric(f.get("missing_metric_count"), errors="coerce").fillna(99)
        present = pd.to_numeric(f.get("present_numeric_metric_count"), errors="coerce").fillna(0)
        certified = f.get("fundamental_metric_certification_status", "").astype(str).str.contains("CERTIFIED", case=False, na=False)
        f["fundamental_trust"] = np.where(certified, 75, 45) + np.minimum(present, 25) - np.minimum(missing * 2, 35)
        f = f[["ticker", "profitability", "fcf_quality", "value", "fundamental_trust", "missing_metric_count", "fundamental_metric_certification_status"]].drop_duplicates("ticker")
    else:
        f = pd.DataFrame(columns=["ticker", "profitability", "fcf_quality", "value", "fundamental_trust", "missing_metric_count", "fundamental_metric_certification_status"])

    rank = c.merge(f, on="ticker", how="left")
    for col in ["profitability", "fcf_quality", "value"]:
        missing_count = int(rank[col].isna().sum())
        if missing_count:
            warnings.append({"ticker": "ALL", "warning_type": f"{col.upper()}_PARTIAL_COVERAGE", "warning": f"{missing_count} tickers missing {col}; filled with neutral 50 proxy"})
        rank[col] = rank[col].fillna(50.0)
    rank["data_trust"] = rank["fundamental_trust"].fillna(50.0)
    rank.loc[rank.get("warning_flags", "").astype(str).str.len() > 0, "data_trust"] = rank["data_trust"] - 10
    if selected_regime == "risk_off":
        lv = low_vol_scores(set(rank["ticker"]), latest_price_date, warnings)
        rank = rank.merge(lv, on="ticker", how="left")
        missing_lv = int(rank["low_vol"].isna().sum())
        if missing_lv:
            warnings.append({"ticker": "ALL", "warning_type": "LOW_VOL_PARTIAL_COVERAGE", "warning": f"{missing_lv} tickers missing low-vol proxy; filled with neutral 50"})
        rank["low_vol"] = rank["low_vol"].fillna(50.0)
    else:
        rank["low_vol"] = np.nan
        rank["left_tail_proxy"] = np.nan

    factor_cols = list(weights)
    rank["c_r2_score"] = 0.0
    for factor, weight in weights.items():
        rank["c_r2_score"] += pd.to_numeric(rank[factor], errors="coerce").fillna(50.0) * weight
    eligible = rank.get("eligible_flag", True)
    if not isinstance(eligible, pd.Series):
        eligible = pd.Series(True, index=rank.index)
    eligible = eligible.astype(str).str.lower().isin(["true", "1", "yes"]) | eligible.eq(True)
    rank["eligible_for_c_r2"] = eligible
    rank["eligibility_flags"] = np.where(eligible, "ELIGIBLE", "SOURCE_C_INELIGIBLE")
    rank["selected_regime"] = selected_regime
    rank["source_regime"] = source_regime
    rank["regime_confidence"] = regime_confidence
    rank["factor_weight_sum_selected_regime"] = round(sum(weights.values()), 10)
    rank["data_quality_warnings"] = rank.get("warning_flags", "").fillna("").astype(str)
    rank.loc[rank["missing_metric_count"].fillna("").astype(str).ne(""), "data_quality_warnings"] = (
        rank["data_quality_warnings"].astype(str).str.strip(";") + ";FUNDAMENTAL_PIT_LITE_PROXY"
    ).str.strip(";")
    rank = rank.sort_values(["eligible_for_c_r2", "c_r2_score", "ticker"], ascending=[False, False, True]).reset_index(drop=True)
    rank["rank"] = np.arange(1, len(rank) + 1)
    rank["is_top20"] = rank["rank"].le(20)
    rank["is_top50"] = rank["rank"].le(50)

    meta = read_csv(META_PATH)
    if not meta.empty:
        meta["ticker"] = meta["ticker_norm"].astype(str).str.upper().str.strip()
        rank = rank.merge(meta[["ticker", "sector", "industry"]].drop_duplicates("ticker"), on="ticker", how="left")
    rank["sector"] = rank.get("sector", "UNKNOWN").fillna("UNKNOWN")
    rank["industry"] = rank.get("industry", "UNKNOWN").fillna("UNKNOWN")

    output_cols = [
        "rank", "ticker", "c_r2_score", "selected_regime", "source_regime", "regime_confidence",
        "is_top20", "is_top50", "eligible_for_c_r2", "eligibility_flags", *factor_cols,
        "low_vol", "final_score", "momentum_score", "latest_price_date", "sector", "industry",
        "factor_weight_sum_selected_regime", "data_quality_warnings",
    ]
    output_cols = list(dict.fromkeys([c for c in output_cols if c in rank.columns]))
    rank[output_cols].to_csv(OUT / "c_r2_shadow_ranking_full.csv", index=False)
    rank.head(50)[output_cols].to_csv(OUT / "c_r2_shadow_ranking_top50.csv", index=False)

    factor_attr = pd.DataFrame([
        {
            "selected_regime": selected_regime,
            "factor": factor,
            "weight": weight,
            "mean_score_top20": rank.head(20)[factor].mean(),
            "mean_score_top50": rank.head(50)[factor].mean(),
            "mean_score_full": rank[factor].mean(),
            "pit_lite_proxy_note": "PIT-lite local proxy; not a full PIT claim",
        }
        for factor, weight in weights.items()
    ])
    factor_attr.to_csv(OUT / "c_r2_factor_attribution.csv", index=False)

    risk_rows = []
    for label, frame in [("Top20", rank.head(20)), ("Top50", rank.head(50)), ("Full", rank)]:
        risk_rows.append({
            "bucket": label,
            "valid_holdings_count": int(len(frame)),
            "repeated_loser_count": int(((pd.to_numeric(frame.get("momentum_acceleration_score"), errors="coerce") < 45) | (pd.to_numeric(frame.get("relative_momentum_score"), errors="coerce") < 45)).sum()) if "momentum_acceleration_score" in frame else "",
            "left_tail_proxy": float(pd.to_numeric(frame.get("left_tail_proxy"), errors="coerce").mean()) if "left_tail_proxy" in frame else np.nan,
            "data_warning_ticker_count": int(frame["data_quality_warnings"].fillna("").astype(str).str.len().gt(0).sum()),
            "score_top1_share": float(frame["c_r2_score"].max() / frame["c_r2_score"].sum()) if frame["c_r2_score"].sum() else 0.0,
            "score_top5_share": float(frame.nlargest(min(5, len(frame)), "c_r2_score")["c_r2_score"].sum() / frame["c_r2_score"].sum()) if frame["c_r2_score"].sum() else 0.0,
            "score_std": float(frame["c_r2_score"].std(ddof=0)) if len(frame) else 0.0,
        })
    pd.DataFrame(risk_rows).to_csv(OUT / "c_r2_risk_attribution.csv", index=False)

    conc_rows = []
    for bucket, frame in [("Top20", rank.head(20)), ("Top50", rank.head(50))]:
        for group_col in ["sector", "industry"]:
            counts = frame[group_col].fillna("UNKNOWN").value_counts()
            for name, count in counts.items():
                conc_rows.append({"bucket": bucket, "dimension": group_col, "name": name, "count": int(count), "weight": float(count / len(frame))})
    pd.DataFrame(conc_rows).to_csv(OUT / "c_r2_sector_industry_concentration.csv", index=False)

    warn_df = pd.DataFrame(warnings)
    if warn_df.empty:
        warn_df = pd.DataFrame([{"ticker": "ALL", "warning_type": "NONE", "warning": ""}])
    warn_df.to_csv(OUT / "c_r2_data_quality_warnings.csv", index=False)

    overlap = build_overlap(rank, a1, c)
    overlap.to_csv(OUT / "c_r2_top20_vs_a1_c_overlap.csv", index=False)

    status = "PASS_V21_161_C_R2_SHADOW_RANKING_READY" if len(warnings) == 0 else "PARTIAL_PASS_V21_161_C_R2_READY_WITH_WARNINGS"
    if len(rank) == 0:
        status = "WARN_V21_161_C_R2_INSUFFICIENT_DATA"
    after = protected_hashes()
    protected_modified = before != after
    summary = {
        "stage": STAGE,
        "FINAL_STATUS": status,
        "DECISION": "C_R2_FORWARD_TRACKING_ONLY",
        **{**POLICY_FLAGS, "protected_outputs_modified": protected_modified},
        "latest_price_date_used": latest_price_date,
        "selected_regime": selected_regime,
        "source_regime": source_regime,
        "regime_confidence": regime_confidence,
        "selected_regime_weights": weights,
        "selected_regime_weight_sum": round(sum(weights.values()), 10),
        "ranking_row_count": int(len(rank)),
        "top50_row_count": int(min(50, len(rank))),
        "top20_tickers": rank.head(20)["ticker"].tolist(),
        "top20_overlap_c_r2_vs_a1": int(len(set(rank.head(20)["ticker"]) & top_set(a1, 20))),
        "top50_overlap_c_r2_vs_a1": int(len(set(rank.head(50)["ticker"]) & top_set(a1, 50))),
        "top20_overlap_c_r2_vs_c_original": int(len(set(rank.head(20)["ticker"]) & top_set(c, 20))),
        "top50_overlap_c_r2_vs_c_original": int(len(set(rank.head(50)["ticker"]) & top_set(c, 50))),
        "warning_count": int(len(warnings)),
        "warnings": warnings,
    }
    if protected_modified:
        summary["FINAL_STATUS"] = "FAIL_V21_161_C_R2_SCRIPT_ERROR"
    (OUT / f"{STAGE}_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    report = [
        STAGE,
        f"FINAL_STATUS={summary['FINAL_STATUS']}",
        f"DECISION={summary['DECISION']}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        f"latest_price_date_used={latest_price_date}",
        f"selected_regime={selected_regime}",
        f"regime_confidence={regime_confidence}",
        "C_R2_TOP20=" + ", ".join(summary["top20_tickers"]),
        f"Top20 overlap vs A1={summary['top20_overlap_c_r2_vs_a1']}",
        f"Top50 overlap vs A1={summary['top50_overlap_c_r2_vs_a1']}",
        f"Top20 overlap vs C original={summary['top20_overlap_c_r2_vs_c_original']}",
        f"Top50 overlap vs C original={summary['top50_overlap_c_r2_vs_c_original']}",
        f"warnings={summary['warning_count']}",
    ]
    (OUT / f"{STAGE}_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


def top_set(df: pd.DataFrame, n: int) -> set[str]:
    if df.empty or "ticker" not in df.columns:
        return set()
    tmp = df.copy()
    tmp["ticker"] = tmp["ticker"].astype(str).str.upper().str.strip()
    if "rank" in tmp.columns:
        tmp["rank"] = pd.to_numeric(tmp["rank"], errors="coerce")
        tmp = tmp.sort_values(["rank", "ticker"])
    return set(tmp.head(n)["ticker"])


def rank_map(df: pd.DataFrame) -> dict[str, int]:
    if df.empty or "ticker" not in df.columns:
        return {}
    tmp = df.copy()
    tmp["ticker"] = tmp["ticker"].astype(str).str.upper().str.strip()
    tmp["rank"] = pd.to_numeric(tmp.get("rank"), errors="coerce")
    return {r["ticker"]: int(r["rank"]) for _, r in tmp.dropna(subset=["rank"]).iterrows()}


def build_overlap(c_r2: pd.DataFrame, a1: pd.DataFrame, c: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    c20, c50 = set(c_r2.head(20)["ticker"]), set(c_r2.head(50)["ticker"])
    a1_20, a1_50 = top_set(a1, 20), top_set(a1, 50)
    c_20, c_50 = top_set(c, 20), top_set(c, 50)
    rows.extend([
        {"row_type": "summary", "comparison": "C_R2_vs_A1", "bucket": "Top20", "overlap_count": len(c20 & a1_20), "entrants": ",".join(sorted(c20 - a1_20)), "exits": ",".join(sorted(a1_20 - c20))},
        {"row_type": "summary", "comparison": "C_R2_vs_A1", "bucket": "Top50", "overlap_count": len(c50 & a1_50), "entrants": ",".join(sorted(c50 - a1_50)), "exits": ",".join(sorted(a1_50 - c50))},
        {"row_type": "summary", "comparison": "C_R2_vs_C_ORIGINAL", "bucket": "Top20", "overlap_count": len(c20 & c_20), "entrants": ",".join(sorted(c20 - c_20)), "exits": ",".join(sorted(c_20 - c20))},
        {"row_type": "summary", "comparison": "C_R2_vs_C_ORIGINAL", "bucket": "Top50", "overlap_count": len(c50 & c_50), "entrants": ",".join(sorted(c50 - c_50)), "exits": ",".join(sorted(c_50 - c50))},
    ])
    r2_map = {r["ticker"]: int(r["rank"]) for _, r in c_r2.iterrows()}
    maps = {"A1": rank_map(a1), "C_ORIGINAL": rank_map(c)}
    for label, other in maps.items():
        for ticker in sorted(set(r2_map) | set(other)):
            rows.append({
                "row_type": "rank_diff",
                "comparison": f"C_R2_vs_{label}",
                "bucket": "Full",
                "ticker": ticker,
                "c_r2_rank": r2_map.get(ticker, ""),
                f"{label.lower()}_rank": other.get(ticker, ""),
                "rank_diff_c_r2_minus_other": (r2_map.get(ticker, np.nan) - other.get(ticker, np.nan)) if ticker in r2_map and ticker in other else "",
                "in_c_r2_top20": ticker in c20,
                "in_c_r2_top50": ticker in c50,
            })
    return pd.DataFrame(rows)


def main() -> int:
    summary = build_ranking()
    print(json.dumps(summary, indent=2))
    return 0 if not str(summary.get("FINAL_STATUS", "")).startswith("FAIL") else 1


if __name__ == "__main__":
    raise SystemExit(main())
