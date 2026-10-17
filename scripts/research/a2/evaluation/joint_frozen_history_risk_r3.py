"""Bounded frozen-history risk CLI; one input helper, engine and fit ledger.

Support reads metadata only. Fit is opened only by the existing managed run's
source/support/code/budget freeze. This adapter owns no labels, estimators,
accounting, provider client, source authority or research registry.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import gc
import hashlib
import json
import os
import time
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
from threadpoolctl import threadpool_limits

from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.data.shared_risk_inputs_r3 import (
    assemble_risk_inputs, correct_rr_qqq_source_range, STOCK_METADATA,
    STORED_LABEL_COORDINATE, _clock, _calendar)
from scripts.research.a2.risk.shared_risk_engine_r2 import (
    SharedRiskEngine, SourceReceipt, METHODS, SCHEDULE, COORDINATE,
    BENCHMARK_PROXY_COORDINATE)
from scripts.research.a2.risk.shared_risk_budget_r2 import (
    StateBudget, LEARNED_KINDS, content_hash)
from scripts.research.a2.evaluation.joint_method_stages import task_writer

REPO = Path(__file__).resolve().parents[4]
BOUNDARY = pd.Timestamp("2026-01-01")
FEATURE_TAGS = ("FROZEN_RAW_A2_TRAINING_MATRIX_32",
                "FROZEN_RAW_A2_FULL_PIT32_LEDGER_PROJECTION")
FEATURE_META = ("ticker", "signal_date", "security_id", "feature_available",
                "all_features_finite", "feature_source")
LABEL_META = tuple(c for c in STOCK_METADATA if c != "security_id")
SOURCE_NAMES = ("ret1d_fixed32", "membership_uid", "raw_open_close", "shareholder_y5",
                "prediction_features", "calendar", "uid_intervals", "share_ca_audit",
                "ff48_surface", "extended_shareholder_y5")
COMPLETE_ID = "V24_B_COMPLETE_COMMON_H5_FF48_RISK_DIAGNOSTIC_R1"
COMPLETE_SCIENCE_SCHEMA = "B_R3_COMPLETE_COMMON_H5_FF48_SCIENCE_V1"
RR_CORRECTION_ID = "V24_B_RR_SOURCE_WINDOW_BINDING_CORRECTION_R1"
RR_CORRECTION_SCHEMA = "B_R3_RR_SOURCE_WINDOW_BINDING_CORRECTION_V1"
RR_CORRECTION_ASOFS = (
    "2024-07-01T20:00:00+00:00", "2024-10-01T20:00:00+00:00",
    "2025-01-02T21:00:00+00:00", "2025-04-01T20:00:00+00:00",
    "2025-07-01T20:00:00+00:00", "2025-10-01T20:00:00+00:00")
FORBIDDEN = {"y_open5", "raw_a2_prediction", "raw_a2_rank", "a1_rank", "ret_1d",
             "open", "close", "alpha", "beta"}


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _json(value):
    if isinstance(value, dict):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime, Path)):
        return str(value)
    if isinstance(value, np.generic):
        return _json(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _json_write_view(value):
    """Read-only synchronous serialization view; _json keeps copy isolation."""
    if isinstance(value, dict):
        converted = {str(k): _json_write_view(v) for k, v in value.items()}
        if (type(value) is dict and len(converted) == len(value)
                and all(type(k) is str and converted[k] is v for k, v in value.items())):
            return value
        return converted
    if isinstance(value, (list, tuple)):
        converted = [_json_write_view(v) for v in value]
        if type(value) is list and all(a is b for a, b in zip(converted, value)):
            return value
        return converted
    return _json(value)


def read_json(path):
    path = Path(path)
    # Only the three fixed metadata support documents receive a larger bound.
    mb = 256 if path.name == "FIT_STATUS.json" and path.parent.name == "work" else (
        128 if path.name in {"RISK_SUPPORT.json", "RISK_COMPONENT_SUPPORT.json", "RISK_COMPLETE_COMMON_SUPPORT.json"} else 32)
    limit = mb * 1024 * 1024
    if path.stat().st_size > limit:
        raise ValueError("COMPACT_METADATA_LIMIT:" + path.name)
    return json.loads(path.read_text(encoding="utf-8"))


def write(run, relative, value, *, immutable=False):
    target = Path(run) / relative
    assert_safe_output_path(target, kind="backtest", paths=resolve(REPO))
    target.parent.mkdir(parents=True, exist_ok=True)
    value = _json_write_view(value)
    if immutable and target.exists():
        if read_json(target) != value:
            raise ValueError("FROZEN_ARTIFACT_CHANGED:" + relative)
        return sha(target)
    temporary = target.with_suffix(target.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    # Metadata sharing/access contention only; never a fitting retry.
    for attempt in range(6):
        try:
            temporary.replace(target)
            break
        except OSError as error:
            if getattr(error, "winerror", None) not in {5, 32, 33} or attempt == 5:
                raise  # Keep the fsynced temporary journal on terminal failure.
            time.sleep(0.05 * (2 ** attempt))
    return sha(target)


def _pin(path, expected, label):
    if not isinstance(expected, str) or len(expected) != 64 or sha(path) != expected:
        raise ValueError("FROZEN_PIN_CHANGED:" + label)


def execution_code_pins(run, freeze, *, freeze_name, support_key):
    """Apply fixed R1/R2/R3 amendments over the original dependency closure."""
    base = freeze.get("code_pins", ())
    bypath = {p["path"]: p for p in base}
    if len(bypath) != len(base):
        raise ValueError("DUPLICATE_EXECUTION_CODE_DEPENDENCY")
    pins = [dict(p) for p in base]
    base_sha = sha(run / freeze_name)
    lineage = []
    matched = False
    for revision in ("R1", "R2", "R3"):
        amendment_path = run / ("EXECUTION_IMPLEMENTATION_AMENDMENT_" + revision + ".json")
        if not amendment_path.exists():
            continue
        amendment = read_json(amendment_path)
        if amendment.get("semantic_change") is not False:
            raise ValueError("IMPLEMENTATION_ONLY_PRE_NUMERIC_AMENDMENT_REQUIRED")
        if revision == "R1":
            if amendment.get("no_numeric_read_before_patch") is not True:
                raise ValueError("IMPLEMENTATION_ONLY_PRE_NUMERIC_AMENDMENT_REQUIRED")
        elif (amendment.get("no_new_numeric_read_during_patch") is not True
              or amendment.get("prior_execution_preserved") is not True
              or amendment.get("fit_retry_allowed") is not False):
            raise ValueError("POST_EXECUTION_ENGINEERING_AMENDMENT_REQUIRED")
        item = dict(path=str(amendment_path), sha256=sha(amendment_path),
                    status="NOT_APPLICABLE_TO_THIS_BASE")
        lineage.append(item)
        if amendment["base_execution_freeze_sha256"] != base_sha:
            continue
        matched = True
        if revision == "R3":
            if support_key != "risk_component_support_sha256":
                raise ValueError("RR_CORRECTION_COMPONENT_BASE_REQUIRED")
            _pin(run / "RR_INPUT_BINDING_CORRECTION_FREEZE.json",
                 amendment.get("rr_correction_freeze_sha256"), "rr_correction_amendment")
        if amendment["support_sha256"] != freeze[support_key] or amendment["source_inputs_sha256"] != freeze["source_inputs_sha256"]:
            raise ValueError("AMENDMENT_SUPPORT_OR_SOURCE_BINDING_CHANGED")
        _pin(run / ("RISK_COMPONENT_SUPPORT.json" if support_key == "risk_component_support_sha256" else "RISK_SUPPORT.json"),
             amendment["support_sha256"], "amendment_support")
        _pin(run / "FAMILY_SOURCE_INPUTS.json", amendment["source_inputs_sha256"], "amendment_source")
        changes = amendment.get("code_pin_changes")
        if not isinstance(changes, list):
            raise ValueError("EXACT_CODE_PIN_CHANGES_REQUIRED")
        seen = set()
        for change in changes:
            path = change.get("path")
            if not isinstance(path, str) or path not in bypath or path in seen:
                raise ValueError("AMENDMENT_DEPENDENCIES_CANNOT_CHANGE")
            seen.add(path)
            current = next(p for p in pins if p["path"] == path)
            if change.get("prior_sha256") != current["sha256"]:
                raise ValueError("AMENDMENT_PRIOR_CODE_PIN_CHANGED")
            replacement = change.get("sha256")
            if (not isinstance(replacement, str) or len(replacement) != 64
                    or any(c not in "0123456789abcdef" for c in replacement)):
                raise ValueError("AMENDMENT_EXACT_REPLACEMENT_SHA_REQUIRED")
            current["sha256"] = replacement
        item["status"] = "APPLIED"
    if lineage and not matched and not all(sha(p["path"]) == p["sha256"] for p in pins):
        raise ValueError("FROZEN_PIN_CHANGED:amendment_base_execution")
    applied = [p for p in lineage if p["status"] == "APPLIED"]
    status = "APPLIED" if applied else ("NOT_APPLICABLE_TO_THIS_BASE" if lineage else "ABSENT")
    return pins, dict(base_execution_freeze_sha256=base_sha,
        execution_implementation_amendment_sha256=(applied or lineage)[-1]["sha256"] if lineage else None,
        execution_implementation_amendments=lineage, amendment_status=status)


def _component_node(key):
    return isinstance(key, str) and key.startswith(("component:", "corrected_rr:"))


def _stage_node(key, *, component, complete=False):
    if not isinstance(key, str):
        return False
    if complete:
        return key.startswith("complete:")
    return not key.startswith("complete:") and _component_node(key) == component


def validate_risk_recovery(run, status, *, component, complete=False):
    """Verify explicit terminal repair; never repair, retry or refund in this CLI."""
    rows = [r for r in status["records"] if r.get("risk_node")
            and _stage_node(r["risk_node"], component=component, complete=complete)]
    if any(r.get("status") in {"STARTED", "FIT_FAILURE"} for r in rows):
        raise ValueError("FAILED_OR_INTERRUPTED_NODE_REQUIRES_EXPLICIT_REPAIR")
    terminals = {"ABANDONED_CHECKPOINT_FAILURE", "BLOCKED_INTERRUPTED_SHARED_DAG"}
    affected = [r for r in rows if r.get("status") in terminals]
    if not affected:
        return
    audits = status.get("engineering_recovery_audits", ())
    by_sha = {}
    for pin in audits:
        path = Path(pin["path"]).resolve()
        if not path.is_relative_to(Path(run).resolve()):
            raise ValueError("RECOVERY_AUDIT_MUST_BELONG_TO_RUN")
        _pin(path, pin["sha256"], "engineering_recovery_audit")
        body = read_json(path)
        if (body.get("semantic_change") is not False or body.get("fit_retry_allowed") is not False
                or body.get("fit_unit_refund") is not False):
            raise ValueError("EXPLICIT_NO_RETRAIN_NO_REFUND_RECOVERY_REQUIRED")
        by_sha[pin["sha256"]] = pin
    if any(row.get("recovery_audit_sha256") not in by_sha for row in affected):
        raise ValueError("TERMINAL_NODE_RECOVERY_AUDIT_REQUIRED")


def guard_run(run, phase):
    component = phase.startswith("component-")
    phase = phase.removeprefix("component-")
    support_name = "RISK_COMPONENT_SUPPORT.json" if component else "RISK_SUPPORT.json"
    freeze_name = "RISK_COMPONENT_EXECUTION_FREEZE.json" if component else "FAMILY_EXECUTION_FREEZE.json"
    support_key = "risk_component_support_sha256" if component else "risk_support_sha256"
    run = Path(run).resolve()
    paths = resolve(REPO)
    assert_safe_output_path(run, kind="backtest", paths=paths)
    if run.parent != paths.backtest_root / "V24" or phase not in {"support", "fit"}:
        raise ValueError("EXISTING_MANAGED_V24_RUN_REQUIRED")
    source = read_json(run / "FAMILY_SOURCE_INPUTS.json")
    family_sha = sha(run / "FAMILY_DESIGN_FREEZE.json")
    _pin(run / "FAMILY_DESIGN_FREEZE.json", source["family_design_freeze_sha256"], "family")
    _pin(run / "SOURCE_AUTHORITY.json", source["source_authority_sha256"], "authority")
    _pin(run / "CONTROL_QUALIFICATION_ANALYSIS_R2.json", source["control_gate_sha256"], "control")
    gate = read_json(run / "CONTROL_QUALIFICATION_ANALYSIS_R2.json")
    if gate.get("conditional_mechanism_eligible") is not True:
        raise ValueError("TWO_CONTROLS_CONDITIONAL_MECHANISM_GATE_REQUIRED")
    if (source.get("scientific_mode") != "FROZEN_HISTORY_MECHANISM_ONLY"
            or source.get("strict_PIT_promotion_eligible") is not False
            or source.get("quote_qualified") is not False
            or source.get("training_exclusive_boundary") != "2026-01-01"):
        raise ValueError("FROZEN_HISTORY_SOURCE_SCOPE_REQUIRED")
    # The pinned family owns this stage's actual frozen-bytes observation time.
    family = read_json(run / "FAMILY_DESIGN_FREEZE.json")
    science = dict(actual_snapshot_timestamp=family["actual_snapshot_timestamp"])
    snapshot = pd.Timestamp(science["actual_snapshot_timestamp"])
    if snapshot.tzinfo is None:
        raise ValueError("FAMILY_SNAPSHOT_EXPLICIT_TIMEZONE_REQUIRED")
    if component:
        component_path = run / "RISK_COMPONENT_SCIENCE_FREEZE.json"
        contract = read_json(component_path)
        for field, name in (("source_inputs_sha256", "FAMILY_SOURCE_INPUTS.json"),
                            ("family_design_freeze_sha256", "FAMILY_DESIGN_FREEZE.json"),
                            ("control_qualification_sha256", "CONTROL_QUALIFICATION_ANALYSIS_R2.json")):
            _pin(run / name, contract[field], "component:" + field)
        if (contract["research_id"] != "V24_B_SOURCE_QUALIFIED_H5_FF48_RISK_COMPONENT_R1"
                or contract["strict_PIT_promotion_eligible"] is not False
                or contract["account_attempts"] != 0 or contract["forecast_fits"] != 0
                or contract["minimum_supported_h5"] != 30 or contract["fixed_parent_origins"] != 252
                or contract["minimum_component_assets"] != 2):
            raise ValueError("FROZEN_COMPONENT_SOURCE_ONLY_QUALIFICATION_REQUIRED")
        science.update(scientific_contract_identity=contract["research_id"],
                       scientific_contract_sha256=sha(component_path),
                       snapshot_roles=dict(
                           source_frozen_bytes_observed_at=science["actual_snapshot_timestamp"],
                           component_contract_frozen_at=contract.get("actual_snapshot_timestamp"),
                           source_timestamp_role="PINNED_FAMILY_FROZEN_SOURCE_BYTES_OBSERVED; not historical acquisition authority",
                           component_timestamp_role="SCIENTIFIC_CONTRACT_REGISTRATION_ONLY; not source acquisition",
                           historical_availability="UNKNOWN", observation_time_assumed=True))
    freeze = None
    if phase == "fit":
        freeze = read_json(run / freeze_name)
        for field, name in (("source_inputs_sha256", "FAMILY_SOURCE_INPUTS.json"),
                            ("family_design_freeze_sha256", "FAMILY_DESIGN_FREEZE.json"),
                            (support_key, support_name),
                            ("budget_scope_sha256", "BUDGET_SCOPE_FREEZE.json"),
                            ("control_qualification_sha256", "CONTROL_QUALIFICATION_ANALYSIS_R2.json")):
            _pin(run / name, freeze[field], field)
        if component:
            _pin(run / "RISK_COMPONENT_SCIENCE_FREEZE.json", freeze["risk_component_science_sha256"], "component_science")
            registration = freeze.get("registration_receipt")
            if registration is None:
                registration = {"path": str(run / "RISK_COMPONENT_REGISTRATION_RECEIPT.json"),
                                "sha256": freeze["registration_receipt_sha256"]}
            _pin(registration["path"], registration["sha256"], "component_registration")
        pins, lineage = execution_code_pins(run, freeze, freeze_name=freeze_name, support_key=support_key)
        science["implementation_lineage"] = lineage
        required = {Path(__file__).resolve(),
                    REPO / "scripts/research/a2/data/shared_risk_inputs_r3.py",
                    REPO / "scripts/research/a2/risk/shared_risk_engine_r2.py",
                    REPO / "scripts/research/a2/risk/shared_risk_budget_r2.py",
                    REPO / "scripts/research/a2/risk/shared_risk_extensions_r2.py",
                    REPO / "scripts/research/a2/risk/joint_risk_estimators.py"}
        supplied = {Path(p["path"]).resolve() for p in pins}
        if not required.issubset(supplied):
            raise ValueError("RISK_CODE_DEPENDENCY_CLOSURE_NOT_FROZEN")
        for p in pins:
            _pin(p["path"], p["sha256"], "code")
        if freeze["risk_stage_fit_cap"] != 1024 or freeze["inherited_prior_reserved"] != 968:
            raise ValueError("RISK_STAGE_BUDGET_CHANGED")
        support = read_json(run / support_name)
        if (support.get("source_inputs_sha256") != sha(run / "FAMILY_SOURCE_INPUTS.json")
                or support.get("family_design_freeze_sha256") != family_sha
                or support.get("numeric_reads") != 0 or support.get("fit_units") != 0):
            raise ValueError("QUALIFICATION_ONLY_SUPPORT_REQUIRED")
    return run, source, science, freeze


def guard_rr_correction(run, science, freeze):
    """Optional, fixed-file correction authority; no source or model body reads."""
    path = run / "RR_INPUT_BINDING_CORRECTION_FREEZE.json"
    if not path.exists():
        return None
    correction = read_json(path)
    if (correction.get("schema") != RR_CORRECTION_SCHEMA
            or correction.get("research_id") != RR_CORRECTION_ID
            or correction.get("status") != "FROZEN_BEFORE_CORRECTED_RR_NUMERIC_READ_OR_FIT"):
        raise ValueError("RR_CORRECTION_INDEPENDENT_FROZEN_IDENTITY_REQUIRED")
    bindings = (
        ("correction_spec_sha256", "RR_INPUT_BINDING_CORRECTION_SPEC.json"),
        ("parent_component_science_sha256", "RISK_COMPONENT_SCIENCE_FREEZE.json"),
        ("parent_component_execution_sha256", "RISK_COMPONENT_EXECUTION_FREEZE.json"),
        ("parent_component_support_sha256", "RISK_COMPONENT_SUPPORT.json"),
        ("source_inputs_sha256", "FAMILY_SOURCE_INPUTS.json"),
        ("family_design_freeze_sha256", "FAMILY_DESIGN_FREEZE.json"),
        ("source_authority_sha256", "SOURCE_AUTHORITY.json"),
        ("registration_receipt_sha256", "RR_INPUT_BINDING_CORRECTION_REGISTRATION_RECEIPT.json"),
        ("pause_receipt_sha256", "RR_INPUT_BINDING_PAUSE_RECEIPT.json"),
        ("checkpoint_ledger_sha256", "work/rr_binding_pause/FIT_STATUS.json"))
    for field, name in bindings:
        _pin(run / name, correction.get(field), "rr_correction:" + field)
    spec = read_json(run / "RR_INPUT_BINDING_CORRECTION_SPEC.json")
    registration = read_json(run / "RR_INPUT_BINDING_CORRECTION_REGISTRATION_RECEIPT.json")
    if (spec.get("research_id") != RR_CORRECTION_ID
            or registration.get("research_id") != RR_CORRECTION_ID
            or registration.get("correction_spec_sha256") != correction["correction_spec_sha256"]):
        raise ValueError("RR_CORRECTION_REGISTRY_SPEC_IDENTITY_MISMATCH")
    true_fields = ("primary_stock_frame_unchanged", "primary_source_receipt_unchanged",
                   "qqq_source_receipt_unchanged", "industry_receipt_unchanged",
                   "other_methods_input_binding_unchanged", "rr_input_binding_changed")
    false_fields = ("prior_completed_rr_reexecution", "strict_PIT_promotion_eligible",
                    "quote_qualified", "certified_nav", "account_equivalence")
    if (any(correction.get(f) is not True for f in true_fields)
            or any(correction.get(f) is not False for f in false_fields)
            or any(correction.get(f) != 0 for f in
                   ("account_attempts", "forecast_fits", "test2026_rows_read"))
            or correction.get("checkpoint_new_fit_units") != 281
            or correction.get("start_as_of") != RR_CORRECTION_ASOFS[0]
            or tuple(correction.get("allowed_as_of", ())) != RR_CORRECTION_ASOFS
            or correction.get("qqq_open_lookback_sessions") != 360
            or correction.get("max_additional_units_per_quarter") != 7
            or correction.get("max_quarters") != 6):
        raise ValueError("RR_CORRECTION_FROZEN_RECIPE_OR_SCOPE_CHANGED")
    pins, _ = execution_code_pins(run, freeze,
        freeze_name="RISK_COMPONENT_EXECUTION_FREEZE.json",
        support_key="risk_component_support_sha256")
    supplied = correction.get("code_pins", ())
    actual = {p["path"]: p["sha256"] for p in pins}
    frozen = {p["path"]: p["sha256"] for p in supplied}
    if len(frozen) != len(supplied) or frozen != actual:
        raise ValueError("RR_CORRECTION_EXACT_EFFECTIVE_CODE_CLOSURE_REQUIRED")
    for pin in supplied:
        _pin(pin["path"], pin["sha256"], "rr_correction_code")
    support = read_json(run / "RISK_COMPONENT_SUPPORT.json")["nodes"]
    support_rr = {n["as_of"]: n for n in support if n["method"] == "RR"}
    if not all(a in support_rr for a in RR_CORRECTION_ASOFS):
        raise ValueError("RR_CORRECTION_SIX_ORIGINAL_QUARTERS_REQUIRED")
    return dict(correction, freeze_sha256=sha(path))


def rr_correction_envelope(correction, node):
    """Separate research identity while retaining the primary source/cache context."""
    return dict(research_id=RR_CORRECTION_ID,
        correction_freeze_sha256=correction["freeze_sha256"],
        correction_spec_sha256=correction["correction_spec_sha256"],
        parent_component_science_sha256=correction["parent_component_science_sha256"],
        parent_component_execution_sha256=correction["parent_component_execution_sha256"],
        parent_component_support_sha256=correction["parent_component_support_sha256"],
        source_inputs_sha256=correction["source_inputs_sha256"],
        method="RR", as_of=node["as_of"], cutoff=node["cutoff"],
        assets=node["assets"], asset_uids=node["asset_uids"], asset_epochs=node["asset_epochs"],
        qqq_open_lookback_sessions=360, rr_input_binding_changed=True,
        original_rr_execution=False, account_equivalence=False,
        strict_PIT_promotion_eligible=False)


def activate_rr_correction(run, ledger, correction, qualified):
    """Bind the zero-fit checkpoint once; resumes bind the immutable activation."""
    if correction is None:
        return None
    expected = dict(schema="B_R3_RR_CORRECTION_ACTIVATION_V1",
        research_id=RR_CORRECTION_ID, correction_freeze_sha256=correction["freeze_sha256"],
        correction_spec_sha256=correction["correction_spec_sha256"],
        registration_receipt_sha256=correction["registration_receipt_sha256"],
        pause_receipt_sha256=correction["pause_receipt_sha256"],
        initial_checkpoint_ledger_sha256=correction["checkpoint_ledger_sha256"],
        checkpoint_new_fit_units=281, start_as_of=correction["start_as_of"],
        allowed_as_of=list(RR_CORRECTION_ASOFS), fit_units_at_activation=0,
        account_attempts=0, forecast_fits=0, test2026_rows_read=0,
        strict_PIT_promotion_eligible=False)
    relative = "RR_INPUT_BINDING_CORRECTION_ACTIVATION_RECEIPT.json"
    path = run / relative
    pin = ledger.status.get("rr_correction_activation")
    if pin is None:
        _pin(run / "work/FIT_STATUS.json", correction["checkpoint_ledger_sha256"],
             "rr_correction_initial_live_checkpoint")
        if (ledger.status["new_fit_units"] != 281
                or any(e.get("status") == "STARTED" for e in ledger.status["physical_events"])
                or any(r.get("status") == "STARTED" for r in ledger.status["records"])):
            raise ValueError("RR_CORRECTION_ZERO_INFLIGHT_CHECKPOINT_REQUIRED")
        retained = {r.get("risk_node") for r in ledger.status["records"]}
        unexecuted = [n["as_of"] for n in qualified if n["method"] == "RR"
                      and "component:RR@" + n["as_of"] not in retained]
        if not unexecuted or min(unexecuted) != correction["start_as_of"]:
            raise ValueError("RR_CORRECTION_FIRST_UNEXECUTED_QUARTER_CHANGED")
        digest = write(run, relative, expected, immutable=True)
        pin = dict(path=relative, sha256=digest, correction_freeze_sha256=correction["freeze_sha256"])
        ledger.status["rr_correction_activation"] = pin
        ledger.checkpoint()
    else:
        if pin.get("path") != relative or pin.get("correction_freeze_sha256") != correction["freeze_sha256"]:
            raise ValueError("RR_CORRECTION_RESUME_ACTIVATION_CHANGED")
        _pin(path, pin.get("sha256"), "rr_correction_activation")
        if read_json(path) != expected:
            raise ValueError("RR_CORRECTION_RESUME_ACTIVATION_CHANGED")
    by_asof = {n["as_of"]: n for n in qualified if n["method"] == "RR"}
    originals = {r.get("risk_node"): r for r in ledger.status["records"]}
    for asof in RR_CORRECTION_ASOFS:
        original = originals.get("component:RR@" + asof)
        if original and (original.get("status") != "CORRECTION_NOT_EXECUTED"
                         or original.get("learned_states") != 0):
            raise ValueError("RR_CORRECTION_PRIOR_ORIGINAL_RECORD_CANNOT_BE_RECOMPUTED")
    for row in ledger.status["records"]:
        key = row.get("risk_node", "")
        if not key.startswith("corrected_rr:"):
            continue
        asof = row.get("as_of")
        if (key != "corrected_rr:RR@" + str(asof) or asof not in RR_CORRECTION_ASOFS
                or row.get("correction_envelope") != rr_correction_envelope(correction, by_asof[asof])
                or not 0 <= row.get("learned_states", -1) <= 7):
            raise ValueError("RR_CORRECTION_RETAINED_NODE_ENVELOPE_CHANGED")
    return pin


def _pending_risk_node(node, records, prefix, correction):
    key = prefix + node["method"] + "@" + node["as_of"]
    retained = next((r for r in records if r.get("risk_node") == key), None)
    if (correction is not None and node["method"] == "RR"
            and node["as_of"] in RR_CORRECTION_ASOFS):
        return not any(r.get("risk_node") == "corrected_rr:RR@" + node["as_of"] for r in records)
    return retained is None


def _corrected_rr_input(assembly, days, node):
    prior = pd.Timestamp(node["cutoff"]).tz_convert("America/New_York").tz_localize(None).normalize()
    position = days.get_loc(prior)
    if position < 360:
        raise ValueError("RR_QQQ_SOURCE_RANGE_REQUIRES_360_PRIOR_SESSIONS")
    result = correct_rr_qqq_source_range(assembly.risk_input,
        cutoff=pd.Timestamp(node["cutoff"]), open_start_date=days[position-360],
        open_stop_date_exclusive=prior)
    original = assembly.risk_input
    if (result.sessions is not original.sessions
            or result.observations is not original.observations
            or result.source_receipt is not original.source_receipt
            or result.qqq_receipt is not original.qqq_receipt
            or result.industry_mapping is not original.industry_mapping
            or result.industry_receipt is not original.industry_receipt
            or result.assets != original.assets or result.asset_uids != original.asset_uids
            or result.identity_epoch != original.identity_epoch):
        raise ValueError("RR_CORRECTION_PRIMARY_INPUT_OR_RECEIPT_CHANGED")
    return result


def complete_schedule(calendar):
    """Prescribed quarterly projection; the core's annual/monthly rules are intact."""
    return [n for n in schedule(calendar) if n["method"] not in {"RD", "RB", "RT"}
            or pd.Timestamp(n["as_of"]).tz_convert("America/New_York").month in (1, 4, 7, 10)]


