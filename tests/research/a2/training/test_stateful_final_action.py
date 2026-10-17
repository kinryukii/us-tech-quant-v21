"""Independent synthetic account-consumer checks; no real packet or model reads."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import ast
import json
import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.training import stateful_final_action as owner
from scripts.research.a2.training import stateful_final_action_packets as packets
from scripts.research.a2.training import stateful_research_account as research
from scripts.research.a2.training import stateful_replay as replay
from scripts.research.a2.training.stateful_account import StatefulOverlay
from scripts.v22.corporate_action_transition_r1 import SourceBackedTerminalEvent
from scripts.maintenance import research_registry as registry

DAY = pd.Timestamp('2024-01-03')
NAMES = tuple(['S%02d' % i for i in range(20)] + ['OUTSIDE'])


def candidate(name='SYNTHETIC_ACTION'):
    return dict(candidate_id=name, scientific_tuple_sha256='a'*64, action='raw',
        value_model='ridge', control='none', gross='fixed', risk='diag20_reference',
        forecast='none', action_cost_mode='blind', source_method_ids=['SYNTHETIC'],
        execution_friction=dict(kind='FIXED_ADVERSE_OPEN_SLIPPAGE', scenario_id='SYNTHETIC_10BPS',
            one_way_bps=10, fee_bps=0, benchmark='NEXT_RAW_OPEN', authority='HYPOTHETICAL_RESEARCH_SCENARIO'))


def state(date=DAY, *, units=None, path='SYNTHETIC_ACTION', buy=None, decision=None):
    units=np.zeros((1,len(NAMES))) if units is None else np.asarray(units,float).reshape(1,-1)
    weights=units*10/3000
    mask=np.ones_like(units,bool) if decision is None else np.asarray(decision,bool).reshape(1,-1)
    allowed=np.ones_like(units,bool) if buy is None else np.asarray(buy,bool).reshape(1,-1)
    return SimpleNamespace(signal_date=pd.Timestamp(date),signal_asof=pd.Timestamp(date),tickers=np.array(NAMES),
        path_ids=(path,),current_units=units,current_weights=weights,cash=np.array([3000*(1-weights.sum())]),
        nav=np.array([3000.]),available_budget=np.array([1.]),decision_mask=mask,buy_allowed=allowed,
        max_positions=20,max_invested=1.,max_weight=1.,holding_age=np.full_like(units,7,int),
        entry_date=np.full(units.shape,np.datetime64('2024-01-02')),entry_price=np.full_like(units,10.),
        entry_execution_open=np.full_like(units,10.))


def make_overlay(records=(), *, date=DAY, qualified=None, sid=True):
    top=np.ones((1,len(NAMES)),bool);top[0,-1]=False
    qualified=np.ones_like(top,bool) if qualified is None else np.asarray(qualified,bool).reshape(top.shape)
    value={'ridge':dict(mu=np.full(top.shape,.03),sigma=np.array([.001]),lineage=np.array(['SYNTHETIC']))}
    sidmap={(pd.Timestamp(date),name):'SID_'+name for name in NAMES} if sid else None
    c=candidate()
    overlay=owner.FinalActionOverlay([c],value,top,qualified,np.full(top.shape,.02),
        action_packets={c['candidate_id']:{pd.Timestamp(date):list(records)}},
        resource_decoder=packets.decode_resource_proposals,sid_by_key=sidmap)
    return overlay,top,qualified,value


def proposal(kind,ticker='S00',*,decision=None,order=0,score=1.,entrant=None):
    return dict(kind=kind,decision=decision or kind,ticker=ticker,entrant=entrant,
        security_id='SID_'+ticker,entrant_security_id=None if entrant is None else 'SID_'+entrant,
        source_order=order,source_score=score,sample_id='SYNTHETIC_'+str(order),local_resolver='R6')


def raw_decision(overlay,ctx):
    return overlay.raw(0,ctx)


def write(path,obj):
    path.write_text(json.dumps(obj),encoding='utf-8')
    return dict(path=str(path),sha256=replay.sha(path))


def test_empty_publication_is_exact_raw_reference():
    overlay,*_=make_overlay()
    ctx=state()
    expected=raw_decision(overlay,ctx)
    actual=overlay(0,ctx)
    np.testing.assert_array_equal(actual.weights,expected.weights)
    np.testing.assert_array_equal(actual.explicit_mask,expected.explicit_mask)


def test_2023_is_raw_reference_even_if_packets_present():
    overlay,*_=make_overlay([proposal('REFERENCE',decision='SKIP')],date='2023-12-29')
    ctx=state('2023-12-29')
    expected=raw_decision(overlay,ctx)
    actual=overlay(0,ctx)
    np.testing.assert_array_equal(actual.weights,expected.weights)
    np.testing.assert_array_equal(actual.explicit_mask,expected.explicit_mask)
    assert not overlay.action_audit


def test_skip_retains_cash_slot_without_reranking():
    overlay,*_=make_overlay([proposal('REFERENCE',decision='SKIP')])
    ctx=state();expected=raw_decision(overlay,ctx);actual=overlay(0,ctx)
    assert actual.weights[0,0]==0 and not actual.explicit_mask[0,0]
    np.testing.assert_array_equal(actual.weights[0,1:],expected.weights[0,1:])
    assert actual.weights.sum()==pytest.approx(.95)
    assert overlay.action_audit[0]['consumer_status']=='APPLIED'


def test_true_hold_keeps_units_and_reserves_signal_budget_without_mutation():
    units=np.zeros(len(NAMES));units[0]=60
    ctx=state(units=units);original_mask=ctx.decision_mask.copy()
    overlay,*_=make_overlay([proposal('HOLD')]);actual=overlay(0,ctx)
    assert actual.weights[0,0]==0 and not actual.explicit_mask[0,0]
    assert actual.weights[0,1]==pytest.approx(.8/20)
    assert actual.weights.sum()+ctx.current_weights[0,0] <=1
    np.testing.assert_array_equal(ctx.decision_mask,original_mask)
    np.testing.assert_array_equal(ctx.current_units[0],units)
    assert overlay.action_audit[0]['consumer_status']=='APPLIED'


def test_sell_is_explicit_full_exit():
    units=np.zeros(len(NAMES));units[0]=60
    overlay,*_=make_overlay([proposal('SELL')]);actual=overlay(0,state(units=units))
    assert actual.weights[0,0]==0 and actual.explicit_mask[0,0]
    assert overlay.action_audit[0]['consumer_status']=='APPLIED'


@pytest.mark.parametrize('reason',['outside','buy_restricted','unqualified','no_decision'])
def test_buy_cannot_expand_frozen_raw_eligibility(reason):
    ticker='OUTSIDE' if reason=='outside' else 'S00'
    qualified=np.ones(len(NAMES),bool);buy=np.ones(len(NAMES),bool);mask=np.ones(len(NAMES),bool)
    if reason=='buy_restricted':buy[0]=False
    if reason=='unqualified':qualified[0]=False;buy[0]=False
    if reason=='no_decision':mask[0]=False
    overlay,*_=make_overlay([proposal('BUY',ticker)],qualified=qualified)
    ctx=state(buy=buy,decision=mask);expected=raw_decision(overlay,ctx);actual=overlay(0,ctx)
    np.testing.assert_array_equal(actual.weights,expected.weights)
    np.testing.assert_array_equal(actual.explicit_mask,expected.explicit_mask)
    assert not any(r['consumer_status']=='APPLIED' for r in overlay.action_audit)


def test_replace_exits_incumbent_and_keeps_exact_raw_entrant_slot():
    units=np.zeros(len(NAMES));units[-1]=60
    overlay,*_=make_overlay([proposal('REPLACE','OUTSIDE',entrant='S00')])
    ctx=state(units=units);expected=raw_decision(overlay,ctx);actual=overlay(0,ctx)
    assert actual.weights[0,-1]==0 and actual.explicit_mask[0,-1]
    assert actual.weights[0,0]==expected.weights[0,0]
    assert actual.explicit_mask[0,0]==expected.explicit_mask[0,0]
    assert overlay.action_audit[0]['consumer_status']=='APPLIED'


def test_replace_conflict_preserves_reference_without_alternate_partner():
    units=np.zeros(len(NAMES));units[0]=15;units[1]=15
    rows=[proposal('REPLACE','S00',entrant='S02',order=0),proposal('REPLACE','S01',entrant='S02',order=1)]
    overlay,*_=make_overlay(rows);actual=overlay(0,state(units=units))
    assert [r['ticker'] for r in overlay.action_audit if r['consumer_status']=='APPLIED']==['S00']
    conflict=[r for r in overlay.action_audit if r['consumer_status']=='RESOURCE_CONFLICT_REFERENCE']
    assert len(conflict)==1 and conflict[0]['reference_preserved'] is True
    assert conflict[0]['reason']=='RESOURCE_ALREADY_USED_REFERENCE_NO_ALTERNATE_PARTNER'
    assert actual.weights[0,1]>0


@pytest.mark.parametrize('field,value',[('security_id','WRONG_SID'),('security_id',None)])
def test_wrong_or_missing_incumbent_source_sid_cannot_change_reference(field,value):
    r=proposal('REFERENCE',decision='SKIP');r[field]=value
    overlay,*_=make_overlay([r]);ctx=state();expected=raw_decision(overlay,ctx);actual=overlay(0,ctx)
    np.testing.assert_array_equal(actual.weights,expected.weights)
    assert not overlay.action_audit


@pytest.mark.parametrize('value',['WRONG_ENTRANT_SID',None])
def test_replace_requires_exact_nonmissing_entrant_sid(value):
    units=np.zeros(len(NAMES));units[-1]=60
    r=proposal('REPLACE','OUTSIDE',entrant='S00');r['entrant_security_id']=value
    overlay,*_=make_overlay([r]);ctx=state(units=units);expected=raw_decision(overlay,ctx);actual=overlay(0,ctx)
    np.testing.assert_array_equal(actual.weights,expected.weights)
    np.testing.assert_array_equal(actual.explicit_mask,expected.explicit_mask)
    assert not overlay.action_audit


@pytest.mark.parametrize('date',['2026-01-01','2027-01-01'])
def test_post2025_context_rejected_before_decoder_or_policy(date):
    overlay,*_=make_overlay()
    overlay.resource_decoder=lambda *a,**k:pytest.fail('decoder read after time boundary')
    with pytest.raises(ValueError,match='2026_LOCKED'):overlay(0,state(date))


def test_path_identity_is_not_rebound_to_candidate_alias():
    overlay,*_=make_overlay()
    with pytest.raises(ValueError,match='POLICY_PATH_ORDER'):overlay(0,state(path='OTHER_PATH'))


def test_native_tail_width_changes_action_with_same_point_output():
    row=dict(ticker='S00',sample_id='SYNTHETIC_NATIVE',security_id='SID_S00',proxy_entrant=True,
        q10=.01,q50=.03,q90=.06,width=.05)
    good=packets.decode_r6_row(row,'distribution');bad=packets.decode_r6_row({**row,'q10':-.10,'width':.4},'distribution')
    for r in (good,bad):r['security_id']='SID_S00'
    assert good['source_score']==bad['source_score']==.03
    a,*_=make_overlay([good]);b,*_=make_overlay([bad])
    left=a(0,state());right=b(0,state())
    assert left.weights[0,0]>0 and right.weights[0,0]==0
    np.testing.assert_array_equal(left.weights[0,1:],right.weights[0,1:])


@pytest.mark.parametrize('objective',['buy','hold','replace'])
def test_frozen_probability_tie_is_reference_not_new_action(objective):
    row=dict(ticker='S00',incumbent='OUTSIDE',sample_id='SYNTHETIC_TIE',p_superior=.5)
    r=packets.decode_r6_row(row,objective)
    assert r['kind']=='REFERENCE' and r['decision']=='REFERENCE'
    r['security_id']='SID_S00'
    overlay,*_=make_overlay([r]);ctx=state();expected=raw_decision(overlay,ctx);actual=overlay(0,ctx)
    np.testing.assert_array_equal(actual.weights,expected.weights)
    np.testing.assert_array_equal(actual.explicit_mask,expected.explicit_mask)


@pytest.fixture
def frozen_contract(tmp_path,monkeypatch):
    run=tmp_path/'synthetic_run';run.mkdir()
    monkeypatch.setattr(owner,'assert_write_path',lambda *a:None)
    monkeypatch.setattr(registry,'verify_a_final_action_admission',lambda *a,**k:dict(status='PASS',admission='OPEN_METADATA_ONLY',new_fit_budget=0))
    audit=write(tmp_path/'audit.json',dict(research_integrity={'RAW_s10':dict(all_passed=True,groups=dict.fromkeys(research.GATES,True))}))
    parent=write(tmp_path/'parent.json',dict(research_account=dict(namespace=research.SESSION_NAMESPACE)))
    source=tmp_path/'synthetic_source.py';source.write_text('# synthetic source only\n',encoding='utf-8')
    manifest=dict(task_id=owner.TASK,status='FROZEN_PRE_OUTCOME',phase0_frozen=True,real_fit_budget=0,
        source_pins=[dict(path=str(source),sha256=replay.sha(source))],candidates=[candidate()],
        reference=dict(candidate_id='RAW_s10',audit_ref=audit,config_ref=parent),**{'2026_locked':True})
    manifest_ref=write(tmp_path/'manifest.json',manifest)
    cfg=dict(final_action_namespace=owner.TASK,coverage_manifest_ref=manifest_ref,new_fit_units=0,
        scientific_retry=0,max_new_account_paths=1)
    write(run/'run_config.json',cfg)
    return run,cfg,manifest,tmp_path


def test_contract_validates_physical_identity_without_fitting(frozen_contract):
    run,_,manifest,_=frozen_contract
    assert owner.contract(run)[2]==manifest


@pytest.mark.parametrize('group',research.GATES)
@pytest.mark.parametrize('value',[False,None,1,'true'])
def test_baseline_ten_groups_require_literal_true(frozen_contract,group,value):
    run,cfg,manifest,tmp=frozen_contract
    groups=dict.fromkeys(research.GATES,True);groups[group]=value
    manifest['reference']['audit_ref']=write(tmp/'bad_audit.json',dict(research_integrity={'RAW_s10':dict(all_passed=True,groups=groups)}))
    cfg['coverage_manifest_ref']=write(tmp/'manifest.json',manifest);write(run/'run_config.json',cfg)
    with pytest.raises(ValueError,match='TEN_LITERAL_TRUE'):owner.contract(run)


@pytest.mark.parametrize('field,value',[('new_fit_units',1),('scientific_retry',1),('max_new_account_paths',2),('final_action_namespace','OTHER')])
def test_contract_rejects_fit_retry_budget_or_namespace_drift(frozen_contract,field,value):
    run,cfg,_,_=frozen_contract;cfg[field]=value;write(run/'run_config.json',cfg)
    with pytest.raises(ValueError):owner.contract(run)


def test_changed_valid64hex_reference_hash_is_rejected(frozen_contract):
    run,cfg,_,_=frozen_contract;cfg['coverage_manifest_ref']['sha256']='b'*64;write(run/'run_config.json',cfg)
    with pytest.raises(ValueError,match='REF_CHANGED'):owner.contract(run)


def test_source_custody_hash_is_checked_not_merely_documented(frozen_contract):
    run,_,manifest,_=frozen_contract;Path(manifest['source_pins'][0]['path']).write_text('# changed\n',encoding='utf-8')
    with pytest.raises(ValueError,match='SOURCE_CHANGED'):owner.contract(run)


@pytest.mark.parametrize('events,code',[
    ([dict(event='ACCOUNT_PATH_ATTEMPT_STARTED',candidate_id='UNKNOWN')],'UNKNOWN_ATTEMPT'),
    ([dict(event='ACCOUNT_PATH_ATTEMPT_STARTED',candidate_id='B')],'EXACT_FROZEN_ORDER'),
    ([dict(event='ACCOUNT_PATH_ATTEMPT_STARTED',candidate_id='A')]*2,'DUPLICATE_ATTEMPT'),
    ([dict(event='ACCOUNT_PATH_COMPLETE',candidate_id='A')],'DUPLICATE_TERMINAL'),
    ([dict(event='ACCOUNT_PATH_ATTEMPT_STARTED',candidate_id='A'),dict(event='ACCOUNT_PATH_COMPLETE',candidate_id='A'),dict(event='ACCOUNT_PATH_FAILED',candidate_id='A')],'DUPLICATE_TERMINAL')])
def test_history_never_resets_trial_budget(monkeypatch,tmp_path,events,code):
    monkeypatch.setattr(replay,'_events',lambda _:events)
    with pytest.raises(ValueError,match=code):owner.history(tmp_path,[dict(candidate_id='A'),dict(candidate_id='B')])


def test_failure_is_consumed_and_outstanding_attempt_is_explicit(monkeypatch,tmp_path):
    rows=[dict(event='ACCOUNT_PATH_ATTEMPT_STARTED',candidate_id='A'),dict(event='ACCOUNT_PATH_FAILED',candidate_id='A'),dict(event='ACCOUNT_PATH_ATTEMPT_STARTED',candidate_id='B')]
    monkeypatch.setattr(replay,'_events',lambda _:rows)
    h=owner.history(tmp_path,[dict(candidate_id='A'),dict(candidate_id='B')])
    assert h['started']==['A','B'] and h['outstanding']==['B']
    assert h['terminal']['A']['event']=='ACCOUNT_PATH_FAILED'


def test_consumer_source_contains_no_estimator_fit_or_provider_entrypoint():
    tree=ast.parse(Path(owner.__file__).read_text(encoding='utf-8'))
    forbidden={'fit','partial_fit','fit_transform','download','Ticker','create_goal'}
    invoked={node.func.attr for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)}
    assert not (invoked & forbidden)
    assert 'stateful_research_account' in Path(owner.__file__).read_text(encoding='utf-8')


@pytest.mark.parametrize('score',[0.,-.1])
def test_sell_action_is_not_suppressed_by_negative_pair_hold(score):
    units=np.zeros(len(NAMES));units[0]=15
    rows=[proposal('SELL','S00',order=0,score=score),proposal('HOLD','S00',order=1,entrant='S02',score=-1.)]
    overlay,*_=make_overlay(rows);actual=overlay(0,state(units=units))
    assert actual.weights[0,0]==0 and actual.explicit_mask[0,0]
    assert any(r['kind']=='SELL' and r['consumer_status']=='APPLIED' for r in overlay.action_audit)


def synthetic_engine(dates,*,prices=None,action_packets=None,terminal=False):
    dates=pd.DatetimeIndex(pd.to_datetime(dates));names=list(NAMES)
    if terminal:names[0]='MKFG'
    shape=(len(dates),len(names));mask=np.ones(shape,bool);top=mask.copy();top[:,-1]=False
    price=np.full(shape,10.) if prices is None else np.asarray(prices,float)
    market=replay.MarketArrays(dates,names,price.copy(),price.copy(),input_present=mask.copy(),
        new_buy_eligible=mask.copy(),signal_asof=[d.tz_localize('America/New_York')+pd.Timedelta(hours=16) for d in dates])
    c=candidate();value={'ridge':dict(mu=np.full(shape,.03),sigma=np.full(len(dates),.001),lineage=np.full(len(dates),'SYNTHETIC'))}
    config=dict(base_currency='USD',initial_nav=3000.,initial_cash=3000.,initial_holdings=[],
        fractional_shares=True,integer_share_rounding=False,transaction_cost_bps=0.,cash_interest=0.,
        financing=False,borrowed_cash=False,long_only=True,max_weight=1.,max_positions=20,max_invested=1.,capacity_fraction=None)
    sid={(d,t):'SID_'+t for d in dates for t in names};holder={}
    def factory(*args,**kw):
        holder['overlay']=owner.FinalActionOverlay(*args,**kw,
            action_packets={c['candidate_id']:action_packets or {}},
            resource_decoder=packets.decode_resource_proposals,sid_by_key=sid)
        return holder['overlay']
    extra={}
    if terminal:
        event=SourceBackedTerminalEvent(event_id='SYNTHETIC_MKFG',old_security_id='SID_MKFG',ticker='MKFG',
            effective_at='2024-12-31T09:30:00-05:00',available_at='2024-12-27T16:00:00-05:00',
            cash_per_old_share=5.,currency='USD',amount_unit='USD_PER_RAW_OLD_SHARE',
            quantity_coordinate='RAW_OLD_SECURITY_SHARES',quantity_source_reference='synthetic://raw-coordinate',
            quantity_source_fingerprint='b'*64,source_type='TIER1_ISSUER_REGULATOR_EXCHANGE',
            source_reference='synthetic://terminal',source_fingerprint='c'*64)
        extra=dict(entitlement_enabled=True,entitlement_events=(event,),
            entitlement_security_tickers={'SID_'+t:t for t in names},
            entitlement_source_binding=dict(status='SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND',
                source_fingerprint='d'*64,quantity_coordinate='RAW_OLD_SECURITY_SHARES',
                event_fingerprints=[event.event_fingerprint],security_tickers={'SID_'+t:t for t in names}))
    result,frames=replay.execute_market(market,[c],value,top,mask.copy(),np.full(shape,.02),config,
        stock_present=mask.copy(),raw_selector_present=mask.copy(),execution_friction=c['execution_friction'],
        policy_factory=factory,**extra)
    return result,frames,holder['overlay']


def test_real_shared_engine_executes_next_open_and_true_hold_survives_crossyear():
    dates=pd.to_datetime(['2023-12-29','2024-01-02','2024-01-03','2024-12-31','2025-01-02'])
    action={d:[proposal('HOLD','S00')] for d in dates if d.year>2023}
    result,frames,overlay=synthetic_engine(dates,action_packets=action)
    fills=frames['fills'];stock=fills.loc[fills.ticker.eq('S00')]
    assert len(stock)==1 and stock.iloc[0].side=='BUY'
    assert stock.iloc[0].signal_date==dates[0] and stock.iloc[0].execution_date==dates[1]
    assert stock.iloc[0].index_units != int(stock.iloc[0].index_units)
    assert result.metadata['annual_reset'] is False
    assert result.final_state['fractional_shares'][0,0]==pytest.approx(stock.iloc[0].index_units)
    assert any(r['kind']=='HOLD' and r['consumer_status']=='APPLIED' for r in overlay.action_audit)


def test_future_market_payload_does_not_change_prechange_account_prefix():
    dates=pd.to_datetime(['2023-12-29','2024-01-02','2024-01-03','2024-12-31','2025-01-02'])
    action={d:[proposal('HOLD','S00')] for d in dates if d.year>2023}
    first=np.full((len(dates),len(NAMES)),10.);second=first.copy();second[3:,:]=90.
    a,af,_=synthetic_engine(dates,prices=first,action_packets=action)
    b,bf,_=synthetic_engine(dates,prices=second,action_packets=action)
    for name,clock in [('daily','date'),('positions','date'),('fills','execution_date')]:
        left=af[name].loc[af[name][clock]<=dates[2]].reset_index(drop=True)
        right=bf[name].loc[bf[name][clock]<=dates[2]].reset_index(drop=True)
        pd.testing.assert_frame_equal(left,right)


def test_unknown_mkfg_settlement_keeps_receivable_nonspendable_no_terminal_rebuy():
    dates=pd.to_datetime(['2024-12-27','2024-12-30','2024-12-31','2025-01-02'])
    malicious=proposal('BUY','MKFG');malicious['security_id']='SID_MKFG'
    result,frames,overlay=synthetic_engine(dates,terminal=True,action_packets={dates[2]:[malicious],dates[3]:[malicious]})
    event=frames['entitlements'];rights=event.loc[event.phase.eq('MERGER_RECEIVABLE_RECOGNIZED')]
    assert len(rights)==1 and rights.iloc[0].amount_usd>0
    assert not event.phase.eq('CASH_PAID').any()
    assert result.final_state['fractional_shares'][0,0]==0
    fills=frames['fills'];terminal=fills.loc[fills.ticker.eq('MKFG')]
    assert len(terminal)==1 and terminal.iloc[0].side=='BUY'
    assert terminal.iloc[0].execution_date<dates[2]
    daily=research.add_dual_nav(result)
    last=daily.iloc[-1]
    assert last.TOTAL_ECONOMIC_NAV-last.LIQUID_NAV==pytest.approx(rights.iloc[0].amount_usd)
    assert last.receivable_value_usd==pytest.approx(rights.iloc[0].amount_usd)
    assert result.metadata['terminal_settlement_qualified_by_path'][candidate()['candidate_id']] is False
    assert not any(r['ticker']=='MKFG' and r['consumer_status']=='APPLIED' for r in overlay.action_audit)


def test_all_failed_paths_are_typed_not_testable_not_economic_no_winner(tmp_path,monkeypatch):
    c=candidate('R6_DISTRIBUTION_LINEAR');run=tmp_path/'fake';run.mkdir()
    manifest=dict(candidates=[c],results_directory=str(tmp_path),reference=dict(run_dir=str(tmp_path)),
        prior_account_audit_refs=[],census_ref=dict(path='synthetic_census',sha256='c'*64),
        statistical_design=dict(Bonferroni_family=221,rule_reference_ids=[],contrasts=[dict(candidate=c['candidate_id'],reference='RAW_s10')]))
    history=dict(outstanding=[],terminal={c['candidate_id']:dict(event='ACCOUNT_PATH_FAILED',audit_path='synthetic_fail',audit_sha256='f'*64)})
    monkeypatch.setattr(owner,'contract',lambda _: (run,{},manifest,{}))
    monkeypatch.setattr(owner,'history',lambda *_:history)
    monkeypatch.setattr(owner,'read_ref',lambda r:dict(representatives=[]) if r['path']=='synthetic_census' else dict(status='FAILED_ENGINEERING_OR_QUALIFICATION'))
    captured={};monkeypatch.setattr(owner,'write_report',lambda p,o:captured.update({Path(p).name:o}))
    summary=owner.build_report(run)
    assert summary['economically_evaluated']==0 and summary['not_testable']==1
    assert summary['native_uncertainty_action_covered'] is False
    assert summary['status'] not in ('ACTION_COVERAGE_COMPLETE_NO_SUPPORTED_WINNER','ACTION_COVERAGE_COMPLETE_SUPPORTED')
    assert '原生分位数/分布动作已纳入完整账户消费。' not in (tmp_path/'REPORT.md').read_text(encoding='utf-8')


def test_equal_unknown_sid_strings_do_not_create_identity_authority():
    r=proposal('REFERENCE',decision='SKIP');r['security_id']='UNKNOWN'
    overlay,*_=make_overlay([r]);overlay.sid_by_key[(DAY,'S00')]='UNKNOWN'
    ctx=state();expected=raw_decision(overlay,ctx);actual=overlay(0,ctx)
    np.testing.assert_array_equal(actual.weights,expected.weights)
    np.testing.assert_array_equal(actual.explicit_mask,expected.explicit_mask)
    assert not overlay.action_audit


def test_registry_denial_happens_before_any_numeric_reader_or_account(frozen_contract,monkeypatch):
    run,_,_,_=frozen_contract
    def denied(*args,**kwargs):
        raise registry.RegistryError('SYNTHETIC_CANONICAL_ADMISSION_DENIED')
    monkeypatch.setattr(registry,'verify_a_final_action_admission',denied)
    monkeypatch.setattr(replay,'_read_parent_inputs_readonly',lambda *a,**k:pytest.fail('numeric reader before registry gate'))
    monkeypatch.setattr(packets,'load_packets',lambda *a,**k:pytest.fail('packet reader before registry gate'))
    monkeypatch.setattr(replay,'execute_market',lambda *a,**k:pytest.fail('account before registry gate'))
    with pytest.raises(registry.RegistryError,match='SYNTHETIC_CANONICAL_ADMISSION_DENIED'):
        owner.run_owned(run)


def test_controller_cli_completion_return_contains_status_stage_and_report():
    tree=ast.parse(Path(owner.__file__).read_text(encoding='utf-8'))
    f=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_owned')
    returns=[n.value for n in ast.walk(f) if isinstance(n,ast.Return) and isinstance(n.value,ast.Call)
             and isinstance(n.value.func,ast.Name) and n.value.func.id=='dict']
    assert len(returns)==1
    fields={k.arg:k.value for k in returns[0].keywords}
    assert {'status','stage','report','real_fit','test_2026_rows_read'} <=set(fields)
    assert ast.literal_eval(fields['status'])=='COMPLETED'
    assert ast.literal_eval(fields['stage'])=='FINAL_ACTION_REPORT'
    assert isinstance(fields['report'],ast.Name) and fields['report'].id=='report'
    assert ast.literal_eval(fields['real_fit'])==ast.literal_eval(fields['test_2026_rows_read'])==0



def test_verified_engineering_source_return_is_used_without_editing_frozen_manifest(frozen_contract,monkeypatch,tmp_path):
    run,cfg,manifest,_=frozen_contract
    before_manifest=Path(cfg['coverage_manifest_ref']['path']).read_bytes()
    # This is the explicit pytest-only file created by frozen_contract above.
    synthetic=(tmp_path/'synthetic_source.py').resolve()
    assert synthetic.is_relative_to(tmp_path.resolve())
    assert synthetic==Path(manifest['source_pins'][0]['path']).resolve()
    assert synthetic.name=='synthetic_source.py'
    synthetic.write_text('# verified synthetic engineering descendant\n',encoding='utf-8')
    pins=[dict(path=str(synthetic),sha256=replay.sha(synthetic))]
    quote=dict(path='synthetic://verified-quote-envelope',sha256='d'*64)
    monkeypatch.setattr(registry,'verify_a_final_action_admission',lambda *a,**k:dict(status='PASS',
        effective_source_pins=pins,engineering_run_dir=str(run),quote_domain_ref=quote))
    _,returned,_,_=owner.contract(run)
    assert returned['_engineering_quote_domain_ref']==quote
    assert Path(cfg['coverage_manifest_ref']['path']).read_bytes()==before_manifest
    assert manifest['source_pins'][0]['sha256']!=pins[0]['sha256']
    assert json.loads((run/'run_config.json').read_text(encoding='utf-8'))==cfg


def test_verified_engineering_return_wrong_source_hash_fails_closed(frozen_contract,monkeypatch):
    run,_,manifest,_=frozen_contract
    bad=[dict(manifest['source_pins'][0],sha256='f'*64)]
    monkeypatch.setattr(registry,'verify_a_final_action_admission',lambda *a,**k:dict(status='PASS',
        effective_source_pins=bad,engineering_run_dir=str(run)))
    with pytest.raises(ValueError,match='FINAL_ACTION_SOURCE_CHANGED'):owner.contract(run)


def test_verified_engineering_return_is_bound_to_the_exact_run(frozen_contract,monkeypatch):
    run,_,_,tmp=frozen_contract
    monkeypatch.setattr(registry,'verify_a_final_action_admission',lambda *a,**k:dict(status='PASS',
        engineering_run_dir=str(tmp/'OTHER_RUN'),quote_domain_ref=dict(path='synthetic://other',sha256='a'*64)))
    with pytest.raises(ValueError,match='FINAL_ACTION_ENGINEERING_EXACT_RUN'):owner.contract(run)


@pytest.mark.parametrize('verified_quote',[False,True])
def test_caller_quote_override_is_discarded_not_used_as_authority(frozen_contract,monkeypatch,verified_quote):
    run,cfg,_,_=frozen_contract
    caller=dict(path='synthetic://unverified-caller',sha256='c'*64)
    trusted=dict(path='synthetic://registry-verified',sha256='d'*64)
    cfg['_engineering_quote_domain_ref']=caller;write(run/'run_config.json',cfg)
    admission=dict(status='PASS',engineering_run_dir=str(run))
    if verified_quote:admission['quote_domain_ref']=trusted
    monkeypatch.setattr(registry,'verify_a_final_action_admission',lambda *a,**k:admission)
    _,returned,_,_=owner.contract(run)
    assert returned.get('_engineering_quote_domain_ref')==(trusted if verified_quote else None)
    assert json.loads((run/'run_config.json').read_text(encoding='utf-8'))['_engineering_quote_domain_ref']==caller


def test_verified_quote_is_forwarded_on_auth_copy_before_any_account_attempt(frozen_contract,monkeypatch):
    from contextlib import nullcontext
    from scripts.research.a2.training import stateful_execution as execution
    run,_,_,_=frozen_contract
    trusted=dict(path='synthetic://registry-verified',sha256='d'*64)
    trusted_session=dict(path='synthetic://registry-verified-session',sha256='e'*64)
    monkeypatch.setattr(registry,'verify_a_final_action_admission',lambda *a,**k:dict(status='PASS',
        engineering_run_dir=str(run),quote_domain_ref=trusted,session_convention_ref=trusted_session))
    actual_run,cfg,manifest,parent=owner.contract(run)
    original=dict(path='synthetic://frozen-original',sha256='b'*64)
    original_session=dict(path='synthetic://frozen-original-session',sha256='a'*64)
    parent['parent_run_dir']='synthetic_parent'
    parent['research_account']['quote_domain_ref']=original
    parent['research_account']['research_ca_accounting_convention']=original_session
    parent['research_account']['MKFG_settlement_authority']='UNKNOWN'
    monkeypatch.setattr(owner,'contract',lambda _: (actual_run,cfg,manifest,parent))
    monkeypatch.setattr(owner,'history',lambda *a:dict(started=[],outstanding=[]))
    monkeypatch.setattr(execution,'continuation_lock',lambda *a,**k:nullcontext())
    monkeypatch.setattr(execution,'configure_environment',lambda *a,**k:None)
    monkeypatch.setattr(owner,'write_json_atomic',lambda *a,**k:None)
    monkeypatch.setattr(replay,'_read_parent_inputs_readonly',lambda *a:SimpleNamespace())
    monkeypatch.setattr(replay,'read_market',lambda *a:(None,None,None,None,None,None))
    monkeypatch.setattr(replay,'_json',lambda *a:{})
    monkeypatch.setattr(replay,'_old',lambda:SimpleNamespace(frozen_events=lambda *a:([],{},[],None)))
    monkeypatch.setattr(research,'_decision_digest',lambda *a:'SYNTHETIC_UNCHANGED')
    monkeypatch.setattr(replay,'_append',lambda *a,**k:pytest.fail('account attempt reserved during source repair'))
    monkeypatch.setattr(replay,'execute_market',lambda *a,**k:pytest.fail('account executed during source repair'))
    monkeypatch.setattr(packets,'load_packets',lambda *a,**k:pytest.fail('action packets read during source repair'))
    captured={}
    class StopAtSourceBoundary(Exception):pass
    def boundary(auth,*a,**k):
        captured.update(auth)
        raise StopAtSourceBoundary()
    monkeypatch.setattr(research,'bound_inputs',boundary)
    with pytest.raises(StopAtSourceBoundary):owner.run_owned(run)
    assert captured['quote_domain_ref']==trusted
    assert captured['research_ca_accounting_convention']==trusted_session
    assert captured['MKFG_settlement_authority']=='UNKNOWN'
    assert parent['research_account']['quote_domain_ref']==original
    assert parent['research_account']['research_ca_accounting_convention']==original_session
    assert not (run/'ACCOUNT_PATH_LOG.jsonl').exists()


@pytest.mark.parametrize('verified_session',[False,True])
def test_caller_session_override_is_discarded_not_used_as_authority(frozen_contract,monkeypatch,verified_session):
    run,cfg,_,_=frozen_contract
    caller=dict(path='synthetic://unverified-caller-session',sha256='c'*64)
    trusted=dict(path='synthetic://registry-verified-session',sha256='e'*64)
    cfg['_engineering_session_convention_ref']=caller;write(run/'run_config.json',cfg)
    admission=dict(status='PASS',engineering_run_dir=str(run))
    if verified_session:admission['session_convention_ref']=trusted
    monkeypatch.setattr(registry,'verify_a_final_action_admission',lambda *a,**k:admission)
    _,returned,_,_=owner.contract(run)
    assert returned.get('_engineering_session_convention_ref')==(trusted if verified_session else None)
    assert json.loads((run/'run_config.json').read_text(encoding='utf-8'))['_engineering_session_convention_ref']==caller
