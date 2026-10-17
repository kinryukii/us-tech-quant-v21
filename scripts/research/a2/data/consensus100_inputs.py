"""Bounded pre-2026 SEC source qualification for the existing consensus owner.

No I/O on import. Package-origin metadata is checked before projecting filing
clocks; no holding VALUE is read during preflight. A complete metadata cohort
is not a certified snapshot, historical vendor-arrival proof, or permission to
invent acceptance times/amendment semantics. Qualified snapshot construction
requires caller-bound evidence and reuses aggregate_snapshot_top100 unchanged.
"""
from __future__ import annotations
import argparse
import datetime as dt
from decimal import Decimal
import types
import xml.etree.ElementTree as ET
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse
import pandas as pd
import pyarrow.parquet as pq
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.storage.refresh_13f_quarter import active_managers, manager_roster_identity
from scripts.research.a2.inference.aggregate_13f_universe import aggregate_snapshot_top100

TASK = 'CONSENSUS100_PTO_3000_20261012_R1'
BOUNDARY = pd.Timestamp('2026-01-01')
INITIAL_POLICY = 'INITIAL_PUBLIC_AS_FILED_NO_AMENDMENT_BACKFILL'
SUB_COLUMNS = ['ACCESSION_NUMBER', 'FILING_DATE', 'SUBMISSIONTYPE', 'CIK', 'PERIODOFREPORT']
INFO_COLUMNS = ['ACCESSION_NUMBER', 'INFOTABLE_SK', 'NAMEOFISSUER', 'TITLEOFCLASS',
                'CUSIP', 'VALUE', 'SSHPRNAMT', 'SSHPRNAMTTYPE', 'PUTCALL']


def require(condition, code):
    if not condition:
        raise ValueError(code)


def file_ref(path):
    path = Path(path).resolve()
    before = path.stat()
    with path.open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    after = path.stat()
    require((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns), 'SOURCE_CHANGED_DURING_HASH')
    return dict(path=str(path), sha256=digest, size=after.st_size, mtime_ns=after.st_mtime_ns)


def verify_ref(ref):
    require(file_ref(ref['path']) == ref, 'SOURCE_CHANGED_AFTER_PREFLIGHT')


def package_window(filename):
    """Official archive period, independent of report quarter/lexical date stats."""
    match = re.fullmatch(r'(20\d{2})q([1-4])_form13f\.zip', filename, flags=re.I)
    if match:
        period = pd.Period(f'{match[1]}Q{match[2]}', freq='Q')
        return period.start_time.normalize(), period.end_time.normalize()
    match = re.fullmatch(r'(\d{2}[a-z]{3}\d{4})-(\d{2}[a-z]{3}\d{4})_form13f\.zip', filename, flags=re.I)
    require(match is not None, 'UNKNOWN_OFFICIAL_PACKAGE_WINDOW')
    return tuple(pd.Timestamp(pd.to_datetime(part, format='%d%b%Y')).normalize() for part in match.groups())


def parse_dates(values):
    result = []
    for value in values:
        text = str(value).strip()
        parsed = None
        for fmt in ('%d-%b-%Y', '%Y-%m-%d', '%m/%d/%Y'):
            try:
                parsed = pd.Timestamp(pd.to_datetime(text, format=fmt)).normalize()
                break
            except (ValueError, TypeError):
                pass
        require(parsed is not None, 'UNPARSEABLE_SEC_DATE')
        result.append(parsed)
    return pd.DatetimeIndex(result)


