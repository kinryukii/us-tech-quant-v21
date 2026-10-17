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
            if rank is None:
                rank = _finite_number(row.get("raw_rank"))
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


def _applied_weight_label(kind, *, recorded_score=False, recorded_rank=False):
    label = {"RECORDED_EXECUTED_BOOK": "Recorded executed book", "RAW_RULE_TARGET": "Raw rule target",
        "CURRENT_CASH_START_TARGET": "Empty-account target", "ARCHIVED_CASH_START_TARGET": "Empty-account target",
        "HISTORICAL_SIGNAL_TARGET": "Historical signal target", "CURRENT_ACCOUNT_TARGET": "Current account target",
        "RECORDED_RESEARCH_SIGNAL_PLAN": "Recorded research signal plan"}.get(kind)
    return tr(label or ("Recorded score · target unverified" if recorded_score else
        "Recorded rank · target unverified" if recorded_rank else "Unavailable"))


def _applied_coverage_label(status):
    return tr({"SCORED": "Recorded score", "OUTSIDE_RAW_TOP40": "Outside Raw Top40",
        "NO_VERIFIED_SCORE": "Score unavailable", "READY": "Verified target",
        "BLOCKED": "Target blocked", "NO_RECORDED_TARGET": "No recorded target"}.get(status, "Unavailable"))


def _focus_applied_ranking(key, tickers, identities=None):
    """A current, unambiguous record can change the existing research focus."""
    import streamlit as st

    if key not in st.session_state.get("_applied_ranking_keys", ()):
        return
    observed = st.session_state.get("decision_date")
    if observed is None or str(observed) != st.session_state.get("_applied_ranking_date"):
        return
    event = st.session_state.get(key, {})
    selection = event.get("selection") if isinstance(event, dict) else None
    rows = selection.get("rows") if isinstance(selection, dict) else None
    if not isinstance(rows, list) or len(rows) != 1 or type(rows[0]) is not int or not 0 <= rows[0] < len(tickers):
        return
    index = rows[0]
    if identities is not None:
        from apps.moomoo_trading_component.moomoo_component.strategy import QUERYABLE_STRATEGY_IDS
        identities = tuple(identities)
        if identities != st.session_state.get("_applied_ranking_row_ids") or index >= len(identities):
            return
        identity = identities[index]
        if (not isinstance(identity, tuple) or len(identity) != 10
                or identity[0] != st.session_state.get("_applied_ranking_date")
                or identity[3] != tickers[index] or identities.count(identity) != 1):
            return
        if identity[1] not in QUERYABLE_STRATEGY_IDS:
            from apps.demo_console.pages.selected_strategies import LEGACY_STRATEGIES
            if identity[1] not in LEGACY_STRATEGIES:
                return
        elif st.session_state.get("workspace_strategy") != identity[1]:
            from apps.demo_console.app import _change_strategy
            st.session_state["workspace_strategy"] = identity[1]
            _change_strategy()
        st.session_state["_applied_comparison_focus"] = identity
    st.session_state[APPLIED_STOCK_FOCUS_KEY] = tickers[index]


def applied_ranking_display(leaf, rows):
    """Omit wholly unknown display columns without inventing a rank or weight."""
    if leaf.get("source_kind") == "research":
        display = [{"ticker": row["ticker"], "native_action": row.get("action"),
            "original_policy_weight": _finite_number(row.get("original_policy_weight")),
            "target_weight": _finite_number(row.get("target_weight")),
            "hold_units": _finite_number(row.get("hold_units")),
            "decision_semantic": row.get("decision_semantic"), "selection": _applied_selection_label(row)} for row in rows]
    elif leaf.get("scope") == "RECORDED_FROZEN_MODEL_INPUTS":
        display = [{"ticker": row["ticker"], "raw_input_rank": _finite_number(row.get("raw_rank")),
            "raw_input_score": _finite_number(row.get("raw_score")),
            "native_action_score": _finite_number(row.get("source_score")),
            "native_action": row.get("action"), "target_weight": _finite_number(row.get("target_weight")),
            "selection": _applied_selection_label(row)} for row in rows]
    else:
        display = [{"model_rank": _finite_number(row.get("model_rank")), "ticker": row["ticker"],
            "score": _finite_number(row.get("score")), "target_weight": _finite_number(row.get("target_weight")),
            "selection": _applied_selection_label(row)} for row in rows]
    return [{key: value for key, value in row.items()
             if key == "ticker" or any(item.get(key) is not None for item in display)} for row in display]

def _applied_action_label(code):
    if code is None:
        return None
    return tr({"BUY": "Buy", "SELL": "Sell", "HOLD": "Hold", "TARGET": "Target allocation", "BUY_OR_ADD": "Buy / add",
        "SELL_OR_TRIM": "Sell / reduce", "SELL_OR_REDUCE": "Sell / reduce"}.get(code, str(code)))


