#!/usr/bin/env python
"""V21.003-R1 risk/regime audit sanity repair.

Audit-repair-only stage that corrects the overheat false-block audit logic and
recomputes risk/regime semantic checks from local CSV evidence.
"""

from __future__ import annotations

import csv
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median


STAGE_NAME = "V21_003_R1_RISK_REGIME_AUDIT_SANITY_REPAIR"
ROOT = Path(__file__).resolve().parents[2]
V20_DIR = ROOT / "outputs" / "v20"
V21_AUDIT_DIR = ROOT / "outputs" / "v21" / "audit"
V21_ABLATION_DIR = ROOT / "outputs" / "v21" / "ablation"
V21_RECAL_DIR = ROOT / "outputs" / "v21" / "recalibration"
OUT_DIR = ROOT / "outputs" / "v21" / "recalibration_r1"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

REQ_INPUTS = [
    V21_RECAL_DIR / "V21_003_RISK_REGIME_JOINED_OUTCOME_ROWS.csv",
    V21_RECAL_DIR / "V21_003_RISK_REGIME_FIELD_MAP.csv",
    V21_RECAL_DIR / "V21_003_REGIME_SEGMENT_PERFORMANCE.csv",
    V21_RECAL_DIR / "V21_003_RISK_SCORE_DECILE_PERFORMANCE.csv",
    V21_RECAL_DIR / "V21_003_OVERHEAT_FALSE_BLOCK_AUDIT.csv",
    V21_RECAL_DIR / "V21_003_RISK_OVERPENALIZATION_CANDIDATES.csv",
    V21_RECAL_DIR / "V21_003_REGIME_MISALIGNMENT_CANDIDATES.csv",
    V21_RECAL_DIR / "V21_003_RECALIBRATION_PLAN.csv",
    V21_RECAL_DIR / "V21_003_NEXT_STAGE_GATE.csv",
]

INPUT_VALIDATION = OUT_DIR / "V21_003_R1_INPUT_VALIDATION.csv"
OVERHEAT_SANITY = OUT_DIR / "V21_003_R1_OVERHEAT_STATUS_SANITY_AUDIT.csv"
REPAIRED_OVERHEAT = OUT_DIR / "V21_003_R1_OVERHEAT_FALSE_BLOCK_AUDIT_REPAIRED.csv"
RISK_DIR_AUDIT = OUT_DIR / "V21_003_R1_RISK_SCORE_DIRECTION_AUDIT.csv"
REGIME_DIR_AUDIT = OUT_DIR / "V21_003_R1_REGIME_SCORE_DIRECTION_AUDIT.csv"
REPAIRED_RISK_CAND = OUT_DIR / "V21_003_R1_REPAIRED_RISK_OVERPENALIZATION_CANDIDATES.csv"
REPAIRED_REGIME_CAND = OUT_DIR / "V21_003_R1_REPAIRED_REGIME_MISALIGNMENT_CANDIDATES.csv"
REPAIRED_PLAN = OUT_DIR / "V21_003_R1_REPAIRED_RECALIBRATION_PLAN.csv"
GATE = OUT_DIR / "V21_003_R1_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER_DIR / "V21_003_R1_RISK_REGIME_AUDIT_SANITY_REPAIR_REPORT.md"

ALLOWED_FINAL_STATUSES = {
    "FAIL_V21_003_R1_REQUIRED_INPUTS_MISSING",
    "FAIL_V21_003_R1_JOINED_ROWS_MISSING",
    "PARTIAL_PASS_V21_003_R1_OVERHEAT_AUDIT_CONTAMINATED_REPAIRED",
    "PARTIAL_PASS_V21_003_R1_SCORE_DIRECTION_AMBIGUOUS",
    "PASS_V21_003_R1_AUDIT_SANITY_REPAIRED_READY_FOR_SIMULATION_SELECTION",
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
OVERHEAT_POSITIVE_PATTERNS = [
    "OVERHEAT",
    "OVERHEATED",
    "EXTENDED",
    "EXHAUSTION",
    "HOT",
    "TOO_HOT",
    "UPPER_BAND_EXTENDED",
    "RSI_OVERBOUGHT",
    "KDJ_OVERBOUGHT",
]
OVERHEAT_NEGATIVE_PATTERNS = [
    "NOT_OVERHEAT",
    "NON_OVERHEAT",
    "NO_OVERHEAT",
    "FALSE",
    "NONE",
    "NO_MATCH",
    "NEUTRAL",
    "UNKNOWN",
]
RISK_FIELDS = ["risk_score", "regime_score", "market_regime_score"]
REGIME_FIELDS = ["regime_score", "market_regime_score"]


def norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").strip().lower()).strip("_")


def overheat_text(text: str | None) -> str:
    return (text or "").upper()


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
    if num is None:
        return None
    return int(num)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def rel_key(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle).fieldnames or [])