def qualify_package(meta_path):
    """Check finite archive origin, footer/schema/custody, then filing clocks only.

    Source-period provenance plus its retained extraction counts permits the
    metadata projection. Every projected clock is checked before a holding
    accessor can be issued. DD-MON-YYYY lexical min/max is never treated as a
    chronological bound. No mixed/future archive is opened as a Parquet table.
    """
    meta_path = Path(meta_path)
    meta = json.loads(meta_path.read_text(encoding='utf-8'))
    lower, upper = package_window(meta['filename'])
    require(lower <= upper, 'INVALID_PACKAGE_WINDOW')
    if upper >= BOUNDARY:
        return dict(status='EXCLUDED_FUTURE_OR_MIXED_PACKAGE', name=meta_path.name,
                    source_window=[str(lower.date()), str(upper.date())], holding_payload_read=False), []
    if upper < pd.Timestamp('2020-01-01'):
        return dict(status='EXCLUDED_BEFORE_CURRENT_COHORT', name=meta_path.name,
                    source_window=[str(lower.date()), str(upper.date())], holding_payload_read=False), []
    url = urlparse(meta['url'])
    require(url.scheme == 'https' and url.netloc.lower() == 'www.sec.gov'
            and url.path == '/files/structureddata/data/form-13f-data-sets/' + meta['filename'], 'UNBOUND_OFFICIAL_SOURCE_URL')
    label = meta['label']
    require(re.fullmatch(r'[A-Za-z0-9_]+', label) is not None
            and meta_path.name == label + '_meta.json', 'INVALID_PACKAGE_LABEL')
    sub_path = meta_path.with_name(label + '_submission.parquet')
    info_path = meta_path.with_name(label + '_infotable.parquet')
    sub_file, info_file = pq.ParquetFile(sub_path), pq.ParquetFile(info_path)
    require(set(SUB_COLUMNS) <= set(sub_file.schema_arrow.names), 'SUBMISSION_SCHEMA_MISSING')
    require(set(INFO_COLUMNS) <= set(info_file.schema_arrow.names), 'FULL_INFOTABLE_SCHEMA_MISSING')
    require(type(meta['submission_rows']) is int and type(meta['infotable_rows']) is int
            and sub_file.metadata.num_rows == meta['submission_rows']
            and info_file.metadata.num_rows == meta['infotable_rows'], 'RETAINED_PACKAGE_ROW_COUNT_MISMATCH')
    refs = dict(meta=file_ref(meta_path), submissions=file_ref(sub_path), infotable=file_ref(info_path))
    table = pq.read_table(sub_path, columns=SUB_COLUMNS).to_pandas()
    filing_dates, report_dates = parse_dates(table.FILING_DATE), parse_dates(table.PERIODOFREPORT)
    require(((filing_dates >= lower) & (filing_dates <= upper)).all(), 'FILING_CLOCK_OUTSIDE_FINITE_PACKAGE')
    require((filing_dates < BOUNDARY).all() and (report_dates < BOUNDARY).all(), 'FUTURE_SOURCE_METADATA')
    require((report_dates <= filing_dates).all(), 'REPORT_AFTER_DISCLOSURE')
    for ref in refs.values():
        verify_ref(ref)
    records = []
    for index, row in enumerate(table.to_dict('records')):
        form = str(row['SUBMISSIONTYPE']).strip().upper()
        require(form in ('13F-HR', '13F-HR/A', '13F-NT', '13F-NT/A'), 'UNEXPECTED_REDUCED_SUBMISSION_FORM')
        if form not in ('13F-HR', '13F-HR/A'):
            continue
        cik = str(row['CIK']).strip()
        require(cik.isdigit() and int(cik) > 0, 'INVALID_SOURCE_CIK')
        records.append(dict(accession=str(row['ACCESSION_NUMBER']).strip(), cik=int(cik),
                            quarter=str(report_dates[index].to_period('Q')), report_date=str(report_dates[index].date()),
                            filed_date=str(filing_dates[index].date()), form=form, package=label,
                            accepted_at=None, availability_status='EXACT_ACCEPTANCE_TIMESTAMP_NOT_IN_BULK'))
    return dict(status='QUALIFIED_FINITE_PACKAGE_METADATA', name=label,
                source_window=[str(lower.date()), str(upper.date())], official_url=meta['url'],
                files=refs, submission_rows=len(table), full_source_rows=info_file.metadata.num_rows,
                metadata_projection_columns=SUB_COLUMNS, legal_accessions=sorted(set(row['accession'] for row in records)),
                holding_payload_read=False, legal_initial_accessions=sorted(set(row['accession'] for row in records if row['form']=='13F-HR')),
                chronological_footer_proof=False,
                scope_proof='OFFICIAL_FINITE_ARCHIVE_LINEAGE_PLUS_FULL_PROJECTED_FILING_CLOCK_SCAN',
                original_zip_retained=False, original_zip_custody='NOT_CERTIFIED'), records



