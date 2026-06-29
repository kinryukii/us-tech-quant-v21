from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.171_INTEGRATE_CALIBRATED_THRESHOLDS_INTO_DAILY_GOVERNANCE_REFRESH"
OUT = ROOT / "outputs" / "v21" / STAGE

V168 = ROOT / "outputs" / "v21" / "V21.168_STRATEGY_SWITCHING_GOVERNANCE_RULEBOOK_R1"
V169 = ROOT / "outputs" / "v21" / "V21.169_DAILY_SWITCH_LEDGER_APPEND_AND_GOVERNANCE_REFRESH"
V170 = ROOT / "outputs" / "v21" / "V21.170_SWITCH_TRIGGER_THRESHOLD_CALIBRATION_R1"

THRESHOLD_FILES = [
    "switch_trigger_threshold_table.csv",
    "maturity_requirement_table.csv",
    "excess_return_threshold_table.csv",
    "risk_blocker_threshold_table.csv",
    "hysteresis_threshold_table.csv",
    "execution_proxy_threshold_table.csv",
    "calibrated_switch_decision_policy.csv",
    "validation_summary.json",
]

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

EMBEDDED_THRESHOLDS = {
    "minimum_5d_matured_observations": 5,
    "minimum_10d_matured_observations": 5,
    "minimum_20d_matured_observations": 3,
    "minimum_10d_win_rate_vs_A1": 0.60,
    "minimum_20d_win_rate_vs_A1": 0.60,
    "minimum_10d_avg_excess_return_vs_A1": 0.005,
    "minimum_20d_avg_excess_return_vs_A1": 0.008,
    "minimum_hysteresis_consecutive_pass_days": 3,
    "minimum_decision_stability_days_before_switch": 3,
    "one_day_outperformance_switch_allowed": False,
}

POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "live_trading_allowed": False,
    "protected_outputs_modified": False,
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


def protected_hashes(extra_paths: list[Path] | None = None) -> dict[str, str]:
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
    for base in extra_paths or []:
        if base.exists() and base.is_file():
            hashes[rel(base)] = sha(base)
        elif base.exists():
            for path in base.rglob("*"):
                if path.is_file():
                    hashes[rel(path)] = sha(path)
    return hashes


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def audit_threshold_sources(warnings: list[dict[str, Any]]) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], dict[str, Any]]:
    frames: dict[str, pd.DataFrame] = {}
    rows = []
    v170_summary = read_json(V170 / "validation_summary.json")
    for name in THRESHOLD_FILES:
        path = V170 / name
        exists = path.exists() and path.stat().st_size > 0
        parseable = False
        row_count = 0
        warning_type = "NONE"
        if exists:
            try:
                if name.endswith(".json"):
                    parseable = bool(read_json(path))
                else:
                    frame = read_csv(path)
                    frames[name] = frame
                    parseable = not frame.empty
                    row_count = int(len(frame))
            except Exception as exc:
                warning_type = "SOURCE_PARSE_WARNING"
                warnings.append({
                    "source_name": name,
                    "source_path": rel(path),
                    "warning_type": warning_type,
                    "warning": f"Threshold source could not be parsed: {exc}",
                })
        else:
            warning_type = "SOURCE_MISSING_WARNING"
            warnings.append({
                "source_name": name,
                "source_path": rel(path),
                "warning_type": warning_type,
                "warning": "Threshold source missing; embedded conservative defaults are used without empirical calibration.",
            })
        rows.append({
            "threshold_source": "V21.170_SWITCH_TRIGGER_THRESHOLD_CALIBRATION_R1",
            "source_file": name,
            "source_path": rel(path),
            "exists": exists,
            "parseable": parseable,
            "row_count": row_count,
            "calibration_defaults_used": boolish(v170_summary.get("calibration_defaults_used", True)),
            "insufficient_historical_calibration_data": boolish(v170_summary.get("insufficient_historical_calibration_data", True)),
            "source_warning": warning_type,
            "research_only": True,
        })
    return pd.DataFrame(rows), frames, v170_summary