def applied_comparison_rows(snapshot, *, day, strategy_ids=None, strategy_labels=None,
                            query="", selected_only=False, order="Score ranking", top_n=10):
    """One display projection; each source keeps its own rank, target and dates."""
    import hashlib
    import json
    from apps.moomoo_trading_component.moomoo_component.strategy import ACTIVE_PAPER_STRATEGY_IDS

    labels = strategy_labels or {}
    selected = ACTIVE_PAPER_STRATEGY_IDS if strategy_ids is None else strategy_ids
    records, identities, groups = [], [], []
    research_kinds = {"RECORDED_RESEARCH_SIGNAL_PLAN", "RAW_RULE_TARGET", "CURRENT_CASH_START_TARGET",
        "ARCHIVED_CASH_START_TARGET", "HISTORICAL_SIGNAL_TARGET"}
    ordered = tuple(ACTIVE_PAPER_STRATEGY_IDS) + tuple(sid for sid in selected if sid not in ACTIVE_PAPER_STRATEGY_IDS)
    for sid in ordered:
        if sid not in selected:
            continue
        leaf = snapshot.get("strategies", {}).get(sid, {})
        if leaf.get("status") == "BLOCKED":
            continue
        rows = applied_ranking_rows(leaf.get("rows", []), query=query, selected_only=selected_only,
            order=order, top_n=top_n)
        kind = leaf.get("target_kind")
        source = {key: leaf.get(key) for key in ("source_kind", "scope", "target_kind",
            "actual_signal_date", "weight_date", "source_refs", "target_source_refs", "source_hashes")}
        start = len(records)
        for row, base in zip(rows, applied_ranking_display(leaf, rows)):
            weight = base.get("target_weight")
            code = row.get("action")
            record = {"strategy": labels.get(sid, sid), "ticker": row["ticker"],
                "recorded_action": _applied_action_label(code),
                "research_target_weight": weight if kind in research_kinds else None,
                "account_target_weight": weight if kind == "CURRENT_ACCOUNT_TARGET"
                    and leaf.get("source_kind") != "research" else None,
                "record_type": _applied_weight_label(kind,
                    recorded_score=any(_finite_number(base.get(key)) is not None
                        for key in ("score", "raw_input_score", "native_action_score")),
                    recorded_rank=any(_finite_number(base.get(key)) is not None
                        for key in ("model_rank", "raw_input_rank"))), "strategy_id": sid,
                "security_id": row.get("security_id"), "signal_date": leaf.get("actual_signal_date"),
                "weight_date": leaf.get("weight_date"), "native_action_code": code,
                "record_type_code": kind, "target_weight": weight,
                **{key: value for key, value in base.items() if key not in ("ticker", "target_weight", "native_action")}}
            fingerprint = hashlib.sha256(json.dumps([source, row], sort_keys=True,
                default=str, ensure_ascii=True).encode()).hexdigest()
            identity = (str(day), sid, row.get("security_id"), row["ticker"], leaf.get("source_kind"),
                leaf.get("scope"), kind, leaf.get("actual_signal_date"), leaf.get("weight_date"), fingerprint)
            records.append(record)
            identities.append(identity)
        groups.append(tuple(zip(records[start:], identities[start:])))
    # Interleave source-local positions; this never compares scores across models.
    pairs = [group[index] for index in range(max(map(len, groups), default=0))
        for group in groups if index < len(group)]
    records = [record for record, _ in pairs]
    identities = [identity for _, identity in pairs]
    mandatory = {"strategy", "ticker", "recorded_action", "research_target_weight", "account_target_weight", "record_type"}
    fields = mandatory | {key for row in records for key, value in row.items() if value is not None}
    return [{key: value for key, value in row.items() if key in fields} for row in records], tuple(identities)


def applied_comparison_columns(display):
    """Show available recorded facts; unknown targets do not hide known scores."""
    candidates = ("strategy", "ticker", "model_rank", "score", "native_action_score",
        "raw_input_rank", "raw_input_score", "recorded_action", "research_target_weight",
        "account_target_weight", "record_type")
    return [key for key in candidates if key in ("strategy", "ticker", "record_type")
        or any(row.get(key) is not None for row in display)]


