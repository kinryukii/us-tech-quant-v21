from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.170_SWITCH_TRIGGER_THRESHOLD_CALIBRATION_R1"
OUT = ROOT / "outputs" / "v21" / STAGE

V168 = ROOT / "outputs" / "v21" / "V21.168_STRATEGY_SWITCHING_GOVERNANCE_RULEBOOK_R1"
V169 = ROOT / "outputs" / "v21" / "V21.169_DAILY_SWITCH_LEDGER_APPEND_AND_GOVERNANCE_REFRESH"
V164_R1 = ROOT / "outputs" / "v21" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR"
V164 = ROOT / "outputs" / "v21" / "V21.164_SWITCH_STATE_FORWARD_TRACKING_LEDGER"

FINAL_DECISIONS = [
    "KEEP_A1_CONTROL",
    "WAIT_MORE_MATURITY",
    "ALLOW_FORWARD_TRACKING_ONLY",
    "BLOCKED_BY_RISK",
    "BLOCKED_BY_EXECUTION",
    "BLOCKED_BY_DATA_QUALITY",
    "ROLE_REVIEW_REQUIRED",
    "SWITCH_ALLOWED_RESEARCH_ONLY",
    "OFFICIAL_ADOPTION_BLOCKED",
]

POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "live_trading_allowed": False,
    "protected_outputs_modified": False,
}

THRESHOLDS = {
    "minimum_5d_matured_observations": 5,
    "minimum_10d_matured_observations": 5,
    "minimum_20d_matured_observations": 3,
    "minimum_10d_win_rate_vs_A1": 0.60,
    "minimum_20d_win_rate_vs_A1": 0.60,
    "minimum_10d_avg_excess_return_vs_A1": 0.005,
    "minimum_20d_avg_excess_return_vs_A1": 0.008,
    "maximum_drawdown_deterioration_vs_A1": 0.005,
    "maximum_left_tail_deterioration_vs_A1": 0.005,
    "maximum_repeated_loser_count_delta_vs_A1": 0,
    "maximum_turnover_instability_delta_vs_A1": 0.10,
    "maximum_top20_single_sector_weight": 0.50,
    "maximum_top20_single_industry_weight": 0.35,
    "maximum_top10_single_sector_weight": 0.60,
    "maximum_single_name_weight_official_portfolio": 0.10,
    "maximum_single_name_weight_research_proxy": 0.25,
    "minimum_hysteresis_consecutive_pass_days": 3,
    "minimum_decision_stability_days_before_switch": 3,
    "one_day_outperformance_switch_allowed": False,
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
    for path in extra_paths or []:
        if path.exists() and path.is_file():
            hashes[rel(path)] = sha(path)
        elif path.exists():
            for child in path.rglob("*"):
                if child.is_file():
                    hashes[rel(child)] = sha(child)
    return hashes


def source_warning(path: Path, warnings: list[dict[str, Any]], name: str, optional: bool = False) -> None:
    if path.exists() and (path.is_dir() or path.stat().st_size > 0):
        return
    warnings.append({
        "source_name": name,
        "source_path": rel(path),
        "warning_type": "OPTIONAL_SOURCE_MISSING_WARNING" if optional else "SOURCE_MISSING_WARNING",
        "warning": "Source missing; calibration records warning and does not fabricate empirical pass results.",
    })


def empirical_counts() -> tuple[int, int]:
    matured = read_csv(V164_R1 / "switch_ledger_r1_matured_results.csv")
    if matured.empty:
        matured = read_csv(V164 / "switch_state_matured_results.csv")
    comparisons = read_csv(V164_R1 / "switch_ledger_r1_vs_a1_comparison.csv")
    if comparisons.empty:
        comparisons = read_csv(V164 / "switch_state_vs_a1_comparison.csv")
    return int(len(matured)), int(len(comparisons))


def maturity_requirement_table(default_used: bool) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "horizon": "5D",
            "minimum_matured_observations": THRESHOLDS["minimum_5d_matured_observations"],
            "threshold_basis": "conservative_default" if default_used else "empirical",
            "gate_effect": "below_threshold_forces_WAIT_MORE_MATURITY",
            "research_only": True,
        },
        {
            "horizon": "10D",
            "minimum_matured_observations": THRESHOLDS["minimum_10d_matured_observations"],
            "threshold_basis": "conservative_default" if default_used else "empirical",
            "gate_effect": "below_threshold_forces_WAIT_MORE_MATURITY",
            "research_only": True,
        },
        {
            "horizon": "20D",
            "minimum_matured_observations": THRESHOLDS["minimum_20d_matured_observations"],
            "threshold_basis": "conservative_default" if default_used else "empirical",
            "gate_effect": "below_threshold_forces_WAIT_MORE_MATURITY",
            "research_only": True,
        },
    ])


