"""Frozen existing R6/R10 action packets and pure resource decoding.

No fitting, labels, model deserialization, prices, account engine or evaluation.
Real packet values require the physical Phase-0 manifest before parquet reads.
Proxy cohort/sequence state remains the original exogenous producer state.
"""
from __future__ import annotations
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

TASK = 'V24_A_FINAL_ACTION_COVERAGE_AND_STATEFUL_DECISION_R1'
BOUNDARY = pd.Timestamp('2026-01-01')
FORBIDDEN = frozenset(('target', 'edge', 'label_qualified', 'label_mature_date',
                       'label_value', 'e_y', 'i_y', 'basket_y', 'local_regret'))
KINDS = frozenset(('BUY', 'HOLD', 'SELL', 'REPLACE', 'REFERENCE'))


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _ref(ref):
    if not isinstance(ref, dict) or set(ref) != {'path', 'sha256'}:
        raise ValueError('PHYSICAL_REFERENCE_REQUIRED')
    path = Path(ref['path']).resolve()
    if not isinstance(ref['sha256'], str) or sha(path) != ref['sha256']:
        raise ValueError('PHYSICAL_SHA_MISMATCH')
    return path


def _calendar(dates):
    dates = pd.DatetimeIndex(pd.to_datetime(dates))
    if (dates.empty or dates.hasnans or dates.has_duplicates
            or not dates.is_monotonic_increasing or dates.min() < pd.Timestamp('2023-01-01')
            or dates.max() >= BOUNDARY):
        raise ValueError('ONLY_ORDERED_UNIQUE_PRE2026_CALENDAR')
    return dates


def _authorize(census_ref, authorization_ref):
    if authorization_ref is None:
        raise ValueError('PHASE0_PHYSICAL_MANIFEST_REQUIRED_BEFORE_NUMERIC_READ')
    manifest = json.loads(_ref(authorization_ref).read_text(encoding='utf-8-sig'))
    authority = manifest.get('packet_read_authority', {})
    if manifest.get('task_id') != TASK:
        raise ValueError('PACKET_TASK_IDENTITY')
    for key in ('enabled', 'phase0_frozen', '2026_locked', 'no_label_columns'):
        if authority.get(key) is not True:
            raise ValueError('PACKET_AUTHORITY_LITERAL_TRUE_' + key)
    if (authority.get('allowed_start') != '2023-01-01'
            or authority.get('cutoff_exclusive') != '2026-01-01'
            or authority.get('census_ref') != census_ref):
        raise ValueError('PACKET_AUTHORITY_BOUNDARY_OR_CENSUS')
    reader = _ref(authority.get('reader_source_ref'))
    if reader != Path(__file__).resolve():
        raise ValueError('PACKET_READER_SOURCE_IDENTITY')
    census = json.loads(_ref(census_ref).read_text(encoding='utf-8-sig'))
    if census.get('task_id') != TASK or census.get('selection_uses_economic_results') is not False:
        raise ValueError('CENSUS_IDENTITY_OR_OUTCOME_SELECTION')
    return census


def _read_packet(ref, wanted, dates, tickers):
    """Hash/footer first, then only requested causal outputs and identity keys."""
    if set(wanted) & FORBIDDEN:
        raise ValueError('LABEL_OR_ECONOMIC_COLUMN_FORBIDDEN')
    path = _ref({'path':ref['path'],'sha256':ref['sha256']})
    footer = pq.ParquetFile(path)
    names = footer.schema_arrow.names
    if 'signal_date' not in names or 'sample_id' not in names or 'ticker' not in names:
        raise ValueError('PACKET_IDENTITY_SCHEMA')
    # Never read a mixed post-2025 row group and filter it afterwards.
    date_column = names.index('signal_date')
    for n in range(footer.num_row_groups):
        stat = footer.metadata.row_group(n).column(date_column).statistics
        if stat is None or not stat.has_min_max or pd.Timestamp(stat.max) >= BOUNDARY:
            raise ValueError('PACKET_PRE2026_PHYSICAL_FOOTER_REQUIRED')
    columns = [c for c in wanted if c in names]
    frame = pd.read_parquet(path, columns=columns,
        filters=[('signal_date', '>=', dates.min()), ('signal_date', '<', BOUNDARY)])
    frame['signal_date'] = pd.to_datetime(frame.signal_date)
    frame = frame.loc[frame.signal_date.isin(dates) & frame.ticker.astype(str).isin(tickers)].copy()
    if frame.duplicated(['signal_date', 'sample_id']).any():
        raise ValueError('DUPLICATE_PACKET_KEY')
    return frame


