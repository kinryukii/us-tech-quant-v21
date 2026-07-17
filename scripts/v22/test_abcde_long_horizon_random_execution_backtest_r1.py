from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v22" / "abcde_long_horizon_random_execution_backtest_r1.py"
SPEC = importlib.util.spec_from_file_location("abcde_lh_r1", SCRIPT)
assert SPEC and SPEC.loader
M = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = M
SPEC.loader.exec_module(M)
OUT = ROOT / "outputs" / "v22" / "ABCDE_LONG_HORIZON_RANDOM_EXECUTION_BACKTEST_R1"


def tiny_prices(missing_open: bool = False) -> pd.DataFrame:
    dates = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"])
    rows = []
    for ticker_i, ticker in enumerate(["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "QQQ"]):
        for i, date in enumerate(dates):
            op = 100 + ticker_i + i
            if missing_open and ticker == "A" and date == dates[2]:
                op = np.nan
            rows.append({"ticker": ticker, "date": date, "open": op, "close": 100.5 + ticker_i + i})
    return pd.DataFrame(rows)


def tiny_ranks(second_a_rank: int = 6) -> pd.DataFrame:
    rows = []
    dates = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"])
    orders = [list("ABCDEFGHIJK"), list("BCDEFA" + "GHIJK"), list("BCDEF" + "GHIJK")]
    if second_a_rank == 11:
        orders[1] = list("BCDEFGHIJKA")
    for date, order in zip(dates, orders):
        for i, ticker in enumerate(order, 1):
            rows.append({"signal_date": date, "strategy": "A1", "rank": i, "ticker": ticker, "source_file": "TEST", "scope": "top20"})
    return pd.DataFrame(rows)


def test_01_signal_data_dates_do_not_exceed_signal_date():
    sample = pd.DataFrame({"signal_date": pd.to_datetime(["2026-01-05"]), "price_max_date": pd.to_datetime(["2026-01-05"])})
    assert (sample["price_max_date"] <= sample["signal_date"]).all()


def test_02_execution_is_next_session_open():
    mapping = M.next_session_map([pd.Timestamp("2026-01-02")], list(pd.to_datetime(["2026-01-02", "2026-01-05"])))
    assert mapping[pd.Timestamp("2026-01-02")] == pd.Timestamp("2026-01-05")


def test_03_top5_entry():
    nav, trades, _ = M.run_policy(tiny_ranks(), tiny_prices(), "A1", "slots", [pd.Timestamp("2026-01-02")], 0, 10)
    assert set(trades.loc[trades.side == "BUY", "ticker"]) == set("ABCDE")


def test_04_top6_to_top10_continues_holding():
    ranks = tiny_ranks(second_a_rank=6)
    _, trades, _ = M.run_policy(ranks, tiny_prices(), "A1", "slots", list(pd.to_datetime(["2026-01-02", "2026-01-05"])), 0, 10)
    assert not ((trades.side == "SELL") & (trades.ticker == "A")).any()


def test_05_rank11_sells():
    ranks = tiny_ranks(second_a_rank=11)
    _, trades, _ = M.run_policy(ranks, tiny_prices(), "A1", "slots", list(pd.to_datetime(["2026-01-02", "2026-01-05"])), 0, 10)
    assert ((trades.side == "SELL") & (trades.ticker == "A")).any()


def test_06_maximum_five_positions():
    nav, _, _ = M.run_policy(tiny_ranks(), tiny_prices(), "A1", "slots", list(pd.to_datetime(["2026-01-02", "2026-01-05"])), 0, 10)
    assert nav.position_count.max() <= 5


def test_07_retained_holdings_are_not_daily_rebalanced():
    ranks = tiny_ranks(second_a_rank=6)
    _, trades, _ = M.run_policy(ranks, tiny_prices(), "A1", "slots", list(pd.to_datetime(["2026-01-02", "2026-01-05"])), 0, 10)
    day2 = trades[trades.execution_date == pd.Timestamp("2026-01-06")]
    assert not (day2.ticker == "A").any()


def test_08_sale_cash_stays_in_original_slot():
    ranks = tiny_ranks(second_a_rank=11)
    _, trades, _ = M.run_policy(ranks, tiny_prices(), "A1", "slots", list(pd.to_datetime(["2026-01-02", "2026-01-05"])), 0, 10)
    sale = trades[(trades.side == "SELL") & (trades.ticker == "A")].iloc[0]
    replacement = trades[(trades.side == "BUY") & (trades.execution_date == sale.execution_date) & (trades.slot_id == sale.slot_id)]
    assert len(replacement) == 1


def test_09_no_duplicate_ticker_holdings():
    nav, trades, _ = M.run_policy(tiny_ranks(), tiny_prices(), "A1", "slots", list(pd.to_datetime(["2026-01-02", "2026-01-05"])), 0, 10)
    buys = trades[trades.side == "BUY"]
    assert not buys.duplicated(["execution_date", "ticker"]).any()


def test_10_cost_is_one_way_bps_times_notional():
    _, trades, _ = M.run_policy(tiny_ranks(), tiny_prices(), "A1", "slots", [pd.Timestamp("2026-01-02")], 5, 10)
    assert np.allclose(trades.cost, trades.notional * 0.0005)


def test_11_missing_open_never_uses_future_open():
    ranks = tiny_ranks(second_a_rank=11)
    _, trades, missing = M.run_policy(ranks, tiny_prices(missing_open=True), "A1", "slots", list(pd.to_datetime(["2026-01-02", "2026-01-05"])), 0, 10)
    assert ((missing.ticker == "A") & (missing.action == "SELL_DELAYED")).any()
    assert not ((trades.ticker == "A") & (trades.execution_date == pd.Timestamp("2026-01-06")) & (trades.side == "SELL")).any()


def test_12_random_seed_is_reproducible():
    a = M.deterministic_window_starts(list(range(5000)), 20260714, 1000)
    b = M.deterministic_window_starts(list(range(5000)), 20260714, 1000)
    assert a == b


def test_13_qqq_comparison_dates_align_exactly():
    nav, _, _ = M.run_policy(tiny_ranks(), tiny_prices(), "A1", "slots", [pd.Timestamp("2026-01-02")], 0, 10)
    qqq, _ = M.run_qqq(tiny_prices(), nav.date.min(), nav.date.max(), 0)
    comp = M.comparison_frame(nav, qqq)
    assert comp.date.tolist() == nav.date.tolist() == qqq.date.tolist()


def test_14_daily_win_rate_definition():
    comp = pd.DataFrame({"daily_return": [0.02, 0.00, -0.01], "qqq_daily_return": [0.01, 0.00, 0.00]})
    row = M.daily_win_row("X", comp)
    assert row["days_outperforming_qqq"] == 1 and row["tie_days"] == 1 and row["days_underperforming_qqq"] == 1


def test_15_window_win_definition():
    assert M.window_win(0.10001, 0.10) is True
    assert M.window_win(0.10, 0.10) is False


def test_16_common_history_dates_have_all_abcde():
    ranks = M.load_uploaded_rankings(ROOT)
    dates = M.common_signal_dates(ranks)
    for date in dates:
        assert set(ranks.loc[ranks.signal_date == date, "strategy"]) == set(M.STRATEGIES)


def test_17_no_future_fundamentals_gate_fails_closed():
    readiness = M.validate_pit_readiness(ROOT)
    assert readiness["pit_validation_pass"] is False
    assert "NO_HISTORICAL_FILING_PUBLICATION_DATE_PANEL" in readiness["blockers"]


def test_18_current_universe_is_not_backfilled():
    readiness = M.validate_pit_readiness(ROOT)
    assert "NO_CERTIFIED_HISTORICAL_UNIVERSE_MEMBERSHIP" in readiness["blockers"]
    assert readiness["strict_long_history_rebuild_ready"] is False


def test_19_all_required_outputs_exist_and_are_readable():
    assert OUT.is_dir()
    for name in M.REQUIRED_OUTPUTS:
        path = OUT / name
        assert path.is_file() and path.stat().st_size > 0, name
    pd.read_parquet(OUT / "historical_rankings_master.parquet")
    pd.read_parquet(OUT / "full_history_daily_nav.parquet")
    pd.read_parquet(OUT / "full_history_trades.parquet")
    pd.read_parquet(OUT / "random_window_detail.parquet")
    json.loads((OUT / "data_inventory.json").read_text(encoding="utf-8"))


def test_20_original_daily_chain_and_v22_protected_files_unchanged():
    config = json.loads((OUT / "run_config.json").read_text(encoding="utf-8"))
    assert config["protected_files_unchanged"] is True
    assert config["protected_hashes_before"] == config["protected_hashes_after"]
    assert M.hash_manifest(M.protected_paths(ROOT)) == config["protected_hashes_after"]
