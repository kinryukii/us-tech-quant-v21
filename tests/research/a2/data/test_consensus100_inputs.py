"""Synthetic boundary checks; no real source/model/outcome imports on collection."""
import json
import pandas as pd
import pytest
from scripts.research.a2.data import consensus100_inputs as owner


def package(tmp_path, filing='14-NOV-2025', filename='01sep2025-30nov2025_form13f.zip'):
    label = '2025_sep_nov'
    meta = tmp_path / (label + '_meta.json')
    pd.DataFrame([dict(ACCESSION_NUMBER='a1', FILING_DATE=filing,
                       SUBMISSIONTYPE='13F-HR', CIK='123', PERIODOFREPORT='30-SEP-2025')]).to_parquet(tmp_path / (label + '_submission.parquet'), index=False)
    pd.DataFrame([dict(ACCESSION_NUMBER='a1', INFOTABLE_SK='row1', NAMEOFISSUER='Stock',
                       TITLEOFCLASS='COM', CUSIP='000000001', VALUE='5', SSHPRNAMT='2',
                       SSHPRNAMTTYPE='SH', PUTCALL='')]).to_parquet(tmp_path / (label + '_infotable.parquet'), index=False)
    meta.write_text(json.dumps(dict(label=label, filename=filename,
                    url='https://www.sec.gov/files/structureddata/data/form-13f-data-sets/'+filename,
                    submission_rows=1, infotable_rows=1)), encoding='utf-8')
    return meta


def test_future_mixed_package_is_excluded_before_parquet_open(tmp_path, monkeypatch):
    p=tmp_path/'2025dec_2026feb_meta.json'
    p.write_text(json.dumps(dict(filename='01dec2025-28feb2026_form13f.zip')), encoding='utf-8')
    monkeypatch.setattr(owner.pq, 'ParquetFile', lambda *a, **k: pytest.fail('future parquet opened'))
    receipt, rows=owner.qualify_package(p)
    assert receipt['status']=='EXCLUDED_FUTURE_OR_MIXED_PACKAGE' and rows==[]


def test_preflight_projects_only_clocks_then_full_accessor_is_predicated(tmp_path, monkeypatch):
    p=package(tmp_path)
    original=owner.pq.read_table
    calls=[]
    def spy(path, **kwargs):
        calls.append((str(path),kwargs))
        return original(path,**kwargs)
    monkeypatch.setattr(owner.pq,'read_table',spy)
    receipt,rows=owner.qualify_package(p)
    assert len(calls)==1 and calls[0][1]['columns']==owner.SUB_COLUMNS
    assert receipt['holding_payload_read'] is False and rows[0]['accepted_at'] is None
    frame=owner.read_qualified_holdings(receipt,['a1'])
    assert len(frame)==1 and calls[-1][1]['filters']==[('ACCESSION_NUMBER','in',['a1'])]
    with pytest.raises(ValueError,match='ACCESSION_OUTSIDE'):
        owner.read_qualified_holdings(receipt,['future-accession'])


def test_clock_outside_package_blocks_before_values(tmp_path, monkeypatch):
    p=package(tmp_path, filing='14-NOV-2026')
    original=owner.pq.read_table
    def spy(path, **kwargs):
        assert 'infotable' not in str(path)
        return original(path,**kwargs)
    monkeypatch.setattr(owner.pq,'read_table',spy)
    with pytest.raises(ValueError,match='FILING_CLOCK_OUTSIDE'):
        owner.qualify_package(p)


def test_custody_change_blocks_value_accessor(tmp_path):
    p=package(tmp_path)
    receipt,_=owner.qualify_package(p)
    Path=p.with_name('2025_sep_nov_infotable.parquet')
    with Path.open('ab') as handle:
        handle.write(b'changed')
    with pytest.raises(ValueError,match='SOURCE_CHANGED_AFTER'):
        owner.read_qualified_holdings(receipt,['a1'])


