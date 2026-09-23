#!/usr/bin/env python
"""Tests for V20.169 DATA_TRUST direct ticker-level mapping repair."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_169_data_trust_direct_ticker_level_mapping_repair.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUT_SCAN = FACTORS / "V20_169_DATA_TRUST_DIRECT_MAPPING_SOURCE_SCAN.csv"
OUT_MAPPING = FACTORS / "V20_169_DATA_TRUST_DIRECT_TICKER_MAPPING.csv"
OUT_STATUS = FACTORS / "V20_169_DATA_TRUST_DIRECT_PASS_FAIL_STATUS.csv"
OUT_REPAIR = FACTORS / "V20_169_DATA_TRUST_DIRECT_MAPPING_REPAIR_AUDIT.csv"
OUT_BACKLOG = FACTORS / "V20_169_DATA_TRUST_DIRECT_MAPPING_REMAINING_BACKLOG.csv"
OUT_SUMMARY = FACTORS / "V20_169_DATA_TRUST_DIRECT_MAPPING_COVERAGE_SUMMARY.csv"
OUT_GATE = FACTORS / "V20_169_DATA_TRUST_DIRECT_MAPPING_NEXT_GATE.csv"
OUT_SAFETY = FACTORS / "V20_169_DATA_TRUST_DIRECT_MAPPING_SAFETY_AUDIT.csv"
OUT_REPORT = READ_CENTER / "V20_169_DATA_TRUST_DIRECT_TICKER_LEVEL_MAPPING_REPAIR_REPORT.md"
OUTPUTS = [OUT_SCAN, OUT_MAPPING, OUT_STATUS, OUT_REPAIR, OUT_BACKLOG, OUT_SUMMARY, OUT_GATE, OUT_SAFETY, OUT_REPORT]

PASS_STATUS = "PASS_V20_169_DATA_TRUST_DIRECT_MAPPING_READY_FOR_V20_170"
PARTIAL_STATUS = "PARTIAL_PASS_V20_169_DATA_TRUST_DIRECT_MAPPING_WITH_REMAINING_UNKNOWN_READY_FOR_V20_170"
WARN_STATUS = "WARN_V20_169_NO_DIRECT_TICKER_LEVEL_DATA_TRUST_MAPPING_RECOVERED"
BLOCKED_STATUS = "BLOCKED_V20_169_DATA_TRUST_DIRECT_TICKER_LEVEL_MAPPING_REPAIR"
SAFETY_FALSE_FIELDS = [
    "formal_activation_allowed",
    "promotion_ready",
    "official_recommendation_created",
    "official_ranking_mutated",
    "official_weight_change_created",
    "official_weight_registry_mutated",
    "weight_mutated",
    "real_book_action_created",
    "trade_action_created",
    "broker_execution_supported",
    "performance_claim_created",
    "shadow_weight_expansion_allowed",
]
MAPPING_COLUMNS = {
    "ticker",
    "baseline_rank",
    "prior_inferred_data_trust_status",
    "direct_data_trust_status",
    "direct_data_trust_pass",
    "direct_data_trust_fail",
    "direct_data_trust_unknown",
    "direct_mapping_found",
    "direct_mapping_source_artifact",
    "direct_mapping_source_field",
    "ticker_identity_match",
    "freshness_status",
    "source_quality_status",
    "pit_safety_status",
    "schema_status",
    "factor_score_availability_status",
    "price_availability_status",
    "current_ranking_eligibility_status",
    "direct_mapping_confidence",
    "direct_failure_category",
    "direct_failure_reason",
    "repair_required",
    "recommended_repair_action",
}
SCAN_COLUMNS = {
    "source_artifact",
    "artifact_exists",
    "row_count",
    "has_ticker_column",
    "ticker_column_name",
    "has_data_trust_status_field",
    "has_freshness_field",
    "has_source_quality_field",
    "has_pit_safety_field",
    "has_schema_status_field",
    "has_factor_score_availability_field",
    "direct_mapping_usable",
    "limitation_reason",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    assert rows
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def upstream_hashes() -> dict[Path, str]:
    paths = [
        FACTORS / "V20_168_DATA_TRUST_GATE_ONLY_OPERATOR_DECISION_CAPTURE.csv",
        FACTORS / "V20_168_DATA_TRUST_GATE_ONLY_DECISION_GATE.csv",
        FACTORS / "V20_168_DATA_TRUST_GATE_ONLY_DECISION_SAFETY_AUDIT.csv",
        FACTORS / "V20_168_DATA_TRUST_DIRECT_MAPPING_REQUIREMENT_PACKET.csv",
        FACTORS / "V20_168_DATA_TRUST_NEXT_STAGE_PACKET.csv",
        CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
        FACTORS / "V20_166_R1_DATA_TRUST_STATUS_SOURCE_MAPPING.csv",
        FACTORS / "V20_166_R1_DATA_TRUST_TICKER_STATUS.csv",
        FACTORS / "V20_166_R1_DATA_TRUST_STATUS_REPAIR_AUDIT.csv",
        FACTORS / "V20_166_R1_DATA_TRUST_REMAINING_UNKNOWN_BACKLOG.csv",
        FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_MAPPING_CONFIDENCE_AUDIT.csv",
        FACTORS / "V20_166_R3_MAPPING_CONFIDENCE_LIMITATION_AUDIT.csv",
        FACTORS / "V20_167_DATA_TRUST_MAPPING_LIMITATION_REVIEW.csv",
    ]
    return {path: digest(path) for path in paths if path.exists()}


def load_module():
    spec = importlib.util.spec_from_file_location("v20_169_direct_mapping_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    module.OUTPUTS = temp
    module.CONSOLIDATION = temp / "consolidation"
    module.FACTORS = temp / "factors"
    module.BACKTEST = temp / "backtest"
    module.READ_CENTER = temp / "read_center"
    for name in [
        "V168_DECISION", "V168_GATE", "V168_SAFETY", "V168_DIRECT_REQ", "V168_NEXT",
        "R1_SOURCE_MAPPING", "R1_TICKER_STATUS", "R1_REPAIR", "R1_UNKNOWN",
        "R2_MAPPING", "R3_MAPPING", "V167_MAPPING",
    ]:
        setattr(module, name, module.FACTORS / getattr(module, name).name)
    module.BASELINE = module.CONSOLIDATION / module.BASELINE.name
    module.NAMED_SOURCE_CANDIDATES = [module.FACTORS / "DIRECT_SOURCE.csv"]
    for name in [
        "OUT_SCAN", "OUT_MAPPING", "OUT_STATUS", "OUT_REPAIR", "OUT_BACKLOG",
        "OUT_SUMMARY", "OUT_GATE", "OUT_SAFETY",
    ]:
        setattr(module, name, module.FACTORS / getattr(module, name).name)
    module.REPORT = module.READ_CENTER / module.REPORT.name


def write_common_inputs(module, status_ok: bool = True) -> None:
    status = "PASS_V20_168_DATA_TRUST_GATE_ONLY_OPERATOR_DECISION_CAPTURE_READY_FOR_V20_169" if status_ok else "WARN"
    write_csv(module.V168_DECISION, [{"data_trust_gate_only_research_policy_approved": "TRUE"}])
    write_csv(module.V168_GATE, [{
        "final_status": status,
        "data_trust_scoring_weight": "0.0000000000",
        "data_trust_role": "GATE_ONLY_AND_REPAIR_DIAGNOSTIC",
        "data_trust_gate_only_research_policy_approved": "TRUE",
        "direct_ticker_mapping_required_before_official_use": "TRUE",
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "formal_activation_allowed": "FALSE",
    }])
    write_csv(module.V168_SAFETY, [{"safety_check_id": "S"}])
    write_csv(module.V168_DIRECT_REQ, [{"direct_ticker_mapping_required_before_official_use": "TRUE"}])
    write_csv(module.V168_NEXT, [{"next_stage_packet_id": "N"}])
    write_csv(module.BASELINE, [
        {"ticker": "AAA", "official_current_rank": "1"},
        {"ticker": "BBB", "official_current_rank": "2"},
    ])
    write_csv(module.R1_SOURCE_MAPPING, [{"mapping_id": "M"}])
    write_csv(module.R1_TICKER_STATUS, [
        {"ticker": "AAA", "data_trust_status": "PASS", "data_trust_pass": "TRUE"},
        {"ticker": "BBB", "data_trust_status": "PASS", "data_trust_pass": "TRUE"},
    ])
    write_csv(module.R1_REPAIR, [{"repair_audit_id": "R"}])
    write_csv(module.R1_UNKNOWN, [{"ticker": "NONE"}])
    write_csv(module.R2_MAPPING, [{"mapping_confidence": "INFERRED"}])
    write_csv(module.R3_MAPPING, [{"mapping_review_id": "R3"}])
    write_csv(module.V167_MAPPING, [{"mapping_review_id": "V167"}])


def write_direct_source(module, include_bbb: bool = False) -> None:
    rows = [{
        "ticker": "AAA",
        "data_trust_status": "PASS",
        "freshness_status": "PASS",
        "source_quality_status": "PASS",
        "pit_safety_status": "PASS",
        "schema_status": "PASS",
        "factor_score_availability_status": "PASS",
        "price_availability_status": "PASS",
        "current_ranking_eligibility_status": "PASS",
    }]
    if include_bbb:
        rows.append({
            "ticker": "BBB",
            "data_trust_status": "PASS",
            "freshness_status": "PASS",
            "source_quality_status": "PASS",
            "pit_safety_status": "PASS",
            "schema_status": "PASS",
            "factor_score_availability_status": "PASS",
            "price_availability_status": "PASS",
            "current_ranking_eligibility_status": "PASS",
        })
    write_csv(module.NAMED_SOURCE_CANDIDATES[0], rows)


def assert_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE in {row}"
        if "data_trust_scoring_weight" in row:
            assert row["data_trust_scoring_weight"] == "0.0000000000"
        if "data_trust_role" in row:
            assert row["data_trust_role"] == "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
        if "direct_ticker_mapping_required_before_official_use" in row:
            assert row["direct_ticker_mapping_required_before_official_use"] == "TRUE"


def test_blocked_missing_inputs_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == BLOCKED_STATUS


def test_blocked_wrong_v168_status_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_common_inputs(module, status_ok=False)
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == BLOCKED_STATUS


def test_temp_partial_direct_mapping_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_common_inputs(module)
        write_direct_source(module, include_bbb=False)
        assert module.main() == 0
        summary = read_csv(module.OUT_SUMMARY)[0]
        gate = read_csv(module.OUT_GATE)[0]
        mapping = read_csv(module.OUT_MAPPING)
        assert summary["direct_mapping_found_count"] == "1"
        assert summary["direct_data_trust_unknown_count"] == "1"
        assert summary["ready_for_direct_mapping_gate_only_ranking_simulation"] == "TRUE"
        assert gate["final_status"] == PARTIAL_STATUS
        assert any(row["ticker"] == "BBB" and row["direct_data_trust_unknown"] == "TRUE" for row in mapping)


def test_temp_full_direct_mapping_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_common_inputs(module)
        write_direct_source(module, include_bbb=True)
        assert module.main() == 0
        summary = read_csv(module.OUT_SUMMARY)[0]
        gate = read_csv(module.OUT_GATE)[0]
        assert summary["direct_mapping_coverage_rate"] == "1.0000000000"
        assert summary["direct_data_trust_unknown_count"] == "0"
        assert summary["ready_for_official_use"] == "FALSE"
        assert gate["final_status"] == PASS_STATUS


def test_data_trust_direct_ticker_level_mapping_repair() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.166-R1 through V20.168 outputs were mutated"
    stdout = result.stdout
    assert any(status in stdout for status in [PASS_STATUS, PARTIAL_STATUS, WARN_STATUS])
    for expected in [
        "V20_168_GATE_CONSUMED=TRUE",
        "DATA_TRUST_SCORING_WEIGHT=0.0000000000",
        "DATA_TRUST_ROLE=GATE_ONLY_AND_REPAIR_DIAGNOSTIC",
        "DATA_TRUST_GATE_ONLY_RESEARCH_POLICY_APPROVED=TRUE",
        "DIRECT_TICKER_MAPPING_REQUIRED_BEFORE_OFFICIAL_USE=TRUE",
        "BASELINE_CANDIDATE_COUNT=40",
        "PRIOR_INFERRED_PASS_COUNT=40",
        "READY_FOR_OFFICIAL_USE=FALSE",
        "OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE",
        "OFFICIAL_RANKING_MUTATION_ALLOWED=FALSE",
        "FORMAL_ACTIVATION_ALLOWED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "REAL_BOOK_ACTION_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
        "PERFORMANCE_CLAIM_CREATED=FALSE",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    scan = read_csv(OUT_SCAN)
    mapping = read_csv(OUT_MAPPING)
    status_rows = read_csv(OUT_STATUS)
    repair = read_csv(OUT_REPAIR)
    summary = read_csv(OUT_SUMMARY)
    gate = read_csv(OUT_GATE)
    safety = read_csv(OUT_SAFETY)
    assert scan and mapping and status_rows and repair and summary and gate and safety
    assert SCAN_COLUMNS.issubset(scan[0].keys()), SCAN_COLUMNS - set(scan[0].keys())
    assert MAPPING_COLUMNS.issubset(mapping[0].keys()), MAPPING_COLUMNS - set(mapping[0].keys())
    assert len(mapping) == 40
    assert len(status_rows) == 40
    assert summary[0]["ready_for_official_use"] == "FALSE"
    assert gate[0]["official_weight_change_allowed"] == "FALSE"
    assert gate[0]["official_ranking_mutation_allowed"] == "FALSE"
    assert gate[0]["inferred_mapping_not_treated_as_direct"] == "TRUE"
    assert all(row["safety_passed"] == "TRUE" for row in safety)
    for rows in [mapping, status_rows, gate, safety]:
        assert_safety(rows)
    assert "Inferred DATA_TRUST mapping is not treated as direct" in OUT_REPORT.read_text(encoding="utf-8")


if __name__ == "__main__":
    test_blocked_missing_inputs_case()
    test_blocked_wrong_v168_status_case()
    test_temp_partial_direct_mapping_case()
    test_temp_full_direct_mapping_case()
    test_data_trust_direct_ticker_level_mapping_repair()
    print("PASS_V20_169_DATA_TRUST_DIRECT_TICKER_LEVEL_MAPPING_REPAIR_TESTS")
