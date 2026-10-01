import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from apps.demo_console.adapters import stock_history_reader as reader
from apps.demo_console.components.stock_history_search import rank_chart
from apps.demo_console.components.stock_history_search import applied_stock_records, applied_stock_summary, applied_stock_chart


def fixture_history():
    return reader.prepare_history(
        pd.DataFrame([dict(target_date='2025-01-02', ticker='NEVER', security_id='123',
                          rank=55, score=.01, universe_id='u')]),
        pd.DataFrame([dict(target_date=day, snapshot_id='s', universe_id='u', quarter='2024Q3')
                      for day in ('2025-01-02', '2025-01-03')]),
        pd.DataFrame([dict(snapshot_id='s', ticker='NEVER', security_id='123',
                          issuer_name='Outside Top40', mapping_verified=True)]))


def test_chart_preserves_rank_beyond_40_and_missing_observations():
    result = reader.query_history(fixture_history(), 'NEVER')
    spec = rank_chart(result['daily']).to_dict(validate=True)
    assert spec['mark']['type'] == 'point'
    assert [r['rank'] for r in spec['data']['values']] == [55, None]
    assert spec['encoding']['y']['scale']['reverse'] is True


def test_ui_can_query_never_selected_stock(monkeypatch, artifact_dir):
    monkeypatch.setattr(reader, 'load_history', lambda model: fixture_history())
    script = artifact_dir / 'app.py'
    script.write_text('from apps.demo_console.components.stock_history_search import render_stock_history_search\n'
                      'from apps.demo_console.models import DecisionOverview\n'
                      'render_stock_history_search(DecisionOverview())\n', encoding='utf-8')
    try:
        app = AppTest.from_file(str(script)).run()
        assert not app.exception
        app.selectbox[0].set_value('NEVER').run()
        assert not app.exception
        assert [metric.value for metric in app.metric] == ['0', '0', '0', '0', '55', '—']
        # AppTest cannot serialize accept_new_options; verify that path in Chrome.
        assert reader.query_history(fixture_history(), 'UNKNOWN')['status'] == 'NOT_FOUND'
    finally:
        script.unlink()


APPLIED_IDS = ('RAW_A2', 'HGB_DIAG_5', 'HGB_FACTOR_5')
APPLIED_DATES = ('2026-01-05', '2026-01-06', '2026-01-07')


def fixture_applied_rankings(day='2026-01-07'):
    snapshot = {'status': 'READY', 'requested_date': day, 'actual_signal_date': day,
                'source_refs': {}, 'coverage': {'eligible_count': 3, 'mapped_count': 4, 'excluded_count': 1}, 'strategies': {}}
    for sid in APPLIED_IDS:
        hgb = sid != 'RAW_A2'
        rows = []
        for ticker, company, raw_rank, hgb_rank, diag_weight, factor_weight in (
                ('ALPHA', 'Alpha company', 1, 2, .7, .2),
                ('BETA', 'Beta company', 2, 1, .1, .8),
                ('NEVER', 'Outside Top40', 55, None, 0., 0.)):
            if hgb and hgb_rank is None:
                continue
            weight = (diag_weight if sid == 'HGB_DIAG_5' else factor_weight) if hgb else .05 if raw_rank <= 20 else 0.
            rows.append(dict(ticker=ticker, security_id=ticker + '-CUSIP', company=company,
                raw_rank=raw_rank, model_rank=hgb_rank if hgb else raw_rank,
                score=1 / (hgb_rank if hgb else raw_rank), eligible=raw_rank <= 20,
                selected=weight > 0, target_weight=weight,
                weight_date=day, target_kind='CURRENT_CASH_START_TARGET' if hgb else 'RAW_RULE_TARGET',
                status='SCORED', score_status='SCORED', target_status='READY'))
        snapshot['strategies'][sid] = dict(status='AVAILABLE', actual_signal_date=day,
            scope='RAW_TOP40' if hgb else 'FULL_VERIFIED_POOL', rank_kind='SHARED_HGB_MODEL_SCORE' if hgb else 'RAW_MODEL_SCORE',
            target_status='READY', target_kind='CURRENT_CASH_START_TARGET' if hgb else 'RAW_RULE_TARGET',
            weight_date=day, rows=rows)
    return snapshot


