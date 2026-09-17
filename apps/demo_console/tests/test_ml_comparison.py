"""Synthetic output-comparison semantics and native controls; no artifact reads."""
from dataclasses import replace
import json

import pytest

from apps.demo_console.components.ml_comparison import (
    comparison_chart, comparison_delta, comparison_history, comparison_rows,
    matchup_header, selection_pair,
)
from apps.demo_console.models import DecisionOverview, HoldingRow


def snapshot(day="2025-12-02", rows=None, error=None):
    return DecisionOverview(
        decision_date=day, error=error,
        ranking=tuple(rows) if rows is not None else (
            HoldingRow(1, "ALPHA", .008), HoldingRow(4, "BETA", -.002),
            HoldingRow(9, "GAMMA", .0)),
    )


def test_error_snapshot_never_exposes_unverified_rows():
    assert comparison_rows(snapshot(error="Unverified")) == ()


def test_missing_scores_and_ranks_stay_missing_and_duplicate_names_are_excluded():
    source = snapshot(rows=[HoldingRow(1, "DUPLICATE", 1), HoldingRow(2, "DUPLICATE", 2),
                            HoldingRow(None, "NO_RANK", .3), HoldingRow(3, "ZERO", 0),
                            HoldingRow(4, "NO_SCORE", float("nan")),
                            HoldingRow(True, "BAD_COORDINATES", True)])
    before = repr(source)
    rows = comparison_rows(source)
    assert [row.ticker for row in rows] == ["ZERO", "NO_SCORE", "BAD_COORDINATES", "NO_RANK"]
    assert rows[0].score == 0
    assert rows[1].score is None
    assert rows[2].rank is None and rows[2].score is None
    assert rows[3].rank is None and rows[3].score == .3
    assert repr(source) == before


@pytest.mark.parametrize("primary,secondary,expected", [
    (None, None, ("ALPHA", "BETA")),
    ("BETA", "ALPHA", ("BETA", "ALPHA")),
    ("ALPHA", "ALPHA", ("ALPHA", "BETA")),
    ("STALE", "GAMMA", ("ALPHA", "GAMMA")),
    ("BETA", "STALE", ("BETA", "ALPHA")),
])
def test_selection_pair_preserves_valid_names_and_repairs_stale_or_equal_choices(primary, secondary, expected):
    assert selection_pair(comparison_rows(snapshot()), primary, secondary) == expected


def test_selection_pair_handles_single_and_empty_snapshot():
    assert selection_pair(()) == (None, None)
    assert selection_pair((HoldingRow(1, "ONLY"),), "ONLY", "ONLY") == ("ONLY", None)


def test_differences_use_actual_signed_coordinates_and_propagate_missing():
    first, second = snapshot().ranking[:2]
    assert comparison_delta(first, second) == {"rank": -3, "score": .01}
    assert comparison_delta(replace(first, score=None), second) == {"rank": -3, "score": None}
    assert comparison_delta(replace(first, rank=None, score=0), second) == {"rank": None, "score": .002}
    assert comparison_delta(replace(first, score=float("inf")), second)["score"] is None
    assert comparison_delta(replace(first, score=1e308), replace(second, score=-1e308))["score"] is None


def test_trajectory_preserves_absence_error_and_score_only_gaps():
    history = (snapshot("2025-12-01"),
               snapshot("2025-12-02", [HoldingRow(2, "BETA", .1)]),
               snapshot("2025-12-03", [HoldingRow(3, "ALPHA", None), HoldingRow(2, "BETA", .2)]),
               snapshot("2025-12-04", error="Missing"),
               snapshot("2025-12-05"))
    records = comparison_history(history, "ALPHA", "BETA")
    alpha = [row for row in records if row["ticker"] == "ALPHA"]
    beta = [row for row in records if row["ticker"] == "BETA"]
    assert [row["rank"] for row in alpha] == [1, None, 3, None, 1]
    assert [row["rank_segment"] for row in alpha] == [1, 1, 2, 2, 3]
    assert [row["score_segment"] for row in alpha] == [1, 1, 1, 1, 2]
    assert [row["ranking_status"] for row in alpha] == [
        "Recorded", "Outside Top20", "Recorded", "Unavailable", "Recorded"]
    assert [row["rank"] for row in beta] == [4, 2, 2, None, 4]
    assert [row["rank_segment"] for row in beta] == [1, 1, 1, 1, 2]


