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
    from apps.demo_console.pages.selected_strategies import strategy_label
    language = next((item.value for item in app.selectbox if item.key == "language"), "en")
    with language_scope(language):
        frame = _summary(app).set_index(tr("Strategy"))
        fields = [tr(name) for name in ("Period return", "Maximum window drawdown", "Historical average cash")]
        result = {}
        for sid in reader.STRATEGY_IDS:
            values = tuple(frame.loc[tr(strategy_label(sid)), fields])
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
    from apps.demo_console.pages.selected_strategies import strategy_label
    assert set(_summary(app)["Strategy"]) == {strategy_label(sid) for sid in reader.STRATEGY_IDS} | {"Raw A2"}
    assert _summary(app).set_index("Strategy").loc["Raw A2", "Period return"] == "—"
    assert not app.tabs and not app.metric
    spec, rows = _chart(app,"research_hgb_comparison_chart")
    assert spec["layer"][0]["encoding"]["x"]["scale"]["domain"] == ["2026-01-05","2026-08-18"]
    assert len(rows) == 6
    app.session_state["research_hgb_risk_path"] = True
    app.run()
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
    assert _summary(app).set_index("Strategy").loc["Raw A2", "Period return"] == "33.10%"
    assert _summary(app).set_index("Strategy").loc["Raw A2", "Maximum window drawdown"] == "0.00%"
    assert _summary(app).set_index("Strategy").loc["Raw A2", "Historical average cash"] == "30.00%"
    _,rows = _chart(app,"research_hgb_comparison_chart")
    assert len(rows) == 9 and [row for row in rows if row["series"] == "Raw A2"][-1]["value"] == pytest.approx(1.331)
    original = _summary(app).copy()
    for focus in ("HGB_FACTOR_5","RAW_A2"):
        app.selectbox(key="workspace_strategy").select(focus).run()
        assert _summary(app).equals(original)
    app.selectbox(key="research_range").select("Custom dates").run()
    app.date_input(key="research_dates_draft").set_value((date(2026,1,6),date(2026,8,18)))
    app.button(key="research_dates_apply").click().run()
    assert not app.exception and not app.error
    assert _summary(app).set_index("Strategy").loc["Raw A2", "Period return"] == "21.00%"
    spec,rows = _chart(app,"research_hgb_comparison_chart")
    assert len(rows) == 6 and spec["layer"][0]["encoding"]["x"]["scale"]["domain"] == ["2026-01-06","2026-08-18"]
    app.session_state["raw_missing_date"] = True
    app.run()
    assert not app.exception and not app.error
    assert len(_chart(app,"research_hgb_comparison_chart")[1]) == 4
    assert _summary(app).set_index("Strategy").loc["Raw A2", "Period return"] == "—"
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
    assert _summary(app).set_index("Strategy").loc["Raw A2", "Period return"] == "33.10%"
    assert _comparison_values(app)["HGB_DIAG_5"][0] == "+19.79%"
    _,rows = _chart(app,"research_hgb_comparison_chart")
    assert len(rows) == 9
    assert not app.tabs and "research_gross" not in {item.key for item in app.toggle}
    assert not next(item for item in app.expander if item.label == "Raw A2 details").proto.expanded


def test_strategy_labels_use_workspace_catalog_in_each_language_without_changing_economics():
    from streamlit.testing.v1 import AppTest
    from apps.demo_console.i18n import language_scope,tr
    from apps.demo_console.pages.selected_strategies import strategy_label
    app = AppTest.from_function(_hgb_page,default_timeout=30).run()
    for language in ("en","zh","ja"):
        app.selectbox(key="language").select(language).run()
        assert not app.exception and not app.error
        assert _comparison_values(app)["HGB_DIAG_5"][0] == "+19.79%"
        with language_scope(language):
            labels = {tr(strategy_label(sid)) for sid in reader.STRATEGY_IDS}
            assert set(_summary(app)[tr("Strategy")]) == labels | {"Raw A2"}
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



