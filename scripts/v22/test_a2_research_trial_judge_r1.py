from __future__ import annotations

import json
import ast
from pathlib import Path

import pytest

from research_governance.io import TrialLedgerAdapter, require_immutable_manifest
from research_governance.judge import FALSE, NOT_EVALUATED, TRUE, JudgeThresholds, evaluate_trial, render_scorecard
from research_governance.registry import RegistryError, build_leaderboard, load_registries, transition_model
from research_governance.schemas import TrialInput


ROOT = Path(__file__).resolve().parents[2]
REGISTRY_DIR = ROOT / "config/research_governance"


def fold(year: int, candidate_sharpe: float, rank_ic: float, **extra) -> dict:
    return {
        "fold_id": str(year),
        "train_start": f"{year - 2}-01-01",
        "train_end": f"{year - 1}-12-31",
        "validation_start": f"{year}-01-02",
        "validation_end": f"{year}-12-29",
        "sharpe": candidate_sharpe,
        "rank_ic": rank_ic,
        "ndcg_at_20": 0.55,
        **extra,
    }


def base_payload() -> dict:
    return {
        "trial_id": "T_STABLE",
        "model_id": "ALPHA_CANDIDATE",
        "model_family": "ALPHA",
        "feature_set_id": "FS_1",
        "parameter_set_id": "PARAMS_FROZEN_1",
        "benchmark_id": "A_A2_QUARTERLY_13F_CLEAN_BASELINE_R1",
        "training_cutoff": "2025-12-31",
        "universe_id": "SYNTHETIC_PIT_UNIVERSE",
        "data_lineage": "SYNTHETIC_STATIC_FIXTURE_R1",
        "pit_status": "PASS",
        "uses_2026_training": False,
        "uses_2026_parameter_search": False,
        "uses_2026_model_selection": False,
        "folds": [fold(2023, 0.8, 0.03), fold(2024, 0.7, 0.025), fold(2025, 0.9, 0.035)],
        "benchmark_folds": [fold(2023, 0.5, 0.01), fold(2024, 0.5, 0.01), fold(2025, 0.5, 0.01)],
        "economic_summary": {
            "cagr": 0.3, "sharpe": 0.8, "sortino": 1.0, "calmar": 1.2,
            "max_drawdown": -0.15, "turnover": 0.4, "cost": 0.01, "winner_damage": 0.0,
        },
        "benchmark_summary": {
            "cagr": 0.2, "sharpe": 0.5, "sortino": 0.8, "calmar": 0.9,
            "max_drawdown": -0.2, "turnover": 0.3, "cost": 0.01, "rank_ic": 0.01,
        },
    }


def explicit_thresholds() -> JudgeThresholds:
    return JudgeThresholds(
        predictive_min_delta=0.0,
        economic_min_delta=0.0,
        maximum_fold_metric_std=1.0,
        maximum_turnover=1.0,
        maximum_winner_damage=0.01,
    )


def evaluate(payload: dict, thresholds: JudgeThresholds | None = None) -> dict:
    return evaluate_trial(
        TrialInput.from_dict(payload),
        thresholds,
        expected_benchmark_id="A_A2_QUARTERLY_13F_CLEAN_BASELINE_R1",
    )


def test_1_stable_challenger_has_broad_support() -> None:
    result = evaluate(base_payload(), explicit_thresholds())
    assert result["single_period_dominance"]["single_period_dominated"] == FALSE
    assert result["classification"] == "A_STABLE_CHALLENGER"
    assert result["promotion_eligible"] is False
    assert result["user_authorization_required"] is True


def test_2_single_2023_period_domination_is_unstable() -> None:
    payload = base_payload()
    payload["trial_id"] = "T_DOMINATED"
    payload["folds"] = [fold(2023, 3.0, 0.08), fold(2024, -0.1, 0.01), fold(2025, -0.1, 0.01)]
    payload["economic_summary"]["sharpe"] = 1.0
    result = evaluate(payload, explicit_thresholds())
    dominance = result["single_period_dominance"]
    assert dominance["single_period_dominated"] == TRUE
    assert dominance["dominant_period"] == "2023"
    assert dominance["full_sample_delta"] > 0
    assert dominance["leave_period_out_delta"] <= 0
    assert result["classification"] == "D_UNSTABLE"


