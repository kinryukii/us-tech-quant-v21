"""Synthetic-only PIT exposure gates. No original ratios, ranks or prices."""
import json
from types import SimpleNamespace
from pathlib import Path
import pandas as pd
import numpy as np
import pytest
from scripts.research.a2.training import stateful_pit_exposures as e


def industry_row(ticker='A',date='2023-12-29',sid='S1'):
 return dict(decision_date=pd.Timestamp(date),canonical_security_id=sid,ticker_at_date=ticker,cik=1,identity_status='AUTHORITATIVE',sic_available_at=pd.Timestamp('2022-01-05T21:00:00Z'),sic_accession='SYNTHETIC',sic_source_sha256='1'*64,taxonomy_name='PIT_AS_FILED_SEC_SIC_FF12_FF48',taxonomy_status='STRICT_PIT_SIC_FF12_FF48_MAPPED',mapping_reason='VERIFIED_SEC_HEADER_AND_OFFICIAL_FRENCH_RULES',ff48_code=1.,a2_rank=987654321)


def fundamental_row(ticker='A',accepted='2023-01-10T21:00:00Z',sid='S1',value=1.):
 at=pd.Timestamp(accepted);day=at.tz_convert('America/New_York').tz_localize(None).normalize()
 return dict(security_id=sid,ticker=ticker,cik=1,mapping_source='EXISTING_A2_SEC_CIK_BRIDGE',mapping_confidence='A_EXISTING_AUDITED',mapping_effective_date=pd.Timestamp('2021-01-06'),accession='SYNTHETIC_'+accepted,filed_date=day,accepted_datetime=at,feature_effective_date=day+pd.Timedelta(days=1),period_end_date=day-pd.Timedelta(days=30),lineage_hash='2'*64,source_sha256='3'*64,accepted_source_entry='SYNTHETIC_ONLY',accepted_source_sha256='4'*64,corporate_action_scale_consistent=True,coverage_status=True,amendment_status='ORIGINAL_FILING',concept_switch_status='NO_CONCEPT_SWITCH',**{x:float(value) for x in e.FUNDAMENTAL_COLUMNS})


def make_reader(tmp_path,monkeypatch,industry=None,fundamental=None):
 run=tmp_path/'run';run.mkdir();sources={}
 for kind,rows in [('industry',industry or [industry_row()]),('fundamental',fundamental or [fundamental_row()])]:
  p=tmp_path/(kind+'.parquet');pd.DataFrame(rows).to_parquet(p,index=False)
  sources[kind]=dict(path=str(p),sha256=e.sha(p),rows=len(rows))
 monkeypatch.setattr(e,'SOURCES',sources);monkeypatch.setattr(e,'resolve',lambda *a:SimpleNamespace(backtest_root=tmp_path));monkeypatch.setattr(e,'assert_write_path',lambda *a:None)
 # Synthetic publisher lives in cache and uses a local fixture writer only.
 monkeypatch.setattr(e,'write_json_atomic',lambda path,value:Path(path).write_text(json.dumps(value)))
 (run/'input_manifest.json').write_text(json.dumps({'conditional_metadata_sources':sources}))
 flags=pd.DataFrame({'signal_date':pd.to_datetime(['2022-12-29']*3),'ticker':['A','B','C']})
 return e.PITExposureReader(run,input_reader=SimpleNamespace(run=run,pred_flags=flags))


def test_metadata_batch_rejects_untyped_clock_before_any_body(tmp_path,monkeypatch):
 rows=[industry_row()];rows[0]['sic_available_at']='2022-01-05T21:00:00Z'
 body=[];monkeypatch.setattr(e.pd,'read_parquet',lambda *a,**k:body.append(True))
 with pytest.raises(ValueError,match='CLOCK_TYPE'):
  make_reader(tmp_path,monkeypatch,industry=rows)
 assert body==[]


def test_physical_future_boundary_rejected_before_any_body(tmp_path,monkeypatch):
 body=[];monkeypatch.setattr(e.pd,'read_parquet',lambda *a,**k:body.append(True))
 with pytest.raises(ValueError,match='PHYSICALLY_PRE2026'):
  make_reader(tmp_path,monkeypatch,industry=[industry_row(date='2026-01-02')])
 assert body==[]


