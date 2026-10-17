"""Pure metadata projection of the existing durable risk ledger; no I/O or fitting.

Caller supplies fixed, independently verified projections after producer writes stop.
This module neither loads model values nor becomes a registry, ledger or estimator.
A whole RiskState artifact does not imply persisted reusable scaler/subfit values.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone

from scripts.maintenance.research_registry import sha256_value
from scripts.research.a2.risk.shared_risk_budget_r2 import KINDS, LEARNED_KINDS, content_hash
from scripts.research.a2.risk.shared_risk_engine_r2 import METHODS, risk_state_contract

_BOUNDARY = datetime(2026, 1, 1, tzinfo=timezone.utc)
_COMPLETE_STUDY_ID = "V24_B_COMPLETE_COMMON_H5_FF48_RISK_DIAGNOSTIC_R1"
_COMPLETE = {"FIT_COMPLETE", "SUCCEEDED"}
_FAILED = {"FIT_FAILURE", "FAILED"}
_PASS = {"PASS_SYNTHETIC", "PASS_FROZEN_HISTORY_MECHANISM"}
_STAGE = {"stage_id", "research_id", "domain_role", "science_ref", "source_inputs_ref",
          "support_ref", "execution_ref", "audit_ref", "producer_code_pins", "audit",
          "parent_stage_ids", "producer_complete", "expected_node_count"}
_AUDIT = {"schema", "nodes", "account_attempts", "test2026_rows_read",
          "strict_PIT_promotion_eligible", "no_refund", "retry_limit",
          "risk_fit_units", "actual_new_fit_units", "b_cumulative_fit_units", "stage_new_fit_units"}
_NODE = {"risk_node", "method", "as_of", "cutoff", "assets", "asset_uids",
         "asset_epochs", "status", "risk_state_id", "artifact", "sha256",
         "learned_states", "fit_dependency_ids", "block_reason", "block_reasons",
         "parent_requested", "parent_origin_window", "excluded_reasons", "snapshot_roles",
         "research_id", "correction_envelope", "correction_activation_sha256",
         "correction_freeze_sha256", "strict_PIT_promotion_eligible",
         "status_before_recovery", "recovery_audit_sha256", "engineering_failure_preserved",
         "domain_comparison", "exact_reuse_receipt_ref", "domain_role",
         "risk_complete_common_science_sha256", "complete_execution_freeze_sha256", "started_utc"}
_EVENT = {"key", "kind", "name", "status", "context", "inputs_sha256", "parameters",
          "owner_stage_id", "learned_states", "result_sha256", "dependencies",
          "corrected_rr_node", "correction_freeze_sha256", "complete_common_node",
          "complete_execution_freeze_sha256", "complete_group_as_of"}
_RAW = {"covariance", "marginal_sigma", "mu", "y_open5", "ret_1d", "returns",
        "nav", "metrics", "predictions", "values", "learned_value", "state_value", "notes"}



_DOMAIN_FIELDS = {"assets", "parent_origin_window", "asset_uids", "asset_epochs",
                  "segment_starts", "supported_h5_by_asset"}
_DOMAIN_COMPARISON_FIELDS = {"parent_origin_window_sha256", "parent_requested_sha256",
    "prior_partial_domain", "complete_domain", "prior_partial_domain_sha256",
    "complete_domain_sha256", "counts_sha256", "parent_component_support_sha256",
    "relation", "whole_scientific_equivalence"}


def _complete_domain_proof(node, stage, stage_map):
    proof = _only(node.get("domain_comparison"), _DOMAIN_COMPARISON_FIELDS, "complete_domain_comparison")
    if set(proof) != _DOMAIN_COMPARISON_FIELDS or proof["whole_scientific_equivalence"] != "NOT_CLAIMED_FROM_RESEARCH_ID_OR_DOMAIN_ALONE":
        raise BankMetadataError("COMPLETE_DOMAIN_EVIDENCE_REQUIRED")
    prior, complete = [_only(proof[k], _DOMAIN_FIELDS, "component_domain") for k in
                       ("prior_partial_domain", "complete_domain")]
    for domain in (prior, complete):
        assets = domain.get("assets", [])
        if set(domain) != _DOMAIN_FIELDS or len(set(assets)) != len(assets):
            raise BankMetadataError("COMPLETE_DOMAIN_SHAPE_REQUIRED")
        for field in ("asset_uids", "asset_epochs", "segment_starts", "supported_h5_by_asset"):
            if set(domain[field]) != set(assets):
                raise BankMetadataError("COMPLETE_DOMAIN_IDENTITY_OR_COUNT_KEYS")
        for count in domain["supported_h5_by_asset"].values():
            if not 0 <= _count(count) <= 252:
                raise BankMetadataError("COMPLETE_SOURCE_COUNT_INVALID")
        clocks = [_time(t) for t in domain["parent_origin_window"]]
        if len(clocks) != 252 or len(set(clocks)) != 252 or clocks != sorted(clocks) or max(clocks) >= _time(node["cutoff"]):
            raise BankMetadataError("COMPLETE_PARENT_252_WINDOW_REQUIRED")
    for field, actual in (("assets", node["assets"]), ("asset_uids", node["asset_uids"]),
                          ("asset_epochs", node["asset_epochs"]), ("parent_origin_window", node.get("parent_origin_window"))):
        if complete[field] != actual:
            raise BankMetadataError("COMPLETE_DOMAIN_NODE_BINDING_CONFLICT")
    requested = node.get("parent_requested")
    if not isinstance(requested, dict) or any(
            requested.get(field, {}).get(x) != complete[field][x]
            for field in ("asset_uids", "asset_epochs", "segment_starts")
            for x in complete["assets"]):
        raise BankMetadataError("COMPLETE_PARENT_REQUESTED_START_UNBOUND")
    if prior["parent_origin_window"] != complete["parent_origin_window"]:
        raise BankMetadataError("COMPLETE_PARENT_WINDOW_CHANGED")
    first_origin = _time(complete["parent_origin_window"][0])
    if any((_segment_session_date(start) > first_origin.date()
            if isinstance(start, str) and len(start) == 10 else _time(start) > first_origin)
           for start in complete["segment_starts"].values()):
        raise BankMetadataError("COMPLETE_UID_SEGMENT_DOES_NOT_COVER_PARENT_WINDOW")
    if any(v != 252 for v in complete["supported_h5_by_asset"].values()):
        raise BankMetadataError("COMPLETE_DOMAIN_REQUIRES_252_SOURCE_OBSERVATIONS")
    if [x for x in prior["assets"] if x in complete["assets"]] != complete["assets"]:
        raise BankMetadataError("COMPLETE_DOMAIN_ORDER_OR_MEMBERSHIP_CHANGED")
    for field in ("asset_uids", "asset_epochs", "segment_starts", "supported_h5_by_asset"):
        if any(complete[field][x] != prior[field][x] for x in complete["assets"]):
            raise BankMetadataError("COMPLETE_DOMAIN_PRIOR_IDENTITY_OR_COUNT_CHANGED")
    digests = {"parent_origin_window_sha256": content_hash(complete["parent_origin_window"]),
        "parent_requested_sha256": content_hash(node.get("parent_requested")),
        "prior_partial_domain_sha256": content_hash(prior), "complete_domain_sha256": content_hash(complete),
        "counts_sha256": content_hash(prior["supported_h5_by_asset"])}
    if any(_sha(proof[k]) != v for k, v in digests.items()):
        raise BankMetadataError("COMPLETE_DOMAIN_CANONICAL_HASH_CONFLICT")
    parents = [stage_map[sid] for sid in stage.get("parent_stage_ids", ())]
    if not any(p["domain_role"] == "SOURCE_QUALIFIED_COMPONENT" and
               p["support_ref"]["sha256"] == proof["parent_component_support_sha256"] for p in parents):
        raise BankMetadataError("COMPLETE_DOMAIN_PARENT_SUPPORT_UNBOUND")
    relation = proof["relation"]
    if relation == "STRICT_SUBSET":
        if not set(complete["assets"]) < set(prior["assets"]):
            raise BankMetadataError("COMPLETE_DOMAIN_NOT_STRICT_SUBSET")
    elif relation == "REUSE_REQUIRED":
        if prior != complete or _count(node.get("learned_states", 0)) != 0:
            raise BankMetadataError("EQUIVALENT_DOMAIN_NEW_FIT_FORBIDDEN")
    else:
        raise BankMetadataError("COMPLETE_DOMAIN_RELATION_UNKNOWN")
    return proof

class BankMetadataError(ValueError):
    pass


def _only(value, allowed, label):
    if not isinstance(value, dict) or set(value) - allowed:
        raise BankMetadataError("METADATA_PROJECTION_REQUIRED:" + label)
    return copy.deepcopy(value)


def _sha(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise BankMetadataError("SHA256_REQUIRED")
    return value


def _ref(value):
    value = _only(value, {"path", "sha256"}, "reference")
    path = value.get("path")
    if not isinstance(path, str) or not path.replace("\\", "/").lower().startswith("d:/"):
        raise BankMetadataError("D_METADATA_REFERENCE_REQUIRED")
    _sha(value.get("sha256"))
    return value


def _count(value):
    if type(value) is not int or value < 0:
        raise BankMetadataError("NONNEGATIVE_INTEGER_REQUIRED")
    return value


def _time(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError()
        result = result.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        raise BankMetadataError("EXPLICIT_UTC_EQUIVALENT_CLOCK_REQUIRED") from None
    if result >= _BOUNDARY:
        raise BankMetadataError("PRE2026_CLOCK_REQUIRED")
    return result


def _segment_session_date(value):
    # UID segment boundaries are session-date metadata, not fit/availability clocks.
    if isinstance(value, str) and len(value) == 10:
        try:
            result = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            raise BankMetadataError("EXACT_SEGMENT_SESSION_DATE_REQUIRED") from None
        if result.isoformat() != value or result >= _BOUNDARY.date():
            raise BankMetadataError("PRE2026_EXACT_SEGMENT_SESSION_REQUIRED")
        return result
    return _time(value).date()


def _metadata(value, path=()):
    if isinstance(value, dict):
        dynamic_assets = path and path[-1] in {"asset_uids", "asset_epochs", "segment_starts",
            "uids", "excluded_reasons", "blocked_assets", "supported_h5_by_asset"}
        if not dynamic_assets and any(str(k).lower() in _RAW for k in value):
            raise BankMetadataError("RAW_VALUES_FORBIDDEN")
        for key, item in value.items():
            _metadata(item, path + (key,))
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            _metadata(item, path + (i,))
    elif value is not None and not isinstance(value, (str, bool, int, float)):
        raise BankMetadataError("METADATA_SCALARS_REQUIRED")


def projection_sha256(stages, reservations, artifact_checks, budget_scope, *,
                      reservation_receipt_ref, other_incremental_fit_units,
                      substate_artifacts=(), previous_bank_ref=None, synthetic=False):
    """Bind the caller's metadata verification; this never proves physical bytes."""
    return sha256_value(dict(stages=stages, reservations=reservations,
        artifact_checks=artifact_checks, budget_scope=budget_scope,
        reservation_receipt_ref=reservation_receipt_ref,
        other_incremental_fit_units=other_incremental_fit_units,
        substate_artifacts=list(substate_artifacts), previous_bank_ref=previous_bank_ref,
        synthetic=synthetic))


