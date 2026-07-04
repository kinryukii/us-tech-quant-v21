#!/usr/bin/env python
"""V21.244 ABCDE retrospective replay from 2026-06-18 to 2026-06-29."""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any


STAGE = "V21.244_ABCDE_RETROSPECTIVE_REPLAY_0618_TO_0629"
OUT_REL = Path("outputs/v21") / STAGE
START_DATE = date(2026, 6, 18)
END_DATE = date(2026, 6, 29)
STRATEGIES = ["A1", "B", "C", "D", "E_R1"]
PIT_LITE_FIELDS = ["legacy_fundamentals", "legacy_event_risk", "legacy_factor_metadata"]


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n", encoding="utf-8")


def read_csv_dict(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def to_float(value: Any) -> float | None:
    try:
        if value in ("", None):
            return None
        x = float(value)
        return None if math.isnan(x) else x
    except Exception:
        return None


def canonical_qfq_path(repo_root: Path) -> Path | None:
    pointer = repo_root / "outputs/v21/V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD/canonical_snapshot_pointer.json"
    if pointer.exists():
        try:
            path = Path(json.loads(pointer.read_text(encoding="utf-8")).get("canonical_qfq_path", ""))
            if path.exists():
                return path
        except Exception:
            pass
    fallback = repo_root / "DUMMY_DO_NOT_USE"
    return fallback if fallback.exists() else None


def load_price_panel(path: Path) -> dict[str, list[dict[str, Any]]]:
    panel: dict[str, list[dict[str, Any]]] = {}
    for row in read_csv_dict(path):
        ticker = (row.get("ticker") or "").upper()
        d = parse_date(row.get("date") or "")
        close = to_float(row.get("close"))
        volume = to_float(row.get("volume")) or 0.0
        if ticker and d and close is not None:
            panel.setdefault(ticker, []).append({"date": d, "close": close, "volume": volume})
    for rows in panel.values():
        rows.sort(key=lambda r: r["date"])
    return panel


def trading_dates(panel: dict[str, list[dict[str, Any]]], start: date, end: date) -> list[date]:
    dates = sorted({r["date"] for rows in panel.values() for r in rows if start <= r["date"] <= end})
    return dates


def pct(a: float | None, b: float | None) -> float:
    return (a / b - 1.0) if a is not None and b not in (None, 0) else 0.0


def stdev(vals: list[float]) -> float:
    if len(vals) < 2:
        return 0.0
    m = sum(vals) / len(vals)
    return math.sqrt(sum((x - m) ** 2 for x in vals) / (len(vals) - 1))


def percentile_scores(values: dict[str, float], reverse: bool = False) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values.items(), key=lambda kv: kv[1], reverse=reverse)
    n = len(ordered)
    if n == 1:
        return {ordered[0][0]: 1.0}
    return {ticker: i / (n - 1) for i, (ticker, _v) in enumerate(ordered)}


