"""Synthetic variant custody regressions; no real models or market files."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import pandas as pd
import pytest
from scripts.research.a2.evaluation import frozen_test_authority as a
from scripts.research.a2.evaluation import stateful_frozen_six_path as six

ROOT=Path(__file__).resolve().parents[4]
spec=importlib.util.spec_from_file_location("_aggregate_custody_fixture",
    ROOT/"tests/research/a2/evaluation/test_continuous_research_account.py")
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
descriptive_fixture=fixtures.descriptive_fixture


@pytest.fixture
def variant(descriptive_fixture,monkeypatch):
    root,bound,_,qualification=descriptive_fixture
    bound=deepcopy(bound);q=deepcopy(qualification)
    write=lambda name,value:fixtures._synthetic_ref(root/name,value)
    plan=json.loads(Path(bound["plan_ref"]["path"]).read_text())
    plan.update(task_id=a.AGGREGATE_TASK,status="DESIGN_FIXED_BEFORE_NEW_UNIVERSE_POLICY_REPLAY",
        test_interval=["2026-01-01","2027-01-01"],budget=dict(new_fit=0),
        universe_change=dict(selection="SYNTHETIC_FULL_AGGREGATE_TOP100"))
    pref=write("variant_plan.json",plan)
    monkeypatch.setattr(a,"AGGREGATE_PLAN_SHA256",pref["sha256"])
    uref=write("universe.json",dict(task_id=a.AGGREGATE_TASK,synthetic=True,
        source_refs=dict(evaluation_plan=pref),universe_change=plan["universe_change"]))
    rref=write("raw_model.json",dict(synthetic=True))
    monkeypatch.setattr(a,"RAW_SELECTOR_SHA256",rref["sha256"])
    lref=write("review.json",dict(task_id=a.AGGREGATE_TASK,synthetic=True,plan_ref=pref,
        schema="A_UNIVERSE_VARIANT_SOURCE_LINEAGE_REVIEW_R1",independent=True,
        status="STRUCTURAL_NONREDUNDANCY_SUPPORTED_EXECUTION_QUALIFICATION_PENDING"))
    bound.update(task_id=a.AGGREGATE_TASK,plan_ref=pref,universe_source_ref=uref,
        raw_selector_ref=rref,lineage_review_ref=lref)
    q.update(task_id=a.AGGREGATE_TASK,plan_ref=pref,universe_source_ref=uref,
        raw_selector_ref=rref,lineage_review_ref=lref)
    bound["source_qualification_ref"]=write("variant_qualification.json",q)
    candidates=json.loads(Path(bound["candidate_manifest_ref"]["path"]).read_text())
    candidates["task_id"]=a.AGGREGATE_TASK
    for row in candidates["candidates"]:
        row["original_policy_tuple_sha256"]=row["scientific_tuple_sha256"]
        row["variant_evaluation_tuple_sha256"]=a.aggregate_evaluation_tuple(pref,row["scientific_tuple_sha256"])
    bound["candidate_manifest_ref"]=write("variant_candidates.json",candidates)
    def ref(value=None):
        return dict(schema="A_2026_DESCRIPTIVE_AUTHORITY_REF_R1",task_id=a.AGGREGATE_TASK,
            admission_ref=write("variant_admission.json",bound if value is None else value),window_id="MAIN")
    return root,bound,q,candidates,ref,write


def test_variant_retains_separate_identity_and_original_account_limits(variant):
    root,bound,q,candidates,ref,write=variant
    admitted=a.load_descriptive_authority(ref())
    assert admitted.task_id==a.AGGREGATE_TASK
    p=json.loads(admitted.provenance_json)
    assert p["reused_policy_identity_is_not_full_evaluation_identity"] is True
    assert p["universe_source_ref"]==bound["universe_source_ref"]
    assert len(p["variant_evaluation_tuples"])==6
    a.require_descriptive_decision(admitted,"2026-01-05","RAW_s10")
    with pytest.raises(ValueError,match="DECISION_OUTSIDE_WINDOW"):
        a.require_descriptive_decision(admitted,"2025-12-31","RAW_s10")
    with pytest.raises(ValueError,match="FIXED_10BPS"):
        a.validate_descriptive_account(admitted,pd.bdate_range("2026-01-02","2026-01-08"),
            ["RAW_s10"],dict(initial_nav=3000),dict(one_way_bps=5))


@pytest.mark.parametrize("field",["universe_source_ref","raw_selector_ref","lineage_review_ref"])
def test_variant_requires_independent_physical_input_binding(variant,field):
    root,bound,q,candidates,ref,write=variant
    changed=deepcopy(bound);changed.pop(field)
    with pytest.raises(ValueError,match="AGGREGATE|DESCRIPTIVE"):
        a.load_descriptive_authority(ref(changed))


def test_parent_qualification_cannot_admit_new_pool(variant):
    root,bound,q,candidates,ref,write=variant
    q["task_id"]=a.TASK
    bound["source_qualification_ref"]=write("variant_qualification.json",q)
    with pytest.raises(ValueError,match="SOURCE_QUALIFICATION_UNBOUND"):
        a.load_descriptive_authority(ref())


@pytest.mark.parametrize("field",["original_policy_tuple_sha256","variant_evaluation_tuple_sha256"])
def test_old_component_identity_cannot_impersonate_changed_question(variant,field):
    root,bound,q,candidates,ref,write=variant
    candidates["candidates"][0][field]="0"*64
    bound["candidate_manifest_ref"]=write("variant_candidates.json",candidates)
    with pytest.raises(ValueError,match="SCIENTIFIC_QUESTION_IDENTITY_CHANGED"):
        a.load_descriptive_authority(ref())


def test_changed_universe_bytes_rejected_before_account(variant):
    root,bound,q,candidates,ref,write=variant
    Path(bound["universe_source_ref"]["path"]).write_text("{}")
    with pytest.raises(ValueError,match="SOURCE_SHA_CHANGED"):
        a.load_descriptive_authority(ref())


def test_false_source_group_still_blocks_variant(variant):
    root,bound,q,candidates,ref,write=variant
    q["groups"]["market_quote"]=False
    bound["source_qualification_ref"]=write("variant_qualification.json",q)
    with pytest.raises(ValueError,match="SOURCE_GATE_NOT_TRUE"):
        a.load_descriptive_authority(ref())


def test_variant_schedule_preserves_calendar_selection():
    dates=pd.bdate_range("2026-01-02","2026-10-07")
    args=dict(as_of="2026-10-07T21:00:00Z")
    original=six.build_schedule(dates,**args)
    variant=six.build_schedule(dates,task_id=a.AGGREGATE_TASK,**args)
    assert original["windows"]==variant["windows"]
    assert variant["account_paths"]==606
    assert variant["task_id"]==a.AGGREGATE_TASK
    with pytest.raises(ValueError,match="EXACT_TASK"):
        six.build_schedule(dates,task_id="ARBITRARY_TASK",**args)


@pytest.mark.parametrize("slot,field,value",[
    ("universe_source_ref","universe_change",{"selection":"PER_MANAGER_TOP100_UNION"}),
    ("universe_source_ref","source_refs",{}),
    ("lineage_review_ref","status","FAIL"),
    ("lineage_review_ref","independent",False),
    ("lineage_review_ref","plan_ref",{})])
def test_relabelled_or_unreviewed_evidence_rejected(variant,slot,field,value):
    root,bound,q,candidates,ref,write=variant
    document=json.loads(Path(bound[slot]["path"]).read_text())
    document[field]=value
    changed=write(Path(bound[slot]["path"]).name,document)
    bound[slot]=changed;q[slot]=changed
    bound["source_qualification_ref"]=write("variant_qualification.json",q)
    with pytest.raises(ValueError,match="AGGREGATE"):
        a.load_descriptive_authority(ref())


spec_six=importlib.util.spec_from_file_location("_aggregate_durable_fixture",
    ROOT/"tests/research/a2/evaluation/test_stateful_frozen_six_path.py")
fixture_six=importlib.util.module_from_spec(spec_six);spec_six.loader.exec_module(fixture_six)
durable_case=fixture_six.durable_case


def test_variant_reuses_durable_owner_with_own_plan_and_no_duplicate_replay(durable_case,monkeypatch):
    from types import SimpleNamespace
    old_run,schedule,kwargs,attempts=durable_case
    run=old_run.parent.parent/a.AGGREGATE_TASK/"SYNTHETIC_EXISTING_RUN"
    run.mkdir(parents=True)
    cfg=json.loads((old_run/"run_config.json").read_text())
    cfg["strategy_id"]=a.AGGREGATE_TASK
    (run/"run_config.json").write_text(json.dumps(cfg))
    schedule["task_id"]=a.AGGREGATE_TASK
    kwargs["expected_run_config_sha256"]=six.sha256(run/"run_config.json")
    monkeypatch.setattr(a,"load_descriptive_authority",lambda w:SimpleNamespace(
        task_id=a.AGGREGATE_TASK,window_id=w["window_id"],start=pd.Timestamp(w["start"]),end=pd.Timestamp(w["end"])))
    reports=six.execute_durable(run,schedule,fixture_six.policies(),**kwargs)
    binding=json.loads((run/"SIX_PATH_EXECUTION_BINDING.json").read_text())
    assert binding["task_id"]==a.AGGREGATE_TASK
    assert binding["plan_sha256"]==a.AGGREGATE_PLAN_SHA256
    assert len(reports)==len(attempts)==6
    before=(run/"ACCOUNT_PATH_LOG.jsonl").read_bytes()
    assert six.execute_durable(run,schedule,fixture_six.policies(),**kwargs)==reports
    assert len(attempts)==6 and (run/"ACCOUNT_PATH_LOG.jsonl").read_bytes()==before


# The aggregate universe variant reuses ordinary post-verified cash only.
# Unknown terminal publication remains exclusive to its original parent task.
def _variant_cash_fixture(variant):
    root, bound, qualification, _, ref, _ = variant
    return root, bound, ref, qualification


@pytest.mark.parametrize("source_type", [
    "TIER1_ISSUER_REGULATOR_EXCHANGE", "TIER2_LOCAL_CANONICAL", "TIER3_VENDOR_METADATA"])
def test_variant_ordinary_cash_preserves_original_sources_and_lifecycle(variant, source_type):
    from dataclasses import replace
    from scripts.v22 import corporate_action_transition_r1 as ca
    fixture = _variant_cash_fixture(variant)
    event = replace(fixtures._postverified_event(fixture), source_type=source_type)
    admitted, _ = fixtures._postverified_bind(fixture, [event])
    a.validate_reconstructed_accounting_events(admitted, [event], require_exact=True)

    def step(day, positions, cash=100., state=None):
        return ca.apply_entitlement_lifecycle([event], positions, cash,
            execution_date=day, session_open_at=day+"T14:30:00Z",
            security_tickers={"secS":"S"}, quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,
            state=state, enabled=True, descriptive_accounting_authority=admitted)
    ex = step("2026-01-06", {"secS":2.5})
    assert ex.cash == 100 and ex.receivable_value_usd == 25
    assert all(r["publication_available_at"] is None for r in ex.records)
    before_pay = step("2026-01-07", {}, ex.cash, ex.state)
    assert before_pay.cash == 100 and before_pay.receivable_value_usd == 25
    paid = step("2026-01-08", {}, before_pay.cash, before_pay.state)
    assert paid.cash == 125 and paid.receivable_value_usd == 0

    # A vendor label cannot be promoted after admission to impersonate an issuer.
    relabelled = replace(event, source_type=(
        "TIER2_LOCAL_CANONICAL" if source_type=="TIER1_ISSUER_REGULATOR_EXCHANGE"
        else "TIER1_ISSUER_REGULATOR_EXCHANGE"))
    with pytest.raises(ValueError, match="EVENT_CHANGED"):
        a.validate_reconstructed_accounting_events(admitted, [relabelled], require_exact=True)
    terminal = fixtures._postverified_event(fixture, "terminal")
    with pytest.raises(ValueError, match="TERMINAL"):
        replace(terminal, source_type="TIER3_VENDOR_METADATA")


def test_variant_cash_reuses_shared_account_without_spending_receivable(variant):
    from dataclasses import replace
    fixture = _variant_cash_fixture(variant)
    event = replace(fixtures._postverified_event(fixture), source_type="TIER3_VENDOR_METADATA")
    admitted, _ = fixtures._postverified_bind(fixture, [event])
    observed = []
    replay = fixtures.run_continuous_account(
        fixtures.market(fixtures._descriptive_market().dates, [100,100,90,90,90]),
        ["RAW_s10"], fixtures.buy_then_hold(observed), fixtures.config(),
        execution_friction=fixtures._descriptive_friction(),
        descriptive_evaluation_authority=admitted,
        **fixtures._postverified_account_args([event]))
    quantity = replay.fills.fractional_shares.iloc[0]
    pending = replay.daily.loc[replay.daily.date.isin(pd.to_datetime(["2026-01-06","2026-01-07"]))]
    assert pending.entitlement_cash_flow_usd.eq(0).all()
    assert pending.receivable_value_usd.tolist() == pytest.approx([quantity*10]*2)
    assert pending.cash.nunique() == 1
    assert replay.daily.entitlement_cash_flow_usd.sum() == pytest.approx(quantity*10)
    assert replay.daily.nav_identity_error.abs().max() < 1e-8
    assert replay.entitlements.publication_available_at.isna().all()
    assert replay.metadata["cash_publication_clock_reconstructed"] is False
    assert replay.metadata["strict_PIT_promotion_eligible"] is False


@pytest.mark.parametrize("fault", ["parent_binding", "terminal_binding", "false_ca_gate",
                                  "changed_source_bytes", "omit_events"])
def test_variant_cash_requires_own_custody_and_does_not_expand_terminal(variant, fault):
    fixture = _variant_cash_fixture(variant)
    root, original, ref, qualification = fixture
    event = fixtures._postverified_event(fixture)
    if fault == "terminal_binding":
        with pytest.raises(ValueError, match="POST_VERIFIED_EXACT_TASK"):
            fixtures._postverified_bind(fixture, [fixtures._postverified_event(fixture,"terminal")])
        return
    admitted, bound = fixtures._postverified_bind(fixture, [event])
    if fault == "omit_events":
        with pytest.raises(ValueError, match="CATALOGUE_CHANGED"):
            fixtures.run_continuous_account(fixtures._descriptive_market(), ["RAW_s10"],
                fixtures.buy_then_hold(), fixtures.config(),
                execution_friction=fixtures._descriptive_friction(),
                descriptive_evaluation_authority=admitted)
        return
    if fault == "changed_source_bytes":
        Path(event.reconstruction_ref).write_text("mutated", encoding="utf-8")
    elif fault == "false_ca_gate":
        q = json.loads(Path(bound["source_qualification_ref"]["path"]).read_text())
        q["groups"]["corporate_actions"] = False
        bound["source_qualification_ref"] = fixtures._synthetic_ref(root/"qualification.json", q)
    else:
        key = "research_cash_reconstruction"
        bound[key]["task_id"] = a.TASK
        bound["source_refs"]["corporate_actions"] = fixtures._synthetic_ref(
            root/"corporate_actions.json", {key:bound[key]})
        q = deepcopy(qualification); q["source_refs"] = deepcopy(bound["source_refs"])
        bound["source_qualification_ref"] = fixtures._synthetic_ref(root/"qualification.json", q)
    with pytest.raises(ValueError, match="DESCRIPTIVE"):
        a.load_descriptive_authority(ref(bound))


@pytest.fixture
def consensus(variant, monkeypatch):
    """Own consensus source/admission, with the amount task's exact parent windows."""
    root,bound,q,candidates,_,write=variant
    parent_ref=bound["plan_ref"]
    parent= six.build_schedule(pd.bdate_range("2026-01-02","2026-01-08"),
        as_of="2026-01-08T21:00:00Z",task_id=a.AGGREGATE_TASK)
    schedule_ref=write("amount_schedule.json",parent)
    monkeypatch.setattr(a,"CONSENSUS_PARENT_SCHEDULE_SHA256",schedule_ref["sha256"])
    plan=json.loads(Path(parent_ref["path"]).read_text())
    plan.update(task_id=a.CONSENSUS_TASK,parent_contract_ref=parent_ref,
        universe_change=dict(selection_rule="MANAGER_COUNT_WEIGHT_SUM",
            new_selection="DISTINCT_MANAGER_COUNT_DESC_WEIGHT_SUM_DESC_CUSIP_ASC_TOP100",
            rank_column="consensus_rank"))
    plan.setdefault("comparison",{})["exact_window_source_ref"]=schedule_ref
    pref=write("consensus_plan.json",plan)
    monkeypatch.setattr(a,"CONSENSUS_PLAN_SHA256",pref["sha256"])
    uref=write("consensus_universe.json",dict(task_id=a.CONSENSUS_TASK,synthetic=True,
        source_refs=dict(evaluation_plan=pref),universe_change=plan["universe_change"]))
    lref=write("consensus_review.json",dict(task_id=a.CONSENSUS_TASK,synthetic=True,plan_ref=pref,
        schema="A_UNIVERSE_VARIANT_SOURCE_LINEAGE_REVIEW_R1",independent=True,
        status="STRUCTURAL_NONREDUNDANCY_SUPPORTED_EXECUTION_QUALIFICATION_PENDING"))
    bound.update(task_id=a.CONSENSUS_TASK,plan_ref=pref,universe_source_ref=uref,lineage_review_ref=lref)
    q.update(task_id=a.CONSENSUS_TASK,plan_ref=pref,universe_source_ref=uref,lineage_review_ref=lref)
    bound["source_qualification_ref"]=write("consensus_qualification.json",q)
    candidates["task_id"]=a.CONSENSUS_TASK
    for row in candidates["candidates"]:
        row["variant_evaluation_tuple_sha256"]=a.aggregate_evaluation_tuple(pref,row["scientific_tuple_sha256"])
    bound["candidate_manifest_ref"]=write("consensus_candidates.json",candidates)
    def ref(value=None):
        return dict(schema="A_2026_DESCRIPTIVE_AUTHORITY_REF_R1",task_id=a.CONSENSUS_TASK,
            admission_ref=write("consensus_admission.json",bound if value is None else value),window_id="MAIN")
    return root,bound,q,candidates,ref,write


