"""Synthetic-only acceptance for the one-event finite CA adapter.

No real admission, source capsule, ledger, provider, model or account is read.
The frozen driver is imported as code only; all artifacts live under tmp_path.
"""
from copy import deepcopy
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pandas as pd
import pytest

MODULE_PATH = Path(__file__).with_name('consensus_paper_ca_continuation.py')
if MODULE_PATH.is_file():
    spec = importlib.util.spec_from_file_location('_synthetic_finite_ca_adapter', MODULE_PATH)
    finite = importlib.util.module_from_spec(spec); sys.modules[spec.name] = finite; spec.loader.exec_module(finite)
else:
    from scripts.research.a2.evaluation import consensus_paper_ca_continuation as finite
from scripts.research.a2.evaluation import consensus_paper_performance as old
_ORIGINAL_CASH_RUNTIME = finite._cash_runtime


def artifact(tmp_path, name, value):
    path = tmp_path/name; path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding='utf8')
    return old.reference(path)


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    monkeypatch.setattr(finite, '_cash_runtime', lambda: {'synthetic_runtime': True})
    refs = {key:artifact(tmp_path,key+'.json',{'synthetic_source':key}) for key in (
        'issuer_cash','security_identity','nasdaq_applicability','finra_rule','vendor_event','prior_raw_close')}
    dates = ['2026-10-13','2026-10-14','2026-10-15']; calendar_ref = artifact(tmp_path,'calendar.json',{'sessions':dates})
    facts = dict(ticker='MU',listing_identity='NASDAQ:MU',security_id='SYNTHETIC_MU_COMMON',identity_unique=True,
        issuer_jurisdiction='US',security_type='COMMON_STOCK',currency='USD',amount_unit='USD_PER_RAW_OLD_SHARE',
        quantity_coordinate='RAW_OLD_SECURITY_SHARES',record_date='2026-10-14',pay_date='2026-10-29',
        publication_calendar_date='2026-09-30',pay_date_status='SOURCE_FIXED_ANNOUNCED_SCHEDULE',cash_per_raw_share=.1,
        clock_role='POST_VERIFIED_ACCOUNTING_ONLY',available_at=None,ordinary_cash_confirmed=True,noncash_flags_absent=True,
        special_or_due_bill_indicator=False,late_notice_indicator=False,vendor_exact_row_count=1,vendor_ex_field='ex_div_date',
        vendor_named_ex_date='2026-10-14',issuer_history_ex_dates=[],
        issuer_source_fingerprint=refs['issuer_cash']['sha256'],identity_source_fingerprint=refs['security_identity']['sha256'],
        vendor_source_fingerprint=refs['vendor_event']['sha256'],
        prior_raw_close=dict(ticker='MU',security_id='SYNTHETIC_MU_COMMON',trade_date='2026-10-13',price_coordinate='RAW_CLOSE',
            quantity_coordinate='RAW_OLD_SECURITY_SHARES',raw_close=100.,source_fingerprint=refs['prior_raw_close']['sha256']))
    cash = finite._cash()
    capsule = dict(schema=finite.FACT_SCHEMA,facts=facts,source_refs=refs,calendar=dates,
        calendar_binding=dict(status='SOURCE_BOUND_LEGAL_SESSION_CALENDAR',session_dates_sha256=cash._hash(dates),
            source_reference=calendar_ref['path'],source_fingerprint=calendar_ref['sha256']),
        rule_sources=dict(TPLUS1=dict(kind='FINRA_24_04_NORMAL_SMALL_CASH',effective_from='2024-05-28',
            effective_until_exclusive=None,source_reference=refs['finra_rule']['path'],source_fingerprint=refs['finra_rule']['sha256'])),
        nasdaq_applicability=dict(listing_identity='NASDAQ:MU',source_ref=refs['nasdaq_applicability'],
            effective_from='2024-05-28',normal_cash_ex_equals_record=True),
        capture_event_binding=dict(ticker='MU',event_date='2026-10-14',audit_kind='SYNTHETIC_CASH',share_event=False,row_count=1))
    facts_ref = artifact(tmp_path,'facts.json',capsule)
    publication = artifact(tmp_path,'publication.json',{'synthetic':'publication'})
    capture = artifact(tmp_path,'capture.json',{'synthetic':'capture'})
    report = artifact(tmp_path,'report.json',{'synthetic':'report'})
    decision = artifact(tmp_path,'decision.json',{'synthetic':'human-decision'})
    monkeypatch.setattr(finite,'DECISION_SHA',decision['sha256'])
    completions = {sid:artifact(tmp_path,'completion-'+str(i)+'.json',{'synthetic':'old prefix'}) for i,sid in enumerate(old.IDS)}
    prefix = artifact(tmp_path,'prefix.json',dict(schema='CONSENSUS_FIXED_MAIN_PAPER_EXTENSION_MANIFEST_R1',
        status='PREFIX_VERIFIED_DESCRIPTIVE_EXTENSION',end='2026-10-13',candidate_ids=list(old.IDS),
        extensions=completions,model_fit_calls=0,broker_action_allowed=False))
    body = dict(schema=finite.SCHEMA,scope=deepcopy(finite.SCOPE),
        authorization=dict(decision_ref=decision,user_message_id=finite.USER_MESSAGE,card_id=finite.CARD),
        frozen_driver_ref=old.reference(old.__file__),publication_ref=publication,capture_ref=capture,daily_report_ref=report,
        accepted_prefix_manifest_ref=prefix,facts_ref=facts_ref)
    admission_ref = artifact(tmp_path,'admission.json',body)
    monkeypatch.setattr(finite,'ADMISSION_SHA',admission_ref['sha256'])
    monkeypatch.setattr(finite,'FACTS_SHA',facts_ref['sha256'])
    preflight = dict(end='2026-10-15',publication_ref=publication,capture_ref=capture,document={'synthetic':True},
        calendar_qualification=dict(main_sessions=dates))
    monkeypatch.setattr(old,'_current_quote_source',lambda *a,**k:dict(report_ref=report))
    return SimpleNamespace(tmp=tmp_path,capsule=capsule,body=body,admission_ref=admission_ref,preflight=preflight,
        facts_ref=facts_ref,as_of='2026-10-16T12:00:00+00:00')


def test_frozen_driver_and_default_source_rejection_remain_unchanged():
    assert old.reference(old.__file__)['sha256']==finite.DRIVER_SHA
    source=Path(old.__file__).read_text(encoding='utf8')
    assert 'need(not ca["typed_event_terms_required"]' in source and 'need(events.empty,' in source
    assert 'current_in_scope_ca_event_count=0' in source


def test_explicit_finite_nasdaq_projection_preserves_unknown_clock(synthetic):
    s=synthetic
    result=finite.adjudicate_finite_nasdaq_cash(s.capsule,s.facts_ref)
    assert result['status']=='ADJUDICATED_RESEARCH_EX_DATE' and result['finite_source_scope']==finite.SOURCE_SCOPE
    assert result['available_at'] is None and result['strict_PIT_promotion_eligible'] is False
    assert result['production_qualified'] is False and result['broker_payment_proven'] is False
    original=finite._cash().adjudicate_post_verified_cash_ex
    env=dict(payload=s.capsule['facts'],path=s.facts_ref['path'],sha256=s.facts_ref['sha256'],guard=dict(
        status='HASH_VERIFIED_PAYLOAD',path=s.facts_ref['path'],sha256=s.facts_ref['sha256'],payload_sha256=finite._cash()._hash(s.capsule['facts'])))
    rejected=original(env,calendar=s.capsule['calendar'],calendar_binding=s.capsule['calendar_binding'],
        rule_sources=s.capsule['rule_sources'],scope_end_exclusive='2027-01-01')
    assert rejected['status']=='BLOCKED_SOURCE' and rejected['reason']=='NORMAL_CASH_IDENTITY_CURRENCY_OR_RAW_UNIT_UNBOUND'


