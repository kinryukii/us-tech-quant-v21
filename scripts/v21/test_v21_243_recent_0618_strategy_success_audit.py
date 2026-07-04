from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_243_recent_0618_strategy_success_audit.py")
SPEC = importlib.util.spec_from_file_location("v21_243_stage", MODULE_PATH)
v243 = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(v243)


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def seed_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    price = tmp_path / "prices.csv"
    price_rows = []
    dates = ["2026-06-18", "2026-06-19", "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-26", "2026-06-30", "2026-07-01", "2026-07-02"]
    base = {"AAA": 10, "BBB": 20, "CCC": 30, "DRAM": 50, "QQQ": 100, "SOXX": 80, "SMH": 70}
    for i, d in enumerate(dates):
        for t, b in base.items():
            price_rows.append({"ticker": t, "date": d, "close": b + i})
    write_csv(price, price_rows, ["ticker", "date", "close"])
    v197 = repo / "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT"
    fields = ["strategy", "rank", "ticker", "final_score", "latest_price_date"]
    for strat, name in [("A1_BASELINE_CONTROL", "a1"), ("B_STATIC", "b"), ("C_DYNAMIC", "c"), ("D_WEIGHT", "d"), ("E_R1_DEF", "e_r1")]:
        for d8, d in [("20260618", "2026-06-18"), ("20260626", "2026-06-26")]:
            write_csv(v197 / f"{name}_final_broad_{d8}_ranking.csv", [
                {"strategy": strat, "rank": 1, "ticker": "AAA", "final_score": 3, "latest_price_date": d},
                {"strategy": strat, "rank": 2, "ticker": "BBB", "final_score": 2, "latest_price_date": d},
                {"strategy": strat, "rank": 51, "ticker": "CCC", "final_score": 1, "latest_price_date": d},
            ], fields)
    v233 = repo / "outputs/v21/V21.233_MOOMOO_ONLY_ABCDE_RERUN"
    write_csv(v233 / "abcde_strategy_ranking_master.csv", [
        {"strategy_name": "A1_CONTROL", "rank": 1, "ticker": "AAA", "latest_date": "2026-07-02", "score": 1},
        {"strategy_name": "B_STATIC_MOMENTUM", "rank": 1, "ticker": "BBB", "latest_date": "2026-07-02", "score": 1},
    ], ["strategy_name", "rank", "ticker", "latest_date", "score"])
    return repo, price


def run_seed(tmp_path: Path):
    repo, price = seed_repo(tmp_path)
    out = repo / "outputs/v21" / v243.STAGE
    summary = v243.run(repo, out, price)
    return repo, out, summary, price


def test_start_date_enforcement(tmp_path):
    repo, price = seed_repo(tmp_path)
    old = repo / "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT/a1_final_broad_20260617_ranking.csv"
    write_csv(old, [{"strategy": "A1_BASELINE_CONTROL", "rank": 1, "ticker": "AAA", "final_score": 1, "latest_price_date": "2026-06-17"}], ["strategy", "rank", "ticker", "final_score", "latest_price_date"])
    summary = v243.run(repo, repo / "out", price)
    assert summary["audit_start_ranking_date"] == "2026-06-18"
    assert summary["full_available_ranking_date_min"] == "2026-06-18"


def test_non_trading_day_holiday_handling(tmp_path):
    _repo, _out, summary, _price = run_seed(tmp_path)
    assert summary["latest_completed_price_date_used"] == "2026-07-02"


def test_no_same_day_lookahead_leakage(tmp_path):
    _repo, out, _summary, _price = run_seed(tmp_path)
    rows = list(csv.DictReader((out / "recent_0618_strategy_success_by_ticker.csv").open(encoding="utf-8")))
    matured = next(r for r in rows if r["ranking_date"] == "2026-06-18" and r["forward_window"] == "1D" and r["ticker"] == "AAA")
    assert matured["target_price_date"] != "2026-06-18"


def test_pending_maturity_handling(tmp_path):
    _repo, out, summary, _price = run_seed(tmp_path)
    assert summary["pending_5d_count"] > 0
    assert "PENDING_MATURITY" in (out / "recent_0618_strategy_success_by_ticker.csv").read_text(encoding="utf-8")


def test_a1_excess_return_correctness(tmp_path):
    _repo, out, _summary, _price = run_seed(tmp_path)
    rows = list(csv.DictReader((out / "recent_0618_strategy_vs_a1_audit.csv").open(encoding="utf-8")))
    assert rows
    for row in rows:
        assert row["benchmark"] == "A1"


def test_dram_benchmark_comparison_correctness(tmp_path):
    _repo, out, _summary, _price = run_seed(tmp_path)
    rows = list(csv.DictReader((out / "recent_0618_strategy_vs_dram_audit.csv").open(encoding="utf-8")))
    assert rows
    assert all(r["benchmark"] == "DRAM" for r in rows)


def test_top20_top50_aggregation_correctness(tmp_path):
    _repo, out, _summary, _price = run_seed(tmp_path)
    rows = list(csv.DictReader((out / "recent_0618_strategy_success_summary.csv").open(encoding="utf-8")))
    topns = {r["top_n"] for r in rows}
    assert {"20", "50"}.issubset(topns)


def test_strict_abcde_same_date_filtering(tmp_path):
    _repo, _out, summary, _price = run_seed(tmp_path)
    assert summary["strict_abcde_comparable_start_date"] == "2026-06-18"


def test_missing_ticker_price_handling(tmp_path):
    repo, price = seed_repo(tmp_path)
    v197 = repo / "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT"
    write_csv(v197 / "a1_final_broad_20260630_ranking.csv", [{"strategy": "A1_BASELINE_CONTROL", "rank": 1, "ticker": "MISSING", "final_score": 1, "latest_price_date": "2026-06-30"}], ["strategy", "rank", "ticker", "final_score", "latest_price_date"])
    out = repo / "out"
    v243.run(repo, out, price)
    assert "MISSING_START_PRICE" in (out / "recent_0618_strategy_success_by_ticker.csv").read_text(encoding="utf-8")


def test_no_input_mutation(tmp_path):
    repo, price = seed_repo(tmp_path)
    before = price.read_bytes()
    summary = v243.run(repo, repo / "out", price)
    assert price.read_bytes() == before
    assert summary["input_files_mutated"] is False


def test_final_flags_research_only(tmp_path):
    _repo, _out, summary, _price = run_seed(tmp_path)
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False


def test_report_and_csv_outputs_created(tmp_path):
    _repo, out, _summary, _price = run_seed(tmp_path)
    for name in [
        "recent_0618_strategy_success_summary.csv",
        "recent_0618_strategy_success_by_date.csv",
        "recent_0618_strategy_success_by_ticker.csv",
        "recent_0618_strategy_success_maturity_matrix.csv",
        "recent_0618_strategy_vs_a1_audit.csv",
        "recent_0618_strategy_vs_dram_audit.csv",
        "recent_0618_strategy_vs_benchmark_audit.csv",
        "recent_0618_strategy_tail_risk_audit.csv",
        "recent_0618_strategy_bucket_monotonicity.csv",
        "recent_0618_strategy_overlap_turnover.csv",
        "v21_243_summary.json",
        "V21.243_recent_0618_strategy_success_report.txt",
    ]:
        assert (out / name).exists()