def test_3_temporal_leakage_is_invalid() -> None:
    payload = base_payload()
    payload["folds"][0]["train_end"] = payload["folds"][0]["validation_start"]
    result = evaluate(payload, explicit_thresholds())
    assert result["flags"]["TEMPORAL_SPLIT_INVALID"] == TRUE
    assert result["classification"] == "E_INVALID"


def test_4_2026_training_is_invalid() -> None:
    payload = base_payload()
    payload["folds"][-1]["train_end"] = "2026-02-01"
    payload["folds"][-1]["validation_start"] = "2026-03-01"
    result = evaluate(payload, explicit_thresholds())
    assert result["flags"]["2026_TRAINING_VIOLATION"] == TRUE
    assert result["classification"] == "E_INVALID"


def test_5_missing_governance_metadata_cannot_pass() -> None:
    payload = base_payload()
    payload["training_cutoff"] = None
    payload["universe_id"] = "UNKNOWN"
    result = evaluate(payload, explicit_thresholds())
    assert result["flags"]["MISSING_REQUIRED_METADATA"] == TRUE
    assert result["flags"]["UNKNOWN_DATA_LINEAGE"] == TRUE
    assert result["classification"] == "E_INVALID"


def test_6_registry_protects_incumbent_and_requires_authorization() -> None:
    alpha = load_registries(REGISTRY_DIR)["ALPHA"]
    with pytest.raises(RegistryError):
        transition_model(alpha, "A2_HGB", "VALID_PRE2026")
    challenger = transition_model(alpha, "XGB_REG", "VALID_PRE2026")
    challenger = transition_model(challenger, "XGB_REG", "STABLE_CHALLENGER")
    challenger = transition_model(challenger, "XGB_REG", "PROSPECTIVE_SHADOW")
    challenger = transition_model(challenger, "XGB_REG", "PROMOTION_ELIGIBLE")
    with pytest.raises(RegistryError, match="explicit user authorization"):
        transition_model(challenger, "XGB_REG", "PROMOTED_CHAMPION")
    assert alpha["models"][0]["model_id"] == "A2_HGB"


def test_7_risk_model_is_excluded_from_alpha_leaderboard() -> None:
    alpha = load_registries(REGISTRY_DIR)["ALPHA"]
    leaderboard = build_leaderboard(alpha, [{
        "model_id": "R6_BAD_ASYMMETRY", "trial_id": "R6", "model_family": "RISK",
        "classification": "A_STABLE_CHALLENGER",
    }], family="ALPHA")
    assert leaderboard["champion"]["model_id"] == "A2_HGB"
    assert leaderboard["STABLE_CHALLENGERS"] == []


def test_8_execution_overlay_is_excluded_from_alpha_leaderboard() -> None:
    alpha = load_registries(REGISTRY_DIR)["ALPHA"]
    leaderboard = build_leaderboard(alpha, [{
        "model_id": "E5_COMBINED_CONSERVATIVE", "trial_id": "E5", "model_family": "EXECUTION",
        "classification": "A_STABLE_CHALLENGER",
    }], family="ALPHA")
    assert leaderboard["champion"]["model_id"] == "A2_HGB"
    assert leaderboard["STABLE_CHALLENGERS"] == []


def test_alpha_threshold_profile_cannot_judge_risk_family() -> None:
    payload = base_payload()
    payload["model_family"] = "RISK"
    result = evaluate(payload, explicit_thresholds())
    assert result["classification"] == "E_INVALID"
    assert "threshold_family_mismatch" in result["classification_reasons"]


def test_known_xgb_unstable_status_is_visible_without_metric_sort() -> None:
    alpha = load_registries(REGISTRY_DIR)["ALPHA"]
    leaderboard = build_leaderboard(alpha, [], family="ALPHA")
    assert [item["model_id"] for item in leaderboard["UNSTABLE"]] == ["XGB_REG"]


def test_default_unregistered_edge_thresholds_are_informational_only() -> None:
    result = evaluate(base_payload())
    assert result["classification"] == "B_PROMISING_BUT_UNPROVEN"
    assert result["flags"]["HIGH_FOLD_VARIANCE"] == NOT_EVALUATED
    assert "rank_ic_threshold_informational_only" in result["classification_reasons"]


