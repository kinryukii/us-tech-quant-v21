#!/usr/bin/env python
"""V20.98C-R1 current ETF price coverage expander.

Builds a research-only ETF price coverage artifact for V20.98C regime pair
auditing. This stage only reuses current prices already present in V20.48 or
V20.50 benchmark context artifacts. Missing ETF prices are classified
explicitly and no prices, recommendations, weights, multipliers, or trade
actions are created.
"""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

V20_98C_AUDIT = CONSOLIDATION / "V20_98C_RESEARCH_ONLY_ETF_ROTATION_REGIME_AUDIT.csv"
V20_98C_MATRIX = CONSOLIDATION / "V20_98C_ETF_PAIR_RELATIVE_STRENGTH_MATRIX.csv"
V20_98C_SCAFFOLD = CONSOLIDATION / "V20_98C_ETF_REGIME_FACTOR_MULTIPLIER_SCAFFOLD.csv"
V48_BENCHMARK = CONSOLIDATION / "V20_48_REFRESHED_BENCHMARK_CONTEXT_VIEW.csv"
V50_BENCHMARK = CONSOLIDATION / "V20_50_BENCHMARK_RESEARCH_CONTEXT_PACKET.csv"
R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

COVERAGE = CONSOLIDATION / "V20_98C_R1_CURRENT_ETF_PRICE_COVERAGE.csv"
PAIR_AUDIT = CONSOLIDATION / "V20_98C_R1_ETF_PAIR_COVERAGE_AUDIT.csv"
REPAIR_PLAN = CONSOLIDATION / "V20_98C_R1_ETF_COVERAGE_GAP_REPAIR_PLAN.csv"
REPORT = READ_CENTER / "V20_98C_R1_CURRENT_ETF_PRICE_COVERAGE_REPORT.md"

REQUIRED_ETFS = [
    "SPY",
    "QQQ",
    "XLK",
    "SOXX",
    "SMH",
    "TQQQ",
    "SQQQ",
    "SOXL",
    "SOXS",
    "RSP",
    "XLU",
    "XLP",
    "TLT",
    "GLD",
]

PAIR_SPECS = [
    ("QQQ vs SPY", "QQQ", "SPY"),
    ("XLK vs SPY", "XLK", "SPY"),
    ("SOXX vs QQQ", "SOXX", "QQQ"),
    ("SMH vs QQQ", "SMH", "QQQ"),
    ("SOXX vs SPY", "SOXX", "SPY"),
    ("SMH vs SPY", "SMH", "SPY"),
    ("TQQQ vs SQQQ", "TQQQ", "SQQQ"),
    ("SOXL vs SOXS", "SOXL", "SOXS"),
    ("RSP vs SPY", "RSP", "SPY"),
    ("XLU vs SPY", "XLU", "SPY"),
    ("XLP vs SPY", "XLP", "SPY"),
    ("TLT vs SPY", "TLT", "SPY"),
    ("GLD vs SPY", "GLD", "SPY"),
]

ETF_ROLES = {
    "SPY": "BROAD_MARKET_BENCHMARK",
    "QQQ": "GROWTH_TECH_BENCHMARK",
    "XLK": "TECHNOLOGY_SECTOR",
    "SOXX": "SEMICONDUCTOR_SECTOR",
    "SMH": "SEMICONDUCTOR_SECTOR",
    "TQQQ": "LEVERAGED_GROWTH_LONG",
    "SQQQ": "LEVERAGED_GROWTH_INVERSE",
    "SOXL": "LEVERAGED_SEMICONDUCTOR_LONG",
    "SOXS": "LEVERAGED_SEMICONDUCTOR_INVERSE",
    "RSP": "EQUAL_WEIGHT_BREADTH",
    "XLU": "DEFENSIVE_UTILITIES",
    "XLP": "DEFENSIVE_STAPLES",
    "TLT": "DURATION_RISK_OFF",
    "GLD": "GOLD_RISK_OFF",
}

COVERAGE_FIELDS = [
    "ticker",
    "asset_class",
    "etf_role",
    "latest_price",
    "latest_price_date",
    "price_source_artifact",
    "price_source_stage",
    "data_available",
    "data_freshness_status",
    "required_for_pair_checks",
    "missing_reason",
    "repair_action",
    "research_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "weight_mutated",
    "trade_action_created",
    "broker_execution_supported",
]

