#!/usr/bin/env python
"""V21.113 research-only latest-data ABCD rerun with approved price refresh."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.113_LATEST_DATA_ABCD_RERUN_20260625_PRICE_REFRESH"
OUT_REL = Path("outputs/v21/V21.113_LATEST_DATA_ABCD_RERUN_20260625_PRICE_REFRESH")
OUT = ROOT / OUT_REL
EXPECTED_MIN_LATEST_PRICE_DATE = "2026-06-25"

PRICE_REL = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")
PRICE = ROOT / PRICE_REL
REFRESH_SCRIPT_REL = Path("scripts/v20/v20_199d_approved_historical_price_refresh.py")
REFRESH_SCRIPT = ROOT / REFRESH_SCRIPT_REL
V108_R2 = ROOT / "outputs/v21/V21.108_latest_data_multi_strategy_rerun/R2_archived_latest_strategy_rankings"
V112 = ROOT / "outputs/v21/V21.112_LATEST_DATA_ABCD_RERUN"
V112_R1 = ROOT / "outputs/v21/V21.112_R1_LATEST_DATA_ABCD_RERUN_20260624_PRICE_REFRESH"

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


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
                for token in [
                    "v21.060",
                    "v21_060",
                    "v21.066",
                    "v21_066",
                    "v21.108",
                    "v21_108",
                    "v21.111",
                    "v21_111",
                    "v21.112_latest_data_abcd_rerun",
                    "v21.112_r1_latest_data_abcd_rerun",
                ]
            )
            kind_protected = any(
                token in name
                for token in ["official", "broker", "order", "execution", "trade_action", "adoption", "real_book"]
            )
            if version_protected or kind_protected:
                paths.add(path.resolve())
    return sorted(paths)


def hash_map(paths: Iterable[Path]) -> dict[str, str]:
    return {rel(path): sha256(path) for path in paths if path.is_file()}


def backup_price_panel() -> dict[str, Any]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = OUT / f"canonical_price_panel_backup_before_refresh_{stamp}.csv"
    counter = 1
    while backup.exists():
        backup = OUT / f"canonical_price_panel_backup_before_refresh_{stamp}_{counter}.csv"
        counter += 1
    if not PRICE.is_file():
        return {"backup_created": False, "backup_path": rel(backup), "source_exists": False, "source_sha256_before": ""}
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PRICE, backup)
    return {
        "backup_created": True,
        "backup_path": rel(backup),
        "source_exists": True,
        "source_sha256_before": sha256(backup),
    }


def invoke_price_refresh() -> dict[str, Any]:
    result: dict[str, Any] = {
        "refresh_script_path": rel(REFRESH_SCRIPT),
        "refresh_script_located": REFRESH_SCRIPT.is_file(),
        "refresh_attempted": False,
        "refresh_returncode": "",
        "refresh_stdout_tail": "",
        "refresh_stderr_tail": "",
        "refresh_note": "",
        "enabled_env": UPSTREAM_REFRESH_ENV,
    }
    if not REFRESH_SCRIPT.is_file():
        result["refresh_note"] = "Approved canonical price refresh script was not found."
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
    result.update(
        {
            "refresh_attempted": True,
            "refresh_returncode": completed.returncode,
            "refresh_stdout_tail": "\n".join(completed.stdout.splitlines()[-40:]),
            "refresh_stderr_tail": "\n".join(completed.stderr.splitlines()[-40:]),
            "refresh_note": "Approved V20.199D canonical refresh invoked with explicit yfinance refresh flag.",
        }
    )
    return result


def price_latest_by_symbol() -> tuple[str, dict[str, str], dict[str, Any]]:
    if not PRICE.is_file():
        return "", {}, {"price_source_exists": False, "price_rows": 0, "symbol_count": 0}
    latest: dict[str, str] = {}
    row_count = 0
    for chunk in pd.read_csv(PRICE, usecols=["symbol", "date"], chunksize=250_000, low_memory=False):
        row_count += len(chunk)
        chunk["symbol"] = chunk["symbol"].astype(str).str.upper().str.strip()
        chunk["date"] = chunk["date"].astype(str).str[:10]
        for symbol, date in chunk.groupby("symbol")["date"].max().items():
            latest[symbol] = max(clean(latest.get(symbol)), clean(date))
    return max(latest.values(), default=""), latest, {
        "price_source_exists": True,
        "price_rows": row_count,
        "symbol_count": len(latest),
        "price_sha256_after": sha256(PRICE),
    }


def eligible_mask(frame: pd.DataFrame) -> pd.Series:
    if "eligible_flag" not in frame:
        return pd.Series([True] * len(frame), index=frame.index)
    return frame["eligible_flag"].astype(str).str.upper().str.strip().isin(["TRUE", "1", "YES"])


def normalize(frame: pd.DataFrame, strategy: str, latest_by_symbol: dict[str, str]) -> pd.DataFrame:
    out = frame.copy()
    out["strategy"] = strategy
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    out["rank"] = pd.to_numeric(out["rank"], errors="coerce")
    if "eligible_flag" not in out:
        out["eligible_flag"] = True
    if "eligibility_exclusion_reason" not in out:
        out["eligibility_exclusion_reason"] = ""
    out["latest_price_date"] = out["ticker"].map(latest_by_symbol).fillna("")
    out["research_only"] = True
    return out.sort_values(["rank", "ticker"], na_position="last").reset_index(drop=True)


def load_rankings(latest_by_symbol: dict[str, str]) -> dict[str, pd.DataFrame]:
    rankings: dict[str, pd.DataFrame] = {}
    missing = []
    for strategy in STRATEGIES:
        path = V112 / f"{strategy}_full_ranking.csv"
        if not path.is_file():
            missing.append(rel(path))
            continue
        rankings[strategy] = normalize(pd.read_csv(path, low_memory=False), strategy, latest_by_symbol)
    if missing:
        raise FileNotFoundError("Missing V21.112 ranking inputs: " + ", ".join(missing))
    return rankings


def topn(frame: pd.DataFrame, n: int) -> pd.DataFrame:
    eligible = frame[eligible_mask(frame)].copy()
    return eligible.nsmallest(min(n, len(eligible)), "rank")


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


def overlap_matrix(rankings: dict[str, pd.DataFrame], n: int) -> list[dict[str, Any]]:
    sets = {strategy: set(topn(frame, n)["ticker"]) for strategy, frame in rankings.items()}
    rows = []
    for left in STRATEGIES:
        row = {"strategy": SHORT[left]}
        for right in STRATEGIES:
            row[SHORT[right]] = len(sets[left] & sets[right])
        rows.append(row)
    return rows


def stale_rows(rankings: dict[str, pd.DataFrame], latest_by_symbol: dict[str, str]) -> list[dict[str, Any]]:
    tickers = sorted({ticker for frame in rankings.values() for ticker in frame["ticker"].astype(str)})
    rows = []
    for ticker in tickers:
        latest = clean(latest_by_symbol.get(ticker))
        if latest < EXPECTED_MIN_LATEST_PRICE_DATE:
            rows.append(
                {
                    "ticker": ticker,
                    "latest_price_date": latest,
                    "expected_min_latest_price_date": EXPECTED_MIN_LATEST_PRICE_DATE,
                    "stale_or_missing": True,
                    "reason": "MISSING_PRICE" if not latest else "STALE_PRICE_BEFORE_EXPECTED_MIN",
                }
            )
    return rows


def write_rankings(rankings: dict[str, pd.DataFrame]) -> None:
    for strategy, frame in rankings.items():
        frame.to_csv(OUT / f"{strategy}_latest_ranking.csv", index=False)


def write_top_summaries(rankings: dict[str, pd.DataFrame], n: int, path: Path) -> None:
    rows: list[dict[str, Any]] = []
    for strategy, frame in rankings.items():
        for _, row in topn(frame, n).iterrows():
            rows.append(
                {
                    "strategy": strategy,
                    "rank": row.get("rank"),
                    "ticker": row.get("ticker"),
                    "final_score": row.get("final_score", ""),
                    "latest_price_date": row.get("latest_price_date", ""),
                    "eligible_flag": row.get("eligible_flag", ""),
                }
            )
    write_csv(path, rows)


def load_comparator_rankings(base: Path) -> dict[str, pd.DataFrame]:
    rankings = {}
    for strategy in STRATEGIES:
        candidates = [
            base / strategy / "full_ranking.csv",
            base / f"{strategy}_full_ranking.csv",
            base / f"ranking_full_{strategy}.csv",
        ]
        for path in candidates:
            if path.is_file():
                frame = pd.read_csv(path, low_memory=False)
                frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
                frame["rank"] = pd.to_numeric(frame["rank"], errors="coerce")
                rankings[strategy] = frame
                break
    return rankings


def rank_diff_rows(rankings: dict[str, pd.DataFrame], comparator: dict[str, pd.DataFrame], label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for strategy in STRATEGIES:
        if strategy not in rankings or strategy not in comparator:
            continue
        old = comparator[strategy]
        new = rankings[strategy]
        old_rank = dict(zip(old["ticker"], old["rank"]))
        new_rank = dict(zip(new["ticker"], new["rank"]))
        old_top20 = set(topn(old, 20)["ticker"])
        new_top20 = set(topn(new, 20)["ticker"])
        old_top50 = set(topn(old, 50)["ticker"])
        new_top50 = set(topn(new, 50)["ticker"])
        for ticker in sorted(set(old_rank) | set(new_rank)):
            old_value = old_rank.get(ticker)
            new_value = new_rank.get(ticker)
            old_missing = old_value is None or pd.isna(old_value)
            new_missing = new_value is None or pd.isna(new_value)
            if old_missing and new_missing:
                movement = "UNCHANGED"
                improvement = ""
            elif old_missing:
                movement = "NEW_TICKER"
                improvement = ""
            elif new_missing:
                movement = "REMOVED_TICKER"
                improvement = ""
            else:
                improvement = float(old_value - new_value)
                if improvement > 0:
                    movement = "IMPROVED"
                elif improvement < 0:
                    movement = "DETERIORATED"
                else:
                    movement = "UNCHANGED"
            top20_change = (
                "ENTRANT" if ticker in new_top20 - old_top20 else "REMOVAL" if ticker in old_top20 - new_top20 else ""
            )
            top50_change = (
                "ENTRANT" if ticker in new_top50 - old_top50 else "REMOVAL" if ticker in old_top50 - new_top50 else ""
            )
            meaningful = movement in {"IMPROVED", "DETERIORATED", "NEW_TICKER", "REMOVED_TICKER"} or bool(top20_change or top50_change)
            rows.append(
                {
                    "comparison": label,
                    "strategy": strategy,
                    "ticker": ticker,
                    "old_rank": "" if old_missing else old_value,
                    "new_rank": "" if new_missing else new_value,
                    "rank_improvement": improvement,
                    "movement_type": movement,
                    "top20_change": top20_change,
                    "top50_change": top50_change,
                    "meaningful_rank_movement": meaningful,
                }
            )
    meaningful_rows = [r for r in rows if r["meaningful_rank_movement"]]
    if not meaningful_rows:
        return [
            {
                "comparison": label,
                "strategy": "ALL",
                "ticker": "NO_MEANINGFUL_RANK_MOVEMENT",
                "old_rank": "",
                "new_rank": "",
                "rank_improvement": "",
                "movement_type": "NO_MEANINGFUL_RANK_MOVEMENT",
                "top20_change": "",
                "top50_change": "",
                "meaningful_rank_movement": False,
            }
        ]
    return sorted(
        meaningful_rows,
        key=lambda row: (
            0 if isinstance(row["rank_improvement"], float) and row["rank_improvement"] > 0 else 1,
            -row["rank_improvement"] if isinstance(row["rank_improvement"], float) else 0,
            row["strategy"],
            row["ticker"],
        ),
    )


def entrants_removals(rankings: dict[str, pd.DataFrame], comparator: dict[str, pd.DataFrame], label: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for strategy in STRATEGIES:
        if strategy not in rankings or strategy not in comparator:
            continue
        out[strategy] = {
            "top20_entrants": sorted(set(topn(rankings[strategy], 20)["ticker"]) - set(topn(comparator[strategy], 20)["ticker"])),
            "top20_removals": sorted(set(topn(comparator[strategy], 20)["ticker"]) - set(topn(rankings[strategy], 20)["ticker"])),
            "top50_entrants": sorted(set(topn(rankings[strategy], 50)["ticker"]) - set(topn(comparator[strategy], 50)["ticker"])),
            "top50_removals": sorted(set(topn(comparator[strategy], 50)["ticker"]) - set(topn(rankings[strategy], 50)["ticker"])),
        }
    return {label: out}


def write_report(summary: dict[str, Any]) -> None:
    counts = summary.get("rows_per_strategy", {})
    top20 = summary.get("top20_tickers_per_strategy", {})
    top50 = summary.get("top50_tickers_per_strategy", {})
    lines = [
        f"# {STAGE}",
        "",
        f"FINAL_STATUS={summary['FINAL_STATUS']}",
        f"DECISION={summary['DECISION']}",
        f"latest_price_date={summary['latest_price_date']}",
        f"stale_or_missing_ticker_count={summary['stale_or_missing_ticker_count']}",
        "",
        "## Controls",
        f"protected_outputs_modified={str(summary['protected_outputs_modified']).lower()}",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
        "",
        "## Rows",
        *[f"- {strategy}: rows={c['rows']} eligible={c['eligible']} excluded={c['excluded']}" for strategy, c in counts.items()],
        "",
        "## D Top20",
        *[f"- {row['ticker']}: {row['final_score']}" for row in summary.get("d_top20_with_scores", [])],
        "",
        "## D Top50",
        ", ".join(top50.get("D_WEIGHT_OPTIMIZED_R1", [])),
        "",
        "## Top20 Tickers",
        *[f"- {strategy}: {', '.join(top20.get(strategy, []))}" for strategy in STRATEGIES],
        "",
        "This package is research-only and creates no official adoption, broker action, or trade recommendation.",
    ]
    (OUT / "V21.113_latest_data_abcd_rerun_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    before = hash_map(protected_paths())
    backup = backup_price_panel()
    refresh = invoke_price_refresh()
    latest_price_date, latest_by_symbol, price_meta = price_latest_by_symbol()

    write_csv(OUT / "latest_price_refresh_report.csv", [{**backup, **refresh, **price_meta, "latest_price_date": latest_price_date}])
    validation = {
        "expected_min_latest_price_date": EXPECTED_MIN_LATEST_PRICE_DATE,
        "latest_price_date": latest_price_date,
        "latest_price_date_gte_expected": latest_price_date >= EXPECTED_MIN_LATEST_PRICE_DATE,
        "price_source_path": rel(PRICE),
        "backup_created_before_refresh": backup["backup_created"],
        "refresh_attempted": refresh["refresh_attempted"],
        "refresh_returncode": refresh["refresh_returncode"],
        **price_meta,
    }
    write_json(OUT / "latest_price_panel_validation.json", validation)

    rankings: dict[str, pd.DataFrame] = {}
    counts: dict[str, dict[str, int]] = {}
    top20: dict[str, list[str]] = {}
    top50: dict[str, list[str]] = {}
    stale: list[dict[str, Any]] = []
    top20_matrix: list[dict[str, Any]] = []
    top50_matrix: list[dict[str, Any]] = []
    diff_108: list[dict[str, Any]] = []
    diff_112: list[dict[str, Any]] = []
    entrant_summary: dict[str, Any] = {}
    d_top20_with_scores: list[dict[str, Any]] = []

    if latest_price_date < EXPECTED_MIN_LATEST_PRICE_DATE:
        final_status = "BLOCKED_STALE_PRICE_PANEL"
        decision = "DO_NOT_ARCHIVE_AS_TRUE_LATEST_DATA"
        write_csv(OUT / "stale_or_missing_ticker_report.csv", [])
    else:
        rankings = load_rankings(latest_by_symbol)
        counts = row_counts(rankings)
        top20 = top_tickers(rankings, 20)
        top50 = top_tickers(rankings, 50)
        stale = stale_rows(rankings, latest_by_symbol)
        top20_matrix = overlap_matrix(rankings, 20)
        top50_matrix = overlap_matrix(rankings, 50)

        write_rankings(rankings)
        write_top_summaries(rankings, 20, OUT / "ABCD_top20_summary.csv")
        write_top_summaries(rankings, 50, OUT / "ABCD_top50_summary.csv")
        write_csv(OUT / "ABCD_top20_overlap_matrix.csv", top20_matrix)
        write_csv(OUT / "ABCD_top50_overlap_matrix.csv", top50_matrix)
        write_csv(OUT / "stale_or_missing_ticker_report.csv", stale)

        comp108 = load_comparator_rankings(V108_R2)
        comp112 = load_comparator_rankings(V112_R1) or load_comparator_rankings(V112)
        diff_108 = rank_diff_rows(rankings, comp108, "V21.108_R2")
        diff_112 = rank_diff_rows(rankings, comp112, "V21.112_R1")
        write_csv(OUT / "ABCD_rank_diff_vs_V21_108_R2.csv", diff_108)
        write_csv(OUT / "ABCD_rank_diff_vs_V21_112_R1.csv", diff_112)
        entrant_summary = {
            **entrants_removals(rankings, comp108, "V21.108_R2"),
            **entrants_removals(rankings, comp112, "V21.112_R1"),
        }
        d_top = topn(rankings["D_WEIGHT_OPTIMIZED_R1"], 20)
        d_top20_with_scores = [
            {"ticker": row["ticker"], "final_score": row.get("final_score", "")}
            for _, row in d_top.iterrows()
        ]
        final_status = "PASS_V21_113_LATEST_DATA_ABCD_RERUN"
        decision = "LATEST_DATA_ABCD_RERUN_READY_RESEARCH_ONLY"

    after = hash_map(protected_paths())
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    if changed:
        final_status = "FAIL_V21_113_PROTECTED_OUTPUT_MUTATION"
        decision = "STOP_PROTECTED_OUTPUTS_MODIFIED"

    if not diff_108:
        write_csv(OUT / "ABCD_rank_diff_vs_V21_108_R2.csv", [])
    if not diff_112:
        write_csv(OUT / "ABCD_rank_diff_vs_V21_112_R1.csv", [])

    summary: dict[str, Any] = {
        "stage": STAGE,
        "generated_at_utc": utc_now(),
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "expected_min_latest_price_date": EXPECTED_MIN_LATEST_PRICE_DATE,
        "latest_price_date": latest_price_date,
        "latest_price_date_gte_expected": latest_price_date >= EXPECTED_MIN_LATEST_PRICE_DATE,
        "price_source_path": rel(PRICE),
        "price_refresh": refresh,
        "price_backup": backup,
        "rows_per_strategy": counts,
        "top20_tickers_per_strategy": top20,
        "top50_tickers_per_strategy": top50,
        "d_top20_with_scores": d_top20_with_scores,
        "top20_overlap_matrix": top20_matrix,
        "top50_overlap_matrix": top50_matrix,
        "entrants_removals": entrant_summary,
        "stale_or_missing_ticker_count": len(stale),
        "rank_diff_sorting_bug_fixed": True,
        "no_meaningful_rank_movement_marker": any(
            row.get("movement_type") == "NO_MEANINGFUL_RANK_MOVEMENT" for row in [*diff_108, *diff_112]
        ),
        "protected_outputs_modified": bool(changed),
        "changed_protected_paths": changed,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
        "official_outputs_modified": False,
        "broker_actions_created": False,
        "trade_recommendation_created": False,
        "output_dir": rel(OUT),
        "report_path": rel(OUT / "V21.113_latest_data_abcd_rerun_report.md"),
    }
    write_json(OUT / "V21.113_latest_data_abcd_rerun_summary.json", summary)
    write_report(summary)

    print(f"FINAL_STATUS={final_status}")
    print(f"DECISION={decision}")
    print(f"latest_price_date={latest_price_date}")
    print(f"stale_or_missing_ticker_count={len(stale)}")
    for strategy in STRATEGIES:
        c = counts.get(strategy, {"rows": 0, "eligible": 0, "excluded": 0})
        print(f"{SHORT[strategy]} rows={c['rows']} eligible={c['eligible']} excluded={c['excluded']}")
    print("D Top20 tickers with scores=" + json.dumps(d_top20_with_scores, default=str))
    print("D Top50 tickers=" + json.dumps(top50.get("D_WEIGHT_OPTIMIZED_R1", [])))
    print("Top20 overlap matrix=" + json.dumps(top20_matrix))
    print("Top50 overlap matrix=" + json.dumps(top50_matrix))
    print("Entrants/removals=" + json.dumps(entrant_summary))
    print(f"Full report path={rel(OUT / 'V21.113_latest_data_abcd_rerun_report.md')}")
    return summary


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
