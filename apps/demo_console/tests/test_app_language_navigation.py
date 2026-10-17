"""Public language widget/navigation contracts using synthetic read-only pages."""
from contextlib import ExitStack
from pathlib import Path
import re
from unittest.mock import patch

import pytest

from apps.demo_console.i18n import catalog, language_scope, tr


def _label(source, language):
    with language_scope(language):
        return tr(source)


@pytest.fixture
def language_app():
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    from apps.demo_console import app as console
    from apps.demo_console.components import trading_workspace as bridge

    cache = {"observation_date": "2025-12-02", "strategy": "RAW_A2", "history": (1.0, 1.01)}
    before = dict(cache)
    reads = []

    def forbidden(*args, **kwargs):
        raise AssertionError("Language/navigation may not acquire, refresh, read real accounts or run models")

    def research(pages=None, *, view=None, shell=None):
        dates = st.session_state["_workbench_dates:" + st.session_state["workspace_sample"]]
        console._render_date_context(shell, dates, preferred=dates[-1])
        reads.append((view, tuple(cache.items())))
        st.write("synthetic view: " + view)
        if view in ("Portfolio", "History"):
            from apps.demo_console.pages.overview import _switch_portfolio_workspace
            st.segmented_control("Synthetic original portfolio selector", ("Portfolio", "History"),
                key="portfolio_workspace", on_change=_switch_portfolio_workspace, required=True)

    def workbench(pages, presentation):
        st.write("synthetic view: Overview")

    def cases(pages, presentation, **kwargs):
        st.write("synthetic view: Strategy applications")

    def trading(mode, pages):
        bridge.render_trading_workspace(mode, pages)

    with ExitStack() as stack:
        for name, value in (("_render_historical_workspace", research),
                            ("render_strategy_workbench", workbench), ("render_strategy_cases", cases),
                            ("render_trading_workspace", trading), ("_load_workspace_model", forbidden)):
            stack.enter_context(patch.object(console, name, value))
        for owner, name in (
                (console.workspace_reader, "load_overview"),
                (console.updated_research_reader, "binding"),
                (console.selected_strategies_reader, "load_package"),
                (console.selected_strategies_reader, "package_observation_sha256"),
                (console.new_strategy_replay_reader, "publication_observation_sha256")):
            stack.enter_context(patch.object(owner, name, forbidden))
        from apps.demo_console.adapters import applied_account_reader as accounts
        stack.enter_context(patch.object(accounts, "showcase_projection", lambda: {"showcase_ids": (
            "RAW_A2", "HGB_DIAG_5", "R7_GROSS_LINEAR", "R6_DURATION_TREE", "R10_DIRECT_H5_RIDGE_MID")}))
        def synthetic_health():
            if st.session_state.get("_synthetic_target") == "live":
                raise AssertionError("Locked live page must not query component health or accounts")
            st.session_state["_synthetic_health_calls"] = st.session_state.get("_synthetic_health_calls", 0) + 1
            return True, "本机交易组件已连接"
        stack.enter_context(patch.object(bridge, "component_health", synthetic_health))
        class NoNetwork(bridge.http.client.HTTPConnection):
            def __init__(self, *args, **kwargs):
                forbidden(*args, **kwargs)
        stack.enter_context(patch.object(bridge.http.client, "HTTPConnection", NoNetwork))
        app = AppTest.from_string("from apps.demo_console.app import main\nmain()", default_timeout=20)
        app.session_state["decision_date"] = cache["observation_date"]
        app.session_state["workspace_strategy"] = cache["strategy"]
        app.session_state["workspace_sample"] = "historical"
        app.session_state["_workbench_dates:historical"] = ("2025-11-27", "2025-11-28", "2025-12-02")
        app.session_state["_workbench_dates:test_2026"] = ("2026-01-02", "2026-01-05")
        yield app, reads, cache
    assert cache == before


def _run_page(app, route=""):
    # The real registered callable route is selected via Streamlit's page request.
    # AppTest.switch_page supports file pages only; this is its existing cold-route seam.
    from streamlit.testing.v1 import local_script_runner
    from streamlit.runtime.scriptrunner import RerunData
    def requested(*args, **kwargs):
        return RerunData(*args, **{**kwargs, "page_script_hash":"", "page_name": route})
    with patch.object(local_script_runner, "RerunData", side_effect=requested):
        return app.run()


def _gallery_container(app):
    containers = [node.proto.tab_container for node in app.get("tab_container")
                  if node.proto.tab_container.id.endswith("-technical_gallery")]
    assert len(containers) == 1
    return containers[0]


