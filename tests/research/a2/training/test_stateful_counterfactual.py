"""Synthetic manifest/budget tests, no market, label or model artifact readers."""
from copy import deepcopy
import pandas as pd
import pytest
from scripts.research.a2.training import stateful_counterfactual as c


def stocks():
    return [dict(sid='SID_A', ticker='A', is_held=True, decision_eligible=True, buy_eligible=True,
                 sell_eligible=True, raw_buy_pool=True, terminal_closed=False, raw_rank=1,
                 raw_fractional_shares=100.),
            dict(sid='SID_B', ticker='B', is_held=False, decision_eligible=True, buy_eligible=True,
                 sell_eligible=True, raw_buy_pool=True, terminal_closed=False, raw_rank=2,
                 raw_fractional_shares=0.)]


def binding():
    friction={'one_way_bps':10,'fee_bps':0,'benchmark':'NEXT_RAW_OPEN'}
    identity={'reference_run_id':'SYNTHETIC_RAW_REFERENCE','source_account_id':'SYNTHETIC_SOURCE_ACCOUNT','reference_policy_sha256':'a'*64,'q_contract_sha256':'b'*64,'friction_contract_sha256':c.digest(friction),'security_binding_sha256':'d'*64}
    return dict(source_account_identity=identity, reference_gross_intent=.5, reference_run_source_account_id='SYNTHETIC_SOURCE_ACCOUNT', continuation_policy_sha='a'*64,
                fixed_q_contract_sha256='b'*64, source_event_quote_bindings={'synthetic': True},
                friction={'one_way_bps':10,'fee_bps':0,'benchmark':'NEXT_RAW_OPEN'})


def snapshot():
    value = dict(signal_index=0, signal_date='2024-01-02', signal_asof='2024-01-02T16:00:00-05:00',
                path_id='RAW_s10', reference_path_id='RAW_s10', source_account_identity=binding()['source_account_identity'],
                quantity_coordinate='RAW_OLD_SECURITY_SHARES', prefix_identity={'sha256':'c'*64,'precision':'EXACT_FLOAT64_HEX_NO_ROUND'},
                stocks=stocks(), account={'gross':.5})
    return rebind(value)



def rebind(s):
    from scripts.research.a2.training.stateful_account_decision import exact_prefix_identity
    coords=s.get('prefix_payload',{}).get('securities') or [{'sid':r['sid'],'ticker':r['ticker'],'raw_fractional_shares':r['raw_fractional_shares']} for r in s['stocks']]
    s['prefix_payload']={k:deepcopy(s[k]) for k in ('signal_index','signal_date','signal_asof','reference_path_id','source_account_identity','quantity_coordinate','account')}
    s['prefix_payload'].update(securities=coords,decision_state_stocks=deepcopy(s['stocks']),corporate_action_state={},actual_fill_prefix=[],prior_completed_daily_prefix=[])
    s['prefix_identity']=exact_prefix_identity(s)
    return s


def planner(s,a):
    w=[.5,0.]
    if a['action']=='BUY': w=[.5,.1]
    elif a['action']=='SELL': w=[0.,0.]
    elif a['action']=='REPLACE': w=[0.,.5]
    elif a['action'] in ('GROSS','REFERENCE_GROSS'):w=[a['gross'],0.]
    return {'weights':w,'explicit_mask':[True,True], 'planner_intent':{'prefix_sha256':s['prefix_identity']['sha256'],
            'q_contract_sha256':'b'*64,'friction_contract_sha256':c.digest(binding()['friction']),'available_at':s['signal_asof']}}


def manifest(**kwargs):
    return c.build_branch_manifest([snapshot()], planner, pd.bdate_range('2024-01-02',periods=10),binding(),**kwargs)


def test_all_incumbent_pairs_formed_without_labels():
    rows=stocks(); rows.append({**rows[0],'sid':'SID_C','ticker':'C','raw_rank':3})
    acts=c.mechanical_actions(rows,.5)
    assert [(a['incumbent_sid'],a['entrant_sid']) for a in acts if a['action']=='REPLACE']==[('SID_A','SID_B'),('SID_C','SID_B')]
    assert len(acts)==14


def test_exact_intent_dedup_preserves_semantic_aliases():
    m=manifest()
    assert m['mechanical_action_aliases']==11 and m['required_distinct_branches']==7
    assert all(x['terminal_nav_qualification']=='UNASSESSED_REQUIRED' for x in m['branches'])
    assert m['outcome_read'] is False and m['real_branches_executed']==0
    assert m['branches'][0]['execution_session']=='2024-01-03'
    assert m['branches'][0]['horizon_end']=='2024-01-09'