def guard_complete_run(run, phase):
    # Existing source/authority/control and parent-science guards remain the owner.
    run, source, parent_science, _ = guard_run(run, "component-support")
    science_path = run / "RISK_COMPLETE_COMMON_SCIENCE_FREEZE.json"
    contract = read_json(science_path)
    if (contract.get("schema") != COMPLETE_SCIENCE_SCHEMA
            or contract.get("research_id") != COMPLETE_ID
            or contract.get("status") != "FROZEN_BEFORE_COMPLETE_COMMON_NUMERIC_READ_OR_FIT"):
        raise ValueError("COMPLETE_COMMON_INDEPENDENT_SCIENCE_REQUIRED")
    bindings = (("source_inputs_sha256", "FAMILY_SOURCE_INPUTS.json"),
        ("source_authority_sha256", "SOURCE_AUTHORITY.json"),
        ("family_design_freeze_sha256", "FAMILY_DESIGN_FREEZE.json"),
        ("control_qualification_sha256", "CONTROL_QUALIFICATION_ANALYSIS_R2.json"),
        ("budget_scope_sha256", "BUDGET_SCOPE_FREEZE.json"),
        ("parent_component_science_sha256", "RISK_COMPONENT_SCIENCE_FREEZE.json"),
        ("parent_component_support_sha256", "RISK_COMPONENT_SUPPORT.json"))
    for field, name in bindings:
        _pin(run / name, contract.get(field), "complete_science:" + field)
    true_fields = ("parent_window_first", "metadata_only_selection",
                   "all_selected_cells_finite_required", "whole_node_block_on_numeric_gap")
    false_fields = ("numeric_domain_filtering_allowed", "prior_failed_node_retry",
        "strict_PIT_promotion_eligible", "quote_qualified", "certified_nav_qualified", "account_equivalence")
    if (any(contract.get(k) is not True for k in true_fields)
            or any(contract.get(k) is not False for k in false_fields)
            or any(contract.get(k) != 0 for k in ("account_attempts", "forecast_fits", "test2026_rows_read"))
            or contract.get("minimum_supported_h5") != 252 or contract.get("fixed_parent_origins") != 252
            or contract.get("minimum_component_assets") != 2 or contract.get("expected_nodes") != 99
            or contract.get("directions") != list(METHODS)
            or contract.get("schedule_policy") != "QUARTER_7_WITH_EXISTING_R0_ANNUAL_RM_BLOCKED"
            or contract.get("rr_qqq_open_lookback_sessions") != 360):
        raise ValueError("COMPLETE_COMMON_FROZEN_RULE_OR_SCOPE_CHANGED")
    science = dict(parent_science, scientific_contract_identity=COMPLETE_ID,
        scientific_contract_sha256=sha(science_path),
        parent_component_support_sha256=contract["parent_component_support_sha256"],
        parent_component_support_nodes=read_json(run / "RISK_COMPONENT_SUPPORT.json")["nodes"])
    freeze = None
    if phase == "fit":
        freeze_name = "RISK_COMPLETE_COMMON_EXECUTION_FREEZE.json"
        freeze = read_json(run / freeze_name)
        if (freeze.get("schema") != "B_R3_COMPLETE_COMMON_EXECUTION_V1"
                or freeze.get("research_id") != COMPLETE_ID
                or freeze.get("status") != "FROZEN_BEFORE_COMPLETE_COMMON_NUMERIC_READ_OR_FIT"):
            raise ValueError("COMPLETE_COMMON_EXECUTION_IDENTITY_REQUIRED")
        for field, name in (*bindings[:5],
            ("risk_complete_common_science_sha256", "RISK_COMPLETE_COMMON_SCIENCE_FREEZE.json"),
            ("risk_complete_common_support_sha256", "RISK_COMPLETE_COMMON_SUPPORT.json"),
            ("registration_receipt_sha256", "RISK_COMPLETE_COMMON_REGISTRATION_RECEIPT.json"),
            ("parent_component_final_audit_sha256", "derived/RISK_COMPONENT_STAGE_AUDIT.json"),
            ("checkpoint_ledger_sha256", "work/complete_common_parent_completion/FIT_STATUS.json")):
            _pin(run / name, freeze.get(field), "complete_execution:" + field)
        receipt = read_json(run / "RISK_COMPLETE_COMMON_REGISTRATION_RECEIPT.json")
        if (receipt.get("research_id") != COMPLETE_ID
                or receipt.get("entity_id") != "V24_B_SOURCE_QUALIFIED_H5_FF48_RISK_COMPONENT_R1"
                or receipt.get("registration_kind") != "REGISTERED_DIAGNOSTIC_UNDER_EXISTING_PARENT"
                or receipt.get("risk_complete_common_science_sha256") != sha(science_path)):
            raise ValueError("COMPLETE_COMMON_ACTUAL_PARENT_REGISTRATION_REQUIRED")
        if ((freeze.get("risk_stage_fit_cap"), freeze.get("inherited_prior_reserved"),
             freeze.get("max_additional_learned_units"), freeze.get("max_group_learned_units"),
             freeze.get("max_numeric_groups")) != (1024, 968, 341, 31, 11)
                or freeze.get("no_refund") is not True or freeze.get("fit_retry_allowed") is not False):
            raise ValueError("COMPLETE_COMMON_EXISTING_BUDGET_CAP_REQUIRED")
        pins, lineage = execution_code_pins(run, freeze, freeze_name=freeze_name,
                                           support_key="risk_complete_common_support_sha256")
        required = {Path(__file__).resolve(), REPO / "scripts/research/a2/data/shared_risk_inputs_r3.py",
            REPO / "scripts/research/a2/risk/shared_risk_engine_r2.py",
            REPO / "scripts/research/a2/risk/shared_risk_budget_r2.py",
            REPO / "scripts/research/a2/risk/shared_risk_extensions_r2.py",
            REPO / "scripts/research/a2/risk/joint_risk_estimators.py",
            REPO / "scripts/research/a2/evaluation/joint_method_stages.py",
            REPO / "scripts/common/storage_paths.py"}
        if not required.issubset({Path(pin["path"]).resolve() for pin in pins}):
            raise ValueError("COMPLETE_COMMON_CODE_CLOSURE_REQUIRED")
        for pin in pins:
            _pin(pin["path"], pin["sha256"], "complete_code")
        science["implementation_lineage"] = lineage
        support_body = read_json(run / "RISK_COMPLETE_COMMON_SUPPORT.json")
        if (support_body.get("numeric_reads") != 0 or support_body.get("fit_units") != 0
                or support_body.get("source_inputs_sha256") != sha(run / "FAMILY_SOURCE_INPUTS.json")
                or support_body.get("risk_complete_common_science_sha256") != sha(science_path)
                or len(support_body.get("nodes", ())) != 99):
            raise ValueError("COMPLETE_COMMON_METADATA_ONLY_99_SUPPORT_REQUIRED")
    elif phase != "support":
        raise ValueError("COMPLETE_COMMON_SUPPORT_OR_FIT_ONLY")
    return run, source, science, freeze