def _latest_open_page():
    """Exercise real UI readers with synthetic immutable evidence and no provider."""
    from contextlib import ExitStack
    from unittest.mock import patch
    import streamlit as st
    from apps.demo_console.adapters import workspace_reader as workspace, applied_account_reader as accounts
    from apps.demo_console.adapters.benchmarks_reader import BenchmarkHistory, BenchmarkSeries
    from apps.demo_console.components import top20_table, stock_history_search
    from apps.demo_console.i18n import language_scope
    from apps.demo_console.pages import selected_strategies, research
    from apps.demo_console.tests.test_selected_workspace_routing import latest_execution_fixture
    from apps.demo_console.tests.test_hgb_research_workspace import _forbidden

    proof = latest_execution_fixture()
    st.session_state["workspace_sample"] = "test_2026"
    st.selectbox("Workspace strategy", ("RAW_A2", "HGB_DIAG_5", "HGB_FACTOR_5"), index=1, key="workspace_strategy")
    st.selectbox("Language", ("zh", "en", "ja"), key="language")
    st.selectbox("Observation", ("2026-10-02", "2026-10-01"), key="decision_date")
    st.selectbox("Page", ("Research", "Overview", "Portfolio", "History"), key="test_page")

    def benchmarks(dates, baseline_date=None):
        st.session_state["test_benchmark_dates"] = dates
        return BenchmarkHistory(series=(BenchmarkSeries("QQQ", "QQQ", error="HTTP_403_CURRENT_OPEN"),))

    def stock_history(**kwargs):
        st.session_state["test_stock_cutoff"] = kwargs["as_of"]
        st.session_state["test_stock_loads"] = st.session_state.get("test_stock_loads", 0) + 1
        return {"status": "UNAVAILABLE", "catalog": []}

    def rankings(day, **kwargs):
        st.session_state["test_rank_cutoff"] = day
        return {"status": "READY", "strategies": {}}

    def original_fixture_contexts(day, **kwargs):
        # This fixture tests its original three archived clock series. Live
        # five-account context/HTTP/new replay providers belong to other tests.
        kwargs.pop("account_state", None)
        return workspace.load_applied_strategies(day, **kwargs)

    with ExitStack() as stack:
        stack.enter_context(patch.object(accounts, "load_state", return_value={"books": {}}))
        stack.enter_context(patch.object(workspace, "load_active_strategies", original_fixture_contexts))
        stack.enter_context(language_scope(st.session_state["language"]))
        for name, function in (("load_overview", proof["overview"]), ("read_performance", proof["performance"]),
                               ("latest_executed_overview", proof["book"]),
                               ("load_applied_stock_catalog", stock_history), ("load_applied_rankings", rankings)):
            stack.enter_context(patch.object(workspace, name, function))
        stack.enter_context(patch.object(workspace.updated, "binding", return_value=proof["binding"]))
        stack.enter_context(patch.object(research, "read_updated_benchmarks", benchmarks))
        stack.enter_context(patch.object(research, "read_benchmarks", _forbidden))
        stack.enter_context(patch.object(research.rx_research_reader, "read", _forbidden))
        stack.enter_context(patch.object(top20_table, "render_applied_rankings", lambda *args, **kwargs: None))
        stack.enter_context(patch.object(stock_history_search, "render_applied_stock_history", lambda *args, **kwargs: None))
        stack.enter_context(patch.object(workspace.selected, "load_package", _forbidden))
        selected_strategies.render_workspace(proof["model"], proof["package"],
            presentation=True, view=st.session_state["test_page"])


@pytest.mark.parametrize("page,key", [("Research", "applied_nav"), ("Overview", "applied_nav")])
def test_current_ui_retains_verified_next_open_when_benchmark_open_is_unavailable(page, key):
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(_latest_open_page, default_timeout=30).run()
    if page != "Research":
        app.selectbox(key="test_page").select(page).run()
    assert not app.exception and not app.error
    spec, rows = _chart(app, key)
    assert spec["layer"][0]["encoding"]["x"]["scale"]["domain"] == ["2026-10-01", "2026-10-05"]
    assert len(rows) == 9 and {row["execution_date"] for row in rows} == {"2026-10-01", "2026-10-02", "2026-10-05"}
    assert not any("QQQ" in row["series"] for row in rows)
    assert app.session_state["test_benchmark_dates"][-1] == "2026-10-05"
    captions = "\n".join(item.value for item in app.caption)
    assert "2026-10-02" in captions and "2026-10-05" in captions
    assert "QQQ 的合格开盘价格尚未完整覆盖至 2026-10-05" in captions
    if page == "Overview":
        assert "test_rank_cutoff" not in app.session_state
        assert "test_stock_cutoff" not in app.session_state
    for focus in ("HGB_FACTOR_5", "RAW_A2"):
        app.selectbox(key="workspace_strategy").select(focus).run()
        assert not app.exception and not app.error
        assert _chart(app, key)[1] == rows


@pytest.mark.parametrize("page,key", [("Research", "applied_nav"), ("Overview", "applied_nav")])
def test_ui_historical_selection_never_sees_later_execution_or_target(page, key):
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(_latest_open_page, default_timeout=30).run()
    if page != "Research":
        app.selectbox(key="test_page").select(page).run()
    app.selectbox(key="decision_date").select("2026-10-01").run()
    assert not app.exception and not app.error
    rows = _chart(app, key)[1]
    assert len(rows) == 3 and {row["execution_date"] for row in rows} == {"2026-10-01"}
    assert app.session_state["test_benchmark_dates"] == ("2026-10-01",)
    captions = "\n".join(item.value for item in app.caption)
    assert "2026-10-01" in captions
    assert "执行绩效截至 2026-10-05" not in captions
    if page == "Overview":
        assert "test_rank_cutoff" not in app.session_state
        assert "test_stock_cutoff" not in app.session_state



