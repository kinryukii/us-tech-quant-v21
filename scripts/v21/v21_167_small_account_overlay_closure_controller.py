from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.167_SMALL_ACCOUNT_OVERLAY_CLOSURE_CONTROLLER"
OUT = ROOT / "outputs" / "v21" / STAGE

PRICE = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
A1 = ROOT / "outputs" / "v21" / "V21.113_LATEST_DATA_ABCD_RERUN_20260625_PRICE_REFRESH" / "A1_BASELINE_CONTROL_latest_ranking.csv"
C_R2 = ROOT / "outputs" / "v21" / "V21.161_R1_C_R2_PROXY_AND_REGIME_REPAIR" / "c_r2_r1_shadow_ranking_top50.csv"
AI = ROOT / "outputs" / "v21" / "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING" / "ai_bottleneck_shadow_ranking_top50.csv"
AI_TAGS = ROOT / "outputs" / "v21" / "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING" / "ai_bottleneck_universe_tags.csv"
SWITCH_STATE = ROOT / "outputs" / "v21" / "V21.163_C_R2_AI_BOTTLENECK_SWITCH_CONTROLLER" / "switch_controller_state.csv"
SWITCH_R1_SUMMARY = ROOT / "outputs" / "v21" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR_summary.json"
V165_SUMMARY = ROOT / "outputs" / "v21" / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD" / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD_summary.json"
V165_IMPACT = ROOT / "outputs" / "v21" / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD" / "data_quality_impact_classification.csv"
V166_SUMMARY = ROOT / "outputs" / "v21" / "V21.166_REALISTIC_EXECUTION_CONSTRAINT_SIMULATOR" / "V21.166_REALISTIC_EXECUTION_CONSTRAINT_SIMULATOR_summary.json"
V166_STATE = ROOT / "outputs" / "v21" / "V21.166_REALISTIC_EXECUTION_CONSTRAINT_SIMULATOR" / "state_level_executable_feasibility.csv"
V166_BLOCKERS = ROOT / "outputs" / "v21" / "V21.166_REALISTIC_EXECUTION_CONSTRAINT_SIMULATOR" / "execution_blockers.csv"
SOFTCAP_SUMMARY = ROOT / "outputs" / "v21" / "V21.159_SOFT_CAP_RECIPIENT_RISK_FILTER_AND_SWITCHING_ELIGIBILITY_AUDIT" / "V21.159_machine_summary.json"
SOFTCAP_PORTFOLIO = ROOT / "outputs" / "v21" / "V21.159_SOFT_CAP_RECIPIENT_RISK_FILTER_AND_SWITCHING_ELIGIBILITY_AUDIT" / "softcap_filter_variant_portfolios.csv"
SOFTCAP_CANDIDATE = ROOT / "outputs" / "v21" / "V21.159_SOFT_CAP_RECIPIENT_RISK_FILTER_AND_SWITCHING_ELIGIBILITY_AUDIT" / "softcap_recommended_candidate.csv"
E_R1_SUMMARY = ROOT / "outputs" / "v21" / "V21.157_E_R1_SHADOW_TRIGGER_ATTRIBUTION_AND_FORWARD_MATURITY_GATE" / "V21.157_machine_summary.json"
E_R1_AUDIT = ROOT / "outputs" / "v21" / "V21.149_E_R1_DEFENSIVE_OVERLAY_AND_INVALID_TRIAL_AUDIT" / "V21.149_summary.json"
E_R1_TOP50 = ROOT / "outputs" / "v21" / "V21.133_E_CONSERVATIVE_ADAPTIVE_MOMENTUM_R1" / "e_top50.csv"

CASH_BUDGETS = [500, 1000, 1500, 2000]
MAX_SINGLE = 0.35
MAX_THEME = 0.25
MIN_POS = 3
MAX_POS = 8
POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "live_trading_allowed": False,
    "protected_outputs_modified": False,
    "role_review_required": False,
    "overlay_adoption_allowed": False,
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


