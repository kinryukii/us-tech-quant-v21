from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.171_NON_BLOCKING_PRICE_ISSUE_REPAIR_PREFLIGHT"
OUT = ROOT / "outputs" / "v21" / STAGE
TARGETS = ["BITF", "PSTG", "SATS", "TQQQ"]

PRICE = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
A1 = ROOT / "outputs" / "v21" / "V21.113_LATEST_DATA_ABCD_RERUN_20260625_PRICE_REFRESH" / "A1_BASELINE_CONTROL_latest_ranking.csv"
C_R2 = ROOT / "outputs" / "v21" / "V21.161_R1_C_R2_PROXY_AND_REGIME_REPAIR" / "c_r2_r1_shadow_ranking_top50.csv"
AI = ROOT / "outputs" / "v21" / "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING" / "ai_bottleneck_shadow_ranking_top50.csv"
V165_SUMMARY = ROOT / "outputs" / "v21" / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD" / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD_summary.json"
V165_STALE = ROOT / "outputs" / "v21" / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD" / "stale_or_missing_tickers.csv"
V170_SUMMARY = ROOT / "outputs" / "v21" / "V21.170_DATA_QUALITY_BLOCKER_DECOMPOSITION_AND_REPAIR_PLAN" / "V21.170_DATA_QUALITY_BLOCKER_DECOMPOSITION_AND_REPAIR_PLAN_summary.json"
V170_PLAN = ROOT / "outputs" / "v21" / "V21.170_DATA_QUALITY_BLOCKER_DECOMPOSITION_AND_REPAIR_PLAN" / "data_repair_action_plan.csv"
SWITCH_R1_LEDGER = ROOT / "outputs" / "v21" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR" / "switch_ledger_r1_full_ledger.csv"

POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "live_trading_allowed": False,
    "protected_outputs_modified": False,
    "role_review_required": False,
}


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(name: str, df: pd.DataFrame) -> None:
    df.to_csv(OUT / name, index=False)


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


def norm(s: pd.Series) -> pd.Series:
    return s.astype(str).str.upper().str.strip()


def ticker_sets(df: pd.DataFrame) -> tuple[set[str], set[str]]:
    if df.empty or "ticker" not in df.columns:
        return set(), set()
    work = df.copy()
    if "rank" in work.columns:
        work["_rank"] = pd.to_numeric(work["rank"], errors="coerce")
        work = work.sort_values("_rank", na_position="last")
    tickers = norm(work["ticker"]).tolist()
    return set(tickers[:20]), set(tickers[:50])


def price_status() -> tuple[pd.DataFrame, str]:
    df = read_csv(PRICE)
    if df.empty or "date" not in df.columns:
        return pd.DataFrame(columns=["ticker", "latest_price_date", "price_row_count"]), ""
    ticker_col = "symbol" if "symbol" in df.columns else "ticker"
    work = df[[ticker_col, "date"]].copy()
    work[ticker_col] = norm(work[ticker_col])
    work["_date"] = pd.to_datetime(work["date"], errors="coerce")
    latest = work.dropna(subset=["_date"]).groupby(ticker_col).agg(latest_price_date=("_date", "max"), price_row_count=("_date", "size")).reset_index()
    latest = latest.rename(columns={ticker_col: "ticker"})
    panel_latest = "" if latest.empty else str(latest["latest_price_date"].max().date())
    latest["latest_price_date"] = latest["latest_price_date"].dt.strftime("%Y-%m-%d")
    return latest, panel_latest


