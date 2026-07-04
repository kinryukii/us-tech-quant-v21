#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

STAGE = "V21.249_TECHNICAL_REPAIR_SPEC_PIT_RETEST_R1"
OUT_REL = Path("outputs/v21") / STAGE
V246_REL = Path("outputs/v21/V21.246_TECHNICAL_AND_FORWARD_PANEL_BUILD_FROM_MOOMOO_CACHE_R1")
V247_REL = Path("outputs/v21/V21.247_TECHNICAL_SUBFACTOR_EFFECTIVENESS_PIT_LITE_AUDIT")
V248_REL = Path("outputs/v21/V21.248_TECHNICAL_SIGNAL_FAILURE_ATTRIBUTION_AND_REPAIR_SPEC_R1")
HORIZONS = ["1D", "5D", "10D", "20D"]
REQUIRED_CANDIDATES = [
    "RSI_LOW_REVERSAL_CONTEXT_R1",
    "KDJ_LOW_GOLDEN_CROSS_R1",
    "BB_PULLBACK_REENTRY_R1",
    "MACD_LOW_CROSS_FILTERED_R1",
    "BREAKOUT_NEXT_DAY_CONFIRM_R1",
    "TECHNICAL_COMPOSITE_TIMING_R1",
]
GATES = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "factor_promotion_allowed": False,
    "weight_update_allowed": False,
    "ranking_mutation_allowed": False,
    "protected_outputs_modified": False,
    "market_data_fetch_allowed": False,
}


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


def load_inputs(repo: Path, v246_root: Path, v247_root: Path, v248_root: Path) -> tuple[Path, Path, Path, list[dict[str, str]], list[str]]:
    r246 = v246_root if v246_root.is_absolute() else repo / v246_root
    r247 = v247_root if v247_root.is_absolute() else repo / v247_root
    r248 = v248_root if v248_root.is_absolute() else repo / v248_root
    missing = []
    for root, key in [(r246, "V21.246"), (r247, "V21.247"), (r248, "V21.248")]:
        if not root.exists():
            missing.append(key)
    if not (r246 / "technical_subfactor_panel_wide.csv").exists() or not (r246 / "forward_return_panel_aligned.csv").exists():
        missing.append("V21.246_panel")
    if not (r247 / "technical_subfactor_effectiveness_master.csv").exists():
        missing.append("V21.247_effectiveness")
    specs = read_rows(r248 / "technical_repair_candidate_spec.csv")
    if not specs:
        missing.append("V21.248_repair_candidate_spec")
    return r246, r247, r248, specs, missing