def build_risk_bank(stages, reservations, artifact_checks, budget_scope, *,
                    reservation_receipt_ref, verified_projection_sha256,
                    other_incremental_fit_units, substate_artifacts=(),
                    previous_bank_ref=None, synthetic=False):
    """Return metadata manifest + fixed count receipt from the sole ledger projection.

    Reservations need owner_stage_id assigned by the independent fixed projection.
    Stage audit cumulative counters are never interpreted as stage fit increments.
    Additive stages use a unique stage_id and retain all old stages/reservations.
    """
    if type(synthetic) is not bool:
        raise BankMetadataError("EXPLICIT_METADATA_MODE_REQUIRED")
    stages = [_only(s, _STAGE, "stage") for s in stages]
    reservations = [_only(e, _EVENT, "reservation") for e in reservations]
    for s in stages:
        s["audit"] = _only(s["audit"], _AUDIT, "audit")
        s["audit"]["nodes"] = [_only(n, _NODE, "node") for n in s["audit"]["nodes"]]
    _metadata([stages, reservations])
    expected = projection_sha256(stages, reservations, artifact_checks, budget_scope,
        reservation_receipt_ref=reservation_receipt_ref,
        other_incremental_fit_units=other_incremental_fit_units,
        substate_artifacts=substate_artifacts, previous_bank_ref=previous_bank_ref,
        synthetic=synthetic)
    if _sha(verified_projection_sha256) != expected:
        raise BankMetadataError("VERIFIED_PROJECTION_DIGEST_CHANGED")
    reservation_receipt_ref = _ref(reservation_receipt_ref)
    previous_bank_ref = _ref(previous_bank_ref) if previous_bank_ref else None
    other = _count(other_incremental_fit_units)
    prior = _count(budget_scope["prior_ledger"]["reserved"])
    for cap in ("branch_cumulative_cap", "effective_new_cap", "stage1_learned_cap"):
        _count(budget_scope[cap])
    if (prior, budget_scope["branch_cumulative_cap"], budget_scope["effective_new_cap"],
            budget_scope["stage1_learned_cap"]) != (968, 4096, 2048, 1024):
        raise BankMetadataError("FROZEN_B_BUDGET_SCOPE_REQUIRED")
    stage_map = {}
    for s in stages:
        sid = s["stage_id"]
        if not isinstance(sid, str) or not sid or sid in stage_map or not s.get("research_id"):
            raise BankMetadataError("UNIQUE_EXISTING_STAGE_IDENTITIES_REQUIRED")
        if s["domain_role"] not in {"FULL_REQUESTED_POOL", "SOURCE_QUALIFIED_COMPONENT", "ADDITIVE_RISK_CORRECTION",
                                     "COMPLETE_COMMON_COMPONENT"}:
            raise BankMetadataError("FROZEN_DOMAIN_ROLE_REQUIRED")
        a = s["audit"]
        for counter in ("account_attempts", "test2026_rows_read", "retry_limit"):
            _count(a.get(counter))
        if (a.get("schema") != "B_R3_RISK_STAGE_COMPACT_AUDIT_V1"
                or a.get("account_attempts") != 0 or a.get("test2026_rows_read") != 0
                or a.get("strict_PIT_promotion_eligible") is not False
                or a.get("no_refund") is not True or a.get("retry_limit") != 0):
            raise BankMetadataError("CONDITIONAL_SOURCE_ONLY_AUDIT_REQUIRED")
        for field in ("science_ref", "source_inputs_ref", "support_ref", "execution_ref", "audit_ref"):
            s[field] = _ref(s[field])
        pins = [_ref(p) for p in s["producer_code_pins"]]
        if not pins or len({p["path"] for p in pins}) != len(pins):
            raise BankMetadataError("UNIQUE_PRODUCER_CODE_PINS_REQUIRED")
        s["producer_code_pins"] = pins
        for field in ("risk_fit_units", "actual_new_fit_units", "b_cumulative_fit_units", "stage_new_fit_units"):
            if field in a:
                _count(a[field])
        if "actual_new_fit_units" in a and "b_cumulative_fit_units" in a:
            if a["b_cumulative_fit_units"] != prior + a["actual_new_fit_units"]:
                raise BankMetadataError("AUDIT_CUMULATIVE_COUNTER_CONFLICT")
        if s["domain_role"] == "COMPLETE_COMMON_COMPONENT" and s["research_id"] != _COMPLETE_STUDY_ID:
            raise BankMetadataError("COMPLETE_COMMON_SCIENTIFIC_IDENTITY_REQUIRED")
        stage_map[sid] = s
    if not stage_map:
        raise BankMetadataError("FIXED_STAGE_AUDITS_REQUIRED")
    seen_stages = set()
    for s in stages:
        if set(s.get("parent_stage_ids", ())) - seen_stages:
            raise BankMetadataError("ADDITIVE_PARENT_STAGE_MISSING")
        if s["domain_role"] in {"ADDITIVE_RISK_CORRECTION", "COMPLETE_COMMON_COMPONENT"} and not s.get("parent_stage_ids"):
            raise BankMetadataError("ADDITIVE_PARENT_BINDING_REQUIRED")
        seen_stages.add(s["stage_id"])
    events = {}
    for e in reservations:
        key, kind = _sha(e["key"]), e["kind"]
        if key in events:
            raise BankMetadataError("DUPLICATE_PHYSICAL_RESERVATION")
        if kind not in {"scaler", "covariance", "regime_threshold", "jackknife_subfit",
                        "horizon", "deterministic_transform"} or e["owner_stage_id"] not in stage_map:
            raise BankMetadataError("RISK_RESERVATION_SCOPE_REQUIRED")
        if not isinstance(e.get("status"), str) or not e["status"]:
            raise BankMetadataError("RESERVATION_STATUS_REQUIRED")
        if e.get("corrected_rr_node"):
            owner = stage_map[e["owner_stage_id"]]
            if (owner["domain_role"] != "ADDITIVE_RISK_CORRECTION"
                    or e.get("correction_freeze_sha256") != owner["execution_ref"]["sha256"]):
                raise BankMetadataError("CORRECTED_EVENT_EXECUTION_OWNER_CONFLICT")
        owner = stage_map[e["owner_stage_id"]]
        if owner["domain_role"] == "COMPLETE_COMMON_COMPONENT" and not e.get("complete_common_node"):
            raise BankMetadataError("COMPLETE_EVENT_PROVENANCE_REQUIRED")
        if e.get("complete_common_node"):
            owner = stage_map[e["owner_stage_id"]]
            if (e.get("corrected_rr_node") or owner["domain_role"] != "COMPLETE_COMMON_COMPONENT"
                    or e.get("complete_execution_freeze_sha256") != owner["execution_ref"]["sha256"]):
                raise BankMetadataError("COMPLETE_EVENT_EXECUTION_OWNER_CONFLICT")
            tagged = [n for n in owner["audit"]["nodes"] if n["risk_node"] == e["complete_common_node"]]
            if (len(tagged) != 1 or not e["complete_common_node"].startswith("complete:")
                    or key not in tagged[0].get("fit_dependency_ids", ())
                    or _time(e.get("complete_group_as_of")) != _time(tagged[0]["as_of"])):
                raise BankMetadataError("COMPLETE_EVENT_NODE_CLOSURE_UNBOUND")
        _count(e["learned_states"])
        if e["learned_states"] != int(kind in LEARNED_KINDS):
            raise BankMetadataError("PHYSICAL_KIND_COST_CONFLICT")
        ctx = e["context"]
        _time(ctx["cutoff"])
        if ctx.get("synthetic") is not synthetic or ctx.get("mechanism") is not (not synthetic):
            raise BankMetadataError("EXECUTION_MODE_CONFLICT")
        _sha(e["inputs_sha256"])
        if content_hash(dict(kind=kind, name=e["name"], context=ctx,
                             inputs_sha256=e["inputs_sha256"], parameters=e["parameters"])) != key:
            raise BankMetadataError("PHYSICAL_OPERATION_KEY_CONFLICT")
        if e["status"] in _COMPLETE:
            _sha(e.get("result_sha256"))
        events[key] = e
    for e in reservations:
        if set(e.get("dependencies", ())) - set(events):
            raise BankMetadataError("PHYSICAL_CHILD_KEY_MISSING")
    total = sum(e["learned_states"] for e in reservations)
    if total > 1024 or total + other > 2048 or prior + total + other > 4096:
        raise BankMetadataError("FROZEN_B_CAP_EXCEEDED")
    diagnostics, entries, stage_receipts, all_used = [], [], [], set()
    for s in stages:
        sid, node_ids, used = s["stage_id"], set(), set()
        owned = [e for e in reservations if e["owner_stage_id"] == sid]
        owned_units = sum(e["learned_states"] for e in owned)
        if "stage_new_fit_units" in s["audit"] and s["audit"]["stage_new_fit_units"] != owned_units:
            raise BankMetadataError("STAGE_ADMINISTRATIVE_INCREMENT_CONFLICT")
        if s["domain_role"] == "COMPLETE_COMMON_COMPONENT":
            groups = {_time(e["complete_group_as_of"]) for e in owned}
            if owned_units > 341 or any(sum(e["learned_states"] for e in owned if _time(e["complete_group_as_of"]) == g) > 31 for g in groups):
                raise BankMetadataError("COMPLETE_DIAGNOSTIC_SCOPE_CAP_EXCEEDED")
        stage_diagnostics = []
        for n in s["audit"]["nodes"]:
            nid = n["risk_node"]
            if not isinstance(nid, str) or not nid or not isinstance(n.get("status"), str) or not n["status"]:
                raise BankMetadataError("NODE_ID_AND_STATUS_REQUIRED")
            if nid in node_ids or n["method"] not in METHODS:
                raise BankMetadataError("UNIQUE_FROZEN_DIRECTION_NODES_REQUIRED")
            node_ids.add(nid)
            if "domain_role" in n and n["domain_role"] != s["domain_role"]:
                raise BankMetadataError("NODE_DOMAIN_ROLE_CONFLICT")
            if "risk_complete_common_science_sha256" in n and (
                    s["domain_role"] != "COMPLETE_COMMON_COMPONENT"
                    or n["risk_complete_common_science_sha256"] != s["science_ref"]["sha256"]):
                raise BankMetadataError("NODE_COMPLETE_SCIENCE_PIN_CONFLICT")
            if "complete_execution_freeze_sha256" in n and (
                    s["domain_role"] != "COMPLETE_COMMON_COMPONENT"
                    or n["complete_execution_freeze_sha256"] != s["execution_ref"]["sha256"]):
                raise BankMetadataError("NODE_COMPLETE_EXECUTION_PIN_CONFLICT")
            if n.get("strict_PIT_promotion_eligible", False) is not False:
                raise BankMetadataError("NODE_STRICT_PROMOTION_FORBIDDEN")
            cutoff, asof = _time(n["cutoff"]), _time(n["as_of"])
            if cutoff >= asof:
                raise BankMetadataError("PRIOR_FIT_CUTOFF_REQUIRED")
            keys = n.get("fit_dependency_ids", [])
            if len(set(keys)) != len(keys) or set(keys) - set(events):
                raise BankMetadataError("NODE_DEPENDENCY_KEY_INVALID")
            used.update(keys)
            reasons = []
            if s["domain_role"] == "COMPLETE_COMMON_COMPONENT" and (n["status"] in _PASS or n.get("domain_comparison")):
                proof = _complete_domain_proof(n, s, stage_map)
                if proof["relation"] == "REUSE_REQUIRED":
                    if not n.get("exact_reuse_receipt_ref"):
                        reasons.append("COMPLETE_WHOLE_INPUT_REUSE_UNPROVED")
                    else:
                        n["exact_reuse_receipt_ref"] = _ref(n["exact_reuse_receipt_ref"])
            if any(set(events[k].get("dependencies", ())) - set(keys) for k in keys):
                reasons.append("NODE_PHYSICAL_CLOSURE_INCOMPLETE")
            if n["status"] not in _PASS:
                reasons.append("ORIGINAL_NODE_NOT_PASS:" + n["status"])
            elif n["status"] != ("PASS_SYNTHETIC" if synthetic else "PASS_FROZEN_HISTORY_MECHANISM"):
                reasons.append("NODE_EXECUTION_MODE_CONFLICT")
            if not any(events[k]["kind"] in {"covariance", "jackknife_subfit"} for k in keys):
                reasons.append("RISK_COVARIANCE_CLOSURE_UNBOUND")
            if n["status"] in _PASS and not n.get("risk_state_id"):
                reasons.append("RISK_STATE_ID_UNBOUND")
            if not keys:
                reasons.append("PHYSICAL_CLOSURE_UNBOUND")
            assets = n.get("assets", [])
            if len(set(assets)) != len(assets):
                raise BankMetadataError("ASSET_ORDER_OR_UID_AMBIGUOUS")
            if n["status"] in _PASS and (not assets or set(n.get("asset_uids", {})) != set(assets)
                    or any(not n["asset_uids"][x] for x in assets)
                    or len(set(n["asset_uids"].values())) != len(assets)):
                raise BankMetadataError("PASS_ASSET_UID_BINDING_REQUIRED")
            for key in keys:
                e = events[key]
                if e["status"] not in _COMPLETE:
                    reasons.append("DEPENDENCY_NOT_COMPLETE:" + key)
                ctx = e["context"]
                if _time(ctx["cutoff"]) != cutoff or list(ctx["assets"]) != list(assets):
                    raise BankMetadataError("NODE_PHYSICAL_CONTEXT_CONFLICT")
                if ctx["identity_epoch"]["uids"] != n.get("asset_uids", {}):
                    raise BankMetadataError("NODE_PHYSICAL_UID_CONFLICT")
            artifact = None
            if n.get("artifact") and n.get("sha256"):
                artifact = _ref(dict(path=n["artifact"], sha256=n["sha256"]))
                if artifact_checks.get(artifact["path"]) != artifact["sha256"]:
                    reasons.append("ARTIFACT_PHYSICAL_HASH_UNKNOWN_OR_MISMATCH")
            else:
                reasons.append("ARTIFACT_REFERENCE_UNKNOWN")
            record = dict(stage_id=sid, research_id=s["research_id"], domain_role=s["domain_role"],
                risk_node=nid, method=n["method"], as_of=n["as_of"], cutoff=n["cutoff"],
                original_status=n["status"], risk_state_id=n.get("risk_state_id"),
                run_started_utc=n.get("started_utc"),
                assets=assets, asset_uids=n.get("asset_uids", {}), asset_epochs=n.get("asset_epochs", {}),
                artifact=artifact, physical_dependency_ids=keys, reusable=not reasons,
                source_contract=s["science_ref"], producer_code_pins=s["producer_code_pins"],
                exact_reuse_only=True, automatic_refit=False, strict_PIT_promotion_eligible=False,
                quote_qualified=False, certified=False, account_qualification_granted=False,
                full_pool_policy_qualification_granted=False,
                riskstate_artifact_retains_all_substate_values=False,
                component_metadata={k: n[k] for k in ("parent_requested", "parent_origin_window",
                    "excluded_reasons", "snapshot_roles", "domain_comparison", "exact_reuse_receipt_ref") if k in n},
                recovery_metadata={k: n[k] for k in ("status_before_recovery", "recovery_audit_sha256", "engineering_failure_preserved") if k in n},
                correction_metadata={k: n[k] for k in ("research_id", "correction_envelope",
                    "correction_activation_sha256", "correction_freeze_sha256") if k in n})
            if n.get("risk_state_id"):
                _sha(n["risk_state_id"])
            if reasons:
                record.update(admission="DIAGNOSTIC_ONLY", reasons=sorted(set(reasons)),
                    original_block_reason=n.get("block_reason"), original_block_reasons=n.get("block_reasons", []))
                diagnostics.append(record)
                stage_diagnostics.append(nid)
            else:
                record["admission"] = "CONDITIONAL_SOURCE_ONLY_EXACT_STATE"
                entries.append(record)
        all_used.update(used)
        if "expected_node_count" in s:
            _count(s["expected_node_count"])
        stage_receipts.append(dict(stage_id=sid, research_id=s["research_id"],
            producer_stage_complete=s.get("producer_complete") is True,
            expected_node_count=s.get("expected_node_count"),
            node_count=len(s["audit"]["nodes"]),
            physical_events=len(owned), learned_fit_units=sum(e["learned_states"] for e in owned),
            per_kind={k: sum(e["kind"] == k for e in owned) for k in KINDS},
            node_recorded_increment_sum=sum(_count(n.get("learned_states", 0)) for n in s["audit"]["nodes"]),
            original_status_counts={k: sum(n["status"] == k for n in s["audit"]["nodes"])
                                   for k in sorted({n["status"] for n in s["audit"]["nodes"]})},
            observed_cumulative_counters={k: s["audit"][k] for k in
                ("risk_fit_units", "actual_new_fit_units", "b_cumulative_fit_units") if k in s["audit"]},
            diagnostic_node_ids=stage_diagnostics, bindings={k: s[k] for k in
                ("science_ref", "source_inputs_ref", "support_ref", "execution_ref", "audit_ref", "producer_code_pins")}))
    unfinished = [e["key"] for e in reservations if e["status"] not in _COMPLETE | _FAILED]
    failed = [e["key"] for e in reservations if e["status"] in _FAILED]
    orphan = sorted(set(events) - all_used)
    substates = []
    substate_keys = set()
    for raw in substate_artifacts:
        v = _only(raw, {"operation_key", "value_sha256", "artifact"}, "substate")
        if v["operation_key"] in substate_keys:
            raise BankMetadataError("DUPLICATE_RETAINED_SUBSTATE")
        substate_keys.add(v["operation_key"])
        e = events.get(v["operation_key"])
        if not e or e["status"] not in _COMPLETE or v["value_sha256"] != e["result_sha256"]:
            raise BankMetadataError("SUCCESSFUL_ORIGINAL_SUBSTATE_BINDING_REQUIRED")
        v["artifact"] = _ref(v["artifact"])
        if artifact_checks.get(v["artifact"]["path"]) != v["artifact"]["sha256"]:
            raise BankMetadataError("SUBSTATE_VALUE_ARTIFACT_NOT_VERIFIED")
        substates.append(v)
    receipt = dict(schema="B_R3_FIXED_RISK_COUNT_RECEIPT_V1",
        authority="PROJECTION_OF_EXISTING_DURABLE_RISK_LEDGER", not_a_new_trial_ledger=True,
        authoritative_reservation_receipt=reservation_receipt_ref, verified_projection_sha256=expected,
        physical_event_keys=list(events), physical_events_total=len(events), learned_risk_fit_units=total,
        per_kind={k: sum(e["kind"] == k for e in reservations) for k in KINDS},
        per_status={k: sum(e["status"] == k for e in reservations) for k in sorted({e["status"] for e in reservations})},
        stages=stage_receipts, inherited_B_reserved=prior, other_incremental_fit_units=other,
        incremental_fit_units=total+other, B_cumulative_fit_units=prior+total+other,
        caps=dict(risk_stage=1024, incremental=2048, B_branch=4096), no_refund=True, automatic_retry=False,
        failed_reservations=failed, unfinished_reservations=unfinished, unassigned_node_closure_keys=orphan,
        projectwide_historical_fit_units="UNKNOWN", projectwide_global_verified=False)
    incomplete = bool(unfinished or orphan or any(
        s["node_recorded_increment_sum"] != s["learned_fit_units"]
        or not s["producer_stage_complete"] or s["expected_node_count"] != s["node_count"]
        for s in stage_receipts))
    manifest = dict(schema="B_R3_CONDITIONAL_RISK_BANK_METADATA_V1",
        stage_status="PARTIAL_OR_UNFINISHED" if incomplete else "COMPLETE_WITH_TYPED_DIAGNOSTICS",
        synthetic_metadata_test=synthetic, previous_bank=previous_bank_ref,
        state_contract=risk_state_contract(), states=entries, blocked_or_unverified_diagnostics=diagnostics,
        physical_operation_bindings=reservations,
        learned_substate_artifacts=substates, standalone_substate_reuse_requires_retained_value_artifact=True,
        fixed_count_receipt_sha256=sha256_value(receipt),
        reuse_scope="Exact source semantics, eligible inputs, cutoff, ordered assets/UID/epoch, coordinate/horizon, parameters and producer pins only.",
        component_scope="Partial and complete common component states never qualify the parent full pool or fill unknown asset risk; complete describes observation support only within the selected domain.",
        no_new_information_source=True, strict_PIT_promotion_eligible=False, quote_qualified=False,
        certified=False, account_qualification_granted=False, full_pool_policy_qualification_granted=False,
        new_model_deserializations=0, new_fits=0, new_account_paths=0, test2026_rows_read=0)
    return dict(manifest=manifest, fixed_count_receipt=receipt,
                manifest_sha256=sha256_value(manifest), fixed_count_receipt_sha256=sha256_value(receipt))


