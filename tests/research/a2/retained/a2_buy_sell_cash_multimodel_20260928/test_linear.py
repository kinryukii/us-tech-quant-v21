"""Boundary, capacity and optimizer tests plus artifact-only fit verification."""
from __future__ import annotations

import itertools
import json
from pathlib import Path
import time
import unittest

import numpy as np
import pandas as pd

import linear_train as linear


class TrainingBoundaryTests(unittest.TestCase):
    def test_sample_is_outcome_independent_and_label_maturity_purged(self):
        rows = []
        for date in pd.to_datetime(["2024-12-26", "2024-12-27", "2024-12-30"]):
            for i in range(9):
                rows.append({"signal_date": date, "ticker": f"T{i:02d}",
                             "label_end_date": date + pd.Timedelta(days=1),
                             "y_next_open": i / 100})
        rows.append({"signal_date": pd.Timestamp("2024-12-31"), "ticker": "PURGED",
                     "label_end_date": pd.Timestamp("2025-01-02"), "y_next_open": .9})
        frame = pd.DataFrame(rows)
        selected, keys, audit = linear.sample(frame, "2025-01-01", budget=7)
        changed = frame.sample(frac=1, random_state=7).copy()
        changed["y_next_open"] = np.arange(len(changed)) * -100
        selected2, keys2, audit2 = linear.sample(changed, "2025-01-01", budget=7)
        self.assertTrue(keys.equals(keys2))
        self.assertEqual(audit, audit2)
        self.assertEqual(len(selected), 7)
        self.assertEqual(selected.signal_date.nunique(), 3)
        self.assertFalse(selected.ticker.eq("PURGED").any())
        self.assertTrue(selected.label_end_date.lt("2025-01-01").all())

    def test_capacity_actual_weights_and_reward(self):
        capacity = linear.capacity
        adv = np.array([100_000., 10_000_000.])
        np.testing.assert_allclose(capacity.realized_weight(.05, .1, adv), [.051, .1])
        np.testing.assert_allclose(capacity.realized_weight(.1, .025, adv), [.025, .025])
        with self.assertRaises(ValueError):
            capacity.realized_weight(0., .1, np.array([0.]))
        frame = pd.DataFrame(np.zeros((2, len(linear.FEATURES))), columns=linear.FEATURES)
        frame["avg_dollar_volume_20d"] = adv
        frame["realized_vol_20d"] = .02
        frame["y_next_open"] = [2., -2.]
        x, y, audit = capacity.expand_capacity(frame)
        self.assertEqual(x.shape, (30, 106))
        self.assertEqual(y.shape, (30,))
        actual = capacity.realized_weight(0., .1, adv)
        expected = actual * np.array([.2, -.2]) - .001 * actual - 2 * .02**2 * actual**2
        np.testing.assert_allclose(y[8:10], expected)
        self.assertGreater(audit["capacity_limited_buy_labels"], 0)

    def test_allocator_matches_exhaustive_optimum_with_constraints(self):
        scores = np.array([[0., .1, .35, .31, .34],
                           [.1, .2, .15, .65, .5],
                           [0., .7, .6, .5, .4]])
        allowed = np.ones_like(scores, dtype=bool)
        allowed[2, 1:] = False
        targets, chosen = linear.allocate_joint_scores(scores, ["A", "B", "C"],
                                                        max_names=2, max_units=5, allowed=allowed)
        gains = scores - scores[:, :1]
        feasible = [a for a in itertools.product(range(5), repeat=3)
                    if sum(v > 0 for v in a) <= 2 and sum(a) <= 5
                    and all(allowed[i, v] for i, v in enumerate(a))]
        optimum = max(sum(gains[i, v] for i, v in enumerate(a)) for a in feasible)
        self.assertAlmostEqual(sum(gains[i, v] for i, v in enumerate(chosen)), optimum)
        self.assertNotIn("C", targets)
        self.assertLessEqual(sum(targets.values()), .125 + 1e-12)

    def test_pre_fit_seal_and_all_14_new_fits(self):
        contract = json.loads((linear.OUT / "PRE_FIT_CONTRACT.json").read_text(encoding="utf-8"))
        linear.verify_contract(contract)
        receipt = json.loads((linear.OUT / "FIT_RECEIPT.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["fit_calls"], 14)
        self.assertEqual(receipt["test2026_rows_read"], 0)
        self.assertEqual(receipt["hyperparameter_search_count"], 0)
        self.assertEqual(receipt["pre_fit_contract_sha256"], linear.sha(linear.OUT / "PRE_FIT_CONTRACT.json"))
        self.assertEqual({(r["stage"], r["name"]) for r in receipt["fits"]},
                         {(s, n) for s in linear.STAGES for n in linear.NAMES})
        for stage, cutoff in linear.STAGES.items():
            audit = receipt["stages"][stage]
            keys = pd.read_parquet(linear.OUT / f"sample_keys_{stage}.parquet")
            self.assertEqual(len(keys), 13333)
            self.assertEqual(keys.signal_date.nunique(), audit["eligible_dates"])
            self.assertTrue(keys.signal_date.lt(cutoff).all())
            self.assertTrue(keys.label_end_date.lt(cutoff).all())
            self.assertTrue(keys.label_end_date.gt(keys.signal_date).all())
            self.assertFalse(keys.duplicated(["signal_date", "ticker"]).any())
        for record in [*receipt["fits"], *receipt["numerical_repairs"]]:
            artifact = Path(record["artifact"])
            self.assertEqual(artifact.parent.resolve(), linear.OUT.resolve())
            self.assertEqual(linear.sha(artifact), record["artifact_sha256"])
            self.assertEqual(record["train_rows"], 199995)
        for repair in receipt["numerical_repairs"]:
            base = next(r for r in receipt["fits"] if r["stage"] == repair["stage"]
                        and r["name"] == repair["name"])
            self.assertEqual(repair["name"], "elastic_net")
            self.assertFalse(base["converged"])
            self.assertTrue(repair["converged"])
            self.assertTrue(repair["objective_and_data_unchanged"])
            self.assertEqual(base["matrix_sha256"], repair["matrix_sha256"])
            self.assertEqual(base["reward_sha256"], repair["reward_sha256"])

    def test_new_policy_interfaces_predict_finite_and_feasible(self):
        frame = pd.read_parquet(linear.DATA)
        day = frame.loc[frame.signal_date.eq(frame.signal_date.min())].head(30).copy()
        self.assertGreater(len(day), 0)
        before = {p.name: linear.sha(p) for p in linear.OUT.glob("*.joblib")}
        for stage in linear.STAGES:
            for name in (*linear.NAMES, "quantile_risk"):
                policy = linear.load_policy(name, stage)
                self.assertEqual(policy.name, name)
                self.assertEqual(policy.stage, stage)
                expected = {"q10", "q50", "q90"} if name == "quantile_risk" else {name}
                self.assertEqual(set(policy.models), expected)
                targets = policy(day, {}, 1., {})
                self.assertLessEqual(len(targets), 20)
                self.assertLessEqual(sum(targets.values()), .95 + 1e-12)
                self.assertTrue(all(0 < w <= .1 for w in targets.values()))
                self.assertTrue(np.isfinite(policy.last_actions.selected_action_value).all())
                if name == "logistic":
                    self.assertTrue(policy.last_actions.selected_action_value.between(0, 1).all())
        after = {p.name: linear.sha(p) for p in linear.OUT.glob("*.joblib")}
        self.assertEqual(before, after)


if __name__ == "__main__":
    started = time.monotonic()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TrainingBoundaryTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    linear.write(linear.OUT / "TEST_RECEIPT.json", {
        "status": "PASS" if result.wasSuccessful() else "FAIL",
        "tests_run": result.testsRun, "errors": len(result.errors), "failures": len(result.failures),
        "seconds": time.monotonic() - started,
        "test2026_rows_read": 0,
        "scope": "maturity/coverage/outcome-independent sampling, capacity reward, exhaustive allocator optimum, all new fit hashes, finite feasible policy inference",
        "test_code_sha256": linear.sha(Path(__file__)),
        "fit_receipt_sha256": linear.sha(linear.OUT / "FIT_RECEIPT.json")
        if (linear.OUT / "FIT_RECEIPT.json").exists() else None})
    raise SystemExit(0 if result.wasSuccessful() else 1)
