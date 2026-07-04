from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

P = Path(__file__).with_name("v21_250_e_r2_shadow_forward_tracking_ledger.py")
S = importlib.util.spec_from_file_location("m250", P)
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


def wc(path: Path, data: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, lineterminator="\n")
        w.writeheader()
        w.writerows(data)


def wj(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def seed(repo: Path) -> Path:
    v247 = repo / m.V247_REL
    v249 = repo / m.V249_REL
    strategies = ["A1", "E_R1", "E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL", "DRAM", "QQQ", "SMH", "SOXX"]
    ticker_rows = []
    for s in strategies:
        for win in ["1D", "2D", "3D", "5D"]:
            ticker_rows.append({"ranking_date": "2026-06-30", "strategy": s, "ticker": "AAA", "rank": "1", "candidate_source_strategy": s, "source_mode": "LIVE_SNAPSHOT", "pit_status": "LIVE_ORIGINAL", "forward_window": win, "target_price_date": "2026-07-02", "forward_return": "0.01", "maturity_status": "MATURED"})
    wc(v247 / "reweighted_strategy_forward_success_by_ticker.csv", ticker_rows, ["ranking_date", "strategy", "ticker", "rank", "candidate_source_strategy", "source_mode", "pit_status", "forward_window", "target_price_date", "forward_return", "maturity_status"])
    summary_rows = []
    for s in strategies:
        avg = "0.02" if s == "E_R2_CONSERVATIVE_DEFENSIVE_RETURN" else "0.01"
        p10 = "-0.01" if s == "E_R2_CONSERVATIVE_DEFENSIVE_RETURN" else "-0.02"
        summary_rows.append({"strategy": s, "forward_window": "1D", "top_n": "20", "average_return": avg, "median_return": avg, "positive_rate": "1", "p10_return": p10, "worst5_return": p10, "matured_date_count": "1", "pit_lite_present": "False"})
    wc(v247 / "reweighted_strategy_forward_success_summary.csv", summary_rows, ["strategy", "forward_window", "top_n", "average_return", "median_return", "positive_rate", "p10_return", "worst5_return", "matured_date_count", "pit_lite_present"])
    wj(v249 / "v21_249_summary.json", {"recommended_shadow_tracking_candidate": "E_R2_CONSERVATIVE_DEFENSIVE_RETURN"})
    return v247


def test_e_r2_shadow_ledger_outputs_and_safety(tmp_path):
    repo = tmp_path / "repo"
    prior = seed(repo)
    before = (prior / "reweighted_strategy_forward_success_by_ticker.csv").read_bytes()
    summary = m.run(repo)
    out = repo / m.OUT_REL
    assert (prior / "reweighted_strategy_forward_success_by_ticker.csv").read_bytes() == before
    assert summary["final_status"] == "E_R2_SHADOW_TRACKING_STARTED"
    assert summary["shadow_forward_tracking_allowed"] is True
    assert summary["official_adoption_allowed"] is False
    assert summary["broker_action_allowed"] is False
    ledger = (out / "e_r2_shadow_forward_tracking_ledger.csv").read_text(encoding="utf-8")
    assert "E_R2_CONSERVATIVE_DEFENSIVE_RETURN" in ledger
    assert "E_R1" in (out / "e_r2_vs_e_r1_vs_a1_daily_audit.csv").read_text(encoding="utf-8")
    assert "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL" in (out / "e_r2_vs_new_factor_lite_audit.csv").read_text(encoding="utf-8")
    assert "10D" in (out / "e_r2_shadow_maturity_matrix.csv").read_text(encoding="utf-8")
    for name in ["e_r2_shadow_tail_risk_audit.csv", "e_r2_shadow_turnover_audit.csv", "e_r2_shadow_benchmark_audit.csv", "v21_250_summary.json", "V21.250_e_r2_shadow_forward_tracking_report.txt"]:
        assert (out / name).exists()


def test_missing_inputs_block(tmp_path):
    summary = m.run(tmp_path / "repo")
    assert summary["final_status"] == "E_R2_SHADOW_TRACKING_BLOCKED"
    assert summary["error_count"] == 1
