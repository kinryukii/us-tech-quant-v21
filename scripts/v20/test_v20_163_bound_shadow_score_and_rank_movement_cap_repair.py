#!/usr/bin/env python
"""Tests for V20.163 bound shadow score and rank movement cap repair."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_163_bound_shadow_score_and_rank_movement_cap_repair.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUT_REPAIR = FACTORS / "V20_163_BOUND_SHADOW_SCORE_RANK_CAP_REPAIR.csv"
OUT_SIM = FACTORS / "V20_163_CAPPED_BOUND_SHADOW_RANKING_SIMULATION.csv"
OUT_DELTA = FACTORS / "V20_163_CAPPED_BOUND_SHADOW_VS_BASELINE_RANK_DELTA.csv"
OUT_SCORE_AUDIT = FACTORS / "V20_163_SCORE_ADJUSTMENT_CAP_AUDIT.csv"
OUT_RANK_AUDIT = FACTORS / "V20_163_RANK_MOVEMENT_CAP_AUDIT.csv"
OUT_OUTLIER_AUDIT = FACTORS / "V20_163_OUTLIER_CAP_REPAIR_AUDIT.csv"
OUT_GATE = FACTORS / "V20_163_CAPPED_SHADOW_NEXT_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_163_BOUND_SHADOW_SCORE_AND_RANK_MOVEMENT_CAP_REPAIR_REPORT.md"
OUTPUTS = [OUT_REPAIR, OUT_SIM, OUT_DELTA, OUT_SCORE_AUDIT, OUT_RANK_AUDIT, OUT_OUTLIER_AUDIT, OUT_GATE, OUT_REPORT]

REPAIR_COLUMNS = {
    "ticker",
    "baseline_rank",
    "uncapped_bound_shadow_rank",
    "capped_bound_shadow_rank",
    "uncapped_absolute_rank_delta",
    "capped_absolute_rank_delta",
    "baseline_score",
    "uncapped_bound_shadow_score",
    "capped_bound_shadow_score",
    "uncapped_score_delta",
    "capped_score_delta",
    "score_adjustment_cap_applied",
    "rank_movement_cap_applied",
    "outlier_cap_applied",
    "likely_factor_driver",
    "factor_impact_concentration_before",
    "factor_impact_concentration_after",
    "baseline_top20_flag",
    "capped_shadow_top20_flag",
    "official_ranking_mutated",
    "official_weight_change_created",
}
SUMMARY_COLUMNS = {
    "baseline_candidate_count",
    "capped_shadow_candidate_count",
    "top20_overlap_count",
    "entered_top20_count",
    "exited_top20_count",
    "capped_top20_turnover_rate",
    "uncapped_max_absolute_rank_delta",
    "capped_max_absolute_rank_delta",
    "uncapped_average_absolute_rank_delta",
    "capped_average_absolute_rank_delta",
    "outlier_ticker_count_before",
    "outlier_ticker_count_after",
    "factor_impact_concentration_before",
    "factor_impact_concentration_after",
    "cap_repair_success",
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
        FACTORS / "V20_162_BOUND_SHADOW_ELEVATED_RANK_IMPACT_REVIEW.csv",
        FACTORS / "V20_162_BOUND_SHADOW_RANK_DELTA_DISTRIBUTION.csv",
        FACTORS / "V20_162_BOUND_SHADOW_OUTLIER_TICKER_AUDIT.csv",
        FACTORS / "V20_162_BOUND_SHADOW_FACTOR_IMPACT_ATTRIBUTION.csv",
        FACTORS / "V20_162_BOUND_SHADOW_CAP_RECOMMENDATION.csv",
        FACTORS / "V20_162_BOUND_SHADOW_NEXT_GATE.csv",
        FACTORS / "V20_158_R2_BOUND_REDUCED_SHADOW_RANKING_SIMULATION.csv",
        FACTORS / "V20_158_R2_BOUND_SHADOW_VS_BASELINE_RANK_DELTA.csv",
        FACTORS / "V20_158_R2_RANK_IMPACT_RETEST_GATE.csv",
    ]
    return {path: digest(path) for path in paths if path.exists()}


def load_module():
    spec = importlib.util.spec_from_file_location("v20_163_cap_repair_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    module.OUTPUTS = temp
    module.FACTORS = temp / "factors"
    module.READ_CENTER = temp / "read_center"
    for name in [
        "V162_REVIEW", "V162_DISTRIBUTION", "V162_OUTLIERS", "V162_ATTRIBUTION", "V162_CAP", "V162_GATE",
        "V158_R2_SIM", "V158_R2_DELTA", "V158_R2_GATE",
    ]:
        setattr(module, name, module.FACTORS / getattr(module, name).name)
    module.OUT_REPAIR = module.FACTORS / module.OUT_REPAIR.name
    module.OUT_SIM = module.FACTORS / module.OUT_SIM.name
    module.OUT_DELTA = module.FACTORS / module.OUT_DELTA.name
    module.OUT_SCORE_AUDIT = module.FACTORS / module.OUT_SCORE_AUDIT.name
    module.OUT_RANK_AUDIT = module.FACTORS / module.OUT_RANK_AUDIT.name
    module.OUT_OUTLIER_AUDIT = module.FACTORS / module.OUT_OUTLIER_AUDIT.name
    module.OUT_GATE = module.FACTORS / module.OUT_GATE.name
    module.REPORT = module.READ_CENTER / module.REPORT.name


def write_minimal_inputs(module, status_ok: bool = True) -> None:
    status = "WARN_V20_162_BOUND_SHADOW_RANK_IMPACT_TOO_CONCENTRATED" if status_ok else "PARTIAL_PASS"
    write_csv(module.V162_REVIEW, [{
        "top20_membership_stable": "TRUE",
        "elevated_rank_impact_confirmed": "TRUE",
        "score_adjustment_cap_required": "TRUE",
        "rank_movement_cap_required": "TRUE",
        "shadow_weight_expansion_allowed": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "factor_impact_concentration": "1.0000000000",
    }])
    write_csv(module.V162_DISTRIBUTION, [{"rank_delta_bucket": "5_TO_9"}])
    write_csv(module.V162_OUTLIERS, [{
        "ticker": "BBB",
        "likely_factor_driver": "RISK",
    }])
    write_csv(module.V162_ATTRIBUTION, [{"factor_driver": "RISK", "factor_impact_concentration": "1.0000000000"}])
    write_csv(module.V162_CAP, [{
        "score_adjustment_cap_required": "TRUE",
        "rank_movement_cap_required": "TRUE",
        "recommended_rank_movement_cap": "4",
    }])
    write_csv(module.V162_GATE, [{
        "final_status": status,
        "shadow_weight_expansion_allowed": "FALSE",
        "official_weight_change_allowed": "FALSE",
    }])
    write_csv(module.V158_R2_SIM, [
        {
            "ticker": "AAA",
            "authoritative_baseline_rank": "1",
            "authoritative_baseline_score": "1.0000000000",
            "bound_reduced_shadow_score": "0.9990000000",
            "bound_reduced_score_delta": "-0.0010000000",
            "bound_reduced_shadow_rank": "1",
            "bound_reduced_rank_delta": "0",
            "affected_factor_family": "RISK",
        },
        {
            "ticker": "BBB",
            "authoritative_baseline_rank": "30",
            "authoritative_baseline_score": "30.0000000000",
            "bound_reduced_shadow_score": "24.9980000000",
            "bound_reduced_score_delta": "-0.0020000000",
            "bound_reduced_shadow_rank": "25",
            "bound_reduced_rank_delta": "-5",
            "affected_factor_family": "RISK",
        },
    ])
    write_csv(module.V158_R2_DELTA, [{"summary_id": "D"}])
    write_csv(module.V158_R2_GATE, [{"final_status": "PASS_V20_158_R2_AUTHORITATIVE_BASELINE_BINDING_REPAIR_READY_FOR_V20_159"}])


def assert_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE in {row}"
        if "capped_bound_shadow_simulation_created" in row:
            assert row["capped_bound_shadow_simulation_created"] == "TRUE"
        if "shadow_repair_scope" in row:
            assert row["shadow_repair_scope"] == "RESEARCH_ONLY_LIMITED_CONSERVATIVE_BOUND_TO_AUTHORITATIVE_BASELINE_WITH_CAPS"


def test_blocked_missing_inputs_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_163_BOUND_SHADOW_SCORE_RANK_CAP_REPAIR"


def test_blocked_wrong_v162_status_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_minimal_inputs(module, status_ok=False)
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_163_BOUND_SHADOW_SCORE_RANK_CAP_REPAIR"


def test_temp_cap_repair_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_minimal_inputs(module)
        assert module.main() == 0
        repair = read_csv(module.OUT_REPAIR)
        summary = read_csv(module.OUT_DELTA)[0]
        gate = read_csv(module.OUT_GATE)[0]
        bbb = next(row for row in repair if row["ticker"] == "BBB")
        assert bbb["uncapped_absolute_rank_delta"] == "5"
        assert bbb["capped_absolute_rank_delta"] == "4"
        assert bbb["score_adjustment_cap_applied"] == "TRUE"
        assert bbb["rank_movement_cap_applied"] == "TRUE"
        assert float(abs(float(bbb["capped_score_delta"]))) <= float(abs(float(bbb["uncapped_score_delta"])))
        assert summary["outlier_ticker_count_before"] == "1"
        assert summary["outlier_ticker_count_after"] == "0"
        assert summary["cap_repair_success"] == "TRUE"
        assert gate["final_status"] == "PASS_V20_163_BOUND_SHADOW_CAP_REPAIR_READY_FOR_V20_164"


def test_bound_shadow_score_and_rank_movement_cap_repair() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.158-R2/V20.162 outputs were mutated"
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_163_BOUND_SHADOW_CAP_REPAIR_READY_FOR_V20_164",
        "PARTIAL_PASS_V20_163_BOUND_SHADOW_CAP_REPAIR_WITH_REMAINING_ELEVATED_IMPACT_READY_FOR_V20_164",
        "WARN_V20_163_BOUND_SHADOW_CAP_REPAIR_INSUFFICIENT",
    ])
    for expected in [
        "V20_162_GATE_CONSUMED=TRUE",
        "V20_162_STATUS=WARN_V20_162_BOUND_SHADOW_RANK_IMPACT_TOO_CONCENTRATED",
        "V20_158_R2_GATE_CONSUMED=TRUE",
        "TOP20_MEMBERSHIP_STABLE=TRUE",
        "ELEVATED_RANK_IMPACT_CONFIRMED=TRUE",
        "SCORE_ADJUSTMENT_CAP_REQUIRED=TRUE",
        "RANK_MOVEMENT_CAP_REQUIRED=TRUE",
        "SHADOW_WEIGHT_EXPANSION_ALLOWED=FALSE",
        "OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE",
        "NO_SCORE_ADJUSTMENT_INCREASED=TRUE",
        "NO_RANK_MOVEMENT_INCREASED=TRUE",
        "TOP20_MEMBERSHIP_PRESERVED=TRUE",
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
    repair = read_csv(OUT_REPAIR)
    sim = read_csv(OUT_SIM)
    summary = read_csv(OUT_DELTA)
    score_audit = read_csv(OUT_SCORE_AUDIT)
    rank_audit = read_csv(OUT_RANK_AUDIT)
    outlier_audit = read_csv(OUT_OUTLIER_AUDIT)
    gate = read_csv(OUT_GATE)
    assert repair and sim and summary and score_audit and rank_audit and outlier_audit and gate
    assert REPAIR_COLUMNS.issubset(repair[0].keys()), REPAIR_COLUMNS - set(repair[0].keys())
    assert SUMMARY_COLUMNS.issubset(summary[0].keys()), SUMMARY_COLUMNS - set(summary[0].keys())
    assert all(row["official_ranking_mutated"] == "FALSE" for row in repair)
    assert all(row["official_weight_change_created"] == "FALSE" for row in repair)
    assert all(row["score_adjustment_increased"] == "FALSE" for row in score_audit)
    assert all(row["rank_movement_increased"] == "FALSE" for row in rank_audit)
    assert all(row["top20_membership_preserved"] == "TRUE" for row in rank_audit)
    assert gate[0]["shadow_weight_expansion_allowed"] == "FALSE"
    assert gate[0]["official_weight_change_allowed"] == "FALSE"
    for rows in [repair, sim, summary, score_audit, rank_audit, outlier_audit, gate]:
        assert_safety(rows)


if __name__ == "__main__":
    test_blocked_missing_inputs_case()
    test_blocked_wrong_v162_status_case()
    test_temp_cap_repair_case()
    test_bound_shadow_score_and_rank_movement_cap_repair()
    print("PASS_V20_163_BOUND_SHADOW_SCORE_AND_RANK_MOVEMENT_CAP_REPAIR_TESTS")
