#!/usr/bin/env python
"""Tests for V20.162 bound shadow elevated rank impact review."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_162_bound_shadow_elevated_rank_impact_review.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUT_REVIEW = FACTORS / "V20_162_BOUND_SHADOW_ELEVATED_RANK_IMPACT_REVIEW.csv"
OUT_DISTRIBUTION = FACTORS / "V20_162_BOUND_SHADOW_RANK_DELTA_DISTRIBUTION.csv"
OUT_OUTLIERS = FACTORS / "V20_162_BOUND_SHADOW_OUTLIER_TICKER_AUDIT.csv"
OUT_ATTRIBUTION = FACTORS / "V20_162_BOUND_SHADOW_FACTOR_IMPACT_ATTRIBUTION.csv"
OUT_CAP = FACTORS / "V20_162_BOUND_SHADOW_CAP_RECOMMENDATION.csv"
OUT_GATE = FACTORS / "V20_162_BOUND_SHADOW_NEXT_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_162_BOUND_SHADOW_ELEVATED_RANK_IMPACT_REVIEW_REPORT.md"
OUTPUTS = [OUT_REVIEW, OUT_DISTRIBUTION, OUT_OUTLIERS, OUT_ATTRIBUTION, OUT_CAP, OUT_GATE, OUT_REPORT]

REVIEW_COLUMNS = {
    "observation_run_count",
    "average_top20_turnover_rate",
    "max_top20_turnover_rate",
    "average_rank_delta_across_runs",
    "max_rank_delta_across_runs",
    "median_rank_delta_across_runs",
    "elevated_rank_impact_confirmed",
    "top20_membership_stable",
    "internal_rank_churn_detected",
    "outlier_ticker_count",
    "top20_internal_churn_count",
    "non_top20_churn_count",
    "factor_impact_concentration",
    "score_adjustment_cap_required",
    "rank_movement_cap_required",
    "continued_shadow_research_allowed",
    "shadow_weight_expansion_allowed",
    "official_weight_change_allowed",
    "recommended_next_action",
}
OUTLIER_COLUMNS = {
    "ticker",
    "baseline_rank",
    "bound_shadow_rank",
    "absolute_rank_delta",
    "baseline_top20_flag",
    "bound_shadow_top20_flag",
    "outlier_rank_impact_flag",
    "likely_factor_driver",
    "cap_needed",
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
        FACTORS / "V20_161_BOUND_SHADOW_STABILITY_OBSERVATION_RUNS.csv",
        FACTORS / "V20_161_BOUND_SHADOW_STABILITY_SUMMARY.csv",
        FACTORS / "V20_161_BOUND_SHADOW_STABILITY_GATE.csv",
        FACTORS / "V20_161_BOUND_SHADOW_STABILITY_SOURCE_AUDIT.csv",
        FACTORS / "V20_161_BOUND_SHADOW_STABILITY_SAFETY_AUDIT.csv",
        FACTORS / "V20_161_BOUND_SHADOW_STABILITY_LIMITATION_AUDIT.csv",
        FACTORS / "V20_158_R2_BOUND_REDUCED_SHADOW_RANKING_SIMULATION.csv",
        FACTORS / "V20_158_R2_BOUND_SHADOW_VS_BASELINE_RANK_DELTA.csv",
        FACTORS / "V20_158_R2_RANK_IMPACT_RETEST_GATE.csv",
    ]
    return {path: digest(path) for path in paths if path.exists()}


def load_module():
    spec = importlib.util.spec_from_file_location("v20_162_review_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    module.OUTPUTS = temp
    module.FACTORS = temp / "factors"
    module.READ_CENTER = temp / "read_center"
    for name in [
        "V161_RUNS", "V161_SUMMARY", "V161_GATE", "V161_SOURCE", "V161_SAFETY", "V161_LIMITATION",
        "V158_R2_SIM", "V158_R2_DELTA", "V158_R2_GATE",
    ]:
        setattr(module, name, module.FACTORS / getattr(module, name).name)
    module.OUT_REVIEW = module.FACTORS / module.OUT_REVIEW.name
    module.OUT_DISTRIBUTION = module.FACTORS / module.OUT_DISTRIBUTION.name
    module.OUT_OUTLIERS = module.FACTORS / module.OUT_OUTLIERS.name
    module.OUT_ATTRIBUTION = module.FACTORS / module.OUT_ATTRIBUTION.name
    module.OUT_CAP = module.FACTORS / module.OUT_CAP.name
    module.OUT_GATE = module.FACTORS / module.OUT_GATE.name
    module.REPORT = module.READ_CENTER / module.REPORT.name


def write_minimal_inputs(module, status_ok: bool = True, concentrated: bool = False) -> None:
    status = "PARTIAL_PASS_V20_161_BOUND_SHADOW_STABILITY_OBSERVATION_WITH_ELEVATED_RANK_IMPACT_READY_FOR_V20_162"
    if not status_ok:
        status = "WARN_V20_161_BOUND_SHADOW_STABILITY_OBSERVATION_UNSTABLE"
    write_csv(module.V161_RUNS, [
        {
            "observation_run_id": "RUN_1",
            "top20_turnover_rate": "0.0000000000",
            "max_absolute_rank_delta": "5",
            "average_absolute_rank_delta": "2.0000000000",
            "median_absolute_rank_delta": "1.0000000000",
        },
        {
            "observation_run_id": "RUN_2",
            "top20_turnover_rate": "0.0000000000",
            "max_absolute_rank_delta": "5",
            "average_absolute_rank_delta": "2.0000000000",
            "median_absolute_rank_delta": "1.0000000000",
        },
    ])
    write_csv(module.V161_SUMMARY, [{
        "observation_run_count": "2",
        "average_top20_turnover_rate": "0.0000000000",
        "max_top20_turnover_rate": "0.0000000000",
        "average_rank_delta_across_runs": "2.0000000000",
        "max_rank_delta_across_runs": "5",
        "stable_enough_for_shadow_continuation": "TRUE",
        "stable_enough_for_shadow_expansion": "FALSE",
        "stable_enough_for_official_weight_change": "FALSE",
    }])
    write_csv(module.V161_GATE, [{
        "final_status": status,
        "official_weight_change_allowed": "FALSE",
        "shadow_weight_expansion_allowed": "FALSE",
    }])
    write_csv(module.V161_SOURCE, [{"source_audit_id": "S"}])
    write_csv(module.V161_SAFETY, [{"safety_check_id": "S"}])
    write_csv(module.V161_LIMITATION, [{"limitation_id": "L"}])
    driver_b = "RISK" if concentrated else "STRATEGY"
    write_csv(module.V158_R2_SIM, [
        {
            "ticker": "AAA",
            "authoritative_baseline_rank": "1",
            "bound_reduced_shadow_rank": "1",
            "bound_reduced_rank_delta": "0",
            "affected_factor_family": "RISK",
        },
        {
            "ticker": "BBB",
            "authoritative_baseline_rank": "30",
            "bound_reduced_shadow_rank": "25",
            "bound_reduced_rank_delta": "5",
            "affected_factor_family": "RISK",
        },
        {
            "ticker": "CCC",
            "authoritative_baseline_rank": "31",
            "bound_reduced_shadow_rank": "26",
            "bound_reduced_rank_delta": "5",
            "affected_factor_family": driver_b,
        },
    ])
    write_csv(module.V158_R2_DELTA, [{"summary_id": "D"}])
    write_csv(module.V158_R2_GATE, [{"final_status": "PASS_V20_158_R2_AUTHORITATIVE_BASELINE_BINDING_REPAIR_READY_FOR_V20_159"}])


def assert_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE in {row}"
        if "bound_shadow_elevated_rank_impact_review_created" in row:
            assert row["bound_shadow_elevated_rank_impact_review_created"] == "TRUE"
        if "shadow_review_scope" in row:
            assert row["shadow_review_scope"] == "RESEARCH_ONLY_LIMITED_CONSERVATIVE_BOUND_TO_AUTHORITATIVE_BASELINE"


def test_blocked_missing_inputs_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_162_BOUND_SHADOW_ELEVATED_RANK_IMPACT_REVIEW"


def test_blocked_wrong_v161_status_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_minimal_inputs(module, status_ok=False)
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_162_BOUND_SHADOW_ELEVATED_RANK_IMPACT_REVIEW"


def test_temp_cap_required_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_minimal_inputs(module)
        assert module.main() == 0
        review = read_csv(module.OUT_REVIEW)[0]
        outliers = read_csv(module.OUT_OUTLIERS)
        gate = read_csv(module.OUT_GATE)[0]
        assert review["elevated_rank_impact_confirmed"] == "TRUE"
        assert review["score_adjustment_cap_required"] == "TRUE"
        assert review["rank_movement_cap_required"] == "TRUE"
        assert review["outlier_ticker_count"] == "2"
        assert len(outliers) == 2
        assert gate["final_status"] == "PARTIAL_PASS_V20_162_BOUND_SHADOW_REVIEW_REQUIRES_SCORE_ADJUSTMENT_CAP"


def test_temp_concentration_warning_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_minimal_inputs(module, concentrated=True)
        assert module.main() == 0
        gate = read_csv(module.OUT_GATE)[0]
        assert gate["factor_impact_concentration"] == "1.0000000000"
        assert gate["final_status"] == "WARN_V20_162_BOUND_SHADOW_RANK_IMPACT_TOO_CONCENTRATED"


def test_bound_shadow_elevated_rank_impact_review() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.158-R2/V20.161 outputs were mutated"
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_162_BOUND_SHADOW_ELEVATED_RANK_IMPACT_REVIEW_READY_FOR_V20_163",
        "PARTIAL_PASS_V20_162_BOUND_SHADOW_REVIEW_REQUIRES_SCORE_ADJUSTMENT_CAP",
        "WARN_V20_162_BOUND_SHADOW_RANK_IMPACT_TOO_CONCENTRATED",
    ])
    for expected in [
        "V20_161_GATE_CONSUMED=TRUE",
        "V20_158_R2_GATE_CONSUMED=TRUE",
        "STABLE_ENOUGH_FOR_SHADOW_CONTINUATION=TRUE",
        "STABLE_ENOUGH_FOR_SHADOW_EXPANSION=FALSE",
        "STABLE_ENOUGH_FOR_OFFICIAL_WEIGHT_CHANGE=FALSE",
        "SHADOW_WEIGHT_EXPANSION_ALLOWED=FALSE",
        "OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE",
        "FORMAL_ACTIVATION_ALLOWED=FALSE",
        "PROMOTION_READY=FALSE",
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
    review = read_csv(OUT_REVIEW)
    distribution = read_csv(OUT_DISTRIBUTION)
    outliers = read_csv(OUT_OUTLIERS)
    attribution = read_csv(OUT_ATTRIBUTION)
    caps = read_csv(OUT_CAP)
    gate = read_csv(OUT_GATE)
    assert review and distribution and outliers and attribution and caps and gate
    assert REVIEW_COLUMNS.issubset(review[0].keys()), REVIEW_COLUMNS - set(review[0].keys())
    assert OUTLIER_COLUMNS.issubset(outliers[0].keys()), OUTLIER_COLUMNS - set(outliers[0].keys())
    assert review[0]["stable_enough_for_shadow_expansion"] if "stable_enough_for_shadow_expansion" in review[0] else True
    assert review[0]["shadow_weight_expansion_allowed"] == "FALSE"
    assert review[0]["official_weight_change_allowed"] == "FALSE"
    assert gate[0]["shadow_weight_expansion_allowed"] == "FALSE"
    assert gate[0]["official_weight_change_allowed"] == "FALSE"
    assert gate[0]["official_ranking_mutated"] == "FALSE"
    assert gate[0]["official_weight_change_created"] == "FALSE"
    assert gate[0]["official_recommendation_created"] == "FALSE"
    for rows in [review, distribution, outliers, attribution, caps, gate]:
        assert_safety(rows)


if __name__ == "__main__":
    test_blocked_missing_inputs_case()
    test_blocked_wrong_v161_status_case()
    test_temp_cap_required_case()
    test_temp_concentration_warning_case()
    test_bound_shadow_elevated_rank_impact_review()
    print("PASS_V20_162_BOUND_SHADOW_ELEVATED_RANK_IMPACT_REVIEW_TESTS")