def render_applied_rankings(day, package, raw_model, *, snapshot=None):
    """One virtualized comparison table over the supplied, qualified snapshot."""
    from functools import partial
    import hashlib
    import json
    import streamlit as st
    from apps.demo_console.components.localized_tabs import localized_expander
    from apps.demo_console.pages.selected_strategies import WORKSPACE_STRATEGIES, LEGACY_STRATEGIES, strategy_label

    if snapshot is None:
        from apps.demo_console.adapters import workspace_reader
        snapshot = workspace_reader.load_applied_rankings(day, package=package, raw_model=raw_model)
    st.caption(tr("Five strategies share one table. Research signals and account targets retain separate weights and dates."))
    strategies = snapshot.get("strategies", {})
    validation_error = snapshot.get("error")
    if validation_error:
        st.warning(tr("Ranking data failed verification. This does not mean this date has no rankings."))
    blocked = [sid for sid, leaf in strategies.items() if leaf.get("status") == "BLOCKED"]
    if blocked:
        st.warning(tr("Unavailable strategies: {names}", names=" · ".join(tr(strategy_label(sid)) for sid in blocked)))
    missing_targets = [sid for sid, leaf in strategies.items() if leaf.get("current_target_status") in ("UNAVAILABLE", "BLOCKED")
        or (leaf.get("target_kind") == "UNAVAILABLE" and (leaf.get("target_status") in ("UNAVAILABLE", "BLOCKED")
            or leaf.get("status") in ("UNAVAILABLE", "BLOCKED")))]
    if missing_targets:
        st.warning(tr("Current PAPER targets unavailable: {names}. Research records are shown separately.",
            names=" · ".join(tr(strategy_label(sid)) for sid in missing_targets)))
    dates = sorted({value for leaf in strategies.values() for value in (leaf.get("actual_signal_date"), leaf.get("weight_date")) if value})
    if dates != [str(day)]:
        st.caption(tr("Record dates: {dates}.", dates=" · ".join(dates) or "—"))
    presentation = bool(st.session_state.get("presentation_mode", True))
    controls_container = (st.popover(tr("Comparison settings"), key="applied_rank_controls")
        if presentation else st.container(key="applied_rank_controls"))
    with controls_container:
        options = tuple(WORKSPACE_STRATEGIES) + tuple(sid for sid in LEGACY_STRATEGIES if sid in strategies)
        labels = {sid: tr(strategy_label(sid)) for sid in options}
        saved = st.session_state.get("applied_rank_strategies", list(options))
        st.session_state["applied_rank_strategies"] = [sid for sid in options if sid in saved] if isinstance(saved, (list, tuple)) else list(options)
        selected_strategies = st.multiselect(tr("Strategies"), options,
            key="applied_rank_strategies", format_func=labels.__getitem__, persist_state="session")
        controls = st.columns([1, 2, 2, 1.4])
        count_labels = {value: tr("All rows per strategy") if value == "All" else tr("{count} rows per strategy", count=value)
            for value in (10, 20, 40, "All")}
        order_labels = {value: tr(value) for value in ("Score ranking", "Portfolio weight")}
        # Reassert canonical selections so translated wire labels reach the browser.
        st.session_state["applied_rank_count"] = (st.session_state.get("applied_rank_count")
            if st.session_state.get("applied_rank_count") in count_labels else 10)
        st.session_state["applied_rank_order"] = (st.session_state.get("applied_rank_order")
            if st.session_state.get("applied_rank_order") in order_labels else "Score ranking")
        count = controls[0].selectbox(tr("Rows per strategy"), (10, 20, 40, "All"), index=None,
            format_func=count_labels.__getitem__, key="applied_rank_count", persist_state="session")
        query = controls[1].text_input(tr("Ticker or company"), key="applied_rank_query", placeholder=tr("Search all available rows"), persist_state="session")
        order = controls[2].selectbox(tr("Sort by"), ("Score ranking", "Portfolio weight"), index=None,
            format_func=order_labels.__getitem__, key="applied_rank_order", persist_state="session")
        selected_only = controls[3].toggle(tr("Selected only"), key="applied_rank_selected", persist_state="session")
    display, identities = applied_comparison_rows(snapshot, day=day, strategy_ids=selected_strategies,
        strategy_labels=labels, query=query, selected_only=selected_only, order=order,
        top_n=None if count == "All" else count)
    digest = hashlib.sha256(json.dumps([str(day), selected_strategies, query, order, count, selected_only,
        identities], ensure_ascii=True).encode()).hexdigest()[:14]
    key = "applied_rank_table_" + digest
    st.session_state["_applied_ranking_keys"] = (key,)
    st.session_state["_applied_ranking_date"] = str(day)
    st.session_state["_applied_ranking_row_ids"] = identities
    if display:
        row_height = 44 if presentation else 36
        st.dataframe(display, hide_index=True, width="stretch",
            height=min(420, 40 + row_height * len(display)), row_height=row_height, key=key,
            column_order=applied_comparison_columns(display),
            placeholder="—", column_config={
                "strategy": st.column_config.TextColumn(tr("Strategy"), width=165),
                "ticker": st.column_config.TextColumn(tr("Ticker"), width=80),
                "recorded_action": st.column_config.TextColumn(tr("Recorded action"), width=100),
                "research_target_weight": st.column_config.NumberColumn(tr("Research target weight"), width=100, format="percent"),
                "account_target_weight": st.column_config.NumberColumn(tr("Account target weight"), width=100, format="percent"),
                "record_type": st.column_config.TextColumn(tr("Record type"), width=165),
                "strategy_id": st.column_config.TextColumn(tr("Strategy ID")),
                "security_id": st.column_config.TextColumn(tr("Security identity (CUSIP)")),
                "signal_date": st.column_config.TextColumn(tr("Signal date")),
                "weight_date": st.column_config.TextColumn(tr("Weight date")),
                "model_rank": st.column_config.NumberColumn(tr("Rank"), format="%d", help=tr("Recorded model rank; 1 is best. Sorting by weight does not change this rank.")),
                "score": st.column_config.NumberColumn(tr("Model score"), format="%.5f"),
                "target_weight": st.column_config.NumberColumn(tr("Original recorded weight"), format="percent"),
                "original_policy_weight": st.column_config.NumberColumn(tr("Policy weight (research action)"), format="percent"),
                "hold_units": st.column_config.NumberColumn(tr("Recorded HOLD units")),
                "decision_semantic": st.column_config.TextColumn(tr("Recorded order semantic")),
                "raw_input_rank": st.column_config.NumberColumn(tr("Raw input rank"), format="%d"),
                "raw_input_score": st.column_config.NumberColumn(tr("Raw input score"), format="%.5f"),
                "native_action_score": st.column_config.NumberColumn(tr("Native action score"), format="%.5f"),
                "native_action_code": st.column_config.TextColumn(tr("Recorded action code")),
                "record_type_code": st.column_config.TextColumn(tr("Record type code")), "selection": None},
            on_select=partial(_focus_applied_ranking, key, tuple(row["ticker"] for row in display), identities),
            selection_mode="single-row")
    elif not blocked:
        absent = bool(selected_strategies) and not any(strategies.get(sid, {}).get("rows") for sid in selected_strategies)
        st.info(tr("Ranking unavailable until verification passes." if validation_error else
            "No verified ranking is available for this date." if absent else "No verified rows match these filters."))
    st.caption(tr("Select one row to inspect the stock below. Search runs before the row limit; an unavailable target is not an unselected stock."))
    focus = st.session_state.get("_applied_comparison_focus")
    if focus in identities:
        record = display[identities.index(focus)]
        st.caption(tr("Selected record: {strategy} · {ticker}", strategy=record["strategy"], ticker=record["ticker"]))
        detail = localized_expander("Selected record details", key="applied_comparison_record")
        if detail.open:
            with detail:
                st.json(record)
    sources = localized_expander("Source and coverage", key="applied_rank_sources")
    if sources.open:
        with sources:
            st.caption(tr("Record dates: {dates}.", dates=" · ".join(dates) or "—"))
            st.caption(tr("Observation date: {date}. Each strategy shows its recorded model scores and target allocations. Scores across different models are not directly comparable.", date=day))
            coverage = snapshot.get("coverage", {})
            if all(coverage.get(field) is not None for field in ("eligible_count", "mapped_count", "excluded_count")):
                st.caption(tr("Raw score coverage: {scored} / {mapped} mapped securities · {excluded} without a verified score.",
                    scored=coverage["eligible_count"], mapped=coverage["mapped_count"], excluded=coverage["mapped_count"] - coverage["eligible_count"]))
            if any(leaf.get("source_kind") == "research" for leaf in strategies.values()):
                st.caption(tr("Recorded MAIN research signal. This is not a current PAPER account target."))
                st.caption(tr("No stock ranking or model score was recorded in this research ledger."))
            if any(leaf.get("scope") == "RECORDED_FROZEN_MODEL_INPUTS" for leaf in strategies.values()):
                st.caption(tr("Rows follow recorded Raw input ranks for these action models. Native action scores do not define a stock ranking."))
            for sid, leaf in strategies.items():
                st.markdown("**" + tr(strategy_label(sid)) + "** · " + _applied_weight_label(leaf.get("target_kind")))
                st.caption(tr("Score date: {score} · Weight date: {weight}",
                    score=leaf.get("actual_signal_date") or "—", weight=leaf.get("weight_date") or "—"))
                if leaf.get("paper_plan_signal_date"):
                    st.caption(tr("Latest PAPER target signal: {date}. The selected-date research record is shown separately.", date=leaf["paper_plan_signal_date"]))
                if leaf.get("error"):
                    st.code(str(leaf["error"])[:12288], language=None)
            if validation_error:
                st.code(str(validation_error)[:12288], language=None)
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
