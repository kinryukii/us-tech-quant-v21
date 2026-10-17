"""Synthetic package and page tests; never query data providers or brokerage accounts."""
from __future__ import annotations

from copy import deepcopy
import csv
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from apps.demo_console.adapters import selected_strategies_reader as reader
from apps.demo_console.components.chart_display import chart_for_display
from apps.demo_console.pages import selected_strategies as page


def package():
    strategies = {}
    for index, strategy_id in enumerate(reader.STRATEGY_IDS):
        nav, weight = (1.05, 0.8) if index == 0 else (1.02, 0.4)
        strategies[strategy_id] = {"label": "HGB + 对角风险" if index == 0 else "HGB + 因子 / 收缩风险",
            "summary": {"end_nav": nav, "cumulative_return": nav - 1, "max_drawdown": 0,
                        "mean_cash": 1 - weight, "days": 2, "turnover": weight},
            "daily": [{"date": "2026-01-05", "nav": 1.0, "cash_weight": 1 - weight},
                      {"date": "2026-01-06", "nav": nav, "cash_weight": 1 - weight}],
            "targets": [{"signal_date": "2026-01-02", "rows": [{"ticker": "AAPL", "target_weight": weight,
                          "weight_before": 0.0, "action": "BUY"}]},
                        {"signal_date": "2026-01-05", "rows": [{"ticker": "MSFT", "target_weight": weight,
                          "weight_before": 0.0, "action": "BUY"}]}],
            "application": {"status": "READY", "signal_date": "2026-02-02", "account_basis": "CASH_START",
                "account_label": "空仓账户目标方案", "reason": "",
                "rows": [{"ticker": "AAPL" if index == 0 else "MSFT", "target_weight": weight,
                          "weight_before": 0.0, "action": "BUY"}], "target_cash_weight": 1 - weight}}
    return {"schema_version": 1, "generated_at": "2026-02-03T01:00:00+00:00",
        "selection_basis": reader.SELECTION_BASIS,
        "performance_period": {"start": "2026-01-05", "end": "2026-01-06", "days": 2,
            "price_basis": "QFQ_PRICE_COORDINATE_PROXY", "decision_clock": "SIGNAL_CLOSE_NEXT_SESSION_OPEN"},
        "source_hashes": {"history/top40.parquet": "ab" * 32},
        "source_refs": {"history/top40.parquet": {"path": "C:/synthetic/top40.parquet", "sha256": "ab" * 32}},
        "strategies": strategies}


def history_package(policy="RAW_TOP20_FROZEN_LEGACY"):
    """Reverse Raw/HGB ranks so candidate membership is distinguishable."""
    payload = package()
    day = "2026-01-30"
    direct = policy == "HGB_TOP20_RISK_R1"
    if direct:
        payload["policy_id"] = policy
    reference = "history/" + day + ".json"
    payload["source_hashes"][reference] = "cd" * 32
    payload["source_refs"][reference] = {"path": "C:/synthetic/" + day + ".json", "sha256": "cd" * 32}
    payload["shared_scores"] = {"model_id": "HGB_2026092501", "model_sha256": "ef" * 32,
        "scoring_scope": "RAW_TOP40", "ranking_basis": "PRED_HGB_DESC_TICKER_ASC",
        "historical": [{"signal_date": day, "ticker": "T" + str(rank), "security_id": str(rank),
                        "raw_rank": rank, "raw_score": rank / 100, "pred_hgb": rank / 100,
                        "hgb_rank": 41 - rank} for rank in range(1, 41)],
        "current": {"status": "UNAVAILABLE", "signal_date": None, "requested_signal_date": None,
                    "rows": [], "reason": "Synthetic history-only score fixture"}}
    for strategy in payload["strategies"].values():
        if direct:
            strategy["application"]["policy_id"] = policy
        app = {"status": "READY", "signal_date": day, "requested_signal_date": day,
            "account_basis": "CASH_START", "rows": [{"ticker": "T40" if direct else "T1",
            "target_weight": .1, "weight_before": 0., "action": "BUY"}],
            "target_cash_weight": .9, "cash_weight_before": 1.,
            "decision_clock": "SIGNAL_CLOSE_NEXT_SESSION_OPEN", "broker_action_allowed": False,
            "model_fit_calls": 0, "execution_status": "TARGET_ONLY", "kind": "ARCHIVED_CASH_START_TARGET",
            "reason": "", "account_label": "Synthetic archived cash-start target", "source_ref": reference}
        if direct:
            app["policy_id"] = policy
        strategy["application_history"] = [app]
    return payload


