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
