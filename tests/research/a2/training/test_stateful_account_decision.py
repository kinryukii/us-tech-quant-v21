"""Only synthetic pre-2026 inputs and the actual unique continuous engine."""
from copy import deepcopy
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.training import stateful_account_decision as consumer
from scripts.research.a2.evaluation import continuous_research_account as owner
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays, TargetDecision
from scripts.v22.corporate_action_transition_r1 import (
    CorporateActionTransition, SourceBackedTerminalEvent, SourceBackedTerminalSettlement,
    RAW_OLD_SHARE_COORDINATE, USD_PER_RAW_OLD_SHARE)

SID = {"SID_A": "A", "SID_B": "B"}
DATES = pd.to_datetime(["2023-12-28", "2023-12-29", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])
IDENTITY = dict(reference_run_id="SYNTHETIC_REFERENCE", source_account_id="SYNTHETIC_ACCOUNT",
    reference_policy_sha256="a"*64, q_contract_sha256="b"*64,
    friction_contract_sha256="c"*64, security_binding_sha256="d"*64)
FRICTION = dict(kind="FIXED_ADVERSE_OPEN_SLIPPAGE", benchmark="NEXT_RAW_OPEN",
    authority="HYPOTHETICAL_RESEARCH_SCENARIO", scenario_id="SYNTHETIC_10BPS",
    one_way_bps=10, fee_bps=0)


def config():
    return dict(base_currency="USD", initial_nav=3000, initial_cash=3000, initial_holdings=[],
        fractional_shares=True, integer_share_rounding=False, cash_interest=0, transaction_cost_bps=0,
        financing=False, borrowed_cash=False, long_only=True, max_positions=20, max_weight=1.,
        max_invested=1., capacity_fraction=None)


def market(*, split=False, terminal=False, future_open=None):
    a = np.full(6, 100.)
    if split:
        a[2:] = 50.
    if terminal:
        a[3:] = np.nan
    close = np.column_stack([a, np.full(6, 200.)])
    opens = close.copy()
    if future_open is not None:
        opens[2, 0] = future_open
    return MarketArrays(DATES, ["A", "B"], opens, close,
        adv=np.full((6, 2), 1e9), signal_asof=[d.tz_localize("UTC")+pd.Timedelta(hours=21) for d in DATES])


def binding(events):
    return dict(status="SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND", source_fingerprint="e"*64,
        quantity_coordinate=RAW_OLD_SHARE_COORDINATE, event_fingerprints=[e.event_fingerprint for e in events],
        security_tickers=SID)


def provider(data, *, split=False, terminal=False, mutate=None):
    def provide(j, ctx):
        now = ctx.signal_asof
        fields = dict(available_at=now, signal_close=data.close[j].copy(),
            quote_qualified=[True, True], quote_available_at=[now, now],
            quote_source_sha=["f"*64, "f"*64], quantity_factors=[2. if split and j >= 2 else 1., 1.],
            quantity_available_at=[now, now],
            raw_buy_pool=[True, True], terminal_closed=[terminal and j >= 3, False],
            terminal_available_at=[now, now], feature_available_at=[now, now], raw_available_at=[now, now],
            pit32=np.zeros((2, 32)), signal_transition_cost_usd={p: 0. for p in ctx.path_ids})
        for key in consumer.RAW_FIELDS:
            fields[key] = [1., 2.] if key == "raw_rank" else [.1, .2]
        if mutate:
            mutate(fields, j, ctx)
        return fields
    return provide


def exporter(data, paths=("ref",), **kwargs):
    return consumer.ReferenceStateExporter(SID, IDENTITY, provider(data, **kwargs),
        reference_path_by_path={p: "RAW_s10" for p in paths})


def reference(j, ctx):
    if j == 0:
        return TargetDecision(np.broadcast_to([.5, 0.], ctx.current_weights.shape).copy(), ctx.decision_mask.copy())
    return TargetDecision(np.zeros_like(ctx.current_weights), np.zeros_like(ctx.decision_mask))


def run(data, exp, policy=None, *, events=(), share_events=(), known=None, paths=("ref",), callback=None):
    if policy is None:
        def policy(j, ctx):
            exp.capture(j, ctx)
            return reference(j, ctx)
    return consumer.run_observed_continuous_account(data, paths, policy, config(),
        exporter=exp, ledger_callback=callback, execution_friction=FRICTION,
        entitlement_enabled=True, entitlement_events=events,
        entitlement_security_tickers=SID, entitlement_source_binding=binding(events),
        corporate_actions=share_events, corporate_action_known_at=known)


