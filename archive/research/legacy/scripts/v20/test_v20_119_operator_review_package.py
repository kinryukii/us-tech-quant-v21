#!/usr/bin/env python
"""Tests for V20.119 operator review package."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_119_operator_review_package.py"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"

OUT_DECISION = CONSOLIDATION / "V20_119_OPERATOR_REVIEW_PACKAGE_DECISION.csv"
OUT_SUMMARY = CONSOLIDATION / "V20_119_OPERATOR_REVIEW_BLOCKER_SUMMARY.csv"
OUT_MANIFEST = CONSOLIDATION / "V20_119_OPERATOR_REVIEW_EVIDENCE_MANIFEST.csv"
OUT_REQUIRED = CONSOLIDATION / "V20_119_OPERATOR_REVIEW_REQUIRED_DECISIONS.csv"
OUT_SAFETY = CONSOLIDATION / "V20_119_OPERATOR_REVIEW_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_119_NEXT_STAGE_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_119_OPERATOR_REVIEW_PACKAGE_REPORT.md"
OUTPUTS = [OUT_DECISION, OUT_SUMMARY, OUT_MANIFEST, OUT_REQUIRED, OUT_SAFETY, OUT_GATE, OUT_REPORT]
UPSTREAM = [CONSOLIDATION / f"V20_{n}_NEXT_STAGE_GATE.csv" for n in ["110", "111", "112", "113", "114", "115", "116", "117", "118"]]
UPSTREAM.append(CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv")

REQUIRED_COLUMNS = {
    OUT_DECISION: {"v20_118_gate_consumed", "selected_repair_scenario_id", "blocker_summary_created", "evidence_manifest_created", "required_decisions_created", "promotion_ready", "v20_120_operator_decision_record_allowed", "operator_review_package_status"},
    OUT_SUMMARY: {"blocker_category", "blocker_resolved", "operator_review_required", "promotion_ready"},
    OUT_MANIFEST: {"artifact_path", "artifact_exists", "evidence_traceable", "official_artifact"},
    OUT_REQUIRED: {"blocker_category", "required_operator_decision", "decision_required", "promotion_ready"},
    OUT_SAFETY: {"prohibited_field", "observed_true_count", "safety_boundary_passed"},
    OUT_GATE: {"v20_118_gate_consumed", "selected_repair_scenario_id", "promotion_ready", "v20_120_operator_decision_record_allowed", "operator_review_package_status"},
}
PROHIBITED_FALSE_FIELDS = [
    "accepted_weight_created", "accepted_weights_created", "real_book_weight_created", "real_book_action_created",
    "official_weight_created", "official_weights_created", "official_ranking_created", "official_rankings_created",
    "official_recommendation_created", "official_recommendations_created", "trade_action_created", "trade_actions_created",
    "broker_action_created", "broker_actions_created", "authoritative_overwrite_created", "authoritative_overwrites_created",
    "authoritative_ranking_overwritten", "weight_mutated", "weight_mutations_created",
    "performance_claim_created", "performance_claims_created", "performance_effectiveness_claim_created",
    "official_promotion_allowed", "is_official_weight", "promotion_ready",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def upstream_hashes() -> dict[Path, str]:
    return {path: digest(path) for path in UPSTREAM if path.exists()}


def assert_false(rows: list[dict[str, str]], field: str) -> None:
    bad = [row for row in rows if row.get(field) not in {"", "FALSE"}]
    assert not bad, f"{field} was not FALSE: {bad[:3]}"


def load_module():
    spec = importlib.util.spec_from_file_location("v20_119_operator_review_package_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_blocked_missing_input_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        for name in ["IN_DECISION", "IN_STATUS", "IN_EVIDENCE", "IN_REMAINING", "IN_SAFETY", "IN_GATE"]:
            setattr(module, name, temp / f"missing_{name}.csv")
        module.REQUIRED_INPUTS = [module.IN_DECISION, module.IN_STATUS, module.IN_EVIDENCE, module.IN_REMAINING, module.IN_SAFETY, module.IN_GATE]
        module.OUT_DECISION = temp / "V20_119_OPERATOR_REVIEW_PACKAGE_DECISION.csv"
        module.OUT_SUMMARY = temp / "V20_119_OPERATOR_REVIEW_BLOCKER_SUMMARY.csv"
        module.OUT_MANIFEST = temp / "V20_119_OPERATOR_REVIEW_EVIDENCE_MANIFEST.csv"
        module.OUT_REQUIRED = temp / "V20_119_OPERATOR_REVIEW_REQUIRED_DECISIONS.csv"
        module.OUT_SAFETY = temp / "V20_119_OPERATOR_REVIEW_SAFETY_BOUNDARY_AUDIT.csv"
        module.OUT_GATE = temp / "V20_119_NEXT_STAGE_GATE.csv"
        module.REPORT = temp / "V20_119_OPERATOR_REVIEW_PACKAGE_REPORT.md"
        assert module.main() == 0
        blocked = read_csv(module.OUT_DECISION)[0]
        assert blocked["operator_review_package_status"] == "BLOCKED_V20_119_OPERATOR_REVIEW_PACKAGE"
        assert blocked["promotion_ready"] == "FALSE"


def test_operator_review_package() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.109-V20.118 outputs were mutated"
    stdout = result.stdout
    assert "PASS_V20_119_OPERATOR_REVIEW_PACKAGE_READY_FOR_V20_120" in stdout
    for expected in [
        "V20_118_GATE_CONSUMED=TRUE",
        "V20_119_OPERATOR_REVIEW_PACKAGE_ALLOWED_BY_V118=TRUE",
        "SELECTED_SCENARIO_MATCHES_V20_118=TRUE",
        "BLOCKER_SUMMARY_CREATED=TRUE",
        "EVIDENCE_MANIFEST_CREATED=TRUE",
        "REQUIRED_DECISIONS_CREATED=TRUE",
        "PROMOTION_READY=FALSE",
        "FABRICATED_TICKER_ROW_COUNT=0",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
        "SAFETY_BOUNDARY_AUDIT_PASSED=TRUE",
        "PROHIBITED_ACTION_TRUE_COUNT=0",
        "V20_120_OPERATOR_DECISION_RECORD_ALLOWED=TRUE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    for path, columns in REQUIRED_COLUMNS.items():
        rows = read_csv(path)
        assert rows, f"empty output {path}"
        assert columns.issubset(rows[0].keys()), f"missing columns in {path}: {columns - set(rows[0].keys())}"
    decision = read_csv(OUT_DECISION)
    summary = read_csv(OUT_SUMMARY)
    manifest = read_csv(OUT_MANIFEST)
    required = read_csv(OUT_REQUIRED)
    safety = read_csv(OUT_SAFETY)
    gate = read_csv(OUT_GATE)
    d = decision[0]
    assert d["selected_repair_scenario_id"] == EXPECTED_SCENARIO_ID
    assert d["operator_review_package_status"] == "PASS_V20_119_OPERATOR_REVIEW_PACKAGE_READY_FOR_V20_120"
    assert d["promotion_ready"] == "FALSE"
    unresolved = {row["blocker_category"] for row in summary if row["operator_review_required"] == "TRUE"}
    required_categories = {row["blocker_category"] for row in required}
    assert unresolved == required_categories
    assert len(required) == int(d["unresolved_blocker_count"])
    assert manifest and all(row["official_artifact"] == "FALSE" and row["real_book_artifact"] == "FALSE" for row in manifest)
    assert all(row["observed_true_count"] == "0" and row["safety_boundary_passed"] == "TRUE" for row in safety)
    assert gate[0]["promotion_ready"] == "FALSE"
    assert gate[0]["v20_120_operator_decision_record_allowed"] == "TRUE"
    strict = [
        d["v20_119_operator_review_package_allowed_by_v118"] == "TRUE",
        d["v20_118_status_allowed"] == "TRUE",
        d["selected_scenario_matches_v20_118"] == "TRUE",
        d["blocker_summary_created"] == "TRUE",
        d["evidence_manifest_created"] == "TRUE",
        d["required_decisions_created"] == "TRUE",
        d["promotion_ready"] == "FALSE",
        d["no_ticker_rows_fabricated"] == "TRUE",
        d["no_upstream_outputs_mutated"] == "TRUE",
        d["safety_boundary_audit_passed"] == "TRUE",
        d["prohibited_action_true_count"] == "0",
    ]
    assert (d["operator_review_package_status"] == "PASS_V20_119_OPERATOR_REVIEW_PACKAGE_READY_FOR_V20_120") == all(strict)
    for rows in [decision, summary, manifest, required, safety, gate]:
        for field in PROHIBITED_FALSE_FIELDS:
            if field in rows[0]:
                assert_false(rows, field)


if __name__ == "__main__":
    test_blocked_missing_input_case()
    test_operator_review_package()
    print("PASS_V20_119_OPERATOR_REVIEW_PACKAGE_TESTS")
