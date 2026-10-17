"""Synthetic exact-profile custody checks; no real model, input reader or data."""
import copy
import hashlib
import json
from pathlib import Path
import pandas as pd
import pytest
from scripts.research.a2.evaluation import frozen_test_authority as common
from scripts.research.a2.evaluation import frozen_a94_profile as profile


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(profile, "_ROOT", tmp_path)
    monkeypatch.setattr(profile, "_roots", lambda: (tmp_path.resolve(),))
    def write(name, value):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True, allow_nan=False), encoding="utf-8")
        return dict(path=str(path), sha256=sha(path.read_bytes()))
    def state(name):
        return dict(model_ref=write("states/" + name + ".model", {"synthetic_state": name}),
                    receipt_ref=write("states/" + name + ".receipt", {"year": 2025, "synthetic_state": name}))
    old = dict(value_models=[], risk_models=[])
    for i in range(13):
        name = ["ridge", "hgb"][i] if i < 2 else "v" + str(i)
        item = state("value_" + name)
        old["value_models"].append(dict(model_id=name, metadata=dict(model_path=item["model_ref"]["path"],
            model_sha256=item["model_ref"]["sha256"]), receipt_ref=item["receipt_ref"]))
    for i in range(12):
        item = state("risk_" + str(i))
        old["risk_models"].append(dict(risk_id="r" + str(i), bundle_ref=item["model_ref"], receipt_ref=item["receipt_ref"]))
    newer = dict(model_states=[], external_scaler_states=[])
    for group, count in (("model_states", 81), ("external_scaler_states", 4)):
        for i in range(count):
            name = group + str(i)
            item = state(name)
            newer[group].append(dict(slot_id=name, model_path=item["model_ref"]["path"],
                model_sha256=item["model_ref"]["sha256"], receipt_ref=item["receipt_ref"]))
    experts = []
    for name in ("ridge", "hgb", "lgb"):
        if name != "lgb":
            prior = next(r for r in old["value_models"] if r["model_id"] == name)
            item = dict(model_ref=dict(path=prior["metadata"]["model_path"], sha256=prior["metadata"]["model_sha256"]), receipt_ref=prior["receipt_ref"])
        else:
            item = state("expert_lgb")
        experts.append(dict(model_id=name, year=2025, **item))
    candidates = []
    for i in range(94):
        name, bps = "policy_" + str(i), 10 if i < 90 else 5 if i < 92 else 20
        digest = sha(name.encode())
        friction = dict(authority="HYPOTHETICAL_RESEARCH_SCENARIO", benchmark="NEXT_RAW_OPEN", fee_bps=0,
            kind="FIXED_ADVERSE_OPEN_SLIPPAGE", one_way_bps=bps, scenario_id="ADVERSE_OPEN_" + str(bps) + "BPS_USD3000")
        spec = dict(candidate_id=name, scientific_tuple_sha256=digest, value_model="frozen",
            risk="diag20_reference", control="TARGET", action="RAW", gross=.8, execution_friction=friction)
        candidates.append(dict(candidate_id=name, scientific_tuple_sha256=digest, specification=spec,
            pre2026_research_integrity="FAIL" if i < 11 else "PASS"))
    plan = dict(task_id=profile.TASK, training_content_cutoff_exclusive="2026-01-01",
        development_validation_cutoff_exclusive="2026-01-01", test_interval=["2026-01-01", "2027-01-01"],
        as_of_utc="2026-10-07T18:42:01.905856+00:00")
    docs = dict(plan=plan, inventory=dict(candidates=candidates), old_states=old, new_states=newer,
        fusion=dict(fusion_expert2025_closure=dict(experts=experts)))
    selector = state("upstream_raw_classifier")
    docs["raw_selector"] = dict(same_model_not_same_universe=dict(frozen_Raw_A2_model=selector["model_ref"],
        frozen_feature_source=dict(path=str(tmp_path / "original_feature_source.py"), sha256="1" * 64),
        ordered_32_features=["feature_" + str(i) for i in range(32)], historical_2026_model_metadata=dict(
            year=2026, train_start="2020-06-24", train_end="2025-12-02", labelmax="2025-12-31",
            model_role="FROZEN_FULL_PRE2026_FOR_2026_INFERENCE_ONLY")), original_contract=dict(institutions=24))
    pins = {}
    for name, value in docs.items():
        ref = write(name + ".json", value)
        pins[name] = (name + ".json", ref["sha256"])
    monkeypatch.setattr(profile, "_PINS", pins)
    contract = profile.frozen_profile_contract()
    sources = {k: write("views/" + k + ".json", dict(synthetic=True)) for k in common.SOURCE_GROUPS}
    qualification = dict(schema="A_2026_DESCRIPTIVE_SOURCE_QUALIFICATION_R1", task_id=profile.TASK,
        status="QUALIFIED_FOR_DECLARED_RESEARCH_SCOPE", source_refs=sources, as_of=plan["as_of_utc"],
        common_calendar_start="2026-01-05", common_calendar_end="2026-10-06",
        common_calendar_selection="SOURCE_AVAILABILITY_AND_ORIGINAL_CALENDAR_ONLY",
        raw_selector_binding=contract["raw_selector_binding"],
        groups={k: True for k in common.SOURCE_GROUPS}, source_slices={k: dict(source_ref=ref,
            no_2027_content=True, view_only=True, content_start="2023-01-01", content_end="2026-10-06",
            available_at="2026-10-07T01:00:00+00:00") for k, ref in sources.items()})
    bound = dict(schema="A_2026_DESCRIPTIVE_ACCOUNT_ADMISSION_R1", task_id=profile.TASK,
        status="SOURCE_AND_POLICY_BOUND_FOR_DESCRIPTIVE_EVALUATION", strict_PIT_promotion_eligible=False,
        production_qualified=False, finalist_selected=False, new_fit=0, plan_ref=contract["metadata_refs"]["plan"],
        candidate_manifest_ref=contract["metadata_refs"]["inventory"], allowed_path_ids=[r["candidate_id"] for r in candidates],
        candidate_bindings=contract["candidate_bindings"], state_refs=contract["state_refs"], initial_cash_usd=3000,
        initial_holdings=[], initial_receivables=[], fresh_account=True, as_of=plan["as_of_utc"],
        windows=[dict(window_id="COMMON_2026", start="2026-01-05", end="2026-10-06")],
        feature_history_start="2023-01-01", source_refs=sources, source_qualification_ref=write("qualification.json", qualification))
    authority = dict(schema="A_2026_DESCRIPTIVE_AUTHORITY_REF_R1", task_id=profile.TASK, window_id="COMMON_2026")
    def persist():
        authority["admission_ref"] = write("admission.json", bound)
        return authority
    def persist_qualification():
        bound["source_qualification_ref"] = write("qualification.json", qualification)
        return persist()
    persist()
    return dict(authority=authority, bound=bound, contract=contract, candidates=candidates, docs=docs,
        qualification=qualification, persist=persist, persist_qualification=persist_qualification, write=write, pins=pins)


