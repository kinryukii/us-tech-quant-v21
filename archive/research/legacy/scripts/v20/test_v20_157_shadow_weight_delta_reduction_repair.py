#!/usr/bin/env python
"""Tests for V20.157 shadow weight delta reduction repair."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_157_shadow_weight_delta_reduction_repair.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUT_REPAIR = FACTORS / "V20_157_SHADOW_WEIGHT_DELTA_REDUCTION_REPAIR.csv"
OUT_PROPOSAL = FACTORS / "V20_157_REDUCED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL.csv"
OUT_GATE = FACTORS / "V20_157_DELTA_REDUCTION_GATE.csv"
OUT_SOURCE = FACTORS / "V20_157_DELTA_REDUCTION_SOURCE_AUDIT.csv"
OUT_SAFETY = FACTORS / "V20_157_DELTA_REDUCTION_SAFETY_AUDIT.csv"
OUT_LIMITATION = FACTORS / "V20_157_DELTA_REDUCTION_LIMITATION_AUDIT.csv"
OUT_REPORT = READ_CENTER / "V20_157_SHADOW_WEIGHT_DELTA_REDUCTION_REPAIR_REPORT.md"
OUTPUTS = [OUT_REPAIR, OUT_PROPOSAL, OUT_GATE, OUT_SOURCE, OUT_SAFETY, OUT_LIMITATION, OUT_REPORT]

REPAIR_COLUMNS = {
    "factor_family",
    "factor_name",
    "evidence_source",
    "original_shadow_proposed_weight",
    "original_proposed_delta",
    "reduced_shadow_proposed_weight",
    "reduced_proposed_delta",
    "original_max_allowed_delta",
    "reduced_max_allowed_delta",
    "reduction_multiplier",
    "confidence_level",
    "evidence_quality",
    "rank_impact_severity_from_v20_156",
    "top20_turnover_rate_from_v20_156",
    "delta_reduction_reason",
    "conservative_mode_applied",
    "usable_for_reduced_shadow_simulation",
    "usable_for_official_weight_change",
    "official_weight_change_blocked_reason",
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
        FACTORS / "V20_156_SHADOW_RANKING_STABILITY_REVIEW.csv",
        FACTORS / "V20_156_SHADOW_RANKING_OPERATOR_REVIEW_PACKET.csv",
        FACTORS / "V20_156_SHADOW_RANKING_IMPACT_GUARDRAIL_AUDIT.csv",
        FACTORS / "V20_156_SHADOW_RANKING_LOW_CONFIDENCE_AUDIT.csv",
        FACTORS / "V20_156_SHADOW_RANKING_NEXT_GATE.csv",
        FACTORS / "V20_154_LIMITED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL.csv",
        FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_GATE.csv",
        FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_SAFETY_AUDIT.csv",
    ]
    return {path: digest(path) for path in paths if path.exists()}


def load_module():
    spec = importlib.util.spec_from_file_location("v20_157_shadow_weight_delta_reduction_repair_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    module.OUTPUTS = temp
    module.FACTORS = temp / "factors"
    module.READ_CENTER = temp / "read_center"
    module.V156_REVIEW = module.FACTORS / "V20_156_SHADOW_RANKING_STABILITY_REVIEW.csv"
    module.V156_OPERATOR = module.FACTORS / "V20_156_SHADOW_RANKING_OPERATOR_REVIEW_PACKET.csv"
    module.V156_GUARDRAIL = module.FACTORS / "V20_156_SHADOW_RANKING_IMPACT_GUARDRAIL_AUDIT.csv"
    module.V156_LOW_CONF = module.FACTORS / "V20_156_SHADOW_RANKING_LOW_CONFIDENCE_AUDIT.csv"
    module.V156_GATE = module.FACTORS / "V20_156_SHADOW_RANKING_NEXT_GATE.csv"
    module.V154_PROPOSAL = module.FACTORS / "V20_154_LIMITED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL.csv"
    module.V154_GATE = module.FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_GATE.csv"
    module.V154_SAFETY = module.FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_SAFETY_AUDIT.csv"
    module.OUT_REPAIR = module.FACTORS / "V20_157_SHADOW_WEIGHT_DELTA_REDUCTION_REPAIR.csv"
    module.OUT_PROPOSAL = module.FACTORS / "V20_157_REDUCED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL.csv"
    module.OUT_GATE = module.FACTORS / "V20_157_DELTA_REDUCTION_GATE.csv"
    module.OUT_SOURCE = module.FACTORS / "V20_157_DELTA_REDUCTION_SOURCE_AUDIT.csv"
    module.OUT_SAFETY = module.FACTORS / "V20_157_DELTA_REDUCTION_SAFETY_AUDIT.csv"
    module.OUT_LIMITATION = module.FACTORS / "V20_157_DELTA_REDUCTION_LIMITATION_AUDIT.csv"
    module.REPORT = module.READ_CENTER / "V20_157_SHADOW_WEIGHT_DELTA_REDUCTION_REPAIR_REPORT.md"


def copy_inputs(temp: Path) -> None:
    (temp / "factors").mkdir(parents=True, exist_ok=True)
    for filename in [
        "V20_156_SHADOW_RANKING_STABILITY_REVIEW.csv",
        "V20_156_SHADOW_RANKING_OPERATOR_REVIEW_PACKET.csv",
        "V20_156_SHADOW_RANKING_IMPACT_GUARDRAIL_AUDIT.csv",
        "V20_156_SHADOW_RANKING_LOW_CONFIDENCE_AUDIT.csv",
        "V20_156_SHADOW_RANKING_NEXT_GATE.csv",
        "V20_154_LIMITED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL.csv",
        "V20_154_SHADOW_WEIGHT_PROPOSAL_GATE.csv",
        "V20_154_SHADOW_WEIGHT_PROPOSAL_SAFETY_AUDIT.csv",
    ]:
        shutil.copy2(FACTORS / filename, temp / "factors" / filename)


def assert_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE in {row}"
        if "shadow_weight_proposal_created" in row:
            assert row["shadow_weight_proposal_created"] == "TRUE"
        if "reduced_shadow_weight_proposal_created" in row:
            assert row["reduced_shadow_weight_proposal_created"] == "TRUE"
        if "reduced_shadow_weight_proposal_scope" in row:
            assert row["reduced_shadow_weight_proposal_scope"] == "RESEARCH_ONLY_LIMITED_CONSERVATIVE"
        if "shadow_weight_expansion_allowed" in row:
            assert row["shadow_weight_expansion_allowed"] == "FALSE"


def write_minimal_inputs(module, status_ok: bool = True) -> None:
    write_csv(module.V156_REVIEW, [{
        "rank_impact_severity": "EXTREME",
        "top20_turnover_rate": "0.9000000000",
        "required_next_action": "REQUEST_SHADOW_WEIGHT_DELTA_REDUCTION" if status_ok else "APPROVE_CONTINUED_SHADOW_RESEARCH_ONLY",
        "allow_continued_shadow_research": "TRUE",
        "allow_shadow_weight_expansion": "FALSE",
        "allow_official_weight_change": "FALSE",
    }])
    write_csv(module.V156_GATE, [{
        "final_status": "WARN_V20_156_SHADOW_RANKING_IMPACT_TOO_UNSTABLE_FOR_EXPANSION",
        "required_next_action": "REQUEST_SHADOW_WEIGHT_DELTA_REDUCTION" if status_ok else "APPROVE_CONTINUED_SHADOW_RESEARCH_ONLY",
        "allow_continued_shadow_research": "TRUE",
        "allow_shadow_weight_expansion": "FALSE",
        "allow_official_weight_change": "FALSE",
    }])
    write_csv(module.V156_OPERATOR, [{"operator_option": "REQUEST_SHADOW_WEIGHT_DELTA_REDUCTION"}])
    write_csv(module.V156_GUARDRAIL, [{"guardrail_name": "OUTLIER", "risk_level": "HIGH"}])
    write_csv(module.V156_LOW_CONF, [{"ticker": "AAA"}])
    write_csv(module.V154_GATE, [{"final_status": "PARTIAL_PASS_V20_154_LIMITED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL_WITH_LOW_CONFIDENCE_READY_FOR_V20_155"}])
    write_csv(module.V154_SAFETY, [{"safety_check_id": "S1"}])
    write_csv(module.V154_PROPOSAL, [{
        "factor_family": "RISK",
        "factor_name": "DOWNSIDE_RISK_EVIDENCE",
        "evidence_source": "source.csv",
        "current_research_weight": "0.1500000000",
        "shadow_proposed_weight": "0.1440000000",
        "proposed_delta": "-0.0060000000",
        "max_allowed_delta": "0.0120000000",
        "confidence_level": "LIMITED",
        "evidence_quality": "HIGH",
        "usable_for_official_weight_change": "FALSE",
    }])


def test_blocked_missing_inputs_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        assert module.main() == 0
        gate = read_csv(module.OUT_GATE)[0]
        assert gate["final_status"] == "BLOCKED_V20_157_SHADOW_WEIGHT_DELTA_REDUCTION_REPAIR"


def test_blocked_wrong_next_action_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        write_minimal_inputs(module, status_ok=False)
        assert module.main() == 0
        gate = read_csv(module.OUT_GATE)[0]
        assert gate["final_status"] == "BLOCKED_V20_157_SHADOW_WEIGHT_DELTA_REDUCTION_REPAIR"


def test_temp_delta_reduction_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        write_minimal_inputs(module)
        assert module.main() == 0
        gate = read_csv(module.OUT_GATE)[0]
        repair = read_csv(module.OUT_REPAIR)
        assert gate["final_status"] == "PARTIAL_PASS_V20_157_SHADOW_WEIGHT_DELTA_REDUCTION_WITH_LIMITED_CONFIDENCE_READY_FOR_V20_158"
        assert repair[0]["reduction_multiplier"] == "0.2500000000"
        assert abs(float(repair[0]["reduced_proposed_delta"])) <= abs(float(repair[0]["original_proposed_delta"]))
        assert repair[0]["usable_for_official_weight_change"] == "FALSE"


def test_shadow_weight_delta_reduction_repair() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.154/V20.156 outputs were mutated"
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_157_SHADOW_WEIGHT_DELTA_REDUCTION_READY_FOR_V20_158",
        "PARTIAL_PASS_V20_157_SHADOW_WEIGHT_DELTA_REDUCTION_WITH_LIMITED_CONFIDENCE_READY_FOR_V20_158",
        "WARN_V20_157_NO_REDUCIBLE_SHADOW_DELTAS_FOUND",
    ])
    for expected in [
        "V20_156_GATE_CONSUMED=TRUE",
        "REQUIRED_NEXT_ACTION_CONFIRMED=TRUE",
        "CONTINUED_SHADOW_RESEARCH_CONFIRMED=TRUE",
        "SHADOW_WEIGHT_EXPANSION_BLOCKED=TRUE",
        "OFFICIAL_WEIGHT_CHANGE_BLOCKED=TRUE",
        "OFFICIAL_WEIGHT_CHANGE_ELIGIBLE_COUNT=0",
        "DELTA_INCREASE_DETECTED=FALSE",
        "NEW_PROPOSAL_ROWS_CREATED=FALSE",
        "NEW_FACTOR_INCLUDED=FALSE",
        "OFFICIAL_WEIGHT_MUTATION=FALSE",
        "OFFICIAL_RANKING_MUTATION=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "REAL_BOOK_ACTION_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_ACTION_CREATED=FALSE",
        "OUTCOMES_FABRICATED=0",
        "BENCHMARKS_FABRICATED=0",
        "FACTOR_CONTRIBUTION_FABRICATED=0",
        "PERFORMANCE_CLAIM_CREATED=FALSE",
        "REDUCED_SHADOW_WEIGHT_PROPOSAL_SCOPE=RESEARCH_ONLY_LIMITED_CONSERVATIVE",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_TRUE_COUNT=0",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    repair = read_csv(OUT_REPAIR)
    reduced = read_csv(OUT_PROPOSAL)
    gate = read_csv(OUT_GATE)
    source = read_csv(OUT_SOURCE)
    safety = read_csv(OUT_SAFETY)
    limitations = read_csv(OUT_LIMITATION)
    assert repair, "repair output must not be empty"
    assert reduced, "reduced proposal output must not be empty"
    assert source, "source audit must not be empty"
    assert safety, "safety audit must not be empty"
    assert limitations, "limitation audit must not be empty"
    assert REPAIR_COLUMNS.issubset(repair[0].keys()), REPAIR_COLUMNS - set(repair[0].keys())
    assert len(repair) == len(reduced)
    assert int(gate[0]["input_proposal_row_count"]) == len(repair)
    assert int(gate[0]["reduced_proposal_row_count"]) == len(reduced)
    assert all(abs(float(row["reduced_proposed_delta"])) <= abs(float(row["original_proposed_delta"])) + 1e-12 for row in repair)
    assert all(float(row["reduction_multiplier"]) <= 0.25 + 1e-12 for row in repair if row["rank_impact_severity_from_v20_156"] == "EXTREME")
    assert all(row["usable_for_official_weight_change"] == "FALSE" for row in repair)
    for rows in [repair, reduced, gate, source, safety, limitations]:
        assert_safety(rows)


if __name__ == "__main__":
    test_blocked_missing_inputs_case()
    test_blocked_wrong_next_action_case()
    test_temp_delta_reduction_case()
    test_shadow_weight_delta_reduction_repair()
    print("PASS_V20_157_SHADOW_WEIGHT_DELTA_REDUCTION_REPAIR_TESTS")
