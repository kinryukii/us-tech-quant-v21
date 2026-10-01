from types import SimpleNamespace
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

SPEC = importlib.util.spec_from_file_location('historical_publication_under_test',
    Path(__file__).resolve().parents[4] / 'scripts/research/a2/inference/historical_top40.py')
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
publish_current_day = runner.publish_current_day


def context(tmp_path):
    paths = SimpleNamespace(daily_root=tmp_path)
    parent = tmp_path / 'parent.json'
    parent.write_text('{}')
    (tmp_path / 'rehab_receipt.json').write_text(json.dumps({
        'status': 'READY', 'source': 'MOOMOO_OPEND_GET_REHAB', 'target_date': '2026-09-22', 'results': []}), encoding='utf-8')
    manifest_path = tmp_path / 'manifest.json'
    manifest_path.write_text('{}')
    rows = [{'target_date': '2026-09-22', 'security_id': f'C{i}', 'ticker': f'T{i}',
             'score': 1 / i, 'rank': i, 'model_sha256': 'a' * 64, 'universe_id': 'pool',
             'source': 'VERIFIED_RAW_AND_EVENT_DATE_REPLAY'} for i in range(1, 42)]
    acquired = {'data_date': '2026-09-22', 'model_sha256': 'a' * 64, 'report_path': str(parent),
                'ranked_rows': rows[:30], 'universe': {'report_path': 'source-universe.json'}}
    manifest = {'end_date': '2026-09-22', 'run_id': 'full_history',
                'generated_at': '2026-09-23T10:00:00+00:00', 'report_path': str(manifest_path), 'outputs': {}}
    coverage = pd.DataFrame([{'target_date': '2026-09-22', 'eligible_count': 41,
        'mapped_count': 42, 'excluded_count': 2, 'status': 'PARTIAL', 'quarter': '2026Q2',
        'effective_date': '2026-09-10', 'universe_member_count': 43, 'institution_count': 25}])
    members = [{'snapshot_id': 's', 'security_id': row['security_id'], 'ticker': row['ticker']} for row in rows]
    members += [{'snapshot_id': 's', 'security_id': 'OTHER', 'ticker': 'MISSING'},
                {'snapshot_id': 's', 'security_id': 'UNKNOWN', 'ticker': None, 'mapping_status': 'UNPROVEN'}]
    pool = {'members': pd.DataFrame(members),
            'ledger': pd.DataFrame([{'target_date': '2026-09-22', 'snapshot_id': 's'}])}
    return paths, acquired, manifest, pd.DataFrame(rows), coverage, pool


def test_today_uses_same_batch_ranks_and_discloses_partial_coverage(tmp_path):
    args = context(tmp_path)
    result = publish_current_day(*args, [{'ticker': 'MISSING', 'reasons': ['NO_RAW']}])
    assert result['eligible_count'] == 41
    saved = json.loads((tmp_path / 'A2_today_recommendation/latest.json').read_text(encoding='utf-8'))
    assert saved['status'] == 'READY' and saved['coverage']['status'] == 'PARTIAL'
    assert [row['rank'] for row in saved['rows']] == list(range(1, 21))
    assert len(saved['ranked_rows']) == 41 and saved['universe']['quarter'] == '2026Q2'
    assert len(list((tmp_path / 'A2_today_recommendation/history').glob('*.json'))) == 1
    gaps = json.loads((tmp_path / 'A2_today_recommendation/runs/full_history_latest/excluded.json').read_text(encoding='utf-8'))
    assert gaps['identity_gaps'][0]['cusip'] == 'UNKNOWN'
    assert gaps['price_or_feature_gaps'] == [{'ticker': 'MISSING', 'reason': 'NO_RAW'}]


def test_changed_same_day_scores_fail_before_replacing_today(tmp_path):
    args = list(context(tmp_path))
    args[3].loc[0, 'score'] = 999
    with pytest.raises(ValueError, match='FEATURE_BEHAVIOR_DIFFER'):
        publish_current_day(*args, [])
    assert not (tmp_path / 'A2_today_recommendation/latest.json').exists()


