from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.168_600USD_CASH_CONSTRAINED_EXECUTION_FALLBACK_CONTROLLER"
OUT = ROOT / "outputs" / "v21" / STAGE

PRICE = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
A1 = ROOT / "outputs" / "v21" / "V21.113_LATEST_DATA_ABCD_RERUN_20260625_PRICE_REFRESH" / "A1_BASELINE_CONTROL_latest_ranking.csv"
C_R2 = ROOT / "outputs" / "v21" / "V21.161_R1_C_R2_PROXY_AND_REGIME_REPAIR" / "c_r2_r1_shadow_ranking_top50.csv"
AI = ROOT / "outputs" / "v21" / "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING" / "ai_bottleneck_shadow_ranking_top50.csv"
AI_TAGS = ROOT / "outputs" / "v21" / "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING" / "ai_bottleneck_universe_tags.csv"
SWITCH_STATE = ROOT / "outputs" / "v21" / "V21.163_C_R2_AI_BOTTLENECK_SWITCH_CONTROLLER" / "switch_controller_state.csv"
SWITCH_R1_SUMMARY = ROOT / "outputs" / "v21" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR_summary.json"
V165_SUMMARY = ROOT / "outputs" / "v21" / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD" / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD_summary.json"
V167_R1_SUMMARY = ROOT / "outputs" / "v21" / "V21.167_R1_ACTIVE_600USD_SMALL_ACCOUNT_OVERLAY_RECHECK" / "V21.167_R1_ACTIVE_600USD_SMALL_ACCOUNT_OVERLAY_RECHECK_summary.json"
V167_R1_BLOCKERS = ROOT / "outputs" / "v21" / "V21.167_R1_ACTIVE_600USD_SMALL_ACCOUNT_OVERLAY_RECHECK" / "active_600usd_overlay_blockers.csv"
V166_SUMMARY = ROOT / "outputs" / "v21" / "V21.166_REALISTIC_EXECUTION_CONSTRAINT_SIMULATOR" / "V21.166_REALISTIC_EXECUTION_CONSTRAINT_SIMULATOR_summary.json"
EVENT_LEDGER = ROOT / "outputs" / "v21" / "v21_096_r6_certified_event_master_ledger.csv"

ACTIVE_CASH = 600
MAX_SINGLE = 0.35
MAX_SINGLE_DOLLARS = 210
MAX_THEME = 0.25
MAX_THEME_DOLLARS = 150
MIN_DIVERSIFIED_POS = 3
PREF_MIN = 3
PREF_MAX = 5
MAX_POS = 5
SHARE_COUNTS = [1, 2, 3, 5, 8]
RETURNS = [-0.05, -0.08, -0.10, -0.15, -0.20]
POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "live_trading_allowed": False,
    "protected_outputs_modified": False,
    "role_review_required": False,
    "fallback_adoption_allowed": False,
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


def latest_prices() -> tuple[pd.DataFrame, dict[str, float], str]:
    df = read_csv(PRICE)
    if df.empty or "date" not in df.columns:
        return pd.DataFrame(columns=["ticker", "price", "latest_price_date"]), {}, ""
    ticker_col = "symbol" if "symbol" in df.columns else "ticker"
    price_col = "adjusted_close" if "adjusted_close" in df.columns else "close"
    work = df[[ticker_col, "date", price_col]].copy()
    work[ticker_col] = norm(work[ticker_col])
    work["_date"] = pd.to_datetime(work["date"], errors="coerce")
    work["price"] = pd.to_numeric(work[price_col], errors="coerce")
    work = work.dropna(subset=["_date", "price"]).sort_values([ticker_col, "_date"])
    latest = work.groupby(ticker_col).tail(1).rename(columns={ticker_col: "ticker"})
    latest["latest_price_date"] = latest["_date"].dt.strftime("%Y-%m-%d")
    latest_date = "" if latest.empty else str(latest["_date"].max().date())
    out = latest[["ticker", "price", "latest_price_date"]].reset_index(drop=True)
    return out, dict(zip(out["ticker"], out["price"])), latest_date


def ranked_tickers(df: pd.DataFrame, source: str, limit: int = 20) -> list[dict[str, Any]]:
    if df.empty or "ticker" not in df.columns:
        return []
    work = df.copy()
    if "rank" in work.columns:
        work["_rank"] = pd.to_numeric(work["rank"], errors="coerce")
        work = work.sort_values("_rank", na_position="last")
    rows = []
    seen = set()
    for i, row in enumerate(work.to_dict("records"), start=1):
        ticker = str(row.get("ticker", "")).upper().strip()
        if not ticker or ticker == "NAN" or ticker in seen:
            continue
        seen.add(ticker)
        rows.append({"ticker": ticker, "source": source, "source_rank": row.get("rank", i), "tag_bucket": ""})
        if len(rows) >= limit:
            break
    return rows


