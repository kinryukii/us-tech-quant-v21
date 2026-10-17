"""Fixed C physical reservation kernel; no raw reader, head recipe or authority.

The old runner owns bounded risk fitting and the canonical modules own UID inputs
and projection. This entry consumes the unchanged PHYSICAL_DAG fields. Strict
source receipts and explicitly retrospective frozen-history contracts have
separate gates; mechanism qualification cannot become strict PIT promotion.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from pathlib import Path
import os
import copy

from scripts.common import storage_paths
from scripts.research.a2.risk import joint_risk_estimators as risk
from scripts.research.a2.training import selector_challenge as prior
from scripts.research.a2.training import selector_risk_challenge as old
from scripts.research.a2.training import selector_risk_features as features
from scripts.research.a2.training import selector_risk_preflight as preflight

REFERENCES = ("MATCHED_ANNUAL_FIXED_CORE_RIDGE_REFERENCE",
              "MATCHED_ANNUAL_FIXED_CORE_HGB_REFERENCE")
GATES = ("budget_frozen", "source_qualified", "source_contract_bound",
         "uid_epoch_qualified", "availability_qualified", "oof_reuse_qualified",
         "canonical_research_id_accepted")
SOURCE_CHECKS = ("provider_and_version_verified", "calendar_and_timezone_verified",
                 "lawful_availability_verified", "c_return_coordinate_verified",
                 "source_version_verified", "endpoint_predecessor_uid_unit_verified",
                 "uid_epoch_policy_verified", "source_proof_bytes_verified",
                 "cutoff_known_universe_verified", "strictly_pre2026_verified")
# Typed charges from the existing DAG, not the canonical bundle's coarse counter.
METHOD_CHARGES = {"DIAG": (0, 0, 0), "LW": (1, 0, 1), "OAS": (1, 0, 1),
                  "PCA": (1, 1, 1), "EWMA": (0, 2, 1)}
COORDINATE = "DIMENSIONLESS_FRACTIONAL_PIT_FORWARD_REHAB_INDEX_PROXY"
CONTROLS = dict(base_fit_calls=0, calibration_fit_calls=0, fusion_fit_calls=0,
                configs_per_role=1, seeds_per_role=1, threads=2, workers=1,
                retries_per_scientific_slot=0)
REQUIRED_SOURCES = (Path(risk.__file__), Path(features.__file__), Path(old.__file__),
                    Path(preflight.__file__), Path(prior.__file__),
                    Path(storage_paths.__file__), Path(__file__))


class ExecutionBlocked(ValueError):
    """Missing frozen identity/qualification stops before any supplied callable."""


def _require(condition, reason):
    if not condition:
        raise ExecutionBlocked(reason)


def _integer(value, expected):
    return type(value) is int and value == expected


def expanded_slots(dag):
    """Validate and expand the existing cutoff/method grid without I/O or fits."""
    contract = dag["scientific_contract"]
    preflight.assert_fixed_family(contract["candidate_roles"], seed=contract["seed"],
        window_sessions=contract["window_sessions"],
        min_observations=contract["min_observations"], target=contract["target"],
        core_methods=contract["core_methods"])
    _require(contract["risk_years"] == list(preflight.YEARS)
             and contract["head_years"] == [2023, 2024, 2025]
             and contract["fixed_reference_roles"] == list(REFERENCES)
             and contract["risk_refresh_cadence"] == "MONTHLY_FIRST_ACCEPTED_SESSION"
             and contract["head_cadence"] == "ANNUAL"
             and contract["head_hyperparameter_search"] is False
             and contract["target_changed"] is False
             and _integer(contract["candidate_count"], 4)
             and _integer(contract["reference_candidate_count"], 0)
             and _integer(contract["monthly_cutoff_max"], 48), "R3_FAMILY_CHANGED")
    plan = dag["risk_slot_reservation_plan"]
    _require(plan["encoding"] == "CUT_OFF_METHOD_CARTESIAN_GRID",
             "R3_GRID_ENCODING_CHANGED")
    expected_cutoffs = [dict(cutoff_ref=f"FIRST_ACCEPTED_SESSION:{y}-{m:02d}",
        purpose="FOUR_CANDIDATES_SHARED_RISK_STATE")
        for y in preflight.YEARS for m in range(1, 13)]
    expected_cutoffs += [dict(cutoff_ref=f"{y}-01-01T00:00:00",
        purpose="OPTIONAL_FIXED_REFERENCE_SHARED_RISK_STATE") for y in preflight.YEARS]
    _require(plan["cutoffs"] == expected_cutoffs, "R3_CUTOFF_OR_PURPOSE_CHANGED")
    _require([entry["method"] for entry in plan["per_method"]] == list(preflight.CORE),
             "R3_CORE_ORDER_CHANGED")
    slots = []
    for cutoff in plan["cutoffs"]:
        cadence = "MONTHLY" if cutoff["cutoff_ref"].startswith("FIRST_") else "ANNUAL"
        for entry in plan["per_method"]:
            method = entry["method"]
            backend, extra, cholesky = METHOD_CHARGES[method]
            expected = dict(backend_fit_reservation=backend, prepare_statistic_reservation=2,
                extra_statistic_reservation=extra, derived_fallback_scalar_reservation=1,
                psd_validation_reservation=1, cholesky_reservation_upper=cholesky,
                attempt_limit=1, retry_limit=0)
            _require(all(_integer(entry.get(k), v) for k, v in expected.items()),
                     "R3_METHOD_RESERVATION_CHANGED")
            charge = dict(risk_state_slots=1, monthly_risk_state_slots=int(cadence == "MONTHLY"),
                possible_matched_annual_reference_risk_slots=int(cadence == "ANNUAL"),
                risk_backend_fit_calls=backend, backend_fit_calls=backend,
                risk_prepare_statistics=2, risk_extra_analytical_statistics=extra,
                risk_numpy_statistic_estimates_excluding_derived_fallback=2 + extra,
                risk_backend_plus_statistic_estimation_nodes_excluding_derived_fallback=backend + 2 + extra,
                all_backend_plus_statistic_estimation_nodes_excluding_derived_fallback=backend + 2 + extra,
                derived_fallback_scalars=1, psd_validation_ops=1, cholesky_ops=cholesky,
                all_model_year_attempt_slots=1)
            slots.append(dict(slot_id=f"RISK:{cadence}:{cutoff['cutoff_ref']}:{method}",
                kind="RISK", cadence=cadence, method=method, **cutoff, reservation=charge))
    expected_heads = [(role, year) for role in (*preflight.ROLES, *REFERENCES)
                      for year in (2023, 2024, 2025)]
    heads = dag["annual_head_reservation_plan"]
    _require([(h["role"], h["year"]) for h in heads] == expected_heads,
             "R3_HEAD_ROLE_OR_YEAR_CHANGED")
    for head in heads:
        reference = head["role"] in REFERENCES
        hgb = "HGB" in head["role"]
        _require(head["candidate"] is (not reference)
                 and head["reference_only"] is reference
                 and head["head_backend"] == ("HistGradientBoostingRegressor" if hgb else "Ridge")
                 and head["slot_id"] == f"ANNUAL_HEAD:{head['role']}:{head['year']}"
                 and all(_integer(head.get(k), v) for k, v in dict(attempt_limit=1,
                    retry_limit=0, scaler_fit_reservation=1, head_model_fit_reservation=1).items()),
                 "R3_HEAD_RESERVATION_CHANGED")
        charge = dict(annual_head_year_slots=1, candidate_head_year_slots=int(not reference),
            reference_head_year_slots=int(reference), scaler_fit_calls=1,
            hgb_fit_calls=int(hgb), ridge_fit_calls=int(not hgb), hgb_internal_trees=64 * int(hgb),
            backend_fit_calls=2, all_backend_plus_statistic_estimation_nodes_excluding_derived_fallback=2,
            all_model_year_attempt_slots=1)
        slots.append(dict(**head, kind="ANNUAL_HEAD", cadence="ANNUAL", reservation=charge))
    caps = dict(CONTROLS)
    for slot in slots:
        for name, count in slot["reservation"].items():
            caps[name] = caps.get(name, 0) + count
    _require(set(dag["proposed_caps"]) == set(caps)
             and all(_integer(dag["proposed_caps"][k], v) for k, v in caps.items())
             and dag["reservation_contract"]["all_new_one_pass_reservation_totals"] == caps
             and plan["expanded_slot_count"] == 260
             and plan["monthly_expanded_slot_count"] == 240
             and dag["reservation_contract"]["reservation_before_first_operation"] is True
             and dag["reservation_contract"]["failed_or_timeout_reservation_released"] is False
             and dag["reservation_contract"]["same_scientific_slot_second_attempt_allowed"] is False,
             "R3_CAP_OR_FAILURE_CONTRACT_CHANGED")
    return tuple(slots)


def _metadata_pin(binding, paths, kind):
    # The frozen descriptor establishes permission/scope before whole JSON access.
    _require(binding.get("metadata_only") is True
        and binding.get("content_scope") == "STRICT_PRE2026_SOURCE_METADATA"
        and binding.get("artifact_kind") == kind, "CLASSIFIED_METADATA_DESCRIPTOR_REQUIRED")
    path = Path(binding["path"]).resolve()
    _require(path.suffix.lower() == ".json" and any(path.is_relative_to(root)
        for root in (paths.results_root, paths.backtest_root, paths.cache_root)),
        "PINNED_METADATA_PATH_REQUIRED")
    _require(path.is_file() and path.stat().st_size <= 262144
             and prior.sha(path) == binding["sha256"], "PINNED_METADATA_CHANGED_OR_UNBOUNDED")
    metadata = prior.readj(path)
    _require(isinstance(metadata, dict) and metadata.get("metadata_only") is True
        and metadata.get("artifact_kind") == kind
        and metadata.get("observation_scope_end_exclusive") == "2026-01-01",
        "SOURCE_METADATA_SCOPE_REQUIRED")
    return metadata


FH_MODE = "FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY"
FH_GATES = tuple(g for g in GATES if g != "availability_qualified") + ("availability_policy_declared",)


def _frozen_history_binding(design, paths):
    """Explicit retrospective source premise; never a historical PIT receipt."""
    descriptor = design["frozen_history_source"]
    authority = _metadata_pin(descriptor, paths, "C_FROZEN_HISTORY_SOURCE_AUTHORITY_METADATA")
    _require(authority.get("schema_id") == "C_FROZEN_HISTORY_SOURCE_AUTHORITY_V1"
        and authority.get("source_policy") == FH_MODE
        and authority.get("research_id") == design.get("research_id")
        and authority.get("mechanism_research_eligible") is True
        and authority.get("strict_PIT_promotion_eligible") is False
        and authority.get("historical_available_at_proved") is False
        and authority.get("historical_revision_vintage_proved") is False
        and authority.get("test2026_locked") is True
        and authority.get("base_calibration_refits_authorized") is False
        and authority.get("identity_policy") == preflight.NO_CROSS_IDENTITY_STITCHING
        and authority.get("return_coordinate") == COORDINATE
        and authority.get("return_unit") == features.UNIT
        and _integer(authority.get("return_horizon_sessions"), 1)
        and authority.get("accepted_sessions") == design["accepted_sessions"]
        and design.get("source_proof_sha256") == descriptor["sha256"],
        "FROZEN_HISTORY_MECHANISM_AUTHORITY_REQUIRED")
    reference = authority.get("human_authorization_ref", {})
    ref_path = Path(reference.get("path", "")).resolve()
    reference_roots = (paths.results_root, paths.backtest_root)
    if design.get("synthetic_only") is True:
        reference_roots += (paths.cache_root,)
    _require(ref_path.is_file() and ref_path.stat().st_size <= 262144
        and any(ref_path.is_relative_to(root) for root in reference_roots)
        and prior.sha(ref_path) == reference.get("sha256"), "FROZEN_HISTORY_HUMAN_AUTHORIZATION_REQUIRED")
    _require(isinstance(authority.get("source_id"), str) and bool(authority["source_id"].strip()),
             "FROZEN_HISTORY_SOURCE_ID_REQUIRED")
    return dict(source_id=authority["source_id"]), descriptor["sha256"]


def _source_binding(design, paths):
    """Strict experimental consumer interface; actual C-source schema pending.

    The source owner must supply compatible C-specific metadata after verifying
    the actual shared contract. No status is converted into source acceptance.
    Parquet bytes are never opened: only the accepted receipt's proof hash binds.
    """
    if design.get("source_contract_mode") == FH_MODE:
        return _frozen_history_binding(design, paths)
    acceptance = _metadata_pin(design["c_source_acceptance"], paths, "C_SOURCE_ACCEPTANCE_METADATA")
    _require(acceptance.get("schema") == "C_R3_SOURCE_ACCEPTANCE_METADATA_V1"
        and acceptance.get("status") == "QUALIFIED_ACCEPTED"
        and _integer(acceptance.get("consumer_binding_version"), 1)
        and acceptance.get("consumer") == "C_SELECTOR_R3"
        and isinstance(acceptance.get("qualification_checks"), dict)
        and all(acceptance["qualification_checks"].get(k) is True for k in SOURCE_CHECKS),
        "C_SOURCE_ACCEPTANCE_SEMANTICS_REQUIRED")
    shared = _metadata_pin(acceptance["shared_contract"], paths, "SHARED_SOURCE_CONTRACT_METADATA")
    _require(shared.get("schema") == "SHARED_C_SOURCE_CONTRACT_METADATA_V1"
             and shared.get("status") == "QUALIFIED_ACCEPTED",
             "SHARED_SOURCE_FAIL_CLOSED_OR_UNKNOWN")
    binding = acceptance["Cret1d_binding"]
    _require(binding == shared.get("Cret1d_binding") and binding["field"] == "Cret1d"
        and binding["coordinate"] == COORDINATE
        and binding["return_unit"] == features.UNIT and _integer(binding["return_horizon_sessions"], 1)
        and binding["identity_policy"] == preflight.NO_CROSS_IDENTITY_STITCHING
        and all(isinstance(binding.get(k), str) and binding[k].strip()
                for k in ("provider", "provider_version", "source_version", "source_id"))
        and binding["session_timezone"] == "America/New_York"
        and binding["scope_end_exclusive"] == "2026-01-01",
        "C_RETURN_SOURCE_BINDING_REQUIRED")
    proof = acceptance["source_proof"]
    _require(proof == shared.get("source_proof")
        and proof["sha256"] == design["source_proof_sha256"]
        and isinstance(proof["sha256"], str) and len(proof["sha256"]) == 64
        and all(c in "0123456789abcdef" for c in proof["sha256"])
        and str(proof["path"]).lower().endswith(".parquet"), "SOURCE_PROOF_HASH_REQUIRED")
    _require(shared["accepted_sessions"] == design["accepted_sessions"],
             "SOURCE_SESSION_CALENDAR_BINDING_CHANGED")
    return binding, proof["sha256"]

def _budget_source_correction(design, dag, pins, paths, run, *, dependency=None):
    """Bind reviewed zero-fit repairs of this entry or its pure UID qualifier.

    Estimator, feature, training, account and registry sources retain exact pins.
    The optional qualifier repair has its own snapshot, design pin and review.
    """
    entry = Path(__file__).resolve()
    current = entry if dependency is None else Path(dependency).resolve()
    _require(current in (entry, Path(preflight.__file__).resolve()),
             "R3_UNAPPROVED_SOURCE_CORRECTION_DEPENDENCY")
    actual = prior.sha(current)
    descriptor = (design.get("budget_source_correction", {}) if current == entry else
        design.get("budget_dependency_corrections", {}).get(str(current), {}))
    correction = _metadata_pin(descriptor, paths, "BUDGET_SOURCE_CORRECTION_METADATA")
    original, corrected = correction["original_source"], correction["corrected_source"]
    sources = {Path(p).resolve(): h for p, h in design.get("sources", {}).items()}
    research_id = design.get("research_id")
    _require(correction.get("schema") == "C_R3_BUDGET_SOURCE_CORRECTION_METADATA_V1"
        and correction.get("classification") == "ENGINEERING_ONLY"
        and Path(original["path"]).resolve() == current == Path(corrected["path"]).resolve()
        and original["sha256"] == pins[current]
        and corrected["sha256"] == actual == sources.get(current)
        and correction.get("physical_dag_sha256") == design["physical_dag"]["sha256"]
        and isinstance(research_id, str) and bool(research_id.strip())
        and research_id == dag.get("research_id") == correction.get("research_id")
        and correction.get("budget_and_scientific_parameters_changed") is False
        and isinstance(correction.get("actual_execution"), dict)
        and all(_integer(correction["actual_execution"].get(key), 0)
                for key in ("fit_calls", "covariance_estimates", "outcome_rows_read")),
        "R3_SOURCE_CORRECTION_SCOPE_CHANGED")
    snapshot = correction["original_snapshot"]
    snapshot_path = Path(snapshot["path"]).resolve()
    _require(snapshot_path.is_relative_to(run) and snapshot_path.is_file()
        and (snapshot_path.is_relative_to(paths.backtest_root)
             or (design.get("synthetic_only") is True and snapshot_path.is_relative_to(paths.cache_root)))
        and snapshot_path.stat().st_size <= 262144
        and snapshot["sha256"] == pins[current] == prior.sha(snapshot_path),
        "R3_ORIGINAL_SOURCE_SNAPSHOT_CHANGED")
    review = _metadata_pin(correction["independent_review"], paths,
                           "ENGINEERING_INDEPENDENT_REVIEW_METADATA")
    _require(review.get("status") == "PASS" and review.get("classification") == "ENGINEERING_ONLY"
        and Path(review.get("source_path", "")).resolve() == current
        and review.get("original_source_sha256") == pins[current]
        and review.get("corrected_source_sha256") == actual
        and review.get("physical_dag_sha256") == design["physical_dag"]["sha256"]
        and review.get("research_id") == research_id, "R3_SOURCE_CORRECTION_REVIEW_REQUIRED")
    return actual


def _same_context(reserved, current):
    _require(reserved.get("authority_mode") == current.get("authority_mode")
        and all(reserved[key] == current[key] for key in
        ("design_sha256", "dag_sha256", "source_proof_sha256", "source_id",
         "accepted_sessions", "slots", "caps")), "R3_RESERVED_CONTEXT_CHANGED")

def checked(run):
    """Read only pinned contract/source metadata; reject before input callables."""
    run = Path(run).resolve()
    paths = storage_paths.resolve(prior.REPO)
    _require(run.is_relative_to(paths.backtest_root) or run.is_relative_to(paths.cache_root),
             "R3_RUN_OUTPUT_ROOT_REQUIRED")
    _require((run / "DESIGN_FREEZE.json").is_file()
             and (run / "DESIGN_FREEZE_SHA.json").is_file(), "DESIGN_FREEZE_MISSING")
    design_sha = prior.sha(run / "DESIGN_FREEZE.json")
    _require(design_sha == prior.readj(run / "DESIGN_FREEZE_SHA.json")["sha256"]
             == prior.readj(run / "run_config.json")["design_freeze_sha256"],
             "DESIGN_FREEZE_SHA_MISMATCH")
    design = prior.readj(run / "DESIGN_FREEZE.json")
    gates = FH_GATES if design.get("source_contract_mode") == FH_MODE else GATES
    if design.get("source_contract_mode") == FH_MODE:
        _require(design.get("mechanism_research_eligible") is True
            and design.get("strict_PIT_promotion_eligible") is False
            and design.get("test2026_locked") is True, "FROZEN_HISTORY_ELIGIBILITY_CHANGED")
    _require(design.get("official_freeze") is True
             and all(design.get("execution_gates", {}).get(g) is True for g in gates),
             "DESIGN_OR_EXECUTION_GATE_BLOCKED")
    if run.is_relative_to(paths.cache_root):
        _require(design.get("synthetic_only") is True, "CACHE_RUN_MUST_BE_SYNTHETIC_ONLY")
    dag = _metadata_pin(design["physical_dag"], paths, "PHYSICAL_DAG_BUDGET_FREEZE")
    slots = expanded_slots(dag)
    if design.get("source_contract_mode") == FH_MODE:
        _require(dag.get("research_id") == design.get("research_id"), "FROZEN_HISTORY_DAG_IDENTITY_CHANGED")
    _require(dag.get("budget_frozen") is True, "DAG_BUDGET_UNFROZEN")
    # Historical DAG source/official-freeze fields are snapshots, not source authority.
    # The current DESIGN gates and exact C acceptance receipt own source qualification.
    pins = {Path(p["path"]).resolve(): p["sha256"] for p in dag["source_pins"]}
    _require(len(pins) == len(dag["source_pins"])
             and all(p.resolve() in pins for p in REQUIRED_SOURCES), "REQUIRED_SOURCE_PIN_MISSING")
    for path, expected in pins.items():
        if path in (Path(__file__).resolve(), Path(preflight.__file__).resolve()) and prior.sha(path) != expected:
            expected = _budget_source_correction(design, dag, pins, paths, run, dependency=path)
        _require(path.is_relative_to(paths.repo_root) and path.suffix == ".py"
                 and path.is_file() and prior.sha(path) == expected, "CURRENT_SOURCE_PIN_CHANGED")
    source_binding, proof_sha = _source_binding(design, paths)
    monthly = preflight.monthly_cutoffs(design["accepted_sessions"])
    _require(len(monthly) == 48, "FROZEN_CALENDAR_MUST_HAVE_ALL48_MONTHS")
    for slot in slots:
        if slot["kind"] == "RISK":
            slot["cutoff"] = (next(d.isoformat() for d in monthly if
                d.strftime("%Y-%m") == slot["cutoff_ref"].split(":", 1)[1])
                if slot["cadence"] == "MONTHLY" else slot["cutoff_ref"])
    return dict(run=run, design_sha256=design_sha, dag_sha256=design["physical_dag"]["sha256"],
                source_proof_sha256=proof_sha, source_id=source_binding["source_id"],
                accepted_sessions=design["accepted_sessions"], caps=dag["proposed_caps"], slots=slots,
                authority_mode=design.get("source_contract_mode", "STRICT_SOURCE_RECEIPT"))


@contextmanager
def _one_worker(run):
    lock = Path(run) / "FIT_LEDGER.lock"
    try:
        stream = lock.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise ExecutionBlocked("R3_SINGLE_WORKER_LOCK_PRESENT") from exc
    try:
        with stream:
            stream.write(str(os.getpid()))
            stream.flush()
            os.fsync(stream.fileno())
        yield
    finally:
        lock.unlink()


def _ledger(context):
    path = context["run"] / "FIT_LEDGER.json"
    identity = {k: context[k] for k in ("design_sha256", "dag_sha256", "source_proof_sha256")}
    ledger = prior.readj(path) if path.exists() else dict(r3_physical_kernel=1,
        **identity, reserved={}, events=[])
    _require(ledger.get("r3_physical_kernel") == 1
             and all(ledger.get(k) == v for k, v in identity.items()), "R3_LEDGER_IDENTITY_CHANGED")
    totals = {}
    slot_map = {s["slot_id"]: s for s in context["slots"]}
    ids = set()
    for event in ledger["events"]:
        _require(event["id"] in slot_map and event["id"] not in ids
                 and event["reservation"] == slot_map[event["id"]]["reservation"]
                 and event["status"] in ("RESERVED", "SUCCEEDED", "FAILED", "TIMED_OUT"),
                 "R3_LEDGER_SLOT_CHANGED")
        ids.add(event["id"])
        for key, value in event["reservation"].items():
            totals[key] = totals.get(key, 0) + value
    _require(ledger["reserved"] == totals, "R3_LEDGER_RESERVATION_CHANGED")
    return path, ledger


def _persist(path, ledger):
    storage_paths.assert_safe_output_path(path)
    prior.putj(path, ledger)
    # Atomic canonical writer plus an fsync acknowledgment precedes the operation.
    with path.open("r+b") as stream:
        stream.flush()
        os.fsync(stream.fileno())


def _reserve(context, slot_id):
    slot = next((s for s in context["slots"] if s["slot_id"] == slot_id), None)
    _require(slot is not None, "R3_UNREGISTERED_SLOT")
    path, ledger = _ledger(context)
    _require(all(e["id"] != slot_id for e in ledger["events"]),
             "R3_SLOT_ALREADY_CONSUMED_NO_RETRY")
    for key, value in slot["reservation"].items():
        total = ledger["reserved"].get(key, 0) + value
        _require(total <= context["caps"][key], "R3_PHYSICAL_CAP_EXCEEDED")
        ledger["reserved"][key] = total
    ledger["events"].append(dict(id=slot_id, status="RESERVED", attempt=1,
        started_at=prior.now(), reservation=slot["reservation"], actual_operations="UNKNOWN"))
    _persist(path, ledger)
    return slot


def reserve(run, slot_id):
    """Reserve once, including a full head/scaler pair; never refund on failure."""
    context = checked(run)
    with _one_worker(context["run"]):
        return _reserve(context, slot_id)


def _finish(context, slot_id, status):
    _require(status in ("SUCCEEDED", "FAILED", "TIMED_OUT"), "R3_FINISH_STATUS_REQUIRED")
    path, ledger = _ledger(context)
    event = next((e for e in ledger["events"] if e["id"] == slot_id), None)
    _require(event is not None and event["status"] == "RESERVED", "R3_SLOT_NOT_UNFINISHED")
    event.update(status=status, finished_at=prior.now())
    _persist(path, ledger)


def finish(run, slot_id, status):
    context = checked(run)
    with _one_worker(context["run"]):
        _finish(context, slot_id, status)


def execute(run, slot_id, operation):
    """No supplied input/model callable runs before all gates and durable reserve."""
    context = checked(run)
    _require(callable(operation), "R3_OPERATION_CALLABLE_REQUIRED")
    with _one_worker(context["run"]):
        slot = _reserve(context, slot_id)
        try:
            _same_context(context, checked(run))
            operation_slot = copy.deepcopy(slot)
            result = operation(operation_slot)
            _require(operation_slot == slot, "R3_OPERATION_CHANGED_RESERVED_SLOT")
        except BaseException as exc:
            _finish(context, slot_id, "TIMED_OUT" if isinstance(exc, TimeoutError) else "FAILED")
            raise
        _finish(context, slot_id, "SUCCEEDED")
        return result


def fit_risk_slot(run, slot_id, input_reader, *, persist_result=None):
    """Thin qualified-input callback adapter, not a raw-data or source pipeline.

    Reader supplies history, accepted_sessions, cutoff-known universe, explicit
    decision_at and the actual source_authority predicate. No clock is guessed.
    """
    def operation(slot):
        _require(slot["kind"] == "RISK", "R3_RISK_SLOT_REQUIRED")
        before_reader = checked(run)
        _, reserved_ledger = _ledger(before_reader)
        _require(any(event["id"] == slot_id and event["status"] == "RESERVED"
                     for event in reserved_ledger["events"]), "R3_READER_SLOT_NOT_RESERVED")
        method, cutoff, cadence = slot["method"], slot["cutoff"], slot["cadence"]
        reader_slot = copy.deepcopy(slot)
        supplied = input_reader(reader_slot)
        _require(reader_slot == slot, "R3_INPUT_READER_CHANGED_SLOT")
        context = checked(run)
        _same_context(before_reader, context)
        _require(supplied["accepted_sessions"] == context["accepted_sessions"]
            and supplied["source_id"] == context["source_id"]
            and supplied["source_proof_sha256"] == context["source_proof_sha256"],
            "R3_READER_SCOPE_OR_PROOF_CHANGED")
        if context.get("authority_mode") == FH_MODE:
            _require(supplied.get("mechanism_research_eligible") is True
                and supplied.get("strict_PIT_promotion_eligible") is False,
                "FROZEN_HISTORY_READER_ELIGIBILITY_CHANGED")
        _require(callable(supplied["source_authority"])
            and supplied["source_authority"](supplied["universe"], cutoff=cutoff,
                decision_at=supplied["decision_at"], proof_kind="CUTOFF_KNOWN_UNIVERSE",
                source_proof_sha256=context["source_proof_sha256"]) is True,
            "R3_CUTOFF_KNOWN_UNIVERSE_PROOF_REQUIRED")
        panel, coverage, metadata = preflight.canonical_uid_return_panel(
            supplied["history"], supplied["accepted_sessions"], cutoff,
            supplied["universe"], cadence=cadence,
            decision_at=supplied["decision_at"], source_authority=supplied["source_authority"])
        _require(metadata["status"] == "UID_PANEL_QUALIFIED", "R3_PANEL_QUALIFICATION_BLOCKED")
        params = dict(fit_cutoff=cutoff, return_unit=features.UNIT,
            return_horizon_sessions=1, source_id=supplied["source_id"],
            information_set_id=metadata["qualification_sha256"])
        bundle = old.bounded_risk_fit(method, panel, None, params, timeout=1800)
        _require(bundle.status == "FITTED" and bundle.method_id == method,
                 "R3_RISK_FIT_NOT_QUALIFIED")
        if persist_result is not None:
            _require(callable(persist_result), "RISK_PERSISTENCE_CALLBACK_REQUIRED")
            persist_result(slot, bundle, coverage, metadata, supplied["universe"])
        return bundle, coverage, metadata
    return execute(run, slot_id, operation)


def project_full_pool(bundle, full_uids):
    """Use the established projection owner once for the complete daily U_t."""
    return features.project(bundle, full_uids)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "check", "reserve-only"))
    parser.add_argument("--dag", type=Path)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--slot")
    args = parser.parse_args()
    if args.action == "plan":
        if args.dag is None:
            parser.error("plan requires --dag containing source-only metadata")
        slots = expanded_slots(prior.readj(args.dag))
        prior.emit(status="PLAN_ONLY", slots=len(slots), fit_calls=0)
    else:
        if args.run is None:
            parser.error("check/reserve-only require --run")
        if args.action == "reserve-only":
            if not args.slot:
                parser.error("reserve-only requires --slot")
            reserve(args.run, args.slot)
        else:
            checked(args.run)
        prior.emit(status="RESERVED_ONLY" if args.action == "reserve-only" else "GATES_READY",
                   fit_calls=0)


if __name__ == "__main__":
    main()