def initial_public_activation(filing_dates):
    """Conservative activation after the latest original-public filing day.

    Missing acceptanceDateTime is not filled. Original filing-date evidence
    supports only a next-day public-disclosure upper bound; five subsequent
    NYSE sessions determine the common activation, as in the existing policy.
    """
    import pandas_market_calendars as mcal
    dates=pd.DatetimeIndex(pd.to_datetime(list(filing_dates))).normalize()
    require(len(dates)>0 and not dates.hasnans and (dates<BOUNDARY).all(), 'PRE2026_INITIAL_FILING_DATES_REQUIRED')
    latest=dates.max()
    schedule=mcal.get_calendar('NYSE').schedule(start_date=(latest+pd.Timedelta(days=1)).date(),
                    end_date=(latest+pd.Timedelta(days=31)).date())
    require(len(schedule)>=5, 'INSUFFICIENT_NYSE_CALENDAR_SESSIONS')
    activation=pd.Timestamp(schedule.iloc[4].market_open)
    require(activation.tz_convert('America/New_York').date()<BOUNDARY.date(), 'INITIAL_ACTIVATION_CROSSES_2026')
    return activation


def initial_public_clocks(quarter_receipt):
    require(quarter_receipt['metadata_status']=='COMPLETE', 'COMPLETE_INITIAL_COHORT_REQUIRED')
    rows=[]
    for filing in quarter_receipt['initial_filings']:
        next_day=(pd.Timestamp(filing['filed_date'])+pd.Timedelta(days=1)).tz_localize('America/New_York').tz_convert('UTC')
        rows.append(dict(filing, disclosure_available_by=next_day.isoformat(),
                         exact_acceptance_timestamp='NOT_ASSERTED', effective_at=quarter_receipt['activation_at'],
                         amendments_handled=False, filing_policy=INITIAL_POLICY))
    return rows

