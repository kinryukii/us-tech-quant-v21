from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

P = Path(__file__).with_name("v21_249_shadow_candidate_selection_and_forward_tracking_gate.py")
S = importlib.util.spec_from_file_location("m249", P)
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


def wc(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def wj(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def seed(repo: Path) -> Path:
    root = repo / m.V247_REL
    fields = ["strategy", "forward_window", "top_n", "average_return", "median_return", "positive_rate", "p10_return", "worst5_return", "matured_date_count", "pit_lite_present"]
    rows = [
        {"strategy": "A1", "forward_window": "1D", "top_n": "20", "average_return": "-0.02", "median_return": "-0.01", "positive_rate": "0.3", "p10_return": "-0.10", "worst5_return": "-0.04", "matured_date_count": "7", "pit_lite_present": "True"},
        {"strategy": "E_R1", "forward_window": "1D", "top_n": "20", "average_return": "0.01", "median_return": "0.006", "positive_rate": "0.7", "p10_return": "-0.03", "worst5_return": "-0.01", "matured_date_count": "7", "pit_lite_present": "True"},
        {"strategy": "DRAM", "forward_window": "1D", "top_n": "20", "average_return": "-0.01", "median_return": "-0.005", "positive_rate": "0.4", "p10_return": "-0.07", "worst5_return": "-0.03", "matured_date_count": "7", "pit_lite_present": "True"},
        {"strategy": "E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "forward_window": "1D", "top_n": "20", "average_return": "0.014", "median_return": "0.009", "positive_rate": "0.8", "p10_return": "-0.02", "worst5_return": "-0.005", "matured_date_count": "7", "pit_lite_present": "True"},
        {"strategy": "A1_LEFT_TAIL_REPAIRED", "forward_window": "1D", "top_n": "20", "average_return": "0.004", "median_return": "0.002", "positive_rate": "0.6", "p10_return": "-0.04", "worst5_return": "-0.015", "matured_date_count": "7", "pit_lite_present": "True"},
    ]
    wc(root / "reweighted_strategy_forward_success_summary.csv", rows, fields)
    wc(root / "reweighted_strategy_candidate_decision_matrix.csv", [
        {"candidate": "E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "decision": "SUPPORTIVE_SHADOW_CANDIDATE", "avg_return": "0.014", "p10_return": "-0.02", "research_only": "True"},
        {"candidate": "A1_LEFT_TAIL_REPAIRED", "decision": "REJECT_REWEIGHT_CANDIDATE", "avg_return": "0.004", "p10_return": "-0.04", "research_only": "True"},
    ], ["candidate", "decision", "avg_return", "p10_return", "research_only"])
    turnover = [
        {"strategy": "A1", "turnover_proxy": "SOURCE_MODE_STABILITY", "live_and_replay_present": "True"},
        {"strategy": "E_R1", "turnover_proxy": "SOURCE_MODE_STABILITY", "live_and_replay_present": "True"},
        {"strategy": "DRAM", "turnover_proxy": "SOURCE_MODE_STABILITY", "live_and_replay_present": "False"},
        {"strategy": "E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "turnover_proxy": "SOURCE_MODE_STABILITY", "live_and_replay_present": "True"},
        {"strategy": "A1_LEFT_TAIL_REPAIRED", "turnover_proxy": "SOURCE_MODE_STABILITY", "live_and_replay_present": "True"},
    ]
    wc(root / "reweighted_strategy_turnover_stability_audit.csv", turnover, ["strategy", "turnover_proxy", "live_and_replay_present"])
    for name in ["reweighted_strategy_vs_e_r1_audit.csv", "reweighted_strategy_vs_a1_audit.csv", "reweighted_strategy_vs_dram_audit.csv", "reweighted_strategy_tail_risk_audit.csv"]:
        wc(root / name, [], ["strategy"])
    wj(root / "v21_247_summary.json", {"final_status": "SUPPORTIVE_SHADOW_CANDIDATE"})
    wj(repo / m.V246_REL / "v21_246_summary.json", {"final_status": "PASS"})
    wj(repo / m.V245_REL / "v21_245_summary.json", {"final_status": "PASS"})
    return root


def test_shadow_candidate_gate_outputs_and_safety(tmp_path):
    repo = tmp_path / "repo"
    prior = seed(repo)
    before = (prior / "reweighted_strategy_candidate_decision_matrix.csv").read_bytes()
    summary = m.run(repo)
    out = repo / m.OUT_REL
    assert (prior / "reweighted_strategy_candidate_decision_matrix.csv").read_bytes() == before
    assert summary["candidate_that_triggered_supportive_shadow_status"] == "E_R2_CONSERVATIVE_DEFENSIVE_RETURN"
    assert summary["beats_e_r1_after_risk_adjustment"] is True
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False
    assert "E_R1" in (out / "shadow_candidate_vs_e_r1_audit.csv").read_text(encoding="utf-8")
    assert "A1_LEFT_TAIL_REPAIRED" in (out / "shadow_candidate_vs_a1_audit.csv").read_text(encoding="utf-8")
    assert "turnover_materially_worse" in (out / "shadow_candidate_turnover_audit.csv").read_text(encoding="utf-8")
    for name in [
        "shadow_candidate_selection_matrix.csv",
        "shadow_candidate_tail_risk_audit.csv",
        "shadow_forward_tracking_gate.csv",
        "v21_249_summary.json",
        "V21.249_shadow_candidate_selection_report.txt",
    ]:
        assert (out / name).exists()


def test_missing_inputs_fail(tmp_path):
    summary = m.run(tmp_path / "repo")
    assert summary["final_status"] == "FAIL_V21_249_REQUIRED_INPUT_MISSING"
    assert summary["error_count"] > 0