def planner(snapshot, **extra):
    return dict(q_contract_sha256=IDENTITY["q_contract_sha256"],
        friction_contract_sha256=IDENTITY["friction_contract_sha256"],
        prefix_sha256=snapshot["prefix_identity"]["sha256"], available_at=snapshot["signal_asof"], **extra)


def branch(data, action, *, policy=reference, gross=None, other_path=False):
    ref = exporter(data)
    def observed(j, ctx):
        ref.capture(j, ctx)
        return policy(j, ctx)
    baseline = run(data, ref, observed)
    paths = ("branch", "untouched") if other_path else ("branch",)
    exp = exporter(data, paths)
    snapshot = deepcopy(ref.snapshots[(1, "ref")])
    intervention = dict(signal_index=1, path_id="branch", action=action,
        entrant_sid="SID_B", incumbent_sid="SID_A")
    intent = planner(snapshot, target_weight=.5)
    if action == "GROSS":
        intervention["gross"] = gross
        intent.update(gross=gross, weights=[gross/2, gross/2], explicit_mask=[True, True])
    intervention["planner_intent"] = intent
    overlay = consumer.SingleActionOverride(policy, exp, intervention, snapshot["prefix_identity"])
    replay = run(data, exp, overlay, paths=paths)
    return baseline, replay, ref, exp, overlay


def test_actual_unique_engine_state_cash_receivable_age_cross_year_and_observer():
    data = market()
    exp = exporter(data)
    original = owner.run_continuous_account.__globals__["apply_entitlement_lifecycle"]
    replay = run(data, exp)
    assert owner.run_continuous_account.__globals__["apply_entitlement_lifecycle"] is original
    assert exp.observation_receipt["same_original_code_object"] is True
    assert exp.observation_receipt["private_globals_copy"] is True
    assert exp.observation_receipt["new_engine"] is False
    initial = exp.snapshots[(0, "ref")]
    a = initial["stocks"][0]
    assert a["is_held"] is False and a["holding_age_sessions"] == -1
    assert a["first_fill_reference_price"] is None and a["first_fill_state"] == "NOT_APPLICABLE"
    assert a["prior_actual_action"] == "NO_ACTUAL_FILL"
    after = exp.snapshots[(2, "ref")]
    a = after["stocks"][0]
    assert a["is_held"] is True and a["holding_age_sessions"] == 1
    assert a["sessions_since_prior_fill"] == 1
    assert a["first_fill_reference_price"] == 100 and a["entry_execution_open"] == 100
    assert after["account"]["spendable_cash_usd"] == pytest.approx(1498.5)
    assert after["account"]["receivable_value_usd"] == 0
    assert replay.metadata["annual_reset"] is False
    assert replay.daily.actual_cash_flow_identity_error.abs().max() < 1e-8
    assert replay.fills.iloc[0].execution_date == DATES[1]


@pytest.mark.parametrize("action", ["BUY", "SKIP", "HOLD", "SELL", "REPLACE"])
def test_single_intervention_then_original_continuation_and_path_isolation(action):
    def policy(j, ctx):
        if j == 1 and action == "SKIP":
            return TargetDecision(np.broadcast_to([0., .5], ctx.current_weights.shape).copy(), ctx.decision_mask.copy())
        if j == 1 and action == "HOLD":
            return TargetDecision(np.zeros_like(ctx.current_weights), ctx.decision_mask.copy())
        return reference(j, ctx)
    baseline, replay, ref, exp, overlay = branch(market(), action, policy=policy, other_path=True)
    assert overlay.applied_count == 1
    assert exp.snapshots[(1, "branch")]["prefix_identity"] == ref.snapshots[(1, "ref")]["prefix_identity"]
    assert exp.snapshots[(1, "untouched")]["prefix_identity"] == ref.snapshots[(1, "ref")]["prefix_identity"]
    untouched = replay.daily.loc[replay.daily.path_id.eq("untouched")]
    assert untouched.nav.to_numpy() == pytest.approx(baseline.daily.nav.to_numpy())
    action_fills = replay.fills.loc[replay.fills.path_id.eq("branch")]
    if action in ("BUY", "REPLACE"):
        assert (action_fills.ticker.eq("B") & action_fills.side.eq("BUY")).any()
    if action == "SKIP":
        assert not action_fills.ticker.eq("B").any()
    if action == "HOLD":
        assert not action_fills.side.eq("SELL").any()
    if action in ("SELL", "REPLACE"):
        assert (action_fills.ticker.eq("A") & action_fills.side.eq("SELL")).any()
    assert (action_fills.loc[action_fills.signal_date.eq(DATES[1]), "execution_date"] == DATES[2]).all()