def _complete_domain_proof(science, pool, partial_assets, counts, window, cutoff):
    """Hash physical metadata domains without using the new science id as a key."""
    def body(names):
        return dict(assets=list(names), parent_origin_window=window,
            **{k: {a: pool[k][a] for a in names}
               for k in ("asset_uids", "asset_epochs", "segment_starts")},
            supported_h5_by_asset={a: counts[a] for a in names})
    partial, complete = body(partial_assets), body(pool["assets"])
    candidates = [n for n in science.get("parent_component_support_nodes", ())
                  if pd.Timestamp(n["cutoff"]) == pd.Timestamp(cutoff)]
    if not candidates:
        raise ValueError("COMPLETE_COMMON_PRIOR_PARTIAL_SUPPORT_REQUIRED")
    for old in candidates:
        expected = dict(assets=old["assets"], parent_origin_window=old["parent_origin_window"],
            **{k: old[k] for k in ("asset_uids", "asset_epochs", "segment_starts")},
            supported_h5_by_asset={a: old["declarations"]["component_supported_h5_by_asset"][a]
                                   for a in old["assets"]})
        if _json(partial) != expected:
            raise ValueError("COMPLETE_COMMON_PRIOR_PARTIAL_DOMAIN_CHANGED")
    return dict(parent_origin_window_sha256=content_hash(window),
        parent_requested_sha256=content_hash(pool["parent_requested"]),
        prior_partial_domain=partial, complete_domain=complete,
        prior_partial_domain_sha256=content_hash(partial), complete_domain_sha256=content_hash(complete),
        counts_sha256=content_hash(partial["supported_h5_by_asset"]), parent_component_support_sha256=science["parent_component_support_sha256"],
        relation="STRICT_SUBSET" if set(pool["assets"]) < set(partial_assets) else "REUSE_REQUIRED",
        whole_scientific_equivalence="NOT_CLAIMED_FROM_RESEARCH_ID_OR_DOMAIN_ALONE")


