#!/usr/bin/env python
"""V21.048-R1 context selectivity audit and repair.

Research-only. Audits context coverage in the latest current daily observation
ledger and rebuilds contexts from ticker/date-specific technical predicates.
No official, shadow-adoption, recommendation, weight, ranking, or trade
artifact is modified.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


STAGE = "V21.048-R1_CONTEXT_SELECTIVITY_AUDIT_AND_REPAIR"
PASS_STATUS = "PASS_V21_048_R1_CONTEXT_SELECTIVITY_REPAIRED"
PARTIAL_STATUS = "PARTIAL_PASS_V21_048_R1_CONTEXT_SELECTIVITY_AUDITED_REPAIR_LIMITED"
NO_PREDICATES_STATUS = "BLOCKED_V21_048_R1_NO_SELECTIVE_CONTEXT_PREDICATES_FOUND"
INVALID_STATUS = "BLOCKED_V21_048_R1_INPUT_MISSING_OR_INVALID"

GLOBAL_CONTEXTS = {
    "BASELINE", "BASELINE_UNSEGMENTED", "ALL_MARKET", "ALL_MARKETS",
    "UNIVERSE", "GLOBAL", "GLOBAL_FALLBACK",
}
REQUIRED_COLUMNS = {
    "observation_id", "as_of_date", "ticker", "lane_id",
    "forward_return_window", "maturity_status",
}

SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "source_input_path", "source_row_count",
    "repaired_row_count", "distinct_ticker_count", "original_context_count",
    "repaired_context_count", "original_max_context_ticker_coverage_ratio",
    "repaired_max_context_ticker_coverage_ratio",
    "repaired_min_context_ticker_coverage_ratio",
    "broadcast_context_count_before", "broadcast_context_count_after",
    "context_selectivity_gate_pass", "alpha_interpretation_allowed",
    "official_use_allowed", "shadow_adoption_allowed", "trade_action_allowed",
    "research_only", "created_at_utc",
]

COVERAGE_FIELDS = [
    "audit_phase", "context_label", "row_count", "distinct_ticker_count",
    "total_distinct_ticker_count", "ticker_coverage_ratio",
    "distinct_as_of_date_count", "distinct_lane_count", "distinct_window_count",
    "global_fallback_context", "broadcast_context", "selectivity_status",
]


def clean(value: object) -> str:
    return str(value or "").strip()


def norm(value: object) -> str:
    return clean(value).upper().replace("-", "_").replace(" ", "_")


def yes(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def fnum(value: object) -> float | None:
    try:
        result = float(clean(value))
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def is_matured_status(value: object) -> bool:
    status = norm(value)
    return status.startswith("MATURED") and "NOT_MATURED" not in status


def rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists() or path.stat().st_size == 0:
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def is_global_context(label: object) -> bool:
    value = norm(label)
    return value in GLOBAL_CONTEXTS or value.startswith("BASELINE_") or value.startswith("ALL_MARKET_")


def context_field(fields: list[str]) -> str:
    for candidate in ("context_label", "context_key", "repaired_context_label"):
        if candidate in fields:
            return candidate
    return ""


def discover_source(root: Path) -> Path | None:
    preferred = [
        root / "outputs/v21/shadow_observation/V21_030_R1_CURRENT_DAILY_MATURITY_STATUS_LEDGER.csv",
        root / "outputs/v21/shadow_observation/V21_029_R1_CURRENT_DAILY_SHADOW_OBSERVATION_LEDGER.csv",
    ]
    for path in preferred:
        rows, fields = read_csv(path)
        if rows and REQUIRED_COLUMNS.issubset(fields) and context_field(fields):
            return path
    candidates: list[tuple[str, float, Path]] = []
    out = root / "outputs/v21"
    if out.exists():
        for path in out.rglob("*.csv"):
            if "048_R1" in path.name.upper():
                continue
            rows, fields = read_csv(path)
            if not rows or not REQUIRED_COLUMNS.issubset(fields) or not context_field(fields):
                continue
            latest_date = max(clean(row.get("as_of_date"))[:10] for row in rows)
            candidates.append((latest_date, path.stat().st_mtime, path))
    return max(candidates, default=("", 0.0, None))[2]


def discover_predicate_source(root: Path, dates: set[str], tickers: set[str]) -> Path | None:
    preferred = root / "outputs/v21/factors/V21_038_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv"
    candidates = [preferred]
    factors = root / "outputs/v21/factors"
    if factors.exists():
        candidates.extend(
            path for path in factors.rglob("*.csv")
            if path != preferred and "048_R1" not in path.name.upper()
        )
    required_any = {
        "rsi_14", "kdj_cross_state", "macd_hist", "bb_position", "ma50_distance",
        "ema20_distance", "momentum_5", "overheat_extension_score", "trend_strength_score",
    }
    best: tuple[int, int, float, Path | None] = (0, 0, 0.0, None)
    for path in candidates:
        rows, fields = read_csv(path)
        if not rows or not {"as_of_date", "ticker"}.issubset(fields):
            continue
        predicate_count = len(required_any.intersection(fields))
        if predicate_count == 0:
            continue
        matched = sum(
            1 for row in rows
            if clean(row.get("as_of_date"))[:10] in dates and norm(row.get("ticker")) in tickers
        )
        score = (matched, predicate_count, path.stat().st_mtime, path)
        if score[:3] > best[:3]:
            best = score
    return best[3]


def coverage(rows: list[dict[str, str]], label_field: str, phase: str) -> list[dict[str, object]]:
    total_tickers = len({norm(row.get("ticker")) for row in rows if clean(row.get("ticker"))})
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        label = clean(row.get(label_field)) or "BASELINE_UNSEGMENTED"
        groups[label].append(row)
    result: list[dict[str, object]] = []
    for label, items in sorted(groups.items()):
        tickers = {norm(row.get("ticker")) for row in items if clean(row.get("ticker"))}
        ratio = len(tickers) / total_tickers if total_tickers else 0.0
        global_context = is_global_context(label)
        broadcast = ratio >= 0.95 and not global_context
        result.append({
            "audit_phase": phase,
            "context_label": label,
            "row_count": len(items),
            "distinct_ticker_count": len(tickers),
            "total_distinct_ticker_count": total_tickers,
            "ticker_coverage_ratio": f"{ratio:.10f}",
            "distinct_as_of_date_count": len({clean(row.get("as_of_date"))[:10] for row in items}),
            "distinct_lane_count": len({clean(row.get("lane_id")) for row in items}),
            "distinct_window_count": len({clean(row.get("forward_return_window")) for row in items}),
            "global_fallback_context": yes(global_context),
            "broadcast_context": yes(broadcast),
            "selectivity_status": "GLOBAL_FALLBACK_EXEMPT" if global_context else "BROADCAST_CONTEXT" if broadcast else "SELECTIVE_CONTEXT",
        })
    return result


def selective_labels(row: dict[str, str]) -> list[tuple[str, str]]:
    labels: list[tuple[str, str]] = []
    rsi = fnum(row.get("rsi_14"))
    if rsi is not None:
        if rsi >= 70:
            labels.append(("RSI_OVERBOUGHT", "rsi_14>=70"))
        elif rsi <= 30:
            labels.append(("RSI_OVERSOLD", "rsi_14<=30"))
        elif rsi >= 55:
            labels.append(("RSI_BULLISH", "55<=rsi_14<70"))
        elif rsi <= 45:
            labels.append(("RSI_BEARISH", "30<rsi_14<=45"))

    cross = norm(row.get("kdj_cross_state"))
    if cross in {"GOLDEN_CROSS", "DEATH_CROSS"}:
        labels.append((f"KDJ_{cross}", f"kdj_cross_state={cross}"))

    macd = fnum(row.get("macd_hist"))
    if macd is not None and macd > 0:
        labels.append(("MACD_HIST_POSITIVE", "macd_hist>0"))
    elif macd is not None and macd < 0:
        labels.append(("MACD_HIST_NEGATIVE", "macd_hist<0"))

    ma50 = fnum(row.get("ma50_distance"))
    if ma50 is not None and ma50 >= 0.05:
        labels.append(("PRICE_ABOVE_MA50_5PCT", "ma50_distance>=0.05"))
    elif ma50 is not None and ma50 <= -0.05:
        labels.append(("PRICE_BELOW_MA50_5PCT", "ma50_distance<=-0.05"))

    bb = fnum(row.get("bb_position"))
    if bb is not None and bb >= 0.8:
        labels.append(("BB_UPPER_ZONE", "bb_position>=0.8"))
    elif bb is not None and bb <= 0.2:
        labels.append(("BB_LOWER_ZONE", "bb_position<=0.2"))

    overheat = fnum(row.get("overheat_extension_score"))
    if overheat is not None and overheat >= 0.70:
        labels.append(("OVERHEAT_HIGH", "overheat_extension_score>=0.70"))

    momentum = fnum(row.get("momentum_5"))
    trend = fnum(row.get("trend_strength_score"))
    if momentum is not None and trend is not None and momentum < 0 and trend >= 0.55:
        labels.append(("PULLBACK_IN_STRONG_TREND", "momentum_5<0 and trend_strength_score>=0.55"))

    # Stable order and no duplicate labels.
    return list(dict.fromkeys(labels))


def deterministic_id(row: dict[str, str], label: str) -> str:
    basis = "|".join([
        clean(row.get("as_of_date"))[:10],
        norm(row.get("ticker")),
        clean(row.get("lane_id")),
        clean(row.get("forward_return_window")),
        label,
    ])
    return "V21_048_R1_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24].upper()


def repair_ledger(
    source_rows: list[dict[str, str]],
    source_fields: list[str],
    predicate_rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[str], int]:
    predicate_map = {
        (clean(row.get("as_of_date"))[:10], norm(row.get("ticker"))): row
        for row in predicate_rows
        if clean(row.get("as_of_date")) and clean(row.get("ticker"))
    }
    # Remove the broadcast context dimension before applying selective labels.
    base: dict[tuple[str, str, str, str], dict[str, str]] = {}
    for row in source_rows:
        key = (
            clean(row.get("as_of_date"))[:10], norm(row.get("ticker")),
            clean(row.get("lane_id")), clean(row.get("forward_return_window")),
        )
        base.setdefault(key, row)

    output: list[dict[str, str]] = []
    matched_predicate_rows = 0
    extra_fields = [
        "original_observation_id", "original_context_label",
        "repaired_context_label", "context_predicate",
        "context_repair_status", "repaired_observation_id",
    ]
    output_fields = list(dict.fromkeys(source_fields + extra_fields))
    source_label_field = context_field(source_fields)
    for key, original in sorted(base.items()):
        predicate = predicate_map.get((key[0], key[1]))
        labels = selective_labels(predicate or {})
        if predicate and labels:
            matched_predicate_rows += 1
        if not labels:
            labels = [("BASELINE_UNSEGMENTED", "no_selective_predicate_satisfied")]
        for label, rule in labels:
            repaired = dict(original)
            repaired_id = deterministic_id(original, label)
            repaired["original_observation_id"] = clean(original.get("observation_id"))
            repaired["original_context_label"] = clean(original.get(source_label_field))
            repaired["repaired_context_label"] = label
            repaired["context_label"] = label
            repaired["context_key"] = label
            repaired["context_predicate"] = rule
            repaired["context_repair_status"] = (
                "SELECTIVE_TICKER_DATE_PREDICATE_APPLIED"
                if label != "BASELINE_UNSEGMENTED" else "BASELINE_ONLY_NO_SELECTIVE_PREDICATE"
            )
            repaired["repaired_observation_id"] = repaired_id
            repaired["observation_id"] = repaired_id
            repaired["research_only"] = "TRUE"
            output.append(repaired)
    return output, output_fields, matched_predicate_rows


def evaluate(
    source_rows: list[dict[str, str]],
    source_fields: list[str],
    predicate_rows: list[dict[str, str]],
    source_path: str,
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, str]], list[str]]:
    label_field = context_field(source_fields)
    valid = bool(source_rows and label_field and REQUIRED_COLUMNS.issubset(source_fields))
    original_coverage = coverage(source_rows, label_field, "ORIGINAL") if valid else []
    repaired_rows: list[dict[str, str]] = []
    repaired_fields: list[str] = list(source_fields)
    matched = 0
    if valid and predicate_rows:
        repaired_rows, repaired_fields, matched = repair_ledger(source_rows, source_fields, predicate_rows)
    repaired_coverage = coverage(repaired_rows, "repaired_context_label", "REPAIRED") if repaired_rows else []

    before_broadcast = sum(row["broadcast_context"] == "TRUE" for row in original_coverage)
    after_broadcast = sum(row["broadcast_context"] == "TRUE" for row in repaired_coverage)
    repaired_non_global = [row for row in repaired_coverage if row["global_fallback_context"] == "FALSE"]
    selective_after = any(float(row["ticker_coverage_ratio"]) < 0.95 for row in repaired_non_global)
    unique_ids = len({row.get("observation_id", "") for row in repaired_rows}) == len(repaired_rows)
    gate_pass = bool(repaired_rows and matched and selective_after and after_broadcast < before_broadcast and unique_ids)
    matured_with_returns = sum(
        1 for row in repaired_rows
        if is_matured_status(row.get("maturity_status"))
        and fnum(row.get("realized_forward_return")) is not None
    )

    if not valid:
        status = INVALID_STATUS
        decision = "BLOCK_CONTEXT_SELECTIVITY_REPAIR_INPUT_MISSING_OR_INVALID"
    elif not predicate_rows or matched == 0:
        status = NO_PREDICATES_STATUS
        decision = "BLOCK_CONTEXT_SELECTIVITY_REPAIR_NO_RELIABLE_TICKER_DATE_PREDICATES"
    elif gate_pass:
        status = PASS_STATUS
        decision = "USE_REPAIRED_RESEARCH_ONLY_CONTEXT_LEDGER_PENDING_FORWARD_RETURN_MATURITY"
    else:
        status = PARTIAL_STATUS
        decision = "CONTEXT_SELECTIVITY_AUDITED_REPAIR_LIMITED_KEEP_ALPHA_INTERPRETATION_BLOCKED"

    original_ratios = [float(row["ticker_coverage_ratio"]) for row in original_coverage]
    repaired_ratios = [float(row["ticker_coverage_ratio"]) for row in repaired_coverage]
    summary = {
        "stage": STAGE,
        "final_status": status,
        "decision": decision,
        "source_input_path": source_path,
        "source_row_count": len(source_rows),
        "repaired_row_count": len(repaired_rows),
        "distinct_ticker_count": len({norm(row.get("ticker")) for row in source_rows}),
        "original_context_count": len(original_coverage),
        "repaired_context_count": len(repaired_coverage),
        "original_max_context_ticker_coverage_ratio": f"{max(original_ratios, default=0):.10f}",
        "repaired_max_context_ticker_coverage_ratio": f"{max(repaired_ratios, default=0):.10f}",
        "repaired_min_context_ticker_coverage_ratio": f"{min(repaired_ratios, default=0):.10f}",
        "broadcast_context_count_before": before_broadcast,
        "broadcast_context_count_after": after_broadcast,
        "context_selectivity_gate_pass": yes(gate_pass),
        "alpha_interpretation_allowed": yes(gate_pass and matured_with_returns > 0),
        "official_use_allowed": "FALSE",
        "shadow_adoption_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "research_only": "TRUE",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    return summary, original_coverage + repaired_coverage, repaired_rows, repaired_fields


def report(summary: dict[str, object], coverage_rows: list[dict[str, object]], predicate_path: str) -> str:
    original = [row for row in coverage_rows if row["audit_phase"] == "ORIGINAL"]
    repaired = [row for row in coverage_rows if row["audit_phase"] == "REPAIRED"]
    table = lambda rows: "\n".join(
        f"| {row['context_label']} | {row['row_count']} | {row['distinct_ticker_count']} | "
        f"{row['ticker_coverage_ratio']} | {row['broadcast_context']} |"
        for row in rows
    ) or "| NONE | 0 | 0 | 0 | FALSE |"
    return f"""# V21.048-R1 Context Selectivity Audit and Repair

