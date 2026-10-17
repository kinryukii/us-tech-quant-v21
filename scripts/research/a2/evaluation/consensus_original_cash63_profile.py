"""Process-private admission for the frozen cash63 new-pool descendants.

No I/O or economic-owner imports on import. The runner installs sealed economic
sources first. This module changes identity/routing only; original policy, date,
account, risk-state and typed reconstructed-event validators retain their math.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import types

TASK = "A_STATEFUL_CASH63_CONSENSUS100_RETRAIN_20261017_R1"
OLD_TASK = "A_ALL_AND_DEMO_RANDOM_TEST2026_20261009_R1"
SCHEMA = "CONSENSUS_ORIGINAL_CASH63_AUTHORITY_REF_R1"
PREFIX = "C100_RETRAIN12__"
SCHEDULE_SHA = "903e6b72d8c1c55f7214b1761f8a6ee607faca5caa5e9d67210d94eb5ba60f3a"
HEADS = frozenset(("extra", "hgb", "hgb_q", "huber", "ngboost", "ridge", "xgb", "xgb_rank",
                   "fusion::equal", "fusion::convex", "fusion::stack_ridge", "fusion::gate_linear"))
_STATE = None
_SEAL = object()


def _need(ok, code):
    if not ok:
        raise ValueError("CASH63_PROFILE_" + code)


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _hash(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _same_ref(left, right):
    return (isinstance(left, dict) and isinstance(right, dict)
            and Path(left.get("path", "")).resolve() == Path(right.get("path", "")).resolve()
            and _hash(left.get("sha256")) and left["sha256"] == right.get("sha256"))


def _physical(reference):
    _need(isinstance(reference, dict) and _hash(reference.get("sha256")), "EXACT_REFERENCE_REQUIRED")
    path = Path(reference.get("path", ""))
    _need(path.is_absolute() and path.resolve(strict=True) == path.absolute(), "ABSOLUTE_PHYSICAL_PATH_REQUIRED")
    with path.open("rb") as stream:
        _need(hashlib.file_digest(stream, "sha256").hexdigest() == reference["sha256"], "SOURCE_SHA_CHANGED")
    return path


def _document(reference, *, kind="metadata"):
    limits = {"metadata": 2_000_000, "source_qualification": 4 * 1024 * 1024}
    _need(kind in limits, "KNOWN_METADATA_KIND_REQUIRED")
    path = _physical(reference)
    _need(path.stat().st_size <= limits[kind], "BOUNDED_METADATA_REQUIRED")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    _need(isinstance(value, dict), "METADATA_OBJECT_REQUIRED")
    return value


def _clone(fn, **overrides):
    scope = dict(fn.__globals__)
    scope.update(overrides)
    result = types.FunctionType(fn.__code__, scope, fn.__name__, fn.__defaults__, fn.__closure__)
    result.__kwdefaults__ = fn.__kwdefaults__
    return result


def candidate_rows(binding, inventory):
    """Pure exact-rule projection; retained source metadata is never rewritten."""
    _need(binding.get("schema") == "CASH12_HEADS_AND_63_RECONSTRUCTION_R1"
          and binding.get("research_id") == TASK and set(binding.get("heads", {})) == HEADS,
          "EXACT_TWELVE_HEAD_BINDING_REQUIRED")
    original = {r["candidate_id"]: r for r in inventory["candidates"]}
    rows = binding.get("configurations")
    _need(isinstance(rows, list) and len(rows) == 63
          and len({r.get("candidate_id") for r in rows}) == 63
          and len({r.get("original_candidate_id") for r in rows}) == 63, "EXACT63_REQUIRED")
    result = []
    for row in rows:
        oid, cid = row["original_candidate_id"], row["candidate_id"]
        _need(oid in original and cid == PREFIX + oid, "HONEST_DESCENDANT_ID_REQUIRED")
        prior = original[oid]
        spec = prior["specification"]
        _need(prior.get("runtime_owner") == "STATEFUL_OVERLAY"
              and prior.get("required_action_roles") == []
              and row.get("original_rule_specification") == spec
              and row.get("original_scientific_tuple_sha256") == prior.get("scientific_tuple_sha256")
              and row.get("original_rules_modified") is False, "ORIGINAL_STATEFUL_RULES_CHANGED")
        head = row.get("learned_head")
        _need(head in HEADS and head == spec.get("value_model")
              and _hash(row.get("scientific_tuple_sha256"))
              and row["scientific_tuple_sha256"] != prior["scientific_tuple_sha256"], "NEW_HEAD_IDENTITY_REQUIRED")
        model = binding["heads"][head]
        # Configuration-to-head references, not merely matching model names.
        _need(_same_ref(row.get("new_model_ref"), model.get("model_ref"))
              and _same_ref(row.get("new_head_receipt_ref"), model.get("receipt_ref")), "HEAD_BYTES_BINDING_CHANGED")
        new_spec = deepcopy(spec)
        new_spec.update(candidate_id=cid, scientific_tuple_sha256=row["scientific_tuple_sha256"])
        risks = [k for k in prior.get("dependency_closure", {}).get("state_ids", ()) if k.startswith("old_risk:")]
        result.append(dict(candidate_id=cid, original_candidate_id=oid,
                           source_group=prior["source_group"], runtime_owner="STATEFUL_OVERLAY",
                           required_action_roles=[], specification=new_spec,
                           scientific_tuple_sha256=row["scientific_tuple_sha256"],
                           dependency_closure=dict(status="COMPLETE", state_ids=["new_value:" + head, *risks])))
    _need({r["specification"]["value_model"] for r in result} == HEADS, "ALL_TWELVE_HEADS_CONSUMED")
    return result


def _prepare(config_ref, f, p):
    cfg = _document(config_ref)
    _need(cfg.get("task_id") == TASK and cfg.get("execution_release") == "ROOT_RELEASED_FROZEN_CASH63_2026"
          and type(cfg.get("new_fit")) is int and cfg["new_fit"] == 0 and cfg.get("tuning") is False,
          "EXPLICIT_ACCOUNT_ONLY_RELEASE_REQUIRED")
    _need(bool(cfg.get("user_scope")) and all(cfg.get(k, False) is False for k in
          ("strict_PIT_certified", "production_qualified", "eligible_for_selection")), "DESCRIPTIVE_ONLY_SCOPE_REQUIRED")
    pins = cfg.get("source_pins")
    _need(isinstance(pins, dict) and bool(pins), "SOURCE_PINS_REQUIRED")
    own = dict(path=str(Path(__file__).resolve()), sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    _need(any(_same_ref(pin, own) for pin in pins.values()), "PROFILE_SOURCE_PIN_REQUIRED")
    for pin in pins.values():
        _physical(pin)
    binding = _document(cfg["head_binding_ref"])
    _need(binding.get("policy_authority_ref", {}).get("sha256") == "e15d9e14a9b8e8078072c048366808c38e899bcc7c422674bf16eb7688a1bcee", "ORIGINAL_POLICY_OWNER_REQUIRED")
    _physical(binding["policy_authority_ref"])
    accepted = _document(cfg["training_acceptance_ref"])
    _need(accepted.get("schema") == "CASH12_FINAL_TRAINING_AND_BINDING_ACCEPTANCE_R1"
          and accepted.get("status") == "COMPLETE"
          and _same_ref(accepted.get("binding_ref"), cfg["head_binding_ref"])
          and accepted.get("training_contract_earlier_cutoffs_preserved") is True,
          "FINAL_TRAINING_ACCEPTANCE_REQUIRED")
    old = _document(cfg["old_account_config_ref"])
    sealed = _document(cfg["sealed_recovery_config_ref"])
    _need(old.get("task_id") == OLD_TASK and _same_ref(sealed.get("original_config_ref"), cfg["old_account_config_ref"])
          and sealed.get("training_allowed") is False and sealed.get("prediction_allowed") is False,
          "EXACT_SEALED_PARENT_REQUIRED")
    _need([r["original_ref"] for r in sealed["sources"]] == old["runtime_source_refs"], "SEALED_OWNER_LIST_CHANGED")
    _need(_same_ref(binding.get("original_inventory_ref"), old["inventory_ref"]), "ORIGINAL_INVENTORY_CHANGED")
    inventory = _document(old["inventory_ref"])
    rows = candidate_rows(binding, inventory)
    _need(cfg.get("candidates") == rows, "FROZEN_FULL63_MANIFEST_REQUIRED")
    schedule = _document(cfg["schedule_ref"])
    _need(_same_ref(cfg["schedule_ref"], old["schedule_ref"])
          and cfg["schedule_ref"]["sha256"] == SCHEDULE_SHA, "ORIGINAL_SCHEDULE_REQUIRED")
    windows = schedule.get("windows", [])
    expected_ids = ["MAIN", *[f"RANDOM_{i:03d}" for i in range(1, 101)]]
    _need([w.get("window_id") for w in windows] == expected_ids
          and all(w.get("end") == "2026-10-08" for w in windows), "EXACT_MAIN_PLUS100_REQUIRED")
    bound = _document(old["admission_ref"])
    original_fields = ("candidate_id", "scientific_tuple_sha256", "specification", "source_group",
                       "runtime_owner", "required_action_roles", "dependency_closure")
    original_bindings = [{**{k: row[k] for k in original_fields}, "lookback": row.get("lookback")}
                         for row in inventory["candidates"]]
    _need(bound.get("task_id") == OLD_TASK
          and bound.get("status") == "SOURCE_AND_POLICY_BOUND_FOR_DESCRIPTIVE_EVALUATION"
          and _same_ref(bound.get("candidate_manifest_ref"), old["inventory_ref"])
          and _same_ref(bound.get("schedule_ref"), old["schedule_ref"])
          and bound.get("windows") == windows
          and bound.get("candidate_bindings") == original_bindings, "ORIGINAL_ADMISSION_CHANGED")
    _need(bound.get("fresh_account") is True and bound.get("initial_cash_usd") == 3000
          and bound.get("initial_holdings") == [] and bound.get("initial_receivables") == []
          and all(bound.get(k) is False for k in ("strict_PIT_promotion_eligible", "production_qualified", "finalist_selected")),
          "ORIGINAL_FRESH_RESEARCH_ACCOUNT_REQUIRED")
    sources = bound["source_refs"]
    qualification = _document(bound["source_qualification_ref"], kind="source_qualification")
    _need(set(sources) == set(f.SOURCE_GROUPS) and cfg.get("source_refs") == sources
          and qualification.get("task_id") == OLD_TASK and qualification.get("source_refs") == sources,
          "EXACT_ORIGINAL_SOURCE_QUALIFICATION_REQUIRED")
    ready = p._source_ready_policies(qualification, sources, bound["allowed_path_ids"], bindings=bound["candidate_bindings"])
    _need(all(r["original_candidate_id"] in ready for r in rows), "ORIGINAL_SOURCE_NOT_QUALIFIED")
    for reference in sources.values():
        _physical(reference)
    # The original validator checks the old catalogue, authorization and every
    # event source pin. Only then wrap its unchanged economic commitments.
    event_json = []
    for key in ("research_cash_reconstruction", "research_terminal_reconstruction"):
        original = json.loads(f._load_post_verified_binding(bound, sources, OLD_TASK, key))
        wrapped = dict(original, task_id=TASK, original_task_id=OLD_TASK,
                       original_catalogue_ref=sources["corporate_actions"], new_scope_config_ref=config_ref,
                       original_binding_sha256=hashlib.sha256(_canonical(original).encode()).hexdigest()) if original else {}
        event_json.append(json.dumps(wrapped, sort_keys=True, allow_nan=False))
    states = {}
    for name, head in binding["heads"].items():
        for key in ("model_ref", "receipt_ref"):
            _physical(head[key])
        states["new_value:" + name] = {k: deepcopy(head[k]) for k in ("model_ref", "receipt_ref")}
    risk_ids = {k for row in rows for k in row["dependency_closure"]["state_ids"] if k.startswith("old_risk:")}
    for key in sorted(risk_ids):
        _need(key in bound["state_refs"], "ORIGINAL_RISK_STATE_MISSING")
        states[key] = deepcopy(bound["state_refs"][key])
        for reference in states[key].values():
            _physical(reference)
    new_outputs = _document(cfg["new_value_outputs_ref"])
    outputs = new_outputs.get("outputs", {})
    _need(new_outputs.get("task_id") == TASK and new_outputs.get("start") == "2026-01-02"
          and new_outputs.get("end") == "2026-10-08" and type(new_outputs.get("new_fit")) is int
          and new_outputs["new_fit"] == 0 and set(outputs) == HEADS | {"lgb"}
          and type(new_outputs.get("requested_heads")) is int and new_outputs["requested_heads"] == 12
          and new_outputs.get("support_heads") == ["lgb"]
          and outputs["lgb"].get("role") == "SUPPORT_ONLY", "EXACT_NEW_SAVED_TWELVE_HEAD_OUTPUTS_REQUIRED")
    _need(_same_ref(new_outputs.get("head_binding_ref"), cfg["head_binding_ref"])
          and _same_ref(new_outputs.get("training_acceptance_ref"), cfg["training_acceptance_ref"]),
          "NEW_OUTPUT_HEAD_BINDING_REQUIRED")
    allowed_columns = {"signal_date", "ticker", "prediction", "value_sigma", "prediction_qualified", "year",
                       "evaluation_year", "model_id", "model_sha256", "model_reuse_tuple_sha256",
                       "model_lineage", "prediction_role"}
    from scripts.research.a2.training import stateful_values as value_owner
    for name in HEADS:
        output, head = outputs[name], binding["heads"][name]
        receipt = _document(head["receipt_ref"])
        diagnostic = set() if name.startswith("fusion::") else set(value_owner.diagnostic_columns(receipt["native_model_id"]))
        columns = output.get("read_columns")
        _need(output.get("role") == "REQUESTED_HEAD" and isinstance(columns, list)
              and len(columns) == len(set(columns))
              and {"signal_date", "ticker", "prediction", "prediction_qualified"} <= set(columns) <= allowed_columns | diagnostic
              and _same_ref(output.get("model_ref"), head["model_ref"])
              and _same_ref(output.get("receipt_ref"), head["receipt_ref"])
              and math.isfinite(output.get("sigma", float("nan"))) and output["sigma"] > 0
              and output["sigma"] == head["new_pool_sigma"]
              and isinstance(output.get("lineage"), str) and bool(output["lineage"]), "NEW_OUTPUT_HEAD_CUSTODY_CHANGED")
        _physical(output["frame_ref"])
    # Metadata contract only: never load the old broad authority or its missing value states.
    parent_contract = p.profile_contract(OLD_TASK)
    old_state_ref = parent_contract["metadata_refs"]["old_states"]
    _physical(old_state_ref)
    plan = _document(old["plan_ref"])
    contract = dict(task_id=TASK, metadata_refs=dict(old_states=old_state_ref, inventory=config_ref,
                    plan=old["plan_ref"], schedule=cfg["schedule_ref"]), plan=plan, schedule=schedule,
                    candidate_bindings=rows, state_refs=states, source_refs=sources,
                    raw_selector_binding=deepcopy(parent_contract["raw_selector_binding"]))
    return dict(config=cfg, config_ref=deepcopy(config_ref), binding=binding, rows=rows,
                parent_admission_ref=deepcopy(old["admission_ref"]),
                contract=contract, windows={w["window_id"]: w for w in windows}, bound=bound,
                events=event_json, issued={})


def candidates():
    _need(_STATE is not None, "INSTALL_ROUTES_FIRST")
    return [deepcopy(r["specification"]) for r in _STATE["rows"]]


def _new(value):
    return ((isinstance(value, dict) and (value.get("task_id") == TASK or value.get("schema") == SCHEMA))
            or getattr(value, "task_id", None) == TASK)


def _fields(value):
    return (value.task_id, value.window_id, value.start, value.end, value.as_of, value.feature_history_start,
            value.allowed_path_ids, value.capability, value.research_cash_reconstruction_json,
            value.research_terminal_reconstruction_json, value.source_ready_policy_ids)


def _verified(value):
    _need(_STATE is not None, "INSTALL_ROUTES_FIRST")
    if not _new(value):
        return _STATE["originals"]["verified"](value)
    f = _STATE["f"]
    _need(type(value) is f.ValidatedDescriptiveAuthority and value._seal is _SEAL
          and value.capability == "ACCOUNT", "SEALED_NEW_SCOPE_AUTHORITY_REQUIRED")
    issued = _STATE["issued"].get((value.window_id, value.source_ready_policy_ids))
    custody = value._source_policy_custody
    _need(issued is not None and _fields(value) == issued["fields"]
          and type(custody) is f._SourcePolicyCustody and custody.seal is _SEAL
          and custody.task_id == TASK and custody.policy_ids == value.source_ready_policy_ids,
          "ADMISSION_OR_SOURCE_CUSTODY_CHANGED")
    ids = value.runtime_policy_ids
    _need(ids == tuple(i for i in value.source_ready_policy_ids if i in ids), "RUNTIME_POLICY_ORDER_CHANGED")
    if ids not in issued["provenances"]:
        provenance = dict(issued["provenance"], runtime_policy_ids=list(ids))
        issued["provenances"][ids] = json.dumps(provenance, sort_keys=True, allow_nan=False)
    _need(value.provenance_json == issued["provenances"][ids], "ADMITTED_PROVENANCE_CHANGED")
    return value


def load_authority(window_id, candidate_ids=None):
    _need(_STATE is not None, "INSTALL_ROUTES_FIRST")
    f = _STATE["f"]
    if type(window_id) is f.ValidatedDescriptiveAuthority:
        _need(candidate_ids is None, "NO_RESCOPING_VALIDATED_OBJECT")
        return _verified(window_id)
    if isinstance(window_id, dict):
        ref = window_id
        _need(set(ref) == {"schema", "task_id", "config_ref", "window_id"}
              and ref["schema"] == SCHEMA and ref["task_id"] == TASK
              and _same_ref(ref["config_ref"], _STATE["config_ref"]), "EXACT_NEW_AUTHORITY_REF_REQUIRED")
        window_id = ref["window_id"]
    _need(isinstance(window_id, str) and window_id in _STATE["windows"], "REGISTERED_WINDOW_REQUIRED")
    full = tuple(r["candidate_id"] for r in _STATE["rows"])
    ids = full if candidate_ids is None else tuple(candidate_ids)
    _need(bool(ids) and len(set(ids)) == len(ids) and ids == tuple(i for i in full if i in ids), "ORDERED_SOURCE_READY_SUBSET_REQUIRED")
    _physical(_STATE["config_ref"])
    window, bound = _STATE["windows"][window_id], _STATE["bound"]
    start, end = f._day(window["start"]), f._day(window["end"])
    as_of, history = f.pd.Timestamp(bound["as_of"]), f._day(bound["feature_history_start"])
    _need(f.pd.Timestamp("2026-01-01") <= start < end < f.pd.Timestamp("2027-01-01")
          and as_of.tzinfo is not None and (end + f.pd.Timedelta(hours=16)).tz_localize("America/New_York") <= as_of,
          "COMPLETE_2026_WINDOW_REQUIRED")
    provenance = dict(schema=SCHEMA, task_id=TASK, config_ref=_STATE["config_ref"],
                      candidate_manifest_ref=_STATE["config_ref"], source_qualification_ref=_STATE["config_ref"],
                      source_refs=bound["source_refs"], candidate_bindings=_STATE["rows"],
                      state_refs=_STATE["contract"]["state_refs"], source_ready_policy_ids=list(ids), runtime_policy_ids=[],
                      raw_selector_binding=_STATE["contract"]["raw_selector_binding"],
                      original_admission_ref=_STATE["parent_admission_ref"],
                      original_source_qualification_ref=bound["source_qualification_ref"],
                      original_state_closure_restored=False, formal_primary_metrics_allowed=False,
                      historical_delivery_certification="RETAIN_ORIGINAL_UNKNOWN")
    serialized = json.dumps(provenance, sort_keys=True, allow_nan=False)
    value = f.ValidatedDescriptiveAuthority(TASK, window_id, start, end, as_of, history, full, serialized, _SEAL,
              research_cash_reconstruction_json=_STATE["events"][0], research_terminal_reconstruction_json=_STATE["events"][1],
              source_ready_policy_ids=ids, _source_policy_custody=f._SourcePolicyCustody(TASK, ids, _SEAL))
    _STATE["issued"][(window_id, ids)] = dict(fields=_fields(value), provenance=provenance, provenances={(): serialized})
    return _verified(value)


def profile_contract(task_id=TASK, **kwargs):
    _need(_STATE is not None and task_id == TASK and all(v is None for v in kwargs.values()), "EXACT_NEW_TASK_CONTRACT_REQUIRED")
    return deepcopy(_STATE["contract"])


def contract_for_authority(value):
    _verified(value)
    return profile_contract()


def install_routes(config_ref):
    """Install after sealed-owner bootstrap; no other task gains admission."""
    global _STATE
    from scripts.research.a2.evaluation import frozen_test_authority as f, frozen_a94_profile as p
    if _STATE is not None:
        _need(_same_ref(_STATE["config_ref"], config_ref), "ONE_FROZEN_CONFIG_PER_PROCESS")
        _physical(config_ref)
        return dict(task_id=TASK, process_private_routes=True)
    prepared = _prepare(config_ref, f, p)
    originals = dict(verified=f._verified, load=f.load_descriptive_authority,
                     event=f.validate_reconstructed_accounting_events,
                     profile_tasks=p.profile_tasks, profile_contract=p.profile_contract,
                     profile_load=p.load_authority, contract=getattr(p, "contract_for_authority", None), roles=p.required_action_roles)
    _STATE = dict(prepared, f=f, p=p, originals=originals)
    def dispatch(fn, old):
        def route(value, *args, **kwargs):
            return fn(value, *args, **kwargs) if _new(value) else old(value, *args, **kwargs)
        return route
    f._verified = _verified
    f.load_descriptive_authority = dispatch(load_authority, originals["load"])
    # Economic event code is verbatim. Original catalogue/header was admitted
    # before wrapping; new task is routed directly, without claiming old identity.
    event = _clone(originals["event"], _verified=_verified, TASK=TASK,
                   six_path_tasks=lambda: (TASK,), a_profile_tasks=lambda: ())
    f.validate_reconstructed_accounting_events = dispatch(event, originals["event"])
    p.profile_tasks = lambda: (*originals["profile_tasks"](), TASK)
    p.profile_contract = lambda task_id=p.TASK, **kw: (profile_contract(task_id, **kw) if task_id == TASK
                                                      else originals["profile_contract"](task_id, **kw))
    p.load_authority = dispatch(load_authority, originals["profile_load"])
    # The sealed parent predates contract_for_authority; its loader calls
    # profile_contract(task_id) directly. Keep that old interface unchanged.
    if originals["contract"] is not None:
        p.contract_for_authority = dispatch(contract_for_authority, originals["contract"])
    def roles(cid, *, authority=None, bindings=None):
        if cid.startswith(PREFIX):
            rows = _STATE["rows"] if bindings is None else bindings
            _need(any(r["candidate_id"] == cid and r["runtime_owner"] == "STATEFUL_OVERLAY"
                      and r["required_action_roles"] == [] for r in rows), "REGISTERED_STATEFUL_POLICY_REQUIRED")
            if authority is not None:
                _verified(authority)
            return ()
        return originals["roles"](cid, authority=authority, bindings=bindings)
    p.required_action_roles = roles
    return dict(task_id=TASK, process_private_routes=True)