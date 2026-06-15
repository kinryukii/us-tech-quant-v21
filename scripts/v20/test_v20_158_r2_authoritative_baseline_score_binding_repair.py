#!/usr/bin/env python
"""Tests for V20.158-R2 authoritative baseline score binding repair."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_158_r2_authoritative_baseline_score_binding_repair.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUT_REPAIR = FACTORS / "V20_158_R2_AUTHORITATIVE_BASELINE_SCORE_BINDING_REPAIR.csv"
OUT_SIM = FACTORS / "V20_158_R2_BOUND_REDUCED_SHADOW_RANKING_SIMULATION.csv"
OUT_DELTA = FACTORS / "V20_158_R2_BOUND_SHADOW_VS_BASELINE_RANK_DELTA.csv"
OUT_BINDING = FACTORS / "V20_158_R2_BASELINE_BINDING_AUDIT.csv"
OUT_ADJUST = FACTORS / "V20_158_R2_SCORE_ADJUSTMENT_AUDIT.csv"
OUT_GATE = FACTORS / "V20_158_R2_RANK_IMPACT_RETEST_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_158_R2_AUTHORITATIVE_BASELINE_SCORE_BINDING_REPAIR_REPORT.md"
OUTPUTS = [OUT_REPAIR, OUT_SIM, OUT_DELTA, OUT_BINDING, OUT_ADJUST, OUT_GATE, OUT_REPORT]

SIM_COLUMNS = {
    "ticker",
    "authoritative_baseline_rank",
    "authoritative_baseline_score",
    "bound_reduced_shadow_score",
    "bound_reduced_score_delta",
    "bound_reduced_shadow_rank",
    "bound_reduced_rank_delta",
    "reduced_shadow_adjustment_source",
    "affected_factor_family",
    "affected_factor_name",
    "reduced_shadow_weight_delta",
    "baseline_score_source",
    "baseline_rank_source",
    "score_binding_success",
    "score_adjustment_bounded",
    "official_ranking_mutated",
    "official_weight_change_created",
}
DELTA_COLUMNS = {
    "baseline_candidate_count",
    "bound_shadow_candidate_count",
    "top20_overlap_count",
    "entered_top20_count",
    "exited_top20_count",
    "bound_top20_turnover_rate",
    "bound_max_absolute_rank_delta",
    "bound_average_absolute_rank_delta",
    "affected_ticker_count",
    "prior_unbound_top20_turnover_rate_if_available",
    "prior_unbound_average_absolute_rank_delta_if_available",
    "binding_repair_improved_rank_stability",
    "remaining_rank_impact_severity",
    "recommended_next_action",
}
SAFETY_FALSE_FIELDS = [
    "formal_activation_allowed",
    "promotion_ready",
    "official_recommendation_created",
    "official_ranking_mutated",
    "official_weight_change_created",
    "shadow_weight_expansion_allowed",
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
        FACTORS / "V20_158_R1_SCORE_RECOMPUTATION_LINEAGE_AUDIT.csv",
        FACTORS / "V20_158_R1_WEIGHT_BINDING_AUDIT.csv",
        FACTORS / "V20_158_R1_UNCHANGED_FACTOR_CARRYFORWARD_AUDIT.csv",
        FACTORS / "V20_158_R1_SCORE_NORMALIZATION_AUDIT.csv",
        FACTORS / "V20_158_R1_RANK_IMPACT_CAUSAL_DIAGNOSTIC.csv",
        FACTORS / "V20_158_R1_NEXT_GATE.csv",
        FACTORS / "V20_157_REDUCED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL.csv",
        CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
        CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv",
    ]
    return {path: digest(path) for path in paths if path.exists()}


def load_module():
    spec = importlib.util.spec_from_file_location("v20_158_r2_binding_repair_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    module.OUTPUTS = temp
    module.FACTORS = temp / "factors"
    module.CONSOLIDATION = temp / "consolidation"
    module.READ_CENTER = temp / "read_center"
    for name in ["R1_LINEAGE", "R1_WEIGHT", "R1_CARRY", "R1_NORM", "R1_CAUSAL", "R1_GATE", "V157_PROPOSAL"]:
        setattr(module, name, module.FACTORS / getattr(module, name).name)
    module.BASELINE_RANKING = module.CONSOLIDATION / module.BASELINE_RANKING.name
    module.BASE_WEIGHT_REGISTRY = module.CONSOLIDATION / module.BASE_WEIGHT_REGISTRY.name
    module.OUT_REPAIR = module.FACTORS / module.OUT_REPAIR.name
    module.OUT_SIM = module.FACTORS / module.OUT_SIM.name
    module.OUT_DELTA = module.FACTORS / module.OUT_DELTA.name
    module.OUT_BINDING = module.FACTORS / module.OUT_BINDING.name
    module.OUT_ADJUST = module.FACTORS / module.OUT_ADJUST.name
    module.OUT_GATE = module.FACTORS / module.OUT_GATE.name
    module.REPORT = module.READ_CENTER / module.REPORT.name


def write_minimal_inputs(module, status_ok: bool = True, include_scores: bool = True) -> None:
    write_csv(module.R1_LINEAGE, [
        {"ticker": "AAA", "reduced_score_delta": "-0.001"},
        {"ticker": "BBB", "reduced_score_delta": "-0.002"},
    ])
    write_csv(module.R1_WEIGHT, [{"factor_family": "RISK"}])
    write_csv(module.R1_CARRY, [{"factor_family": "FUNDAMENTAL"}])
    write_csv(module.R1_NORM, [{"normalization_audit_id": "N"}])
    write_csv(module.R1_CAUSAL, [{
        "likely_root_cause": "RECOMPUTED_BASELINE_SCORE_FORMULA_NOT_CONSISTENT_WITH_AUTHORITATIVE_BASELINE_RANKING",
        "v20_159_allowed": "FALSE",
    }])
    write_csv(module.R1_GATE, [{
        "final_status": "PASS_V20_158_R1_SCORE_RECOMPUTATION_LINEAGE_AUDIT_READY_FOR_REPAIR" if status_ok else "PARTIAL_PASS_V20_158_R1_LINEAGE_AUDIT_WITH_UNCONFIRMED_ROOT_CAUSE",
        "likely_root_cause": "RECOMPUTED_BASELINE_SCORE_FORMULA_NOT_CONSISTENT_WITH_AUTHORITATIVE_BASELINE_RANKING",
        "v20_159_allowed": "FALSE",
    }])
    write_csv(module.V157_PROPOSAL, [{
        "factor_family": "RISK",
        "factor_name": "DOWNSIDE_RISK_EVIDENCE",
        "reduced_proposed_delta": "-0.0015",
    }])
    if include_scores:
        write_csv(module.BASELINE_RANKING, [
            {"ticker": "AAA", "official_current_rank": "1", "official_current_score": "1"},
            {"ticker": "BBB", "official_current_rank": "2", "official_current_score": "2"},
        ])
    else:
        write_csv(module.BASELINE_RANKING, [
            {"ticker": "AAA", "official_current_rank": "1"},
            {"ticker": "BBB", "official_current_rank": "2"},
        ])
    write_csv(module.BASE_WEIGHT_REGISTRY, [{"factor_family": "RISK", "active_research_base_weight": "0.15"}])


def assert_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE in {row}"
        if "reduced_shadow_weight_proposal_created" in row:
            assert row["reduced_shadow_weight_proposal_created"] == "TRUE"
        if "bound_reduced_shadow_ranking_simulation_created" in row:
            assert row["bound_reduced_shadow_ranking_simulation_created"] == "TRUE"
        if "shadow_simulation_scope" in row:
            assert row["shadow_simulation_scope"] == "RESEARCH_ONLY_LIMITED_CONSERVATIVE_BOUND_TO_AUTHORITATIVE_BASELINE"


def test_blocked_missing_inputs_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_158_R2_AUTHORITATIVE_BASELINE_SCORE_BINDING_REPAIR"


def test_blocked_wrong_r1_status_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        write_minimal_inputs(module, status_ok=False)
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_158_R2_AUTHORITATIVE_BASELINE_SCORE_BINDING_REPAIR"


def test_warn_missing_authoritative_score_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        write_minimal_inputs(module, include_scores=False)
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "WARN_V20_158_R2_AUTHORITATIVE_BASELINE_SCORE_UNAVAILABLE"


def test_temp_bound_repair_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        write_minimal_inputs(module)
        assert module.main() == 0
        gate = read_csv(module.OUT_GATE)[0]
        sim = read_csv(module.OUT_SIM)
        assert gate["final_status"] == "PASS_V20_158_R2_AUTHORITATIVE_BASELINE_BINDING_REPAIR_READY_FOR_V20_159"
        assert len(sim) == 2
        assert all(row["score_binding_success"] == "TRUE" for row in sim)
        assert all(row["official_ranking_mutated"] == "FALSE" for row in sim)


def test_authoritative_baseline_score_binding_repair() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.157/V20.158-R1/base outputs were mutated"
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_158_R2_AUTHORITATIVE_BASELINE_BINDING_REPAIR_READY_FOR_V20_159",
        "PARTIAL_PASS_V20_158_R2_BASELINE_BINDING_REPAIR_WITH_REMAINING_INSTABILITY",
        "WARN_V20_158_R2_AUTHORITATIVE_BASELINE_SCORE_UNAVAILABLE",
    ])
    for expected in [
        "R1_ROOT_CAUSE_CONFIRMED=TRUE",
        "V20_159_ALLOWED_FROM_R1=FALSE",
        "PROPOSAL_ROWS_USED_AS_FULL_WEIGHT_TABLE=FALSE",
        "UNCHANGED_FACTOR_FAMILY_CARRYFORWARD_PRESERVED=TRUE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "OFFICIAL_WEIGHT_CHANGE_CREATED=FALSE",
        "PERFORMANCE_CLAIM_CREATED=FALSE",
        "SHADOW_SIMULATION_SCOPE=RESEARCH_ONLY_LIMITED_CONSERVATIVE_BOUND_TO_AUTHORITATIVE_BASELINE",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    repair = read_csv(OUT_REPAIR)
    sim = read_csv(OUT_SIM)
    delta = read_csv(OUT_DELTA)
    binding = read_csv(OUT_BINDING)
    adjust = read_csv(OUT_ADJUST)
    gate = read_csv(OUT_GATE)
    assert repair and sim and delta and binding and adjust and gate
    assert SIM_COLUMNS.issubset(sim[0].keys()), SIM_COLUMNS - set(sim[0].keys())
    assert DELTA_COLUMNS.issubset(delta[0].keys()), DELTA_COLUMNS - set(delta[0].keys())
    assert int(gate[0]["baseline_candidate_count"]) == len(sim)
    assert int(delta[0]["baseline_candidate_count"]) == len(sim)
    assert all(row["official_ranking_mutated"] == "FALSE" for row in sim)
    assert all(row["official_weight_change_created"] == "FALSE" for row in sim)
    assert gate[0]["v20_159_allowed"] in {"TRUE", "FALSE"}
    for rows in [repair, sim, delta, binding, adjust, gate]:
        assert_safety(rows)


if __name__ == "__main__":
    test_blocked_missing_inputs_case()
    test_blocked_wrong_r1_status_case()
    test_warn_missing_authoritative_score_case()
    test_temp_bound_repair_case()
    test_authoritative_baseline_score_binding_repair()
    print("PASS_V20_158_R2_AUTHORITATIVE_BASELINE_SCORE_BINDING_REPAIR_TESTS")