class SelectedReaderTests(unittest.TestCase):
    def setUp(self):
        reader.clear_cache()

    def test_valid_package_and_available_signal_status(self):
        payload = package()
        self.assertIs(reader.validate_package(payload), payload)
        application = payload["strategies"][reader.STRATEGY_IDS[0]]["application"]
        application["status"] = "LATEST_AVAILABLE_SIGNAL"
        application["reason"] = "最新一日尚缺输入；保留完整信号日。"
        self.assertIs(reader.validate_package(payload), payload)
        application.update(status="BLOCKED", rows=[], reason="当前输入不完整")
        self.assertIs(reader.validate_package(payload), payload)

    def test_reject_invalid_identity_clock_dates_weights_numbers_and_hashes(self):
        payload = package()
        sid = reader.STRATEGY_IDS[0]
        mutations = [
            lambda p: p.update(schema_version=True),
            lambda p: p.update(selection_basis="INDEPENDENT_HOLDOUT"),
            lambda p: p["strategies"].update(UNKNOWN=deepcopy(p["strategies"][sid])),
            lambda p: p["source_hashes"].update({"history/top40.parquet": "invalid"}),
            lambda p: p["source_refs"]["history/top40.parquet"].update(sha256="cd" * 32),
            lambda p: p["performance_period"].update(decision_clock="SAME_CLOSE"),
            lambda p: p["strategies"][sid]["daily"][0].update(date="2026-02-30"),
            lambda p: p["strategies"][sid]["daily"][0].update(nav=float("nan")),
            lambda p: p["strategies"][sid]["daily"][0].update(nav=10 ** 1000),
            lambda p: p["strategies"][sid]["daily"][0].update(cash_weight=True),
            lambda p: p["strategies"][sid]["application"].update(target_cash_weight=0.5),
            lambda p: p["strategies"][sid]["application"]["rows"][0].update(weight_before=0.1),
            lambda p: p["strategies"][sid]["application"]["rows"].append(
                deepcopy(p["strategies"][sid]["application"]["rows"][0])),
            lambda p: p["strategies"][sid]["application"]["rows"][0].update(action="SELL"),
            lambda p: p["strategies"][sid]["summary"].update(days=3),
            lambda p: p["strategies"][sid]["summary"].update(end_nav=1.2),
            lambda p: p["strategies"][sid]["application"].update(status="BLOCKED", reason="blocked"),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                candidate = deepcopy(payload)
                mutate(candidate)
                with self.assertRaises(ValueError):
                    reader.validate_package(candidate)

    def test_direct_history_uses_hgb_top20_including_members_outside_raw_top20(self):
        payload = history_package("HGB_TOP20_RISK_R1")
        self.assertIs(reader.validate_package(payload), payload)
        history = payload["strategies"][reader.STRATEGY_IDS[0]]["application_history"][0]
        self.assertEqual(history["rows"][0]["ticker"], "T40")
        history["rows"][0]["ticker"] = "T1"
        with self.assertRaisesRegex(ValueError, "application_history.score_or_weight_binding"):
            reader.validate_package(payload)

    def test_history_policy_must_match_package_in_both_directions(self):
        for package_policy, history_policy in (("HGB_TOP20_RISK_R1", None),
                ("HGB_TOP20_RISK_R1", "RAW_TOP20_FROZEN_LEGACY"),
                ("RAW_TOP20_FROZEN_LEGACY", "HGB_TOP20_RISK_R1")):
            with self.subTest(package_policy=package_policy, history_policy=history_policy):
                payload = history_package(package_policy)
                history = payload["strategies"][reader.STRATEGY_IDS[0]]["application_history"][0]
                if history_policy is None:
                    history.pop("policy_id", None)
                else:
                    history["policy_id"] = history_policy
                with self.assertRaisesRegex(ValueError, "application_history.policy_id"):
                    reader.validate_package(payload)

    def test_legacy_history_missing_policy_keeps_raw_membership_and_original_payload(self):
        payload = history_package()
        original = deepcopy(payload)
        self.assertIs(reader.validate_package(payload), payload)
        self.assertEqual(payload, original)
        for strategy in payload["strategies"].values():
            strategy["application_history"][0]["policy_id"] = "RAW_TOP20_FROZEN_LEGACY"
        self.assertIs(reader.validate_package(payload), payload)
        history = payload["strategies"][reader.STRATEGY_IDS[0]]["application_history"][0]
        history["rows"][0]["ticker"] = "T40"
        with self.assertRaisesRegex(ValueError, "application_history.score_or_weight_binding"):
            reader.validate_package(payload)

    def test_json_cache_follows_content_and_never_returns_shared_mutable_data(self):
        with tempfile.TemporaryDirectory(prefix="selected-hgb-reader-") as folder:
            target = Path(folder) / "package.json"
            target.write_text(json.dumps(package()), encoding="utf-8")
            first = reader.load_package(target)
            first["strategies"][reader.STRATEGY_IDS[0]]["label"] = "changed by caller"
            again = reader.load_package(target)
            self.assertEqual(again["strategies"][reader.STRATEGY_IDS[0]]["label"], "HGB + 对角风险")
            fresh = package()
            fresh["strategies"][reader.STRATEGY_IDS[0]]["application"]["signal_date"] = "2026-02-03"
            target.write_text(json.dumps(fresh), encoding="utf-8")
            newest = reader.load_package(target)
            self.assertEqual(newest["strategies"][reader.STRATEGY_IDS[0]]["application"]["signal_date"], "2026-02-03")
            self.assertNotEqual(newest["package_sha256"], again["package_sha256"])
            with patch.dict(os.environ, {"USTQ_SELECTED_HGB_PACKAGE": str(target)}):
                self.assertEqual(reader.load_package(), newest)

    def test_json_duplicate_keys_and_nonfinite_values_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix="selected-hgb-reader-") as folder:
            target = Path(folder) / "package.json"
            for raw in ('{"schema_version":1,"schema_version":1}', '{"value":NaN}'):
                target.write_text(raw, encoding="utf-8")
                with self.assertRaises(ValueError):
                    reader.load_package(target)

    def test_csv_keeps_strategy_signal_raw_weights_and_cash(self):
        payload = package()
        strategy_id = reader.STRATEGY_IDS[1]
        raw = page.target_csv(strategy_id, payload["strategies"][strategy_id])
        rows = list(csv.DictReader(StringIO(raw.decode("utf-8-sig"))))
        self.assertEqual([row["ticker"] for row in rows], ["MSFT", "CASH"])
        self.assertTrue(all(row["strategy_id"] == strategy_id for row in rows))
        self.assertTrue(all(row["signal_date"] == "2026-02-02" for row in rows))
        self.assertAlmostEqual(sum(float(row["target_weight"]) for row in rows), 1)


