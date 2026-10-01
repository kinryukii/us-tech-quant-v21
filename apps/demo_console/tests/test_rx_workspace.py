"""Four independent curves share the existing sample and period controls."""
from datetime import date

import pytest


def _page():
    from dataclasses import replace
    from unittest.mock import patch
    import pandas as pd
    import streamlit as st
    from apps.demo_console.adapters import workspace_reader, rx_research_reader
    from apps.demo_console.adapters.benchmarks_reader import BenchmarkHistory, BenchmarkSeries, BenchmarkPoint
    from apps.demo_console.models import DecisionOverview, PerformanceHistory, PerformancePoint
    from apps.demo_console.i18n import language_scope
    from apps.demo_console.pages import research
    year = st.session_state.get('fixture_year', 2026)
    dates = tuple(pd.bdate_range(f'{year}-01-02', f'{year}-05-29').strftime('%Y-%m-%d'))
    def history(rx=False):
        points, nav = [], 1.
        for i, day in enumerate(dates):
            ret = (.004 if rx else .002) if i % 3 else -.003
            nav *= 1+ret
            points.append(PerformancePoint(day,nav,ret,ret,0.,0.,0.,nav,20,0,0,0,1.))
        return PerformanceHistory(points=tuple(points),available_dates=dates,archive_start=dates[0],
            archive_end=dates[-1],effective_end_date=dates[-1],model_identity='A2_RX' if rx else 'A2_HGB')
    raw, rx = history(), history(True)
    if st.session_state.get('rx_missing'):
        rxview = rx_research_reader.RXView(error='Synthetic RX unavailable')
    else:
        if st.session_state.get('rx_partial'): rx = replace(rx,points=rx.points[:-4],effective_end_date=dates[-5])
        rxview = rx_research_reader.RXView(history=rx)
    def markets(days, baseline_date=None):
        st.session_state['etf_dates'] = days
        return BenchmarkHistory(series=tuple(BenchmarkSeries(symbol,symbol,adjustment='raw',
            basis='OPEN_TO_OPEN_PRICE_RETURN',points=tuple(BenchmarkPoint(day,100.,.001,1.001**(i+1),0.) for i,day in enumerate(days)),
            total_return=1.001**len(days)-1,max_drawdown=0.) for symbol in ('QQQ','SPY')),baseline_date=baseline_date)
    model = DecisionOverview(decision_date=dates[-1],source_id=workspace_reader.LATEST,
        performance_cutoff_date=dates[-1],sample_start_date=f'{year}-01-01',sample_end_date=f'{year}-12-31')
    with language_scope('en'), patch.object(workspace_reader,'read_performance',return_value=raw), \
         patch.object(rx_research_reader,'read',return_value=rxview), \
         patch.object(research,'read_updated_benchmarks',side_effect=markets), \
         patch.object(research,'_historical_comparisons'):
        research.render_research(model,presentation=True)


def _wealth(app):
    from apps.demo_console.tests.test_research_view import _charts
    return _charts(app)['wealth'][1]


def _check_four(app, year):
    assert not app.exception and not app.error
    rows = _wealth(app)
    assert tuple(row['execution_date'] for row in rows) == tuple(app.session_state['etf_dates'])
    assert all(row['execution_date'].startswith(str(year)) for row in rows)
    assert all({'net_wealth','rx_net_wealth','benchmark_qqq','benchmark_spy'} <= row.keys() for row in rows)
    table = next(item.value for item in app.dataframe if 'series' in item.value.columns)
    assert set(table.series) == {'Raw A2','A2 + RX','QQQ','SPY · S&P 500'}
    assert len(set(table.observations)) == 1