@pytest.mark.parametrize('field,value', [('ticker','OTHER'),('listing_identity','NYSE:MU'),('available_at','2026-09-30T00:00:00Z'),
    ('special_or_due_bill_indicator',True),('noncash_flags_absent',False),('currency','CAD'),('amount_unit','ADJUSTED_SHARES'),
    ('vendor_named_ex_date','2026-10-13'),('cash_per_raw_share',25.)])
def test_finite_source_rejects_wrong_scope_or_original_cash_guard(synthetic,field,value):
    s=synthetic; changed=deepcopy(s.capsule);changed['facts'][field]=value
    with pytest.raises(ValueError): finite.adjudicate_finite_nasdaq_cash(changed,s.facts_ref)


def test_source_qualification_has_no_model_replay_or_provider_calls(synthetic,monkeypatch):
    s=synthetic
    for name in ('_original_authority','qualified_inputs','forward_r7','forward_r10','execute_prepared'):
        monkeypatch.setattr(old,name,lambda *a,**k:pytest.fail('model/replay called'))
    result=finite.qualify_admission(SimpleNamespace(),s.admission_ref,as_of=s.as_of,preflight=s.preflight)
    assert result['admitted_event_terms']=={'US.MU':['2026-10-14']}
    assert result['models_loaded']==result['model_fit_calls']==result['account_replays']==0
    assert result['broker_action_allowed'] is False


def test_current_publication_and_report_drift_fail_closed(synthetic,monkeypatch):
    s=synthetic; changed=deepcopy(s.preflight);changed['publication_ref']=s.body['capture_ref']
    with pytest.raises(ValueError,match='CURRENT_INPUT_BINDING'): finite.qualify_admission(None,s.admission_ref,as_of=s.as_of,preflight=changed)
    monkeypatch.setattr(old,'_current_quote_source',lambda *a,**k:dict(report_ref=s.body['capture_ref']))
    with pytest.raises(ValueError,match='CURRENT_REPORT'): finite.qualify_admission(None,s.admission_ref,as_of=s.as_of,preflight=s.preflight)


def test_wrong_authorization_scope_and_frozen_identity_fail_before_source(synthetic):
    s=synthetic
    for path,value in [('scope',dict(finite.SCOPE,target_session='2026-10-16')),
        ('authorization',dict(s.body['authorization'],card_id='different-card')),
        ('frozen_driver_ref',dict(s.body['frozen_driver_ref'],sha256='0'*64))]:
        body=deepcopy(s.body);body[path]=value;ref=artifact(s.tmp,path+'.json',body)
        with pytest.raises(ValueError):finite._static(ref,s.as_of)


def test_raw_projection_only_admits_the_exact_typed_and_capture_set(synthetic):
    s=synthetic; before=Path(old.__file__).read_bytes(); projected=finite._raw_projection(s.admission_ref,s.capsule)
    terms=projected.__globals__['_finite_terms_gate']; capture=projected.__globals__['_finite_capture_gate']
    terms(dict(typed_event_terms_required={'US.MU':['2026-10-14']},missing_codes=[],finite_ca_admission_ref=s.admission_ref))
    with pytest.raises(ValueError):terms(dict(typed_event_terms_required={'US.MU':['2026-10-14'],'US.OTHER':['2026-10-14']},
        missing_codes=[],finite_ca_admission_ref=s.admission_ref))
    good=pd.DataFrame([dict(ticker='MU',event_date=pd.Timestamp('2026-10-14'),audit_kind='SYNTHETIC_CASH',share_event=False)])
    capture(good)
    with pytest.raises(ValueError):capture(pd.concat([good,good],ignore_index=True))
    with pytest.raises(ValueError):capture(good.assign(share_event=True))
    assert projected.__code__.co_consts.count(1)>=1 and Path(old.__file__).read_bytes()==before


def test_finite_authority_never_reuses_old_event_admission(synthetic,monkeypatch):
    s=synthetic; event=finite._event(s.body,s.capsule)
    base=old.PaperAuthority(None,None,None,old.IDS,'[]','{}','{}','{}',None,seal=old._SEAL)
    value=finite.FiniteCAAuthority(base,s.admission_ref,event,finite._SEAL); seen=[]
    monkeypatch.setattr(old,'validate_reconstructed_accounting_events',lambda value,events,require_exact=False:seen.append(tuple(events)))
    assert finite.validate_reconstructed_accounting_events(value,[event],require_exact=True) is value and seen==[()]
    with pytest.raises(ValueError,match='EXACT_NEW_EVENT'):finite.validate_reconstructed_accounting_events(value,[],require_exact=True)
    with pytest.raises(ValueError,match='AUTHORITY_REQUIRED'):finite.validate_reconstructed_accounting_events(base,[event])
    with pytest.raises(ValueError,match='FINITE_AUTHORITY_REQUIRED'):old._authority(value)


def test_original_guard_projection_binds_finite_guard_without_changing_account_ast():
    def candidate(authority,day):
        from scripts.research.a2.evaluation.frozen_test_authority import require_descriptive_decision
        return require_descriptive_decision(authority,day)
    projected,proof=finite._guard_projection(candidate)
    assert proof['algorithm_ast_unchanged'] is True and proof['guard_imports_rebound']==1
    assert finite.__name__ in projected.__code__.co_names


def test_bounded_json_rejects_duplicate_keys_and_changed_bytes(tmp_path):
    path=tmp_path/'duplicate.json';path.write_text('{"x":1,"x":2}',encoding='utf8')
    with pytest.raises(ValueError,match='DUPLICATE_KEY'):finite._read(old.reference(path))
    path.write_text('{}',encoding='utf8');ref=old.reference(path);path.write_text('{"changed":true}',encoding='utf8')
    with pytest.raises(ValueError):finite._read(ref)


@pytest.mark.parametrize('field,value',[('cash_per_raw_share',.2),('pay_date','2026-10-30'),('record_date','2026-10-15')])
def test_rehashed_changed_facts_cannot_reuse_approved_card(synthetic,field,value):
    s=synthetic; changed=deepcopy(s.capsule);changed['facts'][field]=value
    changed_ref=artifact(s.tmp,'changed-facts-'+field+'.json',changed)
    body=deepcopy(s.body);body['facts_ref']=changed_ref
    rebuilt=artifact(s.tmp,'rebuilt-'+field+'.json',body)
    with pytest.raises(ValueError,match='EXACT_ADMISSION_COMMITMENT'):finite._static(rebuilt,s.as_of)