class SelectedChartTests(unittest.TestCase):
    def test_policy_caption_keeps_legacy_default_direct_and_unknown_distinct(self):
        legacy = "Frozen HGB scores are used in the original Raw A2 Top20 allocation framework. The original risk models optimize weights with existing holdings, cash and costs; held stocks follow the original optimizer's rules."
        self.assertEqual(page.policy_caption({}), legacy)
        self.assertEqual(page.policy_caption({"policy_id": "RAW_TOP20_FROZEN_LEGACY"}), legacy)
        self.assertEqual(page.policy_caption({"policy_id": "HGB_TOP20_RISK_R1"}), 'HGB signals define the Top20 candidates within Raw Top40. Each risk model controls weights and cash; holdings outside the candidates cannot increase.')
        self.assertIsNone(page.policy_caption({"policy_id": "SYNTHETIC_UNKNOWN_POLICY"}))

    def test_policy_method_is_localized_inside_existing_source_details(self):
        from contextlib import nullcontext
        from apps.demo_console.i18n import language_scope, tr

        payload = {"policy_id": "RAW_TOP20_FROZEN_LEGACY", "package_sha256": "ab" * 32,
                   "performance_period": {"price_basis": "QFQ_PRICE_COORDINATE_PROXY"}}
        before = deepcopy(payload)
        for language in ("en", "zh", "ja"):
            with language_scope(language), patch.object(page.st, "expander", return_value=nullcontext()), \
                    patch.object(page.st, "write"), patch.object(page.st, "caption") as rendered:
                page._source_details(payload, presentation=True)
                rendered.assert_any_call(tr("HGB · Diagonal") + " · " + tr(page.policy_caption(payload)))
        self.assertEqual(payload, before)

    def test_comparison_domains_cover_observed_dates_nav_and_baseline_without_empty_data_autoscaling(self):
        # Losing and winning books exercise both sides of the initial NAV;
        # the plot must not invent an earlier date or an unrelated NAV range.
        for navs in ((0.73, 0.83, 0.62, 0.92), (1.23, 2.72, 1.12, 2.12)):
            with self.subTest(navs=navs):
                payload = package()
                observations = []
                for index, strategy in enumerate(payload["strategies"].values()):
                    for offset, point in enumerate(strategy["daily"]):
                        point.update(date=("2026-03-02", "2026-09-24")[offset], nav=navs[index * 2 + offset])
                        observations.append(point)
                spec = chart_for_display(page.nav_chart(payload), presentation=True).to_dict(validate=True)
                x, y = spec["encoding"]["x"], spec["encoding"]["y"]
                self.assertEqual(x["scale"]["domain"], ["2026-03-02", "2026-09-24"])
                self.assertFalse(x["scale"]["nice"])
                observed_values = [point["nav"] for point in observations] + [1.0]
                self.assertLessEqual(y["scale"]["domain"][0], min(observed_values))
                self.assertGreaterEqual(y["scale"]["domain"][1], max(observed_values))
                self.assertLess(y["scale"]["domain"][1] - y["scale"]["domain"][0],
                                (max(observed_values) - min(observed_values)) * 1.2)
                self.assertFalse(y["scale"]["zero"])
                self.assertFalse(y["scale"]["nice"])
                self.assertEqual(len(spec["data"]["values"]), len(observations))
                self.assertEqual({(row["date"], row["nav"]) for row in spec["data"]["values"]},
                                 {(point["date"], point["nav"]) for point in observations})

    def test_single_record_retains_only_recorded_tick_and_visible_point(self):
        payload = package()
        for strategy in payload["strategies"].values():
            strategy["daily"] = strategy["daily"][:1]
        spec = page.nav_chart(payload).to_dict(validate=True)
        self.assertEqual(spec["encoding"]["x"]["axis"]["values"], ["2026-01-05"])
        domain = spec["encoding"]["x"]["scale"]["domain"]
        self.assertLess(domain[0], "2026-01-05")
        self.assertGreater(domain[1], "2026-01-05")
        self.assertEqual({row["date"] for row in spec["data"]["values"]}, {"2026-01-05"})
        self.assertGreater(spec["mark"]["point"]["size"], 0)


class SelectedPageTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        self.temp = tempfile.TemporaryDirectory(prefix="selected-hgb-page-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "package.json"
        self.write(package())
        patch.dict(os.environ, {"USTQ_SELECTED_HGB_PACKAGE": str(self.path)}).start()
        reader.clear_cache()

    def write(self, payload):
        self.path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def app(self):
        from streamlit.testing.v1 import AppTest

        def current_target():
            import streamlit as st
            from apps.demo_console.adapters import selected_strategies_reader as reader
            from apps.demo_console.i18n import language_scope
            from apps.demo_console.pages import selected_strategies as page

            with language_scope("en"):
                context = reader.workspace_view("HGB_DIAG_5", "2026-02-02")
                if context["status"] == "BLOCKED":
                    st.error(context["error"])
                    return
                page._workspace_target(context)

        return AppTest.from_function(current_target, default_timeout=20).run()

    def test_legacy_alias_preserves_workspace_context_and_redirects_without_new_selectors(self):
        # The production callable-Page route is exercised in main-workspace
        # tests; this alias only transports the existing shared context.
        target = object()
        pages = {"research": target, "strategies": object()}
        for strategy_id in page.WORKSPACE_STRATEGIES:
            with self.subTest(strategy_id=strategy_id):
                state = {"workspace_strategy": strategy_id, "decision_date": "2026-09-23",
                    "workspace_sample": "test_2026", "workspace": "Research",
                    "research_range": "Custom dates", "research_dates": ("2026-01-06", "2026-08-18"),
                    "selected_hgb_strategy": "HGB_FACTOR_5", "selected_hgb_history_date": "2026-01-02",
                    "_applied_workspace_context": {"decision_date": "stale"}}
                expected_context = {key: state[key] for key in
                                    ("workspace_strategy", "decision_date", "workspace_sample")}
                with patch.object(page.st, "session_state", state), \
                        patch.object(page.st, "switch_page") as switch, \
                        patch.object(page.st, "selectbox", side_effect=AssertionError("Alias rendered a strategy selector")), \
                        patch.object(page.st, "date_input", side_effect=AssertionError("Alias rendered a date selector")), \
                        patch.object(reader, "load_package", side_effect=AssertionError("Alias loaded a second data snapshot")):
                    page.render_selected_strategies(pages)
                switch.assert_called_once_with(target)
                self.assertEqual(state["workspace"], "Overview")
                self.assertEqual({key: state[key] for key in expected_context}, expected_context)
                self.assertEqual(state["_applied_workspace_context"], expected_context)
                self.assertNotIn("selected_hgb_strategy", state)
                self.assertNotIn("selected_hgb_history_date", state)
                self.assertEqual(state["research_range"], "Custom dates")
                self.assertEqual(state["research_dates"], ("2026-01-06", "2026-08-18"))
                state["decision_date"] = "2026-08-17"
                self.assertEqual(state["_applied_workspace_context"]["decision_date"], "2026-09-23")

    def test_registered_alias_renders_the_same_workspace_without_second_navigation(self):
        pages = {"research": object(), "strategies": object()}
        state = {"workspace_strategy": "R7_GROSS_LINEAR", "decision_date": "2026-01-07",
                 "workspace_sample": "test_2026", "workspace": "Research"}
        callback = unittest.mock.Mock()
        with patch.object(page.st, "session_state", state), patch.object(page.st, "switch_page",
                side_effect=AssertionError("Registered alias must not start another navigation")):
            page.render_selected_strategies(pages, render=callback)
        callback.assert_called_once_with(pages)
        self.assertEqual(state["workspace"], "Overview")
        self.assertEqual(state["workspace_strategy"], "R7_GROSS_LINEAR")
        self.assertEqual(state["_applied_workspace_context"]["decision_date"], "2026-01-07")

    def test_legacy_alias_restores_old_strategy_only_without_inventing_date_or_sample(self):
        for previous, expected in (("HGB_FACTOR_5", "RAW_A2"), ("HGB_DIAG_5", "HGB_DIAG_5"),
                                   ("UNKNOWN", "RAW_A2"), (None, "RAW_A2")):
            with self.subTest(previous=previous):
                state = {"workspace_strategy": "UNKNOWN", "selected_hgb_strategy": previous,
                         "selected_hgb_history_date": "2026-01-02"}
                target = object()
                with patch.object(page.st, "session_state", state), patch.object(page.st, "switch_page") as switch:
                    page.render_selected_strategies({"research": target})
                switch.assert_called_once_with(target)
                self.assertEqual(state["workspace_strategy"], expected)
                self.assertEqual(state["_applied_workspace_context"], {"workspace_strategy": expected})
                self.assertNotIn("decision_date", state)
                self.assertNotIn("workspace_sample", state)
                self.assertNotIn("selected_hgb_strategy", state)
                self.assertNotIn("selected_hgb_history_date", state)

    def test_status_changes_and_valid_recovery_leave_no_stale_errors(self):
        app = self.app()
        payload = package()
        application = payload["strategies"]["HGB_DIAG_5"]["application"]
        application.update(status="LATEST_AVAILABLE_SIGNAL", signal_date="2026-01-05", reason="较新一日输入不完整")
        self.write(payload)
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any("2026-01-05" in warning.value for warning in app.warning))
        self.assertFalse(app.error)
        self.assertEqual(len(app.get("download_button")), 1)
        application.update(status="BLOCKED", rows=[], reason="输入缺口")
        self.write(payload)
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any("输入缺口" in caption.value for caption in app.caption))
        self.assertTrue(app.warning)
        self.assertFalse(app.metric)
        self.assertFalse(app.get("download_button"))
        self.path.write_text("{}", encoding="utf-8")
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.error), 1)
        self.assertFalse(app.metric)
        self.write(package())
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertFalse(app.warning)
        self.assertEqual(len(app.metric), 3)
        self.assertTrue(any(metric.label == "Target cash allocation" and metric.value == "20.00%"
                            for metric in app.metric))
        self.assertEqual(len(app.get("download_button")), 1)


