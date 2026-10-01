"""Small contract tests for the new signal/execute seam."""
import unittest

import numpy as np
import pandas as pd

from policy_engine import Account, PriceStore, project_capped_simplex, qp_target


class PolicyEngineTest(unittest.TestCase):
    def test_projection_includes_exact_cash_corner(self):
        all_cash = project_capped_simplex(np.r_[np.full(20, -1.), 1.])
        self.assertTrue(np.array_equal(all_cash[:20], np.zeros(20)))
        self.assertEqual(all_cash[-1], 1.)
        mixed = project_capped_simplex(np.ones(21))
        self.assertAlmostEqual(mixed.sum(), 1., places=10)
        self.assertTrue(np.all(mixed[:20] <= .10 + 1e-12))

    def test_zero_expected_reward_waits_and_cost_makes_trading_weakly_less(self):
        w, status = qp_target(np.zeros(20), np.eye(20) * .01, np.zeros(20))
        self.assertTrue(status["solver_success"])
        self.assertAlmostEqual(w.sum(), 0., places=9)
        high = np.r_[.1, np.zeros(19)]
        w2, status2 = qp_target(high, np.eye(20) * .0001, np.zeros(20))
        self.assertTrue(status2["solver_success"])
        self.assertAlmostEqual(w2[0], .1, places=7)
        self.assertTrue(np.all(w2[1:] < 1e-7))
        # One-way fee is 5 bps: a 2.5 bps expected edge cannot justify entry.
        tiny = np.r_[.00025, np.zeros(19)]
        w3, status3 = qp_target(tiny, np.zeros((20, 20)), np.zeros(20))
        self.assertTrue(status3["solver_success"])
        self.assertAlmostEqual(w3.sum(), 0., places=8)

    def test_signal_close_value_ignores_next_open_until_execution(self):
        rows = []
        for date, close, opening in [("2024-01-02", 10., 9.),
                                     ("2024-01-03", 11., 20.),
                                     ("2024-01-04", 12., 12.)]:
            for i in range(20):
                rows.append({"trade_date": date, "ticker": f"S{i}",
                             "close": close, "open": opening})
        store = PriceStore(pd.DataFrame(rows))
        acct = Account(store)
        names = [f"S{i}" for i in range(20)]
        state = acct.signal_state(pd.Timestamp("2024-01-02"), names)
        self.assertEqual(state["nav"], 1.)
        self.assertTrue(np.array_equal(state["weights"], np.zeros(20)))
        result = acct.execute(pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03"),
                              names, np.r_[.1, np.zeros(19)])
        self.assertAlmostEqual(result["fee"], .00005, places=10)
        after = acct.signal_state(pd.Timestamp("2024-01-03"), names)
        self.assertLess(after["nav"], 1.)
        self.assertGreater(acct.cash, 0.)
        liquidation = acct.liquidate(pd.Timestamp("2024-01-04"))
        self.assertEqual(acct.shares, {})
        self.assertGreater(liquidation["fee"], 0.)


if __name__ == "__main__":
    unittest.main()