def _vintage_caption_package():
    row = {"ticker": "SYN", "security_id": "SYN_ID", "raw_rank": 2,
           "raw_score": .01, "hgb_rank": 1, "pred_hgb": .02}
    return {"shared_scores": {"current": {"status": "READY", "signal_date": "2026-04-07", "rows": [row]},
        "historical": [{**row, "signal_date": "2026-04-07"}]},
        "performance_period": {"price_basis": "PIT_FORWARD_REHAB_INDEX"}}


@pytest.mark.parametrize("field,value", [("ticker", "SYN_OTHER"), ("security_id", "SYN_OTHER_ID"),
    ("raw_rank", 3), ("raw_score", .011), ("hgb_rank", 2), ("pred_hgb", .021)])
def test_replay_input_vintage_caption_detects_same_day_identity_rank_and_score_changes(field, value):
    from apps.demo_console.pages.selected_strategies import replay_input_vintage_caption
    package = _vintage_caption_package()
    package["shared_scores"]["current"]["rows"][0][field] = value
    original = deepcopy(package)
    assert "candidate lists may differ" in replay_input_vintage_caption(package)
    assert package == original


def test_replay_input_vintage_caption_ignores_order_and_other_signal_dates():
    from apps.demo_console.pages.selected_strategies import replay_input_vintage_caption
    package = _vintage_caption_package()
    row = {**package["shared_scores"]["current"]["rows"][0], "ticker": "SYN_SECOND", "security_id": "ID_SECOND"}
    package["shared_scores"]["current"]["rows"].append(row)
    package["shared_scores"]["historical"].insert(0, {**row, "signal_date": "2026-04-07"})
    package["shared_scores"]["historical"].append({**row, "ticker": "OTHER_DAY", "signal_date": "2026-04-06"})
    assert replay_input_vintage_caption(package) is None
    package["shared_scores"]["historical"] = [{**row, "signal_date": "2026-04-06"}]
    assert replay_input_vintage_caption(package) is None
    assert replay_input_vintage_caption({}) is None


@pytest.mark.parametrize("language,expected", [
    ("zh", "研究回放保留当时已接受的信号输入版本；当前目标／模拟仓采用补齐后的输入，候选名单可能不同。"),
    ("en", "The research replay retains its accepted signal input version. Current targets / paper portfolios use the completed inputs, so candidate lists may differ."),
    ("ja", "研究リプレイは当時受理したシグナル入力版を保持します。現在の目標配分／ペーパーポートフォリオは補完後の入力を使用するため、候補銘柄が異なる場合があります。"),
])
def test_source_details_preserve_input_vintage_caption_only_when_different(monkeypatch, language, expected):
    from contextlib import nullcontext
    from apps.demo_console.i18n import language_scope
    from apps.demo_console.pages import selected_strategies
    captions = []
    monkeypatch.setattr(selected_strategies.st, "caption", captions.append)
    monkeypatch.setattr(selected_strategies.st, "write", lambda *args: None)
    monkeypatch.setattr(selected_strategies.st, "expander", lambda *args, **kwargs: nullcontext())
    package = {**_vintage_caption_package(), "package_sha256": "ab" * 32}
    with language_scope(language):
        selected_strategies._source_details(package, presentation=True)
        assert expected not in captions
        package["shared_scores"]["current"]["rows"][0]["pred_hgb"] += .001
        selected_strategies._source_details(package, presentation=True)
    assert captions.count(expected) == 1
    assert not any("D:/" in caption or "sha256" in caption for caption in captions)

def test_stock_history_loads_only_when_its_tab_opens_and_keeps_observation_cutoff():
    from streamlit.testing.v1 import AppTest
    from apps.demo_console.tests.test_localized_tabs import _switch_tab
    app = AppTest.from_function(_latest_open_page, default_timeout=30).run()
    app.selectbox(key="test_page").select("Portfolio").run()
    assert not app.exception and not app.error
    assert "test_stock_loads" not in app.session_state
    assert app.session_state["test_rank_cutoff"] == "2026-10-02"
    _switch_tab(app, "个股跨策略历史")
    assert not app.exception and not app.error
    assert app.session_state["test_stock_loads"] == 1
    assert app.session_state["test_stock_cutoff"] == "2026-10-02"
    app.selectbox(key="decision_date").select("2026-10-01").run()
    assert not app.exception and not app.error
    assert app.session_state["test_stock_cutoff"] == "2026-10-01"
    # Closed decision content keeps its last capture until that native tab opens.
    assert app.session_state["test_rank_cutoff"] == "2026-10-02"
    from apps.demo_console.tests.test_localized_tabs import _label
    _switch_tab(app, _label("Decisions & portfolio", "zh"), key="applied_workspace_tools")
    assert not app.exception and not app.error
    assert app.session_state["test_rank_cutoff"] == "2026-10-01"


