#!/usr/bin/env python
"""Tests for V20.166-R3 DATA_TRUST score lineage and baseline binding audit."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_166_r3_data_trust_gate_only_score_lineage_and_baseline_binding_audit.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUT_LINEAGE = FACTORS / "V20_166_R3_DATA_TRUST_SCORE_LINEAGE_AUDIT.csv"
OUT_WEIGHT_BINDING = FACTORS / "V20_166_R3_DATA_TRUST_WEIGHT_BINDING_AUDIT.csv"
OUT_NORMALIZATION = FACTORS / "V20_166_R3_DATA_TRUST_SCORE_NORMALIZATION_AUDIT.csv"
OUT_REPAIR = FACTORS / "V20_166_R3_DATA_TRUST_BASELINE_BINDING_REPAIR.csv"
OUT_SIM = FACTORS / "V20_166_R3_BOUND_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION.csv"
OUT_DELTA = FACTORS / "V20_166_R3_BOUND_DATA_TRUST_GATE_ONLY_RANK_DELTA.csv"
OUT_MAPPING = FACTORS / "V20_166_R3_MAPPING_CONFIDENCE_LIMITATION_AUDIT.csv"
OUT_GATE = FACTORS / "V20_166_R3_DATA_TRUST_NEXT_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_166_R3_DATA_TRUST_GATE_ONLY_SCORE_LINEAGE_AND_BASELINE_BINDING_AUDIT_REPORT.md"
OUTPUTS = [OUT_LINEAGE, OUT_WEIGHT_BINDING, OUT_NORMALIZATION, OUT_REPAIR, OUT_SIM, OUT_DELTA, OUT_MAPPING, OUT_GATE, OUT_REPORT]

SIM_COLUMNS = {
    "ticker", "authoritative_baseline_rank", "authoritative_baseline_score",
    "data_trust_status", "data_trust_mapping_confidence", "data_trust_gate_pass",
    "bound_gate_only_score", "bound_gate_only_rank", "bound_score_delta",
    "bound_rank_delta", "baseline_top20_flag", "bound_gate_only_top20_flag",
    "entered_bound_gate_only_top20", "exited_bound_gate_only_top20",
    "data_trust_scoring_weight_before", "data_trust_scoring_weight_after",
    "scoring_weight_renormalization_applied", "baseline_score_source",
    "baseline_rank_source", "score_binding_success", "official_ranking_mutated",
    "official_weight_change_created",
}
SUMMARY_COLUMNS = {
    "baseline_candidate_count", "bound_gate_only_candidate_count",
    "data_trust_pass_count", "data_trust_fail_count", "data_trust_unknown_count",
    "direct_ticker_mapping_count", "inferred_from_artifact_mapping_count",
    "mapping_confidence_limitation_flag", "prior_unbound_top20_turnover_rate",
    "bound_top20_turnover_rate", "prior_unbound_max_absolute_rank_delta",
    "bound_max_absolute_rank_delta", "prior_unbound_average_absolute_rank_delta",
    "bound_average_absolute_rank_delta", "baseline_binding_improved_rank_stability",
    "remaining_rank_impact_severity", "ready_for_operator_review",
    "recommended_next_action",
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
        FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION.csv",
        FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_RANK_DELTA.csv",
        FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_SCORE_AUDIT.csv",
        FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_ELIGIBILITY_AUDIT.csv",
        FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_MAPPING_CONFIDENCE_AUDIT.csv",
        FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_SAFETY_AUDIT.csv",
        FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_NEXT_GATE.csv",
        FACTORS / "V20_166_R1_DATA_TRUST_TICKER_STATUS.csv",
        FACTORS / "V20_166_R1_DATA_TRUST_GATE_READY_AUDIT.csv",
        CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
        CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv",
    ]
    return {path: digest(path) for path in paths if path.exists()}


def load_module():
    spec = importlib.util.spec_from_file_location("v20_166_r3_case", SCRIPT)
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
        "R2_SIM", "R2_DELTA", "R2_SCORE", "R2_ELIGIBILITY", "R2_MAPPING", "R2_SAFETY", "R2_GATE",
        "R1_STATUS", "R1_READY", "V166_POLICY", "V166_WEIGHT",
    ]:
        setattr(module, name, module.FACTORS / getattr(module, name).name)
    for name in ["BASELINE", "WEIGHTS", "R10_SCORES"]:
        setattr(module, name, module.CONSOLIDATION / getattr(module, name).name)
    for name in ["OUT_LINEAGE", "OUT_WEIGHT_BINDING", "OUT_NORMALIZATION", "OUT_REPAIR", "OUT_SIM", "OUT_DELTA", "OUT_MAPPING", "OUT_GATE"]:
        setattr(module, name, module.FACTORS / getattr(module, name).name)
    module.REPORT = module.READ_CENTER / module.REPORT.name


def write_minimal_inputs(module, gate_ok: bool = True) -> None:
    for path in [module.R2_SIM, module.R2_ELIGIBILITY, module.R2_MAPPING, module.R2_SAFETY, module.V166_POLICY, module.V166_WEIGHT, module.WEIGHTS, module.R10_SCORES]:
        write_csv(path, [{"id": "x"}])
    write_csv(module.R2_GATE, [{
        "final_status": "PARTIAL_PASS_V20_166_R2_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION_WITH_MAPPING_LIMITATIONS_READY_FOR_V20_167" if gate_ok else "WARN",
        "data_trust_scoring_weight": "0.0000000000",
        "data_trust_role": "GATE_ONLY_AND_REPAIR_DIAGNOSTIC",
        "official_ranking_mutated": "FALSE",
        "official_weight_change_created": "FALSE",
    }])
    write_csv(module.R2_DELTA, [{
        "baseline_candidate_count": "2",
        "ranking_candidate_count_after_data_trust_gate": "2",
        "data_trust_pass_count": "40" if gate_ok else "2",
        "data_trust_unknown_count": "0",
        "top20_turnover_rate": "0.9000000000",
        "max_absolute_rank_delta": "39",
        "average_absolute_rank_delta": "13.5750000000",
        "exited_top20_count": "1",
    }])
    write_csv(module.R2_SCORE, [
        {"ticker": "AAA", "all_required_scoring_families_available": "TRUE"},
        {"ticker": "BBB", "all_required_scoring_families_available": "TRUE"},
    ])
    write_csv(module.R1_STATUS, [
        {"ticker": "AAA", "data_trust_status": "PASS", "data_trust_pass": "TRUE", "mapping_confidence": "INFERRED_HIGH"},
        {"ticker": "BBB", "data_trust_status": "PASS", "data_trust_pass": "TRUE", "mapping_confidence": "INFERRED_HIGH"},
    ])
    write_csv(module.R1_READY, [{"data_trust_pass_count": "2", "data_trust_fail_count": "0", "data_trust_unknown_count": "0", "direct_ticker_mapping_count": "0", "inferred_from_artifact_mapping_count": "2"}])
    write_csv(module.BASELINE, [
        {"ticker": "AAA", "official_current_rank": "1", "official_current_score": "1"},
        {"ticker": "BBB", "official_current_rank": "2", "official_current_score": "2"},
    ])


def test_blocked_missing_inputs_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_166_R3_DATA_TRUST_SCORE_LINEAGE_AUDIT"


def test_blocked_wrong_r2_status_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_minimal_inputs(module, gate_ok=False)
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_166_R3_DATA_TRUST_SCORE_LINEAGE_AUDIT"


def test_temp_baseline_binding_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_minimal_inputs(module)
        assert module.main() == 0
        sim = read_csv(module.OUT_SIM)
        summary = read_csv(module.OUT_DELTA)[0]
        gate = read_csv(module.OUT_GATE)[0]
        assert all(row["bound_rank_delta"] == "0" for row in sim)
        assert summary["bound_top20_turnover_rate"] == "0.0000000000"
        assert summary["baseline_binding_improved_rank_stability"] == "TRUE"
        assert gate["final_status"] == "PARTIAL_PASS_V20_166_R3_DATA_TRUST_BASELINE_BINDING_WITH_MAPPING_LIMITATIONS_READY_FOR_V20_167"


def test_data_trust_score_lineage_and_baseline_binding_audit() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream R2/R1/baseline/weight outputs were mutated"
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_166_R3_DATA_TRUST_BASELINE_BINDING_REPAIR_READY_FOR_V20_167",
        "PARTIAL_PASS_V20_166_R3_DATA_TRUST_BASELINE_BINDING_WITH_MAPPING_LIMITATIONS_READY_FOR_V20_167",
        "WARN_V20_166_R3_DATA_TRUST_SCORE_LINEAGE_UNRESOLVED",
    ])
    for expected in [
        "BASELINE_BINDING_IMPROVED_RANK_STABILITY=TRUE",
        "BOUND_TOP20_TURNOVER_RATE=0.0000000000",
        "BOUND_MAX_ABSOLUTE_RANK_DELTA=0",
        "READY_FOR_OPERATOR_REVIEW=TRUE",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    sim = read_csv(OUT_SIM)
    summary = read_csv(OUT_DELTA)
    lineage = read_csv(OUT_LINEAGE)
    gate = read_csv(OUT_GATE)
    assert sim and summary and lineage and gate
    assert SIM_COLUMNS.issubset(sim[0].keys()), SIM_COLUMNS - set(sim[0].keys())
    assert SUMMARY_COLUMNS.issubset(summary[0].keys()), SUMMARY_COLUMNS - set(summary[0].keys())
    assert all(row["official_ranking_mutated"] == "FALSE" for row in sim)
    assert all(row["official_weight_change_created"] == "FALSE" for row in sim)
    assert gate[0]["no_upstream_outputs_mutated"] == "TRUE"


if __name__ == "__main__":
    test_blocked_missing_inputs_case()
    test_blocked_wrong_r2_status_case()
    test_temp_baseline_binding_case()
    test_data_trust_score_lineage_and_baseline_binding_audit()
    print("PASS_V20_166_R3_DATA_TRUST_SCORE_LINEAGE_AND_BASELINE_BINDING_AUDIT_TESTS")