def prefix_case(tmp_path, end="2026-10-13", next_session="2026-10-14"):
    fixture_path=Path(old.__file__).parents[4]/'tests/research/a2/evaluation/test_consensus_paper_performance.py'
    fixture_spec=importlib.util.spec_from_file_location('_original_finite_prefix_fixture',fixture_path)
    fixture_module=importlib.util.module_from_spec(fixture_spec);fixture_spec.loader.exec_module(fixture_module)
    paths,frames,_,_=fixture_module.fixtures(tmp_path/'fixture')
    sid=old.IDS[0];end=pd.Timestamp(end);refs={}
    for name,frame in list(frames.items()):
        clock,_=old.LEDGER_TABLES[name]
        row=frame.iloc[[-1]].copy();row.loc[:,clock]=end
        if name=='actions':row.loc[:,'planned_execution_date']=pd.NaT
        if name=='orders':row.loc[:,'execution_date']=pd.NaT;row.loc[:,'status']='no_next_session'
        before=pd.concat([frame,row],ignore_index=True).sort_values(old.LEDGER_TABLES[name][1],kind='stable').reset_index(drop=True)
        file=paths.backtest_root/'prefix13'/f'{name}.parquet';file.parent.mkdir(parents=True,exist_ok=True);before.to_parquet(file,index=False)
        refs[name]=old.reference(file);actual=before.copy()
        if name=='actions':actual.loc[actual.signal_date.eq(end),'planned_execution_date']=pd.Timestamp(next_session)
        elif name=='orders':
            actual.loc[actual.signal_date.eq(end),'execution_date']=pd.Timestamp(next_session)
            actual.loc[actual.signal_date.eq(end),'status']='submitted'
        frames[name]=actual
    completion=artifact(tmp_path,'prefix-completion.json',dict(candidate_ids=[sid],end=str(end.date()),artifacts=refs))
    prefix=artifact(tmp_path,'prefix-manifest.json',dict(end=str(end.date()),extensions={sid:completion}))
    return paths,frames,dict(accepted_prefix_manifest_ref=prefix),sid


def test_six_table_prefix13_uses_only_original_pending_maturity(tmp_path):
    paths,frames,body,sid=prefix_case(tmp_path)
    admission=artifact(tmp_path,'synthetic-admission.json',{'synthetic':True})
    ref=finite._prefix_receipt(paths,sid,frames,admission,body)
    proof=finite._read(ref)
    assert proof['core_tables']['status']=='EXACT_MATCH'
    assert set(proof['core_tables']['table_comparisons'])==set(old.TABLES)
    for name,value in proof['stock_tables']['table_comparisons'].items():
        maturity=value['pending_maturity']
        assert maturity['changed_rows']==1 and maturity['signal_date']=='2026-10-13'
        assert maturity['next_execution_date']=='2026-10-14'
        assert maturity['allowed_columns']==(['planned_execution_date'] if name=='actions' else ['execution_date','status'])


@pytest.mark.parametrize('name,field',[('daily','cash'),('positions','weight'),('fills','price'),
    ('entitlements','amount_usd'),('actions','target_weight'),('orders','target_weight')])
def test_one_changed_prefix_cell_in_any_table_blocks_publication(tmp_path,name,field):
    paths,frames,body,sid=prefix_case(tmp_path)
    admission=artifact(tmp_path,'synthetic-admission.json',{'synthetic':True})
    frames[name].loc[0,field]+=1
    with pytest.raises(ValueError,match='PREFIX'):finite._prefix_receipt(paths,sid,frames,admission,body)


def test_historical_readonly_validation_never_uses_current_source(synthetic,monkeypatch):
    s=synthetic;body=deepcopy(s.body);prefix=json.loads(Path(body['accepted_prefix_manifest_ref']['path']).read_text(encoding='utf8'))
    completions={};receipts={};adapter=old.reference(finite.__file__)
    for i,sid in enumerate(old.IDS):
        artifacts={name:artifact(s.tmp,f'baseline-{i}-{name}.json',{'synthetic':'ledger'}) for name in old.LEDGER_TABLES}
        completion=artifact(s.tmp,f'accepted-completion-{i}.json',{'artifacts':artifacts})
        completions[sid]=completion
        core=dict(status='EXACT_MATCH',table_comparisons={name:dict(status='EXACT_MATCH',original_ref=artifacts[name]) for name in old.TABLES})
        stock=dict(status='EXACT_CLOSED_PREFIX_WITH_PENDING_MATURITY',table_comparisons={name:dict(
            status='EXACT_CLOSED_PREFIX_WITH_PENDING_MATURITY',unchanged_columns_status='EXACT_MATCH',original_ref=artifacts[name],
            pending_maturity=dict(signal_date='2026-10-13',next_execution_date='2026-10-14',changed_rows=0,
                allowed_columns=['planned_execution_date'] if name=='actions' else ['execution_date','status'])) for name in old.STOCK_TABLES})
        receipts[sid]=dict(source_refs=dict(current_publication=body['publication_ref'],finite_ca_adapter_ref=adapter))
        receipts[sid]['synthetic_proof']=(core,stock,completion)
    prefix['extensions']=completions
    body['accepted_prefix_manifest_ref']=artifact(s.tmp,'accepted-manifest.json',prefix)
    admission=artifact(s.tmp,'historical-admission.json',body);monkeypatch.setattr(finite,'ADMISSION_SHA',admission['sha256'])
    for sid,receipt in receipts.items():
        core,stock,completion=receipt.pop('synthetic_proof')
        proof=dict(schema=finite.PREFIX_SCHEMA,status='EXACT_ACCEPTED_PREFIX_WITH_ORIGINAL_PENDING_MATURITY',candidate_id=sid,
            end='2026-10-13',finite_ca_admission_ref=admission,accepted_prefix_manifest_ref=body['accepted_prefix_manifest_ref'],
            accepted_completion_ref=completion,core_tables=core,stock_tables=stock,adapter_ref=adapter)
        receipt['source_refs'].update(finite_ca_admission_ref=admission,
            accepted_extension_prefix_comparison_ref=artifact(s.tmp,'proof-'+sid+'.json',proof))
    monkeypatch.setattr(old,'_current_quote_source',lambda *a,**k:pytest.fail('historical reader consulted live source'))
    result=finite.validate_published_continuation(None,manifest_ref=None,
        manifest=dict(end='2026-10-15',as_of=s.as_of),completion_receipts=receipts)
    assert result['status']=='FINITE_CA_PUBLISHED_CONTINUATION_VERIFIED'
    changed=deepcopy(receipts);changed[old.IDS[0]]['source_refs']['finite_ca_admission_ref']=s.admission_ref
    with pytest.raises(ValueError,match='ADMISSION_MISMATCH'):
        finite.validate_published_continuation(None,manifest_ref=None,manifest=dict(end='2026-10-15',as_of=s.as_of),completion_receipts=changed)


def test_runloop_reuses_original_dispatch_with_runtime_custody_argument(synthetic,monkeypatch):
    s=synthetic;marker=object();seen=[];base=old.PaperAuthority(None,None,None,old.IDS,'[]','{}','{}',
        json.dumps({'source_refs':{}}),None,seal=old._SEAL)
    preflight=dict(s.preflight,originals={},baselines={})
    monkeypatch.setattr(finite,'metadata_preflight',lambda *a,**k:preflight)
    def prepare(paths,sid,pf,qualified,runtime_custody_ref=None):
        assert runtime_custody_ref is marker;seen.append('original_prepare')
        return dict(sid_by_key={(pd.Timestamp(day),'MU'):'SYNTHETIC_MU_COMMON' for day in ('2026-10-13','2026-10-14')},
            source_refs={},authority=base,account_source_kwargs=dict(entitlement_events=(),entitlement_security_tickers={},
                entitlement_source_binding=dict(manifest={},event_fingerprints=[],security_tickers={}))),pd.DataFrame()
    monkeypatch.setattr(old,'_prepare_candidate',prepare)
    def driver(paths,*,capture_ref,as_of,execute,auto,ca_receipt_refs):
        prepared,flags=_prepare_candidate(paths,old.IDS[0],preflight,{},marker)
        assert type(prepared['authority']) is finite.FiniteCAAuthority
        assert prepared['account_source_kwargs']['entitlement_events'][0].event_fingerprint==prepared['authority'].event.event_fingerprint
        assert prepared['source_refs']['finite_ca_admission_ref']==s.admission_ref
        assert prepared['account_source_kwargs']['entitlement_security_tickers']=={'SYNTHETIC_MU_COMMON':'MU'}
        return dict(status='SYNTHETIC_DISPATCH_ONLY',model_fit_calls=0)
    monkeypatch.setattr(old,'run_qualified_main',driver)
    result=finite.run_qualified_main(None,finite_ca_admission_ref=s.admission_ref,capture_ref=s.body['capture_ref'],
        as_of=s.as_of,execute=True,auto=False)
    assert result['status']=='SYNTHETIC_DISPATCH_ONLY' and seen==['original_prepare']


