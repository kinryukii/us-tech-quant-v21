from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from moomoo_component.applied_source import (
    DailySource, DailySourceError, STRATEGY_IDS, _CanonicalSource,
    _clock_status, _reference, _state,
)


NOW = datetime(2026, 9, 28, 17, 10, tzinfo=timezone.utc)
SIGNAL = "2026-09-25"
SESSIONS = ["2026-09-24", SIGNAL, "2026-09-28", "2026-09-29", "2026-09-30"]
HOURS = {day: (day + "T13:30:00Z", day + "T20:00:00Z") for day in SESSIONS}
OPEN = datetime(2026, 9, 28, 13, 30, tzinfo=timezone.utc)


def state(weights=None, cash=1):
    return {"weights": weights or {}, "cash_weight": cash, "signal_date": SIGNAL,
            "valuation_basis": "SIGNAL_CLOSE"}


def clock(now=NOW, source=SIGNAL, ready=True):
    return _clock_status(now, SIGNAL, SESSIONS, HOURS, source, ready)


def application(ticker="T1", weight=.1):
    return {"status": "READY", "signal_date": SIGNAL, "account_basis": "CASH_START",
            "rows": [{"ticker": ticker, "target_weight": weight, "weight_before": 0}],
            "target_cash_weight": 1 - weight, "broker_action_allowed": False}


def report():
    return {"status": "READY", "data_date": SIGNAL, "generated_at": "2026-09-25T21:00:00Z",
            "coverage": {"eligible_count": 40, "excluded_count": 2},
            "universe": {"mapping_gaps": [{"cusip": "unmapped", "reason": "not_common"}]},
            "ranked_rows": [{"rank": index, "ticker": "T" + str(index), "security_id": str(index),
                              "score": index / 100, "raw_target_weight": .05 if index <= 20 else 0}
                             for index in range(1, 41)]}


def package():
    return {"generated_at": "2026-09-25T21:05:00Z", "source_root": "frozen-models",
            "strategies": {"HGB_DIAG_5": {"application": application()},
                           "HGB_FACTOR_5": {"application": application("T2", .08)}},
            "shared_scores": {"model_id": "FROZEN_HGB21", "current": {"status": "READY", "signal_date": SIGNAL,
                              "rows": [{"ticker": "T1", "pred_hgb": .3}]}, "historical": [{"ticker": "OLD"}]},
            "source_hashes": {"model": "a" * 64}}


@contextmanager
def modules(mapping):
    """Stub canonical boundaries, never load a model, SDK, or provider."""
    values = {}
    for name, fields in mapping.items():
        parts = name.split(".")
        for length in range(1, len(parts) + 1):
            key = ".".join(parts[:length])
            values.setdefault(key, ModuleType(key))
        for key, value in fields.items():
            setattr(values[name], key, value)
    for name, module in values.items():
        if "." in name:
            parent, leaf = name.rsplit(".", 1)
            setattr(values[parent], leaf, module)
    with patch.dict(sys.modules, values):
        yield values


class NoNetworkTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(socket, "create_connection", side_effect=AssertionError("network forbidden"))
        guard.start()
        self.addCleanup(guard.stop)


class ClockTests(NoNetworkTests):
    def test_future_open_ready_but_not_executing(self):
        result = clock(OPEN - timedelta(seconds=1))
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["window_status"], "WAITING_OPEN")
        self.assertTrue(result["ready"])
        self.assertFalse(result["execute_now"])

    def test_exact_open_and_59_seconds_are_execution_window(self):
        for seconds in (0, 30, 59.999):
            with self.subTest(seconds=seconds):
                result = clock(OPEN + timedelta(seconds=seconds))
                self.assertEqual(result["status"], "OPEN_WINDOW")
                self.assertTrue(result["execute_now"])

    def test_60_seconds_and_midday_are_missed_without_signal_roll(self):
        for now in (OPEN + timedelta(seconds=60), NOW):
            result = clock(now)
            self.assertEqual(result["status"], "MISSED_OPEN")
            self.assertFalse(result["ready"])
            self.assertFalse(result["execute_now"])
            self.assertEqual(result["signal_date"], SIGNAL)
            self.assertEqual(result["execution_date"], "2026-09-28")
            self.assertEqual(result["next_open_utc"], "2026-09-28T13:30:00Z")
            self.assertEqual(result["next_expected_open_utc"], "2026-09-29T13:30:00Z")

    def test_missing_or_stale_source_keeps_desired_complete_date(self):
        for source in (None, "2026-09-24"):
            result = clock(OPEN - timedelta(seconds=30), source=source, ready=False)
            self.assertEqual(result["status"], "WAITING_SOURCE")
            self.assertEqual(result["signal_date"], SIGNAL)
            self.assertEqual(result["source_date"], source)
            self.assertTrue(result["refresh_required"])

    def test_weekend_and_frozen_holiday_never_create_sessions(self):
        self.assertEqual(clock()["execution_date"], "2026-09-28")
        sessions = ["2026-11-25", "2026-11-27", "2026-11-30"]
        hours = {day: (day + "T14:30:00Z", day + "T21:00:00Z") for day in sessions}
        hours["2026-11-27"] = ("2026-11-27T14:30:00Z", "2026-11-27T18:00:00Z")
        result = _clock_status(datetime(2026, 11, 26, 17, tzinfo=timezone.utc), sessions[0], sessions, hours,
                               sessions[0], True)
        self.assertEqual(result["execution_date"], "2026-11-27")
        self.assertEqual(result["next_close_utc"], "2026-11-27T18:00:00Z")
        self.assertEqual(result["signal_close_utc"], "2026-11-25T21:00:00Z")

    def test_naive_clock_incomplete_signal_and_bound_horizon_reject(self):
        for now, signal in ((NOW.replace(tzinfo=None), SIGNAL),
                            (datetime(2026, 9, 25, 19, tzinfo=timezone.utc), SIGNAL),
                            (NOW, SESSIONS[-1])):
            with self.subTest(now=now, signal=signal), self.assertRaises(DailySourceError):
                _clock_status(now, signal, SESSIONS, HOURS, signal, True)


