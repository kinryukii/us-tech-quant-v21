"""Metadata-only analysis of declared, unfilled quality rejections.

No readers, prices, NAV/returns, account calls or fitting. This independent
analysis preserves the parent control result and never certifies its source.
"""
from __future__ import annotations

import copy
import math
from datetime import date, datetime, time, timezone
from collections.abc import Mapping

from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash

SCHEMA = "B_MECHANISM_CONTROL_QUALIFICATION_R3_V1"
_REASON = "PRICE_QUALITY_UNCERTIFIED"
_TRUE_FACTS = ("raw_row_present", "raw_open_positive_finite", "raw_close_positive_finite",
               "signal_adv_positive_finite", "economic_coordinate_not_used",
               "unsupported_events_preserved")
_ZERO_FACTS = ("actual_fill_count", "previous_held_position_count", "current_held_position_count")
_BINDINGS = ("parent_control_result_sha256", "account_freeze_sha256", "source_snapshot_sha256")
_FACT_FIELDS = frozenset(("path_id", "date", "ticker", "status", "reason", *_TRUE_FACTS,
                          *_ZERO_FACTS, *_BINDINGS))
_AUDIT_ERRORS = ("cash_identity_error_max", "cost_identity_error_max", "self_finance_error_max",
                 "nav_identity_error_max", "actual_cash_flow_identity_error_max")
_FALSE_SOURCE_FLAGS = ("strict_PIT_promotion_eligible", "certified_NAV", "quote_qualified")
_QUALIFICATION_FIELDS = frozenset(("mechanism_accounting_consistent", "raw_endpoints_finite",
    "quality_source_only_or_clear", "unresolved_economic_exception_count", "execution_audit_pass",
    "selection_input_complete", "actual_execution_inputs_complete", "selection_input_gaps",
    "actual_execution_input_gaps", "status", *_FALSE_SOURCE_FLAGS))
_CONTRACT = dict(schema=SCHEMA, operation="RECLASSIFY_DECLARED_UNFILLED_QUALITY_REJECTIONS_ONLY",
                 required_true_facts=list(_TRUE_FACTS), required_zero_facts=list(_ZERO_FACTS),
                 audit_error_tolerance=1e-5, original_failure_retained=True,
                 actual_fit_units=0, actual_account_attempts=0, source_flags=False)
ANALYSIS_IDENTITY_SHA256 = content_hash(_CONTRACT)


class ControlQualificationError(ValueError):
    """Invalid analysis metadata cannot establish eligibility."""