def _active_reference_page():
    from unittest.mock import patch
    from types import SimpleNamespace
    import streamlit as st
    from apps.demo_console.i18n import language_scope
    from apps.demo_console.pages import research, selected_strategies
    from apps.demo_console.adapters.benchmarks_reader import BenchmarkHistory, BenchmarkSeries, BenchmarkPoint
    dates = ("2026-01-05", "2026-01-06", "2026-01-07")
    missing = st.checkbox("Synthetic reference unavailable", key="missing_reference")
    contexts = {sid: {"label": label, "history": {"start": dates[0], "end": dates[-1],
        "daily": [{"date": day, "nav": 1 + index * .02 + offset * .01, "cash_weight": .2}
                  for offset, day in enumerate(dates)]}}
                for index, (sid, label) in enumerate(selected_strategies.WORKSPACE_STRATEGIES.items())}
    payload = {"strategies": {"HGB_DIAG_5": {"daily": contexts["HGB_DIAG_5"]["history"]["daily"]}}}
    def references(requested, baseline_date=None):
        st.session_state["reference_request"] = (requested, baseline_date)
        series = []
        for symbol, gain in (("QQQ", .04), ("SPY", -.02)):
            series.append(BenchmarkSeries(symbol, symbol, adjustment="RAW",
                points=tuple(BenchmarkPoint(day, 100., 0., 1. + offset * gain, 0.)
                             for offset, day in enumerate(requested)),
                total_return=(len(requested) - 1) * gain,
                error="SYNTHETIC_MISSING_OPEN" if missing else None))
        return BenchmarkHistory(series=tuple(series))
    with language_scope(st.session_state.get("reference_language", "en")), patch.object(research, "read_updated_benchmarks", references):
        result = research.render_applied_performance(contexts, payload, dates[-1],
            key_prefix="active_ref", statistics=False)
    st.session_state["recorded_strategy_windows"] = result["windows"]


def test_five_strategy_reference_selector_changes_only_reference_curve_and_preserves_missing_window():
    from copy import deepcopy
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(_active_reference_page, default_timeout=20).run()
    assert not app.exception and not app.error
    expected = deepcopy(app.session_state["recorded_strategy_windows"])
    initial = _chart(app, "active_ref_nav")[1]
    assert len({row["series"] for row in initial}) == 6
    assert any(row["series"].startswith("QQQ") for row in initial)
    assert app.session_state["reference_request"] == (("2026-01-05", "2026-01-06", "2026-01-07"), None)
    for symbol in ("SPY", "None", "QQQ"):
        app.selectbox(key="applied_benchmark").select(symbol).run()
        assert not app.exception and not app.error
        rows = _chart(app, "active_ref_nav")[1]
        assert app.session_state["recorded_strategy_windows"] == expected
        assert any(row["series"].startswith("SPY") for row in rows) == (symbol == "SPY")
        assert any(row["series"].startswith("QQQ") for row in rows) == (symbol == "QQQ")
    app.checkbox(key="missing_reference").check().run()
    assert not app.exception and not app.error
    rows = _chart(app, "active_ref_nav")[1]
    assert len({row["series"] for row in rows}) == 5
    assert app.session_state["recorded_strategy_windows"] == expected
    assert any("2026-01-07" in caption.value and "retained" in caption.value for caption in app.caption)


def test_actual_benchmark_caption_translates_in_all_languages_without_changing_results():
    from copy import deepcopy
    from streamlit.testing.v1 import AppTest
    from apps.demo_console.i18n import catalog, language_scope, tr
    current = "{label}: {return_value} over these dates · RAW open-price reference, excluding dividends and fees. Strategy replay uses its recorded adjustment basis."
    legacy = "{label}: {return_value} over these dates · RAW open-price reference, excluding dividends and fees. QFQ replay remains a separate return basis."
    assert legacy in catalog()
    app = AppTest.from_function(_active_reference_page, default_timeout=20).run()
    assert not app.exception and not app.error
    windows = deepcopy(app.session_state["recorded_strategy_windows"])
    request = app.session_state["reference_request"]
    for language in ("zh", "ja", "en"):
        app.session_state["reference_language"] = language
        app.run()
        assert not app.exception and not app.error
        with language_scope(language):
            expected = tr(current, label="QQQ · " + tr("Price reference"), return_value="8.00%")
        captions = [node.value for node in app.caption]
        assert expected in captions
        assert "8.00%" in expected and "RAW" in expected
        if language != "en":
            assert "over these dates" not in expected and "excluding dividends and fees" not in expected
        assert app.session_state["recorded_strategy_windows"] == windows
        assert app.session_state["reference_request"] == request
