from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REVISION = "V22.037_R2F"
OUTPUT_DIR_NAME = "V22.037_R2F_DIRECTION_AWARE_LIQUID_OPTION_CONTRACT_RANKING_AND_NO_TRADE_GATE_RESEARCH_ONLY"
PASS_STATUS = "PASS_V22_037_R2F_DIRECTION_AWARE_RANKING_AND_NO_TRADE_GATE_READY_RESEARCH_ONLY"
WARN_STATUS = "WARN_V22_037_R2F_INPUTS_VALID_BUT_NO_DIRECTION_AWARE_RANKING_ROWS_RESEARCH_ONLY"
FAIL_INPUT = "FAIL_V22_037_R2F_REQUIRED_INPUT_NOT_FOUND"
FAIL_EXCEPTION = "FAIL_V22_037_R2F_UNHANDLED_EXCEPTION"
DECISION_SELECTED_STRICT = "STRICT_DIRECTION_CONTRACT_RANKING_READY_RESEARCH_ONLY"
DECISION_SELECTED_SHADOW = "SHADOW_DIRECTION_CONTRACT_RANKING_READY_NO_BROKER_ACTION_RESEARCH_ONLY"
DECISION_NO_TRADE = "NO_TRADE_GATE_ACTIVE_DIRECTION_FRESHNESS_OR_CONTRACT_BLOCK_RESEARCH_ONLY"
DECISION_EMPTY = "DIRECTION_AWARE_RANKING_BLOCKED_NO_COMPATIBLE_ROWS_RESEARCH_ONLY"

RESEARCH_ONLY = True
OFFICIAL_ADOPTION_ALLOWED = False
BROKER_ACTION_ALLOWED = False
UTC = timezone.utc

DIRECT_UNDERLYINGS = {"QQQ", "SOXX", "SPY", "SMH", "DIA", "SMH", "SOXL", "TQQQ", "SPXL", "UDOW"}
INVERSE_UNDERLYINGS = {"SOXS", "SQQQ", "SPXS", "SDOW"}
SEMICONDUCTOR_UNDERLYINGS = {"SOXX", "SMH", "SOXL", "SOXS"}

RANKING_FIELDS = [
    "gate_mode", "official_gate", "shadow_only", "gate_reason_code", "direction_label_raw",
    "normalized_market_direction", "direction_scope", "direction_scope_source", "direction_source_fresh", "panel_fresh",
    "gate_pass", "gate_block_reasons", "underlying", "required_option_type", "contract_code",
    "expiry_timestamp_et", "contract_unexpired", "minutes_to_expiry", "dte_bucket", "strike",
    "underlying_price", "bid", "ask", "option_market_price", "spread_ratio_mid",
    "quote_alignment_seconds", "volume", "open_interest", "synthetic_iv", "delta", "gamma",
    "theta_per_day", "vega_per_1vol_point", "liquidity_score", "target_abs_delta",
    "liquidity_component", "alignment_component", "spread_component", "delta_component",
    "gamma_theta_component", "activity_component", "direction_aware_score",
    "direction_rank_underlying_bucket", "selection_allowed", "selection_decision",
    "research_only", "official_adoption_allowed", "broker_action_allowed",
]

TOP_FIELDS = [
    "gate_mode", "official_gate", "shadow_only", "direction_label_raw", "normalized_market_direction",
    "direction_scope", "direction_scope_source", "underlying", "required_option_type", "dte_bucket", "contract_code",
    "expiry_timestamp_et", "minutes_to_expiry", "direction_aware_score", "liquidity_score",
    "bid", "ask", "option_market_price", "spread_ratio_mid", "quote_alignment_seconds",
    "volume", "open_interest", "synthetic_iv", "delta", "gamma", "theta_per_day",
    "vega_per_1vol_point", "selection_decision", "research_only", "official_adoption_allowed",
    "broker_action_allowed",
]

NO_TRADE_FIELDS = [
    "gate_mode", "official_gate", "shadow_only", "direction_label_raw", "normalized_market_direction",
    "direction_scope", "direction_scope_source", "underlying", "required_option_type", "direction_source_fresh", "panel_fresh",
    "liquid_contract_count", "matching_option_type_count", "unexpired_matching_count",
    "candidate_ranking_count", "selected_contract_count", "primary_gate_result", "all_gate_reasons",
    "source_reason_code", "research_only", "official_adoption_allowed", "broker_action_allowed",
]

PROVENANCE_FIELDS = ["provenance_key", "provenance_value", "trust_level", "notes"]
DTE_SUMMARY_FIELDS = [
    "gate_mode", "underlying", "normalized_market_direction", "required_option_type", "dte_bucket",
    "compatible_contract_count", "unexpired_contract_count", "gate_pass_contract_count",
    "selected_contract_count", "best_direction_aware_score", "research_only",
    "official_adoption_allowed", "broker_action_allowed",
]