def _finite(value):
    return value is not None and not isinstance(value, (bool, np.bool_)) and np.isscalar(value) and bool(np.isfinite(value))


def _proposal(row, kind, decision, order, *, score=None, native=False, semantic='', local='R6'):
    return dict(kind=kind, decision=decision, ticker=str(row['ticker']),
        entrant=None if pd.isna(row.get('entrant_ticker')) else str(row.get('entrant_ticker')),
        sample_id=str(row['sample_id']), source_order=int(order),
        source_score=float(score) if _finite(score) else None, native_used=bool(native),
        semantic=semantic, eligible_proxy_support=True, local_resolver=local,
        security_id=row.get('security_id'), entrant_security_id=row.get('entrant_security_id'))


def decode_r6_row(row, objective, source_order=0, *, native_mode='NATIVE'):
    """Original frozen per-row decoder; equality follows the frozen spec."""
    if native_mode not in ('NATIVE', 'POINT'):
        raise ValueError('UNKNOWN_NATIVE_ARM')
    if objective in ('buy', 'hold', 'replace'):
        p = row.get('p_superior')
        if not _finite(p) or not 0 <= p <= 1 or p == .5:
            return _proposal(row, 'REFERENCE', 'REFERENCE', source_order, semantic='TIES_OR_UNKNOWN_REFERENCE')
        positive = p > .5
        if objective == 'buy':
            return _proposal(row, 'BUY' if positive else 'REFERENCE', 'BUY' if positive else 'SKIP', source_order, score=p, semantic='R6_BUY_VS_SKIP')
        if objective == 'hold':
            return _proposal(row, 'HOLD' if positive else 'SELL', 'HOLD' if positive else 'SELL', source_order, score=p, semantic='R6_HOLD_EXACT_UNITS_VS_SELL')
        copy = dict(row, ticker=row.get('incumbent'), entrant_ticker=row['ticker'],
                    security_id=row.get('incumbent_sid'), entrant_security_id=row.get('security_id'))
        return _proposal(copy, 'REPLACE' if positive else 'HOLD', 'REPLACE' if positive else 'HOLD_SKIP_PAIR', source_order, score=p, semantic='R6_REPLACE_VS_HOLD')
    if objective == 'duration':
        p = row.get('p_failure')
        age = row.get('cohort_age_sessions')
        if not _finite(p) or not 0 <= p <= 1 or age not in (0, 7, 14):
            return _proposal(row, 'REFERENCE', 'REFERENCE', source_order, semantic='UNKNOWN_OR_NONPROBE_REFERENCE')
        return _proposal(row, 'SELL' if p > .5 else 'REFERENCE', 'SELL' if p > .5 else 'REFERENCE', source_order, score=p, semantic='ORIGINAL_OOF_MATURE_RISKSET_FIXED_PROXY_PROBE')
    if objective != 'distribution':
        raise ValueError('R6_OBJECTIVE_NOT_ADMITTED')
    q10, q50, q90, width = (row.get(k) for k in ('q10', 'q50', 'q90', 'width'))
    if not all(_finite(v) for v in (q10, q50, q90, width)) or q10 > q50 or q50 > q90 or width < 0:
        return _proposal(row, 'REFERENCE', 'REFERENCE', source_order, native=True, semantic='UNKNOWN_NATIVE_REFERENCE')
    k = (1 - .001) / (1 + .001)
    entrant = bool(row.get('proxy_entrant', False))
    if entrant:
        point = k * (1 + q50) - 1 > 0
        chosen = point and (native_mode == 'POINT' or (k * (1 + q10) - 1 >= -.02 and width <= .25))
        return _proposal(row, 'BUY' if chosen else 'REFERENCE', 'BUY' if chosen else 'SKIP', source_order, score=q50, native=native_mode == 'NATIVE', semantic='R6_DISTRIBUTION_ENTRY_' + native_mode)
    point = (1 - .001) * q50 >= 0
    chosen = point and (native_mode == 'POINT' or ((1 - .001) * q10 >= -.03 and width <= .30))
    return _proposal(row, 'HOLD' if chosen else 'SELL', 'HOLD' if chosen else 'SELL', source_order, score=q50, native=native_mode == 'NATIVE', semantic='R6_DISTRIBUTION_HOLD_' + native_mode)