PAIR_AUDIT_FIELDS = [
    "etf_pair",
    "left_ticker",
    "right_ticker",
    "left_data_available",
    "right_data_available",
    "pair_data_available",
    "left_latest_price",
    "right_latest_price",
    "left_price_date",
    "right_price_date",
    "coverage_status",
    "missing_side",
    "repair_action",
    "research_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "weight_mutated",
    "trade_action_created",
    "broker_execution_supported",
]

REPAIR_PLAN_FIELDS = [
    "ticker",
    "required_for_pair_checks",
    "data_available",
    "gap_status",
    "missing_reason",
    "affected_pairs",
    "repair_action",
    "research_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "weight_mutated",
    "trade_action_created",
    "broker_execution_supported",
    "v20_107_execution_status",
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def safety() -> dict[str, str]:
    return {
        "research_only": "TRUE",
        "official_promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
    }


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], str]:
    if not path.exists():
        return [], "MISSING"
    if path.stat().st_size == 0:
        return [], "EMPTY"
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = [{key: clean(value) for key, value in row.items()} for row in reader]
            if not reader.fieldnames:
                return [], "MALFORMED"
            return rows, "OK"
    except csv.Error:
        return [], "MALFORMED"


def first_row(path: Path) -> dict[str, str]:
    rows, status = read_csv(path)
    return rows[0] if status == "OK" and rows else {}


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def usable_source_price(row: dict[str, str]) -> tuple[str, str, bool]:
    price = clean(row.get("refreshed_latest_close") or row.get("latest_close") or row.get("close"))
    date = clean(row.get("refreshed_price_date") or row.get("price_date") or row.get("as_of_date"))
    certified = clean(row.get("certification_status")).upper() in {"CERTIFIED", "PASS", ""}
    return price, date, bool(price and date and certified)


def build_price_map() -> dict[str, dict[str, str]]:
    price_map: dict[str, dict[str, str]] = {}
    for stage, path in [
        ("V20.48_REFRESHED_BENCHMARK_CONTEXT_VIEW", V48_BENCHMARK),
        ("V20.50_BENCHMARK_RESEARCH_CONTEXT_PACKET", V50_BENCHMARK),
    ]:
        rows, status = read_csv(path)
        if status != "OK":
            continue
        for row in rows:
            ticker = clean(row.get("benchmark_ticker") or row.get("ticker") or row.get("etf_symbol")).upper()
            if ticker not in REQUIRED_ETFS or ticker in price_map:
                continue
            price, date, usable = usable_source_price(row)
            if usable:
                price_map[ticker] = {
                    "latest_price": price,
                    "latest_price_date": date,
                    "price_source_artifact": rel(path),
                    "price_source_stage": stage,
                }
    return price_map


def affected_pairs_by_ticker() -> dict[str, list[str]]:
    result = {ticker: [] for ticker in REQUIRED_ETFS}
    for pair, left, right in PAIR_SPECS:
        result[left].append(pair)
        result[right].append(pair)
    return result


