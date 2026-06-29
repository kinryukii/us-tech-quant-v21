#!/usr/bin/env python
"""V21.138 E_R1 metadata coverage repair and concentration re-audit."""

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
STAGE = "V21.138_E_R1_METADATA_COVERAGE_REPAIR_AND_REAUDIT"
OUT = ROOT / "outputs/v21/V21.138_E_R1_METADATA_COVERAGE_REPAIR_AND_REAUDIT"
A1_SOURCE = ROOT / "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE/A1_BASELINE_CONTROL_latest_ranking.csv"
E_SOURCE = ROOT / "outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR/e_r1_full_ranking.csv"
V137_SUMMARY = ROOT / "outputs/v21/V21.137_E_R1_RISK_DECOMPOSITION_VS_A1/e_r1_risk_decomposition_summary.json"
V137_CONC = ROOT / "outputs/v21/V21.137_E_R1_RISK_DECOMPOSITION_VS_A1/e_r1_vs_a1_concentration_comparison.csv"
SEARCH_ROOT = ROOT / "outputs/v21"
TICKER_COLS = ["ticker_norm", "ticker", "symbol"]
SECTOR_COLS = ["sector", "gics_sector", "Sector", "GICS Sector"]
INDUSTRY_COLS = ["industry", "gics_industry", "Industry", "GICS Industry"]
SUB_INDUSTRY_COLS = ["sub_industry", "gics_sub_industry", "Sub-Industry", "GICS Sub-Industry"]
ALLOWED_STATUS = {"CLEARED", "NON_MATERIAL_REMAINING_GAPS", "MATERIAL_METADATA_GAPS_REMAIN", "BLOCKED_INSUFFICIENT_METADATA"}
ALLOWED_DECISIONS = {
    "E_R1_METADATA_REPAIRED_RISK_PROFILE_ACCEPTABLE_WAIT_MATURITY",
    "E_R1_METADATA_GAPS_NON_MATERIAL_WAIT_MATURITY",
    "E_R1_METADATA_GAPS_MATERIAL_REVIEW_REQUIRED",
    "E_R1_METADATA_INSUFFICIENT_BLOCKED",
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
    allowed_prefix = "?? outputs/v21/V21.138_E_R1_METADATA_COVERAGE_REPAIR_AND_REAUDIT/"
    allowed_scripts = {
        "?? scripts/v21/v21_138_e_r1_metadata_coverage_repair_and_reaudit.py",
        "?? scripts/v21/test_v21_138_e_r1_metadata_coverage_repair_and_reaudit.py",
        "?? scripts/v21/run_v21_138_e_r1_metadata_coverage_repair_and_reaudit.ps1",
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


def first_col(cols: list[str], choices: list[str]) -> str:
    lower = {c.lower(): c for c in cols}
    for choice in choices:
        if choice.lower() in lower:
            return lower[choice.lower()]
    return ""


def load_rankings() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, set[str]]]:
    a1 = pd.read_csv(A1_SOURCE, low_memory=False)
    a1["ticker_norm"] = a1["ticker"].map(ticker_norm)
    e = pd.read_csv(E_SOURCE, low_memory=False)
    e["ticker_norm"] = e["ticker_norm"].map(ticker_norm)
    sets = {
        "A1_top20": set(a1.sort_values(["rank", "ticker_norm"]).head(20)["ticker_norm"]),
        "E_R1_top20": set(e.sort_values(["rank", "ticker_norm"]).head(20)["ticker_norm"]),
        "A1_top50": set(a1.sort_values(["rank", "ticker_norm"]).head(50)["ticker_norm"]),
        "E_R1_top50": set(e.sort_values(["rank", "ticker_norm"]).head(50)["ticker_norm"]),
    }
    sets["union_top20"] = sets["A1_top20"] | sets["E_R1_top20"]
    sets["union_top50"] = sets["A1_top50"] | sets["E_R1_top50"]
    return a1, e, sets


