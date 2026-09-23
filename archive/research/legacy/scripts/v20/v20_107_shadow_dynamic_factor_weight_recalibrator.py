#!/usr/bin/env python
"""V20.107 shadow dynamic factor-family weight recalibrator.

Creates research-only shadow dynamic factor-family weights from immutable
V20.98B-R5 active research base weights, V20.105 factor-family evidence, and
V20.106 ETF/benchmark alignment evidence. This stage intentionally creates no
official weights, recommendations, trades, broker execution, or factor-level
dynamic weights.
"""

from __future__ import annotations

import csv
import math
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
V105_FAMILY = CONSOLIDATION / "V20_105_FACTOR_FAMILY_HISTORICAL_EVIDENCE.csv"
V105_ABLATION = CONSOLIDATION / "V20_105_FACTOR_ABLATION_EVIDENCE_MATRIX.csv"
V105_WINDOW = CONSOLIDATION / "V20_105_FORWARD_WINDOW_FACTOR_PERFORMANCE.csv"
V105_QUALITY = CONSOLIDATION / "V20_105_FACTOR_EVIDENCE_QUALITY_AUDIT.csv"
V105_READY = CONSOLIDATION / "V20_105_SHADOW_REWEIGHTING_READINESS.csv"
V106_ALIGNMENT = CONSOLIDATION / "V20_106_ETF_ROTATION_BENCHMARK_ALIGNMENT.csv"
V106_FACTOR = CONSOLIDATION / "V20_106_REGIME_CONDITIONED_FACTOR_ALIGNMENT.csv"
V106_SIGNAL = CONSOLIDATION / "V20_106_ETF_REGIME_REWEIGHTING_SIGNAL_AUDIT.csv"
V106_PRECONDITION = CONSOLIDATION / "V20_106_SHADOW_REWEIGHTING_PRECONDITION_AUDIT.csv"
V98C_AUDIT = CONSOLIDATION / "V20_98C_RESEARCH_ONLY_ETF_ROTATION_REGIME_AUDIT.csv"
V98C_MATRIX = CONSOLIDATION / "V20_98C_ETF_PAIR_RELATIVE_STRENGTH_MATRIX.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

OUT_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
OUT_CHANGE = CONSOLIDATION / "V20_107_SHADOW_WEIGHT_CHANGE_AUDIT.csv"
OUT_INPUT = CONSOLIDATION / "V20_107_SHADOW_REWEIGHTING_EVIDENCE_INPUT_AUDIT.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_WEIGHT_VALIDATION.csv"
REPORT = READ_CENTER / "V20_107_SHADOW_DYNAMIC_FACTOR_WEIGHT_REPORT.md"

PASS_STATUS = "PASS_V20_107_SHADOW_DYNAMIC_FACTOR_WEIGHT_RECALIBRATOR"
PARTIAL_GRANULARITY = "PARTIAL_PASS_V20_107_SHADOW_DYNAMIC_FACTOR_WEIGHT_RECALIBRATOR_WITH_LIMITED_FACTOR_GRANULARITY"
PARTIAL_EVIDENCE = "PARTIAL_PASS_V20_107_SHADOW_DYNAMIC_FACTOR_WEIGHT_RECALIBRATOR_WITH_LIMITED_EVIDENCE"
FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]
REQUIRED_POSITIVE = {"RISK", "MARKET_REGIME", "DATA_TRUST"}
SCOPE = "RESEARCH_ONLY_SHADOW_FACTOR_FAMILY"

WEIGHT_FIELDS = [
    "factor_family", "active_research_base_weight", "historical_evidence_multiplier",
    "etf_regime_alignment_multiplier", "evidence_quality_multiplier",
    "risk_control_multiplier", "pre_normalized_shadow_weight", "shadow_dynamic_weight",
    "normalized_shadow_dynamic_weight", "weight_change_abs", "weight_change_pct",
    "shadow_weight_confidence", "shadow_weight_status", "adjustment_reason",
    "factor_granularity_status", "shadow_weight_activation_scope", "is_official_weight",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]

CHANGE_FIELDS = [
    "factor_family", "base_weight", "shadow_weight", "weight_change_abs",
    "weight_change_pct", "family_weight_cap_passed", "nonzero_required_family_passed",
    "evidence_quality", "historical_signal_status", "etf_regime_signal_status",
    "risk_control_status", "validation_status", "validation_reason", "research_only",
    "official_promotion_allowed", "official_recommendation_created", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]

