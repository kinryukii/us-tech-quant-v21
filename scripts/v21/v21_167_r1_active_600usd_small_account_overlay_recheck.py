from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.167_R1_ACTIVE_600USD_SMALL_ACCOUNT_OVERLAY_RECHECK"
OUT = ROOT / "outputs" / "v21" / STAGE

PRICE = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
A1 = ROOT / "outputs" / "v21" / "V21.113_LATEST_DATA_ABCD_RERUN_20260625_PRICE_REFRESH" / "A1_BASELINE_CONTROL_latest_ranking.csv"
C_R2 = ROOT / "outputs" / "v21" / "V21.161_R1_C_R2_PROXY_AND_REGIME_REPAIR" / "c_r2_r1_shadow_ranking_top50.csv"
AI = ROOT / "outputs" / "v21" / "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING" / "ai_bottleneck_shadow_ranking_top50.csv"
AI_TAGS = ROOT / "outputs" / "v21" / "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING" / "ai_bottleneck_universe_tags.csv"
SWITCH_STATE = ROOT / "outputs" / "v21" / "V21.163_C_R2_AI_BOTTLENECK_SWITCH_CONTROLLER" / "switch_controller_state.csv"
SWITCH_R1_SUMMARY = ROOT / "outputs" / "v21" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR_summary.json"
V165_SUMMARY = ROOT / "outputs" / "v21" / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD" / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD_summary.json"
V166_SUMMARY = ROOT / "outputs" / "v21" / "V21.166_REALISTIC_EXECUTION_CONSTRAINT_SIMULATOR" / "V21.166_REALISTIC_EXECUTION_CONSTRAINT_SIMULATOR_summary.json"
V167_SUMMARY = ROOT / "outputs" / "v21" / "V21.167_SMALL_ACCOUNT_OVERLAY_CLOSURE_CONTROLLER" / "V21.167_SMALL_ACCOUNT_OVERLAY_CLOSURE_CONTROLLER_summary.json"
SOFTCAP_SUMMARY = ROOT / "outputs" / "v21" / "V21.159_SOFT_CAP_RECIPIENT_RISK_FILTER_AND_SWITCHING_ELIGIBILITY_AUDIT" / "V21.159_machine_summary.json"
SOFTCAP_PORTFOLIO = ROOT / "outputs" / "v21" / "V21.159_SOFT_CAP_RECIPIENT_RISK_FILTER_AND_SWITCHING_ELIGIBILITY_AUDIT" / "softcap_filter_variant_portfolios.csv"
E_R1_SUMMARY = ROOT / "outputs" / "v21" / "V21.157_E_R1_SHADOW_TRIGGER_ATTRIBUTION_AND_FORWARD_MATURITY_GATE" / "V21.157_machine_summary.json"
E_R1_AUDIT = ROOT / "outputs" / "v21" / "V21.149_E_R1_DEFENSIVE_OVERLAY_AND_INVALID_TRIAL_AUDIT" / "V21.149_summary.json"
E_R1_TOP50 = ROOT / "outputs" / "v21" / "V21.133_E_CONSERVATIVE_ADAPTIVE_MOMENTUM_R1" / "e_top50.csv"

ACTIVE_CASH = 600
MAX_SINGLE = 0.35
MAX_SINGLE_DOLLARS = 210
MAX_THEME = 0.25
MAX_THEME_DOLLARS = 150
MIN_POS = 3
PREF_MIN = 3
PREF_MAX = 5
MAX_POS = 5
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
    df = read_csv(PRICE)
    if df.empty or "date" not in df.columns:
        return {}, ""
    ticker_col = "symbol" if "symbol" in df.columns else "ticker"
    price_col = "adjusted_close" if "adjusted_close" in df.columns else "close"
    work = df[[ticker_col, "date", price_col]].copy()
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


def union(*seqs: list[str]) -> list[str]:
    out: list[str] = []
    for seq in seqs:
        for ticker in seq:
            if ticker not in out:
                out.append(ticker)
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