def _sha(value, name):
    if (not isinstance(value, str) or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise ControlQualificationError("SHA256_BINDING_REQUIRED:" + name)
    return value


def _session(value):
    if isinstance(value, datetime):
        stamp = value
    elif isinstance(value, date):
        stamp = datetime.combine(value, time())
    elif isinstance(value, str):
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ControlQualificationError("ISO_SESSION_REQUIRED") from exc
    else:
        raise ControlQualificationError("ISO_SESSION_REQUIRED")
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone(timezone.utc)
    if stamp.time().replace(tzinfo=None) != time() or not date(2023, 1, 1) <= stamp.date() < date(2026, 1, 1):
        raise ControlQualificationError("PRE2026_MIDNIGHT_CONTROL_SESSION_REQUIRED")
    return stamp.date().isoformat()


def _coordinate(path, row):
    ticker = row.get("ticker")
    if not isinstance(ticker, str) or not ticker:
        raise ControlQualificationError("DECLARED_SECURITY_COORDINATE_REQUIRED")
    return (path, _session(row.get("date")), ticker)


def _finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _audit_checks(audit):
    checks = {key: _finite_number(audit.get(key)) and abs(audit[key]) <= 1e-5 for key in _AUDIT_ERRORS}
    for key in ("next_open_violations", "capacity_violations"):
        checks[key] = type(audit.get(key)) is int and audit[key] == 0
    checks["position_count"] = type(audit.get("max_actual_names")) is int and 0 <= audit["max_actual_names"] <= 20
    checks["cash_floor"] = _finite_number(audit.get("minimum_cash")) and audit["minimum_cash"] >= -1e-8
    return checks


def analyze_control_qualification(original_qualification, audit, rejection_facts, *,
                                  parent_control_result_sha256, account_freeze_sha256,
                                  source_snapshot_sha256, baseline_economic_consistent,
                                  baseline_daily_flags_sha256):
    """Analyze complete caller-bound metadata without touching the account trace.

    baseline_economic_consistent maps each exact path to the independently
    projected common-engine daily accounting-qualified flag (all rows). Its
    digest binds that projection; exception count alone is insufficient.
    Facts must match every original execution gap exactly once. A rejected
    request may only be reclassified when all listed dependency facts pass.
    """
    if not isinstance(original_qualification, Mapping) or not original_qualification:
        raise ControlQualificationError("ORIGINAL_PATH_QUALIFICATION_REQUIRED")
    if not isinstance(audit, Mapping) or not isinstance(baseline_economic_consistent, Mapping):
        raise ControlQualificationError("AUDIT_AND_BASELINE_METADATA_REQUIRED")
    paths = set(original_qualification)
    if any(not isinstance(path, str) or not path for path in paths) or set(baseline_economic_consistent) != paths:
        raise ControlQualificationError("EXACT_BASELINE_PATHS_REQUIRED")
    bindings = {key: _sha(value, key) for key, value in zip(_BINDINGS,
        (parent_control_result_sha256, account_freeze_sha256, source_snapshot_sha256))}
    baseline_sha = _sha(baseline_daily_flags_sha256, "baseline_daily_flags_sha256")
    if not isinstance(rejection_facts, (list, tuple)):
        raise ControlQualificationError("REJECTION_FACT_LIST_REQUIRED")
    facts = {}
    for fact in rejection_facts:
        if not isinstance(fact, Mapping) or set(fact) - _FACT_FIELDS:
            raise ControlQualificationError("ONLY_DECLARED_METADATA_FACT_FIELDS_ALLOWED")
        path = fact.get("path_id")
        if path not in paths:
            raise ControlQualificationError("FOREIGN_FACT_PATH")
        if any(fact.get(key) != value for key, value in bindings.items()):
            raise ControlQualificationError("FACT_PROVENANCE_MISMATCH")
        coordinate = _coordinate(path, fact)
        if coordinate in facts:
            raise ControlQualificationError("DUPLICATE_FACT_COORDINATE")
        facts[coordinate] = dict(fact)
    audits = _audit_checks(audit)
    result, seen = {}, set()
    for path, original in original_qualification.items():
        if not isinstance(original, Mapping) or set(original) - _QUALIFICATION_FIELDS:
            raise ControlQualificationError("ONLY_ORIGINAL_QUALIFICATION_METADATA_ALLOWED")
        blocking, constraints = [], []
        if type(original.get("mechanism_accounting_consistent")) is not bool:
            blocking.append("ORIGINAL_AGGREGATE_BOOLEAN_REQUIRED")
        for field in ("raw_endpoints_finite", "quality_source_only_or_clear", "execution_audit_pass", "selection_input_complete"):
            if original.get(field) is not True:
                blocking.append(field)
        if (type(original.get("unresolved_economic_exception_count")) is not int
                or original["unresolved_economic_exception_count"] != 0):
            blocking.append("UNRESOLVED_ECONOMIC_EXCEPTIONS")
        if baseline_economic_consistent[path] is not True:
            blocking.append("BASELINE_DAILY_ECONOMIC_ACCOUNTING_UNQUALIFIED")
        if any(original.get(flag) is not False for flag in _FALSE_SOURCE_FLAGS):
            blocking.append("SOURCE_CERTIFICATION_FLAGS_MUST_REMAIN_FALSE")
        if original.get("selection_input_gaps") != []:
            blocking.append("SELECTION_INPUT_GAPS")
        if not all(audits.values()):
            blocking.append("COMMON_EXECUTION_AUDIT_FAILED")
        gaps = original.get("actual_execution_input_gaps")
        if not isinstance(gaps, list):
            raise ControlQualificationError("ORIGINAL_EXECUTION_GAP_LIST_REQUIRED")
        if original.get("actual_execution_inputs_complete") is not (not gaps):
            blocking.append("ORIGINAL_EXECUTION_COMPLETENESS_INCONSISTENT")
        if original.get("mechanism_accounting_consistent") is False and not gaps:
            blocking.append("ORIGINAL_FAILURE_NOT_EXPLAINED_BY_DECLARED_REJECTIONS")
        for gap in gaps:
            if not isinstance(gap, Mapping) or set(gap) - {"date", "ticker", "reason"}:
                raise ControlQualificationError("ONLY_ORIGINAL_GAP_METADATA_ALLOWED")
            coordinate = _coordinate(path, gap)
            if coordinate in seen:
                raise ControlQualificationError("DUPLICATE_ORIGINAL_GAP_COORDINATE")
            seen.add(coordinate)
            if gap.get("reason") != _REASON:
                blocking.append("MATERIAL_EXECUTION_GAP:" + str(gap.get("reason")))
                continue
            fact = facts.get(coordinate)
            if fact is None:
                blocking.append("MISSING_REJECTION_DEPENDENCY_FACT")
                continue
            invalid = [field for field in _TRUE_FACTS if fact.get(field) is not True]
            invalid += [field for field in _ZERO_FACTS if type(fact.get(field)) is not int or fact[field] != 0]
            if fact.get("status") != "REJECTED" or fact.get("reason") != _REASON:
                invalid.append("REJECTION_STATUS_OR_REASON")
            if invalid:
                blocking.extend("REJECTION_DEPENDENCY_FAILED:" + field for field in invalid)
            else:
                constraints.append(dict(path_id=path, date=coordinate[1], ticker=coordinate[2],
                    reason=_REASON, classification="DECLARED_UNFILLED_EXECUTION_CONSTRAINT",
                    fact_sha256=content_hash(fact), economic_coordinate_not_used=True,
                    unsupported_events_preserved=True, does_not_certify_share_or_quote_coordinate=True))
        eligible = not blocking
        result[path] = dict(conditional_mechanism_eligible=eligible,
            status="CONDITIONAL_MECHANISM_ELIGIBLE_UNCERTIFIED" if eligible else "BLOCKED_MECHANISM_QUALIFICATION",
            declared_execution_constraints=constraints, blocking_conditions=blocking,
            original_aggregate_mechanism_accounting_consistent=original.get("mechanism_accounting_consistent"),
            strict_PIT_promotion_eligible=False, certified_NAV=False, quote_qualified=False)
    if set(facts) - seen:
        raise ControlQualificationError("FACT_WITHOUT_ORIGINAL_DECLARED_GAP")
    payload = dict(schema=SCHEMA, analysis_identity_sha256=ANALYSIS_IDENTITY_SHA256,
        bindings=bindings, baseline_daily_flags_sha256=baseline_sha,
        original_qualification_sha256=content_hash(original_qualification),
        rejection_facts_sha256=content_hash(rejection_facts), baseline_economic_consistent=dict(baseline_economic_consistent),
        audit_checks=audits, qualification=result,
        conditional_mechanism_eligible=all(r["conditional_mechanism_eligible"] for r in result.values()),
        original_control_result_preserved=True, new_account_attempts=0, new_fit_units=0,
        strict_PIT_promotion_eligible=False, certified_NAV=False, quote_qualified=False,
        exact39_proxy_mask_unchanged=True, policy_and_fill_behavior_unchanged=True)
    payload["analysis_payload_sha256"] = content_hash(payload)
    return copy.deepcopy(payload)