def test_snapshot_never_authorizes_2026_decisions():
    with pytest.raises(ValueError,match='PRE2026_DECISION_REQUIRED'):
        owner.rank_qualified_snapshot(None,None,None,quarter='2025Q3',snapshot_id='x',
               decision_at='2026-01-02T21:00:00Z',classify_equity=lambda *args:(True,'COM'))


def test_daily_membership_is_causal_and_does_not_backfill():
    def snapshot(cusip,date):
        return dict(members=pd.DataFrame([dict(snapshot_id=date,cusip=cusip,consensus_rank=1)]),
                    audit=dict(quarter='2025Q3',effective_at=date))
    data=owner.daily_membership([snapshot('old','2025-11-13T14:30:00Z'),
                                snapshot('new','2025-11-17T14:30:00Z')],
                               ['2025-11-12','2025-11-14','2025-11-17'])
    assert data.cusip.tolist()==['old','new']
    assert all(pd.Timestamp(a)<=pd.Timestamp(d) for a,d in zip(data.available_at,data.decision_at))
    with pytest.raises(ValueError,match='PRE2026_ORDERED_CALENDAR'):
        owner.daily_membership([snapshot('new','2025-11-17T14:30:00Z')],['2026-01-02'])


def test_initial_public_activation_excludes_filing_day_and_does_not_invent_acceptance():
    assert owner.initial_public_activation(['2025-11-13','2025-11-14'])==pd.Timestamp('2025-11-21T14:30:00Z')
    receipt=dict(metadata_status='COMPLETE', activation_at='2025-11-21T14:30:00Z',
                 initial_filings=[dict(filed_date='2025-11-14',accepted_at=None)])
    clock=owner.initial_public_clocks(receipt)[0]
    assert clock['accepted_at'] is None and clock['disclosure_available_by']=='2025-11-15T05:00:00+00:00'
    assert clock['amendments_handled'] is False


def test_existing_unit_parser_uses_actual_filing_date_and_never_drops_rows(tmp_path):
    from types import SimpleNamespace
    paths=SimpleNamespace(results_root=owner.resolve(owner.Path(__file__).resolve().parents[4]).results_root)
    parser,classifier,refs=owner.existing_filing_owners(paths)
    receipt,_=owner.qualify_package(package(tmp_path))
    raw=owner.read_qualified_holdings(receipt,['a1'])
    filing=dict(manager_id='m1',accession='a1',filed_date='2023-01-02')
    before=owner.normalize_public_rows(raw,filing,parser)
    after=owner.normalize_public_rows(raw,dict(filing,filed_date='2023-01-03'),parser)
    assert before.value_usd.tolist()==['5000.0'] and after.value_usd.tolist()==['5.0']
    assert classifier('Synthetic Corp','COM','SH','')[0] is True
    assert set(refs)=={'unit_parser','equity_classifier'}
    with pytest.raises(ValueError,match='ROWS_DROPPED'):
        owner.normalize_public_rows(raw.assign(VALUE='invalid'),filing,parser)


def test_metadata_projection_blocks_mixed_source_before_any_table_read(tmp_path,monkeypatch):
    p=tmp_path/'mixed.parquet'
    pd.DataFrame(dict(trade_date=pd.to_datetime(['2025-12-31','2026-01-02']),secret=[1,2])).to_parquet(p,index=False)
    pin=dict(path=str(p),sha256=owner.file_ref(p)['sha256'],rows=2)
    monkeypatch.setattr(owner.pq,'read_table',lambda *a,**k:pytest.fail('mixed payload read'))
    with pytest.raises(ValueError,match='Forbidden mixed/test input'):
        owner.physical_metadata_projection(pin,['trade_date'],'trade_date')