INPUT_FIELDS = [
    "input_check_id", "source_artifact", "artifact_exists", "artifact_non_empty",
    "row_count", "input_status", "input_reason", "limited_factor_granularity_recognized",
    "source_rank_or_score_used_as_weight", "factor_level_dynamic_weights_created",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "is_official_weight", "weight_mutated", "trade_action_created",
    "broker_execution_supported", "dynamic_factor_weight_created",
    "dynamic_factor_weight_scope", "v20_107_execution_status",
]

VALIDATION_FIELDS = [
    "validation_check_id", "factor_family_count", "required_family_count",
    "shadow_weight_sum", "weight_sum_valid", "max_family_weight", "family_cap_valid",
    "risk_weight_positive", "market_regime_weight_positive", "data_trust_weight_positive",
    "factor_level_weights_created", "official_weights_created", "active_base_weights_mutated",
    "dynamic_factor_weight_created", "dynamic_factor_weight_scope", "v20_107_execution_status",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def safety(extra: bool = False) -> dict[str, str]:
    row = {
        "research_only": "TRUE",
        "official_promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
    }
    if extra:
        row["is_official_weight"] = "FALSE"
        row["dynamic_factor_weight_created"] = "TRUE"
        row["dynamic_factor_weight_scope"] = SCOPE
        row["v20_107_execution_status"] = "RUN_SHADOW_ONLY"
    return row


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], str]:
    if not path.exists():
        return [], "MISSING"
    if path.stat().st_size == 0:
        return [], "EMPTY"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [{key: clean(value) for key, value in row.items()} for row in reader]
        return rows, "OK" if reader.fieldnames else "MALFORMED"


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def num(value: object) -> float | None:
    try:
        x = float(clean(value))
    except ValueError:
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    return x


def fmt(value: float, places: int = 10) -> str:
    return f"{value:.{places}f}"


def dec2(value: float) -> str:
    return str(Decimal(str(value)).quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP))


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def load_base_weights() -> dict[str, float]:
    rows, status = read_csv(R5_REGISTRY)
    if status != "OK":
        return {}
    return {row["factor_family"]: float(row["active_research_base_weight"]) for row in rows if row.get("factor_family") in FAMILIES}


def family_metrics() -> dict[str, dict[str, float | str]]:
    rows, _ = read_csv(V105_FAMILY)
    by_family: dict[str, list[dict[str, str]]] = {family: [] for family in FAMILIES}
    for row in rows:
        if row.get("factor_family") in by_family:
            by_family[row["factor_family"]].append(row)
    out: dict[str, dict[str, float | str]] = {}
    for family, subset in by_family.items():
        alphas = [num(row.get("mean_alpha_vs_spy")) for row in subset]
        hit = [num(row.get("hit_rate")) for row in subset]
        adverse = [num(row.get("adverse_outcome_rate")) for row in subset]
        drawdowns = [num(row.get("max_drawdown_proxy")) for row in subset]
        usable = [row for row in subset if row.get("evidence_status") == "USABLE_EVIDENCE"]
        qualities = {row.get("evidence_quality") for row in subset}
        out[family] = {
            "mean_alpha": mean([x for x in alphas if x is not None]) if any(x is not None for x in alphas) else 0.0,
            "hit_rate": mean([x for x in hit if x is not None]) if any(x is not None for x in hit) else 0.5,
            "adverse_rate": mean([x for x in adverse if x is not None]) if any(x is not None for x in adverse) else 0.5,
            "drawdown_proxy": min([x for x in drawdowns if x is not None]) if any(x is not None for x in drawdowns) else 0.0,
            "evidence_quality": "PARTIAL" if "PARTIAL" in qualities else ("HIGH" if "HIGH" in qualities else "LOW"),
            "usable_windows": float(len(usable)),
            "evidence_status": "USABLE_EVIDENCE" if usable else "INSUFFICIENT_EVIDENCE",
        }
    return out


