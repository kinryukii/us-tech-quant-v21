#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

STAGE = "V21.252_R1_FACTOR_SIGN_CONVENTION_AND_TOP_BETA_EXPORT"
OUT_REL = Path("outputs/v21") / STAGE
V252_REL = Path("outputs/v21/V21.252_CURRENT_REGIME_FACTOR_EFFECT_COEFFICIENT_AUDIT")
PENALTY_FACTORS = {"repeated_loser_penalty", "left_tail_memory_factor", "volatility", "gap_overnight_risk_factor", "gap_overnight_risk", "event_proximity_risk_factor"}
AUDIT_FACTORS = PENALTY_FACTORS | {"Strategy", "Risk", "KDJ", "Bollinger Band", "volume", "pullback"}
HIGHER_WORSE = {"volatility", "gap_overnight_risk_factor", "gap_overnight_risk", "event_proximity_risk_factor"}
ALREADY_ADJUSTED = {"repeated_loser_penalty", "left_tail_memory_factor"}


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


def sign_convention(factor: str, family: str) -> str:
    if factor in ALREADY_ADJUSTED:
        return "already_adjusted_score"
    if factor in HIGHER_WORSE:
        return "higher_is_worse"
    if factor.endswith("_penalty"):
        return "penalty_factor"
    if family == "Risk" and factor not in {"Risk"}:
        return "higher_is_worse"
    if factor in {"Strategy", "Risk", "KDJ", "Bollinger Band", "volume", "pullback"}:
        return "higher_is_better"
    return "higher_is_better" if factor else "unknown"


def semantic_direction(raw_beta: float, convention: str) -> str:
    if convention in {"higher_is_better", "already_adjusted_score"}:
        if raw_beta > 0:
            return "positive_higher_score_helped"
        if raw_beta < 0:
            return "negative_higher_score_hurt"
        return "neutral"
    if convention in {"higher_is_worse", "penalty_factor"}:
        if raw_beta > 0:
            return "negative_more_risk_was_rewarded_conflict"
        if raw_beta < 0:
            return "positive_lower_risk_preferred"
        return "neutral"
    return "unknown"


def adjusted_action(raw_action: str, raw_beta: float, convention: str) -> str:
    if convention in {"higher_is_worse", "penalty_factor"}:
        if raw_beta > 0:
            return "cap_or_diagnostic_only"
        if raw_beta < 0:
            return "increase_penalty_or_risk_control"
    if convention == "already_adjusted_score":
        if raw_beta > 0:
            return "increase_adjusted_score_weight"
        if raw_beta < 0:
            return "decrease_or_cap_adjusted_score_weight"
    if raw_action in {"increase", "decrease", "cap", "keep", "diagnostic_only", "wait_more_maturity"}:
        return raw_action
    return "wait_more_maturity"


def is_conflict(raw_beta: float, convention: str, semantic: str) -> bool:
    if convention in {"higher_is_worse", "penalty_factor"} and raw_beta > 0:
        return True
    if convention == "unknown":
        return True
    return "conflict" in semantic


def required_present(master: list[dict[str, str]]) -> bool:
    required = {"factor_name", "factor_family", "forward_window", "topn_scope", "source_mode", "beta_standardized", "recommended_action"}
    return bool(master) and required.issubset(set(master[0].keys()))


