"""Full synthetic owner accounts and frozen383 dispositions, no real readers/fits."""
from dataclasses import asdict
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import joblib
import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.evaluation import consensus_comparison_acceptance as acceptance
from scripts.research.a2.evaluation import consensus_comparison_run as comparison
from scripts.research.a2.evaluation import consensus_shareholder_account as shareholder
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays, TargetDecision
from scripts.research.a2.risk.joint_risk_estimators import RiskBundle


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,sort_keys=True,default=str),encoding='utf8')


@pytest.fixture(scope='module')
def owner_accounts(tmp_path_factory):
    root=tmp_path_factory.mktemp('synthetic_owner')
    spec=importlib.util.spec_from_file_location('_acceptance_owner_fixture',Path(__file__).with_name('test_consensus_shareholder_account.py'))
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    dates=pd.bdate_range('2023-01-02','2025-12-31')
    prices=np.linspace(100,140,len(dates))[:,None]
    market=MarketArrays(dates,['S'],prices.copy(),prices.copy(),adv=np.full(prices.shape,1e9),signal_mask=np.arange(len(dates))<len(dates)-1)
    path_ids=[f'SYNTHETIC_{i}' for i in range(4)]
    def policy(di,ctx):
        mask=np.zeros_like(ctx.decision_mask)
        if di==0 or di==len(dates)-4:mask[:]=True
        target=np.array([[.025],[.1],[.075],[.05]]) if di==0 else np.zeros_like(ctx.current_units)
        return TargetDecision(target,mask,'synthetic acceptance targets')
    replay=shareholder.run_shareholder_cash_account(market,path_ids,policy,task_authority=helper.binding(root,()),
        settlement_calendar=dates,entitlement_events=(),entitlement_security_tickers={},
        entitlement_source_binding=helper.source_binding((),{}))
    assert replay.audit['actual_cash_flow_identity_error_max']<1e-8
    results=[]
    # The original vectorized owner executes four independent cash accounts in
    # one calendar pass. Split only its existing rows/qualification arrays.
    for i,path_id in enumerate(path_ids):
        values={name:getattr(replay,name).loc[getattr(replay,name).path_id.eq(path_id)].copy()
            if 'path_id' in getattr(replay,name) else getattr(replay,name).copy()
            for name in acceptance.LEDGERS if name not in ('state','diagnostics')}
        final=copy.deepcopy(replay.final_state)
        for field in ('accounting_qualified','research_accounting_qualified'):
            final[field]=final[field][i:i+1]
        values.update(metadata=copy.deepcopy(replay.metadata),audit=copy.deepcopy(replay.audit),final_state=final)
        values['metadata']['path_ids']=[path_id]
        results.append(SimpleNamespace(**values))
    return dates,results


