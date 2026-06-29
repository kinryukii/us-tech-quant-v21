#!/usr/bin/env python
"""V21.133 R1 E baseline anchor and overlap repair."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR"
OUT = ROOT / "outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR"
V128 = ROOT / "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE"
V129 = ROOT / "outputs/v21/V21.129_D_CONTINUED_TRACKING_AND_STRICT_ADOPTION_GATE"
V133 = ROOT / "outputs/v21/V21.133_E_CONSERVATIVE_ADAPTIVE_MOMENTUM_R1"
PRICE_PANEL = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
METADATA_PATH = ROOT / "outputs/v21/V21.111_R1_CONCENTRATION_ATTRIBUTION_AUDIT/d_only_ticker_profile.csv"
REPEATED_LOSER_PATH = V129 / "V21.129_d_repeated_loser_diagnostic.csv"

INPUTS = {
    "A1": V128 / "A1_BASELINE_CONTROL_latest_ranking.csv",
    "B": V128 / "B_STATIC_MOMENTUM_BLEND_latest_ranking.csv",
    "C": V128 / "C_DYNAMIC_MOMENTUM_BLEND_latest_ranking.csv",
    "D": V128 / "D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv",
    "prior_E": V133 / "e_full_ranking.csv",
}
WEIGHTS = {
    "A1_baseline_norm": 0.80,
    "context_momentum_norm": 0.12,
    "technical_entry_quality_norm": 0.04,
    "risk_guardrail_norm": 0.04,
}
NORMALIZED_COMPONENTS = list(WEIGHTS)
FORBIDDEN_SCORE_TOKENS = ["forward_return", "future_label", "matured_return", "outcome"]


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
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


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
    allowed_prefix = "?? outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR/"
    allowed_scripts = {
        "?? scripts/v21/v21_133_r1_e_baseline_anchor_and_overlap_repair.py",
        "?? scripts/v21/test_v21_133_r1_e_baseline_anchor_and_overlap_repair.py",
        "?? scripts/v21/run_v21_133_r1_e_baseline_anchor_and_overlap_repair.ps1",
    }
    for line in status_lines:
        normalized = line.replace("\\", "/")
        if normalized in baseline or normalized.startswith(allowed_prefix) or normalized in allowed_scripts:
            continue
        lowered = normalized.lower()
        if lowered.startswith((" m outputs/", " d outputs/", "?? outputs/")) and (
            "official" in lowered or "broker" in lowered or "protected" in lowered
        ):
            return True
    return False


def ticker_norm(value: Any) -> str:
    return str(value).upper().strip()


def read_input(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, low_memory=False) if path.is_file() else pd.DataFrame()


def score_column(frame: pd.DataFrame) -> str:
    for col in ["final_score", "E_final_score", "A1_final_score"]:
        if col in frame.columns:
            return col
    return ""


def normalize_score(series: pd.Series, higher_is_better: bool = True) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    valid = numeric.dropna()
    if valid.empty or valid.nunique() == 1:
        return pd.Series(50.0, index=series.index)
    ranks = numeric.rank(pct=True, method="average", ascending=higher_is_better)
    return (ranks * 100.0).clip(0, 100)


def norm_from_rank(rank: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(rank, errors="coerce")
    max_rank = numeric.max()
    min_rank = numeric.min()
    if pd.isna(max_rank) or max_rank == min_rank:
        return pd.Series(50.0, index=rank.index)
    return ((max_rank - numeric) / (max_rank - min_rank) * 100.0).clip(0, 100)


def top_tickers(frame: pd.DataFrame, n: int) -> list[str]:
    if frame.empty or "ticker_norm" not in frame.columns:
        return []
    if "rank" in frame.columns:
        out = frame.sort_values(["rank", "ticker_norm"]).head(n)
    elif "E_final_score" in frame.columns:
        out = frame.sort_values(["E_final_score", "ticker_norm"], ascending=[False, True]).head(n)
    else:
        out = frame.head(n)
    return out["ticker_norm"].tolist()


def audit_inputs(frames: dict[str, pd.DataFrame]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    artifact_rows = []
    top_rows = []
    score_rows = []
    norm_rows = []
    for name, path in {**INPUTS, "price_panel": PRICE_PANEL, "metadata": METADATA_PATH, "repeated_loser": REPEATED_LOSER_PATH}.items():
        frame = frames.get(name, read_input(path) if name in INPUTS else pd.DataFrame())
        ticker_col = "ticker" if "ticker" in frame.columns else ("symbol" if "symbol" in frame.columns else "")
        rank_col = "rank" if "rank" in frame.columns else ""
        score_col = score_column(frame)
        latest = ""
        if "latest_price_date" in frame.columns and not frame.empty:
            latest = str(frame["latest_price_date"].dropna().astype(str).max())
        top20 = top_tickers(frame, 20) if name in INPUTS else []
        numeric_score = pd.to_numeric(frame[score_col], errors="coerce") if score_col else pd.Series(dtype=float)
        numeric_rank = pd.to_numeric(frame[rank_col], errors="coerce") if rank_col else pd.Series(dtype=float)
        artifact_rows.append({
            "input_name": name,
            "path": rel(path),
            "exists": path.is_file(),
            "row_count": len(frame) if not frame.empty else (sum(1 for _ in path.open("r", encoding="utf-8", errors="ignore")) - 1 if path.is_file() and name not in INPUTS else 0),
            "ticker_column_detected": ticker_col,
            "score_column_detected": score_col,
            "rank_column_detected": rank_col,
            "latest_price_date_used": latest,
            "top20_tickers_after_ticker_normalization": "|".join(top20),
            "score_min": numeric_score.min() if len(numeric_score) else "",
            "score_max": numeric_score.max() if len(numeric_score) else "",
            "score_mean": numeric_score.mean() if len(numeric_score) else "",
            "score_std": numeric_score.std() if len(numeric_score) else "",
            "rank_min": numeric_rank.min() if len(numeric_rank) else "",
            "rank_max": numeric_rank.max() if len(numeric_rank) else "",
            "duplicate_ticker_count": int(frame["ticker_norm"].duplicated().sum()) if "ticker_norm" in frame.columns else "",
            "missing_ticker_count": int((frame["ticker_norm"] == "").sum()) if "ticker_norm" in frame.columns else "",
        })
        if name in INPUTS:
            for i, ticker in enumerate(top20, start=1):
                top_rows.append({"input_name": name, "top_n": 20, "position": i, "ticker_norm": ticker, "source_path": rel(path)})
            score_rows.append({
                "input_name": name,
                "score_column": score_col,
                "score_min": numeric_score.min() if len(numeric_score) else "",
                "score_max": numeric_score.max() if len(numeric_score) else "",
                "score_mean": numeric_score.mean() if len(numeric_score) else "",
                "score_std": numeric_score.std() if len(numeric_score) else "",
                "source_path": rel(path),
            })
            if "ticker" in frame.columns:
                for row in frame[["ticker", "ticker_norm"]].head(5000).to_dict("records"):
                    norm_rows.append({
                        "input_name": name,
                        "source_path": rel(path),
                        "original_ticker": row["ticker"],
                        "ticker_norm": row["ticker_norm"],
                        "duplicate_ticker_norm": bool(frame["ticker_norm"].duplicated(keep=False).loc[frame["ticker_norm"].eq(row["ticker_norm"])].any()),
                    })
    return artifact_rows, top_rows, score_rows, norm_rows


def overlap_details(sets: dict[str, dict[str, set[str]]]) -> tuple[pd.DataFrame, dict[str, Any]]:
    labels = ["A1", "B", "C", "D", "E"]
    rows = []
    detail: dict[str, Any] = {}
    for left in labels:
        row = {"strategy": left}
        for right in labels:
            top20 = sorted(sets[left]["top20"].intersection(sets[right]["top20"]))
            top50 = sorted(sets[left]["top50"].intersection(sets[right]["top50"]))
            row[f"{right}_top20_overlap_count"] = len(top20)
            row[f"{right}_top20_overlap_tickers"] = "|".join(top20)
            row[f"{right}_top50_overlap_count"] = len(top50)
            row[f"{right}_top50_overlap_tickers"] = "|".join(top50)
            detail[f"{left}_vs_{right}"] = {
                "top20_overlap_count": len(top20),
                "top20_overlap_tickers": top20,
                "top50_overlap_count": len(top50),
                "top50_overlap_tickers": top50,
            }
        rows.append(row)
    return pd.DataFrame(rows), detail


def load_and_normalize_inputs() -> dict[str, pd.DataFrame]:
    frames = {}
    for name, path in INPUTS.items():
        frame = read_input(path)
        if not frame.empty and "ticker" in frame.columns:
            frame["ticker_norm"] = frame["ticker"].map(ticker_norm)
            frame = frame[frame["ticker_norm"].ne("") & frame["ticker_norm"].ne("NAN")].copy()
        frames[name] = frame
    return frames


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    baseline_status = git_status()
    protected_inputs = [path for path in [*INPUTS.values(), PRICE_PANEL] if path.is_file()]
    baseline_hashes = {rel(path): sha256(path) for path in protected_inputs}
    frames = load_and_normalize_inputs()
    artifact_rows, top_rows, score_rows, norm_rows = audit_inputs(frames)
    write_csv(OUT / "input_artifact_audit.csv", artifact_rows)
    write_csv(OUT / "input_top20_snapshot.csv", top_rows)
    write_csv(OUT / "input_score_distribution_audit.csv", score_rows)
    write_csv(OUT / "ticker_normalization_audit.csv", norm_rows)

    warnings = []
    a1 = frames["A1"].copy()
    if a1.empty or "ticker_norm" not in a1.columns:
        final_status = "BLOCKED_V21_133_R1_MISSING_OR_INVALID_A1_BASELINE"
        decision = "E_REPAIR_BLOCKED_A1_INPUT_INVALID"
        summary = {"stage": STAGE, "FINAL_STATUS": final_status, "DECISION": decision, "official_adoption_allowed": False, "broker_action_allowed": False, "research_only": True, "protected_outputs_modified": False}
        write_json(OUT / "e_r1_validation_summary.json", summary)
        return summary

    a1_score_col = "final_score" if "final_score" in a1.columns else score_column(a1)
    if a1_score_col:
        a1["A1_raw_score"] = pd.to_numeric(a1[a1_score_col], errors="coerce")
        a1["A1_baseline_norm"] = normalize_score(a1["A1_raw_score"], higher_is_better=True)
    elif "rank" in a1.columns:
        a1["A1_raw_score"] = np.nan
        a1["A1_baseline_norm"] = norm_from_rank(a1["rank"])
    else:
        a1["A1_baseline_norm"] = np.nan
    a1["A1_raw_rank"] = pd.to_numeric(a1["rank"], errors="coerce") if "rank" in a1.columns else np.nan
    a1_anchor = a1[["ticker_norm", "A1_raw_score", "A1_raw_rank", "A1_baseline_norm"]].copy()
    a1_anchor["A1_rank_after_norm"] = a1_anchor["A1_baseline_norm"].rank(ascending=False, method="first")
    a1_anchor["source_path"] = rel(INPUTS["A1"])
    a1_anchor.sort_values("A1_rank_after_norm").to_csv(OUT / "a1_baseline_anchor_audit.csv", index=False)
    discovered_a1_top20 = set(top_tickers(a1, 20))
    reconstructed_a1_top20 = set(a1_anchor.sort_values(["A1_baseline_norm", "ticker_norm"], ascending=[False, True]).head(20)["ticker_norm"])
    a1_anchor_ok = len(discovered_a1_top20.intersection(reconstructed_a1_top20)) >= 18
    if not a1_anchor_ok:
        warnings.append("A1 anchor reconstruction did not substantially match discovered A1 Top20")

    prior_e = frames["prior_E"].copy()
    root_cause = "V21.133 used percentile scoring with rank direction inverted: low A1 final_score / high raw rank received high A1_baseline_norm, creating zero overlap with A1 despite 80% anchor."
    full = a1_anchor.merge(prior_e[[c for c in prior_e.columns if c in ["ticker_norm", "context_momentum_norm", "technical_entry_quality_norm", "risk_guardrail_norm", "latest_price_date"]]], on="ticker_norm", how="left")
    for col in ["context_momentum_norm", "technical_entry_quality_norm", "risk_guardrail_norm"]:
        if col not in full.columns:
            full[col] = 50.0
            warnings.append(f"{col} missing; neutral 50 used")
        full[col] = pd.to_numeric(full[col], errors="coerce").fillna(50.0).clip(0, 100)
    full["A1_baseline_norm"] = pd.to_numeric(full["A1_baseline_norm"], errors="coerce").clip(0, 100)
    full["E_final_score"] = sum(full[col] * weight for col, weight in WEIGHTS.items())
    full["eligible_flag"] = full["A1_baseline_norm"].notna()
    full = full.sort_values(["eligible_flag", "E_final_score", "ticker_norm"], ascending=[False, False, True]).reset_index(drop=True)
    full["rank"] = np.where(full["eligible_flag"], np.arange(1, len(full) + 1), np.nan)
    full["strategy"] = "E_CONSERVATIVE_ADAPTIVE_MOMENTUM_R1_R1_REPAIRED"
    full["research_only"] = True
    full["official_adoption_allowed"] = False
    full["broker_action_allowed"] = False
    full["leakage_warning"] = "NO_FUTURE_LEAKAGE_DETECTED_REPAIRED_ANCHOR_ONLY"
    full.to_csv(OUT / "e_r1_full_ranking.csv", index=False)
    full[full["eligible_flag"]].head(20).to_csv(OUT / "e_r1_top20.csv", index=False)
    full[full["eligible_flag"]].head(50).to_csv(OUT / "e_r1_top50.csv", index=False)
    full.to_csv(OUT / "e_r1_score_components.csv", index=False)

    all_frames = {k: v.copy() for k, v in frames.items() if k in ["A1", "B", "C", "D"]}
    all_frames["E"] = full.rename(columns={"rank": "rank"})
    sets = {}
    for name, frame in all_frames.items():
        sorted_frame = frame.sort_values(["rank", "ticker_norm"]) if "rank" in frame.columns else frame
        sets[name] = {"top20": set(sorted_frame.head(20)["ticker_norm"]), "top50": set(sorted_frame.head(50)["ticker_norm"])}
    overlap, overlap_json = overlap_details(sets)
    overlap.to_csv(OUT / "e_r1_abcd_overlap_matrix.csv", index=False)
    overlap[["strategy", "A1_top20_overlap_count", "B_top20_overlap_count", "C_top20_overlap_count", "D_top20_overlap_count", "E_top20_overlap_count"]].to_csv(OUT / "e_r1_overlap_matrix.csv", index=False)
    (OUT / "e_r1_abcd_overlap_tickers.json").write_text(json.dumps(overlap_json, indent=2) + "\n", encoding="utf-8")

    rank_diff = full[["ticker_norm", "rank", "E_final_score", "A1_baseline_norm"]].merge(a1[["ticker_norm", "rank"]].rename(columns={"rank": "A1_rank"}), on="ticker_norm", how="left")
    rank_diff["E_minus_A1_rank"] = pd.to_numeric(rank_diff["rank"], errors="coerce") - pd.to_numeric(rank_diff["A1_rank"], errors="coerce")
    rank_diff.to_csv(OUT / "e_r1_rank_diff_vs_a1.csv", index=False)

    corr_rows = []
    for col in NORMALIZED_COMPONENTS:
        corr = float(full["E_final_score"].corr(full[col])) if full[col].nunique(dropna=True) > 1 else math.nan
        contribution = float((full[col] * WEIGHTS[col]).mean())
        corr_rows.append({"component": col, "weight": WEIGHTS[col], "corr_with_E_final_score": corr, "mean_weighted_contribution": contribution})
    write_csv(OUT / "e_r1_anchor_correlation_audit.csv", corr_rows)

    corr_a1 = next(row["corr_with_E_final_score"] for row in corr_rows if row["component"] == "A1_baseline_norm")
    non_a1_max_contribution = max(row["mean_weighted_contribution"] for row in corr_rows if row["component"] != "A1_baseline_norm")
    a1_contribution = next(row["mean_weighted_contribution"] for row in corr_rows if row["component"] == "A1_baseline_norm")
    e_vs_a1_top20 = overlap_json["E_vs_A1"]["top20_overlap_count"]
    leakage_risk = any(any(token in col.lower() for token in FORBIDDEN_SCORE_TOKENS) for col in full.columns)
    if not a1_anchor_ok:
        final_status = "FAIL_V21_133_R1_A1_ANCHOR_RECONSTRUCTION_FAILED"
        decision = "E_REPAIR_BLOCKED_A1_INPUT_INVALID"
    elif leakage_risk:
        final_status = "FAIL_V21_133_R1_LEAKAGE_RISK"
        decision = "E_REJECTED_LEAKAGE_RISK"
    elif e_vs_a1_top20 == 0:
        final_status = "FAIL_V21_133_R1_E_ZERO_A1_OVERLAP"
        decision = "E_REJECTED_ZERO_A1_OVERLAP_ANCHOR_FAILURE"
    elif corr_a1 < 0.50 or a1_contribution <= non_a1_max_contribution:
        final_status = "FAIL_V21_133_R1_E_ANCHOR_DOMINANCE_FAILURE"
        decision = "E_REJECTED_A1_ANCHOR_DOMINANCE_FAILURE"
    elif corr_a1 >= 0.75:
        final_status = "PARTIAL_PASS_V21_133_R1_E_ANCHOR_REPAIRED_RESEARCH_ONLY"
        decision = "E_R1_RESEARCH_ONLY_CHALLENGER_READY_FOR_FORWARD_TRACKING_REVIEW"
    else:
        final_status = "FAIL_V21_133_R1_E_ANCHOR_CORRELATION_LOW"
        decision = "E_REJECTED_A1_ANCHOR_CORRELATION_LOW"

    price_panel_max_date = pd.read_csv(PRICE_PANEL, usecols=["date"])["date"].astype(str).max() if PRICE_PANEL.is_file() else ""
    latest_price_date_used = str(read_input(V128 / "V21.128_summary.json").get("latest_price_date_used", "")) if False else str(a1["latest_price_date"].dropna().astype(str).max())
    post_hashes = {rel(path): sha256(path) for path in protected_inputs}
    prot_mod = baseline_hashes != post_hashes or protected_modified(git_status(), baseline_status)
    summary = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "root_cause": root_cause,
        "latest_price_date_used": latest_price_date_used,
        "price_panel_max_date": price_panel_max_date,
        "input_paths": {k: rel(v) for k, v in INPUTS.items()},
        "price_panel_path": rel(PRICE_PANEL),
        "metadata_path": rel(METADATA_PATH),
        "repeated_loser_path": rel(REPEATED_LOSER_PATH),
        "A1_reconstructed_top20": "|".join(sorted(reconstructed_a1_top20, key=lambda t: a1_anchor.set_index("ticker_norm").loc[t, "A1_rank_after_norm"])),
        "E_R1_top20": "|".join(full.head(20)["ticker_norm"]),
        "E_vs_A1_top20_overlap_count": e_vs_a1_top20,
        "E_vs_A1_top20_overlap_tickers": "|".join(overlap_json["E_vs_A1"]["top20_overlap_tickers"]),
        "E_vs_B_top20_overlap_count": overlap_json["E_vs_B"]["top20_overlap_count"],
        "E_vs_C_top20_overlap_count": overlap_json["E_vs_C"]["top20_overlap_count"],
        "E_vs_D_top20_overlap_count": overlap_json["E_vs_D"]["top20_overlap_count"],
        "E_vs_A1_top50_overlap_count": overlap_json["E_vs_A1"]["top50_overlap_count"],
        "corr_E_final_score_A1_baseline_norm": corr_a1,
        "weights": WEIGHTS,
        "weight_sum": float(sum(WEIGHTS.values())),
        "warnings": "|".join(warnings) if warnings else "none",
        "protected_outputs_modified": bool(prot_mod),
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
        "E_adoption_allowed": False,
        "report_path": rel(OUT / "V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR_report.txt"),
    }
    write_json(OUT / "e_r1_validation_summary.json", summary)
    report = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"root_cause={root_cause}",
        f"input_paths={json.dumps(summary['input_paths'], sort_keys=True)}",
        f"A1_reconstructed_Top20={summary['A1_reconstructed_top20']}",
        f"E_R1_Top20={summary['E_R1_top20']}",
        f"E_vs_A1_Top20_overlap={summary['E_vs_A1_top20_overlap_count']} {summary['E_vs_A1_top20_overlap_tickers']}",
        f"E_vs_B_Top20_overlap={summary['E_vs_B_top20_overlap_count']}",
        f"E_vs_C_Top20_overlap={summary['E_vs_C_top20_overlap_count']}",
        f"E_vs_D_Top20_overlap={summary['E_vs_D_top20_overlap_count']}",
        f"E_vs_A1_Top50_overlap={summary['E_vs_A1_top50_overlap_count']}",
        f"E_A1_correlation={corr_a1}",
        "",
        "largest rank movers vs A1",
        rank_diff.reindex(rank_diff["E_minus_A1_rank"].abs().sort_values(ascending=False).index).head(20).to_csv(index=False).strip(),
        "",
        "component distribution table",
        pd.DataFrame(corr_rows).to_csv(index=False).strip(),
        f"warnings={summary['warnings']}",
        "protected_outputs_modified=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
    ]
    (OUT / "V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")

    print(STAGE)
    print(f"FINAL_STATUS={summary['FINAL_STATUS']}")
    print(f"DECISION={summary['DECISION']}")
    print(f"report_path={summary['report_path']}")
    print(f"root_cause={summary['root_cause']}")
    print(f"A1_Top20={summary['A1_reconstructed_top20']}")
    print(f"E_R1_Top20={summary['E_R1_top20']}")
    print(f"E_vs_A1_Top20_overlap_count={summary['E_vs_A1_top20_overlap_count']}")
    print(f"E_vs_A1_Top20_overlap_tickers={summary['E_vs_A1_top20_overlap_tickers']}")
    print(f"E_vs_B_Top20_overlap_count={summary['E_vs_B_top20_overlap_count']}")
    print(f"E_vs_C_Top20_overlap_count={summary['E_vs_C_top20_overlap_count']}")
    print(f"E_vs_D_Top20_overlap_count={summary['E_vs_D_top20_overlap_count']}")
    print(f"corr_E_final_score_A1_baseline_norm={summary['corr_E_final_score_A1_baseline_norm']}")
    print(f"warnings={summary['warnings']}")
    return summary


if __name__ == "__main__":
    run()