def load_panel(r246: Path, candidates: list[str]) -> pd.DataFrame:
    wide_path = r246 / "technical_subfactor_panel_wide.csv"
    fwd_path = r246 / "forward_return_panel_aligned.csv"
    head = pd.read_csv(wide_path, nrows=0)
    needed = set(["asof_date", "ticker"])
    for c in ["RSI_14", "KDJ_K_9_3_3", "KDJ_D_9_3_3", "KDJ_J_9_3_3", "MACD_DIF_12_26", "MACD_DEA_9", "MACD_HIST_12_26_9", "BB_PCTB_20", "PULLBACK_FROM_20D_HIGH", "BREAKOUT_20", "MOMENTUM_20", "MOMENTUM_60", "VOLATILITY_20", "DISTANCE_TO_MA20", "VOLUME_RATIO_20"]:
        if c in head.columns:
            needed.add(c)
    wide = pd.read_csv(wide_path, usecols=lambda c: c in needed)
    fwd_cols = ["asof_date", "ticker"]
    for h in HORIZONS:
        fwd_cols.extend([f"forward_return_{h.lower()}", f"maturity_{h.lower()}"])
    fwd = pd.read_csv(fwd_path, usecols=lambda c: c in fwd_cols)
    df = wide.merge(fwd, on=["asof_date", "ticker"], how="left")
    for c in df.columns:
        if c not in {"asof_date", "ticker"}:
            if c.startswith("maturity_"):
                df[c] = df[c].astype(str).str.lower().isin({"true", "1", "yes"})
            else:
                df[c] = pd.to_numeric(df[c], errors="coerce")
    df["asof_date"] = pd.to_datetime(df["asof_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return df


def cs_rank(df: pd.DataFrame, col: str, ascending: bool = True) -> pd.Series:
    return df.groupby("asof_date")[col].rank(pct=True, ascending=ascending)


def add_repaired_signals(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    out = df.copy()
    missing: dict[str, str] = {}
    def req(cols: list[str], name: str) -> bool:
        miss = [c for c in cols if c not in out.columns]
        if miss:
            missing[name] = "|".join(miss)
            out[name] = math.nan
            return False
        return True
    if req(["RSI_14", "MOMENTUM_20"], "RSI_LOW_REVERSAL_CONTEXT_R1"):
        out["RSI_LOW_REVERSAL_CONTEXT_R1"] = (1 - cs_rank(out, "RSI_14")) * (1 - cs_rank(out, "MOMENTUM_20"))
    if req(["KDJ_K_9_3_3", "KDJ_D_9_3_3", "KDJ_J_9_3_3"], "KDJ_LOW_GOLDEN_CROSS_R1"):
        cross = (out["KDJ_K_9_3_3"] - out["KDJ_D_9_3_3"])
        out["KDJ_LOW_GOLDEN_CROSS_R1"] = cs_rank(out.assign(_cross=cross), "_cross") * (1 - cs_rank(out, "KDJ_J_9_3_3"))
    if req(["BB_PCTB_20", "PULLBACK_FROM_20D_HIGH"], "BB_PULLBACK_REENTRY_R1"):
        out["BB_PULLBACK_REENTRY_R1"] = (1 - (out["BB_PCTB_20"] - 0.5).abs() * 2).clip(lower=0) * (1 - cs_rank(out, "PULLBACK_FROM_20D_HIGH"))
    if req(["MACD_DIF_12_26", "MACD_DEA_9", "MOMENTUM_20"], "MACD_LOW_CROSS_FILTERED_R1"):
        macd_cross = out["MACD_DIF_12_26"] - out["MACD_DEA_9"]
        out["MACD_LOW_CROSS_FILTERED_R1"] = cs_rank(out.assign(_macd=macd_cross), "_macd") * (1 - cs_rank(out, "MOMENTUM_20"))
    if req(["BREAKOUT_20", "MOMENTUM_20"], "BREAKOUT_NEXT_DAY_CONFIRM_R1"):
        out["BREAKOUT_NEXT_DAY_CONFIRM_R1"] = cs_rank(out, "BREAKOUT_20") * cs_rank(out, "MOMENTUM_20")
    if req(["RSI_14", "MOMENTUM_20", "VOLATILITY_20", "BREAKOUT_20"], "TECHNICAL_COMPOSITE_TIMING_R1"):
        out["TECHNICAL_COMPOSITE_TIMING_R1"] = ((1 - cs_rank(out, "RSI_14")) + cs_rank(out, "MOMENTUM_20") + (1 - cs_rank(out, "VOLATILITY_20")) + cs_rank(out, "BREAKOUT_20")) / 4.0
    return out, missing


def corr(x: pd.Series, y: pd.Series, rank: bool = False) -> float:
    z = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(z) < 10 or z["x"].nunique() < 2 or z["y"].nunique() < 2:
        return math.nan
    if rank:
        return float(z["x"].rank().corr(z["y"].rank()))
    return float(z["x"].corr(z["y"]))


def bucket_stats(g: pd.DataFrame, sig: str, ret: str) -> tuple[float, float, int, int, int]:
    z = g[[sig, ret]].dropna()
    if len(z) < 20 or z[sig].nunique() < 5:
        return math.nan, math.nan, 0, 0, 0
    try:
        z["bucket"] = pd.qcut(z[sig], 5, labels=False, duplicates="drop") + 1
    except Exception:
        return math.nan, math.nan, 0, 0, 0
    if z["bucket"].nunique() < 5:
        return math.nan, math.nan, 0, 0, 0
    means = z.groupby("bucket", observed=True)[ret].mean()
    vals = [float(means.get(i, math.nan)) for i in range(1, 6)]
    mono = sum(1 for a, b in zip(vals, vals[1:]) if pd.notna(a) and pd.notna(b) and b >= a) / 4.0
    spread = vals[-1] - vals[0]
    return spread, mono, len(z), sum(1 for v in vals if pd.notna(v) and v > 0), sum(1 for v in vals if pd.notna(v) and v < 0)


def raw_for_candidate(candidate: str) -> str:
    return {
        "RSI_LOW_REVERSAL_CONTEXT_R1": "RSI_14",
        "KDJ_LOW_GOLDEN_CROSS_R1": "KDJ_J_9_3_3",
        "BB_PULLBACK_REENTRY_R1": "BB_PCTB_20",
        "MACD_LOW_CROSS_FILTERED_R1": "MACD_DIF_12_26",
        "BREAKOUT_NEXT_DAY_CONFIRM_R1": "BREAKOUT_20",
        "TECHNICAL_COMPOSITE_TIMING_R1": "MOMENTUM_20",
    }.get(candidate, "")


def evaluate(df: pd.DataFrame, candidates: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    rows, buckets, raw_cmp, inc = [], [], [], []
    proxy_cols = [c for c in ["MOMENTUM_20", "VOLATILITY_20", "BREAKOUT_20"] if c in df.columns]
    for cand in candidates:
        if cand not in df.columns:
            continue
        raw = raw_for_candidate(cand)
        for h in HORIZONS:
            ret, mat = f"forward_return_{h.lower()}", f"maturity_{h.lower()}"
            valid = df[df[mat] & df[cand].notna() & df[ret].notna()]
            daily = []
            for _, g in valid.groupby("asof_date"):
                daily.append(corr(g[cand], g[ret], rank=True))
            daily = [x for x in daily if pd.notna(x)]
            mean_ic = sum(daily) / len(daily) if daily else math.nan
            pos_ratio = sum(1 for x in daily if x > 0) / len(daily) if daily else math.nan
            hit = float((valid[ret] > 0).mean()) if len(valid) else math.nan
            spread, mono, bcnt, posb, negb = bucket_stats(valid, cand, ret)
            pass_flag = bool(pd.notna(mean_ic) and mean_ic > 0.015 and pos_ratio >= 0.53 and (pd.isna(mono) or mono >= 0.50))
            rows.append({"repair_candidate": cand, "forward_horizon": h, "row_count": len(valid), "coverage_ratio": len(valid) / max(1, len(df)), "ic_mean": mean_ic, "ic_sign": "POSITIVE" if mean_ic > 0 else "NEGATIVE" if mean_ic < 0 else "ZERO", "ic_sign_consistency": pos_ratio, "hit_rate": hit, "top_bottom_bucket_spread": spread, "bucket_monotonicity_score": mono, "bucket_sample_count": bcnt, "positive_bucket_count": posb, "negative_bucket_count": negb, "horizon_pass_flag": pass_flag})
            buckets.append({"repair_candidate": cand, "forward_horizon": h, "top_bottom_bucket_spread": spread, "bucket_monotonicity_score": mono, "bucket_sample_count": bcnt, "positive_bucket_count": posb, "negative_bucket_count": negb, "bucket_status": "PASS" if pd.notna(mono) and mono >= 0.5 else "WARN_NON_MONOTONIC_OR_THIN"})
            if raw and raw in df.columns:
                raw_ic = corr(valid[raw], valid[ret], rank=True)
                raw_spread, _, _, _, _ = bucket_stats(valid, raw, ret)
                raw_cmp.append({"repair_candidate": cand, "raw_signal": raw, "forward_horizon": h, "repaired_ic": mean_ic, "raw_ic": raw_ic, "repaired_minus_raw_ic": mean_ic - raw_ic if pd.notna(mean_ic) and pd.notna(raw_ic) else math.nan, "repaired_top_bottom_spread": spread, "raw_top_bottom_spread": raw_spread, "repaired_minus_raw_top_bottom_spread": spread - raw_spread if pd.notna(spread) and pd.notna(raw_spread) else math.nan, "repaired_improvement_label": improvement_label(mean_ic, raw_ic, spread, raw_spread)})
            proxy_corr = max([abs(corr(valid[cand], valid[p], rank=True)) for p in proxy_cols] or [0])
            edge = "INCREMENTAL_EDGE_CONFIRMED" if pd.notna(mean_ic) and mean_ic > 0.02 and proxy_corr < 0.65 else "WEAK_INCREMENTAL_EDGE" if pd.notna(mean_ic) and mean_ic > 0.01 else "REDUNDANT_BUT_USEFUL_TIMING" if proxy_corr >= 0.65 and pd.notna(mean_ic) and mean_ic > 0 else "NEGATIVE_INCREMENTAL_EDGE" if pd.notna(mean_ic) and mean_ic < 0 else "REDUNDANT_NO_EDGE"
            inc.append({"repair_candidate": cand, "forward_horizon": h, "momentum_proxy_available": "MOMENTUM_20" in proxy_cols, "volatility_proxy_available": "VOLATILITY_20" in proxy_cols, "breakout_proxy_available": "BREAKOUT_20" in proxy_cols, "max_abs_proxy_rank_corr": proxy_corr, "incremental_edge_label": edge})
    return rows, buckets, raw_cmp, inc


def improvement_label(repaired_ic: float, raw_ic: float, repaired_spread: float, raw_spread: float) -> str:
    di = repaired_ic - raw_ic if pd.notna(repaired_ic) and pd.notna(raw_ic) else 0
    ds = repaired_spread - raw_spread if pd.notna(repaired_spread) and pd.notna(raw_spread) else 0
    if di > 0.01 and ds > 0:
        return "REPAIR_IMPROVED"
    if di < -0.01:
        return "REPAIR_WORSE"
    return "MIXED_OR_FLAT"


def summarize_roles(retest: list[dict[str, Any]], inc: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by = {}
    inc_by = {}
    for r in retest:
        by.setdefault(r["repair_candidate"], []).append(r)
    for r in inc:
        inc_by.setdefault(r["repair_candidate"], []).append(r)
    role_rows, keep_rows = [], []
    for cand, rows in by.items():
        pass_count = sum(1 for r in rows if r["horizon_pass_flag"])
        best = max(rows, key=lambda r: fnum(r["ic_mean"], -999))
        edge_labels = [r["incremental_edge_label"] for r in inc_by.get(cand, [])]
        if pass_count >= 2 and "INCREMENTAL_EDGE_CONFIRMED" in edge_labels:
            label, role = "REPAIR_CANDIDATE_PASS", "TIMING_OVERLAY_CANDIDATE"
        elif pass_count >= 1:
            label, role = "REPAIR_CANDIDATE_PARTIAL", "CONTEXT_FILTER_CANDIDATE"
        elif any(fnum(r["ic_mean"]) > 0 for r in rows):
            label, role = "REPAIR_CANDIDATE_WEAK", "DIAGNOSTIC_ONLY"
        else:
            label, role = "REPAIR_CANDIDATE_FAIL", "DROP_FROM_NEXT_ROUND"
        role_rows.append({"repair_candidate": cand, "candidate_level_label": label, "role_recommendation": role, "best_forward_horizon": best["forward_horizon"], "best_ic_mean": best["ic_mean"], "passed_horizon_count": pass_count, "official_adoption_allowed": False, "factor_promotion_allowed": False})
        keep_rows.append({"repair_candidate": cand, "keep_drop_decision": "KEEP_FOR_V21_250_RESEARCH" if role in {"TIMING_OVERLAY_CANDIDATE", "CONTEXT_FILTER_CANDIDATE"} else "DROP_OR_DIAGNOSTIC_ONLY", "reason": f"{label}|{role}", "research_only": True})
    return role_rows, keep_rows


def fail_summary(missing: list[str], out: Path) -> dict[str, Any]:
    return {"final_status": "FAIL_V21_249_TECHNICAL_REPAIR_RETEST_INPUT_MISSING", "final_decision": "TECHNICAL_REPAIR_RETEST_BLOCKED_INPUT_MISSING", "repair_candidate_count": 0, "tested_repair_candidate_count": 0, "passed_repair_candidate_count": 0, "partial_repair_candidate_count": 0, "weak_repair_candidate_count": 0, "failed_repair_candidate_count": 0, "timing_overlay_candidate_count": 0, "context_filter_candidate_count": 0, "diagnostic_only_count": 0, "drop_from_next_round_count": 0, "horizon_count": 0, "total_retest_rows": 0, "total_bucket_rows": 0, "raw_comparison_available_count": 0, "incremental_edge_confirmed_count": 0, "weak_incremental_edge_count": 0, "redundant_but_useful_timing_count": 0, "redundant_no_edge_count": 0, "negative_incremental_edge_count": 0, "missing_input_count": len(missing), "missing_signal_field_count": 0, "missing_forward_return_field_count": 0, **GATES}


def run(repo: Path, output_dir: Path | None = None, v246_root: Path = V246_REL, v247_root: Path = V247_REL, v248_root: Path = V248_REL) -> dict[str, Any]:
    out = output_dir or repo / OUT_REL
    r246, r247, r248, specs, missing = load_inputs(repo, v246_root, v247_root, v248_root)
    if missing:
        summary = fail_summary(missing, out)
        write_outputs(out, [], [], [], [], [], [], summary)
        return summary
    candidates = [r.get("repair_candidate_label", "") for r in specs if r.get("repair_candidate_label") in REQUIRED_CANDIDATES]
    if not candidates:
        summary = fail_summary(["empty_repair_candidate_spec"], out)
        write_outputs(out, [], [], [], [], [], [], summary)
        return summary
    df = load_panel(r246, candidates)
    df, missing_signals = add_repaired_signals(df)
    tested = [c for c in candidates if c in df.columns and c not in missing_signals]
    retest, buckets, raw_cmp, inc = evaluate(df, tested)
    roles, keep = summarize_roles(retest, inc)
    passed = sum(1 for r in roles if r["candidate_level_label"] == "REPAIR_CANDIDATE_PASS")
    partial = sum(1 for r in roles if r["candidate_level_label"] == "REPAIR_CANDIDATE_PARTIAL")
    weak = sum(1 for r in roles if r["candidate_level_label"] == "REPAIR_CANDIDATE_WEAK")
    failed = sum(1 for r in roles if r["candidate_level_label"] == "REPAIR_CANDIDATE_FAIL")
    inc_counts = {k: sum(1 for r in inc if r["incremental_edge_label"] == k) for k in ["INCREMENTAL_EDGE_CONFIRMED", "WEAK_INCREMENTAL_EDGE", "REDUNDANT_BUT_USEFUL_TIMING", "REDUNDANT_NO_EDGE", "NEGATIVE_INCREMENTAL_EDGE"]}
    if passed >= 2 and inc_counts["INCREMENTAL_EDGE_CONFIRMED"] >= 1:
        status, decision = "PASS_V21_249_TECHNICAL_REPAIR_PIT_RETEST_READY", "TECHNICAL_REPAIR_RETEST_READY_RESEARCH_ONLY"
    elif passed == 1 or partial > 0:
        status, decision = "PARTIAL_PASS_V21_249_TECHNICAL_REPAIR_SIGNAL_MIXED", "TECHNICAL_REPAIR_RETEST_MIXED_CONTINUE_RESEARCH"
    else:
        status, decision = "WARN_V21_249_TECHNICAL_REPAIR_EDGE_WEAK", "TECHNICAL_REPAIR_EDGE_WEAK_DIAGNOSTIC_ONLY"
    summary = {"final_status": status, "final_decision": decision, "repair_candidate_count": len(candidates), "tested_repair_candidate_count": len(tested), "passed_repair_candidate_count": passed, "partial_repair_candidate_count": partial, "weak_repair_candidate_count": weak, "failed_repair_candidate_count": failed, "timing_overlay_candidate_count": sum(1 for r in roles if r["role_recommendation"] == "TIMING_OVERLAY_CANDIDATE"), "context_filter_candidate_count": sum(1 for r in roles if r["role_recommendation"] == "CONTEXT_FILTER_CANDIDATE"), "diagnostic_only_count": sum(1 for r in roles if r["role_recommendation"] == "DIAGNOSTIC_ONLY"), "drop_from_next_round_count": sum(1 for r in roles if r["role_recommendation"] == "DROP_FROM_NEXT_ROUND"), "horizon_count": 4, "total_retest_rows": len(retest), "total_bucket_rows": len(buckets), "raw_comparison_available_count": len(raw_cmp), "incremental_edge_confirmed_count": inc_counts["INCREMENTAL_EDGE_CONFIRMED"], "weak_incremental_edge_count": inc_counts["WEAK_INCREMENTAL_EDGE"], "redundant_but_useful_timing_count": inc_counts["REDUNDANT_BUT_USEFUL_TIMING"], "redundant_no_edge_count": inc_counts["REDUNDANT_NO_EDGE"], "negative_incremental_edge_count": inc_counts["NEGATIVE_INCREMENTAL_EDGE"], "missing_input_count": 0, "missing_signal_field_count": len(missing_signals), "missing_forward_return_field_count": 0, **GATES}
    write_outputs(out, retest, buckets, raw_cmp, inc, roles, keep, summary)
    return summary


def write_outputs(out: Path, retest: list[dict[str, Any]], buckets: list[dict[str, Any]], raw_cmp: list[dict[str, Any]], inc: list[dict[str, Any]], roles: list[dict[str, Any]], keep: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "technical_repair_candidate_pit_retest.csv", retest, ["repair_candidate", "forward_horizon", "row_count", "coverage_ratio", "ic_mean", "ic_sign", "ic_sign_consistency", "hit_rate", "top_bottom_bucket_spread", "bucket_monotonicity_score", "bucket_sample_count", "positive_bucket_count", "negative_bucket_count", "horizon_pass_flag"])
    write_csv(out / "technical_repair_candidate_horizon_summary.csv", retest, ["repair_candidate", "forward_horizon", "row_count", "coverage_ratio", "ic_mean", "ic_sign", "ic_sign_consistency", "hit_rate", "horizon_pass_flag"])
    write_csv(out / "technical_repair_vs_raw_comparison.csv", raw_cmp, ["repair_candidate", "raw_signal", "forward_horizon", "repaired_ic", "raw_ic", "repaired_minus_raw_ic", "repaired_top_bottom_spread", "raw_top_bottom_spread", "repaired_minus_raw_top_bottom_spread", "repaired_improvement_label"])
    write_csv(out / "technical_repair_incremental_edge_audit.csv", inc, ["repair_candidate", "forward_horizon", "momentum_proxy_available", "volatility_proxy_available", "breakout_proxy_available", "max_abs_proxy_rank_corr", "incremental_edge_label"])
    write_csv(out / "technical_repair_bucket_monotonicity_audit.csv", buckets, ["repair_candidate", "forward_horizon", "top_bottom_bucket_spread", "bucket_monotonicity_score", "bucket_sample_count", "positive_bucket_count", "negative_bucket_count", "bucket_status"])
    write_csv(out / "technical_repair_role_recommendation.csv", roles, ["repair_candidate", "candidate_level_label", "role_recommendation", "best_forward_horizon", "best_ic_mean", "passed_horizon_count", "official_adoption_allowed", "factor_promotion_allowed"])
    write_csv(out / "technical_repair_keep_drop_review.csv", keep, ["repair_candidate", "keep_drop_decision", "reason", "research_only"])
    write_json(out / "v21_249_summary.json", summary)
    (out / "V21.249_technical_repair_spec_pit_retest_report.txt").write_text(f"{STAGE}\nfinal_status={summary['final_status']}\nfinal_decision={summary['final_decision']}\nresearch_only=True\nofficial_adoption_allowed=False\nbroker_action_allowed=False\nfactor_promotion_allowed=False\nweight_update_allowed=False\nmarket_data_fetch_allowed=False\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--output-dir", type=Path)
    p.add_argument("--v21-246-root", type=Path, default=V246_REL)
    p.add_argument("--v21-247-root", type=Path, default=V247_REL)
    p.add_argument("--v21-248-root", type=Path, default=V248_REL)
    a = p.parse_args(argv)
    s = run(a.repo_root.resolve(), a.output_dir, a.v21_246_root, a.v21_247_root, a.v21_248_root)
    for k in ["final_status", "final_decision", "repair_candidate_count", "tested_repair_candidate_count", "passed_repair_candidate_count", "partial_repair_candidate_count", "weak_repair_candidate_count", "failed_repair_candidate_count", "timing_overlay_candidate_count", "context_filter_candidate_count", "diagnostic_only_count", "drop_from_next_round_count", "horizon_count", "total_retest_rows", "incremental_edge_confirmed_count", "official_adoption_allowed", "broker_action_allowed", "factor_promotion_allowed", "weight_update_allowed", "market_data_fetch_allowed"]:
        print(f"{k}={s.get(k)}")
    return 1 if str(s.get("final_status", "")).startswith("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
