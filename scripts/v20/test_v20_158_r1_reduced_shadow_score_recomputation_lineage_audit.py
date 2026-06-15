#!/usr/bin/env python
"""Tests for V20.158-R1 reduced shadow score recomputation lineage audit."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_158_r1_reduced_shadow_score_recomputation_lineage_audit.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUT_LINEAGE = FACTORS / "V20_158_R1_SCORE_RECOMPUTATION_LINEAGE_AUDIT.csv"
OUT_WEIGHT = FACTORS / "V20_158_R1_WEIGHT_BINDING_AUDIT.csv"
OUT_CARRY = FACTORS / "V20_158_R1_UNCHANGED_FACTOR_CARRYFORWARD_AUDIT.csv"
OUT_NORM = FACTORS / "V20_158_R1_SCORE_NORMALIZATION_AUDIT.csv"
OUT_CAUSAL = FACTORS / "V20_158_R1_RANK_IMPACT_CAUSAL_DIAGNOSTIC.csv"
OUT_GATE = FACTORS / "V20_158_R1_NEXT_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_158_R1_REDUCED_SHADOW_SCORE_RECOMPUTATION_LINEAGE_AUDIT_REPORT.md"
OUTPUTS = [OUT_LINEAGE, OUT_WEIGHT, OUT_CARRY, OUT_NORM, OUT_CAUSAL, OUT_GATE, OUT_REPORT]

REQUIRED_CAUSAL = {
    "baseline_weight_sum",
    "reduced_shadow_weight_sum",
    "missing_base_weight_count",
    "missing_current_research_weight_count",
    "unchanged_factor_family_carryforward_count",
    "unchanged_factor_family_missing_count",
    "score_formula_consistent_with_baseline",
    "score_normalization_changed",
    "proposal_rows_used_as_full_weight_table",
    "score_delta_proportional_to_weight_delta",
    "rank_delta_explained_by_score_delta",
    "unexplained_rank_churn_count",
    "likely_root_cause",
}
SAFETY_FALSE_FIELDS = [
    "formal_activation_allowed",
    "promotion_ready",
    "official_recommendation_created",
    "official_ranking_mutated",
    "official_weight_change_created",
    "new_shadow_proposal_created",
    "weight_mutated",
    "real_book_action_created",
    "trade_action_created",
    "broker_execution_supported",
    "performance_claim_created",
    "v20_159_allowed",
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
        FACTORS / "V20_158_REDUCED_SHADOW_WEIGHT_RANKING_SIMULATION.csv",
        FACTORS / "V20_158_REDUCED_SHADOW_VS_BASELINE_RANK_DELTA.csv",
        FACTORS / "V20_158_REDUCED_SHADOW_RANKING_GATE.csv",
        FACTORS / "V20_158_REDUCED_SHADOW_RANKING_SOURCE_AUDIT.csv",
        FACTORS / "V20_158_REDUCED_SHADOW_RANKING_SAFETY_AUDIT.csv",
        FACTORS / "V20_158_REDUCED_VS_ORIGINAL_SHADOW_IMPACT_COMPARISON.csv",
        FACTORS / "V20_157_REDUCED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL.csv",
        FACTORS / "V20_157_DELTA_REDUCTION_GATE.csv",
        CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv",
        CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
    ]
    return {path: digest(path) for path in paths if path.exists()}


def load_module():
    spec = importlib.util.spec_from_file_location("v20_158_r1_lineage_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    module.OUTPUTS = temp
    module.FACTORS = temp / "factors"
    module.CONSOLIDATION = temp / "consolidation"
    module.READ_CENTER = temp / "read_center"
    for name in [
        "V158_SIM", "V158_DELTA", "V158_GATE", "V158_SOURCE", "V158_SAFETY", "V158_COMPARISON",
        "V157_PROPOSAL", "V157_GATE",
    ]:
        setattr(module, name, module.FACTORS / getattr(module, name).name)
    module.BASE_WEIGHT_REGISTRY = module.CONSOLIDATION / module.BASE_WEIGHT_REGISTRY.name
    module.BASELINE_RANKING = module.CONSOLIDATION / module.BASELINE_RANKING.name
    module.OUT_LINEAGE = module.FACTORS / module.OUT_LINEAGE.name
    module.OUT_WEIGHT = module.FACTORS / module.OUT_WEIGHT.name
    module.OUT_CARRY = module.FACTORS / module.OUT_CARRY.name
    module.OUT_NORM = module.FACTORS / module.OUT_NORM.name
    module.OUT_CAUSAL = module.FACTORS / module.OUT_CAUSAL.name
    module.OUT_GATE = module.FACTORS / module.OUT_GATE.name
    module.REPORT = module.READ_CENTER / module.REPORT.name


def write_minimal_inputs(module, status_ok: bool = True) -> None:
    write_csv(module.V158_SIM, [
        {"ticker": "AAA", "baseline_rank": "1", "reduced_shadow_rank": "2", "reduced_shadow_rank_delta": "-1", "baseline_score": "0.50", "reduced_shadow_score": "0.49", "reduced_score_delta": "-0.01"},
        {"ticker": "BBB", "baseline_rank": "2", "reduced_shadow_rank": "1", "reduced_shadow_rank_delta": "1", "baseline_score": "0.60", "reduced_shadow_score": "0.60", "reduced_score_delta": "0.00"},
    ])
    write_csv(module.V158_DELTA, [{"summary_id": "S"}])
    write_csv(module.V158_GATE, [{"final_status": "WARN_V20_158_REDUCED_SHADOW_RANKING_STILL_TOO_UNSTABLE" if status_ok else "PASS_V20_158_REDUCED_SHADOW_WEIGHT_RANKING_SIMULATION_READY_FOR_V20_159"}])
    write_csv(module.V158_SOURCE, [{"source_audit_id": "S"}])
    write_csv(module.V158_SAFETY, [{"safety_check_id": "S"}])
    write_csv(module.V158_COMPARISON, [{"comparison_id": "C"}])
    write_csv(module.V157_GATE, [{"final_status": "PARTIAL_PASS_V20_157_SHADOW_WEIGHT_DELTA_REDUCTION_WITH_LIMITED_CONFIDENCE_READY_FOR_V20_158"}])
    write_csv(module.V157_PROPOSAL, [{
        "factor_family": "RISK",
        "original_shadow_proposed_weight": "0.144",
        "original_proposed_delta": "-0.006",
        "reduced_proposed_delta": "-0.0015",
    }])
    write_csv(module.BASELINE_RANKING, [{"ticker": "AAA", "official_current_rank": "1"}, {"ticker": "BBB", "official_current_rank": "2"}])
    write_csv(module.BASE_WEIGHT_REGISTRY, [
        {"factor_family": "FUNDAMENTAL", "active_research_base_weight": "0.20"},
        {"factor_family": "TECHNICAL", "active_research_base_weight": "0.25"},
        {"factor_family": "STRATEGY", "active_research_base_weight": "0.20"},
        {"factor_family": "RISK", "active_research_base_weight": "0.15"},
        {"factor_family": "MARKET_REGIME", "active_research_base_weight": "0.10"},
        {"factor_family": "DATA_TRUST", "active_research_base_weight": "0.10"},
    ])


def copy_real_inputs(temp: Path) -> None:
    (temp / "factors").mkdir(parents=True, exist_ok=True)
    (temp / "consolidation").mkdir(parents=True, exist_ok=True)
    for path in [
        FACTORS / "V20_158_REDUCED_SHADOW_WEIGHT_RANKING_SIMULATION.csv",
        FACTORS / "V20_158_REDUCED_SHADOW_VS_BASELINE_RANK_DELTA.csv",
        FACTORS / "V20_158_REDUCED_SHADOW_RANKING_GATE.csv",
        FACTORS / "V20_158_REDUCED_SHADOW_RANKING_SOURCE_AUDIT.csv",
        FACTORS / "V20_158_REDUCED_SHADOW_RANKING_SAFETY_AUDIT.csv",
        FACTORS / "V20_158_REDUCED_VS_ORIGINAL_SHADOW_IMPACT_COMPARISON.csv",
        FACTORS / "V20_157_REDUCED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL.csv",
        FACTORS / "V20_157_DELTA_REDUCTION_GATE.csv",
    ]:
        shutil.copy2(path, temp / "factors" / path.name)
    for path in [
        CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv",
        CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
    ]:
        shutil.copy2(path, temp / "consolidation" / path.name)


def assert_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE in {row}"


def test_blocked_missing_inputs_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_158_R1_SCORE_RECOMPUTATION_LINEAGE_AUDIT"


def test_blocked_wrong_v158_status_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        write_minimal_inputs(module, status_ok=False)
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_158_R1_SCORE_RECOMPUTATION_LINEAGE_AUDIT"


def test_temp_lineage_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        write_minimal_inputs(module)
        assert module.main() == 0
        causal = read_csv(module.OUT_CAUSAL)[0]
        assert REQUIRED_CAUSAL.issubset(causal.keys())
        assert causal["baseline_weight_sum"] == "1.0000000000"
        assert causal["missing_base_weight_count"] == "0"
        assert read_csv(module.OUT_GATE)[0]["v20_159_allowed"] == "FALSE"


def test_reduced_shadow_score_recomputation_lineage_audit() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.157/V20.158/base outputs were mutated"
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_158_R1_SCORE_RECOMPUTATION_LINEAGE_AUDIT_READY_FOR_REPAIR",
        "PARTIAL_PASS_V20_158_R1_LINEAGE_AUDIT_WITH_UNCONFIRMED_ROOT_CAUSE",
    ])
    for expected in [
        "V20_158_WARN_STATUS_CONFIRMED=TRUE",
        "BASELINE_WEIGHT_SUM=",
        "REDUCED_SHADOW_WEIGHT_SUM=",
        "LIKELY_ROOT_CAUSE=",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "OFFICIAL_WEIGHT_CHANGE_CREATED=FALSE",
        "NEW_SHADOW_PROPOSAL_CREATED=FALSE",
        "PERFORMANCE_CLAIM_CREATED=FALSE",
        "V20_159_ALLOWED=FALSE",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    lineage = read_csv(OUT_LINEAGE)
    weight = read_csv(OUT_WEIGHT)
    carry = read_csv(OUT_CARRY)
    norm = read_csv(OUT_NORM)
    causal = read_csv(OUT_CAUSAL)
    gate = read_csv(OUT_GATE)
    assert lineage and weight and carry and norm and causal and gate
    assert REQUIRED_CAUSAL.issubset(causal[0].keys())
    assert gate[0]["final_status"] in {
        "PASS_V20_158_R1_SCORE_RECOMPUTATION_LINEAGE_AUDIT_READY_FOR_REPAIR",
        "PARTIAL_PASS_V20_158_R1_LINEAGE_AUDIT_WITH_UNCONFIRMED_ROOT_CAUSE",
    }
    assert gate[0]["v20_159_allowed"] == "FALSE"
    for rows in [lineage, weight, carry, norm, causal, gate]:
        assert_safety(rows)


if __name__ == "__main__":
    test_blocked_missing_inputs_case()
    test_blocked_wrong_v158_status_case()
    test_temp_lineage_case()
    test_reduced_shadow_score_recomputation_lineage_audit()
    print("PASS_V20_158_R1_REDUCED_SHADOW_SCORE_RECOMPUTATION_LINEAGE_AUDIT_TESTS")