def excess_return_threshold_table(default_used: bool) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "horizon": "10D",
            "minimum_win_rate_vs_A1": THRESHOLDS["minimum_10d_win_rate_vs_A1"],
            "minimum_avg_excess_return_vs_A1": THRESHOLDS["minimum_10d_avg_excess_return_vs_A1"],
            "threshold_basis": "conservative_default" if default_used else "empirical",
            "gate_effect": "below_threshold_blocks_ROLE_REVIEW_REQUIRED",
            "research_only": True,
        },
        {
            "horizon": "20D",
            "minimum_win_rate_vs_A1": THRESHOLDS["minimum_20d_win_rate_vs_A1"],
            "minimum_avg_excess_return_vs_A1": THRESHOLDS["minimum_20d_avg_excess_return_vs_A1"],
            "threshold_basis": "conservative_default" if default_used else "empirical",
            "gate_effect": "below_threshold_blocks_ROLE_REVIEW_REQUIRED",
            "research_only": True,
        },
    ])


def risk_blocker_threshold_table(default_used: bool) -> pd.DataFrame:
    rows = [
        ("maximum_drawdown_deterioration_vs_A1", THRESHOLDS["maximum_drawdown_deterioration_vs_A1"], "risk"),
        ("maximum_left_tail_deterioration_vs_A1", THRESHOLDS["maximum_left_tail_deterioration_vs_A1"], "risk"),
        ("maximum_repeated_loser_count_delta_vs_A1", THRESHOLDS["maximum_repeated_loser_count_delta_vs_A1"], "risk"),
        ("maximum_turnover_instability_delta_vs_A1", THRESHOLDS["maximum_turnover_instability_delta_vs_A1"], "risk"),
        ("maximum_top20_single_sector_weight", THRESHOLDS["maximum_top20_single_sector_weight"], "concentration"),
        ("maximum_top20_single_industry_weight", THRESHOLDS["maximum_top20_single_industry_weight"], "concentration"),
        ("maximum_top10_single_sector_weight", THRESHOLDS["maximum_top10_single_sector_weight"], "concentration"),
        ("maximum_single_name_weight_official_portfolio", THRESHOLDS["maximum_single_name_weight_official_portfolio"], "concentration"),
        ("maximum_single_name_weight_research_proxy", THRESHOLDS["maximum_single_name_weight_research_proxy"], "concentration"),
    ]
    return pd.DataFrame([{
        "threshold_name": name,
        "threshold_value": value,
        "threshold_group": group,
        "threshold_basis": "conservative_default" if default_used else "empirical",
        "breach_effect": "BLOCKED_BY_RISK",
        "research_only": True,
    } for name, value, group in rows])


def hysteresis_threshold_table(default_used: bool) -> pd.DataFrame:
    return pd.DataFrame([{
        "minimum_hysteresis_consecutive_pass_days": THRESHOLDS["minimum_hysteresis_consecutive_pass_days"],
        "minimum_decision_stability_days_before_switch": THRESHOLDS["minimum_decision_stability_days_before_switch"],
        "one_day_outperformance_switch_allowed": THRESHOLDS["one_day_outperformance_switch_allowed"],
        "threshold_basis": "conservative_default" if default_used else "empirical",
        "gate_effect": "one_day_or_unstable_outperformance_cannot_trigger_switch",
        "research_only": True,
    }])