def preflight_sources(registry_path=None, reduced_root=None, aliases_path=None):
    paths = resolve(Path(__file__).resolve().parents[4])
    package = paths.results_root / '13f_pit_v1'
    registry_path = Path(registry_path or package / 'config/manager_registry.csv')
    aliases_path = Path(aliases_path or package / 'config/manager_cik_aliases.csv')
    reduced_root = Path(reduced_root or paths.cache_root / '13f_pit_v1/sec_bulk_reduced')
    registry = pd.read_csv(registry_path, dtype=str, keep_default_na=False)
    aliases = pd.read_csv(aliases_path, dtype=str, keep_default_na=False)
    require(set(('manager_id', 'cik', 'valid_from_quarter', 'valid_to_quarter')) <= set(aliases.columns), 'ALIAS_SCHEMA_MISSING')
    packages, failures, filings = [], [], []
    for path in sorted(reduced_root.glob('*_meta.json')):
        try:
            receipt, rows = qualify_package(path)
            packages.append(receipt)
            filings.extend(rows)
        except (ValueError, KeyError, FileNotFoundError) as error:
            failures.append(dict(name=path.name, error=str(error), holding_payload_read=False))
    dedup = {}
    for row in filings:
        key = row['accession']
        identity = tuple(row[field] for field in ('cik', 'quarter', 'report_date', 'filed_date', 'form'))
        if key in dedup:
            previous = tuple(dedup[key][field] for field in ('cik', 'quarter', 'report_date', 'filed_date', 'form'))
            require(identity == previous, 'CONFLICTING_ACCESSION_METADATA')
        else:
            dedup[key] = row
    filings = list(dedup.values())
    quarters = []
    for period in pd.period_range('2020Q1', '2025Q3', freq='Q'):
        quarter = str(period)
        active = active_managers(registry, quarter)
        roster = manager_roster_identity(registry, quarter)
        mapped = []
        for filing in (row for row in filings if row['quarter'] == quarter):
            a = aliases.loc[aliases.manager_id.isin(active.manager_id)
                            & aliases.valid_from_quarter.le(quarter)
                            & (aliases.valid_to_quarter.eq('') | aliases.valid_to_quarter.ge(quarter))]
            names = sorted(set(a.loc[a.cik.map(int).eq(filing['cik']), 'manager_id']))
            require(len(names) <= 1, 'AMBIGUOUS_QUARTER_CIK_ALIAS')
            if names:
                mapped.append(dict(filing, manager_id=names[0]))
        all_initials = [row for row in mapped if row['form'] == '13F-HR']
        initials, additional, counts = [], [], {}
        for manager in active.manager_id:
            candidates = sorted([row for row in all_initials if row['manager_id']==manager], key=lambda row:(row['filed_date'],row['accession']))
            first_day = candidates[0]['filed_date'] if candidates else None
            first = [row for row in candidates if row['filed_date']==first_day]
            counts[manager] = len(first)
            initials.extend(first)
            additional.extend(row for row in candidates if row['filed_date']!=first_day)
        missing = sorted(manager for manager, count in counts.items() if count == 0)
        ambiguous = sorted(manager for manager, count in counts.items() if count > 1)
        quarters.append(dict(quarter=quarter, roster=roster, expected_manager_count=len(active),
                             initial_manager_count=sum(count == 1 for count in counts.values()),
                             missing_initial_managers=missing, ambiguous_initial_managers=ambiguous,
                             metadata_status='COMPLETE' if not missing and not ambiguous else 'INCOMPLETE_OR_AMBIGUOUS',
                             initial_filings=initials, additional_initial_filings=additional,
                             amendments=[row for row in mapped if row['form'] == '13F-HR/A'],
                             filing_policy=INITIAL_POLICY, amendments_handled=False,
                             snapshot_status='NEEDS_FULL_PUBLIC_ROW_AND_UNIT_QUALIFICATION',
                             activation_at=initial_public_activation([row['filed_date'] for row in initials]).isoformat() if not missing and not ambiguous else None))
    return dict(schema='CONSENSUS100_PRE2026_SOURCE_PREFLIGHT_R1', task_id=TASK,
                cutoff_exclusive='2026-01-01', selection_rule='MANAGER_COUNT_WEIGHT_SUM',
                filing_policy=INITIAL_POLICY, amendments_handled=False,
                holding_completeness_scope='FULL_PUBLIC_INITIAL_FILING_ROWS_ONLY_NOT_INSTITUTION_TOTAL_ASSETS',
                source_ref=file_ref(Path(__file__)), aggregate_owner_ref=file_ref(Path(__file__).parents[1]/'inference/aggregate_13f_universe.py'),
                source_owner='scripts.research.a2.inference.aggregate_13f_universe.aggregate_snapshot_top100',
                cohort_start='2020Q1', current_roster_ref=file_ref(registry_path), aliases_ref=file_ref(aliases_path),
                packages=packages, failures=failures, quarters=quarters,
                summary=dict(qualified_packages=sum(row['status'] == 'QUALIFIED_FINITE_PACKAGE_METADATA' for row in packages),
                             complete_quarters=sum(row['metadata_status'] == 'COMPLETE' for row in quarters),
                             requested_quarters=len(quarters), package_failures=len(failures),
                             numeric_holdings_or_market_or_targets_read=False),
                uncertified=['EXACT_SEC_ACCEPTANCE_TIMESTAMPS_NOT_IN_RETAINED_BULK',
                             'AMENDMENT_RESTATEMENT_OR_ADDITIONS_AND_CONFIDENTIAL_OMISSION_COVER_NOT_IN_INFOTABLE',
                             'ORIGINAL_SEC_ZIP_CUSTODY_NOT_RETAINED', 'HISTORICAL_VENDOR_ARRIVAL_UNKNOWN',
                             'SEC_DATE_METADATA_COMPLETENESS_IS_NOT_MODEL_FEATURE_OR_QUOTE_PIT_QUALIFICATION'])


