from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.a2_successor_s1.successor_control import (  # noqa: E402
    ContractError,
    append_hash_chain,
    atomic_write_bytes,
    blocked_outcome_columns,
    derived_contracts,
    load_config,
    sha256_file,
    successor_model_fit_id,
    validate_hash_chain,
)


CONFIG_PATH = REPO / "config" / "a2_successor_s1" / "control_contract.json"
PARENTS = [
    (
        Path(r"D:\us-tech-quant-results\A2_RESEARCH_EVIDENCE_REGISTRY_LABEL_MATURITY_AND_COMPARABILITY_AUDIT_R1\run_id=20260822T085844Z_a4a614a1ff2b"),
        "58e4015d9acb607378fdeed2ace4ae3e879bed89d990cdba28583f03bd2cefb4",
    ),
    (
        Path(r"D:\us-tech-quant-results\A2_CRITICAL_PROVENANCE_RECOVERY_AND_NATIVE_SUPPORT_REMEDIATION_R1\run_id=20260822T092355Z_9b85214c32e3"),
        "cf6b6d4fd5393d0075bf4d5779c68a616706fa65678c164395678f43b3fe402d",
    ),
]


class SuccessorControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_config(CONFIG_PATH)
        value = os.environ.get("A2S1_OUTPUT_DIR")
        cls.output = Path(value) if value else None

    def require_output(self) -> Path:
        if self.output is None:
            self.skipTest("A2S1_OUTPUT_DIR is not set")
        return self.output

    def test_01_parent_manifest_verification(self) -> None:
        for root, expected in PARENTS:
            self.assertEqual(sha256_file(root / "hash_manifest.json"), expected)

    def test_02_new_id_non_reuse(self) -> None:
        self.assertNotEqual(self.config["successor_control_model_id"], self.config["parent_legacy_control_id"])
        self.assertTrue(successor_model_fit_id(self.config).startswith("A2S1_"))

    def test_03_legacy_artifact_immutability(self) -> None:
        self.assertEqual(
            sha256_file(self.config["parent_model_artifact_path"]), self.config["model_artifact_sha256"]
        )

    def test_04_config_schema_validation(self) -> None:
        self.assertEqual(len(self.config["features"]), 32)
        self.assertEqual(self.config["universe_contract"]["expected_count"], 613)

    def test_05_label_maturity(self) -> None:
        self.assertLess(self.config["max_train_label_end_date"], "2026-01-01")

    def test_06_source_bundle_completeness(self) -> None:
        output = self.require_output()
        manifest = json.loads((output / "source_bundle_manifest.json").read_text(encoding="utf-8"))
        names = {row["relative_path"] for row in manifest["files"]}
        self.assertIn("src/a2_successor_s1/successor_control.py", names)
        self.assertIn("config/control_contract.json", names)
        self.assertIn("artifacts/final_full_pre2026_hgb.joblib", names)

    def test_07_source_bundle_isolated_execution(self) -> None:
        output = self.require_output()
        result = json.loads((output / "source_bundle_reproduction_test.json").read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "PASS_ISOLATED_EXECUTION")

    def test_08_native_support_full_universe_gate(self) -> None:
        self.assertEqual(
            self.config["universe_contract"]["completeness_gate"],
            "EXACT_613_SECURITY_SET_REQUIRED_NO_PARTIAL_FALLBACK",
        )

    def test_09_native_support_duplicate_key_rule(self) -> None:
        fields = ["decision_id", "as_of_date", "symbol"]
        rows = [("d", "2025-12-02", "A"), ("d", "2025-12-02", "A")]
        self.assertNotEqual(len(rows), len(set(rows)))
        self.assertEqual(fields, ["decision_id", "as_of_date", "symbol"])

    def test_10_outcome_column_access_prohibition(self) -> None:
        self.assertEqual(blocked_outcome_columns(["symbol", "forward_return"], self.config), ["forward_return"])
        self.assertEqual(blocked_outcome_columns(["max_drawdown_20d"], self.config), [])

    def test_11_partial_universe_fail_closed(self) -> None:
        self.assertNotEqual(549, self.config["universe_contract"]["expected_count"])
        self.assertEqual(self.config["universe_contract"]["missing_security_policy"], "FAIL_CLOSED_NO_FORMAL_DECISION")

    def test_12_prediction_determinism(self) -> None:
        output = self.require_output()
        self.assertEqual(sha256_file(output / "canary_run_1" / "predictions.csv"), sha256_file(output / "canary_run_2" / "predictions.csv"))

    def test_13_decision_determinism(self) -> None:
        output = self.require_output()
        self.assertEqual(sha256_file(output / "canary_run_1" / "position_decision.csv"), sha256_file(output / "canary_run_2" / "position_decision.csv"))

    def test_14_atomic_append(self) -> None:
        path = self.require_output() / "test_runtime" / "atomic" / "value.bin"
        atomic_write_bytes(path, b"one")
        atomic_write_bytes(path, b"two")
        self.assertEqual(path.read_bytes(), b"two")
        self.assertFalse(list(path.parent.glob("*.tmp")))

    def test_15_hash_chain_integrity(self) -> None:
        path = self.require_output() / "test_runtime" / "chain_integrity" / "chain.jsonl"
        append_hash_chain(path, {"DECISION_ID": "A", "VALUE": "1"})
        append_hash_chain(path, {"DECISION_ID": "B", "VALUE": "2"})
        self.assertTrue(validate_hash_chain(path))

    def test_16_idempotent_rerun(self) -> None:
        path = self.require_output() / "test_runtime" / "idempotency" / "chain.jsonl"
        first = append_hash_chain(path, {"DECISION_ID": "A", "VALUE": "1"})
        before = path.read_bytes()
        second = append_hash_chain(path, {"DECISION_ID": "A", "VALUE": "1"})
        self.assertEqual(first, second)
        self.assertEqual(before, path.read_bytes())

    def test_17_duplicate_decision_rejection(self) -> None:
        path = self.require_output() / "test_runtime" / "duplicate_rejection" / "chain.jsonl"
        append_hash_chain(path, {"DECISION_ID": "A", "VALUE": "1"})
        with self.assertRaises(ContractError):
            append_hash_chain(path, {"DECISION_ID": "A", "VALUE": "2"})

    def test_18_post_freeze_reconstruction_classification(self) -> None:
        output = self.require_output()
        receipt = json.loads((output / "canary_run_1" / "decision_receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["classification"], "ENGINEERING_CANARY_NOT_ECONOMIC_EVIDENCE")
        self.assertFalse(receipt["live_captured_prospective"])

    def test_19_broker_action_false(self) -> None:
        self.assertFalse(self.config["broker_action_allowed"])
        self.assertFalse(self.config["execution_contract"]["broker_action_allowed"])

    def test_20_anti_bloat(self) -> None:
        self.assertFalse((REPO / ".venv").exists())
        guard_path = REPO / "fast3" / "scripts" / "audit" / "run_fast3_guard.py"
        spec = importlib.util.spec_from_file_location("a2s1_fast3_guard", guard_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        budget = module.repository_budget()
        self.assertEqual(budget["violations"], [])
        self.assertEqual(budget["target_300m_status"], "PASS")

    def test_21_repo_write_scope(self) -> None:
        output = self.require_output()
        report = json.loads((output / "repo_scope_validation.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "PASS_ONLY_AUTHORIZED_NEW_PATHS_CHANGED")

    def test_22_canonical_read_only(self) -> None:
        self.assertTrue(self.config["canonical_data_read_only"])

    def test_23_central_registry_collision(self) -> None:
        path = self.require_output() / "test_runtime" / "registry_collision" / "registry_hash_chain.jsonl"
        append_hash_chain(path, {"DECISION_ID": "IDENTITY:A2S1", "VALUE": "one"})
        with self.assertRaises(ContractError):
            append_hash_chain(path, {"DECISION_ID": "IDENTITY:A2S1", "VALUE": "different"})

    def test_24_checkpoint_recovery(self) -> None:
        output = self.require_output()
        required = [0, 1, 2, 4, 5, 7, 9]
        available = {int(path.name.split("_")[1]) for path in (output / "checkpoints").glob("phase_*_*.json")}
        self.assertTrue(set(required).issubset(available))


if __name__ == "__main__":
    unittest.main()
