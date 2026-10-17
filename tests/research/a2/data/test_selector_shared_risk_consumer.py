"""Synthetic-only identity/clock/domain tests; never load real B states or outcomes."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from scripts.research.a2.data import selector_shared_risk_consumer as c


def fixtures():
    r=dict(method="SHR_HP",as_of="2023-01-03T21:00:00+00:00",cutoff="2022-12-30T21:00:00+00:00",
        assets=["B","A"],asset_uids={"A":"037833100","B":"009066101"},asset_epochs={"A":"epoch-a","B":"epoch-b"},
        status="CONDITIONAL_FROZEN_HISTORY_MECHANISM",domain_role="FULL_REQUESTED_POOL",reusable=True,
        exact_reuse_only=True,strict_PIT_promotion_eligible=False,admission="CONDITIONAL_SOURCE_ONLY_EXACT_STATE",
        horizon_sessions=5,covariance_shape=[2,2],finite_check=True,psd_check="CHOLESKY_WITH_DECLARED_ROUNDOFF_RIDGE",
        source_contract=dict(path="D:/synthetic.json",sha256="d"*64),full_pool_policy_qualification_granted=False)
    source=dict(id="source",version="v",sha256="a"*64,execution_semantics=dict(
        scientific_contract_sha256="d"*64,status="FROZEN_HISTORY_MECHANISM_SOURCE_BOUND",
        return_coordinate="shareholder_value_open_return",identity_epoch="pool-epoch",
        strict_PIT_promotion_eligible=False,quote_qualified=False,historical_authority_status="UNKNOWN",
        observation_time_assumed=True,assumed_observation_at=r["cutoff"],actual_snapshot_timestamp="2026-10-03T07:00:00+00:00"))
    u=pd.DataFrame(dict(ticker=["A","B"],security_uid=["CUSIP:037833100","CUSIP:009066101"]))
    return r,u,source


def qualify(r=None,u=None,source=None,at="2023-01-04T21:00:00+00:00",cadence="quarterly"):
    rr,uu,ss=fixtures()
    return c.qualify_current_u(rr if r is None else r,uu if u is None else u,at,cadence,ss if source is None else source)


def test_original_bank_order_not_consumer_order_and_policy_false_is_not_missing():
    x=qualify()
    assert x["ordered_assets"]==["B","A"]
    assert x["ordered_consumer_uids"]==["CUSIP:009066101","CUSIP:037833100"]
    assert x["status"]=="SHARED_EXACT_REUSE"
    assert x["strict_PIT_promotion_eligible"] is False


@pytest.mark.parametrize("bad",["AAPL","CUSIP:037833100","03783310",None,"03783310a"])
def test_namespace_never_ticker_stitches_or_guesses(bad):
    with pytest.raises(ValueError,match="CUSIP"): c.namespace(bad)


@pytest.mark.parametrize("kind",["uid","extra","missing","duplicate_uid","duplicate_ticker"])
def test_full_u_exact_domain(kind):
    r,u,s=fixtures()
    if kind=="uid": u.loc[0,"security_uid"]="CUSIP:111111111"
    if kind=="extra": u=pd.concat([u,pd.DataFrame(dict(ticker=["C"],security_uid=["CUSIP:111111111"]))],ignore_index=True)
    if kind=="missing": u=u.iloc[:1]
    if kind=="duplicate_uid": u.loc[0,"security_uid"]=u.loc[1,"security_uid"]
    if kind=="duplicate_ticker": u.loc[0,"ticker"]="B"
    with pytest.raises(ValueError): qualify(r,u,s)


@pytest.mark.parametrize("at,cadence",[("2023-01-03T20:59:59+00:00","quarterly"),("2023-04-03T20:00:00+00:00","quarterly"),("2023-02-01T21:00:00+00:00","monthly"),("2026-01-02T21:00:00+00:00","quarterly"),("2023-01-04","quarterly")])
def test_state_clock_native_period_and_future(at,cadence):
    with pytest.raises(ValueError): qualify(at=at,cadence=cadence)


@pytest.mark.parametrize("change",["late","strict","snapshot","epoch","coordinate","contract"])
def test_source_clock_and_identity(change):
    r,u,s=fixtures();e=s["execution_semantics"]
    if change=="late": e["assumed_observation_at"]="2023-01-03T21:00:00+00:00"
    if change=="strict": e["strict_PIT_promotion_eligible"]=True
    if change=="snapshot": e["actual_snapshot_timestamp"]="2022-01-01T21:00:00+00:00"
    if change=="epoch": e["identity_epoch"]=""
    if change=="coordinate": e["return_coordinate"]="stock_price_close_proxy"
    if change=="contract": e["scientific_contract_sha256"]="c"*64
    with pytest.raises(ValueError): qualify(r,u,s)


@pytest.mark.parametrize("key,value",[("covariance_shape",[1,2]),("finite_check",False),("psd_check","UNKNOWN"),("horizon_sessions",20),("horizon_sessions",True),("domain_role","CONDITIONAL_COHORT")])
def test_metadata_headers_and_native_horizon(key,value):
    r,u,s=fixtures();r[key]=value
    with pytest.raises(ValueError): qualify(r,u,s)


def test_r3_missing_shape_header_deferred_never_fabricated():
    r,u,s=fixtures();r.pop("status");r["original_status"]="PASS_FROZEN_HISTORY_MECHANISM"
    for k in ("covariance_shape","finite_check","psd_check","horizon_sessions"): r.pop(k)
    x=qualify(r,u,s)
    assert x["actual_numeric_shape_check"]=="DEFERRED_UNTIL_FORMAL_FREEZE"


def test_current_u_hash_order_invariant_but_uid_sensitive():
    r,u,s=fixtures();assert c.u_hash(u)==c.u_hash(u.iloc[::-1])
    v=u.copy();v.loc[0,"security_uid"]="CUSIP:111111111";assert c.u_hash(u)!=c.u_hash(v)


def test_admission_needs_frozen_full_u_date_proof_and_single_state():
    r,u,s=fixtures();day="2023-01-04";q=dict(research_id=c.ID,status="METADATA_QUALIFIED_PARTIAL",
        full_u_day_sha256={day:c.u_hash(u)},families={"R17_HIERARCHICAL_POSTERIOR":dict(eligible_dates=[day])},
        state_refs=[dict(bank="R4",cadence="quarterly",record=r,source_context=s,eligible_dates=[day])])
    ss,order=c.admit_state(q,"R17_HIERARCHICAL_POSTERIOR",u,day+"T21:00:00+00:00")
    assert ss["record"]["method"]=="SHR_HP"
    with pytest.raises(ValueError): c.admit_state(q,"R17_HIERARCHICAL_POSTERIOR",u,"2023-01-05T21:00:00+00:00")
    q["state_refs"].append(deepcopy(q["state_refs"][0]))
    with pytest.raises(ValueError,match="SINGLE"): c.admit_state(q,"R17_HIERARCHICAL_POSTERIOR",u,day+"T21:00:00+00:00")


def test_raw_future_footer_blocks_before_body_read(tmp_path,monkeypatch):
    p=tmp_path/"future.parquet"
    pq.write_table(pa.Table.from_pandas(pd.DataFrame(dict(signal_date=pd.to_datetime(["2025-12-31","2026-01-02"]),ticker=["A","A"],security_uid=["CUSIP:037833100"]*2))),p)
    monkeypatch.setattr(c,"safe_d",lambda p:Path(p))
    monkeypatch.setattr(c.pq,"read_table",lambda *a,**kw:pytest.fail("future body projected"))
    with pytest.raises(ValueError,match="PHYSICAL_PRE2026"): c.raw_keys(dict(path=str(p),sha256="0"*64))


def test_raw_projection_has_no_score_rank_or_y(tmp_path,monkeypatch):
    p=tmp_path/"keys.parquet";d=pd.DataFrame(dict(signal_date=pd.to_datetime(["2023-01-03"]),ticker=["A"],security_uid=["CUSIP:037833100"],score=[999.],rank=[1],Y=[888.]))
    pq.write_table(pa.Table.from_pandas(d),p)
    monkeypatch.setattr(c,"safe_d",lambda p:Path(p));monkeypatch.setattr(c,"pin",lambda r:Path(r["path"]))
    original=c.pq.read_table
    def body(*a,**kw):
        assert kw["columns"]==c.KEYS
        return original(*a,**kw)
    monkeypatch.setattr(c.pq,"read_table",body)
    out=c.raw_keys(dict(path=str(p),sha256="0"*64));assert list(out)==c.KEYS


def test_pickle_never_called_before_formal_freeze(monkeypatch):
    import joblib
    monkeypatch.setattr(c,"pin",lambda x:Path(x["path"]))
    monkeypatch.setattr(c,"readj",lambda p:{})
    monkeypatch.setattr(joblib,"load",lambda *a,**kw:pytest.fail("pickle before freeze"))
    ref=dict(path="D:/synthetic.json",sha256="a"*64)
    with pytest.raises(ValueError,match="FORMAL_FREEZE"):
        c.load_state("R17_HIERARCHICAL_POSTERIOR",design_ref=ref,review_ref=ref,qualification_ref=ref,current_u=fixtures()[1],decision_at="2023-01-04T21:00:00+00:00")

def fake_native_load(monkeypatch,bank='R4',method='SHR_HP',state_change=None):
    """No physical model is opened: fake joblib returns an owner-format namespace."""
    from dataclasses import asdict
    from types import SimpleNamespace
    from scripts.research.a2.risk.shared_risk_engine_r2 import SourceReceipt
    import joblib
    r,u,_=fixtures();r.update(method=method,risk_state_id='synthetic-state',artifact=dict(path='D:/fake_model.joblib',sha256='f'*64))
    if bank=='R3':
        r.pop('status');r['original_status']='PASS_FROZEN_HISTORY_MECHANISM';r['stage_id']='full'
    status=r.get('status',r.get('original_status'))
    native=SourceReceipt('source','v','a'*64,r['cutoff'],synthetic=False,mechanism=True,
        status='FROZEN_HISTORY_MECHANISM_SOURCE_BOUND',return_coordinate='shareholder_value_open_return',identity_epoch='pool-epoch',
        quote_qualified=False,historical_authority_status='UNKNOWN',strict_PIT_promotion_eligible=False,
        scientific_contract_identity='B_SYNTHETIC_FORMAT_TEST',scientific_contract_sha256='d'*64,
        actual_snapshot_timestamp='2026-10-03T07:00:00+00:00',observation_time_assumed=True,benchmark_proxy_allowed=False)
    source=native.cache_identity();matrix=np.diag([.04,.09])
    r['covariance_sha256']=c.content_hash(matrix)
    state=SimpleNamespace(status=status,risk_state_id=r['risk_state_id'],method=method,assets=tuple(r['assets']),horizon=5,
        as_of=r['as_of'],cutoff=r['cutoff'],return_coordinate='shareholder_value_open_return',identity_epoch='pool-epoch',
        source_receipt=asdict(native),blocked_assets=(),covariance=matrix)
    if bank=="R3":state.source_receipt.update(cutoff=r["cutoff"],horizon_sessions=5)
    if state_change:state_change(state)
    day='2023-01-04';family={'SHR_HP':'R17_HIERARCHICAL_POSTERIOR','SHR_EB':'R18_EB','RD':'R06_EWMA'}[method]
    q=dict(research_id=c.ID,status='METADATA_QUALIFIED_PARTIAL',spec={},full_u_day_sha256={day:c.u_hash(u)},
        families={family:dict(eligible_dates=[day])},state_refs=[dict(bank=bank,cadence='monthly' if bank=='R3' else 'quarterly',
        record=r,source_context=source,eligible_dates=[day])])
    dr=dict(path='D:/fake_design.json',sha256='d'*64);qr=dict(path='D:/fake_qualification.json',sha256='e'*64);rr=dict(path='D:/fake_review.json',sha256='c'*64)
    source_pins={str(Path(c.__file__).resolve()):c.sha(c.__file__)}
    d=dict(research_id=c.ID,risk_qualification=qr,strict_PIT_promotion_eligible=False,test2026_locked=True,sources=source_pins)
    review=dict(status='PASS',research_id=c.ID,design_sha256=dr['sha256'],source_pins=source_pins)
    documents={dr['path']:d,qr['path']:q,rr['path']:review}
    monkeypatch.setattr(c,'pin',lambda item:Path(item['path']))
    monkeypatch.setattr(c,'readj',lambda p:documents[str(p).replace('\\','/')])
    calls=[]
    monkeypatch.setattr(joblib,'load',lambda path:(calls.append(str(path)) or state))
    return family,dict(design_ref=dr,review_ref=rr,qualification_ref=qr,current_u=u,decision_at=day+'T21:00:00+00:00'),state,calls


@pytest.mark.parametrize('bank,method',[('R4','SHR_HP'),('R4','SHR_EB'),('R3','RD')])
def test_actual_owner_dict_receipt_and_exact_conditional_or_pass_status(monkeypatch,bank,method):
    family,args,state,calls=fake_native_load(monkeypatch,bank,method)
    loaded,order=c.load_state(family,**args)
    assert loaded is state and len(calls)==1
    assert isinstance(loaded.source_receipt,dict)  # Original persistent bytes/type are not mutated.
    assert loaded.status==('CONDITIONAL_FROZEN_HISTORY_MECHANISM' if bank=='R4' else 'PASS_FROZEN_HISTORY_MECHANISM')
    assert order['ordered_assets']==['B','A']
    assert order['strict_PIT_promotion_eligible'] is False


@pytest.mark.parametrize('field,value',[('source_version','changed'),('quote_qualified',True),('strict_PIT_promotion_eligible',True),
    ('available_at','2023-01-03T21:00:00+00:00'),('identity_epoch','changed'),('scientific_contract_sha256','b'*64)])
def test_restored_receipt_guards_precede_covariance(monkeypatch,field,value):
    class CovarianceMustNotBeRead:
        def __array__(self,*a,**kw):pytest.fail('covariance accessed before source authority guard')
    def change(state):
        state.source_receipt[field]=value
        state.covariance=CovarianceMustNotBeRead()
    family,args,_,_=fake_native_load(monkeypatch,state_change=change)
    with pytest.raises(ValueError):c.load_state(family,**args)


def test_conditional_registration_cannot_be_promoted_to_pass(monkeypatch):
    class CovarianceMustNotBeRead:
        def __array__(self,*a,**kw):pytest.fail('covariance accessed before exact status check')
    def change(state):
        state.status='PASS_FROZEN_HISTORY_MECHANISM'
        state.covariance=CovarianceMustNotBeRead()
    family,args,_,_=fake_native_load(monkeypatch,state_change=change)
    with pytest.raises(ValueError,match='IDENTITY_OR_SOURCE'):c.load_state(family,**args)

@pytest.mark.parametrize('field,value',[('cutoff','2022-12-29T21:00:00+00:00'),('horizon_sessions',20),('horizon_sessions',True),('unexpected_revision','UNKNOWN')])
def test_r3_receipt_extra_clock_horizon_checked_before_covariance(monkeypatch,field,value):
    class CovarianceMustNotBeRead:
        def __array__(self,*a,**kw):pytest.fail('covariance accessed before persisted source extra fields guard')
    def change(state):
        state.source_receipt[field]=value
        state.covariance=CovarianceMustNotBeRead()
    family,args,_,_=fake_native_load(monkeypatch,bank='R3',method='RD',state_change=change)
    with pytest.raises(ValueError,match='RECEIPT'):c.load_state(family,**args)