def test_full_synthetic_build_reuses_first_filings_and_preserves_unmapped_pool(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from scripts.research.a2.training import stateful_inputs
    paths=owner.resolve(owner.Path(__file__).resolve().parents[4])
    source=tmp_path/'source';source.mkdir()
    registry=tmp_path/'registry.csv';aliases=tmp_path/'aliases.csv'
    pd.DataFrame([dict(manager_id='m1',cik='123',enabled=True,active_from_quarter='2020Q1',
        active_to_quarter='',top_n=100,protected_top_n=20,manager_weight=1.0,required_for_gate=True)]).to_csv(registry,index=False)
    pd.DataFrame([dict(manager_id='m1',cik='123',valid_from_quarter='2020Q1',valid_to_quarter='')]).to_csv(aliases,index=False)
    for period in pd.period_range('2020Q1','2025Q3',freq='Q'):
        filing=period.end_time.normalize()+pd.Timedelta(days=45)
        label=str(filing.to_period('Q')).lower();accession=str(period)
        pd.DataFrame([dict(ACCESSION_NUMBER=accession,FILING_DATE=filing.strftime('%d-%b-%Y').upper(),
            SUBMISSIONTYPE='13F-HR',CIK='123',PERIODOFREPORT=period.end_time.strftime('%d-%b-%Y').upper())]).to_parquet(source/(label+'_submission.parquet'),index=False)
        pd.DataFrame([dict(ACCESSION_NUMBER=accession,INFOTABLE_SK='row1',NAMEOFISSUER='Synthetic Corp',
            TITLEOFCLASS='COM',CUSIP='000000001',VALUE='5',SSHPRNAMT='2',SSHPRNAMTTYPE='SH',PUTCALL='')]).to_parquet(source/(label+'_infotable.parquet'),index=False)
        filename=label+'_form13f.zip'
        (source/(label+'_meta.json')).write_text(json.dumps(dict(label=label,filename=filename,
            url='https://www.sec.gov/files/structureddata/data/form-13f-data-sets/'+filename,
            submission_rows=1,infotable_rows=1)),encoding='utf-8')
    receipt=owner.preflight_sources(registry,source,aliases)
    assert receipt['summary']['complete_quarters']==23
    dates=pd.to_datetime([pd.Timestamp(q['activation_at']).tz_convert('America/New_York').date() for q in receipt['quarters']])
    calendar=tmp_path/'calendar.parquet';identity=tmp_path/'identity.parquet'
    pd.DataFrame(dict(trade_date=dates)).to_parquet(calendar,index=False)
    ids=pd.DataFrame(dict(signal_date=dates,cusip='000000001',ticker='A',security_id='sid-A',security_id_type='TEST'))
    ids=pd.concat([ids,ids.iloc[:1].assign(ticker='CONFLICT')],ignore_index=True)
    ids.to_parquet(identity,index=False)
    for name,path,rows in [('calendar',calendar,len(dates)),('value_training_panel',identity,len(ids))]:
        monkeypatch.setitem(stateful_inputs.SOURCES,name,dict(path=str(path),sha256=owner.file_ref(path)['sha256'],rows=rows))
    monkeypatch.setattr(owner,'resolve',lambda *a,**k:SimpleNamespace(results_root=paths.results_root))
    monkeypatch.setattr(owner,'assert_safe_output_path',lambda *a,**k:None)
    run=tmp_path/owner.TASK/'synthetic_run';run.mkdir(parents=True)
    result=owner.materialize_inputs(run,receipt)
    day=pd.read_parquet(run/'derived/consensus100_daily.parquet')
    proof=json.loads((run/'derived/consensus100_inputs_proof.json').read_text(encoding='utf-8'))
    assert len(day)==23 and result['quarter_rows']==23 and result['unmapped_daily_rows']==1
    assert day.consensus_rank.eq(1).all() and day.cusip.eq('000000001').all()
    assert proof['summary']['market_prices_features_targets_read'] is False
    assert proof['summary']['conflicting_source_identity_keys']==1
    assert all(q['audit']['amendments_handled'] is False for q in proof['quarters'])
    assert {e['filing_form'] for q in proof['quarters'] for e in q['manager_evidence']}=={'13F-HR'}
    with pytest.raises(ValueError,match='EXISTING_CONSENSUS_INPUTS'):
        owner.materialize_inputs(run,receipt)
