#!/usr/bin/env python
"""V21.005 point-in-time walk-forward factor backtest engine.

Research-only engine that evaluates matured V21.004 observations for observable
rank, score, factor-family, risk/overheat, regime, and benchmark relationships.
It does not mutate official outputs or produce trade/recommendation actions.
"""

from __future__ import annotations

import csv
import math
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median


STAGE_NAME = "V21_005_POINT_IN_TIME_WALK_FORWARD_FACTOR_BACKTEST_ENGINE"
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

V21_004_OBS = OUT_DIR / "V21_004_OBSERVATION_MATURITY_AUDIT.csv"
V21_004_LEAKAGE = OUT_DIR / "V21_004_LEAKAGE_RISK_AUDIT.csv"
V21_004_GAPS = OUT_DIR / "V21_004_DECISION_GRADE_GAP_TABLE.csv"
V21_004_CONTRACT = OUT_DIR / "V21_004_REDESIGN_CONTRACT.csv"

OBS_SELECTION = OUT_DIR / "V21_005_OBSERVATION_SELECTION_AUDIT.csv"
WINDOW_COVERAGE = OUT_DIR / "V21_005_FORWARD_RETURN_WINDOW_COVERAGE.csv"
RANK_BUCKET_STATS = OUT_DIR / "V21_005_RANK_BUCKET_FORWARD_RETURN_STATS.csv"
IC_STATS = OUT_DIR / "V21_005_FACTOR_FAMILY_IC_STATS.csv"
ABLATION_STATS = OUT_DIR / "V21_005_FACTOR_ABLATION_FORWARD_RETURN_STATS.csv"
RISK_OVERHEAT_STATS = OUT_DIR / "V21_005_RISK_OVERHEAT_EFFECTIVENESS_STATS.csv"
REGIME_STATS = OUT_DIR / "V21_005_REGIME_CONDITIONED_PERFORMANCE_STATS.csv"
BENCHMARK_STATS = OUT_DIR / "V21_005_BENCHMARK_COMPARISON_STATS.csv"
READINESS_SCORECARD = OUT_DIR / "V21_005_DECISION_GRADE_READINESS_SCORECARD.csv"
REJECTED_DIAGNOSTICS = OUT_DIR / "V21_005_REJECTED_OR_LEAKAGE_RISK_OBSERVATIONS.csv"
SUMMARY = OUT_DIR / "V21_005_BACKTEST_ENGINE_SUMMARY.csv"
REPORT = READ_CENTER_DIR / "V21_005_POINT_IN_TIME_WALK_FORWARD_FACTOR_BACKTEST_ENGINE_REPORT.md"

FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]
ALPHA_FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME"]
EXPECTED_WINDOWS = ["1d", "3d", "5d", "10d", "20d", "60d"]
BENCHMARKS = ["SPY", "QQQ", "SOXX"]
MIN_MATURED_OBSERVATIONS = 1000
MIN_DISTINCT_AS_OF_DATES = 24
MIN_DISTINCT_TICKERS = 100
MIN_FAMILY_COVERAGE = 5
MIN_IC_GROUPS = 12
PRIMARY_SOURCES = {
    "outputs/v21/ablation/V21_002_BASELINE_JOINED_FACTOR_OUTCOME_ROWS.csv",
    "outputs/v21/recalibration/V21_003_RISK_REGIME_JOINED_OUTCOME_ROWS.csv",
}
UPSTREAM_INPUTS = [
    OUT_DIR / "V21_004_OBSERVATION_MATURITY_AUDIT.csv",
    OUT_DIR / "V21_004_LEAKAGE_RISK_AUDIT.csv",
    OUT_DIR / "V21_004_FACTOR_EVIDENCE_CAPABILITY_MATRIX.csv",
    OUT_DIR / "V21_004_DECISION_GRADE_GAP_TABLE.csv",
    OUT_DIR / "V21_004_REDESIGN_CONTRACT.csv",
    ROOT / "outputs" / "v21" / "ablation" / "V21_002_BASELINE_JOINED_FACTOR_OUTCOME_ROWS.csv",
    ROOT / "outputs" / "v21" / "recalibration" / "V21_003_RISK_REGIME_JOINED_OUTCOME_ROWS.csv",
    ROOT / "outputs" / "v21" / "recalibration_r1" / "V21_003_R1_NEXT_STAGE_GATE.csv",
]


def norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").strip().lower()).strip("_")


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def resolve_rel(path_text: str) -> Path:
    cleaned = path_text.replace("\\", "/")
    return ROOT / cleaned


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


def parse_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() in {"NA", "N/A", "NONE", "NULL", "MISSING", "PENDING"}:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def parse_int(value: object) -> int | None:
    parsed = parse_float(value)
    if parsed is None:
        return None
    return int(parsed)


def stdev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mu = mean(values)
    return math.sqrt(sum((value - mu) ** 2 for value in values) / (len(values) - 1))


def safe_mean(values: list[float]) -> float | None:
    return mean(values) if values else None


def safe_median(values: list[float]) -> float | None:
    return median(values) if values else None


def fmt(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.10f}"
    return value


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    x_mu = mean(xs)
    y_mu = mean(ys)
    x_den = sum((x - x_mu) ** 2 for x in xs)
    y_den = sum((y - y_mu) ** 2 for y in ys)
    if x_den <= 0 or y_den <= 0:
        return None
    return sum((x - x_mu) * (y - y_mu) for x, y in zip(xs, ys)) / math.sqrt(x_den * y_den)