@pytest.mark.parametrize("gross", consumer.GROSS_GRID)
def test_gross_uses_bound_planner_vector_not_internal_new_q(gross):
    baseline, replay, ref, exp, overlay = branch(market(), "GROSS", gross=gross)
    assert overlay.applied_count == 1
    assert np.isfinite(replay.daily.certified_nav).all()
    assert replay.daily.cash.ge(0).all()
    assert replay.daily.actual_cash_flow_identity_error.abs().max() < 1e-8


def test_cash_limited_buy_actual_quantity_and_ten_bps_once():
    baseline, replay, *_ = branch(market(), "BUY")
    buys = replay.fills.loc[replay.fills.ticker.eq("B")]
    assert buys.cash_limited.all()
    assert replay.final_cash[0] >= 0
    assert replay.daily.transaction_cost_amount.sum() == pytest.approx(replay.fills.transaction_cost.sum())
    assert np.allclose(replay.fills.actual_fill_price*replay.fills.fractional_shares,
                       replay.fills.actual_fill_notional)
    assert replay.fills.slippage_amount.sum() == pytest.approx(replay.fills.notional.sum()*.001)


def test_future_open_perturbation_does_not_change_past_state_or_prefix():
    first, changed = market(), market(future_open=321.)
    e1, e2 = exporter(first), exporter(changed)
    r1, r2 = run(first, e1), run(changed, e2)
    for j in (0, 1):
        assert e1.snapshots[(j, "ref")]["prefix_identity"] == e2.snapshots[(j, "ref")]["prefix_identity"]
        assert e1.snapshots[(j, "ref")]["stocks"] == e2.snapshots[(j, "ref")]["stocks"]
    assert r1.daily.iloc[2].nav == r2.daily.iloc[2].nav  # common HOLD_UNITS ignores future opening for quantity


def test_exact_prefix_detects_float_delta_below_round10_and_sid_source_coordinate():
    data = market()
    e = exporter(data)
    run(data, e)
    snap = e.snapshots[(1, "ref")]
    orig = consumer.exact_prefix_identity(snap)
    for field in ("cash", "sid", "factor", "source", "lifecycle"):
        changed = deepcopy(snap)
        if field == "cash":
            changed["prefix_payload"]["account"]["cash_usd"] = np.nextafter(changed["account"]["cash_usd"], np.inf)
        elif field == "sid":
            changed["prefix_payload"]["securities"][0]["sid"] = "OTHER"
        elif field == "factor":
            changed["prefix_payload"]["securities"][0]["quantity_factor"] = 2.
        elif field == "source":
            changed["prefix_payload"]["source_account_identity"]["source_account_id"] = "OTHER"
        else:
            changed["prefix_payload"]["corporate_action_state"] = {"terminal_extinguished": "OTHER"}
        assert consumer.exact_prefix_identity(changed) != orig
        with pytest.raises(consumer.PrefixMismatch):
            consumer.verify_reference_prefix(changed, orig)


@pytest.mark.parametrize("key", ["available_at", "quote_available_at", "feature_available_at",
                                 "raw_available_at", "terminal_available_at", "quantity_available_at"])
def test_future_or_unknown_signal_source_state_is_blocked(key):
    def mutate(fields, j, ctx):
        future = ctx.signal_asof+pd.Timedelta(days=1)
        fields[key] = future if key == "available_at" else [future, future]
    data = market()
    exp = exporter(data, mutate=mutate)
    with pytest.raises(consumer.BlockedState, match="FUTURE"):
        run(data, exp)


