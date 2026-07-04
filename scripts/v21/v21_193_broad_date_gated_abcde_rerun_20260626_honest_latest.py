#!/usr/bin/env python
"""V21.193 broad-date gated honest-latest ABCDE rerun."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from v21_194_broad_date_gate_utils import build_blocked_newer_dates_audit, classify_requested_date, load_latest_broad_date_gate


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.193_BROAD_DATE_GATED_ABCDE_RERUN_20260626_HONEST_LATEST"
OUT = ROOT / "outputs/v21/V21.193_BROAD_DATE_GATED_ABCDE_RERUN_20260626_HONEST_LATEST"
GATE = ROOT / "outputs/v21/V21.192_CANONICAL_DATE_COVERAGE_GATE_AND_BROAD_LATEST_DATE_RESOLUTION/latest_broad_date_gate.json"
CANONICAL = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
V114_SCRIPT = ROOT / "scripts/v21/v21_114_true_latest_data_abcd_full_recompute_20260625.py"
PRIOR_E_R1 = ROOT / "outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR/e_r1_full_ranking.csv"
EXPECTED_TARGET = "2026-06-26"
LABELS = ["A1", "B", "C", "D", "E_R1"]
ABCD_LABEL = {
    "A1_BASELINE_CONTROL": "A1",
    "B_STATIC_MOMENTUM_BLEND": "B",
    "C_DYNAMIC_MOMENTUM_BLEND": "C",
    "D_WEIGHT_OPTIMIZED_R1": "D",
}
RANK_FILES = {
    "A1": "a1_honest_latest_20260626_ranking.csv",
    "B": "b_honest_latest_20260626_ranking.csv",
    "C": "c_honest_latest_20260626_ranking.csv",
    "D": "d_honest_latest_20260626_ranking.csv",
    "E_R1": "e_r1_honest_latest_20260626_ranking.csv",
}
E_WEIGHTS = {
    "A1_baseline_norm": 0.80,
    "context_momentum_norm": 0.12,
    "technical_entry_quality_norm": 0.04,
    "risk_guardrail_norm": 0.04,
}


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
            for key in row:
                if key not in fields:
                    fields.append(key)
        fields = fields or ["empty"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    if not path.is_file():
        return ""
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
    allowed_prefix = "?? outputs/v21/V21.193_BROAD_DATE_GATED_ABCDE_RERUN_20260626_HONEST_LATEST/"
    allowed_scripts = {
        "?? scripts/v21/v21_193_broad_date_gated_abcde_rerun_20260626_honest_latest.py",
        "?? scripts/v21/test_v21_193_broad_date_gated_abcde_rerun_20260626_honest_latest.py",
        "?? scripts/v21/run_v21_193_broad_date_gated_abcde_rerun_20260626_honest_latest.ps1",
    }
    for line in status_lines:
        normalized = line.replace("\\", "/")
        if normalized in baseline or normalized.startswith(allowed_prefix) or normalized in allowed_scripts:
            continue
        lowered = normalized.lower()
        if lowered.startswith((" m outputs/", " d outputs/", "?? outputs/")) and (
            "official" in lowered or "broker" in lowered or "protected" in lowered or "weight" in lowered
        ):
            return True
    return False


def load_v114() -> Any:
    spec = importlib.util.spec_from_file_location("v21_114_recompute", V114_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {rel(V114_SCRIPT)}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.EXPECTED_DATE = EXPECTED_TARGET
    return module


def topn(frame: pd.DataFrame, n: int) -> pd.DataFrame:
    eligible = frame[frame["eligible_flag"].astype(str).str.upper().isin(["TRUE", "1", "YES"])] if "eligible_flag" in frame else frame
    return eligible.sort_values(["rank", "ticker"]).head(n).copy()


def norm_score(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.dropna().nunique() <= 1:
        return pd.Series(50.0, index=series.index)
    return (numeric.rank(pct=True, ascending=True) * 100.0).clip(0, 100)


def build_e_r1(a1: pd.DataFrame, target: str) -> pd.DataFrame:
    prior = pd.read_csv(PRIOR_E_R1, low_memory=False) if PRIOR_E_R1.is_file() else pd.DataFrame()
    base = a1.copy()
    base["ticker_norm"] = base["ticker"].astype(str).str.upper().str.strip()
    full = base[["ticker_norm", "final_score", "rank"]].rename(columns={"final_score": "A1_raw_score", "rank": "A1_raw_rank"})
    full["A1_baseline_norm"] = norm_score(full["A1_raw_score"])
    if not prior.empty:
        prior["ticker_norm"] = prior["ticker_norm"].astype(str).str.upper().str.strip() if "ticker_norm" in prior else prior["ticker"].astype(str).str.upper().str.strip()
        keep = [c for c in ["ticker_norm", "context_momentum_norm", "technical_entry_quality_norm", "risk_guardrail_norm"] if c in prior]
        full = full.merge(prior[keep].drop_duplicates("ticker_norm"), on="ticker_norm", how="left")
    for col in ["context_momentum_norm", "technical_entry_quality_norm", "risk_guardrail_norm"]:
        if col not in full:
            full[col] = 50.0
        full[col] = pd.to_numeric(full[col], errors="coerce").fillna(50.0).clip(0, 100)
    full["E_final_score"] = sum(full[col] * weight for col, weight in E_WEIGHTS.items())
    full = full.sort_values(["E_final_score", "ticker_norm"], ascending=[False, True]).reset_index(drop=True)
    full["rank"] = np.arange(1, len(full) + 1)
    full["ticker"] = full["ticker_norm"]
    full["strategy"] = "E_R1_DEFENSIVE_OVERLAY_REPAIRED"
    full["latest_price_date"] = target
    full["eligible_flag"] = True
    full["research_only"] = True
    full["official_adoption_allowed"] = False
    full["broker_action_allowed"] = False
    return full


def canonical_audit() -> dict[str, Any]:
    df = pd.read_csv(CANONICAL, usecols=["symbol", "date"], low_memory=False)
    df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return {
        "canonical_path": rel(CANONICAL),
        "row_count": int(len(df)),
        "ticker_count": int(df["symbol"].nunique()),
        "min_date": str(df["date"].min()),
        "max_date": str(df["date"].max()),
        "duplicate_symbol_date_rows": int(df.duplicated(["symbol", "date"]).sum()),
        "sha256": sha256(CANONICAL),
    }


def rerun_rankings(target: str) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]], bool, dict[str, str]]:
    base = load_v114()
    universe, _manifest = base.load_universe()
    price, latest, _price_manifest = base.load_price_panel(universe)
    tech, momentum, blockers = base.compute_features(price)
    write_csv(OUT / "feature_blockers_honest_latest_20260626.csv", blockers, list(blockers[0].keys()) if blockers else ["ticker", "reason"])
    rankings: dict[str, pd.DataFrame] = {}
    resolved: dict[str, str] = {label: "" for label in LABELS}
    audit: list[dict[str, Any]] = []
    attempted_ok = latest >= target and not tech.empty and not momentum.empty
    if attempted_ok:
        built = {ABCD_LABEL[k]: v.copy() for k, v in base.build_rankings(tech, momentum).items()}
        for label, frame in built.items():
            dates = sorted(set(frame["latest_price_date"].astype(str)))
            resolved[label] = dates[0] if len(dates) == 1 else "|".join(dates)
            out = frame.copy()
            out["research_only"] = True
            out["official_adoption_allowed"] = False
            out["broker_action_allowed"] = False
            rankings[label] = out
        if "A1" in rankings:
            rankings["E_R1"] = build_e_r1(rankings["A1"], target)
            resolved["E_R1"] = target
    for label in LABELS:
        frame = rankings.get(label, pd.DataFrame())
        dates = sorted(set(frame["latest_price_date"].astype(str))) if not frame.empty and "latest_price_date" in frame else []
        audit.append({
            "strategy_id": label,
            "target_rerun_date": target,
            "resolved_date": dates[0] if len(dates) == 1 else "|".join(dates),
            "row_count": len(frame),
            "top20_count": len(topn(frame, 20)) if not frame.empty else 0,
            "top50_count": len(topn(frame, 50)) if not frame.empty else 0,
            "same_date_comparable": dates == [target],
            "reason": "" if dates == [target] else "MISSING_OR_MIXED_STRATEGY_DATE",
        })
    same_date = len(rankings) == 5 and all(row["same_date_comparable"] for row in audit)
    return rankings, audit, same_date, resolved


def write_outputs(rankings: dict[str, pd.DataFrame], audit: list[dict[str, Any]]) -> None:
    rows20: list[dict[str, Any]] = []
    rows50: list[dict[str, Any]] = []
    sets20: dict[str, set[str]] = {}
    sets50: dict[str, set[str]] = {}
    for label in LABELS:
        frame = rankings[label]
        frame.to_csv(OUT / RANK_FILES[label], index=False)
        score_col = "E_final_score" if label == "E_R1" else "final_score"
        t20 = topn(frame, 20)
        t50 = topn(frame, 50)
        sets20[label] = set(t20["ticker"].astype(str))
        sets50[label] = set(t50["ticker"].astype(str))
        rows20.extend({"strategy_id": label, "rank": rec.get("rank"), "ticker": rec.get("ticker"), "score": rec.get(score_col), "latest_price_date": rec.get("latest_price_date")} for rec in t20.to_dict("records"))
        rows50.extend({"strategy_id": label, "rank": rec.get("rank"), "ticker": rec.get("ticker"), "score": rec.get(score_col), "latest_price_date": rec.get("latest_price_date")} for rec in t50.to_dict("records"))
    write_csv(OUT / "abcde_top20_summary_honest_latest_20260626.csv", rows20)
    write_csv(OUT / "abcde_top50_summary_honest_latest_20260626.csv", rows50)
    for sets, name in [(sets20, "abcde_overlap_top20_matrix_honest_latest_20260626.csv"), (sets50, "abcde_overlap_top50_matrix_honest_latest_20260626.csv")]:
        matrix = []
        for left in LABELS:
            row = {"strategy_id": left}
            for right in LABELS:
                row[right] = len(sets[left] & sets[right])
            matrix.append(row)
        write_csv(OUT / name, matrix)
    base = rankings["A1"][["ticker", "rank"]].rename(columns={"rank": "A1_rank"})
    diff_rows = []
    for label in LABELS:
        if label == "A1":
            diff_rows.append({"strategy_id": label, "compared_to": "A1", "common_ticker_count": len(base), "mean_rank_diff_vs_a1": 0.0, "median_abs_rank_diff_vs_a1": 0.0})
            continue
        comp = rankings[label][["ticker", "rank"]].rename(columns={"rank": f"{label}_rank"})
        merged = base.merge(comp, on="ticker", how="inner")
        diff = pd.to_numeric(merged[f"{label}_rank"], errors="coerce") - pd.to_numeric(merged["A1_rank"], errors="coerce")
        diff_rows.append({"strategy_id": label, "compared_to": "A1", "common_ticker_count": len(merged), "mean_rank_diff_vs_a1": float(diff.mean()), "median_abs_rank_diff_vs_a1": float(diff.abs().median())})
    write_csv(OUT / "abcde_rank_diff_summary_honest_latest_20260626.csv", diff_rows)
    write_csv(OUT / "abcde_same_date_alignment_audit_honest_latest_20260626.csv", audit)


def report(summary: dict[str, Any]) -> None:
    lines = [
        STAGE,
        "label=LATEST_HONEST_BROAD_DATE_20260626",
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"raw_canonical_max_date={summary['raw_canonical_max_date']}",
        f"target_rerun_date={summary['target_rerun_date']}",
        f"blocked_newer_dates={'|'.join(summary['blocked_newer_dates'])}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
    ]
    (OUT / "V21.193_broad_date_gated_abcde_rerun_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    baseline_status = git_status()
    if not GATE.is_file():
        summary = {
            "stage": STAGE,
            "final_status": "FAIL_V21_193_BROAD_DATE_GATE_MISSING",
            "final_decision": "RUN_V21_192_FIRST",
            "research_only": True,
            "official_adoption_allowed": False,
            "broker_action_allowed": False,
            "protected_outputs_modified": False,
        }
        write_json(OUT / "v21_193_summary.json", summary)
        return summary
    gate = load_latest_broad_date_gate(GATE)
    target = str(gate.get("abcd_honest_latest_date", ""))
    raw_max = str(gate.get("raw_canonical_max_date", ""))
    broad_latest = str(gate.get("broad_price_latest_date", ""))
    blocked = [d for d in gate.get("blocked_newer_dates", []) if str(d) > target]
    target_classification = classify_requested_date(target, gate)
    write_csv(OUT / "broad_date_gate_consumption_audit.csv", [{
        "gate_path": rel(GATE),
        "raw_canonical_max_date": raw_max,
        "broad_price_latest_date": broad_latest,
        "abcd_honest_latest_date": target,
        "target_rerun_date": target,
        "raw_max_newer_than_broad": raw_max > broad_latest,
        "refuse_raw_max_date": raw_max > broad_latest,
        "target_date_classification": target_classification["classification"],
    }])
    canon = canonical_audit()
    write_csv(OUT / "canonical_date_status_audit.csv", [canon])
    write_csv(OUT / "blocked_newer_dates_audit.csv", build_blocked_newer_dates_audit(gate))
    if target > broad_latest:
        final_status = "FAIL_V21_193_TARGET_DATE_NOT_BROAD_ELIGIBLE"
        final_decision = "DO_NOT_USE_NARROW_TAIL_DATE_FOR_ABCDE"
        rankings, audit, same_date, resolved = {}, [], False, {label: "" for label in LABELS}
        attempted = False
    else:
        rankings, audit, same_date, resolved = rerun_rankings(target)
        attempted = True
        write_csv(OUT / "abcde_source_resolution_audit_20260626.csv", audit)
        if same_date:
            write_outputs(rankings, audit)
            final_status = "PASS_V21_193_HONEST_LATEST_20260626_ABCDE_READY"
            final_decision = "LATEST_HONEST_BROAD_DATE_ABCDE_READY_RESEARCH_ONLY"
        else:
            final_status = "FAIL_V21_193_MIXED_DATE_ABCDE_OUTPUT"
            final_decision = "DO_NOT_USE_MIXED_DATE_ABCDE_OUTPUT"
    top20 = {label: topn(frame, 20)["ticker"].astype(str).tolist() for label, frame in rankings.items()} if rankings else {}
    prot_mod = protected_modified(git_status(), baseline_status)
    summary = {
        "stage": STAGE,
        "final_status": final_status,
        "final_decision": final_decision,
        "raw_canonical_max_date": raw_max,
        "raw_canonical_max_date_symbol_count": int(gate.get("raw_canonical_max_date_symbol_count", 0)),
        "raw_canonical_max_date_broad_eligible": bool(gate.get("raw_canonical_max_date_broad_eligible", False)),
        "broad_price_latest_date": broad_latest,
        "feature_latest_date_technical": gate.get("feature_latest_date_technical", ""),
        "feature_latest_date_momentum": gate.get("feature_latest_date_momentum", ""),
        "abcd_honest_latest_date": target,
        "target_rerun_date": target,
        "narrow_tail_detected": bool(blocked),
        "blocked_newer_dates": blocked,
        "abcde_rerun_attempted": attempted,
        "abcde_rerun_succeeded": bool(same_date),
        "a1_resolved_date": resolved.get("A1", ""),
        "b_resolved_date": resolved.get("B", ""),
        "c_resolved_date": resolved.get("C", ""),
        "d_resolved_date": resolved.get("D", ""),
        "e_r1_resolved_date": resolved.get("E_R1", ""),
        "same_date_comparable_all_strategies": bool(same_date),
        "a1_top20": top20.get("A1", []),
        "b_top20": top20.get("B", []),
        "c_top20": top20.get("C", []),
        "d_top20": top20.get("D", []),
        "e_r1_top20": top20.get("E_R1", []),
        "top20_overlap_matrix_path": rel(OUT / "abcde_overlap_top20_matrix_honest_latest_20260626.csv"),
        "top50_overlap_matrix_path": rel(OUT / "abcde_overlap_top50_matrix_honest_latest_20260626.csv"),
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": bool(prot_mod),
    }
    write_json(OUT / "v21_193_summary.json", summary)
    report(summary)
    for key in [
        "final_status", "final_decision", "raw_canonical_max_date", "raw_canonical_max_date_symbol_count",
        "broad_price_latest_date", "abcd_honest_latest_date", "target_rerun_date", "blocked_newer_dates",
        "abcde_rerun_attempted", "abcde_rerun_succeeded", "a1_resolved_date", "b_resolved_date",
        "c_resolved_date", "d_resolved_date", "e_r1_resolved_date", "same_date_comparable_all_strategies",
        "official_adoption_allowed", "broker_action_allowed",
    ]:
        print(f"{key}={summary[key]}")
    if same_date:
        for key in ["a1_top20", "b_top20", "c_top20", "d_top20", "e_r1_top20"]:
            print(f"{key}={'|'.join(summary[key])}")
        print(pd.read_csv(OUT / "abcde_overlap_top20_matrix_honest_latest_20260626.csv").to_string(index=False))
    return summary


if __name__ == "__main__":
    run()
