from __future__ import annotations

import ast
import csv
import importlib.util
import re
import shutil
import subprocess
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "scripts" / "v20"
PRODUCTION = SCRIPT_DIR / "v20_47_controlled_current_market_refresh_and_cache_certification.py"
WRAPPER = SCRIPT_DIR / "run_v20_47_controlled_current_market_refresh_and_cache_certification.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

PASS_STATUS = "PASS_V20_47_TESTS"
PARTIAL_CERTIFIED_STATUS = "PARTIAL_CERTIFIED_RESEARCH_HANDOFF"
BLOCKED_CERT_STATUS = "BLOCKED_REFRESH_CACHE_CERTIFICATION"
FALLBACK_CERTIFIED_STATUS = "CERTIFIED_CACHE_FALLBACK_HANDOFF"
PROVIDER_DIAGNOSTICS = CONSOLIDATION / "V20_47_PROVIDER_REFRESH_DIAGNOSTICS.csv"
PROVIDER_SUMMARY = CONSOLIDATION / "V20_47_PROVIDER_REFRESH_SUMMARY.csv"


def load_module():
    spec = importlib.util.spec_from_file_location("v20_47_stage", PRODUCTION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v20_47 = load_module()


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def clean(value: object) -> str:
    return str(value or "").strip()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def dates() -> pd.DatetimeIndex:
    return pd.to_datetime(["2026-06-02", "2026-06-03", "2026-06-04"])


def test_close_only_dataframe_extracts_valid_close() -> None:
    df = pd.DataFrame({"Close": [10.0, None, 12.5]}, index=dates())
    result = v20_47.extract_latest_close_like_price(df, "SPOT")
    assert_true(result["extraction_status"] == "SUCCESS", "Close-only extraction failed")
    assert_true(result["latest_price_date"] == "2026-06-04", "Wrong latest close date")
    assert_true(result["latest_close"] == "12.5", "Wrong close-only price")
    assert_true(result["selected_price_field"] == "Close", "Wrong selected field")


def test_adj_close_only_dataframe_extracts_valid_adjusted_close() -> None:
    df = pd.DataFrame({"Adj Close": [20.0, 21.0, 22.25]}, index=dates())
    result = v20_47.extract_latest_close_like_price(df, "APP")
    assert_true(result["extraction_status"] == "SUCCESS", "Adj Close-only extraction failed")
    assert_true(result["latest_close"] == "22.25", "Wrong adjusted close price")
    assert_true(result["selected_price_field"] == "Adj Close", "Wrong adjusted field")


def test_multiindex_price_ticker_layout_extracts_valid_ticker_close() -> None:
    columns = pd.MultiIndex.from_tuples([("Close", "META"), ("Close", "QQQ")])
    df = pd.DataFrame([[1.0, 2.0], [3.0, 4.0], [5.5, 6.0]], index=dates(), columns=columns)
    result = v20_47.extract_latest_close_like_price(df, "META")
    assert_true(result["extraction_status"] == "SUCCESS", "Price/Ticker MultiIndex extraction failed")
    assert_true(result["latest_close"] == "5.5", "Wrong META close")


def test_multiindex_ticker_price_layout_extracts_valid_ticker_close() -> None:
    columns = pd.MultiIndex.from_tuples([("CRWD", "Adj Close"), ("SPY", "Adj Close")])
    df = pd.DataFrame([[7.0, 8.0], [9.0, 10.0], [11.75, 12.0]], index=dates(), columns=columns)
    result = v20_47.extract_latest_close_like_price(df, "CRWD")
    assert_true(result["extraction_status"] == "SUCCESS", "Ticker/Price MultiIndex extraction failed")
    assert_true(result["latest_close"] == "11.75", "Wrong CRWD adjusted close")
    assert_true(result["selected_price_field"] == "Adj Close", "Wrong CRWD field")


def test_auto_adjust_style_close_present_certifies() -> None:
    row, failure = v20_47.price_row_from_dataframe(
        "V20_47_TEST",
        "PLTR",
        "candidate_tickers",
        "2026-06-05T00:00:00Z",
        pd.DataFrame({"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [100]}, index=pd.to_datetime(["2026-06-04"])),
        False,
        "NOT_ATTEMPTED",
        "SUCCESS",
    )
    cert = v20_47.certify_candidate_rows([row], "abc")[0]
    assert_true(failure is None, "Close-present auto_adjust-style row produced failure")
    assert_true(cert["certification_status"] == "CERTIFIED", "Close-present row did not certify")
    assert_true(cert["blocks_stage_certification"] == "FALSE", "Candidate cert row should not hard-block")


def test_empty_dataframe_fails_gracefully() -> None:
    result = v20_47.extract_latest_close_like_price(pd.DataFrame(), "PDD")
    assert_true(result["extraction_status"] == "FAILED", "Empty DataFrame did not fail")
    assert_true(result["extraction_reason"] == "empty_dataframe", "Wrong empty DataFrame reason")


def test_certification_requires_latest_price_date_and_selected_field() -> None:
    row, _ = v20_47.price_row_from_dataframe(
        "V20_47_TEST",
        "META",
        "candidate_tickers",
        "2026-06-05T00:00:00Z",
        pd.DataFrame({"Close": [10.0]}, index=pd.to_datetime(["2026-06-04"])),
        False,
        "NOT_ATTEMPTED",
        "SUCCESS",
    )
    missing_date = dict(row)
    missing_date["latest_price_date"] = ""
    missing_field = dict(row)
    missing_field["selected_price_field"] = ""
    cert_rows = v20_47.certify_candidate_rows([missing_date, missing_field], "abc")
    assert_true(all(clean(row.get("certification_status")) == "BLOCKED" for row in cert_rows), "Missing date/selected field must block candidate certification")
    bench = v20_47.certify_benchmark_rows([missing_date], "abc")[0]
    assert_true(clean(bench.get("certification_status")) == "BLOCKED", "Missing date/field must block benchmark certification")


def test_provider_cache_diagnostics_and_cache_db_error_capture() -> None:
    diagnostics = v20_47.provider_cache_diagnostics()
    assert_true(clean(diagnostics.get("provider_cache_dir")).endswith("state/v20/provider_cache/yfinance"), "Provider cache dir should be project-local")
    assert_true(clean(diagnostics.get("provider_cache_dir_exists")) == "TRUE", "Provider cache dir should exist")
    assert_true(clean(diagnostics.get("provider_cache_dir_writable")) == "TRUE", "Provider cache dir should be writable")
    assert_true(v20_47.provider_error_type("FAILED: unable to open database file") == "PROVIDER_CACHE_DB_ERROR", "Cache DB error type not detected")
    failure = v20_47.failure_row("V20_47_TEST", "SPY", "benchmark_tickers", "missing_price", "empty_dataframe", True, True, "FAILED: unable to open database file", "FAILED: unable to open database file")
    assert_true(clean(failure.get("cache_db_error_detected")) == "TRUE", "Failure row must capture cache DB error")
    assert_true("unable to open database file" in clean(failure.get("retry_error_message")), "Retry error message missing")


def test_missing_close_like_fields_fail_gracefully() -> None:
    df = pd.DataFrame({"Open": [1.0], "High": [2.0], "Low": [0.5], "Volume": [100]}, index=pd.to_datetime(["2026-06-04"]))
    result = v20_47.extract_latest_close_like_price(df, "DASH")
    assert_true(result["extraction_status"] == "FAILED", "Missing close-like fields did not fail")
    assert_true("missing_close_like" in result["extraction_reason"], "Wrong missing-field reason")


def test_candidate_partial_failure_does_not_block_research_handoff() -> None:
    failures = [
        {"ticker": "SPOT", "blocks_stage_certification": "FALSE"},
        {"ticker": "APP", "blocks_stage_certification": "FALSE"},
    ]
    decision = v20_47.evaluate_stage_decision(40, 22, 2, failures, [])
    assert_true(decision["certification_status"] == PARTIAL_CERTIFIED_STATUS, "Partial candidate failure should be partial-certified")
    assert_true(decision["partial_research_handoff_allowed"] is True, "Partial handoff should be allowed")
    assert_true(decision["final_status"].startswith("PASS_"), "Partial handoff should return pass status")
    assert_true(not decision["blockers"], f"Unexpected partial-handoff blockers: {decision['blockers']}")


def test_benchmark_failure_blocks_stage() -> None:
    failures = [{"ticker": "SPY", "blocks_stage_certification": "TRUE"}]
    decision = v20_47.evaluate_stage_decision(40, 40, 1, failures, [])
    assert_true(decision["certification_status"] == BLOCKED_CERT_STATUS, "Benchmark failure must block")
    assert_true(decision["final_status"].startswith("BLOCKED_"), "Benchmark failure should return blocked status")


def test_no_forbidden_output_paths_are_created() -> None:
    forbidden = [
        ROOT / "outputs" / "v21",
        ROOT / "outputs" / "v19_21",
        ROOT / "outputs" / "v19" / "V19_21",
    ]
    existing = [str(path) for path in forbidden if path.exists()]
    assert_true(not existing, f"Forbidden output paths exist: {existing}")


def test_safety_boundary_flags_remain_pass_when_artifact_exists() -> None:
    path = CONSOLIDATION / "V20_47_REFRESH_SAFETY_BOUNDARY.csv"
    rows = read_csv(path)
    if not rows:
        return
    by_name = {clean(row.get("safety_boundary")): row for row in rows}
    required = {
        "broker_order_execution_used": "FALSE",
        "official_recommendation_allowed": "FALSE",
        "official_trading_allowed": "FALSE",
        "official_ranking_mutated": "FALSE",
        "dynamic_weighting_mutated": "FALSE",
        "real_portfolio_mutated": "FALSE",
        "returns_calculated": "FALSE",
        "scores_recomputed": "FALSE",
        "rankings_recomputed": "FALSE",
        "trading_signals_created": "FALSE",
    }
    for name, expected in required.items():
        row = by_name.get(name)
        assert_true(row is not None, f"Missing safety row {name}")
        assert_true(clean(row.get("actual_value")) == expected, f"{name} actual value changed")
        assert_true(clean(row.get("validation_status")) == "PASS", f"{name} did not pass")


def test_wrapper_reports_accepted_statuses_and_exit_policy() -> None:
    text = WRAPPER.read_text(encoding="utf-8")
    assert_true("FINAL_STATUS=PASS_V20_47_CONTROLLED_CURRENT_MARKET_REFRESH_AND_CACHE_CERTIFICATION" in text, "Wrapper missing pass final status")
    assert_true("throw \"V20.47 stage failed" in text, "Wrapper should fail on production non-zero exit")
    tokens = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "$null = [System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v20/run_v20_47_controlled_current_market_refresh_and_cache_certification.ps1'), [ref]$null); 'PARSE_OK'",
        ],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    assert_true(tokens.returncode == 0 and "PARSE_OK" in tokens.stdout, f"Wrapper parse failed: {tokens.stderr}")


def test_static_safety_scans() -> None:
    prod_text = PRODUCTION.read_text(encoding="utf-8", errors="ignore")
    wrapper_text = WRAPPER.read_text(encoding="utf-8", errors="ignore")
    assert_true(re.search(r"^\s*import\s+yfinance\s+as\s+yf\b", prod_text, re.MULTILINE) is not None, "Guarded yfinance import missing")
    assert_true(re.search(r"^\s*(import|from)\s+yfinance\b|\byfinance\.|\byf\.", wrapper_text, re.MULTILINE) is None, "Wrapper must not use yfinance")
    forbidden_patterns = [
        r"\bsubmit_order\s*\(",
        r"\bplace_order\s*\(",
        r"\bofficial_recommendation_(?:created|generated|allowed)\b\s*=\s*TRUE\b",
        r"\bofficial_ranking_mutat(?:e|ed|ion)\b\s*=\s*TRUE\b",
        r"\bdynamic_weighting_mutat(?:e|ed|ion)\b\s*=\s*TRUE\b",
        r"\b(calculate_returns|compute_returns|recompute_scores|recompute_rankings)\s*\(",
        r"\btrading_signal(?:s)?_(?:created|generated)\b\s*=\s*TRUE\b",
    ]
    for pattern in forbidden_patterns:
        assert_true(re.search(pattern, prod_text, re.IGNORECASE) is None, f"Forbidden production pattern: {pattern}")


def test_no_forbidden_path_literals() -> None:
    tree = ast.parse(PRODUCTION.read_text(encoding="utf-8"))
    literals = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    forbidden = [("outputs", "v21"), ("outputs", "v19_21"), ("outputs", "v19", "V19_21")]
    for literal in literals:
        parts = tuple(part.lower() for part in literal.replace("\\", "/").split("/"))
        windows = [tuple(parts[i:i + len(item)]) for item in forbidden for i in range(len(parts))]
        for item in forbidden:
            assert_true(tuple(part.lower() for part in item) not in windows, f"Forbidden path literal found: {literal}")


def test_current_artifacts_accept_pass_or_partial_handoff() -> None:
    summary_rows = read_csv(CONSOLIDATION / "V20_47_CONTROLLED_REFRESH_SUMMARY.csv")
    next_rows = read_csv(CONSOLIDATION / "V20_47_NEXT_STEP_DECISION.csv")
    report = READ_CENTER / "V20_CURRENT_CONTROLLED_MARKET_REFRESH_CERTIFICATION.md"
    if not summary_rows or not next_rows or not report.exists():
        return
    summary = summary_rows[0]
    next_row = next_rows[0]
    accepted = {"CERTIFIED_FOR_RESEARCH_REPORT_HANDOFF", PARTIAL_CERTIFIED_STATUS, FALLBACK_CERTIFIED_STATUS}
    assert_true(clean(summary.get("certification_status")) in accepted or clean(summary.get("certification_status")) == BLOCKED_CERT_STATUS, "Unexpected summary certification status")
    if clean(summary.get("certification_status")) in accepted:
        assert_true(clean(next_row.get("research_report_handoff_ready")) == "TRUE", "Accepted status should hand off")
    text = report.read_text(encoding="utf-8").lower()
    assert_true("no broker/order execution occurred" in text, "Report missing broker boundary")
    assert_true("no score, ranking, or return recomputation occurred" in text, "Report missing score/ranking/return boundary")


def test_promotion_semantics_are_guarded_by_accepted_handoff() -> None:
    text = PRODUCTION.read_text(encoding="utf-8")
    assert_true("run_raw_candidate_cache" in text and "run_out_candidate_cache" in text, "Run-scoped candidate artifacts missing")
    assert_true("accepted_handoff = not blockers and decision in {DECISION_PASS, DECISION_PARTIAL}" in text, "Accepted handoff guard missing")
    assert_true("copy_if_exists(run_out_candidate_cache, OUT_RAW_CANDIDATE_CACHE)" in text, "Candidate cache promotion missing")
    assert_true("copy_if_exists(run_candidate_cert_path, OUT_CANDIDATE_CERT)" in text, "Candidate certification promotion missing")
    assert_true("write_csv(OUT_LAST_FAILED_ATTEMPT" in text, "Failed-attempt artifact write missing")
    forbidden_direct_writes = [
        "write_csv(OUT_RAW_CANDIDATE_CACHE, candidate_prices",
        "write_csv(OUT_RAW_BENCHMARK_CACHE, benchmark_prices",
        "write_csv(OUT_CANDIDATE_CERT, candidate_cert",
        "write_csv(OUT_BENCHMARK_CERT, benchmark_cert",
        "write_csv(OUT_STAGED_CANDIDATE, staged_candidate",
        "write_csv(OUT_STAGED_BENCHMARK, staged_benchmark",
    ]
    for snippet in forbidden_direct_writes:
        assert_true(snippet not in text, f"Unguarded current artifact write remains: {snippet}")


def test_failed_attempt_artifact_contract_when_present() -> None:
    path = CONSOLIDATION / "V20_47_LAST_FAILED_REFRESH_ATTEMPT.csv"
    if not path.exists():
        return
    rows = read_csv(path)
    assert_true(rows, "Failed-attempt artifact must be non-empty")
    row = rows[0]
    for field in [
        "attempted_run_id",
        "current_certified_run_id_before_attempt",
        "current_certified_run_id_after_attempt",
        "current_alias_promoted_this_run",
        "failed_attempt_preserved",
        "failed_attempt_did_not_overwrite_last_good",
        "candidate_tickers_requested",
        "benchmark_tickers_requested",
    ]:
        assert_true(field in row, f"Failed-attempt artifact missing field: {field}")
    assert_true(clean(row.get("current_alias_promoted_this_run")) == "FALSE", "Failed attempt must not promote current aliases")
    assert_true(clean(row.get("failed_attempt_preserved")) == "TRUE", "Failed attempt must be preserved")


def test_v46_candidate_universe_prevents_empty_universe_blocker() -> None:
    v46_path = CONSOLIDATION / "V20_46_CANDIDATE_REFRESH_UNIVERSE.csv"
    if not v46_path.exists():
        return
    v46_rows = read_csv(v46_path)
    candidate_count = sum(1 for row in v46_rows if clean(row.get("universe_role")) == "candidate")
    if candidate_count == 0:
        return
    summary_rows = read_csv(CONSOLIDATION / "V20_47_CONTROLLED_REFRESH_SUMMARY.csv")
    audit_rows = read_csv(CONSOLIDATION / "V20_47_PROVIDER_REFRESH_AUDIT.csv")
    failure_rows = read_csv(CONSOLIDATION / "V20_47_LAST_FAILED_REFRESH_ATTEMPT.csv")
    if summary_rows:
        assert_true(clean(summary_rows[0].get("candidate_tickers_requested")) != "0", "V20.47 requested zero candidates despite V20.46 universe")
    if failure_rows:
        assert_true(clean(failure_rows[0].get("candidate_tickers_requested")) != "0", "Failed attempt requested zero candidates despite V20.46 universe")
    joined_reasons = ";".join(clean(row.get("failure_reason") or row.get("provider_error_message")) for row in audit_rows)
    assert_true("candidate_ticker_universe_empty" not in joined_reasons, "V20.47 still reports candidate_ticker_universe_empty")


def test_provider_refresh_diagnostics_contract_when_present() -> None:
    if not PROVIDER_DIAGNOSTICS.exists() or not PROVIDER_SUMMARY.exists():
        return
    diag_rows = read_csv(PROVIDER_DIAGNOSTICS)
    summary_rows = read_csv(PROVIDER_SUMMARY)
    assert_true(diag_rows, "Provider diagnostics must be non-empty")
    assert_true(summary_rows, "Provider summary must be non-empty")
    summary = summary_rows[0]
    assert_true(int(clean(summary.get("requested_ticker_count")) or "0") > 0, "Provider summary requested count must be > 0")
    if clean(summary.get("provider_available")).upper() in {"TRUE", "FALSE"}:
        assert_true(clean(summary.get("attempted_ticker_count")) != "0", "Provider summary attempted count must be > 0 when V20.46 is ready")
    required_diag = {
        "ticker",
        "normalized_provider_ticker",
        "ticker_source",
        "provider_name",
        "request_period_or_window",
        "raw_rows_returned",
        "normalized_rows_returned",
        "latest_price_date",
        "latest_close",
        "cache_file_path",
        "cache_rows_before",
        "cache_rows_after",
        "refresh_status",
        "failure_reason",
        "exception_type",
        "exception_message",
    }
    assert_true(required_diag.issubset(diag_rows[0]), "Provider diagnostics missing required ticker-level fields")
    if clean(summary.get("empty_dataframe_count")) not in {"", "0"}:
        assert_true(any(clean(row.get("failure_reason")) == "empty_dataframe" for row in diag_rows), "empty_dataframe must be reported at ticker level")
    if clean(summary.get("exception_count")) not in {"", "0"}:
        assert_true(any(clean(row.get("exception_type")) for row in diag_rows), "Provider exceptions must not be swallowed silently")
    if clean(summary.get("success_count")) == "0":
        v47_summary = read_csv(CONSOLIDATION / "V20_47_CONTROLLED_REFRESH_SUMMARY.csv")
        if v47_summary:
            cert_status = clean(v47_summary[0].get("certification_status"))
            fallback_used = clean(v47_summary[0].get("fallback_used"))
            assert_true(
                cert_status == BLOCKED_CERT_STATUS or (cert_status == FALLBACK_CERTIFIED_STATUS and fallback_used == "TRUE"),
                "Zero live-provider success may only block or use explicit certified-cache fallback",
            )


def test_certified_cache_fallback_contract_when_present() -> None:
    path = CONSOLIDATION / "V20_47_CERTIFIED_CACHE_FALLBACK_AUDIT.csv"
    if not path.exists():
        return
    rows = read_csv(path)
    assert_true(rows, "Fallback audit must be non-empty")
    row = rows[0]
    required = {
        "fallback_status",
        "fallback_used",
        "fallback_source_file",
        "fallback_source_run_id",
        "latest_price_date",
        "cache_age_days",
        "ticker_count_requested",
        "ticker_count_success",
        "missing_ticker_count",
        "certification_status",
        "handoff_allowed",
        "research_only",
        "official_recommendation_created",
        "weight_mutated",
        "trade_action_created",
    }
    assert_true(required.issubset(row), "Fallback audit missing required fields")
    if clean(row.get("fallback_used")) == "TRUE":
        assert_true(clean(row.get("fallback_status")) == FALLBACK_CERTIFIED_STATUS, "Fallback used with wrong status")
        assert_true(clean(row.get("handoff_allowed")) == "TRUE", "Fallback handoff not allowed")
        assert_true(clean(row.get("fallback_source_file")).endswith(".csv"), "Fallback source file missing")
        assert_true(int(clean(row.get("ticker_count_success")) or "0") > 0, "Fallback has no ticker rows")
    assert_true(clean(row.get("research_only")) == "TRUE", "Fallback must be research-only")
    assert_true(clean(row.get("official_recommendation_created")) == "FALSE", "Fallback created official recommendation")
    assert_true(clean(row.get("weight_mutated")) == "FALSE", "Fallback mutated weights")
    assert_true(clean(row.get("trade_action_created")) == "FALSE", "Fallback created trade action")


def cleanup_pycache() -> None:
    for path in SCRIPT_DIR.rglob("__pycache__"):
        if path.is_dir():
            shutil.rmtree(path)


def main() -> int:
    tests = [
        test_close_only_dataframe_extracts_valid_close,
        test_adj_close_only_dataframe_extracts_valid_adjusted_close,
        test_multiindex_price_ticker_layout_extracts_valid_ticker_close,
        test_multiindex_ticker_price_layout_extracts_valid_ticker_close,
        test_auto_adjust_style_close_present_certifies,
        test_empty_dataframe_fails_gracefully,
        test_certification_requires_latest_price_date_and_selected_field,
        test_provider_cache_diagnostics_and_cache_db_error_capture,
        test_missing_close_like_fields_fail_gracefully,
        test_candidate_partial_failure_does_not_block_research_handoff,
        test_benchmark_failure_blocks_stage,
        test_no_forbidden_output_paths_are_created,
        test_safety_boundary_flags_remain_pass_when_artifact_exists,
        test_wrapper_reports_accepted_statuses_and_exit_policy,
        test_static_safety_scans,
        test_no_forbidden_path_literals,
        test_current_artifacts_accept_pass_or_partial_handoff,
        test_promotion_semantics_are_guarded_by_accepted_handoff,
        test_failed_attempt_artifact_contract_when_present,
        test_v46_candidate_universe_prevents_empty_universe_blocker,
        test_provider_refresh_diagnostics_contract_when_present,
        test_certified_cache_fallback_contract_when_present,
    ]
    failures: list[str] = []
    for test in tests:
        try:
            test()
        except Exception as exc:
            failures.append(f"{test.__name__}: {exc}")
    cleanup_pycache()
    if failures:
        for failure in failures:
            print(f"FAIL_DETAIL: {failure}")
        print("FAIL_V20_47_TESTS")
        return 1
    print(PASS_STATUS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