def project_fixed_reservations(stages, physical_events, *, full_stage_id,
                               component_stage_id, verified_full_operation_keys,
                               correction_stage_id=None, complete_stage_id=None):
    """Assign one owner using fixed metadata evidence; never use array position.

    Caller projects fixed ledger fields without decoding learned values. The full
    key set must already be independently verified against the completed full run.
    RR tags are actual producer lineage, not labels inferred from direction names.
    Unclaimed events require explicit investigation; this function never guesses.
    """
    stage_map = {s["stage_id"]: s for s in stages}
    owners = [full_stage_id, component_stage_id] + [sid for sid in (correction_stage_id, complete_stage_id) if sid is not None]
    if len(set(owners)) != len(owners):
        raise BankMetadataError("DISTINCT_PHYSICAL_OWNER_STAGES_REQUIRED")
    if len(stage_map) != len(stages) or full_stage_id not in stage_map or component_stage_id not in stage_map:
        raise BankMetadataError("FIXED_PHASE_STAGES_REQUIRED")
    if any(sid not in stage_map for sid in owners):
        raise BankMetadataError("CORRECTION_STAGE_BINDING_REQUIRED")
    closure = {sid: {k for n in s["audit"]["nodes"] for k in n.get("fit_dependency_ids", ())}
               for sid, s in stage_map.items()}
    full_keys = set(verified_full_operation_keys)
    if len(full_keys) != len(verified_full_operation_keys) or closure[full_stage_id] != full_keys:
        raise BankMetadataError("VERIFIED_FULL_KEYS_AND_AUDIT_CLOSURE_REQUIRED")
    result, seen = [], set()
    allowed = (_EVENT - {"owner_stage_id"}) | {"stage", "started_utc", "synthetic", "mechanism"}
    for raw in physical_events:
        e = _only(raw, allowed, "fixed_physical_event")
        _metadata(e)
        key = _sha(e["key"])
        if key in seen:
            raise BankMetadataError("DUPLICATE_PHYSICAL_RESERVATION")
        seen.add(key)
        tag = e.get("corrected_rr_node")
        complete_tag = e.get("complete_common_node")
        if complete_tag:
            if key in full_keys or tag or complete_stage_id is None or not isinstance(complete_tag, str) or not complete_tag.startswith("complete:"):
                raise BankMetadataError("COMPLETE_EVENT_OWNER_CONFLICT")
            nodes = {n["risk_node"]: n for n in stage_map[complete_stage_id]["audit"]["nodes"]}
            if complete_tag not in nodes or key not in nodes[complete_tag].get("fit_dependency_ids", ()):
                raise BankMetadataError("COMPLETE_EVENT_CLOSURE_UNBOUND")
            if _sha(e.get("complete_execution_freeze_sha256")) != stage_map[complete_stage_id]["execution_ref"]["sha256"]:
                raise BankMetadataError("COMPLETE_EVENT_FREEZE_UNBOUND")
            if _time(e.get("complete_group_as_of")) != _time(nodes[complete_tag]["as_of"]):
                raise BankMetadataError("COMPLETE_EVENT_GROUP_UNBOUND")
            owner = complete_stage_id
        elif tag:
            if (key in full_keys or correction_stage_id is None
                    or not isinstance(tag, str) or not tag.startswith("corrected_rr:")):
                raise BankMetadataError("CORRECTED_EVENT_OWNER_CONFLICT")
            nodes = {n["risk_node"] for n in stage_map[correction_stage_id]["audit"]["nodes"]}
            if tag not in nodes:
                raise BankMetadataError("CORRECTED_EVENT_NODE_UNBOUND")
            if _sha(e.get("correction_freeze_sha256")) != stage_map[correction_stage_id]["execution_ref"]["sha256"]:
                raise BankMetadataError("CORRECTED_EVENT_FREEZE_UNBOUND")
            owner = correction_stage_id
        elif key in full_keys:
            owner = full_stage_id
        elif key in closure[component_stage_id]:
            owner = component_stage_id
        else:
            raise BankMetadataError("PHYSICAL_OWNER_UNPROVEN:" + key)
        for mode in ("synthetic", "mechanism"):
            if mode in e and e[mode] is not e["context"].get(mode):
                raise BankMetadataError("PHYSICAL_EVENT_CONTEXT_MODE_CONFLICT")
            e.pop(mode, None)
        e.pop("stage", None)
        e.pop("started_utc", None)
        e["owner_stage_id"] = owner
        result.append(e)
    if full_keys - seen:
        raise BankMetadataError("VERIFIED_FULL_EVENT_MISSING")
    return result

