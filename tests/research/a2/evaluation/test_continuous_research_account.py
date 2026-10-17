"""Synthetic focused checks for the thin immutable-engine adapter."""
import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.evaluation.continuous_research_account import run_continuous_account,account_prefix_identity
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays,TargetDecision
from scripts.v22.corporate_action_transition_r1 import CorporateActionTransition


def config(capital=3000):
    return dict(base_currency="USD",initial_nav=capital,initial_cash=capital,initial_holdings=[],
        fractional_shares=True,integer_share_rounding=False,cash_interest=0,transaction_cost_bps=0,
        financing=False,borrowed_cash=False,long_only=True,max_positions=20,max_weight=1.,
        max_invested=1.,capacity_fraction=.01)


def market(dates,prices):
    values=np.asarray(prices,float)[:,None]
    return MarketArrays(pd.to_datetime(dates),["S"],values.copy(),values.copy(),
                        adv=np.full(values.shape,1e9),signal_mask=np.ones(len(dates),bool))


def buy_then_hold(observed=None):
    def policy(j,ctx):
        if observed is not None:
            observed.append((j,ctx.holding_age.copy(),ctx.entry_date.copy(),ctx.entry_price.copy(),ctx.current_units.copy()))
        if j==0:
            return TargetDecision(np.array([[.8]]),ctx.decision_mask)
        return TargetDecision(np.zeros((1,1)),np.zeros((1,1),bool))
    return policy


def event(cash=0):
    return CorporateActionTransition("2024-01-04","FORWARD_SPLIT","old","new","S","S",2.,
        cash,"TIER2_LOCAL_CANONICAL","synthetic://split","a"*64)


def test_fractional_cash_age_and_entry_persist_across_year_boundary():
    data=market(["2023-12-29","2024-01-02","2024-01-03","2024-01-04"],[777]*4)
    observed=[]
    replay=run_continuous_account(data,["path"],buy_then_hold(observed),config())
    assert replay.final_cash[0]==pytest.approx(600)
    assert replay.final_state["fractional_shares"][0,0]==pytest.approx(2400/777)
    assert replay.final_state["fractional_shares"][0,0] != int(replay.final_state["fractional_shares"][0,0])
    assert replay.positions.holding_age.tolist()==[0,1,2]
    assert replay.positions.entry_date.eq(pd.Timestamp("2024-01-02")).all()
    assert replay.positions.entry_price.eq(777).all()
    assert [int(o[1][0,0]) for o in observed]==[-1,0,1,2]
    assert replay.fills.iloc[0].execution_date==pd.Timestamp("2024-01-02")
    assert replay.fills.iloc[0].price*replay.fills.iloc[0].fractional_shares==pytest.approx(2400)
    assert replay.daily.transaction_cost_amount.eq(0).all()
    assert replay.metadata["annual_reset"] is False
    larger=run_continuous_account(data,["path"],buy_then_hold(),config(6000))
    assert larger.final_state["fractional_shares"][0,0]==pytest.approx(2*2400/777)


def test_source_backed_split_uses_common_transition_and_raw_fill_identity():
    data=market(["2024-01-02","2024-01-03","2024-01-04","2024-01-05"],[777,777,388.5,388.5])
    split=event()
    replay=run_continuous_account(data,["path"],buy_then_hold(),config(),corporate_actions=[split],
        corporate_action_known_at={split.event_fingerprint:"2024-01-03 16:00:00+00:00"})
    assert replay.daily.nav.eq(3000).all()
    assert replay.final_state["fractional_shares"][0,0]==pytest.approx(2*2400/777)
    assert replay.final_units[0,0]==pytest.approx(2400/777)
    assert replay.positions.fractional_shares.tolist()==pytest.approx([2400/777,2*2400/777,2*2400/777])
    assert replay.positions.market_value.tolist()==pytest.approx([2400]*3)
    assert (replay.positions.mark*replay.positions.fractional_shares).tolist()==pytest.approx([2400]*3)
    assert len(replay.metadata["corporate_action_receipts"])==1
    assert replay.accounting_exceptions.empty

    assert replay.positions.entry_price.tolist()==pytest.approx([777,388.5,388.5])
    assert replay.positions.entry_execution_open.eq(777).all()
    def with_exit(j,ctx):
        if j==2:
            return TargetDecision(np.zeros((1,1)),ctx.decision_mask)
        return buy_then_hold()(j,ctx)
    exited=run_continuous_account(data,["path"],with_exit,config(),corporate_actions=[split],
        corporate_action_known_at={split.event_fingerprint:"2024-01-03 16:00:00+00:00"})
    sold=exited.fills.loc[exited.fills.side.eq("SELL")].iloc[0]
    assert sold.price==388.5
    assert sold.fractional_shares==pytest.approx(2*2400/777)
    assert sold.price*sold.fractional_shares==pytest.approx(sold.notional)
    assert exited.final_cash[0]==pytest.approx(3000)
    assert exited.final_state["holding_age"][0,0]==-1


def test_unavailable_or_cash_component_event_fails_closed_only_for_affected_holding():
    data=market(["2024-01-02","2024-01-03","2024-01-04","2024-01-05"],[777,777,388.5,388.5])
    split=event(cash=1)
    replay=run_continuous_account(data,["path"],buy_then_hold(),config(),corporate_actions=[split],
        corporate_action_known_at={split.event_fingerprint:"2024-01-03 16:00:00+00:00"})
    assert len(replay.accounting_exceptions)==1
    assert replay.accounting_exceptions.iloc[0].nav_valid==False
    assert replay.daily.loc[replay.daily.date.ge("2024-01-04"),"certified_nav"].isna().all()
    assert replay.final_state["fractional_shares"][0,0]==pytest.approx(2400/777)
    assert len(replay.fills)==1
    assert replay.daily.loc[replay.daily.date.ge("2024-01-04"),"accounting_qualified"].eq(False).all()
    assert replay.final_state["accounting_qualified"].tolist()==[False]


