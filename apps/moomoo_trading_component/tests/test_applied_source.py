from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import socket
import sys
import threading
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from moomoo_component.applied_source import (
    DailySource, DailySourceError, LEGACY_STRATEGY_IDS as STRATEGY_IDS, _CanonicalSource,
    _clock_status, _reference, _state, _worker, _reset_request, _bytes,
)


LEGACY_POLICY = "RAW_TOP20_FROZEN_LEGACY"
DIRECT_POLICY = "HGB_TOP20_RISK_R1"
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


def application(ticker="T1", weight=.1, policy=LEGACY_POLICY):
    return {"status": "READY", "signal_date": SIGNAL, "account_basis": "CASH_START", "policy_id": policy,
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
    return {"generated_at": "2026-09-25T21:05:00Z", "source_root": "frozen-models", "policy_id": LEGACY_POLICY,
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
        if name == "scripts.research.a2.portfolio.selected_hgb":
            fields.setdefault("LEGACY_POLICY", LEGACY_POLICY)
            fields.setdefault("DIRECT_POLICY", DIRECT_POLICY)
            fields.setdefault("release_runtime", lambda **kwargs: 0)
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
        for role in ("CURRENT_CATALOG_RAW",):
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

    def native_massive_close(self, folder):
        source, store, native, massive, lineage, bind, reader, boundaries = self.qualified_massive_close(folder)
        source.repo_root = folder
        entry = lineage[0]
        entry.pop("adapter_sha256")
        native_source = {**_reference(native["path"]), "provider": "MOOMOO_OPEND", "provider_code": "US.T1", "adjustment": "RAW"}
        feature = folder / "frozen_feature_source.py"
        feature.write_bytes(b"same frozen feature builder")
        feature_ref = {**_reference(feature), "artifact_id": "source"}
        entry.update(raw_sources=[{**native_source, "role": "NATIVE_MOOMOO_ANCHOR"}],
            anchor_proof={"kind": "NEW_13F_MEMBER_NATIVE_RAW_ANCHOR", "scope": "2026_INFERENCE_ONLY",
                "old_frozen_equivalence_claimed": False, "native_source": native_source},
            security_id="1", security_ids=["1"], membership_validation="CALLER_VERIFIED_CURRENT_PIT_UNIVERSE",
            universe_id="verified_current_universe", universe_effective_date="2026-09-10",
            observed_target=SIGNAL, raw_end=SIGNAL, feature_source=feature_ref)
        def native_bind():
            bind()
            current = source._bundle.return_value[0]
            current["universe"] = {"universe_id": "verified_current_universe", "effective_date": "2026-09-10"}
            report_path = folder / "report.json"
            report_path.write_text(json.dumps(current), encoding="utf-8")
            members = folder / "mapped_members.parquet"
            members.write_bytes(b"original current security membership")
            source.refs["daily/report.json"] = _reference(report_path)
            source.refs["current/mapped_members.parquet"] = _reference(members)
        native_bind()
        loader = Mock(return_value={"components": {"ALPHA": {"artifacts": [feature_ref]}}})
        boundaries["scripts.daily_recommendation_inputs"] = {"load_frozen_binding": loader}
        return source, store, native, massive, lineage, native_bind, reader, loader, boundaries

    def test_native_massive_close_requires_original_schema_and_frozen_feature_source(self):
        with TemporaryDirectory() as tmp:
            source, _, _, _, _, _, reader, loader, boundaries = self.native_massive_close(Path(tmp))
            with modules(boundaries):
                self.assertEqual(source._closes({"T1"}, SIGNAL, {"T1": "1"}), {"US.T1": 25})
            loader.assert_called_once_with(Path(tmp))
            reader.assert_called_once()
            proof = source.refs["close/T1"]
            self.assertEqual(proof["native_anchor"]["qualification_role"], "NATIVE_MOOMOO_ANCHOR")
            self.assertEqual(len(proof["native_qualification_refs"]), 3)

    def test_native_missing_or_incorrect_identity_membership_and_source_are_rejected(self):
        for change in ("identity", "identities", "universe", "effective", "membership", "observed", "raw_end",
                       "scope", "equivalence", "kind", "anchor", "role", "provider", "code", "adjustment",
                       "feature_hash", "feature_path", "adapter_wrong", "adapter_none"):
            with self.subTest(change=change), TemporaryDirectory() as tmp:
                source, _, _, _, lineage, bind, reader, _, boundaries = self.native_massive_close(Path(tmp))
                entry = lineage[0]
                if change == "identity": entry["security_id"] = "OTHER"
                elif change == "identities": entry["security_ids"] = ["1", "OTHER"]
                elif change == "universe": entry["universe_id"] = "stale_universe"
                elif change == "effective": entry["universe_effective_date"] = "2026-09-11"
                elif change == "membership": entry["membership_validation"] = "UNVERIFIED"
                elif change == "observed": entry["observed_target"] = "2026-09-24"
                elif change == "raw_end": entry["raw_end"] = "2026-09-24"
                elif change == "scope": entry["anchor_proof"]["scope"] = "TRAINING"
                elif change == "equivalence": entry["anchor_proof"]["old_frozen_equivalence_claimed"] = True
                elif change == "kind": entry["anchor_proof"]["kind"] = "UNKNOWN"
                elif change == "anchor": entry["anchor_proof"]["native_source"] = {}
                elif change == "role": entry["raw_sources"][0]["role"] = "CURRENT_CATALOG_RAW"
                elif change == "provider": entry["raw_sources"][0]["provider"] = "MASSIVE_GROUPED"
                elif change == "code": entry["raw_sources"][0]["provider_code"] = "US.OTHER"
                elif change == "adjustment": entry["raw_sources"][0]["adjustment"] = "QFQ"
                elif change == "feature_hash": entry["feature_source"]["sha256"] = "0" * 64
                elif change == "feature_path": entry["feature_source"]["path"] = str(Path(tmp) / "other.py")
                elif change == "adapter_wrong": entry["adapter_sha256"] = "0" * 64
                elif change == "adapter_none": entry["adapter_sha256"] = None
                bind()
                with modules(boundaries), self.assertRaises(DailySourceError):
                    source._closes({"T1"}, SIGNAL, {"T1": "1"})
                reader.assert_not_called()

    def test_native_membership_report_or_frozen_feature_bytes_changed_during_read_rejects(self):
        for key in ("daily/report.json", "current/mapped_members.parquet", "feature_source"):
            with self.subTest(key=key), TemporaryDirectory() as tmp:
                source, _, _, _, lineage, _, reader, _, boundaries = self.native_massive_close(Path(tmp))
                result = reader.return_value
                def mutate(*args):
                    path = lineage[0][key]["path"] if key == "feature_source" else source.refs[key]["path"]
                    Path(path).write_bytes(b"changed after initial verification")
                    return result
                reader.side_effect = mutate
                with modules(boundaries), self.assertRaises(DailySourceError):
                    source._closes({"T1"}, SIGNAL, {"T1": "1"})


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

    def test_current_scores_skip_unused_history_and_keep_independent_nested_values(self):
        class UnusedHistory(list):
            def __deepcopy__(self, memo):
                raise AssertionError("unused historical scores must not be copied")

        source = self.backend()
        supplied = package()
        historical = UnusedHistory([{"ticker": "OLD"}])
        supplied["shared_scores"]["historical"] = historical
        supplied["shared_scores"]["extra_metadata"] = {"nested": ["retained"]}
        source._bundle.return_value = (report(), supplied, object())
        with modules({"scripts.research.a2.portfolio.selected_hgb": {}}):
            result = source.load({sid: state() for sid in STRATEGY_IDS}, NOW)
        self.assertEqual(result["scores"]["model_id"], "FROZEN_HGB21")
        self.assertEqual(result["scores"]["current"], supplied["shared_scores"]["current"])
        self.assertEqual(result["scores"]["extra_metadata"], {"nested": ["retained"]})
        self.assertNotIn("historical", result["scores"])
        self.assertIs(supplied["shared_scores"]["historical"], historical)
        result["scores"]["current"]["rows"][0]["pred_hgb"] = -1
        result["scores"]["extra_metadata"]["nested"].append("changed")
        self.assertEqual(supplied["shared_scores"]["current"]["rows"][0]["pred_hgb"], .3)
        self.assertEqual(supplied["shared_scores"]["extra_metadata"], {"nested": ["retained"]})

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
        infer = Mock(side_effect=lambda frame, state, source_root, policy: {
            "HGB_DIAG_5": {**application("T1", .15), "account_basis": "USER_SUPPLIED_SIGNAL_CLOSE_STATE"},
            "HGB_FACTOR_5": {**application("T2", .25), "account_basis": "USER_SUPPLIED_SIGNAL_CLOSE_STATE"}})
        states = {"HGB_DIAG_5": state({"T1": .3}, .7), "HGB_FACTOR_5": state({"T2": .6}, .4)}
        with modules({"scripts.research.a2.portfolio.selected_hgb": {"infer_targets": infer}}):
            result = source.load(states, NOW)
        self.assertEqual(infer.call_count, 2)
        self.assertTrue(all(call.kwargs["policy"] == LEGACY_POLICY for call in infer.call_args_list))
        self.assertEqual(infer.call_args_list[0].kwargs["state"], states["HGB_DIAG_5"])
        self.assertEqual(infer.call_args_list[1].kwargs["state"], states["HGB_FACTOR_5"])
        self.assertEqual(result["plans"]["HGB_DIAG_5"]["rows"][0]["weight_before"], .3)
        self.assertEqual(result["plans"]["HGB_FACTOR_5"]["rows"][0]["weight_before"], .6)
        source._closes.assert_called_once()

    def test_direct_policy_reaches_each_own_book_and_is_recorded_in_plans(self):
        source = self.backend()
        supplied = package()
        supplied["policy_id"] = DIRECT_POLICY
        frame = object()
        source._bundle.return_value = (report(), supplied, frame)
        infer = Mock(return_value={
            "HGB_DIAG_5": {**application("T1", .15, DIRECT_POLICY), "account_basis": "USER_SUPPLIED_SIGNAL_CLOSE_STATE"},
            "HGB_FACTOR_5": {**application("T2", .25, DIRECT_POLICY), "account_basis": "USER_SUPPLIED_SIGNAL_CLOSE_STATE"}})
        states = {"HGB_DIAG_5": state({"T1": .3}, .7), "HGB_FACTOR_5": state({"T2": .6}, .4)}
        with modules({"scripts.research.a2.portfolio.selected_hgb": {"infer_targets": infer}}):
            result = source.load(states, NOW)
        self.assertEqual(set(result["plans"]), set(states), result)
        self.assertEqual(infer.call_count, 2)
        for sid, call in zip(states, infer.call_args_list):
            self.assertEqual(call.kwargs["state"], states[sid])
            self.assertEqual(call.kwargs["policy"], DIRECT_POLICY)
            self.assertEqual(result["plans"][sid]["policy_id"], DIRECT_POLICY)
            self.assertFalse(result["plans"][sid]["broker_action_allowed"])

    def test_direct_cash_package_and_inference_reject_missing_or_legacy_application_policy(self):
        for basis in ("cash", "held"):
            for policy in (None, LEGACY_POLICY):
                with self.subTest(basis=basis, policy=policy):
                    source = self.backend()
                    supplied = package()
                    supplied["policy_id"] = DIRECT_POLICY
                    app = application()
                    if policy is None:
                        app.pop("policy_id")
                    supplied["strategies"]["HGB_DIAG_5"]["application"] = app
                    source._bundle.return_value = (report(), supplied, object())
                    infer = Mock(return_value={"HGB_DIAG_5": app})
                    current = state() if basis == "cash" else state({"T1": .3}, .7)
                    with modules({"scripts.research.a2.portfolio.selected_hgb": {"infer_targets": infer}}):
                        result = source.load({"HGB_DIAG_5": current}, NOW)
                    self.assertEqual(result["status"], "BLOCKED", result)
                    self.assertIn("CURRENT_TARGET_POLICY_MISMATCH", result["reason"])
                    self.assertEqual(result["plans"], {})

    def test_legacy_missing_policy_fields_remains_compatible(self):
        source = self.backend()
        supplied = package()
        supplied.pop("policy_id")
        for value in supplied["strategies"].values():
            value["application"].pop("policy_id")
        source._bundle.return_value = (report(), supplied, object())
        with modules({"scripts.research.a2.portfolio.selected_hgb": {}}):
            result = source.load({"HGB_DIAG_5": state()}, NOW)
        self.assertEqual(result["plans"]["HGB_DIAG_5"]["target_cash_weight"], .9)
        self.assertNotIn("policy_id", result["plans"]["HGB_DIAG_5"])

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


RESET_NOW = OPEN - timedelta(seconds=30)
RESET_HASH = "b" * 64


def reset_request(ids=None, **changes):
    return {"reset_id": "synthetic_cash_reset", "requested_at": "2026-09-27T12:00:00Z",
            "strategy_ids": ids or ["HGB_DIAG_5", "HGB_FACTOR_5"],
            "signal_date": SIGNAL, "expected_policy_id": DIRECT_POLICY,
            "expected_package_sha256": RESET_HASH, **changes}


class ResetPlanTests(NoNetworkTests):
    def backend(self, now=RESET_NOW):
        source = PlanTests.backend(self, now)
        supplied = package()
        supplied.update(policy_id=DIRECT_POLICY, package_sha256=RESET_HASH)
        for value in supplied["strategies"].values():
            value["application"]["policy_id"] = DIRECT_POLICY
        source._bundle.return_value = (report(), supplied, object())
        source.refs["selected/package.json"] = {"path": "verified/package.json", "sha256": RESET_HASH}
        source._closes = Mock(side_effect=AssertionError("reset must not mark existing holdings"))
        return source

    def load(self, source, request=None, now=RESET_NOW):
        infer = Mock(side_effect=AssertionError("reset must not infer or solve"))
        with modules({"scripts.research.a2.portfolio.selected_hgb": {"infer_targets": infer}}):
            result = source.load(None, now=now, reset_request=request or reset_request())
        infer.assert_not_called()
        source._closes.assert_not_called()
        return result

    def test_two_reset_plans_reuse_checked_cash_targets_without_actual_state_claim(self):
        source = self.backend()
        request = reset_request()
        before = deepcopy(request)
        result = self.load(source, request)
        self.assertEqual(request, before)
        self.assertTrue(result["ready"], result)
        self.assertEqual(set(result["plans"]), {"HGB_DIAG_5", "HGB_FACTOR_5"})
        self.assertEqual(result["reset_request_sha256"], hashlib.sha256(_bytes(request)).hexdigest())
        source._bundle.assert_called_once_with(full=True)
        for sid, plan in result["plans"].items():
            expected = source._bundle.return_value[1]["strategies"][sid]["application"]
            self.assertEqual([(row["ticker"], row["target_weight"]) for row in plan["rows"]],
                             [(row["ticker"], row["target_weight"]) for row in expected["rows"]])
            self.assertEqual(plan["target_cash_weight"], expected["target_cash_weight"])
            self.assertEqual(plan["policy_id"], DIRECT_POLICY)
            self.assertEqual(plan["reset_id"], request["reset_id"])
            self.assertEqual(plan["account_basis"], "USER_REQUESTED_POST_LIQUIDATION_CASH_START")
            self.assertEqual(plan["target_origin_account_basis"], "CASH_START")
            self.assertEqual(plan["valuation_basis"], "POST_LIQUIDATION_ASSUMPTION")
            self.assertEqual(plan["execution_condition"], "ACCOUNT_FLAT_AFTER_CONFIRMED_LIQUIDATION")
            self.assertEqual(plan["execution_status"], "TARGET_ONLY")
            self.assertFalse(plan["broker_action_allowed"])
            self.assertEqual(plan["model_fit_calls"], 0)
            self.assertEqual(result["assumed_states"][sid], {"weights": {}, "cash_weight": 1.0,
                              "valuation_basis": "POST_LIQUIDATION_ASSUMPTION"})
        self.assertNotIn("states", result)

    def test_reset_supports_only_requested_hgb_subset(self):
        for sid in STRATEGY_IDS[1:]:
            with self.subTest(sid=sid):
                result = self.load(self.backend(), reset_request([sid]))
                self.assertEqual(set(result["plans"]), {sid}, result)

    def test_reset_rejects_actual_states_and_malformed_scope_before_source_access(self):
        source = self.backend()
        with self.assertRaisesRegex(DailySourceError, "MUTUALLY_EXCLUSIVE"):
            source.load({"HGB_DIAG_5": state()}, RESET_NOW, reset_request=reset_request())
        changes = ({"strategy_ids": ["RAW_A2"]}, {"strategy_ids": []},
                   {"strategy_ids": ["HGB_DIAG_5", "HGB_DIAG_5"]},
                   {"strategy_ids": [False]}, {"reset_id": "../escape"},
                   {"expected_policy_id": LEGACY_POLICY}, {"expected_package_sha256": "bad"},
                   {"requested_at": "2099-01-01T00:00:00Z"},
                   {"requested_at": "2026-09-27T12:00:00"}, {"signal_date": "2026-99-01"},
                   {"extra_authority": True})
        for change in changes:
            with self.subTest(change=change), self.assertRaises((DailySourceError, ValueError)):
                source.load(None, RESET_NOW, reset_request=reset_request(**change))
        source.status.assert_not_called()
        source._bundle.assert_not_called()

    def test_reset_rejects_stale_signal_policy_or_package_hash_with_no_partial_plans(self):
        for kind in ("request_date", "status_date", "policy", "package_hash", "ref_hash"):
            source = self.backend()
            request = reset_request()
            if kind == "request_date":
                request["signal_date"] = "2026-09-24"
            elif kind == "status_date":
                source.status.return_value["signal_date"] = "2026-09-24"
            elif kind == "policy":
                source._bundle.return_value[1]["policy_id"] = LEGACY_POLICY
            elif kind == "package_hash":
                source._bundle.return_value[1]["package_sha256"] = "c" * 64
            else:
                source.refs["selected/package.json"]["sha256"] = "c" * 64
            with self.subTest(kind=kind):
                result = self.load(source, request)
                self.assertEqual(result["status"], "BLOCKED", result)
                self.assertEqual(result["plans"], {})
                self.assertFalse(result["ready"])

    def test_reset_requires_source_ready_and_unmissed_frozen_calendar(self):
        for kind in ("missed", "not_ready", "data_gap"):
            source = self.backend()
            if kind == "missed":
                source.status.return_value = clock(NOW)
            elif kind == "not_ready":
                source.status.return_value.update(status="WAITING_SOURCE", ready=False)
            else:
                source.status.return_value["data_gaps"] = [{"reason": "FEATURES_MISSING"}]
            with self.subTest(kind=kind):
                result = self.load(source)
                self.assertEqual(result["plans"], {})
                source._bundle.assert_not_called()

    def test_reset_rejects_non_cash_app_or_target_identity_and_constraint_changes(self):
        for kind in ("basis", "identity", "application_policy", "cap", "old_weight", "sum"):
            source = self.backend()
            app = source._bundle.return_value[1]["strategies"]["HGB_DIAG_5"]["application"]
            if kind == "basis":
                app["account_basis"] = "USER_SUPPLIED_SIGNAL_CLOSE_STATE"
            elif kind == "identity":
                source._identities.return_value.pop("T1")
            elif kind == "application_policy":
                app["policy_id"] = LEGACY_POLICY
            elif kind == "cap":
                app["rows"][0]["target_weight"] = .11
                app["target_cash_weight"] = .89
            elif kind == "old_weight":
                app["rows"][0]["weight_before"] = .01
            else:
                app["target_cash_weight"] = .5
            with self.subTest(kind=kind):
                result = self.load(source)
                self.assertEqual(result["status"], "BLOCKED", result)
                self.assertEqual(result["plans"], {})


class FacadeTests(NoNetworkTests):
    def facade(self, folder):
        config = folder / "repo/config"
        config.mkdir(parents=True, exist_ok=True)
        roots = {key + "_root": str(folder / key) for key in ("data", "cache", "daily", "backtest", "results", "envs")}
        (config / "storage_paths.json").write_text(json.dumps(roots), encoding="utf-8")
        return DailySource(folder / "repo", runtime_root=folder / "daily/paper", python_exe=sys.executable)

    def measured_memory_plan(self, sid):
        plan = application(policy=sid)
        plan["strategy_id"] = sid
        def sample(value):
            return dict(status="MEASURED", peak_scope="CURRENT_WORKER_PROCESS", working_set_bytes=value,
                process_peak_working_set_bytes=value + 10, pagefile_bytes=value + 20)
        plan["resource_receipt"] = dict(memory_before=sample(10), memory_after_model_release=sample(20),
            model_load_mode="SEQUENTIAL_HEADS_RELEASED", max_loaded_frozen_states=1 if sid == "R7_GROSS_LINEAR" else 2,
            release_weakrefs_checked=True, global_model_cache=False, resource_floor_physical_gib=1.5,
            resource_floor_page_gib=8., model_fit_calls=0, original_unknown_proof="unchanged")
        return plan

    def changed_memory_result(self, result):
        result = deepcopy(result)
        for plan in result["plans"].values():
            for key in ("memory_before", "memory_after_model_release"):
                for name in ("working_set_bytes", "process_peak_working_set_bytes", "pagefile_bytes"):
                    plan["resource_receipt"][key][name] += 100
        return result

    def test_archive_new_three_memory_rechecks_keep_original_bytes_hash_and_receipts(self):
        for sid in ("R10_DIRECT_MEAN4_ELASTICNET_MID", "R10_DIRECT_H5_RIDGE_MID", "R7_GROSS_LINEAR"):
            with self.subTest(sid=sid), TemporaryDirectory() as tmp:
                source = self.facade(Path(tmp)); original = {**clock(), "plans": {sid: self.measured_memory_plan(sid)}}
                source._archive(original, {sid: state()}); archive = Path(original["archive"]["path"]); raw = archive.read_bytes()
                current = self.changed_memory_result(original); measured = deepcopy(current["plans"][sid]["resource_receipt"])
                source._archive(current, {sid: state()})
                self.assertEqual(archive.read_bytes(), raw)
                self.assertEqual(current["archive"], original["archive"])
                self.assertEqual(current["plans"][sid]["resource_receipt"], original["plans"][sid]["resource_receipt"])
                diagnosis = current["archive_resource_recheck"]
                self.assertEqual(diagnosis["schema"], "FROZEN_ARCHIVE_RESOURCE_RECHECK_V1")
                self.assertEqual(diagnosis["preserved_archive_sha256"], hashlib.sha256(raw).hexdigest())
                self.assertEqual(diagnosis["current_resource_receipts"], {sid: measured})
                self.assertNotIn("archive_resource_recheck", json.loads(raw))
                source._archive(current, {sid: state()})
                self.assertEqual(archive.read_bytes(), raw)
                self.assertEqual(list(archive.parent.glob("*.tmp")), [])

    def test_archive_mixed_scope_only_projects_new_memory_and_keeps_unknown_proof_exact(self):
        with TemporaryDirectory() as tmp:
            source = self.facade(Path(tmp))
            ids = ("R10_DIRECT_MEAN4_ELASTICNET_MID", "R10_DIRECT_H5_RIDGE_MID", "R7_GROSS_LINEAR")
            original = {**clock(), "plans": {sid: self.measured_memory_plan(sid) for sid in ids}}
            original["plans"].update(RAW_A2=application(), HGB_DIAG_5=application())
            states = {sid: state() for sid in original["plans"]}; source._archive(original, states)
            archive = Path(original["archive"]["path"]); raw = archive.read_bytes(); current = deepcopy(original)
            for sid in ids:
                current["plans"][sid] = self.changed_memory_result({"plans": {sid: original["plans"][sid]}})["plans"][sid]
            source._archive(current, states)
            self.assertEqual(set(current["archive_resource_recheck"]["current_resource_receipts"]), set(ids))
            self.assertEqual(current["plans"], original["plans"]); self.assertEqual(archive.read_bytes(), raw)

    def test_archive_memory_exception_rejects_every_nonmeasurement_binding_and_proof_change(self):
        mutations = ("rows", "cash", "state", "source_ref", "source_hash", "clock", "model_ref", "release", "fit", "floor", "cache", "unknown_proof")
        sid = "R10_DIRECT_H5_RIDGE_MID"
        for mutation in mutations:
            with self.subTest(mutation=mutation), TemporaryDirectory() as tmp:
                source = self.facade(Path(tmp)); original = {**clock(), "plans": {sid: self.measured_memory_plan(sid)},
                    "source_refs": {"input": {"path": "frozen", "sha256": "a" * 64}}, "source_hashes": {"model": "a" * 64}}
                original["plans"][sid]["model_refs"] = {"model": {"path": "model", "sha256": "a" * 64}}
                states = {sid: state()}; source._archive(original, states); archive = Path(original["archive"]["path"]); raw = archive.read_bytes()
                current = self.changed_memory_result(original); changed_states = deepcopy(states); plan = current["plans"][sid]
                if mutation == "rows": plan["rows"][0]["target_weight"] = .2
                elif mutation == "cash": plan["target_cash_weight"] = .8
                elif mutation == "state": changed_states[sid] = state({"T1": .1}, .9)
                elif mutation == "source_ref": current["source_refs"]["input"]["sha256"] = "b" * 64
                elif mutation == "source_hash": current["source_hashes"]["model"] = "b" * 64
                elif mutation == "clock": current["next_open_utc"] = "2026-09-28T13:31:00Z"
                elif mutation == "model_ref": plan["model_refs"]["model"]["sha256"] = "b" * 64
                elif mutation == "release": plan["resource_receipt"]["release_weakrefs_checked"] = False
                elif mutation == "fit": plan["resource_receipt"]["model_fit_calls"] = 1
                elif mutation == "floor": plan["resource_receipt"]["resource_floor_physical_gib"] = .5
                elif mutation == "cache": plan["resource_receipt"]["global_model_cache"] = True
                else: plan["resource_receipt"]["original_unknown_proof"] = "changed"
                before = deepcopy(current)
                with self.assertRaisesRegex(DailySourceError, "IMMUTABLE_PAPER_PLAN_CONFLICT"):
                    source._archive(current, changed_states)
                self.assertEqual(current, before); self.assertEqual(archive.read_bytes(), raw)
                self.assertEqual(list(archive.parent.glob("*.tmp")), [])

    def test_archive_memory_exception_rejects_invalid_old_or_new_samples(self):
        malformed = ("bool", "float", "negative", "overflow", "peak_below_working", "missing", "unknown", "unavailable", "scope")
        sid = "R7_GROSS_LINEAR"
        for side in ("old", "new"):
            for mutation in malformed:
                with self.subTest(side=side, mutation=mutation), TemporaryDirectory() as tmp:
                    source = self.facade(Path(tmp)); original = {**clock(), "plans": {sid: self.measured_memory_plan(sid)}}
                    current = self.changed_memory_result(original)
                    sample = (original if side == "old" else current)["plans"][sid]["resource_receipt"]["memory_before"]
                    if mutation == "bool": sample["working_set_bytes"] = True
                    elif mutation == "float": sample["working_set_bytes"] = 1.0
                    elif mutation == "negative": sample["working_set_bytes"] = -1
                    elif mutation == "overflow": sample["working_set_bytes"] = 2**64
                    elif mutation == "peak_below_working": sample["process_peak_working_set_bytes"] = 0
                    elif mutation == "missing": sample.pop("pagefile_bytes")
                    elif mutation == "unknown": sample["unknown_count"] = 1
                    elif mutation == "unavailable": sample["status"] = "UNAVAILABLE"
                    else: sample["peak_scope"] = "SOME_OTHER_PROCESS"
                    source._archive(original, {sid: state()}); archive = Path(original["archive"]["path"]); raw = archive.read_bytes()
                    with self.assertRaisesRegex(DailySourceError, "IMMUTABLE_PAPER_PLAN_CONFLICT"):
                        source._archive(current, {sid: state()})
                    self.assertEqual(archive.read_bytes(), raw)

    def test_archive_memory_exception_never_applies_to_legacy_plans(self):
        for sid in ("RAW_A2", "HGB_DIAG_5", "HGB_FACTOR_5"):
            with self.subTest(sid=sid), TemporaryDirectory() as tmp:
                source = self.facade(Path(tmp)); plan = self.measured_memory_plan(sid); plan["policy_id"] = LEGACY_POLICY
                original = {**clock(), "plans": {sid: plan}}; source._archive(original, {sid: state()})
                archive = Path(original["archive"]["path"]); raw = archive.read_bytes()
                with self.assertRaisesRegex(DailySourceError, "IMMUTABLE_PAPER_PLAN_CONFLICT"):
                    source._archive(self.changed_memory_result(original), {sid: state()})
                self.assertEqual(archive.read_bytes(), raw)

    def test_archive_memory_exception_refuses_noncanonical_prior_bytes(self):
        sid = "R10_DIRECT_MEAN4_ELASTICNET_MID"
        for kind in ("whitespace", "key_order", "duplicate"):
            with self.subTest(kind=kind), TemporaryDirectory() as tmp:
                source = self.facade(Path(tmp)); original = {**clock(), "plans": {sid: self.measured_memory_plan(sid)}}
                source._archive(original, {sid: state()}); archive = Path(original["archive"]["path"]); raw = archive.read_bytes()
                if kind == "whitespace": altered = raw + b"\n"
                elif kind == "key_order": altered = json.dumps(json.loads(raw), sort_keys=False, indent=2).encode()
                else: altered = b'{"source_date":"' + SIGNAL.encode() + b'",' + raw[1:]
                archive.write_bytes(altered)
                with self.assertRaisesRegex(DailySourceError, "IMMUTABLE_PAPER_PLAN_CONFLICT"):
                    source._archive(self.changed_memory_result(original), {sid: state()})
                self.assertEqual(archive.read_bytes(), altered)

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

    def test_direct_policy_same_date_preserves_legacy_archive_in_distinct_namespace(self):
        with TemporaryDirectory() as tmp:
            source = self.facade(Path(tmp))
            legacy = {**clock(), "plans": {"HGB_DIAG_5": application()}, "source_refs": {}}
            legacy["plans"]["HGB_DIAG_5"].pop("policy_id")
            source._archive(legacy, {"HGB_DIAG_5": state()})
            legacy_path = Path(legacy["archive"]["path"])
            legacy_bytes = legacy_path.read_bytes()
            direct = {**clock(), "plans": {"HGB_DIAG_5": application(policy=DIRECT_POLICY)}, "source_refs": {}}
            source._archive(direct, {"HGB_DIAG_5": state()})
            direct_path = Path(direct["archive"]["path"])
            self.assertEqual(direct_path, source.runtime_root / "policies" / DIRECT_POLICY / SIGNAL / "plans.json")
            self.assertNotEqual(direct_path, legacy_path)
            self.assertEqual(legacy_path.read_bytes(), legacy_bytes)
            source._archive(direct, {"HGB_DIAG_5": state()})
            direct["plans"]["HGB_DIAG_5"]["target_cash_weight"] = .99
            with self.assertRaisesRegex(DailySourceError, "IMMUTABLE_PAPER_PLAN_CONFLICT"):
                source._archive(direct, {"HGB_DIAG_5": state()})

    def reset_result(self):
        source = ResetPlanTests.backend(self)
        infer = Mock(side_effect=AssertionError("reset must not infer"))
        with modules({"scripts.research.a2.portfolio.selected_hgb": {"infer_targets": infer}}):
            result = source.load(None, now=RESET_NOW, reset_request=reset_request())
        self.assertTrue(result["plans"], result)
        return result

    def test_reset_archive_preserves_both_signal_close_namespaces_and_is_idempotent(self):
        with TemporaryDirectory() as tmp:
            source = self.facade(Path(tmp))
            archived = []
            for policy in (None, DIRECT_POLICY):
                ordinary = {**clock(), "plans": {"HGB_DIAG_5": application()}, "source_refs": {}}
                if policy is None:
                    ordinary["plans"]["HGB_DIAG_5"].pop("policy_id")
                else:
                    ordinary["plans"]["HGB_DIAG_5"]["policy_id"] = policy
                source._archive(ordinary, {"HGB_DIAG_5": state()})
                path = Path(ordinary["archive"]["path"])
                archived.append((path, path.read_bytes()))
            result = self.reset_result()
            source._archive(result)
            path = Path(result["archive"]["path"])
            expected = source.runtime_root / "policies" / DIRECT_POLICY / "resets" / "synthetic_cash_reset" / SIGNAL / "plans.json"
            self.assertEqual(path, expected)
            before = path.read_bytes()
            payload = json.loads(before)
            self.assertEqual(payload["reset_request"], result["reset_request"])
            self.assertEqual(payload["assumed_states"], result["assumed_states"])
            self.assertNotIn("states", payload)
            self.assertNotIn("close_asof_utc", payload)
            self.assertNotIn("equity", payload)
            result.update(now_utc="2026-09-28T13:29:59Z", status="READY")
            source._archive(result)
            self.assertEqual(path.read_bytes(), before)
            result["plans"]["HGB_DIAG_5"]["target_cash_weight"] = .99
            with self.assertRaisesRegex(DailySourceError, "IMMUTABLE_PAPER_PLAN_CONFLICT"):
                source._archive(result)
            self.assertEqual(path.read_bytes(), before)
            for old_path, old_bytes in archived:
                self.assertEqual(old_path.read_bytes(), old_bytes)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_reset_archive_refuses_actual_states_or_forged_assumptions(self):
        with TemporaryDirectory() as tmp:
            source = self.facade(Path(tmp))
            for kind in ("state", "equity", "reset_id", "sha", "ids"):
                result = self.reset_result()
                states = {"HGB_DIAG_5": state()} if kind == "state" else None
                if kind == "equity":
                    result["assumed_states"]["HGB_DIAG_5"]["equity"] = 10000
                elif kind == "reset_id":
                    result["plans"]["HGB_DIAG_5"]["reset_id"] = "OTHER"
                elif kind == "sha":
                    result["reset_request_sha256"] = "c" * 64
                elif kind == "ids":
                    result["plans"].pop("HGB_FACTOR_5")
                with self.subTest(kind=kind), self.assertRaisesRegex(DailySourceError, "RESET_ARCHIVE_IDENTITY"):
                    source._archive(result, states)
            self.assertFalse(source.runtime_root.exists())

    def test_reset_facade_serializes_fixed_load_request_and_archives_verified_result(self):
        with TemporaryDirectory() as tmp:
            source = self.facade(Path(tmp))
            result = self.reset_result()
            with patch.object(source, "_call", return_value=result) as call:
                received = source.load(None, RESET_NOW, reset_request=reset_request())
            call.assert_called_once_with("load", states=None, now="2026-09-28T13:29:30Z", reset_request=reset_request())
            self.assertTrue(Path(received["archive"]["path"]).is_file())
            with self.assertRaisesRegex(DailySourceError, "MUTUALLY_EXCLUSIVE"):
                source.load({"HGB_DIAG_5": state()}, RESET_NOW, reset_request=reset_request())

    def test_archive_rejects_mixed_or_escaping_policy_names(self):
        with TemporaryDirectory() as tmp:
            source = self.facade(Path(tmp))
            for policy in ("../escape", "OTHER_POLICY"):
                value = {**clock(), "plans": {"HGB_DIAG_5": application(policy=DIRECT_POLICY),
                         "HGB_FACTOR_5": application(policy=policy)}, "source_refs": {}}
                with self.subTest(policy=policy), self.assertRaisesRegex(DailySourceError, "POLICY_IDENTITY_REQUIRED"):
                    source._archive(value, {"HGB_DIAG_5": state(), "HGB_FACTOR_5": state()})

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
            seen = {}
            def provider(paths, module, arguments, log, **kwargs):
                seen.update(module=module, arguments=arguments, timeout=kwargs["timeout"],
                            request=json.loads(kwargs["input_path"].read_text(encoding="utf-8")),
                            request_path=kwargs["input_path"], log=log)
                log.write_text(json.dumps({"ok": True, "result": clock()}), encoding="utf-8")
                return {"exit_code": 0}
            with patch("scripts.common.daily_support.run_provider", side_effect=provider) as run:
                self.assertEqual(source.status(NOW), clock())
            self.assertEqual(seen["module"], "apps.moomoo_trading_component.moomoo_component.applied_source")
            self.assertEqual(seen["arguments"], ["--worker"])
            self.assertEqual((seen["request"]["action"], seen["timeout"], run.call_count), ("status", 300, 1))
            self.assertTrue(seen["request_path"].is_relative_to(Path(tmp) / "cache"))
            self.assertFalse(seen["request_path"].exists())
            self.assertFalse(seen["log"].exists())

    def test_two_source_instances_share_one_blocking_worker_slot(self):
        with TemporaryDirectory() as tmp:
            sources = [self.facade(Path(tmp) / "local"), self.facade(Path(tmp) / "moomoo")]
            entered, release, second_calling, second_entered = (threading.Event() for _ in range(4))
            guard, active, peak, errors = threading.Lock(), [0], [0], []
            def blocking(paths, module, arguments, log, **kwargs):
                with guard:
                    active[0] += 1
                    peak[0] = max(peak[0], active[0])
                    first = not entered.is_set()
                    entered.set()
                    if not first: second_entered.set()
                try:
                    if first and not release.wait(3):
                        raise AssertionError("synthetic worker release timed out")
                    log.write_text(json.dumps({"ok": True, "result": clock()}), encoding="utf-8")
                    return {"exit_code": 0}
                finally:
                    with guard: active[0] -= 1
            def invoke(index):
                if index: second_calling.set()
                try: sources[index]._call("load")
                except BaseException as exc: errors.append(exc)
            with patch("scripts.common.daily_support.run_provider", side_effect=blocking) as run:
                threads = [threading.Thread(target=invoke, args=(index,)) for index in range(2)]
                threads[0].start()
                self.assertTrue(entered.wait(2))
                threads[1].start()
                self.assertTrue(second_calling.wait(2))
                try:
                    self.assertFalse(second_entered.wait(.1))
                    self.assertEqual(run.call_count, 1)
                    self.assertEqual(peak[0], 1)
                finally:
                    release.set()
                    for thread in threads: thread.join(3)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            self.assertEqual((run.call_count, peak[0], active[0]), (2, 1, 0))

    def test_worker_errors_keep_gaps_and_never_echo_stderr(self):
        with TemporaryDirectory() as tmp:
            source = self.facade(Path(tmp))
            def provider(paths, module, arguments, log, **kwargs):
                log.write_text(json.dumps({"ok": False, "reason": "EXACT_CLOSE_REQUIRED",
                    "data_gaps": [{"ticker": "T1"}], "source_refs": {"proof": {}}}), encoding="utf-8")
                return {"exit_code": 0, "error": "secret provider output"}
            with patch("scripts.common.daily_support.run_provider", side_effect=provider):
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

    def test_worker_streams_diagnostics_preserves_result_and_provider_log_on_success_or_failure(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for failure in (False, True):
                with self.subTest(failure=failure):
                    observed_sinks = []
                    log = folder / ("failure.log" if failure else "success.log")
                    expected = clock()
                    backend = Mock()

                    def status(**kwargs):
                        self.assertEqual(kwargs, {"now": NOW.isoformat()})
                        observed_sinks.append(sys.stdout)
                        self.assertGreaterEqual(sys.stdout.fileno(), 0)
                        for _ in range(32):
                            print("synthetic private diagnostic " + "x" * 4096)
                        log.write_text("original provider evidence", encoding="utf-8")
                        if failure:
                            raise DailySourceError("SYNTHETIC_SOURCE_FAILURE")
                        return expected

                    backend.status.side_effect = status
                    request = {"action": "status", "repo_root": "synthetic-no-canonical-reads",
                               "now": NOW.isoformat()}
                    protocol = io.StringIO()
                    with patch("sys.stdin", io.StringIO(json.dumps(request))), patch("sys.stdout", protocol), \
                            patch("moomoo_component.applied_source._CanonicalSource", return_value=backend) as constructor:
                        if failure:
                            with self.assertRaisesRegex(DailySourceError, "SYNTHETIC_SOURCE_FAILURE"):
                                _worker()
                        else:
                            self.assertIs(_worker(), expected)
                        self.assertIs(sys.stdout, protocol)
                        self.assertEqual(protocol.getvalue(), "")
                    constructor.assert_called_once_with("synthetic-no-canonical-reads")
                    backend.status.assert_called_once_with(now=NOW.isoformat())
                    self.assertEqual(log.read_text(encoding="utf-8"), "original provider evidence")
                    self.assertEqual(len(observed_sinks), 1)
                    self.assertTrue(observed_sinks[0].closed)

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
                        "active_policy": Mock(return_value=(LEGACY_POLICY, selected)),
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

    def test_configured_direct_package_is_consumed_and_wrong_override_fails_closed(self):
        with self.fixture() as (source, current, p, persist, folder, hgb):
            p["policy_id"] = DIRECT_POLICY
            persist()
            direct = folder / "A2_selected_hgb/direct_hgb_r1/latest.json"
            direct.parent.mkdir()
            direct.write_text(json.dumps(p), encoding="utf-8")
            hgb["active_policy"].return_value = (DIRECT_POLICY, direct)
            _, value, _ = source._bundle()
            self.assertEqual(value["policy_id"], DIRECT_POLICY)
            self.assertEqual(source.refs["selected/package.json"]["path"], str(direct.resolve()))
            p["policy_id"] = LEGACY_POLICY
            persist()
            with patch.dict("os.environ", {"USTQ_SELECTED_HGB_PACKAGE": str(folder / "A2_selected_hgb/latest.json")}):
                with self.assertRaisesRegex(DailySourceError, "ACTIVE_POLICY_MISMATCH"):
                    source._bundle()

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


class ExecutionChartFacadeTests(unittest.TestCase):
    facade = FacadeTests.facade

    def setUp(self):
        guard=patch('moomoo_component.applied_source.subprocess.Popen',side_effect=AssertionError('no uncontained spawn'))
        guard.start(); self.addCleanup(guard.stop)

    def test_fixed_chart_job_uses_shared_heavy_slot_finite_owned_and_preserves_environment(self):
        with TemporaryDirectory() as tmp:
            source = self.facade(Path(tmp)); seen = {}
            entered, release = threading.Event(), threading.Event()
            def provider(paths, module, arguments, log, **kwargs):
                seen.update(module=module, arguments=arguments, log=log, kwargs=kwargs)
                entered.set()
                if not release.wait(2): raise AssertionError("synthetic release timed out")
                return {"exit_code": 0}
            with patch("scripts.common.daily_support.run_provider", side_effect=provider), \
                    patch("moomoo_component.applied_source.subprocess.Popen", side_effect=AssertionError("no uncontained spawn")):
                self.assertTrue(__import__('moomoo_component.applied_source', fromlist=['_WORKER_LOCK'])._WORKER_LOCK.acquire(False))
                job = None; lock_owned = True
                try:
                    job = source.start_execution_charts()
                    self.assertFalse(entered.wait(.1)); self.assertIsNone(job.poll())
                    __import__('moomoo_component.applied_source', fromlist=['_WORKER_LOCK'])._WORKER_LOCK.release(); lock_owned = False
                    self.assertTrue(entered.wait(2))
                    self.assertFalse(__import__('moomoo_component.applied_source', fromlist=['_WORKER_LOCK'])._WORKER_LOCK.acquire(False))
                finally:
                    if lock_owned:__import__('moomoo_component.applied_source', fromlist=['_WORKER_LOCK'])._WORKER_LOCK.release()
                    release.set()
                    if job is not None:
                        if __import__('sys').exc_info()[0] is not None:job.cancel()
                        job._thread.join(3)
                        if job._thread.is_alive():job.cancel()
            self.assertEqual(job.poll(), 0)
            self.assertEqual((seen['module'], seen['arguments']), ('scripts.daily_recommendation', ['--execution-charts']))
            self.assertEqual(seen['kwargs']['timeout'], 3600)
            self.assertNotIn('child_env', seen['kwargs'])
            self.assertFalse(seen['kwargs']['cancel_event'].is_set())
            self.assertFalse(seen['log'].exists())

    def test_poll_completes_only_after_cancelled_runner_cleanup(self):
        with TemporaryDirectory() as tmp:
            source = self.facade(Path(tmp))
            entered, cleaning, release = threading.Event(), threading.Event(), threading.Event()
            def provider(paths, module, arguments, log, **kwargs):
                entered.set(); self.assertTrue(kwargs['cancel_event'].wait(2))
                cleaning.set(); self.assertTrue(release.wait(2))
                return {'exit_code': -1, 'error': 'InterruptedError:PROVIDER_CANCELLED'}
            with patch('scripts.common.daily_support.run_provider', side_effect=provider):
                job=source.start_execution_charts(); self.assertTrue(entered.wait(2))
                cancel=threading.Thread(target=job.cancel); cancel.start()
                try:
                    self.assertTrue(cleaning.wait(2)); self.assertIsNone(job.poll())
                finally:
                    release.set(); cancel.join(2); job._thread.join(2)
            self.assertFalse(cancel.is_alive()); self.assertEqual(job.poll(), -1)

    def test_adapter_failure_is_terminal_and_cleanup_pending_does_not_fake_success(self):
        import moomoo_component.applied_source as module
        with TemporaryDirectory() as tmp:
            source=self.facade(Path(tmp))
            with patch('scripts.common.daily_support.run_provider', side_effect=RuntimeError('synthetic')):
                job=source.start_execution_charts(); job._thread.join(2)
            self.assertEqual(job.poll(), -1)
            fake=module._ExecutionChartsJob.__new__(module._ExecutionChartsJob)
            fake._cancel_event=threading.Event(); fake._thread=Mock(); fake._thread.is_alive.return_value=True
            with self.assertRaisesRegex(RuntimeError,'CLEANUP_PENDING'): fake.cancel()
            self.assertTrue(fake._cancel_event.is_set()); fake._thread.join.assert_called_once_with(timeout=12)


class ExecutionChartReceiptTests(unittest.TestCase):
    def test_same_date_receipt_requires_actual_active_package_sha(self):
        from scripts.research.a2.portfolio import selected_hgb
        from scripts.common import storage_paths
        with TemporaryDirectory() as directory:
            root = Path(directory); package = root / 'package.json'
            report = root / 'source.json'; report.write_text('immutable source')
            source_ref = {'path': str(report), 'sha256': hashlib.sha256(report.read_bytes()).hexdigest()}
            package.write_text(json.dumps({'source_refs': {'current/report.json': source_ref}}))
            digest = hashlib.sha256(package.read_bytes()).hexdigest()
            receipt = root / 'A2_today_recommendation/execution_charts/2026-10-05' / digest[:16] / 'state.json'
            receipt.parent.mkdir(parents=True)
            value = {'schema': 'A2_EXECUTION_CHART_REFRESH_STATE_V1', 'status': 'READY', 'signal_date': '2026-10-02', 'execution_date': '2026-10-05',
                     'source_report': source_ref, 'package_sha256': digest, 'broker_action_allowed': False}
            receipt.write_text(json.dumps(value))
            facade = DailySource()
            with patch.object(storage_paths, 'resolve', return_value=SimpleNamespace(daily_root=root)), \
                    patch.object(selected_hgb, 'active_policy', return_value=(DIRECT_POLICY, package)):
                self.assertEqual(facade.execution_charts_status('2026-10-05')['status'], 'READY')
                value['execution_date'] = '2026-10-06'; receipt.write_text(json.dumps(value))
                self.assertEqual(facade.execution_charts_status('2026-10-05')['status'], 'UNAVAILABLE')
                receipt.write_bytes(b' ' * 65537)
                self.assertEqual(facade.execution_charts_status('2026-10-05')['status'], 'UNAVAILABLE')


class BoundedWorkerFacadeTests(NoNetworkTests):
    facade = FacadeTests.facade

    def test_busy_is_explicit_fail_closed_without_worker_or_cache(self):
        with TemporaryDirectory() as tmp:
            source = self.facade(Path(tmp))
            lock = Mock(); lock.acquire.return_value = False
            with patch("moomoo_component.applied_source._WORKER_LOCK", lock), \
                    patch("scripts.common.daily_support.run_provider") as provider:
                with self.assertRaisesRegex(DailySourceError, "^CANONICAL_SOURCE_WORKER_BUSY$"):
                    source.load({"RAW_A2": state()}, now=NOW)
            lock.acquire.assert_called_once_with(timeout=1.0)
            lock.release.assert_not_called(); provider.assert_not_called()
            self.assertFalse((Path(tmp) / "cache").exists())
            self.assertFalse(source.runtime_root.exists())

    def test_refresh_busy_readers_return_then_verified_reader_recovers(self):
        with TemporaryDirectory() as tmp:
            source = self.facade(Path(tmp))
            entered, release = threading.Event(), threading.Event()
            result, errors = [], []
            def provider(paths, module, arguments, log, **kwargs):
                entered.set()
                if json.loads(kwargs["input_path"].read_text())["action"]=="refresh" and not release.wait(3): raise AssertionError("release timed out")
                log.write_text(json.dumps({"ok": True, "result": clock()}), encoding="utf-8")
                return {"exit_code": 0}
            def refreshing():
                try: result.append(source.refresh())
                except BaseException as exc: errors.append(exc)
            with patch("scripts.common.daily_support.run_provider", side_effect=provider) as run, \
                    patch("moomoo_component.applied_source._WORKER_LOCK_TIMEOUT_SECONDS", .05):
                worker = threading.Thread(target=refreshing); worker.start()
                try:
                    self.assertTrue(entered.wait(2))
                    for action in ("load", "close_states"):
                        with self.subTest(action=action), self.assertRaisesRegex(DailySourceError, "WORKER_BUSY"):
                            source._call(action)
                    self.assertEqual(source.status(NOW), clock())
                    self.assertEqual(run.call_count, 2)
                finally:
                    release.set(); worker.join(3)
                self.assertEqual(source.status(NOW), clock())
                self.assertEqual(run.call_count, 3)
            self.assertFalse(worker.is_alive()); self.assertEqual(errors, [])
            self.assertEqual(result, [clock()])
            self.assertEqual(list((Path(tmp)/"cache/moomoo_trading_component/canonical_source").iterdir()), [])

    def test_protocol_limits_invalid_response_and_cleanup_never_echo_contents(self):
        import moomoo_component.applied_source as module
        with TemporaryDirectory() as tmp:
            source = self.facade(Path(tmp)); limit = module._WORKER_PROTOCOL_MAX_BYTES
            with patch("scripts.common.daily_support.run_provider") as run:
                with self.assertRaisesRegex(DailySourceError, "REQUEST_TOO_LARGE"):
                    source._call("load", states={"private": "x" * (limit + 1)})
                run.assert_not_called()
            samples = [(b"x" * (limit + 1), "RESPONSE_TOO_LARGE"),
                       (b"secret provider output", "UNAVAILABLE"), (b"\xff", "UNAVAILABLE"),
                       (b"[]", "RESPONSE_INVALID"), (b'{"ok":1}', "RESPONSE_INVALID"),
                       (b'{"ok":true,"result":[]}', "RESPONSE_INVALID")]
            for raw, reason in samples:
                def provider(paths, name, arguments, log, **kwargs):
                    log.write_bytes(raw); return {"exit_code": 0}
                with self.subTest(reason=reason, size=len(raw)), \
                        patch("scripts.common.daily_support.run_provider", side_effect=provider):
                    with self.assertRaisesRegex(DailySourceError, reason) as caught:
                        source.status(NOW)
                self.assertNotIn("secret", str(caught.exception))
                self.assertEqual(list((Path(tmp)/"cache/moomoo_trading_component/canonical_source").iterdir()), [])
            self.assertTrue(module._WORKER_LOCK.acquire(blocking=False)); module._WORKER_LOCK.release()

    def test_finite_timeouts_and_failed_provider_cleanup(self):
        with TemporaryDirectory() as tmp:
            source = self.facade(Path(tmp)); observed = []
            failures = [("refresh", {"exit_code": -1, "error": "TimeoutExpired:secret"}, "WORKER_TIMEOUT", 3600),
                        ("status", {"exit_code": -1, "error": "OSError:secret"}, "WORKER_UNAVAILABLE", 300),
                        ("load", OSError("secret"), "WORKER_UNAVAILABLE", 300)]
            for action, failure, reason, deadline in failures:
                def provider(paths, name, arguments, log, **kwargs):
                    observed.append(kwargs["timeout"])
                    self.assertTrue(kwargs["input_path"].exists())
                    log.write_text("secret", encoding="utf-8")
                    if isinstance(failure, Exception): raise failure
                    return failure
                with self.subTest(action=action), patch("scripts.common.daily_support.run_provider", side_effect=provider):
                    with self.assertRaisesRegex(DailySourceError, reason) as caught: source._call(action)
                self.assertNotIn("secret", str(caught.exception))
                self.assertEqual(observed[-1], deadline)
                self.assertEqual(list((Path(tmp)/"cache/moomoo_trading_component/canonical_source").iterdir()), [])

    def test_large_settings_history_is_not_a_close_state_input(self):
        from test_cohort import CohortTests
        from test_best_broker import BestBrokerTests
        case = CohortTests(); case.setUp()
        broker = BestBrokerTests(); broker.setUp()
        try:
            expected = case.cohort._books_input()
            for engine in case.cohort._active_engines().values():
                original = engine.paper_book()
                with patch.object(engine, "paper_book", return_value={**original, "fills": "x" * 1300000,
                        "navs": "y" * 1300000, "fees_total": 123}):
                    self.assertEqual(case.cohort._books_input(), expected)
            broker.runner.snapshot = {"cash": 4321.5, "positions": {"US.T1": {"qty": 5}},
                "orders": "z" * 1300000, "fees_total": 12}
            self.assertEqual(broker.runner._book(), {"cash": 4321.5, "positions": {"US.T1": 5}})
            self.assertLess(len(_bytes({"books": expected})), 1024 * 1024)
        finally:
            broker.tearDown(); case.doCleanups()

    def test_busy_preparation_preserves_frozen_target_and_pauses_submissions(self):
        from test_best_broker import BestBrokerTests, FakeBroker
        case = BestBrokerTests(); case.setUp()
        try:
            case.partial_runner(delay=0)
            case.runner._prepare(case.opening - timedelta(seconds=1))
            self.assertIsNotNone(case.runner.plan)
            saved = deepcopy(case.engine._get("best_plan", None))
            previous = (case.runner.plan, case.runner.metadata, case.runner.prepared_at)
            with patch.object(case.source, "status", side_effect=DailySourceError("CANONICAL_SOURCE_WORKER_BUSY")):
                with self.assertRaisesRegex(DailySourceError, "WORKER_BUSY"):
                    case.runner._prepare(case.opening + timedelta(seconds=1))
                self.assertIs(case.runner.plan, previous[0]);self.assertIs(case.runner.metadata, previous[1])
                self.assertEqual(case.runner.prepared_at, previous[2])
                self.assertTrue(case.runner._source_validation_pending)
                case.tick_at(case.opening + timedelta(seconds=2))
                self.assertEqual(case.runner.status, "WAITING_SOURCE")
            self.assertEqual(case.engine._get("best_plan", None), saved)
            self.assertEqual(FakeBroker.submissions, [])
        finally: case.tearDown()


class NativeEpochRepairGuardTests(NoNetworkTests):
    """Disposable same-database custody only; never import a broker/model or call SDK."""
    def setUp(self):
        super().setUp()
        import sqlite3
        from moomoo_component import applied_source as owner
        self.sql, self.owner = sqlite3, owner
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cohort_path, self.broker_path = self.root / "cohort.sqlite3", self.root / "broker.sqlite3"
        self.plan = {"plan": {"policy_id": "R7_GROSS_LINEAR", "rows": []},
                     "metadata": {"signal_date": SIGNAL}, "close_state": {"cash": 1}}
        self.cohort = {"plans": {}, "plan_close_states": {}, "plan_metadata": {"signal_date": SIGNAL}}
        self.marker = {"phase": "COMMITTED", "repair_id": "synthetic-native-reset", "signal_date": SIGNAL,
            "cohort_db": str(self.cohort_path), "broker_db": str(self.broker_path),
            "new_hashes": {"cohort": owner._pending_plan_digest(self.cohort, "cohort"),
                           "broker": owner._pending_plan_digest(self.plan, "broker")}}
        # Existing marker/value spelling is preserved verbatim, not canonicalized.
        self.marker_raw = json.dumps(self.marker, indent=1) + "\n"
        self.legacy = {"best_plan": json.dumps(self.plan, indent=2),
            "best_account": json.dumps("1343604"), "best_strategy_id": json.dumps("R7_GROSS_LINEAR"),
            "best_capital": json.dumps({"account_id": "1343604", "budget": 10000, "unused_cash": 990000}),
            "pending_plan_repair": self.marker_raw}
        for path in (self.cohort_path, self.broker_path):
            db = sqlite3.connect(path)
            try:
                db.execute("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)")
                db.execute("CREATE TABLE audit(time TEXT,event TEXT,detail TEXT)")
                db.execute("INSERT INTO settings VALUES (?,?)", ("pending_plan_repair", self.marker_raw))
                if path == self.cohort_path:
                    db.execute("INSERT INTO settings VALUES ('cohort',?)", (json.dumps(self.cohort),))
                else:
                    for key, value in self.legacy.items():
                        db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, value))
                    db.execute("CREATE TABLE orders(id TEXT, account_id TEXT)")
                    db.execute("INSERT INTO orders VALUES ('old-order','1343604')")
                    db.execute("CREATE TABLE order_fills(id TEXT,payload TEXT)")
                    db.execute("INSERT INTO order_fills VALUES ('old-order','old-unchanged-fill')")
                db.commit()
            finally: db.close()
        # The predecessor passes the unchanged original COMMITTED contract first.
        owner._pending_repair_commit_guard(self.marker)
        self.reset_id = "synthetic-native-epoch"
        self.namespace = "native_reset_archive/" + self.reset_id + "/"
        self.record = {"schema": "NATIVE_SIM_RESET_ADOPTION_R1", "reset_id": self.reset_id,
            "request": {"reset_id": self.reset_id, "requested_at": "2026-09-28T13:00:00Z",
                "expected_old_account_id": "1343604", "new_account_id": "1436260",
                "target_strategy_id": "R10_DIRECT_H5_RIDGE_MID", "expected_precondition_sha256": "a" * 64,
                "budget": 10000}, "adopted_at_utc": "2026-09-28T13:01:00Z",
            "old_account_id": "1343604", "new_account_id": "1436260", "budget": 10000,
            "previous_strategy_id": "R7_GROSS_LINEAR", "target_strategy_id": "R10_DIRECT_H5_RIDGE_MID",
            "archive_namespace": self.namespace, "archive_manifest": {}, "archive_manifest_sha256": "",
            "ledger_prefix": {key: {"last_rowid": 0, "count": 0, "sha256": "b" * 64}
                              for key in ("orders", "order_fills", "audit")}, "ledger_prefix_sha256": "",
            "native_snapshot": {"cash": 10000, "equity": 10000, "positions": {}, "open_orders": [],
                "quotes": {}, "funds_only": True, "observed_at_utc": "2026-09-28T13:00:30Z"},
            "native_snapshot_sha256": "", "eligible_accounts": [dict(account_id="1436260",market="US",environment="SIMULATE")],
            "old_pending_repair_sha256": hashlib.sha256(self.marker_raw.encode()).hexdigest(),
            "initial_capital": {"budget": 10000, "account_id": "1436260", "unused_cash": 0,
                "initial_account_equity": 10000, "started_at": "2026-09-28T13:01:00Z"},
            "initial_capital_sha256": ""}
        for key, value in self.legacy.items(): self.archive(key, value)
        self.put("best_plan", "null")
        self.put("best_account", json.dumps("1436260"))
        self.put("best_strategy_id", json.dumps("R10_DIRECT_H5_RIDGE_MID"))
        self.put("best_capital", json.dumps(self.record["initial_capital"]))
        self.seal()

    def put(self, key, value, path=None):
        db = self.sql.connect(path or self.broker_path)
        try:
            db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, value)); db.commit()
        finally: db.close()

    def archive(self, key, value):
        entry = dict(archive_key=self.namespace+key, sha256=hashlib.sha256(value.encode()).hexdigest(),
                     size_bytes=len(value.encode()))
        self.record["archive_manifest"][key] = entry
        self.put(entry["archive_key"], value)

    def seal(self):
        for key in ("archive_manifest", "ledger_prefix", "native_snapshot", "initial_capital"):
            self.record[key+"_sha256"] = hashlib.sha256(_bytes(self.record[key])).hexdigest()
        raw = _bytes(self.record).decode()
        self.put("best_native_reset_epoch", raw)
        self.put("native_reset_receipt/"+self.reset_id, raw)
        binding = dict(schema_version=2, binding_type=self.record["schema"], native_reset_id=self.reset_id,
            native_reset_record_sha256=hashlib.sha256(_bytes(self.record)).hexdigest(),
            account_id=self.record["new_account_id"], budget=self.record["budget"],
            previous_strategy_id=self.record["previous_strategy_id"], target_strategy_id=self.record["target_strategy_id"])
        self.put("best_strategy_binding", _bytes(binding).decode())
        db=self.sql.connect(self.broker_path)
        try:
            db.execute("DELETE FROM audit WHERE event='NATIVE_SIM_RESET_ADOPTED'")
            db.execute("INSERT INTO audit VALUES ('synthetic','NATIVE_SIM_RESET_ADOPTED',?)", (raw,)); db.commit()
        finally: db.close()

    def reject(self):
        with self.assertRaises(DailySourceError) as error:
            self.owner._pending_repair_commit_guard(self.marker)
        self.assertEqual(error.exception.reason, "PENDING_REPAIR_UNFINISHED_OR_BINDING_CHANGED")

    def test_native_epoch_none_plan_keeps_original_marker_and_ledger_bytes(self):
        self.owner._pending_repair_commit_guard(self.marker)
        for path in (self.cohort_path,self.broker_path):
            db=self.sql.connect(path)
            try:self.assertEqual(db.execute("SELECT value FROM settings WHERE key='pending_plan_repair'").fetchone()[0],self.marker_raw)
            finally:db.close()
        db=self.sql.connect(self.broker_path)
        try:
            self.assertEqual(db.execute("SELECT value FROM settings WHERE key='best_plan'").fetchone()[0],"null")
            self.assertEqual(db.execute("SELECT * FROM orders").fetchall(),[("old-order","1343604")])
            self.assertEqual(db.execute("SELECT * FROM order_fills").fetchall(),[("old-order","old-unchanged-fill")])
            self.assertEqual(db.execute("SELECT count(*) FROM audit WHERE event='SIM_STRATEGY_BOUND'").fetchone()[0],0)
        finally:db.close()

    def test_large_original_binding_is_hashed_without_json_decode(self):
        old_raw=json.dumps({"unrelated_original_binding":"x"*(2*1024*1024)})
        self.archive("best_strategy_binding",old_raw);self.seal()
        original=json.loads
        def bounded(value,*args,**kwargs):
            if value==old_raw:raise AssertionError("unrelated multi-MB binding must stay raw")
            return original(value,*args,**kwargs)
        with patch.object(self.owner.json,"loads",side_effect=bounded):
            self.owner._pending_repair_commit_guard(self.marker)

    def test_typed_record_request_archive_and_current_binding_fail_closed(self):
        original=deepcopy(self.record)
        mutations=[lambda r:r.update(schema="OTHER"),lambda r:r.update(archive_namespace="E:/forbidden/"),
            lambda r:r.update(reset_id="../bad"),lambda r:r.update(new_account_id="1343604"),
            lambda r:r.update(target_strategy_id="HGB_FACTOR_5"),lambda r:r.update(budget=True),
            lambda r:r.update(budget=10**1000),
            lambda r:r["request"].update(expected_old_account_id="999"),
            lambda r:r["request"].update(expected_precondition_sha256="not-sha"),
            lambda r:r["request"].update(requested_at="2099-01-01T00:00:00Z"),
            lambda r:r["native_snapshot"].update(observed_at_utc=None),
            lambda r:r["native_snapshot"].update(funds_only=False),
            lambda r:r["eligible_accounts"][0].update(environment="REAL"),
            lambda r:r["archive_manifest"]["best_plan"].update(archive_key="F:/other/db"),
            lambda r:r["archive_manifest"]["best_plan"].update(size_bytes=True)]
        for change in mutations:
            with self.subTest(change=mutations.index(change)):
                self.record=deepcopy(original);change(self.record);self.seal();self.reject()
        self.record=original;self.seal()
        for key,value in [("best_account",'"999"'),("best_strategy_id",'"R7_GROSS_LINEAR"'),
                          ("best_capital",'{"account_id":"1436260","budget":1}'),("best_strategy_binding","{}")]:
            with self.subTest(current=key):
                db=self.sql.connect(self.broker_path)
                try:old=db.execute("SELECT value FROM settings WHERE key=?",(key,)).fetchone()[0]
                finally:db.close()
                self.put(key,value);self.reject();self.put(key,old)

    def test_changed_closure_immutable_or_duplicate_audit_reject(self):
        key=self.record["archive_manifest"]["best_plan"]["archive_key"]
        self.put(key,self.legacy["best_plan"]+" ");self.reject();self.put(key,self.legacy["best_plan"])
        self.put("native_reset_receipt/"+self.reset_id,"{}");self.reject();self.seal()
        self.put(self.namespace+"undeclared","null");self.reject()
        db=self.sql.connect(self.broker_path)
        try:
            db.execute("DELETE FROM settings WHERE key=?",(self.namespace+"undeclared",))
            raw=_bytes(self.record).decode()
            db.execute("INSERT INTO audit VALUES ('duplicate','NATIVE_SIM_RESET_ADOPTED',?)",(raw,));db.commit()
        finally:db.close()
        self.reject()

    def test_original_value_match_and_available_date_still_required(self):
        for kind in ("same_day_changed_digest","older_day","future_day"):
            with self.subTest(kind=kind):
                value=deepcopy(self.plan)
                if kind=="same_day_changed_digest":value["plan"]["rows"]=[{"changed":True}]
                if kind=="older_day":value["metadata"]["signal_date"]="2026-09-24"
                if kind=="future_day":value["metadata"]["signal_date"]="2099-01-01"
                self.archive("best_plan",json.dumps(value));self.seal();self.reject()
        self.archive("best_plan",self.legacy["best_plan"]);self.seal()
        self.owner._pending_repair_commit_guard(self.marker)

    def test_paired_marker_difference_uncommitted_or_missing_legacy_anchor_reject(self):
        changed=deepcopy(self.marker);changed["repair_id"]="other"
        self.put("pending_plan_repair",json.dumps(changed),self.cohort_path);self.reject()
        self.put("pending_plan_repair",self.marker_raw+" ",self.cohort_path);self.reject()
        self.put("pending_plan_repair",self.marker_raw,self.cohort_path)
        changed=deepcopy(self.marker);changed["phase"]="PREPARED"
        with self.assertRaises(DailySourceError):self.owner._pending_repair_commit_guard(changed)
        self.record["archive_manifest"].pop("pending_plan_repair");self.seal();self.reject()

    def test_compact_record_and_manifest_item_count_total_limits_before_decode(self):
        original=json.loads
        huge='"'+('x'*(1024*1024))+'"'
        self.put("best_native_reset_epoch",huge)
        def bounded(value,*args,**kwargs):
            if value==huge:raise AssertionError("oversized compact record may not decode")
            return original(value,*args,**kwargs)
        with patch.object(self.owner.json,"loads",side_effect=bounded):self.reject()
        self.seal();base=deepcopy(self.record)
        for key,size,count in [("oversized",16*1024*1024+1,1),("total",16*1024*1024,5),("count",1,513)]:
            with self.subTest(limit=key):
                self.record=deepcopy(base)
                for i in range(count):
                    name=key+str(i);self.record["archive_manifest"][name]={"archive_key":self.namespace+name,"sha256":"b"*64,"size_bytes":size}
                self.seal();self.reject()

    def test_absent_epoch_retains_original_current_commit_and_no_schema2_bypass(self):
        db=self.sql.connect(self.broker_path)
        try:db.execute("DELETE FROM settings WHERE key='best_native_reset_epoch'");db.commit()
        finally:db.close()
        self.put("best_plan",self.legacy["best_plan"])
        self.put("pending_plan_repair",self.marker_raw+" ",self.cohort_path)
        self.owner._pending_repair_commit_guard(self.marker)  # Old semantic equality stays unchanged.
        self.put("best_plan","null");self.reject()
