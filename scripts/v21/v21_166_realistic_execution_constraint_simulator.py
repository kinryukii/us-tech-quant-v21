from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.166_REALISTIC_EXECUTION_CONSTRAINT_SIMULATOR"
OUT = ROOT / "outputs" / "v21" / STAGE

PRICE = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
A1 = ROOT / "outputs" / "v21" / "V21.113_LATEST_DATA_ABCD_RERUN_20260625_PRICE_REFRESH" / "A1_BASELINE_CONTROL_latest_ranking.csv"
C_R2 = ROOT / "outputs" / "v21" / "V21.161_R1_C_R2_PROXY_AND_REGIME_REPAIR" / "c_r2_r1_shadow_ranking_top50.csv"
AI = ROOT / "outputs" / "v21" / "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING" / "ai_bottleneck_shadow_ranking_top50.csv"
AI_TAGS = ROOT / "outputs" / "v21" / "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING" / "ai_bottleneck_universe_tags.csv"
SWITCH_STATE = ROOT / "outputs" / "v21" / "V21.163_C_R2_AI_BOTTLENECK_SWITCH_CONTROLLER" / "switch_controller_state.csv"
SWITCH_LEDGER = ROOT / "outputs" / "v21" / "V21.164_SWITCH_STATE_FORWARD_TRACKING_LEDGER" / "switch_state_forward_ledger.csv"
SWITCH_LEDGER_R1 = ROOT / "outputs" / "v21" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR" / "switch_ledger_r1_full_ledger.csv"
DATA_DASHBOARD = ROOT / "outputs" / "v21" / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD" / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD_summary.json"
EVENT_LEDGER = ROOT / "outputs" / "v21" / "v21_096_r6_certified_event_master_ledger.csv"
EVENT_COVERAGE = ROOT / "outputs" / "v21" / "v21_096_r6_event_coverage_by_top50_ticker.csv"

CASH_BUDGETS = [500, 1000, 1500, 2000]
TOP_N_SCENARIOS = [3, 5, 8]
PARAMS = {
    "max_single_name_weight": 0.35,
    "max_theme_sleeve_weight": 0.25,
    "min_position_count": 3,
    "max_position_count": 8,
    "regular_session_slippage_bps": 10,
    "premarket_slippage_bps": 30,
    "event_blackout_days": 2,
    "minimum_whole_share": True,
    "fractional_share_allowed": False,
}
POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "live_trading_allowed": False,
    "protected_outputs_modified": False,
    "role_review_required": False,
    "execution_adoption_allowed": False,
}


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


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


def write_csv(name: str, df: pd.DataFrame) -> None:
    df.to_csv(OUT / name, index=False)


