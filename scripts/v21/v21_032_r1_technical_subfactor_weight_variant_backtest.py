#!/usr/bin/env python
"""V21.032-R1 technical subfactor weight variant backtest.

Research-only shadow audit for technical subfactor influence and reweighting
variants. This stage writes V21.032-R1 scoped artifacts only and never mutates
official rankings, weights, recommendations, broker actions, or book state.
"""

from __future__ import annotations

import csv
import math
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median


STAGE = "V21.032-R1_TECHNICAL_SUBFACTOR_WEIGHT_VARIANT_BACKTEST"
STAGE_FILE = "V21_032_R1"
PASS_STATUS = "PASS_V21_032_R1_TECHNICAL_VARIANT_BACKTEST_READY_SHADOW_ONLY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_032_R1_TECHNICAL_VARIANT_BACKTEST_DIAGNOSTIC_ONLY"
DECISION = "TECHNICAL_SUBFACTOR_REWEIGHTING_RESEARCH_READY_SHADOW_ONLY_OFFICIAL_UPDATE_BLOCKED"
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

SUMMARY_OUT = OUT_DIR / f"{STAGE_FILE}_TECHNICAL_VARIANT_BACKTEST_SUMMARY.csv"
INFLUENCE_OUT = OUT_DIR / f"{STAGE_FILE}_TECHNICAL_SUBFACTOR_INFLUENCE_AUDIT.csv"
DEFINITIONS_OUT = OUT_DIR / f"{STAGE_FILE}_TECHNICAL_WEIGHT_VARIANT_DEFINITIONS.csv"
BY_WINDOW_OUT = OUT_DIR / f"{STAGE_FILE}_TECHNICAL_VARIANT_BACKTEST_BY_WINDOW.csv"
RANK_COMPARISON_OUT = OUT_DIR / f"{STAGE_FILE}_TECHNICAL_VARIANT_RANK_COMPARISON.csv"
RECOMMENDATION_OUT = OUT_DIR / f"{STAGE_FILE}_TECHNICAL_REWEIGHTING_RECOMMENDATION.csv"
REPORT_OUT = READ_CENTER_DIR / f"{STAGE_FILE}_TECHNICAL_SUBFACTOR_WEIGHT_VARIANT_BACKTEST_REPORT.md"

PRIMARY_INPUTS = [
    ROOT / "outputs" / "v21" / "factor_backtest" / "V21_005_OBSERVATION_SELECTION_AUDIT.csv",
    ROOT / "outputs" / "v21" / "ablation" / "V21_002_BASELINE_JOINED_FACTOR_OUTCOME_ROWS.csv",
    ROOT / "outputs" / "v21" / "shadow_observation" / "V21_030_R1_CURRENT_DAILY_MATURITY_STATUS_LEDGER.csv",
]

SEARCH_ROOTS = [
    ROOT / "outputs" / "v21",
    ROOT / "outputs" / "v20",
]

SUBFACTORS = [
    "RSI",
    "KDJ",
    "MACD",
    "BB",
    "MA",
    "EMA",
    "VOLUME",
    "VOLATILITY",
    "MOMENTUM",
    "BREAKOUT",
    "PULLBACK",
    "OVERHEAT",
    "DISTANCE_FROM_MA",
    "TECHNICAL_SCORE",
    "STRATEGY_SCORE",
    "RISK_SCORE",
    "FINAL_SCORE",
]

TECHNICAL_COMPONENTS = [
    "RSI",
    "KDJ",
    "MACD",
    "BB",
    "MA",
    "EMA",
    "VOLUME",
    "VOLATILITY",
    "MOMENTUM",
    "BREAKOUT",
    "PULLBACK",
    "OVERHEAT",
    "DISTANCE_FROM_MA",
]

WINDOWS = ["5D", "10D", "20D", "60D"]
BUCKETS = [10, 20, 40, 60]


def norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").strip().lower()).strip("_")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt(row.get(field, "")) for field in fields})


def fmt(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.10f}"
    return value


def yes(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def fnum(value: object) -> float | None:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def stdev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mu = mean(values)
    return math.sqrt(sum((value - mu) ** 2 for value in values) / (len(values) - 1))


def rank_corr(xs: list[float], ys: list[float]) -> float | None:
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    rx = ranks([p[0] for p in pairs])
    ry = ranks([p[1] for p in pairs])
    mx, my = mean(rx), mean(ry)
    vx = sum((x - mx) ** 2 for x in rx)
    vy = sum((y - my) ** 2 for y in ry)
    if vx <= 0 or vy <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(rx, ry)) / math.sqrt(vx * vy)


