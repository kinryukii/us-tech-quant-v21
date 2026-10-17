from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import stateful_final_action_packets as p


def row(**extra):
    return dict(ticker='I',sample_id='d_I',cohort_age_sessions=0,**extra)


@pytest.mark.parametrize('objective,prob,kind,decision',[('buy',.7,'BUY','BUY'),('buy',.3,'REFERENCE','SKIP'),('hold',.7,'HOLD','HOLD'),('hold',.3,'SELL','SELL'),('buy',.5,'REFERENCE','REFERENCE'),('hold',.5,'REFERENCE','REFERENCE'),('replace',.3,'HOLD','HOLD_SKIP_PAIR')])
def test_r6_literal_rules(objective,prob,kind,decision):
    r=p.decode_r6_row(row(p_superior=prob,incumbent='J'),objective)
    assert (r['kind'],r['decision'])==(kind,decision)


@pytest.mark.parametrize('prob',[None,np.nan,-.1,1.1,True])
def test_unknown_probability_reference(prob):
    assert p.decode_r6_row(row(p_superior=prob),'buy')['decision']=='REFERENCE'


def test_duration_original_proxy_support():
    assert p.decode_r6_row(row(p_failure=.9),'duration')['kind']=='SELL'
    r=row(p_failure=.9);r['cohort_age_sessions']=1
    assert p.decode_r6_row(r,'duration')['kind']=='REFERENCE'


def test_native_point_same_mean_extra_tail_gate():
    r=row(q10=-.2,q50=.05,q90=.1,width=.3,proxy_entrant=True)
    assert p.decode_r6_row(r,'distribution',native_mode='POINT')['kind']=='BUY'
    assert p.decode_r6_row(r,'distribution')['decision']=='SKIP'
    r=row(incumbent='J',entrant_q50=.1,incumbent_q50=0,entrant_q10=-.2,incumbent_q90=.1)
    assert p.decode_r6_distribution_pair(r,native_mode='POINT')['kind']=='REPLACE'
    assert p.decode_r6_distribution_pair(r)['decision']=='HOLD_SKIP_PAIR'


def proposal(kind,ticker,order,entrant=None,score=1,local='R6',decision=None):
    return dict(kind=kind,ticker=ticker,entrant=entrant,source_order=order,
        source_score=score,sample_id=str(order),local_resolver=local,
        decision=decision or kind,semantic='synthetic',native_used=False)


def test_r6_first_positive_not_highest_score():
    records=[proposal('REPLACE','I',1,'A',.6),proposal('REPLACE','I',2,'B',.9)]
    r=p.decode_resource_proposals(records,{'I'},{'A','B'})
    assert [x['entrant'] for x in r['accepted']]==['A']


def test_r10_highest_then_sampleid():
    records=[proposal('REPLACE','I',1,'A',.6,'R10'),proposal('REPLACE','I',2,'B',.9,'R10')]
    r=p.decode_resource_proposals(records,{'I'},{'A','B'})
    assert r['accepted'][0]['entrant']=='B'


def test_global_duplicate_entrant_no_second_partner():
    records=[proposal('REPLACE','I',1,'A'),proposal('REPLACE','J',2,'A',2),proposal('REPLACE','J',3,'B',.5)]
    r=p.decode_resource_proposals(records,{'I','J'},{'A','B'})
    assert [(x['ticker'],x['entrant']) for x in r['accepted']]==[('I','A')]
    assert len(r['conflicts'])==1 and r['no_partner_substitution']


def test_negative_pair_does_not_lock_entrant_ahead_of_positive():
    records=[proposal('HOLD','I',0,'A',-.2,decision='HOLD_SKIP_PAIR'),proposal('REPLACE','J',1,'A')]
    r=p.decode_resource_proposals(records,{'I','J'},{'A'})
    assert any(x['kind']=='REPLACE' for x in r['accepted'])
    assert not any(x['decision']=='SKIP' and x['ticker']=='A' for x in r['accepted'])