def fixture_applied_daily(ticker='NEVER'):
    daily = []
    for index, day in enumerate(APPLIED_DATES):
        leafs = {}
        for sid in APPLIED_IDS:
            hgb = sid != 'RAW_A2'
            gap = index == 1
            outside = ticker == 'NEVER'
            rank = None if gap or hgb and outside else 55 if outside else 2 if hgb else 1
            weight = None if gap else 0. if outside else .05 if not hgb else .2 if sid == 'HGB_DIAG_5' else .4
            leafs[sid] = dict(ticker=ticker, security_id=ticker + '-CUSIP',
                model_rank=rank, score=1/rank if rank else None, eligible=not outside,
                selected=None if gap else bool(weight), target_weight=weight,
                weight_date=None if gap else day, target_kind='HISTORICAL_SIGNAL_TARGET' if hgb else 'RAW_RULE_TARGET',
                score_status='NO_VERIFIED_SCORE' if rank is None else 'SCORED',
                target_status='NO_RECORDED_TARGET' if gap else 'READY', status='SCORED' if rank else 'NO_VERIFIED_SCORE')
        daily.append(dict(date=day, in_pool=True, pool_security_ids=[ticker + '-CUSIP'],
            security_id=ticker + '-CUSIP', status='RANKED' if index != 1 else 'NO_VERIFIED_RANK', strategies=leafs))
    return daily


def fixture_applied_history():
    return dict(status='READY', start_date=APPLIED_DATES[0], end_date=APPLIED_DATES[-1], source_refs={},
                catalog=[dict(ticker=ticker, issuer_name=company, security_ids=[ticker + '-CUSIP'])
                    for ticker, company in (('ALPHA', 'Alpha company'), ('BETA', 'Beta company'), ('NEVER', 'Outside Top40'))])


def fixture_applied_query(history, ticker, start_date=None, end_date=None, **kwargs):
    if ticker not in {'ALPHA', 'BETA', 'NEVER'}:
        return {'status': 'NOT_FOUND'}
    daily = [row for row in fixture_applied_daily(ticker)
             if (start_date or APPLIED_DATES[0]) <= row['date'] <= (end_date or APPLIED_DATES[-1])]
    return dict(status='READY', ticker=ticker, security_id=ticker + '-CUSIP', daily=daily)


def test_applied_stock_counts_use_known_target_dates_and_keep_rank_above40():
    daily = fixture_applied_daily()
    # Defensive boundary: an old target on a missing date cannot be carried.
    daily[1]['strategies']['HGB_DIAG_5'].update(weight_date=APPLIED_DATES[0], target_weight=.9, selected=True)
    records = applied_stock_records(daily)
    summary = applied_stock_summary(records)
    assert summary['RAW_A2'] == {'selected_days': 0, 'target_days': 2, 'ranked_days': 2, 'best_rank': 55.}
    assert summary['HGB_DIAG_5']['target_days'] == 2
    assert summary['HGB_DIAG_5']['selected_days'] == 0
    assert [row['target_weight'] for row in records if row['strategy_id'] == 'HGB_DIAG_5'] == [0., None, 0.]
    assert [row['rank'] for row in records if row['strategy_id'] == 'RAW_A2'] == [55., None, 55.]


def test_applied_stock_chart_keeps_missing_breaks_observed_domains_and_stable_colors():
    from apps.demo_console.components.performance_charts import STRATEGY_COLORS
    records = applied_stock_records(fixture_applied_daily('ALPHA'))
    for field, expected in (('rank', [1, 2.]), ('target_weight', [0, .4])):
        spec = applied_stock_chart(records, field).to_dict(validate=True)
        assert spec['encoding']['x']['scale'] == {'domain': [APPLIED_DATES[0], APPLIED_DATES[-1]], 'nice': False}
        assert spec['encoding']['y']['scale']['domain'] == expected
        assert spec['encoding']['y']['scale']['reverse'] is (field == 'rank')
        assert spec['encoding']['color']['scale']['range'] == list(STRATEGY_COLORS.values())
        assert spec['encoding']['detail']['field'] == field + '_segment'
        assert len(spec['data']['values']) == 9
        for sid in APPLIED_IDS:
            points = [row for row in spec['data']['values'] if row['strategy_id'] == sid]
            assert [row[field] for row in points][1] is None
            assert points[0][field + '_segment'] != points[-1][field + '_segment']