@dataclass(frozen=True)
class Config:
    max_direction_panel_gap_minutes: float = 180.0
    max_panel_age_minutes: float = 30.0
    min_time_to_expiry_minutes: float = 15.0
    top_n_per_underlying_bucket: int = 3
    max_alignment_seconds_for_score: float = 15.0
    max_spread_ratio_for_score: float = 0.15
    target_abs_delta_0dte: float = 0.40
    target_abs_delta_1_7dte: float = 0.50
    target_abs_delta_8_21dte: float = 0.50
    target_abs_delta_22_45dte: float = 0.50



def unique_preserve_order(values):
    """Return non-empty values once, preserving first-seen order."""
    seen = set()
    output = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return output


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "1", "yes", "y"}


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


def parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


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


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temp, path)


def discover_r2e_output(repo_root: Path, explicit_dir: Path | None = None) -> Path:
    if explicit_dir is not None:
        candidate = explicit_dir.expanduser().resolve()
        if not candidate.exists():
            raise FileNotFoundError(f"R2E output directory does not exist: {candidate}")
        return candidate
    candidate = repo_root / "outputs" / "v22" / "V22.037_R2E_IV_GREEKS_ELIGIBILITY_ATTRIBUTION_AND_LIQUID_CONTRACT_PANEL_RESEARCH_ONLY"
    if candidate.exists():
        return candidate.resolve()
    raise FileNotFoundError(f"V22.037 R2E output directory not found: {candidate}")


def discover_v22_042_summary(repo_root: Path, explicit_path: Path | None = None) -> Path:
    if explicit_path is not None:
        candidate = explicit_path.expanduser().resolve()
        if not candidate.exists():
            raise FileNotFoundError(f"V22.042 summary does not exist: {candidate}")
        return candidate
    output_root = repo_root / "outputs" / "v22"
    candidates: list[Path] = []
    if output_root.exists():
        for path in output_root.rglob("*summary*.json"):
            if "V22.042" in str(path.parent) or path.name.lower().startswith("v22_042"):
                candidates.append(path)
    if not candidates:
        raise FileNotFoundError(f"No V22.042 summary found under: {output_root}")
    return max(candidates, key=lambda p: p.stat().st_mtime).resolve()


def required_r2e_paths(output_dir: Path) -> dict[str, Path]:
    return {
        "panel": output_dir / "option_iv_greeks_liquid_contract_panel_research_only.csv",
        "topn": output_dir / "option_iv_greeks_liquid_contract_topn_by_underlying.csv",
        "summary": output_dir / "v22_037_r2e_summary.json",
    }


def normalize_direction(label: Any) -> tuple[str, str]:
    text = str(label or "").strip().upper()
    if not text or text in {"WAIT", "MIXED", "MIXED_OR_WAIT", "NEUTRAL", "UNKNOWN", "NONE"}:
        return "WAIT", "ALL"
    scope = "SEMICONDUCTOR" if "SEMICONDUCTOR" in text or "SEMI" in text else "BROAD"
    if "BEAR" in text or "SHORT" in text:
        return "BEARISH", scope
    if "BULL" in text or "LONG" in text:
        return "BULLISH", scope
    return "WAIT", scope


def underlying_in_scope(underlying: str, scope: str) -> bool:
    symbol = underlying.upper()
    if scope == "SEMICONDUCTOR":
        return symbol in SEMICONDUCTOR_UNDERLYINGS
    if scope in {"BROAD", "ALL"}:
        return True
    return False


def required_option_type(underlying: str, direction: str) -> str:
    symbol = underlying.upper()
    if direction not in {"BULLISH", "BEARISH"}:
        return ""
    inverse = symbol in INVERSE_UNDERLYINGS
    if direction == "BULLISH":
        return "PUT" if inverse else "CALL"
    return "CALL" if inverse else "PUT"


def target_abs_delta(bucket: str, config: Config) -> float:
    if bucket == "0DTE":
        return config.target_abs_delta_0dte
    if bucket == "1_7DTE":
        return config.target_abs_delta_1_7dte
    if bucket in {"8_21DTE", "8_30DTE"}:
        return config.target_abs_delta_8_21dte
    return config.target_abs_delta_22_45dte


def panel_reference_time(rows: Sequence[Mapping[str, Any]]) -> datetime | None:
    values = [parse_datetime(row.get("valuation_timestamp_et") or row.get("option_quote_timestamp_et")) for row in rows]
    clean = [value for value in values if value is not None]
    return max(clean) if clean else None


