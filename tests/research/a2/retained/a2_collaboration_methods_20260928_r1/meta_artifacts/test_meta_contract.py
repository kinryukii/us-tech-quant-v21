"""Synthetic, no-fit tests of meta time guards, sampling and inference arithmetic."""
import sys
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unittest
import json
import tempfile
import joblib
import numpy as np
import pandas as pd
from meta_train import FrozenMeta, P_COLS, G_COLS, STAGES, select_stage, sha


def panel(counts=(20, 2, 10)):
    records = []
    for number, (date, count) in enumerate(zip(pd.date_range("2025-01-06", periods=len(counts)), counts)):
        for ticker in range(count):
            records.append(dict(signal_date=date, ticker=f"T{ticker:03}",
                p_ridge=.01, p_hgb=.02, p_mlp=-.01, target=.02,
                target_end_date=date+pd.Timedelta(days=10), target_context_available=True,
                base_cutoff=pd.Timestamp("2025-01-01"), g_ret20mean=.01*number,
                g_vol20mean=.02, g_breadth_ma20=.5, g_disagreement=.02))
    return pd.DataFrame(records)


class ConstantResidual:
    def predict(self, X):
        return np.full(len(X), .02)


def fake_stage_artifacts(artifacts, stage="validation", wrong=None):
    """Valid identity envelopes around non-fitted constant fixtures."""
    folder = Path(artifacts)/stage
    folder.mkdir()
    identity = {"stage": stage, "cutoff_exclusive": STAGES[stage]}
    wrong_identity = {"stage": "final", "cutoff_exclusive": STAGES["final"]}
    learned = {**(wrong_identity if wrong == "learned_fixed" else identity), "coefficients": [.2, .5, .3]}
    (folder/"learned_fixed.json").write_text(json.dumps(learned), encoding="utf-8")
    filenames = ["learned_fixed.json"]
    for method in ["stack_ridge", "stack_mlp", "ridge_then_hgb", "hgb_then_ridge"]:
        bundle = {**(wrong_identity if wrong == method else identity), "model": ConstantResidual(), "scaler": None}
        joblib.dump(bundle, folder/(method+".joblib"))
        filenames.append(method+".joblib")
    gate_identity = wrong_identity if wrong == "conditional_gate" else identity
    np.savez(folder/"conditional_gate.npz", mean=np.zeros(4), scale=np.ones(4),
        w1=np.zeros((8, 4)), b1=np.zeros(8), w2=np.zeros((3, 8)), b2=np.zeros(3),
        _stage=np.array(gate_identity["stage"]), _cutoff_exclusive=np.array(gate_identity["cutoff_exclusive"]))
    filenames.append("conditional_gate.npz")
    receipt = {**(wrong_identity if wrong == "receipt" else identity), "status": "PASS", "predictive_fits_or_solves": 6,
               "artifact_sha256": {name: sha(folder/name) for name in filenames}}
    (folder/"STAGE_RECEIPT.json").write_text(json.dumps(receipt), encoding="utf-8")
    return folder


