"""Synthetic-only tests of the source-based general quote-mask rule."""
from copy import deepcopy
import numpy as np
import pytest
from scripts.research.a2.training import stateful_research_quote_domain as rule


def evidence(ticker='UNHELD_SYNTHETIC', day='2024-06-03'):
    return dict(ticker=ticker, date=day, masked=True, inherited_event_mask=True,
                coordinate='RAW_ACTUAL_SHARE', independent_quality_flags=[],
                raw_rows=[dict(ticker=ticker, date=day, code='CODE', open=10., close=11.)],
                code_tickers={'CODE': [ticker]},
                identity_records=[dict(sid='SID', ticker=ticker, start='2023-01-01',
                                       end='2026-01-01', coordinate='RAW_ACTUAL_SHARE')],
                mechanisms=[dict(ticker=ticker, date=day, mask_origin='INHERITED_UNSUPPORTED_EVENT',
                                 reason='UNSUPPORTED_ACCOUNTING_EVENT', source_fingerprint='a'*64,
                                 source_reference='synthetic-source')], terminal_contracts=[])


def test_unheld_non_cash_key_is_admitted_by_general_source_rule():
    r=rule.classify_quote_key(evidence())
    assert r['classification']=='A' and r['clear_inherited_event_mask'] is True
    assert r['classification_name']==rule.CLASSES['A']
    assert r['mechanisms']==r['evidence']['mechanisms']


@pytest.mark.parametrize('field,value', [('open',None),('close',None),('open',float('nan')),
                                        ('close',float('inf')),('open','10')])
def test_nonfinite_raw_is_b_even_with_legal_cash_context(field,value):
    x=evidence();x['raw_rows'][0][field]=value;x['cash_accounting_qualified']=True
    r=rule.classify_quote_key(x)
    assert r['classification']=='B' and not r['clear_inherited_event_mask']


def test_missing_raw_is_b_with_unique_identity():
    x=evidence();x['raw_rows']=[]
    assert rule.classify_quote_key(x)['classification']=='B'


@pytest.mark.parametrize('field,value', [('open',0.),('close',-1.)])
def test_nonpositive_quote_is_retained_as_d(field,value):
    x=evidence();x['raw_rows'][0][field]=value
    r=rule.classify_quote_key(x)
    assert r['classification']=='D' and 'RAW_'+field.upper()+'_NONPOSITIVE' in r['blocking_flags']


@pytest.mark.parametrize('kind', ['missing','overlap','coordinate','code','ticker_key'])
def test_identity_ambiguity_is_c(kind):
    x=evidence()
    if kind=='missing':x['identity_records']=[]
    elif kind=='overlap':x['identity_records'] += [dict(x['identity_records'][0],sid='OTHER')]
    elif kind=='coordinate':x['identity_records'][0]['coordinate']='ADJUSTED_INDEX_UNITS'
    elif kind=='code':x['code_tickers']['CODE'] += ['OTHER_TICKER']
    else:x['raw_rows'][0]['ticker']='OTHER_TICKER'
    assert rule.classify_quote_key(x)['classification']=='C'


def test_identity_interval_is_half_open():
    x=evidence(day='2024-06-03');x['identity_records'][0]['end']='2024-06-03'
    assert rule.classify_quote_key(x)['classification']=='C'


def test_duplicate_raw_row_is_never_a():
    x=evidence();x['raw_rows'] += deepcopy(x['raw_rows'])
    r=rule.classify_quote_key(x)
    assert r['classification']=='D' and 'RAW_ROW_NOT_UNIQUE' in r['blocking_flags']


def test_independent_quality_does_not_disappear_under_cash_qualification():
    x=evidence();x['independent_quality_flags']=['SOURCE_RAW_DEFECT'];x['cash_accounting_qualified']=True
    r=rule.classify_quote_key(x)
    assert r['classification']=='D' and 'INDEPENDENT_QUALITY:SOURCE_RAW_DEFECT' in r['reason_flags']


def test_all_blocking_reasons_survive_primary_classification():
    x=evidence();x['raw_rows'][0]['open']=None;x['identity_records']=[]
    x['independent_quality_flags']=['HALT'];r=rule.classify_quote_key(x)
    assert r['classification']=='C'
    assert {'RAW_OPEN_NONFINITE','DATED_SECURITY_BINDING_NOT_UNIQUE','INDEPENDENT_QUALITY:HALT'} <= set(r['blocking_flags'])


def test_terminal_same_sid_priority_over_other_failures():
    x=evidence(ticker='MKFG');x['raw_rows'][0]['open']=None
    x['terminal_contracts']=[dict(sid='SID',ticker='MKFG',nontradable_from='2024-06-03')]
    r=rule.classify_quote_key(x)
    assert r['classification']=='E' and not r['clear_inherited_event_mask']
    assert 'RAW_OPEN_NONFINITE' in r['blocking_flags']