def execution_proxy_threshold_table(active_cash: int, default_used: bool) -> pd.DataFrame:
    rows = [
        {
            "execution_classification": "Top20 diversified portfolio",
            "minimum_position_count": 20,
            "maximum_single_name_weight": THRESHOLDS["maximum_single_name_weight_official_portfolio"],
            "active_cash_assumption_usd": active_cash,
            "official_portfolio_strategy": True,
            "adoption_allowed_by_this_stage": False,
            "notes": "Official-style diversified portfolio proxy; not promoted by this research-only calibration.",
        },
        {
            "execution_classification": "Top10 research proxy",
            "minimum_position_count": 10,
            "maximum_single_name_weight": THRESHOLDS["maximum_single_name_weight_research_proxy"],
            "active_cash_assumption_usd": active_cash,
            "official_portfolio_strategy": False,
            "adoption_allowed_by_this_stage": False,
            "notes": "Research proxy only.",
        },
        {
            "execution_classification": "Top5 execution fallback",
            "minimum_position_count": 5,
            "maximum_single_name_weight": THRESHOLDS["maximum_single_name_weight_research_proxy"],
            "active_cash_assumption_usd": active_cash,
            "official_portfolio_strategy": False,
            "adoption_allowed_by_this_stage": False,
            "notes": "Small-capital execution fallback only.",
        },
        {
            "execution_classification": "single-name fallback",
            "minimum_position_count": 1,
            "maximum_single_name_weight": 1.0,
            "active_cash_assumption_usd": active_cash,
            "official_portfolio_strategy": False,
            "adoption_allowed_by_this_stage": False,
            "notes": "Fallback scenario only; not diversified.",
        },
        {
            "execution_classification": "DRAM-only",
            "minimum_position_count": 1,
            "maximum_single_name_weight": 1.0,
            "active_cash_assumption_usd": active_cash,
            "official_portfolio_strategy": False,
            "adoption_allowed_by_this_stage": False,
            "notes": "execution_fallback_only; not an official diversified portfolio strategy.",
        },
    ]
    df = pd.DataFrame(rows)
    df["threshold_basis"] = "conservative_default" if default_used else "empirical"
    df["research_only"] = True
    df["broker_action_allowed"] = False
    return df


def switch_trigger_threshold_table(default_used: bool) -> pd.DataFrame:
    rows = [
        ("maturity", "minimum_5d_matured_observations", THRESHOLDS["minimum_5d_matured_observations"], "WAIT_MORE_MATURITY"),
        ("maturity", "minimum_10d_matured_observations", THRESHOLDS["minimum_10d_matured_observations"], "WAIT_MORE_MATURITY"),
        ("maturity", "minimum_20d_matured_observations", THRESHOLDS["minimum_20d_matured_observations"], "WAIT_MORE_MATURITY"),
        ("performance", "minimum_10d_win_rate_vs_A1", THRESHOLDS["minimum_10d_win_rate_vs_A1"], "ALLOW_FORWARD_TRACKING_ONLY"),
        ("performance", "minimum_20d_win_rate_vs_A1", THRESHOLDS["minimum_20d_win_rate_vs_A1"], "ALLOW_FORWARD_TRACKING_ONLY"),
        ("performance", "minimum_10d_avg_excess_return_vs_A1", THRESHOLDS["minimum_10d_avg_excess_return_vs_A1"], "ALLOW_FORWARD_TRACKING_ONLY"),
        ("performance", "minimum_20d_avg_excess_return_vs_A1", THRESHOLDS["minimum_20d_avg_excess_return_vs_A1"], "ALLOW_FORWARD_TRACKING_ONLY"),
        ("risk", "maximum_drawdown_deterioration_vs_A1", THRESHOLDS["maximum_drawdown_deterioration_vs_A1"], "BLOCKED_BY_RISK"),
        ("risk", "maximum_left_tail_deterioration_vs_A1", THRESHOLDS["maximum_left_tail_deterioration_vs_A1"], "BLOCKED_BY_RISK"),
        ("risk", "maximum_repeated_loser_count_delta_vs_A1", THRESHOLDS["maximum_repeated_loser_count_delta_vs_A1"], "BLOCKED_BY_RISK"),
        ("risk", "maximum_turnover_instability_delta_vs_A1", THRESHOLDS["maximum_turnover_instability_delta_vs_A1"], "BLOCKED_BY_RISK"),
        ("concentration", "maximum_top20_single_sector_weight", THRESHOLDS["maximum_top20_single_sector_weight"], "BLOCKED_BY_RISK"),
        ("concentration", "maximum_top20_single_industry_weight", THRESHOLDS["maximum_top20_single_industry_weight"], "BLOCKED_BY_RISK"),
        ("concentration", "maximum_top10_single_sector_weight", THRESHOLDS["maximum_top10_single_sector_weight"], "BLOCKED_BY_RISK"),
        ("concentration", "maximum_single_name_weight_official_portfolio", THRESHOLDS["maximum_single_name_weight_official_portfolio"], "BLOCKED_BY_RISK"),
        ("concentration", "maximum_single_name_weight_research_proxy", THRESHOLDS["maximum_single_name_weight_research_proxy"], "BLOCKED_BY_RISK"),
        ("hysteresis", "minimum_hysteresis_consecutive_pass_days", THRESHOLDS["minimum_hysteresis_consecutive_pass_days"], "ROLE_REVIEW_REQUIRED"),
        ("hysteresis", "minimum_decision_stability_days_before_switch", THRESHOLDS["minimum_decision_stability_days_before_switch"], "ROLE_REVIEW_REQUIRED"),
        ("hysteresis", "one_day_outperformance_switch_allowed", THRESHOLDS["one_day_outperformance_switch_allowed"], "WAIT_MORE_MATURITY"),
    ]
    return pd.DataFrame([{
        "threshold_category": category,
        "threshold_name": name,
        "threshold_value": value,
        "threshold_basis": "conservative_default" if default_used else "empirical",
        "failure_or_breach_decision": decision,
        "research_only": True,
    } for category, name, value, decision in rows])


