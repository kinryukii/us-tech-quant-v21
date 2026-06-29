#!/usr/bin/env python
"""Research-only unified momentum leadership tracker for V21.058-R1."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


STAGE_ID = "V21.058-R1"
PASS_STATUS = "PASS_V21_058_R1_UNIFIED_MOMENTUM_TRACKER_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_058_R1_MOMENTUM_TRACKER_READY_WITH_DATA_WARN"
BLOCKED_STATUS = "BLOCKED_V21_058_R1_FORCED_MOMENTUM_AUDIT_INCOMPLETE"
FAIL_HARDCODED = "FAIL_V21_058_R1_HARDCODED_INCLUSION_VIOLATION"
FAIL_EXHAUSTION = "FAIL_V21_058_R1_HIGH_MOMENTUM_AUTO_EXHAUSTION_VIOLATION"
FAIL_RISK = "FAIL_V21_058_R1_LEVERAGED_OR_INVERSE_RISK_RULE_VIOLATION"
FAIL_MUTATION = "FAIL_V21_058_R1_FORBIDDEN_MUTATION_DETECTED"

OUT_REL = Path("outputs/v21/momentum")
DISCOVERY_REL = Path("outputs/v21/unified_pool/V21_057_R2_ALGORITHMIC_DISCOVERY_POOL.csv")
ELIGIBLE_DISCOVERY_REL = Path("outputs/v21/unified_pool/V21_057_R2_ELIGIBLE_DISCOVERY_POOL.csv")
FORCED_DISCOVERY_REL = Path("outputs/v21/unified_pool/V21_057_R2_FORCED_AUDIT_DISCOVERY_EXPLANATION.csv")
R1_POOL_REL = Path("outputs/v21/unified_pool/V21_057_R1_UNIFIED_OPPORTUNITY_POOL.csv")
R1_ELIGIBLE_REL = Path("outputs/v21/unified_pool/V21_057_R1_ELIGIBLE_UNIFIED_POOL.csv")
PRICE_REL = Path("inputs/v21/historical_ohlcv_cache/V21_037_R1_HISTORICAL_OHLCV_CACHE.csv")
A0_REL = Path("outputs/v21/experiments/version_control/V21_056_R2_A0_CANONICAL_CONTROL_VIEW.csv")
R1_SNAPSHOT_REL = Path("outputs/v21/experiments/version_control/V21_056_R1_A0_LEDGER_SNAPSHOT.csv")

LEDGER_NAME = "V21_058_R1_UNIFIED_MOMENTUM_LEDGER.csv"
TOP50_NAME = "V21_058_R1_MOMENTUM_TOP50.csv"
LEADERSHIP_NAME = "V21_058_R1_MOMENTUM_LEADERSHIP_BOARD.csv"
CHASE_NAME = "V21_058_R1_CHASE_PERMISSION_BOARD.csv"
EXHAUSTION_NAME = "V21_058_R1_EXHAUSTION_RISK_AUDIT.csv"
FORCED_NAME = "V21_058_R1_FORCED_MOMENTUM_AUDIT.csv"
DATA_WARN_NAME = "V21_058_R1_DATA_WARN_AUDIT.csv"
FLOW_NAME = "V21_058_R1_DISCOVERY_TO_MOMENTUM_LINEAGE_AUDIT.csv"
LINEAGE_NAME = "V21_058_R1_LINEAGE_AUDIT.csv"
SUMMARY_NAME = "V21_058_R1_SUMMARY.json"
FORCED = ("MU", "SNDK", "DRAM", "SMH", "SOXX", "SOXL", "USD", "QQQ", "TQQQ", "SQQQ")

LEDGER_FIELDS = [
    "ticker", "as_of_date", "instrument_type", "asset_class", "theme",
    "underlying_index", "leverage_multiplier", "direction", "is_inverse",
    "is_daily_reset", "is_leveraged", "selection_lane", "source_membership",
    "entered_by_existing_candidate_universe", "entered_by_price_universe_discovery",
    "entered_by_relative_strength_discovery", "entered_by_theme_discovery",
    "entered_by_etf_seed", "entered_by_forced_audit_only",
    "objective_discovery_admission_reason", "eligible_for_unified_pool",
    "price_available", "volume_available", "latest_price_date",
    "price_freshness_status", "data_sufficiency_status", "return_3d",
    "return_5d", "return_10d", "return_20d",
    "excess_return_5d_vs_SPY", "excess_return_10d_vs_SPY",
    "excess_return_20d_vs_SPY", "excess_return_5d_vs_QQQ",
    "excess_return_10d_vs_QQQ", "excess_return_20d_vs_QQQ",
    "excess_return_5d_vs_SMH", "excess_return_10d_vs_SMH",
    "excess_return_20d_vs_SMH", "excess_return_5d_vs_SOXX",
    "excess_return_10d_vs_SOXX", "excess_return_20d_vs_SOXX",
    "price_above_ma5", "price_above_ma10", "price_above_ma20",
    "price_above_ma50", "ma5_slope", "ma10_slope", "ma20_slope", "rsi",
    "rsi_slope", "macd_hist", "macd_hist_slope", "volume_ratio_5d_vs_20d",
    "drawdown_from_20d_high", "drawdown_from_60d_high",
    "absolute_momentum_score", "relative_momentum_score",
    "momentum_acceleration_score", "trend_persistence_score",
    "exhaustion_risk_score", "momentum_leadership_score",
    "extension_awareness_flag", "deterioration_confirmation_flag",
    "high_momentum_not_auto_exhaustion_flag", "momentum_state",
    "chase_permission", "risk_size_bucket", "tactical_only", "hedge_only",
    "daily_reset_risk_flag", "leverage_decay_risk_flag", "market_regime",
    "risk_off_confirmed", "regime_fallback_used", "score_computed",
    "score_missing_reason", "research_only",
]


def clean(value: object) -> str:
    return str(value or "").strip()


def tf(value: object) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return "TRUE" if clean(value).upper() == "TRUE" else "FALSE"


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.is_file() or path.stat().st_size == 0:
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def write_csv(path: Path, rows: Iterable[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                field: "TRUE" if row.get(field) is True else "FALSE" if row.get(field) is False
                else "" if row.get(field) is None else row.get(field, "")
                for field in fields
            })


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def row_count(path: Path) -> int:
    return len(read_csv(path)[0])


def protected_hashes(root: Path) -> dict[str, dict[str, str]]:
    groups = {"a0": {}, "official": {}, "real_book": {}, "broker": {}}
    for path in (root / A0_REL, root / R1_SNAPSHOT_REL):
        if path.is_file():
            groups["a0"][rel(root, path)] = sha(path)
    for base in (root / "outputs", root / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or root / OUT_REL in path.parents:
                continue
            text = rel(root, path).lower().replace("-", "_").replace(" ", "_")
            if "broker" in text:
                groups["broker"][rel(root, path)] = sha(path)
            elif "real_book" in text or "realbook" in text:
                groups["real_book"][rel(root, path)] = sha(path)
            elif "official" in text and any(word in text for word in ("rank", "weight", "recommend", "allocation")):
                groups["official"][rel(root, path)] = sha(path)
    return groups


def differences(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))


def num(value: object) -> float | None:
    try:
        parsed = float(clean(value))
        return parsed if math.isfinite(parsed) else None
    except ValueError:
        return None


def text_num(value: object) -> str:
    value = num(value)
    return "" if value is None else f"{value:.10f}"


def rsi_series(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def consecutive_true(values: pd.Series) -> int:
    count = 0
    for value in reversed(values.astype(bool).tolist()):
        if not value:
            break
        count += 1
    return count


def indicator_metrics(group: pd.DataFrame) -> dict[str, object]:
    group = group.sort_values("as_of_date").drop_duplicates("as_of_date", keep="last")
    close = group["price"].astype(float).reset_index(drop=True)
    volume = group["volume"].astype(float).reset_index(drop=True)
    if len(close) < 60:
        return {"history_rows": len(close), "latest_price_date": group["as_of_date"].max()}
    metrics: dict[str, object] = {
        "history_rows": len(close), "latest_price_date": group["as_of_date"].max(),
        "as_of_date": group["as_of_date"].max(),
    }
    for window in (3, 5, 10, 20):
        metrics[f"return_{window}d"] = close.iloc[-1] / close.iloc[-window - 1] - 1
    for window in (5, 10, 20, 50):
        ma = close.rolling(window).mean()
        metrics[f"ma{window}"] = ma.iloc[-1]
        metrics[f"price_above_ma{window}"] = close.iloc[-1] > ma.iloc[-1]
        metrics[f"ma{window}_slope"] = ma.iloc[-1] / ma.iloc[-4] - 1 if len(ma.dropna()) >= 4 else np.nan
        metrics[f"days_above_ma{window}"] = consecutive_true(close.tail(30) > ma.tail(30))
    rsi = rsi_series(close)
    ema12, ema26 = close.ewm(span=12, adjust=False).mean(), close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    hist = macd - macd.ewm(span=9, adjust=False).mean()
    metrics.update({
        "rsi": rsi.iloc[-1], "rsi_slope": rsi.iloc[-1] - rsi.iloc[-4],
        "macd_hist": hist.iloc[-1], "macd_hist_slope": hist.iloc[-1] - hist.iloc[-4],
        "volume_available": bool(volume.notna().any()),
        "volume_ratio_5d_vs_20d": volume.tail(5).mean() / volume.tail(20).mean()
        if volume.tail(20).notna().sum() >= 10 and volume.tail(20).mean() > 0 else np.nan,
        "drawdown_from_20d_high": close.iloc[-1] / close.tail(20).max() - 1,
        "drawdown_from_60d_high": close.iloc[-1] / close.tail(60).max() - 1,
        "new_20d_high": close.iloc[-1] >= close.tail(20).max(),
        "new_60d_high": close.iloc[-1] >= close.tail(60).max(),
        "return_3d_acceleration": (close.iloc[-1] / close.iloc[-4] - 1) - (close.iloc[-4] / close.iloc[-7] - 1),
        "higher_high_count": sum(close.iloc[-i] > close.iloc[-i - 1] for i in range(1, 11)),
        "higher_low_count": sum(close.iloc[-i] > close.iloc[-i - 2] for i in range(1, 10)),
        "close": close.iloc[-1],
    })
    return metrics


def load_metrics(path: Path, tickers: set[str]) -> tuple[dict[str, dict[str, object]], int]:
    use = ["as_of_date", "ticker", "close", "adjusted_close", "volume"]
    frame = pd.read_csv(path, usecols=use, low_memory=False)
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    frame = frame[frame["ticker"].isin(tickers)]
    frame["price"] = pd.to_numeric(frame["adjusted_close"], errors="coerce").fillna(pd.to_numeric(frame["close"], errors="coerce"))
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce")
    frame = frame[frame["price"].gt(0) & frame["as_of_date"].notna()]
    result = {ticker: indicator_metrics(group) for ticker, group in frame.groupby("ticker")}
    return result, len(frame)


def pct_scores(frame: pd.DataFrame, columns: list[tuple[str, bool]]) -> pd.Series:
    parts = []
    for column, positive in columns:
        values = pd.to_numeric(frame[column], errors="coerce")
        ranked = values.rank(pct=True, method="average") * 100
        parts.append(ranked if positive else 100 - ranked)
    return pd.concat(parts, axis=1).mean(axis=1, skipna=True).fillna(50)


def group_board(rows: list[dict[str, object]], keys: list[str]) -> list[dict[str, object]]:
    groups: dict[tuple[str, ...], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        groups[tuple(clean(row.get(key)) for key in keys)].append(row)
    result = []
    for key, members in sorted(groups.items()):
        scores = [num(row.get("momentum_leadership_score")) for row in members]
        valid = [score for score in scores if score is not None]
        result.append({
            **dict(zip(keys, key)), "ticker_count": len(members),
            "scored_count": len(valid), "average_momentum_leadership_score": f"{sum(valid) / len(valid):.10f}" if valid else "",
            "research_only": "TRUE",
        })
    return result


def run_stage(root: Path) -> dict[str, object]:
    root = root.resolve()
    out = root / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    before = protected_hashes(root)
    discovery_rows, _ = read_csv(root / DISCOVERY_REL)
    eligible_rows, _ = read_csv(root / ELIGIBLE_DISCOVERY_REL)
    r1_rows, _ = read_csv(root / R1_POOL_REL)
    forced_discovery, _ = read_csv(root / FORCED_DISCOVERY_REL)
    r1 = {clean(row.get("ticker")).upper(): row for row in r1_rows}
    forced_source = {clean(row.get("ticker")).upper(): row for row in forced_discovery}
    tickers = {clean(row.get("ticker")).upper() for row in discovery_rows}
    metrics, price_rows_used = load_metrics(root / PRICE_REL, tickers)
    benchmarks = {ticker: metrics.get(ticker, {}) for ticker in ("SPY", "QQQ", "SMH", "SOXX", "DRAM")}

    records: list[dict[str, object]] = []
    for discovery in discovery_rows:
        ticker = clean(discovery.get("ticker")).upper()
        meta = r1.get(ticker, {})
        metric = metrics.get(ticker, {})
        eligible = tf(discovery.get("eligible_for_unified_pool")) == "TRUE"
        forced_only = tf(discovery.get("entered_by_forced_audit_only")) == "TRUE"
        sufficient = eligible and not forced_only and int(metric.get("history_rows") or 0) >= 60
        row: dict[str, object] = {
            "ticker": ticker, "as_of_date": metric.get("as_of_date", ""),
            "instrument_type": clean(discovery.get("instrument_type") or meta.get("instrument_type") or "STOCK"),
            "asset_class": clean(meta.get("asset_class")), "theme": clean(meta.get("theme")),
            "underlying_index": clean(meta.get("underlying_index")),
            "leverage_multiplier": clean(meta.get("leverage_multiplier") or "1"),
            "direction": clean(meta.get("direction") or "LONG"),
            "is_inverse": tf(meta.get("is_inverse")), "is_daily_reset": tf(meta.get("is_daily_reset")),
            "is_leveraged": tf(meta.get("is_leveraged")), "selection_lane": clean(meta.get("selection_lane")),
            "source_membership": clean(discovery.get("source_membership")),
            "entered_by_existing_candidate_universe": tf(discovery.get("entered_by_existing_candidate_universe")),
            "entered_by_price_universe_discovery": tf(discovery.get("entered_by_price_universe_discovery")),
            "entered_by_relative_strength_discovery": tf(discovery.get("entered_by_relative_strength_discovery")),
            "entered_by_theme_discovery": tf(discovery.get("entered_by_theme_discovery")),
            "entered_by_etf_seed": tf(discovery.get("entered_by_etf_seed")),
            "entered_by_forced_audit_only": tf(forced_only),
            "objective_discovery_admission_reason": clean(forced_source.get(ticker, {}).get("objective_admission_reason"))
            or clean(discovery.get("source_membership")),
            "eligible_for_unified_pool": tf(eligible), "price_available": tf(bool(metric)),
            "volume_available": tf(metric.get("volume_available", False)),
            "latest_price_date": clean(metric.get("latest_price_date") or discovery.get("latest_price_date")),
            "price_freshness_status": clean(discovery.get("price_freshness_status") or "UNKNOWN"),
            "data_sufficiency_status": "SUFFICIENT_FOR_MOMENTUM" if sufficient else "DATA_INSUFFICIENT",
            "market_regime": "UNKNOWN", "risk_off_confirmed": "FALSE", "regime_fallback_used": "TRUE",
            "score_computed": tf(sufficient),
            "score_missing_reason": "" if sufficient else (
                "FORCED_AUDIT_ONLY_NOT_ELIGIBLE" if forced_only else
                "INELIGIBLE_DISCOVERY_ROW" if not eligible else
                f"PRICE_HISTORY_ROWS_{int(metric.get('history_rows') or 0)}_LT_60"
            ),
            "research_only": "TRUE",
        }
        for field in (
            "return_3d", "return_5d", "return_10d", "return_20d", "price_above_ma5",
            "price_above_ma10", "price_above_ma20", "price_above_ma50", "ma5_slope",
            "ma10_slope", "ma20_slope", "rsi", "rsi_slope", "macd_hist",
            "macd_hist_slope", "volume_ratio_5d_vs_20d", "drawdown_from_20d_high",
            "drawdown_from_60d_high",
        ):
            row[field] = text_num(metric.get(field)) if field not in {"price_above_ma5", "price_above_ma10", "price_above_ma20", "price_above_ma50"} else tf(metric.get(field))
        for benchmark in ("SPY", "QQQ", "SMH", "SOXX"):
            for window in (5, 10, 20):
                own = num(metric.get(f"return_{window}d"))
                bench = num(benchmarks[benchmark].get(f"return_{window}d"))
                row[f"excess_return_{window}d_vs_{benchmark}"] = text_num(own - bench) if own is not None and bench is not None else ""
        records.append(row)

    scored_indexes = [index for index, row in enumerate(records) if row["score_computed"] == "TRUE"]
    score_frame = pd.DataFrame([{
        **{field: num(row.get(field)) for field in LEDGER_FIELDS},
        **metrics.get(clean(row["ticker"]), {}),
    } for row in records])
    if scored_indexes:
        subset = score_frame.loc[scored_indexes].copy()
        subset["absolute_momentum_score"] = pct_scores(subset, [
            ("return_3d", True), ("return_5d", True), ("return_10d", True), ("return_20d", True),
            ("ma5_slope", True), ("ma10_slope", True), ("ma20_slope", True),
            ("drawdown_from_20d_high", True), ("drawdown_from_60d_high", True),
        ])
        relative_fields = [
            (f"excess_return_{window}d_vs_{benchmark}", True)
            for benchmark in ("SPY", "QQQ", "SMH", "SOXX") for window in (5, 10, 20)
        ]
        subset["relative_momentum_score"] = pct_scores(subset, relative_fields)
        subset["momentum_acceleration_score"] = pct_scores(subset, [
            ("return_3d_acceleration", True), ("macd_hist_slope", True),
            ("rsi_slope", True), ("volume_ratio_5d_vs_20d", True),
        ])
        subset["trend_persistence_score"] = pct_scores(subset, [
            ("days_above_ma5", True), ("days_above_ma10", True), ("days_above_ma20", True),
            ("higher_high_count", True), ("higher_low_count", True),
            ("drawdown_from_20d_high", True),
        ])
        for index in scored_indexes:
            metric = metrics[clean(records[index]["ticker"])]
            rsi = num(metric.get("rsi")) or 50
            ma20 = num(metric.get("ma20"))
            close = num(metric.get("close"))
            extended = bool(
                rsi >= 72 or (ma20 and close and close / ma20 - 1 >= 0.10)
                or (num(metric.get("return_20d")) or 0) >= 0.20
            )
            deterioration_parts = [
                (num(metric.get("rsi_slope")) or 0) < -3,
                (num(metric.get("macd_hist_slope")) or 0) < 0,
                (num(records[index].get("excess_return_20d_vs_SPY")) or 0) < 0,
                (num(metric.get("return_3d")) or 0) < 0 and (num(metric.get("return_5d")) or 0) > 0,
                not bool(metric.get("price_above_ma5")),
                (num(metric.get("volume_ratio_5d_vs_20d")) or 0) > 1.5 and (num(metric.get("return_3d")) or 0) <= 0,
            ]
            deterioration_count = sum(deterioration_parts)
            deterioration = deterioration_count >= 2
            exhaustion = min(100.0, (30 if extended else 0) + deterioration_count * 15)
            subset.loc[index, "exhaustion_risk_score"] = exhaustion
            records[index]["extension_awareness_flag"] = tf(extended)
            records[index]["deterioration_confirmation_flag"] = tf(deterioration)
            records[index]["high_momentum_not_auto_exhaustion_flag"] = tf(extended and not deterioration)
        subset["momentum_leadership_score"] = (
            .25 * subset["absolute_momentum_score"] + .30 * subset["relative_momentum_score"]
            + .20 * subset["momentum_acceleration_score"] + .15 * subset["trend_persistence_score"]
            - .10 * subset["exhaustion_risk_score"]
        ).clip(0, 100)
        for index in scored_indexes:
            for field in (
                "absolute_momentum_score", "relative_momentum_score",
                "momentum_acceleration_score", "trend_persistence_score",
                "exhaustion_risk_score", "momentum_leadership_score",
            ):
                records[index][field] = f"{float(subset.loc[index, field]):.10f}"

    for row in records:
        if row["score_computed"] != "TRUE":
            row.update({
                "absolute_momentum_score": "", "relative_momentum_score": "",
                "momentum_acceleration_score": "", "trend_persistence_score": "",
                "exhaustion_risk_score": "", "momentum_leadership_score": "",
                "extension_awareness_flag": "FALSE", "deterioration_confirmation_flag": "FALSE",
                "high_momentum_not_auto_exhaustion_flag": "FALSE",
                "momentum_state": "DATA_INSUFFICIENT",
                "chase_permission": "WATCH_ONLY_DATA_WARN", "risk_size_bucket": "WATCH_ONLY",
            })
        else:
            score = num(row["momentum_leadership_score"]) or 0
            relative = num(row["relative_momentum_score"]) or 0
            acceleration = num(row["momentum_acceleration_score"]) or 0
            persistence = num(row["trend_persistence_score"]) or 0
            extended = row["extension_awareness_flag"] == "TRUE"
            deteriorating = row["deterioration_confirmation_flag"] == "TRUE"
            dd20 = num(row["drawdown_from_20d_high"]) or 0
            above10 = row["price_above_ma10"] == "TRUE"
            above20 = row["price_above_ma20"] == "TRUE"
            if extended and deteriorating:
                state = "MOMENTUM_EXHAUSTION"
            elif score >= 70 and relative >= 65 and acceleration >= 60:
                state = "LEADER_ACCELERATING"
            elif score >= 65 and extended and not deteriorating:
                state = "LEADER_EXTENDED_BUT_VALID"
            elif score >= 62 and persistence >= 60:
                state = "LEADER_CONTINUING"
            elif score >= 55 and -0.10 <= dd20 <= -0.02 and (above10 or above20) and relative >= 50:
                state = "LEADER_PULLBACK_BUYABLE"
            elif score < 35:
                state = "NO_MOMENTUM"
            elif relative < 40 or not above20:
                state = "MOMENTUM_DECAY"
            else:
                state = "LEADER_CONTINUING"
            permission = {
                "LEADER_ACCELERATING": "ALLOW_CHASE",
                "LEADER_CONTINUING": "ALLOW_CHASE",
                "LEADER_EXTENDED_BUT_VALID": "ALLOW_SMALL_SIZE_CHASE",
                "LEADER_PULLBACK_BUYABLE": "PRIORITY_ENTRY",
                "MOMENTUM_DECAY": "WAIT_FOR_PULLBACK",
                "MOMENTUM_EXHAUSTION": "BLOCK_CHASE",
                "NO_MOMENTUM": "HOLD_ONLY",
            }[state]
            risk = "NORMAL_SIZE_ALLOWED" if state.startswith("LEADER") else "HALF_SIZE_ONLY" if state == "MOMENTUM_DECAY" else "WATCH_ONLY"
            instrument = clean(row["instrument_type"])
            leverage = abs(num(row["leverage_multiplier"]) or 1)
            if instrument == "STOCK" and state == "LEADER_ACCELERATING" and not extended and (num(row["exhaustion_risk_score"]) or 100) < 30:
                risk = "FULL_SIZE_ALLOWED"
            if instrument == "LEVERAGED_LONG_ETF":
                risk = "HALF_SIZE_ONLY" if leverage <= 2 else "QUARTER_SIZE_ONLY"
            if instrument == "INVERSE_ETF":
                permission, risk = "HEDGE_ONLY", "WATCH_ONLY"
            row.update({"momentum_state": state, "chase_permission": permission, "risk_size_bucket": risk})
        row["tactical_only"] = tf(clean(row["instrument_type"]) in {"LEVERAGED_LONG_ETF", "INVERSE_ETF"})
        row["hedge_only"] = tf(clean(row["instrument_type"]) == "INVERSE_ETF")
        row["daily_reset_risk_flag"] = tf(clean(row["instrument_type"]) in {"LEVERAGED_LONG_ETF", "INVERSE_ETF"})
        row["leverage_decay_risk_flag"] = row["daily_reset_risk_flag"]
        if clean(row["instrument_type"]) == "INVERSE_ETF" and row["risk_off_confirmed"] != "TRUE":
            row["chase_permission"] = "HEDGE_ONLY"
            row["risk_size_bucket"] = "WATCH_ONLY"

    top50 = sorted(
        (row for row in records if row["score_computed"] == "TRUE" and row["entered_by_forced_audit_only"] != "TRUE"),
        key=lambda row: (-(num(row["momentum_leadership_score"]) or -1), clean(row["ticker"])),
    )[:50]
    for rank, row in enumerate(top50, 1):
        row["momentum_rank"] = rank
    top_set = {clean(row["ticker"]) for row in top50}
    write_csv(out / LEDGER_NAME, records, LEDGER_FIELDS)
    write_csv(out / TOP50_NAME, top50, ["momentum_rank", *LEDGER_FIELDS])
    leadership = group_board(records, ["momentum_state", "instrument_type"])
    write_csv(out / LEADERSHIP_NAME, leadership, ["momentum_state", "instrument_type", "ticker_count", "scored_count", "average_momentum_leadership_score", "research_only"])
    chase = group_board(records, ["chase_permission", "risk_size_bucket", "instrument_type"])
    write_csv(out / CHASE_NAME, chase, ["chase_permission", "risk_size_bucket", "instrument_type", "ticker_count", "scored_count", "average_momentum_leadership_score", "research_only"])
    exhaustion_rows = [row for row in records if row["extension_awareness_flag"] == "TRUE" or (num(row["exhaustion_risk_score"]) or 0) >= 50]
    for row in exhaustion_rows:
        row["exhaustion_classification"] = (
            "CONFIRMED_EXHAUSTION" if row["momentum_state"] == "MOMENTUM_EXHAUSTION"
            else "VALID_EXTENSION_NO_DETERIORATION" if row["extension_awareness_flag"] == "TRUE" and row["deterioration_confirmation_flag"] != "TRUE"
            else "DETERIORATION_RISK"
        )
    write_csv(out / EXHAUSTION_NAME, exhaustion_rows, [*LEDGER_FIELDS, "exhaustion_classification"])
    data_warn = [row for row in records if row["score_computed"] != "TRUE" or row["price_freshness_status"] != "FRESH" or row["volume_available"] != "TRUE"]
    write_csv(out / DATA_WARN_NAME, data_warn, LEDGER_FIELDS)

    by_ticker = {clean(row["ticker"]): row for row in records}
    forced_rows = []
    for ticker in FORCED:
        row = by_ticker.get(ticker, {})
        discovery = next((item for item in discovery_rows if clean(item.get("ticker")).upper() == ticker), {})
        forced_rows.append({
            "ticker": ticker, "present_in_discovery_pool": tf(bool(discovery)),
            "present_in_eligible_discovery_pool": tf(any(clean(item.get("ticker")).upper() == ticker for item in eligible_rows)),
            **{field: row.get(field, discovery.get(field, "")) for field in (
                "entered_by_existing_candidate_universe", "entered_by_price_universe_discovery",
                "entered_by_relative_strength_discovery", "entered_by_theme_discovery",
                "entered_by_etf_seed", "entered_by_forced_audit_only",
                "objective_discovery_admission_reason", "eligible_for_unified_pool",
                "instrument_type", "theme", "price_available", "volume_available",
                "latest_price_date", "price_freshness_status",
            )},
            "score_computed": row.get("score_computed", "FALSE"),
            "data_insufficient_reason": row.get("score_missing_reason", ""),
            **{field: row.get(field, "") for field in (
                "absolute_momentum_score", "relative_momentum_score",
                "momentum_acceleration_score", "trend_persistence_score",
                "exhaustion_risk_score", "momentum_leadership_score",
                "momentum_state", "chase_permission", "risk_size_bucket",
            )},
            "in_momentum_top50": tf(ticker in top_set),
            "top50_inclusion_reason": "OBJECTIVE_SCORE_RANK_WITHIN_TOP50" if ticker in top_set else "NOT_IN_OBJECTIVE_TOP50",
            "exclusion_reason": clean(discovery.get("exclusion_reason") or row.get("score_missing_reason")),
            "notes": "Forced audit is diagnostic only; no eligibility, score, or Top50 override.",
            "research_only": "TRUE",
        })
    forced_fields = list(forced_rows[0].keys())
    write_csv(out / FORCED_NAME, forced_rows, forced_fields)

    forced_only = [row for row in records if row["entered_by_forced_audit_only"] == "TRUE"]
    hardcoded = [row for row in forced_only if row["eligible_for_unified_pool"] == "TRUE" or row["score_computed"] == "TRUE" or clean(row["ticker"]) in top_set]
    flow = [{
        "discovery_pool_count": len(discovery_rows), "eligible_discovery_pool_count": len(eligible_rows),
        "scored_count": sum(row["score_computed"] == "TRUE" for row in records),
        "ineligible_count": sum(row["eligible_for_unified_pool"] != "TRUE" for row in records),
        "data_insufficient_count": sum(row["score_computed"] != "TRUE" for row in records),
        "forced_audit_only_count": len(forced_only),
        "forced_audit_only_scored_count": sum(row["score_computed"] == "TRUE" for row in forced_only),
        "forced_audit_only_top50_count": sum(clean(row["ticker"]) in top_set for row in forced_only),
        "hardcoded_inclusion_violation_count": len(hardcoded), "research_only": "TRUE",
    }]
    write_csv(out / FLOW_NAME, flow, list(flow[0].keys()))

    after = protected_hashes(root)
    a0_modified = bool(differences(before["a0"], after["a0"]))
    official_modified = bool(differences(before["official"], after["official"]))
    real_modified = bool(differences(before["real_book"], after["real_book"]))
    broker_modified = bool(differences(before["broker"], after["broker"]))
    lineage_sources = [
        ("v21_057_r2_discovery_pool", root / DISCOVERY_REL, "READ_ONLY"),
        ("v21_057_r2_eligible_discovery_pool", root / ELIGIBLE_DISCOVERY_REL, "READ_ONLY"),
        ("v21_057_r1_unified_pool", root / R1_POOL_REL, "READ_ONLY"),
        ("a0_canonical_control", root / A0_REL, "READ_ONLY_UNMODIFIED" if not a0_modified else "MUTATED"),
        ("historical_ohlcv_price_source", root / PRICE_REL, "READ_ONLY"),
    ]
    lineage = [{
        "source_role": role, "source_path": rel(root, path), "row_count": price_rows_used if role == "historical_ohlcv_price_source" else row_count(path),
        "status": status, "a0_modified": tf(a0_modified), "official_ranking_or_weight_modified": tf(official_modified),
        "research_only": "TRUE", "notes": "A0 rank/score lineage: JOINED_FROM_CURRENT_V18_RANKING_SOURCE" if role == "a0_canonical_control" else "No source mutation.",
    } for role, path, status in lineage_sources]
    lineage.append({
        "source_role": "market_regime_fallback", "source_path": "", "row_count": 0,
        "status": "FALLBACK_USED", "a0_modified": tf(a0_modified),
        "official_ranking_or_weight_modified": tf(official_modified), "research_only": "TRUE",
        "notes": "No explicit current risk-off confirmation; market_regime=UNKNOWN.",
    })
    write_csv(out / LINEAGE_NAME, lineage, ["source_role", "source_path", "row_count", "status", "a0_modified", "official_ranking_or_weight_modified", "research_only", "notes"])

    high_auto = sum(
        row["momentum_state"] == "MOMENTUM_EXHAUSTION" and row["deterioration_confirmation_flag"] != "TRUE"
        for row in records
    )
    leveraged_full = sum(
        row["instrument_type"] == "LEVERAGED_LONG_ETF" and row["risk_size_bucket"] == "FULL_SIZE_ALLOWED"
        for row in records
    )
    inverse_bad = sum(
        row["instrument_type"] == "INVERSE_ETF"
        and (row["chase_permission"] != "HEDGE_ONLY" or row["risk_size_bucket"] not in {"WATCH_ONLY", "BLOCKED"})
        for row in records
    )
    forced_missing = len(set(FORCED) - {clean(row["ticker"]) for row in forced_rows})
    state_counts = Counter(clean(row["momentum_state"]) for row in records)
    type_counts = Counter(clean(row["instrument_type"]) for row in records if row["score_computed"] == "TRUE")
    critical_risk = high_auto or leveraged_full or inverse_bad
    if a0_modified or official_modified or real_modified or broker_modified:
        final, decision = FAIL_MUTATION, "STOP_AND_RESTORE_FORBIDDEN_MUTATION"
    elif forced_missing:
        final, decision = BLOCKED_STATUS, "FIX_FORCED_MOMENTUM_AUDIT_BEFORE_ABCD"
    elif hardcoded:
        final, decision = FAIL_HARDCODED, "REPAIR_DISCOVERY_TO_REMOVE_FORCED_INCLUSION"
    elif high_auto:
        final, decision = FAIL_EXHAUSTION, "REPAIR_HIGH_MOMENTUM_EXHAUSTION_LOGIC"
    elif critical_risk:
        final, decision = FAIL_RISK, "REPAIR_LEVERAGED_OR_INVERSE_RISK_CONTROLS"
    elif any(row["score_computed"] != "TRUE" for row in records):
        final, decision = PARTIAL_STATUS, "MOMENTUM_TRACKER_READY_FOR_ABCD_WITH_DATA_WARN_REVIEW"
    else:
        final, decision = PASS_STATUS, "MOMENTUM_TRACKER_READY_FOR_V21_059_ABCD_EXPERIMENT_HARNESS"
    summary = {
        "FINAL_STATUS": final, "DECISION": decision, "stage_id": STAGE_ID, "research_only": True,
        "total_discovery_pool_count": len(discovery_rows), "eligible_discovery_pool_count": len(eligible_rows),
        "total_unified_pool_count": len(r1_rows),
        "eligible_unified_pool_count": sum(tf(row.get("eligible_for_unified_pool")) == "TRUE" for row in r1_rows),
        "scored_count": sum(row["score_computed"] == "TRUE" for row in records),
        "data_insufficient_count": sum(row["score_computed"] != "TRUE" for row in records),
        "missing_price_count": sum(row["price_available"] != "TRUE" for row in records),
        "stale_price_count": sum(row["price_freshness_status"] == "STALE_WARN" for row in records),
        "stock_scored_count": type_counts["STOCK"], "core_etf_scored_count": type_counts["CORE_ETF"],
        "sector_etf_scored_count": type_counts["SECTOR_ETF"], "thematic_etf_scored_count": type_counts["THEMATIC_ETF"],
        "leveraged_long_etf_scored_count": type_counts["LEVERAGED_LONG_ETF"], "inverse_etf_scored_count": type_counts["INVERSE_ETF"],
        "forced_audit_count": len(forced_rows), "forced_audit_missing_count": forced_missing,
        "forced_audit_only_count": len(forced_only),
        "forced_audit_only_scored_count": flow[0]["forced_audit_only_scored_count"],
        "forced_audit_only_top50_count": flow[0]["forced_audit_only_top50_count"],
        "hardcoded_inclusion_violation_count": len(hardcoded),
        "top_momentum_leaders": [clean(row["ticker"]) for row in top50[:10]],
        "leader_accelerating_count": state_counts["LEADER_ACCELERATING"],
        "leader_continuing_count": state_counts["LEADER_CONTINUING"],
        "leader_extended_but_valid_count": state_counts["LEADER_EXTENDED_BUT_VALID"],
        "leader_pullback_buyable_count": state_counts["LEADER_PULLBACK_BUYABLE"],
        "momentum_decay_count": state_counts["MOMENTUM_DECAY"],
        "momentum_exhaustion_count": state_counts["MOMENTUM_EXHAUSTION"],
        "high_momentum_auto_exhaustion_violation_count": high_auto,
        "leveraged_full_size_violation_count": leveraged_full,
        "inverse_non_hedge_violation_count": inverse_bad,
        "a0_modified": a0_modified, "official_mutation_detected": official_modified,
        "real_book_mutation_detected": real_modified, "broker_mutation_detected": broker_modified,
        "market_regime": "UNKNOWN", "regime_fallback_used": True,
        "next_recommended_stage": "V21.059_ABCD_EXPERIMENT_HARNESS" if final in {PASS_STATUS, PARTIAL_STATUS} else "REPAIR_V21_058_R1_MOMENTUM_TRACKER",
    }
    write_json(out / SUMMARY_NAME, summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    summary = run_stage(args.root)
    print(json.dumps(summary, indent=2))
    return 1 if clean(summary["FINAL_STATUS"]).startswith(("FAIL_", "BLOCKED_")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
