"""Synthetic account/plan equivalence; no model, result, price or broker inputs."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import numpy as np
import pandas as pd
from scripts.research.a2.inference import consensus_paper as paper
from scripts.research.a2.inference import frozen_target_adaptation as seam
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2 import fast_account as engine
from scripts.research.a2.training.stateful_account import reference_policy_class


def current_frame():
    return pd.DataFrame([dict(signal_date=pd.Timestamp("2025-12-31"), ticker="T%02d" % j,
        security_id="S%02d" % j, is_raw_top20=True, raw_a2_rank=j + 1,
        raw_a2_prediction=.2 - j * .001, feature_available=True, new_buy_eligible=True)
        for j in range(20)])


def state_for(names):
    return dict(weights={t: .01 for t in names}, cash_weight=1. - len(names) * .01,
                units={t: j + 1 for j, t in enumerate(names)},
                security_ids={t: "SID" + t for t in names}, previous_requested_gross=.75)


def current_plan(state, requested=1., sid=paper.NEW_IDS[2], *, frame=None, records=()):
    frame = current_frame() if frame is None else frame
    doc = dict(signal_date="2025-12-31", strategy_status={sid: {"status": "READY"}},
               input_refs={"current": {}}, flags_ref={}, source_bundle_ref={})
    with patch.object(paper, "verify", return_value=Path("synthetic")), \
         patch.object(pd, "read_parquet", return_value=frame), \
         patch.object(paper, "requested_gross", return_value=(.75, requested, {})), \
         patch.object(paper, "decoded_actions", return_value=(list(records), {})):
        return paper.infer_application(SimpleNamespace(), sid, state, doc)


def original_targets(state, requested=1., *, frame=None):
    # Run the actual frozen engine on one completely synthetic signal session.
    frame = current_frame() if frame is None else frame; tickers = sorted(set(frame.ticker) | set(state["weights"]))
    qualified = np.array([[t in set(frame.ticker) for t in tickers]])
    top = qualified.copy(); vol = np.zeros_like(top, float)
    base = reference_policy_class()(vol, np.zeros(1), None, np.zeros(1), vol,
                                     top, qualified, ["SYNTHETIC"])
    def policy(di, ctx):
        result = base(di, ctx)
        mask = result.explicit_mask & ~ctx.reserved_mask & ctx.decision_mask
        return engine.TargetDecision(np.where(mask, result.weights * requested, 0.), explicit_mask=mask)
    market = engine.MarketArrays([pd.Timestamp("2025-12-31")], tickers,
        np.ones_like(top, float), np.ones_like(top, float), quality=np.zeros_like(top, bool),
        input_present=qualified, new_buy_eligible=np.array([[t in set(frame.loc[frame.new_buy_eligible, "ticker"]) for t in tickers]]))
    # Identical normalized weights; units themselves only determine ownership.
    units = np.array([1. if t in state["weights"] else 0. for t in tickers])
    result = engine.run_many(market, ["B"], policy,
        initial_cash=100. * state["cash_weight"], initial_units=units,
        max_positions=20, max_weight=1., max_invested=1., capacity_fraction=None, cost_bps=0.)
    return result.orders.set_index("ticker").target_weight.to_dict()


class FrozenTargetAdaptationTests(unittest.TestCase):
    def test_fifteen_outside_holds_plus_twenty_requests_match_original_repair(self):
        state = state_for(["O%02d" % j for j in range(15)])
        expected = original_targets(state)
        for sid in paper.NEW_IDS:
            with self.subTest(sid=sid):
                plan = current_plan(state, sid=sid)
                rows = {r["ticker"]: r for r in plan["rows"]}
                self.assertEqual(sum(r["target_weight"] > 0 for r in rows.values()), 20)
                self.assertEqual(set(rows), set(expected))
                for t, weight in expected.items():
                    self.assertAlmostEqual(rows[t]["target_weight"], weight)
                for t in state["weights"]:
                    self.assertEqual(rows[t]["action"], "HOLD")
                    self.assertFalse(rows[t]["explicit_target"])
                    self.assertEqual(rows[t]["exact_hold_units"], state["units"][t])
                pruned = [r for r in rows.values() if r["adaptation_reasons"] == "SIGNAL_RESERVED_SLOT_BUDGET"]
                self.assertEqual(len(pruned), 15)
                self.assertTrue(all(r["target_weight"] == 0 and r["raw_model_weight"] > 0 for r in pruned))
                proof = plan["target_adaptation_receipt"]
                self.assertEqual(proof["reserved_positions"], 15)
                self.assertEqual(proof["available_target_slots"], 5)
                self.assertEqual(proof["engine_ref"]["sha256"], seam.ENGINE_SHA)
                self.assertEqual(proof["ast_edits"], [])
                self.assertAlmostEqual(plan["target_cash_weight"], .6375)

    def test_r7_request_state_stays_on_grid_after_cap_and_preserves_holds_at_zero(self):
        state = state_for(["O%02d" % j for j in range(15)])
        for requested in (.5, 0.):
            with self.subTest(requested=requested):
                plan = current_plan(state, requested)
                expected = original_targets(state, requested)
                for row in plan["rows"]:
                    self.assertAlmostEqual(row["target_weight"], expected.get(row["ticker"], 0.))
                self.assertEqual(plan["requested_gross"], requested)
                self.assertEqual(plan["strategy_state_after"]["previous_requested_gross"], requested)
                self.assertEqual(plan["previous_requested_gross"], .75)
                self.assertAlmostEqual(sum(r["target_weight"] for r in plan["rows"]) + plan["target_cash_weight"], 1.)
                self.assertTrue(all(r.get("exact_hold_units") == state["units"][r["ticker"]]
                                    for r in plan["rows"] if r["ticker"] in state["units"]))

    def test_full_hold_slots_leave_requests_cash_without_forced_hold_sale(self):
        state = state_for(["O%02d" % j for j in range(20)])
        plan = current_plan(state)
        self.assertEqual(sum(r["target_weight"] > 0 for r in plan["rows"]), 20)
        self.assertEqual(plan["target_adaptation_receipt"]["available_target_slots"], 0)
        self.assertAlmostEqual(plan["target_cash_weight"], .8)
        with self.assertRaisesRegex(ValueError, "HOLD_COUNT_EXCEEDS"):
            current_plan(state_for(["O%02d" % j for j in range(21)]))

    def test_existing_target_priority_and_buy_ineligibility_match_original(self):
        state = state_for(["O%02d" % j for j in range(14)] + ["T19"])
        state["security_ids"]["T19"] = "S19"
        frame = current_frame(); frame.loc[frame.ticker.eq("T19"), "new_buy_eligible"] = False
        expected = original_targets(state, frame=frame)
        plan = current_plan(state, frame=frame)
        rows = {r["ticker"]: r for r in plan["rows"]}
        for t, weight in expected.items():
            self.assertAlmostEqual(rows[t]["target_weight"], weight)
        self.assertEqual(sum(r["target_weight"] > 0 for r in rows.values()), 20)
        self.assertEqual(rows["T19"]["target_weight"], .01)
        self.assertTrue(rows["T19"]["explicit_target"])
        self.assertEqual(plan["target_adaptation_receipt"]["available_target_slots"], 6)

    def test_removed_pool_sell_packet_cannot_override_exact_hold(self):
        state = state_for(["O00"])
        record = dict(ticker="O00", security_id="SIDO00", kind="SELL", decision="SELL")
        plan = current_plan(state, sid=paper.NEW_IDS[1], records=[record])
        row = next(r for r in plan["rows"] if r["ticker"] == "O00")
        self.assertEqual(row["action"], "HOLD")
        self.assertEqual(row["exact_hold_units"], 1)
        self.assertEqual(row["target_weight"], .01)

    def test_owner_and_account_pins_fail_closed(self):
        with patch.object(seam, "ENGINE_SHA", "0" * 64):
            with self.assertRaisesRegex(ValueError, "OWNER_CHANGED"):
                seam._projection()
        with patch.object(seam, "CONFIG_SHA", "0" * 64):
            with self.assertRaisesRegex(ValueError, "OWNER_CHANGED"):
                seam.frozen_limits()


if __name__ == "__main__":
    unittest.main()