def decode_r6_distribution_pair(row, source_order=0, *, native_mode='NATIVE'):
    if native_mode not in ('NATIVE', 'POINT'):
        raise ValueError('UNKNOWN_NATIVE_ARM')
    e = row.get('entrant_q10') if native_mode == 'NATIVE' else row.get('entrant_q50')
    i = row.get('incumbent_q90') if native_mode == 'NATIVE' else row.get('incumbent_q50')
    copy = dict(row, ticker=row.get('incumbent'), entrant_ticker=row['ticker'],
                    security_id=row.get('incumbent_sid'), entrant_security_id=row.get('security_id'))
    if not _finite(e) or not _finite(i):
        return _proposal(copy, 'REFERENCE', 'REFERENCE', source_order, native=native_mode == 'NATIVE', semantic='UNKNOWN_PAIR_REFERENCE')
    margin = (1 - .001) * ((1 - .001) / (1 + .001) * (1 + e) - (1 + i))
    positive = margin > 0
    return _proposal(copy, 'REPLACE' if positive else 'HOLD', 'REPLACE' if positive else 'HOLD_SKIP_PAIR', source_order, score=margin, native=native_mode == 'NATIVE', semantic='R6_DISTRIBUTION_REPLACE_' + native_mode)


def decode_r10_row(row, source_order=0, *, group='INCUMBENT'):
    if group == 'HAZARD':
        p = row.get('probability')
        if not _finite(p) or not 0 <= p <= 1:
            return _proposal(row, 'REFERENCE', 'REFERENCE', source_order, semantic='UNKNOWN_HAZARD_REFERENCE', local='R10')
        return _proposal(row, 'SELL' if p > .5 else 'REFERENCE', 'SELL' if p > .5 else 'REFERENCE', source_order, score=p-.5, semantic='R10_ORIGINAL_MATURE_PROBE_HAZARD', local='R10')
    score = row.get('mean')
    if not _finite(score): score = row.get('q50')
    if not _finite(score):
        probability = row.get('probability')
        score = probability - .5 if _finite(probability) and 0 <= probability <= 1 else None
    if not _finite(score):
        return _proposal(row, 'REFERENCE', 'REFERENCE', source_order, semantic='UNKNOWN_OUTPUT_REFERENCE', local='R10')
    positive = score > 0
    if group == 'ENTRY':
        return _proposal(row, 'BUY' if positive else 'REFERENCE', 'BUY' if positive else 'SKIP', source_order, score=score, semantic='R10_ENTRY_ADVANTAGE', local='R10')
    token = row.get('action_type')
    if token == -1:
        # The frozen full INCUMBENT actionset explicitly excludes the auxiliary
        # CONTINUATION token. It is not a second contradictory SELL/HOLD vote.
        return _proposal(row, 'REFERENCE', 'REFERENCE', source_order, score=score, semantic='R10_CONTINUATION_AUXILIARY_NOT_INCUMBENT_ACTION', local='R10')
    if token == 0:
        return _proposal(row, 'SELL' if positive else 'HOLD', 'SELL' if positive else 'HOLD', source_order, score=score, semantic='R10_SELL_VS_HOLD_ZERO_REFERENCE', local='R10')
    if token == 1:
        return _proposal(row, 'REPLACE' if positive else 'HOLD', 'REPLACE' if positive else 'HOLD_SKIP_PAIR', source_order, score=score, semantic='R10_REPLACE_VS_HOLD_ZERO_REFERENCE', local='R10')
    return _proposal(row, 'REFERENCE', 'REFERENCE', source_order, score=score, semantic='UNKNOWN_ACTION_TOKEN_REFERENCE', local='R10')