def test_original_entitlement_lifecycle_receivable_payment_and_sold_claim(synthetic,monkeypatch):
    from dataclasses import replace
    from scripts.v22.corporate_action_transition_r1 import apply_entitlement_lifecycle
    s=synthetic;event=replace(finite._event(s.body,s.capsule),pay_date='2026-10-15')
    base=old.PaperAuthority(pd.Timestamp('2026-01-02'),pd.Timestamp('2026-10-15'),pd.Timestamp(s.as_of),
        (old.IDS[0],),'[]','{}','{}','{}',None,seal=old._SEAL)
    value=finite.FiniteCAAuthority(base,s.admission_ref,event,finite._SEAL)
    monkeypatch.setattr(old,'validate_reconstructed_accounting_events',lambda *a,**k:base)
    lifecycle,proof=finite._guard_projection(apply_entitlement_lifecycle)
    kwargs=dict(security_tickers={'SYNTHETIC_MU_COMMON':'MU'},quantity_coordinate='RAW_OLD_SECURITY_SHARES',
        enabled=True,descriptive_accounting_authority=value)
    first=lifecycle([event],{'SYNTHETIC_MU_COMMON':10.},100.,execution_date='2026-10-14',
        session_open_at='2026-10-14T13:30:00Z',**kwargs)
    assert first.cash==100. and first.receivable_value_usd==1.
    paid=lifecycle([event],{},first.cash,execution_date='2026-10-15',session_open_at='2026-10-15T13:30:00Z',state=first.state,**kwargs)
    assert paid.cash==101. and paid.receivable_value_usd==0.
    with pytest.raises(ValueError,match='SESSION_ALREADY_APPLIED_OR_REVERSED'):
        lifecycle([event],{},paid.cash,execution_date='2026-10-15',session_open_at='2026-10-15T13:30:00Z',state=paid.state,**kwargs)
    assert paid.cash==101. and paid.receivable_value_usd==0.
    assert proof['algorithm_ast_unchanged'] is True


def test_auto_nonexecute_reads_actual_original_current_manifest_without_replay(synthetic,monkeypatch):
    s=synthetic
    test_historical_readonly_validation_never_uses_current_source(s,monkeypatch)
    admission=old.reference(s.tmp/'historical-admission.json');body=json.loads(Path(admission['path']).read_text(encoding='utf8'))
    prefix=json.loads(Path(body['accepted_prefix_manifest_ref']['path']).read_text(encoding='utf8'))
    dates=[old.START,old.FIRST_EXECUTION,old.PREFIX_END,'2026-10-13','2026-10-14','2026-10-15']
    cal_ref=artifact(s.tmp,'auto-calendar.json',{'synthetic':'calendar'})
    calendar=dict(helper=old.CALENDAR_HELPER,target_session='2026-10-15',latest_completed_us_session='2026-10-15',
        target_session_completed=True,session_close_utc='2026-10-15T20:00:00+00:00',main_sessions=dates,
        tail_sessions=[day for day in dates if day>old.PREFIX_END],calendar_ref=cal_ref,helper_ref=cal_ref,
        provider_ref=cal_ref,production_binding_ref=cal_ref)
    completions={};baselines={}
    for i,sid in enumerate(old.IDS):
        base=json.loads(Path(prefix['extensions'][sid]['path']).read_text(encoding='utf8'))['artifacts'];baselines[sid]=base
        refs=dict(current_publication=body['publication_ref'],finite_ca_admission_ref=admission,
            finite_ca_adapter_ref=old.reference(finite.__file__),
            accepted_extension_prefix_comparison_ref=old.reference(s.tmp/('proof-'+sid+'.json')))
        completions[sid]=artifact(s.tmp,f'published-completion-{i}.json',dict(schema=old.SCHEMA,candidate_ids=[sid],end='2026-10-15',
            source_refs=refs,artifacts=base,baseline_artifacts=base,original_prefix_comparison=dict(status='EXACT_MATCH'),
            stock_prefix_comparison=dict(status='EXACT_CLOSED_PREFIX_WITH_PENDING_MATURITY')))
    manifest=dict(schema='CONSENSUS_FIXED_MAIN_PAPER_EXTENSION_MANIFEST_R1',status='PREFIX_VERIFIED_DESCRIPTIVE_EXTENSION',
        candidate_ids=list(old.IDS),window_id='MAIN',start=old.START,first_execution_date=old.FIRST_EXECUTION,prefix_end=old.PREFIX_END,
        end='2026-10-15',as_of=s.as_of,calendar_qualification=calendar,model_fit_calls=0,selection_using_2026=False,
        independent_holdout_claim=False,broker_action_allowed=False,extensions=completions)
    manifest_ref=artifact(s.tmp,'published-manifest.json',manifest)
    paths=SimpleNamespace(daily_root=s.tmp/'daily');folder=paths.daily_root/'A2_consensus_paper';folder.mkdir(parents=True)
    (folder/'MAIN_extension_latest.json').write_text(json.dumps(manifest_ref),encoding='utf8')
    (folder/'latest.json').write_text(json.dumps(body['publication_ref']),encoding='utf8')
    monkeypatch.setattr(old,'accepted_baseline_refs',lambda sid:baselines[sid])
    monkeypatch.setattr(old,'completed_calendar',lambda *a:calendar)
    monkeypatch.setattr(finite,'metadata_preflight',lambda *a,**k:pytest.fail('same-date current entered full metadata'))
    monkeypatch.setattr(old,'metadata_preflight',lambda *a,**k:pytest.fail('same-date current entered original metadata'))
    monkeypatch.setattr(old,'run_qualified_main',lambda *a,**k:pytest.fail('same-date current entered replay driver'))
    result=finite.run_qualified_main(paths,finite_ca_admission_ref=admission,as_of=s.as_of,auto=True,execute=False)
    assert result['status']=='ALREADY_CURRENT_PREFIX_VERIFIED' and result['finite_ca_admission_ref']==admission
    assert result['models_loaded']==result['model_fit_calls']==result['ledger_values_decoded']==0


