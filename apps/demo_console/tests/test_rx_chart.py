"""Synthetic RX chart comparisons; no source artifacts or market requests."""
from dataclasses import asdict, replace

import pytest

from apps.demo_console.adapters.benchmarks_reader import BenchmarkPoint, BenchmarkSeries
from apps.demo_console.components.performance_charts import wealth_chart
from apps.demo_console.components.performance_stats import PerformanceSummary, WealthPoint


DATES = ("2026-01-05", "2026-01-06", "2026-01-08")


def _summary(values, *, initial=1.0, reference=False):
    return PerformanceSummary(
        observations=len(values), start_date=DATES[0], end_date=DATES[len(values) - 1],
        initial_wealth=initial, reference_available=reference,
        wealth=tuple(WealthPoint(day, value, value + .001, 0.0,
                               1.01 if reference else None, 1.012 if reference else None)
                     for day, value in zip(DATES, values)),
    )


def _markets():
    return tuple(BenchmarkSeries(symbol, symbol, points=tuple(
        BenchmarkPoint(day, 100.0, 0.0, equity + index * .001, 0.0)
        for index, day in enumerate(DATES)))
        for symbol, equity in (("QQQ", 1.02), ("SPY", 1.015)))


def _layer(spec, name):
    return next(layer for layer in spec["layer"] if layer.get("name") == name)


def _fields(spec):
    return _layer(spec, "performance_paths")["transform"][0]["fold"]


def test_rx_adds_four_independent_paths_with_tooltip_and_end_label():
    a2 = _summary((1.001, 1.013, 1.024))
    rx = _summary((.999, 1.014, 1.035))
    original = asdict(a2), asdict(rx)
    spec = wealth_chart(a2, rx_summary=rx, benchmarks=_markets()).to_dict(validate=True)
    fields = _fields(spec)
    assert fields == ["net_wealth", "rx_net_wealth", "benchmark_qqq", "benchmark_spy"]
    rows = spec["data"]["values"]
    assert tuple(row["execution_date"] for row in rows) == DATES
    assert [row["net_wealth"] for row in rows] == [1.001, 1.013, 1.024]
    assert [row["rx_net_wealth"] for row in rows] == [.999, 1.014, 1.035]
    path = _layer(spec, "performance_paths")
    colors = path["encoding"]["color"]["scale"]["range"]
    assert len(set(colors)) == 4
    assert '"rx_net_wealth": "A2 + RX · Net"' in path["encoding"]["color"]["legend"]["labelExpr"]
    tooltip = next(layer["encoding"]["tooltip"] for layer in spec["layer"]
                   if "tooltip" in layer.get("encoding", {}))
    assert any(item["field"] == "rx_net_wealth" and item["title"] == "A2 + RX · Net"
               for item in tooltip)
    labels = _layer(spec, "recorded_end_labels")
    assert any('"A2 + RX"' in transform.get("calculate", "")
               for transform in labels["transform"])
    assert (asdict(a2), asdict(rx)) == original


@pytest.mark.parametrize("kind", ("short", "shift", "reverse"))
def test_rx_refuses_different_execution_dates(kind):
    a2 = _summary((1.001, 1.013, 1.024))
    rx = _summary((.999, 1.014, 1.035))
    if kind == "short":
        rx = replace(rx, wealth=rx.wealth[:-1])
    elif kind == "shift":
        rx = replace(rx, wealth=(replace(rx.wealth[0], execution_date="2026-01-02"), *rx.wealth[1:]))
    else:
        rx = replace(rx, wealth=rx.wealth[::-1])
    with pytest.raises(ValueError, match="dates must match exactly"):
        wealth_chart(a2, rx_summary=rx)


def test_rx_refuses_different_starting_wealth():
    a2 = _summary((1.001, 1.013, 1.024))
    rx = _summary((1.998, 2.028, 2.07), initial=2.0)
    with pytest.raises(ValueError, match="initial wealth must match exactly"):
        wealth_chart(a2, rx_summary=rx)


def test_rx_pair_focus_keeps_original_a2_and_no_frozen_control_replacement():
    a2 = _summary((1.001, 1.013, 1.024), reference=True)
    rx = _summary((.999, 1.014, 1.035))
    full = wealth_chart(a2, rx_summary=rx, benchmarks=_markets(), show_gross=True).to_dict()
    assert _fields(full) == ["net_wealth", "rx_net_wealth", "reference_net_wealth",
                             "gross_wealth", "benchmark_qqq", "benchmark_spy"]
    focus = wealth_chart(a2, rx_summary=rx, benchmarks=_markets(), visible_series=("A2", "RX")).to_dict()
    assert _fields(focus) == ["net_wealth", "rx_net_wealth"]
    assert focus["data"]["values"] == full["data"]["values"]


def test_omitted_rx_preserves_existing_curves():
    a2 = _summary((1.001, 1.013, 1.024), reference=True)
    kwargs = {"benchmarks": _markets(), "show_gross": True}
    original = wealth_chart(a2, **kwargs).to_dict()
    explicit_none = wealth_chart(a2, rx_summary=None, **kwargs).to_dict()
    assert original == explicit_none
    assert _fields(original) == ["net_wealth", "reference_net_wealth", "gross_wealth",
                                 "benchmark_qqq", "benchmark_spy"]
    assert all("rx_net_wealth" not in row for row in original["data"]["values"])
    with pytest.raises(ValueError, match="requires matching RX observations"):
        wealth_chart(a2, visible_series=("A2", "RX"))


def test_curve_focus_offers_and_selects_rx_pair(monkeypatch):
    from apps.demo_console.components import market_benchmarks

    state = {}
    captured = {}

    def select(label, options, **kwargs):
        captured["options"] = options
        return "A2 / RX"

    monkeypatch.setattr(market_benchmarks.st, "session_state", state)
    monkeypatch.setattr(market_benchmarks.st, "segmented_control", select)
    result = market_benchmarks.render_curve_focus("synthetic_rx_focus", available=("RX", "QQQ", "SPY"))
    assert captured["options"] == ("All curves", "A2 / RX", "A2 / QQQ", "A2 / SPY")
    assert result == ("A2", "RX")
    assert state["_synthetic_rx_focus_selected"] == "A2 / RX"
