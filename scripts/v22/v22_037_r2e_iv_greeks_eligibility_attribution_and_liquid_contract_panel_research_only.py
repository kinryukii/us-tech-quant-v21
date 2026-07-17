from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REVISION = "V22.037_R2E"
OUTPUT_DIR_NAME = "V22.037_R2E_IV_GREEKS_ELIGIBILITY_ATTRIBUTION_AND_LIQUID_CONTRACT_PANEL_RESEARCH_ONLY"
PASS_STATUS = "PASS_V22_037_R2E_ELIGIBILITY_ATTRIBUTED_AND_LIQUID_PANEL_READY_RESEARCH_ONLY"
WARN_STATUS = "WARN_V22_037_R2E_ELIGIBILITY_ATTRIBUTED_BUT_LIQUID_PANEL_EMPTY_RESEARCH_ONLY"
FAIL_NO_BASE_ELIGIBLE = "FAIL_V22_037_R2E_NO_BASE_RESEARCH_ELIGIBLE_ROWS"
FAIL_INPUT = "FAIL_V22_037_R2E_REQUIRED_INPUT_NOT_FOUND"
FAIL_EXCEPTION = "FAIL_V22_037_R2E_UNHANDLED_EXCEPTION"
PASS_DECISION = "LIQUID_IV_GREEKS_RESEARCH_PANEL_READY_FILTERED_RESEARCH_ONLY"
WARN_DECISION = "ELIGIBILITY_ATTRIBUTION_AVAILABLE_REVIEW_PANEL_POLICY_RESEARCH_ONLY"
FAIL_DECISION = "LIQUID_IV_GREEKS_PANEL_BLOCKED_RESEARCH_ONLY"

RESEARCH_ONLY = True
OFFICIAL_ADOPTION_ALLOWED = False
BROKER_ACTION_ALLOWED = False
UTC = timezone.utc

ATTRIBUTION_FIELDS = [
    "source_row_number", "contract_code", "underlying", "option_type", "expiry_timestamp_et",
    "days_to_expiry", "dte_bucket", "strike", "underlying_price", "moneyness_spot_over_strike",
    "abs_log_moneyness", "bid", "ask", "option_market_price", "spread_absolute",
    "spread_ratio_mid", "volume", "open_interest", "activity_data_status",
    "quote_alignment_seconds", "timestamp_alignment_pass", "valuation_timestamp_trust_pass",
    "no_arbitrage_pass", "iv_solver_converged", "greeks_invariant_pass", "quote_quality_pass",
    "synthetic_iv", "delta", "gamma", "theta_per_day", "vega_per_1vol_point", "rho_per_1pct",
    "quality_tier", "eligible_for_research_ranking", "base_validation_error_count",
    "base_validation_warn_count", "base_failure_reasons", "base_warning_reasons",
    "panel_policy_pass", "panel_exclusion_count", "panel_exclusion_reasons", "liquidity_score",
    "liquid_panel_eligible", "panel_rank_underlying", "panel_rank_underlying_dte_bucket",
    "research_only", "official_adoption_allowed", "broker_action_allowed", "source_r2d_run_dir",
]

PANEL_FIELDS = [
    "panel_rank_underlying", "panel_rank_underlying_dte_bucket", "liquidity_score",
    "underlying", "contract_code", "option_type", "expiry_timestamp_et", "days_to_expiry",
    "dte_bucket", "strike", "underlying_price", "moneyness_spot_over_strike",
    "abs_log_moneyness", "bid", "ask", "option_market_price", "spread_absolute",
    "spread_ratio_mid", "volume", "open_interest", "quote_alignment_seconds", "synthetic_iv",
    "delta", "gamma", "theta_per_day", "vega_per_1vol_point", "rho_per_1pct", "quality_tier",
    "eligible_for_research_ranking", "liquid_panel_eligible", "research_only",
    "official_adoption_allowed", "broker_action_allowed",
]

FAILURE_SUMMARY_FIELDS = [
    "stage", "severity", "reason", "affected_row_count", "affected_row_ratio", "underlying_count",
    "research_only", "official_adoption_allowed", "broker_action_allowed",
]