def test_locked_full_prefix_continuation_keeps_pre2026_account_and_requires_freeze():
    pre=market(["2025-12-30","2025-12-31"],[777,777])
    first=run_continuous_account(pre,["path"],buy_then_hold(),config())
    full=market(["2025-12-30","2025-12-31","2026-01-02","2026-01-05"],[777]*4)
    with pytest.raises(ValueError,match="finalist freeze"):
        run_continuous_account(full,["path"],buy_then_hold(),config(),previous_prefix=first.prefix_identity)
    later=run_continuous_account(full,["path"],buy_then_hold(),config(),
        previous_prefix=first.prefix_identity,locked_evaluation_receipt={"status":"FINALIST_FROZEN","sha256":"f"*64})
    assert later.prefix_identity==first.prefix_identity
    assert later.positions.holding_age.tolist()==[0,1,2]
    assert later.final_cash[0]==pytest.approx(first.final_cash[0])
    bad=dict(first.prefix_identity,sha256="0"*64)
    with pytest.raises(AssertionError,match="changed frozen"):
        run_continuous_account(full,["path"],buy_then_hold(),config(),previous_prefix=bad,
            locked_evaluation_receipt={"status":"FINALIST_FROZEN","sha256":"f"*64})


def test_all_cash_prefix_can_legally_add_first_position_in_locked_period():
    pre=market(["2025-12-30","2025-12-31"],[777]*2)
    def cash_then_buy(j,ctx):
        if j==2:
            return TargetDecision(np.array([[.8]]),ctx.decision_mask)
        return TargetDecision(np.zeros((1,1)),ctx.decision_mask)
    first=run_continuous_account(pre,["path"],cash_then_buy,config())
    assert first.fills.empty and first.positions.empty
    full=market(["2025-12-30","2025-12-31","2026-01-02","2026-01-05"],[777]*4)
    later=run_continuous_account(full,["path"],cash_then_buy,config(),
        previous_prefix=first.prefix_identity,locked_evaluation_receipt={"status":"FINALIST_FROZEN","sha256":"f"*64})
    assert later.prefix_identity==first.prefix_identity
    assert later.fills.iloc[0].execution_date==pd.Timestamp("2026-01-05")


def test_finalist_only_prefix_is_reused_from_the_full_candidate_batch():
    pre=market(["2025-12-30","2025-12-31"],[777]*2)
    def batch_policy(j,ctx):
        if j==0:
            return TargetDecision(np.array([[.8],[.4]]),ctx.decision_mask)
        return TargetDecision(np.zeros((2,1)),np.zeros((2,1),bool))
    first=run_continuous_account(pre,["x","y"],batch_policy,config())
    chosen=account_prefix_identity(first,"2025-12-31",["y"])
    full=market(["2025-12-30","2025-12-31","2026-01-02"],[777]*3)
    def finalist_policy(j,ctx):
        if j==0:
            return TargetDecision(np.array([[.4]]),ctx.decision_mask)
        return TargetDecision(np.zeros((1,1)),np.zeros((1,1),bool))
    later=run_continuous_account(full,["y"],finalist_policy,config(),previous_prefix=chosen,
        locked_evaluation_receipt={"status":"FINALIST_FROZEN","sha256":"f"*64})
    assert later.prefix_identity==chosen
    assert later.final_cash[0]==pytest.approx(1800)
    with pytest.raises(ValueError,match="path identity"):
        account_prefix_identity(first,"2025-12-31",["missing"])


def test_historical_cash_event_does_not_block_a_later_first_buy_or_other_ticker():
    data=market(["2024-01-02","2024-01-03","2024-01-04","2024-01-05","2024-01-08"],[777,777,388.5,388.5,388.5])
    cash_event=event(cash=1)
    known={cash_event.event_fingerprint:"2024-01-03 16:00:00+00:00"}
    def late_buy(j,ctx):
        if j==3:
            return TargetDecision(np.array([[.8]]),ctx.decision_mask)
        return TargetDecision(np.zeros((1,1)),ctx.decision_mask)
    later=run_continuous_account(data,["later"],late_buy,config(),corporate_actions=[cash_event],
        corporate_action_known_at=known)
    assert later.accounting_exceptions.empty
    assert later.daily.accounting_qualified.all()
    assert later.daily.certified_nav.notna().all()
    assert later.fills.iloc[0].execution_date==pd.Timestamp("2024-01-08")
    assert later.final_state["fractional_shares"][0,0]==pytest.approx(2400/388.5)
    two=MarketArrays(data.dates,["S","B"],np.column_stack([data.open[:,0],np.full(5,100.)]),
        np.column_stack([data.close[:,0],np.full(5,100.)]),adv=np.full((5,2),1e9))
    def with_other_buy(j,ctx):
        if j==0:
            return TargetDecision(np.array([[.4,0]]),ctx.decision_mask)
        if j==2:
            return TargetDecision(np.array([[0,.2]]),ctx.decision_mask)
        return TargetDecision(np.zeros((1,2)),np.zeros((1,2),bool))
    held=run_continuous_account(two,["held"],with_other_buy,config(),corporate_actions=[cash_event],
        corporate_action_known_at=known)
    assert len(held.accounting_exceptions)==1
    assert (held.fills.ticker.eq("B") & held.fills.side.eq("BUY")).any()
    assert held.daily.loc[held.daily.date.ge("2024-01-04"),"accounting_qualified"].eq(False).all()
    assert held.daily.loc[held.daily.date.ge("2024-01-04"),"certified_nav"].isna().all()


# New explicit descriptive scope. All references below are temporary synthetic
# metadata/bytes; no frozen real models, market files, or account outputs are read.
import hashlib
import json
from pathlib import Path
from copy import deepcopy
from scripts.research.a2.evaluation import frozen_test_authority as descriptive


def _synthetic_ref(path, value):
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


