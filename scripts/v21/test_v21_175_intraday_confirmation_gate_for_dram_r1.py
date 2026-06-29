import json
from pathlib import Path

import pandas as pd

from scripts.v21 import v21_175_intraday_confirmation_gate_for_dram_r1 as m


class EmptyYF:
    @staticmethod
    def download(*_args, **_kwargs):
        return pd.DataFrame()


def anchor_file(path: Path):
    pd.DataFrame(
        [
            {
                "latest_date": "2026-06-26",
                "ticker": "DRAM",
                "latest_close": 70,
                "planned_entry_base": 68,
                "no_chase_above": 74,
                "stop_loss_base": 62,
                "take_profit_1_base": 78,
                "take_profit_2_base": 84,
            }
        ]
    ).to_csv(path, index=False)


def bars(n=40, start=50, interval="1h"):
    dates = pd.date_range("2026-06-26 09:30", periods=n, freq="h")
    close = [start + i * 0.25 for i in range(n)]
    return pd.DataFrame(
        {
            "Datetime": dates,
            "Open": close,
            "High": [x + 0.4 for x in close],
            "Low": [x - 0.4 for x in close],
            "Close": close,
            "Volume": [1000 + i * 10 for i in range(n)],
        }
    )


def test_r1c_anchor_missing_produces_blocked_status(tmp_path):
    out = tmp_path / "out"
    m.main(out, tmp_path / "missing.csv", EmptyYF)
    summary = json.loads((out / "V21.175_summary.json").read_text(encoding="utf-8"))
    assert summary["final_status"] == "BLOCKED_V21_175_DAILY_ANCHOR_MISSING"
    assert summary["decision"] == "DRAM_DAILY_ANCHOR_REQUIRED"


def test_intraday_missing_produces_warn_status_not_crash(tmp_path):
    a = tmp_path / "anchor.csv"
    anchor_file(a)
    out = tmp_path / "out"
    m.main(out, a, EmptyYF)
    summary = json.loads((out / "V21.175_summary.json").read_text(encoding="utf-8"))
    assert summary["final_status"] == "WARN_V21_175_INTRADAY_DATA_MISSING"
    assert "WARN_INTRADAY_DATA_MISSING" in summary["warnings"]


def test_rsi_calculation():
    s = pd.Series([1, 2, 3, 4, 5, 4, 5, 6, 7, 8, 9, 8, 9, 10, 11, 12], dtype=float)
    r = m.rsi(s)
    assert pd.notna(r.iloc[-1])
    assert 0 <= r.iloc[-1] <= 100


def test_kdj_golden_cross_detection():
    df = pd.DataFrame({"kdj_k": [20, 30], "kdj_d": [25, 28]})
    assert m.kdj_golden_cross(df) is True


def test_bollinger_middle_band_reclaim_detection():
    df = pd.DataFrame({"close": [9, 11], "bb_middle": [10, 10]})
    assert m.bollinger_middle_reclaim(df) is True


def test_no_chase_rule_when_latest_price_gt_no_chase():
    assert m.final_trade_decision("PASS", "PASS", "PASS", True, True, True) == "DRAM_NO_CHASE"


def test_1h_pass_15m_pass_1m_missing_results_wait_1m_trigger():
    assert m.final_trade_decision("PASS", "PASS", "UNKNOWN_DATA_MISSING", False, True, True) == "DRAM_WAIT_1M_TRIGGER"


def test_all_three_gates_pass_no_chase_false_entry_allowed():
    assert m.final_trade_decision("PASS", "PASS", "PASS", False, True, True) == "DRAM_INTRADAY_ENTRY_ALLOWED"


def test_hard_policy_flags_remain_locked():
    assert m.POLICY["research_only"] is True
    assert m.POLICY["official_adoption_allowed"] is False
    assert m.POLICY["broker_action_allowed"] is False
    assert m.POLICY["protected_outputs_modified"] is False
    assert m.POLICY["canonical_price_panel_modified"] is False
