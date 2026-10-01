"""RX reads use synthetic books and cannot replace or borrow another A2 run."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from test_updated_research_reader import bundle as a2_bundle, tmp_path, ref, save
from apps.demo_console.adapters import rx_research_reader as reader
from apps.demo_console.adapters import updated_research_reader as a2_reader


@pytest.fixture
def rx_bundle(a2_bundle, monkeypatch):
    a2ref = a2_bundle.publish()
    model = a2_reader.load_overview(reference=a2ref)
    work = a2_bundle.work.parents[2] / 'A2_updated_research_rx' / 'runs' / 'synthetic_rx'
    work.mkdir(parents=True)
    tables = deepcopy(a2_bundle.tables)
    tables['selections'] = [{**row, 'raw_rank': row['rank'], 'raw_score': row['score'],
        'candidate_score': row['score'], 'candidate_id': reader.POLICY}
        for row in tables.pop('rankings') if row['rank'] <= 20]
    for name in ('portfolio_daily', 'positions'):
        for row in tables[name]: row['model'] = reader.MODEL
    tables['decisions'] = [{'signal_date': '2026-09-22', 'scheduled_execution_date': '2026-09-23',
        'incumbent_ticker': 'T20', 'entrant_ticker': 'T21', 'score_margin': .1, 'required_margin': .2,
        'replacement_decision': 'RETAIN'}]
    tables['trades'] = [{'date': '2026-09-21', 'model': reader.MODEL, 'ticker': 'T01',
        'side': 'BUY', 'shares': .9995/20, 'execution_price': 1., 'notional': .9995/20}]
    tables['price_paths'] = [{'date': day, 'ticker': 'T01', 'open': 1.+index/100,
        'close': 1.005+index/100, 'adjustment': reader.PRICE_BASIS,
        'source': 'VERIFIED_RAW_PLUS_PIT_REHAB'} for index, day in enumerate(['2026-09-18','2026-09-21','2026-09-22'])]
    tables['corporate_action_events'] = [{'date': '2026-09-21', 'ticker': 'T01', 'event_type': 'SPLIT'}]
    frozen = work / 'synthetic_frozen.json'
    save(frozen, {'synthetic': 'no real authority or economic data'})
    monkeypatch.setattr(reader, 'AUTHORITY_SHA', ref(frozen)['sha256'])
    selection = {'policy_id': reader.POLICY, 'frozen_contract': ref(frozen),
        'warmup_sessions': 60, 'predictive_model_fit_count': 0, 'threshold_search_count': 0}
    manifest = {'schema_version': 1, 'source_id': reader.SOURCE_ID, 'status': 'READY',
        'run_id': work.name, 'report_path': str(work/'manifest.json'), 'parent_a2_manifest': a2ref,
        'evaluation': {**a2_reader.EVALUATION, 'selection': reader.POLICY},
        'ranking_end_date': '2026-09-22', 'performance_end_date': '2026-09-22'}

    def publish():
        outputs = {}
        for name, rows in tables.items():
            path = work / (name+'.parquet')
            pq.write_table(pa.Table.from_pylist(rows), path)
            outputs[name] = ref(path)
        manifest['outputs'] = outputs
        save(work/'selection_contract.json', selection)
        manifest['selection_contract'] = ref(work/'selection_contract.json')
        save(work/'evaluation_contract.json', {'source_id': reader.SOURCE_ID,
            'evaluation': manifest['evaluation'], 'parent_a2_manifest': manifest['parent_a2_manifest'],
            'selection_contract': manifest['selection_contract']})
        manifest['evaluation_contract'] = ref(work/'evaluation_contract.json')
        save(work/'manifest.json', manifest)
        save(work.parents[1]/'latest.json', manifest)
        reader.clear_cache()
        return ref(work/'manifest.json')
    return SimpleNamespace(publish=publish, model=model, tables=tables, manifest=manifest,
        selection=selection, work=work, a2ref=a2ref, a2=a2_bundle)


def test_rx_is_separate_pending_selection_and_same_sample_performance(rx_bundle):
    ref0 = rx_bundle.publish()
    before = rx_bundle.model
    view = reader.read(before, reference=ref0)
    assert not view.error, view.debug_error
    assert len(view.selections) == 20 and not view.holdings
    assert view.calendar['execution_status'] == 'PENDING_NEXT_OPEN'
    assert len(view.decisions) == 1 and view.history.model_identity == 'A2_RX'
    assert view.history.effective_end_date == '2026-09-22'
    assert rx_bundle.model == before and before.source_id == 'A2_UPDATED_RESEARCH'
    earlier = replace(before, decision_date='2026-09-18', performance_cutoff_date='2026-09-21')
    executed = reader.read(earlier, reference=ref0)
    assert len(executed.holdings) == 20 and executed.history.effective_end_date == '2026-09-21'
    scoped = reader.read(replace(before, sample_start_date='2026-09-21', sample_end_date='2026-09-22'), reference=ref0)
    assert len(scoped.history.points) == 2 and scoped.history.baseline_date == '2026-09-18'


@pytest.mark.parametrize('mutation', ['parent', 'fit', 'warmup', 'threshold', 'cost', 'cash',
    'missing_selection', 'foreign_name', 'future_execution', 'bad_margin'])
def test_corrupt_rx_or_different_a2_cannot_be_attached(rx_bundle, mutation):
    if mutation == 'parent': rx_bundle.manifest['parent_a2_manifest'] = {**rx_bundle.a2ref, 'sha256':'a'*64}
    elif mutation == 'fit': rx_bundle.selection['predictive_model_fit_count'] = 1
    elif mutation == 'warmup': rx_bundle.selection['warmup_sessions'] = 59
    elif mutation == 'threshold': rx_bundle.selection['threshold_search_count'] = 1
    elif mutation == 'cost': rx_bundle.manifest['evaluation']['cost_bps_round_trip'] = 20
    elif mutation == 'cash': rx_bundle.tables['portfolio_daily'][-1]['cash_after'] = .3
    elif mutation == 'missing_selection': rx_bundle.tables['selections'].pop()
    elif mutation == 'foreign_name': rx_bundle.tables['selections'][0]['ticker'] = 'NOT_IN_PARENT'
    elif mutation == 'future_execution': rx_bundle.tables['decision_calendar'][-1]['execution_date'] = '2026-09-23'
    else: rx_bundle.tables['decisions'][0]['replacement_decision'] = 'REPLACE'
    view = reader.read(rx_bundle.model, reference=rx_bundle.publish())
    assert view.error and not view.history.points and not view.holdings


def test_output_drift_and_parent_generation_refresh_fail_closed(rx_bundle):
    reference = rx_bundle.publish()
    assert not reader.read(rx_bundle.model, reference=reference).error
    with (rx_bundle.work/'portfolio_daily.parquet').open('ab') as out: out.write(b'changed')
    broken = reader.read(rx_bundle.model, reference=reference)
    assert broken.error and 'HASH_MISMATCH' in broken.debug_error
    reference = rx_bundle.publish()
    newer = replace(rx_bundle.model, source_manifest_sha256='f'*64)
    assert reader.read(newer, reference=reference).error


def test_price_display_keeps_verified_basis_and_real_trades(rx_bundle):
    view = reader.read(rx_bundle.model, reference=rx_bundle.publish())
    evidence = reader.price_evidence(view, rx_bundle.model)
    assert evidence['adjustment'] == 'PIT_FORWARD_REHAB_INDEX'
    assert evidence['calendar_dates'] == ('2026-09-18','2026-09-21','2026-09-22')
    assert len(evidence['trades']) == 1 and evidence['trades'][0]['date'] == '2026-09-21'
    assert not any(row['date'] == '2026-09-23' for row in evidence['prices'])
    rx_bundle.tables['price_paths'][0]['adjustment'] = 'raw'
    view = reader.read(rx_bundle.model, reference=rx_bundle.publish())
    with pytest.raises(ValueError, match='PRICE_IDENTITY'):
        reader.price_evidence(view, rx_bundle.model)


def test_missing_rx_is_local_and_does_not_read_an_unbound_workspace():
    from apps.demo_console.models import DecisionOverview
    view = reader.read(DecisionOverview(source_id='A2_UPDATED_RESEARCH'))
    assert view.error and not view.history.points


def test_a2_price_projection_and_trades_do_not_require_or_read_rx(rx_bundle, monkeypatch):
    a2 = rx_bundle.a2
    a2.tables['price_paths'] = deepcopy(rx_bundle.tables['price_paths'])
    a2.tables['trades'] = [{**row, 'model':'A2_HGB'} for row in rx_bundle.tables['trades']]
    a2.tables['corporate_action_events'] = deepcopy(rx_bundle.tables['corporate_action_events'])
    model = a2_reader.load_overview(reference=a2.publish())
    def forbidden(*args, **kwargs):
        raise AssertionError('A2 price/stock details must not read the RX bundle')
    monkeypatch.setattr(reader, 'bundle', forbidden)
    evidence = reader.price_evidence(reader.RXView(error='SYNTHETIC_RX_UNAVAILABLE'), model, strategy='A2_HGB')
    assert len(evidence['prices']) == 3 and len(evidence['trades']) == 1
    assert evidence['trades'][0]['model'] == 'A2_HGB'
    assert len(reader.selection_tickers(replace(model, ranking=()))) == 20
    with (a2.work/'price_paths.parquet').open('ab') as stream: stream.write(b'tampered')
    with pytest.raises(ValueError, match='HASH_MISMATCH'):
        reader.price_evidence(reader.RXView(error='RX_MISSING'), model, strategy='A2_HGB')


def test_a2_without_price_projection_still_supplies_verified_names_and_book(rx_bundle):
    a2 = rx_bundle.a2
    a2.tables['trades'] = [{**row,'model':'A2_HGB'} for row in rx_bundle.tables['trades']]
    model = a2_reader.load_overview(reference=a2.publish())
    evidence = reader.price_evidence(reader.RXView(error='RX_MISSING'),model,strategy='A2_HGB')
    assert evidence['prices'] == () and len(evidence['signals']) == 60
    assert len(evidence['positions']) == 40
    assert reader.selection_tickers(model) == tuple(f'T{i:02}' for i in range(1,21))
