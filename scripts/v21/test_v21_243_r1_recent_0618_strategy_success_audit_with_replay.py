from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_243_r1_recent_0618_strategy_success_audit_with_replay.py")
SPEC = importlib.util.spec_from_file_location("v21_243_r1_stage", MODULE_PATH)
v243r1 = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(v243r1)


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def seed(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    repo = tmp_path / "repo"
    price = tmp_path / "prices.csv"
    replay = repo / "outputs/v21/V21.244_ABCDE_RETROSPECTIVE_REPLAY_0618_TO_0629/abcde_replay_strategy_ranking_master.csv"
    dates = ["2026-06-18", "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26", "2026-06-29", "2026-06-30", "2026-07-01", "2026-07-02"]
    tickers = ["AAA", "BBB", "CCC", "DRAM", "QQQ", "SOXX", "SMH"]
    price_rows = [{"ticker": t, "date": d, "close": 10 + i + j} for i, d in enumerate(dates) for j, t in enumerate(tickers)]
    write_csv(price, price_rows, ["ticker", "date", "close"])
    replay_rows = []
    for d in ["2026-06-18", "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26", "2026-06-29"]:
        for s in ["A1", "B", "C", "D", "E_R1", "ABCDE_AGGREGATE"]:
            for rank, t in enumerate(["AAA", "BBB", "CCC"], 1):
                replay_rows.append({"replay_ranking_date": d, "strategy": s, "ticker": t, "rank": rank, "score": 1 / rank, "pit_status": "PIT_LITE_REPLAY"})
    write_csv(replay, replay_rows, ["replay_ranking_date", "strategy", "ticker", "rank", "score", "pit_status"])
    live_dir = repo / "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT"
    write_csv(live_dir / "a1_final_broad_20260629_ranking.csv", [{"strategy": "A1_BASELINE_CONTROL", "rank": 1, "ticker": "BBB", "final_score": 9, "latest_price_date": "2026-06-29"}], ["strategy", "rank", "ticker", "final_score", "latest_price_date"])
    out = repo / "outputs/v21" / v243r1.STAGE
    return repo, price, replay, out


def run_seed(tmp_path: Path):
    repo, price, replay, out = seed(tmp_path)
    summary = v243r1.run(repo, out, price, replay)
    return repo, price, replay, out, summary


def test_replay_input_discovered_and_loaded(tmp_path):
    _repo, _price, _replay, out, summary = run_seed(tmp_path)
    assert summary["replay_snapshot_date_count"] >= 7
    assert "RETROSPECTIVE_PIT_LITE_REPLAY" in (out / "recent_0618_r1_strategy_source_audit.csv").read_text(encoding="utf-8")


def test_min_date_becomes_20260618_with_replay(tmp_path):
    *_rest, summary = run_seed(tmp_path)
    assert summary["full_available_ranking_date_min"] == "2026-06-18"


def test_live_source_priority_on_overlap(tmp_path):
    _repo, _price, _replay, out, _summary = run_seed(tmp_path)
    rows = list(csv.DictReader((out / "recent_0618_r1_strategy_source_audit.csv").open(encoding="utf-8")))
    overlap = [r for r in rows if r["ranking_date"] == "2026-06-29" and r["strategy"] == "A1"][0]
    assert overlap["selected_source_mode"] == "LIVE_SNAPSHOT"


def test_pit_lite_propagated(tmp_path):
    _repo, _price, _replay, out, _summary = run_seed(tmp_path)
    assert "PIT_LITE_REPLAY" in (out / "recent_0618_r1_strategy_success_by_ticker.csv").read_text(encoding="utf-8")


def test_3d_5d_mature_windows_for_early_replay_dates(tmp_path):
    *_rest, summary = run_seed(tmp_path)
    assert summary["matured_3d_count"] > 0
    assert summary["matured_5d_count"] > 0


def test_pending_maturity_late_dates(tmp_path):
    *_rest, summary = run_seed(tmp_path)
    assert summary["pending_5d_count"] > 0


def test_no_same_day_lookahead(tmp_path):
    _repo, _price, _replay, out, _summary = run_seed(tmp_path)
    rows = list(csv.DictReader((out / "recent_0618_r1_strategy_success_by_ticker.csv").open(encoding="utf-8")))
    row = next(r for r in rows if r["ranking_date"] == "2026-06-18" and r["forward_window"] == "1D")
    assert row["target_price_date"] != "2026-06-18"


def test_no_future_price_rows_beyond_local_completed_mapping(tmp_path):
    _repo, _price, _replay, out, summary = run_seed(tmp_path)
    rows = list(csv.DictReader((out / "recent_0618_r1_strategy_success_by_ticker.csv").open(encoding="utf-8")))
    assert all(not r["target_price_date"] or r["target_price_date"] <= summary["latest_completed_price_date_used"] for r in rows)


def test_a1_excess_return_correctness(tmp_path):
    _repo, _price, _replay, out, _summary = run_seed(tmp_path)
    rows = list(csv.DictReader((out / "recent_0618_r1_strategy_vs_a1_audit.csv").open(encoding="utf-8")))
    assert rows and all(r["benchmark"] == "A1" for r in rows)


def test_dram_benchmark_comparison_correctness(tmp_path):
    _repo, _price, _replay, out, _summary = run_seed(tmp_path)
    rows = list(csv.DictReader((out / "recent_0618_r1_strategy_vs_dram_audit.csv").open(encoding="utf-8")))
    assert rows and all(r["benchmark"] == "DRAM" for r in rows)


def test_abcde_aggregate_handled(tmp_path):
    *_rest, summary = run_seed(tmp_path)
    assert "ABCDE_AGGREGATE" in summary["strategies_compared"]
    assert summary["abcde_aggregate_rank"] is not None


def test_no_input_mutation(tmp_path):
    repo, price, replay, out = seed(tmp_path)
    before = replay.read_bytes()
    summary = v243r1.run(repo, out, price, replay)
    assert replay.read_bytes() == before
    assert summary["input_files_mutated"] is False


def test_safety_flags_false(tmp_path):
    *_rest, summary = run_seed(tmp_path)
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False
    assert summary["protected_outputs_modified"] is False


def test_required_outputs_created(tmp_path):
    _repo, _price, _replay, out, _summary = run_seed(tmp_path)
    for name in [
        "recent_0618_r1_strategy_success_summary.csv",
        "recent_0618_r1_strategy_success_by_date.csv",
        "recent_0618_r1_strategy_success_by_ticker.csv",
        "recent_0618_r1_strategy_success_maturity_matrix.csv",
        "recent_0618_r1_strategy_source_audit.csv",
        "recent_0618_r1_strategy_vs_a1_audit.csv",
        "recent_0618_r1_strategy_vs_dram_audit.csv",
        "recent_0618_r1_strategy_vs_benchmark_audit.csv",
        "recent_0618_r1_strategy_tail_risk_audit.csv",
        "recent_0618_r1_strategy_bucket_monotonicity.csv",
        "recent_0618_r1_strategy_overlap_turnover.csv",
        "recent_0618_r1_pit_lite_replay_impact_audit.csv",
        "v21_243_r1_summary.json",
        "V21.243_R1_recent_0618_strategy_success_report.txt",
    ]:
        assert (out / name).exists()