@pytest.mark.parametrize('held,allowed,reason',[(set(),{'A'},'INCUMBENT_NOT_ACTUALLY_HELD'),({'I'},set(),'ENTRANT_NOT_FROZEN_RAW_LEGAL_POOL')])
def test_runtime_legality_reference(held,allowed,reason):
    r=p.decode_resource_proposals([proposal('REPLACE','I',0,'A')],held,allowed)
    assert not r['accepted'] and r['conflicts'][0]['reason']==reason


def test_no_real_read_without_physical_manifest(monkeypatch):
    monkeypatch.setattr(pd,'read_parquet',lambda *a,**kw:pytest.fail('numeric read before freeze'))
    with pytest.raises(ValueError,match='PHASE0_PHYSICAL'):
        p.load_packets({'path':'not_read','sha256':'0'*64},['2025-01-02'],['I'])


@pytest.mark.parametrize('dates',[['2026-01-01'],['2025-01-02','2025-01-01'],['2025-01-01','2025-01-01']])
def test_dates_fail_closed(dates):
    with pytest.raises(ValueError,match='PRE2026_CALENDAR'):
        p.load_packets({},dates,['I'])


def test_forbidden_columns_fail_before_any_file_read():
    with pytest.raises(ValueError,match='COLUMN_FORBIDDEN'):
        p._read_packet({},['target'],pd.DatetimeIndex(['2025-01-02']),{'I'})


def test_synthetic_packet_projection_drops_future_label_columns(tmp_path):
    path=tmp_path/'packet.parquet'
    pd.DataFrame(dict(signal_date=pd.to_datetime(['2025-01-02']),sample_id=['k'],ticker=['I'],p_superior=[.7],target=[987654.])).to_parquet(path,index=False)
    ref={'path':str(path),'sha256':p.sha(path)}
    got=p._read_packet(ref,['signal_date','sample_id','ticker','p_superior'],pd.DatetimeIndex(['2025-01-02']),{'I'})
    assert list(got)==['signal_date','sample_id','ticker','p_superior']


def test_mixed_future_footer_rejected_before_read(tmp_path,monkeypatch):
    path=tmp_path/'mixed.parquet'
    pd.DataFrame(dict(signal_date=pd.to_datetime(['2025-01-02','2026-01-02']),sample_id=['a','b'],ticker=['I','I'])).to_parquet(path,index=False)
    monkeypatch.setattr(pd,'read_parquet',lambda *a,**kw:pytest.fail('mixed body read'))
    with pytest.raises(ValueError,match='PRE2026_PHYSICAL'):
        p._read_packet({'path':str(path),'sha256':p.sha(path)},['signal_date','sample_id','ticker'],pd.DatetimeIndex(['2025-01-02']),{'I'})


def test_incumbent_replacement_before_independent_buy():
    records=[proposal('BUY','A',0),proposal('REPLACE','I',1,'A')]
    r=p.decode_resource_proposals(records,{'I'},{'A'})
    assert [x['kind'] for x in r['accepted']]==['REPLACE']
    assert len(r['conflicts'])==1


def test_sequence_continuation_auxiliary_not_conflicting_vote():
    r=p.decode_r10_row(row(action_type=-1,mean=-.4))
    assert r['kind']=='REFERENCE'
    out=p.decode_resource_proposals([r],{'I'},set())
    assert out['accepted']==[]


def test_pair_sid_coordinates_preserved():
    r=p.decode_r6_row(row(p_superior=.9,incumbent='J',security_id='SID_I',incumbent_sid='SID_J'),'replace')
    assert r['ticker']=='J' and r['security_id']=='SID_J'
    assert r['entrant']=='I' and r['entrant_security_id']=='SID_I'


def test_all_negative_pair_rejections_retained_without_locking_positive():
    records=[proposal('HOLD','I',0,'A',-.2,decision='HOLD_SKIP_PAIR'),
             proposal('HOLD','I',1,'B',-.3,decision='HOLD_SKIP_PAIR')]
    r=p.decode_resource_proposals(records,{'I'},{'A','B'})
    assert sum(x['kind']=='HOLD' for x in r['accepted'])==1
    assert {x['ticker'] for x in r['accepted'] if x['decision']=='SKIP'}=={'A','B'}