def test_consensus_admission_preserves_policy_and_exact_parent_windows(consensus):
    _,bound,_,candidates,ref,_=consensus
    admitted=a.load_descriptive_authority(ref())
    assert admitted.task_id==a.CONSENSUS_TASK
    assert admitted.start==pd.Timestamp("2026-01-02")
    assert admitted.end==pd.Timestamp("2026-01-08")
    for row in candidates["candidates"]:
        assert row["original_policy_tuple_sha256"]==row["scientific_tuple_sha256"]
        assert row["variant_evaluation_tuple_sha256"]!=a.aggregate_evaluation_tuple(
            {"sha256":a.AGGREGATE_PLAN_SHA256},row["scientific_tuple_sha256"])
    changed=deepcopy(bound);changed["windows"][0]["start"]="2026-01-05"
    with pytest.raises(ValueError,match="CONSENSUS_WINDOW_CHANGED"):
        a.load_descriptive_authority(ref(changed))


def test_consensus_plan_and_source_cannot_be_amount_relabel(consensus,monkeypatch):
    _,bound,q,_,ref,write=consensus
    plan=json.loads(Path(bound["plan_ref"]["path"]).read_text())
    plan["universe_change"]["rank_column"]="amount_rank"
    pref=write("consensus_wrong_rank.json",plan)
    monkeypatch.setattr(a,"CONSENSUS_PLAN_SHA256",pref["sha256"])
    with pytest.raises(ValueError,match="CONSENSUS_FROZEN_SELECTION"):
        a.six_path_plan(pref)


