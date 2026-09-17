"""One frozen issuer-date correction; reuse unchanged coverage/return modules.

Only the CLI reads real inputs. Original archive, bindings, failed-run files and
frozen modules remain untouched. No model, real factor or numeric label output.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd

REVISION_ID = 'TAC_COMMON_DIVIDEND_20210528_R1'
ISSUER_URL = 'https://www.sec.gov/Archives/edgar/data/1144800/000114480022000006/tac2021integratedreportf.htm'
RESULT = Path('D:/us-tech-quant-results/A2_ECONOMIC_RETURN_DATA_PREFLIGHT_20260913/issuer_date_revision')
CACHE = Path('D:/us-tech-quant-cache/a2_economic_return_data_preflight_20260913/issuer_date_revision')
RULE = {'code': 'US.TAC', 'ticker': 'TAC', 'vendor_ex_div_date': '2021-05-31',
        'issuer_ex_div_date': '2021-05-28', 'expected_per_cash_div': .03723,
        'official_source_url': ISSUER_URL}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def json_safe(value):
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime, Path)):
        return str(value)
    if isinstance(value, np.generic):
        value = value.item()
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return None
    return value


def verify(pins):
    for path, digest in pins.items():
        if sha(path) != digest:
            raise RuntimeError(f'ISSUER_REVISION_PIN_CHANGED:{path}')


def setup(revision_path):
    revision = json.loads(Path(revision_path).read_text(encoding='utf-8'))
    if (revision.get('status') != 'FROZEN_ISSUER_DATE_REVISION'
            or revision.get('phase') != 'COVERAGE_ONLY' or revision.get('revision_id') != REVISION_ID
            or revision.get('correction') != RULE
            or revision.get('wrapper_source_sha256') != sha(__file__)
            or Path(revision['output']['results_dir']).resolve() != RESULT.resolve()
            or Path(revision['output']['cache_dir']).resolve() != CACHE.resolve()):
        raise RuntimeError('ISSUER_REVISION_NOT_FROZEN_OR_SCOPE_CHANGED')
    counts = revision.get('campaign_counts_at_revision_freeze', {})
    if (counts.get('predictive_fits') != 12
            or not isinstance(counts.get('completed_candidate_comparisons'), int)
            or isinstance(counts.get('completed_candidate_comparisons'), bool)
            or counts['completed_candidate_comparisons'] < 3):
        raise RuntimeError('CAMPAIGN_COUNT_SNAPSHOT_REQUIRED')
    pins = {str(Path(revision_path).resolve()): sha(revision_path),
            str(Path(__file__).resolve()): revision['wrapper_source_sha256']}
    for name in ('original_data_contract', 'original_preflight_source', 'original_bindings',
                 'original_failure', 'original_failure_log', 'evidence_review', 'event_audit'):
        item = revision[name]
        pins[str(Path(item['path']).resolve())] = item['sha256']
    pins.update(revision.get('additional_pins', {}))
    verify(pins)
    original = json.loads(Path(revision['original_data_contract']['path']).read_text(encoding='utf-8'))
    if (original['runner_source_sha256'] != revision['original_preflight_source']['sha256']
            or original['bindings_sha256'] != revision['original_bindings']['sha256']
            or pd.Timestamp(revision['frozen_utc']) < pd.Timestamp(original['frozen_utc'])):
        raise RuntimeError('ORIGINAL_FROZEN_CONTRACT_IDENTITY_CHANGED')
    audit = json.loads(Path(revision['event_audit']['path']).read_text(encoding='utf-8'))
    records = audit['records']
    if (len(records) != 1 or records[0]['code'] != RULE['code']
            or records[0]['ex_div_date'] != RULE['vendor_ex_div_date']
            or audit['assessment']['official_common_event_date_supported'] != RULE['issuer_ex_div_date']):
        raise RuntimeError('ISSUER_DATE_EVIDENCE_CONTRACT_MISMATCH')
    source = Path(revision['original_preflight_source']['path'])
    spec = importlib.util.spec_from_file_location('issuer_revision_frozen_preflight', source)
    stage = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = stage
    spec.loader.exec_module(stage)
    contract, old_pins, modules = stage.frozen_setup(
        Path(revision['original_data_contract']['path']), Path(revision['original_bindings']['path']))
    pins.update(old_pins)
    return revision, contract, pins, stage, modules


def revise_event_metadata(events, calendar, revision):
    """Change exactly one event date; preserve indexes and every other cell."""
    if revision['correction'] != RULE:
        raise RuntimeError('ONLY_FIXED_ISSUER_DATE_CORRECTION_ALLOWED')
    original = events.copy(deep=True)
    old_date, new_date = pd.Timestamp(RULE['vendor_ex_div_date']), pd.Timestamp(RULE['issuer_ex_div_date'])
    match = events.code.eq(RULE['code']) & events.ex_div_date.eq(old_date)
    if int(match.sum()) != 1:
        raise RuntimeError('ISSUER_REVISION_REQUIRES_EXACTLY_ONE_ORIGINAL_EVENT')
    if new_date not in calendar:
        raise RuntimeError('OFFICIAL_DATE_NOT_CANONICAL_SESSION')
    if (events.code.eq(RULE['code']) & events.ex_div_date.eq(new_date)).any():
        raise RuntimeError('ISSUER_REVISION_EVENT_COLLISION')
    if float(events.loc[match, 'per_cash_div'].iloc[0]) != RULE['expected_per_cash_div']:
        raise RuntimeError('ISSUER_REVISION_ORIGINAL_CASH_CHANGED')
    derived = events.copy(deep=True)
    derived['vendor_ex_div_date'] = original.ex_div_date.copy()
    derived['issuer_date_source_url'] = ''
    derived['issuer_date_evidence_report_sha256'] = ''
    derived['issuer_date_revision_id'] = ''
    derived.loc[match, 'ex_div_date'] = new_date
    derived.loc[match, 'issuer_date_source_url'] = RULE['official_source_url']
    derived.loc[match, 'issuer_date_evidence_report_sha256'] = revision['evidence_review']['sha256']
    derived.loc[match, 'issuer_date_revision_id'] = REVISION_ID
    restored = derived[original.columns].copy()
    restored.loc[match, 'ex_div_date'] = old_date
    pd.testing.assert_frame_equal(restored, original, check_exact=True)
    assert len(derived) == len(original) and derived.index.equals(original.index)
    correction = {'revision_id': REVISION_ID, 'changed_original_cells': 1, 'changed_original_field': 'ex_div_date',
        'original_event': json_safe(original.loc[match].iloc[0].to_dict()),
        'derived_event': json_safe(derived.loc[match].iloc[0].to_dict()),
        'official_source_url': RULE['official_source_url'],
        'evidence_report_sha256': revision['evidence_review']['sha256'],
        'cash_or_share_fields_changed': False, 'cash_unit_certified': False,
        'economic_identity_certified': False, 'historical_date_capture_certified': False}
    return derived, correction


def derived_stage_bindings(bindings, revision, revision_sha):
    copied = copy.deepcopy(bindings)
    lineage = {'original_archive': bindings['rehab'], 'revision_contract_sha256': revision_sha,
               'rule': RULE, 'issuer_date_evidence': revision['evidence_review'],
               'event_metadata_audit': revision['event_audit']}
    digest = hashlib.sha256(json.dumps(lineage, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    copied['rehab'] = {'path': 'DERIVED_ISSUER_DATE_REVISION[' + bindings['rehab']['path'] +
        ' | ' + RULE['official_source_url'] + ' | evidence_sha256=' + revision['evidence_review']['sha256'] +
        ' | revision_contract_sha256=' + revision_sha + ']', 'sha256': digest}
    return copied, lineage


def features_with_revision_provenance(features, original_bindings):
    """Only metadata provenance changes; all classifier/math calls are inherited."""
    def classify(frame):
        prepared = frame.copy()
        changed = prepared.vendor_ex_div_date.ne(prepared.ex_div_date)
        exact = (prepared.code.eq(RULE['code']) & prepared.ticker.eq(RULE['ticker'])
                 & prepared.vendor_ex_div_date.eq(pd.Timestamp(RULE['vendor_ex_div_date']))
                 & prepared.ex_div_date.eq(pd.Timestamp(RULE['issuer_ex_div_date'])))
        if int(changed.sum()) != 1 or not changed.equals(exact):
            raise RuntimeError('UNEXPECTED_DERIVED_EVENT_DATE_CHANGE')
        prepared.loc[changed, 'source_type'] = 'DERIVED_VENDOR_ARCHIVE_WITH_ISSUER_DATE_CORRECTION'
        prepared.loc[~changed, 'source_reference'] = original_bindings['rehab']['path']
        prepared.loc[~changed, 'source_fingerprint'] = original_bindings['rehab']['sha256']
        return features.classify_vendor_events(prepared)
    return SimpleNamespace(ACTION_FIELDS=features.ACTION_FIELDS, classify_vendor_events=classify,
                           build_accrual_returns=features.build_accrual_returns)


def run(revision_path):
    destinations = [RESULT / name for name in ('coverage_summary.json', 'coverage_lineage.json', 'issuer_date_correction.json')]
    mask_path = CACHE / 'coverage_masks.parquet'
    if any(path.exists() for path in [*destinations, mask_path]):
        raise RuntimeError('ISSUER_REVISION_OUTPUT_EXISTS_NO_OVERWRITE')
    revision, contract, pins, stage, modules = setup(revision_path)
    original_contract = Path(revision['original_data_contract']['path'])
    binding_path = Path(revision['original_bindings']['path'])
    # Crucially: original reader receives ORIGINAL contract/bindings unchanged.
    raw, events, panel, calendar, raw_lineage = modules['inputs'].load_economic_return_inputs(
        contract_path=original_contract, bindings_path=binding_path)
    bindings = json.loads(binding_path.read_text(encoding='utf-8'))
    derived, correction = revise_event_metadata(events, calendar, revision)
    stage_bindings, derivation = derived_stage_bindings(bindings, revision, sha(revision_path))
    proxy = features_with_revision_provenance(modules['features'], bindings)
    query = pd.read_csv(contract['rehab_status']['path'], keep_default_na=False, dtype={'code': str, 'status': str})
    masks, summary = stage.stage_coverage(raw, derived, panel, calendar, stage_bindings, query,
                                          contract, proxy, modules['targets'])
    if summary['strict_valid_label_rows'] != 0 or masks.strict_target_valid.any():
        raise RuntimeError('DATE_REVISION_CANNOT_CERTIFY_ECONOMIC_IDENTITY')
    inherited_counts = {key: summary.pop(key) for key in ('campaign_predictive_fits', 'campaign_candidate_comparisons')}
    summary.update(revision_id=REVISION_ID, derived_data_role='ONE_ISSUER_DATE_CORRECTION_CONDITIONAL_COVERAGE',
        original_stage_campaign_snapshot=inherited_counts,
        campaign_counts_at_revision_freeze=revision['campaign_counts_at_revision_freeze'],
        campaign_predictive_fits=revision['campaign_counts_at_revision_freeze']['predictive_fits'],
        campaign_candidate_comparisons=revision['campaign_counts_at_revision_freeze']['completed_candidate_comparisons'],
        original_failed_preflight_preserved=True, corrected_event_rows=1, cash_unit_qualification='UNKNOWN',
        revision_contract_sha256=sha(revision_path), provider_changed=False,
        completed_utc=datetime.now(timezone.utc).isoformat())
    pins.update(raw_lineage['source_and_input_hashes'])
    verify(pins)
    lineage = {'raw_input_lineage': raw_lineage, 'revision_contract': revision, 'revision_pins': pins,
               'derivation': derivation, 'derived_event_columns': list(derived.columns),
               'original_event_row_count': len(events), 'derived_event_row_count': len(derived),
               'source_hashes_match_after_processing': True, 'original_archive_mutated': False,
               'original_bindings_mutated': False, 'raw_price_or_daily_return_bodies_persisted': False}
    RESULT.mkdir(parents=True, exist_ok=True); CACHE.mkdir(parents=True, exist_ok=True)
    masks.to_parquet(mask_path, index=False)
    summary['coverage_masks_sha256'] = sha(mask_path)
    for path, value in zip(destinations, (summary, lineage, correction)):
        path.write_text(json.dumps(json_safe(value), indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({key: summary[key] for key in ('status', 'transport_valid_label_rows', 'strict_valid_label_rows', 'fits_added')}))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--revision-contract', type=Path, required=True)
    run(parser.parse_args().revision_contract)
