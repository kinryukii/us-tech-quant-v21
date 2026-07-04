#!/usr/bin/env python
"""V20.209 current ETF rotation selection refresh producer.

Produces a dedicated current ETF rotation selection artifact from local ETF
price inputs. Uses transparent FALLBACK_ETF_ROTATION_LOGIC when no prior
reusable current ETF rotation producer is available.
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v20" / "random_weight_backtest"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
PRICE_DIR = ROOT / "outputs" / "v20" / "price_history"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
REPORTS_DIR = ROOT / "outputs" / "v20" / "reports"

IN_CANONICAL_BENCH = PRICE_DIR / "V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"
IN_CURRENT_BENCH_CACHE = CONSOLIDATION / "V20_47_YAHOO_CURRENT_BENCHMARK_PRICE_CACHE.csv"
IN_CURRENT_BENCH_CERT = CONSOLIDATION / "V20_47_CURRENT_BENCHMARK_PRICE_CERTIFICATION.csv"
IN_ETF_REFRESH = CONSOLIDATION / "V20_98C_R2_CONTROLLED_ETF_PRICE_REFRESH_CACHE.csv"

OUT_SELECTION = CONSOLIDATION / "V20_209_CURRENT_ETF_ROTATION_SELECTION_REFRESH.csv"
OUT_INPUT = OUT_DIR / "V20_209_ETF_INPUT_SOURCE_AUDIT.csv"
OUT_COMPONENTS = OUT_DIR / "V20_209_ETF_SIGNAL_COMPONENTS.csv"
OUT_FRESHNESS = OUT_DIR / "V20_209_ETF_SELECTION_FRESHNESS_AUDIT.csv"
OUT_GATE = OUT_DIR / "V20_209_ETF_SELECTION_REFRESH_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_209_CURRENT_ETF_ROTATION_SELECTION_REFRESH_REPORT.md"

DEFAULT_ETF_UNIVERSE = ["SPY", "QQQ", "SOXX", "SMH", "XLK"]
REQUIRED_FOR_SELECTION = ["SPY", "QQQ"]
LOOKBACK_20 = 20
LOOKBACK_60 = 60

SELECTION_FIELDS = [
    "current_selected_etf", "etf_rotation_signal", "selection_date",
    "selection_logic_source", "selection_logic_status", "etf_universe_used",
    "selected_etf_score", "second_best_etf", "second_best_score", "score_gap",
    "freshness_status", "input_coverage_status", "resolution_status",
    "current_observation_condition_for_v20_206",
    "observation_allowed_if_rule_v20_206_applied", "non_spy_edge_disabled",
    "reason", "created_at",
]
INPUT_FIELDS = [
    "source_artifact", "source_type", "exists_non_empty", "etf_ticker",
    "row_count", "date_field", "min_date", "max_date", "latest_price",
    "input_status", "warning_reason",
]
COMPONENT_FIELDS = [
    "etf_ticker", "latest_date", "latest_price", "momentum_20d",
    "momentum_60d", "volatility_20d", "drawdown_20d", "trend_filter_status",
    "final_score", "rank", "component_status", "warning_reason",
]
FRESHNESS_FIELDS = ["current_run_date", "latest_input_date", "age_calendar_days", "freshness_status", "warning_reason"]
GATE_FIELDS = [
    "final_status", "current_selected_etf", "selection_date",
    "selection_logic_source", "selection_logic_status", "input_coverage_status",
    "freshness_status", "observation_allowed_if_rule_v20_206_applied",
    "non_spy_edge_disabled", "research_only", "official_weight_mutated",
    "official_recommendation_created", "real_book_signal_created",
    "broker_execution_supported", "trade_action_created",
    "shadow_weight_change_recommended", "next_stage_allowed", "reason",
    "next_recommended_action",
]

PASS_SPY = "PASS_V20_209_CURRENT_ETF_SELECTION_REFRESHED_SPY"
PASS_NON_SPY = "PASS_V20_209_CURRENT_ETF_SELECTION_REFRESHED_NON_SPY"
PARTIAL_STALE = "PARTIAL_PASS_V20_209_CURRENT_ETF_SELECTION_RESOLVED_STALE_WARN"
PARTIAL_UNKNOWN = "PARTIAL_PASS_V20_209_CURRENT_ETF_SELECTION_UNKNOWN_INPUT_UNAVAILABLE"
BLOCKED_FAILED = "BLOCKED_V20_209_REFRESH_PRODUCER_FAILED"


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def num(value: object) -> float | None:
    try:
        text = clean(value)
        if not text:
            return None
        parsed = float(text)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def fmt(value: float | None) -> str:
    return "" if value is None or not math.isfinite(value) else f"{value:.10f}"


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def parse_date(value: object) -> str:
    text = clean(value)
    if len(text) >= 10:
        try:
            return date.fromisoformat(text[:10]).isoformat()
        except ValueError:
            return ""
    return ""


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


def returns(values: list[float]) -> list[float]:
    return [values[i] / values[i - 1] - 1.0 for i in range(1, len(values)) if values[i - 1] > 0]


def source_audit_for_rows(path: Path, source_type: str, ticker_field: str, date_field: str, price_fields: list[str], rows: list[dict[str, str]]) -> list[dict[str, object]]:
    audit = []
    by_ticker: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        ticker = clean(row.get(ticker_field)).upper()
        if ticker in DEFAULT_ETF_UNIVERSE:
            by_ticker[ticker].append(row)
    for ticker in DEFAULT_ETF_UNIVERSE:
        group = by_ticker.get(ticker, [])
        dates = [parse_date(row.get(date_field)) for row in group]
        dates = [d for d in dates if d]
        latest_row = max(group, key=lambda row: parse_date(row.get(date_field)) or "") if group else {}
        latest_price = None
        for field in price_fields:
            latest_price = num(latest_row.get(field))
            if latest_price is not None:
                break
        exists = path.exists() and path.stat().st_size > 0
        audit.append({
            "source_artifact": rel(path),
            "source_type": source_type,
            "exists_non_empty": "TRUE" if exists else "FALSE",
            "etf_ticker": ticker,
            "row_count": str(len(group)),
            "date_field": date_field,
            "min_date": min(dates) if dates else "",
            "max_date": max(dates) if dates else "",
            "latest_price": fmt(latest_price),
            "input_status": "PASS" if group and latest_price is not None else "MISSING_OR_INCOMPLETE",
            "warning_reason": "" if group and latest_price is not None else "No usable price row for ticker in this source.",
        })
    return audit


def load_price_series() -> tuple[dict[str, dict[str, float]], list[dict[str, object]]]:
    series: dict[str, dict[str, float]] = defaultdict(dict)
    audit: list[dict[str, object]] = []

    canonical = read_csv(IN_CANONICAL_BENCH)
    audit.extend(source_audit_for_rows(IN_CANONICAL_BENCH, "HISTORICAL_BENCHMARK_OHLCV", "symbol", "date", ["adjusted_close", "close"], canonical))
    for row in canonical:
        ticker = clean(row.get("symbol")).upper()
        day = parse_date(row.get("date"))
        price = num(row.get("adjusted_close")) or num(row.get("close"))
        if ticker in DEFAULT_ETF_UNIVERSE and day and price is not None and price > 0:
            series[ticker][day] = price

    current_cache = read_csv(IN_CURRENT_BENCH_CACHE)
    audit.extend(source_audit_for_rows(IN_CURRENT_BENCH_CACHE, "CURRENT_BENCHMARK_PRICE_CACHE", "ticker", "latest_price_date", ["close_like_price", "latest_adj_close", "latest_close"], current_cache))
    for row in current_cache:
        ticker = clean(row.get("ticker")).upper()
        day = parse_date(row.get("latest_price_date"))
        price = num(row.get("close_like_price")) or num(row.get("latest_adj_close")) or num(row.get("latest_close"))
        if ticker in DEFAULT_ETF_UNIVERSE and day and price is not None and price > 0:
            series[ticker][day] = price

    bench_cert = read_csv(IN_CURRENT_BENCH_CERT)
    audit.extend(source_audit_for_rows(IN_CURRENT_BENCH_CERT, "CURRENT_BENCHMARK_CERTIFICATION", "benchmark_ticker", "latest_price_date", ["close_like_price", "latest_adj_close", "latest_close"], bench_cert))
    for row in bench_cert:
        ticker = clean(row.get("benchmark_ticker")).upper()
        day = parse_date(row.get("latest_price_date"))
        price = num(row.get("close_like_price")) or num(row.get("latest_adj_close")) or num(row.get("latest_close"))
        if ticker in DEFAULT_ETF_UNIVERSE and day and price is not None and price > 0:
            series[ticker][day] = price

    etf_refresh = read_csv(IN_ETF_REFRESH)
    audit.extend(source_audit_for_rows(IN_ETF_REFRESH, "ETF_PRICE_REFRESH_CACHE", "ticker", "latest_price_date", ["latest_price"], etf_refresh))
    for row in etf_refresh:
        ticker = clean(row.get("ticker")).upper()
        day = parse_date(row.get("latest_price_date"))
        price = num(row.get("latest_price"))
        if ticker in DEFAULT_ETF_UNIVERSE and day and price is not None and price > 0:
            series[ticker][day] = price

    return {ticker: dict(sorted(rows.items())) for ticker, rows in series.items()}, audit


def compute_components(series: dict[str, dict[str, float]]) -> list[dict[str, object]]:
    rows = []
    scored: list[tuple[str, float]] = []
    for ticker in DEFAULT_ETF_UNIVERSE:
        points = series.get(ticker, {})
        dates = sorted(points)
        if len(dates) < LOOKBACK_60 + 1:
            latest_date = dates[-1] if dates else ""
            latest_price = points[latest_date] if latest_date else None
            rows.append({
                "etf_ticker": ticker,
                "latest_date": latest_date,
                "latest_price": fmt(latest_price),
                "component_status": "INSUFFICIENT_HISTORY",
                "warning_reason": "Need at least 61 daily prices for 60D momentum.",
            })
            continue
        prices = [points[d] for d in dates]
        latest = prices[-1]
        mom20 = latest / prices[-21] - 1.0
        mom60 = latest / prices[-61] - 1.0
        recent_returns = returns(prices[-21:])
        vol20 = math.sqrt(sum((r - mean(recent_returns)) ** 2 for r in recent_returns) / len(recent_returns)) if recent_returns else 0.0
        high20 = max(prices[-20:])
        drawdown20 = latest / high20 - 1.0 if high20 > 0 else 0.0
        ma20 = mean(prices[-20:])
        ma60 = mean(prices[-60:])
        trend_bonus = 0.02 if latest > ma20 and latest > ma60 else -0.02
        trend = "PRICE_ABOVE_20D_AND_60D_MA" if trend_bonus > 0 else "PRICE_BELOW_20D_OR_60D_MA"
        risk_penalty = vol20 + abs(min(0.0, drawdown20))
        final_score = mom20 + (0.5 * mom60) + trend_bonus - risk_penalty
        scored.append((ticker, final_score))
        rows.append({
            "etf_ticker": ticker,
            "latest_date": dates[-1],
            "latest_price": fmt(latest),
            "momentum_20d": fmt(mom20),
            "momentum_60d": fmt(mom60),
            "volatility_20d": fmt(vol20),
            "drawdown_20d": fmt(drawdown20),
            "trend_filter_status": trend,
            "final_score": fmt(final_score),
            "component_status": "PASS",
            "warning_reason": "",
        })
    ranks = {ticker: str(rank) for rank, (ticker, _score) in enumerate(sorted(scored, key=lambda item: (-item[1], item[0])), start=1)}
    for row in rows:
        row["rank"] = ranks.get(row["etf_ticker"], "")
    return rows


def freshness(latest_input_date: str) -> dict[str, object]:
    run_day = datetime.now(timezone.utc).date()
    if not latest_input_date:
        return {
            "current_run_date": run_day.isoformat(),
            "latest_input_date": "",
            "age_calendar_days": "",
            "freshness_status": "UNKNOWN_DATE_WARN",
            "warning_reason": "No reliable latest ETF input date.",
        }
    selected = date.fromisoformat(latest_input_date)
    age = (run_day - selected).days
    if age <= 3:
        status, warning = "FRESH", ""
    else:
        status, warning = "STALE_WARN", "Latest ETF input date is older than 3 calendar days."
    return {
        "current_run_date": run_day.isoformat(),
        "latest_input_date": latest_input_date,
        "age_calendar_days": str(age),
        "freshness_status": status,
        "warning_reason": warning,
    }


def build_selection(components: list[dict[str, object]], fresh: dict[str, object]) -> dict[str, object]:
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    valid = [row for row in components if row.get("component_status") == "PASS" and row.get("final_score")]
    if not valid:
        return {
            "current_selected_etf": "UNKNOWN",
            "etf_rotation_signal": "NO_VALID_ETF_SIGNAL",
            "selection_date": "",
            "selection_logic_source": "FALLBACK_ETF_ROTATION_LOGIC",
            "selection_logic_status": "NO_VALID_COMPONENTS",
            "etf_universe_used": ";".join(DEFAULT_ETF_UNIVERSE),
            "freshness_status": "UNAVAILABLE",
            "input_coverage_status": "NO_ETF_INPUTS_AVAILABLE",
            "resolution_status": "UNKNOWN",
            "current_observation_condition_for_v20_206": "CURRENT_SELECTED_ETF_UNKNOWN",
            "observation_allowed_if_rule_v20_206_applied": "FALSE",
            "non_spy_edge_disabled": "TRUE",
            "reason": "No ETF inputs had enough history for fallback scoring.",
            "created_at": created,
        }
    ordered = sorted(valid, key=lambda row: (-(num(row["final_score"]) or -999.0), clean(row["etf_ticker"])))
    best = ordered[0]
    second = ordered[1] if len(ordered) > 1 else {}
    selected = clean(best["etf_ticker"])
    best_score = num(best["final_score"]) or 0.0
    second_score = num(second.get("final_score")) if second else None
    coverage = "PASS" if all(any(row["etf_ticker"] == ticker and row.get("component_status") == "PASS" for row in valid) for ticker in REQUIRED_FOR_SELECTION) else "PARTIAL_ETF_INPUT_COVERAGE"
    return {
        "current_selected_etf": selected,
        "etf_rotation_signal": f"FALLBACK_20D_60D_RISK_ADJUSTED_SELECTED_{selected}",
        "selection_date": clean(best["latest_date"]),
        "selection_logic_source": "FALLBACK_ETF_ROTATION_LOGIC",
        "selection_logic_status": "FALLBACK_SCORE_SELECTED",
        "etf_universe_used": ";".join([row["etf_ticker"] for row in valid]),
        "selected_etf_score": fmt(best_score),
        "second_best_etf": clean(second.get("etf_ticker")) if second else "",
        "second_best_score": fmt(second_score),
        "score_gap": fmt(best_score - second_score) if second_score is not None else "",
        "freshness_status": fresh["freshness_status"],
        "input_coverage_status": coverage,
        "resolution_status": "RESOLVED",
        "current_observation_condition_for_v20_206": "SELECTED_ETF_EQ_SPY" if selected == "SPY" else "SELECTED_ETF_NOT_SPY",
        "observation_allowed_if_rule_v20_206_applied": "TRUE" if selected == "SPY" else "FALSE",
        "non_spy_edge_disabled": "FALSE" if selected == "SPY" else "TRUE",
        "reason": "Selected highest valid fallback ETF rotation score from local ETF price inputs.",
        "created_at": created,
    }


def build_gate(selection: dict[str, object]) -> dict[str, object]:
    selected = selection["current_selected_etf"]
    freshness_status = selection["freshness_status"]
    if selection["resolution_status"] != "RESOLVED":
        final_status = PARTIAL_UNKNOWN
        reason = "Current ETF selection is UNKNOWN because ETF inputs are unavailable or insufficient."
    elif freshness_status == "STALE_WARN":
        final_status = PARTIAL_STALE
        reason = "Current ETF selection resolved but ETF inputs are stale."
    elif selected == "SPY":
        final_status = PASS_SPY
        reason = "Current ETF selection refreshed to SPY."
    else:
        final_status = PASS_NON_SPY
        reason = f"Current ETF selection refreshed to non-SPY ETF {selected}."
    return {
        "final_status": final_status,
        "current_selected_etf": selected,
        "selection_date": selection.get("selection_date", ""),
        "selection_logic_source": selection.get("selection_logic_source", ""),
        "selection_logic_status": selection.get("selection_logic_status", ""),
        "input_coverage_status": selection.get("input_coverage_status", ""),
        "freshness_status": freshness_status,
        "observation_allowed_if_rule_v20_206_applied": selection.get("observation_allowed_if_rule_v20_206_applied", "FALSE"),
        "non_spy_edge_disabled": selection.get("non_spy_edge_disabled", "TRUE"),
        "research_only": "TRUE",
        "official_weight_mutated": "FALSE",
        "official_recommendation_created": "FALSE",
        "real_book_signal_created": "FALSE",
        "broker_execution_supported": "FALSE",
        "trade_action_created": "FALSE",
        "shadow_weight_change_recommended": "FALSE",
        "next_stage_allowed": "TRUE",
        "reason": reason,
        "next_recommended_action": "Feed V20_209_CURRENT_ETF_ROTATION_SELECTION_REFRESH.csv into the next research-only report observation integration stage.",
    }


def write_report(gate: dict[str, object], selection: dict[str, object], components: list[dict[str, object]], fresh: dict[str, object]) -> None:
    READ_CENTER.mkdir(parents=True, exist_ok=True)
    score_lines = [
        f"- {row['etf_ticker']}: rank={row.get('rank', '')}, latest_date={row.get('latest_date', '')}, score={row.get('final_score', '')}, status={row.get('component_status', '')}"
        for row in sorted(components, key=lambda row: int(row.get("rank") or 999))
    ]
    lines = [
        "# V20.209 Current ETF Rotation Selection Refresh Report",
        "",
        f"- Final status: {gate.get('final_status', '')}",
        "- V20.209 was needed because V20.208 resolved a stale current selected_etf from historical benchmark outcome rows.",
        f"- ETF universe used: {selection.get('etf_universe_used', ';'.join(DEFAULT_ETF_UNIVERSE))}",
        f"- Selection logic source: {selection.get('selection_logic_source', '')}",
        f"- Input freshness: {fresh.get('freshness_status', '')}; latest_input_date={fresh.get('latest_input_date', '')}; age_days={fresh.get('age_calendar_days', '')}",
        f"- Current selected ETF: {selection.get('current_selected_etf', '')}",
        "",
        "Score table summary:",
        *score_lines,
        "",
        f"- V20.206 SPY condition satisfied: {'TRUE' if selection.get('current_selected_etf') == 'SPY' and selection.get('resolution_status') == 'RESOLVED' else 'FALSE'}",
        f"- Current observation allowed under V20.206 rule: {selection.get('observation_allowed_if_rule_v20_206_applied', '')}",
        f"- Next recommended stage: {gate.get('next_recommended_action', '')}",
        "",
        "Safety statement:",
        "- official weights were not changed",
        "- no official recommendation was created",
        "- no real-book signal was created",
        "- no broker execution was created",
        "- no trade action was created",
        "- no shadow weight change was recommended",
        "- existing daily reports were not overwritten",
    ]
    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def blocked_outputs(reason: str) -> int:
    fresh = {"current_run_date": datetime.now(timezone.utc).date().isoformat(), "latest_input_date": "", "age_calendar_days": "", "freshness_status": "UNAVAILABLE", "warning_reason": reason}
    selection = {
        "current_selected_etf": "UNKNOWN",
        "etf_rotation_signal": "NO_VALID_ETF_SIGNAL",
        "selection_date": "",
        "selection_logic_source": "FALLBACK_ETF_ROTATION_LOGIC",
        "selection_logic_status": "EXECUTION_FAILED",
        "etf_universe_used": ";".join(DEFAULT_ETF_UNIVERSE),
        "freshness_status": "UNAVAILABLE",
        "input_coverage_status": "NO_ETF_INPUTS_AVAILABLE",
        "resolution_status": "UNKNOWN",
        "current_observation_condition_for_v20_206": "CURRENT_SELECTED_ETF_UNKNOWN",
        "observation_allowed_if_rule_v20_206_applied": "FALSE",
        "non_spy_edge_disabled": "TRUE",
        "reason": reason,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    gate = build_gate(selection)
    gate["final_status"] = BLOCKED_FAILED
    gate["next_stage_allowed"] = "FALSE"
    gate["reason"] = reason
    write_csv(OUT_SELECTION, SELECTION_FIELDS, [selection])
    write_csv(OUT_INPUT, INPUT_FIELDS, [])
    write_csv(OUT_COMPONENTS, COMPONENT_FIELDS, [])
    write_csv(OUT_FRESHNESS, FRESHNESS_FIELDS, [fresh])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate, selection, [], fresh)
    print(f"FINAL_STATUS={BLOCKED_FAILED}")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_WEIGHT_MUTATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_SIGNAL_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("SHADOW_WEIGHT_CHANGE_RECOMMENDED=FALSE")
    return 0


def main() -> int:
    try:
        series, input_audit = load_price_series()
        components = compute_components(series)
        latest_dates = [clean(row.get("latest_date")) for row in components if row.get("component_status") == "PASS" and clean(row.get("latest_date"))]
        fresh = freshness(max(latest_dates) if latest_dates else "")
        selection = build_selection(components, fresh)
        gate = build_gate(selection)
        write_csv(OUT_SELECTION, SELECTION_FIELDS, [selection])
        write_csv(OUT_INPUT, INPUT_FIELDS, input_audit)
        write_csv(OUT_COMPONENTS, COMPONENT_FIELDS, components)
        write_csv(OUT_FRESHNESS, FRESHNESS_FIELDS, [fresh])
        write_csv(OUT_GATE, GATE_FIELDS, [gate])
        write_report(gate, selection, components, fresh)
        print(f"FINAL_STATUS={gate['final_status']}")
        print(f"CURRENT_SELECTED_ETF={gate['current_selected_etf']}")
        print(f"FRESHNESS_STATUS={gate['freshness_status']}")
        print(f"OBSERVATION_ALLOWED_IF_RULE_V20_206_APPLIED={gate['observation_allowed_if_rule_v20_206_applied']}")
        print("RESEARCH_ONLY=TRUE")
        print("OFFICIAL_WEIGHT_MUTATED=FALSE")
        print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
        print("REAL_BOOK_SIGNAL_CREATED=FALSE")
        print("BROKER_EXECUTION_SUPPORTED=FALSE")
        print("TRADE_ACTION_CREATED=FALSE")
        print("SHADOW_WEIGHT_CHANGE_RECOMMENDED=FALSE")
        return 0
    except Exception as exc:  # pragma: no cover
        return blocked_outputs(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
