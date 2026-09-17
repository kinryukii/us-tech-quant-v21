"""History charts from immutable display snapshots, without financial reconstruction."""
from __future__ import annotations

import json
from math import isfinite

import altair as alt

from apps.demo_console.models import DecisionOverview
from apps.demo_console.i18n import tr

_PRIMARY = "#739bff"
_AMBER = "#e3af70"


def _ordered(history):
    return sorted((item for item in history if item.decision_date),
                  key=lambda item: item.decision_date)


def _finite(value):
    return value is not None and not isinstance(value, bool) and isfinite(value)


def _recorded_domain(records, field, *, zero):
    """Keep axes finite during Streamlit's initial empty-dataset render.

    Only finite observed coordinates and an intentional bar/turnover baseline
    contribute. [0, 0] is a hidden-axis fallback, never an observation.
    """
    values = [record[field] for record in records if _finite(record[field])]
    if zero and values:
        values.append(0)
    return [min(values), max(values)] if values else [0, 0]


def _portfolio_available(model):
    return (not model.error and bool(model.holdings)
            and any(stage.name == "Portfolio" and stage.status == "AVAILABLE"
                    for stage in model.pipeline))


def _segments(records, field):
    """Group contiguous recorded runs before missing points are filtered for drawing."""
    segment, previous_valid = 0, False
    for record in records:
        valid = record[field] is not None
        if valid and not previous_valid:
            segment += 1
        record[f"{field}_segment"] = segment
        previous_valid = valid


def _display_field(records, field):
    """Add translated labels only to chart copies; internal status keys stay intact."""
    if not any(tr(record[field]) != record[field] for record in records):
        return field
    translated_field = f"{field}_label"
    for record in records:
        record[translated_field] = tr(record[field])
    return translated_field


def _legend_labels(labels):
    return f"{json.dumps({label: tr(label) for label in labels}, ensure_ascii=True)}[datum.label]"


def security_records(history: tuple[DecisionOverview, ...], ticker: str) -> list[dict]:
    """Expose recorded Top20 coordinates and independently verified holdings state.

    An absent name has no exposed rank. Portfolio availability is independent of
    ranking availability; neither membership nor execution causes are inferred.
    """
    records = []
    for model in _ordered(history):
        ranking_available = not model.error and bool(model.ranking)
        row = next((item for item in model.ranking if item.ticker == ticker), None)
        held = (any(item.ticker == ticker for item in model.holdings)
                if _portfolio_available(model) else None)
        status = "Unavailable"
        if held is not None:
            if ticker in (model.entered or ()):
                status = "Entered"
            elif ticker in (model.retained or ()):
                status = "Retained"
            elif ticker in (model.exited or ()):
                status = "Exited"
            else:
                status = "Held" if held else "Not held"
        rank = row.rank if ranking_available and row is not None else None
        score = row.score if ranking_available and row is not None else None
        records.append({
            "decision_date": model.decision_date,
            "execution_date": model.provenance.execution_date,
            "rank": rank if isinstance(rank, int) and not isinstance(rank, bool) else None,
            "score": score if _finite(score) else None,
            "held": held,
            "status": status,
            "ranking_status": ("Unavailable" if not ranking_available else
                               "Recorded" if row is not None else "Outside Top20"),
        })
    _segments(records, "rank")
    _segments(records, "score")
    return records


def _x(records, *, show_axis=True):
    dates = list(dict.fromkeys(row["decision_date"] for row in records))
    label_expression = ("substring(datum.label, 0, 7)"
                        if len({day[:4] for day in dates}) > 1 else
                        "substring(datum.label, 5)")
    count = min(len(dates), 6)
    ticks = ([dates[round(index * (len(dates) - 1) / (count - 1))]
              for index in range(count)] if count > 1 else dates)
    return alt.X(
        "decision_date:O", sort=dates, title=tr("Decision date"),
        scale=alt.Scale(domain=dates, padding=0.25),
        axis=(alt.Axis(values=ticks, labelExpr=label_expression,
                       labelAngle=0, grid=False) if show_axis else None),
    )


def _style(chart, *, height=235):
    properties = {"background": "#11151e"}
    if height is not None:
        properties["height"] = height
    return (chart.properties(**properties)
            .configure_view(stroke=None)
            .configure_axis(
                labelColor="#9aa6ba", titleColor="#c5cfdf",
                labelFont="Segoe UI", titleFont="Segoe UI", labelFontSize=13,
                titleFontSize=13, titleFontWeight="normal", titlePadding=12,
                labelPadding=7, domain=False, ticks=False,
                gridColor="#252e3d", gridWidth=.7,
            )
            .configure_legend(labelColor="#9aa6ba", labelFont="Segoe UI",
                              labelFontSize=13, title=None, orient="top"))