def features_asof(panel: dict[str, list[dict[str, Any]]], asof: date) -> dict[str, dict[str, Any]]:
    raw: dict[str, dict[str, Any]] = {}
    for ticker, rows in panel.items():
        hist = [r for r in rows if r["date"] <= asof]
        if len(hist) < 20 or hist[-1]["date"] != asof:
            continue
        closes = [float(r["close"]) for r in hist]
        volumes = [float(r["volume"]) for r in hist]
        returns = [pct(closes[i], closes[i - 1]) for i in range(1, len(closes))]
        latest = closes[-1]
        ma20 = sum(closes[-20:]) / 20
        ma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else ma20
        high20 = max(closes[-20:])
        low20 = min(closes[-20:])
        raw[ticker] = {
            "ret5": pct(closes[-1], closes[-6]) if len(closes) >= 6 else 0.0,
            "ret20": pct(closes[-1], closes[-21]) if len(closes) >= 21 else 0.0,
            "trend": (latest / ma20 - 1.0) + (ma20 / ma50 - 1.0),
            "volatility": stdev(returns[-20:]),
            "drawdown": pct(latest, high20),
            "liquidity": sum(volumes[-20:]) / 20,
            "range_position": (latest - low20) / (high20 - low20) if high20 != low20 else 0.5,
            "latest_date": hist[-1]["date"],
        }
    score_inputs = {
        "ret5": percentile_scores({k: v["ret5"] for k, v in raw.items()}),
        "ret20": percentile_scores({k: v["ret20"] for k, v in raw.items()}),
        "trend": percentile_scores({k: v["trend"] for k, v in raw.items()}),
        "volatility": percentile_scores({k: v["volatility"] for k, v in raw.items()}, reverse=True),
        "drawdown": percentile_scores({k: v["drawdown"] for k, v in raw.items()}),
        "liquidity": percentile_scores({k: v["liquidity"] for k, v in raw.items()}),
        "range_position": percentile_scores({k: v["range_position"] for k, v in raw.items()}),
    }
    out: dict[str, dict[str, Any]] = {}
    for ticker, vals in raw.items():
        out[ticker] = {name: score_inputs[name].get(ticker, 0.0) for name in score_inputs}
        out[ticker]["latest_date"] = vals["latest_date"]
    return out


def strategy_score(strategy: str, f: dict[str, Any]) -> float:
    if strategy == "A1":
        return 0.30 * f["trend"] + 0.20 * f["ret20"] + 0.15 * f["ret5"] + 0.15 * f["drawdown"] + 0.10 * f["liquidity"] + 0.10 * f["volatility"]
    if strategy == "B":
        return 0.45 * f["ret20"] + 0.25 * f["ret5"] + 0.15 * f["trend"] + 0.10 * f["liquidity"] + 0.05 * f["volatility"]
    if strategy == "C":
        return 0.35 * f["ret5"] + 0.25 * f["trend"] + 0.15 * f["range_position"] + 0.15 * f["ret20"] + 0.10 * f["liquidity"]
    if strategy == "D":
        return 0.25 * f["trend"] + 0.20 * f["liquidity"] + 0.20 * f["drawdown"] + 0.20 * f["ret20"] + 0.15 * f["volatility"]
    if strategy == "E_R1":
        return 0.30 * f["volatility"] + 0.25 * f["drawdown"] + 0.20 * f["liquidity"] + 0.15 * f["trend"] + 0.10 * f["ret20"]
    return 0.0