def test_applied_stock_chart_no_data_and_single_day_do_not_fabricate_records():
    empty = fixture_applied_daily()[1:2]
    assert applied_stock_chart(applied_stock_records(empty), 'rank') is None
    records = applied_stock_records(fixture_applied_daily('ALPHA')[:1])
    spec = applied_stock_chart(records, 'rank').to_dict(validate=True)
    assert {row['date'] for row in spec['data']['values']} == {APPLIED_DATES[0]}
    assert spec['encoding']['x']['scale']['domain'] == ['2026-01-04', '2026-01-06']


def _applied_workspace_app():
    import streamlit as st
    from apps.demo_console.models import DecisionOverview
    from apps.demo_console.components.top20_table import render_applied_rankings
    from apps.demo_console.components.stock_history_search import render_applied_stock_history
    from apps.demo_console.i18n import language_scope
    st.session_state.setdefault('decision_date', '2026-01-07')
    st.session_state.setdefault('workspace', 'Overview')
    st.session_state.setdefault('language', 'en')
    with language_scope(st.session_state['language']):
        render_applied_rankings(st.session_state['decision_date'], {}, DecisionOverview())
        if not st.checkbox('Hide stock search', key='hide_stock_search'):
            render_applied_stock_history(DecisionOverview(), {}, st.session_state['decision_date'])


@pytest.fixture
def applied_ui(monkeypatch):
    from apps.demo_console.adapters import workspace_reader
    monkeypatch.setattr(workspace_reader, 'load_applied_rankings', lambda day, **kw: fixture_applied_rankings(day))
    monkeypatch.setattr(workspace_reader, 'load_applied_stock_history', lambda **kw: fixture_applied_history())
    monkeypatch.setattr(workspace_reader, 'query_applied_stock_history', fixture_applied_query)
    app = AppTest.from_function(_applied_workspace_app).run()
    assert not app.exception and not app.error and not app.warning
    return app


def _ranking_click(app, index, row):
    import json
    from streamlit.proto.WidgetStates_pb2 import WidgetState
    states = app._tree.get_widget_states()
    widget_id = app.dataframe[index].proto.id
    payload = json.dumps({'selection': {'rows': [row], 'columns': [], 'cells': []}})
    found = next((widget for widget in states.widgets if widget.id == widget_id), None)
    if found is not None:
        found.string_value = payload
    else:
        states.widgets.append(WidgetState(id=widget_id, string_value=payload))
    return app._run(states)


def test_applied_native_selection_keeps_workspace_date_and_manual_focus(applied_ui):
    app = applied_ui
    assert list(app.dataframe[1].value.ticker) == ['BETA', 'ALPHA']
    assert list(app.dataframe[2].value.ticker) == ['BETA', 'ALPHA']
    assert list(app.dataframe[1].value.score) == list(app.dataframe[2].value.score)
    assert list(app.dataframe[1].value.target_weight) != list(app.dataframe[2].value.target_weight)
    _ranking_click(app, 0, 2)  # Outside Top40; native selection still queries it.
    assert not app.exception and not app.error
    assert app.selectbox(key='applied_stock_ticker').value == 'NEVER'
    assert app.session_state['workspace'] == 'Overview'
    assert app.session_state['decision_date'] == '2026-01-07'
    assert list(app.dataframe[3].value.selection_coverage) == ['0 / 2'] * 3
    app.selectbox(key='applied_stock_ticker').set_value('ALPHA').run()
    assert app.selectbox(key='applied_stock_ticker').value == 'ALPHA'
    app.checkbox(key='hide_stock_search').check().run()
    app.checkbox(key='hide_stock_search').uncheck().run()
    assert app.selectbox(key='applied_stock_ticker').value == 'ALPHA'
    assert not app.exception and not app.error and not app.warning


