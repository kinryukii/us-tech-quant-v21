from copy import deepcopy
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import patch

from moomoo_component.imports import DailyImportError, MODEL_SHA256, convert_daily, inspect_daily


NOW = datetime(2026, 9, 25, 15, 0, tzinfo=timezone.utc)


def source():
    return {
        "status": "READY", "model_id": "A2_HGB", "model_sha256": MODEL_SHA256,
        "broker_action_allowed": True, "run_id": "20260924_fixture", "data_date": "2026-09-24",
        "generated_at": "2026-09-24T21:00:00Z", "input_manifest_sha256": "a" * 64,
        "report_path": "fixture/report.json",
        "coverage": {"eligible_count": 20, "mapped_count": 20, "excluded_count": 0},
        "universe": {"status": "READY", "current": True, "inference_ready": True,
                     "target_date": "2026-09-24", "universe_id": "fixture-universe",
                     "coverage_status": "FULL_IDENTITY_COVERAGE", "mapping_gap_count": 0,
                     "mapping_gaps": [], "universe_member_count": 20},
        "rows": [{"ticker": f"T{i}", "security_id": f"{i:09d}", "rank": i, "score": 0.1,
                  "raw_target_weight": 0.05, "model_id": "A2_HGB", "target_date": "2026-09-24",
                  "universe_id": "fixture-universe", "source": "MOOMOO_OPEND_RAW_PLUS_REHAB"}
                 for i in range(1, 21)],
    }


class DailyBridgeTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch("moomoo_component.imports._now_utc", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def convert(self, payload=None, quantities=None, **kwargs):
        return convert_daily(payload if payload is not None else source(),
                             quantities if quantities is not None else {"US.T1": 2, "US.T2": 0},
                             kwargs.get("asof", "2026-09-24T21:00:00Z"),
                             kwargs.get("expires_at", "2026-09-25T20:30:00Z"))

    def test_preview_does_not_size_or_mutate_source(self):
        payload = source()
        original = deepcopy(payload)
        review = inspect_daily(payload)
        self.assertTrue(review["eligible_for_conversion"], review["rejection_reasons"])
        self.assertEqual(review["targets"][0]["weight"], 0.05)
        self.assertNotIn("target_qty", review["targets"][0])
        self.assertEqual(payload, original)

    def test_explicit_quantities_and_original_lineage_survive_conversion(self):
        manifest = self.convert(asof="2026-09-25T06:00:00+09:00")
        self.assertEqual(manifest["targets"], [{"code": "US.T1", "target_qty": 2}, {"code": "US.T2", "target_qty": 0}])
        self.assertEqual(manifest["asof"], "2026-09-24T21:00:00Z")
        lineage = json.loads(manifest["source"])
        self.assertEqual(lineage["data_date"], "2026-09-24")
        self.assertEqual(lineage["payload_sha256"], inspect_daily(source())["source_sha256"])
        self.assertEqual(lineage["quantities"], "explicit_caller_input")

    def test_ready_does_not_override_partial_coverage_or_source_prohibition(self):
        payload = source()
        payload["coverage"]["excluded_count"] = 71
        payload["universe"]["coverage_status"] = "PARTIAL_IDENTITY_COVERAGE"
        payload["broker_action_allowed"] = False
        review = inspect_daily(payload)
        self.assertIn("PARTIAL_COVERAGE", review["rejection_reasons"])
        self.assertIn("SOURCE_BROKER_ACTION_NOT_ALLOWED", review["rejection_reasons"])
        self.assertTrue(any("原系统" in item["message"] for item in review["rejection_details"]))
        self.assertFalse(review["eligible_for_conversion"])
        with self.assertRaises(DailyImportError):
            self.convert(payload)

    def test_historical_source_and_regenerated_old_data_are_rejected(self):
        payload = source()
        payload["source"] = "historical_replay"
        self.assertIn("HISTORICAL_OR_RESEARCH_SOURCE", inspect_daily(payload)["rejection_reasons"])
        payload = source()
        payload["data_date"] = "2026-09-23"
        self.assertIn("DATA_DATE_NOT_LATEST_COMPLETED_WEEKDAY", inspect_daily(payload)["rejection_reasons"])
        with self.assertRaisesRegex(DailyImportError, "ASOF_MUST_PRESERVE"):
            self.convert(asof="2026-09-25T15:00:00Z")

    def test_future_stale_and_timezone_less_source_timestamps_are_rejected(self):
        for stamp, reason in [("2026-09-26T01:00:00Z", "SOURCE_GENERATED_IN_FUTURE"),
                              ("2026-09-24T14:00:00Z", "SOURCE_GENERATED_TOO_OLD"),
                              ("2026-09-24T21:00:00", "SOURCE_GENERATED_TIMEZONE_REQUIRED")]:
            with self.subTest(stamp=stamp):
                payload = source()
                payload["generated_at"] = stamp
                self.assertIn(reason, inspect_daily(payload)["rejection_reasons"])

    def test_expiry_cannot_extend_source_freshness(self):
        for expiry in ("2026-09-25T21:00:01Z", "2026-09-25T14:59:00Z", "2026-09-25T20:00:00"):
            with self.subTest(expiry=expiry), self.assertRaises(DailyImportError):
                self.convert(expires_at=expiry)

    def test_bad_quantities_or_unrelated_symbols_are_rejected(self):
        for quantities in ({}, {"US.T1": True}, {"US.T1": 0.5}, {"US.T1": -1},
                           {"US.UNRELATED": 1}, {"US.T1": 1_000_001}):
            with self.subTest(quantities=quantities), self.assertRaises(DailyImportError):
                self.convert(quantities=quantities)

    def test_duplicate_identity_missing_weights_and_nan_cannot_be_converted(self):
        payload = source()
        payload["rows"][1]["security_id"] = payload["rows"][0]["security_id"]
        self.assertIn("DUPLICATE_SECURITY", inspect_daily(payload)["rejection_reasons"])
        payload = source()
        payload["rows"][0].pop("raw_target_weight")
        self.assertIn("INVALID_TARGET_WEIGHT", inspect_daily(payload)["rejection_reasons"])
        payload = source()
        payload["rows"][0]["score"] = float("nan")
        self.assertIn("SOURCE_NOT_FINITE_JSON", inspect_daily(payload)["rejection_reasons"])

    def test_missing_coverage_is_not_assumed_complete(self):
        payload = source()
        payload.pop("coverage")
        payload["universe"].pop("mapping_gap_count")
        review = inspect_daily(payload)
        self.assertIn("COVERAGE_METADATA_REQUIRED", review["rejection_reasons"])
        self.assertIn("IDENTITY_GAPS_OR_UNKNOWN", review["rejection_reasons"])

    def test_model_or_transport_alias_requires_a_separate_adapter(self):
        payload = source()
        payload["model_sha256"] = "b" * 64
        self.assertIn("UNRECOGNIZED_FROZEN_MODEL", inspect_daily(payload)["rejection_reasons"])
        payload = source()
        payload["rows"][0]["moomoo_transport_code"] = "US.UNRELATED"
        self.assertIn("SECURITY_TRANSPORT_IDENTITY_MISMATCH", inspect_daily(payload)["rejection_reasons"])

    def test_malformed_json_field_types_remain_a_blocked_preview(self):
        payload = source()
        payload["universe"]["coverage_status"] = {"unknown": True}
        payload["rows"][0]["security_id"] = ["invalid"]
        payload["rows"][0]["raw_target_weight"] = 10 ** 1000
        review = inspect_daily(payload)
        self.assertFalse(review["eligible_for_conversion"])
        self.assertIn("SECURITY_IDENTITY_REQUIRED", review["rejection_reasons"])
        self.assertIn("INVALID_TARGET_WEIGHT", review["rejection_reasons"])


if __name__ == "__main__":
    unittest.main()
