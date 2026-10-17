"""Synthetic controller boundaries; never opens production inputs or runs models."""
import copy
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import selector_constrained_risk as c


def raw_day():
    return pd.DataFrame({'signal_date':pd.Timestamp('2025-01-02'),'security_uid':['CUSIP:'+str(i).zfill(9) for i in range(50)],
        'ticker':['T'+str(i) for i in range(50)],'U_t_fingerprint':'synthetic','rank':np.arange(1,51),'score':-np.arange(1,51,dtype=float)})


def fake_q():
    q={'families':{},'state_refs':[],'full_u_day_sha256':{}}
    for family,(_,method,_) in c.consumer.METHODS.items():
        count=115 if family.startswith(('R06','R08')) else 194
        dates=pd.bdate_range('2023-01-03',periods=count).strftime('%Y-%m-%d').tolist()
        q['families'][family]={'eligible_dates':dates}
        for k,part in enumerate(np.array_split(np.array(dates),12)):
            q['state_refs'].append({'record':{'method':method,'risk_state_id':family+str(k),'artifact':{'path':'synthetic','sha256':'a'*64},
                'as_of':'2023-01-03T21:00:00Z','cutoff':'2023-01-02T21:00:00Z'},'eligible_dates':part.tolist()})
        q['full_u_day_sha256'].update({d:'b'*64 for d in dates})
    return q


def test_exact_physical_dag():
    dag=c.physical_dag(fake_q())
    assert len(dag['nodes'])==3708 and len({n['id'] for n in dag['nodes']})==3708
    assert dag['new_learned_states']==0 and dag['reused_risk_states']==48
    assert dag['optimizer_solve_ceiling']<dag['optimizer_solve_hard_cap']
    assert {n['method'] for n in dag['nodes']}==set(c.rules.METHODS)
    assert dag['D12']['minimum_partial_solves']==97000


@pytest.mark.parametrize('wrong',['duplicate','drop','alias'])
def test_dag_no_slot_duplicates_missing_or_alias(wrong):
    q=fake_q()
    if wrong=='duplicate':q['state_refs'].append(copy.deepcopy(q['state_refs'][0]))
    elif wrong=='drop':q['families']['R06_EWMA']['eligible_dates'].pop()
    else:q['state_refs'][0]['record']['method']='R0'
    with pytest.raises(ValueError):c.physical_dag(q)


def test_full_u_panel_no_padding_or_weights():
    g=raw_day();uids=list(g.security_uid);chosen=uids[:19]+[uids[21]]
    panel=c.membership_panel(g,chosen,'C13_R06_D02')
    assert len(panel)==len(g) and panel[c.shared.KEY].equals(g[c.shared.KEY])
    assert panel['rank'].le(20).sum()==20
    assert set(panel.loc[panel['rank'].le(20),'security_uid'])==set(chosen)
    assert panel.score.eq(-panel['rank']).all()
    assert not {'weight','gross','cash','target','return_value'}&set(panel)


@pytest.mark.parametrize('kind',['core','outside','duplicate','count'])
def test_panel_identity_geometry_rejects(kind):
    g=raw_day();chosen=list(g.security_uid.iloc[:20])
    if kind=='core':chosen[0]=g.security_uid.iloc[21]
    elif kind=='outside':chosen[-1]=g.security_uid.iloc[44]
    elif kind=='duplicate':chosen[-1]=chosen[0]
    else:chosen.pop()
    with pytest.raises(ValueError):c.membership_panel(g,chosen,'C13_R06_D02')


def test_panel_future_append_does_not_change_selection():
    g=raw_day();chosen=list(g.security_uid.iloc[:20]);p=c.membership_panel(g,chosen,'C13_R06_D02')
    future=g.copy();future['signal_date']=pd.Timestamp('2026-01-02')
    # Date batches are selected independently; future batches are never admitted.
    combined=pd.concat([g,future]).groupby('signal_date')
    same=c.membership_panel(combined.get_group(pd.Timestamp('2025-01-02')),chosen,'C13_R06_D02')
    pd.testing.assert_frame_equal(p,same)


def full_ledger():
    dag=c.physical_dag(fake_q())
    events=[dict(key=n['id'],status='SUCCEEDED',backend_entered=True) for n in dag['nodes']]
    ledger=dict(events=events,learned_total=0,new_state_estimations=0,charged_reservations=3708,
        actual_solver_calls=3708,success_count=3708,failed_count=0,counts={'deterministic_transform':3708})
    assembly=dict(complete_candidates=[],panels={},failed_or_untestable=dict.fromkeys(c.ev.ROLES,'synthetic'))
    return dag,ledger,assembly


def test_complete_terminal_dag():
    dag,ledger,assembly=full_ledger();c.validate_terminal_solver(dag,ledger,assembly)


@pytest.mark.parametrize('mutation',['empty','missing','duplicate','extra','reserved','fit','not_entered','count','forgotten_exposure','fake_complete'])
def test_terminal_gate_rejects_incomplete_or_invalid(mutation):
    dag,l,a=full_ledger()
    if mutation=='empty':l['events']=[]
    elif mutation=='missing':l['events'].pop()
    elif mutation=='duplicate':l['events'][-1]=l['events'][0]
    elif mutation=='extra':l['events'].append(dict(key='extra',status='FAILED',backend_entered=False))
    elif mutation=='reserved':l['events'][0]['status']='RESERVED'
    elif mutation=='fit':l['learned_total']=1
    elif mutation=='not_entered':l['events'][0]['backend_entered']=False;l['actual_solver_calls']-=1
    elif mutation=='count':l['charged_reservations']=1
    elif mutation=='forgotten_exposure':a['failed_or_untestable'].pop(c.ev.ROLES[0])
    else:a['complete_candidates']=[c.ev.ACTIVE_ROLES[0]]
    with pytest.raises(ValueError):c.validate_terminal_solver(dag,l,a)


def test_failed_presolver_reservation_retained():
    dag,l,a=full_ledger();l['events'][0].update(status='FAILED',backend_entered=False)
    l.update(actual_solver_calls=3707,success_count=3707,failed_count=1)
    c.validate_terminal_solver(dag,l,a)


def test_actual_budget_failure_keeps_reservation_no_retry():
    durable=[];b=c.StateBudget(2400,limits={'deterministic_transform':1},reserve_callback=durable.append)
    e=b.reserve('one','deterministic_transform','optimizer_solve',{'synthetic':False,'mechanism':True},'a'*64,{})
    e['status']='FAILED'
    with pytest.raises(ValueError):b.reserve('one','deterministic_transform','optimizer_solve',{'synthetic':False,'mechanism':True},'a'*64,{})
    with pytest.raises(ValueError):b.reserve('two','deterministic_transform','optimizer_solve',{'synthetic':False,'mechanism':True},'a'*64,{})
    assert b.learned_total==0 and b.snapshot()['counts']['deterministic_transform']==1 and len(durable)==1


def test_wrong_run_rejected_before_file_access():
    with pytest.raises(ValueError,match='ONLY_AUTHORIZED'):c.paths(c.RUN.parent/'another')