def run(repo: Path, output_dir: Path | None = None) -> dict[str, Any]:
    out = output_dir or repo / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    master = rows(repo / V252_REL / "factor_effect_coefficient_master.csv")
    posneg = rows(repo / V252_REL / "factor_positive_negative_effect_summary.csv")
    recs = rows(repo / V252_REL / "factor_weight_adjustment_recommendation.csv")
    matrix = rows(repo / V252_REL / "strategy_factor_exposure_effect_matrix.csv")
    if not required_present(master) or not posneg or not recs or not matrix:
        summary = {
            "final_status": "FAIL_V21_252_R1_BLOCKED",
            "final_decision": "FACTOR_SIGN_CONVENTION_AND_TOP_BETA_EXPORT_BLOCKED",
            "factor_count_loaded": 0,
            "top_positive_factor_names": [],
            "top_negative_factor_names": [],
            "penalty_factor_count": 0,
            "sign_conflict_count": 0,
            "repeated_loser_penalty_semantic_action": "",
            "left_tail_memory_semantic_action": "",
            "volatility_semantic_action": "",
            "gap_overnight_risk_semantic_action": "",
            "e_r2_top_positive_coefficients": [],
            "e_r2_top_negative_coefficients": [],
            "new_factor_lite_top_positive_coefficients": [],
            "coefficient_guided_reweighting_ready": False,
            "warning_count": 0,
            "error_count": 1,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "protected_outputs_modified": False,
            "input_files_mutated": False,
        }
        wjson(out / "v21_252_r1_summary.json", summary)
        return summary

    enriched = []
    for r in master:
        factor = r.get("factor_name", "")
        family = r.get("factor_family", "")
        beta = fnum(r.get("beta_standardized"))
        convention = sign_convention(factor, family)
        semantic = semantic_direction(beta, convention)
        action = adjusted_action(r.get("recommended_action", ""), beta, convention)
        enriched.append({
            **r,
            "factor_sign_convention": convention,
            "raw_beta_standardized": beta,
            "semantic_effect_direction": semantic,
            "adjusted_weight_action": action,
            "sign_conflict": is_conflict(beta, convention, semantic),
        })

    pos = sorted(enriched, key=lambda r: fnum(r.get("beta_standardized")), reverse=True)
    neg = sorted(enriched, key=lambda r: fnum(r.get("beta_standardized")))
    pos_export = [{**r, "leaderboard_rank": i} for i, r in enumerate(pos, 1)]
    neg_export = [{**r, "leaderboard_rank": i} for i, r in enumerate(neg, 1)]

    audit = []
    semantic_rows = []
    penalty_rows = []
    for r in enriched:
        row = {
            "factor_name": r.get("factor_name", ""),
            "factor_family": r.get("factor_family", ""),
            "factor_subtype": r.get("factor_subtype", ""),
            "forward_window": r.get("forward_window", ""),
            "topn_scope": r.get("topn_scope", ""),
            "source_mode": r.get("source_mode", ""),
            "factor_sign_convention": r["factor_sign_convention"],
            "raw_beta_standardized": r["raw_beta_standardized"],
            "raw_beta_sign": r.get("beta_sign", ""),
            "semantic_effect_direction": r["semantic_effect_direction"],
            "raw_recommended_action": r.get("recommended_action", ""),
            "adjusted_weight_action": r["adjusted_weight_action"],
            "sign_conflict": r["sign_conflict"],
            "notes": "raw coefficient preserved; semantic action is for V21.253 input only",
        }
        semantic_rows.append(row)
        if r.get("factor_name") in AUDIT_FACTORS:
            audit.append(row)
        if r["factor_sign_convention"] in {"higher_is_worse", "penalty_factor", "already_adjusted_score"}:
            penalty_rows.append(row)

    matrix_lookup = {}
    for r in matrix:
        key = (r.get("strategy"), r.get("factor_name"), r.get("forward_window"), r.get("topn_scope"), r.get("source_mode"))
        matrix_lookup.setdefault(key, r)

    def strategy_table(strategy: str) -> list[dict[str, Any]]:
        out_rows = []
        for r in enriched:
            key = (strategy, r.get("factor_name"), r.get("forward_window"), r.get("topn_scope"), r.get("source_mode"))
            m = matrix_lookup.get(key, {})
            out_rows.append({
                "strategy": strategy,
                "factor_name": r.get("factor_name", ""),
                "forward_window": r.get("forward_window", ""),
                "topn_scope": r.get("topn_scope", ""),
                "source_mode": r.get("source_mode", ""),
                "raw_beta_standardized": r["raw_beta_standardized"],
                "semantic_effect_direction": r["semantic_effect_direction"],
                "average_factor_exposure_z": m.get("average_factor_exposure_z", ""),
                "estimated_contribution": m.get("estimated_contribution", ""),
                "adjusted_weight_action": r["adjusted_weight_action"],
                "sign_conflict": r["sign_conflict"],
            })
        return out_rows

    action_input = []
    for r in enriched:
        action_input.append({
            "factor_name": r.get("factor_name", ""),
            "factor_family": r.get("factor_family", ""),
            "forward_window": r.get("forward_window", ""),
            "topn_scope": r.get("topn_scope", ""),
            "source_mode": r.get("source_mode", ""),
            "raw_beta_standardized": r["raw_beta_standardized"],
            "factor_sign_convention": r["factor_sign_convention"],
            "semantic_effect_direction": r["semantic_effect_direction"],
            "coefficient_guided_action": r["adjusted_weight_action"],
            "sign_conflict": r["sign_conflict"],
            "official_adoption_allowed": False,
            "broker_action_allowed": False,
        })

    master_fields = list(master[0].keys())
    pos_fields = ["leaderboard_rank"] + master_fields + ["factor_sign_convention", "raw_beta_standardized", "semantic_effect_direction", "adjusted_weight_action", "sign_conflict"]
    semantic_fields = ["factor_name", "factor_family", "factor_subtype", "forward_window", "topn_scope", "source_mode", "factor_sign_convention", "raw_beta_standardized", "raw_beta_sign", "semantic_effect_direction", "raw_recommended_action", "adjusted_weight_action", "sign_conflict", "notes"]
    strategy_fields = ["strategy", "factor_name", "forward_window", "topn_scope", "source_mode", "raw_beta_standardized", "semantic_effect_direction", "average_factor_exposure_z", "estimated_contribution", "adjusted_weight_action", "sign_conflict"]
    action_fields = ["factor_name", "factor_family", "forward_window", "topn_scope", "source_mode", "raw_beta_standardized", "factor_sign_convention", "semantic_effect_direction", "coefficient_guided_action", "sign_conflict", "official_adoption_allowed", "broker_action_allowed"]
    wcsv(out / "factor_top_positive_beta_leaderboard.csv", pos_export, pos_fields)
    wcsv(out / "factor_top_negative_beta_leaderboard.csv", neg_export, pos_fields)
    wcsv(out / "factor_sign_convention_audit.csv", audit, semantic_fields)
    wcsv(out / "factor_semantic_effect_interpretation.csv", semantic_rows, semantic_fields)
    wcsv(out / "penalty_factor_direction_audit.csv", penalty_rows, semantic_fields)
    wcsv(out / "e_r2_exact_factor_coefficient_table.csv", strategy_table("E_R2_CONSERVATIVE_DEFENSIVE_RETURN"), strategy_fields)
    wcsv(out / "new_factor_lite_exact_factor_coefficient_table.csv", strategy_table("NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL"), strategy_fields)
    wcsv(out / "a1_left_tail_exact_factor_coefficient_table.csv", strategy_table("A1"), strategy_fields)
    wcsv(out / "coefficient_guided_weight_action_input.csv", action_input, action_fields)

    def first_action(factor: str) -> str:
        candidates = [r for r in semantic_rows if r["factor_name"] == factor]
        return candidates[0]["adjusted_weight_action"] if candidates else ""

    conflicts = sum(1 for r in semantic_rows if r["sign_conflict"])
    final_status = "WARN_V21_252_R1_SIGN_CONFLICT_REVIEW_REQUIRED" if conflicts else "PASS_V21_252_R1_COEFFICIENT_EXPORT_READY"
    summary = {
        "final_status": final_status,
        "final_decision": "FACTOR_SIGN_CONVENTION_AND_TOP_BETA_EXPORT_READY_RESEARCH_ONLY",
        "factor_count_loaded": len({r.get("factor_name") for r in master}),
        "top_positive_factor_names": [r.get("factor_name", "") for r in pos[:10]],
        "top_negative_factor_names": [r.get("factor_name", "") for r in neg[:10]],
        "penalty_factor_count": len(penalty_rows),
        "sign_conflict_count": conflicts,
        "repeated_loser_penalty_semantic_action": first_action("repeated_loser_penalty"),
        "left_tail_memory_semantic_action": first_action("left_tail_memory_factor"),
        "volatility_semantic_action": first_action("volatility"),
        "gap_overnight_risk_semantic_action": first_action("gap_overnight_risk_factor") or first_action("gap_overnight_risk"),
        "e_r2_top_positive_coefficients": [r["factor_name"] for r in sorted(strategy_table("E_R2_CONSERVATIVE_DEFENSIVE_RETURN"), key=lambda x: fnum(x["raw_beta_standardized"]), reverse=True)[:5]],
        "e_r2_top_negative_coefficients": [r["factor_name"] for r in sorted(strategy_table("E_R2_CONSERVATIVE_DEFENSIVE_RETURN"), key=lambda x: fnum(x["raw_beta_standardized"]))[:5]],
        "new_factor_lite_top_positive_coefficients": [r["factor_name"] for r in sorted(strategy_table("NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL"), key=lambda x: fnum(x["raw_beta_standardized"]), reverse=True)[:5]],
        "coefficient_guided_reweighting_ready": True,
        "warning_count": 1 if conflicts else 0,
        "error_count": 0,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "protected_outputs_modified": False,
        "input_files_mutated": False,
    }
    wjson(out / "v21_252_r1_summary.json", summary)
    (out / "V21.252_R1_factor_sign_convention_top_beta_report.txt").write_text(
        f"{STAGE}\nfinal_status={final_status}\nsign_conflict_count={conflicts}\nofficial_adoption_allowed=False\nbroker_action_allowed=False\n",
        encoding="utf-8",
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--output-dir", type=Path)
    args = p.parse_args(argv)
    s = run(args.repo_root.resolve(), args.output_dir)
    print(str((args.output_dir or args.repo_root / OUT_REL) / "v21_252_r1_summary.json"))
    return 1 if s.get("error_count", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
