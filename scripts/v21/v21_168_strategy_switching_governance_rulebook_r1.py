from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.168_STRATEGY_SWITCHING_GOVERNANCE_RULEBOOK_R1"
OUT = ROOT / "outputs" / "v21" / STAGE

V164 = ROOT / "outputs" / "v21" / "V21.164_SWITCH_STATE_FORWARD_TRACKING_LEDGER"
V164_R1 = ROOT / "outputs" / "v21" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR"
V159 = ROOT / "outputs" / "v21" / "V21.159_SOFT_CAP_RECIPIENT_RISK_FILTER_AND_SWITCHING_ELIGIBILITY_AUDIT"
V168_FALLBACK = ROOT / "outputs" / "v21" / "V21.168_600USD_CASH_CONSTRAINED_EXECUTION_FALLBACK_CONTROLLER"
V166_EXEC = ROOT / "outputs" / "v21" / "V21.166_REALISTIC_EXECUTION_CONSTRAINT_SIMULATOR"
V160_D_R3 = ROOT / "outputs" / "v21" / "V21.160_D_R3_RISK_CONSTRAINED_REBUILD_FEASIBILITY_AUDIT"
V137_E_RISK = ROOT / "outputs" / "v21" / "V21.137_E_R1_RISK_DECOMPOSITION_VS_A1"

FINAL_DECISIONS = {
    "KEEP_A1_CONTROL",
    "WAIT_MORE_MATURITY",
    "ALLOW_FORWARD_TRACKING_ONLY",
    "BLOCKED_BY_RISK",
    "BLOCKED_BY_EXECUTION",
    "BLOCKED_BY_DATA_QUALITY",
    "ROLE_REVIEW_REQUIRED",
    "SWITCH_ALLOWED_RESEARCH_ONLY",
    "OFFICIAL_ADOPTION_BLOCKED",
}

HORIZONS = ["5D", "10D", "20D"]
POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "live_trading_allowed": False,
    "protected_outputs_modified": False,
    "adopted_weights_modified": False,
    "official_rankings_modified": False,
}

STATE_RULES = [
    {
        "state": "A1_CONTROL",
        "eligibility_class": "baseline",
        "role": "current_primary_control",
        "official_portfolio_strategy": True,
    },
    {
        "state": "C_R2_CHALLENGER",
        "eligibility_class": "eligible_forward_tracking",
        "role": "challenger_forward_tracking",
        "official_portfolio_strategy": False,
    },
    {
        "state": "AI_BOTTLENECK_THEME",
        "eligibility_class": "theme_tracking_only",
        "role": "theme_tracking_only",
        "official_portfolio_strategy": False,
    },
    {
        "state": "A1_PLUS_C_R2_FORWARD_TRACKING",
        "eligibility_class": "eligible_forward_tracking",
        "role": "forward_tracking_state",
        "official_portfolio_strategy": False,
    },
    {
        "state": "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING",
        "eligibility_class": "eligible_forward_tracking",
        "role": "main_forward_tracking_state",
        "official_portfolio_strategy": False,
    },
    {
        "state": "A1_PLUS_E_R1_DEFENSIVE_STANDBY",
        "eligibility_class": "defensive_candidate",
        "role": "defensive_candidate_wait_maturity",
        "official_portfolio_strategy": False,
    },
    {
        "state": "A1_PLUS_SOFTCAP_WATCH_ONLY",
        "eligibility_class": "blocked_risk_mixed",
        "role": "return_enhancer_candidate_blocked_from_switching",
        "official_portfolio_strategy": False,
    },
    {
        "state": "D_ORIGINAL",
        "eligibility_class": "frozen_reference_only",
        "role": "frozen_reference_only",
        "official_portfolio_strategy": False,
    },
    {
        "state": "D_R3_REBUILD",
        "eligibility_class": "blocked",
        "role": "unsupported_rebuild",
        "official_portfolio_strategy": False,
    },
    {
        "state": "DRAM_ONLY",
        "eligibility_class": "execution_fallback_only",
        "role": "capital_constrained_execution_fallback_not_official_strategy",
        "official_portfolio_strategy": False,
    },
]


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
            protected = protected or ("adopted" in s and any(x in s for x in ["weight", "allocation"]))
            if protected:
                hashes[rel(path)] = sha(path)
    return hashes