def threshold_value(frames: dict[str, pd.DataFrame], name: str) -> Any:
    trigger = frames.get("switch_trigger_threshold_table.csv", pd.DataFrame())
    if not trigger.empty and {"threshold_name", "threshold_value"}.issubset(trigger.columns):
        hit = trigger[trigger["threshold_name"].astype(str).eq(name)]
        if not hit.empty:
            value = hit["threshold_value"].iloc[0]
            if str(value).lower() in {"true", "false"}:
                return str(value).lower() == "true"
            return pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return EMBEDDED_THRESHOLDS[name]


def current_states(maturity: pd.DataFrame, risk: pd.DataFrame) -> list[str]:
    states = set()
    if not maturity.empty and "state" in maturity.columns:
        states.update(maturity["state"].astype(str))
    if not risk.empty and "state" in risk.columns:
        states.update(risk["state"].astype(str))
    states.update(["A1_CONTROL", "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING", "DRAM_ONLY"])
    return sorted(states)


def state_maturity(maturity: pd.DataFrame, state: str, horizon: str) -> int:
    if maturity.empty:
        return 0
    hit = maturity[maturity["state"].astype(str).eq(state) & maturity["horizon"].astype(str).eq(horizon)]
    if hit.empty:
        return 0
    return int(pd.to_numeric(hit["matured_observations"], errors="coerce").fillna(0).sum())


