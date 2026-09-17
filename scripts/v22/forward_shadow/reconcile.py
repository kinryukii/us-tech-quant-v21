"""Cross-shadow date, lineage, security, and inference-only governance checks."""

from __future__ import annotations

from typing import Any, Mapping

from .schemas import ComponentResult, ROLES, RunIdentity, RunnerConfig


def _securities(result: ComponentResult) -> set[str]:
    return {str(row.get("security_id")) for row in result.records if row.get("security_id") not in {None, "", "UNKNOWN"}}


def reconcile_components(
    results: Mapping[str, ComponentResult], identity: RunIdentity, config: RunnerConfig,
) -> dict[str, Any]:
    reasons: list[str] = []
    if set(results) != set(ROLES):
        reasons.append("COMPONENT_SET_INCOMPLETE")
    component_failures = [role for role, result in results.items() if result.status != "PASS"]
    reasons.extend(f"COMPONENT_{role}_FAILED" for role in component_failures)
    dates = {result.target_date for result in results.values()}
    date_status = "PASS" if dates == {identity.target_date} else "FAIL"
    if date_status == "FAIL":
        reasons.append("CROSS_SHADOW_TARGET_DATE_MISMATCH")
    lineage_ok = all(result.run_id == identity.run_id for result in results.values())
    if "RISK" in results and results["RISK"].input_alpha_run_id != identity.run_id:
        lineage_ok = False
    if "EXECUTION" in results and (
        results["EXECUTION"].input_alpha_run_id != identity.run_id
        or results["EXECUTION"].input_risk_run_id != identity.run_id
    ):
        lineage_ok = False
    if not lineage_ok:
        reasons.append("CROSS_COMPONENT_LINEAGE_MISMATCH")
    governance_violations = []
    for role, result in results.items():
        if result.fit_called or result.training_rows_2026 > 0:
            governance_violations.append(f"{role}_TRAINING_VIOLATION")
        if result.parameter_search_run or result.threshold_search_run:
            governance_violations.append(f"{role}_PARAMETER_OR_THRESHOLD_SEARCH_VIOLATION")
        if result.model_selection_run:
            governance_violations.append(f"{role}_MODEL_SELECTION_VIOLATION")
        if result.broker_action:
            governance_violations.append(f"{role}_BROKER_ACTION_VIOLATION")
    reasons.extend(governance_violations)

    alpha = _securities(results["ALPHA"]) if "ALPHA" in results else set()
    risk = _securities(results["RISK"]) if "RISK" in results else set()
    execution = _securities(results["EXECUTION"]) if "EXECUTION" in results else set()
    alpha_without_risk, risk_without_alpha = alpha - risk, risk - alpha
    execution_without_alpha = execution - alpha
    security_reasons = []
    if config.risk_must_be_subset_of_alpha and risk_without_alpha:
        security_reasons.append("RISK_SECURITY_NOT_IN_ALPHA")
    if config.require_risk_for_every_alpha and alpha_without_risk:
        security_reasons.append("ALPHA_SECURITY_WITHOUT_RISK")
    if config.execution_must_be_subset_of_alpha and execution_without_alpha:
        security_reasons.append("EXECUTION_SECURITY_NOT_IN_ALPHA")
    alpha_without_execution = alpha - execution
    if alpha_without_execution and config.allow_execution_subset_with_reason and not results["EXECUTION"].security_alignment_reason:
        security_reasons.append("EXECUTION_SUBSET_REASON_MISSING")
    if alpha_without_execution and not config.allow_execution_subset_with_reason:
        security_reasons.append("EXECUTION_SUBSET_FORBIDDEN")
    reasons.extend(security_reasons)
    security_status = "PASS" if not security_reasons else "FAIL"
    governance_status = "PASS" if not governance_violations else "FAIL"
    status = "PASS" if not reasons else "FAIL"
    return {
        "status": status, "reasons": sorted(set(reasons)),
        "cross_shadow_date_status": date_status,
        "cross_component_lineage_status": "PASS" if lineage_ok else "FAIL",
        "security_alignment_status": security_status,
        "governance_status": governance_status,
        "broker_action_status": "FORBIDDEN_PASS" if not any(result.broker_action for result in results.values()) else "FAIL",
        "alpha_security_count": len(alpha), "risk_security_count": len(risk),
        "execution_security_count": len(execution),
        "alpha_without_risk": sorted(alpha_without_risk), "risk_without_alpha": sorted(risk_without_alpha),
        "execution_without_alpha": sorted(execution_without_alpha),
        "alpha_without_execution": sorted(alpha_without_execution),
        "execution_subset_reason": results["EXECUTION"].security_alignment_reason,
        "execution_subset_difference_policy": (
            "ALLOWED_WITH_REASON" if config.allow_execution_subset_with_reason else "FAIL_IF_DIFFERENT"
        ),
    }
