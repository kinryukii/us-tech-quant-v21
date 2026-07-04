#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

STAGE = "V21.248_TECHNICAL_SIGNAL_FAILURE_ATTRIBUTION_AND_REPAIR_SPEC_R1"
OUT_REL = Path("outputs/v21") / STAGE
V246_REL = Path("outputs/v21/V21.246_TECHNICAL_AND_FORWARD_PANEL_BUILD_FROM_MOOMOO_CACHE_R1")
V247_REL = Path("outputs/v21/V21.247_TECHNICAL_SUBFACTOR_EFFECTIVENESS_PIT_LITE_AUDIT")
GATES = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "factor_promotion_allowed": False,
    "weight_update_allowed": False,
    "protected_outputs_modified": False,
    "market_data_fetch_allowed": False,
}
HORIZON_ORDER = {"1D": 1, "5D": 5, "10D": 10, "20D": 20}
REPAIR_BY_FAMILY = [
    ("RSI", "RSI_LOW_REVERSAL_CONTEXT_R1"),
    ("KDJ", "KDJ_LOW_GOLDEN_CROSS_R1"),
    ("BB_", "BB_PULLBACK_REENTRY_R1"),
    ("MACD", "MACD_LOW_CROSS_FILTERED_R1"),
    ("BREAKOUT", "BREAKOUT_NEXT_DAY_CONFIRM_R1"),
]


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


def fnum(v: Any, default: float = 0.0) -> float:
    try:
        if v in ("", None):
            return default
        return float(v)
    except Exception:
        return default


def load_inputs(repo: Path, v246_root: Path, v247_root: Path) -> tuple[dict[str, list[dict[str, str]]], list[str]]:
    r246 = v246_root if v246_root.is_absolute() else repo / v246_root
    r247 = v247_root if v247_root.is_absolute() else repo / v247_root
    inputs = {
        "v246_gate": read_rows(r246 / "v21_246_input_cache_gate.csv"),
        "v246_quality": read_rows(r246 / "technical_panel_quality_audit.csv"),
        "v246_forward_quality": read_rows(r246 / "forward_return_quality_audit.csv"),
        "v247_master": read_rows(r247 / "technical_subfactor_effectiveness_master.csv"),
        "v247_regime": read_rows(r247 / "technical_subfactor_effectiveness_by_regime.csv"),
        "v247_bucket": read_rows(r247 / "technical_subfactor_bucket_returns.csv"),
        "v247_redundancy": read_rows(r247 / "technical_subfactor_redundancy_audit.csv"),
        "v247_candidate": read_rows(r247 / "technical_subfactor_candidate_for_v21_248.csv"),
    }
    missing = []
    for key in ["v246_gate", "v247_master", "v247_bucket", "v247_redundancy"]:
        if not inputs[key]:
            missing.append(key)
    return inputs, missing


def sign(v: float) -> int:
    if v > 0.002:
        return 1
    if v < -0.002:
        return -1
    return 0


def direction_label(rows: list[dict[str, str]]) -> str:
    signs = [sign(fnum(r.get("mean_rank_ic"))) for r in rows]
    nz = [s for s in signs if s]
    if not nz:
        return "DIRECTION_UNSTABLE"
    if len(set(nz)) > 1:
        return "SIGN_FLIP_BY_HORIZON"
    if nz[0] < 0:
        return "DIRECTION_INVERSION_SUSPECTED"
    pos_ratio = sum(1 for r in rows if fnum(r.get("positive_rank_ic_ratio"), 0.5) >= 0.52) / max(1, len(rows))
    return "STABLE_POSITIVE" if pos_ratio >= 0.75 else "DIRECTION_UNSTABLE"


def horizon_label(rows: list[dict[str, str]]) -> str:
    vals = {r.get("forward_horizon"): abs(fnum(r.get("mean_rank_ic"))) for r in rows}
    best_h = max(vals, key=vals.get) if vals else ""
    best = vals.get(best_h, 0.0)
    if best < 0.01:
        return "NO_HORIZON_EDGE"
    if best_h == "1D":
        return "SHORT_HORIZON_ONLY" if vals.get("5D", 0) < best * 0.7 else "HORIZON_DECAY"
    if best_h in {"5D", "10D"}:
        return "MEDIUM_HORIZON_ONLY"
    return "LONG_HORIZON_ONLY"