def admitted(bundle):
    value = common.load_descriptive_authority(bundle["authority"])
    return common.validate_descriptive_policy(value, [r["specification"] for r in bundle["candidates"]])


def test_exact94_and111_closure_preserves_all_failures_and_friction(bundle):
    value = admitted(bundle)
    assert len(value.allowed_path_ids) == 94
    assert len(bundle["contract"]["state_refs"]) == 111
    assert "fusion_expert:lgb" in bundle["contract"]["state_refs"]
    assert sum(r["pre2026_research_integrity"] == "FAIL" for r in bundle["candidates"]) == 11
    assert [sum(r["specification"]["execution_friction"]["one_way_bps"] == cost for r in bundle["candidates"]) for cost in (5, 10, 20)] == [2, 90, 2]
    assert common.validate_descriptive_policy(value, [r["specification"] for r in bundle["candidates"]]).allowed_path_ids == value.allowed_path_ids
    assert json.loads(value.provenance_json)["source_gate_level"] == "DECLARED_SOURCE_CUSTODY_NOT_PIT_CERTIFICATION"


def test_cached_authority_account_policy_and_dates_do_no_io(bundle, monkeypatch):
    value = admitted(bundle)
    def fail(*args, **kwargs):
        raise AssertionError("cached checks must not rehash or read")
    monkeypatch.setattr(common, "_physical", fail)
    monkeypatch.setattr(profile, "_document", fail)
    assert common.load_descriptive_authority(value) is value
    assert common.require_descriptive_decision(value, "2026-10-06", "policy_90") is value
    assert common.validate_descriptive_input_dates(value, ["2023-01-03"], feature_context=True) is value
    assert json.loads(common.validate_descriptive_policy(value, [bundle["candidates"][90]["specification"]]).provenance_json)["runtime_policy_ids"] == ["policy_90"]
    assert common.validate_descriptive_account(value, ["2026-01-05", "2026-10-06"], ["policy_90"],
        dict(initial_nav=3000), bundle["candidates"][90]["specification"]["execution_friction"]) is value


@pytest.mark.parametrize("path,change", [
    (("candidate_bindings", 0, "specification", "risk"), "PCA"),
    (("candidate_bindings", 0, "specification", "control"), "HOLD"),
    (("candidate_bindings", 0, "specification", "action"), "REPLACE"),
    (("candidate_bindings", 0, "scientific_tuple_sha256"), "0" * 64),
    (("plan_ref", "sha256"), "0" * 64),
    (("candidate_manifest_ref", "sha256"), "0" * 64),
    (("new_fit",), 1), (("production_qualified",), True),
    (("initial_holdings",), ["S"]), (("initial_cash_usd",), 10000),
    (("as_of",), "2026-10-08T00:00:00+00:00"),
    (("as_of",), "2026-10-07T18:42:01.905856"),
    (("windows", 0, "end"), "2026-10-07"),
    (("windows", 0, "start"), "2026-01-02"),
])
def test_admission_tamper_refused(bundle, path, change):
    item = bundle["bound"]
    for key in path[:-1]:
        item = item[key]
    item[path[-1]] = change
    with pytest.raises(ValueError):
        common.load_descriptive_authority(bundle["persist"]())


@pytest.mark.parametrize("mutation", ["risk", "control", "action", "extra", "reorder", "unknown"])
def test_runtime_full_policy_not_just_id_or_digest(bundle, mutation):
    value = admitted(bundle)
    policies = copy.deepcopy([r["specification"] for r in bundle["candidates"][:2]])
    if mutation == "extra":
        policies[0]["runtime_field"] = "not_white_listed"
    elif mutation == "reorder":
        policies.reverse()
    elif mutation == "unknown":
        policies[0]["candidate_id"] = "unregistered"
    else:
        policies[0][mutation] = "changed_without_digest_change"
    with pytest.raises(ValueError):
        common.validate_descriptive_policy(value, policies)


def test_model_or_receipt_mutation_refused_without_deserialization(bundle):
    state = bundle["contract"]["state_refs"]["fusion_expert:lgb"]
    Path(state["model_ref"]["path"]).write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA_CHANGED"):
        common.load_descriptive_authority(bundle["authority"])


@pytest.mark.parametrize("slot", ["fusion_expert:lgb", "old_risk:r11", "new_scaler:external_scaler_states3"])
def test_missing_dependency_rejected(bundle, slot):
    del bundle["bound"]["state_refs"][slot]
    with pytest.raises(ValueError, match="FULL_STATE_BINDING"):
        common.load_descriptive_authority(bundle["persist"]())


def test_fusion_expert_cannot_disappear_from_pinned_metadata_projection(bundle):
    docs = bundle["docs"]
    docs["fusion"]["fusion_expert2025_closure"]["experts"].pop()
    ref = bundle["write"]("fusion.json", docs["fusion"])
    bundle["pins"]["fusion"] = ("fusion.json", ref["sha256"])
    with pytest.raises(ValueError, match="FUSION_EXPERT_CLOSURE"):
        profile.frozen_profile_contract()


@pytest.mark.parametrize("mutation", ["future", "old_asof", "naive", "unbounded", "wrong_ref", "false_gate"])
def test_source_declaration_rejected_before_scientific_view_hash(bundle, monkeypatch, mutation):
    qualification = bundle["qualification"]
    scope = qualification["source_slices"]["market_quote"]
    if mutation == "future":
        scope["content_end"] = "2027-01-01"
    elif mutation == "old_asof":
        scope["available_at"] = "2026-10-08T00:00:00+00:00"
    elif mutation == "naive":
        scope["available_at"] = "2026-10-06T00:00:00"
    elif mutation == "unbounded":
        scope["view_only"] = False
    elif mutation == "wrong_ref":
        scope["source_ref"] = bundle["bound"]["source_refs"]["action_inputs"]
    else:
        qualification["groups"]["market_quote"] = False
    bundle["persist_qualification"]()
    original = common._physical
    sources = {v["path"] for v in bundle["bound"]["source_refs"].values()}
    def checked(ref):
        assert ref["path"] not in sources, "invalid scope touched a scientific view"
        return original(ref)
    monkeypatch.setattr(common, "_physical", checked)
    with pytest.raises(ValueError):
        common.load_descriptive_authority(bundle["authority"])