SUMMARY_GROUP_FIELDS = [
    "group_type", "group_value", "input_row_count", "timestamp_aligned_count",
    "base_research_eligible_count", "base_research_eligible_ratio", "liquid_panel_count",
    "liquid_panel_ratio", "zero_dte_base_eligible_count", "nonzero_dte_base_eligible_count",
    "median_spread_ratio", "median_alignment_seconds", "median_synthetic_iv", "primary_base_failure",
    "primary_panel_exclusion", "research_only", "official_adoption_allowed", "broker_action_allowed",
]

TOPN_FIELDS = PANEL_FIELDS


@dataclass(frozen=True)
class Config:
    min_dte: float = 0.0
    max_dte: float = 45.0
    max_abs_log_moneyness: float = 0.08
    max_spread_ratio: float = 0.15
    max_spread_absolute: float = 0.50
    min_option_market_price: float = 0.10
    min_bid: float = 0.05
    min_abs_delta: float = 0.15
    max_abs_delta: float = 0.85
    min_volume: float = 1.0
    min_open_interest: float = 10.0
    require_activity: bool = False
    top_n_per_underlying: int = 20
    max_alignment_seconds_for_score: float = 15.0


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "1", "yes", "y"}


def bool_text(value: bool) -> str:
    return "True" if value else "False"


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    text = str(value).strip().replace(",", "")
    if not text or text.lower() in {"nan", "none", "null", "na", "n/a", "--"}:
        return None
    if text.endswith("%"):
        text = text[:-1]
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def safe_int(value: Any) -> int | None:
    number = safe_float(value)
    return int(number) if number is not None else None


def median(values: Iterable[float | None]) -> float | None:
    clean = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return statistics.median(clean) if clean else None


def ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def dte_bucket(days_to_expiry: float | None) -> str:
    if days_to_expiry is None:
        return "UNKNOWN"
    if days_to_expiry < 0:
        return "EXPIRED"
    if days_to_expiry < 1:
        return "0DTE"
    if days_to_expiry <= 7:
        return "1_7DTE"
    if days_to_expiry <= 30:
        return "8_30DTE"
    if days_to_expiry <= 45:
        return "31_45DTE"
    return "GT45DTE"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})
    os.replace(temp, path)


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temp, path)


