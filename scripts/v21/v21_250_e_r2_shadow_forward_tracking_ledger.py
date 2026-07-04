#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import mean
from typing import Any

STAGE = "V21.250_E_R2_SHADOW_FORWARD_TRACKING_LEDGER"
OUT_REL = Path("outputs/v21") / STAGE
V247_REL = Path("outputs/v21/V21.247_REWEIGHTED_STRATEGY_REPLAY_AND_FORWARD_BACKTEST")
V249_REL = Path("outputs/v21/V21.249_SHADOW_CANDIDATE_SELECTION_AND_FORWARD_TRACKING_GATE")
TRACKED = ["A1", "E_R1", "E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL", "DRAM", "QQQ", "SMH", "SOXX"]
WINDOWS = ["1D", "2D", "3D", "5D", "10D"]
TOPNS = ["20", "50", "100"]


def rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def wcsv(path: Path, data: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(data)


def wjson(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def fnum(v: Any, default: float = 0.0) -> float:
    try:
        if v in (None, ""):
            return default
        return float(v)
    except Exception:
        return default


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def metric(summary_rows: list[dict[str, str]], strategy: str, window: str, top_n: str) -> dict[str, str]:
    for row in summary_rows:
        if row.get("strategy") == strategy and row.get("forward_window") == window and str(row.get("top_n")) == str(top_n):
            return row
    return {}


def status_vs(summary_rows: list[dict[str, str]], left: str, right: str) -> str:
    left_row = metric(summary_rows, left, "1D", "20")
    right_row = metric(summary_rows, right, "1D", "20")
    if not left_row or not right_row:
        return "INSUFFICIENT_DATA"
    avg_ok = fnum(left_row.get("average_return")) >= fnum(right_row.get("average_return"))
    tail_ok = fnum(left_row.get("p10_return")) >= fnum(right_row.get("p10_return")) and fnum(left_row.get("worst5_return")) >= fnum(right_row.get("worst5_return"))
    if avg_ok and tail_ok:
        return "OUTPERFORMS_OR_PRESERVES_TAIL"
    if avg_ok:
        return "RETURN_OK_TAIL_WATCH"
    return "UNDERPERFORMS"


def run(repo: Path, output_dir: Path | None = None) -> dict[str, Any]:
    out = output_dir or repo / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    by_ticker_path = repo / V247_REL / "reweighted_strategy_forward_success_by_ticker.csv"
    summary_path = repo / V247_REL / "reweighted_strategy_forward_success_summary.csv"
    v249_summary = load_json(repo / V249_REL / "v21_249_summary.json")
    if not by_ticker_path.exists() or not summary_path.exists() or v249_summary.get("recommended_shadow_tracking_candidate") != "E_R2_CONSERVATIVE_DEFENSIVE_RETURN":
        summary = {
            "final_status": "E_R2_SHADOW_TRACKING_BLOCKED",
            "final_decision": "E_R2_SHADOW_TRACKING_BLOCKED_MISSING_REQUIRED_ROWS",
            "tracking_start_date": "",
            "latest_completed_price_date_used": "",
            "strategies_tracked": [],
            "shadow_tracking_candidate": "E_R2_CONSERVATIVE_DEFENSIVE_RETURN",
            "parallel_watch_candidate": "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL",
            "matured_1d_count": 0,
            "matured_2d_count": 0,
            "matured_3d_count": 0,
            "matured_5d_count": 0,
            "pending_1d_count": 0,
            "pending_2d_count": 0,
            "pending_3d_count": 0,
            "pending_5d_count": 0,
            "e_r2_vs_e_r1_status": "INSUFFICIENT_DATA",
            "e_r2_vs_a1_status": "INSUFFICIENT_DATA",
            "e_r2_vs_new_factor_lite_status": "INSUFFICIENT_DATA",
            "e_r2_tail_risk_status": "INSUFFICIENT_DATA",
            "shadow_forward_tracking_allowed": False,
            "official_adoption_allowed": False,
            "broker_action_allowed": False,
            "protected_outputs_modified": False,
            "input_files_mutated": False,
            "warning_count": 0,
            "error_count": 1,
        }
        wjson(out / "v21_250_summary.json", summary)
        return summary

    raw = [r for r in rows(by_ticker_path) if r.get("strategy") in TRACKED and r.get("forward_window") in WINDOWS[:4]]
    summary_rows = [r for r in rows(summary_path) if r.get("strategy") in TRACKED]
    ranking_dates = sorted({r.get("ranking_date") for r in raw if r.get("ranking_date")})
    latest_completed = max([r.get("target_price_date") for r in raw if r.get("maturity_status") == "MATURED" and r.get("target_price_date")] or [""])
    for strategy in TRACKED:
        for top_n in TOPNS:
            for ranking_date in ranking_dates:
                raw.append({
                    "ranking_date": ranking_date,
                    "strategy": strategy,
                    "ticker": "__PENDING_10D_WINDOW__",
                    "rank": "",
                    "candidate_source_strategy": strategy,
                    "source_mode": "TRACKING_PLACEHOLDER",
                    "pit_status": "PENDING_FUTURE_MATURITY",
                    "forward_window": "10D",
                    "target_price_date": "",
                    "forward_return": "",
                    "maturity_status": "PENDING_MATURITY",
                    "top_n": top_n,
                })
    for r in raw:
        if "top_n" not in r:
            try:
                rank = int(float(r.get("rank") or 999999))
                r["top_n"] = "20" if rank <= 20 else "50" if rank <= 50 else "100" if rank <= 100 else "OUTSIDE_TOP100"
            except Exception:
                r["top_n"] = ""

    maturity = []
    for window in WINDOWS:
        subset = [r for r in raw if r.get("forward_window") == window and r.get("strategy") == "E_R2_CONSERVATIVE_DEFENSIVE_RETURN"]
        maturity.append({
            "strategy": "E_R2_CONSERVATIVE_DEFENSIVE_RETURN",
            "forward_window": window,
            "matured_count": sum(1 for r in subset if r.get("maturity_status") == "MATURED"),
            "pending_count": sum(1 for r in subset if r.get("maturity_status") != "MATURED"),
            "latest_completed_price_date_used": latest_completed,
            "notes": "10D is initialized as pending until enough future completed sessions exist" if window == "10D" else "from V21.247 preserved rows",
        })

    def audit_vs(base: str) -> list[dict[str, Any]]:
        out_rows = []
        for window in WINDOWS[:4]:
            for topn in TOPNS:
                e = metric(summary_rows, "E_R2_CONSERVATIVE_DEFENSIVE_RETURN", window, topn)
                b = metric(summary_rows, base, window, topn)
                out_rows.append({
                    "comparison": f"E_R2_vs_{base}",
                    "forward_window": window,
                    "top_n": topn,
                    "e_r2_average_return": e.get("average_return", ""),
                    "benchmark_average_return": b.get("average_return", ""),
                    "excess_return": fnum(e.get("average_return"), 0) - fnum(b.get("average_return"), 0) if e and b else "",
                    "e_r2_p10": e.get("p10_return", ""),
                    "benchmark_p10": b.get("p10_return", ""),
                    "status": "PRESENT" if e and b else "MISSING_COMPARISON",
                })
        return out_rows

    tail = []
    for window in WINDOWS[:4]:
        for topn in TOPNS:
            e = metric(summary_rows, "E_R2_CONSERVATIVE_DEFENSIVE_RETURN", window, topn)
            if e:
                tail.append({
                    "strategy": "E_R2_CONSERVATIVE_DEFENSIVE_RETURN",
                    "forward_window": window,
                    "top_n": topn,
                    "p10_return": e.get("p10_return", ""),
                    "worst5_return": e.get("worst5_return", ""),
                    "tail_risk_status": "PASS" if fnum(e.get("p10_return")) > -0.05 else "WATCH",
                    "notes": "research-only shadow tracking",
                })
    turnover = [{
        "strategy": s,
        "turnover_proxy": "SOURCE_MODE_STABILITY",
        "tracked": True,
        "notes": "turnover inherited from V21.247 source-mode stability audit",
    } for s in TRACKED]
    benchmark = audit_vs("QQQ") + audit_vs("SMH") + audit_vs("SOXX") + audit_vs("DRAM")
    latest_rows = []
    for s in TRACKED:
        dated = [r for r in summary_rows if r.get("strategy") == s and r.get("forward_window") == "1D" and str(r.get("top_n")) == "20"]
        latest_rows.extend(dated[:1])

    matured = {w.lower(): sum(int(r["matured_count"]) for r in maturity if r["forward_window"] == w) for w in WINDOWS[:4]}
    pending = {w.lower(): sum(int(r["pending_count"]) for r in maturity if r["forward_window"] == w) for w in WINDOWS[:4]}
    e_vs_e1 = status_vs(summary_rows, "E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "E_R1")
    e_vs_a1 = status_vs(summary_rows, "E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "A1")
    e_vs_new = status_vs(summary_rows, "E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL")
    tail_status = "PASS" if all(r["tail_risk_status"] == "PASS" for r in tail if r["top_n"] == "20") else "WATCH"
    if matured["1d"] == 0:
        final_status = "E_R2_SHADOW_TRACKING_WAIT_MATURITY"
        final_decision = "E_R2_SHADOW_LEDGER_CREATED_WAIT_FORWARD_MATURITY_RESEARCH_ONLY"
    else:
        final_status = "E_R2_SHADOW_TRACKING_STARTED"
        final_decision = "E_R2_SHADOW_FORWARD_TRACKING_LEDGER_READY_RESEARCH_ONLY"

    summary = {
        "final_status": final_status,
        "final_decision": final_decision,
        "tracking_start_date": min(ranking_dates) if ranking_dates else "",
        "latest_completed_price_date_used": latest_completed,
        "strategies_tracked": TRACKED,
        "shadow_tracking_candidate": "E_R2_CONSERVATIVE_DEFENSIVE_RETURN",
        "parallel_watch_candidate": "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL",
        "matured_1d_count": matured["1d"],
        "matured_2d_count": matured["2d"],
        "matured_3d_count": matured["3d"],
        "matured_5d_count": matured["5d"],
        "pending_1d_count": pending["1d"],
        "pending_2d_count": pending["2d"],
        "pending_3d_count": pending["3d"],
        "pending_5d_count": pending["5d"],
        "e_r2_vs_e_r1_status": e_vs_e1,
        "e_r2_vs_a1_status": e_vs_a1,
        "e_r2_vs_new_factor_lite_status": e_vs_new,
        "e_r2_tail_risk_status": tail_status,
        "shadow_forward_tracking_allowed": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": False,
        "input_files_mutated": False,
        "warning_count": 0 if final_status == "E_R2_SHADOW_TRACKING_STARTED" else 1,
        "error_count": 0,
    }

    ledger_fields = ["ranking_date", "strategy", "ticker", "rank", "candidate_source_strategy", "source_mode", "pit_status", "forward_window", "target_price_date", "forward_return", "maturity_status", "top_n"]
    wcsv(out / "e_r2_shadow_forward_tracking_ledger.csv", raw, ledger_fields)
    wcsv(out / "e_r2_shadow_forward_tracking_latest.csv", latest_rows, ["strategy", "forward_window", "top_n", "average_return", "median_return", "positive_rate", "p10_return", "worst5_return", "matured_date_count", "pit_lite_present"])
    comp_fields = ["comparison", "forward_window", "top_n", "e_r2_average_return", "benchmark_average_return", "excess_return", "e_r2_p10", "benchmark_p10", "status"]
    wcsv(out / "e_r2_vs_e_r1_vs_a1_daily_audit.csv", audit_vs("E_R1") + audit_vs("A1"), comp_fields)
    wcsv(out / "e_r2_vs_new_factor_lite_audit.csv", audit_vs("NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL"), comp_fields)
    wcsv(out / "e_r2_shadow_maturity_matrix.csv", maturity, ["strategy", "forward_window", "matured_count", "pending_count", "latest_completed_price_date_used", "notes"])
    wcsv(out / "e_r2_shadow_tail_risk_audit.csv", tail, ["strategy", "forward_window", "top_n", "p10_return", "worst5_return", "tail_risk_status", "notes"])
    wcsv(out / "e_r2_shadow_turnover_audit.csv", turnover, ["strategy", "turnover_proxy", "tracked", "notes"])
    wcsv(out / "e_r2_shadow_benchmark_audit.csv", benchmark, comp_fields)
    wjson(out / "v21_250_summary.json", summary)
    (out / "V21.250_e_r2_shadow_forward_tracking_report.txt").write_text(
        f"{STAGE}\nfinal_status={final_status}\nshadow_tracking_candidate=E_R2_CONSERVATIVE_DEFENSIVE_RETURN\nofficial_adoption_allowed=False\nbroker_action_allowed=False\n",
        encoding="utf-8",
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--output-dir", type=Path)
    args = p.parse_args(argv)
    s = run(args.repo_root.resolve(), args.output_dir)
    print(str((args.output_dir or args.repo_root / OUT_REL) / "v21_250_summary.json"))
    return 1 if s.get("error_count", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