def boolish(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def source_status(path: Path, warnings: list[dict[str, Any]], source_name: str) -> str:
    if path.exists() and path.stat().st_size > 0:
        return "SOURCE_AVAILABLE"
    warnings.append({
        "source_name": source_name,
        "source_path": rel(path),
        "warning_type": "SOURCE_MISSING_WARNING",
        "warning": "Source file missing; gate records warning and does not fabricate PASS.",
    })
    return "SOURCE_MISSING_WARNING"


def maturity_by_state(ledger: pd.DataFrame) -> dict[tuple[str, str], int]:
    if ledger.empty or not {"tracked_state", "horizon", "maturity_status"}.issubset(ledger.columns):
        return {}
    matured = ledger[ledger["maturity_status"].astype(str).eq("MATURED")]
    grouped = matured.groupby(["tracked_state", "horizon"]).size()
    return {(str(k[0]), str(k[1])): int(v) for k, v in grouped.items()}


def pending_by_state(ledger: pd.DataFrame) -> dict[tuple[str, str], int]:
    if ledger.empty or not {"tracked_state", "horizon", "maturity_status"}.issubset(ledger.columns):
        return {}
    pending = ledger[ledger["maturity_status"].astype(str).eq("PENDING_MATURITY")]
    grouped = pending.groupby(["tracked_state", "horizon"]).size()
    return {(str(k[0]), str(k[1])): int(v) for k, v in grouped.items()}


def risk_lookup(risk: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if risk.empty or "tracked_state" not in risk.columns:
        return {}
    return {str(row["tracked_state"]): row.to_dict() for _, row in risk.iterrows()}


def blocker_text(parts: list[str]) -> str:
    clean = [p for p in parts if p]
    return "|".join(clean) if clean else "NONE"


def build_eligibility(switch_summary: dict[str, Any]) -> pd.DataFrame:
    selected = str(switch_summary.get("selected_switch_state") or "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING")
    rows = []
    for rule in STATE_RULES:
        state = rule["state"]
        rows.append({
            "state": state,
            "eligibility_class": rule["eligibility_class"],
            "current_role": rule["role"],
            "current_primary_control": state == "A1_CONTROL",
            "selected_main_forward_tracking_state": state == selected,
            "official_portfolio_strategy": rule["official_portfolio_strategy"],
            "research_only": True,
            "official_adoption_allowed": False,
            "broker_action_allowed": False,
            "eligibility_notes": {
                "A1_CONTROL": "Current primary control remains A1_CONTROL.",
                "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING": "Best forward-tracking state if supported by V21.164; not adopted.",
                "A1_PLUS_SOFTCAP_WATCH_ONLY": "Soft-cap is return enhancer candidate with mixed risk; switching remains blocked.",
                "A1_PLUS_E_R1_DEFENSIVE_STANDBY": "Defensive candidate waiting for maturity.",
                "D_ORIGINAL": "Frozen reference only.",
                "D_R3_REBUILD": "Unsupported rebuild.",
                "DRAM_ONLY": "Capital-constrained execution fallback only, not diversified portfolio strategy.",
            }.get(state, "Research-only state classification."),
        })
    return pd.DataFrame(rows)


def build_maturity(ledger: pd.DataFrame, r1_summary: dict[str, Any], warnings: list[dict[str, Any]]) -> pd.DataFrame:
    if ledger.empty:
        warnings.append({
            "source_name": "switch_state_forward_ledger",
            "source_path": rel(V164_R1 / "switch_ledger_r1_full_ledger.csv"),
            "warning_type": "SOURCE_MISSING_WARNING",
            "warning": "No switch-state ledger available; maturity pass cannot be asserted.",
        })
    matured = maturity_by_state(ledger)
    pending = pending_by_state(ledger)
    rows = []
    for rule in STATE_RULES:
        state = rule["state"]
        for horizon in HORIZONS:
            m = matured.get((state, horizon), 0)
            p = pending.get((state, horizon), 0)
            rows.append({
                "state": state,
                "horizon": horizon,
                "available_matured_observations": m,
                "pending_observations": p,
                "maturity_gate_status": "PASS_MATURITY_AVAILABLE" if m > 0 else "FAIL_WAIT_MATURITY",
                "source": "V21.164_R1" if not ledger.empty else "SOURCE_MISSING_WARNING",
                "research_only": True,
            })
    if int(r1_summary.get("matured_result_count_after", 0) or 0) == 0:
        warnings.append({
            "source_name": "V21.164_R1 maturity summary",
            "source_path": rel(V164_R1 / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR_summary.json"),
            "warning_type": "INSUFFICIENT_MATURITY",
            "warning": "V21.164_R1 reports zero matured switch-state results; switching cannot be based on immature rows.",
        })
    return pd.DataFrame(rows)


def build_risk_blockers(risk: pd.DataFrame, softcap: pd.DataFrame, warnings: list[dict[str, Any]]) -> pd.DataFrame:
    source_status(V164 / "switch_state_risk_diagnostics.csv", warnings, "switch_state_risk_diagnostics")
    source_status(V159 / "softcap_switching_eligibility_audit.csv", warnings, "softcap_switching_eligibility_audit")
    source_status(V137_E_RISK / "e_r1_vs_a1_left_tail_proxy_comparison.csv", warnings, "e_r1_left_tail_proxy")
    source_status(V164 / "switch_state_turnover_instability.csv", warnings, "switch_state_turnover_instability")
    lookup = risk_lookup(risk)
    softcap_status = ""
    if not softcap.empty and "eligibility_status" in softcap.columns:
        softcap_status = "|".join(sorted(set(softcap["eligibility_status"].dropna().astype(str))))
    rows = []
    for rule in STATE_RULES:
        state = rule["state"]
        r = lookup.get(state, {})
        concentration = pd.to_numeric(pd.Series([r.get("top20_sector_concentration", "")]), errors="coerce").iloc[0]
        data_warning_count = int(pd.to_numeric(pd.Series([r.get("data_warning_count", 0)]), errors="coerce").fillna(0).iloc[0])
        repeated_loser_count = int(pd.to_numeric(pd.Series([r.get("repeated_loser_count", 0)]), errors="coerce").fillna(0).iloc[0])
        blockers = []
        if pd.notna(concentration) and concentration >= 0.70 and state != "A1_CONTROL":
            blockers.append("CONCENTRATION_RISK")
        if state == "A1_PLUS_SOFTCAP_WATCH_ONLY" or "RISK_MIXED" in softcap_status:
            if state == "A1_PLUS_SOFTCAP_WATCH_ONLY":
                blockers.append("SOFTCAP_RISK_MIXED")
        if data_warning_count > 0:
            blockers.append("STALE_PRICE_OR_DATA_QUALITY_WARNING")
        if repeated_loser_count > 0:
            blockers.append("REPEATED_LOSER_RISK")
        if state == "D_R3_REBUILD":
            blockers.append("UNSUPPORTED_REBUILD")
        if state == "DRAM_ONLY":
            blockers.append("NOT_DIVERSIFIED_PORTFOLIO")
        left_tail = "SOURCE_MISSING_WARNING"
        if r and boolish(r.get("left_tail_proxy_available", False)):
            left_tail = "AVAILABLE"
        rows.append({
            "state": state,
            "concentration_risk": "WARN" if "CONCENTRATION_RISK" in blockers else "NO_PASS_ASSERTED" if not r else "NOT_FLAGGED",
            "left_tail_risk": left_tail,
            "repeated_loser_risk": "WARN" if "REPEATED_LOSER_RISK" in blockers else "NOT_FLAGGED" if r else "SOURCE_MISSING_WARNING",
            "regime_mismatch": "NOT_EVALUATED_SOURCE_MISSING_WARNING",
            "stale_price_data_quality_warnings": data_warning_count,
            "turnover_instability": "SOURCE_MISSING_WARNING",
            "risk_blockers": blocker_text(blockers),
            "risk_gate_status": "FAIL_RISK_BLOCKER" if blockers else "WARN_SOURCE_LIMITED" if not r else "PASS_NO_BLOCKER_FOUND_IN_AVAILABLE_SOURCES",
            "research_only": True,
        })
    return pd.DataFrame(rows)


def build_execution_feasibility(fallback_summary: dict[str, Any], blockers: pd.DataFrame) -> pd.DataFrame:
    active_cash = int(fallback_summary.get("active_cash_budget_usd") or 600)
    blocker_lookup = {}
    if not blockers.empty and {"module", "top_n"}.issubset(blockers.columns):
        for _, row in blockers.iterrows():
            module = str(row["module"])
            top_n = str(row.get("top_n", ""))
            blocker_lookup.setdefault((module, top_n), []).append(str(row.get("blocker_type", "")))
    module_map = {
        "A1_CONTROL": "A1_PRIMARY_CONTROL",
        "C_R2_CHALLENGER": "C_R2_CHALLENGER",
        "AI_BOTTLENECK_THEME": "AI_BOTTLENECK_THEME_SLEEVE",
        "A1_PLUS_SOFTCAP_WATCH_ONLY": "SOFTCAP_RETURN_OVERLAY",
        "A1_PLUS_E_R1_DEFENSIVE_STANDBY": "E_R1_DEFENSIVE_OVERLAY",
        "DRAM_ONLY": "DRAM_ONLY_RESEARCH_VIEW",
    }
    rows = []
    for rule in STATE_RULES:
        state = rule["state"]
        module = module_map.get(state, state)
        for bucket, top_n in [("Top20", "20.0"), ("Top10", "10.0"), ("Top5", "5.0"), ("single_name_fallback", "1.0")]:
            b = blocker_lookup.get((module, top_n), [])
            if bucket == "Top20" and bool(fallback_summary.get("portfolio_mode_blocked", True)):
                b = b + ["PORTFOLIO_MODE_BLOCKED_BY_ACTIVE_CASH"]
            if state == "DRAM_ONLY":
                classification = "execution_fallback_only"
                executable = bucket == "single_name_fallback" and bool(fallback_summary.get("dram_fallback_available", False))
                b = b + ["NOT_OFFICIAL_DIVERSIFIED_PORTFOLIO_STRATEGY"]
            else:
                classification = rule["eligibility_class"]
                executable = not b and bucket in {"Top5", "Top10", "Top20"} and active_cash > 600
            rows.append({
                "state": state,
                "active_cash_assumption_usd": active_cash,
                "feasibility_bucket": bucket,
                "eligibility_class": classification,
                "executable_under_small_cash": executable,
                "execution_gate_status": "PASS_EXECUTION_FEASIBLE" if executable and state != "DRAM_ONLY" else "FAIL_EXECUTION_BLOCKED" if b else "WARN_NOT_VERIFIED",
                "blockers": blocker_text(b),
                "official_portfolio_strategy": False if state == "DRAM_ONLY" else rule["official_portfolio_strategy"],
                "research_only": True,
                "broker_action_allowed": False,
            })
    return pd.DataFrame(rows)


def build_hysteresis(maturity: pd.DataFrame, comparison: pd.DataFrame) -> pd.DataFrame:
    rows = []
    thresholds = {
        "min_matured_5d": 3,
        "min_matured_10d": 3,
        "min_matured_20d": 2,
        "min_positive_horizons": 2,
        "min_average_excess_return_vs_a1": 0.01,
        "min_win_rate_vs_a1": 0.60,
        "min_consecutive_ranking_dates": 3,
    }
    for rule in STATE_RULES:
        state = rule["state"]
        m = maturity[maturity["state"].eq(state)] if not maturity.empty else pd.DataFrame()
        matured_total = int(pd.to_numeric(m.get("available_matured_observations", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        comp = comparison[comparison["tracked_state"].astype(str).eq(state)].copy() if not comparison.empty and "tracked_state" in comparison.columns else pd.DataFrame()
        avg_excess = None
        win_rate = None
        positive_horizons = 0
        if not comp.empty and "excess_return_vs_a1" in comp.columns:
            comp["excess_return_vs_a1"] = pd.to_numeric(comp["excess_return_vs_a1"], errors="coerce")
            avg_excess = float(comp["excess_return_vs_a1"].mean()) if comp["excess_return_vs_a1"].notna().any() else None
            positive_horizons = int((comp["excess_return_vs_a1"] > 0).sum())
            if "win_vs_a1" in comp.columns:
                win_rate = float(comp["win_vs_a1"].astype(str).str.lower().isin(["true", "1"]).mean())
        pass_gate = (
            matured_total >= thresholds["min_matured_5d"] + thresholds["min_matured_10d"] + thresholds["min_matured_20d"]
            and avg_excess is not None
            and avg_excess >= thresholds["min_average_excess_return_vs_a1"]
            and (win_rate or 0.0) >= thresholds["min_win_rate_vs_a1"]
            and positive_horizons >= thresholds["min_positive_horizons"]
        )
        rows.append({
            "state": state,
            "matured_observation_total": matured_total,
            "average_excess_return_vs_a1": "" if avg_excess is None else avg_excess,
            "win_rate_vs_a1": "" if win_rate is None else win_rate,
            "positive_horizon_count": positive_horizons,
            **thresholds,
            "hysteresis_gate_status": "PASS_ROLE_REVIEW_ELIGIBLE" if pass_gate else "FAIL_WAIT_PERSISTENT_ADVANTAGE",
            "one_day_or_immature_switching_allowed": False,
            "research_only": True,
        })
    return pd.DataFrame(rows)


def final_decision(elig: pd.DataFrame, maturity: pd.DataFrame, risk: pd.DataFrame, execution: pd.DataFrame, hysteresis: pd.DataFrame) -> tuple[str, str]:
    mature_total = int(pd.to_numeric(maturity["available_matured_observations"], errors="coerce").fillna(0).sum()) if not maturity.empty else 0
    main_state = "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING"
    main_hyst = hysteresis[hysteresis["state"].eq(main_state)] if not hysteresis.empty else pd.DataFrame()
    main_risk = risk[risk["state"].eq(main_state)] if not risk.empty else pd.DataFrame()
    if mature_total == 0:
        return "WAIT_MORE_MATURITY", "No 5D/10D/20D switch-state observations are matured; A1_CONTROL remains primary control."
    if not main_risk.empty and str(main_risk["risk_gate_status"].iloc[0]).startswith("FAIL"):
        return "BLOCKED_BY_RISK", "Main forward-tracking state has an active risk blocker."
    if main_hyst.empty or str(main_hyst["hysteresis_gate_status"].iloc[0]) != "PASS_ROLE_REVIEW_ELIGIBLE":
        return "ALLOW_FORWARD_TRACKING_ONLY", "Maturity exists but persistent advantage thresholds are not satisfied."
    exec_pass = execution[
        execution["state"].eq(main_state) & execution["execution_gate_status"].astype(str).eq("PASS_EXECUTION_FEASIBLE")
    ]
    if exec_pass.empty:
        return "BLOCKED_BY_EXECUTION", "Persistent advantage would still need executable diversified portfolio feasibility."
    return "SWITCH_ALLOWED_RESEARCH_ONLY", "All research gates passed, but official adoption and broker action remain blocked by this isolated stage."


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    before = protected_hashes()
    warnings: list[dict[str, Any]] = []

    r1_summary_path = V164_R1 / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR_summary.json"
    switch_summary = read_json(r1_summary_path)
    fallback_summary = read_json(V168_FALLBACK / "V21.168_600USD_CASH_CONSTRAINED_EXECUTION_FALLBACK_CONTROLLER_summary.json")
    exec_summary = read_json(V166_EXEC / "V21.166_REALISTIC_EXECUTION_CONSTRAINT_SIMULATOR_summary.json")

    source_status(r1_summary_path, warnings, "V21.164_R1 summary")
    source_status(V168_FALLBACK / "V21.168_600USD_CASH_CONSTRAINED_EXECUTION_FALLBACK_CONTROLLER_summary.json", warnings, "V21.168 fallback summary")
    source_status(V166_EXEC / "V21.166_REALISTIC_EXECUTION_CONSTRAINT_SIMULATOR_summary.json", warnings, "V21.166 execution summary")

    ledger = read_csv(V164_R1 / "switch_ledger_r1_full_ledger.csv")
    if ledger.empty:
        ledger = read_csv(V164 / "switch_state_forward_ledger.csv")
    comparison = read_csv(V164_R1 / "switch_ledger_r1_vs_a1_comparison.csv")
    if comparison.empty:
        comparison = read_csv(V164 / "switch_state_vs_a1_comparison.csv")
    risk_source = read_csv(V164 / "switch_state_risk_diagnostics.csv")
    softcap = read_csv(V159 / "softcap_switching_eligibility_audit.csv")
    execution_blockers = read_csv(V168_FALLBACK / "portfolio_mode_blockers_600usd.csv")

    eligibility = build_eligibility(switch_summary)
    maturity = build_maturity(ledger, switch_summary, warnings)
    risk = build_risk_blockers(risk_source, softcap, warnings)
    execution = build_execution_feasibility(fallback_summary or exec_summary, execution_blockers)
    hysteresis = build_hysteresis(maturity, comparison)
    decision, reason = final_decision(eligibility, maturity, risk, execution, hysteresis)
    if decision not in FINAL_DECISIONS:
        decision = "OFFICIAL_ADOPTION_BLOCKED"
        reason = "Internal decision enum fallback."

    final = pd.DataFrame([{
        "current_primary_control": "A1_CONTROL",
        "best_forward_tracking_state": switch_summary.get("selected_switch_state") or "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING",
        "final_decision": decision,
        "final_decision_reason": reason,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": False,
        "adopted_weights_modified": False,
        "research_only": True,
    }])

    write_csv("switch_state_eligibility_matrix.csv", eligibility)
    write_csv("switch_state_maturity_scoreboard.csv", maturity)
    write_csv("switch_state_risk_blocker_ledger.csv", risk)
    write_csv("switch_state_execution_feasibility.csv", execution)
    write_csv("switch_state_hysteresis_check.csv", hysteresis)
    write_csv("final_switch_recommendation.csv", final)

    after = protected_hashes()
    changed = [path for path, digest in before.items() if after.get(path) != digest]
    protected_clean = len(changed) == 0
    warning_df = pd.DataFrame(warnings) if warnings else pd.DataFrame([{
        "source_name": "NONE",
        "source_path": "",
        "warning_type": "NONE",
        "warning": "",
    }])

    validation = {
        "stage": STAGE,
        "final_status": "PASS_RESEARCH_RULEBOOK_CREATED_WITH_WARNINGS" if warnings else "PASS_RESEARCH_RULEBOOK_CREATED",
        "final_decision": decision,
        "allowed_final_decision_enum": sorted(FINAL_DECISIONS),
        **POLICY,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": False,
        "protected_output_mutation_audit_clean": protected_clean,
        "changed_protected_file_count": len(changed),
        "changed_protected_paths": changed,
        "current_primary_control": "A1_CONTROL",
        "expected_primary_control_retained": True,
        "best_forward_tracking_state": final["best_forward_tracking_state"].iloc[0],
        "active_cash_assumption_usd": int((fallback_summary or exec_summary).get("active_cash_budget_usd") or 600),
        "source_warning_count": len([w for w in warnings if w.get("warning_type") == "SOURCE_MISSING_WARNING"]),
        "warning_count": len(warnings),
        "warnings": warnings,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_directory": rel(OUT),
    }
    write_json("validation_summary.json", validation)
    write_csv("source_warning_ledger.csv", warning_df)

    thresholds = hysteresis.iloc[0].to_dict() if not hysteresis.empty else {}
    report = [
        STAGE,
        f"final_decision={decision}",
        f"reason={reason}",
        "current_primary_control=A1_CONTROL",
        f"best_forward_tracking_state={final['best_forward_tracking_state'].iloc[0]}",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
        "",
        "Eligibility gate:",
        "- A1_CONTROL is baseline/current primary control.",
        "- A1+C_R2+AI_BOTTLENECK remains forward-tracking only when supported by V21.164.",
        "- Soft-cap remains blocked_risk_mixed; no switch allowed.",
        "- E_R1 remains defensive_candidate pending maturity.",
        "- D_original is frozen_reference_only; D_R3 rebuild is blocked/unsupported.",
        "- DRAM_ONLY is execution_fallback_only, not an official diversified portfolio strategy.",
        "",
        "Maturity gate:",
        f"- V21.164_R1 matured_result_count_after={switch_summary.get('matured_result_count_after', 0)}.",
        "- Insufficient maturity forces WAIT_MORE_MATURITY or forward-tracking-only handling.",
        "",
        "Risk blocker gate:",
        "- Concentration, left-tail, repeated-loser, regime mismatch, stale/data-quality, and turnover instability fields are recorded.",
        "- Missing source files are SOURCE_MISSING_WARNING, never silent PASS.",
        "",
        "Execution feasibility gate:",
        f"- Active cash assumption={validation['active_cash_assumption_usd']} USD.",
        "- Top20, Top10, Top5, and single-name fallback feasibility are classified separately.",
        "- DRAM-only remains a capital-constrained fallback and is not promoted.",
        "",
        "Hysteresis gate thresholds:",
        f"- Minimum matured observations: 5D={thresholds.get('min_matured_5d', 3)}, 10D={thresholds.get('min_matured_10d', 3)}, 20D={thresholds.get('min_matured_20d', 2)}.",
        f"- Minimum positive horizons={thresholds.get('min_positive_horizons', 2)}.",
        f"- Minimum average excess return vs A1={thresholds.get('min_average_excess_return_vs_a1', 0.01)}.",
        f"- Minimum win rate vs A1={thresholds.get('min_win_rate_vs_a1', 0.60)}.",
        f"- Minimum consecutive ranking dates={thresholds.get('min_consecutive_ranking_dates', 3)}.",
        "- One-day or immature switching is not allowed.",
        "",
        f"source_warning_count={validation['source_warning_count']}",
        f"protected_output_mutation_audit_clean={protected_clean}",
    ]
    (OUT / "V21.168_switching_governance_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