def discover_r2d_run(repo_root: Path, explicit_run_dir: Path | None = None) -> Path:
    if explicit_run_dir is not None:
        candidate = explicit_run_dir.expanduser().resolve()
        if not candidate.exists():
            raise FileNotFoundError(f"R2D run directory does not exist: {candidate}")
        return candidate
    root = repo_root / "outputs" / "v22" / "V22.037_R2D_MULTI_UNDERLYING_RATE_LIMITED_SAME_SNAPSHOT_CAPTURE_AND_IV_GREEKS_VALIDATION_RESEARCH_ONLY"
    pointer = root / "latest_run.json"
    if pointer.exists():
        payload = json.loads(pointer.read_text(encoding="utf-8"))
        output_dir = payload.get("output_dir")
        if output_dir and Path(output_dir).exists():
            return Path(output_dir).resolve()
    runs_dir = root / "runs"
    candidates = sorted((p for p in runs_dir.glob("v22_037_r2d_*") if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates:
        return candidates[0].resolve()
    raise FileNotFoundError(f"No V22.037 R2D run found under: {root}")


def required_paths(run_dir: Path) -> dict[str, Path]:
    return {
        "capture": run_dir / "option_underlying_same_snapshot_capture_research_only.csv",
        "recalculated": run_dir / "iv_greeks_r2b_child" / "option_iv_greeks_recalculated_research_only.csv",
        "validation": run_dir / "iv_greeks_r2b_child" / "option_iv_greeks_quality_validation.csv",
        "r2d_summary": run_dir / "v22_037_r2d_summary.json",
    }


def normalize_contract_code(row: Mapping[str, Any]) -> str:
    return str(row.get("contract_code") or row.get("option_code") or "").strip().upper()


def build_validation_index(validation_rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, list[str]]]:
    result: dict[str, dict[str, list[str]]] = defaultdict(lambda: {"ERROR": [], "WARN": []})
    for row in validation_rows:
        if bool_value(row.get("passed")):
            continue
        code = normalize_contract_code(row)
        if not code or code == "GLOBAL":
            continue
        severity = str(row.get("severity") or "WARN").strip().upper()
        if severity not in {"ERROR", "WARN"}:
            severity = "WARN"
        reason = str(row.get("check_name") or "UNKNOWN_CHECK").strip()
        if reason and reason not in result[code][severity]:
            result[code][severity].append(reason)
    return result


def activity_status(volume: float | None, open_interest: float | None) -> str:
    if volume is None and open_interest is None:
        return "MISSING"
    if volume is None or open_interest is None:
        return "PARTIAL"
    return "AVAILABLE"


def activity_pass(volume: float | None, open_interest: float | None, config: Config) -> bool:
    volume_ok = volume is not None and volume >= config.min_volume
    oi_ok = open_interest is not None and open_interest >= config.min_open_interest
    return volume_ok or oi_ok


def panel_policy_reasons(row: Mapping[str, Any], config: Config) -> list[str]:
    reasons: list[str] = []
    if not bool_value(row.get("eligible_for_research_ranking")):
        reasons.append("BASE_NOT_RESEARCH_ELIGIBLE")
        return reasons
    dte = safe_float(row.get("days_to_expiry"))
    bid = safe_float(row.get("bid"))
    ask = safe_float(row.get("ask"))
    market_price = safe_float(row.get("option_market_price"))
    spread_ratio = safe_float(row.get("spread_ratio_mid"))
    spread_abs = safe_float(row.get("spread_absolute"))
    log_moneyness = safe_float(row.get("log_moneyness"))
    delta = safe_float(row.get("delta"))
    volume = safe_float(row.get("volume"))
    oi = safe_float(row.get("open_interest"))

    if dte is None or dte < config.min_dte or dte > config.max_dte:
        reasons.append("DTE_OUTSIDE_POLICY")
    if log_moneyness is None or abs(log_moneyness) > config.max_abs_log_moneyness:
        reasons.append("MONEYNESS_OUTSIDE_POLICY")
    if bid is None or bid < config.min_bid:
        reasons.append("BID_BELOW_MINIMUM")
    if ask is None or bid is None or ask <= bid:
        reasons.append("BID_ASK_NOT_EXECUTABLE")
    if market_price is None or market_price < config.min_option_market_price:
        reasons.append("OPTION_PRICE_BELOW_MINIMUM")
    if spread_ratio is None or spread_ratio > config.max_spread_ratio:
        reasons.append("SPREAD_RATIO_ABOVE_LIMIT")
    if spread_abs is None or spread_abs > config.max_spread_absolute:
        reasons.append("SPREAD_ABSOLUTE_ABOVE_LIMIT")
    if delta is None or abs(delta) < config.min_abs_delta or abs(delta) > config.max_abs_delta:
        reasons.append("ABS_DELTA_OUTSIDE_POLICY")
    if config.require_activity and not activity_pass(volume, oi, config):
        reasons.append("VOLUME_OPEN_INTEREST_BELOW_POLICY")
    return reasons


def score_row(row: Mapping[str, Any], config: Config) -> float:
    if not bool_value(row.get("eligible_for_research_ranking")):
        return 0.0
    spread = safe_float(row.get("spread_ratio_mid"))
    alignment = safe_float(row.get("quote_alignment_seconds"))
    log_moneyness = safe_float(row.get("log_moneyness"))
    delta = safe_float(row.get("delta"))
    volume = safe_float(row.get("volume")) or 0.0
    oi = safe_float(row.get("open_interest")) or 0.0

    spread_score = 0.0 if spread is None else max(0.0, 1.0 - spread / max(config.max_spread_ratio, 1e-9)) * 30.0
    align_score = 0.0 if alignment is None else max(0.0, 1.0 - alignment / max(config.max_alignment_seconds_for_score, 1e-9)) * 25.0
    money_score = 0.0 if log_moneyness is None else max(0.0, 1.0 - abs(log_moneyness) / max(config.max_abs_log_moneyness, 1e-9)) * 20.0
    delta_score = 0.0 if delta is None else max(0.0, 1.0 - abs(abs(delta) - 0.50) / 0.50) * 15.0
    volume_score = min(1.0, math.log1p(max(volume, 0.0)) / math.log1p(1000.0)) * 5.0
    oi_score = min(1.0, math.log1p(max(oi, 0.0)) / math.log1p(5000.0)) * 5.0
    return round(spread_score + align_score + money_score + delta_score + volume_score + oi_score, 6)


def enrich_rows(
    capture_rows: Sequence[Mapping[str, Any]],
    recalc_rows: Sequence[Mapping[str, Any]],
    validation_rows: Sequence[Mapping[str, Any]],
    run_dir: Path,
    config: Config,
) -> list[dict[str, Any]]:
    capture_index = {normalize_contract_code(row): dict(row) for row in capture_rows if normalize_contract_code(row)}
    validation_index = build_validation_index(validation_rows)
    result: list[dict[str, Any]] = []
    for recalc in recalc_rows:
        code = normalize_contract_code(recalc)
        capture = capture_index.get(code, {})
        volume = safe_float(capture.get("volume"))
        oi = safe_float(capture.get("open_interest"))
        errors = validation_index.get(code, {}).get("ERROR", [])
        warns = validation_index.get(code, {}).get("WARN", [])
        days = safe_float(recalc.get("days_to_expiry"))
        log_money = safe_float(recalc.get("log_moneyness"))
        row: dict[str, Any] = {
            **dict(recalc),
            "contract_code": code,
            "volume": volume,
            "open_interest": oi,
            "activity_data_status": activity_status(volume, oi),
            "dte_bucket": dte_bucket(days),
            "abs_log_moneyness": abs(log_money) if log_money is not None else None,
            "base_validation_error_count": len(errors),
            "base_validation_warn_count": len(warns),
            "base_failure_reasons": ";".join(errors),
            "base_warning_reasons": ";".join(warns),
            "research_only": RESEARCH_ONLY,
            "official_adoption_allowed": OFFICIAL_ADOPTION_ALLOWED,
            "broker_action_allowed": BROKER_ACTION_ALLOWED,
            "source_r2d_run_dir": str(run_dir),
        }
        exclusions = panel_policy_reasons(row, config)
        row["panel_policy_pass"] = not exclusions
        row["panel_exclusion_count"] = len(exclusions)
        row["panel_exclusion_reasons"] = ";".join(exclusions)
        row["liquid_panel_eligible"] = not exclusions
        row["liquidity_score"] = score_row(row, config)
        row["panel_rank_underlying"] = ""
        row["panel_rank_underlying_dte_bucket"] = ""
        result.append(row)

    eligible = [row for row in result if bool_value(row.get("liquid_panel_eligible"))]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    grouped_bucket: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in eligible:
        grouped[str(row.get("underlying", ""))].append(row)
        grouped_bucket[(str(row.get("underlying", "")), str(row.get("dte_bucket", "")))].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda r: (-float(r.get("liquidity_score") or 0.0), str(r.get("expiry_timestamp_et", "")), float(safe_float(r.get("strike")) or 0.0)))
        for index, row in enumerate(rows, start=1):
            row["panel_rank_underlying"] = index
    for rows in grouped_bucket.values():
        rows.sort(key=lambda r: (-float(r.get("liquidity_score") or 0.0), str(r.get("expiry_timestamp_et", "")), float(safe_float(r.get("strike")) or 0.0)))
        for index, row in enumerate(rows, start=1):
            row["panel_rank_underlying_dte_bucket"] = index
    return result