@pytest.mark.parametrize("indexes", [[0, 1], [90, 91], [92, 93]])
def test_each_original_cost_batch_accepted(bundle, indexes):
    value = admitted(bundle)
    rows = [bundle["candidates"][i] for i in indexes]
    assert common.validate_descriptive_account(value, ["2026-01-05", "2026-10-06"],
        [r["candidate_id"] for r in rows], dict(initial_nav=3000), rows[0]["specification"]["execution_friction"]) is value


@pytest.mark.parametrize("mutation", ["mixed", "fee", "basis", "capital", "receivables", "order"])
def test_account_cannot_normalize_cost_basis_or_capital(bundle, mutation):
    value = admitted(bundle)
    ids, account = ["policy_0", "policy_1"], dict(initial_nav=3000)
    friction = copy.deepcopy(bundle["candidates"][0]["specification"]["execution_friction"])
    if mutation == "mixed": ids.append("policy_90")
    if mutation == "fee": friction["fee_bps"] = 1
    if mutation == "basis": friction["benchmark"] = "CLOSE"
    if mutation == "capital": account["initial_nav"] = 10000
    if mutation == "receivables": account["initial_receivables"] = [1]
    if mutation == "order": ids.reverse()
    with pytest.raises(ValueError):
        common.validate_descriptive_account(value, ["2026-01-05", "2026-10-06"], ids, account, friction)


def test_unknown_third_task_and_unsealed_object_are_rejected(bundle):
    authority = copy.deepcopy(bundle["authority"])
    authority["task_id"] = "ARBITRARY_TASK"
    with pytest.raises(ValueError, match="EXACT_TASK"):
        common.load_descriptive_authority(authority)
    value = admitted(bundle)
    forged = common.ValidatedDescriptiveAuthority(value.task_id, value.window_id, value.start, value.end,
        value.as_of, value.feature_history_start, value.allowed_path_ids, value.provenance_json, object())
    with pytest.raises(ValueError, match="VALIDATED"):
        common.load_descriptive_authority(forged)
    with pytest.raises(TypeError):
        value.__reduce__()


def test_physical_escape_and_oversized_metadata_rejected_before_hash(bundle, tmp_path):
    with pytest.raises(ValueError, match="PHYSICAL_ROOT"):
        profile._safe_path(dict(path=str(Path(__file__).resolve()), sha256="0" * 64))
    path = tmp_path / "oversized.json"
    with path.open("wb") as stream:
        stream.truncate(16 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="SIZE_BOUND"):
        profile._document(dict(path=str(path), sha256="0" * 64))


def test_legacy_constants_and_default_10bps_semantics_unchanged():
    assert common.TASK == "V24_A_FROZEN_THREE_POLICY_2026_RANDOM_START_EVALUATION_R1"
    assert len(common.PATH_IDS) == 6 and common.MODEL_IDS == common.PATH_IDS[1:4]
    value = common.ValidatedDescriptiveAuthority(common.TASK, "W", pd.Timestamp("2026-01-01"),
        pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-03T00:00:00Z"), pd.Timestamp("2023-01-01"),
        common.PATH_IDS, "{}", common._SEAL)
    assert common.validate_descriptive_account(value, ["2026-01-01", "2026-01-02"], [common.PATH_IDS[0]],
        dict(initial_nav=3000), dict(one_way_bps=10)) is value
    with pytest.raises(ValueError, match="FIXED_10BPS"):
        common.validate_descriptive_account(value, ["2026-01-01", "2026-01-02"], [common.PATH_IDS[0]],
            dict(initial_nav=3000), dict(one_way_bps=5))


def test_metadata_seal_alone_cannot_enter_overlay_or_account(bundle):
    value = common.load_descriptive_authority(bundle["authority"])
    assert value.start == pd.Timestamp("2026-01-05")
    assert common.require_descriptive_decision(value, "2026-01-05") is value
    with pytest.raises(ValueError, match="FULL_RUNTIME_POLICY"):
        common.require_descriptive_decision(value, "2026-01-05", "policy_0")
    with pytest.raises(ValueError, match="FULL_RUNTIME_POLICY"):
        common.validate_descriptive_account(value, ["2026-01-05", "2026-10-06"], ["policy_0"],
            dict(initial_nav=3000), bundle["candidates"][0]["specification"]["execution_friction"])
    scoped = common.validate_descriptive_policy(value, [bundle["candidates"][0]["specification"]])
    assert common.require_descriptive_decision(scoped, "2026-01-05", "policy_0") is scoped
    with pytest.raises(ValueError, match="FULL_RUNTIME_POLICY"):
        common.require_descriptive_decision(scoped, "2026-01-05", "policy_1")
    with pytest.raises(ValueError, match="FULL_RUNTIME_POLICY"):
        common.require_descriptive_decision(value, "2026-01-05", "policy_0")


@pytest.mark.parametrize("mutation", ["classifier", "features", "vintage", "calendar", "selection"])
def test_original_selector_and_source_only_calendar_binding(bundle, mutation):
    q = bundle["qualification"]
    if mutation == "classifier":
        q["raw_selector_binding"] = copy.deepcopy(q["raw_selector_binding"])
        q["raw_selector_binding"]["model_ref"] = bundle["contract"]["state_refs"]["new_model:model_states0"]["model_ref"]
    elif mutation == "features":
        q["raw_selector_binding"] = copy.deepcopy(q["raw_selector_binding"])
        q["raw_selector_binding"]["ordered_32_features"].reverse()
    elif mutation == "vintage":
        q["raw_selector_binding"] = copy.deepcopy(q["raw_selector_binding"])
        q["raw_selector_binding"]["model_vintage"]["labelmax"] = "2026-01-01"
    elif mutation == "calendar":
        q["common_calendar_start"] = "2026-01-01"
    else:
        q["common_calendar_selection"] = "SELECTED_BY_RETURN"
    with pytest.raises(ValueError):
        common.load_descriptive_authority(bundle["persist_qualification"]())


def test_full_spec_number_types_are_not_coerced(bundle):
    value = common.load_descriptive_authority(bundle["authority"])
    policy = copy.deepcopy(bundle["candidates"][0]["specification"])
    policy["execution_friction"]["fee_bps"] = False
    with pytest.raises(ValueError, match="FULL_SPEC_CHANGED"):
        common.validate_descriptive_policy(value, [policy])