# The scanner below reuses the one-off full execution review's Projection core.
# Only the fixed indent=2 risk producer schemas are accepted; no file I/O lives here.
_PROJECTION_SKIP = {"notes", "error", "implementation_lineage", "snapshot_roles"}
_LEDGER_ROOT = {"status", "fit_attempts", "inherited_fit_units", "new_fit_units",
    "risk_fit_units", "records", "failures", "physical_events", "account_paths",
    "test2026_rows_read", "rr_correction_activation", "engineering_recovery_audits",
    "complete_common_activation"}
_AUDIT_ROOT = _AUDIT | {"execution_freeze_sha256", "implementation_lineage",
    "risk_support_sha256", "inherited_prior_reserved", "workers", "library_threads",
    "projections", "research_id", "risk_component_science_sha256", "forecast_fits",
    "notes", "corrected_rr_nodes", "rr_correction"}
_COMPLETE_AUDIT_ROOT = _AUDIT_ROOT | {"domain_role", "risk_complete_common_science_sha256",
    "source_inputs_sha256", "activation_receipt_sha256", "max_additional_learned_units",
    "max_group_learned_units", "account_equivalence"}
_CONTEXT_FIELDS = {"source_identity", "cutoff", "assets", "return_coordinate",
    "horizon", "identity_epoch", "synthetic", "mechanism"}