def manifest_fixture(tmp_path,**updates):
    census=tmp_path/'census.json'
    census.write_text(json.dumps({'task_id':p.TASK,'selection_uses_economic_results':False}),encoding='utf-8')
    cref={'path':str(census),'sha256':p.sha(census)}
    authority=dict(enabled=True,phase0_frozen=True,**{'2026_locked':True},no_label_columns=True,
        allowed_start='2023-01-01',cutoff_exclusive='2026-01-01',census_ref=cref,
        reader_source_ref={'path':str(Path(p.__file__).resolve()),'sha256':p.sha(p.__file__)})
    for key,value in updates.items():
        if value=='__MISSING__':authority.pop(key,None)
        else:authority[key]=value
    manifest=tmp_path/'manifest.json'
    manifest.write_text(json.dumps({'task_id':p.TASK,'packet_read_authority':authority}),encoding='utf-8')
    return cref,{'path':str(manifest),'sha256':p.sha(manifest)}


@pytest.mark.parametrize('key',['enabled','phase0_frozen','2026_locked','no_label_columns'])
@pytest.mark.parametrize('value',[False,None,'__MISSING__',1])
def test_physical_read_authority_literal_gate(tmp_path,key,value):
    cref,auth=manifest_fixture(tmp_path,**{key:value})
    with pytest.raises(ValueError,match='LITERAL_TRUE'):
        p._authorize(cref,auth)


def test_physical_authority_exact_binding(tmp_path):
    cref,auth=manifest_fixture(tmp_path)
    assert p._authorize(cref,auth)['task_id']==p.TASK
    bad=dict(cref,sha256='0'*64)
    with pytest.raises(ValueError,match='BOUNDARY_OR_CENSUS'):
        p._authorize(bad,auth)


def test_read_authority_hash_tamper_rejected(tmp_path):
    cref,auth=manifest_fixture(tmp_path)
    Path(auth['path']).write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='PHYSICAL_SHA_MISMATCH'):
        p._authorize(cref,auth)


def test_r6_zero_probability_sell_is_not_dropped_by_score_gate():
    r=p.decode_r6_row(row(p_superior=0),'hold')
    accepted=p.decode_resource_proposals([r],{'I'},set())['accepted']
    assert len(accepted)==1 and accepted[0]['kind']=='SELL'


def test_r6_negative_quantile_sell_is_not_dropped_by_score_gate():
    r=p.decode_r6_row(row(q10=-.2,q50=-.1,q90=.1,width=.3,proxy_entrant=False),'distribution')
    accepted=p.decode_resource_proposals([r],{'I'},set())['accepted']
    assert len(accepted)==1 and accepted[0]['kind']=='SELL'



