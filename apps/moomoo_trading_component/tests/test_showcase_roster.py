"""Versioned roster custody on isolated synthetic books; no source, SDK or model IO."""
from copy import deepcopy
from contextlib import ExitStack
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
import hashlib
import http.client
import json
import tempfile
import threading
import unittest
from unittest.mock import patch

from moomoo_component.cohort import Cohort
from moomoo_component.core import Engine
from moomoo_component.server import LocalServer, applied_display_view
from moomoo_component.showcase import load_roster_reference, validate_roster_manifest, validate_state_projection
from moomoo_component.strategy import ACTIVE_PAPER_STRATEGY_IDS
from test_cohort import Source, Quotes, CLOSE, CODES, NoWorker, OPEN
from test_five_strategy_execution import FiveSource, original_auto_policy
from test_http import FakeLive

DURATION = "R6_DURATION_TREE"
ELASTIC = "R10_DIRECT_MEAN4_ELASTICNET_MID"
RIDGE = "R10_DIRECT_H5_RIDGE_MID"
SELECTED = ["RAW_A2", "HGB_DIAG_5", "R7_GROSS_LINEAR", DURATION, RIDGE]


def reference(path):
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


class ShowcaseRosterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.results = self.root / "results" / "_maintenance" / "fixture"
        self.results.mkdir(parents=True)
        self.source, self.quotes = Source(), Quotes()
        self.source.paths = SimpleNamespace(results_root=self.root / "results")
        self.now = CLOSE + timedelta(minutes=20)
        self.owner = Cohort(self.root / "cohort", self.source, self.quotes)
        self.addCleanup(lambda: self.owner.close() if not self.owner.closed else None)
        # Keep the complete original v1 binding and legacy history contract.
        self.owner.migrate_strategy_membership(migration_id="original-v1", requested_at=CLOSE.isoformat(),
            expected_precondition_sha256=self.owner._membership_precondition(),
            target_strategy_ids=list(ACTIVE_PAPER_STRATEGY_IDS), now=CLOSE)
        self.original_v1 = deepcopy(self.owner.meta["strategy_membership_binding"])
        self.source_file = self.results / "metrics.json"
        self.source_file.write_text('{"synthetic":true}', encoding="utf-8")
        self.doc = dict(schema_version=1, kind="SHOWCASE_PAPER_ROSTER_V1", revision_id="synthetic-R1",
            created_at_utc=(self.now-timedelta(seconds=1)).isoformat(), effective_at_utc=self.now.isoformat(),
            showcase_ids=list(SELECTED), source_ref=reference(self.source_file),
            evaluation_window=dict(sample="test_2026", initialization_signal_date="2026-01-02",
                first_execution_date="2026-01-05", end="2026-09-25", selection_status="POST_EXPOSURE_DISPLAY_SELECTION"),
            ranking_rule=dict(primary="annualized_sharpe_desc", comparisons=["total_return", "max_drawdown"],
                fixed_ids_excluded=True), new_book_policy="INDEPENDENT_CASH_10000_FROM_ACCEPTANCE",
            retired_book_policy="PAUSE_PRESERVE_HISTORY", broker_permission_granted=False)

    def publish(self, doc=None, name="roster.json"):
        path = self.results / name
        path.write_text(json.dumps(doc or self.doc), encoding="utf-8")
        return reference(path)

    def accept(self, ref=None, now=None):
        self.last_control_receipt = self.owner.revise_showcase_roster(roster_ref=ref or self.publish(),
            expected_precondition_sha256=self.owner._roster_precondition(), now=now or self.now)
        return self.owner.state()

    def events(self):
        return self.owner.db.execute("SELECT detail FROM events WHERE event='SHOWCASE_ROSTER_REVISED'").fetchall()

    def test_preview_verifies_refs_without_creating_books_or_loading_sources(self):
        before = set(self.owner.engines)
        with patch.object(self.source, "load", side_effect=AssertionError("inference forbidden")), \
                patch.object(self.source, "refresh", side_effect=AssertionError("fetch forbidden")), \
                patch.object(self.quotes, "quotes", side_effect=AssertionError("quote forbidden")):
            result = self.owner.preview_showcase_roster(roster_ref=self.publish(), now=self.now)
        self.assertEqual(result["showcase_ids"], SELECTED)
        self.assertEqual(set(self.owner.engines), before)
        self.assertEqual(self.events(), [])
        self.assertFalse(result["broker_permission_granted"])
        self.assertEqual(self.source.loads, [])

    def test_accept_preserves_v1_retired_book_and_new_book_starts_at_acceptance_blocked(self):
        old = self.owner.engines[ELASTIC]
        old._set("paper", {"cash": 9876.0, "positions": {CODES[0]: 1}, "fees": 4})
        old.db.execute("INSERT INTO paper_fills VALUES (?,?)", ("synthetic-old-fill",
            json.dumps(dict(strategy_id=ELASTIC, filled_at=CLOSE.isoformat(), sequence=1, paper=True))))
        old.db.commit()
        old_inception, old_path = old.paper_inception_utc, old.path
        self.owner.meta["automatic_completion_policy"] = {"synthetic": "unchanged"}
        state = self.accept()
        self.assertEqual(state["showcase_ids"], SELECTED)
        self.assertEqual(self.owner.meta["strategy_membership_binding"], self.original_v1)
        self.assertEqual(self.owner.meta["automatic_completion_policy"], {"synthetic": "unchanged"})
        retired = state["legacy_history"]["books"][ELASTIC]
        self.assertEqual((old.path, retired["inception_utc"], retired["trade_count"]), (old_path, old_inception, 1))
        self.assertTrue(retired["paused"])
        self.assertEqual(retired["cash"], 9876.0)
        book = state["books"][DURATION]
        self.assertEqual((book["initial_cash"], book["cash"], book["positions"], book["trade_count"]),
            (10000.0, 10000.0, [], 0))
        self.assertEqual(book["inception_utc"], self.now.isoformat())
        self.assertEqual(book["status"], "BLOCKED")
        self.assertEqual(book["reason"], "SHOWCASE_ROSTER_SOURCE_NOT_PREPARED")
        self.assertEqual(self.owner.engines[DURATION].paper_nav_history()[0]["basis"], "INITIAL_CASH")
        self.assertTrue(self.owner.engines[DURATION].paper_only)
        self.assertIsNone(self.owner.engines[DURATION].broker)
        self.assertIsNone(self.owner.engines[DURATION]._get("automatic_completion_policy", None))
        self.assertEqual(self.source.loads, [])
        self.assertEqual(self.quotes.calls, [])

    def test_same_reference_is_idempotent_but_is_reverified_before_returning(self):
        ref = self.publish()
        original = self.accept(ref)
        duplicate = self.owner.revise_showcase_roster(roster_ref=ref,
            expected_precondition_sha256="0"*64, now=self.now+timedelta(seconds=1))
        self.assertTrue(duplicate["idempotent"])
        self.assertEqual(duplicate["roster_ref"], original["roster_ref"])
        self.assertEqual(self.owner.meta["showcase_roster_binding"], original["showcase_roster_binding"])
        self.assertEqual(len(self.events()), 1)
        self.source_file.write_text('{"synthetic":"changed"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "REFERENCE_CHANGED"):
            self.owner.revise_showcase_roster(roster_ref=ref,
                expected_precondition_sha256=self.owner._roster_precondition(), now=self.now+timedelta(seconds=2))
        self.assertEqual(len(self.events()), 1)

    def test_second_revision_and_restart_preserve_all_book_epochs_and_history(self):
        self.accept()
        duration = self.owner.engines[DURATION]
        duration._set("paper", {"cash": 9990.0, "positions": {}, "fees": 10.0})
        inception = duration.paper_inception_utc
        next_doc = deepcopy(self.doc)
        next_doc.update(revision_id="synthetic-R2", created_at_utc=(self.now+timedelta(minutes=1)).isoformat(),
            effective_at_utc=(self.now+timedelta(minutes=1)).isoformat(), showcase_ids=list(ACTIVE_PAPER_STRATEGY_IDS))
        self.accept(self.publish(next_doc, "roster2.json"), self.now+timedelta(minutes=1))
        self.assertEqual(self.owner.state()["legacy_history"]["books"][DURATION]["cash"], 9990.0)
        self.owner.close()
        self.owner = Cohort(self.root / "cohort", self.source, self.quotes)
        self.assertEqual(self.owner._active_ids(), ACTIVE_PAPER_STRATEGY_IDS)
        self.assertIn(DURATION, self.owner.engines)
        self.assertEqual(self.owner.engines[DURATION].paper_inception_utc, inception)
        self.assertEqual(self.owner.engines[DURATION].paper_book()["cash"], 9990.0)
        self.assertEqual(len(self.events()), 2)
        self.assertEqual(self.owner.meta["strategy_membership_binding"], self.original_v1)

    def test_reselect_old_book_never_resets_its_cash_or_inception(self):
        self.accept()
        first = self.owner.engines[DURATION].paper_inception_utc
        self.owner.engines[DURATION]._set("paper", {"cash": 9901.0, "positions": {}, "fees": 99})
        for number, ids in ((2, list(ACTIVE_PAPER_STRATEGY_IDS)), (3, SELECTED)):
            doc = deepcopy(self.doc)
            clock = self.now+timedelta(minutes=number)
            doc.update(revision_id=f"synthetic-R{number}", created_at_utc=clock.isoformat(),
                effective_at_utc=clock.isoformat(), showcase_ids=list(ids))
            self.accept(self.publish(doc, f"roster{number}.json"), clock)
        book = self.owner.state()["books"][DURATION]
        self.assertEqual((book["cash"], book["inception_utc"]), (9901.0, first))
        self.assertEqual(book["status"], "BLOCKED")
        self.assertEqual(self.owner.meta["showcase_roster_binding"]["created_book_ids"], [])

    def test_running_pending_tick_and_stale_preconditions_reject_without_creation(self):
        ref = self.publish()
        args = dict(roster_ref=ref, expected_precondition_sha256=self.owner._roster_precondition(), now=self.now)
        self.owner.stop_event.clear()
        with self.assertRaisesRegex(ValueError, "REQUIRES_STOPPED"):
            self.owner.revise_showcase_roster(**args)
        self.owner.stop_event.set()
        with patch.object(self.owner.engines["RAW_A2"], "_pending", return_value=True):
            with self.assertRaisesRegex(ValueError, "PENDING_ORDER"):
                self.owner.revise_showcase_roster(**args)
        self.owner.tick_lock.acquire()
        try:
            with self.assertRaisesRegex(ValueError, "WAIT_FOR_TICK"):
                self.owner.revise_showcase_roster(**args)
        finally:
            self.owner.tick_lock.release()
        with self.assertRaisesRegex(ValueError, "PRECONDITION_CHANGED"):
            self.owner.revise_showcase_roster(**{**args, "expected_precondition_sha256": "0"*64})
        self.assertNotIn(DURATION, self.owner.engines)
        self.assertFalse((self.owner.path / "books" / DURATION).exists())
        self.assertEqual(self.events(), [])

    def test_manifest_cannot_expand_scope_grant_permission_or_be_future_effective(self):
        for update, reason in (
            ({"showcase_ids": SELECTED+["R6_BUY_NEURAL"]}, "FIVE_QUERYABLE"),
            ({"showcase_ids": ["HGB_FACTOR_5", *SELECTED[1:]]}, "FIVE_QUERYABLE"),
            ({"broker_permission_granted": True}, "PAPER_ONLY"),
            ({"effective_at_utc": (self.now+timedelta(seconds=1)).isoformat()}, "NOT_EFFECTIVE"),
            ({"schema_version": True}, "SCHEMA_INVALID"),
        ):
            with self.subTest(update=update):
                doc = {**self.doc, **update}
                with self.assertRaisesRegex(ValueError, reason):
                    validate_roster_manifest(doc, now=self.now)
        self.assertEqual(self.events(), [])

    def test_path_or_manifest_drift_rejected_and_restart_checks_external_ref(self):
        ref = self.publish()
        bad = {**ref, "sha256": "0"*64}
        with self.assertRaisesRegex(ValueError, "REFERENCE_CHANGED"):
            self.accept(bad)
        outside = self.root / "outside.json"
        outside.write_text(json.dumps(self.doc), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "RESULTS_PATH"):
            load_roster_reference(reference(outside), paths=self.source.paths, now=self.now)
        self.accept(ref)
        self.owner.close()
        self.source_file.write_text("drift", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "REFERENCE_CHANGED"):
            Cohort(self.root / "cohort", self.source, self.quotes)

    def test_event_chain_or_active_membership_tamper_is_rejected(self):
        self.accept()
        self.owner.meta["active_strategy_ids"] = list(ACTIVE_PAPER_STRATEGY_IDS)
        with self.assertRaisesRegex(ValueError, "ACTIVE_IDS_CHANGED"):
            self.owner._active_ids()
        self.owner.meta["active_strategy_ids"] = list(SELECTED)
        detail = self.events()[0][0]
        self.owner.db.execute("DELETE FROM events WHERE event='SHOWCASE_ROSTER_REVISED'")
        self.owner.db.commit()
        try:
            with self.assertRaisesRegex(ValueError, "AUDIT_MISSING"):
                self.owner._active_ids()
        finally:
            # Restore the deliberately damaged fixture so normal owner close can run.
            self.owner.db.execute("INSERT INTO events VALUES (?,?,?)",
                (self.now.isoformat(), "SHOWCASE_ROSTER_REVISED", detail))
            self.owner.db.commit()

    def test_display_projection_is_pure_and_api_fault_never_falls_back_to_old_five(self):
        old = validate_state_projection({"books": {}})
        self.assertEqual(old["showcase_ids"], list(ACTIVE_PAPER_STRATEGY_IDS))
        self.assertIsNone(old["roster_ref"])
        state = self.accept()
        display = applied_display_view(state)
        with patch("moomoo_component.showcase.load_roster_reference", side_effect=AssertionError("no reread")):
            self.assertEqual(validate_state_projection(display)["showcase_ids"], SELECTED)
        for changed in (
            {"books": {}, "error": "unavailable"},
            {"books": {}, "roster_ref": state["roster_ref"]},
            {**display, "showcase_ids": list(ACTIVE_PAPER_STRATEGY_IDS)},
            {**display, "roster_ref": {**state["roster_ref"], "sha256": "0"*64}},
        ):
            with self.subTest(changed=list(changed)):
                with self.assertRaises(ValueError):
                    validate_state_projection(changed)

    def test_http_preview_and_accept_require_csrf_and_exact_fields(self):
        engine = Engine(self.root / "http-engine")
        server = LocalServer(0, engine, live=FakeLive(), cohort=self.owner)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            ref = self.publish()
            def post(path, body, token=True):
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                headers = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{server.server_port}"}
                if token:
                    headers["X-CSRF-Token"] = server.token
                conn.request("POST", path, json.dumps(body) if token else "", headers)
                response = conn.getresponse()
                result = response.status, json.loads(response.read())
                conn.close()
                return result
            preview_path, accept_path = "/api/applied/showcase-roster-preview", "/api/applied/showcase-roster"
            self.assertEqual(post(accept_path, {}, token=False)[0], 403)
            status, preview = post(preview_path, {"roster_ref": ref})
            self.assertEqual(status, 200, preview)
            self.assertEqual(self.events(), [])
            args = {"roster_ref": ref, "expected_precondition_sha256": preview["data"]["roster_precondition_sha256"]}
            self.assertEqual(post(accept_path, {**args, "account_id": "forbidden"})[0], 400)
            status, accepted = post(accept_path, args)
            self.assertEqual(status, 200, accepted)
            self.assertEqual(accepted["data"]["showcase_ids"], SELECTED)
            self.assertEqual(self.source.loads, [])
            self.assertEqual(self.quotes.calls, [])
        finally:
            server.shutdown()
            server.server_close()
            worker.join(2)
            engine.close()

    def test_unprepared_duration_keeps_four_ready_books_and_original_broker_hook_independent(self):
        self.accept()
        source = FiveSource()
        source.paths = self.source.paths
        source.blocked.add(DURATION)
        self.owner.source = source
        with patch.object(self.owner, "_hook") as hook, patch("moomoo_component.cohort.threading.Thread", NoWorker):
            self.owner.start()
            self.quotes.clock = OPEN+timedelta(seconds=10)
            state = self.owner.tick(now=self.quotes.clock)
        self.assertEqual(state["books"][DURATION]["status"], "BLOCKED")
        self.assertEqual(state["books"][DURATION]["reason"], "synthetic missing identity")
        for sid in set(SELECTED)-{DURATION}:
            self.assertEqual(state["books"][sid]["status"], "EXECUTED", state["books"][sid])
        self.assertTrue(any(call.args == ("tick",) for call in hook.call_args_list))
        self.assertEqual(state["legacy_history"]["books"][ELASTIC]["trade_count"], 0)
        self.assertEqual(self.owner.engines[DURATION].paper_book()["trade_count"], 0)

    def test_roster_acceptance_does_not_expand_original_automatic_policy_or_clock(self):
        self.owner.close()
        self.owner = Cohort(self.root/"clock-cohort", self.source, self.quotes,
            execution_delay_minutes=25, execution_window_seconds=1500)
        self.owner.migrate_strategy_membership(migration_id="clock-v1", requested_at=CLOSE.isoformat(),
            expected_precondition_sha256=self.owner._membership_precondition(),
            target_strategy_ids=list(ACTIVE_PAPER_STRATEGY_IDS), now=CLOSE)
        policy = original_auto_policy()
        policy.update(schema_version=2, execution_delay_minutes=25, priority_window_seconds=1500)
        self.owner.meta["automatic_completion_policy"] = deepcopy(policy)
        self.accept()
        self.assertEqual(self.owner.meta["automatic_completion_policy"], policy)
        self.assertEqual((self.owner.execution_delay_minutes,self.owner.execution_window_seconds),(25,1500))
        self.assertIsNone(self.owner.engines[DURATION]._automatic_completion_policy(
            OPEN+timedelta(minutes=25),DURATION,execution_date="2026-09-29"))
        self.assertNotIn(DURATION, policy["active_strategy_ids"])
        self.assertIsNone(self.owner.best_broker)

    def test_roster_revision_cannot_bypass_or_detach_original_v1_membership(self):
        original = self.owner.meta.pop("strategy_membership_binding")
        try:
            with self.assertRaisesRegex(ValueError,"ORIGINAL_V1_BINDING_REQUIRED"):
                self.accept()
        finally:
            self.owner.meta["strategy_membership_binding"] = original
        self.accept()
        self.owner.meta.pop("strategy_membership_binding")
        try:
            with self.assertRaisesRegex(ValueError,"ORIGINAL_V1_BINDING_CHANGED"):
                self.owner._active_ids()
        finally:
            self.owner.meta["strategy_membership_binding"] = original

    def test_failed_roster_commit_creates_no_unaccepted_directory_and_can_retry(self):
        ref = self.publish()
        original_db = self.owner.db
        class CommitFailure:
            def __getattr__(self, key):
                return getattr(original_db, key)
            def __enter__(self):
                original_db.__enter__()
                return self
            def __exit__(self, kind, value, tb):
                if kind is None:
                    original_db.rollback()
                    raise RuntimeError("synthetic cohort commit failure")
                return original_db.__exit__(kind, value, tb)
        self.owner.db = CommitFailure()
        try:
            with self.assertRaisesRegex(RuntimeError,"synthetic cohort commit failure"):
                self.accept(ref)
        finally:
            self.owner.db = original_db
        self.assertNotIn("showcase_roster_binding",self.owner.meta)
        self.assertEqual(self.events(),[])
        self.assertNotIn(DURATION,self.owner.engines)
        self.assertFalse((self.owner.path/"books"/DURATION).exists())
        later = self.now+timedelta(minutes=1)
        state = self.accept(ref,later)
        self.assertEqual(state["books"][DURATION]["inception_utc"],later.isoformat())

    def test_accepted_book_open_failure_recovers_only_with_custody_and_original_acceptance_clock(self):
        ref = self.publish()
        with patch("moomoo_component.cohort.Engine",side_effect=RuntimeError("synthetic open failure")):
            with self.assertRaisesRegex(RuntimeError,"synthetic open failure"):
                self.accept(ref)
        self.assertEqual(len(self.events()),1)
        self.assertEqual(self.owner.state()["books"][DURATION]["reason"],"SHOWCASE_ROSTER_BOOK_OWNER_OPEN_REQUIRED")
        with self.assertRaisesRegex(ValueError,"BOOK_OWNER_OPEN_REQUIRED"):
            self.owner._active_engines()
        later=self.now+timedelta(minutes=2)
        recovered=self.owner.revise_showcase_roster(roster_ref=ref,
            expected_precondition_sha256="0"*64,now=later)
        self.assertTrue(recovered["idempotent"])
        self.assertEqual(recovered["new_books"][DURATION]["inception_utc"],self.now.isoformat())
        self.assertEqual(recovered["new_books"][DURATION]["status"],"BLOCKED")
        self.assertTrue(recovered["new_books"][DURATION]["book_owner_ready"])
        self.assertEqual(self.owner.state()["books"][DURATION]["cash"],10000.0)
        self.assertEqual(len(self.events()),1)
        self.assertFalse(recovered["broker_permission_granted"])

    def test_preexisting_unbound_book_is_never_deleted_reset_or_adopted(self):
        target=self.owner.path/"books"/DURATION
        unbound=Engine(target,paper_only=True,paper_account_id="paper-"+DURATION)
        unbound._set("paper",{"cash":8765.0,"positions":{},"fees":1235.0})
        unbound.close()
        before=hashlib.sha256((target/"state.sqlite3").read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError,"UNBOUND_BOOK_PATH_EXISTS"):
            self.accept()
        self.assertEqual(hashlib.sha256((target/"state.sqlite3").read_bytes()).hexdigest(),before)
        self.assertNotIn(DURATION,self.owner.engines)
        self.assertEqual(self.events(),[])

    def test_control_receipts_stay_small_and_never_materialize_full_account_history(self):
        ref=self.publish()
        precondition=self.owner._roster_precondition()
        oversized={"books":{"synthetic":{"nav_history":[{"payload":"x"*(4*1024*1024+1)}]}}}
        self.assertGreater(len(json.dumps(oversized).encode()),4*1024*1024)
        with ExitStack() as stack:
            dump=stack.enter_context(patch.object(self.owner,"state",return_value=oversized))
            for engine in self.owner.engines.values():
                for name in ("paper_book","paper_trades","paper_nav_history"):
                    stack.enter_context(patch.object(engine,name,side_effect=AssertionError("history read forbidden")))
            first=self.owner.revise_showcase_roster(roster_ref=ref,
                expected_precondition_sha256=precondition,now=self.now)
            duplicate=self.owner.revise_showcase_roster(roster_ref=ref,
                expected_precondition_sha256="0"*64,now=self.now+timedelta(seconds=1))
            dump.assert_not_called()
        for receipt,expected in ((first,False),(duplicate,True)):
            self.assertEqual(receipt["action"],"SHOWCASE_ROSTER_REVISION")
            self.assertEqual(receipt["status"],"ACCEPTED")
            self.assertIs(receipt["idempotent"],expected)
            self.assertEqual(receipt["showcase_ids"],SELECTED)
            self.assertEqual(receipt["roster_revision"],1)
            self.assertEqual(receipt["new_books"][DURATION]["inception_utc"],self.now.isoformat())
            self.assertLess(len(json.dumps(receipt).encode()),8192)
            self.assertFalse({"books","trades","nav_history","showcase_roster_binding","manifest"} & set(receipt))
        self.assertEqual(len(self.events()),1)

    def test_roster_metadata_has_no_full_state_engine_broker_or_external_file_reads(self):
        self.accept()
        original_engines,original_broker=self.owner.engines,self.owner.best_broker
        class ForbiddenOwner:
            def __getattribute__(self,name):
                raise AssertionError("other owner read forbidden: "+name)
        self.owner.engines,self.owner.best_broker=ForbiddenOwner(),ForbiddenOwner()
        self.owner.meta["synthetic_large_history"]="x"*(4*1024*1024+1)
        try:
            with patch.object(self.owner,"state",side_effect=AssertionError("full state forbidden")), \
                    patch("moomoo_component.cohort.load_roster_reference",side_effect=AssertionError("file hash forbidden")):
                result=self.owner.showcase_roster_state()
        finally:
            self.owner.engines,self.owner.best_broker=original_engines,original_broker
            self.owner.meta.pop("synthetic_large_history")
        self.assertTrue(result["metadata_only"])
        self.assertEqual(result["books"],{})
        self.assertEqual(result["active_strategy_ids"],SELECTED)
        self.assertEqual(validate_state_projection(result)["showcase_ids"],SELECTED)
        self.assertEqual(result["roster_ref"],self.owner.meta["showcase_roster_binding"]["roster_ref"])
        self.assertLess(len(json.dumps(result).encode()),8192)
        self.assertNotIn("synthetic_large_history",result)
        self.assertEqual(self.source.loads,[])
        self.assertEqual(self.quotes.calls,[])

    def test_roster_metadata_v1_fallback_requires_successful_original_owner_validation(self):
        with patch.object(self.owner,"state",side_effect=AssertionError("full state forbidden")):
            result=self.owner.showcase_roster_state()
        self.assertEqual(validate_state_projection(result)["showcase_ids"],list(ACTIVE_PAPER_STRATEGY_IDS))
        self.assertIsNone(result["roster_ref"])
        self.assertNotIn("showcase_roster_binding",result)
        self.assertEqual(result["books"],{})

    def test_roster_metadata_active_binding_drift_fails_without_state_fallback(self):
        self.accept()
        self.owner.meta["active_strategy_ids"]=list(ACTIVE_PAPER_STRATEGY_IDS)
        try:
            with patch.object(self.owner,"state",side_effect=AssertionError("full state forbidden")):
                with self.assertRaisesRegex(ValueError,"ACTIVE_IDS_CHANGED"):
                    self.owner.showcase_roster_state()
        finally:
            self.owner.meta["active_strategy_ids"]=list(SELECTED)

    def _metadata_http(self,callback):
        engine=Engine(self.root/"metadata-http")
        server=LocalServer(0,engine,live=FakeLive(),cohort=self.owner)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        def get():
            conn=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=3)
            conn.request("GET","/api/applied/showcase-roster")
            response=conn.getresponse();raw=response.read(65537)
            result=response.status,json.loads(raw),len(raw)
            conn.close()
            return result
        try:
            return callback(server,get)
        finally:
            server.shutdown();server.server_close();worker.join(2);engine.close()

    def test_roster_metadata_http_is_small_and_never_calls_complete_state(self):
        self.accept()
        def check(server,get):
            with patch.object(self.owner,"state",side_effect=AssertionError("full state forbidden")), \
                    patch.object(server,"applied_view_body",side_effect=AssertionError("full display forbidden")):
                status,body,size=get()
            self.assertEqual(status,200,body)
            self.assertLess(size,8192)
            self.assertEqual(validate_state_projection(body["data"])["showcase_ids"],SELECTED)
            self.assertEqual(body["data"]["books"],{})
        self._metadata_http(check)

    def test_roster_metadata_http_unavailable_or_invalid_owner_never_defaults_to_five(self):
        def check(server,get):
            server.cohort=None
            self.assertEqual(get()[0],503)
            server.cohort=self.owner
            with patch.object(self.owner,"_active_ids",side_effect=ValueError("synthetic audit drift")), \
                    patch.object(self.owner,"state",side_effect=AssertionError("full state forbidden")):
                status,body,size=get()
            self.assertEqual(status,503)
            self.assertFalse(body["ok"])
            self.assertNotIn("data",body)
            self.assertLess(size,1024)
        self._metadata_http(check)

    def test_roster_metadata_http_keeps_separate_64kib_response_cap(self):
        def check(server,get):
            with patch.object(self.owner,"showcase_roster_state",return_value={"oversized":"x"*65536}):
                status,body,size=get()
            self.assertEqual(status,503)
            self.assertEqual(body["error"],"SHOWCASE_ROSTER_METADATA_RESPONSE_LIMIT")
            self.assertLess(size,1024)
        self._metadata_http(check)