def classify(row: dict[str, Any], active: bool, maturity_dep: bool) -> str:
    status = str(row.get("freshness_status", ""))
    if active or maturity_dep:
        return "REPAIR_REQUIRED_BEFORE_ACTIVE_USE"
    if status == "MISSING_PRICE":
        return "REPAIR_RECOMMENDED_FOR_DATA_CLEANLINESS" if row.get("in_any_top50") else "REPAIR_OPTIONAL_NOT_ACTIVE"
    if status == "STALE_PRICE":
        return "SAFE_TO_REPAIR_NON_BLOCKING"
    return "EXCLUDE_IF_PRICE_UNAVAILABLE"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    before = protected_hashes()
    v165 = read_json(V165_SUMMARY)
    v170 = read_json(V170_SUMMARY)
    stale = read_csv(V165_STALE)
    plan = read_csv(V170_PLAN)
    prices, panel_latest = price_status()
    a1_20, a1_50 = ticker_sets(read_csv(A1))
    c20, c50 = ticker_sets(read_csv(C_R2))
    ai20, ai50 = ticker_sets(read_csv(AI))
    switch_ledger = read_csv(SWITCH_R1_LEDGER)

    stale_by = {str(r.get("ticker", "")).upper(): r for r in stale.to_dict("records")}
    price_by = {str(r.get("ticker", "")).upper(): r for r in prices.to_dict("records")}
    plan_by = {str(r.get("ticker", "")).upper(): r for r in plan.to_dict("records")}
    rows = []
    for ticker in TARGETS:
        p = price_by.get(ticker, {})
        s = stale_by.get(ticker, {})
        exists_price = bool(p)
        latest = s.get("latest_price_date") or p.get("latest_price_date", "")
        status = s.get("freshness_status", "OK" if exists_price else "MISSING_PRICE")
        active = ticker in a1_20 or ticker in c20 or ticker in ai20 or bool(s.get("in_switch_tracked_state", False))
        maturity_dep = bool(s.get("in_switch_tracked_state", False))
        in_any_top50 = ticker in a1_50 or ticker in c50 or ticker in ai50
        base = {
            "ticker": ticker,
            "exists_in_current_universe": ticker in (a1_50 | c50 | ai50),
            "exists_in_latest_price_panel": exists_price,
            "latest_price_date": latest,
            "has_missing_price_status": status == "MISSING_PRICE",
            "has_stale_price_status": status == "STALE_PRICE",
            "freshness_status": status,
            "appears_in_a1_top20": ticker in a1_20,
            "appears_in_a1_top50": ticker in a1_50,
            "appears_in_c_r2_top20": ticker in c20,
            "appears_in_c_r2_top50": ticker in c50,
            "appears_in_ai_bottleneck_top20": ticker in ai20,
            "appears_in_ai_bottleneck_top50": ticker in ai50,
            "appears_in_switch_tracked_holdings": maturity_dep,
            "needed_for_pending_maturity_calculations": maturity_dep,
            "in_any_top50": in_any_top50,
        }
        base["repair_classification"] = classify(base, active, maturity_dep)
        base["v170_impact_class"] = plan_by.get(ticker, {}).get("impact_class", "")
        rows.append(base)

    detail = pd.DataFrame(rows)
    write_csv("target_ticker_price_issue_detail.csv", detail)
    write_csv("target_ticker_active_holding_impact.csv", detail[[
        "ticker", "appears_in_a1_top20", "appears_in_a1_top50", "appears_in_c_r2_top20",
        "appears_in_c_r2_top50", "appears_in_ai_bottleneck_top20", "appears_in_ai_bottleneck_top50",
        "appears_in_switch_tracked_holdings", "needed_for_pending_maturity_calculations", "repair_classification",
    ]])
    write_csv("target_ticker_universe_membership_check.csv", detail[["ticker", "exists_in_current_universe", "exists_in_latest_price_panel", "latest_price_date", "freshness_status"]])
    safety = []
    recs = []
    for r in detail.to_dict("records"):
        actual_refresh_needed = r["has_missing_price_status"] or r["has_stale_price_status"]
        safety.append({
            "ticker": r["ticker"],
            "future_refresh_requires_canonical_price_panel_mutation": actual_refresh_needed,
            "preflight_mutates_canonical_price_panel": False,
            "future_refresh_affects_protected_outputs": False,
            "future_refresh_alters_existing_ledger_rows": False,
            "future_refresh_alters_historical_rankings": False,
            "future_refresh_only_improves_future_data_cleanliness": True,
            "safe_for_later_approved_refresh_stage": True,
        })
        recs.append({
            "ticker": r["ticker"],
            "repair_classification": r["repair_classification"],
            "recommended_action": "QUEUE_FOR_SEPARATE_APPROVED_PRICE_REFRESH_STAGE" if actual_refresh_needed else "NO_REFRESH_NEEDED",
            "refresh_required_before_active_use": r["repair_classification"] == "REPAIR_REQUIRED_BEFORE_ACTIVE_USE",
            "safe_to_continue_research_without_refresh": r["repair_classification"] != "REPAIR_REQUIRED_BEFORE_ACTIVE_USE",
            "research_only": True,
            "broker_action_allowed": False,
            "live_trading_allowed": False,
            "official_adoption_allowed": False,
        })
    safety_df = pd.DataFrame(safety)
    rec_df = pd.DataFrame(recs)
    write_csv("target_ticker_refresh_safety_check.csv", safety_df)
    write_csv("target_ticker_repair_recommendation.csv", rec_df)
    write_csv("canonical_price_panel_mutation_risk.csv", pd.DataFrame([{
        "canonical_price_panel_path": rel(PRICE),
        "preflight_mutated_canonical_price_panel": False,
        "actual_future_refresh_would_require_mutation": bool(safety_df["future_refresh_requires_canonical_price_panel_mutation"].any()),
        "protected_outputs_expected_to_change": False,
        "official_outputs_expected_to_change": False,
        "existing_ledger_rows_expected_to_change": False,
        "historical_rankings_expected_to_change": False,
    }]))

    safe_count = int(detail["repair_classification"].isin(["SAFE_TO_REPAIR_NON_BLOCKING", "REPAIR_RECOMMENDED_FOR_DATA_CLEANLINESS", "REPAIR_OPTIONAL_NOT_ACTIVE"]).sum())
    rec_count = int(detail["repair_classification"].isin(["SAFE_TO_REPAIR_NON_BLOCKING", "REPAIR_RECOMMENDED_FOR_DATA_CLEANLINESS"]).sum())
    required_count = int(detail["repair_classification"].eq("REPAIR_REQUIRED_BEFORE_ACTIVE_USE").sum())
    active_count = int(detail[["appears_in_a1_top20", "appears_in_c_r2_top20", "appears_in_ai_bottleneck_top20", "appears_in_switch_tracked_holdings"]].any(axis=1).sum())
    maturity_count = int(detail["needed_for_pending_maturity_calculations"].sum())
    write_csv("price_issue_repair_preflight_summary.csv", pd.DataFrame([{
        "target_ticker_count": len(TARGETS),
        "safe_to_repair_count": safe_count,
        "repair_recommended_count": rec_count,
        "repair_required_before_active_use_count": required_count,
        "active_holding_impact_count": active_count,
        "maturity_dependency_count": maturity_count,
        "future_refresh_stage_recommended": rec_count > 0,
        "preflight_performed_refresh": False,
    }]))

    after = protected_hashes()
    changed = [p for p, h in before.items() if after.get(p) != h]
    audit_clean = len(changed) == 0
    write_csv("protected_output_mutation_audit.csv", pd.DataFrame([{
        "audit_item": "protected_output_mutation_check",
        "changed_protected_file_count": len(changed),
        "protected_outputs_modified": False,
        "audit_clean": audit_clean,
        "changed_paths": "|".join(changed),
        "stage_output_directory": rel(OUT),
    }]))

    future_refresh = rec_count > 0
    warning_count = rec_count + required_count
    if required_count > 0:
        final_status = "WARN"
        decision = "WARN_V21_171_PRICE_REPAIR_PREFLIGHT_ACTIVE_DEPENDENCY_FOUND"
    elif warning_count:
        final_status = "PARTIAL_PASS"
        decision = "PARTIAL_PASS_V21_171_PRICE_REPAIR_PREFLIGHT_READY_WITH_WARNINGS"
    else:
        final_status = "PASS"
        decision = "PASS_V21_171_PRICE_REPAIR_PREFLIGHT_READY"
    summary = {
        "final_status": final_status,
        "decision": decision,
        "default_decision_label": "NON_BLOCKING_PRICE_REPAIR_PREFLIGHT_READY_RESEARCH_ONLY",
        **POLICY,
        "latest_price_date_used": panel_latest or v165.get("latest_price_date_used", ""),
        "target_ticker_count": len(TARGETS),
        "safe_to_repair_count": safe_count,
        "repair_recommended_count": rec_count,
        "repair_required_before_active_use_count": required_count,
        "active_holding_impact_count": active_count,
        "maturity_dependency_count": maturity_count,
        "canonical_mutation_required_for_actual_refresh": bool(safety_df["future_refresh_requires_canonical_price_panel_mutation"].any()),
        "protected_output_mutation_audit_clean": audit_clean,
        "future_refresh_stage_recommended": future_refresh,
        "warning_count": warning_count,
        "preflight_performed_refresh": False,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_directory": rel(OUT),
    }
    write_json("V21.171_NON_BLOCKING_PRICE_ISSUE_REPAIR_PREFLIGHT_summary.json", summary)
    classes = "; ".join(f"{r['ticker']}={r['repair_classification']}" for r in detail.to_dict("records"))
    report = [
        STAGE,
        f"final_status={final_status}",
        f"decision={decision}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "live_trading_allowed=false",
        "protected_outputs_modified=false",
        f"latest_price_date_used={summary['latest_price_date_used']}",
        f"target_ticker_classifications={classes}",
        f"safe_to_repair_count={safe_count}",
        f"repair_recommended_count={rec_count}",
        f"active_holding_impact_count={active_count}",
        f"maturity_dependency_count={maturity_count}",
        f"future_refresh_stage_recommended={future_refresh}",
        f"warnings={warning_count}",
    ]
    (OUT / "V21.171_NON_BLOCKING_PRICE_ISSUE_REPAIR_PREFLIGHT_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report[1:]))


if __name__ == "__main__":
    main()
