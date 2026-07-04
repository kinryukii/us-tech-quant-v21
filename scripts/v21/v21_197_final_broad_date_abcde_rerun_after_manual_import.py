#!/usr/bin/env python
"""V21.197 final broad-date ABCDE rerun after V21.196 manual import."""

from __future__ import annotations

import csv
import importlib.util
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT"
OUT = ROOT / "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT"
CANONICAL = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
V114_SCRIPT = ROOT / "scripts/v21/v21_114_true_latest_data_abcd_full_recompute_20260625.py"
V193_SCRIPT = ROOT / "scripts/v21/v21_193_broad_date_gated_abcde_rerun_20260626_honest_latest.py"
V193_SUMMARY = ROOT / "outputs/v21/V21.193_BROAD_DATE_GATED_ABCDE_RERUN_20260626_HONEST_LATEST/v21_193_summary.json"
TARGET = os.environ.get("V21_197_TARGET_DATE", "2026-06-30").strip() or "2026-06-30"
TARGET_TAG = TARGET.replace("-", "")
MIN_BROAD_SYMBOLS = 300
MIN_COVERAGE_RATIO = 0.80
LABELS = ["A1", "B", "C", "D", "E_R1"]
ABCD_LABEL = {
    "A1_BASELINE_CONTROL": "A1",
    "B_STATIC_MOMENTUM_BLEND": "B",
    "C_DYNAMIC_MOMENTUM_BLEND": "C",
    "D_WEIGHT_OPTIMIZED_R1": "D",
}
RANK_FILES = {
    "A1": f"a1_final_broad_{TARGET_TAG}_ranking.csv",
    "B": f"b_final_broad_{TARGET_TAG}_ranking.csv",
    "C": f"c_final_broad_{TARGET_TAG}_ranking.csv",
    "D": f"d_final_broad_{TARGET_TAG}_ranking.csv",
    "E_R1": f"e_r1_final_broad_{TARGET_TAG}_ranking.csv",
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


def git_status() -> list[str]:
    proc = subprocess.run(["git", "status", "--short"], cwd=ROOT, text=True, capture_output=True, check=False)
    return proc.stdout.splitlines()


def protected_modified(status_lines: list[str], baseline_lines: list[str]) -> bool:
    baseline = {line.replace("\\", "/") for line in baseline_lines}
    allowed_prefix = "?? outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT/"
    allowed_scripts = {
        "?? scripts/v21/v21_197_final_broad_date_abcde_rerun_after_manual_import.py",
        "?? scripts/v21/run_v21_197_final_broad_date_abcde_rerun_after_manual_import.ps1",
        "?? scripts/v21/test_v21_197_final_broad_date_abcde_rerun_after_manual_import.py",
    }
    for line in status_lines:
        normalized = line.replace("\\", "/")
        if normalized in baseline or normalized.startswith(allowed_prefix) or normalized in allowed_scripts:
            continue
        lowered = normalized.lower()
        if lowered.startswith((" m outputs/", " d outputs/", "?? outputs/")) and (
            "official" in lowered or "broker" in lowered or "weight" in lowered or "protected" in lowered
        ):
            return True
    return False


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {rel(path)}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_canonical(path: Path = CANONICAL) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return frame.dropna(subset=["symbol", "date"])


def date_coverage(frame: pd.DataFrame) -> list[dict[str, Any]]:
    universe_count = int(frame["symbol"].nunique())
    rows: list[dict[str, Any]] = []
    for date, group in frame.groupby("date", sort=True):
        distinct = int(group["symbol"].nunique())
        duplicate_count = int(group.duplicated(["symbol", "date"]).sum())
        close = pd.to_numeric(group.get("close"), errors="coerce")
        coverage = distinct / universe_count if universe_count else 0.0
        broad = distinct >= MIN_BROAD_SYMBOLS and coverage >= MIN_COVERAGE_RATIO and duplicate_count == 0 and int((close <= 0).sum()) == 0
        rows.append({
            "date": str(date),
            "price_row_count": int(len(group)),
            "distinct_symbol_count": distinct,
            "canonical_symbol_count": universe_count,
            "coverage_ratio": coverage,
            "duplicate_symbol_date_count": duplicate_count,
            "zero_or_negative_close_count": int((close <= 0).sum()),
            "broad_price_date_eligible": broad,
        })
    return rows


def canonical_audit(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "canonical_path": rel(CANONICAL),
        "row_count": int(len(frame)),
        "symbol_count": int(frame["symbol"].nunique()),
        "min_date": str(frame["date"].min()),
        "max_date": str(frame["date"].max()),
        "duplicate_symbol_date_rows": int(frame.duplicated(["symbol", "date"]).sum()),
    }


def prior_feature_dates(path: Path = V193_SUMMARY) -> dict[str, str]:
    if not path.is_file():
        return {"feature_latest_date_technical_before": "", "feature_latest_date_momentum_before": ""}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "feature_latest_date_technical_before": str(payload.get("feature_latest_date_technical", "")),
        "feature_latest_date_momentum_before": str(payload.get("feature_latest_date_momentum", "")),
    }