def row_count(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return max(sum(1 for _ in handle) - 1, 0)


def detect_ticker_field(columns: list[str]) -> str | None:
    for candidate in ["ticker", "symbol", "ticker_or_candidate_id", "display_name_or_ticker"]:
        if candidate in {norm(c) for c in columns}:
            return {norm(c): c for c in columns}[candidate]
    for col in columns:
        if any(token in norm(col) for token in ["ticker", "symbol"]):
            return col
    return None


def detect_date_field(columns: list[str]) -> str | None:
    for candidate in ["as_of_date", "signal_date", "date", "snapshot_date"]:
        if candidate in {norm(c) for c in columns}:
            return {norm(c): c for c in columns}[candidate]
    for col in columns:
        if any(token in norm(col) for token in ["asof", "signal", "date", "snapshot"]):
            return col
    return None


def is_positive_overheat_text(text: str | None) -> bool:
    upper = overheat_text(text)
    if any(token in upper for token in OVERHEAT_NEGATIVE_PATTERNS):
        return False
    return any(token in upper for token in OVERHEAT_POSITIVE_PATTERNS)


def detect_overheat_status(text: str | None) -> str:
    if is_positive_overheat_text(text):
        upper = overheat_text(text)
        return next((token for token in OVERHEAT_POSITIVE_PATTERNS if token in upper), "OVERHEAT")
    return "NOT_OVERHEAT"


def write_report(gate: dict[str, object], contamination_note: str) -> None:
    lines = [
        "# V21.003-R1 Risk/Regime Audit Sanity Repair",
        "",
        "## Final status",
        f"final_status: {gate['final_status']}",
        f"contamination_ratio: {gate['contamination_ratio']}",
        "",
        "## Input validation",
        "The stage validated the V21.003 recalibration inputs and repaired the overheat audit logic locally.",
        "",
        "## Original V21.003 issue",
        contamination_note,
        "",
        "## Overheat status sanity audit",
        "Only rows whose equivalent overheat status matched a positive overheat pattern and did not match the excluded negative patterns were retained.",
        "",
        "## Repaired overheat false-block audit",
        "The repaired audit excludes NOT_OVERHEAT and other negative-equivalent rows.",
        "",
        "## Risk-score direction audit",
        "Direction checks were recomputed from the repaired local evidence.",
        "",
        "## Regime-score direction audit",
        "Regime semantics were recomputed against benchmark-relative forward outcomes.",
        "",
        "## Repaired risk over-penalization candidates",
        "See the repaired candidate table for evidence-backed rows only.",
        "",
        "## Repaired regime misalignment candidates",
        "See the repaired candidate table for benchmark-relative misalignment evidence only.",
        "",
        "## Repaired recalibration plan",
        "The plan keeps the repair audit-only and avoids any official weight change.",
        "",
        "## Strategy diagnosis",
        str(gate["strategy_diagnosis"]),
        "",
        "## Next recommended action",
        str(gate["next_recommended_action"]),
        "",
        "## Safety confirmation",
        "No official weights, recommendations, real-book signals, trade actions, or broker execution behavior were changed.",
    ]
    for field in FALSE_FIELDS:
        lines.append(f"- {field}: {gate[field]}")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_required_inputs() -> dict[str, list[dict[str, str]]]:
    missing = [path for path in REQ_INPUTS if not path.exists()]
    if missing:
        raise FileNotFoundError(", ".join(str(path) for path in missing))
    return {str(path): read_csv(path) for path in REQ_INPUTS}


def validate_inputs() -> list[dict[str, object]]:
    rows = []
    for path in REQ_INPUTS:
        exists = path.exists()
        rows.append(
            {
                "artifact_path": rel_key(path),
                "exists_non_empty": str(exists and path.stat().st_size > 0).upper() if exists else "FALSE",
                "row_count": row_count(path) if exists else 0,
                "validation_status": "PASS" if exists and path.stat().st_size > 0 else "MISSING",
                "selection_reason": "required V21.003 input for audit repair" if exists else "missing required input",
            }
        )
    return rows


def load_joined_rows() -> list[dict[str, str]]:
    path = V21_RECAL_DIR / "V21_003_RISK_REGIME_JOINED_OUTCOME_ROWS.csv"
    if not path.exists():
        return []
    return read_csv(path)


def load_v20_strategy_status_map() -> dict[str, dict[str, str]]:
    path = V20_DIR / "consolidation" / "V20_108_R7_STRATEGY_CANDIDATE_SCORE_SOURCE.csv"
    status_map: dict[str, dict[str, str]] = {}
    if not path.exists():
        return status_map
    for row in read_csv(path):
        ticker = str(row.get("ticker", "")).strip().upper()
        if not ticker:
            continue
        text = " | ".join(
            [
                row.get("strategy_raw_columns_used", ""),
                row.get("strategy_categorical_mappings_used", ""),
                row.get("strategy_source_status", ""),
                row.get("missing_reason", ""),
            ]
        ).upper()
        if is_positive_overheat_text(text):
            matched = detect_overheat_status(text)
            status_map[ticker] = {
                "overheat_status": matched,
                "strategy_source_artifact": rel_key(path),
                "strategy_component_score": row.get("overheat_penalty_component_score", ""),
                "strategy_raw_columns_used": row.get("strategy_raw_columns_used", ""),
                "strategy_categorical_mappings_used": row.get("strategy_categorical_mappings_used", ""),
            }
        else:
            status_map[ticker] = {
                "overheat_status": "NOT_OVERHEAT",
                "strategy_source_artifact": rel_key(path),
                "strategy_component_score": row.get("overheat_penalty_component_score", ""),
                "strategy_raw_columns_used": row.get("strategy_raw_columns_used", ""),
                "strategy_categorical_mappings_used": row.get("strategy_categorical_mappings_used", ""),
            }
    return status_map


def build_repaired_overheat_audit(joined_rows: list[dict[str, str]], status_map: dict[str, dict[str, str]]) -> tuple[list[dict[str, object]], dict[str, int]]:
    original_count = len(joined_rows)
    repaired_rows: list[dict[str, object]] = []
    removed_not_overheat = 0
    for row in joined_rows:
        ticker = str(row.get("ticker", "")).strip().upper()
        status = status_map.get(ticker, {}).get("overheat_status", "NOT_OVERHEAT")
        if not is_positive_overheat_text(status):
            removed_not_overheat += 1
            continue
        f10 = parse_float(row.get("forward_return_10d"))
        dd10 = parse_float(row.get("max_drawdown_10d"))
        ex_q = parse_float(row.get("excess_return_vs_QQQ_10d"))
        ex_s = parse_float(row.get("excess_return_vs_SOXX_10d"))
        ex_p = parse_float(row.get("excess_return_vs_SPY_10d"))
        if f10 is None or dd10 is None or ex_q is None or ex_s is None or ex_p is None:
            flag = "INSUFFICIENT_FORWARD_DATA"
            note = "Missing or non-numeric forward outcome fields."
        elif f10 > 0 and (ex_q > 0 or ex_s > 0 or ex_p > 0):
            flag = "OVERHEAT_FALSE_BLOCK_CONTINUED_STRONG"
            note = "Positive forward return and positive benchmark-relative excess return."
        elif f10 < 0 or dd10 < -0.05:
            flag = "OVERHEAT_VALID_PULLBACK"
            note = "Negative forward return or material drawdown after the label."
        else:
            flag = "OVERHEAT_MIXED"
            note = "Evidence is contradictory or too weak to classify cleanly."
        repaired_rows.append(
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
                "diagnosis_note": note,
            }
        )
    summary = {
        "original_overheat_false_block_candidate_count": original_count,
        "repaired_true_overheat_row_count": len(repaired_rows),
        "repaired_false_block_candidate_count": sum(1 for row in repaired_rows if row["false_block_flag"] == "OVERHEAT_FALSE_BLOCK_CONTINUED_STRONG"),
        "removed_not_overheat_row_count": removed_not_overheat,
    }
    summary["contamination_ratio"] = (removed_not_overheat / original_count) if original_count else 0.0
    return repaired_rows, summary