def discover_metadata(sets: dict[str, set[str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    inventory = []
    assignments = []
    for path in SEARCH_ROOT.rglob("*.csv"):
        if OUT in path.parents:
            continue
        try:
            header = pd.read_csv(path, nrows=0)
        except Exception:
            continue
        cols = list(header.columns)
        ticker_col = first_col(cols, TICKER_COLS)
        sector_col = first_col(cols, SECTOR_COLS)
        industry_col = first_col(cols, INDUSTRY_COLS)
        sub_col = first_col(cols, SUB_INDUSTRY_COLS)
        if not ticker_col or not (sector_col or industry_col or sub_col):
            continue
        try:
            frame = pd.read_csv(path, low_memory=False)
        except Exception:
            continue
        if ticker_col not in frame.columns:
            continue
        frame["ticker_norm"] = frame[ticker_col].map(ticker_norm)
        frame = frame[frame["ticker_norm"].ne("") & frame["ticker_norm"].ne("NAN")].copy()
        if frame.empty:
            continue
        sector_nonnull = int(frame[sector_col].notna().sum()) if sector_col else 0
        industry_nonnull = int(frame[industry_col].notna().sum()) if industry_col else 0
        unique_count = int(frame["ticker_norm"].nunique())
        coverage = {name: len(vals & set(frame["ticker_norm"])) / len(vals) if vals else 0 for name, vals in sets.items()}
        priority = (
            100 * coverage["union_top50"]
            + 25 * coverage["union_top20"]
            + 10 * (sector_nonnull / len(frame))
            + 10 * (industry_nonnull / len(frame))
            - 2 * int(frame["ticker_norm"].duplicated().sum())
        )
        inventory.append({
            "path": rel(path),
            "exists": True,
            "row_count": len(frame),
            "detected_ticker_column": ticker_col,
            "detected_sector_column": sector_col,
            "detected_industry_column": industry_col,
            "detected_sub_industry_column": sub_col,
            "unique_ticker_count": unique_count,
            "non_null_sector_count": sector_nonnull,
            "non_null_industry_count": industry_nonnull,
            "coverage_A1_top20": coverage["A1_top20"],
            "coverage_E_R1_top20": coverage["E_R1_top20"],
            "coverage_A1_top50": coverage["A1_top50"],
            "coverage_E_R1_top50": coverage["E_R1_top50"],
            "duplicate_ticker_count": int(frame["ticker_norm"].duplicated().sum()),
            "source_priority_score": priority,
        })
        for row in frame.to_dict("records"):
            sector = str(row.get(sector_col, "") or "").strip() if sector_col else ""
            industry = str(row.get(industry_col, row.get(sub_col, "")) or "").strip() if industry_col or sub_col else ""
            if sector or industry:
                assignments.append({"ticker_norm": row["ticker_norm"], "sector": sector or "UNKNOWN", "industry": industry or "UNKNOWN", "source_path": rel(path), "source_priority_score": priority})
    return sorted(inventory, key=lambda x: x["source_priority_score"], reverse=True), assignments


def consolidate(assignments: list[dict[str, Any]], needed: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for row in assignments:
        if row["ticker_norm"] in needed:
            by_ticker.setdefault(row["ticker_norm"], []).append(row)
    bridge = []
    conflicts = []
    for ticker, rows in by_ticker.items():
        rows = sorted(rows, key=lambda r: r["source_priority_score"], reverse=True)
        primary = rows[0]
        sectors = sorted({r["sector"] for r in rows if r["sector"] and r["sector"] != "UNKNOWN"})
        industries = sorted({r["industry"] for r in rows if r["industry"] and r["industry"] != "UNKNOWN"})
        if len(sectors) > 1 or len(industries) > 1:
            conflicts.append({"ticker_norm": ticker, "sector_values": "|".join(sectors), "industry_values": "|".join(industries), "source_paths": "|".join(sorted({r["source_path"] for r in rows}))})
        bridge.append({"ticker_norm": ticker, "sector": primary["sector"], "industry": primary["industry"], "primary_source_path": primary["source_path"], "source_priority_score": primary["source_priority_score"], "conflict_flag": len(sectors) > 1 or len(industries) > 1})
    present = {r["ticker_norm"] for r in bridge}
    missing = [{"ticker_norm": t, "missing_sector": True, "missing_industry": True} for t in sorted(needed - present)]
    return sorted(bridge, key=lambda r: r["ticker_norm"]), conflicts, missing


def hhi(vals: pd.Series) -> float:
    shares = vals.fillna("UNKNOWN").value_counts(normalize=True)
    return float((shares ** 2).sum()) if len(shares) else math.nan


def coverage_rows(sets: dict[str, set[str]], bridge: pd.DataFrame, conflicts: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    bset = set(bridge["ticker_norm"]) if not bridge.empty else set()
    cset = set(conflicts["ticker_norm"]) if not conflicts.empty else set()
    for name, vals in sets.items():
        if not name.startswith(("A1", "E_R1", "union")):
            continue
        sub = bridge[bridge["ticker_norm"].isin(vals)] if not bridge.empty else pd.DataFrame()
        sector_present = set(sub[sub["sector"].ne("UNKNOWN")]["ticker_norm"]) if not sub.empty else set()
        industry_present = set(sub[sub["industry"].ne("UNKNOWN")]["ticker_norm"]) if not sub.empty else set()
        missing = sorted(vals - (sector_present & industry_present))
        rows.append({"coverage_group": name, "sector_coverage_ratio": len(sector_present) / len(vals), "industry_coverage_ratio": len(industry_present) / len(vals), "missing_sector_ticker_count": len(vals - sector_present), "missing_industry_ticker_count": len(vals - industry_present), "missing_ticker_list": "|".join(missing), "conflict_ticker_count": len(vals & cset), "conflict_ticker_list": "|".join(sorted(vals & cset))})
    return rows


def concentration(strategy: str, bucket: str, tickers: list[str], bridge: pd.DataFrame) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sub = pd.DataFrame({"ticker_norm": tickers}).merge(bridge[["ticker_norm", "sector", "industry"]], on="ticker_norm", how="left").fillna("UNKNOWN")
    rows = []
    for exp in ["sector", "industry"]:
        for rank, (name, count) in enumerate(sub[exp].value_counts().items(), start=1):
            rows.append({"strategy": strategy, "bucket": bucket, "exposure_type": exp, "bucket_name": name, "count": int(count), "weight": count / len(sub), "rank": rank})
    sector_counts = sub["sector"].value_counts(normalize=True)
    industry_counts = sub["industry"].value_counts(normalize=True)
    return {"strategy": strategy, "bucket": bucket, "top_sector": sector_counts.idxmax(), "top_sector_weight": float(sector_counts.max()), "top_industry": industry_counts.idxmax(), "top_industry_weight": float(industry_counts.max()), "unique_sector_count": int(sub["sector"].nunique()), "unique_industry_count": int(sub["industry"].nunique()), "sector_hhi": hhi(sub["sector"]), "industry_hhi": hhi(sub["industry"])}, rows


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    baseline_status = git_status()
    protected = [p for p in [A1_SOURCE, E_SOURCE, V137_SUMMARY, V137_CONC] if p.is_file()]
    baseline_hashes = {rel(p): sha256(p) for p in protected}
    a1, e, sets = load_rankings()
    inventory, assignments = discover_metadata(sets)
    bridge_rows, conflict_rows, missing_rows = consolidate(assignments, sets["union_top50"])
    write_csv(OUT / "metadata_source_inventory.csv", inventory)
    write_csv(OUT / "consolidated_sector_industry_metadata_bridge.csv", bridge_rows)
    write_csv(OUT / "metadata_conflict_audit.csv", conflict_rows)
    write_csv(OUT / "metadata_missing_ticker_audit.csv", missing_rows)
    bridge = pd.DataFrame(bridge_rows)
    conflicts = pd.DataFrame(conflict_rows)
    coverage = coverage_rows(sets, bridge, conflicts)
    write_csv(OUT / "metadata_coverage_reaudit.csv", coverage)
    conc_metrics = []
    exposure = {"top20": [], "top50": []}
    for bucket, n in [("top20", 20), ("top50", 50)]:
        for strategy, frame in [("A1", a1), ("E_R1", e)]:
            tickers = frame.sort_values(["rank", "ticker_norm"]).head(n)["ticker_norm"].tolist()
            metric, rows = concentration(strategy, bucket, tickers, bridge if not bridge.empty else pd.DataFrame(columns=["ticker_norm","sector","industry"]))
            conc_metrics.append(metric); exposure[bucket].extend(rows)
    deltas = []
    cm = pd.DataFrame(conc_metrics)
    for bucket in ["top20", "top50"]:
        a = cm[(cm["strategy"].eq("A1")) & (cm["bucket"].eq(bucket))].iloc[0]
        er = cm[(cm["strategy"].eq("E_R1")) & (cm["bucket"].eq(bucket))].iloc[0]
        row = {"bucket": bucket, "A1_top_sector": a["top_sector"], "E_R1_top_sector": er["top_sector"], "A1_top_sector_weight": a["top_sector_weight"], "E_R1_top_sector_weight": er["top_sector_weight"], "delta_top_sector_weight": er["top_sector_weight"] - a["top_sector_weight"], "A1_top_industry": a["top_industry"], "E_R1_top_industry": er["top_industry"], "A1_top_industry_weight": a["top_industry_weight"], "E_R1_top_industry_weight": er["top_industry_weight"], "delta_top_industry_weight": er["top_industry_weight"] - a["top_industry_weight"], "A1_unique_sector_count": a["unique_sector_count"], "E_R1_unique_sector_count": er["unique_sector_count"], "A1_unique_industry_count": a["unique_industry_count"], "E_R1_unique_industry_count": er["unique_industry_count"], "A1_sector_hhi": a["sector_hhi"], "E_R1_sector_hhi": er["sector_hhi"], "delta_sector_hhi": er["sector_hhi"] - a["sector_hhi"], "A1_industry_hhi": a["industry_hhi"], "E_R1_industry_hhi": er["industry_hhi"], "delta_industry_hhi": er["industry_hhi"] - a["industry_hhi"]}
        deltas.append(row)
    write_csv(OUT / "e_r1_vs_a1_concentration_reaudit.csv", deltas)
    write_csv(OUT / "e_r1_sector_industry_reaudit_top20.csv", exposure["top20"])
    write_csv(OUT / "e_r1_sector_industry_reaudit_top50.csv", exposure["top50"])
    cov_map = {r["coverage_group"]: r for r in coverage}
    min_top20 = min(cov_map["A1_top20"]["sector_coverage_ratio"], cov_map["A1_top20"]["industry_coverage_ratio"], cov_map["E_R1_top20"]["sector_coverage_ratio"], cov_map["E_R1_top20"]["industry_coverage_ratio"])
    min_top50 = min(cov_map["A1_top50"]["sector_coverage_ratio"], cov_map["A1_top50"]["industry_coverage_ratio"], cov_map["E_R1_top50"]["sector_coverage_ratio"], cov_map["E_R1_top50"]["industry_coverage_ratio"])
    if min_top20 >= 0.95 and min_top50 >= 0.95:
        warn_status = "CLEARED"; final_status = "PASS_V21_138_E_R1_METADATA_WARNING_CLEARED"; decision = "E_R1_METADATA_REPAIRED_RISK_PROFILE_ACCEPTABLE_WAIT_MATURITY"
    elif min_top20 >= 0.90 and min_top50 >= 0.80 and all(abs(r["delta_top_sector_weight"]) <= 0.10 and abs(r["delta_top_industry_weight"]) <= 0.10 for r in deltas):
        warn_status = "NON_MATERIAL_REMAINING_GAPS"; final_status = "PARTIAL_PASS_V21_138_E_R1_METADATA_NON_MATERIAL_GAPS"; decision = "E_R1_METADATA_GAPS_NON_MATERIAL_WAIT_MATURITY"
    elif min_top20 < 0.50 or min_top50 < 0.50:
        warn_status = "BLOCKED_INSUFFICIENT_METADATA"; final_status = "BLOCKED_V21_138_E_R1_METADATA_INSUFFICIENT"; decision = "E_R1_METADATA_INSUFFICIENT_BLOCKED"
    else:
        warn_status = "MATERIAL_METADATA_GAPS_REMAIN"; final_status = "WARN_V21_138_E_R1_METADATA_MATERIAL_GAPS"; decision = "E_R1_METADATA_GAPS_MATERIAL_REVIEW_REQUIRED"
    warnings = []
    if warn_status != "CLEARED":
        warnings.append(warn_status)
    post_hashes = {rel(p): sha256(p) for p in protected}
    prot_mod = baseline_hashes != post_hashes or protected_modified(git_status(), baseline_status)
    summary = {"stage": STAGE, "FINAL_STATUS": final_status, "DECISION": decision, "ranking_date": load_json(V137_SUMMARY).get("ranking_date", "2026-06-26"), "A1_source_path": rel(A1_SOURCE), "E_R1_source_path": rel(E_SOURCE), "metadata_sources_discovered": len(inventory), "best_metadata_sources_used": "|".join(sorted({r["primary_source_path"] for r in bridge_rows})[:10]), "sector_coverage_ratio_min_top20": min_top20, "industry_coverage_ratio_min_top50": min_top50, "missing_tickers": "|".join(sorted({r["ticker_norm"] for r in missing_rows})), "conflict_tickers": "|".join(sorted({r["ticker_norm"] for r in conflict_rows})), "metadata_warning_status": warn_status, "v21_137_warning_resolution": "cleared" if warn_status == "CLEARED" else ("downgraded" if warn_status == "NON_MATERIAL_REMAINING_GAPS" else "remains_material_or_blocked"), "warnings": "|".join(warnings) if warnings else "none", "protected_outputs_modified": bool(prot_mod), "official_adoption_allowed": False, "broker_action_allowed": False, "research_only": True, "E_adoption_allowed": False, "report_path": rel(OUT / "V21.138_E_R1_METADATA_COVERAGE_REPAIR_AND_REAUDIT_report.txt")}
    write_json(OUT / "e_r1_metadata_reaudit_summary.json", summary)
    report = [STAGE, f"FINAL_STATUS={final_status}", f"DECISION={decision}", f"ranking_date={summary['ranking_date']}", f"A1_source_path={rel(A1_SOURCE)}", f"E_R1_source_path={rel(E_SOURCE)}", f"metadata_sources_discovered={len(inventory)}", f"best_metadata_sources_used={summary['best_metadata_sources_used']}", "metadata coverage", pd.DataFrame(coverage).to_csv(index=False).strip(), f"missing_tickers={summary['missing_tickers']}", f"conflict_tickers={summary['conflict_tickers']}", "A1 vs E_R1 concentration comparison after repair", pd.DataFrame(deltas).to_csv(index=False).strip(), f"metadata_warning_status={warn_status}", f"v21_137_warning_resolution={summary['v21_137_warning_resolution']}", f"warnings={summary['warnings']}", "protected_outputs_modified=false", "official_adoption_allowed=false", "broker_action_allowed=false", "research_only=true", "E_adoption_allowed=false"]
    (OUT / "V21.138_E_R1_METADATA_COVERAGE_REPAIR_AND_REAUDIT_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(STAGE); print(f"FINAL_STATUS={final_status}"); print(f"DECISION={decision}"); print(f"report_path={summary['report_path']}"); print(f"metadata_warning_status={warn_status}"); print(f"best_metadata_sources_used={summary['best_metadata_sources_used']}"); print(f"sector_coverage_ratio={min_top20}"); print(f"industry_coverage_ratio={min_top50}"); print(f"missing_tickers={summary['missing_tickers']}"); print(f"conflict_tickers={summary['conflict_tickers']}"); print("concentration_summary=" + pd.DataFrame(deltas).to_json(orient="records")); print(f"warnings={summary['warnings']}")
    return summary


if __name__ == "__main__":
    run()