@pytest.mark.parametrize("metric", ["rank", "score"])
def test_chart_has_explicit_finite_domains_and_independent_series_segments(metric):
    history = (snapshot("2025-12-03"), snapshot("2025-12-01"),
               snapshot("2025-12-02", [HoldingRow(1, "BETA", .0)]))
    before = repr(history)
    spec = comparison_chart(history, "ALPHA", "BETA", metric).to_dict()
    encoding = spec["encoding"]
    assert encoding["x"]["scale"]["domain"] == ["2025-12-01", "2025-12-02", "2025-12-03"]
    assert encoding["color"]["scale"]["domain"] == ["ALPHA", "BETA"]
    assert encoding["color"]["scale"]["range"] == ["#235c48", "#997045"]
    assert encoding["strokeDash"]["scale"]["domain"] == ["ALPHA", "BETA"]
    assert encoding["detail"]["field"] == f"{metric}_segment"
    assert encoding["y"]["scale"]["domain"] == ([20, 1] if metric == "rank" else [-.002, .008])
    assert not encoding["y"]["scale"]["zero"]
    assert spec["transform"] == [{"filter": {"field": metric, "valid": True}}]
    assert len(spec["data"]["values"]) == 6
    json.dumps(spec, allow_nan=False)
    assert repr(history) == before


def test_score_chart_keeps_small_values_zero_and_no_observation_fallback():
    history = (snapshot(rows=[HoldingRow(1, "ALPHA", 1.25e-9), HoldingRow(2, "BETA", 0)]),)
    spec = comparison_chart(history, "ALPHA", "BETA", "score").to_dict()
    assert [row["score"] for row in spec["data"]["values"]] == [1.25e-9, 0]
    assert spec["encoding"]["y"]["scale"]["domain"] == [0, 1.25e-9]
    assert spec["data"]["values"][0]["score_label"] == "1.25e-09"
    empty = comparison_chart((), "ALPHA", "BETA", "score").to_dict()
    assert empty["data"]["values"] == []
    assert empty["encoding"]["y"]["scale"]["domain"] == [0, 0]
    assert empty["encoding"]["y"]["axis"] is None
    json.dumps(empty, allow_nan=False)


def test_invalid_comparison_and_metric_are_rejected_and_html_is_escaped():
    with pytest.raises(ValueError):
        comparison_history((), "ALPHA", "ALPHA")
    with pytest.raises(ValueError):
        comparison_chart((), "ALPHA", "BETA", "probability")
    result = matchup_header('<img src=x onerror="alert(1)">', "Primary security")
    assert "<img" not in result
    assert "&lt;img" in result


def test_installed_vega_shows_both_legend_names_before_and_after_fullscreen():
    from copy import deepcopy
    from streamlit.elements.vega_charts import _prepare_vega_lite_spec
    from apps.demo_console.components.chart_display import chart_for_display
    from apps.demo_console.i18n import language_scope
    from apps.demo_console.tests.test_vega_initialization import _run_specs

    history = (snapshot("2025-12-01"), snapshot("2025-12-02"))
    cases = []
    for language in ("en", "zh", "ja"):
        with language_scope(language):
            for metric in ("rank", "score"):
                for presentation in (False, True):
                    chart = chart_for_display(comparison_chart(history, "ALPHA", "BETA", metric),
                                              presentation=presentation)
                    spec = _prepare_vega_lite_spec(chart.to_dict(), True)
                    spec.setdefault("padding", {})["bottom"] = 20
                    cases.append(((language, metric, presentation), spec))
    legacy = deepcopy(cases[0][1])
    legacy["encoding"]["color"].pop("legend")
    legacy["encoding"]["strokeDash"]["legend"] = None
    results = _run_specs([*(spec for _, spec in cases), legacy], width=720,
                         fullscreen={"width": 1250, "height": 662})["results"]
    for (label, spec), result in zip(cases, results[:-1], strict=True):
        assert result["warnings"] == [], (label, result["warnings"])
        assert result["loaded"] == len(spec["data"]["values"]) and result["cleared"] == 0
        for frame in (result, *result["resized"]):
            assert [row["text"] for row in frame["legendLabels"]] == ["ALPHA", "BETA"], label
            assert frame["loadedRows"] == spec["data"]["values"], label
            viewport = frame["viewport"]
            for mark in frame["legendLabels"]:
                assert mark["fontSize"] == (15 if label[2] else 13)
                assert -2 <= mark["x1"] + viewport["originX"]
                assert mark["x2"] + viewport["originX"] <= viewport["width"] + 2
                assert -2 <= mark["y1"] + viewport["originY"]
                assert mark["y2"] + viewport["originY"] <= viewport["height"] + 2
    assert results[-1]["legendLabels"] == [], "The old merge must reproduce the missing legend."


