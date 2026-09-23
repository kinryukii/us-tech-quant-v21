#!/usr/bin/env python
"""Tests for V20.166-R2 DATA_TRUST gate-only ranking simulation."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_166_r2_data_trust_gate_only_ranking_simulation.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUT_SIM = FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION.csv"
OUT_DELTA = FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_RANK_DELTA.csv"
OUT_SCORE = FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_SCORE_AUDIT.csv"
OUT_ELIGIBILITY = FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_ELIGIBILITY_AUDIT.csv"
OUT_MAPPING = FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_MAPPING_CONFIDENCE_AUDIT.csv"
OUT_SAFETY = FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_SAFETY_AUDIT.csv"
OUT_GATE = FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_NEXT_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_166_R2_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION_REPORT.md"
OUTPUTS = [OUT_SIM, OUT_DELTA, OUT_SCORE, OUT_ELIGIBILITY, OUT_MAPPING, OUT_SAFETY, OUT_GATE, OUT_REPORT]

SIM_COLUMNS = {
    "ticker",
    "baseline_rank",
    "baseline_score",
    "data_trust_status",
    "data_trust_pass",
    "data_trust_fail",
    "data_trust_unknown",
    "data_trust_mapping_confidence",
    "ranking_eligible_after_data_trust_gate",
    "gate_only_rank",
    "gate_only_score",
    "rank_delta",
    "score_delta",
    "baseline_top20_flag",
    "gate_only_top20_flag",
    "entered_gate_only_top20",
    "exited_gate_only_top20",
    "data_trust_scoring_weight_before",
    "data_trust_scoring_weight_after",
    "scoring_weight_renormalization_applied",
    "official_ranking_mutated",
    "official_weight_change_created",
}
SCORE_COLUMNS = {
    "ticker",
    "fundamental_score_available",
    "technical_score_available",
    "strategy_score_available",
    "risk_score_available",
    "market_regime_score_available",
    "data_trust_score_excluded_from_scoring",
    "all_required_scoring_families_available",
    "score_recomputation_performed",
    "score_recomputation_blocked_reason",
    "baseline_score_source",
    "gate_only_score_source",
    "formula_consistent_with_available_factor_family_scores",
    "limitation_reason",
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
    "shadow_weight_expansion_allowed",
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
        FACTORS / "V20_166_R1_DATA_TRUST_STATUS_SOURCE_MAPPING.csv",
        FACTORS / "V20_166_R1_DATA_TRUST_TICKER_STATUS.csv",
        FACTORS / "V20_166_R1_DATA_TRUST_STATUS_REPAIR_AUDIT.csv",
        FACTORS / "V20_166_R1_DATA_TRUST_REMAINING_UNKNOWN_BACKLOG.csv",
        FACTORS / "V20_166_R1_DATA_TRUST_GATE_READY_AUDIT.csv",
        FACTORS / "V20_166_R1_DATA_TRUST_NEXT_GATE.csv",
        CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
        CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv",
    ]
    return {path: digest(path) for path in paths if path.exists()}


def load_module():
    spec = importlib.util.spec_from_file_location("v20_166_r2_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    module.OUTPUTS = temp
    module.CONSOLIDATION = temp / "consolidation"
    module.FACTORS = temp / "factors"
    module.READ_CENTER = temp / "read_center"
    for name in ["V166_POLICY", "V166_WEIGHT", "V166_ELIGIBILITY", "V166_BACKLOG", "V166_SAFETY", "V166_GATE", "R1_MAPPING", "R1_STATUS", "R1_REPAIR", "R1_UNKNOWN", "R1_READY", "R1_GATE"]:
        setattr(module, name, module.FACTORS / getattr(module, name).name)
    module.BASELINE = module.CONSOLIDATION / module.BASELINE.name
    module.WEIGHTS = module.CONSOLIDATION / module.WEIGHTS.name
    module.R10_SCORES = module.CONSOLIDATION / module.R10_SCORES.name
    module.OUT_SIM = module.FACTORS / module.OUT_SIM.name
    module.OUT_DELTA = module.FACTORS / module.OUT_DELTA.name
    module.OUT_SCORE = module.FACTORS / module.OUT_SCORE.name
    module.OUT_ELIGIBILITY = module.FACTORS / module.OUT_ELIGIBILITY.name
    module.OUT_MAPPING = module.FACTORS / module.OUT_MAPPING.name
    module.OUT_SAFETY = module.FACTORS / module.OUT_SAFETY.name
    module.OUT_GATE = module.FACTORS / module.OUT_GATE.name
    module.REPORT = module.READ_CENTER / module.REPORT.name


def write_minimal_inputs(module, missing_score: bool = False, gate_ok: bool = True) -> None:
    for path in [module.V166_POLICY, module.V166_WEIGHT, module.V166_ELIGIBILITY, module.V166_BACKLOG, module.V166_SAFETY, module.V166_GATE, module.R1_MAPPING, module.R1_REPAIR, module.R1_UNKNOWN]:
        write_csv(path, [{"id": "x"}])
    write_csv(module.R1_GATE, [{
        "final_status": "PASS_V20_166_R1_DATA_TRUST_STATUS_MAPPING_READY_FOR_V20_166_R2" if gate_ok else "WARN",
        "data_trust_scoring_weight": "0.0000000000",
        "data_trust_role": "GATE_ONLY_AND_REPAIR_DIAGNOSTIC",
    }])
    write_csv(module.R1_READY, [{
        "ready_for_gate_only_ranking_simulation": "TRUE",
        "data_trust_unknown_count": "0",
        "ranking_eligible_after_data_trust_count": "2",
        "direct_ticker_mapping_count": "0",
        "inferred_from_artifact_mapping_count": "2",
    }])
    write_csv(module.R1_STATUS, [
        {"ticker": "AAA", "data_trust_status": "PASS", "data_trust_pass": "TRUE", "data_trust_fail": "FALSE", "data_trust_unknown": "FALSE", "ranking_eligible_after_data_trust_gate": "TRUE", "mapping_confidence": "INFERRED_HIGH"},
        {"ticker": "BBB", "data_trust_status": "PASS", "data_trust_pass": "TRUE", "data_trust_fail": "FALSE", "data_trust_unknown": "FALSE", "ranking_eligible_after_data_trust_gate": "TRUE", "mapping_confidence": "INFERRED_HIGH"},
    ])
    write_csv(module.BASELINE, [
        {"ticker": "AAA", "official_current_rank": "1", "official_current_score": "1", "score_name": "source_rank_or_score"},
        {"ticker": "BBB", "official_current_rank": "2", "official_current_score": "2", "score_name": "source_rank_or_score"},
    ])
    write_csv(module.WEIGHTS, [{"factor_family": "DATA_TRUST", "active_research_base_weight": "0.10"}])
    b_market = "" if missing_score else "0.5"
    write_csv(module.R10_SCORES, [
        {"ticker": "AAA", "fundamental_contribution": "0.1", "technical_contribution": "0.2", "strategy_contribution": "0.3", "risk_contribution": "0.4", "market_regime_contribution": "0.5", "data_trust_contribution": "1.0"},
        {"ticker": "BBB", "fundamental_contribution": "0.5", "technical_contribution": "0.4", "strategy_contribution": "0.3", "risk_contribution": "0.2", "market_regime_contribution": b_market, "data_trust_contribution": "1.0"},
    ])


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
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_166_R2_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION"


def test_blocked_wrong_r1_status_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_minimal_inputs(module, gate_ok=False)
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_166_R2_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION"


def test_temp_mapping_limitation_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_minimal_inputs(module)
        assert module.main() == 0
        summary = read_csv(module.OUT_DELTA)[0]
        gate = read_csv(module.OUT_GATE)[0]
        score = read_csv(module.OUT_SCORE)
        assert summary["gate_only_policy_simulation_success"] == "TRUE"
        assert summary["mapping_confidence_limitation_flag"] == "TRUE"
        assert all(row["data_trust_score_excluded_from_scoring"] == "TRUE" for row in score)
        assert gate["final_status"] == "PARTIAL_PASS_V20_166_R2_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION_WITH_MAPPING_LIMITATIONS_READY_FOR_V20_167"


def test_temp_score_recomputation_blocked_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_minimal_inputs(module, missing_score=True)
        assert module.main() == 0
        gate = read_csv(module.OUT_GATE)[0]
        score = read_csv(module.OUT_SCORE)
        assert any(row["score_recomputation_blocked_reason"] == "MISSING_REQUIRED_FACTOR_FAMILY_SCORE" for row in score)
        assert gate["final_status"] == "WARN_V20_166_R2_DATA_TRUST_GATE_ONLY_SCORE_RECOMPUTATION_BLOCKED"


def test_data_trust_gate_only_ranking_simulation() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.166/R1 or baseline/weight outputs were mutated"
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_166_R2_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION_READY_FOR_V20_167",
        "PARTIAL_PASS_V20_166_R2_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION_WITH_MAPPING_LIMITATIONS_READY_FOR_V20_167",
        "WARN_V20_166_R2_DATA_TRUST_GATE_ONLY_SCORE_RECOMPUTATION_BLOCKED",
    ])
    for expected in [
        "V20_166_R1_GATE_CONSUMED=TRUE",
        "V20_166_R1_STATUS=PASS_V20_166_R1_DATA_TRUST_STATUS_MAPPING_READY_FOR_V20_166_R2",
        "DATA_TRUST_SCORING_WEIGHT=0.0000000000",
        "DATA_TRUST_ROLE=GATE_ONLY_AND_REPAIR_DIAGNOSTIC",
        "RESEARCH_ONLY=TRUE",
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
        "SHADOW_WEIGHT_EXPANSION_ALLOWED=FALSE",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    sim = read_csv(OUT_SIM)
    summary = read_csv(OUT_DELTA)
    score = read_csv(OUT_SCORE)
    eligibility = read_csv(OUT_ELIGIBILITY)
    mapping = read_csv(OUT_MAPPING)
    safety = read_csv(OUT_SAFETY)
    gate = read_csv(OUT_GATE)
    assert sim and summary and score and eligibility and mapping and safety and gate
    assert SIM_COLUMNS.issubset(sim[0].keys()), SIM_COLUMNS - set(sim[0].keys())
    assert SCORE_COLUMNS.issubset(score[0].keys()), SCORE_COLUMNS - set(score[0].keys())
    assert all(row["data_trust_score_excluded_from_scoring"] == "TRUE" for row in score)
    assert all(row["data_trust_scoring_weight_after"] == "0.0000000000" for row in sim)
    assert gate[0]["official_ranking_mutated"] == "FALSE"
    assert gate[0]["official_weight_change_created"] == "FALSE"
    assert all(row["safety_passed"] == "TRUE" for row in safety)
    for rows in [sim, summary, score, eligibility, mapping, safety, gate]:
        assert_safety(rows)


if __name__ == "__main__":
    test_blocked_missing_inputs_case()
    test_blocked_wrong_r1_status_case()
    test_temp_mapping_limitation_case()
    test_temp_score_recomputation_blocked_case()
    test_data_trust_gate_only_ranking_simulation()
    print("PASS_V20_166_R2_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION_TESTS")