## Decision

- final_status: {summary['final_status']}
- decision: {summary['decision']}
- source_input_path: {summary['source_input_path']}
- predicate_source_path: {predicate_path or 'NOT_AVAILABLE'}
- context_selectivity_gate_pass: {summary['context_selectivity_gate_pass']}
- alpha_interpretation_allowed: {summary['alpha_interpretation_allowed']}

## Original Context Coverage

| Context | Rows | Tickers | Coverage | Broadcast |
|---|---:|---:|---:|---|
{table(original)}

## Repaired Context Coverage

| Context | Rows | Tickers | Coverage | Broadcast |
|---|---:|---:|---:|---|
{table(repaired)}

## Guardrails

- research_only: TRUE
- official_use_allowed: FALSE
- shadow_adoption_allowed: FALSE
- trade_action_allowed: FALSE

Alpha interpretation additionally requires matured realized forward-return
evidence. Context selectivity alone does not authorize an alpha conclusion.
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--source", type=Path)
    parser.add_argument("--predicate-source", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    out_context = root / "outputs/v21/context"
    out_read = root / "outputs/v21/read_center"
    summary_path = out_context / "V21_048_R1_CONTEXT_SELECTIVITY_AUDIT_SUMMARY.csv"
    coverage_path = out_context / "V21_048_R1_CONTEXT_COVERAGE_BY_CONTEXT.csv"
    ledger_path = out_context / "V21_048_R1_REPAIRED_CONTEXT_OBSERVATION_LEDGER.csv"
    report_path = out_read / "V21_048_R1_CONTEXT_SELECTIVITY_AUDIT_AND_REPAIR_REPORT.md"

    source = args.source or discover_source(root)
    source_rows, source_fields = read_csv(source) if source else ([], [])
    dates = {clean(row.get("as_of_date"))[:10] for row in source_rows}
    tickers = {norm(row.get("ticker")) for row in source_rows}
    predicate_source = args.predicate_source or discover_predicate_source(root, dates, tickers)
    predicate_rows, _ = read_csv(predicate_source) if predicate_source else ([], [])
    predicate_rows = [
        row for row in predicate_rows
        if clean(row.get("as_of_date"))[:10] in dates and norm(row.get("ticker")) in tickers
    ]
    source_text = rel(root, source) if source else "NOT_AVAILABLE"
    summary, coverage_rows, repaired_rows, repaired_fields = evaluate(
        source_rows, source_fields, predicate_rows, source_text
    )
    write_csv(summary_path, [summary], SUMMARY_FIELDS)
    write_csv(coverage_path, coverage_rows, COVERAGE_FIELDS)
    if repaired_rows:
        write_csv(ledger_path, repaired_rows, repaired_fields)
    elif ledger_path.exists():
        ledger_path.unlink()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    predicate_text = rel(root, predicate_source) if predicate_source else ""
    report_path.write_text(report(summary, coverage_rows, predicate_text), encoding="utf-8")
    for field in (
        "final_status", "decision", "source_input_path",
        "context_selectivity_gate_pass", "alpha_interpretation_allowed",
    ):
        print(f"{field.upper()}={summary[field]}")
    print("OFFICIAL_USE_ALLOWED=FALSE")
    print("SHADOW_ADOPTION_ALLOWED=FALSE")
    print("TRADE_ACTION_ALLOWED=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
