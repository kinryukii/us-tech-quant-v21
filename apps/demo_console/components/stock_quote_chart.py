"""Observed USD quotes and explicitly evidenced split-only display adjustments."""
import altair as alt
import streamlit as st

from apps.demo_console.components.chart_display import render_chart
from apps.demo_console.i18n import tr


def action_label(action):
    return tr('{old} → {new} share units', old=f"{action['old_shares']:g}", new=f"{action['new_shares']:g}")


def quote_chart(raw, adjusted=False):
    fields = ('split_adjusted_open', 'split_adjusted_close') if adjusted else ('raw_open', 'raw_close')
    rows = [{**row, 'price': row[field], 'series': tr(label)} for row in raw['rows']
            for field, label in zip(fields, ('Open', 'Close'))]
    title = tr('Split-adjusted comparable price (USD)') if adjusted else tr('Market price (USD)')
    lines = alt.Chart(alt.Data(values=rows)).mark_line(point=len(raw['rows']) == 1).encode(
        x=alt.X('date:T', title=tr('Date')),
        y=alt.Y('price:Q', title=title, scale=alt.Scale(zero=False)),
        color=alt.Color('series:N', title=None, scale=alt.Scale(range=['#2357d9', '#087f71'])),
        tooltip=[alt.Tooltip('date:T', title=tr('Date'), format='%Y-%m-%d'),
                 alt.Tooltip('series:N', title=tr('Price')), alt.Tooltip('price:Q', title=title, format='$.4f'),
                 alt.Tooltip('raw_open:Q', title=tr('Market open (USD)'), format='$.4f'),
                 alt.Tooltip('raw_close:Q', title=tr('Market close (USD)'), format='$.4f')])
    dates = [row['date'] for row in raw['rows']]
    actions = [{**row, 'label': action_label(row)} for row in raw.get('corporate_actions', ())
               if min(dates) <= row['event_date'] <= max(dates)]
    layers = [lines]
    if actions:
        marks = alt.Chart(alt.Data(values=actions)).encode(x='event_date:T',
            tooltip=[alt.Tooltip('event_date:T', title=tr('Corporate action date'), format='%Y-%m-%d'),
                     alt.Tooltip('label:N', title=tr('Split / consolidation'))])
        layers.extend([marks.mark_rule(color='#b37729', strokeDash=[6, 3]),
                       marks.mark_text(align='left', dx=5, dy=8, baseline='top', color='#976224').encode(y=alt.value(0), text='label:N')])
    return alt.layer(*layers).properties(height=250)


def render_quote_history(raw, *, key):
    if not raw.get('rows'):
        st.caption(tr('Verified unadjusted USD quotes are unavailable for this interval.'))
        return
    unsupported = raw.get('unsupported_corporate_actions', ())
    split_ready = raw.get('split_display_status') == 'READY' and not unsupported
    modes = ('RAW', 'SPLIT') if split_ready else ('RAW',)
    mode = st.segmented_control(tr('Price display'), modes, default='RAW', required=True,
        format_func=lambda value: tr('Actual historical USD prices' if value == 'RAW' else 'Comparable prices after verified splits'), key=key)
    if mode == 'SPLIT':
        st.caption(tr('Share-unit basis: {date}. Only verified split/consolidation ratios through this date are applied. No dividends or strategy returns are included.', date=raw['split_basis_date']))
    else:
        st.caption(tr('Unadjusted observed USD quotes; splits can create discontinuities. This chart does not calculate strategy returns.'))
    render_chart(quote_chart(raw, adjusted=mode == 'SPLIT'))
    actions = raw.get('corporate_actions', ())
    if actions:
        st.dataframe([{tr('Corporate action date'): row['event_date'], tr('Split / consolidation'): action_label(row)}
                      for row in actions], hide_index=True)
    if unsupported:
        st.warning(tr('Some mixed corporate actions cannot be represented by split ratios alone. Comparable prices are unavailable for this range.'))
