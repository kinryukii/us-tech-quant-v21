"""Bounded NY Fed primary-dealer positions, financing and fails; data intake only."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import shutil
import time
import urllib.error
import urllib.request

import pyarrow as pa
import pyarrow.parquet as pq

from scripts.storage import refresh_official_research_data as common

FAMILY = 'nyfed_primary_dealer'
DATASET = 'nyfed_primary_dealer_current'
BASE = 'https://markets.newyorkfed.org/api/pd/'
POSITIONS = tuple('PDPOS'+s+'-TOT' for s in ('GST','FGS','MBS','CS','ABS','SMGO'))
FINANCING = tuple(p+'-'+s for p in ('PDSORA','PDSIRRA')
                  for s in ('UTSETTOT','UTSTTOT','FGEMTOT','FGMTOT','FGCMTOT'))
FAILS = tuple(p+'-'+s for p in ('PDFTR','PDFTD') for s in ('USTET','UST','FGEM','FGM','OM','CS'))
SERIES = POSITIONS + FINANCING + FAILS
START = '2010-01-01'
META = {'definitions':BASE+'list/timeseries.json', 'seriesbreaks':BASE+'list/seriesbreaks.json',
        'dates':BASE+'list/asof.json', 'latest':BASE+'latest/SBN2024.json'}
DOCS = {
    'reporting_forms':'https://www.federalreserve.gov/apps/reportingforms/Report/Index/FR_2004',
    **{'instructions_'+year:'https://www.federalreserve.gov/apps/reportingforms/Download/DownloadAttachment?guid='+guid
       for year,guid in [('2024','950ab256-b485-4586-99b0-b27eb205fdfa'),
                         ('2022','978610fa-a9ee-4a6c-ac90-8055546b77ea'),
                         ('2015','0ead3d17-ff78-4ffe-9c62-a5c0b9784c82'),
                         ('2013','f555fe11-e149-479b-8088-4ed4e9ae1206'),
                         ('2010','e46ffb82-6319-424d-aed2-6edfe6765328')]},
    'release_schedule':'https://www.newyorkfed.org/markets/counterparties/primary-dealers-statistics',
    'fails_primer':'https://www.newyorkfed.org/markets/pridealers_failsprimer.html',
    'terms':'https://www.newyorkfed.org/privacy/termsofuse'}
RAW_LIMIT = 300 * 1024**2
TOTAL_LIMIT = 1024**3
FLOOR = 20 * 1024**3
RESPONSE_LIMIT = 20 * 1024**2
NOTICE = ('Primary Dealer Statistics are provided by the Federal Reserve Bank of New York and are '
          'subject to its Terms of Use. The New York Fed does not endorse this republication by '
          'US Tech Quant and is not responsible for its publication or use.')


def plan():
    return {**META, **{'history_'+str(i//7+1):BASE+'get/'+'_'.join(SERIES[i:i+7])+'.json'
                      for i in range(0,len(SERIES),7)}, **DOCS}


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')


def validate_as_of(as_of):
    common.snapshot_day(as_of)
    if as_of is None: raise ValueError('AS_OF_REQUIRED')


def check_budget(paths, root, output_bytes=0):
    raw_bytes = sum(p.stat().st_size for p in root.glob('*.source')) if root.exists() else 0
    if raw_bytes > RAW_LIMIT or raw_bytes + output_bytes > TOTAL_LIMIT:
        raise ValueError('SOURCE_BUDGET_EXCEEDED')
    if min(shutil.disk_usage(paths.cache_root).free, shutil.disk_usage(paths.data_root).free) < FLOOR:
        raise ValueError('DISK_FREE_BELOW_20_GIB')
    return raw_bytes


def validate_receipt(receipt, name, url, paths):
    raw = receipt['raw']; path = Path(raw['local_path']).resolve()
    expected_source = 'FEDERAL_RESERVE_BOARD' if name in DOCS and 'federalreserve.gov' in url else 'NYFED_OFFICIAL'
    if (receipt['name'] != name or receipt['url'] != url or raw['source_reference'] != url
        or raw['source'] != expected_source or raw['status'] not in {'CACHED','DOWNLOADED'}
        or not path.is_relative_to(paths.cache_root) or common.sha256(path) != raw['sha256']):
        raise ValueError('RAW_IDENTITY_INVALID')
    stamp = datetime.fromisoformat(raw['retrieval_timestamp_utc'].replace('Z','+00:00'))
    if stamp.tzinfo is None: raise ValueError('RETRIEVAL_TIMEZONE_REQUIRED')
    sidecar=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    if any(sidecar[k] != raw[k] for k in ('sha256','source_reference','retrieval_timestamp_utc','source')):
        raise ValueError('RAW_SIDECAR_MISMATCH')
    return path


def acquire(paths, run_id, as_of):
    validate_as_of(as_of)
    root=paths.results_root/'official_research_intake'/run_id/FAMILY
    raw_root=paths.cache_root/'official_research_intake'/run_id/'raw'
    if (root/'source_stop.json').exists(): raise ValueError('PRIOR_SOURCE_FAILURE_REQUIRES_REVIEW')
    archive=common.archive_module(paths.repo_root)
    receipts={}
    for name,url in plan().items():
        receipt_path=root/(name+'_acquisition.json')
        if receipt_path.exists():
            receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
            validate_receipt(receipt,name,url,paths)
            receipts[name]=receipt
            continue
        if (root/'source_stop.json').exists(): raise ValueError('PRIOR_SOURCE_FAILURE_REQUIRES_REVIEW')
        raw_bytes=check_budget(paths,raw_root/FAMILY)
        response={}
        def download(target,timeout):
            time.sleep(.6)
            request=urllib.request.Request(target,headers={'User-Agent':'US-Tech-Quant-official-data-integrity/1.0',
                                                           'Accept-Encoding':'identity'})
            try:
                with urllib.request.urlopen(request,timeout=timeout) as handle:
                    response.update(status=handle.status,headers=dict(handle.headers),
                                    observed_at_utc=utc_now(),final_url=handle.geturl())
                    if handle.status != 200: raise ValueError('HTTP_200_REQUIRED')
                    body=handle.read(RESPONSE_LIMIT+1)
                    if len(body)>RESPONSE_LIMIT or raw_bytes+len(body)>RAW_LIMIT:
                        raise ValueError('RESPONSE_BUDGET_EXCEEDED')
                    length=handle.headers.get('Content-Length')
                    if length is not None and int(length)!=len(body): raise ValueError('INCOMPLETE_HTTP_BODY')
                    if not body: raise ValueError('EMPTY_HTTP_BODY')
                    return body
            except urllib.error.HTTPError as exc:
                response.update(status=exc.code,headers=dict(exc.headers),observed_at_utc=utc_now(),
                                error_body_retained=False)
                raise
        archive._download_once=download
        source='FEDERAL_RESERVE_BOARD' if name in DOCS and 'federalreserve.gov' in url else 'NYFED_OFFICIAL'
        raw=archive.acquire_url(url,FAMILY,source,'PDS_'+name.upper(),raw_root,40,0,0)
        receipt={'name':name,'url':url,'raw':asdict(raw),'response':response}
        common.save_json(receipt_path,receipt)
        if raw.status=='FAILED':
            common.save_json(root/'source_stop.json',{'name':name,'receipt':str(receipt_path),
                'observed_at_utc':utc_now(),'reason':'FAILED_REQUEST_NO_AUTOMATIC_RETRY'})
            raise RuntimeError(raw.error)
        validate_receipt(receipt,name,url,paths)
        receipts[name]=receipt
        print(json.dumps({'acquired':name,'bytes':Path(raw.local_path).stat().st_size}),flush=True)
    return receipts


def records(raw, key):
    def pairs(items):
        result={}
        for k,v in items:
            if k in result: raise ValueError('DUPLICATE_JSON_KEY')
            result[k]=v
        return result
    payload=json.loads(raw,object_pairs_hook=pairs,
                       parse_constant=lambda x: (_ for _ in ()).throw(ValueError('NONFINITE_JSON')))
    if (not isinstance(payload,dict) or set(payload)!={'pd'} or not isinstance(payload['pd'],dict)
        or set(payload['pd'])!={key} or not isinstance(payload['pd'][key],list) or not payload['pd'][key]):
        raise ValueError('INVALID_OR_EMPTY_PD_ENVELOPE')
    return payload['pd'][key]


def iso_day(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):
        raise ValueError('INVALID_DATE')
    if date.fromisoformat(value).isoformat()!=value: raise ValueError('INVALID_DATE')
    return value


def parse_metadata(definitions, breaks, dates, as_of):
    validate_as_of(as_of)
    regimes={}
    for row in records(breaks,'seriesbreaks'):
        if set(row)!={'seriesbreak','label','startdate','enddate'}:
            raise ValueError('UNEXPECTED_SERIESBREAK_SCHEMA')
        key=row['seriesbreak']; lo=iso_day(row['startdate']); hi=iso_day(row['enddate'])
        if not isinstance(key,str) or key in regimes or not isinstance(row['label'],str) or lo>hi:
            raise ValueError('INVALID_OR_DUPLICATE_SERIESBREAK')
        regimes[key]=row
    ordered=sorted(regimes.values(),key=lambda x:x['startdate'])
    if any(a['enddate']>=b['startdate'] for a,b in zip(ordered,ordered[1:])):
        raise ValueError('OVERLAPPING_SERIESBREAKS')
    date_map={}
    for row in records(dates,'asofdates'):
        if set(row)!={'asof','seriesbreak'}: raise ValueError('UNEXPECTED_DATE_SCHEMA')
        day=iso_day(row['asof']); key=row['seriesbreak']
        if key not in regimes or day in date_map or day>as_of:
            raise ValueError('INVALID_OR_DUPLICATE_ASOF_DATE')
        if not regimes[key]['startdate']<=day<=regimes[key]['enddate']:
            raise ValueError('DATE_OUTSIDE_SERIESBREAK')
        date_map[day]=key
    definitions_map={}
    for row in records(definitions,'timeseries'):
        if set(row)!={'seriesbreak','keyid','description'} or not all(isinstance(v,str) and v for v in row.values()):
            raise ValueError('UNEXPECTED_DEFINITION_SCHEMA')
        key=(row['seriesbreak'],row['keyid'])
        if key in definitions_map or row['seriesbreak']!='SBN2024':
            raise ValueError('DEFINITION_REGIME_REQUIRES_REVIEW')
        definitions_map[key]=row['description']
    selected={key:definitions_map[('SBN2024',key)] for key in SERIES}
    return regimes,date_map,selected


def parse_history(raw, expected, date_map, as_of):
    expected=set(expected)
    if not expected or not expected<=set(SERIES): raise ValueError('UNSUPPORTED_SERIES')
    result=[]; seen=set(); found=set()
    for ordinal,row in enumerate(records(raw,'timeseries'),1):
        if not isinstance(row,dict) or set(row)!={'asofdate','keyid','value'}:
            raise ValueError('UNEXPECTED_OBSERVATION_SCHEMA')
        day=iso_day(row['asofdate']); key=row['keyid']; value=row['value']
        if key not in expected or day>as_of or day not in date_map:
            raise ValueError('UNEXPECTED_SERIES_OR_DATE')
        identity=(day,key)
        if identity in seen: raise ValueError('DUPLICATE_SERIES_DATE')
        seen.add(identity);found.add(key)
        if not isinstance(value,str): raise ValueError('VALUE_STRING_REQUIRED')
        if value=='*': number=None;status='PROVIDER_ASTERISK_MEANING_UNVERIFIED'
        elif re.fullmatch(r'-?\d{1,38}',value):
            number=Decimal(value);status='OBSERVED'
            if key not in POSITIONS and number<0: raise ValueError('NEGATIVE_FINANCING_OR_FAILS')
        else: raise ValueError('UNKNOWN_PROVIDER_VALUE_REQUIRES_REVIEW')
        group='NET_POSITION' if key in POSITIONS else 'FINANCING' if key in FINANCING else 'SETTLEMENT_FAILS'
        result.append({'date':day,'series_id':key,'seriesbreak':date_map[day],
            'value':number,'provider_value_text':value,'value_status':status,'unit':'USD_millions',
            'measure_group':group,'measurement_basis':{
                'NET_POSITION':'NET_LONG_MINUS_SHORT_FAIR_VALUE_TRADE_DATE_EXCEPT_BUYBACKS',
                'FINANCING':'GROSS_OUTSTANDING_ACTUAL_FUNDS_OR_COLLATERAL_FAIR_VALUE_SETTLEMENT_DATE',
                'SETTLEMENT_FAILS':'REPORTING_PERIOD_CUMULATIVE_PRINCIPAL_EX_ACCRUED_OR_FAILED_FINANCING_FUNDS'}[group],
            'source_row':ordinal,'source_record_json':json.dumps(row,ensure_ascii=False,separators=(',',':'))})
    if found!=expected: raise ValueError('REQUESTED_SERIES_MISSING')
    return result


def validate_latest(rows, raw, date_map, as_of):
    selected=[r for r in records(raw,'timeseries') if r.get('keyid') in SERIES]
    latest=parse_history(json.dumps({'pd':{'timeseries':selected}}).encode(),SERIES,date_map,as_of)
    if len(latest)!=len(SERIES): raise ValueError('LATEST_SET_NOT_ONE_PER_SERIES')
    expected={row['series_id']:row for row in latest}
    all_dates=sorted({r['date'] for r in rows})
    freshness=[]
    for key in SERIES:
        observed=[r for r in rows if r['series_id']==key]
        tail=max(observed,key=lambda x:x['date']); current=expected[key]
        if (any(tail[k]!=current[k] for k in ('date','seriesbreak','provider_value_text','value_status'))
            or json.loads(tail['source_record_json'])!=json.loads(current['source_record_json'])):
            raise ValueError('LATEST_RELEASE_DIFFERS_FROM_HISTORY')
        days=sorted(r['date'] for r in observed)
        missing=sorted(set(d for d in all_dates if days[0]<=d<=days[-1])-set(days))
        if missing: raise ValueError('SELECTED_WEEKLY_SERIES_HAS_INTERNAL_DATE_GAPS')
        freshness.append({'series_id':key,'min_date':days[0],'max_date':days[-1],
            'rows':len(observed),'missing_values':sum(r['value'] is None for r in observed),
            'seriesbreaks':sorted({r['seriesbreak'] for r in observed}),
            'leading_coverage_gap':{'requested_start':START,'first_observation':days[0]},
            'latest_status':'EXACT_MATCH_WITH_OFFICIAL_LATEST',
            'internal_date_comparison':'MATCHES_UNION_OF_SELECTED_WEEKLY_SERIES_WITHIN_ACTIVE_RANGE'})
    return freshness


def normalize(receipts, paths, run_id, as_of):
    validate_as_of(as_of)
    if set(receipts)!=set(plan()): raise ValueError('ACQUISITION_PLAN_INCOMPLETE')
    raw={}
    for name,url in plan().items():
        path=validate_receipt(receipts[name],name,url,paths)
        if receipts[name]['raw']['retrieval_timestamp_utc'][:10]>as_of:
            raise ValueError('RETRIEVAL_AFTER_AS_OF')
        raw[name]=path.read_bytes()
    regimes,date_map,definitions=parse_metadata(raw['definitions'],raw['seriesbreaks'],raw['dates'],as_of)
    rows=[];before_start=0
    for i in range(0,len(SERIES),7):
        name='history_'+str(i//7+1); receipt=receipts[name]['raw']
        for row in parse_history(raw[name],SERIES[i:i+7],date_map,as_of):
            if row['date']<START: before_start+=1;continue
            row.update(source='NYFED_OFFICIAL',source_id=receipt['sha256'],source_url=receipt['source_reference'],
                observed_at_utc=receipt['retrieval_timestamp_utc'],available_at_utc=None,
                provider_description_current=definitions[row['series_id']],definition_regime='SBN2024',
                definition_source_id=receipts['definitions']['raw']['sha256'],
                definition_applicability=('MATCHING_CURRENT_REGIME' if row['seriesbreak']=='SBN2024'
                                          else 'CURRENT_DESCRIPTION_NOT_CERTIFIED_FOR_HISTORICAL_REGIME'),
                vintage_semantics=common.VINTAGE)
            rows.append(row)
    freshness=validate_latest(rows,raw['latest'],date_map,as_of)
    rows.sort(key=lambda r:(r['date'],r['series_id']))
    schema=pa.schema([(k,pa.decimal128(38,0) if k=='value' else pa.int64() if k=='source_row'
                       else pa.timestamp('us',tz='UTC') if k=='available_at_utc' else pa.string()) for k in rows[0]])
    table=pa.Table.from_pylist(rows,schema=schema)
    contract={'as_of':as_of,'start':START,'series':list(SERIES),
        'inputs':{name:{k:r['raw'][k] for k in ('source_reference','sha256','retrieval_timestamp_utc')}
                  for name,r in receipts.items()},
        'normalizer_sha256':common.sha256(__file__),'common_sha256':common.sha256(common.__file__),
        'archive_sha256':common.sha256(paths.repo_root/'fast6/src/fast6/acquisition.py')}
    version=hashlib.sha256(common.json_bytes(contract)).hexdigest()[:24]
    folder=paths.data_root/'reference/official_research'/FAMILY/version
    path=folder/(DATASET+'.parquet');temporary=folder/(DATASET+'.parquet.tmp')
    check_budget(paths,paths.cache_root/'official_research_intake'/run_id/'raw'/FAMILY,table.nbytes*2)
    folder.mkdir(parents=True,exist_ok=True)
    if temporary.exists(): raise ValueError('PRIOR_PARTIAL_OUTPUT_PRESERVED')
    pq.write_table(table,temporary,compression='zstd')
    if not table.equals(pq.read_table(temporary)): raise ValueError('PARQUET_ROUNDTRIP_MISMATCH')
    if path.exists():
        if common.sha256(path)!=common.sha256(temporary): raise ValueError('EXISTING_OUTPUT_PRESERVED')
        temporary.unlink()
    else: temporary.replace(path)
    manifest={'role':'NYFED_PRIMARY_DEALER_INTAKE','status':'VALIDATED_DATA_ONLY','contract':contract,
        'inputs':receipts,'freshness':freshness,'seriesbreak_definitions':regimes,
        'historical_pit_certified':False,'available_at_semantics':'UNKNOWN_NULL',
        'revision_semantics':'CURRENT_RETRIEVAL_NO_PROVIDER_REVISION_HISTORY_OR_ROW_REVISION_FLAG',
        'historical_definition_semantics':'CURRENT_DEFINITION_RETAINED_SEPARATELY_NOT_A_HISTORICAL_CROSSWALK',
        'release_schedule':'Thursday approximately 16:15 New York time for previous week; no historical release timestamp inferred',
        'fails_semantics':'Weekly cumulative amount, not unique failed trades or daily average. FR2004C instructions include weekends and holidays. Primer main text says business days but footnote also includes calendar days; no daily conversion applied.',
        'provider_asterisk_semantics':'MEANING_UNVERIFIED_NULL_VALUE_RAW_ASTERISK_RETAINED',
        'attribution_notice':NOTICE,'terms_url':DOCS['terms'],
        'research_usage':'2026_PLUS_OBSERVATION_ONLY_NO_TRAINING_TUNING_OR_BACKTEST',
        'coverage':'FIXED_28_OFFICIAL_SERIES_NO_LEGACY_ID_SPLICE_NO_DEALER_LEVEL_DATA',
        'qc':{'source_rows':len(rows)+before_start,'rows_before_requested_start':before_start,
              'value_status_counts':dict(Counter(r['value_status'] for r in rows)),
              'seriesbreak_row_counts':dict(Counter(r['seriesbreak'] for r in rows)),
              'latest_selected_date':max(x['max_date'] for x in freshness),
              'raw_byte_count':sum(len(v) for v in raw.values()),'parquet_roundtrip':'EXACT_ARROW_TABLE_MATCH'},
        'outputs':[{'dataset':DATASET,'source':'NYFED_OFFICIAL','date_column':'date',
                  'path':str(path),'sha256':common.sha256(path),'row_count':len(rows),
                  'min_date':rows[0]['date'],'max_date':rows[-1]['date'],'byte_count':path.stat().st_size,
                  'series_count':len(SERIES),'missing_value_rows':sum(r['value'] is None for r in rows)}]}
    manifest_path=paths.results_root/'official_research_intake'/run_id/FAMILY/'manifest.json'
    common.save_json(manifest_path,manifest)
    return manifest_path


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--as-of',required=True)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--acquire-only',action='store_true')
    args=parser.parse_args(argv);validate_as_of(args.as_of)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',args.run_id): raise ValueError('INVALID_RUN_ID')
    if not args.execute:
        print(json.dumps({'series':SERIES,'start':START,'as_of':args.as_of,'urls':plan(),'raw_limit':RAW_LIMIT}))
        return 0
    paths=common.resolve()
    receipts=acquire(paths,args.run_id,args.as_of)
    if not args.acquire_only:
        manifest=normalize(receipts,paths,args.run_id,args.as_of)
        print(json.dumps({'status':'VALIDATED_NOT_REGISTERED','manifest':str(manifest)}))
    else: print(json.dumps({'status':'ACQUIRED_ONLY','receipt_count':len(receipts)}))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
