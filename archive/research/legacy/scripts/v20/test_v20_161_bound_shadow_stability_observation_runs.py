#!/usr/bin/env python
"""Tests for V20.161 bound shadow stability observation runs."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_161_bound_shadow_stability_observation_runs.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUT_RUNS = FACTORS / "V20_161_BOUND_SHADOW_STABILITY_OBSERVATION_RUNS.csv"
OUT_SUMMARY = FACTORS / "V20_161_BOUND_SHADOW_STABILITY_SUMMARY.csv"
OUT_GATE = FACTORS / "V20_161_BOUND_SHADOW_STABILITY_GATE.csv"
OUT_SOURCE = FACTORS / "V20_161_BOUND_SHADOW_STABILITY_SOURCE_AUDIT.csv"
OUT_SAFETY = FACTORS / "V20_161_BOUND_SHADOW_STABILITY_SAFETY_AUDIT.csv"
OUT_LIMITATION = FACTORS / "V20_161_BOUND_SHADOW_STABILITY_LIMITATION_AUDIT.csv"
OUT_REPORT = READ_CENTER / "V20_161_BOUND_SHADOW_STABILITY_OBSERVATION_RUNS_REPORT.md"
OUTPUTS = [OUT_RUNS, OUT_SUMMARY, OUT_GATE, OUT_SOURCE, OUT_SAFETY, OUT_LIMITATION, OUT_REPORT]

RUN_COLUMNS = {
    "observation_run_id",
    "source_baseline_artifact",
    "source_shadow_proposal_artifact",
    "baseline_candidate_count",
    "bound_shadow_candidate_count",
    "top20_overlap_count",
    "entered_top20_count",
    "exited_top20_count",
    "top20_turnover_rate",
    "max_absolute_rank_delta",
    "average_absolute_rank_delta",
    "median_absolute_rank_delta",
    "affected_ticker_count",
    "remaining_rank_impact_severity",
    "stability_result",
    "limitation_reason",
}
SUMMARY_COLUMNS = {
    "observation_run_count",
    "stability_pass_count",
    "stability_warn_count",
    "stability_fail_count",
    "average_top20_turnover_rate",
    "max_top20_turnover_rate",
    "average_rank_delta_across_runs",
    "max_rank_delta_across_runs",
    "stable_enough_for_shadow_continuation",
    "stable_enough_for_shadow_expansion",
    "stable_enough_for_official_weight_change",
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
        FACTORS / "V20_160_BOUND_SHADOW_OPERATOR_DECISION_CAPTURE.csv",
        FACTORS / "V20_160_BOUND_SHADOW_OPERATOR_DECISION_GATE.csv",
        FACTORS / "V20_160_BOUND_SHADOW_DECISION_SAFETY_AUDIT.csv",
        FACTORS / "V20_160_BOUND_SHADOW_NEXT_STAGE_PACKET.csv",
        FACTORS / "V20_158_R2_BOUND_REDUCED_SHADOW_RANKING_SIMULATION.csv",
        FACTORS / "V20_158_R2_BOUND_SHADOW_VS_BASELINE_RANK_DELTA.csv",
        FACTORS / "V20_158_R2_RANK_IMPACT_RETEST_GATE.csv",
        FACTORS / "V20_157_REDUCED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL.csv",
        CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
    ]
    return {path: digest(path) for path in paths if path.exists()}


def load_module():
    spec = importlib.util.spec_from_file_location("v20_161_stability_case", SCRIPT)
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
        "V160_DECISION", "V160_GATE", "V160_SAFETY", "V160_NEXT",
        "V158_R2_SIM", "V158_R2_DELTA", "V158_R2_GATE", "V157_PROPOSAL",
    ]:
        setattr(module, name, module.FACTORS / getattr(module, name).name)
    module.V83_RANKING = module.CONSOLIDATION / module.V83_RANKING.name
    module.OUT_RUNS = module.FACTORS / module.OUT_RUNS.name
    module.OUT_SUMMARY = module.FACTORS / module.OUT_SUMMARY.name
    module.OUT_GATE = module.FACTORS / module.OUT_GATE.name
    module.OUT_SOURCE = module.FACTORS / module.OUT_SOURCE.name
    module.OUT_SAFETY = module.FACTORS / module.OUT_SAFETY.name
    module.OUT_LIMITATION = module.FACTORS / module.OUT_LIMITATION.name
    module.REPORT = module.READ_CENTER / module.REPORT.name


def write_minimal_inputs(module, status_ok: bool = True, turnover_case: bool = False) -> None:
    write_csv(module.V160_DECISION, [{
        "selected_operator_option": "REQUEST_ADDITIONAL_STABILITY_OBSERVATION_RUNS",
    }])
    write_csv(module.V160_GATE, [{
        "final_status": "PASS_V20_160_BOUND_SHADOW_OPERATOR_DECISION_CAPTURE_READY_FOR_V20_161" if status_ok else "BLOCKED",
        "selected_operator_option": "REQUEST_ADDITIONAL_STABILITY_OBSERVATION_RUNS",
        "continued_bound_shadow_research_allowed": "TRUE",
        "additional_stability_observation_runs_required": "TRUE",
        "shadow_weight_expansion_allowed": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "formal_activation_allowed": "FALSE",
        "promotion_ready": "FALSE",
    }])
    write_csv(module.V160_SAFETY, [{"safety_check_id": "S"}])
    write_csv(module.V160_NEXT, [{"v20_161_allowed": "TRUE"}])
    delta = "-2.0" if turnover_case else "-0.001"
    write_csv(module.V158_R2_SIM, [
        {"ticker": "AAA", "authoritative_baseline_rank": "1", "bound_reduced_score_delta": delta},
        {"ticker": "BBB", "authoritative_baseline_rank": "2", "bound_reduced_score_delta": "0"},
    ])
    write_csv(module.V158_R2_DELTA, [{"summary_id": "D"}])
    write_csv(module.V158_R2_GATE, [{"final_status": "PASS"}])
    write_csv(module.V157_PROPOSAL, [{"factor_family": "RISK", "reduced_proposed_delta": "-0.0015"}])
    write_csv(module.V83_RANKING, [
        {"ticker": "AAA", "official_current_rank": "1", "official_current_score": "1", "score_name": "source_rank_or_score"},
        {"ticker": "BBB", "official_current_rank": "2", "official_current_score": "2", "score_name": "source_rank_or_score"},
    ])


def assert_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE in {row}"
        if "bound_shadow_stability_observation_created" in row:
            assert row["bound_shadow_stability_observation_created"] == "TRUE"
        if "shadow_observation_scope" in row:
            assert row["shadow_observation_scope"] == "RESEARCH_ONLY_LIMITED_CONSERVATIVE_BOUND_TO_AUTHORITATIVE_BASELINE"


def test_blocked_missing_inputs_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_161_BOUND_SHADOW_STABILITY_OBSERVATION_RUNS"


def test_blocked_wrong_v160_status_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        write_minimal_inputs(module, status_ok=False)
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_161_BOUND_SHADOW_STABILITY_OBSERVATION_RUNS"


def test_temp_stability_observation_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patch_module_to_temp(module, temp)
        write_minimal_inputs(module)
        assert module.main() == 0
        runs = read_csv(module.OUT_RUNS)
        summary = read_csv(module.OUT_SUMMARY)[0]
        gate = read_csv(module.OUT_GATE)[0]
        assert len(runs) == 3
        assert summary["stable_enough_for_shadow_expansion"] == "FALSE"
        assert summary["stable_enough_for_official_weight_change"] == "FALSE"
        assert gate["final_status"] in {
            "PASS_V20_161_BOUND_SHADOW_STABILITY_OBSERVATION_READY_FOR_V20_162",
            "PARTIAL_PASS_V20_161_BOUND_SHADOW_STABILITY_OBSERVATION_WITH_ELEVATED_RANK_IMPACT_READY_FOR_V20_162",
            "WARN_V20_161_BOUND_SHADOW_STABILITY_OBSERVATION_UNSTABLE",
        }


def test_bound_shadow_stability_observation_runs() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.157/V20.158-R2/V20.160 outputs were mutated"
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_161_BOUND_SHADOW_STABILITY_OBSERVATION_READY_FOR_V20_162",
        "PARTIAL_PASS_V20_161_BOUND_SHADOW_STABILITY_OBSERVATION_WITH_ELEVATED_RANK_IMPACT_READY_FOR_V20_162",
        "WARN_V20_161_BOUND_SHADOW_STABILITY_OBSERVATION_UNSTABLE",
    ])
    for expected in [
        "V20_160_GATE_CONSUMED=TRUE",
        "SELECTED_OPERATOR_OPTION=REQUEST_ADDITIONAL_STABILITY_OBSERVATION_RUNS",
        "CONTINUED_BOUND_SHADOW_RESEARCH_ALLOWED=TRUE",
        "ADDITIONAL_STABILITY_OBSERVATION_RUNS_REQUIRED=TRUE",
        "SHADOW_WEIGHT_EXPANSION_ALLOWED=FALSE",
        "OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE",
        "FORMAL_ACTIVATION_ALLOWED=FALSE",
        "PROMOTION_READY=FALSE",
        "STABLE_ENOUGH_FOR_SHADOW_EXPANSION=FALSE",
        "STABLE_ENOUGH_FOR_OFFICIAL_WEIGHT_CHANGE=FALSE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "OFFICIAL_WEIGHTS_MUTATED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "REAL_BOOK_ACTION_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_ACTION_CREATED=FALSE",
        "OUTCOMES_FABRICATED=0",
        "BENCHMARKS_FABRICATED=0",
        "PERFORMANCE_CLAIM_CREATED=FALSE",
        "UPSTREAM_MUTATION_DETECTED=FALSE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"
    runs = read_csv(OUT_RUNS)
    summary = read_csv(OUT_SUMMARY)
    gate = read_csv(OUT_GATE)
    source = read_csv(OUT_SOURCE)
    safety = read_csv(OUT_SAFETY)
    limitations = read_csv(OUT_LIMITATION)
    assert runs and summary and gate and source and safety and limitations
    assert RUN_COLUMNS.issubset(runs[0].keys()), RUN_COLUMNS - set(runs[0].keys())
    assert SUMMARY_COLUMNS.issubset(summary[0].keys()), SUMMARY_COLUMNS - set(summary[0].keys())
    assert int(summary[0]["observation_run_count"]) == len(runs)
    assert gate[0]["shadow_weight_expansion_allowed"] == "FALSE"
    assert gate[0]["official_weight_change_allowed"] == "FALSE"
    assert all(row["safety_passed"] == "TRUE" for row in safety)
    for rows in [runs, summary, gate, source, safety, limitations]:
        assert_safety(rows)


if __name__ == "__main__":
    test_blocked_missing_inputs_case()
    test_blocked_wrong_v160_status_case()
    test_temp_stability_observation_case()
    test_bound_shadow_stability_observation_runs()
    print("PASS_V20_161_BOUND_SHADOW_STABILITY_OBSERVATION_RUNS_TESTS")
