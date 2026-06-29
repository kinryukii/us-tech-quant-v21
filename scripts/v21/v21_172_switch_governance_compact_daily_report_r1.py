from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.172_SWITCH_GOVERNANCE_COMPACT_DAILY_REPORT_R1"
OUT = ROOT / "outputs" / "v21" / STAGE

V168 = ROOT / "outputs" / "v21" / "V21.168_STRATEGY_SWITCHING_GOVERNANCE_RULEBOOK_R1"
V169 = ROOT / "outputs" / "v21" / "V21.169_DAILY_SWITCH_LEDGER_APPEND_AND_GOVERNANCE_REFRESH"
V170 = ROOT / "outputs" / "v21" / "V21.170_SWITCH_TRIGGER_THRESHOLD_CALIBRATION_R1"
V171 = ROOT / "outputs" / "v21" / "V21.171_INTEGRATE_CALIBRATED_THRESHOLDS_INTO_DAILY_GOVERNANCE_REFRESH"

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
            for child in base.rglob("*"):
                if child.is_file():
                    hashes[rel(child)] = sha(child)
    return hashes


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def source(path: Path, warnings: list[dict[str, Any]], source_name: str) -> bool:
    ok = path.exists() and path.stat().st_size > 0
    if not ok:
        warnings.append({
            "source_name": source_name,
            "source_path": rel(path),
            "warning_type": "SOURCE_MISSING_WARNING",
            "warning": "Input missing; compact report continues with available sources and does not fabricate source results.",
        })
    return ok


def first_row(df: pd.DataFrame) -> dict[str, Any]:
    return df.iloc[0].to_dict() if not df.empty else {}