@pytest.fixture
def case(tmp_path,monkeypatch,owner_accounts):
    def output(path,**kw):
        comparison.require(Path(path).resolve().is_relative_to(tmp_path.resolve()),'SYNTHETIC_OUTPUT_ROOT_ONLY')
    monkeypatch.setattr(comparison,'assert_safe_output_path',output)
    monkeypatch.setattr(acceptance,'assert_safe_output_path',output)
    monkeypatch.setattr(comparison,'write_json_atomic',save)
    run=tmp_path/'SYNTHETIC_R12';run.mkdir()
    packs={f'p{i:03}':dict(packet_id='core5',fusion_method='equal') for i in range(323)}
    risks={name:dict(members=['LW'],weights=[1.]) for name in ('LW','LW_ALIAS')}
    rows=[dict(coordinate_id=f'C{i:03}',comparison_arm='SYNTHETIC',forecast_pack=p,risk_combination='LW',decision_method='cost_aware',status='PLANNED_NOT_ATTEMPTED') for i,p in enumerate(packs)]
    rows.extend(dict(rows[i],coordinate_id=f'A{i:03}',risk_combination='LW_ALIAS') for i in range(60))
    manifest=run/'COMPARISON_COORDINATES.jsonl';manifest.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf8')
    scope=dict(schema='CONSENSUS_COMPARISON_RESEARCH_SCOPE_R12',research_id=comparison.RESEARCH_ID,output_run=str(run),
        train_and_development_before='2026-01-01',test2026_read_authorized=False,confirmation_read_authorized=False,
        real_trades_authorized=False,old_account_state_reused=False,independent_holdout_claim=False,
        account=dict(currency='USD',type='CASH',initial_cash=3000,fractional=True,
            independent_empty_account_per_coordinate=True,continuous_replay_years=[2023,2024,2025],max_positions=20,
            max_single_weight=.1,max_gross=.95,minimum_trade_usd=5,one_way_all_in_bps=10,fixed_per_fill_usd=0,
            settlement_enabled=True,decision_clock='AFTER_SIGNAL_CLOSE_THEN_NEXT_LEGAL_OPEN',same_corporate_action_and_quote_qualification=True),
        budget=dict(prior_fit_units=2063,max_fit_units=10000,no_reset=True,failed_attempts_count=True),
        comparison=dict(forecast_packs=packs,risk_combinations=risks,decision_methods=['cost_aware'],
            matrix_coordinates_ref=comparison.ref(manifest),total_planned_coordinates=383,neutral_coordinate=['p000','LW','cost_aware']),
        selection=dict(all_planned_coordinates_terminal_before_ranking=True,base_order=acceptance.ORDER,
            development_only=True,ineligible_or_missing_is_not_zero_return=True,no_fusion_preselection=True),
        sensitivities=dict(conditions=acceptance.CONDITIONS,maximum_extra_accounts=12,all_accounts_restarted_empty=True,
            no_retuning=True,selection='TOP_THREE_FULLY_CERTIFIED_BASE_COORDINATES_PLUS_NEUTRAL_IF_CERTIFIED_DEDUPLICATED'))
    save(run/comparison.SCOPE_FILE,scope);master=comparison.ref(run/comparison.SCOPE_FILE)
    monkeypatch.setattr(acceptance,'MASTER_SHA',master['sha256'])
    save(run/comparison.FREEZE_FILE,dict(root_scope_ref=master,matrix_coordinates_ref=comparison.ref(manifest),research_id=comparison.RESEARCH_ID,output_run=str(run)))
    reader=run/'SYNTHETIC_READER.json'
    save(reader,dict(calendar_ref={'path':'synthetic://exchange_calendar','sha256':'b'*64},
        settlement_calendar_ref={'path':'synthetic://bank_calendar','sha256':'c'*64}))
    consumer=run/'SYNTHETIC_CONSUMER.json';save(consumer,dict(synthetic_only=True,reader_scope_ref=comparison.ref(reader)))
    consumer_ref=comparison.ref(consumer)
    frozen,planned,_=comparison.plan(run,scope)
    index=dict(schema='CONSENSUS_COMPARISON_STATUS_R12',identity_sha256='a'*64,
        coordinates=[dict(r,status='INPUT_QUALIFICATION_BLOCKED',reason='SYNTHETIC_PROVIDER_UNAVAILABLE',actual_account_attempted=False) for r in planned])
    dates,replays=owner_accounts
    cache=comparison.DiskRiskCache(run/'evaluation/consensus_comparison/risk_store')
    cache['SYNTHETIC']=RiskBundle('LW','FITTED',('S',),('2022-12-30',),estimated_assets=('S',),covariance=np.array([[.01]]),fitted_state={'synthetic_only':True})
    blob=Path(dict.__getitem__(cache,'SYNTHETIC')['path'])
    for i,replay in enumerate(replays):
        row=index['coordinates'][i]
        coordinate=comparison.extension.Coordinate(row['forecast_pack'],row['risk_combination'],row['decision_method'])
        flow='matrix__'+coordinate.identity;root=run/'evaluation/consensus_account'/flow;root.mkdir(parents=True)
        artifacts={}
        for name in acceptance.LEDGERS:
            if name=='state':continue
            table=pd.DataFrame([dict(json=json.dumps(dict(status='OK',reason='SYNTHETIC')))]) if name=='diagnostics' else getattr(replay,name).copy()
            if 'path_id' in table:table['path_id']=flow
            path=root/(name+'.parquet');table.to_parquet(path,index=False);artifacts[name]=comparison.ref(path)
        meta=copy.deepcopy(replay.metadata);meta['path_ids']=[flow]
        state=dict(risk_cache=cache,metadata=meta,audit=replay.audit,final_state=replay.final_state,freeze_ref=consumer_ref)
        path=root/'state.joblib';joblib.dump(state,path);artifacts['state']=comparison.ref(path)
        receipt=dict(status='COMPLETE',flow_id=flow,matrix_coordinate=asdict(coordinate),matrix_scope_identity=comparison.extension._digest(frozen),
            receipt_path=str(root/'receipt.json'),freeze_ref=consumer_ref,artifacts=artifacts)
        save(root/'receipt.json',receipt)
        row.update(status='COMPLETE',actual_account_attempted=True,receipt_ref=comparison.ref(root/'receipt.json'),reason=None)
    index_path=run/'evaluation/consensus_comparison/status_index.json'
    def sync():
        by={r['coordinate_id']:r for r in index['coordinates']}
        for row in index['coordinates']:
            if row['exact_alias_of'] is not None:
                target=by[row['exact_alias_of']]
                row.update(status='EXACT_ALIAS_REUSED' if target['status']=='COMPLETE' else target['status'],
                    alias_is_independent_mechanism=False,alias_target_status=target['status'],receipt_ref=target.get('receipt_ref'),reason=target.get('reason'))
        save(index_path,index)
    sync()
    save(run/'COMPARISON_QUALIFIED_ACCOUNT_CALENDAR.json',dict(schema='CONSENSUS_COMPARISON_ACCOUNT_CALENDAR_R12',
        master_scope_ref=master,consumer_freeze_ref=consumer_ref,full_account_calendar=True,
        account_sessions=[str(d.date()) for d in dates],settlement_sessions=[str(d.date()) for d in dates],
        calendar_source_ref={'path':'synthetic://exchange_calendar','sha256':'b'*64},settlement_calendar_source_ref={'path':'synthetic://bank_calendar','sha256':'c'*64},
        source='ACTUAL_C_QUALIFIED_LOADED_ARRAYS_METADATA_ONLY',market_values_exported=False))
    (run/'FIT_LOG.jsonl').write_text(json.dumps(dict(event='FIT_FAILED',fit_units=0,hidden_model_numeric={'future2026':'NEVER_DECODE'}))+'\n')
    def update_receipt(i,change):
        row=index['coordinates'][i];path=Path(row['receipt_ref']['path']);value=json.loads(path.read_text());change(value)
        save(path,value);row['receipt_ref']=comparison.ref(path);sync()
    return SimpleNamespace(run=run,index=index,index_path=index_path,sync=sync,blob=blob,update_receipt=update_receipt,tmp=tmp_path)