if __name__ == "__main__":
    unittest.main()


def test_raw_rule_target_csv_does_not_invent_previous_holdings_or_trade_actions():
    import csv
    from io import StringIO
    from apps.demo_console.pages.selected_strategies import target_csv
    payload={"application":{"signal_date":"2026-09-24","account_basis":"RAW_TOP20_EQUAL_WEIGHT_RULE",
        "target_cash_weight":0.,"cash_weight_before":None,
        "rows":[{"ticker":"ABC","target_weight":.05}]}}
    rows=list(csv.DictReader(StringIO(target_csv("RAW_A2",payload).decode("utf-8-sig"))))
    assert rows[0]["target_weight"] == "0.05"
    assert rows[0]["weight_before"] == rows[0]["action"] == ""
    assert rows[-1]["ticker"] == "CASH" and rows[-1]["weight_before"] == ""


def _lazy_applied_workspace():
    """Exercise the real page with every source/renderer replaced before entry."""
    from contextlib import ExitStack
    from types import SimpleNamespace
    from unittest.mock import patch
    import streamlit as st
    from apps.demo_console.adapters import applied_account_reader as accounts, workspace_reader
    from apps.demo_console.components import top20_table, stock_history_search
    from apps.demo_console.i18n import language_scope
    from apps.demo_console.pages import machine_learning as ml, research, selected_strategies as page

    st.session_state.setdefault("workspace_strategy", "R7_GROSS_LINEAR")
    st.session_state.setdefault("decision_date", "2026-01-09")
    st.session_state.setdefault("workspace_sample", "test_2026")
    st.selectbox("Synthetic workspace", ("Portfolio", "Overview", "History", "Research", "Machine learning", "Evidence"),
                 key="test_view")
    trace = {name: [] for name in ("account", "contexts", "rankings", "stock", "statistics", "performance")}
    st.session_state["lazy_trace"] = trace
    st.session_state["lazy_ml_calls"] = []
    state = {"error": None, "state": {"books": {}}, "capture": object()}
    day = st.session_state["decision_date"]
    model = SimpleNamespace(decision_date=day)
    contexts = {sid: {"status": "AVAILABLE"} for sid in page.WORKSPACE_STRATEGIES}
    def account():
        trace["account"].append(True)
        return state
    def context_loader(cutoff, **kwargs):
        assert cutoff == day and kwargs["account_state"] is state
        trace["contexts"].append(cutoff)
        return contexts
    def ranking_loader(cutoff, **kwargs):
        assert cutoff == day and kwargs["account_state"] is state
        trace["rankings"].append(cutoff)
        return {"synthetic": True}
    def stock_loader(**kwargs):
        assert kwargs["as_of"] == day and kwargs["account_state"] is state
        trace["stock"].append(day)
        return {"synthetic": True}
    def performance(*args, **kwargs):
        trace["performance"].append(day)
        st.caption("Synthetic research cutoff is independent of current targets.")
        if kwargs.get("statistics"):
            statistics(None)
        return {"synthetic": True}
    def statistics(*args, **kwargs):
        trace["statistics"].append(day)
        st.text("Synthetic statistics opened")
    def model_renderer(current, *, presentation, workspace):
        assert current is model and presentation is True
        assert workspace["strategy_id"] == st.session_state["workspace_strategy"]
        st.session_state["lazy_ml_calls"].append(workspace["strategy_id"])
        st.text("Synthetic frozen model")
    with language_scope(st.session_state.get("test_language", "en")), ExitStack() as stack:
        patches = ((accounts, "load_state", account),
            (workspace_reader, "load_active_strategies", context_loader),
            (workspace_reader, "load_active_rankings", ranking_loader),
            (workspace_reader, "load_active_stock_catalog", stock_loader),
            (workspace_reader, "applied_history_cutoff", lambda cutoff, **kwargs: cutoff),
            (page, "_verified_raw_model", lambda model, cutoff: model),
            (page, "policy_caption", lambda package: ""),
            (page, "_source_details", lambda *args, **kwargs: None),
            (ml, "render_machine_learning", model_renderer),
            (page, "render_legacy_history", lambda *args, **kwargs: None),
            (page, "_workspace_allocation_comparison", lambda *args, **kwargs: None),
            (page, "_exact_signal_contexts", lambda contexts, cutoff: contexts),
            (page, "render_comparison_statistics", statistics),
            (research, "render_applied_performance", performance),
            (top20_table, "render_applied_rankings", lambda *args, **kwargs: st.text("Synthetic rankings opened")),
            (stock_history_search, "render_applied_stock_history", lambda *args, **kwargs: st.text("Synthetic stock history opened")))
        for owner, name, replacement in patches:
            stack.enter_context(patch.object(owner, name, replacement))
        page.render_workspace(model, {}, presentation=True, view=st.session_state["test_view"])