def test_consensus_schedule_inherits_without_resampling_and_rejects_changed_dates(consensus):
    _,bound,_,_,_,_=consensus
    plan=json.loads(Path(bound["plan_ref"]["path"]).read_text())
    ref=plan["comparison"]["exact_window_source_ref"]
    parent=json.loads(Path(ref["path"]).read_text())
    dates=pd.bdate_range("2026-01-02","2026-01-09")
    actual=six.build_schedule(dates,as_of="2026-01-09T22:00:00Z",
        task_id=a.CONSENSUS_TASK,inherited_schedule_ref=ref)
    assert actual["windows"]==parent["windows"] and actual["common_end"]=="2026-01-08"
    assert actual["parent_schedule_ref"]==ref
    changed=deepcopy(actual);changed["windows"][0]["end"]="2026-01-09"
    with pytest.raises(ValueError,match="CONSENSUS_FROZEN_SCHEDULE_CHANGED"):
        six._schedule_keys(changed)
    with pytest.raises(ValueError,match="CONSENSUS_EXACT_PARENT_SCHEDULE"):
        six.build_schedule(dates,as_of="2026-01-09T22:00:00Z",task_id=a.CONSENSUS_TASK)
    with pytest.raises(ValueError,match="CONSENSUS_PARENT_WINDOW_COVERAGE"):
        six.build_schedule(dates.delete(2),as_of="2026-01-09T22:00:00Z",
            task_id=a.CONSENSUS_TASK,inherited_schedule_ref=ref)


