from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

P = Path(__file__).with_name("v21_252_current_regime_factor_effect_coefficient_audit.py")
S = importlib.util.spec_from_file_location("m252", P)
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


def wc(path: Path, data: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, lineterminator="\n")
        w.writeheader()
        w.writerows(data)


def seed(repo: Path) -> Path:
    ledger = repo / m.V250_REL / "e_r2_shadow_forward_tracking_ledger.csv"
    rows = []
    for date in ["2026-06-18", "2026-06-22", "2026-06-23"]:
        for strategy, boost in [("A1", 0.0), ("E_R1", 0.01), ("E_R2_CONSERVATIVE_DEFENSIVE_RETURN", 0.02), ("NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL", 0.025)]:
            for rank in range(1, 11):
                ret = boost + (11 - rank) * 0.002
                rows.append({"ranking_date": date, "strategy": strategy, "ticker": f"T{rank}", "rank": str(rank), "candidate_source_strategy": strategy, "source_mode": "LIVE_SNAPSHOT" if date == "2026-06-23" else "RETROSPECTIVE_PIT_LITE_REPLAY", "pit_status": "LIVE_ORIGINAL", "forward_window": "1D", "target_price_date": "2026-07-02", "forward_return": str(ret), "maturity_status": "MATURED", "top_n": "20"})
    wc(ledger, rows, ["ranking_date", "strategy", "ticker", "rank", "candidate_source_strategy", "source_mode", "pit_status", "forward_window", "target_price_date", "forward_return", "maturity_status", "top_n"])
    wc(repo / m.V246_REL / "factor_weight_candidate_master.csv", [
        {"candidate": "E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "factor_family": "Technical", "weight": "0.28", "weights_sum": "1.0", "research_only": "True", "official_adoption_allowed": "False", "broker_action_allowed": "False"},
        {"candidate": "E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "factor_family": "Risk", "weight": "0.27", "weights_sum": "1.0", "research_only": "True", "official_adoption_allowed": "False", "broker_action_allowed": "False"},
    ], ["candidate", "factor_family", "weight", "weights_sum", "research_only", "official_adoption_allowed", "broker_action_allowed"])
    return ledger


def test_standardization_by_ranking_date():
    weights = {"A1": {"Technical": 1.0, "Risk": 0.1}}
    base = [
        {"ranking_date": "2026-06-18", "ticker": "A", "strategy": "A1", "source_mode": "LIVE_SNAPSHOT", "pit_status": "", "forward_window": "1D", "top_n": "20", "forward_return": "0.01", "rank": "1"},
        {"ranking_date": "2026-06-18", "ticker": "B", "strategy": "A1", "source_mode": "LIVE_SNAPSHOT", "pit_status": "", "forward_window": "1D", "top_n": "20", "forward_return": "0.00", "rank": "10"},
    ]
    z = [r for r in m.standardize_exposures(base, weights) if r["factor_name"] == "Technical"]
    assert round(sum(r["factor_z"] for r in z), 10) == 0


def test_coefficient_known_positive_and_outputs(tmp_path):
    repo = tmp_path / "repo"
    ledger = seed(repo)
    before = ledger.read_bytes()
    summary = m.run(repo)
    out = repo / m.OUT_REL
    assert ledger.read_bytes() == before
    assert summary["error_count"] == 0
    assert summary["broker_action_allowed"] is False and summary["official_adoption_allowed"] is False
    assert summary["protected_outputs_modified"] is False and summary["input_files_mutated"] is False
    master = list(csv.DictReader((out / "factor_effect_coefficient_master.csv").open("r", encoding="utf-8")))
    technical = [r for r in master if r["factor_name"] in {"Technical", "momentum_relative_strength"}]
    assert technical
    assert any(float(r["beta_standardized"]) > 0 for r in technical)
    ic = list(csv.DictReader((out / "factor_ic_and_bucket_spread_audit.csv").open("r", encoding="utf-8")))
    assert any(float(r["rank_ic"]) > 0 for r in ic)
    matrix = list(csv.DictReader((out / "strategy_factor_exposure_effect_matrix.csv").open("r", encoding="utf-8")))
    assert any(r["strategy"] == "E_R2_CONSERVATIVE_DEFENSIVE_RETURN" for r in matrix)
    assert "PIT_LITE" in (out / "factor_source_mode_robustness_audit.csv").read_text(encoding="utf-8")
    for name in [
        "factor_effect_coefficient_by_date.csv",
        "factor_effect_coefficient_by_strategy.csv",
        "factor_effect_coefficient_by_window.csv",
        "factor_multicollinearity_audit.csv",
        "factor_weight_adjustment_recommendation.csv",
        "e_r2_factor_driver_audit.csv",
        "new_factor_lite_factor_driver_audit.csv",
        "a1_left_tail_factor_coefficient_audit.csv",
        "b_c_d_negative_factor_audit.csv",
        "abcde_aggregate_factor_dilution_audit.csv",
        "dram_factor_exposure_audit.csv",
        "v21_252_summary.json",
        "V21.252_current_regime_factor_effect_coefficient_report.txt",
    ]:
        assert (out / name).exists()


def test_missing_ledger_fails(tmp_path):
    summary = m.run(tmp_path / "repo")
    assert summary["final_status"] == "FAIL_FACTOR_COEFFICIENT_AUDIT_BLOCKED"
    assert summary["error_count"] == 1