class MetaContractTests(unittest.TestCase):
    def test_label_must_mature_strictly_before_cutoff_and_context_is_required(self):
        data = panel((4,))
        data.loc[0, "target_end_date"] = pd.Timestamp("2025-07-01")
        data.loc[1, "target_context_available"] = False
        data.loc[2, "target_end_date"] = pd.NaT
        selected, excluded = select_stage(data, "validation")
        self.assertEqual(selected.ticker.tolist(), ["T003"])
        self.assertEqual(len(excluded), 3)
        self.assertIn("TARGET_NOT_MATURE_BEFORE_STAGE_CUTOFF", excluded.iloc[0].exclusion_reasons)
        self.assertIn("TARGET_CONTEXT_UNAVAILABLE", excluded.iloc[1].exclusion_reasons)
        self.assertIn("TARGET_END_UNKNOWN", excluded.iloc[2].exclusion_reasons)

    def test_equal_date_quota_hash_selection_is_order_and_target_value_independent(self):
        data = panel()
        selected, excluded = select_stage(data, "validation", cap=12)
        self.assertEqual(sorted(selected.groupby("signal_date").size().tolist()), [2, 5, 5])
        self.assertTrue(np.allclose(selected.groupby("signal_date").sample_weight.sum(), 4.))
        self.assertAlmostEqual(selected.sample_weight.sum(), 12.)
        changed = data.sample(frac=1, random_state=123).copy()
        changed["target"] = np.linspace(-.8, .8, len(changed))
        again, _ = select_stage(changed, "validation", cap=12)
        self.assertEqual(list(selected[["signal_date", "ticker"]].itertuples(index=False, name=None)),
                         list(again[["signal_date", "ticker"]].itertuples(index=False, name=None)))
        self.assertEqual(len(excluded)+len(selected), len(data))
        self.assertTrue(excluded.exclusion_reasons.eq("FIXED_DATE_BALANCED_HASH_CAP").all())

    def test_training_target_clips_but_saved_base_predictions_remain_unclipped(self):
        data = panel((2,))
        data.loc[0, ["target", "p_ridge"]] = [1.2, 1.5]
        data.loc[1, "target"] = -1.2
        selected, _ = select_stage(data, "final")
        self.assertEqual(selected.target.tolist(), [1.2, -1.2])
        self.assertEqual(selected.target_clipped_for_training.tolist(), [.3, -.3])
        self.assertEqual(selected.p_ridge.iloc[0], 1.5)

    def test_future_base_unknown_source_year_and_ticker_specific_gate_state_fail(self):
        for mutation, message in [
            (lambda d: d.assign(base_cutoff=pd.Timestamp("2025-02-01")), "OOF_BASE_CUTOFF"),
            (lambda d: d.assign(base_cutoff=pd.Timestamp("2025-01-02")), "FIXED_ANNUAL_OOF_VINTAGE"),
            (lambda d: d.assign(base_cutoff=pd.Timestamp("2024-01-01")), "FIXED_ANNUAL_OOF_VINTAGE"),
            (lambda d: d.assign(signal_date=pd.Timestamp("2026-01-02")), "ONLY_CONTAIN_2024_2025"),
            (lambda d: d.assign(g_breadth_ma20=[.5, .6]), "GATE_CONTEXT_NOT_CONSTANT")]:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    select_stage(mutation(panel((2,))), "final")

    def test_fixed_learned_gate_and_residual_predictions_use_return_units(self):
        meta = FrozenMeta.__new__(FrozenMeta)
        meta.coefficients = np.array([.3, .4, .3])
        meta.models = {name: {"model": ConstantResidual(), "scaler": None}
                       for name in ["ridge_then_hgb", "hgb_then_ridge"]}
        prior = np.array([.2, .5, .3], dtype=np.float32)
        meta.gate = dict(mean=np.zeros(4), scale=np.ones(4), w1=np.zeros((8, 4), dtype=np.float32),
                         b1=np.zeros(8, dtype=np.float32), w2=np.zeros((3, 8), dtype=np.float32),
                         b2=np.log((prior-.05)/.85))
        P = np.array([[.1, -.2, .3], [.02, .03, .04]])
        G = np.zeros((2, 4))
        np.testing.assert_allclose(meta.predict("fixed_pred", P, G), P@prior, atol=1e-8)
        np.testing.assert_allclose(meta.predict("learned_fixed", P, G), P@meta.coefficients)
        np.testing.assert_allclose(meta.predict("conditional_gate", P, G), P@prior, atol=1e-8)
        np.testing.assert_allclose(meta.gate_weights(G).sum(axis=1), 1., atol=1e-7)
        np.testing.assert_allclose(meta.predict("ridge_then_hgb", P, G), P[:, 0]+.02)
        np.testing.assert_allclose(meta.predict("hgb_then_ridge", P, G), P[:, 1]+.02)

    def test_inference_rejects_target_columns_and_score_fusion_for_decision_blend(self):
        meta = FrozenMeta.__new__(FrozenMeta)
        P, G = np.zeros((2, 3)), np.zeros((2, 4))
        with self.assertRaisesRegex(ValueError, "DECISION_BLEND_REQUIRES_BASE_TOP20"):
            meta.predict("decision_blend", P, G)
        with self.assertRaisesRegex(ValueError, "N_BY_3_P_AND_N_BY_4_G"):
            meta.predict("fixed_pred", np.zeros((2, 4)), G)
        with self.assertRaisesRegex(ValueError, "NONFINITE_META_INFERENCE"):
            meta.predict("fixed_pred", np.full((2, 3), np.nan), G)

    def test_validation_loader_fails_closed_on_final_artifact_identity(self):
        for wrong in ["receipt", "learned_fixed", "stack_ridge", "stack_mlp", "ridge_then_hgb", "hgb_then_ridge", "conditional_gate"]:
            with self.subTest(wrong=wrong), tempfile.TemporaryDirectory() as directory:
                fake_stage_artifacts(directory, wrong=wrong)
                with self.assertRaisesRegex(RuntimeError, "STAGE_OR_CUTOFF_MISMATCH"):
                    FrozenMeta("validation", artifacts=directory)

    def test_valid_stage_identity_loads_with_no_fit_and_gate_cutoff_is_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            fake_stage_artifacts(directory)
            loaded = FrozenMeta("validation", artifacts=directory)
            np.testing.assert_allclose(loaded.coefficients, [.2, .5, .3])
            self.assertEqual(loaded.stage, "validation")
            self.assertEqual(loaded.gate_weights(np.zeros((2, 4))).shape, (2, 3))


if __name__ == "__main__":
    unittest.main()