def decode_resource_proposals(records, held, allowed):
    """Local choice first; stable resource conflicts preserve reference, no retry.

    `allowed` is the caller's unchanged Raw buy pool intersected with execution
    legality. It never re-ranks entrants. Negative pairs cannot reserve an entrant
    ahead of a positive action. The returned diagnostics are not performance.
    """
    held, allowed = set(held), set(allowed)
    records = [dict(r) for r in records]
    for r in records:
        if r.get('kind') not in KINDS or type(r.get('source_order')) is not int:
            raise ValueError('ACTION_PROPOSAL_SCHEMA')
    groups = defaultdict(list); singles = []
    for r in records:
        if r.get('entrant') is not None or r['kind'] in ('SELL','HOLD'):
            groups[r['ticker']].append(r)
        else: singles.append(r)
    local = []
    for ticker, rows in groups.items():
        positives = [r for r in rows if r['kind'] in ('SELL','REPLACE')
                     and (r.get('local_resolver') == 'R6'
                          or (_finite(r.get('source_score')) and r['source_score'] > 0))]
        if positives:
            if any(r.get('local_resolver') == 'R10' for r in rows):
                local.append(min(positives, key=lambda r: (-r['source_score'], r['sample_id'])))
            else: local.append(min(positives, key=lambda r: r['source_order']))
        else:
            negatives = [r for r in rows if r['kind'] == 'HOLD']
            if negatives: local.append(min(negatives, key=lambda r: r['source_order']))
            else: local.append(min(rows, key=lambda r: r['source_order']))
    proposed = sorted(singles + local, key=lambda r: (r['source_order'], r['sample_id']))
    # Common protocol for the full native and point arms: incumbent action
    # choice precedes independent BUY, so BUY cannot pre-empt every REPLACE.
    positive = [r for r in proposed if r['kind'] in ('SELL','REPLACE')]
    positive += [r for r in proposed if r['kind'] == 'BUY']
    remainder = [r for r in proposed if r['kind'] not in ('BUY','SELL','REPLACE')]
    accepted=[]; conflicts=[]; used_inc=set(); used_ent=set()
    for r in positive:
        inc = r['ticker'] if r['kind'] in ('SELL','REPLACE') else None
        ent = r.get('entrant') if r['kind']=='REPLACE' else r['ticker'] if r['kind']=='BUY' else None
        reason = None
        if inc is not None and inc not in held: reason='INCUMBENT_NOT_ACTUALLY_HELD'
        elif ent is not None and (ent not in allowed or ent in held): reason='ENTRANT_NOT_FROZEN_RAW_LEGAL_POOL'
        elif inc in used_inc or ent in used_ent: reason='RESOURCE_ALREADY_USED_REFERENCE_NO_ALTERNATE_PARTNER'
        if reason:
            conflicts.append(dict(sample_id=r['sample_id'],source_order=r['source_order'],reason=reason,reference_preserved=True));continue
        if inc is not None: used_inc.add(inc)
        if ent is not None: used_ent.add(ent)
        accepted.append(r)
    skipped=set()
    for r in remainder:
        if r.get('semantic') == 'R10_CONTINUATION_AUXILIARY_NOT_INCUMBENT_ACTION':continue
        if r['kind']=='HOLD':
            if r['ticker'] not in held or r['ticker'] in used_inc:continue
            accepted.append(r);used_inc.add(r['ticker'])
        elif r.get('decision')=='SKIP':
            if r['ticker'] not in used_ent:
                accepted.append(r);skipped.add(r['ticker'])
        else:accepted.append(r)
    # Keep every original negative pair's rejection, including pairs not chosen
    # as the incumbent's single HOLD representative. Never overwrite a positive
    # entrant or reserve it before positive resource resolution.
    for r in sorted(records,key=lambda x:(x['source_order'],x['sample_id'])):
        entrant=r.get('entrant')
        if (r.get('decision')=='HOLD_SKIP_PAIR' and r['ticker'] in held
                and entrant in allowed and entrant not in held
                and entrant not in used_ent and entrant not in skipped):
            skip=dict(r,kind='REFERENCE',decision='SKIP',ticker=entrant,entrant=None,
                      security_id=r.get('entrant_security_id'),entrant_security_id=None,
                      semantic='NEGATIVE_PAIR_SKIP_AFTER_ALL_POSITIVES')
            accepted.append(skip);skipped.add(entrant)
    return {'accepted':sorted(accepted,key=lambda r:(r['source_order'],r['sample_id'],r['kind'])),
            'conflicts':conflicts,'positive_incumbents':sorted(used_inc),
            'positive_entrants':sorted(used_ent),'local_candidates':len(local),
            'no_partner_substitution':True}


