#!/usr/bin/env python
"""Tests for V20.170 DATA_TRUST direct status contract and emitter repair."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_170_data_trust_direct_status_contract_and_emitter_repair.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUT_CONTRACT = FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_CONTRACT.csv"
OUT_DISCOVERY = FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_SOURCE_DISCOVERY.csv"
OUT_EMITTER = FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_EMITTER.csv"
OUT_STATUS = FACTORS / "V20_170_DATA_TRUST_DIRECT_PASS_FAIL_UNKNOWN.csv"
OUT_BACKLOG = FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_REPAIR_BACKLOG.csv"
OUT_COVERAGE = FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_COVERAGE_AUDIT.csv"
OUT_GATE = FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_NEXT_GATE.csv"
OUT_SAFETY = FACTORS / "V20_170_DATA_TRUST_DIRECT_STATUS_SAFETY_AUDIT.csv"
OUT_REPORT = READ_CENTER / "V20_170_DATA_TRUST_DIRECT_STATUS_CONTRACT_AND_EMITTER_REPAIR_REPORT.md"
OUTPUTS = [OUT_CONTRACT, OUT_DISCOVERY, OUT_EMITTER, OUT_STATUS, OUT_BACKLOG, OUT_COVERAGE, OUT_GATE, OUT_SAFETY, OUT_REPORT]

WARN_STATUS = "WARN_V20_170_DIRECT_STATUS_EMITTER_CREATED_BUT_NO_DIRECT_PASS_ROWS"
BLOCKED_STATUS = "BLOCKED_V20_170_DATA_TRUST_DIRECT_STATUS_CONTRACT_AND_EMITTER_REPAIR"
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
CONTRACT_COLUMNS = {
    "contract_field",
    "required_for_direct_pass",
    "accepted_source_type",
    "accepted_source_artifact",
    "accepted_source_field",
    "direct_evidence_required",
    "aggregate_evidence_allowed",
    "fail_condition",
    "unknown_condition",
    "repair_action_if_missing",
}
EMITTER_COLUMNS = {
    "ticker",
    "baseline_rank",
    "ticker_identity_match",
    "price_data_available",
    "required_factor_family_scores_available",
    "fundamental_score_available",
    "technical_score_available",
    "strategy_score_available",
    "risk_score_available",
    "market_regime_score_available",
    "data_trust_score_excluded_from_scoring",
    "source_quality_status",
    "freshness_status",
    "pit_safety_status",
    "schema_status",
    "current_ranking_eligibility_status",
    "score_lineage_bindable",
    "direct_data_trust_status",
    "direct_data_trust_pass",
    "direct_data_trust_fail",
    "direct_data_trust_unknown",
    "direct_status_source_artifacts",
    "direct_status_source_fields",
    "direct_status_confidence",
    "failure_or_unknown_reason",
    "repair_required",
    "recommended_repair_action",
}
DISCOVERY_COLUMNS = {
    "source_artifact",
    "artifact_exists",
    "row_count",
    "ticker_level",
    "has_ticker_column",
    "ticker_column_name",
    "has_price_data_field",
    "has_factor_family_score_fields",
    "has_source_quality_field",
    "has_freshness_field",
    "has_pit_safety_field",
    "has_schema_status_field",
    "has_ranking_eligibility_field",
    "usable_for_direct_status_emitter",
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
        FACTORS / "V20_169_DATA_TRUST_DIRECT_MAPPING_SOURCE_SCAN.csv",
        FACTORS / "V20_169_DATA_TRUST_DIRECT_TICKER_MAPPING.csv",
        FACTORS / "V20_169_DATA_TRUST_DIRECT_PASS_FAIL_STATUS.csv",
        FACTORS / "V20_169_DATA_TRUST_DIRECT_MAPPING_REPAIR_AUDIT.csv",
        FACTORS / "V20_169_DATA_TRUST_DIRECT_MAPPING_REMAINING_BACKLOG.csv",
        FACTORS / "V20_169_DATA_TRUST_DIRECT_MAPPING_COVERAGE_SUMMARY.csv",
        FACTORS / "V20_169_DATA_TRUST_DIRECT_MAPPING_NEXT_GATE.csv",
        FACTORS / "V20_169_DATA_TRUST_DIRECT_MAPPING_SAFETY_AUDIT.csv",
        CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
        CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv",
    ]
    return {path: digest(path) for path in paths if path.exists()}


def load_module():
    spec = importlib.util.spec_from_file_location("v20_170_direct_status_case", SCRIPT)
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
    for name in ["V169_SCAN", "V169_MAPPING", "V169_STATUS", "V169_REPAIR", "V169_BACKLOG", "V169_SUMMARY", "V169_GATE", "V169_SAFETY"]:
        setattr(module, name, module.FACTORS / getattr(module, name).name)
    module.BASELINE = module.CONSOLIDATION / module.BASELINE.name
    module.WEIGHTS = module.CONSOLIDATION / module.WEIGHTS.name
    module.R10_SCORES = module.CONSOLIDATION / module.R10_SCORES.name
    module.SOURCE_CANDIDATES = [module.R10_SCORES]
    for name in ["OUT_CONTRACT", "OUT_DISCOVERY", "OUT_EMITTER", "OUT_STATUS", "OUT_BACKLOG", "OUT_COVERAGE", "OUT_GATE", "OUT_SAFETY"]:
        setattr(module, name, module.FACTORS / getattr(module, name).name)
    module.REPORT = module.READ_CENTER / module.REPORT.name


def write_common_inputs(module, status_ok: bool = True) -> None:
    status = "WARN_V20_169_NO_DIRECT_TICKER_LEVEL_DATA_TRUST_MAPPING_RECOVERED" if status_ok else "PASS"
    write_csv(module.V169_SCAN, [{"source_artifact": "X"}])
    write_csv(module.V169_MAPPING, [{"ticker": "AAA"}])
    write_csv(module.V169_STATUS, [{"ticker": "AAA"}])
    write_csv(module.V169_REPAIR, [{"repair_audit_id": "R"}])
    write_csv(module.V169_BACKLOG, [{"ticker": "AAA"}])
    write_csv(module.V169_SUMMARY, [{"summary_id": "S"}])
    write_csv(module.V169_GATE, [{
        "final_status": status,
        "data_trust_scoring_weight": "0.0000000000",
        "data_trust_role": "GATE_ONLY_AND_REPAIR_DIAGNOSTIC",
        "ready_for_direct_mapping_gate_only_ranking_simulation": "FALSE",
        "ready_for_official_use": "FALSE",
    }])
    write_csv(module.V169_SAFETY, [{"safety_check_id": "S"}])
    write_csv(module.BASELINE, [{
        "ticker": "AAA",
        "official_current_rank": "1",
        "official_current_score": "1",
        "latest_price": "10",
        "latest_price_date": "2026-06-05",
        "certification_status": "CERTIFIED",
        "accepted_artifact_validation_status": "PASS",
        "exact_artifact_proof_status": "FOUND",
        "source_file": "source.csv",
    }])
    write_csv(module.WEIGHTS, [{"factor_family": "DATA_TRUST", "is_official_weight": "FALSE"}])
    write_csv(module.R10_SCORES, [{
        "ticker": "AAA",
        "fundamental_contribution": "1",
        "technical_contribution": "1",
        "strategy_contribution": "1",
        "risk_contribution": "1",
        "market_regime_contribution": "1",
        "fundamental_materialization_status": "PASS",
        "technical_materialization_status": "PASS",
        "strategy_materialization_status": "PASS",
        "risk_materialization_status": "PASS",
        "market_regime_materialization_status": "PASS",
    }])


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


def test_blocked_wrong_v169_status_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_common_inputs(module, status_ok=False)
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == BLOCKED_STATUS


def test_temp_emitter_created_but_unknown_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_common_inputs(module)
        assert module.main() == 0
        contract = read_csv(module.OUT_CONTRACT)
        emitter = read_csv(module.OUT_EMITTER)
        summary = read_csv(module.OUT_COVERAGE)[0]
        gate = read_csv(module.OUT_GATE)[0]
        assert len(contract) == 10
        assert emitter[0]["ticker"] == "AAA"
        assert emitter[0]["required_factor_family_scores_available"] == "TRUE"
        assert emitter[0]["pit_safety_status"] == "UNKNOWN"
        assert emitter[0]["direct_data_trust_unknown"] == "TRUE"
        assert summary["direct_status_emitter_created"] == "TRUE"
        assert gate["final_status"] == WARN_STATUS


def test_data_trust_direct_status_contract_and_emitter_repair() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.169/base outputs were mutated"
    stdout = result.stdout
    for expected in [
        WARN_STATUS,
        "V20_169_GATE_CONSUMED=TRUE",
        "DATA_TRUST_SCORING_WEIGHT=0.0000000000",
        "DATA_TRUST_ROLE=GATE_ONLY_AND_REPAIR_DIAGNOSTIC",
        "DIRECT_STATUS_CONTRACT_CREATED=TRUE",
        "DIRECT_STATUS_EMITTER_CREATED=TRUE",
        "BASELINE_CANDIDATE_COUNT=40",
        "DIRECT_DATA_TRUST_PASS_COUNT=0",
        "DIRECT_DATA_TRUST_UNKNOWN_COUNT=40",
        "READY_FOR_DIRECT_STATUS_GATE_ONLY_RANKING_SIMULATION=FALSE",
        "READY_FOR_OFFICIAL_USE=FALSE",
        "OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE",
        "OFFICIAL_RANKING_MUTATION_ALLOWED=FALSE",
        "RANKING_SIMULATION_CREATED=FALSE",
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
    contract = read_csv(OUT_CONTRACT)
    discovery = read_csv(OUT_DISCOVERY)
    emitter = read_csv(OUT_EMITTER)
    status_rows = read_csv(OUT_STATUS)
    backlog = read_csv(OUT_BACKLOG)
    coverage = read_csv(OUT_COVERAGE)
    gate = read_csv(OUT_GATE)
    safety = read_csv(OUT_SAFETY)
    assert contract and discovery and emitter and status_rows and backlog and coverage and gate and safety
    assert CONTRACT_COLUMNS.issubset(contract[0].keys()), CONTRACT_COLUMNS - set(contract[0].keys())
    assert DISCOVERY_COLUMNS.issubset(discovery[0].keys()), DISCOVERY_COLUMNS - set(discovery[0].keys())
    assert EMITTER_COLUMNS.issubset(emitter[0].keys()), EMITTER_COLUMNS - set(emitter[0].keys())
    assert len(emitter) == 40
    assert len(status_rows) == 40
    assert len(backlog) == 40
    assert coverage[0]["direct_status_contract_created"] == "TRUE"
    assert coverage[0]["direct_status_emitter_created"] == "TRUE"
    assert coverage[0]["ready_for_official_use"] == "FALSE"
    assert gate[0]["final_status"] == WARN_STATUS
    assert gate[0]["ranking_simulation_created"] == "FALSE"
    assert all(row["safety_passed"] == "TRUE" for row in safety)
    for rows in [emitter, status_rows, gate, safety]:
        assert_safety(rows)
    assert "Aggregate evidence and inferred mapping are not treated as direct" in OUT_REPORT.read_text(encoding="utf-8")


if __name__ == "__main__":
    test_blocked_missing_inputs_case()
    test_blocked_wrong_v169_status_case()
    test_temp_emitter_created_but_unknown_case()
    test_data_trust_direct_status_contract_and_emitter_repair()
    print("PASS_V20_170_DATA_TRUST_DIRECT_STATUS_CONTRACT_AND_EMITTER_REPAIR_TESTS")