class StateAndMarkTests(NoNetworkTests):
    def backend(self):
        source = _CanonicalSource.__new__(_CanonicalSource)
        source.refs, source.paths = {}, SimpleNamespace()
        source.close_hours = HOURS
        source._calendar = Mock(return_value=(SIGNAL, SESSIONS, HOURS))
        source._bundle = Mock(return_value=(report(), package(), object()))
        source._identities = Mock(return_value={"T1": "1", "T2": "2"})
        return source

    def test_state_requires_exact_close_date_and_normalised_finite_weights(self):
        for change in ({"signal_date": "2026-09-24"}, {"valuation_basis": "INTRADAY"},
                       {"weights": {"T1": float("nan")}}, {"cash_weight": .5},
                       {"open_prices": {}}, {"weights": {"US.T1": 1}}):
            with self.subTest(change=change), self.assertRaises(DailySourceError):
                _state({**state(), **change}, SIGNAL)

    def test_halfday_close_does_not_advance_frozen_completion_early(self):
        sessions = ["2026-11-25", "2026-11-27", "2026-11-30"]
        hours = {day: (day + "T14:30:00Z", day + "T21:00:00Z") for day in sessions}
        hours["2026-11-27"] = ("2026-11-27T14:30:00Z", "2026-11-27T18:00:00Z")
        with self.assertRaisesRegex(DailySourceError, "SIGNAL_NOT_COMPLETED"):
            _clock_status(datetime(2026, 11, 27, 18, 1, tzinfo=timezone.utc), "2026-11-27", sessions, hours,
                           "2026-11-27", True)

    def test_three_cash_books_do_not_require_report_or_prices(self):
        source = self.backend()
        source._closes = Mock(side_effect=AssertionError("cash must not read prices"))
        result = source.close_states({sid: {"cash": 10000, "positions": {}} for sid in STRATEGY_IDS}, SIGNAL)
        self.assertEqual(set(result), set(STRATEGY_IDS))
        for value in result.values():
            self.assertEqual(value["equity"], 10000)
            self.assertEqual(value["cash_weight"], 1)
            self.assertEqual(value["weights"], {})
            self.assertEqual(value["prices"], {})
        source._bundle.assert_not_called()

    def test_independent_books_use_exact_close_marks_and_preserve_equity(self):
        source = self.backend()
        source._closes = Mock(return_value={"US.T1": 20, "US.T2": 50})
        books = {"HGB_DIAG_5": {"cash": 1000, "positions": {"US.T1": 50}},
                 "HGB_FACTOR_5": {"cash": 500, "positions": {"US.T2": 30}}}
        original = deepcopy(books)
        result = source.close_states(books, SIGNAL)
        self.assertEqual(books, original)
        self.assertEqual(result["HGB_DIAG_5"]["weights"], {"T1": .5})
        self.assertEqual(result["HGB_FACTOR_5"]["weights"], {"T2": .75})
        self.assertEqual(result["HGB_FACTOR_5"]["equity"], 2000)
        self.assertEqual(result["HGB_DIAG_5"]["prices"], {"US.T1": 20})
        self.assertEqual(result["HGB_FACTOR_5"]["security_ids"], {"T2": "2"})
        source._closes.assert_called_once_with({"T1", "T2"}, SIGNAL, {"T1": "1", "T2": "2"})

    def test_invalid_book_unknown_strategy_and_future_session_block(self):
        source = self.backend()
        for books, day in (({"OTHER": {"cash": 10000, "positions": {}}}, SIGNAL),
                           ({"RAW_A2": {"cash": 10, "positions": {"T1": 2}}}, SIGNAL),
                           ({"RAW_A2": {"cash": 10, "positions": {"US.T1": -1}}}, SIGNAL),
                           ({"RAW_A2": {"cash": 0, "positions": {}}}, SIGNAL),
                           ({"RAW_A2": {"cash": 10, "positions": {}}}, "2026-09-29")):
            with self.subTest(books=books, day=day), self.assertRaises(DailySourceError):
                source.close_states(books, day)

    def raw_store(self, folder, row):
        normalized, leaf = folder / "prices.parquet", folder / "raw.csv"
        normalized.write_bytes(b"normalised fixture")
        leaf.write_bytes(b"raw fixture")
        digest = hashlib.sha256(leaf.read_bytes()).hexdigest()
        row = {"ticker": "T1", "date": SIGNAL, "adjustment": "raw", "source": "MOOMOO_OPEND",
               "provider_code": "US.T1", "source_id": digest, "close": 20,
               "observed_at": "2026-09-25T21:00:00Z", **row}
        frame = SimpleNamespace(iloc=[SimpleNamespace(to_dict=lambda: row)])
        class Frame:
            iloc = frame.iloc
            def __len__(self):
                return 1
        store = Mock()
        store.metadata.return_value = {"path": str(normalized), "source_sha256": _reference(normalized)["sha256"],
                                       "adjustment": "raw", "source": "MOOMOO_OPEND"}
        store.resolve_price_inputs.return_value = [{"path": str(leaf), "sha256": digest}]
        store.daily.return_value = Frame()
        return store

    def test_raw_close_hash_identity_and_explicit_us_currency_proof(self):
        with TemporaryDirectory() as tmp:
            source = self.backend()
            store = self.raw_store(Path(tmp), {})
            with modules({"scripts.storage.storage_r2a": {"DataStore": Mock(return_value=store)}}):
                self.assertEqual(source._closes({"T1"}, SIGNAL, {"T1": "1"}), {"US.T1": 20})
            store.daily.assert_called_once_with("T1", "raw", SIGNAL, SIGNAL, provider="moomoo")
            store.resolve_price_inputs.assert_called_once_with(store.metadata.return_value, verify_raw=True)
            proof = source.refs["close/T1"]
            self.assertEqual(proof["currency"], "USD")
            self.assertEqual(proof["price_basis"], "RAW")
            self.assertEqual(proof["security_id"], "1")

    def test_qfq_intraday_wrong_day_alias_nonfinite_or_unlinked_raw_mark_reject(self):
        changes = ({"adjustment": "qfq"}, {"source": "LIVE_QUOTE"}, {"date": "2026-09-24"},
                   {"provider_code": "US.UNRELATED"}, {"ticker": "T2"},
                   {"source_id": "0" * 64}, {"close": float("nan")}, {"close": 0}, {"currency": "HKD"},
                   {"observed_at": "2026-09-25T19:00:00Z"}, {"observed_at": "2099-09-25T21:00:00Z"})
        with TemporaryDirectory() as tmp:
            for change in changes:
                source, store = self.backend(), self.raw_store(Path(tmp), change)
                with self.subTest(change=change), modules({"scripts.storage.storage_r2a": {"DataStore": Mock(return_value=store)}}), \
                     self.assertRaises(DailySourceError):
                    source._closes({"T1"}, SIGNAL, {"T1": "1"})

    def test_unknown_identity_missing_or_tampered_close_stops(self):
        with TemporaryDirectory() as tmp:
            source, store = self.backend(), self.raw_store(Path(tmp), {})
            with modules({"scripts.storage.storage_r2a": {"DataStore": Mock(return_value=store)}}):
                with self.assertRaisesRegex(DailySourceError, "IDENTITY_UNKNOWN"):
                    source._closes({"T1"}, SIGNAL, {})
                store.metadata.return_value["source_sha256"] = "0" * 64
                with self.assertRaisesRegex(DailySourceError, "SOURCE_HASH_MISMATCH"):
                    source._closes({"T1"}, SIGNAL, {"T1": "1"})
                store.metadata.side_effect = KeyError("missing")
                with self.assertRaisesRegex(DailySourceError, "HELD_RAW_CLOSE_UNAVAILABLE"):
                    source._closes({"T1"}, SIGNAL, {"T1": "1"})


    def qualified_massive_close(self, folder, row_changes=None):
        source, store = self.backend(), self.raw_store(folder, {})
        native = dict(store.metadata.return_value)
        massive_path = folder / "massive_raw.parquet"
        massive_path.write_bytes(b"native raw USD fixture, never a PIT price index")
        massive = {**_reference(massive_path), "source_sha256": _reference(massive_path)["sha256"]}
        lineage = [{"ticker": "T1", "code": "US.T1", "source": "MOOMOO_RAW_PLUS_QUALIFIED_MASSIVE_TAIL_PLUS_MOOMOO_REHAB",
            "adapter_sha256": "a" * 64, "unused_model_index_close": 1000,
            "raw_sources": [{**_reference(native["path"]), "role": "CURRENT_CATALOG_RAW"}],
            "alternate_bridge": {"provider": "MASSIVE_GROUPED", "provider_symbol": "T1",
                "qualification": "UNADJUSTED_RAW_WITH_FIVE_SESSION_MOOMOO_OVERLAP", "tail_end": SIGNAL, "overlap_sessions": 5,
                "normalized_path": massive["path"], "normalized_sha256": massive["source_sha256"]}}]
        lineage_path = folder / "input_lineage.json"
        def bind():
            lineage_path.write_text(json.dumps(lineage), encoding="utf-8")
            current = {**report(), "report_path": str(folder / "report.json"),
                "input_manifest_sha256": hashlib.sha256(json.dumps(lineage, sort_keys=True).encode()).hexdigest()}
            source._bundle.return_value = (current, {}, None)
        bind()
        class Empty:
            def __len__(self):
                return 0
        store.daily.return_value = Empty()
        store.metadata.side_effect = lambda dataset, *_: dict(native) if dataset == "prices_daily" else dict(massive)
        row = {"ticker": "T1", "date": SIGNAL, "source": "MASSIVE_GROUPED", "adjustment": "raw",
            "currency": "USD", "provider_code": "T1", "source_id": "b" * 64,
            "observed_at": "2026-09-25T21:00:00Z", "close": 25, **(row_changes or {})}
        class Raw:
            iloc = [SimpleNamespace(to_dict=lambda: row)]
            def __len__(self):
                return 1
        reader = Mock(return_value=(Raw(), {"raw_inputs": [{"sha256": "b" * 64}]}))
        boundaries = {"scripts.storage.storage_r2a": {"DataStore": Mock(return_value=store)},
            "scripts.daily_recommendation_prices": {"ADAPTER_SHA": "a" * 64, "_massive_raw_window": reader}}
        return source, store, native, massive, lineage, bind, reader, boundaries

    def test_qualified_massive_zero_native_gap_uses_raw_usd_and_explicit_source(self):
        for role in ("CURRENT_CATALOG_RAW", "NATIVE_MOOMOO_ANCHOR"):
            with self.subTest(role=role), TemporaryDirectory() as tmp:
                source, store, _, _, lineage, bind, reader, boundaries = self.qualified_massive_close(Path(tmp))
                lineage[0]["raw_sources"][0]["role"] = role
                bind()
                with modules(boundaries):
                    self.assertEqual(source._closes({"T1"}, SIGNAL, {"T1": "1"}), {"US.T1": 25})
                reader.assert_called_once()
                self.assertEqual(reader.call_args.args[1:4], ("T1", SIGNAL, SIGNAL))
                self.assertIs(reader.call_args.args[4], store)
                proof = source.refs["close/T1"]
                self.assertEqual((proof["source"], proof["price_basis"], proof["currency"]), ("MASSIVE_GROUPED", "RAW", "USD"))
                self.assertEqual(proof["currency_basis"], "MASSIVE_US_GROUPED_MARKET_RAW_USD")
                self.assertEqual(proof["qualification"], "UNADJUSTED_RAW_WITH_FIVE_SESSION_MOOMOO_OVERLAP")
                self.assertIn("qualification_lineage", proof)
                self.assertEqual(proof["native_anchor"]["source"], "MOOMOO_OPEND")
                self.assertEqual(proof["native_anchor"]["qualification_role"], role)

    def test_qualified_massive_lineage_hash_or_record_change_rejects(self):
        for change in ("lineage_hash", "record_hash", "code", "provider", "qualification", "adapter", "missing_entry",
                       "overlap", "anchor_hash", "anchor_path", "anchor_role", "duplicate_anchor"):
            with self.subTest(change=change), TemporaryDirectory() as tmp:
                source, _, _, massive, lineage, bind, reader, boundaries = self.qualified_massive_close(Path(tmp))
                if change == "record_hash":
                    massive["source_sha256"] = "0" * 64
                elif change == "code": lineage[0]["code"] = "US.OTHER"
                elif change == "provider": lineage[0]["alternate_bridge"]["provider"] = "PIT_INDEX"
                elif change == "qualification": lineage[0]["alternate_bridge"]["qualification"] = "RELAXED"
                elif change == "adapter": lineage[0]["adapter_sha256"] = "0" * 64
                elif change == "missing_entry": lineage.clear()
                elif change == "overlap": lineage[0]["alternate_bridge"]["overlap_sessions"] = 4
                elif change == "anchor_hash": lineage[0]["raw_sources"][0]["sha256"] = "0" * 64
                elif change == "anchor_path": lineage[0]["raw_sources"][0]["path"] = str(Path(tmp) / "other")
                elif change == "anchor_role": lineage[0]["raw_sources"][0]["role"] = "PIT_INDEX"
                elif change == "duplicate_anchor": lineage[0]["raw_sources"].append(dict(lineage[0]["raw_sources"][0]))
                bind()
                if change == "lineage_hash": source._bundle.return_value[0]["input_manifest_sha256"] = "0" * 64
                with modules(boundaries), self.assertRaises(DailySourceError):
                    source._closes({"T1"}, SIGNAL, {"T1": "1"})
                reader.assert_not_called()

    def test_qualified_massive_raw_identity_clock_or_invalid_close_rejects(self):
        for change in ({"currency": "HKD"}, {"adjustment": "qfq"}, {"source": "PIT_INDEX"},
                       {"provider_code": "OTHER"}, {"ticker": "OTHER"}, {"date": "2026-09-24"},
                       {"observed_at": "2026-09-25T19:00:00Z"}, {"observed_at": "2099-09-25T21:00:00Z"},
                       {"close": float("nan")}, {"close": 0}):
            with self.subTest(change=change), TemporaryDirectory() as tmp:
                source, _, _, _, _, _, _, boundaries = self.qualified_massive_close(Path(tmp), change)
                with modules(boundaries), self.assertRaises(DailySourceError):
                    source._closes({"T1"}, SIGNAL, {"T1": "1"})

    def test_qualified_massive_source_gate_or_midread_lineage_tamper_rejects(self):
        for change in ("source_gate", "midread_lineage", "midread_native_bytes", "midread_native_pointer", "midread_native_path", "midread_massive_bytes"):
            with self.subTest(change=change), TemporaryDirectory() as tmp:
                source, _, native, massive, _, _, reader, boundaries = self.qualified_massive_close(Path(tmp))
                if change == "source_gate": reader.side_effect = ValueError("MASSIVE_DAY_CHECKPOINT_IDENTITY_MISMATCH")
                else:
                    original = reader.return_value
                    def mutate(*args):
                        if change == "midread_lineage": (Path(tmp) / "input_lineage.json").write_text("[]", encoding="utf-8")
                        elif change == "midread_native_bytes": Path(native["path"]).write_bytes(b"tampered")
                        elif change == "midread_native_pointer": native["source_sha256"] = "0" * 64
                        elif change == "midread_native_path":
                            other = Path(tmp) / "another_native.parquet"
                            other.write_bytes(Path(native["path"]).read_bytes())
                            native["path"] = str(other)
                        elif change == "midread_massive_bytes": Path(massive["path"]).write_bytes(b"tampered")
                        return original
                    reader.side_effect = mutate
                with modules(boundaries), self.assertRaises(DailySourceError):
                    source._closes({"T1"}, SIGNAL, {"T1": "1"})

    def test_native_integrity_identity_clock_or_duplicate_never_uses_massive(self):
        for change in ("hash", "identity", "clock", "duplicate", "valid"):
            with self.subTest(change=change), TemporaryDirectory() as tmp:
                source, store, native, _, _, _, reader, boundaries = self.qualified_massive_close(Path(tmp))
                row_change = {"provider_code": "US.OTHER"} if change == "identity" else (
                    {"observed_at": "2099-09-25T21:00:00Z"} if change == "clock" else {})
                real = self.raw_store(Path(tmp), row_change)
                store.daily.return_value = real.daily.return_value
                if change == "hash": native["source_sha256"] = "0" * 64
                if change == "duplicate":
                    class Duplicate:
                        def __len__(self): return 2
                    store.daily.return_value = Duplicate()
                with modules(boundaries):
                    if change == "valid":
                        self.assertEqual(source._closes({"T1"}, SIGNAL, {"T1": "1"}), {"US.T1": 20})
                    else:
                        with self.assertRaises(DailySourceError): source._closes({"T1"}, SIGNAL, {"T1": "1"})
                reader.assert_not_called()
                source._bundle.assert_not_called()