def test_recomputing_an_earlier_end_date_does_not_replace_today(tmp_path):
    args = list(context(tmp_path))
    args[2]['end_date'] = '2025-12-31'
    assert publish_current_day(*args, [])['status'].startswith('SKIPPED')
    assert not (tmp_path / 'A2_today_recommendation/latest.json').exists()


def test_published_report_carries_identical_rehab_receipt_for_next_rebuild(tmp_path):
    args = context(tmp_path)
    result = publish_current_day(*args, [])
    directory = Path(result['report_path']).parent
    assert (directory / 'rehab_receipt.json').read_bytes() == (tmp_path / 'rehab_receipt.json').read_bytes()
    lineage = json.loads((directory / 'input_lineage.json').read_text(encoding='utf-8'))
    ref = lineage['rehab_receipt']
    assert ref['source']['sha256'] == ref['published']['sha256'] == runner.digest(directory / 'rehab_receipt.json')
    # The next default rebuild resolves exactly this sibling path.
    latest = json.loads((tmp_path / 'A2_today_recommendation/latest.json').read_text(encoding='utf-8'))
    assert json.loads((Path(latest['report_path']).parent / 'rehab_receipt.json').read_text(encoding='utf-8'))['target_date'] == latest['data_date']


@pytest.mark.parametrize('target,value', [('old', float('nan')), ('old', float('inf')),
                                        ('new', float('nan')), ('new', float('-inf'))])
def test_nonfinite_score_never_bypasses_equivalence_check(tmp_path, target, value):
    args = list(context(tmp_path))
    if target == 'old':
        args[1]['ranked_rows'][0]['score'] = value
    else:
        args[3].loc[0, 'score'] = value
    with pytest.raises(ValueError, match='NONFINITE_OR_DUPLICATE_SCORES'):
        publish_current_day(*args, [])
    assert not (tmp_path / 'A2_today_recommendation/latest.json').exists()


def test_overlap_and_removed_previous_tickers_are_explicit(tmp_path):
    args = list(context(tmp_path))
    args[1]['ranked_rows'] = args[1]['ranked_rows'] + [{'ticker': 'OLD_MISSING', 'score': 0.5}]
    result = publish_current_day(*args, [])
    lineage = json.loads((Path(result['report_path']).parent / 'input_lineage.json').read_text(encoding='utf-8'))
    check = lineage['same_day_prediction_equivalence']
    assert check['status'] == 'PARTIAL_OVERLAP_MATCH'
    assert check['compared_rows'] == 30 and check['previous_eligible_count'] == 31
    assert check['missing_previous_count'] == 1 and check['missing_previous_tickers'] == ['OLD_MISSING']
    assert check['newly_eligible_count'] == 11 and check['max_absolute_difference'] == 0


def test_no_overlap_is_not_reported_as_prediction_equivalence(tmp_path):
    args = list(context(tmp_path))
    args[1]['ranked_rows'] = [{'ticker': 'OTHER', 'score': 0.5}]
    result = publish_current_day(*args, [])
    lineage = json.loads((Path(result['report_path']).parent / 'input_lineage.json').read_text(encoding='utf-8'))
    check = lineage['same_day_prediction_equivalence']
    assert check['status'] == 'NO_OVERLAP_NOT_VERIFIED'
    assert check['compared_rows'] == 0 and check['max_absolute_difference'] is None


def test_missing_rehab_cannot_publish_an_unreproducible_latest(tmp_path):
    args = context(tmp_path)
    (tmp_path / 'rehab_receipt.json').unlink()
    with pytest.raises(FileNotFoundError):
        publish_current_day(*args, [])
    assert not (tmp_path / 'A2_today_recommendation/latest.json').exists()


def test_wrong_day_rehab_is_rejected(tmp_path):
    args = context(tmp_path)
    (tmp_path / 'rehab_receipt.json').write_text(json.dumps({
        'target_date': '2026-09-21', 'source': 'MOOMOO_OPEND_GET_REHAB', 'results': []}), encoding='utf-8')
    with pytest.raises(ValueError, match='REHAB_RECEIPT_IDENTITY_INVALID'):
        publish_current_day(*args, [])
    assert not (tmp_path / 'A2_today_recommendation/latest.json').exists()