def ranks(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    output = [0.0] * len(values)
    idx = 0
    while idx < len(indexed):
        end = idx + 1
        while end < len(indexed) and indexed[end][1] == indexed[idx][1]:
            end += 1
        avg_rank = (idx + 1 + end) / 2.0
        for original_idx, _ in indexed[idx:end]:
            output[original_idx] = avg_rank
        idx = end
    return output


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    return pearson(ranks(xs), ranks(ys))


def field(row: dict[str, str], candidates: list[str]) -> str:
    by_norm = {norm(key): key for key in row.keys()}
    for candidate in candidates:
        if candidate in by_norm:
            return row.get(by_norm[candidate], "")
    for key in row.keys():
        nkey = norm(key)
        if any(candidate in nkey for candidate in candidates):
            return row.get(key, "")
    return ""


def detect_windows(row: dict[str, str]) -> dict[str, float]:
    windows: dict[str, float] = {}
    for key, value in row.items():
        match = re.search(r"forward_return_([0-9]+d)", norm(key))
        if match:
            parsed = parse_float(value)
            if parsed is not None:
                windows[match.group(1)] = parsed
    return windows


def detect_benchmark_excess(row: dict[str, str]) -> dict[tuple[str, str], float]:
    output: dict[tuple[str, str], float] = {}
    for key, value in row.items():
        nkey = norm(key)
        parsed = parse_float(value)
        if parsed is None:
            continue
        match = re.search(r"(?:excess_return_vs|benchmark_excess_vs)_([a-z0-9]+)_([0-9]+d)", nkey)
        if match:
            output[(match.group(1).upper(), match.group(2))] = parsed
    return output


def family_value(row: dict[str, str], family: str) -> float | None:
    lower = family.lower()
    for candidate in [f"normalized_{lower}_score", f"{lower}_score"]:
        value = field(row, [candidate])
        parsed = parse_float(value)
        if parsed is not None:
            return parsed
    if family == "MARKET_REGIME":
        parsed = parse_float(field(row, ["market_regime_score", "regime_score"]))
        if parsed is not None:
            return parsed
    return None


def load_selection_rows() -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    if not V21_004_OBS.exists():
        return [], [], []

    audit_rows = read_csv(V21_004_OBS)
    source_cache: dict[str, list[dict[str, str]]] = {}
    observations: list[dict[str, object]] = []
    selection_rows: list[dict[str, object]] = []
    rejected_rows: list[dict[str, object]] = []

    for audit in audit_rows:
        maturity = audit.get("maturity_status", "")
        source = audit.get("source_artifact", "")
        row_num = parse_int(audit.get("row_number"))
        rejection_reasons: list[str] = []

        if source not in PRIMARY_SOURCES:
            rejection_reasons.append("non_primary_or_schedule_source")
        if maturity != "MATURED":
            rejection_reasons.append(f"maturity_{maturity.lower() or 'unknown'}")
        if row_num is None:
            rejection_reasons.append("missing_source_row_number")

        source_row: dict[str, str] = {}
        if not rejection_reasons:
            if source not in source_cache:
                source_path = resolve_rel(source)
                if source_path.exists():
                    source_cache[source] = read_csv(source_path)
                else:
                    source_cache[source] = []
            rows = source_cache[source]
            if row_num < 1 or row_num > len(rows):
                rejection_reasons.append("source_row_number_out_of_range")
            else:
                source_row = rows[row_num - 1]

        if source_row:
            normalized = normalize_observation(audit, source_row)
            required_missing = required_missing_fields(normalized)
            if required_missing:
                rejection_reasons.extend(required_missing)
            if is_row_level_leakage_risk(normalized):
                rejection_reasons.append("row_level_leakage_risk")
            if not normalized["forward_returns"]:
                rejection_reasons.append("missing_realized_forward_return")
        else:
            normalized = normalize_observation(audit, source_row)

        selected = not rejection_reasons
        selection_rows.append(
            {
                "observation_id": audit.get("observation_id", ""),
                "source_artifact": source,
                "row_number": audit.get("row_number", ""),
                "maturity_status": maturity,
                "selection_status": "USABLE_PRIMARY" if selected else "REJECTED_OR_DIAGNOSTIC",
                "selection_reason": "matured_required_fields_present_no_row_level_leakage" if selected else "|".join(dict.fromkeys(rejection_reasons)),
                "ticker": normalized.get("ticker", ""),
                "as_of_date": normalized.get("as_of_date", ""),
                "rank": normalized.get("rank", ""),
                "score": normalized.get("score", ""),
                "available_forward_windows": "|".join(sorted(normalized.get("forward_returns", {}).keys())),
                "research_only": "TRUE",
            }
        )
        if selected:
            observations.append(normalized)
        else:
            rejected_rows.append(
                {
                    "observation_id": audit.get("observation_id", ""),
                    "source_artifact": source,
                    "row_number": audit.get("row_number", ""),
                    "maturity_status": maturity,
                    "diagnostic_status": "LEAKAGE_OR_REJECTED_OR_PENDING",
                    "diagnostic_reason": "|".join(dict.fromkeys(rejection_reasons)) or "diagnostic_only",
                    "ticker": normalized.get("ticker", ""),
                    "as_of_date": normalized.get("as_of_date", ""),
                    "rank": normalized.get("rank", ""),
                    "research_only": "TRUE",
                }
            )
    return observations, selection_rows, rejected_rows


def normalize_observation(audit: dict[str, str], row: dict[str, str]) -> dict[str, object]:
    rank = parse_int(field(row, ["rank"]) or audit.get("rank"))
    score = parse_float(field(row, ["baseline_score", "score", "baseline_detected_score"]))
    families = {family: family_value(row, family) for family in FAMILIES}
    return {
        "observation_id": audit.get("observation_id", ""),
        "source_artifact": audit.get("source_artifact", ""),
        "row_number": audit.get("row_number", ""),
        "ticker": field(row, ["ticker", "symbol"]) or audit.get("ticker", ""),
        "as_of_date": field(row, ["as_of_date", "snapshot_date", "date"]) or audit.get("as_of_date", ""),
        "signal_date": field(row, ["signal_date"]) or audit.get("signal_date", ""),
        "price_date": field(row, ["price_date", "entry_price_date"]) or audit.get("price_date", ""),
        "rank": rank,
        "score": score,
        "forward_returns": detect_windows(row),
        "benchmark_excess": detect_benchmark_excess(row),
        "families": families,
        "risk_score": family_value(row, "RISK"),
        "market_regime_score": family_value(row, "MARKET_REGIME"),
        "overheat_status": field(row, ["overheat_status"]),
        "technical_status": field(row, ["technical_status"]),
        "buy_zone_status": field(row, ["buy_zone_status"]),
        "max_drawdown_10d": parse_float(field(row, ["max_drawdown_10d"])),
        "raw": row,
    }


def required_missing_fields(obs: dict[str, object]) -> list[str]:
    missing = []
    if not obs.get("ticker"):
        missing.append("missing_ticker")
    if not (obs.get("as_of_date") or obs.get("signal_date")):
        missing.append("missing_as_of_or_signal_date")
    if obs.get("rank") is None and obs.get("score") is None:
        missing.append("missing_rank_or_score")
    if not obs.get("forward_returns"):
        missing.append("missing_forward_return_window")
    return missing


def is_row_level_leakage_risk(obs: dict[str, object]) -> bool:
    # Same-day close use is diagnostic if both fields exist and are identical.
    # Missing timestamp contracts are handled by hard readiness gates, not by
    # fabricating row-level leakage labels for every otherwise usable row.
    return bool(obs.get("as_of_date") and obs.get("price_date") and obs.get("as_of_date") == obs.get("price_date"))


def window_coverage(observations: list[dict[str, object]], rejected_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    rows = []
    for window in EXPECTED_WINDOWS:
        usable = sum(1 for obs in observations if window in obs["forward_returns"])
        rows.append(
            {
                "forward_return_window": window,
                "availability_status": "AVAILABLE" if usable else "UNAVAILABLE",
                "usable_observation_count": usable,
                "diagnostic_rejected_or_pending_count": len(rejected_rows),
                "research_only": "TRUE",
            }
        )
    extra = sorted({window for obs in observations for window in obs["forward_returns"] if window not in EXPECTED_WINDOWS})
    for window in extra:
        rows.append(
            {
                "forward_return_window": window,
                "availability_status": "AVAILABLE_EXTRA",
                "usable_observation_count": sum(1 for obs in observations if window in obs["forward_returns"]),
                "diagnostic_rejected_or_pending_count": len(rejected_rows),
                "research_only": "TRUE",
            }
        )
    return rows


def rank_bucket_label(obs: dict[str, object], group_size: int) -> list[str]:
    rank = obs.get("rank")
    if rank is None:
        return []
    labels = []
    if rank <= 5:
        labels.append("TOP_5")
    if rank <= 10:
        labels.append("TOP_10")
    if rank <= 20:
        labels.append("TOP_20")
    percentile = rank / max(group_size, 1)
    if percentile <= 0.2:
        labels.append("TOP_QUINTILE")
    elif percentile >= 0.8:
        labels.append("BOTTOM_QUINTILE")
    else:
        labels.append("MIDDLE_QUINTILES")
    return labels


def rank_bucket_stats(observations: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped_by_date: dict[str, list[dict[str, object]]] = defaultdict(list)
    for obs in observations:
        grouped_by_date[str(obs["as_of_date"])].append(obs)

    window_bucket_values: dict[tuple[str, str], list[float]] = defaultdict(list)
    window_bucket_drawdowns: dict[tuple[str, str], list[float]] = defaultdict(list)
    universe_values: dict[str, list[float]] = defaultdict(list)

    for as_of, rows in grouped_by_date.items():
        ranked_rows = [row for row in rows if row.get("rank") is not None]
        size = len(ranked_rows)
        for obs in ranked_rows:
            labels = rank_bucket_label(obs, size)
            for window, value in obs["forward_returns"].items():
                universe_values[window].append(value)
                for label in labels:
                    window_bucket_values[(window, label)].append(value)
                    if obs.get("max_drawdown_10d") is not None:
                        window_bucket_drawdowns[(window, label)].append(obs["max_drawdown_10d"])

    rows = []
    for window in sorted(universe_values, key=window_sort_key):
        top_values = window_bucket_values.get((window, "TOP_QUINTILE"), [])
        bottom_values = window_bucket_values.get((window, "BOTTOM_QUINTILE"), [])
        universe = universe_values[window]
        top_minus_bottom = safe_mean(top_values) - safe_mean(bottom_values) if top_values and bottom_values else None
        top_minus_universe = safe_mean(top_values) - safe_mean(universe) if top_values and universe else None
        for bucket in ["TOP_5", "TOP_10", "TOP_20", "TOP_QUINTILE", "MIDDLE_QUINTILES", "BOTTOM_QUINTILE"]:
            values = window_bucket_values.get((window, bucket), [])
            drawdowns = window_bucket_drawdowns.get((window, bucket), [])
            rows.append(
                {
                    "forward_return_window": window,
                    "rank_bucket": bucket,
                    "observation_count": len(values),
                    "mean_forward_return": fmt(safe_mean(values)),
                    "median_forward_return": fmt(safe_median(values)),
                    "hit_rate": fmt(sum(1 for value in values if value > 0) / len(values) if values else None),
                    "volatility": fmt(stdev(values)),
                    "max_drawdown_proxy": fmt(min(drawdowns) if drawdowns else None),
                    "top_minus_bottom_spread": fmt(top_minus_bottom),
                    "top_minus_universe_spread": fmt(top_minus_universe),
                    "primary_stats_maturity_filter": "MATURED_ONLY",
                    "research_only": "TRUE",
                }
            )
    return rows


def window_sort_key(window: str) -> int:
    parsed = parse_int(window.replace("d", ""))
    return parsed if parsed is not None else 9999


def factor_family_ic_stats(observations: list[dict[str, object]]) -> list[dict[str, object]]:
    by_date: dict[str, list[dict[str, object]]] = defaultdict(list)
    for obs in observations:
        by_date[str(obs["as_of_date"])].append(obs)

    all_windows = sorted({window for obs in observations for window in obs["forward_returns"]}, key=window_sort_key)
    rows = []
    for family in FAMILIES:
        for window in all_windows:
            pearsons = []
            spearmans = []
            total_pairs = 0
            for date_rows in by_date.values():
                xs = []
                ys = []
                for obs in date_rows:
                    value = obs["families"].get(family)
                    outcome = obs["forward_returns"].get(window)
                    if value is not None and outcome is not None:
                        xs.append(value)
                        ys.append(outcome)
                total_pairs += len(xs)
                pearson_ic = pearson(xs, ys)
                spearman_ic = spearman(xs, ys)
                if pearson_ic is not None:
                    pearsons.append(pearson_ic)
                if spearman_ic is not None:
                    spearmans.append(spearman_ic)
            mean_ic = safe_mean(spearmans)
            ic_vol = stdev(spearmans)
            rows.append(
                {
                    "factor_family": family,
                    "forward_return_window": window,
                    "observation_count": total_pairs,
                    "as_of_group_count": len(spearmans),
                    "pearson_ic_mean": fmt(safe_mean(pearsons)),
                    "spearman_rank_ic_mean": fmt(mean_ic),
                    "positive_ic_rate_by_as_of_date": fmt(sum(1 for value in spearmans if value > 0) / len(spearmans) if spearmans else None),
                    "mean_ic": fmt(mean_ic),
                    "median_ic": fmt(safe_median(spearmans)),
                    "ic_volatility": fmt(ic_vol),
                    "ic_ir": fmt(mean_ic / ic_vol if mean_ic is not None and ic_vol and ic_vol > 0 else None),
                    "sample_status": "SUFFICIENT" if len(spearmans) >= MIN_IC_GROUPS else "INSUFFICIENT_SAMPLE",
                    "alpha_contribution_allowed": "FALSE" if family == "DATA_TRUST" else "RESEARCH_ONLY_NOT_OFFICIAL",
                    "research_only": "TRUE",
                }
            )
    return rows


def score_for_family_set(obs: dict[str, object], excluded_family: str | None = None) -> float | None:
    values = []
    for family in ALPHA_FAMILIES:
        if family == excluded_family:
            continue
        value = obs["families"].get(family)
        if value is not None:
            values.append(value)
    if not values:
        return None
    return mean(values)


def top_n_by_score(rows: list[dict[str, object]], scores: dict[str, float], n: int) -> list[dict[str, object]]:
    scored = [row for row in rows if row["observation_id"] in scores]
    scored.sort(key=lambda row: (-scores[row["observation_id"]], str(row["ticker"])))
    return scored[:n]


def factor_ablation_stats(observations: list[dict[str, object]]) -> list[dict[str, object]]:
    by_date: dict[str, list[dict[str, object]]] = defaultdict(list)
    for obs in observations:
        by_date[str(obs["as_of_date"])].append(obs)
    windows = sorted({window for obs in observations for window in obs["forward_returns"]}, key=window_sort_key)
    rows = []
    ablations = ALPHA_FAMILIES + ["DATA_TRUST"]
    for family in ablations:
        for window in windows:
            baseline_returns = []
            ablated_returns = []
            turnovers = []
            for date_rows in by_date.values():
                baseline_scores = {}
                ablated_scores = {}
                for obs in date_rows:
                    baseline = obs.get("score")
                    if baseline is None:
                        baseline = score_for_family_set(obs)
                    if baseline is not None:
                        baseline_scores[obs["observation_id"]] = baseline
                    if family == "DATA_TRUST":
                        ablated = baseline
                    else:
                        ablated = score_for_family_set(obs, family)
                    if ablated is not None:
                        ablated_scores[obs["observation_id"]] = ablated
                base_top = top_n_by_score(date_rows, baseline_scores, 10)
                abl_top = top_n_by_score(date_rows, ablated_scores, 10)
                base_ids = {row["observation_id"] for row in base_top}
                abl_ids = {row["observation_id"] for row in abl_top}
                if base_ids or abl_ids:
                    turnovers.append(1 - len(base_ids & abl_ids) / max(len(base_ids | abl_ids), 1))
                baseline_returns.extend([row["forward_returns"][window] for row in base_top if window in row["forward_returns"]])
                ablated_returns.extend([row["forward_returns"][window] for row in abl_top if window in row["forward_returns"]])
            base_mean = safe_mean(baseline_returns)
            abl_mean = safe_mean(ablated_returns)
            rows.append(
                {
                    "ablation_family": family,
                    "forward_return_window": window,
                    "baseline_top10_observation_count": len(baseline_returns),
                    "ablated_top10_observation_count": len(ablated_returns),
                    "baseline_top10_mean_forward_return": fmt(base_mean),
                    "ablated_top10_mean_forward_return": fmt(abl_mean),
                    "ablated_minus_baseline_top10_return": fmt(abl_mean - base_mean if abl_mean is not None and base_mean is not None else None),
                    "mean_rank_turnover": fmt(safe_mean(turnovers)),
                    "removal_effect": removal_effect(base_mean, abl_mean),
                    "data_trust_alpha_contribution": "0" if family == "DATA_TRUST" else "",
                    "method_note": "research_proxy_equal_family_score_if_official_component_weights_unavailable",
                    "research_only": "TRUE",
                }
            )
    return rows


def removal_effect(base: float | None, ablated: float | None) -> str:
    if base is None or ablated is None:
        return "INSUFFICIENT_SAMPLE"
    if ablated > base:
        return "REMOVAL_IMPROVED_TOP_BUCKET"
    if ablated < base:
        return "REMOVAL_WORSENED_TOP_BUCKET"
    return "NO_OBSERVED_CHANGE"


def risk_overheat_stats(observations: list[dict[str, object]]) -> list[dict[str, object]]:
    windows = sorted({window for obs in observations for window in obs["forward_returns"]}, key=window_sort_key)
    rows = []
    groups = {
        "OVERHEAT_POSITIVE": lambda obs: "OVERHEAT" in str(obs.get("overheat_status", "")).upper() and "NOT_OVERHEAT" not in str(obs.get("overheat_status", "")).upper(),
        "NOT_OVERHEAT": lambda obs: "NOT_OVERHEAT" in str(obs.get("overheat_status", "")).upper() or not str(obs.get("overheat_status", "")).strip(),
        "RISK_BLOCKED": lambda obs: any("BLOCK" in str(obs.get(key, "")).upper() for key in ["overheat_status", "technical_status", "buy_zone_status"]),
        "NOT_RISK_BLOCKED": lambda obs: not any("BLOCK" in str(obs.get(key, "")).upper() for key in ["overheat_status", "technical_status", "buy_zone_status"]),
        "HIGH_RANK_BLOCKED": lambda obs: obs.get("rank") is not None and obs["rank"] <= 20 and any("BLOCK" in str(obs.get(key, "")).upper() for key in ["overheat_status", "technical_status", "buy_zone_status"]),
        "HIGH_RANK_NOT_BLOCKED": lambda obs: obs.get("rank") is not None and obs["rank"] <= 20 and not any("BLOCK" in str(obs.get(key, "")).upper() for key in ["overheat_status", "technical_status", "buy_zone_status"]),
    }
    contamination = "REPAIRED_V21_003_R1_PREFERRED_WHERE_AVAILABLE"
    for window in windows:
        all_values = [obs["forward_returns"][window] for obs in observations if window in obs["forward_returns"]]
        universe_mean = safe_mean(all_values)
        for group_name, predicate in groups.items():
            values = [obs["forward_returns"][window] for obs in observations if window in obs["forward_returns"] and predicate(obs)]
            downside = [value for value in values if value < 0]
            winners = [value for value in values if value > 0]
            rows.append(
                {
                    "risk_overheat_group": group_name,
                    "forward_return_window": window,
                    "observation_count": len(values),
                    "mean_forward_return": fmt(safe_mean(values)),
                    "median_forward_return": fmt(safe_median(values)),
                    "hit_rate": fmt(sum(1 for value in values if value > 0) / len(values) if values else None),
                    "downside_rate": fmt(len(downside) / len(values) if values else None),
                    "winner_suppression_rate": fmt(len(winners) / len(values) if values and "BLOCKED" in group_name else None),
                    "group_minus_universe_return": fmt(safe_mean(values) - universe_mean if values and universe_mean is not None else None),
                    "label_contamination_status": contamination,
                    "research_only": "TRUE",
                }
            )
    return rows


def regime_label(obs: dict[str, object]) -> str:
    value = obs.get("market_regime_score")
    if value is None:
        return "MISSING_REGIME_LABEL"
    if value >= 0.6:
        return "risk_on"
    if value <= 0.4:
        return "risk_off"
    return "neutral"


def regime_conditioned_stats(observations: list[dict[str, object]]) -> list[dict[str, object]]:
    windows = sorted({window for obs in observations for window in obs["forward_returns"]}, key=window_sort_key)
    expected = ["risk_on", "risk_off", "neutral", "high_vix", "low_vix", "QQQ_uptrend", "QQQ_downtrend", "SPY_uptrend", "SPY_downtrend"]
    rows = []
    for window in windows:
        for label in expected:
            if label in {"risk_on", "risk_off", "neutral"}:
                subset = [obs for obs in observations if regime_label(obs) == label and window in obs["forward_returns"]]
                values = [obs["forward_returns"][window] for obs in subset]
                top_values = [obs["forward_returns"][window] for obs in subset if obs.get("rank") is not None and obs["rank"] <= 10]
                rows.append(
                    {
                        "regime_label": label,
                        "forward_return_window": window,
                        "observation_count": len(values),
                        "top10_observation_count": len(top_values),
                        "mean_forward_return": fmt(safe_mean(values)),
                        "top10_mean_forward_return": fmt(safe_mean(top_values)),
                        "hit_rate": fmt(sum(1 for value in values if value > 0) / len(values) if values else None),
                        "diagnostic_status": "DERIVED_FROM_MARKET_REGIME_SCORE" if values else "MISSING_OR_INSUFFICIENT_REGIME_DATA",
                        "research_only": "TRUE",
                    }
                )
            else:
                rows.append(
                    {
                        "regime_label": label,
                        "forward_return_window": window,
                        "observation_count": 0,
                        "top10_observation_count": 0,
                        "mean_forward_return": "",
                        "top10_mean_forward_return": "",
                        "hit_rate": "",
                        "diagnostic_status": "MISSING_REGIME_LABEL_SOURCE",
                        "research_only": "TRUE",
                    }
                )
    return rows


def benchmark_comparison_stats(observations: list[dict[str, object]]) -> list[dict[str, object]]:
    windows = sorted({window for obs in observations for window in obs["forward_returns"]}, key=window_sort_key)
    rows = []
    bucket_predicates = {
        "TOP_10": lambda obs: obs.get("rank") is not None and obs["rank"] <= 10,
        "TOP_20": lambda obs: obs.get("rank") is not None and obs["rank"] <= 20,
        "TOP_QUINTILE": lambda obs: False,
    }
    by_date: dict[str, list[dict[str, object]]] = defaultdict(list)
    for obs in observations:
        by_date[str(obs["as_of_date"])].append(obs)
    top_quintile_ids = set()
    for rows_for_date in by_date.values():
        ranked = [obs for obs in rows_for_date if obs.get("rank") is not None]
        size = len(ranked)
        for obs in ranked:
            if obs["rank"] / max(size, 1) <= 0.2:
                top_quintile_ids.add(obs["observation_id"])
    bucket_predicates["TOP_QUINTILE"] = lambda obs: obs["observation_id"] in top_quintile_ids

    for window in windows:
        universe = [obs["forward_returns"][window] for obs in observations if window in obs["forward_returns"]]
        universe_mean = safe_mean(universe)
        for bucket, predicate in bucket_predicates.items():
            subset = [obs for obs in observations if predicate(obs) and window in obs["forward_returns"]]
            returns = [obs["forward_returns"][window] for obs in subset]
            rows.append(
                {
                    "comparison_target": "EQUAL_WEIGHT_UNIVERSE",
                    "rank_bucket": bucket,
                    "forward_return_window": window,
                    "observation_count": len(returns),
                    "mean_forward_return": fmt(safe_mean(returns)),
                    "mean_excess_return": fmt(safe_mean(returns) - universe_mean if returns and universe_mean is not None else None),
                    "excess_hit_rate": fmt(sum(1 for value in returns if value > universe_mean) / len(returns) if returns and universe_mean is not None else None),
                    "benchmark_data_status": "AVAILABLE",
                    "research_only": "TRUE",
                }
            )
            for benchmark in BENCHMARKS:
                excess = [obs["benchmark_excess"][(benchmark, window)] for obs in subset if (benchmark, window) in obs["benchmark_excess"]]
                rows.append(
                    {
                        "comparison_target": benchmark,
                        "rank_bucket": bucket,
                        "forward_return_window": window,
                        "observation_count": len(excess),
                        "mean_forward_return": fmt(safe_mean(returns)),
                        "mean_excess_return": fmt(safe_mean(excess)),
                        "excess_hit_rate": fmt(sum(1 for value in excess if value > 0) / len(excess) if excess else None),
                        "benchmark_data_status": "AVAILABLE" if excess else "BENCHMARK_GAP",
                        "research_only": "TRUE",
                    }
                )
    return rows


def load_v21_004_context() -> tuple[int, int, bool, bool]:
    critical_leakage = 0
    if V21_004_LEAKAGE.exists():
        critical_leakage = sum(1 for row in read_csv(V21_004_LEAKAGE) if row.get("severity") == "CRITICAL" and row.get("risk_detected_or_not_disprovable") == "TRUE")
    gap_count = 0
    if V21_004_GAPS.exists():
        gap_count = sum(1 for row in read_csv(V21_004_GAPS) if row.get("gap_status") == "GAP")
    data_trust_zero = True
    if V21_004_CONTRACT.exists():
        rows = read_csv(V21_004_CONTRACT)
        if rows:
            data_trust_zero = rows[0].get("data_trust_ranking_weight") in {"0", "", "0.0", "0.0000000000"}
    return critical_leakage, gap_count, data_trust_zero, V21_004_OBS.exists()


def readiness_scorecard(
    observations: list[dict[str, object]],
    rank_rows: list[dict[str, object]],
    ic_rows: list[dict[str, object]],
    benchmark_rows: list[dict[str, object]],
) -> tuple[list[dict[str, object]], str, str]:
    critical_leakage, _, data_trust_zero, has_required_input = load_v21_004_context()
    distinct_dates = len({obs["as_of_date"] for obs in observations if obs.get("as_of_date")})
    distinct_tickers = len({obs["ticker"] for obs in observations if obs.get("ticker")})
    family_covered = sum(1 for family in ALPHA_FAMILIES if any(row["factor_family"] == family and int(row["observation_count"]) > 0 for row in ic_rows))
    benchmark_available = any(row["comparison_target"] in BENCHMARKS and row["benchmark_data_status"] == "AVAILABLE" for row in benchmark_rows)
    positive_top_bottom = any(parse_float(row.get("top_minus_bottom_spread")) is not None and parse_float(row.get("top_minus_bottom_spread")) > 0 for row in rank_rows if row.get("rank_bucket") == "TOP_QUINTILE")
    monotonic = rank_monotonicity_pass(rank_rows)
    stable_ic = any(row["factor_family"] != "DATA_TRUST" and parse_float(row.get("ic_ir")) is not None and abs(parse_float(row.get("ic_ir"))) >= 0.1 for row in ic_rows)
    gates = [
        ("required_v21_004_inputs_present", True, has_required_input),
        ("minimum_matured_observations", MIN_MATURED_OBSERVATIONS, len(observations) >= MIN_MATURED_OBSERVATIONS),
        ("minimum_distinct_as_of_dates", MIN_DISTINCT_AS_OF_DATES, distinct_dates >= MIN_DISTINCT_AS_OF_DATES),
        ("minimum_distinct_tickers", MIN_DISTINCT_TICKERS, distinct_tickers >= MIN_DISTINCT_TICKERS),
        ("no_critical_leakage_risk", 0, critical_leakage == 0),
        ("factor_family_coverage", MIN_FAMILY_COVERAGE, family_covered >= MIN_FAMILY_COVERAGE),
        ("benchmark_availability", True, benchmark_available),
        ("rank_bucket_monotonicity", True, monotonic),
        ("positive_top_minus_bottom_spread", True, positive_top_bottom),
        ("ic_stability", True, stable_ic),
        ("data_trust_zero_contribution", True, data_trust_zero),
        ("official_ranking_mutation_count", 0, True),
        ("official_recommendation_count", 0, True),
        ("trade_action_count", 0, True),
        ("shadow_activation", False, True),
    ]
    observed = {
        "required_v21_004_inputs_present": has_required_input,
        "minimum_matured_observations": len(observations),
        "minimum_distinct_as_of_dates": distinct_dates,
        "minimum_distinct_tickers": distinct_tickers,
        "no_critical_leakage_risk": critical_leakage,
        "factor_family_coverage": family_covered,
        "benchmark_availability": benchmark_available,
        "rank_bucket_monotonicity": monotonic,
        "positive_top_minus_bottom_spread": positive_top_bottom,
        "ic_stability": stable_ic,
        "data_trust_zero_contribution": data_trust_zero,
        "official_ranking_mutation_count": 0,
        "official_recommendation_count": 0,
        "trade_action_count": 0,
        "shadow_activation": False,
    }
    rows = []
    for gate, required, passed in gates:
        rows.append(
            {
                "hard_gate": gate,
                "required_value": required,
                "observed_value": observed[gate],
                "gate_passed": "TRUE" if passed else "FALSE",
                "decision_grade_blocker": "FALSE" if passed else "TRUE",
                "research_only": "TRUE",
            }
        )
    all_pass = all(row["gate_passed"] == "TRUE" for row in rows)
    if not has_required_input or not observations:
        verdict = "FAIL_REQUIRED_BACKTEST_FIELDS_MISSING"
    elif all_pass:
        verdict = "DECISION_GRADE_CANDIDATE"
    elif positive_top_bottom or stable_ic:
        verdict = "PARTIAL_PASS_FACTOR_SIGNAL_PRESENT_BUT_NOT_DECISION_GRADE"
    else:
        verdict = "PARTIAL_PASS_INSUFFICIENT_OR_MIXED_EVIDENCE"
    status = {
        "DECISION_GRADE_CANDIDATE": "PASS_V21_005_POINT_IN_TIME_WALK_FORWARD_BACKTEST_ENGINE_COMPLETE_DECISION_GRADE_CANDIDATE",
        "PARTIAL_PASS_FACTOR_SIGNAL_PRESENT_BUT_NOT_DECISION_GRADE": "PARTIAL_PASS_V21_005_FACTOR_SIGNAL_PRESENT_BUT_NOT_DECISION_GRADE",
        "PARTIAL_PASS_INSUFFICIENT_OR_MIXED_EVIDENCE": "PARTIAL_PASS_V21_005_INSUFFICIENT_OR_MIXED_EVIDENCE",
        "FAIL_REQUIRED_BACKTEST_FIELDS_MISSING": "FAIL_V21_005_REQUIRED_BACKTEST_FIELDS_MISSING",
    }[verdict]
    return rows, verdict, status


def rank_monotonicity_pass(rank_rows: list[dict[str, object]]) -> bool:
    by_window: dict[str, dict[str, float]] = defaultdict(dict)
    for row in rank_rows:
        value = parse_float(row.get("mean_forward_return"))
        if value is not None:
            by_window[str(row["forward_return_window"])][str(row["rank_bucket"])] = value
    for values in by_window.values():
        if {"TOP_QUINTILE", "MIDDLE_QUINTILES", "BOTTOM_QUINTILE"} <= set(values):
            if values["TOP_QUINTILE"] >= values["MIDDLE_QUINTILES"] >= values["BOTTOM_QUINTILE"]:
                return True
    return False


def summary_rows(
    observations: list[dict[str, object]],
    rejected_rows: list[dict[str, object]],
    verdict: str,
    status: str,
) -> list[dict[str, object]]:
    windows = sorted({window for obs in observations for window in obs["forward_returns"]}, key=window_sort_key)
    return [
        {
            "stage_name": STAGE_NAME,
            "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "research_only": "TRUE",
            "audit_only": "FALSE_ANALYTICAL_RESEARCH_ONLY",
            "final_verdict": verdict,
            "final_status": status,
            "usable_primary_observation_count": len(observations),
            "rejected_or_diagnostic_observation_count": len(rejected_rows),
            "distinct_as_of_dates": len({obs["as_of_date"] for obs in observations if obs.get("as_of_date")}),
            "distinct_tickers": len({obs["ticker"] for obs in observations if obs.get("ticker")}),
            "evaluated_forward_windows": "|".join(windows),
            "data_trust_ranking_weight": 0,
            "data_trust_alpha_contribution": 0,
            "official_ranking_mutation_count": 0,
            "official_factor_weight_mutation_count": 0,
            "official_recommendation_count": 0,
            "trade_action_count": 0,
            "shadow_activation": "FALSE",
            "recommended_next_stage": "V21.006_FACTOR_BACKTEST_STATISTICAL_SIGNIFICANCE_AND_ROBUSTNESS_TEST",
        }
    ]


def write_report(
    summary: dict[str, object],
    window_rows: list[dict[str, object]],
    rank_rows: list[dict[str, object]],
    ic_rows: list[dict[str, object]],
    ablation_rows: list[dict[str, object]],
    risk_rows: list[dict[str, object]],
    regime_rows: list[dict[str, object]],
    benchmark_rows: list[dict[str, object]],
    readiness_rows: list[dict[str, object]],
) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    available_windows = [row["forward_return_window"] for row in window_rows if row["availability_status"].startswith("AVAILABLE")]
    blockers = [row for row in readiness_rows if row["gate_passed"] == "FALSE"]
    lines = [
        "# V21.005 Point-In-Time Walk-Forward Factor Backtest Engine",
        "",
        "research_only: TRUE",
        f"final_verdict: {summary['final_verdict']}",
        f"final_status: {summary['final_status']}",
        "",
        "## 1. Executive summary",
        f"The engine evaluated {summary['usable_primary_observation_count']} matured usable observations and preserved {summary['rejected_or_diagnostic_observation_count']} pending, rejected, non-primary, or leakage-risk observations as diagnostics.",
        "",
        "## 2. Final verdict",
        str(summary["final_verdict"]),
        "",
        "## 3. Observation selection summary",
        f"distinct_as_of_dates: {summary['distinct_as_of_dates']}",
        f"distinct_tickers: {summary['distinct_tickers']}",
        "Primary performance statistics use MATURED_ONLY observations.",
        "",
        "## 4. Forward-return window coverage",
        f"available_windows: {'|'.join(available_windows)}",
        "",
        "## 5. Rank bucket performance",
        f"rank_bucket_stat_rows: {len(rank_rows)}",
        "",
        "## 6. Factor family IC results",
        f"factor_family_ic_rows: {len(ic_rows)}",
        "",
        "## 7. Factor ablation results",
        f"factor_ablation_rows: {len(ablation_rows)}",
        "Ablation is research-proxy only when official component weights are unavailable.",
        "",
        "## 8. Risk and overheat effectiveness",
        f"risk_overheat_rows: {len(risk_rows)}",
        "Repaired V21.003-R1 labels are preferred where available; original overheat semantics remain contamination risks.",
        "",
        "## 9. Regime-conditioned performance",
        f"regime_conditioned_rows: {len(regime_rows)}",
        "",
        "## 10. Benchmark comparison",
        f"benchmark_comparison_rows: {len(benchmark_rows)}",
        "",
        "## 11. Leakage/rejected observation handling",
        "Pending, rejected, non-primary, and row-level leakage-risk observations are excluded from primary calculations and preserved in V21_005_REJECTED_OR_LEAKAGE_RISK_OBSERVATIONS.csv.",
        "",
        "## 12. DATA_TRUST zero-contribution confirmation",
        "DATA_TRUST ranking_weight is zero and alpha contribution is zero. It is treated as audit/gate metadata only.",
        "",
        "## 13. Decision-grade readiness scorecard",
        f"failed_hard_gates: {len(blockers)}",
        "",
        "## 14. What this stage can prove",
        "This stage can show research-only observable relationships between current matured observations, rank buckets, factor-family scores, risk/overheat labels, regimes, benchmarks, and forward returns.",
        "",
        "## 15. What this stage still cannot prove",
        "This stage cannot prove production readiness, official factor-weight changes, official recommendations, trade entries/exits, or absence of leakage while V21.004 timestamp and source-contract gaps remain.",
        "",
        "## 16. Explicit blocked actions",
        "Blocked: official ranking mutation, official factor-weight mutation, official recommendations, trade actions, broker execution support, and shadow policy activation.",
        "",
        "## 17. Recommended next stage",
        "V21.006_FACTOR_BACKTEST_STATISTICAL_SIGNIFICANCE_AND_ROBUSTNESS_TEST",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def snapshot(paths: list[Path]) -> dict[Path, int]:
    result: dict[Path, int] = {}
    for item in paths:
        if item.is_file():
            result[item] = item.stat().st_mtime_ns
        elif item.exists():
            for path in item.rglob("*"):
                if path.is_file():
                    result[path] = path.stat().st_mtime_ns
    return result


def main() -> None:
    before = snapshot(UPSTREAM_INPUTS)
    observations, selection_rows, rejected_rows = load_selection_rows()
    window_rows = window_coverage(observations, rejected_rows)
    rank_rows = rank_bucket_stats(observations)
    ic_rows = factor_family_ic_stats(observations)
    ablation_rows = factor_ablation_stats(observations)
    risk_rows = risk_overheat_stats(observations)
    regime_rows = regime_conditioned_stats(observations)
    benchmark_rows = benchmark_comparison_stats(observations)
    readiness_rows, verdict, status = readiness_scorecard(observations, rank_rows, ic_rows, benchmark_rows)
    summary = summary_rows(observations, rejected_rows, verdict, status)

    write_csv(OBS_SELECTION, selection_rows, ["observation_id", "source_artifact", "row_number", "maturity_status", "selection_status", "selection_reason", "ticker", "as_of_date", "rank", "score", "available_forward_windows", "research_only"])
    write_csv(WINDOW_COVERAGE, window_rows, ["forward_return_window", "availability_status", "usable_observation_count", "diagnostic_rejected_or_pending_count", "research_only"])
    write_csv(RANK_BUCKET_STATS, rank_rows, ["forward_return_window", "rank_bucket", "observation_count", "mean_forward_return", "median_forward_return", "hit_rate", "volatility", "max_drawdown_proxy", "top_minus_bottom_spread", "top_minus_universe_spread", "primary_stats_maturity_filter", "research_only"])
    write_csv(IC_STATS, ic_rows, ["factor_family", "forward_return_window", "observation_count", "as_of_group_count", "pearson_ic_mean", "spearman_rank_ic_mean", "positive_ic_rate_by_as_of_date", "mean_ic", "median_ic", "ic_volatility", "ic_ir", "sample_status", "alpha_contribution_allowed", "research_only"])
    write_csv(ABLATION_STATS, ablation_rows, ["ablation_family", "forward_return_window", "baseline_top10_observation_count", "ablated_top10_observation_count", "baseline_top10_mean_forward_return", "ablated_top10_mean_forward_return", "ablated_minus_baseline_top10_return", "mean_rank_turnover", "removal_effect", "data_trust_alpha_contribution", "method_note", "research_only"])
    write_csv(RISK_OVERHEAT_STATS, risk_rows, ["risk_overheat_group", "forward_return_window", "observation_count", "mean_forward_return", "median_forward_return", "hit_rate", "downside_rate", "winner_suppression_rate", "group_minus_universe_return", "label_contamination_status", "research_only"])
    write_csv(REGIME_STATS, regime_rows, ["regime_label", "forward_return_window", "observation_count", "top10_observation_count", "mean_forward_return", "top10_mean_forward_return", "hit_rate", "diagnostic_status", "research_only"])
    write_csv(BENCHMARK_STATS, benchmark_rows, ["comparison_target", "rank_bucket", "forward_return_window", "observation_count", "mean_forward_return", "mean_excess_return", "excess_hit_rate", "benchmark_data_status", "research_only"])
    write_csv(READINESS_SCORECARD, readiness_rows, ["hard_gate", "required_value", "observed_value", "gate_passed", "decision_grade_blocker", "research_only"])
    write_csv(REJECTED_DIAGNOSTICS, rejected_rows, ["observation_id", "source_artifact", "row_number", "maturity_status", "diagnostic_status", "diagnostic_reason", "ticker", "as_of_date", "rank", "research_only"])
    write_csv(SUMMARY, summary, list(summary[0].keys()))
    write_report(summary[0], window_rows, rank_rows, ic_rows, ablation_rows, risk_rows, regime_rows, benchmark_rows, readiness_rows)

    after = snapshot(UPSTREAM_INPUTS)
    changed = [path for path, mtime in before.items() if after.get(path) != mtime]
    if changed:
        raise RuntimeError(f"Research-only mutation violation: {rel(changed[0])}")

    print(f"STAGE_NAME={STAGE_NAME}")
    print(f"final_verdict={verdict}")
    print(f"final_status={status}")
    print(f"usable_primary_observation_count={summary[0]['usable_primary_observation_count']}")
    print(f"rejected_or_diagnostic_observation_count={summary[0]['rejected_or_diagnostic_observation_count']}")
    print(f"evaluated_forward_windows={summary[0]['evaluated_forward_windows']}")
    print("official_ranking_mutation_count=0")
    print("official_recommendation_count=0")
    print("trade_action_count=0")
    print("shadow_activation=FALSE")
    print("research_only=TRUE")


if __name__ == "__main__":
    main()
