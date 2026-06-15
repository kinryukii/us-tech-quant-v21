#!/usr/bin/env python
"""Tests for V20.155 limited shadow weight ranking simulation."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_155_limited_shadow_weight_ranking_simulation.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUT_SIM = FACTORS / "V20_155_LIMITED_SHADOW_WEIGHT_RANKING_SIMULATION.csv"
OUT_DELTA = FACTORS / "V20_155_SHADOW_VS_BASELINE_RANK_DELTA.csv"
OUT_GATE = FACTORS / "V20_155_SHADOW_RANKING_SIMULATION_GATE.csv"
OUT_SOURCE = FACTORS / "V20_155_SHADOW_RANKING_SOURCE_AUDIT.csv"
OUT_SAFETY = FACTORS / "V20_155_SHADOW_RANKING_SAFETY_AUDIT.csv"
OUT_LIMITATION = FACTORS / "V20_155_SHADOW_RANKING_LIMITATION_AUDIT.csv"
OUT_REPORT = READ_CENTER / "V20_155_LIMITED_SHADOW_WEIGHT_RANKING_SIMULATION_REPORT.md"
OUTPUTS = [OUT_SIM, OUT_DELTA, OUT_GATE, OUT_SOURCE, OUT_SAFETY, OUT_LIMITATION, OUT_REPORT]

SIM_COLUMNS = {
    "ticker",
    "baseline_rank",
    "shadow_rank",
    "rank_delta",
    "baseline_score",
    "shadow_score",
    "score_delta",
    "affected_factor_family",
    "affected_factor_name",
    "applied_shadow_weight_delta",
    "proposal_confidence_level",
    "evidence_quality",
    "baseline_top20_flag",
    "shadow_top20_flag",
    "entered_shadow_top20",
    "exited_shadow_top20",
    "buy_zone_status_if_available",
    "technical_status_if_available",
    "risk_flag_if_available",
    "simulation_scope",
    "official_ranking_mutated",
    "official_weight_change_created",
}
SUMMARY_COLUMNS = {
    "baseline_candidate_count",
    "shadow_candidate_count",
    "top20_overlap_count",
    "entered_top20_count",
    "exited_top20_count",
    "max_absolute_rank_delta",
    "average_absolute_rank_delta",
    "affected_ticker_count",
    "proposal_row_count",
    "low_confidence_proposal_count",
    "limitation_reason",
}
SAFETY_FALSE_FIELDS = [
    "formal_activation_allowed",
    "promotion_ready",
    "official_recommendation_created",
    "official_ranking_mutated",
    "official_weight_change_created",
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
        FACTORS / "V20_154_LIMITED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL.csv",
        FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_GATE.csv",
        FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_SOURCE_AUDIT.csv",
        FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_SAFETY_AUDIT.csv",
        FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_BLOCKED_OFFICIAL_AUDIT.csv",
    ]
    return {path: digest(path) for path in paths if path.exists()}


def load_module():
    spec = importlib.util.spec_from_file_location("v20_155_limited_shadow_weight_ranking_simulation_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    module.OUTPUTS = temp
    module.FACTORS = temp / "factors"
    module.CONSOLIDATION = temp / "consolidation"
    module.READ_CENTER = temp / "read_center"
    module.IN_PROPOSAL = module.FACTORS / "V20_154_LIMITED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL.csv"
    module.IN_GATE = module.FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_GATE.csv"
    module.IN_SOURCE = module.FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_SOURCE_AUDIT.csv"
    module.IN_SAFETY = module.FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_SAFETY_AUDIT.csv"
    module.IN_BLOCKED = module.FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_BLOCKED_OFFICIAL_AUDIT.csv"
    module.V83_RANKING = module.CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
    module.V108_COMPONENTS = module.CONSOLIDATION / "V20_108_R12_SHADOW_SCORE_COMPONENT_CONTRIBUTION_AUDIT.csv"
    module.OPTIONAL_SOURCES = []
    module.OUT_SIM = module.FACTORS / "V20_155_LIMITED_SHADOW_WEIGHT_RANKING_SIMULATION.csv"
    module.OUT_DELTA = module.FACTORS / "V20_155_SHADOW_VS_BASELINE_RANK_DELTA.csv"
    module.OUT_GATE = module.FACTORS / "V20_155_SHADOW_RANKING_SIMULATION_GATE.csv"
    module.OUT_SOURCE = module.FACTORS / "V20_155_SHADOW_RANKING_SOURCE_AUDIT.csv"
    module.OUT_SAFETY = module.FACTORS / "V20_155_SHADOW_RANKING_SAFETY_AUDIT.csv"
    module.OUT_LIMITATION = module.FACTORS / "V20_155_SHADOW_RANKING_LIMITATION_AUDIT.csv"
    module.REPORT = module.READ_CENTER / "V20_155_LIMITED_SHADOW_WEIGHT_RANKING_SIMULATION_REPORT.md"


def copy_inputs(temp: Path) -> None:
    (temp / "factors").mkdir(parents=True, exist_ok=True)
    (temp / "consolidation").mkdir(parents=True, exist_ok=True)
    for filename in [
        "V20_154_LIMITED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL.csv",
        "V20_154_SHADOW_WEIGHT_PROPOSAL_GATE.csv",
        "V20_154_SHADOW_WEIGHT_PROPOSAL_SOURCE_AUDIT.csv",
        "V20_154_SHADOW_WEIGHT_PROPOSAL_SAFETY_AUDIT.csv",
        "V20_154_SHADOW_WEIGHT_PROPOSAL_BLOCKED_OFFICIAL_AUDIT.csv",
    ]:
        shutil.copy2(FACTORS / filename, temp / "factors" / filename)
    for filename in [
        "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
        "V20_108_R12_SHADOW_SCORE_COMPONENT_CONTRIBUTION_AUDIT.csv",
    ]:
        shutil.copy2(CONSOLIDATION / filename, temp / "consolidation" / filename)


def assert_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE in {row}"
        if "shadow_weight_proposal_created" in row:
            assert row["shadow_weight_proposal_created"] == "TRUE"
        if "shadow_ranking_simulation_created" in row:
            assert row["shadow_ranking_simulation_created"] == "TRUE"
        if "shadow_ranking_simulation_scope" in row:
            assert row["shadow_ranking_simulation_scope"] == "RESEARCH_ONLY_LIMITED"


def write_minimal_inputs(module, include_all_components: bool = True) -> None:
    write_csv(module.IN_PROPOSAL, [{
        "factor_family": "RISK",
        "factor_name": "DOWNSIDE_RISK_EVIDENCE",
        "evidence_source": "source.csv",
        "proposed_delta": "-0.006",
        "confidence_level": "LIMITED",
        "evidence_quality": "HIGH",
        "usable_for_shadow_weight_proposal": "TRUE",
        "usable_for_official_weight_change": "FALSE",
    }])
    write_csv(module.IN_GATE, [{"final_status": "PASS_V20_154_LIMITED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL_READY_FOR_V20_155", "v20_155_limited_shadow_simulation_allowed": "TRUE"}])
    write_csv(module.IN_SOURCE, [{"source_audit_id": "S1"}])
    write_csv(module.IN_SAFETY, [{"safety_check_id": "A1"}])
    write_csv(module.IN_BLOCKED, [{"blocked_official_audit_id": "B1"}])
    write_csv(module.V83_RANKING, [
        {"ticker": "AAA", "official_current_rank": "1", "official_current_score": "1"},
        {"ticker": "BBB", "official_current_rank": "2", "official_current_score": "2"},
    ])
    families = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"] if include_all_components else ["RISK"]
    rows = []
    for ticker, risk in [("AAA", 1.0), ("BBB", 0.1)]:
        for family in families:
            rows.append({
                "ticker": ticker,
                "factor_family": family,
                "contribution_value": str(risk if family == "RISK" else 0.5),
                "contribution_available": "TRUE",
                "fabricated_values_created": "FALSE",
            })
    write_csv(module.V108_COMPONENTS, rows)


def test_blocked_missing_inputs_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        assert module.main() == 0
        gate = read_csv(module.OUT_GATE)[0]
        assert gate["final_status"] == "BLOCKED_V20_155_LIMITED_SHADOW_WEIGHT_RANKING_SIMULATION"


def test_temp_score_recompute_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        write_minimal_inputs(module, include_all_components=True)
        assert module.main() == 0
        gate = read_csv(module.OUT_GATE)[0]
        sim = read_csv(module.OUT_SIM)
        assert gate["final_status"] == "PARTIAL_PASS_V20_155_LIMITED_SHADOW_WEIGHT_RANKING_SIMULATION_WITH_LIMITATIONS_READY_FOR_V20_156"
        assert gate["score_recomputation_performed"] == "TRUE"
        assert len(sim) == 2
        assert all(row["official_ranking_mutated"] == "FALSE" for row in sim)
        assert any(float(row["score_delta"]) != 0 for row in sim)


def test_temp_limitation_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        write_minimal_inputs(module, include_all_components=False)
        assert module.main() == 0
        gate = read_csv(module.OUT_GATE)[0]
        limitations = read_csv(module.OUT_LIMITATION)
        assert gate["final_status"] == "PARTIAL_PASS_V20_155_LIMITED_SHADOW_WEIGHT_RANKING_SIMULATION_WITH_LIMITATIONS_READY_FOR_V20_156"
        assert gate["score_recomputation_performed"] == "FALSE"
        assert limitations and limitations[0]["score_recomputation_available"] == "FALSE"


def test_limited_shadow_weight_ranking_simulation() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.154 outputs were mutated"
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_155_LIMITED_SHADOW_WEIGHT_RANKING_SIMULATION_READY_FOR_V20_156",
        "PARTIAL_PASS_V20_155_LIMITED_SHADOW_WEIGHT_RANKING_SIMULATION_WITH_LIMITATIONS_READY_FOR_V20_156",
        "WARN_V20_155_SHADOW_RANKING_SIMULATION_INSUFFICIENT_INPUTS",
    ])
    for expected in [
        "V20_154_GATE_CONSUMED=TRUE",
        "V20_154_ALLOWED_FOR_V20_155=TRUE",
        "OFFICIAL_RANKING_ROWS_MUTATED=0",
        "OFFICIAL_WEIGHT_ROWS_MUTATED=0",
        "TICKER_ROWS_FABRICATED=0",
        "SCORES_FABRICATED=0",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "OFFICIAL_WEIGHTS_MUTATED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "REAL_BOOK_ACTION_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_ACTION_CREATED=FALSE",
        "PERFORMANCE_CLAIM_CREATED=FALSE",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_TRUE_COUNT=0",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    sim = read_csv(OUT_SIM)
    delta = read_csv(OUT_DELTA)
    gate = read_csv(OUT_GATE)
    source = read_csv(OUT_SOURCE)
    safety = read_csv(OUT_SAFETY)
    limitations = read_csv(OUT_LIMITATION)
    assert sim, "simulation output must not be empty"
    assert delta, "summary output must not be empty"
    assert source, "source audit must not be empty"
    assert safety, "safety audit must not be empty"
    assert limitations, "limitation audit must not be empty"
    assert SIM_COLUMNS.issubset(sim[0].keys()), SIM_COLUMNS - set(sim[0].keys())
    assert SUMMARY_COLUMNS.issubset(delta[0].keys()), SUMMARY_COLUMNS - set(delta[0].keys())
    assert int(gate[0]["simulation_row_count"]) == len(sim)
    assert int(delta[0]["baseline_candidate_count"]) == len(sim)
    assert all(row["official_ranking_mutated"] == "FALSE" for row in sim)
    assert all(row["official_weight_change_created"] == "FALSE" for row in sim)
    assert gate[0]["official_ranking_rows_mutated"] == "0"
    assert gate[0]["official_weight_rows_mutated"] == "0"
    for rows in [sim, delta, gate, source, safety, limitations]:
        assert_safety(rows)


if __name__ == "__main__":
    test_blocked_missing_inputs_case()
    test_temp_score_recompute_case()
    test_temp_limitation_case()
    test_limited_shadow_weight_ranking_simulation()
    print("PASS_V20_155_LIMITED_SHADOW_WEIGHT_RANKING_SIMULATION_TESTS")