def test_applied_common_filters_orders_and_missing_date_clear_stale_tables(applied_ui, monkeypatch):
    app = applied_ui
    assert any('3 / 4 mapped securities' in caption.value for caption in app.caption)
    app.selectbox(key='applied_rank_order').set_value('Portfolio weight').run()
    assert list(app.dataframe[1].value.ticker) == ['ALPHA', 'BETA']
    assert list(app.dataframe[2].value.ticker) == ['BETA', 'ALPHA']
    app.text_input(key='applied_rank_query').set_value('Outside Top40').run()
    assert list(app.dataframe[0].value.ticker) == ['NEVER']
    assert len(app.dataframe) == 1
    app.toggle(key='applied_rank_selected').set_value(True).run()
    assert len(app.dataframe) == 0
    app.toggle(key='applied_rank_selected').set_value(False).run()
    app.text_input(key='applied_rank_query').set_value('').run()
    from apps.demo_console.adapters import workspace_reader
    snapshot = fixture_applied_rankings()
    for sid in APPLIED_IDS[1:]:
        snapshot['strategies'][sid].update(status='UNAVAILABLE', actual_signal_date=None, rows=[])
    monkeypatch.setattr(workspace_reader, 'load_applied_rankings', lambda *a, **kw: snapshot)
    app.run()
    assert len(app.dataframe) == 1
    assert not app.exception and not app.error


def test_applied_stock_private_dates_clip_to_asof_and_unknown_ticker_is_explicit(applied_ui, caplog, monkeypatch):
    from datetime import date
    from streamlit.elements.lib import policies
    monkeypatch.setattr(policies, '_shown_default_value_warning', False)
    app = applied_ui
    app.selectbox(key='applied_stock_ticker').set_value('ALPHA').run()
    app.session_state['decision_date'] = '2026-01-06'
    app.run()
    assert app.date_input(key='applied_stock_dates').value == (date(2026, 1, 5), date(2026, 1, 6))
    assert app.selectbox(key='applied_stock_snapshot_date').value == '2026-01-06'
    app.session_state['decision_date'] = '2026-01-07'
    app.run()
    app.date_input(key='applied_stock_dates').set_value((date(2026, 1, 6), date(2026, 1, 7))).run()
    assert app.session_state['decision_date'] == '2026-01-07'
    assert list(app.dataframe[3].value.selection_coverage) == ['1 / 1'] * 3
    app.session_state['decision_date'] = '2026-01-06'
    app.run()
    assert app.date_input(key='applied_stock_dates').value == (date(2026, 1, 6), date(2026, 1, 6))
    assert list(app.dataframe[3].value.selection_coverage) == ['—'] * 3
    assert len(app.get('vega_lite_chart')) == 0
    assert not app.warning
    # AppTest's selectbox.index cannot serialize accept_new_options. Exercise
    # the real browser string payload and native SelectboxSerde instead.
    from streamlit.proto.WidgetStates_pb2 import WidgetState
    states = app._tree.get_widget_states()
    widget_id = app.selectbox(key='applied_stock_ticker').proto.id
    found = next((widget for widget in states.widgets if widget.id == widget_id), None)
    if found is None:
        states.widgets.append(WidgetState(id=widget_id, string_value='UNKNOWN'))
    else:
        found.string_value = 'UNKNOWN'
    app._run(states)
    assert not app.exception and not app.error and not app.warning
    assert len(app.dataframe) == 3  # Rankings remain; the old stock tables disappear.
    assert any('no verified record' in message.value for message in app.info)
    assert not any('was created with a default value' in record.message for record in caplog.records)


def test_applied_stock_search_remains_visible_without_verified_source(applied_ui, monkeypatch):
    from apps.demo_console.adapters import workspace_reader
    app = applied_ui
    app.selectbox(key='applied_stock_ticker').set_value('ALPHA').run()
    monkeypatch.setattr(workspace_reader, 'load_applied_stock_history',
        lambda **kwargs: {'status': 'UNAVAILABLE', 'catalog': []})
    app.run()
    assert not app.exception and not app.error and not app.warning
    assert app.selectbox(key='applied_stock_ticker').value == 'ALPHA'
    assert len(app.dataframe) == 3
    assert len(app.get('vega_lite_chart')) == 0
    assert any('history is unavailable' in message.value for message in app.info)


