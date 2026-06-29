#!/usr/bin/env python
"""V21.003 risk/regime recalibration plan.

Audit-only and plan-only stage. No official weights, rankings, recommendations,
trade actions, broker execution, or real-book behavior are changed.
"""

from __future__ import annotations

import csv
import math
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median


STAGE_NAME = "V21_003_RISK_REGIME_RECALIBRATION_PLAN"
ROOT = Path(__file__).resolve().parents[2]
V20_DIR = ROOT / "outputs" / "v20"
V21_AUDIT_DIR = ROOT / "outputs" / "v21" / "audit"
V21_ABLATION_DIR = ROOT / "outputs" / "v21" / "ablation"
OUT_DIR = ROOT / "outputs" / "v21" / "recalibration"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

REQ_INPUTS = [
    V21_AUDIT_DIR / "V21_001_FORWARD_OUTCOME_ROWS.csv",
    V21_AUDIT_DIR / "V21_001_BENCHMARK_RELATIVE_PERFORMANCE.csv",
    V21_AUDIT_DIR / "V21_001_FAILURE_CASES_TOP_RANKED.csv",
    V21_AUDIT_DIR / "V21_001_NEXT_STAGE_GATE.csv",
    V21_ABLATION_DIR / "V21_002_BASELINE_JOINED_FACTOR_OUTCOME_ROWS.csv",
    V21_ABLATION_DIR / "V21_002_SINGLE_FACTOR_FAMILY_PERFORMANCE.csv",
    V21_ABLATION_DIR / "V21_002_LEAVE_ONE_FAMILY_OUT_PERFORMANCE.csv",
    V21_ABLATION_DIR / "V21_002_FACTOR_REMOVAL_IMPACT.csv",
    V21_ABLATION_DIR / "V21_002_RANKING_WEAKNESS_DIAGNOSIS.csv",
    V21_ABLATION_DIR / "V21_002_NEXT_STAGE_GATE.csv",
]

INPUT_DISCOVERY = OUT_DIR / "V21_003_INPUT_DISCOVERY.csv"
FIELD_MAP = OUT_DIR / "V21_003_RISK_REGIME_FIELD_MAP.csv"
JOINED_ROWS = OUT_DIR / "V21_003_RISK_REGIME_JOINED_OUTCOME_ROWS.csv"
REGIME_SEGMENT_PERF = OUT_DIR / "V21_003_REGIME_SEGMENT_PERFORMANCE.csv"
RISK_DECILE_PERF = OUT_DIR / "V21_003_RISK_SCORE_DECILE_PERFORMANCE.csv"
OVERHEAT_FALSE_BLOCK = OUT_DIR / "V21_003_OVERHEAT_FALSE_BLOCK_AUDIT.csv"
RISK_OVERPENALIZATION = OUT_DIR / "V21_003_RISK_OVERPENALIZATION_CANDIDATES.csv"
REGIME_MISALIGNMENT = OUT_DIR / "V21_003_REGIME_MISALIGNMENT_CANDIDATES.csv"
SCENARIOS = OUT_DIR / "V21_003_RECALIBRATION_SCENARIOS.csv"
PLAN = OUT_DIR / "V21_003_RECALIBRATION_PLAN.csv"
GATE = OUT_DIR / "V21_003_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER_DIR / "V21_003_RISK_REGIME_RECALIBRATION_PLAN_REPORT.md"

ALLOWED_FINAL_STATUSES = {
    "FAIL_V21_003_REQUIRED_INPUTS_MISSING",
    "FAIL_V21_003_NO_RISK_REGIME_FIELDS_DETECTED",
    "PARTIAL_PASS_V21_003_LIMITED_RISK_REGIME_COVERAGE",
    "PARTIAL_PASS_V21_003_RECALIBRATION_EVIDENCE_LIMITED",
    "PASS_V21_003_RISK_REGIME_RECALIBRATION_PLAN_READY",
}
FALSE_FIELDS = [
    "official_weight_mutated",
    "official_recommendation_created",
    "real_book_signal_created",
    "broker_execution_supported",
    "trade_action_created",
    "shadow_weight_activated",
]
BENCHMARKS = ["QQQ", "SOXX", "SPY"]


def norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").strip().lower()).strip("_")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle).fieldnames or [])


def parse_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() in {"NA", "N/A", "NONE", "NULL", "MISSING"}:
        return None
    try:
        num = float(text)
    except ValueError:
        return None
    if math.isnan(num) or math.isinf(num):
        return None
    return num


def parse_int(value: object) -> int | None:
    num = parse_float(value)
    return None if num is None else int(num)


