"""Pixel-only endpoint labels over the chart's existing observations."""
import json
import math

import altair as alt


LINE_LABEL_GUTTER = 154


def line_label_x_range():
    """Reserve an in-frame label column without extending the date domain."""
    return [0, alt.ExprRef(expr=f"max(48, width - {LINE_LABEL_GUTTER})")]


def line_end_labels(base, *, date_field, value_field, end_date, endpoints,
                    series_field="series", label_names=None, number_format=".2f"):
    """Return leaders/text; only their pixel positions can differ from the data.

    ``base`` may already fold a wide table. It must encode the shared x/y scales
    and series colors. ``endpoints`` contains the actual last observed values;
    it supplies ordering only, while the displayed number comes from each row.
    The chart must reserve ``line_label_x_range()`` in its temporal scale.
    """
    if not endpoints or any(not math.isfinite(value) for value in endpoints.values()):
        raise ValueError("Endpoint labels require finite recorded values")
    ordered = sorted(endpoints, key=lambda key: -endpoints[key])
    count, margin, gap = len(ordered), 11, 22
    series = f"datum[{json.dumps(series_field)}]"
    y_positions = []
    for index, key in enumerate(ordered):
        # Forward packing followed by an upper bound for each rank preserves
        # the minimum separation, including ties at zero drawdown. Expressions
        # use the current Vega height, so native fullscreen needs no rerun.
        targets = [str(margin + index * gap)] + [
            f"scale('y', {json.dumps(endpoints[previous])}) + {(index - offset) * gap}"
            for offset, previous in enumerate(ordered[:index + 1])]
        position = f"min(max({', '.join(targets)}), height - {margin + (count - 1 - index) * gap})"
        y_positions.append(f"{series} === {json.dumps(key)} ? ({position}) : ")
    labels = label_names or {}
    names = "".join(f"{series} === {json.dumps(key)} ? {json.dumps(labels.get(key, key))} : "
                    for key in ordered) + series
    end = (base.transform_filter(
        f"toNumber(toDate(datum[{json.dumps(date_field)}])) === toNumber(toDate({json.dumps(end_date)}))")
        .transform_filter(alt.FieldOneOfPredicate(field=series_field, oneOf=ordered))
        .transform_calculate(
            _uq_end_y="".join(y_positions) + "0",
            _uq_end_text=f"({names}) + ' ' + format(datum[{json.dumps(value_field)}], {json.dumps(number_format)})"))
    label_x = alt.ExprRef(expr=f"max(48, width - {LINE_LABEL_GUTTER}) + 14")
    leaders = (end.mark_rule(aria=False).encode(
        x2=alt.value(alt.ExprRef(expr=f"max(48, width - {LINE_LABEL_GUTTER}) + 9")),
        y2=alt.value(alt.ExprRef(expr="datum._uq_end_y")),
        strokeWidth=alt.value(1), strokeDash=alt.value([1, 0]), opacity=alt.value(.5))
        .properties(name="recorded_end_leaders"))
    text = (end.mark_text(align="left", baseline="middle", font="Segoe UI", fontSize=15,
                          fontWeight=600).encode(
        x=alt.value(label_x), y=alt.value(alt.ExprRef(expr="datum._uq_end_y")),
        text=alt.Text("_uq_end_text:N"), color=alt.value("#27364b"),
        strokeWidth=alt.Undefined, strokeDash=alt.Undefined, opacity=alt.value(1))
        .properties(name="recorded_end_labels"))
    # encode(..., Undefined) preserves an existing channel in Altair. Remove
    # line-only channels explicitly so Vega never tries to project them to text.
    text.encoding.strokeWidth = alt.Undefined
    text.encoding.strokeDash = alt.Undefined
    return leaders, text
