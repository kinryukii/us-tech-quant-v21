"""Synthetic updated-workspace bundles; no financial dataset or network reads."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import shutil
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append('D:/us-tech-quant')
import apps.demo_console
import apps.demo_console.adapters
for package, folder in ((apps.demo_console, ''), (apps.demo_console.adapters, 'adapters')):
    package.__path__.insert(0, str(ROOT / 'apps/demo_console' / folder))
from apps.demo_console.adapters import updated_research_reader as reader
from apps.demo_console.adapters import workspace_reader as workspace


def ref(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def save(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')


@pytest.fixture
def tmp_path():
    # Ordinary directories avoid Python 3.14's Windows owner-only temp ACL.
    base = (ROOT / 'updated-reader-synthetic').resolve()
    path = base / uuid4().hex
    path.mkdir(parents=True)
    yield path
    if path.resolve().parent == base:
        shutil.rmtree(path)


@pytest.fixture
def bundle(tmp_path):
    root = tmp_path / 'A2_updated_research'
    work = root / 'runs' / 'synthetic_test'
    work.mkdir(parents=True)
    days = ['2026-09-18', '2026-09-21', '2026-09-22']
    outputs = {}
    tables = {}
    tables['rankings'] = [{'target_date': day, 'ticker': f'T{rank:02}', 'security_id': str(rank),
        'rank': rank, 'score': 1 / rank, 'model_year': 2026, 'model_sha256': reader.MODEL_2026_SHA,
        'universe_id': 'synthetic_pool', 'universe_quarter': '2026Q2',
        'universe_effective_date': '2026-09-10', 'institution_count': 25}
        for day in days for rank in range(1, 41)]
    tables['portfolio_daily'] = []
    navs = [1., .9995, .9995 * 1.01]
    for i, day in enumerate(days):
        row = {key: 0. for key in reader.DAILY_COLUMNS}
        row.update(execution_date=day, model='A2_HGB', reconstruction_mode='POSITION_LEDGER',
            cash_before=1. if i <= 1 else 0., cash_after=1. if i == 0 else 0.,
            pretrade_nav=1. if i <= 1 else navs[i], reconstructed_nav=navs[i],
            reconstructed_gross_return=.01 if i == 2 else 0.,
            reconstructed_daily_return=navs[i] / (navs[i-1] if i else 1.) - 1,
            target_turnover=.5 if i == 1 else 0., reconstructed_turnover=.5 if i == 1 else 0.,
            reconstructed_transaction_cost=.0005 if i == 1 else 0.,
            position_value=navs[i] if i else 0., actual_risky_name_count=20 if i else 0,
            buy_cash_scale=1.)
        tables['portfolio_daily'].append(row)
    tables['positions'] = [{'date': day, 'previous_date': days[i-1], 'ticker': f'T{rank:02}',
        'shares_before': 0. if i == 1 else .9995/20, 'shares_after': .9995/20,
        'model': 'A2_HGB', 'portfolio': 'TOP20_EQUAL_WEIGHT_LONG_ONLY',
        'posttrade_weight': .05, 'target_weight': .05, 'position_weight': 0. if i == 1 else .05}
        for i, day in enumerate(days) if i for rank in range(1, 21)]
    tables['decision_calendar'] = [{'signal_date': day, 'scheduled_execution_date': days[i+1] if i < 2 else '2026-09-23',
        'execution_date': days[i+1] if i < 2 else None,
        'portfolio_snapshot_date': days[i+1] if i < 2 else None,
        'performance_cutoff_date': days[i+1] if i < 2 else days[-1],
        'execution_status': 'EXECUTED' if i < 2 else 'PENDING_NEXT_OPEN',
        'quarter': '2026Q2', 'effective_date': '2026-09-10', 'institution_count': 25,
        'universe_member_count': 45, 'mapped_count': 42, 'eligible_count': 40,
        'excluded_count': 5, 'coverage_status': 'PARTIAL'} for i, day in enumerate(days)]
    lineage = work / 'ranking_lineage.json'
    save(lineage, {'models': {'feature_columns': ['momentum'], 'artifacts': {'2026': {
        'sha256': reader.MODEL_2026_SHA, 'train_end': '2025-11-28', 'labelmax': '2025-12-30',
        'training_row_count': 123}}}})
    manifest = {'schema_version': 1, 'source_id': reader.SOURCE_ID, 'status': 'PARTIAL',
        'run_id': work.name, 'generated_at': '2026-09-23T00:00:00Z',
        'ranking_end_date': days[-1], 'performance_end_date': days[-1],
        'report_path': str(work / 'manifest.json'), 'ranking_manifest': ref(lineage),
        'evaluation': deepcopy(reader.EVALUATION), 'outputs': outputs}

    def publish():
        for name, rows in tables.items():
            path = work / (name + '.parquet')
            pq.write_table(pa.Table.from_pylist(rows), path)
            outputs[name] = ref(path)
        contract = work / 'evaluation_contract.json'
        save(contract, {'source_id': reader.SOURCE_ID, 'evaluation': manifest['evaluation'],
                        'rankings': outputs['rankings']})
        manifest['evaluation_contract'] = ref(contract)
        save(work / 'manifest.json', manifest)
        save(root / 'latest.json', manifest)
        reader.clear_cache()
        return reader.binding(SimpleNamespace(daily_root=tmp_path))

    return SimpleNamespace(tables=tables, manifest=manifest, work=work, publish=publish)


def test_executed_and_pending_keep_distinct_dates_weights_and_cutoffs(bundle):
    reference = bundle.publish()
    first = reader.load_overview('2026-09-18', reference=reference)
    assert first.provenance.execution_date == '2026-09-21'
    assert len(first.ranking) == 40 and len(first.holdings) == 20
    assert first.holdings[0].weight == .05 and first.previous_holdings == ()
    old = reader.read_performance(first.performance_cutoff_date, reference=reference)
    assert len(old.points) == 2 and old.effective_end_date == '2026-09-21'
    latest = reader.load_overview(reference=reference)
    assert latest.provenance.execution_date is None and latest.holdings == ()
    assert latest.previous_holdings == tuple(f'T{rank:02}' for rank in range(1, 21))
    assert all(row.held_before is (row.rank <= 20) for row in latest.ranking)
    assert latest.retained is latest.entered is latest.exited is None
    assert latest.performance_cutoff_date == '2026-09-22'
    assert latest.scheduled_execution_date == '2026-09-23'
    assert latest.coverage.excluded_count == 5 and latest.learning.vintages[0].prediction_count == 120
    history = reader.read_performance(latest.performance_cutoff_date, reference=reference)
    assert len(history.points) == 3 and not history.reference_available


@pytest.mark.parametrize('field,value', [('top_n', 40), ('cost_bps_round_trip', 20),
    ('terminal_liquidation', True), ('initial_nav', 2), ('signal_execution', 'same close')])
def test_changed_rules_are_rejected(bundle, field, value):
    bundle.manifest['evaluation'][field] = value
    with pytest.raises(ValueError, match='EVALUATION_CONTRACT_CHANGED'):
        reader.load_overview(reference=bundle.publish())


@pytest.mark.parametrize('mutation', ['missing_rank', 'wrong_model', 'future_cutoff', 'pending_has_execution',
    'executed_missing_day', 'wrong_position_weight', 'wrong_cash', 'unknown_execution'])
def test_broken_rank_execution_or_accounting_cannot_render(bundle, mutation):
    if mutation == 'missing_rank': bundle.tables['rankings'].pop()
    elif mutation == 'wrong_model': bundle.tables['rankings'][0]['model_sha256'] = 'a'*64
    elif mutation == 'future_cutoff': bundle.tables['decision_calendar'][0]['performance_cutoff_date'] = '2026-09-22'
    elif mutation == 'pending_has_execution': bundle.tables['decision_calendar'][-1]['execution_date'] = '2026-09-23'
    elif mutation == 'executed_missing_day': bundle.tables['decision_calendar'][0]['execution_date'] = None
    elif mutation == 'wrong_position_weight': bundle.tables['positions'][0]['posttrade_weight'] = .9
    elif mutation == 'wrong_cash': bundle.tables['portfolio_daily'][-1]['cash_before'] = .1
    else: bundle.tables['decision_calendar'][-1]['execution_status'] = 'UNKNOWN'
    with pytest.raises(ValueError): reader.load_overview(reference=bundle.publish())


def test_cached_output_tampering_is_detected(bundle):
    reference = bundle.publish()
    reader.load_overview(reference=reference)
    with (bundle.work / 'rankings.parquet').open('ab') as stream: stream.write(b'changed')
    with pytest.raises(ValueError, match='HASH_MISMATCH'):
        reader.load_overview(reference=reference)


def test_old_reference_stays_bound_and_new_pointer_refreshes(bundle):
    reference = bundle.publish()
    reader.load_overview(reference=reference)
    bundle.manifest['generated_at'] = '2026-09-23T01:00:00Z'
    revised = bundle.publish()
    assert reference['sha256'] != revised['sha256']
    with pytest.raises(ValueError, match='MANIFEST_HASH_MISMATCH'):
        reader.load_overview(reference=reference)
    assert reader.load_overview(reference=revised).source_manifest_sha256 == revised['sha256']


@pytest.mark.parametrize('mutation', ['blocked', 'earlier_cutoff'])
def test_pending_only_recovers_same_day_verified_opening_book(bundle, mutation):
    row = bundle.tables['decision_calendar'][-1]
    if mutation == 'blocked': row['execution_status'] = 'BLOCKED_PRICE_INPUT'
    else: row['performance_cutoff_date'] = '2026-09-21'
    result = reader.load_overview(reference=bundle.publish())
    assert result.previous_holdings is None and all(row.held_before is None for row in result.ranking)
    assert result.holdings == () and result.provenance.execution_date is None


def test_pending_before_uses_existing_posttrade_book_not_unexecuted_signal(bundle):
    for row in bundle.tables['positions']:
        if row['date'] == '2026-09-22': row['shares_before'] = 0.
    result = reader.load_overview(reference=bundle.publish())
    assert len(result.previous_holdings) == 20
    assert result.holdings == () and result.turnover is None
    assert result.execution_status == 'PENDING_NEXT_OPEN'


def model_evidence(bundle):
    path = bundle.work / 'ranking_lineage.json'
    ranking = json.loads(path.read_text())
    freeze = bundle.work / 'freeze.json'
    alpha = {'feature_schema': ['momentum'], 'source_fingerprint': 'a' * 64,
        'prereg_fingerprint': 'b' * 64, 'supplemental_full_pre2026_model': {'sha256': reader.MODEL_2026_SHA},
        'hyperparameters': {'max_depth': 3, 'early_stopping': False, 'learning_rate': .05},
        'target': 'recorded synthetic target'}
    save(freeze, {'contracts': {'A2': alpha}})
    lineage = {'freeze_path': str(freeze), 'freeze_sha256': ref(freeze)['sha256'],
        'feature_source_sha256': alpha['source_fingerprint'], 'model_params_source_sha256': alpha['prereg_fingerprint']}
    ranking['models']['lineage'] = lineage
    ranking['models']['artifacts']['2026']['lineage'] = deepcopy(lineage)
    save(path, ranking)
    bundle.manifest['ranking_manifest'] = ref(path)
    return path, ranking, freeze


def test_learning_metadata_uses_bound_fixed_spec_without_substituting_model(bundle):
    model_evidence(bundle)
    result = reader.load_overview(reference=bundle.publish())
    assert dict(result.learning.parameters) == {'early_stopping': 'false', 'learning_rate': '0.05', 'max_depth': '3'}
    assert result.learning.source_fingerprint == 'a' * 64
    assert result.learning.target == 'recorded synthetic target'
    assert result.learning.vintages[0].fingerprint == reader.MODEL_2026_SHA


def test_unrecorded_fixed_spec_stays_unknown(bundle):
    result = reader.load_overview(reference=bundle.publish())
    assert result.learning.parameters == () and result.learning.source_fingerprint is None


def test_learning_cache_detects_changed_fixed_parameter_evidence(bundle):
    _, _, freeze = model_evidence(bundle)
    reference = bundle.publish()
    reader.load_overview(reference=reference)
    freeze.write_text('{}')
    with pytest.raises(ValueError, match='METADATA_HASH_MISMATCH'):
        reader.load_overview(reference=reference)


def test_parameters_from_another_model_lineage_are_rejected(bundle):
    path, ranking, _ = model_evidence(bundle)
    ranking['models']['artifacts']['2026']['lineage']['freeze_sha256'] = 'c' * 64
    save(path, ranking)
    bundle.manifest['ranking_manifest'] = ref(path)
    with pytest.raises(ValueError, match='PARAMETER_LINEAGE_MISMATCH'):
        reader.load_overview(reference=bundle.publish())


def test_latest_completed_book_is_separate_and_keeps_exact_reference(bundle, monkeypatch):
    from dataclasses import replace
    reference = bundle.publish()
    selected = reader.load_overview(reference=reference)
    monkeypatch.setattr(reader, 'binding', lambda *args: pytest.fail('must not switch source pointer'))
    result = workspace.latest_executed_overview(selected)
    assert result.decision_date == '2026-09-21' and result.provenance.execution_date == '2026-09-22'
    assert len(result.holdings) == 20 and result.execution_status == 'EXECUTED'
    assert result.source_id == selected.source_id
    assert workspace.source_reference(result) == workspace.source_reference(selected)
    assert selected.decision_date == '2026-09-22' and selected.holdings == ()
    earlier = workspace.latest_executed_overview(replace(selected, performance_cutoff_date='2026-09-21'))
    assert earlier.decision_date == '2026-09-18'
    prior_signal = workspace.latest_executed_overview(replace(selected, decision_date='2026-09-18'))
    assert prior_signal.decision_date == '2026-09-18'
    assert workspace.latest_executed_overview(replace(selected, performance_cutoff_date='2026-09-18')) is None
    assert workspace.latest_executed_overview(replace(selected, source_manifest_sha256='0' * 64)) is None
    assert workspace.latest_executed_overview(replace(selected, source_id='frozen')) is None


def test_sample_performance_never_crosses_the_2026_boundary(monkeypatch):
    from apps.demo_console.models import DecisionOverview, PerformanceHistory, PerformancePoint
    from dataclasses import replace
    dates = ('2025-12-30', '2025-12-31', '2026-01-02', '2026-01-05')
    points = tuple(PerformancePoint(day, 1., .01, .01, 0., 0., 0., 1., 20, 0, 0, 0, 1.) for day in dates)
    history = PerformanceHistory(points=points, available_dates=dates, archive_start=dates[0], archive_end=dates[-1])
    calls = []
    def read(cutoff, **kwargs):
        calls.append(cutoff)
        return replace(history, points=tuple(p for p in points if p.execution_date <= cutoff))
    monkeypatch.setattr(reader, 'read_performance', read)
    model = DecisionOverview(decision_date='2025-12-31', available_dates=dates, source_id=workspace.LATEST,
        source_manifest_path='synthetic.json', source_manifest_sha256='a'*64, performance_cutoff_date='2026-01-02')
    historical = workspace.scope_overview(model, 'historical')
    result = workspace.read_performance(historical)
    assert calls[-1] == '2025-12-31'
    assert historical.available_dates == dates[:2]
    assert result.points == points[:2] and result.available_dates == dates[:2]
    assert result.archive_end == result.effective_end_date == '2025-12-31'
    test = workspace.scope_overview(replace(model, decision_date='2026-01-02', performance_cutoff_date='2026-01-05'), 'test_2026')
    result = workspace.read_performance(test)
    assert test.available_dates == dates[2:]
    assert result.points == points[2:] and result.available_dates == dates[2:]
    assert result.archive_start == '2026-01-02'
    assert result.baseline_date == '2025-12-31'
    assert history.points == points and model.performance_cutoff_date == '2026-01-02'
