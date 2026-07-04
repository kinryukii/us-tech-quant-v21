from __future__ import annotations

import csv
import importlib.util
import json
import re
from pathlib import Path

P = Path(__file__).with_name("v21_245_moomoo_historical_backfill_to_local_cache_r1.py")
S = importlib.util.spec_from_file_location("m245", P)
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


class FakeProvider:
    def fetch_daily(self, ticker, moomoo_symbol, start, end, price_type):
        if ticker == "FAIL":
            return []
        if ticker == "PART":
            return [
                {"date": "2020-01-02", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000, "turnover": 10000},
                {"date": "2020-01-02", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000, "turnover": 10000},
            ]
        return [
            {"date": "2018-01-01", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 100, "turnover": 200},
            {"date": "2018-01-02", "open": 2, "high": 3, "low": 1, "close": 2, "volume": 100, "turnover": 200},
            {"date": "2026-07-03", "open": 3, "high": 4, "low": 2, "close": 3, "volume": 100, "turnover": 300},
        ]


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, rows[0].keys(), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def seed_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    cache = tmp_path / "cache"
    rows = [
        {"ticker": "FULL", "rank": 1},
        {"ticker": "PART", "rank": 2},
        {"ticker": "SKIP", "rank": 3},
        {"ticker": "FAIL", "rank": 4},
    ]
    write_csv(repo / "outputs/v21/V21.233_MOOMOO_ONLY_ABCDE_RERUN/ranking.csv", rows)
    existing = [
        {"date": "2018-01-01", "ticker": "SKIP", "moomoo_symbol": "US.SKIP", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "turnover": "", "price_type": "RAW_DAILY", "provider": "MOOMOO", "fetch_timestamp": "x", "source_run_id": "old"},
        {"date": "2026-07-03", "ticker": "SKIP", "moomoo_symbol": "US.SKIP", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "turnover": "", "price_type": "RAW_DAILY", "provider": "MOOMOO", "fetch_timestamp": "x", "source_run_id": "old"},
    ]
    write_csv(cache / "market_data/moomoo/daily/raw/SKIP.csv", existing)
    qfq_existing = [dict(r, price_type="QFQ_DAILY") for r in existing]
    write_csv(cache / "market_data/moomoo/daily/qfq/SKIP.csv", qfq_existing)
    return repo, cache


def run_seeded(tmp_path: Path, execute: bool = True):
    repo, cache = seed_repo(tmp_path)
    s = m.run(repo, cache_root=cache, start_date="2018-01-01", end_date="2026-07-03", execute=execute, allow_moomoo_provider_fetch=execute, provider=FakeProvider())
    return repo, cache, repo / m.OUT_REL, s


def rows(path: Path):
    return list(csv.DictReader(path.open(encoding="utf-8")))


def test_required_output_files_are_created(tmp_path):
    _, _, out, _ = run_seeded(tmp_path)
    required = [
        "v21_245_summary.json", "moomoo_backfill_universe.csv", "moomoo_backfill_plan.csv",
        "moomoo_backfill_progress.csv", "moomoo_backfill_result.csv", "moomoo_backfill_failure_audit.csv",
        "moomoo_cache_manifest.csv", "moomoo_cache_hash_manifest.csv", "moomoo_daily_panel_coverage_audit.csv",
        "technical_indicator_build_plan.csv", "forward_return_build_plan.csv", "V21.245_moomoo_historical_backfill_report.txt",
    ]
    assert all((out / name).exists() for name in required)


def test_summary_json_contains_governance_fields(tmp_path):
    _, _, out, _ = run_seeded(tmp_path)
    s = json.loads((out / "v21_245_summary.json").read_text(encoding="utf-8"))
    for key in ["final_status", "final_decision", "research_only", "official_adoption_allowed", "broker_action_allowed"]:
        assert key in s
    assert s["research_only"] is True


def test_official_adoption_allowed_is_always_false(tmp_path):
    _, _, _, s = run_seeded(tmp_path)
    assert s["official_adoption_allowed"] is False
    assert s["official_factor_marked_count"] == 0


def test_broker_action_allowed_is_always_false(tmp_path):
    _, _, _, s = run_seeded(tmp_path)
    assert s["broker_action_allowed"] is False