def test_complete_synthetic_frozen_output_loader_roles_sids_and_seed_mean(tmp_path,monkeypatch):
    objects=[]; reps=[]
    def publication(name,frame):
        path=tmp_path/(name+'.parquet');frame.to_parquet(path,index=False)
        return {'path':str(path),'sha256':p.sha(path),'rows':len(frame),'prediction_role':'SYNTHETIC'}
    r6buy=[];r6dist=[];r10direct=[];r10seq=[]
    for year in (2024,2025):
        date=pd.Timestamp(f'{year}-01-02')
        def f(tickers,ids,**extra):
            n=len(tickers)
            return pd.DataFrame(dict(signal_date=[date]*n,sample_id=ids,ticker=tickers,
                security_id=['SID_'+t for t in tickers],target=['FORBIDDEN']*n,
                label_qualified=[False]*n,**extra))
        for objective,ticker,prob in [('buy','A',.8),('hold','I',.2)]:
            slot=f'{objective}_linear_{year}';pub=publication(slot,f([ticker],[slot],p_superior=[prob],cohort_age_sessions=[0]))
            objects.append(dict(slot_id=slot,year=year,seed=20260928,objective=objective,oof_path=pub['path'],oof_sha256=pub['sha256']))
            if objective=='buy':r6buy.append(slot)
        slot=f'distribution_linear_{year}'
        pub=publication(slot,f(['A','I'],['entry','held'],q10=[.2,-.02],q50=[.3,.01],q90=[.4,.04],width=[.2,.06],cohort_age_sessions=[0,7]))
        pair=publication(slot+'_pair',f(['A'],['pair'],incumbent=['I'],incumbent_sid=['SID_I'],entrant_q10=[.2],incumbent_q90=[.04]))
        objects.append(dict(slot_id=slot,year=year,seed=20260928,objective='distribution',oof_path=pub['path'],oof_sha256=pub['sha256'],distribution_replace_oof_path=pair['path'],distribution_replace_oof_sha256=pair['sha256']))
        r6dist.append(slot)
        for group in ('ENTRY','INCUMBENT'):
            slot=f'R10_{group}_{year}'
            frame=f(['A'],['entry'],mean=[.2]) if group=='ENTRY' else f(['I','I'],['sell','replace'],mean=[-.02,.03],action_type=[0,1],entrant_ticker=[None,'A'])
            objects.append(dict(slot_id=slot,year=year,seed=20260928,family='ridge',capacity='LOW',group=group,horizon='MEAN',status='TRAINED',publication=publication(slot,frame)))
            r10direct.append(slot)
        for seed in (20260928,20260929,20260930):
            slot=f'R10_SEQUENCE_{year}_{seed}'
            frame=f(['I','I','I'],['continue','sell','replace'],mean=[.02,-.02,.03+(seed-20260928)*.01],action_type=[-1,0,1],entrant_ticker=[None,None,'A'])
            objects.append(dict(slot_id=slot,year=year,seed=seed,family='tcn',capacity='MID',group='JOINT_SEQUENCE',publication=publication(slot,frame)))
            r10seq.append(slot)
    for rid,objective,members in [('R6_BUY_LINEAR','buy',r6buy),('R6_DISTRIBUTION_LINEAR','distribution',r6dist)]:
        reps.append(dict(representative_id=rid,classification='A_DIRECT_ACTION_COMPATIBLE',member_slot_ids=members,original_candidate={'objective':objective,'learner':'linear'}))
    reps.extend([dict(representative_id='R10_DIRECT_MEAN4_RIDGE',classification='A_DIRECT_ACTION_COMPATIBLE',member_slot_ids=r10direct),dict(representative_id='R10_SEQUENCE_TCN_L5_MID',classification='A_SEQUENCE_ACTION_COMPATIBLE',member_slot_ids=r10seq)])
    monkeypatch.setattr(p,'_authorize',lambda *args:dict(objects=objects,representatives=reps))
    original=pd.read_parquet;columns=[]
    def checked_read(*args,**kwargs):
        columns.extend(kwargs['columns']);return original(*args,**kwargs)
    monkeypatch.setattr(pd,'read_parquet',checked_read)
    loaded=p.load_packets({},pd.to_datetime(['2023-01-03','2024-01-02','2025-01-02']),['A','I'])
    assert not set(columns)&p.FORBIDDEN
    date=pd.Timestamp('2024-01-02')
    assert pd.Timestamp('2023-01-03') not in loaded['packets']['R6_BUY_LINEAR']
    for rid in ('R6_DISTRIBUTION_LINEAR','R10_DIRECT_MEAN4_RIDGE','R10_SEQUENCE_TCN_L5_MID'):
        records=loaded['packets'][rid][date]
        accepted=p.decode_resource_proposals(records,{'I'},{'A'})['accepted']
        assert [r['kind'] for r in accepted]==['REPLACE']
        assert accepted[0]['security_id']=='SID_I'
        assert accepted[0]['entrant_security_id']=='SID_A'
    sequence=loaded['packets']['R10_SEQUENCE_TCN_L5_MID'][date]
    replace=next(r for r in sequence if r['kind']=='REPLACE')
    assert replace['source_score']==pytest.approx(.04)