def counter_primary(counter: Counter[str]) -> str:
    return counter.most_common(1)[0][0] if counter else ""


def summarize_groups(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: list[tuple[str, str, list[Mapping[str, Any]]]] = []
    by_underlying: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    by_dte: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_underlying[str(row.get("underlying", "UNKNOWN"))].append(row)
        by_dte[str(row.get("dte_bucket", "UNKNOWN"))].append(row)
    groups.extend(("UNDERLYING", key, value) for key, value in sorted(by_underlying.items()))
    groups.extend(("DTE_BUCKET", key, value) for key, value in sorted(by_dte.items()))
    output: list[dict[str, Any]] = []
    for group_type, group_value, items in groups:
        aligned = sum(bool_value(row.get("timestamp_alignment_pass")) for row in items)
        base = [row for row in items if bool_value(row.get("eligible_for_research_ranking"))]
        liquid = [row for row in items if bool_value(row.get("liquid_panel_eligible"))]
        zero = sum(str(row.get("dte_bucket")) == "0DTE" for row in base)
        base_fail = Counter()
        panel_fail = Counter()
        for row in items:
            for reason in str(row.get("base_failure_reasons") or "").split(";"):
                if reason:
                    base_fail[reason] += 1
            for reason in str(row.get("panel_exclusion_reasons") or "").split(";"):
                if reason:
                    panel_fail[reason] += 1
        output.append({
            "group_type": group_type,
            "group_value": group_value,
            "input_row_count": len(items),
            "timestamp_aligned_count": aligned,
            "base_research_eligible_count": len(base),
            "base_research_eligible_ratio": ratio(len(base), len(items)),
            "liquid_panel_count": len(liquid),
            "liquid_panel_ratio": ratio(len(liquid), len(items)),
            "zero_dte_base_eligible_count": zero,
            "nonzero_dte_base_eligible_count": len(base) - zero,
            "median_spread_ratio": median(safe_float(row.get("spread_ratio_mid")) for row in items),
            "median_alignment_seconds": median(safe_float(row.get("quote_alignment_seconds")) for row in items),
            "median_synthetic_iv": median(safe_float(row.get("synthetic_iv")) for row in items),
            "primary_base_failure": counter_primary(base_fail),
            "primary_panel_exclusion": counter_primary(panel_fail),
            "research_only": RESEARCH_ONLY,
            "official_adoption_allowed": OFFICIAL_ADOPTION_ALLOWED,
            "broker_action_allowed": BROKER_ACTION_ALLOWED,
        })
    return output


def failure_summary(rows: Sequence[Mapping[str, Any]], validation_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, str, str]] = Counter()
    underlying_sets: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    code_to_underlying = {normalize_contract_code(row): str(row.get("underlying", "")) for row in rows}
    for validation in validation_rows:
        if bool_value(validation.get("passed")):
            continue
        code = normalize_contract_code(validation)
        if not code or code == "GLOBAL":
            continue
        severity = str(validation.get("severity") or "WARN").upper()
        reason = str(validation.get("check_name") or "UNKNOWN_CHECK")
        key = ("BASE_VALIDATION", severity, reason)
        counts[key] += 1
        underlying_sets[key].add(code_to_underlying.get(code, str(validation.get("underlying", ""))))
    for row in rows:
        for reason in str(row.get("panel_exclusion_reasons") or "").split(";"):
            if not reason:
                continue
            key = ("LIQUID_PANEL_POLICY", "INFO", reason)
            counts[key] += 1
            underlying_sets[key].add(str(row.get("underlying", "")))
    total = len(rows)
    output = []
    for (stage, severity, reason), count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        output.append({
            "stage": stage,
            "severity": severity,
            "reason": reason,
            "affected_row_count": count,
            "affected_row_ratio": ratio(count, total),
            "underlying_count": len({x for x in underlying_sets[(stage, severity, reason)] if x}),
            "research_only": RESEARCH_ONLY,
            "official_adoption_allowed": OFFICIAL_ADOPTION_ALLOWED,
            "broker_action_allowed": BROKER_ACTION_ALLOWED,
        })
    return output