def test_real_execute_dispatch_rebinds_r7_overlay_callback_guard(synthetic,monkeypatch):
    from types import ModuleType
    s=synthetic;sid=old.IDS[2];event=finite._event(s.body,s.capsule);dates=pd.DatetimeIndex(['2026-01-02','2026-10-15'])
    candidate=dict(candidate_id=sid);account={};friction={}
    base=old.PaperAuthority(dates[0],dates[-1],pd.Timestamp(s.as_of),(sid,),old.canonical([candidate]),'{}','{}','{}',None,seal=old._SEAL)
    value=finite.FiniteCAAuthority(base,s.admission_ref,event,finite._SEAL)
    class Overlay:
        def __init__(self,actual,*args,descriptive_evaluation_authority=None,**kwargs):self.authority=descriptive_evaluation_authority
        def __call__(self,date):
            from scripts.research.a2.evaluation.frozen_test_authority import require_descriptive_decision
            return require_descriptive_decision(self.authority,date)
    def execute_market(*args,policy_factory,**kwargs):
        policy=policy_factory(object(),descriptive_evaluation_authority=kwargs['descriptive_evaluation_authority'])
        assert policy(pd.Timestamp('2026-10-15')) is value
        return 'synthetic-result',{'synthetic':'frames'}
    methods=dict(execute_market=execute_market,StatefulOverlay=object,FinalActionOverlay=object)
    def replay_projection():return methods,[]
    monkeypatch.setattr(old,'replay_projection',replay_projection)
    monkeypatch.setattr(old,'load_original_owner',lambda *a:SimpleNamespace(R7GrossOverlay=Overlay))
    monkeypatch.setattr(old,'_original_nav_output_frames',lambda result,frames,ids:frames)
    packets=ModuleType('scripts.research.a2.training.stateful_final_action_packets');packets.decode_resource_proposals=lambda *a:None
    monkeypatch.setitem(sys.modules,packets.__name__,packets)
    prepared=dict(candidates=[candidate],account=account,execution_friction=friction,market=SimpleNamespace(dates=dates),
        account_source_kwargs=dict(entitlement_enabled=True,entitlement_source_binding={}),sid_by_key={},packets={},top={},
        qualified={},vol={},stock_present={},raw_selector_present={})
    result,frames,proofs=finite._execution_projection()(prepared,value,gross_calendar={sid:{}})
    assert result=='synthetic-result' and frames=={'synthetic':'frames'}
    assert len(proofs)==2 and all(proof['algorithm_ast_unchanged'] for proof in proofs)


def test_source_drift_before_locked_qualification_never_reaches_original_source(synthetic,monkeypatch):
    s=synthetic;preflight=dict(s.preflight,originals={},baselines={})
    monkeypatch.setattr(finite,'metadata_preflight',lambda *a,**k:preflight)
    def forbidden(*a,**k):pytest.fail('unbound original source executed')
    monkeypatch.setattr(old,'qualified_inputs',forbidden)
    def driver(paths,*,capture_ref,as_of,execute,auto,ca_receipt_refs):
        monkeypatch.setattr(old,'_current_quote_source',lambda *a,**k:dict(report_ref=s.body['capture_ref']))
        return qualified_inputs(paths,preflight,ca_receipt_refs=ca_receipt_refs)
    monkeypatch.setattr(old,'run_qualified_main',driver)
    with pytest.raises(ValueError,match='CURRENT_REPORT_CHANGED'):
        finite.run_qualified_main(None,finite_ca_admission_ref=s.admission_ref,capture_ref=s.body['capture_ref'],
            as_of=s.as_of,execute=True,auto=False)


@pytest.mark.parametrize('execute',[False,True])
def test_original_run_owns_one_preflight_and_keeps_locked_readmission(synthetic,monkeypatch,execute):
    from contextlib import contextmanager
    from scripts.common import daily_support
    s=synthetic;paths=SimpleNamespace(daily_root=s.tmp/'daily');calls=[];locked=False
    preflight=dict(s.preflight,status='METADATA_PREFLIGHT_READY_NOT_SOURCE_OR_REPLAY_QUALIFICATION',
        originals={sid:{'synthetic':sid} for sid in old.IDS},baselines={})
    def metadata(paths,*,capture_ref,as_of):
        assert not locked and capture_ref==s.body['capture_ref'];calls.append('metadata')
        return preflight
    def admission(paths,ref,*,as_of,preflight=None):
        assert ref==s.admission_ref and preflight is expected_preflight
        calls.append('admit_locked' if locked else 'admit_outside')
        return dict(admitted_event_terms={'US.MU':['2026-10-14']})
    expected_preflight=preflight
    @contextmanager
    def lock(root):
        nonlocal locked
        assert root==paths.daily_root/'A2_today_recommendation' and not locked
        locked=True;calls.append('lock')
        try:yield
        finally:locked=False;calls.append('unlock')
    @contextmanager
    def custody(meta):yield None
    def source(paths,current_preflight,*,ca_receipt_refs=()):
        assert locked and current_preflight is preflight and ca_receipt_refs==()
        assert calls[-1]=='admit_locked';calls.append('source')
        return {}
    class StopBeforeModel(Exception):pass
    def prepare(*args,**kwargs):
        assert locked and args[2] is preflight;calls.append('prepare')
        raise StopBeforeModel()
    monkeypatch.setattr(old,'metadata_preflight',metadata)
    monkeypatch.setattr(finite,'qualify_admission',admission)
    monkeypatch.setattr(daily_support,'single_update',lock)
    monkeypatch.setattr(old,'original_runtime_custody',custody)
    monkeypatch.setattr(old,'qualified_inputs',source)
    monkeypatch.setattr(old,'_prepare_candidate',prepare)
    monkeypatch.setattr(old,'check_resources',lambda *a,**k:calls.append('resource'))
    for name in ('forward_r7','forward_r10','execute_prepared','publish_verified','publish_manifest'):
        monkeypatch.setattr(old,name,lambda *a,**k:pytest.fail('model/account/publication reached'))
    kwargs=dict(finite_ca_admission_ref=s.admission_ref,capture_ref=s.body['capture_ref'],as_of=s.as_of,execute=execute,auto=False)
    if execute:
        with pytest.raises(StopBeforeModel):finite.run_qualified_main(paths,**kwargs)
        assert calls.count('admit_locked')==calls.count('source')==1
        assert calls.index('metadata')<calls.index('admit_outside')<calls.index('lock')<calls.index('admit_locked')<calls.index('source')
        assert not locked and calls[-1]=='unlock'
    else:
        result=finite.run_qualified_main(paths,**kwargs)
        assert result['status']=='METADATA_PREFLIGHT_READY_NOT_SOURCE_OR_REPLAY_QUALIFICATION'
        assert calls==['metadata','admit_outside']
        assert not {'document','originals','baselines'} & set(result)
    assert calls.count('metadata')==calls.count('admit_outside')==1


@pytest.fixture
def original_canonical_guard(tmp_path, monkeypatch):
    """Original canonical checks, isolated synthetic source/proof; no real facts."""
    import scripts.v22 as parent
    guard_path=Path('D:/us-tech-quant-cache/_maintenance/A_ALL_REPAIR_AND_CONSENSUS_SENSITIVITY_20261011_R1/source_compatibility/ca_worktree_source.py')
    assert old.reference(guard_path)['sha256']=='8ae837dd4de365989465210492e4b04eaf1163afcf03dee8d12f962a12b35219'
    guard_name='_finite_synthetic_original_canonical_guard'
    spec=importlib.util.spec_from_file_location(guard_name,guard_path)
    guard=importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules,guard_name,guard);spec.loader.exec_module(guard)
    selected=tmp_path/'selected_ca.py'
    selected.write_text("def canonical_bytes(value): return repr(value).encode()\ndef _entitlement_day(value): return value\nclass ResearchReconstructedCashEvent:\n    def __init__(self, **values):\n        self.__dict__.update(values)\n        self.event_fingerprint = 'SYNTHETIC_EVENT_ONLY'\n",encoding='utf8')
    monkeypatch.setattr(guard,'SELECTED',selected)
    monkeypatch.setattr(guard,'NEW_SHA',old.reference(selected)['sha256'])
    proof={'synthetic_proof':True};calls=[]
    def sealed(ref,context_task_id):
        assert ref==proof and context_task_id=='SYNTHETIC_ORIGINAL_RUNTIME'
        calls.append('source_seal');return {}
    monkeypatch.setattr(guard,'_sealed_pair',sealed)
    previous_ca=sys.modules.get(guard.NAME);leaf=guard.NAME.rsplit('.',1)[1]
    previous_parent=getattr(parent,leaf,None)
    monkeypatch.delitem(sys.modules,guard.NAME,raising=False)
    monkeypatch.delattr(parent,leaf,raising=False)
    bootstrap=tmp_path/'bootstrap.py'
    bootstrap.write_text("import sys\nTASK='SYNTHETIC_ORIGINAL_RUNTIME'\nCA_HELPER_REF={'synthetic_helper': True}\nCA_PROOF_REF={'synthetic_proof': True}\ndef load(ref,name):\n    assert ref == CA_HELPER_REF\n    return sys.modules['"+guard_name+"']\ndef bootstrap(research_id):\n    raise AssertionError('CBC or account bootstrap reached during metadata')\ndef assert_bound(research_id):\n    raise AssertionError('CBC or account validation reached during metadata')\n",encoding='utf8')
    release=artifact(tmp_path,'original-release.json',dict(runtime_bootstrap_ref=old.reference(bootstrap)))
    monkeypatch.setattr(old,'R7_RELEASE',release)
    monkeypatch.setattr(finite,'_cash_runtime',_ORIGINAL_CASH_RUNTIME)
    monkeypatch.setattr(finite,'_owner',lambda:old)
    previous=sys.modules.get('_finite_ca_original_cash_runtime')
    yield SimpleNamespace(guard=guard,proof=proof,calls=calls,parent=parent,selected=selected,release=release)
    if previous is None:sys.modules.pop('_finite_ca_original_cash_runtime',None)
    else:sys.modules['_finite_ca_original_cash_runtime']=previous
    if previous_ca is None:sys.modules.pop(guard.NAME,None)
    else:sys.modules[guard.NAME]=previous_ca
    if previous_parent is None:
        if hasattr(parent,leaf):delattr(parent,leaf)
    else:setattr(parent,leaf,previous_parent)


