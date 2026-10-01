"""Recorded stock price paths and fills; a selection never creates a holding."""
from dataclasses import dataclass
from datetime import date
from math import isfinite

import altair as alt
import streamlit as st

from apps.demo_console.adapters import rx_research_reader
from apps.demo_console.components.chart_display import render_chart
from apps.demo_console.i18n import tr


@dataclass(frozen=True)
class HoldingEpisode:
    start: str
    exit: str | None = None
    entry_known: bool = True


def _day(value):
    return date.fromisoformat(str(value)[:10]).isoformat()


def _number(value):
    number = float(value)
    if not isfinite(number) or number < 0:
        raise ValueError("Invalid recorded position or price")
    return number


def holding_episodes(positions, ticker, cutoff):
    """Use real zero/nonzero position transitions, including repeated entries."""
    episodes, active = [], None
    rows = sorted((row for row in positions if row["ticker"] == ticker and _day(row["date"]) <= cutoff),
                  key=lambda row: _day(row["date"]))
    dates = [_day(row["date"]) for row in rows]
    if len(set(dates)) != len(dates):
        raise ValueError("Duplicate recorded position date")
    for row, day in zip(rows, dates):
        before, after = _number(row["shares_before"]) > 1e-14, _number(row["shares_after"]) > 1e-14
        if not before and after:
            if active is not None:
                raise ValueError("Position entry has no preceding recorded exit")
            active = HoldingEpisode(day)
        elif before and active is None:
            # The supplied ledger starts during an existing holding; its entry
            # date is unknown and must not become a fabricated buy marker.
            active = HoldingEpisode(day, entry_known=False)
        if before and not after and active is not None:
            episodes.append(HoldingEpisode(active.start, day, active.entry_known))
            active = None
    if active is not None:
        episodes.append(active)
    return tuple(episodes)


def _bounds(model, evidence):
    cutoff = min(_day(value) for value in (evidence["cutoff"], model.performance_cutoff_date,
        model.sample_end_date) if value)
    return _day(model.sample_start_date) if model.sample_start_date else "1900-01-01", cutoff


def window_data(evidence, model, ticker, episode=None):
    """Clip every plotted/table record locally; do not fill or extrapolate prices."""
    if evidence.get("adjustment") != "PIT_FORWARD_REHAB_INDEX":
        raise ValueError("Unrecognized execution price basis")
    lower, cutoff = _bounds(model, evidence)
    upper = min(episode.exit, cutoff) if episode and episode.exit else cutoff
    signals = sorted({_day(row["signal_date"]) for row in evidence["signals"]
        if row["ticker"] == ticker and lower <= _day(row["signal_date"]) <= cutoff})
    if episode:
        start = episode.start
        prior_signal = [day for day in signals if day < start]
        lower = max(lower, prior_signal[-1] if episode.entry_known and prior_signal else start)
    prices = sorted((dict(row, date=_day(row["date"])) for row in evidence["prices"]
        if row["ticker"] == ticker and lower <= _day(row["date"]) <= upper), key=lambda row: row["date"])
    if not episode and prices:
        # A pending or unfilled selection shows recent observed context only.
        prices = prices[-20:]
        lower = prices[0]["date"]
    for row in prices:
        if row.get("adjustment") != evidence["adjustment"] or min(_number(row["open"]), _number(row["close"])) <= 0:
            raise ValueError("Invalid recorded price basis or value")
    trades = tuple(dict(row, date=_day(row["date"])) for row in evidence["trades"]
        if row["ticker"] == ticker and lower <= _day(row["date"]) <= upper
        and row["side"] in {"BUY", "SELL"})
    for row in trades:
        if _number(row["execution_price"]) <= 0 or _number(row["shares"]) <= 0:
            raise ValueError("Invalid recorded trade")
    calendar = tuple(_day(day) for day in evidence.get("calendar_dates", ()))
    if calendar != tuple(sorted(set(calendar))):
        raise ValueError("Execution calendar is duplicated or unordered")
    previous = dict(zip(calendar[1:], calendar))
    price_map = {_day(row["date"]): row for row in evidence["prices"] if row["ticker"] == ticker}
    positions = {_day(row["date"]): row for row in evidence["positions"] if row["ticker"] == ticker}
    buy_dates = {row["date"] for row in trades if row["side"] == "BUY"}
    for row in prices:
        preceding = previous.get(row["date"])
        prior = price_map.get(preceding)
        prior_close = _number(prior["close"]) if prior and prior.get("adjustment") == evidence["adjustment"] else None
        if prior_close is not None and prior_close <= 0:
            raise ValueError("Invalid preceding session close")
        position = positions.get(row["date"])
        held_before = _number(position["shares_before"]) > 1e-14 if position is not None else None
        row.update(previous_session=preceding, previous_close=prior_close,
            overnight_gap=row["open"] / prior_close - 1 if prior_close is not None else None,
            held_before=held_before, new_buy_at_open=held_before is False and row["date"] in buy_dates)
    events = []
    for row in evidence.get("events", ()):
        if row.get("ticker") != ticker:
            continue
        value = next((row.get(key) for key in ("ex_date", "event_date", "date") if row.get(key)), None)
        if value is None:
            continue
        try:
            day = _day(value)
        except (ValueError, TypeError):
            continue
        if lower <= day <= upper:
            events.append({**row, "display_date": day})
    return {"prices": tuple(prices), "trades": trades, "events": tuple(events),
            "signals": tuple({"date": day} for day in signals if lower <= day <= upper),
            "start": lower, "end": upper}


