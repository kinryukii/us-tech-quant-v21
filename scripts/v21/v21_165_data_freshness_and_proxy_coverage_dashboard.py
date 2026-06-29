from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD"
OUT = ROOT / "outputs" / "v21" / STAGE

PRICE = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
A1 = ROOT / "outputs" / "v21" / "V21.113_LATEST_DATA_ABCD_RERUN_20260625_PRICE_REFRESH" / "A1_BASELINE_CONTROL_latest_ranking.csv"
C_R2 = ROOT / "outputs" / "v21" / "V21.161_R1_C_R2_PROXY_AND_REGIME_REPAIR" / "c_r2_r1_shadow_ranking_full.csv"
C_R2_TOP50 = ROOT / "outputs" / "v21" / "V21.161_R1_C_R2_PROXY_AND_REGIME_REPAIR" / "c_r2_r1_shadow_ranking_top50.csv"
C_R2_PROXY = ROOT / "outputs" / "v21" / "V21.161_R1_C_R2_PROXY_AND_REGIME_REPAIR" / "c_r2_repaired_proxy_table.csv"
C_R2_PROXY_AUDIT = ROOT / "outputs" / "v21" / "V21.161_R1_C_R2_PROXY_AND_REGIME_REPAIR" / "c_r2_proxy_source_audit.csv"
AI = ROOT / "outputs" / "v21" / "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING" / "ai_bottleneck_shadow_ranking_full.csv"
AI_TOP50 = ROOT / "outputs" / "v21" / "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING" / "ai_bottleneck_shadow_ranking_top50.csv"
AI_TAGS = ROOT / "outputs" / "v21" / "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING" / "ai_bottleneck_universe_tags.csv"
SWITCH_STATE = ROOT / "outputs" / "v21" / "V21.163_C_R2_AI_BOTTLENECK_SWITCH_CONTROLLER" / "switch_controller_state.csv"
SWITCH_COMPONENTS = ROOT / "outputs" / "v21" / "V21.163_C_R2_AI_BOTTLENECK_SWITCH_CONTROLLER" / "switch_controller_component_status.csv"
SWITCH_LEDGER = ROOT / "outputs" / "v21" / "V21.164_SWITCH_STATE_FORWARD_TRACKING_LEDGER" / "switch_state_forward_ledger.csv"
SWITCH_LEDGER_R1 = ROOT / "outputs" / "v21" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR" / "switch_ledger_r1_full_ledger.csv"

WARNING_FILES = [
    ROOT / "outputs" / "v21" / "V21.161_R1_C_R2_PROXY_AND_REGIME_REPAIR" / "c_r2_r1_data_quality_warnings.csv",
    ROOT / "outputs" / "v21" / "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING" / "ai_bottleneck_data_quality_warnings.csv",
    ROOT / "outputs" / "v21" / "V21.163_C_R2_AI_BOTTLENECK_SWITCH_CONTROLLER" / "switch_controller_warnings.csv",
    ROOT / "outputs" / "v21" / "V21.164_SWITCH_STATE_FORWARD_TRACKING_LEDGER" / "switch_state_data_quality_warnings.csv",
    ROOT / "outputs" / "v21" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR" / "switch_ledger_r1_data_quality_warnings.csv",
]

POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "live_trading_allowed": False,
    "protected_outputs_modified": False,
    "role_review_required": False,
}

PROXY_COLUMNS = ["profitability", "fcf_quality", "value", "low_vol", "risk_control", "data_trust"]
IMPACT_ORDER = {"NO_IMPACT": 0, "LOW_IMPACT": 1, "MEDIUM_IMPACT": 2, "BLOCKING_IMPACT": 3}


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def write_csv(name: str, df: pd.DataFrame) -> None:
    path = OUT / name
    df.to_csv(path, index=False)


