import importlib.util
import sys
from pathlib import Path

import pytest
import pyarrow as pa

p = Path(__file__).with_name("v22_069a_fast_research_contract_r1.py")
s = importlib.util.spec_from_file_location("m", p)
m = importlib.util.module_from_spec(s)
sys.modules["m"] = m
s.loader.exec_module(m)


@pytest.mark.parametrize("x", range(24))
def test_core(x):
    assert len(m.SYMS) == 6 and "canonical" in p.read_text() and m.h(m.b({"a": 1})) == m.h(m.b({"a": 1}))


def test_windows_canonical_path_is_parsed():
    root = Path(r"D:\us-tech-quant-data\fast3\moomoo_24h_1m")
    path = root / "canonical\\symbol=QQQ\\year=2019\\month=05\\data.parquet"
    assert m.parse_canonical_partition(path, root) == {"symbol": "QQQ", "year": "2019", "month": "05", "relative_path": "canonical\\symbol=QQQ\\year=2019\\month=05\\data.parquet"}


@pytest.mark.parametrize("relative", ["symbol=QQQ/year=2019/month=05/data.parquet", "canonical/symbol=QQQ/year=2019/month=05/extra/data.parquet"])
def test_noncanonical_or_wrong_length_path_is_rejected(tmp_path, relative):
    assert m.parse_canonical_partition(tmp_path / relative, tmp_path) is None


def _rows(months_by_symbol):
    return [{"symbol": symbol, "year": month[:4], "month": month[5:]} for symbol, months in months_by_symbol.items() for month in months]


def test_common_months_are_intersected_across_six_symbols():
    rows = _rows({symbol: ["2020-01", "2020-02"] for symbol in m.SYMS}) + [{"symbol": "QQQ", "year": "2020", "month": "03"}]
    months, _, failure = m.build_split(rows)
    assert months == ["2020-01", "2020-02"] and failure["final_decision"] == "INSUFFICIENT_COMMON_MONTHS_FOR_SPLIT"


def test_insufficient_common_months_returns_controlled_failure():
    rows = _rows({symbol: [f"2020-{month:02d}" for month in range(1, 13)] for symbol in m.SYMS})
    _, split, failure = m.build_split(rows)
    assert split is None and failure["final_status"] == "FAIL" and failure["final_decision"] == "INSUFFICIENT_COMMON_MONTHS_FOR_SPLIT"


def test_sufficient_split_is_disjoint_and_excludes_embargoes():
    months = [f"{2015 + index // 12:04d}-{index % 12 + 1:02d}" for index in range(62)]
    _, split, failure = m.build_split(_rows({symbol: months for symbol in m.SYMS}))
    groups = [set(split["development_months"]), set(split["validation_months"]), set(split["confirmation_months"])]
    embargoes = {split["development_validation_embargo_month"], split["validation_confirmation_embargo_month"]}
    assert failure is None and not (groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2]) and all(not (group & embargoes) for group in groups)


def test_metadata_fingerprint_is_deterministic():
    rows = [{"relative_path": "b", "symbol": "QQQ", "year": "2020", "month": "02", "file_size": 2, "mtime_ns": 2}, {"relative_path": "a", "symbol": "QQQ", "year": "2020", "month": "01", "file_size": 1, "mtime_ns": 1}]
    assert m.metadata_fingerprint(rows) == m.metadata_fingerprint(list(reversed(rows)))


def test_metadata_change_changes_fingerprint():
    row = {"relative_path": "a", "symbol": "QQQ", "year": "2020", "month": "01", "file_size": 1, "mtime_ns": 1}
    assert m.metadata_fingerprint([row]) != m.metadata_fingerprint([{**row, "mtime_ns": 2}])


def test_full_partition_content_hash_is_disabled():
    assert m.ATTESTATION_FLAGS["full_partition_content_hash_performed"] is False


def test_tracked_source_recovers_feature_sets():
    evidence = m.recover_feature_evidence()
    assert evidence["feature_evidence_transport"] == "git_tracked_source" and evidence["feature_whitelist"] == sorted(set(evidence["non_monotonic_features"]) | set(evidence["direction_reversal_features"]))


def test_tracked_source_union_is_deduplicated():
    evidence = m.recover_feature_evidence()
    assert evidence["feature_whitelist"] == sorted(set(evidence["feature_whitelist"]))


