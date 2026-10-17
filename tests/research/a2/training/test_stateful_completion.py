"""Synthetic own-run metadata only; no fit or economic artifact readers."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from scripts.research.a2.training import stateful_completion as c


def write(path,item):
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(item,ensure_ascii=False)+'\n',encoding='utf-8')


def metadata_run(tmp_path,monkeypatch):
 root=tmp_path/'backtests';run=root/'task'/'run';run.mkdir(parents=True)
 results=tmp_path/'results'/'task'/'V24'
 repo=Path(c.__file__).resolve().parents[4]
 monkeypatch.setattr(c,'resolve_storage_paths',lambda:SimpleNamespace(backtest_root=root,results_root=tmp_path/'results',repo_root=repo))
 def check_report(path,purpose):assert Path(path).resolve().is_relative_to(results) and purpose=='report'
 monkeypatch.setattr(c,'assert_write_path',check_report)
 fusion,aux,risk=c.source_maps(repo)
 from scripts.research.a2.risk.joint_risk_estimators import CONFIGS
 risk_names=list(CONFIGS)
 applies=set(range(1,30))|set(range(32,68))|set(range(82,85))|set(range(94,98))|{99}|set(range(102,107))
 rows=[]
 for i in range(1,107):
  row=dict(method_id=f'M{i:03d}',method=f'SYNTHETIC_{i}',category='synthetic',purpose='fixture only',status='ROOT_PENDING',actual_fit_units=0,actual_account_paths=0,empirical_validation='NOT_RUN',applicability='A_APPLIES' if i in applies else 'HANDOFF_B',scientific_role='VALUE_PRIMITIVE' if i<30 else 'RISK_SIGNAL_PROXY' if 45<=i<=67 else 'RULE')
  if i<30:row['native_model_id']='ridge' if i==1 else f'fixture_value{i}'
  if 50<=i<=67:row['method']=risk_names[i-50]
  rows.append(row)
 coverage=dict(count=106,version='V24',request_sha256='a'*64,methods=rows,status='ROOT_PENDING')
 write(run/'method_coverage.json',coverage)
 cfg=dict(strategy_id='task',parent_task_id='task',run_id='run',strategy_version='V24',training_cutoff_exclusive='2026-01-01',evaluation_years=[2023,2024,2025],results_directory=str(results),phase='FROZEN',prior_cumulative_fit_units=18,prior_account_paths=4,request_sha256='a'*64,fractional_primary=True,**{'2026_rows_read':0})
 for stage in ('value','fusion','risk','aux'):cfg[stage+'_training']=dict(status='FROZEN',module_sha256='b'*64,budget_bucket='risk_primary' if stage in ('risk','aux') else 'value_meta_primary',max_new_bucket_fit_units=72 if stage in ('risk','aux') else 384,max_fit_units=882,max_model_year_attempts=201)
 candidates=[dict(candidate_id='B_fixture',source_method_ids=['M001','M050','M099','M102'],action='raw',gross='fixed',control='none',forecast='none',value_model='ridge',risk='DIAG',scientific_tuple_sha256='d'*64)]
 pin=c.hashlib.sha256(json.dumps(candidates,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
 cfg.update(stateful_candidates=candidates,stateful_replay=dict(status='FROZEN',module_sha256='c'*64,candidates_sha256=pin))
 write(run/'run_config.json',cfg)
 return run,results,cfg,coverage


def test_fit_failure_counts_not_double_counted_and_alias_zero():
 cfg=dict(prior_cumulative_fit_units=18,prior_account_paths=4)
 fits=[dict(event='MODEL_YEAR_ATTEMPT_STARTED',model_id='failed',year=2023),
       dict(event='FIT_STARTED',model_id='failed',year=2023,fit_units=1,budget_bucket='value_meta_primary'),
       dict(event='MODEL_YEAR_FAILED',model_id='failed',year=2023,fit_units=999),
       dict(event='RISK_METHOD_EXACT_REUSED',model_id='RISK::HISTVOL',year=2023,fit_units=0)]
 paths=[dict(event='ACCOUNT_PATH_ATTEMPT_STARTED',path_units=1,candidate_id='a'),dict(event='ACCOUNT_PATH_FAILED',candidate_id='a'),dict(event='ACCOUNT_PATH_ATTEMPT_STARTED',path_units=1,candidate_id='b'),dict(event='ACCOUNT_PATH_COMPLETE',candidate_id='b')]
 out=c.budget_audit(cfg,fits,paths)
 assert out['new_fit_units']==1 and out['cumulative_fit_units']==19 and out['failed_fit_units_included']==1
 assert out['model_year_attempts']==1 and out['account_path_attempts_cumulative']==6 and out['failed_path_attempts']==1
 assert out['aliases_new_fit_units']==0 and out['buckets']['risk_primary']['used']==0


def test_bucket_and_global_excess_and_alias_nonzero_fail_audit():
 cfg=dict(prior_cumulative_fit_units=18,prior_account_paths=4)
 fits=[dict(event='FIT_STARTED',fit_units=385,budget_bucket='value_meta_primary'),dict(event='FIT_STARTED',fit_units=500,budget_bucket='UNDECLARED'),dict(event='RISK_METHOD_EXACT_REUSED',fit_units=1)]
 out=c.budget_audit(cfg,fits,[])
 assert out['status']=='BUDGET_AUDIT_FAILED'
 assert {'FIT_BUCKET_EXCEEDED:value_meta_primary','GLOBAL_FIT_CAP_EXCEEDED','ALIAS_HAS_NONZERO_FIT_UNITS','UNDECLARED_FIT_BUCKET:UNDECLARED'}<=set(out['violations'])


def test_projection_never_decodes_economic_number_or_failure_payload(tmp_path,monkeypatch):
 path=tmp_path/'audit.json';write(path,dict(status='SYNTHETIC',selection_eligibility={},certified_nav=987654.321,net_return=987654.321,accounting_exceptions=[dict(cash=987654.321)],prefix_identity={'positions':[987654.321]},failure={'type':'ValueError','message':'BLOCKED_INPUT secret NAV 987654.321'}))
 old=c.json.loads;decoded=[]
 def guarded(token,*a,**kw):
  decoded.append(token)
  if '987654' in token:raise AssertionError('economic payload decoded')
  return old(token,*a,**kw)
 monkeypatch.setattr(c.json,'loads',guarded)
 result=c.read_metadata(tmp_path,path,c.AUDIT)
 assert result['failure']['message']=='BLOCKED_INPUT' and 'certified_nav' not in result and 'prefix_identity' not in result
 assert not any('987654' in token for token in decoded)


def test_post2025_metadata_and_nonmetadata_body_refused(tmp_path):
 write(tmp_path/'receipt.json',dict(year=2025,fitted_dates=['2026-01-02']))
 with pytest.raises(ValueError,match='POST2025_OBSERVATION'):
  c.read_metadata(tmp_path,'receipt.json',c.RECEIPT)
 with pytest.raises(ValueError,match='ONLY_OWN_RUN_JSON'):
  c.read_metadata(tmp_path,'ledger.parquet',c.ALL)
 with pytest.raises(ValueError,match='ONLY_OWN_RUN_JSON'):
  c.read_metadata(tmp_path,tmp_path.parent/'outside.json',c.ALL)


def test_build_preserves106_identity_and_baseline_not_testable(tmp_path,monkeypatch):
 run,out,cfg,original=metadata_run(tmp_path,monkeypatch)
 # A diagnostic or trained model never proves the baseline account is certified.
 receipt=dict(status='FAILED',model_id='ridge',year=2023,fit_units=1,failure={'type':'RuntimeError','message':'FIT_TIMEOUT'})
 write(run/'models/value/ridge/2023/fit_receipt.json',receipt)
 (run/'FIT_LOG.jsonl').write_text(json.dumps(dict(event='FIT_STARTED',model_id='ridge',year=2023,component='PREDICTOR',fit_units=1,budget_bucket='value_meta_primary'))+'\n'+json.dumps(dict(event='MODEL_YEAR_FAILED',model_id='ridge',year=2023,fit_units=9))+'\n',encoding='utf-8')
 answer=c.build_report(run)
 report=json.loads((out/'METHOD_COVERAGE_REPORT.json').read_text(encoding='utf-8'));task=json.loads((out/'TASK_RECORD.json').read_text(encoding='utf-8'))
 assert answer['status']=='NOT_TESTABLE' and task['selection_performed'] is False and task['test_2026_rows_read']==0
 assert [m['method'] for m in report['methods']]==[m['method'] for m in original['methods']]
 assert report['methods'][0]['status']=='FAILED' and report['methods'][0]['actual_fit_units']==1
 assert report['methods'][29]['status']=='NOT_ASSESSED_BY_A' and report['all_106_trained'] is False
 assert report['observed_summary']['A_methods']==78 and report['observed_summary']['B_handoff_not_assessed']==28
 assert report['methods'][44]['observed_runtime']['diagnostic_only'] is True
 assert report['methods'][60]['observed_runtime']['alias_of']=='M050' and report['methods'][103]['observed_runtime']['alias_of']=='M103'
 assert 'NO_FINALIST' not in task['status']


def test_full_three_year_qualification_booleans_only(tmp_path,monkeypatch):
 run,out,cfg,_=metadata_run(tmp_path,monkeypatch)
 audit=dict(status='ACTUAL_CONTINUOUS_PRE2026_REPLAY_COMPLETE',batch=1,calendar_sessions=752,annual_reset=False,candidates_sha256=cfg['stateful_replay']['candidates_sha256'],source_closure={'module_sha256':'c'*64},selection_eligibility={'B_fixture':{str(y):dict(sessions=n,accounting_qualified_all=True,certified_nav_positive_and_finite_all=True,net_return_finite_except_initial=True) for y,n in zip((2023,2024,2025),(250,252,250))}},accounting_exceptions=[dict(cash=987654.321)])
 write(run/'ledgers/stateful/attempt_0001/audit.json',audit)
 c.build_report(run)
 task=json.loads((out/'TASK_RECORD.json').read_text(encoding='utf-8'))
 assert task['status']=='PENDING_ECONOMIC_SELECTION' and task['selection_performed'] is False
 audit['selection_eligibility']['B_fixture']['2024']['accounting_qualified_all']=False
 write(run/'ledgers/stateful/attempt_0001/audit.json',audit);c.build_report(run)
 assert json.loads((out/'TASK_RECORD.json').read_text(encoding='utf-8'))['status']=='NOT_TESTABLE'
 del audit['selection_eligibility']['B_fixture']['2024'];write(run/'ledgers/stateful/attempt_0001/audit.json',audit)
 with pytest.raises(ValueError,match='ALL_THREE'):c.build_report(run)


def test_receipt_source_qualification_and_slot_identity(tmp_path,monkeypatch):
 run,out,cfg,_=metadata_run(tmp_path,monkeypatch)
 path=run/'models/value/ridge/2023/fit_receipt.json'
 receipt=dict(status='TRAINED',model_id='ridge',year=2023,fit_units=2,model_sha256='f'*64,scientific_feature_pit_qualified=True,scientific_target_qualified=True,reuse_tuple={'source_pins':{'module_sha256':'b'*64}},calibration={'sigma':987654.321})
 write(path,receipt)
 a=c.annual_state(run,'value','ridge',2023,{},cfg['value_training']);assert a['metadata_qualified'] is True
 receipt['scientific_target_qualified']=False;write(path,receipt)
 assert c.annual_state(run,'value','ridge',2023,{},cfg['value_training'])['state']=='UNQUALIFIED_RECEIPT'
 receipt.update(scientific_target_qualified=True,model_id='different_model');write(path,receipt)
 with pytest.raises(ValueError,match='SLOT_IDENTITY'):c.annual_state(run,'value','ridge',2023,{},cfg['value_training'])


def test_incomplete_append_is_never_budget_completion(tmp_path,monkeypatch):
 run,out,cfg,_=metadata_run(tmp_path,monkeypatch)
 (run/'FIT_LOG.jsonl').write_text('{"event":"FIT_STARTED","fit_units":',encoding='utf-8')
 c.build_report(run)
 task=json.loads((out/'TASK_RECORD.json').read_text(encoding='utf-8'));budget=json.loads((out/'FINITE_BUDGET_AUDIT.json').read_text(encoding='utf-8'))
 assert task['partial_append_snapshot'] is True and budget['status']=='INCOMPLETE_APPEND_SNAPSHOT'


def test_technical_repair_preserves_failed_generation_and_counts_all_fits(tmp_path,monkeypatch):
 run,out,cfg,_=metadata_run(tmp_path,monkeypatch)
 # Bind the existing EBM source declaration, while all observations remain synthetic.
 generation='technical_repair_1';ledger='VALUE_REPAIR::ebm::technical_repair_1'
 cfg['value_repair']=dict(status='FROZEN',method='ebm',generation=generation,repair_transport_sha256='e'*64,budget_bucket='value_meta_technical',max_new_bucket_fit_units=384,max_fit_units=882,max_model_year_attempts=201)
 write(run/'run_config.json',cfg)
 coverage=json.loads((run/'method_coverage.json').read_text(encoding='utf-8'));coverage['methods'][10]['native_model_id']='ebm';write(run/'method_coverage.json',coverage)
 events=[]
 for year in (2023,2024,2025):
  old=run/f'models/value/ebm/{year}/fit_receipt.json'
  write(old,dict(status='FAILED',model_id='ebm',year=year,fit_units=1,reuse_tuple_sha256='f'*64,failure={'type':'RuntimeError','message':'FIT_WORKER_DID_NOT_EXIT_CLEANLY_AFTER_RESULT'}))
  repaired=run/f'models/value/ebm/{year}/{generation}/fit_receipt.json'
  write(repaired,dict(status='TRAINED',model_id='ebm',ledger_model_id=ledger,generation=generation,year=year,fit_units=2,model_sha256='d'*64,scientific_target_qualified=True,scientific_feature_pit_qualified=True,old_failed_receipt={'receipt_sha256':c.sha(old)},reuse_tuple={'original_scientific_tuple_sha256':'f'*64,'source_pins':{'module_sha256':'b'*64,'repair_transport_sha256':'e'*64}}))
  events += [dict(event='FIT_STARTED',model_id='ebm',year=year,component='OLD_FAILED_PREDICTOR',fit_units=1,budget_bucket='value_meta_primary'),dict(event='MODEL_YEAR_FAILED',model_id='ebm',year=year,fit_units=1)]
  events += [dict(event='FIT_STARTED',model_id=ledger,year=year,component='REPAIRED_PREDICTOR',fit_units=1,budget_bucket='value_meta_technical'),dict(event='FIT_STARTED',model_id=ledger,year=year,component='HELDOUT_RESIDUAL_SIGMA',fit_units=1,budget_bucket='value_meta_technical')]
 (run/'FIT_LOG.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events),encoding='utf-8')
 c.build_report(run)
 report=json.loads((out/'METHOD_COVERAGE_REPORT.json').read_text(encoding='utf-8'));obs=report['methods'][10]['observed_runtime']
 assert obs['state']=='MODEL_METADATA_QUALIFIED' and obs['actual_fit_units']==9
 assert [a['state'] for a in obs['primary_annual_models']]==['FAILED']*3
 assert [a['state'] for a in obs['technical_repair_models']]==['TRAINED']*3
 audit=json.loads((out/'FINITE_BUDGET_AUDIT.json').read_text(encoding='utf-8'))
 assert audit['new_fit_units']==9 and audit['failed_fit_units_included']==3 and audit['buckets']['value_meta_technical']['used']==6
 assert audit['buckets']['conditional_final']['authorization_state']=='NOT_STARTED_AUTH_NOT_PRESENT'


def test_blocked_data_budget_stop_and_fit_error_are_distinct():
 assert c.failure_state({'failure':{'message':'BLOCKED_DATA_CHRONOLOGICAL_TRAIN_CALIBRATION'}})=='BLOCKED_INPUT'
 assert c.failure_state({'failure':{'message':'BLOCKED_DEPENDENCY_GENUINE_BACKEND'}})=='BLOCKED_DEPENDENCY'
 assert c.failure_state({'failure':{'message':'FROZEN_FIT_BUCKET_EXHAUSTED'}})=='BUDGET_STOP_NOT_COMPLETE'
 assert c.failure_state({'failure':{'message':'FIT_WORKER_DID_NOT_EXIT_CLEANLY_AFTER_RESULT'}})=='FAILED'


def test_original_diag_presentation_title_is_preserved(tmp_path,monkeypatch):
 run,out,cfg,_=metadata_run(tmp_path,monkeypatch)
 path=run/'method_coverage.json';coverage=json.loads(path.read_text(encoding='utf-8'))
 coverage['methods'][49]['method']='Diagonal / DIAG';write(path,coverage)
 c.build_report(run)
 row=json.loads((out/'METHOD_COVERAGE_REPORT.json').read_text(encoding='utf-8'))['methods'][49]
 assert row['method']=='Diagonal / DIAG' and row['observed_runtime']['model_binding']=={'group':'risk','model_id':'DIAG'}

def continuation_fixture(tmp_path,monkeypatch):
    root=tmp_path/'backtests';run=root/'task'/'run';run.mkdir(parents=True);out=tmp_path/'results'/'task'/'V24'
    monkeypatch.setattr(c,'resolve_storage_paths',lambda:SimpleNamespace(backtest_root=root,results_root=tmp_path/'results'))
    monkeypatch.setattr(c,'assert_write_path',lambda path,purpose:None)
    candidates=[dict(candidate_id=i,scientific_tuple_sha256=(str(j)*64),risk='diag20_reference',control='none',gross='fixed',action_cost_mode='blind',execution_friction={'one_way_bps':10}) for j,i in enumerate(['RAW','DIAG','CONDITIONAL'],1)]
    write(run/'candidates.json',candidates)
    cfg=dict(phase='FROZEN',strategy_id='SYNTHETIC',run_id='SYNTHETIC',training_cutoff_exclusive='2026-01-01',evaluation_years=[2023,2024,2025],parent_run_dir='SYNTHETIC_PARENT',prior_cumulative_fit_units=455,prior_account_paths=74,outputs={'reports':str(out)},execution_continuation=dict(status='FROZEN',reuse_only=True,candidates_path=str(run/'candidates.json'),candidates_sha256=c.sha(run/'candidates.json'),baseline_candidate_id='RAW',diagnostic_candidate_ids=['RAW','DIAG'],max_new_fit_units=72,max_new_account_paths=80))
    write(run/'run_config.json',cfg)
    return run,out,candidates


def test_continuation_report_requires_all_activated_terminals(tmp_path,monkeypatch):
    run,out,candidates=continuation_fixture(tmp_path,monkeypatch)
    write(run/'ACCOUNT_PATH_LOG.jsonl',dict(event='ACCOUNT_PATH_ATTEMPT_STARTED',candidate_id='RAW',scientific_tuple_sha256='1'*64))
    result=c.build_continuation_report(run)
    assert result['status']=='IN_PROGRESS' and result['finite_execution_complete'] is False
    record=json.loads((out/'TASK_RECORD.json').read_text(encoding='utf-8'))
    assert record['budget']['new_account_attempts']==1 and record['accounts']['RAW']['state']=='IN_PROGRESS'


def test_unqualified_baseline_is_not_economic_no_finalist_and_payload_is_not_decoded(tmp_path,monkeypatch):
    run,out,candidates=continuation_fixture(tmp_path,monkeypatch)
    annual={str(y):dict(sessions=n,accounting_qualified_all=False,certified_nav_positive_and_finite_all=False,net_return_finite_except_initial=False) for y,n in zip([2023,2024,2025],[250,252,250])}
    ap=run/'audit.json';write(ap,dict(status='ACTUAL_CONTINUOUS_PRE2026_REPLAY_COMPLETE',calendar_sessions=752,selection_eligibility={'RAW':annual,'DIAG':annual},certified_nav=987654.321,net_return=987654.321))
    events=[]
    for i in ['RAW','DIAG']:
        st=next(x for x in candidates if x['candidate_id']==i)['scientific_tuple_sha256']
        events.extend([dict(event='ACCOUNT_PATH_ATTEMPT_STARTED',candidate_id=i,scientific_tuple_sha256=st),dict(event='ACCOUNT_PATH_COMPLETE',candidate_id=i,scientific_tuple_sha256=st,audit_path=str(ap),audit_sha256=c.sha(ap))])
    (run/'ACCOUNT_PATH_LOG.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events),encoding='utf-8')
    old=c.json.loads
    def guarded(token,*args,**kwargs):
        assert '987654' not in token
        return old(token,*args,**kwargs)
    monkeypatch.setattr(c.json,'loads',guarded)
    result=c.build_continuation_report(run)
    assert result['status']=='NOT_TESTABLE' and result['finite_execution_complete'] is True
    record=json.loads((out/'TASK_RECORD.json').read_text(encoding='utf-8'))
    assert record['economic_NO_FINALIST_inferred'] is False and record['selection_performed'] is False
    assert record['budget']['new_account_attempts']==2 and record['budget']['new_fit_units']==0
    assert record['accounts']['CONDITIONAL']['reason']=='NOT_EXECUTED_REQUIRED_BASELINE_UNQUALIFIED'