def score_deciles(rows: list[dict[str, str]], score_field: str) -> list[dict[str, object]]:
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
        vals10 = [v for v in (parse_float(row.get("forward_return_10d")) for row in chunk) if v is not None]
        dd10 = [v for v in (parse_float(row.get("max_drawdown_10d")) for row in chunk) if v is not None]
        ex_q = [v for v in (parse_float(row.get("excess_return_vs_QQQ_10d")) for row in chunk) if v is not None]
        ex_s = [v for v in (parse_float(row.get("excess_return_vs_SOXX_10d")) for row in chunk) if v is not None]
        ex_p = [v for v in (parse_float(row.get("excess_return_vs_SPY_10d")) for row in chunk) if v is not None]
        out.append(
            {
                "score_field": score_field,
                "decile": idx + 1,
                "evaluated_row_count": len(vals10),
                "avg_forward_return_10d": fmt(mean(vals10)) if vals10 else "",
                "median_forward_return_10d": fmt(median(vals10)) if vals10 else "",
                "hit_rate_10d": fmt(sum(1 for v in vals10 if v > 0) / len(vals10)) if vals10 else "",
                "avg_max_drawdown_10d": fmt(mean(dd10)) if dd10 else "",
                "avg_max_gain_10d": fmt(mean([v for v in (parse_float(row.get("max_gain_10d")) for row in chunk) if v is not None])) if any(parse_float(row.get("max_gain_10d")) is not None for row in chunk) else "",
                "avg_excess_return_vs_QQQ_10d": fmt(mean(ex_q)) if ex_q else "",
                "avg_excess_return_vs_SOXX_10d": fmt(mean(ex_s)) if ex_s else "",
                "avg_excess_return_vs_SPY_10d": fmt(mean(ex_p)) if ex_p else "",
                "risk_return_tradeoff_flag": risk_tradeoff_flag(vals10, dd10, ex_q, ex_s, ex_p),
            }
        )
    return out


def fmt(value: float) -> str:
    return f"{value:.10f}"


def risk_tradeoff_flag(returns: list[float], dd: list[float], ex_q: list[float], ex_s: list[float], ex_p: list[float]) -> str:
    if not returns:
        return "INSUFFICIENT_EVIDENCE"
    avg_ret = mean(returns)
    avg_dd = mean(dd) if dd else 0.0
    avg_excess = mean([v for v in ex_q + ex_s + ex_p if v is not None]) if any(v is not None for v in ex_q + ex_s + ex_p) else 0.0
    if avg_ret > 0 and avg_excess >= 0 and avg_dd > -0.05:
        return "GOOD_RISK_FILTER"
    if avg_ret > 0 and avg_excess < 0:
        return "OVERPENALIZES_WINNERS"
    if avg_ret <= 0 and avg_dd <= -0.05:
        return "WEAK_RISK_FILTER"
    if abs(avg_ret) < 0.01:
        return "MIXED_RISK_FILTER"
    return "INSUFFICIENT_EVIDENCE"