def test_full_owner_certification_master_ranking_aliases_and_unexecuted_twelve_sensitivities(case):
    c=case
    exported=acceptance.export_owner_audits(c.run)
    assert len(exported['owner_audit_refs'])==4
    report=acceptance.summarize(c.run)
    assert report['ranking']==['C001','C002','C003','C000']
    assert report['qualified_representatives']==4 and report['exact_aliases']==60
    assert report['status']=='TERMINAL_INCOMPLETE' and report['actual_account_attempts']==4
    alias=next(r for r in report['coordinates'] if r['coordinate_id']=='A001')
    assert alias['exact_alias_of']=='C001' and alias['rank'] is None and alias['representative_rank']==1
    assert alias['alias_is_independent_mechanism'] is False
    assert len(report['sensitivity_plan'])==12 and all(not r['executed'] for r in report['sensitivity_plan'])
    assert {r['base_coordinate_id'] for r in report['sensitivity_plan']}=={'C000','C001','C002','C003'}
    assert report['coordinates'][1]['max_observed_position_weight']>.1 # price drift is not a target violation
    assert report['read_scope']['independent_holdout_claim'] is False
    assert report['budget']['cumulative_fit_units']==2063
    pins=acceptance.write_report(report,c.tmp/'results')
    assert len(pd.read_csv(pins['coordinate_metrics']['path']))==383
    assert len(pd.read_csv(pins['sensitivity_execution_plan']['path']))==12


def test_owner_export_restores_refs_without_decoding_risk_bundle_and_is_idempotent(case,monkeypatch):
    c=case;original=joblib.load;loaded=[]
    def load(path,*a,**kw):
        loaded.append(Path(path))
        assert Path(path)!=c.blob,'risk model bundle must remain unread'
        return original(path,*a,**kw)
    monkeypatch.setattr(acceptance.joblib,'load',load)
    first=acceptance.export_owner_audits(c.run);second=acceptance.export_owner_audits(c.run)
    assert first==second and len(loaded)==8
    assert all(p.name=='state.joblib' for p in loaded)


@pytest.mark.parametrize('kind',['state_bytes','cross_run','receipt_pin'])
def test_owner_export_rejects_changed_state_and_cross_run_exact_pins(case,kind):
    c=case;row=c.index['coordinates'][0];receipt=json.loads(Path(row['receipt_ref']['path']).read_text())
    state=Path(receipt['artifacts']['state']['path'])
    if kind=='state_bytes':state.write_bytes(state.read_bytes()+b'changed')
    elif kind=='cross_run':
        outside=c.tmp/'OTHER_RUN/state.joblib';outside.parent.mkdir();outside.write_bytes(state.read_bytes())
        c.update_receipt(0,lambda r:r['artifacts'].update(state=comparison.ref(outside)))
    else:row['receipt_ref']['sha256']='0'*64;c.sync()
    with pytest.raises(ValueError):acceptance.export_owner_audits(c.run)