def topn(frame: pd.DataFrame, n: int) -> pd.DataFrame:
    eligible = frame[frame["eligible_flag"].astype(str).str.upper().isin(["TRUE", "1", "YES"])] if "eligible_flag" in frame else frame
    return eligible.sort_values(["rank", "ticker"]).head(n).copy()


def tagged(name: str) -> str:
    return name.format(tag=TARGET_TAG)


def target_date_rerank(frame: pd.DataFrame, target: str = TARGET) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    if frame.empty or "latest_price_date" not in frame:
        return frame.copy(), []
    out = frame.copy()
    out["latest_price_date"] = out["latest_price_date"].astype(str)
    stale = out.loc[~out["latest_price_date"].eq(target)].copy()
    filtered = out.loc[out["latest_price_date"].eq(target)].copy()
    if not filtered.empty and "final_score" in filtered:
        filtered["rank"] = pd.to_numeric(filtered["final_score"], errors="coerce").rank(method="first", ascending=False).astype(int)
        filtered = filtered.sort_values(["rank", "ticker"]).reset_index(drop=True)
    rows = []
    for row in stale.to_dict("records"):
        rows.append({
            "strategy_id": row.get("strategy", ""),
            "target_rerun_date": target,
            "resolved_date": row.get("latest_price_date", ""),
            "ticker": row.get("ticker", ""),
            "reason": "EXCLUDED_FROM_FINAL_SAME_DATE_RANKING_STALE_SYMBOL_DATE",
            "upstream_builder": rel(V114_SCRIPT),
        })
    return filtered, rows


def load_builders() -> tuple[Any, Any]:
    base = load_module(V114_SCRIPT, "v21_114_for_197")
    base.EXPECTED_DATE = TARGET
    e_mod = load_module(V193_SCRIPT, "v21_193_for_197")
    return base, e_mod


def rebuild_features_and_rankings() -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    base, e_mod = load_builders()
    universe, _manifest = base.load_universe()
    price, price_latest, _price_manifest = base.load_price_panel(universe)
    tech, momentum, blockers = base.compute_features(price)
    tech_latest = max(tech["latest_price_date"].astype(str), default="") if not tech.empty else ""
    mom_latest = max(momentum["latest_price_date"].astype(str), default="") if not momentum.empty else ""
    write_csv(OUT / tagged("feature_blockers_{tag}.csv"), blockers, list(blockers[0].keys()) if blockers else ["ticker", "reason"])
    feature_audit = {
        "price_panel_latest_from_builder": price_latest,
        "feature_latest_date_technical_after": tech_latest,
        "feature_latest_date_momentum_after": mom_latest,
        "technical_feature_row_count": int(len(tech)),
        "momentum_feature_row_count": int(len(momentum)),
        "feature_blocker_count": int(len(blockers)),
    }
    rankings: dict[str, pd.DataFrame] = {}
    if price_latest >= TARGET and tech_latest >= TARGET and mom_latest >= TARGET and not tech.empty and not momentum.empty:
        built = base.build_rankings(tech, momentum)
        for strategy, frame in built.items():
            label = ABCD_LABEL[strategy]
            out, stale_rows = target_date_rerank(frame, TARGET)
            out["research_only"] = True
            out["official_adoption_allowed"] = False
            out["broker_action_allowed"] = False
            rankings[label] = out
            blockers.extend({**row, "strategy_id": label} for row in stale_rows)
        if "A1" in rankings:
            e_mod.OUT = OUT
            rankings["E_R1"] = e_mod.build_e_r1(rankings["A1"], TARGET)
    resolution = []
    for label in LABELS:
        frame = rankings.get(label, pd.DataFrame())
        dates = sorted(set(frame["latest_price_date"].astype(str))) if not frame.empty and "latest_price_date" in frame else []
        resolved = dates[0] if len(dates) == 1 else "|".join(dates)
        resolution.append({
            "strategy_id": label,
            "target_rerun_date": TARGET,
            "resolved_date": resolved,
            "row_count": int(len(frame)),
            "top20_count": int(len(topn(frame, 20))) if not frame.empty else 0,
            "top50_count": int(len(topn(frame, 50))) if not frame.empty else 0,
            "same_date_comparable": dates == [TARGET],
            "reason": "" if dates == [TARGET] else "MISSING_OR_MIXED_STRATEGY_DATE",
        })
    return rankings, resolution, feature_audit, blockers