@pytest.mark.parametrize('entry',['cash','event'])
def test_original_bootstrap_precedes_each_financial_import_and_is_idempotent(original_canonical_guard,monkeypatch,entry):
    s=original_canonical_guard;seen=[]
    import_module=finite.importlib.import_module
    def imported(name,*args,**kwargs):
        if name=='scripts.research.a2.data.joint_cash_bindings':
            pytest.fail('current cash module imported into frozen canonical CA runtime')
        return import_module(name,*args,**kwargs)
    monkeypatch.setattr(finite.importlib,'import_module',imported)
    body={'facts_ref':{'path':'synthetic','sha256':'0'*64}}
    capsule={'facts':dict(security_id='SYNTHETIC_MU',record_date='2026-10-14',pay_date='2026-10-29',cash_per_raw_share=.1),
        'source_refs':{'issuer_cash':{'path':'synthetic','sha256':'1'*64}}}
    if entry=='cash':
        cash=finite._cash()
        assert cash.projection['original_function_ast_unchanged'] and cash.projection['account_class_nodes_loaded']==0
    else:assert finite._event(body,capsule).event_fingerprint=='SYNTHETIC_EVENT_ONLY'
    module=sys.modules[s.guard.NAME]
    assert Path(module.__file__)==s.selected and getattr(s.parent,s.guard.NAME.rsplit('.',1)[1]) is module
    finite._cash_runtime()
    assert sys.modules[s.guard.NAME] is module
    if entry=='cash':assert seen==[]
    assert len(s.calls)>=3


def test_original_bootstrap_rejects_preloaded_wrong_module_without_replacement(original_canonical_guard,monkeypatch):
    from types import ModuleType
    s=original_canonical_guard;wrong=ModuleType(s.guard.NAME);wrong.__file__=str(s.selected.with_name('shared_main.py'))
    monkeypatch.setitem(sys.modules,s.guard.NAME,wrong)
    monkeypatch.setattr(s.parent,s.guard.NAME.rsplit('.',1)[1],wrong,raising=False)
    with pytest.raises(ValueError,match='SELECTED_CANONICAL_MODULE_REQUIRED'):
        finite._cash_runtime()
    assert sys.modules[s.guard.NAME] is wrong and getattr(s.parent,s.guard.NAME.rsplit('.',1)[1]) is wrong


def test_original_bootstrap_rechecks_class_identity_on_reuse(original_canonical_guard):
    s=original_canonical_guard;finite._cash_runtime();module=sys.modules[s.guard.NAME]
    module.ResearchReconstructedCashEvent.__init__=lambda self,**values:None
    with pytest.raises(ValueError,match='SELECTED_CLASS_METHOD_CHANGED'):
        finite._cash_runtime()
    assert sys.modules[s.guard.NAME] is module


def test_metadata_qualification_uses_same_original_bootstrap_before_cash_and_event(synthetic,original_canonical_guard,monkeypatch):
    s=synthetic;guard=original_canonical_guard;seen=[]
    def adjudicate(capsule,facts_ref):
        finite._cash_runtime()
        guard.guard.assert_selected_owner(guard.proof,context_task_id='SYNTHETIC_ORIGINAL_RUNTIME',check_functions=True)
        seen.append('cash_adjudication_after_original_guard');return {'synthetic':True}
    monkeypatch.setattr(finite,'adjudicate_finite_nasdaq_cash',adjudicate)
    result=finite.qualify_admission(None,s.admission_ref,as_of=s.as_of,preflight=s.preflight)
    assert result['status']=='FINITE_CA_ADMISSION_QUALIFIED_NOT_REPLAY' and result['event_fingerprint']=='SYNTHETIC_EVENT_ONLY'
    assert seen==['cash_adjudication_after_original_guard']
    assert result['models_loaded']==result['model_fit_calls']==result['account_replays']==0


@pytest.mark.parametrize('source',['declared_bootstrap','selected_ca'])
def test_original_bootstrap_rejects_source_bytes_drift(original_canonical_guard,source):
    s=original_canonical_guard
    ref=old.projected_metadata(s.release,('runtime_bootstrap_ref',))['runtime_bootstrap_ref']
    path=Path(ref['path']) if source=='declared_bootstrap' else s.selected
    path.write_bytes(path.read_bytes()+b'\n# changed synthetic source\n')
    expected='PAPER_EXTENSION_REFERENCE_CHANGED' if source=='declared_bootstrap' else 'STRICT_SOURCE_SHA_CHANGED'
    with pytest.raises(ValueError,match=expected):finite._cash_runtime()
    assert s.guard.NAME not in sys.modules



def test_actual_joint_source_projection_works_with_original_ca_abi(synthetic,original_canonical_guard,monkeypatch):
    import ast
    import inspect
    s=synthetic;guard=original_canonical_guard
    import_module=finite.importlib.import_module
    def imported(name,*args,**kwargs):
        if name=='scripts.research.a2.data.joint_cash_bindings':pytest.fail('joint cash module was imported')
        return import_module(name,*args,**kwargs)
    monkeypatch.setattr(finite.importlib,'import_module',imported)
    cash=finite._cash();canonical=sys.modules[guard.guard.NAME]
    assert not hasattr(canonical,'validate_closed_record_research_binding')
    assert not hasattr(canonical,'CLOSED_RECORD_RESEARCH_POLICY')
    result=finite.adjudicate_finite_nasdaq_cash(s.capsule,s.facts_ref)
    assert result['status']=='ADJUDICATED_RESEARCH_EX_DATE' and result['ex_date']=='2026-10-14'
    assert sys.modules[guard.guard.NAME] is canonical
    guard.guard.assert_selected_owner(guard.proof,context_task_id='SYNTHETIC_ORIGINAL_RUNTIME',check_functions=True)
    original=ast.parse(Path(cash.__file__).read_bytes())
    funcs={node.name:node for node in original.body if isinstance(node,ast.FunctionDef)}
    namespace=cash.adjudicate_post_verified_cash_ex.__globals__
    assert set(cash.projection['functions'])=={'_hash','_sha','_guard','normal_cash_ex_date','adjudicate_post_verified_cash_ex'}
    for name in cash.projection['functions']:
        projected=ast.parse(inspect.getsource(namespace[name])).body[0]
        assert ast.dump(projected,include_attributes=False)==ast.dump(funcs[name],include_attributes=False)
    assert 'validate_closed_record_research_binding' not in namespace
    assert 'ResearchReconstructedCashEvent' not in namespace
    assert result['cash_dependency_ref']['sha256']==finite.CASH_DEPENDENCY_SHA