def topn_panel(rows: Sequence[Mapping[str, Any]], top_n: int) -> list[dict[str, Any]]:
    eligible = [dict(row) for row in rows if bool_value(row.get("liquid_panel_eligible"))]
    if top_n <= 0:
        return sorted(eligible, key=lambda r: (str(r.get("underlying", "")), int(safe_int(r.get("panel_rank_underlying")) or 999999)))
    return sorted(
        [row for row in eligible if (safe_int(row.get("panel_rank_underlying")) or 999999) <= top_n],
        key=lambda r: (str(r.get("underlying", "")), int(safe_int(r.get("panel_rank_underlying")) or 999999)),
    )


def policy_payload(config: Config) -> dict[str, Any]:
    return {
        "revision": REVISION,
        "base_requirement": "eligible_for_research_ranking=True from V22.037_R2B child",
        "min_dte": config.min_dte,
        "max_dte": config.max_dte,
        "max_abs_log_moneyness": config.max_abs_log_moneyness,
        "max_spread_ratio": config.max_spread_ratio,
        "max_spread_absolute": config.max_spread_absolute,
        "min_option_market_price": config.min_option_market_price,
        "min_bid": config.min_bid,
        "min_abs_delta": config.min_abs_delta,
        "max_abs_delta": config.max_abs_delta,
        "min_volume": config.min_volume,
        "min_open_interest": config.min_open_interest,
        "require_activity": config.require_activity,
        "top_n_per_underlying": config.top_n_per_underlying,
        "official_adoption_allowed": OFFICIAL_ADOPTION_ALLOWED,
        "broker_action_allowed": BROKER_ACTION_ALLOWED,
    }