class PlanTests(NoNetworkTests):
    def backend(self, now=NOW):
        source = _CanonicalSource.__new__(_CanonicalSource)
        source.refs = {"report": {"path": "immutable/report.json", "sha256": "a" * 64}}
        source.status = Mock(return_value=clock(now))
        source._bundle = Mock(return_value=(report(), package(), object()))
        source._identities = Mock(return_value={"T" + str(i): str(i) for i in range(1, 41)})
        source._closes = Mock(return_value={"US.T1": 20, "US.T2": 50})
        return source

    def test_missed_cash_plans_show_three_rules_without_replay_holdings_or_inference(self):
        source, infer = self.backend(), Mock(side_effect=AssertionError("cash package must not infer"))
        states = {sid: state() for sid in STRATEGY_IDS}
        original = deepcopy(states)
        with modules({"scripts.research.a2.portfolio.selected_hgb": {"infer_targets": infer}}):
            result = source.load(states, NOW)
        self.assertEqual(states, original)
        self.assertEqual(result["status"], "MISSED_OPEN")
        self.assertFalse(result["ready"])
        self.assertEqual(set(result["plans"]), set(STRATEGY_IDS))
        raw = result["plans"]["RAW_A2"]
        self.assertEqual(len(raw["rows"]), 20)
        self.assertTrue(all(row["target_weight"] == .05 for row in raw["rows"]))
        self.assertEqual(raw["target_cash_weight"], 0)
        self.assertEqual(result["plans"]["HGB_DIAG_5"]["target_cash_weight"], .9)
        self.assertNotIn("historical", result["scores"])
        self.assertEqual(result["coverage_gaps"]["coverage"]["excluded_count"], 2)
        self.assertFalse(raw["broker_action_allowed"])
        self.assertEqual(raw["model_fit_calls"], 0)
        source._closes.assert_not_called()
        infer.assert_not_called()

    def test_open_window_load_keeps_execution_permission(self):
        source = self.backend(OPEN + timedelta(seconds=30))
        with modules({"scripts.research.a2.portfolio.selected_hgb": {}}):
            result = source.load({"HGB_DIAG_5": state()}, OPEN + timedelta(seconds=30))
        self.assertEqual(result["status"], "OPEN_WINDOW")
        self.assertTrue(result["execute_now"])
        self.assertEqual(set(result["plans"]), {"HGB_DIAG_5"})

    def test_supplied_held_identity_change_blocks_even_with_valid_close_prices(self):
        source = self.backend()
        value = {**state({"T1": .2}, .8), "security_ids": {"T1": "OLD_CUSIP"}}
        result = source.load({"HGB_DIAG_5": value}, NOW)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("IDENTITY_CHANGED", result["reason"])
        self.assertEqual(result["plans"], {})

    def test_held_hgb_each_uses_own_close_state_and_never_crosses_accounts(self):
        source = self.backend()
        infer = Mock(side_effect=lambda frame, state, source_root: {
            "HGB_DIAG_5": {**application("T1", .15), "account_basis": "USER_SUPPLIED_SIGNAL_CLOSE_STATE"},
            "HGB_FACTOR_5": {**application("T2", .25), "account_basis": "USER_SUPPLIED_SIGNAL_CLOSE_STATE"}})
        states = {"HGB_DIAG_5": state({"T1": .3}, .7), "HGB_FACTOR_5": state({"T2": .6}, .4)}
        with modules({"scripts.research.a2.portfolio.selected_hgb": {"infer_targets": infer}}):
            result = source.load(states, NOW)
        self.assertEqual(infer.call_count, 2)
        self.assertEqual(infer.call_args_list[0].kwargs["state"], states["HGB_DIAG_5"])
        self.assertEqual(infer.call_args_list[1].kwargs["state"], states["HGB_FACTOR_5"])
        self.assertEqual(result["plans"]["HGB_DIAG_5"]["rows"][0]["weight_before"], .3)
        self.assertEqual(result["plans"]["HGB_FACTOR_5"]["rows"][0]["weight_before"], .6)
        source._closes.assert_called_once()

    def test_feature_gap_account_clock_or_held_close_failure_leaves_no_partial_plans(self):
        for kind in ("features", "held_close", "state"):
            source = self.backend()
            states = {sid: state() for sid in STRATEGY_IDS}
            if kind == "features":
                source._bundle.side_effect = DailySourceError("FEATURES_MISSING")
            elif kind == "held_close":
                states["HGB_FACTOR_5"] = state({"T2": .5}, .5)
                source._closes.side_effect = DailySourceError("HELD_RAW_CLOSE_MISSING")
            else:
                states["HGB_FACTOR_5"]["signal_date"] = "2026-09-24"
            with self.subTest(kind=kind):
                result = source.load(states, NOW)
                self.assertEqual(result["status"], "BLOCKED")
                self.assertFalse(result["ready"])
                self.assertEqual(result["plans"], {})
                self.assertTrue(result["data_gaps"])

    def test_unknown_target_bad_raw_rule_or_solver_failure_never_falls_back(self):
        for kind in ("identity", "raw_rule", "solver"):
            source = self.backend()
            states = {sid: state() for sid in STRATEGY_IDS}
            if kind == "identity":
                source._identities.return_value.pop("T1")
            elif kind == "raw_rule":
                source._bundle.return_value[0]["ranked_rows"][0]["raw_target_weight"] = .04
            else:
                states["HGB_DIAG_5"] = state({"T1": .5}, .5)
            infer = Mock(side_effect=ValueError("SOLVER_FAILED"))
            with self.subTest(kind=kind), modules({"scripts.research.a2.portfolio.selected_hgb": {"infer_targets": infer}}):
                result = source.load(states, NOW)
                self.assertEqual(result["status"], "BLOCKED")
                self.assertEqual(result["plans"], {})

    def test_stale_missing_current_source_does_not_infer(self):
        source = self.backend()
        source.status.return_value.update(status="WAITING_SOURCE", data_gaps=[{"reason": "STALE"}])
        result = source.load({"RAW_A2": state()}, NOW)
        self.assertEqual(result["plans"], {})
        source._bundle.assert_not_called()


