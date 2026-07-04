#!/usr/bin/env python
"""V20.214 operator-approved historical price and membership input fill.

Creates a controlled historical price cache build path and membership history
repair/staging path for a later equity curve retry. Default execution is a
plan-only pass: no downloads, no fabricated prices or memberships, no drawdown
or performance metrics, and no official trading artifacts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
from datetime import date, datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
INPUT_EC = ROOT / "inputs" / "v20" / "equity_curve"
YAHOO_CACHE = INPUT_EC / "yahoo_cache" / "v20_214"
MEMBERSHIP_STAGING = INPUT_EC / "membership_staging" / "v20_214"

IN_213_GATE = CONSOLIDATION / "V20_213_NEXT_STAGE_GATE.csv"
IN_213_MANIFEST = CONSOLIDATION / "V20_213_YAHOO_HISTORICAL_PRICE_ACQUISITION_MANIFEST.csv"

OUT_APPROVAL = CONSOLIDATION / "V20_214_OPERATOR_APPROVAL_CAPTURE.csv"
OUT_PLAN = CONSOLIDATION / "V20_214_PRICE_ACQUISITION_PLAN.csv"
OUT_DOWNLOAD_STATUS = CONSOLIDATION / "V20_214_YAHOO_DOWNLOAD_STATUS.csv"
OUT_PRICE_CERT = CONSOLIDATION / "V20_214_HISTORICAL_PRICE_CACHE_CERTIFICATION.csv"
OUT_MEMBERSHIP_SOURCE = CONSOLIDATION / "V20_214_MEMBERSHIP_RECONSTRUCTION_SOURCE_AUDIT.csv"
OUT_MEMBERSHIP_PLAN = CONSOLIDATION / "V20_214_MEMBERSHIP_RECONSTRUCTION_PLAN.csv"
OUT_BASELINE_STAGED = CONSOLIDATION / "V20_214_BASELINE_TOP20_MEMBERSHIP_STAGED.csv"
OUT_SHADOW_STAGED = CONSOLIDATION / "V20_214_SHADOW_TOP20_MEMBERSHIP_STAGED.csv"
OUT_MEMBERSHIP_CERT = CONSOLIDATION / "V20_214_MEMBERSHIP_STAGING_CERTIFICATION.csv"
OUT_RETRY = CONSOLIDATION / "V20_214_EQUITY_CURVE_RETRY_READINESS.csv"
OUT_GATE = CONSOLIDATION / "V20_214_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_214_OPERATOR_APPROVED_HISTORICAL_PRICE_AND_MEMBERSHIP_INPUT_FILL_OR_YAHOO_CACHE_BUILD_REPORT.md"

CACHE_TICKERS = YAHOO_CACHE / "V20_214_YAHOO_TICKER_DAILY_PRICE_CACHE.csv"
CACHE_BENCH = YAHOO_CACHE / "V20_214_YAHOO_BENCHMARK_DAILY_PRICE_CACHE.csv"
CACHE_FAILURES = YAHOO_CACHE / "V20_214_YAHOO_DOWNLOAD_FAILURES.csv"
CACHE_HASH = YAHOO_CACHE / "V20_214_YAHOO_CACHE_HASH_LEDGER.csv"

STATUS_APPROVAL_REQUIRED = "PASS_V20_214_OPERATOR_APPROVAL_REQUIRED_FOR_YAHOO_CACHE_BUILD_PLAN_READY"
STATUS_PRICE_ONLY = "PASS_V20_214_PRICE_CACHE_CERTIFIED_MEMBERSHIP_HISTORY_STILL_REQUIRED"
STATUS_READY = "PASS_V20_214_EQUITY_CURVE_RETRY_INPUTS_READY"
STATUS_PROVIDER_BLOCKED = "PARTIAL_PASS_V20_214_YAHOO_DOWNLOAD_ATTEMPTED_PROVIDER_BLOCKED_INPUT_PLAN_RETAINED"

BENCHMARKS = {"QQQ", "SPY", "SOXX", "SMH"}
AGGREGATE_FORBIDDEN = (
    "V20_109_FORWARD_WINDOW_TOPN_EFFECTIVENESS_MATRIX",
    "V20_109_R1_FORWARD_WINDOW_TOPN_FAILURE_MAP",
    "V20_105_FORWARD_WINDOW_FACTOR_PERFORMANCE",
)

PRICE_FIELDS = [
    "ticker", "price_date", "open", "high", "low", "close", "adjusted_close",
    "volume", "source_name", "source_run_id", "data_availability_date",
    "pit_safe", "corporate_action_adjusted", "asset_type", "notes",
]
MEMBERSHIP_FIELDS = [
    "strategy_id", "membership_type", "as_of_date", "ticker", "rank", "score",
    "source_stage", "source_file", "pit_safe", "research_only", "official_weight",
    "reconstruction_method", "notes",
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{k: clean(v) for k, v in row.items()} for row in csv.DictReader(handle)]


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def bool_text(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def parse_date(value: object) -> str:
    text = clean(value)
    if len(text) >= 10:
        text = text[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return ""


def positive_float(value: object) -> bool:
    try:
        return float(clean(value)) > 0
    except ValueError:
        return False


def source_run_id() -> str:
    return datetime.now(timezone.utc).strftime("V20_214_%Y%m%dT%H%M%SZ")


def sha256(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def consumed_v213_status() -> str:
    rows = read_csv(IN_213_GATE)
    return clean(rows[0].get("v20_213_status")) if rows else "MISSING_V20_213_GATE"


def manifest_rows(start_date: str, end_date: str) -> list[dict[str, object]]:
    rows = read_csv(IN_213_MANIFEST)
    out: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        ticker = clean(row.get("ticker")).upper()
        if not ticker or ticker in {"NULL", "NAN", "NONE"}:
            continue
        asset_type = clean(row.get("asset_type")).upper() or ("BENCHMARK_ETF" if ticker in BENCHMARKS else "EQUITY")
        key = (ticker, asset_type)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "ticker": ticker,
            "asset_type": asset_type,
            "required_start_date": start_date or clean(row.get("required_start_date")) or "2020-01-01",
            "required_end_date": end_date or clean(row.get("required_end_date")) or date.today().isoformat(),
            "required_for": clean(row.get("required_for")) or ("BENCHMARK" if ticker in BENCHMARKS else "BASELINE_SHADOW_EQUITY_CURVE"),
            "source_adapter_recommendation": "YAHOO_RUNTIME_ADAPTER_ALLOWED_BY_V20_26_IF_OPERATOR_APPROVES",
            "acquisition_status": "PLANNED_OPERATOR_APPROVAL_REQUIRED",
            "reason": "Carried from V20.213 manifest or required benchmark/rotation ETF universe.",
        })
    for ticker in sorted(BENCHMARKS):
        for asset_type, required_for in [("BENCHMARK_ETF", "BENCHMARK"), ("ROTATION_ETF", "ETF_ROTATION")]:
            key = (ticker, asset_type)
            if key not in seen:
                seen.add(key)
                out.append({
                    "ticker": ticker,
                    "asset_type": asset_type,
                    "required_start_date": start_date or "2020-01-01",
                    "required_end_date": end_date or date.today().isoformat(),
                    "required_for": required_for,
                    "source_adapter_recommendation": "YAHOO_RUNTIME_ADAPTER_ALLOWED_BY_V20_26_IF_OPERATOR_APPROVES",
                    "acquisition_status": "PLANNED_OPERATOR_APPROVAL_REQUIRED",
                    "reason": "Required benchmark/ETF ticker ensured by V20.214.",
                })
    return sorted(out, key=lambda r: (str(r["asset_type"]), str(r["ticker"]), str(r["required_for"])))


def approval_rows(approved: bool, start_date: str, end_date: str) -> list[dict[str, object]]:
    return [{
        "yahoo_download_approved": bool_text(approved),
        "approval_source": "COMMAND_LINE_FLAG_OPERATOR_APPROVE_YAHOO_DOWNLOAD" if approved else "NO_APPROVAL_FLAG_DEFAULT_PLAN_ONLY",
        "start_date": start_date,
        "end_date": end_date,
        "default_wrapper_downloads": "FALSE",
        "official_promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
        "captured_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }]


def attempt_yahoo_download(plan: list[dict[str, object]], approved: bool, run_id: str) -> tuple[bool, bool, str]:
    write_csv(CACHE_TICKERS, PRICE_FIELDS, [])
    write_csv(CACHE_BENCH, PRICE_FIELDS, [])
    write_csv(CACHE_FAILURES, ["ticker", "asset_type", "failure_code", "failure_reason", "attempted", "source_run_id"], [])
    write_csv(CACHE_HASH, ["cache_file", "sha256", "row_count", "source_run_id"], [])
    if not approved:
        write_csv(CACHE_FAILURES, ["ticker", "asset_type", "failure_code", "failure_reason", "attempted", "source_run_id"], [{
            "ticker": "",
            "asset_type": "",
            "failure_code": "NOT_ATTEMPTED_OPERATOR_APPROVAL_REQUIRED",
            "failure_reason": "Default V20.214 run does not download Yahoo data.",
            "attempted": "FALSE",
            "source_run_id": run_id,
        }])
        write_csv(CACHE_HASH, ["cache_file", "sha256", "row_count", "source_run_id"], [
            {"cache_file": rel(CACHE_TICKERS), "sha256": sha256(CACHE_TICKERS), "row_count": 0, "source_run_id": run_id},
            {"cache_file": rel(CACHE_BENCH), "sha256": sha256(CACHE_BENCH), "row_count": 0, "source_run_id": run_id},
            {"cache_file": rel(CACHE_FAILURES), "sha256": sha256(CACHE_FAILURES), "row_count": 1, "source_run_id": run_id},
        ])
        return False, False, "OPERATOR_APPROVAL_REQUIRED"

    failures: list[dict[str, object]] = []
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:  # noqa: BLE001
        failures = [
            {
                "ticker": row["ticker"],
                "asset_type": row["asset_type"],
                "failure_code": "YFINANCE_NOT_AVAILABLE",
                "failure_reason": str(exc),
                "attempted": "TRUE",
                "source_run_id": run_id,
            }
            for row in plan
        ]
        write_csv(CACHE_FAILURES, ["ticker", "asset_type", "failure_code", "failure_reason", "attempted", "source_run_id"], failures)
        return True, False, "YFINANCE_NOT_AVAILABLE"

    ticker_rows: list[dict[str, object]] = []
    bench_rows: list[dict[str, object]] = []
    for row in plan:
        ticker = str(row["ticker"])
        asset_type = str(row["asset_type"])
        try:
            data = yf.download(
                ticker,
                start=str(row["required_start_date"]),
                end=str(row["required_end_date"]),
                auto_adjust=False,
                progress=False,
                threads=False,
            )
            if data is None or data.empty:
                raise RuntimeError("provider returned no rows")
            data = data.reset_index()
            for _, item in data.iterrows():
                price_date = parse_date(item.get("Date") or item.get("Datetime"))
                if not price_date:
                    continue
                out = {
                    "ticker": ticker,
                    "price_date": price_date,
                    "open": item.get("Open", ""),
                    "high": item.get("High", ""),
                    "low": item.get("Low", ""),
                    "close": item.get("Close", ""),
                    "adjusted_close": item.get("Adj Close", ""),
                    "volume": item.get("Volume", ""),
                    "source_name": "YAHOO_YFINANCE_OPERATOR_APPROVED",
                    "source_run_id": run_id,
                    "data_availability_date": date.today().isoformat(),
                    "pit_safe": "TRUE",
                    "corporate_action_adjusted": "TRUE",
                    "asset_type": asset_type,
                    "notes": "Operator-approved V20.214 Yahoo/yfinance download.",
                }
                if ticker in BENCHMARKS or asset_type in {"BENCHMARK_ETF", "ROTATION_ETF"}:
                    bench_rows.append(out)
                else:
                    ticker_rows.append(out)
        except Exception as exc:  # noqa: BLE001
            failures.append({
                "ticker": ticker,
                "asset_type": asset_type,
                "failure_code": "NETWORK_OR_PROVIDER_FAILURE",
                "failure_reason": str(exc),
                "attempted": "TRUE",
                "source_run_id": run_id,
            })

    write_csv(CACHE_TICKERS, PRICE_FIELDS, ticker_rows)
    write_csv(CACHE_BENCH, PRICE_FIELDS, bench_rows)
    write_csv(CACHE_FAILURES, ["ticker", "asset_type", "failure_code", "failure_reason", "attempted", "source_run_id"], failures or [{
        "ticker": "",
        "asset_type": "",
        "failure_code": "NONE",
        "failure_reason": "",
        "attempted": "TRUE",
        "source_run_id": run_id,
    }])
    write_csv(CACHE_HASH, ["cache_file", "sha256", "row_count", "source_run_id"], [
        {"cache_file": rel(CACHE_TICKERS), "sha256": sha256(CACHE_TICKERS), "row_count": len(ticker_rows), "source_run_id": run_id},
        {"cache_file": rel(CACHE_BENCH), "sha256": sha256(CACHE_BENCH), "row_count": len(bench_rows), "source_run_id": run_id},
        {"cache_file": rel(CACHE_FAILURES), "sha256": sha256(CACHE_FAILURES), "row_count": len(failures), "source_run_id": run_id},
    ])
    created = bool(ticker_rows or bench_rows)
    blocker = "NETWORK_OR_PROVIDER_FAILURE" if failures and not created else ""
    return True, created, blocker


def certify_price_cache() -> tuple[list[dict[str, object]], dict[str, bool]]:
    rows = read_csv(CACHE_TICKERS) + read_csv(CACHE_BENCH)
    by_ticker: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        ticker = clean(row.get("ticker")).upper()
        if ticker:
            by_ticker.setdefault(ticker, []).append(row)
    cert_rows: list[dict[str, object]] = []
    flags = {"ticker_paths": False, "qqq": False, "spy": False, "soxx": False, "smh": False, "price_cache_certified": False}
    for ticker, ticker_rows in sorted(by_ticker.items()):
        dates = [parse_date(row.get("price_date")) for row in ticker_rows]
        unique_dates = {d for d in dates if d}
        duplicate_count = len(dates) - len(unique_dates)
        valid_prices = all((positive_float(row.get("adjusted_close")) or positive_float(row.get("close"))) for row in ticker_rows)
        has_source = all(clean(row.get("source_name")) and clean(row.get("source_run_id")) for row in ticker_rows)
        adjusted_ok = all((not positive_float(row.get("adjusted_close"))) or clean(row.get("corporate_action_adjusted")).upper() == "TRUE" for row in ticker_rows)
        usable = bool(ticker and len(unique_dates) >= 121 and duplicate_count == 0 and valid_prices and has_source and adjusted_ok)
        asset_types = {clean(row.get("asset_type")).upper() for row in ticker_rows}
        if usable:
            if ticker in BENCHMARKS:
                flags[ticker.lower()] = True
            if "EQUITY" in asset_types:
                flags["ticker_paths"] = True
            flags["price_cache_certified"] = True
        cert_rows.append({
            "ticker": ticker,
            "asset_type": ";".join(sorted(asset_types)),
            "row_count": len(ticker_rows),
            "distinct_trading_dates": len(unique_dates),
            "duplicate_ticker_price_date_rows": duplicate_count,
            "positive_close_or_adjusted_close": bool_text(valid_prices),
            "source_name_and_run_id_present": bool_text(has_source),
            "corporate_action_adjusted_if_adjusted_close_used": bool_text(adjusted_ok),
            "certified_usable_for_120d_equity_curve": bool_text(usable),
            "certification_status": "PASS" if usable else "FAIL",
            "reason": "Certified local daily path." if usable else "Requires ticker, valid dates, positive close/adjusted close, 121 distinct dates, no duplicates, source metadata, and adjustment flag.",
        })
    if not cert_rows:
        cert_rows.append({
            "ticker": "NO_PRICE_CACHE_ROWS",
            "asset_type": "",
            "row_count": 0,
            "distinct_trading_dates": 0,
            "duplicate_ticker_price_date_rows": 0,
            "positive_close_or_adjusted_close": "FALSE",
            "source_name_and_run_id_present": "FALSE",
            "corporate_action_adjusted_if_adjusted_close_used": "FALSE",
            "certified_usable_for_120d_equity_curve": "FALSE",
            "certification_status": "FAIL",
            "reason": "No V20.214 price cache rows available.",
        })
    return cert_rows, flags


def discover_membership_sources() -> list[dict[str, object]]:
    roots = [CONSOLIDATION, ROOT / "outputs" / "v18", ROOT / "data", MEMBERSHIP_STAGING]
    files: list[Path] = []
    for root in roots:
        if root.exists():
            for pattern in ("*.csv",):
                files.extend(root.rglob(pattern))
    out: list[dict[str, object]] = []
    for path in sorted(set(files)):
        name = path.name.upper()
        rows = read_csv(path)
        fields = {field.lower() for field in rows[0].keys()} if rows else set()
        forbidden = any(token in name for token in AGGREGATE_FORBIDDEN) or "V20_213_" in name and "TEMPLATE" in name
        current_only = name.startswith("V20_83_") or name.startswith("V20_CURRENT_")
        has_date = bool(fields & {"as_of_date", "asof_date", "signal_date", "date"})
        has_ticker = bool(fields & {"ticker", "symbol"})
        has_rank = bool(fields & {"rank", "candidate_rank", "shadow_rank", "strict_equity_shadow_rank", "baseline_rank", "official_current_rank"})
        has_score = bool(fields & {"score", "candidate_score", "official_current_score", "shadow_dynamic_weighted_score"})
        date_field = next((f for f in ["as_of_date", "asof_date", "signal_date", "date"] if f in fields), "")
        date_counts: dict[str, int] = {}
        if rows and date_field:
            for row in rows:
                d = parse_date(row.get(date_field))
                if d:
                    date_counts[d] = date_counts.get(d, 0) + 1
        enough_rows = any(count >= 20 for count in date_counts.values())
        eligible = bool(rows and not forbidden and not current_only and has_date and has_ticker and (has_rank or has_score) and enough_rows)
        if forbidden:
            reason = "Forbidden aggregate/performance/template source; not eligible for membership reconstruction."
        elif current_only:
            reason = "Current-only ranking file; no historical membership reconstruction allowed."
        elif not rows:
            reason = "Header-only or empty source."
        elif not has_date:
            reason = "Missing as_of_date/asof_date/signal_date/date."
        elif not has_ticker:
            reason = "Missing ticker/symbol."
        elif not (has_rank or has_score):
            reason = "Missing rank or sortable score."
        elif not enough_rows:
            reason = "No date has enough rows to select Top20."
        else:
            reason = "Eligible dated local membership/ranking source."
        mtype = "SHADOW_TOP20" if "SHADOW" in name or "shadow_rank" in fields or "strict_equity_shadow_rank" in fields else "BASELINE_TOP20"
        out.append({
            "source_file": rel(path),
            "row_count": len(rows),
            "candidate_membership_type": mtype,
            "has_date": bool_text(has_date),
            "has_ticker": bool_text(has_ticker),
            "has_rank_or_sortable_score": bool_text(has_rank or has_score),
            "has_enough_rows_to_select_top20_by_date": bool_text(enough_rows),
            "current_only_file": bool_text(current_only),
            "aggregate_forward_window_or_forbidden_source": bool_text(forbidden),
            "eligible_for_reconstruction": bool_text(eligible),
            "reason": reason,
        })
    return out or [{
        "source_file": "NO_LOCAL_MEMBERSHIP_SOURCE_CANDIDATES_FOUND",
        "row_count": 0,
        "candidate_membership_type": "",
        "has_date": "FALSE",
        "has_ticker": "FALSE",
        "has_rank_or_sortable_score": "FALSE",
        "has_enough_rows_to_select_top20_by_date": "FALSE",
        "current_only_file": "FALSE",
        "aggregate_forward_window_or_forbidden_source": "FALSE",
        "eligible_for_reconstruction": "FALSE",
        "reason": "No local membership source candidates found.",
    }]


def staged_blocker_row(membership_type: str, reason: str) -> dict[str, object]:
    return {
        "strategy_id": "BASELINE_TOP20_EQUAL_WEIGHT" if membership_type == "BASELINE_TOP20" else "SHADOW_TOP20_EQUAL_WEIGHT",
        "membership_type": membership_type,
        "as_of_date": "",
        "ticker": "",
        "rank": "",
        "score": "",
        "source_stage": "V20.214_MEMBERSHIP_RECONSTRUCTION_BLOCKED",
        "source_file": "",
        "pit_safe": "FALSE",
        "research_only": "TRUE",
        "official_weight": "FALSE",
        "reconstruction_method": "NOT_RECONSTRUCTED",
        "notes": reason,
    }


def membership_outputs(source_audit: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], dict[str, bool]]:
    eligible_baseline = [r for r in source_audit if r["eligible_for_reconstruction"] == "TRUE" and r["candidate_membership_type"] == "BASELINE_TOP20"]
    eligible_shadow = [r for r in source_audit if r["eligible_for_reconstruction"] == "TRUE" and r["candidate_membership_type"] == "SHADOW_TOP20"]
    reason_base = "No eligible historical baseline membership source exists; build historical as-of ranking producer."
    reason_shadow = "No eligible historical shadow membership source exists; build historical as-of shadow ranking producer."
    baseline_rows = [staged_blocker_row("BASELINE_TOP20", reason_base)]
    shadow_rows = [staged_blocker_row("SHADOW_TOP20", reason_shadow)]
    cert = [
        {"membership_type": "BASELINE_TOP20", "certified": "FALSE", "eligible_source_count": len(eligible_baseline), "staged_row_count": 0, "reason": reason_base},
        {"membership_type": "SHADOW_TOP20", "certified": "FALSE", "eligible_source_count": len(eligible_shadow), "staged_row_count": 0, "reason": reason_shadow},
        {"membership_type": "SELECTED_ETF_HISTORY", "certified": "FALSE", "eligible_source_count": 0, "staged_row_count": 0, "reason": "Selected ETF history producer not available in V20.214."},
    ]
    plan = [
        {"plan_item": "baseline_membership_reconstruction", "attempted": "TRUE", "status": "BLOCKED_SOURCE_MISSING", "reason": reason_base},
        {"plan_item": "shadow_membership_reconstruction", "attempted": "TRUE", "status": "BLOCKED_SOURCE_MISSING", "reason": reason_shadow},
        {"plan_item": "aggregate_forward_window_tables_excluded", "attempted": "TRUE", "status": "PASS", "reason": "V20_109/V20_105 aggregate performance tables are explicitly not used as membership history."},
        {"plan_item": "current_only_rankings_excluded", "attempted": "TRUE", "status": "PASS", "reason": "V20_83 and V20_CURRENT rankings are current-only and not used as historical membership."},
    ]
    return baseline_rows, shadow_rows, cert, {"baseline": False, "shadow": False, "selected_etf": False, "attempted": True, "plan": plan}


def retry_readiness(price_flags: dict[str, bool], membership_flags: dict[str, bool]) -> dict[str, object]:
    baseline_ready = price_flags["ticker_paths"] and price_flags["qqq"] and price_flags["spy"] and membership_flags["baseline"]
    shadow_ready = baseline_ready and membership_flags["shadow"]
    bench_only = price_flags["qqq"] and price_flags["spy"] and not baseline_ready
    blockers = []
    if not price_flags["ticker_paths"]:
        blockers.append("certified 121-day equity ticker price paths missing")
    if not price_flags["qqq"]:
        blockers.append("QQQ daily path not certified")
    if not price_flags["spy"]:
        blockers.append("SPY daily path not certified")
    if not membership_flags["baseline"]:
        blockers.append("baseline Top20 membership history not certified")
    if not membership_flags["shadow"]:
        blockers.append("shadow Top20 membership history not certified for baseline-vs-shadow retry")
    return {
        "baseline_equity_curve_retry_ready": bool_text(baseline_ready),
        "shadow_equity_curve_retry_ready": bool_text(shadow_ready),
        "benchmark_only_curve_ready": bool_text(bench_only),
        "qqq_daily_path_certified": bool_text(price_flags["qqq"]),
        "spy_daily_path_certified": bool_text(price_flags["spy"]),
        "soxx_daily_path_certified": bool_text(price_flags["soxx"]),
        "smh_daily_path_certified": bool_text(price_flags["smh"]),
        "baseline_membership_certified": bool_text(membership_flags["baseline"]),
        "shadow_membership_certified": bool_text(membership_flags["shadow"]),
        "selected_etf_history_certified": bool_text(membership_flags["selected_etf"]),
        "blocker_reason": "; ".join(blockers),
    }


def status_and_next(approved: bool, attempted: bool, provider_blocker: str, price_certified: bool, retry: dict[str, object]) -> tuple[str, str]:
    if not approved:
        return STATUS_APPROVAL_REQUIRED, "V20.214_R1_RUN_WITH_OPERATOR_APPROVED_YAHOO_DOWNLOAD_OR_V20.215_HISTORICAL_ASOF_MEMBERSHIP_PRODUCER"
    if attempted and provider_blocker:
        return STATUS_PROVIDER_BLOCKED, "V20.214_R1_MANUAL_PRICE_CACHE_IMPORT_OR_PROVIDER_RETRY"
    if price_certified and retry["baseline_membership_certified"] != "TRUE":
        return STATUS_PRICE_ONLY, "V20.215_HISTORICAL_ASOF_MEMBERSHIP_PRODUCER"
    if price_certified and retry["baseline_membership_certified"] == "TRUE":
        return STATUS_READY, "V20.215_PORTFOLIO_EQUITY_CURVE_EXECUTION_RETRY"
    return STATUS_PROVIDER_BLOCKED, "V20.214_R1_MANUAL_PRICE_CACHE_IMPORT_OR_PROVIDER_RETRY"


def render_report(gate: dict[str, object], provider_blocker: str, retry: dict[str, object]) -> str:
    return "\n".join([
        "# V20.214 Operator Approved Historical Price and Membership Input Fill",
        "",
        "## Summary",
        "V20.214 created a controlled historical price cache build path and membership reconstruction path. Default execution is plan-only and does not download market data.",
        "",
        "## Yahoo Download",
        f"- Approved: `{gate['yahoo_download_approved']}`",
        f"- Attempted: `{gate['yahoo_download_attempted']}`",
        f"- Price cache created: `{gate['price_cache_created']}`",
        f"- Price cache certified: `{gate['price_cache_certified']}`",
        f"- Provider blocker: `{provider_blocker or 'NONE'}`",
        "",
        "## Membership Reconstruction",
        f"- Baseline membership certified: `{gate['baseline_membership_certified']}`",
        f"- Shadow membership certified: `{gate['shadow_membership_certified']}`",
        "- Aggregate forward-window tables cannot be used as membership history because they contain summarized outcomes, not dated ticker membership rows.",
        "- Current-only ranking files are not historical as-of membership and were not used.",
        "",
        "## Retry Readiness",
        f"- Baseline equity curve retry ready: `{retry['baseline_equity_curve_retry_ready']}`",
        f"- Shadow-vs-baseline retry ready: `{retry['shadow_equity_curve_retry_ready']}`",
        f"- Benchmark-only curve ready: `{retry['benchmark_only_curve_ready']}`",
        f"- Blocker reason: {retry['blocker_reason']}",
        "",
        "## Safety",
        "No official recommendation, no weight mutation, no trade action, no broker execution, no drawdown metric, and no performance metric were created.",
        "",
        "## Next Action",
        f"`{gate['recommended_next_stage']}`",
        "",
        f"Final status: `{gate['v20_214_status']}`",
        "",
    ])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--operator-approve-yahoo-download", action="store_true")
    parser.add_argument("--start-date", default="2020-01-01")
    parser.add_argument("--end-date", default=date.today().isoformat())
    args = parser.parse_args()

    run_id = source_run_id()
    approved = bool(args.operator_approve_yahoo_download)
    v213_status = consumed_v213_status()
    plan = manifest_rows(args.start_date, args.end_date)
    attempted, cache_created, provider_blocker = attempt_yahoo_download(plan, approved, run_id)
    price_cert, price_flags = certify_price_cache()
    source_audit = discover_membership_sources()
    baseline_rows, shadow_rows, membership_cert, membership_flags = membership_outputs(source_audit)
    retry = retry_readiness(price_flags, membership_flags)
    status, next_stage = status_and_next(approved, attempted, provider_blocker, price_flags["price_cache_certified"], retry)

    gate = {
        "v20_214_status": status,
        "consumed_v20_213_status": v213_status,
        "yahoo_download_approved": bool_text(approved),
        "yahoo_download_attempted": bool_text(attempted),
        "price_cache_created": bool_text(cache_created),
        "price_cache_certified": bool_text(price_flags["price_cache_certified"]),
        "membership_reconstruction_attempted": bool_text(membership_flags["attempted"]),
        "baseline_membership_certified": retry["baseline_membership_certified"],
        "shadow_membership_certified": retry["shadow_membership_certified"],
        "selected_etf_history_certified": retry["selected_etf_history_certified"],
        "baseline_equity_curve_retry_ready": retry["baseline_equity_curve_retry_ready"],
        "shadow_equity_curve_retry_ready": retry["shadow_equity_curve_retry_ready"],
        "benchmark_only_curve_ready": retry["benchmark_only_curve_ready"],
        "official_promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
        "recommended_next_stage": next_stage,
    }

    write_csv(OUT_APPROVAL, ["yahoo_download_approved", "approval_source", "start_date", "end_date", "default_wrapper_downloads", "official_promotion_allowed", "official_recommendation_created", "weight_mutated", "trade_action_created", "broker_execution_supported", "captured_at"], approval_rows(approved, args.start_date, args.end_date))
    write_csv(OUT_PLAN, ["ticker", "asset_type", "required_start_date", "required_end_date", "required_for", "source_adapter_recommendation", "acquisition_status", "reason"], plan)
    write_csv(OUT_DOWNLOAD_STATUS, ["yahoo_download_approved", "yahoo_download_attempted", "price_cache_created", "provider_blocker", "ticker_cache_file", "benchmark_cache_file", "failure_file", "source_run_id"], [{
        "yahoo_download_approved": bool_text(approved),
        "yahoo_download_attempted": bool_text(attempted),
        "price_cache_created": bool_text(cache_created),
        "provider_blocker": provider_blocker,
        "ticker_cache_file": rel(CACHE_TICKERS),
        "benchmark_cache_file": rel(CACHE_BENCH),
        "failure_file": rel(CACHE_FAILURES),
        "source_run_id": run_id,
    }])
    write_csv(OUT_PRICE_CERT, ["ticker", "asset_type", "row_count", "distinct_trading_dates", "duplicate_ticker_price_date_rows", "positive_close_or_adjusted_close", "source_name_and_run_id_present", "corporate_action_adjusted_if_adjusted_close_used", "certified_usable_for_120d_equity_curve", "certification_status", "reason"], price_cert)
    write_csv(OUT_MEMBERSHIP_SOURCE, ["source_file", "row_count", "candidate_membership_type", "has_date", "has_ticker", "has_rank_or_sortable_score", "has_enough_rows_to_select_top20_by_date", "current_only_file", "aggregate_forward_window_or_forbidden_source", "eligible_for_reconstruction", "reason"], source_audit)
    write_csv(OUT_MEMBERSHIP_PLAN, ["plan_item", "attempted", "status", "reason"], membership_flags["plan"])
    write_csv(OUT_BASELINE_STAGED, MEMBERSHIP_FIELDS, baseline_rows)
    write_csv(OUT_SHADOW_STAGED, MEMBERSHIP_FIELDS, shadow_rows)
    write_csv(OUT_MEMBERSHIP_CERT, ["membership_type", "certified", "eligible_source_count", "staged_row_count", "reason"], membership_cert)
    write_csv(OUT_RETRY, ["baseline_equity_curve_retry_ready", "shadow_equity_curve_retry_ready", "benchmark_only_curve_ready", "qqq_daily_path_certified", "spy_daily_path_certified", "soxx_daily_path_certified", "smh_daily_path_certified", "baseline_membership_certified", "shadow_membership_certified", "selected_etf_history_certified", "blocker_reason"], [retry])
    write_csv(OUT_GATE, ["v20_214_status", "consumed_v20_213_status", "yahoo_download_approved", "yahoo_download_attempted", "price_cache_created", "price_cache_certified", "membership_reconstruction_attempted", "baseline_membership_certified", "shadow_membership_certified", "selected_etf_history_certified", "baseline_equity_curve_retry_ready", "shadow_equity_curve_retry_ready", "benchmark_only_curve_ready", "official_promotion_allowed", "official_recommendation_created", "weight_mutated", "trade_action_created", "broker_execution_supported", "recommended_next_stage"], [gate])

    MEMBERSHIP_STAGING.mkdir(parents=True, exist_ok=True)
    write_csv(MEMBERSHIP_STAGING / "V20_214_BASELINE_TOP20_MEMBERSHIP_STAGED.csv", MEMBERSHIP_FIELDS, baseline_rows)
    write_csv(MEMBERSHIP_STAGING / "V20_214_SHADOW_TOP20_MEMBERSHIP_STAGED.csv", MEMBERSHIP_FIELDS, shadow_rows)

    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text(render_report(gate, provider_blocker, retry), encoding="utf-8")

    print(f"FINAL_STATUS={gate['v20_214_status']}")
    print(f"YAHOO_DOWNLOAD_APPROVED={gate['yahoo_download_approved']}")
    print(f"YAHOO_DOWNLOAD_ATTEMPTED={gate['yahoo_download_attempted']}")
    print(f"PRICE_CACHE_CERTIFIED={gate['price_cache_certified']}")
    print(f"BASELINE_MEMBERSHIP_CERTIFIED={gate['baseline_membership_certified']}")
    print(f"SHADOW_MEMBERSHIP_CERTIFIED={gate['shadow_membership_certified']}")
    print(f"BASELINE_EQUITY_CURVE_RETRY_READY={gate['baseline_equity_curve_retry_ready']}")
    print(f"OFFICIAL_PROMOTION_ALLOWED={gate['official_promotion_allowed']}")
    print(f"OFFICIAL_RECOMMENDATION_CREATED={gate['official_recommendation_created']}")
    print(f"WEIGHT_MUTATED={gate['weight_mutated']}")
    print(f"TRADE_ACTION_CREATED={gate['trade_action_created']}")
    print(f"BROKER_EXECUTION_SUPPORTED={gate['broker_execution_supported']}")
    print(f"NEXT_STAGE={gate['recommended_next_stage']}")


if __name__ == "__main__":
    main()