def derive_panel_reference_time(
    r2e_output_dir: Path,
    panel_rows: Sequence[Mapping[str, Any]],
    r2e_summary: Mapping[str, Any],
) -> tuple[datetime | None, str, str]:
    direct = panel_reference_time(panel_rows)
    if direct is not None:
        return direct, "R2E_PANEL_EXPLICIT_TIMESTAMP", "HIGH"

    source_run = str(r2e_summary.get("source_r2d_run_dir") or "").strip()
    if source_run:
        run_dir = Path(source_run)
        recalc_path = run_dir / "iv_greeks_r2b_child" / "option_iv_greeks_recalculated_research_only.csv"
        if recalc_path.exists():
            recalc_rows = read_csv(recalc_path)
            value = panel_reference_time(recalc_rows)
            if value is not None:
                return value, "R2D_RECALCULATED_EXPLICIT_VALUATION_TIMESTAMP", "HIGH"
        capture_path = run_dir / "option_underlying_same_snapshot_capture_research_only.csv"
        if capture_path.exists():
            capture_rows = read_csv(capture_path)
            value = panel_reference_time(capture_rows)
            if value is not None:
                return value, "R2D_CAPTURE_EXPLICIT_OPTION_TIMESTAMP", "HIGH"
        r2d_summary_path = run_dir / "v22_037_r2d_summary.json"
        if r2d_summary_path.exists():
            payload = json.loads(r2d_summary_path.read_text(encoding="utf-8"))
            value = parse_datetime(payload.get("run_end_utc") or payload.get("run_start_utc"))
            if value is not None:
                return value, "R2D_RUN_TIMESTAMP_FALLBACK", "MEDIUM"

    value = parse_datetime(r2e_summary.get("run_start_utc") or r2e_summary.get("run_end_utc"))
    if value is not None:
        return value, "R2E_RUN_TIMESTAMP_FALLBACK", "LOW"
    return None, "UNAVAILABLE", "MISSING"


def minmax_scores(values: Sequence[float | None]) -> list[float]:
    clean = [value for value in values if value is not None and math.isfinite(value)]
    if not clean:
        return [0.0 for _ in values]
    low, high = min(clean), max(clean)
    if math.isclose(low, high):
        return [100.0 if value is not None else 0.0 for value in values]
    result: list[float] = []
    for value in values:
        if value is None or not math.isfinite(value):
            result.append(0.0)
        else:
            result.append(clamp((value - low) / (high - low) * 100.0))
    return result


def base_components(row: Mapping[str, Any], config: Config) -> dict[str, float]:
    liquidity = clamp(safe_float(row.get("liquidity_score")) or 0.0)
    alignment = safe_float(row.get("quote_alignment_seconds"))
    spread = safe_float(row.get("spread_ratio_mid"))
    volume = max(safe_float(row.get("volume")) or 0.0, 0.0)
    oi = max(safe_float(row.get("open_interest")) or 0.0, 0.0)
    bucket = str(row.get("dte_bucket") or "")
    target = target_abs_delta(bucket, config)
    delta = safe_float(row.get("delta"))
    alignment_component = 0.0 if alignment is None else clamp((1.0 - alignment / max(config.max_alignment_seconds_for_score, 1e-9)) * 100.0)
    spread_component = 0.0 if spread is None else clamp((1.0 - spread / max(config.max_spread_ratio_for_score, 1e-9)) * 100.0)
    delta_component = 0.0 if delta is None else clamp((1.0 - abs(abs(delta) - target) / max(target, 1e-9)) * 100.0)
    volume_component = min(1.0, math.log1p(volume) / math.log1p(1000.0)) * 100.0
    oi_component = min(1.0, math.log1p(oi) / math.log1p(5000.0)) * 100.0
    activity_component = (volume_component + oi_component) / 2.0
    return {
        "liquidity_component": liquidity,
        "alignment_component": alignment_component,
        "spread_component": spread_component,
        "delta_component": delta_component,
        "activity_component": activity_component,
        "target_abs_delta": target,
    }


def gamma_theta_raw(row: Mapping[str, Any]) -> float | None:
    gamma = safe_float(row.get("gamma"))
    theta = safe_float(row.get("theta_per_day"))
    if gamma is None or theta is None:
        return None
    return max(gamma, 0.0) / max(abs(theta), 1e-9)


def score_candidate_groups(rows: list[dict[str, Any]], config: Config) -> None:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row.get("gate_mode")), str(row.get("underlying")), str(row.get("dte_bucket")))].append(row)
    for items in grouped.values():
        gt_scores = minmax_scores([gamma_theta_raw(row) for row in items])
        for row, gamma_theta_component in zip(items, gt_scores):
            components = base_components(row, config)
            row.update(components)
            row["gamma_theta_component"] = round(gamma_theta_component, 6)
            final_score = (
                components["liquidity_component"] * 0.30
                + components["alignment_component"] * 0.20
                + components["spread_component"] * 0.15
                + components["delta_component"] * 0.15
                + gamma_theta_component * 0.10
                + components["activity_component"] * 0.10
            )
            row["direction_aware_score"] = round(final_score, 6)
        items.sort(key=lambda row: (-float(row.get("direction_aware_score") or 0.0), str(row.get("expiry_timestamp_et") or ""), float(safe_float(row.get("strike")) or 0.0)))
        for rank, row in enumerate(items, start=1):
            row["direction_rank_underlying_bucket"] = rank