def report_text(summary: Mapping[str, Any]) -> str:
    return "\n".join([
        "V22.037 R2E IV/Greeks Eligibility Attribution and Liquid Contract Panel",
        "=" * 78,
        f"Final status: {summary.get('final_status')}",
        f"Final decision: {summary.get('final_decision')}",
        f"Source R2D run: {summary.get('source_r2d_run_dir')}",
        f"Input rows: {summary.get('input_row_count')}",
        f"Timestamp aligned: {summary.get('timestamp_alignment_pass_count')}",
        f"Base research eligible: {summary.get('base_research_eligible_count')}",
        f"Base eligible ratio: {summary.get('base_research_eligible_ratio')}",
        f"0DTE base eligible: {summary.get('zero_dte_base_eligible_count')}",
        f"0DTE concentration: {summary.get('zero_dte_base_eligible_ratio')}",
        f"Liquid panel rows: {summary.get('liquid_panel_count')}",
        f"Liquid panel ratio: {summary.get('liquid_panel_ratio')}",
        f"Underlyings represented: {summary.get('underlying_with_liquid_panel_count')}",
        f"Top-N rows: {summary.get('topn_panel_count')}",
        "",
        "Governance",
        "----------",
        "Research only: True",
        "Official adoption allowed: False",
        "Broker action allowed: False",
        "This module attributes eligibility and creates a stricter research liquidity panel. It does not place orders.",
    ]) + "\n"