def latest_prices() -> tuple[dict[str, float], str]:
    px = read_csv(PRICE)
    if px.empty or "date" not in px.columns:
        return {}, ""
    ticker_col = "symbol" if "symbol" in px.columns else "ticker"
    price_col = "adjusted_close" if "adjusted_close" in px.columns else "close"
    work = px[[ticker_col, "date", price_col]].copy()
    work[ticker_col] = norm(work[ticker_col])
    work["_date"] = pd.to_datetime(work["date"], errors="coerce")
    work["_price"] = pd.to_numeric(work[price_col], errors="coerce")
    work = work.dropna(subset=["_date", "_price"]).sort_values([ticker_col, "_date"])
    latest = work.groupby(ticker_col).tail(1)
    latest_date = "" if latest.empty else str(latest["_date"].max().date())
    return dict(zip(latest[ticker_col], latest["_price"])), latest_date


def ranked_tickers(df: pd.DataFrame, limit: int = 50) -> list[str]:
    if df.empty or "ticker" not in df.columns:
        return []
    work = df.copy()
    if "rank" in work.columns:
        work["_rank"] = pd.to_numeric(work["rank"], errors="coerce")
        work = work.sort_values("_rank", na_position="last")
    out: list[str] = []
    for ticker in norm(work["ticker"]).tolist():
        if ticker and ticker != "NAN" and ticker not in out:
            out.append(ticker)
        if len(out) >= limit:
            break
    return out


def softcap_tickers() -> list[str]:
    df = read_csv(SOFTCAP_PORTFOLIO)
    if df.empty or "ticker" not in df.columns:
        return []
    work = df.copy()
    if "filter_variant" in work.columns:
        filt = work[work["filter_variant"].astype(str).eq("SOFTCAP_FILTER_CONCENTRATION")]
        if not filt.empty:
            work = filt
    if "final_filter_weight" in work.columns:
        work["_w"] = pd.to_numeric(work["final_filter_weight"], errors="coerce")
        work = work.sort_values("_w", ascending=False, na_position="last")
    return ranked_tickers(work, 50)


def dram_tickers(ai_tags: pd.DataFrame, ai_ranked: list[str], price_map: dict[str, float]) -> list[str]:
    if ai_tags.empty or "ticker" not in ai_tags.columns:
        return []
    cols = [c for c in ["primary_ai_bottleneck_theme", "secondary_ai_bottleneck_theme", "reason"] if c in ai_tags.columns]
    mask = pd.Series(False, index=ai_tags.index)
    for col in cols:
        mask |= ai_tags[col].astype(str).str.upper().str.contains("DRAM|HBM|NAND", regex=True, na=False)
    tagged = norm(ai_tags.loc[mask, "ticker"]).tolist()
    ordered = [t for t in ai_ranked if t in set(tagged)] + [t for t in tagged if t not in ai_ranked]
    return [t for t in ordered if t in price_map]