_SOURCE_FIELDS = {"id", "version", "sha256", "source_id", "execution_semantics"}
_SEMANTICS_FIELDS = {"scientific_contract_sha256", "status", "return_coordinate",
    "identity_epoch", "strict_PIT_promotion_eligible", "historical_authority_status",
    "quote_qualified", "observation_time_assumed", "assumed_observation_at",
    "actual_snapshot_timestamp", "benchmark_proxy_allowed"}
_PARAMETER_FIELDS = {"seed", "configs", "seeds", "window", "min_observations",
    "variance_floor", "numerical_ridge_relative", "numerical_ridge_absolute",
    "missing_returns", "unknown_assets", "maturity", "assume_centered",
    "n_components", "svd_solver", "decay", "weights", "fit_cutoff", "return_unit",
    "return_horizon_sessions", "source_id", "information_set_id", "horizons", "scales"}
_ENVELOPE_FIELDS = {"research_id", "correction_freeze_sha256", "correction_spec_sha256",
    "parent_component_science_sha256", "parent_component_execution_sha256",
    "parent_component_support_sha256", "source_inputs_sha256", "method", "as_of",
    "cutoff", "assets", "asset_uids", "asset_epochs", "qqq_open_lookback_sessions",
    "rr_input_binding_changed", "original_rr_execution", "account_equivalence",
    "strict_PIT_promotion_eligible"}