def alignment_metrics() -> dict[str, dict[str, float | str]]:
    rows, _ = read_csv(V106_FACTOR)
    by_family: dict[str, list[dict[str, str]]] = {family: [] for family in FAMILIES}
    for row in rows:
        if row.get("factor_family") in by_family:
            by_family[row["factor_family"]].append(row)
    out: dict[str, dict[str, float | str]] = {}
    for family, subset in by_family.items():
        alphas = [num(row.get("factor_mean_alpha")) for row in subset]
        usable = [row for row in subset if row.get("evidence_status") == "USABLE_EVIDENCE"]
        out[family] = {
            "mean_alignment_alpha": mean([x for x in alphas if x is not None]) if any(x is not None for x in alphas) else 0.0,
            "usable_alignment_rows": float(len(usable)),
            "signal_status": "USABLE_ETF_REGIME_ALIGNMENT" if usable else "INSUFFICIENT_ETF_REGIME_ALIGNMENT",
        }
    return out


def normalize_with_caps(raw: dict[str, float]) -> dict[str, float]:
    total = sum(raw.values())
    weights = {k: (v / total if total else 0.0) for k, v in raw.items()}
    # The upstream base weights and conservative multipliers should already obey
    # the cap. Keep this guard explicit for validation.
    for _ in range(5):
        excess = sum(max(0.0, v - 0.35) for v in weights.values())
        capped = {k for k, v in weights.items() if v > 0.35}
        if excess <= 1e-12:
            break
        for k in capped:
            weights[k] = 0.35
        receivers = [k for k in weights if k not in capped]
        receiver_total = sum(weights[k] for k in receivers)
        for k in receivers:
            weights[k] += excess * (weights[k] / receiver_total if receiver_total else 1 / len(receivers))
    total = sum(weights.values())
    return {k: v / total for k, v in weights.items()}


def input_audit_rows(limited: bool) -> list[dict[str, str]]:
    paths = [
        R5_REGISTRY, V105_FAMILY, V105_ABLATION, V105_WINDOW, V105_QUALITY, V105_READY,
        V106_ALIGNMENT, V106_FACTOR, V106_SIGNAL, V106_PRECONDITION, V98C_AUDIT,
        V98C_MATRIX, V49_RESEARCH, V49_OFFICIAL,
    ]
    rows = []
    for idx, path in enumerate(paths, start=1):
        data, status = read_csv(path)
        rows.append({
            "input_check_id": f"V20_107_INPUT_{idx:03d}",
            "source_artifact": rel(path),
            "artifact_exists": tf(path.exists()),
            "artifact_non_empty": tf(path.exists() and path.stat().st_size > 0),
            "row_count": str(len(data) if status == "OK" else 0),
            "input_status": "PASS" if status == "OK" and data else "WARN_MISSING_OR_EMPTY",
            "input_reason": "READ_ONLY_EVIDENCE_INPUT_LIMITED_FACTOR_GRANULARITY_RECOGNIZED" if limited else "READ_ONLY_EVIDENCE_INPUT",
            "limited_factor_granularity_recognized": tf(limited),
            "source_rank_or_score_used_as_weight": "FALSE",
            "factor_level_dynamic_weights_created": "FALSE",
            **safety(extra=True),
        })
    return rows


