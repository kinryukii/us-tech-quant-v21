from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

from moomoo_component.strategy import (execution_reasons, validate_manifest,
    validate_auto_completion_policy, auto_completion_spread_is_valid, automatic_completion_clock_matches)


class StrategyBoundaryTests(unittest.TestCase):
    def setUp(self):
        now = datetime.now(timezone.utc)
        self.manifest = dict(schema_version=1, strategy_id='source-a', name='来源A', revision='1',
            asof=now.isoformat(), expires_at=(now + timedelta(hours=1)).isoformat(),
            provenance='live', targets=[dict(code='US.AAPL', target_qty=2)])

    def test_quantities_and_symbols_are_strict(self):
        for quantity in (-1, 0.5, True, '2', float('nan'), float('inf')):
            item = deepcopy(self.manifest)
            item['targets'][0]['target_qty'] = quantity
            with self.subTest(quantity=quantity), self.assertRaises(ValueError):
                validate_manifest(item)
        for code in ('HK.00700', 'US.AAPL260925C200000', '../file', 'BTC', ''):
            item = deepcopy(self.manifest)
            item['targets'][0]['code'] = code
            with self.subTest(code=code), self.assertRaises(ValueError):
                validate_manifest(item)

    def test_arbitrary_code_and_unknown_keys_not_imported(self):
        for key in ('python', 'plugin', 'command', 'broker', 'account_id', 'risk_limits'):
            item = {**self.manifest, key: 'payload'}
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_manifest(item)

    def test_duplicate_codes_and_naive_time_rejected(self):
        item = deepcopy(self.manifest)
        item['targets'].append(deepcopy(item['targets'][0]))
        with self.assertRaises(ValueError):
            validate_manifest(item)
        item = {**self.manifest, 'asof': '2026-09-25T12:00:00'}
        with self.assertRaises(ValueError):
            validate_manifest(item)

    def test_historical_demo_expired_and_future_execution_barriers(self):
        self.assertEqual(execution_reasons(self.manifest, 'moomoo_simulate', 86400), [])
        now = datetime.now(timezone.utc)
        for updates, mode in (({'provenance': 'historical'}, 'paper'),
                              ({'provenance': 'demo'}, 'moomoo_simulate'),
                              ({'asof': (now + timedelta(minutes=5)).isoformat()}, 'paper'),
                              ({'expires_at': (now - timedelta(seconds=1)).isoformat()}, 'paper'),
                              ({'asof': (now - timedelta(days=2)).isoformat()}, 'paper')):
            with self.subTest(updates=updates, mode=mode):
                self.assertTrue(execution_reasons({**self.manifest, **updates}, mode, 86400))



