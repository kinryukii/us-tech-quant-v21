"""Synthetic daily equivalence against the unchanged metadata identity helper."""
import pandas as pd
import pytest
from scripts.research.a2.evaluation import joint_policy_metadata_adapter_r4 as m
from scripts.research.a2.data.shared_risk_inputs_r3 import _calendar,_clock
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash


class Reader:
    def __init__(self,frame):self.frame=frame;self.audit=[]
    def read(self,name,columns,**kw):
        assert not set(columns)&m.old.FORBIDDEN
        self.audit.append((name,columns,kw))
        if name=='raw_open_close':
            return pd.DataFrame({'ticker':['A','B'],'trade_date':kw['day']})
        result=self.frame.copy()
        if kw.get('start') is not None:result=result.loc[result.signal_date>=kw['start']]
        if kw.get('stop') is not None:result=result.loc[result.signal_date<kw['stop']]
        return result.loc[:,list(columns)]


def inputs():
    days,_=_calendar(pd.bdate_range('2022-01-01','2025-12-31'))
    selected=pd.bdate_range('2022-12-29','2023-01-13')
    frame=pd.DataFrame([dict(ticker=a,signal_date=d,security_id='U'+a,feature_available=True,
        all_features_finite=True,feature_source=m.old.FEATURE_TAGS[0]) for d in selected for a in ('A','B')])
    witness=m.ImmutableHistory('SYNTHETIC','a'*64,0,0,0,synthetic=True)
    return days,selected,frame,witness


@pytest.mark.parametrize('case',['stable','uid_change','same_uid_gap','same_uid_duplicate','domain_flag','decision_gap'])
def test_exact_original_helper_equivalence_including_same_uid_reopen(case):
    days,selected,frame,witness=inputs()
    chosen=pd.Timestamp('2023-01-05')
    if case=='uid_change':frame.loc[frame.ticker.eq('B')&frame.signal_date.ge(chosen),'security_id']='NEW_UID_B'
    elif case=='same_uid_gap':frame=frame.loc[~(frame.ticker.eq('B')&frame.signal_date.eq(chosen))]
    elif case=='same_uid_duplicate':frame=pd.concat([frame,frame.loc[frame.ticker.eq('B')&frame.signal_date.eq(chosen)]],ignore_index=True)
    elif case=='domain_flag':frame.loc[frame.ticker.eq('B')&frame.signal_date.eq(chosen),'feature_available']=False
    requested=selected[selected>=pd.Timestamp('2023-01-03')]
    if case=='decision_gap':requested=requested[requested!=chosen]
    reader=Reader(frame)
    adapter=m.EpochCarryMetadataPool(reader,days,witness=witness,audit_dates=requested)
    results={}
    for day in requested:
        actual=adapter(day)
        legal=frame.loc[frame.signal_date<=day]
        raw=pd.DataFrame({'ticker':['A','B'],'trade_date':day})
        expected=m.old.current_pool(legal,raw,days,_clock(day))
        assert content_hash(m.identity(actual))==content_hash(m.identity(expected))
        results[day]=m.identity(actual)
    assert all(r['exact_identity_equal'] for r in adapter.audits)
    if case=='stable':assert adapter.full_helper_calls==1 and adapter.carry_calls==len(requested)-1
    else:assert adapter.full_helper_calls>=2
    if case in {'same_uid_gap','same_uid_duplicate'}:
        reopened=pd.Timestamp('2023-01-06')
        assert results[reopened]['asset_uids']['B']=='UB'
        assert results[reopened]['segment_starts']['B']=='2023-01-06'
        assert results[reopened]['asset_epochs']['B']!=results[pd.Timestamp('2023-01-04')]['asset_epochs']['B']


def test_past_rewrite_window_blocks_before_carry():
    days,selected,frame,witness=inputs()
    reader=Reader(frame)
    adapter=m.EpochCarryMetadataPool(reader,days,witness=witness)
    adapter('2023-01-03')
    original=reader.read
    def bad(name,columns,**kw):
        result=original(name,columns,**kw)
        if name=='prediction_features':result=pd.concat([result,frame.loc[frame.signal_date.eq('2023-01-03')]],ignore_index=True)
        return result
    reader.read=bad
    with pytest.raises(m.policy.PolicyInputBlocked,match='REWRITES_PAST'):adapter('2023-01-04')


def test_synthetic_witness_cannot_be_attached_to_real_reader():
    days,selected,frame,witness=inputs()
    real=object.__new__(m.old.ProjectedReader)
    with pytest.raises(m.policy.PolicyInputBlocked,match='SYNTHETIC_WITNESS'):m.EpochCarryMetadataPool(real,days,witness=witness)


def test_R2_unknown_rows_force_original_and_admin_scope_is_exact(monkeypatch):
    from scripts.research.a2.evaluation import joint_policy_metadata_adapter_r4_r2 as r2
    days,selected,frame,witness=inputs()
    extra=frame.loc[frame.ticker.eq('A')&frame.signal_date.eq('2023-01-04')].copy()
    extra['ticker']='OUTSIDE';extra['security_id']=None;extra['feature_available']=False
    frame=pd.concat([frame,extra],ignore_index=True)
    adapter=r2.EpochCarryMetadataPoolR2(Reader(frame),days,witness=witness)
    adapter('2023-01-03');actual=adapter('2023-01-04')
    assert adapter.full_helper_calls==2 and adapter.carry_calls==0
    raw=pd.DataFrame({'ticker':['A','B'],'trade_date':pd.Timestamp('2023-01-04')})
    expected=m.old.current_pool(frame.loc[frame.signal_date.le('2023-01-04')],raw,days,_clock('2023-01-04'))
    assert content_hash(m.identity(actual))==content_hash(m.identity(expected))
    spec={'original_main':[{'id':'OLD','risk':'R0'}],'original_sensitivity':[{'id':'SENS','scope':'SENSITIVITY'}]}
    captured={}
    result=r2.canonical_inherited(lambda run,s:captured.update(s) or 'PASS',None,spec)
    assert result=='PASS' and captured['original_main'][0]['scope']=='MAIN'
    assert 'scope' not in spec['original_main'][0] and captured['original_sensitivity']==spec['original_sensitivity']