def read_qualified_holdings(package_receipt, accessions):
    """Access full selected accessions only after the finite-package metadata gate.

    This returns raw SEC values. It does not manufacture USD-unit qualification,
    exact acceptance timestamps, cover reconciliation, or amendment resolution.
    """
    require(package_receipt.get('status') == 'QUALIFIED_FINITE_PACKAGE_METADATA', 'FINITE_PACKAGE_METADATA_REQUIRED')
    require(pd.Timestamp(package_receipt['source_window'][1]) < BOUNDARY, 'FUTURE_OR_MIXED_PACKAGE')
    selected = sorted(set(map(str, accessions)))
    require(selected and set(selected) <= set(package_receipt['legal_initial_accessions']), 'ACCESSION_OUTSIDE_QUALIFIED_PACKAGE')
    for ref in package_receipt['files'].values():
        verify_ref(ref)
    ref = package_receipt['files']['infotable']
    frame = pq.read_table(ref['path'], columns=INFO_COLUMNS,
                          filters=[('ACCESSION_NUMBER', 'in', selected)]).to_pandas()
    verify_ref(ref)
    require(set(frame.ACCESSION_NUMBER) == set(selected), 'INITIAL_ACCESSION_FULL_ROWS_MISSING_OR_PREDICATE_FAILED')
    require(not frame.duplicated(['ACCESSION_NUMBER', 'INFOTABLE_SK']).any(), 'DUPLICATE_FULL_SOURCE_ROW')
    return frame


def rank_qualified_snapshot(holdings, evidence, registry, *, quarter, snapshot_id, decision_at, classify_equity):
    """Caller must bind real source/unit/availability evidence; no invented fields."""
    decision = pd.Timestamp(decision_at)
    require(decision.tzinfo is not None and decision.tz_convert('America/New_York').date() < BOUNDARY.date(), 'PRE2026_DECISION_REQUIRED')
    require('filing_date' in evidence.columns, 'INITIAL_FILING_DATE_EVIDENCE_REQUIRED')
    activation=initial_public_activation(evidence.filing_date)
    require(evidence.effective_at.map(pd.Timestamp).eq(activation).all(), 'FIVE_NYSE_ACTIVATION_CHANGED')
    return aggregate_snapshot_top100(holdings, evidence, registry, quarter=quarter,
                                    snapshot_id=snapshot_id, decision_at=decision,
                                    classify_equity=classify_equity, selection_rule='MANAGER_COUNT_WEIGHT_SUM',
                                    filing_policy=INITIAL_POLICY)


def daily_membership(ranked_snapshots, calendar):
    """Expand existing ranked vintages causally; identity mapping stays external."""
    dates = pd.DatetimeIndex(pd.to_datetime(calendar)).normalize()
    require(not dates.has_duplicates and dates.is_monotonic_increasing
            and not dates.hasnans and (dates < BOUNDARY).all(), 'PRE2026_ORDERED_CALENDAR_REQUIRED')
    ordered = sorted(ranked_snapshots, key=lambda item: pd.Timestamp(item['audit']['effective_at']))
    require(ordered, 'NO_QUALIFIED_RANKED_SNAPSHOT')
    effective = [pd.Timestamp(item['audit']['effective_at']) for item in ordered]
    require(all(time.tzinfo is not None for time in effective) and len(set(effective)) == len(effective), 'INVALID_SNAPSHOT_ACTIVATION')
    rows = []
    for date in dates:
        decision = date.tz_localize('America/New_York') + pd.Timedelta(hours=16)
        eligible = [index for index, time in enumerate(effective) if time <= decision]
        if not eligible:
            continue
        index = eligible[-1]
        snapshot = ordered[index]
        day = snapshot['members'].copy()
        day['signal_date'] = date
        day['decision_at'] = decision.isoformat()
        day['available_at'] = effective[index].isoformat()
        day['effective_at'] = effective[index].isoformat()
        day['quarter'] = snapshot['audit']['quarter']
        rows.append(day)
    require(rows, 'NO_ACTIVE_PRE2026_MEMBERSHIP')
    frame = pd.concat(rows, ignore_index=True)
    require(not frame.duplicated(['signal_date', 'cusip']).any(), 'DUPLICATE_DAILY_MEMBERSHIP')
    return frame



