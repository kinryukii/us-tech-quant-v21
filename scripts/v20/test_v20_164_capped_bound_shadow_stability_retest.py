#!/usr/bin/env python
"""Tests for V20.164 capped bound shadow stability retest."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_164_capped_bound_shadow_stability_retest.py"
FACTORS = ROOT / "outputs" / "v20" / "factors"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUT_RETEST = FACTORS / "V20_164_CAPPED_BOUND_SHADOW_STABILITY_RETEST.csv"
OUT_SUMMARY = FACTORS / "V20_164_CAPPED_BOUND_SHADOW_STABILITY_SUMMARY.csv"
OUT_GUARDRAIL = FACTORS / "V20_164_CAPPED_BOUND_SHADOW_GUARDRAIL_AUDIT.csv"
OUT_OUTLIER = FACTORS / "V20_164_CAPPED_BOUND_SHADOW_OUTLIER_RETEST_AUDIT.csv"
OUT_GATE = FACTORS / "V20_164_CAPPED_BOUND_SHADOW_NEXT_GATE.csv"
OUT_SAFETY = FACTORS / "V20_164_CAPPED_BOUND_SHADOW_SAFETY_AUDIT.csv"
OUT_REPORT = READ_CENTER / "V20_164_CAPPED_BOUND_SHADOW_STABILITY_RETEST_REPORT.md"
OUTPUTS = [OUT_RETEST, OUT_SUMMARY, OUT_GUARDRAIL, OUT_OUTLIER, OUT_GATE, OUT_SAFETY, OUT_REPORT]

RETEST_COLUMNS = {
    "retest_run_id",
    "baseline_candidate_count",
    "capped_shadow_candidate_count",
    "top20_overlap_count",
    "entered_top20_count",
    "exited_top20_count",
    "capped_top20_turnover_rate",
    "capped_max_absolute_rank_delta",
    "capped_average_absolute_rank_delta",
    "capped_median_absolute_rank_delta",
    "outlier_ticker_count",
    "factor_impact_concentration",
    "cap_guardrail_passed",
    "stability_result",
    "limitation_reason",
}
SUMMARY_COLUMNS = {
    "retest_run_count",
    "stability_pass_count",
    "stability_warn_count",
    "stability_fail_count",
    "average_capped_top20_turnover_rate",
    "max_capped_top20_turnover_rate",
    "average_capped_rank_delta",
    "max_capped_rank_delta",
    "outlier_ticker_count_max",
    "factor_impact_concentration_max",
    "stable_enough_for_continued_capped_shadow_research",
    "stable_enough_for_operator_review",
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
        FACTORS / "V20_163_BOUND_SHADOW_SCORE_RANK_CAP_REPAIR.csv",
        FACTORS / "V20_163_CAPPED_BOUND_SHADOW_RANKING_SIMULATION.csv",
        FACTORS / "V20_163_CAPPED_BOUND_SHADOW_VS_BASELINE_RANK_DELTA.csv",
        FACTORS / "V20_163_SCORE_ADJUSTMENT_CAP_AUDIT.csv",
        FACTORS / "V20_163_RANK_MOVEMENT_CAP_AUDIT.csv",
        FACTORS / "V20_163_OUTLIER_CAP_REPAIR_AUDIT.csv",
        FACTORS / "V20_163_CAPPED_SHADOW_NEXT_GATE.csv",
    ]
    return {path: digest(path) for path in paths if path.exists()}


def load_module():
    spec = importlib.util.spec_from_file_location("v20_164_retest_case", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_module_to_temp(module, temp: Path) -> None:
    module.OUTPUTS = temp
    module.FACTORS = temp / "factors"
    module.READ_CENTER = temp / "read_center"
    for name in [
        "V163_REPAIR", "V163_SIM", "V163_DELTA", "V163_SCORE_AUDIT",
        "V163_RANK_AUDIT", "V163_OUTLIER_AUDIT", "V163_GATE",
    ]:
        setattr(module, name, module.FACTORS / getattr(module, name).name)
    module.OUT_RETEST = module.FACTORS / module.OUT_RETEST.name
    module.OUT_SUMMARY = module.FACTORS / module.OUT_SUMMARY.name
    module.OUT_GUARDRAIL = module.FACTORS / module.OUT_GUARDRAIL.name
    module.OUT_OUTLIER = module.FACTORS / module.OUT_OUTLIER.name
    module.OUT_GATE = module.FACTORS / module.OUT_GATE.name
    module.OUT_SAFETY = module.FACTORS / module.OUT_SAFETY.name
    module.REPORT = module.READ_CENTER / module.REPORT.name


def write_minimal_inputs(module, status_ok: bool = True) -> None:
    status = "PASS_V20_163_BOUND_SHADOW_CAP_REPAIR_READY_FOR_V20_164" if status_ok else "WARN"
    write_csv(module.V163_REPAIR, [{"ticker": "AAA"}])
    sim_rows = [
        {
            "ticker": "AAA",
            "baseline_rank": "1",
            "capped_bound_shadow_rank": "1",
            "capped_absolute_rank_delta": "0",
            "baseline_top20_flag": "TRUE",
            "capped_shadow_top20_flag": "TRUE",
            "likely_factor_driver": "RISK",
        },
        {
            "ticker": "BBB",
            "baseline_rank": "30",
            "capped_bound_shadow_rank": "26",
            "capped_absolute_rank_delta": "4",
            "baseline_top20_flag": "FALSE",
            "capped_shadow_top20_flag": "FALSE",
            "likely_factor_driver": "RISK",
        },
    ]
    write_csv(module.V163_SIM, sim_rows)
    write_csv(module.V163_DELTA, [{
        "cap_repair_success": "TRUE",
        "capped_top20_turnover_rate": "0.0000000000",
        "capped_max_absolute_rank_delta": "4",
        "outlier_ticker_count_after": "0",
        "factor_impact_concentration_after": "0.0000000000",
    }])
    write_csv(module.V163_SCORE_AUDIT, [{"safety_check": "S"}])
    write_csv(module.V163_RANK_AUDIT, [{"safety_check": "R"}])
    write_csv(module.V163_OUTLIER_AUDIT, [{"safety_check": "O"}])
    write_csv(module.V163_GATE, [{
        "final_status": status,
        "shadow_weight_expansion_allowed": "FALSE",
        "official_weight_change_allowed": "FALSE",
    }])


def assert_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE in {row}"
        if "capped_bound_shadow_stability_retest_created" in row:
            assert row["capped_bound_shadow_stability_retest_created"] == "TRUE"
        if "shadow_retest_scope" in row:
            assert row["shadow_retest_scope"] == "RESEARCH_ONLY_LIMITED_CONSERVATIVE_BOUND_TO_AUTHORITATIVE_BASELINE_WITH_CAPS"


def test_blocked_missing_inputs_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_164_CAPPED_BOUND_SHADOW_STABILITY_RETEST"


def test_blocked_wrong_v163_status_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_minimal_inputs(module, status_ok=False)
        assert module.main() == 0
        assert read_csv(module.OUT_GATE)[0]["final_status"] == "BLOCKED_V20_164_CAPPED_BOUND_SHADOW_STABILITY_RETEST"


def test_temp_stability_retest_case() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as temp_dir:
        patch_module_to_temp(module, Path(temp_dir))
        write_minimal_inputs(module)
        assert module.main() == 0
        retests = read_csv(module.OUT_RETEST)
        summary = read_csv(module.OUT_SUMMARY)[0]
        gate = read_csv(module.OUT_GATE)[0]
        assert len(retests) == 3
        assert all(row["cap_guardrail_passed"] == "TRUE" for row in retests)
        assert summary["stability_pass_count"] == "3"
        assert summary["stable_enough_for_operator_review"] == "TRUE"
        assert gate["all_capped_guardrails_passed"] == "TRUE"
        assert gate["final_status"] == "PASS_V20_164_CAPPED_BOUND_SHADOW_STABILITY_RETEST_READY_FOR_V20_165"


def test_capped_bound_shadow_stability_retest() -> None:
    before = upstream_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = upstream_hashes()
    assert before == after, "upstream V20.163 outputs were mutated"
    stdout = result.stdout
    assert any(status in stdout for status in [
        "PASS_V20_164_CAPPED_BOUND_SHADOW_STABILITY_RETEST_READY_FOR_V20_165",
        "PARTIAL_PASS_V20_164_CAPPED_BOUND_SHADOW_STABILITY_RETEST_WITH_WARNINGS_READY_FOR_V20_165",
        "WARN_V20_164_CAPPED_BOUND_SHADOW_STABILITY_RETEST_UNSTABLE",
    ])
    for expected in [
        "V20_163_GATE_CONSUMED=TRUE",
        "V20_163_STATUS=PASS_V20_163_BOUND_SHADOW_CAP_REPAIR_READY_FOR_V20_164",
        "CAP_REPAIR_SUCCESS=TRUE",
        "CAPPED_TOP20_TURNOVER_RATE=0.0000000000",
        "OUTLIER_TICKER_COUNT_AFTER=0",
        "FACTOR_IMPACT_CONCENTRATION_AFTER=0.0000000000",
        "SHADOW_WEIGHT_EXPANSION_ALLOWED=FALSE",
        "OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE",
        "STABLE_ENOUGH_FOR_SHADOW_EXPANSION=FALSE",
        "STABLE_ENOUGH_FOR_OFFICIAL_WEIGHT_CHANGE=FALSE",
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
    retests = read_csv(OUT_RETEST)
    summary = read_csv(OUT_SUMMARY)
    guardrails = read_csv(OUT_GUARDRAIL)
    outliers = read_csv(OUT_OUTLIER)
    gate = read_csv(OUT_GATE)
    safety = read_csv(OUT_SAFETY)
    assert retests and summary and guardrails and outliers and gate and safety
    assert RETEST_COLUMNS.issubset(retests[0].keys()), RETEST_COLUMNS - set(retests[0].keys())
    assert SUMMARY_COLUMNS.issubset(summary[0].keys()), SUMMARY_COLUMNS - set(summary[0].keys())
    assert summary[0]["stable_enough_for_shadow_expansion"] == "FALSE"
    assert summary[0]["stable_enough_for_official_weight_change"] == "FALSE"
    assert gate[0]["shadow_weight_expansion_allowed"] == "FALSE"
    assert gate[0]["official_weight_change_allowed"] == "FALSE"
    assert all(row["safety_passed"] == "TRUE" for row in safety)
    for rows in [retests, summary, guardrails, outliers, gate, safety]:
        assert_safety(rows)


if __name__ == "__main__":
    test_blocked_missing_inputs_case()
    test_blocked_wrong_v163_status_case()
    test_temp_stability_retest_case()
    test_capped_bound_shadow_stability_retest()
    print("PASS_V20_164_CAPPED_BOUND_SHADOW_STABILITY_RETEST_TESTS")