def _navigate(app, target, *, records=True):
    from apps.demo_console.tests.test_localized_tabs import _switch_tab, _open_expander
    app.session_state["_synthetic_target"] = target
    if target == "live":
        _run_page(app, "live-trading")
    else:
        if not any(node.proto.tab_container.id.endswith("-technical_gallery")
                   for node in app.get("tab_container")):
            _run_page(app)
        source = {"research":"Technical showcase", "strategies":"Strategy applications",
                  "evidence":"Data & charts", "paper":"Daily simulation"}[target]
        language = app.selectbox(key="language").value
        _switch_tab(app, _label(source, language), key="technical_gallery")
        if target == "strategies" and records:
            _switch_tab(app, _label("Decisions & portfolio", language), key="strategy_application_tools")
            _open_expander(app, "gallery_recorded_decisions")
    assert not app.exception


def _shared_shell(app, language):
    assert not app.get("page_link") and not app.get("link_button")
    assert len([w for w in app.selectbox if w.key == "language"]) == 1
    assert len([w for w in app.toggle if w.key == "presentation_mode"]) == 1
    assert not app.radio
    updates = app.main.get_by_key("uq_workbench_updates")
    assert len(updates.button) == 1 and updates.button[0].key == "reload_published_cache"
    assert len([w for w in app.button if w.key == "reload_published_cache"]) == 1
    assert len([item for item in app.get("html") if 'class="uq-gallery-identity"' in item.proto.body]) == 1
    route = app.session_state["_synthetic_target"] if "_synthetic_target" in app.session_state else "research"
    if route == "live":
        assert not app.get("tab_container")
        assert app.button(key="workbench_home").label == _label("Back to the showcase", language)
    else:
        from apps.demo_console.app import GALLERY_SECTIONS
        container = _gallery_container(app)
        source = {"research":"Technical showcase", "strategies":"Strategy applications",
                  "evidence":"Data & charts", "paper":"Daily simulation"}[route]
        assert container.default_tab_index == GALLERY_SECTIONS.index(source)
        assert app.session_state["_localized_tabs:technical_gallery"] == source
        assert all(any(tab.label == _label(item, language) for tab in app.tabs) for item in GALLERY_SECTIONS)
        assert not any(button.key == "workbench_home" for button in app.button)


def test_public_language_control_is_visible_on_paper_and_live(language_app):
    app, _, _ = language_app
    app.run()
    for route in ("paper", "live"):
        _navigate(app, route)
        language = app.selectbox(key="language")
        assert language.label == "语言 / Language"
        assert language.proto.label_visibility.value == 2
        assert language.options == ["中文", "日本語", "English"]
        assert not language.disabled
        _shared_shell(app, "en")


def test_language_round_trip_and_navigation_preserve_cache_and_context(language_app):
    app, reads, cache = language_app
    app.run()
    for language in ("zh", "en", "ja", "zh", "en"):
        app.selectbox(key="language").select(language).run()
        assert not app.exception
        for route in ("strategies", "paper", "evidence", "live", "research"):
            _navigate(app, route)
            _shared_shell(app, language)
            assert app.selectbox(key="language").value == language
            assert app.session_state["decision_date"] == cache["observation_date"]
            assert app.session_state["workspace_strategy"] == cache["strategy"]
            assert app.session_state["workspace_sample"] == "historical"
            if route in ("research", "paper", "live"):
                assert not any(w.key in ("decision_date", "workspace_sample", "workspace_strategy") for w in app.selectbox)
            else:
                date = app.selectbox(key="decision_date")
                assert date.value == cache["observation_date"]
                assert date.proto.raw_value == date.value and date.proto.set_value
                assert date.proto.default == date.options.index(date.value)
            content = "\n".join(item.value for item in (*app.markdown, *app.caption))
            if route in ("research", "strategies", "evidence"):
                view = {"research":"Overview", "strategies":"Portfolio", "evidence":"Research"}[route]
                assert "synthetic view: " + view in content
            elif route == "live":
                assert app.title[0].value == _label("Live trading", language)
                lock = "Live trading is not authorized and remains locked. This page does not unlock accounts or send live orders."
                assert app.warning[0].value == _label(lock, language)
                assert not app.get("iframe")
            else:
                assert app.get("iframe")[0].proto.src == f"http://127.0.0.1:8766/paper?embed=1&lang={language}&view=presentation"
        assert not app.selectbox(key="language").proto.query_param_key
    assert reads and all(value == tuple(cache.items()) for _, value in reads)