def test_applied_identity_price_and_13f_sources_follow_private_range_without_changing_main_date(applied_ui, monkeypatch, caplog):
    from apps.demo_console.adapters import workspace_reader, stock_identity_display, raw_stock_price_reader
    from apps.demo_console.components import stock_quote_chart, selection_price_path
    from streamlit.elements.lib import policies
    monkeypatch.setattr(policies, '_shown_default_value_warning', False)
    reference = {'path': 'verified-raw-manifest.json', 'sha256': 'synthetic'}
    history = fixture_applied_history()
    history['source_refs'] = {'a2': reference}
    chain = dict(status='VERIFIED', old_security_id='OLD', new_security_id='NEW', event_date='2026-01-06')
    calls = {'queries': [], 'quotes': [], 'holders': []}
    def query(bound, ticker, start, end, **kwargs):
        calls['queries'].append(kwargs)
        if kwargs.get('identity_mode') != 'VERIFIED_COMPANY' and not kwargs.get('security_id'):
            return {'status': 'AMBIGUOUS_IDENTITY', 'identities': ['OLD', 'NEW']}
        result = fixture_applied_query(bound, ticker, start, end)
        result['security_id'] = None
        for day in result['daily']:
            identity = 'OLD' if day['date'] < chain['event_date'] else 'NEW'
            day['security_id'] = identity
            for row in day['strategies'].values():
                row['security_id'] = identity
        return result
    def prices(ref, ticker, start, end, **kwargs):
        calls['quotes'].append((ref, ticker, start, end, kwargs))
        return {'status': 'READY'}
    monkeypatch.setattr(workspace_reader, 'load_applied_stock_history', lambda **kw: history)
    monkeypatch.setattr(workspace_reader, 'query_applied_stock_history', query)
    monkeypatch.setattr(stock_identity_display, 'read_identity_chain', lambda ref, ticker: chain)
    monkeypatch.setattr(raw_stock_price_reader, 'read_raw_stock_prices', prices)
    monkeypatch.setattr(stock_quote_chart, 'render_quote_history', lambda result, **kw: None)
    monkeypatch.setattr(selection_price_path, 'render_stock_holders',
        lambda model, ticker, **kw: calls['holders'].append((model.decision_date, ticker, kw)))
    app = applied_ui
    app.selectbox(key='applied_stock_ticker').set_value('ALPHA').run()
    assert app.segmented_control(key='applied_stock_history_mode').value == 'COMPANY'
    app.checkbox(key='applied_stock_history_details').check().run()
    assert not app.exception and not app.error
    assert calls['queries'][-1] == {'identity_mode': 'VERIFIED_COMPANY', 'identity_chain': chain}
    assert calls['quotes'][-1][:4] == (reference, 'ALPHA', '2026-01-05', '2026-01-07')
    assert calls['quotes'][-1][4] == {'security_id': None, 'identity_chain': chain}
    assert calls['holders'][-1] == ('2026-01-07', 'ALPHA', {'security_id': 'NEW', 'key_prefix': 'applied_stock_history'})
    app.session_state['decision_date'] = '2026-01-05'
    app.run()
    assert not app.exception and not app.error and not app.warning
    assert app.selectbox(key='applied_stock_history_13f_date').value == '2026-01-05'
    assert calls['quotes'][-1][3] == '2026-01-05'
    assert calls['holders'][-1][2]['security_id'] == 'OLD'
    assert app.session_state['workspace'] == 'Overview'
    assert app.session_state['decision_date'] == '2026-01-05'
    assert not any('was created with a default value' in record.message for record in caplog.records)


@pytest.mark.parametrize('language', ('en', 'zh', 'ja'))
def test_applied_labels_translate_without_altering_focus_or_economic_fields(applied_ui, language):
    from apps.demo_console.i18n import language_scope, tr
    from apps.demo_console.pages.selected_strategies import WORKSPACE_STRATEGIES
    app = applied_ui
    app.session_state['language'] = language
    app.selectbox(key='applied_stock_ticker').set_value('ALPHA').run()
    assert not app.exception and not app.error
    with language_scope(language):
        labels = [tr(WORKSPACE_STRATEGIES[sid]) for sid in APPLIED_IDS]
        assert list(app.dataframe[3].value.strategy) == labels
        assert list(app.dataframe[5].value.strategy)[:3] == labels
        assert app.selectbox(key='applied_rank_order').options == [tr('Score ranking'), tr('Portfolio weight')]
    assert app.session_state['applied_stock_ticker'] == 'ALPHA'
    assert list(app.dataframe[4].value['weight']) == [.05, .2, .4]
    assert app.session_state['decision_date'] == '2026-01-07'