@pytest.mark.parametrize('kind',['missing_ledger','partial_calendar','bad_nav','failed_audit','annual_reset','not_attempted'])
def test_incomplete_or_uncertified_account_never_enters_ranking(case,kind):
    c=case
    if kind=='missing_ledger':c.update_receipt(1,lambda r:r['artifacts'].pop('positions'))
    elif kind in ('partial_calendar','bad_nav'):
        def change(r):
            path=Path(r['artifacts']['daily']['path']);table=pd.read_parquet(path)
            if kind=='partial_calendar':table=table.drop(index=[100])
            else:table.loc[100,'certified_nav']=np.nan
            table.to_parquet(path,index=False);r['artifacts']['daily']=comparison.ref(path)
        c.update_receipt(1,change)
    elif kind in ('failed_audit','annual_reset'):
        def change(r):
            path=Path(r['artifacts']['state']['path']);state=joblib.load(path)
            if kind=='failed_audit':state['audit']['nav_identity_error_max']=.1
            else:state['metadata']['annual_reset']=True
            joblib.dump(state,path);r['artifacts']['state']=comparison.ref(path)
        c.update_receipt(1,change)
    else:c.index['coordinates'][1]['actual_account_attempted']=False;c.sync()
    acceptance.export_owner_audits(c.run)
    report=acceptance.summarize(c.run)
    rejected=next(r for r in report['coordinates'] if r['coordinate_id']=='C001')
    assert not rejected['qualified'] and rejected['net_total_return'] is None and 'qualification_failure' in rejected
    assert 'C001' not in report['ranking']


def test_all_terminal_gate_precedes_account_state_or_numeric_reads(case,monkeypatch):
    c=case;c.index['coordinates'][10]['status']='PLANNED_NOT_ATTEMPTED';c.sync()
    monkeypatch.setattr(acceptance,'_calendar',lambda *a:pytest.fail('numeric boundary must not be entered'))
    report=acceptance.summarize(c.run)
    assert report['selection_status']=='SELECTION_DEFERRED' and report['ranking']==[]
    with pytest.raises(ValueError,match='ALL_PLANNED'):acceptance.export_owner_audits(c.run)


def test_no_qualified_selection_missing_audits_is_not_zero_performance(case):
    report=acceptance.summarize(case.run)
    assert report['selection_status']=='NO_QUALIFIED_SELECTION' and report['sensitivity_plan']==[]
    assert all(r['net_total_return'] is None for r in report['coordinates'])


def test_budget_reason_projection_and_lifetime_cap_cannot_claim_complete(case):
    c=case;c.index['coordinates'][9].update(status='NOT_TESTABLE',reason='CUMULATIVE_FIT_BUDGET_EXHAUSTED:global_counted_R2')
    c.sync();acceptance.export_owner_audits(c.run)
    path=c.run/'FIT_LOG.jsonl'
    path.write_text(''.join(json.dumps(dict(event='FIT_STARTED',fit_units=1,not_projected={'price2026':12345}))+'\n' for _ in range(7937)))
    report=acceptance.summarize(c.run)
    assert report['budget']['cumulative_fit_units']==10000
    assert report['budget_exhaustion_is_incomplete'] and not report['comparison_complete']
    with path.open('a') as handle:handle.write(json.dumps(dict(event='FIT_STARTED',fit_units=1))+'\n')
    with pytest.raises(ValueError,match='CAP_BREACHED'):acceptance.summarize(c.run)


def test_physical_2026_ledger_rejected_before_numeric_decode(case,monkeypatch):
    c=case
    def change(r):
        path=Path(r['artifacts']['daily']['path']);table=pd.read_parquet(path);table.loc[len(table)-1,'date']=pd.Timestamp('2026-01-02')
        table.to_parquet(path,index=False);r['artifacts']['daily']=comparison.ref(path)
    c.update_receipt(1,change);acceptance.export_owner_audits(c.run)
    original=acceptance.pq.ParquetFile.read
    def read(self,*a,**kw):
        # First account is legal; the mixed second account must be rejected by footer.
        assert '2026-01-02' not in str(self.metadata.row_group(0).column(self.schema.names.index('date')).statistics) if 'date' in self.schema.names else True
        return original(self,*a,**kw)
    monkeypatch.setattr(acceptance.pq.ParquetFile,'read',read)
    with pytest.raises(ValueError,match='Forbidden mixed/test'):acceptance.summarize(c.run)