@pytest.mark.parametrize("value,expected", [("中文", "zh"), ("zh", "zh"), ("English", "en"), ("bogus", "en")])
def test_language_url_restore_and_invalid_value_fallback(language_app, value, expected):
    app, _, _ = language_app
    app.query_params["language"] = value
    app.run()
    assert not app.exception
    assert app.selectbox(key="language").value == expected
    _navigate(app, "paper")
    assert app.selectbox(key="language").value == expected
    assert app.get("iframe")[0].proto.src == f"http://127.0.0.1:8766/paper?embed=1&lang={expected}&view=presentation"


def test_single_presentation_switch_updates_embedded_view_without_research_reads(language_app):
    app, reads, cache = language_app
    _navigate(app, "paper")
    before = len(reads)
    for enabled, view in ((False, "research"), (True, "presentation"), (False, "research")):
        app.toggle(key="presentation_mode").set_value(enabled).run()
        assert not app.exception
        _shared_shell(app, "en")
        assert app.get("iframe")[0].proto.src.endswith("&view=" + view), (enabled, app.toggle(key="presentation_mode").value, app.session_state["presentation_mode"], type(app.session_state["presentation_mode"]).__name__)
        assert len(reads) == before
        assert app.session_state["decision_date"] == cache["observation_date"]


def test_evidence_subtabs_are_lazy_and_keep_identity_after_language_change(language_app):
    from apps.demo_console.tests.test_localized_tabs import _switch_tab
    app, reads, _ = language_app
    _navigate(app, "evidence")
    assert [view for view, _ in reads] == ["Research"]
    _switch_tab(app, _label("Data sources", "en"), key="workbench_evidence_tools")
    assert not app.exception and reads[-1][0] == "Evidence"
    app.selectbox(key="language").select("ja").run()
    assert not app.exception
    assert app.session_state["_localized_tabs:workbench_evidence_tools"] == "Data sources"
    assert app.session_state["_localized_tabs:technical_gallery"] == "Data & charts"
    previous = len(reads)
    _switch_tab(app, _label("Machine learning", "ja"), key="workbench_evidence_tools")
    assert not app.exception
    assert [name for name, _ in reads[previous:]] == ["Machine learning"]
    assert app.session_state["_localized_tabs:technical_gallery"] == "Strategy applications"
    assert app.session_state["_localized_tabs:strategy_application_tools"] == "Machine learning"
    app.selectbox(key="language").select("zh").run()
    assert not app.exception and reads[-1][0] == "Machine learning"
    assert app.session_state["_localized_tabs:strategy_application_tools"] == "Machine learning"
    # The compatibility link is consumed once; charts remains directly accessible.
    previous = len(reads)
    _switch_tab(app, _label("Data & charts", "zh"), key="technical_gallery")
    assert not app.exception
    assert app.session_state["_localized_tabs:technical_gallery"] == "Data & charts"
    assert app.session_state["_localized_tabs:workbench_evidence_tools"] == "Data sources"
    assert [name for name, _ in reads[previous:]] == ["Evidence"]



def test_legacy_context_is_restored_before_shared_widgets_and_execution_stays_read_only(language_app):
    from apps.demo_console import app as console
    app, reads, _ = language_app
    restored = {"decision_date":"2025-11-28", "workspace_strategy":"HGB_DIAG_5",
                "workspace_sample":"historical"}
    app.session_state["_applied_workspace_context"] = restored
    _navigate(app, "paper")
    for key, value in restored.items():
        assert app.session_state[key] == value
    assert not reads
    app.session_state["workspace_source"] = console.workspace_reader.FROZEN
    app.session_state["_source_date:" + console.workspace_reader.LATEST] = "2025-11-27"
    app.session_state["history_ticker"] = "SYNTHETIC"
    _navigate(app, "paper")
    assert app.session_state["decision_date"] == "2025-11-27"
    assert "history_ticker" not in app.session_state
    assert "workspace_source" not in app.session_state
    assert not reads


