#!/usr/bin/env python
"""V21.113 R1 recompute lineage and cache audit.

Research-only audit. Writes only under the stage output directory.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.113_R1_RECOMPUTE_LINEAGE_AND_CACHE_AUDIT"
OUT_REL = Path("outputs/v21/V21.113_R1_RECOMPUTE_LINEAGE_AND_CACHE_AUDIT")
OUT = ROOT / OUT_REL
FORCED = OUT / "forced_recompute"

V113 = ROOT / "outputs/v21/V21.113_LATEST_DATA_ABCD_RERUN_20260625_PRICE_REFRESH"
V113_SCRIPT = ROOT / "scripts/v21/v21_113_latest_data_abcd_rerun_20260625_price_refresh.py"
V112 = ROOT / "outputs/v21/V21.112_LATEST_DATA_ABCD_RERUN"
V112_R1 = ROOT / "outputs/v21/V21.112_R1_LATEST_DATA_ABCD_RERUN_20260624_PRICE_REFRESH"
V108_R2 = ROOT / "outputs/v21/V21.108_latest_data_multi_strategy_rerun/R2_archived_latest_strategy_rankings"
V108 = ROOT / "outputs/v21/V21.108_latest_data_multi_strategy_rerun"
PRICE = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"

EXPECTED_DATE = "2026-06-25"
STRATEGIES = [
    "A1_BASELINE_CONTROL",
    "B_STATIC_MOMENTUM_BLEND",
    "C_DYNAMIC_MOMENTUM_BLEND",
    "D_WEIGHT_OPTIMIZED_R1",
]
RANKING_NAMES = [f"{s}_latest_ranking.csv" for s in STRATEGIES]
DATE_COLUMNS = ["as_of_date", "date", "price_date", "ranking_date", "latest_price_date", "latest_date"]
SCORE_HINTS = ("score", "rank")


def clean(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text.lower() in {"nan", "nat", "none"} else text


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str] | None = None) -> None:
    rows = list(rows)
    if fields is None:
        fields = list(rows[0].keys()) if rows else ["empty"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, low_memory=False)


def csv_profile(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "path": rel(path),
            "exists": False,
            "modified_time_utc": "",
            "sha256": "",
            "row_count": 0,
            "column_count": 0,
            "columns": "",
            "score_columns": "",
        }
    frame = read_csv(path)
    score_cols = [c for c in frame.columns if any(h in c.lower() for h in SCORE_HINTS)]
    return {
        "path": rel(path),
        "exists": True,
        "modified_time_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        "sha256": sha256(path),
        "row_count": int(len(frame)),
        "column_count": int(len(frame.columns)),
        "columns": "|".join(map(str, frame.columns)),
        "score_columns": "|".join(score_cols),
    }


def max_date_in_frame(frame: pd.DataFrame) -> tuple[str, str]:
    found: list[str] = []
    cols: list[str] = []
    for col in frame.columns:
        if col.lower() in DATE_COLUMNS or col.lower().endswith("_date"):
            values = pd.to_datetime(frame[col], errors="coerce")
            if values.notna().any():
                found.append(values.max().strftime("%Y-%m-%d"))
                cols.append(col)
    return (max(found) if found else "", "|".join(cols))


def latest_price_date_and_hash() -> tuple[str, str]:
    if not PRICE.is_file():
        return "", ""
    latest = ""
    for chunk in pd.read_csv(PRICE, usecols=["date"], chunksize=500_000, low_memory=False):
        values = pd.to_datetime(chunk["date"], errors="coerce")
        if values.notna().any():
            latest = max(latest, values.max().strftime("%Y-%m-%d"))
    return latest, sha256(PRICE)


def ranking_path(strategy: str, base: Path, latest: bool = False) -> Path | None:
    candidates = []
    if latest:
        candidates.append(base / f"{strategy}_latest_ranking.csv")
    candidates.extend(
        [
            base / f"{strategy}_full_ranking.csv",
            base / strategy / "full_ranking.csv",
            base / f"ranking_full_{strategy}.csv",
            base / f"ranking_top50_{strategy}.csv",
            base / f"{strategy}_latest_ranking.csv",
        ]
    )
    for path in candidates:
        if path.is_file():
            return path
    return None


def prior_ranking_files() -> list[tuple[str, Path]]:
    roots = [
        ("V21.108_R2", V108_R2),
        ("V21.112", V112),
        ("V21.112_R1", V112_R1),
    ]
    for path in sorted((ROOT / "outputs/v21").glob("V21.066A*")):
        if path.is_dir():
            roots.append((path.name, path))
    rows: list[tuple[str, Path]] = []
    for label, base in roots:
        for strategy in STRATEGIES:
            path = ranking_path(strategy, base)
            if path:
                rows.append((f"{label}:{strategy}", path))
    return rows


def lineage_and_hash_rows() -> tuple[list[dict[str, Any]], int]:
    prior = [(label, path, sha256(path)) for label, path in prior_ranking_files()]
    rows: list[dict[str, Any]] = []
    exact = 0
    for name in RANKING_NAMES:
        current = V113 / name
        current_profile = csv_profile(current)
        strategy = name.replace("_latest_ranking.csv", "")
        source_v112 = V112 / f"{strategy}_full_ranking.csv"
        source_hash = sha256(source_v112) if source_v112.is_file() else ""
        for label, path, digest in prior:
            match = bool(current_profile["sha256"] and current_profile["sha256"] == digest)
            exact += 1 if match else 0
            rows.append(
                {
                    "v21_113_file": current_profile["path"],
                    "strategy": strategy,
                    "v21_113_exists": current_profile["exists"],
                    "v21_113_modified_time_utc": current_profile["modified_time_utc"],
                    "v21_113_sha256": current_profile["sha256"],
                    "v21_113_row_count": current_profile["row_count"],
                    "v21_113_columns": current_profile["columns"],
                    "v21_113_score_columns": current_profile["score_columns"],
                    "prior_label": label,
                    "prior_path": rel(path),
                    "prior_sha256": digest,
                    "exact_hash_match": match,
                    "known_v21_113_source_path_from_script": rel(source_v112),
                    "known_source_sha256": source_hash,
                    "known_source_exists": source_v112.is_file(),
                    "lineage_flag": "SOURCE_RANKING_REUSED_WITH_PRICE_DATE_REWRITE"
                    if source_v112.is_file()
                    else "SOURCE_UNKNOWN",
                }
            )
    return rows, exact


def d_score_identity_rows() -> tuple[list[dict[str, Any]], int, int]:
    current_path = V113 / "D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv"
    if not current_path.is_file():
        return [], 0, 0
    current = read_csv(current_path)
    current["ticker"] = current["ticker"].astype(str).str.upper().str.strip()
    current["rank"] = pd.to_numeric(current["rank"], errors="coerce")
    current["final_score"] = pd.to_numeric(current["final_score"], errors="coerce")
    cur20 = current.nsmallest(20, "rank")[["ticker", "rank", "final_score"]]
    rows: list[dict[str, Any]] = []
    max_exact = 0
    max_near = 0
    for label, base in [("V21.108_R2", V108_R2), ("V21.112", V112), ("V21.112_R1", V112_R1)]:
        old_path = ranking_path("D_WEIGHT_OPTIMIZED_R1", base)
        if not old_path:
            rows.append({"prior_run": label, "prior_path": "", "comparison_status": "MISSING_PRIOR_D_RANKING"})
            continue
        old = read_csv(old_path)
        old["ticker"] = old["ticker"].astype(str).str.upper().str.strip()
        old["rank"] = pd.to_numeric(old["rank"], errors="coerce")
        old["final_score"] = pd.to_numeric(old["final_score"], errors="coerce")
        old20 = old.nsmallest(20, "rank")[["ticker", "rank", "final_score"]]
        merged = cur20.merge(old20, on="ticker", how="inner", suffixes=("_v21_113", "_prior"))
        deltas = (merged["final_score_v21_113"] - merged["final_score_prior"]).abs()
        exact = int((deltas == 0).sum())
        near = int((merged["final_score_v21_113"].round(6) == merged["final_score_prior"].round(6)).sum())
        max_exact = max(max_exact, exact)
        max_near = max(max_near, near)
        rows.append(
            {
                "prior_run": label,
                "prior_path": rel(old_path),
                "top20_exact_ticker_overlap": int(len(merged)),
                "exact_score_equality_count": exact,
                "rounded_score_equality_count_6dp": near,
                "max_absolute_score_delta": float(deltas.max()) if len(deltas) else "",
                "median_absolute_score_delta": float(deltas.median()) if len(deltas) else "",
                "warning": "WARN_SCORE_STABILITY_REQUIRES_LINEAGE_PROOF" if near >= 15 else "",
                "comparison_status": "OK",
            }
        )
    return rows, max_exact, max_near


def discover_declared_inputs() -> list[Path]:
    paths: set[Path] = {PRICE, V113_SCRIPT}
    for strategy in STRATEGIES:
        paths.add(V112 / f"{strategy}_full_ranking.csv")
        paths.add(V112_R1 / f"{strategy}_latest_ranking.csv")
        candidate = V108_R2 / strategy / "full_ranking.csv"
        paths.add(candidate)
    for extra in [
        ROOT / "outputs/v21/momentum/V21_058_R4_REPAIRED_NEWLY_LISTED_MOMENTUM_LEDGER.csv",
        ROOT / "outputs/v21/experiments/momentum_dynamic/V21_059_R1_VARIANT_SCORE_COMPONENTS.csv",
        ROOT / "outputs/v21/experiments/momentum_dynamic/d_weight_optimized/D_WEIGHT_OPTIMIZED_R1_current_ranking.csv",
        V108 / "v21_108_latest_data_multi_strategy_rerun.py",
        V108 / "run_console_summary.json",
        V108_R2 / "manifest/archive_manifest.json",
        V112 / "latest_abcd_summary.json",
        V112_R1 / "latest_abcd_summary.json",
        V113 / "V21.113_latest_data_abcd_rerun_summary.json",
    ]:
        paths.add(extra)
    if V113_SCRIPT.is_file():
        text = V113_SCRIPT.read_text(encoding="utf-8")
        for match in re.findall(r"Path\(\"([^\"]+)\"\)|ROOT / \"([^\"]+)\"", text):
            raw = clean(match[0] or match[1])
            if raw:
                paths.add(ROOT / raw.replace("/", "\\"))
    return sorted(paths)


def input_manifest_and_freshness() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], int, str, str]:
    manifest: list[dict[str, Any]] = []
    freshness: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    latest_dates: list[str] = []
    for path in discover_declared_inputs():
        row = csv_profile(path) if path.suffix.lower() == ".csv" and path.exists() else {
            "path": rel(path),
            "exists": path.is_file(),
            "modified_time_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat() if path.is_file() else "",
            "sha256": sha256(path) if path.is_file() else "",
            "row_count": "",
            "column_count": "",
            "columns": "",
            "score_columns": "",
        }
        manifest.append(row)
        max_date = ""
        date_cols = ""
        if path.is_file() and path.suffix.lower() == ".csv":
            try:
                frame = read_csv(path)
                max_date, date_cols = max_date_in_frame(frame)
            except Exception as exc:
                date_cols = f"READ_ERROR:{exc}"
        elif path.is_file() and path.suffix.lower() == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                candidates = []
                for key, value in payload.items() if isinstance(payload, dict) else []:
                    if "date" in str(key).lower():
                        date = pd.to_datetime(clean(value), errors="coerce")
                        if not pd.isna(date):
                            candidates.append(date.strftime("%Y-%m-%d"))
                max_date = max(candidates) if candidates else ""
                date_cols = "|".join(k for k in payload.keys() if "date" in str(k).lower()) if isinstance(payload, dict) else ""
            except Exception as exc:
                date_cols = f"READ_ERROR:{exc}"
        if max_date:
            latest_dates.append(max_date)
        kind = "price_panel" if path == PRICE else "ranking_or_factor_cache" if any(
            token in rel(path).lower() for token in ["ranking", "momentum", "component", "v21.058", "v21_058", "v21.059", "v21_059", "v21.108", "v21_108", "v21.112"]
        ) else "script_or_metadata"
        predates = bool(max_date and max_date < EXPECTED_DATE)
        fresh_row = {
            "path": rel(path),
            "exists": path.is_file(),
            "input_kind": kind,
            "modified_time_utc": row["modified_time_utc"],
            "sha256": row["sha256"],
            "latest_date_columns_found": date_cols,
            "max_available_date": max_date,
            "predates_2026_06_25": predates,
            "stale_factor_cache_flag": predates and kind == "ranking_or_factor_cache",
        }
        freshness.append(fresh_row)
        if fresh_row["stale_factor_cache_flag"]:
            stale.append(
                {
                    **fresh_row,
                    "stale_reason": "RANKING_OR_FACTOR_INPUT_LATEST_DATE_BEFORE_2026_06_25",
                    "required_action": "DO_NOT_ARCHIVE_AS_TRUE_FULL_RECOMPUTE",
                }
            )
    return manifest, freshness, stale, len(stale), min(latest_dates) if latest_dates else "", max(latest_dates) if latest_dates else ""


def load_d(path: Path) -> pd.DataFrame:
    frame = read_csv(path)
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    frame["rank"] = pd.to_numeric(frame["rank"], errors="coerce")
    if "final_score" in frame:
        frame["final_score"] = pd.to_numeric(frame["final_score"], errors="coerce")
    return frame.sort_values(["rank", "ticker"], na_position="last").reset_index(drop=True)


def forced_recompute_attempt() -> tuple[list[dict[str, Any]], bool, bool, bool, str, int, int]:
    FORCED.mkdir(parents=True, exist_ok=True)
    reason = (
        "forced_recompute_not_possible: V21.113 hardcodes load_rankings() to "
        "outputs/v21/V21.112_LATEST_DATA_ABCD_RERUN/*_full_ranking.csv and only rewrites latest_price_date. "
        "No no-cache parameter or isolated output override exists for recomputing A/B/C/D factor, momentum, "
        "technical, and ranking inputs from the 2026-06-25 canonical price panel."
    )
    (FORCED / "forced_recompute_not_possible.md").write_text(reason + "\n", encoding="utf-8")
    v113_d = V113 / "D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv"
    source_d = V112 / "D_WEIGHT_OPTIMIZED_R1_full_ranking.csv"
    rows = [
        {
            "forced_recompute_attempted": True,
            "forced_recompute_succeeded": False,
            "forced_recompute_matches_v21_113": False,
            "forced_recompute_not_possible_reason": reason,
            "comparison_basis": "no forced no-cache recompute artifact was produced",
        }
    ]
    top20_overlap = 0
    top50_overlap = 0
    if v113_d.is_file() and source_d.is_file():
        current = load_d(v113_d)
        source = load_d(source_d)
        top20_overlap = len(set(current.nsmallest(20, "rank")["ticker"]) & set(source.nsmallest(20, "rank")["ticker"]))
        top50_overlap = len(set(current.nsmallest(50, "rank")["ticker"]) & set(source.nsmallest(50, "rank")["ticker"]))
        current.nsmallest(20, "rank").merge(
            source.nsmallest(20, "rank"), on="ticker", how="outer", suffixes=("_v21_113", "_source_v112")
        ).to_csv(OUT / "D_top20_v21_113_vs_forced_recompute.csv", index=False)
        current.nsmallest(50, "rank").merge(
            source.nsmallest(50, "rank"), on="ticker", how="outer", suffixes=("_v21_113", "_source_v112")
        ).to_csv(OUT / "D_top50_v21_113_vs_forced_recompute.csv", index=False)
        rows[0]["source_v112_top20_overlap_used_as_lineage_proxy"] = top20_overlap
        rows[0]["source_v112_top50_overlap_used_as_lineage_proxy"] = top50_overlap
    else:
        write_csv(OUT / "D_top20_v21_113_vs_forced_recompute.csv", [], ["empty"])
        write_csv(OUT / "D_top50_v21_113_vs_forced_recompute.csv", [], ["empty"])
    return rows, True, False, False, reason, top20_overlap, top50_overlap


def entrants_removals_rows(label: str, comparator: Path | None) -> tuple[list[dict[str, Any]], bool]:
    current_path = V113 / "D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv"
    if not current_path.is_file() or comparator is None or not comparator.is_file():
        return [{"comparison": label, "status": "MISSING_INPUT", "message": "NO_MEANINGFUL_RANK_MOVEMENT"}], True
    current = load_d(current_path)
    old = load_d(comparator)
    rows: list[dict[str, Any]] = []
    no_movement = True
    for n in [20, 50]:
        cur = set(current.nsmallest(n, "rank")["ticker"])
        prev = set(old.nsmallest(n, "rank")["ticker"])
        entrants = sorted(cur - prev)
        removals = sorted(prev - cur)
        if entrants or removals:
            no_movement = False
        for ticker in entrants:
            rows.append({"comparison": label, "view": f"top{n}", "change_type": "ENTRANT", "ticker": ticker})
        for ticker in removals:
            rows.append({"comparison": label, "view": f"top{n}", "change_type": "REMOVAL", "ticker": ticker})
    if not rows:
        rows.append({"comparison": label, "view": "D_TOP20_AND_TOP50", "change_type": "NO_MEANINGFUL_RANK_MOVEMENT", "ticker": ""})
    return rows, no_movement


def source_script_uses_v112_cache() -> bool:
    if not V113_SCRIPT.is_file():
        return False
    tree = ast.parse(V113_SCRIPT.read_text(encoding="utf-8"))
    text = ast.get_source_segment(V113_SCRIPT.read_text(encoding="utf-8"), tree) or V113_SCRIPT.read_text(encoding="utf-8")
    return "V112 / f\"{strategy}_full_ranking.csv\"" in text or "V112 ranking inputs" in text


def write_report(summary: dict[str, Any], forced_reason: str) -> None:
    answer = (
        "V21.113 did not prove a full ABCD recompute from 2026-06-25 data. "
        "The wrapper refreshed the price panel and reused V21.112 ranking files as downstream inputs."
    )
    if summary["FINAL_STATUS"] == "PASS_V21_113_R1_FULL_RECOMPUTE_CONFIRMED":
        answer = "V21.113 fully recomputed ABCD rankings from 2026-06-25 data."
    lines = [
        f"# {STAGE}",
        "",
        f"FINAL_STATUS={summary['FINAL_STATUS']}",
        f"DECISION={summary['DECISION']}",
        f"latest_price_date={summary['latest_price_date']}",
        "",
        "## Direct Answer",
        "Did V21.113 fully recompute ABCD rankings from 2026-06-25 data, or did it only refresh prices?",
        "",
        answer,
        "",
        "## Evidence",
        f"- canonical_price_panel_latest_date={summary['canonical_price_panel_latest_date']}",
        f"- ranking_hash_exact_match_with_prior_count={summary['ranking_hash_exact_match_with_prior_count']}",
        f"- stale_factor_input_count={summary['stale_factor_input_count']}",
        f"- factor_inputs_latest_date_min={summary['factor_inputs_latest_date_min']}",
        f"- factor_inputs_latest_date_max={summary['factor_inputs_latest_date_max']}",
        f"- forced_recompute_attempted={str(summary['forced_recompute_attempted']).lower()}",
        f"- forced_recompute_succeeded={str(summary['forced_recompute_succeeded']).lower()}",
        f"- forced_recompute_matches_v21_113={str(summary['forced_recompute_matches_v21_113']).lower()}",
        "",
        "## Forced Recompute",
        forced_reason,
        "",
        "## Controls",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "protected_outputs_modified=false",
        "",
        "## Output Files",
        "- lineage_input_file_manifest.csv",
        "- ranking_file_hash_comparison.csv",
        "- d_score_identity_vs_prior_runs.csv",
        "- factor_input_freshness_audit.csv",
        "- forced_recompute_comparison.csv",
        "- stale_factor_cache_report.csv",
    ]
    (OUT / "V21.113_R1_recompute_lineage_and_cache_audit_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    latest_price_date, price_hash = latest_price_date_and_hash()
    ranking_hash_rows, exact_hash_count = lineage_and_hash_rows()
    write_csv(OUT / "ranking_file_hash_comparison.csv", ranking_hash_rows)

    d_identity, d_exact, d_near = d_score_identity_rows()
    write_csv(OUT / "d_score_identity_vs_prior_runs.csv", d_identity)

    manifest, freshness, stale, stale_count, factor_min, factor_max = input_manifest_and_freshness()
    write_csv(OUT / "lineage_input_file_manifest.csv", manifest)
    write_csv(OUT / "factor_input_freshness_audit.csv", freshness)
    write_csv(OUT / "stale_factor_cache_report.csv", stale, list(stale[0].keys()) if stale else [
        "path", "exists", "input_kind", "modified_time_utc", "sha256", "latest_date_columns_found",
        "max_available_date", "predates_2026_06_25", "stale_factor_cache_flag", "stale_reason", "required_action",
    ])

    forced_rows, forced_attempted, forced_succeeded, forced_matches, forced_reason, d20_forced, d50_forced = forced_recompute_attempt()
    write_csv(OUT / "forced_recompute_comparison.csv", forced_rows)

    prior108 = ranking_path("D_WEIGHT_OPTIMIZED_R1", V108_R2)
    prior112 = ranking_path("D_WEIGHT_OPTIMIZED_R1", V112_R1) or ranking_path("D_WEIGHT_OPTIMIZED_R1", V112)
    original = V113 / "D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv"
    er108, no108 = entrants_removals_rows("V21.108_R2", prior108)
    er112, no112 = entrants_removals_rows("V21.112_R1", prior112)
    er113, no113 = entrants_removals_rows("V21.113_original", original)
    write_csv(OUT / "D_entrants_removals_vs_V21_108_R2.csv", er108)
    write_csv(OUT / "D_entrants_removals_vs_V21_112_R1.csv", er112)
    write_csv(OUT / "D_entrants_removals_vs_V21_113_original.csv", er113)

    v21_113_files_found = sum(1 for name in RANKING_NAMES if (V113 / name).is_file())
    copied_lineage = source_script_uses_v112_cache()
    if latest_price_date >= EXPECTED_DATE and (stale_count > 0 or copied_lineage):
        final_status = "BLOCKED_V21_113_R1_STALE_FACTOR_CACHE"
        decision = "DO_NOT_ARCHIVE_AS_TRUE_FULL_RECOMPUTE"
    elif forced_succeeded and forced_matches and stale_count == 0:
        final_status = "PASS_V21_113_R1_FULL_RECOMPUTE_CONFIRMED"
        decision = "LATEST_DATA_ABCD_FULL_RECOMPUTE_CONFIRMED_RESEARCH_ONLY"
    elif forced_attempted and not forced_succeeded:
        final_status = "WARN_V21_113_R1_FORCED_RECOMPUTE_NOT_POSSIBLE"
        decision = "DO_NOT_ARCHIVE_WITHOUT_ADDITIONAL_LINEAGE_PROOF"
    else:
        final_status = "WARN_V21_113_R1_V21_113_USED_PARTIAL_CACHE"
        decision = "DO_NOT_ARCHIVE_AS_TRUE_FULL_RECOMPUTE"

    summary = {
        "stage": STAGE,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "latest_price_date": latest_price_date,
        "canonical_price_panel_hash": price_hash,
        "canonical_price_panel_latest_date": latest_price_date,
        "v21_113_ranking_files_found": v21_113_files_found,
        "ranking_hash_exact_match_with_prior_count": exact_hash_count,
        "stale_factor_input_count": stale_count,
        "factor_inputs_latest_date_min": factor_min,
        "factor_inputs_latest_date_max": factor_max,
        "forced_recompute_attempted": forced_attempted,
        "forced_recompute_succeeded": forced_succeeded,
        "forced_recompute_matches_v21_113": forced_matches,
        "forced_recompute_not_possible_reason": forced_reason,
        "d_top20_overlap_v21_113_vs_forced": d20_forced,
        "d_top50_overlap_v21_113_vs_forced": d50_forced,
        "d_score_exact_match_count_vs_prior": d_exact,
        "d_score_near_match_count_vs_prior_6dp": d_near,
        "no_meaningful_rank_movement": bool(no108 and no112 and no113),
        "v21_113_script_reuses_v112_ranking_inputs": copied_lineage,
        "protected_outputs_modified": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
        "report_path": rel(OUT / "V21.113_R1_recompute_lineage_and_cache_audit_report.md"),
    }
    write_json(OUT / "V21.113_R1_recompute_lineage_and_cache_audit_summary.json", summary)
    write_report(summary, forced_reason)
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    run()