_RR_SUMMARY_FIELDS = {"research_id", "correction_freeze_sha256", "correction_spec_sha256",
    "activation_receipt_sha256", "learned_fit_units", "completed_nodes", "max_quarters",
    "per_quarter_cap", "original_rr_reexecuted", "original_component_nodes_preserved",
    "stock_preprocessing_new_fit_units", "account_equivalence", "strict_PIT_promotion_eligible"}
_UID_MAPS = {"asset_uids", "asset_epochs", "segment_starts", "uids"}
_STRING_ARRAYS = {"assets", "fit_dependency_ids", "dependencies", "block_reasons",
    "parent_origin_window", "columns", "exact_tickers"}


def _fixed_field(path, key, profile):
    if not path:
        allowed = _LEDGER_ROOT if profile == "ledger" else _COMPLETE_AUDIT_ROOT if profile == "complete_audit" else _AUDIT_ROOT
    elif path[0] in {"nodes", "records", "corrected_rr_nodes"} and len(path) == 2:
        allowed = _NODE | _PROJECTION_SKIP | {"started_utc"}
        if profile not in {"complete_audit", "ledger"}:
            allowed = allowed - {"domain_comparison", "exact_reuse_receipt_ref", "domain_role",
                "risk_complete_common_science_sha256", "complete_execution_freeze_sha256"}
    elif path[0] == "physical_events" and len(path) == 2:
        allowed = (_EVENT - {"owner_stage_id"}) | {"synthetic", "mechanism", "stage", "started_utc"}
    elif path[0] == "failures" and len(path) == 2:
        allowed = {"risk_node", "key", "kind", "name", "error"}
    elif path[0] == "projections" and len(path) == 2:
        allowed = {"source", "columns", "start", "stop", "day", "exact_tickers", "maturity_predicate", "rows"}
    elif path[0] == "engineering_recovery_audits" and len(path) == 2:
        allowed = {"path", "sha256"}
    elif path == ("rr_correction_activation",):
        allowed = {"path", "sha256", "correction_freeze_sha256"}
    elif path == ("complete_common_activation",):
        allowed = {"path", "sha256", "execution_freeze_sha256"}
    elif path == ("rr_correction",):
        allowed = _RR_SUMMARY_FIELDS
    elif path[-1] == "context":
        allowed = _CONTEXT_FIELDS
    elif path[-1] == "source_identity":
        allowed = _SOURCE_FIELDS
    elif path[-1] == "execution_semantics":
        allowed = _SEMANTICS_FIELDS
    elif path[-1] == "identity_epoch":
        allowed = {"epoch", "uids"}
    elif path[-1] == "parameters":
        allowed = _PARAMETER_FIELDS
    elif path[-1] == "exact_reuse_receipt_ref":
        allowed = {"path", "sha256"}
    elif path[-1] == "domain_comparison":
        allowed = _DOMAIN_COMPARISON_FIELDS
    elif path[-1] == "correction_envelope":
        allowed = _ENVELOPE_FIELDS
    elif path[-1] == "parent_requested":
        allowed = {"assets", "asset_uids", "asset_epochs", "segment_starts", "blocked_assets"}
    elif path[-1] in {"prior_partial_domain", "complete_domain"}:
        allowed = _DOMAIN_FIELDS
    elif path[-1] in _UID_MAPS | {"excluded_reasons", "blocked_assets", "supported_h5_by_asset"}:
        return True  # Dynamic asset keys; values are shape-checked before decoding.
    else:
        raise BankMetadataError("FIXED_PRODUCER_METADATA_PATH_UNKNOWN")
    if key not in allowed:
        raise BankMetadataError("FIXED_PRODUCER_FIELD_UNKNOWN:" + str(key))
    return key not in _PROJECTION_SKIP


