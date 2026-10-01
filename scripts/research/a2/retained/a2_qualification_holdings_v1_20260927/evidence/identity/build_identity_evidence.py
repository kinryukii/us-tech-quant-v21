"""45-security identity supplement. Reads frozen evidence; no model/price API calls.

Preserves existing R6 qualifications. Canonical UID allocation is out of scope.
Public clocks, effective dates, and historical provider receipts stay separate.
"""
from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
LINEAGE = ROOT / 'a2_latest_effective_joint_20260927/followup_review/input_lineage'
OLD = ROOT / 'a2_13f_learned_sizing_pre2026_test2026_r1/continuation_2026_r1'
UNIVERSE = Path('D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1/universe')
UID = Path('D:/us-tech-quant-results/permanent_security_uid_authority_policy_r1/20260903T154404Z')
REVIEW_END = '2026-09-24'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def clean(value):
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, 'item'):
        return value.item()
    return value


def records(frame):
    return [{k: clean(v) for k, v in row.items()} for row in frame.to_dict('records')]


def write_json(name, value):
    (HERE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def source_text(name):
    return BeautifulSoup((HERE / 'official_sources' / (name + '.html')).read_bytes(), 'html.parser').get_text(' ', strip=True)


def acceptance(name):
    # EDGAR filing-detail Accepted uses US Eastern local time.
    stamp = re.search(r'Accepted\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', source_text(name)).group(1)
    return datetime.fromisoformat(stamp).replace(tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc).isoformat()


def main():
    paths = {
        'lineage': LINEAGE / 'TICKER_INPUT_LINEAGE.csv',
        'saved_gates': LINEAGE / 'SAVED_GATE_HISTORY_INTERVALS.csv',
        'r6_current': LINEAGE / 'R6_CURRENT_CANDIDATE_EVIDENCE.parquet',
        'resolution75': OLD / 'REMAINING75_RESOLUTION.csv',
        'members': UNIVERSE / 'quarterly_universe_members.parquet',
        'quarter_manifest': UNIVERSE / 'quarterly_universe_manifest.parquet',
        'uid_inventory': UID / 'tables/existing_uid_authority_inventory.csv',
        'uid_policy': UID / 'summary/uid_authority_policy_v1.json',
        'dte_raw': OLD / 'SUBSCRIPTION_US_DTE_RAW_DAY_K_INPUT_ONLY.parquet',
        'dtp_raw_rejected': OLD / 'SUBSCRIPTION_US_DTP_RAW_DAY_K_INPUT_ONLY.parquet',
        'dte_receipt': OLD / 'SUBSCRIPTION_OFFICIAL_COMMON_ALIASES_RECEIPT.json',
        'dte_save_code': OLD / 'pilot_reused_quota_raw.py',
    }
    event_dir = ROOT / 'a2_strict_method_retrain_20260926/test2026_stage/r4_event_pit/raw_share_events'
    paths['bynd_split_original'] = event_dir / 'BYND_2026_08_nasdaq.html'
    paths['slmt_split_original'] = event_dir / 'SLMT_2026_05_12_nasdaq.html'
    original_hashes = {key: sha(path) for key, path in paths.items()}
    sources = [{'source_id': key, 'path': str(path), 'sha256': original_hashes[key],
                'kind': 'FROZEN_LOCAL_EVIDENCE_REUSED', 'modified': False} for key, path in paths.items()]
    official = json.loads((HERE / 'OFFICIAL_FETCH_RECEIPT.json').read_text(encoding='utf-8'))
    for item in official:
        assert item['raw_original_available'] and sha(item['local_path']) == item['sha256']
        sources.append(dict(item, kind='SEC_ORIGINAL_HTTP_BYTES'))
    source_by_id = {x['source_id']: x for x in sources}
    lineage = pd.read_csv(paths['lineage'], dtype=str).fillna('')
    gates = pd.read_csv(paths['saved_gates'], dtype=str).fillna('')
    r6 = pd.read_parquet(paths['r6_current']).set_index('ticker')
    members = pd.read_parquet(paths['members'], columns=['quarter', 'report_date', 'effective_date', 'expiry_date', 'cusip', 'issuer_name', 'title_of_class', 'ticker', 'moomoo_transport_code', 'mapping_source', 'mapping_confidence'])
    quarters = pd.read_parquet(paths['quarter_manifest'], columns=['quarter', 'latest_actual_filing_timestamp', 'filing_timestamp_granularity']).set_index('quarter')
    inventory = pd.read_csv(paths['uid_inventory'], dtype=str).fillna('')
    assert len(lineage) == 45 and lineage.ticker.is_unique
    members = members.loc[members.ticker.isin(lineage.ticker)].copy()
    assert not r6.multi_cusip_transport_interval_pending.any()

    # Cross-check original texts rather than trusting filenames or earlier summaries.
    assert '233331107' in source_text('dte_common_cusip_13g')
    assert 'Common Stock' in source_text('dte_common_cusip_13g')
    assert 'Corporate Units' in source_text('dte_corporate_units_prospectus')
    assert 'DTP' in source_text('dte_corporate_units_prospectus') and 'DTE' in source_text('dte_corporate_units_prospectus')
    assert 'G13311116' in source_text('slmt_old_cusip_class_6k') and 'Class B Ordinary Shares' in source_text('slmt_old_cusip_class_6k')
    assert '08862E109' in source_text('bynd_old_cusip_class_13g') and 'Common Stock' in source_text('bynd_old_cusip_class_13g')
    assert 'halted prior to the opening of trading' in source_text('exas_merger_8k')
    exas_public = acceptance('exas_merger_index')
    dte_public = max(acceptance('dte_common_cusip_index'), acceptance('dte_prospectus_index'))

    def refs(ids):
        return [{'source_id': s, 'sha256': source_by_id[s]['sha256'],
                 'path': source_by_id[s].get('path', source_by_id[s].get('local_path')),
                 'url': source_by_id[s].get('url')} for s in ids]

    bridges = [
        dict(ticker='DTP', from_cusip='233331107', from_share_class='COM', to_cusip='233331107',
             to_share_class='COMMON_STOCK', from_source_label='DTP', to_transport='US.DTE',
             state='VERIFIED', relation='SOURCE_LABEL_CORRECTION_NOT_MARKET_TICKER_ALIAS',
             public_at=dte_public, known_by=dte_public, effective_date=None,
             original_label_correction_recorded_at='2026-09-25T15:10:45.942959+00:00',
             allow_backfill_original_label_as_market_alias=False,
             allow_only_existing_r6_corrected_transport_rows=True,
             forbidden_transport='US.DTP', source_refs=refs(['dte_corporate_units_prospectus', 'dte_prospectus_index', 'dte_common_cusip_13g', 'dte_common_cusip_index', 'resolution75']),
             boundary='233331107 common may identify DTE. DTP Corporate Units is a different instrument. Existing corrected R6 intervals survive; unknown DTP-origin rows cannot be rewritten using issuer identity.'),
        dict(ticker='EXAS', from_cusip='30063P105', from_share_class='COMMON_STOCK', to_cusip=None,
             to_share_class='CASH_RECEIVABLE', from_source_label='EXAS', to_transport=None,
             state='VERIFIED', relation='COMMON_STOCK_CONVERTED_TO_CASH_RIGHT',
             public_at=exas_public, known_by=exas_public, effective_date='2026-03-23',
             tradability_end_exclusive='2026-03-23', cash_entitlement_usd_per_share=105.0,
             cash_settlement_date=None, historical_account_cash_receipt_state='UNKNOWN',
             source_refs=refs(['exas_merger_8k', 'exas_merger_index', 'resolution75']),
             boundary='No EXAS exchange fill from 2026-03-23. Ordinary non-excluded shares become a cash right; no automatic available cash, ABT-stock conversion or invented 9/23 price.'),
        dict(ticker='BYND', from_cusip='08862E109', from_share_class='COMMON_STOCK', to_cusip='08862E307',
             to_share_class='COMMON_STOCK', from_source_label='BYND', to_transport='US.BYND',
             state='VERIFIED', relation='SAME_SHARE_CLASS_REVERSE_SPLIT',
             old_cusip_public_at=acceptance('bynd_old_cusip_class_index'),
             public_at='2026-08-12', public_at_precision='DATE_ONLY', known_by='2026-08-14T00:00:00+00:00',
             effective_date='2026-08-14', old_share_count_per_new_share=30,
             source_refs=refs(['bynd_old_cusip_class_13g', 'bynd_old_cusip_class_index', 'bynd_split_original']),
             boundary='Connect only existing 08862E109 common account lots to 08862E307 common at the event. Official class continuity corroborates old R6 identity; event/vendor/coordinate gates are independent.'),
        dict(ticker='SLMT', from_cusip='G13311116', from_share_class='CLASS_B_ORDINARY_USD0.05', to_cusip='G13311132',
             to_share_class='CLASS_B_ORDINARY_USD0.50', from_source_label='SLMT', to_transport='US.SLMT',
             state='VERIFIED', relation='SAME_SHARE_CLASS_REVERSE_SPLIT',
             old_cusip_public_at=acceptance('slmt_old_cusip_class_index'), old_cusip_effective_date='2025-06-26',
             historical_ticker_at_old_cusip_issue='BREA', historical_brea_to_slmt_exact_effective_date=None,
             public_at='2026-05-12', public_at_precision='DATE_ONLY', known_by='2026-05-14T00:00:00+00:00',
             effective_date='2026-05-14', old_share_count_per_new_share=10,
             source_refs=refs(['slmt_old_cusip_class_6k', 'slmt_old_cusip_class_index', 'slmt_split_original']),
             boundary='Old generic Common Stock row is corroborated as Class B by exact G13311116. Never combine Class A. Do not assign G13311116 before 2025-06-26 or infer a BREA/SLMT rename date. Applies to existing 2026 R6 lots only.'),
    ]
    bridge_by_ticker = {b['ticker']: b for b in bridges}
    output = []
    interval_output = []
    for row in lineage.to_dict('records'):
        ticker = row['ticker']
        history = members.loc[members.ticker.eq(ticker)].sort_values('effective_date')
        last = history.iloc[-1]
        current = r6.loc[ticker] if ticker in r6.index else last
        cusip, share_class = str(current.cusip), str(current.title_of_class)
        assert cusip in row['historical_cusips'].split('|')
        baseline = gates.loc[gates.ticker.eq(ticker)].copy()
        verified = baseline.loc[baseline.final_input_gate.str.startswith('INPUT_VERIFIED')]
        # Empty UID does not negate an already-qualified baseline account identity.
        candidates = inventory.loc[inventory.ticker.eq(ticker), 'internal_security_uid'].tolist()
        exact_key = f'CUSIP:{cusip}|CLASS_AS_FILED:{share_class}'
        historical = []
        for h in records(history):
            q = quarters.loc[h['quarter']]
            h.update(canonical_security_uid=None,
                     membership_public_at=clean(q.latest_actual_filing_timestamp),
                     membership_public_at_precision=str(q.filing_timestamp_granularity),
                     mapping_public_at=None, mapping_known_by=None,
                     scope='OBSERVED_FROZEN_13F_MEMBERSHIP_ATTRIBUTES_NOT_GLOBAL_ALIAS_AUTHORITY',
                     expiry_is_lifecycle_end=False)
            historical.append(h)
        unknown = []
        if not row['in_current_saved_candidate_snapshot'] == 'True':
            unknown.append('CURRENT_CANDIDATE_ABSENCE_DOES_NOT_PROVE_SECURITY_ENDED')
        if candidates:
            unknown.append('PROSPECTIVE_UID_CANDIDATE_HAS_NO_EXACT_CUSIP_CLASS_BINDING_IN_INVENTORY')
        else:
            unknown.append('NO_EXACT_EXISTING_CANONICAL_UID_BINDING')
        unknown.append('HISTORICAL_VENDOR_IDENTITY_RECEIPT_TIME_NOT_NEWLY_PROVEN')
        transport = 'US.DTE' if ticker == 'DTP' else row['last_saved_transport_used']
        state = 'CONFLICT' if ticker == 'DTP' else 'VERIFIED'
        current_cusip = bridge_by_ticker.get(ticker, {}).get('to_cusip', cusip)
        current_class = bridge_by_ticker.get(ticker, {}).get('to_share_class', share_class)
        source_ids = ['lineage', 'saved_gates', 'r6_current', 'members', 'quarter_manifest']
        out = dict(ticker=ticker, state=state, state_scope='SOURCE_LABEL_CONFLICT' if ticker == 'DTP' else 'EXISTING_BASELINE_SECURITY_IDENTITY_PRESERVED',
                   stable_security_id=None, stable_security_id_state='UNKNOWN',
                   account_reconciliation_key=exact_key, account_key_is_canonical_uid=False,
                   canonical_uid_candidates=candidates, canonical_uid_candidate_binding_permitted=False,
                   original_cusip=cusip, original_share_class=share_class,
                   issuer_name=str(last.issuer_name), selected_transport=transport,
                   effective_cusip_at_review_end=current_cusip, effective_share_class_at_review_end=current_class,
                   baseline_identity_state='VERIFIED', baseline_verified_input_intervals=records(verified),
                   baseline_observed_gate_intervals=records(baseline), baseline_identity_reuse_allowed=True,
                   prior_input_verified_day_count=int(verified.candidate_days.astype(int).sum()),
                   identity_continuity_through=REVIEW_END, identity_continuity_scope='EXISTING_ACCOUNT_LOTS_ONLY_SUBJECT_TO_EXPLICIT_EVENT_BOUNDARIES',
                   historical_attribute_intervals=historical,
                   lifecycle_state='VERIFIED' if ticker == 'EXAS' else 'UNKNOWN',
                   lifecycle_status='CONVERTED_TO_CASH_RIGHT' if ticker == 'EXAS' else 'NO_NEW_LIFECYCLE_END_PROVEN',
                   public_at=bridge_by_ticker.get(ticker, {}).get('public_at'),
                   known_by=bridge_by_ticker.get(ticker, {}).get('known_by'),
                   effective_date=bridge_by_ticker.get(ticker, {}).get('effective_date'),
                   historical_vendor_known_by=None,
                   new_identity_bridge=bridge_by_ticker.get(ticker),
                   new_buy_eligibility_granted_by_this_evidence=False,
                   full_feature_price_event_eligibility_granted=False,
                   unresolved_reasons=unknown,
                   source_refs=refs(source_ids),
                   safe_consumer_boundary='Preserve prior qualified intervals; join same CUSIP plus class. Candidate expiry never closes held identity. New identity evidence cannot clear unrelated price, event-prefix, feature, quantity, or settlement gates.')
        if ticker == 'DTP':
            out['unresolved_reasons'].append('DTP_IS_NOT_A_HISTORICAL_MARKET_ALIAS_FOR_DTE_COMMON; UNKNOWN_SOURCE_LOT_OR_PRICE_ROWS_REQUIRE_CUSIP_CLASS_PROOF')
        if ticker == 'SLMT':
            out['unresolved_reasons'].append('EXACT_BREA_TO_SLMT_TICKER_CHANGE_DATE_NOT_QUALIFIED; NO_BACKFILL_BEFORE_EXISTING_R6_INTERVALS')
        if ticker == 'EXAS':
            out['unresolved_reasons'].append('CASH_RECEIVABLE_IS_NOT_CASH_RECEIVED; ACCOUNT_SETTLEMENT_DATE_UNKNOWN')
        output.append(out)
        for interval in records(baseline):
            filed = history.loc[history.quarter.eq(interval['quarter']) & history.cusip.eq(interval['cusip']), 'title_of_class']
            interval_class = str(filed.iloc[-1]) if len(filed) else share_class
            interval_output.append(dict(interval, share_class=interval_class, selected_transport=transport,
                                        stable_security_id=None, account_reconciliation_key=exact_key,
                                        share_class_scope='AS_FILED_IN_MATCHING_QUARTER' if len(filed) else 'CURRENT_R6_AS_FILED',
                                        identity_state='VERIFIED', source_hash=original_hashes['saved_gates'],
                                        prior_input_gate_preserved=True, new_qualification=False,
                                        expiry_is_lifecycle_end=False))

    raw_checks = []
    for key in ['dte_raw', 'dtp_raw_rejected']:
        frame = pd.read_parquet(paths[key], columns=['code', 'time_key'])
        dates = pd.to_datetime(frame.time_key).dt.strftime('%Y-%m-%d')
        raw_checks.append(dict(source_id=key, sha256=original_hashes[key], rows=len(frame),
                               codes=sorted(frame.code.unique().tolist()), first_date=dates.min(), last_date=dates.max(),
                               rows_2026_09_23=int(dates.eq('2026-09-23').sum()), rows_2026_09_24=int(dates.eq('2026-09-24').sum()),
                               reusable_for_common=key == 'dte_raw', values_read=False))
    dte_tail = dict(state='UNKNOWN', review_end=REVIEW_END, raw_files=raw_checks,
                    receipt_post_cutoff_count=3, saved_post_cutoff_rows=0,
                    save_code_fact='Only allowed=frame[trade_date<=2026-09-22] is written. Isolated count does not preserve raw bytes.',
                    no_price_api_calls=True, disk_wide_scan_performed=False,
                    safe_consumer_boundary='US.DTE raw ends 9/22; 9/23 and 9/24 execution/mark values absent in these audited files. Never use US.DTP Corporate Units. Existing saved common rows remain available within original gates.')

    write_json('identity_lifecycle_qualification.json', {
        'schema_version': 1, 'scope_tickers': lineage.ticker.tolist(), 'review_through': REVIEW_END,
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'state_scope_note': 'state verifies baseline identity or reports label conflict; lifecycle and full input qualification are separate. No baseline qualification revoked because canonical UID is unavailable.',
        'known_by_definition': 'Earliest proven public availability or conservative public-date upper bound, NOT a historical vendor receipt; effective_date is independent.',
        'securities': output, 'identity_bridges': bridges, 'dte_tail_check': dte_tail,
    })
    flat = []
    for obj in output:
        flat.append({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value for key, value in obj.items()})
    pd.DataFrame(flat).to_csv(HERE / 'identity_lifecycle_qualification.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(interval_output).to_csv(HERE / 'baseline_identity_intervals.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame([{k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in b.items()} for b in bridges]).to_csv(HERE / 'identity_bridges.csv', index=False, encoding='utf-8-sig')
    write_json('DTE_LOCAL_TAIL_CHECK.json', dte_tail)
    write_json('SOURCE_MANIFEST.json', sources)
    assert all(sha(path) == original_hashes[key] for key, path in paths.items())
    assert len(output) == 45 and len({x['ticker'] for x in output}) == 45
    assert len({x['account_reconciliation_key'] for x in output}) == 45
    by_ticker = {x['ticker']: x for x in output}
    assert by_ticker['GOOG']['account_reconciliation_key'] != by_ticker['GOOGL']['account_reconciliation_key']
    assert by_ticker['DTP']['selected_transport'] == 'US.DTE'
    assert by_ticker['EXAS']['new_identity_bridge']['cash_settlement_date'] is None
    assert not any(x['new_buy_eligibility_granted_by_this_evidence'] for x in output)
    verification = dict(status='PASS', tickers=45, baseline_identity_preserved=45,
                        baseline_input_intervals_preserved=len(interval_output),
                        prior_input_verified_days=sum(x['prior_input_verified_day_count'] for x in output),
                        new_official_http_originals=len(official), qualified_new_bridges=len(bridges),
                        label_conflicts=['DTP'], canonical_uids_minted=0,
                        canonical_uid_ticker_only_candidates=sum(bool(x['canonical_uid_candidates']) for x in output),
                        original_files_unchanged=True, original_source_count=len(paths),
                        model_calls=0, price_download_calls=0, raw_price_values_read=0,
                        output_hashes={name: sha(HERE / name) for name in ['identity_lifecycle_qualification.json', 'identity_lifecycle_qualification.csv', 'baseline_identity_intervals.csv', 'identity_bridges.csv', 'DTE_LOCAL_TAIL_CHECK.json', 'SOURCE_MANIFEST.json']})
    write_json('VERIFICATION.json', verification)
    print(json.dumps(verification, ensure_ascii=False))


if __name__ == '__main__':
    main()