def test_actual_settlement_2026_rejected_by_footer_before_decode(case,monkeypatch):
    c=case
    def change(r):
        path=Path(r['artifacts']['settlement_ledger']['path']);table=pd.read_parquet(path)
        table.loc[0,'actual_settlement_session']=pd.Timestamp('2026-01-02')
        table.to_parquet(path,index=False);r['artifacts']['settlement_ledger']=comparison.ref(path)
    c.update_receipt(1,change);acceptance.export_owner_audits(c.run)
    original=acceptance.pq.ParquetFile.read
    def read(self,*a,**kw):
        if 'actual_settlement_session' in self.schema.names:
            stat=self.metadata.row_group(0).column(self.schema.names.index('actual_settlement_session')).statistics
            assert str(stat.max)[:10]<'2026-01-01','future actual outcome must not decode'
        return original(self,*a,**kw)
    monkeypatch.setattr(acceptance.pq.ParquetFile,'read',read)
    with pytest.raises(ValueError,match='FORBIDDEN_OPTIONAL_ACCOUNT_CLOCK'):acceptance.summarize(c.run)


def test_nullable_pending_clock_uses_null_schema_without_outcome_read(case):
    c=case;row=c.index['coordinates'][0]
    root,receipt=acceptance._receipt(c.run,row,comparison.extension_scope(json.loads((c.run/comparison.SCOPE_FILE).read_text())))
    path=Path(receipt['artifacts']['settlement_ledger']['path'])
    table=pd.read_parquet(path);table['actual_settlement_session']=None;table.to_parquet(path,index=False)
    receipt['artifacts']['settlement_ledger']=comparison.ref(path)
    loaded=acceptance._frame(c.run,root,receipt,'settlement_ledger',['actual_settlement_session'],optional_clocks=['actual_settlement_session'])
    assert loaded.actual_settlement_session.isna().all()


@pytest.mark.parametrize('kind',['outside_risk_store','integer_final_qualification'])
def test_export_scope_and_original_boolean_qualification_cannot_be_forged(case,kind):
    c=case
    def change(r):
        path=Path(r['artifacts']['state']['path']);state=joblib.load(path)
        if kind=='outside_risk_store':state['risk_cache']=comparison.DiskRiskCache(c.tmp/'OTHER_RUN/risk_store')
        else:state['final_state']['accounting_qualified']=np.array([1])
        joblib.dump(state,path);r['artifacts']['state']=comparison.ref(path)
    c.update_receipt(1,change)
    if kind=='outside_risk_store':
        with pytest.raises(ValueError,match='REFERENCE_ONLY_RISK_CACHE'):acceptance.export_owner_audits(c.run)
    else:
        acceptance.export_owner_audits(c.run);report=acceptance.summarize(c.run)
        assert 'C001' not in report['ranking']


def test_grouped_fingerprints_match_prior_day_filter_hashes_exactly():
    orders=pd.DataFrame([dict(path_id='A',signal_date=pd.Timestamp(day),ticker=ticker,
        decision_semantic='MODEL_TARGET',target_weight=weight,signal_reserved=False)
        for day,ticker,weight in [('2023-01-03','B',.04),('2023-01-02','A',.1),('2023-01-03','A',.08)]])
    fills=pd.DataFrame([dict(path_id='A',signal_date=pd.Timestamp('2023-01-02'),execution_date=pd.Timestamp(day),
        ticker=ticker,side='BUY',notional=notional,settlement_date=pd.NaT)
        for day,ticker,notional in [('2023-01-04','A',20.),('2023-01-03','B',50.),('2023-01-03','A',100.)]])
    def old(orders,fills):
        records=[]
        for day in sorted(set(pd.to_datetime(orders.get('signal_date',[])))|set(pd.to_datetime(fills.get('execution_date',[])))):
            def digest(table,column):
                subset=table.loc[pd.to_datetime(table[column]).eq(day)].drop(columns=['path_id'],errors='ignore') if len(table) else table
                payload=acceptance._json(subset.sort_values(list(subset.columns)).to_dict('records')) if len(subset) else []
                return comparison.extension._digest(payload)
            records.append(dict(coordinate_id='C',date=str(day.date()),decision_sha256=digest(orders,'signal_date'),fills_sha256=digest(fills,'execution_date')))
        return records
    assert acceptance._fingerprints('C',orders,fills)==old(orders,fills)
    assert acceptance._fingerprints('C',orders.iloc[:0],fills)==old(orders.iloc[:0],fills)
    assert acceptance._fingerprints('C',orders,fills.iloc[:0])==old(orders,fills.iloc[:0])
    assert acceptance._fingerprints('C',pd.DataFrame(),pd.DataFrame())==[]


