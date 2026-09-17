"""Synthetic holdings and native selection events; no result-source access."""
from dataclasses import replace
from datetime import date, timedelta
import json
import unittest
from unittest.mock import patch

from streamlit.proto.WidgetStates_pb2 import WidgetState
from streamlit.typing import VegaLiteState

from apps.demo_console.components import holding_matrix as matrix
from apps.demo_console.i18n import language_scope, tr
from apps.demo_console.models import DecisionOverview, HoldingRow, PipelineStage, Provenance
from apps.demo_console.tests.test_history_view import _charts, history_app
from apps.demo_console.tests.test_terminal_interactions import _workspace_action


def snapshot(day, *, held=("FIRST",), available=True, execution=None):
    return DecisionOverview(
        decision_date=day,
        ranking=(HoldingRow(1, "FIRST", score=.000001), HoldingRow(2, "SECOND", score=-.1)),
        holdings=tuple(HoldingRow(None, ticker) for ticker in held),
        pipeline=(PipelineStage("Portfolio", "AVAILABLE" if available else "UNAVAILABLE", "Synthetic"),),
        provenance=Provenance(execution_date=execution),
    )


def event(rows):
    return VegaLiteState({"selection": {"holding_matrix_row": rows}})


class HoldingMatrixTests(unittest.TestCase):
    def test_membership_keeps_unknown_separate_and_ignores_ranking_availability(self):
        history = (snapshot("2025-01-02"),
                   replace(snapshot("2025-01-03", held=("SECOND",)), ranking=()),
                   snapshot("2025-01-06", available=False),
                   snapshot("2025-01-07", held=()),
                   replace(snapshot("2025-01-08"), error="Unverified"))
        records = matrix.matrix_records(history, ("FIRST", "SECOND"))
        self.assertEqual([row["held"] for row in records[:5]], [True, False, None, None, None])
        self.assertEqual([row["state"] for row in records[:5]],
                         ["Held", "Not held", "Unavailable", "Unavailable", "Unavailable"])
        self.assertEqual(records[6]["held"], True)

    def test_last_60_supplied_dates_and_first_20_raw_tickers_keep_their_order(self):
        start = date(2025, 1, 1)
        days = tuple((start + timedelta(days=i)).isoformat() for i in range(75))
        history = tuple(snapshot(day) for day in reversed(days))
        # available_dates must not extend the supplied history cutoff.
        history = (replace(history[0], available_dates=days + ("2025-12-31",)),) + history[1:]
        tickers = tuple(f"RAW-{i:02}" for i in reversed(range(25)))
        records = matrix.matrix_records(history, tickers)
        self.assertEqual(len(records), 60 * 20)
        self.assertEqual(list(dict.fromkeys(row["ticker"] for row in records)), list(tickers[:20]))
        self.assertEqual([row["decision_date"] for row in records[:60]], list(days[-60:]))
        self.assertLessEqual(max(row["decision_date"] for row in records), days[-1])
        spec = matrix.matrix_chart(history, tickers).to_dict()
        self.assertEqual(spec["encoding"]["y"]["scale"]["domain"], list(tickers[:20]))
        self.assertGreaterEqual(spec["height"], 400, "Twenty rows retain room inside the complete frame")
        self.assertEqual(spec["autosize"], {"type": "fit", "contains": "padding"})

    def test_empty_inputs_and_duplicate_tickers_do_not_fabricate_cells(self):
        self.assertEqual(matrix.matrix_records((), ("FIRST",)), [])
        self.assertEqual(matrix.matrix_records((snapshot("2025-01-02"),), ()), [])
        self.assertEqual(matrix.matrix_records((DecisionOverview(),), ("FIRST",)), [])
        records = matrix.matrix_records((snapshot("2025-01-02"),), ("SECOND", "FIRST", "SECOND"))
        self.assertEqual([row["ticker"] for row in records], ["SECOND", "FIRST"])
        self.assertEqual(matrix.matrix_chart((), ()).to_dict()["data"]["values"], [])

    def test_chart_preserves_raw_values_cutoff_and_models_in_every_language(self):
        literal = 'A"</script>'
        history = (snapshot("2024-12-31", held=(literal,), execution="2025-01-02"),
                   snapshot("2025-01-02", available=False))
        before = repr(history)
        original = matrix.matrix_records(history, (literal,))
        for language in ("en", "zh", "ja"):
            with language_scope(language):
                spec = matrix.matrix_chart(history, (literal,), literal).to_dict()
                values = spec["data"]["values"]
                self.assertEqual([{key: row[key] for key in original[0]} for row in values], original)
                self.assertEqual(values[1]["execution_label"], tr("Not recorded"))
                self.assertEqual(values[1]["state_label"], tr("Unavailable"))
                self.assertEqual(spec["encoding"]["x"]["axis"]["labelExpr"], "substring(datum.label, 0, 7)")
                self.assertEqual(spec["encoding"]["x"]["scale"]["domain"], ["2024-12-31", "2025-01-02"])
                self.assertNotIn("transform", spec)
                json.dumps(spec, allow_nan=False)
        self.assertEqual(repr(history), before)

    def test_native_selection_validates_single_original_ticker_and_clear_inputs(self):
        literal = 'A"</script>'
        self.assertEqual(matrix._selected_ticker(event([{"ticker": literal}]), (literal,)), literal)
        invalid = (None, {}, {"selection": None}, event({}), event([]), event("FIRST"),
                   event(["FIRST"]), event([{"ticker": ["FIRST"]}]), event([{"ticker": 1}]),
                   event([{"ticker": "OUTSIDE"}]), event([{"ticker": "FIRST"}, {"ticker": "SECOND"}]))
        for value in invalid:
            with self.subTest(value=value):
                self.assertIsNone(matrix._selected_ticker(value, ("FIRST", "SECOND")))

    def test_callback_updates_both_keys_only_for_a_valid_event(self):
        state = {"chart": event([{"ticker": "SECOND"}]),
                 "history_ticker": "FIRST", "_history_focus": "FIRST", "_holding_matrix_key": "chart"}
        with patch.object(matrix.st, "session_state", state):
            matrix._select_row(("FIRST", "SECOND"), "chart")
            self.assertEqual((state["history_ticker"], state["_history_focus"]), ("SECOND", "SECOND"))
            for value in (event([]), event({}), event([{"ticker": "OUTSIDE"}])):
                state["chart"] = value
                matrix._select_row(("FIRST", "SECOND"), "chart")
                self.assertEqual((state["history_ticker"], state["_history_focus"]), ("SECOND", "SECOND"))

    def test_repeated_render_does_not_reapply_old_selection_or_override_manual_focus(self):
        history = (snapshot("2025-01-02", execution="2025-01-03"),)
        state = {"history_ticker": "FIRST", "_history_focus": "FIRST"}
        with patch.object(matrix.st, "session_state", state), patch.object(matrix.st, "html"), \
                patch.object(matrix.st, "caption"), patch.object(matrix.st, "altair_chart") as chart:
            matrix.render_holding_matrix(history, ("FIRST", "SECOND"))
            first = chart.call_args.kwargs
            self.assertTrue(callable(first["on_select"]))
            self.assertEqual(first["selection_mode"], ["holding_matrix_row"])
            state[first["key"]] = event([{"ticker": "SECOND"}])
            first["on_select"]()
            self.assertEqual(state["history_ticker"], "SECOND")
            matrix.render_holding_matrix(history, ("FIRST", "SECOND"))
            second_key = chart.call_args.kwargs["key"]
            self.assertNotEqual(first["key"], second_key)
            state[second_key] = event([{"ticker": "SECOND"}])
            state["history_ticker"] = state["_history_focus"] = "FIRST"
            matrix.render_holding_matrix(history, ("FIRST", "SECOND"))
            final_key = chart.call_args.kwargs["key"]
            self.assertNotEqual(final_key, first["key"])
            self.assertNotEqual(final_key, second_key)
            # Even a delayed callback from the discarded chart cannot win.
            first["on_select"]()
            matrix.render_holding_matrix(history, ("FIRST", "SECOND"))
            self.assertEqual((state["history_ticker"], state["_history_focus"]), ("FIRST", "FIRST"))
            self.assertEqual(chart.call_args.kwargs["key"], final_key)

    def test_chart_selection_has_explicit_ticker_field_and_empty_render_has_no_widget(self):
        history = (snapshot("2025-01-02"),)
        spec = matrix.matrix_chart(history, ("FIRST",)).to_dict()
        self.assertEqual(spec["params"][0]["select"],
                         {"type": "point", "clear": "dblclick", "fields": ["ticker"],
                          "encodings": [], "on": "click", "toggle": False})
        self.assertEqual(spec["encoding"]["x"]["axis"]["labelExpr"], "substring(datum.label, 5)")
        with patch.object(matrix.st, "session_state", {}), patch.object(matrix.st, "html"), \
                patch.object(matrix.st, "info") as info, \
                patch.object(matrix.st, "altair_chart") as chart:
            matrix.render_holding_matrix((), ("FIRST",))
            info.assert_called_once()
            chart.assert_not_called()