def _postverified94(bundle, monkeypatch, kind="cash"):
    from scripts.v22 import corporate_action_transition_r1 as ca
    source = bundle["write"]("post_source.json", {"synthetic": True})
    recon = bundle["write"]("post_reconstruction.json", {"synthetic": True, "task_id": profile.TASK})
    args = dict(event_id="SYNTHETIC_"+kind, old_security_id="secDBRG" if kind=="terminal" else "secS",
        ticker="DBRG" if kind=="terminal" else "S", available_at=None,
        cash_per_old_share=16. if kind=="terminal" else 1., currency="USD",
        amount_unit=ca.USD_PER_RAW_OLD_SHARE, quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,
        source_type="TIER1_ISSUER_REGULATOR_EXCHANGE", source_reference=source["path"],
        source_fingerprint=source["sha256"], reconstruction_ref=recon["path"],
        reconstruction_sha256=recon["sha256"])
    if kind=="terminal":
        quantity=bundle["write"]("post_quantity.json",{"synthetic":True})
        event=ca.ResearchPostVerifiedTerminalEvent(**args, effective_at="2026-09-30T13:30:00Z",
            quantity_source_reference=quantity["path"], quantity_source_fingerprint=quantity["sha256"])
    else:
        event=ca.ResearchReconstructedCashEvent(**args,action_type="CASH_DIVIDEND",
            ex_date="2026-02-06",record_date="2026-02-06",pay_date="2026-02-10")
    decision=dict(schema="A94_POST_VERIFIED_CASH_TERMINAL_SOURCE_DECISION_R1",task_id=profile.TASK,
        status="HUMAN_AUTHORIZED_NOT_SOURCE_OR_RUNTIME_ADMISSION",
        candidate_scope="EXACT94_FROZEN_EMPTY_START_RESEARCH_POLICIES",
        clock_role="POST_VERIFIED_ACCOUNTING_ONLY", original_plan_ref=bundle["contract"]["metadata_refs"]["plan"],
        candidate_manifest_ref=bundle["contract"]["metadata_refs"]["inventory"],
        economic_as_of_utc=bundle["docs"]["plan"]["as_of_utc"],separate_A6_permission_inherited=False,
        prohibitions={k:False for k in ("model_or_H5_input_authority","new_fit","parameter_or_rule_change",
            "strategy_selection","production_qualified","strict_PIT_promotion_eligible","broker_orders",
            "source_or_account_admitted_by_decision_alone","economic_window_extended")})
    decision_ref=bundle["write"]("decision.json",decision)
    monkeypatch.setattr(profile,"_POST_VERIFIED_DECISION_PIN",("decision.json",decision_ref["sha256"]))
    entry=dict(event_fingerprint=event.event_fingerprint,reconstruction_ref=recon)
    key="research_"+kind+"_reconstruction"
    if kind=="terminal":
        entry["terminal_terms"]={**{k:getattr(event,k) for k in common._TERMINAL_COMMITMENT_FIELDS},"settlement":None}
    binding=dict(task_id=profile.TASK,authorization_ref=decision_ref,clock_role="POST_VERIFIED_ACCOUNTING_ONLY",
        strict_PIT_promotion_eligible=False,production_qualified=False,events=[entry])
    bundle["bound"][key]=binding
    bundle["bound"]["post_verified_accounting_decision_ref"]=decision_ref
    bundle["post_catalogue"]={key:binding}
    bundle["post_key"]=key
    def persist():
        source_ref=bundle["write"]("views/corporate_actions.json",bundle["post_catalogue"])
        bundle["bound"]["source_refs"]["corporate_actions"]=source_ref
        bundle["qualification"]["source_refs"]["corporate_actions"]=source_ref
        bundle["qualification"]["source_slices"]["corporate_actions"]["source_ref"]=source_ref
        return bundle["persist_qualification"]()
    bundle["persist_post"]=persist
    bundle["qualification"]["source_slices"]["corporate_actions"].update(
        clock_role="POST_VERIFIED_ACCOUNTING_ONLY",available_at=None,
        historical_available_at_bound=False,captured_at="2026-10-08T05:00:00Z")
    persist()
    return event


@pytest.mark.parametrize("kind",["cash","terminal"])
def test_postverified94_independent_decision_bound_and_runtime_cached(bundle,monkeypatch,kind):
    event=_postverified94(bundle,monkeypatch,kind)
    value=admitted(bundle)
    field="research_"+kind+"_reconstruction_json"
    assert json.loads(getattr(value,field))["task_id"]==profile.TASK
    monkeypatch.setattr(common,"_physical",lambda *args:pytest.fail("runtime IO"))
    assert common.validate_reconstructed_accounting_events(value,[event],require_exact=True) is value


@pytest.mark.parametrize("fault",["missing_ref","other_task","other_decision","wrong_clock","duplicate","no_capture","naive_capture","fake_history"])
def test_postverified94_ref_scope_and_capture_tampering_refused(bundle,monkeypatch,fault):
    _postverified94(bundle,monkeypatch)
    binding=bundle["bound"][bundle["post_key"]]
    scope=bundle["qualification"]["source_slices"]["corporate_actions"]
    if fault=="missing_ref":del bundle["bound"]["post_verified_accounting_decision_ref"]
    elif fault=="other_task":binding["task_id"]=common.TASK
    elif fault=="other_decision":binding["authorization_ref"]=bundle["contract"]["metadata_refs"]["plan"]
    elif fault=="wrong_clock":binding["clock_role"]="STRICT_PIT"
    elif fault=="duplicate":binding["events"]*=2
    elif fault=="no_capture":scope["captured_at"]=None
    elif fault=="naive_capture":scope["captured_at"]="2026-10-08T05:00:00"
    else:scope["historical_available_at_bound"]=True
    bundle["persist_post"]()
    with pytest.raises(ValueError):common.load_descriptive_authority(bundle["authority"])


@pytest.mark.parametrize("slot",["market_quote","security_identity","action_inputs","quote_quality"])
def test_postverified94_cash_permission_never_relaxes_other_source_clocks(bundle,monkeypatch,slot):
    _postverified94(bundle,monkeypatch)
    bundle["qualification"]["source_slices"][slot].update(clock_role="POST_VERIFIED_ACCOUNTING_ONLY",
        available_at=None,historical_available_at_bound=False,captured_at="2026-10-08T05:00:00Z")
    bundle["persist_post"]()
    with pytest.raises(ValueError,match="SCOPE_OUTSIDE_WINDOW"):
        common.load_descriptive_authority(bundle["authority"])


@pytest.mark.parametrize("term,value",[("ticker","OTHER"),("cash_per_old_share",17.),
    ("effective_at","2026-10-01T13:30:00Z"),("settlement","2026-10-01")])
def test_postverified94_terminal_permission_is_only_explicit_DBRG_terms(bundle,monkeypatch,term,value):
    _postverified94(bundle,monkeypatch,"terminal")
    bundle["bound"][bundle["post_key"]]["events"][0]["terminal_terms"][term]=value
    bundle["persist_post"]()
    with pytest.raises(ValueError,match="DBRG_TERMINAL_SCOPE"):
        common.load_descriptive_authority(bundle["authority"])


