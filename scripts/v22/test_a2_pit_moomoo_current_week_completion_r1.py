from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from pathlib import Path

import pandas as pd
import pytest


SOURCE = Path(__file__).with_name("a2_pit_moomoo_current_week_completion_r1.py")
SPEC = importlib.util.spec_from_file_location("a2_current_week_r1_tested", SOURCE)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_cutoff_is_frozen_before_august_19_close() -> None:
    assert str(MODULE.FIXED_CUTOFF.date()) == "2026-08-18"


def test_planned_ranges_request_only_prefix_and_suffix() -> None:
    member = {"required_history_start": "2020-01-01"}
    frame = pd.DataFrame({"date": pd.to_datetime(["2020-02-03", "2026-08-01"])})
    assert MODULE.planned_ranges(member, frame) == [
        ("2020-01-01", "2020-02-02"),
        ("2026-08-02", "2026-08-18"),
    ]


def test_normalizer_rejects_invalid_prices() -> None:
    bad = pd.DataFrame({
        "date": ["2026-08-18"], "open": [1.0], "high": [1.0], "low": [0.0],
        "close": [1.0], "volume": [1], "turnover": [1.0],
    })
    with pytest.raises(RuntimeError, match="INVALID_OHLCV"):
        MODULE.normalize_frame(bad, "TEST", "US.TEST", "TEST")


def test_all_declared_final_statuses_are_terminal() -> None:
    required = {
        "COMPLETE_TO_FIXED_CUTOFF", "PARTIAL_MISSING_HISTORY", "EMPTY_RESPONSE_CONFIRMED",
        "UNKNOWN_SECURITY", "UNSUPPORTED_SECURITY", "UNSUPPORTED_OTC",
        "INVALID_HISTORICAL_MAPPING", "OTHER_HARD_FAILURE",
    }
    assert MODULE.TERMINAL == required


def test_ge_when_issued_mapping_is_corrected_at_identity_boundary() -> None:
    frozen = pd.DataFrame([{
        "security_id": "369604301", "ticker": "GE.WI",
        "moomoo_transport_code": "US.GE.WI", "mapping_status": "RESOLVED",
        "mapping_source": "V11_MOOMOO", "mapping_confidence": "EXISTING",
    }])
    corrected = MODULE.apply_security_identity_overrides(frozen)
    assert frozen.iloc[0].ticker == "GE.WI"  # immutable input was not mutated
    assert corrected.iloc[0].ticker == "GE"
    assert corrected.iloc[0].moomoo_transport_code == "US.GE"
    assert corrected.iloc[0].mapping_source == "A2_CUSIP_IDENTITY_OVERRIDE_R1"
    assert corrected.iloc[0].mapping_confidence == "CUSIP_VERIFIED"


def sunb_fixture() -> pd.DataFrame:
    dates = pd.bdate_range(end="2026-08-21", periods=121)
    return pd.DataFrame({"date": dates, "ticker": "SUNB", "close": 10.0, "volume": 100.0})


def test_sunb_asof_boundary_is_120_then_121() -> None:
    frame = sunb_fixture()
    aug20 = MODULE.asof_feature_readiness(frame, "2026-08-20")
    aug21 = MODULE.asof_feature_readiness(frame, "2026-08-21")
    assert aug20["observation_count_asof"] == 120
    assert aug20["model_safe"] is False
    assert aug21["observation_count_asof"] == 121
    assert aug21["model_safe"] is True


def test_future_rows_cannot_rescue_historical_readiness() -> None:
    frame = sunb_fixture()
    base = frame.loc[frame.date.le("2026-08-20")]
    future_augmented = pd.concat([
        frame,
        pd.DataFrame({"date": pd.to_datetime(["2026-08-24"]), "ticker": "SUNB", "close": 11.0, "volume": 101.0}),
    ], ignore_index=True)
    assert MODULE.asof_feature_readiness(base, "2026-08-20")["model_safe"] is False
    assert MODULE.asof_feature_readiness(future_augmented, "2026-08-20")["model_safe"] is False


