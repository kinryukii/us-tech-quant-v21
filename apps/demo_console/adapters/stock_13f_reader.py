"""Read registered institutions' evidenced holdings; never change a selection."""
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
import ast
import datetime
import json
import numpy as np
import pandas as pd

from apps.demo_console.adapters import updated_research_reader as reader


def _json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _checked(ref):
    path = Path(ref['path'])
    if reader._hash(path) != ref['sha256']:
        raise ValueError('STOCK_13F_SOURCE_HASH_CHANGED')
    return path


def _ref(path):
    return {'path': str(path), 'sha256': reader._hash(path)}


def _readonly_parser(reference):
    """Reuse only the three verified XML functions, without research-runner setup."""
    path = _checked(reference)
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    names = {'localname', 'text_at', 'parse_holdings'}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in nodes} != names or len(nodes) != 3:
        raise ValueError('13F_PARSER_CONTRACT_CHANGED')
    scope = {'dt': datetime}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(path), 'exec'), scope)
    return SimpleNamespace(**{name: scope[name] for name in names})


def summarize_holders(holdings, registry, filings, *, cusip, quarter, as_of):
    """Exact security identity, no options, no future filing, no person inference."""
    frame = holdings.loc[holdings.cusip.astype(str).eq(cusip) & holdings.quarter.eq(quarter)].copy()
    if 'put_call' in frame:
        frame = frame.loc[frame.put_call.fillna('').astype(str).str.strip().eq('')]
    share_type = 'share_type' if 'share_type' in frame else 'ssh_prnamt_type'
    if share_type in frame:
        frame = frame.loc[frame[share_type].fillna('').astype(str).str.upper().eq('SH')]
    people = registry.set_index('manager_id').to_dict('index')
    records = []
    for manager, rows in frame.groupby('manager_id', sort=True):
        if manager not in people:
            raise ValueError('UNREGISTERED_13F_MANAGER')
        metadata = people[manager]
        if quarter < str(metadata['active_from_quarter']) or (
                metadata.get('active_to_quarter') and quarter > str(metadata['active_to_quarter'])):
            raise ValueError('13F_MANAGER_OUTSIDE_REGISTERED_PERIOD')
        evidence = filings.loc[filings.manager_id.eq(manager) & filings.quarter.eq(quarter)]
        evidence = evidence.loc[pd.to_datetime(evidence.filed_date).dt.strftime('%Y-%m-%d').le(as_of)]
        if 'filing_date' in rows:
            dates = pd.to_datetime(rows.filing_date).dt.strftime('%Y-%m-%d')
            rows = rows.loc[dates.le(as_of)]
            filed = dates.loc[rows.index].max() if not rows.empty else None
        else:
            evidence = evidence.loc[pd.to_datetime(evidence.filed_date).dt.strftime('%Y-%m-%d').le(as_of)]
            filed = str(pd.to_datetime(evidence.filed_date).max().date()) if not evidence.empty else None
        if rows.empty or not filed:
            continue
        # A later amendment's content may never acquire an earlier filing date.
        if 'accession_key' in rows and not evidence.empty:
            known = set(evidence.accession.astype(str).str.replace('-', '', regex=False))
            if not set(rows.accession_key.astype(str)) <= known:
                raise ValueError('13F_ACCESSION_NOT_IN_SELECTED_VINTAGE')
        values = pd.to_numeric(rows.reported_value_usd, errors='raise')
        quantities = pd.to_numeric(rows.shares, errors='raise') if 'shares' in rows else None
        if not np.isfinite(values).all() or values.lt(0).any() or quantities is not None and (
                not np.isfinite(quantities).all() or quantities.lt(0).any()):
            raise ValueError('13F_INVALID_HOLDING_VALUE')
        value = values.sum()
        shares = quantities.sum() if quantities is not None else None
        if 'accession_key' in rows and not evidence.empty:
            evidence = evidence.loc[evidence.accession.astype(str).str.replace('-', '', regex=False).isin(
                set(rows.accession_key.astype(str)))]
        if not evidence.empty and 'source_url' in evidence:
            source_url = evidence.sort_values('filed_date').iloc[-1].source_url
        else:
            accession = str(rows.iloc[0].accession_key)
            source_url = f'https://www.sec.gov/Archives/edgar/data/{int(metadata["cik"])}/{accession}/'
        records.append({'institution_name': metadata['manager_name'],
            'notable_person': metadata.get('notable_person') or '', 'manager_id': manager,
            'reported_value': float(value), 'shares': None if shares is None else float(shares),
            'filing_date': filed, 'source_url': source_url})
    return sorted(records, key=lambda row: (-row['reported_value'], row['manager_id']))