def mode_rows(summary: Mapping[str, Any], comparison_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if comparison_rows:
        output: list[dict[str, Any]] = []
        for row in comparison_rows:
            output.append({
                "gate_mode": str(row.get("gate_mode") or "UNKNOWN_GATE"),
                "direction_label": str(row.get("direction_label") or "MIXED_OR_WAIT"),
                "wait_state": bool_value(row.get("wait_state")),
                "reason_code": str(row.get("reason_code") or ""),
                "official_gate": bool_value(row.get("official_gate")),
                "shadow_only": bool_value(row.get("shadow_only")),
                "direction_scope_input": str(row.get("direction_scope") or "").strip().upper(),
            })
        return output
    return [{
        "gate_mode": "strict_official_gate",
        "direction_label": str(summary.get("strict_official_final_direction_label") or "MIXED_OR_WAIT"),
        "wait_state": bool_value(summary.get("strict_official_wait_state")),
        "reason_code": str(summary.get("primary_wait_reason_code") or ""),
        "official_gate": True,
        "shadow_only": False,
        "direction_scope_input": "",
    }]


def universe_from_summary(panel_rows: Sequence[Mapping[str, Any]], r2e_summary: Mapping[str, Any]) -> list[str]:
    values = {str(row.get("underlying") or "").strip().upper() for row in panel_rows if str(row.get("underlying") or "").strip()}
    raw = str(r2e_summary.get("underlyings") or "")
    values.update(token.strip().upper() for token in raw.split(",") if token.strip())
    return sorted(values)


def build_outputs(
    panel_rows: Sequence[Mapping[str, Any]],
    r2e_summary: Mapping[str, Any],
    direction_summary: Mapping[str, Any],
    comparison_rows: Sequence[Mapping[str, Any]],
    direction_summary_path: Path,
    now: datetime,
    config: Config,
    panel_ref_override: datetime | None = None,
    panel_ref_source: str = "R2E_PANEL_EXPLICIT_TIMESTAMP",
    panel_ref_trust: str = "HIGH",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    panel_ref = panel_ref_override or panel_reference_time(panel_rows)
    direction_time = datetime.fromtimestamp(direction_summary_path.stat().st_mtime, tz=UTC)
    panel_age_minutes = (now - panel_ref).total_seconds() / 60.0 if panel_ref else math.inf
    direction_panel_gap_minutes = abs((panel_ref - direction_time).total_seconds()) / 60.0 if panel_ref else math.inf
    panel_fresh = panel_ref is not None and -5.0 <= panel_age_minutes <= config.max_panel_age_minutes
    direction_fresh = panel_ref is not None and direction_panel_gap_minutes <= config.max_direction_panel_gap_minutes

    universe = universe_from_summary(panel_rows, r2e_summary)
    by_underlying: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in panel_rows:
        by_underlying[str(row.get("underlying") or "").upper()].append(dict(row))

    rankings: list[dict[str, Any]] = []
    no_trade: list[dict[str, Any]] = []
    modes = mode_rows(direction_summary, comparison_rows)

    for mode in modes:
        normalized_direction, inferred_scope = normalize_direction(mode["direction_label"])
        explicit_scope = str(mode.get("direction_scope_input") or "").strip().upper()
        if explicit_scope in {"ALL", "BROAD", "SEMICONDUCTOR"}:
            scope = explicit_scope
            direction_scope_source = "EXPLICIT_DIRECTION_MODE_INPUT"
        else:
            scope = inferred_scope
            direction_scope_source = "INFERRED_FROM_DIRECTION_LABEL"
        wait_state = bool_value(mode.get("wait_state")) or normalized_direction == "WAIT"
        for underlying in universe:
            required_type = required_option_type(underlying, normalized_direction)
            liquid_rows = by_underlying.get(underlying, [])
            matching = [row for row in liquid_rows if str(row.get("option_type") or "").upper() == required_type] if required_type else []
            unexpired: list[dict[str, Any]] = []
            for row in matching:
                expiry = parse_datetime(row.get("expiry_timestamp_et"))
                minutes_to_expiry = (expiry - now).total_seconds() / 60.0 if expiry else -math.inf
                if minutes_to_expiry >= config.min_time_to_expiry_minutes:
                    unexpired.append(row)

            reasons: list[str] = []
            if wait_state:
                reasons.append("NO_TRADE_DIRECTION_WAIT")
            if not direction_fresh:
                reasons.append("NO_TRADE_DIRECTION_INPUT_STALE")
            if not panel_fresh:
                reasons.append("NO_TRADE_PANEL_STALE")
            if not underlying_in_scope(underlying, scope):
                reasons.append("NO_TRADE_OUTSIDE_DIRECTION_SCOPE")
            if not liquid_rows:
                reasons.append("NO_LIQUID_CONTRACT_AVAILABLE")
            elif required_type and not matching:
                reasons.append("NO_MATCHING_OPTION_TYPE")
            elif matching and not unexpired:
                reasons.append("NO_UNEXPIRED_MATCHING_CONTRACT")
            if not required_type and not wait_state:
                reasons.append("NO_DIRECTION_TO_OPTION_TYPE_MAPPING")

            gate_pass = len(reasons) == 0
            candidate_source = matching
            for source in candidate_source:
                row = dict(source)
                expiry = parse_datetime(row.get("expiry_timestamp_et"))
                minutes_to_expiry = (expiry - now).total_seconds() / 60.0 if expiry else None
                contract_unexpired = minutes_to_expiry is not None and minutes_to_expiry >= config.min_time_to_expiry_minutes
                row.update({
                    "gate_mode": mode["gate_mode"],
                    "official_gate": mode["official_gate"],
                    "shadow_only": mode["shadow_only"],
                    "gate_reason_code": mode.get("reason_code", ""),
                    "direction_label_raw": mode["direction_label"],
                    "normalized_market_direction": normalized_direction,
                    "direction_scope": scope,
                "direction_scope_source": direction_scope_source,
                    "direction_scope_source": direction_scope_source,
                    "direction_source_fresh": direction_fresh,
                    "panel_fresh": panel_fresh,
                    "gate_pass": gate_pass and contract_unexpired,
                    "gate_block_reasons": ";".join(
                        unique_preserve_order(
                            reasons + ([] if contract_unexpired else ["NO_UNEXPIRED_MATCHING_CONTRACT"])
                        )
                    ),
                    "underlying": underlying,
                    "required_option_type": required_type,
                    "contract_unexpired": contract_unexpired,
                    "minutes_to_expiry": round(minutes_to_expiry, 6) if minutes_to_expiry is not None else "",
                    "selection_allowed": False,
                    "selection_decision": "BLOCKED_BY_NO_TRADE_GATE",
                    "research_only": RESEARCH_ONLY,
                    "official_adoption_allowed": OFFICIAL_ADOPTION_ALLOWED,
                    "broker_action_allowed": BROKER_ACTION_ALLOWED,
                })
                rankings.append(row)

            no_trade.append({
                "gate_mode": mode["gate_mode"],
                "official_gate": mode["official_gate"],
                "shadow_only": mode["shadow_only"],
                "direction_label_raw": mode["direction_label"],
                "normalized_market_direction": normalized_direction,
                "direction_scope": scope,
                "underlying": underlying,
                "required_option_type": required_type,
                "direction_source_fresh": direction_fresh,
                "panel_fresh": panel_fresh,
                "liquid_contract_count": len(liquid_rows),
                "matching_option_type_count": len(matching),
                "unexpired_matching_count": len(unexpired),
                "candidate_ranking_count": len(candidate_source),
                "selected_contract_count": 0,
                "primary_gate_result": reasons[0] if reasons else "CANDIDATE_SELECTION_READY_RESEARCH_ONLY",
                "all_gate_reasons": ";".join(reasons),
                "source_reason_code": mode.get("reason_code", ""),
                "research_only": RESEARCH_ONLY,
                "official_adoption_allowed": OFFICIAL_ADOPTION_ALLOWED,
                "broker_action_allowed": BROKER_ACTION_ALLOWED,
            })

    score_candidate_groups(rankings, config)

    top_rows: list[dict[str, Any]] = []
    ranking_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rankings:
        ranking_groups[(str(row.get("gate_mode")), str(row.get("underlying")), str(row.get("dte_bucket")))].append(row)
    for items in ranking_groups.values():
        selectable = [row for row in items if bool_value(row.get("gate_pass")) and bool_value(row.get("contract_unexpired"))]
        selectable.sort(key=lambda row: int(safe_int(row.get("direction_rank_underlying_bucket")) or 999999))
        for row in selectable[: max(config.top_n_per_underlying_bucket, 0)]:
            row["selection_allowed"] = True
            row["selection_decision"] = "TOP_DIRECTION_MATCHED_CONTRACT_SELECTED_RESEARCH_ONLY"
            top_rows.append(dict(row))

    selected_index: dict[tuple[str, str], int] = defaultdict(int)
    for row in top_rows:
        selected_index[(str(row.get("gate_mode")), str(row.get("underlying")))] += 1
    for row in no_trade:
        count = selected_index.get((str(row.get("gate_mode")), str(row.get("underlying"))), 0)
        row["selected_contract_count"] = count
        if count > 0:
            row["primary_gate_result"] = "TOP_CONTRACT_SELECTED_RESEARCH_ONLY"
            row["all_gate_reasons"] = ""

    dte_rows: list[dict[str, Any]] = []
    dte_groups: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rankings:
        key = (
            str(row.get("gate_mode")), str(row.get("underlying")),
            str(row.get("normalized_market_direction")), str(row.get("required_option_type")),
            str(row.get("dte_bucket")),
        )
        dte_groups[key].append(row)
    for key, items in sorted(dte_groups.items()):
        selected = sum(bool_value(row.get("selection_allowed")) for row in items)
        best = max((safe_float(row.get("direction_aware_score")) or 0.0 for row in items), default=0.0)
        dte_rows.append({
            "gate_mode": key[0], "underlying": key[1], "normalized_market_direction": key[2],
            "required_option_type": key[3], "dte_bucket": key[4],
            "compatible_contract_count": len(items),
            "unexpired_contract_count": sum(bool_value(row.get("contract_unexpired")) for row in items),
            "gate_pass_contract_count": sum(bool_value(row.get("gate_pass")) for row in items),
            "selected_contract_count": selected,
            "best_direction_aware_score": round(best, 6),
            "research_only": RESEARCH_ONLY,
            "official_adoption_allowed": OFFICIAL_ADOPTION_ALLOWED,
            "broker_action_allowed": BROKER_ACTION_ALLOWED,
        })

    context = {
        "panel_reference_time_utc": panel_ref.isoformat() if panel_ref else "",
        "panel_reference_time_source": panel_ref_source if panel_ref else "UNAVAILABLE",
        "panel_reference_time_trust": panel_ref_trust if panel_ref else "MISSING",
        "direction_source_time_utc": direction_time.isoformat(),
        "panel_age_minutes": panel_age_minutes,
        "direction_panel_time_gap_minutes": direction_panel_gap_minutes,
        "panel_fresh": panel_fresh,
        "direction_source_fresh": direction_fresh,
        "universe": universe,
        "mode_count": len(modes),
        "strict_official_wait_state": bool_value(direction_summary.get("strict_official_wait_state")),
        "strict_official_direction_label": str(direction_summary.get("strict_official_final_direction_label") or ""),
        "primary_wait_reason_code": str(direction_summary.get("primary_wait_reason_code") or ""),
        "secondary_wait_reason_code": str(direction_summary.get("secondary_wait_reason_code") or ""),
        "shadow_direction_label": str(direction_summary.get("semiconductor_only_shadow_direction_label") or direction_summary.get("relaxed_broad_shadow_direction_label") or ""),
    }
    return rankings, top_rows, no_trade, dte_rows, context


def execute(
    repo_root: Path,
    output_dir: Path,
    r2e_output_dir: Path | None,
    direction_summary_path: Path | None,
    config: Config,
    now_override: datetime | None = None,
) -> dict[str, Any]:
    run_start = utc_now_iso()
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        r2e_dir = discover_r2e_output(repo_root, r2e_output_dir)
        paths = required_r2e_paths(r2e_dir)
        for path in paths.values():
            if not path.exists():
                raise FileNotFoundError(f"Required R2E input missing: {path}")
        direction_path = discover_v22_042_summary(repo_root, direction_summary_path)
        comparison_path = direction_path.parent / "direction_gate_mode_comparison.csv"
        panel_rows = read_csv(paths["panel"])
        r2e_summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
        direction_summary = json.loads(direction_path.read_text(encoding="utf-8"))
        comparison_rows = read_csv(comparison_path) if comparison_path.exists() else []
        now = now_override.astimezone(UTC) if now_override else utc_now()
        panel_ref, panel_ref_source, panel_ref_trust = derive_panel_reference_time(r2e_dir, panel_rows, r2e_summary)
        rankings, top_rows, no_trade_rows, dte_rows, context = build_outputs(
            panel_rows, r2e_summary, direction_summary, comparison_rows, direction_path, now, config,
            panel_ref_override=panel_ref, panel_ref_source=panel_ref_source, panel_ref_trust=panel_ref_trust
        )

        ranking_path = output_dir / "direction_aware_option_contract_ranking.csv"
        top_path = output_dir / "top_contract_by_underlying_direction.csv"
        breakdown_path = output_dir / "contract_score_breakdown.csv"
        no_trade_path = output_dir / "no_trade_gate_audit.csv"
        provenance_path = output_dir / "direction_input_provenance.csv"
        dte_path = output_dir / "dte_bucket_summary.csv"
        policy_path = output_dir / "direction_aware_ranking_policy.json"
        report_path = output_dir / "V22.037_R2F_direction_aware_liquid_option_contract_ranking_and_no_trade_gate_report.txt"
        summary_path = output_dir / "v22_037_r2f_summary.json"

        rankings_sorted = sorted(rankings, key=lambda row: (str(row.get("gate_mode")), str(row.get("underlying")), str(row.get("dte_bucket")), int(safe_int(row.get("direction_rank_underlying_bucket")) or 999999)))
        top_sorted = sorted(top_rows, key=lambda row: (str(row.get("gate_mode")), str(row.get("underlying")), str(row.get("dte_bucket")), int(safe_int(row.get("direction_rank_underlying_bucket")) or 999999)))
        write_csv(ranking_path, rankings_sorted, RANKING_FIELDS)
        write_csv(top_path, top_sorted, TOP_FIELDS)
        write_csv(breakdown_path, rankings_sorted, RANKING_FIELDS)
        write_csv(no_trade_path, no_trade_rows, NO_TRADE_FIELDS)
        write_csv(dte_path, dte_rows, DTE_SUMMARY_FIELDS)

        provenance_rows = [
            {"provenance_key": "r2e_output_dir", "provenance_value": str(r2e_dir), "trust_level": "HIGH", "notes": "Filtered liquid IV/Greeks panel source."},
            {"provenance_key": "r2e_panel_path", "provenance_value": str(paths["panel"]), "trust_level": "HIGH", "notes": "R2E liquid contract panel."},
            {"provenance_key": "direction_summary_path", "provenance_value": str(direction_path), "trust_level": "MEDIUM", "notes": "Latest discovered V22.042 summary."},
            {"provenance_key": "direction_mode_comparison_path", "provenance_value": str(comparison_path), "trust_level": "MEDIUM" if comparison_path.exists() else "MISSING", "notes": "Gate modes and reason codes."},
            {"provenance_key": "panel_reference_time_utc", "provenance_value": context["panel_reference_time_utc"], "trust_level": context["panel_reference_time_trust"], "notes": context["panel_reference_time_source"]},
            {"provenance_key": "direction_source_time_utc", "provenance_value": context["direction_source_time_utc"], "trust_level": "LOW", "notes": "Filesystem modification time; V22.042 summary has no explicit market timestamp."},
            {"provenance_key": "direction_panel_time_gap_minutes", "provenance_value": context["direction_panel_time_gap_minutes"], "trust_level": "DERIVED", "notes": "Absolute time gap used by stale-direction guard."},
            {"provenance_key": "runtime_utc", "provenance_value": now.isoformat(), "trust_level": "HIGH", "notes": "Runtime used for panel freshness and expiry guards."},
        ]
        write_csv(provenance_path, provenance_rows, PROVENANCE_FIELDS)

        policy = {
            "revision": REVISION,
            "max_direction_panel_gap_minutes": config.max_direction_panel_gap_minutes,
            "max_panel_age_minutes": config.max_panel_age_minutes,
            "min_time_to_expiry_minutes": config.min_time_to_expiry_minutes,
            "top_n_per_underlying_bucket": config.top_n_per_underlying_bucket,
            "weights": {
                "liquidity_component": 0.30,
                "alignment_component": 0.20,
                "spread_component": 0.15,
                "delta_component": 0.15,
                "gamma_theta_component": 0.10,
                "activity_component": 0.10,
            },
            "direction_mapping": {
                "BULLISH_DIRECT": "CALL", "BEARISH_DIRECT": "PUT",
                "BULLISH_INVERSE": "PUT", "BEARISH_INVERSE": "CALL",
                "WAIT": "NO_TRADE",
            },
            "semiconductor_scope": sorted(SEMICONDUCTOR_UNDERLYINGS),
            "direct_underlyings": sorted(DIRECT_UNDERLYINGS),
            "direction_scope_resolution": {
                "allowed_scopes": ["ALL", "BROAD", "SEMICONDUCTOR"],
                "precedence": [
                    "EXPLICIT_DIRECTION_MODE_INPUT",
                    "INFERRED_FROM_DIRECTION_LABEL",
                ],
                "explicit_input_field": "direction_scope",
                "fallback_rule": "INFER_SCOPE_FROM_DIRECTION_LABEL",
                "current_behavior_change": False,
            },
            "inverse_underlyings": sorted(INVERSE_UNDERLYINGS),
            "policy_role": "GENERATED_AUDIT_SNAPSHOT",
            "policy_is_input": False,
            "runtime_configuration_source": "PYTHON_CONSTANTS_AND_DIRECTION_MODE_INPUT",
            "candidate_ranking_count_definition": "DIRECTION_COMPATIBLE_ROWS_INCLUDING_EXPIRED_FOR_AUDIT",
            "gate_block_reasons_deduplicated": True,
            "research_only": True,
            "official_adoption_allowed": False,
            "broker_action_allowed": False,
        }
        write_json(policy_path, policy)

        strict_selected = sum(bool_value(row.get("official_gate")) for row in top_rows)
        shadow_selected = sum(bool_value(row.get("shadow_only")) for row in top_rows)
        if strict_selected > 0:
            decision = DECISION_SELECTED_STRICT
        elif shadow_selected > 0:
            decision = DECISION_SELECTED_SHADOW
        elif rankings:
            decision = DECISION_NO_TRADE
        else:
            decision = DECISION_EMPTY
        status = PASS_STATUS if rankings or no_trade_rows else WARN_STATUS

        summary: dict[str, Any] = {
            "revision": REVISION,
            "run_start_utc": run_start,
            "run_end_utc": utc_now_iso(),
            "repo_root": str(repo_root),
            "source_r2e_output_dir": str(r2e_dir),
            "source_direction_summary_path": str(direction_path),
            "source_direction_mode_comparison_path": str(comparison_path) if comparison_path.exists() else "",
            "final_status": status,
            "final_decision": decision,
            "error_message": "",
            "panel_row_count": len(panel_rows),
            "underlying_count": len(context["universe"]),
            "underlyings": ",".join(context["universe"]),
            "direction_gate_mode_count": context["mode_count"],
            "panel_reference_time_utc": context["panel_reference_time_utc"],
            "panel_reference_time_source": context["panel_reference_time_source"],
            "panel_reference_time_trust": context["panel_reference_time_trust"],
            "panel_age_minutes": context["panel_age_minutes"],
            "panel_fresh": context["panel_fresh"],
            "direction_source_time_utc": context["direction_source_time_utc"],
            "direction_panel_time_gap_minutes": context["direction_panel_time_gap_minutes"],
            "direction_source_fresh": context["direction_source_fresh"],
            "strict_official_wait_state": context["strict_official_wait_state"],
            "strict_official_direction_label": context["strict_official_direction_label"],
            "primary_wait_reason_code": context["primary_wait_reason_code"],
            "secondary_wait_reason_code": context["secondary_wait_reason_code"],
            "shadow_direction_label": context["shadow_direction_label"],
            "direction_compatible_ranking_row_count": len(rankings),
            "selected_contract_count": len(top_rows),
            "strict_official_selected_contract_count": strict_selected,
            "shadow_selected_contract_count": shadow_selected,
            "no_trade_audit_row_count": len(no_trade_rows),
            "no_trade_active_count": sum(str(row.get("primary_gate_result")) != "TOP_CONTRACT_SELECTED_RESEARCH_ONLY" for row in no_trade_rows),
            "research_only": RESEARCH_ONLY,
            "official_adoption_allowed": OFFICIAL_ADOPTION_ALLOWED,
            "broker_action_allowed": BROKER_ACTION_ALLOWED,
            "output_dir": str(output_dir),
            "output_files": {
                "ranking": str(ranking_path),
                "top_contract": str(top_path),
                "score_breakdown": str(breakdown_path),
                "no_trade_audit": str(no_trade_path),
                "direction_provenance": str(provenance_path),
                "dte_summary": str(dte_path),
                "policy": str(policy_path),
                "report": str(report_path),
            },
        }
        report_lines = [
            "V22.037 R2F DIRECTION-AWARE LIQUID OPTION CONTRACT RANKING AND NO-TRADE GATE",
            f"final_status={status}",
            f"final_decision={decision}",
            f"panel_row_count={len(panel_rows)}",
            f"panel_fresh={context['panel_fresh']}",
            f"direction_source_fresh={context['direction_source_fresh']}",
            f"strict_official_wait_state={context['strict_official_wait_state']}",
            f"ranking_row_count={len(rankings)}",
            f"selected_contract_count={len(top_rows)}",
            f"strict_official_selected_contract_count={strict_selected}",
            f"shadow_selected_contract_count={shadow_selected}",
            "research_only=True",
            "official_adoption_allowed=False",
            "broker_action_allowed=False",
        ]
        report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
        write_json(summary_path, summary)
        return summary
    except FileNotFoundError as exc:
        summary = {
            "revision": REVISION, "run_start_utc": run_start, "run_end_utc": utc_now_iso(),
            "repo_root": str(repo_root), "final_status": FAIL_INPUT, "final_decision": DECISION_EMPTY,
            "error_message": str(exc), "research_only": True, "official_adoption_allowed": False,
            "broker_action_allowed": False, "output_dir": str(output_dir),
        }
        write_json(output_dir / "v22_037_r2f_summary.json", summary)
        return summary
    except Exception as exc:  # pragma: no cover - defensive boundary
        summary = {
            "revision": REVISION, "run_start_utc": run_start, "run_end_utc": utc_now_iso(),
            "repo_root": str(repo_root), "final_status": FAIL_EXCEPTION, "final_decision": DECISION_EMPTY,
            "error_message": f"{type(exc).__name__}: {exc}", "research_only": True,
            "official_adoption_allowed": False, "broker_action_allowed": False,
            "output_dir": str(output_dir),
        }
        write_json(output_dir / "v22_037_r2f_summary.json", summary)
        return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="V22.037 R2F direction-aware option ranking and no-trade gate (research only).")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--r2e-output-dir")
    parser.add_argument("--direction-summary-path")
    parser.add_argument("--max-direction-panel-gap-minutes", type=float, default=180.0)
    parser.add_argument("--max-panel-age-minutes", type=float, default=30.0)
    parser.add_argument("--min-time-to-expiry-minutes", type=float, default=15.0)
    parser.add_argument("--top-n-per-underlying-bucket", type=int, default=3)
    parser.add_argument("--execute", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.execute:
        print("Dry guard only. Add --execute. No broker action exists or is allowed.")
        return 0
    config = Config(
        max_direction_panel_gap_minutes=args.max_direction_panel_gap_minutes,
        max_panel_age_minutes=args.max_panel_age_minutes,
        min_time_to_expiry_minutes=args.min_time_to_expiry_minutes,
        top_n_per_underlying_bucket=args.top_n_per_underlying_bucket,
    )
    summary = execute(
        Path(args.repo_root).resolve(),
        Path(args.output_dir).resolve(),
        Path(args.r2e_output_dir) if args.r2e_output_dir else None,
        Path(args.direction_summary_path) if args.direction_summary_path else None,
        config,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if str(summary.get("final_status", "")).startswith("FAIL_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