def portfolio_chart(history: tuple[DecisionOverview, ...], metric: str = "changes"):
    """Show observed holding-name changes or later executed turnover by signal date."""
    if metric not in {"changes", "turnover"}:
        raise ValueError("Portfolio metric must be 'changes' or 'turnover'.")
    records = []
    for model in _ordered(history):
        available = _portfolio_available(model)
        records.append({
            "decision_date": model.decision_date,
            "execution_date": model.provenance.execution_date,
            "entered": len(model.entered) if available and model.entered is not None else None,
            "exited": len(model.exited) if available and model.exited is not None else None,
            "turnover": model.turnover if available and _finite(model.turnover) else None,
        })
    tooltip = [alt.Tooltip("decision_date:N", title=tr("Decision date")),
               alt.Tooltip("execution_date:N", title=tr("Execution date"))]
    if metric == "turnover":
        _segments(records, "turnover")
        chart = (alt.Chart(alt.Data(values=records))
                 .transform_filter(alt.datum.turnover != None)
                 .mark_line(color=_PRIMARY, strokeWidth=2, point={"filled": True, "size": 32, "color": _PRIMARY})
                 .encode(x=_x(records),
                         y=alt.Y("turnover:Q", title=tr("Executed turnover"),
                                 scale=alt.Scale(domain=_recorded_domain(records, "turnover", zero=True), zero=True),
                                 axis=alt.Axis(format=".0%", tickCount=4)
                                 if any(record["turnover"] is not None for record in records) else None),
                         detail="turnover_segment:N",
                         tooltip=tooltip + [alt.Tooltip("turnover:Q", title=tr("Executed turnover"), format=".2%")]))
    else:
        changes = []
        for record in records:
            for field, label, sign in (("entered", "Entered", 1), ("exited", "Exited", -1)):
                changes.append({**record, "change": label,
                                "count": record[field],
                                "signed_count": sign * record[field] if record[field] is not None else None})
        change_field = _display_field(changes, "change")
        chart = (alt.Chart(alt.Data(values=changes))
                 .mark_bar(cornerRadius=2)
                 .encode(x=_x(records),
                         y=alt.Y("signed_count:Q", title=tr("Holding names"), stack=None,
                                 scale=alt.Scale(domain=_recorded_domain(changes, "signed_count", zero=True), zero=True),
                                 axis=alt.Axis(tickMinStep=1, labelExpr="abs(datum.value)")
                                 if any(record["signed_count"] is not None for record in changes) else None),
                         color=alt.Color("change:N", title=None,
                                         scale=alt.Scale(domain=["Entered", "Exited"], range=[_PRIMARY, _AMBER]),
                                         legend=alt.Legend(labelExpr=_legend_labels(["Entered", "Exited"]))),
                         tooltip=tooltip + [alt.Tooltip(f"{change_field}:N", title=tr("Snapshot change")),
                                            alt.Tooltip("count:Q", title=tr("Names"), format="d")]))
    return _style(chart)


def security_chart(history: tuple[DecisionOverview, ...], ticker: str, metric: str = "rank"):
    """Plot actual Top20 rank or model score; disconnected segments retain absence."""
    if metric not in {"rank", "score"}:
        raise ValueError("Security metric must be 'rank' or 'score'.")
    records = [{**record,
                "score_label": (format(record["score"], ".6g")
                                if record["score"] is not None else tr("Not recorded")),
                "holdings_state": ("Held" if record["held"] is True else
                                   "Not held" if record["held"] is False else "Unavailable")}
               for record in security_records(history, ticker)]
    ranking_field = _display_field(records, "ranking_status")
    status_field = _display_field(records, "status")
    holdings_field = _display_field(records, "holdings_state")
    tooltip = [alt.Tooltip("decision_date:N", title=tr("Decision date")),
               alt.Tooltip("execution_date:N", title=tr("Execution date")),
               alt.Tooltip("rank:Q", title=tr("Recorded rank"), format="d"),
               alt.Tooltip("score_label:N", title=tr("Recorded score")),
               alt.Tooltip(f"{ranking_field}:N", title=tr("Ranking evidence")),
               alt.Tooltip(f"{status_field}:N", title=tr("Holdings state"))]
    y = (alt.Y("rank:Q", title=tr("Top20 rank · 1 is highest"),
               scale=alt.Scale(domain=[20, 1], zero=False),
               axis=alt.Axis(values=[1, 5, 10, 15, 20], format="d"))
         if metric == "rank" else
         alt.Y("score:Q", title=tr("Recorded model score"),
               scale=alt.Scale(domain=_recorded_domain(records, "score", zero=False), zero=False),
               axis=alt.Axis(format=".3~g", tickCount=4)
               if any(record["score"] is not None for record in records) else None))
    chart = (alt.Chart(alt.Data(values=records))
             .transform_filter(alt.FieldValidPredicate(field=metric, valid=True))
             .mark_line(color=_PRIMARY, strokeWidth=2, point={"filled": True, "size": 36, "color": _PRIMARY})
             .encode(x=_x(records, show_axis=metric != "rank"), y=y,
                     detail=f"{metric}_segment:N", tooltip=tooltip))
    if metric == "score":
        return _style(chart)
    holdings = (alt.Chart(alt.Data(values=records))
                .mark_rect(cornerRadius=1)
                .encode(
                    x=_x(records),
                    color=alt.Color("holdings_state:N", title=None,
                                    scale=alt.Scale(domain=["Held", "Not held", "Unavailable"],
                                                    range=[_PRIMARY, "#1b2535", "#8f9db3"]),
                                    legend=alt.Legend(orient="bottom", direction="horizontal",
                                                      symbolType="square", offset=10,
                                                      labelExpr=_legend_labels(["Held", "Not held", "Unavailable"]))),
                    tooltip=[alt.Tooltip("decision_date:N", title=tr("Decision date")),
                             alt.Tooltip("execution_date:N", title=tr("Execution date")),
                             alt.Tooltip(f"{holdings_field}:N", title=tr("Holdings state")),
                             alt.Tooltip(f"{status_field}:N", title=tr("Snapshot change"))],
                ).properties(height=12))
    combined = alt.vconcat(
        chart.properties(height=170, data=alt.Undefined),
        holdings.properties(data=alt.Undefined),
        data=alt.Data(values=records), spacing=7,
    ).resolve_scale(x="shared")
    return _style(combined, height=None)
