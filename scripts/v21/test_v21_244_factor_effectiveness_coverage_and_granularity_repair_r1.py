from __future__ import annotations

import csv
import importlib.util
import json
import re
from pathlib import Path

P = Path(__file__).with_name("v21_244_factor_effectiveness_coverage_and_granularity_repair_r1.py")
S = importlib.util.spec_from_file_location("m244", P)
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, rows[0].keys(), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def seed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    root = repo / m.V243_REL
    summary = {"evaluated_factor_count": 4, "insufficient_coverage_factor_count": 3, "research_only": True, "official_adoption_allowed": False, "broker_action_allowed": False}
    root.mkdir(parents=True, exist_ok=True)
    (root / "v21_243_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    inv = [
        {"factor_name": "RSI", "factor_family": "Technical", "factor_subtype": "technical", "source_artifact": "x", "pit_eligibility": "PIT_ELIGIBLE", "coverage_ratio": 0.1, "available_horizons": "1D", "observation_count": 60},
        {"factor_name": "KDJ", "factor_family": "Technical", "factor_subtype": "technical", "source_artifact": "x", "pit_eligibility": "PIT_ELIGIBLE", "coverage_ratio": 0.1, "available_horizons": "1D", "observation_count": 60},
        {"factor_name": "MACD", "factor_family": "Technical", "factor_subtype": "technical", "source_artifact": "x", "pit_eligibility": "PIT_ELIGIBLE", "coverage_ratio": 0.1, "available_horizons": "1D", "observation_count": 60},
        {"factor_name": "event_proximity_risk_factor", "factor_family": "Market Regime", "factor_subtype": "repair", "source_artifact": "x", "pit_eligibility": "PIT_BLOCKED", "coverage_ratio": 0.0, "available_horizons": "", "observation_count": 0},
    ]
    write_csv(root / "factor_inventory.csv", inv)
    detail = []
    for f in inv:
        for h in ["1D", "5D", "10D", "20D"]:
            detail.append({"factor_name": f["factor_name"], "factor_family": f["factor_family"], "factor_subtype": f["factor_subtype"], "forward_horizon": h, "pit_eligibility": f["pit_eligibility"], "coverage_ratio": 0.1 if h == "1D" else 0, "observation_count": 60 if h == "1D" and f["pit_eligibility"] != "PIT_BLOCKED" else 0, "allowed_role": "INSUFFICIENT_COVERAGE"})
    write_csv(root / "factor_effectiveness_detail.csv", detail)
    write_csv(root / "subfactor_effectiveness_detail.csv", [r for r in detail if r["factor_family"] == "Technical"])
    panel = []
    fwd = []
    for d in ["2026-06-18", "2026-06-19", "2026-06-22"]:
        for i in range(25):
            t = f"T{i:02d}"
            panel.append({"ranking_date": d, "ticker": t, "RSI": i, "KDJ": i + 1, "MACD": i + 2, "BB": i + 3, "MA20": i + 4, "MA50": i + 5, "volume": 100 + i, "volatility": 0.1, "momentum": 0.2, "pit_status": "LIVE_ORIGINAL"})
            fwd.append({"ranking_date": d, "ticker": t, "forward_window": "1D", "forward_return": 0.01, "maturity_status": "MATURED"})
    write_csv(repo / "outputs/v21/LOCAL_TECHNICAL_PANEL/technical_feature_panel.csv", panel)
    write_csv(repo / "outputs/v21/LOCAL_FORWARD_LEDGER/forward_return_ledger.csv", fwd)
    return repo


def run_seeded(tmp_path: Path):
    repo = seed_repo(tmp_path)
    s = m.run(repo)
    return repo, repo / m.OUT_REL, s


def rows(path: Path):
    return list(csv.DictReader(path.open(encoding="utf-8")))


def test_required_output_files_are_created(tmp_path):
    _, out, _ = run_seeded(tmp_path)
    required = ["v21_244_summary.json", "factor_coverage_failure_detail.csv", "factor_source_artifact_map.csv", "factor_join_diagnostics.csv", "factor_horizon_availability.csv", "factor_panel_reconstruction_plan.csv", "technical_raw_subfactor_discovery.csv", "pit_eligibility_recheck.csv", "coverage_threshold_sensitivity.csv", "V21.244_factor_coverage_repair_report.txt"]
    assert all((out / name).exists() for name in required)


def test_summary_json_contains_governance_fields(tmp_path):
    _, out, _ = run_seeded(tmp_path)
    s = json.loads((out / "v21_244_summary.json").read_text(encoding="utf-8"))
    for key in ["final_status", "final_decision", "research_only", "official_adoption_allowed", "broker_action_allowed"]:
        assert key in s
    assert s["research_only"] is True


def test_official_adoption_allowed_is_always_false(tmp_path):
    _, out, s = run_seeded(tmp_path)
    assert s["official_adoption_allowed"] is False
    assert {r["officially_adopted"] for r in rows(out / "factor_panel_reconstruction_plan.csv")} == {"False"}


def test_broker_action_allowed_is_always_false(tmp_path):
    _, _, s = run_seeded(tmp_path)
    assert s["broker_action_allowed"] is False


def test_no_factor_is_marked_official(tmp_path):
    _, out, s = run_seeded(tmp_path)
    assert s["official_factor_marked_count"] == 0
    assert all(r["officially_adopted"] == "False" for r in rows(out / "factor_coverage_failure_detail.csv"))


def test_no_factor_is_marked_shadow_candidate(tmp_path):
    _, out, s = run_seeded(tmp_path)
    assert s["shadow_candidate_marked_count"] == 0
    assert all(r["shadow_candidate"] == "False" for r in rows(out / "factor_panel_reconstruction_plan.csv"))


def test_coverage_failure_detail_contains_blockers(tmp_path):
    _, out, _ = run_seeded(tmp_path)
    data = rows(out / "factor_coverage_failure_detail.csv")
    assert data and "primary_blocker" in data[0]
    assert any(r["pit_blocked"] == "TRUE" for r in data)


def test_join_diagnostics_contain_join_counts_and_ratio(tmp_path):
    _, out, _ = run_seeded(tmp_path)
    data = rows(out / "factor_join_diagnostics.csv")
    assert data and {"joined_row_count", "join_success_ratio"} <= set(data[0])


def test_technical_discovery_includes_required_terms(tmp_path):
    _, out, _ = run_seeded(tmp_path)
    names = {r["technical_term"] for r in rows(out / "technical_raw_subfactor_discovery.csv")}
    assert {"RSI", "KDJ", "MACD", "BB", "MA20", "MA50", "volume", "volatility", "momentum"} <= names


def test_no_provider_network_fetch_is_attempted(tmp_path):
    _, out, _ = run_seeded(tmp_path)
    s = json.loads((out / "v21_244_summary.json").read_text(encoding="utf-8"))
    assert s["market_data_fetch_attempted"] is False
    assert s["network_provider_fetch_attempted"] is False
    text = P.read_text(encoding="utf-8").lower()
    banned = [r"\bimport\s+yfinance\b", r"\bfrom\s+yfinance\b", r"\bimport\s+requests\b", r"\bfrom\s+requests\b", r"\bimport\s+futu\b", r"\bfrom\s+futu\b", r"\bimport\s+moomoo\b", r"\bfrom\s+moomoo\b"]
    assert not any(re.search(p, text) for p in banned)
