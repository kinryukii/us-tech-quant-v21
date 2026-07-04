from __future__ import annotations

import csv
import importlib.util
import json
import re
from pathlib import Path

P = Path(__file__).with_name("v21_245_r1a_moomoo_cache_currentness_and_failure_triage.py")
S = importlib.util.spec_from_file_location("m245r1a", P)
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or (list(rows[0].keys()) if rows else ["cache_file_path", "sha256"])
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def rows(path: Path):
    return list(csv.DictReader(path.open(encoding="utf-8")))


def cache_row(ticker, d, pt="RAW_DAILY", close=1):
    return {"date": d, "ticker": ticker, "moomoo_symbol": f"US.{ticker}", "open": 1, "high": 2, "low": 0.5, "close": close, "volume": 100, "turnover": "", "price_type": pt, "provider": "MOOMOO", "fetch_timestamp": "x", "source_run_id": "r"}


def seed(tmp_path: Path):
    repo = tmp_path / "repo"
    cache = tmp_path / "cache"
    v245 = repo / m.DEFAULT_V245_REL
    summary = {"raw_daily_current_count": 0, "qfq_daily_current_count": 0, "full_from_2018_count": 0, "partial_ipo_late_count": 2, "technical_ready_to_build_count": 19, "forward_return_ready_to_build_count": 4}
    v245.mkdir(parents=True, exist_ok=True)
    (v245 / "v21_245_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    universe = [{"ticker": t, "moomoo_symbol": f"US.{t}"} for t in ["IPO", "DUP", "BAD", "FAIL"]]
    write_csv(v245 / "moomoo_backfill_universe.csv", universe)
    result = []
    coverage = []
    failure = []
    for t in ["IPO", "DUP", "BAD", "FAIL"]:
        for pt in ["RAW_DAILY", "QFQ_DAILY"]:
            status = "FAIL_EMPTY_RESPONSE" if t == "FAIL" else "SUCCESS_PARTIAL_IPO_LATE"
            result.append({"ticker": t, "moomoo_symbol": f"US.{t}", "price_type": pt, "result_status": status})
            if t == "FAIL":
                failure.append({"ticker": t, "moomoo_symbol": f"US.{t}", "price_type": pt, "result_status": status, "failure_class": "EMPTY_RESPONSE", "failure_reason": "empty"})
        coverage.append({"ticker": t, "coverage_class": "NO_DATA" if t == "FAIL" else "PARTIAL_IPO_LATE"})
    write_csv(v245 / "moomoo_backfill_result.csv", result)
    write_csv(v245 / "moomoo_backfill_failure_audit.csv", failure)
    write_csv(v245 / "moomoo_daily_panel_coverage_audit.csv", coverage)
    write_csv(v245 / "moomoo_cache_hash_manifest.csv", [])
    for pt, sub in [("RAW_DAILY", "raw"), ("QFQ_DAILY", "qfq")]:
        write_csv(cache / f"market_data/moomoo/daily/{sub}/IPO.csv", [cache_row("IPO", "2020-01-02", pt), cache_row("IPO", "2026-07-03", pt)], m.REQUIRED_COLS)
        write_csv(cache / f"market_data/moomoo/daily/{sub}/DUP.csv", [cache_row("DUP", "2020-01-02", pt), cache_row("DUP", "2020-01-02", pt), cache_row("DUP", "2026-07-03", pt)], m.REQUIRED_COLS)
        write_csv(cache / f"market_data/moomoo/daily/{sub}/BAD.csv", [{"date": "2026-07-03", "ticker": "BAD", "close": 1}])
    return repo, cache


def run_seeded(tmp_path):
    repo, cache = seed(tmp_path)
    s = m.run(repo, cache_root=cache, expected_latest_date="2026-07-03", minimum_usable_ticker_count=1, write_exclusion_list=True)
    return repo, cache, repo / m.OUT_REL, s


def test_required_output_files_are_created(tmp_path):
    _, _, out, _ = run_seeded(tmp_path)
    req = ["v21_245_r1a_summary.json", "moomoo_cache_currentness_audit.csv", "moomoo_failed_symbol_triage.csv", "moomoo_partial_history_classification.csv", "moomoo_latest_date_distribution.csv", "moomoo_cache_ready_for_v21_246_gate.csv", "moomoo_currentness_logic_audit.csv", "moomoo_cache_file_integrity_audit.csv", "V21.245_R1A_moomoo_cache_currentness_triage_report.txt"]
    assert all((out / x).exists() for x in req)


def test_summary_json_contains_governance_fields(tmp_path):
    _, _, out, _ = run_seeded(tmp_path)
    s = json.loads((out / "v21_245_r1a_summary.json").read_text(encoding="utf-8"))
    for k in ["final_status", "final_decision", "research_only", "official_adoption_allowed", "broker_action_allowed"]:
        assert k in s
    assert s["research_only"] is True


def test_official_and_broker_flags_false(tmp_path):
    _, _, _, s = run_seeded(tmp_path)
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False


def test_no_factor_marked_official_or_shadow(tmp_path):
    _, _, _, s = run_seeded(tmp_path)
    assert s["official_factor_marked_count"] == 0
    assert s["shadow_candidate_marked_count"] == 0


def test_no_broad_provider_fetch_or_non_moomoo_provider(tmp_path):
    _, _, _, s = run_seeded(tmp_path)
    assert s["broad_provider_fetch_attempted"] is False
    text = P.read_text(encoding="utf-8").lower()
    assert not any(re.search(p, text) for p in [r"\bimport\s+yfinance\b", r"\bfrom\s+yfinance\b", r"yf\.download", r"alphavantage", r"polygon", r"nasdaq"])


def test_ipo_late_latest_current_not_stale(tmp_path):
    _, _, out, _ = run_seeded(tmp_path)
    data = [r for r in rows(out / "moomoo_cache_currentness_audit.csv") if r["ticker"] == "IPO"]
    assert data and all(r["cache_currentness_status"] == "PARTIAL_IPO_LATE_BUT_CURRENT" for r in data)


def test_logic_audit_identifies_strict_full_from_2018(tmp_path):
    _, _, out, _ = run_seeded(tmp_path)
    data = rows(out / "moomoo_currentness_logic_audit.csv")
    assert any(r["likely_issue"] == "CLASSIFICATION_TOO_STRICT_FULL_FROM_2018_ONLY" for r in data)


def test_failed_symbol_triage_has_next_action(tmp_path):
    _, _, out, _ = run_seeded(tmp_path)
    data = rows(out / "moomoo_failed_symbol_triage.csv")
    assert data and "recommended_next_action" in data[0]


def test_integrity_detects_duplicates_and_invalid_schema(tmp_path):
    _, _, out, _ = run_seeded(tmp_path)
    data = rows(out / "moomoo_cache_file_integrity_audit.csv")
    assert any(r["ticker"] == "DUP" and r["integrity_status"] == "WARN_DUPLICATE_DATES" for r in data)
    assert any(r["ticker"] == "BAD" and r["integrity_status"] == "FAIL_SCHEMA_INVALID" for r in data)


def test_ready_gate_allowed_status_and_partial_not_failure(tmp_path):
    _, _, out, s = run_seeded(tmp_path)
    gate = rows(out / "moomoo_cache_ready_for_v21_246_gate.csv")[0]
    assert gate["gate_status"] in m.GATE_STATUSES
    assert s["final_status"] != "FAIL_V21_245_R1A_CACHE_TRIAGE_EXECUTION_ERROR"
