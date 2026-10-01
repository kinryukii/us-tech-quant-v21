"""Zero-fit tests for full-hash 2026 inference gating and source lineage."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import pandas as pd

import freeze_batch
import predict_saved
import train_models as trainer
from common import sha


class FreezeGateTests(unittest.TestCase):
    def frozen_fixture(self, root):
        artifact = root / "frozen_model.dat"
        artifact.write_bytes(b"original frozen bytes")
        contract = root / "contract.json"
        contract.write_text("{}", encoding="utf-8")
        (root / "DESIGN_LOCK.json").write_text(json.dumps({"contract_sha256": sha(contract)}), encoding="utf-8")
        value = {"status": "FROZEN", "fit_2026_rows": 0, "artifact_sha256": {artifact.name: sha(artifact)}}
        (root / "GLOBAL_FREEZE.json").write_text(json.dumps(value), encoding="utf-8")
        return artifact, value

    def test_valid_manifest_checks_complete_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, value = self.frozen_fixture(root)
            with patch.object(freeze_batch, "ROOT", root):
                self.assertEqual(freeze_batch.validate_global_freeze(), value)

    def test_status_alone_cannot_pass_mutated_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact, _ = self.frozen_fixture(root)
            artifact.write_bytes(b"changed bytes")
            with patch.object(freeze_batch, "ROOT", root):
                with self.assertRaisesRegex(RuntimeError, "GLOBAL_FROZEN_ARTIFACT_CHANGED"):
                    freeze_batch.validate_global_freeze()

    def test_native_entry_rejects_hash_drift_before_any_2026_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact, _ = self.frozen_fixture(root)
            artifact.write_bytes(b"changed bytes")
            with patch.object(trainer, "ROOT", root), patch.object(freeze_batch, "ROOT", root), \
                 patch.object(trainer, "verify_design"), patch.object(trainer, "implementation_lock") as lock, \
                 patch.object(trainer.pd, "read_parquet", side_effect=AssertionError("2026 read")) as read_frame:
                with self.assertRaisesRegex(RuntimeError, "GLOBAL_FROZEN_ARTIFACT_CHANGED"):
                    trainer.predict_final()
                lock.assert_not_called()
                read_frame.assert_not_called()

    def test_saved_entry_rejects_hash_drift_before_loading_models(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact, _ = self.frozen_fixture(root)
            artifact.write_bytes(b"changed bytes")
            with patch.object(freeze_batch, "ROOT", root), patch.object(sys, "argv", ["predict_saved.py", "--predict-final"]), \
                 patch.object(predict_saved, "patch_binding") as binding, patch.object(trainer, "predict_final") as predict:
                with self.assertRaisesRegex(RuntimeError, "GLOBAL_FROZEN_ARTIFACT_CHANGED"):
                    predict_saved.main()
                binding.assert_not_called()
                predict.assert_not_called()

    def test_missing_freeze_rejects_before_any_2026_read(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(trainer, "ROOT", Path(directory)), patch.object(trainer, "verify_design"), \
                 patch.object(trainer.pd, "read_parquet") as read_frame:
                with self.assertRaisesRegex(RuntimeError, "GLOBAL_FREEZE_REQUIRED"):
                    trainer.predict_final()
                read_frame.assert_not_called()

    def test_original_learning_and_inference_bindings_retained(self):
        with patch.object(trainer.native.NativeBundle, "fit", side_effect=AssertionError("fit forbidden")):
            lock = trainer.implementation_lock()
            binding = predict_saved.patch_binding()
        self.assertEqual(lock["source_sha256"][str(trainer.ROOT / "train_models.py")],
                         trainer.sealed_source_sha(trainer.ROOT / "train_models.py"))
        self.assertEqual(binding["inference_patch_sha256"], trainer.sealed_source_sha(trainer.ROOT / "predict_saved.py"))

    def test_direct_final_prediction_uses_saved_single_job_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frame = pd.DataFrame({"signal_date": pd.to_datetime(["2026-01-05"]), "ticker": ["SYNTHETIC"]})
            bundle = Mock()
            bundle.predict.return_value = pd.DataFrame({"mu": [.001], "sigma": [.02], "p_up": [.5],
                                                       "q10": [-.02], "q50": [0.], "q90": [.02]})
            fitted = {"status": "PASS", "artifact_sha256": "synthetic_hash", "cutoff_exclusive": "2026-01-01"}
            with patch.object(trainer, "MODELS", root / "models"), patch.object(trainer, "PREDICTIONS", root / "predictions"), \
                 patch.object(trainer, "read", return_value=fitted), patch.object(trainer, "sha", return_value="synthetic_hash"), \
                 patch.object(trainer, "atomic_json"), patch.object(trainer, "atomic_parquet"), \
                 patch.object(predict_saved, "deterministic_load", return_value=bundle) as saved_load, \
                 patch.object(trainer.native.NativeBundle, "load", side_effect=AssertionError("uncontrolled loader")):
                receipt = trainer.predict_member("final", "rf", frame)
                saved_load.assert_called_once()
                self.assertEqual(receipt["inference_jobs_override"], 1)

    def test_amendment_cannot_hide_live_or_baseline_source_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            models = root / "models"
            models.mkdir()
            current, snapshot = root / "train_models.py", models / "before.txt"
            current.write_bytes(b"gate source")
            snapshot.write_bytes(b"original learning source")
            original_hash = sha(snapshot)
            record = {"after_sha256": sha(current), "before_snapshot": "models/before.txt", "before_sha256": original_hash}
            (models / "ZERO_FIT_GATE_AMENDMENT.json").write_text(json.dumps({"new_fit_calls": 0,
                "learning_functions_unchanged": True, "source_changes": {"train_models.py": record}}), encoding="utf-8")
            with patch.object(trainer, "ROOT", root), patch.object(trainer, "MODELS", models):
                self.assertEqual(trainer.sealed_source_sha(current), original_hash)
                current.write_bytes(b"unrecorded code change")
                with self.assertRaisesRegex(RuntimeError, "ZERO_FIT_GATE_AMENDMENT_SOURCE_DRIFT"):
                    trainer.sealed_source_sha(current)
                current.write_bytes(b"gate source")
                snapshot.write_bytes(b"altered baseline")
                with self.assertRaisesRegex(RuntimeError, "ZERO_FIT_GATE_AMENDMENT_SOURCE_DRIFT"):
                    trainer.sealed_source_sha(current)


if __name__ == "__main__":
    unittest.main()