@pytest.fixture
def isolated_summary(tmp_path,monkeypatch):
    # Full admission/calendar/owner integration is covered by case above. These
    # tests isolate terminal bookkeeping without repeating 783-session replay.
    run=tmp_path/'SYNTHETIC_DIAGNOSTIC';run.mkdir()
    rows=[dict(coordinate_id=f'C{i:03}',forecast_pack=f'p{i:03}',risk_combination='LW',decision_method='cost_aware',
        status='INPUT_QUALIFICATION_BLOCKED',reason='SYNTHETIC_MISSING_PROVIDER',actual_account_attempted=False,exact_alias_of=None) for i in range(323)]
    rows.extend(dict(rows[i],coordinate_id=f'A{i:03}',exact_alias_of=rows[i]['coordinate_id']) for i in range(60))
    index=run/'status_index.json';save(index,{'synthetic_only':True})
    pin=comparison.ref(index);scope={'comparison':{'neutral_coordinate':['p000','LW','cost_aware']}}
    monkeypatch.setattr(acceptance,'_context',lambda *a:(run,scope,{},pin,pin,pin,rows))
    monkeypatch.setattr(acceptance,'_calendar',lambda *a:None)
    monkeypatch.setattr(acceptance,'_budget',lambda *a:dict(cumulative_fit_units=2063,metadata_projection_columns=['event','fit_units']))
    monkeypatch.setattr(acceptance,'_account',lambda *a:pytest.fail('incomplete account must not decode economic rows'))
    return run,rows


def test_claimed_complete_without_owner_receipt_is_unqualified_not_zero(isolated_summary):
    run,rows=isolated_summary
    for row in rows[:4]:row.update(status='COMPLETE',actual_account_attempted=True)
    report=acceptance.summarize(run)
    assert report['selection_status']=='NO_QUALIFIED_SELECTION'
    assert all(report['coordinates'][i]['qualification_failure']=='ORIGINAL_ACCOUNT_RECEIPT_MISSING' for i in range(4))
    assert all(report['coordinates'][i]['net_total_return'] is None for i in range(4))


def test_not_testable_budget_reason_hidden_in_diagnostics_is_counted_without_payload_decode(isolated_summary,monkeypatch):
    run,rows=isolated_summary;root=run/'account';root.mkdir()
    path=root/'diagnostics.parquet'
    raw=json.dumps(dict(signal_date='2025-05-02',status='NOT_TESTABLE_RISK_PRESERVE_UNITS',
        reason='PHYSICAL_LEARNED_CAP_EXCEEDED',risk_payload={'future2026_price':999.,'array':[12,34]}))
    pd.DataFrame([{'json':raw}]).to_parquet(path,index=False)
    receipt={'status':'NOT_TESTABLE','artifacts':{'diagnostics':comparison.ref(path)},'failure':{'reason':'PRIMARY_RISK_INPUT_OR_ESTIMATION_BLOCKED'}}
    rows[0].update(status='NOT_TESTABLE',actual_account_attempted=True,receipt_ref={'path':str(root/'receipt.json'),'sha256':'a'*64})
    monkeypatch.setattr(acceptance,'_receipt',lambda *a:(root,receipt))
    loads=acceptance.json.loads;decoded=[]
    def selected_only(value,*a,**kw):
        decoded.append(value)
        assert 'future2026_price' not in str(value),'unselected numeric payload cannot be JSON-decoded'
        return loads(value,*a,**kw)
    monkeypatch.setattr(acceptance.json,'loads',selected_only)
    report=acceptance.summarize(run)
    assert report['budget_exhaustion_is_incomplete'] and report['comparison_truncated_by_budget']
    assert report['selection_status']=='NO_QUALIFIED_SELECTION' and decoded
    assert any('PHYSICAL_LEARNED_CAP_EXCEEDED' in key for key in report['coordinates'][0]['diagnostic_reason_counts'])


def test_complete_label_with_budget_reason_remains_incomplete_before_numeric_read(isolated_summary,monkeypatch):
    run,rows=isolated_summary
    rows[0].update(status='COMPLETE',actual_account_attempted=True,reason='CUMULATIVE_FIT_BUDGET_EXHAUSTED',
        receipt_ref={'path':str(run/'receipt.json'),'sha256':'a'*64})
    monkeypatch.setattr(acceptance,'_receipt',lambda *a:(run,{'status':'COMPLETE','artifacts':{}}))
    report=acceptance.summarize(run)
    assert report['budget_exhaustion_is_incomplete'] and report['qualified_representatives']==0
    assert report['coordinates'][0]['qualification_failure']=='CUMULATIVE_FIT_BUDGET_EXHAUSTED'