def existing_filing_owners(paths):
    """Execute unchanged pure field/unit parser and frozen equity classifier."""
    from scripts.research.a2.inference.aggregate_13f_source_replay import pure_source_functions
    root=paths.results_root/'13f_pit_v1'
    parser_path=root/'scripts/build_13f_history.py'
    classifier_path=root/'scripts/v17b/eligibility_v17b.py'
    refs=dict(unit_parser=file_ref(parser_path),equity_classifier=file_ref(classifier_path))
    parser=pure_source_functions(parser_path,{'localname','text_at','parse_holdings'},{'dt':dt})
    scope=types.ModuleType('consensus_existing_equity_classifier')
    exec(compile(classifier_path.read_text(encoding='utf-8-sig'),str(classifier_path),'exec'),scope.__dict__)
    for ref in refs.values():verify_ref(ref)
    return parser,scope.classify_equity,refs


def normalize_public_rows(raw,filing,parser):
    """Field projection into the existing parser; no fabricated raw XML claim."""
    root=ET.Element('informationTable')
    fields={'nameofissuer':'NAMEOFISSUER','titleofclass':'TITLEOFCLASS','cusip':'CUSIP',
            'value':'VALUE','sshprnamt':'SSHPRNAMT','sshprnamttype':'SSHPRNAMTTYPE','putcall':'PUTCALL'}
    raw=raw.sort_values('INFOTABLE_SK').reset_index(drop=True)
    for row in raw.to_dict('records'):
        node=ET.SubElement(root,'infoTable')
        for xml,column in fields.items():ET.SubElement(node,xml).text='' if pd.isna(row[column]) else str(row[column])
    normalized=parser.parse_holdings(root,filing['filed_date'])
    require(len(normalized)==len(raw) and len(raw)>0,'PUBLIC_INITIAL_ROWS_DROPPED_BY_EXISTING_PARSER')
    rows=[]
    for index,row in enumerate(normalized):
        value=Decimal(str(row['value_usd']))
        require(value.is_finite() and value>=0,'INVALID_NORMALIZED_PUBLIC_VALUE')
        rows.append(dict(manager_id=filing['manager_id'],source_row_id=str(raw.loc[index,'INFOTABLE_SK']),
                         original_accession=filing['accession'],cusip=row['cusip'],issuer_name=row['issuer_name'],
                         title_of_class=row['title_of_class'],ssh_prnamt_type=row['share_type'],put_call=row['put_call'],value_usd=str(value)))
    return pd.DataFrame(rows)


def physical_metadata_projection(pin,columns,clock):
    from scripts.research.a2.data.joint_input_binding import guard_parquet
    _,receipt=guard_parquet(pin['path'],pin['sha256'],[clock])
    require(receipt['rows']==pin['rows'],'FROZEN_METADATA_ROW_COUNT_CHANGED')
    require(set(columns)<=set(receipt['schema']),'IDENTITY_OR_CALENDAR_SCHEMA_MISSING')
    before=file_ref(pin['path'])
    frame=pq.read_table(pin['path'],columns=columns).to_pandas()
    verify_ref(before)
    return frame,dict(**receipt,projection_columns=list(columns),numeric_features_or_targets_read=False)


