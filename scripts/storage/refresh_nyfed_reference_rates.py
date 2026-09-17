"""Six NY Fed reference-rate feeds; existing archive, storage and catalog only."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from scripts.storage import refresh_official_research_data as common
from scripts.storage.storage_r2a import CATALOG_ROLE, CATALOG_SCHEMA_VERSION

DATASET = 'nyfed_reference_rates_current'
STARTS = {'effr':'2010-01-01','obfr':'2016-03-01','tgcr':'2018-04-02',
          'bgcr':'2018-04-02','sofr':'2018-04-02','sofrai':'2018-04-02'}
LATEST_URL = 'https://markets.newyorkfed.org/api/rates/all/latest.json'
TERMS_URL = 'https://www.newyorkfed.org/privacy/termsofuse'
NOTICE = ('New York Fed reference rates are subject to the Terms of Use posted at newyorkfed.org. '
          'The New York Fed is not responsible for publication of these reference rates by US Tech Quant, '
          'does not endorse this republication, and has no liability for your use.')
UNITS = {key:'percent' for key in ['percentRate','percentPercentile1','percentPercentile25',
    'percentPercentile75','percentPercentile99','targetRateFrom','targetRateTo','intraDayHigh',
    'intraDayLow','average30day','average90day','average180day']}
UNITS.update(volumeInBillions='USD_billions',index='index',stdDeviation='percentage_points')
KEYS = set(UNITS) | {'effectiveDate','type','revisionIndicator','footnoteId'}


def check_as_of(as_of):
    day = date.fromisoformat(as_of)
    if not date(2026,1,1) <= day <= date.today():
        raise ValueError('AS_OF_OUTSIDE_CURRENT_INTAKE_SCOPE')
    return day


def url_for(kind, as_of):
    group = 'unsecured' if kind in {'effr','obfr'} else 'secured'
    return (f'https://markets.newyorkfed.org/api/rates/{group}/{kind}/search.json'
            f'?startDate={STARTS[kind]}&endDate={as_of}')


def records(raw):
    def invalid(value):
        raise ValueError('NONFINITE_JSON_NUMBER:'+value)
    payload = json.loads(raw, parse_constant=invalid)
    if not isinstance(payload,dict) or set(payload) != {'refRates'} or not payload['refRates']:
        raise ValueError('NYFED_RESPONSE_INVALID_OR_EMPTY')
    return payload['refRates']


def parse(raw, kind, start, as_of):
    check_as_of(as_of)
    if kind not in STARTS or start != STARTS[kind]:
        raise ValueError('UNSUPPORTED_RATE_OR_START')
    rows, seen = [], set()
    for item in records(raw):
        if not isinstance(item,dict) or set(item)-KEYS or item.get('type') != kind.upper():
            raise ValueError('UNEXPECTED_RATE_TYPE_OR_FIELD')
        original_values={k:item[k] for k in set(item)&set(UNITS)}
        item={k:(None if k in UNITS and v=='NA' else v) for k,v in item.items()}
        day = item.get('effectiveDate','')
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day) or date.fromisoformat(day).isoformat()!=day or not start <= day <= as_of:
            raise ValueError('EFFECTIVE_DATE_OUTSIDE_REQUEST')
        if day in seen:
            raise ValueError('DUPLICATE_EFFECTIVE_DATE')
        seen.add(day)
        required = {'average30day','average90day','average180day','index'} if kind=='sofrai' else {'percentRate'}
        if not required <= item.keys() or any(item[k] is None for k in required):
            raise ValueError('MISSING_HEADLINE_RATE')
        for key in set(item)&set(UNITS):
            value=item[key]
            if value is not None and (type(value) not in {int,float} or not np.isfinite(value)):
                raise ValueError('NONNUMERIC_OR_NONFINITE_VALUE')
            if key in {'volumeInBillions','index'} and value is not None and value < 0:
                raise ValueError('NEGATIVE_VOLUME_OR_INDEX')
        ordered = [item.get(k) for k in ['percentPercentile1','percentPercentile25','percentRate','percentPercentile75','percentPercentile99']]
        present = [v for v in ordered if v is not None]
        if present != sorted(present):
            raise ValueError('PERCENTILE_ORDER_INVALID')
        revision=item.get('revisionIndicator')
        if revision is not None and not isinstance(revision,str):
            raise ValueError('REVISION_INDICATOR_INVALID')
        regime = ('EFFR_BEFORE_2016_03_01' if day<'2016-03-01' else 'EFFR_FROM_2016_03_01') if kind=='effr' else 'SEE_PROVIDER_METHODOLOGY'
        for metric in sorted(set(item)&set(UNITS)):
            rows.append({'date':day,'rate_type':kind.upper(),'metric':metric,'value':item[metric],
                'unit':UNITS[metric],
                'value_status':('SOURCE_NOT_AVAILABLE' if original_values[metric]=='NA' else
                                'SOURCE_NULL' if item[metric] is None else 'OBSERVED'),
                'provider_value_json':json.dumps(original_values[metric],ensure_ascii=False),
                'revision_indicator':revision,'source_footnote_json':json.dumps(item.get('footnoteId'),ensure_ascii=False),
                'methodology_regime':regime})
    return pd.DataFrame(rows).sort_values(['date','rate_type','metric']).reset_index(drop=True)


def validate_latest(frames, latest, as_of):
    expected={k.upper() for k in STARTS}
    entries=records(latest)
    if len(entries)!=len(expected) or {x.get('type') for x in entries}!=expected:
        raise ValueError('LATEST_RATE_SET_INCOMPLETE')
    freshness=[]
    for item in entries:
        kind=item['type']; frame=frames[kind]
        if item['effectiveDate']>as_of or frame.date.max()!=item['effectiveDate']:
            raise ValueError('HISTORY_DOES_NOT_REACH_LATEST_RELEASE')
        latest_frame=parse(json.dumps({'refRates':[item]}).encode(),kind.lower(),STARTS[kind.lower()],as_of)
        observed=frame[frame.date.eq(item['effectiveDate'])]
        try:
            pd.testing.assert_frame_equal(observed.loc[:,latest_frame.columns].reset_index(drop=True),
                latest_frame,check_dtype=False,check_exact=True)
        except AssertionError as exc:
            raise ValueError('LATEST_RELEASE_VALUE_DIFFERS_FROM_HISTORY') from exc
        freshness.append({'rate_type':kind,'min_date':frame.date.min(),'max_date':frame.date.max(),
            'observation_dates':int(frame.date.nunique()),'metrics':sorted(frame.metric.unique()),
            'status':'MATCHES_OFFICIAL_LATEST_ENDPOINT'})
    return sorted(freshness,key=lambda x:x['rate_type'])


def validate_raw(raw, paths, expected_url):
    path=Path(raw['local_path']).resolve()
    if raw['status'] not in {'CACHED','DOWNLOADED'} or not path.is_relative_to(paths.cache_root):
        raise ValueError('RAW_STATUS_OR_STORAGE_INVALID')
    if raw['source']!='NYFED_OFFICIAL' or raw['source_reference']!=expected_url or common.sha256(path)!=raw['sha256']:
        raise ValueError('RAW_SOURCE_IDENTITY_INVALID')
    observed=pd.Timestamp(raw['retrieval_timestamp_utc'])
    if pd.isna(observed) or observed.tzinfo is None:
        raise ValueError('OBSERVED_TIME_INVALID')
    return path.read_bytes()


def normalize(acquisition, paths):
    as_of=acquisition['as_of'];check_as_of(as_of)
    items=acquisition['items']
    if len(items)!=6 or {x['kind'] for x in items}!=set(STARTS):
        raise ValueError('SIX_RATE_FEEDS_REQUIRED')
    frames, inputs = {}, []
    for item in items:
        kind=item['kind'];raw=item['raw']
        frame=parse(validate_raw(raw,paths,url_for(kind,as_of)),kind,item['start'],as_of)
        frame['source']='NYFED_OFFICIAL';frame['source_id']=raw['sha256']
        frame['observed_at_utc']=raw['retrieval_timestamp_utc']
        frame['available_at_utc']=pd.Series(pd.NaT,index=frame.index,dtype='datetime64[ns, UTC]')
        frame['vintage_semantics']=common.VINTAGE
        frames[kind.upper()]=frame
        inputs.append({'kind':kind,'raw':raw})
    latest_raw=acquisition['latest_raw']
    freshness=validate_latest(frames,validate_raw(latest_raw,paths,LATEST_URL),as_of)
    frame=pd.concat(frames.values(),ignore_index=True).sort_values(['date','rate_type','metric']).reset_index(drop=True)
    contract={'as_of':as_of,'inputs':[{'kind':i['kind'],'sha256':i['raw']['sha256'],
        'observed_at':i['raw']['retrieval_timestamp_utc']} for i in inputs],
        'latest_sha256':latest_raw['sha256'],'normalizer_sha256':common.sha256(__file__),
        'shared_code_sha256':common.sha256(common.__file__)}
    version=hashlib.sha256(common.json_bytes(contract)).hexdigest()[:24]
    folder=paths.data_root/'reference/official_research/nyfed'/version;folder.mkdir(parents=True,exist_ok=True)
    path=folder/(DATASET+'.parquet');temp=folder/(DATASET+'.parquet.tmp')
    frame.to_parquet(temp,index=False,compression='zstd')
    if pq.ParquetFile(temp).metadata.num_rows!=len(frame):
        raise ValueError('PARQUET_ROW_COUNT_MISMATCH')
    if path.exists():
        if common.sha256(path)!=common.sha256(temp):raise ValueError('EXISTING_VERSION_PRESERVED')
        temp.unlink()
    else:temp.replace(path)
    return {'role':'NYFED_REFERENCE_RATE_INTAKE','status':'VALIDATED_DATA_ONLY','contract':contract,
        'inputs':inputs,'latest_raw':latest_raw,'freshness':freshness,'terms_url':TERMS_URL,'attribution_notice':NOTICE,
        'historical_pit_certified':False,'research_usage':'2026_PLUS_OBSERVATION_ONLY_NO_TRAINING_TUNING_OR_BACKTEST',
        'output':{'dataset':DATASET,'path':str(path),'sha256':common.sha256(path),'row_count':len(frame),
            'min_date':frame.date.min(),'max_date':frame.date.max(),'missing_value_rows':int(frame.value.isna().sum())}}


def publish(manifest_path,paths):
    manifest_path=Path(manifest_path).resolve()
    if not manifest_path.is_relative_to(paths.results_root):raise ValueError('MANIFEST_STORAGE_INVALID')
    a=json.loads(manifest_path.read_text(encoding='utf-8'));o=a['output']
    if a['role']!='NYFED_REFERENCE_RATE_INTAKE' or a['status']!='VALIDATED_DATA_ONLY' or o['dataset']!=DATASET:
        raise ValueError('UNVALIDATED_MANIFEST')
    as_of=a['contract']['as_of'];check_as_of(as_of)
    for i in a['inputs']:validate_raw(i['raw'],paths,url_for(i['kind'],as_of))
    validate_raw(a['latest_raw'],paths,LATEST_URL)
    path=Path(o['path']).resolve()
    if not path.is_relative_to(paths.data_root) or common.sha256(path)!=o['sha256'] or o['max_date']>as_of:
        raise ValueError('OUTPUT_IDENTITY_INVALID')
    if pq.ParquetFile(path).metadata.num_rows!=o['row_count']:raise ValueError('OUTPUT_ROW_COUNT_INVALID')
    catalog=paths.cache_root/'derived/data_catalog/catalog.sqlite3'
    if not catalog.is_file():raise ValueError('EXISTING_CATALOG_REQUIRED')
    with sqlite3.connect(catalog,timeout=30) as c:
        c.execute('BEGIN IMMEDIATE')
        metadata=dict(c.execute('SELECT key,value FROM catalog_metadata'))
        if metadata.get('schema_version')!=CATALOG_SCHEMA_VERSION or metadata.get('catalog_role')!=CATALOG_ROLE:
            raise ValueError('CATALOG_ROLE_INVALID')
        prior=c.execute('SELECT min_date,max_date,lineage_json FROM data_files WHERE dataset=? AND is_current=1',(DATASET,)).fetchall()
        current={x['rate_type']:x for x in a['freshness']}
        for lo,hi,previous in prior:
            if o['min_date']>lo or o['max_date']<hi:raise ValueError('COVERAGE_REGRESSION')
            previous={x['rate_type']:x for x in json.loads(previous).get('freshness',[])}
            if set(previous)!=set(current):raise ValueError('SERIES_COVERAGE_REGRESSION_OR_UNKNOWN')
            if any(current[k]['min_date']>v['min_date'] or current[k]['max_date']<v['max_date']
                   or current[k]['observation_dates']<v['observation_dates'] for k,v in previous.items()):
                raise ValueError('SERIES_COVERAGE_REGRESSION')
        lineage={'date_column':'date','manifest_path':str(manifest_path),'manifest_sha256':common.sha256(manifest_path),
            'as_of':as_of,'historical_pit_certified':False,'available_at_semantics':'UNKNOWN_NULL',
            'vintage_semantics':common.VINTAGE,'freshness':a['freshness'],'terms_url':TERMS_URL,
            'attribution_notice':NOTICE,'research_usage':a['research_usage']}
        common.register_file(c,DATASET,'','',str(path),o['row_count'],o['min_date'],o['max_date'],'NYFED_OFFICIAL',lineage)
    return {'status':'CATALOG_REGISTERED','dataset':DATASET,'manifest':str(manifest_path)}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id',required=True);parser.add_argument('--as-of',required=True)
    parser.add_argument('--execute',action='store_true');parser.add_argument('--register',action='store_true')
    args=parser.parse_args(argv);check_as_of(args.as_of)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',args.run_id):raise ValueError('INVALID_RUN_ID')
    paths=common.resolve();root=paths.results_root/'official_research_intake'/args.run_id/'nyfed'
    if not args.execute:
        print(json.dumps({'history_urls':[url_for(k,args.as_of) for k in STARTS],'latest_url':LATEST_URL}));return 0
    acquisition_path=root/'acquisition.json'
    if not acquisition_path.exists():
        capture=common.archive_module(paths.repo_root);raw_root=paths.cache_root/'official_research_intake'/args.run_id/'raw'
        items=[]
        for kind,start in STARTS.items():
            raw=capture.acquire_url(url_for(kind,args.as_of),'nyfed_reference_rates','NYFED_OFFICIAL','REFERENCE_RATE_HISTORY',raw_root,30,1,2)
            if raw.status=='FAILED':raise RuntimeError(raw.error)
            items.append({'kind':kind,'start':start,'raw':asdict(raw)});time.sleep(.5)
        raw=capture.acquire_url(LATEST_URL,'nyfed_reference_rates','NYFED_OFFICIAL','LATEST_RELEASE_VERIFICATION',raw_root,30,1,2)
        if raw.status=='FAILED':raise RuntimeError(raw.error)
        common.save_json(acquisition_path,{'as_of':args.as_of,'items':items,'latest_raw':asdict(raw)})
    acquisition=json.loads(acquisition_path.read_text(encoding='utf-8'))
    if acquisition['as_of']!=args.as_of:raise ValueError('RUN_ID_AS_OF_MISMATCH')
    manifest_path=root/'manifest.json'
    if not manifest_path.exists():common.save_json(manifest_path,normalize(acquisition,paths))
    print(json.dumps(publish(manifest_path,paths) if args.register else {'status':'VALIDATED_NOT_REGISTERED','manifest':str(manifest_path)}))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
