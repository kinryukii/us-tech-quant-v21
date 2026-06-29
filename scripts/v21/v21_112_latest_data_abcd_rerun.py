#!/usr/bin/env python
"""V21.112 research-only latest-data ABCD rerun archive.

This wrapper preserves the V21.108-R2 latest-data strategy definitions and
archives a fresh isolated package without mutating official or protected output.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.112_LATEST_DATA_ABCD_RERUN"
OUT_REL = Path("outputs/v21/V21.112_LATEST_DATA_ABCD_RERUN")
OUT = ROOT / OUT_REL
SOURCE_REL = Path("outputs/v21/V21.108_latest_data_multi_strategy_rerun/R2_archived_latest_strategy_rankings")
SOURCE = ROOT / SOURCE_REL
SOURCE_MANIFEST = SOURCE / "manifest/archive_manifest.json"
V111_EXPOSURE_TOP20 = ROOT / "outputs/v21/V21.111_D_FAILURE_MODE_DECOMPOSITION/exposure_top20.csv"
V111_EXPOSURE_TOP50 = ROOT / "outputs/v21/V21.111_D_FAILURE_MODE_DECOMPOSITION/exposure_top50.csv"

STRATEGIES = [
    "A1_BASELINE_CONTROL",
    "B_STATIC_MOMENTUM_BLEND",
    "C_DYNAMIC_MOMENTUM_BLEND",
    "D_WEIGHT_OPTIMIZED_R1",
]
SHORT = {
    "A1_BASELINE_CONTROL": "A1",
    "B_STATIC_MOMENTUM_BLEND": "B",
    "C_DYNAMIC_MOMENTUM_BLEND": "C",
    "D_WEIGHT_OPTIMIZED_R1": "D",
}

REQUIRED_FILES = [
    "latest_abcd_summary.json",
    "latest_abcd_report.txt",
    "A1_BASELINE_CONTROL_full_ranking.csv",
    "B_STATIC_MOMENTUM_BLEND_full_ranking.csv",
    "C_DYNAMIC_MOMENTUM_BLEND_full_ranking.csv",
    "D_WEIGHT_OPTIMIZED_R1_full_ranking.csv",
    "A1_BASELINE_CONTROL_top20.csv",
    "B_STATIC_MOMENTUM_BLEND_top20.csv",
    "C_DYNAMIC_MOMENTUM_BLEND_top20.csv",
    "D_WEIGHT_OPTIMIZED_R1_top20.csv",
    "A1_BASELINE_CONTROL_top50.csv",
    "B_STATIC_MOMENTUM_BLEND_top50.csv",
    "C_DYNAMIC_MOMENTUM_BLEND_top50.csv",
    "D_WEIGHT_OPTIMIZED_R1_top50.csv",
    "top20_overlap_matrix.csv",
    "top50_overlap_matrix.csv",
    "sector_industry_concentration.csv",
    "excluded_tickers.csv",
    "validation_manifest.json",
]


def clean(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text.lower() in {"nan", "nat", "none"} else text


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


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
    def default(value: Any) -> Any:
        if pd.isna(value):
            return None
        return str(value)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=default) + "\n", encoding="utf-8")


def protected_paths() -> list[Path]:
    paths: set[Path] = set()
    for base in [ROOT / "outputs/v21", ROOT / "outputs/v20", ROOT / "outputs/v18", ROOT / "data"]:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if OUT in path.parents:
                continue
            name = rel(path).lower().replace("-", "_").replace(" ", "_")
            protected_version = any(token in name for token in ["v21.060", "v21_060", "v21.066", "v21_066", "v21.108", "v21_108", "v21.111", "v21_111"])
            protected_kind = any(token in name for token in ["official", "broker", "order", "execution", "trade_action", "adoption", "real_book"])
            if protected_version or protected_kind:
                paths.add(path.resolve())
    return sorted(paths)


def hash_map(paths: Iterable[Path]) -> dict[str, str]:
    return {rel(path): sha256(path) for path in paths if path.is_file()}


def load_source_manifest() -> dict[str, Any]:
    if SOURCE_MANIFEST.is_file():
        return json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    return {}


def eligible_mask(frame: pd.DataFrame) -> pd.Series:
    if "eligible_flag" not in frame:
        return pd.Series([True] * len(frame), index=frame.index)
    values = frame["eligible_flag"].astype(str).str.upper().str.strip()
    return values.isin(["TRUE", "1", "YES"])


def normalize_ranking(frame: pd.DataFrame, strategy: str) -> pd.DataFrame:
    out = frame.copy()
    out["strategy"] = strategy
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    out["rank"] = pd.to_numeric(out["rank"], errors="coerce")
    if "final_score" in out:
        out["final_score"] = pd.to_numeric(out["final_score"], errors="coerce")
    if "eligible_flag" not in out:
        out["eligible_flag"] = True
    if "eligibility_exclusion_reason" not in out:
        out["eligibility_exclusion_reason"] = ""
    if "research_only" not in out:
        out["research_only"] = "TRUE"
    return out.sort_values(["rank", "ticker"], na_position="last").reset_index(drop=True)


def load_rankings() -> dict[str, pd.DataFrame]:
    rankings: dict[str, pd.DataFrame] = {}
    missing: list[str] = []
    for strategy in STRATEGIES:
        path = SOURCE / strategy / "full_ranking.csv"
        if not path.is_file():
            missing.append(rel(path))
            continue
        rankings[strategy] = normalize_ranking(pd.read_csv(path, low_memory=False), strategy)
    if missing:
        raise FileNotFoundError("Missing V21.108-R2 ranking inputs: " + ", ".join(missing))
    return rankings


def topn(frame: pd.DataFrame, n: int) -> pd.DataFrame:
    eligible = frame[eligible_mask(frame)].copy()
    return eligible.nsmallest(min(n, len(eligible)), "rank")


def overlap_matrix(rankings: dict[str, pd.DataFrame], n: int) -> list[dict[str, Any]]:
    sets = {strategy: set(topn(frame, n)["ticker"]) for strategy, frame in rankings.items()}
    rows = []
    for left in STRATEGIES:
        row = {"strategy": SHORT[left]}
        for right in STRATEGIES:
            row[SHORT[right]] = len(sets[left] & sets[right])
        rows.append(row)
    return rows


def classification_source() -> tuple[pd.DataFrame, str]:
    patterns = [
        "outputs/v21/**/**CLASSIFICATION_MASTER*.csv",
        "outputs/v21/**/*classification*.csv",
        "configs/v21/instrument_listing_reference.csv",
    ]
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend([p for p in ROOT.glob(pattern) if p.is_file()])
    for path in sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            frame = pd.read_csv(path, low_memory=False)
        except Exception:
            continue
        if "ticker" in frame.columns:
            frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
            return frame, rel(path)
    return pd.DataFrame(), ""


def add_classification(frame: pd.DataFrame, classification: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for col in ["sector", "industry"]:
        if col not in out:
            out[col] = ""
    if not classification.empty:
        cols = [c for c in ["ticker", "sector", "industry", "instrument_type", "asset_type", "theme", "theme_tags"] if c in classification.columns]
        if len(cols) > 1:
            cls = classification[cols].drop_duplicates("ticker", keep="last")
            out = out.merge(cls, on="ticker", how="left", suffixes=("", "_class"))
    for target, fallbacks in {
        "sector": ["sector", "sector_class", "asset_type", "instrument_type", "market_regime"],
        "industry": ["industry", "industry_class", "theme_tags", "theme", "instrument_type"],
    }.items():
        values = pd.Series([""] * len(out), index=out.index, dtype="object")
        for col in fallbacks:
            if col in out:
                values = values.mask(values.astype(str).str.strip().eq(""), out[col])
        out[target] = values.fillna("").astype(str).replace({"": "UNCLASSIFIED", "nan": "UNCLASSIFIED"})
    return out


def concentration_rows(rankings: dict[str, pd.DataFrame], classification: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for strategy, frame in rankings.items():
        for view, n in [("top20", 20), ("top50", 50)]:
            classified = add_classification(topn(frame, n), classification)
            for exposure_type, column in [("sector", "sector"), ("industry", "industry")]:
                if classified.empty:
                    continue
                counts = classified[column].fillna("UNCLASSIFIED").astype(str).replace({"": "UNCLASSIFIED"}).value_counts()
                top_name = str(counts.index[0]) if len(counts) else "UNCLASSIFIED"
                top_weight = float(counts.iloc[0] / len(classified)) if len(counts) and len(classified) else 0.0
                for rank, (bucket, count) in enumerate(counts.items(), start=1):
                    rows.append({
                        "strategy": strategy,
                        "view": view,
                        "exposure_type": exposure_type,
                        "bucket": bucket,
                        "count": int(count),
                        "weight": float(count / len(classified)) if len(classified) else 0.0,
                        "rank": rank,
                        "top_bucket": top_name,
                        "top_bucket_weight": top_weight,
                        "research_only": True,
                    })
    return rows


def existing_exposure_rows() -> tuple[list[dict[str, Any]], str]:
    rows: list[dict[str, Any]] = []
    sources = []
    for path in [V111_EXPOSURE_TOP20, V111_EXPOSURE_TOP50]:
        if not path.is_file():
            continue
        sources.append(rel(path))
        frame = pd.read_csv(path, low_memory=False)
        frame = frame[frame["strategy"].isin(STRATEGIES) & frame["exposure_type"].isin(["sector", "industry"])].copy()
        for (strategy, view, exposure_type), group in frame.groupby(["strategy", "view", "exposure_type"], sort=False):
            group = group.copy()
            group["weight"] = pd.to_numeric(group["weight"], errors="coerce").fillna(0.0)
            group = group.sort_values(["weight", "count"], ascending=[False, False]).reset_index(drop=True)
            top_bucket = clean(group.iloc[0]["bucket"]) if len(group) else "UNCLASSIFIED"
            top_weight = float(group.iloc[0]["weight"]) if len(group) else 0.0
            for idx, row in group.iterrows():
                rows.append({
                    "strategy": strategy,
                    "view": view,
                    "exposure_type": exposure_type,
                    "bucket": clean(row.get("bucket")) or "UNCLASSIFIED",
                    "count": int(pd.to_numeric(row.get("count"), errors="coerce")) if clean(row.get("count")) else 0,
                    "weight": float(row.get("weight", 0.0)),
                    "rank": idx + 1,
                    "top_bucket": top_bucket,
                    "top_bucket_weight": top_weight,
                    "research_only": True,
                })
    return rows, "|".join(sources)


def top_concentration(rows: list[dict[str, Any]], view: str, exposure_type: str) -> tuple[str, float]:
    matches = [
        row for row in rows
        if row["strategy"] == "D_WEIGHT_OPTIMIZED_R1"
        and row["view"] == view
        and row["exposure_type"] == exposure_type
        and int(row["rank"]) == 1
    ]
    if not matches:
        return "UNCLASSIFIED", 0.0
    return clean(matches[0]["bucket"]), float(matches[0]["weight"])


def excluded_rows(rankings: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for strategy, frame in rankings.items():
        excluded = frame[~eligible_mask(frame)].copy()
        for _, row in excluded.iterrows():
            rows.append({
                "strategy": strategy,
                "ticker": row.get("ticker", ""),
                "rank": row.get("rank", ""),
                "exclusion_reason": clean(row.get("eligibility_exclusion_reason")) or "NOT_ELIGIBLE_FOR_VARIANT_RANKING",
                "latest_price_date": row.get("latest_price_date", ""),
                "research_only": True,
            })
    return rows


def manifest_rows(output: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(output.iterdir()):
        if path.is_file():
            rows.append({"file": path.name, "path": rel(path), "bytes": path.stat().st_size, "sha256": sha256(path), "research_only": True})
    return rows


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    before = hash_map(protected_paths())
    started = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    source_manifest = load_source_manifest()
    rankings = load_rankings()
    classification, classification_path = classification_source()
    latest_price_date = clean(source_manifest.get("latest_price_date"))
    if not latest_price_date:
        latest_price_date = max(
            clean(value)
            for frame in rankings.values()
            for value in frame.get("latest_price_date", pd.Series(dtype=str)).dropna().astype(str).tolist()
        )

    row_counts: dict[str, dict[str, int]] = {}
    top20_tickers: dict[str, list[str]] = {}
    for strategy, frame in rankings.items():
        full = frame.copy()
        top20 = topn(full, 20)
        top50 = topn(full, 50)
        full.to_csv(OUT / f"{strategy}_full_ranking.csv", index=False)
        top20.to_csv(OUT / f"{strategy}_top20.csv", index=False)
        top50.to_csv(OUT / f"{strategy}_top50.csv", index=False)
        eligible_count = int(eligible_mask(full).sum())
        row_counts[strategy] = {
            "rows": int(len(full)),
            "eligible": eligible_count,
            "excluded": int(len(full) - eligible_count),
            "top20": int(len(top20)),
            "top50": int(len(top50)),
        }
        top20_tickers[strategy] = top20["ticker"].astype(str).tolist()

    top20_overlap = overlap_matrix(rankings, 20)
    top50_overlap = overlap_matrix(rankings, 50)
    write_csv(OUT / "top20_overlap_matrix.csv", top20_overlap)
    write_csv(OUT / "top50_overlap_matrix.csv", top50_overlap)
    concentration, exposure_source = existing_exposure_rows()
    if not concentration:
        concentration = concentration_rows(rankings, classification)
        exposure_source = classification_path
    write_csv(OUT / "sector_industry_concentration.csv", concentration)
    excluded = excluded_rows(rankings)
    write_csv(OUT / "excluded_tickers.csv", excluded, ["strategy", "ticker", "rank", "exclusion_reason", "latest_price_date", "research_only"])

    after = hash_map(protected_paths())
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    d20_sector, d20_sector_weight = top_concentration(concentration, "top20", "sector")
    d50_sector, d50_sector_weight = top_concentration(concentration, "top50", "sector")
    d20_industry, d20_industry_weight = top_concentration(concentration, "top20", "industry")
    d50_industry, d50_industry_weight = top_concentration(concentration, "top50", "industry")

    top_counts_valid = all(
        counts["top20"] == min(20, counts["eligible"]) and counts["top50"] == min(50, counts["eligible"])
        for counts in row_counts.values()
    )
    final_status = "PASS_V21_112_LATEST_DATA_ABCD_RERUN_ARCHIVED"
    decision = "LATEST_DATA_ABCD_RESEARCH_ARCHIVE_READY"
    if changed:
        final_status = "FAIL_V21_112_PROTECTED_OUTPUT_MUTATION"
        decision = "STOP_PROTECTED_OUTPUTS_MODIFIED"
    elif not top_counts_valid:
        final_status = "FAIL_V21_112_VALIDATION_COUNTS"
        decision = "REVIEW_TOP_COUNT_VALIDATION"

    summary: dict[str, Any] = {
        "stage": STAGE,
        "generated_at_utc": started,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "latest_price_date": latest_price_date,
        "latest_price_source": rel(SOURCE_MANIFEST) if SOURCE_MANIFEST.is_file() else "derived_from_ranking_latest_price_date",
        "source_ranking_folder": rel(SOURCE),
        "classification_source": classification_path,
        "exposure_diagnostics_source": exposure_source,
        "rows_per_strategy": row_counts,
        "top20_tickers_per_strategy": top20_tickers,
        "eligible_counts_per_strategy": {k: v["eligible"] for k, v in row_counts.items()},
        "excluded_counts_per_strategy": {k: v["excluded"] for k, v in row_counts.items()},
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": bool(changed),
        "protected_output_changed_count": len(changed),
        "changed_protected_paths": changed,
        "official_outputs_modified": False,
        "broker_actions_created": False,
        "new_strategy_or_weight_adopted": False,
        "historical_v21_060_v21_066_v21_108_v21_111_outputs_overwritten": False,
        "d_top20_top_sector": d20_sector,
        "d_top20_top_sector_weight": d20_sector_weight,
        "d_top50_top_sector": d50_sector,
        "d_top50_top_sector_weight": d50_sector_weight,
        "d_top20_top_industry": d20_industry,
        "d_top20_top_industry_weight": d20_industry_weight,
        "d_top50_top_industry": d50_industry,
        "d_top50_top_industry_weight": d50_industry_weight,
        "top20_overlap_matrix_path": rel(OUT / "top20_overlap_matrix.csv"),
        "top50_overlap_matrix_path": rel(OUT / "top50_overlap_matrix.csv"),
        "report_path": rel(OUT / "latest_abcd_report.txt"),
    }
    write_json(OUT / "latest_abcd_summary.json", summary)

    report = [
        f"{STAGE}",
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"LATEST_PRICE_DATE={latest_price_date}",
        "",
        "Controls",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "protected_outputs_modified=false" if not changed else "protected_outputs_modified=true",
        "No official ranking, protected output, broker action, strategy definition, or weight was modified.",
        "",
        "Source",
        f"rankings={rel(SOURCE)}",
        f"source_manifest={rel(SOURCE_MANIFEST) if SOURCE_MANIFEST.is_file() else ''}",
        f"classification_source={classification_path or 'none_available'}",
        f"exposure_diagnostics_source={exposure_source or 'derived_from_ranking_columns'}",
        "",
        "Validation Counts",
        *[
            f"{strategy}: rows={counts['rows']} eligible={counts['eligible']} excluded={counts['excluded']} top20={counts['top20']} top50={counts['top50']}"
            for strategy, counts in row_counts.items()
        ],
        "",
        "ABCD Top20 Tickers",
        *[f"{strategy}: {', '.join(tickers)}" for strategy, tickers in top20_tickers.items()],
        "",
        "D Concentration",
        f"top20 sector={d20_sector} weight={d20_sector_weight:.6f}",
        f"top50 sector={d50_sector} weight={d50_sector_weight:.6f}",
        f"top20 industry={d20_industry} weight={d20_industry_weight:.6f}",
        f"top50 industry={d50_industry} weight={d50_industry_weight:.6f}",
    ]
    (OUT / "latest_abcd_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")

    validation = {
        "stage": STAGE,
        "required_files": REQUIRED_FILES,
        "missing_required_files": [name for name in REQUIRED_FILES if not (OUT / name).is_file()],
        "row_counts": row_counts,
        "eligible_counts_confirmed": {k: v["eligible"] for k, v in row_counts.items()},
        "excluded_counts_confirmed": {k: v["excluded"] for k, v in row_counts.items()},
        "latest_price_date_confirmed": latest_price_date,
        "top20_count_valid": all(v["top20"] == min(20, v["eligible"]) for v in row_counts.values()),
        "top50_count_valid": all(v["top50"] == min(50, v["eligible"]) for v in row_counts.values()),
        "protected_outputs_modified": bool(changed),
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
        "output_manifest": manifest_rows(OUT),
    }
    write_json(OUT / "validation_manifest.json", validation)
    write_json(OUT / "latest_abcd_summary.json", summary)

    print(f"FINAL_STATUS={final_status}")
    print(f"DECISION={decision}")
    print(f"LATEST_PRICE_DATE={latest_price_date}")
    print(f"A1_ROWS={row_counts['A1_BASELINE_CONTROL']['rows']}")
    print(f"B_ROWS={row_counts['B_STATIC_MOMENTUM_BLEND']['rows']}")
    print(f"C_ROWS={row_counts['C_DYNAMIC_MOMENTUM_BLEND']['rows']}")
    print(f"D_ROWS={row_counts['D_WEIGHT_OPTIMIZED_R1']['rows']}")
    print(f"A1_ELIGIBLE={row_counts['A1_BASELINE_CONTROL']['eligible']}")
    print(f"B_ELIGIBLE={row_counts['B_STATIC_MOMENTUM_BLEND']['eligible']}")
    print(f"C_ELIGIBLE={row_counts['C_DYNAMIC_MOMENTUM_BLEND']['eligible']}")
    print(f"D_ELIGIBLE={row_counts['D_WEIGHT_OPTIMIZED_R1']['eligible']}")
    print(f"A1_EXCLUDED={row_counts['A1_BASELINE_CONTROL']['excluded']}")
    print(f"B_EXCLUDED={row_counts['B_STATIC_MOMENTUM_BLEND']['excluded']}")
    print(f"C_EXCLUDED={row_counts['C_DYNAMIC_MOMENTUM_BLEND']['excluded']}")
    print(f"D_EXCLUDED={row_counts['D_WEIGHT_OPTIMIZED_R1']['excluded']}")
    print(f"A1_TOP20={row_counts['A1_BASELINE_CONTROL']['top20']}")
    print(f"B_TOP20={row_counts['B_STATIC_MOMENTUM_BLEND']['top20']}")
    print(f"C_TOP20={row_counts['C_DYNAMIC_MOMENTUM_BLEND']['top20']}")
    print(f"D_TOP20={row_counts['D_WEIGHT_OPTIMIZED_R1']['top20']}")
    print(f"TOP20_OVERLAP_MATRIX_PATH={rel(OUT / 'top20_overlap_matrix.csv')}")
    print(f"TOP50_OVERLAP_MATRIX_PATH={rel(OUT / 'top50_overlap_matrix.csv')}")
    print(f"D_TOP20_TOP_SECTOR={d20_sector}")
    print(f"D_TOP20_TOP_SECTOR_WEIGHT={d20_sector_weight}")
    print(f"D_TOP50_TOP_SECTOR={d50_sector}")
    print(f"D_TOP50_TOP_SECTOR_WEIGHT={d50_sector_weight}")
    print(f"D_TOP20_TOP_INDUSTRY={d20_industry}")
    print(f"D_TOP20_TOP_INDUSTRY_WEIGHT={d20_industry_weight}")
    print(f"D_TOP50_TOP_INDUSTRY={d50_industry}")
    print(f"D_TOP50_TOP_INDUSTRY_WEIGHT={d50_industry_weight}")
    print(f"PROTECTED_OUTPUTS_MODIFIED={str(bool(changed)).lower()}")
    print("OFFICIAL_ADOPTION_ALLOWED=false")
    print("BROKER_ACTION_ALLOWED=false")
    print(f"REPORT_PATH={rel(OUT / 'latest_abcd_report.txt')}")
    for strategy in STRATEGIES:
        print(f"{SHORT[strategy]}_TOP20_TICKERS={','.join(top20_tickers[strategy])}")
    return summary


def main() -> int:
    summary = run()
    return 1 if clean(summary["FINAL_STATUS"]).startswith("FAIL_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