@pytest.mark.parametrize("what", ["pit32", "quote", "raw", "factor", "transition"])
def test_missing_required_state_is_never_filled_zero(what):
    def mutate(fields, j, ctx):
        if what == "pit32": fields["pit32"][0, 0] = np.nan
        if what == "quote": fields["quote_qualified"][0] = False
        if what == "raw": fields["raw_score"][0] = np.nan
        if what == "factor": fields["quantity_factors"][0] = 0
        if what == "transition": fields["signal_transition_cost_usd"] = {}
    data = market()
    exp = exporter(data, mutate=mutate)
    with pytest.raises(consumer.BlockedState):
        run(data, exp)


def test_receivable_none_is_blocked_and_held_entry_unknown_blocked():
    data = market()
    exp = exporter(data)
    def policy(j, ctx):
        if j == 1:
            object.__setattr__(ctx, "receivable_value_usd", None)
        exp.capture(j, ctx)
        return reference(j, ctx)
    with pytest.raises(consumer.BlockedState, match="RECEIVABLE_UNKNOWN"):
        run(data, exp, policy)
    exp = exporter(data)
    def bad_entry(j, ctx):
        if j == 1: ctx.entry_price[0, 0] = np.nan
        exp.capture(j, ctx)
        return reference(j, ctx)
    with pytest.raises(consumer.BlockedState, match="HELD_FIRST_FILL"):
        run(data, exp, bad_entry)


def test_fill_action_normalization_from_actual_engine_add_and_exit():
    data = market()
    exp = exporter(data)
    def policy(j, ctx):
        exp.capture(j, ctx)
        if j == 0: return TargetDecision(np.array([[.3, 0.]]), ctx.decision_mask)
        if j == 1: return TargetDecision(np.array([[.5, 0.]]), ctx.decision_mask)
        if j == 2: return TargetDecision(np.zeros((1, 2)), ctx.decision_mask)
        return reference(j, ctx)
    replay = run(data, exp, policy)
    assert replay.fills.action.tolist() == ["BUY", "INCREASE", "EXIT"]
    assert exp.snapshots[(2, "ref")]["stocks"][0]["prior_actual_action"] == "ADD"
    assert exp.snapshots[(3, "ref")]["stocks"][0]["prior_actual_action"] == "SELL"


def split_event():
    return CorporateActionTransition(str(DATES[2].date()), "FORWARD_SPLIT", "SID_A", "SID_A", "A", "A",
        2., 0., "TIER2_LOCAL_CANONICAL", "synthetic://split", "1"*64)


def terminal_event(known=True, pay_index=5):
    pay = None
    if known:
        pay = SourceBackedTerminalSettlement("TERMINAL_A", "SID_A", str(DATES[pay_index].date()),
            str(DATES[pay_index-1].date())+"T21:00:00+00:00", 5., USD_PER_RAW_OLD_SHARE,
            RAW_OLD_SHARE_COORDINATE, "TIER2_LOCAL_CANONICAL", "synthetic://settlement", "2"*64)
    return SourceBackedTerminalEvent("TERMINAL_A", "SID_A", "A",
        str(DATES[3].date())+"T14:30:00+00:00", str(DATES[2].date())+"T21:00:00+00:00",
        5., "USD", USD_PER_RAW_OLD_SHARE, RAW_OLD_SHARE_COORDINATE, "synthetic://quantity", "3"*64,
        "TIER2_LOCAL_CANONICAL", "synthetic://terminal", "4"*64, pay)


def test_actual_owner_split_coordinate_observer_does_not_apply_split_twice():
    data = market(split=True)
    exp = exporter(data, split=True)
    split = split_event()
    replay = run(data, exp, share_events=[split],
        known={split.event_fingerprint: str(DATES[1].date())+"T21:00:00+00:00"})
    stock = exp.snapshots[(2, "ref")]["stocks"][0]
    assert stock["raw_fractional_shares"] == pytest.approx(30.)
    assert stock["first_fill_reference_price"] == 50.
    assert stock["entry_execution_open"] == 100.
    assert stock["mark_vs_first_fill"] == 1.
    assert replay.final_units[0, 0] == pytest.approx(15.)
    assert replay.final_state["fractional_shares"][0, 0] == pytest.approx(30.)