def _member_frames(rep, rows, dates, tickers):
    members=[rows[x] for x in rep['member_slot_ids']]
    output=[]
    for member in members:
        pub=member.get('publication') or {'path':member['oof_path'],'sha256':member['oof_sha256']}
        columns=['signal_date','sample_id','ticker','security_id','incumbent','entrant_ticker','action_type','cohort_age_sessions']
        if rep['representative_id'].startswith('R6_'):
            objective=rep['original_candidate']['objective']
            columns += ['q10','q50','q90','width'] if objective=='distribution' else ['p_failure'] if objective=='duration' else ['p_superior']
        else:columns += ['mean','q50','probability']
        frame=_read_packet(pub,columns,dates,tickers)
        frame['_group']=member.get('group',member.get('objective'));frame['_year']=member['year']
        frame['_seed']=member.get('seed');frame['_member_slot']=member['slot_id'];output.append(frame)
    if not output:return pd.DataFrame()
    all_rows=pd.concat(output,ignore_index=True)
    if rep['representative_id'].startswith('R6_'):return all_rows
    # Original deterministic singleton or equal fixed-three-seed ensemble.
    keys=['_group','_year','signal_date','sample_id']
    combined=[]
    expected_keys = {}
    for (_, year, group_name), block in all_rows.groupby(['_seed','_year','_group'],sort=False,dropna=False):
        identity = tuple(zip(block.signal_date.astype(str), block.sample_id.astype(str)))
        role = (year, group_name)
        if role in expected_keys and expected_keys[role] != identity:
            raise ValueError('FROZEN_SEED_KEY_ORDER_MISMATCH')
        expected_keys[role] = identity
    for _, group in all_rows.groupby(keys,sort=False,dropna=False):
        expected=3 if len({m['seed'] for m in members if m.get('group')==group['_group'].iloc[0] and m['year']==group['_year'].iloc[0]})==3 else 1
        if len(group)!=expected or group['_seed'].duplicated().any():raise ValueError('FROZEN_SEED_BUNDLE_KEY_MISMATCH')
        first=group.iloc[0].to_dict()
        for col in ('mean','q50','probability'):
            if col in group:first[col]=float(np.mean(group[col].to_numpy(float)))
        for col in ('ticker','security_id','incumbent','entrant_ticker','action_type'):
            if col in group and group[col].astype(str).nunique(dropna=False)!=1:raise ValueError('SEED_IDENTITY_OR_ACTION_TOKEN_MISMATCH')
        combined.append(first)
    return pd.DataFrame(combined)


def _original_sid_support(rows, dates, tickers):
    # Identity-only views of the earliest original role publications. These are
    # original producer SID bindings, not today's ticker/security mapping.
    sid = {}; proxy_entrants = set()
    for year in (2024, 2025):
        for objective in ('buy', 'hold'):
            member=rows[objective + '_linear_' + str(year)]
            f=_read_packet({'path':member['oof_path'],'sha256':member['oof_sha256']},
                ['signal_date','sample_id','ticker','security_id'],dates,tickers)
            for r in f.to_dict('records'):
                key=('R6',r['signal_date'],str(r['ticker']))
                if key in sid and str(sid[key])!=str(r['security_id']):raise ValueError('ORIGINAL_SID_ROLE_CONFLICT')
                sid[key]=r['security_id']
                if objective=='buy':proxy_entrants.add((r['signal_date'],str(r['ticker']),str(r['security_id'])))
        members=[r for r in rows.values() if r.get('family')=='ridge' and r.get('capacity')=='LOW'
                 and r.get('group')=='ENTRY' and r.get('horizon')=='MEAN' and r.get('year')==year
                 and not r.get('prefix') and r.get('status')=='TRAINED']
        if len(members)!=1:raise ValueError('ORIGINAL_R10_ENTRY_SID_PUBLICATION_REQUIRED')
        f=_read_packet(members[0]['publication'],['signal_date','sample_id','ticker','security_id'],dates,tickers)
        for r in f.to_dict('records'):sid[('R10',r['signal_date'],str(r['ticker']))]=r['security_id']
    return sid,proxy_entrants


