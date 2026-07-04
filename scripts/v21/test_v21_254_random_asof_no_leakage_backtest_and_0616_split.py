from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

P = Path(__file__).with_name("v21_254_random_asof_no_leakage_backtest_and_0616_split.py")
S = importlib.util.spec_from_file_location("m254", P)
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


def wc(path: Path, data: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, lineterminator="\n")
        w.writeheader()
        w.writerows(data)


def seed(repo: Path) -> Path:
    fields = ["ranking_date","strategy","ticker","rank","candidate_source_strategy","source_mode","pit_status","forward_window","target_price_date","forward_return","maturity_status","top_n"]
    data = []
    for d in ["2026-06-10", "2026-06-18", "2026-06-30"]:
        for s, ret in [("A1", 0.01), ("E_R1", 0.012), ("E_R2_CONSERVATIVE_DEFENSIVE_RETURN", 0.014), ("NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL", 0.016), ("DRAM", -0.01), ("QQQ", 0.005), ("SMH", 0.006), ("SOXX", 0.004)]:
            for w in ["1D", "2D", "3D", "5D"]:
                data.append({"ranking_date": d, "strategy": s, "ticker": "AAA", "rank": "1", "candidate_source_strategy": s, "source_mode": "LIVE_SNAPSHOT" if d == "2026-06-30" else "RETROSPECTIVE_PIT_LITE_REPLAY", "pit_status": "PIT_LITE", "forward_window": w, "target_price_date": "2026-07-02", "forward_return": str(ret), "maturity_status": "MATURED", "top_n": "20"})
    wc(repo / m.V250_REL / "e_r2_shadow_forward_tracking_ledger.csv", data, fields)
    wc(repo / m.V253_REL / "e_r3_weight_candidate_master.csv", [{"candidate": c, "factor_family": "Risk", "weight": "1", "weights_sum": "1"} for c in m.E_R3], ["candidate", "factor_family", "weight", "weights_sum"])
    return repo / m.V250_REL / "e_r2_shadow_forward_tracking_ledger.csv"


def test_random_asof_reproducible_split_labels_and_outputs(tmp_path):
    repo = tmp_path / "repo"
    prior = seed(repo)
    before = prior.read_bytes()
    s1 = m.run(repo, seed_count=2, trials_per_seed=3)
    first = (repo / m.OUT_REL / "random_asof_trial_master.csv").read_text(encoding="utf-8")
    s2 = m.run(repo, seed_count=2, trials_per_seed=3)
    second = (repo / m.OUT_REL / "random_asof_trial_master.csv").read_text(encoding="utf-8")
    out = repo / m.OUT_REL
    assert first == second
    assert prior.read_bytes() == before
    assert s1["pre_0616_trial_count"] > 0 and s1["post_0616_to_now_trial_count"] > 0
    assert s2["broker_action_allowed"] is False and s2["official_adoption_allowed"] is False
    trial_text = first
    assert "PRE_0616_RANDOM_ASOF" in trial_text and "POST_0616_TO_NOW_RANDOM_ASOF" in trial_text
    assert all(c in trial_text for c in m.E_R3)
    assert "POST_HOC_CANDIDATE_STRESS" in trial_text
    assert "E_R2_CONSERVATIVE_DEFENSIVE_RETURN" in (out / "e_r3_vs_e_r2_random_asof_audit.csv").read_text(encoding="utf-8")
    assert "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL" in (out / "e_r3_vs_new_factor_lite_random_asof_audit.csv").read_text(encoding="utf-8")
    assert (out / "leakage_rejection_audit.csv").exists()
    assert (out / "no_future_function_compliance_audit.csv").exists()
    for name in ["pre_0616_strategy_backtest_summary.csv","post_0616_to_now_strategy_backtest_summary.csv","random_start_to_now_strategy_backtest_summary.csv","e_r3_tail_risk_random_asof_audit.csv","e_r3_turnover_random_asof_audit.csv","source_mode_and_pit_lite_audit.csv","random_seed_reproducibility_audit.csv","strategy_period_decision_matrix.csv","v21_254_summary.json","V21.254_random_asof_no_leakage_backtest_0616_split_report.txt"]:
        assert (out / name).exists()


def test_leakage_rejection_detects_future_feature():
    clean, rejected = m.reject_leakage([{"ranking_date": "2026-06-18", "feature_effective_date": "2026-06-19", "price_date_used_for_ranking": "2026-06-18", "target_price_date": "2026-06-22"}])
    assert not clean and rejected[0]["leakage_reason"] == "feature_effective_date_after_asof"


def test_missing_v253_blocks(tmp_path):
    summary = m.run(tmp_path / "repo", seed_count=1, trials_per_seed=1)
    assert summary["error_count"] == 1
