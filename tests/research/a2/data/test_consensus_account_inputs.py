"""Synthetic-only task input gating, exact projection, source-owner wiring."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
from scripts.research.a2.data import consensus_account_inputs as inputs



@pytest.fixture(autouse=True)
def pinned_legacy_fact_owners(monkeypatch):
    # This adapter's historical fact recipe owns d456/8f. Live collection sources
    # may advance independently; generated fixtures must use the declared owner.
    root=Path('D:/us-tech-quant-backtests/CONSENSUS100_PTO_3000_20261012_R1/20261011T170254+0000_bf592a79/source_custody')
    source=inputs.existing._load_python(dict(path=str(root/'reused_pair_ca_sources_source.py'),sha256=inputs.SOURCE_ADAPTER_SHA),'_generated_consensus_d456_fact_owner')
    cash=inputs.existing._load_python(dict(path=str(root/'joint_cash_bindings_8f57_source.py'),sha256=inputs.SOURCE_DEPENDENCIES['joint_cash_bindings']),'_generated_consensus_8f_fact_cash')
    source.cash=cash
    monkeypatch.setattr(inputs.existing,'source',source)
    monkeypatch.setattr(inputs,'SOURCE_DEPENDENCIES',dict(inputs.SOURCE_DEPENDENCIES,corporate_action=inputs.sha256(inputs.existing.ca.__file__)))


def proof(path):
    return dict(scope_start='2023-01-01',scope_end_exclusive='2026-01-01',branch='A',classification_ref=inputs.file_ref(path))


def quote_file(tmp_path):
    # The illegal numeric spelling is deliberately only in lexically skipped
    # evidence/outcome; any accidental whole/record JSON decode fails visibly.
    p=tmp_path/'classification.json'
    p.write_text('{"branches":{"B":{"outcome":{"numeric":DO_NOT_DECODE_THIS_OUTCOME}},"A":{"decisions":['
        '{"evidence":{"raw_rows":[{"open":DO_NOT_DECODE_THIS_UNSELECTED_PRICE}]},"key":{"date":"2025-06-02","ticker":"X"},"classification":"G","source_availability":"UNKNOWN","qualification":{}},'
        '{"key":{"date":"2025-06-03","ticker":"S"},"classification":"A","source_availability":"UNKNOWN","qualification":{},"evidence":{"raw_rows":[{"open":100,"close":101}]}}]}}}')
    return p


def test_status_projection_never_decodes_numeric_evidence_or_outcome(tmp_path):
    p=quote_file(tmp_path)
    result,receipt=inputs.project_quote_decisions(p,[('2025-06-03','S')],source_scope_proof=proof(p))
    assert len(result)==1 and result[0]['key']==dict(date='2025-06-03',ticker='S')
    assert 'evidence' not in result[0] and receipt['numeric_evidence_records_decoded']==0
    assert receipt['unselected_values_json_decoded'] is False


def test_numeric_gate_projection_decodes_only_preselected_exact_record(tmp_path):
    p=quote_file(tmp_path)
    result,receipt=inputs.project_quote_decisions(p,[('2025-06-03','S')],decode_numeric_evidence=True,source_scope_proof=proof(p))
    assert result[0]['evidence']['raw_rows'][0]['open']==100
    assert receipt['numeric_evidence_records_decoded']==1


def test_quote_projection_rejects_unproven_scope_before_parse(tmp_path,monkeypatch):
    p=quote_file(tmp_path)
    with pytest.raises(ValueError,match='SOURCE_SCOPE_PROOF'):
        inputs.project_quote_decisions(p,[('2025-06-03','S')],source_scope_proof=dict(proof(p),scope_end_exclusive='2027-01-01'))
    with pytest.raises(ValueError,match='KEY_OUTSIDE_SCOPE'):
        inputs.project_quote_decisions(p,[('2026-01-01','S')],source_scope_proof=proof(p))


def test_exact_arrow_price_keys_exclude_gap_day_before_numeric_projection(tmp_path):
    dates=pd.DatetimeIndex(['2025-06-02','2025-06-03','2025-06-04'])
    p=tmp_path/'prices.parquet'
    pd.DataFrame(dict(ticker=['S']*3,trade_date=dates,open=['POISON_BEFORE_ENTRY','100','POISON_IDENTITY_GAP'])).to_parquet(p,index=False)
    keys=pd.DataFrame(dict(ticker=['S'],signal_date=[dates[1]]))
    table=pq.read_table(p,columns=['trade_date','ticker','open'],filters=inputs._price_filters(keys)).to_pandas()
    assert table.open.tolist()==['100'] and table.trade_date.tolist()==[dates[1]]


def fixture(tmp_path,monkeypatch,*,gate=False):
    root=tmp_path/inputs.TASK;root.mkdir();dates=pd.DatetimeIndex(['2025-06-02','2025-06-03','2025-06-04'])
    sources={}
    for key in inputs.existing.DEFAULT_REFS:
        p=root/(key+'.json');p.write_text('{}');sources[key]=inputs.file_ref(p)
    def parquet(name,frame):
        p=root/(name+'.parquet');frame.to_parquet(p,index=False);return inputs.file_ref(p)
    sources['raw_prices']=parquet('raw_prices',pd.DataFrame(dict(trade_date=dates,ticker=['S']*3,open=[9000.,100.,100.],close=[9000.,100.,100.],price_quality_warning=[False]*3)))
    sources['dated_identity']=parquet('dated_identity',pd.DataFrame(dict(signal_date=dates,ticker=['S']*3,security_id=['111111111']*3,moomoo_transport_code=['US.S']*3)))
    pool=parquet('pool',pd.DataFrame(dict(signal_date=[dates[1],dates[2]],cusip=['111111111']*2,ticker=['S']*2,security_id=['111111111']*2,identity_present=[True]*2)))
    calendar=parquet('calendar',pd.DataFrame(dict(trade_date=dates)))
    settle_calendar=parquet('settlement_calendar',pd.DataFrame(dict(settlement_date=dates)))
    mapping=dict(records=[dict(ticker='S',start='2023-01-01',end='2026-01-01',coordinate='RAW_ACTUAL_SHARE',sid='111111111')])
    identity=dict(rows=[dict(ticker='S',observed_decision_security_ids=['111111111'])])
    for key,payload in [('a_mapping',mapping),('a_identity',identity),('a_authority',dict(research_account=dict(research_account_authority=None))),('quote_classification',dict(branches=dict(A=dict(decisions=[]))))]:
        p=Path(sources[key]['path']);p.write_text(json.dumps(payload));sources[key]=inputs.file_ref(p)
    # Reuse the actual archived pure make_market and wrapper quality owners.
    for key in ['market_adapter','quote_composer']:sources[key]=copy.deepcopy(inputs.existing.DEFAULT_REFS[key])
    def custody(_):
        def pin(ref):
            assert inputs.sha256(ref['path'])==ref['sha256'];return Path(ref['path'])
        return pin,lambda ref:json.loads(pin(ref).read_text())
    monkeypatch.setattr(inputs.existing,'custody_reader',custody)
    adv_ref=dict(path='synthetic://signal_adv',sha256='b'*64)
    fact_path=root/'reused_pair_ca_sources_source.py';fact_path.write_bytes(Path(inputs.existing.source.__file__).read_bytes())
    dependencies={'joint_cash_bindings':inputs.file_ref(inputs.existing.source.cash.__file__),'corporate_action':inputs.file_ref(inputs.existing.ca.__file__)}
    scope=inputs.source_scope_template(sources=sources,pool_ref=pool,calendar_ref=calendar,settlement_calendar_ref=settle_calendar,legacy_source_transport=[],
        quote_classification_scope_proof=proof(sources['quote_classification']['path']),signal_adv_source_ref=adv_ref,source_fact_owner_ref=inputs.file_ref(fact_path),source_dependency_refs=dependencies)
    if gate:scope['numeric_read_authorization']=inputs.GATE
    scope_path=root/'ACCOUNT_SOURCE_SCOPE.json';scope_path.write_text(json.dumps(scope))
    freeze_path=root/'ACCOUNT_FREEZE.json';freeze_path.write_text(json.dumps(dict(task_id=inputs.TASK,status='SYNTHETIC_ONLY')))
    bound=inputs.metadata_preflight(frozen_contract_ref=inputs.file_ref(freeze_path),source_scope_ref=inputs.file_ref(scope_path))
    adv=pd.DataFrame(dict(signal_date=dates,ticker=['S']*3,adv=[1e7]*3,available_at=[str(d.date())+'T19:59:00Z' for d in dates]));adv.attrs['source_ref']=adv_ref
    return bound,adv


def test_metadata_preflight_reads_no_price_and_keeps_post_entry_identity(tmp_path,monkeypatch):
    observed=[];original=pq.read_table
    def spy(path,**kw):observed.append((str(path),kw['columns']));return original(path,**kw)
    monkeypatch.setattr(pq,'read_table',spy)
    bound,_=fixture(tmp_path,monkeypatch)
    assert not bound['numeric_prices_read'] and not bound['quote_numeric_evidence_read']
    assert not any({'open','close','adv'}&set(cols) for _,cols in observed)
    assert bound['raw_keys'].signal_date.min()==pd.Timestamp('2025-06-03')
    assert len(bound['raw_keys'])==2


def test_unfrozen_gate_and_memory_mutation_fail_before_numeric_decode(tmp_path,monkeypatch):
    bound,adv=fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(inputs.joblib,'load',lambda _:pytest.fail('numeric source decoded before gate'))
    with pytest.raises(ValueError,match='NUMERIC_READ_GATE'):
        inputs.load_account_inputs(bound,signal_adv_by_key=adv)
    bound['scope']['numeric_read_authorization']=inputs.GATE
    with pytest.raises(ValueError,match='BOUND_SOURCE_SCOPE_CHANGED'):
        inputs.load_account_inputs(bound,signal_adv_by_key=adv)


def test_authorized_actual_entry_wires_owners_without_old_execution_authority(tmp_path,monkeypatch):
    bound,adv=fixture(tmp_path,monkeypatch,gate=True);calls=[]
    original=dict(entitlement_events=(),entitlement_security_tickers={},unsupported_events=(),corporate_actions=(),corporate_action_known_at={})
    source_binding=dict(status='SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND',source_fingerprint='c'*64,event_fingerprints=[],security_tickers={},quantity_coordinate=inputs.existing.ca.RAW_OLD_SHARE_COORDINATE)
    monkeypatch.setattr(inputs.joblib,'load',lambda _:original)
    def bind(owner,catalogue,bundle,**kw):
        calls.append('existing_private_source_adapter');return dict(events=copy.deepcopy(original),ordinary_cash_event_fingerprints=[],receipt={'synthetic':True})
    monkeypatch.setattr(inputs,'FunctionType',lambda *a,**kw:lambda *a:SimpleNamespace(bind_source_account_descendant=bind))
    def combine(descendant,*a):
        calls.append('existing_combine_cash_and_terminal');return dict(**original,entitlement_source_binding=source_binding,research_account_authority={}),{'synthetic':True}
    monkeypatch.setattr(inputs.existing,'combine_cash_and_terminal',combine)
    Path(bound['sources']['a_catalogue']['path']).write_text('{"events":[]}')
    bound['sources']['a_catalogue']=inputs.file_ref(bound['sources']['a_catalogue']['path'])
    p=Path(bound['sources']['a_catalogue']['path']);bound['physical_stats'][str(p)]=dict(size=p.stat().st_size,mtime_ns=p.stat().st_mtime_ns)
    # Fixture source change is frozen back into its exact synthetic task scope.
    Path(bound['source_scope_ref']['path']).write_text(json.dumps(bound['scope']));bound['source_scope_ref']=inputs.file_ref(bound['source_scope_ref']['path'])
    result=inputs.load_account_inputs(bound,signal_adv_by_key=adv)
    assert calls==['existing_private_source_adapter','existing_combine_cash_and_terminal']
    assert result['task_authority']['task_id']==inputs.TASK and result['task_authority']['schema']==inputs.account.SCHEMA
    assert np.isnan(result['market'].open[0,0]) and result['market'].open[1,0]==100.
    assert result['quote_execution_upgrade_applied'] is False and not result['usable_a'].any()
    assert result['market'].new_buy_eligible[:,0].tolist()==[False,True,True]
    assert result['market'].adv[1,0]==1e7


def test_signal_adv_requires_signal_available_source_binding(tmp_path,monkeypatch):
    bound,adv=fixture(tmp_path,monkeypatch,gate=True)
    monkeypatch.setattr(inputs.joblib,'load',lambda _:pytest.fail('source decode before ADV qualification'))
    adv.loc[0,'available_at']='2025-06-03T20:00:00Z'
    with pytest.raises(ValueError,match='SIGNAL_ADV_NOT_SIGNAL_KNOWN'):
        inputs.load_account_inputs(bound,signal_adv_by_key=adv)

def test_qualified_loader_to_full_shareholder_cash_replay_synthetic(tmp_path,monkeypatch):
    from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import TargetDecision
    from scripts.research.a2.evaluation.consensus_cash_account import FeeConfig
    bound,adv=fixture(tmp_path,monkeypatch,gate=True)
    original=dict(entitlement_events=(),entitlement_security_tickers={},unsupported_events=(),corporate_actions=(),corporate_action_known_at={})
    binding=dict(status='SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND',source_fingerprint='c'*64,event_fingerprints=[],security_tickers={},quantity_coordinate=inputs.existing.ca.RAW_OLD_SHARE_COORDINATE)
    monkeypatch.setattr(inputs.joblib,'load',lambda _:original)
    monkeypatch.setattr(inputs,'FunctionType',lambda *a,**kw:lambda *a:SimpleNamespace(bind_source_account_descendant=lambda *a,**kw:dict(events=original,ordinary_cash_event_fingerprints=[],receipt={'synthetic':True})))
    monkeypatch.setattr(inputs.existing,'combine_cash_and_terminal',lambda *a: (dict(**original,entitlement_source_binding=binding,research_account_authority={}),{'synthetic':True}))
    p=Path(bound['sources']['a_catalogue']['path']);p.write_text('{"events":[]}');bound['sources']['a_catalogue']=inputs.file_ref(p)
    bound['physical_stats'][str(p)]=dict(size=p.stat().st_size,mtime_ns=p.stat().st_mtime_ns)
    Path(bound['source_scope_ref']['path']).write_text(json.dumps(bound['scope']));bound['source_scope_ref']=inputs.file_ref(bound['source_scope_ref']['path'])
    loaded=inputs.load_account_inputs(bound,signal_adv_by_key=adv)
    def policy(di,ctx):return TargetDecision(np.full(ctx.current_units.shape,.1),ctx.decision_mask.copy(),'synthetic joint target')
    events=loaded['events']
    replay=inputs.account.run_shareholder_cash_account(loaded['market'],['x'],policy,task_authority=loaded['task_authority'],
        settlement_calendar=loaded['settlement_calendar'],fee_config=FeeConfig(10,.5,5,True),corporate_actions=events['corporate_actions'],
        corporate_action_known_at=events['corporate_action_known_at'],unsupported_events=events['unsupported_events'],entitlement_events=events['entitlement_events'],
        entitlement_security_tickers=events['entitlement_security_tickers'],entitlement_source_binding=events['entitlement_source_binding'])
    assert len(replay.fills)==1 and replay.fills.notional.iloc[0]==pytest.approx(300.)
    assert replay.fills.transaction_cost.iloc[0]==pytest.approx(.8)
    assert replay.audit['actual_cash_flow_identity_error_max']<1e-8
    assert replay.metadata['quote_vintage_status']=='UNKNOWN' and replay.metadata['certified_NAV'] is False


def signal_record(day='2025-06-03',ticker='S',open=100.,close=100.):
    return dict(date=day,ticker=ticker,masked=True,inherited_event_mask=True,
        raw_rows=[dict(date=day,ticker=ticker,open=open,close=close,code='US.'+ticker)],
        identity_records=[dict(ticker=ticker,start='2023-01-01',end='2026-01-01',coordinate='RAW_ACTUAL_SHARE',sid='111111111')],
        code_tickers={'US.'+ticker:[ticker]},coordinate='RAW_ACTUAL_SHARE',independent_quality_flags=[],
        mechanisms=[dict(mask_origin='INHERITED_UNSUPPORTED_EVENT',ticker=ticker,date=day,source_fingerprint='f'*64,source_reference='synthetic://event')],terminal_contracts=[])


def signal_freeze(tmp_path,raw_ref=None,mapping_ref=None,*,poison=False):
    root=tmp_path/inputs.TASK/'signal';root.mkdir(parents=True,exist_ok=True)
    refs={}
    for role in ('security_mapping','cash_catalogue','human_authorization','raw_quote_coordinate_proof'):
        p=root/(role+'.json');p.write_text('{}');refs[role]=inputs.file_ref(p)
    if mapping_ref:refs['security_mapping']=mapping_ref
    for role,clock in [('raw_quotes','trade_date'),('event_mechanism_source','event_date')]:
        p=root/(role+'.parquet');pd.DataFrame({clock:pd.to_datetime(['2025-06-03'])}).to_parquet(p,index=False)
        refs[role]={**inputs.file_ref(p),'clock_column':clock}
    if raw_ref:refs['raw_quotes']={**raw_ref,'clock_column':'trade_date'}
    decisions=[inputs.signal_quote.classify_quote_key(signal_record())]
    pop=dict(schema='QUOTE_MASK_POPULATION_CENSUS_R1',task_id=inputs.signal_quote.TASK_ID,source_refs=refs,masked_key_count=1,decisions=decisions)
    p=root/'population.json';text=json.dumps(pop)
    if poison:text=text.replace('"open": 100.0','"open": DO_NOT_DECODE_THIS_PRICE',1)
    p.write_text(text);population=inputs.file_ref(p)
    owner=inputs.file_ref(inputs.signal_quote.__file__)
    frozen=dict(schema='FROZEN_RESEARCH_QUOTE_DOMAIN_R1',status='FROZEN_BEFORE_ACCOUNT_ATTEMPT',task_id=inputs.signal_quote.TASK_ID,
        namespace=inputs.signal_quote.NAMESPACE,rule_definition=inputs.signal_quote.RULE_DEFINITION,module_ref=owner,population_ref=population,
        source_refs=refs,source_pins={owner['path']:owner['sha256']},strict_PIT_promotion_eligible=False,production_qualified=False,
        certified_market_data=False,certified_market_quote_authority=False)
    p=root/'freeze.json';p.write_text(json.dumps(frozen))
    return inputs.file_ref(p),dict(scope_start='2023-01-01',scope_end_exclusive='2026-01-01',branch='STATEFUL',classification_ref=population)


def test_signal_metadata_reuses_source_checks_without_population_numeric_decode(tmp_path):
    ref,popproof=signal_freeze(tmp_path,poison=True)
    result=inputs.signal_quote_metadata_preflight(ref)
    assert result['header']['masked_key_count']==1
    assert result['lineage']['population_full_numeric_decode'] is False
    assert result['lineage']['original_source_checks_unchanged']
    # An accidental full population decode would fail on the poison numeric.
    with pytest.raises(json.JSONDecodeError):json.loads(Path(popproof['classification_ref']['path']).read_text())


def test_signal_metadata_requires_exact_owner_and_pre2026_source_clock(tmp_path):
    ref,_=signal_freeze(tmp_path)
    frozen=json.loads(Path(ref['path']).read_text());event=frozen['source_refs']['event_mechanism_source']
    pd.DataFrame(dict(event_date=pd.to_datetime(['2026-01-01']))).to_parquet(event['path'],index=False)
    frozen['source_refs']['event_mechanism_source']['sha256']=inputs.sha256(event['path'])
    Path(ref['path']).write_text(json.dumps(frozen));ref=inputs.file_ref(ref['path'])
    with pytest.raises(ValueError,match='NOT_PHYSICALLY_PRE2026'):inputs.signal_quote_metadata_preflight(ref)


def test_stateful_exact_projection_skips_unselected_poison_prices(tmp_path):
    p=tmp_path/'population.json';valid=inputs.signal_quote.classify_quote_key(signal_record())
    p.write_text('{"decisions":[{"key":{"date":"2025-06-02","ticker":"X"},"classification":"B","evidence":{"open":UNSELECTED_PRICE}},'+json.dumps(valid)+'],"unexecuted_account":{"outcome":DO_NOT_READ}}')
    sourceproof=dict(scope_start='2023-01-01',scope_end_exclusive='2026-01-01',branch='STATEFUL',classification_ref=inputs.file_ref(p))
    result,receipt=inputs.project_quote_decisions(p,[('2025-06-03','S')],decode_numeric_evidence=True,source_scope_proof=sourceproof)
    assert result==[valid] and receipt['numeric_evidence_records_decoded']==1
    assert not receipt['unselected_values_json_decoded'] and not receipt['outcome_branches_json_decoded']


def test_signal_binding_clears_only_both_source_owners_and_preserves_ca_base():
    from dataclasses import dataclass,replace
    @dataclass
    class Market:
        dates:object;tickers:tuple;open:object;close:object;quality:object
    raw=Market(pd.DatetimeIndex(['2025-06-03']),('S','X','Y','Z'),np.full((1,4),100.),np.full((1,4),100.),np.array([[False,False,True,False]]))
    original=replace(raw,quality=np.ones((1,4),bool));remaining=replace(raw,quality=np.array([[False,False,True,True]]))
    decisions=[inputs.signal_quote.classify_quote_key(signal_record(ticker=t)) for t in raw.tickers]
    market,usable,audit=inputs.apply_signal_quote_binding(raw,original,remaining,np.array([[True,False,True,True]]),decisions)
    assert market.quality.tolist()==[[False,True,True,True]] and usable.tolist()==[[True,False,False,False]]
    assert audit['actual_signal_quality_cleared_count']==1 and audit['independent_quality_preserved']
    bad=copy.deepcopy(decisions);bad[0]=inputs.signal_quote.classify_quote_key(signal_record(open=99.))
    with pytest.raises(ValueError,match='RAW_COORDINATE_MISMATCH'):inputs.apply_signal_quote_binding(raw,original,remaining,np.ones((1,4),bool),bad)


def test_signal_source_binding_full_loader_and_cash_account_synthetic(tmp_path,monkeypatch):
    from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import TargetDecision
    from scripts.research.a2.evaluation.consensus_cash_account import FeeConfig
    bound,adv=fixture(tmp_path,monkeypatch,gate=True)
    original=dict(entitlement_events=(),entitlement_security_tickers={},unsupported_events=[dict(ticker='S',effective_date='2025-06-03')],corporate_actions=(),corporate_action_known_at={})
    current={**original,'unsupported_events':()}
    binding=dict(status='SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND',source_fingerprint='c'*64,event_fingerprints=[],security_tickers={},quantity_coordinate=inputs.existing.ca.RAW_OLD_SHARE_COORDINATE)
    monkeypatch.setattr(inputs.joblib,'load',lambda _:original)
    monkeypatch.setattr(inputs,'FunctionType',lambda *a,**kw:lambda *a:SimpleNamespace(bind_source_account_descendant=lambda *a,**kw:dict(events=current,ordinary_cash_event_fingerprints=[],receipt={'synthetic':True})))
    monkeypatch.setattr(inputs.existing,'combine_cash_and_terminal',lambda *a:(dict(**current,entitlement_source_binding=binding,research_account_authority={}),{'synthetic':True}))
    p=Path(bound['sources']['a_catalogue']['path']);p.write_text('{"events":[]}');bound['sources']['a_catalogue']=inputs.file_ref(p)
    r=dict(date='2025-06-03',ticker='S',masked=True,
        raw_rows=[dict(date='2025-06-03',ticker='S',open=100.,close=100.,row_identity=1,source_ref={'path':'synthetic://raw','sha256':'a'*64},coordinate='RAW_UNADJUSTED')],
        raw_coordinate_proof=dict(status='RAW_UNADJUSTED',source_ref={'path':'synthetic://raw','sha256':'a'*64}),
        identity_proof=dict(kind='OPAQUE_FROZEN_BUNDLE',status='EXACT_UNIQUE',token='synthetic dated identity',source_ref={'path':'synthetic://raw','sha256':'a'*64}),
        identity_conflicts=[],coordinate_conflicts=[],quality_origins=[dict(kind='MECHANISM_ONLY',reason='UNSUPPORTED_ACCOUNTING_FACTOR',source_ref={'path':'synthetic://event','sha256':'b'*64})],
        known_real_defect_flags=[],known_real_defect_scope=dict(status='BOUND_APPROVED_SOURCES_CHECKED',source_refs=[{'path':'synthetic://raw','sha256':'a'*64},{'path':'synthetic://event','sha256':'b'*64}]),terminal_contracts=[],source_availability='UNKNOWN')
    shared=inputs.existing.quote.classify_quote_key(r);assert shared['classification']=='A'
    p=Path(bound['sources']['quote_classification']['path']);p.write_text(json.dumps(dict(branches=dict(A=dict(decisions=[shared])))))
    bound['sources']['quote_classification']=inputs.file_ref(p)
    scope=bound['scope'];scope['quote_classification_scope_proof']=proof(p)
    signalref,signalproof=signal_freeze(tmp_path,scope['sources']['raw_prices'],scope['sources']['a_mapping'])
    scope.update(signal_quote_domain_ref=signalref,signal_quote_population_scope_proof=signalproof)
    Path(bound['source_scope_ref']['path']).write_text(json.dumps(scope))
    bound=inputs.metadata_preflight(frozen_contract_ref=bound['frozen_contract_ref'],source_scope_ref=inputs.file_ref(bound['source_scope_ref']['path']))
    loaded=inputs.load_account_inputs(bound,signal_adv_by_key=adv)
    assert not loaded['market'].quality[1,0] and loaded['usable_a'][1,0]
    assert loaded['signal_quote_binding']['audit']['actual_signal_quality_cleared_count']==1
    assert not loaded['signal_quote_binding']['legacy_execution_authority_reused'] and loaded['conditional_research_only']
    def policy(di,ctx):return TargetDecision(np.full(ctx.current_units.shape,.1),ctx.decision_mask.copy(),'source qualified signal synthetic')
    events=loaded['events']
    replay=inputs.account.run_shareholder_cash_account(loaded['market'],['x'],policy,task_authority=loaded['task_authority'],settlement_calendar=loaded['settlement_calendar'],fee_config=FeeConfig(10,.5,5,True),
        corporate_actions=events['corporate_actions'],corporate_action_known_at=events['corporate_action_known_at'],unsupported_events=events['unsupported_events'],
        entitlement_events=events['entitlement_events'],entitlement_security_tickers=events['entitlement_security_tickers'],entitlement_source_binding=events['entitlement_source_binding'])
    assert len(replay.fills)==1 and replay.fills.notional.iloc[0]==pytest.approx(300.)
    assert replay.fills.transaction_cost.iloc[0]==pytest.approx(.8) and replay.audit['actual_cash_flow_identity_error_max']<1e-8


def test_unexecuted_old_replay_pin_is_audited_never_old_freeze_pass(tmp_path):
    ref,_=signal_freeze(tmp_path);p=Path(ref['path']);frozen=json.loads(p.read_text())
    old=inputs.LEGACY_SIGNAL_REPLAY_REF
    frozen['source_pins'][old['path']]=old['sha256'];p.write_text(json.dumps(frozen))
    result=inputs.signal_quote_metadata_preflight(inputs.file_ref(p));lineage=result['lineage']
    assert lineage['unexecuted_old_source_pins']==[dict(ref=old,status='UNEXECUTED_OLD_SOURCE_PIN_NOT_REVALIDATED',same_byte_custody_unavailable=True)]
    assert not lineage['old_freeze_full_validation_passed'] and not lineage['original_source_checks_unchanged']
    assert lineage['source_ref_and_clock_checks_unchanged'] and lineage['current_task_source_fact_closure_qualified']


def test_other_changed_source_pin_still_fails_closed(tmp_path):
    ref,_=signal_freeze(tmp_path);p=Path(ref['path']);frozen=json.loads(p.read_text())
    frozen['source_pins'][str(p.parent/'unknown_source.py')]='9'*64;p.write_text(json.dumps(frozen))
    with pytest.raises((FileNotFoundError,ValueError)):inputs.signal_quote_metadata_preflight(inputs.file_ref(p))


def test_raw_identity_screen_missing_sid_never_creates_empty_shared_uid():
    frame=pd.DataFrame(dict(signal_date=pd.to_datetime(['2025-06-03']*4),ticker=['S','X','Y','Z'],security_id=['111111111',None,'','   '],moomoo_transport_code=['US.S','US.X','US.Y','US.Z']))
    qualified,gaps,proof=inputs.screen_raw_identity_keys(frame)
    assert qualified.ticker.tolist()==['S'] and qualified.security_uid.tolist()==['CUSIP:111111111']
    assert {g['ticker'] for g in gaps}=={'X','Y','Z'} and all(g['security_uid'] is None for g in gaps)
    assert all(g['reason']=='MISSING_DATED_SECURITY_IDENTITY' for g in gaps)
    assert proof['missing_identity_keys']==3 and proof['ambiguous_identity_keys']==0
    links,owner_gaps=inputs.existing.identity_links(qualified,
        dict(records=[dict(ticker='S',start='2023-01-01',end='2026-01-01',coordinate='RAW_ACTUAL_SHARE',sid='111111111')]),
        dict(rows=[dict(ticker='S',observed_decision_security_ids=['111111111'])]),frame)
    assert links.ticker.tolist()==['S'] and not owner_gaps


def test_raw_identity_screen_ambiguous_valid_uid_blocks_all_aliases():
    frame=pd.DataFrame(dict(signal_date=pd.to_datetime(['2025-06-03','2025-06-03','2025-06-03','2025-06-04']),ticker=['S','X','Y','S'],security_id=['111111111','111111111','222222222','111111111']))
    qualified,gaps,proof=inputs.screen_raw_identity_keys(frame)
    assert list(zip(qualified.signal_date.dt.strftime('%Y-%m-%d'),qualified.ticker))==[('2025-06-03','Y'),('2025-06-04','S')]
    assert {g['ticker'] for g in gaps}=={'S','X'} and all(g['reason']=='AMBIGUOUS_DATED_SECURITY_UID' for g in gaps)
    assert proof['ambiguous_identity_keys']==2 and proof['ambiguous_date_uid_pairs']==1
    assert not qualified.duplicated(['signal_date','security_uid']).any()


def test_metadata_preflight_missing_hold_context_is_gapped_before_price_projection(tmp_path,monkeypatch):
    bound,adv=fixture(tmp_path,monkeypatch,gate=True)
    sources=bound['scope']['sources'];path=Path(sources['dated_identity']['path'])
    # Signal pool has day2 only; missing day3 is continued context, not a new buy.
    dated=pd.read_parquet(path);dated.loc[dated.signal_date.eq('2025-06-04'),'security_id']=None;dated.to_parquet(path,index=False);sources['dated_identity']=inputs.file_ref(path)
    path=Path(bound['scope']['pool_ref']['path']);pool=pd.read_parquet(path);pool=pool.loc[pool.signal_date.eq('2025-06-03')];pool.to_parquet(path,index=False);bound['scope']['pool_ref']=inputs.file_ref(path)
    p=Path(bound['source_scope_ref']['path']);p.write_text(json.dumps(bound['scope']))
    observed=[];original_read=pq.read_table
    def spy(path,**kw):observed.append(kw['columns']);return original_read(path,**kw)
    monkeypatch.setattr(pq,'read_table',spy)
    fixed=inputs.metadata_preflight(frozen_contract_ref=bound['frozen_contract_ref'],source_scope_ref=inputs.file_ref(p))
    assert not any({'open','close'}&set(cols) for cols in observed)
    assert fixed['raw_keys'].signal_date.tolist()==[pd.Timestamp('2025-06-03')]
    assert fixed['raw_identity_gaps']==[dict(signal_date='2025-06-04',security_uid=None,ticker='S',reason='MISSING_DATED_SECURITY_IDENTITY')]
    assert fixed['metadata_proofs']['raw_identity_key_screen']['missing_identity_keys']==1
    price=pq.read_table(sources['raw_prices']['path'],columns=['trade_date','ticker'],filters=inputs._price_filters(fixed['raw_keys'])).to_pandas()
    assert price.trade_date.tolist()==[pd.Timestamp('2025-06-03')]
    assert fixed['keys'].signal_date.tolist()==[pd.Timestamp('2025-06-03')]


def construction_transport(tmp_path):
    source=Path('D:/us-tech-quant-cache/V24/V24_B_FAST_TRACK_PAIR_COMPLETION_R1/source_audit/original_frozen/reused_pair_ca_sources_1775b34066887c59b1da10e83121c6d860575d050edded5f59040a457684ba98.py')
    root=tmp_path/inputs.TASK/'source_custody';root.mkdir(parents=True,exist_ok=True)
    path=root/'construction1775.py';path.write_bytes(source.read_bytes())
    assert inputs.sha256(path)==inputs.LEGACY_SOURCE_FACT_OWNER_REF['sha256']
    return dict(original_ref=copy.deepcopy(inputs.LEGACY_SOURCE_FACT_OWNER_REF),custody_ref=inputs.file_ref(path),original_bytes_unchanged=True,old_ref_not_relabelled_as_current_producer=True)


def test_exact_construction_transport_keeps_old_pin_and_current_source_owner(tmp_path,monkeypatch):
    tx=construction_transport(tmp_path);calls=[]
    def original_custody(_):
        def pin(ref):
            calls.append(ref.copy());assert inputs.sha256(ref['path'])==ref['sha256'];return Path(ref['path'])
        return pin,lambda ref:json.loads(pin(ref).read_text())
    monkeypatch.setattr(inputs.existing,'custody_reader',original_custody)
    pin,read,proof=inputs.source_fact_custody_reader([],tx)
    assert pin(tx['original_ref'])==Path(tx['custody_ref']['path'])
    assert calls[-1]==tx['custody_ref'] and proof['source_pin_check_skipped'] is False
    # The exact current execution owner/private namespace still invokes this
    # pin. The recovered original source is custody only, never executed.
    current=inputs.existing.source
    factory=inputs.FunctionType(inputs.existing.private_source_adapter.__code__,{**inputs.existing.private_source_adapter.__globals__,'source':current},argdefs=inputs.existing.private_source_adapter.__defaults__)
    adapter=factory(pin,read)
    assert adapter._pin(tx['original_ref'])==Path(tx['custody_ref']['path'])
    assert adapter.bind_source_account_descendant.__code__ is current.bind_source_account_descendant.__code__
    assert proof['old_bundle_references_unchanged'] and not proof['legacy_execution_authority_reused']
    other=tmp_path/inputs.TASK/'plain_source.json';other.write_text('{"source":"unchanged"}')
    assert read(inputs.file_ref(other))=={'source':'unchanged'}


def test_construction_transport_never_repins_wrong_original_or_changes_bytes(tmp_path,monkeypatch):
    tx=construction_transport(tmp_path)
    def custody(_):
        def pin(ref):
            if inputs.sha256(ref['path'])!=ref['sha256']:raise ValueError('SYNTHETIC_CUSTODY_BYTES_CHANGED')
            return Path(ref['path'])
        return pin,lambda ref:json.loads(pin(ref).read_text())
    monkeypatch.setattr(inputs.existing,'custody_reader',custody)
    for key in ('original_ref','custody_ref'):
        bad=copy.deepcopy(tx);bad[key]['sha256']='9'*64
        with pytest.raises(ValueError,match='SAME_BYTE_1775'):inputs.source_fact_custody_reader([],bad)
    Path(tx['custody_ref']['path']).write_text('TAMPERED')
    with pytest.raises(ValueError,match='CUSTODY_BYTES_CHANGED'):inputs.source_fact_custody_reader([],tx)


def test_construction_transport_cannot_clear_other_ref_failure(tmp_path,monkeypatch):
    tx=construction_transport(tmp_path)
    def custody(_):
        def pin(ref):
            if inputs.sha256(ref['path'])!=ref['sha256']:raise ValueError('SYNTHETIC_UNRELATED_REF_CHANGED')
            return Path(ref['path'])
        return pin,lambda ref:json.loads(pin(ref).read_text())
    monkeypatch.setattr(inputs.existing,'custody_reader',custody)
    pin,_,_=inputs.source_fact_custody_reader([],tx)
    unrelated=tmp_path/inputs.TASK/'other.py';unrelated.write_text('other source')
    with pytest.raises(ValueError,match='UNRELATED_REF_CHANGED'):pin(dict(path=str(unrelated),sha256='1'*64))


def test_metadata_binds_construction_custody_and_detects_post_preflight_change(tmp_path,monkeypatch):
    bound,adv=fixture(tmp_path,monkeypatch,gate=True);tx=construction_transport(tmp_path)
    bound['scope']['source_fact_construction_transport']=tx
    path=Path(bound['source_scope_ref']['path']);path.write_text(json.dumps(bound['scope']))
    fixed=inputs.metadata_preflight(frozen_contract_ref=bound['frozen_contract_ref'],source_scope_ref=inputs.file_ref(path))
    assert str(Path(tx['custody_ref']['path'])) in fixed['physical_stats']
    assert fixed['metadata_proofs']['source_fact_construction_transport']['original_ref']==inputs.LEGACY_SOURCE_FACT_OWNER_REF
    Path(tx['custody_ref']['path']).write_text('CHANGED AFTER PREFLIGHT')
    monkeypatch.setattr(inputs.joblib,'load',lambda _:pytest.fail('No source numerical loads after custody drift'))
    with pytest.raises(ValueError,match='BOUND_PHYSICAL_SOURCE_CHANGED'):inputs.load_account_inputs(fixed,signal_adv_by_key=adv)


def construction_transports(tmp_path):
    first=construction_transport(tmp_path)
    old=inputs.LEGACY_JOINT_CASH_REF
    source=Path('D:/us-tech-quant-cache/V24/V24_B_FAST_TRACK_PAIR_COMPLETION_R1/source_audit/original_frozen')/('joint_cash_bindings_'+old['sha256']+'.py')
    target=Path(first['custody_ref']['path']).parent/'joint_cash8a.py';target.write_bytes(source.read_bytes())
    return [first,dict(original_ref=copy.deepcopy(old),custody_ref=inputs.file_ref(target),original_bytes_unchanged=True,old_ref_not_relabelled_as_current_producer=True)]


def strict_custody(_):
    def pin(ref):
        if inputs.sha256(ref['path'])!=ref['sha256']:raise ValueError('SYNTHETIC_CUSTODY_BYTES_CHANGED')
        return Path(ref['path'])
    return pin,lambda ref:json.loads(pin(ref).read_text())


def test_multi_construction_transport_only_fixed_two_old_bytes(tmp_path,monkeypatch):
    entries=construction_transports(tmp_path);monkeypatch.setattr(inputs.existing,'custody_reader',strict_custody)
    pin,read,proof=inputs.source_fact_custody_reader([],entries)
    assert len(proof['transports'])==2 and proof['source_pin_check_skipped'] is False
    for tx in entries:assert pin(tx['original_ref'])==Path(tx['custody_ref']['path'])
    # Same canonical path with the actual current8f57 dependency SHA is not
    # historical8a; delegation leaves current executable dependency untouched.
    current_ref=inputs.file_ref(inputs.existing.source.cash.__file__)
    assert current_ref['sha256']==inputs.SOURCE_DEPENDENCIES['joint_cash_bindings']
    assert pin(current_ref)==Path(current_ref['path'])
    factory=inputs.FunctionType(inputs.existing.private_source_adapter.__code__,{**inputs.existing.private_source_adapter.__globals__,'source':inputs.existing.source},argdefs=inputs.existing.private_source_adapter.__defaults__)
    adapter=factory(pin,read)
    assert adapter.cash is inputs.existing.source.cash
    for tx in entries:assert adapter._pin(tx['original_ref'])==Path(tx['custody_ref']['path'])


def test_multi_construction_transport_rejects_partial_duplicate_or_extra_ref(tmp_path,monkeypatch):
    entries=construction_transports(tmp_path);monkeypatch.setattr(inputs.existing,'custody_reader',strict_custody)
    for value in ([entries[0]],[entries[0],entries[0]],[*entries,entries[0]]):
        with pytest.raises(ValueError,match='CONSTRUCTION'):inputs.source_fact_custody_reader([],value)
    bad=copy.deepcopy(entries);bad[1]['original_ref']['path']='D:/us-tech-quant/scripts/research/a2/data/arbitrary.py'
    with pytest.raises(ValueError,match='SAME_BYTE'):inputs.source_fact_custody_reader([],bad)


def test_multi_construction_custody_both_pins_before_numeric_and_drift_guard(tmp_path,monkeypatch):
    bound,adv=fixture(tmp_path,monkeypatch,gate=True);entries=construction_transports(tmp_path)
    bound['scope']['source_fact_construction_transport']=entries
    path=Path(bound['source_scope_ref']['path']);path.write_text(json.dumps(bound['scope']))
    fixed=inputs.metadata_preflight(frozen_contract_ref=bound['frozen_contract_ref'],source_scope_ref=inputs.file_ref(path))
    assert all(str(Path(tx['custody_ref']['path'])) in fixed['physical_stats'] for tx in entries)
    assert len(fixed['metadata_proofs']['source_fact_construction_transport']['transports'])==2
    Path(entries[1]['custody_ref']['path']).write_text('SECOND SOURCE CHANGED')
    monkeypatch.setattr(inputs.joblib,'load',lambda _:pytest.fail('numeric decode after second custody drift'))
    with pytest.raises(ValueError,match='BOUND_PHYSICAL_SOURCE_CHANGED'):inputs.load_account_inputs(fixed,signal_adv_by_key=adv)


def test_legacy_typed_rebind_uses_same_pinned_owner_as_source_factory(tmp_path,monkeypatch):
    import importlib.util,sys
    from dataclasses import asdict
    bound,adv=fixture(tmp_path,monkeypatch,gate=True)
    # Same declared source dataclass in a separate loaded legacy namespace,
    # purely synthetic terms. The actual pinned rebind algorithm must convert.
    name='_consensus_synthetic_legacy_ca_rebind'
    spec=importlib.util.spec_from_file_location(name,inputs.existing.ca.__file__)
    legacy=importlib.util.module_from_spec(spec);monkeypatch.setitem(sys.modules,name,legacy);spec.loader.exec_module(legacy)
    event=legacy.SourceBackedEntitlementEvent('synthetic namespace dividend','CASH_DIVIDEND','111111111','S','2025-06-03','2025-06-03','2025-06-04',
        '2025-06-02T12:00:00Z',1.,'USD',legacy.USD_PER_RAW_OLD_SHARE,legacy.RAW_OLD_SHARE_COORDINATE,'TIER2_LOCAL_CANONICAL','synthetic://rebind','b'*64)
    original=dict(entitlement_events=(event,),entitlement_security_tickers={'111111111':'S'},unsupported_events=(),corporate_actions=(),corporate_action_known_at={})
    monkeypatch.setattr(inputs.joblib,'load',lambda _:original)
    monkeypatch.setattr(inputs.existing.source,'rebind_entitlement_catalogue',lambda *a,**kw:pytest.fail('unbound live source rebind executed'))
    source_binding=dict(status='SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND',source_fingerprint='c'*64,event_fingerprints=[event.event_fingerprint],security_tickers={'111111111':'S'},quantity_coordinate=inputs.existing.ca.RAW_OLD_SHARE_COORDINATE)
    loaded={};calls=[];loader=inputs.existing._load_python
    def pinned_loader(ref,name):
        module=loader(ref,name)
        if ref==bound['scope']['source_fact_owner_ref']:
            loaded['module']=module;calls.append('pinned_source_loaded');actual_rebind=module.rebind_entitlement_catalogue
            def rebind(*a,**kw):
                calls.append('pinned_rebind');assert kw['source_owner'] is legacy
                result=actual_rebind(*a,**kw)
                value=result['entitlement_events'][0]
                assert type(value) is inputs.existing.ca.SourceBackedEntitlementEvent
                assert asdict(value)==asdict(event) and value.event_fingerprint==event.event_fingerprint
                return result
            module.rebind_entitlement_catalogue=rebind
        return module
    monkeypatch.setattr(inputs.existing,'_load_python',pinned_loader)
    def factory(code,globals,**kw):
        assert globals['source'] is loaded['module'];calls.append('same_pinned_source_factory')
        def bind(owner,catalogue,*a,**kw):
            assert type(catalogue['entitlement_events'][0]) is inputs.existing.ca.SourceBackedEntitlementEvent
            return dict(events=catalogue,ordinary_cash_event_fingerprints=[],receipt={'synthetic':True})
        return lambda *a:SimpleNamespace(bind_source_account_descendant=bind)
    monkeypatch.setattr(inputs,'FunctionType',factory)
    monkeypatch.setattr(inputs.existing,'combine_cash_and_terminal',lambda descendant,*a:(dict(**descendant['events'],entitlement_source_binding=source_binding,research_account_authority={}),{'synthetic':True}))
    p=Path(bound['sources']['a_catalogue']['path']);p.write_text('{"events":[]}');bound['sources']['a_catalogue']=inputs.file_ref(p)
    bound['physical_stats'][str(p)]=dict(size=p.stat().st_size,mtime_ns=p.stat().st_mtime_ns)
    p=Path(bound['source_scope_ref']['path']);p.write_text(json.dumps(bound['scope']));bound['source_scope_ref']=inputs.file_ref(p)
    result=inputs.load_account_inputs(bound,signal_adv_by_key=adv)
    assert calls==['pinned_source_loaded','pinned_rebind','same_pinned_source_factory']
    assert len(result['events']['entitlement_events'])==1 and result['events']['entitlement_events'][0].event_fingerprint==event.event_fingerprint


def test_continuation_fact_custody_preserves_original_refs_and_current_owner(tmp_path,monkeypatch):
    from scripts.research.a2.training import consensus_fusion as fusion
    repo=tmp_path/'repo';run=tmp_path/'backtests'/fusion.CONTINUATION_RESEARCH_ID/'run'
    base=tmp_path/'results'/inputs.TASK;base.mkdir(parents=True);run.mkdir(parents=True)
    monkeypatch.setattr(fusion,'CONTINUATION_RUN',run)
    monkeypatch.setattr(inputs.existing,'REPO',repo)
    monkeypatch.setattr(inputs.existing,'resolve',lambda p:SimpleNamespace(results_root=tmp_path/'results',backtest_root=tmp_path/'backtests'))
    corporate=repo/'scripts/v22/corporate_action_transition_r1.py';corporate.parent.mkdir(parents=True);corporate.write_text('synthetic-current-ca')
    monkeypatch.setattr(inputs.existing,'ca',SimpleNamespace(__file__=str(corporate)))
    deps={};tx=[];hashes={}
    for role,rel in [('joint_cash_bindings','scripts/research/a2/data/joint_cash_bindings.py'),('corporate_action','scripts/v22/corporate_action_transition_r1.py')]:
        custody=base/(role+'.py');custody.write_text('synthetic-old-'+role);hashes[role]=inputs.sha256(custody)
        deps[role]=dict(path=str(repo/rel),sha256=hashes[role])
        tx.append(dict(role=role,original_ref=copy.deepcopy(deps[role]),custody_ref=inputs.file_ref(custody),original_bytes_unchanged=True,not_current_execution_source=True))
    monkeypatch.setattr(inputs,'SOURCE_DEPENDENCIES',hashes)
    scope=dict(research_id=fusion.CONTINUATION_RESEARCH_ID,source_dependency_refs=deps,continuation_source_dependency_custody=tx,
        continuation_scope_ref=dict(path=str(run/'CONTINUATION_SCOPE.json'),sha256=fusion.CONTINUATION_SCOPE_SHA256),
        account_convention_scope_ref=dict(path=str(run/'ACCOUNT_CONVENTION_SCOPE.json'),sha256='71ccae1d26b09cd972747a1876f7750b940e5b133abac5010c0a7bf28045eba8'),
        current_corporate_owner_ref=inputs.file_ref(corporate))
    seen=[]
    def pin(ref):
        seen.append(copy.deepcopy(ref));path=Path(ref['path'])
        # Control contracts are generated mock authority; code bytes are real generated custody.
        if path.suffix=='.py':assert inputs.sha256(path)==ref['sha256']
        return path
    hp,hr,cash,receipt=inputs.continuation_dependency_custody(scope,pin,lambda r:r)
    assert hp(deps['joint_cash_bindings'])==Path(tx[0]['custody_ref']['path'])
    assert hr(deps['corporate_action'])==tx[1]['custody_ref']
    assert cash==tx[0]['custody_ref'] and receipt['historical_facts_not_relabelled_as_current']
    assert receipt['current_corporate_execution_ref']==scope['current_corporate_owner_ref']
    assert deps['joint_cash_bindings']['path']==str(repo/'scripts/research/a2/data/joint_cash_bindings.py')
    bad=copy.deepcopy(scope);bad['continuation_source_dependency_custody'][0]['custody_ref']['sha256']='f'*64
    with pytest.raises(ValueError,match='NOT_SAME'):inputs.continuation_dependency_custody(bad,pin,lambda r:r)
    bad=copy.deepcopy(scope);bad['current_corporate_owner_ref']['sha256']='f'*64
    with pytest.raises(ValueError,match='EXECUTION_SOURCE'):inputs.continuation_dependency_custody(bad,pin,lambda r:r)
    bad=copy.deepcopy(scope);bad.pop('continuation_source_dependency_custody')
    with pytest.raises(ValueError,match='CUSTODY_REQUIRED'):inputs.continuation_dependency_custody(bad,pin,lambda r:r)
    bad=copy.deepcopy(scope);bad['research_id']='unapproved-other-study'
    with pytest.raises(ValueError,match='IDENTITY_REQUIRED'):inputs.continuation_dependency_custody(bad,pin,lambda r:r)


def test_shared_pinned_python_loader_registers_annotations_and_restores_failed_namespace(tmp_path):
    import sys
    from dataclasses import fields
    name='_generated_consensus_pinned_module_registration'
    good=tmp_path/'good_source.py'
    good.write_text('from __future__ import annotations\nfrom dataclasses import dataclass, InitVar\n@dataclass\nclass Payload:\n    value: int\n    stamp: InitVar[str] = "generated"\n',encoding='utf-8')
    before=sys.modules.get(name)
    try:
        module=inputs.existing._load_python(inputs.file_ref(good),name)
        assert sys.modules[name] is module and module.Payload(3).value==3
        assert [f.name for f in fields(module.Payload)]==['value']
        bad=tmp_path/'bad_source.py';bad.write_text('raise ValueError("generated source failure")\n',encoding='utf-8')
        with pytest.raises(ValueError,match='generated source failure'):inputs.existing._load_python(inputs.file_ref(bad),name)
        assert sys.modules[name] is module
        with pytest.raises(ValueError,match='SOURCE_CHANGED'):inputs.existing._load_python(dict(path=str(good),sha256='f'*64),name)
        assert sys.modules[name] is module
    finally:
        if before is None:sys.modules.pop(name,None)
        else:sys.modules[name]=before


def completion_fixture(tmp_path,monkeypatch):
    from scripts.research.a2.training import consensus_fusion as fusion
    monkeypatch.setattr(inputs.existing,'REPO',tmp_path)
    def save(name,value):
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value));return inputs.file_ref(p)
    owner_refs={}
    for role,relative in (('ordinary_owner_ref','scripts/research/a2/data/reused_pair_ca_sources.py'),('ordinary_cash_owner_ref','scripts/research/a2/data/joint_cash_bindings.py'),('fx_parser_ref','scripts/research/a2/data/consensus_h10_fx_sources.py')):
        owner_refs[role]=save(relative,{})
    dates=pd.DatetimeIndex(['2025-06-02','2025-06-03'])
    raw=tmp_path/'extra.parquet';pd.DataFrame(dict(ticker=['TRP']*3,trade_date=[*dates,pd.Timestamp('2025-06-04')],open=[100.,101.,99999.],close=[101.,102.,99999.])).to_parquet(raw,index=False)
    identity_ref=save('identity.json',{'generated':True})
    entry=dict(role='HELD_RAW_SID_CONTINUATION',ticker='TRP',raw_security_id='FROZEN_RAW_TRANSPORT_CODE:US.TRP',new_CUSIP_assignment=False,
        new_buy_eligibility_upgrade=False,alpha_or_label_expansion=False,price_coordinate='RAW_ACTUAL_SHARE',
        source_identity_status='QUALIFIED_DATED_LEGAL_CLASS_AND_EXISTING_RAW_TRANSPORT',identity_available_at='2025-06-01T00:00:00Z',
        identity_source_refs=[identity_ref],price_ref=inputs.file_ref(raw),trade_dates=[str(d.date()) for d in dates])
    links=save('links.json',dict(schema='CONSENSUS_QUALIFIED_ADDITIONAL_RAW_PRICE_LINKS_R1',status='QUALIFIED_ACCOUNTING_RAW_KEYS_NO_POOL_OR_ALPHA_EXPANSION',entries=[entry]))
    manifest=dict(schema='CONSENSUS_SOURCE_COMPLETION_ACCOUNT_INPUT_MANIFEST_R1',task_id=inputs.TASK,research_id=fusion.CONTINUATION_RESEARCH_ID,
        status='QUALIFIED_SOURCE_FACTS_FOR_PRE2026_ACCOUNTING_ONLY',scope_start='2023-01-01',scope_end_exclusive='2026-01-01',strict_PIT=False,target_support_expansion=False,
        ordinary_bundle_ref=save('ordinary.json',{}),special_events_ref=save('special.json',{}),fx_source_book_ref=save('fx.json',{}),price_links_ref=links,source_refs=[identity_ref],**owner_refs)
    historical_ref=save('historical_parser.py',{})
    manifest['fx_source_validation_ref']=save('fx_validation.json',dict(schema='CONSENSUS_PRE2026_H10_CAD_SOURCE_CUSTODY_AMBIGUITY_SUPPLEMENT_R2',
        status='PASS_SOURCE_FACTS_ONLY_PENDING_ROOT_ACCOUNT_ADMISSION',book_ref=manifest['fx_source_book_ref'],current_parser_ref=manifest['fx_parser_ref'],
        exact_observation_match=True,duplicate_publication_observation_keys=0,selected_mark_order_invariant=True,
        current_source_guard_applied_to_actual_pre2026_CAD_only=True,test_2026_payload_read=False,
        historical_parser_custody=dict(original_ref=historical_ref,archived_ref=historical_ref)))
    ref=save('manifest.json',manifest);scope=dict(research_id=fusion.CONTINUATION_RESEARCH_ID,source_completion_manifest_ref=ref)
    def pin(r):assert inputs.sha256(r['path'])==r['sha256'];return Path(r['path'])
    def read(r):return json.loads(pin(r).read_text())
    return scope,manifest,entry,dates,pin,read,save


def test_completion_raw_metadata_then_exact_pre2026_numeric_projection(tmp_path,monkeypatch):
    scope,manifest,entry,dates,pin,read,_=completion_fixture(tmp_path,monkeypatch)
    projected=[];original=inputs.pq.read_table
    def selected(*args,**kwargs):
        projected.append(kwargs['filters']);return original(*args,**kwargs)
    monkeypatch.setattr(inputs.pq,'read_table',selected)
    bound=inputs.completion_metadata(scope,pin,read,dates)
    assert projected==[]
    frame=inputs.read_additional_prices(bound,pin)
    assert len(frame)==2 and frame.open.max()==101. and frame.trade_date.lt('2026-01-01').all()
    assert bound['price_links']['entries'][0]['new_CUSIP_assignment'] is False
    assert all(part[-1]==('trade_date','<',pd.Timestamp('2026-01-01')) for part in projected[0])


@pytest.mark.parametrize('bad',('future','buy','identity_late','unqualified'))
def test_completion_invalid_metadata_blocks_before_price_decode(tmp_path,monkeypatch,bad):
    scope,manifest,entry,dates,pin,read,save=completion_fixture(tmp_path,monkeypatch)
    if bad=='future':entry['trade_dates'].append('2026-01-02')
    elif bad=='buy':entry['new_buy_eligibility_upgrade']=True
    elif bad=='identity_late':entry['identity_available_at']='2025-06-02T15:00:00Z'
    else:entry['source_identity_status']='PENDING'
    manifest['price_links_ref']=save('links_bad.json',dict(schema='CONSENSUS_QUALIFIED_ADDITIONAL_RAW_PRICE_LINKS_R1',status='QUALIFIED_ACCOUNTING_RAW_KEYS_NO_POOL_OR_ALPHA_EXPANSION',entries=[entry]))
    scope['source_completion_manifest_ref']=save('manifest_bad.json',manifest)
    monkeypatch.setattr(inputs.pq,'read_table',lambda *a,**kw:pytest.fail('numeric decode before identity/date qualification'))
    with pytest.raises(ValueError):inputs.completion_metadata(scope,pin,read,dates)


def test_additional_quote_overlap_requires_equal_raw_values_and_preserves_keys():
    original=pd.DataFrame(dict(ticker=['TRP'],trade_date=pd.to_datetime(['2025-06-02']),open=[100.],close=[101.]))
    extra=pd.concat([original,original.assign(trade_date=pd.Timestamp('2025-06-03'))],ignore_index=True)
    merged=inputs.merge_raw_price_projections(original,extra)
    assert len(merged)==2
    extra.loc[0,'close']=102.
    with pytest.raises(ValueError,match='QUOTE_CONFLICT'):inputs.merge_raw_price_projections(original,extra)


def test_native_cash_completion_removes_only_exact_proved_record_and_keeps_old_source():
    ca=inputs.existing.ca
    event=ca.SourceBackedEntitlementEvent('cash','CASH_DIVIDEND','RAW:S','S','2025-06-03','2025-06-03','2025-06-04','2025-06-01T00:00:00Z',.2,'USD',ca.USD_PER_RAW_OLD_SHARE,ca.RAW_OLD_SHARE_COORDINATE,'TIER2_LOCAL_CANONICAL','generated','a'*64)
    solved=dict(ticker='S',effective_date='2025-06-03',reason='VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY')
    unsolved=dict(solved,reason='UNRELATED_SAME_DAY_SOURCE_GAP')
    binding=dict(manifest={},source_fingerprint='a'*64,security_tickers={'RAW:S':'S'})
    combined=dict(entitlement_events=(event,),unsupported_events=(solved,unsolved),entitlement_security_tickers={'RAW:S':'S'},entitlement_source_binding=binding,research_account_authority={})
    native=dict(events=dict(entitlement_events=(event,),unsupported_events=(unsolved,),entitlement_security_tickers={'RAW:S':'S'},entitlement_source_binding=dict(binding,manifest=dict(removed_exact_original_keys=[solved]))))
    result=inputs.merge_completion_descendant(combined,native,dict(path='D:/generated-manifest.json',sha256='b'*64))
    assert result['unsupported_events']==(unsolved,) and result['entitlement_events'][0].event_fingerprint==event.event_fingerprint
    assert combined['unsupported_events']==(solved,unsolved)
    assert result['entitlement_source_binding']['manifest']['original']=={}


def test_completion_mixed_physical_future_source_rejected_before_numeric_projection(tmp_path,monkeypatch):
    scope,manifest,entry,dates,pin,read,save=completion_fixture(tmp_path,monkeypatch)
    raw=tmp_path/'mixed.parquet';pd.DataFrame(dict(ticker=['TRP'],trade_date=[pd.Timestamp('2026-01-02')],open=[99999.],close=[99999.])).to_parquet(raw,index=False)
    entry['price_ref']=inputs.file_ref(raw)
    manifest['price_links_ref']=save('mixed_links.json',dict(schema='CONSENSUS_QUALIFIED_ADDITIONAL_RAW_PRICE_LINKS_R1',status='QUALIFIED_ACCOUNTING_RAW_KEYS_NO_POOL_OR_ALPHA_EXPANSION',entries=[entry]))
    scope['source_completion_manifest_ref']=save('mixed_manifest.json',manifest)
    monkeypatch.setattr(inputs.pq,'read_table',lambda *a,**kw:pytest.fail('mixed/future source decoded'))
    with pytest.raises(ValueError,match='Forbidden mixed/test input'):inputs.completion_metadata(scope,pin,read,dates)


def test_special_stock_source_replaces_only_exact_blocker_and_registers_child_raw_sid():
    from dataclasses import asdict
    ca=inputs.existing.ca
    event=ca.SourceBackedStockDistributionEvent('generated-stock','MULTI_SECURITY_STOCK_DISTRIBUTION','RAW:DHR','DHR','2023-10-02','2023-09-13','2023-09-01T00:00:00Z','LEGAL_CLASS:VLTO_COMMON','VLTO',1,3,'COMMON_SHARE','2023-10-02','2023-10-02',ca.RAW_OLD_SHARE_COORDINATE,'TIER2_LOCAL_CANONICAL','generated-only','a'*64,'Issuer cash-in-lieu retained; research beneficial fraction separate')
    solved=dict(ticker='DHR',effective_date='2023-10-02',reason='VENDOR_MULTI_SECURITY_TRANSFORM')
    unsolved=dict(solved,reason='INDEPENDENT_RAW_QUOTE_GAP')
    combined=dict(entitlement_events=(),unsupported_events=(solved,unsolved),entitlement_security_tickers={},entitlement_source_binding=dict(manifest={},source_fingerprint='b'*64))
    record=dict(type=type(event).__name__,terms=asdict(event),event_fingerprint=event.event_fingerprint)
    proof=dict(resolved_event_id=event.event_id,original_record=solved,vendor_price_factor_as_share_ratio=False,original_raw_price_coordinate_preserved=True)
    catalogue=dict(schema='CONSENSUS_QUALIFIED_SPECIAL_ACCOUNT_CATALOGUE_R1',status='QUALIFIED_SOURCE_FACTS_PRE2026_ACCOUNTING_ONLY',events=[record],resolved_unsupported_records=[proof])
    result=inputs.apply_special_completion(combined,catalogue,dict(path='D:/generated-special.json',sha256='c'*64))
    assert result['unsupported_events']==(unsolved,) and result['entitlement_events']==(event,)
    assert result['entitlement_security_tickers']=={'RAW:DHR':'DHR','LEGAL_CLASS:VLTO_COMMON':'VLTO'}
    assert combined['unsupported_events']==(solved,unsolved)
    changed=copy.deepcopy(catalogue);changed['resolved_unsupported_records'][0]['vendor_price_factor_as_share_ratio']=True
    with pytest.raises(ValueError,match='RESOLUTION_PROOF'):inputs.apply_special_completion(combined,changed,{})


def test_bn_official_split_replacement_preserves_old_record_and_binds_preopen_clock():
    from dataclasses import asdict
    ca=inputs.existing.ca
    old=ca.CorporateActionTransition('2025-10-10','FORWARD_SPLIT','RAW:BN','RAW:BN','BN','BN',1.4999925000374998,0.,'TIER3_VENDOR_METADATA','','',repair_authorized=False)
    new=ca.CorporateActionTransition('2025-10-10','FORWARD_SPLIT','RAW:BN','RAW:BN','BN','BN',1.5,0.,'TIER1_ISSUER_REGULATOR_EXCHANGE','generated-preex-original','a'*64)
    base=dict(entitlement_events=(),unsupported_events=(),entitlement_security_tickers={},entitlement_source_binding=dict(manifest={},source_fingerprint='b'*64),corporate_actions=(old,),corporate_action_known_at={})
    replacement=dict(original_event_fingerprint=old.event_fingerprint,terms=asdict(new),source_sha256='a'*64,price_ratio_inference=False,known_at='2025-08-07T13:00:00Z')
    catalogue=dict(schema='CONSENSUS_QUALIFIED_SPECIAL_ACCOUNT_CATALOGUE_R1',status='QUALIFIED_SOURCE_FACTS_PRE2026_ACCOUNTING_ONLY',events=[],resolved_unsupported_records=[],corporate_action_replacements=[replacement])
    result=inputs.apply_special_completion(base,catalogue,{})
    assert result['corporate_actions']==(new,) and base['corporate_actions']==(old,)
    assert result['corporate_action_known_at'][new.event_fingerprint]=='2025-08-07 13:00:00+00:00'
    replacement['known_at']='2025-10-10T15:00:00Z'
    with pytest.raises(ValueError,match='BEFORE_EFFECTIVE_OPEN'):inputs.apply_special_completion(base,catalogue,{})


def test_unvalidated_fx_source_book_cannot_enter_completion_before_price_decode(tmp_path,monkeypatch):
    scope,manifest,entry,dates,pin,read,save=completion_fixture(tmp_path,monkeypatch)
    proof=read(manifest['fx_source_validation_ref']);proof['current_parser_ref']=dict(proof['current_parser_ref'],sha256='f'*64)
    manifest['fx_source_validation_ref']=save('wrong_fx_validation.json',proof);scope['source_completion_manifest_ref']=save('wrong_fx_manifest.json',manifest)
    monkeypatch.setattr(inputs.pq,'read_table',lambda *a,**kw:pytest.fail('unvalidated FX/source escaped metadata gate'))
    with pytest.raises(ValueError,match='FX_SOURCE_AMBIGUITY'):inputs.completion_metadata(scope,pin,read,dates)


def test_exact_child_metadata_route_is_selected_before_source_projection(tmp_path,monkeypatch):
    child=tmp_path/'child';monkeypatch.setattr(inputs.account,'CHILD_RUN',child)
    calls=[]
    def check(ref,**kwargs):
        calls.append(kwargs)
        if kwargs.get('scope'):raise RuntimeError('route inspected before scan')
    monkeypatch.setattr(inputs.account,'_metadata_ref',check)
    with pytest.raises(RuntimeError,match='route inspected'):
        inputs.metadata_preflight(frozen_contract_ref=dict(path=str(child/'freeze.json'),sha256='a'*64),source_scope_ref=dict(path=str(child/'scope.json'),sha256='b'*64))
    assert calls==[dict(child=True),dict(scope=True,child=True)]


def test_bn_vendor_placeholder_requires_exact_existing_raw_identity_proof():
    from dataclasses import asdict
    ca=inputs.existing.ca
    old=ca.CorporateActionTransition('2025-10-10','OTHER_SHARE_COUNT_TRANSFORM','FROZEN_VENDOR:BN','FROZEN_VENDOR:BN','BN','BN',1.4999925000374998,0.,'TIER3_VENDOR_METADATA','','')
    new=ca.CorporateActionTransition('2025-10-10','FORWARD_SPLIT','FROZEN_RAW_TRANSPORT_CODE:US.BN','FROZEN_RAW_TRANSPORT_CODE:US.BN','BN','BN',1.5,0.,'TIER1_ISSUER_REGULATOR_EXCHANGE','generated-pre-ex-original','a'*64)
    base=dict(entitlement_events=(),unsupported_events=(),entitlement_security_tickers={},entitlement_source_binding=dict(manifest={},source_fingerprint='b'*64),corporate_actions=(old,),corporate_action_known_at={})
    replacement=dict(original_event_fingerprint=old.event_fingerprint,terms=asdict(new),source_sha256='a'*64,price_ratio_inference=False,known_at='2025-08-07T10:45:04Z',raw_identity_bridge_ref=dict(path='D:/generated-identity.json',sha256='c'*64))
    catalogue=dict(schema='CONSENSUS_QUALIFIED_SPECIAL_ACCOUNT_CATALOGUE_R1',status='QUALIFIED_SOURCE_FACTS_PRE2026_ACCOUNTING_ONLY',events=[],resolved_unsupported_records=[],corporate_action_replacements=[replacement])
    with pytest.raises(ValueError,match='PLACEHOLDER_REQUIRES'):inputs.apply_special_completion(base,catalogue,{})
    proof=dict(schema='CONSENSUS_BN_OFFICIAL_SPLIT_EXISTING_DATED_RAW_IDENTITY_BRIDGE_R1',status='PASS_EXISTING_EXACT_PRIOR_AND_EX_RAW_LINK_NO_CUSIP_EXPANSION',
        original_vendor_placeholder_sid=old.old_security_id,qualified_raw_accounting_sid=new.old_security_id,new_CUSIP_assignment=False,new_identity_interval_extension=False,
        exact_key_rows=[dict(signal_date=d,ticker='BN',accounting_sid=new.old_security_id) for d in ('2025-10-09','2025-10-10')])
    result=inputs.apply_special_completion(base,catalogue,{},source_pin=lambda ref:None,source_read=lambda ref:proof)
    assert result['corporate_actions']==(new,) and base['corporate_actions']==(old,)
    proof['new_CUSIP_assignment']=True
    with pytest.raises(ValueError,match='RAW_IDENTITY_BRIDGE'):inputs.apply_special_completion(base,catalogue,{},source_pin=lambda ref:None,source_read=lambda ref:proof)