def activate_complete(run, ledger, freeze):
    expected = dict(schema="B_R3_COMPLETE_COMMON_ACTIVATION_V1", research_id=COMPLETE_ID,
        execution_freeze_sha256=sha(run / "RISK_COMPLETE_COMMON_EXECUTION_FREEZE.json"),
        science_sha256=freeze["risk_complete_common_science_sha256"],
        support_sha256=freeze["risk_complete_common_support_sha256"],
        initial_checkpoint_ledger_sha256=freeze["checkpoint_ledger_sha256"],
        checkpoint_new_fit_units=freeze["checkpoint_new_fit_units"],
        checkpoint_risk_fit_units=freeze["checkpoint_risk_fit_units"],
        max_additional_learned_units=341, original_risk_cap=1024,
        account_attempts=0, forecast_fits=0, test2026_rows_read=0,
        strict_PIT_promotion_eligible=False)
    relative = "RISK_COMPLETE_COMMON_ACTIVATION_RECEIPT.json"
    pin = ledger.status.get("complete_common_activation")
    if pin is None:
        _pin(run / "work/FIT_STATUS.json", freeze["checkpoint_ledger_sha256"], "complete_initial_live_checkpoint")
        if (ledger.status["status"] != "FROZEN_HISTORY_RISK_COMPONENT_STAGE_COMPLETE"
                or ledger.status["new_fit_units"] != freeze["checkpoint_new_fit_units"]
                or ledger.status["risk_fit_units"] != freeze["checkpoint_risk_fit_units"]
                or any(r.get("status") == "STARTED" for r in ledger.status["records"])
                or any(e.get("status") == "STARTED" for e in ledger.status["physical_events"])):
            raise ValueError("COMPLETE_COMMON_ENDED_ORIGINAL_ZERO_INFLIGHT_REQUIRED")
        if (ledger.status["risk_fit_units"] + 341 > 1024
                or ledger.status["new_fit_units"] + 341 > ledger.new_cap
                or ledger.status["fit_attempts"] + 341 > 4096):
            raise ValueError("COMPLETE_COMMON_UPPER341_MUST_FIT_EXISTING_CAP_BEFORE_NUMERIC")
        digest = write(run, relative, expected, immutable=True)
        pin = dict(path=relative, sha256=digest, execution_freeze_sha256=expected["execution_freeze_sha256"])
        ledger.status["complete_common_activation"] = pin
        ledger.checkpoint()
    else:
        if pin.get("path") != relative or pin.get("execution_freeze_sha256") != expected["execution_freeze_sha256"]:
            raise ValueError("COMPLETE_COMMON_RESUME_ACTIVATION_CHANGED")
        _pin(run / relative, pin.get("sha256"), "complete_activation")
        if read_json(run / relative) != expected:
            raise ValueError("COMPLETE_COMMON_RESUME_ACTIVATION_CHANGED")
    return pin


def _safe_source(path):
    path = Path(path)
    paths = resolve(REPO)
    if path.drive.upper() in {"E:", "F:"}:
        raise ValueError("FORBIDDEN_SOURCE_ROOT")
    for parent in (path, *path.parents):
        if parent.exists():
            flags = getattr(parent.stat(follow_symlinks=False), "st_file_attributes", 0)
            if parent.is_symlink() or flags & 0x400:
                raise ValueError("SOURCE_REPARSE_POINT_FORBIDDEN")
    physical = path.resolve()
    if not any(physical.is_relative_to(root) for root in
               (paths.results_root, paths.data_root, paths.backtest_root)):
        raise ValueError("SOURCE_OUTSIDE_EXISTING_D_ROOTS")
    return physical


class ProjectedReader:
    """Only manifest-exact files and pre-body predicate/column projections."""
    def __init__(self, source, *, phase):
        self.phase, self.sources, self.audit = phase, source["sources"], []
        self.datasets = {}
        for name in SOURCE_NAMES + ("qqq_qfq_years",):
            pins = self.sources[name]
            pins = pins if isinstance(pins, list) else [pins]
            for p in pins:
                path = _safe_source(p["path"])
                _pin(path, p["sha256"], name)
                if name == "qqq_qfq_years" and not 2020 <= p["year"] <= 2025:
                    raise ValueError("QQQ_PARTITION_PRE2026_REQUIRED")
                footer = pq.ParquetFile(path)
                guard = p.get("physical_pre2026_guard", {})
                if not guard:
                    raise ValueError("PHYSICAL_DATE_FOOTER_REQUIRED:" + name)
                for column, declared in guard.items():
                    ci = footer.schema.names.index(column)
                    if len(declared) != footer.metadata.num_row_groups:
                        raise ValueError("SOURCE_FOOTER_GROUPS_CHANGED:" + name)
                    for i, bound in enumerate(declared):
                        stats = footer.metadata.row_group(i).column(ci).statistics
                        if not stats or not stats.has_min_max or pd.Timestamp(stats.max) >= BOUNDARY:
                            raise ValueError("MIXED_OR_UNKNOWN_DATE_BODY_FORBIDDEN:" + name)
                        if pd.Timestamp(stats.min) != pd.Timestamp(bound["min"]) or pd.Timestamp(stats.max) != pd.Timestamp(bound["max"]):
                            raise ValueError("SOURCE_FOOTER_BOUNDS_CHANGED:" + name)
                self.datasets[str(path)] = ds.dataset(path, format="parquet")

    @staticmethod
    def _scalar(dataset, field, value):
        typ = dataset.schema.field(field).type
        t = pd.Timestamp(value)
        if pa.types.is_string(typ) or pa.types.is_large_string(typ):
            return t.date().isoformat()
        return pa.scalar(t.to_pydatetime(), type=typ)

    def read(self, name, columns, *, date_field, start=None, stop=None, day=None,
             tickers=None, mature_before=None, ticker_field="ticker", availability_cutoff=None, origin_dates=None):
        columns = tuple(columns)
        if self.phase == "support" and FORBIDDEN.intersection(columns):
            raise ValueError("SUPPORT_NUMERIC_OR_SCORE_PROJECTION_FORBIDDEN")
        # stop is an exclusive date upper bound; equality reads no 2026 row.
        if stop is not None and (pd.isna(pd.Timestamp(stop)) or pd.Timestamp(stop) > BOUNDARY):
            raise ValueError("PRE2026_READER_CUTOFF_REQUIRED")
        # Point/date and availability roles do not inherit exclusive-stop permission.
        for cutoff in (start, day, mature_before,
                       availability_cutoff[1] if availability_cutoff is not None else None):
            if cutoff is not None:
                timestamp = pd.Timestamp(cutoff)
                if pd.isna(timestamp) or timestamp.date() >= BOUNDARY.date():
                    raise ValueError("PRE2026_READER_CUTOFF_REQUIRED")
        pins = self.sources[name]
        pins = pins if isinstance(pins, list) else [pins]
        frames = []
        for p in pins:
            if name == "qqq_qfq_years" and (p["year"] > pd.Timestamp(stop).year
                    or p["year"] < pd.Timestamp(start).year):
                continue
            dataset = self.datasets[str(Path(p["path"]).resolve())]
            expr = ds.field(date_field) < self._scalar(dataset, date_field, BOUNDARY)
            if start is not None:
                expr = expr & (ds.field(date_field) >= self._scalar(dataset, date_field, start))
            if stop is not None:
                expr = expr & (ds.field(date_field) < self._scalar(dataset, date_field, stop))
            if day is not None:
                expr = expr & (ds.field(date_field) == self._scalar(dataset, date_field, day))
            if origin_dates is not None:
                expr = expr & ds.field(date_field).isin([self._scalar(dataset, date_field, d) for d in origin_dates])
            if tickers is not None:
                expr = expr & ds.field(ticker_field).isin(list(tickers))
            if availability_cutoff is not None:
                field, clock = availability_cutoff
                expr = expr & (ds.field(field) <= self._scalar(dataset, field, clock))
            if mature_before is not None:
                for field in ("execution_date", "label_end_date", "label_mature_date"):
                    expr = expr & (ds.field(field) < self._scalar(dataset, field, mature_before))
            frames.append(dataset.to_table(columns=list(columns), filter=expr).to_pandas())
            self.audit.append(dict(source=name, columns=list(columns), start=str(start),
                stop=str(stop), day=str(day), exact_tickers=list(tickers or ()),
                maturity_predicate=str(mature_before), rows=len(frames[-1])))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=columns)