def test_postverified94_six_seal_cannot_be_renamed_to_inherit_role(bundle,monkeypatch):
    from dataclasses import replace
    event=_postverified94(bundle,monkeypatch)
    value=admitted(bundle)
    binding=json.loads(value.research_cash_reconstruction_json);binding["task_id"]=common.TASK
    spoof=replace(value,research_cash_reconstruction_json=json.dumps(binding))
    with pytest.raises(ValueError,match="EXACT_TASK"):common.validate_reconstructed_accounting_events(spoof,[event])


def test_postverified94_terminal_is_nonspendable_and_extinguished_once(bundle,monkeypatch):
    from scripts.v22 import corporate_action_transition_r1 as ca
    event=_postverified94(bundle,monkeypatch,"terminal");value=admitted(bundle)
    def step(day,positions,state=None):
        return ca.apply_entitlement_lifecycle([event],positions,100.,execution_date=day,
            session_open_at=pd.Timestamp(day+"T13:30:00Z"),security_tickers={"secDBRG":"DBRG"},
            quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,state=state,enabled=True,
            descriptive_accounting_authority=value)
    first=step("2026-09-30",{"secDBRG":2.5})
    assert first.cash==100. and first.receivable_value_usd==40.
    assert first.positions["secDBRG"]==0.
    again=step("2026-10-01",first.positions,first.state)
    assert again.cash==100. and again.receivable_value_usd==40.
    fresh=step("2026-10-01",{})
    assert fresh.cash==100. and fresh.receivable_value_usd==0.


def _partial94(bundle,monkeypatch):
    monkeypatch.setattr(profile,"required_action_roles",lambda cid:("R6:duration",) if cid=="policy_1" else ())
    records={cid:dict(status="BLOCKED" if cid=="policy_1" else "QUALIFIED",
        reason="Missing historical parent5 availability" if cid=="policy_1" else "",
        required_action_roles=list(profile.required_action_roles(cid)),source_ref=bundle["bound"]["source_refs"]["action_inputs"])
        for cid in bundle["bound"]["allowed_path_ids"]}
    bundle["qualification"]["candidate_source_qualification"]=records
    bundle["qualification"]["groups"]["action_inputs"]=False
    bundle["persist_qualification"]()
    return records


def test_partial94_preserves_full_inventory_and_blocks_unqualified_runtime_unit(bundle,monkeypatch):
    _partial94(bundle,monkeypatch)
    value=common.load_descriptive_authority(bundle["authority"])
    assert len(value.allowed_path_ids)==94
    assert len(json.loads(value.provenance_json)["source_ready_policy_ids"])==93
    accepted=common.validate_descriptive_policy(value,[bundle["candidates"][0]["specification"]])
    assert accepted.runtime_policy_ids==("policy_0",)
    with pytest.raises(ValueError,match="SOURCE_NOT_QUALIFIED"):
        common.validate_descriptive_policy(value,[bundle["candidates"][1]["specification"]])


@pytest.mark.parametrize("fault",["omit","false_role","false_ref","pretend_all","no_reason","empty_ready","bad_status"])
def test_partial94_cannot_hide_source_gaps_or_change_role(bundle,monkeypatch,fault):
    records=_partial94(bundle,monkeypatch)
    if fault=="omit":del records["policy_1"]
    elif fault=="false_role":records["policy_1"]["required_action_roles"]=[]
    elif fault=="false_ref":records["policy_1"]["source_ref"]=bundle["bound"]["source_refs"]["market_quote"]
    elif fault=="pretend_all":bundle["qualification"]["groups"]["action_inputs"]=True
    elif fault=="no_reason":records["policy_1"]["reason"]=""
    elif fault=="empty_ready":
        for item in records.values():item.update(status="BLOCKED",reason="Unavailable")
    else:records["policy_1"]["status"]="SKIP_BY_SCORE"
    bundle["persist_qualification"]()
    with pytest.raises(ValueError):common.load_descriptive_authority(bundle["authority"])


@pytest.mark.parametrize("slot",["market_quote","security_identity","action_inputs","quote_quality"])
def test_postverified94_role_cannot_hide_behind_plausible_old_available_clock(bundle,monkeypatch,slot):
    _postverified94(bundle,monkeypatch)
    bundle["qualification"]["source_slices"][slot].update(clock_role="POST_VERIFIED_ACCOUNTING_ONLY",
        historical_available_at_bound=False,captured_at="2026-10-08T05:00:00Z")
    bundle["persist_post"]()
    with pytest.raises(ValueError,match="SCOPE_OUTSIDE_WINDOW"):
        common.load_descriptive_authority(bundle["authority"])


@pytest.mark.parametrize("slot",list(common.SOURCE_GROUPS))
def test_unknown_historical_clock_cannot_be_relabelled_as_known_by_filling_timestamp(bundle,slot):
    bundle["qualification"]["source_slices"][slot]["historical_available_at_bound"]=False
    bundle["persist_qualification"]()
    with pytest.raises(ValueError,match="SCOPE_OUTSIDE_WINDOW"):
        common.load_descriptive_authority(bundle["authority"])


@pytest.mark.parametrize("field,changed",[("clock_role","STRICT_PIT"),("production_qualified",True),
    ("strict_PIT_promotion_eligible",True)])
def test_postverified94_runtime_binding_flags_cannot_be_replaced(bundle,monkeypatch,field,changed):
    from dataclasses import replace
    event=_postverified94(bundle,monkeypatch);value=admitted(bundle)
    binding=json.loads(value.research_cash_reconstruction_json);binding[field]=changed
    spoof=replace(value,research_cash_reconstruction_json=json.dumps(binding))
    with pytest.raises(ValueError):common.validate_reconstructed_accounting_events(spoof,[event])


def test_partial94_empty_replacement_cannot_restore_all_policies(bundle,monkeypatch):
    from dataclasses import replace
    _partial94(bundle,monkeypatch)
    value=common.load_descriptive_authority(bundle["authority"])
    spoof=replace(value,runtime_policy_ids=("policy_1",),source_ready_policy_ids=())
    with pytest.raises(ValueError,match="CUSTODY_CHANGED"):
        profile.require_runtime_policy(spoof,("policy_1",))


_FROZEN_HISTORY_ROLE = "FROZEN_HISTORY_RESEARCH_OBSERVATIONS_NOT_HISTORICAL_DELIVERY_CERTIFICATION"


def frozen_history_qualification(bundle, keys=None):
    q = bundle["qualification"]
    q.update(original_plan_ref=bundle["contract"]["metadata_refs"]["plan"],
             strict_PIT_promotion_eligible=False, production_qualified=False,
             finalist_selected=False, new_fit=0)
    for key in (keys or [k for k in common.SOURCE_GROUPS if k != "corporate_actions"]):
        scope = q["source_slices"][key]
        scope.update(clock_role=_FROZEN_HISTORY_ROLE, source_clock_semantics=_FROZEN_HISTORY_ROLE,
                     available_at=None, historical_available_at_bound=False,
                     source_observation_fact_refs=[scope["source_ref"]])
    return q


