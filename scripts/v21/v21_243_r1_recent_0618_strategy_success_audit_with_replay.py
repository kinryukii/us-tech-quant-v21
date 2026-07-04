#!/usr/bin/env python
"""V21.243_R1 recent strategy success audit including V21.244 replay snapshots."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from datetime import date
from pathlib import Path
from typing import Any


STAGE = "V21.243_R1_RECENT_0618_STRATEGY_SUCCESS_AUDIT_WITH_REPLAY"
OUT_REL = Path("outputs/v21") / STAGE
START_DATE = date(2026, 6, 18)
STRATEGIES = {"A1", "B", "C", "D", "E_R1", "ABCDE_AGGREGATE"}
BENCHMARKS = {"DRAM", "QQQ", "SOXX", "SMH"}


def load_v243():
    path = Path(__file__).with_name("v21_243_recent_0618_strategy_success_audit.py")
    spec = importlib.util.spec_from_file_location("v21_243_base", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


v243 = load_v243()


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
    return v243.read_csv_dict(path)


def load_replay_rankings(repo_root: Path, replay_path: Path | None = None) -> list[dict[str, Any]]:
    path = replay_path or repo_root / "outputs/v21/V21.244_ABCDE_RETROSPECTIVE_REPLAY_0618_TO_0629/abcde_replay_strategy_ranking_master.csv"
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for row in read_csv_dict(path):
        rd = v243.parse_date(row.get("replay_ranking_date") or "")
        if not rd or rd < START_DATE:
            continue
        rows.append({
            "ranking_date": rd,
            "strategy": v243.normalize_strategy(row.get("strategy") or ""),
            "ticker": (row.get("ticker") or "").upper(),
            "rank": int(float(row.get("rank") or 0)),
            "score": v243.to_float(row.get("score")),
            "source_file": str(path),
            "source_mode": "RETROSPECTIVE_PIT_LITE_REPLAY",
            "pit_status": row.get("pit_status") or "PIT_LITE_REPLAY",
        })
    return [r for r in rows if r["ticker"] and r["rank"] > 0]


def load_live_rankings(repo_root: Path) -> list[dict[str, Any]]:
    rows = v243.discover_rankings(repo_root, START_DATE)
    for row in rows:
        row["source_mode"] = "LIVE_SNAPSHOT"
        row["pit_status"] = "LIVE_ORIGINAL"
    return rows


def merge_rankings(live: list[dict[str, Any]], replay: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    live_keys = {(r["ranking_date"], r["strategy"]) for r in live}
    merged = list(live)
    source_audit: list[dict[str, Any]] = []
    for d, s in sorted({(r["ranking_date"], r["strategy"]) for r in live + replay}):
        live_count = sum(1 for r in live if r["ranking_date"] == d and r["strategy"] == s)
        replay_count = sum(1 for r in replay if r["ranking_date"] == d and r["strategy"] == s)
        selected = "LIVE_SNAPSHOT" if live_count else "RETROSPECTIVE_PIT_LITE_REPLAY" if replay_count else "MISSING"
        source_audit.append({
            "ranking_date": d.isoformat(),
            "strategy": s,
            "live_row_count": live_count,
            "replay_row_count": replay_count,
            "selected_source_mode": selected,
            "priority_rule": "live snapshot preferred over replay on overlap",
        })
    for row in replay:
        if (row["ranking_date"], row["strategy"]) not in live_keys:
            merged.append(row)
    return merged, source_audit


def add_benchmarks(rankings: list[dict[str, Any]], prices: dict[str, dict[date, float]]) -> None:
    ranking_dates = sorted({r["ranking_date"] for r in rankings})
    for d in ranking_dates:
        if "DRAM" in prices:
            rankings.append({"ranking_date": d, "strategy": "DRAM", "ticker": "DRAM", "rank": 1, "score": None, "source_file": "benchmark_local_price", "source_mode": "BENCHMARK_LOCAL_PRICE", "pit_status": "BENCHMARK"})
        for ticker in ("QQQ", "SOXX", "SMH"):
            if ticker in prices:
                rankings.append({"ranking_date": d, "strategy": ticker, "ticker": ticker, "rank": 1, "score": None, "source_file": "benchmark_local_price", "source_mode": "BENCHMARK_LOCAL_PRICE", "pit_status": "BENCHMARK"})


def calc_forward_rows(rankings: list[dict[str, Any]], prices: dict[str, dict[date, float]], trading_dates: list[date]) -> list[dict[str, Any]]:
    rows = v243.calc_forward_rows(rankings, prices, trading_dates)
    for row in rows:
        row.setdefault("source_mode", "UNKNOWN")
        row.setdefault("pit_status", "UNKNOWN")
    return rows


def aggregate_with_source(forward_rows: list[dict[str, Any]], mode: str, strict_start: date | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = [r for r in forward_rows if mode == "FULL_AVAILABLE_WINDOW" or (strict_start and r["ranking_date"] >= strict_start and r["strategy"] in STRATEGIES)]
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for r in rows:
        for topn in v243.TOPNS:
            if r["rank"] <= topn:
                groups.setdefault((mode, r["ranking_date"], r["strategy"], r["forward_window"], topn, r["source_mode"], r["pit_status"]), []).append(r)
    by_date: list[dict[str, Any]] = []
    for (mode, rd, strat, win, topn, source, pit), group in groups.items():
        matured = [r for r in group if r["maturity_status"] == "MATURED" and r["forward_return"] is not None]
        returns = [float(r["forward_return"]) for r in matured]
        by_date.append({
            "comparison_mode": mode,
            "ranking_date": rd.isoformat(),
            "strategy": strat,
            "forward_window": win,
            "top_n": topn,
            "source_mode": source,
            "pit_status": pit,
            "matured_count": len(returns),
            "pending_count": sum(1 for r in group if r["maturity_status"] == "PENDING_MATURITY"),
            "average_forward_return": sum(returns) / len(returns) if returns else None,
            "median_forward_return": v243.median(returns),
            "positive_rate": sum(1 for x in returns if x > 0) / len(returns) if returns else None,
            "p10_forward_return": v243.quantile(returns, 0.1),
            "worst_ticker_return": min(returns) if returns else None,
            "worst5_average_return": sum(sorted(returns)[:5]) / min(5, len(returns)) if returns else None,
            "top_name_contribution_share": max(returns) / sum(returns) if returns and sum(returns) > 0 else None,
            "loser_count": sum(1 for x in returns if x < 0),
            "spearman_rank_return": v243.spearman_rank([float(r["rank"]) for r in matured], returns),
        })
    summary_groups: dict[tuple, list[dict[str, Any]]] = {}
    for r in by_date:
        summary_groups.setdefault((r["comparison_mode"], r["strategy"], r["forward_window"], r["top_n"], r["source_mode"], r["pit_status"]), []).append(r)
    summary: list[dict[str, Any]] = []
    for (mode, strat, win, topn, source, pit), group in summary_groups.items():
        avgs = [r["average_forward_return"] for r in group if r["average_forward_return"] is not None]
        meds = [r["median_forward_return"] for r in group if r["median_forward_return"] is not None]
        summary.append({
            "comparison_mode": mode,
            "strategy": strat,
            "forward_window": win,
            "top_n": topn,
            "source_mode": source,
            "pit_status": pit,
            "ranking_date_count": len(group),
            "matured_ranking_date_count": sum(1 for r in group if r["matured_count"] > 0),
            "average_forward_return": sum(avgs) / len(avgs) if avgs else None,
            "median_forward_return": v243.median(meds),
            "positive_date_rate": sum(1 for v in avgs if v > 0) / len(avgs) if avgs else None,
            "p10_forward_return": v243.quantile([r["p10_forward_return"] for r in group if r["p10_forward_return"] is not None], 0.1),
            "worst5_average_return": min([r["worst5_average_return"] for r in group if r["worst5_average_return"] is not None], default=None),
            "pending_count": sum(r["pending_count"] for r in group),
        })
    return by_date, summary


def comparison_audits(summary_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    by_key = {(r["comparison_mode"], r["strategy"], r["forward_window"], r["top_n"]): r for r in summary_rows}
    vs_a1: list[dict[str, Any]] = []
    vs_dram: list[dict[str, Any]] = []
    vs_bench: list[dict[str, Any]] = []
    for r in summary_rows:
        avg = r.get("average_forward_return")
        if avg is None:
            continue
        a1 = by_key.get((r["comparison_mode"], "A1", r["forward_window"], r["top_n"]), {}).get("average_forward_return")
        if a1 is not None and r["strategy"] != "A1":
            vs_a1.append({**r, "benchmark": "A1", "excess_return": avg - a1})
        dram = by_key.get((r["comparison_mode"], "DRAM", r["forward_window"], 20), {}).get("average_forward_return")
        if dram is not None and r["strategy"] != "DRAM":
            vs_dram.append({**r, "benchmark": "DRAM", "excess_return": avg - dram})
        for b in ("QQQ", "SOXX", "SMH"):
            bv = by_key.get((r["comparison_mode"], b, r["forward_window"], 20), {}).get("average_forward_return")
            if bv is not None and r["strategy"] != b:
                vs_bench.append({**r, "benchmark": b, "excess_return": avg - bv})
    return vs_a1, vs_dram, vs_bench


def strict_start(rankings: list[dict[str, Any]]) -> date | None:
    by_date: dict[date, set[str]] = {}
    for r in rankings:
        if r["strategy"] in STRATEGIES:
            by_date.setdefault(r["ranking_date"], set()).add(r["strategy"])
    dates = [d for d, s in by_date.items() if {"A1", "B", "C", "D", "E_R1"}.issubset(s)]
    return min(dates) if dates else None


def bucket_monotonicity(forward_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for strat in sorted({r["strategy"] for r in forward_rows}):
        for win in [f"{w}D" for w in v243.WINDOWS]:
            m = [r for r in forward_rows if r["strategy"] == strat and r["forward_window"] == win and r["maturity_status"] == "MATURED" and r["forward_return"] is not None]
            def avg(lo: int, hi: int):
                vals = [r["forward_return"] for r in m if lo <= r["rank"] <= hi]
                return sum(vals) / len(vals) if vals else None
            a, b, c = avg(1, 20), avg(21, 50), avg(51, 100)
            rows.append({"strategy": strat, "forward_window": win, "top20_avg": a, "rank21_50_avg": b, "rank51_100_avg": c, "monotonic_pass": a is not None and b is not None and c is not None and a >= b >= c})
    return rows


def overlap_turnover(rankings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for strat in sorted({r["strategy"] for r in rankings}):
        prev = None
        for d in sorted({r["ranking_date"] for r in rankings if r["strategy"] == strat}):
            cur = {r["ticker"] for r in rankings if r["strategy"] == strat and r["ranking_date"] == d and r["rank"] <= 20}
            out.append({"strategy": strat, "ranking_date": d.isoformat(), "source_mode": next((r["source_mode"] for r in rankings if r["strategy"] == strat and r["ranking_date"] == d), ""), "top20_count": len(cur), "top20_overlap_with_prior": len(cur & prev) if prev is not None else "", "top20_turnover": 1 - len(cur & prev) / len(cur) if prev and cur else ""})
            prev = cur
    return out


def run(repo_root: Path, output_dir: Path | None = None, price_path: Path | None = None, replay_path: Path | None = None) -> dict[str, Any]:
    output_dir = output_dir or repo_root / OUT_REL
    output_dir.mkdir(parents=True, exist_ok=True)
    prices, trading_dates = v243.load_prices(repo_root, price_path)
    live = load_live_rankings(repo_root)
    replay = load_replay_rankings(repo_root, replay_path)
    rankings, source_audit = merge_rankings(live, replay)
    add_benchmarks(rankings, prices)
    strict = strict_start(rankings)
    forward_rows = calc_forward_rows(rankings, prices, trading_dates)
    by_full, sum_full = aggregate_with_source(forward_rows, "FULL_AVAILABLE_WINDOW", None)
    by_strict, sum_strict = aggregate_with_source(forward_rows, "STRICT_ABCDE_COMPARABLE_WINDOW", strict)
    by_date = by_full + by_strict
    summary_rows = sum_full + sum_strict
    vs_a1, vs_dram, vs_bench = comparison_audits(summary_rows)
    maturity = []
    for win in [f"{w}D" for w in v243.WINDOWS]:
        maturity.append({"forward_window": win, "matured_count": sum(1 for r in forward_rows if r["forward_window"] == win and r["maturity_status"] == "MATURED"), "pending_count": sum(1 for r in forward_rows if r["forward_window"] == win and r["maturity_status"] == "PENDING_MATURITY"), "missing_price_count": sum(1 for r in forward_rows if r["forward_window"] == win and str(r["maturity_status"]).startswith("MISSING"))})
    fields_summary = ["comparison_mode", "strategy", "forward_window", "top_n", "source_mode", "pit_status", "ranking_date_count", "matured_ranking_date_count", "average_forward_return", "median_forward_return", "positive_date_rate", "p10_forward_return", "worst5_average_return", "pending_count"]
    write_csv(output_dir / "recent_0618_r1_strategy_success_summary.csv", summary_rows, fields_summary)
    write_csv(output_dir / "recent_0618_r1_strategy_success_by_date.csv", by_date, ["comparison_mode", "ranking_date", "strategy", "forward_window", "top_n", "source_mode", "pit_status", "matured_count", "pending_count", "average_forward_return", "median_forward_return", "positive_rate", "p10_forward_return", "worst_ticker_return", "worst5_average_return", "top_name_contribution_share", "loser_count", "spearman_rank_return"])
    ticker_rows = [{k: (v.isoformat() if isinstance(v, date) else v) for k, v in r.items()} for r in forward_rows]
    write_csv(output_dir / "recent_0618_r1_strategy_success_by_ticker.csv", ticker_rows, ["ranking_date", "strategy", "ticker", "rank", "score", "source_file", "source_mode", "pit_status", "forward_window", "target_price_date", "start_close", "target_close", "forward_return", "maturity_status"])
    write_csv(output_dir / "recent_0618_r1_strategy_success_maturity_matrix.csv", maturity, ["forward_window", "matured_count", "pending_count", "missing_price_count"])
    write_csv(output_dir / "recent_0618_r1_strategy_source_audit.csv", source_audit, ["ranking_date", "strategy", "live_row_count", "replay_row_count", "selected_source_mode", "priority_rule"])
    write_csv(output_dir / "recent_0618_r1_strategy_vs_a1_audit.csv", vs_a1, fields_summary + ["benchmark", "excess_return"])
    write_csv(output_dir / "recent_0618_r1_strategy_vs_dram_audit.csv", vs_dram, fields_summary + ["benchmark", "excess_return"])
    write_csv(output_dir / "recent_0618_r1_strategy_vs_benchmark_audit.csv", vs_bench, fields_summary + ["benchmark", "excess_return"])
    write_csv(output_dir / "recent_0618_r1_strategy_tail_risk_audit.csv", [{k: r.get(k) for k in ("comparison_mode", "strategy", "forward_window", "top_n", "source_mode", "pit_status", "p10_forward_return", "worst5_average_return", "pending_count")} for r in summary_rows], ["comparison_mode", "strategy", "forward_window", "top_n", "source_mode", "pit_status", "p10_forward_return", "worst5_average_return", "pending_count"])
    write_csv(output_dir / "recent_0618_r1_strategy_bucket_monotonicity.csv", bucket_monotonicity(forward_rows), ["strategy", "forward_window", "top20_avg", "rank21_50_avg", "rank51_100_avg", "monotonic_pass"])
    write_csv(output_dir / "recent_0618_r1_strategy_overlap_turnover.csv", overlap_turnover(rankings), ["strategy", "ranking_date", "source_mode", "top20_count", "top20_overlap_with_prior", "top20_turnover"])
    impact_rows = [r for r in summary_rows if r["source_mode"] == "RETROSPECTIVE_PIT_LITE_REPLAY"]
    write_csv(output_dir / "recent_0618_r1_pit_lite_replay_impact_audit.csv", impact_rows, fields_summary)
    def best(field: str) -> str:
        c = [r for r in summary_rows if r["comparison_mode"] == "FULL_AVAILABLE_WINDOW" and r["top_n"] == 20 and r["forward_window"] == "1D" and r.get(field) is not None and r["strategy"] not in BENCHMARKS]
        return max(c, key=lambda r: r[field])["strategy"] if c else ""
    def best_excess(rows: list[dict[str, Any]]) -> str:
        c = [r for r in rows if r["top_n"] == 20 and r["forward_window"] == "1D" and r.get("excess_return") is not None and r["strategy"] not in BENCHMARKS]
        return max(c, key=lambda r: r["excess_return"])["strategy"] if c else ""
    full_dates = sorted({r["ranking_date"] for r in rankings if r["strategy"] in STRATEGIES})
    live_dates = {r["ranking_date"] for r in rankings if r["source_mode"] == "LIVE_SNAPSHOT" and r["strategy"] in STRATEGIES}
    replay_dates = {r["ranking_date"] for r in rankings if r["source_mode"] == "RETROSPECTIVE_PIT_LITE_REPLAY"}
    summary = {
        "final_status": "MIXED_RECENT_SIGNAL_WITH_PIT_LITE_REPLAY" if maturity[2]["matured_count"] or maturity[3]["matured_count"] else "WAIT_MORE_MATURITY_WITH_PIT_LITE_REPLAY",
        "final_decision": "RECENT_0618_STRATEGY_SUCCESS_AUDIT_WITH_REPLAY_READY_RESEARCH_ONLY",
        "audit_start_ranking_date": START_DATE.isoformat(),
        "latest_completed_price_date_used": max(trading_dates).isoformat(),
        "full_available_ranking_date_min": min(full_dates).isoformat() if full_dates else "",
        "full_available_ranking_date_max": max(full_dates).isoformat() if full_dates else "",
        "strict_abcde_comparable_start_date": strict.isoformat() if strict else "",
        "live_snapshot_date_count": len(live_dates),
        "replay_snapshot_date_count": len(replay_dates),
        "pit_lite_replay_date_count": len(replay_dates),
        "strategies_compared": sorted({r["strategy"] for r in rankings if r["strategy"] in STRATEGIES}),
        "benchmarks_compared": sorted({r["strategy"] for r in rankings if r["strategy"] in BENCHMARKS}),
        "matured_1d_count": maturity[0]["matured_count"], "matured_2d_count": maturity[1]["matured_count"], "matured_3d_count": maturity[2]["matured_count"], "matured_5d_count": maturity[3]["matured_count"],
        "pending_1d_count": maturity[0]["pending_count"], "pending_2d_count": maturity[1]["pending_count"], "pending_3d_count": maturity[2]["pending_count"], "pending_5d_count": maturity[3]["pending_count"],
        "best_top20_strategy_by_avg_return": best("average_forward_return"),
        "best_top20_strategy_by_median_return": best("median_forward_return"),
        "best_top20_strategy_by_excess_vs_A1": best_excess(vs_a1),
        "best_top20_strategy_by_excess_vs_DRAM": best_excess(vs_dram),
        "best_risk_adjusted_strategy": best("positive_date_rate"),
        "worst_left_tail_strategy": min([r for r in summary_rows if r["top_n"] == 20 and r["forward_window"] == "1D" and r.get("p10_forward_return") is not None and r["strategy"] not in BENCHMARKS], key=lambda r: r["p10_forward_return"])["strategy"] if summary_rows else "",
        "abcde_aggregate_rank": next((i + 1 for i, r in enumerate(sorted([r for r in summary_rows if r["top_n"] == 20 and r["forward_window"] == "1D" and r.get("average_forward_return") is not None and r["strategy"] in STRATEGIES], key=lambda r: r["average_forward_return"], reverse=True)) if r["strategy"] == "ABCDE_AGGREGATE"), None),
        "warning_count": 1,
        "error_count": 0,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "protected_outputs_modified": False,
        "input_files_mutated": False,
        "source_contains_pit_lite_replay": True,
    }
    write_json(output_dir / "v21_243_r1_summary.json", summary)
    (output_dir / "V21.243_R1_recent_0618_strategy_success_report.txt").write_text("\n".join([STAGE, f"final_status={summary['final_status']}", f"final_decision={summary['final_decision']}", "broker_action_allowed=False", "official_adoption_allowed=False"]) + "\n", encoding="utf-8")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--price-path", type=Path, default=None)
    parser.add_argument("--replay-path", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(args.repo_root.resolve(), args.output_dir, args.price_path, args.replay_path)
    print(str((args.output_dir or (args.repo_root / OUT_REL)) / "v21_243_r1_summary.json"))
    return 1 if summary["final_status"].startswith("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