def test_scorecard_contains_required_governance_fields() -> None:
    scorecard = render_scorecard(evaluate(base_payload(), explicit_thresholds()))
    for text in (
        "RESEARCH TRIAL JUDGE R1", "DELTA_SHARPE=", "SINGLE_PERIOD_DOMINATED=FALSE",
        "CLASSIFICATION=A_STABLE_CHALLENGER", "PROMOTION_ELIGIBLE=FALSE",
        "USER_AUTHORIZATION_REQUIRED=TRUE",
    ):
        assert text in scorecard


def test_static_ledger_adapter_uses_only_completed_outer_test_rows() -> None:
    rows = []
    for year in (2023, 2024, 2025):
        rows.append({
            "trial_id": f"T_{year}", "parent_trial_id": "SPEC_1", "model_family": "XGBOOST_RANKING",
            "feature_set_id": "FS_1", "hyperparameters": "{\"depth\": 2}", "outer_fold": f"OUTER_{year}",
            "inner_fold": "", "train_start": "2021-01-01", "train_end": f"{year - 1}-12-31",
            "test_start": f"{year}-01-02", "test_end": f"{year}-12-29", "status": "COMPLETED",
            "predictive_metrics": json.dumps({"spearman_ic": 0.02}),
            "economic_metrics": json.dumps({"sharpe": 0.7}),
        })
    rows.append({**rows[0], "trial_id": "INNER", "inner_fold": "INNER_2022"})
    metadata = {
        "model_family": "ALPHA", "benchmark_id": "A_A2_QUARTERLY_13F_CLEAN_BASELINE_R1",
        "training_cutoff": "2025-12-31", "universe_id": "SYNTHETIC", "data_lineage": "STATIC",
        "pit_status": "PASS", "uses_2026_training": False,
        "uses_2026_parameter_search": False, "uses_2026_model_selection": False,
        "models": {"XGBOOST_RANKING": {
            "model_id": "XGB_NESTED_PROCEDURE", "model_family": "ALPHA",
            "feature_set_id": "FS_1", "parameter_set_id": "NESTED_SEARCH_FROZEN_R1",
        }},
    }
    benchmark = {"folds": base_payload()["benchmark_folds"], "economic_summary": {"sharpe": 0.5}}
    trials = TrialLedgerAdapter.normalize_rows(rows, metadata, benchmark)
    assert len(trials) == 1
    assert trials[0].model_family == "ALPHA"
    assert trials[0].model_id == "XGB_NESTED_PROCEDURE"
    assert len(trials[0].folds) == 3


def test_frozen_overnight_manifest_can_authorize_only_hash_matching_copy() -> None:
    fixture_dir = ROOT / "scripts/v22/fixtures/research_governance"
    ledger = fixture_dir / "tiny_immutable_ledger.fixture"
    manifest = fixture_dir / "tiny_immutable_manifest.json"
    assert require_immutable_manifest(ledger, manifest)["pre2026_champion_frozen"] is True


def test_registry_schema_and_known_incumbents() -> None:
    registries = load_registries(REGISTRY_DIR)
    champions = {
        family: next(item for item in registry["models"] if item["role"].endswith("_CHAMPION"))["model_id"]
        for family, registry in registries.items()
    }
    assert champions == {
        "ALPHA": "A2_HGB", "RISK": "R6_BAD_ASYMMETRY", "EXECUTION": "E5_COMBINED_CONSERVATIVE",
    }
    assert all(registry["governance"]["auto_promotion_forbidden"] for registry in registries.values())


def test_judge_source_has_no_training_or_network_dependencies() -> None:
    paths = [
        ROOT / "scripts/v22/a2_research_trial_judge_r1.py",
        *(ROOT / "scripts/v22/research_governance").glob("*.py"),
    ]
    banned = {"sklearn", "xgboost", "lightgbm", "catboost", "torch", "tensorflow", "moomoo", "futu", "requests"}
    imported: set[str] = set()
    fit_calls = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "fit":
                fit_calls.append((path.name, node.lineno))
    assert imported.isdisjoint(banned)
    assert fit_calls == []