def test_missing_labels_never_change_action_partner_selection():
    s=snapshot(); before=manifest()['manifest_sha256']
    m=c.build_branch_manifest([s],planner,pd.bdate_range('2024-01-02',periods=10),binding())
    assert m['manifest_sha256']==before
    s['stocks'][1]['y']=None
    with pytest.raises(ValueError,match='OUTCOME'):c.build_branch_manifest([s],planner,pd.bdate_range('2024-01-02',periods=10),binding())


def test_complete_overbudget_set_is_retained_and_execution_blocked():
    m=manifest(max_branches=6)
    assert m['status']=='BLOCKED_BUDGET' and len(m['branches'])==7
    with pytest.raises(ValueError,match='BUDGET'):c.reserve_branch_attempt(m,[],m['branches'][0]['branch_sha256'])


def test_failed_attempt_counts_no_retry_no_refund():
    m=manifest(); journal=[]; key=m['branches'][0]['branch_sha256']
    c.reserve_branch_attempt(m,journal,key);journal[0]['status']='FAILED'
    with pytest.raises(ValueError,match='RETRY'):c.reserve_branch_attempt(m,journal,key)
    assert len(journal)==1
    with pytest.raises(ValueError,match='WALL'):c.reserve_branch_attempt(m,journal,m['branches'][1]['branch_sha256'],elapsed_seconds=7200)


@pytest.mark.parametrize('bad',[False,None,1,'true'])
@pytest.mark.parametrize('group',c.GATES)
def test_literal_gate_rejects_each_bad_value(group,bad):
    slots={k:{'approved':True,'source_qualified':True,'ref':{'path':'synthetic','sha256':'d'*64}} for k in c.SOURCE_SLOTS}
    gates={k:True for k in c.GATES};gates[group]=bad
    assert c.readiness_gate(slots,gates)['status']=='NOT_TESTABLE_SOURCE_ACCOUNT_AUTHORITY'


def test_metadata_pass_is_not_real_execution_admission():
    slots={k:{'approved':True,'source_qualified':True,'ref':{'path':'synthetic','sha256':'d'*64}} for k in c.SOURCE_SLOTS}
    result=c.readiness_gate(slots,{k:True for k in c.GATES})
    assert result['status']=='READY_FOR_FROZEN_R5_OWNER_VALIDATION' and result['real_execution_admitted'] is False
    with pytest.raises(ValueError,match='UNBOUND'):c.require_real_reference(None,None)


def test_missing_gate_and_source_hash_alone_fail_closed():
    slots={k:{'approved':True,'source_qualified':True,'ref':{'path':'synthetic','sha256':'d'*64}} for k in c.SOURCE_SLOTS}
    gates={k:True for k in c.GATES};gates.pop('cash')
    assert c.readiness_gate(slots,gates)['groups']['cash'] is False
    slots['market_quote_authority']={'ref':{'path':'proposal','sha256':'d'*64}}
    assert 'market_quote_authority' in c.readiness_gate(slots,{k:True for k in c.GATES})['unbound_slots']


def test_terminal_and_restricted_security_never_reselected():
    rows=stocks();rows[1]['terminal_closed']=True
    assert not any(a.get('entrant_sid')=='SID_B' for a in c.mechanical_actions(rows,.5))
    rows=stocks();rows[0]['sell_eligible']=False
    assert not any(a['action'] in ('SELL','REPLACE') for a in c.mechanical_actions(rows,.5))


def test_future_calendar_and_prefix_approximation_rejected():
    with pytest.raises(ValueError,match='2026'):c.build_branch_manifest([snapshot()],planner,pd.bdate_range('2025-12-30',periods=10),binding())
    s=snapshot();s['prefix_identity']['precision']='ROUND10'
    with pytest.raises(ValueError,match='PREFIX.*EXACT|EXACT_PREFIX'):c.build_branch_manifest([s],planner,pd.bdate_range('2024-01-02',periods=10),binding())


def test_unknown_sid_and_boolean_support_blocked():
    rows=stocks();rows[0]['sid']='A2_TICKER_A'
    with pytest.raises(ValueError,match='SECURITY_IDENTITY'):c.mechanical_actions(rows,.5)
    rows=stocks();rows[0]['is_held']=1
    with pytest.raises(ValueError,match='UNKNOWN_SIGNAL'):c.mechanical_actions(rows,.5)


def test_action_order_does_not_depend_on_input_order():
    rows=stocks()
    assert c.mechanical_actions(rows,.5)==c.mechanical_actions(rows[::-1],.5)


def test_physical_dag174_shared_scaler_reuse_without_fitting():
    design={'training_budget':{'physical_fit_hard_cap':174},'objectives':[{'objective_id':h} for h in ('ENTRY','INCUMBENT','GROSS')],
            'folds':[{'outer_year':2024},{'outer_year':2025}],
            'models':[{'family':f,'seeds':seeds} for f,seeds in [('RIDGE',[None]),('HGB',[20260928]),('CATBOOST',[20260928,20260929,20260930]),('MLP',[20260928,20260929,20260930])]]}
    dag=c.physical_fit_dag(design)
    assert len(dag['nodes'])==174
    assert sum(n['kind']=='SCALER' for n in dag['nodes'])==6
    for node in dag['nodes']:
        if node.get('family') in ('RIDGE','MLP'):assert any('SHARED_SCALER' in dep for dep in node['dependencies'])
    assert dag['actual_estimator_fits']==dag['actual_scaler_fits']==0


