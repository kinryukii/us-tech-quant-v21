"""Bounded official G.17 technology-industry current-vintage intake."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime, timezone
from decimal import Decimal
import calendar
from html.parser import HTMLParser
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import time
import xml.etree.ElementTree as ET
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq
import requests

from scripts.storage import refresh_official_research_data as common
from scripts.storage.refresh_frb_h10 import ReleaseTable

FAMILY='frb_g17'
RAW_LIMIT=150*1024**2
TOTAL_LIMIT=350*1024**2
FLOOR=20*1024**3
BASE='https://www.federalreserve.gov/releases/g17/'
DOCS={
    'release':BASE+'Current/default.htm',
    'download':BASE+'download.htm',
    'about':BASE+'about.htm',
    'data_format':BASE+'data_format.htm',
    'ip_table1':BASE+'Current/ipdisk/g17tab1.txt',
    'ip_table2':BASE+'Current/ipdisk/g17tab2.txt',
    'capacity_table':BASE+'Current/ipdisk/g17caputl.txt',
    'series_revisions':BASE+'g17_revision_series.htm',
    'github_project':'https://github.com/mortada/fredapi',
    'github_license':'https://github.com/mortada/fredapi/blob/master/LICENSE'}
DOCS.update(ip_notes=BASE+'IpNotes.htm',capacity_notes=BASE+'CapNotes.htm',release_dates=BASE+'default.htm',
    website_policies='https://www.federalreserve.gov/website-linking-policies.htm',
    disclaimer='https://www.federalreserve.gov/disclaimer.htm',
    latest_ip4=BASE+'Current/table4.htm',latest_ip5=BASE+'Current/table5.htm',latest_utl7=BASE+'Current/table7.htm')
HISTORY={'ip_sa':BASE+'Current/ipdisk/ip_sa.txt','utl_sa':BASE+'Current/ipdisk/utl_sa.txt',
         'cap_sa':BASE+'Current/ipdisk/cap_sa.txt','sdmx_zip':BASE+'data/FRB_g17_xml.zip'}
START='1990-01-01'
INDUSTRIES=('GMF','G333','G334','G3341','G3342','G3344','G335')
EXTRA_IP=('B52100','B52120','HITEK2')
SERIES={**{'IP.'+code+'.S':('IP_MAJOR_INDUSTRY_GROUPS' if code in {'GMF','G333','G334','G335'}
                            else 'IP_DURABLE_GOODS_DETAIL') for code in INDUSTRIES},
        **{'IP.'+code+'.S':('IP_SPECIAL_AGGREGATES' if code=='HITEK2' else 'IP_MARKET_GROUPS') for code in EXTRA_IP},
        **{measure+'.'+code+'.S':measure for measure in ('CAP','CAPUTL') for code in INDUSTRIES}}
DATASET='frb_g17_technology_industry_monthly_current'
NS={'m':'http://www.SDMX.org/resources/SDMXML/schemas/v1_0/message',
    's':'http://www.SDMX.org/resources/SDMXML/schemas/v1_0/structure',
    'c':'http://www.SDMX.org/resources/SDMXML/schemas/v1_0/common',
    'f':'http://www.federalreserve.gov/structure/compact/common'}


def roots(paths,run_id):
    return (paths.results_root/'official_research_intake'/run_id/FAMILY,
            paths.cache_root/'official_research_intake'/run_id/'raw'/FAMILY)


def verified_raw(receipt,paths,run_id,name,url):
    path=Path(receipt['raw']['local_path']).resolve();raw=receipt['raw']
    if (path.parent!=roots(paths,run_id)[1].resolve() or receipt['name']!=name or receipt['url']!=url
        or receipt['response']['status']!=200 or raw['status'] not in {'DOWNLOADED','CACHED'}
        or raw['source_reference']!=url or common.sha256(path)!=raw['sha256']):
        raise ValueError('G17_RAW_IDENTITY_MISMATCH')
    meta=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    if (meta['byte_count']!=path.stat().st_size or any(raw[key]!=meta[key] for key in
        ['source_reference','sha256','retrieval_timestamp_utc','event_family','source','document_kind'])):
        raise ValueError('G17_SIDECAR_IDENTITY_MISMATCH')
    if raw['event_family']!=FAMILY or raw['document_kind']!='G17_'+name.upper():
        raise ValueError('G17_RAW_KIND_MISMATCH')
    if datetime.fromisoformat(raw['retrieval_timestamp_utc'].replace('Z','+00:00')).tzinfo is None:
        raise ValueError('G17_RETRIEVAL_TIME_INVALID')
    if datetime.fromisoformat(receipt['response']['observed_at_utc'].replace('Z','+00:00')).tzinfo is None:
        raise ValueError('G17_RESPONSE_TIME_INVALID')
    length=next((v for k,v in receipt['response']['headers'].items() if k.lower()=='content-length'),None)
    if length is not None and int(length)!=path.stat().st_size:raise ValueError('G17_HTTP_LENGTH_MISMATCH')
    return path


def fetch(paths,run_id,name,url):
    report,rawroot=roots(paths,run_id);receipt_path=report/(name+'_acquisition.json')
    if receipt_path.exists():
        receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
        verified_raw(receipt,paths,run_id,name,url);return receipt
    if (report/'access_stop.json').exists(): raise ValueError('G17_PRIOR_ACCESS_DENIAL_STOPPED')
    used=sum(p.stat().st_size for p in rawroot.glob('*.source'))
    if used>=RAW_LIMIT or min(shutil.disk_usage(paths.cache_root).free,shutil.disk_usage(paths.data_root).free)<FLOOR+RAW_LIMIT:
        raise ValueError('G17_STORAGE_BUDGET_OR_FLOOR')
    capture=common.archive_module(paths.repo_root);response={}
    def download(target,timeout):
        time.sleep(.6)
        with requests.get(target,headers={'User-Agent':'US-Tech-Quant-official-data-integrity/1.0','Accept-Encoding':'identity'},
                          stream=True,timeout=(15,60),allow_redirects=False) as handle:
            response.update(status=handle.status_code,headers=dict(handle.headers),observed_at_utc=common.utc_now())
            if handle.status_code!=200: raise ValueError('HTTP_'+str(handle.status_code))
            chunks=[];size=0
            for chunk in handle.iter_content(65536):
                size+=len(chunk)
                if size+used>RAW_LIMIT: raise ValueError('G17_RAW_BUDGET_EXCEEDED')
                chunks.append(chunk)
            if not size or (handle.headers.get('content-length') is not None and int(handle.headers['content-length'])!=size):
                raise ValueError('G17_HTTP_BODY_INCOMPLETE')
            return b''.join(chunks)
    capture._download_once=download
    raw=capture.acquire_url(url,FAMILY,'GITHUB_REFERENCE' if 'github.com' in url else 'FRB_OFFICIAL',
                            'G17_'+name.upper(),rawroot.parent,60,0,0)
    receipt={'name':name,'url':url,'raw':asdict(raw),'response':response};common.save_json(receipt_path,receipt)
    if raw.status=='FAILED':
        if response.get('status') in {401,403,429}:common.save_json(report/'access_stop.json',{'url':url,'response':response})
        raise ValueError('G17_ACQUISITION_FAILED:'+name)
    verified_raw(receipt,paths,run_id,name,url);return receipt


def month_end(period):
    if not re.fullmatch(r'\d{4}-\d{2}',period): raise ValueError('G17_MONTH_FORMAT_INVALID')
    first=date.fromisoformat(period+'-01')
    return first.replace(day=calendar.monthrange(first.year,first.month)[1]).isoformat()


def number(text,status='A'):
    if status=='ND':
        if text!='-9999': raise ValueError('G17_MISSING_SENTINEL_CHANGED')
        return None
    if status!='A' or not isinstance(text,str) or not re.fullmatch(r'\d{1,12}\.\d{4}',text):
        raise ValueError('G17_VALUE_OR_STATUS_REQUIRES_REVIEW')
    result=Decimal(text)
    if result<=0: raise ValueError('G17_NONPOSITIVE_INDEX_OR_RATE')
    return result


def parse_release(raw,as_of):
    text=raw.decode('utf-8-sig')
    if 'Industrial Production and Capacity Utilization' not in text: raise ValueError('G17_RELEASE_IDENTITY_MISSING')
    found=re.findall(r'Release Date:\s*([A-Za-z]+ \d{1,2}, \d{4})',text)
    if len(found)!=1: raise ValueError('G17_RELEASE_DATE_MISSING')
    released=datetime.strptime(found[0],'%B %d, %Y').date().isoformat()
    if released>as_of: raise ValueError('G17_RELEASE_AFTER_AS_OF')
    if '2017=100' not in text and '2017 = 100' not in text: raise ValueError('G17_CURRENT_BASE_YEAR_CHANGED')
    return {'release_date':released,'raw_release_date_text':found[0],
        'release_time_semantics':'Monthly schedule 09:15 America/New_York; actual historical availability not inferred',
        'annual_revision_notice_present':'autumn of 2026' in text and '2022' in text}


def parse_text(raw,measure,latest_period,selected):
    """Official year rows use fixed-width month cells; never split away blank cells."""
    text=raw.decode('utf-8-sig');rows={};descriptions={};active=None;seen_years=set()
    for line_no,line in enumerate(text.splitlines(),1):
        if not line.strip(): continue
        header=re.fullmatch(r'"([A-Z0-9@._-]+): (.*)"',line)
        if header:
            active=header[1]
            if active in selected:
                if active in descriptions: raise ValueError('G17_DUPLICATE_TEXT_SERIES')
                parts=header[2].split('  NAICS=')
                if len(parts)>2: raise ValueError('G17_DESCRIPTION_NAICS_AMBIGUOUS')
                descriptions[active]={'description':parts[0],'naics_current':parts[1] if len(parts)==2 else None,
                    'description_line':line,'description_line_number':line_no}
            continue
        match=re.fullmatch(r'"([A-Z0-9@._-]+)"\s+(\d{4})\s+.*',line)
        if not match or match[1]!=active: raise ValueError('G17_TEXT_RECORD_WITHOUT_MATCHING_DESCRIPTION')
        if active not in selected: continue
        if (active,match[2]) in seen_years: raise ValueError('G17_DUPLICATE_TEXT_YEAR')
        seen_years.add((active,match[2]));year=int(match[2])
        if line[16:20]!=match[2]: raise ValueError('G17_TEXT_YEAR_COLUMN_CHANGED')
        # Actual files: year at zero-based16; 10-character month cells start at23.
        # The saved format page describes different month-position endpoints; retain this discrepancy.
        if line[20:23].strip() or len(line)>143 or not line[:16].strip()=='"'+active+'"':
            raise ValueError('G17_TEXT_LAYOUT_CHANGED')
        padded=line.ljust(143)
        for month in range(1,13):
            period=f'{year:04d}-{month:02d}';cell=padded[23+(month-1)*10:33+(month-1)*10]
            token=cell.strip()
            if not START[:7]<=period<=latest_period:
                if period>latest_period and token: raise ValueError('G17_TEXT_HAS_UNEXPECTED_FUTURE_MONTH')
                continue
            if not token: raise ValueError('G17_TEXT_INTERNAL_EMPTY_MONTH')
            status='ND' if token=='-9999' else 'A';value=number(token,status)
            identity=(measure+'.'+active+'.S',month_end(period))
            if identity in rows: raise ValueError('G17_DUPLICATE_TEXT_OBSERVATION')
            rows[identity]={'value':value,'provider_value_text':token,'source_text_cell':cell,
                'source_text_line':line,'source_text_line_number':line_no,'source_month_slot':month}
    if set(descriptions)!=set(selected): raise ValueError('G17_TEXT_SELECTED_SERIES_MISSING')
    return rows,descriptions


def parse_structure(raw):
    if b'<!DOCTYPE' in raw or b'<!ENTITY' in raw: raise ValueError('G17_XML_EXTERNAL_DECLARATION')
    root=ET.fromstring(raw)
    if root.tag!='{'+NS['m']+'}Structure': raise ValueError('G17_STRUCTURE_MESSAGE_INVALID')
    codelists={}
    for node in root.findall('m:CodeLists/s:CodeList',NS):
        if node.get('id') in codelists or node.get('agency')!='FRB': raise ValueError('G17_CODELIST_AMBIGUOUS')
        values={}
        for child in node.findall('s:Code',NS):
            code=child.get('value')
            if code in values: raise ValueError('G17_DUPLICATE_CODE')
            values[code]=child.findtext('s:Description',namespaces=NS)
        codelists[node.get('id')]=values
    for cl,code,label in [('CL_FREQ','129','Monthly'),('CL_SA','SA','Seasonally adjusted'),
                         ('CL_UNIT','Index:_2017_100','Index: 2017 = 100'),('CL_UNIT','Percentage','Percentage'),
                         ('CL_UNIT_MULT','1','One'),('CL_OBS_STATUS','A','Normal'),('CL_OBS_STATUS','ND','No data')]:
        if codelists.get(cl,{}).get(code)!=label: raise ValueError('G17_EXPECTED_CODE_DEFINITION_CHANGED')
    return codelists


def parse_sdmx(raw,release,selected=SERIES):
    rows={};metadata={};copies={};zip_manifest=[]
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names=[x.filename for x in archive.infolist()]
        if len(names)!=len(set(names)) or not {'G17_data.xml','G17_struct.xml'}<=set(names):
            raise ValueError('G17_ZIP_MEMBERS_INVALID')
        if sum(x.file_size for x in archive.infolist())>120*1024**2:
            raise ValueError('G17_UNCOMPRESSED_BUDGET_EXCEEDED')
        for info in archive.infolist():
            if Path(info.filename).name!=info.filename or info.flag_bits&1: raise ValueError('G17_UNSAFE_ZIP_MEMBER')
            zip_manifest.append({'name':info.filename,'byte_count':info.file_size,'compressed_bytes':info.compress_size,'crc32':info.CRC})
        if archive.testzip() is not None: raise ValueError('G17_ZIP_CRC_MISMATCH')
        codelists=parse_structure(archive.read('G17_struct.xml'));payload=archive.read('G17_data.xml')
    if b'<!DOCTYPE' in payload or b'<!ENTITY' in payload: raise ValueError('G17_XML_EXTERNAL_DECLARATION')
    header=None;dataset=None;dataset_ordinal=0;series_ordinal=0;root=None
    for event,node in ET.iterparse(io.BytesIO(payload),events=('start','end')):
        if node.tag.split('}')[-1] in {'Error','Footer'}:raise ValueError('G17_SDMX_PROVIDER_ERROR_OR_FOOTER')
        if root is None:
            root=node
            if root.tag!='{'+NS['m']+'}MessageGroup': raise ValueError('G17_DATA_MESSAGE_INVALID')
        if event=='start' and node.tag=='{'+NS['f']+'}DataSet':
            dataset=dict(node.attrib);dataset_ordinal+=1;series_ordinal=0
        if event=='end' and node.tag=='{'+NS['m']+'}Header':
            if node.findtext('m:ID',namespaces=NS)!='G17' or node.findtext('m:Test',namespaces=NS)!='false':
                raise ValueError('G17_HEADER_IDENTITY_INVALID')
            prepared=node.findtext('m:Prepared',namespaces=NS)
            if not prepared: raise ValueError('G17_PREPARED_MISSING')
            datetime.fromisoformat(prepared)
            header={'prepared_timestamp_text':prepared,'header_xml':ET.tostring(node,encoding='unicode')}
        if event!='end' or not node.tag.endswith('}Series'): continue
        series_ordinal+=1;identity=node.get('SERIES_NAME')
        if identity in selected:
            attrs=dict(node.attrib);measure,code,_=identity.split('.')
            expected={'CURRENCY':'NA','FREQ':'129','SA':'SA','SERIES_CODE':code,'SERIES_NAME':identity,
                      'UNIT':'Percentage' if measure=='CAPUTL' else 'Index:_2017_100','UNIT_MULT':'1'}
            if attrs!=expected or dataset is None: raise ValueError('G17_SELECTED_SERIES_ATTRIBUTES_CHANGED')
            expected_namespace='http://www.federalreserve.gov/structure/compact/G17_'+dataset['id']
            if node.tag!='{'+expected_namespace+'}Series': raise ValueError('G17_DATASET_NAMESPACE_MISMATCH')
            observations=[];annotations=[]
            for child in node:
                if child.tag=='{'+NS['f']+'}Obs':
                    if len(child) or set(child.attrib)!={'OBS_STATUS','OBS_VALUE','TIME_PERIOD'}: raise ValueError('G17_OBSERVATION_SCHEMA_CHANGED')
                    day=child.get('TIME_PERIOD');stamp=date.fromisoformat(day)
                    if day!=month_end(day[:7]): raise ValueError('G17_OBSERVATION_NOT_MONTH_END')
                    value=number(child.get('OBS_VALUE'),child.get('OBS_STATUS'))
                    observations.append({'date':day,'value':value,'attrs':dict(child.attrib)})
                elif child.tag=='{'+NS['f']+'}Annotations': annotations.append(ET.tostring(child,encoding='unicode'))
                else: raise ValueError('G17_UNKNOWN_SERIES_CHILD')
            dates=[x['date'] for x in observations]
            if not dates or dates!=sorted(set(dates)): raise ValueError('G17_SERIES_PERIODS_DUPLICATE_OR_UNSORTED')
            body={'attributes':attrs,'annotations_xml':annotations,'observations':observations}
            if identity in copies:
                previous=copies[identity]
                if body!=previous: raise ValueError('G17_DUPLICATE_PUBLISHED_SERIES_CONFLICT')
            else: copies[identity]=body
            meta={'dataset_attributes':dataset,'series_attributes':attrs,'series_annotations_xml':annotations,
                  'source_dataset_ordinal':dataset_ordinal,'source_series_ordinal':series_ordinal,
                  'source_total_observations':len(observations),'source_first_date':dates[0],'source_latest_date':dates[-1]}
            metadata.setdefault(identity,{'primary':None,'published_copies':[]})['published_copies'].append(meta)
            if dataset['id']==selected[identity]:
                if metadata[identity]['primary'] is not None: raise ValueError('G17_PRIMARY_SERIES_DUPLICATED')
                metadata[identity]['primary']=meta
                for ordinal,item in enumerate(observations,1):
                    if item['date']<START: continue
                    if item['date']>release['release_date']: raise ValueError('G17_SOURCE_OBSERVATION_AFTER_RELEASE')
                    rows[(identity,item['date'])]={'date':item['date'],'period':item['date'][:7],
                        'provider_series':identity,'measure':measure,'provider_series_code':code,
                        'provider_dataset':dataset['id'],'value':item['value'],
                        'provider_value_text':item['attrs']['OBS_VALUE'],'provider_observation_status':item['attrs']['OBS_STATUS'],
                        'provider_status_label':codelists['CL_OBS_STATUS'][item['attrs']['OBS_STATUS']],
                        'provider_unit':attrs['UNIT'],'provider_unit_mult':attrs['UNIT_MULT'],
                        'provider_frequency':attrs['FREQ'],'provider_seasonal_adjustment':attrs['SA'],'provider_currency':attrs['CURRENCY'],
                        'unit_label':codelists['CL_UNIT'][attrs['UNIT']],
                        'unit_semantics':{'IP':'REAL_OUTPUT_INDEX_2017_AVERAGE_100','CAP':'SUSTAINABLE_CAPACITY_PERCENT_OF_2017_ACTUAL_OUTPUT','CAPUTL':'UTILIZATION_PERCENT_OF_CAPACITY'}[measure],
                        'source_dataset_ordinal':dataset_ordinal,'source_series_ordinal':series_ordinal,'source_observation_ordinal':ordinal,
                        'source_observation_attributes_json':json.dumps(item['attrs'],sort_keys=True,separators=(',',':'))}
        node.clear()
    if header is None or set(metadata)!=set(selected) or any(x['primary'] is None for x in metadata.values()):
        raise ValueError('G17_SELECTED_PRIMARY_SET_INCOMPLETE')
    return rows,{'header':header,'series':metadata,'codelists':codelists,'zip_members':zip_manifest}


def parse_release_tables(raws,release):
    month_names={name.lower():i for i in range(1,13) for name in (calendar.month_abbr[i],calendar.month_name[i])}
    parsed={};series={}
    for name,raw in raws.items():
        text=raw.decode('utf-8-sig')
        if release['raw_release_date_text'] not in text: raise ValueError('G17_TABLE_RELEASE_DATE_DIFFERS')
        parser=ReleaseTable();parser.feed(text);headers=[]
        for row in parser.rows:
            months=[]
            for cell in row:
                match=re.fullmatch(r'([A-Za-z]+)\.?(?:\[([rp])\])?',cell)
                if match and match[1].lower() in month_names:
                    month=month_names[match[1].lower()];year=int(release['release_date'][:4])
                    if month>int(release['release_date'][5:7]):year-=1
                    months.append({'period':f'{year:04d}-{month:02d}','flag':match[2],'header_text':cell})
            if len(months)>=6:headers.append(months)
        if len(headers)!=1 or headers[0][-1]['flag']!='p': raise ValueError('G17_TABLE_PERIOD_FLAGS_INVALID')
        periods=headers[0]
        if periods!=sorted(periods,key=lambda x:x['period']) or len({p['period'] for p in periods})!=len(periods):
            raise ValueError('G17_TABLE_PERIOD_ORDER_INVALID')
        parsed[name]={'period_headers':periods,'source_rows':parser.rows}
        for identity in SERIES:
            measure,code,_=identity.split('.')
            which=('latest_utl7' if measure=='CAPUTL' else
                   'latest_ip5' if code in {'G3341','G3342','G3344','HITEK2'} else 'latest_ip4')
            if measure=='CAP' or name!=which:continue
            labels={'B52100':'Business equipment','B52120':'Information processing','HITEK2':'Selected high-technology industries'}
            naics='31-33' if code=='GMF' else code[1:]
            matches=[r for r in parser.rows if len(r)==(15 if measure=='CAPUTL' else 12)
                     and (r[0]==labels[code] if code in labels else r[1]==naics)]
            if len(matches)!=1:raise ValueError('G17_LATEST_HTML_SERIES_IDENTITY_AMBIGUOUS:'+identity)
            row=matches[0];records=[]
            for period,token in zip(periods,row[-len(periods):]):
                if not re.fullmatch(r'\d+\.\d',token): raise ValueError('G17_HTML_VALUE_FORMAT_CHANGED')
                records.append({**period,'value_text':token})
            series[identity]={'source_name':name,'row':row,'naics_current':row[1] or None,'records':records}
    if len(series)!=17 or len({x['period_headers'][-1]['period'] for x in parsed.values()})!=1:
        raise ValueError('G17_LATEST_HTML_SCOPE_INCOMPLETE')
    return series,parsed


def normalize(receipts,paths,run_id,as_of):
    common.snapshot_day(as_of)
    if set(receipts)!=set(DOCS)|set(HISTORY): raise ValueError('G17_ACQUISITION_PLAN_INCOMPLETE')
    raw={name:verified_raw(receipts[name],paths,run_id,name,url).read_bytes() for name,url in {**DOCS,**HISTORY}.items()}
    if any(r['raw']['retrieval_timestamp_utc'][:10]>as_of for r in receipts.values()):raise ValueError('G17_RETRIEVAL_AFTER_AS_OF')
    release=parse_release(raw['release'],as_of)
    html_series,html_tables=parse_release_tables({name:raw[name] for name in ['latest_ip4','latest_ip5','latest_utl7']},release)
    latest=next(iter(html_tables.values()))['period_headers'][-1]['period'];release['latest_period']=latest
    rows,metadata=parse_sdmx(raw['sdmx_zip'],release)
    textrows={};descriptions={}
    for measure,name,codes in [('IP','ip_sa',(*INDUSTRIES,*EXTRA_IP)),('CAP','cap_sa',INDUSTRIES),('CAPUTL','utl_sa',INDUSTRIES)]:
        parsed,desc=parse_text(raw[name],measure,latest,codes)
        textrows.update(parsed)
        for code,description in desc.items():descriptions[measure+'.'+code+'.S']={**description,'source_name':name}
    if set(rows)!=set(textrows):raise ValueError('G17_SDMX_TEXT_OBSERVATION_IDENTITIES_DIFFER')
    for identity,row in rows.items():
        counterpart=textrows[identity]
        if row['value']!=counterpart['value'] or row['provider_value_text']!=counterpart['provider_value_text']:
            raise ValueError('G17_SDMX_TEXT_VALUE_DIFFERS')
        desc=descriptions[identity[0]];html=html_series.get(identity[0]);record=next((r for r in html['records'] if r['period']==row['period']),None) if html else None
        if record and (row['value'] is None or abs(row['value']-Decimal(record['value_text']))>Decimal('.05005')):
            raise ValueError('G17_PUBLISHED_ROUNDED_VALUE_DIFFERS')
        row.update(provider_description_current=desc['description'],provider_naics_current=desc['naics_current'],
            classification_vintage_semantics='CURRENT_RELEASE_DESCRIPTION_NOT_HISTORICAL_MEMBERSHIP',
            release_naics_current=html['naics_current'] if html else None,
            release_observation_flag=record['flag'] if record else None,
            release_flag_source=html['source_name'] if record else None,
            release_rounded_value_text=record['value_text'] if record else None,
            release_flag_semantics='ONLY_EXPLICIT_CURRENT_TABLE_HEADERS; SDMX A DOES_NOT_MEAN_UNREVISED',
            source_release_date=release['release_date'],source_prepared_timestamp_text=metadata['header']['prepared_timestamp_text'],
            source_text_line_number=counterpart['source_text_line_number'],source_month_slot=counterpart['source_month_slot'],
            source_text_cell=counterpart['source_text_cell'],source_text_line=counterpart['source_text_line'],
            text_source_id=receipts[desc['source_name']]['raw']['sha256'],source='FRB_OFFICIAL',
            source_id=receipts['sdmx_zip']['raw']['sha256'],source_url=HISTORY['sdmx_zip'],
            observed_at_utc=receipts['sdmx_zip']['raw']['retrieval_timestamp_utc'],available_at_utc=None,vintage_semantics=common.VINTAGE)
    records=list(rows.values());freshness=[]
    for series in SERIES:
        items=[r for r in records if r['provider_series']==series];days=[r['date'] for r in items]
        first=date.fromisoformat(START);last=date.fromisoformat(month_end(latest));expected=[]
        while first<=last:
            expected.append(month_end(first.strftime('%Y-%m')))
            first=date(first.year+int(first.month==12),first.month%12+1,1)
        if days!=expected:raise ValueError('G17_REQUESTED_MONTH_COVERAGE_INCOMPLETE')
        freshness.append({'series':series,'row_count':len(items),'min_date':days[0],'max_date':days[-1],
            'missing_values':sum(x['value'] is None for x in items),'status_counts':dict(Counter(x['provider_observation_status'] for x in items)),
            'text_full_history_match':True,'latest_source_value_text':items[-1]['provider_value_text'],
            'html_latest_match':series in html_series,'published_xml_copies':len(metadata['series'][series]['published_copies'])})
    contract={'as_of':as_of,'start_date':START,'series':SERIES,'normalizer_sha256':common.sha256(__file__),
        'common_sha256':common.sha256(common.__file__),
        'html_table_parser_sha256':common.sha256(paths.repo_root/'scripts/storage/refresh_frb_h10.py'),
        'archive_sha256':common.sha256(paths.repo_root/'fast6/src/fast6/acquisition.py'),
        'inputs':{name:{k:r['raw'][k] for k in ['source_reference','sha256','retrieval_timestamp_utc']} for name,r in receipts.items()}}
    version=hashlib.sha256(common.json_bytes(contract)).hexdigest()[:24]
    folder=paths.data_root/'reference/official_research'/FAMILY/version;report,rawroot=roots(paths,run_id)
    schema=pa.schema([(k,pa.decimal128(20,4) if k=='value' else pa.timestamp('us',tz='UTC') if k=='available_at_utc' else
        pa.int64() if k in {'source_dataset_ordinal','source_series_ordinal','source_observation_ordinal','source_text_line_number','source_month_slot'} else pa.string()) for k in records[0]])
    table=pa.Table.from_pylist(records,schema=schema);reserve=table.nbytes+16*1024**2
    used=sum(p.stat().st_size for d in [rawroot,report,folder] for p in d.glob('*') if p.is_file())
    if used+reserve>TOTAL_LIMIT or shutil.disk_usage(paths.data_root).free<FLOOR+reserve:raise ValueError('G17_OUTPUT_BUDGET_OR_FLOOR')
    folder.mkdir(parents=True,exist_ok=True);path=folder/(DATASET+'.parquet');tmp=path.with_suffix('.parquet.tmp')
    if tmp.exists():raise ValueError('G17_PREVIOUS_PARTIAL_PRESERVED')
    pq.write_table(table,tmp,compression='zstd')
    if not table.equals(pq.read_table(tmp)):raise ValueError('G17_PARQUET_ROUNDTRIP_MISMATCH')
    if path.exists():
        if common.sha256(path)!=common.sha256(tmp):raise ValueError('G17_EXISTING_OUTPUT_PRESERVED')
        tmp.unlink()
    else:tmp.replace(path)
    metadata.update(descriptions=descriptions,release_tables=html_tables,release_series=html_series)
    meta_path=report/'source_metadata.json';common.save_json(meta_path,metadata)
    manifest={'role':'FRB_G17_TECHNOLOGY_INDUSTRY_INTAKE','status':'VALIDATED_DATA_ONLY','as_of':as_of,'contract':contract,
        'inputs':receipts,'release':release,'freshness':freshness,'source_metadata':{'path':str(meta_path),'sha256':common.sha256(meta_path)},
        'outputs':[{'dataset':DATASET,'source':'FRB_OFFICIAL','date_column':'date','path':str(path),'sha256':common.sha256(path),
            'row_count':len(records),'min_date':min(r['date'] for r in records),'max_date':max(r['date'] for r in records),
            'byte_count':path.stat().st_size,'series_count':len(SERIES),'missing_value_rows':sum(r['value'] is None for r in records)}],
        'raw_byte_count':sum(len(b) for b in raw.values()),'historical_pit_certified':False,'availability_semantics':'UNKNOWN_NULL',
        'attribution':'Source: Board of Governors of the Federal Reserve System, Industrial Production and Capacity Utilization (G.17). No endorsement implied.',
        'data_terms':{'url':DOCS['disclaimer'],'summary':'Board website information is public domain unless otherwise indicated; cite the Board. Third-party material and official seals/logos have separate restrictions. No warranty or endorsement is implied.'},
        'github_reference':{'url':DOCS['github_project'],'license':'Apache-2.0','role':'API and vintage-handling reference only; package not installed, no code copied, data acquired from Board official publication.'},
        'limitations':['Current-revision data and current descriptions are not historical PIT inputs. No historical membership mapping is constructed.',
            'IP and capacity indexes use 2017 output as base; capacity index is not normalized to average capacity of 100. Utilization is percent, not fraction.',
            'Monthly capacity is an estimate built from annual/source information, not a direct monthly capacity census.',
            'Current NAICS-based series may have been retrospectively reclassified; 2022 NAICS applies to provider current construction since 2017. Historical NAICS versions are not certified.',
            'The announced autumn 2026 revision intends a 2022 base; this capture remains 2017-based. Future base/schema changes stop for review.',
            'OBS_STATUS=A means Normal, not final/unrevised. Explicit r/p table flags are kept only for displayed IP/utilization months; capacity-level flags are not invented.',
            'Prepared is provider file-generation text without timezone; source_release_date is this snapshot publication, not the first publication date of every historical point.',
            'Date is provider month-end label, not disclosure or trading availability. No forwarding to the as-of day.',
            'Official XML repeats some identical IP series across presentation tables; all copies must match exactly, with primary table and aliases preserved.',
            'The format page month-position endpoints differ from observed files: actual zero-based month cells start at23, width10, full row143 characters. Original lines and cells are retained and all selected values cross-checked against XML.',
            'DDP Build Your Package retirement is planned for November 2026; static official historical XML and text are used here.',
            '2026+ rows are acquisition/integrity only; no strategy, training, tuning or backtests performed.',
            'Existing unrelated repository preflight/access hard blockers remain unchanged; source-specific validation is not global governance clearance.'],
        'qc':{'sdmx_text_exact_observation_matches':len(records),'html_latest_series_matches':len(html_series),
            'html_displayed_point_matches':sum(len(x['records']) for x in html_series.values()),
            'zip_crc':'ALL_MEMBERS_PASS','parquet_roundtrip':'EXACT_ARROW_MATCH','requested_month_gaps':0,
            'duplicate_xml_copy_count':sum(len(x['published_copies'])-1 for x in metadata['series'].values())}}
    target=report/'manifest.json';common.save_json(target,manifest);return target


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-id',required=True);parser.add_argument('--as-of',required=True)
    parser.add_argument('--execute',action='store_true');parser.add_argument('--acquire-only',action='store_true');args=parser.parse_args(argv)
    common.snapshot_day(args.as_of)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',args.run_id):raise ValueError('G17_INVALID_RUN_ID')
    if not args.execute:print(json.dumps({'series':SERIES,'as_of':args.as_of,'urls':{**DOCS,**HISTORY}}));return 0
    paths=common.resolve();receipts={name:fetch(paths,args.run_id,name,url) for name,url in {**DOCS,**HISTORY}.items()}
    if args.acquire_only:print(json.dumps({'status':'ACQUIRED_ONLY','sources':len(receipts)}));return 0
    target=normalize(receipts,paths,args.run_id,args.as_of);print(json.dumps({'status':'VALIDATED_NOT_REGISTERED','manifest':str(target)}));return 0


if __name__=='__main__':raise SystemExit(main())