def write_ranking_outputs(rankings: dict[str, pd.DataFrame], resolution: list[dict[str, Any]]) -> None:
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
        rows20.extend({"strategy_id": label, "rank": r.get("rank"), "ticker": r.get("ticker"), "score": r.get(score_col), "latest_price_date": r.get("latest_price_date")} for r in t20.to_dict("records"))
        rows50.extend({"strategy_id": label, "rank": r.get("rank"), "ticker": r.get("ticker"), "score": r.get(score_col), "latest_price_date": r.get("latest_price_date")} for r in t50.to_dict("records"))
    write_csv(OUT / tagged("abcde_top20_summary_final_broad_{tag}.csv"), rows20)
    write_csv(OUT / tagged("abcde_top50_summary_final_broad_{tag}.csv"), rows50)
    for n, sets, path in [
        (20, sets20, OUT / tagged("abcde_overlap_top20_matrix_final_broad_{tag}.csv")),
        (50, sets50, OUT / tagged("abcde_overlap_top50_matrix_final_broad_{tag}.csv")),
    ]:
        matrix = []
        for left in LABELS:
            row = {"strategy_id": left}
            for right in LABELS:
                row[right] = len(sets[left] & sets[right])
            matrix.append(row)
        write_csv(path, matrix)
    base = rankings["A1"][["ticker", "rank"]].rename(columns={"rank": "A1_rank"})
    diffs = []
    for label in LABELS:
        if label == "A1":
            diffs.append({"strategy_id": label, "compared_to": "A1", "common_ticker_count": len(base), "mean_rank_diff_vs_a1": 0.0, "median_abs_rank_diff_vs_a1": 0.0})
            continue
        comp = rankings[label][["ticker", "rank"]].rename(columns={"rank": f"{label}_rank"})
        merged = base.merge(comp, on="ticker", how="inner")
        diff = pd.to_numeric(merged[f"{label}_rank"], errors="coerce") - pd.to_numeric(merged["A1_rank"], errors="coerce")
        diffs.append({"strategy_id": label, "compared_to": "A1", "common_ticker_count": int(len(merged)), "mean_rank_diff_vs_a1": float(diff.mean()), "median_abs_rank_diff_vs_a1": float(diff.abs().median())})
    write_csv(OUT / tagged("abcde_rank_diff_summary_final_broad_{tag}.csv"), diffs)
    write_csv(OUT / tagged("abcde_same_date_alignment_audit_final_broad_{tag}.csv"), resolution)


