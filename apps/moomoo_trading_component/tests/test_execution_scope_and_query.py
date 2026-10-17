"""Pre2026 fake-native account scoping and exact read-count regression."""
from pathlib import Path
from datetime import datetime,timedelta
from copy import deepcopy
from unittest.mock import patch
import json,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_native_first_execution as base
from moomoo_component import core as C,best_broker as B,strategy

class ExecutionScopeTests(unittest.TestCase):
    def prepared(self,old_ticker=False,old_date=None):
        helper=base.NativeFirstTests("test_authorization_is_separate_finite_idempotent_no_phase_or_start")
        original=base.F.Source.load
        def load(source,*args,**kw):
            value=original(source,*args,**kw)
            if old_ticker:value["plans"][base.F.RIDGE]["rows"][0]["code"]="US.OLD"
            return value
        original_order=base.F.ResetTests.order
        def order(fixture,ident,*args,**kwargs):
            original_order(fixture,ident,*args,**kwargs)
            if ident=="old-buy" and old_date is not None:
                fixture.engine.db.execute("UPDATE orders SET created_at=? WHERE id=?",(old_date,ident))
        with patch.object(base.F.Source,"load",load),patch.object(base.F.ResetTests,"order",order):helper.setUp()
        self.addCleanup(helper.doCleanups)
        # Keep the first fixture archive immutable when the rollover case prepares its successor.
        def published_load(*args,**kwargs):
            value=load(helper.s,*args,**kwargs)
            archive=helper.f.path/("current-source-"+value["signal_date"]+".json")
            archive.write_text(base.F.canon({"plans":value["plans"]}),encoding="utf8")
            value["archive"]={"path":str(archive),"sha256":B.hashlib.sha256(archive.read_bytes()).hexdigest()}
            return value
        helper.s.load=published_load
        return helper
    @staticmethod
    def snap(helper,code="US.OLD"):
        value=deepcopy(helper.b.snapshot)
        value["quotes"]={code:dict(price=100.,bid=99.99,ask=100.01,asof=helper.now.isoformat(),lot_size=1,price_tick=.01,tradable=True)}
        return value
    def poisoned(self,helper,quantities=None):
        helper.grant();record=helper.b._native_first_record()
        state=dict(signal_date="2025-10-13",phase="BUY",processed_codes=["US.OLD","US.ZERO"],
            target_quantities=quantities if quantities is not None else {"US.KNOWN":7,"US.ZERO":0},
            native_first_execution_permission_sha256=helper.b._content_sha(record))
        helper.e._set("best_execution",state);helper.b.stop_event.clear();return state
    def test_session_orders_scope_physical_account_strategy_and_fill_identity(self):
        h=self.prepared();h.f.order("wrong-strategy",base.F.NEW,"US.AAA",1)
        h.e.db.execute("UPDATE orders SET strategy_id=? WHERE id=?",(base.F.R7,"wrong-strategy"))
        h.f.order("right-order",base.F.NEW,"US.AAA",1,fill=dict(fill_qty=1,account_id=base.F.OLD,
            strategy_id=base.F.R7,id="spoof",code="US.FAKE",status="UNKNOWN"))
        rows=h.b._current_session_orders();self.assertEqual(len(rows),1)
        self.assertEqual((rows[0]["id"],rows[0]["account_id"],rows[0]["strategy_id"],rows[0]["code"],rows[0]["status"]),
            ("right-order",base.F.NEW,base.F.RIDGE,"US.AAA","FILLED_ALL"))
    def test_aware_session_instants_utc_jst_and_exact_close(self):
        h=self.prepared()
        dates={"jst-nextday":"2025-10-15T04:00:00+09:00", "utc-same":"2025-10-14T19:00:00Z",
            "at-open":"2025-10-14T22:30:00+09:00", "before-open":"2025-10-14T22:29:59.999999+09:00",
            "before-close":"2025-10-15T04:59:59.999999+09:00", "at-close":"2025-10-15T05:00:00+09:00"}
        for ident,date in dates.items():
            h.f.order(ident,base.F.NEW,"US.AAA",1)
            h.e.db.execute("UPDATE orders SET created_at=? WHERE id=?",(date,ident))
        h.f.order("wrong-sid-invalid",base.F.NEW,"US.AAA",1)
        h.e.db.execute("UPDATE orders SET strategy_id=?,created_at='invalid' WHERE id='wrong-sid-invalid'",(base.F.R7,))
        h.e.db.execute("UPDATE order_fills SET payload='invalid' WHERE id IN ('before-open','at-close','wrong-sid-invalid')")
        rows=h.b._current_session_orders()
        self.assertEqual([v["id"] for v in rows],["before-close","utc-same","jst-nextday","at-open"])
        self.assertEqual([v["id"] for v in h.b._current_session_orders(descending=False)],
            ["at-open","jst-nextday","utc-same","before-close"])
        self.assertEqual({v["id"]:v["created_at"] for v in rows},{k:dates[k] for k in ("before-close","utc-same","jst-nextday","at-open")})
    def test_invalid_current_timestamp_is_fail_closed_before_fill_decode(self):
        for date in ("invalid","2025-10-14T19:00:00",""):
            with self.subTest(date=date):
                h=self.prepared();h.f.order("invalid-current",base.F.NEW,"US.AAA",1)
                h.e.db.execute("UPDATE orders SET created_at=? WHERE id='invalid-current'",(date,))
                h.e.db.execute("UPDATE order_fills SET payload='invalid' WHERE id='invalid-current'")
                with self.assertRaisesRegex(ValueError,"CURRENT_SESSION_ORDER_TIMESTAMP_INVALID"):h.b._current_session_orders()
    def test_foreign_evidence_aware_instants_and_exact_close(self):
        for date,expected in (("2025-10-15T04:00:00+09:00",True),("2025-10-14T19:00:00Z",True),
                ("2025-10-15T04:59:59.999999+09:00",True),("2025-10-15T05:00:00+09:00",False),
                ("2025-10-14T22:29:59.999999+09:00",False)):
            with self.subTest(date=date):
                h=self.prepared(True,old_date=date);state=self.poisoned(h)
                proof=h.b._foreign_processed_scope_repair(state,[],{"US.OLD":.5},{},h.now)
                self.assertEqual(proof is not None,expected)
                if expected:self.assertEqual(proof["foreign_attempts"][0]["created_at"],date)
        h=self.prepared(True,old_date="invalid");state=self.poisoned(h)
        with self.assertRaisesRegex(ValueError,"FOREIGN_SESSION_ORDER_TIMESTAMP_INVALID"):
            h.b._foreign_processed_scope_repair(state,[],{"US.OLD":.5},{},h.now)
    def test_foreign_processed_without_quantity_resolves_naturally_once_and_keeps_prefix(self):
        h=self.prepared(True);state=self.poisoned(h);oldorders=h.f.prefix()["orders"];oldfills=h.f.prefix()["order_fills"]
        after=h.b._partial_execution(h.now,"BUY",self.snap(h))
        expected=h.b._desired_quantity(.5,10000.,self.snap(h)["quotes"]["US.OLD"],buy=True)
        self.assertEqual(after["target_quantities"]["US.OLD"],expected)
        self.assertEqual(after["target_quantities"]["US.KNOWN"],7);self.assertEqual(after["target_quantities"]["US.ZERO"],0)
        self.assertNotIn("US.OLD",after["processed_codes"]);self.assertIn("US.ZERO",after["processed_codes"])
        self.assertEqual(h.f.prefix()["orders"],oldorders);self.assertEqual(h.f.prefix()["order_fills"],oldfills)
        audit=h.e.db.execute("SELECT detail FROM audit WHERE event='NATIVE_EXECUTION_ACCOUNT_SCOPE_REPAIRED'").fetchall()
        self.assertEqual(len(audit),1);proof=json.loads(audit[0][0]);self.assertEqual(proof["removed_processed_codes"],["US.OLD"])
        self.assertEqual(proof["original_execution_sha256"],h.b._content_sha(state))
        after2=h.b._partial_execution(h.now,"BUY",self.snap(h));self.assertEqual(after2["target_quantities"],after["target_quantities"])
        self.assertEqual(h.e.db.execute("SELECT COUNT(*) FROM audit WHERE event='NATIVE_EXECUTION_ACCOUNT_SCOPE_REPAIRED'").fetchone()[0],1)
    def test_resolved_quantity_and_current_account_attempt_are_never_cleared(self):
        for resolved,current in ((True,False),(False,True)):
            with self.subTest(resolved=resolved,current=current):
                h=self.prepared(True);state=self.poisoned(h,{"US.OLD":12} if resolved else {})
                if current:h.f.order("current-original",base.F.NEW,"US.OLD",1)
                after=h.b._partial_execution(h.now,"BUY",self.snap(h))
                self.assertIn("US.OLD",after["processed_codes"])
                self.assertEqual(after["target_quantities"],state["target_quantities"])
                self.assertFalse(h.e.db.execute("SELECT 1 FROM audit WHERE event='NATIVE_EXECUTION_ACCOUNT_SCOPE_REPAIRED'").fetchone())
    def test_same_account_other_strategy_attempt_blocks_foreign_repair(self):
        h=self.prepared(True);state=self.poisoned(h)
        h.f.order("same-account-other-sid",base.F.NEW,"US.OLD",1)
        h.e.db.execute("UPDATE orders SET strategy_id=?,created_at='2025-10-15T04:00:00+09:00' WHERE id='same-account-other-sid'",(base.F.R7,))
        self.assertEqual(h.b._current_session_orders(),[])
        self.assertIsNone(h.b._foreign_processed_scope_repair(state,[],{"US.OLD":.5},{},h.now))
        self.assertEqual(h.e._get("best_execution",None),state)
        self.assertFalse(h.e.db.execute("SELECT 1 FROM audit WHERE event='NATIVE_EXECUTION_ACCOUNT_SCOPE_REPAIRED'").fetchone())
    def test_before_open_cannot_repair_state_or_audit(self):
        h=self.prepared(True);state=self.poisoned(h)
        with self.assertRaises(ValueError):
            h.b._foreign_processed_scope_repair(state,[],{"US.OLD":.5},{},B.timestamp(h.b.metadata["next_open_utc"])-timedelta(microseconds=1))
        self.assertEqual(h.e._get("best_execution",None),state)
        self.assertFalse(h.e.db.execute("SELECT 1 FROM audit WHERE event='NATIVE_EXECUTION_ACCOUNT_SCOPE_REPAIRED'").fetchone())
    def test_after_open_before_native_authorization_cannot_repair(self):
        h=self.prepared(True);state=self.poisoned(h)
        clock=h.now-timedelta(microseconds=1)
        self.assertGreater(clock,B.timestamp(h.b.metadata["next_open_utc"]))
        with self.assertRaisesRegex(ValueError,"CURRENT_VALID_EXECUTION"):
            h.b._foreign_processed_scope_repair(state,[],{"US.OLD":.5},{},clock)
        self.assertEqual(h.e._get("best_execution",None),state)
        self.assertFalse(h.e.db.execute("SELECT 1 FROM audit WHERE event='NATIVE_EXECUTION_ACCOUNT_SCOPE_REPAIRED'").fetchone())
    def test_sell_detour_does_not_call_buy_scope_repair(self):
        h=self.prepared(True);state=self.poisoned(h)
        with patch.object(h.b,"_foreign_processed_scope_repair",side_effect=AssertionError("BUY_REPAIR_IN_SELL")):
            result=h.b._partial_execution(h.now,"SELL",self.snap(h),sell_codes=[],resume_buy_state=state)
        self.assertEqual(result["phase"],"SELL")
        self.assertFalse(h.e.db.execute("SELECT 1 FROM audit WHERE event='NATIVE_EXECUTION_ACCOUNT_SCOPE_REPAIRED'").fetchone())
    def test_exact_hold_or_no_foreign_evidence_is_not_repaired(self):
        h=self.prepared(True);state=self.poisoned(h)
        self.assertIsNone(h.b._foreign_processed_scope_repair(state,[],{"US.OLD":.5},{"US.OLD":3},h.now))
        state["processed_codes"]=["US.ABSENT"]
        self.assertIsNone(h.b._foreign_processed_scope_repair(state,[],{"US.ABSENT":.5},{},h.now))
    def test_expired_permission_cannot_repair_processed_or_create_quantity(self):
        h=self.prepared(True);state=self.poisoned(h);raw=h.e._get("best_execution",None)
        with self.assertRaisesRegex(ValueError,"CURRENT_VALID_EXECUTION"):
            h.b._foreign_processed_scope_repair(state,[],{"US.OLD":.5},{},h.now+timedelta(seconds=600))
        self.assertEqual(h.e._get("best_execution",None),raw)
        self.assertFalse(h.e.db.execute("SELECT 1 FROM audit WHERE event='NATIVE_EXECUTION_ACCOUNT_SCOPE_REPAIRED'").fetchone())
    def test_repair_rejects_changed_source_without_touching_state_or_audit(self):
        h=self.prepared(True);state=self.poisoned(h);raw=h.e._get("best_execution",None);status=h.s.status
        h.s.status=lambda now=None:{**status(now),"next_close_utc":"2025-10-14T20:01:00+00:00"}
        with self.assertRaisesRegex(ValueError,"CURRENT_SOURCE_CHANGED"):
            h.b._foreign_processed_scope_repair(state,[],{"US.OLD":.5},{},h.now)
        self.assertEqual(h.e._get("best_execution",None),raw)
        self.assertFalse(h.e.db.execute("SELECT 1 FROM audit WHERE event='NATIVE_EXECUTION_ACCOUNT_SCOPE_REPAIRED'").fetchone())
    def test_no_native_epoch_cannot_enable_repair(self):
        h=self.prepared(True);state=self.poisoned(h);h.e.db.execute("DELETE FROM settings WHERE key='best_native_reset_epoch'")
        self.assertIsNone(h.b._foreign_processed_scope_repair(state,[],{"US.OLD":.5},{},h.now))
    def test_same_call_epoch_verification_is_one_and_next_call_revalidates(self):
        h=self.prepared();h.grant()
        with self.assertRaises(TypeError):h.b._native_first_binding(_epoch={"untrusted":True})
        with patch.object(h.b,"_native_reset_record",wraps=h.b._native_reset_record) as verify:
            record=h.b._native_first_record();self.assertEqual(verify.call_count,1)
        self.assertEqual(record["account_id"],base.F.NEW)
        self.assertEqual(record["plan_sha256"],h.b._content_sha(h.b.plan))
        epoch=h.b._native_reset_record()
        h.e.db.execute("UPDATE settings SET value='changed' WHERE key=?",(epoch["archive_namespace"]+"raw_unknown",))
        with self.assertRaisesRegex(ValueError,"ARCHIVED_SETTINGS_CHANGED"):h.b._native_first_record()
    def test_real_owner_rollover_prepares_new_plan_without_old_native_permission(self):
        h=self.prepared();ack=h.grant();oldgrant=h.f.rawsettings()["best_native_first_execution"]
        oldslot=h.f.rawsettings()["best_native_first_execution:"+ack["epoch_id"]]
        audit=h.e.db.execute("SELECT detail FROM audit WHERE event='NATIVE_FIRST_EXECUTION_AUTHORIZED'").fetchone()[0]
        oldbootstrap=h.f.rawsettings()["best_native_reset_bootstrap"]
        h.f.order("first-epoch-fill",base.F.NEW,"US.AAA",2)
        base.F.Native.native[base.F.NEW]=dict(cash=9800.,equity=10000.,positions={"US.AAA":dict(qty=2,sellable=2,market_value=200.)},open_orders=[])
        h.b._accept_snapshot(h.e.broker.snapshot([],include_quotes=False))
        nextday=h.now+timedelta(days=1);status=h.s.status
        def newstatus(now=None):
            value=status(now)
            value.update(signal_date="2025-10-14",source_date="2025-10-14",execution_date="2025-10-15",
                signal_close_utc="2025-10-14T20:00:00+00:00",next_open_utc="2025-10-15T13:30:00+00:00",next_close_utc="2025-10-15T20:00:00+00:00")
            return value
        h.s.status=newstatus;h.b._now=lambda:nextday
        receipt=h.b.prepare_published_inputs(expected_signal_date="2025-10-14",now=nextday)
        self.assertTrue(receipt["prepared"]);self.assertEqual(h.b.metadata["signal_date"],"2025-10-14")
        self.assertIsNone(h.b._native_first_record())
        self.assertEqual(h.b._execution_end().isoformat(),"2025-10-15T13:40:00+00:00")
        self.assertEqual(h.f.rawsettings()["best_native_first_execution"],oldgrant)
        self.assertEqual(h.f.rawsettings()["best_native_first_execution:"+ack["epoch_id"]],oldslot)
        self.assertEqual(h.f.rawsettings()["best_native_reset_bootstrap"],oldbootstrap)
        self.assertEqual(h.e.db.execute("SELECT detail FROM audit WHERE event='NATIVE_FIRST_EXECUTION_AUTHORIZED'").fetchone()[0],audit)
        close=[call for call in h.s.calls if isinstance(call,tuple) and call[0]=="close_states"][-1]
        self.assertEqual(close[1][base.F.RIDGE]["positions"],{"US.AAA":2})
        self.assertNotIn("native_first_execution_permission_sha256",h.e._get("best_plan",{})["plan"])
    def test_pending_step_uses_two_fresh_snapshots_and_same_deadline(self):
        h=self.prepared();h.grant();h.b.stop_event.clear();snap=self.snap(h,"US.AAA")
        state=h.b._partial_execution(h.now,"BUY",snap);reads=[];sent=[]
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return h.now if tz is None else h.now.astimezone(tz)
        def snapshot(codes,**kwargs):reads.append(list(codes));return deepcopy(snap)
        def submit(order,client_id,**kwargs):
            sent.append((deepcopy(order),client_id,kwargs))
            return dict(order_id="native-synthetic",status="SUBMITTED")
        with patch.object(C,"datetime",Clock),patch.object(strategy,"datetime",Clock),patch.object(C,"now_iso",return_value=h.now.isoformat()), \
                patch.object(h.e,"_snapshot",side_effect=snapshot),patch.object(h.e.broker,"submit",side_effect=submit):
            result=h.e.step(respect_cancel=True,allow_partial_quotes=True,broker_order_type="MARKET")
        self.assertEqual(len(reads),2)
        self.assertEqual(len(result["submitted"]),1);self.assertEqual(len(sent),1);self.assertTrue(h.e._pending())
        self.assertEqual(sent[0][2]["execution_deadline_utc"],(h.now+timedelta(seconds=600)).isoformat())
        self.assertEqual(sent[0][0],{key:result["submitted"][0][key] for key in ("code","side","qty","limit_price")})
        self.assertEqual(sent[0][0]["qty"],state["target_quantities"]["US.AAA"])
        self.assertEqual(h.e._get("best_execution",None),state)
if __name__=="__main__":unittest.main()