def execute(repo_root: Path, output_dir: Path, run_dir: Path, config: Config) -> dict[str, Any]:
    start = utc_now_iso()
    paths = required_paths(run_dir)
    missing = [str(path) for key, path in paths.items() if key != "r2d_summary" and not path.exists()]
    if missing:
        return {
            "revision": REVISION,
            "final_status": FAIL_INPUT,
            "final_decision": FAIL_DECISION,
            "repo_root": str(repo_root),
            "output_dir": str(output_dir),
            "source_r2d_run_dir": str(run_dir),
            "run_start_utc": start,
            "run_end_utc": utc_now_iso(),
            "input_row_count": 0,
            "missing_input_paths": missing,
            "research_only": RESEARCH_ONLY,
            "official_adoption_allowed": OFFICIAL_ADOPTION_ALLOWED,
            "broker_action_allowed": BROKER_ACTION_ALLOWED,
            "error_message": "Required R2D/R2B child input files are missing.",
        }
    capture_rows = read_csv(paths["capture"])
    recalc_rows = read_csv(paths["recalculated"])
    validation_rows = read_csv(paths["validation"])
    rows = enrich_rows(capture_rows, recalc_rows, validation_rows, run_dir, config)
    group_rows = summarize_groups(rows)
    failure_rows = failure_summary(rows, validation_rows)
    panel_rows = sorted(
        [row for row in rows if bool_value(row.get("liquid_panel_eligible"))],
        key=lambda r: (str(r.get("underlying", "")), int(safe_int(r.get("panel_rank_underlying")) or 999999)),
    )
    top_rows = topn_panel(rows, config.top_n_per_underlying)

    base_rows = [row for row in rows if bool_value(row.get("eligible_for_research_ranking"))]
    aligned_count = sum(bool_value(row.get("timestamp_alignment_pass")) for row in rows)
    zero_base = sum(str(row.get("dte_bucket")) == "0DTE" for row in base_rows)
    panel_zero = sum(str(row.get("dte_bucket")) == "0DTE" for row in panel_rows)
    underlyings = sorted({str(row.get("underlying", "")) for row in rows if str(row.get("underlying", ""))})
    panel_underlyings = sorted({str(row.get("underlying", "")) for row in panel_rows if str(row.get("underlying", ""))})

    if not base_rows:
        status, decision = FAIL_NO_BASE_ELIGIBLE, FAIL_DECISION
    elif not panel_rows:
        status, decision = WARN_STATUS, WARN_DECISION
    else:
        status, decision = PASS_STATUS, PASS_DECISION

    output_dir.mkdir(parents=True, exist_ok=True)
    attribution_path = output_dir / "option_iv_greeks_eligibility_attribution.csv"
    panel_path = output_dir / "option_iv_greeks_liquid_contract_panel_research_only.csv"
    topn_path = output_dir / "option_iv_greeks_liquid_contract_topn_by_underlying.csv"
    failure_path = output_dir / "option_iv_greeks_failure_reason_summary.csv"
    group_path = output_dir / "option_iv_greeks_group_summary.csv"
    policy_path = output_dir / "liquid_contract_panel_policy.json"
    summary_path = output_dir / "v22_037_r2e_summary.json"
    report_path = output_dir / "V22.037_R2E_iv_greeks_eligibility_attribution_and_liquid_contract_panel_report.txt"

    write_csv(attribution_path, rows, ATTRIBUTION_FIELDS)
    write_csv(panel_path, panel_rows, PANEL_FIELDS)
    write_csv(topn_path, top_rows, TOPN_FIELDS)
    write_csv(failure_path, failure_rows, FAILURE_SUMMARY_FIELDS)
    write_csv(group_path, group_rows, SUMMARY_GROUP_FIELDS)
    write_json(policy_path, policy_payload(config))

    summary = {
        "revision": REVISION,
        "final_status": status,
        "final_decision": decision,
        "repo_root": str(repo_root),
        "output_dir": str(output_dir),
        "source_r2d_run_dir": str(run_dir),
        "run_start_utc": start,
        "run_end_utc": utc_now_iso(),
        "input_row_count": len(rows),
        "underlying_count": len(underlyings),
        "underlyings": ",".join(underlyings),
        "timestamp_alignment_pass_count": aligned_count,
        "timestamp_alignment_pass_ratio": ratio(aligned_count, len(rows)),
        "base_research_eligible_count": len(base_rows),
        "base_research_eligible_ratio": ratio(len(base_rows), len(rows)),
        "zero_dte_base_eligible_count": zero_base,
        "zero_dte_base_eligible_ratio": ratio(zero_base, len(base_rows)),
        "nonzero_dte_base_eligible_count": len(base_rows) - zero_base,
        "liquid_panel_count": len(panel_rows),
        "liquid_panel_ratio": ratio(len(panel_rows), len(rows)),
        "liquid_panel_conversion_ratio_from_base_eligible": ratio(len(panel_rows), len(base_rows)),
        "liquid_panel_zero_dte_count": panel_zero,
        "liquid_panel_zero_dte_ratio": ratio(panel_zero, len(panel_rows)),
        "underlying_with_liquid_panel_count": len(panel_underlyings),
        "underlyings_with_liquid_panel": ",".join(panel_underlyings),
        "topn_panel_count": len(top_rows),
        "top_n_per_underlying": config.top_n_per_underlying,
        "quality_tier_a_count": sum(str(row.get("quality_tier")) == "A" for row in rows),
        "quality_tier_b_count": sum(str(row.get("quality_tier")) == "B" for row in rows),
        "quality_tier_c_count": sum(str(row.get("quality_tier")) == "C" for row in rows),
        "quality_rejected_count": sum(str(row.get("quality_tier")) == "REJECTED" for row in rows),
        "activity_data_available_count": sum(str(row.get("activity_data_status")) == "AVAILABLE" for row in rows),
        "activity_data_partial_count": sum(str(row.get("activity_data_status")) == "PARTIAL" for row in rows),
        "activity_data_missing_count": sum(str(row.get("activity_data_status")) == "MISSING" for row in rows),
        "research_only": RESEARCH_ONLY,
        "official_adoption_allowed": OFFICIAL_ADOPTION_ALLOWED,
        "broker_action_allowed": BROKER_ACTION_ALLOWED,
        "output_files": {
            "attribution": str(attribution_path),
            "liquid_panel": str(panel_path),
            "topn_panel": str(topn_path),
            "failure_summary": str(failure_path),
            "group_summary": str(group_path),
            "policy": str(policy_path),
            "report": str(report_path),
        },
        "error_message": "",
    }
    write_json(summary_path, summary)
    report_path.write_text(report_text(summary), encoding="utf-8")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="V22.037 R2E eligibility attribution and liquid IV/Greeks contract panel, research only")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--r2d-run-dir", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--min-dte", type=float, default=Config.min_dte)
    parser.add_argument("--max-dte", type=float, default=Config.max_dte)
    parser.add_argument("--max-abs-log-moneyness", type=float, default=Config.max_abs_log_moneyness)
    parser.add_argument("--max-spread-ratio", type=float, default=Config.max_spread_ratio)
    parser.add_argument("--max-spread-absolute", type=float, default=Config.max_spread_absolute)
    parser.add_argument("--min-option-market-price", type=float, default=Config.min_option_market_price)
    parser.add_argument("--min-bid", type=float, default=Config.min_bid)
    parser.add_argument("--min-abs-delta", type=float, default=Config.min_abs_delta)
    parser.add_argument("--max-abs-delta", type=float, default=Config.max_abs_delta)
    parser.add_argument("--min-volume", type=float, default=Config.min_volume)
    parser.add_argument("--min-open-interest", type=float, default=Config.min_open_interest)
    parser.add_argument("--require-activity", action="store_true")
    parser.add_argument("--top-n-per-underlying", type=int, default=Config.top_n_per_underlying)
    parser.add_argument("--execute", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.execute:
        print(json.dumps({
            "revision": REVISION,
            "final_status": "DRY_GUARD_V22_037_R2E_NOT_EXECUTED",
            "research_only": RESEARCH_ONLY,
            "official_adoption_allowed": OFFICIAL_ADOPTION_ALLOWED,
            "broker_action_allowed": BROKER_ACTION_ALLOWED,
        }, indent=2))
        return 0
    repo_root = Path(args.repo_root).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else repo_root / "outputs" / "v22" / OUTPUT_DIR_NAME
    config = Config(
        min_dte=args.min_dte,
        max_dte=args.max_dte,
        max_abs_log_moneyness=args.max_abs_log_moneyness,
        max_spread_ratio=args.max_spread_ratio,
        max_spread_absolute=args.max_spread_absolute,
        min_option_market_price=args.min_option_market_price,
        min_bid=args.min_bid,
        min_abs_delta=args.min_abs_delta,
        max_abs_delta=args.max_abs_delta,
        min_volume=args.min_volume,
        min_open_interest=args.min_open_interest,
        require_activity=args.require_activity,
        top_n_per_underlying=args.top_n_per_underlying,
    )
    summary: dict[str, Any]
    try:
        run_dir = discover_r2d_run(repo_root, Path(args.r2d_run_dir) if args.r2d_run_dir else None)
        summary = execute(repo_root, output_dir, run_dir, config)
    except Exception as exc:  # pragma: no cover - exercised by CLI integration
        output_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "revision": REVISION,
            "final_status": FAIL_EXCEPTION,
            "final_decision": FAIL_DECISION,
            "repo_root": str(repo_root),
            "output_dir": str(output_dir),
            "run_start_utc": utc_now_iso(),
            "run_end_utc": utc_now_iso(),
            "research_only": RESEARCH_ONLY,
            "official_adoption_allowed": OFFICIAL_ADOPTION_ALLOWED,
            "broker_action_allowed": BROKER_ACTION_ALLOWED,
            "error_message": f"{type(exc).__name__}: {exc}",
        }
        write_json(output_dir / "v22_037_r2e_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if str(summary.get("final_status", "")).startswith("FAIL_") else 0


if __name__ == "__main__":
    sys.exit(main())