def schedule(calendar):
    days, _ = _calendar(calendar)
    selected = days[(days.year >= 2023) & (days.year <= 2025)]
    result = []
    for method in METHODS:
        seen = set()
        for d in selected:
            key = d.year if SCHEDULE[method] == "annual" else (
                d.year, d.month if SCHEDULE[method] == "monthly" else (d.month - 1) // 3)
            if key not in seen:
                i = days.get_loc(d)
                if i == 0:
                    raise ValueError("PRIOR_CLOSE_SESSION_REQUIRED")
                result.append(dict(method=method, as_of=_clock(d).isoformat(),
                    cutoff=_clock(days[i-1]).isoformat(), prior_date=days[i-1].date().isoformat()))
                seen.add(key)
    return sorted(result, key=lambda r: (r["as_of"], METHODS.index(r["method"])))


def current_pool(features, raw_keys, days, cutoff):
    """Pool never observes labels, scores or future target completeness."""
    prior = pd.Timestamp(cutoff).tz_convert("America/New_York").tz_localize(None).normalize()
    current = features.loc[pd.to_datetime(features.signal_date).eq(prior)]
    accepted = (current.feature_available.eq(True) & current.all_features_finite.eq(True)
                & current.feature_source.isin(FEATURE_TAGS))
    raw = set(raw_keys.loc[pd.to_datetime(raw_keys.trade_date).eq(prior), "ticker"])
    assets = tuple(sorted(set(current.loc[accepted, "ticker"]).intersection(raw)))
    uids, epochs, starts, blocked = {}, {}, {}, {}
    positions = {d: i for i, d in enumerate(days)}
    history = features.loc[features.ticker.isin(assets), ["ticker", "signal_date", "security_id"]].copy()
    history["signal_date"] = pd.to_datetime(history.signal_date)
    grouped_history = {a: rows for a, rows in history.groupby("ticker", sort=False)}
    for asset in assets:
        rows = grouped_history[asset]
        at = rows.loc[rows.signal_date.eq(prior), "security_id"]
        if len(at) != 1 or not isinstance(at.iloc[0], str) or not at.iloc[0]:
            blocked[asset] = "AMBIGUOUS_OR_MISSING_CURRENT_UID"
            uids[asset], epochs[asset], starts[asset] = None, None, None
            continue
        uid = at.iloc[0]
        bydate = rows.set_index("signal_date").security_id
        i = positions[prior]
        start = i
        while start >= 0:
            value = bydate.get(days[start])
            if not isinstance(value, str) or value != uid:
                break
            start -= 1
        start += 1
        uids[asset] = uid
        starts[asset] = days[start].date().isoformat()
        epochs[asset] = "OBSERVED_CONTIGUOUS_UID:" + content_hash(dict(asset=asset, uid=uid, start=starts[asset]))
    repeated = pd.Series([u for u in uids.values() if u is not None]).duplicated(keep=False)
    repeated_uids = set(pd.Series([u for u in uids.values() if u is not None])[repeated])
    for asset in assets:
        if uids[asset] in repeated_uids:
            blocked[asset] = "NONUNIQUE_CURRENT_UID"
    clocks = {d: _clock(d) for d in history.signal_date.drop_duplicates()}
    history["available_at"] = history.signal_date.map(clocks)
    history["identity_epoch"] = [epochs[a] if starts[a] is not None and d >= pd.Timestamp(starts[a])
                                 and u == uids[a] else "PRIOR_OBSERVED_UID_EPOCH"
                                 for a, d, u in history[["ticker", "signal_date", "security_id"]].itertuples(index=False, name=None)]
    return dict(assets=assets, asset_uids=uids, asset_epochs=epochs,
                segment_starts=starts, blocked_assets=blocked, history=history)


def _receipt(source, science, cutoff, epoch, *, benchmark=False):
    name = "qqq_qfq_years" if benchmark else "extended_shareholder_y5"
    pins = source["sources"][name]
    digest = content_hash([{k: p[k] for k in ("year", "sha256")} for p in pins]) if benchmark else pins["sha256"]
    return SourceReceipt(name, "FROZEN_EXISTING_BYTES_R3", digest, cutoff,
        synthetic=False, mechanism=True, status="FROZEN_HISTORY_MECHANISM_SOURCE_BOUND",
        return_coordinate=BENCHMARK_PROXY_COORDINATE if benchmark else COORDINATE,
        identity_epoch=epoch, scientific_contract_identity=science.get("scientific_contract_identity", source["research_id"]),
        scientific_contract_sha256=science.get("scientific_contract_sha256", source["family_design_freeze_sha256"]),
        actual_snapshot_timestamp=science["actual_snapshot_timestamp"],
        observation_time_assumed=True, benchmark_proxy_allowed=benchmark)


def asof_ff48(reader, source, science, pool, cutoff, epoch):
    """Exact current ticker+UID and available/effective asof mapping, no aliases."""
    prior = pd.Timestamp(cutoff).tz_convert("America/New_York").tz_localize(None).normalize()
    columns = ("decision_date", "canonical_security_id", "ticker_at_date", "sic_available_at",
               "ff48_code", "identity_status", "taxonomy_status", "sic_source_sha256", "source_fingerprints")
    rows = reader.read("ff48_surface", columns, date_field="decision_date",
        stop=prior + pd.Timedelta(days=1), tickers=pool["assets"], ticker_field="ticker_at_date",
        availability_cutoff=("sic_available_at", cutoff))
    qualified = []
    grouped_rows = {(a, u): frame for (a, u), frame in
                    rows.groupby(["ticker_at_date", "canonical_security_id"], sort=False)}
    for asset in pool["assets"]:
        exact = grouped_rows.get((asset, pool["asset_uids"][asset]), rows.iloc[:0]).copy()
        if exact.empty:
            continue
        latest = pd.to_datetime(exact.decision_date).max()
        exact = exact.loc[pd.to_datetime(exact.decision_date).eq(latest)]
        if len(exact) != 1:
            continue
        row = exact.iloc[0]
        g = row.ff48_code
        if (row.identity_status != "AUTHORITATIVE" or row.taxonomy_status != "STRICT_PIT_SIC_FF12_FF48_MAPPED"
                or pd.isna(g) or float(g) != int(g) or not 1 <= int(g) <= 48
                or not isinstance(row.sic_source_sha256, str) or len(row.sic_source_sha256) != 64
                or not isinstance(row.source_fingerprints, str) or not row.source_fingerprints):
            continue
        qualified.append(dict(asset=asset, uid=pool["asset_uids"][asset], group=int(g),
            available_at=pd.Timestamp(row.sic_available_at).tz_convert("UTC"),
            effective_at=_clock(row.decision_date)))
    frame = pd.DataFrame(qualified, columns=("asset", "uid", "group", "available_at", "effective_at"))
    primary = _receipt(source, science, cutoff, epoch)
    pin = source["sources"]["ff48_surface"]
    receipt = SourceReceipt("ff48_surface", "FROZEN_EXISTING_BYTES_R3", pin["sha256"], cutoff,
        synthetic=False, mechanism=True, status=primary.status, identity_epoch=epoch,
        scientific_contract_identity=primary.scientific_contract_identity,
        scientific_contract_sha256=primary.scientific_contract_sha256,
        actual_snapshot_timestamp=primary.actual_snapshot_timestamp, observation_time_assumed=True)
    reason = None if set(frame.asset) == set(pool["assets"]) else "BLOCK_MISSING_OR_UID_UNBOUND_FF48"
    return frame, receipt, reason


def load_period(reader, source, science, days, cutoff, *, numeric, allow_partial_uid=False):
    prior = pd.Timestamp(cutoff).tz_convert("America/New_York").tz_localize(None).normalize()
    next_day = prior + pd.Timedelta(days=1)
    features = reader.read("prediction_features", FEATURE_META, date_field="signal_date", stop=next_day)
    current = features.loc[pd.to_datetime(features.signal_date).eq(prior)]
    accepted = current.loc[current.feature_available.eq(True) & current.all_features_finite.eq(True)
                           & current.feature_source.isin(FEATURE_TAGS), "ticker"].drop_duplicates()
    raw = reader.read("raw_open_close", ("ticker", "trade_date"), date_field="trade_date",
                      day=prior, tickers=accepted.tolist())
    pool = current_pool(features, raw, days, cutoff)
    if allow_partial_uid:
        parent = {k: pool[k] for k in ("assets", "asset_uids", "asset_epochs", "segment_starts", "blocked_assets")}
        names = tuple(a for a in pool["assets"] if a not in pool["blocked_assets"])
        pool = {**pool, "assets": names, "blocked_assets": {}, "parent_requested": parent,
                **{k: {a: pool[k][a] for a in names} for k in ("asset_uids", "asset_epochs", "segment_starts")},
                "history": pool["history"].loc[pool["history"].ticker.isin(names)].copy()}
    assets = pool["assets"]
    if not assets or pool["blocked_assets"]:
        return pool, None, dict(reason="EMPTY_POOL" if not assets else "REQUESTED_UID_UNBOUND")
    eligible_days = days[days < prior]
    start = eligible_days[max(0, len(eligible_days)-306)]
    metadata = reader.read("extended_shareholder_y5", LABEL_META + (("y_open5",) if numeric else ()),
        date_field="signal_date", start=start, stop=prior, tickers=assets, mature_before=prior)
    base = reader.read("shareholder_y5", ("ticker", "signal_date", "security_id"),
        date_field="signal_date", start=start, stop=prior, tickers=assets)
    if base.duplicated(["ticker", "signal_date"]).any():
        return pool, None, dict(reason="AMBIGUOUS_BASE_LABEL_UID_METADATA")
    labels = metadata.merge(base, on=["ticker", "signal_date"], how="left", validate="one_to_one")
    labels = labels.merge(pool["history"][["ticker", "signal_date", "identity_epoch"]],
                          on=["ticker", "signal_date"], how="left", validate="many_to_one")
    if not numeric:
        labels["y_open5"] = np.nan  # Explicit unavailable placeholder; never a source value.
    if allow_partial_uid:
        pool["component_labels"] = labels
    epoch = "CURRENT_POOL_OBSERVED_UIDS:" + content_hash(pool["asset_epochs"])
    receipt = _receipt(source, science, cutoff, epoch)
    qstart = days[max(0, days.get_loc(prior)-360)]
    qcolumns = ("ticker", "trade_date", "open") if numeric else ("ticker", "trade_date")
    qq = reader.read("qqq_qfq_years", qcolumns, date_field="trade_date",
                     start=qstart, stop=prior, tickers=("QQQ",))
    qreceipt = _receipt(source, science, cutoff, "EXISTING_QQQ_QFQ_OPEN_PROXY", benchmark=True)
    ff, ireceipt, ff_reason = asof_ff48(reader, source, science, pool, cutoff, epoch)
    assembly = assemble_risk_inputs(labels, days, assets=assets,
        asset_uids=pool["asset_uids"], asset_epochs=pool["asset_epochs"],
        identity_epoch=epoch, source_receipt=receipt, cutoff=cutoff,
        identity_history=pool["history"], qqq_opens=qq if numeric else None,
        qqq_receipt=qreceipt if numeric else None, industry_mapping=ff, industry_receipt=ireceipt)
    declaration = dict(assembly.support_declarations)
    declaration["ff48_binding_reason"] = ff_reason
    if not numeric:
        qdays = set(pd.to_datetime(qq.trade_date))
        obs = assembly.risk_input.observations
        origins = pd.DatetimeIndex(obs.origin_at.unique()).sort_values()[-252:]
        needed = []
        for o in origins:
            i = days.get_loc(o.tz_convert("America/New_York").tz_localize(None).normalize())
            needed.extend((days[i+1], days[i+6]))
        qreason = None if needed and all(d in qdays for d in needed) else "BLOCK_QQQ_OPEN_ENDPOINT_METADATA_MISSING"
        for method in ("RB", "RH", "RR", "RE"):
            declaration["method_block_reasons"][method] = [r for r in declaration["method_block_reasons"][method]
                if r != "BLOCK_QQQ_OPEN_SOURCE_UNBOUND"] + ([qreason] if qreason else [])
        declaration["qqq_binding_reason"] = qreason
        declaration["qqq_numeric_support"] = "UNKNOWN_UNTIL_FROZEN_OPEN_PROJECTION"
        recent_dates = {o.tz_convert("America/New_York").tz_localize(None).normalize() for o in origins}
        supported = labels.signal_date.isin(recent_dates) & labels.label_available.eq(True) & labels.endpoint_pair_available.eq(True) & labels.label_unsupported_common_event.eq(False)
        eligible_counts = (supported & labels.security_id.eq(labels.ticker.map(pool["asset_uids"]))
                           & labels.identity_epoch.eq(labels.ticker.map(pool["asset_epochs"])))
        counts_by_asset = labels.loc[eligible_counts].groupby("ticker", sort=False).size()
        counts = {asset: int(counts_by_asset.get(asset, 0)) for asset in assets}
        declaration["metadata_supported_labels_by_asset"] = counts
        if len(origins) < 252 or any(v < 30 for v in counts.values()):
            for method in METHODS:
                declaration["method_block_reasons"][method].append("BLOCK_METADATA_252_OR_ASSET30_SUPPORT")
        declaration["numeric_label_finiteness"] = "UNKNOWN_NOT_READ"
    if ff_reason and ff_reason not in declaration["method_block_reasons"]["RH"]:
        declaration["method_block_reasons"]["RH"].append(ff_reason)
    return pool, assembly, declaration


def load_component_period(reader, source, science, days, cutoff, *, numeric, expected=None, complete=False):
    """One prespecified metadata domain for every method; values never select it."""
    pool, assembly, declaration = load_period(reader, source, science, days, cutoff,
                                               numeric=False, allow_partial_uid=True)
    parent = pool.get("parent_requested", {k: pool[k] for k in
        ("assets", "asset_uids", "asset_epochs", "segment_starts", "blocked_assets")})
    pool["parent_requested"] = parent
    declaration["parent_full_pool_blocked_assets"] = parent["blocked_assets"]
    if assembly is None:
        declaration.update(reason="BLOCK_COMPONENT_VALID_UID_DOMAIN_EMPTY",
                           parent_origin_window=[], excluded_reasons=dict(parent["blocked_assets"]))
        return pool, None, declaration
    inputs = assembly.risk_input
    labels = pool["component_labels"]
    # Freeze the parent's origin window before the FF48 / minimum support filter.
    origins = pd.DatetimeIndex(inputs.observations.origin_at.unique()).sort_values()[-252:]
    legal_keys = {(row.asset, row.origin_at) for row in inputs.observations.itertuples()}
    good = (labels.label_available.eq(True) & labels.endpoint_pair_available.eq(True)
            & labels.label_unsupported_common_event.eq(False)
            & labels.label_coordinate.eq(STORED_LABEL_COORDINATE))
    supported = [(a, _clock(d)) in legal_keys and _clock(d) in origins
                 for a, d in labels[["ticker", "signal_date"]].itertuples(index=False, name=None)]
    good = good & pd.Series(supported, index=labels.index)
    groups = inputs.industry_mapping
    grouped = set(groups.asset) if groups is not None else set()
    excluded = {a: [reason] for a, reason in parent["blocked_assets"].items()}
    counts, assets, partial_assets = {}, [], []
    counts_by_asset = labels.loc[good].groupby("ticker", sort=False).size()
    for asset in pool["assets"]:
        count = int(counts_by_asset.get(asset, 0))
        counts[asset] = count
        reasons = []
        if count < 30:
            reasons.append("BLOCK_COMPONENT_SUPPORTED_H5_LT30")
        elif complete and count != 252:
            reasons.append("BLOCK_COMPLETE_COMMON_SUPPORTED_H5_NE252")
        if not declaration["inference_support"][asset]:
            reasons.append("BLOCK_COMPONENT_CURRENT_UID_CONTINUITY")
        if asset not in grouped:
            reasons.append("BLOCK_COMPONENT_EXACT_ASOF_FF48_MISSING")
        if count >= 30 and declaration["inference_support"][asset] and asset in grouped:
            partial_assets.append(asset)
        if reasons:
            excluded[asset] = reasons
        else:
            assets.append(asset)
    assets = tuple(assets)
    selected = inputs.observations.loc[inputs.observations.asset.isin(assets)
                                      & inputs.observations.origin_at.isin(origins)].copy()
    covered = set(selected.origin_at)
    reasons = []
    if len(origins) != 252:
        reasons.append("BLOCK_COMPONENT_PARENT_252_ORIGINS")
    if len(assets) < 2:
        reasons.append("BLOCK_COMPONENT_FEWER_THAN_TWO_ASSETS")
    if covered != set(origins):
        reasons.append("BLOCK_COMPONENT_PARENT_ORIGIN_UNION_NOT_COVERED")
    if assets == tuple(parent["assets"]):
        reasons.append("REUSE_ORIGINAL_FULL_DOMAIN_NOT_COMPONENT")
    window = [o.isoformat() for o in origins]
    requested = {k: parent[k] for k in ("assets", "asset_uids", "asset_epochs", "segment_starts", "blocked_assets")}
    complete_proof_pool = dict(pool, assets=assets, parent_requested=requested)
    pool.update(assets=assets, asset_uids={a: pool["asset_uids"][a] for a in assets},
                asset_epochs={a: pool["asset_epochs"][a] for a in assets},
                segment_starts={a: pool["segment_starts"][a] for a in assets},
                blocked_assets={}, parent_requested=requested, parent_origin_window=window)
    declaration.update(parent_origin_window=window, excluded_reasons=excluded,
        component_supported_h5_by_asset=counts, component_assets=list(assets),
        parent_requested_assets=list(parent["assets"]),
        parent_full_pool_status="BLOCKED" if parent["blocked_assets"] or excluded else "METADATA_ONLY",
        component_selection_basis="SINGLE_CONTIGUOUS_UID_SUPPORTED_H5_GE30_AND_EXACT_ASOF_FF48; no y selection",
        account_attempts=0, forecast_fits=0,
        snapshot_roles=science.get("snapshot_roles", {}))
    if complete:
        proof = _complete_domain_proof(science, complete_proof_pool, tuple(partial_assets),
                                       counts, window, cutoff)
        pool["domain_comparison"] = declaration["domain_comparison"] = proof
        declaration["component_selection_basis"] = (
            "PARENT_252_WINDOW_FIRST; EXACT_252_METADATA_SUPPORTED_H5_AND_EXACT_UID_FF48; NO_NUMERIC_SELECTION")
        if assets and proof["relation"] != "STRICT_SUBSET" and not reasons:
            reasons.append("REUSE_REQUIRED_EXACT_PRIOR_SCIENTIFIC_STATE_NOT_NEW_FIT")
    # Component exclusions do not change the parent's status or the fixed window.
    methods = {m: list(reasons) for m in METHODS}
    methods["RM"].append("BLOCK_UNBOUND_STOCK_HORIZONS_3_10_20")
    qreason = declaration.get("qqq_binding_reason")
    if qreason:
        for method in ("RB", "RH", "RR", "RE"):
            methods[method].append(qreason)
    declaration["method_block_reasons"] = methods
    if reasons:
        declaration["reason"] = reasons[0]
        return pool, None, declaration
    epoch = "COMPONENT_CURRENT_UIDS:" + content_hash(pool["asset_epochs"])
    receipt = replace(inputs.source_receipt, identity_epoch=epoch)
    selected.loc[:, "identity_epoch"] = epoch
    mapping = groups.loc[groups.asset.isin(assets)].copy()
    mapping.loc[:, "identity_epoch"] = epoch
    industry_receipt = replace(inputs.industry_receipt, identity_epoch=epoch)
    result = replace(inputs, assets=assets, observations=selected, source_receipt=receipt,
        asset_uids=pool["asset_uids"], identity_epoch=epoch, industry_mapping=mapping,
        industry_receipt=industry_receipt)
    if not numeric:
        return pool, replace(assembly, risk_input=result, support_declarations=declaration), declaration
    if expected is None or any(_json(pool[k]) != expected[k] for k in
            ("assets", "asset_uids", "asset_epochs", "parent_origin_window")):
        raise ValueError("FROZEN_COMPONENT_DOMAIN_OR_ORIGIN_WINDOW_CHANGED")
    if complete and pool["domain_comparison"] != expected.get("domain_comparison"):
        raise ValueError("FROZEN_COMPLETE_COMMON_DOMAIN_PROOF_CHANGED")
    prior = pd.Timestamp(cutoff).tz_convert("America/New_York").tz_localize(None).normalize()
    origin_days = [o.tz_convert("America/New_York").tz_localize(None).normalize() for o in origins]
    values = reader.read("extended_shareholder_y5", (*LABEL_META, "y_open5"),
        date_field="signal_date", start=min(origin_days), stop=prior, tickers=assets,
        mature_before=prior, origin_dates=origin_days)
    metadata = labels.loc[labels.ticker.isin(assets) & labels.signal_date.isin(origin_days)].drop(columns="y_open5")
    labels_numeric = metadata.merge(values[["ticker", "signal_date", "y_open5"]],
                                   on=["ticker", "signal_date"], how="left", validate="one_to_one")
    numeric_good = good.loc[metadata.index].to_numpy()
    finite = np.isfinite(pd.to_numeric(labels_numeric.y_open5, errors="coerce").to_numpy(float))
    if complete and (len(metadata) != 252*len(assets) or not numeric_good.all()):
        declaration["reason"] = "BLOCK_COMPLETE_COMMON_SELECTED_252XN_METADATA_SLOTS_CHANGED"
        return pool, None, declaration
    if not finite[numeric_good].all():
        declaration["reason"] = "BLOCK_COMPONENT_NUMERIC_FINITE_SUPPORT_CHANGED"
        return pool, None, declaration
    qstart = days[max(0, days.get_loc(prior)-360)]
    q = reader.read("qqq_qfq_years", ("ticker", "trade_date", "open"), date_field="trade_date",
                    start=qstart, stop=prior, tickers=("QQQ",))
    qreceipt = _receipt(source, science, cutoff, "EXISTING_QQQ_QFQ_OPEN_PROXY", benchmark=True)
    group_input = mapping.copy()
    group_input["uid"] = group_input.asset.map(pool["asset_uids"])
    packaged = assemble_risk_inputs(labels_numeric, days, assets=assets, asset_uids=pool["asset_uids"],
        asset_epochs=pool["asset_epochs"], identity_epoch=epoch, source_receipt=receipt, cutoff=cutoff,
        identity_history=pool["history"], qqq_opens=q, qqq_receipt=qreceipt,
        industry_mapping=group_input, industry_receipt=industry_receipt)
    return pool, packaged, declaration


class DurableFitLedger:
    """The existing FIT_STATUS shape, extended with compact physical reservations.

    Fit attempts count learned states, including failure/abandonment. Deterministic
    operations are recorded at zero learned cost. Caller holds existing task_writer.
    """
    def __init__(self, run, *, stage="risk"):
        self.run, self.stage = Path(run), stage
        scope = read_json(self.run / "BUDGET_SCOPE_FREEZE.json")
        self.inherited = scope["prior_ledger"]["reserved"]
        self.new_cap = scope["effective_new_cap"]
        self.stage_cap = scope["stage1_learned_cap"]
        if (self.inherited, self.new_cap, self.stage_cap, scope["branch_cumulative_cap"]) != (968, 2048, 1024, 4096):
            raise ValueError("FROZEN_B_BUDGET_SCOPE_REQUIRED")
        target = self.run / "work/FIT_STATUS.json"
        self.status = read_json(target) if target.exists() else dict(status="READY",
            fit_attempts=self.inherited, inherited_fit_units=self.inherited,
            new_fit_units=0, risk_fit_units=0, records=[], failures=[], physical_events=[],
            account_paths=2, test2026_rows_read=0)
        if self.status.get("inherited_fit_units") != self.inherited or self.status.get("fit_attempts") != self.inherited + self.status.get("new_fit_units", -1):
            raise ValueError("INHERITED_B_FIT_COUNTER_CHANGED")
        if self.status.get("account_paths") != 2 or self.status.get("test2026_rows_read") != 0:
            raise ValueError("RISK_RUN_ACCOUNT_OR_TIME_SCOPE_CHANGED")
        self.status.setdefault("physical_events", [])
        self.status.setdefault("risk_fit_units", 0)
        self.active_rr_correction = None
        self.active_complete_group = None

    def checkpoint(self):
        write(self.run, "work/FIT_STATUS.json", self.status)

    def reserve(self, event):
        if any(e["key"] == event["key"] for e in self.status["physical_events"]):
            raise ValueError("RESERVED_OR_FAILED_PHYSICAL_KEY_NO_AUTOMATIC_RETRY")
        cost = int(event["kind"] in LEARNED_KINDS)
        if self.status["new_fit_units"] + cost > self.new_cap:
            raise ValueError("NEW_MECHANISM_CAP_EXCEEDED")
        if self.stage == "risk" and self.status["risk_fit_units"] + cost > self.stage_cap:
            raise ValueError("RISK_STAGE_CAP_EXCEEDED")
        if self.active_rr_correction is not None:
            scope = self.active_rr_correction
            if cost and event["kind"] == "scaler" and event["name"] in {"stock_preprocessing", "stock_observed_mean"}:
                raise ValueError("RR_CORRECTION_GLOBAL_STOCK_PREPROCESSING_MUST_REUSE")
            if self.status["new_fit_units"] - scope["start_new_fit_units"] + cost > 7:
                raise ValueError("RR_CORRECTION_QUARTER_CAP_EXCEEDED_NO_REFUND")
        if self.active_complete_group is not None:
            if self.status["new_fit_units"] - self.active_complete_group["stage_start_new_fit_units"] + cost > 341:
                raise ValueError("COMPLETE_COMMON_STAGE_CAP_EXCEEDED_NO_REFUND")
            if self.status["new_fit_units"] - self.active_complete_group["start_new_fit_units"] + cost > 31:
                raise ValueError("COMPLETE_COMMON_GROUP_CAP_EXCEEDED_NO_REFUND")
        record = _json(event)
        if self.active_complete_group is not None:
            record.update(complete_common_node=self.active_complete_group["risk_node"],
                complete_execution_freeze_sha256=self.active_complete_group["execution_freeze_sha256"],
                complete_group_as_of=self.active_complete_group["as_of"])
        if self.active_rr_correction is not None:
            record.update(corrected_rr_node=self.active_rr_correction["risk_node"],
                          correction_freeze_sha256=self.active_rr_correction["freeze_sha256"])
        record.update(status="STARTED", learned_states=cost, stage=self.stage,
                      started_utc=datetime.now(timezone.utc).isoformat())
        self.status["physical_events"].append(record)
        self.status["new_fit_units"] += cost
        self.status["fit_attempts"] += cost
        self.status[self.stage + "_fit_units"] = self.status.get(self.stage + "_fit_units", 0) + cost
        self.status["status"] = "FROZEN_HISTORY_MECHANISM_FITS_RUNNING"
        self.checkpoint()  # Return only after the durable reservation exists.

    def sync(self, events):
        bykey = {r["key"]: r for r in self.status["physical_events"]}
        for e in events:
            if e["key"] not in bykey:
                continue
            row = bykey[e["key"]]
            row["status"] = {"SUCCEEDED": "FIT_COMPLETE", "FAILED": "FIT_FAILURE"}.get(e["status"], "STARTED")
            for field in ("result_sha256", "dependencies"):
                if field in e:
                    row[field] = _json(e[field])
            if e["status"] == "FAILED" and not any(r.get("key") == e["key"] for r in self.status["failures"]):
                self.status["failures"].append(dict(key=e["key"], kind=e["kind"], name=e["name"]))
        self.checkpoint()


def _bind_rr_budget_guard(budget, ledger):
    """Preflight the existing budget reservation; never count or fit beyond the scope."""
    original_reserve = budget.reserve
    def reserve(key, kind, name, context, inputs_sha256, parameters):
        if ledger.active_complete_group is not None:
            scope = ledger.active_complete_group
            cost = int(kind in LEARNED_KINDS)
            if ledger.status["new_fit_units"] - scope["stage_start_new_fit_units"] + cost > 341:
                raise ValueError("COMPLETE_COMMON_STAGE_CAP_EXCEEDED_NO_REFUND")
            if ledger.status["new_fit_units"] - scope["start_new_fit_units"] + cost > 31:
                raise ValueError("COMPLETE_COMMON_GROUP_CAP_EXCEEDED_NO_REFUND")
        scope = ledger.active_rr_correction
        if scope is not None:
            cost = int(kind in LEARNED_KINDS)
            if cost and kind == "scaler" and name in {"stock_preprocessing", "stock_observed_mean"}:
                raise ValueError("RR_CORRECTION_GLOBAL_STOCK_PREPROCESSING_MUST_REUSE")
            if ledger.status["new_fit_units"] - scope["start_new_fit_units"] + cost > 7:
                raise ValueError("RR_CORRECTION_QUARTER_CAP_EXCEEDED_NO_REFUND")
        return original_reserve(key, kind, name, context, inputs_sha256, parameters)
    budget.reserve = reserve
    return budget


def support(run, *, component=False, complete=False):
    component = component or complete
    run, source, science, _ = (guard_complete_run(run, "support") if complete else
        guard_run(run, "component-support" if component else "support"))
    loader = load_component_period if component else load_period
    support_name = "RISK_COMPLETE_COMMON_SUPPORT.json" if complete else (
        "RISK_COMPONENT_SUPPORT.json" if component else "RISK_SUPPORT.json")
    reader = ProjectedReader(source, phase="support")
    calendar = reader.read("calendar", ("trade_date",), date_field="trade_date")["trade_date"]
    days, _ = _calendar(calendar)
    nodes = complete_schedule(days) if complete else schedule(days)
    output = []
    for asof in sorted({n["as_of"] for n in nodes}):
        group = [n for n in nodes if n["as_of"] == asof]
        cutoff = pd.Timestamp(group[0]["cutoff"])
        pool, assembly, declaration = loader(reader, source, science, days, cutoff, numeric=False,
            **({"complete": True} if complete else {}))
        for node in group:
            reasons = (declaration.get("method_block_reasons", {}).get(node["method"], [declaration.get("reason", "BLOCK_COMPONENT_SOURCE")])
                       if assembly is None else declaration["method_block_reasons"][node["method"]])
            output.append({**node, **{k: _json(pool[k]) for k in
                ("assets", "asset_uids", "asset_epochs", "segment_starts", "blocked_assets")},
                **({"parent_requested": _json(pool["parent_requested"]),
                    "parent_origin_window": pool.get("parent_origin_window", declaration.get("parent_origin_window", [])),
                    "excluded_reasons": declaration.get("excluded_reasons", {})} if component else {}),
                **({"domain_comparison": pool["domain_comparison"]} if complete and "domain_comparison" in pool else {}),
                "metadata_block_reasons": reasons, "numeric_check_eligible": not reasons,
                "source_requirements": ["extended_shareholder_y5", "shareholder_y5", "prediction_features",
                    "raw_open_close", "calendar"] + (["ff48_surface"] if component else []) + (["qqq_qfq_years"] if node["method"] in {"RB","RH","RR","RE"} else []),
                "declarations": declaration})
        del pool, assembly, declaration
        gc.collect()
    result = dict(schema="B_R3_RISK_QUALIFICATION_ONLY_SUPPORT_V1",
        source_inputs_sha256=sha(run / "FAMILY_SOURCE_INPUTS.json"),
        family_design_freeze_sha256=source["family_design_freeze_sha256"],
        control_qualification_sha256=source["control_gate_sha256"], nodes=output,
        numeric_reads=0, fit_units=0, account_attempts=0, test2026_rows_read=0,
        strict_PIT_promotion_eligible=False, historical_publication_revision_authority="UNKNOWN",
        inference_pool_policy="PRIOR_CLOSE_ACCEPTED_FEATURE_FLAGS_AND_RAW_ROW_KEYS; no label completeness selection",
        numeric_support="UNKNOWN; metadata eligibility is not finite-return qualification",
        projections=reader.audit)
    if component and not complete:
        result.update(schema="B_R3_SOURCE_QUALIFIED_COMPONENT_SUPPORT_V1",
            research_id=science["scientific_contract_identity"],
            risk_component_science_sha256=science["scientific_contract_sha256"],
            parent_full_pool_support_sha256=sha(run / "RISK_SUPPORT.json"),
            forecast_fits=0)
    if complete:
        result.update(schema="B_R3_COMPLETE_COMMON_H5_FF48_SUPPORT_V1",
            research_id=COMPLETE_ID, domain_role="COMPLETE_COMMON_COMPONENT", forecast_fits=0,
            risk_complete_common_science_sha256=science["scientific_contract_sha256"],
            parent_component_support_sha256=science["parent_component_support_sha256"])
    write(run, support_name, result, immutable=True)
    return dict(status="SUPPORT_COMPLETE", nodes=len(output),
                metadata_numeric_check_eligible=sum(n["numeric_check_eligible"] for n in output),
                fit_units=0, sha256=sha(run / support_name))


def fit(run, *, component=False, complete=False):
    component = component or complete
    run, source, science, freeze = (guard_complete_run(run, "fit") if complete else
        guard_run(run, "component-fit" if component else "fit"))
    loader = load_component_period if component else load_period
    support_name = "RISK_COMPLETE_COMMON_SUPPORT.json" if complete else ("RISK_COMPONENT_SUPPORT.json" if component else "RISK_SUPPORT.json")
    freeze_name = "RISK_COMPLETE_COMMON_EXECUTION_FREEZE.json" if complete else ("RISK_COMPONENT_EXECUTION_FREEZE.json" if component else "FAMILY_EXECUTION_FREEZE.json")
    support_key = "risk_complete_common_support_sha256" if complete else ("risk_component_support_sha256" if component else "risk_support_sha256")
    prefix = "complete:" if complete else ("component:" if component else "")
    correction = guard_rr_correction(run, science, freeze) if component and not complete else None
    qualified = read_json(run / support_name)["nodes"]
    if complete and len({n["as_of"] for n in qualified if n["numeric_check_eligible"]}) > 11:
        raise ValueError("COMPLETE_COMMON_MAXIMUM_11_NUMERIC_GROUPS")
    (run / "work").mkdir(parents=True, exist_ok=True)
    with task_writer(run):
        ledger = DurableFitLedger(run)
        validate_risk_recovery(run, ledger.status, component=component, complete=complete)
        complete_activation = activate_complete(run, ledger, freeze) if complete else None
        activation = activate_rr_correction(run, ledger, correction, qualified)
        reader = ProjectedReader(source, phase="fit")
        days, _ = _calendar(reader.read("calendar", ("trade_date",), date_field="trade_date").trade_date)
        if [(n["method"], n["as_of"], n["cutoff"]) for n in qualified] != [
                (n["method"], n["as_of"], n["cutoff"]) for n in (complete_schedule(days) if complete else schedule(days))]:
            raise ValueError("FROZEN_SUPPORT_SCHEDULE_CHANGED")
        budget = _bind_rr_budget_guard(
            StateBudget(limit=1024-ledger.status["risk_fit_units"], reserve_callback=ledger.reserve), ledger)
        records = ledger.status["records"]
        for retained in records:
            if retained.get("risk_node") and retained.get("artifact"):
                _pin(retained["artifact"], retained["sha256"], "retained_risk_state")
        for asof in sorted({n["as_of"] for n in qualified}):
            group = [n for n in qualified if n["as_of"] == asof]
            pending = [n for n in group if _pending_risk_node(n, records, prefix, correction)]
            if not pending:
                continue
            active = [n for n in pending if n["numeric_check_eligible"]]
            pool, assembly, declaration = (None, None, None)
            if active:
                pool, assembly, declaration = loader(reader, source, science, days,
                    pd.Timestamp(group[0]["cutoff"]), numeric=True,
                    **({"expected": active[0]} if component else {}),
                    **({"complete": True} if complete else {}))
                if assembly is None and not component:
                    raise ValueError("FROZEN_POOL_ASSEMBLY_CHANGED")
                if list(pool["assets"]) != active[0]["assets"] or pool["asset_uids"] != active[0]["asset_uids"] or pool["asset_epochs"] != active[0]["asset_epochs"]:
                    raise ValueError("FROZEN_INFERENCE_POOL_CHANGED")
            engine = SharedRiskEngine(budget=budget)
            if complete:
                ledger.active_complete_group = dict(as_of=asof, risk_node=None,
                    execution_freeze_sha256=sha(run / freeze_name),
                    start_new_fit_units=ledger.status["new_fit_units"],
                    stage_start_new_fit_units=freeze["checkpoint_new_fit_units"])
            for node in pending:
                key = prefix+node["method"]+"@"+asof
                record = dict(risk_node=key, method=node["method"], as_of=asof, cutoff=node["cutoff"],
                              assets=node["assets"], asset_uids=node["asset_uids"],
                              asset_epochs=node["asset_epochs"], strict_PIT_promotion_eligible=False,
                              implementation_lineage=science.get("implementation_lineage", {}),
                              **({**{k: node[k] for k in ("parent_requested", "parent_origin_window", "excluded_reasons")},
                                  "snapshot_roles": science.get("snapshot_roles", {})} if component else {}))
                if complete:
                    ledger.active_complete_group["risk_node"] = key
                    record.update(research_id=COMPLETE_ID, domain_role="COMPLETE_COMMON_COMPONENT",
                        risk_complete_common_science_sha256=science["scientific_contract_sha256"],
                        complete_execution_freeze_sha256=sha(run / freeze_name),
                        domain_comparison=node.get("domain_comparison"))
                corrected = (correction is not None and node["method"] == "RR"
                             and asof in RR_CORRECTION_ASOFS)
                if corrected:
                    if not any(r.get("risk_node") == key for r in records):
                        original = dict(record, status="CORRECTION_NOT_EXECUTED", learned_states=0,
                            block_reasons=["SEPARATE_PRE_REGISTERED_SOURCE_RANGE_CORRECTION"],
                            correction_freeze_sha256=correction["freeze_sha256"])
                        records.append(original)
                        ledger.checkpoint()
                    key = "corrected_rr:RR@" + asof
                    record.update(risk_node=key, research_id=RR_CORRECTION_ID,
                        correction_envelope=rr_correction_envelope(correction, node),
                        correction_activation_sha256=activation["sha256"])
                if not node["numeric_check_eligible"] or (component and assembly is None):
                    record.update(status="BLOCKED_METADATA" if not node["numeric_check_eligible"] else "BLOCKED_NUMERIC_SOURCE",
                        block_reasons=node["metadata_block_reasons"] if not node["numeric_check_eligible"] else [declaration["reason"]],
                        learned_states=0)
                    records.append(record)
                    ledger.checkpoint()
                    continue
                risk_input = assembly.risk_input
                if corrected or (complete and node["method"] == "RR"):
                    try:
                        risk_input = _corrected_rr_input(assembly, days, node)
                    except ValueError as error:
                        record.update(status="BLOCKED_INPUT_SOURCE_RANGE", learned_states=0,
                                      block_reasons=[str(error)])
                        records.append(record)
                        ledger.checkpoint()
                        continue
                record.update(status="STARTED", started_utc=datetime.now(timezone.utc).isoformat())
                records.append(record)
                ledger.checkpoint()
                count = budget.learned_total
                try:
                    if corrected:
                        ledger.active_rr_correction = dict(risk_node=key,
                            freeze_sha256=correction["freeze_sha256"],
                            start_new_fit_units=ledger.status["new_fit_units"])
                    with threadpool_limits(limits=2):
                        state = engine.fit(node["method"], risk_input, as_of=pd.Timestamp(asof))
                    if corrected:
                        envelope = record["correction_envelope"]
                        original_state_id = state.risk_state_id
                        state = replace(state, risk_state_id=content_hash(dict(
                            correction_envelope=envelope, engine_state_id=original_state_id)),
                            notes={**state.notes, "correction_envelope": envelope,
                                   "parent_engine_state_id": original_state_id})
                    ledger.sync(budget.events)
                    target = run / "models/risk" / (state.risk_state_id + ".joblib")
                    assert_safe_output_path(target, kind="backtest", paths=resolve(REPO))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists():
                        raise ValueError("UNREGISTERED_RISK_ARTIFACT_PRESERVED")
                    joblib.dump(state, target, compress=3)
                    record.update(status=state.status, risk_state_id=state.risk_state_id,
                        artifact=str(target), sha256=sha(target), learned_states=budget.learned_total-count,
                        fit_dependency_ids=list(state.fit_dependency_ids), notes=_json(state.notes))
                except BaseException as error:
                    ledger.sync(budget.events)
                    record.update(status="FIT_FAILURE", error=repr(error), learned_states=budget.learned_total-count)
                    ledger.status["failures"].append(dict(risk_node=key, error=repr(error)))
                    ledger.checkpoint()
                    raise  # No refund and no automatic retry.
                finally:
                    ledger.active_rr_correction = None
                ledger.checkpoint()
                print(json.dumps(dict(risk_node=key, status=record["status"],
                    new_fit_units=ledger.status["new_fit_units"])), flush=True)
            ledger.active_complete_group = None
            del engine, pool, assembly, declaration
            gc.collect()
        if any(r.get("status") in {"STARTED", "FIT_FAILURE"} for r in records if r.get("risk_node") and _stage_node(r["risk_node"], component=component, complete=complete)):
            raise ValueError("FAILED_OR_INTERRUPTED_NODE_REQUIRES_EXPLICIT_REPAIR")
        ledger.status["status"] = "FROZEN_HISTORY_RISK_COMPLETE_COMMON_STAGE_COMPLETE" if complete else (
            "FROZEN_HISTORY_RISK_COMPONENT_STAGE_COMPLETE" if component else "FROZEN_HISTORY_RISK_STAGE_COMPLETE")
        ledger.checkpoint()
        result = dict(schema="B_R3_RISK_STAGE_COMPACT_AUDIT_V1",
            execution_freeze_sha256=sha(run / freeze_name),
            implementation_lineage=science.get("implementation_lineage", {}),
            risk_support_sha256=freeze[support_key], actual_new_fit_units=ledger.status["new_fit_units"],
            risk_fit_units=ledger.status["risk_fit_units"], inherited_prior_reserved=968,
            b_cumulative_fit_units=ledger.status["fit_attempts"], no_refund=True, retry_limit=0,
            account_attempts=0, test2026_rows_read=0, strict_PIT_promotion_eligible=False,
            workers=1, library_threads=2, nodes=[r for r in records if r.get("risk_node")
                   and _stage_node(r["risk_node"], component=component, complete=complete)
                   and not r["risk_node"].startswith("corrected_rr:")],
            projections=reader.audit)
        if component and not complete:
            result.update(research_id=science["scientific_contract_identity"],
                          risk_component_science_sha256=science["scientific_contract_sha256"], forecast_fits=0,
                          notes=dict(snapshot_roles=science.get("snapshot_roles", {})))
        if correction is not None:
            corrected_nodes = [r for r in records if r.get("risk_node", "").startswith("corrected_rr:")]
            correction_events = [e for e in ledger.status["physical_events"] if e.get("corrected_rr_node")]
            result.update(corrected_rr_nodes=corrected_nodes,
                rr_correction=dict(research_id=RR_CORRECTION_ID,
                    correction_freeze_sha256=correction["freeze_sha256"],
                    correction_spec_sha256=correction["correction_spec_sha256"],
                    activation_receipt_sha256=activation["sha256"],
                    learned_fit_units=sum(e["learned_states"] for e in correction_events),
                    completed_nodes=len(corrected_nodes), max_quarters=6, per_quarter_cap=7,
                    original_rr_reexecuted=False, original_component_nodes_preserved=True,
                    stock_preprocessing_new_fit_units=0, account_equivalence=False,
                    strict_PIT_promotion_eligible=False))
        if complete:
            events = [e for e in ledger.status["physical_events"] if e.get("complete_common_node")]
            result.update(research_id=COMPLETE_ID, domain_role="COMPLETE_COMMON_COMPONENT",
                forecast_fits=0, notes=dict(snapshot_roles=science.get("snapshot_roles", {})),
                risk_complete_common_science_sha256=science["scientific_contract_sha256"],
                source_inputs_sha256=sha(run / "FAMILY_SOURCE_INPUTS.json"),
                activation_receipt_sha256=complete_activation["sha256"],
                stage_new_fit_units=sum(e["learned_states"] for e in events),
                max_additional_learned_units=341, max_group_learned_units=31,
                account_equivalence=False)
        output_name = "derived/RISK_COMPLETE_COMMON_STAGE_AUDIT.json" if complete else (
            "derived/RISK_COMPONENT_STAGE_AUDIT.json" if component else "derived/RISK_STAGE_AUDIT.json")
        write(run, output_name, result)
        return dict(status=ledger.status["status"], risk_fit_units=ledger.status["risk_fit_units"],
                    cumulative_B_fit_units=ledger.status["fit_attempts"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--phase", required=True, choices=("support", "fit", "component-support", "component-fit", "complete-support", "complete-fit"))
    args = parser.parse_args()
    function = support if args.phase.endswith("support") else fit
    print(json.dumps(function(args.run, component=args.phase.startswith("component-"), complete=args.phase.startswith("complete-"))), flush=True)


if __name__ == "__main__":
    main()