@pytest.mark.parametrize('field',['CASH_SHA','CASH_DEPENDENCY_SHA'])
def test_cash_pure_projection_rejects_source_pin_drift(synthetic,monkeypatch,field):
    monkeypatch.setattr(finite,field,'0'*64)
    with pytest.raises(ValueError,match='FINITE_CA_CASH_(OWNER|DEPENDENCY)_CHANGED'):
        finite._cash()


def test_cash_projection_preserves_original_ordinary_exception_gates(synthetic):
    s=synthetic;cash=finite._cash();facts=deepcopy(s.capsule['facts']);facts['listing_identity']='NYSE:MU'
    def adjudicate(facts):
        env=dict(payload=facts,path=s.facts_ref['path'],sha256=s.facts_ref['sha256'],guard=dict(status='HASH_VERIFIED_PAYLOAD',
            path=s.facts_ref['path'],sha256=s.facts_ref['sha256'],payload_sha256=cash._hash(facts)))
        return cash.adjudicate_post_verified_cash_ex(env,calendar=s.capsule['calendar'],calendar_binding=s.capsule['calendar_binding'],
            rule_sources=s.capsule['rule_sources'],scope_end_exclusive='2027-01-01',source_scope='US_2026_SOURCE_ONLY')
    assert adjudicate(facts)['status']=='ADJUDICATED_RESEARCH_EX_DATE'
    for field,reason in [('closed_record_research_binding','CLOSED_RECORD_RESEARCH_SCOPE_AND_CALENDAR_REQUIRED'),
        ('cns_bank_holiday_record_binding','NSCC_CNS_SCOPE_OR_CALENDAR_OR_POLICY_CONFLICT'),
        ('nyse_nonbusiness_record_binding','NYSE_NONBUSINESS_REPORT_SCOPE_AND_CALENDAR_REQUIRED')]:
        changed=deepcopy(facts);changed[field]={}
        result=adjudicate(changed)
        assert result['status']=='BLOCKED_SOURCE' and result['reason']==reason


@pytest.fixture
def target16(synthetic, monkeypatch):
    s = synthetic
    dates = [old.START, old.FIRST_EXECUTION, old.PREFIX_END, '2026-10-13', '2026-10-14', '2026-10-15']
    s.capsule['calendar'] = dates
    s.capsule['calendar_binding']['session_dates_sha256'] = finite._cash()._hash(dates)
    s.facts_ref = artifact(s.tmp, 'target16-old-facts.json', s.capsule)
    s.body['facts_ref'] = s.facts_ref
    monkeypatch.setattr(finite, 'FACTS_SHA', s.facts_ref['sha256'])
    test_historical_readonly_validation_never_uses_current_source(s, monkeypatch)
    previous_ref = old.reference(s.tmp/'historical-admission.json')
    previous = finite._read(previous_ref)
    legacy = s.tmp/'legacy_adapter.py.before'; legacy.write_text('# synthetic accepted source\n', encoding='utf8')
    legacy_ref = old.reference(legacy); monkeypatch.setattr(finite, 'LEGACY_ADAPTER_EVIDENCE', legacy_ref)
    adapter = dict(old.reference(finite.__file__), sha256=legacy_ref['sha256'])
    completions = {}
    for sid in old.IDS:
        proof_path = s.tmp/('proof-'+sid+'.json')
        proof = json.loads(proof_path.read_text(encoding='utf8')); proof['adapter_ref'] = adapter
        proof_ref = artifact(s.tmp, proof_path.name, proof)
        completions[sid] = artifact(s.tmp, 'accepted15-'+sid+'.json', dict(source_refs=dict(
            current_publication=previous['publication_ref'], finite_ca_admission_ref=previous_ref,
            finite_ca_adapter_ref=adapter, accepted_extension_prefix_comparison_ref=proof_ref)))
    accepted = artifact(s.tmp, 'accepted15-manifest.json', dict(schema='CONSENSUS_FIXED_MAIN_PAPER_EXTENSION_MANIFEST_R1',
        status='PREFIX_VERIFIED_DESCRIPTIVE_EXTENSION', candidate_ids=list(old.IDS), extensions=completions,
        end='2026-10-15', as_of=s.as_of, model_fit_calls=0, broker_action_allowed=False))
    s.as_of = '2026-10-17T12:00:00+00:00'
    proposal = artifact(s.tmp, 'target16-proposal.json', {'synthetic':'approved target16'})
    monkeypatch.setattr(finite, 'TARGET16_DECISION_SHA', proposal['sha256'])
    auth = artifact(s.tmp, 'target16-human.json', dict(schema='FINITE_MAIN_TARGET16_HUMAN_DECISION_R1',
        proposal_ref=proposal, question_item_id=finite.TARGET16_QUESTION_ITEM,
        answer='批准，仅续接到10/16（推荐）', user_message_id=None, recorded_at_utc='2026-10-17T10:00:00+00:00'))
    cal_ref = artifact(s.tmp, 'target16-calendar-source.json', {'synthetic':True})
    calendar = dict(helper=old.CALENDAR_HELPER, target_session='2026-10-16', latest_completed_us_session='2026-10-16',
        target_session_completed=True, session_close_utc='2026-10-16T20:00:00+00:00', as_of_utc=s.as_of,
        main_sessions=dates+['2026-10-16'], tail_sessions=[d for d in dates+['2026-10-16'] if d>old.PREFIX_END],
        calendar_ref=cal_ref, helper_ref=cal_ref, provider_ref=cal_ref, production_binding_ref=cal_ref)
    extension = dict(schema='FINITE_MAIN_TARGET16_CALENDAR_EXTENSION_R1', facts_ref=s.facts_ref,
        previous_admission_ref=previous_ref, legacy_calendar_session_count=len(dates), legacy_calendar_end='2026-10-15',
        legacy_calendar_binding=s.capsule['calendar_binding'],
        legacy_session_dates_sha256=finite._cash()._hash(dates), calendar_qualification=calendar)
    extension_ref = artifact(s.tmp, 'target16-calendar.json', extension)
    body = dict(previous, scope=deepcopy(finite.TARGET16_SCOPE), previous_admission_ref=previous_ref,
        original_prefix_manifest_ref=previous['accepted_prefix_manifest_ref'], accepted_prefix_manifest_ref=accepted,
        legacy_adapter_evidence_ref=legacy_ref, calendar_extension_ref=extension_ref,
        authorization=dict(decision_ref=proposal, receipt_ref=auth, question_item_id=finite.TARGET16_QUESTION_ITEM, user_message_id=None))
    for field in ('publication_ref','capture_ref','daily_report_ref'):
        body[field] = artifact(s.tmp, 'target16-'+field+'.json', {'synthetic':field})
    admission = artifact(s.tmp, 'target16-admission.json', body)
    monkeypatch.setattr(finite, 'TARGET16_ADMISSION_SHA', admission['sha256'])
    preflight = dict(end='2026-10-16', document={'synthetic':True}, calendar_qualification=deepcopy(calendar),
        publication_ref=body['publication_ref'], capture_ref=body['capture_ref'])
    monkeypatch.setattr(old, '_current_quote_source', lambda *a,**k: dict(report_ref=body['daily_report_ref']))
    return SimpleNamespace(**vars(s) | dict(body=body, admission_ref=admission, preflight=preflight,
        previous_ref=previous_ref, accepted=accepted, completions=completions, calendar=calendar, extension=extension, legacy=legacy))


