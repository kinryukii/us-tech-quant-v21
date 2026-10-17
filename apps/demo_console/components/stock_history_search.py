"""Independent historical stock lookup; never changes the active selection."""
from dataclasses import replace
from datetime import date

import altair as alt
import streamlit as st

from apps.demo_console.adapters import stock_history_reader as reader
from apps.demo_console.components.chart_display import render_chart
from apps.demo_console.components.localized_tabs import localized_expander
from apps.demo_console.i18n import tr


def _query_identity(history, ticker, period, query, *, prefix):
    """Reuse the verified company/CUSIP choice for both stock search surfaces."""
    result = query(history, ticker, *map(str, period))
    chain = None
    if result['status'] == 'AMBIGUOUS_IDENTITY':
        from apps.demo_console.adapters.stock_identity_display import read_identity_chain
        reference = history.get('source_refs', {}).get('a2')
        candidate = read_identity_chain(reference, ticker) if reference else {}
        if candidate.get('status') == 'VERIFIED':
            mode_labels = {value: tr('Verified company continuity' if value == 'COMPANY' else 'Separate CUSIP records')
                for value in ('COMPANY', 'SECURITY')}
            mode = st.segmented_control(tr('Identity history'), ('COMPANY', 'SECURITY'), default='COMPANY', required=True,
                format_func=mode_labels.__getitem__, key=prefix + '_mode')
            if mode == 'COMPANY':
                chain = candidate
                result = query(history, ticker, *map(str, period),
                    identity_mode='VERIFIED_COMPANY', identity_chain=chain)
                st.caption(tr('Verified continuity: {old} → {new}, corporate action on {date}. Original reported identities remain unchanged.',
                    old=chain['old_security_id'], new=chain['new_security_id'], date=chain['event_date']))
        if result['status'] == 'AMBIGUOUS_IDENTITY':
            identity = st.selectbox(tr('Security identity (CUSIP)'), result['identities'], key=prefix + '_identity')
            result = query(history, ticker, *map(str, period), security_id=identity)
    return result, chain


def _render_market_details(model, history, result, ticker, period, chain, *, prefix):
    """Cached identity-bound prices and 13F details, with their own reference date."""
    if not st.checkbox(tr('Show market prices and institutional holdings'), key=prefix + '_details'):
        return
    reference = history.get('source_refs', {}).get('a2')
    if reference is None:
        st.info(tr('Verified price and institutional sources are unavailable for this query.'))
        return
    from apps.demo_console.adapters.raw_stock_price_reader import read_raw_stock_prices
    from apps.demo_console.components.selection_price_path import render_stock_holders
    from apps.demo_console.components.stock_quote_chart import render_quote_history
    raw = read_raw_stock_prices(reference, ticker, *map(str, period),
        security_id=result.get('security_id'), identity_chain=chain)
    render_quote_history(raw, key=prefix + '_price_basis')
    if result.get('daily'):
        dates = [row['date'] for row in result['daily']]
        key = prefix + '_13f_date'
        if st.session_state.get(key) not in dates:
            st.session_state[key] = dates[-1]
        query_day = st.selectbox(tr('13F reference date'), dates, index=None, key=key)
        selected_day = next(row for row in result['daily'] if row['date'] == query_day)
        render_stock_holders(replace(model, decision_date=query_day), ticker,
            security_id=selected_day.get('security_id') or result.get('security_id'), key_prefix=prefix)


def rank_chart(rows):
    # Points preserve unavailable dates instead of joining across missing ranks.
    return alt.Chart(alt.Data(values=rows)).mark_point(filled=True, size=22).encode(
        x=alt.X('date:T', title=tr('Date')),
        y=alt.Y('rank:Q', title=tr('Full-pool rank'), scale=alt.Scale(reverse=True, zero=False)),
        color=alt.condition('datum.top20', alt.value('#087f71'), alt.value('#879aaf')),
        tooltip=[alt.Tooltip('date:T', title=tr('Date'), format='%Y-%m-%d'),
                 alt.Tooltip('rank:Q', title=tr('Rank'), format='d'),
                 alt.Tooltip('score:Q', title=tr('Model score'), format='.6f'),
                 alt.Tooltip('quarter:N', title=tr('13F quarter'))]).properties(height=240)