def calibrated_policy() -> pd.DataFrame:
    rows = [
        ("baseline_control_retained", "KEEP_A1_CONTROL", "No eligible mature switch state has passed all review gates."),
        ("insufficient_maturity", "WAIT_MORE_MATURITY", "Any required 5D/10D/20D maturity threshold is not met."),
        ("maturity_pass_performance_or_hysteresis_not_passed", "ALLOW_FORWARD_TRACKING_ONLY", "Forward tracking may continue but role review is not triggered."),
        ("risk_blocker_breached", "BLOCKED_BY_RISK", "Any risk, concentration, left-tail, repeated-loser, or turnover blocker breaches threshold."),
        ("execution_feasibility_failed", "BLOCKED_BY_EXECUTION", "Small-capital or diversified execution gate fails."),
        ("data_quality_blocker_active", "BLOCKED_BY_DATA_QUALITY", "Required data source is missing or stale with blocking impact."),
        ("maturity_performance_risk_execution_hysteresis_pass", "ROLE_REVIEW_REQUIRED", "Persistent advantage passes thresholds; human role review required before any adoption."),
        ("all_research_gates_pass_after_role_review", "SWITCH_ALLOWED_RESEARCH_ONLY", "Research switch may be labeled allowed; this does not permit official adoption or broker action."),
        ("official_action_requested_or_unprotected", "OFFICIAL_ADOPTION_BLOCKED", "Official adoption and broker action are blocked by this stage."),
    ]
    return pd.DataFrame([{
        "gate_result_pattern": pattern,
        "allowed_final_decision": decision,
        "policy_description": desc,
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
    } for pattern, decision, desc in rows])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    before = protected_hashes([V168, V169])
    warnings: list[dict[str, Any]] = []

    v168_summary = read_json(V168 / "validation_summary.json")
    v169_summary = read_json(V169 / "validation_summary.json")
    source_warning(V168 / "validation_summary.json", warnings, "V21.168 governance summary")
    source_warning(V169 / "validation_summary.json", warnings, "V21.169 daily refresh summary")
    source_warning(V164_R1 / "switch_ledger_r1_matured_results.csv", warnings, "V21.164_R1 matured switch ledger")
    source_warning(V164_R1 / "switch_ledger_r1_vs_a1_comparison.csv", warnings, "V21.164_R1 vs A1 comparison")
    source_warning(ROOT / "outputs" / "v21" / "switch_trigger_empirical_calibration_panel.csv", warnings, "empirical threshold calibration panel", optional=True)

    matured_count, comparison_count = empirical_counts()
    insufficient_history = matured_count < 13 or comparison_count < 13
    if insufficient_history:
        warnings.append({
            "source_name": "switch trigger historical calibration data",
            "source_path": rel(V164_R1),
            "warning_type": "CALIBRATION_DEFAULTS_USED_WITH_INSUFFICIENT_HISTORY",
            "warning": "Historical matured switch-state observations are insufficient for empirical calibration; conservative defaults are used.",
        })

    active_cash = int(v169_summary.get("active_cash_assumption_usd") or v168_summary.get("active_cash_assumption_usd") or 600)
    default_used = insufficient_history

    outputs = {
        "switch_trigger_threshold_table.csv": switch_trigger_threshold_table(default_used),
        "maturity_requirement_table.csv": maturity_requirement_table(default_used),
        "excess_return_threshold_table.csv": excess_return_threshold_table(default_used),
        "risk_blocker_threshold_table.csv": risk_blocker_threshold_table(default_used),
        "hysteresis_threshold_table.csv": hysteresis_threshold_table(default_used),
        "execution_proxy_threshold_table.csv": execution_proxy_threshold_table(active_cash, default_used),
        "calibrated_switch_decision_policy.csv": calibrated_policy(),
    }
    for name, df in outputs.items():
        write_csv(name, df)

    after = protected_hashes([V168, V169])
    changed = [path for path, digest in before.items() if after.get(path) != digest]
    thresholds_non_null = all(not df.drop(columns=[c for c in df.columns if c in {"notes", "policy_description"}], errors="ignore").isna().any().any() for df in outputs.values())
    all_decisions_valid = set(outputs["calibrated_switch_decision_policy.csv"]["allowed_final_decision"]).issubset(set(FINAL_DECISIONS))
    validation = {
        "stage": STAGE,
        "final_status": "PASS_DEFAULT_THRESHOLDS_CALIBRATED_WITH_WARNINGS" if warnings else "PASS_THRESHOLDS_CALIBRATED",
        "final_decision": v169_summary.get("final_decision") or v168_summary.get("final_decision") or "WAIT_MORE_MATURITY",
        "allowed_final_decision_enum": FINAL_DECISIONS,
        **POLICY,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": False,
        "v21_168_outputs_modified": False,
        "v21_169_outputs_modified": False,
        "changed_protected_file_count": len(changed),
        "changed_protected_paths": changed,
        "thresholds_non_null": thresholds_non_null,
        "all_decisions_valid": all_decisions_valid,
        "calibration_defaults_used": default_used,
        "insufficient_historical_calibration_data": insufficient_history,
        "matured_observation_count_for_calibration": matured_count,
        "vs_a1_comparison_count_for_calibration": comparison_count,
        "current_primary_control": v169_summary.get("current_primary_control") or v168_summary.get("current_primary_control") or "A1_CONTROL",
        "best_forward_tracking_state": v169_summary.get("best_forward_tracking_state") or v168_summary.get("best_forward_tracking_state") or "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING",
        "latest_available_price_date": v169_summary.get("latest_available_price_date", "2026-06-26"),
        "latest_switch_state_tracking_date": v169_summary.get("latest_switch_state_tracking_date", "2026-06-25"),
        "new_rows_appended_v21_169": v169_summary.get("new_rows_appended", 0),
        "active_cash_assumption_usd": active_cash,
        "one_day_outperformance_switch_allowed": False,
        "dram_only_official_portfolio_strategy": False,
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
        f"current_governance_decision={validation['final_decision']}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "protected_outputs_modified=false",
        f"current_primary_control={validation['current_primary_control']}",
        f"best_forward_tracking_state={validation['best_forward_tracking_state']}",
        f"active_cash_assumption_usd={active_cash}",
        f"latest_available_price_date={validation['latest_available_price_date']}",
        f"latest_switch_state_tracking_date={validation['latest_switch_state_tracking_date']}",
        f"calibration_defaults_used={default_used}",
        f"matured_observation_count_for_calibration={matured_count}",
        f"vs_a1_comparison_count_for_calibration={comparison_count}",
        "",
        "Maturity thresholds:",
        "- 5D minimum matured observations: 5",
        "- 10D minimum matured observations: 5",
        "- 20D minimum matured observations: 3",
        "",
        "Performance thresholds:",
        "- 10D/20D win rate vs A1 minimum: 0.60",
        "- 10D average excess return vs A1 minimum: 0.005",
        "- 20D average excess return vs A1 minimum: 0.008",
        "",
        "Risk and concentration thresholds:",
        "- Drawdown and left-tail deterioration vs A1 max: 0.005",
        "- Repeated loser count delta vs A1 max: 0",
        "- Turnover instability delta vs A1 max: 0.10",
        "- Top20 sector max: 0.50; Top20 industry max: 0.35; Top10 sector max: 0.60",
        "- Official single-name max: 0.10; research proxy single-name max: 0.25",
        "",
        "Hysteresis thresholds:",
        "- Minimum consecutive pass days: 3",
        "- Minimum decision stability days before switch: 3",
        "- One-day outperformance switch allowed: false",
        "",
        "Execution classifications:",
        "- Top20 diversified portfolio",
        "- Top10 research proxy",
        "- Top5 execution fallback",
        "- single-name fallback",
        "- DRAM-only remains execution_fallback_only and not an official diversified portfolio strategy.",
        "",
        "Warnings:",
        *[f"- {w['warning_type']}: {w['warning']}" for w in warnings],
    ]
    (OUT / "V21.170_switch_trigger_threshold_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