def replay(panel: dict[str, list[dict[str, Any]]], dates: list[date]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for d in dates:
        feats = features_asof(panel, d)
        coverage.append({"replay_ranking_date": d.isoformat(), "eligible_ticker_count": len(feats), "source_mode": "LOCAL_MOOMOO_QFQ", "notes": "features use price rows <= replay date"})
        if not feats:
            for strategy in STRATEGIES:
                missing.append({"replay_ranking_date": d.isoformat(), "strategy": strategy, "missing_reason": "NO_ELIGIBLE_TICKERS", "severity": "ERROR"})
            continue
        strategy_scores: dict[str, dict[str, float]] = {}
        for strategy in STRATEGIES:
            scored = {ticker: strategy_score(strategy, f) for ticker, f in feats.items()}
            strategy_scores[strategy] = scored
            ordered = sorted(scored.items(), key=lambda kv: kv[1], reverse=True)
            if not ordered:
                missing.append({"replay_ranking_date": d.isoformat(), "strategy": strategy, "missing_reason": "NO_SCORED_TICKERS", "severity": "ERROR"})
            for rank, (ticker, score) in enumerate(ordered, 1):
                rows.append({
                    "replay_ranking_date": d.isoformat(),
                    "strategy": strategy,
                    "ticker": ticker,
                    "rank": rank,
                    "score": round(score, 10),
                    "source_mode": "LOCAL_MOOMOO_QFQ",
                    "replay_mode": "RETROSPECTIVE_SAME_LOGIC_COMPACT",
                    "input_price_latest_date_used": feats[ticker]["latest_date"].isoformat(),
                    "input_feature_latest_date_used": feats[ticker]["latest_date"].isoformat(),
                    "pit_status": "PIT_LITE_REPLAY",
                    "warning_flags": "PIT_LITE_NON_PRICE_FIELDS",
                })
        aggregate = {ticker: sum(strategy_scores[s][ticker] for s in STRATEGIES) / len(STRATEGIES) for ticker in feats}
        for rank, (ticker, score) in enumerate(sorted(aggregate.items(), key=lambda kv: kv[1], reverse=True), 1):
            rows.append({
                "replay_ranking_date": d.isoformat(),
                "strategy": "ABCDE_AGGREGATE",
                "ticker": ticker,
                "rank": rank,
                "score": round(score, 10),
                "source_mode": "LOCAL_MOOMOO_QFQ",
                "replay_mode": "RETROSPECTIVE_SAME_LOGIC_COMPACT",
                "input_price_latest_date_used": feats[ticker]["latest_date"].isoformat(),
                "input_feature_latest_date_used": feats[ticker]["latest_date"].isoformat(),
                "pit_status": "PIT_LITE_REPLAY",
                "warning_flags": "PIT_LITE_NON_PRICE_FIELDS",
            })
    return rows, coverage, missing


def top_summary(rows: list[dict[str, Any]], topn: int) -> list[dict[str, Any]]:
    return [r for r in rows if int(r["rank"]) <= topn]


def overlap_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    by_key: dict[tuple[str, str], set[str]] = {}
    for r in rows:
        if int(r["rank"]) <= 20:
            by_key.setdefault((r["replay_ranking_date"], r["strategy"]), set()).add(r["ticker"])
    dates = sorted({k[0] for k in by_key})
    strategies = sorted({k[1] for k in by_key})
    for d in dates:
        for i, left in enumerate(strategies):
            for right in strategies[i + 1:]:
                a, b = by_key.get((d, left), set()), by_key.get((d, right), set())
                if a and b:
                    out.append({"replay_ranking_date": d, "strategy_left": left, "strategy_right": right, "top20_overlap_count": len(a & b), "top20_overlap_ratio": len(a & b) / 20})
    return out


def input_audit(repo_root: Path, price_path: Path, dates: list[date]) -> list[dict[str, Any]]:
    return [{
        "source_name": "canonical_moomoo_qfq",
        "source_path": str(price_path),
        "read_only": True,
        "effective_date_rule": "price_date <= replay_ranking_date",
        "replay_start_date": dates[0].isoformat() if dates else "",
        "replay_end_date": dates[-1].isoformat() if dates else "",
        "notes": "no forward outcome columns used for ranking generation",
    }]


def pit_lite_audit(dates: list[date]) -> list[dict[str, Any]]:
    return [{"replay_ranking_date": d.isoformat(), "field_or_source": field, "pit_status": "PIT_LITE_REPLAY", "reason": "strict historical as-of non-price source unavailable; compact replay uses local price-only proxy"} for d in dates for field in PIT_LITE_FIELDS]


def run(repo_root: Path, output_dir: Path | None = None, price_path: Path | None = None) -> dict[str, Any]:
    output_dir = output_dir or repo_root / OUT_REL
    output_dir.mkdir(parents=True, exist_ok=True)
    price_path = price_path or canonical_qfq_path(repo_root)
    if not price_path:
        raise FileNotFoundError("canonical qfq price path unavailable")
    before_stat = price_path.stat()
    panel = load_price_panel(price_path)
    dates = trading_dates(panel, START_DATE, END_DATE)
    rows, coverage, missing = replay(panel, dates)
    fields = ["replay_ranking_date", "strategy", "ticker", "rank", "score", "source_mode", "replay_mode", "input_price_latest_date_used", "input_feature_latest_date_used", "pit_status", "warning_flags"]
    write_csv(output_dir / "abcde_replay_strategy_ranking_master.csv", rows, fields)
    write_csv(output_dir / "abcde_replay_top20_summary.csv", top_summary(rows, 20), fields)
    write_csv(output_dir / "abcde_replay_top50_summary.csv", top_summary(rows, 50), fields)
    write_csv(output_dir / "abcde_replay_top100_summary.csv", top_summary(rows, 100), fields)
    write_csv(output_dir / "abcde_replay_input_source_audit.csv", input_audit(repo_root, price_path, dates), ["source_name", "source_path", "read_only", "effective_date_rule", "replay_start_date", "replay_end_date", "notes"])
    write_csv(output_dir / "abcde_replay_pit_lite_audit.csv", pit_lite_audit(dates), ["replay_ranking_date", "field_or_source", "pit_status", "reason"])
    write_csv(output_dir / "abcde_replay_missing_strategy_date_audit.csv", missing, ["replay_ranking_date", "strategy", "missing_reason", "severity"])
    write_csv(output_dir / "abcde_replay_coverage_audit.csv", coverage, ["replay_ranking_date", "eligible_ticker_count", "source_mode", "notes"])
    write_csv(output_dir / "abcde_replay_overlap_audit.csv", overlap_rows(rows), ["replay_ranking_date", "strategy_left", "strategy_right", "top20_overlap_count", "top20_overlap_ratio"])
    strategies = sorted({r["strategy"] for r in rows})
    expected_count = len(dates) * len(STRATEGIES)
    missing_count = len(missing)
    pit_count = len(PIT_LITE_FIELDS)
    final_status = "FAIL_V21_244_ABCDE_REPLAY_BLOCKED" if not rows else "WARN_V21_244_ABCDE_REPLAY_READY_PIT_LITE" if pit_count else "PASS_V21_244_ABCDE_REPLAY_READY"
    if rows and missing_count:
        final_status = "PARTIAL_PASS_V21_244_ABCDE_REPLAY_MISSING_DATES"
    after_stat = price_path.stat()
    summary = {
        "final_status": final_status,
        "final_decision": "ABCDE_RETROSPECTIVE_REPLAY_READY_FOR_V21_243_R1_RESEARCH_ONLY",
        "replay_start_date": START_DATE.isoformat(),
        "replay_end_date": END_DATE.isoformat(),
        "replay_trading_dates": [d.isoformat() for d in dates],
        "strategies_replayed": strategies,
        "strategy_date_count": len({(r["replay_ranking_date"], r["strategy"]) for r in rows if r["strategy"] in STRATEGIES}),
        "missing_strategy_date_count": max(0, expected_count - len({(r["replay_ranking_date"], r["strategy"]) for r in rows if r["strategy"] in STRATEGIES})) + missing_count,
        "replay_rows_created": len(rows),
        "top20_rows_created": len(top_summary(rows, 20)),
        "top50_rows_created": len(top_summary(rows, 50)),
        "top100_rows_created": len(top_summary(rows, 100)),
        "strict_pit_possible": False,
        "pit_lite_field_count": pit_count,
        "warning_count": pit_count,
        "error_count": 0 if rows else 1,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "protected_outputs_modified": False,
        "input_files_mutated": before_stat.st_size != after_stat.st_size or before_stat.st_mtime != after_stat.st_mtime,
    }
    write_json(output_dir / "v21_244_summary.json", summary)
    (output_dir / "V21.244_abcde_retrospective_replay_report.txt").write_text("\n".join([STAGE, f"final_status={final_status}", "replay_snapshot_type=retrospective same-logic replay snapshot", "forward_outcome_evaluation=deferred to V21.243_R1", "broker_action_allowed=False", "official_adoption_allowed=False"]) + "\n", encoding="utf-8")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--price-path", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(args.repo_root.resolve(), args.output_dir, args.price_path)
    print(str((args.output_dir or (args.repo_root / OUT_REL)) / "v21_244_summary.json"))
    return 1 if summary["final_status"].startswith("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