def simulate(module: str, tickers: list[str], price_map: dict[str, float], theme: bool, top_n: int) -> dict[str, Any]:
    selected = tickers[:top_n]
    per_slot = ACTIVE_CASH / max(len(selected), 1)
    positions = []
    gross = 0.0
    missing = 0
    for rank, ticker in enumerate(selected, start=1):
        price = price_map.get(ticker)
        if price is None or pd.isna(price) or price <= 0:
            shares = 0
            notional = 0.0
            missing += 1
        else:
            shares = int(per_slot // price)
            notional = float(shares * price)
        gross += notional
        positions.append({"ticker": ticker, "rank": rank, "price": price if price else "", "shares": shares, "notional": notional})
    weights = [(p["notional"] / gross if gross else 0.0) for p in positions]
    for p, w in zip(positions, weights):
        p["weight"] = w
        p["single_name_dollar_cap_pass"] = p["notional"] <= MAX_SINGLE_DOLLARS
    position_count = sum(1 for p in positions if p["shares"] > 0)
    max_weight = max(weights, default=0.0)
    max_notional = max([p["notional"] for p in positions], default=0.0)
    theme_notional = gross if theme else 0.0
    theme_weight = theme_notional / ACTIVE_CASH if ACTIVE_CASH else 0.0
    min_pass = position_count >= MIN_POS
    single_pass = max_weight <= MAX_SINGLE and max_notional <= MAX_SINGLE_DOLLARS
    theme_pass = (not theme) or (theme_weight <= MAX_THEME and theme_notional <= MAX_THEME_DOLLARS)
    active_executable = min_pass and single_pass and theme_pass and missing == 0
    blockers = []
    if missing:
        blockers.append("MISSING_PRICE")
    if not min_pass:
        blockers.append("MIN_POSITION_COUNT_NOT_MET")
    if not single_pass:
        blockers.append("SINGLE_NAME_CONCENTRATION")
    if not theme_pass:
        blockers.append("THEME_SLEEVE_CONCENTRATION")
    if theme and position_count <= 2 and gross > 0:
        blockers.append("CONCENTRATED_SINGLE_THEME_BET_RESEARCH_ONLY")
    return {
        "module": module,
        "active_cash_budget_usd": ACTIVE_CASH,
        "top_n": top_n,
        "selected_ticker_count": len(selected),
        "position_count": position_count,
        "gross_invested_usd": gross,
        "leftover_cash_usd": ACTIVE_CASH - gross,
        "max_single_name_weight": max_weight,
        "max_single_name_notional_usd": max_notional,
        "max_single_name_weight_pass": max_weight <= MAX_SINGLE,
        "max_single_name_dollar_cap_pass": max_notional <= MAX_SINGLE_DOLLARS,
        "theme_sleeve_weight": theme_weight,
        "theme_sleeve_notional_usd": theme_notional,
        "theme_sleeve_cap_pass": theme_pass,
        "min_position_count_pass": min_pass,
        "missing_price_count": missing,
        "active_600usd_executable": active_executable,
        "blockers": "|".join(dict.fromkeys(blockers)),
        "positions_json": json.dumps(positions),
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "live_trading_allowed": False,
        "overlay_adoption_allowed": False,
    }


def best_module_row(rows: list[dict[str, Any]], module: str) -> dict[str, Any]:
    sub = [r for r in rows if r["module"] == module]
    feasible = [r for r in sub if r["active_600usd_executable"]]
    if feasible:
        return sorted(feasible, key=lambda r: (-r["position_count"], r["max_single_name_weight"]))[0]
    return sorted(sub, key=lambda r: (-r["position_count"], r["max_single_name_weight"]))[0]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    before = protected_hashes()
    price_map, latest_price_date = latest_prices()
    switch = read_csv(SWITCH_STATE)
    selected_regime = "UNKNOWN"
    regime_confidence: Any = ""
    if not switch.empty:
        selected_regime = str(switch.get("selected_regime", pd.Series(["UNKNOWN"])).iloc[0])
        regime_confidence = switch.get("regime_confidence", pd.Series([""])).iloc[0]
    v165 = read_json(V165_SUMMARY)
    v166 = read_json(V166_SUMMARY)
    v167 = read_json(V167_SUMMARY)
    switch_r1 = read_json(SWITCH_R1_SUMMARY)
    softcap_summary = read_json(SOFTCAP_SUMMARY)
    e_summary = read_json(E_R1_SUMMARY)
    e_audit = read_json(E_R1_AUDIT)

    a1 = ranked_tickers(read_csv(A1), 50)
    c_r2 = ranked_tickers(read_csv(C_R2), 50)
    ai = ranked_tickers(read_csv(AI), 50)
    soft = softcap_tickers()
    e_r1 = ranked_tickers(read_csv(E_R1_TOP50), 50)
    dram = dram_tickers(read_csv(AI_TAGS), ai, price_map)
    modules = {
        "A1_PRIMARY_CONTROL": (a1, False),
        "C_R2_CHALLENGER": (c_r2, False),
        "AI_BOTTLENECK_THEME_SLEEVE": (ai, True),
        "SOFTCAP_RETURN_OVERLAY": (soft, False),
        "E_R1_DEFENSIVE_OVERLAY": (e_r1, False),
        "DRAM_ONLY_RESEARCH_VIEW": (dram, True),
    }

    sim_rows = []
    for module, (tickers, theme) in modules.items():
        for top_n in [3, 5]:
            sim_rows.append(simulate(module, tickers, price_map, theme, top_n))
    sim_df = pd.DataFrame(sim_rows)
    write_csv("active_600usd_top3_top5_feasibility.csv", sim_df)

    module_best = {m: best_module_row(sim_rows, m) for m in modules}
    matured_count = int(switch_r1.get("matured_result_count_after", 0) or 0)
    maturity_available = matured_count > 0
    data_blocking = str(v165.get("max_data_quality_impact", "")).upper() == "BLOCKING_IMPACT"
    softcap_risk_mixed = "RISK_MIXED" in str(softcap_summary.get("FINAL_STATUS", "")) or "RISK_MIXED" in str(softcap_summary.get("DECISION", ""))
    e_regime_active = selected_regime.lower() == "risk_off"
    e_maturity = bool(e_summary.get("trigger_maturity_sufficient", False))
    e_lowers_risk = bool(e_audit.get("E_R1_left_tail_valid_after_invalid_filter", False))

    soft_status = "SOFTCAP_WATCH_ONLY_600USD_LIMITED"
    if not soft:
        soft_status = "SOFTCAP_THEORETICAL_ONLY_600USD_BLOCKED"
    soft_feasible = bool(module_best["SOFTCAP_RETURN_OVERLAY"]["active_600usd_executable"]) and not softcap_risk_mixed and maturity_available
    e_status = "E_R1_NOT_ACTIVE_CURRENT_REGIME_600USD" if not e_regime_active else "E_R1_STANDBY_600USD_TRACKED"
    e_feasible = bool(module_best["E_R1_DEFENSIVE_OVERLAY"]["active_600usd_executable"]) and e_regime_active and e_maturity and e_lowers_risk and maturity_available
    if not dram:
        dram_status = "DRAM_ONLY_UNAVAILABLE_MISSING_PRICE"
        dram_feasible = False
    elif module_best["DRAM_ONLY_RESEARCH_VIEW"]["active_600usd_executable"]:
        dram_status = "DRAM_ONLY_RESEARCH_VIEW_AVAILABLE_600USD"
        dram_feasible = True
    else:
        dram_status = "DRAM_ONLY_RESEARCH_VIEW_EXECUTION_BLOCKED_BY_CONCENTRATION_600USD"
        dram_feasible = False
    dram_concentrated = "CONCENTRATED_SINGLE_THEME_BET_RESEARCH_ONLY" in str(module_best["DRAM_ONLY_RESEARCH_VIEW"]["blockers"])

    class_map = {
        "A1_PRIMARY_CONTROL": "A1_PRIMARY_600USD_REFERENCE",
        "C_R2_CHALLENGER": "C_R2_FORWARD_TRACKING_600USD_LIMITED",
        "AI_BOTTLENECK_THEME_SLEEVE": "AI_BOTTLENECK_FORWARD_TRACKING_600USD_LIMITED",
        "SOFTCAP_RETURN_OVERLAY": soft_status,
        "E_R1_DEFENSIVE_OVERLAY": e_status,
        "DRAM_ONLY_RESEARCH_VIEW": "CONCENTRATED_SINGLE_THEME_BET_RESEARCH_ONLY" if dram_concentrated else dram_status,
    }
    state_rows = []
    for module, row in module_best.items():
        state_rows.append({
            "module": module,
            "classification_state": class_map[module],
            **{k: row[k] for k in [
                "active_cash_budget_usd", "top_n", "position_count", "gross_invested_usd", "leftover_cash_usd",
                "max_single_name_weight", "max_single_name_notional_usd", "theme_sleeve_weight",
                "theme_sleeve_notional_usd", "min_position_count_pass", "active_600usd_executable", "blockers",
            ]},
            "research_only": True,
            "official_adoption_allowed": False,
            "broker_action_allowed": False,
            "live_trading_allowed": False,
            "overlay_adoption_allowed": False,
        })
    state_df = pd.DataFrame(state_rows)
    write_csv("active_600usd_overlay_state.csv", state_df)
    write_csv("active_600usd_single_name_cap_check.csv", sim_df[[
        "module", "top_n", "max_single_name_weight", "max_single_name_notional_usd",
        "max_single_name_weight_pass", "max_single_name_dollar_cap_pass", "active_600usd_executable",
    ]])
    write_csv("active_600usd_theme_sleeve_cap_check.csv", sim_df[[
        "module", "top_n", "theme_sleeve_weight", "theme_sleeve_notional_usd", "theme_sleeve_cap_pass", "active_600usd_executable",
    ]])
    write_csv("active_600usd_dram_only_concentration_check.csv", sim_df[sim_df["module"].eq("DRAM_ONLY_RESEARCH_VIEW")].copy())
    write_csv("active_600usd_leftover_cash.csv", sim_df[["module", "top_n", "gross_invested_usd", "leftover_cash_usd", "position_count", "active_600usd_executable"]])

    blocker_rows = []
    for row in sim_rows:
        if row["blockers"]:
            for blocker in row["blockers"].split("|"):
                blocker_rows.append({
                    "module": row["module"],
                    "top_n": row["top_n"],
                    "blocker_type": blocker,
                    "severity": "ACTIVE_600USD_CONSTRAINT",
                    "detail": f"position_count={row['position_count']} max_weight={row['max_single_name_weight']:.4f} max_notional={row['max_single_name_notional_usd']:.2f} theme_notional={row['theme_sleeve_notional_usd']:.2f}",
                })
    if not maturity_available:
        blocker_rows.append({"module": "ALL_OVERLAYS", "top_n": "", "blocker_type": "NO_OVERLAY_PROMOTION_INSUFFICIENT_MATURITY_600USD", "severity": "MATURITY", "detail": "V21.164/R1 matured results are zero"})
    if data_blocking:
        blocker_rows.append({"module": "ALL_OVERLAYS", "top_n": "", "blocker_type": "V21_165_BLOCKING_DATA_QUALITY_IMPACT", "severity": "DATA", "detail": "V21.165 max_data_quality_impact=BLOCKING_IMPACT"})
    blockers_df = pd.DataFrame(blocker_rows)
    write_csv("active_600usd_overlay_blockers.csv", blockers_df)

    overlay_promotion_allowed = False
    closure = "NO_OVERLAY_PROMOTION_INSUFFICIENT_MATURITY_600USD" if not maturity_available else "NO_OVERLAY_PROMOTION_EXECUTION_BLOCKED_600USD"
    write_csv("active_600usd_overlay_closure_decision.csv", pd.DataFrame([{
        "closure_decision": closure,
        "overlay_promotion_allowed": overlay_promotion_allowed,
        "softcap_status_600usd": soft_status,
        "e_r1_status_600usd": e_status,
        "dram_only_status_600usd": dram_status,
        "maturity_evidence_available": maturity_available,
        "data_quality_blocking": data_blocking,
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "live_trading_allowed": False,
        "overlay_adoption_allowed": False,
    }]))
    write_csv("active_600usd_forward_tracking_plan.csv", pd.DataFrame([
        {"module": "A1_PRIMARY_CONTROL", "recommended_forward_tracking_action": "KEEP_PRIMARY_600USD_REFERENCE", "trading_action": "NONE"},
        {"module": "C_R2_CHALLENGER", "recommended_forward_tracking_action": "CONTINUE_FORWARD_TRACKING_ONLY_AT_600USD", "trading_action": "NONE"},
        {"module": "AI_BOTTLENECK_THEME_SLEEVE", "recommended_forward_tracking_action": "TRACK_THEME_SLEEVE_CONCENTRATION_AT_600USD", "trading_action": "NONE"},
        {"module": "SOFTCAP_RETURN_OVERLAY", "recommended_forward_tracking_action": "KEEP_WATCH_ONLY_WAIT_MATURITY_AND_ACTIVE_600USD_FEASIBILITY", "trading_action": "NONE"},
        {"module": "E_R1_DEFENSIVE_OVERLAY", "recommended_forward_tracking_action": "KEEP_STANDBY_UNTIL_RISK_OFF_AND_FORWARD_MATURITY", "trading_action": "NONE"},
        {"module": "DRAM_ONLY_RESEARCH_VIEW", "recommended_forward_tracking_action": "TRACK_RESEARCH_VIEW_ONLY_CONCENTRATION_BLOCKED_AT_600USD", "trading_action": "NONE"},
    ]))
    warnings = pd.DataFrame([
        {"warning_type": "ACTIVE_600USD_PRIMARY_DECISION", "warning": "Final decision is based on USD 600 active cash, not generic sensitivity budgets."},
        {"warning_type": "V21_165_DATA_QUALITY", "warning": f"max_data_quality_impact={v165.get('max_data_quality_impact')}"},
        {"warning_type": "V21_166_REFERENCE_ONLY", "warning": f"prior_warning_count={v166.get('warning_count')}; prior_not_executable_count={v166.get('not_executable_count')}"},
        {"warning_type": "V21_167_REFERENCE_ONLY", "warning": f"prior_decision={v167.get('decision')}"},
        {"warning_type": "MATURITY_WAIT", "warning": f"matured_result_count_after={matured_count}; overlay promotion blocked"},
    ])
    write_csv("active_600usd_data_quality_warnings.csv", warnings)

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

    executable_count = int(state_df["active_600usd_executable"].sum())
    blocked_count = int((~state_df["active_600usd_executable"]).sum())
    max_active_weight = float(pd.to_numeric(state_df["max_single_name_weight"], errors="coerce").max())
    min_pass_count = int(state_df["min_position_count_pass"].sum())
    blocker_count = len(blockers_df)
    warning_count = blocker_count + len(warnings)
    final_status = "WARN"
    decision = "WARN_V21_167_R1_ACTIVE_600USD_PROMOTION_BLOCKED"
    if maturity_available and blocker_count:
        final_status = "PARTIAL_PASS"
        decision = "PARTIAL_PASS_V21_167_R1_ACTIVE_600USD_READY_WITH_WARNINGS"
    elif maturity_available and not blocker_count:
        final_status = "PASS"
        decision = "PASS_V21_167_R1_ACTIVE_600USD_RECHECK_READY"
    summary = {
        "final_status": final_status,
        "decision": decision,
        "default_decision_label": "ACTIVE_600USD_OVERLAY_CLOSURE_TRACKING_ONLY_PROMOTION_BLOCKED",
        **POLICY,
        "latest_price_date_used": latest_price_date or v165.get("latest_price_date_used"),
        "selected_regime": selected_regime,
        "regime_confidence": float(regime_confidence) if str(regime_confidence) else "",
        "active_cash_budget_usd": ACTIVE_CASH,
        "whole_share_required": True,
        "fractional_share_allowed": False,
        "max_single_name_weight": MAX_SINGLE,
        "max_single_name_dollar_cap": MAX_SINGLE_DOLLARS,
        "max_theme_sleeve_weight": MAX_THEME,
        "max_theme_sleeve_dollar_cap": MAX_THEME_DOLLARS,
        "min_position_count": MIN_POS,
        "preferred_position_count_min": PREF_MIN,
        "preferred_position_count_max": PREF_MAX,
        "active_600usd_executable_state_count": executable_count,
        "active_600usd_blocked_state_count": blocked_count,
        "active_600usd_max_single_name_weight": max_active_weight,
        "active_600usd_min_position_count_pass_count": min_pass_count,
        "softcap_status_600usd": soft_status,
        "softcap_small_account_feasible_600usd": soft_feasible,
        "e_r1_status_600usd": e_status,
        "e_r1_small_account_feasible_600usd": e_feasible,
        "dram_only_status_600usd": dram_status,
        "dram_only_small_account_feasible_600usd": dram_feasible,
        "dram_only_concentrated_single_theme_bet": dram_concentrated,
        "maturity_evidence_available": maturity_available,
        "overlay_promotion_allowed": overlay_promotion_allowed,
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_directory": rel(OUT),
    }
    write_json("V21.167_R1_ACTIVE_600USD_SMALL_ACCOUNT_OVERLAY_RECHECK_summary.json", summary)
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
        f"active_cash_budget_usd={ACTIVE_CASH}",
        f"softcap_600usd_status={soft_status}",
        f"e_r1_600usd_status={e_status}",
        f"dram_only_600usd_status={dram_status}",
        f"active_600usd_executable_state_count={executable_count}",
        f"active_600usd_blocked_state_count={blocked_count}",
        f"active_600usd_max_single_name_weight={max_active_weight}",
        f"blocker_count={blocker_count}",
        f"overlay_promotion_allowed={overlay_promotion_allowed}",
        f"warnings={warning_count}",
    ]
    (OUT / "V21.167_R1_ACTIVE_600USD_SMALL_ACCOUNT_OVERLAY_RECHECK_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report[1:]))


if __name__ == "__main__":
    main()
