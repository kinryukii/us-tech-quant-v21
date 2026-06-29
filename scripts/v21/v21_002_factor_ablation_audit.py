#!/usr/bin/env python
"""V21.002 factor ablation audit.

Research-only stage that diagnoses which factor families and score components
appear to help or hurt forward performance. This script only reads local CSVs
and writes audit artifacts under outputs/v21/ablation and outputs/v21/read_center.
"""

from __future__ import annotations

import csv
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Iterable


STAGE_NAME = "V21_002_FACTOR_ABLATION_AUDIT"
ROOT = Path(__file__).resolve().parents[2]
V20_DIR = ROOT / "outputs" / "v20"
V21_AUDIT_DIR = ROOT / "outputs" / "v21" / "audit"
OUT_DIR = ROOT / "outputs" / "v21" / "ablation"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

REQ_V21_001_FILES = [
    V21_AUDIT_DIR / "V21_001_BASELINE_RANKING_SNAPSHOT.csv",
    V21_AUDIT_DIR / "V21_001_FORWARD_OUTCOME_ROWS.csv",
    V21_AUDIT_DIR / "V21_001_BUCKET_PERFORMANCE_SUMMARY.csv",
    V21_AUDIT_DIR / "V21_001_BENCHMARK_RELATIVE_PERFORMANCE.csv",
    V21_AUDIT_DIR / "V21_001_NEXT_STAGE_GATE.csv",
]

INPUT_DISCOVERY = OUT_DIR / "V21_002_INPUT_DISCOVERY.csv"
FIELD_MAP = OUT_DIR / "V21_002_FACTOR_FIELD_MAP.csv"
JOINED_ROWS = OUT_DIR / "V21_002_BASELINE_JOINED_FACTOR_OUTCOME_ROWS.csv"
SINGLE_FAMILY = OUT_DIR / "V21_002_SINGLE_FACTOR_FAMILY_PERFORMANCE.csv"
LEAVE_ONE_OUT = OUT_DIR / "V21_002_LEAVE_ONE_FAMILY_OUT_PERFORMANCE.csv"
REMOVAL_IMPACT = OUT_DIR / "V21_002_FACTOR_REMOVAL_IMPACT.csv"
NEGATIVE_CANDIDATES = OUT_DIR / "V21_002_NEGATIVE_CONTRIBUTOR_CANDIDATES.csv"
POSITIVE_CANDIDATES = OUT_DIR / "V21_002_POSITIVE_CONTRIBUTOR_CANDIDATES.csv"
DIAGNOSIS = OUT_DIR / "V21_002_RANKING_WEAKNESS_DIAGNOSIS.csv"
GATE = OUT_DIR / "V21_002_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER_DIR / "V21_002_FACTOR_ABLATION_AUDIT_REPORT.md"

ALLOWED_FINAL_STATUSES = {
    "FAIL_V21_002_REQUIRED_V21_001_INPUTS_MISSING",
    "FAIL_V21_002_NO_FACTOR_FIELDS_DETECTED",
    "PARTIAL_PASS_V21_002_LIMITED_FACTOR_COVERAGE",
    "PARTIAL_PASS_V21_002_ABLATION_EVIDENCE_LIMITED",
    "PASS_V21_002_FACTOR_ABLATION_READY_FOR_WEIGHT_REPAIR_PLAN",
}
MANDATORY_FALSE_FIELDS = [
    "official_weight_mutated",
    "official_recommendation_created",
    "real_book_signal_created",
    "broker_execution_supported",
    "trade_action_created",
    "shadow_weight_activated",
]
BENCHMARKS = ["QQQ", "SOXX", "SPY"]
FAMILY_ORDER = [
    "FUNDAMENTAL",
    "TECHNICAL",
    "STRATEGY",
    "RISK",
    "MARKET_REGIME",
    "DATA_TRUST",
    "VALUATION",
    "QUALITY",
    "GROWTH",
    "MOMENTUM",
    "ENTRY_TIMING",
    "OTHER",
]
SCORE_PATTERNS = [
    "score",
    "contribution",
    "component_score",
    "factor_score",
    "rank",
]
EXCLUDE_SCORE_TOKENS = [
    "official_",
    "mutated",
    "action",
    "recommendation",
    "claim",
    "count",
    "status",
    "reason",
    "allowed",
    "blocked",
    "required",
    "usable",
    "fabricated",
    "source_",
    "current_",
    "no_",
    "trade_",
    "broker_",
    "performance_",
    "cache",
]


def norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").strip().lower()).strip("_")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle).fieldnames or [])


def count_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return max(sum(1 for _ in handle) - 1, 0)


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


def parse_date(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    candidates = [text, text[:10], text.replace("/", "-")]
    for candidate in candidates:
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


def percentile_rank(values: list[float], value: float) -> float:
    if not values:
        return float("nan")
    if len(values) == 1:
        return 1.0
    ordered = sorted(values)
    lower = sum(1 for item in ordered if item < value)
    equal = sum(1 for item in ordered if item == value)
    return (lower + 0.5 * max(equal - 1, 0)) / (len(ordered) - 1)


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(ys) < 2 or len(xs) != len(ys):
        return None
    mx = mean(xs)
    my = mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mx) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - my) ** 2 for y in ys))
    if den_x == 0 or den_y == 0:
        return None
    return num / (den_x * den_y)


