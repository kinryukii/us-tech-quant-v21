"""Fail-closed target-date, canonical, frozen identity, and governance checks."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from .schemas import CanonicalReadiness, ComponentIdentity, ROLES, RunnerConfig, valid_sha256


def run_preflight(
    target_date: str,
    readiness: CanonicalReadiness,
    components: Mapping[str, ComponentIdentity],
    config: RunnerConfig,
    *,
    mode: str,
) -> dict[str, Any]:
    reasons: list[str] = []
    try:
        target = date.fromisoformat(target_date)
        as_of = date.fromisoformat(readiness.as_of_date)
    except ValueError:
        target = as_of = None
        reasons.append("INVALID_TARGET_OR_AS_OF_DATE")
    if readiness.target_date != target_date:
        reasons.append("READINESS_TARGET_DATE_MISMATCH")
    if target is not None and as_of is not None and target > as_of:
        reasons.append("TARGET_DATE_FUTURE")
    checks = (
        (readiness.available_dates, "TARGET_DATE_MISSING_CANONICAL"),
        (readiness.eligible_trading_dates, "TARGET_DATE_NOT_ELIGIBLE_TRADING_DATE"),
        (readiness.feature_ready_dates, "REQUIRED_FEATURES_UNAVAILABLE"),
        (readiness.universe_ready_dates, "UNIVERSE_SNAPSHOT_UNAVAILABLE"),
    )
    reasons.extend(reason for values, reason in checks if target_date not in values)
    if target_date in readiness.partial_dates:
        reasons.append("TARGET_DATE_PARTIAL")
    if not valid_sha256(readiness.canonical_manifest_sha256):
        reasons.append("CANONICAL_MANIFEST_HASH_INVALID")
    if str(readiness.universe_id).upper() in {"", "UNKNOWN"}:
        reasons.append("UNIVERSE_ID_UNKNOWN")
    if set(components) != set(ROLES):
        reasons.append("FROZEN_COMPONENT_SET_INCOMPLETE")
    for role, component in components.items():
        if component.role != role or str(component.freeze_id).upper() in {"", "UNKNOWN"}:
            reasons.append(f"{role}_FROZEN_IDENTITY_UNKNOWN")
        if mode in {"production", "resume"} and config.require_frozen_hashes and not component.hashes_materialized:
            reasons.append(f"{role}_HASH_NOT_YET_MATERIALIZED")
        if component.uses_2026_training is not False:
            reasons.append(f"{role}_2026_TRAINING_METADATA_NOT_FALSE")
        if component.uses_2026_parameter_search is not False:
            reasons.append(f"{role}_2026_PARAMETER_SEARCH_METADATA_NOT_FALSE")
        if component.uses_2026_model_selection is not False:
            reasons.append(f"{role}_2026_MODEL_SELECTION_METADATA_NOT_FALSE")
    if config.auto_canonical_refresh:
        reasons.append("AUTO_CANONICAL_REFRESH_FORBIDDEN")
    if config.broker_action_allowed or config.training_allowed or config.parameter_search_allowed or config.model_selection_allowed:
        reasons.append("UNSAFE_CAPABILITY_ENABLED")
    return {
        "status": "PASS" if not reasons else "FAIL_CLOSED",
        "target_date": target_date, "mode": mode, "reasons": sorted(set(reasons)),
        "canonical_readiness_action": "READINESS_CHECK_ONLY",
        "canonical_refresh_run": False, "fallback_date_used": False,
        "2026_inference_allowed": bool(target and target.year == 2026),
        "training_allowed": False, "parameter_search_allowed": False,
        "model_selection_allowed": False, "broker_action_allowed": False,
    }
