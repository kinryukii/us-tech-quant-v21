#!/usr/bin/env python
"""V20.213 daily price path source repair or equity curve input staging.

Stages strict input schemas and templates for a future portfolio equity curve
retry, discovers local-only membership and price sources, and certifies only
real local paths. Default execution never calls external APIs and never
fabricates prices, membership histories, drawdowns, or portfolio metrics.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
INPUT_EC = ROOT / "inputs" / "v20" / "equity_curve"
INPUT_BENCH = ROOT / "inputs" / "v20" / "outcome_benchmark"

IN_212_GATE = CONSOLIDATION / "V20_212_NEXT_STAGE_GATE.csv"
IN_212_AUDIT = CONSOLIDATION / "V20_212_DATA_AVAILABILITY_AUDIT.csv"

OUT_BLOCKER = CONSOLIDATION / "V20_213_V20_212_BLOCKER_INTAKE.csv"
OUT_MEMBERSHIP_DISCOVERY = CONSOLIDATION / "V20_213_MEMBERSHIP_SOURCE_DISCOVERY.csv"
OUT_PRICE_DISCOVERY = CONSOLIDATION / "V20_213_DAILY_PRICE_SOURCE_DISCOVERY.csv"
OUT_SCHEMA = CONSOLIDATION / "V20_213_EQUITY_CURVE_REQUIRED_INPUT_SCHEMA.csv"
OUT_STAGING = CONSOLIDATION / "V20_213_EQUITY_CURVE_INPUT_STAGING_STATUS.csv"
OUT_YAHOO_MANIFEST = CONSOLIDATION / "V20_213_YAHOO_HISTORICAL_PRICE_ACQUISITION_MANIFEST.csv"
OUT_PRICE_CERT = CONSOLIDATION / "V20_213_PRICE_PATH_CERTIFICATION_AUDIT.csv"
OUT_MEMBERSHIP_CERT = CONSOLIDATION / "V20_213_MEMBERSHIP_CERTIFICATION_AUDIT.csv"
OUT_ETF_CONTRACT = CONSOLIDATION / "V20_213_ETF_ROTATION_HISTORY_STAGING_CONTRACT.csv"
OUT_GATE = CONSOLIDATION / "V20_213_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_213_DAILY_PRICE_PATH_SOURCE_REPAIR_OR_EQUITY_CURVE_INPUT_STAGING_REPORT.md"

TEMPLATE_BASELINE = INPUT_EC / "V20_213_BASELINE_TOP20_MEMBERSHIP_INPUT_TEMPLATE.csv"
TEMPLATE_SHADOW = INPUT_EC / "V20_213_SHADOW_TOP20_MEMBERSHIP_INPUT_TEMPLATE.csv"
TEMPLATE_PRICE = INPUT_EC / "V20_213_DAILY_PRICE_PATH_INPUT_TEMPLATE.csv"
TEMPLATE_BENCH = INPUT_EC / "V20_213_BENCHMARK_DAILY_PRICE_PATH_INPUT_TEMPLATE.csv"
TEMPLATE_ETF = INPUT_EC / "V20_213_SELECTED_ETF_HISTORY_INPUT_TEMPLATE.csv"
TEMPLATES = [TEMPLATE_BASELINE, TEMPLATE_SHADOW, TEMPLATE_PRICE, TEMPLATE_BENCH, TEMPLATE_ETF]

STATUS_READY = "PASS_V20_213_EQUITY_CURVE_INPUTS_STAGED_AND_READY_FOR_RETRY"
STATUS_COLLECTION = "PASS_V20_213_EQUITY_CURVE_INPUT_STAGING_CONTRACT_READY_DATA_COLLECTION_REQUIRED"
BENCHMARKS = ["QQQ", "SPY", "SOXX", "SMH"]

MEMBERSHIP_FIELDS = [
    "strategy_id", "membership_type", "as_of_date", "ticker", "rank", "score",
    "source_stage", "source_file", "pit_safe", "research_only", "official_weight", "notes",
]
PRICE_FIELDS = [
    "ticker", "price_date", "close", "adjusted_close", "volume", "source_name",
    "source_file", "source_run_id", "data_availability_date", "pit_safe",
    "corporate_action_adjusted", "notes",
]
BENCH_FIELDS = [
    "benchmark_ticker", "price_date", "close", "adjusted_close", "volume", "source_name",
    "source_file", "source_run_id", "data_availability_date", "pit_safe",
    "corporate_action_adjusted", "notes",
]
ETF_FIELDS = [
    "as_of_date", "selected_etf", "selection_rule", "regime_classification",
    "leverage_allowed", "source_stage", "source_file", "pit_safe", "research_only", "notes",
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


def is_true(value: object) -> bool:
    return clean(value).upper() == "TRUE"


def as_int(value: object) -> int:
    try:
        return int(float(clean(value)))
    except ValueError:
        return 0


def row_count(path: Path) -> int:
    if path.suffix.lower() != ".csv":
        return 0
    return len(read_csv(path))


def discover_local_files(roots: list[Path], terms: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for suffix in ("*.csv", "*.json", "*.parquet", "*.md"):
            for path in root.rglob(suffix):
                name = path.name.lower()
                if any(term in name for term in terms):
                    files.append(path)
    return sorted(set(files))


def parse_date_text(value: object) -> str:
    text = clean(value)
    if len(text) >= 10:
        return text[:10]
    return ""


def count_dates(rows: list[dict[str, str]], date_fields: list[str]) -> int:
    dates = set()
    for row in rows:
        for field in date_fields:
            text = parse_date_text(row.get(field))
            if text:
                dates.add(text)
                break
    return len(dates)


def symbol_for(row: dict[str, str]) -> str:
    return clean(row.get("ticker") or row.get("symbol") or row.get("benchmark_ticker")).upper()


def fields_lower(rows: list[dict[str, str]]) -> set[str]:
    return {field.lower() for field in rows[0].keys()} if rows else set()


def consume_v212_blockers() -> tuple[str, list[dict[str, object]]]:
    gate_rows = read_csv(IN_212_GATE)
    audit_rows = read_csv(IN_212_AUDIT)
    status = clean(gate_rows[0].get("v20_212_status")) if gate_rows else "MISSING_V20_212_GATE"
    rows: list[dict[str, object]] = []
    if audit_rows:
        for row in audit_rows:
            if clean(row.get("available")).upper() == "FALSE":
                rows.append({
                    "consumed_v20_212_status": status,
                    "blocker_item": row.get("audit_item", ""),
                    "requirement": row.get("requirement", ""),
                    "blocker_reason": row.get("blocker_reason", ""),
                    "intake_status": "CONSUMED",
                })
    else:
        rows.append({
            "consumed_v20_212_status": status,
            "blocker_item": "V20_212_DATA_AVAILABILITY_AUDIT",
            "requirement": "V20.212 blocker audit must exist for exact intake.",
            "blocker_reason": "V20.212 audit missing or empty.",
            "intake_status": "MISSING_SOURCE_AUDIT",
        })
    return status, rows


def membership_discovery() -> list[dict[str, object]]:
    roots = [CONSOLIDATION, READ_CENTER, ROOT / "outputs" / "v18", ROOT / "data", INPUT_EC]
    files = discover_local_files(roots, ("membership", "ranking", "rerank", "top20", "selection"))
    rows: list[dict[str, object]] = []
    for path in files:
        csv_rows = read_csv(path) if path.suffix.lower() == ".csv" else []
        fields = fields_lower(csv_rows)
        header_only = path.suffix.lower() == ".csv" and not csv_rows
        has_date = bool(fields & {"as_of_date", "asof_date", "signal_date"})
        has_ticker = bool(fields & {"ticker", "symbol"})
        has_rank = bool(fields & {"rank", "candidate_rank", "baseline_rank", "official_current_rank", "asof_technical_rank"})
        has_shadow_rank = bool(fields & {"strict_equity_shadow_rank", "shadow_rank"})
        membership_type = "UNKNOWN"
        name = path.name.upper()
        if "SHADOW" in name or has_shadow_rank:
            membership_type = "SHADOW_TOP20"
        elif "BASELINE" in name or "TOP20" in name or "RANKING" in name:
            membership_type = "BASELINE_TOP20"
        is_v213_template = path.parent.resolve() == INPUT_EC.resolve() and path.name.startswith("V20_213_") and "TEMPLATE" in path.name.upper()
        date_count = count_dates(csv_rows, ["as_of_date", "asof_date", "signal_date", "ranking_timestamp_utc"])
        top20_like = "TOP20" in name or any(as_int(row.get("rank") or row.get("candidate_rank") or row.get("baseline_rank") or row.get("official_current_rank") or row.get("asof_technical_rank")) <= 20 for row in csv_rows[:50])
        usable = bool(csv_rows and has_date and has_ticker and (has_rank or has_shadow_rank) and top20_like and not is_v213_template)
        reason = ""
        if is_v213_template:
            reason = "V20.213 user-fillable template; staging artifact only, not certified historical membership."
        elif header_only:
            reason = "Header-only file; no membership rows."
        elif not csv_rows:
            reason = "No parseable CSV rows or non-CSV artifact."
        elif not has_date:
            reason = "Missing as_of_date/asof_date/signal_date."
        elif not has_ticker:
            reason = "Missing ticker/symbol."
        elif not (has_rank or has_shadow_rank):
            reason = "Missing rank field."
        elif not top20_like:
            reason = "No explicit Top20 membership/rank evidence detected."
        rows.append({
            "source_file": rel(path),
            "row_count": len(csv_rows),
            "header_only": bool_text(header_only),
            "candidate_membership_type": membership_type,
            "distinct_as_of_dates": date_count,
            "has_required_date": bool_text(has_date),
            "has_required_ticker": bool_text(has_ticker),
            "has_rank_or_membership": bool_text(has_rank or has_shadow_rank),
            "never_inferred_from_aggregate_topn_matrix": "TRUE",
            "certification_candidate": bool_text(usable),
            "usable_for_equity_curve_membership": bool_text(usable),
            "reason": reason or "Candidate has local dated ticker rank/membership rows.",
        })
    if not rows:
        rows.append({
            "source_file": "NO_LOCAL_MEMBERSHIP_CANDIDATES_FOUND",
            "row_count": 0,
            "header_only": "FALSE",
            "candidate_membership_type": "UNKNOWN",
            "distinct_as_of_dates": 0,
            "has_required_date": "FALSE",
            "has_required_ticker": "FALSE",
            "has_rank_or_membership": "FALSE",
            "never_inferred_from_aggregate_topn_matrix": "TRUE",
            "certification_candidate": "FALSE",
            "usable_for_equity_curve_membership": "FALSE",
            "reason": "No local membership source candidates found.",
        })
    return rows


def price_discovery() -> list[dict[str, object]]:
    roots = [INPUT_BENCH, INPUT_EC, CONSOLIDATION, ROOT / "outputs" / "v18", ROOT / "data"]
    files = discover_local_files(roots, ("price", "close", "yahoo", "history", "ohlc", "benchmark"))
    rows: list[dict[str, object]] = []
    for path in files:
        csv_rows = read_csv(path) if path.suffix.lower() == ".csv" else []
        fields = fields_lower(csv_rows)
        header_only = path.suffix.lower() == ".csv" and not csv_rows
        has_symbol = bool(fields & {"ticker", "symbol", "benchmark_ticker"})
        has_date = "price_date" in fields or "date" in fields
        has_close = "close" in fields or "adjusted_close" in fields or "adj_close" in fields
        date_count = count_dates(csv_rows, ["price_date", "date"])
        symbols = {symbol_for(row) for row in csv_rows if symbol_for(row)}
        is_bench = bool(symbols & set(BENCHMARKS)) or "BENCHMARK" in path.name.upper()
        source_type = "BENCHMARK_PRICE_PATH" if is_bench else "TICKER_PRICE_PATH"
        sufficient = date_count >= 121
        usable = bool(csv_rows and has_symbol and has_date and has_close and sufficient)
        reason = ""
        if header_only:
            reason = "Header-only file; no price rows."
        elif not csv_rows:
            reason = "No parseable CSV rows or non-CSV artifact."
        elif not has_symbol:
            reason = "Missing ticker/symbol/benchmark_ticker."
        elif not has_date:
            reason = "Missing price_date/date."
        elif not has_close:
            reason = "Missing close/adjusted_close."
        elif not sufficient:
            reason = f"Only {date_count} distinct trading dates; at least 121 required for 120D equity curve."
        rows.append({
            "source_file": rel(path),
            "source_type": source_type,
            "row_count": len(csv_rows),
            "header_only": bool_text(header_only),
            "distinct_trading_dates": date_count,
            "has_ticker_or_symbol": bool_text(has_symbol),
            "has_price_date": bool_text(has_date),
            "has_close_or_adjusted_close": bool_text(has_close),
            "covers_121_trading_dates": bool_text(sufficient),
            "qqq_present": bool_text("QQQ" in symbols),
            "spy_present": bool_text("SPY" in symbols),
            "soxx_present": bool_text("SOXX" in symbols),
            "smh_present": bool_text("SMH" in symbols),
            "never_inferred_from_forward_window_returns": "TRUE",
            "certification_candidate": bool_text(usable),
            "usable_for_120d_equity_curve": bool_text(usable),
            "reason": reason or "Candidate has local daily price rows and sufficient date coverage.",
        })
    if not rows:
        rows.append({
            "source_file": "NO_LOCAL_PRICE_CANDIDATES_FOUND",
            "source_type": "UNKNOWN",
            "row_count": 0,
            "header_only": "FALSE",
            "distinct_trading_dates": 0,
            "has_ticker_or_symbol": "FALSE",
            "has_price_date": "FALSE",
            "has_close_or_adjusted_close": "FALSE",
            "covers_121_trading_dates": "FALSE",
            "qqq_present": "FALSE",
            "spy_present": "FALSE",
            "soxx_present": "FALSE",
            "smh_present": "FALSE",
            "never_inferred_from_forward_window_returns": "TRUE",
            "certification_candidate": "FALSE",
            "usable_for_120d_equity_curve": "FALSE",
            "reason": "No local daily price source candidates found.",
        })
    return rows


def schema_rows() -> list[dict[str, object]]:
    sections = [
        ("BASELINE_TOP20_MEMBERSHIP", MEMBERSHIP_FIELDS, "strategy_id=baseline; membership_type=BASELINE_TOP20"),
        ("SHADOW_TOP20_MEMBERSHIP", MEMBERSHIP_FIELDS, "strategy_id=shadow; membership_type=SHADOW_TOP20"),
        ("DAILY_TICKER_PRICE_PATH", PRICE_FIELDS, "At least 121 trading dates for 120D equity curve."),
        ("BENCHMARK_DAILY_PRICE_PATH", BENCH_FIELDS, "benchmark_ticker in QQQ/SPY/SOXX/SMH when available."),
        ("SELECTED_ETF_HISTORY", ETF_FIELDS, "Requires real selected_etf history; current selected ETF only is insufficient."),
    ]
    rows: list[dict[str, object]] = []
    for section, fields, notes in sections:
        for pos, field in enumerate(fields, start=1):
            rows.append({
                "schema_name": section,
                "field_order": pos,
                "field_name": field,
                "required": "TRUE",
                "notes": notes,
            })
    return rows


def write_templates() -> None:
    write_csv(TEMPLATE_BASELINE, MEMBERSHIP_FIELDS, [{
        "strategy_id": "BASELINE_TOP20_EQUAL_WEIGHT",
        "membership_type": "BASELINE_TOP20",
        "as_of_date": "YYYY-MM-DD",
        "ticker": "TICKER",
        "rank": "1",
        "score": "",
        "source_stage": "USER_SUPPLIED_OR_LOCAL_CERTIFIED_SOURCE",
        "source_file": rel(TEMPLATE_BASELINE),
        "pit_safe": "TRUE",
        "research_only": "TRUE",
        "official_weight": "FALSE",
        "notes": "Template row; replace with real dated membership history.",
    }])
    write_csv(TEMPLATE_SHADOW, MEMBERSHIP_FIELDS, [{
        "strategy_id": "SHADOW_TOP20_EQUAL_WEIGHT",
        "membership_type": "SHADOW_TOP20",
        "as_of_date": "YYYY-MM-DD",
        "ticker": "TICKER",
        "rank": "1",
        "score": "",
        "source_stage": "USER_SUPPLIED_OR_LOCAL_CERTIFIED_SOURCE",
        "source_file": rel(TEMPLATE_SHADOW),
        "pit_safe": "TRUE",
        "research_only": "TRUE",
        "official_weight": "FALSE",
        "notes": "Template row; replace with real dated shadow membership history.",
    }])
    write_csv(TEMPLATE_PRICE, PRICE_FIELDS, [{
        "ticker": "TICKER",
        "price_date": "YYYY-MM-DD",
        "close": "",
        "adjusted_close": "",
        "volume": "",
        "source_name": "LOCAL_ONLY",
        "source_file": rel(TEMPLATE_PRICE),
        "source_run_id": "",
        "data_availability_date": "YYYY-MM-DD",
        "pit_safe": "TRUE",
        "corporate_action_adjusted": "TRUE_OR_FALSE",
        "notes": "Template row; replace with real daily ticker prices.",
    }])
    write_csv(TEMPLATE_BENCH, BENCH_FIELDS, [{
        "benchmark_ticker": "QQQ",
        "price_date": "YYYY-MM-DD",
        "close": "",
        "adjusted_close": "",
        "volume": "",
        "source_name": "LOCAL_ONLY",
        "source_file": rel(TEMPLATE_BENCH),
        "source_run_id": "",
        "data_availability_date": "YYYY-MM-DD",
        "pit_safe": "TRUE",
        "corporate_action_adjusted": "TRUE_OR_FALSE",
        "notes": "Template row; replace with real benchmark prices.",
    }])
    write_csv(TEMPLATE_ETF, ETF_FIELDS, [{
        "as_of_date": "YYYY-MM-DD",
        "selected_etf": "QQQ",
        "selection_rule": "RULE_NAME",
        "regime_classification": "",
        "leverage_allowed": "FALSE",
        "source_stage": "USER_SUPPLIED_OR_LOCAL_CERTIFIED_SOURCE",
        "source_file": rel(TEMPLATE_ETF),
        "pit_safe": "TRUE",
        "research_only": "TRUE",
        "notes": "Template row; replace with real selected_etf history.",
    }])


def certification_from_discovery(membership_rows: list[dict[str, object]], price_rows: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, bool]]:
    membership_cert: list[dict[str, object]] = []
    baseline = False
    shadow = False
    for row in membership_rows:
        usable = clean(row.get("usable_for_equity_curve_membership")) == "TRUE"
        mtype = clean(row.get("candidate_membership_type"))
        if usable and mtype == "BASELINE_TOP20":
            baseline = True
        if usable and mtype == "SHADOW_TOP20":
            shadow = True
        membership_cert.append({
            "source_file": row.get("source_file", ""),
            "candidate_membership_type": mtype,
            "row_count": row.get("row_count", 0),
            "header_only": row.get("header_only", "FALSE"),
            "certified_usable": bool_text(usable),
            "certification_status": "PASS" if usable else "FAIL",
            "reason": row.get("reason", ""),
        })

    price_cert: list[dict[str, object]] = []
    ticker_paths = False
    bench = {b: False for b in BENCHMARKS}
    for row in price_rows:
        usable = clean(row.get("usable_for_120d_equity_curve")) == "TRUE"
        source_type = clean(row.get("source_type"))
        if usable and source_type == "TICKER_PRICE_PATH":
            ticker_paths = True
        for b in BENCHMARKS:
            if usable and clean(row.get(f"{b.lower()}_present")) == "TRUE":
                bench[b] = True
        price_cert.append({
            "source_file": row.get("source_file", ""),
            "source_type": source_type,
            "row_count": row.get("row_count", 0),
            "header_only": row.get("header_only", "FALSE"),
            "distinct_trading_dates": row.get("distinct_trading_dates", 0),
            "certified_usable": bool_text(usable),
            "certification_status": "PASS" if usable else "FAIL",
            "reason": row.get("reason", ""),
        })
    flags = {
        "baseline_membership": baseline,
        "shadow_membership": shadow,
        "membership_history": baseline and shadow,
        "daily_ticker_paths": ticker_paths,
        "qqq": bench["QQQ"],
        "spy": bench["SPY"],
        "soxx": bench["SOXX"],
        "smh": bench["SMH"],
    }
    return membership_cert, price_cert, flags


def selected_etf_history_available() -> tuple[bool, str]:
    roots = [INPUT_EC, CONSOLIDATION, ROOT / "data", ROOT / "outputs" / "v18"]
    files = discover_local_files(roots, ("selected_etf", "etf_rotation", "rotation_selection"))
    for path in files:
        rows = read_csv(path) if path.suffix.lower() == ".csv" else []
        fields = fields_lower(rows)
        has_history = len(rows) > 5 and bool(fields & {"as_of_date", "selection_date", "date"}) and "selected_etf" in fields
        current_only = "current_selected_etf" in fields and len(rows) <= 5
        if has_history and not current_only:
            return True, rel(path)
    return False, "No real selected_etf history found; current selected ETF snapshots are not treated as history."


def etf_contract_rows(selected_available: bool, selected_reason: str) -> list[dict[str, object]]:
    return [
        {"contract_item": "selected_etf_history_required", "required": "TRUE", "available": bool_text(selected_available), "notes": selected_reason},
        {"contract_item": "daily_selected_etf_price_path_required", "required": "TRUE", "available": "FALSE", "notes": "Must provide daily price path for every selected ETF over each holding interval."},
        {"contract_item": "current_selected_etf_only_not_enough", "required": "TRUE", "available": "FALSE", "notes": "Do not infer ETF rotation history from V20.208/V20.209 current selected ETF snapshots."},
        {"contract_item": "separate_lane", "required": "TRUE", "available": "TRUE", "notes": "ETF rotation remains separate from stock ranking and portfolio equity curve until history is staged."},
    ]


def staging_status_rows(flags: dict[str, bool], selected_etf_available: bool, allow_download: bool) -> list[dict[str, object]]:
    templates_ready = all(path.exists() and path.stat().st_size > 0 for path in TEMPLATES)
    equity_ready = flags["membership_history"] and flags["daily_ticker_paths"]
    benchmark_only = (flags["qqq"] or flags["spy"]) and not equity_ready
    return [
        {"staging_item": "input_templates_created", "status": bool_text(templates_ready), "reason": "User-fillable templates created under inputs/v20/equity_curve/."},
        {"staging_item": "membership_history_available", "status": bool_text(flags["membership_history"]), "reason": "Requires certified baseline and shadow Top20 histories."},
        {"staging_item": "daily_ticker_price_paths_available", "status": bool_text(flags["daily_ticker_paths"]), "reason": "Requires certified local ticker paths with at least 121 trading dates."},
        {"staging_item": "benchmark_only_available", "status": bool_text(benchmark_only), "reason": "Benchmark paths alone do not make portfolio equity curve retry ready."},
        {"staging_item": "selected_etf_history_available", "status": bool_text(selected_etf_available), "reason": "ETF rotation requires real selected_etf history, not current snapshot only."},
        {"staging_item": "allow_yahoo_download_argument_used", "status": bool_text(allow_download), "reason": "Default wrapper does not use --allow-yahoo-download."},
        {"staging_item": "equity_curve_retry_ready", "status": bool_text(equity_ready), "reason": "TRUE only when membership history and daily ticker price paths are certified usable."},
    ]


def collect_manifest_tickers() -> tuple[set[str], str, str]:
    tickers: set[str] = set()
    dates: list[str] = []
    for path in [
        CONSOLIDATION / "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
        CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
        CONSOLIDATION / "V20_108_R12_STRICT_EQUITY_SHADOW_DYNAMIC_WEIGHTED_RERANK.csv",
        CONSOLIDATION / "V20_104_RANDOM_ASOF_FORWARD_OUTCOME_MATRIX.csv",
    ]:
        rows = read_csv(path)
        for row in rows:
            symbol = symbol_for(row)
            if symbol and symbol not in {"QQQ", "SPY", "SOXX", "SMH"}:
                tickers.add(symbol)
            for field in ("as_of_date", "signal_date", "price_date"):
                d = parse_date_text(row.get(field))
                if d:
                    dates.append(d)
    start = min(dates) if dates else "TBD_OPERATOR_SUPPLIED"
    end = date.today().isoformat()
    return tickers, start, end


def acquisition_manifest_rows() -> list[dict[str, object]]:
    tickers, start, end = collect_manifest_tickers()
    rows: list[dict[str, object]] = []
    for ticker in sorted(tickers):
        rows.append({
            "ticker": ticker,
            "asset_type": "EQUITY",
            "required_start_date": start,
            "required_end_date": end,
            "required_for": "BASELINE_SHADOW_EQUITY_CURVE",
            "source_adapter_recommendation": "YAHOO_RUNTIME_ADAPTER_ALLOWED_BY_V20_26_IF_OPERATOR_APPROVES",
            "acquisition_status": "NOT_FETCHED_BY_DEFAULT",
            "reason": "Needed for daily ticker price path staging; not fetched by default.",
        })
    for ticker in BENCHMARKS:
        rows.append({
            "ticker": ticker,
            "asset_type": "BENCHMARK_ETF",
            "required_start_date": start,
            "required_end_date": end,
            "required_for": "BENCHMARK",
            "source_adapter_recommendation": "YAHOO_RUNTIME_ADAPTER_ALLOWED_BY_V20_26_IF_OPERATOR_APPROVES",
            "acquisition_status": "NOT_FETCHED_BY_DEFAULT",
            "reason": "Needed for benchmark daily NAV comparison; not fetched by default.",
        })
    for ticker in ["QQQ", "SPY", "SOXX", "SMH"]:
        rows.append({
            "ticker": ticker,
            "asset_type": "ROTATION_ETF",
            "required_start_date": start,
            "required_end_date": end,
            "required_for": "ETF_ROTATION",
            "source_adapter_recommendation": "YAHOO_RUNTIME_ADAPTER_ALLOWED_BY_V20_26_IF_OPERATOR_APPROVES",
            "acquisition_status": "NOT_FETCHED_BY_DEFAULT",
            "reason": "Needed only after selected_etf history exists; not fetched by default.",
        })
    return rows


def gate_row(v212_status: str, flags: dict[str, bool], selected_etf_available: bool, ready: bool) -> dict[str, object]:
    return {
        "v20_213_status": STATUS_READY if ready else STATUS_COLLECTION,
        "consumed_v20_212_status": v212_status,
        "v20_212_blocker_intake_created": "TRUE",
        "membership_source_discovery_created": "TRUE",
        "price_source_discovery_created": "TRUE",
        "required_input_schema_created": "TRUE",
        "input_templates_created": "TRUE",
        "yahoo_acquisition_manifest_created": "TRUE",
        "membership_history_available": bool_text(flags["membership_history"]),
        "daily_ticker_price_paths_available": bool_text(flags["daily_ticker_paths"]),
        "qqq_daily_path_available": bool_text(flags["qqq"]),
        "spy_daily_path_available": bool_text(flags["spy"]),
        "soxx_daily_path_available": bool_text(flags["soxx"]),
        "smh_daily_path_available": bool_text(flags["smh"]),
        "selected_etf_history_available": bool_text(selected_etf_available),
        "equity_curve_retry_ready": bool_text(ready),
        "official_promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
        "recommended_next_stage": "V20.214_PORTFOLIO_EQUITY_CURVE_EXECUTION_RETRY" if ready else "V20.214_OPERATOR_APPROVED_HISTORICAL_PRICE_AND_MEMBERSHIP_INPUT_FILL_OR_YAHOO_CACHE_BUILD",
    }


def render_report(
    blocker_rows: list[dict[str, object]],
    membership_rows: list[dict[str, object]],
    price_rows: list[dict[str, object]],
    gate: dict[str, object],
    selected_reason: str,
) -> str:
    blockers = [f"- {row['blocker_item']}: {row['blocker_reason']}" for row in blocker_rows]
    missing = []
    if gate["membership_history_available"] == "FALSE":
        missing.append("certified baseline and shadow Top20 membership histories")
    if gate["daily_ticker_price_paths_available"] == "FALSE":
        missing.append("certified daily ticker price paths with at least 121 trading dates")
    if gate["selected_etf_history_available"] == "FALSE":
        missing.append("selected_etf rotation history")
    membership_summary = f"{sum(1 for row in membership_rows if row['usable_for_equity_curve_membership'] == 'TRUE')} usable of {len(membership_rows)} discovered candidates"
    price_summary = f"{sum(1 for row in price_rows if row['usable_for_120d_equity_curve'] == 'TRUE')} usable of {len(price_rows)} discovered candidates"
    return "\n".join([
        "# V20.213 Daily Price Path Source Repair or Equity Curve Input Staging",
        "",
        "## Summary",
        "V20.213 staged the required schemas and user-fillable templates for a future equity curve retry, discovered local membership and price sources, and created a Yahoo acquisition manifest for later operator-approved data collection. No network download was performed by default.",
        "",
        "## V20.212 Blocker Intake",
        f"- Consumed V20.212 status: `{gate['consumed_v20_212_status']}`",
        *(blockers or ["- No V20.212 blocker rows were available."]),
        "",
        "## Membership Source Availability",
        membership_summary,
        "",
        "## Daily Price Source Availability",
        price_summary,
        "",
        "## Benchmark Availability",
        f"- QQQ certified daily path: `{gate['qqq_daily_path_available']}`",
        f"- SPY certified daily path: `{gate['spy_daily_path_available']}`",
        f"- SOXX certified daily path: `{gate['soxx_daily_path_available']}`",
        f"- SMH certified daily path: `{gate['smh_daily_path_available']}`",
        "",
        "## ETF Rotation History",
        f"- Selected ETF history available: `{gate['selected_etf_history_available']}`",
        f"- Reason: {selected_reason}",
        "",
        "## Retry Readiness",
        f"- Equity curve retry ready: `{gate['equity_curve_retry_ready']}`",
        f"- Missing inputs: {', '.join(missing) if missing else 'None'}",
        "",
        "## User-Fillable Templates",
        *[f"- `{rel(path)}`" for path in TEMPLATES],
        "",
        "## Yahoo Acquisition Manifest",
        f"- `{rel(OUT_YAHOO_MANIFEST)}`",
        "- Default acquisition status is `NOT_FETCHED_BY_DEFAULT`; operator approval is required before any Yahoo runtime adapter fetch.",
        "",
        "## Safety",
        "No official recommendation, no official weight mutation, no trade action, and no broker execution artifact were created. No drawdown or performance metric was fabricated.",
        "",
        "## Next Recommended Action",
        f"`{gate['recommended_next_stage']}`",
        "",
        f"Final status: `{gate['v20_213_status']}`",
        "",
    ])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-yahoo-download", action="store_true", help="Reserved for explicit operator-approved Yahoo download; not used by default wrapper.")
    args = parser.parse_args()

    v212_status, blockers = consume_v212_blockers()
    membership_rows = membership_discovery()
    price_rows = price_discovery()
    write_templates()
    membership_cert, price_cert, flags = certification_from_discovery(membership_rows, price_rows)
    selected_available, selected_reason = selected_etf_history_available()
    ready = flags["membership_history"] and flags["daily_ticker_paths"]
    gate = gate_row(v212_status, flags, selected_available, ready)

    write_csv(OUT_BLOCKER, ["consumed_v20_212_status", "blocker_item", "requirement", "blocker_reason", "intake_status"], blockers)
    write_csv(OUT_MEMBERSHIP_DISCOVERY, ["source_file", "row_count", "header_only", "candidate_membership_type", "distinct_as_of_dates", "has_required_date", "has_required_ticker", "has_rank_or_membership", "never_inferred_from_aggregate_topn_matrix", "certification_candidate", "usable_for_equity_curve_membership", "reason"], membership_rows)
    write_csv(OUT_PRICE_DISCOVERY, ["source_file", "source_type", "row_count", "header_only", "distinct_trading_dates", "has_ticker_or_symbol", "has_price_date", "has_close_or_adjusted_close", "covers_121_trading_dates", "qqq_present", "spy_present", "soxx_present", "smh_present", "never_inferred_from_forward_window_returns", "certification_candidate", "usable_for_120d_equity_curve", "reason"], price_rows)
    write_csv(OUT_SCHEMA, ["schema_name", "field_order", "field_name", "required", "notes"], schema_rows())
    write_csv(OUT_STAGING, ["staging_item", "status", "reason"], staging_status_rows(flags, selected_available, args.allow_yahoo_download))
    write_csv(OUT_YAHOO_MANIFEST, ["ticker", "asset_type", "required_start_date", "required_end_date", "required_for", "source_adapter_recommendation", "acquisition_status", "reason"], acquisition_manifest_rows())
    write_csv(OUT_PRICE_CERT, ["source_file", "source_type", "row_count", "header_only", "distinct_trading_dates", "certified_usable", "certification_status", "reason"], price_cert)
    write_csv(OUT_MEMBERSHIP_CERT, ["source_file", "candidate_membership_type", "row_count", "header_only", "certified_usable", "certification_status", "reason"], membership_cert)
    write_csv(OUT_ETF_CONTRACT, ["contract_item", "required", "available", "notes"], etf_contract_rows(selected_available, selected_reason))
    write_csv(OUT_GATE, ["v20_213_status", "consumed_v20_212_status", "v20_212_blocker_intake_created", "membership_source_discovery_created", "price_source_discovery_created", "required_input_schema_created", "input_templates_created", "yahoo_acquisition_manifest_created", "membership_history_available", "daily_ticker_price_paths_available", "qqq_daily_path_available", "spy_daily_path_available", "soxx_daily_path_available", "smh_daily_path_available", "selected_etf_history_available", "equity_curve_retry_ready", "official_promotion_allowed", "official_recommendation_created", "weight_mutated", "trade_action_created", "broker_execution_supported", "recommended_next_stage"], [gate])
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text(render_report(blockers, membership_rows, price_rows, gate, selected_reason), encoding="utf-8")

    print(f"FINAL_STATUS={gate['v20_213_status']}")
    print(f"CONSUMED_V20_212_STATUS={gate['consumed_v20_212_status']}")
    print(f"MEMBERSHIP_HISTORY_AVAILABLE={gate['membership_history_available']}")
    print(f"DAILY_TICKER_PRICE_PATHS_AVAILABLE={gate['daily_ticker_price_paths_available']}")
    print(f"SELECTED_ETF_HISTORY_AVAILABLE={gate['selected_etf_history_available']}")
    print(f"EQUITY_CURVE_RETRY_READY={gate['equity_curve_retry_ready']}")
    print(f"OFFICIAL_PROMOTION_ALLOWED={gate['official_promotion_allowed']}")
    print(f"OFFICIAL_RECOMMENDATION_CREATED={gate['official_recommendation_created']}")
    print(f"WEIGHT_MUTATED={gate['weight_mutated']}")
    print(f"TRADE_ACTION_CREATED={gate['trade_action_created']}")
    print(f"BROKER_EXECUTION_SUPPORTED={gate['broker_execution_supported']}")
    print(f"NEXT_STAGE={gate['recommended_next_stage']}")


if __name__ == "__main__":
    main()