def test_applied_workspace_routes_each_section_without_duplicate_payloads():
    from streamlit.testing.v1 import AppTest
    from apps.demo_console.tests.test_localized_tabs import _switch_tab
    app = AppTest.from_function(_lazy_applied_workspace, default_timeout=15).run()
    assert not app.exception and not app.error
    assert {name: len(events) for name, events in app.session_state["lazy_trace"].items()} == {
        "account": 1, "contexts": 1, "rankings": 1, "stock": 0, "statistics": 0, "performance": 0}
    _switch_tab(app, "Stock history across strategies")
    assert not app.exception and not app.error
    assert {name: len(events) for name, events in app.session_state["lazy_trace"].items()} == {
        "account": 1, "contexts": 1, "rankings": 0, "stock": 1, "statistics": 0, "performance": 0}
    for view, payload in (("Overview", ("performance",)), ("Research", ("performance", "statistics")),
                          ("History", ("stock",)), ("Machine learning", ("rankings",)), ("Evidence", ())):
        app.selectbox(key="test_view").select(view).run()
        assert not app.exception and not app.error
        assert not app.tabs
        trace = app.session_state["lazy_trace"]
        assert trace["account"] == [True] and len(trace["contexts"]) == (0 if view=="Machine learning" else 1)
        assert {key for key in ("rankings", "stock", "statistics", "performance") if trace[key]} == set(payload)
        assert all(len(events) <= 1 for events in trace.values())
        assert app.session_state["lazy_ml_calls"] == (["R7_GROSS_LINEAR"] if view == "Machine learning" else [])
    assert app.session_state["workspace_strategy"] == "R7_GROSS_LINEAR"