def test_2023_temporal_gap_has_no_body_read_and_retains_unknown_assets(tmp_path,monkeypatch):
 reader=make_reader(tmp_path,monkeypatch);body=[]
 monkeypatch.setattr(e.pd,'read_parquet',lambda *a,**k:body.append(True))
 result=reader.read_annual('industry',2023,['A','B'])
 assert result.receipt['status']=='BLOCKED_SPECIFIC_TEMPORAL_COVERAGE'
 assert result.frame.shape==(2,48) and result.frame.isna().all().all() and body==[]
 assert result.receipt['fit_units']==0 and not result.frame.attrs['pit_qualified']


def test_prior_latest_row_only_and_no_rank_or_future_value_projection(tmp_path,monkeypatch):
 future=fundamental_row(accepted='2024-02-01T21:00:00Z',value=987654321.)
 reader=make_reader(tmp_path,monkeypatch,fundamental=[fundamental_row(value=.25),future])
 original=e.pd.read_parquet;calls=[]
 def projected(path,**kw):
  calls.append(kw);return original(path,**kw)
 monkeypatch.setattr(e.pd,'read_parquet',projected)
 result=reader.read_annual('fundamental',2024,['A','B'])
 assert result.frame.loc['A'].eq(.25).all() and result.frame.loc['B'].isna().all()
 assert all('a2_rank' not in c['columns'] for c in calls)
 assert all({x[0] for x in c['filters']}>=set(e.CLOCKS['fundamental']) for c in calls)
 assert result.frame.attrs['available_at']<pd.Timestamp('2024-01-01')
 assert result.receipt['missing_factor_cells']==24


@pytest.mark.parametrize('defect',['current_mapping','ambiguous_security'])
def test_mapping_defect_is_local_and_numeric_columns_are_never_read(tmp_path,monkeypatch,defect):
 row=fundamental_row();rows=[row]
 if defect=='current_mapping':row.update(mapping_source='SEC_COMPANY_TICKER_AND_NAME_EXACT',mapping_confidence='C_CURRENT_TICKER_NAME_EXACT')
 else:rows.append(fundamental_row(accepted='2022-12-01T21:00:00Z',sid='OTHER'))
 reader=make_reader(tmp_path,monkeypatch,fundamental=rows);original=e.pd.read_parquet;columns=[]
 def projected(path,**kw):columns.extend(kw['columns']);return original(path,**kw)
 monkeypatch.setattr(e.pd,'read_parquet',projected)
 result=reader.read_annual('fundamental',2024,['A'])
 assert result.frame.isna().all().all() and not result.qualification.metadata_pit_qualified.any()
 assert not set(columns)&set(e.FUNDAMENTAL_COLUMNS)


def test_industry_onehot_and_published_loader_restore_exact_pit_attrs(tmp_path,monkeypatch):
 reader=make_reader(tmp_path,monkeypatch)
 result=reader.read_annual('industry',2024,['A','B'])
 assert result.frame.loc['A'].sum()==1 and result.frame.loc['A','FF48_01']==1
 assert result.frame.loc['B'].isna().all()
 receipt=reader.publish(result);record=receipt['artifacts']['exposure']
 rp=Path(record['path']).with_name('receipt.json')
 pin=dict(producer_path=str(Path(e.__file__).resolve()),producer_sha256=e.sha(e.__file__),artifact_path=record['path'],artifact_sha256=record['sha256'],receipt_path=str(rp),receipt_sha256=e.sha(rp),source_id=receipt['source_id'],available_at=receipt['available_at'])
 restored=e.load_annual_projection(pin,pd.Timestamp('2024-01-01'))
 pd.testing.assert_frame_equal(restored,result.frame)
 assert restored.attrs['pit_qualified'] and not restored.attrs['asset_eligibility_upgraded']
 pin['available_at']='2024-01-01T00:00:00'
 with pytest.raises(ValueError,match='UNQUALIFIED_EXPOSURE'):
  e.load_annual_projection(pin,pd.Timestamp('2024-01-01'))


def test_future_membership_is_rejected_before_body(tmp_path,monkeypatch):
 reader=make_reader(tmp_path,monkeypatch);body=[]
 monkeypatch.setattr(e.pd,'read_parquet',lambda *a,**k:body.append(True))
 with pytest.raises(ValueError,match='FUTURE_MEMBERSHIP'):
  reader.read_annual('industry',2024,['NEVER_SEEN'])
 assert body==[]