def main() -> int:
    base = load_base_weights()
    metrics = family_metrics()
    alignment = alignment_metrics()
    precondition_rows, _ = read_csv(V106_PRECONDITION)
    limited = any(row.get("factor_granularity_status") == "LIMITED_FACTOR_GRANULARITY" for row in precondition_rows)
    partial = limited or any(clean(row.get("evidence_quality")).startswith("PARTIAL") for row in precondition_rows)

    pre_raw: dict[str, float] = {}
    multiplier_rows: dict[str, dict[str, float | str]] = {}
    for family in FAMILIES:
        base_weight = base.get(family, 0.0)
        m = metrics.get(family, {})
        a = alignment.get(family, {})
        alpha = float(m.get("mean_alpha", 0.0))
        hit = float(m.get("hit_rate", 0.5))
        adverse = float(m.get("adverse_rate", 0.5))
        drawdown = float(m.get("drawdown_proxy", 0.0))
        align_alpha = float(a.get("mean_alignment_alpha", 0.0))
        quality = str(m.get("evidence_quality", "LOW"))
        status = str(m.get("evidence_status", "INSUFFICIENT_EVIDENCE"))
        hist_mult = 1.0 + clamp(alpha * 0.8 + (hit - 0.5) * 0.15 - (adverse - 0.5) * 0.08, -0.08, 0.08)
        etf_mult = 1.0 + clamp(align_alpha * 0.5, -0.04, 0.04)
        quality_mult = 1.0 if quality == "HIGH" else (0.98 if quality == "PARTIAL" and status == "USABLE_EVIDENCE" else 0.95)
        risk_mult = 1.0 - clamp(max(0.0, adverse - 0.45) * 0.10 + max(0.0, -drawdown - 0.50) * 0.03, 0.0, 0.05)
        raw = base_weight * hist_mult * etf_mult * quality_mult * risk_mult
        # Partial evidence cannot move more than 20% relative to the base.
        if quality != "HIGH":
            raw = clamp(raw, base_weight * 0.80, base_weight * 1.20)
        pre_raw[family] = min(raw, 0.35)
        multiplier_rows[family] = {
            "historical": hist_mult,
            "etf": etf_mult,
            "quality": quality_mult,
            "risk": risk_mult,
            "quality_label": quality,
            "evidence_status": status,
            "historical_signal_status": "USABLE_HISTORICAL_SIGNAL" if status == "USABLE_EVIDENCE" else "LIMITED_HISTORICAL_SIGNAL",
            "etf_signal_status": a.get("signal_status", "INSUFFICIENT_ETF_REGIME_ALIGNMENT"),
            "risk_status": "RISK_CONTROL_PENALTY_APPLIED" if risk_mult < 1.0 else "RISK_CONTROL_PASS",
        }

    normalized = normalize_with_caps(pre_raw)
    # Round while preserving exact 1.0 within emitted precision.
    rounded = {k: float(dec2(v)) for k, v in normalized.items()}
    diff = 1.0 - sum(rounded.values())
    largest = max(rounded, key=rounded.get)
    rounded[largest] = float(dec2(rounded[largest] + diff))

    weight_rows: list[dict[str, str]] = []
    change_rows: list[dict[str, str]] = []
    for family in FAMILIES:
        base_weight = base[family]
        shadow = rounded[family]
        change = shadow - base_weight
        change_pct = change / base_weight if base_weight else 0.0
        mult = multiplier_rows[family]
        quality = str(mult["quality_label"])
        status = str(mult["evidence_status"])
        if status != "USABLE_EVIDENCE":
            shadow_status = "HOLD_BASE_WEIGHT_DUE_TO_LIMITED_EVIDENCE"
            reason = "INSUFFICIENT_EVIDENCE"
        elif partial:
            shadow_status = "RESEARCH_ONLY_SHADOW_FACTOR_FAMILY_WEIGHT_CREATED_PARTIAL_CONFIDENCE"
            reason = "LIMITED_FACTOR_GRANULARITY_PARTIAL_EVIDENCE_CONSERVATIVE_MULTIPLIERS"
        else:
            shadow_status = "RESEARCH_ONLY_SHADOW_FACTOR_FAMILY_WEIGHT_CREATED"
            reason = "USABLE_FACTOR_FAMILY_AND_ETF_ALIGNMENT_EVIDENCE"
        weight_rows.append({
            "factor_family": family,
            "active_research_base_weight": fmt(base_weight),
            "historical_evidence_multiplier": fmt(float(mult["historical"])),
            "etf_regime_alignment_multiplier": fmt(float(mult["etf"])),
            "evidence_quality_multiplier": fmt(float(mult["quality"])),
            "risk_control_multiplier": fmt(float(mult["risk"])),
            "pre_normalized_shadow_weight": fmt(pre_raw[family]),
            "shadow_dynamic_weight": fmt(shadow),
            "normalized_shadow_dynamic_weight": fmt(shadow),
            "weight_change_abs": fmt(change),
            "weight_change_pct": fmt(change_pct),
            "shadow_weight_confidence": "PARTIAL" if partial else "HIGH",
            "shadow_weight_status": shadow_status,
            "adjustment_reason": reason,
            "factor_granularity_status": "LIMITED_FACTOR_GRANULARITY" if limited else "FACTOR_FAMILY_GRANULARITY",
            "shadow_weight_activation_scope": "RESEARCH_ONLY_SHADOW",
            "is_official_weight": "FALSE",
            **safety(),
        })
        cap_pass = shadow <= 0.35 + 1e-9
        required_pass = family not in REQUIRED_POSITIVE or shadow > 0
        change_rows.append({
            "factor_family": family,
            "base_weight": fmt(base_weight),
            "shadow_weight": fmt(shadow),
            "weight_change_abs": fmt(change),
            "weight_change_pct": fmt(change_pct),
            "family_weight_cap_passed": tf(cap_pass),
            "nonzero_required_family_passed": tf(required_pass),
            "evidence_quality": quality,
            "historical_signal_status": str(mult["historical_signal_status"]),
            "etf_regime_signal_status": str(mult["etf_signal_status"]),
            "risk_control_status": str(mult["risk_status"]),
            "validation_status": "PASS" if cap_pass and required_pass and abs(change_pct) <= 0.2000001 else "WARN",
            "validation_reason": "SHADOW_WEIGHT_WITHIN_CAPS_AND_RESEARCH_ONLY_SCOPE",
            **safety(),
        })

    total = sum(rounded.values())
    max_weight = max(rounded.values()) if rounded else 0.0
    validation_rows = [{
        "validation_check_id": "V20_107_VALIDATION_001",
        "factor_family_count": str(len(weight_rows)),
        "required_family_count": str(len(FAMILIES)),
        "shadow_weight_sum": fmt(total),
        "weight_sum_valid": tf(abs(total - 1.0) <= 1e-8),
        "max_family_weight": fmt(max_weight),
        "family_cap_valid": tf(max_weight <= 0.35 + 1e-8),
        "risk_weight_positive": tf(rounded.get("RISK", 0) > 0),
        "market_regime_weight_positive": tf(rounded.get("MARKET_REGIME", 0) > 0),
        "data_trust_weight_positive": tf(rounded.get("DATA_TRUST", 0) > 0),
        "factor_level_weights_created": "FALSE",
        "official_weights_created": "FALSE",
        "active_base_weights_mutated": "FALSE",
        "dynamic_factor_weight_created": "TRUE",
        "dynamic_factor_weight_scope": SCOPE,
        "v20_107_execution_status": "RUN_SHADOW_ONLY",
        **safety(),
    }]

    input_rows = input_audit_rows(limited)
    status = PARTIAL_GRANULARITY if limited else (PARTIAL_EVIDENCE if partial else PASS_STATUS)

    write_csv(OUT_WEIGHTS, WEIGHT_FIELDS, weight_rows)
    write_csv(OUT_CHANGE, CHANGE_FIELDS, change_rows)
    write_csv(OUT_INPUT, INPUT_FIELDS, input_rows)
    write_csv(OUT_VALIDATION, VALIDATION_FIELDS, validation_rows)

    lines = [
        "# V20.107 Shadow Dynamic Factor Weight Recalibrator",
        "",
        "## Current Result",
        f"- wrapper_status: {status}",
        f"- factor_family_count: {len(weight_rows)}",
        f"- shadow_weight_sum: {fmt(total)}",
        "- dynamic_factor_weight_created: TRUE",
        f"- dynamic_factor_weight_scope: {SCOPE}",
        "- factor_level_weights_created: FALSE",
        "- official_weights_created: FALSE",
        "- active_base_weights_mutated: FALSE",
        "- v20_107_execution_status: RUN_SHADOW_ONLY",
        f"- limited_factor_granularity_recognized: {tf(limited)}",
        "",
        "## Safety Boundary",
        "- research_only: TRUE",
        "- official_promotion_allowed: FALSE",
        "- official_recommendation_created: FALSE",
        "- is_official_weight: FALSE",
        "- weight_mutated: FALSE",
        "- trade_action_created: FALSE",
        "- broker_execution_supported: FALSE",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(status)
    print(f"FACTOR_FAMILY_COUNT={len(weight_rows)}")
    print(f"SHADOW_WEIGHT_SUM={fmt(total)}")
    print(f"MAX_FAMILY_WEIGHT={fmt(max_weight)}")
    print(f"LIMITED_FACTOR_GRANULARITY_RECOGNIZED={tf(limited)}")
    print("FACTOR_LEVEL_WEIGHTS_CREATED=FALSE")
    print("OFFICIAL_WEIGHTS_CREATED=FALSE")
    print("ACTIVE_BASE_WEIGHTS_MUTATED=FALSE")
    print("DYNAMIC_FACTOR_WEIGHT_CREATED=TRUE")
    print(f"DYNAMIC_FACTOR_WEIGHT_SCOPE={SCOPE}")
    print("V20_107_EXECUTION_STATUS=RUN_SHADOW_ONLY")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print(f"OUTPUT_WEIGHTS={rel(OUT_WEIGHTS)}")
    print(f"OUTPUT_CHANGE_AUDIT={rel(OUT_CHANGE)}")
    print(f"OUTPUT_INPUT_AUDIT={rel(OUT_INPUT)}")
    print(f"OUTPUT_VALIDATION={rel(OUT_VALIDATION)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
