from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
from pathlib import Path

import pandas as pd

P = Path(__file__).with_name("v21_247_technical_subfactor_effectiveness_pit_lite_audit.py")
S = importlib.util.spec_from_file_location("m247", P)
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, rows[0].keys(), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def rows(path: Path):
    return list(csv.DictReader(path.open(encoding="utf-8")))


def seed_panel(tmp_path: Path, names_per_date: int = 25):
    repo = tmp_path / "repo"
    inp = repo / m.DEFAULT_INPUT_REL
    data = []
    indicators = ["MOMENTUM_20", "MOMENTUM_60", "VOLATILITY_20"]
    for d_i, d in enumerate(["2026-01-02", "2026-01-03", "2026-06-17", "2026-06-18"]):
        for i in range(names_per_date):
            ticker = f"T{i:03d}"
            for ind in indicators:
                val = i if ind != "VOLATILITY_20" else (names_per_date - i)
                ret = i / 1000
                data.append({"asof_date": d, "ticker": ticker, "technical_subfactor_name": ind, "technical_group": "MOMENTUM" if "MOMENTUM" in ind else "VOLATILITY", "raw_value": val, "forward_return_1d": ret, "forward_return_5d": ret * 2, "forward_return_10d": ret * 3, "forward_return_20d": ret * 4, "maturity_1d": True, "maturity_5d": True, "maturity_10d": True, "maturity_20d": True})
    write_csv(inp / "technical_forward_join_panel.csv", data)
    (inp / "v21_246_summary.json").write_text(json.dumps({"technical_indicator_count": 3}), encoding="utf-8")
    return repo, inp


def test_required_input_discovery_and_outputs(tmp_path):
    repo, _ = seed_panel(tmp_path)
    s = m.run(repo)
    out = repo / m.OUT_REL
    assert s["tested_indicator_count"] == 3
    for name in ["technical_subfactor_effectiveness_master.csv", "technical_subfactor_effectiveness_by_regime.csv", "technical_subfactor_bucket_returns.csv", "technical_subfactor_ic_timeseries.csv", "technical_subfactor_redundancy_audit.csv", "technical_subfactor_candidate_for_v21_248.csv", "v21_247_summary.json", "V21.247_technical_subfactor_effectiveness_report.txt"]:
        assert (out / name).exists()


def test_defensive_column_normalization():
    df = pd.DataFrame({"symbol": ["A"], "date": ["2026-01-01"], "indicator_name": ["RSI"], "indicator_value": [1], "return_1d": [0.1], "return_5d": [0.2], "return_10d": [0.3], "return_20d": [0.4]})
    out = m.normalize_columns(df)
    ok, missing = m.required_columns_present(out)
    assert ok, missing


def test_ic_and_rank_ic_calculation(tmp_path):
    repo, _ = seed_panel(tmp_path)
    m.run(repo)
    master = rows(repo / m.OUT_REL / "technical_subfactor_effectiveness_master.csv")
    mom = next(r for r in master if r["technical_indicator"] == "MOMENTUM_20" and r["forward_horizon"] == "1D")
    assert float(mom["mean_ic"]) > 0.99
    assert float(mom["mean_rank_ic"]) > 0.99


def test_bucket_return_calculation(tmp_path):
    repo, _ = seed_panel(tmp_path)
    m.run(repo)
    buckets = rows(repo / m.OUT_REL / "technical_subfactor_bucket_returns.csv")
    assert buckets
    top = [r for r in buckets if r["technical_indicator"] == "MOMENTUM_20" and r["bucket"] == "5"]
    bottom = [r for r in buckets if r["technical_indicator"] == "MOMENTUM_20" and r["bucket"] == "1"]
    assert sum(float(r["bucket_forward_return"]) for r in top) / len(top) > sum(float(r["bucket_forward_return"]) for r in bottom) / len(bottom)


def test_too_few_names_bucket_skip_behavior(tmp_path):
    repo, _ = seed_panel(tmp_path, names_per_date=8)
    m.run(repo)
    master = rows(repo / m.OUT_REL / "technical_subfactor_effectiveness_master.csv")
    assert any(int(r["bucket_skipped_date_count"]) > 0 for r in master)


def test_regime_split_output_generation(tmp_path):
    repo, _ = seed_panel(tmp_path)
    m.run(repo)
    regimes = {r["regime"] for r in rows(repo / m.OUT_REL / "technical_subfactor_effectiveness_by_regime.csv")}
    assert {"FULL_SAMPLE", "PRE_20260616", "POST_20260616_TO_NOW", "HIGH_VOL", "LOW_VOL", "MOMENTUM_UP", "MOMENTUM_DOWN"} <= regimes


def test_redundancy_threshold_labeling(tmp_path):
    repo, _ = seed_panel(tmp_path)
    m.run(repo)
    red = rows(repo / m.OUT_REL / "technical_subfactor_redundancy_audit.csv")
    pair = next(r for r in red if {r["indicator_a"], r["indicator_b"]} == {"MOMENTUM_20", "MOMENTUM_60"})
    assert pair["redundancy_label"] == "HIGH_REDUNDANCY"


def test_candidate_file_research_only(tmp_path):
    repo, _ = seed_panel(tmp_path)
    m.run(repo)
    cand = rows(repo / m.OUT_REL / "technical_subfactor_candidate_for_v21_248.csv")
    assert cand and {r["promotion_allowed"] for r in cand} == {"False"}


def test_summary_json_contains_gate_fields(tmp_path):
    repo, _ = seed_panel(tmp_path)
    m.run(repo)
    s = json.loads((repo / m.OUT_REL / "v21_247_summary.json").read_text(encoding="utf-8"))
    for k in ["final_status", "final_decision", "official_adoption_allowed", "broker_action_allowed", "factor_promotion_allowed", "weight_update_allowed", "ranking_mutation_allowed"]:
        assert k in s
    assert s["official_adoption_allowed"] is False


def test_failure_path_nonzero_only_for_fail(tmp_path):
    repo = tmp_path / "repo"
    proc = subprocess.run([str(Path.cwd() / ".venv/Scripts/python.exe"), str(P), "--repo-root", str(repo)], cwd=Path.cwd(), text=True)
    assert proc.returncode == 1