def render_stock_history_search(model):
    history = reader.load_history(model)
    if history.get('status') != 'READY':
        st.info(tr('Verified full-pool history is unavailable.'))
        return
    catalog = {item['ticker']: item for item in history['catalog']}
    st.caption(tr('Search the complete verified historical pool, including stocks never selected in Top40. This query has its own date range and does not change the current signal or portfolio.'))
    ticker = st.selectbox(tr('Search any stock'), tuple(catalog), index=None, accept_new_options=True,
        format_func=lambda symbol: f"{symbol} · {catalog[symbol]['issuer_name']}" if symbol in catalog else symbol,
        placeholder=tr('Type a ticker or company name'), key='full_stock_history_ticker')
    if not ticker:
        return
    ticker = ticker.strip().upper()
    period = st.date_input(tr('Stock history date range'),
        value=(date.fromisoformat(history['start_date']), date.fromisoformat(history['end_date'])),
        min_value=date.fromisoformat(history['start_date']), max_value=date.fromisoformat(history['end_date']),
        key='full_stock_history_dates')
    if len(period) != 2:
        st.info(tr('Choose both dates.'))
        return
    result, chain = _query_identity(history, ticker, period, reader.query_history, prefix='full_stock_history')
    if result['status'] != 'READY':
        st.info(tr('This ticker has no verified record in this project. This does not mean it has never traded or never been held by an institution.'))
        return
    summary = result['summary']
    metrics = [('Top20 days', 'top20_days'), ('Top20 selection periods', 'top20_episodes'),
               ('Top40 days', 'top40_days'), ('Top40 selection periods', 'top40_episodes'),
               ('Best recorded rank', 'best_rank'), ('A2 + RX selected days', 'rx_selected_days')]
    for column, (label, key) in zip(st.columns(3), metrics[:3]):
        column.metric(tr(label), str(summary[key]) if summary[key] is not None else '—')
    for column, (label, key) in zip(st.columns(3), metrics[3:]):
        value = summary[key] if key != 'rx_selected_days' or result['rx_available'] else None
        column.metric(tr(label), str(value) if value is not None else '—')
    st.caption(tr('Counts are selection trading days, not buys. A continuous period ends at any unselected or unverified trading day; a period already active at the range start counts once within this range.'))
    st.caption(tr('In pool: {pool} days · Ranked: {ranked} · In-pool data gaps: {gaps} · Outside the effective pool: {outside}',
        pool=summary['pool_days'], ranked=summary['ranked_days'], gaps=summary['unranked_pool_days'], outside=summary['outside_pool_days']))
    st.caption(tr('First Top20 in range: {first} · Last Top20 in range: {last}',
        first=summary['top20_first'] or '—', last=summary['top20_last'] or '—'))
    if summary['ranked_days']:
        render_chart(rank_chart(result['daily']))
    else:
        st.info(tr('No verified ranking in this interval; this is not a rank below 40.'))
    labels = {'top20': 'A2 Top20', 'top40': 'A2 Top40', 'rx_selected': 'A2 + RX'}
    with st.expander(tr('Continuous selection periods'), on_change="rerun", key="full_stock_selection_periods") as periods:
        if periods.open:
            st.dataframe([{tr('Selection'): labels[row['type']], tr('Start'): row['start_date'],
                tr('End'): row['end_date'], tr('Trading days'): row['trading_days']}
                for row in result['episodes']], hide_index=True)
    with st.expander(tr('Daily ranking and pool records'), on_change="rerun", key="full_stock_daily_records") as daily_records:
        if daily_records.open:
            st.dataframe([{tr('Date'): row['date'], tr('13F quarter'): row['quarter'],
                'CUSIP': row.get('security_id'),
                tr('Rank'): row['rank'], tr('Model score'): row['score'], 'Top20': row['top20'],
                'Top40': row['top40'], 'A2 + RX': row['rx_selected'] if result['rx_available'] else None,
                tr('Coverage'): tr({'RANKED': 'Ranked', 'NO_VERIFIED_RANK': 'In pool, no verified rank',
                                   'OUTSIDE_POOL': 'Outside effective pool'}[row['status']])}
                for row in reversed(result['daily'])], hide_index=True)
    _render_market_details(model, history, result, ticker, period, chain, prefix='full_stock_history')