@pytest.fixture
def comparison_app(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from apps.demo_console.adapters import decision_reader

    calls = []

    def read_history(end_date, window):
        calls.append((end_date, window))
        assert end_date in {"2025-12-02", "2025-12-03"}
        assert window in {20, 60}
        return (snapshot("2025-12-01"), snapshot(end_date))

    monkeypatch.setattr(decision_reader, "load_history", read_history)

    def script():
        import streamlit as st
        from apps.demo_console.components.ml_comparison import render_model_comparison
        from apps.demo_console.i18n import language_scope
        from apps.demo_console.models import DecisionOverview, HoldingRow

        rows = st.session_state.get("test_rows", ((1, "ALPHA", .008), (4, "BETA", -.002), (9, "GAMMA", 0)))
        model = DecisionOverview(decision_date=st.session_state.get("test_date", "2025-12-02"),
                                 ranking=tuple(HoldingRow(*row) for row in rows))
        with language_scope(st.session_state.get("test_language", "en")):
            render_model_comparison(model)

    app = AppTest.from_function(script, default_timeout=15).run()
    assert not app.exception
    return app, calls


def test_native_controls_exclude_primary_and_preserve_valid_comparison_across_language(comparison_app):
    app, calls = comparison_app
    assert app.selectbox(key="ml_primary").value == "ALPHA"
    assert app.selectbox(key="ml_secondary").options == ["BETA", "GAMMA"]
    app.selectbox(key="ml_secondary").select("GAMMA").run()
    app.selectbox(key="ml_primary").select("BETA").run()
    assert not app.exception
    assert app.selectbox(key="ml_secondary").value == "GAMMA"
    app.session_state["test_language"] = "ja"
    app.run()
    assert not app.exception
    assert app.selectbox(key="ml_primary").value == "BETA"
    assert app.selectbox(key="ml_secondary").value == "GAMMA"
    app.selectbox(key="ml_primary").select("GAMMA").run()
    assert not app.exception
    assert app.selectbox(key="ml_secondary").value == "ALPHA"
    assert "GAMMA" not in app.selectbox(key="ml_secondary").options
    assert calls[-1] == ("2025-12-02", 20)


def test_date_changes_repair_stale_pair_and_history_window_passes_selected_cutoff(comparison_app):
    app, calls = comparison_app
    app.selectbox(key="ml_history_window").select("60 snapshots").run()
    assert not app.exception
    assert calls[-1] == ("2025-12-02", 60)
    app.session_state["test_date"] = "2025-12-03"
    app.session_state["test_rows"] = ((1, "DELTA", .1), (2, "BETA", .0))
    app.run()
    assert not app.exception
    assert app.selectbox(key="ml_primary").value == "DELTA"
    assert app.selectbox(key="ml_secondary").value == "BETA"
    assert calls[-1] == ("2025-12-03", 60)
    app.session_state["test_rows"] = ((1, "ONLY", 0),)
    count = len(calls)
    app.run()
    assert not app.exception and app.info
    assert len(calls) == count, "An insufficient current pair must not trigger history reads."


def test_history_verification_failure_keeps_current_pair_visible(comparison_app, monkeypatch):
    from apps.demo_console.adapters import decision_reader

    app, calls = comparison_app
    monkeypatch.setattr(decision_reader, "load_history", lambda *args, **kwargs: (snapshot(error="Unavailable"),))
    app.run()
    assert not app.exception and app.info
    assert [metric.value for metric in app.metric][:4] == ["#1", "0.008", "#4", "-0.002"]
    assert not app.get("vega_lite_chart")
