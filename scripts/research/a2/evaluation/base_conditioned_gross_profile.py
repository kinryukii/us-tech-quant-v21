"""Process-private authority route for the two bases and six gross descendants.

Only task/scope admission is new. Original date/account/policy/friction and
reconstructed-event functions retain their code; no shared source is modified.
Call runtime.bootstrap, then install_routes, before loading account authority.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import types

from scripts.research.a2.evaluation import base_conditioned_gross_runtime as runtime

TASK = runtime.TASK
ROOT = runtime.RESULTS
SCHEMA = "BASE_CONDITIONED_GROSS_ACCOUNT_AUTHORITY_REF_R1"
RELEASE_SCHEMA = "BASE_CONDITIONED_GROSS_ACCOUNT_RELEASE_R1"
QUALIFICATION_SCHEMA = "BASE_CONDITIONED_GROSS_SOURCE_QUALIFICATION_R1"
BASES = ("R10_DIRECT_MEAN4_ELASTICNET_MID", "R10_DIRECT_H5_RIDGE_MID")
CONTRACT_REF = dict(path=str(ROOT / "RESEARCH_CONTRACT.json"), sha256="2329b8edb6e03ca387c57d83eb28fff41d0cd9ed7cd1aafe978af1eb38eb23ff")
INPUT_MANIFEST_REF = dict(path=str(ROOT / "SIX_COMBINATION_INPUT_MANIFEST.json"), sha256="47832a9280c354890a73ebdc8a21cee6214502374de549c1a2bceca2ef40169b")
RUNTIME_BINDING_REF = dict(path=str(ROOT / "RUNTIME_SOURCE_BINDING_R1.json"), sha256="70a5a752563cfe183b678597742f5408c8b48220dbe2adec982167a0073bc716")
SCOPE_REF = dict(path=str(ROOT / "RUNTIME_SCOPE.json"), sha256="d79bdcc3136aff2e5ab5c269d4b34c916ed962581f85107c96aacb1589e6e030")
SCHEDULE_REF = dict(path="D:/us-tech-quant-results/_maintenance/A_ALL_AND_DEMO_RANDOM_TEST2026_20261009_R1/RANDOM_WINDOWS.json", sha256="903e6b72d8c1c55f7214b1761f8a6ee607faca5caa5e9d67210d94eb5ba60f3a")
RELEASE_NAMES = {"HISTORY2024": "HISTORY_ACCOUNT_RELEASE.json", "FROZEN2026": "EVALUATION_ACCOUNT_RELEASE.json"}
UNKNOWN_CLOCK = "FROZEN_HISTORY_RESEARCH_OBSERVATIONS_NOT_HISTORICAL_DELIVERY_CERTIFICATION"
POST_CLOCK = "POST_VERIFIED_ACCOUNTING_ONLY"
NO_AUTHORITY_FLAGS = ("strategy_selection", "production_qualified", "broker_action_allowed",
                      "strict_PIT_promotion_eligible", "formal_primary_metrics_allowed")
_SEAL = object()
_STATE = None


def _need(condition, code):
    if not condition:
        raise ValueError("BASE_GROSS_PROFILE_" + code)


def _document(ref):
    # Only the already scoped task catalogue needs the existing 2MB typed payload budget.
    limit = 2_000_000 if (_STATE is not None and _STATE.get("phase") == "FROZEN2026"
                         and _STATE.get("large_catalog_ref") == ref) else 200_000
    _, raw = runtime._physical(ref, limit=limit)
    value = json.loads(raw)
    _need(isinstance(value, dict), "METADATA_OBJECT_REQUIRED")
    return value


def _reference(path):
    path = Path(path)
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def _clone(fn, **overrides):
    scope = dict(fn.__globals__)
    scope.update(overrides)
    result = types.FunctionType(fn.__code__, scope, fn.__name__, fn.__defaults__, fn.__closure__)
    result.__kwdefaults__ = fn.__kwdefaults__
    return result


def _new(value):
    if isinstance(value, dict):
        return value.get("task_id") == TASK or value.get("schema") == SCHEMA
    return getattr(value, "task_id", None) == TASK


def _core(value):
    provenance = json.loads(value.provenance_json)
    provenance.pop("runtime_policy_ids", None)
    return (value.task_id, value.window_id, value.start, value.end, value.as_of,
            value.feature_history_start, value.allowed_path_ids,
            json.dumps(provenance, sort_keys=True), value.capability,
            value.research_cash_reconstruction_json, value.research_terminal_reconstruction_json,
            value.source_ready_policy_ids)


def _verified(value):
    if not _new(value):
        return _STATE["originals"]["_verified"](value)
    f = _STATE["f"]
    _need(type(value) is f.ValidatedDescriptiveAuthority and value._seal is _SEAL
          and value.capability == "ACCOUNT", "NEW_TASK_SEALED_AUTHORITY_REQUIRED")
    custody = value._source_policy_custody
    _need(type(custody) is f._SourcePolicyCustody and custody.seal is _SEAL
          and custody.task_id == TASK and custody.policy_ids == value.source_ready_policy_ids,
          "NEW_TASK_CUSTODY_REQUIRED")
    provenance = json.loads(value.provenance_json)
    _need(provenance.get("phase") == _STATE["phase"]
          and provenance.get("runtime_binding_ref") == _STATE["binding_ref"], "CROSS_PHASE_AUTHORITY")
    key = (provenance.get("release_ref", {}).get("sha256"), value.window_id)
    _need(_STATE["admissions"].get(key) == _core(value), "ADMITTED_AUTHORITY_CHANGED")
    _need(value.runtime_policy_ids == tuple(i for i in value.allowed_path_ids if i in value.runtime_policy_ids),
          "RUNTIME_POLICY_ORDER_CHANGED")
    return value


def _candidate_ids(phase, manifest):
    expected = tuple(base + "__GROSS_" + learner for base in BASES for learner in ("LINEAR", "TREE", "NEURAL"))
    _need(tuple(manifest.get("candidate_ids", ())) == expected, "SIX_FROZEN_CANDIDATES_REQUIRED")
    return BASES if phase == "HISTORY2024" else expected + tuple(base + "__GROSS_FIXED_050" for base in BASES)


def _post_header(binding, key, bound):
    if binding is None:
        return
    _need(isinstance(binding, dict) and binding.get("task_id") == TASK
          and binding.get("authorization_ref") == bound.get("post_verified_accounting_decision_ref")
          and binding.get("clock_role") == POST_CLOCK
          and binding.get("strict_PIT_promotion_eligible") is False
          and binding.get("production_qualified") is False, "POST_VERIFIED_NEW_TASK_BINDING_REQUIRED")
    decision = _document(binding["authorization_ref"])
    _need(decision.get("task_id") == TASK and decision.get("phase") == _STATE["phase"]
          and decision.get("status") == "ROOT_POST_VERIFIED_ACCOUNTING_ONLY_BOUND"
          and decision.get("contract_ref") == CONTRACT_REF and decision.get("clock_role") == POST_CLOCK
          and all(decision.get(k) is False for k in NO_AUTHORITY_FLAGS)
          and decision.get("model_or_label_input_authority") is False,
          "POST_VERIFIED_ACCOUNTING_ONLY_REQUIRED")
    _need(decision.get("authorized_bindings", {}).get(key)
          == {name: value for name, value in binding.items() if name != "authorization_ref"},
          "POST_VERIFIED_EXACT_EVENTS_REQUIRED")


def _source_gate(bound, ids, start, end, history, as_of):
    f = _STATE["f"]
    pd = f.pd
    sources = bound.get("source_refs")
    _need(isinstance(sources, dict) and set(sources) == set(f.SOURCE_GROUPS), "FIVE_SOURCE_GROUPS_REQUIRED")
    qualification = _document(bound.get("source_qualification_ref"))
    _need(qualification.get("schema") == QUALIFICATION_SCHEMA
          and qualification.get("task_id") == TASK and qualification.get("phase") == _STATE["phase"]
          and qualification.get("status") == "QUALIFIED_FOR_DECLARED_RESEARCH_SCOPE"
          and qualification.get("contract_ref") == CONTRACT_REF
          and qualification.get("source_refs") == sources and qualification.get("as_of") == bound["as_of"]
          and qualification.get("formal_primary_metrics_allowed") is False,
          "SOURCE_QUALIFICATION_UNBOUND")
    exclusion_ref = bound.get("source_exclusion_ref")
    _need(qualification.get("source_exclusion_ref") == exclusion_ref,
          "SOURCE_EXCLUSION_NOT_ACCOUNT_BOUND")
    if exclusion_ref is not None:
        _need(_STATE["phase"] == "HISTORY2024", "SOURCE_EXCLUSION_HISTORY_ONLY")
        exclusion = _document(exclusion_ref)
        _need(exclusion.get("schema") == "BASE_CONDITIONED_GROSS_USER_SOURCE_EXCLUSION_R1"
              and exclusion.get("status") == "USER_AUTHORIZED_TEMPORARY_MISSING_SOURCE_EXCLUSION"
              and exclusion.get("task_id") == TASK and exclusion.get("scope") == "HISTORY2024"
              and exclusion.get("contract_ref") == CONTRACT_REF
              and exclusion.get("cutoff_exclusive") == "2024-10-07"
              and exclusion.get("nominal_top_n") == 100 and exclusion.get("backfill") is False
              and exclusion.get("row_count") == 709,
              "EXACT_USER_SOURCE_EXCLUSION_REQUIRED")
        runtime._physical(exclusion["dated_identity_ref"])
        runtime._physical(exclusion["exclusion_rows_ref"])
    groups, slices = qualification.get("groups"), qualification.get("source_slices")
    _need(isinstance(groups, dict) and set(groups) == set(f.SOURCE_GROUPS)
          and all(groups[k] is True for k in f.SOURCE_GROUPS)
          and isinstance(slices, dict) and set(slices) == set(f.SOURCE_GROUPS), "FIVE_SOURCE_GATES_NOT_TRUE")
    _need(qualification.get("common_calendar_start") == str(start.date())
          and qualification.get("common_calendar_end") == str(end.date())
          and qualification.get("common_calendar_selection") == "SOURCE_AVAILABILITY_AND_ORIGINAL_CALENDAR_ONLY",
          "SOURCE_CALENDAR_CHANGED")
    _need(qualification.get("candidate_ids") == list(ids)
          and qualification.get("raw_selector_binding") == bound.get("raw_selector_binding")
          and isinstance(bound.get("raw_selector_binding"), dict)
          and bool(bound["raw_selector_binding"]), "RAW_OR_CANDIDATE_BINDING_REQUIRED")
    for key in f.SOURCE_GROUPS:
        scope = slices[key]
        _need(isinstance(scope, dict) and scope.get("source_ref") == sources[key]
              and scope.get("view_only") is True and scope.get("no_2027_content") is True
              and scope.get("read_filter_applied_before_economic_decode") is True,
              "BOUNDED_SOURCE_SCOPE_REQUIRED")
        first, last = f._day(scope.get("content_start")), f._day(scope.get("content_end"))
        _need(history <= first <= last <= end, "SOURCE_SCOPE_OUTSIDE_PHASE")
        role = scope.get("clock_role")
        if role == POST_CLOCK:
            _need(key == "corporate_actions" and bound.get("post_verified_accounting_decision_ref") is not None
                  and scope.get("available_at") is None and scope.get("historical_available_at_bound") is False,
                  "POST_VERIFIED_NOT_SIGNAL_AUTHORITY")
            captured = pd.Timestamp(scope.get("captured_at"))
            _need(not pd.isna(captured) and captured.tzinfo is not None, "POST_VERIFIED_CAPTURE_REQUIRED")
        elif role == UNKNOWN_CLOCK:
            _need(key != "corporate_actions" and scope.get("available_at") is None
                  and scope.get("historical_available_at_bound") is False
                  and bool(scope.get("source_observation_fact_refs")), "UNKNOWN_CLOCK_NOT_PIT")
            for ref in scope["source_observation_fact_refs"]:
                runtime._physical(ref)
        else:
            _need(role == "HISTORICAL_AVAILABLE_AT_BOUND"
                  and scope.get("historical_available_at_bound") is True, "EXACT_CLOCK_ROLE_REQUIRED")
            available = pd.Timestamp(scope.get("available_at"))
            _need(not pd.isna(available) and available.tzinfo is not None and available <= as_of,
                  "SOURCE_NOT_AVAILABLE")
    # All bounded scope and clock declarations precede hashing the source files.
    for ref in sources.values():
        f._physical(ref)
    catalog = Path(sources["corporate_actions"]["path"]).resolve()
    own_catalog = (catalog.name == "ACCOUNT_CATALOG.json"
                   and catalog.parent.name == "gross_evaluation_sources"
                   and catalog.parent.parent.name == "derived" and catalog.parents[3].name == TASK)
    _STATE["large_catalog_ref"] = dict(sources["corporate_actions"]) if own_catalog else None
    return qualification


def _release(authority):
    f, phase = _STATE["f"], _STATE["phase"]
    pd = f.pd
    _need(isinstance(authority, dict) and set(authority) == {"schema", "task_id", "release_ref", "window_id"}
          and authority["schema"] == SCHEMA and authority["task_id"] == TASK, "EXACT_AUTHORITY_REF_REQUIRED")
    release_ref = authority["release_ref"]
    _need(isinstance(release_ref, dict)
          and runtime._same_path(release_ref.get("path", ""), ROOT / RELEASE_NAMES[phase]), "EXACT_PHASE_RELEASE_REQUIRED")
    bound = _document(release_ref)
    _need(bound.get("schema") == RELEASE_SCHEMA and bound.get("task_id") == TASK
          and bound.get("phase") == phase and bound.get("status") == "ROOT_SOURCE_AND_POLICY_BOUND",
          "ROOT_SEALED_RELEASE_REQUIRED")
    _need(bound.get("contract_ref") == CONTRACT_REF and bound.get("input_manifest_ref") == INPUT_MANIFEST_REF
          and bound.get("runtime_binding_ref") == _STATE["binding_ref"] and bound.get("scope_ref") == SCOPE_REF,
          "FROZEN_CONTRACT_CHANGED")
    _need(type(bound.get("new_fit")) is int and bound["new_fit"] == 0
          and all(bound.get(k) is False for k in NO_AUTHORITY_FLAGS), "ACCOUNT_ONLY_NO_FIT_OR_SELECTION")
    _need(bound.get("initial_cash_usd") == 3000 and bound.get("initial_holdings") == []
          and bound.get("initial_receivables") == [] and bound.get("fresh_account") is True,
          "FRESH_USD3000_REQUIRED")
    _document(CONTRACT_REF)
    manifest = _document(INPUT_MANIFEST_REF)
    ids = _candidate_ids(phase, manifest)
    _need(bound.get("allowed_path_ids") == list(ids), "EXACT_CANDIDATES_REQUIRED")
    as_of = pd.Timestamp(bound.get("as_of"))
    _need(not pd.isna(as_of) and as_of.tzinfo is not None, "AS_OF_REQUIRED")
    windows = bound.get("windows")
    _need(isinstance(windows, list) and bool(windows) and all(isinstance(w, dict) for w in windows), "WINDOWS_REQUIRED")
    if phase == "HISTORY2024":
        _need(len(windows) == 1 and windows[0].get("window_id") == "HISTORY2024"
              and windows[0].get("start") == "2024-01-02"
              and f._day(windows[0].get("end")) < pd.Timestamp("2024-10-07")
              and bound.get("signal_and_label_maturity_cutoff_exclusive") == "2024-10-07",
              "HISTORICAL_EARLIER_CUTOFF_REQUIRED")
    else:
        _need(bound.get("schedule_ref") == SCHEDULE_REF, "ORIGINAL_SCHEDULE_REQUIRED")
        schedule = _document(SCHEDULE_REF)
        _need(windows == schedule.get("windows") and len(windows) == 101
              and windows[0].get("start") == "2026-01-02"
              and all(w.get("end") == "2026-10-08" for w in windows), "EXACT_MAIN_PLUS100_REQUIRED")
    _need(len({w.get("window_id") for w in windows}) == len(windows), "UNIQUE_WINDOWS_REQUIRED")
    matches = [w for w in windows if w.get("window_id") == authority["window_id"]]
    _need(len(matches) == 1, "WINDOW_NOT_REGISTERED")
    common_start, end = f._day(windows[0].get("start")), f._day(windows[0].get("end"))
    start = f._day(matches[0].get("start"))
    _need(common_start <= start < end
          and (end + pd.Timedelta(hours=16)).tz_localize("America/New_York") <= as_of, "INCOMPLETE_WINDOW")
    if phase == "FROZEN2026":
        _need(pd.Timestamp("2026-01-01") <= start < end < pd.Timestamp("2027-01-01"), "TEST_YEAR_REQUIRED")
    history = f._day(bound.get("feature_history_start"))
    _need(history == pd.Timestamp("2023-01-03"), "ORIGINAL_PROXY_PREFIX_REQUIRED")
    qualification = _source_gate(bound, ids, common_start, end, history, as_of)
    policies = _document(bound.get("candidate_manifest_ref"))
    bindings = policies.get("candidate_bindings")
    _need(policies.get("task_id") == TASK and policies.get("phase") == phase
          and policies.get("status") == "FROZEN" and isinstance(bindings, list)
          and tuple(row.get("candidate_id") for row in bindings) == ids
          and bound.get("candidate_bindings") == bindings, "FULL_POLICY_MANIFEST_REQUIRED")
    for row in bindings:
        spec = row.get("specification")
        _need(isinstance(spec, dict) and spec.get("candidate_id") == row["candidate_id"]
              and isinstance(spec.get("execution_friction"), dict)
              and spec["execution_friction"].get("one_way_bps") == 10, "FULL_POLICY_FRICTION_REQUIRED")
    states = _document(bound.get("state_manifest_ref"))
    refs = states.get("state_refs")
    _need(states.get("task_id") == TASK and states.get("phase") == phase
          and states.get("status") == "FROZEN" and isinstance(refs, dict) and bool(refs)
          and bound.get("state_refs") == refs, "FROZEN_STATE_MANIFEST_REQUIRED")
    for state in refs.values():
        role = state.get("role")
        _need(role in ("base", "raw", "gross", "scaler"), "STATE_ROLE_REQUIRED")
        maximum = ("2024-01-01" if phase == "HISTORY2024" else
                   "2024-10-07" if role == "gross" else
                   "2026-01-01" if phase == "FROZEN2026" and role == "raw" else "2025-01-01")
        _need(f._day(state.get("signal_cutoff_exclusive")) <= pd.Timestamp(maximum)
              and f._day(state.get("label_maturity_cutoff_exclusive")) <= pd.Timestamp(maximum), "STATE_EARLIER_CUTOFF_REQUIRED")
        f._physical(state.get("model_ref"))  # hash only; never deserialize
        _document(state.get("receipt_ref"))
    used = set()
    for row in bindings:
        keys = row.get("state_ids")
        _need(isinstance(keys, list) and bool(keys) and len(set(keys)) == len(keys)
              and all(key in refs for key in keys), "FULL_CANDIDATE_STATE_CLOSURE_REQUIRED")
        used.update(keys)
        cid = row["candidate_id"]
        base_id = cid.split("__GROSS_", 1)[0]
        base_states = [refs[key] for key in keys if refs[key]["role"] == "base"]
        gross_states = [refs[key] for key in keys if refs[key]["role"] == "gross"]
        _need({state.get("group") for state in base_states} == {"ENTRY", "INCUMBENT"}
              and all(state.get("base_id") == base_id for state in base_states)
              and any(refs[key]["role"] == "raw" for key in keys), "BASE_HEAD_CLOSURE_REQUIRED")
        learned = "__GROSS_" in cid and not cid.endswith("__GROSS_FIXED_050")
        _need((len(gross_states) == 1 and gross_states[0].get("candidate_id") == cid) if learned
              else not gross_states, "GROSS_STATE_CLOSURE_REQUIRED")
    _need(used == set(refs), "UNCONSUMED_STATE_NOT_ALLOWED")
    expected_owners = {"profile": _reference(__file__), "runtime": _reference(runtime.__file__),
                       "authority": _reference(f.__file__), "policy": _reference(_STATE["p"].__file__)}
    owners = bound.get("owner_refs")
    _need(isinstance(owners, dict) and all(owners.get(k) == v for k, v in expected_owners.items()), "EXACT_ROUTE_OWNERS_REQUIRED")
    for ref in owners.values():
        runtime._physical(ref)
    runtime._physical(bound.get("driver_ref"))
    _need(isinstance(bound.get("proof_refs"), dict) and bool(bound["proof_refs"]), "INDEPENDENT_PROOFS_REQUIRED")
    for ref in bound["proof_refs"].values():
        _document(ref)
    for key in ("research_cash_reconstruction", "research_terminal_reconstruction"):
        _post_header(bound.get(key), key, bound)
    cash = _STATE["load_post"](bound, bound["source_refs"], TASK, "research_cash_reconstruction")
    terminal = _STATE["load_post"](bound, bound["source_refs"], TASK, "research_terminal_reconstruction")
    return bound, ids, start, end, as_of, history, qualification, cash, terminal


def load_authority(authority):
    _need(_STATE is not None, "INSTALL_ROUTES_FIRST")
    if type(authority) is _STATE["f"].ValidatedDescriptiveAuthority:
        return _verified(authority)
    bound, ids, start, end, as_of, history, qualification, cash, terminal = _release(authority)
    f = _STATE["f"]
    provenance = dict(schema=SCHEMA, task_id=TASK, phase=_STATE["phase"], release_ref=authority["release_ref"],
        runtime_binding_ref=_STATE["binding_ref"], candidate_bindings=bound["candidate_bindings"],
        state_refs=bound["state_refs"], source_refs=bound["source_refs"],
        source_qualification_ref=bound["source_qualification_ref"], candidate_manifest_ref=bound["candidate_manifest_ref"],
        source_ready_policy_ids=list(ids), runtime_policy_ids=[], formal_primary_metrics_allowed=False,
        historical_delivery_certification="RETAIN_ORIGINAL_UNKNOWN",
        source_clock_roles={k: v["clock_role"] for k, v in qualification["source_slices"].items()})
    value = f.ValidatedDescriptiveAuthority(TASK, authority["window_id"], start, end, as_of, history, ids,
        json.dumps(provenance, sort_keys=True, allow_nan=False), _SEAL,
        research_cash_reconstruction_json=cash, research_terminal_reconstruction_json=terminal,
        source_ready_policy_ids=ids, _source_policy_custody=f._SourcePolicyCustody(TASK, ids, _SEAL))
    _STATE["admissions"][(authority["release_ref"]["sha256"], value.window_id)] = _core(value)
    return _verified(value)


def install_routes(runtime_binding_ref, phase):
    """Install only new-task wrappers in this interpreter; leave old calls intact."""
    global _STATE
    _need(runtime_binding_ref == RUNTIME_BINDING_REF and phase in RELEASE_NAMES, "EXACT_RUNTIME_BINDING_REQUIRED")
    runtime.assert_runtime(runtime_binding_ref, phase=phase)
    context = runtime.source_execution_context(runtime_binding_ref, phase=phase)
    _need(context["binding"]["scope_ref"] == SCOPE_REF, "EXACT_NEW_TASK_SCOPE_REQUIRED")
    if _STATE is not None:
        _need(_STATE["binding_ref"] == runtime_binding_ref and _STATE["phase"] == phase, "ONE_PHASE_PER_PROCESS")
        _need(all(getattr(_STATE["f"], name) is fn for name, fn in _STATE["routes"].items()), "INSTALLED_ROUTE_CHANGED")
        return {"task_id": TASK, "phase": phase, "process_private_routes": True}
    from scripts.research.a2.evaluation import frozen_test_authority as f, frozen_a94_profile as p
    names = ("_verified", "load_descriptive_authority", "require_descriptive_decision",
             "validate_descriptive_input_dates", "validate_descriptive_account", "validate_descriptive_policy",
             "validate_reconstructed_accounting_events")
    originals = {name: getattr(f, name) for name in names}
    _STATE = dict(f=f, p=p, phase=phase, binding_ref=dict(runtime_binding_ref), originals=originals, admissions={})
    # Only task routing/validators differ. Reconstructed-event economic code is unchanged.
    post_globals = dict(TASK=TASK, six_path_tasks=lambda: (TASK,), a_profile_tasks=lambda: (),
                        _verified=_verified, _document=_document)
    _STATE["load_post"] = _clone(f._load_post_verified_binding, **post_globals)
    new_event = _clone(originals["validate_reconstructed_accounting_events"], **post_globals)
    new_dates = _clone(originals["validate_descriptive_input_dates"], _verified=_verified)
    new_decision = _clone(originals["require_descriptive_decision"], _verified=_verified, a_profile_tasks=lambda: (TASK,))
    new_account = _clone(originals["validate_descriptive_account"], load_descriptive_authority=load_authority,
                         validate_descriptive_input_dates=new_dates, a_profile_tasks=lambda: (TASK,))
    def dispatch(name, fn):
        original = originals[name]
        def route(value, *args, **kwargs):
            return fn(value, *args, **kwargs) if _new(value) else original(value, *args, **kwargs)
        return route
    new_policy = lambda value, candidates: p.validate_policy(load_authority(value), candidates)
    routes = {"_verified": _verified,
              "load_descriptive_authority": dispatch("load_descriptive_authority", load_authority),
              "require_descriptive_decision": dispatch("require_descriptive_decision", new_decision),
              "validate_descriptive_input_dates": dispatch("validate_descriptive_input_dates", new_dates),
              "validate_descriptive_account": dispatch("validate_descriptive_account", new_account),
              "validate_descriptive_policy": dispatch("validate_descriptive_policy", new_policy),
              "validate_reconstructed_accounting_events": dispatch("validate_reconstructed_accounting_events", new_event)}
    _STATE["routes"] = routes
    for name, fn in routes.items():
        setattr(f, name, fn)
    return {"task_id": TASK, "phase": phase, "process_private_routes": True}