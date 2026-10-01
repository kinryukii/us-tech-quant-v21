"""Main Research behavior from bound NAV snapshots; source reads stay explicit."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
import os

import pyarrow as pa
import pytest

from apps.demo_console.adapters import selected_strategies_reader as reader
from apps.demo_console.components.performance_charts import nav_comparison_chart
from apps.demo_console.pages import research
from apps.demo_console.tests.test_selected_strategies import package as base_package


def _package():
    payload = base_package()
    dates = ("2026-01-05", "2026-01-06", "2026-08-18")
    payload["performance_period"].update(start=dates[0], end=dates[-1], days=3)
    for sid, navs, cash in (
        ("HGB_DIAG_5", (.99, 1.089, 1.1979), (.2, .1, .3)),
        ("HGB_FACTOR_5", (1.0, .95, 1.14), (.7, .6, .8)),
    ):
        strategy = payload["strategies"][sid]
        strategy["daily"] = [{"date": day, "nav": nav, "cash_weight": weight}
                             for day, nav, weight in zip(dates, navs, cash)]
        strategy["summary"].update(end_nav=navs[-1], cumulative_return=navs[-1] - 1,
            max_drawdown=-.01 if sid == "HGB_DIAG_5" else -.05,
            mean_cash=sum(cash) / 3, days=3)
        strategy["application"]["signal_date"] = "2026-09-24"
    payload["generated_at"] = "2026-09-24T01:00:00+00:00"
    return reader.validate_package(payload)


def _forbidden(*args, **kwargs):
    raise AssertionError("Research detail must not bypass its shared applied-strategy snapshot")


def _applied_contexts(day, *, package, sample="test_2026"):
    """Thin synthetic aggregation; optional RAW keeps an earlier actual NAV."""
    import streamlit as st
    contexts = {sid: reader.workspace_view(sid, day, package=package) for sid in reader.STRATEGY_IDS}
    contexts["RAW_A2"] = {"strategy_id": "RAW_A2", "history": {"daily": [], "summary": None},
                          "target": {"kind": "UNAVAILABLE", "rows": []}, "error": "Raw evidence unavailable"}
    if st.session_state.get("with_raw"):
        raw = [{"date": recorded, "nav": nav, "cash_weight": cash} for recorded, nav, cash in (
            ("2026-01-02", .8, .8), ("2026-01-05", .88, .4), ("2026-01-06", .968, .3),
            ("2026-08-18", 1.0648, .2), ("2026-09-24", 10.648, .1)) if recorded <= day]
        if st.session_state.get("raw_missing_date"):
            raw = [row for row in raw if row["date"] != "2026-01-06"]
        contexts["RAW_A2"] = {"strategy_id": "RAW_A2", "history": {"daily": raw}, "error": None}
    return contexts


def _hgb_page(package_path=None):
    from unittest.mock import patch
    import streamlit as st
    from apps.demo_console.adapters import selected_strategies_reader as reader
    from apps.demo_console.i18n import language_scope
    from apps.demo_console.models import DecisionOverview
    from apps.demo_console.adapters.benchmarks_reader import BenchmarkHistory
    from apps.demo_console.tests.test_hgb_research_workspace import _package, _forbidden, _applied_contexts
    from apps.demo_console.pages import research

    st.selectbox("Workspace strategy", ("RAW_A2", *reader.STRATEGY_IDS), index=1, key="workspace_strategy")
    st.session_state["workspace_sample"] = "test_2026"
    st.selectbox("Language", ("en", "zh", "ja"), key="language")
    st.selectbox("Observation", ("2026-09-24", "2026-01-06", "2025-12-31"), key="decision_date")
    # The source identity intentionally carries no RAW provenance or metadata.
    model = DecisionOverview(decision_date="2026-09-24", source_id="SELECTED_HGB",
                             performance_cutoff_date="2025-01-01")
    package = _package() if package_path is None else reader.load_package(package_path)
    if st.session_state.get("broken_package"):
        package["strategies"]["HGB_DIAG_5"]["summary"]["end_nav"] = -1
    with language_scope(st.session_state["language"]), patch.object(research, "read_performance", _forbidden), \
            patch.object(research.workspace_reader, "load_applied_strategies", _applied_contexts), \
            patch.object(research.workspace_reader, "read_performance", _forbidden), \
            patch.object(research.rx_research_reader, "read", _forbidden), \
            patch.object(research, "read_benchmarks", _forbidden), \
            patch.object(research, "read_updated_benchmarks", return_value=BenchmarkHistory()), \
            patch.object(reader, "load_package", _forbidden):
        research.render_research(model, presentation=True, selected_package=package)


def _summary(app):
    from apps.demo_console.i18n import language_scope, tr
    language = next((item.value for item in app.selectbox if item.key == "language"), "en")
    with language_scope(language):
        column = tr("Period return")
    return next(item.value for item in app.dataframe if column in item.value.columns)


def _comparison_values(app):
    from apps.demo_console.i18n import language_scope, tr
    from apps.demo_console.pages.selected_strategies import WORKSPACE_STRATEGIES
    language = next((item.value for item in app.selectbox if item.key == "language"), "en")
    with language_scope(language):
        frame = _summary(app).set_index(tr("Strategy"))
        fields = [tr(name) for name in ("Period return", "Maximum window drawdown", "Historical average cash")]
        result = {}
        for sid in reader.STRATEGY_IDS:
            values = tuple(frame.loc[tr(WORKSPACE_STRATEGIES[sid]), fields])
            result[sid] = (f"{float(values[0].rstrip('%')):+.2f}%", *values[1:])
        return result


def _chart(app, name):
    key = {"research_hgb_comparison_chart":"research_hgb_nav",
           "research_hgb_drawdown_chart":"research_hgb_drawdown"}.get(name,name)
    for element in app.get("vega_lite_chart"):
        if json.loads(element.proto.spec).get("name") == key:
            spec = json.loads(element.proto.spec)
            payloads = [element.proto.data.data, *(dataset.data.data for dataset in element.proto.datasets)]
            rows = [row for payload in payloads if payload
                    for row in pa.ipc.open_stream(payload).read_all().to_pylist() if "series" in row]
            def inline(node):
                if isinstance(node,dict):
                    for key,value in node.items():
                        if isinstance(value,list) and value and isinstance(value[0],dict) and "series" in value[0]:
                            rows.extend(row for row in value if isinstance(row,dict) and "series" in row)
                        else: inline(value)
                elif isinstance(node,list):
                    for item in node: inline(item)
            inline(spec)
            return spec, rows
    raise AssertionError(f"Chart {key} was not rendered")


def test_main_hgb_metrics_and_charts_switch_policy_without_raw_identity_or_future_records():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(_hgb_page, default_timeout=30).run()
    assert not app.exception and not app.error
    expected = {"HGB_DIAG_5": ("+19.79%", "-1.00%", "20.00%"), "HGB_FACTOR_5": ("+14.00%", "-5.00%", "70.00%")}
    assert _comparison_values(app) == expected
    assert _summary(app).iloc[0]["Strategy"] == "Raw A2"
    assert _summary(app).iloc[0]["Period return"] == "—"
    assert not app.tabs and not app.metric
    spec, rows = _chart(app,"research_hgb_comparison_chart")
    assert spec["layer"][0]["encoding"]["x"]["scale"]["domain"] == ["2026-01-05","2026-08-18"]
    assert len(rows) == 6
    assert len(_chart(app,"research_hgb_drawdown_chart")[1]) == 6
    for focus in ("HGB_FACTOR_5","RAW_A2","HGB_DIAG_5"):
        app.selectbox(key="workspace_strategy").select(focus).run()
        assert not app.exception and not app.error
        assert _comparison_values(app) == expected
        assert _chart(app,"research_hgb_comparison_chart")[1] == rows


def test_single_record_returns_use_preceding_nav_and_strategy_switch_keeps_valid_dates():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(_hgb_page, default_timeout=30).run()
    app.selectbox(key="research_range").select("Single date").run()
    assert not app.exception and not app.error
    assert app.selectbox(key="research_single_date").value == "2026-08-18"
    values = _comparison_values(app)
    assert values == {"HGB_DIAG_5": ("+10.00%", "0.00%", "30.00%"),
                      "HGB_FACTOR_5": ("+20.00%", "0.00%", "80.00%")}
    spec, rows = _chart(app, "research_hgb_comparison_chart")
    assert len(rows) == 2 and {row["execution_date"] for row in rows} == {"2026-08-18"}
    assert spec["layer"][0]["encoding"]["x"]["scale"]["domain"] == ["2026-08-17", "2026-08-19"]
    app.selectbox(key="workspace_strategy").select("HGB_FACTOR_5").run()
    assert not app.exception and not app.error
    assert _comparison_values(app) == values


def test_observation_cutoff_replaces_old_results_and_prearchive_has_no_raw_substitute():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(_hgb_page, default_timeout=30).run()
    app.selectbox(key="decision_date").select("2026-01-06").run()
    assert not app.exception and not app.error
    assert _comparison_values(app) == {"HGB_DIAG_5": ("+8.90%", "-1.00%", "15.00%"),
                                       "HGB_FACTOR_5": ("-5.00%", "-5.00%", "65.00%")}
    spec, rows = _chart(app, "research_hgb_comparison_chart")
    assert spec["layer"][0]["encoding"]["x"]["scale"]["domain"] == ["2026-01-05", "2026-01-06"]
    assert {row["execution_date"] for row in rows} == {"2026-01-05", "2026-01-06"}
    app.selectbox(key="decision_date").select("2025-12-31").run()
    assert not app.exception and not app.error and not app.get("vega_lite_chart")
    assert not app.metric
    assert any("No recorded HGB performance" in row.value for row in app.info)
    app.selectbox(key="decision_date").select("2026-09-24").run()
    assert not app.exception and not app.error and _comparison_values(app)["HGB_DIAG_5"][0] == "+19.79%"


def test_custom_calendar_selection_counts_only_recorded_navs_and_keeps_first_included_return():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(_hgb_page, default_timeout=30).run()
    app.selectbox(key="research_range").select("Custom dates").run()
    app.date_input(key="research_dates_draft").set_value((date(2026, 1, 6), date(2026, 8, 18)))
    app.button(key="research_dates_apply").click().run()
    assert not app.exception and not app.error
    assert _comparison_values(app) == {"HGB_DIAG_5": ("+21.00%", "0.00%", "20.00%"),
                                       "HGB_FACTOR_5": ("+14.00%", "-5.00%", "70.00%")}
    _, rows = _chart(app, "research_hgb_comparison_chart")
    assert len(rows) == 4 and {row["execution_date"] for row in rows} == {"2026-01-06", "2026-08-18"}
    app.selectbox(key="research_range").select("Calendar month").run()
    app.selectbox(key="research_calendar_month").select("2026-08").run()
    assert not app.exception and not app.error and _comparison_values(app)["HGB_DIAG_5"][0] == "+10.00%"
    assert any("incomplete month or quarter" in item.value for item in app.caption)


def test_invalid_snapshot_is_blocked_without_fallback_or_previous_chart():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(_hgb_page, default_timeout=30).run()
    app.session_state["broken_package"] = True
    app.run()
    assert not app.exception and len(app.error) == 1
    assert "no RAW result is substituted" in app.error[0].value
    assert not app.get("vega_lite_chart") and not app.tabs
    app.session_state["broken_package"] = False
    app.run()
    assert not app.exception and not app.error and _comparison_values(app)["HGB_DIAG_5"][0] == "+19.79%"


def test_available_raw_is_a_third_common_window_card_without_future_gain_or_missing_date_fill():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(_hgb_page,default_timeout=30)
    app.session_state["with_raw"] = True
    app.run()
    assert not app.exception and not app.error
    assert _summary(app).iloc[0]["Period return"] == "33.10%"
    assert _summary(app).iloc[0]["Maximum window drawdown"] == "0.00%"
    assert _summary(app).iloc[0]["Historical average cash"] == "30.00%"
    _,rows = _chart(app,"research_hgb_comparison_chart")
    assert len(rows) == 9 and rows[2]["value"] == pytest.approx(1.331)
    original = _summary(app).copy()
    for focus in ("HGB_FACTOR_5","RAW_A2"):
        app.selectbox(key="workspace_strategy").select(focus).run()
        assert _summary(app).equals(original)
    app.selectbox(key="research_range").select("Custom dates").run()
    app.date_input(key="research_dates_draft").set_value((date(2026,1,6),date(2026,8,18)))
    app.button(key="research_dates_apply").click().run()
    assert not app.exception and not app.error
    assert _summary(app).iloc[0]["Period return"] == "21.00%"
    spec,rows = _chart(app,"research_hgb_comparison_chart")
    assert len(rows) == 6 and spec["layer"][0]["encoding"]["x"]["scale"]["domain"] == ["2026-01-06","2026-08-18"]
    app.session_state["raw_missing_date"] = True
    app.run()
    assert not app.exception and not app.error
    assert len(_chart(app,"research_hgb_comparison_chart")[1]) == 4
    assert _summary(app).iloc[0]["Period return"] == "—"
    assert any("RAW is omitted" in item.value for item in app.caption)


def _raw_page():
    from types import SimpleNamespace
    from unittest.mock import patch
    import streamlit as st
    from apps.demo_console.adapters import workspace_reader
    from apps.demo_console.adapters import selected_strategies_reader as reader
    from apps.demo_console.adapters.benchmarks_reader import BenchmarkHistory
    from apps.demo_console.i18n import language_scope
    from apps.demo_console.models import DecisionOverview, PerformanceHistory, PerformancePoint
    from apps.demo_console.pages import research
    from apps.demo_console.tests.test_hgb_research_workspace import _package, _forbidden, _applied_contexts

    st.session_state["workspace_strategy"] = "RAW_A2"
    st.session_state["workspace_source"] = workspace_reader.LATEST
    st.session_state["workspace_sample"] = "test_2026"
    st.session_state["with_raw"] = True
    st.session_state["decision_date"] = "2026-09-24"
    points, previous = [], 1.0
    for day, nav in (("2025-12-31", .8), ("2026-01-05", .88),
                     ("2026-01-06", .968), ("2026-08-18", 1.0648), ("2026-09-24", 10.648)):
        net = nav / previous - 1
        points.append(PerformancePoint(execution_date=day, nav=nav, net_return=net,
            gross_return=net + .001 / previous, transaction_cost=.001, turnover=.1,
            cash=.2 * nav, position_value=.8 * nav, holding_count=10, stale_mark_count=0,
            skipped_buy_count=0, blocked_rebalance_count=0, buy_cash_scale=1))
        previous = nav
    history = PerformanceHistory(points=tuple(points), available_dates=tuple(p.execution_date for p in points),
        archive_start=points[0].execution_date, archive_end=points[-1].execution_date,
        initial_nav=1.0, reference_available=False)
    model = DecisionOverview(decision_date="2026-09-24", source_id=workspace_reader.LATEST,
                             performance_cutoff_date="2026-09-24")
    with language_scope("en"), patch.object(workspace_reader, "read_performance", return_value=history), \
            patch.object(workspace_reader, "load_applied_strategies", _applied_contexts), \
            patch.object(research, "read_performance", _forbidden), \
            patch.object(research.rx_research_reader, "read", return_value=SimpleNamespace(error="Synthetic RX unavailable")), \
            patch.object(research, "read_updated_benchmarks", return_value=BenchmarkHistory()), \
            patch.object(research, "_historical_comparisons"), patch.object(reader, "load_package", _forbidden):
        research.render_research(model, presentation=True, selected_package=_package())


def test_raw_focus_keeps_common_primary_comparison_and_reuses_full_raw_analysis_at_shared_dates():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(_raw_page,default_timeout=30).run()
    assert not app.exception and not app.error
    assert _summary(app).iloc[0]["Period return"] == "33.10%"
    assert _comparison_values(app)["HGB_DIAG_5"][0] == "+19.79%"
    _,rows = _chart(app,"research_hgb_comparison_chart")
    assert len(rows) == 9
    assert not app.tabs and "research_gross" not in {item.key for item in app.toggle}
    assert not next(item for item in app.expander if item.label == "Raw A2 details").proto.expanded


def test_strategy_labels_use_workspace_catalog_in_each_language_without_changing_economics():
    from streamlit.testing.v1 import AppTest
    from apps.demo_console.i18n import language_scope,tr
    from apps.demo_console.pages.selected_strategies import WORKSPACE_STRATEGIES
    app = AppTest.from_function(_hgb_page,default_timeout=30).run()
    for language in ("en","zh","ja"):
        app.selectbox(key="language").select(language).run()
        assert not app.exception and not app.error
        assert _comparison_values(app)["HGB_DIAG_5"][0] == "+19.79%"
        with language_scope(language):
            labels = {tr(WORKSPACE_STRATEGIES[sid]) for sid in reader.STRATEGY_IDS}
            assert set(_summary(app)[tr("Strategy")]) == labels|{"Raw A2"}
        assert {row["series"] for row in _chart(app,"research_hgb_comparison_chart")[1]} == labels


def test_comparison_clips_raw_future_gains_to_identical_real_hgb_window():
    package = _package()
    original = deepcopy(package)
    raw = [{"date": day, "nav": nav, "cash_weight": cash} for day, nav, cash in (
        ("2025-12-31", .8, .8), ("2026-01-05", .88, .4),
        ("2026-01-06", .968, .3), ("2026-08-18", 1.0648, .2), ("2026-09-24", 10.648, .1))]
    comparison = research._hgb_comparison(package, "2025-12-31", "2026-09-24", raw)
    assert comparison["raw_matches"] is True
    assert (comparison["start"], comparison["end"], comparison["days"]) == ("2026-01-05", "2026-08-18", 3)
    assert comparison["windows"]["Raw A2"]["cumulative_return"] == pytest.approx(.331)
    assert comparison["windows"]["HGB + 对角风险"]["cumulative_return"] == pytest.approx(.1979)
    assert all(window["end"] == "2026-08-18" and len(window["rows"]) == 3
               for window in comparison["windows"].values())
    assert package == original
    # A missing actual raw observation cannot be inferred or forward-filled.
    incomplete = research._hgb_comparison(package, "2025-12-31", "2026-09-24", raw[:2] + raw[3:])
    assert not incomplete["raw_matches"] and "Raw A2" not in incomplete["windows"]
    assert research._hgb_comparison(package, "2026-09-24", "2026-09-24", raw) is None


def test_window_drawdown_includes_initial_loss_and_recovery_uses_recorded_peak():
    daily = [{"date": day, "nav": nav, "cash_weight": .2} for day, nav in (
        ("2026-01-05", .9), ("2026-01-06", 1.1), ("2026-01-07", .88), ("2026-01-08", 1.1))]
    initial = research._nav_window(daily, "2026-01-05", "2026-01-05")
    assert initial["cumulative_return"] == pytest.approx(-.1)
    assert initial["max_drawdown"] == pytest.approx(-.1)
    window = research._nav_window(daily, "2026-01-05", "2026-01-08")
    assert window["max_drawdown"] == pytest.approx(-.2)
    assert window["trough_date"] == "2026-01-07" and window["recovery_date"] == "2026-01-08"
    subwindow = research._nav_window(daily, "2026-01-07", "2026-01-08")
    assert subwindow["cumulative_return"] == pytest.approx(0)
    assert subwindow["max_drawdown"] == pytest.approx(-.2)


def test_nav_chart_domains_are_actual_shared_observations_and_baseline():
    series = {"one": [{"execution_date": "2026-01-05", "value": .97},
                      {"execution_date": "2026-08-18", "value": 1.97}],
              "two": [{"execution_date": "2026-01-05", "value": 1.01},
                      {"execution_date": "2026-08-18", "value": 1.49}]}
    spec = nav_comparison_chart(series).to_dict()
    x, y = spec["layer"][0]["encoding"]["x"]["scale"], spec["layer"][0]["encoding"]["y"]["scale"]
    assert x["domain"] == ["2026-01-05", "2026-08-18"] and x["nice"] is False
    assert .90 < y["domain"][0] < .97 < 1 < 1.97 < y["domain"][1] < 2.1
    assert y["nice"] is False and y["zero"] is False
    empty_gain = nav_comparison_chart({"loss": [{"execution_date": "2026-01-05", "value": .5}]}).to_dict()
    assert empty_gain["layer"][0]["encoding"]["y"]["scale"]["domain"][1] > 1  # Initial wealth belongs in the scale.
    different_calendar = deepcopy(series)
    different_calendar["two"][1]["execution_date"] = "2026-09-24"
    with pytest.raises(ValueError):
        nav_comparison_chart(different_calendar)