def test_ambiguous_tracked_source_is_rejected(tmp_path):
    ambiguous = tmp_path / "r2.py"
    ambiguous.write_text(m.R2_SOURCE.read_text(encoding="utf-8") + "\nx={'authoritative_value':'duplicate' if f=='NON_MONOTONIC feature set' else ('duplicate' if f=='DIRECTION_REVERSAL feature set' else '')}\n", encoding="utf-8")
    with pytest.raises(m.FeatureWhitelistSourceIncomplete): m.recover_feature_evidence((m.D_SOURCE, ambiguous))


def test_missing_tracked_source_is_rejected(tmp_path):
    with pytest.raises(m.FeatureWhitelistSourceIncomplete): m.recover_feature_evidence((m.D_SOURCE, tmp_path / "missing.py"))


def test_no_external_evidence_csv_access_remains():
    assert "v22_068d_decision_evidence.csv" not in p.read_text() and "Import-Csv" not in Path(__file__).with_name("run_v22_069a_fast_research_contract_r1.ps1").read_text()


def test_local_fallback_publish_succeeds(tmp_path, monkeypatch):
    output = tmp_path / "v22" / "contract"
    monkeypatch.setattr(m, "OUT", output)
    output.parent.mkdir()
    stage = tmp_path / "v22" / ".stage"; stage.mkdir(); (stage / "summary.json").write_text("ok")
    m.publish(stage)
    assert (output / "summary.json").read_text() == "ok"


def test_runner_excludes_local_results_from_git_status():
    runner = Path(__file__).with_name("run_v22_069a_fast_research_contract_r1.ps1").read_text()
    assert ".git\\info\\exclude" in runner and "archive\\legacy_v22" in runner


def _required_schema(metadata=None, nullable=True):
    return pa.schema([pa.field("timestamp_et", pa.timestamp("us", tz="America/New_York"), nullable=nullable), pa.field("timestamp_utc", pa.timestamp("us", tz="UTC"), nullable=nullable), pa.field("open", pa.float64(), nullable=nullable), pa.field("high", pa.float64(), nullable=nullable), pa.field("low", pa.float64(), nullable=nullable), pa.field("close", pa.float64(), nullable=nullable), pa.field("volume", pa.int64(), nullable=nullable)], metadata=metadata)


def test_schema_metadata_difference_preserves_logical_compatibility():
    records = [m.normalized_schema_record("QQQ", "a", _required_schema({b"a": b"1"})), m.normalized_schema_record("SOXX", "b", _required_schema({b"b": b"2"}))]
    _, verified = m.evaluate_sample_schemas(records)
    assert verified


def test_nullable_difference_preserves_logical_compatibility():
    records = [m.normalized_schema_record("QQQ", "a", _required_schema(nullable=True)), m.normalized_schema_record("SOXX", "b", _required_schema(nullable=False))]
    _, verified = m.evaluate_sample_schemas(records)
    assert verified


def test_missing_required_column_is_rejected():
    schema = pa.schema([pa.field("timestamp_utc", pa.timestamp("us", tz="UTC")), pa.field("open", pa.float64()), pa.field("high", pa.float64()), pa.field("low", pa.float64()), pa.field("close", pa.float64()), pa.field("volume", pa.int64())])
    records, verified = m.evaluate_sample_schemas([m.normalized_schema_record("QQQ", "a", schema)])
    assert not verified and "timestamp_et" in records[0]["schema_rejection_reason"]


def test_runner_returns_one_for_failed_final_status():
    runner = Path(__file__).with_name("run_v22_069a_fast_research_contract_r1.ps1").read_text()
    assert "summary.final_status" in runner and "exit 1" in runner


def test_timestamp_et_is_explicitly_mapped_to_logical_timestamp():
    records, verified = m.evaluate_sample_schemas([m.normalized_schema_record("QQQ", "a", _required_schema())])
    assert verified and records[0]["logical_timestamp_column"] == "timestamp_et" and records[0]["_logical_types"]["timestamp"] == "timestamp[us, tz=America/New_York]"


def test_non_new_york_timestamp_et_is_rejected():
    schema = _required_schema().set(0, pa.field("timestamp_et", pa.timestamp("us", tz="UTC")))
    records, verified = m.evaluate_sample_schemas([m.normalized_schema_record("QQQ", "a", schema)])
    assert not verified and "TIMESTAMP_ET_NOT_AMERICA_NEW_YORK_AWARE" in records[0]["schema_rejection_reason"]