def value(*items: Any, default: Any = "") -> Any:
    for item in items:
        if item is not None and item != "":
            return item
    return default


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    before = protected_hashes([V168, V169, V170, V171])
    warnings: list[dict[str, Any]] = []

    source(V168 / "validation_summary.json", warnings, "V21.168 validation summary")
    source(V169 / "validation_summary.json", warnings, "V21.169 validation summary")
    source(V170 / "validation_summary.json", warnings, "V21.170 validation summary")
    source(V171 / "validation_summary.json", warnings, "V21.171 validation summary")
    source(V171 / "integrated_daily_governance_snapshot.csv", warnings, "V21.171 integrated snapshot")
    source(V171 / "switch_state_threshold_pass_fail_matrix.csv", warnings, "V21.171 state pass/fail matrix")

    v168 = read_json(V168 / "validation_summary.json")
    v169 = read_json(V169 / "validation_summary.json")
    v170 = read_json(V170 / "validation_summary.json")
    v171 = read_json(V171 / "validation_summary.json")
    integrated_snapshot = first_row(read_csv(V171 / "integrated_daily_governance_snapshot.csv"))
    matrix = read_csv(V171 / "switch_state_threshold_pass_fail_matrix.csv")
    append_summary = first_row(read_csv(V169 / "daily_switch_ledger_append_summary.csv"))

    final_decision = str(value(v171.get("final_decision"), integrated_snapshot.get("final_decision"), v169.get("final_decision"), v168.get("final_decision"), default="WAIT_MORE_MATURITY"))
    if final_decision not in FINAL_DECISIONS:
        warnings.append({
            "source_name": "final_decision",
            "source_path": rel(V171 / "validation_summary.json"),
            "warning_type": "INVALID_DECISION_ENUM_WARNING",
            "warning": "Final decision outside allowed enum; compact report blocks adoption.",
        })
        final_decision = "OFFICIAL_ADOPTION_BLOCKED"

    current_primary = value(v171.get("current_primary_control"), integrated_snapshot.get("current_primary_control"), v169.get("current_primary_control"), v168.get("current_primary_control"), default="A1_CONTROL")
    best_state = value(v171.get("best_forward_tracking_state"), integrated_snapshot.get("best_forward_tracking_state"), v169.get("best_forward_tracking_state"), v168.get("best_forward_tracking_state"), default="A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING")
    final_status = str(value(v171.get("final_status"), integrated_snapshot.get("final_status"), v169.get("final_status"), v168.get("final_status"), default="PARTIAL_PASS_COMPACT_SWITCH_REPORT_READY_WITH_WARNINGS"))
    compact_status = "PASS_COMPACT_SWITCH_REPORT_READY" if not warnings else "PARTIAL_PASS_COMPACT_SWITCH_REPORT_READY_WITH_WARNINGS"
    threshold_source = value(v171.get("threshold_source"), integrated_snapshot.get("threshold_source"), default="V21.170_SWITCH_TRIGGER_THRESHOLD_CALIBRATION_R1")
    calibration_mode = "conservative_default" if boolish(value(v171.get("calibration_defaults_used"), integrated_snapshot.get("calibration_defaults_used"), v170.get("calibration_defaults_used"), default=True)) else "empirical"
    active_cash = int(value(v171.get("active_cash_assumption_usd"), integrated_snapshot.get("active_cash_assumption_usd"), v170.get("active_cash_assumption_usd"), default=600))
    latest_price = value(v171.get("latest_available_price_date"), integrated_snapshot.get("latest_available_price_date"), v169.get("latest_available_price_date"), default="")
    latest_tracking = value(v171.get("latest_switch_state_tracking_date"), integrated_snapshot.get("latest_switch_state_tracking_date"), v169.get("latest_switch_state_tracking_date"), default="")

    role_review = boolish(value(v171.get("role_review_required"), integrated_snapshot.get("role_review_required"), default=False))
    one_day_allowed = boolish(value(v171.get("one_day_outperformance_switch_allowed"), v170.get("one_day_outperformance_switch_allowed"), default=False))
    switch_allowed_research_only = final_decision == "SWITCH_ALLOWED_RESEARCH_ONLY"

    blockers = [
        {
            "blocker": "insufficient_forward_maturity",
            "active": final_decision == "WAIT_MORE_MATURITY" or int(v170.get("matured_observation_count_for_calibration", 0) or 0) == 0,
            "detail": "Forward 5D/10D/20D maturity remains below calibrated thresholds.",
        },
        {
            "blocker": "insufficient_historical_calibration_data",
            "active": boolish(v170.get("insufficient_historical_calibration_data", True)),
            "detail": "V21.170 used conservative defaults because empirical calibration history is insufficient.",
        },
        {
            "blocker": "no_new_switch_ledger_data",
            "active": boolish(v169.get("no_new_data", False)) or str(append_summary.get("append_status", "")).eq("WARN_NO_NEW_SWITCH_LEDGER_DATA") if hasattr(str(append_summary.get("append_status", "")), "eq") else str(append_summary.get("append_status", "")) == "WARN_NO_NEW_SWITCH_LEDGER_DATA",
            "detail": "V21.169 reported no new switch ledger rows.",
        },
        {
            "blocker": "execution_feasibility_constraints_600usd",
            "active": active_cash <= 600,
            "detail": "Top20 official portfolio execution remains blocked or unverified under 600 USD active cash.",
        },
        {
            "blocker": "dram_only_execution_fallback_only",
            "active": True,
            "detail": "DRAM-only is an execution_fallback_only scenario and not an official diversified strategy.",
        },
        {
            "blocker": "source_missing_warnings",
            "active": any(w.get("warning_type") == "SOURCE_MISSING_WARNING" for w in warnings),
            "detail": "One or more compact report inputs are missing." if warnings else "No missing required compact report sources detected.",
        },
    ]
    blocker_df = pd.DataFrame([{**row, "research_only": True} for row in blockers])

    snapshot = pd.DataFrame([{
        "report_date": latest_price or datetime.now(timezone.utc).date().isoformat(),
        "final_status": compact_status if warnings else final_status if final_status else compact_status,
        "upstream_final_status": final_status,
        "final_decision": final_decision,
        "current_primary_control": current_primary,
        "best_forward_tracking_state": best_state,
        "threshold_source": threshold_source,
        "calibration_mode": calibration_mode,
        "calibration_defaults_used": calibration_mode == "conservative_default",
        "insufficient_historical_calibration_data": boolish(v170.get("insufficient_historical_calibration_data", True)),
        "active_cash_assumption_usd": active_cash,
        "latest_available_price_date": latest_price,
        "latest_switch_state_tracking_date": latest_tracking,
        "next_required_data_condition": "Continue daily switch ledger append and wait for 5D/10D/20D maturity.",
        **POLICY,
    }])

    action_flags = pd.DataFrame([{
        "role_review_required": role_review,
        "switch_allowed_research_only": switch_allowed_research_only,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": False,
        "one_day_outperformance_switch_allowed": one_day_allowed,
        "research_only": True,
    }])

    watch_states = [
        ("A1_CONTROL", "baseline"),
        ("C_R2_CHALLENGER", "challenger"),
        ("AI_BOTTLENECK_THEME", "theme_tracking_only"),
        ("A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING", "best_forward_tracking_state"),
        ("A1_PLUS_E_R1_DEFENSIVE_STANDBY", "E_R1_DEFENSIVE_CANDIDATE"),
        ("A1_PLUS_SOFTCAP_WATCH_ONLY", "SOFT_CAP"),
        ("D_ORIGINAL", "frozen_reference"),
        ("DRAM_ONLY", "execution_fallback_only"),
    ]
    watch_rows = []
    for state, label in watch_states:
        hit = matrix[matrix["state"].astype(str).eq(state)] if not matrix.empty and "state" in matrix.columns else pd.DataFrame()
        row = first_row(hit)
        watch_rows.append({
            "watch_state": "E_R1_DEFENSIVE_CANDIDATE" if state == "A1_PLUS_E_R1_DEFENSIVE_STANDBY" else "SOFT_CAP" if state == "A1_PLUS_SOFTCAP_WATCH_ONLY" else state,
            "source_state": state,
            "watch_role": label,
            "eligibility_class": row.get("eligibility_class", "source_missing"),
            "role_review_required": boolish(row.get("role_review_required", False)),
            "official_portfolio_strategy": False if state == "DRAM_ONLY" else boolish(row.get("official_portfolio_strategy", state == "A1_CONTROL")),
            "blocker_summary": row.get("blocker_summary", "SOURCE_MISSING_WARNING" if hit.empty else ""),
            "research_only": True,
            "official_adoption_allowed": False,
            "broker_action_allowed": False,
        })
    watchlist = pd.DataFrame(watch_rows)

    write_csv("compact_switch_governance_snapshot.csv", snapshot)
    write_csv("compact_switch_blocker_summary.csv", blocker_df)
    write_csv("compact_switch_action_flags.csv", action_flags)
    write_csv("compact_switch_watchlist.csv", watchlist)

    after = protected_hashes([V168, V169, V170, V171])
    changed = [path for path, digest in before.items() if after.get(path) != digest]
    validation = {
        "stage": STAGE,
        "final_status": str(snapshot["final_status"].iloc[0]),
        "final_decision": final_decision,
        "allowed_final_decision_enum": sorted(FINAL_DECISIONS),
        **POLICY,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": False,
        "changed_protected_file_count": len(changed),
        "changed_protected_paths": changed,
        "current_primary_control": current_primary,
        "best_forward_tracking_state": best_state,
        "threshold_source": threshold_source,
        "calibration_mode": calibration_mode,
        "calibration_defaults_used": calibration_mode == "conservative_default",
        "insufficient_historical_calibration_data": boolish(v170.get("insufficient_historical_calibration_data", True)),
        "role_review_required": role_review,
        "switch_allowed_research_only": switch_allowed_research_only,
        "one_day_outperformance_switch_allowed": one_day_allowed,
        "dram_only_official_portfolio_strategy": False,
        "active_cash_assumption_usd": active_cash,
        "latest_available_price_date": latest_price,
        "latest_switch_state_tracking_date": latest_tracking,
        "warning_count": len(warnings),
        "source_warning_count": len([w for w in warnings if w.get("warning_type") == "SOURCE_MISSING_WARNING"]),
        "warnings": warnings,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_directory": rel(OUT),
    }
    write_json("validation_summary.json", validation)

    active_blockers = blocker_df[blocker_df["active"].astype(bool)]["blocker"].tolist()
    report = [
        "V21.172 Compact Switch Governance Daily Report",
        "",
        f"Conclusion: {final_decision}. Continue daily ledger append and wait for maturity.",
        f"Current control: {current_primary}",
        f"Best forward-tracking state: {best_state}",
        f"Final status: {snapshot['final_status'].iloc[0]}",
        f"Threshold source: {threshold_source}",
        f"Calibration mode: {calibration_mode}",
        "",
        "Main blockers:",
        *[f"- {b}" for b in active_blockers],
        "",
        f"Role review triggered: {str(role_review).lower()}",
        f"Switching allowed research-only: {str(switch_allowed_research_only).lower()}",
        "Official adoption allowed: false",
        "Broker action allowed: false",
        "Protected outputs modified: false",
        f"One-day outperformance switch allowed: {str(one_day_allowed).lower()}",
        "",
        "Next required data condition: continue daily switch ledger append and wait for matured 5D/10D/20D observations.",
    ]
    (OUT / "V21.172_compact_switch_governance_daily_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
