"""Synthetic current R6 source/clock tests. No SDK, model, or real data IO."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.inference import current_r6_probes as owner
ORIGINAL_NEEDED_KEYS = owner.needed_probe_keys


@pytest.fixture(autouse=True)
def no_external_work(monkeypatch):
    import socket,joblib
    def forbidden(*args,**kwargs):raise AssertionError("network/model work forbidden")
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    monkeypatch.setattr(socket,'create_connection',forbidden)
    monkeypatch.setattr(joblib,'load',forbidden)


def pin(path):return owner._ref(path)


@pytest.fixture(scope='module')
def graph():
    cal=pd.bdate_range('2023-01-03','2026-02-20')
    rows=[]
    for day in cal:
        for ticker,sid in (('A','000000001'),('B','000000002')):
            rows.append(dict(signal_date=day,ticker=ticker,security_id=sid,feature_available=True,
                is_raw_top20=True,new_buy_eligible=True,raw_top20_set_complete=False,
                raw_a2_rank=1 if ticker=='A' else 2,raw_a2_prediction=.1))
    pred=pd.DataFrame(rows)
    hold=owner._structural(pred,cal,cal[-1])
    day=hold.loc[hold.signal_date.ge('2026-01-01')&hold.cohort_age_sessions.eq(14),'signal_date'].max()
    cal=cal[cal<=day];pred=pred.loc[pred.signal_date.le(day)].reset_index(drop=True)
    keys=owner.needed_probe_keys(pred,cal,day)
    assert len(keys)==4
    return SimpleNamespace(cal=cal,pred=pred,day=day,keys=keys)


def paths_at(tmp_path):
    from scripts.common.storage_paths import StoragePaths,validate
    p=StoragePaths(**{k:tmp_path/k for k in ('repo_root','data_root','cache_root','daily_root','backtest_root','results_root','envs_root')})
    validate(p);return p


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding='utf-8');return path


@pytest.fixture
def prepared(tmp_path,monkeypatch,graph):
    from scripts.research.a2.inference import consensus_paper as consumer
    from scripts.storage import storage_r2a
    paths=paths_at(tmp_path);root=paths.daily_root/'synthetic';root.mkdir(parents=True)
    flags=root/'flags.parquet';prior=root/'prior.parquet';calendar=root/'calendar.parquet'
    graph.pred.loc[graph.pred.signal_date.ge('2026-01-01')].to_parquet(flags,index=False)
    graph.pred.loc[graph.pred.signal_date.lt('2026-01-01')].to_parquet(prior,index=False)
    pd.DataFrame({'trade_date':graph.cal[graph.cal<'2026-01-01']}).to_parquet(calendar,index=False)
    bundle=write(root/'bundle.json',dict(prehistory_ref=pin(prior),prehistory_calendar_ref=pin(calendar),pool_variant_id='TOP100',selection_rule='MANAGER_COUNT_WEIGHT_SUM'))
    monkeypatch.setattr(consumer,'BUNDLE_SHA',pin(bundle)['sha256'])
    monkeypatch.setattr(consumer,'resource_check',lambda:None)
    day=str(graph.day.date());observed=graph.day.tz_localize('America/New_York')+pd.Timedelta(hours=18)
    event=write(root/'event_owner.py',{})
    event.write_text("def apply_event_windows(frame,events):\n    return np.ones(len(frame)), np.zeros(len(frame),bool), np.zeros(len(frame),int)\ndef synthetic_check():\n    return []\n",encoding='utf-8')
    monkeypatch.setattr(owner,'EVENT_OWNER',pin(event))
    receipts=[]
    for ticker in ('A','B'):
        f=root/(ticker+'_rehab.parquet')
        pd.DataFrame({'code':pd.Series(dtype=str),'ex_div_date':pd.Series(dtype=str)}).to_parquet(f,index=False)
        receipts.append(dict(code='US.'+ticker,status='PASS',path=str(f),sha256=pin(f)['sha256'],row_count=0,fetched_at=observed.isoformat()))
    rehab=write(root/'rehab_receipt.json',dict(source='MOOMOO_OPEND_GET_REHAB',status='READY',target_date=day,results=receipts))
    monkeypatch.setattr(owner,'needed_probe_keys',lambda *args:graph.keys.copy())
    monkeypatch.setattr(storage_r2a,'DataStore',lambda *args:object())
    marker=write(root/'raw_metadata.json',{'synthetic':True})
    calls=[]
    def endpoints(store,ticker,dates,clock):
        calls.append((ticker,set(dates)))
        return ({d:100.+i for i,d in enumerate(sorted(dates))},{d:observed for d in dates},[pin(marker)])
    monkeypatch.setattr(owner,'_raw_endpoints',endpoints)
    args=dict(flags_ref=pin(flags),source_bundle_ref=pin(bundle),signal_date=day,decision_as_of=observed.isoformat(),current_report={'report_path':str(root/'report.json')},run_dir=root)
    return SimpleNamespace(paths=paths,root=root,args=args,rehab=rehab,receipts=receipts,calls=calls,observed=observed,graph=graph)


def test_keys_are_exact_original_cohort_predecessors_and_no_future_targets(graph):
    assert graph.keys.label_mature_date.lt(graph.day).all()
    assert graph.keys.groupby('ticker').size().eq(2).all()
    for t,part in graph.keys.groupby('ticker'):
        indexes=graph.cal.get_indexer(part.signal_date)
        assert indexes[1]-indexes[0]==7
    with pytest.raises(ValueError,match='COHORT_PHASE'):
        owner.needed_probe_keys(graph.pred,graph.cal[1:],graph.day)


@pytest.mark.parametrize('positive',[True,False])
def test_exact_dependency_projection_matches_full_original_kernel_current_rows(graph,positive):
    state,decision,build=owner._kernels(graph.day)
    pred=graph.pred.assign(**{k:.01 for k in state.original_inputs.FEATURES})
    labels=pred.loc[pred.signal_date.lt(graph.day)].copy()
    positions=graph.cal.get_indexer(labels.signal_date)
    labels=labels.loc[positions+6<len(graph.cal)].copy();positions=graph.cal.get_indexer(labels.signal_date)
    labels['label_mature_date']=graph.cal[positions+6]
    labels=labels.loc[labels.label_mature_date.lt(graph.day)]
    labels=labels.assign(label_available=True,account_event_unhandled=False,label_unsupported_common_event=False,y_open5=.1 if positive else -.1)
    full,_=build(pred,labels[list(decision.LABEL_COLS)],graph.cal)
    selected=labels.merge(graph.keys[list(owner.KEYS)],on=list(owner.KEYS))
    minimal,_=build(pred,selected[list(decision.LABEL_COLS)],graph.cal)
    pd.testing.assert_frame_equal(state._clean(full['duration'],graph.day),state._clean(minimal['duration'],graph.day))


def test_prepare_qualified_no_event_sources_and_exact_mature_dates(prepared):
    p=prepared;source=owner.prepare_current_r6_probes(p.paths,**p.args)
    assert source['status']=='READY',source
    assert source['flags_ref']==p.args['flags_ref'] and source['source_bundle_ref']==p.args['source_bundle_ref']
    frame=pd.read_parquet(source['probe_ref']['path'])
    assert len(frame)==4 and frame.label_mature_date.lt(p.graph.day).all()
    assert pd.to_datetime(frame.observation_available_at,utc=True).eq(p.observed).all()
    assert frame.label_coordinate.eq(owner.current_r6_label()).all()
    assert len(p.calls)==2
    proof=json.loads(Path(source['qualification_ref']['path']).read_text())
    assert proof['source_complete'] is True and proof['future_unmatured_probe_outcomes_read']==0


@pytest.mark.parametrize('defect',['missing_receipt','missing_code','future_clock','stale_clock','unknown_event','sid_break','raw_gap'])
def test_unknown_coverage_never_becomes_empty_source_success(prepared,monkeypatch,defect):
    p=prepared;payload=json.loads(p.rehab.read_text())
    if defect=='missing_receipt':p.rehab.unlink()
    elif defect=='missing_code':payload['results']=payload['results'][:1];write(p.rehab,payload)
    elif defect in ('future_clock','stale_clock'):
        payload['results'][0]['fetched_at']=(p.observed+pd.Timedelta(days=1) if defect=='future_clock' else p.observed-pd.Timedelta(days=1)).isoformat();write(p.rehab,payload)
    elif defect=='unknown_event':
        row=payload['results'][0];part=p.graph.keys.loc[p.graph.keys.ticker.eq('A')].iloc[0]
        pd.DataFrame([{'code':'US.A','ex_div_date':str(part.label_mature_date.date())}]).to_parquet(row['path'],index=False)
        row.update(sha256=pin(row['path'])['sha256'],row_count=1);write(p.rehab,payload)
    elif defect=='sid_break':
        f=Path(p.args['flags_ref']['path']);frame=pd.read_parquet(f);key=p.graph.keys.iloc[0]
        frame.loc[frame.signal_date.eq(key.execution_date)&frame.ticker.eq(key.ticker),'security_id']='CHANGED';frame.to_parquet(f,index=False);p.args['flags_ref']=pin(f)
    else:
        def missing(*args):raise ValueError('R6_CURRENT_RAW_ENDPOINT_COVERAGE')
        monkeypatch.setattr(owner,'_raw_endpoints',missing)
    result=owner.prepare_current_r6_probes(p.paths,**p.args)
    assert result['status']=='BLOCKED' and result['reason'] and result['probe_ref'] is None


def test_explicit_empty_dependency_set_still_requires_real_producer_and_rehab(prepared,monkeypatch):
    p=prepared;monkeypatch.setattr(owner,'needed_probe_keys',lambda *args:p.graph.keys.iloc[:0].copy())
    def forbidden(*args):raise AssertionError('no numerical endpoint read for empty dependencies')
    monkeypatch.setattr(owner,'_raw_endpoints',forbidden)
    result=owner.prepare_current_r6_probes(p.paths,**p.args)
    assert result['status']=='READY',result
    assert pd.read_parquet(result['probe_ref']['path']).empty
    p.rehab.unlink()
    assert owner.prepare_current_r6_probes(p.paths,**p.args)['status']=='BLOCKED'


def test_current_frame_uses_original_late_discard_and_is_independently_validated(prepared,monkeypatch):
    p=prepared;source=owner.prepare_current_r6_probes(p.paths,**p.args)
    state,_,_=owner._kernels(p.graph.day)
    pred=p.graph.pred.assign(**{k:.01 for k in state.original_inputs.FEATURES})
    result=owner.build_current_duration_frame(p.paths,prediction_prefix=pred,calendar_prefix=p.graph.cal,
        signal_date=p.args['signal_date'],decision_as_of=p.args['decision_as_of'],r6_probe_source=source)
    assert result['qualification']['late_publication_metadata_discarded']>=2
    assert result['frame'].empty  # True late metadata, not a missing source exemption.
    assert not set(result['frame']).intersection(state._OUTCOMES)
    args=dict(frame=result['frame'],qualification=result['qualification'],r6_probe_source=source,
        signal_date=p.args['signal_date'],decision_as_of=p.args['decision_as_of'])
    assert owner.validate_current_duration_frame(p.paths,**args)==result['qualification']
    json.dumps(result['qualification'],allow_nan=False)
    changed=deepcopy(source);changed['flags_ref']={'path':'other','sha256':'0'*64}
    with pytest.raises(ValueError,match='BASE_SOURCE_CHANGED'):
        owner.validate_current_duration_frame(p.paths,**{**args,'r6_probe_source':changed})
    broken=deepcopy(result['qualification']);broken['new_fit_count']=False
    with pytest.raises(ValueError,match='COMPUTATION'):
        owner.validate_current_duration_frame(p.paths,**{**args,'qualification':broken})
    with pytest.raises(ValueError,match='PRODUCER'):
        owner.build_current_duration_frame(p.paths,prediction_prefix=pred,calendar_prefix=p.graph.cal,
            signal_date=p.args['signal_date'],decision_as_of=p.args['decision_as_of'],r6_probe_source=None)


def test_streamed_raw_leaf_skips_unrequested_economic_values(tmp_path):
    path=tmp_path/'raw.csv'
    path.write_text('code,time_key,open,observed_at\nUS.FORBIDDEN,2026-01-05,NOT_A_NUMBER,unknown\nUS.A,2026-01-05,100,2026-01-05T22:00:00Z\n')
    assert owner._selected_leaf_opens(path,{('US.A','2026-01-05')})[('US.A','2026-01-05')][0]==100
    path=tmp_path/'raw.json'
    path.write_text('{"results":[{"T":"FORBIDDEN","o":"NOT_A_NUMBER"},{"T":"A","o":101}]}')
    assert owner._selected_leaf_opens(path,{('A','2026-01-05')})[('A','2026-01-05')][0]==101


def test_same_day_refresh_preserves_base_clock_and_adds_current_source_only(tmp_path,monkeypatch):
    from scripts.research.a2.inference import consensus_current_inputs as inputs,consensus_paper as consumer
    base=dict(flags_ref={'path':'flags','sha256':'a'},source_bundle_ref={'path':'pool','sha256':'b'},source_extension_ref={'path':'extension','sha256':'c'},signal_date='2026-10-15',decision_as_of='2026-10-15T21:00:00Z')
    monkeypatch.setattr(inputs,'_prepare_current_inputs',lambda *a,**k:{'reused':True,'publication':{'path':'old','sha256':'d'}})
    monkeypatch.setattr(consumer,'metadata',lambda *a,**k:deepcopy(base))
    source={'status':'BLOCKED','reason':'synthetic missing source'}
    monkeypatch.setattr(owner,'prepare_current_r6_probes',lambda *a,**k:source)
    calls=[]
    monkeypatch.setattr(consumer,'publish_inputs',lambda *a,**k:(calls.append(k) or {'status':'READY'}))
    result=inputs.refresh_current_inputs(object(),current_report={},run_dir=tmp_path)
    assert calls==[{**base,'r6_probe_source':source}]
    assert result['status']=='READY'


def test_bounded_raw_reader_reuses_two_providers_and_rejects_clock_drift(tmp_path):
    from scripts.storage.refresh_massive_market import ENDPOINT
    csv=tmp_path/'moomoo.csv';stamp='2026-01-05T23:00:00Z'
    csv.write_text('code,time_key,open,observed_at\nUS.A,2026-01-05,100,'+stamp+'\nUS.FORBIDDEN,2027-01-01,NOT_A_NUMBER,unknown\n')
    first=tmp_path/'moomoo.parquet'
    pd.DataFrame([dict(date='2026-01-05',ticker='A',open=100.,source='MOOMOO_OPEND',adjustment='raw',provider_code='US.A',source_id=pin(csv)['sha256'],observed_at=stamp),
        dict(date='2027-01-01',ticker='A',open=np.nan,source='FORBIDDEN',adjustment='qfq',provider_code='UNKNOWN',source_id='unknown',observed_at='unknown')]).to_parquet(first,index=False)
    folder=tmp_path/'massive';folder.mkdir();raw=write(folder/'raw.json',{'results':[{'T':'FORBIDDEN','o':'NOT_A_NUMBER'},{'T':'A','o':101}]})
    ref={**pin(raw),'date':'2026-01-06','observed_at':'2026-01-06T23:00:00Z'}
    write(folder/'checkpoint.json',dict(status='SUCCESS',raw=pin(raw),observed_at=ref['observed_at'],contract=dict(date=ref['date'],url=ENDPOINT+ref['date'],params={'adjusted':'false','include_otc':'false'})))
    second=tmp_path/'massive.parquet'
    pd.DataFrame([dict(date=ref['date'],ticker='A',open=101.,source='MASSIVE_GROUPED',adjustment='raw',provider_code='A',currency='USD',source_id=ref['sha256'],observed_at=ref['observed_at'])]).to_parquet(second,index=False)
    records={
        'prices_daily':dict(dataset='prices_daily',ticker='A',format='parquet',adjustment='raw',source='MOOMOO_OPEND',path=str(first),source_sha256=pin(first)['sha256']),
        'prices_daily_massive':dict(dataset='prices_daily_massive',ticker='A',format='parquet',adjustment='raw',source='MASSIVE_GROUPED',path=str(second),source_sha256=pin(second)['sha256'],lineage=dict(provider='MASSIVE_GROUPED',price_basis='RAW',currency='USD',exchange_timezone='America/New_York',provider_symbol='A',provider_mapping={'provider_symbol':'A'}))}
    class Store:
        def metadata(self,dataset,*args):return records[dataset]
        def resolve_price_inputs(self,record,**kwargs):return [pin(csv)] if record['dataset']=='prices_daily' else [ref]
    values,clocks,refs=owner._raw_endpoints(Store(),'A',{'2026-01-05','2026-01-06'},pd.Timestamp('2026-01-07T23:00:00Z'))
    assert values=={'2026-01-05':100.,'2026-01-06':101.}
    assert len(refs)==5
    bad=write(folder/'checkpoint.json',dict(status='SUCCESS',raw=pin(raw),observed_at='2026-01-07T23:00:00Z',contract=dict(date=ref['date'],url=ENDPOINT+ref['date'],params={'adjusted':'false','include_otc':'false'})))
    with pytest.raises(ValueError,match='CHECKPOINT_CHANGED'):
        owner._raw_endpoints(Store(),'A',{'2026-01-06'},pd.Timestamp('2026-01-07T23:00:00Z'))


@pytest.mark.parametrize('date',['2025-12-31','2027-01-01'])
def test_current_scope_does_not_reopen_other_years(date):
    with pytest.raises(ValueError,match='2026_SIGNAL'):
        owner._scope(date,'2026-10-16T06:12:00Z')


def seed_accepted_rehab(p,mature,fetched):
    """The original daily writes this even when no duration probe is due."""
    root=p.paths.daily_root/'A2_today_recommendation'
    folder=root/'runs'/(pd.Timestamp(fetched).strftime('%Y%m%dT%H%M%S')+'_accepted')
    folder.mkdir(parents=True,exist_ok=True)
    mapped=folder/'universe/mapped_members.parquet';mapped.parent.mkdir()
    pd.DataFrame([{'ticker':t,'security_id':sid} for t,sid in [('A','000000001'),('B','000000002')]]).to_parquet(mapped,index=False)
    rows=[]
    for ticker in ('A','B'):
        f=folder/(ticker+'_rehab.parquet')
        pd.DataFrame({'code':pd.Series(dtype=str),'ex_div_date':pd.Series(dtype=str)}).to_parquet(f,index=False)
        rows.append(dict(code='US.'+ticker,status='PASS',path=str(f),sha256=pin(f)['sha256'],row_count=0,fetched_at=pd.Timestamp(fetched).isoformat()))
    rehab=write(folder/'rehab_receipt.json',dict(source='MOOMOO_OPEND_GET_REHAB',status='READY',target_date=mature,results=rows))
    source=folder/'recommendation_source.json'
    write(source,dict(status='READY',data_date=mature,generated_at=pd.Timestamp(fetched).isoformat(),report_path=str(source),
        universe=dict(report_path=str(mapped.parent/'receipt.json'),universe_members_sha256=pin(mapped)['sha256']),
        unrelated_future_economic_results={'2027':'DO_NOT_DECODE'}))
    capture=dict(status='READY',data_date=mature,generated_at=pd.Timestamp(fetched).isoformat(),report_path=str(folder/'report.json'),
        accepted_source=pin(source),accepted_inputs=[pin(rehab)],unrelated_future_economic_results={'2027':'DO_NOT_DECODE'})
    write(folder/'report.json',capture)
    history=write(root/'history'/(folder.name+'.json'),capture)
    return SimpleNamespace(source=source,rehab=rehab,history=history,folder=folder)


def earlier_raw_observations(p,monkeypatch,*,late=False):
    marker=write(p.root/'historical_raw_metadata.json',{'synthetic':True})
    def endpoints(store,ticker,dates,clock):
        times={d:(clock if late else pd.Timestamp(d).tz_localize('America/New_York')+pd.Timedelta(hours=17)) for d in dates}
        return ({d:100.+i for i,d in enumerate(sorted(dates))},times,[pin(marker)])
    monkeypatch.setattr(owner,'_raw_endpoints',endpoints)


def test_previous_daily_receipts_enable_original_age14_without_forward_probe_registry(prepared,monkeypatch):
    p=prepared
    previous=p.graph.cal[-2]
    assert ORIGINAL_NEEDED_KEYS(p.graph.pred.loc[p.graph.pred.signal_date.le(previous)],p.graph.cal[:-1],previous).empty
    for mature in sorted(set(p.graph.keys.label_mature_date)):
        # NY close +4h crosses the UTC date, but precedes the next session close.
        fetched=mature.tz_localize('America/New_York')+pd.Timedelta(hours=20)
        seed_accepted_rehab(p,str(mature.date()),fetched)
    earlier_raw_observations(p,monkeypatch)
    source=owner.prepare_current_r6_probes(p.paths,**p.args)
    assert source['status']=='READY',source
    proof=json.loads(Path(source['qualification_ref']['path']).read_text())
    assert all(r['rehab_source_status']=='ACCEPTED_REHAB_OBSERVED_BEFORE_STRIDE_DEADLINE' for r in proof['probe_observation_diagnostics'])
    assert not any(r['late_at_original_probe'] for r in proof['probe_observation_diagnostics'])
    state,_,_=owner._kernels(p.graph.day)
    pred=p.graph.pred.assign(**{k:.01 for k in state.original_inputs.FEATURES})
    result=owner.build_current_duration_frame(p.paths,prediction_prefix=pred,calendar_prefix=p.graph.cal,
        signal_date=p.args['signal_date'],decision_as_of=p.args['decision_as_of'],r6_probe_source=source)
    assert result['qualification']['late_publication_metadata_discarded']==0
    assert len(result['frame'])==2 and result['frame'].cohort_age_sessions.eq(14).all()
    owner.validate_current_duration_frame(p.paths,frame=result['frame'],qualification=result['qualification'],
        r6_probe_source=source,signal_date=p.args['signal_date'],decision_as_of=p.args['decision_as_of'])


@pytest.mark.parametrize('defect',['after_deadline','raw_late','unaccepted','tampered'])
def test_accepted_history_never_backdates_or_waives_source_failures(prepared,monkeypatch,defect):
    p=prepared
    seeded=[]
    for mature in sorted(set(p.graph.keys.label_mature_date)):
        fetched=mature.tz_localize('America/New_York')+pd.Timedelta(hours=20)
        if defect=='after_deadline':
            ix=p.graph.cal.get_loc(mature)
            fetched=p.graph.cal[ix+1].tz_localize('America/New_York')+pd.Timedelta(hours=16,seconds=1)
        seeded.append(seed_accepted_rehab(p,str(mature.date()),fetched))
    earlier_raw_observations(p,monkeypatch,late=defect=='raw_late')
    if defect=='unaccepted':
        for item in seeded:
            for path in (item.history,item.folder/'report.json'):
                value=json.loads(path.read_text());value.pop('accepted_inputs');write(path,value)
    if defect=='tampered':
        value=json.loads(seeded[0].rehab.read_text());value['status']='BLOCKED';write(seeded[0].rehab,value)
    source=owner.prepare_current_r6_probes(p.paths,**p.args)
    if defect=='tampered':
        assert source['status']=='BLOCKED' and 'CHANGED' in source['reason']
    else:
        assert source['status']=='READY',source
        proof=json.loads(Path(source['qualification_ref']['path']).read_text())
        assert all(d['late_at_original_probe'] for d in proof['probe_observation_diagnostics'])
        if defect!='raw_late':
            assert all(d['rehab_source_status'].startswith('NO_ACCEPTED_REHAB') for d in proof['probe_observation_diagnostics'])


def test_accepted_metadata_lookup_is_utc_bounded_and_never_reads_unrelated_logs(prepared):
    from scripts.research.a2.inference.consensus_current_inputs import accepted_daily_report_metadata
    p=prepared;q=p.graph.keys.iloc[-1]
    fetched=q.label_mature_date.tz_localize('America/New_York')+pd.Timedelta(hours=20)
    item=seed_accepted_rehab(p,str(q.label_mature_date.date()),fetched)
    root=p.paths.daily_root/'A2_today_recommendation/history'
    (root/'20270101T_future.json').write_text('MUST_NOT_BE_PARSED')
    ix=p.graph.cal.get_loc(q.signal_date)
    deadline=p.graph.cal[ix+7].tz_localize('America/New_York')+pd.Timedelta(hours=16)
    result=accepted_daily_report_metadata(p.paths,str(q.label_mature_date.date()),deadline=deadline)
    assert len(result)==1
    assert result[0]['source_ref']==pin(item.source)
    assert not any('economic' in k for k in result[0])


def test_old_accepted_empty_rehab_cannot_hide_current_window_event(prepared,monkeypatch):
    p=prepared
    for mature in sorted(set(p.graph.keys.label_mature_date)):
        seed_accepted_rehab(p,str(mature.date()),mature.tz_localize('America/New_York')+pd.Timedelta(hours=20))
    q=p.graph.keys.loc[p.graph.keys.ticker.eq('A')].iloc[0]
    receipt=json.loads(p.rehab.read_text());row=next(r for r in receipt['results'] if r['code']=='US.A')
    pd.DataFrame([{'code':'US.A','ex_div_date':str(q.label_mature_date.date())}]).to_parquet(row['path'],index=False)
    row.update(sha256=pin(row['path'])['sha256'],row_count=1);write(p.rehab,receipt)
    def forbidden(*args):pytest.fail('known metadata event must block before open decoding')
    monkeypatch.setattr(owner,'_raw_endpoints',forbidden)
    source=owner.prepare_current_r6_probes(p.paths,**p.args)
    assert source['status']=='BLOCKED' and source['probe_ref'] is None
    assert 'CA_CLASSIFICATION_REQUIRED' in source['reason'] and 'CURRENT_REVISION' in source['reason']


@pytest.mark.parametrize("variant", ["features", "missing", "sid_break", "not_buy_eligible"])
def test_reused_original_hold_matches_structural_probe_dependencies(graph, variant):
    state, decision, build = owner._kernels(graph.day)
    pred = graph.pred.assign(**{k: .013 for k in state.original_inputs.FEATURES})
    if variant == "missing":
        pred.loc[pred.index % 17 == 0, "feature_available"] = False
    elif variant == "sid_break":
        pred.loc[pred.signal_date.ge(graph.cal[-25]) & pred.ticker.eq("A"), "security_id"] = "000000099"
    elif variant == "not_buy_eligible":
        pred.loc[pred.signal_date.ge(graph.cal[-40]) & pred.ticker.eq("B"), "new_buy_eligible"] = False
    expected = ORIGINAL_NEEDED_KEYS(pred, graph.cal, graph.day)
    frames, _ = build(pred, pd.DataFrame(columns=decision.LABEL_COLS), graph.cal)
    actual = owner._probe_keys_from_hold(frames["hold"], graph.cal, graph.day)
    pd.testing.assert_frame_equal(actual, expected, check_dtype=True)


def test_structural_reuse_preserves_full_calendar_and_flag_validation(graph):
    with pytest.raises(ValueError, match="COMPLETE_PREDICTION_KEYS"):
        owner._validate_structural_keys(graph.pred.iloc[2:], graph.cal)
    invalid = graph.pred.copy();invalid["feature_available"] = invalid.feature_available.astype(object);invalid.loc[0,"feature_available"] = None
    with pytest.raises(ValueError, match="FLAGS_UNBOUND"):
        owner._validate_structural_keys(invalid, graph.cal)
    empty = owner._probe_keys_from_hold(pd.DataFrame(), graph.cal, graph.day)
    assert empty.empty and list(empty) == [*owner.KEYS,"execution_date","label_mature_date"]


@pytest.mark.parametrize("objective", ["hold", "duration"])
def test_projected_storage_matches_original_values_dtypes_and_audit(graph, objective):
    state, decision, build = owner._kernels(graph.day)
    pred = graph.pred.assign(**{name: .013 for name in state.original_inputs.FEATURES})
    labels = pred.merge(graph.keys[[*owner.KEYS,"label_mature_date"]], on=list(owner.KEYS))
    labels = labels.assign(label_available=True, account_event_unhandled=False,
        label_unsupported_common_event=False, y_open5=.1)
    labels = labels[list(decision.LABEL_COLS)]
    original, original_audit = build(pred, labels, graph.cal)
    projected, projected_audit = owner._projected_samples(build, pred, labels, graph.cal, graph.day, objective)
    assert original_audit == projected_audit
    if objective == "hold":
        columns = [*owner.KEYS, "cohort_id", "cohort_age_sessions"]
        pd.testing.assert_frame_equal(projected[objective], original[objective][columns])
    else:
        pd.testing.assert_frame_equal(state._clean(projected[objective], graph.day), state._clean(original[objective], graph.day))
        assert len(projected[objective]) < len(original[objective])
    assert all(frame.empty for name, frame in projected.items() if name != objective)


@pytest.mark.parametrize("date_kind", ["string", "timestamp"])
@pytest.mark.parametrize("empty", [False, True])
def test_scan_low_memory_conversion_matches_original(tmp_path, date_kind, empty):
    import pyarrow.dataset as ds
    frame = pd.DataFrame({"signal_date": ["2025-12-31", "2026-01-02", "2026-01-05"],
        "value": [1., float("nan"), 3.], "count": pd.Series([1, None, 3], dtype="Int64"),
        "label": pd.Categorical(["B", "A", "B"])})
    if date_kind == "timestamp":
        frame["signal_date"] = pd.to_datetime(frame.signal_date)
    frame.index = pd.Index([10, 20, 30], name="original_index")
    path = tmp_path / "scan.parquet"; frame.to_parquet(path)
    cols = ["signal_date", "label", "count", "value", "original_index"]
    first, last = ("2026-02-01", "2026-02-02") if empty else ("2026-01-02", "2026-01-05")
    lo, hi = ((first, last) if date_kind == "string" else
        (pd.Timestamp(first).to_pydatetime(), pd.Timestamp(last).to_pydatetime()))
    rule = (ds.field("signal_date") >= lo) & (ds.field("signal_date") <= hi)
    expected = ds.dataset(path, format="parquet").to_table(columns=cols, filter=rule).to_pandas()
    actual = owner._scan(pin(path), cols, "signal_date", first, last)
    pd.testing.assert_frame_equal(actual, expected, check_dtype=True)