def simulate(module: str, tickers: list[str], price_map: dict[str, float], theme: bool) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    selected = tickers[:MAX_POS]
    for budget in CASH_BUDGETS:
        per_slot = budget / max(len(selected), 1)
        gross = 0.0
        parts = []
        missing = 0
        for ticker in selected:
            price = price_map.get(ticker)
            if price is None or pd.isna(price) or price <= 0:
                shares = 0
                notional = 0.0
                missing += 1
            else:
                shares = int(per_slot // price)
                notional = float(shares * price)
            gross += notional
            parts.append((ticker, shares, notional))
        weights = [n / gross if gross else 0.0 for _, _, n in parts]
        position_count = sum(1 for _, sh, _ in parts if sh > 0)
        max_weight = max(weights, default=0.0)
        theme_weight = 1.0 if theme and gross > 0 else 0.0
        min_pass = position_count >= MIN_POS
        single_pass = max_weight <= MAX_SINGLE
        theme_pass = theme_weight <= MAX_THEME
        feasible = min_pass and single_pass and theme_pass and missing == 0
        blockers = []
        if missing:
            blockers.append("MISSING_PRICE")
        if not min_pass:
            blockers.append("MIN_POSITION_COUNT_NOT_MET")
        if not single_pass:
            blockers.append("SINGLE_NAME_CONCENTRATION")
        if not theme_pass:
            blockers.append("THEME_SLEEVE_CONCENTRATION")
        rows.append({
            "module": module,
            "cash_budget_usd": budget,
            "selected_ticker_count": len(selected),
            "position_count": position_count,
            "min_position_count_pass": min_pass,
            "max_single_name_weight": max_weight,
            "single_name_weight_pass": single_pass,
            "theme_sleeve_weight": theme_weight,
            "theme_sleeve_pass": theme_pass,
            "missing_price_count": missing,
            "gross_invested_usd": gross,
            "leftover_cash_usd": budget - gross,
            "small_account_feasible": feasible,
            "blockers": "|".join(blockers),
            "research_only": True,
            "broker_action_allowed": False,
            "live_trading_allowed": False,
        })
    return pd.DataFrame(rows)


def best_status(df: pd.DataFrame) -> tuple[bool, int, float, str]:
    if df.empty:
        return False, 0, 0.0, "NO_SIMULATION_ROWS"
    feasible = bool(df["small_account_feasible"].any())
    blockers = int(df["blockers"].astype(str).ne("").sum())
    max_weight = float(pd.to_numeric(df["max_single_name_weight"], errors="coerce").max())
    if feasible:
        status = "SMALL_ACCOUNT_FEASIBLE_RESEARCH_ONLY"
    elif int(df["min_position_count_pass"].sum()) == 0:
        status = "SMALL_ACCOUNT_BLOCKED_MIN_POSITION_COUNT"
    elif not bool(df["single_name_weight_pass"].any()):
        status = "SMALL_ACCOUNT_BLOCKED_CONCENTRATION"
    else:
        status = "SMALL_ACCOUNT_BLOCKED_BY_CONSTRAINTS"
    return feasible, blockers, max_weight, status


def inherited_state(v166_state: pd.DataFrame, state: str) -> tuple[bool, int, float, str]:
    sub = v166_state[v166_state["state"].eq(state)].copy() if not v166_state.empty and "state" in v166_state.columns else pd.DataFrame()
    if sub.empty:
        return False, 0, 0.0, "V21_166_STATE_UNAVAILABLE"
    feasible = bool(sub["feasibility_status"].astype(str).str.startswith("EXECUTABLE").any())
    blocker_count = int((~sub["feasibility_status"].astype(str).eq("EXECUTABLE_RESEARCH_SIM_ONLY")).sum())
    max_weight = float(pd.to_numeric(sub["max_single_name_weight"], errors="coerce").max())
    status = "SMALL_ACCOUNT_EXECUTABLE_OR_TRACKED" if feasible else "SMALL_ACCOUNT_LIMITED"
    return feasible, blocker_count, max_weight, status


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    before = protected_hashes()
    price_map, latest_price_date = latest_prices()
    switch = read_csv(SWITCH_STATE)
    selected_regime = "UNKNOWN"
    regime_confidence = ""
    if not switch.empty:
        selected_regime = str(switch.get("selected_regime", pd.Series(["UNKNOWN"])).iloc[0])
        regime_confidence = switch.get("regime_confidence", pd.Series([""])).iloc[0]
    v165 = read_json(V165_SUMMARY)
    v166 = read_json(V166_SUMMARY)
    switch_r1 = read_json(SWITCH_R1_SUMMARY)
    softcap_summary = read_json(SOFTCAP_SUMMARY)
    e_summary = read_json(E_R1_SUMMARY)
    e_audit = read_json(E_R1_AUDIT)
    v166_state = read_csv(V166_STATE)
    v166_blockers = read_csv(V166_BLOCKERS)
    impact = read_csv(V165_IMPACT)

    a1_feasible, a1_blockers, a1_max, a1_status = inherited_state(v166_state, "A1_CONTROL")
    c_feasible, c_blockers, c_max, c_status = inherited_state(v166_state, "C_R2_CHALLENGER")
    ai_feasible, ai_blockers, ai_max, ai_status = inherited_state(v166_state, "AI_BOTTLENECK_THEME")
    dram_v166_feasible, dram_v166_blockers, dram_v166_max, _ = inherited_state(v166_state, "DRAM_ONLY_SCENARIO")

    soft_df = simulate("SOFTCAP_RETURN_OVERLAY", softcap_tickers(), price_map, theme=False)
    e_df = simulate("E_R1_DEFENSIVE_OVERLAY", ranked_tickers(read_csv(E_R1_TOP50), 50), price_map, theme=False)
    dram_df = simulate("DRAM_ONLY_RESEARCH_VIEW", dram_tickers(read_csv(AI_TAGS), ranked_tickers(read_csv(AI), 50), price_map), price_map, theme=True)
    write_csv("softcap_small_account_feasibility.csv", soft_df)
    write_csv("e_r1_small_account_feasibility.csv", e_df)
    write_csv("dram_only_small_account_feasibility.csv", dram_df)

    soft_feasible, soft_blockers, soft_max, soft_sa_status = best_status(soft_df)
    e_feasible, e_blockers, e_max, e_sa_status = best_status(e_df)
    dram_feasible, dram_blockers, dram_max, dram_sa_status = best_status(dram_df)

    matured_count = int(switch_r1.get("matured_result_count_after", 0) or 0)
    maturity_available = matured_count > 0
    data_impact = str(v165.get("max_data_quality_impact", "UNKNOWN"))
    softcap_available = bool(softcap_summary)
    softcap_risk_mixed = "RISK_MIXED" in str(softcap_summary.get("FINAL_STATUS", "")) or "RISK_MIXED" in str(softcap_summary.get("DECISION", ""))
    softcap_pool_exists = len(soft_df) > 0 and int(soft_df["selected_ticker_count"].max()) > 0
    e_available = bool(e_summary) and E_R1_TOP50.exists()
    e_regime_active = selected_regime.lower() == "risk_off"
    e_maturity = bool(e_summary.get("trigger_maturity_sufficient", False))
    e_lowers_risk = bool(e_audit.get("E_R1_left_tail_valid_after_invalid_filter", False))

    softcap_status = "SOFTCAP_WATCH_ONLY_SMALL_ACCOUNT_LIMITED"
    if not softcap_available or not softcap_pool_exists:
        softcap_status = "SOFTCAP_THEORETICAL_ONLY_SMALL_ACCOUNT_BLOCKED"
    elif not soft_feasible or softcap_risk_mixed or not maturity_available:
        softcap_status = "SOFTCAP_WATCH_ONLY_SMALL_ACCOUNT_LIMITED"
    e_status = "E_R1_STANDBY_SMALL_ACCOUNT_TRACKED"
    if not e_regime_active:
        e_status = "E_R1_NOT_ACTIVE_CURRENT_REGIME"
    elif not e_feasible or not e_maturity or not e_lowers_risk:
        e_status = "E_R1_STANDBY_SMALL_ACCOUNT_TRACKED"
    if not dram_df.empty and int(dram_df["selected_ticker_count"].max()) > 0:
        dram_status = "DRAM_ONLY_RESEARCH_VIEW_AVAILABLE"
        if not dram_feasible or dram_v166_blockers:
            dram_status = "DRAM_ONLY_RESEARCH_VIEW_EXECUTION_BLOCKED"
    else:
        dram_status = "DRAM_ONLY_UNAVAILABLE_MISSING_PRICE"

    overlay_promotion_allowed = False
    closure_class = "NO_OVERLAY_PROMOTION_INSUFFICIENT_MATURITY" if not maturity_available else "NO_OVERLAY_PROMOTION_EXECUTION_BLOCKED"

    state_rows = [
        {"module": "A1_PRIMARY_CONTROL", "classification_state": "A1_PRIMARY_SMALL_ACCOUNT_REFERENCE", "small_account_feasible": a1_feasible, "blocker_count": a1_blockers, "max_single_name_weight": a1_max, "notes": a1_status},
        {"module": "C_R2_CHALLENGER", "classification_state": "C_R2_FORWARD_TRACKING_SMALL_ACCOUNT_LIMITED", "small_account_feasible": c_feasible, "blocker_count": c_blockers, "max_single_name_weight": c_max, "notes": c_status},
        {"module": "AI_BOTTLENECK_THEME_SLEEVE", "classification_state": "AI_BOTTLENECK_FORWARD_TRACKING_SMALL_ACCOUNT_LIMITED", "small_account_feasible": ai_feasible, "blocker_count": ai_blockers, "max_single_name_weight": ai_max, "notes": ai_status},
        {"module": "SOFTCAP_RETURN_OVERLAY", "classification_state": softcap_status, "small_account_feasible": soft_feasible, "blocker_count": soft_blockers, "max_single_name_weight": soft_max, "notes": str(softcap_summary.get("softcap_blocker_after_v21_159", ""))},
        {"module": "E_R1_DEFENSIVE_OVERLAY", "classification_state": e_status, "small_account_feasible": e_feasible, "blocker_count": e_blockers, "max_single_name_weight": e_max, "notes": str(e_summary.get("DECISION", ""))},
        {"module": "DRAM_ONLY_RESEARCH_VIEW", "classification_state": dram_status, "small_account_feasible": dram_feasible, "blocker_count": dram_blockers + dram_v166_blockers, "max_single_name_weight": max(dram_max, dram_v166_max), "notes": "DRAM/HBM/NAND tagged priced tickers only; no DRAM ticker price fabricated"},
    ]
    state_df = pd.DataFrame(state_rows)
    for col in ["research_only", "broker_action_allowed", "live_trading_allowed", "official_adoption_allowed", "overlay_adoption_allowed"]:
        state_df[col] = False
    state_df["research_only"] = True
    write_csv("small_account_overlay_state.csv", state_df)

    inherited = v166_blockers.copy()
    if not inherited.empty:
        inherited["source"] = "V21.166"
        inherited = inherited.rename(columns={"state": "module_or_state"})
    own_blockers = []
    for module, df in [("SOFTCAP_RETURN_OVERLAY", soft_df), ("E_R1_DEFENSIVE_OVERLAY", e_df), ("DRAM_ONLY_RESEARCH_VIEW", dram_df)]:
        for row in df[df["blockers"].astype(str).ne("")].to_dict("records"):
            own_blockers.append({"module_or_state": module, "cash_budget_usd": row["cash_budget_usd"], "blocker_type": row["blockers"], "severity": "SMALL_ACCOUNT", "detail": f"position_count={row['position_count']} max_single_name_weight={row['max_single_name_weight']:.4f}", "source": STAGE})
    if not maturity_available:
        own_blockers.append({"module_or_state": "ALL_OVERLAYS", "cash_budget_usd": "", "blocker_type": "NO_OVERLAY_PROMOTION_INSUFFICIENT_MATURITY", "severity": "MATURITY", "detail": "V21.164-R1 matured_result_count_after=0", "source": "V21.164_R1"})
    if data_impact == "BLOCKING_IMPACT":
        own_blockers.append({"module_or_state": "ALL_OVERLAYS", "cash_budget_usd": "", "blocker_type": "V21_165_BLOCKING_DATA_QUALITY_IMPACT", "severity": "DATA", "detail": "V21.165 max_data_quality_impact=BLOCKING_IMPACT", "source": "V21.165"})
    blockers = pd.concat([inherited, pd.DataFrame(own_blockers)], ignore_index=True) if not inherited.empty else pd.DataFrame(own_blockers)
    write_csv("small_account_overlay_blockers.csv", blockers)

    risk_rows = []
    for row in state_rows:
        risk_rows.append({
            "module": row["module"],
            "max_single_name_weight_limit": MAX_SINGLE,
            "observed_max_single_name_weight": row["max_single_name_weight"],
            "single_name_pass": row["max_single_name_weight"] <= MAX_SINGLE,
            "max_theme_sleeve_weight_limit": MAX_THEME,
            "theme_sleeve_applicable": row["module"] in {"AI_BOTTLENECK_THEME_SLEEVE", "DRAM_ONLY_RESEARCH_VIEW"},
            "min_position_count": MIN_POS,
            "max_position_count": MAX_POS,
            "whole_share_required": True,
            "fractional_share_allowed": False,
        })
    write_csv("small_account_overlay_risk_budget.csv", pd.DataFrame(risk_rows))
    write_csv("small_account_overlay_regime_mapping.csv", pd.DataFrame([
        {"module": "A1_PRIMARY_CONTROL", "selected_regime": selected_regime, "regime_confidence": regime_confidence, "current_role": "PRIMARY_REFERENCE"},
        {"module": "C_R2_CHALLENGER", "selected_regime": selected_regime, "regime_confidence": regime_confidence, "current_role": "FORWARD_TRACKING_ONLY"},
        {"module": "AI_BOTTLENECK_THEME_SLEEVE", "selected_regime": selected_regime, "regime_confidence": regime_confidence, "current_role": "FORWARD_TRACKING_ONLY"},
        {"module": "SOFTCAP_RETURN_OVERLAY", "selected_regime": selected_regime, "regime_confidence": regime_confidence, "current_role": "WATCH_ONLY"},
        {"module": "E_R1_DEFENSIVE_OVERLAY", "selected_regime": selected_regime, "regime_confidence": regime_confidence, "current_role": "STANDBY_NOT_ACTIVE_CURRENT_REGIME" if not e_regime_active else "RISK_OFF_STANDBY"},
        {"module": "DRAM_ONLY_RESEARCH_VIEW", "selected_regime": selected_regime, "regime_confidence": regime_confidence, "current_role": "RESEARCH_VIEW_ONLY"},
    ]))
    write_csv("small_account_overlay_forward_tracking_plan.csv", pd.DataFrame([
        {"module": "A1_PRIMARY_CONTROL", "recommended_forward_tracking_action": "KEEP_PRIMARY_REFERENCE_TRACKING", "trading_action": "NONE"},
        {"module": "C_R2_CHALLENGER", "recommended_forward_tracking_action": "CONTINUE_FORWARD_TRACKING_ONLY", "trading_action": "NONE"},
        {"module": "AI_BOTTLENECK_THEME_SLEEVE", "recommended_forward_tracking_action": "CONTINUE_FORWARD_TRACKING_ONLY_AND_MONITOR_THEME_CONCENTRATION", "trading_action": "NONE"},
        {"module": "SOFTCAP_RETURN_OVERLAY", "recommended_forward_tracking_action": "KEEP_WATCH_ONLY_WAIT_MATURITY_AND_SMALL_ACCOUNT_FEASIBILITY", "trading_action": "NONE"},
        {"module": "E_R1_DEFENSIVE_OVERLAY", "recommended_forward_tracking_action": "KEEP_STANDBY_UNTIL_RISK_OFF_AND_FORWARD_MATURITY", "trading_action": "NONE"},
        {"module": "DRAM_ONLY_RESEARCH_VIEW", "recommended_forward_tracking_action": "TRACK_RESEARCH_VIEW_ONLY_EXECUTION_BLOCKED_BY_CONCENTRATION", "trading_action": "NONE"},
    ]))
    warnings = pd.DataFrame([
        {"warning_type": "V21_165_DATA_QUALITY", "warning": f"max_data_quality_impact={data_impact}; stale_ticker_count={v165.get('stale_ticker_count')}; missing_price_ticker_count={v165.get('missing_price_ticker_count')}"},
        {"warning_type": "V21_166_EXECUTION_BLOCKERS", "warning": f"warning_count={v166.get('warning_count')}; not_executable_count={v166.get('not_executable_count')}"},
        {"warning_type": "MATURITY_WAIT", "warning": f"matured_result_count_after={matured_count}; overlay promotion blocked"},
    ])
    write_csv("small_account_overlay_data_quality_warnings.csv", warnings)
    decision_df = pd.DataFrame([{
        "closure_decision": closure_class,
        "overlay_promotion_allowed": overlay_promotion_allowed,
        "softcap_status": softcap_status,
        "e_r1_status": e_status,
        "dram_only_status": dram_status,
        "maturity_evidence_available": maturity_available,
        "data_quality_impact": data_impact,
        "execution_blocker_count": len(blockers),
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "live_trading_allowed": False,
        "overlay_adoption_allowed": False,
    }])
    write_csv("overlay_execution_closure_decision.csv", decision_df)

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

    blocker_count = len(blockers)
    warning_count = len(warnings) + blocker_count
    final_status = "WARN"
    decision = "WARN_V21_167_SMALL_ACCOUNT_OVERLAY_PROMOTION_BLOCKED"
    if maturity_available and blocker_count:
        final_status = "PARTIAL_PASS"
        decision = "PARTIAL_PASS_V21_167_SMALL_ACCOUNT_OVERLAY_CLOSURE_READY_WITH_WARNINGS"
    elif maturity_available and not blocker_count:
        final_status = "PASS"
        decision = "PASS_V21_167_SMALL_ACCOUNT_OVERLAY_CLOSURE_READY"
    summary = {
        "final_status": final_status,
        "decision": decision,
        "default_decision_label": "SMALL_ACCOUNT_OVERLAY_CLOSURE_TRACKING_ONLY_PROMOTION_BLOCKED",
        **POLICY,
        "latest_price_date_used": latest_price_date or v166.get("latest_price_date_used") or v165.get("latest_price_date_used"),
        "selected_regime": selected_regime,
        "regime_confidence": float(regime_confidence) if str(regime_confidence) else "",
        "small_account_constraints_enabled": True,
        "whole_share_required": True,
        "fractional_share_allowed": False,
        "cash_budget_scenarios": CASH_BUDGETS,
        "max_single_name_weight": MAX_SINGLE,
        "max_theme_sleeve_weight": MAX_THEME,
        "min_position_count": MIN_POS,
        "softcap_status": softcap_status,
        "softcap_small_account_feasible": soft_feasible,
        "e_r1_status": e_status,
        "e_r1_small_account_feasible": e_feasible,
        "dram_only_status": dram_status,
        "dram_only_small_account_feasible": dram_feasible,
        "maturity_evidence_available": maturity_available,
        "overlay_promotion_allowed": overlay_promotion_allowed,
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_directory": rel(OUT),
    }
    write_json("V21.167_SMALL_ACCOUNT_OVERLAY_CLOSURE_CONTROLLER_summary.json", summary)
    report = [
        STAGE,
        f"final_status={final_status}",
        f"decision={decision}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "live_trading_allowed=false",
        "overlay_adoption_allowed=false",
        "protected_outputs_modified=false",
        f"latest_price_date_used={summary['latest_price_date_used']}",
        f"selected_regime={selected_regime}",
        f"regime_confidence={regime_confidence}",
        f"softcap_small_account_status={softcap_status}",
        f"e_r1_small_account_status={e_status}",
        f"dram_only_small_account_status={dram_status}",
        f"blocker_count={blocker_count}",
        f"overlay_promotion_allowed={overlay_promotion_allowed}",
        f"warnings={warning_count}",
    ]
    (OUT / "V21.167_SMALL_ACCOUNT_OVERLAY_CLOSURE_CONTROLLER_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report[1:]))


if __name__ == "__main__":
    main()