def _native_matrix(app):
    return next(element for element in app.get("vega_lite_chart")
                if "holding_matrix_row" in element.proto.selection_mode)


def _matrix_click(app, ticker, *, widget_id=None):
    # Drive Streamlit's actual chart deserializer and on_select callback. The
    # AppTest API has no chart click helper, so send its native string payload.
    states = app._tree.get_widget_states()
    states.widgets.append(WidgetState(
        id=widget_id or _native_matrix(app).proto.id,
        string_value=json.dumps({"selection": {"holding_matrix_row": [{"ticker": ticker}]}}),
    ))
    return app._run(states)


def _assert_rendered_focus(state, ticker, *, language="en"):
    app = state.app
    assert not app.exception and not app.error
    assert app.selectbox(key="history_ticker").value == ticker
    assert app.session_state["history_ticker"] == ticker
    assert app.session_state["_history_focus"] == ticker
    decision = app.selectbox(key="decision_date").value
    assert app.select_slider(key="replay_date").value == decision
    assert state.history_calls[-1][0] == decision
    expected = next(row for row in state.models[decision].ranking if row.ticker == ticker)
    summary = next(element.proto.body for element in app.get("html")
                   if 'class="uq-history-security-summary"' in element.proto.body)
    assert f"<strong>{ticker}</strong>" in summary
    with language_scope(language):
        assert f'<dt>{tr("Latest recorded rank")}</dt><dd>{expected.rank}</dd>' in summary
    displayed = {row["decision_date"]: row for row in _charts(app)["rank"][1]}
    assert displayed[decision]["rank"] == expected.rank
    assert all(day <= decision for day in displayed)