@pytest.mark.parametrize("saved,preferred,expected", [
    (None, "2025-11-28", "2025-11-28"),
    ("2026-01-02", "2025-11-28", "2025-11-28"),
    ("2026-01-02", None, "2025-12-02"),
    ("2025-11-27", "2025-11-28", "2025-11-27"),
])
def test_verified_date_current_preferred_latest_order_and_nonempty_wire(monkeypatch, saved, preferred, expected):
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    from apps.demo_console import app as console

    def render(preferred=None):
        import streamlit as st
        from apps.demo_console import app as console
        shell = {"date_controls":st.container(), "date_navigation":st.sidebar.container()}
        chosen = console._render_date_context(shell, ("2025-11-27", "2025-11-28", "2025-12-02"),
                                              preferred=preferred)
        st.write("chosen: " + str(chosen))
    ui = AppTest.from_function(render, args=(preferred,))
    ui.session_state["decision_date"] = saved
    ui.run()
    assert not ui.exception
    widget = ui.selectbox(key="decision_date")
    assert widget.value == expected
    assert widget.proto.raw_value == expected and widget.proto.set_value
    assert widget.proto.default == widget.options.index(expected)


def test_date_selection_none_wire_and_old_sample_recover_only_with_verified_dates(language_app):
    from streamlit.proto.WidgetStates_pb2 import WidgetState
    app, _, _ = language_app
    _navigate(app, "strategies")

    def run_open_records():
        # AppTest1.63 omits native Tab/Expander states from its widget tree.
        # Send their browser wire values alongside the changed selectbox value.
        states = app._tree.get_widget_states()
        states.widgets.append(WidgetState(id=_gallery_container(app).id,
            string_value=_label("Strategy applications", app.selectbox(key="language").value)))
        panel = next(item for item in app.expander if item.proto.id.endswith("-gallery_recorded_decisions"))
        states.widgets.append(WidgetState(id=panel.proto.id, bool_value=True))
        app._run(states)
        assert not app.exception

    app.selectbox(key="decision_date").select(None)
    run_open_records()
    assert app.selectbox(key="decision_date").value == "2025-12-02"
    app.selectbox(key="workspace_sample").select("test_2026")
    run_open_records()
    assert app.selectbox(key="decision_date").value == "2026-01-05"
    assert app.selectbox(key="decision_date").options == ["2026-01-02", "2026-01-05"]
    app.selectbox(key="workspace_sample").select("historical")
    run_open_records()
    assert app.selectbox(key="decision_date").value == "2025-12-02"


def test_empty_verified_calendar_keeps_date_unavailable_without_creating_options():
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    from apps.demo_console import app as console
    def render():
        import streamlit as st
        from apps.demo_console import app as console
        shell = {"date_controls":st.container(), "date_navigation":st.sidebar.container()}
        chosen = console._render_date_context(shell, (), preferred="2025-12-02")
        assert chosen is None
    ui = AppTest.from_function(render)
    ui.session_state["decision_date"] = "2025-12-02"
    ui.run()
    assert not ui.exception and not ui.selectbox
    assert any("No displayable decision date" in item.value for item in ui.info)


def test_shared_shell_does_not_render_untrusted_legacy_title(language_app, monkeypatch):
    from apps.demo_console import app as console
    app, _, _ = language_app
    original = console._render_shared_shell
    def title(pages, page_title=None, **kwargs):
        return original(pages, **kwargs, page_title='<script>alert("x")</script>&')
    monkeypatch.setattr(console, "_render_shared_shell", title)
    app.run()
    assert not app.exception
    html = "\n".join(item.proto.body for item in app.get("html"))
    assert 'class="uq-gallery-identity"' in html
    assert '<script>alert("x")</script>' not in html

def test_language_toolbar_leaves_native_menu_and_sidebar_controls_accessible(language_app):
    app, _, _ = language_app
    app.run()
    assert not app.exception
    assert app.main.get_by_key("uq_gallery_utilities").selectbox(key="language")
    css = (Path(__file__).parents[1] / "components/console.css").read_text(encoding="utf-8")
    native_rules = re.findall(
        r'\[data-testid="(?:stToolbar|stMainMenu|stExpandSidebarButton)"\][^{]*\{([^}]+)\}', css)
    assert not any(re.search(r"display:\s*none|visibility:\s*hidden|opacity:\s*0(?:[;!]|$)", rule)
                   for rule in native_rules)


def test_trading_wrapper_catalog_messages_preserve_translated_fields():
    import ast
    from apps.demo_console.tests.test_i18n import _placeholders

    source = Path(__file__).parents[1] / "components/trading_workspace.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    messages = {node.args[0].value for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "tr" and node.args
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "health_labels" for t in node.targets):
            messages.update(value.value for value in node.value.values)
    messages.update(("Paper trading", "Live trading"))
    for message in messages:
        for language in ("zh", "ja"):
            translated = catalog()[message][language]
            assert translated.strip()
            assert _placeholders(translated) == _placeholders(message)


