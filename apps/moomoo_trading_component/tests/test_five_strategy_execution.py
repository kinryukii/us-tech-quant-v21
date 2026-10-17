"""Five-book membership and SIM binding; synthetic books, quotes and SDK only."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import http.client
import threading
import tempfile
import unittest
from unittest.mock import patch

from moomoo_component.cohort import Cohort, _fingerprint
from moomoo_component.core import Engine
from moomoo_component.best_broker import BestBroker, SID
from moomoo_component.strategy import ACTIVE_PAPER_STRATEGY_IDS, requested_gross_input, accepted_requested_gross_state
from test_cohort import Source, Quotes, NoWorker, OPEN, CLOSE, CODES
from test_best_broker import FakeBroker, FakeSource
from test_http import FakeLive
from moomoo_component.server import LocalServer
from moomoo_component.applied_source import _pending_plan_digest, _pending_repair_commit_guard, DailySourceError

R7 = "R7_GROSS_LINEAR"
RIDGE = "R10_DIRECT_H5_RIDGE_MID"


def original_auto_policy():
    return dict(schema_version=1, enabled=True, policy_id="synthetic_auto_policy", reason="USER_EXPLICIT_DAILY_AUTO_COMPLETION",
        authorized_at_utc="2026-09-27T12:00:00+00:00", effective_execution_date="2026-09-28", evaluation_end_exclusive="2027-01-01",
        priority_window_seconds=600, close_buffer_seconds=600, one_tick_spread=True, normal_spread_bps=50,
        max_single_tick_spread_bps=200, quote_max_age_seconds=30, price_deviation_fraction=.02,
        active_strategy_ids=[SID,"HGB_FACTOR_5"], broker_account_id="3604", broker_budget=10000)


class FiveSource(Source):
    def __init__(self):
        super().__init__()
        self.blocked = set()
        self.requested = .6
        for sid in ACTIVE_PAPER_STRATEGY_IDS:
            self.weights.setdefault(sid, {CODES[0]: .05})

    def load(self, states, now=None):
        self.loads.append(deepcopy(states))
        result = self.status(now)
        result["strategy_status"] = {sid: dict(status="BLOCKED", reason="synthetic missing identity") for sid in self.blocked}
        result["plans"] = {}
        for sid in states:
            if sid in self.blocked:
                continue
            weights = self.weights[sid]
            plan = dict(strategy_id=sid, signal_date=result["signal_date"], source_date=result["signal_date"],
                target_cash_weight=1-sum(weights.values()), account_basis="SIGNAL_CLOSE",
                rows=[dict(code=code, ticker=code[3:], target_weight=weight, explicit_target=True,
                    weight_before=states[sid]["weights"].get(code[3:], 0)) for code, weight in weights.items()])
            if sid == R7:
                plan.update(previous_requested_gross=states[sid]["previous_requested_gross"], requested_gross=self.requested,
                    strategy_state_after=dict(last_signal_date=result["signal_date"], previous_requested_gross=self.requested))
            result["plans"][sid] = plan
        return result


class FiveMembershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.origin = Path(self.temp.name)/"cohort"
        self.source, self.quotes = FiveSource(), Quotes()
        self.inception = patch("moomoo_component.core.now_iso", return_value=(CLOSE-timedelta(hours=6)).isoformat())
        self.inception.start()
        self.addCleanup(self.inception.stop)
        self.cohort = Cohort(self.origin, self.source, self.quotes, execution_window_seconds=600, allow_partial_quotes=True)
        self.addCleanup(lambda: self.cohort.close() if not self.cohort.closed else None)

    def migrate(self):
        now = CLOSE+timedelta(minutes=10)
        self.request = dict(migration_id="synthetic-five", requested_at=now.isoformat(),
            expected_precondition_sha256=self.cohort.state()["membership_precondition_sha256"],
            target_strategy_ids=list(ACTIVE_PAPER_STRATEGY_IDS))
        return self.cohort.migrate_strategy_membership(**self.request, now=now)

    def tick(self, now):
        with patch("moomoo_component.cohort.threading.Thread", NoWorker):
            self.cohort.start()
        self.quotes.clock = now
        return self.cohort.tick(now=now)

    def test_membership_keeps_original_epochs_reset_policy_and_legacy_history(self):
        self.cohort.meta["active_strategy_ids"] = [SID, "HGB_FACTOR_5"]
        self.cohort.meta["paper_reset"] = {"phase": "COMMITTED", "request": {"reset_id": "old-epoch"}}
        self.cohort._persist()
        original = deepcopy(self.cohort.meta["paper_reset"])
        accounts = {sid: engine.paper_account_id for sid, engine in self.cohort.engines.items()}
        state = self.migrate()
        self.assertEqual(tuple(state["books"]), ACTIVE_PAPER_STRATEGY_IDS)
        self.assertEqual(self.cohort.meta["paper_reset"], original)
        self.assertIn("HGB_FACTOR_5", state["legacy_history"]["books"])
        self.assertEqual({sid:self.cohort.engines[sid].paper_account_id for sid in accounts}, accounts)
        self.assertEqual(self.cohort.migrate_strategy_membership(**self.request, now=CLOSE+timedelta(minutes=11))["strategy_membership_binding"], state["strategy_membership_binding"])
        self.cohort.close()
        self.cohort = Cohort(self.origin, self.source, self.quotes)
        self.assertEqual(self.cohort._active_ids(), ACTIVE_PAPER_STRATEGY_IDS)
        self.assertEqual(self.cohort.meta["paper_reset"], original)

    def test_one_missing_new_strategy_does_not_block_ready_books(self):
        self.migrate()
        self.source.blocked.add(RIDGE)
        state = self.tick(OPEN+timedelta(seconds=10))
        self.assertEqual(state["books"][RIDGE]["status"], "BLOCKED")
        for sid in set(ACTIVE_PAPER_STRATEGY_IDS)-{RIDGE}:
            self.assertEqual(state["books"][sid]["status"], "EXECUTED", state["books"][sid])
        self.assertEqual(state["legacy_history"]["books"]["HGB_FACTOR_5"]["trade_count"], 0)
        count = len(self.cohort.trades())
        self.tick(OPEN+timedelta(seconds=11))
        self.assertEqual(len(self.cohort.trades()), count)

    def test_waiting_open_projection_preserves_each_blocked_book_reason(self):
        self.migrate()
        blocked=set(ACTIVE_PAPER_STRATEGY_IDS)-{"RAW_A2",SID}
        self.source.blocked.update(blocked)
        state=self.tick(OPEN-timedelta(seconds=10))
        self.assertEqual(state["status"],"WAITING_OPEN")
        for sid in blocked:
            self.assertIsNone(state["books"][sid]["plan"])
            self.assertEqual(state["books"][sid]["status"],"BLOCKED")
            self.assertEqual(state["books"][sid]["reason"],"synthetic missing identity")
        for sid in {"RAW_A2",SID}:
            self.assertIsNotNone(state["books"][sid]["plan"])
            self.assertEqual(state["books"][sid]["status"],"WAITING_OPEN")
        saved=deepcopy(self.cohort.book_status)
        self.cohort.state()
        self.assertEqual(self.cohort.book_status,saved)

    def test_waiting_open_projection_requires_current_plan_even_without_book_status(self):
        self.migrate()
        self.source.blocked.add(R7)
        self.tick(OPEN-timedelta(seconds=10))
        self.cohort.book_status.pop(R7)
        self.cohort.meta["last_error"]="latest consensus publication missing"
        state=self.cohort.state()
        self.assertEqual(state["books"][R7]["status"],"BLOCKED")
        self.assertEqual(state["books"][R7]["reason"],"latest consensus publication missing")
        self.assertNotIn(R7,self.cohort.book_status)
        self.cohort.meta["signal_date"]=(CLOSE+timedelta(days=3)).date().isoformat()
        self.cohort.meta["execution_date"]=(OPEN+timedelta(days=3)).date().isoformat()
        self.cohort.meta["last_error"]="new signal input missing"
        state=self.cohort.state()
        self.assertEqual(state["books"][SID]["status"],"BLOCKED")
        self.assertEqual(state["books"][SID]["reason"],"new signal input missing")
        self.assertEqual(self.cohort.book_status[SID]["status"],"WAITING_OPEN")

    def test_paused_restart_new_targets_never_inherit_previous_batch_completion(self):
        from moomoo_component.server import applied_display_view
        self.migrate()
        self.quotes.errors[CODES[-1]] = "synthetic missing RAW quote"
        previous = self.tick(OPEN + timedelta(seconds=5))
        self.assertEqual(previous["books"]["RAW_A2"]["status"], "PARTIALLY_EXECUTED")
        later = {"RAW_A2", SID, R7}
        for sid in later:
            self.cohort.plans[sid]["signal_date"] = "2026-09-29"
            self.cohort.plans[sid]["source_date"] = "2026-09-29"
            self.cohort.meta["book_plan_metadata"][sid].update(signal_date="2026-09-29",
                execution_date="2026-09-30", signal_close_utc=(CLOSE + timedelta(days=1)).isoformat(),
                next_open_utc=(OPEN + timedelta(days=1)).isoformat())
        self.cohort.meta.update(signal_date="2026-09-29", execution_date="2026-09-30")
        self.cohort._persist()
        self.cohort.close()
        self.cohort = Cohort(self.origin, self.source, self.quotes)
        def raw_rows():
            return ([tuple(row) for row in self.cohort.db.execute("SELECT * FROM settings")],
                {sid: {table: [tuple(row) for row in engine.db.execute("SELECT * FROM " + table)]
                    for table in ("settings", "paper_batches", "paper_fills", "orders", "order_fills")}
                    for sid, engine in self.cohort.engines.items()})
        before = raw_rows()
        frozen = deepcopy((self.cohort.meta, self.cohort.plans, self.cohort.book_status))
        full = self.cohort.state()
        self.assertFalse(full["running"])
        for sid in ACTIVE_PAPER_STRATEGY_IDS:
            book = full["books"][sid]
            self.assertEqual(book["execution"]["signal_date"], "2026-09-28")
            self.assertEqual(book["execution"]["execution_date"], "2026-09-29")
            self.assertEqual(book["status"], "TARGET_ONLY" if sid in later else "EXECUTED")
        self.assertEqual(full["books"]["RAW_A2"]["execution"]["status"], "PARTIALLY_EXECUTED")
        self.assertEqual(self.cohort.state(compact=True), applied_display_view(full))
        self.assertEqual(raw_rows(), before)
        self.assertEqual((self.cohort.meta, self.cohort.plans, self.cohort.book_status), frozen)

    def test_completion_projection_requires_plan_batch_clock_binding(self):
        self.migrate()
        self.tick(OPEN + timedelta(seconds=5))
        original_plan = deepcopy(self.cohort.plans[SID])
        original_meta = deepcopy(self.cohort.meta["book_plan_metadata"][SID])
        original_batch = deepcopy(self.cohort.book_status[SID])
        self.cohort.stop_event.set()
        self.cohort.meta["status"] = "STOPPED"
        for mismatch in ("missing_plan", "missing_clock", "plan_clock", "batch_clock"):
            with self.subTest(mismatch=mismatch):
                self.cohort.plans[SID] = deepcopy(original_plan)
                self.cohort.meta["book_plan_metadata"][SID] = deepcopy(original_meta)
                self.cohort.book_status[SID] = deepcopy(original_batch)
                if mismatch == "missing_plan": self.cohort.plans.pop(SID)
                elif mismatch == "missing_clock": self.cohort.meta["book_plan_metadata"][SID].pop("execution_date")
                elif mismatch == "plan_clock": self.cohort.plans[SID]["signal_date"] = "2026-09-30"
                else: self.cohort.book_status[SID]["execution_date"] = "2026-09-30"
                book = self.cohort.state()["books"][SID]
                self.assertNotIn(book["status"], {"EXECUTED", "PARTIALLY_EXECUTED"})
                self.assertEqual(book["execution"], self.cohort.book_status[SID])
        self.cohort.plans[SID] = original_plan
        self.cohort.meta["book_plan_metadata"][SID] = original_meta
        self.cohort.book_status[SID] = original_batch
        self.assertEqual(self.cohort.state()["books"][SID]["status"], "EXECUTED")
        self.cohort.book_status[SID] = {**original_batch, "status": "BLOCKED", "reason": "qualification gap"}
        self.assertEqual(self.cohort.state()["books"][SID]["reason"], "qualification gap")

    def test_completed_signal_keeps_frozen_plans_when_display_source_changes(self):
        self.migrate()
        first=self.tick(OPEN+timedelta(seconds=5))
        original=deepcopy(self.cohort.plans)
        fills=len(self.cohort.trades())
        status=self.source.status
        self.source.status=lambda now=None:{**status(now),"source_refs":{"manifest":"c"*64}}
        second=self.tick(OPEN+timedelta(seconds=6))
        self.assertEqual(second["status"],"EXECUTED",second["reason"])
        self.assertEqual(self.cohort.plans,original)
        self.assertEqual(len(self.cohort.trades()),fills)

    def test_original_diagonal_standing_grant_keeps_its_own_window(self):
        policy = original_auto_policy()
        self.cohort.meta["automatic_completion_policy"] = deepcopy(policy)
        for sid in policy["active_strategy_ids"]:
            e=self.cohort.engines[sid]
            e._set("automatic_completion_policy",policy)
            e.db.execute("INSERT INTO audit VALUES (?,?,?)",(policy["authorized_at_utc"],"AUTOMATIC_COMPLETION_POLICY_AUTHORIZED",json.dumps(policy)))
            e.db.commit()
        self.migrate()
        state=self.tick(OPEN+timedelta(seconds=601))
        self.assertEqual(state["books"][SID]["status"],"EXECUTED", state["books"][SID])
        self.assertEqual(state["books"][R7]["status"],"MISSED_OPEN")
        self.assertEqual(self.cohort.meta["automatic_completion_policy"],policy)
        self.assertEqual(state["legacy_history"]["books"]["HGB_FACTOR_5"]["trade_count"],0)

    def test_only_active_diag_receives_one_tick_spread_exception(self):
        policy=original_auto_policy()
        self.cohort.meta["automatic_completion_policy"]=deepcopy(policy)
        for sid in policy["active_strategy_ids"]:
            e=self.cohort.engines[sid];e._set("automatic_completion_policy",policy)
            e.db.execute("INSERT INTO audit VALUES (?,?,?)",(policy["authorized_at_utc"],"AUTOMATIC_COMPLETION_POLICY_AUTHORIZED",json.dumps(policy)));e.db.commit()
        self.source.weights[R7]={CODES[18]:.05}
        self.migrate()
        self.assertEqual(set(self.cohort._active_ids())&set(policy["active_strategy_ids"]),{SID})
        for code in (CODES[0],CODES[18]):
            self.quotes.overrides[code]=dict(price=100,bid=99.5,ask=100.5,price_tick=1)
        state=self.tick(OPEN+timedelta(seconds=5))
        self.assertEqual(state["books"][SID]["status"],"EXECUTED",state["books"][SID])
        self.assertEqual(state["books"][R7]["trade_count"],0)
        self.assertNotEqual(state["books"][R7]["status"],"EXECUTED")
        self.assertEqual(state["legacy_history"]["books"]["HGB_FACTOR_5"]["trade_count"],0)
        self.assertIsNone(self.cohort.engines[R7]._automatic_completion_policy(OPEN+timedelta(seconds=5),R7,execution_date="2026-09-29"))

    def test_requested_g_transition_rejects_future_or_inconsistent_state(self):
        with self.assertRaisesRegex(ValueError,"FUTURE_REQUESTED"):
            requested_gross_input(dict(last_signal_date="2026-09-29",previous_requested_gross=.5),"2026-09-28")
        plan=dict(previous_requested_gross=1,requested_gross=.75,
            strategy_state_after=dict(last_signal_date="2026-09-28",previous_requested_gross=.5))
        with self.assertRaisesRegex(ValueError,"STATE_CONTRACT_INVALID"):
            accepted_requested_gross_state(plan,dict(previous_requested_gross=1),"2026-09-28")

    def test_r7_partial_restart_and_other_book_recovery_never_recurse_g(self):
        self.migrate()
        self.source.requested=.75
        self.source.weights[R7]={CODES[18]:.05,CODES[19]:.05}
        self.source.blocked.add(RIDGE)
        self.quotes.errors[CODES[19]]="synthetic unqualified quote"
        first=self.tick(OPEN+timedelta(seconds=5))
        self.assertEqual(first["books"][R7]["status"],"PARTIALLY_EXECUTED",first["books"][R7])
        self.assertEqual(first["books"][R7]["trade_count"],1)
        frozen=deepcopy(self.cohort.plans[R7])
        requested=deepcopy(self.cohort.meta["strategy_requested_state"][R7])
        self.assertEqual(requested["previous_requested_gross"],.75)
        self.cohort.close()
        self.cohort=Cohort(self.origin,self.source,self.quotes)
        self.source.requested=.5  # A second inference would recurse to another request.
        self.source.blocked.remove(RIDGE)
        self.quotes.errors.clear()
        second=self.tick(OPEN+timedelta(seconds=6))
        self.assertEqual(second["books"][R7]["status"],"EXECUTED",second["books"][R7])
        self.assertEqual(second["books"][R7]["trade_count"],2)
        self.assertEqual(second["books"][RIDGE]["status"],"EXECUTED")
        self.assertEqual(self.cohort.plans[R7],frozen)
        self.assertEqual(self.cohort.meta["strategy_requested_state"][R7],requested)
        r7_inputs=[states[R7]["previous_requested_gross"] for states in self.source.loads if R7 in states]
        self.assertEqual(r7_inputs,[1])
        self.assertEqual(self.cohort._requested_input(R7,"2026-09-28"),1)
        self.assertEqual(self.cohort._requested_input(R7,"2026-09-29"),.75)

    def test_requested_g_is_accepted_once_and_previous_input_survives_restart(self):
        self.migrate()
        now=CLOSE+timedelta(minutes=15)
        self.cohort._prepare_active_members(self.source.status(now),now)
        self.assertEqual(self.source.loads[-1][R7]["previous_requested_gross"],1)
        state=self.cohort.meta["strategy_requested_state"][R7]
        self.assertEqual(state["previous_requested_gross"],.6)
        self.assertEqual(self.cohort._requested_input(R7,"2026-09-28"),1)
        self.assertEqual(self.cohort._requested_input(R7,"2026-09-29"),.6)
        self.cohort.close()
        self.cohort=Cohort(self.origin,self.source,self.quotes)
        self.assertEqual(self.cohort._requested_input(R7,"2026-09-28"),1)
        self.assertEqual(self.cohort._requested_input(R7,"2026-09-29"),.6)

    def test_http_membership_requires_csrf_and_explicit_fields(self):
        manual=Engine(Path(self.temp.name)/"manual")
        server=LocalServer(0,manual,live=FakeLive(),cohort=self.cohort)
        worker=threading.Thread(target=server.serve_forever,daemon=True)
        worker.start()
        try:
            request=dict(migration_id="http-five",requested_at=CLOSE.isoformat(),
                target_strategy_ids=list(ACTIVE_PAPER_STRATEGY_IDS),
                expected_precondition_sha256=self.cohort._membership_precondition())
            def post(payload,token=None):
                conn=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=3)
                headers={"Content-Type":"application/json","Origin":f"http://127.0.0.1:{server.server_port}"}
                if token:headers["X-CSRF-Token"]=token
                # A rejected CSRF request sends no unread body; Windows otherwise may reset the early-closed socket.
                conn.request("POST","/api/applied/strategy-membership",json.dumps(payload) if token else "",headers)
                response=conn.getresponse();data=json.loads(response.read());status=response.status;conn.close()
                return status,data
            self.assertEqual(post(request)[0],403)
            self.assertEqual(post({**request,"account_id":"forbidden"},server.token)[0],400)
            status,data=post(request,server.token)
            self.assertEqual(status,200,data)
            self.assertEqual(tuple(data["data"]["books"]),ACTIVE_PAPER_STRATEGY_IDS)
            self.assertEqual(self.source.loads,[])
        finally:
            server.shutdown();server.server_close();worker.join(2);manual.close()

    def test_page_nav_is_bounded_but_full_history_remains_queryable(self):
        e=self.cohort.engines["RAW_A2"]
        inception_rows=len(e.paper_nav_history())
        records=[(f"{index:04}",json.dumps(dict(date=f"{index:04}",nav=1))) for index in range(1005)]
        e.db.executemany("INSERT INTO paper_nav VALUES (?,?)",records);e.db.commit()
        state=self.cohort.state()
        self.assertEqual(len(state["books"]["RAW_A2"]["nav_history"]),1000)
        full=e.paper_nav_history()
        self.assertEqual(state["books"]["RAW_A2"]["nav_history"],full[-1000:])
        self.assertEqual(len(full),1005+inception_rows)

    def test_running_or_changed_precondition_cannot_migrate(self):
        request=dict(migration_id="five",requested_at=CLOSE.isoformat(),target_strategy_ids=list(ACTIVE_PAPER_STRATEGY_IDS),expected_precondition_sha256="0"*64)
        with self.assertRaisesRegex(ValueError,"PRECONDITION_CHANGED"):
            self.cohort.migrate_strategy_membership(**request,now=CLOSE)
        self.cohort.stop_event.clear()
        with self.assertRaisesRegex(ValueError,"REQUIRES_STOPPED"):
            self.cohort.migrate_strategy_membership(**request,now=CLOSE)
        self.cohort.stop_event.set()

    def test_hold_keeps_exact_units_despite_price_and_weight_drift(self):
        e=self.cohort.engines["RAW_A2"]
        e._set("paper",dict(cash=9200,positions={CODES[0]:8},fees=0))
        plan=dict(source_date="2026-09-28",target_cash_weight=.92,
            rows=[dict(code=CODES[0],target_weight=.08,action="HOLD",explicit_target=False,exact_hold_units=8)])
        quote=dict(price=200,bid=200,ask=200,asof=(OPEN+timedelta(seconds=5)).isoformat(),tradable=True,lot_size=1,source="MOOMOO_OPEND")
        result=e.paper_rebalance("RAW_A2",plan,{CODES[0]:quote},now=OPEN+timedelta(seconds=5),next_open_utc=OPEN.isoformat(),
            signal_date="2026-09-28",execution_date="2026-09-29",signal_close_utc=CLOSE.isoformat(),
            source_refs={"fixture":"a"*64},allow_partial_quotes=True,execution_window_seconds=600)
        self.assertEqual(result["status"],"EXECUTED")
        self.assertEqual(e.paper_book()["positions"][0]["qty"],8)
        self.assertEqual(e.paper_book()["cash"],9200)
        self.assertEqual(e.paper_book()["trade_count"],0)
        changed=deepcopy(plan);changed["rows"][0]["exact_hold_units"]=7
        with self.assertRaisesRegex(ValueError,"EXACT_HOLD_UNITS_CHANGED"):
            e.paper_rebalance("RAW_A2",{**changed, "source_date": "2026-09-29"},{},now=OPEN+timedelta(days=1,seconds=5),next_open_utc=(OPEN+timedelta(days=1)).isoformat(),
                signal_date="2026-09-29",execution_date="2026-09-30",signal_close_utc=(CLOSE+timedelta(days=1)).isoformat(),execution_window_seconds=600)


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.opening=datetime(2026,9,28,13,30,tzinfo=timezone.utc)
        self.source=FakeSource(self.opening)
        FakeBroker.positions,FakeBroker.submissions={},[]
        FakeBroker.cash=1000000
        FakeBroker.submit_options,FakeBroker.reconcile_calls,FakeBroker.snapshot_calls=[],[],[]
        FakeBroker.reconcile_result,FakeBroker.before_send_error=None,None
        FakeBroker.quote_errors,FakeBroker.market_prices={},{}
        FakeBroker.prewarm_calls,FakeBroker.prewarm_error=[],None
        self.engine=Engine(self.temp.name,broker_factory=FakeBroker)
        self.runner=BestBroker(self.temp.name,self.source,engine=self.engine,execution_window_seconds=600,allow_partial_quotes=True)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(lambda:self.runner.close())
        self.runner._connect()

    def bind(self,target,binding_id="switch-r7"):
        now=self.opening+timedelta(seconds=30)
        return self.runner.bind_strategy(binding_id=binding_id,requested_at=now.isoformat(),
            expected_strategy_id=self.runner.strategy_id,target_strategy_id=target,
            expected_precondition_sha256=self.runner._strategy_binding_precondition(),now=now)

    def test_binding_and_rollback_keep_account_budget_and_raw_old_authorizations(self):
        capital=deepcopy(self.engine._get("best_capital", None))
        prior={"original":"permission bytes", "unknown_field":"retained"}
        self.engine._set("best_same_day_catchup",prior)
        state=self.bind(R7)
        self.assertEqual(state["strategy_id"],R7)
        self.assertEqual(self.engine._get("best_capital", None),capital)
        self.assertEqual(self.engine._get("best_account", None),"3604")
        self.assertEqual(self.engine._get("best_same_day_catchup", None),prior)
        self.assertIsNone(self.runner._catchup_end())
        self.assertEqual(self.runner._scoped_legacy_setting("best_same_day_catchup"),None)
        self.runner=BestBroker(self.temp.name,self.source,engine=self.engine,execution_window_seconds=600,allow_partial_quotes=True)
        self.assertEqual(self.runner.strategy_id,R7)
        self.runner._connect()
        self.bind(SID,"rollback-diag")
        self.assertEqual(self.runner.strategy_id,SID)
        self.assertEqual(self.engine._get("best_capital", None),capital)
        self.assertEqual(len(self.engine._get("best_strategy_binding_history", None)),2)
        self.assertEqual(self.engine._get("best_same_day_catchup", None),prior)
        self.assertIsNone(self.runner._catchup_end())
        with self.assertRaisesRegex(ValueError,"NOT_TRANSFERABLE"):
            self.runner._require_legacy_strategy()

    def tick_at(self, now):
        FakeBroker.clock=staticmethod(lambda:now)
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):
                return now if tz is None else now.astimezone(tz)
        with patch("moomoo_component.core.datetime",Clock),patch("moomoo_component.strategy.datetime",Clock),patch("moomoo_component.best_broker.datetime",Clock):
            self.runner.tick(now=now)

    def test_r7_rebalances_existing_positions_and_preserves_old_orders_and_cash(self):
        self.runner.stop_event.clear()
        for second in (2,3,4):
            self.tick_at(self.opening+timedelta(seconds=second))
        self.runner.stop()
        self.runner.reconcile()
        self.assertGreater(FakeBroker.positions.get("US.AAPL",0),0)
        prior_qty=FakeBroker.positions["US.AAPL"]
        old_orders=list(self.engine.db.execute("SELECT * FROM orders WHERE strategy_id=?",(SID,)))
        old_fills=list(self.engine.db.execute("SELECT * FROM order_fills"))
        capital=deepcopy(self.engine._get("best_capital",None))
        source=FakeSource(self.opening)
        previous_inputs=[]
        def close_states(books,signal_date):
            result={}
            for sid,book in books.items():
                equity=book["cash"]+sum(qty*100 for qty in book["positions"].values())
                result[sid]=dict(weights={code[3:]:qty*100/equity for code,qty in book["positions"].items()},
                    cash_weight=book["cash"]/equity,signal_date=signal_date,valuation_basis="SIGNAL_CLOSE")
            return result
        def load(states,now=None):
            previous_inputs.append(states[R7]["previous_requested_gross"])
            signal=source.status(now)["signal_date"]
            plan=dict(strategy_id=R7,signal_date=signal,source_date=signal,target_cash_weight=.95,
                rows=[dict(code="US.AAPL",target_weight=.05,explicit_target=True,action="TARGET")],
                previous_requested_gross=states[R7]["previous_requested_gross"],requested_gross=.5,
                strategy_state_after=dict(previous_requested_gross=.5,last_signal_date=signal))
            return {**source.status(now),"plans":{R7:plan}}
        source.close_states,source.load=close_states,load
        self.runner.source=source
        self.bind(R7)
        with patch("moomoo_component.best_broker.threading.Thread",NoWorker):
            self.runner.start()
        def partial_submit(order,client_id,**options):
            FakeBroker.submissions.append({**order,"client_id":client_id,"order_type":options.get("order_type","NORMAL")})
            sign=1 if order["side"]=="BUY" else -1
            FakeBroker.positions[order["code"]]+=sign*2
            FakeBroker.cash-=sign*2*order["limit_price"]
            FakeBroker.reconcile_result=dict(order_id="123",status="FILLED_PART",dealt_qty=2,dealt_avg_price=order["limit_price"])
            return dict(order_id="123",status="SUBMITTED")
        with patch.object(self.engine.broker,"submit",side_effect=partial_submit):
            self.tick_at(self.opening+timedelta(seconds=31))
        self.assertTrue(self.engine._pending())
        partial_plan=deepcopy(self.engine._get("best_plan",None))
        partial_request=deepcopy(self.engine._get("best_requested_strategy_state",{})[R7])
        self.runner.stop()
        source.load=lambda *args,**kwargs:(_ for _ in ()).throw(AssertionError("partial restart must reuse the original R7 request"))
        self.runner=BestBroker(self.temp.name,source,engine=self.engine,execution_window_seconds=600,allow_partial_quotes=True)
        with patch("moomoo_component.best_broker.threading.Thread",NoWorker):
            self.runner.start()
        self.tick_at(self.opening+timedelta(seconds=32))
        self.assertTrue(self.engine._pending())
        self.assertEqual(self.engine._get("best_plan",None),partial_plan)
        self.assertEqual(self.engine._get("best_requested_strategy_state",{})[R7],partial_request)
        self.assertEqual(previous_inputs,[1])
        order=FakeBroker.submissions[-1]
        remaining=order["qty"]-2
        FakeBroker.positions[order["code"]]-=remaining
        FakeBroker.cash+=remaining*order["limit_price"]
        FakeBroker.reconcile_result=dict(order_id="123",status="FILLED_ALL",dealt_qty=order["qty"],dealt_avg_price=order["limit_price"])
        self.tick_at(self.opening+timedelta(seconds=33))
        self.runner.stop()
        self.runner.reconcile()
        new_orders=list(self.engine.db.execute("SELECT side,qty FROM orders WHERE strategy_id=?",(R7,)))
        self.assertTrue(new_orders,new_orders)
        self.assertTrue(all(side=="SELL" and 0<qty<prior_qty for side,qty in new_orders),new_orders)
        self.assertGreater(FakeBroker.positions["US.AAPL"],0)
        self.assertLess(FakeBroker.positions["US.AAPL"],prior_qty)
        self.assertEqual(list(self.engine.db.execute("SELECT * FROM orders WHERE strategy_id=?",(SID,))),old_orders)
        self.assertEqual(list(self.engine.db.execute("SELECT * FROM order_fills WHERE id IN (SELECT id FROM orders WHERE strategy_id=?)",(SID,))),old_fills)
        self.assertEqual(self.engine._get("best_capital",None),capital)
        self.assertEqual(previous_inputs,[1])
        requested=self.engine._get("best_requested_strategy_state",{})[R7]
        self.assertEqual(requested["previous_requested_gross"],.5)
        self.assertEqual(requested["previous_input_gross"],1)
        frozen=deepcopy(self.engine._get("best_plan",None))
        order_count=self.engine.db.execute("SELECT count(*) FROM orders").fetchone()[0]
        source.load=lambda *args,**kwargs:(_ for _ in ()).throw(AssertionError("same signal must restore its frozen plan"))
        self.runner=BestBroker(self.temp.name,source,engine=self.engine,execution_window_seconds=600,allow_partial_quotes=True)
        with patch("moomoo_component.best_broker.threading.Thread",NoWorker):
            self.runner.start()
        self.tick_at(self.opening+timedelta(seconds=40))
        self.assertEqual(self.runner.plan,frozen["plan"])
        self.assertEqual(self.engine._get("best_plan",None),frozen)
        self.assertEqual(self.engine._get("best_requested_strategy_state",{})[R7],requested)
        self.assertEqual(self.engine.db.execute("SELECT count(*) FROM orders").fetchone()[0],order_count)

    def test_r7_sim_binding_does_not_inherit_original_auto_policy_projection(self):
        policy=original_auto_policy()
        self.engine.automatic_completion_policy_provider=lambda:policy
        self.engine._set("automatic_completion_policy",policy)
        self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)",(policy["authorized_at_utc"],"AUTOMATIC_COMPLETION_POLICY_AUTHORIZED",json.dumps(policy)));self.engine.db.commit()
        self.assertEqual(self.engine._automatic_completion_policy(self.opening,SID,execution_date="2026-09-28"),policy)
        self.bind(R7)
        self.assertIsNone(self.engine._automatic_completion_policy(self.opening,R7,execution_date="2026-09-28"))
        self.assertEqual(self.engine._get("automatic_completion_policy",None),policy)

    def test_binding_refuses_pending_or_unknown_orders_and_stale_reconciliation(self):
        self.engine.db.execute("INSERT INTO orders(id,created_at,strategy_id,mode,account_id,code,side,qty,limit_price,status) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("unknown",self.opening.isoformat(),SID,"moomoo_simulate","3604","US.AAPL","BUY",1,100,"UNKNOWN"))
        self.engine.db.commit()
        with self.assertRaisesRegex(ValueError,"RECONCILED_ORIGINAL_ACCOUNT"):
            self.bind(R7)
        self.assertEqual(self.runner.strategy_id,SID)
        self.assertEqual(self.engine.db.execute("SELECT status FROM orders WHERE id='unknown'").fetchone()[0],"UNKNOWN")


class PairedRepairContinuationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)/"applied"
        self.source,self.quotes=FiveSource(),Quotes()
        self.cohort=Cohort(root/"books",self.source,self.quotes,execution_window_seconds=600,allow_partial_quotes=True)
        FakeBroker.positions,FakeBroker.submissions={},[]
        FakeBroker.cash=1000000
        FakeBroker.submit_options,FakeBroker.reconcile_calls,FakeBroker.snapshot_calls=[],[],[]
        FakeBroker.reconcile_result,FakeBroker.before_send_error=None,None
        FakeBroker.quote_errors,FakeBroker.market_prices={},{}
        FakeBroker.prewarm_calls,FakeBroker.prewarm_error=[],None
        self.broker=BestBroker(root/"moomoo-best",self.source,
            engine=Engine(root/"moomoo-best",broker_factory=FakeBroker),execution_window_seconds=600,allow_partial_quotes=True)
        self.cohort.best_broker=self.broker
        self.addCleanup(lambda:self.cohort.close() if not self.cohort.closed else None)
        self.broker._connect()
        now=CLOSE+timedelta(minutes=10)
        metadata={**self.source.status(now),"execution_time_utc":OPEN.isoformat(),
            "execution_delay_minutes":0,"execution_window_seconds":600,"allow_partial_quotes":True}
        self.cohort.meta["active_strategy_ids"]=[SID,"HGB_FACTOR_5"]
        self.cohort.plan_metadata=deepcopy(metadata)
        states=self.source.close_states(self.cohort._books_input(),"2026-09-28")
        self.cohort.close_states=deepcopy(states)
        self.cohort.plans=deepcopy(self.source.load(states,now)["plans"])
        self.cohort._persist()
        broker_plan=dict(metadata=deepcopy(metadata),plan=deepcopy(self.cohort.plans[SID]),close_state=deepcopy(states[SID]))
        self.broker.engine._set("best_plan",broker_plan)
        control=json.loads(self.cohort.db.execute("SELECT value FROM settings WHERE key='cohort'").fetchone()[0])
        self.marker=dict(phase="COMMITTED",repair_id="synthetic-committed",signal_date="2026-09-28",
            execution_date="2026-09-29",cohort_db=str(root/"books/cohort.sqlite3"),broker_db=str(root/"moomoo-best/state.sqlite3"),
            new_hashes=dict(cohort=_pending_plan_digest(control,"cohort"),broker=_pending_plan_digest(broker_plan,"broker")))
        self.marker_raw=json.dumps(self.marker)
        for db in (self.cohort.db,self.broker.engine.db):
            db.execute("INSERT OR REPLACE INTO settings VALUES ('pending_plan_repair',?)",(self.marker_raw,));db.commit()
        self.cohort._pending_repair_guard()
        self.broker._pending_repair_guard()

    def transition(self):
        now=CLOSE+timedelta(minutes=10)
        self.cohort.migrate_strategy_membership(migration_id="five-after-repair",requested_at=now.isoformat(),
            expected_precondition_sha256=self.cohort._membership_precondition(),target_strategy_ids=list(ACTIVE_PAPER_STRATEGY_IDS),now=now)
        self.broker.bind_strategy(binding_id="r7-after-repair",requested_at=now.isoformat(),expected_strategy_id=SID,
            target_strategy_id=R7,expected_precondition_sha256=self.broker._strategy_binding_precondition(),now=now)
        self.cohort._pending_repair_guard()
        self.broker._pending_repair_guard()
        self.cohort._prepare_active_members(self.source.status(now),now)
        self.cohort._pending_repair_guard()
        self.broker._pending_repair_guard()

    def test_committed_repair_survives_five_members_and_r7_null_then_same_signal_plan(self):
        self.transition()
        self.assertEqual(self.cohort._active_ids(),ACTIVE_PAPER_STRATEGY_IDS)
        self.assertEqual(self.broker.strategy_id,R7)
        for db in (self.cohort.db,self.broker.engine.db):
            self.assertEqual(db.execute("SELECT value FROM settings WHERE key='pending_plan_repair'").fetchone()[0],self.marker_raw)
        self.assertNotIn("preserved_cohort_setting",self.cohort.state()["strategy_membership_binding"])
        self.assertEqual(self.cohort._requested_input(R7,"2026-09-28"),1)

    def test_committed_repair_allows_same_signal_r7_plan_then_strategy_rollback(self):
        self.transition()
        now=CLOSE+timedelta(minutes=15)
        self.broker.stop_event.clear()
        self.broker._prepare(now)
        self.broker.stop_event.set()
        self.assertEqual(self.broker.engine._get("best_plan",None)["plan"]["strategy_id"],R7)
        self.broker._pending_repair_guard()
        self.broker.bind_strategy(binding_id="return-diag-after-r7-plan",requested_at=now.isoformat(),expected_strategy_id=R7,
            target_strategy_id=SID,expected_precondition_sha256=self.broker._strategy_binding_precondition(),now=now)
        self.broker._pending_repair_guard()
        self.cohort._pending_repair_guard()
        self.assertEqual(self.broker.strategy_id,SID)
        self.assertEqual(self.broker.engine._get("best_capital",None)["budget"],10000)

    def test_changed_continuation_archive_does_not_bypass_old_repair_guard(self):
        self.transition()
        record=self.broker.engine._get("best_strategy_binding",None)
        record["preserved_settings"]["pending_plan_repair"]="{}"
        record["preserved_settings_sha256"]=self.broker._content_sha(record["preserved_settings"])
        self.broker.engine._set("best_strategy_binding",record)
        with self.assertRaises(DailySourceError):
            _pending_repair_commit_guard(self.marker)
