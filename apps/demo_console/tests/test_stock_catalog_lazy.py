"""Directory-only metadata over synthetic immutable sources; full query unchanged."""
from copy import deepcopy
from types import SimpleNamespace
import hashlib
import json
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from streamlit.testing.v1 import AppTest
from apps.demo_console.adapters import stock_history_reader as reader, workspace_reader as workspace


def _ref(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    from apps.demo_console.tests.test_stock_history_reader import applied_fixture
    raw, package = applied_fixture()
    old = raw['_members'].assign(snapshot_id='old')
    old = pd.concat([old, pd.DataFrame([dict(snapshot_id='old', ticker='EXITED', security_id='old-id',
        issuer_name='Historical exited company', mapping_verified=True)])], ignore_index=True)
    raw['_members'] = pd.concat([old, raw['_members']], ignore_index=True)
    raw['_ledger'].loc[raw['_ledger'].target_date.eq('2026-01-02'), 'snapshot_id'] = 'old'
    refs = {}
    for key in ('ranked', 'ledger', 'members'):
        path = tmp_path / (key + '.parquet')
        pq.write_table(pa.Table.from_pandas(raw['_' + key], preserve_index=False), path)
        refs[key] = _ref(path)
    hist = tmp_path / 'history.json'
    hist.write_text(json.dumps({'outputs': {'ranked': refs['ranked']},
        'universe_outputs': {key: refs[key] for key in ('ledger', 'members')}}))
    tail = tmp_path / 'tail.parquet'
    rows = raw['_ranked'].loc[raw['_ranked'].target_date.eq('2026-09-24') & raw['_ranked']['rank'].le(40)].copy()
    rows['target_date'] = '2026-09-25'
    pq.write_table(pa.Table.from_pandas(rows, preserve_index=False), tail)
    reports = []
    for day, ticker in (('2026-09-26', 'NEW'), ('2026-09-27', 'FUTURE')):
        folder = tmp_path / day; folder.mkdir()
        member = folder / 'mapped_members.parquet'
        pq.write_table(pa.table({'ticker': [ticker], 'security_id': [ticker + '-ID']}), member)
        report = folder / 'report.json'
        payload = {'data_date': day, 'status': 'READY', 'model_id': 'A2_HGB', 'model_sha256': reader.base.MODEL_2026_SHA,
            'universe': {'universe_id': day, 'quarter': '2026Q3', 'report_path': str(folder / 'universe.json'),
                         'universe_members_sha256': _ref(member)['sha256']},
            'coverage': {'mapped_count': 1, 'eligible_count': 1, 'excluded_count': 0},
            'ranked_rows': [{'ticker': ticker, 'security_id': ticker + '-ID', 'rank': 1, 'score': .2, 'universe_id': day}]}
        report.write_text(json.dumps(payload));reports.append(_ref(report))
    parent = tmp_path / 'parent.json'
    parent.write_text(json.dumps({'ranking_manifest': _ref(hist), 'outputs': {'rankings': _ref(tail)},
                                 'recommendation_reports': reports}))
    model = SimpleNamespace(error=None, decision_date='2026-09-26')
    monkeypatch.setattr(workspace, 'is_updated', lambda value: True)
    monkeypatch.setattr(workspace, 'source_reference', lambda value: _ref(parent))
    reader._cached_history.cache_clear();reader._cached_applied_history.cache_clear()
    return SimpleNamespace(package=package, model=model, refs=refs, reports=reports)


@pytest.mark.parametrize('as_of', ['2026-01-02', '2026-09-24', '2026-09-25', '2026-09-26'])
def test_catalog_matches_full_asof_retains_exited_names_and_tail_pools(evidence, as_of):
    args = dict(package=evidence.package, raw_model=evidence.model, as_of=as_of)
    catalog = reader.load_applied_catalog(**args)
    full = reader.load_applied_history(**args)
    assert catalog['status'] == 'CATALOG_READY', catalog
    assert full['status'] == 'READY', full
    assert catalog['catalog'] == full['catalog']
    assert (catalog['start_date'], catalog['end_date']) == (full['start_date'], full['end_date'])
    assert any(row['ticker'] == 'EXITED' and row['issuer_name'] == 'Historical exited company' for row in catalog['catalog'])
    assert not any(row['ticker'] == 'FUTURE' for row in catalog['catalog'])
    assert ('NEW' in {row['ticker'] for row in catalog['catalog']}) is (as_of >= '2026-09-26')
    assert reader.bind_catalog_history(catalog, full)['status'] == 'READY'


def test_catalog_never_decodes_ranking_values_or_calls_full_hgb_main(evidence, monkeypatch):
    original = reader._frame
    seen = []
    def frame(ref, parent, columns):
        assert not {'rank', 'score', 'pred_hgb', 'nav'}.intersection(columns)
        seen.append(tuple(columns))
        return original(ref, parent, columns)
    monkeypatch.setattr(reader, '_frame', frame)
    monkeypatch.setattr(reader, 'load_history', lambda *a, **k: pytest.fail('full raw history'))
    monkeypatch.setattr(reader, 'prepare_applied_history', lambda *a, **k: pytest.fail('full HGB history'))
    from apps.demo_console.adapters import selected_strategies_reader as selected
    monkeypatch.setattr(selected, 'score_history', lambda *a, **k: pytest.fail('HGB score rows'))
    result = reader.load_applied_catalog(package=evidence.package, raw_model=evidence.model, as_of='2026-09-26')
    assert result['status'] == 'CATALOG_READY' and seen
    assert not any(key.startswith('_rank') or key in ('_scores', '_targets', 'raw_history') for key in result)
    path = evidence.refs['members']['path']
    with open(path, 'ab') as handle: handle.write(b'changed')
    assert reader.bind_catalog_history(result, {'status': 'READY', 'catalog': result['catalog'], 'as_of': result['as_of']})['status'] == 'UNAVAILABLE'
    assert reader.load_applied_catalog(package=evidence.package, raw_model=evidence.model, as_of='2026-09-26')['status'] == 'UNAVAILABLE'


def _page():
    import streamlit as st
    from apps.demo_console.components.stock_history_search import render_applied_stock_history
    from apps.demo_console.models import DecisionOverview
    from apps.demo_console.i18n import language_scope
    from apps.demo_console.adapters import workspace_reader
    language = st.selectbox('Language', ('en', 'zh', 'ja'), key='test_language')
    history = workspace_reader.load_active_stock_catalog(package={}, raw_model=DecisionOverview(), as_of='2026-01-07', account_state={'capture': 'SYNTHETIC'}) if st.session_state.get('active') else None
    with language_scope(language):
        render_applied_stock_history(DecisionOverview(), {}, '2026-01-07', history=history)


@pytest.mark.parametrize('active', [False, True])
def test_blank_stock_search_full_loader_zero_then_selected_one_and_focus_language_dates(monkeypatch, active):
    from apps.demo_console.tests.test_stock_history_search import fixture_applied_history, fixture_applied_query
    from apps.demo_console.components import stock_history_search
    from apps.demo_console.tests.test_hidden_detail_lazy import _language
    calls = []
    catalog = {**fixture_applied_history(), 'status': 'CATALOG_READY', 'as_of': '2026-01-07', '_catalog_only': True}
    monkeypatch.setattr(workspace, 'load_applied_stock_catalog', lambda **k: deepcopy(catalog))
    def full(**kwargs):
        calls.append(kwargs)
        return {**fixture_applied_history(), 'as_of': '2026-01-07'}
    monkeypatch.setattr(workspace, 'load_applied_stock_history', full)
    def active_full(**kwargs):
        result = full(**kwargs)
        return {**result, '_active_account_state': kwargs['account_state']}
    monkeypatch.setattr(workspace, 'load_active_stock_history', active_full)
    monkeypatch.setattr(workspace, 'query_applied_stock_history', fixture_applied_query)
    monkeypatch.setattr(workspace, 'query_active_stock_history', fixture_applied_query)
    monkeypatch.setattr(stock_history_search, 'render_chart', lambda *a, **k: None)
    app = AppTest.from_function(_page);app.session_state['active'] = active;app.run()
    assert not app.exception and not calls
    app.selectbox(key='applied_stock_ticker').set_value('ALPHA').run()
    assert not app.exception and len(calls) == 1
    if active: assert calls[0]['account_state'] == {'capture': 'SYNTHETIC'}
    interval = app.session_state['applied_stock_dates']
    _language(app, 'zh')
    assert not app.exception and len(calls) == 2
    assert app.session_state['applied_stock_ticker'] == 'ALPHA' and app.session_state['applied_stock_dates'] == interval
    _language(app, 'ja')
    assert not app.exception and len(calls) == 3
    assert app.session_state['applied_stock_ticker'] == 'ALPHA'