def monotonicity_by_indicator(bucket_rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, Any]]:
    by = defaultdict(list)
    for r in bucket_rows:
        by[(r.get("technical_indicator", ""), r.get("forward_horizon", ""))].append(r)
    out = {}
    for key, rows in by.items():
        by_date = defaultdict(dict)
        for r in rows:
            by_date[r.get("asof_date", "")][int(fnum(r.get("bucket"), 0))] = fnum(r.get("bucket_forward_return"))
        scores, spreads = [], []
        for buckets in by_date.values():
            vals = [buckets.get(i, math.nan) for i in range(1, 6)]
            if any(math.isnan(v) for v in vals):
                continue
            scores.append(sum(1 for a, b in zip(vals, vals[1:]) if b >= a) / 4.0)
            spreads.append(vals[-1] - vals[0])
        out[key] = {"bucket_date_count": len(scores), "bucket_monotonicity_score": sum(scores) / len(scores) if scores else 0.0, "avg_top_minus_bottom": sum(spreads) / len(spreads) if spreads else 0.0}
    return out


def redundancy_by_indicator(rows: list[dict[str, str]]) -> dict[str, list[str]]:
    out = defaultdict(list)
    for r in rows:
        label = r.get("redundancy_label", "")
        if label not in {"HIGH_REDUNDANCY", "MEDIUM_REDUNDANCY"}:
            continue
        for side in ["indicator_a", "indicator_b"]:
            ind = r.get(side, "")
            other = r.get("indicator_b" if side == "indicator_a" else "indicator_a", "")
            if "MOMENTUM" in other:
                out[ind].append("REDUNDANT_WITH_MOMENTUM")
            if "VOLATILITY" in other:
                out[ind].append("REDUNDANT_WITH_VOLATILITY")
            if "BREAKOUT" in other or "PULLBACK" in other:
                out[ind].append("REDUNDANT_WITH_BREAKOUT")
    return out


def attribution(inputs: dict[str, list[dict[str, str]]]) -> dict[str, list[dict[str, Any]]]:
    master = inputs["v247_master"]
    buckets = monotonicity_by_indicator(inputs["v247_bucket"])
    red = redundancy_by_indicator(inputs["v247_redundancy"])
    by_ind = defaultdict(list)
    for r in master:
        by_ind[r.get("technical_indicator", "")].append(r)
    failure, horizon_rows, direction_rows, bucket_audit, keep_drop = [], [], [], [], []
    for ind, rows in sorted(by_ind.items()):
        dlabel = direction_label(rows)
        hlabel = horizon_label(rows)
        red_labels = sorted(set(red.get(ind, [])))
        for r in sorted(rows, key=lambda x: HORIZON_ORDER.get(x.get("forward_horizon"), 99)):
            key = (ind, r.get("forward_horizon", ""))
            b = buckets.get(key, {})
            labels = []
            if hlabel != "NO_HORIZON_EDGE":
                labels.append(hlabel)
            else:
                labels.append("NO_HORIZON_EDGE")
            if dlabel in {"SIGN_FLIP_BY_HORIZON", "DIRECTION_INVERSION_SUSPECTED", "DIRECTION_UNSTABLE"}:
                labels.append(dlabel)
            if b.get("bucket_date_count", 0) < 10:
                labels.append("BUCKET_SAMPLE_TOO_THIN")
            elif b.get("bucket_monotonicity_score", 0) < 0.55:
                labels.append("NON_MONOTONIC_BUCKETS")
            if abs(fnum(r.get("mean_rank_ic"))) < 0.01:
                labels.append("NOISY_SIGNAL")
            labels.extend(red_labels)
            if not labels:
                labels.append("CONTEXT_CONCENTRATED_EDGE")
            failure.append({"technical_indicator": ind, "technical_group": r.get("technical_group", ""), "forward_horizon": r.get("forward_horizon", ""), "mean_ic": fnum(r.get("mean_ic")), "mean_rank_ic": fnum(r.get("mean_rank_ic")), "hit_rate": fnum(r.get("positive_rank_ic_ratio")), "top_minus_bottom_return": b.get("avg_top_minus_bottom", fnum(r.get("top_minus_bottom_return"))), "bucket_monotonicity_score": b.get("bucket_monotonicity_score", fnum(r.get("monotonicity_score"))), "sample_count": int(fnum(r.get("observation_count"))), "coverage_ratio": fnum(r.get("coverage_ratio")), "direction_stability_label": dlabel, "horizon_stability_label": hlabel, "failure_attribution_labels": "|".join(sorted(set(labels)))})
            horizon_rows.append({"technical_indicator": ind, "forward_horizon": r.get("forward_horizon", ""), "mean_rank_ic": fnum(r.get("mean_rank_ic")), "abs_mean_rank_ic": abs(fnum(r.get("mean_rank_ic"))), "horizon_stability_label": hlabel, "sample_count": int(fnum(r.get("observation_count")))})
            bucket_audit.append({"technical_indicator": ind, "forward_horizon": r.get("forward_horizon", ""), "bucket_date_count": b.get("bucket_date_count", 0), "top_minus_bottom_return": b.get("avg_top_minus_bottom", 0.0), "bucket_monotonicity_score": b.get("bucket_monotonicity_score", 0.0), "bucket_failure_label": "NON_MONOTONIC_BUCKETS" if b.get("bucket_date_count", 0) > 0 and b.get("bucket_monotonicity_score", 0) < 0.55 else "BUCKET_SAMPLE_TOO_THIN" if b.get("bucket_date_count", 0) < 10 else "BUCKETS_OK"})
        direction_rows.append({"technical_indicator": ind, "direction_stability_label": dlabel, "positive_horizon_count": sum(1 for r in rows if fnum(r.get("mean_rank_ic")) > 0), "negative_horizon_count": sum(1 for r in rows if fnum(r.get("mean_rank_ic")) < 0), "direction_inversion_candidate": dlabel == "DIRECTION_INVERSION_SUSPECTED"})
        drop = dlabel == "DIRECTION_UNSTABLE" and hlabel == "NO_HORIZON_EDGE"
        keep_drop.append({"technical_indicator": ind, "review_action": "DROP_OR_DIAGNOSTIC_ONLY" if drop else "KEEP_FOR_REPAIR_SPEC_REVIEW", "primary_reason": f"{dlabel}|{hlabel}", "official_adoption_allowed": False, "factor_promotion_allowed": False})
    return {"failure": failure, "horizon": horizon_rows, "direction": direction_rows, "bucket": bucket_audit, "keep_drop": keep_drop}