def _fixed_shape(path, token):
    if len(path) > 1 and path[-2] in _UID_MAPS | {"supported_h5_by_asset"}:
        if token not in '"n-0123456789':
            raise BankMetadataError("FLAT_IDENTITY_METADATA_REQUIRED")
    if isinstance(path[-1] if path else None, int):
        field = path[-2]
        if field in _STRING_ARRAYS and token != '"':
            raise BankMetadataError("STRING_METADATA_ARRAY_REQUIRED")
        if len(path) > 2 and path[-3] in {"excluded_reasons", "blocked_assets"} and token != '"':
            raise BankMetadataError("STRING_DIAGNOSTIC_METADATA_REQUIRED")


class _FixedProducerProjection:
    def __init__(self, lines, profile, max_line_chars):
        self.lines, self.profile = iter(lines), profile
        self.max_line_chars, self.depth = max_line_chars, 0
        self.line, self.position, self.line_number = "", 0, 0
        self.c = self.read()

    def read(self):
        if self.position == len(self.line):
            line = next(self.lines, None)
            if line is None:
                return ""
            if not isinstance(line, str) or not line.endswith("\n") or len(line) > self.max_line_chars:
                raise BankMetadataError("BOUNDED_FIXED_WRITER_LINE_REQUIRED")
            body = line.rstrip("\r\n")
            indent = len(body) - len(body.lstrip(" "))
            expected = 2*(self.depth - int(body.lstrip(" ").startswith(("}", "]"))))
            if indent != expected or "\t" in body[:indent] or not body.strip():
                raise BankMetadataError("FIXED_WRITER_INDENT2_REQUIRED")
            if self.line_number == 0 and body != "{":
                raise BankMetadataError("FIXED_WRITER_ROOT_OBJECT_REQUIRED")
            self.line, self.position = line, 0
            self.line_number += 1
        c = self.line[self.position]
        self.position += 1
        return c

    def step(self):
        old, self.c = self.c, self.read()
        return old

    def ws(self):
        while self.c and self.c.isspace():
            self.step()

    def string(self, decode):
        out = ['"'] if decode else None
        self.step()
        escaped = False
        while self.c:
            c = self.step()
            if decode:
                out.append(c)
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                return json.loads("".join(out)) if decode else None
        raise BankMetadataError("UNTERMINATED_FIXED_JSON_STRING")

    def value(self, path=(), keep=True):
        self.ws()
        if keep:
            _fixed_shape(path, self.c)
        if self.c == '"':
            return self.string(keep)
        if self.c and self.c in "{[":
            opening = self.step()
            closing = "}" if opening == "{" else "]"
            self.depth += 1
            out = ({} if opening == "{" else []) if keep else None
            if self.c == closing:
                self.step()
                self.depth -= 1
                return out
            if self.c not in "\r\n":
                raise BankMetadataError("FIXED_WRITER_MULTILINE_CONTAINER_REQUIRED")
            self.ws()
            i, seen = 0, set()
            while True:
                if opening == "{":
                    if self.c != '"':
                        raise BankMetadataError("FIXED_JSON_OBJECT_KEY_REQUIRED")
                    key = self.string(keep)
                    if self.step() != ":" or self.step() != " ":
                        raise BankMetadataError("FIXED_WRITER_KEY_SEPARATOR_REQUIRED")
                    if keep and key in seen:
                        raise BankMetadataError("DUPLICATE_FIXED_METADATA_KEY")
                    seen.add(key)
                    include = keep and _fixed_field(path, key, self.profile)
                    item = self.value(path + (key,), include)
                    if include:
                        out[key] = item
                else:
                    item = self.value(path + (i,), keep)
                    if keep:
                        out.append(item)
                    i += 1
                self.ws()
                delimiter = self.step()
                if delimiter == closing:
                    self.depth -= 1
                    return out
                if delimiter != "," or self.c not in "\r\n":
                    raise BankMetadataError("FIXED_WRITER_CONTAINER_SEPARATOR_REQUIRED")
                self.ws()
        out = [] if keep else None
        consumed = 0
        while self.c and self.c not in ",]}" and not self.c.isspace():
            c = self.step()
            consumed += 1
            if keep:
                out.append(c)
        if not consumed:
            raise BankMetadataError("FIXED_JSON_SCALAR_REQUIRED")
        return json.loads("".join(out)) if keep else None

    def parse(self):
        out = self.value()
        self.ws()
        if self.c or self.depth:
            raise BankMetadataError("FIXED_JSON_TRAILING_OR_INCOMPLETE_CONTENT")
        return out