def load_packets(census, dates, tickers, *, authorization_ref=None):
    """Load only admitted, physically frozen original action output projections.

    A representative still needs caller/registry account admission. This function
    never runs accounts, acquires data, upgrades authority or invents a fallback.
    """
    dates=_calendar(dates);tickers={str(t) for t in tickers}
    bound=_authorize(census,authorization_ref);rows={r['slot_id']:r for r in bound['objects']}
    packets={};diagnostics={}
    original_sid,proxy_entrant_keys=_original_sid_support(rows,dates,tickers)
    for rep in bound['representatives']:
        if rep['classification'] not in ('A_DIRECT_ACTION_COMPATIBLE','A_SEQUENCE_ACTION_COMPATIBLE'):continue
        rid=rep['representative_id'];frame=_member_frames(rep,rows,dates,tickers)
        perdate=defaultdict(list)
        if rid.startswith('R6_'):
            objective=rep['original_candidate']['objective']
            # Physical publication row order preserves the original producer's
            # pre-label pair order. Never rank pairs by observed outcomes.
            if objective == 'distribution':
                learner = rep['original_candidate']['learner']
                entrant_keys = proxy_entrant_keys
                marginal = {(r['signal_date'], str(r['ticker']), str(r['security_id'])):r
                            for r in frame.to_dict('records')}
                for date, day in frame.groupby('signal_date',sort=True):
                    for order, row in enumerate(day.to_dict('records')):
                        row['proxy_entrant'] = (date,str(row['ticker']),str(row['security_id'])) in entrant_keys
                        if objective=='replace':
                            row['incumbent_sid']=original_sid.get(('R6',date,str(row.get('incumbent'))))
                        perdate[pd.Timestamp(date)].append(decode_r6_row(row,objective,order))
                for member_id in rep['member_slot_ids']:
                    member=rows[member_id]
                    pair = _read_packet({'path':member['distribution_replace_oof_path'],
                        'sha256':member['distribution_replace_oof_sha256']},
                        ['signal_date','sample_id','ticker','security_id','incumbent','incumbent_sid',
                         'entrant_q10','incumbent_q90'],dates,tickers)
                    for date, day in pair.groupby('signal_date',sort=True):
                        offset=len(perdate[pd.Timestamp(date)])
                        for order,row in enumerate(day.to_dict('records'),start=offset):
                            # Original two marginals supply the point arm without
                            # any additional fit, inference or new training rows.
                            e=marginal.get((date,str(row['ticker']),str(row['security_id'])))
                            i=marginal.get((date,str(row['incumbent']),str(row.get('incumbent_sid'))))
                            row['entrant_q50']=None if e is None else e.get('q50')
                            row['incumbent_q50']=None if i is None else i.get('q50')
                            perdate[pd.Timestamp(date)].append(decode_r6_distribution_pair(row,order))
            else:
                for date,day in frame.groupby('signal_date',sort=True):
                    for order,row in enumerate(day.to_dict('records')):
                        if objective=='replace':
                            row['incumbent_sid']=original_sid.get(('R6',date,str(row.get('incumbent'))))
                        perdate[pd.Timestamp(date)].append(decode_r6_row(row,objective,order))
        else:
            for date,day in frame.groupby('signal_date',sort=True):
                for order,row in enumerate(day.to_dict('records')):
                    group=row['_group'];role='HAZARD' if group=='HAZARD' else 'ENTRY' if group=='ENTRY' else 'INCUMBENT'
                    if row.get('action_type')==1:
                        row['entrant_security_id']=original_sid.get(('R10',date,str(row.get('entrant_ticker'))))
                    perdate[pd.Timestamp(date)].append(decode_r10_row(row,order,group=role))
        packets[rid]=dict(perdate);diagnostics[rid]={'rows':len(frame),'dates':len(perdate),'year2023':'RAW_REFERENCE','labels_read':0,'new_fit':0,'packet_role':'EXISTING_ORIGINAL_OOF_ACTION_OUTPUT_ONLY'}
    return {'packets':packets,'diagnostics':diagnostics,'2026_rows_read':0,'new_fit':0}