def parse_date(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in [text, text[:10], text.replace("/", "-")]:
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
            try:
                return datetime.strptime(candidate, fmt).date().isoformat()
            except ValueError:
                continue
    return None


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def rel_key(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def discover_inputs() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    keywords = [
        "risk",
        "regime",
        "market_regime",
        "benchmark",
        "qqq",
        "soxx",
        "spy",
        "vix",
        "overheat",
        "drawdown",
        "volatility",
        "technical_status",
        "buy_zone",
        "near_entry",
        "pullback",
        "breakout",
        "entry",
    ]
    for path in sorted(V20_DIR.rglob("*.csv")):
        name = path.name.lower()
        if not any(token in name for token in keywords):
            continue
        try:
            columns = read_header(path)
        except Exception:
            continue
        if not columns:
            continue
        rows.append(
            {
                "artifact_path": rel_key(path),
                "artifact_type": detect_artifact_type(path, columns),
                "exists_non_empty": str(path.exists() and path.stat().st_size > 0).upper(),
                "row_count": row_count(path),
                "detected_columns": "|".join(columns),
                "selected_for_audit": "TRUE",
                "selection_reason": "contains risk/regime/benchmark/status-related local evidence",
                "validation_status": "PASS_RECALIBRATION_SOURCE_DETECTED",
                "_path": path,
                "_columns": columns,
            }
        )
    return rows


def row_count(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return max(sum(1 for _ in handle) - 1, 0)


def detect_artifact_type(path: Path, columns: list[str]) -> str:
    name = path.name.lower()
    if "benchmark" in name:
        return "benchmark"
    if "risk" in name:
        return "risk"
    if "regime" in name:
        return "regime"
    if "strategy" in name:
        return "strategy"
    if "technical" in name:
        return "technical"
    return "other"


def detect_field(columns: list[str], candidates: list[str]) -> str | None:
    lookup = {norm(col): col for col in columns}
    for candidate in candidates:
        if norm(candidate) in lookup:
            return lookup[norm(candidate)]
    for col in columns:
        n = norm(col)
        if any(token in n for token in candidates):
            return col
    return None


def detect_ticker_field(columns: list[str]) -> str | None:
    return detect_field(columns, ["ticker", "symbol"])


def detect_date_field(columns: list[str]) -> str | None:
    return detect_field(columns, ["as_of_date", "signal_date", "date", "snapshot_date"])


def detect_score_field(columns: list[str], tokens: list[str]) -> str | None:
    for col in columns:
        n = norm(col)
        if any(token in n for token in tokens) and "status" not in n and "reason" not in n and "count" not in n:
            return col
    return None


def detect_status_field(columns: list[str], tokens: list[str]) -> str | None:
    for col in columns:
        n = norm(col)
        if "status" in n and any(token in n for token in tokens):
            return col
    return None


def map_field_type(column: str, path: Path) -> tuple[str, str, str]:
    n = norm(column)
    if any(token in n for token in ["risk_score", "risk_contribution", "volatility", "drawdown", "downside", "overheat", "leverage"]):
        return "RISK_SCORE", "high", "column name indicates risk-related score"
    if any(token in n for token in ["regime_score", "market_regime", "etf_regime", "risk_on_off", "macro_regime"]):
        return "REGIME_SCORE", "high", "column name indicates regime score"
    if any(token in n for token in ["benchmark_score", "benchmark_exposure", "benchmark_return", "qqq", "soxx", "spy", "vix"]):
        return "BENCHMARK_CONTEXT", "high", "column name indicates benchmark context"
    if any(token in n for token in ["technical_status"]):
        return "TECHNICAL_STATUS", "high", "column name indicates technical status"
    if any(token in n for token in ["buy_zone", "near_entry", "pullback", "breakout", "entry"]):
        return "ENTRY_STATUS", "high", "column name indicates entry timing status"
    if "overheat" in n:
        return "OVERHEAT_STATUS", "high", "column name indicates overheat status"
    if "volatility" in n:
        return "VOLATILITY_STATUS", "high", "column name indicates volatility status"
    if "drawdown" in n:
        return "DRAWDOWN_STATUS", "high", "column name indicates drawdown status"
    if "benchmark" in n:
        return "BENCHMARK_CONTEXT", "medium", "generic benchmark-related column"
    return "OTHER", "low", "no confident risk/regime mapping"


def discover_field_map() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for artifact in discover_inputs():
        columns: list[str] = artifact["_columns"]  # type: ignore[index]
        path: Path = artifact["_path"]  # type: ignore[index]
        ticker_col = detect_ticker_field(columns)
        date_col = detect_date_field(columns)
        risk_cols = [col for col in columns if map_field_type(col, path)[0] == "RISK_SCORE"]
        regime_cols = [col for col in columns if map_field_type(col, path)[0] == "REGIME_SCORE"]
        benchmark_cols = [col for col in columns if map_field_type(col, path)[0] == "BENCHMARK_CONTEXT"]
        status_cols = [col for col in columns if map_field_type(col, path)[0] in {"OVERHEAT_STATUS", "VOLATILITY_STATUS", "DRAWDOWN_STATUS", "TECHNICAL_STATUS", "ENTRY_STATUS"}]
        score_cols = risk_cols + regime_cols + benchmark_cols + status_cols
        if not score_cols and not ticker_col and not date_col:
            continue
        non_null = {col: 0 for col in score_cols}
        total = 0
        try:
            for row in read_csv(path):
                total += 1
                for col in score_cols:
                    if str(row.get(col, "")).strip():
                        non_null[col] += 1
        except Exception:
            total = 0
        for col in score_cols:
            mapped, conf, reason = map_field_type(col, path)
            rows.append(
                {
                    "source_artifact": rel_key(path),
                    "column_name": col,
                    "mapped_field_type": mapped,
                    "mapping_confidence": conf,
                    "mapping_reason": reason,
                    "non_null_count": non_null.get(col, 0),
                    "coverage_ratio": f"{(non_null.get(col, 0) / max(total, 1)):.10f}",
                    "selected_for_recalibration_audit": "TRUE" if mapped != "OTHER" else "FALSE",
                }
            )
    return rows


def load_v21_sources() -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, str]]:
    for path in REQ_INPUTS:
        if not path.exists():
            raise FileNotFoundError(str(path))
    base_rows = read_csv(V21_ABLATION_DIR / "V21_002_BASELINE_JOINED_FACTOR_OUTCOME_ROWS.csv")
    gate_001 = read_csv(V21_AUDIT_DIR / "V21_001_NEXT_STAGE_GATE.csv")[0]
    gate_002 = read_csv(V21_ABLATION_DIR / "V21_002_NEXT_STAGE_GATE.csv")[0]
    return base_rows, [gate_001, gate_002], {**gate_001, **gate_002}


def build_joined_rows(base_rows: list[dict[str, str]]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for row in base_rows:
        out.append(
            {
                "as_of_date": row.get("as_of_date", ""),
                "ticker": row.get("ticker", ""),
                "rank": row.get("rank", ""),
                "baseline_score": row.get("baseline_detected_score", row.get("baseline_score", row.get("score", ""))),
                "forward_return_5d": row.get("forward_return_5d", ""),
                "forward_return_10d": row.get("forward_return_10d", ""),
                "forward_return_20d": row.get("forward_return_20d", ""),
                "max_drawdown_10d": row.get("max_drawdown_10d", ""),
                "max_gain_10d": row.get("max_gain_10d", ""),
                "excess_return_vs_QQQ_10d": row.get("benchmark_excess_vs_QQQ_10d", row.get("excess_return_vs_QQQ_10d", "")),
                "excess_return_vs_SOXX_10d": row.get("benchmark_excess_vs_SOXX_10d", row.get("excess_return_vs_SOXX_10d", "")),
                "excess_return_vs_SPY_10d": row.get("benchmark_excess_vs_SPY_10d", row.get("excess_return_vs_SPY_10d", "")),
                "risk_score": first_present(row, ["risk_score", "risk_contribution", "normalized_risk_score"]),
                "regime_score": first_present(row, ["market_regime_score", "regime_score", "normalized_market_regime_score"]),
                "market_regime_score": first_present(row, ["market_regime_score", "normalized_market_regime_score"]),
                "benchmark_score": first_present(row, ["benchmark_score", "benchmark_exposure_component_score"]),
                "overheat_status": derive_overheat_status(row),
                "technical_status": derive_technical_status(row),
                "buy_zone_status": derive_label_status(row, ["buy_zone"]),
                "near_entry_status": derive_label_status(row, ["near_entry", "entry"]),
                "pullback_status": derive_label_status(row, ["pullback"]),
                "breakout_status": derive_label_status(row, ["breakout"]),
                "source_artifacts": row.get("source_artifact", "") + ";V21_002_BASELINE_JOINED_FACTOR_OUTCOME_ROWS.csv",
                "raw_status_summary": row.get("raw_status_summary", ""),
                "detected_factor_family_columns": row.get("detected_factor_family_columns", ""),
            }
        )
    return out


def first_present(row: dict[str, str], fields: list[str]) -> str:
    for field in fields:
        if row.get(field, "") != "":
            return row.get(field, "")
    return ""


def derive_overheat_status(row: dict[str, str]) -> str:
    text = " ".join(str(row.get(field, "")) for field in [
        "overheat_status",
        "overheat_penalty_component_score",
        "overheat_component_score",
        "raw_status_summary",
        "detected_label_fields",
    ]).lower()
    if "overheat" in text and any(token in text for token in ["true", "1", "high", "0.7", "0.8", "0.9"]):
        return "OVERHEAT"
    if "overheat" in text:
        return "OVERHEAT_CONTEXT"
    return "NOT_OVERHEAT"


def derive_technical_status(row: dict[str, str]) -> str:
    text = " ".join(str(row.get(field, "")) for field in [
        "technical_status",
        "technical_score",
        "technical_contribution",
        "raw_status_summary",
    ]).lower()
    if "strong" in text or "uptrend" in text or "watch_positive" in text:
        return "TECHNICAL_STRONG"
    if "weak" in text or "downtrend" in text or "watch_negative" in text:
        return "TECHNICAL_WEAK"
    return "TECHNICAL_NEUTRAL"


def derive_label_status(row: dict[str, str], tokens: list[str]) -> str:
    text = " ".join(str(row.get(field, "")) for field in [
        "raw_status_summary",
        "detected_label_fields",
        "source_artifacts",
        "technical_status",
    ]).lower()
    for token in tokens:
        if token in text:
            if token == "buy_zone":
                return "BUY_ZONE" if "buy" in text else "NO_BUY_ZONE"
            if token == "near_entry":
                return "NEAR_ENTRY" if "entry" in text else "NO_NEAR_ENTRY"
            if token == "pullback":
                return "PULLBACK" if "pullback" in text else "NO_PULLBACK"
            if token == "breakout":
                return "BREAKOUT" if "breakout" in text else "NO_BREAKOUT"
            if token == "entry":
                return "ENTRY_CONTEXT"
    return "NO_MATCH"


def numeric_rows(rows: list[dict[str, object]], field: str) -> list[float]:
    return [value for value in (parse_float(row.get(field)) for row in rows) if value is not None]


def avg(values: list[float]) -> str:
    return "" if not values else f"{mean(values):.10f}"


def med(values: list[float]) -> str:
    return "" if not values else f"{median(values):.10f}"


def load_benchmark_series() -> dict[str, dict[str, float]]:
    series: dict[str, dict[str, float]] = defaultdict(dict)
    for path in [V21_AUDIT_DIR / "V21_001_FORWARD_OUTCOME_ROWS.csv"]:
        if not path.exists():
            continue
        for row in read_csv(path):
            as_of = row.get("as_of_date", "")
            for benchmark in BENCHMARKS:
                key = f"excess_return_vs_{benchmark}_10d"
                if row.get(key, "") != "":
                    series[benchmark][as_of] = parse_float(row.get(key)) or 0.0
    return series


def score_deciles(rows: list[dict[str, object]], score_field: str) -> list[dict[str, object]]:
    scored = [row for row in rows if parse_float(row.get(score_field)) is not None and parse_float(row.get("forward_return_10d")) is not None]
    if len(scored) < 10:
        return []
    scored = sorted(scored, key=lambda row: parse_float(row.get(score_field)) or 0.0)
    decile_size = max(len(scored) // 10, 1)
    out: list[dict[str, object]] = []
    for idx in range(10):
        chunk = scored[idx * decile_size : (idx + 1) * decile_size] if idx < 9 else scored[idx * decile_size :]
        if not chunk:
            continue
        vals_10 = numeric_rows(chunk, "forward_return_10d")
        vals_5 = numeric_rows(chunk, "forward_return_5d")
        vals_20 = numeric_rows(chunk, "forward_return_20d")
        dd = numeric_rows(chunk, "max_drawdown_10d")
        gain = numeric_rows(chunk, "max_gain_10d")
        qqq = numeric_rows(chunk, "excess_return_vs_QQQ_10d")
        soxx = numeric_rows(chunk, "excess_return_vs_SOXX_10d")
        spy = numeric_rows(chunk, "excess_return_vs_SPY_10d")
        out.append(
            {
                "score_field": score_field,
                "decile": idx + 1,
                "evaluated_row_count": len(vals_10),
                "avg_forward_return_10d": avg(vals_10),
                "median_forward_return_10d": med(vals_10),
                "hit_rate_10d": f"{(sum(1 for v in vals_10 if v > 0) / len(vals_10)):.10f}" if vals_10 else "",
                "avg_max_drawdown_10d": avg(dd),
                "avg_max_gain_10d": avg(gain),
                "avg_excess_return_vs_QQQ_10d": avg(qqq),
                "avg_excess_return_vs_SOXX_10d": avg(soxx),
                "avg_excess_return_vs_SPY_10d": avg(spy),
                "risk_return_tradeoff_flag": risk_tradeoff_flag(idx + 1, vals_10, dd, qqq, soxx, spy),
            }
        )
    return out


def risk_tradeoff_flag(decile: int, returns: list[float], dd: list[float], qqq: list[float], soxx: list[float], spy: list[float]) -> str:
    if not returns:
        return "INSUFFICIENT_EVIDENCE"
    avg_ret = mean(returns)
    avg_dd = mean(dd) if dd else 0.0
    avg_excess = mean([v for v in qqq + soxx + spy if v is not None]) if any(v is not None for v in qqq + soxx + spy) else 0.0
    if avg_ret > 0 and avg_excess >= 0 and avg_dd > -0.15:
        return "GOOD_RISK_FILTER"
    if avg_ret > 0 and avg_excess < 0:
        return "OVERPENALIZES_WINNERS"
    if avg_ret <= 0 and avg_dd <= -0.2:
        return "WEAK_RISK_FILTER"
    if abs(avg_ret) < 0.01:
        return "MIXED_RISK_FILTER"
    return "INSUFFICIENT_EVIDENCE"


def segment_performance(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    segments = [
        ("overheat_status", set(str(row.get("overheat_status", "")) for row in rows if row.get("overheat_status"))),
        ("technical_status", set(str(row.get("technical_status", "")) for row in rows if row.get("technical_status"))),
        ("buy_zone_status", set(str(row.get("buy_zone_status", "")) for row in rows if row.get("buy_zone_status"))),
        ("near_entry_status", set(str(row.get("near_entry_status", "")) for row in rows if row.get("near_entry_status"))),
        ("pullback_status", set(str(row.get("pullback_status", "")) for row in rows if row.get("pullback_status"))),
        ("breakout_status", set(str(row.get("breakout_status", "")) for row in rows if row.get("breakout_status"))),
    ]
    out: list[dict[str, object]] = []
    for field, values in segments:
        for value in sorted(values):
            chunk = [row for row in rows if str(row.get(field, "")) == value]
            vals10 = numeric_rows(chunk, "forward_return_10d")
            if not vals10:
                continue
            qqq = numeric_rows(chunk, "excess_return_vs_QQQ_10d")
            soxx = numeric_rows(chunk, "excess_return_vs_SOXX_10d")
            spy = numeric_rows(chunk, "excess_return_vs_SPY_10d")
            out.append(
                {
                    "segment_field": field,
                    "segment_value": value,
                    "evaluated_row_count": len(vals10),
                    "avg_forward_return_5d": avg(numeric_rows(chunk, "forward_return_5d")),
                    "avg_forward_return_10d": avg(vals10),
                    "avg_forward_return_20d": avg(numeric_rows(chunk, "forward_return_20d")),
                    "median_forward_return_10d": med(vals10),
                    "hit_rate_10d": f"{(sum(1 for v in vals10 if v > 0) / len(vals10)):.10f}",
                    "avg_max_drawdown_10d": avg(numeric_rows(chunk, "max_drawdown_10d")),
                    "avg_max_gain_10d": avg(numeric_rows(chunk, "max_gain_10d")),
                    "avg_excess_return_vs_QQQ_10d": avg(qqq),
                    "avg_excess_return_vs_SOXX_10d": avg(soxx),
                    "avg_excess_return_vs_SPY_10d": avg(spy),
                    "diagnosis_flag": diagnose_segment(vals10, qqq, soxx, spy),
                }
            )
    return out


def diagnose_segment(vals10: list[float], qqq: list[float], soxx: list[float], spy: list[float]) -> str:
    if len(vals10) < 20:
        return "REGIME_DATA_INSUFFICIENT"
    avg_ret = mean(vals10)
    avg_excess = mean([v for v in qqq + soxx + spy if v is not None]) if any(v is not None for v in qqq + soxx + spy) else 0.0
    if avg_ret > 0 and avg_excess >= 0:
        return "REGIME_SUPPORTS_RANKING"
    if avg_ret < 0 and avg_excess < 0:
        return "REGIME_HURTS_RANKING"
    return "REGIME_MIXED"


def overheat_false_block(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for row in rows:
        status = str(row.get("overheat_status", ""))
        if "OVERHEAT" not in status:
            continue
        vals10 = parse_float(row.get("forward_return_10d"))
        if vals10 is None:
            out.append(
                {
                    "as_of_date": row.get("as_of_date", ""),
                    "ticker": row.get("ticker", ""),
                    "rank": row.get("rank", ""),
                    "baseline_score": row.get("baseline_score", ""),
                    "overheat_status": status,
                    "forward_return_5d": row.get("forward_return_5d", ""),
                    "forward_return_10d": row.get("forward_return_10d", ""),
                    "forward_return_20d": row.get("forward_return_20d", ""),
                    "max_drawdown_10d": row.get("max_drawdown_10d", ""),
                    "max_gain_10d": row.get("max_gain_10d", ""),
                    "excess_return_vs_QQQ_10d": row.get("excess_return_vs_QQQ_10d", ""),
                    "excess_return_vs_SOXX_10d": row.get("excess_return_vs_SOXX_10d", ""),
                    "excess_return_vs_SPY_10d": row.get("excess_return_vs_SPY_10d", ""),
                    "false_block_flag": "INSUFFICIENT_FORWARD_DATA",
                    "diagnosis_note": "Overheat status detected but 10d forward outcome is unavailable.",
                }
            )
            continue
        qqq = parse_float(row.get("excess_return_vs_QQQ_10d"))
        soxx = parse_float(row.get("excess_return_vs_SOXX_10d"))
        spy = parse_float(row.get("excess_return_vs_SPY_10d"))
        flag = "OVERHEAT_CONTINUED_STRONG" if vals10 > 0 and (row.get("max_gain_10d", "") != "" and parse_float(row.get("max_gain_10d")) or 0) > 0 else "OVERHEAT_VALID_PULLBACK" if vals10 < 0 else "OVERHEAT_MIXED"
        out.append(
            {
                "as_of_date": row.get("as_of_date", ""),
                "ticker": row.get("ticker", ""),
                "rank": row.get("rank", ""),
                "baseline_score": row.get("baseline_score", ""),
                "overheat_status": status,
                "forward_return_5d": row.get("forward_return_5d", ""),
                "forward_return_10d": row.get("forward_return_10d", ""),
                "forward_return_20d": row.get("forward_return_20d", ""),
                "max_drawdown_10d": row.get("max_drawdown_10d", ""),
                "max_gain_10d": row.get("max_gain_10d", ""),
                "excess_return_vs_QQQ_10d": row.get("excess_return_vs_QQQ_10d", ""),
                "excess_return_vs_SOXX_10d": row.get("excess_return_vs_SOXX_10d", ""),
                "excess_return_vs_SPY_10d": row.get("excess_return_vs_SPY_10d", ""),
                "false_block_flag": flag,
                "diagnosis_note": "Overheat label aligned with continuation if forward return remained positive; otherwise treated as pullback/mixed.",
            }
        )
    return out


def candidates(rows: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    risk_candidates: list[dict[str, object]] = []
    regime_candidates: list[dict[str, object]] = []
    # risk score fields
    for field in ["risk_score", "regime_score", "market_regime_score", "benchmark_score"]:
        vals = [parse_float(row.get(field)) for row in rows if parse_float(row.get(field)) is not None and parse_float(row.get("forward_return_10d")) is not None]
        if len(vals) < 25:
            continue
        deciles = score_deciles(rows, field)
        if not deciles:
            continue
        top = next((row for row in deciles if int(row["decile"]) == 10), None)
        bottom = next((row for row in deciles if int(row["decile"]) == 1), None)
        if not top or not bottom:
            continue
        top_ret = parse_float(top.get("avg_forward_return_10d"))
        bottom_ret = parse_float(bottom.get("avg_forward_return_10d"))
        top_excess = mean([v for v in [parse_float(top.get("avg_excess_return_vs_QQQ_10d")), parse_float(top.get("avg_excess_return_vs_SOXX_10d")), parse_float(top.get("avg_excess_return_vs_SPY_10d"))] if v is not None]) if any(parse_float(top.get(k)) is not None for k in ["avg_excess_return_vs_QQQ_10d", "avg_excess_return_vs_SOXX_10d", "avg_excess_return_vs_SPY_10d"]) else 0.0
        evidence = "score decile spread"
        if top_ret is not None and bottom_ret is not None:
            risk_candidates.append(
                {
                    "risk_field": field,
                    "evidence_type": "DECILE_SPREAD",
                    "evidence_metric": "top_minus_bottom_forward_return_10d",
                    "metric_value": f"{(top_ret - bottom_ret):.10f}",
                    "coverage_ratio": f"{(len(vals) / max(len(rows), 1)):.10f}",
                    "affected_row_count": len(vals),
                    "impact_summary": f"top_decile_10d={top_ret:.10f}; bottom_decile_10d={bottom_ret:.10f}; top_excess={top_excess:.10f}",
                    "candidate_action": "REVIEW_FOR_GATE_MODE" if top_ret < bottom_ret else "REVIEW_FOR_WARNING_LAYER",
                }
            )
    # regime candidates based on segments
    for seg in segment_performance(rows):
        if parse_float(seg.get("evaluated_row_count")) is None:
            continue
        value = parse_float(seg.get("avg_excess_return_vs_QQQ_10d"))
        if value is None:
            continue
        regime_candidates.append(
            {
                "regime_field": seg["segment_field"],
                "segment_value": seg["segment_value"],
                "evidence_metric": "avg_excess_return_vs_QQQ_10d",
                "metric_value": seg["avg_excess_return_vs_QQQ_10d"],
                "coverage_ratio": f"{(parse_float(seg.get('evaluated_row_count')) or 0.0) / max(len(rows), 1):.10f}",
                "impact_summary": f"QQQ={seg.get('avg_excess_return_vs_QQQ_10d', '')}; SOXX={seg.get('avg_excess_return_vs_SOXX_10d', '')}; SPY={seg.get('avg_excess_return_vs_SPY_10d', '')}",
                "candidate_action": regime_action(seg),
            }
        )
    return risk_candidates, regime_candidates


def regime_action(seg: dict[str, object]) -> str:
    value = parse_float(seg.get("avg_excess_return_vs_QQQ_10d"))
    if value is None:
        return "NO_ACTION_INSUFFICIENT_EVIDENCE"
    field = str(seg.get("segment_field", ""))
    if "overheat" in field or "entry" in field:
        return "REVIEW_FOR_REPORT_ONLY_MODE"
    if value > 0:
        return "REVIEW_FOR_QQQ_SPECIFIC_REGIME"
    if value < 0:
        return "REVIEW_FOR_SPY_SPECIFIC_REGIME"
    return "REVIEW_FOR_GATE_MODE"


def recalibration_scenarios() -> list[dict[str, object]]:
    return [
        {
            "scenario_id": "SCENARIO_001",
            "scenario_name": "RISK_AS_WARNING_NOT_RANKING_WEIGHT",
            "target_problem": "Reduce rank contamination from risk penalties.",
            "expected_benefit": "Preserve winner selection while keeping risk visible.",
            "expected_risk": "Lower immediate drawdown filtering.",
            "required_inputs": "risk deciles; regime segments; benchmark-relative outcomes",
            "implementation_complexity": "MEDIUM",
            "recommended_test_stage": "V21.004_RISK_WEIGHT_REPAIR_SIMULATION",
            "audit_only_status": "NOT_APPLIED",
        },
        {
            "scenario_id": "SCENARIO_002",
            "scenario_name": "DATA_TRUST_AND_RISK_AS_GATE_LAYER",
            "target_problem": "Separate contaminated inputs from ranking weights.",
            "expected_benefit": "Keeps weak or stale inputs out of rank math.",
            "expected_risk": "Can reduce coverage if gate becomes too strict.",
            "required_inputs": "data trust audit; risk/regime audit",
            "implementation_complexity": "HIGH",
            "recommended_test_stage": "V21.004_RISK_REGIME_DATA_TRUST_GATE_SIMULATION",
            "audit_only_status": "NOT_APPLIED",
        },
        {
            "scenario_id": "SCENARIO_003",
            "scenario_name": "OVERHEAT_SPLIT_EXHAUSTION_VS_TREND_STRENGTH",
            "target_problem": "Avoid blocking trend-confirmation names as overheat.",
            "expected_benefit": "Reduce false blocks on persistent winners.",
            "expected_risk": "More short-term reversals may pass through.",
            "required_inputs": "overheat false-block audit; trend strength indicators",
            "implementation_complexity": "MEDIUM",
            "recommended_test_stage": "V21.004_OVERHEAT_LOGIC_REDEFINITION_SIMULATION",
            "audit_only_status": "NOT_APPLIED",
        },
        {
            "scenario_id": "SCENARIO_004",
            "scenario_name": "BENCHMARK_SPECIFIC_REGIME_SOXX_QQQ_SPY",
            "target_problem": "Regime logic conflates benchmark leadership modes.",
            "expected_benefit": "Better regime-conditioned ranking behavior.",
            "expected_risk": "More branches in the logic surface.",
            "required_inputs": "benchmark-relative regime evidence; SOXX/QQQ/SPY returns",
            "implementation_complexity": "HIGH",
            "recommended_test_stage": "V21.004_BENCHMARK_SPECIFIC_REGIME_REPAIR_SIMULATION",
            "audit_only_status": "NOT_APPLIED",
        },
        {
            "scenario_id": "SCENARIO_005",
            "scenario_name": "REDUCE_RISK_PENALTY_IN_CONFIRMED_RISK_ON",
            "target_problem": "Over-penalization of strong winners in risk-on tape.",
            "expected_benefit": "Improves top-ranked continuation capture.",
            "expected_risk": "More drawdown exposure in choppy markets.",
            "required_inputs": "risk decile performance; regime segments",
            "implementation_complexity": "MEDIUM",
            "recommended_test_stage": "V21.004_RISK_WEIGHT_REPAIR_SIMULATION",
            "audit_only_status": "NOT_APPLIED",
        },
        {
            "scenario_id": "SCENARIO_006",
            "scenario_name": "INCREASE_RISK_PENALTY_IN_CONFIRMED_RISK_OFF",
            "target_problem": "Poor drawdown control in risk-off tape.",
            "expected_benefit": "Reduce downside during weak tape.",
            "expected_risk": "May suppress upside recovery names.",
            "required_inputs": "risk deciles; regime classification; benchmark context",
            "implementation_complexity": "MEDIUM",
            "recommended_test_stage": "V21.004_RISK_WEIGHT_REPAIR_SIMULATION",
            "audit_only_status": "NOT_APPLIED",
        },
        {
            "scenario_id": "SCENARIO_007",
            "scenario_name": "ENTRY_TIMING_SEPARATED_FROM_RANKING",
            "target_problem": "Entry labels are mixed into rank math.",
            "expected_benefit": "Cleaner separation between rank and timing.",
            "expected_risk": "Entry timing may become less integrated.",
            "required_inputs": "overheat false-block audit; entry timing fields",
            "implementation_complexity": "MEDIUM",
            "recommended_test_stage": "V21.004_ENTRY_TIMING_SEPARATION_SIMULATION",
            "audit_only_status": "NOT_APPLIED",
        },
    ]


def recalibration_plan() -> list[dict[str, object]]:
    return [
        {
            "priority": 1,
            "plan_item": "Treat risk/regime as a warning layer in risk-on segments unless drawdown benefit is clearly proven.",
            "evidence_source": "V21.003 risk decile performance; regime segment performance",
            "rationale": "Prevent risk penalties from suppressing winning names when benchmark-relative performance is positive.",
            "proposed_next_stage": "V21.004_RISK_WEIGHT_REPAIR_SIMULATION",
            "allowed_action": "DESIGN_ONLY",
            "forbidden_action": "NO_OFFICIAL_WEIGHT_CHANGE|NO_OFFICIAL_RECOMMENDATION|NO_REAL_BOOK_SIGNAL|NO_BROKER_EXECUTION|NO_TRADE_ACTION",
        },
        {
            "priority": 2,
            "plan_item": "Split overheat logic into exhaustion vs trend-confirmation branches before any ranking use.",
            "evidence_source": "V21.003 overheat false-block audit",
            "rationale": "Overheat labels can be a false block if continuation names keep outperforming after the label.",
            "proposed_next_stage": "V21.004_OVERHEAT_LOGIC_REDEFINITION_SIMULATION",
            "allowed_action": "DESIGN_ONLY",
            "forbidden_action": "NO_OFFICIAL_WEIGHT_CHANGE|NO_OFFICIAL_RECOMMENDATION|NO_REAL_BOOK_SIGNAL|NO_BROKER_EXECUTION|NO_TRADE_ACTION",
        },
        {
            "priority": 3,
            "plan_item": "Separate benchmark-specific regime logic for QQQ, SOXX, and SPY before any future promotion.",
            "evidence_source": "V21.003 regime segment performance",
            "rationale": "Regime conditions can diverge across benchmark leadership modes and should not be collapsed prematurely.",
            "proposed_next_stage": "V21.004_BENCHMARK_SPECIFIC_REGIME_REPAIR_SIMULATION",
            "allowed_action": "FURTHER_AUDIT_ONLY",
            "forbidden_action": "NO_OFFICIAL_WEIGHT_CHANGE|NO_OFFICIAL_RECOMMENDATION|NO_REAL_BOOK_SIGNAL|NO_BROKER_EXECUTION|NO_TRADE_ACTION",
        },
        {
            "priority": 4,
            "plan_item": "Keep entry timing signals separate from baseline ranking until their incremental value is isolated.",
            "evidence_source": "V21.003 overheat false-block audit; V21.002 factor ablation",
            "rationale": "Entry and overheat logic may be blending rank selection with timing, obscuring the core score signal.",
            "proposed_next_stage": "V21.004_ENTRY_TIMING_SEPARATION_SIMULATION",
            "allowed_action": "SIMULATION_ONLY",
            "forbidden_action": "NO_OFFICIAL_WEIGHT_CHANGE|NO_OFFICIAL_RECOMMENDATION|NO_REAL_BOOK_SIGNAL|NO_BROKER_EXECUTION|NO_TRADE_ACTION",
        },
    ]


def diagnosis_rows(risk_candidates: list[dict[str, object]], regime_candidates: list[dict[str, object]], overheat_rows: list[dict[str, object]], joined_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if risk_candidates:
        rows.append(
            {
                "diagnosis_area": "RISK_FACTOR_OVERPENALIZATION",
                "evidence_summary": f"{len(risk_candidates)} risk-related score fields show candidate decile spread or tradeoff risk.",
                "severity": "HIGH" if len(risk_candidates) >= 2 else "MEDIUM",
                "recommended_next_stage": "V21.004_RISK_WEIGHT_REPAIR_SIMULATION",
            }
        )
    if regime_candidates:
        rows.append(
            {
                "diagnosis_area": "REGIME_FACTOR_MISALIGNMENT",
                "evidence_summary": f"{len(regime_candidates)} regime/segment conditions show benchmark-relative differences.",
                "severity": "HIGH" if any(parse_float(row.get("metric_value")) is not None and parse_float(row.get("metric_value")) < 0 for row in regime_candidates) else "MEDIUM",
                "recommended_next_stage": "V21.004_BENCHMARK_SPECIFIC_REGIME_REPAIR_SIMULATION",
            }
        )
    if overheat_rows:
        count = sum(1 for row in overheat_rows if row.get("false_block_flag") == "OVERHEAT_CONTINUED_STRONG")
        rows.append(
            {
                "diagnosis_area": "ENTRY_TIMING_NOT_SEPARATED_FROM_RANKING",
                "evidence_summary": f"{count} overheat rows appear to continue strong after the label.",
                "severity": "HIGH" if count > 10 else "MEDIUM",
                "recommended_next_stage": "V21.004_OVERHEAT_LOGIC_REDEFINITION_SIMULATION",
            }
        )
    if len(joined_rows) < 500:
        rows.append(
            {
                "diagnosis_area": "INSUFFICIENT_FACTOR_COVERAGE",
                "evidence_summary": "Joined risk/regime outcome coverage is below threshold.",
                "severity": "HIGH",
                "recommended_next_stage": "V21.004_RISK_REGIME_DATA_COVERAGE_REPAIR",
            }
        )
    if not rows:
        rows.append(
            {
                "diagnosis_area": "FACTOR_FAMILY_NOISE",
                "evidence_summary": "No decisive risk/regime issue proven; keep as report-only until further evidence.",
                "severity": "LOW",
                "recommended_next_stage": "V21.004_RISK_REGIME_DATA_COVERAGE_REPAIR",
            }
        )
    return rows


def build_report(gate: dict[str, object]) -> None:
    lines = [
        "# V21.003 Risk/Regime Recalibration Plan",
        "",
        "## Final status",
        f"final_status: {gate['final_status']}",
        f"joined_risk_regime_outcome_rows: {gate['joined_risk_regime_outcome_rows']}",
        "",
        "## Input discovery",
        "This stage is audit-only and plan-only. No official weights, rankings, recommendations, real-book signals, or broker execution behavior were changed.",
        "",
        "## Risk/regime field map",
        "See the field map output for local risk, regime, benchmark, overheat, and entry-status mappings.",
        "",
        "## Joined risk/regime outcome coverage",
        "Local outcome rows were joined to risk and regime sources without fetching new data.",
        "",
        "## Regime segment performance",
        "Segment performance is evaluated by detected overheat, technical, buy-zone, near-entry, pullback, and breakout statuses.",
        "",
        "## Risk-score decile performance",
        "Risk-score deciles are evaluated using locally available risk/regime fields only.",
        "",
        "## Overheat false-block audit",
        "The audit checks whether overheat-like labels coincided with continued positive forward returns.",
        "",
        "## Risk over-penalization candidates",
        "Candidate rows identify possible over-penalization or gating behavior only.",
        "",
        "## Regime misalignment candidates",
        "Candidate rows compare regime segments against benchmark-relative outcomes.",
        "",
        "## Recalibration scenarios",
        "The scenarios are not applied; they are research-only design options.",
        "",
        "## Recalibration plan",
        "The plan is research-only and keeps official weights unchanged.",
        "",
        "## Strategy diagnosis",
        str(gate["strategy_diagnosis"]),
        "",
        "## Next recommended action",
        str(gate["next_recommended_action"]),
        "",
        "## Safety confirmation",
        "No official weights, rankings, recommendations, real-book signals, trade actions, or broker execution behavior were changed.",
    ]
    for field in FALSE_FIELDS:
        lines.append(f"- {field}: {gate[field]}")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def next_action(final_status: str, diagnosis: list[dict[str, object]]) -> str:
    if final_status == "FAIL_V21_003_REQUIRED_INPUTS_MISSING":
        return "Repair the missing V21.001/V21.002 inputs before continuing."
    if final_status == "FAIL_V21_003_NO_RISK_REGIME_FIELDS_DETECTED":
        return "Repair risk/regime source discovery before continuing."
    if any(row["diagnosis_area"] == "INSUFFICIENT_FACTOR_COVERAGE" for row in diagnosis):
        return "Proceed to V21.004_RISK_REGIME_DATA_COVERAGE_REPAIR."
    if any(row["diagnosis_area"] == "RISK_FACTOR_OVERPENALIZATION" for row in diagnosis):
        return "Proceed to V21.004_RISK_WEIGHT_REPAIR_SIMULATION."
    if any(row["diagnosis_area"] == "REGIME_FACTOR_MISALIGNMENT" for row in diagnosis):
        return "Proceed to V21.004_BENCHMARK_SPECIFIC_REGIME_REPAIR_SIMULATION."
    if any(row["diagnosis_area"] == "ENTRY_TIMING_NOT_SEPARATED_FROM_RANKING" for row in diagnosis):
        return "Proceed to V21.004_OVERHEAT_LOGIC_REDEFINITION_SIMULATION."
    return "Proceed to V21.004_RISK_WEIGHT_REPAIR_SIMULATION."


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)

    try:
        base_rows, _gates, _ = load_v21_sources()
    except FileNotFoundError:
        gate = {
            "stage_name": STAGE_NAME,
            "final_status": "FAIL_V21_003_REQUIRED_INPUTS_MISSING",
            "joined_risk_regime_outcome_rows": 0,
            "evaluated_regime_segment_count": 0,
            "evaluated_risk_score_field_count": 0,
            "overheat_false_block_candidate_count": 0,
            "risk_overpenalization_candidate_count": 0,
            "regime_misalignment_candidate_count": 0,
            "recalibration_scenario_count": 0,
            "recalibration_evidence_status": "INSUFFICIENT_EVIDENCE",
            "strategy_diagnosis": "required V21.001 or V21.002 inputs are missing.",
            "next_recommended_action": "Repair the missing V21.001/V21.002 inputs before continuing.",
        }
        gate.update({field: "FALSE" for field in FALSE_FIELDS})
        write_csv(GATE, [gate], [
            "stage_name",
            "final_status",
            "joined_risk_regime_outcome_rows",
            "evaluated_regime_segment_count",
            "evaluated_risk_score_field_count",
            "overheat_false_block_candidate_count",
            "risk_overpenalization_candidate_count",
            "regime_misalignment_candidate_count",
            "recalibration_scenario_count",
            "recalibration_evidence_status",
            "strategy_diagnosis",
            "next_recommended_action",
        ] + FALSE_FIELDS)
        REPORT.write_text("# V21.003 Risk/Regime Recalibration Plan\n\n## Final status\nMissing required inputs.\n", encoding="utf-8")
        print(f"STAGE_NAME={STAGE_NAME}")
        print(f"final_status={gate['final_status']}")
        print("joined_risk_regime_outcome_rows=0")
        print("evaluated_regime_segment_count=0")
        print("evaluated_risk_score_field_count=0")
        print("overheat_false_block_candidate_count=0")
        print("risk_overpenalization_candidate_count=0")
        print("regime_misalignment_candidate_count=0")
        print("recalibration_scenario_count=0")
        print("next_recommended_action=Repair the missing V21.001/V21.002 inputs before continuing.")
        return 0

    discovery = discover_inputs()
    field_map_rows = discover_field_map()
    joined_rows = build_joined_rows(base_rows)

    if not field_map_rows:
        gate = {
            "stage_name": STAGE_NAME,
            "final_status": "FAIL_V21_003_NO_RISK_REGIME_FIELDS_DETECTED",
            "joined_risk_regime_outcome_rows": len(joined_rows),
            "evaluated_regime_segment_count": 0,
            "evaluated_risk_score_field_count": 0,
            "overheat_false_block_candidate_count": 0,
            "risk_overpenalization_candidate_count": 0,
            "regime_misalignment_candidate_count": 0,
            "recalibration_scenario_count": 0,
            "recalibration_evidence_status": "INSUFFICIENT_EVIDENCE",
            "strategy_diagnosis": "outcome rows exist but no usable risk/regime fields were detected.",
            "next_recommended_action": "Repair risk/regime source discovery before continuing.",
        }
        gate.update({field: "FALSE" for field in FALSE_FIELDS})
        write_csv(GATE, [gate], [
            "stage_name",
            "final_status",
            "joined_risk_regime_outcome_rows",
            "evaluated_regime_segment_count",
            "evaluated_risk_score_field_count",
            "overheat_false_block_candidate_count",
            "risk_overpenalization_candidate_count",
            "regime_misalignment_candidate_count",
            "recalibration_scenario_count",
            "recalibration_evidence_status",
            "strategy_diagnosis",
            "next_recommended_action",
        ] + FALSE_FIELDS)
        REPORT.write_text("# V21.003 Risk/Regime Recalibration Plan\n\n## Final status\nNo risk/regime fields detected.\n", encoding="utf-8")
        print(f"STAGE_NAME={STAGE_NAME}")
        print(f"final_status={gate['final_status']}")
        print(f"joined_risk_regime_outcome_rows={len(joined_rows)}")
        print("evaluated_regime_segment_count=0")
        print("evaluated_risk_score_field_count=0")
        print("overheat_false_block_candidate_count=0")
        print("risk_overpenalization_candidate_count=0")
        print("regime_misalignment_candidate_count=0")
        print("recalibration_scenario_count=0")
        print(f"next_recommended_action={gate['next_recommended_action']}")
        return 0

    risk_fields = [row["column_name"] for row in field_map_rows if row["mapped_field_type"] == "RISK_SCORE"]
    regime_fields = [row["column_name"] for row in field_map_rows if row["mapped_field_type"] in {"REGIME_SCORE", "MARKET_REGIME_SCORE"}]
    joined_risk_regime_outcome_rows = len(joined_rows)
    evaluated_regime_segment_count = len(segment_performance(joined_rows))
    evaluated_risk_score_field_count = len(set(risk_fields))
    overheat_rows = overheat_false_block(joined_rows)
    risk_candidates, regime_candidates = candidates(joined_rows)
    scenarios = recalibration_scenarios()
    diagnosis = diagnosis_rows(risk_candidates, regime_candidates, overheat_rows, joined_rows)
    plan = recalibration_plan()

    if joined_risk_regime_outcome_rows < 500 or len(set(risk_fields + regime_fields)) < 2:
        final_status = "PARTIAL_PASS_V21_003_LIMITED_RISK_REGIME_COVERAGE"
    elif not overheat_rows and not risk_candidates and not regime_candidates:
        final_status = "PARTIAL_PASS_V21_003_RECALIBRATION_EVIDENCE_LIMITED"
    elif joined_risk_regime_outcome_rows >= 500 and evaluated_regime_segment_count >= 1 and len(scenarios) >= 3 and (risk_candidates or regime_candidates or plan):
        final_status = "PASS_V21_003_RISK_REGIME_RECALIBRATION_PLAN_READY"
    else:
        final_status = "PARTIAL_PASS_V21_003_RECALIBRATION_EVIDENCE_LIMITED"

    gate = {
        "stage_name": STAGE_NAME,
        "final_status": final_status,
        "joined_risk_regime_outcome_rows": joined_risk_regime_outcome_rows,
        "evaluated_regime_segment_count": evaluated_regime_segment_count,
        "evaluated_risk_score_field_count": evaluated_risk_score_field_count,
        "overheat_false_block_candidate_count": sum(1 for row in overheat_rows if row["false_block_flag"] == "OVERHEAT_CONTINUED_STRONG"),
        "risk_overpenalization_candidate_count": len(risk_candidates),
        "regime_misalignment_candidate_count": len(regime_candidates),
        "recalibration_scenario_count": len(scenarios),
        "recalibration_evidence_status": "PASS_RECALIBRATION_EVIDENCE" if (risk_candidates or regime_candidates or overheat_rows) else "INSUFFICIENT_EVIDENCE",
        "strategy_diagnosis": strategy_diagnosis(joined_rows, risk_candidates, regime_candidates, overheat_rows),
        "next_recommended_action": next_action(final_status, diagnosis),
    }
    gate.update({field: "FALSE" for field in FALSE_FIELDS})

    segment_perf = segment_performance(joined_rows)
    risk_deciles = []
    for field in sorted(set(risk_fields + regime_fields)):
        risk_deciles.extend(score_deciles(joined_rows, field))
    overheat_rows_out = overheat_rows
    write_csv(INPUT_DISCOVERY, discovery, ["artifact_path", "artifact_type", "exists_non_empty", "row_count", "detected_columns", "selected_for_audit", "selection_reason", "validation_status"])
    write_csv(FIELD_MAP, field_map_rows, ["source_artifact", "column_name", "mapped_field_type", "mapping_confidence", "mapping_reason", "non_null_count", "coverage_ratio", "selected_for_recalibration_audit"])
    write_csv(JOINED_ROWS, joined_rows, [
        "as_of_date",
        "ticker",
        "rank",
        "baseline_score",
        "forward_return_5d",
        "forward_return_10d",
        "forward_return_20d",
        "max_drawdown_10d",
        "max_gain_10d",
        "excess_return_vs_QQQ_10d",
        "excess_return_vs_SOXX_10d",
        "excess_return_vs_SPY_10d",
        "risk_score",
        "regime_score",
        "market_regime_score",
        "benchmark_score",
        "overheat_status",
        "technical_status",
        "buy_zone_status",
        "near_entry_status",
        "pullback_status",
        "breakout_status",
        "source_artifacts",
    ])
    write_csv(REGIME_SEGMENT_PERF, segment_perf, [
        "segment_field",
        "segment_value",
        "evaluated_row_count",
        "avg_forward_return_5d",
        "avg_forward_return_10d",
        "avg_forward_return_20d",
        "median_forward_return_10d",
        "hit_rate_10d",
        "avg_max_drawdown_10d",
        "avg_max_gain_10d",
        "avg_excess_return_vs_QQQ_10d",
        "avg_excess_return_vs_SOXX_10d",
        "avg_excess_return_vs_SPY_10d",
        "diagnosis_flag",
    ])
    write_csv(RISK_DECILE_PERF, risk_deciles, [
        "score_field",
        "decile",
        "evaluated_row_count",
        "avg_forward_return_10d",
        "median_forward_return_10d",
        "hit_rate_10d",
        "avg_max_drawdown_10d",
        "avg_max_gain_10d",
        "avg_excess_return_vs_QQQ_10d",
        "avg_excess_return_vs_SOXX_10d",
        "avg_excess_return_vs_SPY_10d",
        "risk_return_tradeoff_flag",
    ])
    write_csv(OVERHEAT_FALSE_BLOCK, overheat_rows_out, [
        "as_of_date",
        "ticker",
        "rank",
        "baseline_score",
        "overheat_status",
        "forward_return_5d",
        "forward_return_10d",
        "forward_return_20d",
        "max_drawdown_10d",
        "max_gain_10d",
        "excess_return_vs_QQQ_10d",
        "excess_return_vs_SOXX_10d",
        "excess_return_vs_SPY_10d",
        "false_block_flag",
        "diagnosis_note",
    ])
    write_csv(RISK_OVERPENALIZATION, risk_candidates, [
        "risk_field",
        "evidence_type",
        "evidence_metric",
        "metric_value",
        "coverage_ratio",
        "affected_row_count",
        "impact_summary",
        "candidate_action",
    ])
    write_csv(REGIME_MISALIGNMENT, regime_candidates, [
        "regime_field",
        "segment_value",
        "evidence_metric",
        "metric_value",
        "coverage_ratio",
        "impact_summary",
        "candidate_action",
    ])
    write_csv(SCENARIOS, scenarios, [
        "scenario_id",
        "scenario_name",
        "target_problem",
        "expected_benefit",
        "expected_risk",
        "required_inputs",
        "implementation_complexity",
        "recommended_test_stage",
        "audit_only_status",
    ])
    write_csv(PLAN, plan, [
        "priority",
        "plan_item",
        "evidence_source",
        "rationale",
        "proposed_next_stage",
        "allowed_action",
        "forbidden_action",
    ])
    write_csv(GATE, [gate], [
        "stage_name",
        "final_status",
        "joined_risk_regime_outcome_rows",
        "evaluated_regime_segment_count",
        "evaluated_risk_score_field_count",
        "overheat_false_block_candidate_count",
        "risk_overpenalization_candidate_count",
        "regime_misalignment_candidate_count",
        "recalibration_scenario_count",
        "recalibration_evidence_status",
        "strategy_diagnosis",
        "next_recommended_action",
    ] + FALSE_FIELDS)
    build_report(gate)

    print(f"STAGE_NAME={STAGE_NAME}")
    print(f"final_status={final_status}")
    print(f"joined_risk_regime_outcome_rows={joined_risk_regime_outcome_rows}")
    print(f"evaluated_regime_segment_count={evaluated_regime_segment_count}")
    print(f"evaluated_risk_score_field_count={evaluated_risk_score_field_count}")
    print(f"overheat_false_block_candidate_count={gate['overheat_false_block_candidate_count']}")
    print(f"risk_overpenalization_candidate_count={gate['risk_overpenalization_candidate_count']}")
    print(f"regime_misalignment_candidate_count={gate['regime_misalignment_candidate_count']}")
    print(f"recalibration_scenario_count={gate['recalibration_scenario_count']}")
    print(f"next_recommended_action={gate['next_recommended_action']}")
    return 0 if final_status in ALLOWED_FINAL_STATUSES else 1


def strategy_diagnosis(joined_rows: list[dict[str, object]], risk_candidates: list[dict[str, object]], regime_candidates: list[dict[str, object]], overheat_rows: list[dict[str, object]]) -> str:
    notes: list[str] = []
    if any(parse_float(row.get("risk_score")) is not None and parse_float(row.get("risk_score")) > 0.6 for row in joined_rows):
        notes.append("risk scoring is active in the ranking path")
    if risk_candidates:
        notes.append("risk factor over-penalization is plausible")
    if regime_candidates:
        notes.append("benchmark-relative regime misalignment is plausible")
    if any(row.get("false_block_flag") == "OVERHEAT_CONTINUED_STRONG" for row in overheat_rows):
        notes.append("overheat logic may be blocking trend continuation")
    if not notes:
        notes.append("insufficient evidence for a decisive recalibration diagnosis")
    return "; ".join(notes) + "."


if __name__ == "__main__":
    raise SystemExit(main())