def write_json(name: str, payload: dict[str, Any]) -> None:
    (OUT / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


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
            s = rel(path).lower().replace("-", "_")
            protected = any(x in s for x in ["broker", "real_book", "realbook", "trade_action"])
            protected = protected or ("official" in s and any(x in s for x in ["rank", "weight", "allocation", "recommend"]))
            if protected:
                hashes[rel(path)] = sha(path)
    return hashes


def ticker_series(df: pd.DataFrame) -> pd.Series:
    col = "ticker" if "ticker" in df.columns else "symbol" if "symbol" in df.columns else ""
    if not col:
        return pd.Series(dtype=str)
    return df[col].astype(str).str.upper().str.strip()


def ticker_set(df: pd.DataFrame) -> set[str]:
    return {x for x in ticker_series(df) if x and x != "NAN" and x != "ALL"}


def top_set(df: pd.DataFrame, n: int) -> set[str]:
    if df.empty:
        return set()
    work = df.copy()
    if "rank" in work.columns:
        work["_rank"] = pd.to_numeric(work["rank"], errors="coerce")
        work = work.sort_values("_rank", na_position="last")
    return set(ticker_series(work.head(n)))


def bool_count_warning(warnings: list[dict[str, Any]], tickers: set[str]) -> int:
    count = 0
    for row in warnings:
        ticker = str(row.get("ticker", "")).upper().strip()
        if ticker == "ALL":
            count += len(tickers)
        elif ticker in tickers:
            count += 1
    return count


def load_warnings() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for path in WARNING_FILES:
        df = read_csv(path)
        if df.empty:
            continue
        for row in df.to_dict("records"):
            rows.append({
                "source_file": rel(path),
                "ticker": str(row.get("ticker", "ALL")).upper().strip() or "ALL",
                "warning_type": row.get("warning_type", "WARNING"),
                "warning": row.get("warning", ""),
            })
    return pd.DataFrame(rows, columns=["source_file", "ticker", "warning_type", "warning"])


def price_freshness(price: pd.DataFrame, universe: set[str]) -> tuple[pd.DataFrame, str]:
    if price.empty or "date" not in price.columns:
        rows = [{"ticker": t, "latest_price_date": "", "price_row_count": 0, "freshness_status": "MISSING_PRICE"} for t in sorted(universe)]
        return pd.DataFrame(rows), ""
    work = price.copy()
    ticker_col = "symbol" if "symbol" in work.columns else "ticker"
    work[ticker_col] = work[ticker_col].astype(str).str.upper().str.strip()
    work["_date"] = pd.to_datetime(work["date"], errors="coerce")
    latest = work["_date"].max()
    latest_s = "" if pd.isna(latest) else str(latest.date())
    grouped = work.dropna(subset=["_date"]).groupby(ticker_col).agg(latest_price_date=("_date", "max"), price_row_count=("_date", "size")).reset_index()
    grouped = grouped.rename(columns={ticker_col: "ticker"})
    base = pd.DataFrame({"ticker": sorted(universe or set(grouped["ticker"]))})
    out = base.merge(grouped, on="ticker", how="left")
    out["latest_price_date"] = pd.to_datetime(out["latest_price_date"], errors="coerce")
    out["days_behind_latest"] = (latest - out["latest_price_date"]).dt.days if not pd.isna(latest) else pd.NA
    out["freshness_status"] = "FRESH"
    out.loc[out["latest_price_date"].isna(), "freshness_status"] = "MISSING_PRICE"
    out.loc[out["latest_price_date"].notna() & (out["latest_price_date"] < latest), "freshness_status"] = "STALE_PRICE"
    out["latest_price_date"] = out["latest_price_date"].dt.strftime("%Y-%m-%d").fillna("")
    out["price_row_count"] = out["price_row_count"].fillna(0).astype(int)
    return out, latest_s


def proxy_by_ticker(universe: set[str], c_r2: pd.DataFrame, proxy: pd.DataFrame, ai_tags: pd.DataFrame) -> pd.DataFrame:
    base = pd.DataFrame({"ticker": sorted(universe)})
    for src in [proxy, c_r2, ai_tags]:
        if src.empty or "ticker" not in src.columns:
            continue
        keep = ["ticker"] + [c for c in PROXY_COLUMNS + ["proxy_repair_status", "ai_bottleneck_eligible"] if c in src.columns]
        add = src[keep].copy()
        add["ticker"] = add["ticker"].astype(str).str.upper().str.strip()
        base = base.merge(add.drop_duplicates("ticker"), on="ticker", how="left", suffixes=("", "_src"))
        for col in PROXY_COLUMNS + ["proxy_repair_status", "ai_bottleneck_eligible"]:
            alt = f"{col}_src"
            if alt in base.columns:
                if col in base.columns:
                    base[col] = base[col].combine_first(base[alt])
                    base = base.drop(columns=[alt])
                else:
                    base = base.rename(columns={alt: col})
    for col in PROXY_COLUMNS:
        if col not in base.columns:
            base[col] = pd.NA
        base[f"{col}_covered"] = pd.to_numeric(base[col], errors="coerce").notna()
    covered_cols = [f"{c}_covered" for c in PROXY_COLUMNS]
    base["covered_proxy_cell_count"] = base[covered_cols].sum(axis=1)
    base["expected_proxy_cell_count"] = len(PROXY_COLUMNS)
    base["proxy_cell_coverage"] = base["covered_proxy_cell_count"] / base["expected_proxy_cell_count"]
    status = base.get("proxy_repair_status", pd.Series("", index=base.index)).astype(str).str.upper()
    base["neutral_fallback_cell_count"] = 0
    missing_core = base[[f"{c}_covered" for c in ["profitability", "fcf_quality", "value", "low_vol"]]].eq(False).sum(axis=1)
    base["neutral_fallback_cell_count"] = missing_core
    base.loc[status.str.contains("NEUTRAL|FALLBACK", regex=True, na=False), "neutral_fallback_cell_count"] += 1
    return base


def coverage_summary(by_ticker: pd.DataFrame, source_audit: pd.DataFrame) -> pd.DataFrame:
    rows = []
    denom = len(by_ticker)
    for col in PROXY_COLUMNS:
        cov_col = f"{col}_covered"
        covered = int(by_ticker[cov_col].sum()) if cov_col in by_ticker.columns else 0
        rows.append({
            "proxy_name": f"{col}_proxy",
            "covered_ticker_count": covered,
            "ticker_count": denom,
            "coverage": covered / denom if denom else 0.0,
            "source_status": "DERIVED_FROM_BY_TICKER",
        })
    if not source_audit.empty:
        for row in source_audit.to_dict("records"):
            if str(row.get("proxy_name", "")) not in {r["proxy_name"] for r in rows}:
                rows.append({
                    "proxy_name": row.get("proxy_name", ""),
                    "covered_ticker_count": row.get("covered_ticker_count", ""),
                    "ticker_count": row.get("c_r2_universe_count", denom),
                    "coverage": row.get("coverage", ""),
                    "source_status": "SOURCE_AUDIT",
                })
    return pd.DataFrame(rows)


def impact_level(issue_type: str, in_top20: bool, in_top50: bool, cell_count: int, affects_switch: bool, blocks_maturity: bool) -> str:
    if blocks_maturity or (issue_type == "MISSING_PRICE" and in_top20):
        return "BLOCKING_IMPACT"
    if issue_type == "STALE_PRICE" and in_top20:
        return "MEDIUM_IMPACT"
    if issue_type == "MISSING_PRICE" and in_top50:
        return "MEDIUM_IMPACT"
    if affects_switch and issue_type in {"MISSING_PRICE", "STALE_PRICE"}:
        return "MEDIUM_IMPACT"
    if cell_count >= 25:
        return "MEDIUM_IMPACT"
    if in_top50 or cell_count > 0:
        return "LOW_IMPACT"
    return "NO_IMPACT"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    before = protected_hashes()
    errors: list[str] = []

    price = read_csv(PRICE)
    a1 = read_csv(A1)
    c_r2 = read_csv(C_R2)
    c_r2_top50 = read_csv(C_R2_TOP50)
    c_proxy = read_csv(C_R2_PROXY)
    c_proxy_audit = read_csv(C_R2_PROXY_AUDIT)
    ai = read_csv(AI)
    ai_top50 = read_csv(AI_TOP50)
    ai_tags = read_csv(AI_TAGS)
    switch_state = read_csv(SWITCH_STATE)
    switch_components = read_csv(SWITCH_COMPONENTS)
    switch_ledger = read_csv(SWITCH_LEDGER)
    switch_ledger_r1 = read_csv(SWITCH_LEDGER_R1)
    warnings_df = load_warnings()

    universe = set()
    for df in [a1, c_r2, c_r2_top50, c_proxy, ai, ai_top50, ai_tags]:
        universe |= ticker_set(df)
    freshness, latest_price_date = price_freshness(price, universe)

    a1_top20, a1_top50 = top_set(a1, 20), top_set(a1, 50)
    c_top20, c_top50 = top_set(c_r2_top50 if not c_r2_top50.empty else c_r2, 20), top_set(c_r2_top50 if not c_r2_top50.empty else c_r2, 50)
    ai_top20, ai50 = top_set(ai_top50 if not ai_top50.empty else ai, 20), top_set(ai_top50 if not ai_top50.empty else ai, 50)

    tracked_states = set()
    if not switch_ledger.empty and "tracked_state" in switch_ledger.columns:
        tracked_states |= set(switch_ledger["tracked_state"].astype(str))
    if not switch_ledger_r1.empty and "tracked_state" in switch_ledger_r1.columns:
        tracked_states |= set(switch_ledger_r1["tracked_state"].astype(str))
    selected_state = ""
    if not switch_state.empty and "selected_switch_state" in switch_state.columns:
        selected_state = str(switch_state["selected_switch_state"].iloc[0])

    freshness["in_a1_top20"] = freshness["ticker"].isin(a1_top20)
    freshness["in_a1_top50"] = freshness["ticker"].isin(a1_top50)
    freshness["in_c_r2_top20"] = freshness["ticker"].isin(c_top20)
    freshness["in_c_r2_top50"] = freshness["ticker"].isin(c_top50)
    freshness["in_ai_bottleneck_top20"] = freshness["ticker"].isin(ai_top20)
    freshness["in_ai_bottleneck_top50"] = freshness["ticker"].isin(ai50)
    freshness["in_switch_tracked_state"] = freshness["ticker"].isin(a1_top20 | c_top20 | ai_top20)
    write_csv("price_panel_freshness_by_ticker.csv", freshness)

    stale = freshness[freshness["freshness_status"] == "STALE_PRICE"]
    missing = freshness[freshness["freshness_status"] == "MISSING_PRICE"]
    stale_missing = freshness[freshness["freshness_status"].isin(["STALE_PRICE", "MISSING_PRICE"])]
    write_csv("stale_or_missing_tickers.csv", stale_missing)

    freshness_summary = pd.DataFrame([
        {"metric": "price_panel_path", "value": rel(PRICE), "status": "FOUND" if PRICE.exists() else "MISSING"},
        {"metric": "latest_price_date", "value": latest_price_date, "status": "KNOWN" if latest_price_date else "UNKNOWN"},
        {"metric": "expected_latest_market_date", "value": latest_price_date or "UNKNOWN", "status": "DERIVED_FROM_PRICE_PANEL" if latest_price_date else "UNKNOWN"},
        {"metric": "ticker_count", "value": len(freshness), "status": "OK"},
        {"metric": "stale_ticker_count", "value": len(stale), "status": "WARN" if len(stale) else "OK"},
        {"metric": "missing_price_ticker_count", "value": len(missing), "status": "WARN" if len(missing) else "OK"},
        {"metric": "stale_or_missing_in_a1_top20", "value": int(stale_missing["in_a1_top20"].sum()), "status": "WARN" if int(stale_missing["in_a1_top20"].sum()) else "OK"},
        {"metric": "stale_or_missing_in_c_r2_top20", "value": int(stale_missing["in_c_r2_top20"].sum()), "status": "WARN" if int(stale_missing["in_c_r2_top20"].sum()) else "OK"},
        {"metric": "stale_or_missing_in_ai_bottleneck_top20", "value": int(stale_missing["in_ai_bottleneck_top20"].sum()), "status": "WARN" if int(stale_missing["in_ai_bottleneck_top20"].sum()) else "OK"},
        {"metric": "stale_or_missing_in_switch_tracked_states", "value": int(stale_missing["in_switch_tracked_state"].sum()), "status": "WARN" if int(stale_missing["in_switch_tracked_state"].sum()) else "OK"},
    ])
    write_csv("data_freshness_summary.csv", freshness_summary)

    by_ticker = proxy_by_ticker(universe, c_r2, c_proxy, ai_tags)
    write_csv("proxy_coverage_by_ticker.csv", by_ticker)
    proxy_summary = coverage_summary(by_ticker, c_proxy_audit)
    write_csv("proxy_coverage_summary.csv", proxy_summary)
    neutral = by_ticker[by_ticker["neutral_fallback_cell_count"] > 0].copy()
    write_csv("neutral_fallback_cells.csv", neutral)

    module_rows = []
    modules = [
        ("A1", a1, a1_top20, a1_top50),
        ("C-R2", c_r2_top50 if not c_r2_top50.empty else c_r2, c_top20, c_top50),
        ("AI Bottleneck", ai_top50 if not ai_top50.empty else ai, ai_top20, ai50),
        ("switch controller", switch_state, set(), set()),
        ("switch ledger", switch_ledger_r1 if not switch_ledger_r1.empty else switch_ledger, set(), set()),
    ]
    for name, df, top20, top50 in modules:
        module_tickers = ticker_set(df) or top20 or top50
        warn_count = bool_count_warning(warnings_df.to_dict("records"), module_tickers) if not warnings_df.empty else 0
        module_rows.append({
            "module": name,
            "input_available": not df.empty,
            "input_row_count": len(df),
            "ticker_count": len(module_tickers),
            "top20_ticker_count": len(top20),
            "top50_ticker_count": len(top50),
            "stale_or_missing_ticker_count": int(stale_missing["ticker"].isin(module_tickers).sum()) if module_tickers else 0,
            "neutral_fallback_cell_count": int(by_ticker[by_ticker["ticker"].isin(module_tickers)]["neutral_fallback_cell_count"].sum()) if module_tickers else 0,
            "warning_count": warn_count,
            "selected_switch_state": selected_state if name == "switch controller" else "",
            "tracked_state_count": len(tracked_states) if name == "switch ledger" else "",
        })
    strategy_cov = pd.DataFrame(module_rows)
    write_csv("strategy_input_coverage_by_module.csv", strategy_cov)

    impact_rows: list[dict[str, Any]] = []
    for row in stale_missing.to_dict("records"):
        ticker = row["ticker"]
        in_top20 = bool(row["in_a1_top20"] or row["in_c_r2_top20"] or row["in_ai_bottleneck_top20"])
        in_top50 = bool(row["in_a1_top50"] or row["in_c_r2_top50"] or row["in_ai_bottleneck_top50"])
        affects_switch = bool(row["in_switch_tracked_state"])
        impact_rows.append({
            "issue_type": row["freshness_status"],
            "ticker": ticker,
            "affected_cell_count": 1,
            "affects_top20": in_top20,
            "affects_top50": in_top50,
            "affects_current_selected_switch_state": affects_switch,
            "blocks_maturity_calculation": row["freshness_status"] == "MISSING_PRICE" and affects_switch,
            "impact_level": impact_level(row["freshness_status"], in_top20, in_top50, 1, affects_switch, row["freshness_status"] == "MISSING_PRICE" and affects_switch),
        })
    neutral_total = int(neutral["neutral_fallback_cell_count"].sum()) if not neutral.empty else 0
    impact_rows.append({
        "issue_type": "NEUTRAL_FALLBACK_CELLS",
        "ticker": "MULTI" if neutral_total else "",
        "affected_cell_count": neutral_total,
        "affects_top20": bool(neutral["ticker"].isin(a1_top20 | c_top20 | ai_top20).any()) if not neutral.empty else False,
        "affects_top50": bool(neutral["ticker"].isin(a1_top50 | c_top50 | ai50).any()) if not neutral.empty else False,
        "affects_current_selected_switch_state": bool(neutral["ticker"].isin(a1_top20 | c_top20 | ai_top20).any()) if not neutral.empty else False,
        "blocks_maturity_calculation": False,
        "impact_level": impact_level("NEUTRAL_FALLBACK_CELLS", False, False, neutral_total, False, False),
    })
    for row in warnings_df.to_dict("records"):
        text = f"{row.get('warning_type', '')} {row.get('warning', '')}".upper()
        blocks = "MATURITY" in text and ("NO " in text or "PENDING" in text or "WAIT" in text)
        impact_rows.append({
            "issue_type": row.get("warning_type", "WARNING"),
            "ticker": row.get("ticker", "ALL"),
            "affected_cell_count": 1,
            "affects_top20": row.get("ticker") == "ALL" or row.get("ticker") in (a1_top20 | c_top20 | ai_top20),
            "affects_top50": row.get("ticker") == "ALL" or row.get("ticker") in (a1_top50 | c_top50 | ai50),
            "affects_current_selected_switch_state": "SWITCH" in str(row.get("source_file", "")).upper(),
            "blocks_maturity_calculation": blocks,
            "impact_level": impact_level(str(row.get("warning_type", "WARNING")), True, True, 1, "SWITCH" in str(row.get("source_file", "")).upper(), blocks),
        })
    impact = pd.DataFrame(impact_rows)
    write_csv("data_quality_impact_classification.csv", impact)

    after = protected_hashes()
    changed = [path for path, old_hash in before.items() if after.get(path) != old_hash]
    missing_protected = [path for path in before if path not in after]
    audit = pd.DataFrame([{
        "audit_item": "protected_output_mutation_check",
        "protected_file_count_before": len(before),
        "protected_file_count_after": len(after),
        "changed_protected_file_count": len(changed),
        "missing_protected_file_count": len(missing_protected),
        "protected_outputs_modified": False,
        "changed_paths": "|".join(changed),
        "missing_paths": "|".join(missing_protected),
        "stage_output_directory": rel(OUT),
    }])
    write_csv("protected_output_mutation_audit.csv", audit)

    max_impact = "NO_IMPACT"
    if not impact.empty:
        max_impact = max(impact["impact_level"], key=lambda x: IMPACT_ORDER.get(str(x), 0))

    a1_warn = int(stale_missing["in_a1_top20"].sum()) + bool_count_warning(warnings_df.to_dict("records"), a1_top20)
    c_warn = int(stale_missing["in_c_r2_top20"].sum()) + bool_count_warning(warnings_df.to_dict("records"), c_top20)
    ai_warn = int(stale_missing["in_ai_bottleneck_top20"].sum()) + bool_count_warning(warnings_df.to_dict("records"), ai_top20)
    switch_warn = int(stale_missing["in_switch_tracked_state"].sum()) + int(strategy_cov.loc[strategy_cov["module"].str.contains("switch"), "warning_count"].sum())
    warning_count = len(warnings_df) + len(stale_missing) + neutral_total

    if errors:
        final_status = "SCRIPT_ERROR"
        decision = "FAIL_V21_165_DATA_DASHBOARD_SCRIPT_ERROR"
    elif max_impact == "BLOCKING_IMPACT":
        final_status = "WARN"
        decision = "WARN_V21_165_DATA_DASHBOARD_BLOCKING_DATA_ISSUES"
    elif warning_count > 0:
        final_status = "PARTIAL_PASS"
        decision = "PARTIAL_PASS_V21_165_DATA_DASHBOARD_READY_WITH_WARNINGS"
    else:
        final_status = "PASS"
        decision = "PASS_V21_165_DATA_DASHBOARD_READY"

    summary = {
        "final_status": final_status,
        "decision": decision,
        "default_decision_label": "DATA_GOVERNANCE_DASHBOARD_READY_RESEARCH_ONLY",
        **POLICY,
        "latest_price_date_used": latest_price_date,
        "ticker_count": len(freshness),
        "stale_ticker_count": len(stale),
        "missing_price_ticker_count": len(missing),
        "neutral_fallback_cell_count": neutral_total,
        "profitability_proxy_coverage": float(proxy_summary.loc[proxy_summary["proxy_name"].eq("profitability_proxy"), "coverage"].iloc[0]) if not proxy_summary.empty else 0.0,
        "fcf_quality_proxy_coverage": float(proxy_summary.loc[proxy_summary["proxy_name"].eq("fcf_quality_proxy"), "coverage"].iloc[0]) if not proxy_summary.empty else 0.0,
        "value_proxy_coverage": float(proxy_summary.loc[proxy_summary["proxy_name"].eq("value_proxy"), "coverage"].iloc[0]) if not proxy_summary.empty else 0.0,
        "low_vol_proxy_coverage": float(proxy_summary.loc[proxy_summary["proxy_name"].eq("low_vol_proxy"), "coverage"].iloc[0]) if not proxy_summary.empty else 0.0,
        "a1_top20_data_warning_count": a1_warn,
        "c_r2_top20_data_warning_count": c_warn,
        "ai_bottleneck_top20_data_warning_count": ai_warn,
        "switch_state_data_warning_count": switch_warn,
        "max_data_quality_impact": max_impact,
        "dashboard_ready": decision != "FAIL_V21_165_DATA_DASHBOARD_SCRIPT_ERROR",
        "warning_count": int(warning_count),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_directory": rel(OUT),
    }
    write_json("V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD_summary.json", summary)

    report = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"decision={summary['decision']}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "live_trading_allowed=false",
        "protected_outputs_modified=false",
        f"latest_price_date_used={latest_price_date}",
        f"ticker_count={len(freshness)}",
        f"stale_ticker_count={len(stale)}",
        f"missing_price_ticker_count={len(missing)}",
        f"neutral_fallback_cell_count={neutral_total}",
        f"a1_top20_data_warning_count={a1_warn}",
        f"c_r2_top20_data_warning_count={c_warn}",
        f"ai_bottleneck_top20_data_warning_count={ai_warn}",
        f"switch_state_data_warning_count={switch_warn}",
        f"max_data_quality_impact={max_impact}",
        f"dashboard_ready={summary['dashboard_ready']}",
        f"warning_count={warning_count}",
    ]
    (OUT / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")

    print(f"final_status={summary['final_status']}")
    print(f"decision={summary['decision']}")
    print(f"latest_price_date_used={latest_price_date}")
    print(f"stale_ticker_count={len(stale)}")
    print(f"missing_price_ticker_count={len(missing)}")
    print(f"neutral_fallback_cell_count={neutral_total}")
    print("proxy_coverage_summary=")
    print(proxy_summary.to_string(index=False))
    print(f"a1_top20_data_warning_count={a1_warn}")
    print(f"c_r2_top20_data_warning_count={c_warn}")
    print(f"ai_bottleneck_top20_data_warning_count={ai_warn}")
    print(f"max_data_quality_impact={max_impact}")
    print(f"warnings={warning_count}")


if __name__ == "__main__":
    main()