def test_lazy_applied_tabs_keep_observation_and_selected_source_across_languages():
    from streamlit.testing.v1 import AppTest
    from apps.demo_console.tests.test_localized_tabs import _switch_tab
    app = AppTest.from_function(_lazy_applied_workspace, default_timeout=15).run()
    _switch_tab(app, "Stock history across strategies")
    for language in ("zh", "ja", "en"):
        app.session_state["test_language"] = language
        app.session_state["decision_date"] = "2026-01-12"
        app.run()
        assert not app.exception and not app.error
        assert app.session_state["_localized_tabs:applied_workspace_tools"] == "Stock history across strategies"
        trace = app.session_state["lazy_trace"]
        assert trace["stock"] == ["2026-01-12"] and not trace["rankings"] and not trace["statistics"]
        assert trace["contexts"] == ["2026-01-12"] and not trace["performance"]
        assert app.session_state["workspace_strategy"] == "R7_GROSS_LINEAR"
        assert any("2026-01-12" in node.proto.body for node in app.get("html"))


def test_historical_sample_does_not_start_current_account_or_tool_reads():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(_lazy_applied_workspace, default_timeout=15)
    app.session_state["workspace_sample"] = "historical"
    app.run()
    assert not app.exception and not app.error
    assert not any(app.session_state["lazy_trace"].values())
    assert not app.tabs


