#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

STAGE = "V21.251_STRATEGY_WEIGHT_GOVERNANCE_FROM_V21_255_AND_CURRENT_REGIME_R1"
OUT_REL = Path("outputs/v21") / STAGE
V255_REL = Path("outputs/v21/V21.255_DETAILED_STRATEGY_BACKTEST_FACTOR_WEIGHT_COMPARISON")
V250_REL = Path("outputs/v21/V21.250_TECHNICAL_DIAGNOSTIC_FREEZE_AND_MANUAL_CHECKLIST_ARCHIVE_R1")
GATES = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "factor_promotion_allowed": False,
    "weight_update_allowed": False,
    "ranking_mutation_allowed": False,
    "trade_plan_mutation_allowed": False,
    "protected_outputs_modified": False,
    "market_data_fetch_allowed": False,
}


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return [{k: (v or "") for k, v in r.items() if k is not None} for r in csv.DictReader(f)]
    except Exception:
        return []


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n", encoding="utf-8")


def roots(repo: Path, v255: Path, v250: Path) -> tuple[Path, Path]:
    return (v255 if v255.is_absolute() else repo / v255, v250 if v250.is_absolute() else repo / v250)


def strategy_roles(s255: dict[str, Any]) -> list[dict[str, Any]]:
    current = s255.get("recommended_current_regime_strategy") or "E_R3_QUALITY_RISK_REPAIR_BASE"
    fallback = s255.get("recommended_fallback_strategy") or "E_R2_CONSERVATIVE_DEFENSIVE_RETURN"
    watch = s255.get("recommended_parallel_watch_strategy") or "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL"
    strategies = list(dict.fromkeys([current, fallback, watch, "DRAM", "A1", "QQQ", *s255.get("strategies_compared", [])]))
    rows = []
    for st in strategies:
        if st == current:
            role, rationale = "CURRENT_REGIME_SHADOW_PRIMARY", "V21.255 current-regime risk-adjusted winner."
        elif st == fallback:
            role, rationale = "LONG_HISTORY_FALLBACK", "V21.255 conservative long-history fallback."
        elif st == watch:
            role, rationale = "HIGH_RETURN_WATCH_ONLY", "V21.255 high-return watch with risk gates unresolved."
        elif st in {"A1", "QQQ", "DRAM"}:
            role, rationale = "CONTROL_BASELINE", "Baseline/control reference; DRAM remains primary trading focus where applicable."
        else:
            role, rationale = "DIAGNOSTIC_ONLY", "Not mapped to governance role."
        rows.append({"strategy": st, "governance_role": role, "source": "V21.255", "rationale": rationale, "research_only": True, "official_adoption_allowed": False, "broker_action_allowed": False, "weight_update_allowed": False, "ranking_mutation_allowed": False})
    return rows


def switch_conditions(current: str, fallback: str, watch: str) -> list[dict[str, Any]]:
    return [
        {"condition_name": "E_R3_REMAINS_PRIMARY_IF_ADVANTAGE_PERSISTS", "source_strategy": current, "target_strategy": current, "condition_description": "E_R3 remains shadow primary if current-regime risk-adjusted advantage persists.", "action_allowed": "RESEARCH_REVIEW_ONLY"},
        {"condition_name": "E_R2_FALLBACK_ON_E_R3_DRAWDOWN_OR_MISMATCH", "source_strategy": current, "target_strategy": fallback, "condition_description": "E_R2 becomes fallback if E_R3 drawdown, instability, or regime mismatch appears.", "action_allowed": "RESEARCH_REVIEW_ONLY"},
        {"condition_name": "NEW_FACTOR_LITE_WATCH_ONLY_UNTIL_RISK_GATES_IMPROVE", "source_strategy": watch, "target_strategy": watch, "condition_description": "High-return watch remains watch-only unless risk gates improve.", "action_allowed": "WATCH_ONLY"},
        {"condition_name": "DRAM_ONLY_PREFERENCE_REMAINS_DOMINANT", "source_strategy": "DRAM", "target_strategy": "DRAM", "condition_description": "DRAM-only preference remains dominant unless user explicitly approves broader strategy action.", "action_allowed": "NO_AUTOMATIC_ACTION"},
    ]


def no_go_audit() -> list[dict[str, Any]]:
    checks = [
        ("no_official_adoption", False, "official_adoption_allowed"),
        ("no_broker_action", False, "broker_action_allowed"),
        ("no_live_trade_plan_mutation", False, "trade_plan_mutation_allowed"),
        ("no_factor_weight_update", False, "weight_update_allowed"),
        ("no_ranking_mutation", False, "ranking_mutation_allowed"),
    ]
    return [{"check_name": name, "expected_allowed": expected, "observed_allowed": GATES[field], "passed": GATES[field] == expected, "field": field} for name, expected, field in checks]


