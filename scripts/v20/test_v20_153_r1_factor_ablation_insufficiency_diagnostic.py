#!/usr/bin/env python
"""Tests for V20.153-R1 factor ablation insufficiency diagnostic."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_153_r1_factor_ablation_insufficiency_diagnostic.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUT_DIAGNOSTIC = FACTORS / "V20_153_R1_FACTOR_ABLATION_INSUFFICIENCY_DIAGNOSTIC.csv"
OUT_BREAKDOWN = FACTORS / "V20_153_R1_FACTOR_ABLATION_BLOCKER_BREAKDOWN.csv"
OUT_REPAIR = FACTORS / "V20_153_R1_FACTOR_ABLATION_REPAIR_PLAN.csv"
OUT_GATE = FACTORS / "V20_153_R1_FACTOR_ABLATION_NEXT_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_153_R1_FACTOR_ABLATION_INSUFFICIENCY_DIAGNOSTIC_REPORT.md"
OUTPUTS = [OUT_DIAGNOSTIC, OUT_BREAKDOWN, OUT_REPAIR, OUT_GATE, OUT_REPORT]

REPAIR_COLUMNS = {
    "blocker_category",
    "affected_row_count",
    "required_repair_action",
    "can_repair_from_existing_artifacts",
    "requires_future_forward_outcomes",
    "requires_new_backtest_generation",
    "safe_to_repair_without_fabrication",
    "recommended_next_stage",
}
SAFETY_FALSE_FIELDS = [
    "formal_activation_allowed",
    "promotion_ready",
    "official_recommendation_created",
    "official_ranking_mutated",
    "official_weight_change_created",
    "shadow_weight_proposal_created",
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
        FACTORS / "V20_153_FACTOR_ABLATION_MATRIX.csv",
        FACTORS / "V20_153_FACTOR_ABLATION_GATE.csv",
        FACTORS / "V20_153_FACTOR_ABLATION_SOURCE_AUDIT.csv",
        FACTORS / "V20_153_FACTOR_ABLATION_ELIGIBILITY_AUDIT.csv",
        FACTORS / "V20_153_FACTOR_ABLATION_GAP_AUDIT.csv",
    ]
    return {path: digest(path) for path in paths if path.exists()}


def load_module():
    spec = importlib.util.spec_from_file_location("v20_153_r1_factor_ablation_insufficiency_diagnostic_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    module.OUTPUTS = temp
    module.FACTORS = temp / "factors"
    module.READ_CENTER = temp / "read_center"
    module.IN_MATRIX = module.FACTORS / "V20_153_FACTOR_ABLATION_MATRIX.csv"
    module.IN_GATE = module.FACTORS / "V20_153_FACTOR_ABLATION_GATE.csv"
    module.IN_SOURCE = module.FACTORS / "V20_153_FACTOR_ABLATION_SOURCE_AUDIT.csv"
    module.IN_ELIGIBILITY = module.FACTORS / "V20_153_FACTOR_ABLATION_ELIGIBILITY_AUDIT.csv"
    module.IN_GAP = module.FACTORS / "V20_153_FACTOR_ABLATION_GAP_AUDIT.csv"
    module.OUT_DIAGNOSTIC = module.FACTORS / "V20_153_R1_FACTOR_ABLATION_INSUFFICIENCY_DIAGNOSTIC.csv"
    module.OUT_BREAKDOWN = module.FACTORS / "V20_153_R1_FACTOR_ABLATION_BLOCKER_BREAKDOWN.csv"
    module.OUT_REPAIR = module.FACTORS / "V20_153_R1_FACTOR_ABLATION_REPAIR_PLAN.csv"
    module.OUT_NEXT_GATE = module.FACTORS / "V20_153_R1_FACTOR_ABLATION_NEXT_GATE.csv"
    module.REPORT = module.READ_CENTER / "V20_153_R1_FACTOR_ABLATION_INSUFFICIENCY_DIAGNOSTIC_REPORT.md"


def copy_v153_inputs(temp: Path) -> None:
    target = temp / "factors"
    target.mkdir(parents=True, exist_ok=True)
    for filename in [
        "V20_153_FACTOR_ABLATION_MATRIX.csv",
        "V20_153_FACTOR_ABLATION_GATE.csv",
        "V20_153_FACTOR_ABLATION_SOURCE_AUDIT.csv",
        "V20_153_FACTOR_ABLATION_ELIGIBILITY_AUDIT.csv",
        "V20_153_FACTOR_ABLATION_GAP_AUDIT.csv",
    ]:
        shutil.copy2(FACTORS / filename, target / filename)


def assert_safety_false(rows: list[dict[str, str]]) -> None:
    for row in rows:
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE in {row}"


def test_blocked_missing_inputs_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        assert module.main() == 0
        gate = read_csv(module.OUT_NEXT_GATE)[0]
        assert gate["final_status"] == "BLOCKED_V20_153_R1_FACTOR_ABLATION_INSUFFICIENCY_DIAGNOSTIC"
        assert gate["v20_154_shadow_dynamic_weight_proposal_allowed"] == "FALSE"


def test_blocked_wrong_v153_status_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        copy_v153_inputs(temp)
        patch_module_to_temp(module, temp)
        gate = read_csv(module.IN_GATE)
        gate[0]["final_status"] = "PASS_V20_153_FACTOR_ABLATION_MATRIX_READY_FOR_V20_154"
        write_csv(module.IN_GATE, gate)
        assert module.main() == 0
        out_gate = read_csv(module.OUT_NEXT_GATE)[0]
        assert out_gate["final_status"] == "BLOCKED_V20_153_R1_FACTOR_ABLATION_INSUFFICIENCY_DIAGNOSTIC"


def test_temp_diagnostic_counts_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        write_csv(module.IN_GATE, [{"final_status": "WARN_V20_153_INSUFFICIENT_FACTOR_ABLATION_EVIDENCE"}])
        write_csv(module.IN_MATRIX, [
            {
                "factor_family": "STRATEGY",
                "factor_name": "TEST",
                "evidence_source": "source.csv",
                "as_of_sample_count": "1",
                "forward_observation_count": "3",
                "outcome_available_count": "0",
                "pending_outcome_count": "2",
                "benchmark_available_count": "0",
                "positive_contribution_count": "0",
                "negative_contribution_count": "0",
                "neutral_contribution_count": "0",
                "contribution_stability": "UNKNOWN_NO_FACTOR_CONTRIBUTION_EVIDENCE",
                "regime_coverage": "NOT_APPLICABLE",
                "window_coverage": "1",
                "usable_for_shadow_weight_proposal": "FALSE",
                "usable_for_official_weight_change": "FALSE",
                "exclusion_reason": "INSUFFICIENT_OUTCOME_EVIDENCE|INSUFFICIENT_BENCHMARK_EVIDENCE|NO_FACTOR_CONTRIBUTION_SIGN_EVIDENCE",
                "evidence_quality": "INSUFFICIENT",
            }
        ])
        write_csv(module.IN_SOURCE, [{"source_artifact": "source.csv", "exclusion_reason": ""}])
        write_csv(module.IN_ELIGIBILITY, [{"factor_family": "STRATEGY", "eligibility_status": "INSUFFICIENT_EVIDENCE"}])
        write_csv(module.IN_GAP, [{"gap_type": "INSUFFICIENT_OUTCOME_EVIDENCE"}])
        assert module.main() == 0
        gate = read_csv(module.OUT_NEXT_GATE)[0]
        diagnostic = read_csv(module.OUT_DIAGNOSTIC)[0]
        repair = read_csv(module.OUT_REPAIR)
        assert gate["final_status"] == "PARTIAL_PASS_V20_153_R1_FACTOR_ABLATION_DIAGNOSTIC_WITH_UNREPAIRABLE_PENDING_OUTCOMES"
        assert gate["v20_154_shadow_dynamic_weight_proposal_allowed"] == "FALSE"
        assert gate["missing_outcome_blocked_row_count"] == "1"
        assert gate["missing_benchmark_blocked_row_count"] == "1"
        assert gate["pending_forward_observation_blocked_row_count"] == "1"
        assert diagnostic["primary_blocker"] == "PENDING_FORWARD_OBSERVATION"
        assert REPAIR_COLUMNS.issubset(repair[0].keys())


def test_factor_ablation_insufficiency_diagnostic() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.153 outputs were mutated"
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_153_R1_FACTOR_ABLATION_INSUFFICIENCY_DIAGNOSTIC_READY_FOR_REPAIR",
        "PARTIAL_PASS_V20_153_R1_FACTOR_ABLATION_DIAGNOSTIC_WITH_UNREPAIRABLE_PENDING_OUTCOMES",
    ])
    for expected in [
        "V20_153_GATE_CONSUMED=TRUE",
        "V20_153_REQUIRED_WARN_STATUS_CONFIRMED=TRUE",
        "V20_154_SHADOW_DYNAMIC_WEIGHT_PROPOSAL_ALLOWED=FALSE",
        "OUTCOMES_FABRICATED=0",
        "BENCHMARKS_FABRICATED=0",
        "FACTOR_CONTRIBUTION_FABRICATED=0",
        "ELIGIBILITY_THRESHOLDS_LOWERED=FALSE",
        "SHADOW_WEIGHTS_CREATED=FALSE",
        "OFFICIAL_WEIGHT_MUTATION=FALSE",
        "OFFICIAL_RANKING_CHANGES=FALSE",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_TRUE_COUNT=0",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    diagnostics = read_csv(OUT_DIAGNOSTIC)
    breakdown = read_csv(OUT_BREAKDOWN)
    repair = read_csv(OUT_REPAIR)
    gate = read_csv(OUT_GATE)
    assert diagnostics, "diagnostic output must not be empty"
    assert breakdown, "breakdown output must not be empty"
    assert repair, "repair plan output must not be empty"
    assert REPAIR_COLUMNS.issubset(repair[0].keys()), REPAIR_COLUMNS - set(repair[0].keys())
    g = gate[0]
    assert g["v20_154_shadow_dynamic_weight_proposal_allowed"] == "FALSE"
    assert int(g["diagnostic_row_count"]) == len(diagnostics)
    assert int(g["repair_plan_row_count"]) == len(repair)
    assert int(g["missing_outcome_blocked_row_count"]) >= 0
    assert int(g["missing_benchmark_blocked_row_count"]) >= 0
    assert int(g["pending_forward_observation_blocked_row_count"]) >= 0
    assert int(g["insufficient_as_of_sample_blocked_row_count"]) >= 0
    assert int(g["insufficient_regime_coverage_blocked_row_count"]) >= 0
    assert int(g["insufficient_window_coverage_blocked_row_count"]) >= 0
    assert int(g["insufficient_contribution_attribution_blocked_row_count"]) >= 0
    assert int(g["pit_safety_issue_blocked_row_count"]) >= 0
    assert int(g["evidence_quality_threshold_blocked_row_count"]) >= 0
    assert int(g["conservative_threshold_only_blocked_row_count"]) >= 0
    assert all(row["safe_to_repair_without_fabrication"] == "TRUE" for row in repair)
    for rows in [diagnostics, breakdown, repair, gate]:
        assert_safety_false(rows)


if __name__ == "__main__":
    test_blocked_missing_inputs_case()
    test_blocked_wrong_v153_status_case()
    test_temp_diagnostic_counts_case()
    test_factor_ablation_insufficiency_diagnostic()
    print("PASS_V20_153_R1_FACTOR_ABLATION_INSUFFICIENCY_DIAGNOSTIC_TESTS")