def test_explicit_frozen_history_observation_role_is_descriptive_not_cash_or_H5(bundle):
    q = frozen_history_qualification(bundle)
    bundle["persist_qualification"]()
    value = admitted(bundle)
    provenance = json.loads(value.provenance_json)
    assert value.as_of == pd.Timestamp(bundle["docs"]["plan"]["as_of_utc"])
    assert provenance["source_gate_level"] == "DECLARED_SOURCE_CUSTODY_NOT_PIT_CERTIFICATION"
    assert all(provenance[k] is False for k in ("strict_PIT_promotion_eligible", "production_qualified"))
    assert provenance["post_verified_accounting_decision_ref"] is None
    assert value.research_cash_reconstruction_json == "{}"
    assert value.research_terminal_reconstruction_json == "{}"
    assert provenance["source_clock_roles"]["action_inputs"] == _FROZEN_HISTORY_ROLE
    assert all(q["source_slices"][k]["available_at"] is None
               for k in common.SOURCE_GROUPS if k != "corporate_actions")


@pytest.mark.parametrize("key", [k for k in common.SOURCE_GROUPS if k != "corporate_actions"])
@pytest.mark.parametrize("field,bad", [
    ("source_clock_semantics", "POST_VERIFIED_ACCOUNTING_ONLY"),
    ("available_at", "2026-01-01T00:00:00Z"),
    ("historical_available_at_bound", True),
    ("source_observation_fact_refs", []),
])
def test_frozen_history_role_rejects_fabricated_clocks_or_unbound_source_facts(bundle,key,field,bad):
    q = frozen_history_qualification(bundle)
    q["source_slices"][key][field] = bad
    bundle["persist_qualification"]()
    with pytest.raises(ValueError, match="A94_FROZEN_HISTORY"):
        admitted(bundle)


@pytest.mark.parametrize("field,bad", [
    ("original_plan_ref", {"path": "other-plan", "sha256": "0"*64}),
    ("strict_PIT_promotion_eligible", True), ("production_qualified", True),
    ("finalist_selected", True), ("new_fit", 1), ("new_fit", False),
])
def test_frozen_history_role_cannot_create_new_task_or_model_authority(bundle,field,bad):
    q = frozen_history_qualification(bundle)
    q[field] = bad
    bundle["persist_qualification"]()
    with pytest.raises(ValueError, match="A94_FROZEN_HISTORY"):
        admitted(bundle)


def test_frozen_history_role_cannot_authorize_cash_or_terminal_slot(bundle):
    frozen_history_qualification(bundle, ["corporate_actions"])
    bundle["persist_qualification"]()
    with pytest.raises(ValueError, match="A94_FROZEN_HISTORY"):
        admitted(bundle)


def test_frozen_history_fact_content_tamper_stops_before_model_load(bundle):
    q = frozen_history_qualification(bundle)
    leaf = Path(q["source_slices"]["action_inputs"]["source_observation_fact_refs"][0]["path"])
    bundle["persist_qualification"]()
    leaf.write_text('{"tampered":true}',encoding="utf-8")
    with pytest.raises(ValueError):
        admitted(bundle)


@pytest.fixture
def all_bundle(bundle, monkeypatch, tmp_path):
    """Independent small full census proves new scope is not fixed at94/111."""
    docs = copy.deepcopy(bundle["docs"])
    docs["plan"].update(task_id=profile.ALL_TASK,
        schema="ALL_FROZEN_A_AND_ACTUAL_DEMO_RANDOM2026_DESCRIPTIVE_PLAN_R1",
        as_of_utc="2026-10-09T03:46:22+00:00", A_scope={"no_new_combinations": True},
        constraints={k:0 for k in ("new_fit","calibration","parameter_search","policy_selection","new_strategy_combinations")})
    rows = docs["inventory"]["candidates"] = docs["inventory"]["candidates"][:3]
    for i,row in enumerate(rows):
        row.update(source_group="ORIGINAL_FAMILY", runtime_owner="STATEFUL_OVERLAY", required_action_roles=[],
            dependency_closure=dict(status="COMPLETE",state_ids=["old_value:ridge"],reason=None))
    rows[-1].update(runtime_owner="UNSUPPORTED_ORIGINAL_OWNER",
        dependency_closure=dict(status="BLOCKED",state_ids=["missing:original"],reason="ORIGINAL_FAILED_STATE"))
    docs["old_states"]["value_models"] = docs["old_states"]["value_models"][:2]
    docs["old_states"]["risk_models"] = []
    docs["new_states"]["model_states"] = docs["new_states"]["model_states"][:1]
    docs["new_states"]["external_scaler_states"] = []
    docs["schedule"] = profile.build_random_schedule(pd.bdate_range("2026-01-02","2026-10-08"),
        as_of=docs["plan"]["as_of_utc"], candidate_ids=[r["candidate_id"] for r in rows])
    monkeypatch.setattr(profile,"_ALL_ROOT",tmp_path)
    pins={}
    def freeze():
        for name,value in docs.items():
            ref=bundle["write"]("all_"+name+".json",value);pins[name]=("all_"+name+".json",ref["sha256"])
        monkeypatch.setattr(profile,"_ALL_PINS",dict(pins))
    freeze();contract=profile.profile_contract(profile.ALL_TASK)
    q=copy.deepcopy(bundle["qualification"]);b=copy.deepcopy(bundle["bound"])
    q.update(task_id=profile.ALL_TASK,as_of=docs["plan"]["as_of_utc"],common_calendar_start="2026-01-02",
        common_calendar_end="2026-10-08",candidate_source_qualification={r["candidate_id"]:dict(
            required_action_roles=[],source_ref=b["source_refs"]["action_inputs"],
            status="BLOCKED" if i==2 else "QUALIFIED",reason="ORIGINAL_FAILED_STATE" if i==2 else None)
            for i,r in enumerate(rows)})
    q["groups"]["action_inputs"]=False
    for v in q["source_slices"].values():v.update(content_end="2026-10-08",available_at="2026-10-09T01:00:00Z")
    b.update(task_id=profile.ALL_TASK,as_of=docs["plan"]["as_of_utc"],plan_ref=contract["metadata_refs"]["plan"],
        candidate_manifest_ref=contract["metadata_refs"]["inventory"],candidate_bindings=contract["candidate_bindings"],
        state_refs=contract["state_refs"],allowed_path_ids=[r["candidate_id"] for r in rows],
        schedule_ref=contract["metadata_refs"]["schedule"],windows=docs["schedule"]["windows"])
    a=dict(schema="A_2026_DESCRIPTIVE_AUTHORITY_REF_R1",task_id=profile.ALL_TASK,window_id="MAIN")
    def persist():
        b["source_qualification_ref"]=bundle["write"]("all_qualification.json",q)
        a["admission_ref"]=bundle["write"]("all_admission.json",b)
        return a
    persist()
    return dict(authority=a,bound=b,qualification=q,docs=docs,freeze=freeze,persist=persist,contract=contract,legacy=bundle)