def with_raw_quotes(window, quotes):
    """Join observed USD quotes by date without converting the execution index."""
    observed = {}
    for row in quotes:
        day = _day(row['date'])
        if day in observed or row.get('currency') != 'USD' or row.get('adjustment') != 'RAW':
            raise ValueError('Invalid raw quote identity or basis')
        if min(_number(row['raw_open']), _number(row['raw_close'])) <= 0:
            raise ValueError('Invalid raw quote')
        observed[day] = row
    return {**window, 'trades': tuple({**row,
        'raw_open': observed.get(row['date'], {}).get('raw_open')}
        for row in window['trades']), 'prices': tuple({**row,
        'raw_open': observed.get(row['date'], {}).get('raw_open'),
        'raw_close': observed.get(row['date'], {}).get('raw_close')}
        for row in window['prices'])}


def price_path_chart(window):
    """All y-values are observed open/close prices or actual engine fill prices."""
    labels = {"open": tr("Open"), "close": tr("Close")}
    prices = [{"date": row["date"], "price": row[field], "series": labels[field],
               "raw_open": row.get("raw_open"), "raw_close": row.get("raw_close"),
               "source": row.get("source", "")} for row in window["prices"] for field in ("open", "close")]
    x = alt.X("date:T", title=tr("Date"), axis=alt.Axis(format="%Y-%m-%d", labelAngle=0, tickCount=5))
    lines = alt.Chart(alt.Data(values=prices)).mark_line(point=len(window["prices"]) == 1).encode(
        x=x, y=alt.Y("price:Q", title=tr("Execution price index"), scale=alt.Scale(zero=False)),
        color=alt.Color("series:N", title=None, scale=alt.Scale(domain=list(labels.values()), range=["#2357d9", "#087f71"])),
        tooltip=[alt.Tooltip("date:T", title=tr("Date"), format="%Y-%m-%d"),
                 alt.Tooltip("series:N", title=tr("Price")), alt.Tooltip("price:Q", title=tr("Execution price index"), format=".4f"),
                 alt.Tooltip("raw_open:Q", title=tr("Market open (USD)"), format="$.4f"),
                 alt.Tooltip("raw_close:Q", title=tr("Market close (USD)"), format="$.4f"),
                 alt.Tooltip("source:N", title=tr("Source"))]).properties(name="selection_price_lines")
    layers = [lines]
    if window["signals"]:
        layers.append(alt.Chart(alt.Data(values=list(window["signals"]))).mark_rule(color="#8190a5", strokeDash=[2, 4], opacity=.35).encode(
            x=x, tooltip=[alt.Tooltip("date:T", title=tr("Selection signal date"), format="%Y-%m-%d")]).properties(name="selection_signal_dates"))
    if window["events"]:
        layers.append(alt.Chart(alt.Data(values=[{"date": row["display_date"]} for row in window["events"]])).mark_rule(
            color="#aa6b2d", strokeDash=[7, 3]).encode(x=x,
            tooltip=[alt.Tooltip("date:T", title=tr("Corporate action date"), format="%Y-%m-%d")]).properties(name="selection_event_dates"))
    if window["trades"]:
        fills = [{**row, "fill_label": tr("Executed buy" if row["side"] == "BUY" else "Executed sell")} for row in window["trades"]]
        layers.append(alt.Chart(alt.Data(values=fills)).mark_point(filled=True, size=105).encode(
            x=x, y="execution_price:Q", shape=alt.Shape("side:N", title=None, scale=alt.Scale(domain=["BUY", "SELL"], range=["triangle-up", "triangle-down"])),
            color=alt.Color("side:N", title=None, scale=alt.Scale(domain=["BUY", "SELL"], range=["#087f71", "#c74d64"])),
            tooltip=[alt.Tooltip("date:T", title=tr("Date"), format="%Y-%m-%d"), alt.Tooltip("fill_label:N", title=tr("Trade")),
                     alt.Tooltip("execution_price:Q", title=tr("Recorded fill price"), format=".4f"),
                     alt.Tooltip("raw_open:Q", title=tr("Market open (USD)"), format="$.4f"),
                     alt.Tooltip("shares:Q", title=tr("Shares"), format=".6f")]).properties(name="selection_executed_trades"))
    return alt.layer(*layers).resolve_scale(color="independent").properties(height=300).configure_view(stroke=None)