def materialize_inputs(run_dir,receipt=None):
    """Build only authorized pre2026 original-public holdings and identity keys."""
    from scripts.research.a2.training.stateful_inputs import SOURCES
    paths=resolve(Path(__file__).resolve().parents[4]);run=Path(run_dir).resolve()
    assert_safe_output_path(run,kind='backtest',paths=paths)
    require(run.is_dir() and run.parent.name==TASK,'EXISTING_TASK_RUN_REQUIRED')
    receipt=receipt or preflight_sources()
    require(receipt['task_id']==TASK and receipt['filing_policy']==INITIAL_POLICY
            and receipt['summary']['complete_quarters']==23 and not receipt['failures'],'COMPLETE_23_QUARTER_SOURCE_PREFLIGHT_REQUIRED')
    require(receipt['source_ref']==file_ref(Path(__file__)),'PREFLIGHT_READER_VERSION_CHANGED')
    verify_ref(receipt['current_roster_ref']);verify_ref(receipt['aliases_ref'])
    registry=pd.read_csv(receipt['current_roster_ref']['path'],dtype=str,keep_default_na=False)
    parser,classifier,owner_refs=existing_filing_owners(paths)
    calendar,calendar_proof=physical_metadata_projection(SOURCES['calendar'],['trade_date'],'trade_date')
    identity,identity_proof=physical_metadata_projection(SOURCES['value_training_panel'],
        ['signal_date','cusip','ticker','security_id','security_id_type'],'signal_date')
    source_packages={row['name']:row for row in receipt['packages'] if row['status']=='QUALIFIED_FINITE_PACKAGE_METADATA'}
    derived=run/'derived';derived.mkdir(parents=True,exist_ok=True)
    quarter_path=derived/'consensus100_quarterly.parquet';daily_path=derived/'consensus100_daily.parquet'
    proof_path=derived/'consensus100_inputs_proof.json'
    require(not any(path.exists() for path in (quarter_path,daily_path,proof_path)),'EXISTING_CONSENSUS_INPUTS_PRESERVE_AND_VERIFY_BEFORE_REBUILD')
    snapshots=[];quarter_evidence=[]
    for q in receipt['quarters']:
        clocks=initial_public_clocks(q);groups={}
        for package in sorted(set(row['package'] for row in clocks)):
            selected=[row['accession'] for row in clocks if row['package']==package]
            groups[package]=read_qualified_holdings(source_packages[package],selected)
        full=[];evidence=[]
        snapshot_id=q['quarter']+'_initial_public_'+q['activation_at'][:10]
        for filing in clocks:
            raw=groups[filing['package']]
            raw=raw.loc[raw.ACCESSION_NUMBER.eq(filing['accession'])].copy()
            normalized=normalize_public_rows(raw,filing,parser)
            source_sha=hashlib.sha256(normalized.to_json(orient='records').encode()).hexdigest()
            binding=dict(filing=filing,package_files=source_packages[filing['package']]['files'],owner_refs=owner_refs,
                         public_rows_complete_basis='RETAINED_FULL_ACCESSION_INFOTABLE_EXTRACTION_NO_POSITION_CAP',
                         original_xml='NOT_RECONSTRUCTED_OR_CLAIMED',confidential_omissions='UNKNOWN_NOT_INSTITUTION_TOTAL_ASSETS')
            qualification_sha=hashlib.sha256(json.dumps(binding,sort_keys=True).encode()).hexdigest()
            normalized['source_sha256']=source_sha;normalized['snapshot_id']=snapshot_id;normalized['quarter']=q['quarter']
            full.append(normalized)
            evidence.append(dict(snapshot_id=snapshot_id,quarter=q['quarter'],manager_id=filing['manager_id'],
                holdings_scope='FULL_INITIAL_PUBLIC_AS_FILED_HOLDINGS',full_public_filing_complete=True,
                amendments_handled=False,filing_form='13F-HR',initial_public_filing=True,filing_date=filing['filed_date'],
                disclosure_available_by=filing['disclosure_available_by'],qualification_available_at=filing['disclosure_available_by'],
                effective_at=q['activation_at'],full_row_count=len(normalized),
                full_value_usd=str(sum(map(Decimal,normalized.value_usd),Decimal(0))),source_sha256=source_sha,
                qualification_sha256=qualification_sha,unit_evidence_sha256=owner_refs['unit_parser']['sha256']))
        result=rank_qualified_snapshot(pd.concat(full,ignore_index=True),pd.DataFrame(evidence),registry,
            quarter=q['quarter'],snapshot_id=snapshot_id,decision_at=q['activation_at'],classify_equity=classifier)
        snapshots.append(result);quarter_evidence.append(dict(audit=result['audit'],manager_evidence=evidence,
            audit_only_amendments=q['amendments'],public_row_completeness='PUBLIC_INCLUDED_REPORT_ROWS_ONLY_COVER_CONFIDENTIAL_FIELDS_UNKNOWN'))
    quarterly=pd.concat([item['members'].assign(effective_at=item['audit']['effective_at']) for item in snapshots],ignore_index=True)
    daily=daily_membership(snapshots,calendar.trade_date)
    identity['signal_date']=pd.to_datetime(identity.signal_date);identity['cusip']=identity.cusip.fillna('').astype(str).str.strip().str.upper()
    identity=identity.drop_duplicates()
    conflicts=identity.groupby(['signal_date','cusip']).size().gt(1)
    conflict_keys=conflicts[conflicts].index
    keys=pd.MultiIndex.from_frame(identity[['signal_date','cusip']])
    identity=identity.loc[~keys.isin(conflict_keys)]
    daily=daily.merge(identity,on=['signal_date','cusip'],how='left',validate='one_to_one',sort=False)
    daily['identity_present']=daily.ticker.notna()&daily.security_id.notna()
    daily['identity_source']='RETAINED_PHYSICAL_PRE2026_SIGNAL_DATE_CUSIP_METADATA_ONLY'
    for path in (quarter_path,daily_path,proof_path):assert_safe_output_path(path,kind='backtest',paths=paths)
    quarterly.to_parquet(quarter_path,index=False);daily.to_parquet(daily_path,index=False)
    proof=dict(schema='CONSENSUS100_INITIAL_PUBLIC_INPUT_BUILD_R1',task_id=TASK,reader_ref=file_ref(Path(__file__)),
               aggregate_owner_ref=receipt['aggregate_owner_ref'],filing_policy=INITIAL_POLICY,source_owner_refs=owner_refs,
               source_packages=source_packages,current_roster_ref=receipt['current_roster_ref'],aliases_ref=receipt['aliases_ref'],
               calendar_projection=calendar_proof,identity_projection=identity_proof,quarters=quarter_evidence,
               outputs=dict(quarterly=file_ref(quarter_path),daily=file_ref(daily_path)),
               summary=dict(quarter_rows=len(quarterly),daily_rows=len(daily),daily_sessions=daily.signal_date.nunique(),
                            unique_cusips=daily.cusip.nunique(),unmapped_daily_rows=int((~daily.identity_present).sum()),
                            conflicting_source_identity_keys=len(conflict_keys),market_prices_features_targets_read=False),
               limitations=receipt['uncertified']+['HISTORICAL_IDENTITY_JOIN_NO_NEW_STRICT_PIT_CERTIFICATION','NO_RANK101_COVERAGE_BACKFILL'])
    proof_path.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return dict(proof_path=str(proof_path),**proof['summary'])

def main(argv=None):
    parser = argparse.ArgumentParser()
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--preflight',action='store_true')
    mode.add_argument('--build-run')
    args = parser.parse_args(argv)
    receipt = preflight_sources()
    paths = resolve(Path(__file__).resolve().parents[4])
    destination = paths.results_root / '_maintenance' / TASK / 'data_preflight.json'
    assert_safe_output_path(destination, kind='results', paths=paths)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary=destination.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temporary.replace(destination)
    result=materialize_inputs(args.build_run,receipt) if args.build_run else dict(receipt_path=str(destination),**receipt['summary'])
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    main()