def dram_audit() -> list[dict[str, Any]]:
    return [
        {"audit_item": "strategy_governance_research_only", "passed": True, "detail": "Strategy governance roles are research-only."},
        {"audit_item": "dram_primary_trading_focus_unchanged", "passed": True, "detail": "No automatic replacement of DRAM trading focus."},
        {"audit_item": "strategy_roles_research_review_only", "passed": True, "detail": "Roles may inform research review only."},
        {"audit_item": "no_automatic_ticker_replacement", "passed": True, "detail": "No ticker replacement or trade plan mutation allowed."},
    ]


def technical_freeze_audit(s250: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    checks = [
        ("technical_model_entry_allowed", False, "model_entry_allowed"),
        ("technical_timing_overlay_allowed", False, "technical_timing_overlay_allowed"),
        ("technical_context_filter_allowed", False, "technical_context_filter_allowed"),
        ("technical_manual_checklist_allowed", True, "technical_manual_checklist_allowed"),
    ]
    for name, expected, key in checks:
        observed = s250.get(key, expected)
        rows.append({"freeze_item": name, "expected": expected, "observed": observed, "passed": observed == expected, "source": "V21.250"})
    return rows


def keep_watch_drop(roles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in roles:
        role = r["governance_role"]
        if role == "CURRENT_REGIME_SHADOW_PRIMARY":
            action = "KEEP_AS_SHADOW_PRIMARY_RESEARCH_ONLY"
        elif role == "LONG_HISTORY_FALLBACK":
            action = "KEEP_AS_FALLBACK_RESEARCH_ONLY"
        elif role == "HIGH_RETURN_WATCH_ONLY":
            action = "WATCH_ONLY"
        elif role == "CONTROL_BASELINE":
            action = "KEEP_AS_CONTROL"
        else:
            action = "DIAGNOSTIC_ONLY"
        out.append({"strategy": r["strategy"], "governance_role": role, "review_action": action, "reason": r["rationale"], "official_adoption_allowed": False, "broker_action_allowed": False})
    return out


def optional_missing(r255: Path) -> list[str]:
    names = ["strategy_period_decision_matrix.csv", "strategy_backtest_comparison_master.csv", "strategy_factor_weight_effectiveness_matrix.csv"]
    return [n for n in names if not (r255 / n).exists()]


def gate_violation(summary: dict[str, Any]) -> bool:
    gate_keys = ["official_adoption_allowed", "broker_action_allowed", "weight_update_allowed", "ranking_mutation_allowed", "trade_plan_mutation_allowed"]
    return any(summary.get(k) is True for k in gate_keys) or summary.get("technical_model_entry_allowed") is True or summary.get("technical_timing_overlay_allowed") is True or summary.get("technical_context_filter_allowed") is True


def fail_summary(status: str, decision: str, missing_count: int) -> dict[str, Any]:
    return {"final_status": status, "final_decision": decision, "strategy_count": 0, "role_mapped_strategy_count": 0, "current_regime_shadow_primary": "", "long_history_fallback": "", "high_return_watch_only": "", "switch_condition_count": 0, "dram_compatible": False, "technical_freeze_enforced": False, "technical_model_entry_allowed": False, "technical_timing_overlay_allowed": False, "technical_context_filter_allowed": False, "technical_manual_checklist_allowed": True, "missing_input_count": missing_count, "warning_count": 0, "error_count": 1, **GATES}


def run(repo: Path, output_dir: Path | None = None, v255_root: Path = V255_REL, v250_root: Path = V250_REL) -> dict[str, Any]:
    out = output_dir or repo / OUT_REL
    r255, r250 = roots(repo, v255_root, v250_root)
    s255 = read_json(r255 / "v21_255_summary.json")
    s250 = read_json(r250 / "v21_250_summary.json")
    missing = []
    if not s255:
        missing.append("V21.255 summary")
    if not s250:
        missing.append("V21.250 summary")
    if missing:
        summary = fail_summary("FAIL_V21_251_STRATEGY_GOVERNANCE_INPUT_MISSING", "STRATEGY_GOVERNANCE_BLOCKED_INPUT_MISSING", len(missing))
        write_outputs(out, [], [], [], [], [], summary)
        return summary
    roles = strategy_roles(s255)
    current = next(r["strategy"] for r in roles if r["governance_role"] == "CURRENT_REGIME_SHADOW_PRIMARY")
    fallback = next(r["strategy"] for r in roles if r["governance_role"] == "LONG_HISTORY_FALLBACK")
    watch = next(r["strategy"] for r in roles if r["governance_role"] == "HIGH_RETURN_WATCH_ONLY")
    switches = switch_conditions(current, fallback, watch)
    dram = dram_audit()
    freeze = technical_freeze_audit(s250)
    optional = optional_missing(r255)
    freeze_ok = all(r["passed"] for r in freeze)
    dram_ok = all(r["passed"] for r in dram)
    strategy_count = len(s255.get("strategies_compared", [])) or len(roles)
    status = "PASS_V21_251_STRATEGY_GOVERNANCE_READY_RESEARCH_ONLY" if not optional and freeze_ok and dram_ok else "WARN_V21_251_STRATEGY_GOVERNANCE_READY_WITH_MISSING_OPTIONAL_INPUTS"
    decision = "STRATEGY_GOVERNANCE_READY_RESEARCH_ONLY" if status.startswith("PASS") else "STRATEGY_GOVERNANCE_READY_RESEARCH_ONLY_WITH_OPTIONAL_GAPS"
    summary = {"final_status": status, "final_decision": decision, "strategy_count": strategy_count, "role_mapped_strategy_count": len(roles), "current_regime_shadow_primary": current, "long_history_fallback": fallback, "high_return_watch_only": watch, "switch_condition_count": len(switches), "dram_compatible": dram_ok, "technical_freeze_enforced": freeze_ok, "technical_model_entry_allowed": False, "technical_timing_overlay_allowed": False, "technical_context_filter_allowed": False, "technical_manual_checklist_allowed": True, "missing_input_count": 0, "warning_count": len(optional) + (0 if freeze_ok and dram_ok else 1), "error_count": 0, **GATES}
    if not freeze_ok or not dram_ok:
        summary["final_status"] = "FAIL_V21_251_STRATEGY_GOVERNANCE_GATE_VIOLATION"
        summary["final_decision"] = "STRATEGY_GOVERNANCE_BLOCKED_GATE_VIOLATION"
        summary["error_count"] = 1
    if gate_violation(summary):
        summary["final_status"] = "FAIL_V21_251_STRATEGY_GOVERNANCE_GATE_VIOLATION"
        summary["final_decision"] = "STRATEGY_GOVERNANCE_BLOCKED_GATE_VIOLATION"
        summary["error_count"] = 1
    write_outputs(out, roles, switches, no_go_audit(), dram, freeze, summary)
    return summary


def write_outputs(out: Path, roles: list[dict[str, Any]], switches: list[dict[str, Any]], nogo: list[dict[str, Any]], dram: list[dict[str, Any]], freeze: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "strategy_governance_role_map.csv", roles, ["strategy", "governance_role", "source", "rationale", "research_only", "official_adoption_allowed", "broker_action_allowed", "weight_update_allowed", "ranking_mutation_allowed"])
    write_csv(out / "strategy_switch_condition_candidates.csv", switches, ["condition_name", "source_strategy", "target_strategy", "condition_description", "action_allowed"])
    write_csv(out / "strategy_weight_governance_no_go_audit.csv", nogo, ["check_name", "expected_allowed", "observed_allowed", "passed", "field"])
    write_csv(out / "dram_compatibility_audit.csv", dram, ["audit_item", "passed", "detail"])
    write_csv(out / "technical_freeze_enforcement_audit.csv", freeze, ["freeze_item", "expected", "observed", "passed", "source"])
    write_csv(out / "strategy_governance_keep_watch_drop_review.csv", keep_watch_drop(roles), ["strategy", "governance_role", "review_action", "reason", "official_adoption_allowed", "broker_action_allowed"])
    write_json(out / "v21_251_summary.json", summary)
    (out / "V21.251_strategy_weight_governance_report.txt").write_text(f"{STAGE}\nfinal_status={summary['final_status']}\nfinal_decision={summary['final_decision']}\ncurrent_regime_shadow_primary={summary.get('current_regime_shadow_primary','')}\nlong_history_fallback={summary.get('long_history_fallback','')}\nhigh_return_watch_only={summary.get('high_return_watch_only','')}\nresearch_only=True\nofficial_adoption_allowed=False\nbroker_action_allowed=False\nweight_update_allowed=False\nranking_mutation_allowed=False\ntrade_plan_mutation_allowed=False\nmarket_data_fetch_allowed=False\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--output-dir", type=Path)
    p.add_argument("--v21-255-root", type=Path, default=V255_REL)
    p.add_argument("--v21-250-root", type=Path, default=V250_REL)
    a = p.parse_args(argv)
    s = run(a.repo_root.resolve(), a.output_dir, a.v21_255_root, a.v21_250_root)
    for k in ["final_status", "final_decision", "strategy_count", "role_mapped_strategy_count", "current_regime_shadow_primary", "long_history_fallback", "high_return_watch_only", "switch_condition_count", "dram_compatible", "technical_freeze_enforced", "technical_model_entry_allowed", "technical_timing_overlay_allowed", "technical_context_filter_allowed", "technical_manual_checklist_allowed", "official_adoption_allowed", "broker_action_allowed", "weight_update_allowed", "ranking_mutation_allowed", "trade_plan_mutation_allowed", "market_data_fetch_allowed", "missing_input_count", "warning_count", "error_count"]:
        print(f"{k}={s.get(k)}")
    return 1 if str(s.get("final_status", "")).startswith("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
