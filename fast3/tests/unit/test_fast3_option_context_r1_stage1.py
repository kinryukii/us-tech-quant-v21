import importlib.util
import sys
from pathlib import Path

import pandas as pd

p = Path(r"D:\us-tech-quant\fast3\src\fast3\options\option_context_r1_stage1.py")
s = importlib.util.spec_from_file_location("ctx", p); m = importlib.util.module_from_spec(s); sys.modules["ctx"] = m; s.loader.exec_module(m)


def test_native_manifest_is_stable_and_compact():
    a = m.factor_manifest("native", m.NATIVE_ROWS, "raw", "asof")
    assert a["sha256"] == m.factor_manifest("native", m.NATIVE_ROWS, "raw", "asof")["sha256"]
    assert len(m.NATIVE_ROWS) <= 20 and len({x[0] for x in m.NATIVE_ROWS}) == len(m.NATIVE_ROWS)


def test_reconciled_legacy_is_deterministic_and_semantically_unique():
    left, evidence = m.reconciled_legacy(); right, _ = m.reconciled_legacy()
    assert m.stable(left) == m.stable(right)
    assert len({row["factor_name"] for row in left}) == len(left)
    assert evidence["R29_FACTOR_MANIFEST_STATUS"].startswith("NOT_FOUND")


def test_native_snapshot_is_backward_only_under_future_mutation():
    frame = pd.DataFrame({"option_code": ["C", "P", "C", "P"], "timestamp": ["2026-01-02 10:00", "2026-01-02 10:00", "2026-01-02 10:05", "2026-01-02 10:05"], "call_put": ["CALL", "PUT", "CALL", "PUT"], "expiry": ["2026-01-09"] * 4, "strike": [1.0] * 4, "close": [2.0, 2.0, 99.0, 99.0], "volume": [3.0, 2.0, 999.0, 999.0], "turnover": [1.0] * 4})
    before = m.historical_native_snapshot(frame, "2026-01-02 10:00")
    frame.loc[frame.timestamp.gt("2026-01-02 10:00"), ["close", "volume"]] = -999.0
    after = m.historical_native_snapshot(frame, "2026-01-02 10:00")
    assert all((pd.isna(before[key]) and pd.isna(after[key])) or before[key] == after[key] for key in before)


def test_dst_aware_utc_conversion_uses_both_eastern_offsets():
    converted = m._utc_from_time_key(pd.Series(["2025-01-02 09:35:00", "2025-07-01 09:35:00"]))
    assert str(converted.iloc[0]) == "2025-01-02 14:35:00+00:00"
    assert str(converted.iloc[1]) == "2025-07-01 13:35:00+00:00"


def test_stage2_preflight_detects_frozen_t5_regression_metric_mismatch():
    audit = m.stage2_target_preflight()
    assert audit["identity_status"] == "PASS"
    assert audit["status"] == "STOP_CANONICAL_T5_METRIC_TARGET_TYPE_MISMATCH"


def test_stage2r_preflight_refuses_to_substitute_r32b_29_for_frozen_36():
    audit = m.stage2r_matrix_preflight()
    assert audit["required_legacy_count"] == 36
    assert audit["source_matrix_feature_count"] == 29
    assert audit["status"] == "STOP_FROZEN_36_LEGACY_FEATURE_MATRIX_UNAVAILABLE"


def test_stage2m_uses_only_documented_semantic_identity_and_fails_closed():
    audit = m.stage2m_semantic_diff()
    assert audit["OVERLAP_FACTOR_COUNT"] == 14
    assert audit["MISSING_FROM_29_FACTOR_COUNT"] == 22
    assert "kdj_j__delta_5m" in audit["MISSING_FROM_29_FACTOR_NAMES"]
    assert "KDJ_J_9_3" in audit["EXTRA_IN_29_FACTOR_NAMES"]
    assert audit["DOCUMENTED_ALIAS_PAIRS"] == []
    assert audit["missing_factor_audit"]["downside_vol_60m"]["classification"] == "A_EXACT_SOURCE_BUILDER_AVAILABLE"
    assert audit["missing_factor_audit"]["boll_z7"]["classification"] == "D_ONLY_HISTORICAL_REPORT_REFERENCE"