def ranks(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    out = [0.0] * len(values)
    idx = 0
    while idx < len(indexed):
        end = idx + 1
        while end < len(indexed) and indexed[end][1] == indexed[idx][1]:
            end += 1
        avg = (idx + 1 + end) / 2
        for pos in range(idx, end):
            out[indexed[pos][0]] = avg
        idx = end
    return out


def row_field(row: dict[str, str], candidates: list[str]) -> str:
    by_norm = {norm(key): key for key in row}
    for candidate in candidates:
        key = by_norm.get(norm(candidate))
        if key:
            return row.get(key, "")
    return ""


def detect_columns(headers: list[str], subfactor: str) -> list[str]:
    normalized = {header: norm(header) for header in headers}
    patterns = {
        "RSI": [r"(^|_)rsi($|_)"],
        "KDJ": [r"(^|_)kdj($|_)", r"(^|_)stoch"],
        "MACD": [r"(^|_)macd($|_)"],
        "BB": [r"(^|_)bb($|_)", r"bollinger"],
        "MA": [r"(^|_)ma($|_)", r"moving_average"],
        "EMA": [r"(^|_)ema($|_)"],
        "VOLUME": [r"volume", r"vol_score"],
        "VOLATILITY": [r"volatility", r"atr", r"stddev"],
        "MOMENTUM": [r"momentum"],
        "BREAKOUT": [r"breakout"],
        "PULLBACK": [r"pullback"],
        "OVERHEAT": [r"overheat", r"overbought"],
        "DISTANCE_FROM_MA": [r"distance.*ma", r"ma.*distance"],
        "TECHNICAL_SCORE": [r"technical_score", r"normalized_technical_score"],
        "STRATEGY_SCORE": [r"strategy_score", r"normalized_strategy_score"],
        "RISK_SCORE": [r"risk_score", r"normalized_risk_score"],
        "FINAL_SCORE": [r"baseline_score", r"baseline_detected_score", r"final_score", r"^score$"],
    }
    out = []
    for header, nheader in normalized.items():
        for pattern in patterns.get(subfactor, []):
            if re.search(pattern, nheader):
                out.append(header)
                break
    if subfactor == "MA":
        out = [h for h in out if "macd" not in norm(h) and "ema" not in norm(h)]
    return sorted(set(out))


def detect_headers(paths: list[Path]) -> dict[Path, list[str]]:
    out = {}
    for path in paths:
        if not path.exists() or path.suffix.lower() != ".csv":
            continue
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.reader(handle)
                out[path] = next(reader, [])
        except (OSError, UnicodeDecodeError, StopIteration):
            continue
    return out


def candidate_csvs() -> list[Path]:
    found = [
        ROOT / "outputs" / "v21" / "ablation" / "V21_002_BASELINE_JOINED_FACTOR_OUTCOME_ROWS.csv",
        ROOT / "outputs" / "v21" / "factor_backtest" / "V21_014_RESCALING_VARIANT_SCORE_OUTPUT.csv",
        ROOT / "outputs" / "v21" / "factor_backtest" / "V21_016_RISK_REGIME_PROTOTYPE_VARIANT_SCORE_OUTPUT.csv",
        ROOT / "outputs" / "v21" / "shadow_observation" / "V21_030_REALIZED_FORWARD_RETURNS.csv",
        ROOT / "outputs" / "v20" / "backtest" / "V20_199B_R1_RANDOM_ASOF_RECOMPUTED_FACTOR_SNAPSHOT.csv",
        ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_TABLE.csv",
        ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R7_STRATEGY_CANDIDATE_SCORE_SOURCE.csv",
    ]
    include = re.compile(r"(factor|score|snapshot|candidate|ablation|mature|result|walk|backtest)", re.I)
    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.csv"):
            name = str(path.relative_to(ROOT))
            if include.search(name):
                found.append(path)
            if len(found) >= 300:
                break
        if len(found) >= 300:
            break
    return sorted({path for path in found if path.exists()})


def load_matured_rows() -> tuple[list[dict[str, str]], list[str], int]:
    selection = read_csv(ROOT / "outputs" / "v21" / "factor_backtest" / "V21_005_OBSERVATION_SELECTION_AUDIT.csv")
    usable = [
        row for row in selection
        if row.get("selection_status") == "USABLE_PRIMARY" and row.get("maturity_status") == "MATURED"
    ]
    if usable:
        wanted: dict[str, set[int]] = defaultdict(set)
        for row in usable:
            src = row.get("source_artifact", "")
            row_number = int(fnum(row.get("row_number")) or -1)
            if src and row_number > 0:
                wanted[src].add(row_number)
        rows = []
        inputs = []
        for src, numbers in sorted(wanted.items()):
            path = ROOT / src.replace("\\", "/")
            if not path.exists():
                continue
            inputs.append(str(path.relative_to(ROOT)))
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                for idx, row in enumerate(csv.DictReader(handle), start=1):
                    if idx in numbers:
                        merged = dict(row)
                        merged["_source_artifact"] = src
                        rows.append(merged)
        return rows, inputs, 0

    fallback = ROOT / "outputs" / "v21" / "ablation" / "V21_002_BASELINE_JOINED_FACTOR_OUTCOME_ROWS.csv"
    rows = read_csv(fallback)
    return rows, [str(fallback.relative_to(ROOT))] if rows else [], 0


def pending_current_daily_count() -> int:
    ledger = read_csv(ROOT / "outputs" / "v21" / "shadow_observation" / "V21_030_R1_CURRENT_DAILY_MATURITY_STATUS_LEDGER.csv")
    return sum(1 for row in ledger if row.get("maturity_status") != "MATURED")


def variants() -> list[dict[str, object]]:
    return [
        {
            "variant_name": "BASELINE_CURRENT_TECHNICAL",
            "description": "current observed technical scoring proxy",
            "rsi_treatment": "current",
            "kdj_treatment": "current",
            "macd_treatment": "current",
            "bb_treatment": "current",
            "ma_treatment": "current",
            "volume_treatment": "current",
            "volatility_treatment": "current",
            "rsi_multiplier": 1.0,
            "kdj_multiplier": 1.0,
            "macd_multiplier": 1.0,
            "bb_multiplier": 1.0,
            "ma_multiplier": 1.0,
            "volume_multiplier": 1.0,
            "volatility_multiplier": 1.0,
            "subfactor_cap_enabled": "FALSE",
            "regime_aware_rsi_enabled": "FALSE",
        },
        {
            "variant_name": "RSI_DEEMPHASIZED",
            "description": "reduce RSI influence to avoid simple overheat misclassification",
            "rsi_treatment": "deemphasized",
            "kdj_treatment": "slightly_deemphasized",
            "macd_treatment": "slightly_deemphasized",
            "bb_treatment": "confirmation_emphasized",
            "ma_treatment": "confirmation_emphasized",
            "volume_treatment": "confirmation_emphasized",
            "volatility_treatment": "current",
            "rsi_multiplier": 0.50,
            "kdj_multiplier": 0.90,
            "macd_multiplier": 0.90,
            "bb_multiplier": 1.10,
            "ma_multiplier": 1.10,
            "volume_multiplier": 1.10,
            "volatility_multiplier": 1.00,
            "subfactor_cap_enabled": "FALSE",
            "regime_aware_rsi_enabled": "FALSE",
        },
        {
            "variant_name": "MOMENTUM_DEDUPED",
            "description": "reduce duplicate scoring across RSI, KDJ, and MACD",
            "rsi_treatment": "deemphasized",
            "kdj_treatment": "deduped",
            "macd_treatment": "deduped",
            "bb_treatment": "confirmation_emphasized",
            "ma_treatment": "confirmation_emphasized",
            "volume_treatment": "confirmation_emphasized",
            "volatility_treatment": "current",
            "rsi_multiplier": 0.50,
            "kdj_multiplier": 0.70,
            "macd_multiplier": 0.70,
            "bb_multiplier": 1.10,
            "ma_multiplier": 1.10,
            "volume_multiplier": 1.20,
            "volatility_multiplier": 1.00,
            "subfactor_cap_enabled": "FALSE",
            "regime_aware_rsi_enabled": "FALSE",
        },
        {
            "variant_name": "TECHNICAL_SUBFACTOR_CAPPED",
            "description": "cap individual technical subfactor influence and avoid one technical cluster dominating final score",
            "rsi_treatment": "capped",
            "kdj_treatment": "capped",
            "macd_treatment": "capped",
            "bb_treatment": "current",
            "ma_treatment": "current",
            "volume_treatment": "current",
            "volatility_treatment": "current",
            "rsi_multiplier": 0.70,
            "kdj_multiplier": 0.70,
            "macd_multiplier": 0.70,
            "bb_multiplier": 1.00,
            "ma_multiplier": 1.00,
            "volume_multiplier": 1.00,
            "volatility_multiplier": 1.00,
            "subfactor_cap_enabled": "TRUE",
            "regime_aware_rsi_enabled": "FALSE",
        },
        {
            "variant_name": "REGIME_AWARE_RSI_PROXY",
            "description": "RSI is not penalized solely for being high when trend proxies are positive; overheat penalty is reserved for extended and non-confirmed cases",
            "rsi_treatment": "conditional",
            "kdj_treatment": "deduped",
            "macd_treatment": "deduped",
            "bb_treatment": "confirmation_emphasized",
            "ma_treatment": "confirmation_emphasized",
            "volume_treatment": "confirmation_emphasized",
            "volatility_treatment": "current",
            "rsi_multiplier": "conditional",
            "kdj_multiplier": 0.80,
            "macd_multiplier": 0.80,
            "bb_multiplier": 1.15,
            "ma_multiplier": 1.15,
            "volume_multiplier": 1.10,
            "volatility_multiplier": 1.00,
            "subfactor_cap_enabled": "FALSE",
            "regime_aware_rsi_enabled": "TRUE",
        },
    ]


def field_value(row: dict[str, str], subfactor: str, detected: dict[str, list[str]]) -> float | None:
    for column in detected.get(subfactor, []):
        value = fnum(row.get(column))
        if value is not None:
            return value
    candidates = {
        "TECHNICAL_SCORE": ["normalized_technical_score", "technical_score"],
        "STRATEGY_SCORE": ["normalized_strategy_score", "strategy_score"],
        "RISK_SCORE": ["normalized_risk_score", "risk_score"],
        "FINAL_SCORE": ["baseline_score", "baseline_detected_score", "final_score", "score"],
    }.get(subfactor, [])
    value = fnum(row_field(row, candidates))
    return value


def return_value(row: dict[str, str], window: str) -> float | None:
    return fnum(row_field(row, [f"forward_return_{window.lower()}", f"forward_return_{window}"]))


def benchmark_excess(row: dict[str, str], proxy: str, window: str) -> float | None:
    return fnum(row_field(row, [f"benchmark_excess_vs_{proxy}_{window.lower()}", f"benchmark_excess_vs_{proxy}_{window}"]))


def score_baseline(row: dict[str, str], detected: dict[str, list[str]]) -> float | None:
    return field_value(row, "FINAL_SCORE", detected)


def technical_score(row: dict[str, str], detected: dict[str, list[str]]) -> float | None:
    return field_value(row, "TECHNICAL_SCORE", detected)


def normalize_by_date(rows: list[dict[str, str]], detected: dict[str, list[str]]) -> dict[str, list[float | None]]:
    raw = {sub: [field_value(row, sub, detected) for row in rows] for sub in TECHNICAL_COMPONENTS}
    groups: dict[str, list[int]] = defaultdict(list)
    for idx, row in enumerate(rows):
        groups[row_field(row, ["as_of_date"])].append(idx)
    out = {sub: [None] * len(rows) for sub in TECHNICAL_COMPONENTS}
    for sub in TECHNICAL_COMPONENTS:
        for idxs in groups.values():
            vals = [raw[sub][idx] for idx in idxs if raw[sub][idx] is not None]
            if not vals:
                continue
            lo, hi = min(vals), max(vals)
            for idx in idxs:
                value = raw[sub][idx]
                if value is None:
                    continue
                out[sub][idx] = 0.5 if hi == lo else (value - lo) / (hi - lo)
    return out


def scoring_method_for(rows: list[dict[str, str]], detected: dict[str, list[str]]) -> str:
    granular = [
        sub for sub in TECHNICAL_COMPONENTS
        if detected.get(sub) and any(field_value(row, sub, detected) is not None for row in rows)
    ]
    rich = [sub for sub in granular if sub not in {"MOMENTUM"}]
    if len(rich) >= 3:
        return "TRUE_SUBFACTOR_REWEIGHTING"
    if granular:
        return "PROXY_LIMITED"
    return "PROXY_RESCORING"


def build_variant_scores(rows: list[dict[str, str]], detected: dict[str, list[str]]) -> tuple[dict[str, list[float | None]], dict[str, list[float | None]], str]:
    normalized = normalize_by_date(rows, detected)
    method = scoring_method_for(rows, detected)
    base_final = [score_baseline(row, detected) for row in rows]
    base_tech = [technical_score(row, detected) for row in rows]
    out_final: dict[str, list[float | None]] = {}
    out_tech: dict[str, list[float | None]] = {}
    for variant in variants():
        name = str(variant["variant_name"])
        vf, vt = [], []
        for idx, row in enumerate(rows):
            baseline = base_final[idx]
            tech = base_tech[idx]
            if baseline is None:
                vf.append(None)
                vt.append(None)
                continue
            if name == "BASELINE_CURRENT_TECHNICAL" or tech is None:
                vf.append(baseline)
                vt.append(tech)
                continue
            adjustment_parts = []
            for sub, mult_key in [
                ("RSI", "rsi_multiplier"),
                ("KDJ", "kdj_multiplier"),
                ("MACD", "macd_multiplier"),
                ("BB", "bb_multiplier"),
                ("MA", "ma_multiplier"),
                ("VOLUME", "volume_multiplier"),
                ("VOLATILITY", "volatility_multiplier"),
            ]:
                value = normalized.get(sub, [None])[idx]
                if value is None:
                    continue
                multiplier = variant.get(mult_key)
                if multiplier == "conditional":
                    trend_vals = [
                        normalized.get("MA", [None])[idx],
                        normalized.get("MOMENTUM", [None])[idx],
                        normalized.get("BREAKOUT", [None])[idx],
                    ]
                    trend_confirmation = mean([v for v in trend_vals if v is not None]) if any(v is not None for v in trend_vals) else 0.5
                    multiplier = 1.10 if trend_confirmation >= 0.60 and value >= 0.65 else 0.55
                delta = (float(multiplier) - 1.0) * (value - 0.5)
                if variant.get("subfactor_cap_enabled") == "TRUE":
                    delta = max(-0.08, min(0.08, delta))
                adjustment_parts.append(delta)
            adjustment = mean(adjustment_parts) if adjustment_parts else 0.0
            variant_tech = max(0.0, min(1.0, tech + adjustment))
            variant_final = max(0.0, min(1.0, baseline + 0.25 * (variant_tech - tech)))
            vf.append(variant_final)
            vt.append(variant_tech)
        out_final[name] = vf
        out_tech[name] = vt
    return out_final, out_tech, method


def rank_by_date(rows: list[dict[str, str]], scores: list[float | None]) -> list[int | None]:
    groups: dict[str, list[int]] = defaultdict(list)
    for idx, row in enumerate(rows):
        groups[row_field(row, ["as_of_date"])].append(idx)
    out: list[int | None] = [None] * len(rows)
    for idxs in groups.values():
        valid = [idx for idx in idxs if scores[idx] is not None]
        valid.sort(key=lambda idx: (-float(scores[idx]), row_field(rows[idx], ["ticker"])))
        for rank, idx in enumerate(valid, start=1):
            out[idx] = rank
    return out


def metric(values: list[float]) -> dict[str, object]:
    if not values:
        return {
            "mean_forward_return": None,
            "median_forward_return": None,
            "hit_rate": None,
            "downside_rate": None,
        }
    return {
        "mean_forward_return": mean(values),
        "median_forward_return": median(values),
        "hit_rate": sum(1 for v in values if v > 0) / len(values),
        "downside_rate": sum(1 for v in values if v < 0) / len(values),
    }


def selected_by_bucket(rows: list[dict[str, str]], ranks: list[int | None], bucket: int) -> set[int]:
    return {idx for idx, rank in enumerate(ranks) if rank is not None and rank <= bucket}


def turnover_proxy(rows: list[dict[str, str]], selected: set[int]) -> float | None:
    by_date: dict[str, set[str]] = defaultdict(set)
    for idx in selected:
        by_date[row_field(rows[idx], ["as_of_date"])].add(row_field(rows[idx], ["ticker"]))
    dates = sorted(by_date)
    if len(dates) < 2:
        return None
    turns = []
    for prev, cur in zip(dates, dates[1:]):
        p, c = by_date[prev], by_date[cur]
        denom = len(p | c)
        turns.append(1.0 - (len(p & c) / denom if denom else 0.0))
    return mean(turns) if turns else None


def build_by_window(rows: list[dict[str, str]], variant_scores: dict[str, list[float | None]], scoring_method: str) -> tuple[list[dict[str, object]], dict[str, list[int | None]]]:
    dates = [row_field(row, ["as_of_date"]) for row in rows]
    tickers = [row_field(row, ["ticker"]) for row in rows]
    fwd_by_window = {window: [return_value(row, window) for row in rows] for window in WINDOWS}
    benchmark_by_window = {
        window: {
            "QQQ": [benchmark_excess(row, "QQQ", window) for row in rows],
            "SPY": [benchmark_excess(row, "SPY", window) for row in rows],
            "SOXX": [benchmark_excess(row, "SOXX", window) for row in rows],
        }
        for window in WINDOWS
    }
    ranks = {name: rank_by_date(rows, scores) for name, scores in variant_scores.items()}
    baseline_ranks = ranks["BASELINE_CURRENT_TECHNICAL"]
    available_by_window = {
        window: {idx for idx, value in enumerate(fwd_by_window[window]) if value is not None}
        for window in WINDOWS
    }
    selected_cache = {
        (name, bucket): selected_by_bucket(rows, rank_list, bucket)
        for name, rank_list in ranks.items()
        for bucket in BUCKETS
    }
    turnover_cache = {
        key: turnover_proxy(rows, selected)
        for key, selected in selected_cache.items()
    }
    out = []
    for name, rank_list in ranks.items():
        for window in WINDOWS:
            available = available_by_window[window]
            if not available:
                out.append({
                    "variant_name": name,
                    "scoring_method": scoring_method if name != "BASELINE_CURRENT_TECHNICAL" else "CURRENT_BASELINE",
                    "forward_window": window,
                    "rows_used": 0,
                    "distinct_as_of_dates": 0,
                    "distinct_tickers": 0,
                    "top_bucket": "EXCLUDED",
                    "result_quality": "FORWARD_WINDOW_UNAVAILABLE_OR_IMMATURE",
                    "interpretation_allowed": "FALSE",
                    "interpretation_block_reason": "No matured realized forward-return rows are available for this window.",
                })
                continue
            for bucket in BUCKETS:
                selected = selected_cache[(name, bucket)] & available
                baseline_selected = selected_cache[("BASELINE_CURRENT_TECHNICAL", bucket)] & available
                vals = [fwd_by_window[window][idx] for idx in selected]
                vals = [v for v in vals if v is not None]
                base_vals = [fwd_by_window[window][idx] for idx in baseline_selected]
                base_vals = [v for v in base_vals if v is not None]
                m = metric(vals)
                qqq = [benchmark_by_window[window]["QQQ"][idx] for idx in selected]
                spy = [benchmark_by_window[window]["SPY"][idx] for idx in selected]
                soxx = [benchmark_by_window[window]["SOXX"][idx] for idx in selected]
                qqq_vals = [v for v in qqq if v is not None]
                spy_vals = [v for v in spy if v is not None]
                soxx_vals = [v for v in soxx if v is not None]
                overlap = len(selected & selected_by_bucket(rows, baseline_ranks, 20)) / max(1, len(selected_by_bucket(rows, baseline_ranks, 20))) if bucket == 20 else None
                result_quality = "BENCHMARK_DATA_MISSING" if not (qqq_vals or spy_vals or soxx_vals) else "MATURED_REALIZED_WITH_BENCHMARK_PROXY"
                if not vals:
                    result_quality = "INSUFFICIENT_ROWS"
                out.append({
                    "variant_name": name,
                    "scoring_method": scoring_method if name != "BASELINE_CURRENT_TECHNICAL" else "CURRENT_BASELINE",
                    "forward_window": window,
                    "rows_used": len(vals),
                    "distinct_as_of_dates": len({dates[idx] for idx in selected}),
                    "distinct_tickers": len({tickers[idx] for idx in selected}),
                    "top_bucket": f"TOP{bucket}",
                    **m,
                    "mean_excess_vs_baseline": None if not vals or not base_vals else mean(vals) - mean(base_vals),
                    "median_excess_vs_baseline": None if not vals or not base_vals else median(vals) - median(base_vals),
                    "mean_excess_vs_qqq": mean(qqq_vals) if qqq_vals else None,
                    "median_excess_vs_qqq": median(qqq_vals) if qqq_vals else None,
                    "mean_excess_vs_spy": mean(spy_vals) if spy_vals else None,
                    "mean_excess_vs_soxx": mean(soxx_vals) if soxx_vals else None,
                    "rank_overlap_with_baseline_top20": overlap,
                    "turnover_proxy": turnover_cache[(name, bucket)],
                    "result_quality": result_quality,
                    "interpretation_allowed": "TRUE" if vals else "FALSE",
                    "interpretation_block_reason": "" if vals else "No selected matured rows for this bucket/window.",
                })
    return out, ranks


def build_rank_comparison(rows: list[dict[str, str]], detected: dict[str, list[str]], variant_scores: dict[str, list[float | None]], variant_tech: dict[str, list[float | None]], ranks: dict[str, list[int | None]]) -> list[dict[str, object]]:
    out = []
    baseline_scores = variant_scores["BASELINE_CURRENT_TECHNICAL"]
    baseline_ranks = ranks["BASELINE_CURRENT_TECHNICAL"]
    limit_dates = sorted({row_field(row, ["as_of_date"]) for row in rows})[-12:]
    for idx, row in enumerate(rows):
        if row_field(row, ["as_of_date"]) not in limit_dates:
            continue
        for name in variant_scores:
            out.append({
                "as_of_date": row_field(row, ["as_of_date"]),
                "ticker": row_field(row, ["ticker"]),
                "baseline_rank": baseline_ranks[idx],
                "variant_name": name,
                "variant_rank": ranks[name][idx],
                "rank_delta": None if ranks[name][idx] is None or baseline_ranks[idx] is None else ranks[name][idx] - baseline_ranks[idx],
                "baseline_score": baseline_scores[idx],
                "variant_score": variant_scores[name][idx],
                "technical_score_original": technical_score(row, detected),
                "technical_score_variant": variant_tech[name][idx],
                "rsi_detected_value_or_score": field_value(row, "RSI", detected),
                "kdj_detected_value_or_score": field_value(row, "KDJ", detected),
                "macd_detected_value_or_score": field_value(row, "MACD", detected),
                "bb_detected_value_or_score": field_value(row, "BB", detected),
                "ma_detected_value_or_score": field_value(row, "MA", detected),
                "volume_detected_value_or_score": field_value(row, "VOLUME", detected),
                "volatility_detected_value_or_score": field_value(row, "VOLATILITY", detected),
                "risk_score_or_penalty": field_value(row, "RISK_SCORE", detected),
                "strategy_score": field_value(row, "STRATEGY_SCORE", detected),
                "final_score_original": baseline_scores[idx],
                "final_score_variant": variant_scores[name][idx],
                "forward_return_5d": return_value(row, "5D"),
                "forward_return_10d": return_value(row, "10D"),
                "forward_return_20d": return_value(row, "20D"),
                "forward_return_60d": return_value(row, "60D"),
            })
    return out


def build_influence(rows: list[dict[str, str]], all_headers: dict[Path, list[str]], detected: dict[str, list[str]]) -> list[dict[str, object]]:
    out = []
    final_vals = [field_value(row, "FINAL_SCORE", detected) for row in rows]
    technical_vals = [field_value(row, "TECHNICAL_SCORE", detected) for row in rows]
    fwd = {window: [return_value(row, window) for row in rows] for window in WINDOWS}
    for sub in SUBFACTORS:
        values = [field_value(row, sub, detected) for row in rows]
        present = [v for v in values if v is not None]
        source_cols = []
        for path, headers in all_headers.items():
            for col in detect_columns(headers, sub):
                rel = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
                source_cols.append(f"{rel}:{col}")
                if len(source_cols) >= 80:
                    break
            if len(source_cols) >= 80:
                break
        corr_final = rank_corr([v if v is not None else None for v in values], final_vals)
        corr_tech = rank_corr([v if v is not None else None for v in values], technical_vals)
        corr_5 = rank_corr([v if v is not None else None for v in values], fwd["5D"])
        corr_10 = rank_corr([v if v is not None else None for v in values], fwd["10D"])
        corr_20 = rank_corr([v if v is not None else None for v in values], fwd["20D"])
        duplicate_group = "MOMENTUM_CLUSTER" if sub in {"RSI", "KDJ", "MACD", "MOMENTUM"} else "TREND_CONFIRMATION_CLUSTER" if sub in {"BB", "MA", "EMA", "VOLUME", "BREAKOUT"} else ""
        warning = "POTENTIAL_DUPLICATE_SIGNAL_CLUSTER" if duplicate_group and present else "MISSING_SUBFACTOR_DATA" if not present and sub in TECHNICAL_COMPONENTS else ""
        overheat_warning = "POSSIBLE_TECHNICAL_RISK_DOUBLE_PENALTY" if sub in {"OVERHEAT", "RISK_SCORE"} and present else ""
        interpretation = ""
        action = "retain_audit_only"
        if sub == "RSI" and not present:
            interpretation = "MISSING_SUBFACTOR_DATA"
            action = "add_raw_rsi_capture_before_official_weight_change"
        elif sub == "RSI" and corr_20 is not None and corr_20 <= 0:
            interpretation = "RSI weak_or_negative_realized_relationship"
            action = "test_shadow_rsi_deemphasis_only"
        elif sub in {"KDJ", "MACD"} and present:
            interpretation = "possible_collinearity_with_rsi_momentum_cluster"
            action = "test_shadow_momentum_deduplication"
        elif sub == "TECHNICAL_SCORE":
            interpretation = "aggregate_family_score_available"
            action = "audit_family_dominance_before_any_weight_update"
        out.append({
            "subfactor_name": sub,
            "detected_column_names": "; ".join(sorted(set(source_cols))) if source_cols else "",
            "non_null_count": len(present),
            "missing_count": len(rows) - len(present),
            "mean_value": mean(present) if present else None,
            "median_value": median(present) if present else None,
            "std_value": stdev(present) if present else None,
            "min_value": min(present) if present else None,
            "max_value": max(present) if present else None,
            "inferred_direction": "higher_is_better_proxy" if sub not in {"RISK_SCORE", "OVERHEAT", "VOLATILITY"} else "higher_may_be_penalty_or_risk",
            "current_weight_or_proxy": "RAW_WEIGHT_NOT_FOUND_PROXY_INFLUENCE_ONLY",
            "rank_correlation_with_final_score": corr_final,
            "rank_correlation_with_technical_score": corr_tech,
            "rank_correlation_with_forward_return_5d": corr_5,
            "rank_correlation_with_forward_return_10d": corr_10,
            "rank_correlation_with_forward_return_20d": corr_20,
            "possible_duplicate_signal_group": duplicate_group,
            "collinearity_warning": warning,
            "overheat_double_penalty_warning": overheat_warning,
            "interpretation_issue": interpretation,
            "recommended_action": action,
        })
    return out


def recommendations(influence: list[dict[str, object]], scoring_method: str) -> list[dict[str, object]]:
    by_name = {str(row["subfactor_name"]): row for row in influence}
    rsi_issue = by_name.get("RSI", {}).get("interpretation_issue") or "RSI raw field availability or realized relationship requires more shadow evidence."
    return [
        {
            "recommendation_id": "V21_032_R1_REC_001",
            "recommendation_type": "SHADOW_ONLY_REWEIGHTING",
            "target_subfactor_or_family": "RSI",
            "current_issue": rsi_issue,
            "proposed_change": "Continue RSI_DEEMPHASIZED as shadow-only candidate; no official weight mutation.",
            "evidence_source": scoring_method,
            "expected_benefit": "Reduce simple overheat misclassification risk.",
            "risk_of_change": "Trend continuation candidates may be under-filtered if RSI is useful in current regime.",
            "official_use_allowed": "FALSE",
            "shadow_use_allowed": "TRUE",
            "requires_additional_maturity": "TRUE",
            "next_validation_required": "Mature more shadow observations with raw RSI captured.",
        },
        {
            "recommendation_id": "V21_032_R1_REC_002",
            "recommendation_type": "SHADOW_ONLY_DEDUPLICATION",
            "target_subfactor_or_family": "RSI/KDJ/MACD",
            "current_issue": "Momentum oscillator cluster may repeatedly score the same technical condition.",
            "proposed_change": "Keep MOMENTUM_DEDUPED in research-only comparison.",
            "evidence_source": "TECHNICAL_SUBFACTOR_INFLUENCE_AUDIT",
            "expected_benefit": "Lower ranking distortion from collinear oscillator signals.",
            "risk_of_change": "Could mute valid momentum confirmation.",
            "official_use_allowed": "FALSE",
            "shadow_use_allowed": "TRUE",
            "requires_additional_maturity": "TRUE",
            "next_validation_required": "Raw subfactor capture plus walk-forward validation.",
        },
        {
            "recommendation_id": "V21_032_R1_REC_003",
            "recommendation_type": "OFFICIAL_UPDATE_BLOCKER",
            "target_subfactor_or_family": "TECHNICAL",
            "current_issue": "Current stage is research-only and current daily observations are immature.",
            "proposed_change": "Do not mutate official weights, rankings, reports, broker actions, or book state.",
            "evidence_source": "V21_030_R1 maturity context and V21_032_R1 guardrails",
            "expected_benefit": "Preserves production integrity while research evidence matures.",
            "risk_of_change": "None for production because official use is blocked.",
            "official_use_allowed": "FALSE",
            "shadow_use_allowed": "TRUE",
            "requires_additional_maturity": "TRUE",
            "next_validation_required": "V21.032-R2 raw technical capture and matured shadow validation.",
        },
    ]


def best_variant(by_window: list[dict[str, object]]) -> dict[str, object] | None:
    candidates = [
        row for row in by_window
        if row.get("variant_name") != "BASELINE_CURRENT_TECHNICAL"
        and row.get("forward_window") == "20D"
        and row.get("top_bucket") == "TOP20"
        and fnum(row.get("mean_forward_return")) is not None
    ]
    if not candidates:
        candidates = [
            row for row in by_window
            if row.get("variant_name") != "BASELINE_CURRENT_TECHNICAL"
            and row.get("top_bucket") == "TOP20"
            and fnum(row.get("mean_forward_return")) is not None
        ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda row: (fnum(row.get("mean_forward_return")) or -999, fnum(row.get("mean_excess_vs_baseline")) or -999), reverse=True)[0]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)

    rows, inputs_used, immature_from_input = load_matured_rows()
    immature_pending = pending_current_daily_count()
    csvs = candidate_csvs()
    headers = detect_headers(csvs)
    primary_headers = list(rows[0].keys()) if rows else []
    detected = {sub: detect_columns(primary_headers, sub) for sub in SUBFACTORS}
    for sub in SUBFACTORS:
        if not detected[sub]:
            for cols in headers.values():
                detected[sub] = detect_columns(cols, sub)
                if detected[sub]:
                    break

    definitions = variants()
    variant_scores, variant_tech, scoring_method = build_variant_scores(rows, detected) if rows else ({v["variant_name"]: [] for v in definitions}, {v["variant_name"]: [] for v in definitions}, "PROXY_RESCORING")
    by_window, ranks = build_by_window(rows, variant_scores, scoring_method) if rows else ([], {})
    influence = build_influence(rows, headers, detected)
    rank_comparison = build_rank_comparison(rows, detected, variant_scores, variant_tech, ranks) if rows else []
    recs = recommendations(influence, scoring_method)
    best = best_variant(by_window)
    baseline = next((row for row in by_window if row.get("variant_name") == "BASELINE_CURRENT_TECHNICAL" and row.get("forward_window") == (best or {}).get("forward_window") and row.get("top_bucket") == (best or {}).get("top_bucket")), None)
    matured_count = len(rows)
    final_status = PASS_STATUS if matured_count > 0 else PARTIAL_STATUS
    benchmark_status = "QQQ" if any(fnum(row.get("mean_excess_vs_qqq")) is not None for row in by_window) else "BENCHMARK_DATA_MISSING"

    summary = [{
        "stage": STAGE,
        "final_status": final_status,
        "decision": DECISION,
        "research_only": "TRUE",
        "official_use_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "real_book_mutation_allowed": "FALSE",
        "baseline_variant_name": "BASELINE_CURRENT_TECHNICAL",
        "best_shadow_variant_name": best.get("variant_name") if best else "",
        "best_shadow_variant_selected": "TRUE" if best and fnum(best.get("mean_excess_vs_baseline")) is not None and (fnum(best.get("mean_excess_vs_baseline")) or 0) > 0 else "FALSE",
        "benchmark_primary": benchmark_status,
        "benchmark_secondary": "SPY" if any(fnum(row.get("mean_excess_vs_spy")) is not None for row in by_window) else "BENCHMARK_DATA_MISSING",
        "benchmark_semiconductor_proxy": "SOXX" if any(fnum(row.get("mean_excess_vs_soxx")) is not None for row in by_window) else "BENCHMARK_DATA_MISSING",
        "total_rows_used": len(rows),
        "matured_rows_used": matured_count,
        "immature_rows_excluded": immature_pending + immature_from_input,
        "distinct_as_of_dates": len({row_field(row, ["as_of_date"]) for row in rows}),
        "distinct_tickers": len({row_field(row, ["ticker"]) for row in rows}),
        "forward_windows_tested": "|".join(sorted({str(row.get("forward_window")) for row in by_window if fnum(row.get("rows_used")) and int(fnum(row.get("rows_used")) or 0) > 0})),
        "variants_tested_count": len(definitions),
        "best_variant_mean_forward_return": best.get("mean_forward_return") if best else None,
        "baseline_mean_forward_return": baseline.get("mean_forward_return") if baseline else None,
        "best_variant_mean_excess_vs_baseline": best.get("mean_excess_vs_baseline") if best else None,
        "best_variant_mean_excess_vs_qqq": best.get("mean_excess_vs_qqq") if best else None,
        "best_variant_hit_rate": best.get("hit_rate") if best else None,
        "baseline_hit_rate": baseline.get("hit_rate") if baseline else None,
        "best_variant_turnover_proxy": best.get("turnover_proxy") if best else None,
        "best_variant_rank_overlap_with_baseline_top20": best.get("rank_overlap_with_baseline_top20") if best else None,
        "data_trust_alpha_weight_allowed": "FALSE",
        "next_recommended_stage": "V21.032-R2_RAW_TECHNICAL_SUBFACTOR_CAPTURE_AND_MATURED_SHADOW_VALIDATION",
    }]

    definition_fields = [
        "variant_name", "description", "scoring_method", "rsi_treatment", "kdj_treatment", "macd_treatment",
        "bb_treatment", "ma_treatment", "volume_treatment", "volatility_treatment", "rsi_multiplier",
        "kdj_multiplier", "macd_multiplier", "bb_multiplier", "ma_multiplier", "volume_multiplier",
        "volatility_multiplier", "subfactor_cap_enabled", "regime_aware_rsi_enabled",
    ]
    for row in definitions:
        row["scoring_method"] = scoring_method if row["variant_name"] != "BASELINE_CURRENT_TECHNICAL" else "CURRENT_BASELINE"

    write_csv(SUMMARY_OUT, summary, list(summary[0].keys()))
    write_csv(INFLUENCE_OUT, influence, [
        "subfactor_name", "detected_column_names", "non_null_count", "missing_count", "mean_value",
        "median_value", "std_value", "min_value", "max_value", "inferred_direction", "current_weight_or_proxy",
        "rank_correlation_with_final_score", "rank_correlation_with_technical_score",
        "rank_correlation_with_forward_return_5d", "rank_correlation_with_forward_return_10d",
        "rank_correlation_with_forward_return_20d", "possible_duplicate_signal_group",
        "collinearity_warning", "overheat_double_penalty_warning", "interpretation_issue", "recommended_action",
    ])
    write_csv(DEFINITIONS_OUT, definitions, definition_fields)
    write_csv(BY_WINDOW_OUT, by_window, [
        "variant_name", "scoring_method", "forward_window", "rows_used", "distinct_as_of_dates", "distinct_tickers",
        "top_bucket", "mean_forward_return", "median_forward_return", "hit_rate", "downside_rate",
        "mean_excess_vs_baseline", "median_excess_vs_baseline", "mean_excess_vs_qqq", "median_excess_vs_qqq",
        "mean_excess_vs_spy", "mean_excess_vs_soxx", "rank_overlap_with_baseline_top20", "turnover_proxy",
        "result_quality", "interpretation_allowed", "interpretation_block_reason",
    ])
    write_csv(RANK_COMPARISON_OUT, rank_comparison, [
        "as_of_date", "ticker", "baseline_rank", "variant_name", "variant_rank", "rank_delta", "baseline_score",
        "variant_score", "technical_score_original", "technical_score_variant", "rsi_detected_value_or_score",
        "kdj_detected_value_or_score", "macd_detected_value_or_score", "bb_detected_value_or_score",
        "ma_detected_value_or_score", "volume_detected_value_or_score", "volatility_detected_value_or_score",
        "risk_score_or_penalty", "strategy_score", "final_score_original", "final_score_variant",
        "forward_return_5d", "forward_return_10d", "forward_return_20d", "forward_return_60d",
    ])
    write_csv(RECOMMENDATION_OUT, recs, [
        "recommendation_id", "recommendation_type", "target_subfactor_or_family", "current_issue",
        "proposed_change", "evidence_source", "expected_benefit", "risk_of_change", "official_use_allowed",
        "shadow_use_allowed", "requires_additional_maturity", "next_validation_required",
    ])

    report = f"""# {STAGE}

Generated: {datetime.now(UTC).isoformat()}

## Final status and decision

- final_status: {final_status}
- decision: {DECISION}
- research_only: TRUE
- official weight mutation allowed: FALSE

## Input files used

{chr(10).join(f"- {item}" for item in inputs_used) if inputs_used else "- No matured input rows found."}

## Scoring method

True raw subfactor weights were not found as an official contract. This stage used `{scoring_method}` and labels missing raw technical fields as `MISSING_SUBFACTOR_DATA` or `PROXY_LIMITED`; it does not fabricate RSI, KDJ, MACD, BB, MA, volume, or volatility values.

## Technical subfactor influence audit

See `{INFLUENCE_OUT.relative_to(ROOT)}`. Aggregate technical score availability is audited separately from raw technical subfactors.

## RSI-specific findings

RSI columns detected in the primary matured rows: {yes(bool(detected.get("RSI")))}. Missing RSI data blocks official interpretation and supports shadow-only RSI deemphasis testing.

## KDJ/MACD/RSI collinearity findings

The oscillator cluster is treated as a possible duplicate signal group. Any de-duplication recommendation remains shadow-only until raw subfactor capture matures.

## BB/MA/volume confirmation findings

Confirmation fields are used only when locally detected. Missing confirmation fields are not synthesized.

## Overheat double-penalty findings

Overheat and Risk are audited for possible double penalty. The stage does not change Risk or Technical production logic.

## Variant definitions

See `{DEFINITIONS_OUT.relative_to(ROOT)}` for the five required variants and their multipliers.

## Backtest results by forward window

See `{BY_WINDOW_OUT.relative_to(ROOT)}`. Unavailable or immature windows are excluded from realized-performance interpretation and marked in `result_quality` / `interpretation_block_reason`.

## Comparison vs baseline

Baseline comparison is computed by top bucket and forward window using matured historical observations only.

## Comparison vs QQQ, SPY, and SOXX

Benchmark proxy status: QQQ={summary[0]["benchmark_primary"]}, SPY={summary[0]["benchmark_secondary"]}, SOXX={summary[0]["benchmark_semiconductor_proxy"]}. Missing benchmark windows are marked `BENCHMARK_DATA_MISSING` instead of failing.

## Best shadow variant

Best shadow variant: {summary[0]["best_shadow_variant_name"] or "none selected"}. Selection flag: {summary[0]["best_shadow_variant_selected"]}.

## Why official weight mutation remains blocked

Official weight mutation remains blocked because this is a research-only shadow stage, current daily observations are pending maturity and excluded from realized evidence, raw official subfactor weights were not found, DATA_TRUST alpha weight must remain zero, and the evidence is not an approved production promotion gate.

## Next recommended stage

{summary[0]["next_recommended_stage"]}
"""
    REPORT_OUT.write_text(report, encoding="utf-8")
    print(f"STAGE_NAME={STAGE}")
    print(f"final_status={final_status}")
    print(f"decision={DECISION}")
    print("research_only=TRUE")
    print("official_weight_mutation_allowed=FALSE")


if __name__ == "__main__":
    main()