def test_target16_qualifies_only_same_fact_and_full_calendar_extension(target16):
    s=target16; before=Path(s.facts_ref['path']).read_bytes()
    proof=finite.qualify_admission(None,s.admission_ref,as_of=s.as_of,preflight=s.preflight)
    assert proof['end']=='2026-10-16' and proof['accepted_prefix_end']=='2026-10-15'
    assert proof['admitted_event_terms']=={'US.MU':['2026-10-14']}
    assert proof['model_fit_calls']==proof['models_loaded']==proof['account_replays']==0
    assert Path(s.facts_ref['path']).read_bytes()==before
    assert proof['source_adjudication']['calendar_binding']==s.capsule['calendar_binding']


def test_old15_is_still_readable_but_cannot_authorize_target16(target16):
    s=target16
    accepted=finite._read(s.accepted)
    receipts={sid:finite._read(ref) for sid,ref in s.completions.items()}
    proof=finite.validate_published_continuation(None,manifest_ref=s.accepted,manifest=accepted,completion_receipts=receipts)
    assert proof['end']=='2026-10-15' and proof['admission_ref']==s.previous_ref
    with pytest.raises(ValueError,match='CURRENT_INPUT_BINDING'):
        finite.qualify_admission(None,s.previous_ref,as_of=s.as_of,preflight=s.preflight)
    s.legacy.write_text('# changed source custody',encoding='utf8')
    with pytest.raises(ValueError):
        finite.validate_published_continuation(None,manifest_ref=s.accepted,manifest=accepted,completion_receipts=receipts)


@pytest.mark.parametrize('change',['old_prefix','extra_day','future_asof','source_ref'])
def test_target16_calendar_drift_cannot_be_rehashed_into_scope(target16,monkeypatch,change):
    s=target16; extension=deepcopy(s.extension)
    if change=='old_prefix': extension['calendar_qualification']['main_sessions'].remove('2026-10-13')
    elif change=='extra_day': extension['calendar_qualification']['main_sessions'].append('2026-10-19')
    elif change=='future_asof': extension['calendar_qualification']['as_of_utc']='2026-10-20T12:00:00+00:00'
    else: extension['facts_ref']['sha256']='0'*64
    changed=deepcopy(s.body);changed['calendar_extension_ref']=artifact(s.tmp,'changed-calendar.json',extension)
    ref=artifact(s.tmp,'changed-admission.json',changed);monkeypatch.setattr(finite,'TARGET16_ADMISSION_SHA',ref['sha256'])
    with pytest.raises(ValueError):finite.qualify_admission(None,ref,as_of=s.as_of,preflight=s.preflight)


@pytest.mark.parametrize('change',['publication_ref','capture_ref','report','scope','authorization','original_prefix'])
def test_target16_source_authorization_and_scope_drift_fail_closed(target16,monkeypatch,change):
    s=target16; preflight=deepcopy(s.preflight); body=deepcopy(s.body); ref=s.admission_ref
    if change in ('publication_ref','capture_ref'):preflight[change]=s.body['daily_report_ref']
    elif change=='report':monkeypatch.setattr(old,'_current_quote_source',lambda *a,**k:dict(report_ref=s.body['capture_ref']))
    else:
        if change=='scope':body['scope']['target_session']='2026-10-19'
        elif change=='authorization':body['authorization']['question_item_id']=['request_user_input_async','wrong',0]
        else:body['original_prefix_manifest_ref']=body['accepted_prefix_manifest_ref']
        ref=artifact(s.tmp,'drift-admission.json',body);monkeypatch.setattr(finite,'TARGET16_ADMISSION_SHA',ref['sha256'])
    with pytest.raises(ValueError):finite.qualify_admission(None,ref,as_of=s.as_of,preflight=preflight)


def test_target16_pending_maturity_is_only_signal15_execution16(tmp_path):
    paths,frames,body,sid=prefix_case(tmp_path,end='2026-10-15',next_session='2026-10-16')
    body['scope']=deepcopy(finite.TARGET16_SCOPE)
    admission=artifact(tmp_path,'synthetic-target16.json',{'synthetic':True})
    proof=finite._read(finite._prefix_receipt(paths,sid,frames,admission,body))
    assert proof['end']=='2026-10-15'
    for row in proof['stock_tables']['table_comparisons'].values():
        assert row['pending_maturity']['signal_date']=='2026-10-15'
        assert row['pending_maturity']['next_execution_date']=='2026-10-16'
        assert row['pending_maturity']['changed_rows']==1
    frames['orders'].loc[frames['orders'].signal_date.eq(pd.Timestamp('2026-10-15')),'execution_date']=pd.Timestamp('2026-10-17')
    with pytest.raises(ValueError,match='PENDING_OPEN_CLOCK'):
        finite._prefix_receipt(paths,sid,frames,admission,body)


@pytest.mark.parametrize('name,field',[('daily','cash'),('positions','weight'),('fills','price'),
    ('entitlements','amount_usd'),('actions','target_weight'),('orders','target_weight')])
def test_target16_six_table_prefix_value_drift_blocks(tmp_path,name,field):
    paths,frames,body,sid=prefix_case(tmp_path,end='2026-10-15',next_session='2026-10-16')
    body['scope']=deepcopy(finite.TARGET16_SCOPE)
    frames[name].loc[0,field]+=1
    with pytest.raises(ValueError,match='PREFIX'):
        finite._prefix_receipt(paths,sid,frames,artifact(tmp_path,'admission.json',{'synthetic':True}),body)


@pytest.mark.parametrize('change',['dtype','extra_column','missing_row','identity'])
def test_target16_prefix_schema_rowset_and_identity_stay_exact(tmp_path,change):
    paths,frames,body,sid=prefix_case(tmp_path,end='2026-10-15',next_session='2026-10-16')
    body['scope']=deepcopy(finite.TARGET16_SCOPE)
    if change=='dtype':frames['daily']['cash']=frames['daily']['cash'].astype('float32')
    elif change=='extra_column':frames['daily']['extra']=1
    elif change=='missing_row':frames['daily']=frames['daily'].iloc[1:]
    else:frames['positions'].loc[0,'ticker']='CHANGED'
    with pytest.raises(ValueError,match='PREFIX'):
        finite._prefix_receipt(paths,sid,frames,artifact(tmp_path,'admission.json',{'synthetic':True}),body)


@pytest.mark.parametrize('change',['adapter_path','admission_ref','cutoff'])
def test_old15_exact_identity_cannot_be_rebased_or_extended(target16, change):
    s=target16; manifest=finite._read(s.accepted)
    receipts={sid:finite._read(ref) for sid,ref in s.completions.items()}
    if change=='adapter_path':
        for receipt in receipts.values():
            receipt['source_refs']['finite_ca_adapter_ref']['path']=str(s.legacy)
    elif change=='admission_ref':
        for receipt in receipts.values():
            receipt['source_refs']['finite_ca_admission_ref']['sha256']='0'*64
    else:manifest['end']='2026-10-16'
    with pytest.raises(ValueError):
        finite.validate_published_continuation(None,manifest_ref=None,manifest=manifest,completion_receipts=receipts)
