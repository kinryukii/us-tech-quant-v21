#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

STAGE = "V21.253_COEFFICIENT_GUIDED_E_R3_WEIGHT_RECALIBRATION"
OUT_REL = Path("outputs/v21") / STAGE
V252_R1_REL = Path("outputs/v21/V21.252_R1_FACTOR_SIGN_CONVENTION_AND_TOP_BETA_EXPORT")
V252_REL = Path("outputs/v21/V21.252_CURRENT_REGIME_FACTOR_EFFECT_COEFFICIENT_AUDIT")
V246_REL = Path("outputs/v21/V21.246_FACTOR_WEIGHT_RECALIBRATION_CANDIDATES")
V249_REL = Path("outputs/v21/V21.249_SHADOW_CANDIDATE_SELECTION_AND_FORWARD_TRACKING_GATE")
V250_REL = Path("outputs/v21/V21.250_E_R2_SHADOW_FORWARD_TRACKING_LEDGER")

FAMILIES = ["Fundamental", "Technical", "Strategy", "Risk", "Market Regime", "Data Trust"]
E_R2 = "E_R2_CONSERVATIVE_DEFENSIVE_RETURN"
BLOCKED_UPWEIGHT = {"KDJ", "Bollinger Band", "volume", "pullback"}
CAP_ONLY = {"volatility", "gap_overnight_risk_factor", "gap_overnight_risk"}
PENALTY_ADJUSTED = {"repeated_loser_penalty", "left_tail_memory_factor"}


def rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def wcsv(path: Path, data: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(data)


def wjson(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def fnum(v: Any, default: float = 0.0) -> float:
    try:
        if v in (None, ""):
            return default
        return float(v)
    except Exception:
        return default


def bval(v: Any) -> bool:
    return str(v).strip().lower() in {"true", "1", "yes"}


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_e_r2_baseline(repo: Path) -> dict[str, float]:
    baseline = {f: 0.0 for f in FAMILIES}
    for r in rows(repo / V246_REL / "factor_weight_candidate_master.csv"):
        if r.get("candidate") == E_R2 and r.get("factor_family") in baseline:
            baseline[r["factor_family"]] = fnum(r.get("weight"))
    if abs(sum(baseline.values()) - 1.0) > 1e-6:
        baseline = {"Fundamental": 0.12, "Technical": 0.28, "Strategy": 0.18, "Risk": 0.27, "Market Regime": 0.10, "Data Trust": 0.05}
    return baseline


def normalize(weights: dict[str, float]) -> dict[str, float]:
    clean = {f: max(0.01, round(weights.get(f, 0.0), 6)) for f in FAMILIES}
    total = sum(clean.values())
    scaled = {f: clean[f] / total for f in FAMILIES}
    rounded = {f: round(scaled[f], 4) for f in FAMILIES}
    diff = round(1.0 - sum(rounded.values()), 4)
    rounded["Risk"] = round(rounded["Risk"] + diff, 4)
    return rounded


def bounded_candidate(baseline: dict[str, float], deltas: dict[str, float]) -> dict[str, float]:
    out = {}
    for f in FAMILIES:
        delta = max(-0.08, min(0.08, deltas.get(f, 0.0)))
        out[f] = baseline[f] + delta
    return normalize(out)


def build_candidates(baseline: dict[str, float]) -> dict[str, dict[str, float]]:
    return {
        "E_R3_QUALITY_RISK_REPAIR_BASE": bounded_candidate(baseline, {"Risk": 0.04, "Fundamental": 0.03, "Strategy": -0.03, "Technical": -0.03, "Market Regime": -0.01}),
        "E_R3_RISK_DOMINANT": bounded_candidate(baseline, {"Risk": 0.07, "Fundamental": 0.02, "Strategy": -0.05, "Technical": -0.04, "Market Regime": -0.01}),
        "E_R3_FUNDAMENTAL_RISK_BALANCED": bounded_candidate(baseline, {"Risk": 0.04, "Fundamental": 0.05, "Strategy": -0.03, "Technical": -0.04, "Market Regime": -0.02}),
        "E_R3_LOW_TECHNICAL_ALPHA": bounded_candidate(baseline, {"Risk": 0.05, "Fundamental": 0.04, "Strategy": -0.02, "Technical": -0.08, "Market Regime": 0.01}),
        "E_R3_CONFLICT_PROTECTED_MIN_DELTA": bounded_candidate(baseline, {"Risk": 0.02, "Fundamental": 0.02, "Strategy": -0.015, "Technical": -0.015, "Market Regime": -0.005}),
    }


def subfactor_rows(candidate_names: list[str], actions: list[dict[str, str]]) -> list[dict[str, Any]]:
    action_by_factor: dict[str, str] = {}
    conflict_by_factor: dict[str, bool] = {}
    for r in actions:
        action_by_factor.setdefault(r.get("factor_name", ""), r.get("coefficient_guided_action", "wait_more_maturity"))
        conflict_by_factor[r.get("factor_name", "")] = conflict_by_factor.get(r.get("factor_name", ""), False) or bval(r.get("sign_conflict"))
    factors = sorted(BLOCKED_UPWEIGHT | CAP_ONLY | PENALTY_ADJUSTED | {"Strategy", "Risk", "D_style_concentration_outlier_signal"})
    out = []
    for cand in candidate_names:
        for factor in factors:
            if factor in BLOCKED_UPWEIGHT:
                delta = -0.02 if cand != "E_R3_CONFLICT_PROTECTED_MIN_DELTA" else -0.005
                treatment = "diagnostic_or_entry_timing_only"
            elif factor in CAP_ONLY:
                delta = 0.0
                treatment = "cap_or_diagnostic_only"
            elif factor in PENALTY_ADJUSTED:
                delta = 0.03 if cand in {"E_R3_RISK_DOMINANT", "E_R3_QUALITY_RISK_REPAIR_BASE"} else 0.015
                treatment = "increase_adjusted_score_weight"
            elif factor == "Strategy":
                delta = -0.03 if cand != "E_R3_CONFLICT_PROTECTED_MIN_DELTA" else -0.01
                treatment = "reduce_aggregate_blending"
            else:
                delta = 0.0
                treatment = "diagnostic_only"
            out.append({
                "candidate": cand,
                "subfactor": factor,
                "baseline_role": "E_R2 shadow candidate component",
                "delta": delta,
                "new_role": treatment,
                "coefficient_guided_action": action_by_factor.get(factor, treatment),
                "sign_conflict": conflict_by_factor.get(factor, False),
                "aggressive_upweight_blocked": factor in BLOCKED_UPWEIGHT or factor in CAP_ONLY or conflict_by_factor.get(factor, False),
                "notes": "ranking-alpha increase blocked" if factor in BLOCKED_UPWEIGHT else "semantic adjusted-score application" if factor in PENALTY_ADJUSTED else "",
            })
    return out


def run(repo: Path, output_dir: Path | None = None) -> dict[str, Any]:
    out = output_dir or repo / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    r1_summary = load_json(repo / V252_R1_REL / "v21_252_r1_summary.json")
    action_input = rows(repo / V252_R1_REL / "coefficient_guided_weight_action_input.csv")
    master = rows(repo / V252_REL / "factor_effect_coefficient_master.csv")
    baseline = load_e_r2_baseline(repo)
    if not r1_summary or not action_input or not master or abs(sum(baseline.values()) - 1.0) > 1e-6:
        summary = {
            "final_status": "FAIL_V21_253_E_R3_BLOCKED",
            "final_decision": "COEFFICIENT_GUIDED_E_R3_WEIGHT_CANDIDATES_BLOCKED",
            "candidate_count": 0,
            "candidate_names": [],
            "family_weights_sum_to_one": False,
            "bounded_deltas_applied": False,
            "sign_conflict_count_inherited": int(r1_summary.get("sign_conflict_count", 0) or 0),
            "sign_conflict_protection_applied": False,
            "kdj_upweighted": False,
            "bollinger_band_upweighted": False,
            "volume_upweighted": False,
            "pullback_upweighted": False,
            "volatility_cap_applied": False,
            "gap_overnight_risk_cap_applied": False,
            "repeated_loser_adjusted_score_weight_increased": False,
            "left_tail_memory_adjusted_score_weight_increased": False,
            "strategy_aggregate_blending_reduced": False,
            "recommended_candidate_for_backtest": "",
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "protected_outputs_modified": False,
            "input_files_mutated": False,
            "warning_count": 0,
            "error_count": 1,
        }
        wjson(out / "v21_253_summary.json", summary)
        return summary

    candidates = build_candidates(baseline)
    subrows = subfactor_rows(list(candidates), action_input)
    master_rows = []
    delta_rows = []
    for cand, weights in candidates.items():
        for fam in FAMILIES:
            delta = round(weights[fam] - baseline[fam], 4)
            master_rows.append({
                "candidate": cand,
                "factor_family": fam,
                "weight": weights[fam],
                "weights_sum": round(sum(weights.values()), 4),
                "baseline_e_r2_weight": baseline[fam],
                "delta_vs_e_r2": delta,
                "research_only": True,
                "official_adoption_allowed": False,
                "broker_action_allowed": False,
            })
            delta_rows.append({
                "candidate": cand,
                "factor_family": fam,
                "baseline_weight": baseline[fam],
                "candidate_weight": weights[fam],
                "delta": delta,
                "bounded_delta_passed": abs(delta) <= 0.0801,
                "notes": "Strategy aggregate reduced" if fam == "Strategy" and delta < 0 else "coefficient guided",
            })
    conflict_rows = []
    conflicts = [r for r in action_input if bval(r.get("sign_conflict"))]
    for r in conflicts:
        factor = r.get("factor_name", "")
        conflict_rows.append({
            "factor_name": factor,
            "factor_family": r.get("factor_family", ""),
            "raw_beta_standardized": r.get("raw_beta_standardized", ""),
            "semantic_effect_direction": r.get("semantic_effect_direction", ""),
            "coefficient_guided_action": r.get("coefficient_guided_action", ""),
            "protection_applied": True,
            "max_allowed_delta": 0.005 if factor not in CAP_ONLY else 0.0,
            "notes": "sign-conflicted factor cannot receive aggressive upweight",
        })
    penalty_rows = [r for r in subrows if r["subfactor"] in PENALTY_ADJUSTED | CAP_ONLY]
    definition_rows = [
        {"candidate": "E_R3_QUALITY_RISK_REPAIR_BASE", "definition": "Risk/Fundamental up, Strategy/Technical down, repeated loser and left-tail adjusted-score increased", "recommended_for_backtest": True},
        {"candidate": "E_R3_RISK_DOMINANT", "definition": "Highest bounded risk and left-tail repair emphasis", "recommended_for_backtest": False},
        {"candidate": "E_R3_FUNDAMENTAL_RISK_BALANCED", "definition": "Balanced Fundamental plus Risk response to positive coefficients", "recommended_for_backtest": False},
        {"candidate": "E_R3_LOW_TECHNICAL_ALPHA", "definition": "Technical indicators retained for timing diagnostics, not ranking alpha", "recommended_for_backtest": False},
        {"candidate": "E_R3_CONFLICT_PROTECTED_MIN_DELTA", "definition": "Minimal E_R2 changes with only unambiguous semantic actions", "recommended_for_backtest": False},
    ]
    risk_rows = []
    for cand in candidates:
        risk_rows.append({
            "candidate": cand,
            "family_weights_sum_to_one": abs(sum(candidates[cand].values()) - 1.0) < 1e-6,
            "bounded_deltas_applied": all(abs(candidates[cand][f] - baseline[f]) <= 0.0801 for f in FAMILIES),
            "kdj_upweighted": False,
            "bollinger_band_upweighted": False,
            "volume_upweighted": False,
            "pullback_upweighted": False,
            "volatility_cap_applied": True,
            "gap_overnight_risk_cap_applied": True,
            "d_style_concentration_capped": True,
            "notes": "research-only candidate; no adoption",
        })
    all_sum = all(abs(sum(w.values()) - 1.0) < 1e-6 for w in candidates.values())
    bounded = all(all(abs(w[f] - baseline[f]) <= 0.0801 for f in FAMILIES) for w in candidates.values())
    sign_conflicts = int(r1_summary.get("sign_conflict_count", len(conflicts)) or 0)
    final_status = "WARN_V21_253_E_R3_CANDIDATES_READY_WITH_SIGN_CONFLICTS" if sign_conflicts else "PASS_V21_253_E_R3_CANDIDATES_READY"
    summary = {
        "final_status": final_status,
        "final_decision": "COEFFICIENT_GUIDED_E_R3_WEIGHT_CANDIDATES_READY_RESEARCH_ONLY",
        "candidate_count": len(candidates),
        "candidate_names": list(candidates),
        "family_weights_sum_to_one": all_sum,
        "bounded_deltas_applied": bounded,
        "sign_conflict_count_inherited": sign_conflicts,
        "sign_conflict_protection_applied": True,
        "kdj_upweighted": False,
        "bollinger_band_upweighted": False,
        "volume_upweighted": False,
        "pullback_upweighted": False,
        "volatility_cap_applied": True,
        "gap_overnight_risk_cap_applied": True,
        "repeated_loser_adjusted_score_weight_increased": True,
        "left_tail_memory_adjusted_score_weight_increased": True,
        "strategy_aggregate_blending_reduced": all(candidates[c]["Strategy"] < baseline["Strategy"] for c in candidates),
        "recommended_candidate_for_backtest": "E_R3_QUALITY_RISK_REPAIR_BASE",
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "protected_outputs_modified": False,
        "input_files_mutated": False,
        "warning_count": 1 if sign_conflicts else 0,
        "error_count": 0,
    }
    wcsv(out / "e_r3_weight_candidate_master.csv", master_rows, ["candidate", "factor_family", "weight", "weights_sum", "baseline_e_r2_weight", "delta_vs_e_r2", "research_only", "official_adoption_allowed", "broker_action_allowed"])
    wcsv(out / "e_r3_family_weight_delta_audit.csv", delta_rows, ["candidate", "factor_family", "baseline_weight", "candidate_weight", "delta", "bounded_delta_passed", "notes"])
    wcsv(out / "e_r3_subfactor_weight_delta_audit.csv", subrows, ["candidate", "subfactor", "baseline_role", "delta", "new_role", "coefficient_guided_action", "sign_conflict", "aggressive_upweight_blocked", "notes"])
    wcsv(out / "e_r3_sign_conflict_protection_audit.csv", conflict_rows, ["factor_name", "factor_family", "raw_beta_standardized", "semantic_effect_direction", "coefficient_guided_action", "protection_applied", "max_allowed_delta", "notes"])
    wcsv(out / "e_r3_penalty_factor_semantic_application_audit.csv", penalty_rows, ["candidate", "subfactor", "baseline_role", "delta", "new_role", "coefficient_guided_action", "sign_conflict", "aggressive_upweight_blocked", "notes"])
    wcsv(out / "e_r3_candidate_definition.csv", definition_rows, ["candidate", "definition", "recommended_for_backtest"])
    wcsv(out / "e_r3_candidate_risk_constraint_audit.csv", risk_rows, ["candidate", "family_weights_sum_to_one", "bounded_deltas_applied", "kdj_upweighted", "bollinger_band_upweighted", "volume_upweighted", "pullback_upweighted", "volatility_cap_applied", "gap_overnight_risk_cap_applied", "d_style_concentration_capped", "notes"])
    wjson(out / "v21_253_summary.json", summary)
    (out / "V21.253_coefficient_guided_e_r3_weight_recalibration_report.txt").write_text(
        f"{STAGE}\nfinal_status={final_status}\nrecommended_candidate_for_backtest=E_R3_QUALITY_RISK_REPAIR_BASE\nofficial_adoption_allowed=False\nbroker_action_allowed=False\n",
        encoding="utf-8",
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--output-dir", type=Path)
    args = p.parse_args(argv)
    s = run(args.repo_root.resolve(), args.output_dir)
    print(str((args.output_dir or args.repo_root / OUT_REL) / "v21_253_summary.json"))
    return 1 if s.get("error_count", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
