from __future__ import annotations

import csv
import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

P = Path(__file__).with_name("v21_254_r1_moomoo_pre0616_historical_random_asof_backtest.py")
S = importlib.util.spec_from_file_location("m254r1", P)
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
    qfq = repo / "cache/canonical_qfq.csv"
    fields = ["ticker","moomoo_symbol","market","date","open","high","low","close","volume","turnover","adjustment","source","source_policy","snapshot_id","fetched_at_utc"]
    start = date(2026, 4, 1)
    tickers = ["AAA", "BBB", "CCC", "DRAM", "QQQ", "SMH", "SOXX"]
    data = []
    for i in range(60):
        d = start + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        for j, t in enumerate(tickers):
            close = 10 + i * (0.1 + j * 0.01)
            data.append({"ticker": t, "moomoo_symbol": f"US.{t}", "market": "US", "date": d.isoformat(), "open": close - 0.1, "high": close + 0.2, "low": close - 0.2, "close": close, "volume": 1000 + i, "turnover": 0, "adjustment": "qfq", "source": "MOOMOO_OPEND", "source_policy": "MOOMOO_ONLY", "snapshot_id": "test", "fetched_at_utc": "2026-07-03T00:00:00Z"})
    wc(qfq, data, fields)
    wj(repo / m.V253_REL / "v21_253_summary.json", {"final_status": "WARN"})
    wc(repo / m.V253_REL / "e_r3_weight_candidate_master.csv", [{"candidate": c, "factor_family": "Risk", "weight": "1", "weights_sum": "1"} for c in m.E_R3], ["candidate","factor_family","weight","weights_sum"])
    wc(repo / m.V254_REL / "post_0616_to_now_strategy_backtest_summary.csv", [{"period": "POST", "strategy": "E_R3_QUALITY_RISK_REPAIR_BASE", "topn_scope": "20", "forward_window": "1D", "trial_count": "1", "average_return": "0.02", "p10_return": "0.01", "worst5_return": "0.01"}], ["period","strategy","topn_scope","forward_window","trial_count","average_return","p10_return","worst5_return"])
    return qfq


def test_pre0616_moomoo_backtest_outputs_no_broker_and_labels(tmp_path):
    repo = tmp_path / "repo"
    qfq = seed(repo)
    before = qfq.read_bytes()
    summary = m.run(repo, canonical_qfq_path=qfq, seed_count=2, trials_per_seed=3)
    out = repo / m.OUT_REL
    assert qfq.read_bytes() == before
    assert summary["moomoo_historical_market_data_only"] is True
    assert summary["broker_action_allowed"] is False and summary["official_adoption_allowed"] is False
    assert summary["yahoo_yfinance_used"] is False
    assert summary["pre_0616_trial_count"] > 0
    assert summary["leakage_violation_count"] == 0
    trial_text = (out / "pre0616_random_asof_trial_master.csv").read_text(encoding="utf-8")
    assert "POST_HOC_CANDIDATE_STRESS" in trial_text
    assert "True" in trial_text  # PIT-lite universe flag
    for cand in m.E_R3:
        assert cand in trial_text
    assert "E_R2_CONSERVATIVE_DEFENSIVE_RETURN" in (out / "pre0616_e_r3_vs_e_r2_audit.csv").read_text(encoding="utf-8")
    assert "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL" in (out / "pre0616_e_r3_vs_new_factor_lite_audit.csv").read_text(encoding="utf-8")
    for name in ["moomoo_pre0616_historical_price_master.csv","moomoo_pre0616_historical_price_coverage_audit.csv","moomoo_pre0616_fetch_audit.csv","pre0616_tail_risk_audit.csv","pre0616_turnover_audit.csv","pre_vs_post_0616_strategy_comparison.csv","source_mode_and_post_hoc_stress_audit.csv","leakage_rejection_audit.csv","no_future_function_compliance_audit.csv","random_seed_reproducibility_audit.csv","strategy_period_decision_matrix.csv","v21_254_r1_summary.json","V21.254_R1_moomoo_pre0616_historical_random_asof_backtest_report.txt"]:
        assert (out / name).exists()


def test_seed_reproducibility(tmp_path):
    repo = tmp_path / "repo"
    qfq = seed(repo)
    m.run(repo, canonical_qfq_path=qfq, seed_count=2, trials_per_seed=2)
    first = (repo / m.OUT_REL / "pre0616_random_asof_trial_master.csv").read_text(encoding="utf-8")
    m.run(repo, canonical_qfq_path=qfq, seed_count=2, trials_per_seed=2)
    assert first == (repo / m.OUT_REL / "pre0616_random_asof_trial_master.csv").read_text(encoding="utf-8")


def test_missing_inputs_block(tmp_path):
    summary = m.run(tmp_path / "repo", canonical_qfq_path=tmp_path / "missing.csv", seed_count=1, trials_per_seed=1)
    assert summary["final_status"] == "PRE0616_MOOMOO_FETCH_BLOCKED"
    assert summary["error_count"] == 1