class FacadeTests(NoNetworkTests):
    def facade(self, folder):
        config = folder / "repo/config"
        config.mkdir(parents=True, exist_ok=True)
        roots = {key + "_root": str(folder / key) for key in ("data", "cache", "daily", "backtest", "results", "envs")}
        (config / "storage_paths.json").write_text(json.dumps(roots), encoding="utf-8")
        return DailySource(folder / "repo", runtime_root=folder / "daily/paper", python_exe=sys.executable)

    def test_archive_is_immutable_idempotent_and_excludes_volatile_clock(self):
        with TemporaryDirectory() as tmp:
            source = self.facade(Path(tmp))
            result = {**clock(), "plans": {"RAW_A2": application()}, "scores": {"current": {"rows": []}},
                      "source_refs": {"report": {"path": "frozen.json", "sha256": "a" * 64}}}
            source._archive(result, {"RAW_A2": state()})
            archive = Path(result["archive"]["path"])
            before = archive.read_bytes()
            result.update(now_utc="2026-09-28T17:11:00Z", status="MISSED_OPEN")
            source._archive(result, {"RAW_A2": state()})
            self.assertEqual(archive.read_bytes(), before)
            result["plans"]["RAW_A2"]["target_cash_weight"] = .99
            with self.assertRaisesRegex(DailySourceError, "IMMUTABLE_PAPER_PLAN_CONFLICT"):
                source._archive(result, {"RAW_A2": state()})
            self.assertEqual(archive.read_bytes(), before)
            self.assertEqual(list(archive.parent.glob("*.tmp")), [])

    def test_archive_state_or_source_changes_conflict_and_canonical_repo_is_not_writable(self):
        with TemporaryDirectory() as tmp:
            source = self.facade(Path(tmp))
            result = {**clock(), "plans": {"RAW_A2": application()}, "source_refs": {}}
            source._archive(result, {"RAW_A2": state()})
            with self.assertRaisesRegex(DailySourceError, "CONFLICT"):
                source._archive(result, {"RAW_A2": state({"T1": .2}, .8)})
            result["source_refs"] = {"new": "source"}
            with self.assertRaisesRegex(DailySourceError, "CONFLICT"):
                source._archive(result, {"RAW_A2": state()})
            source.runtime_root = source.repo_root / "paper"
            with self.assertRaisesRegex(DailySourceError, "OUTSIDE_CANONICAL"):
                source._archive(result, {"RAW_A2": state()})

    def test_archive_refuses_canonical_data_root(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = self.facade(folder)
            source.runtime_root = folder / "data/paper"
            with self.assertRaisesRegex(DailySourceError, "OUTSIDE_CANONICAL"):
                source._archive(clock(), {"RAW_A2": state()})
            self.assertFalse((folder / "data").exists())

    def test_archive_refuses_wrong_purpose_roots_and_path_escape(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = self.facade(folder)
            for invalid in (folder / "cache/paper", source.daily_root, source.daily_root / "../outside"):
                source.runtime_root = invalid
                with self.subTest(path=invalid), self.assertRaisesRegex(DailySourceError, "REQUIRES_DAILY_ROOT"):
                    source._archive(clock(), {"RAW_A2": state()})
            self.assertFalse((folder / "cache").exists())
            self.assertFalse((folder / "outside").exists())

    def test_frontend_uses_fixed_worker_args_without_automatic_refresh(self):
        with TemporaryDirectory() as tmp:
            source = self.facade(Path(tmp))
            fake = SimpleNamespace(returncode=0, stdout=json.dumps({"ok": True, "result": clock()}))
            with patch("moomoo_component.applied_source.subprocess.run", return_value=fake) as run:
                source.status(NOW)
                args, kwargs = run.call_args
                self.assertIn("-B", args[0])
                self.assertEqual(args[0][-1], "--worker")
                self.assertEqual(json.loads(kwargs["input"])["action"], "status")
                self.assertNotIn("shell", kwargs)
                self.assertEqual(run.call_count, 1)

    def test_worker_errors_keep_gaps_and_never_echo_stderr(self):
        with TemporaryDirectory() as tmp:
            source = self.facade(Path(tmp))
            fake = SimpleNamespace(returncode=0, stderr="secret provider output", stdout=json.dumps(
                {"ok": False, "reason": "EXACT_CLOSE_REQUIRED", "data_gaps": [{"ticker": "T1"}], "source_refs": {"proof": {}}}))
            with patch("moomoo_component.applied_source.subprocess.run", return_value=fake):
                with self.assertRaises(DailySourceError) as caught:
                    source.close_states({"RAW_A2": {"cash": 1, "positions": {}}}, SIGNAL)
            self.assertEqual(caught.exception.data_gaps, [{"ticker": "T1"}])
            self.assertEqual(caught.exception.source_refs, {"proof": {}})
            self.assertNotIn("secret", str(caught.exception))

    def test_real_fixed_worker_bad_action_returns_json_only_without_canonical_reads(self):
        with TemporaryDirectory() as tmp:
            source = self.facade(Path(tmp))
            with self.assertRaisesRegex(DailySourceError, "UNKNOWN_CANONICAL_SOURCE_ACTION"):
                source._call("not-an-action")

    def test_refresh_calls_existing_execute_entry_once_only_when_explicit(self):
        source = _CanonicalSource.__new__(_CanonicalSource)
        source.paths = object()
        update = Mock(return_value={"status": "READY", "data_date": SIGNAL, "broker_action_allowed": False})
        with modules({"scripts.daily_recommendation": {"run_update": update}}):
            result = source.refresh()
        update.assert_called_once()
        self.assertIs(update.call_args.args[0], source.paths)
        self.assertIs(update.call_args.kwargs["execute"], True)
        self.assertFalse(result["broker_action_allowed"])


class BundleTests(NoNetworkTests):
    @contextmanager
    def fixture(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            run = folder / "A2_today_recommendation/runs/run1"
            run.mkdir(parents=True)
            features = folder / "features.parquet"
            features.write_bytes(b"pinned 40 x 21 snapshot")
            current = report()
            current.update(report_path=str(run / "report.json"), model_id="A2_HGB", model_sha256="a" * 64)
            current["selected_hgb_features"] = {**_reference(features), "signal_date": SIGNAL}
            selected_report = folder / "selected_report.json"
            p = package()
            p["shared_scores"]["model_sha256"] = "b" * 64
            p["shared_scores"]["current"]["rows"] = [
                {"ticker": row["ticker"], "security_id": row["security_id"], "raw_rank": row["rank"],
                 "raw_score": row["score"], "pred_hgb": row["score"], "hgb_rank": row["rank"]}
                for row in current["ranked_rows"]]
            selected = folder / "A2_selected_hgb/latest.json"
            selected.parent.mkdir()
            def persist():
                text = json.dumps(current)
                (run / "report.json").write_text(text, encoding="utf-8")
                (folder / "A2_today_recommendation/latest.json").write_text(text, encoding="utf-8")
                selected_report.write_text(text, encoding="utf-8")
                p["source_refs"] = {"current/report.json": _reference(selected_report),
                                    "current/selected_hgb_features.parquet": _reference(features)}
                selected.write_text(json.dumps(p), encoding="utf-8")
            persist()
            def read_package(path):
                value = json.loads(Path(path).read_text(encoding="utf-8"))
                value["package_sha256"] = _reference(path)["sha256"]
                return value
            class Frame:
                def itertuples(self):
                    return iter(SimpleNamespace(ticker=row["ticker"], raw_rank=row["rank"],
                                                security_id=row["security_id"], raw_score=row["score"])
                                for row in current["ranked_rows"])
            frame = Frame()
            fake_hgb = {"A2_MODEL_SHA256": "a" * 64, "FROZEN_HASHES": {"models/hgb_2026092501.joblib": "b" * 64},
                        "verify_frozen": Mock(), "_current_day": Mock(return_value=(frame, SIGNAL, "")),
                        "_normalise_day": Mock(return_value=(frame, SIGNAL))}
            source = _CanonicalSource.__new__(_CanonicalSource)
            source.paths = SimpleNamespace(daily_root=folder)
            source.refs = {}
            source._calendar = Mock(return_value=(SIGNAL, SESSIONS, HOURS))
            source.hours_metadata = {"sessions_equal_frozen": True}
            with modules({"apps.demo_console.adapters.selected_strategies_reader": {"load_package": read_package},
                          "scripts.research.a2.portfolio.selected_hgb": fake_hgb,
                          "pandas": {}, "numpy": {}}):
                yield source, current, p, persist, folder, fake_hgb

    def test_exact_source_bytes_features_scores_and_frozen_runtime_are_pinned(self):
        with self.fixture() as (source, current, p, persist, folder, hgb):
            result = source.status(OPEN - timedelta(seconds=1))
            self.assertEqual(result["status"], "READY", result)
            report_value, package_value, frame = source._bundle(full=True)
            hgb["verify_frozen"].assert_called_once_with("frozen-models")
            hgb["_normalise_day"].assert_called_once()
            self.assertEqual(report_value["data_date"], SIGNAL)
            self.assertEqual(len(package_value["shared_scores"]["current"]["rows"]), 40)
            self.assertTrue(source.refs["current/features.parquet"]["sha256"])

    def test_package_snapshot_report_can_extend_old_daily_without_changing_ranks(self):
        with self.fixture() as (source, current, p, persist, folder, hgb):
            daily = deepcopy(current)
            daily.pop("selected_hgb_features")
            text = json.dumps(daily)
            Path(current["report_path"]).write_text(text, encoding="utf-8")
            (folder / "A2_today_recommendation/latest.json").write_text(text, encoding="utf-8")
            source._bundle(full=True)
            self.assertIn("current/features.parquet", source.refs)

    def test_future_missing_generated_timestamp_and_source_gap_stay_unexecutable(self):
        for timestamp in (None, "2026-09-28T19:00:00Z", "2026-09-25T19:00:00Z"):
            with self.subTest(timestamp=timestamp), self.fixture() as (source, current, p, persist, folder, hgb):
                current["generated_at"] = timestamp
                persist()
                result = source.status(NOW)
                self.assertFalse(result["ready"])
                self.assertEqual(result["source_date"], SIGNAL)
                self.assertTrue(result["refresh_required"])
                self.assertIn("SOURCE_GENERATED_CLOCK_MISMATCH", result["data_gaps"][0]["reason"])

    def test_report_pointer_hash_mismatch_blocks_and_retains_required_signal(self):
        with self.fixture() as (source, current, p, persist, folder, hgb):
            Path(current["report_path"]).write_text("{}", encoding="utf-8")
            result = source.status(NOW)
            self.assertEqual(result["status"], "WAITING_SOURCE")
            self.assertEqual(result["signal_date"], SIGNAL)
            self.assertTrue(result["data_gaps"])
            self.assertIn("SOURCE_HASH_MISMATCH", result["data_gaps"][0]["reason"])

    def test_source_features_date_hash_model_or_score_binding_gap_reject(self):
        for kind in ("feature_date", "feature_hash", "score_date", "score_count", "score_model", "package_hash"):
            with self.subTest(kind=kind), self.fixture() as (source, current, p, persist, folder, hgb):
                if kind == "feature_date":
                    current["selected_hgb_features"]["signal_date"] = "2026-09-24"
                elif kind == "feature_hash":
                    current["selected_hgb_features"]["sha256"] = "0" * 64
                elif kind == "score_date":
                    p["shared_scores"]["current"]["signal_date"] = "2026-09-24"
                elif kind == "score_count":
                    p["shared_scores"]["current"]["rows"].pop()
                elif kind == "score_model":
                    p["shared_scores"]["model_sha256"] = "0" * 64
                persist()
                if kind == "package_hash":
                    selected = folder / "A2_selected_hgb/latest.json"
                    value = json.loads(selected.read_text(encoding="utf-8"))
                    value["source_refs"]["current/selected_hgb_features.parquet"]["sha256"] = "0" * 64
                    selected.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaises(DailySourceError):
                    source._bundle(full=True)

    def test_full_features_security_rank_incomplete_normalisation_cannot_be_skipped(self):
        with self.fixture() as (source, current, p, persist, folder, hgb):
            p["shared_scores"]["current"]["rows"][0]["security_id"] = "WRONG"
            persist()
            with self.assertRaisesRegex(DailySourceError, "SCORE_SECURITY_OR_RANKING_MISMATCH"):
                source._bundle(full=True)
            p["shared_scores"]["current"]["rows"][0]["security_id"] = "1"
            persist()
            hgb["_normalise_day"].side_effect = ValueError("INCOMPLETE_OR_NONFINITE_FROZEN_FEATURES")
            with self.assertRaisesRegex(ValueError, "INCOMPLETE_OR_NONFINITE"):
                source._bundle(full=True)


if __name__ == "__main__":
    unittest.main()
