"""Synthetic bridge tests: no broker, research artifact, or real health endpoint."""
from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

_STAGED = Path(__file__).with_name("trading_workspace.py").is_file()
_APP = Path(__file__).with_name("app.py") if _STAGED else Path(__file__).parents[1] / "app.py"
_BRIDGE = (Path(__file__).with_name("trading_workspace.py") if _STAGED
           else Path(__file__).parents[1] / "components" / "trading_workspace.py")
_HEALTH = {"ok": True, "data": {"component": "moomoo-trading-component", "api_version": 1,
           "live_execution_enabled": False, "pages": ["paper", "live"]}}


class TradingWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        loaded = []
        for name, path in (("apps.demo_console.components.trading_workspace", _BRIDGE),
                           ("apps.demo_console._trading_candidate", _APP)):
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            # Restore only these aliases: restoring all sys.modules also unloads
            # native dependencies imported by the app, which cannot be reloaded.
            if name in sys.modules:
                self.addCleanup(sys.modules.__setitem__, name, sys.modules[name])
            else:
                self.addCleanup(sys.modules.pop, name, None)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            loaded.append(module)
        self.bridge, self.console = loaded

    def fake_connection(self, payload, status=200, failure=None):
        calls = []

        class Connection:
            def __init__(self, host, port, *, timeout):
                calls.append(("connect", host, port, timeout))

            def request(self, method, path, *, headers):
                calls.append(("request", method, path, headers))
                if failure:
                    raise failure

            def getresponse(self):
                return self

            def read(self, size):
                calls.append(("read", size))
                return payload[:size]

            def close(self):
                calls.append(("close",))

        Connection.status = status
        patch.object(self.bridge.http.client, "HTTPConnection", Connection).start()
        return calls

    def test_health_is_fixed_bounded_read_and_checks_identity(self):
        calls = self.fake_connection(json.dumps(_HEALTH).encode())
        self.assertEqual(self.bridge.component_health(), (True, "本机交易组件已连接"))
        self.assertEqual(calls, [("connect", "127.0.0.1", 8766, 1),
                         ("request", "GET", "/api/health", {"Accept": "application/json"}),
                         ("read", 8193), ("close",)])

    def test_health_rejects_incompatible_or_unlocked_service(self):
        for change in ({"component": "another-service"}, {"api_version": 2}, {"api_version": True},
                       {"live_execution_enabled": True}, {"live_execution_enabled": None},
                       {"pages": ["paper"]}, {"pages": "paper,live"}):
            with self.subTest(change=change):
                calls = self.fake_connection(json.dumps({"ok": True, "data": {**_HEALTH["data"], **change}}).encode())
                self.assertIs(self.bridge.component_health()[0], False)
                self.assertEqual(calls[-1], ("close",))

    def test_health_fails_closed_on_bad_or_redirected_response(self):
        for payload, status in ((b"[]", 200), (b"null", 200), (b"{}", 200), (b"not json", 200),
                                (b"x" * 8193, 200), (json.dumps(_HEALTH).encode(), 302),
                                (b'{"ok":false,"data":{}}', 200)):
            with self.subTest(payload=payload[:35], status=status):
                calls = self.fake_connection(payload, status=status)
                self.assertIs(self.bridge.component_health()[0], False)
                self.assertEqual(calls[-1], ("close",))

    def test_health_timeout_is_readable_and_closes_socket(self):
        calls = self.fake_connection(b"", failure=TimeoutError())
        self.assertEqual(self.bridge.component_health(), (False, "尚未连接到本机交易组件。"))
        self.assertEqual(calls[-1], ("close",))

    def test_frame_destination_cannot_be_overridden(self):
        self.assertEqual(self.bridge.trading_url("paper", embed=True, language="zh", presentation=True), "http://127.0.0.1:8766/paper?embed=1&lang=zh&view=presentation")
        self.assertEqual(self.bridge.trading_url("live", embed=True, language="ja", presentation=False), "http://127.0.0.1:8766/live?embed=1&lang=ja&view=research")
        self.assertEqual(self.bridge.trading_url("paper", language="en", presentation=True), "http://127.0.0.1:8766/paper?lang=en&view=presentation")
        self.assertEqual(self.bridge.trading_url("paper", language="zh&url=evil", presentation="evil"), "http://127.0.0.1:8766/paper?lang=en&view=presentation")
        for invalid in ("https://example.org", "../live", "paper?url=evil", "real", ""):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.bridge.trading_url(invalid, embed=True)

    def trading_app(self, mode, *, healthy):
        import streamlit as st
        from streamlit.testing.v1 import AppTest
        from streamlit.testing.v1 import local_script_runner
        from streamlit.runtime.scriptrunner import RerunData

        def forbidden(*args, **kwargs):
            raise AssertionError("Trading page must not read research data or start a research refresh")

        patch.object(self.console, "_load_workspace_model", forbidden).start()
        patch.object(self.console.workspace_reader, "load_overview", forbidden).start()
        patch.object(self.console.updated_research_reader, "binding", forbidden).start()
        def synthetic_health():
            if mode == "live":
                raise AssertionError("Locked live page must not query component health or accounts")
            return healthy, "合成连接状态"
        patch.object(self.bridge, "component_health", synthetic_health).start()

        def synthetic_landing(pages=None, *, view=None, shell=None):
            st.write("合成研究页")
        patch.object(self.console, "_render_historical_workspace", synthetic_landing).start()
        patch.object(self.console, "render_strategy_workbench",
            lambda pages, presentation: synthetic_landing(pages, view="Overview")).start()
        patch.object(self.console, "render_strategy_cases",
            lambda pages, presentation: st.write("合成策略页")).start()
        app = AppTest.from_string(
            "import sys\nsys.modules['apps.demo_console._trading_candidate'].main()", default_timeout=15)
        app.session_state["_localized_tabs:technical_gallery"] = "Daily simulation"
        app.session_state["_workspace_binding_seen"] = (self.console.workspace_reader.LATEST, "old-synthetic-hash")
        app.session_state["workspace"] = "History"
        app.session_state["decision_date"] = "2025-12-02"
        app.query_params["url"] = "https://example.invalid"
        app.query_params["language"] = "中文"
        if mode == "live":
            def requested(*args, **kwargs):
                return RerunData(*args, **{**kwargs, "page_script_hash":"", "page_name":"live-trading"})
            with patch.object(local_script_runner, "RerunData", side_effect=requested):
                return app.run()
        return app.run()

    def check_trade_page(self, mode, title):
        app = self.trading_app(mode, healthy=True)
        self.assertFalse(app.exception)
        if mode == "paper":
            self.assertFalse(app.title)
        else:
            self.assertEqual(app.title[0].value, title)
        frames = app.get("iframe")
        if mode == "paper":
            self.assertEqual(len(frames), 1)
            self.assertEqual(frames[0].proto.src, "http://127.0.0.1:8766/paper?embed=1&lang=zh&view=presentation")
        else:
            self.assertFalse(frames)
            self.assertFalse(any(item.proto.label == "连接详情" for item in app.expander))
        self.assertFalse(app.get("link_button"))
        self.assertFalse(app.get("page_link"))
        from apps.demo_console.i18n import language_scope, tr
        with language_scope("zh"):
            if mode == "paper":
                self.assertEqual([tab.label for tab in app.tabs], [tr(label) for label in self.console.GALLERY_SECTIONS])
                self.assertTrue(any(tr("From plan to confirmed fills.") in item.proto.body for item in app.get("html")))
            else:
                self.assertFalse(app.tabs)
                self.assertEqual(app.button(key="workbench_home").label, tr("Back to the showcase"))
        self.assertFalse(any(w.key in ("decision_date", "workspace_sample", "workspace_strategy") for w in app.selectbox))
        self.assertEqual(len([item for item in app.toggle if item.key == "presentation_mode"]), 1)
        self.assertEqual(app.session_state["workspace"], "History")
        self.assertEqual(app.session_state["decision_date"], "2025-12-02")
        if mode == "live":
            self.assertIn("实盘未授权", app.warning[0].value)
        if mode == "paper":
            app.button(key="trading_connection_paper").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.get("iframe")), 1)
        else:
            self.assertFalse(any(button.key == "trading_connection_live" for button in app.button))

    def test_paper_registered_page_without_research_reads(self):
        self.check_trade_page("paper", "模拟盘")

    def test_paper_frame_stretches_within_its_single_bounded_container(self):
        import streamlit as st
        with patch.object(st, "iframe", wraps=st.iframe) as iframe:
            app=self.trading_app("paper",healthy=True)
        self.assertFalse(app.exception)
        self.assertEqual(len(iframe.call_args_list),1)
        self.assertEqual(iframe.call_args.kwargs["height"],"stretch")
        self.assertEqual(iframe.call_args.kwargs["width"],"stretch")
        container=app.main.get_by_key("trading_component_frame")
        self.assertTrue(container.proto.height_config.use_stretch)
        self.assertFalse(container.proto.height_config.HasField("pixel_height"))
        self.assertFalse(container.proto.flex_container.border)
        self.assertEqual(len(container.get("iframe")),1)

    def test_shared_native_navigation_keeps_context_on_return_to_research(self):
        from apps.demo_console.tests.test_localized_tabs import _switch_tab
        from apps.demo_console.i18n import language_scope, tr
        app = self.trading_app("paper", healthy=True)
        self.assertFalse(app.exception)
        with language_scope("zh"):
            _switch_tab(app, tr("Technical showcase"), key="technical_gallery")
        self.assertFalse(app.exception)
        self.assertFalse(app.get("iframe"))
        self.assertTrue(any(item.value == "合成研究页" for item in app.markdown))
        self.assertEqual(app.session_state["workspace"], "History")
        self.assertEqual(app.session_state["decision_date"], "2025-12-02")

    def test_live_registered_page_without_research_reads(self):
        self.check_trade_page("live", "实盘")

    def test_unavailable_component_has_actionable_ui_without_blank_frame(self):
        for mode in ("paper", "live"):
            with self.subTest(mode=mode):
                app = self.trading_app(mode, healthy=False)
                self.assertFalse(app.exception)
                self.assertFalse(app.get("iframe"))
                if mode == "live":
                    self.assertIn("实盘未授权", app.warning[0].value)
                    self.assertFalse(app.info)
                    self.assertFalse(any("start.ps1" in item.value for item in app.code))
                    continue
                self.assertEqual(app.info[0].value, "合成连接状态")
                self.assertTrue(any(item.value == "启动交易组件" for item in app.subheader))
                command = next(item.value for item in app.code if "start.ps1" in item.value)
                self.assertIn("-ManualDataUpdates", command)
                self.assertIn("-WithMoomooBest", command)
                self.assertNotIn("-ActivateStrategies", command)
                self.assertTrue(any("同一台电脑" in element.value for element in app.caption))

    def test_refresh_is_single_shared_control_and_bridge_has_no_research_or_broker_imports(self):
        app_tree = ast.parse(_APP.read_text(encoding="utf-8-sig"))
        functions = {node.name: node for node in app_tree.body if isinstance(node, ast.FunctionDef)}
        callers = [name for name, node in functions.items()
                   if any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                          and call.func.id == "_refresh_published_data" for call in ast.walk(node))]
        self.assertEqual(callers, ["main"])
        self.assertIn('target=shell[\'refresh_controls\']', ast.unparse(functions["main"]))
        self.assertNotIn("radio", ast.unparse(functions["_render_shared_shell"]))
        bridge_tree = ast.parse(_BRIDGE.read_text(encoding="utf-8-sig"))
        imports = [node.module or "" for node in ast.walk(bridge_tree) if isinstance(node, ast.ImportFrom)]
        self.assertFalse(any("adapters" in name or "research" in name or "moomoo" in name for name in imports))

    def _cold_entry_route(self, entry, route):
        import streamlit as st
        from streamlit.testing.v1 import AppTest
        from streamlit.testing.v1 import local_script_runner
        from streamlit.runtime.pages_manager import PagesManager
        from streamlit.runtime.scriptrunner import RerunData
        calls=[];messages=[];cold_flags=[]
        def forbidden(*args,**kwargs):raise AssertionError("Cold routing must not read research, models or actual broker")
        for owner,name in ((self.console,"_load_workspace_model"),
            (self.console.workspace_reader,"load_overview"),(self.console.updated_research_reader,"binding")):
            patch.object(owner,name,forbidden).start()
        patch.object(self.console,"render_strategy_workbench",lambda pages,presentation:(calls.append("root"),st.write("synthetic root"))).start()
        patch.object(self.console,"render_strategy_cases",lambda pages,presentation:(calls.append("cases"),st.write("synthetic cases"))).start()
        patch.object(self.console,"_render_historical_workspace",lambda pages,view=None,shell=None:(calls.append("records:"+view),st.write("synthetic records"))).start()
        patch.object(self.console,"render_trading_workspace",lambda mode,pages:(calls.append(mode),st.write("synthetic "+mode))).start()
        patch.dict(sys.modules,{"apps.demo_console.app":self.console}).start()
        original_init=PagesManager.__init__;original_run=local_script_runner.LocalScriptRunner.run
        def initialize(manager,*args,**kwargs):
            original_init(manager,*args,**kwargs);cold_flags.append(PagesManager.uses_pages_directory)
        def run(runner,*args,**kwargs):
            result=original_run(runner,*args,**kwargs);messages.extend(runner.forward_msgs());return result
        def requested_route(*args,**kwargs):return RerunData(*args,**{**kwargs,"page_script_hash":"","page_name":route})
        with patch.object(PagesManager,"uses_pages_directory",None),patch.object(PagesManager,"__init__",initialize),\
            patch.object(local_script_runner,"RerunData",side_effect=requested_route),\
            patch.object(local_script_runner.LocalScriptRunner,"run",run):
            app=AppTest.from_file(entry,default_timeout=15).run()
        return app,calls,[msg.page_not_found.page_name for msg in messages if msg.WhichOneof("type")=="page_not_found"],cold_flags

    def test_fresh_entry_resolves_paper_live_root_and_keeps_unknown_route_failure(self):
        entry=_APP.parent/"launch/app.py"
        self.assertFalse((entry.parent/"pages").exists())
        for route,expected,section in (
                ("paper-trading",["paper"],"Daily simulation"),
                ("strategies",["cases","records:Portfolio"],"Strategy applications"),
                ("evidence",["records:Research"],"Data & charts"),
                ("live-trading",["live"],None),("",["root"],"Technical showcase"),
                ("unknown-route",["root"],"Technical showcase")):
            with self.subTest(route=route):
                app,calls,missing,flags=self._cold_entry_route(entry,route)
                self.assertFalse(app.exception);self.assertEqual(flags,[False]);self.assertEqual(calls,expected)
                self.assertEqual(bool(missing),route=="unknown-route")
                self.assertEqual({p["url_pathname"] for p in app._registered_pages.values()},
                    {"","strategies","paper-trading","evidence","live-trading"})
                if section is not None:
                    self.assertEqual(app.session_state["_localized_tabs:technical_gallery"],section)
                    self.assertEqual(len(app.main.get_by_key("uq_gallery_header").selectbox),1)

    def test_original_entry_preserves_compatibility_route_without_data_reads(self):
        # The direct entry still resolves the old URL into the same unified tab.
        import streamlit as st
        patch.object(self.bridge,"component_health",return_value=(False,"synthetic component unavailable")).start()
        app,calls,missing,flags=self._cold_entry_route(_APP,"paper-trading")
        self.assertFalse(app.exception);self.assertEqual(flags,[True]);self.assertFalse(missing)
        self.assertFalse(calls)  # Original file is exec'd, not our imported synthetic renderers.
        self.assertTrue(any(item.value=="synthetic component unavailable" for item in app.info))
        self.assertEqual(app.session_state["_localized_tabs:technical_gallery"],"Daily simulation")

    def test_cold_entry_is_only_existing_main_call_and_original_launcher_selects_it(self):
        entry=_APP.parent/"launch/app.py";tree=ast.parse(entry.read_text(encoding="utf-8"))
        imported=[node for node in tree.body if isinstance(node,ast.ImportFrom)]
        self.assertEqual(len(imported),1);self.assertEqual(imported[0].module,"apps.demo_console.app")
        self.assertEqual([item.name for item in imported[0].names],["main"])
        calls=[node for node in ast.walk(tree) if isinstance(node,ast.Call)]
        self.assertEqual({ast.unparse(call.func) for call in calls},{"os.environ.setdefault","main"})
        self.assertEqual(sum(ast.unparse(call.func)=="main" for call in calls),1)
        self.assertFalse(any(isinstance(node,(ast.FunctionDef,ast.ClassDef)) for node in ast.walk(tree)))
        launcher=(_APP.parent/"start.ps1").read_text(encoding="utf-8")
        self.assertEqual(launcher.count("streamlit run launch/app.py"),1)
        self.assertIn("Push-Location $PSScriptRoot",launcher)
        self.assertIn("$env:PYTHONPATH = $repo",launcher)
        self.assertNotIn("--theme.",launcher)
        self.assertNotIn("streamlit run apps/demo_console/app.py",launcher)

    def test_demo_thread_defaults_precede_main_and_preserve_explicit_environment(self):
        import os
        import runpy
        from types import ModuleType
        keys=("OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS")
        original=dict(os.environ)
        for overrides in ({},{"OPENBLAS_NUM_THREADS":"2"},{key:"4" for key in keys}):
            with self.subTest(overrides=overrides):
                snapshot={key:value for key,value in original.items() if key not in keys}
                snapshot.update(overrides)
                calls=[]; fake=ModuleType("apps.demo_console.app")
                fake.main=lambda:calls.append({key:os.environ.get(key) for key in keys})
                with patch.dict(os.environ,snapshot,clear=True),patch.dict(sys.modules,{"apps.demo_console.app":fake}):
                    runpy.run_path(str(_APP.parent/"launch/app.py"),run_name="__main__")
                    self.assertEqual(calls,[{key:overrides.get(key,"1") for key in keys}])
                self.assertEqual(dict(os.environ),original)

    def test_existing_five_research_navigation_values_are_preserved(self):
        from apps.demo_console.components.demo_tour import workspace_options

        self.assertEqual(workspace_options("Overview"), ("Overview", "Machine learning", "Portfolio", "Research", "Evidence"))
        self.assertEqual(workspace_options("History"), ("Overview", "Machine learning", "History", "Research", "Evidence"))


if __name__ == "__main__":
    unittest.main()
