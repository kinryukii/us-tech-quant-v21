"""Synthetic preservation/revision tests; never open real data or catalog."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

SOURCE = Path(__file__).parents[1] / 'scripts/storage/refresh_current_observations.py'
SPEC = importlib.util.spec_from_file_location('bounded_publication', SOURCE)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def write(path, rows):
    pq.write_table(pa.Table.from_pylist(rows), path)


def row(day, series='A', value=1, observed='2026-09-23T08:00:00Z', unit='PERCENT'):
    return {'date': day, 'series_id': series, 'value': value, 'units': unit,
            'observed_at_utc': observed, 'source_id': 'new' if observed.startswith('2026-09-23') else 'old'}


def test_keeps_all_old_keys_uses_new_overlap_and_preserves_row_lineage(tmp_path):
    old, new, output = [tmp_path/name for name in ('old.parquet','new.parquet','merged.parquet')]
    before = [row('2025-12-31', observed='2026-09-01T08:00:00Z'),
              row('2026-09-01', observed='2026-09-01T08:00:00Z'),
              row('2026-09-01', series='B', observed='2026-09-01T08:00:00Z')]
    incoming = [row('2026-09-01', value=7), row('2026-09-22', value=8)]
    write(old,before); write(new,incoming)
    old_hash, new_hash = module.sha(old), module.sha(new)
    result = module.merge_preserving_keys(old,new,output,['date','series_id'],'date')
    actual = {(r['date'],r['series_id']):r for r in pq.read_table(output).to_pylist()}
    assert len(actual)==4
    assert actual[('2025-12-31','A')]==before[0]
    assert actual[('2026-09-01','B')]==before[2]
    assert actual[('2026-09-01','A')]==incoming[0]
    assert result['overlap_keys_replaced']==1
    assert result['old_only_rows_retained']==2
    assert (module.sha(old),module.sha(new))==(old_hash,new_hash)


@pytest.mark.parametrize('change,error', [
    ({'unit':'USD'},'UNIT_OR_SERIES_CONVENTION_CHANGED'),
    ({'observed':'2026-08-01T08:00:00Z'},'NEW_VINTAGE_OLDER'),
    ({'observed':'2026-09-23T08:00:00'},'TIMEZONE_UNKNOWN'),
])
def test_rejects_changed_units_or_invalid_vintage(tmp_path,change,error):
    old,new,output=[tmp_path/name for name in ('old.parquet','new.parquet','merged.parquet')]
    write(old,[row('2026-09-01',observed='2026-09-01T08:00:00Z')])
    write(new,[row('2026-09-01',**change)])
    with pytest.raises(ValueError,match=error):
        module.merge_preserving_keys(old,new,output,['date','series_id'],'date')


@pytest.mark.parametrize('side', ['old','new'])
def test_rejects_duplicate_composite_keys_without_silent_dedup(tmp_path,side):
    old,new,output=[tmp_path/name for name in ('old.parquet','new.parquet','merged.parquet')]
    rows=[row('2026-09-01')]
    write(old,rows*2 if side=='old' else rows)
    write(new,rows*2 if side=='new' else rows)
    with pytest.raises(ValueError,match='DUPLICATE_COMPOSITE_KEY'):
        module.merge_preserving_keys(old,new,output,['date','series_id'],'date')


def test_schema_change_stops_before_publication(tmp_path):
    old,new,output=[tmp_path/name for name in ('old.parquet','new.parquet','merged.parquet')]
    write(old,[row('2026-09-01')])
    write(new,[{**row('2026-09-22'),'unknown_new_field':1}])
    with pytest.raises(ValueError,match='SCHEMA_CHANGED'):
        module.merge_preserving_keys(old,new,output,['date','series_id'],'date')


def test_streaming_merge_keeps_order_when_old_only_symbol_is_inside_revised_dates(tmp_path,monkeypatch):
    monkeypatch.setattr(module,'STREAMING_KEY_THRESHOLD',1)
    old,new,output=[tmp_path/name for name in ('old.parquet','new.parquet','merged.parquet')]
    def finra(day,symbol,observed):
        return {'date':day,'provider_symbol':symbol,'value':1,'observed_at_utc':observed}
    write(old,[finra(day,symbol,'2026-09-01T08:00:00Z') for day,symbol in
               [('2026-08-28','A'),('2026-08-31','A'),('2026-08-31','B'),('2026-09-01','A')]])
    write(new,[finra(day,'A','2026-09-23T08:00:00Z') for day in ['2026-08-31','2026-09-22']])
    result=module.merge_preserving_keys(old,new,output,['date','provider_symbol'],'date')
    keys=module.key_values(pq.read_table(output),['date','provider_symbol'])
    assert keys==sorted(keys)
    assert ('2026-08-31','B') in keys
    assert result['row_count']==5


class Store:
    def metadata(self,dataset):
        return {'max_date':'2026-09-22' if dataset.startswith('finra') else '2026-09-18'}


def test_future_jobs_reuse_existing_adapters_with_incremental_finra_and_current_bls(tmp_path):
    paths=SimpleNamespace(results_root=tmp_path/'results',repo_root=tmp_path/'repo',cache_root=tmp_path/'cache')
    jobs=dict(module.current_source_jobs(paths,'daily_next','2026-09-23','2026-09-22',Store()))
    assert len(jobs)==8
    finra=jobs['scripts.storage.refresh_official_research_data']
    assert finra[finra.index('--finra-start')+1]=='2026-09-20'
    assert '--register' not in finra
    bls=jobs['scripts.storage.refresh_bls_observations']
    assert bls[bls.index('--start-year')+1]=='2026'
    public=jobs['scripts.storage.refresh_public_sources']
    assert Path(public[public.index('--work-root')+1]).is_relative_to(paths.cache_root)
    assert 'bls' not in public


def test_year_boundary_keeps_latest_published_previous_year_observations(tmp_path):
    paths=SimpleNamespace(results_root=tmp_path/'results',repo_root=tmp_path/'repo',cache_root=tmp_path/'cache')
    jobs=dict(module.current_source_jobs(paths,'new_year','2027-01-01','2026-12-31',Store()))
    treasury=jobs['scripts.storage.refresh_official_research_data']
    assert treasury[treasury.index('--first-year')+1]=='2026'
    assert treasury[treasury.index('--last-year')+1]=='2026'
    bls=jobs['scripts.storage.refresh_bls_observations']
    assert bls[bls.index('--start-year')+1]=='2026'


def test_future_coordinator_publishes_only_successful_receipts_and_records_missing_sources(tmp_path,monkeypatch):
    paths=SimpleNamespace(results_root=tmp_path/'results',repo_root=tmp_path/'repo',cache_root=tmp_path/'cache')
    monkeypatch.setattr(module,'DataStore',lambda paths=None:Store())
    captured={}
    def fake_publish(path,run_id,provided_paths):
        captured.update(module.load(path))
        return {'registered_datasets':1,'results':[]}
    monkeypatch.setattr(module,'publish_verified_report',fake_publish)
    def runner(name,args,log):
        if name=='scripts.storage.refresh_public_sources':
            target=Path(args[args.index('--work-root')+1])/'synthetic/acquisition_report.json'
            module.save_new(target,{'results':[{'status':'SUCCESS','dataset':'vix_cboe_daily',
                'source':'CBOE_OFFICIAL','output':{'path':str(tmp_path/'synthetic.parquet'),'sha256':'synthetic'}}]})
        # Exit zero alone must never turn absent/failed data into published data.
        return {'module':name,'exit_code':0}
    result=module.run_current_sources(paths,'DAILY_NEXT','2026-09-23','2026-09-22',runner=runner)
    assert result['status']=='PARTIAL'
    assert len(captured['jobs'])==8
    assert len(captured['sources'])==21
    assert sum(row['status']=='SUCCESS' for row in captured['sources'])==1
    assert sum(row['status']=='ACQUISITION_NOT_VALIDATED' for row in captured['sources'])==20
    with pytest.raises(ValueError,match='UNIQUE_ID'):
        module.run_current_sources(paths,'DAILY_NEXT','2026-09-23','2026-09-22',runner=runner)