def test_terminal_other_sid_does_not_close_current_identity():
    x=evidence();x['terminal_contracts']=[dict(sid='OTHER',ticker=x['ticker'],nontradable_from='2023-01-01')]
    assert rule.classify_quote_key(x)['classification']=='A'


def test_unmasked_catalogue_context_never_clears_quality():
    x=evidence();x['masked']=x['inherited_event_mask']=False
    assert rule.classify_quote_key(x)['classification']=='D'


@pytest.mark.parametrize('field', ['independent_quality_flags','raw_rows','identity_records','terminal_contracts'])
def test_incomplete_evidence_fails_closed(field):
    x=evidence();del x[field]
    with pytest.raises(ValueError,match='EVIDENCE_INCOMPLETE'):rule.classify_quote_key(x)


@pytest.mark.parametrize('day', ['2022-12-31','2026-01-01','2027-01-01'])
def test_pre2026_window_is_enforced(day):
    with pytest.raises(ValueError,match='OUTSIDE_FROZEN_WINDOW'):rule.classify_quote_key(evidence(day=day))


def test_population_preserves_every_source_reason_and_order():
    x=evidence();x['mechanisms'] += [dict(x['mechanisms'][0],reason='SECOND_MECHANISM',source_fingerprint='b'*64)]
    y=evidence(ticker='ANOTHER');r=rule.classify_population([x,y])
    assert [z['key']['ticker'] for z in r]==['ANOTHER','UNHELD_SYNTHETIC']
    assert len(r[1]['mechanisms'])==2 and 'MECHANISM_REASON:SECOND_MECHANISM' in r[1]['reason_flags']
    with pytest.raises(ValueError,match='DUPLICATE'):rule.classify_population([x,x])


def test_apply_clears_only_inherited_a_and_preserves_base_quality():
    a=rule.classify_quote_key(evidence());b=evidence(ticker='BLOCKED');b['raw_rows'][0]['close']=None
    decisions=[a,rule.classify_quote_key(b)]
    base=np.array([[True,False]],bool);inherited=np.ones((1,2),bool)
    quality,audit=rule.apply_quote_domain(base,inherited,['2024-06-03'],['UNHELD_SYNTHETIC','BLOCKED'],decisions)
    assert quality.tolist()==[[True,True]] and inherited.all() and base.tolist()==[[True,False]]
    assert audit['cleared_inherited_keys']==[a['key']]
    assert audit['accounting_records_changed'] is False and audit['nav_comparator_changed'] is False


def test_apply_a_clear_general_population_without_holdings_or_returns():
    records=[evidence(ticker=x) for x in ['A_NEW','B_NEW','C_NEW']]
    decisions=rule.classify_population(records)
    q,audit=rule.apply_quote_domain(np.zeros((1,3),bool),np.ones((1,3),bool),['2024-06-03'],['A_NEW','B_NEW','C_NEW'],decisions)
    assert not q.any() and len(audit['cleared_inherited_keys'])==3 and audit['returns_used'] is False


def test_forged_caller_verified_or_clear_flag_cannot_change_classification():
    x=evidence();x['raw_rows'][0]['open']=None;x['verified']=True
    decision=rule.classify_quote_key(x);decision['classification']='A';decision['clear_inherited_event_mask']=True
    with pytest.raises(ValueError,match='NOT_DERIVED'):rule.apply_quote_domain(np.zeros((1,1),bool),np.ones((1,1),bool),['2024-06-03'],[x['ticker']],[decision])


def test_already_removed_inherited_component_is_audited_without_clear():
    x=rule.classify_quote_key(evidence())
    q,audit=rule.apply_quote_domain(np.ones((1,1),bool),np.zeros((1,1),bool),['2024-06-03'],[x['key']['ticker']],[x])
    assert q.all() and audit['already_absent_inherited_keys']==[x['key']]
    assert audit['cleared_inherited_keys']==[]


def test_outside_runtime_key_is_counted_not_silently_lost():
    x=rule.classify_quote_key(evidence())
    q,audit=rule.apply_quote_domain(np.zeros((1,1),bool),np.zeros((1,1),bool),['2024-06-03'],['DIFFERENT'],[x])
    assert not q.any() and audit['outside_runtime_keys']==[x['key']]


def test_numeric_combined_masks_are_not_accepted():
    with pytest.raises(ValueError,match='SEPARATE_BOOLEAN'):rule.apply_quote_domain(np.zeros((1,1)),np.ones((1,1),bool),['2024-06-03'],['X'],[])