def rankdata(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i + 1
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[indexed[k][0]] = avg_rank
        i = j
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    return pearson(rankdata(xs), rankdata(ys))


def safe_mean(values: Iterable[object]) -> str:
    numeric = [value for value in (parse_float(item) for item in values) if value is not None]
    return "" if not numeric else f"{mean(numeric):.10f}"


def safe_median(values: list[float]) -> str:
    return "" if not values else f"{median(values):.10f}"


def safe_corr(values_x: list[float], values_y: list[float]) -> str:
    corr = pearson(values_x, values_y)
    return "" if corr is None else f"{corr:.10f}"


def safe_spearman(values_x: list[float], values_y: list[float]) -> str:
    corr = spearman(values_x, values_y)
    return "" if corr is None else f"{corr:.10f}"


def detect_ticker_field(columns: list[str]) -> str | None:
    candidates = ["ticker", "symbol", "ticker_or_candidate_id", "display_name_or_ticker"]
    lookup = {norm(col): col for col in columns}
    for candidate in candidates:
        if norm(candidate) in lookup:
            return lookup[norm(candidate)]
    for col in columns:
        if any(token in norm(col) for token in ["ticker", "symbol"]):
            return col
    return None


def detect_date_field(columns: list[str]) -> str | None:
    candidates = ["as_of_date", "signal_date", "date", "snapshot_date"]
    lookup = {norm(col): col for col in columns}
    for candidate in candidates:
        if norm(candidate) in lookup:
            return lookup[norm(candidate)]
    for col in columns:
        if any(token in norm(col) for token in ["asof", "signal", "date", "snapshot"]):
            return col
    return None


def detect_rank_field(columns: list[str]) -> str | None:
    for candidate in ["rank", "baseline_rank", "pit_lite_rank", "asof_technical_rank", "rank_within_asof_scenario", "zero_weight_rank"]:
        if candidate in {norm(col) for col in columns}:
            return {norm(col): col for col in columns}[candidate]
    for col in columns:
        if "rank" in norm(col):
            return col
    return None


def detect_score_columns(columns: list[str]) -> list[str]:
    result = []
    for col in columns:
        n = norm(col)
        if n in {"row_hash", "source_artifact", "source_stage", "source_status", "rank", "baseline_rank"} or "rank" in n:
            continue
        if any(block in n for block in EXCLUDE_SCORE_TOKENS):
            continue
        if any(pattern in n for pattern in SCORE_PATTERNS):
            if "score" in n and not any(token in n for token in [
                "fundamental",
                "technical",
                "strategy",
                "risk",
                "market_regime",
                "data_trust",
                "valuation",
                "quality",
                "growth",
                "momentum",
                "entry",
                "pullback",
                "breakout",
                "buy_zone",
                "overheat",
                "pit_lite",
                "zero_weight",
                "composite_candidate",
                "factor",
            ]):
                continue
            result.append(col)
    return result


def rel_key(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def map_family(column_name: str, artifact_path: Path) -> tuple[str, str, str]:
    n = norm(column_name)
    p = norm(artifact_path.name)
    path_text = norm(str(artifact_path))
    if "data_trust" in n or "freshness" in n or "coverage" in n or "quality" in n and "data_quality" in n:
        return "DATA_TRUST", "high", "column name indicates data trust / freshness / coverage"
    if "market_regime" in n or any(token in n for token in ["sector_exposure", "industry_exposure", "theme_exposure", "benchmark_exposure", "etf_regime", "macro_regime", "risk_on_off"]):
        return "MARKET_REGIME", "high", "column name indicates market regime exposure"
    if "fundamental" in n:
        return "FUNDAMENTAL", "high", "column name indicates fundamental factor"
    if "technical" in n and "technical_timing" not in n:
        return "TECHNICAL", "high", "column name indicates technical factor"
    if "strategy" in n:
        return "STRATEGY", "high", "column name indicates strategy factor"
    if "risk" in n or any(token in n for token in ["downside", "volatility", "drawdown", "leverage", "balance_sheet", "valuation_risk", "event_macro", "trend_break"]):
        if "valuation" in n:
            return "VALUATION", "high", "column name indicates valuation risk"
        if "balance_sheet" in n:
            return "QUALITY", "medium", "column name indicates balance-sheet quality / defensive quality"
        return "RISK", "high", "column name indicates risk factor"
    if "valuation" in n:
        return "VALUATION", "high", "column name indicates valuation factor"
    if "quality" in n:
        return "QUALITY", "high", "column name indicates quality factor"
    if "growth" in n:
        return "GROWTH", "high", "column name indicates growth factor"
    if any(token in n for token in ["momentum", "relative_strength", "trend", "volume_confirmation"]):
        return "MOMENTUM", "high", "column name indicates momentum factor"
    if any(token in n for token in ["entry", "pullback", "breakout", "buy_zone", "overheat", "technical_timing", "technical_signal"]):
        return "ENTRY_TIMING", "high", "column name indicates entry timing factor"
    if n in {"score", "composite_candidate_score", "factor_score"} or ("score" in n and "rank" not in n):
        if "technical" in p or "technical" in path_text:
            return "TECHNICAL", "medium", "generic score column in a technical artifact"
        if "strategy" in p or "strategy" in path_text:
            return "STRATEGY", "medium", "generic score column in a strategy artifact"
        if "risk" in p or "risk" in path_text:
            return "RISK", "medium", "generic score column in a risk artifact"
        if "market_regime" in p or "regime" in p or "regime" in path_text:
            return "MARKET_REGIME", "medium", "generic score column in a regime artifact"
        if "fundamental" in p or "fundamental" in path_text:
            return "FUNDAMENTAL", "medium", "generic score column in a fundamental artifact"
        return "OTHER", "low", "generic score column with no family-specific context"
    return "OTHER", "low", "no confident family mapping"


def artifact_type(path: Path, columns: list[str]) -> str:
    p = path.name.lower()
    if "research_view" in p:
        return "research_view"
    if "factor_family" in p:
        return "factor_family_score_table"
    if "random_asof" in p and "recomputed_factor_snapshot" in p:
        return "historical_asof_factor_snapshot"
    if "strategy_candidate_score_source" in p:
        return "strategy_candidate_score_source"
    if "risk_candidate_score_source" in p:
        return "risk_candidate_score_source"
    if "fundamental_candidate_score_source" in p:
        return "fundamental_candidate_score_source"
    if "market_regime_candidate_exposure_source" in p:
        return "market_regime_candidate_exposure_source"
    if "technical_score" in p or "technical" in p:
        return "technical_score_source"
    if {"ticker", "rank"} & {norm(col) for col in columns}:
        return "rank_or_score_source"
    return "other"


def is_relevant_artifact(path: Path, columns: list[str]) -> bool:
    if path.suffix.lower() != ".csv":
        return False
    if "shadow" in path.name.lower():
        return False
    ticker = detect_ticker_field(columns)
    score_cols = detect_score_columns(columns)
    if not ticker or not score_cols:
        return False
    if any(token in path.name.lower() for token in ["candidate", "ranking", "research_view", "factor", "backtest", "technical", "risk", "strategy", "regime", "fundamental"]):
        return True
    return False


def discover_source_artifacts() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(V20_DIR.rglob("*.csv")):
        columns = read_header(path)
        if not columns:
            continue
        if not is_relevant_artifact(path, columns):
            continue
        score_cols = detect_score_columns(columns)
        rows.append(
            {
                "artifact_path": rel_key(path),
                "artifact_type": artifact_type(path, columns),
                "exists_non_empty": str(path.exists() and path.stat().st_size > 0).upper(),
                "row_count": count_rows(path),
                "detected_columns": "|".join(columns),
                "selected_for_audit": "TRUE",
                "selection_reason": "contains usable ticker/date/score columns for factor ablation",
                "validation_status": "PASS_SCORE_SOURCE_DETECTED",
                "_score_columns": score_cols,
                "_ticker_col": detect_ticker_field(columns),
                "_date_col": detect_date_field(columns),
                "_rank_col": detect_rank_field(columns),
                "_columns": columns,
                "_path": path,
            }
        )
    return rows


def load_artifact_index(artifact: dict[str, object]) -> dict[tuple[str | None, str], dict[str, object]]:
    path: Path = artifact["_path"]  # type: ignore[index]
    columns: list[str] = artifact["_columns"]  # type: ignore[index]
    ticker_col: str | None = artifact["_ticker_col"]  # type: ignore[index]
    date_col: str | None = artifact["_date_col"]  # type: ignore[index]
    rank_col: str | None = artifact["_rank_col"]  # type: ignore[index]
    score_cols: list[str] = artifact["_score_columns"]  # type: ignore[index]
    family_map: dict[str, tuple[str, str, str]] = {}
    for col in score_cols:
        family_map[col] = map_family(col, path)
    index: dict[tuple[str | None, str], dict[str, object]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            ticker = str(raw.get(ticker_col, "") if ticker_col else "").strip().upper()
            if not ticker:
                continue
            as_of = parse_date(raw.get(date_col)) if date_col else None
            key = (as_of, ticker)
            candidate = index.get(key)
            if candidate is None:
                candidate = {"rows": [], "best_rank": None}
                index[key] = candidate
            rank = parse_int(raw.get(rank_col)) if rank_col else None
            if candidate["best_rank"] is None or (rank is not None and rank < candidate["best_rank"]):  # type: ignore[operator]
                candidate["best_rank"] = rank
                candidate["row"] = raw
            candidate["rows"].append(raw)
    # add a ticker-only fallback index
    collapsed: dict[tuple[str | None, str], dict[str, object]] = {}
    for key, payload in index.items():
        as_of, ticker = key
        row = payload.get("row") or payload["rows"][0]
        collapsed[key] = {
            "row": row,
            "family_values": extract_family_values(row, path, family_map),
        }
        if as_of is None:
            collapsed[(None, ticker)] = collapsed[key]
    return collapsed


def extract_family_values(row: dict[str, str], path: Path, family_map: dict[str, tuple[str, str, str]]) -> dict[str, list[tuple[str, float]]]:
    out: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for column, (family, _confidence, _reason) in family_map.items():
        value = parse_float(row.get(column))
        if value is None:
            continue
        out[family].append((column, value))
    return out


def artifact_score_map(artifact: dict[str, object], index: dict[tuple[str | None, str], dict[str, object]], as_of: str, ticker: str) -> dict[str, float | None]:
    # exact date match first, then ticker-only fallback
    payload = index.get((as_of, ticker)) or index.get((None, ticker))
    if not payload:
        return {family: None for family in FAMILY_ORDER}
    family_values: dict[str, list[tuple[str, float]]] = payload["family_values"]  # type: ignore[index]
    result: dict[str, float | None] = {family: None for family in FAMILY_ORDER}
    for family, values in family_values.items():
        if values:
            result[family] = mean(v for _col, v in values)
    return result


def build_discovery_and_indexes() -> tuple[list[dict[str, object]], dict[str, dict[tuple[str | None, str], dict[str, object]]], dict[str, list[tuple[str, str, str, str]]]]:
    discovery = discover_source_artifacts()
    indexes: dict[str, dict[tuple[str | None, str], dict[str, object]]] = {}
    field_map: dict[str, list[tuple[str, str, str, str]]] = defaultdict(list)
    for artifact in discovery:
        path = artifact["_path"]  # type: ignore[index]
        family_map = {}
        for col in artifact["_score_columns"]:  # type: ignore[index]
            family, confidence, reason = map_family(col, path)
            family_map[col] = (family, confidence, reason)
            field_map[rel_key(path)].append((col, family, confidence, reason))
        artifact["_family_map"] = family_map
        indexes[rel_key(path)] = load_artifact_index(artifact)
    return discovery, indexes, field_map


def load_v21_base() -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, str]]:
    missing = [path for path in REQ_V21_001_FILES if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing required V21.001 inputs: {missing}")
    snapshot = read_csv(V21_AUDIT_DIR / "V21_001_BASELINE_RANKING_SNAPSHOT.csv")
    outcomes = read_csv(V21_AUDIT_DIR / "V21_001_FORWARD_OUTCOME_ROWS.csv")
    gate = read_csv(V21_AUDIT_DIR / "V21_001_NEXT_STAGE_GATE.csv")[0]
    outcome_map = {(row["as_of_date"], row["ticker"]): row for row in outcomes}
    joined_base = []
    for row in snapshot:
        key = (row["as_of_date"], row["ticker"])
        outcome = outcome_map.get(key, {})
        merged = {**row, **outcome}
        joined_base.append(merged)
    return snapshot, joined_base, gate


def build_joined_rows(base_rows: list[dict[str, str]], indexes: dict[str, dict[tuple[str | None, str], dict[str, object]]]) -> list[dict[str, object]]:
    joined: list[dict[str, object]] = []
    # family preferences prioritize the most specific artifact for each family
    family_priority = {
        "FUNDAMENTAL": ["outputs/v20/consolidation/V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_TABLE.csv", "outputs/v20/consolidation/V20_108_R6_FUNDAMENTAL_CANDIDATE_SCORE_SOURCE.csv"],
        "TECHNICAL": [
            "outputs/v20/backtest/V20_199B_R1_RANDOM_ASOF_RECOMPUTED_FACTOR_SNAPSHOT.csv",
            "outputs/v20/consolidation/V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_TABLE.csv",
            "outputs/v20/consolidation/V20_35_R2_ASOF_TECHNICAL_SCORE_AND_RANKING.csv",
        ],
        "STRATEGY": [
            "outputs/v20/consolidation/V20_108_R7_STRATEGY_CANDIDATE_SCORE_SOURCE.csv",
            "outputs/v20/backtest/V20_199B_R1_RANDOM_ASOF_RECOMPUTED_FACTOR_SNAPSHOT.csv",
            "outputs/v20/consolidation/V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_TABLE.csv",
        ],
        "RISK": [
            "outputs/v20/backtest/V20_199B_R1_RANDOM_ASOF_RECOMPUTED_FACTOR_SNAPSHOT.csv",
            "outputs/v20/consolidation/V20_108_R9_RISK_CANDIDATE_SCORE_SOURCE.csv",
            "outputs/v20/consolidation/V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_TABLE.csv",
        ],
        "MARKET_REGIME": [
            "outputs/v20/backtest/V20_199B_R1_RANDOM_ASOF_RECOMPUTED_FACTOR_SNAPSHOT.csv",
            "outputs/v20/consolidation/V20_108_R8_MARKET_REGIME_CANDIDATE_EXPOSURE_SOURCE.csv",
            "outputs/v20/consolidation/V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_TABLE.csv",
        ],
        "DATA_TRUST": ["outputs/v20/consolidation/V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_TABLE.csv"],
        "VALUATION": ["outputs/v20/consolidation/V20_108_R9_RISK_CANDIDATE_SCORE_SOURCE.csv"],
        "QUALITY": ["outputs/v20/consolidation/V20_108_R9_RISK_CANDIDATE_SCORE_SOURCE.csv"],
        "GROWTH": [],
        "MOMENTUM": ["outputs/v20/consolidation/V20_108_R7_STRATEGY_CANDIDATE_SCORE_SOURCE.csv"],
        "ENTRY_TIMING": ["outputs/v20/consolidation/V20_108_R7_STRATEGY_CANDIDATE_SCORE_SOURCE.csv"],
        "OTHER": ["outputs/v20/backtest/V20_199B_R1_RANDOM_ASOF_RECOMPUTED_FACTOR_SNAPSHOT.csv"],
    }
    for row in base_rows:
        as_of = row["as_of_date"]
        ticker = row["ticker"]
        family_scores: dict[str, float | None] = {}
        detected_families: list[str] = []
        family_sources: dict[str, str] = {}
        for family in FAMILY_ORDER:
            scores: list[float] = []
            sources: list[str] = []
            for artifact_path in family_priority.get(family, []):
                payload = indexes.get(artifact_path, {}).get((as_of, ticker)) or indexes.get(artifact_path, {}).get((None, ticker))
                if not payload:
                    continue
                family_values: dict[str, list[tuple[str, float]]] = payload["family_values"]  # type: ignore[index]
                values = family_values.get(family, [])
                if values:
                    scores.append(mean(value for _column, value in values))
                    sources.append(artifact_path)
                    break
            family_scores[family] = scores[0] if scores else None
            if scores:
                detected_families.append(family)
                family_sources[family] = sources[0]
        joined.append(
            {
                "as_of_date": as_of,
                "ticker": ticker,
                "rank": row.get("rank", ""),
                "baseline_score": row.get("score", ""),
                "forward_return_5d": row.get("forward_return_5d", ""),
                "forward_return_10d": row.get("forward_return_10d", ""),
                "forward_return_20d": row.get("forward_return_20d", ""),
                "max_drawdown_10d": row.get("max_drawdown_10d", ""),
                "max_gain_10d": row.get("max_gain_10d", ""),
                "benchmark_relative_fields_if_available": "; ".join(
                    f"{benchmark}={row.get(f'excess_return_vs_{benchmark}_10d', '')}"
                    for benchmark in BENCHMARKS
                    if row.get(f"excess_return_vs_{benchmark}_10d", "") != ""
                ),
                "detected_factor_family_columns": "|".join(detected_families),
                "source_artifact": row.get("source_artifact", ""),
                "original_label_fields": row.get("detected_label_fields", ""),
                "raw_status_summary": row.get("raw_status_summary", ""),
                "benchmark_excess_vs_QQQ_10d": row.get("excess_return_vs_QQQ_10d", ""),
                "benchmark_excess_vs_SOXX_10d": row.get("excess_return_vs_SOXX_10d", ""),
                "benchmark_excess_vs_SPY_10d": row.get("excess_return_vs_SPY_10d", ""),
                "family_sources": "|".join(f"{fam}:{src}" for fam, src in family_sources.items()),
                **{f"{family.lower()}_score": ("" if family_scores[family] is None else f"{family_scores[family]:.10f}") for family in FAMILY_ORDER},
            }
        )
    return joined


def add_normalized_family_scores(joined_rows: list[dict[str, object]]) -> None:
    by_date: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in joined_rows:
        as_of = str(row["as_of_date"])
        for family in FAMILY_ORDER:
            raw = parse_float(row.get(f"{family.lower()}_score"))
            if raw is not None:
                by_date[as_of][family].append(raw)
    for row in joined_rows:
        as_of = str(row["as_of_date"])
        for family in FAMILY_ORDER:
            raw = parse_float(row.get(f"{family.lower()}_score"))
            values = by_date[as_of][family]
            if raw is None or len(values) == 0:
                row[f"normalized_{family.lower()}_score"] = ""
            else:
                row[f"normalized_{family.lower()}_score"] = f"{percentile_rank(values, raw):.10f}"
        normalized_values = [parse_float(row.get(f"normalized_{family.lower()}_score")) for family in FAMILY_ORDER if parse_float(row.get(f"normalized_{family.lower()}_score")) is not None]
        row["baseline_detected_score"] = f"{mean(normalized_values):.10f}" if normalized_values else ""


def make_family_indexed_rows(joined_rows: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    out: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in joined_rows:
        out[str(row["as_of_date"])].append(row)
    return out


def compute_single_family_performance(joined_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for family in FAMILY_ORDER:
        score_field = f"normalized_{family.lower()}_score"
        scored_rows = [row for row in joined_rows if parse_float(row.get(score_field)) is not None and parse_float(row.get("forward_return_10d")) is not None]
        scores = [parse_float(row.get(score_field)) for row in scored_rows]
        forward10 = [parse_float(row.get("forward_return_10d")) for row in scored_rows]
        forward5 = [parse_float(row.get("forward_return_5d")) for row in scored_rows]
        forward20 = [parse_float(row.get("forward_return_20d")) for row in scored_rows]
        scores = [v for v in scores if v is not None]
        if len(scores) < 25:
            rows.append(
                {
                    "factor_family": family,
                    "evaluated_row_count": len(scores),
                    "coverage_ratio": f"{len(scores) / max(len(joined_rows), 1):.10f}",
                    "score_forward_return_5d_correlation": "",
                    "score_forward_return_10d_correlation": "",
                    "score_forward_return_20d_correlation": "",
                    "top_quintile_avg_forward_return_10d": "",
                    "bottom_quintile_avg_forward_return_10d": "",
                    "top_minus_bottom_forward_return_10d": "",
                    "top_quintile_hit_rate_10d": "",
                    "bottom_quintile_hit_rate_10d": "",
                    "avg_max_drawdown_10d_top_quintile": "",
                    "diagnosis_flag": "INSUFFICIENT_COVERAGE",
                }
            )
            continue
        sorted_rows = sorted(
            [(parse_float(row.get(score_field)) or 0.0, row) for row in scored_rows],
            key=lambda item: item[0],
        )
        q = max(len(sorted_rows) // 5, 1)
        bottom = [row for _score, row in sorted_rows[:q]]
        top = [row for _score, row in sorted_rows[-q:]]
        corr5 = safe_corr(
            [parse_float(row.get(score_field)) for row in scored_rows if parse_float(row.get("forward_return_5d")) is not None],
            [parse_float(row.get("forward_return_5d")) for row in scored_rows if parse_float(row.get("forward_return_5d")) is not None],
        )
        corr10 = safe_corr(
            [parse_float(row.get(score_field)) for row in scored_rows if parse_float(row.get("forward_return_10d")) is not None],
            [parse_float(row.get("forward_return_10d")) for row in scored_rows if parse_float(row.get("forward_return_10d")) is not None],
        )
        corr20 = safe_corr(
            [parse_float(row.get(score_field)) for row in scored_rows if parse_float(row.get("forward_return_20d")) is not None],
            [parse_float(row.get("forward_return_20d")) for row in scored_rows if parse_float(row.get("forward_return_20d")) is not None],
        )
        top10 = [parse_float(row.get("forward_return_10d")) for row in top if parse_float(row.get("forward_return_10d")) is not None]
        bottom10 = [parse_float(row.get("forward_return_10d")) for row in bottom if parse_float(row.get("forward_return_10d")) is not None]
        top_hit = [1.0 if (parse_float(row.get("forward_return_10d")) or 0.0) > 0 else 0.0 for row in top if parse_float(row.get("forward_return_10d")) is not None]
        bottom_hit = [1.0 if (parse_float(row.get("forward_return_10d")) or 0.0) > 0 else 0.0 for row in bottom if parse_float(row.get("forward_return_10d")) is not None]
        top_dd = [parse_float(row.get("max_drawdown_10d")) for row in top if parse_float(row.get("max_drawdown_10d")) is not None]
        diagnosis = diagnose_single_family(corr10, top10, bottom10, top_hit, bottom_hit, len(scores))
        top_minus_bottom = (mean(top10) - mean(bottom10)) if top10 and bottom10 else None
        rows.append(
            {
                "factor_family": family,
                "evaluated_row_count": len(scores),
                "coverage_ratio": f"{len(scores) / max(len(joined_rows), 1):.10f}",
                "score_forward_return_5d_correlation": corr5,
                "score_forward_return_10d_correlation": corr10,
                "score_forward_return_20d_correlation": corr20,
                "top_quintile_avg_forward_return_10d": safe_mean(top10),
                "bottom_quintile_avg_forward_return_10d": safe_mean(bottom10),
                "top_minus_bottom_forward_return_10d": "" if top_minus_bottom is None else f"{top_minus_bottom:.10f}",
                "top_quintile_hit_rate_10d": f"{mean(top_hit):.10f}" if top_hit else "",
                "bottom_quintile_hit_rate_10d": f"{mean(bottom_hit):.10f}" if bottom_hit else "",
                "avg_max_drawdown_10d_top_quintile": safe_mean(top_dd),
                "diagnosis_flag": diagnosis,
            }
        )
    return rows


def diagnose_single_family(corr10: str, top10: list[float], bottom10: list[float], top_hit: list[float], bottom_hit: list[float], coverage: int) -> str:
    if coverage < 25:
        return "INSUFFICIENT_COVERAGE"
    corr = parse_float(corr10)
    top_minus_bottom = (mean(top10) - mean(bottom10)) if top10 and bottom10 else 0.0
    hit_gap = (mean(top_hit) - mean(bottom_hit)) if top_hit and bottom_hit else 0.0
    if corr is not None and corr > 0.08 and top_minus_bottom > 0 and hit_gap >= 0:
        return "POSITIVE_SIGNAL"
    if corr is not None and corr < -0.08 and top_minus_bottom < 0:
        return "NEGATIVE_SIGNAL"
    if corr is not None and abs(corr) < 0.03 and abs(top_minus_bottom) < 0.01:
        return "WEAK_SIGNAL"
    return "MIXED_SIGNAL"


def compute_experiment_scores(rows: list[dict[str, object]], removed_family: str | None) -> list[tuple[str, str, dict[str, object]]]:
    by_date = make_family_indexed_rows(rows)
    output: list[tuple[str, str, dict[str, object]]] = []
    for as_of, bucket in by_date.items():
        for row in bucket:
            vals = []
            for family in FAMILY_ORDER:
                if family == "OTHER":
                    continue
                if removed_family and family == removed_family:
                    continue
                v = parse_float(row.get(f"normalized_{family.lower()}_score"))
                if v is not None:
                    vals.append(v)
            row["_experiment_score"] = mean(vals) if vals else None
        scored = [row for row in bucket if row.get("_experiment_score") is not None]
        ranked = sorted(scored, key=lambda r: float(r["_experiment_score"]), reverse=True)
        baseline_ranks = {id(row): idx + 1 for idx, row in enumerate(sorted(scored, key=lambda r: parse_float(r.get("baseline_detected_score")) or -1e9, reverse=True))}
        experiment_ranks = {id(row): idx + 1 for idx, row in enumerate(ranked)}
        for row in ranked:
            output.append(
                (
                    as_of,
                    str(row["ticker"]),
                    {
                        "as_of_date": as_of,
                        "ticker": row["ticker"],
                        "baseline_detected_score": row.get("baseline_detected_score", ""),
                        "experiment_score": f"{float(row['_experiment_score']):.10f}" if row.get("_experiment_score") is not None else "",
                        "baseline_rank": baseline_ranks.get(id(row), ""),
                        "experiment_rank": experiment_ranks.get(id(row), ""),
                        "forward_return_5d": row.get("forward_return_5d", ""),
                        "forward_return_10d": row.get("forward_return_10d", ""),
                        "forward_return_20d": row.get("forward_return_20d", ""),
                        "max_drawdown_10d": row.get("max_drawdown_10d", ""),
                        "max_gain_10d": row.get("max_gain_10d", ""),
                        "benchmark_excess_vs_QQQ_10d": row.get("benchmark_excess_vs_QQQ_10d", ""),
                        "benchmark_excess_vs_SOXX_10d": row.get("benchmark_excess_vs_SOXX_10d", ""),
                        "benchmark_excess_vs_SPY_10d": row.get("benchmark_excess_vs_SPY_10d", ""),
                        "removed_family": removed_family or "baseline_detected_score",
                    },
                )
            )
    return output


def evaluate_experiment(rows: list[dict[str, object]], removed_family: str | None) -> dict[str, object]:
    by_date = make_family_indexed_rows(rows)
    selected_top5: list[dict[str, object]] = []
    selected_top10: list[dict[str, object]] = []
    selected_top20: list[dict[str, object]] = []
    ranked_pairs: list[tuple[float, float]] = []
    baseline_pairs: list[tuple[float, float]] = []
    rank_deltas: list[float] = []
    evaluated_dates = 0
    for as_of, bucket in by_date.items():
        for row in bucket:
            vals = []
            for family in FAMILY_ORDER:
                if family == "OTHER":
                    continue
                if removed_family and family == removed_family:
                    continue
                v = parse_float(row.get(f"normalized_{family.lower()}_score"))
                if v is not None:
                    vals.append(v)
            row["_experiment_score"] = mean(vals) if vals else None
            row["_baseline_score_numeric"] = parse_float(row.get("baseline_detected_score"))
        scored = [row for row in bucket if row.get("_experiment_score") is not None and row.get("_baseline_score_numeric") is not None]
        if not scored:
            continue
        evaluated_dates += 1
        baseline_ranked = sorted(scored, key=lambda r: float(r["_baseline_score_numeric"]), reverse=True)
        experiment_ranked = sorted(scored, key=lambda r: float(r["_experiment_score"]), reverse=True)
        baseline_rank_lookup = {id(row): idx + 1 for idx, row in enumerate(baseline_ranked)}
        experiment_rank_lookup = {id(row): idx + 1 for idx, row in enumerate(experiment_ranked)}
        for row in scored:
            rank_deltas.append(abs(experiment_rank_lookup[id(row)] - baseline_rank_lookup[id(row)]))
            ranked_pairs.append((baseline_rank_lookup[id(row)], experiment_rank_lookup[id(row)]))
            baseline_pairs.append((float(row["_baseline_score_numeric"]), float(row["_experiment_score"])))
        selected_top5.extend(experiment_ranked[:5])
        selected_top10.extend(experiment_ranked[:10])
        selected_top20.extend(experiment_ranked[:20])
    if not selected_top10:
        return {
            "experiment_name": f"remove_{removed_family or 'baseline_detected_score'}",
            "removed_family": removed_family or "baseline_detected_score",
            "evaluated_as_of_date_count": 0,
            "evaluated_row_count": 0,
            "top5_avg_forward_return_10d": "",
            "top10_avg_forward_return_10d": "",
            "top20_avg_forward_return_10d": "",
            "top10_hit_rate_10d": "",
            "top10_avg_excess_return_vs_QQQ_10d": "",
            "top10_avg_excess_return_vs_SOXX_10d": "",
            "top10_avg_excess_return_vs_SPY_10d": "",
            "top10_avg_max_drawdown_10d": "",
            "rank_correlation_vs_baseline": "",
            "avg_rank_delta_vs_baseline": "",
            "diagnosis_flag": "INSUFFICIENT_EVIDENCE",
        }
    top5_returns = [v for v in (parse_float(row.get("forward_return_10d")) for row in selected_top5) if v is not None]
    top10_returns = [v for v in (parse_float(row.get("forward_return_10d")) for row in selected_top10) if v is not None]
    top20_returns = [v for v in (parse_float(row.get("forward_return_10d")) for row in selected_top20) if v is not None]
    top10_hit = [1.0 if value > 0 else 0.0 for value in top10_returns]
    top10_dd = [v for v in (parse_float(row.get("max_drawdown_10d")) for row in selected_top10) if v is not None]
    qqq_excess = [v for v in (parse_float(row.get("benchmark_excess_vs_QQQ_10d")) for row in selected_top10) if v is not None]
    soxx_excess = [v for v in (parse_float(row.get("benchmark_excess_vs_SOXX_10d")) for row in selected_top10) if v is not None]
    spy_excess = [v for v in (parse_float(row.get("benchmark_excess_vs_SPY_10d")) for row in selected_top10) if v is not None]
    baseline_ranks = [pair[0] for pair in ranked_pairs]
    experiment_ranks = [pair[1] for pair in ranked_pairs]
    return {
        "experiment_name": f"remove_{removed_family or 'baseline_detected_score'}",
        "removed_family": removed_family or "baseline_detected_score",
        "evaluated_as_of_date_count": evaluated_dates,
        "evaluated_row_count": len(baseline_ranks),
        "top5_avg_forward_return_10d": safe_mean(top5_returns),
        "top10_avg_forward_return_10d": safe_mean(top10_returns),
        "top20_avg_forward_return_10d": safe_mean(top20_returns),
        "top10_hit_rate_10d": f"{mean(top10_hit):.10f}" if top10_hit else "",
        "top10_avg_excess_return_vs_QQQ_10d": safe_mean(qqq_excess),
        "top10_avg_excess_return_vs_SOXX_10d": safe_mean(soxx_excess),
        "top10_avg_excess_return_vs_SPY_10d": safe_mean(spy_excess),
        "top10_avg_max_drawdown_10d": safe_mean(top10_dd),
        "rank_correlation_vs_baseline": safe_spearman(baseline_ranks, experiment_ranks),
        "avg_rank_delta_vs_baseline": f"{mean(rank_deltas):.10f}" if rank_deltas else "",
        "diagnosis_flag": diagnose_experiment(top10_returns, top10_hit, qqq_excess, soxx_excess, spy_excess),
    }


def diagnose_experiment(top10_returns: list[float], top10_hit: list[float], qqq_excess: list[float], soxx_excess: list[float], spy_excess: list[float]) -> str:
    if not top10_returns:
        return "INSUFFICIENT_EVIDENCE"
    avg_ret = mean(top10_returns)
    hit_rate = mean(top10_hit) if top10_hit else 0.0
    avg_excess = mean([v for v in qqq_excess + soxx_excess + spy_excess if v is not None]) if any(v is not None for v in qqq_excess + soxx_excess + spy_excess) else 0.0
    if avg_ret > 0 and hit_rate >= 0.5 and avg_excess >= 0:
        return "REMOVAL_HURTS_PERFORMANCE"
    if avg_ret < 0 and avg_excess < 0:
        return "REMOVAL_IMPROVES_PERFORMANCE"
    if avg_ret > 0 and avg_excess < 0:
        return "REMOVAL_IMPROVES_RETURN_BUT_INCREASES_DRAWDOWN"
    if abs(avg_ret) < 0.005 and abs(avg_excess) < 0.005:
        return "REMOVAL_NEUTRAL"
    return "INSUFFICIENT_EVIDENCE"


def compute_factor_removal_impact(baseline: dict[str, object], experiments: list[dict[str, object]]) -> list[dict[str, object]]:
    baseline_by_family = {row["removed_family"]: row for row in experiments if row["removed_family"] == "baseline_detected_score"}
    base = baseline_by_family.get("baseline_detected_score")
    out: list[dict[str, object]] = []
    if not base:
        return out
    for row in experiments:
        if row["removed_family"] == "baseline_detected_score":
            continue
        out.append(
            {
                "removed_family": row["removed_family"],
                "top10_return_delta_vs_baseline_10d": delta(row["top10_avg_forward_return_10d"], base["top10_avg_forward_return_10d"]),
                "top20_return_delta_vs_baseline_10d": delta(row["top20_avg_forward_return_10d"], base["top20_avg_forward_return_10d"]),
                "hit_rate_delta_vs_baseline_10d": delta(row["top10_hit_rate_10d"], base["top10_hit_rate_10d"]),
                "drawdown_delta_vs_baseline_10d": delta(row["top10_avg_max_drawdown_10d"], base["top10_avg_max_drawdown_10d"]),
                "benchmark_excess_delta_vs_baseline_10d": delta(
                    safe_mean([row["top10_avg_excess_return_vs_QQQ_10d"], row["top10_avg_excess_return_vs_SOXX_10d"], row["top10_avg_excess_return_vs_SPY_10d"]]),
                    safe_mean([base["top10_avg_excess_return_vs_QQQ_10d"], base["top10_avg_excess_return_vs_SOXX_10d"], base["top10_avg_excess_return_vs_SPY_10d"]]),
                ),
                "rank_stability_cost": abs(parse_float(row.get("avg_rank_delta_vs_baseline")) or 0.0),
                "impact_diagnosis": diagnose_impact(row, base),
            }
        )
    return out


def delta(value: object, baseline: object) -> str:
    v = parse_float(value)
    b = parse_float(baseline)
    if v is None or b is None:
        return ""
    return f"{(v - b):.10f}"


def diagnose_impact(row: dict[str, object], base: dict[str, object]) -> str:
    top10_delta = parse_float(row.get("top10_avg_forward_return_10d"))
    base_top10 = parse_float(base.get("top10_avg_forward_return_10d"))
    hit_delta = parse_float(row.get("top10_hit_rate_10d"))
    base_hit = parse_float(base.get("top10_hit_rate_10d"))
    dd_delta = parse_float(row.get("top10_avg_max_drawdown_10d"))
    base_dd = parse_float(base.get("top10_avg_max_drawdown_10d"))
    if None in {top10_delta, base_top10, hit_delta, base_hit, dd_delta, base_dd}:
        return "INSUFFICIENT_EVIDENCE"
    if top10_delta > base_top10 and (hit_delta or 0) >= (base_hit or 0):
        return "REMOVAL_IMPROVES_PERFORMANCE"
    if top10_delta < base_top10 and (hit_delta or 0) <= (base_hit or 0):
        return "REMOVAL_HURTS_PERFORMANCE"
    if top10_delta > base_top10 and dd_delta > base_dd:
        return "REMOVAL_IMPROVES_RETURN_BUT_INCREASES_DRAWDOWN"
    if abs(top10_delta - base_top10) < 0.003 and abs((hit_delta or 0) - (base_hit or 0)) < 0.03:
        return "REMOVAL_NEUTRAL"
    return "INSUFFICIENT_EVIDENCE"


def candidate_tables(single_family: list[dict[str, object]], impacts: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    negative: list[dict[str, object]] = []
    positive: list[dict[str, object]] = []
    impact_by_family = {row["removed_family"]: row for row in impacts}
    family_by_name = {row["factor_family"]: row for row in single_family}
    for family, row in family_by_name.items():
        coverage = parse_float(row.get("coverage_ratio")) or 0.0
        corr = parse_float(row.get("score_forward_return_10d_correlation"))
        top_minus_bottom = parse_float(row.get("top_minus_bottom_forward_return_10d"))
        impact = impact_by_family.get(family, {})
        top10_delta = parse_float(impact.get("top10_return_delta_vs_baseline_10d"))
        hit_delta = parse_float(impact.get("hit_rate_delta_vs_baseline_10d"))
        dd_delta = parse_float(impact.get("drawdown_delta_vs_baseline_10d"))
        if coverage < 0.10 or row.get("diagnosis_flag") == "INSUFFICIENT_COVERAGE":
            continue
        if corr is not None and (corr < -0.05 or (top_minus_bottom is not None and top_minus_bottom < 0)) and (top10_delta is not None and top10_delta > 0):
            negative.append(
                {
                    "factor_family": family,
                    "evidence_type": "NEGATIVE_CORRELATION_AND_REMOVAL_IMPROVES_RETURN",
                    "evidence_metric": "score_forward_return_10d_correlation",
                    "metric_value": f"{corr:.10f}",
                    "coverage_ratio": f"{coverage:.10f}",
                    "impact_summary": f"leave-one-out top10 return delta={top10_delta:.10f}; hit_delta={hit_delta if hit_delta is not None else ''}; drawdown_delta={dd_delta if dd_delta is not None else ''}",
                    "candidate_action": "REVIEW_FOR_DOWNWEIGHT" if family not in {"DATA_TRUST", "RISK"} else "REVIEW_FOR_GATE_MODE",
                }
            )
        elif corr is not None and (corr > 0.05 or (top_minus_bottom is not None and top_minus_bottom > 0)) and (top10_delta is not None and top10_delta < 0):
            positive.append(
                {
                    "factor_family": family,
                    "evidence_type": "POSITIVE_CORRELATION_AND_REMOVAL_HURTS_RETURN",
                    "evidence_metric": "score_forward_return_10d_correlation",
                    "metric_value": f"{corr:.10f}",
                    "coverage_ratio": f"{coverage:.10f}",
                    "impact_summary": f"leave-one-out top10 return delta={top10_delta:.10f}; hit_delta={hit_delta if hit_delta is not None else ''}; drawdown_delta={dd_delta if dd_delta is not None else ''}",
                    "candidate_action": "REVIEW_FOR_RETAIN" if family in {"FUNDAMENTAL", "TECHNICAL", "STRATEGY"} else "REVIEW_FOR_ENTRY_MODEL_USE",
                }
            )
    return negative, positive


def ranking_weakness_diagnosis(single_family: list[dict[str, object]], impacts: list[dict[str, object]], negative: list[dict[str, object]], positive: list[dict[str, object]], baseline_row: dict[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    family_map = {row["factor_family"]: row for row in single_family}
    neg_families = {row["factor_family"] for row in negative}
    pos_families = {row["factor_family"] for row in positive}
    # factor family noise
    weak_count = sum(1 for row in single_family if row.get("diagnosis_flag") in {"NEGATIVE_SIGNAL", "WEAK_SIGNAL", "MIXED_SIGNAL"})
    rows.append(
        {
            "diagnosis_area": "FACTOR_FAMILY_NOISE",
            "evidence_summary": f"{weak_count} of {len(single_family)} families show weak/mixed/negative signal under normalized family scores.",
            "severity": severity_from_ratio(weak_count / max(len(single_family), 1)),
            "recommended_next_stage": "V21.003_WEIGHT_REPAIR_PLAN",
        }
    )
    # negative contributor
    if negative:
        rows.append(
            {
                "diagnosis_area": "NEGATIVE_FACTOR_CONTRIBUTION",
                "evidence_summary": f"Negative contributor candidates detected for {', '.join(sorted(neg_families))}.",
                "severity": "HIGH" if len(negative) >= 2 else "MEDIUM",
                "recommended_next_stage": "V21.003_WEIGHT_REPAIR_PLAN",
            }
        )
    # data trust
    if "DATA_TRUST" in family_map:
        rows.append(
            {
                "diagnosis_area": "DATA_TRUST_RANKING_CONTAMINATION",
                "evidence_summary": f"DATA_TRUST diagnosis_flag={family_map['DATA_TRUST'].get('diagnosis_flag', '')}; coverage={family_map['DATA_TRUST'].get('coverage_ratio', '')}.",
                "severity": "HIGH" if family_map["DATA_TRUST"].get("diagnosis_flag") == "NEGATIVE_SIGNAL" else "LOW",
                "recommended_next_stage": "V21.003_DATA_TRUST_GATE_MODE_REPAIR",
            }
        )
    # risk / regime
    for area, family, next_stage in [
        ("RISK_FACTOR_OVERPENALIZATION", "RISK", "V21.003_RISK_REGIME_RECALIBRATION_PLAN"),
        ("REGIME_FACTOR_MISALIGNMENT", "MARKET_REGIME", "V21.003_RISK_REGIME_RECALIBRATION_PLAN"),
        ("TECHNICAL_SIGNAL_WEAKNESS", "TECHNICAL", "V21.003_WEIGHT_REPAIR_PLAN"),
        ("FUNDAMENTAL_SIGNAL_WEAKNESS", "FUNDAMENTAL", "V21.003_WEIGHT_REPAIR_PLAN"),
        ("ENTRY_TIMING_NOT_SEPARATED_FROM_RANKING", "ENTRY_TIMING", "V21.003_ENTRY_TIMING_SEPARATION_PLAN"),
        ("BENCHMARK_RELATIVE_WEAKNESS", "OTHER", "V21.003_WEIGHT_REPAIR_PLAN"),
        ("INSUFFICIENT_FACTOR_COVERAGE", "OTHER", "V21.003_FACTOR_SOURCE_COVERAGE_REPAIR"),
    ]:
        if family == "OTHER":
            if parse_float(baseline_row.get("benchmark_excess_vs_QQQ_10d")) is not None and mean([
                parse_float(baseline_row.get("benchmark_excess_vs_QQQ_10d")) or 0.0,
                parse_float(baseline_row.get("benchmark_excess_vs_SOXX_10d")) or 0.0,
                parse_float(baseline_row.get("benchmark_excess_vs_SPY_10d")) or 0.0,
            ]) < 0:
                rows.append(
                    {
                        "diagnosis_area": area,
                        "evidence_summary": "Baseline top10 excess returns versus QQQ/SOXX/SPY are negative on average.",
                        "severity": "HIGH",
                        "recommended_next_stage": next_stage,
                    }
                )
            continue
        family_row = family_map.get(family)
        if not family_row:
            continue
        flag = family_row.get("diagnosis_flag", "")
        severity = "HIGH" if flag == "NEGATIVE_SIGNAL" else "MEDIUM" if flag == "MIXED_SIGNAL" else "LOW"
        evidence = f"{family} diagnosis_flag={flag}; top_minus_bottom_10d={family_row.get('top_minus_bottom_forward_return_10d', '')}; impact={impact_summary_for_family(family, impacts)}"
        rows.append({"diagnosis_area": area, "evidence_summary": evidence, "severity": severity, "recommended_next_stage": next_stage})
    return rows


def impact_summary_for_family(family: str, impacts: list[dict[str, object]]) -> str:
    row = next((item for item in impacts if item["removed_family"] == family), None)
    if not row:
        return ""
    return f"top10_delta={row.get('top10_return_delta_vs_baseline_10d', '')}; hit_delta={row.get('hit_rate_delta_vs_baseline_10d', '')}; dd_delta={row.get('drawdown_delta_vs_baseline_10d', '')}"


def severity_from_ratio(ratio: float) -> str:
    if ratio >= 0.66:
        return "HIGH"
    if ratio >= 0.33:
        return "MEDIUM"
    return "LOW"


def build_report(gate: dict[str, object], discovery: list[dict[str, object]], field_map_rows: list[dict[str, object]], joined_rows: list[dict[str, object]], single_family: list[dict[str, object]], leave_one_out: list[dict[str, object]], impacts: list[dict[str, object]], positive: list[dict[str, object]], negative: list[dict[str, object]], diagnosis_rows: list[dict[str, object]]) -> None:
    lines = [
        "# V21.002 Factor Ablation Audit",
        "",
        "## Final status",
        f"final_status: {gate['final_status']}",
        f"joined_factor_outcome_rows: {gate['joined_factor_outcome_rows']}",
        f"evaluated_factor_family_count: {gate['evaluated_factor_family_count']}",
        "",
        "## Input discovery",
        f"Discovered {len(discovery)} V20 score/factor artifacts suitable for ablation.",
        "",
        "## Factor field map",
        f"Mapped {len(field_map_rows)} source columns to factor families.",
        "",
        "## Joined factor-outcome coverage",
        f"Joined rows: {len(joined_rows)}; baseline rows are V21.001 forward-outcome rows enriched with V20 factor columns.",
        "",
        "## Single factor-family performance",
        table(single_family, ["factor_family", "evaluated_row_count", "coverage_ratio", "score_forward_return_10d_correlation", "top_minus_bottom_forward_return_10d", "diagnosis_flag"]),
        "",
        "## Leave-one-family-out performance",
        table(leave_one_out, ["experiment_name", "removed_family", "evaluated_row_count", "top10_avg_forward_return_10d", "top10_hit_rate_10d", "rank_correlation_vs_baseline", "avg_rank_delta_vs_baseline", "diagnosis_flag"]),
        "",
        "## Factor removal impact",
        table(impacts, ["removed_family", "top10_return_delta_vs_baseline_10d", "hit_rate_delta_vs_baseline_10d", "drawdown_delta_vs_baseline_10d", "benchmark_excess_delta_vs_baseline_10d", "impact_diagnosis"]),
        "",
        "## Positive contributor candidates",
        table(positive, ["factor_family", "evidence_type", "evidence_metric", "metric_value", "coverage_ratio", "impact_summary", "candidate_action"]),
        "",
        "## Negative contributor candidates",
        table(negative, ["factor_family", "evidence_type", "evidence_metric", "metric_value", "coverage_ratio", "impact_summary", "candidate_action"]),
        "",
        "## Ranking weakness diagnosis",
        table(diagnosis_rows, ["diagnosis_area", "evidence_summary", "severity", "recommended_next_stage"]),
        "",
        "## Next recommended action",
        str(gate["next_recommended_action"]),
        "",
        "## Safety confirmation",
        "This is an audit-only stage and does not change official weights, recommendations, trade signals, broker execution, or real-book behavior.",
    ]
    for field in MANDATORY_FALSE_FIELDS:
        lines.append(f"- {field}: {gate[field]}")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def table(rows: list[dict[str, object]], fields: list[str]) -> str:
    if not rows:
        return "No rows available."
    lines = ["| " + " | ".join(fields) + " |", "| " + " | ".join(["---"] * len(fields)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(field, "")) for field in fields) + " |")
    return "\n".join(lines)


def next_action(final_status: str, diagnosis_rows: list[dict[str, object]]) -> str:
    if final_status == "FAIL_V21_002_REQUIRED_V21_001_INPUTS_MISSING":
        return "Repair the missing V21.001 audit inputs before continuing."
    if final_status == "FAIL_V21_002_NO_FACTOR_FIELDS_DETECTED":
        return "Repair factor source discovery before any ablation interpretation."
    if any(row["diagnosis_area"] == "DATA_TRUST_RANKING_CONTAMINATION" and row["severity"] == "HIGH" for row in diagnosis_rows):
        return "Proceed to V21.003_DATA_TRUST_GATE_MODE_REPAIR."
    if any(row["diagnosis_area"] == "RISK_FACTOR_OVERPENALIZATION" and row["severity"] in {"HIGH", "MEDIUM"} for row in diagnosis_rows):
        return "Proceed to V21.003_RISK_REGIME_RECALIBRATION_PLAN."
    if any(row["diagnosis_area"] == "ENTRY_TIMING_NOT_SEPARATED_FROM_RANKING" and row["severity"] in {"HIGH", "MEDIUM"} for row in diagnosis_rows):
        return "Proceed to V21.003_ENTRY_TIMING_SEPARATION_PLAN."
    if any(row["diagnosis_area"] == "INSUFFICIENT_FACTOR_COVERAGE" and row["severity"] in {"HIGH", "MEDIUM"} for row in diagnosis_rows):
        return "Proceed to V21.003_FACTOR_SOURCE_COVERAGE_REPAIR."
    if any(row["diagnosis_area"] == "NEGATIVE_FACTOR_CONTRIBUTION" for row in diagnosis_rows):
        return "Proceed to V21.003_WEIGHT_REPAIR_PLAN."
    return "Proceed to V21.003_WEIGHT_REPAIR_PLAN."


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)

    # V21.001 inputs
    try:
        base_snapshot, joined_base, v21_gate = load_v21_base()
    except FileNotFoundError:
        gate = {
            "stage_name": STAGE_NAME,
            "final_status": "FAIL_V21_002_REQUIRED_V21_001_INPUTS_MISSING",
            "joined_factor_outcome_rows": 0,
            "evaluated_factor_family_count": 0,
            "negative_contributor_count": 0,
            "positive_contributor_count": 0,
            "factor_coverage_status": "MISSING_V21_001_INPUTS",
            "ablation_evidence_status": "INSUFFICIENT_EVIDENCE",
            "strategy_diagnosis": "required V21.001 inputs are missing.",
            "next_recommended_action": "Repair the missing V21.001 audit inputs before continuing.",
        }
        gate.update({field: "FALSE" for field in MANDATORY_FALSE_FIELDS})
        write_csv(GATE, [gate], ["stage_name", "final_status", "joined_factor_outcome_rows", "evaluated_factor_family_count", "negative_contributor_count", "positive_contributor_count", "factor_coverage_status", "ablation_evidence_status", "strategy_diagnosis", "next_recommended_action"] + MANDATORY_FALSE_FIELDS)
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text("# V21.002 Factor Ablation Audit\n\n## Final status\nMissing required V21.001 inputs.\n", encoding="utf-8")
        print(f"STAGE_NAME={STAGE_NAME}")
        print(f"final_status={gate['final_status']}")
        print("joined_factor_outcome_rows=0")
        print("evaluated_factor_family_count=0")
        print("negative_contributor_count=0")
        print("positive_contributor_count=0")
        print(f"next_recommended_action={gate['next_recommended_action']}")
        return 0

    discovery, indexes, field_map = build_discovery_and_indexes()
    field_map_rows: list[dict[str, object]] = []
    for artifact in discovery:
        artifact_path = str(artifact["artifact_path"])
        source_rows = read_csv(ROOT / artifact_path)
        columns = read_header(ROOT / artifact_path)
        ticker_col = detect_ticker_field(columns)
        date_col = detect_date_field(columns)
        mapped_cols = field_map.get(artifact_path, [])
        non_null = {col: 0 for col, *_rest in mapped_cols}
        total_rows = len(source_rows)
        for row in source_rows:
            for col, family, confidence, reason in mapped_cols:
                if parse_float(row.get(col)) is not None:
                    non_null[col] += 1
        for col, family, confidence, reason in mapped_cols:
            field_map_rows.append(
                {
                    "source_artifact": artifact_path,
                    "column_name": col,
                    "mapped_factor_family": family,
                    "mapping_confidence": confidence,
                    "mapping_reason": reason,
                    "non_null_count": non_null[col],
                    "coverage_ratio": f"{(non_null[col] / max(total_rows, 1)):.10f}",
                    "selected_for_ablation": "TRUE" if family != "OTHER" or "score" in norm(col) else "FALSE",
                }
            )

    if not field_map_rows:
        gate = {
            "stage_name": STAGE_NAME,
            "final_status": "FAIL_V21_002_NO_FACTOR_FIELDS_DETECTED",
            "joined_factor_outcome_rows": len(joined_base),
            "evaluated_factor_family_count": 0,
            "negative_contributor_count": 0,
            "positive_contributor_count": 0,
            "factor_coverage_status": "NO_FACTOR_FIELDS_DETECTED",
            "ablation_evidence_status": "INSUFFICIENT_EVIDENCE",
            "strategy_diagnosis": "outcome rows exist but no usable factor or score columns were discovered.",
            "next_recommended_action": "Repair factor source discovery before any ablation interpretation.",
        }
        gate.update({field: "FALSE" for field in MANDATORY_FALSE_FIELDS})
        write_csv(GATE, [gate], ["stage_name", "final_status", "joined_factor_outcome_rows", "evaluated_factor_family_count", "negative_contributor_count", "positive_contributor_count", "factor_coverage_status", "ablation_evidence_status", "strategy_diagnosis", "next_recommended_action"] + MANDATORY_FALSE_FIELDS)
        REPORT.write_text("# V21.002 Factor Ablation Audit\n\n## Final status\nNo factor fields detected.\n", encoding="utf-8")
        print(f"STAGE_NAME={STAGE_NAME}")
        print(f"final_status={gate['final_status']}")
        print(f"joined_factor_outcome_rows={len(joined_base)}")
        print("evaluated_factor_family_count=0")
        print("negative_contributor_count=0")
        print("positive_contributor_count=0")
        print(f"next_recommended_action={gate['next_recommended_action']}")
        return 0

    joined_rows = build_joined_rows(joined_base, indexes)
    add_normalized_family_scores(joined_rows)

    # Add row-level benchmark fields and normalized family fields to the joined audit output.
    for row in joined_rows:
        for family in FAMILY_ORDER:
            row.setdefault(f"{family.lower()}_score", "")
            row.setdefault(f"normalized_{family.lower()}_score", "")
        row["detected_factor_family_columns"] = row.get("detected_factor_family_columns", "")

    single_family = compute_single_family_performance(joined_rows)
    baseline_experiment = evaluate_experiment(joined_rows, None)
    leave_one_rows = [baseline_experiment] + [evaluate_experiment(joined_rows, family) for family in FAMILY_ORDER if family != "OTHER"]
    impacts = compute_factor_removal_impact(baseline_experiment, leave_one_rows)
    positive, negative = candidate_tables(single_family, impacts)
    diagnosis_rows = ranking_weakness_diagnosis(single_family, impacts, negative, positive, baseline_experiment)

    joined_factor_outcome_rows = len(joined_rows)
    evaluated_factor_family_count = sum(1 for row in single_family if row.get("diagnosis_flag") != "INSUFFICIENT_COVERAGE")
    factor_coverage_status = "PASS_FACTOR_COVERAGE" if evaluated_factor_family_count >= 3 else "PARTIAL_FACTOR_COVERAGE"
    ablation_evidence_status = "PASS_ABLATION_EVIDENCE" if joined_factor_outcome_rows >= 500 else "LIMITED_ABLATION_EVIDENCE"
    if joined_factor_outcome_rows < 500:
        final_status = "PARTIAL_PASS_V21_002_ABLATION_EVIDENCE_LIMITED"
    elif evaluated_factor_family_count < 3:
        final_status = "PARTIAL_PASS_V21_002_LIMITED_FACTOR_COVERAGE"
    elif not positive and not negative:
        final_status = "PARTIAL_PASS_V21_002_ABLATION_EVIDENCE_LIMITED"
    else:
        final_status = "PASS_V21_002_FACTOR_ABLATION_READY_FOR_WEIGHT_REPAIR_PLAN"

    strategy_diagnosis = build_strategy_diagnosis(single_family, impacts, positive, negative, baseline_experiment)
    next_recommended_action = next_action(final_status, diagnosis_rows)
    gate = {
        "stage_name": STAGE_NAME,
        "final_status": final_status,
        "joined_factor_outcome_rows": joined_factor_outcome_rows,
        "evaluated_factor_family_count": evaluated_factor_family_count,
        "negative_contributor_count": len(negative),
        "positive_contributor_count": len(positive),
        "factor_coverage_status": factor_coverage_status,
        "ablation_evidence_status": ablation_evidence_status,
        "strategy_diagnosis": strategy_diagnosis,
        "next_recommended_action": next_recommended_action,
    }
    gate.update({field: "FALSE" for field in MANDATORY_FALSE_FIELDS})

    # output files
    write_csv(INPUT_DISCOVERY, discovery, ["artifact_path", "artifact_type", "exists_non_empty", "row_count", "detected_columns", "selected_for_audit", "selection_reason", "validation_status"])
    write_csv(FIELD_MAP, field_map_rows, ["source_artifact", "column_name", "mapped_factor_family", "mapping_confidence", "mapping_reason", "non_null_count", "coverage_ratio", "selected_for_ablation"])
    write_csv(
        JOINED_ROWS,
        joined_rows,
        [
            "as_of_date",
            "ticker",
            "rank",
            "baseline_score",
            "forward_return_5d",
            "forward_return_10d",
            "forward_return_20d",
            "max_drawdown_10d",
            "max_gain_10d",
            "benchmark_relative_fields_if_available",
            "detected_factor_family_columns",
            "source_artifact",
            "original_label_fields",
            "raw_status_summary",
            "benchmark_excess_vs_QQQ_10d",
            "benchmark_excess_vs_SOXX_10d",
            "benchmark_excess_vs_SPY_10d",
            "family_sources",
        ]
        + [f"{family.lower()}_score" for family in FAMILY_ORDER]
        + [f"normalized_{family.lower()}_score" for family in FAMILY_ORDER]
        + ["baseline_detected_score"],
    )
    write_csv(SINGLE_FAMILY, single_family, [
        "factor_family",
        "evaluated_row_count",
        "coverage_ratio",
        "score_forward_return_5d_correlation",
        "score_forward_return_10d_correlation",
        "score_forward_return_20d_correlation",
        "top_quintile_avg_forward_return_10d",
        "bottom_quintile_avg_forward_return_10d",
        "top_minus_bottom_forward_return_10d",
        "top_quintile_hit_rate_10d",
        "bottom_quintile_hit_rate_10d",
        "avg_max_drawdown_10d_top_quintile",
        "diagnosis_flag",
    ])
    write_csv(LEAVE_ONE_OUT, leave_one_rows, [
        "experiment_name",
        "removed_family",
        "evaluated_as_of_date_count",
        "evaluated_row_count",
        "top5_avg_forward_return_10d",
        "top10_avg_forward_return_10d",
        "top20_avg_forward_return_10d",
        "top10_hit_rate_10d",
        "top10_avg_excess_return_vs_QQQ_10d",
        "top10_avg_excess_return_vs_SOXX_10d",
        "top10_avg_excess_return_vs_SPY_10d",
        "top10_avg_max_drawdown_10d",
        "rank_correlation_vs_baseline",
        "avg_rank_delta_vs_baseline",
        "diagnosis_flag",
    ])
    write_csv(REMOVAL_IMPACT, impacts, [
        "removed_family",
        "top10_return_delta_vs_baseline_10d",
        "top20_return_delta_vs_baseline_10d",
        "hit_rate_delta_vs_baseline_10d",
        "drawdown_delta_vs_baseline_10d",
        "benchmark_excess_delta_vs_baseline_10d",
        "rank_stability_cost",
        "impact_diagnosis",
    ])
    write_csv(POSITIVE_CANDIDATES, positive, ["factor_family", "evidence_type", "evidence_metric", "metric_value", "coverage_ratio", "impact_summary", "candidate_action"])
    write_csv(NEGATIVE_CANDIDATES, negative, ["factor_family", "evidence_type", "evidence_metric", "metric_value", "coverage_ratio", "impact_summary", "candidate_action"])
    write_csv(DIAGNOSIS, diagnosis_rows, ["diagnosis_area", "evidence_summary", "severity", "recommended_next_stage"])
    write_csv(
        GATE,
        [gate],
        [
            "stage_name",
            "final_status",
            "joined_factor_outcome_rows",
            "evaluated_factor_family_count",
            "negative_contributor_count",
            "positive_contributor_count",
            "factor_coverage_status",
            "ablation_evidence_status",
            "strategy_diagnosis",
            "next_recommended_action",
        ]
        + MANDATORY_FALSE_FIELDS,
    )
    build_report(gate, discovery, field_map_rows, joined_rows, single_family, leave_one_rows, impacts, positive, negative, diagnosis_rows)

    print(f"STAGE_NAME={STAGE_NAME}")
    print(f"final_status={final_status}")
    print(f"joined_factor_outcome_rows={joined_factor_outcome_rows}")
    print(f"evaluated_factor_family_count={evaluated_factor_family_count}")
    print(f"negative_contributor_count={len(negative)}")
    print(f"positive_contributor_count={len(positive)}")
    print(f"next_recommended_action={next_recommended_action}")
    return 0 if final_status in ALLOWED_FINAL_STATUSES else 1


def build_strategy_diagnosis(single_family: list[dict[str, object]], impacts: list[dict[str, object]], positive: list[dict[str, object]], negative: list[dict[str, object]], baseline_row: dict[str, object]) -> str:
    problems: list[str] = []
    fam = {row["factor_family"]: row for row in single_family}
    if any(row["diagnosis_flag"] == "NEGATIVE_SIGNAL" for row in single_family):
        problems.append("ranking model weakness")
    if any(row["factor_family"] == "ENTRY_TIMING" and row["diagnosis_flag"] in {"NEGATIVE_SIGNAL", "MIXED_SIGNAL"} for row in single_family):
        problems.append("entry timing weakness")
    if any(row["factor_family"] == "RISK" and row["diagnosis_flag"] in {"NEGATIVE_SIGNAL", "MIXED_SIGNAL"} for row in single_family):
        problems.append("risk factor over-penalization")
    if any(row["factor_family"] == "MARKET_REGIME" and row["diagnosis_flag"] in {"NEGATIVE_SIGNAL", "MIXED_SIGNAL"} for row in single_family):
        problems.append("regime factor misalignment")
    if any(row["factor_family"] == "TECHNICAL" and row["diagnosis_flag"] in {"NEGATIVE_SIGNAL", "MIXED_SIGNAL"} for row in single_family):
        problems.append("technical signal weakness")
    if any(row["factor_family"] == "FUNDAMENTAL" and row["diagnosis_flag"] in {"NEGATIVE_SIGNAL", "MIXED_SIGNAL"} for row in single_family):
        problems.append("fundamental signal weakness")
    if any(parse_float(row.get("benchmark_excess_vs_QQQ_10d")) is not None and parse_float(row.get("benchmark_excess_vs_QQQ_10d")) < 0 for row in [baseline_row]):
        problems.append("benchmark-relative weakness")
    if len([row for row in single_family if row["diagnosis_flag"] != "INSUFFICIENT_COVERAGE"]) < 3:
        problems.append("insufficient factor coverage")
    if not problems:
        problems.append("no decisive weakness proven by available evidence")
    return "; ".join(dict.fromkeys(problems)) + "."


if __name__ == "__main__":
    raise SystemExit(main())