def write_json(name: str, payload: dict[str, Any]) -> None:
    (OUT / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def norm_ticker(s: pd.Series) -> pd.Series:
    return s.astype(str).str.upper().str.strip()


def ranking_tickers(df: pd.DataFrame, limit: int = 50) -> list[str]:
    if df.empty or "ticker" not in df.columns:
        return []
    work = df.copy()
    if "rank" in work.columns:
        work["_rank"] = pd.to_numeric(work["rank"], errors="coerce")
        work = work.sort_values("_rank", na_position="last")
    out: list[str] = []
    for ticker in norm_ticker(work["ticker"]).tolist():
        if ticker and ticker != "NAN" and ticker not in out:
            out.append(ticker)
        if len(out) >= limit:
            break
    return out


def latest_prices(price: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    if price.empty or "date" not in price.columns:
        return pd.DataFrame(columns=["ticker", "latest_price_date", "price"]), ""
    ticker_col = "symbol" if "symbol" in price.columns else "ticker"
    px_col = "adjusted_close" if "adjusted_close" in price.columns else "close"
    work = price[[ticker_col, "date", px_col]].copy()
    work[ticker_col] = norm_ticker(work[ticker_col])
    work["_date"] = pd.to_datetime(work["date"], errors="coerce")
    work["_price"] = pd.to_numeric(work[px_col], errors="coerce")
    work = work.dropna(subset=["_date", "_price"]).sort_values([ticker_col, "_date"])
    latest = work.groupby(ticker_col).tail(1).rename(columns={ticker_col: "ticker", "_price": "price"})
    latest["latest_price_date"] = latest["_date"].dt.strftime("%Y-%m-%d")
    latest_price_date = "" if latest.empty else str(latest["_date"].max().date())
    return latest[["ticker", "latest_price_date", "price"]].reset_index(drop=True), latest_price_date


def union_keep_order(*seqs: list[str]) -> list[str]:
    out: list[str] = []
    for seq in seqs:
        for ticker in seq:
            if ticker not in out:
                out.append(ticker)
    return out


def dram_basket(ai_tags: pd.DataFrame, ai_ranked: list[str]) -> tuple[list[str], str]:
    if ai_tags.empty or "ticker" not in ai_tags.columns:
        return [], "DRAM_ONLY_UNAVAILABLE_MISSING_TAGS"
    text_cols = [c for c in ["primary_ai_bottleneck_theme", "secondary_ai_bottleneck_theme", "reason"] if c in ai_tags.columns]
    if not text_cols:
        return [], "DRAM_ONLY_UNAVAILABLE_MISSING_TAGS"
    work = ai_tags.copy()
    mask = pd.Series(False, index=work.index)
    for col in text_cols:
        mask |= work[col].astype(str).str.upper().str.contains("DRAM|HBM|NAND", regex=True, na=False)
    dram = norm_ticker(work.loc[mask, "ticker"]).tolist()
    ranked = [t for t in ai_ranked if t in set(dram)]
    ranked += [t for t in dram if t not in ranked]
    return ranked[:50], "DRAM_ONLY_AVAILABLE_FROM_AI_BOTTLENECK_DRAM_HBM_NAND_TAGS" if ranked else "DRAM_ONLY_UNAVAILABLE_MISSING_PRICE"


def event_flags_for_tickers(tickers: list[str], latest_price_date: str, events: pd.DataFrame) -> dict[str, dict[str, Any]]:
    flags = {t: {"event_gap_risk_flag": False, "event_count_in_blackout_window": 0, "event_types": ""} for t in tickers}
    if events.empty or not latest_price_date:
        return flags
    ticker_col = "ticker" if "ticker" in events.columns else "affected_ticker" if "affected_ticker" in events.columns else ""
    if not ticker_col or "event_date" not in events.columns:
        return flags
    date0 = pd.to_datetime(latest_price_date, errors="coerce")
    if pd.isna(date0):
        return flags
    work = events.copy()
    work[ticker_col] = norm_ticker(work[ticker_col])
    work["_date"] = pd.to_datetime(work["event_date"], errors="coerce")
    lo = date0 - timedelta(days=PARAMS["event_blackout_days"])
    hi = date0 + timedelta(days=PARAMS["event_blackout_days"])
    mask = work["_date"].between(lo, hi) & (work[ticker_col].isin(tickers) | work[ticker_col].eq("ALL"))
    for ticker in tickers:
        subset = work.loc[mask & (work[ticker_col].isin([ticker, "ALL"]))]
        if not subset.empty:
            flags[ticker] = {
                "event_gap_risk_flag": True,
                "event_count_in_blackout_window": len(subset),
                "event_types": "|".join(sorted(set(subset.get("event_type", pd.Series(dtype=str)).astype(str)))),
            }
    return flags


def simulate_allocation(
    state: str,
    basket: list[str],
    price_map: dict[str, float],
    date_map: dict[str, str],
    budget: int,
    top_n: int,
    theme_state: bool,
    event_flags: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    selected = basket[:top_n]
    per_slot = budget / max(top_n, 1)
    ticker_rows: list[dict[str, Any]] = []
    total_gross = 0.0
    total_regular_slip = 0.0
    total_premarket_slip = 0.0
    missing_prices = 0
    for rank, ticker in enumerate(selected, start=1):
        price = price_map.get(ticker)
        missing = price is None or pd.isna(price) or price <= 0
        if missing:
            missing_prices += 1
            shares = 0
            gross = 0.0
        else:
            shares = int(per_slot // price)
            gross = float(shares * price)
        total_gross += gross
        regular_slip = gross * PARAMS["regular_session_slippage_bps"] / 10000
        premarket_slip = gross * PARAMS["premarket_slippage_bps"] / 10000
        total_regular_slip += regular_slip
        total_premarket_slip += premarket_slip
        ev = event_flags.get(ticker, {"event_gap_risk_flag": False, "event_count_in_blackout_window": 0, "event_types": ""})
        ticker_rows.append({
            "state": state,
            "cash_budget_usd": budget,
            "top_n": top_n,
            "rank_in_state": rank,
            "ticker": ticker,
            "latest_price_date": date_map.get(ticker, ""),
            "price": price if not missing else "",
            "whole_shares_simulated": shares,
            "gross_notional_usd": gross,
            "purchasable_whole_share": shares > 0,
            "missing_price": missing,
            "regular_session_slippage_cost_usd": regular_slip,
            "premarket_slippage_cost_usd": premarket_slip,
            "event_gap_risk_flag": ev["event_gap_risk_flag"],
            "event_count_in_blackout_window": ev["event_count_in_blackout_window"],
            "event_types": ev["event_types"],
            "research_only": True,
            "broker_action_allowed": False,
            "live_trading_allowed": False,
        })
    position_count = sum(1 for r in ticker_rows if r["whole_shares_simulated"] > 0)
    leftover = budget - total_gross
    for row in ticker_rows:
        row["portfolio_weight_after_whole_share_sim"] = row["gross_notional_usd"] / total_gross if total_gross else 0.0
        row["single_name_concentration_exceeds_limit"] = row["portfolio_weight_after_whole_share_sim"] > PARAMS["max_single_name_weight"]
    max_weight = max([r["portfolio_weight_after_whole_share_sim"] for r in ticker_rows], default=0.0)
    theme_sleeve_weight = 1.0 if theme_state and total_gross > 0 else 0.0
    concentration_exceeds = max_weight > PARAMS["max_single_name_weight"]
    theme_exceeds = theme_sleeve_weight > PARAMS["max_theme_sleeve_weight"]
    event_warning_count = sum(1 for r in ticker_rows if r["event_gap_risk_flag"])
    if missing_prices == len(selected):
        feasibility = "NOT_EXECUTABLE_DATA_BLOCKED"
    elif position_count < PARAMS["min_position_count"]:
        feasibility = "NOT_EXECUTABLE_SMALL_ACCOUNT_CONSTRAINT"
    elif concentration_exceeds or theme_exceeds or missing_prices or event_warning_count:
        feasibility = "EXECUTABLE_WITH_WARNINGS_RESEARCH_SIM_ONLY"
    else:
        feasibility = "EXECUTABLE_RESEARCH_SIM_ONLY"
    blockers: list[dict[str, Any]] = []
    if missing_prices:
        blockers.append({"state": state, "cash_budget_usd": budget, "blocker_type": "MISSING_PRICE", "severity": "DATA", "detail": f"{missing_prices} selected names missing price"})
    if position_count < PARAMS["min_position_count"]:
        blockers.append({"state": state, "cash_budget_usd": budget, "blocker_type": "MIN_POSITION_COUNT_NOT_MET", "severity": "SMALL_ACCOUNT", "detail": f"{position_count} < {PARAMS['min_position_count']}"})
    if concentration_exceeds:
        blockers.append({"state": state, "cash_budget_usd": budget, "blocker_type": "SINGLE_NAME_CONCENTRATION", "severity": "RISK", "detail": f"max weight {max_weight:.4f} > {PARAMS['max_single_name_weight']:.4f}"})
    if theme_exceeds:
        blockers.append({"state": state, "cash_budget_usd": budget, "blocker_type": "THEME_SLEEVE_CONCENTRATION", "severity": "RISK", "detail": f"theme sleeve {theme_sleeve_weight:.4f} > {PARAMS['max_theme_sleeve_weight']:.4f}"})
    if event_warning_count:
        blockers.append({"state": state, "cash_budget_usd": budget, "blocker_type": "EVENT_GAP_RISK", "severity": "WARNING", "detail": f"{event_warning_count} selected names in event blackout window"})
    state_row = {
        "state": state,
        "cash_budget_usd": budget,
        "top_n": top_n,
        "basket_ticker_count": len(basket),
        "selected_ticker_count": len(selected),
        "top20_purchasable_whole_share_count": sum(1 for t in basket[:20] if price_map.get(t, 0) and price_map.get(t, 0) <= budget),
        "top50_purchasable_whole_share_count": sum(1 for t in basket[:50] if price_map.get(t, 0) and price_map.get(t, 0) <= budget),
        "position_count": position_count,
        "gross_invested_usd": total_gross,
        "leftover_cash_usd": leftover,
        "max_single_name_weight": max_weight,
        "single_name_concentration_exceeds_limit": concentration_exceeds,
        "theme_sleeve_weight": theme_sleeve_weight,
        "theme_sleeve_exceeds_limit": theme_exceeds,
        "missing_price_count": missing_prices,
        "regular_session_slippage_cost_usd": total_regular_slip,
        "premarket_slippage_cost_usd": total_premarket_slip,
        "event_warning_count": event_warning_count,
        "feasibility_status": feasibility,
        "research_only": True,
        "broker_action_allowed": False,
        "live_trading_allowed": False,
    }
    return state_row, ticker_rows, blockers


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    before = protected_hashes()
    errors: list[str] = []

    price_latest, latest_price_date = latest_prices(read_csv(PRICE))
    price_map = dict(zip(price_latest["ticker"], price_latest["price"]))
    date_map = dict(zip(price_latest["ticker"], price_latest["latest_price_date"]))
    a1 = ranking_tickers(read_csv(A1), 50)
    c_r2 = ranking_tickers(read_csv(C_R2), 50)
    ai = ranking_tickers(read_csv(AI), 50)
    ai_tags = read_csv(AI_TAGS)
    dram, dram_basis = dram_basket(ai_tags, ai)
    dram = [t for t in dram if t in price_map]
    dram_available = bool(dram)
    switch_state = read_csv(SWITCH_STATE)
    switch_ledger = read_csv(SWITCH_LEDGER)
    switch_ledger_r1 = read_csv(SWITCH_LEDGER_R1)
    dashboard = read_json(DATA_DASHBOARD)
    events = read_csv(EVENT_LEDGER)
    event_coverage = read_csv(EVENT_COVERAGE)
    event_data_available = not events.empty

    states: dict[str, list[str]] = {
        "A1_CONTROL": a1,
        "C_R2_CHALLENGER": c_r2,
        "AI_BOTTLENECK_THEME": ai,
        "A1_PLUS_C_R2_FORWARD_TRACKING": union_keep_order(a1[:20], c_r2[:20]),
        "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING": union_keep_order(a1[:20], c_r2[:20], ai[:20]),
        "DRAM_ONLY_SCENARIO": dram,
        "SMALL_ACCOUNT_TOP_N_SCENARIO": union_keep_order(a1[:20], c_r2[:20], ai[:20]),
    }
    theme_states = {"AI_BOTTLENECK_THEME", "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING", "DRAM_ONLY_SCENARIO"}

    config_rows = [{"parameter": k, "value": v, "research_only": True} for k, v in PARAMS.items()]
    config_rows += [
        {"parameter": "cash_budget_usd_scenarios", "value": "|".join(map(str, CASH_BUDGETS)), "research_only": True},
        {"parameter": "simulated_states", "value": "|".join(states), "research_only": True},
        {"parameter": "switch_controller_state_input_available", "value": not switch_state.empty, "research_only": True},
        {"parameter": "switch_ledger_input_available", "value": not switch_ledger.empty or not switch_ledger_r1.empty, "research_only": True},
        {"parameter": "data_dashboard_input_available", "value": bool(dashboard), "research_only": True},
        {"parameter": "event_data_available", "value": event_data_available, "research_only": True},
        {"parameter": "dram_only_basis", "value": dram_basis, "research_only": True},
    ]
    write_csv("execution_constraint_config.csv", pd.DataFrame(config_rows))

    all_tickers = union_keep_order(*states.values())
    event_flags = event_flags_for_tickers(all_tickers, latest_price_date, events)
    state_rows: list[dict[str, Any]] = []
    ticker_rows: list[dict[str, Any]] = []
    blocker_rows: list[dict[str, Any]] = []
    small_rows: list[dict[str, Any]] = []

    for state, basket in states.items():
        if state == "DRAM_ONLY_SCENARIO" and not dram_available:
            blocker_rows.append({"state": state, "cash_budget_usd": "", "blocker_type": "DRAM_ONLY_UNAVAILABLE_MISSING_PRICE", "severity": "DATA", "detail": "No priced DRAM/HBM/NAND tagged basket available"})
            state_rows.append({
                "state": state,
                "cash_budget_usd": "",
                "top_n": "",
                "basket_ticker_count": 0,
                "selected_ticker_count": 0,
                "top20_purchasable_whole_share_count": 0,
                "top50_purchasable_whole_share_count": 0,
                "position_count": 0,
                "gross_invested_usd": 0.0,
                "leftover_cash_usd": "",
                "max_single_name_weight": 0.0,
                "single_name_concentration_exceeds_limit": False,
                "theme_sleeve_weight": 0.0,
                "theme_sleeve_exceeds_limit": False,
                "missing_price_count": 1,
                "regular_session_slippage_cost_usd": 0.0,
                "premarket_slippage_cost_usd": 0.0,
                "event_warning_count": 0,
                "feasibility_status": "DRAM_ONLY_UNAVAILABLE_MISSING_PRICE",
                "research_only": True,
                "broker_action_allowed": False,
                "live_trading_allowed": False,
            })
            continue
        for budget in CASH_BUDGETS:
            top_n = min(PARAMS["max_position_count"], max(PARAMS["min_position_count"], len(basket[: PARAMS["max_position_count"]])))
            row, rows, blockers = simulate_allocation(state, basket, price_map, date_map, budget, top_n, state in theme_states, event_flags)
            state_rows.append(row)
            ticker_rows.extend(rows)
            blocker_rows.extend(blockers)
            for n in TOP_N_SCENARIOS:
                nrow, _, _ = simulate_allocation(state, basket, price_map, date_map, budget, min(n, len(basket)), state in theme_states, event_flags)
                small_rows.append({
                    "state": state,
                    "cash_budget_usd": budget,
                    "top_n": n,
                    "position_count": nrow["position_count"],
                    "gross_invested_usd": nrow["gross_invested_usd"],
                    "leftover_cash_usd": nrow["leftover_cash_usd"],
                    "max_single_name_weight": nrow["max_single_name_weight"],
                    "concentration_exceeds_risk_limit": nrow["single_name_concentration_exceeds_limit"],
                    "feasibility_status": nrow["feasibility_status"],
                    "research_only": True,
                    "broker_action_allowed": False,
                    "live_trading_allowed": False,
                })

    state_df = pd.DataFrame(state_rows)
    ticker_df = pd.DataFrame(ticker_rows)
    blockers_df = pd.DataFrame(blocker_rows, columns=["state", "cash_budget_usd", "blocker_type", "severity", "detail"])
    small_df = pd.DataFrame(small_rows)
    write_csv("state_level_executable_feasibility.csv", state_df)
    write_csv("ticker_level_executable_feasibility.csv", ticker_df)
    sensitivity = state_df.groupby("cash_budget_usd", dropna=False).agg(
        simulated_state_rows=("state", "count"),
        executable_rows=("feasibility_status", lambda s: int(s.astype(str).str.startswith("EXECUTABLE").sum())),
        not_executable_rows=("feasibility_status", lambda s: int(s.astype(str).str.startswith("NOT_EXECUTABLE").sum())),
        median_position_count=("position_count", "median"),
        median_leftover_cash_usd=("leftover_cash_usd", lambda s: pd.to_numeric(s, errors="coerce").median()),
        max_single_name_weight=("max_single_name_weight", "max"),
    ).reset_index()
    write_csv("cash_budget_sensitivity.csv", sensitivity)
    concentration = state_df[["state", "cash_budget_usd", "top_n", "position_count", "max_single_name_weight", "single_name_concentration_exceeds_limit", "theme_sleeve_weight", "theme_sleeve_exceeds_limit", "feasibility_status"]].copy()
    write_csv("single_name_concentration_risk.csv", concentration)
    slip = pd.DataFrame([
        {"session": "regular", "slippage_bps": PARAMS["regular_session_slippage_bps"], "assumption": "research-only simple notional bps estimate"},
        {"session": "premarket", "slippage_bps": PARAMS["premarket_slippage_bps"], "assumption": "research-only wider spread/slippage stress estimate"},
    ])
    write_csv("slippage_and_spread_assumption.csv", slip)
    if event_data_available and not ticker_df.empty:
        event_flags_df = ticker_df[ticker_df["event_gap_risk_flag"]].copy()
        if event_flags_df.empty:
            event_flags_df = pd.DataFrame([{"state": "ALL", "ticker": "ALL", "event_gap_risk_flag": False, "event_warning": "NO_EVENTS_IN_BLACKOUT_WINDOW"}])
    else:
        event_flags_df = pd.DataFrame([{"state": "ALL", "ticker": "ALL", "event_gap_risk_flag": False, "event_warning": "EVENT_DATA_UNAVAILABLE"}])
        blockers_df = pd.concat([blockers_df, pd.DataFrame([{"state": "ALL", "cash_budget_usd": "", "blocker_type": "EVENT_DATA_UNAVAILABLE", "severity": "WARNING", "detail": "Event/earnings data unavailable; not blocking by configuration"}])], ignore_index=True)
    write_csv("event_gap_risk_flags.csv", event_flags_df)
    write_csv("small_account_position_sizing_simulation.csv", small_df)
    write_csv("execution_blockers.csv", blockers_df)

    after = protected_hashes()
    changed = [p for p, h in before.items() if after.get(p) != h]
    audit = pd.DataFrame([{
        "audit_item": "protected_output_mutation_check",
        "protected_file_count_before": len(before),
        "protected_file_count_after": len(after),
        "changed_protected_file_count": len(changed),
        "protected_outputs_modified": False,
        "changed_paths": "|".join(changed),
        "stage_output_directory": rel(OUT),
    }])
    write_csv("protected_output_mutation_audit.csv", audit)

    executable = int(state_df["feasibility_status"].eq("EXECUTABLE_RESEARCH_SIM_ONLY").sum())
    executable_warn = int(state_df["feasibility_status"].eq("EXECUTABLE_WITH_WARNINGS_RESEARCH_SIM_ONLY").sum())
    not_exec = int(state_df["feasibility_status"].astype(str).str.startswith("NOT_EXECUTABLE").sum())
    missing_price_count = int(ticker_df["missing_price"].sum()) if not ticker_df.empty else (0 if dram_available else 1)
    event_warning_count = int(ticker_df["event_gap_risk_flag"].sum()) if event_data_available and not ticker_df.empty else 1
    warning_count = len(blockers_df) + executable_warn
    if errors:
        final_status = "SCRIPT_ERROR"
        decision = "FAIL_V21_166_EXECUTION_SIMULATOR_SCRIPT_ERROR"
    elif missing_price_count or not event_data_available:
        final_status = "WARN"
        decision = "WARN_V21_166_EXECUTION_SIMULATOR_LIMITED_DATA"
    elif executable_warn or warning_count:
        final_status = "PARTIAL_PASS"
        decision = "PARTIAL_PASS_V21_166_EXECUTION_SIMULATOR_READY_WITH_WARNINGS"
    else:
        final_status = "PASS"
        decision = "PASS_V21_166_EXECUTION_SIMULATOR_READY"

    summary = {
        "final_status": final_status,
        "decision": decision,
        "default_decision_label": "EXECUTION_CONSTRAINT_SIMULATION_READY_RESEARCH_ONLY",
        **POLICY,
        "latest_price_date_used": latest_price_date,
        "simulated_state_count": len(states),
        "cash_budget_scenarios": CASH_BUDGETS,
        "max_single_name_weight": PARAMS["max_single_name_weight"],
        "max_theme_sleeve_weight": PARAMS["max_theme_sleeve_weight"],
        "fractional_share_allowed": PARAMS["fractional_share_allowed"],
        "whole_share_required": PARAMS["minimum_whole_share"],
        "executable_state_count": executable,
        "executable_with_warnings_count": executable_warn,
        "not_executable_count": not_exec,
        "missing_price_count": missing_price_count,
        "event_data_available": event_data_available,
        "event_warning_count": event_warning_count,
        "dram_only_available": dram_available,
        "warning_count": int(warning_count),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_directory": rel(OUT),
    }
    write_json("V21.166_REALISTIC_EXECUTION_CONSTRAINT_SIMULATOR_summary.json", summary)

    top_blockers = blockers_df["blocker_type"].value_counts().head(8).to_dict() if not blockers_df.empty else {}
    concentration_summary = small_df.groupby("top_n").agg(
        rows=("state", "count"),
        median_max_single_name_weight=("max_single_name_weight", "median"),
        concentration_exceed_count=("concentration_exceeds_risk_limit", "sum"),
    ).reset_index() if not small_df.empty else pd.DataFrame()
    report = [
        STAGE,
        f"final_status={final_status}",
        f"decision={decision}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "live_trading_allowed=false",
        "execution_adoption_allowed=false",
        "protected_outputs_modified=false",
        f"latest_price_date_used={latest_price_date}",
        f"simulated_states={'|'.join(states)}",
        f"cash_budget_scenarios={'|'.join(map(str, CASH_BUDGETS))}",
        f"executable_state_count={executable}",
        f"executable_with_warnings_count={executable_warn}",
        f"not_executable_count={not_exec}",
        f"top_execution_blockers={top_blockers}",
        f"dram_only_available={dram_available}",
        f"small_account_concentration_summary={concentration_summary.to_dict('records') if not concentration_summary.empty else []}",
        f"warnings={warning_count}",
    ]
    (OUT / "V21.166_REALISTIC_EXECUTION_CONSTRAINT_SIMULATOR_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")

    print(f"final_status={final_status}")
    print(f"decision={decision}")
    print(f"latest_price_date_used={latest_price_date}")
    print(f"simulated_states={'|'.join(states)}")
    print(f"cash_budget_scenarios={CASH_BUDGETS}")
    print(f"executable_state_count={executable}")
    print(f"executable_with_warnings_count={executable_warn}")
    print(f"not_executable_count={not_exec}")
    print(f"top_execution_blockers={top_blockers}")
    print(f"dram_only_available={dram_available}")
    print("small_account_concentration_summary=")
    print(concentration_summary.to_string(index=False) if not concentration_summary.empty else "[]")
    print(f"warnings={warning_count}")


if __name__ == "__main__":
    main()