def test_additional_inherited_exception_not_in_census_is_preserved():
    d=rule.classify_quote_key(evidence())
    q,a=rule.apply_quote_domain(np.zeros((1,2),bool),np.ones((1,2),bool),['2024-06-03'],[d['key']['ticker'],'EXTRA'],[d])
    assert q.tolist()==[[False,True]] and a['independent_quality_preserved']


@pytest.fixture
def frozen_ref(tmp_path,monkeypatch):
    import hashlib,json
    from pathlib import Path
    from types import SimpleNamespace
    import pandas as pd
    from scripts.common import storage_paths
    roots=SimpleNamespace(repo_root=Path(rule.__file__).resolve().parents[4],results_root=tmp_path/'results',
                          backtest_root=tmp_path/'backtests',data_root=tmp_path/'data',cache_root=tmp_path)
    monkeypatch.setattr(storage_paths,'resolve',lambda *a,**k:roots)
    def ref(path):return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    def write(path,data):path.write_text(json.dumps(data,sort_keys=True),encoding='utf-8');return ref(path)
    raw=tmp_path/'raw.parquet';pd.DataFrame({'trade_date':pd.to_datetime(['2024-06-03'])}).to_parquet(raw)
    audit=tmp_path/'audit.parquet';pd.DataFrame({'event_date':pd.to_datetime(['2024-06-03'])}).to_parquet(audit)
    src={'raw_quotes':dict(ref(raw),clock_column='trade_date'),
         'event_mechanism_source':dict(ref(audit),clock_column='event_date')}
    for role in ['security_mapping','cash_catalogue','human_authorization','raw_quote_coordinate_proof']:
        src[role]=write(tmp_path/(role+'.json'),{'synthetic':True})
    population=dict(schema='QUOTE_MASK_POPULATION_CENSUS_R1',task_id=rule.TASK_ID,
                    source_refs=src,masked_key_count=1,decisions=rule.classify_population([evidence()]))
    pp=tmp_path/'population.json';pr=write(pp,population)
    module=Path(rule.__file__).resolve()
    payload=dict(schema='FROZEN_RESEARCH_QUOTE_DOMAIN_R1',status='FROZEN_BEFORE_ACCOUNT_ATTEMPT',
                 task_id=rule.TASK_ID,namespace=rule.NAMESPACE,rule_definition=rule.RULE_DEFINITION,
                 strict_PIT_promotion_eligible=False,production_qualified=False,certified_market_data=False,certified_market_quote_authority=False,
                 module_ref=ref(module),source_refs=src,source_pins={str(module):ref(module)['sha256']},population_ref=pr)
    fp=tmp_path/'freeze.json';fr=write(fp,payload)
    return fr,payload,population,write,fp,pp


def test_loader_verifies_physical_freeze_population_and_all_sources(frozen_ref):
    ref,*_=frozen_ref
    payload=rule.load_frozen_domain(ref)
    assert payload['decisions'][0]['classification']=='A'
    assert payload['namespace']=='FROZEN_HISTORY_RESEARCH_QUOTE_DOMAIN'


@pytest.mark.parametrize('change', ['module','promotion','namespace','rule','population','source'])
def test_loader_rejects_tampering_even_with_caller_rehashed_freeze(frozen_ref,change):
    ref,payload,pop,write,fp,pp=frozen_ref
    if change=='module':payload['module_ref']=payload['source_refs']['human_authorization']
    elif change=='promotion':payload['production_qualified']=True
    elif change=='namespace':payload['namespace']+='OTHER'
    elif change=='rule':payload['rule_definition']=dict(payload['rule_definition'],outcome_or_holding_conditioned=True)
    elif change=='population':
        pop['decisions'][0]['clear_inherited_event_mask']=False
        payload['population_ref']=write(pp,pop)
    else:
        from pathlib import Path
        Path(payload['source_refs']['human_authorization']['path']).write_text('changed',encoding='utf-8')
    ref=write(fp,payload)
    with pytest.raises(ValueError):rule.load_frozen_domain(ref)


def test_forbidden_drive_rejected_before_file_access():
    with pytest.raises(ValueError,match='FORBIDDEN_DRIVE'):
        rule.load_frozen_domain({'path':'E:/forbidden/source.json','sha256':'a'*64})

def test_same_sid_overlapping_other_ticker_is_c():
    x=evidence();x['identity_records'].append(dict(x['identity_records'][0],ticker='OTHER'))
    r=rule.classify_quote_key(x)
    assert r['classification']=='C'
    assert 'DATED_SECURITY_REVERSE_BINDING_NOT_UNIQUE' in r['blocking_flags']


def test_same_sid_nonoverlapping_other_ticker_is_not_ambiguous():
    x=evidence();x['identity_records'].append(dict(x['identity_records'][0],ticker='OTHER',start='2020-01-01',end='2023-01-01'))
    assert rule.classify_quote_key(x)['classification']=='A'