class CurrentPaperSourceScopeTests(unittest.TestCase):
    def source(self):
        return dict(signal_date="2026-09-25", candidate_source_scope="PAPER_CANDIDATE_REFS_V1",
            source_refs={"shared": "a" * 64, DURATION + "/model": "b" * 64,
                         RIDGE + "/model": "c" * 64},
            strategy_status={sid: {"status": "READY", "signal_date": "2026-09-25"}
                             for sid in (DURATION, RIDGE)})

    def test_duration_keeps_its_own_source_and_does_not_mutate_input(self):
        source = self.source(); original = deepcopy(source)
        projected = Cohort._book_source_data(DURATION, source)
        self.assertEqual(projected["source_refs"], {"model": "b" * 64})
        self.assertEqual(source, original)

    def test_candidate_source_change_does_not_contaminate_another_book(self):
        source = self.source()
        before = {sid: Cohort._book_source_data(sid, source)["source_refs"] for sid in ("RAW_A2", RIDGE)}
        source["source_refs"][DURATION + "/model"] = "d" * 64
        after = {sid: Cohort._book_source_data(sid, source)["source_refs"] for sid in before}
        self.assertEqual(before, after)
        self.assertEqual(after["RAW_A2"], {"shared": "a" * 64})
        self.assertEqual(after[RIDGE], {"model": "c" * 64})

    def test_duration_missing_or_nonready_proof_never_falls_back_to_common_refs(self):
        for change in ("blocked", "wrong_date", "missing_ref"):
            source = self.source()
            if change == "blocked": source["strategy_status"][DURATION]["status"] = "BLOCKED"
            elif change == "wrong_date": source["strategy_status"][DURATION]["signal_date"] = "2026-09-24"
            else: del source["source_refs"][DURATION + "/model"]
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "FROZEN_BOOK_SOURCE_PROOF_UNAVAILABLE"):
                Cohort._book_source_data(DURATION, source)


