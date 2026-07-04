from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_244_abcde_retrospective_replay_0618_to_0629.py")
SPEC = importlib.util.spec_from_file_location("v21_244_stage", MODULE_PATH)
v244 = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(v244)


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def seed_prices(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = tmp_path / "repo"
    price = tmp_path / "prices.csv"
    dates = ["2026-05-15", "2026-05-18", "2026-05-19", "2026-05-20", "2026-05-21", "2026-05-22", "2026-05-26", "2026-05-27", "2026-05-28", "2026-05-29", "2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05", "2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12", "2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18", "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26", "2026-06-29", "2026-06-30"]
    rows = []
    for i, d in enumerate(dates):
        for j, ticker in enumerate(["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]):
            rows.append({"ticker": ticker, "date": d, "close": 10 + i + j, "volume": 1000 + i + j})
    write_csv(price, rows, ["ticker", "date", "close", "volume"])
    out = repo / "outputs" / "v21" / v244.STAGE
    return repo, price, out


def run_seed(tmp_path: Path):
    repo, price, out = seed_prices(tmp_path)
    summary = v244.run(repo, out, price)
    return repo, price, out, summary


def test_replay_date_range_enforcement(tmp_path):
    _repo, _price, _out, summary = run_seed(tmp_path)
    assert summary["replay_start_date"] == "2026-06-18"
    assert summary["replay_end_date"] == "2026-06-29"


def test_us_non_trading_day_exclusion(tmp_path):
    _repo, _price, _out, summary = run_seed(tmp_path)
    assert "2026-06-19" not in summary["replay_trading_dates"]
    assert "2026-06-20" not in summary["replay_trading_dates"]


def test_strategy_generation_for_a1_b_c_d_e(tmp_path):
    _repo, _price, _out, summary = run_seed(tmp_path)
    for strategy in ["A1", "B", "C", "D", "E_R1"]:
        assert strategy in summary["strategies_replayed"]


def test_no_future_price_rows_used(tmp_path):
    _repo, _price, out, _summary = run_seed(tmp_path)
    text = (out / "abcde_replay_strategy_ranking_master.csv").read_text(encoding="utf-8")
    assert "2026-06-30" not in text


def test_no_forward_outcome_columns_used(tmp_path):
    _repo, _price, out, _summary = run_seed(tmp_path)
    header = (out / "abcde_replay_strategy_ranking_master.csv").read_text(encoding="utf-8").splitlines()[0]
    assert "forward_return" not in header


def test_pit_lite_fallback_audited(tmp_path):
    _repo, _price, out, summary = run_seed(tmp_path)
    assert summary["pit_lite_field_count"] > 0
    assert "PIT_LITE_REPLAY" in (out / "abcde_replay_pit_lite_audit.csv").read_text(encoding="utf-8")


def test_missing_strategy_date_combinations_audited(tmp_path):
    _repo, _price, out, _summary = run_seed(tmp_path)
    assert (out / "abcde_replay_missing_strategy_date_audit.csv").exists()


def test_raw_replay_rows_preserved(tmp_path):
    _repo, _price, out, summary = run_seed(tmp_path)
    rows = list(csv.DictReader((out / "abcde_replay_strategy_ranking_master.csv").open(encoding="utf-8")))
    assert len(rows) == summary["replay_rows_created"]


def test_original_v21_233_and_v21_243_not_mutated(tmp_path):
    repo, price, out = seed_prices(tmp_path)
    old233 = repo / "outputs/v21/V21.233_MOOMOO_ONLY_ABCDE_RERUN/abcde_strategy_ranking_master.csv"
    old243 = repo / "outputs/v21/V21.243_RECENT_0618_STRATEGY_SUCCESS_AUDIT/v21_243_summary.json"
    old233.parent.mkdir(parents=True, exist_ok=True)
    old243.parent.mkdir(parents=True, exist_ok=True)
    old233.write_text("keep", encoding="utf-8")
    old243.write_text("keep", encoding="utf-8")
    v244.run(repo, out, price)
    assert old233.read_text(encoding="utf-8") == "keep"
    assert old243.read_text(encoding="utf-8") == "keep"


def test_research_only_flags(tmp_path):
    _repo, _price, _out, summary = run_seed(tmp_path)
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False


def test_required_outputs_created(tmp_path):
    _repo, _price, out, _summary = run_seed(tmp_path)
    for name in [
        "abcde_replay_strategy_ranking_master.csv",
        "abcde_replay_top20_summary.csv",
        "abcde_replay_top50_summary.csv",
        "abcde_replay_top100_summary.csv",
        "abcde_replay_input_source_audit.csv",
        "abcde_replay_pit_lite_audit.csv",
        "abcde_replay_missing_strategy_date_audit.csv",
        "abcde_replay_coverage_audit.csv",
        "abcde_replay_overlap_audit.csv",
        "v21_244_summary.json",
        "V21.244_abcde_retrospective_replay_report.txt",
    ]:
        assert (out / name).exists()


def test_summary_json_fields_complete(tmp_path):
    _repo, _price, out, _summary = run_seed(tmp_path)
    payload = json.loads((out / "v21_244_summary.json").read_text(encoding="utf-8"))
    for key in ["final_status", "final_decision", "replay_trading_dates", "strategy_date_count", "replay_rows_created", "strict_pit_possible", "input_files_mutated"]:
        assert key in payload