@pytest.fixture
def descriptive_fixture(tmp_path, monkeypatch):
    plan = dict(task_id=descriptive.TASK, allow_2027_read=False,
        pre2026_parent_remains_closed=True,
        status="EVALUATION_DESIGN_FROZEN_BEFORE_2026_POLICY_REPLAY",
        account=dict(fractional=True, execution="ORIGINAL_NEXT_LEGAL_RAW_OPEN",
            friction_bps_each_executed_notional=10, terminal_liquidation=False),
        comparison=dict(benchmark_contract="SYNTHETIC_FROZEN_ETF_CONTRACT"))
    plan_ref = _synthetic_ref(tmp_path / "plan.json", plan)
    monkeypatch.setattr(descriptive, "PLAN_SHA256", plan_ref["sha256"])
    sources = {key: _synthetic_ref(tmp_path / (key + ".json"),
        dict(synthetic=True, role=key)) for key in descriptive.SOURCE_GROUPS}
    qualification = dict(schema="A_2026_DESCRIPTIVE_SOURCE_QUALIFICATION_R1",
        task_id=descriptive.TASK, status="QUALIFIED_FOR_DECLARED_RESEARCH_SCOPE",
        source_refs=sources, groups={key: True for key in descriptive.SOURCE_GROUPS})
    qref = _synthetic_ref(tmp_path / "qualification.json", qualification)
    models = {key: _synthetic_ref(tmp_path / (key + ".model.json"),
        dict(synthetic_model_identity=key)) for key in descriptive.MODEL_IDS}
    monkeypatch.setattr(descriptive, "MODEL_SHA256", {k: r["sha256"] for k, r in models.items()})
    rows = []
    for key in descriptive.PATH_IDS:
        row = dict(candidate_id=key, friction_bps=10)
        if key in descriptive.POLICY_TUPLE_SHA256:
            row["scientific_tuple_sha256"] = descriptive.POLICY_TUPLE_SHA256[key]
        else:
            contract = descriptive.benchmark_contract(plan, key)
            row["benchmark_contract"] = contract
            row["scientific_tuple_sha256"] = hashlib.sha256(json.dumps(contract,
                sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        if key in models:
            row["model_ref"] = models[key]
        rows.append(row)
    candidates = dict(task_id=descriptive.TASK, candidates=rows)
    cref = _synthetic_ref(tmp_path / "candidates.json", candidates)
    bound = dict(schema="A_2026_DESCRIPTIVE_ACCOUNT_ADMISSION_R1",
        task_id=descriptive.TASK, status="SOURCE_AND_POLICY_BOUND_FOR_DESCRIPTIVE_EVALUATION",
        strict_PIT_promotion_eligible=False, production_qualified=False, finalist_selected=False,
        new_fit=0, plan_ref=plan_ref, allowed_path_ids=list(descriptive.PATH_IDS),
        initial_cash_usd=3000, initial_holdings=[], initial_receivables=[],
        friction_bps=10, fresh_account=True, source_refs=sources,
        source_qualification_ref=qref, model_refs=models, candidate_manifest_ref=cref,
        windows=[dict(window_id="MAIN", start="2026-01-02", end="2026-01-08")],
        as_of="2026-01-08T22:00:00Z", feature_history_start="2023-01-01")
    def authority(value=None):
        ref = _synthetic_ref(tmp_path / "admission.json", bound if value is None else value)
        return dict(schema="A_2026_DESCRIPTIVE_AUTHORITY_REF_R1", task_id=descriptive.TASK,
                    admission_ref=ref, window_id="MAIN")
    return tmp_path, bound, authority, qualification


def _descriptive_market():
    return market(["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"], [100]*5)


def _descriptive_friction(bps=10):
    return dict(kind="FIXED_ADVERSE_OPEN_SLIPPAGE", scenario_id="SYNTHETIC_10BPS",
        one_way_bps=bps, fee_bps=0, benchmark="NEXT_RAW_OPEN", authority="HYPOTHETICAL_RESEARCH_SCENARIO")


def test_descriptive_fresh_scope_is_not_a_finalist_or_prefix_and_caches_custody(descriptive_fixture, monkeypatch):
    _, _, authority, _ = descriptive_fixture
    admitted = descriptive.load_descriptive_authority(authority())
    def no_more_io(*args, **kwargs):
        raise AssertionError("Per-session validation must not reread source references")
    monkeypatch.setattr(descriptive, "_physical", no_more_io)
    observed=[]
    def policy(j,ctx):
        descriptive.require_descriptive_decision(admitted, ctx.signal_date, "RAW_s10")
        return buy_then_hold(observed)(j,ctx)
    replay = run_continuous_account(_descriptive_market(), ["RAW_s10"], policy, config(),
        execution_friction=_descriptive_friction(), descriptive_evaluation_authority=admitted)
    assert replay.fills.execution_date.tolist() == [pd.Timestamp("2026-01-05")]
    assert replay.daily.iloc[0]["cash"] == 3000
    assert replay.prefix_identity is None
    assert replay.metadata["descriptive_evaluation_authority"]["finalist_selected"] is False
    assert replay.metadata["strict_PIT_promotion_eligible"] is False
    assert replay.metadata["production_qualified"] is False
    assert replay.daily.nav.iloc[-1] == pytest.approx(3000-replay.daily.transaction_cost_amount.sum())
    assert observed[0][1].tolist() == [[-1]]
    assert replay.daily.nav_identity_error.abs().max() < 1e-8
    again = run_continuous_account(_descriptive_market(), ["RAW_s10"], buy_then_hold(), config(),
        execution_friction=_descriptive_friction(), descriptive_evaluation_authority=admitted)
    assert again.fills.fractional_shares.tolist() == replay.fills.fractional_shares.tolist()
    assert again.daily.iloc[0]["cash"] == 3000


@pytest.mark.parametrize("key,value", [
    ("task_id", "OTHER_TASK"), ("status", None), ("plan_ref", None),
    ("source_refs", {}), ("source_qualification_ref", None), ("model_refs", {}),
    ("candidate_manifest_ref", None), ("allowed_path_ids", ["RAW_s10"]),
    ("initial_cash_usd", 3001), ("initial_holdings", ["S"]), ("initial_receivables", [1]),
    ("fresh_account", None), ("friction_bps", 5), ("new_fit", False), ("new_fit", 1),
    ("production_qualified", True), ("strict_PIT_promotion_eligible", None),
    ("finalist_selected", True), ("as_of", None),
    ("as_of", "2026-01-08T19:00:00Z"), ("feature_history_start", "2022-01-01"),
    ("windows", []),
])
def test_descriptive_missing_null_or_changed_contract_rejected(descriptive_fixture,key,value):
    _, bound, authority, _ = descriptive_fixture
    changed = deepcopy(bound); changed[key] = value
    with pytest.raises(ValueError, match="DESCRIPTIVE"):
        descriptive.load_descriptive_authority(authority(changed))


@pytest.mark.parametrize("group", descriptive.SOURCE_GROUPS)
@pytest.mark.parametrize("value", [False, None, "MISSING"])
def test_descriptive_each_source_group_requires_literal_true(descriptive_fixture,group,value):
    path, bound, authority, qualification = descriptive_fixture
    qualification = deepcopy(qualification)
    if value == "MISSING":
        del qualification["groups"][group]
    else:
        qualification["groups"][group] = value
    bound = deepcopy(bound)
    bound["source_qualification_ref"] = _synthetic_ref(path / "qualification.json", qualification)
    with pytest.raises(ValueError, match="SOURCE_GATE_NOT_TRUE"):
        descriptive.load_descriptive_authority(authority(bound))


def test_descriptive_stale_source_hash_or_swapped_model_rejected(descriptive_fixture):
    path, bound, authority, _ = descriptive_fixture
    auth = authority()
    (path / "market_quote.json").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="SOURCE_SHA_CHANGED"):
        descriptive.load_descriptive_authority(auth)
    bound = deepcopy(bound)
    bound["source_refs"]["market_quote"] = _synthetic_ref(path / "market_quote.json",
        dict(synthetic=True, role="market_quote"))
    bound["model_refs"]["R6_BUY_TREE"]["sha256"] = "0"*64
    with pytest.raises(ValueError, match="EXACT_FROZEN_MODEL_REQUIRED"):
        descriptive.load_descriptive_authority(authority(bound))


@pytest.mark.parametrize("change", ["path", "order", "capital", "friction", "start", "end",
                                   "prefix", "finalist", "legacy_ca", "legacy_quote"])
def test_descriptive_account_scope_cannot_expand(descriptive_fixture, change):
    _, _, authority, _ = descriptive_fixture
    data=_descriptive_market(); ids=["RAW_s10"]; cfg=config()
    args=dict(execution_friction=_descriptive_friction(), descriptive_evaluation_authority=authority())
    if change=="path": ids=["NEW_CANDIDATE"]
    elif change=="order": ids=["R6_BUY_TREE","RAW_s10"]
    elif change=="capital": cfg=config(6000)
    elif change=="friction": args["execution_friction"]=_descriptive_friction(5)
    elif change=="start": data=market(["2025-12-31","2026-01-08"],[100]*2)
    elif change=="end": data=market(["2026-01-02","2027-01-04"],[100]*2)
    elif change=="prefix": args["previous_prefix"]={"end_session":"2025-12-31"}
    elif change=="finalist": args["locked_evaluation_receipt"]={"status":"FINALIST_FROZEN","sha256":"f"*64}
    elif change=="legacy_ca": args["research_ca_accounting_convention"]={}
    elif change=="legacy_quote": args["research_quote_domain"]={}
    with pytest.raises(ValueError, match="DESCRIPTIVE"):
        run_continuous_account(data,ids,buy_then_hold(),cfg,**args)


def test_descriptive_default_remains_locked_and_feature_buffer_is_separate(descriptive_fixture):
    _, _, authority, _ = descriptive_fixture
    with pytest.raises(ValueError, match="finalist freeze"):
        run_continuous_account(_descriptive_market(),["RAW_s10"],buy_then_hold(),config())
    admitted=descriptive.load_descriptive_authority(authority())
    descriptive.validate_descriptive_input_dates(admitted,["2025-12-30","2026-01-02"],feature_context=True)
    with pytest.raises(ValueError,match="DECISION_OUTSIDE_WINDOW"):
        descriptive.require_descriptive_decision(admitted,"2025-12-30")
    with pytest.raises(ValueError,match="INPUT_OUTSIDE_WINDOW"):
        descriptive.validate_descriptive_input_dates(admitted,["2026-01-09"],feature_context=True)
    with pytest.raises(ValueError,match="VALIDATED_DESCRIPTIVE"):
        descriptive.require_descriptive_decision(authority(),"2026-01-02")


@pytest.mark.parametrize("settlement_known",[False,True])
def test_descriptive_terminal_uses_original_nonspendable_lifecycle(descriptive_fixture,settlement_known):
    from scripts.v22.corporate_action_transition_r1 import (
        SourceBackedTerminalEvent, SourceBackedTerminalSettlement, RAW_OLD_SHARE_COORDINATE,
        USD_PER_RAW_OLD_SHARE)
    _, _, authority, _ = descriptive_fixture
    payment=SourceBackedTerminalSettlement(event_id="SYNTHETIC_TERMINAL",old_security_id="secS",
        pay_date="2026-01-08",available_at="2026-01-07T12:00:00Z",cash_per_old_share=5,
        amount_unit=USD_PER_RAW_OLD_SHARE,quantity_coordinate=RAW_OLD_SHARE_COORDINATE,
        source_type="TIER2_LOCAL_CANONICAL",source_reference="synthetic://payment",source_fingerprint="a"*64)
    event=SourceBackedTerminalEvent(event_id="SYNTHETIC_TERMINAL",old_security_id="secS",ticker="S",
        effective_at="2026-01-06T14:30:00Z",available_at="2026-01-05T12:00:00Z",
        cash_per_old_share=5,currency="USD",amount_unit=USD_PER_RAW_OLD_SHARE,
        quantity_coordinate=RAW_OLD_SHARE_COORDINATE,quantity_source_reference="synthetic://raw",
        quantity_source_fingerprint="b"*64,source_type="TIER2_LOCAL_CANONICAL",
        source_reference="synthetic://terminal",source_fingerprint="c"*64,
        settlement=payment if settlement_known else None)
    mapping={"secS":"S"}
    def keep_buying(j,ctx):
        return TargetDecision(np.full((1,1),.8),ctx.decision_mask)
    replay=run_continuous_account(_descriptive_market(),["RAW_s10"],keep_buying,config(),
        execution_friction=_descriptive_friction(),descriptive_evaluation_authority=authority(),
        entitlement_enabled=True,entitlement_events=[event],entitlement_security_tickers=mapping,
        entitlement_source_binding=dict(status="SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND",
            source_fingerprint="d"*64,event_fingerprints=[event.event_fingerprint],
            security_tickers=mapping,quantity_coordinate=RAW_OLD_SHARE_COORDINATE))
    assert replay.final_state["fractional_shares"][0,0] == 0
    assert replay.fills.side.tolist()==["BUY"]
    assert replay.fills.execution_date.tolist()==[pd.Timestamp("2026-01-05")]
    rights=replay.fills.fractional_shares.iloc[0]*5
    at_ex=replay.daily.loc[replay.daily.date.eq("2026-01-06")].iloc[0]
    assert at_ex["receivable_value_usd"]==pytest.approx(rights)
    assert at_ex["entitlement_cash_flow_usd"]==0
    assert replay.daily.entitlement_cash_flow_usd.sum()==pytest.approx(rights if settlement_known else 0)
    assert replay.final_state["receivable_value_usd"][0]==pytest.approx(0 if settlement_known else rights)
    assert replay.final_state["accounting_qualified"].tolist()==[settlement_known]
    assert replay.daily.nav_identity_error.abs().max()<1e-8

@pytest.mark.parametrize("candidate_id", tuple(descriptive.POLICY_TUPLE_SHA256))
def test_descriptive_exact_policy_commitment_cannot_be_relabelled(descriptive_fixture, candidate_id):
    path, bound, authority, _ = descriptive_fixture
    manifest = json.loads((path / "candidates.json").read_text(encoding="utf-8"))
    row = next(r for r in manifest["candidates"] if r["candidate_id"] == candidate_id)
    row["scientific_tuple_sha256"] = "0"*64
    changed = deepcopy(bound)
    changed["candidate_manifest_ref"] = _synthetic_ref(path / "candidates.json", manifest)
    with pytest.raises(ValueError, match="EXACT_FROZEN_POLICY_REQUIRED"):
        descriptive.load_descriptive_authority(authority(changed))


@pytest.mark.parametrize("candidate_id", descriptive.PATH_IDS[4:])
@pytest.mark.parametrize("field,value", [
    ("ticker", "OTHER"), ("policy", "DAILY_REBALANCE"), ("fractional", False),
    ("execution", "SAME_CLOSE"), ("friction_bps", 5),
    ("corporate_actions", "PRICE_RETURN_ONLY"), ("terminal_liquidation", True),
    ("frozen_plan_contract", "ALTERED"), ("ticker", None), ("ticker", "MISSING"),
    ("scientific_tuple_sha256", "0"*64)])
def test_descriptive_benchmark_contract_is_exact(descriptive_fixture, candidate_id, field, value):
    path, bound, authority, _ = descriptive_fixture
    manifest = json.loads((path / "candidates.json").read_text(encoding="utf-8"))
    row = next(r for r in manifest["candidates"] if r["candidate_id"] == candidate_id)
    if field == "scientific_tuple_sha256":
        row[field] = value
    elif value == "MISSING":
        del row["benchmark_contract"][field]
    else:
        row["benchmark_contract"][field] = value
    changed = deepcopy(bound)
    changed["candidate_manifest_ref"] = _synthetic_ref(path / "candidates.json", manifest)
    with pytest.raises(ValueError, match="BENCHMARK_CONTRACT_CHANGED|BENCHMARK_COMMITMENT_CHANGED"):
        descriptive.load_descriptive_authority(authority(changed))

@pytest.mark.parametrize("drive", ["E", "F", "e", "f"])
def test_descriptive_forbidden_drive_rejects_before_filesystem_io(monkeypatch, drive):
    from pathlib import Path
    calls=[]
    def forbidden_io(*args, **kwargs):
        calls.append("IO")
        raise AssertionError("Forbidden drive must fail before is_file or open")
    monkeypatch.setattr(Path, "is_file", forbidden_io)
    monkeypatch.setattr(Path, "open", forbidden_io)
    with pytest.raises(ValueError, match="DESCRIPTIVE_FORBIDDEN_DRIVE"):
        descriptive._physical(dict(path=drive+":/synthetic-never-read.json", sha256="0"*64))
    assert calls == []


# Human-approved exact-task post-verified accounting roles. Synthetic sources
# below are built only in pytest tmp_path; no real source/model/account is loaded.
def _postverified_event(fixture, kind="cash"):
    from scripts.v22 import corporate_action_transition_r1 as ca
    path, bound, _, _ = fixture
    source = _synthetic_ref(path / (kind + "_source.json"), dict(synthetic=True, role=kind))
    reconstruction = _synthetic_ref(path / (kind + "_reconstruction.json"),
        dict(synthetic=True, task_id=bound["task_id"], role="POST_VERIFIED_ACCOUNTING_ONLY"))
    common = dict(event_id="SYNTHETIC_" + kind, old_security_id="secS", ticker="S",
        available_at=None, cash_per_old_share=10. if kind == "cash" else 16.,
        currency="USD", amount_unit=ca.USD_PER_RAW_OLD_SHARE,
        quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,
        source_type="TIER1_ISSUER_REGULATOR_EXCHANGE",
        source_reference=source["path"], source_fingerprint=source["sha256"],
        reconstruction_ref=reconstruction["path"], reconstruction_sha256=reconstruction["sha256"])
    if kind == "cash":
        return ca.ResearchReconstructedCashEvent(**common, action_type="CASH_DIVIDEND",
            ex_date="2026-01-06", record_date="2026-01-06", pay_date="2026-01-08")
    quantity = _synthetic_ref(path / "terminal_quantity.json",
        dict(synthetic=True, coordinate=ca.RAW_OLD_SHARE_COORDINATE))
    return ca.ResearchPostVerifiedTerminalEvent(**common,
        effective_at="2026-01-06T14:30:00Z", quantity_source_reference=quantity["path"],
        quantity_source_fingerprint=quantity["sha256"])


def _postverified_bind(fixture, events):
    from scripts.v22 import corporate_action_transition_r1 as ca
    path, original, authority, qualification = fixture
    bound, qualification = deepcopy(original), deepcopy(qualification)
    catalogue = dict(synthetic=True, role="corporate_actions")
    for cls, key in ((ca.ResearchReconstructedCashEvent, "research_cash_reconstruction"),
                     (ca.ResearchPostVerifiedTerminalEvent, "research_terminal_reconstruction")):
        entries = []
        for event in events:
            if not isinstance(event, cls):
                continue
            entry = dict(event_fingerprint=event.event_fingerprint,
                reconstruction_ref=dict(path=event.reconstruction_ref, sha256=event.reconstruction_sha256))
            if cls is ca.ResearchPostVerifiedTerminalEvent:
                entry["terminal_terms"] = {
                    **{k:getattr(event,k) for k in descriptive._TERMINAL_COMMITMENT_FIELDS},
                    "settlement":None}
            entries.append(entry)
        if entries:
            binding = dict(task_id=bound["task_id"], clock_role="POST_VERIFIED_ACCOUNTING_ONLY",
                strict_PIT_promotion_eligible=False, production_qualified=False, events=entries)
            bound[key] = binding
            catalogue[key] = deepcopy(binding)
    bound["source_refs"]["corporate_actions"] = _synthetic_ref(path/"corporate_actions.json",catalogue)
    qualification["source_refs"] = deepcopy(bound["source_refs"])
    bound["source_qualification_ref"] = _synthetic_ref(path/"qualification.json",qualification)
    return descriptive.load_descriptive_authority(authority(bound)), bound


def _postverified_account_args(events):
    from scripts.v22 import corporate_action_transition_r1 as ca
    mapping = {e.old_security_id:e.ticker for e in events}
    return dict(entitlement_enabled=True, entitlement_events=events,
        entitlement_security_tickers=mapping,
        entitlement_source_binding=dict(status="SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND",
            source_fingerprint="d"*64, event_fingerprints=[e.event_fingerprint for e in events],
            security_tickers=mapping, quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE))


@pytest.mark.parametrize("kind", ["cash","terminal"])
def test_postverified_lifecycle_preserves_cash_identity_and_pending_right(descriptive_fixture,monkeypatch,kind):
    from scripts.v22 import corporate_action_transition_r1 as ca
    event=_postverified_event(descriptive_fixture,kind)
    authority,_=_postverified_bind(descriptive_fixture,[event])
    monkeypatch.setattr(descriptive,"_physical",lambda *a:pytest.fail("runtime source IO"))
    def step(day,positions,cash=100.,state=None):
        return ca.apply_entitlement_lifecycle([event],positions,cash,execution_date=day,
            session_open_at=pd.Timestamp(day+"T14:30:00Z"),security_tickers={"secS":"S"},
            quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,state=state,enabled=True,
            descriptive_accounting_authority=authority)
    ex=step("2026-01-06",{"secS":2.5})
    amount=2.5*event.cash_per_old_share
    assert ex.cash==100 and ex.receivable_value_usd==amount
    assert ex.positions["secS"]==(0. if kind=="terminal" else 2.5)
    assert all(r["publication_available_at"] is None for r in ex.records)
    assert all(r["clock_role"]=="POST_VERIFIED_ACCOUNTING_ONLY" for r in ex.records)
    later=step("2026-01-07",{},ex.cash,ex.state)
    end=step("2026-01-08",{},later.cash,later.state)
    assert end.cash==(100 if kind=="terminal" else 100+amount)
    assert end.receivable_value_usd==(amount if kind=="terminal" else 0.)
    assert (end.state.receivables[0].pay_date if kind=="terminal" else None) is None


@pytest.mark.parametrize("kind", ["cash","terminal"])
@pytest.mark.parametrize("fault", ["none","dict","fake_seal","wrong_task","aggregate","a94","inference"])
def test_postverified_rejects_unsealed_wrong_task_and_inference(descriptive_fixture,kind,fault):
    from dataclasses import replace
    event=_postverified_event(descriptive_fixture,kind)
    admitted,_=_postverified_bind(descriptive_fixture,[event])
    value=admitted
    if fault=="none":value=None
    elif fault=="dict":value={"task_id":descriptive.TASK}
    elif fault=="fake_seal":value=replace(admitted,_seal=object())
    elif fault=="wrong_task":value=replace(admitted,task_id="UNAPPROVED")
    elif fault=="aggregate":value=replace(admitted,task_id=descriptive.AGGREGATE_TASK)
    elif fault=="a94":value=replace(admitted,task_id="DEMO_VS_A_STATEFUL_FROZEN_TEST2026_R1")
    elif fault=="inference":value=replace(admitted,capability="INFERENCE_ONLY",\
        allowed_path_ids=descriptive.MODEL_IDS,_seal=descriptive._INFERENCE_SEAL)
    with pytest.raises(ValueError,match="DESCRIPTIVE"):
        descriptive.validate_reconstructed_accounting_events(value,[event],require_exact=True)


@pytest.mark.parametrize("kind", ["cash","terminal"])
@pytest.mark.parametrize("fault", ["empty","amount","SID","ref","duplicate","catalogue","source"])
def test_postverified_exact_commitment_and_physical_custody(descriptive_fixture,kind,fault):
    from dataclasses import replace
    path,_,authority,_=descriptive_fixture
    event=_postverified_event(descriptive_fixture,kind)
    admitted,bound=_postverified_bind(descriptive_fixture,[event])
    events=[event]
    if fault=="empty":events=[]
    elif fault=="amount":events=[replace(event,cash_per_old_share=event.cash_per_old_share+.01)]
    elif fault=="SID":events=[replace(event,old_security_id="ANOTHER_SID")]
    elif fault=="ref":events=[replace(event,reconstruction_sha256="e"*64)]
    elif fault=="duplicate":events=[event,event]
    elif fault=="catalogue":
        key="research_"+kind+"_reconstruction"
        bound[key]["events"][0]["event_fingerprint"]="e"*64
        with pytest.raises(ValueError,match="SOURCE_COMMITMENT_CHANGED"):
            descriptive.load_descriptive_authority(authority(bound))
        return
    elif fault=="source":
        Path(event.reconstruction_ref).write_text("changed",encoding="utf-8")
        with pytest.raises(ValueError,match="SOURCE_SHA_CHANGED"):
            descriptive.load_descriptive_authority(authority(bound))
        return
    with pytest.raises(ValueError,match="DESCRIPTIVE"):
        descriptive.validate_reconstructed_accounting_events(admitted,events,require_exact=True)


@pytest.mark.parametrize("kind",["cash","terminal"])
def test_postverified_active_subset_does_not_rebind_full_catalogue(descriptive_fixture,kind):
    from dataclasses import replace
    first=_postverified_event(descriptive_fixture,kind)
    second=replace(first,event_id="SYNTHETIC_SECOND",old_security_id="secB",ticker="B")
    admitted,_=_postverified_bind(descriptive_fixture,[first,second])
    descriptive.validate_reconstructed_accounting_events(admitted,[second])
    with pytest.raises(ValueError,match="CATALOGUE_CHANGED"):
        descriptive.validate_reconstructed_accounting_events(admitted,[second],require_exact=True)
    descriptive.validate_reconstructed_accounting_events(admitted,[first,second],require_exact=True)


@pytest.mark.parametrize("kind",["cash","terminal"])
def test_postverified_old_account_seal_without_new_commitment_is_insufficient(descriptive_fixture,kind):
    _,_,authority,_=descriptive_fixture
    event=_postverified_event(descriptive_fixture,kind)
    admitted=descriptive.load_descriptive_authority(authority())
    with pytest.raises(ValueError,match="EVENT_CHANGED"):
        descriptive.validate_reconstructed_accounting_events(admitted,[event],require_exact=True)


@pytest.mark.parametrize("changes,code",[
    ({"effective_at":"2025-12-31T14:30:00Z"},"2026_UNKNOWN"),
    ({"effective_at":"2027-01-01T14:30:00Z"},"2026_UNKNOWN"),
    ({"effective_at":"2026-01-06T14:30:01Z"},"2026_UNKNOWN"),
    ({"effective_at":"2026-01-06T13:00:00Z"},"2026_UNKNOWN"),
    ({"effective_clock_basis":"SOURCE_CONFIRMED_TIME"},"2026_UNKNOWN"),
    ({"available_at":"2026-01-05T12:00:00Z"},"2026_UNKNOWN"),
    ({"settlement":object()},"2026_UNKNOWN"),
    ({"quantity_coordinate":"ADJUSTED_SHARES"},"COORDINATE"),
    ({"currency":"EUR"},"CURRENCY"),({"amount_unit":"QFQ_UNIT"},"CASH_UNIT"),
    ({"cash_per_old_share":float("nan")},"CONSIDERATION"),
])
def test_postverified_terminal_type_keeps_restricted_semantics(descriptive_fixture,changes,code):
    from dataclasses import replace
    event=_postverified_event(descriptive_fixture,"terminal")
    with pytest.raises(ValueError,match=code):
        replace(event,**changes)


def test_postverified_does_not_relax_strict_or_old_reconstructed_types(descriptive_fixture):
    from dataclasses import asdict
    from scripts.v22 import corporate_action_transition_r1 as ca
    for kind,cls in [("cash",ca.SourceBackedEntitlementEvent),("terminal",ca.SourceBackedTerminalEvent)]:
        event=_postverified_event(descriptive_fixture,kind)
        values=asdict(event)
        for field in ["reconstruction_ref","reconstruction_sha256","clock_role"]:values.pop(field)
        with pytest.raises(ValueError,match="AVAILABLE_TIME"):
            cls(**values)
    values=asdict(_postverified_event(descriptive_fixture,"terminal"))
    values["clock_role"]="RECONSTRUCTED_REALIZED_EVENT"
    with pytest.raises(ValueError,match="RESEARCH_TERMINAL_EFFECTIVE_TIME_OR_BOUNDARY"):
        ca.ResearchReconstructedTerminalEvent(**values)


@pytest.mark.parametrize("kind",["cash","terminal"])
def test_postverified_shared_account_no_extra_nav_cash_or_path_promotion(descriptive_fixture,kind):
    event=_postverified_event(descriptive_fixture,kind)
    admitted,_=_postverified_bind(descriptive_fixture,[event])
    prices=[100,100,90,90,90] if kind=="cash" else [100,100,999,777,555]
    data=market(_descriptive_market().dates,prices)
    ids=["RAW_s10","R6_BUY_TREE"]
    def policy(j,ctx):
        weights=np.zeros_like(ctx.current_weights);weights[0,0]=.8
        return TargetDecision(weights,ctx.decision_mask)
    replay=run_continuous_account(data,ids,policy,config(),execution_friction=_descriptive_friction(),
        descriptive_evaluation_authority=admitted,**_postverified_account_args([event]))
    held=replay.daily.loc[replay.daily.path_id.eq(ids[0])]
    untouched=replay.daily.loc[replay.daily.path_id.eq(ids[1])]
    qty=replay.fills.loc[replay.fills.execution_date.eq(pd.Timestamp("2026-01-05")),"fractional_shares"].iloc[0]
    amount=qty*event.cash_per_old_share
    assert untouched.cash.eq(3000).all() and untouched.receivable_value_usd.eq(0).all()
    assert untouched.accounting_qualified.all()
    assert replay.daily.nav_identity_error.abs().max()<1e-8
    assert replay.daily.actual_cash_flow_identity_error.abs().max()<1e-8
    assert replay.metadata["strict_PIT_promotion_eligible"] is False
    if kind=="terminal":
        assert replay.fills.side.tolist()==["BUY"]
        assert replay.final_state["fractional_shares"][0,0]==0
        assert held.loc[held.date.ge("2026-01-06"),"receivable_value_usd"].tolist()==pytest.approx([amount]*3)
        assert held.loc[held.date.ge("2026-01-06"),"cash"].nunique()==1
        assert held.loc[held.date.ge("2026-01-06"),"certified_nav"].isna().all()
        assert not held.loc[held.date.ge("2026-01-06"),"accounting_qualified"].any()
        assert replay.metadata["terminal_settlement_qualified_by_path"]=={ids[0]:False,ids[1]:True}
        assert replay.metadata["terminal_settlement_assumed"] is False
        assert replay.entitlements.pay_date.isna().all()
        assert held.loc[held.date.ge("2026-01-06"),"nav"].to_numpy()==pytest.approx(
            held.loc[held.date.ge("2026-01-06"),"cash"].to_numpy()+amount)
    else:
        assert held.entitlement_cash_flow_usd.sum()==pytest.approx(amount)
        assert held.accounting_qualified.all()
        assert replay.metadata["cash_publication_clock_reconstructed"] is False


def test_postverified_fresh_after_terminal_has_no_inherited_receivable(descriptive_fixture):
    path,_,authority,_=descriptive_fixture
    event=_postverified_event(descriptive_fixture,"terminal")
    _,bound=_postverified_bind(descriptive_fixture,[event])
    bound["windows"]=[dict(window_id="MAIN",start="2026-01-07",end="2026-01-08")]
    admitted=descriptive.load_descriptive_authority(authority(bound))
    replay=run_continuous_account(market(["2026-01-07","2026-01-08"],[999,999]),["RAW_s10"],
        buy_then_hold(),config(),execution_friction=_descriptive_friction(),
        descriptive_evaluation_authority=admitted,**_postverified_account_args([event]))
    assert replay.fills.empty and replay.daily.cash.eq(3000).all()
    assert replay.daily.receivable_value_usd.eq(0).all()
    assert replay.daily.accounting_qualified.all() and replay.final_state["cash_receivables"]==()


@pytest.mark.parametrize("kind",["cash","terminal"])
@pytest.mark.parametrize("fault",["task","role","promotion","production","duplicate","missing_ref","wrong_ref_sha"])
def test_postverified_source_binding_cannot_mint_wrong_or_incomplete_role(descriptive_fixture,kind,fault):
    event=_postverified_event(descriptive_fixture,kind)
    _,bound=_postverified_bind(descriptive_fixture,[event])
    key="research_"+kind+"_reconstruction"
    if fault=="task":bound[key]["task_id"]=descriptive.AGGREGATE_TASK
    elif fault=="role":bound[key]["clock_role"]="STRICT_PIT"
    elif fault=="promotion":bound[key]["strict_PIT_promotion_eligible"]=True
    elif fault=="production":bound[key]["production_qualified"]=True
    elif fault=="duplicate":bound[key]["events"]*=2
    elif fault=="missing_ref":del bound[key]["events"][0]["reconstruction_ref"]
    else:bound[key]["events"][0]["reconstruction_ref"]["sha256"]="0"*64
    path,_,_,_=descriptive_fixture
    # Deliberately rebind matching synthetic documents: structural/physical
    # checks must still reject, not just an incidental old catalogue hash.
    bound["source_refs"]["corporate_actions"]=_synthetic_ref(path/"corporate_actions.json",{key:bound[key]})
    with pytest.raises(ValueError,match="DESCRIPTIVE"):
        descriptive._load_post_verified_binding(bound,bound["source_refs"],descriptive.TASK,key)


@pytest.mark.parametrize("term",["cash_per_old_share","old_security_id","effective_at"])
def test_postverified_terminal_exact_terms_cannot_disagree_with_fingerprint(descriptive_fixture,term):
    event=_postverified_event(descriptive_fixture,"terminal")
    _,bound=_postverified_bind(descriptive_fixture,[event])
    key="research_terminal_reconstruction"
    entry=bound[key]["events"][0]
    entry["terminal_terms"][term]={"cash_per_old_share":17.,"old_security_id":"DIFFERENT",
        "effective_at":"2026-01-07T14:30:00Z"}[term]
    path,_,authority,qualification=descriptive_fixture
    bound["source_refs"]["corporate_actions"]=_synthetic_ref(path/"corporate_actions.json",{key:bound[key]})
    qualification=deepcopy(qualification);qualification["source_refs"]=deepcopy(bound["source_refs"])
    bound["source_qualification_ref"]=_synthetic_ref(path/"qualification.json",qualification)
    admitted=descriptive.load_descriptive_authority(authority(bound))
    with pytest.raises(ValueError,match="TERMINAL_TERMS_CHANGED"):
        descriptive.validate_reconstructed_accounting_events(admitted,[event],require_exact=True)


@pytest.mark.parametrize("changes,code",[
    ({"action_type":"SPINOFF"},"CASH_SOURCE_TERMS"),
    ({"ex_date":"2025-12-31"},"CASH_SOURCE_TERMS"),
    ({"ex_date":"2027-01-01","record_date":"2027-01-01","pay_date":"2027-01-02"},"CASH_SOURCE_TERMS"),
    ({"available_at":"2026-01-05"},"AVAILABLE_TIME"),
    ({"pay_date":"2026-01-05"},"DUE_BILL"),
    ({"source_type":"HEURISTIC"},"SOURCE_NOT_AUTHORIZED"),
])
def test_postverified_cash_is_not_a_general_source_or_date_waiver(descriptive_fixture,changes,code):
    from dataclasses import replace
    event=_postverified_event(descriptive_fixture,"cash")
    with pytest.raises(ValueError,match=code):replace(event,**changes)


def test_postverified_dbrg_raw_quantity_after_split_is_not_divided_twice(descriptive_fixture):
    from dataclasses import replace
    event=replace(_postverified_event(descriptive_fixture,"terminal"),
        ticker="DBRG",old_security_id="25401T603",effective_at="2026-01-07T14:30:00Z")
    admitted,_=_postverified_bind(descriptive_fixture,[event])
    data=market(_descriptive_market().dates,[10,10,100,999,777])
    data.tickers=("DBRG",)
    split=CorporateActionTransition("2026-01-06","REVERSE_SPLIT","synthetic_old","25401T603",
        "DBRG","DBRG",.1,0.,"TIER2_LOCAL_CANONICAL","synthetic://split","a"*64)
    replay=run_continuous_account(data,["RAW_s10"],buy_then_hold(),config(),
        execution_friction=_descriptive_friction(),descriptive_evaluation_authority=admitted,
        corporate_actions=[split],corporate_action_known_at={split.event_fingerprint:"2026-01-05T12:00:00Z"},
        **_postverified_account_args([event]))
    snapshot=replay.entitlements.loc[replay.entitlements.phase.eq("TERMINAL_PRE_EFFECTIVE_RAW_SHARE_SNAPSHOT")].iloc[0]
    expected_raw=float(replay.fills.fractional_shares.iloc[0])*.1
    assert snapshot.entitled_raw_shares==pytest.approx(expected_raw)
    assert snapshot.pre_effective_quantity_factor==.1
    assert replay.final_state["receivable_value_usd"][0]==pytest.approx(expected_raw*16.)
    assert replay.fills.side.tolist()==["BUY"]
    assert replay.daily.nav_identity_error.abs().max()<1e-8
    assert replay.metadata["terminal_settlement_qualified_by_path"]["RAW_s10"] is False


def test_postverified_bound_catalogue_cannot_be_omitted_at_account_entry(descriptive_fixture):
    event=_postverified_event(descriptive_fixture,"terminal")
    admitted,_=_postverified_bind(descriptive_fixture,[event])
    with pytest.raises(ValueError,match="CATALOGUE_CHANGED"):
        run_continuous_account(_descriptive_market(),["RAW_s10"],buy_then_hold(),config(),
            execution_friction=_descriptive_friction(),descriptive_evaluation_authority=admitted)


@pytest.mark.parametrize("key",["research_cash_reconstruction","research_terminal_reconstruction"])
def test_postverified_inference_admission_cannot_bind_accounting_role(descriptive_fixture,key):
    path, original, _, _=descriptive_fixture
    bound=deepcopy(original)
    bound.update(schema="A_2026_FROZEN_MODEL_INFERENCE_ADMISSION_R1",
        status="SOURCE_AND_POLICY_BOUND_FOR_FROZEN_INFERENCE_ONLY",
        capability="INFERENCE_ONLY",account_execution_allowed=False,
        allowed_path_ids=list(descriptive.MODEL_IDS))
    bound["source_refs"]={k:v for k,v in bound["source_refs"].items()
        if k in descriptive.INFERENCE_SOURCE_GROUPS}
    bound[key]={}
    q=dict(schema="A_2026_FROZEN_MODEL_INFERENCE_SOURCE_QUALIFICATION_R1",
        task_id=descriptive.TASK,status="QUALIFIED_FOR_FROZEN_INFERENCE_ONLY",
        capability="INFERENCE_ONLY",source_refs=bound["source_refs"],
        groups={k:True for k in descriptive.INFERENCE_SOURCE_GROUPS})
    bound["source_qualification_ref"]=_synthetic_ref(path/"inference_qualification.json",q)
    envelope=dict(schema=descriptive.INFERENCE_REF_SCHEMA,task_id=descriptive.TASK,
        capability="INFERENCE_ONLY",window_id="MAIN",
        admission_ref=_synthetic_ref(path/"inference_admission.json",bound))
    with pytest.raises(ValueError,match="INFERENCE_ONLY_CANNOT_ADMIT_ACCOUNTING"):
        descriptive.load_descriptive_inference_authority(envelope)