def test_all_a_independent_full_census_keeps_blocked_and_legacy_pins(all_bundle):
    value=common.load_descriptive_authority(all_bundle["authority"])
    assert len(value.allowed_path_ids)==3 and len(value.source_ready_policy_ids)==2
    assert len(all_bundle["contract"]["state_refs"])==4
    assert profile.frozen_profile_contract()==all_bundle["legacy"]["contract"]
    with pytest.raises(ValueError,match="SOURCE_NOT_QUALIFIED"):
        common.validate_descriptive_policy(value,[all_bundle["docs"]["inventory"]["candidates"][-1]["specification"]])


def test_all_a_random_window_reuses_full_source_and_fresh_account(all_bundle):
    a=all_bundle["authority"];a["window_id"]="RANDOM_050"
    value=common.load_descriptive_authority(a)
    window=next(w for w in all_bundle["docs"]["schedule"]["windows"] if w["window_id"]==a["window_id"])
    assert value.start==pd.Timestamp(window["start"]) and value.end==pd.Timestamp("2026-10-08")
    assert value.feature_history_start==pd.Timestamp("2023-01-01")
    assert all_bundle["bound"]["initial_holdings"]==all_bundle["bound"]["initial_receivables"]==[]


@pytest.mark.parametrize("field",["start","first_execution_date","end","account_initialization","signal_context_start"])
def test_all_a_schedule_tampering_cannot_choose_another_random_window(all_bundle,field):
    all_bundle["bound"]["windows"]=copy.deepcopy(all_bundle["bound"]["windows"])
    all_bundle["bound"]["windows"][1][field]="2026-02-12"
    all_bundle["persist"]()
    with pytest.raises(ValueError,match="EXACT_RANDOM_SCHEDULE"):
        common.load_descriptive_authority(all_bundle["authority"])


def test_all_a_missing_freeze_and_closed_state_are_not_generic_permissions(all_bundle,monkeypatch):
    monkeypatch.setattr(profile,"_ALL_PINS",{"plan":profile._ALL_PINS["plan"]})
    with pytest.raises(ValueError,match="PROFILE_NOT_FROZEN"):
        profile.profile_contract(profile.ALL_TASK)
    with pytest.raises(ValueError,match="EXACT_TASK"):
        profile.profile_contract("A_ALL_OTHER")


def test_all_a_missing_dependency_cannot_be_relabelled_complete(all_bundle):
    all_bundle["docs"]["inventory"]["candidates"][0]["dependency_closure"]["state_ids"]=["absent"]
    all_bundle["freeze"]()
    with pytest.raises(ValueError,match="COMPLETE_DEPENDENCIES"):
        profile.profile_contract(profile.ALL_TASK)


def test_all_a_blocked_original_owner_cannot_receive_source_pass(all_bundle):
    q=all_bundle["qualification"];q["groups"]["action_inputs"]=True
    q["candidate_source_qualification"]["policy_2"]["status"]="QUALIFIED"
    all_bundle["persist"]()
    with pytest.raises(ValueError,match="UNCLOSED_POLICY"):
        common.load_descriptive_authority(all_bundle["authority"])


def test_all_a_dates_are_identical_to_original_six_path_selection():
    from scripts.research.a2.evaluation import stateful_frozen_six_path as six
    dates=pd.bdate_range("2026-01-02","2026-10-08");asof="2026-10-09T03:46:22Z"
    old=six.build_schedule(dates,as_of=asof)
    new=profile.build_random_schedule(dates,as_of=asof,candidate_ids=["A","B","ORIGINAL_FAILED"])
    assert new["windows"]==old["windows"] and new["account_paths"]==303
    assert new["random_start_count"]==100 and all(w["execution_sessions"]>=20 for w in new["windows"][1:])


@pytest.fixture
def consensus_all_bundle(all_bundle, monkeypatch):
    b = all_bundle; write = b["legacy"]["write"]; docs = b["docs"]
    rule = dict(selection_rule="MANAGER_COUNT_WEIGHT_SUM", rank_column="consensus_rank", size=100)
    parent = write("consensus_parent.json", dict(universe_change=rule))
    manifest = write("consensus_source.json", dict(universe_change=rule))
    amendment = write("scope_amendment.json", dict(task_id=profile.ALL_TASK, authorized=True))
    monkeypatch.setattr(profile,"_CONSENSUS_SOURCE_REF",manifest)
    docs["plan"]["A_scope"] = dict(universe_variant="CONSENSUS100",universe_application_authorized=True,
        no_new_algorithm_combinations=True,universe_contract_ref=parent,universe_rule=rule)
    docs["plan"]["scope_amendment_ref"] = amendment
    plan_ref = write("all_plan.json",docs["plan"])
    original_ref = dict(path=str(profile._ROOT/profile._PINS["raw_selector"][0]),sha256=profile._PINS["raw_selector"][1])
    docs["raw_selector"].update(schema="ALL_A_CONSENSUS100_FROZEN_RAW_SELECTOR_APPLICATION_SCOPE_R2",
        task_id=profile.ALL_TASK,plan_ref=plan_ref,scope_amendment_ref=amendment,
        consensus_contract_ref=parent,training_source_original24_audit_ref=original_ref,
        application_pool_origin="CONSENSUS_TOP100_FULL_PIT32_APPLICATION_POOL",new_model_or_fit=False,
        pre2026_training_identity_unchanged=True,original_contract=rule)
    b["freeze"]()
    return b


def test_consensus_application_keeps_training_and_legacy_profile(consensus_all_bundle):
    b=consensus_all_bundle;c=profile.profile_contract(profile.ALL_TASK)
    assert c["raw_selector_binding"]["application_pool_origin"]=="CONSENSUS_TOP100_FULL_PIT32_APPLICATION_POOL"
    assert c["raw_selector_binding"]["universe_source_ref"]==profile._CONSENSUS_SOURCE_REF
    assert c["raw_selector_binding"]["model_ref"]==b["contract"]["raw_selector_binding"]["model_ref"]
    assert profile.frozen_profile_contract()==b["legacy"]["contract"]