def report(summary: dict[str, Any]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"canonical_latest_date={summary['canonical_latest_date']}",
        f"broad_price_latest_date={summary['broad_price_latest_date']}",
        f"target_rerun_date={summary['target_rerun_date']}",
        f"same_date_comparable_all_strategies={summary['same_date_comparable_all_strategies']}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        f"protected_outputs_modified={str(summary['protected_outputs_modified']).lower()}",
    ]
    (OUT / "V21.197_final_broad_date_abcde_rerun_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    baseline = git_status()
    canonical = load_canonical()
    audit = canonical_audit(canonical)
    write_csv(OUT / "canonical_after_v21_196_apply_audit.csv", [audit])
    coverage = date_coverage(canonical)
    write_csv(OUT / "v21_197_broad_date_coverage_audit.csv", coverage)
    cov = pd.DataFrame(coverage)
    raw_max = str(canonical["date"].max()) if len(canonical) else ""
    raw_row = cov[cov["date"].eq(raw_max)].iloc[0].to_dict() if raw_max and not cov.empty else {}
    broad_dates = cov.loc[cov["broad_price_date_eligible"].astype(bool), "date"].astype(str).tolist() if not cov.empty else []
    broad_latest = max(broad_dates) if broad_dates else ""
    feature_before = prior_feature_dates()
    rankings: dict[str, pd.DataFrame] = {}
    resolution: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    feature_after = {
        "feature_latest_date_technical_after": "",
        "feature_latest_date_momentum_after": "",
        "technical_feature_row_count": 0,
        "momentum_feature_row_count": 0,
        "feature_blocker_count": 0,
    }
    feature_rebuild_attempted = broad_latest == TARGET
    if feature_rebuild_attempted:
        rankings, resolution, feature_after, blockers = rebuild_features_and_rankings()
    feature_rebuild_succeeded = feature_after["feature_latest_date_technical_after"] >= TARGET and feature_after["feature_latest_date_momentum_after"] >= TARGET
    feature_rows = [
        {"feature_name": "technical", "latest_before": feature_before["feature_latest_date_technical_before"], "latest_after": feature_after["feature_latest_date_technical_after"], "row_count": feature_after["technical_feature_row_count"], "rebuild_attempted": feature_rebuild_attempted, "rebuild_succeeded": feature_rebuild_succeeded},
        {"feature_name": "momentum", "latest_before": feature_before["feature_latest_date_momentum_before"], "latest_after": feature_after["feature_latest_date_momentum_after"], "row_count": feature_after["momentum_feature_row_count"], "rebuild_attempted": feature_rebuild_attempted, "rebuild_succeeded": feature_rebuild_succeeded},
    ]
    write_csv(OUT / tagged("feature_rebuild_audit_{tag}.csv"), feature_rows)
    write_csv(OUT / tagged("abcd_source_resolution_audit_{tag}.csv"), resolution, ["strategy_id", "target_rerun_date", "resolved_date", "row_count", "top20_count", "top50_count", "same_date_comparable", "reason"])
    stale = []
    same_date = len(rankings) == 5 and all(row.get("same_date_comparable") for row in resolution)
    if same_date:
        write_ranking_outputs(rankings, resolution)
    else:
        stale = [row for row in resolution if not row.get("same_date_comparable")]
    write_csv(OUT / "stale_or_failed_strategy_diagnostic.csv", stale, ["strategy_id", "target_rerun_date", "resolved_date", "row_count", "top20_count", "top50_count", "same_date_comparable", "reason"])
    abcd_honest = min([broad_latest, feature_after["feature_latest_date_technical_after"], feature_after["feature_latest_date_momentum_after"]]) if broad_latest and feature_after["feature_latest_date_technical_after"] and feature_after["feature_latest_date_momentum_after"] else ""
    gate = {
        "stage": STAGE,
        "raw_canonical_max_date": raw_max,
        "raw_canonical_max_date_symbol_count": int(raw_row.get("distinct_symbol_count", 0) or 0),
        "raw_canonical_max_date_broad_eligible": bool(raw_row.get("broad_price_date_eligible", False)),
        "broad_price_latest_date": broad_latest,
        "feature_latest_date_technical": feature_after["feature_latest_date_technical_after"],
        "feature_latest_date_momentum": feature_after["feature_latest_date_momentum_after"],
        "abcd_honest_latest_date": abcd_honest,
        "blocked_newer_dates": [],
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
    }
    write_json(OUT / "v21_197_latest_broad_date_gate.json", gate)
    resolved = {row["strategy_id"]: row.get("resolved_date", "") for row in resolution}
    top20 = {label: topn(rankings[label], 20)["ticker"].astype(str).tolist() for label in rankings} if rankings else {}
    top50 = {label: topn(rankings[label], 50)["ticker"].astype(str).tolist() for label in rankings} if rankings else {}
    abcde_attempted = feature_rebuild_attempted and feature_rebuild_succeeded
    if raw_max < TARGET:
        final_status = "BLOCKED_STALE_CANONICAL"
        final_decision = "STOP_DO_NOT_REPORT_STALE_RANKINGS_AS_LATEST"
    elif broad_latest != TARGET:
        final_status = "BLOCKED_STALE_CANONICAL"
        final_decision = "STOP_CANONICAL_NOT_BROAD_ELIGIBLE_FOR_TARGET_DATE"
    elif not feature_rebuild_succeeded:
        final_status = "PARTIAL_PASS_V21_197_FEATURE_REBUILD_REQUIRED_OR_FAILED"
        final_decision = "REPAIR_IDENTIFIED_FEATURE_BUILDER_BEFORE_ABCDE_USE"
    elif not same_date:
        final_status = "FAIL_NON_COMPARABLE_STRATEGY_DATES"
        final_decision = "DO_NOT_USE_MIXED_DATE_ABCDE_OUTPUT"
    else:
        final_status = f"PASS_V21_197_FINAL_{TARGET_TAG}_ABCDE_READY"
        final_decision = f"FINAL_BROAD_{TARGET_TAG}_ABCDE_READY_RESEARCH_ONLY"
    summary = {
        "stage": STAGE,
        "final_status": final_status,
        "final_decision": final_decision,
        "canonical_latest_date": raw_max,
        "raw_canonical_max_date": raw_max,
        "raw_canonical_max_date_symbol_count": int(raw_row.get("distinct_symbol_count", 0) or 0),
        "raw_canonical_max_date_broad_eligible": bool(raw_row.get("broad_price_date_eligible", False)),
        "broad_price_latest_date": broad_latest,
        "feature_latest_date_technical_before": feature_before["feature_latest_date_technical_before"],
        "feature_latest_date_momentum_before": feature_before["feature_latest_date_momentum_before"],
        "feature_rebuild_attempted": feature_rebuild_attempted,
        "feature_rebuild_succeeded": feature_rebuild_succeeded,
        "feature_latest_date_technical_after": feature_after["feature_latest_date_technical_after"],
        "feature_latest_date_momentum_after": feature_after["feature_latest_date_momentum_after"],
        "abcd_honest_latest_date": abcd_honest,
        "target_rerun_date": TARGET,
        "abcde_rerun_attempted": abcde_attempted,
        "abcde_rerun_succeeded": bool(same_date),
        "a1_resolved_date": resolved.get("A1", ""),
        "b_resolved_date": resolved.get("B", ""),
        "c_resolved_date": resolved.get("C", ""),
        "d_resolved_date": resolved.get("D", ""),
        "e_r1_resolved_date": resolved.get("E_R1", ""),
        "strategy_latest_dates": resolved,
        "same_date_comparable_all_strategies": bool(same_date),
        "a1_top20": top20.get("A1", []),
        "b_top20": top20.get("B", []),
        "c_top20": top20.get("C", []),
        "d_top20": top20.get("D", []),
        "e_r1_top20": top20.get("E_R1", []),
        "a1_top50": top50.get("A1", []),
        "b_top50": top50.get("B", []),
        "c_top50": top50.get("C", []),
        "d_top50": top50.get("D", []),
        "e_r1_top50": top50.get("E_R1", []),
        "top20_overlap_matrix_path": rel(OUT / tagged("abcde_overlap_top20_matrix_final_broad_{tag}.csv")),
        "top50_overlap_matrix_path": rel(OUT / tagged("abcde_overlap_top50_matrix_final_broad_{tag}.csv")),
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": protected_modified(git_status(), baseline),
    }
    write_json(OUT / "v21_197_summary.json", summary)
    report(summary)
    for key in [
        "final_status", "final_decision", "canonical_latest_date", "broad_price_latest_date",
        "feature_latest_date_technical_before", "feature_latest_date_momentum_before",
        "feature_rebuild_attempted", "feature_rebuild_succeeded", "feature_latest_date_technical_after",
        "feature_latest_date_momentum_after", "abcd_honest_latest_date", "target_rerun_date",
        "abcde_rerun_attempted", "abcde_rerun_succeeded", "a1_resolved_date", "b_resolved_date",
        "c_resolved_date", "d_resolved_date", "e_r1_resolved_date", "same_date_comparable_all_strategies",
        "official_adoption_allowed", "broker_action_allowed", "protected_outputs_modified",
    ]:
        print(f"{key}={summary[key]}")
    print(f"strategy_latest_dates={json.dumps(summary['strategy_latest_dates'], sort_keys=True)}")
    for key in ["a1_top20", "b_top20", "c_top20", "d_top20", "e_r1_top20", "a1_top50", "b_top50", "c_top50", "d_top50", "e_r1_top50"]:
        print(f"{key}={'|'.join(summary[key])}")
    for path in [OUT / tagged("abcde_overlap_top20_matrix_final_broad_{tag}.csv"), OUT / tagged("abcde_overlap_top50_matrix_final_broad_{tag}.csv")]:
        if path.is_file():
            print(rel(path))
            print(pd.read_csv(path).to_string(index=False))
    return summary


if __name__ == "__main__":
    run()