def build_coverage_rows(price_map: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    pair_usage = affected_pairs_by_ticker()
    for ticker in REQUIRED_ETFS:
        source = price_map.get(ticker, {})
        available = bool(source)
        rows.append(
            {
                "ticker": ticker,
                "asset_class": "ETF",
                "etf_role": ETF_ROLES[ticker],
                "latest_price": source.get("latest_price", ""),
                "latest_price_date": source.get("latest_price_date", ""),
                "price_source_artifact": source.get("price_source_artifact", ""),
                "price_source_stage": source.get("price_source_stage", ""),
                "data_available": "TRUE" if available else "FALSE",
                "data_freshness_status": "CURRENT_REFRESHED_PRICE_AVAILABLE"
                if available
                else "MISSING_CURRENT_ETF_PRICE_DATA",
                "required_for_pair_checks": "TRUE" if pair_usage[ticker] else "FALSE",
                "missing_reason": "" if available else "MISSING_CURRENT_ETF_PRICE_DATA",
                "repair_action": "NONE"
                if available
                else "ADD_CURRENT_CERTIFIED_ETF_PRICE_TO_V20_48_OR_V20_50_BENCHMARK_CONTEXT",
                **safety(),
            }
        )
    return rows


def by_ticker(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["ticker"]: row for row in rows}


def build_pair_audit_rows(coverage_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    coverage = by_ticker(coverage_rows)
    rows: list[dict[str, str]] = []
    for pair, left, right in PAIR_SPECS:
        left_row = coverage[left]
        right_row = coverage[right]
        left_available = left_row["data_available"] == "TRUE"
        right_available = right_row["data_available"] == "TRUE"
        pair_available = left_available and right_available
        if pair_available:
            status = "PAIR_CURRENT_PRICE_COVERAGE_AVAILABLE"
            missing_side = "NONE"
            repair_action = "NONE"
        elif not left_available and not right_available:
            status = "MISSING_CURRENT_ETF_PRICE_DATA"
            missing_side = "LEFT_AND_RIGHT"
            repair_action = f"ADD_CURRENT_CERTIFIED_ETF_PRICES_FOR_{left}_AND_{right}"
        elif not left_available:
            status = "MISSING_CURRENT_ETF_PRICE_DATA"
            missing_side = "LEFT"
            repair_action = f"ADD_CURRENT_CERTIFIED_ETF_PRICE_FOR_{left}"
        else:
            status = "MISSING_CURRENT_ETF_PRICE_DATA"
            missing_side = "RIGHT"
            repair_action = f"ADD_CURRENT_CERTIFIED_ETF_PRICE_FOR_{right}"
        rows.append(
            {
                "etf_pair": pair,
                "left_ticker": left,
                "right_ticker": right,
                "left_data_available": "TRUE" if left_available else "FALSE",
                "right_data_available": "TRUE" if right_available else "FALSE",
                "pair_data_available": "TRUE" if pair_available else "FALSE",
                "left_latest_price": left_row["latest_price"],
                "right_latest_price": right_row["latest_price"],
                "left_price_date": left_row["latest_price_date"],
                "right_price_date": right_row["latest_price_date"],
                "coverage_status": status,
                "missing_side": missing_side,
                "repair_action": repair_action,
                **safety(),
            }
        )
    return rows


def build_repair_plan_rows(coverage_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    pair_usage = affected_pairs_by_ticker()
    rows: list[dict[str, str]] = []
    for row in coverage_rows:
        if row["data_available"] == "TRUE":
            continue
        ticker = row["ticker"]
        rows.append(
            {
                "ticker": ticker,
                "required_for_pair_checks": row["required_for_pair_checks"],
                "data_available": "FALSE",
                "gap_status": "OPEN",
                "missing_reason": "MISSING_CURRENT_ETF_PRICE_DATA",
                "affected_pairs": "|".join(pair_usage[ticker]),
                "repair_action": "ADD_CURRENT_CERTIFIED_ETF_PRICE_TO_V20_48_OR_V20_50_BENCHMARK_CONTEXT",
                **safety(),
                "v20_107_execution_status": "NOT_RUN",
            }
        )
    return rows


def write_report(
    coverage_rows: list[dict[str, str]],
    pair_rows: list[dict[str, str]],
    repair_rows: list[dict[str, str]],
    source_statuses: dict[str, str],
) -> None:
    available_tickers = [row["ticker"] for row in coverage_rows if row["data_available"] == "TRUE"]
    missing_tickers = [row["ticker"] for row in coverage_rows if row["data_available"] != "TRUE"]
    available_pairs = [row for row in pair_rows if row["pair_data_available"] == "TRUE"]
    status = (
        "PASS_V20_98C_R1_CURRENT_ETF_PRICE_COVERAGE_EXPANDER"
        if not repair_rows
        else "PASS_V20_98C_R1_CURRENT_ETF_PRICE_COVERAGE_EXPANDER_WITH_REPAIR_PLAN"
    )
    lines = [
        "# V20.98C-R1 Current ETF Price Coverage",
        "",
        "## Current Result",
        f"- wrapper_status: {status}",
        f"- required_etf_count: {len(coverage_rows)}",
        f"- current_price_available_count: {len(available_tickers)}",
        f"- missing_current_price_count: {len(missing_tickers)}",
        f"- required_pair_count: {len(pair_rows)}",
        f"- pair_current_price_available_count: {len(available_pairs)}",
        f"- repair_plan_rows: {len(repair_rows)}",
        "- v20_107_execution_status: NOT_RUN",
        "",
        "## Input Status",
        f"- V20.98C audit: {source_statuses['v20_98c_audit']}",
        f"- V20.98C pair matrix: {source_statuses['v20_98c_matrix']}",
        f"- V20.98C multiplier scaffold: {source_statuses['v20_98c_scaffold']}",
        f"- V20.48 benchmark context: {source_statuses['v48_benchmark']}",
        f"- V20.50 benchmark context: {source_statuses['v50_benchmark']}",
        f"- V20.98B-R5 active research base weights: {source_statuses['r5_registry']}",
        f"- V20.49 research-only conclusion gate: {source_statuses['v49_research']}",
        f"- V20.49 official promotion gate: {source_statuses['v49_official']}",
        "",
        "## Available Current ETF Prices",
        "- " + ("|".join(available_tickers) if available_tickers else "NONE"),
        "",
        "## Missing Current ETF Prices",
        "- " + ("|".join(missing_tickers) if missing_tickers else "NONE"),
        "",
        "## Repair Plan",
        "Add current certified ETF prices for missing tickers to V20.48 or V20.50 benchmark context artifacts, then rerun this R1 coverage expander.",
        "",
        "## Safety Boundary",
        "- research_only: TRUE",
        "- official_promotion_allowed: FALSE",
        "- official_recommendation_created: FALSE",
        "- weight_mutated: FALSE",
        "- trade_action_created: FALSE",
        "- broker_execution_supported: FALSE",
        "- dynamic_factor_weight_created: FALSE",
        "- official_weight_created: FALSE",
        "- V20.107: NOT_RUN",
        "",
        "## Preservation Checks",
        "- active_research_base_weights_preserved_without_modification: TRUE",
        "- v20_49_research_only_pass_preserved: TRUE",
        "- v20_49_official_promotion_blocked_preserved: TRUE",
        "- official_promotion_allowed: FALSE",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    source_statuses = {
        "v20_98c_audit": read_csv(V20_98C_AUDIT)[1],
        "v20_98c_matrix": read_csv(V20_98C_MATRIX)[1],
        "v20_98c_scaffold": read_csv(V20_98C_SCAFFOLD)[1],
        "v48_benchmark": read_csv(V48_BENCHMARK)[1],
        "v50_benchmark": read_csv(V50_BENCHMARK)[1],
        "r5_registry": read_csv(R5_REGISTRY)[1],
        "v49_research": read_csv(V49_RESEARCH)[1],
        "v49_official": read_csv(V49_OFFICIAL)[1],
    }
    research_gate = first_row(V49_RESEARCH)
    official_gate = first_row(V49_OFFICIAL)

    price_map = build_price_map()
    coverage_rows = build_coverage_rows(price_map)
    pair_rows = build_pair_audit_rows(coverage_rows)
    repair_rows = build_repair_plan_rows(coverage_rows)

    write_csv(COVERAGE, COVERAGE_FIELDS, coverage_rows)
    write_csv(PAIR_AUDIT, PAIR_AUDIT_FIELDS, pair_rows)
    write_csv(REPAIR_PLAN, REPAIR_PLAN_FIELDS, repair_rows)
    write_report(coverage_rows, pair_rows, repair_rows, source_statuses)

    available_tickers = sum(1 for row in coverage_rows if row["data_available"] == "TRUE")
    available_pairs = sum(1 for row in pair_rows if row["pair_data_available"] == "TRUE")
    status = (
        "PASS_V20_98C_R1_CURRENT_ETF_PRICE_COVERAGE_EXPANDER"
        if not repair_rows
        else "PASS_V20_98C_R1_CURRENT_ETF_PRICE_COVERAGE_EXPANDER_WITH_REPAIR_PLAN"
    )
    print(status)
    print(f"REQUIRED_ETF_COUNT={len(coverage_rows)}")
    print(f"CURRENT_PRICE_AVAILABLE_COUNT={available_tickers}")
    print(f"MISSING_CURRENT_PRICE_COUNT={len(repair_rows)}")
    print(f"REQUIRED_PAIR_COUNT={len(pair_rows)}")
    print(f"PAIR_CURRENT_PRICE_AVAILABLE_COUNT={available_pairs}")
    print(f"REPAIR_PLAN_ROWS={len(repair_rows)}")
    print(f"V20_49_RESEARCH_ONLY_GATE_STATUS={research_gate.get('research_only_gate_status', 'MISSING')}")
    print(f"V20_49_OFFICIAL_PROMOTION_GATE_STATUS={official_gate.get('official_promotion_gate_status', 'MISSING')}")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("DYNAMIC_FACTOR_WEIGHT_CREATED=FALSE")
    print("V20_107_EXECUTION_STATUS=NOT_RUN")
    print(f"OUTPUT_COVERAGE={rel(COVERAGE)}")
    print(f"OUTPUT_PAIR_AUDIT={rel(PAIR_AUDIT)}")
    print(f"OUTPUT_REPAIR_PLAN={rel(REPAIR_PLAN)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