@pytest.mark.parametrize('year',[2025,2026])
def test_all_four_curves_share_month_quarter_and_custom_controls(year):
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(_page,default_timeout=30)
    app.session_state['fixture_year'] = year
    app.run(); _check_four(app,year)
    app.selectbox(key='research_range').select('Calendar month').run()
    app.selectbox(key='research_calendar_month').select(f'{year}-03').run()
    _check_four(app,year)
    assert all(row['execution_date'].startswith(f'{year}-03') for row in _wealth(app))
    app.selectbox(key='research_range').select('Calendar quarter').run()
    app.selectbox(key='research_calendar_quarter').select(f'{year}-Q1').run()
    _check_four(app,year)
    assert max(row['execution_date'] for row in _wealth(app)) <= f'{year}-03-31'
    app.selectbox(key='research_range').select('Custom dates').run()
    app.date_input(key='research_dates_draft').set_value((date(year,2,3),date(year,3,17)))
    app.button(key='research_dates_apply').click().run()
    _check_four(app,year)
    assert min(row['execution_date'] for row in _wealth(app)) >= f'{year}-02-03'
    assert max(row['execution_date'] for row in _wealth(app)) <= f'{year}-03-17'


@pytest.mark.parametrize('state',['rx_missing','rx_partial'])
def test_unavailable_rx_never_shortens_or_replaces_a2_or_etfs(state):
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(_page,default_timeout=30).run()
    raw = tuple((row['execution_date'],row['net_wealth']) for row in _wealth(app))
    app.session_state[state] = True
    app.run()
    assert not app.exception and not app.error
    rows = _wealth(app)
    assert tuple((row['execution_date'],row['net_wealth']) for row in rows) == raw
    assert all('benchmark_qqq' in row and 'benchmark_spy' in row and 'rx_net_wealth' not in row for row in rows)
    assert any('RX' in item.value for item in [*app.caption,*app.info])


def _portfolio_page():
    from unittest.mock import patch
    from types import SimpleNamespace
    from apps.demo_console.components.rx_portfolio import render_rx_portfolio
    from apps.demo_console.components import selection_price_path
    from apps.demo_console.adapters import rx_research_reader
    from apps.demo_console.models import DecisionOverview, PerformanceHistory
    from apps.demo_console.i18n import language_scope
    view = rx_research_reader.RXView(history=PerformanceHistory(effective_end_date='2026-09-22'),
        calendar={'execution_status':'PENDING_NEXT_OPEN','scheduled_execution_date':'2026-09-23'},
        selections=tuple({'candidate_rank':i,'ticker':f'T{i:02}','raw_rank':i,'candidate_score':1/i} for i in range(1,21)))
    with language_scope('en'), patch.object(rx_research_reader,'read',return_value=view), \
            patch.object(selection_price_path,'render_selection_price_path'):
        render_rx_portfolio(DecisionOverview(decision_date='2026-09-22'))


def test_pending_rx_has_selection_but_never_invented_executed_holdings():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(_portfolio_page,default_timeout=20).run()
    assert not app.exception and not app.error
    assert len(app.dataframe) == 1 and len(app.dataframe[0].value) == 20
    assert any('not an executed holding snapshot' in item.value for item in app.info)


def _portfolio_failed_rx_page():
    from unittest.mock import patch
    import streamlit as st
    from apps.demo_console.components.rx_portfolio import render_rx_portfolio
    from apps.demo_console.components import selection_price_path
    from apps.demo_console.adapters import rx_research_reader
    from apps.demo_console.models import DecisionOverview
    def independent_detail(model, view):
        assert view.error
        st.write('A2 price and 13F inspector remains available')
    with patch.object(rx_research_reader,'read',return_value=rx_research_reader.RXView(error='Synthetic RX missing')), \
            patch.object(selection_price_path,'render_selection_price_path',side_effect=independent_detail):
        render_rx_portfolio(DecisionOverview(decision_date='2026-09-22'))


def test_rx_failure_does_not_remove_independent_a2_stock_inspector():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(_portfolio_failed_rx_page,default_timeout=20).run()
    assert not app.exception and not app.error
    assert any('Synthetic RX missing' in row.value for row in app.info)
    assert any('A2 price and 13F inspector remains available' in row.value for row in app.markdown)
