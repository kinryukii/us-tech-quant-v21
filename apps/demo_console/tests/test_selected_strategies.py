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

    def test_legacy_alias_restores_old_strategy_only_without_inventing_date_or_sample(self):
        for previous, expected in (("HGB_FACTOR_5", "HGB_FACTOR_5"),
                                   ("UNKNOWN", "HGB_DIAG_5"), (None, "HGB_DIAG_5")):
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