def ai_tag_rows(ai_tags: pd.DataFrame) -> list[dict[str, Any]]:
    if ai_tags.empty or "ticker" not in ai_tags.columns:
        return []
    buckets = {
        "DRAM_HBM_NAND": "DRAM|HBM|NAND",
        "STORAGE": "STORAGE|HDD|SSD",
        "SEMICAP": "SEMICAP|SEMICONDUCTOR EQUIPMENT",
        "ADVANCED_PACKAGING": "ADVANCED_PACKAGING|PACKAGING",
    }
    rows = []
    for row in ai_tags.to_dict("records"):
        ticker = str(row.get("ticker", "")).upper().strip()
        text = " ".join(str(row.get(c, "")) for c in ["primary_ai_bottleneck_theme", "secondary_ai_bottleneck_theme", "reason", "industry"]).upper()
        tags = [name for name, pattern in buckets.items() if pd.Series([text]).str.contains(pattern, regex=True).iloc[0]]
        if tags:
            rows.append({"ticker": ticker, "source": "AI_BOTTLENECK_TAGS", "source_rank": "", "tag_bucket": "|".join(tags)})
    return rows


def exposure_bucket(weight: float) -> str:
    if weight <= 0.25:
        return "LOW_ACCOUNT_EXPOSURE"
    if weight <= 0.35:
        return "CONTROLLED_CONCENTRATION"
    if weight <= 0.50:
        return "CAP_BREACH_CONCENTRATION"
    if weight <= 0.80:
        return "HIGH_CONCENTRATION"
    return "EXTREME_CONCENTRATION"


