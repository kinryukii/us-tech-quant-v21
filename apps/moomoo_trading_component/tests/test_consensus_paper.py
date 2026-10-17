"""Synthetic contract checks; no historical result, broker or model reads."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import numpy as np
import pandas as pd
from scripts.research.a2.inference import consensus_paper as c
from scripts.research.a2.inference import frozen_a94_state as original
from scripts.research.a2.training.stateful_inputs import FEATURES
from scripts.research.a2.training import stateful_final_action_packets as packets


def fixture():
    cal = pd.bdate_range("2023-01-03", periods=25)
    rows = []
    for day in cal:
        for i in range(24):
            row = {f: .01 for f in FEATURES}
            row.update(signal_date=day, ticker="T" + str(i), security_id="S" + str(i), feature_available=True,
                is_raw_top20=i < 20, new_buy_eligible=i < 20, raw_top20_set_complete=True,
                raw_a2_rank=i+1, raw_a2_prediction=.1-i*.001)
            rows.append(row)
    return pd.DataFrame(rows), cal


class PaperInputTests(unittest.TestCase):
    def test_only_current_features_and_original_r7_counterstate_grid(self):
        frame, cal = fixture(); current = frame.loc[frame.signal_date.eq(cal[-1])]
        result = c.gross_frame(current, cal[-1])
        self.assertEqual(len(result), 5)
        self.assertEqual(set(result.gross_previous_proxy), {0., .25, .5, .75, 1.})
        self.assertFalse(set(result) & c.FORBIDDEN)
        expected = np.sqrt(np.sum(current.loc[current.is_raw_top20, "realized_vol_20d"]**2))/20
        self.assertTrue(np.allclose(result.diagonal_vol_proxy, expected))
        with self.assertRaisesRegex(ValueError, "COMPLETE_RAW20"):
            c.gross_frame(current.loc[current.ticker.ne("T0")], cal[-1])

    def test_r10_thin_current_projection_matches_original_full_prefix_kernel(self):
        prefix, cal = fixture(); day = cal[-1]
        roles = c.original_frames(prefix, cal, day)
        auth = SimpleNamespace(task_id=original.profile.TASK, provenance_json='{"source_refs":{"action_inputs":{"path":"synthetic","sha256":"synthetic"}}}')
        def scoped(values, nullable=False): return pd.to_datetime(values)
        def clock(*args): return auth, day, pd.Timestamp("2023-02-06T21:00:00Z"), scoped, lambda x: pd.DatetimeIndex(x), cal
        with patch.object(original, "_clock_scope", clock), patch.object(original, "_required_roles", return_value=("R10:ENTRY", "R10:INCUMBENT")):
            result = original.build_current_state(auth, prefix, cal, day, decision_as_of="synthetic", r6_probe_rows=None,
                native_h5_probe_rows=None, action_source_ref={"path":"synthetic","sha256":"synthetic"}, required_roles=("R10:ENTRY","R10:INCUMBENT"))
        for name, ours in roles.items():
            trusted = result.role_frames["R10:" + name][list(ours)].reset_index(drop=True)
            pd.testing.assert_frame_equal(ours.reset_index(drop=True), trusted, check_dtype=False)
            self.assertFalse(set(ours) & c.FORBIDDEN)
        with self.assertRaisesRegex(ValueError, "COHORT_PHASE"):
            c.original_frames(prefix.loc[prefix.signal_date.gt(cal[0])], cal[1:], day)

    def test_hold_units_and_skipped_slot_preserve_cash_without_normalisation(self):
        prefix, cal = fixture(); current = prefix.loc[prefix.signal_date.eq(cal[-1])].copy()
        day = str(cal[-1].date()); sid = c.NEW_IDS[1]
        records = [packets.decode_r10_row(dict(ticker="T0", security_id="S0", sample_id="h", action_type=0, mean=-1), 0),
                   packets.decode_r10_row(dict(ticker="T1", security_id="S1", sample_id="e", mean=-1), 1, group="ENTRY")]
        doc = dict(signal_date=day, strategy_status={sid:{"status":"READY"}}, flags_ref={}, source_bundle_ref={}, input_refs={"current":{}})
        state = dict(weights={"T0":.1}, cash_weight=.9, units={"T0":5})
        with patch.object(c, "verify", return_value=Path("synthetic")), patch.object(pd, "read_parquet", return_value=current), patch.object(c, "decoded_actions", return_value=(records, {})):
            plan = c.infer_application(SimpleNamespace(), sid, state, doc)
        rows = {r["ticker"]:r for r in plan["rows"]}
        self.assertEqual(rows["T0"]["action"], "HOLD")
        self.assertEqual(rows["T0"]["exact_hold_units"], 5)
        self.assertFalse(rows["T0"]["explicit_target"])
        self.assertEqual(rows["T1"]["target_weight"], 0)
        self.assertGreater(plan["target_cash_weight"], .05)
        self.assertAlmostEqual(sum(r["target_weight"] for r in rows.values()) + plan["target_cash_weight"], 1)

    def test_auxiliary_features_do_not_authorise_exit_of_removed_pool_holding(self):
        prefix, cal = fixture(); current = prefix.loc[prefix.signal_date.eq(cal[-1])].copy()
        current.loc[current.ticker.eq("T21"), ["raw_a2_rank","security_id"]] = [np.nan,None]
        sid=c.NEW_IDS[1]; doc=dict(signal_date=str(cal[-1].date()),strategy_status={sid:{"status":"READY"}},flags_ref={},source_bundle_ref={},input_refs={"current":{}})
        state=dict(weights={"T21":.1},cash_weight=.9,units={"T21":5},security_ids={"T21":"S21"})
        with patch.object(c,"verify",return_value=Path("synthetic")), patch.object(pd,"read_parquet",return_value=current), patch.object(c,"decoded_actions",return_value=([],{})):
            plan=c.infer_application(SimpleNamespace(),sid,state,doc)
        held=next(row for row in plan["rows"] if row["ticker"]=="T21")
        self.assertEqual(held["action"],"HOLD")
        self.assertEqual(held["exact_hold_units"],5)
        self.assertEqual(held["security_id"],"S21")
        self.assertEqual(held["target_weight"],.1)

    def test_r7_uses_previous_request_grid_and_releases_loaded_model(self):
        import joblib
        from scripts.research.a2.training import stateful_decision as decision, stateful_decision_models as model_owner
        prefix, cal = fixture(); current = prefix.loc[prefix.signal_date.eq(cal[-1])]
        gross = c.gross_frame(current, cal[-1]); _, names = decision.encode_features(gross, decision.GROSS)
        class Model:
            objective = "gross"; learner = "linear"; features = names
        refs = {"R7_GROSS_LINEAR": {"model_ref": {"path":"synthetic","sha256":"synthetic"}}}
        requested = np.array([.25, .5, .75, 1., 0.])
        doc = dict(signal_date=str(cal[-1].date()), input_refs={"GROSS":{}})
        with patch.object(c, "resource_check"), patch.object(c, "verify", return_value=Path("synthetic")), \
             patch.object(c, "frozen_states", return_value=refs), patch.object(pd, "read_parquet", return_value=gross), \
             patch.object(joblib, "load", side_effect=lambda p:Model()), \
             patch.object(model_owner, "predict", new=lambda model,x:{"gross":requested}):
            previous, target, _ = c.requested_gross(SimpleNamespace(), doc, {"previous_requested_gross":.75,"realized_gross":.13})
        self.assertEqual((previous,target),(.75,1.))

    def test_extension_proof_retains_pool_frozen_pins_and_history_limitations(self):
        day=pd.Timestamp("2026-10-12"); clock=pd.Timestamp("2026-10-13T09:00:00Z")
        source={"path":"bundle","sha256":c.BUNDLE_SHA}; flags={"path":"flags","sha256":"f"*64}
        feature={"path":"math","sha256":"fd4fe78d27bfbf57c89343d60550366ccf7fcbf3d6a65e7ef66f28405d050c19"}
        model={"path":"model","sha256":"4f7eff07021bef084b0329dac8dabc31e9391c7c4945eb2955dc6c1339dcea0b"}
        parent={"source_role":"FROZEN_HISTORY_RESEARCH_OBSERVATIONS","source_completeness_unknown":True,"historical_available_at_bound":False}
        proof=dict(schema="CURRENT_CONSENSUS_PAPER_SOURCE_EXTENSION_R1",task_id="DEMO_FIVE_STRATEGY_PAPER_20261013_R1",status="READY",signal_date="2026-10-12",
            observed_at_utc=clock.isoformat(),decision_as_of=clock.isoformat(),source_bundle_ref=source,flags_ref=flags,new_fit=0,
            selection_rule="MANAGER_COUNT_WEIGHT_SUM",pool_variant_id="TOP100",cohort_count=25,execution_admission_inherited=False,
            parent_flags_ref={"path":"parentflags","sha256":"8598030725df0758336ca6e2a7b559f4c203d0d106e1e79a1064437a2b1dfa06"},raw_model_ref=model,feature_source_ref=feature,
            **{"parent_"+k:v for k,v in parent.items()},current_day_proofs=[dict(signal_date="2026-10-12",ordered_pool_security_ids=["S"+str(i) for i in range(100)],ranked_pool_security_ids=["S"+str(i) for i in range(100)],unranked_pool_security_ids=[],input_coverage_status="READY",ranked_rows=100,rows=110,source_snapshot_id="snapshot",
                mapping_ref={},feature_ref=dict(path="frame",sha256="f"*64,signal_date="2026-10-12",feature_source_ref=feature,frozen_model_sha256=model["sha256"]))])
        with patch.object(c,"verify",return_value=Path("synthetic")), patch.object(c,"metadata",new=lambda ref,fields:parent if ref==source else proof):
            self.assertEqual(c.validate_extension({},flags,source,day,clock),proof)
            changed_bundle = dict(source, sha256="a"*64)
            with self.assertRaisesRegex(ValueError,"ORIGINAL_TOP100_BUNDLE_REQUIRED"):
                c.validate_extension({},flags,changed_bundle,day,clock)
            partial = deepcopy(proof)
            partition = partial["current_day_proofs"][0]
            partition.update(ranked_pool_security_ids=["S"+str(i) for i in range(93)],
                unranked_pool_security_ids=["S"+str(i) for i in range(93,100)],ranked_rows=93,input_coverage_status="PARTIAL")
            with patch.object(c,"metadata",new=lambda ref,fields:parent if ref==source else partial):
                self.assertEqual(c.validate_extension({},flags,source,day,clock),partial)
                self.assertEqual(len(partition["ordered_pool_security_ids"]),100)
                partition["ranked_pool_security_ids"][0]="INJECTED_ID"
                with self.assertRaisesRegex(ValueError,"POOL_ORDER_PROOF"):
                    c.validate_extension({},flags,source,day,clock)
            proof["parent_historical_available_at_bound"]=True
            with self.assertRaisesRegex(ValueError,"LIMITATIONS_CHANGED"):c.validate_extension({},flags,source,day,clock)
            proof["parent_historical_available_at_bound"]=False
            proof["current_day_proofs"][0]["ordered_pool_security_ids"][99]="S0"
            with self.assertRaisesRegex(ValueError,"POOL_ORDER_PROOF"):c.validate_extension({},flags,source,day,clock)

    def test_cash_reset_ids_are_explicit_two_hgb_only(self):
        from moomoo_component.applied_source import HGB_RESET_STRATEGY_IDS, ACTIVE_STRATEGY_IDS, STRATEGY_IDS
        self.assertEqual(HGB_RESET_STRATEGY_IDS,("HGB_DIAG_5","HGB_FACTOR_5"))
        self.assertEqual(len(ACTIVE_STRATEGY_IDS),5)
        self.assertIn("HGB_FACTOR_5",STRATEGY_IDS)
        self.assertFalse(set(c.NEW_IDS)&set(HGB_RESET_STRATEGY_IDS))

    def test_new_input_missing_does_not_clear_old_strategy_plans(self):
        from moomoo_component.applied_source import _CanonicalSource
        source = _CanonicalSource.__new__(_CanonicalSource); source.paths = SimpleNamespace()
        day = "2026-10-12"; now = "2026-10-12T21:00:00Z"
        source.close_hours = {day:("2026-10-12T13:30:00Z", "2026-10-12T20:00:00Z"),"2026-10-13":("2026-10-13T13:30:00Z","2026-10-13T20:00:00Z")}
        source._calendar = lambda clock: (day,list(source.close_hours),source.close_hours)
        result = dict(signal_date=day, plans={"RAW_A2":{"status":"READY"}}, execution_date="2026-10-13",source_refs={})
        states = {"RAW_A2":{},c.NEW_IDS[2]:dict(weights={}, cash_weight=1., signal_date=day, valuation_basis="SIGNAL_CLOSE")}
        with patch.object(c,"load_publication",side_effect=ValueError("synthetic gap")):
            result=source._new_plans(result,states,now)
        self.assertIn("RAW_A2",result["plans"])
        self.assertEqual(result["strategy_status"][c.NEW_IDS[2]]["status"],"BLOCKED")


if __name__ == "__main__": unittest.main()