@lru_cache(maxsize=3)
def _current_holdings(report_path, report_sha, recovery_path, recovery_sha, cache_root, results_root, as_of):
    from scripts.daily_recommendation_universe import _inspect_filing, _apply_filings
    report = _json(_checked({'path': report_path, 'sha256': report_sha}))
    recovery = _json(_checked({'path': recovery_path, 'sha256': recovery_sha}))
    evidence_path = Path(report_path).parent / 'filing_evidence.json'
    evidence = [row for row in _json(evidence_path)['filings'] if str(row['filed_date'])[:10] <= as_of]
    originals = {row['url']: row for row in recovery['raw_filings']}
    acquisition = Path(results_root) / '13f_intake/13f_personal_contact_20260914/acquisition.json'
    if acquisition.is_file():
        for row in _json(acquisition).get('verified_filings', []):
            originals[row['source_url']] = {'path': row['raw_path'], 'sha256': row['source_sha256']}
    receipts = Path(report_path).parent / 'raw' / 'request_receipts.json'
    if receipts.is_file():
        for row in _json(receipts).get('sources', []):
            if row.get('status') == 200 and row.get('raw_path'):
                originals[row['url']] = {'path': row['raw_path'], 'sha256': row['sha256']}
    parser_ref = recovery['sources']['xml_parser']
    parser = _readonly_parser(parser_ref)
    records, refs = [], [_ref(evidence_path), parser_ref]
    for filing in evidence:
        original = originals.get(filing['source_url'])
        if original is None or original['sha256'] != filing['source_sha256']:
            raise ValueError('13F_VERIFIED_RAW_FILING_UNAVAILABLE')
        raw_ref = {'path': original['path'], 'sha256': filing['source_sha256']}
        payload = _checked(raw_ref).read_bytes()
        rows, details = _inspect_filing(payload, filing, parser)
        records.append((filing, rows, details)); refs.append(raw_ref)
    holdings, filings = _apply_filings(records)
    return holdings, filings, refs