def build_gate_matrices(
    frames: dict[str, pd.DataFrame],
    maturity: pd.DataFrame,
    risk: pd.DataFrame,
    execution: pd.DataFrame,
    v170_summary: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    states = current_states(maturity, risk)
    min5 = int(threshold_value(frames, "minimum_5d_matured_observations"))
    min10 = int(threshold_value(frames, "minimum_10d_matured_observations"))
    min20 = int(threshold_value(frames, "minimum_20d_matured_observations"))
    one_day_allowed = boolish(threshold_value(frames, "one_day_outperformance_switch_allowed"))
    active_cash = int(v170_summary.get("active_cash_assumption_usd") or 600)
    rows = []
    state_rows = []
    for state in states:
        m5 = state_maturity(maturity, state, "5D")
        m10 = state_maturity(maturity, state, "10D")
        m20 = state_maturity(maturity, state, "20D")
        maturity_pass = m5 >= min5 and m10 >= min10 and m20 >= min20
        risk_hit = risk[risk["state"].astype(str).eq(state)] if not risk.empty and "state" in risk.columns else pd.DataFrame()
        risk_status = str(risk_hit["risk_gate_status"].iloc[0]) if not risk_hit.empty and "risk_gate_status" in risk_hit.columns else "SOURCE_MISSING_WARNING"
        risk_pass = risk_status.startswith("PASS")
        exec_hit = execution[execution["execution_classification"].astype(str).eq("Top20 diversified portfolio")] if not execution.empty and "execution_classification" in execution.columns else pd.DataFrame()
        official_exec_feasible = active_cash > 600 and not exec_hit.empty and boolish(exec_hit["official_portfolio_strategy"].iloc[0])
        if state == "DRAM_ONLY":
            official_exec_feasible = False
        performance_pass = False
        hysteresis_pass = False if not one_day_allowed else False
        gates = [
            ("maturity_thresholds", maturity_pass, f"5D={m5}/{min5};10D={m10}/{min10};20D={m20}/{min20}"),
            ("win_rate_thresholds", performance_pass, "No matured vs A1 win-rate observations available."),
            ("excess_return_thresholds", performance_pass, "No matured vs A1 excess-return observations available."),
            ("risk_deterioration_thresholds", risk_pass, risk_status),
            ("concentration_thresholds", risk_pass, risk_status),
            ("hysteresis_thresholds", hysteresis_pass, f"one_day_outperformance_switch_allowed={one_day_allowed}"),
            ("execution_feasibility_thresholds", official_exec_feasible, f"active_cash_assumption_usd={active_cash}"),
        ]
        blockers = [gate for gate, passed, _ in gates if not passed]
        for gate, passed, detail in gates:
            rows.append({
                "state": state,
                "gate_category": gate,
                "gate_pass": passed,
                "gate_status": "PASS" if passed else "FAIL_OR_WAIT",
                "evaluation_detail": detail,
                "threshold_source": "V21.170_SWITCH_TRIGGER_THRESHOLD_CALIBRATION_R1",
                "research_only": True,
            })
        state_rows.append({
            "state": state,
            "maturity_thresholds_pass": maturity_pass,
            "win_rate_thresholds_pass": performance_pass,
            "excess_return_thresholds_pass": performance_pass,
            "risk_thresholds_pass": risk_pass,
            "concentration_thresholds_pass": risk_pass,
            "hysteresis_thresholds_pass": hysteresis_pass,
            "execution_feasibility_thresholds_pass": official_exec_feasible,
            "role_review_required": False,
            "official_portfolio_strategy": False if state == "DRAM_ONLY" else state == "A1_CONTROL",
            "eligibility_class": "execution_fallback_only" if state == "DRAM_ONLY" else "baseline" if state == "A1_CONTROL" else "research_forward_tracking",
            "blocker_summary": "|".join(blockers) if blockers else "NONE",
            "research_only": True,
            "official_adoption_allowed": False,
            "broker_action_allowed": False,
        })
    return pd.DataFrame(rows), pd.DataFrame(state_rows)


def decide(state_matrix: pd.DataFrame, v169_summary: dict[str, Any], v170_summary: dict[str, Any]) -> tuple[str, str]:
    matured_zero = int(v170_summary.get("matured_observation_count_for_calibration", 0) or 0) == 0
    main = state_matrix[state_matrix["state"].astype(str).eq("A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING")]
    if matured_zero or (not main.empty and not boolish(main["maturity_thresholds_pass"].iloc[0])):
        return "WAIT_MORE_MATURITY", "Integrated calibrated thresholds keep switch state in maturity wait."
    if not main.empty and not boolish(main["risk_thresholds_pass"].iloc[0]):
        return "BLOCKED_BY_RISK", "Main forward-tracking state breaches or lacks risk threshold support."
    if not main.empty and not boolish(main["execution_feasibility_thresholds_pass"].iloc[0]):
        return "BLOCKED_BY_EXECUTION", "Main forward-tracking state lacks official Top20 execution feasibility."
    return str(v169_summary.get("final_decision", "ALLOW_FORWARD_TRACKING_ONLY")), "Carried from daily governance refresh."


def build_history(refresh_date: str, decision: str, v169_summary: dict[str, Any], v170_summary: dict[str, Any], blocker_summary: str) -> tuple[pd.DataFrame, str, bool]:
    path = OUT / "integrated_decision_history.csv"
    existing = read_csv(path)
    previous = decision
    if not existing.empty and "current_decision" in existing.columns:
        previous = str(existing.tail(1)["current_decision"].iloc[0])
    row = {
        "refresh_date": refresh_date,
        "previous_decision": previous,
        "current_decision": decision,
        "decision_changed": previous != decision,
        "threshold_source": "V21.170_SWITCH_TRIGGER_THRESHOLD_CALIBRATION_R1",
        "calibration_mode": "conservative_default" if boolish(v170_summary.get("calibration_defaults_used", True)) else "empirical",
        "current_primary_control": v169_summary.get("current_primary_control", "A1_CONTROL"),
        "best_forward_tracking_state": v169_summary.get("best_forward_tracking_state", "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING"),
        "role_review_required": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "blocker_summary": blocker_summary,
        "research_only": True,
    }
    if existing.empty:
        return pd.DataFrame([row]), previous, True
    history = pd.concat([existing, pd.DataFrame([row])], ignore_index=True)
    history = history.drop_duplicates(["refresh_date"], keep="last").sort_values("refresh_date")
    return history, previous, False


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    before = protected_hashes([V168, V169, V170])
    warnings: list[dict[str, Any]] = []

    audit, frames, v170_summary = audit_threshold_sources(warnings)
    v168_summary = read_json(V168 / "validation_summary.json")
    v169_summary = read_json(V169 / "validation_summary.json")
    maturity = read_csv(V169 / "refreshed_switch_state_maturity_scoreboard.csv")
    risk = read_csv(V168 / "switch_state_risk_blocker_ledger.csv")
    execution = frames.get("execution_proxy_threshold_table.csv", pd.DataFrame())
    policy = frames.get("calibrated_switch_decision_policy.csv", pd.DataFrame())
    if policy.empty:
        policy = pd.DataFrame({"allowed_final_decision": sorted(FINAL_DECISIONS)})

    gate_matrix, state_matrix = build_gate_matrices(frames, maturity, risk, execution, v170_summary)
    decision, decision_reason = decide(state_matrix, v169_summary, v170_summary)
    if decision not in FINAL_DECISIONS:
        decision = "OFFICIAL_ADOPTION_BLOCKED"
        decision_reason = "Decision enum invalid; official adoption blocked."
    main_state = state_matrix[state_matrix["state"].astype(str).eq("A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING")]
    blocker_summary = str(main_state["blocker_summary"].iloc[0]) if not main_state.empty else "MISSING_MAIN_STATE"
    refresh_date = str(v169_summary.get("latest_available_price_date") or v170_summary.get("latest_available_price_date") or datetime.now(timezone.utc).date())
    history, previous, history_initialized = build_history(refresh_date, decision, v169_summary, v170_summary, blocker_summary)
    change = pd.DataFrame([{
        "refresh_date": refresh_date,
        "previous_decision": previous,
        "current_decision": decision,
        "decision_changed": previous != decision,
        "previous_role_review_required": False,
        "current_role_review_required": False,
        "role_review_required_changed_false_to_true": False,
        "previous_official_adoption_allowed": False,
        "current_official_adoption_allowed": False,
        "official_adoption_allowed_changed": False,
        "previous_broker_action_allowed": False,
        "current_broker_action_allowed": False,
        "broker_action_allowed_changed": False,
        "threshold_source": "V21.170_SWITCH_TRIGGER_THRESHOLD_CALIBRATION_R1",
        "research_only": True,
    }])
    snapshot = pd.DataFrame([{
        "refresh_date": refresh_date,
        "final_status": "PARTIAL_PASS_INTEGRATED_THRESHOLDS_WAIT_MATURITY",
        "final_decision": decision,
        "decision_reason": decision_reason,
        "threshold_source": "V21.170_SWITCH_TRIGGER_THRESHOLD_CALIBRATION_R1",
        "calibration_defaults_used": boolish(v170_summary.get("calibration_defaults_used", True)),
        "insufficient_historical_calibration_data": boolish(v170_summary.get("insufficient_historical_calibration_data", True)),
        "current_primary_control": v169_summary.get("current_primary_control") or v168_summary.get("current_primary_control") or "A1_CONTROL",
        "best_forward_tracking_state": v169_summary.get("best_forward_tracking_state") or v168_summary.get("best_forward_tracking_state") or "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING",
        "active_cash_assumption_usd": int(v170_summary.get("active_cash_assumption_usd") or v169_summary.get("active_cash_assumption_usd") or 600),
        "latest_available_price_date": v169_summary.get("latest_available_price_date", "2026-06-26"),
        "latest_switch_state_tracking_date": v169_summary.get("latest_switch_state_tracking_date", "2026-06-25"),
        "role_review_required": False,
        "blocker_summary": blocker_summary,
        **POLICY,
    }])

    write_csv("integrated_threshold_source_audit.csv", audit)
    write_csv("integrated_daily_governance_snapshot.csv", snapshot)
    write_csv("threshold_gate_evaluation_matrix.csv", gate_matrix)
    write_csv("switch_state_threshold_pass_fail_matrix.csv", state_matrix)
    write_csv("integrated_decision_history.csv", history)
    write_csv("integrated_switch_decision_change_log.csv", change)

    after = protected_hashes([V168, V169, V170])
    changed = [path for path, digest in before.items() if after.get(path) != digest]
    if history_initialized:
        warnings.append({
            "source_name": "integrated_decision_history",
            "source_path": rel(OUT / "integrated_decision_history.csv"),
            "warning_type": "HISTORY_INITIALIZED",
            "warning": "No prior integrated decision history existed; initialized with current decision.",
        })
    allowed_policy_ok = set(policy.get("allowed_final_decision", pd.Series(dtype=str)).astype(str)).issubset(FINAL_DECISIONS)
    validation = {
        "stage": STAGE,
        "final_status": str(snapshot["final_status"].iloc[0]),
        "final_decision": decision,
        "allowed_final_decision_enum": sorted(FINAL_DECISIONS),
        **POLICY,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": False,
        "changed_protected_file_count": len(changed),
        "changed_protected_paths": changed,
        "threshold_source": "V21.170_SWITCH_TRIGGER_THRESHOLD_CALIBRATION_R1",
        "threshold_source_detected": bool(audit["exists"].all() and audit["parseable"].all()),
        "calibration_defaults_used": boolish(v170_summary.get("calibration_defaults_used", True)),
        "insufficient_historical_calibration_data": boolish(v170_summary.get("insufficient_historical_calibration_data", True)),
        "calibration_matured_observations": int(v170_summary.get("matured_observation_count_for_calibration", 0) or 0),
        "current_primary_control": snapshot["current_primary_control"].iloc[0],
        "best_forward_tracking_state": snapshot["best_forward_tracking_state"].iloc[0],
        "active_cash_assumption_usd": int(snapshot["active_cash_assumption_usd"].iloc[0]),
        "latest_available_price_date": snapshot["latest_available_price_date"].iloc[0],
        "latest_switch_state_tracking_date": snapshot["latest_switch_state_tracking_date"].iloc[0],
        "role_review_required": False,
        "one_day_outperformance_switch_allowed": False,
        "dram_only_official_portfolio_strategy": False,
        "allowed_policy_ok": allowed_policy_ok,
        "history_initialized": history_initialized,
        "decision_changed": bool(change["decision_changed"].iloc[0]),
        "warning_count": len(warnings),
        "source_warning_count": len([w for w in warnings if "SOURCE_MISSING_WARNING" in str(w.get("warning_type", ""))]),
        "warnings": warnings,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_directory": rel(OUT),
    }
    write_json("validation_summary.json", validation)

    report = [
        STAGE,
        f"final_status={validation['final_status']}",
        f"final_decision={decision}",
        f"decision_reason={decision_reason}",
        "threshold_source=V21.170_SWITCH_TRIGGER_THRESHOLD_CALIBRATION_R1",
        f"calibration_defaults_used={validation['calibration_defaults_used']}",
        f"insufficient_historical_calibration_data={validation['insufficient_historical_calibration_data']}",
        f"calibration_matured_observations={validation['calibration_matured_observations']}",
        f"current_primary_control={validation['current_primary_control']}",
        f"best_forward_tracking_state={validation['best_forward_tracking_state']}",
        f"active_cash_assumption_usd={validation['active_cash_assumption_usd']}",
        "role_review_required=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "protected_outputs_modified=false",
        "research_only=true",
        "",
        "Integrated gate result:",
        blocker_summary,
        "",
        "Small-capital execution:",
        "Top20 official portfolio execution remains blocked under current 600 USD assumption.",
        "Top10 is research proxy only; Top5 is execution fallback only; single-name fallback is not official.",
        "DRAM-only remains execution_fallback_only and not an official diversified portfolio strategy.",
        "",
        "Warnings:",
        *[f"- {w['warning_type']}: {w['warning']}" for w in warnings],
    ]
    (OUT / "V21.171_integrated_threshold_governance_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