def context_rows(inputs: dict[str, list[dict[str, str]]]) -> tuple[list[dict[str, Any]], int, int]:
    regime = inputs["v247_regime"]
    missing_fields = []
    if not regime:
        missing_fields.append("technical_subfactor_effectiveness_by_regime.csv")
        return [], 0, len(missing_fields)
    rows = []
    for r in regime:
        reg = r.get("regime", "")
        if reg == "FULL_SAMPLE":
            continue
        edge = abs(fnum(r.get("mean_rank_ic")))
        rows.append({"technical_indicator": r.get("technical_indicator", ""), "forward_horizon": r.get("forward_horizon", ""), "context_bucket": reg, "mean_rank_ic": fnum(r.get("mean_rank_ic")), "positive_rank_ic_ratio": fnum(r.get("positive_rank_ic_ratio")), "observation_count": int(fnum(r.get("observation_count"))), "context_effect_label": "CONTEXT_EDGE" if edge >= 0.02 else "NO_CONTEXT_EDGE", "missing_context_fields": ""})
    candidates = sum(1 for r in rows if r["context_effect_label"] == "CONTEXT_EDGE")
    return rows, candidates, 0


def repair_candidates(attr: dict[str, list[dict[str, Any]]], context: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_ind = defaultdict(list)
    for r in attr["failure"]:
        by_ind[r["technical_indicator"]].append(r)
    context_edge = {r["technical_indicator"] for r in context if r["context_effect_label"] == "CONTEXT_EDGE"}
    out = []
    used_labels = set()
    for ind, rows in by_ind.items():
        labels = "|".join(r["failure_attribution_labels"] for r in rows)
        best = max(rows, key=lambda r: abs(fnum(r["mean_rank_ic"])))
        sufficient = best["sample_count"] >= 1000 and (abs(best["mean_rank_ic"]) >= 0.01 or ind in context_edge or "DIRECTION_INVERSION_SUSPECTED" in labels)
        if not sufficient:
            continue
        repair = None
        for token, label in REPAIR_BY_FAMILY:
            if token in ind:
                repair = label
                break
        if repair is None and ("MOMENTUM" in ind or "DISTANCE" in ind):
            repair = "TECHNICAL_COMPOSITE_TIMING_R1"
        if repair and repair not in used_labels:
            used_labels.add(repair)
            out.append({"repair_candidate_label": repair, "source_indicator": ind, "best_forward_horizon": best["forward_horizon"], "evidence_basis": labels, "repair_spec": spec_for(repair), "research_only": True, "official_adoption_allowed": False, "factor_promotion_allowed": False, "weight_update_allowed": False})
    return out


def spec_for(label: str) -> str:
    return {
        "RSI_LOW_REVERSAL_CONTEXT_R1": "Test RSI only in oversold reversal/context buckets; verify inverse direction before scoring.",
        "KDJ_LOW_GOLDEN_CROSS_R1": "Require low-zone KDJ cross confirmation and exclude high redundancy regimes.",
        "BB_PULLBACK_REENTRY_R1": "Convert Bollinger signal to pullback re-entry timing overlay, not daily alpha.",
        "MACD_LOW_CROSS_FILTERED_R1": "Use MACD cross only after low momentum filter and confirm next-day follow-through.",
        "BREAKOUT_NEXT_DAY_CONFIRM_R1": "Require breakout persistence on next trading row to reduce false positives.",
        "TECHNICAL_COMPOSITE_TIMING_R1": "Combine non-redundant timing signals with volatility/momentum context gates.",
    }.get(label, "Research-only repair specification.")


def redundancy_rows(inputs: dict[str, list[dict[str, str]]]) -> list[dict[str, Any]]:
    out = []
    for r in inputs["v247_redundancy"]:
        a, b = r.get("indicator_a", ""), r.get("indicator_b", "")
        label = r.get("redundancy_label", "")
        attr = ""
        joined = f"{a}|{b}"
        if "MOMENTUM" in joined:
            attr = "REDUNDANT_WITH_MOMENTUM"
        elif "VOLATILITY" in joined:
            attr = "REDUNDANT_WITH_VOLATILITY"
        elif "BREAKOUT" in joined or "PULLBACK" in joined:
            attr = "REDUNDANT_WITH_BREAKOUT"
        else:
            attr = "NO_MAJOR_REDUNDANCY_FAMILY"
        out.append({"indicator_a": a, "indicator_b": b, "spearman_corr": fnum(r.get("spearman_corr")), "redundancy_label": label, "redundancy_attribution": attr})
    return out


def fail_summary(missing: list[str], out: Path) -> dict[str, Any]:
    return {"final_status": "FAIL_V21_248_TECHNICAL_ATTRIBUTION_INPUT_MISSING", "final_decision": "TECHNICAL_ATTRIBUTION_BLOCKED_INPUT_MISSING", "technical_indicator_count": 0, "tested_indicator_count": 0, "horizon_count": 0, "context_bucket_count": 0, "failure_attribution_row_count": 0, "repair_candidate_count": 0, "context_conditioned_candidate_count": 0, "direction_inversion_candidate_count": 0, "timing_overlay_candidate_count": 0, "missing_input_count": len(missing), "missing_context_field_count": 0, **GATES}


def run(repo: Path, output_dir: Path | None = None, v246_root: Path = V246_REL, v247_root: Path = V247_REL) -> dict[str, Any]:
    out = output_dir or repo / OUT_REL
    inputs, missing = load_inputs(repo, v246_root, v247_root)
    if missing or not inputs["v247_master"]:
        summary = fail_summary(missing or ["empty_effectiveness"], out)
        write_outputs(out, {}, [], [], summary)
        return summary
    attr = attribution(inputs)
    context, context_candidate_count, missing_context = context_rows(inputs)
    red = redundancy_rows(inputs)
    repairs = repair_candidates(attr, context)
    indicators = sorted({r.get("technical_indicator", "") for r in inputs["v247_master"]})
    horizons = sorted({r.get("forward_horizon", "") for r in inputs["v247_master"]})
    repair_count = len(repairs)
    if repair_count >= 3:
        status = "PASS_V21_248_TECHNICAL_REPAIR_SPEC_READY"
        decision = "TECHNICAL_REPAIR_SPEC_READY_FOR_V21_249_RESEARCH_ONLY"
    elif repair_count >= 1:
        status = "PARTIAL_PASS_V21_248_TECHNICAL_FAILURE_ATTRIBUTION_READY_MIXED"
        decision = "TECHNICAL_ATTRIBUTION_READY_LIMITED_REPAIR_SPEC"
    else:
        status = "WARN_V21_248_TECHNICAL_SIGNALS_REMAIN_WEAK"
        decision = "TECHNICAL_ATTRIBUTION_COMPLETE_NO_REPAIR_CANDIDATE"
    summary = {"final_status": status, "final_decision": decision, "technical_indicator_count": len(indicators), "tested_indicator_count": len(indicators), "horizon_count": len(horizons), "context_bucket_count": len({r["context_bucket"] for r in context}), "failure_attribution_row_count": len(attr["failure"]), "repair_candidate_count": repair_count, "context_conditioned_candidate_count": context_candidate_count, "direction_inversion_candidate_count": sum(1 for r in attr["direction"] if r["direction_inversion_candidate"]), "timing_overlay_candidate_count": sum(1 for r in repairs if "TIMING" in r["repair_candidate_label"] or "CONFIRM" in r["repair_candidate_label"]), "missing_input_count": 0, "missing_context_field_count": missing_context, **GATES}
    write_outputs(out, attr, context, red, summary, repairs)
    return summary


def write_outputs(out: Path, attr: dict[str, list[dict[str, Any]]] | dict[Any, Any], context: list[dict[str, Any]], red: list[dict[str, Any]], summary: dict[str, Any], repairs: list[dict[str, Any]] | None = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    repairs = repairs or []
    if not attr:
        attr = {"failure": [], "horizon": [], "direction": [], "bucket": [], "keep_drop": []}
    write_csv(out / "technical_indicator_failure_attribution.csv", attr["failure"], ["technical_indicator", "technical_group", "forward_horizon", "mean_ic", "mean_rank_ic", "hit_rate", "top_minus_bottom_return", "bucket_monotonicity_score", "sample_count", "coverage_ratio", "direction_stability_label", "horizon_stability_label", "failure_attribution_labels"])
    write_csv(out / "technical_horizon_attribution.csv", attr["horizon"], ["technical_indicator", "forward_horizon", "mean_rank_ic", "abs_mean_rank_ic", "horizon_stability_label", "sample_count"])
    write_csv(out / "technical_direction_attribution.csv", attr["direction"], ["technical_indicator", "direction_stability_label", "positive_horizon_count", "negative_horizon_count", "direction_inversion_candidate"])
    write_csv(out / "technical_bucket_monotonicity_audit.csv", attr["bucket"], ["technical_indicator", "forward_horizon", "bucket_date_count", "top_minus_bottom_return", "bucket_monotonicity_score", "bucket_failure_label"])
    write_csv(out / "technical_context_conditioned_effectiveness.csv", context, ["technical_indicator", "forward_horizon", "context_bucket", "mean_rank_ic", "positive_rank_ic_ratio", "observation_count", "context_effect_label", "missing_context_fields"])
    write_csv(out / "technical_redundancy_attribution.csv", red, ["indicator_a", "indicator_b", "spearman_corr", "redundancy_label", "redundancy_attribution"])
    write_csv(out / "technical_repair_candidate_spec.csv", repairs, ["repair_candidate_label", "source_indicator", "best_forward_horizon", "evidence_basis", "repair_spec", "research_only", "official_adoption_allowed", "factor_promotion_allowed", "weight_update_allowed"])
    write_csv(out / "technical_keep_drop_review.csv", attr["keep_drop"], ["technical_indicator", "review_action", "primary_reason", "official_adoption_allowed", "factor_promotion_allowed"])
    write_json(out / "v21_248_summary.json", summary)
    (out / "V21.248_technical_signal_failure_attribution_report.txt").write_text(f"{STAGE}\nfinal_status={summary['final_status']}\nfinal_decision={summary['final_decision']}\nresearch_only=True\nofficial_adoption_allowed=False\nbroker_action_allowed=False\nfactor_promotion_allowed=False\nweight_update_allowed=False\nmarket_data_fetch_allowed=False\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--output-dir", type=Path)
    p.add_argument("--v21-246-root", type=Path, default=V246_REL)
    p.add_argument("--v21-247-root", type=Path, default=V247_REL)
    a = p.parse_args(argv)
    s = run(a.repo_root.resolve(), a.output_dir, a.v21_246_root, a.v21_247_root)
    for k in ["final_status", "final_decision", "technical_indicator_count", "tested_indicator_count", "horizon_count", "failure_attribution_row_count", "repair_candidate_count", "context_conditioned_candidate_count", "direction_inversion_candidate_count", "timing_overlay_candidate_count", "missing_input_count", "missing_context_field_count", "official_adoption_allowed", "broker_action_allowed", "factor_promotion_allowed", "weight_update_allowed", "market_data_fetch_allowed"]:
        print(f"{k}={s.get(k)}")
    return 1 if str(s.get("final_status", "")).startswith("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
