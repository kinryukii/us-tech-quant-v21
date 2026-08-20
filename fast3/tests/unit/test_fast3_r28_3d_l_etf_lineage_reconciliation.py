import importlib.util
from pathlib import Path

SOURCE = Path(__file__).parents[2] / "scripts" / "run" / "fast3_r28_3d_l_etf_lineage_reconciliation.py"
SPEC = importlib.util.spec_from_file_location("r28_3d_l", SOURCE)
AUDIT = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(AUDIT)


def record(symbol="SOXL", key="2024-01", digest="a", rows=3, lo="2024-01-01", hi="2024-01-02", schema="s", path="symbol=SOXL/year=2024/month=01/data.parquet"):
    return {"symbol": symbol, "partition_key": key, "source_path": path, "normalized_path": path, "file_sha256": digest, "row_count": rows, "min_timestamp": lo, "max_timestamp": hi, "schema_fingerprint": schema}


def test_no_model_or_economic_execution_surface():
    text = SOURCE.read_text(encoding="utf-8")
    assert ".fit(" not in text and "predict_proba" not in text and "placebo(" not in text
    assert "construct_payoffs" not in text and "fast3_r28_3d_frozen_target_aligned_translation" not in text


def test_path_and_ordering_only_drift_classes():
    a, b = record(), record(path="X/data.parquet")
    assert AUDIT.classify_pair(a, b) == "A_PATH_REPRESENTATION_ONLY"
    assert AUDIT.classify_pair(a, record()) == "B_ORDERING_OR_SERIALIZATION_ONLY"


def test_content_row_timestamp_and_schema_changes_are_detected():
    a = record()
    assert AUDIT.classify_pair(a, record(digest="b")) == "F_FILE_CONTENT_HASH_CHANGED"
    assert AUDIT.classify_pair(a, record(rows=4)) == "G_ROW_COUNT_CHANGED"
    assert AUDIT.classify_pair(a, record(lo="2024-01-01T01:00")) == "H_TIMESTAMP_BOUNDS_CHANGED"
    assert AUDIT.classify_pair(a, record(schema="other")) == "I_SCHEMA_CHANGED"


def test_missing_and_added_partitions_are_detected():
    rows, identity = AUDIT.comparison([record()], [record(), record(symbol="SOXS", key="2024-02")])
    assert any(x["difference_class"] == "D_PARTITION_ADDED" for x in rows)
    assert identity["underlying_partition_set_identity"] is False


def test_bridge_evidence_is_denied_when_historical_manifest_is_absent():
    rows, identity = AUDIT.comparison(None, [record()])
    assert rows[0]["difference_class"] == "J_UNKNOWN"
    assert identity["underlying_content_identity"] == "UNKNOWN"
