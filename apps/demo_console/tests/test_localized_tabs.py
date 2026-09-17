"""Real Streamlit tab events across language changes; no data artifacts or mocks."""
from pathlib import Path
import unittest

from streamlit.proto.WidgetStates_pb2 import WidgetState
from streamlit.testing.v1 import AppTest

from apps.demo_console.i18n import catalog

_SOURCES = ("Performance path", "Consistency & concentration", "Evidence & method")


def _app_script():
    import streamlit as st
    from apps.demo_console.components.localized_tabs import localized_tabs
    from apps.demo_console.i18n import language_scope

    language = st.selectbox("Language", ("zh", "ja", "en"), key="language")
    visible = st.checkbox("Show tabs", value=True, key="visible")
    if visible:
        with language_scope(language):
            sources = st.session_state.get("test_sources", (
                "Performance path", "Consistency & concentration", "Evidence & method"))
            tabs = localized_tabs(sources, key="synthetic_tabs")
            st.session_state["native_open_states"] = tuple(tab.open for tab in tabs)
            for index, tab in enumerate(tabs):
                with tab:
                    st.text(f"All content rendered: {index}")


def _label(source, language):
    return source if language == "en" else catalog()[source][language]


def _switch_tab(app, label):
    # AppTest 1.63 exposes Tab blocks but no Tab.select(). Send the same native
    # string-value widget event the browser sends, through its real runner.
    container = app.get("tab_container")[0].proto.tab_container
    states = app._tree.get_widget_states()
    states.widgets.append(WidgetState(id=container.id, string_value=label))
    return app._run(states)


class LocalizedTabsTests(unittest.TestCase):
    def app(self):
        # The test file doubles as a self-contained synthetic app, avoiding
        # generated app files and any dependency on the production entrypoint.
        app = AppTest.from_file(str(Path(__file__)), default_timeout=10).run()
        self.healthy(app)
        return app

    def healthy(self, app, index=0):
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        if app.checkbox(key="visible").value:
            self.assertEqual(app.session_state["native_open_states"],
                             tuple(i == index for i in range(len(app.tabs))))
            self.assertEqual(app.get("tab_container")[0].proto.tab_container.default_tab_index, index)
            self.assertEqual([element.value for element in app.text],
                             [f"All content rendered: {i}" for i in range(len(app.tabs))])

    def test_second_native_tab_survives_zh_ja_en_and_all_content_still_renders(self):
        app = self.app()
        _switch_tab(app, _label(_SOURCES[1], "zh"))
        self.healthy(app, 1)
        for language in ("ja", "en", "zh"):
            app.selectbox(key="language").select(language).run()
            self.healthy(app, 1)
            self.assertEqual([tab.label for tab in app.tabs], [_label(source, language) for source in _SOURCES])
            self.assertEqual(app.session_state["synthetic_tabs"], _label(_SOURCES[1], language))
            self.assertEqual(app.session_state["_localized_tabs:synthetic_tabs"], _SOURCES[1])

    def test_user_tab_callback_updates_raw_source_before_next_render(self):
        app = self.app()
        for index in (2, 1, 0):
            _switch_tab(app, _label(_SOURCES[index], "zh"))
            self.healthy(app, index)
            self.assertEqual(app.session_state["_localized_tabs:synthetic_tabs"], _SOURCES[index])
            app.run()
            self.healthy(app, index)

    def test_leaving_and_returning_preserves_source_after_widget_state_cleanup(self):
        app = self.app()
        _switch_tab(app, _label(_SOURCES[1], "zh"))
        app.checkbox(key="visible").uncheck().run()
        self.assertFalse(app.tabs)
        self.assertNotIn("synthetic_tabs", app.session_state)
        self.assertEqual(app.session_state["_localized_tabs:synthetic_tabs"], _SOURCES[1])
        app.selectbox(key="language").select("ja").run()
        app.checkbox(key="visible").check().run()
        self.healthy(app, 1)
        self.assertEqual(app.session_state["synthetic_tabs"], _label(_SOURCES[1], "ja"))

    def test_invalid_saved_source_and_removed_source_fall_back_to_first(self):
        app = self.app()
        _switch_tab(app, _label(_SOURCES[1], "zh"))
        app.session_state["_localized_tabs:synthetic_tabs"] = "UNKNOWN_SOURCE"
        app.run()
        self.healthy(app, 0)
        self.assertEqual(app.session_state["_localized_tabs:synthetic_tabs"], _SOURCES[0])
        _switch_tab(app, _label(_SOURCES[1], "zh"))
        app.session_state["test_sources"] = (_SOURCES[0], _SOURCES[2])
        app.run()
        self.healthy(app, 0)
        self.assertEqual(app.session_state["_localized_tabs:synthetic_tabs"], _SOURCES[0])

    def test_unknown_native_label_cannot_replace_valid_saved_source(self):
        app = self.app()
        _switch_tab(app, _label(_SOURCES[1], "zh"))
        _switch_tab(app, "UNRECOGNIZED_NATIVE_LABEL")
        self.healthy(app, 1)
        self.assertEqual(app.session_state["_localized_tabs:synthetic_tabs"], _SOURCES[1])
        self.assertEqual(app.session_state["synthetic_tabs"], _label(_SOURCES[1], "zh"))


if __name__ == "__main__":
    _app_script()
