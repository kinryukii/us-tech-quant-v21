"""Single residual SIM sell regression, reusing canonical fake fixtures only.

No OpenD, network, market files, source reconstruction, or duplicated execution
implementation. Each test forbids socket construction before fixture setup.
"""
from pathlib import Path
import importlib.util
import json
import unittest
from datetime import datetime, timedelta
from copy import deepcopy
from unittest.mock import patch

from moomoo_component import core, brokers


def original_test_module(name):
    path = Path(__file__).parent / (name + ".py")
    spec = importlib.util.spec_from_file_location("_residual_fixture_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bt = original_test_module("test_best_broker")
br = original_test_module("test_brokers")


def forbid_network(case):
    guard = patch("socket.socket",
                  side_effect=AssertionError("NO_NETWORK_RESIDUAL_SELL_REGRESSION"))
    guard.start()
    case.addCleanup(guard.stop)
    import socket
    with case.assertRaisesRegex(AssertionError, "NO_NETWORK"):
        socket.socket()

class ManualResidualSellTests(unittest.TestCase):
    def setUp(self):
        forbid_network(self)
        self.case=bt.ManualCatchupRenewalTests("runTest");self.case.setUp()
        self.addCleanup(self.case.tearDown)
        self.c=self.case
        original_status=self.c.source.status
        keys={"frozen_calendar","session_hours_rules","daily/report.json","selected/package.json","selected/current_report.json","current/features.parquet"}
        refs={k:{"path":"synthetic/"+k,"sha256":"a"*64} for k in keys}
        def status(now=None):
            value=original_status(now=now);value["source_refs"]=deepcopy(refs);return value
        self.c.source.status=status
        self.c.new_permission()
        bt.FakeBroker.before_send_error=brokers.BrokerOrderNotSent("synthetic definitely not sent")
        bt.FakeBroker.before_send_error.retry_after_seconds=30
        with self.c.priced(msft=200):
            with self.assertRaises(brokers.BrokerReadError):
                self.c.tick_at(self.c.now+timedelta(seconds=1))
        self.c.runner.stop()
        self.c.renew_now=self.c.deadline+timedelta(seconds=1)
        self.renewal=self.c.renew(allowed_codes=["US.MSFT"])
        self.now=datetime.fromisoformat(self.renewal["deadline_utc"])+timedelta(seconds=1)
        bt.FakeBroker.before_send_error=None;bt.FakeBroker.quote_errors={}
        bt.FakeBroker.clock=staticmethod(lambda:self.now)
        self.c.runner._accept_snapshot(self.c.engine.broker.snapshot([],include_quotes=False))
        self.prior=self.c.engine._get("best_same_day_catchup",{})
        self.target=self.prior["deferred_sell_targets"]["US.MSFT"]
        self.old_raw={k:self.c.engine.db.execute("SELECT value FROM settings WHERE key=?",(k,)).fetchone()[0] for k in
            ("best_plan","best_same_day_catchup","best_same_day_catchup_renewal","best_execution")}
        self.args=dict(execution_date="2026-09-28",deadline_utc=(self.now+timedelta(seconds=590)).isoformat(),
            authorization_id="explicit-manual-once-1",code="US.MSFT",target_qty=self.target,max_sell_qty=17-self.target,
            limit_price=199.41,max_spread_bps=60,spread_authorization="USER_EXPLICIT_SINGLE_SELL_60BP",
            expected_prior_sha256=self.c.runner._content_sha(self.renewal),
            expected_plan_sha256=self.c.runner._content_sha(self.c.engine._get("best_plan",{})["plan"]),
            expected_execution_sha256=self.c.runner._content_sha(self.c.engine._get("best_execution",{})),
            expected_package_sha256="a"*64,now=self.now)
    def grant(self,**changes):
        return self.c.runner.authorize_manual_residual_sell(**{**self.args,**changes})
    def clock_patch(self,now=None):
        now=now or self.now
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return now if tz is None else now.astimezone(tz)
        return patch.multiple(core,datetime=Clock),patch("moomoo_component.strategy.datetime",Clock)
    def execute(self,**quote_changes):
        original=bt.FakeBroker.snapshot_partial
        original_submit=bt.FakeBroker.submit
        def snapshot(broker,codes):
            value=original(broker,codes)
            if "US.MSFT" in value["quotes"]:
                value["quotes"]["US.MSFT"].update({"price":200,"bid":199.41,"ask":200.59,**quote_changes})
            return value
        def submit(broker,order,client_id,**options):
            cap=options.pop("single_sell_spread_bps",None)
            self.assertEqual(cap,self.c.engine._get("best_manual_residual_sell",{})["max_spread_bps"])
            self.assertEqual(order["code"],"US.MSFT");self.assertEqual(order["side"],"SELL")
            self.assertEqual(options.get("order_type","NORMAL"),"NORMAL")
            return original_submit(broker,order,client_id,**options)
        a,b=self.clock_patch()
        with a,b,patch.object(bt.FakeBroker,"snapshot_partial",snapshot),patch.object(bt.FakeBroker,"submit",submit):
            return self.c.runner.execute_manual_residual_sell(self.args["authorization_id"],now=self.now)
    def test_compact_once_cas_preserves_all_old_bytes_and_no_side_effect(self):
        g=self.grant()
        self.assertLess(len(json.dumps(g).encode()),3000)
        self.assertEqual(self.grant(),g)
        self.assertEqual(bt.FakeBroker.submissions,[])
        for k,v in self.old_raw.items():self.assertEqual(self.c.engine.db.execute("SELECT value FROM settings WHERE key=?",(k,)).fetchone()[0],v)
        with self.assertRaisesRegex(ValueError,"ALREADY_AUTHORIZED"):self.grant(authorization_id="another-once-permit")
        self.assertEqual(self.c.engine.limits["max_spread_bps"],50)
    def test_explicit_60_normal_sell_only_original_target_and_repeat_zero(self):
        self.grant()
        result=self.execute()
        self.assertEqual(len(result["submitted"]),1)
        self.assertEqual([(r["code"],r["side"],r["qty"],r["limit_price"],r["order_type"]) for r in bt.FakeBroker.submissions],
            [("US.MSFT","SELL",17-self.target,199.41,"NORMAL")])
        self.assertEqual(bt.FakeBroker.positions["US.MSFT"],self.target)
        self.assertEqual(self.execute()["status"],"ORDER_ALREADY_CREATED")
        self.assertEqual(len(bt.FakeBroker.submissions),1)
        self.assertEqual(self.c.engine.limits["max_spread_bps"],50)
    def test_bid_improvement_uses_fresh_bid_above_authorized_floor(self):
        self.grant()
        result=self.execute(bid=199.49)
        self.assertEqual(len(result["submitted"]),1)
        self.assertEqual(bt.FakeBroker.submissions[0]["limit_price"],199.49)
        self.assertGreater(bt.FakeBroker.submissions[0]["limit_price"],self.args["limit_price"])
    def test_submitted_sell_is_never_automatically_repriced(self):
        self.grant();self.execute()
        before=deepcopy(bt.FakeBroker.submissions)
        self.c.runner._maybe_reprice_pending(self.now)
        self.assertEqual(bt.FakeBroker.submissions,before)
        self.assertEqual(self.c.engine._get("best_order_reprices",{}),{})
    def test_forced_market_is_rejected_before_any_durable_intent(self):
        self.grant();before=self.c.engine.db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        original=self.c.engine.step
        def forbidden(**options):return original(**{**options,"broker_order_type":"MARKET"})
        with patch.object(self.c.engine,"step",forbidden):
            with self.assertRaisesRegex(ValueError,"NORMAL_ONLY"):self.execute()
        self.assertEqual(bt.FakeBroker.submissions,[])
        self.assertEqual(self.c.engine.db.execute("SELECT COUNT(*) FROM orders").fetchone()[0],before)
        self.assertFalse(self.c.engine.halt_event.is_set())
    def test_original_50_rejects_same_59bps_quote(self):
        self.grant(max_spread_bps=50,spread_authorization="ORIGINAL_50BP")
        result=self.execute()
        self.assertEqual(result["submitted"],[]);self.assertEqual(bt.FakeBroker.submissions,[])
    def test_cancel_blocks_with_zero_submission(self):
        self.grant()
        self.c.runner.cancel_manual_residual_sell(self.args["authorization_id"],now=self.now)
        with self.assertRaisesRegex(ValueError,"PERMISSION_CHANGED_OR_EXPIRED"):self.execute()
        self.assertEqual(bt.FakeBroker.submissions,[])
    def test_fixed_minimum_limit_blocks_fresh_bid_drop(self):
        self.grant()
        result=self.execute(bid=199.40)
        self.assertEqual(result["submitted"],[]);self.assertEqual(bt.FakeBroker.submissions,[])
    def test_wide_over_60_blocks(self):
        self.grant()
        result=self.execute(ask=200.70)
        self.assertEqual(result["submitted"],[]);self.assertEqual(bt.FakeBroker.submissions,[])
    def test_target_increase_or_sell_quantity_mismatch_rejected(self):
        for change in ({"target_qty":self.target+1},{"max_sell_qty":self.args["max_sell_qty"]+1},{"code":"US.AAPL"},
                {"max_spread_bps":61},{"spread_authorization":"ORIGINAL_50BP"},{"expected_prior_sha256":"b"*64},
                {"deadline_utc":(self.now+timedelta(seconds=601)).isoformat()}):
            with self.subTest(change=change),self.assertRaises(ValueError):self.grant(**change)
        self.assertEqual(bt.FakeBroker.submissions,[])
    def test_source_change_blocks_before_ledger_write(self):
        self.c.source.status=lambda now=None:{"source_refs":{}}
        with self.assertRaisesRegex(ValueError,"SOURCE_CHANGED"):self.grant()
        self.assertIsNone(self.c.engine._get("best_manual_residual_sell",None))
    def test_expiry_blocks(self):
        self.grant();self.now=self.now+timedelta(seconds=590)
        with self.assertRaisesRegex(ValueError,"PERMISSION_CHANGED_OR_EXPIRED"):self.execute()
        self.assertEqual(bt.FakeBroker.submissions,[])
    def test_immutable_slot_or_execution_tamper_blocks(self):
        self.grant();state=self.c.engine._get("best_execution",{});state["target_quantities"]["US.MSFT"]=self.target+1
        self.c.engine._set("best_execution",state)
        with self.assertRaisesRegex(ValueError,"PERMISSION_CHANGED_OR_EXPIRED"):self.execute()
        self.assertEqual(bt.FakeBroker.submissions,[])
    def test_max_quantity_prevents_external_holdings_increase(self):
        self.grant();bt.FakeBroker.positions["US.MSFT"]=18
        with self.assertRaisesRegex(ValueError,"FIXED_TARGET_OR_MAX_QUANTITY_CHANGED"):self.execute()
        self.assertEqual(bt.FakeBroker.submissions,[])
    def test_below_target_never_buys(self):
        self.grant();bt.FakeBroker.positions["US.MSFT"]=max(0,self.target-1)
        with self.assertRaisesRegex(ValueError,"FIXED_TARGET_OR_MAX_QUANTITY_CHANGED"):self.execute()
        self.assertEqual(bt.FakeBroker.submissions,[])
    def reconcile_at(self, now):
        a,b=self.clock_patch(now)
        with a,b,patch.object(self.c.runner,"_now",return_value=now):
            return self.c.runner.reconcile()
    def test_real_full_fill_after_expiry_completes_original_bookkeeping_without_resend(self):
        # Represent an original book whose other target was already processed.
        state=self.c.engine._get("best_execution",{})
        buy=state if state["phase"]=="BUY" else state["resume_buy_state"]
        buy["processed_codes"]=sorted(set(buy.get("processed_codes",[]))|{"US.AAPL"})
        buy["skipped"]=[r for r in buy.get("skipped",[]) if r.get("code")!="US.AAPL"]
        self.c.engine._set("best_execution",state)
        self.args["expected_execution_sha256"]=self.c.runner._content_sha(state)
        grant=self.grant();self.execute()
        self.now=datetime.fromisoformat(grant["deadline_utc"])+timedelta(seconds=1)
        before=deepcopy(bt.FakeBroker.submissions)
        self.reconcile_at(self.now)
        status=self.c.engine._get("best_manual_residual_sell_state:"+grant["authorization_id"],{})
        state=self.c.engine._get("best_execution",{})
        self.assertEqual(status["status"],"COMPLETED")
        self.assertEqual(status["actual_target_qty"],self.target)
        self.assertEqual(status["fill_qty"],17-self.target)
        self.assertIn("US.MSFT",state["processed_codes"])
        self.assertFalse(any(r.get("code")=="US.MSFT" for r in state.get("deferred_sells",[])+state.get("skipped",[])))
        self.assertEqual(state["phase"],"DONE")
        self.assertEqual(state["completion_status"],"EXECUTED")
        for k in ("best_plan","best_same_day_catchup","best_same_day_catchup_renewal"):
            self.assertEqual(self.c.engine.db.execute("SELECT value FROM settings WHERE key=?",(k,)).fetchone()[0],self.old_raw[k])
        self.assertEqual(self.c.engine._get("best_manual_residual_sell",{}),grant)
        self.reconcile_at(self.now+timedelta(seconds=1))
        self.assertEqual(self.execute()["status"],"ORDER_ALREADY_CREATED")
        self.c.runner._tick_partial(self.now)
        self.assertEqual(self.c.runner.status,"EXECUTED")
        self.assertEqual(bt.FakeBroker.submissions,before)
    def test_pending_partial_or_missing_real_fill_cannot_fake_completion(self):
        grant=self.grant();self.execute()
        self.now=datetime.fromisoformat(grant["deadline_utc"])+timedelta(seconds=1)
        for response,held in ((dict(status="SUBMITTED",dealt_qty=0),17),
                (dict(status="FILLED_PART",dealt_qty=1,dealt_avg_price=199.41),16),
                (dict(status="FILLED_ALL",dealt_qty=None),self.target)):
            with self.subTest(status=response["status"]):
                bt.FakeBroker.reconcile_result=response
                bt.FakeBroker.positions["US.MSFT"]=held
                if response["status"]=="FILLED_ALL":
                    self.c.engine.db.execute("DELETE FROM order_fills")
                    self.c.engine.db.commit()
                if response["status"]=="FILLED_ALL":
                    # Original account/fill identity guard must reject unexplained holdings.
                    with self.assertRaisesRegex(ValueError,"持仓与本策略已核对成交数量不一致"):
                        self.reconcile_at(self.now)
                else:
                    self.reconcile_at(self.now)
                self.assertNotEqual(self.c.engine._get("best_manual_residual_sell_state:"+grant["authorization_id"],{}).get("status"),"COMPLETED")
                self.assertNotIn("US.MSFT",self.c.engine._get("best_execution",{}).get("processed_codes",[]))
        self.assertEqual(len(bt.FakeBroker.submissions),1)
    def test_completion_retains_other_unresolved_progress(self):
        state=self.c.engine._get("best_execution",{})
        state.setdefault("skipped",[]).append(dict(code="US.GOOG",reason="synthetic other unresolved"))
        self.c.engine._set("best_execution",state)
        self.args["expected_execution_sha256"]=self.c.runner._content_sha(state)
        grant=self.grant();self.execute()
        self.now=datetime.fromisoformat(grant["deadline_utc"])+timedelta(seconds=1)
        self.reconcile_at(self.now)
        status=self.c.engine._get("best_manual_residual_sell_state:"+grant["authorization_id"],{})
        state=self.c.engine._get("best_execution",{})
        self.assertEqual(status["status"],"COMPLETED")
        self.assertFalse(status["execution_complete"])
        self.assertEqual(state["phase"],"SELL")
        self.assertIn("US.MSFT",state["processed_codes"])
        self.assertIn("US.MSFT",state["resume_buy_state"]["processed_codes"])
        self.assertTrue(any(r.get("code")=="US.GOOG" for r in state["skipped"]))
        self.assertFalse(any(r.get("code")=="US.MSFT" for r in state.get("skipped",[])+state.get("deferred_sells",[])))
        self.assertEqual(self.execute()["status"],"ORDER_ALREADY_CREATED")
        self.assertEqual(len(bt.FakeBroker.submissions),1)


class CompletionExitBookkeepingTests(unittest.TestCase):
    """Replays signed synthetic bookkeeping inputs; original tests cover issuing."""
    setUp=ManualResidualSellTests.setUp
    grant=ManualResidualSellTests.grant
    execute=ManualResidualSellTests.execute
    clock_patch=ManualResidualSellTests.clock_patch
    def reconcile_at(self, now):
        # Isolate the bookkeeping helper with original native receipt/snapshot
        # APIs; synthetic added EXIT is not a second full catchup authority.
        a,b=self.clock_patch(now)
        with a,b,patch.object(self.c.runner,"_now",return_value=now):
            self.c.engine.reconcile()
            snapshot=self.c.engine.broker.snapshot([],include_quotes=False)
            self.c.runner._accept_snapshot(snapshot)
            return self.c.runner._reconcile_manual_residual_sell(snapshot)

    def exit_book(self, *, weight=0, native=True, held=0, target=0, outside_session=False):
        grant=self.grant()
        saved=self.c.engine._get("best_plan",{})
        saved["plan"]["rows"].append(dict(code="US.EXIT",target_weight=weight))
        saved["plan"]["target_cash_weight"]-=weight
        self.c.engine._set("best_plan",saved)
        state=deepcopy(self.c.engine._get("best_execution",{})["resume_buy_state"])
        state["target_quantities"]["US.EXIT"]=target
        state["processed_codes"]=["US.AAPL"]
        state["skipped"]=[r for r in state.get("skipped",[]) if r.get("code")!="US.AAPL"]
        self.c.engine._set("best_execution",state)
        # Seal fake authority before the operation. No production grant is mutated.
        grant=deepcopy(grant)
        grant["expected_plan_sha256"]=self.c.runner._content_sha(saved["plan"])
        grant["expected_execution_sha256"]=self.c.runner._content_sha(state)
        raw=json.dumps(grant)
        for key in ("best_manual_residual_sell","best_manual_residual_sell:"+grant["signal_date"]):
            self.c.engine._set(key,grant)
        self.c.engine.db.execute("UPDATE audit SET detail=? WHERE event=? AND time=?",
            (raw,"BEST_MANUAL_RESIDUAL_SELL_AUTHORIZED",grant["authorized_at_utc"]))
        old=(self.c.opening-timedelta(days=3)).isoformat()
        new=(self.c.opening+timedelta(days=1) if outside_session else self.c.opening+timedelta(seconds=1)).isoformat()
        for oid,stamp,side in (("old-exit",old,"BUY"),("original-exit",new,"SELL")):
            self.c.engine.db.execute("INSERT INTO orders(id,created_at,strategy_id,mode,account_id,code,side,qty,"
                "limit_price,status,order_id,order_type) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (oid,stamp,"HGB_DIAG_5","moomoo_simulate","3604","US.EXIT",side,1,100,"FILLED_ALL",oid,"MARKET"))
            payload=dict(fill_qty=1 if side=="BUY" else 1-held,fill_price=100,filled_at=stamp,
                fill_source="MOOMOO_SIMULATE_ORDER_RECONCILE" if native or side=="BUY" else "UNVERIFIED")
            self.c.engine.db.execute("INSERT INTO order_fills VALUES(?,?)",(oid,json.dumps(payload)))
        self.c.engine.db.commit()
        if held:bt.FakeBroker.positions["US.EXIT"]=held
        self.original_grant=deepcopy(grant)
        self.old_permission_bytes={k:self.c.engine.db.execute("SELECT value FROM settings WHERE key=?",(k,)).fetchone()[0]
            for k in ("best_manual_residual_sell","best_manual_residual_sell:"+grant["signal_date"],
                      "best_same_day_catchup","best_same_day_catchup_renewal")}
        return grant
    def finish(self,grant):
        self.execute()
        self.now=datetime.fromisoformat(grant["deadline_utc"])+timedelta(seconds=1)
        return self.reconcile_at(self.now)
    def unchanged_grants(self):
        for k,raw in self.old_permission_bytes.items():
            self.assertEqual(self.c.engine.db.execute("SELECT value FROM settings WHERE key=?",(k,)).fetchone()[0],raw)
    def test_sell_exit_full_native_fill_can_finish_without_buy_processed(self):
        grant=self.exit_book();self.finish(grant)
        state=self.c.engine._get("best_execution",{})
        receipt=self.c.engine._get("best_manual_residual_sell_state:"+grant["authorization_id"],{})
        self.assertEqual(state["phase"],"DONE");self.assertEqual(state["completion_status"],"EXECUTED")
        self.assertNotIn("US.EXIT",state["processed_codes"])
        self.assertEqual(receipt["sell_exit_codes"],["US.EXIT"])
        self.assertTrue(receipt["execution_complete"])
        self.assertEqual(len(bt.FakeBroker.submissions),1);self.unchanged_grants()
    def test_missing_native_fill_remaining_holding_or_positive_weight_cannot_finish(self):
        for args in (dict(native=False),dict(held=1),dict(weight=.01),dict(target=1),dict(outside_session=True)):
            with self.subTest(args=args):
                case=CompletionExitBookkeepingTests("runTest");case.setUp()
                try:
                    grant=case.exit_book(**args);case.finish(grant)
                    receipt=case.c.engine._get("best_manual_residual_sell_state:"+grant["authorization_id"],{})
                    self.assertEqual(receipt["status"],"COMPLETED")
                    self.assertFalse(receipt["execution_complete"])
                    self.assertEqual(case.c.engine._get("best_execution",{})["phase"],"BUY")
                    case.unchanged_grants()
                finally:case.doCleanups()
    def make_legacy_false(self):
        grant=self.exit_book(native=False);self.finish(grant)
        receipt=self.c.engine._get("best_manual_residual_sell_state:"+grant["authorization_id"],{})
        self.assertFalse(receipt["execution_complete"])
        old_audit=self.c.engine.db.execute("SELECT detail FROM audit WHERE event=? AND time=?",
            ("BEST_MANUAL_RESIDUAL_SELL_RECONCILED",receipt["reconciled_at_utc"])).fetchone()[0]
        payload=json.loads(self.c.engine.db.execute("SELECT payload FROM order_fills WHERE id='original-exit'").fetchone()[0])
        payload["fill_source"]="MOOMOO_SIMULATE_ORDER_RECONCILE"
        self.c.engine.db.execute("UPDATE order_fills SET payload=? WHERE id='original-exit'",(json.dumps(payload),))
        self.c.engine.db.commit()
        return grant,receipt,old_audit
    def test_completed_false_refines_only_from_exact_signed_preimage_no_new_send(self):
        grant,receipt,old_audit=self.make_legacy_false()
        before=deepcopy(bt.FakeBroker.submissions)
        self.reconcile_at(self.now+timedelta(seconds=1))
        refined=self.c.engine._get("best_manual_residual_sell_state:"+grant["authorization_id"],{})
        self.assertTrue(refined["execution_complete"])
        self.assertEqual(self.c.engine._get("best_execution",{})["phase"],"DONE")
        self.assertEqual(self.c.engine.db.execute("SELECT detail FROM audit WHERE event=? AND time=?",
            ("BEST_MANUAL_RESIDUAL_SELL_RECONCILED",receipt["reconciled_at_utc"])).fetchone()[0],old_audit)
        self.reconcile_at(self.now+timedelta(seconds=2))
        self.assertEqual(self.execute()["status"],"ORDER_ALREADY_CREATED")
        self.assertEqual(bt.FakeBroker.submissions,before);self.unchanged_grants()
    def test_refinement_rejects_bad_audit_or_unrecoverable_original_cas_and_cannot_send(self):
        grant,receipt,old_audit=self.make_legacy_false()
        before=deepcopy(bt.FakeBroker.submissions)
        for fault in ("audit","quantity"):
            self.c.engine.db.execute("SAVEPOINT refinement_fault")
            try:
                if fault=="audit":
                    self.c.engine.db.execute("DELETE FROM audit WHERE event='BEST_MANUAL_RESIDUAL_SELL_RECONCILED'")
                else:
                    state=self.c.engine._get("best_execution",{});state["target_quantities"]["US.AAPL"]+=1
                    self.c.engine.db.execute("UPDATE settings SET value=? WHERE key='best_execution'",(json.dumps(state),))
                snapshot=self.c.engine.broker.snapshot([],include_quotes=False)
                self.assertFalse(self.c.runner._reconcile_manual_residual_sell(snapshot))
                self.assertFalse(self.c.engine._get("best_manual_residual_sell_state:"+grant["authorization_id"],{})["execution_complete"])
            finally:
                self.c.engine.db.execute("ROLLBACK TO refinement_fault");self.c.engine.db.execute("RELEASE refinement_fault")
        with self.assertRaisesRegex(ValueError,"ACCOUNTING_ONLY"):
            self.c.engine._manual_residual_sell_permission(self.c.engine._manifest(),self.now,
                completion_execution_state={})
        self.assertEqual(bt.FakeBroker.submissions,before);self.unchanged_grants()

class FinalBrokerPreflightTests(unittest.TestCase):
    def setUp(self):
        forbid_network(self)

    def make(self,*,bid=1.69,ask=1.70,age=0):
        sdk=br.FakeSDK();sdk.positions=[{"code":"US.AAPL","qty":595,"can_sell_qty":595,"position_side":"LONG","currency":"USD","market_val":1008.525}]
        sdk.quotes["US.AAPL"].update(last_price=1.695,bid_price=bid,ask_price=ask,
            update_time=(br.NOW-timedelta(seconds=age)).astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).replace(tzinfo=None).isoformat(" "))
        broker=brokers.MoomooBroker(account_id="222",sdk=sdk,now=lambda:br.NOW)
        self.addCleanup(broker.close)
        return sdk,broker
    def send(self,sdk,broker,**opts):
        return broker.submit({"code":"US.AAPL","side":"SELL","qty":579,"limit_price":1.69},"only-authorized-once",
            allow_partial_quotes=True,execution_deadline_utc=(br.NOW+timedelta(seconds=600)).isoformat(),order_type="NORMAL",**opts)
    def test_final_explicit_60_allows_real_fake_sdk_59bps_normal_sell(self):
        sdk,broker=self.make();self.send(sdk,broker,single_sell_spread_bps=60)
        sends=[kw for name,kw in sdk.calls if name=="place_order"]
        self.assertEqual(len(sends),1)
        self.assertEqual((sends[0]["trd_side"],sends[0]["order_type"],sends[0]["qty"],sends[0]["price"]),("SELL","NORMAL",579,1.69))
    def test_final_default_50_blocks_without_exception(self):
        sdk,broker=self.make()
        with self.assertRaises(brokers.BrokerError):self.send(sdk,broker)
        self.assertFalse(any(n=="place_order" for n,_ in sdk.calls))
    def test_final60_does_not_allow_over60_or_stale_or_bid_below_limit(self):
        for args in ({"ask":1.71},{"age":31},{"bid":1.68,"ask":1.689}):
            with self.subTest(args=args):
                sdk,broker=self.make(**args)
                with self.assertRaises(brokers.BrokerError):self.send(sdk,broker,single_sell_spread_bps=60)
                self.assertFalse(any(n=="place_order" for n,_ in sdk.calls))
    def test_final_bid_improvement_or_decline_blocks_old_limit(self):
        for bid,ask in ((1.70,1.71),(1.68,1.689)):
            with self.subTest(bid=bid):
                sdk,broker=self.make(bid=bid,ask=ask)
                with self.assertRaises(brokers.BrokerError):self.send(sdk,broker,single_sell_spread_bps=60)
                self.assertFalse(any(n=="place_order" for n,_ in sdk.calls))
    def test_final60_keeps_original_two_percent_price_deviation_guard(self):
        sdk,broker=self.make();sdk.quotes["US.AAPL"]["last_price"]=1.50
        with self.assertRaises(brokers.BrokerError):self.send(sdk,broker,single_sell_spread_bps=60)
        self.assertFalse(any(n=="place_order" for n,_ in sdk.calls))
    def test_final60_forbidden_market_or_buy(self):
        for side,kind in (("BUY","NORMAL"),("SELL","MARKET")):
            with self.subTest(side=side,kind=kind):
                sdk,broker=self.make()
                with self.assertRaises(brokers.BrokerError):
                    broker.submit({"code":"US.AAPL","side":side,"qty":579,"limit_price":1.69},"forbidden",
                        allow_partial_quotes=True,execution_deadline_utc=(br.NOW+timedelta(seconds=600)).isoformat(),
                        order_type=kind,single_sell_spread_bps=60)
                self.assertFalse(any(n=="place_order" for n,_ in sdk.calls))


class AutomaticCompletionBrokerTests(unittest.TestCase):
    """Only the canonical fake account/SDK; socket disabled before setup."""
    def setUp(self):
        forbid_network(self)
        self.case=bt.BestBrokerTests("runTest");self.case.setUp()
        self.addCleanup(self.case.tearDown)
        self.c=self.case;self.c.partial_runner(delay=0)
        self.p=dict(schema_version=1,enabled=True,policy_id="DAILY_AUTO_COMPLETION_V1",
            reason="USER_EXPLICIT_DAILY_AUTO_COMPLETION",
            authorized_at_utc=(self.c.opening-timedelta(days=3,hours=2)).isoformat(),
            effective_execution_date="2026-09-26",evaluation_end_exclusive="2027-01-01",
            priority_window_seconds=600,close_buffer_seconds=600,one_tick_spread=True,
            normal_spread_bps=50,max_single_tick_spread_bps=200,quote_max_age_seconds=30,
            price_deviation_fraction=.02,active_strategy_ids=["HGB_DIAG_5","HGB_FACTOR_5"],
            broker_account_id="3604",broker_budget=10000)
        self.c.engine.automatic_completion_policy_provider=lambda:self.p
        self.c.engine._set("automatic_completion_policy",self.p)
        self.c.engine.db.execute("INSERT INTO audit VALUES(?,?,?)",
            (self.p["authorized_at_utc"],"AUTOMATIC_COMPLETION_POLICY_AUTHORIZED",json.dumps(self.p)))
        self.c.engine.db.commit()
        original=bt.FakeBroker.submit
        def submit(broker,order,client_id,*,allow_single_tick_spread=False,**kwargs):
            self.assertIs(type(allow_single_tick_spread),bool)
            result=original(broker,order,client_id,**kwargs)
            bt.FakeBroker.submit_options[-1]["allow_single_tick_spread"]=allow_single_tick_spread
            return result
        patcher=patch.object(bt.FakeBroker,"submit",submit);patcher.start();self.addCleanup(patcher.stop)
    def tick(self,seconds):
        now=self.c.opening+timedelta(seconds=seconds)
        self.c.tick_at(now);return now
    def seed_holding(self,qty=20):
        stamp=(self.c.opening-timedelta(days=3)).isoformat()
        self.c.engine.db.execute("INSERT INTO orders(id,created_at,strategy_id,mode,account_id,code,side,qty,limit_price,status,order_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",("old-holding",stamp,"HGB_DIAG_5","moomoo_simulate","3604","US.AAPL","BUY",qty,100,"FILLED_ALL","old-broker"))
        self.c.engine.db.execute("INSERT INTO order_fills VALUES(?,?)",
            ("old-holding",json.dumps(dict(fill_qty=qty,fill_price=100,filled_at=stamp,
                fill_source="MOOMOO_SIMULATE_ORDER_RECONCILE"))))
        self.c.engine.db.commit()
        bt.FakeBroker.positions={"US.AAPL":qty};bt.FakeBroker.cash=1000000-qty*100
        self.c.runner._accept_snapshot(self.c.engine.broker.snapshot([],include_quotes=False))
    def test_future_preparation_seals_close_minus_ten_and_no_early_send(self):
        self.tick(-10)
        self.assertEqual(bt.FakeBroker.submissions,[])
        end=self.c.runner._execution_end()
        self.assertEqual(end,self.c.opening+timedelta(hours=6,minutes=20))
        self.assertEqual(self.c.runner.execution_window_seconds,600)
        self.tick(1)
        state=self.c.engine._get("best_execution",{})
        self.assertEqual(state["manifest"]["expires_at"],end.isoformat())
        self.assertEqual(json.loads(state["manifest"]["source"])["automatic_completion_policy_sha256"],
            self.c.runner._content_sha(self.p))
    def test_stale_open_retries_after_priority_without_new_plan_or_duplicate(self):
        bt.FakeBroker.quote_errors={"US.AAPL":"stale vendor"}
        self.tick(1);saved=deepcopy(self.c.engine._get("best_plan",{}))
        bt.FakeBroker.quote_errors={}
        self.tick(601);self.tick(602);self.tick(603);self.tick(604)
        self.assertTrue(bt.FakeBroker.submissions)
        self.assertEqual(self.c.engine._get("best_plan",{}),saved)
        self.assertEqual(len(bt.FakeBroker.submissions),1)
        self.assertEqual(self.c.engine._get("best_execution",{})["phase"],"DONE")
        self.assertTrue(bt.FakeBroker.submit_options[-1]["allow_single_tick_spread"])
    def test_cutoff_and_later_day_cannot_send_old_signal(self):
        bt.FakeBroker.quote_errors={"US.AAPL":"stale"};self.tick(1)
        bt.FakeBroker.quote_errors={}
        self.tick(6*3600+20*60)
        self.assertEqual(bt.FakeBroker.submissions,[])
        self.c.runner.prepared_at=0
        self.c.tick_at(self.c.opening+timedelta(days=1,hours=1))
        self.assertEqual(bt.FakeBroker.submissions,[])
    def test_final_policy_projection_or_callback_drift_blocks_zero_send(self):
        bt.FakeBroker.quote_errors={"US.AAPL":"stale"};self.tick(1)
        bt.FakeBroker.quote_errors={}
        wrong=deepcopy(self.p);wrong["policy_id"]="ANOTHER_POLICY_01"
        self.c.engine._set("automatic_completion_policy",wrong)
        with self.assertRaisesRegex(ValueError,"PROJECTION_CHANGED"):self.tick(601)
        self.assertEqual(bt.FakeBroker.submissions,[])
    def test_native_cancelled_part_sell_retries_only_actual_remaining_no_reverse_buy(self):
        self.seed_holding(20)
        bt.FakeBroker.reconcile_result=dict(status="CANCELLED_PART",order_id="123",dealt_qty=4,dealt_avg_price=100)
        self.tick(1)
        first=deepcopy(bt.FakeBroker.submissions[0]);target=20-first["qty"]
        # The fake fills immediately; restore the independently observed partial holding.
        bt.FakeBroker.positions["US.AAPL"]=16
        bt.FakeBroker.cash=998400
        self.tick(2)
        state=self.c.engine._get("best_execution",{})
        self.assertEqual(state["target_quantities"]["US.AAPL"],target)
        self.assertEqual(state["resolved_sell_targets"]["US.AAPL"],target)
        self.assertEqual(len(bt.FakeBroker.submissions),1)
        bt.FakeBroker.reconcile_result=None
        self.tick(34);self.tick(35);self.tick(36);self.tick(37)
        self.assertEqual([o["side"] for o in bt.FakeBroker.submissions],["SELL","SELL"])
        self.assertEqual(bt.FakeBroker.submissions[1]["qty"],16-target)
        self.assertEqual(bt.FakeBroker.positions["US.AAPL"],target)
        self.assertEqual(self.c.engine._get("best_execution",{})["phase"],"DONE")
    def test_native_failed_zero_fill_is_saved_and_sell_retry_requires_native_evidence(self):
        self.seed_holding(20)
        bt.FakeBroker.reconcile_result=dict(status="FAILED",order_id="123",dealt_qty=0,dealt_avg_price=None)
        self.tick(1);bt.FakeBroker.positions["US.AAPL"]=20;bt.FakeBroker.cash=998000
        self.tick(2)
        row=self.c.engine.state()["orders"][0]
        self.assertEqual(row["fill_qty"],0);self.assertEqual(row["fill_source"],"MOOMOO_SIMULATE_ORDER_RECONCILE")
        self.c.engine.db.execute("DELETE FROM order_fills WHERE id=?",(row["id"],));self.c.engine.db.commit()
        self.tick(34)
        self.assertEqual(len(bt.FakeBroker.submissions),1)
        self.assertNotEqual(self.c.engine._get("best_execution",{})["phase"],"DONE")
    def test_native_terminal_sell_cannot_sell_external_increase(self):
        self.seed_holding(20)
        bt.FakeBroker.reconcile_result=dict(status="CANCELLED_PART",order_id="123",dealt_qty=4,dealt_avg_price=100)
        self.tick(1);bt.FakeBroker.positions["US.AAPL"]=30;bt.FakeBroker.cash=997000
        with self.assertRaisesRegex(ValueError,"持仓"):
            self.tick(2)
        self.assertEqual(len(bt.FakeBroker.submissions),1)

    def test_confirmed_native_failure_retries_beyond_old_cap_for_buy_and_sell(self):
        for side in ("BUY","SELL"):
            with self.subTest(side=side):
                case=AutomaticCompletionBrokerTests("runTest");case.setUp()
                try:
                    if side=="SELL":case.seed_holding(20)
                    bt.FakeBroker.reconcile_result=dict(status="FAILED",order_id="123",dealt_qty=0,dealt_avg_price=None)
                    case.tick(601)
                    original_target=case.c.engine._get("best_execution",{})["target_quantities"]["US.AAPL"]
                    for i in range(8):
                        bt.FakeBroker.positions={"US.AAPL":20} if side=="SELL" else {}
                        bt.FakeBroker.cash=998000 if side=="SELL" else 1000000
                        case.tick(602+i*31)
                        if i<7:case.tick(632+i*31)
                    self.assertEqual(len(bt.FakeBroker.submissions),8)
                    self.assertTrue(all(o["side"]==side for o in bt.FakeBroker.submissions))
                    self.assertEqual(case.c.engine._get("best_execution",{})["target_quantities"]["US.AAPL"],original_target)
                    self.assertNotEqual(case.c.engine._get("best_execution",{})["phase"],"DONE")
                finally:case.doCleanups()

    def test_z_session_bounds_include_first_fractional_second_native_order(self):
        original=self.c.source.status
        def zstatus(now=None):
            value=original(now=now)
            for key in ("next_open_utc","next_close_utc"):
                value[key]=value[key].replace("+00:00","Z")
            return value
        self.c.source.status=zstatus
        self.seed_holding(20)
        bt.FakeBroker.reconcile_result=dict(status="CANCELLED_PART",order_id="123",dealt_qty=4,dealt_avg_price=100)
        self.tick(.001);target=self.c.engine._get("best_execution",{})["target_quantities"]["US.AAPL"]
        bt.FakeBroker.positions["US.AAPL"]=16;bt.FakeBroker.cash=998400
        self.tick(.2)
        meta=self.c.engine._get("best_plan",{})["metadata"]
        self.assertTrue(meta["next_open_utc"].endswith("Z"))
        self.assertEqual(self.c.engine._terminal_retry_remaining("US.AAPL","SELL",
            meta["next_open_utc"],meta["next_close_utc"],"HGB_DIAG_5"),16-target)
        bt.FakeBroker.reconcile_result=None
        self.tick(31.3);self.tick(32.3);self.tick(33.3)
        self.assertEqual([o["side"] for o in bt.FakeBroker.submissions],["SELL","SELL"])
        self.assertEqual(bt.FakeBroker.submissions[1]["qty"],16-target)
    def test_native_gen0_failed_then_gen1_confirmed_unsent_can_retry_same_id(self):
        self.seed_holding(20)
        bt.FakeBroker.reconcile_result=dict(status="FAILED",order_id="123",dealt_qty=0,dealt_avg_price=None)
        self.tick(1);bt.FakeBroker.positions["US.AAPL"]=20;bt.FakeBroker.cash=998000
        self.tick(2)
        error=brokers.BrokerOrderNotSent("synthetic final preflight");error.retry_after_seconds=30
        bt.FakeBroker.before_send_error=error
        with self.assertRaises(brokers.BrokerReadError):self.tick(34)
        unsent=self.c.engine.db.execute("SELECT id FROM orders WHERE status='CANCELLED_BEFORE_SEND'").fetchone()[0]
        self.assertEqual(len(bt.FakeBroker.submissions),1)
        bt.FakeBroker.before_send_error=None;bt.FakeBroker.reconcile_result=None
        self.tick(66);self.tick(67);self.tick(68)
        self.assertEqual(len(bt.FakeBroker.submissions),2)
        self.assertEqual(bt.FakeBroker.submissions[1]["client_id"],unsent)
        self.assertEqual(self.c.engine._get("best_execution",{})["phase"],"DONE")
    def test_state_rule_summary_contains_no_plain_account_identifier(self):
        self.tick(-1)
        result=self.c.runner.state()
        self.assertNotIn("broker_account_id",result["automatic_completion_policy"])
        self.assertEqual(result["automatic_completion_policy"]["close_buffer_seconds"],600)
        self.assertIsNone(result["reprice_policy"]["max_terminal_retries_per_code"])
        self.assertEqual(result["reprice_policy"]["terminal_retry_policy"],"UNTIL_SESSION_CUTOFF")
        self.assertEqual(result["reprice_policy"]["daily_order_limit"],100)

    def test_friday_prepares_monday_but_future_intent_cannot_send_friday(self):
        friday=self.c.opening-timedelta(days=3)+timedelta(hours=8)
        self.c.runner._prepare(friday)
        self.assertIsNotNone(self.c.runner._automatic_completion(friday))
        self.assertEqual(bt.FakeBroker.submissions,[])
        self.assertEqual(self.c.runner._automatic_completion(friday)[1],
            self.c.opening+timedelta(hours=6,minutes=20))

    def test_unknown_order_never_retried(self):
        self.seed_holding(20)
        bt.FakeBroker.reconcile_result=dict(status="UNKNOWN",order_id="123",dealt_qty=0,dealt_avg_price=None)
        self.tick(1)
        with self.assertRaisesRegex(ValueError,"未知"):self.tick(2)
        self.assertEqual(len(bt.FakeBroker.submissions),1)
        self.assertTrue(self.c.engine.halt_event.is_set())
    def test_standing_one_tick_reaches_both_preview_and_original_partial_target_gate(self):
        original=bt.FakeBroker.snapshot_partial
        def snapshot(broker,codes):
            result=original(broker,codes)
            for q in result["quotes"].values():
                q.update(price=1.695,bid=1.69,ask=1.70,price_tick=.01)
            return result
        with patch.object(bt.FakeBroker,"snapshot_partial",snapshot):
            self.tick(1)
        self.assertEqual(len(bt.FakeBroker.submissions),1)
        self.assertTrue(bt.FakeBroker.submit_options[0]["allow_single_tick_spread"])
    def test_quote_rpc_crossing_cutoff_never_sends(self):
        before=self.c.opening+timedelta(hours=6,minutes=19,seconds=59)
        self.c.runner._prepare(before)
        original=bt.FakeBroker.snapshot_partial
        def slow(broker,codes):
            value=original(broker,codes)
            self.c.runner._now=lambda:before+timedelta(seconds=2)
            return value
        with patch.object(bt.FakeBroker,"snapshot_partial",slow):
            self.c.tick_at(before)
        self.assertEqual(bt.FakeBroker.submissions,[])


class AutomaticCompletionFinalBrokerTests(unittest.TestCase):
    def setUp(self):forbid_network(self)
    def make(self,bid=1.69,ask=1.70,tick=.01):
        sdk=br.FakeSDK()
        sdk.quotes["US.AAPL"].update(last_price=(bid+ask)/2,bid_price=bid,ask_price=ask,price_spread=tick)
        sdk.positions=[dict(code="US.AAPL",qty=2,can_sell_qty=2,market_val=2*(bid+ask)/2,position_side="LONG",currency="USD")]
        broker=brokers.MoomooBroker(account_id="222",sdk=sdk,now=lambda:br.NOW)
        self.addCleanup(broker.close);return sdk,broker
    def send(self,broker,*,side="BUY",kind="NORMAL",authorized=True):
        price=1.70 if side=="BUY" else 1.69
        return broker.submit(dict(code="US.AAPL",side=side,qty=1,limit_price=price),"daily-one-tick",
            allow_partial_quotes=True,execution_deadline_utc=(br.NOW+timedelta(seconds=600)).isoformat(),
            order_type=kind,allow_single_tick_spread=authorized)
    def test_one_tick_authority_passes_buy_and_sell_normal_and_market(self):
        for side in ("BUY","SELL"):
            for kind in ("NORMAL","MARKET"):
                with self.subTest(side=side,kind=kind):
                    sdk,b=self.make();self.send(b,side=side,kind=kind)
                    self.assertTrue(any(n=="place_order" for n,k in sdk.calls))
    def test_no_authority_multiple_ticks_over200_or_missing_tick_never_sent(self):
        for bid,ask,tick,authorized in ((1.69,1.70,.01,False),(1.69,1.71,.01,True),(.49,.50,.01,True),(1.69,1.70,None,True)):
            with self.subTest(case=(bid,ask,tick,authorized)):
                sdk,b=self.make(bid,ask,tick)
                with self.assertRaises(brokers.BrokerError):self.send(b,authorized=authorized)
                self.assertFalse(any(n=="place_order" for n,k in sdk.calls))
    def test_one_tick_cannot_relax_age_or_price_deviation(self):
        for defect in ("age","deviation"):
            with self.subTest(defect=defect):
                sdk,b=self.make()
                if defect=="age":sdk.quotes["US.AAPL"]["update_time"]="2026-09-25 10:59:00"
                else:sdk.quotes["US.AAPL"]["last_price"]=1.50
                with self.assertRaises(brokers.BrokerError):self.send(b)
                self.assertFalse(any(n=="place_order" for n,k in sdk.calls))