class AutomaticCompletionBoundaryTests(unittest.TestCase):
    def policy(self):
        return dict(schema_version=1, enabled=True, policy_id="user_auto_test_once",
            reason="USER_EXPLICIT_DAILY_AUTO_COMPLETION", authorized_at_utc="2026-09-28T16:00:00+00:00",
            effective_execution_date="2026-09-29", evaluation_end_exclusive="2027-01-01",
            priority_window_seconds=600, close_buffer_seconds=600, one_tick_spread=True,
            normal_spread_bps=50, max_single_tick_spread_bps=200, quote_max_age_seconds=30,
            price_deviation_fraction=.02, active_strategy_ids=["HGB_DIAG_5","HGB_FACTOR_5"],
            broker_account_id="3604", broker_budget=10000)

    def test_only_explicit_next_day_bounded_policy_is_accepted(self):
        policy=self.policy()
        self.assertEqual(validate_auto_completion_policy(policy),policy)
        for changes in ({"effective_execution_date":"2026-09-28"},
                        {"effective_execution_date":"2027-01-01"},
                        {"effective_execution_date":None},{"authorized_at_utc":"2026-09-28T16:00:00"},
                        {"broker_budget":10001},{"normal_spread_bps":200},
                        {"quote_max_age_seconds":31},{"price_deviation_fraction":.03},
                        {"active_strategy_ids":["RAW_A2"]},{"broker_account_id":"REAL"},
                        {"close_buffer_seconds":599},{"priority_window_seconds":True},
                        {"extra":"override"}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                validate_auto_completion_policy({**policy,**changes})

    def test_schema_two_adds_only_the_explicit_clock_and_keeps_original_scope(self):
        legacy=self.policy()
        policy={**legacy,"schema_version":2,"execution_delay_minutes":25,"priority_window_seconds":1500}
        before=deepcopy(policy)
        self.assertIs(validate_auto_completion_policy(policy),policy)
        self.assertEqual(policy,before)
        self.assertEqual(set(policy)-set(legacy),{"execution_delay_minutes"})
        for changes in ({"execution_delay_minutes":0},{"execution_delay_minutes":30},
                        {"execution_delay_minutes":True},{"execution_delay_minutes":25.0},
                        {"priority_window_seconds":600},{"priority_window_seconds":1500.0},
                        {"schema_version":True},{"schema_version":3},{"enabled":1},
                        {"broker_budget":10001},{"broker_account_id":"REAL"},
                        {"active_strategy_ids":["HGB_DIAG_5","R10_DIRECT_H5_RIDGE_MID"]},
                        {"active_strategy_ids":["HGB_DIAG_5"]},{"close_buffer_seconds":599},
                        {"quote_max_age_seconds":31},{"normal_spread_bps":200},
                        {"max_single_tick_spread_bps":201},{"price_deviation_fraction":.03},
                        {"one_tick_spread":1},{"extra":"override"}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                validate_auto_completion_policy({**policy,**changes})
        missing={k:v for k,v in policy.items() if k!="execution_delay_minutes"}
        with self.assertRaises(ValueError):validate_auto_completion_policy(missing)
        for changes in ({"execution_delay_minutes":25},{"priority_window_seconds":1500}):
            with self.subTest(legacy_injection=changes),self.assertRaises(ValueError):
                validate_auto_completion_policy({**legacy,**changes})
        self.assertEqual(validate_auto_completion_policy(legacy),self.policy())

    def test_shared_clock_match_is_schema_bound_and_validates_before_matching(self):
        legacy=self.policy()
        current={**legacy,"schema_version":2,"execution_delay_minutes":25,"priority_window_seconds":1500}
        for delay,window in ((0,600),(30,600)):
            self.assertTrue(automatic_completion_clock_matches(legacy,delay,window))
            self.assertFalse(automatic_completion_clock_matches(current,delay,window))
        self.assertTrue(automatic_completion_clock_matches(current,25,1500))
        self.assertFalse(automatic_completion_clock_matches(legacy,25,1500))
        for policy in (legacy,current):
            before=deepcopy(policy)
            for delay,window in ((25,600),(30,1500),(0,1500),(25,3600),(True,600),(25,True),(25.0,1500),(25,1500.0)):
                with self.subTest(schema=policy["schema_version"],delay=delay,window=window):
                    self.assertFalse(automatic_completion_clock_matches(policy,delay,window))
            self.assertEqual(policy,before)
        with self.assertRaises(ValueError):
            automatic_completion_clock_matches({**current,"broker_budget":1},25,1500)

    def test_actual_one_tick_data_required_above_normal_spread(self):
        self.assertTrue(auto_completion_spread_is_valid({"bid":100,"ask":100.01}))
        original={"bid":1.69,"ask":1.70,"price_tick":.01}
        self.assertTrue(auto_completion_spread_is_valid(original))
        self.assertTrue(auto_completion_spread_is_valid({**original,"tick_size":.01}))
        for row in ({"bid":1.69,"ask":1.70}, {"bid":1.69,"ask":1.70,"tick_size":.01}, {**original,"price_tick":.001},
                    {**original,"tick_size":.02}, {**original,"price_tick":True},
                    {"bid":1.69,"ask":1.71,"price_tick":.01},
                    {"bid":.49,"ask":.50,"price_tick":.01},
                    {"bid":0,"ask":.01,"price_tick":.01},
                    {"bid":2,"ask":1,"price_tick":.01},
                    {**original,"ask":float("nan")}, {**original,"price_tick":float("inf")}):
            with self.subTest(row=row):
                self.assertFalse(auto_completion_spread_is_valid(row))


class FrozenConsensusHoldBoundaryTests(unittest.TestCase):
    ids = ("R10_DIRECT_MEAN4_ELASTICNET_MID", "R10_DIRECT_H5_RIDGE_MID", "R7_GROSS_LINEAR", "R6_DURATION_TREE")

    def plan(self, sid, quantity=5.0):
        return dict(strategy_id=sid, policy_id=sid, account_basis="OWN_SIGNAL_CLOSE_FROZEN_CONSENSUS",
            valuation_basis="SIGNAL_CLOSE", status="READY", broker_action_allowed=False, model_fit_calls=0,
            rows=[dict(code="US.AAPL", action="HOLD", explicit_target=False, exact_hold_units=quantity, target_weight=.1)])

    def test_only_bound_current_paper_integer_floats_are_lossless_and_plan_immutable(self):
        import json
        from moomoo_component.strategy import exact_hold_units
        for sid in self.ids:
            for quantity in (0.0, 5.0, float(2**53)):
                with self.subTest(sid=sid, quantity=quantity):
                    plan=self.plan(sid,quantity); before=json.dumps(plan,sort_keys=True)
                    result=exact_hold_units(plan)
                    self.assertEqual(result,{"US.AAPL":int(quantity)})
                    self.assertIs(type(result["US.AAPL"]),int)
                    self.assertEqual(json.dumps(plan,sort_keys=True),before)

    def test_invalid_float_and_bool_units_remain_rejected(self):
        from moomoo_component.strategy import exact_hold_units
        for sid in self.ids:
            for quantity in (True,False,float("nan"),float("inf"),-float("inf"),-.1,1.5,float(2**53+2),"5",None):
                with self.subTest(sid=sid,quantity=quantity),self.assertRaisesRegex(ValueError,"EXACT_HOLD_UNIT_CONTRACT_INVALID"):
                    exact_hold_units(self.plan(sid,quantity))

    def test_unknown_legacy_cross_identity_or_unbound_scope_keeps_original_int_contract(self):
        from moomoo_component.strategy import exact_hold_units
        changes=({"strategy_id":"RAW_A2","policy_id":"RAW_A2"},{"strategy_id":"HGB_DIAG_5","policy_id":"HGB_DIAG_5"},
            {"strategy_id":"HGB_FACTOR_5","policy_id":"HGB_FACTOR_5"},{"strategy_id":"UNKNOWN","policy_id":"UNKNOWN"},
            {"strategy_id":"R6_BUY_NEURAL","policy_id":"R6_BUY_NEURAL"},{"strategy_id":"RAW_s10","policy_id":"RAW_s10"},
            {"strategy_id":None},{"policy_id":self.ids[1]},{"account_basis":"CASH_START"},{"valuation_basis":"OTHER"},
            {"status":"BLOCKED"},{"broker_action_allowed":True},{"model_fit_calls":1},{"model_fit_calls":False})
        for change in changes:
            with self.subTest(change=change):
                plan={**self.plan(self.ids[0]),**change}
                with self.assertRaisesRegex(ValueError,"EXACT_HOLD_UNIT_CONTRACT_INVALID"):exact_hold_units(plan)
                plan["rows"][0]["exact_hold_units"]=5
                self.assertEqual(exact_hold_units(plan),{"US.AAPL":5})

    def test_only_explicit_false_zero_entry_skip_without_hold_units_is_omitted(self):
        from moomoo_component.strategy import exact_hold_units
        for sid in self.ids:
            plan=self.plan(sid)
            for zero in (0,0.0):
                plan["rows"].append(dict(code="US.MSFT",action="SKIP",explicit_target=False,target_weight=zero))
                self.assertEqual(exact_hold_units(plan),{"US.AAPL":5});plan["rows"].pop()
            for updates in ({"target_weight":.1},{"target_weight":True},{"target_weight":float("nan")},
                    {"target_weight":float("inf")},{"target_weight":None},{"code":"HK.00700"},
                    {"explicit_target":True},{"explicit_target":None},{"exact_hold_units":0},{"action":"TARGET"},{"action":"SELL"}):
                row=dict(code="US.MSFT",action="SKIP",explicit_target=False,target_weight=0);row.update(updates)
                with self.subTest(sid=sid,updates=updates),self.assertRaisesRegex(ValueError,"EXACT_HOLD_UNIT_CONTRACT_INVALID"):
                    exact_hold_units({**plan,"rows":plan["rows"]+[row]})
        for sid in ("RAW_A2","UNKNOWN"):
            plan=self.plan(sid,5);plan["rows"].append(dict(code="US.MSFT",action="SKIP",explicit_target=False,target_weight=0))
            with self.subTest(sid=sid),self.assertRaisesRegex(ValueError,"EXACT_HOLD_UNIT_CONTRACT_INVALID"):exact_hold_units(plan)

    def test_source_real_21_row_shape_keeps_integer_hold_units_and_actual_unit_guard(self):
        import json,tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from moomoo_component.applied_source import _CanonicalSource
        from moomoo_component.strategy import exact_hold_units
        from moomoo_component.core import Engine
        from scripts.research.a2.inference import consensus_paper as consumer
        signal="2026-09-25";execution="2026-09-28";opening=datetime(2026,9,28,13,30,tzinfo=timezone.utc)
        for sid in self.ids[:2]:
            with self.subTest(sid=sid),tempfile.TemporaryDirectory() as tmp:
                source=_CanonicalSource.__new__(_CanonicalSource);source.paths=SimpleNamespace()
                source.close_hours={signal:(signal+"T13:30:00Z",signal+"T20:00:00Z"),execution:(execution+"T13:30:00Z",execution+"T20:00:00Z")}
                source._calendar=lambda clock:(signal,list(source.close_hours),source.close_hours)
                rows=[dict(ticker=chr(65+i),security_id="S"+str(i),target_weight=.01 if i<16 else 0,
                    action="HOLD" if i<16 else "TARGET",explicit_target=i>=16,
                    **({"exact_hold_units":float(i+1)} if i<16 else {})) for i in range(21)]
                application=dict(status="READY",signal_date=signal,rows=rows,target_cash_weight=.84,
                    policy_id=sid,account_basis="OWN_SIGNAL_CLOSE_FROZEN_CONSENSUS",source_refs={},model_refs={})
                state=dict(signal_date=signal,valuation_basis="SIGNAL_CLOSE",weights={chr(65+i):.01 for i in range(16)},
                    cash_weight=.84,units={chr(65+i):i+1 for i in range(16)})
                initial=dict(signal_date=signal,source_date=signal,execution_date=execution,next_open_utc=opening.isoformat(),source_refs={})
                with patch.object(consumer,"load_publication",return_value=({},{})),patch.object(consumer,"infer_application",return_value=application):
                    loaded=source._new_plans(initial,{sid:state},datetime(2026,9,25,21,tzinfo=timezone.utc))
                plan=loaded["plans"][sid];before=json.dumps(plan,sort_keys=True)
                holds=exact_hold_units(plan);self.assertEqual(len(holds),16);self.assertTrue(all(type(q)is int for q in holds.values()))
                engine=Engine(Path(tmp),paper_only=True)
                try:
                    engine._set("paper",dict(cash=9200,positions=holds,fees=0))
                    clock=opening+timedelta(seconds=5)
                    quotes={code:dict(price=100,bid=100,ask=100,asof=clock.isoformat(),tradable=True,lot_size=1,source="MOOMOO_OPEND") for code in holds}
                    result=engine.paper_rebalance(sid,plan,quotes,now=clock,next_open_utc=opening.isoformat(),signal_date=signal,
                        execution_date=execution,signal_close_utc=signal+"T20:00:00Z",source_refs={"fixture":"a"*64},allow_partial_quotes=True,execution_window_seconds=600)
                    self.assertEqual(result["status"],"EXECUTED");self.assertEqual(engine.paper_book()["trade_count"],0)
                    self.assertEqual({r["code"]:r["qty"] for r in engine.paper_book()["positions"]},holds)
                    self.assertEqual(json.dumps(plan,sort_keys=True),before)
                    changed=deepcopy(plan);changed["rows"][0]["exact_hold_units"]=2.0;changed["source_date"]=execution
                    with self.assertRaisesRegex(ValueError,"EXACT_HOLD_UNITS_CHANGED"):
                        engine.paper_rebalance(sid,changed,{},now=opening+timedelta(days=1,seconds=5),next_open_utc=(opening+timedelta(days=1)).isoformat(),
                            signal_date=execution,execution_date="2026-09-29",signal_close_utc=execution+"T20:00:00Z",execution_window_seconds=600)
                    self.assertEqual(engine.paper_book()["trade_count"],0)
                finally:engine.close()

    def test_original_consumer_hold_and_skip_output_crosses_execution_interface_unchanged(self):
        import json
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        import pandas as pd
        from test_consensus_paper import fixture
        from scripts.research.a2.inference import consensus_paper as c
        from scripts.research.a2.training import stateful_final_action_packets as packets
        from moomoo_component.strategy import exact_hold_units
        prefix,calendar=fixture();current=prefix.loc[prefix.signal_date.eq(calendar[-1])].copy()
        current["ticker"]=[chr(65+i) for i in range(len(current))];sid=self.ids[1]
        records=[packets.decode_r10_row(dict(ticker="A",security_id="S0",sample_id="h",action_type=0,mean=-1),0),
            packets.decode_r10_row(dict(ticker="B",security_id="S1",sample_id="e",mean=-1),1,group="ENTRY")]
        doc=dict(signal_date=str(calendar[-1].date()),strategy_status={sid:{"status":"READY"}},flags_ref={},source_bundle_ref={},input_refs={"current":{}})
        state=dict(weights={"A":.1},cash_weight=.9,units={"A":5})
        with patch.object(c,"verify",return_value=Path("synthetic")),patch.object(pd,"read_parquet",return_value=current),patch.object(c,"decoded_actions",return_value=(records,{})):
            plan=c.infer_application(SimpleNamespace(),sid,state,doc)
        plan.update(strategy_id=sid,valuation_basis="SIGNAL_CLOSE",broker_action_allowed=False)
        for row in plan["rows"]:row["code"]="US."+row["ticker"]
        before=json.dumps(plan,sort_keys=True);rows={r["ticker"]:r for r in plan["rows"]}
        self.assertEqual(rows["B"]["action"],"SKIP");self.assertEqual(rows["B"]["target_weight"],0)
        self.assertEqual(exact_hold_units(plan),{"US.A":5})
        self.assertEqual(json.dumps(plan,sort_keys=True),before)


if __name__ == '__main__':
    unittest.main()