def test_reference_gross_intent_not_realized_exposure():
    s=snapshot();s['account']['gross']=.4995004995004995;rebind(s)
    m=c.build_branch_manifest([s],planner,pd.bdate_range('2024-01-02',periods=10),binding())
    refs=[r['action_semantic_intent'] for r in m['aliases'] if r['action_semantic_intent']['action']=='REFERENCE_GROSS']
    assert refs==[{'objective':'SCALAR_GROSS_ADVANTAGE','action':'REFERENCE_GROSS','gross':.5}]
    b=binding();b.pop('reference_gross_intent')
    with pytest.raises(ValueError,match='GROSS_INTENT'):c.build_branch_manifest([s],planner,pd.bdate_range('2024-01-02',periods=10),b)


def test_late_planner_intent_cannot_form_past_branch():
    def late(s,a):
        result=planner(s,a);result['planner_intent']['available_at']='2024-01-03T16:00:00-05:00';return result
    with pytest.raises(ValueError,match='FUTURE_PLANNER'):c.build_branch_manifest([snapshot()],late,pd.bdate_range('2024-01-02',periods=10),binding())


def test_compile_calls_existing_single_action_consumer():
    from types import SimpleNamespace
    import numpy as np
    from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import TargetDecision
    snap=snapshot();ctx=SimpleNamespace(current_weights=np.array([[.5,0.]]),decision_mask=np.array([[True,True]]),
        path_ids=('RAW_s10',),tickers=np.array(['A','B']),max_weight=1.)
    reference=TargetDecision(np.array([[.5,0.]]),np.array([[True,False]]))
    intent=planner(snap,{'action':'BUY'})['planner_intent'];intent['target_weight']=.1
    compiled=c.compile_existing_action(reference,ctx,snap,{'action':'BUY','entrant_sid':'SID_B'},intent)
    assert compiled['weights']==[.5,.1] and compiled['explicit_mask']==[True,True]
    held=c.compile_existing_action(reference,ctx,snap,{'action':'HOLD','incumbent_sid':'SID_A'},intent)
    assert held['weights'][0]==0 and held['explicit_mask'][0] is False
    base=c.compile_existing_action(reference,ctx,snap,{'action':'REFERENCE_GROSS','gross':.5},intent)
    assert base['weights']==[.5,0.] and base['explicit_mask']==[True,False]


def test_terminal_qualification_requires_independent_source_before_nav():
    with pytest.raises(ValueError,match='SOURCE_AUTHORITY'):
        c.qualified_terminal_value({'horizon_end':'2024-01-09'},None,'RAW_s10')


def test_full_engine_vector_may_exceed_actionable_stocks():
    s=snapshot();s['prefix_payload']['securities'].append({'sid':'SID_IDLE','ticker':'IDLE','raw_fractional_shares':0.});rebind(s)
    def full(s,a):
        item=planner(s,a);item['weights'].append(0.);item['explicit_mask'].append(False);return item
    m=c.build_branch_manifest([s],full,pd.bdate_range('2024-01-02',periods=10),binding())
    assert all(len(b['target_decision']['weights'])==3 and len(b['SID_quantity_coordinate']['stocks'])==3 for b in m['branches'])


def test_terminal_not_applicable_rank_does_not_require_post_terminal_quote():
    s=snapshot();s['stocks'][1].update(terminal_closed=True,decision_eligible=False,buy_eligible=False,sell_eligible=False,raw_rank=None);rebind(s)
    m=c.build_branch_manifest([s],planner,pd.bdate_range('2024-01-02',periods=10),binding())
    assert not any(a['action_semantic_intent'].get('entrant_sid')=='SID_B' for a in m['aliases'])


@pytest.mark.parametrize('sid',['UNKNOWN','UNBOUND','nan','none','<NA>','A','a2_ticker_a'])
def test_sentinel_and_ticker_fallback_sid_fail_closed(sid):
    rows=stocks();rows[0]['sid']=sid
    with pytest.raises(ValueError,match='SECURITY_IDENTITY'):c.mechanical_actions(rows,.5)


def test_snapshot_action_support_tamper_without_prefix_update_rejected():
    s=snapshot();s['stocks'][1]['buy_eligible']=False
    with pytest.raises(ValueError,match='SUPPORT_NOT_PREFIX_BOUND'):
        c.build_branch_manifest([s],planner,pd.bdate_range('2024-01-02',periods=10),binding())