def render_selection_price_path(model, rx_view):
    """One strategy read per render; other Portfolio content stays independent."""
    st.subheader(tr("Selected stocks: price paths and executions"))
    labels = {"A2_HGB": "A2", "A2_RX": "A2 + RX"}
    strategy = st.segmented_control(tr("Strategy"), tuple(labels), default="A2_HGB", required=True,
        format_func=labels.__getitem__, key="selection_price_strategy")
    ticker = None
    try:
        available_names = set(rx_research_reader.selection_tickers(model, strategy="A2_HGB", view=rx_view))
        if strategy == "A2_RX":
            available_names.update(rx_research_reader.selection_tickers(model, strategy=strategy, view=rx_view))
        price_error = False
        try:
            evidence = rx_research_reader.price_evidence(rx_view, model, strategy=strategy)
        except (OSError, ValueError, KeyError, TypeError):
            price_error = True
            evidence = {"signals": (), "positions": (), "prices": (),
                "cutoff": model.performance_cutoff_date or model.decision_date}
        lower, cutoff = _bounds(model, evidence)
        signal_limit = min(_day(value) for value in (model.decision_date, model.sample_end_date) if value)
        selected = {row["ticker"] for row in evidence["signals"] if lower <= _day(row["signal_date"]) <= signal_limit}
        held = {row["ticker"] for row in evidence["positions"] if lower <= _day(row["date"]) <= cutoff
                and (_number(row["shares_before"]) > 1e-14 or _number(row["shares_after"]) > 1e-14)}
        tickers = tuple(sorted(selected | held | available_names))
        if not tickers:
            st.caption(tr("No selection or executed holding evidence is available in this sample."))
            return
        current = st.session_state.get("inspect_ticker")
        ticker = st.selectbox(tr("Stock"), tickers, index=tickers.index(current) if current in tickers else 0,
                             key=f"selection_price_ticker_{strategy}")
        if price_error:
            st.caption(tr("Verified stock price evidence is unavailable for this selection."))
            return
        episodes = tuple(item for item in holding_episodes(evidence["positions"], ticker, cutoff)
                         if item.start <= cutoff and (item.exit is None or item.exit >= lower))
        options = list(episodes)
        status = (rx_view.calendar or {}).get("execution_status") if strategy == "A2_RX" else model.execution_status
        pending = status in {"PENDING_NEXT_OPEN", "BLOCKED_PRICE_INPUT"} and any(
            row["ticker"] == ticker and _day(row["signal_date"]) == model.decision_date for row in evidence["signals"])
        if pending or not options:
            options.append(None)
        def label(index):
            episode = options[index]
            if episode is None:
                return tr("Pending selection · {date}", date=model.decision_date) if pending else tr("Selected without a recorded holding")
            return tr("Holding · {start} → {end}", start=episode.start, end=episode.exit or tr("Still held")) + (
                "" if episode.entry_known else " · " + tr("Entry predates available ledger"))
        index = st.selectbox(tr("Holding or pending selection interval"), tuple(range(len(options))), index=len(options) - 1,
            format_func=label, key=f"selection_price_interval_{strategy}_{ticker}")
        episode = options[index]
        window = window_data(evidence, model, ticker, episode)
        st.caption(tr("Prices use the execution engine's point-in-time adjusted index, not raw market quotes. Trading fees are deducted separately."))
        st.caption(tr("Dashed lines mark selection signals; triangles mark recorded BUY/SELL executions. A selection alone does not establish a holding."))
        if episode is None:
            st.caption(tr("Pending selection: no position entry is implied. The chart shows up to 20 recent observed price dates.") if pending
                       else tr("No holding episode is recorded for this selection. The chart shows up to 20 recent observed price dates."))
        if not window["prices"]:
            st.caption(tr("No verified prices are available for this interval."))
            return
        raw = None
        if model.source_manifest_path and model.source_manifest_sha256:
            from apps.demo_console.adapters.raw_stock_price_reader import read_raw_stock_prices
            parent = {'path': model.source_manifest_path, 'sha256': model.source_manifest_sha256}
            from apps.demo_console.adapters.stock_identity_display import read_identity_chain
            candidate = read_identity_chain(parent, ticker)
            chain = candidate if candidate.get('status') == 'VERIFIED' else None
            raw = read_raw_stock_prices(parent, ticker, window['start'], window['end'],
                identity_chain=chain)
            window = with_raw_quotes(window, raw.get('rows', ()))
        latest = window['prices'][-1]
        if latest.get('raw_open') is not None:
            opening, closing = st.columns(2)
            opening.metric(tr("Market open (USD)"), f"${latest['raw_open']:,.4f}")
            closing.metric(tr("Market close (USD)"), f"${latest['raw_close']:,.4f}")
            st.caption(tr("Market quotes for {date}. Hover over the chart or open daily details for other dates. USD quotes are unadjusted; the chart retains the execution index.", date=latest['date']))
        else:
            st.caption(tr("Verified unadjusted USD quotes are unavailable for this date; index values are not dollar prices."))
        render_chart(price_path_chart(window))
        if raw and raw.get('rows'):
            from apps.demo_console.components.stock_quote_chart import render_quote_history
            with st.expander(tr('Dollar price history and splits')):
                render_quote_history(raw, key=f'selection_quote_basis_{strategy}_{ticker}')
        if window["trades"]:
            with st.expander(tr("Recorded executions")):
                st.dataframe([{**{key: row.get(key) for key in ("date", "side", "shares", "execution_price", "notional")},
                               tr("Market open (USD)"): row.get('raw_open')}
                              for row in window["trades"]], hide_index=True)
        st.caption(tr("Overnight gap = open / previous session close − 1. Missing previous-session prices remain blank. Only shares held before the open are exposed; a new opening buy does not earn the preceding gap. This breakdown is descriptive and is not added again to portfolio returns."))
        with st.expander(tr("Daily prices and overnight gaps")):
            detail = []
            for row in window["prices"]:
                exposure = ("Held before open" if row["held_before"] else "New buy at open: preceding gap excluded"
                    if row["new_buy_at_open"] else "Not held before open" if row["held_before"] is False else "Pre-open holding unavailable")
                detail.append({tr("Date"): row["date"], tr("Previous session"): row["previous_session"],
                    tr("Previous close"): row["previous_close"], tr("Open"): row["open"], tr("Close"): row["close"],
                    tr("Market open (USD)"): row.get("raw_open"), tr("Market close (USD)"): row.get("raw_close"),
                    tr("Overnight gap (%)"): row["overnight_gap"] * 100 if row["overnight_gap"] is not None else None,
                    tr("Holding before open"): tr(exposure)})
            st.dataframe(detail, hide_index=True)
        if window["events"]:
            with st.expander(tr("Corporate actions and price adjustments")):
                st.dataframe(list(window["events"]), hide_index=True)
        else:
            st.caption(tr("No dated corporate-action event is recorded for this stock in the displayed interval."))
    except (OSError, ValueError, KeyError, TypeError):
        st.caption(tr("Verified stock price evidence is unavailable for this selection."))
    finally:
        if ticker is not None:
            render_stock_holders(model, ticker)