def applied_stock_records(daily):
    """Keep each recorded calendar date, including missing ranks and targets."""
    from apps.demo_console.components.history_charts import _segments
    from apps.demo_console.components.performance_charts import STRATEGY_COLORS
    from apps.demo_console.components.top20_table import _finite_number

    records = []
    for strategy_id in dict.fromkeys(sid for day in daily for sid in day.get("strategies", {})):
        points = []
        for day in sorted(daily, key=lambda item: item['date']):
            row = day.get('strategies', {}).get(strategy_id, {})
            # A prior target may be useful in a snapshot; it cannot fill a later
            # historical date or enter that date's coverage denominator.
            weight_date = row.get('weight_date')
            target_dated = weight_date == day['date']
            points.append({'date': day['date'], 'execution_date': day['date'], 'strategy_id': strategy_id,
                'rank': _finite_number(row.get('model_rank')), 'score': _finite_number(row.get('score')),
                'raw_input_rank':_finite_number(row.get('raw_rank')) if strategy_id in ('HGB_DIAG_5','HGB_FACTOR_5') else None,
                'target_weight': _finite_number(row.get('target_weight')) if target_dated else None,
                'selected': row.get('selected') if target_dated else None,
                'eligible': row.get('eligible'), 'weight_date': weight_date,
                'target_kind': row.get('target_kind'), 'security_id': (None if row.get('security_identity_status') ==
                    'TICKER_ONLY_NO_RECORDED_CUSIP' else row.get('security_id') or day.get('security_id')),
                **{field: row.get(field) for field in ('research_weight', 'research_units', 'native_action',
                    'research_mark_date', 'research_accounting_qualified', 'security_identity_status',
                    'planned_execution_date', 'research_orders', 'research_fills')},
                'status': row.get('status'), 'score_status': row.get('score_status'),
                'target_status': row.get('target_status'), 'in_pool': day.get('in_pool')})
        _segments(points, 'rank')
        _segments(points, 'target_weight')
        _segments(points, 'research_weight')
        records.extend(points)
    return records


def applied_stock_summary(records):
    """Unknown target dates stay outside the known-selection denominator."""
    from apps.demo_console.components.performance_charts import STRATEGY_COLORS
    result = {}
    for strategy_id in dict.fromkeys(row["strategy_id"] for row in records):
        rows = [row for row in records if row['strategy_id'] == strategy_id]
        known = [row for row in rows if type(row.get('selected')) is bool]
        ranks = [row['rank'] for row in rows if row.get('rank') is not None]
        result[strategy_id] = {'selected_days': sum(row['selected'] for row in known),
            'target_days': len(known), 'ranked_days': len(ranks),
            'best_rank': min(ranks) if ranks else None}
    return result


def applied_stock_chart(records, field):
    """The observed calendar and explicit segments prevent gap interpolation."""
    from apps.demo_console.components.performance_charts import STRATEGY_COLORS, _date_axis, _style
    from apps.demo_console.pages.selected_strategies import WORKSPACE_STRATEGIES, LEGACY_STRATEGIES, strategy_label

    valid = [row[field] for row in records if row.get(field) is not None]
    if not valid:
        return None
    dates = sorted({row['date'] for row in records})
    axis = _date_axis([{'execution_date': day} for day in dates], title=tr('Signal / record date'))
    axis.scale = alt.Scale(domain=axis.to_dict()['scale']['domain'], nice=False)
    rank = field == 'rank'
    low, high = (1, max(valid)) if rank else (0, max(valid))
    if high == low:
        high = low + (1 if rank else .01)
    labels = {sid: tr(strategy_label(sid)) for sid in dict.fromkeys(row["strategy_id"] for row in records)
              if field != "research_weight" or any(row["strategy_id"] == sid and row.get(field) is not None for row in records)}
    points = [{**row, 'strategy': labels[row['strategy_id']]} for row in records if row['strategy_id'] in labels]
    plot = alt.Chart(alt.Data(values=points)).transform_filter(f'isValid(datum.{field})').mark_line(
        point=alt.OverlayMarkDef(filled=True, size=30), clip=True, strokeWidth=2).encode(
            x=axis, y=alt.Y(f'{field}:Q', title=tr('Model rank' if rank else 'Recorded research holding weight' if field == 'research_weight' else 'Portfolio weight'),
                scale=alt.Scale(domain=[low, high], nice=False, zero=False, reverse=rank),
                axis=alt.Axis(format='d' if rank else '.0%')),
            color=alt.Color('strategy:N', title=None,
                scale=alt.Scale(domain=list(labels.values()), range=[STRATEGY_COLORS[sid] for sid in labels]),
                legend=alt.Legend(orient='bottom', columns=2, labelLimit=0, columnPadding=16, rowPadding=6)),
            detail=alt.Detail(f'{field}_segment:N'),
            tooltip=[alt.Tooltip('execution_date:T', title=tr('Date'), format='%Y-%m-%d'),
                alt.Tooltip('strategy:N', title=tr('Strategy')),
                alt.Tooltip(f'{field}:Q', title=tr('Model rank' if rank else 'Recorded research holding weight' if field == 'research_weight' else 'Portfolio weight'), format='d' if rank else '.2%')])
    return _style(plot.properties(height=400))