def _lazy_drawdown_panel():
    from unittest.mock import patch, MagicMock
    import streamlit as st
    from apps.demo_console.pages import selected_strategies as page
    comparison = {"windows": {"Synthetic": {"rows": [{"date": "2026-01-09", "drawdown": -.01}]}},
        "strategy_ids": {"Synthetic": "R7_GROSS_LINEAR"}, "start": "2026-01-09", "end": "2026-01-09", "days": 1}
    calls = []
    st.session_state["lazy_charts"] = calls
    def chart(*args, **kwargs):
        calls.append(kwargs["title"])
        return MagicMock()
    with patch.object(page, "nav_comparison_chart", chart), patch.object(page, "render_chart", lambda *args, **kwargs: None):
        page.render_comparison_paths(comparison, key_prefix="synthetic_lazy")


def test_collapsed_applied_drawdown_has_no_hidden_chart_payload_and_opens_normally():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(_lazy_drawdown_panel, default_timeout=15).run()
    assert not app.exception and not app.error
    assert app.session_state["lazy_charts"] == ["NAV"]
    app.session_state["synthetic_lazy_risk_path"] = True
    app.run()
    assert not app.exception and not app.error
    assert app.session_state["lazy_charts"] == ["NAV", "Window drawdown"]


def test_target_security_count_preserves_unknown_and_known_zero_with_text_column():
    from unittest.mock import MagicMock
    from apps.demo_console.adapters import applied_account_reader as accounts
    from apps.demo_console.tests.test_applied_account_reader import state
    from apps.demo_console.i18n import language_scope
    payload = state()
    payload["books"]["RAW_A2"]["plan"].update(rows=[], target_cash_weight=1.)
    missing = "R10_DIRECT_MEAN4_ELASTICNET_MID"
    payload["books"].pop(missing)
    contexts = {sid: accounts.current_view(payload, sid, "2026-01-07") for sid in page.WORKSPACE_STRATEGIES}
    before = deepcopy(contexts)
    with language_scope("en"), patch.object(page.st, "dataframe") as tables, \
            patch.object(page.st, "container", return_value=MagicMock()), \
            patch.object(page.st, "markdown"), patch.object(page.st, "caption"):
        page._workspace_allocation_comparison(contexts)
    rows = {row["Strategy"]: row for row in tables.call_args_list[0].args[0]}
    assert rows["Raw A2"]["Target securities"] == "0"
    assert rows["ElasticNet MID"]["Target securities"] == "—"
    assert rows["HGB + diagonal risk"]["Target securities"] == "1"
    config = tables.call_args_list[0].kwargs["column_config"]["Target securities"]
    assert config["type_config"]["type"] == "text"
    matrix = tables.call_args_list[1].args[0]
    assert all(row["ElasticNet MID"] == "—" for row in matrix)
    assert contexts[missing]["target"]["kind"] == "UNAVAILABLE"
    assert contexts[missing]["target"]["target_cash_weight"] is None
    assert contexts == before
