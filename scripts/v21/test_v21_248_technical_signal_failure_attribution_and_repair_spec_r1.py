from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path

P = Path(__file__).with_name("v21_248_technical_signal_failure_attribution_and_repair_spec_r1.py")
S = importlib.util.spec_from_file_location("m248", P)
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or (list(rows[0].keys()) if rows else ["x"])
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def rows(path: Path):
    return list(csv.DictReader(path.open(encoding="utf-8")))


def seed(tmp_path: Path, empty_master: bool = False, no_regime: bool = False):
    repo = tmp_path / "repo"
    r246 = repo / m.V246_REL
    r247 = repo / m.V247_REL
    write_csv(r246 / "v21_246_input_cache_gate.csv", [{"gate_status": "PARTIAL_PASS_READY_WITH_EXCLUSIONS"}])
    write_csv(r246 / "technical_panel_quality_audit.csv", [{"technical_subfactor_name": "RSI_14"}])
    master = []
    specs = {
        "RSI_14": [0.03, 0.02, -0.01, -0.02],
        "MACD_DIF_12_26": [-0.04, -0.03, -0.02, -0.01],
        "BREAKOUT_20": [0.05, 0.01, 0.0, -0.01],
        "MOMENTUM_20": [0.0, 0.0, 0.0, 0.0],
    }
    for ind, vals in specs.items():
        for h, v in zip(["1D", "5D", "10D", "20D"], vals):
            master.append({"technical_indicator": ind, "technical_group": ind.split("_")[0], "forward_horizon": h, "mean_ic": v, "mean_rank_ic": v, "positive_rank_ic_ratio": 0.7 if v > 0 else 0.3 if v < 0 else 0.5, "top_minus_bottom_return": v / 10, "monotonicity_score": 0.4 if ind == "MOMENTUM_20" else 0.7, "observation_count": 2000, "coverage_ratio": 0.9})
    write_csv(r247 / "technical_subfactor_effectiveness_master.csv", [] if empty_master else master)
    buckets = []
    for r in master:
        for d in ["2026-01-01", "2026-01-02"]:
            vals = [0.01, -0.01, 0.02, -0.02, 0.03] if r["technical_indicator"] == "MOMENTUM_20" else [0, 0.01, 0.02, 0.03, 0.04]
            for b, val in enumerate(vals, 1):
                buckets.append({"technical_indicator": r["technical_indicator"], "technical_group": r["technical_group"], "forward_horizon": r["forward_horizon"], "asof_date": d, "bucket": b, "bucket_forward_return": val, "bucket_count": 20})
    write_csv(r247 / "technical_subfactor_bucket_returns.csv", buckets)
    write_csv(r247 / "technical_subfactor_redundancy_audit.csv", [
        {"indicator_a": "BREAKOUT_20", "indicator_b": "MOMENTUM_20", "spearman_corr": 0.9, "redundancy_label": "HIGH_REDUNDANCY"},
        {"indicator_a": "RSI_14", "indicator_b": "MACD_DIF_12_26", "spearman_corr": 0.2, "redundancy_label": "LOW_REDUNDANCY"},
    ])
    if not no_regime:
        reg = [dict(r, regime="HIGH_VOL") for r in master]
        write_csv(r247 / "technical_subfactor_effectiveness_by_regime.csv", reg)
    write_csv(r247 / "technical_subfactor_candidate_for_v21_248.csv", [{"technical_indicator": "RSI_14", "promotion_allowed": False}])
    protected = repo / "protected.txt"
    protected.write_text("do not touch", encoding="utf-8")
    return repo, protected, hashlib.sha256(protected.read_bytes()).hexdigest()


def test_missing_v21_246_input(tmp_path):
    repo = tmp_path / "repo"
    (repo / m.V247_REL).mkdir(parents=True)
    write_csv(repo / m.V247_REL / "technical_subfactor_effectiveness_master.csv", [{"technical_indicator": "X"}])
    s = m.run(repo)
    assert s["final_status"] == "FAIL_V21_248_TECHNICAL_ATTRIBUTION_INPUT_MISSING"


def test_missing_v21_247_input(tmp_path):
    repo = tmp_path / "repo"
    write_csv(repo / m.V246_REL / "v21_246_input_cache_gate.csv", [{"x": 1}])
    s = m.run(repo)
    assert s["final_status"] == "FAIL_V21_248_TECHNICAL_ATTRIBUTION_INPUT_MISSING"


def test_empty_technical_effectiveness_rows(tmp_path):
    repo, _, _ = seed(tmp_path, empty_master=True)
    s = m.run(repo)
    assert s["final_status"] == "FAIL_V21_248_TECHNICAL_ATTRIBUTION_INPUT_MISSING"


def test_mixed_horizon_sign_labels(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    data = rows(repo / m.OUT_REL / "technical_direction_attribution.csv")
    assert any(r["technical_indicator"] == "RSI_14" and r["direction_stability_label"] == "SIGN_FLIP_BY_HORIZON" for r in data)


def test_direction_inversion_detection(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    data = rows(repo / m.OUT_REL / "technical_direction_attribution.csv")
    assert any(r["technical_indicator"] == "MACD_DIF_12_26" and r["direction_inversion_candidate"] == "True" for r in data)


def test_non_monotonic_bucket_detection(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    data = rows(repo / m.OUT_REL / "technical_bucket_monotonicity_audit.csv")
    assert any(r["technical_indicator"] == "MOMENTUM_20" and r["bucket_failure_label"] == "NON_MONOTONIC_BUCKETS" for r in data)


def test_context_missing_graceful_degradation(tmp_path):
    repo, _, _ = seed(tmp_path, no_regime=True)
    s = m.run(repo)
    assert s["missing_context_field_count"] >= 1


def test_redundancy_label_assignment(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    data = rows(repo / m.OUT_REL / "technical_redundancy_attribution.csv")
    assert any(r["redundancy_attribution"] == "REDUNDANT_WITH_MOMENTUM" for r in data)


def test_repair_candidate_generation_and_gates(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    specs = rows(repo / m.OUT_REL / "technical_repair_candidate_spec.csv")
    assert specs
    assert {r["official_adoption_allowed"] for r in specs} == {"False"}
    assert s["factor_promotion_allowed"] is False


def test_summary_json_schema_and_gate_enforcement(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    payload = json.loads((repo / m.OUT_REL / "v21_248_summary.json").read_text(encoding="utf-8"))
    for k in ["final_status", "final_decision", "technical_indicator_count", "repair_candidate_count", "research_only", "official_adoption_allowed", "broker_action_allowed", "market_data_fetch_allowed"]:
        assert k in payload
    assert payload["official_adoption_allowed"] is False
    assert payload["market_data_fetch_allowed"] is False


def test_no_protected_output_mutation(tmp_path):
    repo, protected, before = seed(tmp_path)
    m.run(repo)
    after = hashlib.sha256(protected.read_bytes()).hexdigest()
    assert before == after