def test_same_page_return_from_execution_preserves_research_context(language_app):
    app, _, cache = language_app
    _navigate(app, "paper")
    assert app.get("iframe")
    _navigate(app, "research")
    assert not app.get("iframe")
    assert any("synthetic view: Overview" in item.value for item in app.markdown)
    assert app.session_state["decision_date"] == cache["observation_date"]


def test_gallery_only_active_section_reads_and_records_require_explicit_open(language_app):
    from apps.demo_console.tests.test_localized_tabs import _open_expander
    app, reads, cache = language_app
    app.run()
    assert not app.exception and not reads and not app.get("iframe")
    assert "_synthetic_health_calls" not in app.session_state
    assert not any(w.key in ("decision_date", "workspace_sample", "workspace_strategy") for w in app.selectbox)
    _navigate(app, "strategies", records=False)
    assert not reads and not app.get("iframe")
    assert "_synthetic_health_calls" not in app.session_state
    assert not any(w.key in ("decision_date", "workspace_sample", "workspace_strategy") for w in app.selectbox)
    from apps.demo_console.tests.test_localized_tabs import _switch_tab
    _switch_tab(app, _label("Decisions & portfolio", "en"), key="strategy_application_tools")
    assert not reads  # The selected disclosure remains closed until explicitly opened.
    _open_expander(app, "gallery_recorded_decisions")
    assert [view for view, _ in reads] == ["Portfolio"]
    assert app.selectbox(key="decision_date").value == cache["observation_date"]
    previous = len(reads)
    _navigate(app, "paper")
    assert len(reads) == previous and app.get("iframe")
    assert app.session_state["_synthetic_health_calls"] == 1
    _navigate(app, "research")
    assert len(reads) == previous and not app.get("iframe")
    assert app.session_state["_synthetic_health_calls"] == 1


def test_compatibility_section_selector_rejects_unregistered_values(monkeypatch):
    from apps.demo_console import app as console
    state, calls = {}, []
    page = object()
    monkeypatch.setattr(console.st, "session_state", state)
    monkeypatch.setattr(console.st, "switch_page", calls.append)
    for source in console.GALLERY_SECTIONS:
        console._show_gallery_section(source, {"research":page})
        assert state["_localized_tabs:technical_gallery"] == source
    assert calls == [page] * 4
    before = dict(state)
    with pytest.raises(ValueError):
        console._show_gallery_section("https://example.invalid", {"research":page})
    assert state == before and len(calls) == 4


def test_case_presentation_research_switch_reuses_original_owner_and_context(language_app, monkeypatch):
    import streamlit as st
    from streamlit.proto.WidgetStates_pb2 import WidgetState
    from apps.demo_console import app as console
    from apps.demo_console.tests.test_localized_tabs import _open_expander

    app, reads, _ = language_app
    context = {"workspace_strategy":"R10_DIRECT_H5_RIDGE_MID",
               "decision_date":"2025-11-28", "workspace_sample":"historical"}
    for key, value in context.items():
        app.session_state[key] = value
    methods = []
    original_cases = console.render_strategy_cases
    def cases(pages, presentation, **kwargs):
        methods.append((presentation, st.session_state["workspace_strategy"], st.session_state["decision_date"]))
        return original_cases(pages, presentation, **kwargs)
    monkeypatch.setattr(console, "render_strategy_cases", cases)

    def switch_mode(enabled):
        app.toggle(key="presentation_mode").set_value(enabled)
        states = app._tree.get_widget_states()
        states.widgets.append(WidgetState(id=_gallery_container(app).id,
            string_value=_label("Strategy applications", app.selectbox(key="language").value)))
        app._run(states)
        assert not app.exception
        assert app.session_state["_localized_tabs:technical_gallery"] == "Strategy applications"
        for key, value in context.items():
            assert app.session_state[key] == value
        assert "_synthetic_health_calls" not in app.session_state and not app.get("iframe")

    from apps.demo_console.tests.test_localized_tabs import _switch_tab
    _navigate(app, "strategies", records=False)
    assert not reads and methods == [(True, context["workspace_strategy"], context["decision_date"])]
    assert not any(widget.key in context for widget in app.selectbox)

    switch_mode(False)
    assert not reads  # Formatting mode does not silently choose a different tool.
    assert methods[-1] == (False, context["workspace_strategy"], context["decision_date"])
    _switch_tab(app, _label("Machine learning", "en"), key="strategy_application_tools")
    assert not app.exception and reads[-1][0] == "Machine learning"
    assert app.selectbox(key="decision_date").value == context["decision_date"]
    assert app.session_state["workspace_strategy"] == context["workspace_strategy"]
    assert app.button(key="workbench_method_" + context["workspace_strategy"]).proto.type == "primary"
    read_count = len(reads)

    switch_mode(True)
    assert len(reads) == read_count + 1 and reads[-1][0] == "Machine learning"
    assert app.session_state["_localized_tabs:strategy_application_tools"] == "Machine learning"
    _switch_tab(app, _label("How this method works", "en"), key="strategy_application_tools")
    assert not app.exception and len(reads) == read_count + 1
    assert methods[-1] == (True, context["workspace_strategy"], context["decision_date"])
    assert not any(widget.key in context for widget in app.selectbox)


