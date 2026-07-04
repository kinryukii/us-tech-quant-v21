from __future__ import annotations

import csv
import importlib.util
import json
import re
from pathlib import Path

P = Path(__file__).with_name("v21_243_factor_effectiveness_continuation_r1.py")
S = importlib.util.spec_from_file_location("m243c", P)
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
    rows = []
    tickers = [f"T{i:02d}" for i in range(30)]
    dates = ["2026-06-18", "2026-06-19", "2026-06-22"]
    for d_i, d in enumerate(dates):
        for h in ["1D", "5D"]:
            for rank, ticker in enumerate(tickers, 1):
                ret = (31 - rank) * 0.001 + (0.002 if h == "5D" else 0.0) + d_i * 0.0001
                rows.append({
                    "ranking_date": d,
                    "strategy": "A1",
                    "ticker": ticker,
                    "rank": rank,
                    "candidate_source_strategy": "A1",
                    "source_mode": "LIVE_SNAPSHOT",
                    "pit_status": "LIVE_ORIGINAL",
                    "forward_window": h,
                    "target_price_date": "2026-06-30",
                    "forward_return": ret,
                    "maturity_status": "MATURED",
                    "top_n": "20" if rank <= 20 else "50",
                })
    write_csv(repo / m.V250_REL / "e_r2_shadow_forward_tracking_ledger.csv", rows)
    return repo


def run_seeded(tmp_path: Path):
    repo = seed_repo(tmp_path)
    s = m.run(repo)
    out = repo / m.OUT_REL
    return repo, out, s


def read_csv(path: Path):
    return list(csv.DictReader(path.open(encoding="utf-8")))


def test_required_output_files_are_created(tmp_path):
    _, out, _ = run_seeded(tmp_path)
    required = [
        "v21_243_summary.json",
        "factor_effectiveness_detail.csv",
        "subfactor_effectiveness_detail.csv",
        "family_effectiveness_summary.csv",
        "technical_subfactor_effectiveness.csv",
        "factor_correlation_cluster.csv",
        "factor_regime_dependency.csv",
        "factor_outlier_dependency.csv",
        "factor_promotion_candidate_review.csv",
        "V21.243_factor_effectiveness_report.txt",
    ]
    assert all((out / name).exists() for name in required)


def test_summary_json_contains_governance_fields(tmp_path):
    _, out, _ = run_seeded(tmp_path)
    s = json.loads((out / "v21_243_summary.json").read_text(encoding="utf-8"))
    for key in ["final_status", "final_decision", "research_only", "official_adoption_allowed", "broker_action_allowed"]:
        assert key in s
    assert s["research_only"] is True


def test_official_adoption_allowed_is_always_false(tmp_path):
    _, out, s = run_seeded(tmp_path)
    assert s["official_adoption_allowed"] is False
    assert {r["official_adoption_allowed"] for r in read_csv(out / "factor_effectiveness_detail.csv")} == {"False"}


def test_broker_action_allowed_is_always_false(tmp_path):
    _, out, s = run_seeded(tmp_path)
    assert s["broker_action_allowed"] is False
    assert {r["broker_action_allowed"] for r in read_csv(out / "factor_effectiveness_detail.csv")} == {"False"}


def test_non_pit_factors_are_not_promoted(tmp_path):
    _, out, _ = run_seeded(tmp_path)
    rows = [r for r in read_csv(out / "factor_promotion_candidate_review.csv") if r["factor_name"] == "event_proximity_risk_factor"]
    assert rows
    assert all(r["allowed_role"] == "PIT_BLOCKED" and r["promotion_review_decision"] == "NOT_PROMOTED" for r in rows)


def test_insufficient_coverage_factors_are_not_promoted(tmp_path):
    _, out, _ = run_seeded(tmp_path)
    rows = [r for r in read_csv(out / "factor_promotion_candidate_review.csv") if r["forward_horizon"] == "10D"]
    assert rows
    assert all(r["allowed_role"] in {"INSUFFICIENT_COVERAGE", "PIT_BLOCKED"} for r in rows)
    assert all(r["promotion_review_decision"] == "NOT_PROMOTED" for r in rows)


def test_technical_subfactors_are_evaluated_separately_when_available(tmp_path):
    _, out, s = run_seeded(tmp_path)
    rows = read_csv(out / "technical_subfactor_effectiveness.csv")
    names = {r["factor_name"] for r in rows}
    assert {"RSI", "KDJ", "MACD", "Bollinger Bands", "MA20", "MA50", "volatility", "momentum", "relative strength", "breakout", "pullback"} <= names
    assert s["evaluated_subfactor_count"] > 0


def test_promotion_review_contains_blocker_fields(tmp_path):
    _, out, _ = run_seeded(tmp_path)
    rows = read_csv(out / "factor_promotion_candidate_review.csv")
    assert rows and {"blocker_count", "blockers", "officially_adopted"} <= set(rows[0])
    assert all(r["officially_adopted"] == "False" for r in rows)


def test_no_provider_network_fetch_is_attempted(tmp_path):
    _, out, _ = run_seeded(tmp_path)
    s = json.loads((out / "v21_243_summary.json").read_text(encoding="utf-8"))
    assert s["market_data_fetch_attempted"] is False
    assert s["network_provider_fetch_attempted"] is False
    text = P.read_text(encoding="utf-8").lower()
    banned_imports = [
        r"\bimport\s+yfinance\b",
        r"\bfrom\s+yfinance\b",
        r"\bimport\s+requests\b",
        r"\bfrom\s+requests\b",
        r"\bimport\s+futu\b",
        r"\bfrom\s+futu\b",
        r"\bimport\s+moomoo\b",
        r"\bfrom\s+moomoo\b",
    ]
    assert not any(re.search(pattern, text) for pattern in banned_imports)


def test_weak_evidence_exits_successfully_not_execution_failure(tmp_path):
    repo = tmp_path / "repo"
    s = m.run(repo)
    assert s["error_count"] == 0
    assert s["final_status"] != "FAIL_V21_243_FACTOR_EFFECTIVENESS_EXECUTION_ERROR"