class DurationSourceProofTests(unittest.TestCase):
    publish = ShowcaseRosterTests.publish
    accept = ShowcaseRosterTests.accept

    def setUp(self):
        ShowcaseRosterTests.setUp(self)
        self.accept()
        self.owner.manual_data_updates = True
        self.owner.execution_delay_minutes, self.owner.execution_window_seconds = 25, 1500
        def ref(name): return dict(path="synthetic/"+name, sha256=hashlib.sha256(name.encode()).hexdigest())
        keys = ("consensus/flags", "consensus/pool", "current", "R6_DURATION", "consensus/base_publication",
            "consensus/duration_publication", "consensus/duration_qualification", "consensus/r6_probe",
            "consensus/r6_probe_qualification", "consensus/publication", "model/duration_tree_2025")
        self.old = {key: ref(key) for key in keys}
        self.added = {key: ref(key) for key in
            ("model_receipt/duration_tree_2025", "model_contract/R6", "model_closure/R6")}
        self.current = {**self.old, **self.added}
        self.data = self.source.status(self.now)
        self.data.update(candidate_source_scope="PAPER_CANDIDATE_REFS_V1", strategy_status={
            sid: dict(status="READY", signal_date=self.data["signal_date"]) for sid in SELECTED})
        self.data["source_refs"].update({DURATION+"/"+key: value for key,value in self.current.items()})
        for sid in ("R7_GROSS_LINEAR", RIDGE):
            self.data["source_refs"][sid+"/model"] = ref(sid)
        self.status_patch = patch.object(self.source, "status", side_effect=lambda now=None: deepcopy(self.data))
        self.status_patch.start(); self.addCleanup(self.status_patch.stop)
        self.source.load = lambda **kwargs: self.fail("proof completion must not infer targets")
        for sid in SELECTED:
            refs = self.old if sid == DURATION else Cohort._book_source_data(sid, self.data)["source_refs"]
            self.owner.plans[sid] = dict(strategy_id=sid, signal_date=self.data["signal_date"],
                execution_date=self.data["execution_date"], source_refs=deepcopy(refs), rows=[], target_cash_weight=1.)
            self.owner.close_states[sid] = dict(signal_date=self.data["signal_date"], weights={}, cash_weight=1.)
            frozen = {key: self.data[key] for key in
                ("signal_date", "execution_date", "next_open_utc", "signal_close_utc", "next_close_utc")}
            frozen.update(source_refs=deepcopy(refs), execution_time_utc=(OPEN+timedelta(minutes=25)).isoformat(),
                execution_delay_minutes=25, execution_window_seconds=1500, allow_partial_quotes=True)
            self.owner.meta.setdefault("book_plan_metadata", {})[sid] = frozen
        model = self.old["model/duration_tree_2025"]
        self.owner.plans[DURATION].update(model_refs={"duration_tree_2025": model},
            source_hashes={"duration_tree_2025": model["sha256"]})
        self.owner._persist()
        self.original_plans = deepcopy(self.owner.plans)
        self.original_states = deepcopy(self.owner.close_states)
        self.original_books = {sid: engine.paper_book() for sid,engine in self.owner._active_engines().items()}
        self.original_frozen = deepcopy(self.owner.meta["book_plan_metadata"])

    def proof_events(self):
        return self.owner.db.execute("SELECT detail FROM events WHERE event='DURATION_SOURCE_PROOF_COMPLETED'").fetchall()

    def prepare(self, now=None):
        return self.owner.prepare_published_inputs(expected_signal_date=self.data["signal_date"], now=now or self.now)

    def unchanged_targets(self):
        self.assertEqual(self.owner.plans, self.original_plans)
        self.assertEqual(self.owner.close_states, self.original_states)
        self.assertEqual({sid: engine.paper_book() for sid,engine in self.owner._active_engines().items()}, self.original_books)
        self.assertEqual(self.source.loads, [])
        self.assertEqual(self.quotes.calls, [])

    def test_explicit_completion_keeps_sealed_targets_and_is_idempotent(self):
        result = self.prepare()
        self.assertEqual(result["status"], "READY", result)
        self.assertEqual(self.owner.meta["book_plan_metadata"][DURATION]["source_refs"], self.current)
        self.assertEqual(len(self.proof_events()), 1)
        event = json.loads(self.proof_events()[0][0])
        self.assertEqual(event["added_source_refs"], self.added)
        self.assertEqual(event["orders_created"], 0)
        expected = deepcopy(self.original_frozen); expected[DURATION]["source_refs"] = self.current
        self.assertEqual(self.owner.meta["book_plan_metadata"], expected)
        self.unchanged_targets()
        self.assertEqual(self.prepare()["status"], "READY")
        self.assertEqual(len(self.proof_events()), 1)
        self.unchanged_targets()

    def test_ordinary_tick_preparation_does_not_complete_proofs(self):
        errors = self.owner._prepare_active_members(self.data, self.now, explicit_update=False)
        self.assertEqual(errors[DURATION], "FROZEN_BOOK_SOURCE_CHANGED")
        self.assertEqual(self.owner.meta["book_plan_metadata"], self.original_frozen)
        self.assertEqual(self.proof_events(), [])
        self.unchanged_targets()

    def test_old_reference_drift_or_additional_missing_key_remain_blocked(self):
        for change in ("old_hash", "other_missing", "one_missing_proof"):
            with self.subTest(change=change):
                self.owner.meta["book_plan_metadata"] = deepcopy(self.original_frozen)
                self.owner.plans = deepcopy(self.original_plans)
                self.data["source_refs"][DURATION+"/current"] = deepcopy(self.current["current"])
                old = self.owner.meta["book_plan_metadata"][DURATION]["source_refs"]
                if change == "old_hash": self.data["source_refs"][DURATION+"/current"]["sha256"] = "0"*64
                elif change == "other_missing": del old["current"]
                else: old["model_contract/R6"] = self.added["model_contract/R6"]
                before = deepcopy(self.owner.meta["book_plan_metadata"])
                result = self.prepare()
                self.assertEqual(result["books"][DURATION]["reason"], "FROZEN_BOOK_SOURCE_CHANGED")
                self.assertEqual(self.owner.meta["book_plan_metadata"], before)
                self.assertEqual(self.proof_events(), [])

    def test_model_binding_and_clock_drift_reject(self):
        for change in ("model", "clock", "manual"):
            with self.subTest(change=change):
                self.owner.plans = deepcopy(self.original_plans)
                self.owner.meta["book_plan_metadata"] = deepcopy(self.original_frozen)
                self.owner.meta.pop("paper_first_execution", None)
                if change == "model": self.owner.plans[DURATION]["source_hashes"]["duration_tree_2025"] = "0"*64
                elif change == "clock": self.owner.meta["book_plan_metadata"][DURATION]["execution_delay_minutes"] = 0
                else: self.owner.meta["paper_first_execution"] = dict(signal_date=self.data["signal_date"])
                result = self.prepare()
                self.assertIn("UNTOUCHED_PAUSED_PLAN", result["books"][DURATION]["reason"])
                self.assertEqual(self.proof_events(), [])
                self.assertEqual(self.owner.meta["book_plan_metadata"][DURATION]["source_refs"], self.old)

    def test_running_pending_attempted_and_opening_reject(self):
        self.owner.stop_event.clear()
        with self.assertRaisesRegex(ValueError, "PAUSED_IDLE"):
            self.prepare()
        self.owner.stop_event.set()
        engine = self.owner.engines[DURATION]
        with patch.object(engine, "_pending", return_value=[{"synthetic": True}]):
            with self.assertRaisesRegex(ValueError, "PAUSED_IDLE"):
                self.prepare()
        engine.db.execute("INSERT INTO paper_batches VALUES (?,?)", ("attempt", json.dumps(dict(execution_date=self.data["execution_date"]))))
        engine.db.commit()
        self.assertIn("ALREADY_ATTEMPTED", self.prepare()["books"][DURATION]["reason"])
        engine.db.execute("DELETE FROM paper_batches WHERE id='attempt'"); engine.db.commit()
        self.assertIn("PREOPEN_ONLY", self.prepare(now=OPEN)["books"][DURATION]["reason"])
        self.assertEqual(self.proof_events(), [])
        self.assertEqual(self.owner.meta["book_plan_metadata"], self.original_frozen)
        self.unchanged_targets()

    def test_second_source_recheck_cannot_change_refs_or_clock(self):
        for change in ("proof", "clock"):
            with self.subTest(change=change):
                changed = deepcopy(self.data)
                if change == "proof": changed["source_refs"][DURATION+"/model_closure/R6"]["sha256"] = "0"*64
                else: changed["next_open_utc"] = (OPEN+timedelta(minutes=1)).isoformat()
                with patch.object(self.source, "status", side_effect=[deepcopy(self.data), changed]):
                    result = self.prepare()
                self.assertIn("CHANGED_DURING_RECHECK", result["books"][DURATION]["reason"])
                self.assertEqual(self.owner.meta["book_plan_metadata"], self.original_frozen)
                self.assertEqual(self.proof_events(), [])
        self.unchanged_targets()

    def test_audit_insert_failure_rolls_back_memory_and_persisted_proof(self):
        self.owner.db.execute("CREATE TEMP TRIGGER fail_proof BEFORE INSERT ON events WHEN NEW.event='DURATION_SOURCE_PROOF_COMPLETED' BEGIN SELECT RAISE(ABORT,'synthetic proof audit failure'); END")
        result = self.prepare()
        self.assertIn("synthetic proof audit failure", result["books"][DURATION]["reason"])
        saved = json.loads(self.owner.db.execute("SELECT value FROM settings WHERE key='cohort'").fetchone()[0])
        self.assertEqual(saved["book_plan_metadata"], self.original_frozen)
        self.assertEqual(self.owner.meta["book_plan_metadata"], self.original_frozen)
        self.assertEqual(self.proof_events(), [])
        self.unchanged_targets()
        self.owner.db.execute("DROP TRIGGER fail_proof")
        self.assertEqual(self.prepare()["status"], "READY")
        self.assertEqual(len(self.proof_events()), 1)


    def test_halt_during_source_recheck_cannot_commit_proof(self):
        calls = []
        def status(now=None):
            calls.append(now)
            if len(calls) == 2:
                self.owner.halt_event.set()
            return deepcopy(self.data)
        with patch.object(self.source, "status", side_effect=status):
            result = self.prepare()
        self.assertIn("UNTOUCHED_PAUSED_PLAN", result["books"][DURATION]["reason"])
        self.assertEqual(self.owner.meta["book_plan_metadata"], self.original_frozen)
        self.assertEqual(self.proof_events(), [])
        self.unchanged_targets()