@pytest.fixture
def distinct_calendar_metadata(tmp_path):
    # Metadata only. These synthetic weekdays intentionally model the calendar
    # distinction, without importing a real holiday/source table.
    run=tmp_path/'SYNTHETIC_DISTINCT_CALENDARS';run.mkdir()
    weekdays=pd.bdate_range('2023-01-02','2025-12-31')
    exchange=weekdays.difference(pd.DatetimeIndex(['2023-04-07']))
    bank=weekdays.difference(pd.DatetimeIndex(['2023-10-09']))
    master=run/'MASTER.json';save(master,{'synthetic_only':True})
    refs=dict(calendar_ref={'path':'synthetic://exchange','sha256':'d'*64},
        settlement_calendar_ref={'path':'synthetic://bank','sha256':'e'*64})
    reader=run/'READER.json';save(reader,refs)
    consumer=run/'CONSUMER.json';save(consumer,dict(reader_scope_ref=comparison.ref(reader)))
    path=run/'COMPARISON_QUALIFIED_ACCOUNT_CALENDAR.json'
    value=dict(schema='CONSENSUS_COMPARISON_ACCOUNT_CALENDAR_R12',master_scope_ref=comparison.ref(master),
        consumer_freeze_ref=comparison.ref(consumer),full_account_calendar=True,market_values_exported=False,
        source='ACTUAL_C_QUALIFIED_LOADED_ARRAYS_METADATA_ONLY',account_sessions=[str(d.date()) for d in exchange],
        settlement_sessions=[str(d.date()) for d in bank],calendar_source_ref=refs['calendar_ref'],
        settlement_calendar_source_ref=refs['settlement_calendar_ref'])
    save(path,value)
    return SimpleNamespace(run=run,path=path,value=value,master=comparison.ref(master),exchange=exchange,bank=bank)


def test_calendar_keeps_distinct_exchange_and_bank_holidays_and_original_settlement_rule(distinct_calendar_metadata):
    c=distinct_calendar_metadata
    exchange,bank,value,pin=acceptance._calendar(c.run,None,c.master)
    assert exchange.equals(c.exchange) and bank.equals(c.bank)
    assert not exchange.isin(bank).all() and not bank.isin(exchange).all()
    assert pd.Timestamp('2023-04-07') not in exchange and pd.Timestamp('2023-04-07') in bank
    assert pd.Timestamp('2023-10-09') in exchange and pd.Timestamp('2023-10-09') not in bank
    # Original owner counts settlement-bank sessions even when the exchange is
    # closed, and skips bank holidays while accepting an exchange trading day.
    assert acceptance.cash.settlement_date('2023-04-06',bank,trading_calendar=exchange)==pd.Timestamp('2023-04-10')
    assert acceptance.cash.settlement_date('2023-10-06',bank,trading_calendar=exchange)==pd.Timestamp('2023-10-11')
    assert acceptance.cash.settlement_date('2023-10-09',bank,trading_calendar=exchange)==pd.Timestamp('2023-10-11')
    assert value==c.value and pin==comparison.ref(c.path)


@pytest.mark.parametrize('kind',['duplicate','unsorted','empty','missing_year','future','source_swap','reader_pin'])
def test_distinct_calendars_still_require_original_full_scope_and_exact_source_refs(distinct_calendar_metadata,kind):
    c=distinct_calendar_metadata;value=c.value
    if kind=='duplicate':value['settlement_sessions'].append(value['settlement_sessions'][-1])
    elif kind=='unsorted':value['settlement_sessions']=value['settlement_sessions'][::-1]
    elif kind=='empty':value['settlement_sessions']=[]
    elif kind=='missing_year':value['settlement_sessions']=[d for d in value['settlement_sessions'] if d[:4]!='2024']
    elif kind=='future':value['settlement_sessions'].append('2026-01-02')
    elif kind=='source_swap':value['settlement_calendar_source_ref']=value['calendar_source_ref']
    else:
        consumer=Path(value['consumer_freeze_ref']['path']);consumer.write_text(consumer.read_text()+' ')
    save(c.path,value)
    with pytest.raises(ValueError):acceptance._calendar(c.run,None,c.master)