def _bounded_stock_period(history, as_of):
    start = date.fromisoformat(history['start_date'])
    end = min(date.fromisoformat(history['end_date']), date.fromisoformat(str(as_of)))
    if start > end:
        return None
    key = 'applied_stock_dates'
    previous = st.session_state.get(key, (start, end))
    bounded = tuple(max(start, min(end, item if isinstance(item, date) else date.fromisoformat(str(item)))) for item in previous)
    if len(bounded) == 2 and bounded[0] > bounded[1]:
        bounded = (bounded[1], bounded[0])
    if key not in st.session_state or bounded != previous:
        st.session_state[key] = bounded
    # Native 1.63 reads the session range when value="today". This avoids
    # supplying a second default while preserving the range through bounds.
    return st.date_input(tr('Stock history date range'), value='today', min_value=start, max_value=end,
        key=key, persist_state='session')


def _native_stock_rows(records):
    from apps.demo_console.pages.selected_strategies import strategy_label

    return [{'date': row['date'], 'strategy': tr(strategy_label(row['strategy_id'])),
        'native_action': row.get('native_action'), 'planned_execution_date': row.get('planned_execution_date'),
        'research_weight': row.get('research_weight'), 'research_units': row.get('research_units'),
        'research_mark_date': row.get('research_mark_date'),
        'accounting_qualified': row.get('research_accounting_qualified'),
        'research_orders': row.get('research_orders'), 'research_fills': row.get('research_fills'),
        'security_identity': row.get('security_identity_status')}
        for row in records if any(row.get(field) is not None for field in
            ('native_action', 'research_weight', 'research_orders', 'research_fills'))]


