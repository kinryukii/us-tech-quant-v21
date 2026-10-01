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
        self.assertEqual(self.bridge.trading_url("paper", embed=True), "http://127.0.0.1:8766/paper?embed=1")
        self.assertEqual(self.bridge.trading_url("live", embed=True), "http://127.0.0.1:8766/live?embed=1")
        for invalid in ("https://example.org", "../live", "paper?url=evil", "real", ""):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.bridge.trading_url(invalid, embed=True)

    def trading_app(self, mode, *, healthy):
        import streamlit as st
        from streamlit.testing.v1 import AppTest

        def forbidden(*args, **kwargs):
            raise AssertionError("Trading page must not read research data or start a research refresh")

        patch.object(self.console, "_refresh_published_data", forbidden).start()
        patch.object(self.console, "_load_workspace_model", forbidden).start()
        patch.object(self.console.workspace_reader, "load_overview", forbidden).start()
        patch.object(self.console.updated_research_reader, "binding", forbidden).start()
        patch.object(self.bridge, "component_health", lambda: (healthy, "合成连接状态")).start()

        def synthetic_landing(pages=None):
            # AppTest's switch_page only accepts file pages. Use Streamlit's
            # public switch_page to exercise the real registered callable route.
            target = st.session_state.get("_synthetic_target")
            if target:
                st.switch_page(pages[target])
            st.write("合成研究页")
            self.bridge.render_trading_links(pages)

        patch.object(self.console, "_overview_page", synthetic_landing).start()
        app = AppTest.from_string(
            "import sys\nsys.modules['apps.demo_console._trading_candidate'].main()", default_timeout=15)
        app.session_state["_synthetic_target"] = mode
        app.session_state["_workspace_binding_seen"] = (self.console.workspace_reader.LATEST, "old-synthetic-hash")
        app.session_state["workspace"] = "History"
        app.session_state["decision_date"] = "2025-12-02"
        app.query_params["url"] = "https://example.invalid"
        return app.run()

    def check_trade_page(self, mode, title):
        app = self.trading_app(mode, healthy=True)
        self.assertFalse(app.exception)
        self.assertEqual(app.title[0].value, title)
        frames = app.get("iframe")
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].proto.src, f"http://127.0.0.1:8766/{mode}?embed=1")
        self.assertEqual({link.proto.label for link in app.get("page_link")}, {"研究工作台", "已应用策略 · 3", "模拟盘", "实盘"})
        self.assertEqual(app.session_state["workspace"], "History")
        self.assertEqual(app.session_state["decision_date"], "2025-12-02")
        if mode == "live":
            self.assertIn("实盘未授权", app.warning[0].value)
        app.button(key=f"trading_connection_{mode}").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.get("iframe")), 1)

    def test_paper_registered_page_without_research_reads(self):
        self.check_trade_page("paper", "模拟盘")

    def test_live_registered_page_without_research_reads(self):
        self.check_trade_page("live", "实盘")

    def test_unavailable_component_has_actionable_ui_without_blank_frame(self):
        for mode in ("paper", "live"):
            with self.subTest(mode=mode):
                app = self.trading_app(mode, healthy=False)
                self.assertFalse(app.exception)
                self.assertFalse(app.get("iframe"))
                self.assertEqual(app.info[0].value, "合成连接状态")
                self.assertEqual(app.subheader[0].value, "启动交易组件")
                self.assertIn("start.ps1", app.code[0].value)
                self.assertTrue(any("同一台电脑" in element.value for element in app.caption))

    def test_refresh_is_research_only_and_bridge_has_no_research_or_broker_imports(self):
        app_tree = ast.parse(_APP.read_text(encoding="utf-8-sig"))
        functions = {node.name: node for node in app_tree.body if isinstance(node, ast.FunctionDef)}
        callers = [name for name, node in functions.items()
                   if any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                          and call.func.id == "_refresh_published_data" for call in ast.walk(node))]
        self.assertEqual(callers, ["_overview_page"])
        self.assertIn("workspace_options", ast.unparse(functions["_render_historical_workspace"]))
        bridge_tree = ast.parse(_BRIDGE.read_text(encoding="utf-8-sig"))
        imports = [node.module or "" for node in ast.walk(bridge_tree) if isinstance(node, ast.ImportFrom)]
        self.assertFalse(any("adapters" in name or "research" in name or "moomoo" in name for name in imports))

    def test_existing_five_research_navigation_values_are_preserved(self):
        from apps.demo_console.components.demo_tour import workspace_options

        self.assertEqual(workspace_options("Overview"), ("Overview", "Machine learning", "Portfolio", "Research", "Evidence"))
        self.assertEqual(workspace_options("History"), ("Overview", "Machine learning", "History", "Research", "Evidence"))


if __name__ == "__main__":
    unittest.main()
