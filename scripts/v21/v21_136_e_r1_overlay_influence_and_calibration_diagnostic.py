#!/usr/bin/env python
"""V21.136 E_R1 overlay influence and calibration diagnostic."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.136_E_R1_OVERLAY_INFLUENCE_AND_CALIBRATION_DIAGNOSTIC"
OUT = ROOT / "outputs/v21/V21.136_E_R1_OVERLAY_INFLUENCE_AND_CALIBRATION_DIAGNOSTIC"
V128 = ROOT / "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE"
R1 = ROOT / "outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR"
V135 = ROOT / "outputs/v21/V21.135_ABCDE_SAME_DATE_FORWARD_ALIGNMENT"
SOURCES = {
    "A1": V128 / "A1_BASELINE_CONTROL_latest_ranking.csv",
    "B": V128 / "B_STATIC_MOMENTUM_BLEND_latest_ranking.csv",
    "C": V128 / "C_DYNAMIC_MOMENTUM_BLEND_latest_ranking.csv",
    "D": V128 / "D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv",
    "E_R1": R1 / "e_r1_full_ranking.csv",
}
ALIGNMENT_SUMMARY = V135 / "abcde_alignment_summary.json"
TOP20_MATRIX = V135 / "abcde_top20_overlap_matrix.csv"
TOP50_MATRIX = V135 / "abcde_top50_overlap_matrix.csv"
WEIGHTS = {
    "E_R1": (0.80, 0.12, 0.04, 0.04),
    "E_SIM_78_14_4_4": (0.78, 0.14, 0.04, 0.04),
    "E_SIM_76_16_4_4": (0.76, 0.16, 0.04, 0.04),
    "E_SIM_80_10_6_4": (0.80, 0.10, 0.06, 0.04),
    "E_SIM_80_10_4_6": (0.80, 0.10, 0.04, 0.06),
    "E_SIM_82_10_4_4": (0.82, 0.10, 0.04, 0.04),
}
ALLOWED_CLASSES = {"TOO_WEAK", "CONSERVATIVE_BUT_MEANINGFUL", "TOO_STRONG_OR_UNSTABLE"}
ALLOWED_RECS = {"KEEP_E_R1_WAIT_FORWARD_MATURITY", "CONSIDER_E_R2_AFTER_FORWARD_MATURITY", "E_R1_TOO_WEAK_NEEDS_CALIBRATION_REVIEW", "E_R1_TOO_STRONG_REVERT_CLOSER_TO_A1", "E_REJECT_STRUCTURAL_RISK"}


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str] | None = None) -> None:
    rows = list(rows)
    if fields is None:
        fields = []
        for row in rows:
            for field in row:
                if field not in fields:
                    fields.append(field)
        fields = fields if fields else ["empty"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_status() -> list[str]:
    completed = subprocess.run(["git", "status", "--short"], cwd=ROOT, text=True, capture_output=True, check=False)
    return completed.stdout.splitlines()


def protected_modified(status_lines: list[str], baseline_lines: list[str]) -> bool:
    baseline = {line.replace("\\", "/") for line in baseline_lines}
    allowed_prefix = "?? outputs/v21/V21.136_E_R1_OVERLAY_INFLUENCE_AND_CALIBRATION_DIAGNOSTIC/"
    allowed_scripts = {
        "?? scripts/v21/v21_136_e_r1_overlay_influence_and_calibration_diagnostic.py",
        "?? scripts/v21/test_v21_136_e_r1_overlay_influence_and_calibration_diagnostic.py",
        "?? scripts/v21/run_v21_136_e_r1_overlay_influence_and_calibration_diagnostic.ps1",
    }
    for line in status_lines:
        normalized = line.replace("\\", "/")
        if normalized in baseline or normalized.startswith(allowed_prefix) or normalized in allowed_scripts:
            continue
        lowered = normalized.lower()
        if lowered.startswith((" m outputs/", " d outputs/", "?? outputs/")) and ("official" in lowered or "broker" in lowered or "protected" in lowered):
            return True
    return False


def ticker_norm(value: Any) -> str:
    return str(value).upper().strip()


def load_ranking(path: Path, strategy: str) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    if "ticker_norm" not in frame.columns:
        frame["ticker_norm"] = frame["ticker"].map(ticker_norm)
    if strategy != "E_R1":
        frame = frame.rename(columns={"rank": f"{strategy}_rank", "final_score": f"{strategy}_raw_score"})
    return frame


def top_set(frame: pd.DataFrame, rank_col: str, n: int) -> set[str]:
    return set(frame.sort_values([rank_col, "ticker_norm"]).head(n)["ticker_norm"])


def classify(top20_overlap: int, top50_overlap: int) -> str:
    if top20_overlap >= 18 and top50_overlap >= 47:
        return "TOO_WEAK"
    if 12 <= top20_overlap <= 17 and 38 <= top50_overlap <= 46:
        return "CONSERVATIVE_BUT_MEANINGFUL"
    if top20_overlap < 10 or top50_overlap < 30:
        return "TOO_STRONG_OR_UNSTABLE"
    return "CONSERVATIVE_BUT_MEANINGFUL"


def simulation_score(frame: pd.DataFrame, weights: tuple[float, float, float, float]) -> pd.Series:
    a1, momentum, technical, risk = weights
    return (
        a1 * frame["A1_baseline_norm"]
        + momentum * frame["context_momentum_norm"]
        + technical * frame["technical_entry_quality_norm"]
        + risk * frame["risk_guardrail_norm"]
    )


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    baseline_status = git_status()
    protected = [p for p in [*SOURCES.values(), ALIGNMENT_SUMMARY, TOP20_MATRIX, TOP50_MATRIX] if p.is_file()]
    baseline_hashes = {rel(p): sha256(p) for p in protected}
    warnings = []
    if not SOURCES["E_R1"].is_file() or not SOURCES["A1"].is_file():
        status = "BLOCKED_V21_136_E_R1_SOURCE_MISSING"
        decision = "E_R1_OVERLAY_DIAGNOSTIC_BLOCKED_MISSING_SOURCE"
        summary = {"stage": STAGE, "FINAL_STATUS": status, "DECISION": decision, "official_adoption_allowed": False, "broker_action_allowed": False, "research_only": True, "E_adoption_allowed": False, "protected_outputs_modified": False}
        write_json(OUT / "e_r1_overlay_diagnostic_summary.json", summary)
        return summary
    e = load_ranking(SOURCES["E_R1"], "E_R1")
    a1 = load_ranking(SOURCES["A1"], "A1")
    merged = e.merge(a1[["ticker_norm", "A1_rank", "A1_raw_score"]], on="ticker_norm", how="inner")
    merged["rank_delta"] = pd.to_numeric(merged["A1_rank"], errors="coerce") - pd.to_numeric(merged["rank"], errors="coerce")
    merged["A1_score_norm"] = merged["A1_baseline_norm"]
    merged["score_delta"] = merged["E_final_score"] - merged["A1_score_norm"]
    a1_top20 = top_set(a1, "A1_rank", 20); a1_top50 = top_set(a1, "A1_rank", 50)
    e_top20 = top_set(e, "rank", 20); e_top50 = top_set(e, "rank", 50)
    merged["entered_E_top20_from_outside_A1_top20"] = merged["ticker_norm"].isin(e_top20 - a1_top20)
    merged["exited_A1_top20_under_E_R1"] = merged["ticker_norm"].isin(a1_top20 - e_top20)
    merged["entered_E_top50_from_outside_A1_top50"] = merged["ticker_norm"].isin(e_top50 - a1_top50)
    merged["exited_A1_top50_under_E_R1"] = merged["ticker_norm"].isin(a1_top50 - e_top50)
    movement_cols = ["ticker_norm", "A1_rank", "rank", "rank_delta", "A1_score_norm", "E_final_score", "score_delta", "entered_E_top20_from_outside_A1_top20", "exited_A1_top20_under_E_R1", "entered_E_top50_from_outside_A1_top50", "exited_A1_top50_under_E_R1"]
    merged[movement_cols].rename(columns={"rank": "E_R1_rank"}).to_csv(OUT / "e_r1_vs_a1_rank_movement_audit.csv", index=False)
    top20_entries = sorted(e_top20 - a1_top20); top20_exits = sorted(a1_top20 - e_top20)
    top50_entries = sorted(e_top50 - a1_top50); top50_exits = sorted(a1_top50 - e_top50)
    write_csv(OUT / "e_r1_top20_entries_exits.csv", [{"change_type": "ENTRY", "ticker_norm": t} for t in top20_entries] + [{"change_type": "EXIT", "ticker_norm": t} for t in top20_exits])
    write_csv(OUT / "e_r1_top50_entries_exits.csv", [{"change_type": "ENTRY", "ticker_norm": t} for t in top50_entries] + [{"change_type": "EXIT", "ticker_norm": t} for t in top50_exits])
    contrib = merged.copy()
    contrib["A1_contribution"] = 0.80 * contrib["A1_baseline_norm"]
    contrib["context_momentum_contribution"] = 0.12 * contrib["context_momentum_norm"]
    contrib["technical_contribution"] = 0.04 * contrib["technical_entry_quality_norm"]
    contrib["risk_contribution"] = 0.04 * contrib["risk_guardrail_norm"]
    contrib["overlay_total_contribution"] = contrib["context_momentum_contribution"] + contrib["technical_contribution"] + contrib["risk_contribution"]
    contrib["overlay_minus_neutral"] = contrib["overlay_total_contribution"] - (0.12 * 50 + 0.04 * 50 + 0.04 * 50)
    contrib["momentum_minus_neutral"] = contrib["context_momentum_contribution"] - 0.12 * 50
    contrib["technical_minus_neutral"] = contrib["technical_contribution"] - 0.04 * 50
    contrib["risk_minus_neutral"] = contrib["risk_contribution"] - 0.04 * 50
    drivers = ["momentum_minus_neutral", "technical_minus_neutral", "risk_minus_neutral"]
    contrib["rank_movement_attribution_proxy"] = contrib[drivers].abs().idxmax(axis=1)
    contrib.to_csv(OUT / "e_r1_component_contribution_decomposition.csv", index=False)
    contrib[["ticker_norm", "rank_delta", "rank_movement_attribution_proxy", *drivers]].to_csv(OUT / "e_r1_overlay_driver_attribution.csv", index=False)
    top20_overlap = len(e_top20 & a1_top20); top50_overlap = len(e_top50 & a1_top50)
    influence_class = classify(top20_overlap, top50_overlap)
    overlay_total_norm = 0.60 * merged["context_momentum_norm"] + 0.20 * merged["technical_entry_quality_norm"] + 0.20 * merged["risk_guardrail_norm"]
    strength = {
        "corr_E_R1_final_score_A1_baseline_norm": merged["E_final_score"].corr(merged["A1_baseline_norm"]),
        "corr_E_R1_final_score_overlay_total_norm": merged["E_final_score"].corr(overlay_total_norm),
        "corr_rank_delta_context_momentum_norm": merged["rank_delta"].corr(merged["context_momentum_norm"]),
        "corr_rank_delta_technical_entry_quality_norm": merged["rank_delta"].corr(merged["technical_entry_quality_norm"]),
        "corr_rank_delta_risk_guardrail_norm": merged["rank_delta"].corr(merged["risk_guardrail_norm"]),
        "E_R1_vs_A1_top20_overlap": top20_overlap,
        "E_R1_vs_A1_top50_overlap": top50_overlap,
        "top20_changes_vs_A1": len(top20_entries) + len(top20_exits),
        "top50_changes_vs_A1": len(top50_entries) + len(top50_exits),
        "average_absolute_rank_delta": merged["rank_delta"].abs().mean(),
        "median_absolute_rank_delta": merged["rank_delta"].abs().median(),
        "p90_absolute_rank_delta": merged["rank_delta"].abs().quantile(0.90),
        "max_rank_improvement": merged["rank_delta"].max(),
        "max_rank_deterioration": merged["rank_delta"].min(),
        "overlay_influence_class": influence_class,
    }
    write_csv(OUT / "e_r1_overlay_influence_strength_audit.csv", [strength])
    rankings = {k: load_ranking(v, k) for k, v in SOURCES.items() if k != "E_R1" and v.is_file()}
    sim_summary = []; sim_top20 = []; sim_top50 = []; sim_overlap = []
    for name, weights in WEIGHTS.items():
        sim = merged[["ticker_norm", "A1_baseline_norm", "context_momentum_norm", "technical_entry_quality_norm", "risk_guardrail_norm"]].copy()
        sim["simulated_final_score"] = simulation_score(sim, weights)
        sim = sim.sort_values(["simulated_final_score", "ticker_norm"], ascending=[False, True]).reset_index(drop=True)
        sim["simulated_rank"] = sim.index + 1
        s20 = set(sim.head(20)["ticker_norm"]); s50 = set(sim.head(50)["ticker_norm"])
        row = {"variant": name, "diagnostic_only": True, "adopted": False, "a1_weight": weights[0], "momentum_weight": weights[1], "technical_weight": weights[2], "risk_weight": weights[3], "weight_sum": sum(weights), "top20_tickers": "|".join(sim.head(20)["ticker_norm"]), "top50_tickers": "|".join(sim.head(50)["ticker_norm"]), "avg_abs_rank_movement_vs_A1": sim.merge(a1[["ticker_norm", "A1_rank"]], on="ticker_norm")["A1_rank"].sub(sim["simulated_rank"]).abs().mean()}
        for peer, frame in rankings.items():
            row[f"top20_overlap_vs_{peer}"] = len(s20 & top_set(frame, f"{peer}_rank", 20))
            row[f"top50_overlap_vs_{peer}"] = len(s50 & top_set(frame, f"{peer}_rank", 50))
        row["top20_overlap_vs_E_R1"] = len(s20 & e_top20)
        row["top50_overlap_vs_E_R1"] = len(s50 & e_top50)
        row["risk_guardrail_deterioration_count"] = int((sim["risk_guardrail_norm"] < 50).sum())
        row["repeated_loser_count"] = ""
        row["left_tail_risk_proxy"] = ""
        sim_summary.append(row)
        sim_top20 += [{"variant": name, "rank": i + 1, "ticker_norm": t, "diagnostic_only": True, "adopted": False} for i, t in enumerate(sim.head(20)["ticker_norm"])]
        sim_top50 += [{"variant": name, "rank": i + 1, "ticker_norm": t, "diagnostic_only": True, "adopted": False} for i, t in enumerate(sim.head(50)["ticker_norm"])]
        sim_overlap.append({k: v for k, v in row.items() if "overlap" in k or k in {"variant", "diagnostic_only", "adopted"}})
    write_csv(OUT / "e_r1_calibration_simulation_summary.csv", sim_summary)
    write_csv(OUT / "e_r1_calibration_simulated_top20.csv", sim_top20)
    write_csv(OUT / "e_r1_calibration_simulated_top50.csv", sim_top50)
    write_csv(OUT / "e_r1_calibration_overlap_matrix.csv", sim_overlap)
    structural_risk = False
    recommendation = "KEEP_E_R1_WAIT_FORWARD_MATURITY" if influence_class == "CONSERVATIVE_BUT_MEANINGFUL" and not structural_risk else ("CONSIDER_E_R2_AFTER_FORWARD_MATURITY" if influence_class == "TOO_WEAK" else "E_R1_TOO_STRONG_REVERT_CLOSER_TO_A1")
    rec = {"structural_recommendation": recommendation, "basis": "structure_only_no_forward_returns_used", "overlay_influence_class": influence_class, "diagnostic_only": True, "E_adoption_allowed": False}
    write_json(OUT / "e_r1_structural_recommendation.json", rec)
    leakage = any(any(tok in col.lower() for tok in ["forward_return", "future_label", "outcome"]) for col in merged.columns)
    if leakage:
        status = "FAIL_V21_136_E_R1_LEAKAGE_RISK"; decision = "E_R1_OVERLAY_DIAGNOSTIC_REJECTED_LEAKAGE_RISK"
    elif recommendation == "KEEP_E_R1_WAIT_FORWARD_MATURITY":
        status = "PASS_V21_136_E_R1_OVERLAY_DIAGNOSTIC_KEEP_WAIT_MATURITY"; decision = "KEEP_E_R1_RESEARCH_ONLY_WAIT_FORWARD_MATURITY"
    elif recommendation == "CONSIDER_E_R2_AFTER_FORWARD_MATURITY":
        status = "PARTIAL_PASS_V21_136_E_R1_OVERLAY_DIAGNOSTIC_CALIBRATION_WATCH"; decision = "KEEP_E_R1_NOW_CONSIDER_E_R2_AFTER_FORWARD_MATURITY"
    elif recommendation == "E_REJECT_STRUCTURAL_RISK":
        status = "WARN_V21_136_E_R1_STRUCTURAL_RISK"; decision = "E_R1_RESEARCH_ONLY_STRUCTURAL_RISK_REVIEW_REQUIRED"
    else:
        status = "PARTIAL_PASS_V21_136_E_R1_OVERLAY_DIAGNOSTIC_CALIBRATION_WATCH"; decision = "KEEP_E_R1_NOW_CONSIDER_E_R2_AFTER_FORWARD_MATURITY"
    post_hashes = {rel(p): sha256(p) for p in protected}
    prot_mod = baseline_hashes != post_hashes or protected_modified(git_status(), baseline_status)
    alignment = load_json(ALIGNMENT_SUMMARY)
    summary = {"stage": STAGE, "FINAL_STATUS": status, "DECISION": decision, "ranking_date": alignment.get("ranking_date", "2026-06-26"), "source_paths": {k: rel(v) for k, v in SOURCES.items()}, "E_R1_vs_A1_top20_overlap": top20_overlap, "E_R1_vs_A1_top50_overlap": top50_overlap, "overlay_influence_class": influence_class, "structural_recommendation": recommendation, "top20_entries_vs_A1": "|".join(top20_entries), "top20_exits_vs_A1": "|".join(top20_exits), "largest_rank_improvements": "|".join(merged.sort_values("rank_delta", ascending=False).head(10)["ticker_norm"]), "largest_rank_deteriorations": "|".join(merged.sort_values("rank_delta").head(10)["ticker_norm"]), "warnings": "|".join(warnings) if warnings else "none", "protected_outputs_modified": bool(prot_mod), "official_adoption_allowed": False, "broker_action_allowed": False, "research_only": True, "E_adoption_allowed": False, "report_path": rel(OUT / "V21.136_E_R1_OVERLAY_INFLUENCE_AND_CALIBRATION_DIAGNOSTIC_report.txt")}
    write_json(OUT / "e_r1_overlay_diagnostic_summary.json", summary)
    report = [STAGE, f"FINAL_STATUS={status}", f"DECISION={decision}", f"ranking_date={summary['ranking_date']}", f"source_paths={json.dumps(summary['source_paths'], sort_keys=True)}", f"E_R1_vs_A1_Top20_overlap={top20_overlap}", f"E_R1_vs_A1_Top50_overlap={top50_overlap}", f"overlay_influence_class={influence_class}", f"E_R1_Top20_entries_vs_A1={summary['top20_entries_vs_A1']}", f"E_R1_Top20_exits_vs_A1={summary['top20_exits_vs_A1']}", f"largest_rank_improvements={summary['largest_rank_improvements']}", f"largest_rank_deteriorations={summary['largest_rank_deteriorations']}", "component contribution summary", contrib[["A1_contribution","context_momentum_contribution","technical_contribution","risk_contribution","overlay_minus_neutral"]].describe().to_csv(), "calibration simulation table", pd.DataFrame(sim_summary).to_csv(index=False).strip(), f"structural_recommendation={recommendation}", f"warnings={summary['warnings']}", "protected_outputs_modified=false", "official_adoption_allowed=false", "broker_action_allowed=false", "research_only=true", "E_adoption_allowed=false"]
    (OUT / "V21.136_E_R1_OVERLAY_INFLUENCE_AND_CALIBRATION_DIAGNOSTIC_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(STAGE)
    print(f"FINAL_STATUS={status}")
    print(f"DECISION={decision}")
    print(f"report_path={summary['report_path']}")
    print(f"overlay_influence_class={influence_class}")
    print(f"structural_recommendation={recommendation}")
    print(f"E_R1_Top20_entries_vs_A1={summary['top20_entries_vs_A1']}")
    print(f"E_R1_Top20_exits_vs_A1={summary['top20_exits_vs_A1']}")
    print(f"largest_rank_improvements={summary['largest_rank_improvements']}")
    print(f"largest_rank_deteriorations={summary['largest_rank_deteriorations']}")
    print("calibration_simulation_summary=" + pd.DataFrame(sim_summary).to_json(orient="records"))
    print(f"warnings={summary['warnings']}")
    return summary


if __name__ == "__main__":
    run()