def test_actual_owner_terminal_known_settlement_receivable_not_spendable_no_sell_rebuy():
    data = market(split=True, terminal=True)
    exp = exporter(data, split=True, terminal=True)
    split, event = split_event(), terminal_event()
    replay = run(data, exp, events=[event], share_events=[split],
        known={split.event_fingerprint: str(DATES[1].date())+"T21:00:00+00:00"})
    claim = exp.snapshots[(3, "ref")]
    assert claim["account"]["receivable_value_usd"] == pytest.approx(150.)
    assert claim["account"]["spendable_cash_usd"] == pytest.approx(1498.5)
    terminal = claim["stocks"][0]
    assert terminal["terminal_closed"] and not terminal["is_held"]
    assert not terminal["buy_eligible"] and not terminal["sell_eligible"]
    assert terminal["first_fill_state"] == "TERMINAL_NOT_APPLICABLE"
    assert replay.final_state["fractional_shares"][0, 0] == 0
    assert len(replay.fills) == 1
    assert replay.final_cash[0] == pytest.approx(1648.5)
    assert replay.daily.loc[replay.daily.date.ge(DATES[3]), "certified_nav"].notna().all()


def test_actual_owner_terminal_unknown_settlement_state_observed_but_qualification_blocked():
    data = market(terminal=True)
    exp = exporter(data, terminal=True)
    event = terminal_event(False)
    blocked = []
    def policy(j, ctx):
        try: exp.capture(j, ctx)
        except consumer.BlockedState as error:
            blocked.append((j, str(error)))
        return reference(j, ctx)
    replay = run(data, exp, policy, events=[event])
    assert blocked and all(j >= 3 and "ACCOUNT_UNQUALIFIED" in error for j, error in blocked)
    assert replay.final_state["fractional_shares"][0, 0] == 0
    assert replay.final_state["receivable_value_usd"][0] == pytest.approx(75.)
    assert replay.final_cash[0] == pytest.approx(1498.5)
    assert replay.daily.loc[replay.daily.date.ge(DATES[3]), "certified_nav"].isna().all()
    assert replay.metadata["terminal_settlement_qualified_by_path"]["ref"] is False
    assert exp.lifecycle["ref"]["state"].receivables[0].amount_usd == pytest.approx(75.)
    assert not exp.snapshots.keys() & {(j, "ref") for j in range(3, 6)}


def test_future_payment_perturbation_never_changes_past_predictive_state():
    data = market(terminal=True)
    e1, e2 = exporter(data, terminal=True), exporter(data, terminal=True)
    run(data, e1, events=[terminal_event(True, 5)])
    run(data, e2, events=[terminal_event(True, 4)])
    for j in (0, 1, 2, 3):
        assert e1.snapshots[(j, "ref")]["stocks"] == e2.snapshots[(j, "ref")]["stocks"]
        assert e1.snapshots[(j, "ref")]["account"] == e2.snapshots[(j, "ref")]["account"]
    # Catalogue source fingerprints differ, so exact source-aware prefix may differ.
    assert e1.snapshots[(4, "ref")]["account"]["spendable_cash_usd"] != e2.snapshots[(4, "ref")]["account"]["spendable_cash_usd"]


def test_wrong_prefix_wrong_planner_or_terminal_intent_blocks_before_override():
    data = market()
    exp = exporter(data)
    run(data, exp)
    snapshot = exp.snapshots[(1, "ref")]
    bad = deepcopy(snapshot["prefix_identity"]); bad["sha256"] = "0"*64
    overlay = consumer.SingleActionOverride(reference, exporter(data, ("branch",)),
        dict(signal_index=1, path_id="branch", action="BUY", entrant_sid="SID_B",
             planner_intent=planner(snapshot, target_weight=.5)), bad)
    with pytest.raises(consumer.PrefixMismatch):
        run(data, overlay.exporter, overlay, paths=("branch",))
    assert overlay.applied_count == 0
    bad_intent = planner(snapshot, target_weight=.5); bad_intent["q_contract_sha256"] = "0"*64
    overlay = consumer.SingleActionOverride(reference, exporter(data, ("branch",)),
        dict(signal_index=1, path_id="branch", action="BUY", entrant_sid="SID_B", planner_intent=bad_intent),
        snapshot["prefix_identity"])
    with pytest.raises(consumer.BlockedState, match="PLANNER"):
        run(data, overlay.exporter, overlay, paths=("branch",))
    assert overlay.applied_count == 0


def test_finite_source_nonmutation_and_no_data_or_fit_entrypoints():
    assert hashlib.sha256(Path(owner.__file__).read_bytes()).hexdigest() == consumer.CORE_SOURCE_SHA
    assert not hasattr(consumer, "fit") and not hasattr(consumer, "read_parquet")