def test_gallery_consumes_original_history_callback_and_legacy_ml_intent(language_app):
    app, reads, cache = language_app
    _navigate(app, "strategies")
    assert reads[-1][0] == "Portfolio"
    app.segmented_control(key="portfolio_workspace").set_value("History").run()
    assert not app.exception and reads[-1][0] == "History"
    assert app.session_state["workspace"] == "History"
    app.run()
    assert reads[-1][0] == "History"
    assert app.segmented_control(key="portfolio_workspace").value == "History"
    # Existing capability callbacks write this same canonical key.
    app.session_state["workspace"] = "Machine learning"
    previous = len(reads); app.run()
    assert not app.exception
    assert [view for view, _ in reads[previous:]] == ["Machine learning"]
    assert app.session_state["_localized_tabs:technical_gallery"] == "Strategy applications"
    assert app.session_state["_localized_tabs:strategy_application_tools"] == "Machine learning"
    assert app.session_state["decision_date"] == cache["observation_date"]
    assert app.session_state["workspace_strategy"] == cache["strategy"]


def test_navigation_helper_preserves_existing_case_and_uses_canonical_route(monkeypatch):
    from apps.demo_console import app as console
    state = {"workspace_strategy": "R10_DIRECT_H5_RIDGE_MID", "decision_date": "2025-12-02",
        "workspace_sample": "historical", "_research_case_ticker": "SYNTH_CASE"}
    monkeypatch.setattr(console.st, "session_state", state)
    monkeypatch.setattr(console, "pause_replay", lambda **kwargs: None)
    before = dict(state)
    console.navigate_workspace("Machine learning", strategy_id=state["workspace_strategy"])
    assert {key:state[key] for key in before} == before
    assert state["workspace"] == "Machine learning"
    assert state["_localized_tabs:technical_gallery"] == "Strategy applications"
    assert state["_localized_tabs:strategy_application_tools"] == "Machine learning"
    console.navigate_workspace("History")
    assert state["portfolio_workspace"] == "History" and state["gallery_recorded_decisions"] is True
    assert state["_localized_tabs:strategy_application_tools"] == "Decisions & portfolio"
    for view, sid in (("INVALID", None), ("Machine learning", "UNKNOWN")):
        saved = dict(state)
        with pytest.raises(ValueError):
            console.navigate_workspace(view, strategy_id=sid)
        assert state == saved


@pytest.mark.parametrize("strategy", ("HGB_DIAG_5", "R10_DIRECT_MEAN4_ELASTICNET_MID",
    "R10_DIRECT_H5_RIDGE_MID", "R7_GROSS_LINEAR"))