@pytest.fixture
def writer_metadata_toy(tmp_path,monkeypatch):
    def output(path,**kwargs):
        assert kwargs['kind']=='results'
        comparison.require(Path(path).resolve().is_relative_to(tmp_path.resolve()),'SYNTHETIC_OUTPUT_ROOT_ONLY')
    monkeypatch.setattr(acceptance,'assert_safe_output_path',output)
    run=tmp_path/'SYNTHETIC_WRITER_ONLY';run.mkdir()
    reference=run/'SYNTHETIC_METADATA.json';save(reference,dict(synthetic_only=True,no_real_account_or_source=True))
    pin=comparison.ref(reference)
    coordinates=[dict(coordinate_id=f'C{i:03}',forecast_pack=f'p{i:03}',risk_combination='LW',decision_method='cost_aware',
        qualified=i==0,exact_alias_of=None,receipt_ref=pin,calendar_ref=pin) for i in range(323)]
    coordinates.extend(dict(coordinates[i],coordinate_id=f'A{i:03}',risk_combination='LW_ALIAS',exact_alias_of=f'C{i:03}') for i in range(60))
    plan=[dict(base_coordinate_id='C000',fee_condition=condition,base_owner_receipt_ref=pin,
        initial_cash=3000,empty_independent_account=True,no_retuning=True,
        execution_authorized_by_this_report=False,executed=False,status='PLANNED_NOT_ATTEMPTED')
        for condition in acceptance.CONDITIONS]
    fingerprints=[dict(coordinate_id='C000',date=day,decision_sha256=decision*64,fills_sha256=fill*64)
        for day,decision,fill in [('2023-01-04','a','0'),('2023-01-02','b','1'),('2023-01-03','c','2')]]
    report=dict(schema=acceptance.SCHEMA,acceptance_source_ref=comparison.ref(acceptance.__file__),master_scope_ref=pin,
        matrix_scope_ref=pin,status_index_ref=pin,all_planned_coordinates_terminal=True,planned_labels=383,
        coordinates=coordinates,ranking=['C000'],sensitivity_plan=plan,
        read_scope=dict(own_run=str(run),before='2026-01-01',test2026_read=False,confirmation_read=False,
            independent_holdout_claim=False,synthetic_only=True),
        daily_decision_trade_fingerprints=fingerprints,other_metadata={'unchanged':['synthetic only',17]})
    return report,tmp_path/'results'


@pytest.mark.parametrize('empty',[False,True])
def test_writer_external_fingerprint_csv_roundtrip_preserves_metadata_and_fee_reader(writer_metadata_toy,monkeypatch,empty):
    from scripts.research.a2.evaluation import consensus_comparison_sensitivity as fee
    report,output=writer_metadata_toy
    if empty:report['daily_decision_trade_fingerprints']=[]
    original_fingerprints=report['daily_decision_trade_fingerprints'];before=copy.deepcopy(report)
    pins=acceptance.write_report(report,output)
    assert report==before and report['daily_decision_trade_fingerprints'] is original_fingerprints
    assert acceptance.write_report(report,output)==pins
    persisted=json.loads(Path(pins['report']['path']).read_text(encoding='utf8'))
    for key,value in report.items():
        if key!='daily_decision_trade_fingerprints':assert persisted[key]==value
    metadata=persisted['daily_decision_trade_fingerprints']
    assert metadata==dict(artifact_ref=pins['daily_decision_trade_fingerprints'],row_count=len(original_fingerprints),
        format='CSV',inline_rows=False,schema=dict(columns=['coordinate_id','date','decision_sha256','fills_sha256'],
            record_unit='ONE_COORDINATE_DATE_DECISION_AND_FILL_HASH_PAIR'))
    assert metadata['artifact_ref']==comparison.ref(metadata['artifact_ref']['path'])
    table=pd.read_csv(metadata['artifact_ref']['path'],dtype=str,keep_default_na=False)
    assert list(table.columns)==metadata['schema']['columns']
    assert table.to_dict('records')==original_fingerprints
    assert Path(pins['report']['path']).stat().st_size<8*1024*1024 # Fee reader cap remains unchanged.
    original_open=Path.open
    def deny_csv(self,*args,**kwargs):
        assert self.suffix!='.csv','fee acceptance metadata projection must not open fingerprint CSV'
        return original_open(self,*args,**kwargs)
    with monkeypatch.context() as guard:
        guard.setattr(Path,'open',deny_csv)
        decoded=fee._acceptance(pins['report'])
        assert decoded['ranking']==report['ranking'] and decoded['sensitivity_plan']==report['sensitivity_plan']
        assert decoded['coordinates']==report['coordinates']
        assert decoded['acceptance_source_ref']==comparison.ref(acceptance.__file__)
        plan,by_id=fee._plan(decoded,dict(comparison=dict(neutral_coordinate=['p000','LW','cost_aware'])))
        assert plan==report['sensitivity_plan'] and len(by_id)==383


def test_writer_external_fingerprint_artifact_is_immutable(writer_metadata_toy):
    report,output=writer_metadata_toy
    pins=acceptance.write_report(report,output)
    report['daily_decision_trade_fingerprints'][0]['fills_sha256']='f'*64
    with pytest.raises(ValueError,match='IMMUTABLE_EXPORT_CHANGED'):acceptance.write_report(report,output)
    persisted=json.loads(Path(pins['report']['path']).read_text(encoding='utf8'))
    assert persisted['daily_decision_trade_fingerprints']['artifact_ref']==comparison.ref(pins['daily_decision_trade_fingerprints']['path'])
