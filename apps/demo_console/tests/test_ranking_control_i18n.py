"""Synthetic native control wire labels; no history, adapters or API reads."""
import unittest


def _controls_app():
    import ast
    from pathlib import Path
    import streamlit as st
    from apps.demo_console.i18n import language_scope, tr

    from apps.demo_console.components import top20_table
    path = Path(top20_table.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "render_applied_rankings")
    assignment = lambda node, name: (isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == name for target in node.targets))
    body = next(node.body for node in ast.walk(function) if isinstance(node, (ast.FunctionDef, ast.With))
        and any(assignment(child, "controls") for child in node.body))
    start = next(i for i, node in enumerate(body) if assignment(node, "controls"))
    end = next(i for i, node in enumerate(body) if assignment(node, "selected_only"))
    # Execute the actual UI-only block; none of the renderer's imports/readers run.
    code = compile(ast.Module(body=body[start:end + 1], type_ignores=[]), str(path), "exec")
    namespace = {"st": st, "tr": tr}
    with language_scope(st.session_state.get("synthetic_language", "en")):
        exec(code, namespace)
    st.session_state["synthetic_result"] = {key: namespace[key] for key in ("count", "order", "selected_only")}


class RankingControlLanguageTests(unittest.TestCase):
    def test_selected_labels_refresh_and_canonical_order_survives_language_switch(self):
        from streamlit.testing.v1 import AppTest
        from apps.demo_console.i18n import language_scope, tr

        for order in ("Score ranking", "Portfolio weight"):
            with self.subTest(order=order):
                app = AppTest.from_function(_controls_app, default_timeout=30).run()
                self.assertFalse(app.exception)
                app.selectbox(key="applied_rank_count").select("All").run()
                app.selectbox(key="applied_rank_order").select(order).run()
                for language in ("en", "zh", "ja", "en"):
                    app.session_state["synthetic_language"] = language
                    app.run()
                    self.assertFalse(app.exception)
                    self.assertFalse(app.warning)
                    with language_scope(language):
                        for key, canonical, source in (("applied_rank_order", order, order),
                                ("applied_rank_count", "All", "All rows per strategy")):
                            widget = app.selectbox(key=key)
                            self.assertEqual(widget.value, canonical)
                            self.assertIn(tr(source), widget.proto.options)
                            self.assertTrue(widget.proto.set_value)
                            self.assertEqual(widget.proto.raw_value, tr(source))
                    self.assertEqual(app.session_state["synthetic_result"],
                        {"count": "All", "order": order, "selected_only": False})

    def test_default_sort_and_count_are_unchanged_in_each_language(self):
        from streamlit.testing.v1 import AppTest
        from apps.demo_console.i18n import language_scope, tr

        for language in ("en", "zh", "ja"):
            with self.subTest(language=language):
                app = AppTest.from_function(_controls_app, default_timeout=30)
                app.session_state["synthetic_language"] = language
                app.run()
                self.assertFalse(app.exception)
                self.assertFalse(app.warning)
                self.assertEqual(app.session_state["synthetic_result"],
                    {"count": 10, "order": "Score ranking", "selected_only": False})
                with language_scope(language):
                    self.assertEqual(app.selectbox(key="applied_rank_order").proto.raw_value, tr("Score ranking"))

    def test_invalid_saved_choices_keep_original_default_fallback(self):
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_function(_controls_app, default_timeout=30)
        app.session_state["applied_rank_count"] = "UNKNOWN"
        app.session_state["applied_rank_order"] = "UNKNOWN"
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.warning)
        self.assertEqual(app.session_state["synthetic_result"],
            {"count": 10, "order": "Score ranking", "selected_only": False})