def render_applied_stock_history(raw_model, package, as_of, *, history=None):
    """Inline stock research uses a private interval within the observation date."""
    from apps.demo_console.adapters import workspace_reader
    from apps.demo_console.components.top20_table import (APPLIED_STOCK_FOCUS_KEY, _applied_selection_label,
        _applied_weight_label, _applied_coverage_label)
    from apps.demo_console.pages.selected_strategies import WORKSPACE_STRATEGIES, LEGACY_STRATEGIES, strategy_label, replay_provenance_caption

    st.markdown('#### ' + tr('Stock history across strategies'))
    history = history if history is not None else workspace_reader.load_applied_stock_catalog(
        package=package, raw_model=raw_model, as_of=as_of)
    ready = history.get('status') in ('READY', 'CATALOG_READY') and history.get('start_date') and history.get('end_date')
    catalog = {item['ticker']: item for item in history.get('catalog', [])}
    st.caption(tr('Search every verified stock, including names outside the current ranking or allocation. The query interval ends no later than {date} and leaves the workbench observation date unchanged.', date=as_of))
    controls = st.columns([2, 1.2])
    with controls[0]:
        ticker = st.selectbox(tr('Search any stock'), tuple(catalog), index=None, accept_new_options=True,
            format_func=lambda symbol: f"{symbol} · {catalog[symbol].get('company') or catalog[symbol].get('issuer_name') or symbol}" if symbol in catalog else symbol,
            placeholder=tr('Type a ticker or company name'), key=APPLIED_STOCK_FOCUS_KEY, persist_state='session')
    with controls[1]:
        period = _bounded_stock_period(history, as_of) if ready else None
    if not ready:
        st.info(tr('Verified full-pool history is unavailable.'))
        if history.get('error'):
            st.warning(tr('Historical stock records failed verification. Current-day rankings are verified separately.'))
            with st.expander(tr('Verification details')):
                st.code(str(history['error']), language=None)
        return
    if period is None:
        st.info(tr('No verified stock history exists on or before the observation date.'))
        return
    if not ticker:
        return
    ticker = ticker.strip().upper()
    if len(period) != 2:
        st.info(tr('Choose both dates.'))
        return
    if history.get('_catalog_only'):
        loader = workspace_reader.load_active_stock_history if history.get('_active_catalog') else workspace_reader.load_applied_stock_history
        extra = {'account_state': history.get('_catalog_account_state')} if history.get('_active_catalog') else {}
        history = loader(package=package, raw_model=raw_model, as_of=as_of, catalog=history, **extra)
        if history.get('status') != 'READY':
            st.info(tr('Verified full-pool history is unavailable.'))
            if history.get('error'):
                st.warning(tr('Historical stock records failed verification. Current-day rankings are verified separately.'))
                with st.expander(tr('Verification details')):
                    st.code(str(history['error']), language=None)
            return
    result, chain = _query_identity(history, ticker, period, workspace_reader.query_active_stock_history if "_active_account_state" in history
        else workspace_reader.query_applied_stock_history,
        prefix='applied_stock_history')
    if result.get('status') != 'READY' or not result.get('daily'):
        st.info(tr('This ticker has no verified record in this project. This does not mean it has never traded or never been held by an institution.'))
        return
    if result.get('native_stock_note'):
        st.caption(replay_provenance_caption(result['native_stock_note']))
    if result.get('native_stock_errors'):
        st.warning(tr('Some native research stock records failed verification: {names}',
            names=' · '.join(strategy_label(sid) for sid in result['native_stock_errors'])))
    if result.get('score_source_errors'):
        st.warning(tr('Some HGB historical inputs failed verification. Their rankings and targets remain unavailable on those dates.'))
        with st.expander(tr('Verification details')):
            st.code('\n'.join(day+': '+error for day,error in list(result['score_source_errors'].items())[:3])[:12288],language=None)
    records = applied_stock_records(result['daily'])
    summary = applied_stock_summary(records)
    st.caption(tr('Raw ranks cover the verified full pool; HGB ranks cover the recorded Raw Top40. Selection counts use only dates with verified weights. Missing targets are unknown, not unselected.'))
    st.caption(tr('Raw ranks use the latest verified coverage. HGB historical inputs and selections retain their accepted signal source version; later coverage updates can change a same-day Raw rank.'))
    st.caption(tr('Observation dates limit recorded sessions; accepted later source revisions do not establish availability at the original decision time.'))
    st.dataframe([{'strategy': tr(strategy_label(sid)),
        'selection_coverage': f"{value['selected_days']} / {value['target_days']}" if value['target_days'] else '—',
        'ranked_days': value['ranked_days'], 'best_rank': value['best_rank']}
        for sid, value in summary.items()], hide_index=True, width='stretch', placeholder='—', column_config={
            'strategy': tr('Strategy'), 'selection_coverage': tr('Selected / verified weight dates'),
            'ranked_days': tr('Ranked days'), 'best_rank': tr('Best recorded rank')})
    dates = [day['date'] for day in result['daily']]
    if st.session_state.get('applied_stock_snapshot_date') not in dates:
        st.session_state['applied_stock_snapshot_date'] = dates[-1]
    state_day = st.selectbox(tr('Stock snapshot date'), dates, index=None,
        key='applied_stock_snapshot_date', persist_state='session')
    state = [row for row in records if row['date'] == state_day]
    st.dataframe([{'strategy': tr(strategy_label(row['strategy_id'])),
        'rank': row['rank'], 'raw_input_rank':row.get('raw_input_rank'), 'score': row['score'], 'weight': row['target_weight'],
        'selection': _applied_selection_label(row),
        'weight_date': row['weight_date'],
        'weight_kind': _applied_weight_label(row['target_kind'])}
        for row in state], hide_index=True, width='stretch', placeholder='—', column_config={
            'strategy': tr('Strategy'), 'rank': st.column_config.NumberColumn(tr('Rank'), format='%d'),
            'raw_input_rank':st.column_config.NumberColumn(tr('HGB original Raw input rank'),format='%d'),
            'score': st.column_config.NumberColumn(tr('Model score'), format='%.6f'),
            'weight': st.column_config.NumberColumn(tr('Portfolio weight'), format='percent'),
            'selection': tr('Selection status'), 'weight_date': tr('Weight date'), 'weight_kind': tr('Weight record type')})
    with st.container(key='applied_stock_trajectories'):
        for column, field, title in zip(st.columns(2), ('rank', 'target_weight'), ('Rank history', 'Allocation history')):
            with column:
                st.markdown('**' + tr(title) + '**')
                chart = applied_stock_chart(records, field)
                if chart is None:
                    st.info(tr('No verified ranking in this interval; this is not a rank below 40.') if field == 'rank'
                        else tr('No verified weights in this interval.'))
                else:
                    render_chart(chart)
    if any(row.get('research_weight') is not None for row in records):
        st.markdown('**' + tr('Recorded research holding history') + '**')
        chart = applied_stock_chart(records, 'research_weight')
        if chart is not None:
            render_chart(chart)
    st.caption(tr('Lines stop at missing observations. Target allocations and recorded holdings retain their own dates and record types.'))
    with st.expander(tr('Daily ranking and allocation records'), on_change="rerun", key="applied_stock_daily_records") as allocation_records:
        if allocation_records.open:
            st.dataframe([{'date': row['date'], 'strategy': tr(strategy_label(row['strategy_id'])),
                'rank': row['rank'], 'raw_input_rank':row.get('raw_input_rank'), 'score': row['score'], 'weight': row['target_weight'],
                'selection': _applied_selection_label(row), 'weight_date': row['weight_date'],
                'security_id': row['security_id'],
                'in_pool': row['in_pool'], 'score_status': _applied_coverage_label(row['score_status']),
                'target_status': _applied_coverage_label(row['target_status'])}
                for row in sorted(records, key=lambda item: (-date.fromisoformat(item['date']).toordinal(),
                    tuple({**WORKSPACE_STRATEGIES, **LEGACY_STRATEGIES}).index(item['strategy_id'])))],
                hide_index=True, width='stretch', placeholder='—', column_config={
                    'date': tr('Date'), 'strategy': tr('Strategy'),
                    'rank': st.column_config.NumberColumn(tr('Rank'), format='%d'),
                    'raw_input_rank':st.column_config.NumberColumn(tr('HGB original Raw input rank'),format='%d'),
                    'score': st.column_config.NumberColumn(tr('Model score'), format='%.6f'),
                    'weight': st.column_config.NumberColumn(tr('Portfolio weight'), format='percent'),
                    'selection': tr('Selection status'), 'weight_date': tr('Weight date'), 'security_id': 'CUSIP', 'in_pool': tr('In verified pool'),
                    'score_status': tr('Score coverage'), 'target_status': tr('Weight coverage')})
    if any(any(row.get(field) is not None for field in
            ('native_action', 'research_weight', 'research_orders', 'research_fills')) for row in records):
        with localized_expander('Original MAIN stock actions, holdings and research fills', key="applied_stock_native_records") as native_records:
            if native_records.open:
                st.dataframe(_native_stock_rows(records), hide_index=True, width='stretch', placeholder='—', column_config={
                    'date': tr('Date'), 'strategy': tr('Strategy'), 'native_action': tr('Recorded model action'),
                    'planned_execution_date': tr('Planned execution date'),
                    'research_weight': st.column_config.NumberColumn(tr('Recorded research holding weight'), format='percent'),
                    'research_units': tr('Original research fractional shares'), 'research_mark_date': tr('Original mark date'),
                    'accounting_qualified': tr('Research accounting qualified'),
                    'research_orders': st.column_config.JsonColumn(tr('Original research order records')),
                    'research_fills': st.column_config.JsonColumn(tr('Original research fill records')),
                    'security_identity': tr('Native ledger identity scope')})
    _render_market_details(raw_model, history, result, ticker, period, chain, prefix='applied_stock_history')