def _block_unconfigured_reads(monkeypatch):
    from apps.demo_console.adapters import decision_reader, performance_reader

    def forbidden(*args, **kwargs):
        raise AssertionError("Matrix AppTest may use only the existing synthetic fixture config")

    # history_app binds its approved synthetic config to both original reader
    # calls. Any accidental fallback to the production config must fail closed.
    monkeypatch.setattr(decision_reader, "default_config", forbidden)
    monkeypatch.setattr(performance_reader, "read_performance", forbidden)


def test_native_matrix_click_updates_security_summary_and_old_event_cannot_undo_manual_choice(history_app, monkeypatch):
    state, app = history_app, history_app.app
    _block_unconfigured_reads(monkeypatch)
    _workspace_action(app, "History").run()
    original_id = _native_matrix(app).proto.id
    _matrix_click(app, "SYNTH_21")
    _assert_rendered_focus(state, "SYNTH_21")
    assert app.selectbox(key="decision_date").value == "2025-12-02"
    selected_id = _native_matrix(app).proto.id
    assert selected_id != original_id

    app.selectbox(key="history_ticker").select("SYNTH_03").run()
    _assert_rendered_focus(state, "SYNTH_03")
    manual_id = _native_matrix(app).proto.id
    assert manual_id not in {original_id, selected_id}
    _matrix_click(app, "SYNTH_21", widget_id=selected_id)
    _assert_rendered_focus(state, "SYNTH_03")
    app.run()
    _assert_rendered_focus(state, "SYNTH_03")
    assert _native_matrix(app).proto.id == manual_id

    # A fresh click on that same previously selected ticker remains usable.
    _matrix_click(app, "SYNTH_21")
    _assert_rendered_focus(state, "SYNTH_21")


def test_native_matrix_selection_keeps_raw_ticker_cutoff_and_payload_when_language_changes(history_app, monkeypatch):
    state, app = history_app, history_app.app
    _block_unconfigured_reads(monkeypatch)
    _workspace_action(app, "History").run()
    _matrix_click(app, "SYNTH_07")
    app.selectbox(key="history_window").select("All available").run()
    app.select_slider(key="replay_date").set_value("2025-12-01").run()
    _assert_rendered_focus(state, "SYNTH_07")
    fields = ("ticker", "decision_date", "execution_date", "held", "state")
    before = [tuple(row[field] for field in fields) for row in _charts(app)["ticker"][1]]
    for language in ("zh", "ja", "en"):
        app.selectbox(key="language").select(language).run()
        _assert_rendered_focus(state, "SYNTH_07", language=language)
        assert app.selectbox(key="decision_date").value == "2025-12-01"
        assert app.selectbox(key="history_window").value == "All available"
        assert [tuple(row[field] for field in fields) for row in _charts(app)["ticker"][1]] == before
        assert app.session_state["_history_focus"] == "SYNTH_07"


if __name__ == "__main__":
    unittest.main()
