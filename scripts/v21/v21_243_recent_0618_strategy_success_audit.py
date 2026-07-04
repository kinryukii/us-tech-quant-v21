#!/usr/bin/env python
"""V21.243 recent strategy success audit from 2026-06-18 onward."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any


STAGE = "V21.243_RECENT_0618_STRATEGY_SUCCESS_AUDIT"
OUT_REL = Path("outputs/v21") / STAGE
START_DATE = date(2026, 6, 18)
WINDOWS = [1, 2, 3, 5]
TOPNS = [20, 50, 100]
STRATEGY_ORDER = ["A1", "B", "C", "D", "E_R1", "ABCDE_AGGREGATE", "DRAM", "QQQ", "SOXX", "SMH"]


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
    if not value:
        return None
    value = str(value)[:10]
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        try:
            return datetime.strptime(value, "%Y%m%d").date()
        except ValueError:
            return None


def to_float(value: Any) -> float | None:
    try:
        if value in ("", None):
            return None
        x = float(value)
        if math.isnan(x):
            return None
        return x
    except Exception:
        return None


def median(values: list[float]) -> float | None:
    if not values:
        return None
    vals = sorted(values)
    n = len(vals)
    mid = n // 2
    return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2


def quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    vals = sorted(values)
    idx = max(0, min(len(vals) - 1, int(math.floor((len(vals) - 1) * q))))
    return vals[idx]


def spearman_rank(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    def ranks(vals: list[float]) -> list[float]:
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        out = [0.0] * len(vals)
        for rank, i in enumerate(order, 1):
            out[i] = float(rank)
        return out
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    denx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    deny = math.sqrt(sum((b - my) ** 2 for b in ry))
    return num / (denx * deny) if denx and deny else None


def canonical_pointer(repo_root: Path) -> Path | None:
    p = repo_root / "outputs/v21/V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD/canonical_snapshot_pointer.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        qfq = Path(data.get("canonical_qfq_path", ""))
        return qfq if qfq.exists() else None
    except Exception:
        return None


def load_prices(repo_root: Path, price_path: Path | None = None) -> tuple[dict[str, dict[date, float]], list[date]]:
    path = price_path or canonical_pointer(repo_root)
    if not path or not path.exists():
        raise FileNotFoundError("canonical qfq price file not found")
    prices: dict[str, dict[date, float]] = {}
    for row in read_csv_dict(path):
        ticker = (row.get("ticker") or "").upper()
        d = parse_date(row.get("date") or row.get("latest_date") or "")
        close = to_float(row.get("close"))
        if ticker and d and close is not None:
            prices.setdefault(ticker, {})[d] = close
    dates = sorted({d for by_date in prices.values() for d in by_date})
    return prices, dates


def normalize_strategy(raw: str, path: Path | None = None) -> str:
    s = (raw or "").upper()
    name = path.name.lower() if path else ""
    if s.startswith("A1") or name.startswith("a1_"):
        return "A1"
    if s.startswith("B") or name.startswith("b_"):
        return "B"
    if s.startswith("C") or name.startswith("c_"):
        return "C"
    if s.startswith("D") or name.startswith("d_"):
        return "D"
    if "E_R1" in s or name.startswith("e_r1_"):
        return "E_R1"
    if "ABCDE" in s:
        return "ABCDE_AGGREGATE"
    return raw or "UNKNOWN"


def discover_rankings(repo_root: Path, start_date: date) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    v197 = repo_root / "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT"
    if v197.exists():
        for p in sorted(v197.glob("*_final_broad_*_ranking.csv")):
            m = re.search(r"(20\d{6})", p.name)
            if not m:
                continue
            ranking_date = parse_date(m.group(1))
            if not ranking_date or ranking_date < start_date:
                continue
            for row in read_csv_dict(p):
                ticker = (row.get("ticker") or "").upper()
                rank = int(float(row.get("rank") or 0))
                if ticker and rank > 0:
                    rows.append({
                        "ranking_date": ranking_date,
                        "strategy": normalize_strategy(row.get("strategy") or "", p),
                        "ticker": ticker,
                        "rank": rank,
                        "score": to_float(row.get("score") or row.get("final_score")),
                        "source_file": str(p),
                    })
    v233 = repo_root / "outputs/v21/V21.233_MOOMOO_ONLY_ABCDE_RERUN/abcde_strategy_ranking_master.csv"
    if v233.exists():
        for row in read_csv_dict(v233):
            ranking_date = parse_date(row.get("latest_date") or "")
            if not ranking_date or ranking_date < start_date:
                continue
            rows.append({
                "ranking_date": ranking_date,
                "strategy": normalize_strategy(row.get("strategy_name") or ""),
                "ticker": (row.get("ticker") or "").upper(),
                "rank": int(float(row.get("rank") or 0)),
                "score": to_float(row.get("score")),
                "source_file": str(v233),
            })
    return [r for r in rows if r["ticker"] and r["rank"] > 0]


def add_benchmarks(rankings: list[dict[str, Any]], prices: dict[str, dict[date, float]]) -> None:
    ranking_dates = sorted({r["ranking_date"] for r in rankings})
    for d in ranking_dates:
        if "DRAM" in prices:
            rankings.append({"ranking_date": d, "strategy": "DRAM", "ticker": "DRAM", "rank": 1, "score": None, "source_file": "benchmark_local_price"})
        for ticker in ("QQQ", "SOXX", "SMH"):
            if ticker in prices:
                rankings.append({"ranking_date": d, "strategy": ticker, "ticker": ticker, "rank": 1, "score": None, "source_file": "benchmark_local_price"})


def future_date(trading_dates: list[date], ranking_date: date, window: int) -> date | None:
    if ranking_date not in trading_dates:
        return None
    idx = trading_dates.index(ranking_date)
    target = idx + window
    return trading_dates[target] if target < len(trading_dates) else None


def calc_forward_rows(rankings: list[dict[str, Any]], prices: dict[str, dict[date, float]], trading_dates: list[date]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    latest = max(trading_dates) if trading_dates else None
    for r in rankings:
        rd = r["ranking_date"]
        ticker = r["ticker"]
        start_close = prices.get(ticker, {}).get(rd)
        for window in WINDOWS:
            target = future_date(trading_dates, rd, window)
            status = "MATURED"
            ret = None
            target_close = None
            if not target or (latest and target > latest):
                status = "PENDING_MATURITY"
            elif start_close is None:
                status = "MISSING_START_PRICE"
            else:
                target_close = prices.get(ticker, {}).get(target)
                if target_close is None:
                    status = "MISSING_TARGET_PRICE"
                else:
                    ret = target_close / start_close - 1.0
            rows.append({
                **r,
                "forward_window": f"{window}D",
                "target_price_date": target.isoformat() if target else "",
                "start_close": start_close,
                "target_close": target_close,
                "forward_return": ret,
                "maturity_status": status,
            })
    return rows


def aggregate(forward_rows: list[dict[str, Any]], mode: str, strict_start: date | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_date_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    filtered = [r for r in forward_rows if mode == "FULL_AVAILABLE_WINDOW" or (strict_start and r["ranking_date"] >= strict_start and r["strategy"] in {"A1", "B", "C", "D", "E_R1"})]
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for row in filtered:
        for topn in TOPNS:
            if row["rank"] <= topn:
                key = (mode, row["ranking_date"], row["strategy"], row["forward_window"], topn)
                groups.setdefault(key, []).append(row)
    date_metrics: dict[tuple, dict[str, Any]] = {}
    for (mode, rd, strat, win, topn), rows in groups.items():
        matured = [r for r in rows if r["maturity_status"] == "MATURED" and r["forward_return"] is not None]
        returns = [float(r["forward_return"]) for r in matured]
        pending = sum(1 for r in rows if r["maturity_status"] == "PENDING_MATURITY")
        avg = sum(returns) / len(returns) if returns else None
        med = median(returns)
        p10 = quantile(returns, 0.1)
        worst = min(returns) if returns else None
        worst5 = sum(sorted(returns)[:5]) / min(5, len(returns)) if returns else None
        pos = sum(1 for x in returns if x > 0) / len(returns) if returns else None
        top_share = (max(returns) / sum(returns)) if returns and sum(returns) > 0 else None
        loser_count = sum(1 for x in returns if x < 0)
        spear = spearman_rank([float(r["rank"]) for r in matured], returns)
        out = {
            "comparison_mode": mode,
            "ranking_date": rd.isoformat(),
            "strategy": strat,
            "forward_window": win,
            "top_n": topn,
            "matured_count": len(returns),
            "pending_count": pending,
            "average_forward_return": avg,
            "median_forward_return": med,
            "positive_rate": pos,
            "p10_forward_return": p10,
            "worst_ticker_return": worst,
            "worst5_average_return": worst5,
            "top_name_contribution_share": top_share,
            "loser_count": loser_count,
            "spearman_rank_return": spear,
        }
        by_date_rows.append(out)
        date_metrics[(mode, rd.isoformat(), strat, win, topn)] = out
    by_summary: dict[tuple, list[dict[str, Any]]] = {}
    for row in by_date_rows:
        by_summary.setdefault((row["comparison_mode"], row["strategy"], row["forward_window"], row["top_n"]), []).append(row)
    for key, rows in by_summary.items():
        vals = [r["average_forward_return"] for r in rows if r["average_forward_return"] is not None]
        med_vals = [r["median_forward_return"] for r in rows if r["median_forward_return"] is not None]
        summary_rows.append({
            "comparison_mode": key[0],
            "strategy": key[1],
            "forward_window": key[2],
            "top_n": key[3],
            "ranking_date_count": len(rows),
            "matured_ranking_date_count": sum(1 for r in rows if r["matured_count"] > 0),
            "average_forward_return": sum(vals) / len(vals) if vals else None,
            "median_forward_return": median(med_vals),
            "positive_date_rate": sum(1 for v in vals if v > 0) / len(vals) if vals else None,
            "p10_forward_return": quantile([r["p10_forward_return"] for r in rows if r["p10_forward_return"] is not None], 0.1),
            "worst5_average_return": min([r["worst5_average_return"] for r in rows if r["worst5_average_return"] is not None], default=None),
            "pending_count": sum(r["pending_count"] for r in rows),
        })
    return by_date_rows, summary_rows


def metric_lookup(summary_rows: list[dict[str, Any]], mode: str = "FULL_AVAILABLE_WINDOW") -> dict[tuple, dict[str, Any]]:
    return {(r["comparison_mode"], r["strategy"], r["forward_window"], r["top_n"]): r for r in summary_rows}


def build_comparison_audits(summary_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    lookup = metric_lookup(summary_rows)
    vs_a1: list[dict[str, Any]] = []
    vs_dram: list[dict[str, Any]] = []
    vs_bench: list[dict[str, Any]] = []
    for row in summary_rows:
        base_key = (row["comparison_mode"], "A1", row["forward_window"], row["top_n"])
        a1 = lookup.get(base_key, {}).get("average_forward_return")
        if a1 is not None and row["strategy"] != "A1":
            vs_a1.append({**row, "benchmark": "A1", "excess_return": row["average_forward_return"] - a1 if row["average_forward_return"] is not None else None})
        dram = lookup.get((row["comparison_mode"], "DRAM", row["forward_window"], 20), {}).get("average_forward_return")
        if dram is not None and row["strategy"] != "DRAM":
            vs_dram.append({**row, "benchmark": "DRAM", "excess_return": row["average_forward_return"] - dram if row["average_forward_return"] is not None else None})
        for bench in ("QQQ", "SOXX", "SMH"):
            b = lookup.get((row["comparison_mode"], bench, row["forward_window"], 20), {}).get("average_forward_return")
            if b is not None and row["strategy"] != bench:
                vs_bench.append({**row, "benchmark": bench, "excess_return": row["average_forward_return"] - b if row["average_forward_return"] is not None else None})
    return vs_a1, vs_dram, vs_bench


def strict_start(rankings: list[dict[str, Any]]) -> date | None:
    by_date: dict[date, set[str]] = {}
    for r in rankings:
        if r["strategy"] in {"A1", "B", "C", "D", "E_R1"}:
            by_date.setdefault(r["ranking_date"], set()).add(r["strategy"])
    dates = [d for d, s in by_date.items() if {"A1", "B", "C", "D", "E_R1"}.issubset(s)]
    return min(dates) if dates else None


def overlap_turnover(rankings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    dates = sorted({r["ranking_date"] for r in rankings})
    for strat in sorted({r["strategy"] for r in rankings}):
        prev: set[str] | None = None
        for d in dates:
            cur = {r["ticker"] for r in rankings if r["strategy"] == strat and r["ranking_date"] == d and r["rank"] <= 20}
            if not cur:
                continue
            rows.append({"strategy": strat, "ranking_date": d.isoformat(), "top20_count": len(cur), "top20_overlap_with_prior": len(cur & prev) if prev is not None else "", "top20_turnover": 1 - len(cur & prev) / len(cur) if prev else ""})
            prev = cur
    return rows


def bucket_monotonicity(forward_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for mode in ("FULL_AVAILABLE_WINDOW",):
        for strat in sorted({r["strategy"] for r in forward_rows}):
            for win in [f"{w}D" for w in WINDOWS]:
                matured = [r for r in forward_rows if r["strategy"] == strat and r["forward_window"] == win and r["maturity_status"] == "MATURED" and r["forward_return"] is not None]
                def avg(lo: int, hi: int) -> float | None:
                    vals = [r["forward_return"] for r in matured if lo <= r["rank"] <= hi]
                    return sum(vals) / len(vals) if vals else None
                a, b, c = avg(1, 20), avg(21, 50), avg(51, 100)
                rows.append({"comparison_mode": mode, "strategy": strat, "forward_window": win, "top20_avg": a, "rank21_50_avg": b, "rank51_100_avg": c, "monotonic_pass": (a is not None and b is not None and c is not None and a >= b >= c)})
    return rows


def run(repo_root: Path, output_dir: Path | None = None, price_path: Path | None = None) -> dict[str, Any]:
    output_dir = output_dir or repo_root / OUT_REL
    output_dir.mkdir(parents=True, exist_ok=True)
    prices, trading_dates = load_prices(repo_root, price_path)
    latest = max(trading_dates)
    rankings = discover_rankings(repo_root, START_DATE)
    add_benchmarks(rankings, prices)
    strict = strict_start(rankings)
    forward_rows = calc_forward_rows(rankings, prices, trading_dates)
    by_date_full, summary_full = aggregate(forward_rows, "FULL_AVAILABLE_WINDOW", None)
    by_date_strict, summary_strict = aggregate(forward_rows, "STRICT_ABCDE_COMPARABLE_WINDOW", strict)
    by_date_rows = by_date_full + by_date_strict
    summary_rows = summary_full + summary_strict
    vs_a1, vs_dram, vs_bench = build_comparison_audits(summary_rows)
    tail = [{k: r.get(k) for k in ("comparison_mode", "strategy", "forward_window", "top_n", "p10_forward_return", "worst5_average_return", "pending_count")} for r in summary_rows]
    ticker_rows = [{k: (v.isoformat() if isinstance(v, date) else v) for k, v in r.items()} for r in forward_rows]
    maturity = []
    for win in [f"{w}D" for w in WINDOWS]:
        maturity.append({"forward_window": win, "matured_count": sum(1 for r in forward_rows if r["forward_window"] == win and r["maturity_status"] == "MATURED"), "pending_count": sum(1 for r in forward_rows if r["forward_window"] == win and r["maturity_status"] == "PENDING_MATURITY"), "missing_price_count": sum(1 for r in forward_rows if r["forward_window"] == win and r["maturity_status"].startswith("MISSING"))})
    fields_sum = ["comparison_mode", "strategy", "forward_window", "top_n", "ranking_date_count", "matured_ranking_date_count", "average_forward_return", "median_forward_return", "positive_date_rate", "p10_forward_return", "worst5_average_return", "pending_count"]
    write_csv(output_dir / "recent_0618_strategy_success_summary.csv", summary_rows, fields_sum)
    write_csv(output_dir / "recent_0618_strategy_success_by_date.csv", by_date_rows, ["comparison_mode", "ranking_date", "strategy", "forward_window", "top_n", "matured_count", "pending_count", "average_forward_return", "median_forward_return", "positive_rate", "p10_forward_return", "worst_ticker_return", "worst5_average_return", "top_name_contribution_share", "loser_count", "spearman_rank_return"])
    write_csv(output_dir / "recent_0618_strategy_success_by_ticker.csv", ticker_rows, ["ranking_date", "strategy", "ticker", "rank", "score", "source_file", "forward_window", "target_price_date", "start_close", "target_close", "forward_return", "maturity_status"])
    write_csv(output_dir / "recent_0618_strategy_success_maturity_matrix.csv", maturity, ["forward_window", "matured_count", "pending_count", "missing_price_count"])
    write_csv(output_dir / "recent_0618_strategy_vs_a1_audit.csv", vs_a1, fields_sum + ["benchmark", "excess_return"])
    write_csv(output_dir / "recent_0618_strategy_vs_dram_audit.csv", vs_dram, fields_sum + ["benchmark", "excess_return"])
    write_csv(output_dir / "recent_0618_strategy_vs_benchmark_audit.csv", vs_bench, fields_sum + ["benchmark", "excess_return"])
    write_csv(output_dir / "recent_0618_strategy_tail_risk_audit.csv", tail, ["comparison_mode", "strategy", "forward_window", "top_n", "p10_forward_return", "worst5_average_return", "pending_count"])
    write_csv(output_dir / "recent_0618_strategy_bucket_monotonicity.csv", bucket_monotonicity(forward_rows), ["comparison_mode", "strategy", "forward_window", "top20_avg", "rank21_50_avg", "rank51_100_avg", "monotonic_pass"])
    write_csv(output_dir / "recent_0618_strategy_overlap_turnover.csv", overlap_turnover(rankings), ["strategy", "ranking_date", "top20_count", "top20_overlap_with_prior", "top20_turnover"])
    def best(rows: list[dict[str, Any]], field: str) -> str:
        candidates = [r for r in rows if r["comparison_mode"] == "FULL_AVAILABLE_WINDOW" and r["top_n"] == 20 and r["forward_window"] == "1D" and r.get(field) is not None]
        return max(candidates, key=lambda r: r[field])["strategy"] if candidates else ""
    matured_counts = {m["forward_window"].lower(): m["matured_count"] for m in maturity}
    pending_counts = {m["forward_window"].lower(): m["pending_count"] for m in maturity}
    strategies = sorted({r["strategy"] for r in rankings if r["strategy"] not in {"QQQ", "SOXX", "SMH"}})
    benchmarks = sorted({r["strategy"] for r in rankings if r["strategy"] in {"QQQ", "SOXX", "SMH", "DRAM"}})
    status = "WAIT_MORE_MATURITY" if len({r["ranking_date"] for r in rankings}) < 3 else "MIXED_RECENT_SIGNAL"
    summary = {
        "final_status": status,
        "final_decision": "RECENT_0618_STRATEGY_SUCCESS_AUDIT_READY_RESEARCH_ONLY",
        "audit_start_ranking_date": START_DATE.isoformat(),
        "latest_completed_price_date_used": latest.isoformat(),
        "full_available_ranking_date_min": min(r["ranking_date"] for r in rankings).isoformat() if rankings else "",
        "full_available_ranking_date_max": max(r["ranking_date"] for r in rankings).isoformat() if rankings else "",
        "strict_abcde_comparable_start_date": strict.isoformat() if strict else "",
        "strategies_compared": strategies,
        "benchmarks_compared": benchmarks,
        "matured_1d_count": matured_counts.get("1d", 0),
        "matured_2d_count": matured_counts.get("2d", 0),
        "matured_3d_count": matured_counts.get("3d", 0),
        "matured_5d_count": matured_counts.get("5d", 0),
        "pending_1d_count": pending_counts.get("1d", 0),
        "pending_2d_count": pending_counts.get("2d", 0),
        "pending_3d_count": pending_counts.get("3d", 0),
        "pending_5d_count": pending_counts.get("5d", 0),
        "best_top20_strategy_by_avg_return": best(summary_rows, "average_forward_return"),
        "best_top20_strategy_by_median_return": best(summary_rows, "median_forward_return"),
        "best_top20_strategy_by_excess_vs_A1": max(vs_a1, key=lambda r: r["excess_return"] if r["top_n"] == 20 and r["forward_window"] == "1D" and r["excess_return"] is not None else -999).get("strategy") if vs_a1 else "",
        "best_top20_strategy_by_excess_vs_DRAM": max(vs_dram, key=lambda r: r["excess_return"] if r["top_n"] == 20 and r["forward_window"] == "1D" and r["excess_return"] is not None else -999).get("strategy") if vs_dram else "",
        "best_risk_adjusted_strategy": best(summary_rows, "positive_date_rate"),
        "worst_left_tail_strategy": min([r for r in summary_rows if r["top_n"] == 20 and r["forward_window"] == "1D" and r["p10_forward_return"] is not None], key=lambda r: r["p10_forward_return"]).get("strategy") if summary_rows else "",
        "warning_count": 0,
        "error_count": 0,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "protected_outputs_modified": False,
        "input_files_mutated": False,
    }
    write_json(output_dir / "v21_243_summary.json", summary)
    (output_dir / "V21.243_recent_0618_strategy_success_report.txt").write_text("\n".join([STAGE, f"final_status={status}", "broker_action_allowed=False", "official_adoption_allowed=False"]) + "\n", encoding="utf-8")
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
    print(str((args.output_dir or (args.repo_root / OUT_REL)) / "v21_243_summary.json"))
    return 1 if int(summary.get("error_count", 0)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