@pytest.mark.parametrize("sample,ahead", (("historical",False), ("test_2026",False), ("test_2026",True)))
def test_selected_ml_route_uses_light_context_without_raw_or_five_history_reads(monkeypatch, strategy, sample, ahead):
    from streamlit.testing.v1 import AppTest
    from apps.demo_console import app as console
    from apps.demo_console.models import DecisionOverview
    from apps.demo_console.adapters import workspace_reader, selected_strategies_reader, applied_account_reader
    from apps.demo_console.pages import selected_strategies
    observed = []
    dates = () if sample == "historical" else ("2026-01-02", "2026-01-05")
    query = "2025-12-02" if sample == "historical" else "2026-01-07" if ahead else "2026-01-05"
    native = strategy not in selected_strategies_reader.STRATEGY_IDS
    package = {"package_sha256":"ab"*32} if sample == "test_2026" and not native else {}
    account_capture = {"synthetic": True}
    requested = [query]
    def forbidden(*args, **kwargs):
        raise AssertionError("Selected ML must not load Raw, full histories, accounts or models")
    for owner, name in ((console,"_load_workspace_model"), (workspace_reader,"load_overview"),
            (workspace_reader,"load_selected_overview"), (workspace_reader,"applied_observation_dates")):
        monkeypatch.setattr(owner,name,forbidden)
    def load_package(*, include_performance):
        assert sample == "test_2026" and include_performance is False
        observed.append("package")
        return package
    monkeypatch.setattr(selected_strategies_reader,"load_package",load_package)
    def package_calendar():
        assert sample == "test_2026" and native
        observed.append("package_calendar")
        return {"available_dates": dates, "package_sha256": "ab"*32}
    monkeypatch.setattr(selected_strategies_reader, "load_workspace_calendar", package_calendar)
    def capture():
        assert sample == "test_2026"
        observed.append("capture")
        return account_capture
    monkeypatch.setattr(applied_account_reader, "load_state", capture)
    def calendar(received, *, sample, account_state, package_dates):
        assert received == package
        assert account_state is (account_capture if sample == "test_2026" else None)
        assert package_dates == (dates if native and sample == "test_2026" else None)
        observed.append("calendar")
        return dates
    def overview(sid, day=None, *, sample, observation_dates):
        assert (sid,day,sample,tuple(observation_dates)) == (strategy,requested[0],sample,dates)
        observed.append("light")
        return DecisionOverview(decision_date=requested[0] if sample=="test_2026" else None, available_dates=dates)
    monkeypatch.setattr(workspace_reader,"ml_observation_dates",calendar)
    monkeypatch.setattr(workspace_reader,"load_ml_overview",overview)
    def render(model, selected_package, *, presentation, view, account_state):
        assert view == "Machine learning" and selected_package == package
        assert account_state is (account_capture if sample == "test_2026" else None)
        observed.append("render")
    monkeypatch.setattr(console, "render_overview", forbidden)
    monkeypatch.setattr(selected_strategies, "render_workspace", render)
    def script():
        from apps.demo_console import app as console
        shell = console._render_shared_shell({})
        console._render_record_controls(shell)
        console._render_historical_workspace(view="Machine learning", shell=shell)
    app = AppTest.from_function(script,default_timeout=20)
    app.session_state["language"]="en"
    app.session_state["workspace_strategy"]=strategy
    app.session_state["workspace_sample"]=sample
    app.session_state["decision_date"]=query
    app.run()
    assert not app.exception and not app.error
    expected = (["calendar", "light", "render"] if sample == "historical" else
        ["package_calendar" if native else "package", "capture", "calendar", "light", "render"])
    assert observed == expected
    assert app.session_state["decision_date"] == query
    if ahead:
        assert app.button(key="ml_latest_recorded_observation")
        requested[0] = dates[-1]
        observed.clear()
        app.button(key="ml_latest_recorded_observation").click().run()
        assert not app.exception and not app.error
        assert app.session_state["decision_date"] == dates[-1]
        assert app.selectbox(key="decision_date").value == dates[-1]
        assert observed == expected
    else:
        assert not any(button.key == "ml_latest_recorded_observation" for button in app.button)