@pytest.mark.parametrize("bad",["authority","origin","source_rule","model","amendment"])
def test_consensus_application_rejects_unbound_or_changed_scope(consensus_all_bundle,bad):
    b=consensus_all_bundle;d=b["docs"]
    if bad=="authority":d["plan"]["A_scope"]["universe_application_authorized"]=False
    elif bad=="origin":d["raw_selector"]["application_pool_origin"]="ORIGINAL_24_MANAGER_FULL_PIT32_INFERENCE_POOL"
    elif bad=="source_rule":d["raw_selector"]["original_contract"]["size"]=101
    elif bad=="model":d["raw_selector"]["same_model_not_same_universe"]["ordered_32_features"][0]="REPLACED"
    else:d["raw_selector"]["scope_amendment_ref"]={"path":"unbound","sha256":"0"*64}
    d["raw_selector"]["plan_ref"]=b["legacy"]["write"]("all_plan.json",d["plan"])
    b["freeze"]()
    with pytest.raises(ValueError,match="ALL_A_"):profile.profile_contract(profile.ALL_TASK)


@pytest.fixture
def benchmark_bundle(all_bundle, monkeypatch):
    b=all_bundle; write=b["legacy"]["write"]; contract=profile.profile_contract(profile.ALL_TASK)
    rows=[]
    for cid in common.PATH_IDS[4:]:
        rows.append(dict(candidate_id=cid,scientific_tuple_sha256=sha(cid.encode()),
            benchmark_contract=dict(ticker=cid.split("_")[0],policy="BUY_AND_HOLD"),
            execution_friction=copy.deepcopy(b["docs"]["inventory"]["candidates"][0]["specification"]["execution_friction"])))
    monkeypatch.setattr(profile,"benchmark_candidates",lambda c:copy.deepcopy(rows))
    sr=write("benchmark_source.json",dict(task_id=profile.ALL_TASK,universe_variant="CONSENSUS100",
        plan_ref=contract["metadata_refs"]["plan"],account_catalog_ref=b["bound"]["source_refs"]["corporate_actions"],
        bars_ref=write("bars.json",dict(synthetic=True))))
    monkeypatch.setattr(profile,"_BENCHMARK_SOURCE_REF",sr)
    ar=write("benchmark_action_source.json",dict(source_bundle_ref=sr))
    b["bound"]["source_refs"]["action_inputs"]=ar
    b["qualification"]["source_refs"]["action_inputs"]=ar
    b["qualification"]["source_slices"]["action_inputs"]["source_ref"]=ar
    for row in b["qualification"]["candidate_source_qualification"].values():row["source_ref"]=ar
    b["persist"]()
    source=json.loads(Path(sr["path"]).read_text())
    q=dict(schema="A_ALL_TWO_BENCHMARK_SOURCE_QUALIFICATION_R1",task_id=profile.ALL_TASK,source_bundle_ref=sr,
        source_refs=b["bound"]["source_refs"],groups=dict.fromkeys(common.SOURCE_GROUPS,True),
        action_inputs_scope="ORIGINAL_BUY_AND_HOLD_NO_MODEL_INPUT",common_sessions=contract["schedule"]["common_sessions"],
        bars_ref=source["bars_ref"],fresh_cash_usd=3000,initial_holdings=[],initial_receivables=[],one_way_bps=10,
        terminal_liquidation=False,source_fact_refs=[source["bars_ref"]])
    x=dict(schema="A_ALL_BENCHMARK_ACCOUNT_ADMISSION_R1",task_id=profile.ALL_TASK,plan_ref=contract["metadata_refs"]["plan"],
        schedule_ref=contract["metadata_refs"]["schedule"],windows=contract["schedule"]["windows"],account_execution_allowed=True,
        strict_PIT_promotion_eligible=False,production_qualified=False,finalist_selected=False,new_fit=0,
        source_bundle_ref=sr,verified_source_authority_ref=copy.deepcopy(b["authority"]),allowed_path_ids=list(common.PATH_IDS[4:]),candidates=rows)
    a=dict(schema="A_ALL_BENCHMARK_AUTHORITY_REF_R1",task_id=profile.ALL_TASK,window_id="MAIN")
    def persist():
        x["source_qualification_ref"]=write("benchmark_q.json",q);a["admission_ref"]=write("benchmark_admission.json",x);return a
    persist();return dict(original=b,rows=rows,q=q,bound=x,authority=a,persist=persist)


def test_benchmark_closed_capability_and_fresh_random_window(benchmark_bundle):
    b=benchmark_bundle;v=common.load_descriptive_authority(b["authority"])
    assert v.allowed_path_ids==common.PATH_IDS[4:]
    with pytest.raises(ValueError,match="NOT_REGISTERED"):
        common.require_descriptive_decision(v,"2026-01-05",b["original"]["docs"]["inventory"]["candidates"][0]["candidate_id"])
    v=common.validate_descriptive_policy(v,b["rows"])
    random=profile.benchmark_window_authority(v,"RANDOM_050")
    assert random.start>v.start and random.end==v.end and random.runtime_policy_ids==v.runtime_policy_ids
    with pytest.raises(ValueError,match="FROZEN_WINDOW"):
        profile.benchmark_window_authority(v,"RANDOM_101")
    old=common.load_descriptive_authority(b["original"]["authority"])
    assert len(old.allowed_path_ids)==3 and not set(old.allowed_path_ids)&set(common.PATH_IDS[4:])
    with pytest.raises(ValueError,match="NOT_REGISTERED"):
        common.require_descriptive_decision(old,"2026-01-05",common.PATH_IDS[4])
    with pytest.raises(ValueError,match="CAPABILITY_REQUIRED"):
        profile.benchmark_window_authority(old,"MAIN")


@pytest.mark.parametrize("bad",["path","window","cost","initial","gate","gate_integer","source","policy"])
def test_benchmark_rejects_scope_or_source_substitution(benchmark_bundle,bad):
    b=benchmark_bundle
    if bad=="path":b["bound"]["allowed_path_ids"].append("A_STOCK")
    elif bad=="window":b["bound"]["windows"]=copy.deepcopy(b["bound"]["windows"]);b["bound"]["windows"][0]["start"]="2026-01-01"
    elif bad=="cost":b["q"]["one_way_bps"]=5
    elif bad=="initial":b["q"]["initial_receivables"]=[dict(amount=1)]
    elif bad=="gate":b["q"]["groups"]["market_quote"]=False
    elif bad=="gate_integer":b["q"]["groups"]["market_quote"]=1
    elif bad=="source":b["bound"]["source_bundle_ref"]=dict(path="unbound",sha256="0"*64)
    else:b["bound"]["candidates"]=copy.deepcopy(b["rows"]);b["bound"]["candidates"][0]["benchmark_contract"]["policy"]="TIMING"
    b["persist"]()
    with pytest.raises(ValueError):common.load_descriptive_authority(b["authority"])