def read_stock_holders(model, ticker, mode='AS_OF_SIGNAL', paths=None, security_id=None):
    try:
        if mode not in {'AS_OF_SIGNAL', 'LATEST_DISCLOSED'}:
            raise ValueError('13F_UNKNOWN_VIEW_MODE')
        if paths is None:
            from scripts.common.storage_paths import resolve
            paths = resolve()
        from apps.demo_console.adapters.workspace_reader import source_reference
        parent_ref = source_reference(model)
        parent = _json(_checked(parent_ref))
        hist_ref = parent['ranking_manifest']; hist = _json(_checked(hist_ref))
        ranks = pd.read_parquet(_checked(hist['outputs']['ranked']))
        members = pd.read_parquet(_checked(hist['universe_outputs']['members']))
        day = str(model.decision_date)[:10]
        available = ranks.loc[ranks.ticker.eq(ticker) & ranks.target_date.astype(str).str[:10].le(day)]
        if security_id is not None:
            available = available.loc[available.security_id.astype(str).eq(str(security_id))]
        if available.empty:
            identities = members.loc[members.ticker.eq(ticker) & members.mapping_verified.eq(True)
                & members.effective_date.astype(str).str[:10].le(day)]
            if security_id is not None:
                identities = identities.loc[identities.security_id.astype(str).eq(str(security_id))]
            if identities.empty or identities.security_id.nunique() != 1:
                raise ValueError('13F_STOCK_HAS_NO_UNAMBIGUOUS_RECORDED_IDENTITY')
            security_id = str(identities.iloc[0].security_id)
        else:
            identity = available.sort_values('target_date').iloc[-1]
            security_id = str(identity.security_id)
        candidates = members.loc[members.security_id.astype(str).eq(security_id), 'cusip'].astype(str).unique()
        if len(candidates) != 1:
            raise ValueError('13F_SECURITY_IDENTITY_AMBIGUOUS')
        cusip = candidates[0]
        source_ref = {'path': hist['source_report'], 'sha256': hist['source_report_sha256']}
        source = _json(_checked(source_ref))
        universe_ref = {'path': source['universe']['report_path'], 'sha256': hist['universe_report_sha256']}
        universe = _json(_checked(universe_ref))
        if mode == 'LATEST_DISCLOSED':
            evaluation = _json(_checked(parent['evaluation_contract']))
            source_ref = evaluation['current_report']
            source = _json(_checked(source_ref))
            universe_ref = _ref(Path(source['universe']['report_path']))
            universe = _json(_checked(universe_ref))
            if any(universe.get(key) != source['universe'].get(key)
                   for key in ('quarter', 'universe_manifest_sha256', 'universe_members_sha256', 'effective_date')):
                raise ValueError('13F_CURRENT_REPORT_UNIVERSE_CHANGED')
            if universe.get('universe_id') != source['universe'].get('universe_id'):
                recomputed = source.get('historical_recomputation', {})
                if (recomputed.get('sha256') != hist_ref['sha256']
                        or Path(recomputed.get('path', '')).resolve() != Path(hist_ref['path']).resolve()):
                    raise ValueError('13F_RECOMPUTED_POOL_NOT_BOUND')
                ledger = pd.read_parquet(_checked(hist['universe_outputs']['ledger']))
                actual = ledger.loc[ledger.target_date.astype(str).str[:10].eq(source['data_date'])]
                if len(actual) != 1 or actual.iloc[0].universe_id != source['universe']['universe_id']:
                    raise ValueError('13F_RECOMPUTED_POOL_IDENTITY_CHANGED')
        recovery_path = Path(paths.data_root) / '13f/recovery_20260913/quarter_manifest.json'
        recovery_ref = _ref(recovery_path); recovery = _json(recovery_path)
        registry_ref = recovery['sources']['registry']
        registry = pd.read_csv(_checked(registry_ref), dtype=str, keep_default_na=False)
        refs = [parent_ref, hist_ref, source_ref, universe_ref, recovery_ref, registry_ref]
        schedule = pd.read_parquet(_checked(hist['universe_outputs']['schedule']))
        versions = schedule.loc[pd.to_datetime(schedule.effective_date).le(pd.Timestamp(day))]
        if versions.empty:
            raise ValueError('13F_NO_EFFECTIVE_POOL_AT_SIGNAL')
        selected_version = versions.sort_values('effective_date').iloc[-1]
        latest = mode == 'LATEST_DISCLOSED'
        quarter = universe['quarter'] if latest else selected_version.quarter
        effective = universe['effective_date'] if latest else str(selected_version.effective_date)[:10]
        revision = latest or quarter == universe['quarter'] and selected_version.version_kind == 'REVISION'
        if revision:
            as_of = str(universe.get('latest_disclosures_checked_at') or source['data_date'])[:10] if latest else day
            holdings, filings, extra = _current_holdings(str(_checked(universe_ref)), universe_ref['sha256'],
                str(recovery_path), recovery_ref['sha256'], str(paths.cache_root), str(paths.results_root), as_of)
            refs.extend(extra)
            scope = 'REGISTERED_INSTITUTIONS_FULL_VERIFIED_FILINGS'
        elif quarter == recovery['quarter']:
            holdings = pd.read_parquet(_checked(recovery['files']['raw_holdings']))
            filings = pd.read_parquet(_checked(recovery['files']['filings']))
            refs.extend([recovery['files']['raw_holdings'], recovery['files']['filings']])
            as_of, scope = day, 'REGISTERED_INSTITUTIONS_FULL_INITIAL_FILINGS'
        else:
            ref = recovery['files']['historical_selected_top100_units']
            holdings = pd.read_parquet(_checked(ref)); refs.append(ref)
            filings = pd.DataFrame(columns=['manager_id', 'quarter', 'filed_date', 'accession'])
            as_of, scope = day, 'REGISTERED_INSTITUTIONS_SELECTED_TOP100_HISTORY'
        rows = summarize_holders(holdings, registry, filings, cusip=cusip, quarter=quarter, as_of=as_of)
        for reference in refs:
            _checked(reference)
        return {'status': 'READY', 'quarter': quarter, 'effective_date': effective,
            'filing_as_of': as_of, 'rows': rows, 'source_refs': refs, 'security_id': security_id,
            'signal_date': day, 'scope': scope,
            'limitations': ['Covers the registered institutions, not all SEC filers. Associated people come from the registry; these are institution holdings, not personal accounts.',
                'Historical coverage contains the retained eligible Top100 per institution; an absent row does not prove no holding. Share counts are blank when unavailable.']}
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        return {'status': 'UNAVAILABLE', 'rows': [], 'error': str(exc)}
