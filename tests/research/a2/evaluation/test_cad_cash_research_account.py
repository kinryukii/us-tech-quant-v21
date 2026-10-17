"""Synthetic CAD rights; no FX collector, true prices or post2025 samples."""
from dataclasses import replace
import json
import numpy as np
import pandas as pd
import pytest
from scripts.v22 import corporate_action_transition_r1 as ca
from scripts.research.a2.evaluation import consensus_shareholder_account as bridge
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays, TargetDecision
from test_stock_distribution_research_account import scoped_authority, ref


def foreign_event(**changes):
    fields=dict(event_id="synthetic CAD dividend",action_type="CASH_DIVIDEND",old_security_id="TRP_source_security",ticker="TRP",
        ex_date="2025-09-29",record_date="2025-09-29",pay_date="2025-10-31",available_at="2025-07-31T20:00:00Z",
        cash_per_old_share=.85,currency="CAD",amount_unit=ca.CAD_PER_RAW_OLD_SHARE,
        quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,source_type="TIER2_LOCAL_CANONICAL",
        source_reference="synthetic://declared-CAD-common",source_fingerprint="c"*64)
    fields.update(changes);return ca.SourceBackedForeignCashEvent(**fields)


def fx(day="2025-09-22", observation="2025-09-19", rate=2.):
    available=(pd.Timestamp(day)+pd.Timedelta(hours=23,minutes=59,seconds=59)).tz_localize("America/New_York").tz_convert("UTC")
    return ca.SourceBackedFXMark("CAD",ca.CAD_PER_USD,observation,str(available),rate,"synthetic://dated-Fed-H10","d"*64)


def apply(e,day,*,state=None,mark=None,positions=None):
    return ca.apply_entitlement_lifecycle((e,),positions or {"TRP_source_security":3.},11.,execution_date=day,
        session_open_at=(pd.Timestamp(day)+pd.Timedelta(hours=9,minutes=30)).tz_localize("America/New_York"),
        security_tickers={"TRP_source_security":"TRP"},quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,
        state=state,enabled=True,foreign_fx_mark=mark,foreign_conversion_friction_bps=25.)


@pytest.fixture
def foreign_authority(scoped_authority,monkeypatch):
    base=scoped_authority(())
    root=bridge.CHILD_RUN
    contract=root/"ACCOUNT_FX_CONVENTION_SCOPE.json"
    contract.write_text(json.dumps(dict(schema="CONSENSUS_SOURCE_COMPLETION_CAD_CLAIM_CONVENTION_R1",task_id=bridge.TASK,
        research_id=bridge.CHILD_RESEARCH_ID,continuation_scope_ref=bridge.CONTINUATION_REF,account_convention_scope_ref=bridge.CONVENTION_REF,
        conversion_friction_bps=25.,declared_cad_amount_as_usd_allowed=False,actual_broker_fx_rate_fee_payment_or_tax_certified=False)))
    monkeypatch.setattr(bridge,"FX_CONVENTION_REF",ref(contract))
    qualification=root/"FX_SOURCE_AVAILABILITY_QUALIFICATION.json"
    qualification.write_text(json.dumps(dict(schema="CONSENSUS_FX_RELEASE_DATE_AVAILABILITY_QUALIFICATION_R1",task_id=bridge.TASK,
        research_id=bridge.CHILD_RESEARCH_ID,fx_convention_scope_ref=bridge.FX_CONVENTION_REF,
        available_at_convention="END_OF_CERTIFIED_RELEASE_DATE_AMERICA_NEW_YORK_23_59_59_CONVERTED_TO_UTC",
        actual_timestamp_authority="UNKNOWN_RETAINED",same_release_date_market_close_mark_allowed=False)))
    monkeypatch.setattr(bridge,"FX_AVAILABILITY_REF",ref(qualification))
    def make(events):
        return bridge.make_task_authority(events,frozen_contract_ref=base["frozen_contract_ref"],source_scope_ref=base["source_scope_ref"],
            market_source_binding=base["market_source_binding"],continuation_scope_ref=bridge.CONTINUATION_REF,
            account_convention_scope_ref=bridge.CONVENTION_REF,account_fx_convention_scope_ref=bridge.FX_CONVENTION_REF,
            fx_source_availability_qualification_ref=bridge.FX_AVAILABILITY_REF)
    return make


def test_release_date_close_unavailable_and_latest_published_inverse_unit():
    old=fx();new=fx("2025-09-29","2025-09-26",4.)
    close=pd.Timestamp("2025-09-29 16:00:00",tz="America/New_York")
    assert ca.select_foreign_fx_mark((new,old),as_of=close)==old
    assert ca.select_foreign_fx_mark((new,old),as_of=pd.Timestamp("2025-09-30 09:30",tz="America/New_York"))==new
    with pytest.raises(ValueError,match="PUBLICATION_BOUND"):
        replace(new,available_at="2025-09-29T20:15:00Z")
    with pytest.raises(ValueError,match="PRE2026_ONLY"):
        ca.select_foreign_fx_mark((old,),as_of="2026-01-01T00:00:00Z")


