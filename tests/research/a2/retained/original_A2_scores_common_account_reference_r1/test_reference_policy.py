"""Adapter-only boundary tests. No training, model inference or research replay."""
import sys
sys.dont_write_bytecode = True

import unittest
from types import SimpleNamespace

import numpy as np
import pandas as pd

from reference_policy import OriginalA2ScorePolicy


SIGNAL_DATE = pd.Timestamp("2025-07-01")


def scores_for(values):
    return pd.DataFrame([
        {"signal_date": SIGNAL_DATE, "ticker": ticker, "a2_prediction": score}
        for ticker, score in values.items()
    ])


def inputs(names, *, slots=20, budget=.95, reserved=(), held=()):
    day = pd.DataFrame({"signal_date": [SIGNAL_DATE] * len(names), "ticker": names})
    context = SimpleNamespace(
        signal_date=SIGNAL_DATE, decision_tickers=tuple(names), available_slots=slots,
        available_weight=budget, reserved_tickers=tuple(reserved), reserved_slots=len(reserved),
        current_weights={ticker: .025 for ticker in (*reserved, *held)},
        current_units={ticker: 10. for ticker in (*reserved, *held)},
        max_positions=20, max_weight=.10, max_invested=.95)
    return day, context


class OriginalA2AdapterTests(unittest.TestCase):
    def test_cold_start_top20_score_then_ticker_and_negative_scores_stay_eligible(self):
        names = [f"T{i:02d}" for i in range(25)]
        values = {ticker: -1. for ticker in names}
        values["T24"] = 0.  # Score wins ahead of the lexical tie breaker.
        policy = OriginalA2ScorePolicy(scores_for(values))
        day, ctx = inputs(list(reversed(names)))
        decision = policy(day, ctx)
        selected = {ticker for ticker, weight in decision.model_decisions.items() if weight > 0}
        self.assertEqual(selected, {"T24", *names[:19]})
        self.assertEqual(len(decision.model_decisions), 25)
        self.assertTrue(all(weight == .0475 for weight in decision.model_decisions.values() if weight > 0))
        self.assertAlmostEqual(sum(decision.model_decisions.values()), .95)
        self.assertEqual(decision.raw_model_outputs["T24"]["decision_pool_rank"], 1)
        self.assertEqual(decision.raw_model_outputs["T00"]["decision_pool_rank"], 2)
        self.assertEqual(decision.raw_model_outputs["T00"]["saved_a2_oof_score"], -1.)

    def test_fewer_than_twenty_names_leave_remaining_budget_in_cash(self):
        policy = OriginalA2ScorePolicy(scores_for({"A": 2., "B": 1., "C": 0.}))
        day, ctx = inputs(["A", "B", "C"])
        decision = policy(day, ctx)
        self.assertEqual(decision.model_decisions, {"A": .0475, "B": .0475, "C": .0475})
        self.assertAlmostEqual(1 - sum(decision.model_decisions.values()), .8575)

    def test_reserved_slots_limit_ranked_names_without_held_name_priority(self):
        policy = OriginalA2ScorePolicy(scores_for({"LOWHELD": 0., "HIGH1": 3., "HIGH2": 2., "NEXT": 1.}))
        reserved = tuple(f"RESERVED{i:02d}" for i in range(18))
        day, ctx = inputs(["LOWHELD", "NEXT", "HIGH2", "HIGH1"], slots=2,
                          budget=.5, reserved=reserved, held=("LOWHELD",))
        decision = policy(day, ctx)
        self.assertEqual({ticker for ticker, weight in decision.model_decisions.items() if weight > 0}, {"HIGH1", "HIGH2"})
        self.assertEqual(decision.model_decisions["LOWHELD"], 0.)
        self.assertEqual(len([weight for weight in decision.model_decisions.values() if weight > 0]) + len(reserved), 20)
        self.assertTrue(all(ticker not in decision.model_decisions for ticker in reserved))

    def test_reserved_budget_only_scales_down_and_exhausted_budget_or_slots_gives_zero(self):
        for slots, budget, expected in [(3, .06, .02), (3, 0., 0.), (0, .50, 0.)]:
            with self.subTest(slots=slots, budget=budget):
                policy = OriginalA2ScorePolicy(scores_for({"A": 3., "B": 2., "C": 1.}))
                day, ctx = inputs(["A", "B", "C"], slots=slots, budget=budget)
                decision = policy(day, ctx)
                for weight in decision.model_decisions.values():
                    self.assertAlmostEqual(weight, expected)
                    self.assertLessEqual(weight, .0475)
                self.assertLessEqual(sum(decision.model_decisions.values()), budget + 1e-12)

    def test_explicit_zero_for_unselected_decidable_old_holding_but_no_key_for_reserved(self):
        policy = OriginalA2ScorePolicy(scores_for({"NEW": 2., "LOWHELD": 1., "RESERVED": 100.}))
        day, ctx = inputs(["NEW", "LOWHELD"], slots=1, budget=.5,
                          reserved=("RESERVED", "MISSING_INPUT"), held=("LOWHELD",))
        decision = policy(day, ctx)
        self.assertEqual(decision.model_decisions["LOWHELD"], 0.)
        self.assertEqual(decision.model_decisions["NEW"], .0475)
        self.assertNotIn("RESERVED", decision.model_decisions)
        self.assertNotIn("MISSING_INPUT", decision.model_decisions)
        self.assertEqual(decision.operational_exits, {})

    def test_invalid_saved_scores_or_decision_keys_fail_without_silent_reservation(self):
        good = scores_for({"A": 1.})
        with self.subTest(case="duplicate_saved_key"):
            with self.assertRaisesRegex(ValueError, "DUPLICATE_SAVED_OOF_KEY"):
                OriginalA2ScorePolicy(pd.concat([good, good], ignore_index=True))
        for value in [np.nan, np.inf, -np.inf]:
            with self.subTest(case="nonfinite", value=value):
                with self.assertRaisesRegex(ValueError, "NONFINITE_SAVED_OOF_SCORE"):
                    OriginalA2ScorePolicy(scores_for({"A": value}))
        policy = OriginalA2ScorePolicy(good)
        with self.subTest(case="missing_saved_score"):
            day, ctx = inputs(["A", "NO_SCORE"])
            with self.assertRaisesRegex(ValueError, "SAVED_OOF_MISSING"):
                policy(day, ctx)
        with self.subTest(case="duplicate_decision_ticker"):
            day, ctx = inputs(["A", "A"])
            with self.assertRaisesRegex(ValueError, "DUPLICATE_DECISION_DAY_KEY"):
                policy(day, ctx)
        with self.subTest(case="context_mismatch"):
            day, ctx = inputs(["A"])
            ctx.decision_tickers = ("OTHER",)
            with self.assertRaisesRegex(ValueError, "DECISION_DAY_CONTEXT_MISMATCH"):
                policy(day, ctx)
        self.assertEqual(policy.calls, 0)
        self.assertEqual(policy.score_rows_consumed, 0)


if __name__ == "__main__":
    unittest.main()
