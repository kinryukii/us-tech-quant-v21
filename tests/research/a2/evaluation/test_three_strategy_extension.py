import importlib.util
from pathlib import Path
import tempfile
import unittest
import pandas as pd
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location("extension", Path(__file__).parents[4] / "scripts/research/a2/evaluation/three_strategy_extension.py")
extension = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extension)


class ClockAndEvidenceTests(unittest.TestCase):
    def test_missing_signal_stops_before_gap_not_after(self):
        pairs, gap = extension.common_clock(["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"],
            ["2026-01-02", "2026-01-06"], "2026-01-07")
        self.assertEqual(pairs, [(pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-05"))])
        self.assertEqual(gap["signal_date"], "2026-01-05")

    def test_latest_close_is_not_same_day_execution(self):
        pairs, gap = extension.common_clock(["2026-01-02", "2026-01-05", "2026-01-06"],
            ["2026-01-02", "2026-01-05", "2026-01-06"], "2026-01-05")
        self.assertEqual(len(pairs), 1)
        self.assertIsNone(gap)

    def test_changed_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source"
            path.write_text("original")
            ref = extension.reference(path)
            path.write_text("revised")
            with self.assertRaisesRegex(ValueError, "SOURCE_HASH_MISMATCH"):
                extension.verify_refs([ref])

    def test_optimizer_receives_continuous_signal_close_holdings(self):
        seen = []
        def solve(group, shares, values, nav, bundle, spec, signal):
            seen.append((shares.copy(), values.copy(), nav))
            return {"AA": .1}, {"raw_targets": {"AA": .1}, "solver_failed": False}
        def replay(name, callback, prices, executions, signals):
            callback(signals[executions[0]], {}, {}, 1.)
            callback(signals[executions[1]], {"AA": 2.}, {"AA": .2}, 1.05)
            return "ledger"
        panel = pd.DataFrame({"signal_date": pd.to_datetime(["2026-01-02", "2026-01-05"]),
                              "ticker": ["AA", "AA"], "raw_rank": [1, 1]})
        pairs = [(pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-05")),
                 (pd.Timestamp("2026-01-05"), pd.Timestamp("2026-01-06"))]
        prices = pd.DataFrame({"trade_date": pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]), "ticker": ["AA"] * 3})
        result, targets = extension.replay_common(replay, "HGB", ("frozen",), panel, prices,
            {"optimizer": SimpleNamespace(solve=solve), "risk": "frozen"}, pairs)
        self.assertEqual(seen[1], ({"AA": 2.}, {"AA": .2}, 1.05))
        self.assertAlmostEqual(targets.iloc[1].signal_close_weight, .2 / 1.05)
        self.assertEqual(result, "ledger")

    def test_recorded_predictions_do_not_impute_or_refit_short_lags(self):
        frame = pd.DataFrame({"signal_date": [pd.Timestamp("2026-01-02")] * 40,
            "ticker": [f"T{i}" for i in range(40)], "raw_rank": range(1, 41),
            "raw_score": range(40), "lag": [float("nan")] * 40,
            "pred_hgb": [.1] * 40, "pred_q10": [-.1] * 40})
        selected = SimpleNamespace(FEATURES=("lag",))
        panel = extension.score_panel([frame], selected, {})
        self.assertTrue(panel.lag.isna().all())
        self.assertTrue(panel.pred_hgb.eq(.1).all())

    def test_one_reviewed_event_does_not_resolve_another(self):
        pairs = [(pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-05")),
                 (pd.Timestamp("2026-01-05"), pd.Timestamp("2026-01-06"))]
        events = pd.DataFrame({"event_date": ["2025-12-31", "2026-01-05", "2026-01-06"],
            "ticker": ["OLD", "RESOLVED", "UNKNOWN"],
            "audit_kind": ["LARGE_RAW_MOVE_NO_VENDOR_EVENT"] * 3,
            "resolution_status": ["UNREVIEWED", "RESOLVED_NON_CORPORATE_ACTION", "UNREVIEWED"]})
        kept, gap = extension.event_clock(pairs, events)
        self.assertEqual(len(kept), 1)
        self.assertEqual(gap["tickers"], ["UNKNOWN"])

    def test_unreviewed_event_blocks_only_actual_positive_holding(self):
        signal, execution = pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-05")
        panel = pd.DataFrame({"signal_date": [signal], "ticker": ["AA"], "raw_rank": [1]})
        prices = pd.DataFrame({"trade_date": [signal, execution], "ticker": ["AA", "AA"]})
        runtime = {"unresolved_events": {(execution, "AA")}}
        def held_replay(name, callback, prices, executions, signals):
            callback(signal, {"AA": 1.}, {"AA": .1}, 1.)
        with self.assertRaises(extension.HeldEventUnresolved):
            extension.replay_common(held_replay, "RAW", None, panel, prices, runtime, [(signal, execution)])
        def empty_replay(name, callback, prices, executions, signals):
            self.assertEqual(callback(signal, {}, {}, 1.), {"AA": .05})
            return "qualified"
        result, _ = extension.replay_common(empty_replay, "RAW", None, panel, prices, runtime, [(signal, execution)])
        self.assertEqual(result, "qualified")


if __name__ == "__main__":
    unittest.main()


def reused_receipts(tmp_path):
    import json
    from scripts.common.storage_paths import StoragePaths
    paths = StoragePaths(**{name: tmp_path / name for name in
        ("repo_root", "data_root", "cache_root", "daily_root", "backtest_root", "results_root", "envs_root")})
    paths.daily_root.mkdir()
    payloads = {
        "acquisition": {"status": "PARTIAL", "results": []},
        "massive": {"summary": {"status": "COMPLETE"}, "contract": {"provider": "MASSIVE_GROUPED"},
            "catalog_records": [{"ticker": "HOOD", "max_date": "2026-09-30"}]},
        "rehab": {"source": "MOOMOO_OPEND_GET_REHAB", "target_date": "2026-09-30", "results": []}}
    refs = {}
    for name, value in payloads.items():
        path = paths.daily_root / (name + ".json")
        path.write_text(json.dumps(value))
        refs[name] = extension.reference(path)
    return paths, refs


def test_saved_receipts_load_without_transport_and_preserve_binding(tmp_path, monkeypatch):
    from scripts.storage import refresh_market_data, refresh_current_massive, refresh_massive_market
    from scripts import daily_recommendation_prices
    fail = lambda *a, **k: (_ for _ in ()).throw(AssertionError("No saved-receipt transport or key read"))
    monkeypatch.setattr(refresh_market_data, "run", fail)
    monkeypatch.setattr(refresh_current_massive, "load_api_key", fail)
    monkeypatch.setattr(refresh_massive_market, "acquire", fail)
    monkeypatch.setattr(daily_recommendation_prices, "refresh_rehab", fail)
    paths, refs = reused_receipts(tmp_path)
    acquired, records, rehab, source, used = extension._load_held_reuse(paths, refs, ["HOOD"], "2026-09-30")
    assert acquired["status"] == "PARTIAL" and set(records) == {"HOOD"}
    assert source == Path(refs["rehab"]["path"]) and used == list(refs.values())
    assert rehab["target_date"] == "2026-09-30"


def test_saved_receipts_reject_changed_bytes_missing_name_and_wrong_target(tmp_path):
    import json
    import pytest
    paths, refs = reused_receipts(tmp_path)
    with pytest.raises(ValueError, match="HELD_REUSE_TICKER_UNAVAILABLE"):
        extension._load_held_reuse(paths, refs, ["TTAN"], "2026-09-30")
    with pytest.raises(ValueError, match="HELD_REUSE_SOURCE_CONTRACT_INVALID"):
        extension._load_held_reuse(paths, refs, ["HOOD"], "2026-10-01")
    path = Path(refs["rehab"]["path"])
    path.write_text(json.dumps({"changed": True}))
    with pytest.raises(ValueError, match="SOURCE_HASH_MISMATCH"):
        extension._load_held_reuse(paths, refs, ["HOOD"], "2026-09-30")
