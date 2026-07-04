from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import re
from pathlib import Path

P = Path(__file__).with_name("v21_249_technical_repair_spec_pit_retest_r1.py")
S = importlib.util.spec_from_file_location("m249", P)
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


def seed(tmp_path: Path, empty_specs: bool = False):
    repo = tmp_path / "repo"
    r246, r247, r248 = repo / m.V246_REL, repo / m.V247_REL, repo / m.V248_REL
    panel = []
    for d in ["2026-01-01", "2026-01-02", "2026-01-03"]:
        for i in range(30):
            ret = i / 1000
            panel.append({"asof_date": d, "ticker": f"T{i:02d}", "RSI_14": 100 - i, "KDJ_K_9_3_3": i, "KDJ_D_9_3_3": i - 1, "KDJ_J_9_3_3": i, "MACD_DIF_12_26": i, "MACD_DEA_9": i - 1, "BB_PCTB_20": 0.5, "PULLBACK_FROM_20D_HIGH": -i / 100, "BREAKOUT_20": i / 100, "MOMENTUM_20": i / 100, "MOMENTUM_60": i / 90, "VOLATILITY_20": 1 - i / 100, "forward_return_1d": ret, "forward_return_5d": ret, "forward_return_10d": -ret, "forward_return_20d": -ret, "maturity_1d": True, "maturity_5d": True, "maturity_10d": True, "maturity_20d": True})
    write_csv(r246 / "technical_subfactor_panel_wide.csv", panel)
    fwd = [{k: v for k, v in r.items() if k in {"asof_date", "ticker", "forward_return_1d", "forward_return_5d", "forward_return_10d", "forward_return_20d", "maturity_1d", "maturity_5d", "maturity_10d", "maturity_20d"}} for r in panel]
    write_csv(r246 / "forward_return_panel_aligned.csv", fwd)
    write_csv(r247 / "technical_subfactor_effectiveness_master.csv", [{"technical_indicator": "RSI_14"}])
    specs = [{"repair_candidate_label": "RSI_LOW_REVERSAL_CONTEXT_R1"}, {"repair_candidate_label": "KDJ_LOW_GOLDEN_CROSS_R1"}, {"repair_candidate_label": "BREAKOUT_NEXT_DAY_CONFIRM_R1"}, {"repair_candidate_label": "TECHNICAL_COMPOSITE_TIMING_R1"}]
    write_csv(r248 / "technical_repair_candidate_spec.csv", [] if empty_specs else specs)
    protected = repo / "protected.txt"
    protected.write_text("protected", encoding="utf-8")
    return repo, protected, hashlib.sha256(protected.read_bytes()).hexdigest()


def test_missing_v21_246_input(tmp_path):
    repo = tmp_path / "repo"
    write_csv(repo / m.V247_REL / "technical_subfactor_effectiveness_master.csv", [{"x": 1}])
    write_csv(repo / m.V248_REL / "technical_repair_candidate_spec.csv", [{"repair_candidate_label": "RSI_LOW_REVERSAL_CONTEXT_R1"}])
    assert m.run(repo)["final_status"] == "FAIL_V21_249_TECHNICAL_REPAIR_RETEST_INPUT_MISSING"


def test_missing_v21_247_input(tmp_path):
    repo, _, _ = seed(tmp_path)
    (repo / m.V247_REL / "technical_subfactor_effectiveness_master.csv").unlink()
    assert m.run(repo)["final_status"] == "FAIL_V21_249_TECHNICAL_REPAIR_RETEST_INPUT_MISSING"


def test_missing_v21_248_input(tmp_path):
    repo, _, _ = seed(tmp_path)
    (repo / m.V248_REL / "technical_repair_candidate_spec.csv").unlink()
    assert m.run(repo)["final_status"] == "FAIL_V21_249_TECHNICAL_REPAIR_RETEST_INPUT_MISSING"


def test_empty_repair_candidate_spec(tmp_path):
    repo, _, _ = seed(tmp_path, empty_specs=True)
    assert m.run(repo)["final_status"] == "FAIL_V21_249_TECHNICAL_REPAIR_RETEST_INPUT_MISSING"


def test_pit_safe_signal_construction_and_no_future_leakage(tmp_path):
    repo, _, _ = seed(tmp_path)
    # Future returns are not part of add_repaired_signals inputs and changing them after construction would not change signal columns.
    df = m.load_panel(repo / m.V246_REL, ["RSI_LOW_REVERSAL_CONTEXT_R1"])
    built, missing = m.add_repaired_signals(df)
    assert not missing
    assert "RSI_LOW_REVERSAL_CONTEXT_R1" in built
    before = built["RSI_LOW_REVERSAL_CONTEXT_R1"].copy()
    df["forward_return_1d"] = df["forward_return_1d"] * -99
    built2, _ = m.add_repaired_signals(df)
    assert before.equals(built2["RSI_LOW_REVERSAL_CONTEXT_R1"])


def test_horizon_pass_and_fail_labels(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    data = rows(repo / m.OUT_REL / "technical_repair_candidate_pit_retest.csv")
    assert any(r["horizon_pass_flag"] == "True" for r in data)
    assert any(r["horizon_pass_flag"] == "False" for r in data)


def test_repaired_vs_raw_and_incremental_edge(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    assert rows(repo / m.OUT_REL / "technical_repair_vs_raw_comparison.csv")
    inc = rows(repo / m.OUT_REL / "technical_repair_incremental_edge_audit.csv")
    assert {r["incremental_edge_label"] for r in inc} & {"INCREMENTAL_EDGE_CONFIRMED", "WEAK_INCREMENTAL_EDGE", "REDUNDANT_BUT_USEFUL_TIMING", "REDUNDANT_NO_EDGE", "NEGATIVE_INCREMENTAL_EDGE"}


def test_timing_overlay_and_keep_drop(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    roles = rows(repo / m.OUT_REL / "technical_repair_role_recommendation.csv")
    keep = rows(repo / m.OUT_REL / "technical_repair_keep_drop_review.csv")
    assert roles and keep
    assert any(r["role_recommendation"] in {"TIMING_OVERLAY_CANDIDATE", "CONTEXT_FILTER_CANDIDATE", "DIAGNOSTIC_ONLY", "DROP_FROM_NEXT_ROUND"} for r in roles)


def test_summary_schema_and_gate_enforcement(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    for k in ["final_status", "final_decision", "repair_candidate_count", "official_adoption_allowed", "broker_action_allowed", "market_data_fetch_allowed"]:
        assert k in s
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["market_data_fetch_allowed"] is False


def test_no_provider_call_and_no_protected_mutation(tmp_path):
    repo, protected, before = seed(tmp_path)
    m.run(repo)
    after = hashlib.sha256(protected.read_bytes()).hexdigest()
    assert before == after
    text = P.read_text(encoding="utf-8").lower()
    banned = [r"\bimport\s+yfinance\b", r"\bfrom\s+yfinance\b", r"\bimport\s+moomoo\b", r"\bfrom\s+moomoo\b", r"\bimport\s+futu\b", r"\bfrom\s+futu\b"]
    assert not any(re.search(p, text) for p in banned)
