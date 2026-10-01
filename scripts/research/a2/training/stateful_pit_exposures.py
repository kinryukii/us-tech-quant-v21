"""Annual pre-cutoff PIT exposures; existing factors only, no fitting or backfill.

The frozen input manifest owns source identity. This adapter adds only strict
as-of clocks, local mapping qualification, FF48 one-hot encoding and projection.
It never reads ranks, labels, forecasts, returns or economic reports.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib,json,re
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from scripts.common.storage_paths import resolve
from scripts.storage.storage_r2a import assert_write_path,write_json_atomic

REPO=Path(__file__).resolve().parents[4]
BOUNDARY=pd.Timestamp('2026-01-01')
SOURCES={
 'industry':{'path':'D:/us-tech-quant-results/A2_FREE_PIT_SECURITY_IDENTITY_SIC_FF48_AND_FACTOR_RISK_FOUNDATION_R1/pit_sec_sic_ff12_ff48_eligible_surface.parquet','sha256':'591ecea001bf1f0b1b6ef7059a65b7e6efd45890befa149c0377d45b6aad6646','rows':313668},
 'fundamental':{'path':'D:/us-tech-quant-results/A2_PIT_SEC_FUNDAMENTAL_ACCELERATION_ALPHA_R1/fundamental_feature_ledger.parquet','sha256':'2789c80596e9758c7a984529f034a389594aa6aa7cbf9d88bc99c8cd9c933aef','rows':31687}}
FUNDAMENTAL_COLUMNS=tuple('revenue_yoy revenue_yoy_change_vs_prior_filing revenue_growth_acceleration gross_margin gross_margin_yoy_change operating_margin operating_margin_yoy_change net_margin net_margin_yoy_change operating_cash_flow_margin operating_cash_flow_margin_change free_cash_flow_margin free_cash_flow_margin_change cfo_to_net_income accrual_quality asset_growth_yoy rd_to_revenue rd_intensity_change sbc_to_revenue sbc_intensity_change filing_lag_days amendment_indicator concept_switch_indicator fact_coverage_ratio'.split())
FACTORS={'industry':tuple(f'FF48_{i:02d}' for i in range(1,49)),'fundamental':FUNDAMENTAL_COLUMNS}
META={
 'industry':tuple('decision_date canonical_security_id ticker_at_date cik identity_status sic_available_at sic_accession sic_source_sha256 taxonomy_name taxonomy_status mapping_reason'.split()),
 'fundamental':tuple('security_id ticker cik mapping_source mapping_confidence mapping_effective_date accession filed_date accepted_datetime feature_effective_date period_end_date lineage_hash source_sha256 accepted_source_entry accepted_source_sha256 corporate_action_scale_consistent coverage_status amendment_status concept_switch_status'.split())}
CLOCKS={'industry':{'decision_date':None,'sic_available_at':'UTC'},'fundamental':{'mapping_effective_date':None,'filed_date':None,'accepted_datetime':'UTC','feature_effective_date':None,'period_end_date':None}}
PRIMARY={'industry':'decision_date','fundamental':'feature_effective_date'}
TICKER={'industry':'ticker_at_date','fundamental':'ticker'}
SECURITY={'industry':'canonical_security_id','fundamental':'security_id'}
KEYS={'industry':['decision_date','canonical_security_id','ticker_at_date'],'fundamental':['security_id','ticker','feature_effective_date','accepted_datetime','accession']}
MAPPING_PAIRS={('EXISTING_A2_SEC_CIK_BRIDGE','A_EXISTING_AUDITED'),('SEC_SUBMISSION_LEGAL_NAME_EXACT_UNIQUE','B_HISTORICAL_EXACT_NAME')}
_HASHED={}


def sha(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def _fingerprint(path):
 st=Path(path).stat();return {'size':st.st_size,'mtime_ns':st.st_mtime_ns}


def _date_bound(cutoff,tz):
 return cutoff.tz_localize('America/New_York').tz_convert('UTC').to_pydatetime() if tz else cutoff.to_pydatetime()


def _local_time(values,tz):
 parsed=pd.to_datetime(values,utc=bool(tz),errors='raise')
 return parsed.dt.tz_convert('America/New_York').dt.tz_localize(None) if tz else parsed


def prepare_exposure_sources(run_dir):
 """Both SHA/schema/footer/typed clock gates precede any table-body projection."""
 run=Path(run_dir).resolve();paths=resolve(REPO)
 if not run.is_relative_to(paths.backtest_root.resolve()) or not run.is_dir():raise ValueError('EXPOSURE_RUN_NOT_EXISTING_BACKTEST_ROOT')
 manifest_path=run/'input_manifest.json';manifest=json.loads(manifest_path.read_text(encoding='utf-8-sig'))
 records={}
 for kind,pin in SOURCES.items():
  declared=manifest.get('conditional_metadata_sources',{}).get(kind,{})
  if any(declared.get(k)!=pin[k] for k in ('path','sha256')):raise ValueError('EXPOSURE_SOURCE_NOT_FROZEN_INPUT_MANIFEST:'+kind)
  path=Path(pin['path']);fingerprint=_fingerprint(path);key=(str(path.resolve()),pin['sha256'])
  if key in _HASHED and _HASHED[key]!=fingerprint:raise ValueError('EXPOSURE_SOURCE_CHANGED_AFTER_VERIFICATION')
  if key not in _HASHED:
   if sha(path)!=pin['sha256']:raise ValueError('EXPOSURE_SOURCE_HASH_CHANGED:'+kind)
   _HASHED[key]=fingerprint
  pf=pq.ParquetFile(path);schema=pf.schema_arrow;numeric=['ff48_code'] if kind=='industry' else list(FUNDAMENTAL_COLUMNS)
  if not set(META[kind]+tuple(numeric)).issubset(schema.names) or pf.metadata.num_rows!=pin['rows']:raise ValueError('EXPOSURE_SCHEMA_OR_ROWS:'+kind)
  for name in numeric:
   if not pa.types.is_floating(schema.field(name).type):raise ValueError('EXPOSURE_NUMERIC_TYPE:'+name)
  for name in META[kind]:
   if name in CLOCKS[kind] or name=='cik' or name in ('corporate_action_scale_consistent','coverage_status'):continue
   typ=schema.field(name).type
   if not (pa.types.is_string(typ) or pa.types.is_large_string(typ)):raise ValueError('EXPOSURE_METADATA_TYPE:'+name)
  if not pa.types.is_integer(schema.field('cik').type):raise ValueError('EXPOSURE_CIK_TYPE')
  if kind=='fundamental' and any(not pa.types.is_boolean(schema.field(n).type) for n in ('corporate_action_scale_consistent','coverage_status')):raise ValueError('EXPOSURE_FLAG_TYPE')
  ranges={}
  for name,tz in CLOCKS[kind].items():
   typ=schema.field(name).type
   if not pa.types.is_timestamp(typ) or typ.tz!=tz:raise ValueError('EXPOSURE_CLOCK_TYPE:'+name)
   entries=[]
   for i in range(pf.num_row_groups):
    st=pf.metadata.row_group(i).column(schema.names.index(name)).statistics
    if st is None or not st.has_min_max:raise ValueError('EXPOSURE_CLOCK_FOOTER_MISSING:'+name)
    limit=BOUNDARY.tz_localize('UTC') if tz else BOUNDARY
    if pd.Timestamp(st.max)>=limit:raise ValueError('EXPOSURE_NOT_PHYSICALLY_PRE2026:'+name)
    entries.append({'min':str(st.min),'max':str(st.max),'nulls':st.null_count})
   ranges[name]=entries
  records[kind]={**pin,'file_fingerprint':fingerprint,'hash_verified':True,'clock_types':CLOCKS[kind],'clock_ranges':ranges,'schema':schema.names}
 return {'status':'SOURCE_METADATA_QUALIFIED','source_module_sha256':sha(__file__),'input_manifest_sha256':sha(manifest_path),'sources':records,'table_body_read':False,'fit_units':0,'test_2026_rows_read':0}


@dataclass
class ExposureResult:
 frame:pd.DataFrame
 qualification:pd.DataFrame
 receipt:dict


class PITExposureReader:
 def __init__(self,run_dir,*,input_reader):
  self.run=Path(run_dir).resolve();self.source_receipt=prepare_exposure_sources(self.run)
  if Path(input_reader.run).resolve()!=self.run:raise ValueError('EXPOSURE_INPUT_READER_OTHER_RUN')
  self.input_reader=input_reader

 def _project(self,kind,year,assets,columns,extra=()):
  record=self.source_receipt['sources'][kind];path=Path(record['path'])
  if _fingerprint(path)!=record['file_fingerprint']:raise ValueError('EXPOSURE_SOURCE_CHANGED_BEFORE_READ')
  cut=pd.Timestamp(f'{year}-01-01')
  # No body is needed when the footer proves no prior primary-clock row.
  if all(pd.Timestamp(r['min'])>=cut for r in record['clock_ranges'][PRIMARY[kind]]):return pd.DataFrame(columns=columns)
  filters=[(name,'<',_date_bound(cut,tz)) for name,tz in CLOCKS[kind].items()]
  filters+=[(TICKER[kind],'in',list(assets)),*extra]
  out=pd.read_parquet(path,columns=list(columns),filters=filters)
  if _fingerprint(path)!=record['file_fingerprint']:raise ValueError('EXPOSURE_SOURCE_CHANGED_DURING_READ')
  # Secondary assertions verify the projected relation, never replace predicates.
  for name,tz in CLOCKS[kind].items():
   if name in out and not out.empty:
    local=_local_time(out[name],tz)
    if local.isna().any() or not local.lt(cut).all():raise ValueError('EXPOSURE_PROJECTED_CLOCK_NOT_PAST:'+name)
  return out

 def read_annual(self,kind,year,assets):
  if kind not in SOURCES or year not in (2023,2024,2025):raise ValueError('UNREGISTERED_EXPOSURE_KIND_OR_YEAR')
  names=list(assets)
  if not names or any(not isinstance(x,str) or not x for x in names) or len(set(names))!=len(names):raise ValueError('EXPOSURE_UNIQUE_EXACT_ASSET_KEYS_REQUIRED')
  cut=pd.Timestamp(f'{year}-01-01');flags=self.input_reader.pred_flags
  history=set(flags.loc[pd.to_datetime(flags.signal_date).lt(cut),'ticker'].astype(str))
  if not set(names).issubset(history):raise ValueError('EXPOSURE_ASSETS_HAVE_FUTURE_MEMBERSHIP_OR_UNKNOWN_HISTORY')
  meta=self._project(kind,year,names,META[kind]);idcol=SECURITY[kind];tickercol=TICKER[kind]
  chosen=[];qualification=[]
  for asset in names:
   rows=meta.loc[meta[tickercol].eq(asset)].copy();reason='';last=None;available=pd.NaT
   if rows.empty:reason='NO_PRIOR_ROW_WITH_ALL_TYPED_CLOCKS'
   elif rows[idcol].isna().any() or rows[idcol].nunique()!=1 or rows.cik.isna().any() or rows.cik.nunique()!=1:reason='AMBIGUOUS_TICKER_SECURITY_OR_ISSUER'
   else:
    order=[PRIMARY[kind]]+(['accepted_datetime'] if kind=='fundamental' else [])
    rows=rows.sort_values(order,kind='mergesort');last=rows.iloc[-1]
    tied=np.ones(len(rows),bool)
    for c in order:tied&=rows[c].eq(last[c]).to_numpy()
    if tied.sum()!=1:reason='AMBIGUOUS_LATEST_ASOF_ROW'
    elif kind=='industry' and (last.identity_status!='AUTHORITATIVE' or last.taxonomy_status!='STRICT_PIT_SIC_FF12_FF48_MAPPED' or last.taxonomy_name!='PIT_AS_FILED_SEC_SIC_FF12_FF48' or last.mapping_reason!='VERIFIED_SEC_HEADER_AND_OFFICIAL_FRENCH_RULES'):reason='UNQUALIFIED_AS_FILED_SIC_MAPPING'
    elif kind=='fundamental' and (last.mapping_source,last.mapping_confidence) not in MAPPING_PAIRS:reason='CURRENT_OR_UNVERIFIED_TICKER_MAPPING'
    elif kind=='fundamental' and (not bool(last.corporate_action_scale_consistent) or not bool(last.coverage_status)):reason='SOURCE_SCALE_OR_CORE_COVERAGE_UNQUALIFIED'
    hashes=['sic_source_sha256'] if kind=='industry' else ['lineage_hash','source_sha256','accepted_source_sha256']
    if not reason and any(not isinstance(last[h],str) or not re.fullmatch(r'[0-9a-fA-F]{64}',last[h]) for h in hashes):reason='SOURCE_ROW_LINEAGE_HASH_MISSING'
    if not reason:
     available=max(_local_time(pd.Series([last[c]]),tz).iloc[0] for c,tz in CLOCKS[kind].items())
     if pd.isna(available) or available>=cut:raise ValueError('EXPOSURE_AVAILABILITY_NOT_STRICTLY_PRIOR')
     chosen.append(last)
   qualification.append({'ticker':asset,'security_id':None if last is None else last[idcol],'available_at':available,'metadata_pit_qualified':not bool(reason),'blocked_reason':reason})
  q=pd.DataFrame(qualification).set_index('ticker')
  # Two requested symbols cannot silently represent one security at this cutoff.
  duplicated=q.metadata_pit_qualified&q.security_id.duplicated(keep=False)
  q.loc[duplicated,'metadata_pit_qualified']=False;q.loc[duplicated,'blocked_reason']='SECURITY_HAS_MULTIPLE_REQUESTED_TICKERS'
  selected=pd.DataFrame(chosen,columns=META[kind]);selected=selected.loc[selected[tickercol].isin(q.index[q.metadata_pit_qualified])]
  frame=pd.DataFrame(np.nan,index=pd.Index(names,name='ticker'),columns=FACTORS[kind])
  if not selected.empty:
   numeric=['ff48_code'] if kind=='industry' else list(FUNDAMENTAL_COLUMNS)
   extra=[(idcol,'in',selected[idcol].tolist()),(PRIMARY[kind],'in',selected[PRIMARY[kind]].tolist())]
   if kind=='fundamental':extra+=[('accession','in',selected.accession.tolist()),('mapping_source','in',[p[0] for p in MAPPING_PAIRS]),('mapping_confidence','in',[p[1] for p in MAPPING_PAIRS]),('corporate_action_scale_consistent','==',True),('coverage_status','==',True)]
   else:extra+=[('identity_status','==','AUTHORITATIVE'),('taxonomy_status','==','STRICT_PIT_SIC_FF12_FF48_MAPPED')]
   vectors=self._project(kind,year,selected[tickercol].tolist(),tuple(KEYS[kind]+numeric),extra)
   if vectors.duplicated(KEYS[kind]).any():raise ValueError('EXPOSURE_NUMERIC_DUPLICATE_SOURCE_KEY')
   joined=selected[KEYS[kind]].merge(vectors,on=KEYS[kind],how='left',validate='one_to_one',indicator=True)
   if not joined._merge.eq('both').all():raise ValueError('EXPOSURE_QUALIFIED_VECTOR_KEYS_INCOMPLETE')
   if kind=='industry':
    for row in joined.itertuples(index=False):
     code=float(row.ff48_code)
     if not np.isfinite(code) or code!=int(code) or not 1<=code<=48:
      q.loc[row.ticker_at_date,['metadata_pit_qualified','blocked_reason']]=[False,'INVALID_OFFICIAL_FF48_CODE'];continue
     frame.loc[row.ticker_at_date]=0.;frame.loc[row.ticker_at_date,f'FF48_{int(code):02d}']=1.
   else:
    array=joined[list(FUNDAMENTAL_COLUMNS)].to_numpy(float,copy=True);array[~np.isfinite(array)]=np.nan
    frame.loc[joined.ticker.to_numpy(),list(FUNDAMENTAL_COLUMNS)]=array
  q['missing_factor_count']=frame.isna().sum(axis=1);q['complete_exposure']=q.metadata_pit_qualified&np.isfinite(frame).all(axis=1)
  qualified=q.metadata_pit_qualified;available=q.loc[qualified,'available_at'].max() if qualified.any() else None
  status='PIT_ASOF_EXPOSURE_READY' if qualified.any() else ('BLOCKED_SPECIFIC_TEMPORAL_COVERAGE' if meta.empty else 'BLOCKED_INPUT_NO_QUALIFIED_ASSET_MAPPING')
  units={c:('one_hot' if kind=='industry' else 'days' if c=='filing_lag_days' else 'binary' if c in ('amendment_indicator','concept_switch_indicator') else 'dimensionless_source_ratio_or_ratio_difference') for c in FACTORS[kind]}
  source_id=f"{kind}|{year}|{SOURCES[kind]['sha256']}|{self.source_receipt['source_module_sha256']}"
  frame.attrs.update(pit_qualified=bool(qualified.any()),source_id=source_id,available_at=available,cutoff_exclusive=cut,clock_timezone='America/New_York',factor_units=units,missing_semantics='NaN; no imputation or unknown-sector all-zero row',asset_eligibility_upgraded=False,exposure_clock='ANNUAL_STATIC_LAST_ROW_WITH_ALL_CLOCKS_STRICTLY_PREJAN1')
  receipt={'status':status,'kind':kind,'year':year,'source_id':source_id,'source_module_sha256':self.source_receipt['source_module_sha256'],'input_manifest_sha256':self.source_receipt['input_manifest_sha256'],'source':self.source_receipt['sources'][kind],'cutoff_exclusive':cut.isoformat(),'available_at':None if available is None else available.isoformat(),'factor_columns':list(frame.columns),'factor_units':units,'assets_requested':len(names),'metadata_qualified_assets':int(qualified.sum()),'complete_exposure_assets':int(q.complete_exposure.sum()),'missing_factor_cells':int(frame.isna().to_numpy().sum()),'blocked_reasons':q.loc[~qualified,'blocked_reason'].value_counts().to_dict(),'accepted_mapping_pairs':[list(p) for p in sorted(MAPPING_PAIRS)] if kind=='fundamental' else None,'cash_entitlement_inferred':False,'marketcap_book_fields_invented':False,'fixed32_changed':False,'fit_units':0,'test_2026_rows_read':0}
  return ExposureResult(frame,q.reset_index(),receipt)

 def publish(self,result):
  """Run-owned derived factors with immutable receipt; not a model fit or ledger."""
  kind=result.receipt['kind'];year=result.receipt['year'];folder=self.run/'inputs/pit_exposures'/kind/str(year)
  assert_write_path(folder,'backtest')
  if folder.exists():raise ValueError('EXISTING_EXPOSURE_OUTPUTS_PRESERVED')
  folder.mkdir(parents=True)
  records={}
  for name,data in (('exposure',result.frame.reset_index()),('qualification',result.qualification)):
   path=folder/(name+'.parquet');stored=data.copy();stored.attrs={};stored.to_parquet(path,index=False);records[name]={'path':str(path),'sha256':sha(path),'rows':len(data)}
  receipt={**result.receipt,'artifacts':records}
  write_json_atomic(folder/'receipt.json',receipt);return receipt


def load_annual_projection(pin,cutoff):
 """Restore only source-qualified run-owned static exposures for the risk API."""
 cut=pd.Timestamp(cutoff)
 if cut.tzinfo is not None or cut!=pd.Timestamp(f'{cut.year}-01-01') or cut.year not in (2023,2024,2025):raise ValueError('EXPOSURE_LOADER_ANNUAL_CUTOFF')
 required={'producer_path','producer_sha256','artifact_path','artifact_sha256','receipt_path','receipt_sha256','source_id','available_at'}
 if not required.issubset(pin):raise ValueError('EXPOSURE_PRODUCER_ARTIFACT_AND_RECEIPT_PINS_REQUIRED')
 producer=Path(pin['producer_path']).resolve()
 if producer!=Path(__file__).resolve() or sha(producer)!=pin['producer_sha256']:raise ValueError('EXPOSURE_PRODUCER_NOT_CURRENT_SOURCE')
 receipt_path=Path(pin['receipt_path']).resolve()
 if sha(receipt_path)!=pin['receipt_sha256']:raise ValueError('EXPOSURE_QUALIFICATION_RECEIPT_CHANGED')
 receipt=json.loads(receipt_path.read_text(encoding='utf-8-sig'));kind=receipt.get('kind')
 available=pd.Timestamp(receipt.get('available_at'))
 if receipt.get('status')!='PIT_ASOF_EXPOSURE_READY' or kind not in SOURCES or receipt.get('year')!=cut.year or pd.Timestamp(receipt.get('cutoff_exclusive'))!=cut or pd.isna(available) or available.tzinfo is not None or available>=cut or receipt.get('source_module_sha256')!=pin['producer_sha256'] or receipt.get('source_id')!=pin['source_id'] or pd.Timestamp(pin['available_at'])!=available or receipt.get('fit_units')!=0 or receipt.get('test_2026_rows_read')!=0:raise ValueError('UNQUALIFIED_EXPOSURE_ASOF_METADATA')
 source=receipt.get('source',{})
 if source.get('path')!=SOURCES[kind]['path'] or source.get('sha256')!=SOURCES[kind]['sha256'] or source.get('hash_verified') is not True or tuple(receipt.get('factor_columns',()))!=FACTORS[kind]:raise ValueError('EXPOSURE_SOURCE_OR_FIXED_FACTOR_COLUMNS_CHANGED')
 artifact=Path(pin['artifact_path']).resolve();record=receipt['artifacts']['exposure']
 if len(artifact.parents)<5:raise ValueError('EXPOSURE_ARTIFACT_NOT_CANONICAL_RUN')
 run=artifact.parents[4];expected=run/'inputs/pit_exposures'/kind/str(cut.year)
 if artifact!=expected/'exposure.parquet' or receipt_path!=expected/'receipt.json' or not run.is_relative_to(resolve(REPO).backtest_root.resolve()) or record['path']!=str(artifact) or record['sha256']!=pin['artifact_sha256'] or sha(artifact)!=pin['artifact_sha256'] or sha(run/'input_manifest.json')!=receipt.get('input_manifest_sha256'):raise ValueError('EXPOSURE_ARTIFACT_OR_INPUT_IDENTITY_CHANGED')
 qp=Path(receipt['artifacts']['qualification']['path']).resolve()
 if qp!=expected/'qualification.parquet' or sha(qp)!=receipt['artifacts']['qualification']['sha256']:raise ValueError('EXPOSURE_QUALIFICATION_FLAG_ARTIFACT_CHANGED')
 qcols=['ticker','security_id','available_at','metadata_pit_qualified','complete_exposure','missing_factor_count','blocked_reason']
 q=pq.read_table(qp,columns=qcols).to_pandas()
 if q.ticker.isna().any() or q.ticker.duplicated().any() or len(q)!=receipt['assets_requested'] or not q.metadata_pit_qualified.isin([True,False]).all():raise ValueError('EXPOSURE_QUALIFICATION_KEYS_OR_FLAGS')
 legal=q.metadata_pit_qualified;times=pd.to_datetime(q.loc[legal,'available_at'])
 if times.isna().any() or times.dt.tz is not None or not times.lt(cut).all() or times.max()!=available or int(legal.sum())!=receipt['metadata_qualified_assets']:raise ValueError('EXPOSURE_QUALIFIED_ASSET_CLOCKS_NOT_PAST')
 pf=pq.ParquetFile(artifact)
 if pf.schema_arrow.names!=['ticker',*FACTORS[kind]] or pf.metadata.num_rows!=len(q) or any(not pa.types.is_floating(pf.schema_arrow.field(c).type) for c in FACTORS[kind]):raise ValueError('EXPOSURE_ARTIFACT_TYPED_FACTOR_SCHEMA')
 vectors=pd.read_parquet(artifact,columns=['ticker',*FACTORS[kind]],filters=[('ticker','in',q.loc[legal,'ticker'].tolist())])
 if vectors.ticker.duplicated().any() or set(vectors.ticker)!=set(q.loc[legal,'ticker']):raise ValueError('EXPOSURE_QUALIFIED_VECTOR_KEYS')
 frame=vectors.set_index('ticker').reindex(q.ticker)
 if np.isinf(frame.to_numpy(float)).any():raise ValueError('EXPOSURE_NONFINITE_INF')
 complete=np.isfinite(frame).all(axis=1)
 if not np.array_equal(complete.to_numpy(),q.complete_exposure.to_numpy()):raise ValueError('EXPOSURE_COMPLETE_FLAGS_NOT_EXACT')
 frame.attrs.update(pit_qualified=True,source_id=receipt['source_id'],available_at=available,cutoff_exclusive=cut,clock_timezone='America/New_York',factor_units=receipt['factor_units'],missing_semantics='NaN; no imputation',asset_eligibility_upgraded=False,exposure_clock='ANNUAL_STATIC_LAST_ROW_WITH_ALL_CLOCKS_STRICTLY_PREJAN1')
 return frame