def test_reference_gross_exact_target_copy_does_not_use_realized_exposure():
    data=market()
    base, replay, ref, exp, overlay=branch(data,"REFERENCE_GROSS")
    assert overlay.applied_count == 1
    assert replay.daily.nav.tolist() == base.daily.nav.tolist()
    assert replay.fills.notional.tolist() == base.fills.notional.tolist()
    assert ref.snapshots[(1,"ref")]["account"]["gross"] != pytest.approx(.5)


@pytest.mark.parametrize("action",["BUY","SELL","GROSS"])
def test_terminal_known_security_cannot_be_rebought_sold_or_marked(action):
    data=market(terminal=True)
    exp=exporter(data,terminal=True)
    event=terminal_event()
    blocked=[]
    def policy(j,ctx):
        snap=exp.capture(j,ctx)[0]
        target=reference(j,ctx)
        if j==3:
            command=dict(signal_index=3,path_id="ref",action=action,entrant_sid="SID_A",incumbent_sid="SID_A",
                         planner_intent=planner(snap,target_weight=.5))
            if action=="GROSS":
                command.update(gross=.5)
                command["planner_intent"].update(gross=.5,weights=[.5,0.],explicit_mask=[True,False])
            try: consumer.single_action_override(target,ctx,snap,command)
            except consumer.BlockedState as error: blocked.append(str(error))
        return target
    replay=run(data,exp,policy,events=[event])
    assert blocked
    assert len(replay.fills)==1
    assert replay.final_state["fractional_shares"][0,0]==0
    assert exp.snapshots[(3,"ref")]["stocks"][0]["pit32"] is None


def test_bound_quote_source_and_actual_age_are_in_exact_prefix():
    data=market()
    e=exporter(data)
    run(data,e)
    snap=e.snapshots[(1,"ref")]
    base=consumer.exact_prefix_identity(snap)
    for key,value in [("quote_source_sha256","0"*64),("holding_age_sessions",99)]:
        altered=deepcopy(snap)
        altered["prefix_payload"]["decision_state_stocks"][0][key]=value
        assert consumer.exact_prefix_identity(altered)!=base


def test_signal_mark_inconsistent_with_actual_engine_weight_is_blocked():
    def mutate(fields,j,ctx):
        if j==1: fields["signal_close"][0]=101.
    data=market(); e=exporter(data,mutate=mutate)
    with pytest.raises(consumer.BlockedState,match="SOURCE_MARK_CONTEXT"):
        run(data,e)


def test_hold_baseline_preserves_sell_restricted_existing_holding():
    data=market()
    sell=np.zeros((6,2),bool);sell[1,0]=True
    data=MarketArrays(data.dates,data.tickers,data.open,data.close,adv=data.adv,signal_asof=data.signal_asof,
        sell_restricted=sell,known_restrictions_evidence=[dict(signal_date=DATES[1],ticker="A",
            known_at=data.signal_asof[1],source_id="synthetic://restriction",reason="synthetic",sell_restricted=True)])
    base,replay,ref,exp,overlay=branch(data,"HOLD")
    assert overlay.applied_count==1
    assert ref.snapshots[(1,"ref")]["stocks"][0]["sell_eligible"] is False
    assert replay.final_units[0,0]==base.final_units[0,0]


@pytest.mark.parametrize("sid",["UNKNOWN","UNBOUND","nan","null","none","na","<NA>","A","","A2_TICKER_A","a2_ticker_a"])
def test_unknown_or_ticker_fallback_sid_is_blocked(sid):
    data=market()
    with pytest.raises(consumer.BlockedState,match="SID_TICKER_BINDING"):
        consumer.ReferenceStateExporter({sid:"A","SID_B":"B"},IDENTITY,provider(data),
            reference_path_by_path={"ref":"RAW_s10"})


@pytest.mark.parametrize("field",["terminal_available_at","quantity_available_at"])
def test_inactive_security_future_provenance_cannot_enter_prefix(field):
    data=market()
    def mutate(fields,j,ctx):
        fields["raw_buy_pool"][1]=False
        fields[field][1]=ctx.signal_asof+pd.Timedelta(days=1)
    exp=exporter(data,mutate=mutate)
    with pytest.raises(consumer.BlockedState,match="FUTURE"):
        run(data,exp)


