#!/usr/bin/env python
"""Tests for V20.151 forward observation accumulation repair."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_151_forward_observation_accumulation_repair.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
STAGING = ROOT / "outputs" / "v20" / "staging"
OBSERVATIONS = ROOT / "outputs" / "v20" / "observations"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUT_ACCUMULATION = OBSERVATIONS / "V20_151_FORWARD_OBSERVATION_ACCUMULATION.csv"
OUT_GATE = OBSERVATIONS / "V20_151_FORWARD_OBSERVATION_GATE.csv"
OUT_SOURCE = OBSERVATIONS / "V20_151_FORWARD_OBSERVATION_SOURCE_AUDIT.csv"
OUT_ELIGIBILITY = OBSERVATIONS / "V20_151_FORWARD_OBSERVATION_ELIGIBILITY_AUDIT.csv"
OUT_REPORT = READ_CENTER / "V20_151_FORWARD_OBSERVATION_ACCUMULATION_REPORT.md"
OUTPUTS = [OUT_ACCUMULATION, OUT_GATE, OUT_SOURCE, OUT_ELIGIBILITY, OUT_REPORT]
UPSTREAM = sorted(
    [path for path in CONSOLIDATION.glob("V20_*") if path.is_file() and any(path.name.startswith(f"V20_{stage}_") for stage in range(109, 150))]
    + [path for path in STAGING.glob("V20_150_*") if path.is_file()]
)
REQUIRED_COLUMNS = {
    OUT_ACCUMULATION: {"source_run_id", "source_stage", "source_artifact_path", "run_timestamp_utc", "observation_date", "observation_status", "outcome_status", "forward_outcome_fabricated", "benchmark_outcome_fabricated", "ticker_rows_fabricated", "dynamic_weight_research_eligible", "eligibility_status", "formal_activation_allowed", "promotion_ready"},
    OUT_GATE: {"v20_150_gate_consumed", "v20_151_allowed_after_v20_150", "staging_review_allowed", "formal_activation_allowed", "promotion_ready", "safety_constraint_audit_passed", "source_audit_row_count", "discovered_run_count", "eligible_forward_observation_count", "outcome_pending_count", "no_ticker_rows_fabricated", "no_forward_outcomes_fabricated", "no_benchmark_outcomes_fabricated", "no_upstream_outputs_mutated", "forward_observation_accumulation_status"},
    OUT_SOURCE: {"source_stage", "source_artifact_path", "source_exists", "source_non_empty", "source_row_count", "source_sha256", "source_role", "source_usable_for_forward_observation", "source_exclusion_reason"},
    OUT_ELIGIBILITY: {"source_run_id", "source_stage", "source_artifact_path", "eligible_for_forward_observation", "dynamic_weight_research_eligible", "outcome_status", "exclusion_reason", "source_evidence_sufficient", "formal_activation_allowed", "promotion_ready"},
}
SAFETY_FALSE_FIELDS = ["formal_activation_allowed", "promotion_ready", "official_recommendation_created", "official_ranking_mutated", "weight_mutated", "real_book_action_created", "trade_action_created", "broker_execution_supported", "performance_claim_created"]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    assert rows
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def upstream_hashes() -> dict[Path, str]:
    return {path: digest(path) for path in UPSTREAM if path.exists()}


def assert_false(rows: list[dict[str, str]], field: str) -> None:
    bad = [row for row in rows if row.get(field) not in {"", "FALSE"}]
    assert not bad, f"{field} was not false: {bad[:3]}"


def load_module():
    spec = importlib.util.spec_from_file_location("v20_151_forward_observation_accumulation_repair_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    module.IN_PACKET = temp / "V20_150_STAGING_REVIEW_PACKET.csv"
    module.IN_GATE = temp / "V20_150_STAGING_REVIEW_GATE.csv"
    module.IN_BOUNDARY = temp / "V20_150_PROMOTION_BOUNDARY_AUDIT.csv"
    module.IN_SAFETY = temp / "V20_150_SAFETY_CONSTRAINT_AUDIT.csv"
    module.REQUIRED_INPUTS = [module.IN_PACKET, module.IN_GATE, module.IN_BOUNDARY, module.IN_SAFETY]
    module.UPSTREAM_HASH_INPUTS = module.REQUIRED_INPUTS
    module.OUTPUTS = temp
    module.OUT_ACCUMULATION = temp / "V20_151_FORWARD_OBSERVATION_ACCUMULATION.csv"
    module.OUT_GATE = temp / "V20_151_FORWARD_OBSERVATION_GATE.csv"
    module.OUT_SOURCE_AUDIT = temp / "V20_151_FORWARD_OBSERVATION_SOURCE_AUDIT.csv"
    module.OUT_ELIGIBILITY = temp / "V20_151_FORWARD_OBSERVATION_ELIGIBILITY_AUDIT.csv"
    module.REPORT = temp / "V20_151_FORWARD_OBSERVATION_ACCUMULATION_REPORT.md"


def copy_staging_inputs(temp: Path) -> None:
    for filename in [
        "V20_150_STAGING_REVIEW_PACKET.csv",
        "V20_150_STAGING_REVIEW_GATE.csv",
        "V20_150_PROMOTION_BOUNDARY_AUDIT.csv",
        "V20_150_SAFETY_CONSTRAINT_AUDIT.csv",
    ]:
        shutil.copy2(STAGING / filename, temp / filename)


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        assert module.main() == 0
        gate = read_csv(module.OUT_GATE)[0]
        assert gate["forward_observation_accumulation_status"] == "BLOCKED_V20_151_FORWARD_OBSERVATION_ACCUMULATION"
        assert gate["v20_152_forward_observation_review_allowed"] == "FALSE"


def test_blocked_staging_gate_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_staging_inputs(temp)
        patch_module_to_temp(module, temp)
        gate = read_csv(module.IN_GATE)
        gate[0]["staging_review_packet_status"] = "BLOCKED_V20_150_STAGING_REVIEW_PACKET"
        write_csv(module.IN_GATE, gate)
        assert module.main() == 0
        out_gate = read_csv(module.OUT_GATE)[0]
        assert out_gate["forward_observation_accumulation_status"] == "BLOCKED_V20_151_FORWARD_OBSERVATION_ACCUMULATION"


def test_forward_observation_accumulation() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109-V20.150 outputs were mutated"
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_151_FORWARD_OBSERVATION_ACCUMULATION_READY_FOR_V20_152",
        "PARTIAL_PASS_V20_151_FORWARD_OBSERVATION_ACCUMULATION_WITH_PENDING_OUTCOMES_READY_FOR_V20_152",
        "WARN_V20_151_NO_ELIGIBLE_FORWARD_OBSERVATIONS_FOUND",
    ])
    for expected in [
        "V20_150_GATE_CONSUMED=TRUE",
        "V20_151_ALLOWED_AFTER_V20_150=TRUE",
        "STAGING_REVIEW_ALLOWED=TRUE",
        "FORMAL_ACTIVATION_ALLOWED=FALSE",
        "PROMOTION_READY=FALSE",
        "SAFETY_CONSTRAINT_AUDIT_PASSED=TRUE",
        "TICKER_ROWS_FABRICATED=0",
        "FORWARD_OUTCOMES_FABRICATED=0",
        "BENCHMARK_OUTCOMES_FABRICATED=0",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_TRUE_COUNT=0",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    for path, columns in REQUIRED_COLUMNS.items():
        rows = read_csv(path)
        assert rows, f"empty output {path}"
        assert columns.issubset(rows[0].keys()), f"missing columns in {path}: {columns - set(rows[0].keys())}"

    accumulation = read_csv(OUT_ACCUMULATION)
    gate = read_csv(OUT_GATE)
    source = read_csv(OUT_SOURCE)
    eligibility = read_csv(OUT_ELIGIBILITY)
    g = gate[0]
    assert int(g["source_audit_row_count"]) == len(source)
    assert int(g["discovered_run_count"]) == len(eligibility)
    assert g["formal_activation_allowed"] == "FALSE"
    assert g["promotion_ready"] == "FALSE"
    assert g["no_ticker_rows_fabricated"] == "TRUE"
    assert g["no_forward_outcomes_fabricated"] == "TRUE"
    assert g["no_benchmark_outcomes_fabricated"] == "TRUE"
    assert any(row["source_stage"] in {"V20.55", "V20.96", "V20.97"} for row in source)
    assert any(row["source_usable_for_forward_observation"] == "TRUE" for row in source)
    assert any(row["eligible_for_forward_observation"] == "FALSE" and row["exclusion_reason"] for row in eligibility)
    assert all(row["outcome_status"] in {"OUTCOME_PENDING", "NOT_APPLICABLE"} for row in eligibility)
    if accumulation:
        assert all(row["outcome_status"] == "OUTCOME_PENDING" for row in accumulation)
        assert all(row["forward_outcome_fabricated"] == "FALSE" and row["benchmark_outcome_fabricated"] == "FALSE" and row["ticker_rows_fabricated"] == "0" for row in accumulation)
    for rows in [accumulation, gate, source, eligibility]:
        if rows:
            for field in SAFETY_FALSE_FIELDS:
                if field in rows[0]:
                    assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_blocked_staging_gate_case()
    test_forward_observation_accumulation()
    print("PASS_V20_151_FORWARD_OBSERVATION_ACCUMULATION_TESTS")

