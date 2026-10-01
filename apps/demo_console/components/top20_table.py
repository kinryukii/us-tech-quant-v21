"""Format recorded rows for a presentation table; never infer portfolio actions."""

from html import escape
from math import isfinite

from apps.demo_console.models import HoldingRow
from apps.demo_console.i18n import tr


_OPTIONAL_COLUMNS = (
    ("rank", "Rank"),
    ("rank_change", "ΔRank"),
    ("ticker", "Ticker"),
    ("score", "Score"),
    ("held_before", "Held before"),
    ("raw_action", "Raw A2 action"),
    ("rx_action", "RX action"),
    ("final_action", "Final action"),
    ("weight", "Weight"),
)


def table_records(rows: tuple[HoldingRow, ...]) -> list[dict]:
    """Omit wholly unavailable columns; sorting only uses the recorded rank."""
    fields = [(field, label) for field, label in _OPTIONAL_COLUMNS
              if field == "ticker" or any(getattr(row, field) is not None for row in rows)]
    ordered = sorted(rows, key=lambda row: (row.rank is None, row.rank or 0))
    return [{label: getattr(row, field) for field, label in fields} for row in ordered]


def _finite_number(value: object) -> float | None:
    """Non-finite numeric cells are unavailable, never CSS widths or signals."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def _missing(reason: str = "Recorded value unavailable") -> str:
    return f'<span class="uq-muted" title="{escape(tr(reason), quote=True)}">—</span>'


def score_label(value: object) -> str | None:
    """Share precision between the ledger and the selected-security detail."""
    number = _finite_number(value)
    if number is None:
        return None
    return f"{number:.4f}" if number == 0 or 0.0001 <= abs(number) < 1e6 else f"{number:.4g}"


def applied_ranking_rows(rows, *, query="", selected_only=False, order="Score ranking", top_n=10):
    """Filter source rows before limiting them, preserving unknown selection.

    Model rank and portfolio weight describe different recorded facts. Sorting
    by weight never creates a model rank, and a missing target is not zero.
    """
    query = query.strip().casefold()
    filtered = [dict(row) for row in rows
                if (not query or query in str(row.get("ticker", "")).casefold()
                    or query in str(row.get("company", "")).casefold())
                and (not selected_only or row.get("selected") is True)]
    if order == "Portfolio weight":
        def key(row):
            weight = _finite_number(row.get("target_weight"))
            return (weight is None, -(weight or 0.0), str(row.get("ticker", "")))
    else:
        def key(row):
            rank = _finite_number(row.get("model_rank"))
            return (rank is None, rank or 0.0, str(row.get("ticker", "")))
    filtered.sort(key=key)
    return filtered if top_n is None else filtered[:top_n]


APPLIED_STOCK_FOCUS_KEY = "applied_stock_ticker"


def _applied_selection_label(row):
    if row.get("selected") is None:
        return tr("Target unavailable")
    if row["selected"]:
        return tr("Recorded holding" if row.get("target_kind") == "RECORDED_EXECUTED_BOOK" else "Selected target")
    return tr("Outside allocation candidates" if row.get("eligible") is False else "Not selected")


def _applied_weight_label(kind):
    return tr({"RECORDED_EXECUTED_BOOK": "Recorded executed book", "RAW_RULE_TARGET": "Raw rule target",
        "CURRENT_CASH_START_TARGET": "Empty-account target", "ARCHIVED_CASH_START_TARGET": "Empty-account target",
        "HISTORICAL_SIGNAL_TARGET": "Historical signal target"}.get(kind, "Unavailable"))


def _applied_coverage_label(status):
    return tr({"SCORED": "Recorded score", "OUTSIDE_RAW_TOP40": "Outside Raw Top40",
        "NO_VERIFIED_SCORE": "Score unavailable", "READY": "Verified target",
        "BLOCKED": "Target blocked", "NO_RECORDED_TARGET": "No recorded target"}.get(status, "Unavailable"))


def _focus_applied_ranking(key, tickers):
    """Only a current table event updates focus; clearing a row preserves it."""
    import streamlit as st

    if key not in st.session_state.get("_applied_ranking_keys", ()):
        return
    observed = st.session_state.get("decision_date")
    if observed is not None and str(observed) != st.session_state.get("_applied_ranking_date"):
        return
    event = st.session_state.get(key, {})
    selection = event.get("selection") if isinstance(event, dict) else None
    rows = selection.get("rows") if isinstance(selection, dict) else None
    if not isinstance(rows, list) or len(rows) != 1 or type(rows[0]) is not int or not 0 <= rows[0] < len(tickers):
        return
    st.session_state[APPLIED_STOCK_FOCUS_KEY] = tickers[rows[0]]


def render_applied_rankings(day, package, raw_model, *, snapshot=None):
    """One observed date, three score/weight ledgers, and one inline stock focus."""
    from functools import partial
    import hashlib
    import json
    import streamlit as st
    from apps.demo_console.adapters import workspace_reader
    # The main page imports this component; resolve its canonical labels lazily.
    from apps.demo_console.pages.selected_strategies import WORKSPACE_STRATEGIES

    snapshot = snapshot if snapshot is not None else workspace_reader.load_applied_rankings(
        day, package=package, raw_model=raw_model)
    st.markdown("#### " + tr("Daily rankings and allocations"))
    st.caption(tr("Observation date: {date}. The two HGB strategies share model scores and ranking; their risk models produce different allocations. Scores across different models are not directly comparable.", date=day))
    coverage = snapshot.get("coverage", {})
    if all(coverage.get(field) is not None for field in ("eligible_count", "mapped_count", "excluded_count")):
        st.caption(tr("Raw score coverage: {scored} / {mapped} mapped securities · {excluded} without a verified score.",
            scored=coverage["eligible_count"], mapped=coverage["mapped_count"],
            excluded=coverage["mapped_count"] - coverage["eligible_count"]))
    controls = st.columns([1, 2, 2, 1.4])
    count_labels = {value: tr("All") if value == "All" else f"Top {value}" for value in (10, 20, 40, "All")}
    order_labels = {value: tr(value) for value in ("Score ranking", "Portfolio weight")}
    count = controls[0].selectbox(tr("Show rows"), (10, 20, 40, "All"),
        format_func=count_labels.__getitem__, key="applied_rank_count")
    query = controls[1].text_input(tr("Ticker or company"), key="applied_rank_query", placeholder=tr("Search all available rows"))
    order = controls[2].selectbox(tr("Sort by"), ("Score ranking", "Portfolio weight"),
        format_func=order_labels.__getitem__, key="applied_rank_order")
    selected_only = controls[3].toggle(tr("Selected only"), key="applied_rank_selected")
    prepared = []
    for strategy_id in WORKSPACE_STRATEGIES:
        leaf = snapshot.get("strategies", {}).get(strategy_id, {})
        rows = applied_ranking_rows(leaf.get("rows", []), query=query,
            selected_only=selected_only, order=order, top_n=None if count == "All" else count)
        digest = hashlib.sha256(json.dumps([day, strategy_id, query, order, count, selected_only,
            [(row.get("ticker"), row.get("security_id")) for row in rows]], ensure_ascii=True).encode()).hexdigest()[:14]
        prepared.append((strategy_id, leaf, rows, "applied_rank_table_" + digest))
    st.session_state["_applied_ranking_keys"] = tuple(item[3] for item in prepared)
    st.session_state["_applied_ranking_date"] = str(day)
    for column, (strategy_id, leaf, rows, key) in zip(st.columns(3), prepared):
        with column:
            st.markdown("**" + tr(WORKSPACE_STRATEGIES[strategy_id]) + "**")
            score_date = leaf.get("actual_signal_date") or "—"
            weight_date = leaf.get("weight_date") or "—"
            scope = {"FULL_VERIFIED_POOL": "Verified full pool", "RAW_TOP40": "Raw Top40 scoring scope",
                "RECORDED_TOP40_ONLY": "Recorded Top40 only", "RECORDED_TOP20_ONLY": "Recorded Top20 only"}.get(leaf.get("scope"), "Unavailable")
            st.caption(tr("Score date: {score} · Weight date: {weight}", score=score_date, weight=weight_date))
            st.caption(tr(scope) + " · " + _applied_weight_label(leaf.get("target_kind")))
            if not rows:
                st.info(tr("No verified rows match these filters." if leaf.get("rows") else "No verified ranking is available for this date."))
                continue
            display = [{"model_rank": _finite_number(row.get("model_rank")),
                "ticker": row["ticker"], "score": _finite_number(row.get("score")),
                "target_weight": _finite_number(row.get("target_weight")),
                "selection": _applied_selection_label(row)} for row in rows]
            st.dataframe(display, hide_index=True, width="stretch", height=365, key=key,
                placeholder="—", column_config={
                    "model_rank": st.column_config.NumberColumn(tr("Rank"), width=48, format="%d", help=tr("Recorded model rank; 1 is best. Sorting by weight does not change this rank.")),
                    "ticker": st.column_config.TextColumn(tr("Ticker"), width=60),
                    "score": st.column_config.NumberColumn(tr("Model score"), width=75, format="%.5f"),
                    "target_weight": st.column_config.NumberColumn(tr("Portfolio weight"), width=80, format="percent"),
                    "selection": None},
                on_select=partial(_focus_applied_ranking, key, tuple(row["ticker"] for row in rows)),
                selection_mode="single-row")
    st.caption(tr("Select one row to inspect the stock below. Search runs before the row limit; an unavailable target is not an unselected stock."))
    return snapshot


def _rank_change(value: object) -> str:
    number = _finite_number(value)
    if number is None:
        return _missing("No previous rank available for comparison")
    count = f"{abs(number):g}"
    if number > 0:
        return (f'<span class="uq-change-up" title="{escape(tr("Improved by {count} rank positions", count=count), quote=True)}">'
                f'↑ +{count}</span>')
    if number < 0:
        return (f'<span class="uq-change-down" title="{escape(tr("Fell by {count} rank positions", count=count), quote=True)}">'
                f'↓ −{count}</span>')
    return f'<span class="uq-muted" title="{escape(tr("Rank unchanged"), quote=True)}">→ 0</span>'


def _score_cell(value: object, bounds: tuple[float, float] | None) -> str:
    number = _finite_number(value)
    if number is None:
        return _missing()
    # Keep four decimals for ordinary values, retaining precision for tiny or huge
    # outputs that fixed formatting would otherwise flatten into zero or overflow.
    label = score_label(number)
    bar = ""
    if bounds is not None:
        low, high = bounds
        # Scaling first avoids overflow when a valid range spans ±1e308.
        scale = max(abs(low), abs(high))
        width = 100 * ((number / scale - low / scale) / (high / scale - low / scale))
        width = max(0.0, min(100.0, width))
        bar = ('<span class="uq-score-track" aria-hidden="true">'
               f'<span class="uq-score-fill" style="width:{width:.2f}%"></span></span>')
    return f'<span class="uq-score-cell"><span>{label}</span>{bar}</span>'


def table_html(rows: tuple[HoldingRow, ...]) -> str:
    """Render all recorded rows, with escaped text and no client-side sorting.

    ``table_records`` intentionally retains its historical pure-data contract.
    Only this display layer hides wholly non-finite numeric columns and formats
    available values; the model and recorded ordering remain unchanged.
    """
    records = table_records(rows)
    if not records:
        return ('<div class="uq-table-empty uq-muted" role="status">'
                f'{escape(tr("No recorded rows are available for this snapshot."))}</div>')
    numeric_columns = {"Rank", "ΔRank", "Score", "Weight"}
    columns = [column for column in records[0]
               if column not in numeric_columns
               or any(_finite_number(record[column]) is not None for record in records)]
    scores = [number for record in records
              if (number := _finite_number(record.get("Score"))) is not None]
    bounds = (min(scores), max(scores)) if scores and min(scores) != max(scores) else None
    titles = {
        "Rank": "Recorded rank; rows follow the recorded rank, not a score recalculation",
        "ΔRank": "Previous recorded rank minus current rank; positive means improved",
        "Score": "Recorded model output; not a probability",
        "Held before": "Whether the ticker was held in the previous portfolio snapshot",
        "Weight": "Recorded portfolio weight, as a fraction",
    }
    header = "".join(
        f'<th scope="col" title="{escape(tr(titles.get(column, column)), quote=True)}">'
        f'{escape(tr(column))}</th>' for column in columns
    )
    body = []
    for record in records:
        cells = []
        for column in columns:
            value = record[column]
            if column == "Ticker":
                cell = f'<span class="uq-ticker">{escape(str(value))}</span>'
            elif column == "Rank":
                number = _finite_number(value)
                cell = f'<span class="uq-rank">{number:g}</span>' if number is not None else _missing()
            elif column == "ΔRank":
                cell = _rank_change(value)
            elif column == "Score":
                cell = _score_cell(value, bounds)
            elif column == "Held before":
                if value is None:
                    cell = _missing("Previous holding status unavailable")
                elif value:
                    cell = f'<span class="uq-pill uq-pill-held">{escape(tr("Previous holding"))}</span>'
                else:
                    cell = f'<span class="uq-pill uq-pill-not-held">{escape(tr("Not held"))}</span>'
            elif column == "Weight":
                number = _finite_number(value)
                cell = f"{number:.4f}" if number is not None else _missing()
            else:
                cell = _missing() if value is None else f'<span class="uq-pill">{escape(str(value))}</span>'
            if column == "Ticker":
                cells.append(f'<th scope="row">{cell}</th>')
            else:
                cells.append(f'<td>{cell}</td>')
        body.append(f'<tr>{"".join(cells)}</tr>')
    notes = ["Sorted by recorded rank." if "Rank" in columns else "Recorded holdings; source order preserved."]
    if "ΔRank" in columns:
        notes.append("ΔRank compares recorded snapshots; — means no previous rank is available.")
    if "Score" in columns:
        notes.append("Scores are model outputs, not probabilities.")
        if bounds is not None:
            notes.append("Bars span the displayed score range, from lowest to highest.")
    if "Held before" in columns:
        notes.append("Held before refers to the previous portfolio snapshot.")
    notes.append("Only available fields are shown; — marks an unavailable value.")
    return (
        '<div class="uq-table-shell"><div class="uq-table-scroll" role="region" '
        f'aria-label="{escape(tr("Recorded rows"), quote=True)}" tabindex="0"><table class="uq-table">'
        f'<thead><tr>{header}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'
        f'<p class="uq-table-note uq-muted">{escape(" ".join(tr(note) for note in notes))}</p></div>'
    )


def render_holding_table(rows: tuple[HoldingRow, ...], *, key: str) -> None:
    """Render the presentation table; keep ``key`` for existing callers."""
    import streamlit as st

    with st.container(key=key):
        st.html(table_html(rows), width="stretch")