def render_stock_holders(model, ticker, *, security_id=None, key_prefix='stock'):
    """The chosen stock shares one inspector; 13F queries never alter its signal."""
    st.markdown("**" + tr("13F institutional holdings · {ticker}", ticker=ticker) + "**")
    labels = {"AS_OF_SIGNAL": tr("Effective disclosures at the selected signal"),
              "LATEST_DISCLOSED": tr("Latest disclosed holdings")}
    mode = st.segmented_control(tr("13F disclosure scope"), tuple(labels), default="AS_OF_SIGNAL",
        required=True, key=f"{key_prefix}_13f_scope", format_func=labels.__getitem__)
    if mode == "LATEST_DISCLOSED":
        st.caption(tr("Latest holdings are a current disclosure query only. They do not change historical stock selection or performance."))
    try:
        from apps.demo_console.adapters.stock_13f_reader import read_stock_holders
        result = read_stock_holders(model, ticker, mode=mode, **({'security_id': security_id} if security_id else {}))
        if result.get("status") not in {"READY", "PARTIAL"}:
            st.info(tr("Verified 13F holdings are unavailable for this stock and disclosure scope."))
        else:
            st.caption(tr("Reported quarter {quarter} · Effective {effective} · Filings through {asof}",
                quarter=result.get("quarter") or "—", effective=result.get("effective_date") or "—",
                asof=result.get("filing_as_of") or "—"))
            rows = result.get("rows", ())
            if rows:
                st.dataframe([{
                    "institution": row["institution_name"], "person": row.get("notable_person"),
                    "shares": row.get("shares"), "value": row.get("reported_value"),
                    "filing_date": row.get("filing_date"), "source": row.get("source_url")}
                    for row in rows], hide_index=True, width="stretch", key="stock_13f_holders",
                    column_config={"institution": tr("Reporting institution"),
                        "person": tr("Registered associated person"), "shares": tr("Reported shares"),
                        "value": tr("Reported value (USD)"), "filing_date": tr("Filing date"),
                        "source": st.column_config.LinkColumn(tr("Disclosure source"))})
            else:
                st.caption(tr("No matching holding is recorded within this verified disclosure scope."))
        st.caption(tr("Associated people are registry labels for institutions, not evidence of personal-account holdings. Reported holdings describe the filing quarter, not a live portfolio."))
        for note in result.get("limitations", ()):
            st.caption(tr(note))
    except (ImportError, OSError, ValueError, KeyError, TypeError):
        st.caption(tr("Verified 13F holdings are unavailable for this stock and disclosure scope."))