def test_cad_claim_nonspendable_gross_mark_and_payment_fee_once_after_sale():
    e=foreign_event();ex=apply(e,"2025-09-29",mark=fx())
    assert ex.cash==11. and ex.state.foreign_cash_receivables[0].amount_foreign==pytest.approx(2.55)
    assert ex.receivable_value_usd==pytest.approx(1.275) and ex.state.receivables==()
    mark=fx("2025-10-27","2025-10-24",4.)
    pay=apply(e,"2025-11-03",state=ex.state,mark=mark,positions={"TRP_source_security":0.})
    assert pay.cash==pytest.approx(11.+.6375*(1-.0025)) and pay.fx_conversion_fee_usd==pytest.approx(.6375*.0025)
    assert pay.state.foreign_cash_receivables==() and pay.state.paid_event_ids==(e.event_id,)
    again=apply(e,"2025-11-04",state=pay.state,mark=mark,positions={"TRP_source_security":0.})
    assert again.cash==11. and again.fx_conversion_fee_usd==0. and not any(r["phase"].startswith("FOREIGN_CASH_PAID") for r in again.records)


def test_cross2026_pay_remains_cad_claim_and_pre2026_gross_mark_only():
    e=foreign_event(ex_date="2025-12-31",record_date="2025-12-31",pay_date="2026-01-30",available_at="2025-11-06T20:00:00Z")
    out=apply(e,"2025-12-31",mark=fx("2025-12-29","2025-12-26",2.))
    assert out.cash==11. and out.receivable_value_usd==pytest.approx(1.275)
    assert out.state.foreign_cash_receivables[0].pay_date=="2026-01-30"
    assert out.state.foreign_cash_receivables[0].currency=="CAD" and out.fx_conversion_fee_usd==0.


def test_missing_fx_preserves_currency_right_and_blocks_nav_not_fabricated_usd():
    out=apply(foreign_event(),"2025-09-29")
    assert not out.accounting_qualified and out.cash==11.
    assert out.state.foreign_cash_receivables[0].amount_foreign==pytest.approx(2.55)
    with pytest.raises(ValueError,match="ENABLED_SOURCE_MARKED"):
        ca.apply_entitlement_lifecycle((),{},11.,execution_date="2025-09-30",session_open_at="2025-09-30T13:30:00Z",
            security_tickers={},quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,state=out.state,enabled=False)
    with pytest.raises(ValueError,match="GROSS_CAD"):
        foreign_event(currency="USD")


def test_full_original_cash_pipeline_gross_cad_nav_net_cash_single_conversionfee(foreign_authority):
    dates=pd.bdate_range("2025-09-25","2025-11-04")
    prices=np.full((len(dates),1),100.);prices[dates>=pd.Timestamp("2025-09-29")]=99.575
    m=MarketArrays(dates,["TRP"],prices.copy(),prices.copy(),adv=np.full(prices.shape,1e9))
    e=foreign_event();mapping={e.old_security_id:e.ticker}
    def policy(j,ctx):
        weights=np.zeros_like(ctx.current_units);explicit=np.zeros_like(weights,bool)
        if j==0:weights[:,0]=.1;explicit[:,0]=True
        return TargetDecision(weights,explicit)
    r=bridge.run_shareholder_cash_account(m,["p"],policy,task_authority=foreign_authority((e,)),settlement_calendar=dates,
        entitlement_events=(e,),entitlement_security_tickers=mapping,entitlement_source_binding=dict(
            status="SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND",source_fingerprint="e"*64,event_fingerprints=[e.event_fingerprint],
            security_tickers=mapping,quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE),
        foreign_fx_marks=(fx(),fx("2025-10-27","2025-10-24",4.)))
    fees=r.entitlements.loc[r.entitlements.phase.eq("FOREIGN_CASH_PAID_AND_CONVERTED_RESEARCH")]
    assert len(fees)==1 and fees.paid_gross_usd.iloc[0]==pytest.approx(.6375)
    assert fees.fx_conversion_fee_usd.iloc[0]==pytest.approx(.00159375)
    assert fees.session.iloc[0]=="2025-11-03"
    assert r.daily.fx_conversion_fee_usd.sum()==pytest.approx(.00159375)
    assert r.final_cash[0]==pytest.approx(2699.7+.6375-.00159375)
    assert r.final_state["foreign_cash_receivables"]==() and r.audit["actual_cash_flow_identity_error_max"]<1e-8
    assert not r.metadata["actual_broker_fx_payment_fee_or_tax_certified"]


def test_exact_fx_scope_custody_required_and_original_usd_class_unchanged(foreign_authority):
    e=foreign_event();authority=foreign_authority((e,))
    with pytest.raises(ValueError,match="EXACT_FROZEN_CAD"):
        bridge.validate_task_authority((e,),dict(authority,fx_source_availability_qualification_ref=dict(bridge.FX_AVAILABILITY_REF,sha256="f"*64)))
    with pytest.raises(ValueError,match="CURRENCY_NOT_USD"):
        ca.SourceBackedEntitlementEvent(**{k:getattr(e,k) for k in e.__dataclass_fields__})


def test_conflicting_published_mark_versions_reject_both_orders_and_identical_dedup():
    old=fx();conflict=replace(old,currency_per_usd=4.)
    asof=pd.Timestamp("2025-09-29 16:00",tz="America/New_York")
    for marks in [(old,conflict),(conflict,old),(old,replace(old,source_fingerprint="e"*64))]:
        with pytest.raises(ValueError,match="AMBIGUOUS_PUBLISHED_FX"):
            ca.select_foreign_fx_mark(marks,as_of=asof)
    assert ca.select_foreign_fx_mark((old,old),as_of=asof)==old