def test_observation_count_and_feature_input_dates_are_asof_bounded() -> None:
    result = MODULE.asof_feature_readiness(sunb_fixture(), "2026-08-20")
    assert result["observation_count_asof"] == 120
    assert result["feature_input_max_date"] == "2026-08-20"
    assert result["asof_rows_used_max_date"] == "2026-08-20"
    assert result["local_data_extends_beyond_asof"] is True


def test_missing_asof_date_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="ASOF_DATE_REQUIRED"):
        MODULE.asof_feature_readiness(sunb_fixture(), None)


def test_explicit_current_mode_preserves_operational_latest_behavior() -> None:
    used, audit = MODULE.asof_history_window(sunb_fixture(), None, current_mode=True)
    assert len(used) == 121
    assert audit["as_of_date"] == "2026-08-21"
    assert audit["current_mode"] is True


def test_authoritative_coverage_masks_raw_qfq_and_future_rows() -> None:
    qfq = sunb_fixture()
    raw = qfq.tail(2).copy()
    result = MODULE.authoritative_model_safe_coverage(raw, qfq, ["SUNB"], "2026-08-20")
    assert result["model_safe_count"] == 0
    assert result["rows"][0]["observation_count_asof"] == 120
    assert result["max_used_date"] == "2026-08-20"
    assert result["local_data_extends_beyond_asof"] is True


def make_queue() -> tuple[Path, Path, Path, str]:
    root = Path(r"D:\us-tech-quant-cache") / f"a2_queue_test_{uuid.uuid4().hex}"
    root.mkdir(parents=False, exist_ok=False)
    queue = root / "queue.csv"
    rows = [{
        "security_id": f"SID{i:03d}", "symbol": f"S{i:03d}", "moomoo_code": f"US.S{i:03d}",
        "fetch_priority": "P2_FULL_HISTORY", "queue_reason": "FAIL_MOOMOO_WEEKLY_QUOTA_DEFERRED",
    } for i in range(42)]
    pd.DataFrame(rows).to_csv(queue, index=False, lineterminator="\n")
    manifest = root / "queue_manifest.json"
    manifest.write_text(json.dumps({
        "queue_count": 42,
        "queue_file_sha256": MODULE.sha256(queue),
        "security_id_set_sha256": MODULE.frozen_queue_security_id_hash(rows),
    }, sort_keys=True), encoding="utf-8")
    return root, queue, manifest, MODULE.sha256(manifest)


def clean_queue(root: Path) -> None:
    for path in root.iterdir():
        path.unlink()
    root.rmdir()


def test_frozen_queue_loader_validates_42_unique_ordered_members() -> None:
    root, queue, manifest, digest = make_queue()
    try:
        result = MODULE.load_frozen_backfill_queue(queue, manifest, digest)
        assert result["status"] == "PASS"
        assert result["queue_count"] == 42
        assert len(set(result["execution_order"])) == 42
    finally:
        clean_queue(root)


def test_frozen_queue_dry_parse_invokes_no_moomoo() -> None:
    root, queue, manifest, digest = make_queue()
    try:
        assert MODULE.load_frozen_backfill_queue(queue, manifest, digest)["moomoo_api_request_count"] == 0
    finally:
        clean_queue(root)


def test_frozen_queue_manifest_hash_mismatch_fails_closed() -> None:
    root, queue, manifest, _digest = make_queue()
    try:
        with pytest.raises(RuntimeError, match="QUEUE_MANIFEST_HASH_MISMATCH"):
            MODULE.load_frozen_backfill_queue(queue, manifest, "0" * 64)
    finally:
        clean_queue(root)


def test_frozen_queue_rejects_non_quota_case() -> None:
    root, queue, manifest, _digest = make_queue()
    try:
        frame = pd.read_csv(queue, dtype=str)
        frame.loc[0, "queue_reason"] = "FAIL_PROVIDER_AVAILABILITY"
        frame.to_csv(queue, index=False, lineterminator="\n")
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["queue_file_sha256"] = MODULE.sha256(queue)
        manifest.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        with pytest.raises(RuntimeError, match="QUEUE_REASON_NOT_QUOTA_DEFERRED"):
            MODULE.load_frozen_backfill_queue(queue, manifest, MODULE.sha256(manifest))
    finally:
        clean_queue(root)