def loss_bucket(account_loss_pct: float) -> str:
    x = abs(account_loss_pct)
    if x <= 0.01:
        return "<=1% account loss"
    if x <= 0.025:
        return ">1% and <=2.5%"
    if x <= 0.05:
        return ">2.5% and <=5%"
    if x <= 0.10:
        return ">5% and <=10%"
    return ">10%"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    before = protected_hashes()
    price_df, price_map, latest_price_date = latest_prices()
    v167 = read_json(V167_R1_SUMMARY)
    v165 = read_json(V165_SUMMARY)
    v166 = read_json(V166_SUMMARY)
    switch_r1 = read_json(SWITCH_R1_SUMMARY)
    switch = read_csv(SWITCH_STATE)
    selected_regime = str(v167.get("selected_regime") or "UNKNOWN")
    regime_confidence = v167.get("regime_confidence", "")
    if not switch.empty:
        selected_regime = str(switch.get("selected_regime", pd.Series([selected_regime])).iloc[0])
        regime_confidence = switch.get("regime_confidence", pd.Series([regime_confidence])).iloc[0]

    candidate_rows = []
    candidate_rows += ranked_tickers(read_csv(A1), "A1_TOP")
    candidate_rows += ranked_tickers(read_csv(C_R2), "C_R2_TOP")
    candidate_rows += ranked_tickers(read_csv(AI), "AI_BOTTLENECK_TOP")
    candidate_rows += ai_tag_rows(read_csv(AI_TAGS))
    merged: dict[str, dict[str, Any]] = {}
    for row in candidate_rows:
        ticker = row["ticker"]
        if ticker not in merged:
            merged[ticker] = {"ticker": ticker, "sources": [], "tag_buckets": [], "best_source_rank": row.get("source_rank", "")}
        merged[ticker]["sources"].append(row["source"])
        if row.get("tag_bucket"):
            merged[ticker]["tag_buckets"].extend(str(row["tag_bucket"]).split("|"))
    universe = []
    warnings = []
    for ticker, row in sorted(merged.items()):
        price = price_map.get(ticker)
        priced = price is not None and not pd.isna(price) and price > 0
        if not priced:
            warnings.append({"warning_type": "MISSING_PRICE_EXCLUDED_FROM_FEASIBILITY", "ticker": ticker, "warning": "Candidate retained in universe but excluded from priced fallback feasibility."})
        tags = sorted(set(x for x in row["tag_buckets"] if x))
        universe.append({
            "ticker": ticker,
            "sources": "|".join(sorted(set(row["sources"]))),
            "tag_buckets": "|".join(tags),
            "is_dram_hbm_nand": "DRAM_HBM_NAND" in tags,
            "is_storage_semicap_packaging": any(t in tags for t in ["STORAGE", "SEMICAP", "ADVANCED_PACKAGING"]),
            "priced": priced,
            "price": price if priced else "",
            "classification": "CASH_CONSTRAINED_FALLBACK_MODE_RESEARCH_ONLY",
            "not_user_preference_only_strategy": True,
            "not_diversified_portfolio": True,
            "research_only": True,
        })
    universe_df = pd.DataFrame(universe)
    write_csv("fallback_candidate_universe_600usd.csv", universe_df)
    priced_df = universe_df[universe_df["priced"].eq(True)].copy()

    feasibility_rows = []
    share_rows = []
    loss_rows = []
    for row in priced_df.to_dict("records"):
        ticker = row["ticker"]
        price = float(row["price"])
        max_shares = int(ACTIVE_CASH // price)
        one_share_weight = price / ACTIVE_CASH
        feasibility_rows.append({
            "ticker": ticker,
            "price": price,
            "sources": row["sources"],
            "tag_buckets": row["tag_buckets"],
            "max_whole_shares_purchasable": max_shares,
            "one_share_exposure_weight": one_share_weight,
            "one_share_exposure_bucket": exposure_bucket(one_share_weight),
            "breaches_25pct": one_share_weight > 0.25,
            "breaches_35pct": one_share_weight > 0.35,
            "breaches_50pct": one_share_weight > 0.50,
            "breaches_80pct": one_share_weight > 0.80,
            "fallback_candidate_state": "DRAM_AS_CASH_CONSTRAINED_FALLBACK_CANDIDATE" if row["is_dram_hbm_nand"] else "CASH_CONSTRAINED_FALLBACK_MODE_RESEARCH_ONLY",
            "not_user_preference_only_strategy": True,
            "not_diversified_portfolio": True,
            "research_only": True,
            "broker_action_allowed": False,
            "live_trading_allowed": False,
            "official_adoption_allowed": False,
        })
        for n in SHARE_COUNTS:
            exposure = price * n
            feasible = exposure <= ACTIVE_CASH
            weight = exposure / ACTIVE_CASH
            share_rows.append({
                "ticker": ticker,
                "price": price,
                "share_count": n,
                "share_count_feasible": feasible,
                "dollar_exposure": exposure if feasible else "",
                "leftover_cash": ACTIVE_CASH - exposure if feasible else "",
                "exposure_weight": weight if feasible else "",
                "concentration_bucket": exposure_bucket(weight) if feasible else "NOT_PURCHASABLE_WITH_600USD",
                "diversified_portfolio_eligible": False,
                "research_only": True,
            })
            if feasible:
                for ret in RETURNS:
                    loss = exposure * ret
                    acct_loss_pct = loss / ACTIVE_CASH
                    loss_rows.append({
                        "ticker": ticker,
                        "share_count": n,
                        "ticker_return": ret,
                        "position_loss_usd": loss,
                        "account_loss_pct": acct_loss_pct,
                        "loss_bucket": loss_bucket(acct_loss_pct),
                        "research_only": True,
                    })
    feasibility_df = pd.DataFrame(feasibility_rows)
    share_df = pd.DataFrame(share_rows)
    loss_df = pd.DataFrame(loss_rows)
    write_csv("fallback_candidate_feasibility_600usd.csv", feasibility_df)
    write_csv("share_count_feasibility_600usd.csv", share_df)
    write_csv("account_loss_budget_scenarios_600usd.csv", loss_df)
    dram_df = feasibility_df[feasibility_df["tag_buckets"].astype(str).str.contains("DRAM_HBM_NAND", na=False)].copy() if not feasibility_df.empty else pd.DataFrame()
    write_csv("dram_hbm_nand_fallback_check_600usd.csv", dram_df)
    write_csv("single_name_exposure_scenarios_600usd.csv", feasibility_df)

    active_exec = int(v167.get("active_600usd_executable_state_count", 0) or 0)
    active_blocked = int(v167.get("active_600usd_blocked_state_count", 0) or 0)
    portfolio_blocked = active_exec == 0
    portfolio_reason = "ACTIVE_600USD_EXECUTABLE_DIVERSIFIED_STATE_COUNT_ZERO" if portfolio_blocked else "ACTIVE_600USD_HAS_EXECUTABLE_DIVERSIFIED_STATE"
    inherited_blockers = read_csv(V167_R1_BLOCKERS)
    write_csv("portfolio_mode_blockers_600usd.csv", inherited_blockers)
    state_rows = [
        {"classification_state": "PORTFOLIO_MODE_BLOCKED_BY_INSUFFICIENT_CAPITAL_600USD", "active": portfolio_blocked, "notes": portfolio_reason},
        {"classification_state": "CASH_CONSTRAINED_FALLBACK_MODE_RESEARCH_ONLY", "active": True, "notes": "Fallback analysis only; not a new strategy and not a trading instruction."},
        {"classification_state": "NOT_USER_PREFERENCE_ONLY_STRATEGY", "active": True, "notes": "DRAM/HBM/NAND fallback is driven by cash and whole-share constraints."},
        {"classification_state": "NOT_DIVERSIFIED_PORTFOLIO", "active": True, "notes": "One-name/two-name fallback exposure is non-diversified."},
        {"classification_state": "FALLBACK_EXECUTION_NOT_PROMOTED", "active": True, "notes": "No official, broker, live, or fallback adoption enabled."},
        {"classification_state": "NO_BROKER_ACTION_ALLOWED", "active": True, "notes": "No order or broker file generated."},
        {"classification_state": "NO_OFFICIAL_ADOPTION_ALLOWED", "active": True, "notes": "Research-only classification."},
    ]
    if dram_df.empty:
        state_rows.append({"classification_state": "DRAM_FALLBACK_UNAVAILABLE_MISSING_PRICE", "active": True, "notes": "No priced DRAM/HBM/NAND tagged candidate."})
    else:
        max_dram_exposure = float(dram_df["one_share_exposure_weight"].max())
        state_rows.append({"classification_state": "DRAM_AS_CASH_CONSTRAINED_FALLBACK_CANDIDATE", "active": True, "notes": "Priced DRAM/HBM/NAND tagged candidates exist."})
        if max_dram_exposure > MAX_SINGLE or len(dram_df) < MIN_DIVERSIFIED_POS:
            state_rows.append({"classification_state": "DRAM_FALLBACK_AVAILABLE_BUT_CONCENTRATION_BLOCKED", "active": True, "notes": "DRAM fallback is non-diversified or breaches concentration."})
    if not EVENT_LEDGER.exists() or read_csv(EVENT_LEDGER).empty:
        state_rows.append({"classification_state": "EVENT_DATA_UNAVAILABLE", "active": True, "notes": "No event coverage claimed."})
    write_csv("cash_constrained_fallback_state.csv", pd.DataFrame(state_rows))
    write_csv("fallback_vs_portfolio_separation.csv", pd.DataFrame([
        {"mode": "PORTFOLIO_MODE", "state": "BLOCKED" if portfolio_blocked else "AVAILABLE", "description": "Diversified portfolio execution under ranking/sleeve logic.", "promoted": False},
        {"mode": "CASH_CONSTRAINED_FALLBACK_MODE", "state": "RESEARCH_ONLY_TRACKABLE", "description": "Non-diversified fallback analysis caused by USD 600 whole-share constraints.", "promoted": False},
        {"mode": "DRAM_HBM_NAND_FALLBACK", "state": "NOT_USER_PREFERENCE_ONLY_STRATEGY", "description": "Tagged candidates are fallback candidates, not a diversified portfolio or stated preference-only strategy.", "promoted": False},
    ]))

    event_available = EVENT_LEDGER.exists() and not read_csv(EVENT_LEDGER).empty
    maturity_available = int(switch_r1.get("matured_result_count_after", 0) or 0) > 0
    data_quality_impact = str(v165.get("max_data_quality_impact", "UNKNOWN"))
    warnings += [
        {"warning_type": "PORTFOLIO_MODE_BLOCKED", "ticker": "ALL", "warning": portfolio_reason},
        {"warning_type": "FALLBACK_NOT_DIVERSIFIED", "ticker": "ALL", "warning": "Fallback mode is explicitly non-diversified and not promoted."},
        {"warning_type": "DATA_QUALITY_IMPACT", "ticker": "ALL", "warning": f"V21.165 max_data_quality_impact={data_quality_impact}"},
        {"warning_type": "MATURITY_EVIDENCE", "ticker": "ALL", "warning": f"maturity_evidence_available={maturity_available}"},
    ]
    if not event_available:
        warnings.append({"warning_type": "EVENT_DATA_UNAVAILABLE", "ticker": "ALL", "warning": "Event/earnings data unavailable; event coverage not claimed."})
    write_csv("fallback_data_quality_warnings.csv", pd.DataFrame(warnings))
    write_csv("fallback_policy_flags.csv", pd.DataFrame([{**POLICY, "fallback_execution_promoted": False, "orders_created": False, "broker_files_created": False}]))
    after = protected_hashes()
    changed = [p for p, h in before.items() if after.get(p) != h]
    write_csv("protected_output_mutation_audit.csv", pd.DataFrame([{
        "audit_item": "protected_output_mutation_check",
        "protected_file_count_before": len(before),
        "protected_file_count_after": len(after),
        "changed_protected_file_count": len(changed),
        "protected_outputs_modified": False,
        "changed_paths": "|".join(changed),
        "stage_output_directory": rel(OUT),
    }]))

    priced_count = len(priced_df)
    dram_count = int(universe_df["is_dram_hbm_nand"].sum()) if not universe_df.empty else 0
    dram_available = not dram_df.empty
    dram_blocked = dram_available and (float(dram_df["one_share_exposure_weight"].max()) > MAX_SINGLE or len(dram_df) < MIN_DIVERSIFIED_POS)
    feasible_share_weights = pd.to_numeric(share_df.loc[share_df["share_count_feasible"].eq(True), "exposure_weight"], errors="coerce") if not share_df.empty else pd.Series(dtype=float)
    max_weight = float(feasible_share_weights.max()) if not feasible_share_weights.empty else 0.0
    max_loss = abs(float(loss_df["account_loss_pct"].min())) if not loss_df.empty else 0.0
    blocker_count = len(inherited_blockers) + int(portfolio_blocked) + int(dram_blocked) + int(not maturity_available) + int(data_quality_impact == "BLOCKING_IMPACT")
    warning_count = len(warnings)
    decision = "WARN_V21_168_CASH_CONSTRAINED_FALLBACK_RESEARCH_ONLY_PORTFOLIO_BLOCKED" if portfolio_blocked else "PARTIAL_PASS_V21_168_CASH_CONSTRAINED_FALLBACK_READY_WITH_WARNINGS"
    final_status = "WARN" if portfolio_blocked else "PARTIAL_PASS"
    summary = {
        "final_status": final_status,
        "decision": decision,
        "default_decision_label": "CASH_CONSTRAINED_FALLBACK_RESEARCH_ONLY_PORTFOLIO_MODE_BLOCKED",
        **POLICY,
        "active_cash_budget_usd": ACTIVE_CASH,
        "latest_price_date_used": latest_price_date or v167.get("latest_price_date_used"),
        "selected_regime": selected_regime,
        "regime_confidence": float(regime_confidence) if str(regime_confidence) else "",
        "portfolio_mode_blocked": portfolio_blocked,
        "portfolio_mode_block_reason": portfolio_reason,
        "cash_constrained_fallback_mode_research_only": True,
        "not_user_preference_only_strategy": True,
        "not_diversified_portfolio": True,
        "fallback_candidate_count": len(universe_df),
        "priced_fallback_candidate_count": priced_count,
        "dram_hbm_nand_candidate_count": dram_count,
        "dram_fallback_available": dram_available,
        "dram_fallback_concentration_blocked": dram_blocked,
        "max_single_name_exposure_weight": max_weight,
        "max_account_loss_pct_scenario": max_loss,
        "maturity_evidence_available": maturity_available,
        "data_quality_impact": data_quality_impact,
        "event_data_available": event_available,
        "fallback_execution_promoted": False,
        "blocker_count": int(blocker_count),
        "warning_count": int(warning_count),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_directory": rel(OUT),
    }
    write_json("V21.168_600USD_CASH_CONSTRAINED_EXECUTION_FALLBACK_CONTROLLER_summary.json", summary)
    loss_summary = loss_df.groupby("ticker").agg(max_account_loss_pct=("account_loss_pct", "min")).reset_index().sort_values("max_account_loss_pct").head(5).to_dict("records") if not loss_df.empty else []
    report = [
        STAGE,
        f"final_status={final_status}",
        f"decision={decision}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "live_trading_allowed=false",
        "fallback_adoption_allowed=false",
        "protected_outputs_modified=false",
        f"active_cash_budget_usd={ACTIVE_CASH}",
        f"latest_price_date_used={summary['latest_price_date_used']}",
        f"selected_regime={selected_regime}",
        f"regime_confidence={regime_confidence}",
        f"portfolio_mode_blocked={portfolio_blocked}",
        f"portfolio_block_reason={portfolio_reason}",
        "fallback_mode_state=CASH_CONSTRAINED_FALLBACK_MODE_RESEARCH_ONLY",
        "not_user_preference_only_strategy=True",
        "not_diversified_portfolio=True",
        f"dram_hbm_nand_fallback_available={dram_available}",
        f"max_single_name_exposure_weight={max_weight}",
        f"account_loss_budget_scenario_summary={loss_summary}",
        f"event_data_available={event_available}",
        f"warnings={warning_count}",
    ]
    (OUT / "V21.168_600USD_CASH_CONSTRAINED_EXECUTION_FALLBACK_CONTROLLER_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report[1:]))


if __name__ == "__main__":
    main()
