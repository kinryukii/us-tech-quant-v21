"""Exercise the production main entry, global strategy selection, and all HGB views.

Synthetic packages isolate UI routing from frozen scientific dependencies. The
final two tests also read the real published package; neither path fits models.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import os
from math import fsum
from pathlib import Path

from pandas.testing import assert_frame_equal
import pyarrow as pa
import pytest
from streamlit.testing.v1 import AppTest

from apps.demo_console import app as console
from apps.demo_console.adapters import selected_strategies_reader as reader
from apps.demo_console.models import DecisionOverview, PerformanceHistory
from apps.demo_console.pages.selected_strategies import WORKSPACE_STRATEGIES


IDS = ("HGB_DIAG_5", "HGB_FACTOR_5")
EXPECTED = {
    "HGB_DIAG_5": {"nav": 1.9741700933241764, "drawdown": -.0884573208090429,
                   "count": 11, "cash": .39938536599784025, "prefix": "DIAG"},
    "HGB_FACTOR_5": {"nav": 1.4908459559581526, "drawdown": -.06171305217284928,
                     "count": 8, "cash": .6632744890251268, "prefix": "FACTOR"},
}


def _rows(prefix, count, total):
    weight = total / count
    return [{"ticker": f"{prefix}_{number:02}", "target_weight": weight,
             "weight_before": 0.0, "action": "BUY"} for number in range(1, count + 1)]


def _package():
    dates = ("2026-01-05", "2026-01-06", "2026-08-18")
    result = {
        "schema_version": 1, "generated_at": "2026-09-28T08:00:00+00:00",
        "selection_basis": "USER_SELECTED_AFTER_EXPOSURE",
        "performance_period": {"start": dates[0], "end": dates[-1], "days": 3,
            "decision_clock": "SIGNAL_CLOSE_NEXT_SESSION_OPEN",
            "price_basis": "QFQ_PRICE_COORDINATE_PROXY"},
        "source_hashes": {"synthetic_business_contract": "ab" * 32},
        "broker_action_allowed": False, "model_fit_calls": 0, "strategies": {},
    }
    for sid, expected in EXPECTED.items():
        cash = (.2, .3, .4) if sid == IDS[0] else (.5, .6, .7)
        daily = [{"date": day, "nav": nav, "cash_weight": reserve}
                 for day, nav, reserve in zip(dates, (1., 1. + expected["drawdown"], expected["nav"]), cash)]
        result["strategies"][sid] = {
            "label": reader.STRATEGY_LABELS[sid],
            "summary": {"end_nav": expected["nav"], "cumulative_return": expected["nav"] - 1.,
                "max_drawdown": expected["drawdown"], "mean_cash": fsum(cash) / 3,
                "days": 3, "turnover": .2},
            "daily": daily,
            "targets": [{"signal_date": day, "rows": _rows("HIST_" + expected["prefix"], count, .2)}
                        for day, count in (("2026-01-02", 1), ("2026-01-05", 2), ("2026-08-17", 3))],
            "application": {"status": "READY", "signal_date": "2026-09-24",
                "requested_signal_date": "2026-09-24", "account_basis": "CASH_START",
                "account_label": "空仓账户目标方案", "reason": None,
                "rows": _rows(expected["prefix"], expected["count"], 1. - expected["cash"]),
                "target_cash_weight": expected["cash"], "broker_action_allowed": False,
                "model_fit_calls": 0, "decision_clock": "SIGNAL_CLOSE_NEXT_SESSION_OPEN"},
        }
    return reader.validate_package(result)


def _content(app):
    output = []
    for element in app:
        if hasattr(element, "proto"):
            output.append(str(element.proto))
        try:
            value = element.value
        except AttributeError:
            continue
        if callable(getattr(value, "to_numpy", None)):
            output.extend(str(cell) for cell in value.to_numpy().flat)
        else:
            output.append(str(value))
    return "\n".join(output)


def _healthy(app):
    assert not app.exception, _content(app)
    assert not app.error, _content(app)


def _metrics(app):
    return {element.label: element.value for element in app.metric}


def _metric_values(app, label):
    return [element.value for element in app.metric if element.label == label]


def _summary(app):
    return next(item.value for item in app.dataframe if "Period return" in item.value.columns and "Strategy" in item.value.columns)


def _allocation_matrix(app):
    return next(item.value for item in app.dataframe if list(item.value.columns) ==
                ["Ticker", "Raw A2", "HGB · Diagonal", "HGB · Factor"])


def _open_legacy_strategies_bookmark(app):
    # AppTest's public switch_page accepts files, while this production URL is
    # a callable st.Page. Use its observed registry hash as the client request.
    pages = app._registered_pages
    app._page_hash = next(key for key, page in pages.items()
                          if page.get("url_pathname") == "strategies")
    return app.run()


def _table(app, column):
    return next(element.value for element in app.dataframe if column in element.value.columns)


def _chart(app, key):
    element = next(item for item in app.get("vega_lite_chart") if json.loads(item.proto.spec).get("name") == key)
    payloads = [element.proto.data.data, *(item.data.data for item in element.proto.datasets)]
    rows = [row for payload in payloads if payload for row in pa.ipc.open_stream(payload).read_all().to_pylist()
            if "series" in row]
    spec = json.loads(element.proto.spec)
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


def _new_app(*, strategy=None, sample="test_2026", view="Overview", date=None):
    app = AppTest.from_string("from apps.demo_console import app as console\nconsole.main()",
                              default_timeout=90)
    app.session_state["language"] = "en"
    app.session_state["workspace_sample"] = sample
    app.session_state["workspace"] = view
    app.session_state["presentation_mode"] = True
    app.session_state["motion_enabled"] = False
    if strategy is not None:
        app.session_state["workspace_strategy"] = strategy
    if date is not None:
        app.session_state["decision_date"] = date
    return app.run()


@pytest.fixture
def hgb_workspace(tmp_path, monkeypatch):
    package = _package()
    path = tmp_path / "selected_hgb.json"
    path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("USTQ_SELECTED_HGB_PACKAGE", str(path))
    reader.clear_cache()
    raw_calls, raw_reference_calls, render_calls = [], [], []
    raw_dates = ("2026-09-23", "2026-09-24")
    raw_reference_path = tmp_path / "raw_reference_manifest.json"
    raw_reference_path.write_text(json.dumps({"source_id": console.workspace_reader.LATEST,
        "observed_dates": raw_dates}), encoding="utf-8")
    raw_reference_hash = sha256(raw_reference_path.read_bytes()).hexdigest()

    def raw_model():
        raw_calls.append("RAW_A2")
        observed = console.st.session_state.get("decision_date")
        return raw_reference(observed if observed in raw_dates else raw_dates[-1])

    def raw_reference(day=None, **kwargs):
        raw_reference_calls.append({"day": day, **kwargs})
        return DecisionOverview(decision_date=day or "2026-09-24",
            available_dates=raw_dates, source_id=console.workspace_reader.LATEST,
            performance_cutoff_date=day or "2026-09-24",
            source_manifest_path=str(raw_reference_path), source_manifest_sha256=raw_reference_hash)

    def raw_performance(model):
        return PerformanceHistory(requested_end_date=model.decision_date,
            error="SYNTHETIC_RAW_REFERENCE_UNAVAILABLE")

    real_render = console.render_overview

    def observed_render(model, **kwargs):
        render_calls.append({"model": model, "package": kwargs.get("selected_package"),
                             "view": kwargs.get("view")})
        return real_render(model, **kwargs)

    monkeypatch.setattr(console, "_load_workspace_model", raw_model)
    monkeypatch.setattr(console.workspace_reader, "load_overview", raw_reference)
    monkeypatch.setattr(console.workspace_reader, "read_performance", raw_performance)
    monkeypatch.setattr(console.workspace_reader, "latest_executed_overview", lambda model: None)
    monkeypatch.setattr(console, "render_overview", observed_render)
    yield {"path": path, "package": package, "raw_calls": raw_calls,
           "raw_reference_calls": raw_reference_calls, "render_calls": render_calls}
    reader.clear_cache()


def test_main_three_strategy_summary_and_shared_paths_keep_observations(hgb_workspace):
    app = _new_app()
    _healthy(app)
    assert app.selectbox(key="workspace_strategy").value == "RAW_A2"
    frame = _summary(app)
    assert frame["Strategy"].tolist() == list(WORKSPACE_STRATEGIES.values())
    assert frame["Period return"].tolist() == ["—", "97.42%", "49.08%"]
    assert len(_chart(app, "applied_nav")[1]) == 6
    assert len(_chart(app, "applied_drawdown")[1]) == 6
    assert not app.metric
    assert [tab.label for tab in app.tabs] == ["Decisions & portfolio", "Stock history across strategies", "Quantitative comparison"]
    markup = next(item.proto.body for item in app.get("html") if 'class="uq-strategy-scorecard"' in item.proto.body)
    assert markup.count('class="uq-strategy-score"') == 3
    assert all(value in markup for value in ("97.42%", "49.08%", "Raw A2", 'data-strategy="RAW_A2"'))
    assert not next(item for item in app.expander if item.label == "Drawdown comparison").proto.expanded
    assert app.selectbox(key="applied_rank_count") and app.selectbox(key="applied_rank_order")
    assert "Daily rankings and allocations" in _content(app)
    assert "Stock history across strategies" in _content(app)
    metrics = _table(app, "Metric").set_index("Metric")
    assert metrics.at["Annualized volatility", "HGB · Diagonal"] != "—"
    assert metrics.at["Cumulative turnover · Times", "HGB · Diagonal"] == "—"
    assert metrics.at["Simulated fees / Window initial NAV", "HGB · Factor"] == "—"


def test_detail_focus_preserves_three_strategy_interval_and_allocation(hgb_workspace):
    from datetime import date
    app = _new_app(strategy=IDS[0])
    app.selectbox(key="research_range").select("Custom dates").run()
    app.date_input(key="research_dates_draft").set_value((date(2026,1,6), date(2026,8,18)))
    app.button(key="research_dates_apply").click().run()
    _healthy(app)
    expected = _summary(app).copy()
    matrix = _allocation_matrix(app).copy()
    for focus in (IDS[1], "RAW_A2", IDS[0]):
        app.selectbox(key="workspace_strategy").select(focus).run()
        _healthy(app)
        assert app.selectbox(key="decision_date").value == "2026-09-24"
        assert app.selectbox(key="research_range").value == "Custom dates"
        assert_frame_equal(_summary(app), expected)
        assert_frame_equal(_allocation_matrix(app), matrix)
    app.radio(key="workspace").set_value("Research").run()
    _healthy(app)
    assert_frame_equal(_summary(app), expected)
    assert len(_chart(app, "research_hgb_nav")[1]) == 4


def test_signal_comparison_never_carries_an_old_target_to_a_new_date(hgb_workspace):
    app = _new_app(strategy=IDS[1])
    current = _allocation_matrix(app).set_index("Ticker")
    assert current.at["CASH", "HGB · Diagonal"] == "39.94%"
    assert current.at["CASH", "HGB · Factor"] == "66.33%"
    assert len([x for x in current["HGB · Diagonal"] if x not in ("0.00%", "—")]) == 12
    app.selectbox(key="decision_date").select("2026-09-23").run()
    _healthy(app)
    assert _allocation_matrix(app).iloc[:,1:].eq("—").all().all()
    assert not app.get("download_button")
    app.selectbox(key="decision_date").select("2026-01-05").run()
    _healthy(app)
    historical = _allocation_matrix(app).set_index("Ticker")
    assert historical.at["CASH", "HGB · Diagonal"] == "80.00%"
    assert "HIST_DIAG_02" in historical.index
    assert {row["execution_date"] for row in _chart(app,"applied_nav")[1]} == {"2026-01-05"}


def test_applied_bookmark_and_languages_keep_shared_context(hgb_workspace):
    app = _new_app(strategy=IDS[1],date="2026-08-17")
    _healthy(app)
    _open_legacy_strategies_bookmark(app)
    _healthy(app)
    assert app.radio(key="workspace").value == "Overview"
    assert app.selectbox(key="workspace_strategy").value == IDS[1]
    assert app.selectbox(key="decision_date").value == "2026-08-17"
    for language in ("zh","ja","en"):
        app.selectbox(key="language").select(language).run()
        _healthy(app)
        assert app.selectbox(key="workspace_strategy").value == IDS[1]
        assert app.selectbox(key="decision_date").value == "2026-08-17"
        assert len(_chart(app,"applied_nav")[1]) == 4


def test_invalid_package_exposes_no_fallback_and_preserves_selected_id(hgb_workspace):
    package = deepcopy(hgb_workspace["package"])
    package["strategies"][IDS[0]]["application"]["target_cash_weight"] = .99
    hgb_workspace["path"].write_text(json.dumps(package),encoding="utf-8")
    reader.clear_cache()
    app = _new_app(strategy=IDS[1])
    assert not app.exception and app.error
    assert app.selectbox(key="workspace_strategy").value == IDS[1]
    assert not app.dataframe and not app.get("vega_lite_chart")


def test_hgb_model_details_keep_original_frozen_feature_contract(hgb_workspace):
    app = _new_app(strategy=IDS[1],view="Machine learning")
    _healthy(app)
    assert _metrics(app)["Model input features"] == "21"
    assert _metrics(app)["Training boundary"] == "< 2026-01-01"
    assert _table(app,"Feature count")["Feature count"].tolist() == [2,9,10]
    assert "Raw Top40 prediction scores" in _content(app)


@pytest.mark.skipif(not os.environ.get("USTQ_TEST_HGB_PACKAGE"), reason="Published inputs are opt-in read-only QA")
def test_real_three_strategy_workbench_and_nonselected_stock_query(monkeypatch):
    monkeypatch.setenv("USTQ_SELECTED_HGB_PACKAGE", os.environ["USTQ_TEST_HGB_PACKAGE"])
    reader.clear_cache()
    app = _new_app(strategy=IDS[0])
    _healthy(app)
    frame = _summary(app)
    assert frame["Period return"].tolist() == ["41.96%","97.42%","49.08%"]
    _, points = _chart(app,"applied_nav")
    assert len([row for row in points if row["series"] in WORKSPACE_STRATEGIES.values()]) == 468
    reference=[row for row in points if row["series"].startswith("QQQ") ]
    assert len(reference) == 156 and reference[0]["value"] == 1.
    assert {row["execution_date"] for row in points} == {row["date"] for row in reader.load_package()["raw_reference"]["daily"]}
    ranks = [item.value for item in app.dataframe if "model_rank" in item.value.columns]
    assert len(ranks) == 3 and all(len(frame) == 10 for frame in ranks)
    app.selectbox(key="applied_stock_ticker").select("AAPL").run()
    _healthy(app)
    assert app.selectbox(key="decision_date").value == "2026-09-24"
    assert "Daily ranking and allocation records" in _content(app)
    assert len([x for x in app.dataframe if "selection_coverage" in x.value.columns][0].value) == 3
    app.selectbox(key="decision_date").select("2026-09-23").run()
    _healthy(app)
    assert "Recorded Top40 only" in _content(app)
    assert _allocation_matrix(app).iloc[:,2:].eq("—").all().all()
    reader.clear_cache()