def test_inactive_security_does_not_require_quote_or_pit32():
    data=market()
    def mutate(fields,j,ctx):
        fields["raw_buy_pool"][1]=False
        fields["signal_close"][1]=np.nan
        fields["pit32"][1,:]=np.nan
        fields["quote_qualified"][1]=False
        fields["quote_available_at"][1]=None
    exp=exporter(data,mutate=mutate)
    replay=run(data,exp)
    assert len(exp.snapshots[(1,"ref")]["stocks"])==1
    assert len(exp.snapshots[(1,"ref")]["prefix_payload"]["securities"])==2
    assert replay.final_cash[0]>=0


def test_existing_cash_catalogue_mapping_can_be_legal_market_subset():
    data=market(); exp=exporter(data)
    subset={"SID_A":"A"}
    source=binding([]);source["security_tickers"]=subset
    def policy(j,ctx):
        exp.capture(j,ctx)
        return reference(j,ctx)
    replay=consumer.run_observed_continuous_account(data,["ref"],policy,config(),exporter=exp,
        execution_friction=FRICTION,entitlement_enabled=True,entitlement_events=[],
        entitlement_security_tickers=subset,entitlement_source_binding=source)
    assert replay.daily.accounting_qualified.all()
    assert exp.snapshots[(1,"ref")]["stocks"][0]["is_held"]
    assert len(exp.snapshots[(1,"ref")]["prefix_payload"]["securities"])==2


@pytest.mark.parametrize("cash_mapping",[{"SID_A":"B"},{"UNKNOWN":"A"}])
def test_cash_catalogue_mapping_conflict_or_unknown_sid_is_blocked(cash_mapping):
    data=market(); exp=exporter(data)
    source=binding([]);source["security_tickers"]=cash_mapping
    with pytest.raises(consumer.BlockedState,match="OBSERVER_SECURITY_BINDING"):
        consumer.run_observed_continuous_account(data,["ref"],reference,config(),exporter=exp,
            execution_friction=FRICTION,entitlement_enabled=True,entitlement_events=[],
            entitlement_security_tickers=cash_mapping,entitlement_source_binding=source)
    assert exp.paths is None


def test_continuous_2023_2024_2025_account_and_receivable_cross_both_year_boundaries():
    dates=pd.to_datetime(["2023-12-29","2024-01-02","2024-12-30","2024-12-31","2025-01-02","2025-01-03"])
    old=market(terminal=True)
    data=MarketArrays(dates,old.tickers,old.open,old.close,adv=old.adv,
        signal_asof=[d.tz_localize("UTC")+pd.Timedelta(hours=21) for d in dates])
    payment=SourceBackedTerminalSettlement("TERMINAL_A","SID_A","2025-01-03",
        "2025-01-02T21:00:00+00:00",5.,USD_PER_RAW_OLD_SHARE,RAW_OLD_SHARE_COORDINATE,
        "TIER2_LOCAL_CANONICAL","synthetic://settlement","2"*64)
    event=SourceBackedTerminalEvent("TERMINAL_A","SID_A","A","2024-12-31T14:30:00+00:00",
        "2024-12-30T21:00:00+00:00",5.,"USD",USD_PER_RAW_OLD_SHARE,RAW_OLD_SHARE_COORDINATE,
        "synthetic://quantity","3"*64,"TIER2_LOCAL_CANONICAL","synthetic://terminal","4"*64,payment)
    exp=exporter(data,terminal=True)
    replay=run(data,exp,events=[event])
    assert exp.snapshots[(1,"ref")]["stocks"][0]["holding_age_sessions"]==0
    assert exp.snapshots[(2,"ref")]["stocks"][0]["holding_age_sessions"]==1
    assert exp.snapshots[(2,"ref")]["stocks"][0]["raw_fractional_shares"]==pytest.approx(15.)
    assert exp.snapshots[(3,"ref")]["account"]["receivable_value_usd"]==pytest.approx(75.)
    assert exp.snapshots[(4,"ref")]["account"]["receivable_value_usd"]==pytest.approx(75.)
    assert exp.snapshots[(4,"ref")]["account"]["spendable_cash_usd"]==pytest.approx(1498.5)
    assert exp.snapshots[(5,"ref")]["account"]["receivable_value_usd"]==0
    assert replay.final_cash[0]==pytest.approx(1573.5)
    assert replay.metadata["annual_reset"] is False
    assert len(replay.fills)==1
