"""Official H.10 daily SDMX intake, using the existing archive and storage layer.

Preserves provider metadata, revisions, missing observations and quote direction.
No model use, currency redenomination adjustment, or automatic catalog publication.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
import time
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from scripts.common.storage_paths import resolve
from scripts.storage.refresh_official_research_data import archive_module, save_json, json_bytes, VINTAGE
from scripts.storage.build_data_catalog import sha256

DATASET = 'frb_h10_daily_current'
RELEASE_URL = 'https://www.federalreserve.gov/releases/h10/current/'
ZIP_URL = 'https://www.federalreserve.gov/releases/h10/data/FRB_h10_xml.zip'
NS = {'m': 'http://www.SDMX.org/resources/SDMXML/schemas/v1_0/message',
      'f': 'http://www.federalreserve.gov/structure/compact/common',
      's': 'http://www.federalreserve.gov/structure/compact/H10_H10',
      'c': 'http://www.SDMX.org/resources/SDMXML/schemas/v1_0/common'}
SERIES_COUNTRIES = {
    'JRXWTFB_N.B': '1) BROAD', 'JRXWTFN_N.B': '2) AFE', 'JRXWTFO_N.B': '3) EME',
    'RXI$US_N.B.AL': '*AUSTRALIA', 'RXI$US_N.B.EU': '*EMU MEMBERS',
    'RXI$US_N.B.NZ': '*NEW ZEALAND', 'RXI$US_N.B.UK': '*UNITED KINGDOM',
    **{'RXI_N.B.' + code: country for code, country in {
        'SF': 'SOUTH AFRICA', 'BZ': 'BRAZIL', 'CA': 'CANADA', 'CH': 'CHINA, P.R.',
        'DN': 'DENMARK', 'HK': 'HONG KONG', 'IN': 'INDIA', 'JA': 'JAPAN',
        'MA': 'MALAYSIA', 'MX': 'MEXICO', 'NO': 'NORWAY', 'SI': 'SINGAPORE',
        'KO': 'SOUTH KOREA', 'SL': 'SRI LANKA', 'SD': 'SWEDEN', 'SZ': 'SWITZERLAND',
        'TA': 'TAIWAN', 'TH': 'THAILAND', 'VES': 'VENEZUELA'}.items()}}


class ReleaseTable(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows = []; self.row = []; self.cell = None
    def handle_starttag(self, tag, attrs):
        if tag == 'tr': self.row = []
        if tag in {'th', 'td'}: self.cell = []
    def handle_data(self, value):
        if self.cell is not None: self.cell.append(value)
    def handle_endtag(self, tag):
        if tag in {'th', 'td'} and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split())); self.cell = None
        if tag == 'tr' and self.row:
            self.rows.append(self.row); self.row = []


def parse_release(raw):
    text = raw.decode('utf-8-sig')
    match = re.search(r'Release Date:\s*([A-Za-z]+ \d{1,2}, \d{4})', text)
    if not match or 'H.10 Weekly' not in text:
        raise ValueError('H10_RELEASE_IDENTITY_MISSING')
    released = datetime.strptime(match[1], '%B %d, %Y').date()
    parser = ReleaseTable(); parser.feed(text)
    headers = [r for r in parser.rows if r[:2] == ['COUNTRY', 'CURRENCY']]
    if len(headers) != 1 or len(headers[0]) != 7:
        raise ValueError('H10_RELEASE_DATE_HEADERS_INVALID')
    latest = datetime.strptime(headers[0][-1].replace('.', '') + f' {released.year}', '%b %d %Y').date()
    if latest > released: latest = latest.replace(year=latest.year - 1)
    countries = set(SERIES_COUNTRIES.values())
    selected = [r for r in parser.rows if r[0] in countries]
    if len(selected) != len(countries) or {r[0] for r in selected} != countries or any(len(r) != 7 for r in selected):
        raise ValueError('H10_RELEASE_COUNTRY_SET_INVALID')
    records = {r[0]: {'unit': r[1], 'latest_value': r[-1]} for r in selected}
    return {'release_date': released.isoformat(), 'latest_date': latest.isoformat(), 'series': records}


def parse_sdmx(raw, release, start_date, as_of):
    start, end = date.fromisoformat(start_date), date.fromisoformat(as_of)
    if not date(2020, 1, 1) <= start <= end <= date.today():
        raise ValueError('H10_DATE_BOUNDARY_INVALID')
    if not release['latest_date'] <= release['release_date'] <= as_of:
        raise ValueError('H10_RELEASE_OUTSIDE_BOUNDARY')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = [i for i in archive.infolist() if i.filename == 'H10_data.xml']
        if len(members) != 1 or members[0].file_size > 60_000_000:
            raise ValueError('H10_ZIP_DATA_MEMBER_INVALID')
        payload = archive.read(members[0])  # Never extract a source-controlled path.
    if b'<!DOCTYPE' in payload.upper() or b'<!ENTITY' in payload.upper():
        raise ValueError('H10_XML_EXTERNAL_DECLARATION_FORBIDDEN')
    root = ET.fromstring(payload)
    if root.tag != '{' + NS['m'] + '}MessageGroup' or root.findtext('m:Header/m:ID', namespaces=NS) != 'H10':
        raise ValueError('H10_SDMX_IDENTITY_INVALID')
    prepared = root.findtext('m:Header/m:Prepared', namespaces=NS)
    if not prepared or pd.isna(pd.Timestamp(prepared)):
        raise ValueError('H10_PREPARED_TIME_INVALID')
    series = [s for s in root.findall('f:DataSet/s:Series', NS)
              if s.get('FREQ') == '9' and not s.get('SERIES_NAME', '').startswith('V0.')]
    if len(series) != len(SERIES_COUNTRIES) or {s.get('SERIES_NAME') for s in series} != set(SERIES_COUNTRIES):
        raise ValueError('H10_DAILY_SERIES_IDENTITY_MISMATCH')
    rows = []; summaries = []
    for s in series:
        name = s.get('SERIES_NAME'); country = SERIES_COUNTRIES[name]
        evidence = release['series'][country]
        index = name.startswith('JRX')
        if not {'FX', 'CURRENCY', 'UNIT', 'UNIT_MULT'} <= s.attrib.keys() or s.get('UNIT_MULT') != '1':
            raise ValueError('H10_SERIES_METADATA_INVALID')
        if index and evidence['unit'] != 'JAN06=100':
            raise ValueError('H10_INDEX_RELEASE_BASE_CHANGED_REVIEW_REQUIRED')
        direction = 'INDEX_JAN2006_100' if index else ('USD_PER_FOREIGN_UNIT' if country.startswith('*') else 'FOREIGN_UNITS_PER_USD')
        unit_status = ('XML_BASE_LABEL_DIFFERS_FROM_OFFICIAL_RELEASE' if index and s.get('UNIT') != 'Index:_2006_Jan_100'
                       else 'PROVIDER_METADATA_PRESERVED')
        if country == 'VENEZUELA': unit_status = 'PROVIDER_CURRENCY_CODE_AND_REDENOMINATION_REQUIRE_REVIEW'
        observations = s.findall('f:Obs', NS)
        dates = [o.get('TIME_PERIOD') for o in observations]
        if not dates or dates != sorted(set(dates)) or max(dates) != release['latest_date']:
            raise ValueError('H10_SERIES_DATE_COVERAGE_MISMATCH')
        latest = observations[-1]
        if evidence['latest_value'] == 'ND':
            if latest.get('OBS_STATUS') != 'ND': raise ValueError('H10_LATEST_RELEASE_VALUE_MISMATCH')
        elif latest.get('OBS_STATUS') != 'A' or Decimal(latest.get('OBS_VALUE')) != Decimal(evidence['latest_value']):
            raise ValueError('H10_LATEST_RELEASE_VALUE_MISMATCH')
        count = missing = 0
        for o in observations:
            stamp = o.get('TIME_PERIOD'); date.fromisoformat(stamp)
            if not start_date <= stamp <= as_of: continue
            status = o.get('OBS_STATUS'); original = o.get('OBS_VALUE')
            if status not in {'A', 'ND'} or original is None:
                raise ValueError('H10_OBSERVATION_STATUS_INVALID')
            if status == 'ND':
                if original != '-9999': raise ValueError('H10_MISSING_SENTINEL_CHANGED')
                value = np.nan; missing += 1
            else:
                value = float(original)
                if not np.isfinite(value) or value <= 0: raise ValueError('H10_OBSERVATION_VALUE_INVALID')
            rows.append({'date': stamp, 'provider_series': name, 'provider_fx': s.get('FX'),
                'provider_currency': s.get('CURRENCY'), 'provider_unit': s.get('UNIT'), 'provider_unit_mult': s.get('UNIT_MULT'),
                'country_or_index': country.lstrip('*'), 'quote_convention': direction,
                'current_release_unit_label': evidence['unit'], 'unit_metadata_status': unit_status,
                'value': value, 'provider_value_text': original, 'provider_observation_status': status,
                'source_release_date': release['release_date'], 'source_prepared_timestamp_text': prepared})
            count += 1
        if not count: raise ValueError('H10_EMPTY_REQUESTED_SERIES')
        summaries.append({'provider_series': name, 'row_count': count, 'missing_rows': missing,
                          'latest_date': release['latest_date'], 'quote_convention': direction, 'unit_metadata_status': unit_status})
    frame = pd.DataFrame(rows).sort_values(['date', 'provider_series']).reset_index(drop=True)
    return frame, summaries


def run(paths, run_id, start_date='2020-01-01', as_of=None):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', run_id): raise ValueError('H10_INVALID_RUN_ID')
    as_of = as_of or date.today().isoformat()
    if not date(2020, 1, 1) <= date.fromisoformat(start_date) <= date.fromisoformat(as_of) <= date.today():
        raise ValueError('H10_DATE_BOUNDARY_INVALID')
    report = paths.results_root/'official_research_intake'/run_id/'frb_h10'
    raw_root = paths.cache_root/'official_research_intake'/run_id/'frb_h10/raw'
    if (report/'manifest.json').exists():
        prior = json.loads((report/'manifest.json').read_text(encoding='utf-8'))
        if (prior.get('role') != 'FRB_H10_DATA_INTAKE' or prior.get('status') != 'VALIDATED_DATA_ONLY'
                or prior['contract']['start_date'] != start_date or prior['contract']['as_of'] != as_of
                or prior['contract']['normalizer_sha256'] != sha256(__file__)):
            raise ValueError('H10_EXISTING_RUN_CONTRACT_DIFFERS')
        for raw in prior['inputs']:
            path = Path(raw['local_path']).resolve()
            if not path.is_relative_to(paths.cache_root) or sha256(path) != raw['sha256']:
                raise ValueError('H10_RAW_IDENTITY_INVALID')
        for output in prior['outputs']:
            path = Path(output['path']).resolve()
            if not path.is_relative_to(paths.data_root) or sha256(path) != output['sha256']:
                raise ValueError('H10_OUTPUT_IDENTITY_INVALID')
        return prior
    capture = archive_module(paths.repo_root)
    inputs = []
    for kind, url in [('CURRENT_RELEASE', RELEASE_URL), ('SDMX_ZIP', ZIP_URL)]:
        record = asdict(capture.acquire_url(url, 'frb_h10', 'FRB_OFFICIAL', kind, raw_root, 45, 0, 1.))
        inputs.append(record)
        if record['status'] not in {'DOWNLOADED', 'CACHED'}:
            save_json(report/'acquisition_failure.json', {'status': 'SOURCE_FAILED', 'inputs': inputs})
            raise ValueError('H10_SOURCE_DOWNLOAD_FAILED')
        time.sleep(.5)
    for raw in inputs:
        path = Path(raw['local_path']).resolve()
        if not path.is_relative_to(paths.cache_root) or sha256(path) != raw['sha256']:
            raise ValueError('H10_RAW_IDENTITY_INVALID')
        stamp = pd.Timestamp(raw['retrieval_timestamp_utc'])
        if pd.isna(stamp) or stamp.tzinfo is None: raise ValueError('H10_OBSERVED_TIME_INVALID')
    release = parse_release(Path(inputs[0]['local_path']).read_bytes())
    frame, series = parse_sdmx(Path(inputs[1]['local_path']).read_bytes(), release, start_date, as_of)
    frame['source'] = 'FRB_OFFICIAL'
    frame['source_id'] = inputs[1]['sha256']
    frame['observed_at_utc'] = inputs[1]['retrieval_timestamp_utc']
    frame['available_at_utc'] = pd.Series(pd.NaT, index=frame.index, dtype='datetime64[ns, UTC]')
    frame['vintage_semantics'] = VINTAGE
    import hashlib
    contract = {'dataset': DATASET, 'start_date': start_date, 'as_of': as_of, 'normalizer_sha256': sha256(__file__),
                'source_identities': [{k: raw[k] for k in ['source_reference', 'sha256', 'retrieval_timestamp_utc']} for raw in inputs]}
    digest = hashlib.sha256(json_bytes(contract)).hexdigest()
    directory = paths.data_root/'reference/official_research/versions'/digest[:24]
    directory.mkdir(parents=True, exist_ok=True)
    output = directory/(DATASET+'.parquet'); temporary = directory/(DATASET+'.parquet.tmp')
    frame.to_parquet(temporary, index=False, compression='zstd')
    if pq.ParquetFile(temporary).metadata.num_rows != len(frame): raise ValueError('H10_PARQUET_ROW_COUNT_MISMATCH')
    if output.exists():
        if sha256(output) != sha256(temporary): raise ValueError('H10_EXISTING_VERSION_DIFFERS')
        temporary.unlink()
    else: temporary.replace(output)
    manifest = {'schema_version': 1, 'role': 'FRB_H10_DATA_INTAKE', 'status': 'VALIDATED_DATA_ONLY',
        'contract': contract, 'contract_sha256': digest, 'inputs': inputs, 'release': release, 'series': series,
        'outputs': [{'dataset': DATASET, 'path': str(output), 'sha256': sha256(output), 'row_count': len(frame),
                     'min_date': frame.date.min(), 'max_date': frame.date.max(), 'date_column': 'date',
                     'source': 'FRB_OFFICIAL', 'observation_dates': frame.date.nunique(), 'missing_value_rows': int(frame.value.isna().sum())}],
        'historical_pit_certified': False, 'vintage_semantics': VINTAGE, 'available_at_semantics': 'UNKNOWN_NULL',
        'research_usage': '2026_PLUS_OBSERVATION_ONLY_NO_TRAINING_TUNING_OR_BACKTEST',
        'limitations': ['WEEKLY_RELEASE_OF_DAILY_NOON_QUOTES_NOT_SAME_DAY_AVAILABILITY',
            'CURRENT_RETRIEVAL_CAN_INCLUDE_HISTORICAL_REVISIONS', 'XML_INDEX_BASE_LABEL_CONFLICT_WITH_OFFICIAL_RELEASE_RETAINED',
            'VENEZUELA_CURRENCY_CODE_AND_REDENOMINATION_REQUIRE_REVIEW', 'SOURCE_PREPARED_TIME_NOT_RELEASE_TIME',
            'SOURCE_ND_RETAINED_AS_NULL_NO_FORWARD_FILL', 'NO_RETURN_FACTOR_OR_MODEL_VALIDATION']}
    save_json(report/'manifest.json', manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True, help='New ID for each fresh release; reuse only to resume identical capture')
    parser.add_argument('--start-date', default='2020-01-01'); parser.add_argument('--as-of', required=True)
    args = parser.parse_args(); manifest = run(resolve(), args.run_id, args.start_date, args.as_of)
    print(json.dumps({'status': manifest['status'], 'outputs': manifest['outputs']}, ensure_ascii=False))


if __name__ == '__main__': main()