@pytest.mark.parametrize("source_type",[
    "TIER1_ISSUER_REGULATOR_EXCHANGE","TIER2_LOCAL_CANONICAL","TIER3_VENDOR_METADATA"])
def test_consensus_reuses_ordinary_cash_and_keeps_terminal_boundary(consensus,source_type):
    test_variant_ordinary_cash_preserves_original_sources_and_lifecycle(consensus,source_type)


def test_consensus_full_account_cash_keeps_receivable_nonspendable(consensus):
    test_variant_cash_reuses_shared_account_without_spending_receivable(consensus)


@pytest.mark.parametrize("fault",["parent_binding","terminal_binding","false_ca_gate","changed_source_bytes","omit_events"])
def test_consensus_cash_custody_failures_remain_closed(consensus,fault):
    test_variant_cash_requires_own_custody_and_does_not_expand_terminal(consensus,fault)


def test_consensus_durable_reuses_exact_parent_schedule_and_never_replays(durable_case, monkeypatch):
    from types import SimpleNamespace
    old_run, parent, kwargs, attempts = durable_case
    parent["task_id"] = a.AGGREGATE_TASK
    parent_path = old_run.parent.parent / "SYNTHETIC_AMOUNT_SCHEDULE.json"
    parent_path.write_text(json.dumps(parent), encoding="utf-8")
    pref = dict(path=str(parent_path), sha256=six.sha256(parent_path))
    monkeypatch.setattr(a, "CONSENSUS_PARENT_SCHEDULE_SHA256", pref["sha256"])
    schedule = six.build_schedule(pd.bdate_range("2026-01-02", periods=5),
        as_of="2026-01-08T22:00:00Z", task_id=a.CONSENSUS_TASK, inherited_schedule_ref=pref)
    run = old_run.parent.parent / a.CONSENSUS_TASK / "SYNTHETIC_EXISTING_RUN"
    run.mkdir(parents=True)
    cfg = json.loads((old_run / "run_config.json").read_text(encoding="utf-8"))
    cfg["strategy_id"] = a.CONSENSUS_TASK
    (run / "run_config.json").write_text(json.dumps(cfg), encoding="utf-8")
    kwargs["expected_run_config_sha256"] = six.sha256(run / "run_config.json")
    monkeypatch.setattr(a, "load_descriptive_authority", lambda w: SimpleNamespace(
        task_id=a.CONSENSUS_TASK, window_id=w["window_id"],
        start=pd.Timestamp(w["start"]), end=pd.Timestamp(w["end"])))
    reports = six.execute_durable(run, schedule, fixture_six.policies(), **kwargs)
    binding = json.loads((run / "SIX_PATH_EXECUTION_BINDING.json").read_text(encoding="utf-8"))
    assert binding["task_id"] == a.CONSENSUS_TASK
    assert binding["plan_sha256"] == a.CONSENSUS_PLAN_SHA256
    assert schedule["windows"] == parent["windows"]
    assert len(reports) == len(attempts) == 6
    before = (run / "ACCOUNT_PATH_LOG.jsonl").read_bytes()
    assert six.execute_durable(run, schedule, fixture_six.policies(), **kwargs) == reports
    assert len(attempts) == 6 and (run / "ACCOUNT_PATH_LOG.jsonl").read_bytes() == before
