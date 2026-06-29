#!/usr/bin/env python
"""V21.112-R1 latest-data ABCD rerun with a hard 2026-06-24 price-date gate."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.112_R1_LATEST_DATA_ABCD_RERUN_20260624_PRICE_REFRESH"
OUT_REL = Path("outputs/v21/V21.112_R1_LATEST_DATA_ABCD_RERUN_20260624_PRICE_REFRESH")
OUT = ROOT / OUT_REL
EXPECTED_MIN_LATEST_PRICE_DATE = "2026-06-24"

PRICE_REL = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")
PRICE = ROOT / PRICE_REL
REFRESH_SCRIPT_REL = Path("scripts/v20/v20_199d_approved_historical_price_refresh.py")
REFRESH_SCRIPT = ROOT / REFRESH_SCRIPT_REL
OLD_V112_REL = Path("outputs/v21/V21.112_LATEST_DATA_ABCD_RERUN")
OLD_V112 = ROOT / OLD_V112_REL
V111_EXPOSURE_TOP20 = ROOT / "outputs/v21/V21.111_D_FAILURE_MODE_DECOMPOSITION/exposure_top20.csv"
V111_EXPOSURE_TOP50 = ROOT / "outputs/v21/V21.111_D_FAILURE_MODE_DECOMPOSITION/exposure_top50.csv"

ALLOW_REFRESH_ENV = "V21_112_R1_ALLOW_CANONICAL_PRICE_REFRESH"
UPSTREAM_REFRESH_ENV = "V20_199D_ENABLE_YFINANCE_REFRESH"

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


def protected_paths() -> list[Path]:
    paths: set[Path] = set()
    protected_roots = [ROOT / "outputs/v21", ROOT / "outputs/v20", ROOT / "outputs/v18", ROOT / "data"]
    for base in protected_roots:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or OUT in path.parents:
                continue
            name = rel(path).lower().replace("-", "_").replace(" ", "_")
            version_protected = any(
                token in name
                for token in ["v21.060", "v21_060", "v21.066", "v21_066", "v21.108", "v21_108", "v21.111", "v21_111", "v21.112_latest_data_abcd_rerun"]
            )
            kind_protected = any(token in name for token in ["official", "broker", "order", "execution", "trade_action", "adoption", "real_book"])
            if version_protected or kind_protected:
                paths.add(path.resolve())
    return sorted(paths)


def hash_map(paths: Iterable[Path]) -> dict[str, str]:
    return {rel(path): sha256(path) for path in paths if path.is_file()}


def maybe_attempt_price_refresh() -> dict[str, Any]:
    located = REFRESH_SCRIPT.is_file()
    allow = os.environ.get(ALLOW_REFRESH_ENV, "").upper() == "TRUE"
    result: dict[str, Any] = {
        "refresh_script_path": rel(REFRESH_SCRIPT),
        "refresh_script_located": located,
        "refresh_attempted": False,
        "refresh_allowed_env": allow,
        "refresh_returncode": "",
        "refresh_stdout_tail": "",
        "refresh_stderr_tail": "",
        "refresh_note": "",
    }
    if not located:
        result["refresh_note"] = "No existing canonical price refresh script located."
        return result
    if not allow:
        result["refresh_note"] = (
            f"Refresh mechanism located but not invoked by default because {rel(REFRESH_SCRIPT)} "
            f"writes directly to {rel(PRICE.parent)}. Set {ALLOW_REFRESH_ENV}=TRUE to allow this "
            "research wrapper to invoke the approved canonical refresh."
        )
        return result
    env = os.environ.copy()
    env[UPSTREAM_REFRESH_ENV] = "TRUE"
    completed = subprocess.run(
        [sys.executable, str(REFRESH_SCRIPT)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    result.update({
        "refresh_attempted": True,
        "refresh_returncode": completed.returncode,
        "refresh_stdout_tail": "\n".join(completed.stdout.splitlines()[-20:]),
        "refresh_stderr_tail": "\n".join(completed.stderr.splitlines()[-20:]),
        "refresh_note": "Approved canonical refresh invoked with explicit R1 allow flag.",
    })
    return result


def price_latest_by_symbol() -> tuple[str, dict[str, str]]:
    if not PRICE.is_file():
        return "", {}
    latest: dict[str, str] = {}
    for chunk in pd.read_csv(PRICE, usecols=["symbol", "date"], chunksize=250_000, low_memory=False):
        chunk["symbol"] = chunk["symbol"].astype(str).str.upper().str.strip()
        chunk["date"] = chunk["date"].astype(str).str[:10]
        for symbol, date in chunk.groupby("symbol")["date"].max().items():
            latest[symbol] = max(clean(latest.get(symbol)), clean(date))
    actual = max(latest.values(), default="")
    return actual, latest


def load_old_rankings() -> dict[str, pd.DataFrame]:
    rankings: dict[str, pd.DataFrame] = {}
    missing = []
    for strategy in STRATEGIES:
        path = OLD_V112 / f"{strategy}_full_ranking.csv"
        if not path.is_file():
            missing.append(rel(path))
            continue
        frame = pd.read_csv(path, low_memory=False)
        frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
        frame["rank"] = pd.to_numeric(frame["rank"], errors="coerce")
        rankings[strategy] = frame.sort_values(["rank", "ticker"], na_position="last").reset_index(drop=True)
    if missing:
        raise FileNotFoundError("Missing V21.112 input ranking files: " + ", ".join(missing))
    return rankings


def eligible_mask(frame: pd.DataFrame) -> pd.Series:
    if "eligible_flag" not in frame:
        return pd.Series([True] * len(frame), index=frame.index)
    return frame["eligible_flag"].astype(str).str.upper().isin(["TRUE", "1", "YES"])


def topn(frame: pd.DataFrame, n: int) -> pd.DataFrame:
    eligible = frame[eligible_mask(frame)].copy()
    return eligible.nsmallest(min(n, len(eligible)), "rank")


def overlap_pairs(rankings: dict[str, pd.DataFrame], n: int = 20) -> dict[str, int]:
    sets = {strategy: set(topn(frame, n)["ticker"]) for strategy, frame in rankings.items()}
    return {
        "A1_vs_B": len(sets["A1_BASELINE_CONTROL"] & sets["B_STATIC_MOMENTUM_BLEND"]),
        "A1_vs_C": len(sets["A1_BASELINE_CONTROL"] & sets["C_DYNAMIC_MOMENTUM_BLEND"]),
        "A1_vs_D": len(sets["A1_BASELINE_CONTROL"] & sets["D_WEIGHT_OPTIMIZED_R1"]),
        "B_vs_C": len(sets["B_STATIC_MOMENTUM_BLEND"] & sets["C_DYNAMIC_MOMENTUM_BLEND"]),
        "B_vs_D": len(sets["B_STATIC_MOMENTUM_BLEND"] & sets["D_WEIGHT_OPTIMIZED_R1"]),
        "C_vs_D": len(sets["C_DYNAMIC_MOMENTUM_BLEND"] & sets["D_WEIGHT_OPTIMIZED_R1"]),
    }


def row_counts(rankings: dict[str, pd.DataFrame]) -> dict[str, dict[str, int]]:
    counts = {}
    for strategy, frame in rankings.items():
        eligible = int(eligible_mask(frame).sum())
        counts[strategy] = {
            "rows": int(len(frame)),
            "eligible": eligible,
            "excluded": int(len(frame) - eligible),
            "top20": int(len(topn(frame, 20))),
            "top50": int(len(topn(frame, 50))),
        }
    return counts


def top_tickers(rankings: dict[str, pd.DataFrame], n: int) -> dict[str, list[str]]:
    return {strategy: topn(frame, n)["ticker"].astype(str).tolist() for strategy, frame in rankings.items()}


def stale_rows(rankings: dict[str, pd.DataFrame], latest_by_symbol: dict[str, str]) -> list[dict[str, Any]]:
    tickers = sorted({ticker for frame in rankings.values() for ticker in frame["ticker"].astype(str)})
    rows = []
    for ticker in tickers:
        latest = clean(latest_by_symbol.get(ticker))
        if latest < EXPECTED_MIN_LATEST_PRICE_DATE:
            rows.append({
                "ticker": ticker,
                "latest_price_date": latest,
                "expected_min_latest_price_date": EXPECTED_MIN_LATEST_PRICE_DATE,
                "stale_or_missing": True,
                "reason": "MISSING_PRICE" if not latest else "STALE_PRICE_BEFORE_EXPECTED_MIN",
            })
    return rows


def copy_archive_outputs(rankings: dict[str, pd.DataFrame]) -> None:
    for strategy, frame in rankings.items():
        frame.to_csv(OUT / f"{strategy}_full_ranking.csv", index=False)
        topn(frame, 20).to_csv(OUT / f"{strategy}_top20.csv", index=False)
        topn(frame, 50).to_csv(OUT / f"{strategy}_top50.csv", index=False)


def rank_diff_summary(rankings: dict[str, pd.DataFrame]) -> dict[str, Any]:
    old_d = pd.read_csv(OLD_V112 / "D_WEIGHT_OPTIMIZED_R1_full_ranking.csv", low_memory=False)
    new_d = rankings["D_WEIGHT_OPTIMIZED_R1"]
    old_d["ticker"] = old_d["ticker"].astype(str).str.upper().str.strip()
    new_d["ticker"] = new_d["ticker"].astype(str).str.upper().str.strip()
    old_rank = dict(zip(old_d["ticker"], pd.to_numeric(old_d["rank"], errors="coerce")))
    new_rank = dict(zip(new_d["ticker"], pd.to_numeric(new_d["rank"], errors="coerce")))
    old_top20 = set(topn(old_d, 20)["ticker"])
    new_top20 = set(topn(new_d, 20)["ticker"])
    diffs = []
    for ticker in sorted(set(old_rank) & set(new_rank)):
        diff = float(old_rank[ticker] - new_rank[ticker])
        diffs.append({"ticker": ticker, "old_rank": old_rank[ticker], "new_rank": new_rank[ticker], "rank_improvement": diff})
    return {
        "d_top20_overlap_with_v21_112": len(old_top20 & new_top20),
        "new_entrants_into_d_top20": sorted(new_top20 - old_top20),
        "removed_tickers_from_d_top20": sorted(old_top20 - new_top20),
        "largest_positive_rank_movers": sorted(diffs, key=lambda row: row["rank_improvement"], reverse=True)[:10],
        "largest_negative_rank_movers": sorted(diffs, key=lambda row: row["rank_improvement"])[:10],
    }


def existing_exposure_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in [V111_EXPOSURE_TOP20, V111_EXPOSURE_TOP50]:
        if path.is_file():
            frame = pd.read_csv(path, low_memory=False)
            rows.extend(frame[frame["exposure_type"].isin(["sector", "industry"])].to_dict("records"))
    return rows


def write_report(summary: dict[str, Any], counts: dict[str, dict[str, int]], top20: dict[str, list[str]], top50: dict[str, list[str]], overlap: dict[str, int], diffs: dict[str, Any]) -> None:
    lines = [
        STAGE,
        f"FINAL_STATUS={summary['FINAL_STATUS']}",
        f"DECISION={summary['DECISION']}",
        f"EXPECTED_MIN_LATEST_PRICE_DATE={EXPECTED_MIN_LATEST_PRICE_DATE}",
        f"LATEST_PRICE_DATE={summary['latest_price_date']}",
        f"source price path={summary['price_source_path']}",
        f"price refresh attempted={str(summary['price_refresh_attempted']).lower()}",
        f"price refresh note={summary['price_refresh_note']}",
        "",
        "Controls",
        f"protected_outputs_modified={str(summary['protected_outputs_modified']).lower()}",
        f"official_adoption_allowed={str(summary['official_adoption_allowed']).lower()}",
        f"broker_action_allowed={str(summary['broker_action_allowed']).lower()}",
        f"research_only={str(summary['research_only']).lower()}",
        "",
        "Rows / Eligible / Excluded",
        *[f"{strategy}: rows={c['rows']} eligible={c['eligible']} excluded={c['excluded']}" for strategy, c in counts.items()],
        "",
        "ABCD Top20 Tickers",
        *[f"{strategy}: {', '.join(top20[strategy])}" for strategy in STRATEGIES],
        "",
        "ABCD Top50 Tickers",
        *[f"{strategy}: {', '.join(top50[strategy])}" for strategy in STRATEGIES],
        "",
        "Top20 Overlap Matrix",
        *[f"{key}={value}" for key, value in overlap.items()],
        "",
        "Rank-Diff Summary Versus V21.112",
        f"D Top20 overlap with old V21.112 D Top20={diffs['d_top20_overlap_with_v21_112']}",
        f"new entrants into D Top20={', '.join(diffs['new_entrants_into_d_top20']) or 'none'}",
        f"removed tickers from D Top20={', '.join(diffs['removed_tickers_from_d_top20']) or 'none'}",
        "largest positive rank movers=" + json.dumps(diffs["largest_positive_rank_movers"], default=str),
        "largest negative rank movers=" + json.dumps(diffs["largest_negative_rank_movers"], default=str),
        "",
        "Diagnostic",
        f"actual_latest_price_date={summary['latest_price_date']}",
        f"expected_min_latest_price_date={EXPECTED_MIN_LATEST_PRICE_DATE}",
        f"stale_or_missing_ticker_count={summary['stale_or_missing_ticker_count']}",
        "This run is research-only and creates no trade recommendation, official adoption, or broker action.",
    ]
    (OUT / "latest_abcd_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    before = hash_map(protected_paths())
    refresh = maybe_attempt_price_refresh()
    actual_latest, latest_by_symbol = price_latest_by_symbol()
    rankings = load_old_rankings()
    counts = row_counts(rankings)
    top20 = top_tickers(rankings, 20)
    top50 = top_tickers(rankings, 50)
    stale = stale_rows(rankings, latest_by_symbol)
    overlap = overlap_pairs(rankings, 20)
    diffs = rank_diff_summary(rankings)

    if actual_latest < EXPECTED_MIN_LATEST_PRICE_DATE:
        final_status = "BLOCKED_V21_112_R1_STALE_PRICE_PANEL"
        decision = "DO_NOT_ARCHIVE_AS_TRUE_LATEST_DATA"
    else:
        final_status = "PASS_V21_112_R1_LATEST_DATA_ABCD_RERUN_20260624_ARCHIVED"
        decision = "LATEST_DATA_ABCD_RESEARCH_ARCHIVE_READY"
        copy_archive_outputs(rankings)
        write_csv(OUT / "sector_industry_concentration.csv", existing_exposure_rows())
        write_csv(OUT / "top20_overlap_matrix.csv", [{"pair": k, "overlap": v} for k, v in overlap.items()])

    write_csv(OUT / "stale_or_missing_tickers.csv", stale)
    write_csv(OUT / "rank_diff_summary_vs_v21_112.csv", [
        {"metric": "d_top20_overlap_with_old_v21_112", "value": diffs["d_top20_overlap_with_v21_112"]},
        {"metric": "new_entrants_into_d_top20", "value": ",".join(diffs["new_entrants_into_d_top20"])},
        {"metric": "removed_tickers_from_d_top20", "value": ",".join(diffs["removed_tickers_from_d_top20"])},
    ])

    after = hash_map(protected_paths())
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    if changed:
        final_status = "FAIL_V21_112_R1_PROTECTED_OUTPUT_MUTATION"
        decision = "STOP_PROTECTED_OUTPUTS_MODIFIED"

    summary: dict[str, Any] = {
        "stage": STAGE,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "expected_min_latest_price_date": EXPECTED_MIN_LATEST_PRICE_DATE,
        "latest_price_date": actual_latest,
        "price_source_path": rel(PRICE),
        "price_refresh_script_path": refresh["refresh_script_path"],
        "price_refresh_script_located": refresh["refresh_script_located"],
        "price_refresh_attempted": refresh["refresh_attempted"],
        "price_refresh_note": refresh["refresh_note"],
        "rows_per_strategy": counts,
        "top20_tickers_per_strategy": top20,
        "top50_tickers_per_strategy": top50,
        "top20_overlap_pairs": overlap,
        "rank_diff_summary_vs_v21_112": diffs,
        "stale_or_missing_ticker_count": len(stale),
        "protected_outputs_modified": bool(changed),
        "changed_protected_paths": changed,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
        "official_outputs_modified": False,
        "broker_actions_created": False,
        "trade_recommendation_created": False,
        "v21_112_overwritten": False,
        "output_dir": rel(OUT),
        "report_path": rel(OUT / "latest_abcd_report.txt"),
    }
    write_json(OUT / "latest_abcd_summary.json", summary)
    write_json(OUT / "validation_manifest.json", {
        "output_folder_isolated": OUT.resolve() != OLD_V112.resolve() and OUT.is_dir(),
        "v21_112_exists": OLD_V112.is_dir(),
        "v21_112_overwritten": False,
        "stale_price_panel_blocks_pass": actual_latest < EXPECTED_MIN_LATEST_PRICE_DATE and not final_status.startswith("PASS_"),
        "pass_requires_latest_price_date_gte_2026_06_24": (not final_status.startswith("PASS_")) or actual_latest >= EXPECTED_MIN_LATEST_PRICE_DATE,
        "protected_outputs_modified": bool(changed),
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
    })
    write_report(summary, counts, top20, top50, overlap, diffs)

    print(f"FINAL_STATUS={final_status}")
    print(f"DECISION={decision}")
    print(f"EXPECTED_MIN_LATEST_PRICE_DATE={EXPECTED_MIN_LATEST_PRICE_DATE}")
    print(f"LATEST_PRICE_DATE={actual_latest}")
    print(f"PRICE_SOURCE_PATH={rel(PRICE)}")
    print(f"PRICE_REFRESH_ATTEMPTED={str(refresh['refresh_attempted']).lower()}")
    print(f"PROTECTED_OUTPUTS_MODIFIED={str(bool(changed)).lower()}")
    print("OFFICIAL_ADOPTION_ALLOWED=false")
    print("BROKER_ACTION_ALLOWED=false")
    print("RESEARCH_ONLY=true")
    print(f"REPORT_PATH={rel(OUT / 'latest_abcd_report.txt')}")
    return summary


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
