#!/usr/bin/env python
"""Tests for V20.166-R1 DATA_TRUST status source mapping repair."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_166_r1_data_trust_status_source_mapping_repair.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUT_MAPPING = FACTORS / "V20_166_R1_DATA_TRUST_STATUS_SOURCE_MAPPING.csv"
OUT_STATUS = FACTORS / "V20_166_R1_DATA_TRUST_TICKER_STATUS.csv"
OUT_REPAIR = FACTORS / "V20_166_R1_DATA_TRUST_STATUS_REPAIR_AUDIT.csv"
OUT_UNKNOWN = FACTORS / "V20_166_R1_DATA_TRUST_REMAINING_UNKNOWN_BACKLOG.csv"
OUT_READY = FACTORS / "V20_166_R1_DATA_TRUST_GATE_READY_AUDIT.csv"
OUT_GATE = FACTORS / "V20_166_R1_DATA_TRUST_NEXT_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_166_R1_DATA_TRUST_STATUS_SOURCE_MAPPING_REPAIR_REPORT.md"
OUTPUTS = [OUT_MAPPING, OUT_STATUS, OUT_REPAIR, OUT_UNKNOWN, OUT_READY, OUT_GATE, OUT_REPORT]

STATUS_COLUMNS = {
    "ticker",
    "baseline_rank",
    "baseline_score",
    "data_trust_status",
    "data_trust_pass",
    "data_trust_fail",
    "data_trust_unknown",
    "freshness_status",
    "source_quality_status",
    "pit_safety_status",
    "schema_status",
    "factor_score_availability_status",
    "price_availability_status",
    "benchmark_availability_status_if_relevant",
    "outcome_availability_status_if_relevant",
    "data_trust_failure_category",
    "data_trust_failure_reason",
    "data_trust_source_artifact",
    "data_trust_source_field",
    "mapping_confidence",
    "ranking_eligible_after_data_trust_gate",
    "repair_required",
    "recommended_repair_action",
}
READY_COLUMNS = {
    "baseline_candidate_count",
    "data_trust_pass_count",
    "data_trust_fail_count",
    "data_trust_unknown_count",
    "ranking_eligible_after_data_trust_count",
    "excluded_due_to_data_trust_fail_count",
    "excluded_due_to_data_trust_unknown_count",
    "remaining_unknown_backlog_count",
    "mapping_source_artifact_count",
    "direct_ticker_mapping_count",
    "inferred_from_artifact_mapping_count",
    "unmapped_ticker_count",
    "ready_for_gate_only_ranking_simulation",
    "recommended_next_action",
}
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
]


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
        FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_POLICY.csv",
        FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_WEIGHT_SIMULATION.csv",
        FACTORS / "V20_166_DATA_TRUST_RANKING_ELIGIBILITY_AUDIT.csv",
        FACTORS / "V20_166_DATA_TRUST_FAILED_REPAIR_BACKLOG.csv",
        FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_SAFETY_AUDIT.csv",
        FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_NEXT_GATE.csv",
        CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
    ]
    return {path: digest(path) for path in paths if path.exists()}


def load_module():
    spec = importlib.util.spec_from_file_location("v20_166_r1_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    module.OUTPUTS = temp
    module.CONSOLIDATION = temp / "consolidation"
    module.FACTORS = temp / "factors"
    module.READ_CENTER = temp / "read_center"
    for name in ["V166_POLICY", "V166_WEIGHT", "V166_ELIGIBILITY", "V166_BACKLOG", "V166_SAFETY", "V166_GATE"]:
        setattr(module, name, module.FACTORS / getattr(module, name).name)
    module.BASELINE = module.CONSOLIDATION / module.BASELINE.name
    module.SOURCE_CANDIDATES = [
        module.CONSOLIDATION / "V20_12_FACTOR_INPUT_DATA_QUALITY_REVIEW.csv",
        module.CONSOLIDATION / "V20_13_FACTOR_EVIDENCE_DATA_QUALITY_AUDIT.csv",
        module.CONSOLIDATION / "V20_15_FACTOR_SCORE_DATA_QUALITY_AUDIT.csv",
        module.CONSOLIDATION / "V20_16_FACTOR_SCORE_DATA_QUALITY_REVIEW.csv",
    ]
    module.OUT_MAPPING = module.FACTORS / module.OUT_MAPPING.name
    module.OUT_STATUS = module.FACTORS / module.OUT_STATUS.name
    module.OUT_REPAIR = module.FACTORS / module.OUT_REPAIR.name
    module.OUT_UNKNOWN = module.FACTORS / module.OUT_UNKNOWN.name
    module.OUT_READY = module.FACTORS / module.OUT_READY.name
    module.OUT_GATE = module.FACTORS / module.OUT_GATE.name
    module.REPORT = module.READ_CENTER / module.REPORT.name


def write_minimal_inputs(module, gate_ok: bool = True, aggregate_ok: bool = True) -> None:
    write_csv(module.V166_POLICY, [{"factor_family": "DATA_TRUST"}])
    write_csv(module.V166_WEIGHT, [{"factor_family": "DATA_TRUST"}])
    write_csv(module.V166_ELIGIBILITY, [
        {"ticker": "AAA", "data_trust_status": "UNKNOWN"},
        {"ticker": "BBB", "data_trust_status": "UNKNOWN"},
    ])
    write_csv(module.V166_BACKLOG, [{"ticker": "AAA"}])
    write_csv(module.V166_SAFETY, [{"safety_check_id": "S"}])
    write_csv(module.V166_GATE, [{
        "final_status": "WARN_V20_166_DATA_TRUST_GATE_ONLY_POLICY_INSUFFICIENT_DATA_TRUST_STATUS" if gate_ok else "PASS",
    }])
    write_csv(module.BASELINE, [
        {
            "ticker": "AAA",
            "official_current_rank": "1",
            "official_current_score": "1.0",
            "latest_price": "10",
            "latest_price_date": "2026-06-12",
            "source_file": "source.csv",
            "certification_status": "CERTIFIED_AUTHORITATIVE_OFFICIAL_CURRENT_RESEARCH_RANKING",
            "accepted_artifact_validation_status": "PASS",
            "exact_artifact_proof_status": "FOUND",
        },
        {
            "ticker": "BBB",
            "official_current_rank": "2",
            "official_current_score": "2.0",
            "latest_price": "20",
            "latest_price_date": "2026-06-12",
            "source_file": "source.csv",
            "certification_status": "CERTIFIED_AUTHORITATIVE_OFFICIAL_CURRENT_RESEARCH_RANKING",
            "accepted_artifact_validation_status": "PASS",
            "exact_artifact_proof_status": "FOUND",
        },
    ])
    status = "PASS" if aggregate_ok else "WARN"
    write_csv(module.SOURCE_CANDIDATES[0], [{"data_quality_review_status": status}])
    write_csv(module.SOURCE_CANDIDATES[1], [{"data_quality_status": status}])
    write_csv(module.SOURCE_CANDIDATES[2], [{"data_quality_status": status}])
    write_csv(module.SOURCE_CANDIDATES[3], [{"data_quality_review_status": status}])


def assert_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        assert row.get("research_only", "TRUE") == "TRUE"
        assert row.get("data_trust_scoring_weight", "0.0000000000") == "0.0000000000"
        assert row.get("data_trust_role", "GATE_ONLY_AND_REPAIR_DIAGNOSTIC") == "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE in {row}"


def test_blocked_missing_inputs_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_166_R1_DATA_TRUST_STATUS_SOURCE_MAPPING_REPAIR"


def test_blocked_wrong_v166_status_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_minimal_inputs(module, gate_ok=False)
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_166_R1_DATA_TRUST_STATUS_SOURCE_MAPPING_REPAIR"


def test_temp_inferred_mapping_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_minimal_inputs(module)
        assert module.main() == 0
        status_rows = read_csv(module.OUT_STATUS)
        ready = read_csv(module.OUT_READY)[0]
        gate = read_csv(module.OUT_GATE)[0]
        assert all(row["data_trust_status"] == "PASS" for row in status_rows)
        assert all(row["mapping_confidence"] == "INFERRED_HIGH" for row in status_rows)
        assert ready["data_trust_pass_count"] == "2"
        assert ready["ready_for_gate_only_ranking_simulation"] == "TRUE"
        assert gate["final_status"] == "PASS_V20_166_R1_DATA_TRUST_STATUS_MAPPING_READY_FOR_V20_166_R2"


def test_temp_remaining_unknown_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_minimal_inputs(module, aggregate_ok=False)
        assert module.main() == 0
        ready = read_csv(module.OUT_READY)[0]
        unknown = read_csv(module.OUT_UNKNOWN)
        gate = read_csv(module.OUT_GATE)[0]
        assert ready["data_trust_unknown_count"] == "2"
        assert len(unknown) == 2
        assert gate["final_status"] == "WARN_V20_166_R1_NO_TICKER_LEVEL_DATA_TRUST_STATUS_RECOVERED"


def test_data_trust_status_source_mapping_repair() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.166 or baseline outputs were mutated"
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_166_R1_DATA_TRUST_STATUS_MAPPING_READY_FOR_V20_166_R2",
        "PARTIAL_PASS_V20_166_R1_DATA_TRUST_STATUS_MAPPING_WITH_REMAINING_UNKNOWN_READY_FOR_V20_166_R2",
        "WARN_V20_166_R1_NO_TICKER_LEVEL_DATA_TRUST_STATUS_RECOVERED",
    ])
    for expected in [
        "V20_166_GATE_CONSUMED=TRUE",
        "V20_166_STATUS=WARN_V20_166_DATA_TRUST_GATE_ONLY_POLICY_INSUFFICIENT_DATA_TRUST_STATUS",
        "NO_TICKER_STATUS_FABRICATED=TRUE",
        "UNKNOWN_NOT_TREATED_AS_PASS=TRUE",
        "DATA_TRUST_GATE_CRITERIA_NOT_LOWERED=TRUE",
        "RESEARCH_ONLY=TRUE",
        "DATA_TRUST_SCORING_WEIGHT=0.0000000000",
        "DATA_TRUST_ROLE=GATE_ONLY_AND_REPAIR_DIAGNOSTIC",
        "FORMAL_ACTIVATION_ALLOWED=FALSE",
        "PROMOTION_READY=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "OFFICIAL_WEIGHT_CHANGE_CREATED=FALSE",
        "OFFICIAL_WEIGHT_REGISTRY_MUTATED=FALSE",
        "WEIGHT_MUTATED=FALSE",
        "REAL_BOOK_ACTION_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
        "PERFORMANCE_CLAIM_CREATED=FALSE",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    mapping = read_csv(OUT_MAPPING)
    statuses = read_csv(OUT_STATUS)
    repairs = read_csv(OUT_REPAIR)
    ready = read_csv(OUT_READY)
    gate = read_csv(OUT_GATE)
    assert mapping and statuses and repairs and ready and gate
    assert STATUS_COLUMNS.issubset(statuses[0].keys()), STATUS_COLUMNS - set(statuses[0].keys())
    assert READY_COLUMNS.issubset(ready[0].keys()), READY_COLUMNS - set(ready[0].keys())
    assert int(ready[0]["baseline_candidate_count"]) == len(statuses)
    assert all(row["data_trust_unknown"] != "TRUE" or row["ranking_eligible_after_data_trust_gate"] == "FALSE" for row in statuses)
    assert gate[0]["no_ticker_status_fabricated"] == "TRUE"
    assert gate[0]["unknown_not_treated_as_pass"] == "TRUE"
    for rows in [mapping, statuses, repairs, ready, gate]:
        assert_safety(rows)


if __name__ == "__main__":
    test_blocked_missing_inputs_case()
    test_blocked_wrong_v166_status_case()
    test_temp_inferred_mapping_case()
    test_temp_remaining_unknown_case()
    test_data_trust_status_source_mapping_repair()
    print("PASS_V20_166_R1_DATA_TRUST_STATUS_SOURCE_MAPPING_REPAIR_TESTS")
