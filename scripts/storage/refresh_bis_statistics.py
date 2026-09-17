"""Selected BIS policy rates and broad real exchange rates; official data only."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from collections import Counter
import calendar
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlencode

import pyarrow as pa
import pyarrow.parquet as pq
import requests

from scripts.storage import refresh_official_research_data as common

FAMILY='bis_statistics'
RAW_LIMIT=100*1024**2
TOTAL_LIMIT=300*1024**2
FLOOR=20*1024**3
DOCS={
    'api_docs':'https://stats.bis.org/api-doc/v2/',
    'api_initializer':'https://stats.bis.org/api-doc/v2/swagger-initializer.js',
    'policy_topic':'https://data.bis.org/topics/CBPOL',
    'eer_topic':'https://data.bis.org/topics/EER',
    'terms':'https://data.bis.org/help/legal',
    'policy_methodology_current':'https://www.bis.org/pages/statistics/cbpol-doc.pdf',
    'github_project':'https://github.com/bis-med-it/pysdmx',
    'github_license':'https://github.com/bis-med-it/pysdmx/blob/develop/LICENSE'}
DOCS['api_spec']='https://stats.bis.org/api-doc/v2/bis-stats-api-latest.yaml'
AREAS=('US','XM','JP','GB','CA','AU','CH','CN','IN','KR','BR','MX')
CONFIG={
    'policy':{'flow':'WS_CBPOL','dsd':'BIS_CBPOL','dimensions':['FREQ','REF_AREA'],
              'fixed':{'FREQ':'D'},'start':'1990-01-01','unit':'368',
              'dataset':'bis_central_bank_policy_rates_daily_current'},
    'eer':{'flow':'WS_EER','dsd':'BIS_EER','dimensions':['FREQ','EER_TYPE','EER_BASKET','REF_AREA'],
           'fixed':{'FREQ':'M','EER_TYPE':'R','EER_BASKET':'B'},'start':'1994-01','unit':'882',
           'dataset':'bis_real_effective_exchange_rates_monthly_current'}}
NS={'m':'http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message',
    's':'http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure',
    'c':'http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common'}
XSI='{http://www.w3.org/2001/XMLSchema-instance}'
SS='{http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/structurespecific}'
DATA_ACCEPT='application/vnd.sdmx.structurespecificdata+xml;version=2.1'
STRUCTURE_ACCEPT='application/vnd.sdmx.structure+xml;version=2.1'


def roots(paths,run_id):
    return (paths.results_root/'official_research_intake'/run_id/FAMILY,
            paths.cache_root/'official_research_intake'/run_id/'raw'/FAMILY)


def raw_file(receipt,paths,url,run_id,name):
    raw=receipt['raw'];path=Path(raw['local_path']).resolve()
    if (raw['status'] not in {'DOWNLOADED','CACHED'} or raw['source_reference']!=url
        or path.parent!=roots(paths,run_id)[1].resolve() or common.sha256(path)!=raw['sha256']
        or receipt['url']!=url or receipt['name']!=name or receipt['response']['status']!=200
        or raw['event_family']!=FAMILY or raw['document_kind']!='BIS_'+name.upper()):
        raise ValueError('BIS_RAW_IDENTITY_INVALID')
    meta=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    if (any(meta[k]!=raw[k] for k in ('source_reference','sha256','retrieval_timestamp_utc','event_family','document_kind','source'))
        or meta['byte_count']!=path.stat().st_size):
        raise ValueError('BIS_RAW_SIDECAR_MISMATCH')
    if datetime.fromisoformat(raw['retrieval_timestamp_utc'].replace('Z','+00:00')).tzinfo is None:
        raise ValueError('BIS_RETRIEVAL_TIME_INVALID')
    if datetime.fromisoformat(receipt['response']['observed_at_utc'].replace('Z','+00:00')).tzinfo is None:
        raise ValueError('BIS_RESPONSE_TIME_INVALID')
    length=next((v for k,v in receipt['response']['headers'].items() if k.lower()=='content-length'),None)
    if length is not None and int(length)!=path.stat().st_size: raise ValueError('BIS_HTTP_LENGTH_MISMATCH')
    return path


def fetch(paths,run_id,name,url,accept='*/*'):
    report,rawroot=roots(paths,run_id);receipt_path=report/(name+'_acquisition.json')
    if receipt_path.exists():
        receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
        if receipt['raw']['status']=='FAILED': raise ValueError('PRIOR_FAILED_REQUEST_PRESERVED')
        raw_file(receipt,paths,url,run_id,name)
        if receipt.get('request_accept',accept)!=accept: raise ValueError('REQUEST_FORMAT_CHANGED')
        return receipt
    if (report/'access_stop.json').exists(): raise ValueError('PRIOR_ACCESS_DENIAL_NO_RETRY')
    used=sum(p.stat().st_size for p in rawroot.glob('*.source')) if rawroot.exists() else 0
    if used>=RAW_LIMIT or min(shutil.disk_usage(paths.cache_root).free,shutil.disk_usage(paths.data_root).free)<FLOOR:
        raise ValueError('BIS_STORAGE_BUDGET_OR_DISK_FLOOR')
    response={};archive=common.archive_module(paths.repo_root)
    def download(target,timeout):
        time.sleep(.7)
        with requests.get(target,headers={'User-Agent':'US-Tech-Quant-official-data-integrity/1.0',
            'Accept':accept,'Accept-Encoding':'identity'},timeout=(15,60),stream=True,allow_redirects=False) as handle:
            response.update(status=handle.status_code,headers=dict(handle.headers),
                            observed_at_utc=datetime.now(timezone.utc).isoformat())
            if handle.status_code!=200: raise ValueError('HTTP_'+str(handle.status_code))
            chunks=[];size=0
            for chunk in handle.iter_content(65536):
                size+=len(chunk)
                if size+used>RAW_LIMIT: raise ValueError('BIS_RAW_SIZE_LIMIT')
                chunks.append(chunk)
            if not size: raise ValueError('EMPTY_RESPONSE')
            length=handle.headers.get('content-length')
            if length is not None and int(length)!=size: raise ValueError('INCOMPLETE_HTTP_BODY')
            return b''.join(chunks)
    archive._download_once=download
    raw=archive.acquire_url(url,FAMILY,'BIS_OFFICIAL_GITHUB' if 'github.com' in url else 'BIS_OFFICIAL',
                            'BIS_'+name.upper(),rawroot.parent,60,0,0)
    receipt={'name':name,'url':url,'request_accept':accept,'raw':asdict(raw),'response':response}
    common.save_json(receipt_path,receipt)
    if raw.status=='FAILED':
        if response.get('status') in {401,403,429}:
            common.save_json(report/'access_stop.json',{'url':url,'response_status':response['status'],
                'receipt_path':str(receipt_path),'reason':'ACCESS_DENIED_SOURCE_STOPPED'})
        raise ValueError('BIS_ACQUISITION_FAILED:'+name)
    return receipt


def plan(as_of):
    common.snapshot_day(as_of)
    result={name:(url,'*/*') for name,url in DOCS.items()}
    for kind,cfg in CONFIG.items():
        base='https://stats.bis.org/api/v2/'
        result[kind+'_structure']=(base+'structure/dataflow/BIS/'+cfg['flow']+'/1.0?references=descendants',STRUCTURE_ACCEPT)
        key='.'.join([*cfg['fixed'].values(),'+'.join(AREAS)])
        url=base+'data/dataflow/BIS/'+cfg['flow']+'/1.0/'+key
        result[kind+'_latest']=(url+'?lastNObservations=1',DATA_ACCEPT)
        result[kind+'_history']=(url+'?'+urlencode({'c[TIME_PERIOD]':'ge:'+cfg['start']+'+le:'+as_of}),DATA_ACCEPT)
    return result


def xml_root(raw,tag):
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('XML_EXTERNAL_DECLARATION_FORBIDDEN')
    root=ET.fromstring(raw)
    if root.tag!='{'+NS['m']+'}'+tag: raise ValueError('UNEXPECTED_SDMX_MESSAGE')
    if any(x.tag.split('}')[-1]=='Footer' or 'footer}' in x.tag for x in root.iter()):
        raise ValueError('SDMX_FOOTER_REQUIRES_REVIEW')
    return root


def parse_structure(raw,kind):
    cfg=CONFIG[kind];root=xml_root(raw,'Structure')
    flows=root.findall('.//s:Dataflow',NS);dsds=root.findall('.//s:DataStructure',NS)
    if len(flows)!=1 or len(dsds)!=1: raise ValueError('UNEXPECTED_STRUCTURE_COUNT')
    for node,identity in [(flows[0],cfg['flow']),(dsds[0],cfg['dsd'])]:
        if any(node.get(k)!=v for k,v in {'agencyID':'BIS','id':identity,'version':'1.0'}.items()):
            raise ValueError('STRUCTURE_IDENTITY_MISMATCH')
    ref=flows[0].find('s:Structure/Ref',NS)
    if ref is None or any(ref.get(k)!=v for k,v in {'agencyID':'BIS','id':cfg['dsd'],'version':'1.0'}.items()):
        raise ValueError('DATAFLOW_DSD_REFERENCE_MISMATCH')
    dimensions=dsds[0].findall('s:DataStructureComponents/s:DimensionList/*',NS)
    if [x.get('id') for x in sorted(dimensions,key=lambda x:int(x.get('position')))]!=cfg['dimensions']+['TIME_PERIOD']:
        raise ValueError('DIMENSION_ORDER_CHANGED')
    lists={}
    for node in root.findall('.//s:Codelist',NS):
        key=node.get('id')
        if key in lists or node.get('agencyID')!='BIS': raise ValueError('CODELIST_IDENTITY_AMBIGUOUS')
        values={}
        for code in node.findall('s:Code',NS):
            names=[x.text for x in code.findall('c:Name',NS) if x.get('{http://www.w3.org/XML/1998/namespace}lang')=='en']
            if len(names)!=1 or code.get('id') in values: raise ValueError('CODELIST_LABEL_AMBIGUOUS')
            values[code.get('id')]=names[0]
        lists[key]=values
    fields={};attributes=dsds[0].findall('s:DataStructureComponents/s:AttributeList/s:Attribute',NS)
    for node in [*dimensions,*attributes]:
        ref=node.find('s:LocalRepresentation/s:Enumeration/Ref',NS)
        fields[node.get('id')]=ref.get('id') if ref is not None else None
        if ref is not None and ref.get('id') not in lists: raise ValueError('CODELIST_REFERENCE_MISSING')
    if not set(AREAS)<=set(lists[fields['REF_AREA']]): raise ValueError('SELECTED_COUNTRY_NOT_IN_CODELIST')
    unit_label=lists[fields['UNIT_MEASURE']][cfg['unit']]
    if unit_label!=('Per cent per year' if kind=='policy' else 'Index, 2020 = 100'):
        raise ValueError('UNIT_DEFINITION_CHANGED')
    return {'flow':cfg['flow'],'dsd':cfg['dsd'],'dimensions':cfg['dimensions'],
            'attributes':[x.get('id') for x in attributes],'field_codelists':fields,'codelists':lists,
            'dataflow_attributes':dict(flows[0].attrib),'dsd_attributes':dict(dsds[0].attrib)}


def exact_number(text):
    if text is None or text in {'','NaN'}: return None
    if not re.fullmatch(r'-?\d{1,26}(?:\.\d{1,12})?',text):
        raise ValueError('UNRECOGNIZED_OR_INEXACT_VALUE')
    with localcontext() as context:
        context.prec=50
        return Decimal(text).quantize(Decimal('.000000000001'))


def attributes(node,structure,transport=()):
    result={k:v for k,v in node.attrib.items() if k not in transport}
    for key,value in result.items():
        if key not in structure['field_codelists'] and key!='OBS_VALUE':
            raise ValueError('UNDECLARED_ATTRIBUTE:'+key)
        cl=structure['field_codelists'].get(key)
        if cl is not None and value not in structure['codelists'][cl]:
            raise ValueError('UNKNOWN_CODE:'+key+':'+value)
    return result


def overlay(*levels):
    result={}
    for level in levels:
        for key,value in level.items():
            if key in result and result[key]!=value: raise ValueError('CONFLICTING_INHERITED_ATTRIBUTE:'+key)
            result[key]=value
    return result


def parse_data(raw,kind,structure,as_of,areas=AREAS):
    cfg=CONFIG[kind];root=xml_root(raw,'StructureSpecificData');header=root.find('m:Header',NS)
    if header is None or header.findtext('m:Test',namespaces=NS)!='false': raise ValueError('NON_PRODUCTION_DATA')
    refs=header.findall('m:Structure/c:StructureUsage/Ref',NS)
    if len(refs)!=1 or any(refs[0].get(k)!=v for k,v in {'agencyID':'BIS','id':cfg['flow'],'version':'1.0'}.items()):
        raise ValueError('DATAFLOW_REFERENCE_MISMATCH')
    prepared=header.findtext('m:Prepared',namespaces=NS)
    if not prepared or datetime.fromisoformat(prepared.replace('Z','+00:00')).tzinfo is None:
        raise ValueError('PREPARED_TIMESTAMP_INVALID')
    if header.findtext('m:DataSetAction',namespaces=NS)!='Information': raise ValueError('DATASET_ACTION_REQUIRES_REVIEW')
    datasets=root.findall('m:DataSet',NS)
    if len(datasets)!=1: raise ValueError('UNEXPECTED_DATASET_COUNT')
    ds=datasets[0];base=attributes(ds,structure,(XSI+'type',SS+'dataScope',SS+'structureRef'))
    if ds.get(SS+'structureRef')!='BIS_'+cfg['flow']+'_1_0': raise ValueError('STRUCTURE_REFERENCE_MISMATCH')
    groups=[];series_meta={};rows=[];seen=set();group_used=set()
    for node in ds:
        if node.tag=='Group':
            attrs=attributes(node,structure,(XSI+'type',));keys=set(attrs)&set(cfg['dimensions'])
            if not keys or list(node): raise ValueError('INVALID_GROUP')
            groups.append((dict(node.attrib),attrs,keys))
        elif node.tag!='Series': raise ValueError('UNSUPPORTED_DATASET_CHILD')
    for series_no,node in enumerate(ds.findall('Series'),1):
        attrs=attributes(node,structure)
        if attrs.get('REF_AREA') not in areas or any(attrs.get(k)!=v for k,v in cfg['fixed'].items()):
            raise ValueError('UNREQUESTED_SERIES')
        series_id='.'.join(attrs[k] for k in cfg['dimensions'])
        if series_id in series_meta: raise ValueError('DUPLICATE_SERIES')
        matched=[];group_levels=[]
        for i,(original,group,keys) in enumerate(groups):
            if all(attrs.get(k)==group[k] for k in keys):
                matched.append(original);group_levels.append(group);group_used.add(i)
        inherited=overlay(base,*group_levels,attrs)
        if inherited.get('UNIT_MEASURE')!=cfg['unit']: raise ValueError('UNIT_MISSING_OR_CHANGED')
        if kind=='policy' and inherited.get('UNIT_MULT')!='0': raise ValueError('RATE_UNIT_MULT_CHANGED')
        if kind=='eer' and inherited.get('COLLECTION')!='A': raise ValueError('REER_AVERAGING_CHANGED')
        series_meta[series_id]={'source_series_ordinal':series_no,'dataset_attributes':dict(ds.attrib),
            'group_attributes':matched,'series_attributes':dict(node.attrib),'effective_attributes':inherited}
        if not len(node): raise ValueError('EMPTY_SERIES')
        for ordinal,obs in enumerate(node,1):
            if obs.tag!='Obs' or len(obs) or (obs.text and obs.text.strip()): raise ValueError('UNSUPPORTED_OBSERVATION_CONTENT')
            original=attributes(obs,structure);effective=overlay(inherited,original)
            period=original.get('TIME_PERIOD','');daily=kind=='policy'
            pattern=r'\d{4}-\d{2}-\d{2}' if daily else r'\d{4}-\d{2}'
            if not re.fullmatch(pattern,period): raise ValueError('INVALID_OBSERVATION_PERIOD')
            start=date.fromisoformat(period if daily else period+'-01')
            end=start if daily else start.replace(day=calendar.monthrange(start.year,start.month)[1])
            if period<cfg['start'] or start>date.fromisoformat(as_of): raise ValueError('OUTSIDE_REQUESTED_TIME_SCOPE')
            if not daily and end>date.fromisoformat(as_of): raise ValueError('INCOMPLETE_PROVIDER_MONTH_REQUIRES_REVIEW')
            identity=(series_id,period)
            if identity in seen: raise ValueError('DUPLICATE_SERIES_PERIOD')
            seen.add(identity);status=effective.get('OBS_STATUS');conf=effective.get('OBS_CONF')
            if status is None or conf not in {None,'F'}: raise ValueError('STATUS_MISSING_OR_NONPUBLIC_OBSERVATION')
            text=original.get('OBS_VALUE');number=exact_number(text)
            if (number is None)!=(status in {'H','L','M','Q'}): raise ValueError('MISSING_VALUE_STATUS_CONFLICT')
            if kind=='eer' and number is not None and number<=0: raise ValueError('NONPOSITIVE_REER_INDEX')
            label=lambda key: structure['codelists'][structure['field_codelists'][key]].get(effective.get(key))
            rows.append({'date':start.isoformat(),'period':period,'period_end':end.isoformat(),
                'date_semantics':'OBSERVATION_DAY_NOT_RELEASE' if daily else 'MONTH_START_LABEL_NOT_RELEASE',
                'series_id':series_id,'ref_area':attrs['REF_AREA'],'ref_area_name':label('REF_AREA'),
                'frequency':attrs['FREQ'],'eer_type':attrs.get('EER_TYPE'),'eer_basket':attrs.get('EER_BASKET'),
                'value':number,'provider_value_text':text,
                'value_status':'SOURCE_MISSING' if number is None else 'FORECAST' if status=='F' else 'OBSERVED',
                'obs_status':status,'obs_status_label':label('OBS_STATUS'),
                'obs_conf':conf,'obs_conf_label':label('OBS_CONF'),
                'provider_pre_break_text':effective.get('OBS_PRE_BREAK'),
                'pre_break_value':exact_number(effective.get('OBS_PRE_BREAK')),
                'unit_measure':effective['UNIT_MEASURE'],'unit_label':label('UNIT_MEASURE'),
                'unit_mult':effective.get('UNIT_MULT'),'provider_decimals':effective.get('DECIMALS'),
                'collection':effective.get('COLLECTION'),'collection_label':label('COLLECTION') if 'COLLECTION' in structure['field_codelists'] else None,
                'seasonal_adjustment':'NOT_SEASONALLY_ADJUSTED_PER_BIS_TOPIC',
                'source_ref':effective.get('SOURCE_REF'),'compilation':effective.get('COMPILATION'),
                'supp_info_breaks':effective.get('SUPP_INFO_BREAKS'),
                'provider_title':effective.get('TITLE',effective.get('TITLE_TS')),
                'source_series_ordinal':series_no,'source_observation_ordinal':ordinal,
                'source_observation_attributes_json':json.dumps(dict(obs.attrib),sort_keys=True,ensure_ascii=False,separators=(',',':'))})
    if {x['ref_area'] for x in rows}!=set(areas) or len(series_meta)!=len(areas): raise ValueError('REQUESTED_COUNTRY_SET_INCOMPLETE')
    if group_used!=set(range(len(groups))): raise ValueError('UNMATCHED_GROUP')
    metadata={'provider_prepared':prepared,'header_xml':ET.tostring(header,encoding='unicode'),
              'dataset_attributes':dict(ds.attrib),'series':series_meta}
    return rows,metadata


def validate_latest(rows,metadata,latest,latest_metadata,kind,as_of):
    if len(latest)!=len(metadata['series']): raise ValueError('LATEST_NOT_ONE_OBSERVATION_PER_SERIES')
    lookup={r['series_id']:r for r in latest};freshness=[]
    for identity,meta in metadata['series'].items():
        items=sorted((x for x in rows if x['series_id']==identity),key=lambda x:x['period'])
        tail=items[-1];other=lookup[identity]
        if any(tail[k]!=other[k] for k in tail if k not in {'source_series_ordinal','source_observation_ordinal'}):
            raise ValueError('LATEST_OBSERVATION_DIFFERS')
        if any(meta[k]!=latest_metadata['series'][identity][k] for k in ['dataset_attributes','group_attributes','series_attributes','effective_attributes']):
            raise ValueError('LATEST_SERIES_METADATA_DIFFERS')
        first=date.fromisoformat(items[0]['date']);last=date.fromisoformat(tail['date'])
        dates={x['date'] for x in items};expected=[];current=first
        while current<=last:
            expected.append(current)
            current=(current+timedelta(days=1) if kind=='policy' else
                     date(current.year+int(current.month==12),current.month%12+1,1))
        absent=[x.isoformat() for x in expected if x.isoformat() not in dates]
        if kind=='eer' and absent: raise ValueError('MONTHLY_INTERNAL_PERIOD_MISSING')
        freshness.append({'series_id':identity,'ref_area':tail['ref_area'],'row_count':len(items),
            'min_period':items[0]['period'],'max_period':tail['period'],'min_date':items[0]['date'],'max_date':tail['date'],
            'latest_provider_value_text':tail['provider_value_text'],'latest_status':'EXACT_MATCH_OFFICIAL_LAST_N_1',
            'source_status_counts':dict(Counter(x['obs_status'] for x in items)),
            'missing_values':sum(x['value'] is None for x in items),
            'calendar_dates_without_source_record':len(absent),'calendar_absence_sample':absent[:12],
            'weekend_source_records':sum(date.fromisoformat(x['date']).weekday()>=5 for x in items) if kind=='policy' else None,
            'adjacent_equal_raw_values':sum(a['provider_value_text']==b['provider_value_text'] for a,b in zip(items,items[1:])),
            'requested_start':CONFIG[kind]['start'],'as_of':as_of,
            'calendar_interpretation':'PROVIDER_COUNTRY_CALENDARS_VARY_NO_MISSING_DAY_INFERENCE' if kind=='policy' else 'CONTIGUOUS_MONTHS',
            'latest_is_provider_observation_boundary_not_publication_date':True})
    return freshness


def normalize(receipts,paths,run_id,as_of):
    expected=plan(as_of)
    if set(receipts)!=set(expected): raise ValueError('ACQUISITION_PLAN_INCOMPLETE')
    raw={}
    for name,(url,accept) in expected.items():
        receipt=receipts[name]
        if receipt.get('request_accept',accept)!=accept: raise ValueError('REQUEST_FORMAT_CHANGED')
        if receipt['raw']['retrieval_timestamp_utc'][:10]>as_of: raise ValueError('RETRIEVAL_AFTER_AS_OF')
        raw[name]=raw_file(receipt,paths,url,run_id,name).read_bytes()
    contract={'as_of':as_of,'areas':list(AREAS),'series_config':CONFIG,
        'inputs':{name:{k:r['raw'][k] for k in ('source_reference','sha256','retrieval_timestamp_utc')} for name,r in receipts.items()},
        'normalizer_sha256':common.sha256(__file__),'common_sha256':common.sha256(common.__file__),
        'archive_sha256':common.sha256(paths.repo_root/'fast6/src/fast6/acquisition.py')}
    version=hashlib.sha256(common.json_bytes(contract)).hexdigest()[:24]
    folder=paths.data_root/'reference/official_research'/FAMILY/version
    outputs=[];freshness={};metadata={};report,rawroot=roots(paths,run_id)
    for kind,cfg in CONFIG.items():
        structure=parse_structure(raw[kind+'_structure'],kind)
        rows,meta=parse_data(raw[kind+'_history'],kind,structure,as_of)
        latest,latest_meta=parse_data(raw[kind+'_latest'],kind,structure,as_of)
        freshness[kind]=validate_latest(rows,meta,latest,latest_meta,kind,as_of)
        metadata[kind]={'structure':structure,'history':meta,'latest':latest_meta}
        receipt=receipts[kind+'_history']['raw']
        for row in rows:
            row.update(source='BIS_OFFICIAL',source_id=receipt['sha256'],source_url=receipt['source_reference'],
                structure_source_id=receipts[kind+'_structure']['raw']['sha256'],
                observed_at_utc=receipt['retrieval_timestamp_utc'],available_at_utc=None,
                vintage_semantics=common.VINTAGE)
        schema=pa.schema([(key,pa.decimal128(38,12) if key in {'value','pre_break_value'} else
            pa.int64() if key in {'source_series_ordinal','source_observation_ordinal'} else
            pa.timestamp('us',tz='UTC') if key=='available_at_utc' else pa.string()) for key in rows[0]])
        table=pa.Table.from_pylist(rows,schema=schema)
        used=sum(p.stat().st_size for directory in [rawroot,report,folder] for p in directory.glob('*') if p.is_file())
        # Atomic replacement does not duplicate the temporary file; reserve its uncompressed size plus metadata overhead.
        reserve=table.nbytes+16*1024**2
        if used+reserve>TOTAL_LIMIT or min(shutil.disk_usage(paths.data_root).free,shutil.disk_usage(paths.cache_root).free)<FLOOR+reserve:
            raise ValueError('BIS_TOTAL_BUDGET_OR_DISK_FLOOR')
        folder.mkdir(parents=True,exist_ok=True);path=folder/(cfg['dataset']+'.parquet');temp=path.with_suffix('.parquet.tmp')
        if temp.exists(): raise ValueError('PRIOR_PARTIAL_OUTPUT_PRESERVED')
        pq.write_table(table,temp,compression='zstd')
        if not table.equals(pq.read_table(temp)): raise ValueError('PARQUET_ROUNDTRIP_MISMATCH')
        if path.exists():
            if common.sha256(path)!=common.sha256(temp): raise ValueError('EXISTING_OUTPUT_PRESERVED')
            temp.unlink()
        else: temp.replace(path)
        outputs.append({'dataset':cfg['dataset'],'source':'BIS_OFFICIAL','date_column':'date','path':str(path),
            'sha256':common.sha256(path),'row_count':len(rows),'min_date':min(r['date'] for r in rows),
            'max_date':max(r['date'] for r in rows),'min_period':min(r['period'] for r in rows),
            'max_period':max(r['period'] for r in rows),'series_count':len(AREAS),
            'missing_value_rows':sum(r['value'] is None for r in rows),'byte_count':path.stat().st_size})
    metadata_path=report/'series_metadata.json';common.save_json(metadata_path,metadata)
    manifest={'role':'BIS_STATISTICS_INTAKE','status':'VALIDATED_DATA_ONLY','as_of':as_of,'contract':contract,
        'inputs':receipts,'outputs':outputs,'freshness':freshness,
        'series_metadata':{'path':str(metadata_path),'sha256':common.sha256(metadata_path)},
        'raw_byte_count':sum(len(value) for value in raw.values()),'historical_pit_certified':False,
        'availability_semantics':'UNKNOWN_NULL; Prepared is response generation, observation period is not disclosure time.',
        'revision_semantics':'CURRENT_VINTAGE; original SDMX status and pre-break values retained; no original release/revision history certified.',
        'github_project':DOCS['github_project'],'github_license':'Apache-2.0 applies to pysdmx code, not BIS data; no package installed or code copied.',
        'data_terms_url':DOCS['terms'],
        'attribution':'Source: Bank for International Settlements (BIS). Policy rates also credit the national central bank in each series SOURCE_REF. No BIS endorsement or affiliation implied.',
        'data_terms_summary':'BIS statistics may be used subject to the official legal terms, including attribution, no misleading endorsement, and no additional charge attributable to BIS statistics in a commercial product; warranty disclaimers apply. Any translation must be labelled unofficial.',
        'policy_methodology':'Percent per year, end of period, not seasonally adjusted. BIS-spliced national policy instruments and historical proxies; raw COMPILATION/SUPP_INFO_BREAKS retained without rewriting.',
        'eer_methodology':'Monthly broad real effective exchange rate, 2020=100, not seasonally adjusted. Higher means real appreciation. Geometric trade weights adjusted by relative consumer prices; weights/methodology can change. It is not a valuation misalignment measure.',
        'limitations':['Only the fixed 12 economy series are covered; provider tails differ and are not filled forward.',
            'Daily country calendars and coverage change historically; absent calendar dates are reported, not certified as missing downloads. Raw NaN and OBS_STATUS remain distinguishable.',
            'Daily data repeat unchanged rates and are not change-date-only events; no common business-day calendar or effective/publication lag is inferred.',
            'Latest EER observation is a completed provider month, not a daily freshness guarantee. Date is month-start label; period_end retained.',
            'Current series descriptions may include later method changes; they are not point-in-time historical metadata.',
            'SDMX provider omits some DSD Mandatory attributes, such as policy TIME_FORMAT; absent fields are not synthesized.',
            '2026 and later rows are intake/integrity only, not authorized for training, tuning or backtests.'],
        'qc':{'latest_observation_field_comparisons':24,'parquet_roundtrip':'EXACT_ARROW_TABLE_MATCH','values':'EXACT_DECIMAL_38_12_NO_FLOAT',
              'country_set':'EXACT_12_PER_CLASS','monthly_calendar':'NO_INTERNAL_MONTH_GAPS'}}
    target=report/'manifest.json';common.save_json(target,manifest);return target


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id',required=True);parser.add_argument('--as-of',required=True)
    parser.add_argument('--execute',action='store_true');parser.add_argument('--acquire-only',action='store_true')
    args=parser.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',args.run_id): raise ValueError('INVALID_RUN_ID')
    requests_plan=plan(args.as_of)
    if not args.execute:
        print(json.dumps({'as_of':args.as_of,'plan':requests_plan,'raw_limit':RAW_LIMIT,'total_limit':TOTAL_LIMIT}));return 0
    paths=common.resolve();receipts={name:fetch(paths,args.run_id,name,url,accept) for name,(url,accept) in requests_plan.items()}
    if args.acquire_only: print(json.dumps({'status':'ACQUIRED_ONLY','receipts':len(receipts)}));return 0
    target=normalize(receipts,paths,args.run_id,args.as_of)
    print(json.dumps({'status':'VALIDATED_NOT_REGISTERED','manifest':str(target)}));return 0


if __name__=='__main__':
    raise SystemExit(main())