def test_original_exhibit_execution_callback_is_display_only(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from apps.demo_console import app as console
    def forbidden(*a, **k):
        raise AssertionError("Navigation cannot read data, prepare plans or invoke execution")
    monkeypatch.setattr(console,"_load_workspace_model",forbidden)
    monkeypatch.setattr(console,"render_trading_workspace",forbidden)
    def script():
        import streamlit as st
        from apps.demo_console.components.strategy_workbench import _open_view
        st.button("Synthetic exhibit execution CTA",key="exhibit_execution_test",
            on_click=_open_view,args=("Execution",))
        st.write(st.session_state.get("_localized_tabs:technical_gallery",""))
    app=AppTest.from_function(script,default_timeout=20)
    app.session_state["workspace_strategy"]="R10_DIRECT_H5_RIDGE_MID"
    app.session_state["workspace_sample"]="historical"
    app.session_state["decision_date"]="2025-12-02"
    app.run();app.button(key="exhibit_execution_test").click().run()
    assert not app.exception
    assert app.session_state["_localized_tabs:technical_gallery"]=="Daily simulation"
    assert app.session_state["workspace"]=="Execution"
    assert app.session_state["decision_date"]=="2025-12-02"
    assert app.session_state["workspace_strategy"]=="R10_DIRECT_H5_RIDGE_MID"


@pytest.mark.parametrize("strategy",("HGB_DIAG_5","R10_DIRECT_H5_RIDGE_MID"))
@pytest.mark.parametrize("sample",("historical","test_2026"))
def test_ml_cache_refresh_compares_base_identity_without_overlay_or_raw_fallback(monkeypatch,strategy,sample):
    from streamlit.testing.v1 import AppTest
    from apps.demo_console import app as console
    from apps.demo_console.adapters import selected_strategies_reader,updated_research_reader,new_strategy_replay_reader
    calls=[]
    def observed(*,include_performance):
        assert include_performance is False
        calls.append("base_package")
        return "synthetic_base_sha"
    def forbidden(*a,**k):
        raise AssertionError("ML cache check must not read a full overlay or Raw binding")
    monkeypatch.setattr(selected_strategies_reader,"package_observation_sha256",observed)
    monkeypatch.setattr(updated_research_reader,"binding",forbidden)
    monkeypatch.setattr(new_strategy_replay_reader,"publication_observation_sha256",
        lambda:"synthetic_pointer")
    def script():
        import streamlit as st
        from apps.demo_console import app as console
        console._refresh_published_data(target=st.container())
    app=AppTest.from_function(script,default_timeout=20)
    app.session_state["workspace"]="Machine learning"
    app.session_state["workspace_strategy"]=strategy
    app.session_state["workspace_sample"]=sample
    app.session_state["_selected_strategy_binding_seen"]="synthetic_base_sha"
    app.session_state["_new_strategy_extension_binding_seen"]="synthetic_pointer"
    app.session_state["_workspace_binding_seen"]=("LATEST","unrelated_raw")
    app.run();app.button(key="reload_published_cache").click().run()
    assert not app.exception and not app.error
    assert calls==([] if sample=="historical" else ["base_package"])
    assert "_published_cache_notice" not in app.session_state


@pytest.mark.parametrize("language",("en","zh","ja"))
def test_record_views_keep_one_primary_header_and_compact_gallery_context(language_app,language):
    from apps.demo_console.tests.test_localized_tabs import _switch_tab
    app,reads,cache=language_app
    app.run();app.selectbox(key="language").select(language).run()
    _navigate(app,"strategies",records=False)
    def html():
        from html import unescape
        return [unescape(node.proto.body) for node in app.get("html")]
    assert sum('class="uq-gallery-section"' in body and '<h1>' in body for body in html())==1
    assert any(_label("Five methods. A shared engineering foundation.",language) in body for body in html())
    _switch_tab(app,_label("Machine learning",language),key="strategy_application_tools")
    assert not app.exception and reads[-1][0]=="Machine learning"
    for route in ("Machine learning","Portfolio"):
        if route=="Portfolio":
            _navigate(app,"strategies")
        bodies=html()
        assert not any('class="uq-gallery-section"' in body for body in bodies)
        crumbs=[body for body in bodies if 'class="uq-gallery-breadcrumb"' in body]
        assert len(crumbs)==1 and "02 / " in crumbs[0]
        assert _label("Strategy applications",language) in crumbs[0] and '<h1>' not in crumbs[0]
        assert app.selectbox(key="decision_date").value==cache["observation_date"]
        assert reads[-1][0]==route
    _navigate(app,"evidence")
    for source,view in (("Performance & risk","Research"),("Data sources","Evidence")):
        _switch_tab(app,_label(source,language),key="workbench_evidence_tools")
        assert not app.exception and reads[-1][0]==view
        bodies=html()
        assert not any('class="uq-gallery-section"' in body for body in bodies)
        crumbs=[body for body in bodies if 'class="uq-gallery-breadcrumb"' in body]
        assert len(crumbs)==1 and "03 / " in crumbs[0]
        assert _label("Data & charts",language) in crumbs[0] and '<h1>' not in crumbs[0]
    assert app.session_state["decision_date"]==cache["observation_date"]
    assert app.session_state["workspace_strategy"]==cache["strategy"]


def test_five_method_focus_is_shared_by_all_application_tools_without_duplicate_selector(language_app):
    from apps.demo_console.tests.test_localized_tabs import _switch_tab
    app, _, cache = language_app
    _navigate(app, "strategies", records=False)
    expected = {"workbench_method_" + sid for sid in (
        "RAW_A2", "HGB_DIAG_5", "R7_GROSS_LINEAR", "R6_DURATION_TREE", "R10_DIRECT_H5_RIDGE_MID")}
    for tool in ("How this method works", "Machine learning", "Decisions & portfolio"):
        _switch_tab(app, _label(tool, "en"), key="strategy_application_tools")
        assert not app.exception
        assert expected <= {button.key for button in app.button}
        assert not any(widget.key == "workspace_strategy" for widget in app.selectbox)
        assert app.session_state["decision_date"] == cache["observation_date"]