def test_non_moomoo_providers_are_never_called_static():
    text = P.read_text(encoding="utf-8").lower()
    banned = [r"\bimport\s+yfinance\b", r"\bfrom\s+yfinance\b", r"yf\.download", r"alphavantage", r"polygon", r"nasdaq"]
    assert not any(re.search(p, text) for p in banned)


def test_provider_fetch_is_isolated_behind_adapter_and_mocked(tmp_path):
    _, _, out, s = run_seeded(tmp_path)
    assert s["provider"] == "MOOMOO"
    result = rows(out / "moomoo_backfill_result.csv")
    assert any(r["ticker"] == "FULL" and r["result_status"] == "SUCCESS_FULL" for r in result)


def test_existing_cache_files_are_reused_and_not_duplicated(tmp_path):
    _, cache, out, s = run_seeded(tmp_path)
    result = rows(out / "moomoo_backfill_result.csv")
    assert any(r["ticker"] == "SKIP" and r["result_status"] == "SKIPPED_ALREADY_CURRENT" for r in result)
    assert len(rows(cache / "market_data/moomoo/daily/raw/SKIP.csv")) == 2


def test_cache_rows_are_deduplicated_by_ticker_and_date(tmp_path):
    _, cache, _, _ = run_seeded(tmp_path)
    data = rows(cache / "market_data/moomoo/daily/raw/PART.csv")
    keys = {(r["ticker"], r["date"]) for r in data}
    assert len(data) == len(keys)


def test_cache_manifest_contains_required_fields(tmp_path):
    _, _, out, _ = run_seeded(tmp_path)
    data = rows(out / "moomoo_cache_manifest.csv")
    assert data
    assert {"cache_file_path", "ticker", "first_date", "latest_date", "row_count"} <= set(data[0])
    hashes = rows(out / "moomoo_cache_hash_manifest.csv")
    assert "sha256" in hashes[0]


def test_backfill_result_classifies_full_partial_skipped_failed(tmp_path):
    _, _, out, _ = run_seeded(tmp_path)
    statuses = {r["result_status"] for r in rows(out / "moomoo_backfill_result.csv")}
    assert {"SUCCESS_FULL", "SUCCESS_PARTIAL_IPO_LATE", "SKIPPED_ALREADY_CURRENT", "FAIL_EMPTY_RESPONSE"} <= statuses


def test_coverage_audit_classification_values_supported(tmp_path):
    _, _, out, _ = run_seeded(tmp_path)
    classes = {r["coverage_class"] for r in rows(out / "moomoo_daily_panel_coverage_audit.csv")}
    allowed = {"FULL_FROM_2018", "PARTIAL_IPO_LATE", "PARTIAL_PROVIDER_LIMIT", "PARTIAL_MISSING_DATES", "NO_DATA", "INVALID"}
    assert classes <= allowed
    assert {"FULL_FROM_2018", "PARTIAL_IPO_LATE", "NO_DATA"} <= classes


def test_technical_build_plan_includes_required_subfactors(tmp_path):
    _, _, out, _ = run_seeded(tmp_path)
    names = {r["technical_subfactor_name"] for r in rows(out / "technical_indicator_build_plan.csv")}
    assert {"RSI", "KDJ", "MACD", "BB", "MA20", "MA50", "volume_ma", "volatility", "momentum", "relative_strength", "breakout", "pullback"} <= names


def test_forward_return_build_plan_includes_required_horizons(tmp_path):
    _, _, out, _ = run_seeded(tmp_path)
    horizons = {r["horizon"] for r in rows(out / "forward_return_build_plan.csv")}
    assert {"1D", "5D", "10D", "20D"} <= horizons


def test_no_factor_is_marked_official(tmp_path):
    _, _, _, s = run_seeded(tmp_path)
    assert s["official_factor_marked_count"] == 0


def test_no_factor_is_marked_shadow_candidate(tmp_path):
    _, _, _, s = run_seeded(tmp_path)
    assert s["shadow_candidate_marked_count"] == 0


def test_partial_provider_coverage_does_not_fail_exit_semantics(tmp_path):
    _, _, _, s = run_seeded(tmp_path)
    assert s["final_status"] != "FAIL_V21_245_MOOMOO_BACKFILL_EXECUTION_ERROR"