def project_fixed_producer_lines(lines, *, profile, max_line_chars=65536):
    """Reuse the full review scanner on fixed producer lines, without any I/O.

    Root supplies an iterator from a pinned, stable file with bounded readline,
    closes it with its own with-statement, and separately verifies physical SHA.
    Whole notes/error/lineage payloads are scanned without JSON value decoding.
    """
    if profile not in {"full_audit", "component_audit", "complete_audit", "ledger"}:
        raise BankMetadataError("FIXED_PRODUCER_PROFILE_REQUIRED")
    if type(max_line_chars) is not int or not 1024 <= max_line_chars <= 65536:
        raise BankMetadataError("BOUNDED_PROJECTION_LINE_LIMIT_REQUIRED")
    out = _FixedProducerProjection(lines, profile, max_line_chars).parse()
    if profile == "ledger":
        if not {"status", "records", "physical_events", "new_fit_units", "risk_fit_units",
                "fit_attempts", "inherited_fit_units"}.issubset(out):
            raise BankMetadataError("FIXED_LEDGER_METADATA_SCHEMA_REQUIRED")
    elif out.get("schema") != "B_R3_RISK_STAGE_COMPACT_AUDIT_V1" or "nodes" not in out:
        raise BankMetadataError("FIXED_RISK_AUDIT_SCHEMA_REQUIRED")
    if profile == "complete_audit" and (out.get("research_id") != _COMPLETE_STUDY_ID
            or out.get("domain_role") != "COMPLETE_COMMON_COMPONENT"
            or out.get("max_additional_learned_units", 341) != 341
            or out.get("max_group_learned_units", 31) != 31
            or out.get("account_equivalence", False) is not False):
        raise BankMetadataError("COMPLETE_AUDIT_SCIENTIFIC_SCOPE_REQUIRED")
    return out