def infer_score_direction(rows: list[dict[str, str]], score_field: str) -> dict[str, object]:
    scored = [row for row in rows if parse_float(row.get(score_field)) is not None and parse_float(row.get("forward_return_10d")) is not None and parse_float(row.get("max_drawdown_10d")) is not None]
    values = [parse_float(row.get(score_field)) for row in scored if parse_float(row.get(score_field)) is not None]
    if len(values) < 25:
        return {
            "score_field": score_field,
            "evaluated_row_count": len(values),
            "correlation_forward_return_10d": "",
            "correlation_max_drawdown_10d": "",
            "top_decile_forward_return_10d": "",
            "bottom_decile_forward_return_10d": "",
            "top_decile_max_drawdown_10d": "",
            "bottom_decile_max_drawdown_10d": "",
            "direction_inference": "INSUFFICIENT_EVIDENCE",
            "diagnosis_flag": "INSUFFICIENT_EVIDENCE",
        }
    ordered = sorted(scored, key=lambda row: parse_float(row.get(score_field)) or 0.0)
    decile_size = max(len(ordered) // 10, 1)
    bottom = ordered[:decile_size]
    top = ordered[-decile_size:]
    xs = [parse_float(row.get(score_field)) for row in scored if parse_float(row.get(score_field)) is not None]
    ys_ret = [parse_float(row.get("forward_return_10d")) for row in scored if parse_float(row.get("forward_return_10d")) is not None]
    ys_dd = [parse_float(row.get("max_drawdown_10d")) for row in scored if parse_float(row.get("max_drawdown_10d")) is not None]
    corr_ret = correlation(xs, ys_ret)
    corr_dd = correlation(xs, ys_dd)
    top_ret = mean([parse_float(row.get("forward_return_10d")) for row in top if parse_float(row.get("forward_return_10d")) is not None])
    bottom_ret = mean([parse_float(row.get("forward_return_10d")) for row in bottom if parse_float(row.get("forward_return_10d")) is not None])
    top_dd = mean([parse_float(row.get("max_drawdown_10d")) for row in top if parse_float(row.get("max_drawdown_10d")) is not None])
    bottom_dd = mean([parse_float(row.get("max_drawdown_10d")) for row in bottom if parse_float(row.get("max_drawdown_10d")) is not None])
    if corr_ret is None or corr_dd is None:
        direction = "HIGHER_IS_AMBIGUOUS"
        diagnosis = "INSUFFICIENT_EVIDENCE"
    else:
        # Lower numeric drawdown values are worse; values closer to 0 are safer.
        if corr_ret > 0.05 and corr_dd > 0.05:
            direction = "HIGHER_IS_SAFER"
            diagnosis = "POSSIBLE_VALID_RISK_REDUCTION"
        elif corr_ret < -0.05 and corr_dd < -0.05:
            direction = "HIGHER_IS_RISKIER"
            diagnosis = "POSSIBLE_SCORE_DIRECTION_INVERSION"
        elif corr_ret < -0.05 and corr_dd > 0.02:
            direction = "HIGHER_IS_RISKIER"
            diagnosis = "POSSIBLE_VALID_RISK_REDUCTION"
        elif corr_ret < -0.05 and abs(corr_dd) <= 0.02:
            direction = "HIGHER_IS_RISKIER"
            diagnosis = "POSSIBLE_OVERPENALIZATION"
        else:
            direction = "HIGHER_IS_AMBIGUOUS"
            diagnosis = "INSUFFICIENT_EVIDENCE"
    return {
        "score_field": score_field,
        "evaluated_row_count": len(values),
        "correlation_forward_return_10d": fmt(corr_ret) if corr_ret is not None else "",
        "correlation_max_drawdown_10d": fmt(corr_dd) if corr_dd is not None else "",
        "top_decile_forward_return_10d": fmt(mean([parse_float(row.get("forward_return_10d")) for row in top if parse_float(row.get("forward_return_10d")) is not None])),
        "bottom_decile_forward_return_10d": fmt(mean([parse_float(row.get("forward_return_10d")) for row in bottom if parse_float(row.get("forward_return_10d")) is not None])),
        "top_decile_max_drawdown_10d": fmt(mean([parse_float(row.get("max_drawdown_10d")) for row in top if parse_float(row.get("max_drawdown_10d")) is not None])),
        "bottom_decile_max_drawdown_10d": fmt(mean([parse_float(row.get("max_drawdown_10d")) for row in bottom if parse_float(row.get("max_drawdown_10d")) is not None])),
        "direction_inference": direction,
        "diagnosis_flag": diagnosis,
    }


def infer_regime_direction(rows: list[dict[str, str]], score_field: str) -> dict[str, object]:
    scored = [row for row in rows if parse_float(row.get(score_field)) is not None and parse_float(row.get("forward_return_10d")) is not None]
    values = [parse_float(row.get(score_field)) for row in scored if parse_float(row.get(score_field)) is not None]
    if len(values) < 25:
        return {
            "score_field": score_field,
            "evaluated_row_count": len(values),
            "correlation_forward_return_10d": "",
            "correlation_excess_return_vs_QQQ_10d": "",
            "correlation_excess_return_vs_SOXX_10d": "",
            "correlation_excess_return_vs_SPY_10d": "",
            "top_decile_forward_return_10d": "",
            "bottom_decile_forward_return_10d": "",
            "regime_direction": "INSUFFICIENT_EVIDENCE",
            "diagnosis_flag": "INSUFFICIENT_EVIDENCE",
        }
    ordered = sorted(scored, key=lambda row: parse_float(row.get(score_field)) or 0.0)
    decile_size = max(len(ordered) // 10, 1)
    bottom = ordered[:decile_size]
    top = ordered[-decile_size:]
    xs = [parse_float(row.get(score_field)) for row in scored if parse_float(row.get(score_field)) is not None]
    ys_ret = [parse_float(row.get("forward_return_10d")) for row in scored if parse_float(row.get("forward_return_10d")) is not None]
    ys_q = [parse_float(row.get("excess_return_vs_QQQ_10d")) for row in scored if parse_float(row.get("excess_return_vs_QQQ_10d")) is not None]
    ys_s = [parse_float(row.get("excess_return_vs_SOXX_10d")) for row in scored if parse_float(row.get("excess_return_vs_SOXX_10d")) is not None]
    ys_p = [parse_float(row.get("excess_return_vs_SPY_10d")) for row in scored if parse_float(row.get("excess_return_vs_SPY_10d")) is not None]
    corr_ret = correlation(xs, ys_ret)
    corr_q = correlation(xs, ys_q)
    corr_s = correlation(xs, ys_s)
    corr_p = correlation(xs, ys_p)
    top_ret = mean([parse_float(row.get("forward_return_10d")) for row in top if parse_float(row.get("forward_return_10d")) is not None])
    bottom_ret = mean([parse_float(row.get("forward_return_10d")) for row in bottom if parse_float(row.get("forward_return_10d")) is not None])
    top_ex = mean([v for v in [parse_float(row.get("excess_return_vs_QQQ_10d")) for row in top if parse_float(row.get("excess_return_vs_QQQ_10d")) is not None] +
                   [parse_float(row.get("excess_return_vs_SOXX_10d")) for row in top if parse_float(row.get("excess_return_vs_SOXX_10d")) is not None] +
                   [parse_float(row.get("excess_return_vs_SPY_10d")) for row in top if parse_float(row.get("excess_return_vs_SPY_10d")) is not None]])
    bottom_ex = mean([v for v in [parse_float(row.get("excess_return_vs_QQQ_10d")) for row in bottom if parse_float(row.get("excess_return_vs_QQQ_10d")) is not None] +
                      [parse_float(row.get("excess_return_vs_SOXX_10d")) for row in bottom if parse_float(row.get("excess_return_vs_SOXX_10d")) is not None] +
                      [parse_float(row.get("excess_return_vs_SPY_10d")) for row in bottom if parse_float(row.get("excess_return_vs_SPY_10d")) is not None]])
    if any(c is None for c in [corr_ret, corr_q, corr_s, corr_p]):
        direction = "REGIME_SCORE_AMBIGUOUS"
        diagnosis = "INSUFFICIENT_EVIDENCE"
    else:
        avg_corr = mean([corr_ret, corr_q, corr_s, corr_p])  # type: ignore[arg-type]
        if avg_corr > 0.03 and top_ex >= bottom_ex:
            direction = "REGIME_SCORE_ALIGNED"
            diagnosis = "REGIME_SUPPORTS_RANKING"
        elif avg_corr < -0.03 and top_ex < bottom_ex:
            direction = "REGIME_SCORE_MISALIGNED"
            diagnosis = "REGIME_HURTS_RANKING"
        else:
            direction = "REGIME_SCORE_AMBIGUOUS"
            diagnosis = "REGIME_MIXED"
    return {
        "score_field": score_field,
        "evaluated_row_count": len(values),
        "correlation_forward_return_10d": fmt(corr_ret) if corr_ret is not None else "",
        "correlation_excess_return_vs_QQQ_10d": fmt(corr_q) if corr_q is not None else "",
        "correlation_excess_return_vs_SOXX_10d": fmt(corr_s) if corr_s is not None else "",
        "correlation_excess_return_vs_SPY_10d": fmt(corr_p) if corr_p is not None else "",
        "top_decile_forward_return_10d": fmt(top_ret),
        "bottom_decile_forward_return_10d": fmt(bottom_ret),
        "regime_direction": direction,
        "diagnosis_flag": diagnosis,
    }


def correlation(xs: list[float | None], ys: list[float | None]) -> float | None:
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 2:
        return None
    xv = [x for x, _ in pairs]
    yv = [y for _, y in pairs]
    mx = mean(xv)
    my = mean(yv)
    denom_x = math.sqrt(sum((x - mx) ** 2 for x in xv))
    denom_y = math.sqrt(sum((y - my) ** 2 for y in yv))
    if denom_x == 0 or denom_y == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in pairs) / (denom_x * denom_y)


def build_candidates_from_audits(risk_audit: list[dict[str, object]], regime_audit: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    risk_candidates = []
    regime_candidates = []
    for row in risk_audit:
        if row["diagnosis_flag"] in {"POSSIBLE_OVERPENALIZATION", "POSSIBLE_SCORE_DIRECTION_INVERSION"}:
            risk_candidates.append(
                {
                    "risk_field": row["score_field"],
                    "evidence_type": "DIRECTION_AUDIT",
                    "evidence_metric": "correlation_forward_return_10d",
                    "metric_value": row["correlation_forward_return_10d"],
                    "coverage_ratio": "",
                    "affected_row_count": row["evaluated_row_count"],
                    "impact_summary": f"top_decile_10d={row['top_decile_forward_return_10d']}; bottom_decile_10d={row['bottom_decile_forward_return_10d']}; top_dd={row['top_decile_max_drawdown_10d']}; bottom_dd={row['bottom_decile_max_drawdown_10d']}",
                    "candidate_action": "REVIEW_FOR_GATE_MODE" if row["diagnosis_flag"] == "POSSIBLE_SCORE_DIRECTION_INVERSION" else "REVIEW_FOR_DOWNWEIGHT",
                }
            )
    for row in regime_audit:
        if row["diagnosis_flag"] == "REGIME_HURTS_RANKING":
            regime_candidates.append(
                {
                    "regime_field": row["score_field"],
                    "segment_value": row["regime_direction"],
                    "evidence_metric": "correlation_excess_return_vs_QQQ_10d",
                    "metric_value": row["correlation_excess_return_vs_QQQ_10d"],
                    "coverage_ratio": "",
                    "impact_summary": f"top_decile_10d={row['top_decile_forward_return_10d']}; bottom_decile_10d={row['bottom_decile_forward_return_10d']}",
                    "candidate_action": "REVIEW_FOR_BENCHMARK_SPECIFIC_REGIME",
                }
            )
    return risk_candidates, regime_candidates


def build_repaired_plan(contamination_ratio: float, risk_audit: list[dict[str, object]], regime_audit: list[dict[str, object]], overheat_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    plan = [
        {
            "priority": 1,
            "plan_item": "Repair overheat audit logic before overheat simulation.",
            "evidence_source": "V21.003-R1 overheat status sanity audit",
            "rationale": "The original V21.003 false-block table included NOT_OVERHEAT rows and must not be reused directly.",
            "proposed_next_stage": "V21.004_OVERHEAT_LOGIC_REDEFINITION_SIMULATION",
            "allowed_action": "FURTHER_AUDIT_ONLY",
            "forbidden_action": "NO_OFFICIAL_WEIGHT_CHANGE|NO_OFFICIAL_RECOMMENDATION|NO_REAL_BOOK_SIGNAL|NO_BROKER_EXECUTION|NO_TRADE_ACTION",
        },
        {
            "priority": 2,
            "plan_item": "Audit risk-score direction before risk-weight simulation.",
            "evidence_source": "V21.003-R1 risk-score direction audit",
            "rationale": "Risk-score semantics can flip interpretation; direction must be verified before any simulation.",
            "proposed_next_stage": "V21.004_RISK_REGIME_SCORE_SEMANTIC_AUDIT",
            "allowed_action": "FURTHER_AUDIT_ONLY",
            "forbidden_action": "NO_OFFICIAL_WEIGHT_CHANGE|NO_OFFICIAL_RECOMMENDATION|NO_REAL_BOOK_SIGNAL|NO_BROKER_EXECUTION|NO_TRADE_ACTION",
        },
        {
            "priority": 3,
            "plan_item": "Audit regime-score direction before benchmark-specific simulation.",
            "evidence_source": "V21.003-R1 regime-score direction audit",
            "rationale": "Regime scores should only become gating logic after their directional meaning is confirmed.",
            "proposed_next_stage": "V21.004_RISK_REGIME_SCORE_SEMANTIC_AUDIT",
            "allowed_action": "FURTHER_AUDIT_ONLY",
            "forbidden_action": "NO_OFFICIAL_WEIGHT_CHANGE|NO_OFFICIAL_RECOMMENDATION|NO_REAL_BOOK_SIGNAL|NO_BROKER_EXECUTION|NO_TRADE_ACTION",
        },
        {
            "priority": 4,
            "plan_item": "Convert ambiguous risk/regime scores into warning/report layers until directional semantics are confirmed.",
            "evidence_source": "V21.003-R1 repaired direction audits",
            "rationale": "Ambiguous semantics should not be promoted into ranking weights.",
            "proposed_next_stage": "V21.004_RISK_REGIME_SCORE_SEMANTIC_AUDIT",
            "allowed_action": "DESIGN_ONLY",
            "forbidden_action": "NO_OFFICIAL_WEIGHT_CHANGE|NO_OFFICIAL_RECOMMENDATION|NO_REAL_BOOK_SIGNAL|NO_BROKER_EXECUTION|NO_TRADE_ACTION",
        },
    ]
    if any(row["false_block_flag"] == "OVERHEAT_FALSE_BLOCK_CONTINUED_STRONG" for row in overheat_rows):
        plan.append(
            {
                "priority": 5,
                "plan_item": "Proceed to overheat logic redefinition only if true overheat-positive rows show continuation.",
                "evidence_source": "V21.003-R1 repaired overheat false-block audit",
                "rationale": "Continuation after true overheat labels may justify a logic split between exhaustion and trend strength.",
                "proposed_next_stage": "V21.004_OVERHEAT_LOGIC_REDEFINITION_SIMULATION",
                "allowed_action": "SIMULATION_ONLY",
                "forbidden_action": "NO_OFFICIAL_WEIGHT_CHANGE|NO_OFFICIAL_RECOMMENDATION|NO_REAL_BOOK_SIGNAL|NO_BROKER_EXECUTION|NO_TRADE_ACTION",
            }
        )
    if contamination_ratio >= 0.25:
        plan.insert(
            0,
            {
                "priority": 0,
                "plan_item": "Repair V21.003 overheat logic before any simulation.",
                "evidence_source": "V21.003 original false-block table contamination",
                "rationale": "The original audit was materially contaminated by NOT_OVERHEAT rows.",
                "proposed_next_stage": "V21.004_RISK_REGIME_SCORE_SEMANTIC_AUDIT",
                "allowed_action": "FURTHER_AUDIT_ONLY",
                "forbidden_action": "NO_OFFICIAL_WEIGHT_CHANGE|NO_OFFICIAL_RECOMMENDATION|NO_REAL_BOOK_SIGNAL|NO_BROKER_EXECUTION|NO_TRADE_ACTION",
            }
        )
    return plan


def diagnose_strategy(contamination_ratio: float, risk_audit: list[dict[str, object]], regime_audit: list[dict[str, object]], overheat_rows: list[dict[str, object]]) -> str:
    parts = []
    if contamination_ratio >= 0.25:
        parts.append("original overheat audit was contaminated by NOT_OVERHEAT rows")
    if any(row["diagnosis_flag"] == "POSSIBLE_OVERPENALIZATION" for row in risk_audit):
        parts.append("risk-score over-penalization remains plausible after repair")
    if any(row["diagnosis_flag"] == "POSSIBLE_SCORE_DIRECTION_INVERSION" for row in risk_audit):
        parts.append("risk-score direction inversion remains plausible after repair")
    if any(row["diagnosis_flag"] == "REGIME_HURTS_RANKING" for row in regime_audit):
        parts.append("regime-score misalignment remains plausible after repair")
    if any(row["false_block_flag"] == "OVERHEAT_FALSE_BLOCK_CONTINUED_STRONG" for row in overheat_rows):
        parts.append("true overheat-positive rows still showed continuation in repaired evidence")
    if not parts:
        parts.append("repaired evidence is limited and should remain audit-only")
    return "; ".join(parts) + "."


def audit_direction_label(row: dict[str, object]) -> str:
    return str(row.get("direction_inference") or row.get("regime_direction") or row.get("diagnosis_flag") or "")


def next_recommended_action(contamination_ratio: float, risk_audit: list[dict[str, object]], regime_audit: list[dict[str, object]], overheat_rows: list[dict[str, object]]) -> str:
    if contamination_ratio >= 0.25:
        return "Repair V21.003 overheat logic before any simulation."
    if any(row["diagnosis_flag"] == "POSSIBLE_SCORE_DIRECTION_INVERSION" for row in risk_audit + regime_audit):
        return "Proceed to V21.004_RISK_REGIME_SCORE_SEMANTIC_AUDIT."
    if any(row["diagnosis_flag"] == "POSSIBLE_OVERPENALIZATION" for row in risk_audit):
        return "Proceed to V21.004_RISK_WEIGHT_REPAIR_SIMULATION."
    if any(row["diagnosis_flag"] == "REGIME_HURTS_RANKING" for row in regime_audit):
        return "Proceed to V21.004_BENCHMARK_SPECIFIC_REGIME_REPAIR_SIMULATION."
    if any(row["false_block_flag"] == "OVERHEAT_FALSE_BLOCK_CONTINUED_STRONG" for row in overheat_rows):
        return "Proceed to V21.004_OVERHEAT_LOGIC_REDEFINITION_SIMULATION."
    return "Proceed to V21.004_RISK_REGIME_SCORE_SEMANTIC_AUDIT."


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)

    try:
        inputs = load_required_inputs()
    except FileNotFoundError:
        gate = {
            "stage_name": STAGE_NAME,
            "final_status": "FAIL_V21_003_R1_REQUIRED_INPUTS_MISSING",
            "original_overheat_false_block_candidate_count": 0,
            "repaired_true_overheat_row_count": 0,
            "repaired_false_block_candidate_count": 0,
            "removed_not_overheat_row_count": 0,
            "contamination_ratio": "0.0000000000",
            "risk_score_direction_audited_field_count": 0,
            "regime_score_direction_audited_field_count": 0,
            "repaired_risk_overpenalization_candidate_count": 0,
            "repaired_regime_misalignment_candidate_count": 0,
            "audit_sanity_status": "MISSING_INPUTS",
            "strategy_diagnosis": "required V21.003 inputs are missing.",
            "next_recommended_action": "Repair the missing V21.003 inputs before continuing.",
        }
        gate.update({field: "FALSE" for field in FALSE_FIELDS})
        write_csv(GATE, [gate], [
            "stage_name",
            "final_status",
            "original_overheat_false_block_candidate_count",
            "repaired_true_overheat_row_count",
            "repaired_false_block_candidate_count",
            "removed_not_overheat_row_count",
            "contamination_ratio",
            "risk_score_direction_audited_field_count",
            "regime_score_direction_audited_field_count",
            "repaired_risk_overpenalization_candidate_count",
            "repaired_regime_misalignment_candidate_count",
            "audit_sanity_status",
            "strategy_diagnosis",
            "next_recommended_action",
        ] + FALSE_FIELDS)
        REPORT.write_text("# V21.003-R1 Risk/Regime Audit Sanity Repair\n\n## Final status\nMissing required inputs.\n", encoding="utf-8")
        print(f"STAGE_NAME={STAGE_NAME}")
        print(f"final_status={gate['final_status']}")
        print("original_overheat_false_block_candidate_count=0")
        print("repaired_true_overheat_row_count=0")
        print("repaired_false_block_candidate_count=0")
        print("removed_not_overheat_row_count=0")
        print("contamination_ratio=0.0000000000")
        print("risk_score_direction_audited_field_count=0")
        print("regime_score_direction_audited_field_count=0")
        print("next_recommended_action=Repair the missing V21.003 inputs before continuing.")
        return 0

    joined_rows = inputs[str(V21_RECAL_DIR / "V21_003_RISK_REGIME_JOINED_OUTCOME_ROWS.csv")]
    original_overheat = inputs[str(V21_RECAL_DIR / "V21_003_OVERHEAT_FALSE_BLOCK_AUDIT.csv")]
    original_overheat_count = len(original_overheat)
    if not joined_rows:
        gate = {
            "stage_name": STAGE_NAME,
            "final_status": "FAIL_V21_003_R1_JOINED_ROWS_MISSING",
            "original_overheat_false_block_candidate_count": original_overheat_count,
            "repaired_true_overheat_row_count": 0,
            "repaired_false_block_candidate_count": 0,
            "removed_not_overheat_row_count": original_overheat_count,
            "contamination_ratio": fmt(1.0 if original_overheat_count else 0.0),
            "risk_score_direction_audited_field_count": 0,
            "regime_score_direction_audited_field_count": 0,
            "repaired_risk_overpenalization_candidate_count": 0,
            "repaired_regime_misalignment_candidate_count": 0,
            "audit_sanity_status": "JOINED_ROWS_MISSING",
            "strategy_diagnosis": "joined risk/regime outcome rows are missing or empty.",
            "next_recommended_action": "Repair the missing joined rows before continuing.",
        }
        gate.update({field: "FALSE" for field in FALSE_FIELDS})
        write_csv(GATE, [gate], [
            "stage_name",
            "final_status",
            "original_overheat_false_block_candidate_count",
            "repaired_true_overheat_row_count",
            "repaired_false_block_candidate_count",
            "removed_not_overheat_row_count",
            "contamination_ratio",
            "risk_score_direction_audited_field_count",
            "regime_score_direction_audited_field_count",
            "repaired_risk_overpenalization_candidate_count",
            "repaired_regime_misalignment_candidate_count",
            "audit_sanity_status",
            "strategy_diagnosis",
            "next_recommended_action",
        ] + FALSE_FIELDS)
        REPORT.write_text("# V21.003-R1 Risk/Regime Audit Sanity Repair\n\n## Final status\nJoined rows missing.\n", encoding="utf-8")
        print(f"STAGE_NAME={STAGE_NAME}")
        print(f"final_status={gate['final_status']}")
        print(f"original_overheat_false_block_candidate_count={original_overheat_count}")
        print("repaired_true_overheat_row_count=0")
        print("repaired_false_block_candidate_count=0")
        print(f"removed_not_overheat_row_count={original_overheat_count}")
        print(f"contamination_ratio={gate['contamination_ratio']}")
        print("risk_score_direction_audited_field_count=0")
        print("regime_score_direction_audited_field_count=0")
        print("next_recommended_action=Repair the missing joined rows before continuing.")
        return 0

    status_map = load_v20_strategy_status_map()
    repaired_overheat_rows, overheat_summary = build_repaired_overheat_audit(joined_rows, status_map)
    overheat_sanity_rows = []
    for ticker, payload in sorted(status_map.items()):
        status = payload["overheat_status"]
        overheat_sanity_rows.append(
            {
                "ticker": ticker,
                "derived_overheat_status": status,
                "positive_filter_pass": str(is_positive_overheat_text(status)).upper(),
                "negative_filter_hit": str(not is_positive_overheat_text(status)).upper(),
                "source_artifact": payload["strategy_source_artifact"],
                "strategy_component_score": payload["strategy_component_score"],
                "strategy_raw_columns_used": payload["strategy_raw_columns_used"],
                "strategy_categorical_mappings_used": payload["strategy_categorical_mappings_used"],
            }
        )
    risk_audits = [infer_score_direction(joined_rows, field) for field in RISK_FIELDS if any(parse_float(row.get(field)) is not None for row in joined_rows)]
    regime_audits = [infer_regime_direction(joined_rows, field) for field in REGIME_FIELDS if any(parse_float(row.get(field)) is not None for row in joined_rows)]
    risk_candidates, regime_candidates = build_candidates_from_audits(risk_audits, regime_audits)
    repaired_plan = build_repaired_plan(
        overheat_summary["contamination_ratio"],
        risk_audits,
        regime_audits,
        repaired_overheat_rows,
    )
    contamination_ratio = overheat_summary["contamination_ratio"]
    if contamination_ratio >= 0.25:
        final_status = "PARTIAL_PASS_V21_003_R1_OVERHEAT_AUDIT_CONTAMINATED_REPAIRED"
    elif any(audit_direction_label(row) in {"HIGHER_IS_AMBIGUOUS", "REGIME_SCORE_AMBIGUOUS", "INSUFFICIENT_EVIDENCE"} or row["diagnosis_flag"] == "INSUFFICIENT_EVIDENCE" for row in risk_audits + regime_audits):
        final_status = "PARTIAL_PASS_V21_003_R1_SCORE_DIRECTION_AMBIGUOUS"
    else:
        final_status = "PASS_V21_003_R1_AUDIT_SANITY_REPAIRED_READY_FOR_SIMULATION_SELECTION"

    audit_sanity_status = "CONTAMINATION_CONFIRMED_AND_REPAIRED" if contamination_ratio >= 0.25 else "SANITY_REPAIRED"
    gate = {
        "stage_name": STAGE_NAME,
        "final_status": final_status,
        "original_overheat_false_block_candidate_count": overheat_summary["original_overheat_false_block_candidate_count"],
        "repaired_true_overheat_row_count": overheat_summary["repaired_true_overheat_row_count"],
        "repaired_false_block_candidate_count": overheat_summary["repaired_false_block_candidate_count"],
        "removed_not_overheat_row_count": overheat_summary["removed_not_overheat_row_count"],
        "contamination_ratio": fmt(contamination_ratio),
        "risk_score_direction_audited_field_count": len(risk_audits),
        "regime_score_direction_audited_field_count": len(regime_audits),
        "repaired_risk_overpenalization_candidate_count": len(risk_candidates),
        "repaired_regime_misalignment_candidate_count": len(regime_candidates),
        "audit_sanity_status": audit_sanity_status,
        "strategy_diagnosis": diagnose_strategy(contamination_ratio, risk_audits, regime_audits, repaired_overheat_rows),
        "next_recommended_action": next_recommended_action(contamination_ratio, risk_audits, regime_audits, repaired_overheat_rows),
    }
    gate.update({field: "FALSE" for field in FALSE_FIELDS})

    write_csv(INPUT_VALIDATION, validate_inputs(), ["artifact_path", "exists_non_empty", "row_count", "validation_status", "selection_reason"])
    write_csv(
        OVERHEAT_SANITY,
        overheat_sanity_rows,
        ["ticker", "derived_overheat_status", "positive_filter_pass", "negative_filter_hit", "source_artifact", "strategy_component_score", "strategy_raw_columns_used", "strategy_categorical_mappings_used"],
    )
    write_csv(
        REPAIRED_OVERHEAT,
        repaired_overheat_rows,
        [
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
        ],
    )
    write_csv(
        RISK_DIR_AUDIT,
        risk_audits,
        [
            "score_field",
            "evaluated_row_count",
            "correlation_forward_return_10d",
            "correlation_max_drawdown_10d",
            "top_decile_forward_return_10d",
            "bottom_decile_forward_return_10d",
            "top_decile_max_drawdown_10d",
            "bottom_decile_max_drawdown_10d",
            "direction_inference",
            "diagnosis_flag",
        ],
    )
    write_csv(
        REGIME_DIR_AUDIT,
        regime_audits,
        [
            "score_field",
            "evaluated_row_count",
            "correlation_forward_return_10d",
            "correlation_excess_return_vs_QQQ_10d",
            "correlation_excess_return_vs_SOXX_10d",
            "correlation_excess_return_vs_SPY_10d",
            "top_decile_forward_return_10d",
            "bottom_decile_forward_return_10d",
            "regime_direction",
            "diagnosis_flag",
        ],
    )
    write_csv(
        REPAIRED_RISK_CAND,
        risk_candidates,
        [
            "risk_field",
            "evidence_type",
            "evidence_metric",
            "metric_value",
            "coverage_ratio",
            "affected_row_count",
            "impact_summary",
            "candidate_action",
        ],
    )
    write_csv(
        REPAIRED_REGIME_CAND,
        regime_candidates,
        [
            "regime_field",
            "segment_value",
            "evidence_metric",
            "metric_value",
            "coverage_ratio",
            "impact_summary",
            "candidate_action",
        ],
    )
    write_csv(
        REPAIRED_PLAN,
        repaired_plan,
        [
            "priority",
            "plan_item",
            "evidence_source",
            "rationale",
            "proposed_next_stage",
            "allowed_action",
            "forbidden_action",
        ],
    )
    write_csv(
        GATE,
        [gate],
        [
            "stage_name",
            "final_status",
            "original_overheat_false_block_candidate_count",
            "repaired_true_overheat_row_count",
            "repaired_false_block_candidate_count",
            "removed_not_overheat_row_count",
            "contamination_ratio",
            "risk_score_direction_audited_field_count",
            "regime_score_direction_audited_field_count",
            "repaired_risk_overpenalization_candidate_count",
            "repaired_regime_misalignment_candidate_count",
            "audit_sanity_status",
            "strategy_diagnosis",
            "next_recommended_action",
        ]
        + FALSE_FIELDS,
    )
    write_report(gate, f"Original V21.003 overheat false-block count was contaminated by NOT_OVERHEAT rows. Removed {overheat_summary['removed_not_overheat_row_count']} of {overheat_summary['original_overheat_false_block_candidate_count']} original rows.")

    print(f"STAGE_NAME={STAGE_NAME}")
    print(f"final_status={final_status}")
    print(f"original_overheat_false_block_candidate_count={overheat_summary['original_overheat_false_block_candidate_count']}")
    print(f"repaired_true_overheat_row_count={overheat_summary['repaired_true_overheat_row_count']}")
    print(f"repaired_false_block_candidate_count={overheat_summary['repaired_false_block_candidate_count']}")
    print(f"removed_not_overheat_row_count={overheat_summary['removed_not_overheat_row_count']}")
    print(f"contamination_ratio={fmt(contamination_ratio)}")
    print(f"risk_score_direction_audited_field_count={len(risk_audits)}")
    print(f"regime_score_direction_audited_field_count={len(regime_audits)}")
    print(f"next_recommended_action={gate['next_recommended_action']}")
    return 0 if final_status in ALLOWED_FINAL_STATUSES else 1


if __name__ == "__main__":
    raise SystemExit(main())
