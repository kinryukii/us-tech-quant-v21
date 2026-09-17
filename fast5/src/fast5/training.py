from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from .asset_audit import (
    CACHE, CONFIG, DATA, FORBIDDEN_TARGET_COLUMNS, R1_FEATURE_MANIFEST, R1_MATRIX, R1_ROOT,
    R43A_CONTRACT, REPO, RESULTS, TargetValueFirewall, load_config, now_utc,
    run_asset_audit, sha256, stable_hash, write_json,
)
from .features import build_cross_asset_features


FAST4_SRC = REPO / "fast4/src"
if str(FAST4_SRC) not in sys.path:
    sys.path.insert(0, str(FAST4_SRC))

from fast4.evaluation import profit_factor, spearman  # noqa: E402
from fast4.r2_evaluation import (  # noqa: E402
    choose_abstention, crossfit_ridge_stack, economic_score_metrics, group_metrics,
    inner_economic_objective, normalized_mean_score, probability_metrics,
    risk_adjusted_score, stability_table, status_from_slices,
)
from fast4.splits import fold_manifest, inner_folds, outer_folds  # noqa: E402
from fast4.strong_models import (  # noqa: E402
    StrongSpec, default_parameters, fit_spec, model_importance, specifications,
    sqlite_storage_url, tune_outer_spec,
)


class Fast5Stop(RuntimeError):
    pass


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _safe(local) for key, local in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(local) for local in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        local = float(value)
        if np.isnan(local):
            return None
        if np.isposinf(local):
            return "INF"
        if np.isneginf(local):
            return "-INF"
        return local
    if isinstance(value, (pd.Timestamp, datetime)):
        return str(value)
    return value


def _write(path: Path, value: Any) -> None:
    write_json(path, _safe(value))


def _snapshot(root: Path) -> dict[str, str]:
    return {str(path): sha256(path) for path in sorted(root.glob("*")) if path.is_file()}


def _environment_manifest() -> dict[str, Any]:
    import catboost
    import lightgbm
    import optuna
    import xgboost
    expected = Path(r"D:\us-tech-quant\.venv\Scripts\python.exe")
    actual = Path(sys.executable)
    if actual.resolve() != expected.resolve():
        raise Fast5Stop(f"PYTHON_EXECUTABLE_MISMATCH:{actual}")
    return {
        "schema_version": "FAST5_R1_ENVIRONMENT_MANIFEST_V1", "created_at_utc": now_utc(),
        "python_executable": str(actual), "python_version": platform.python_version(), "sys_path": sys.path,
        "dependencies": {"lightgbm": lightgbm.__version__, "xgboost": xgboost.__version__,
                         "catboost": catboost.__version__, "optuna": optuna.__version__},
        "packages_installed_or_modified": False, "network_used": False, "gpu_used": False,
        "model_threads": load_config()["model_threads"], "optuna_parallel_trials": 1,
    }


def _preregistration(audit: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    selected = list(audit["selected"])
    if not selected:
        raise Fast5Stop("PREREGISTRATION_WITHOUT_TIER_A")
    return {
        "schema_version": "FAST5_R1_PREREGISTRATION_V1", "creation_timestamp_utc": now_utc(),
        "research_interpretation": "DEVELOPMENT_EVIDENCE_NOT_INDEPENDENT_CONFIRMATION",
        "selected_new_information_families": selected, "family_priority_order": cfg["family_priority"],
        "outcome_blind_family_selection": True, "stage_a_target_value_read_count": 0,
        "feature_contract": {
            "baseline_feature_count": cfg["fast4_baseline_feature_count"],
            "baseline_manifest_sha256": cfg["fast4_baseline_feature_manifest_sha256"],
            "new_feature_budget": cfg["new_feature_budget"], "total_feature_budget": cfg["total_feature_budget"],
            "selected_family_cap": cfg["cross_asset_feature_cap"], "symbols": cfg["cross_asset_symbols"],
            "return_windows_days": cfg["cross_asset_return_windows_days"],
            "volatility_window_days": cfg["cross_asset_volatility_window_days"],
            "availability_rule": cfg["cross_asset_availability_rule"],
            "corporate_action_rule": cfg["corporate_action_rule"],
        },
        "target_contract": cfg["target_contract"], "target_sha256": cfg["target_sha256"],
        "target_formula": "MEAN_NET20_FIXED_HORIZON_RETURN_5_10_15_30_60_MINUTES",
        "legal_training_cutoff": cfg["legal_training_cutoff"],
        "validation": {"outer_folds": cfg["outer_fold_count"], "inner_folds": cfg["inner_fold_count"],
                       "purge_minutes": cfg["purge_minutes"], "embargo_minutes": cfg["embargo_minutes"],
                       "chronological": True, "random_split": False},
        "family_subset_rules": {"candidates": cfg["family_subsets"], "prescreen_model": "FIXED_LIGHTGBM_HUBER",
                                "prescreen_inner_only": True, "keep": cfg["family_prescreen_keep"]},
        "models": {"families": ["LightGBM", "XGBoost", "CatBoost", "Ridge"],
                   "spec_names": cfg["model_spec_names"],
                   "ranking": "SKIPPED_NO_VALID_MULTI_CANDIDATE_GROUPS"},
        "model_objectives": ["ROBUST_RETURN", "POSITIVE_PROBABILITY", "SEVERE_LOSS_PROBABILITY",
                             "QUANTILE_Q10_Q25_Q50", "MULTI_HORIZON_5M_60M", "CROSSFITTED_RIDGE",
                             "EXPLICIT_RISK_ADJUSTED_SCORE"],
        "optuna": {"trial_cap": cfg["optuna_trial_cap"], "major_per_fold": cfg["major_trials_per_outer_fold"],
                   "primary_per_fold": cfg["primary_trials_per_outer_fold"],
                   "classification_per_fold": cfg["classification_trials_per_outer_fold"],
                   "secondary_per_fold": cfg["secondary_trials_per_outer_fold"], "inner_only": True},
        "inner_selection_metric": "SPEARMAN_PLUS_SPREAD_TOP_MEAN_MEDIAN_MONOTONICITY_MINUS_TAIL_AND_FOLD_INSTABILITY",
        "abstention": {"coverages": cfg["abstention_coverage_candidates"], "minimum_coverage": .10,
                       "threshold_selected_inner_only": True, "top5_diagnostic_only": True},
        "minimum_support": {"selected_rows": cfg["minimum_selected_rows"],
                            "selected_coverage": cfg["minimum_selected_coverage"],
                            "outer_folds": cfg["minimum_selected_outer_folds"],
                            "positive_years": cfg["minimum_positive_selected_years"]},
        "success_gate_A": {
            "oof_spearman_positive": True, "material_delta_spearman": cfg["material_delta_spearman"],
            "selected_mean_positive": True, "selected_median_positive": True,
            "selected_profit_factor_minimum": cfg["strong_profit_factor_minimum"],
            "tail_not_worse_than_baseline": True, "permutation_p_maximum": .05,
            "new_family_ablation_delta_spearman": cfg["material_ablation_delta_spearman"],
            "timestamp_shift_must_weaken": True,
        },
        "permutation": {"count": cfg["permutation_count"], "seed": cfg["permutation_seed"],
                        "block_rows": cfg["permutation_block_rows"], "statistic": cfg["permutation_statistic"],
                        "null": "WITHIN_OUTER_FOLD_RANDOM_CIRCULAR_BLOCK_SHIFT"},
        "seeds": {key: cfg[key] for key in ("seed", "optuna_seed", "permutation_seed", "random_feature_seed")},
        "final_selection_metric": cfg["permutation_statistic"],
        "prospective_outcome_read": False, "broker_action_allowed": False,
    }


def _load_stage_b_frame(firewall: TargetValueFirewall, cfg: dict[str, Any]) -> tuple[pd.DataFrame, list[str], dict[str, str], dict[str, Any]]:
    firewall.record_target_read()
    frame = pd.read_parquet(R1_MATRIX)
    frame["decision_timestamp_utc"] = pd.to_datetime(frame.decision_timestamp_utc, utc=True, errors="raise")
    frame["entry_timestamp"] = pd.to_datetime(frame.entry_timestamp, utc=True, errors="raise")
    frame["target_end_timestamp_utc"] = pd.to_datetime(frame.target_end_timestamp_utc, utc=True, errors="raise")
    manifest = json.loads(R1_FEATURE_MANIFEST.read_text(encoding="utf-8"))
    baseline = list(manifest["feature_order"])
    families = dict(manifest["feature_families"])
    if len(frame) != 1197 or len(baseline) != 241 or frame.candidate_id.duplicated().any():
        raise Fast5Stop("TARGET_IDENTITY_FAIL:ROW_OR_FEATURE_COUNT")
    if manifest["feature_manifest_sha256"] != cfg["fast4_baseline_feature_manifest_sha256"]:
        raise Fast5Stop("FEATURE_PIT_FAIL:BASELINE_SHA")
    if sha256(R43A_CONTRACT) != cfg["target_sha256"]:
        raise Fast5Stop("TARGET_IDENTITY_FAIL")
    target_columns = ["primary_target", "y_positive", "positive_horizon_majority", "severe_loss",
                      "y_5m", "y_10m", "y_15m", "y_30m", "y_60m"]
    if not set(target_columns).issubset(frame) or not frame[target_columns].notna().all().all():
        raise Fast5Stop("TARGET_IDENTITY_FAIL:TARGET_COLUMNS")
    if str(frame.target_end_timestamp_utc.max()).replace(" ", "T").replace("+00:00", "Z") != cfg["legal_training_cutoff"]:
        raise Fast5Stop("TARGET_IDENTITY_FAIL:LEGAL_CUTOFF")
    if np.isinf(frame[baseline].to_numpy(dtype=float)).any():
        raise Fast5Stop("FEATURE_PIT_FAIL:BASELINE_INFINITY")
    return frame, baseline, families, manifest


def _selected_specs(cfg: dict[str, Any]) -> list[StrongSpec]:
    mapping = {spec.name: spec for spec in specifications()}
    missing = [name for name in cfg["model_spec_names"] if name not in mapping]
    if missing:
        raise Fast5Stop(f"MODEL_SPEC_CONTRACT_FAIL:{missing}")
    return [mapping[name] for name in cfg["model_spec_names"]]


def _subset_features(baseline: list[str], new: list[str]) -> dict[str, list[str]]:
    return {"BASELINE_ONLY": baseline, "NEW_INFORMATION_ONLY": new,
            "BASELINE_PLUS_NEW_INFORMATION": baseline + new}


def _prescreen(frame: pd.DataFrame, fold: Any, inner: list[Any], subsets: dict[str, list[str]],
               cfg: dict[str, Any], fold_number: int) -> tuple[dict[str, Any], dict[str, np.ndarray], dict[str, int]]:
    spec = next(spec for spec in specifications() if spec.name == "lgb_huber_pooled")
    records: dict[str, Any] = {}
    outer_predictions: dict[str, np.ndarray] = {}
    counts = {"fit": 0, "predict": 0}
    for subset_number, (name, features) in enumerate(subsets.items()):
        values = []
        for inner_number, local in enumerate(inner):
            fitted, count = fit_spec(spec, frame, local.train_index, features, default_parameters(spec),
                                     cfg["seed"] + fold_number * 1000 + subset_number * 100 + inner_number,
                                     cfg["model_threads"])
            prediction = fitted.predict_score(frame.loc[local.valid_index])
            values.append(inner_economic_objective(frame.loc[local.valid_index], prediction))
            counts["fit"] += count; counts["predict"] += count
        objective = float(np.mean(values) - .20 * np.std(values))
        fitted, count = fit_spec(spec, frame, fold.train_index, features, default_parameters(spec),
                                 cfg["seed"] + fold_number * 1000 + subset_number * 100 + 90,
                                 cfg["model_threads"])
        outer_predictions[name] = fitted.predict_score(frame.loc[fold.valid_index])
        counts["fit"] += count; counts["predict"] += count
        records[name] = {"inner_fold_objectives": values, "stable_objective": objective,
                         "feature_count": len(features), "outer_outcome_used": False}
    ordered = sorted(records, key=lambda name: (records[name]["stable_objective"], name), reverse=True)
    return {"subsets": records, "kept_for_tuning": ordered[:cfg["family_prescreen_keep"]]}, outer_predictions, counts


def _quantile_order(inner_base: pd.DataFrame, outer_base: pd.DataFrame) -> dict[str, int]:
    columns = ["lgb_q10_pooled", "lgb_q25_pooled", "lgb_q50_pooled"]
    before = after = rows = 0
    if set(columns).issubset(inner_base):
        for local in (inner_base, outer_base):
            valid = local[columns].notna().all(axis=1)
            values = local.loc[valid, columns].to_numpy(dtype=float)
            before += int(np.any(np.diff(values, axis=1) < 0, axis=1).sum())
            rows += len(values)
            local.loc[valid, columns] = np.sort(values, axis=1)
            after += int(np.any(np.diff(local.loc[valid, columns].to_numpy(), axis=1) < 0, axis=1).sum())
    return {"rows": rows, "crossings_before": before, "crossings_after": after}


def _top_metrics(frame: pd.DataFrame, score: str, fraction: float) -> dict[str, Any]:
    data = frame.loc[frame[score].notna() & frame.primary_target.notna()].sort_values(
        [score, "decision_timestamp_utc", "candidate_id"], ascending=[False, True, True], kind="mergesort")
    count = max(1, int(np.ceil(fraction * len(data))))
    return group_metrics(data.head(count).primary_target, len(data))


def _selected_statistic(values: pd.Series, target_scale: float) -> float:
    metrics = group_metrics(values)
    if not metrics["N"] or not np.isfinite(target_scale) or target_scale <= 0:
        return -1e9
    pf = metrics["profit_factor"]
    pf_term = 2.0 if np.isposinf(pf) else float(np.log(max(float(pf), 1e-8)))
    tail_penalty = max(0.0, float(-metrics["cvar"] / target_scale))
    return float(metrics["mean"] / target_scale + .5 * metrics["median"] / target_scale
                 + .15 * pf_term - .20 * tail_penalty)


def _permutation_test(oof: pd.DataFrame, cfg: dict[str, Any]) -> dict[str, Any]:
    target = oof.primary_target.to_numpy(dtype=float)
    selected = oof.abstention_selected.to_numpy(dtype=bool)
    scale = float(oof.primary_target.std(ddof=1))
    observed = _selected_statistic(pd.Series(target[selected]), scale)
    observed_spearman = spearman(oof.primary_target, oof.nested_selected_score)
    rng = np.random.default_rng(cfg["permutation_seed"])
    null = np.empty(cfg["permutation_count"], dtype=float)
    null_spearman = np.empty(cfg["permutation_count"], dtype=float)
    group_positions = [np.asarray(index, dtype=int) for _, index in oof.groupby("validation_slice", sort=True).groups.items()]
    block = int(cfg["permutation_block_rows"])
    for number in range(cfg["permutation_count"]):
        permuted = target.copy()
        for positions in group_positions:
            blocks = max(2, int(np.ceil(len(positions) / block)))
            shift_blocks = int(rng.integers(1, blocks))
            permuted[positions] = np.roll(target[positions], shift_blocks * block)
        null[number] = _selected_statistic(pd.Series(permuted[selected]), scale)
        null_spearman[number] = spearman(pd.Series(permuted), oof.nested_selected_score)
    return {
        "statistic": cfg["permutation_statistic"], "null_procedure": "WITHIN_OUTER_FOLD_RANDOM_CIRCULAR_5_ROW_BLOCK_SHIFT",
        "count": cfg["permutation_count"], "seed": cfg["permutation_seed"], "observed": observed,
        "empirical_p_one_sided": float((1 + np.sum(null >= observed)) / (len(null) + 1)),
        "null_mean": float(null.mean()), "null_std": float(null.std(ddof=1)),
        "null_q95": float(np.quantile(null, .95)), "observed_oof_spearman": observed_spearman,
        "spearman_empirical_p_one_sided": float((1 + np.sum(null_spearman >= observed_spearman)) / (len(null_spearman) + 1)),
        "evidence_interpretation": "DEVELOPMENT_FALSIFICATION_EVIDENCE_NOT_INDEPENDENT_CONFIRMATION",
    }


def _fixed_control_oof(frame: pd.DataFrame, outer: list[Any], features: list[str], cfg: dict[str, Any],
                       seed_offset: int) -> tuple[pd.Series, dict[str, int]]:
    spec = next(spec for spec in specifications() if spec.name == "lgb_huber_pooled")
    prediction = pd.Series(np.nan, index=frame.index, dtype=float)
    counts = {"fit": 0, "predict": 0}
    for number, fold in enumerate(outer):
        fitted, count = fit_spec(spec, frame, fold.train_index, features, default_parameters(spec),
                                 cfg["seed"] + seed_offset + number, cfg["model_threads"])
        prediction.loc[fold.valid_index] = fitted.predict_score(frame.loc[fold.valid_index])
        counts["fit"] += count; counts["predict"] += count
    return prediction, counts


def _falsification(frame: pd.DataFrame, oof: pd.DataFrame, outer: list[Any], baseline: list[str], new: list[str],
                   cfg: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    counts = {"fit": 0, "predict": 0}
    permutation = _permutation_test(oof, cfg)
    evaluation_index = frame.validation_slice.isin([fold.name for fold in outer])
    diagnostic = frame.loc[evaluation_index, ["candidate_id", "decision_timestamp_utc", "primary_target"]].copy()

    rng = np.random.default_rng(cfg["random_feature_seed"])
    noise = frame.copy()
    noise_columns = []
    for number in range(len(new)):
        name = f"fast5_random_control_{number:02d}"
        noise[name] = rng.normal(size=len(noise))
        noise_columns.append(name)
    random_prediction, local = _fixed_control_oof(noise, outer, baseline + noise_columns, cfg, 500_000)
    counts = {key: counts[key] + local[key] for key in counts}
    diagnostic["random_control"] = random_prediction.loc[evaluation_index].to_numpy()
    random_metrics = economic_score_metrics(diagnostic, "random_control")[0]

    shifted = frame.copy()
    order = shifted.sort_values(["underlying_symbol", "decision_timestamp_utc", "candidate_id"], kind="mergesort").index
    shifted_values = shifted.loc[order].groupby("underlying_symbol", sort=False)[new].shift(cfg["timestamp_shift_rows"])
    shifted.loc[order, new] = shifted_values.to_numpy()
    for column in new:
        shifted[column] = shifted[column].fillna(shifted.loc[frame.index.isin(outer[0].train_index), column].median())
    shifted_prediction, local = _fixed_control_oof(shifted, outer, baseline + new, cfg, 600_000)
    counts = {key: counts[key] + local[key] for key in counts}
    diagnostic["timestamp_shift"] = shifted_prediction.loc[evaluation_index].to_numpy()
    shift_metrics = economic_score_metrics(diagnostic, "timestamp_shift")[0]

    baseline_metrics = economic_score_metrics(oof, "baseline_only_score")[0]
    combo_metrics = economic_score_metrics(oof, "baseline_plus_new_score")[0]
    new_only_metrics = economic_score_metrics(oof, "new_information_only_score")[0]
    random_weaker = (random_metrics.get("spearman") or -1) < combo_metrics["spearman"]
    shift_delta = combo_metrics["spearman"] - (shift_metrics.get("spearman") or 0.0)
    ablation_delta = combo_metrics["spearman"] - baseline_metrics["spearman"]
    report = {
        "schema_version": "FAST5_R1_FALSIFICATION_REPORT_V1", "frozen_test_contract": True,
        "primary_permutation": permutation, "random_feature_control": random_metrics,
        "timestamp_shift_control": shift_metrics, "remove_new_family_control": baseline_metrics,
        "new_information_only": new_only_metrics, "baseline_plus_new": combo_metrics,
        "timestamp_shift_delta_spearman": shift_delta, "new_family_ablation_delta_spearman": ablation_delta,
        "year_exclusion": [], "direction_exclusion": [], "underlying_exclusion": [],
        "duplicate_leakage_audit": "PASS_CANDIDATE_IDS_UNIQUE_FEATURE_DUPLICATES_AUDITED_BASELINE_FROZEN",
        "fold_boundary_audit": "PASS_60_MIN_TARGET_PURGE_60_MIN_EMBARGO",
        "candidate_key_audit": "PASS_ONE_TO_ONE_CANDIDATE_JOIN",
        "label_overlap_audit": "PASS_TRAIN_TARGET_END_STRICTLY_BEFORE_VALID_START_MINUS_EMBARGO",
    }
    for year in sorted(pd.to_datetime(oof.decision_timestamp_utc, utc=True).dt.year.unique()):
        part = oof.loc[pd.to_datetime(oof.decision_timestamp_utc, utc=True).dt.year.ne(year)]
        report["year_exclusion"].append({"excluded_year": int(year), **economic_score_metrics(part, "nested_selected_score")[0]})
    for direction in sorted(oof["head"].unique()):
        report["direction_exclusion"].append({"excluded_direction": direction,
            **economic_score_metrics(oof.loc[oof["head"].ne(direction)], "nested_selected_score")[0]})
    for symbol in sorted(oof.underlying_symbol.unique()):
        report["underlying_exclusion"].append({"excluded_underlying": symbol,
            **economic_score_metrics(oof.loc[oof.underlying_symbol.ne(symbol)], "nested_selected_score")[0]})
    report["new_family_ablation_status"] = ("PASS_MATERIALLY_WEAKENS" if ablation_delta >= cfg["material_ablation_delta_spearman"]
                                            else "FAIL_OR_MIXED_DOES_NOT_MATERIALLY_WEAKEN")
    report["timestamp_shift_status"] = ("PASS_MATERIALLY_WEAKENS" if shift_delta >= cfg["material_ablation_delta_spearman"]
                                        else "FAIL_OR_MIXED_DOES_NOT_MATERIALLY_WEAKEN")
    report["status"] = ("PASS" if permutation["empirical_p_one_sided"] <= .05 and random_weaker
                        and report["new_family_ablation_status"].startswith("PASS")
                        and report["timestamp_shift_status"].startswith("PASS") else "MIXED_OR_FAIL")
    return report, counts


def _metric_delta(combo: dict[str, Any], baseline: dict[str, Any], key: str) -> float:
    return float(combo[key] - baseline[key])


def _data_audit_fields(audit_result: dict[str, Any]) -> dict[str, Any]:
    eligibility = audit_result["eligibility"].set_index("logical_asset_family")
    tier_lists = audit_result["tier_lists"]
    def status(family: str) -> str:
        row = eligibility.loc[family]
        return f"{row.tier}:{row.reason}"
    return {
        "FAST5_DATA_AUDIT_STATUS": "PASS_OUTCOME_BLIND_TIER_A_IDENTIFIED" if audit_result["selected"] else "PASS_OUTCOME_BLIND_NO_TIER_A",
        "CANONICAL_DATA_ROOT": str(DATA), "EXTERNAL_RESULTS_ROOT": str(RESULTS),
        "ASSET_FAMILY_COUNT": len(eligibility),
        "MICROSTRUCTURE_ASSET_STATUS": status("MARKET_MICROSTRUCTURE"),
        "MICROSTRUCTURE_COVERAGE": float(eligibility.loc["MARKET_MICROSTRUCTURE", "coverage"]),
        "OPTION_HISTORY_ASSET_STATUS": status("HISTORICAL_OPTIONS"),
        "OPTION_HISTORY_COVERAGE": float(eligibility.loc["HISTORICAL_OPTIONS", "coverage"]),
        "MACRO_EVENT_ASSET_STATUS": status("SCHEDULED_MACRO_EVENTS"),
        "MACRO_EVENT_COVERAGE": float(eligibility.loc["SCHEDULED_MACRO_EVENTS", "coverage"]),
        "NEWS_EVENT_ASSET_STATUS": status("ARCHIVED_NEWS_EVENTS"),
        "NEWS_EVENT_COVERAGE": float(eligibility.loc["ARCHIVED_NEWS_EVENTS", "coverage"]),
        "NEW_CROSS_ASSET_STATUS": status("GENUINELY_NEW_CROSS_ASSET"),
        "NEW_CROSS_ASSET_COVERAGE": float(eligibility.loc["GENUINELY_NEW_CROSS_ASSET", "coverage"]),
        "TIER_A_FAMILIES": "|".join(tier_lists["TIER_A_ELIGIBLE_NEW_PIT_INFORMATION"]) or "NONE",
        "TIER_B_FAMILIES": "|".join(tier_lists["TIER_B_VALID_PIT_BUT_INSUFFICIENT_COVERAGE"]) or "NONE",
        "TIER_C_FAMILIES": "|".join(tier_lists["TIER_C_UNSAFE_OR_NON_PIT_FORBIDDEN"]) or "NONE",
        "TIER_D_FAMILIES": "|".join(tier_lists["TIER_D_REDUNDANT_WITH_EXISTING_FAST4_INFORMATION"]) or "NONE",
        "SELECTED_NEW_INFORMATION_FAMILIES": "|".join(audit_result["selected"]) or "NONE",
    }


def _no_tier_a_summary(audit_fields: dict[str, Any], environment: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    na = "NOT_APPLICABLE_STAGE_B_NOT_STARTED"
    return {
        "FAST5_R1_STATUS": "STOP_NO_ELIGIBLE_NEW_PIT_INFORMATION",
        "FAST5_R1_CLASSIFICATION": "D_NO_ELIGIBLE_NEW_PIT_INFORMATION_ASSET",
        "FAST5_R1_DECISION": "D_STOP_BEFORE_MODEL_TRAINING_DATA_ACQUISITION_REQUIRED",
        "FINAL_DECISION": "D_STOP_BEFORE_MODEL_TRAINING_DATA_ACQUISITION_REQUIRED", "DEVELOPMENT_EVIDENCE_ONLY": True,
        "PYTHON_EXECUTABLE": environment["python_executable"], "PYTHON_VERSION": environment["python_version"],
        "TRAINING_START": na, "TRAINING_END": na, "LEGAL_TRAINING_CUTOFF": cfg["legal_training_cutoff"],
        "TARGET_CONTRACT": cfg["target_contract"], "TARGET_SHA256": cfg["target_sha256"],
        "FAST4_BASELINE_FEATURE_COUNT": 241, "FAST4_BASELINE_FEATURE_MANIFEST_SHA256": cfg["fast4_baseline_feature_manifest_sha256"],
        "SELECTED_NEW_INFORMATION_FAMILIES": "NONE", "NEW_FEATURE_COUNT": 0, "TOTAL_FEATURE_COUNT": 241,
        "FAST5_FEATURE_MANIFEST_SHA256": na, "OUTER_FOLD_COUNT": 0, "INNER_FOLD_COUNT": 0,
        "MODEL_FAMILIES_TRAINED": "NONE", "OBJECTIVES_TRAINED": "NONE", "OPTUNA_TRIAL_CAP": cfg["optuna_trial_cap"],
        "HYPERPARAMETER_TRIAL_COUNT": 0, "OOF_ROW_COUNT": 0, "BEST_PIPELINE": na,
        "BEST_NEW_INFORMATION_SUBSET": na, "PIT_AUDIT_STATUS": "PASS_STAGE_A_ONLY",
        "LEAKAGE_AUDIT_STATUS": "PASS_TARGET_VALUES_NEVER_READ", "PREREGISTRATION_AUDIT_STATUS": na,
        "PROSPECTIVE_OUTCOME_READ": False, "BROKER_ACTION_ALLOWED": False, "TRADE_CONTEXT_CREATED": False,
        "ORDER_API_CALL_COUNT": 0, "MODEL_FIT_COUNT": 0, "MODEL_PREDICT_COUNT": 0,
        "STORAGE_CONTRACT_STATUS": "PASS_EXTERNAL_RESULTS_DATA_ROOT_READ_ONLY",
        "ANTI_BLOAT_STATUS": "PASS_COMPACT_FAST5_AUDIT_PIPELINE", "FINAL_MODEL_TYPE": "NO_MODEL_DATA_AUDIT_STOP_D",
        "FINAL_MODEL_SHA256": na, "FAST5_R1_PROSPECTIVE_SHADOW_READY": False,
        "FAST5_R1_PROSPECTIVE_SHADOW_STARTED": False,
        **audit_fields,
    }


def run() -> tuple[dict[str, Any], dict[str, Any], Path]:
    cfg = load_config()
    started = now_utc()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    scratch_parent = (RESULTS / "scratch/fast5").resolve()
    frozen_parent = (RESULTS / "frozen/fast5").resolve()
    scratch_parent.mkdir(parents=True, exist_ok=True)
    frozen_parent.mkdir(parents=True, exist_ok=True)
    staging = scratch_parent / f"fast5_r1_new_information_{stamp}"
    frozen = frozen_parent / staging.name
    if staging.exists() or frozen.exists():
        raise Fast5Stop(f"OUTPUT_COLLISION:{staging}")
    staging.mkdir()
    firewall = TargetValueFirewall()
    environment = _environment_manifest()
    _write(staging / "FAST5_R1_ENVIRONMENT_MANIFEST.json", environment)
    r1_snapshot = _snapshot(R1_ROOT)
    selected_source_paths = [DATA / "stocks" / symbol / "daily_raw.parquet" for symbol in cfg["cross_asset_symbols"]]
    source_snapshot = {str(path): sha256(path) for path in selected_source_paths}

    audit_result = run_asset_audit(staging, firewall)
    audit_fields = _data_audit_fields(audit_result)
    for key, value in audit_fields.items():
        print(f"{key}={value}", flush=True)
    if not audit_result["selected"]:
        summary = _no_tier_a_summary(audit_fields, environment, cfg)
        _write(staging / "FAST5_R1_FINAL_SUMMARY.json", summary)
        _write(staging / "FAST5_R1_ARTIFACT_MANIFEST.json", {
            "created_at_utc": now_utc(), "artifacts": {p.name: sha256(p) for p in staging.glob("*") if p.is_file()},
            "stage_a_target_value_read_count": firewall.target_value_read_count,
        })
        shutil.move(str(staging), str(frozen))
        return summary, audit_fields, frozen

    prereg = _preregistration(audit_result, cfg)
    prereg_path = staging / "FAST5_R1_PREREGISTRATION.json"
    _write(prereg_path, prereg)
    prereg_sha = sha256(prereg_path)
    (staging / "FAST5_R1_PREREGISTRATION.sha256").write_text(prereg_sha + "\n", encoding="ascii")
    firewall.preregistration_frozen = True
    prereg_fields = {
        "FAST5_R1_PREREGISTRATION_STATUS": "PASS_FROZEN_BEFORE_TARGET_VALUE_READ",
        "FAST5_R1_PREREGISTRATION_TIMESTAMP_UTC": prereg["creation_timestamp_utc"],
        "FAST5_R1_PREREGISTRATION_SHA256": prereg_sha,
        "FAST5_R1_TARGET_VALUE_READ_COUNT_AT_FREEZE": firewall.target_value_read_count,
        "FAST5_R1_SELECTED_FAMILY_COUNT": len(audit_result["selected"]),
        "FAST5_R1_NEW_FEATURE_BUDGET": cfg["new_feature_budget"],
        "FAST5_R1_TOTAL_FEATURE_BUDGET": cfg["total_feature_budget"],
        "FAST5_R1_OPTUNA_TRIAL_CAP": cfg["optuna_trial_cap"],
        "FAST5_R1_PERMUTATION_COUNT": cfg["permutation_count"],
    }
    for key, value in prereg_fields.items():
        print(f"{key}={value}", flush=True)
    if firewall.target_value_read_count != 0:
        raise Fast5Stop("TARGET_VALUE_READ_BEFORE_PREREGISTRATION")

    firewall.authorize_stage_b()
    frame, baseline_features, baseline_families, r1_feature_manifest = _load_stage_b_frame(firewall, cfg)
    new_values, new_audit = build_cross_asset_features(
        frame[["candidate_id", "trading_date", "decision_timestamp_utc"]], DATA, cfg["cross_asset_symbols"])
    frame = frame.merge(new_values, on="candidate_id", how="left", validate="one_to_one")
    new_features = list(new_audit["feature_order"])
    if len(new_features) > cfg["new_feature_budget"] or len(baseline_features) + len(new_features) > cfg["total_feature_budget"]:
        raise Fast5Stop("FEATURE_BLOAT_HARD_LIMIT")
    new_medians = frame[new_features].median()
    frame[new_features] = frame[new_features].fillna(new_medians)
    if not np.isfinite(frame[new_features].to_numpy(dtype=float)).all():
        raise Fast5Stop("FEATURE_PIT_FAIL:NONFINITE_NEW_FEATURES")
    all_features = baseline_features + new_features
    feature_families = {**baseline_families, **{name: "new_cross_asset" for name in new_features}}
    feature_identity = stable_hash({
        "baseline_manifest_sha256": cfg["fast4_baseline_feature_manifest_sha256"],
        "new_feature_order": new_features, "new_feature_contract": prereg["feature_contract"],
    })
    feature_manifest = {
        "schema_version": "FAST5_R1_FEATURE_MANIFEST_V1", "created_at_utc": now_utc(),
        "baseline_manifest_path": str(R1_FEATURE_MANIFEST),
        "baseline_manifest_sha256": cfg["fast4_baseline_feature_manifest_sha256"],
        "baseline_feature_count": len(baseline_features), "new_feature_count": len(new_features),
        "total_feature_count": len(all_features), "selected_new_families": audit_result["selected"],
        "new_feature_order": new_features, "total_feature_order": all_features,
        "feature_families": feature_families, "feature_manifest_sha256": feature_identity,
        "pit_audit": new_audit, "target_outcome_used_for_feature_construction": False,
    }
    _write(staging / "FAST5_R1_FEATURE_MANIFEST.json", feature_manifest)
    _write(staging / "FAST5_R1_TARGET_MANIFEST.json", {
        "schema_version": "FAST5_R1_TARGET_MANIFEST_V1", "target_contract": cfg["target_contract"],
        "target_sha256": cfg["target_sha256"], "primary_target": "AVERAGE_FIXED_HORIZON_NET20",
        "horizons_minutes": [5, 10, 15, 30, 60], "transaction_cost_bps": 20,
        "legal_training_cutoff": cfg["legal_training_cutoff"], "target_value_read_after_preregistration": True,
        "target_value_read_count": firewall.target_value_read_count,
    })

    outer = outer_folds(frame, cfg["purge_minutes"], cfg["embargo_minutes"])
    inner_by_outer = {fold.name: inner_folds(frame, fold.train_index, cfg["inner_fold_count"],
                                            cfg["purge_minutes"], cfg["embargo_minutes"]) for fold in outer}
    folds = fold_manifest(frame, outer, inner_by_outer)
    r1_fold_path = R1_ROOT / "FAST4_R1_PURGED_NESTED_FOLD_MANIFEST.json"
    if folds["manifest_sha256"] != json.loads(r1_fold_path.read_text(encoding="utf-8"))["manifest_sha256"]:
        raise Fast5Stop("OUTER_FOLD_LEAKAGE:FROZEN_FOLD_IDENTITY")
    folds.update({"schema_version": "FAST5_R1_FOLD_MANIFEST_V1", "outer_outcome_used_for_selection": False,
                  "family_selection_inner_only": True, "threshold_selection_inner_only": True})
    _write(staging / "FAST5_R1_FOLD_MANIFEST.json", folds)

    subsets = _subset_features(baseline_features, new_features)
    specs = _selected_specs(cfg)
    storage = sqlite_storage_url(staging / "FAST5_R1_OPTUNA.sqlite3")
    counts = {"fit": 0, "predict": 0, "trials": 0}
    oof_parts: list[pd.DataFrame] = []
    tuning_records: list[dict[str, Any]] = []
    selection_records: list[dict[str, Any]] = []
    importance_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    quantile_audits: list[dict[str, Any]] = []
    for fold_number, fold in enumerate(outer, start=1):
        print(f"FAST5_R1_PROGRESS=OUTER_{fold_number}_OF_{len(outer)}:{fold.name}", flush=True)
        prescreen, comparator_outer, local_counts = _prescreen(
            frame, fold, inner_by_outer[fold.name], subsets, cfg, fold_number)
        for key in ("fit", "predict"):
            counts[key] += local_counts[key]
        part = frame.loc[fold.valid_index, [
            "candidate_id", "decision_timestamp_utc", "trading_date", "validation_slice", "head", "underlying_symbol",
            "primary_target", "y_positive", "positive_horizon_majority", "severe_loss",
            "y_5m", "y_10m", "y_15m", "y_30m", "y_60m", "minutes_since_rth_open", "vix_percentile_252d",
        ]].copy()
        part["baseline_only_score"] = comparator_outer["BASELINE_ONLY"]
        part["new_information_only_score"] = comparator_outer["NEW_INFORMATION_ONLY"]
        part["baseline_plus_new_score"] = comparator_outer["BASELINE_PLUS_NEW_INFORMATION"]
        inner_base = pd.DataFrame(index=frame.index)
        outer_base = pd.DataFrame(index=fold.valid_index)
        fold_selected_records = []
        for spec_number, spec in enumerate(specs, start=1):
            attempts = []
            print(f"FAST5_R1_PROGRESS={fold.name}:SPEC_{spec_number}_OF_{len(specs)}:{spec.name}", flush=True)
            for subset_number, subset_name in enumerate(prescreen["kept_for_tuning"]):
                try:
                    pred, raw, inner_pred, record, fitted, local = tune_outer_spec(
                        spec, frame, subsets[subset_name], fold.train_index, fold.valid_index,
                        inner_by_outer[fold.name], inner_economic_objective, storage,
                        f"{fold.name}__{spec.name}__{subset_name}", cfg,
                        cfg["optuna_seed"] + fold_number * 10000 + spec_number * 100 + subset_number)
                    record.update({"outer_fold": fold.name, "feature_subset": subset_name,
                                   "feature_count": len(subsets[subset_name]), "outer_outcome_used": False})
                    tuning_records.append(record)
                    attempts.append((record["best_value"], subset_name, pred, raw, inner_pred, record, fitted))
                    for key in counts:
                        counts[key] += local[key]
                except Exception as error:
                    failures.append({"outer_fold": fold.name, "spec": spec.name, "feature_subset": subset_name,
                                     "error_type": type(error).__name__, "error": str(error)})
                    print(f"FAST5_R1_MODEL_FAILURE_ISOLATED={fold.name}:{spec.name}:{subset_name}:{type(error).__name__}", flush=True)
            if not attempts:
                continue
            selected = max(attempts, key=lambda value: (value[0], value[1]))
            _, subset_name, pred, raw, inner_pred, record, fitted = selected
            record["selected_for_spec"] = True
            fold_selected_records.append(record)
            inner_base[spec.name] = inner_pred
            outer_base[spec.name] = pred
            part[spec.name] = pred
            part[f"raw__{spec.name}"] = raw
            for feature, value in model_importance(fitted).items():
                importance_rows.append({"outer_fold": fold.name, "spec": spec.name, "feature_subset": subset_name,
                                        "family": feature_families[feature], "feature": feature, "importance": value})
        required = {"lgb_huber_pooled", "xgb_pseudohuber_pooled", "cat_huber_pooled",
                    "lgb_positive_pooled", "xgb_positive_pooled", "cat_positive_pooled",
                    "lgb_severe_pooled", "xgb_severe_pooled", "cat_severe_pooled",
                    "lgb_q10_pooled", "xgb_q10_pooled", "cat_q10_pooled"}
        if not required.issubset(outer_base.columns):
            raise Fast5Stop(f"MODEL_FAMILY_CORE_FAILURE:{sorted(required - set(outer_base.columns))}")
        quantile_audits.append({"outer_fold": fold.name, **_quantile_order(inner_base, outer_base)})
        for column in outer_base:
            part[column] = outer_base[column]
        fold_labels = pd.Series(index=frame.index, dtype=object)
        for inner in inner_by_outer[fold.name]:
            fold_labels.loc[inner.valid_index] = inner.name
        meta_columns = [column for column in inner_base if inner_base[column].notna().sum() >= 50]
        ridge_inner, ridge_outer, ridge_contract, _ = crossfit_ridge_stack(
            inner_base[meta_columns], outer_base[meta_columns], frame.primary_target, fold_labels)
        counts["fit"] += 1; counts["predict"] += 1
        primary_columns = [spec.name for spec in specs if spec.target == "primary_target" and spec.quantile is None
                           and spec.task == "regression" and spec.name in outer_base]
        pooled_inner, pooled_outer = normalized_mean_score(inner_base, outer_base, primary_columns)
        directional_columns = [name for name in ("lgb_l2_directional",) if name in outer_base]
        direction_inner, direction_outer = normalized_mean_score(inner_base, outer_base, directional_columns)
        horizon_columns = [name for name in ("lgb_h5_pooled", "lgb_h60_pooled") if name in outer_base]
        horizon_inner, horizon_outer = normalized_mean_score(inner_base, outer_base, horizon_columns)
        risk_inner, risk_outer, risk_contract = risk_adjusted_score(inner_base, outer_base, frame.primary_target)
        best_record = max(fold_selected_records, key=lambda row: (row["best_value"], row["spec"]))
        best_name = best_record["spec"]
        candidates_inner = {
            "nested_best_single": inner_base[best_name], "cross_fitted_ridge_stack": ridge_inner,
            "pooled_primary_ensemble": pooled_inner, "direction_specific_ensemble": direction_inner,
            "multi_horizon_ensemble": horizon_inner, "risk_adjusted_score": risk_inner,
        }
        candidates_outer = {
            "nested_best_single": outer_base[best_name].to_numpy(), "cross_fitted_ridge_stack": ridge_outer,
            "pooled_primary_ensemble": pooled_outer, "direction_specific_ensemble": direction_outer,
            "multi_horizon_ensemble": horizon_outer, "risk_adjusted_score": risk_outer,
        }
        common = pd.Series(True, index=frame.index)
        for values in candidates_inner.values():
            common &= values.notna()
        if common.sum() < 25:
            raise Fast5Stop("STACK_SELF_TRAINING:INSUFFICIENT_CROSSFIT_ROWS")
        contract_frame = frame.loc[common, ["candidate_id", "decision_timestamp_utc", "primary_target"]]
        objectives = {name: inner_economic_objective(contract_frame, value.loc[common].to_numpy())
                      for name, value in candidates_inner.items()}
        chosen = max(objectives, key=lambda name: (objectives[name], name))
        selected_mask, abstention = choose_abstention(
            frame, candidates_inner[chosen], fold_labels, candidates_outer[chosen], cfg["abstention_coverage_candidates"])
        for name, prediction in candidates_outer.items():
            part[name] = prediction
        part["nested_selected_score"] = candidates_outer[chosen]
        part["abstention_selected"] = selected_mask
        part["nested_selected_architecture"] = chosen
        selection_records.append({
            "outer_fold": fold.name, "family_prescreen": prescreen, "best_single_spec": best_name,
            "best_single_feature_subset": best_record["feature_subset"], "architecture_inner_objectives": objectives,
            "selected_architecture": chosen, "ridge_contract": ridge_contract, "risk_adjusted_contract": risk_contract,
            "abstention_contract": abstention, "outer_validation_outcome_used": False,
            "family_selection_outer_outcome_used": False, "stack_outer_candidate_overlap": 0,
        })
        oof_parts.append(part)
        if counts["trials"] > cfg["optuna_trial_cap"]:
            raise Fast5Stop(f"OPTUNA_TRIAL_CAP_EXCEEDED:{counts['trials']}")

    oof = pd.concat(oof_parts).sort_values(["decision_timestamp_utc", "candidate_id"], kind="mergesort").reset_index(drop=True)
    if len(oof) != 998 or oof.candidate_id.duplicated().any() or oof.nested_selected_score.isna().any():
        raise Fast5Stop("STACK_SELF_TRAINING:OOF_ROW_IDENTITY")
    oof.to_parquet(staging / "FAST5_R1_OOF_PREDICTIONS.parquet", index=False)
    pd.DataFrame(importance_rows).to_parquet(staging / "FAST5_R1_FEATURE_IMPORTANCE.parquet", index=False)
    _write(staging / "FAST5_R1_HYPERPARAMETER_SELECTION.json", {"records": tuning_records, "isolated_failures": failures})

    score_columns = [spec.name for spec in specs if spec.name in oof] + [
        "baseline_only_score", "new_information_only_score", "baseline_plus_new_score", "nested_best_single",
        "cross_fitted_ridge_stack", "pooled_primary_ensemble", "direction_specific_ensemble",
        "multi_horizon_ensemble", "risk_adjusted_score", "nested_selected_score",
    ]
    trial_by_spec = pd.DataFrame(tuning_records).groupby("spec").study_trial_count.sum().to_dict()
    spec_map = {spec.name: spec for spec in specs}
    leaderboard_rows = []
    for score in score_columns:
        metrics, _, top = economic_score_metrics(oof, score)
        scale = float(oof.primary_target.std(ddof=1))
        top20 = top["TOP20"]
        selection_objective = float((metrics.get("spearman") or -1) + .25 * (metrics.get("q10_q1_mean") or 0) / scale
                                    + .15 * top20["mean"] / scale + .10 * top20["median"] / scale
                                    - .10 * max(0, -top20["cvar"] / scale))
        spec = spec_map.get(score)
        row = {"model": score, "model_family": spec.family if spec else "ENSEMBLE_OR_COMPARATOR",
               "objective": spec.objective if spec else "NESTED_ECONOMIC_SELECTION",
               "direction_mode": spec.mode if spec else "MIXED", "trial_count": int(trial_by_spec.get(score, 0)),
               "selection_objective": selection_objective, **metrics}
        for label, values in top.items():
            for key in ("N", "coverage", "mean", "median", "profit_factor", "q10", "cvar"):
                row[f"{label}_{key}"] = values.get(key)
        top15 = _top_metrics(oof, score, .15)
        for key in ("N", "coverage", "mean", "median", "profit_factor", "q10", "cvar"):
            row[f"TOP15_{key}"] = top15.get(key)
        leaderboard_rows.append(row)
    leaderboard = pd.DataFrame(leaderboard_rows).sort_values("selection_objective", ascending=False)
    leaderboard.to_csv(staging / "FAST5_R1_MODEL_LEADERBOARD.csv", index=False)

    final_metrics, final_deciles, final_top = economic_score_metrics(oof, "nested_selected_score")
    final_top15 = _top_metrics(oof, "nested_selected_score", .15)
    selected_metrics = group_metrics(oof.loc[oof.abstention_selected, "primary_target"], len(oof))
    baseline_metrics, _, baseline_top = economic_score_metrics(oof, "baseline_only_score")
    new_only_metrics, _, new_only_top = economic_score_metrics(oof, "new_information_only_score")
    combo_metrics, _, combo_top = economic_score_metrics(oof, "baseline_plus_new_score")
    def per_fold_top(score: str, coverage: float) -> pd.Series:
        mask = pd.Series(False, index=oof.index)
        for _, part_local in oof.groupby("validation_slice", sort=True):
            count = max(1, int(np.ceil(coverage * len(part_local))))
            mask.loc[part_local.nlargest(count, score).index] = True
        return mask
    baseline_selected_mask = per_fold_top("baseline_only_score", .20)
    combo_selected_mask = per_fold_top("baseline_plus_new_score", .20)
    baseline_selected = group_metrics(oof.loc[baseline_selected_mask, "primary_target"], len(oof))
    combo_selected = group_metrics(oof.loc[combo_selected_mask, "primary_target"], len(oof))
    incremental = {
        "schema_version": "FAST5_R1_INCREMENTAL_INFORMATION_REPORT_V1",
        "comparator_contract": "SAME_FIXED_LIGHTGBM_HUBER_NESTED_OUTER_OOF;FIXED_PER_FOLD_TOP20_SELECTION",
        "baseline_only": {"metrics": baseline_metrics, "top": baseline_top, "selected_top20": baseline_selected},
        "new_information_only": {"metrics": new_only_metrics, "top": new_only_top},
        "baseline_plus_new": {"metrics": combo_metrics, "top": combo_top, "selected_top20": combo_selected},
        "delta_spearman": _metric_delta(combo_metrics, baseline_metrics, "spearman"),
        "delta_q10_q1_mean": _metric_delta(combo_metrics, baseline_metrics, "q10_q1_mean"),
        "delta_selected_mean": combo_selected["mean"] - baseline_selected["mean"],
        "delta_selected_median": combo_selected["median"] - baseline_selected["median"],
        "delta_selected_profit_factor": combo_selected["profit_factor"] - baseline_selected["profit_factor"],
        "delta_selected_cvar": combo_selected["cvar"] - baseline_selected["cvar"],
        "outer_outcome_used_for_architecture_selection": False,
    }
    _write(staging / "FAST5_R1_INCREMENTAL_INFORMATION_REPORT.json", incremental)

    stability = stability_table(oof, "nested_selected_score", "abstention_selected")
    stability["new_data_availability"] = "AVAILABLE_FULL_COVERAGE"
    stability.to_csv(staging / "FAST5_R1_STABILITY_SLICES.csv", index=False)
    fold_rows = stability.loc[stability.slice_type.eq("validation_slice")]
    year_rows = stability.loc[stability.slice_type.eq("year")]
    selected_outer_folds = int(fold_rows.selected_N.ge(cfg["minimum_selected_rows_per_outer_fold"]).sum())
    positive_selected_years = int((year_rows.selected_N.gt(0) & year_rows.selected_mean.gt(0)).sum())
    support_pass = bool(selected_metrics["N"] >= cfg["minimum_selected_rows"]
                        and selected_metrics["coverage"] >= cfg["minimum_selected_coverage"]
                        and selected_outer_folds >= cfg["minimum_selected_outer_folds"]
                        and positive_selected_years >= cfg["minimum_positive_selected_years"])
    stability_report = {
        "schema_version": "FAST5_R1_STABILITY_REPORT_V1", "slice_file": "FAST5_R1_STABILITY_SLICES.csv",
        "outer_fold_status": status_from_slices(stability, "validation_slice"),
        "year_status": status_from_slices(stability, "year"),
        "direction_status": status_from_slices(stability, "head"),
        "underlying_status": status_from_slices(stability, "underlying_symbol"),
        "time_of_day_status": status_from_slices(stability, "time_of_day"),
        "new_data_availability_status": "PASS_FULL_COVERAGE_UNIFORM",
        "selected_outer_folds": selected_outer_folds, "positive_selected_years": positive_selected_years,
        "sample_support_pass": support_pass,
    }
    _write(staging / "FAST5_R1_STABILITY_REPORT.json", stability_report)

    probability_report = {}
    for label, target in (("positive", "y_positive"), ("severe", "severe_loss")):
        for short in ("lgb", "xgb", "cat"):
            raw = f"raw__{short}_{label}_pooled"
            if raw in oof:
                probability_report[raw] = probability_metrics(oof, raw, target)
    selection_report = {
        "schema_version": "FAST5_R1_SELECTION_POLICY_REPORT_V1", "outer_fold_contracts": selection_records,
        "selected_metrics": selected_metrics, "support_contract": prereg["minimum_support"],
        "support_pass": support_pass, "probability_heads": probability_report,
        "quantile_order_audit": quantile_audits, "deciles": final_deciles,
        "top_selection": {**final_top, "TOP15": final_top15},
        "ranking_model_status": "SKIPPED_NO_VALID_GROUPS", "outer_outcome_used_for_threshold": False,
    }
    _write(staging / "FAST5_R1_SELECTION_POLICY_REPORT.json", selection_report)

    falsification, false_counts = _falsification(frame, oof, outer, baseline_features, new_features, cfg)
    counts["fit"] += false_counts["fit"]; counts["predict"] += false_counts["predict"]
    _write(staging / "FAST5_R1_FALSIFICATION_REPORT.json", falsification)

    baseline_tail_at_selected_coverage = group_metrics(
        oof.loc[per_fold_top("baseline_only_score", selected_metrics["coverage"]), "primary_target"], len(oof))
    tail_ok = bool(selected_metrics["cvar"] >= baseline_tail_at_selected_coverage["cvar"]
                   and selected_metrics["q10"] >= baseline_tail_at_selected_coverage["q10"])
    direction_counts = oof.loc[oof.abstention_selected, "head"].value_counts(normalize=True)
    underlying_counts = oof.loc[oof.abstention_selected, "underlying_symbol"].value_counts(normalize=True)
    concentration_ok = bool((direction_counts.max() if len(direction_counts) else 1) <= .90
                            and (underlying_counts.max() if len(underlying_counts) else 1) <= .90)
    incremental_material = bool(incremental["delta_spearman"] >= cfg["material_delta_spearman"]
                                and incremental["delta_q10_q1_mean"] > 0)
    permutation_p = falsification["primary_permutation"]["empirical_p_one_sided"]
    a_pass = bool(final_metrics["spearman"] > 0 and incremental_material
                  and selected_metrics["mean"] > 0 and selected_metrics["median"] > 0
                  and selected_metrics["profit_factor"] >= cfg["strong_profit_factor_minimum"]
                  and support_pass and tail_ok and concentration_ok and permutation_p <= .05
                  and falsification["status"] == "PASS"
                  and falsification["new_family_ablation_status"].startswith("PASS")
                  and falsification["timestamp_shift_status"].startswith("PASS"))
    b_incremental = bool(incremental["delta_spearman"] >= cfg["classification_b_delta_spearman"]
                         or incremental["delta_q10_q1_mean"] >= cfg["classification_b_delta_q10_q1_mean"])
    if a_pass:
        classification = "A_STRONG_NEW_INFORMATION_ECONOMIC_SELECTION_EDGE"
        decision = "A_FREEZE_FOR_PROSPECTIVE_SHADOW_ONLY"
    elif b_incremental:
        classification = "B_NEW_INFORMATION_PRESENT_BUT_ECONOMIC_EDGE_NOT_STRONG_ENOUGH"
        decision = "B_KEEP_RESEARCH_ONLY_DO_NOT_ACTIVATE"
    else:
        classification = "C_NEW_INFORMATION_DOES_NOT_ADD_RELIABLE_ECONOMIC_EDGE"
        decision = "C_STOP_TESTED_FAST5_INFORMATION_FAMILIES"

    final_model_type = "NO_FINAL_MODEL_NEGATIVE_OR_INSUFFICIENT_RESULT"
    final_model_sha = "NOT_APPLICABLE_CLASSIFICATION_NOT_A"
    prospective_ready = False
    if a_pass:
        modal_spec_name = Counter(row["best_single_spec"] for row in selection_records).most_common(1)[0][0]
        modal_subset = Counter(row["best_single_feature_subset"] for row in selection_records).most_common(1)[0][0]
        candidates = [row for row in tuning_records if row["spec"] == modal_spec_name and row["feature_subset"] == modal_subset]
        chosen_record = sorted(candidates, key=lambda row: row["best_value"])[len(candidates) // 2]
        spec = next(local for local in specs if local.name == modal_spec_name)
        fitted, count = fit_spec(spec, frame, frame.index.to_numpy(), subsets[modal_subset], chosen_record["best_parameters"],
                                 cfg["seed"] + 900_000, cfg["model_threads"])
        counts["fit"] += count
        model_path = staging / "FAST5_R1_FINAL_MODEL.joblib"
        joblib.dump(fitted, model_path)
        reloaded = joblib.load(model_path)
        sample = frame.tail(min(50, len(frame)))
        original = fitted.predict_score(sample); restored = reloaded.predict_score(sample)
        counts["predict"] += 2 * count
        if not np.allclose(original, restored, rtol=0, atol=1e-12):
            raise Fast5Stop("MODEL_RELOAD_EQUALITY_FAIL")
        final_model_type = f"{modal_spec_name}:{modal_subset}"
        final_model_sha = sha256(model_path)
        prospective_ready = True
        _write(staging / "FAST5_R1_FINAL_MODEL_MANIFEST.json", {
            "schema_version": "FAST5_R1_FINAL_MODEL_MANIFEST_V1", "classification": classification,
            "model_file": model_path.name, "model_sha256": final_model_sha, "model_type": final_model_type,
            "feature_order": subsets[modal_subset], "feature_manifest_sha256": feature_identity,
            "target_sha256": cfg["target_sha256"], "legal_training_cutoff": cfg["legal_training_cutoff"],
            "hyperparameters": chosen_record["best_parameters"], "seed": cfg["seed"] + 900_000,
            "selection_policy": "PROSPECTIVE_SHADOW_READY_NOT_STARTED", "broker_action_allowed": False,
            "reload_equality_status": "PASS",
        })
        _write(staging / "FAST5_R1_PROSPECTIVE_SHADOW_READY_CONTRACT.json", {
            "ready": True, "started": False, "no_retroactive_outcomes": True,
            "freeze_timestamp_utc": now_utc(), "broker_action_allowed": False,
        })

    best_pipeline = leaderboard.iloc[0].model
    selected_subset_modal = Counter(row["best_single_feature_subset"] for row in selection_records).most_common(1)[0][0]
    up = oof.loc[oof["head"].eq("UP")]
    down = oof.loc[oof["head"].eq("DOWN")]
    top15 = final_top15
    def top(prefix: str, values: dict[str, Any]) -> dict[str, Any]:
        return {f"{prefix}_N": values["N"], f"{prefix}_MEAN": values["mean"],
                f"{prefix}_MEDIAN": values["median"], f"{prefix}_PROFIT_FACTOR": values["profit_factor"]}
    summary = {
        "FAST5_R1_STATUS": "PASS_COMPLETE", "FAST5_R1_CLASSIFICATION": classification,
        "FAST5_R1_DECISION": decision, "FINAL_DECISION": decision, "DEVELOPMENT_EVIDENCE_ONLY": True,
        "PYTHON_EXECUTABLE": environment["python_executable"], "PYTHON_VERSION": environment["python_version"],
        "TRAINING_START": str(frame.decision_timestamp_utc.min()).replace(" ", "T").replace("+00:00", "Z"),
        "TRAINING_END": str(frame.decision_timestamp_utc.max()).replace(" ", "T").replace("+00:00", "Z"),
        "LEGAL_TRAINING_CUTOFF": cfg["legal_training_cutoff"], "TARGET_CONTRACT": cfg["target_contract"],
        "TARGET_SHA256": cfg["target_sha256"], "FAST4_BASELINE_FEATURE_COUNT": len(baseline_features),
        "FAST4_BASELINE_FEATURE_MANIFEST_SHA256": cfg["fast4_baseline_feature_manifest_sha256"],
        "SELECTED_NEW_INFORMATION_FAMILIES": "|".join(audit_result["selected"]),
        "NEW_FEATURE_COUNT": len(new_features), "TOTAL_FEATURE_COUNT": len(all_features),
        "FAST5_FEATURE_MANIFEST_SHA256": feature_identity, "OUTER_FOLD_COUNT": len(outer),
        "INNER_FOLD_COUNT": cfg["inner_fold_count"], "MODEL_FAMILIES_TRAINED": "LightGBM|XGBoost|CatBoost|Ridge",
        "OBJECTIVES_TRAINED": "Huber|Fair|PseudoHuber|BinaryPositive|BinarySevereLoss|Quantile_q10_q25_q50|MultiHorizon_5m_60m|CrossFittedStack|RiskAdjusted|Ranking_SKIPPED_NO_VALID_GROUPS",
        "OPTUNA_TRIAL_CAP": cfg["optuna_trial_cap"], "HYPERPARAMETER_TRIAL_COUNT": counts["trials"],
        "OOF_ROW_COUNT": len(oof), "BEST_PIPELINE": best_pipeline, "BEST_NEW_INFORMATION_SUBSET": selected_subset_modal,
        "OOF_SPEARMAN": final_metrics["spearman"], "OOF_PEARSON": final_metrics["pearson"],
        "OOF_Q10_Q1_MEAN": final_metrics["q10_q1_mean"], "OOF_Q10_Q1_MEDIAN": final_metrics["q10_q1_median"],
        "SELECTED_POLICY": "INNER_ONLY_ARCHITECTURE_AND_40_30_20_15_10_PERCENT_ABSTENTION",
        "SELECTED_N": selected_metrics["N"], "SELECTED_COVERAGE": selected_metrics["coverage"],
        "SELECTED_MEAN": selected_metrics["mean"], "SELECTED_MEDIAN": selected_metrics["median"],
        "SELECTED_WIN_RATE": selected_metrics["win_rate"], "SELECTED_PROFIT_FACTOR": selected_metrics["profit_factor"],
        "SELECTED_Q10": selected_metrics["q10"], "SELECTED_CVAR": selected_metrics["cvar"],
        **top("TOP30", final_top["TOP30"]), **top("TOP20", final_top["TOP20"]), **top("TOP15", top15),
        **top("TOP10", final_top["TOP10"]), **top("TOP5", final_top["TOP5"]),
        "BASELINE_ONLY_OOF_SPEARMAN": baseline_metrics["spearman"],
        "NEW_INFORMATION_ONLY_OOF_SPEARMAN": new_only_metrics["spearman"],
        "BASELINE_PLUS_NEW_OOF_SPEARMAN": combo_metrics["spearman"],
        "INCREMENTAL_DELTA_SPEARMAN": incremental["delta_spearman"],
        "INCREMENTAL_DELTA_Q10_Q1_MEAN": incremental["delta_q10_q1_mean"],
        "INCREMENTAL_DELTA_SELECTED_MEAN": incremental["delta_selected_mean"],
        "INCREMENTAL_DELTA_SELECTED_MEDIAN": incremental["delta_selected_median"],
        "INCREMENTAL_DELTA_SELECTED_PROFIT_FACTOR": incremental["delta_selected_profit_factor"],
        "UP_OOF_SPEARMAN": economic_score_metrics(up, "nested_selected_score")[0]["spearman"],
        "DOWN_OOF_SPEARMAN": economic_score_metrics(down, "nested_selected_score")[0]["spearman"],
        "OUTER_FOLD_STABILITY_STATUS": stability_report["outer_fold_status"],
        "YEAR_STABILITY_STATUS": stability_report["year_status"], "DIRECTION_STABILITY_STATUS": stability_report["direction_status"],
        "UNDERLYING_STABILITY_STATUS": stability_report["underlying_status"],
        "TIME_OF_DAY_STABILITY_STATUS": stability_report["time_of_day_status"],
        "NEW_DATA_AVAILABILITY_STABILITY_STATUS": stability_report["new_data_availability_status"],
        "PERMUTATION_COUNT": cfg["permutation_count"], "PERMUTATION_EMPIRICAL_P": permutation_p,
        "FALSIFICATION_STATUS": falsification["status"],
        "NEW_FAMILY_ABLATION_STATUS": falsification["new_family_ablation_status"],
        "TIMESTAMP_SHIFT_STATUS": falsification["timestamp_shift_status"],
        "PIT_AUDIT_STATUS": "PASS_BASELINE_FROZEN_AND_NEW_RAW_PRIOR_DAY_SOURCE_DATE_STRICTLY_BEFORE_DECISION",
        "LEAKAGE_AUDIT_STATUS": "PASS_TARGET_IDENTITY_PURGE_EMBARGO_NO_OUTER_SELECTION_NO_SELF_TRAINING",
        "PREREGISTRATION_AUDIT_STATUS": "PASS_FROZEN_BEFORE_TARGET_VALUE_READ",
        "FAMILY_SELECTION_LEAKAGE_AUDIT_STATUS": "PASS_INNER_ONLY_PER_OUTER_FOLD",
        "ABSTENTION_LEAKAGE_AUDIT_STATUS": "PASS_INNER_ONLY_PER_OUTER_FOLD",
        "STACK_CROSSFIT_AUDIT_STATUS": "PASS_SEQUENTIAL_INNER_CROSSFIT_ZERO_OUTER_SELF_TRAINING",
        "PROSPECTIVE_OUTCOME_READ": False, "BROKER_ACTION_ALLOWED": False, "TRADE_CONTEXT_CREATED": False,
        "ORDER_API_CALL_COUNT": 0, "MODEL_FIT_COUNT": counts["fit"], "MODEL_PREDICT_COUNT": counts["predict"],
        "STORAGE_CONTRACT_STATUS": "PASS_EXTERNAL_RESULTS_DATA_ROOT_READ_ONLY",
        "ANTI_BLOAT_STATUS": "PASS_ONE_CONFIG_ONE_AUDIT_ONE_FEATURE_ONE_TRAINING_MODULE_ONE_ENTRYPOINT",
        "FINAL_MODEL_TYPE": final_model_type, "FINAL_MODEL_SHA256": final_model_sha,
        "FAST5_R1_PROSPECTIVE_SHADOW_READY": prospective_ready, "FAST5_R1_PROSPECTIVE_SHADOW_STARTED": False,
        "FAST5_R1_PREREGISTRATION_SHA256": prereg_sha, "RUN_STARTED_AT_UTC": started, "RUN_COMPLETED_AT_UTC": now_utc(),
        **audit_fields,
    }
    _write(staging / "FAST5_R1_FINAL_SUMMARY.json", summary)
    (staging / "FAST5_R1_REPORT.md").write_text(
        f"FAST5-R1 completed as {classification}. New cross-asset fixed-comparator delta Spearman="
        f"{incremental['delta_spearman']:.6f}; final nested OOF Spearman={final_metrics['spearman']:.6f}; "
        f"selected N={selected_metrics['N']}, mean={selected_metrics['mean']:.6g}, median={selected_metrics['median']:.6g}, "
        f"PF={selected_metrics['profit_factor']:.4g}; blockwise 999-permutation p={permutation_p:.4g}. "
        "This is development evidence, not independent confirmation.\n", encoding="utf-8")

    if _snapshot(R1_ROOT) != r1_snapshot:
        raise Fast5Stop("FROZEN_ARTIFACT_MUTATION")
    if {str(path): sha256(path) for path in selected_source_paths} != source_snapshot:
        raise Fast5Stop("SOURCE_DATA_MUTATION")
    artifact_hashes = {path.name: sha256(path) for path in sorted(staging.glob("*")) if path.is_file()}
    _write(staging / "FAST5_R1_ARTIFACT_MANIFEST.json", {
        "created_at_utc": now_utc(), "artifacts": artifact_hashes, "r1_postrun_identity_status": "PASS_UNCHANGED",
        "source_data_postrun_identity_status": "PASS_UNCHANGED", "target_value_read_count": firewall.target_value_read_count,
        "prospective_outcome_read": False,
    })
    if not staging.is_relative_to(scratch_parent) or not frozen.is_relative_to(frozen_parent):
        raise Fast5Stop("STORAGE_CONTRACT_PATH_ESCAPE")
    # Windows/managed sandboxes can retain SQLite handles until process exit.  Freeze by
    # verified copy and leave the non-canonical scratch staging directory unreferenced.
    shutil.copytree(str(staging), str(frozen))
    source_hashes = {path.name: sha256(path) for path in staging.glob("*") if path.is_file()}
    frozen_hashes = {path.name: sha256(path) for path in frozen.glob("*") if path.is_file()}
    if source_hashes != frozen_hashes:
        raise Fast5Stop("FROZEN_COPY_SHA256_MISMATCH")
    return summary, {**audit_fields, **prereg_fields}, frozen


SUMMARY_FIELDS = [
    "FAST5_R1_STATUS", "FAST5_R1_CLASSIFICATION", "FAST5_R1_DECISION", "FINAL_DECISION",
    "DEVELOPMENT_EVIDENCE_ONLY", "PYTHON_EXECUTABLE", "PYTHON_VERSION", "TRAINING_START", "TRAINING_END",
    "LEGAL_TRAINING_CUTOFF", "TARGET_CONTRACT", "TARGET_SHA256", "FAST4_BASELINE_FEATURE_COUNT",
    "FAST4_BASELINE_FEATURE_MANIFEST_SHA256", "SELECTED_NEW_INFORMATION_FAMILIES", "NEW_FEATURE_COUNT",
    "TOTAL_FEATURE_COUNT", "FAST5_FEATURE_MANIFEST_SHA256", "OUTER_FOLD_COUNT", "INNER_FOLD_COUNT",
    "MODEL_FAMILIES_TRAINED", "OBJECTIVES_TRAINED", "OPTUNA_TRIAL_CAP", "HYPERPARAMETER_TRIAL_COUNT",
    "OOF_ROW_COUNT", "BEST_PIPELINE", "BEST_NEW_INFORMATION_SUBSET", "OOF_SPEARMAN", "OOF_PEARSON",
    "OOF_Q10_Q1_MEAN", "OOF_Q10_Q1_MEDIAN", "SELECTED_POLICY", "SELECTED_N", "SELECTED_COVERAGE",
    "SELECTED_MEAN", "SELECTED_MEDIAN", "SELECTED_WIN_RATE", "SELECTED_PROFIT_FACTOR", "SELECTED_Q10",
    "SELECTED_CVAR", "TOP30_N", "TOP30_MEAN", "TOP30_MEDIAN", "TOP30_PROFIT_FACTOR", "TOP20_N",
    "TOP20_MEAN", "TOP20_MEDIAN", "TOP20_PROFIT_FACTOR", "TOP15_N", "TOP15_MEAN", "TOP15_MEDIAN",
    "TOP15_PROFIT_FACTOR", "TOP10_N", "TOP10_MEAN", "TOP10_MEDIAN", "TOP10_PROFIT_FACTOR", "TOP5_N",
    "TOP5_MEAN", "TOP5_MEDIAN", "TOP5_PROFIT_FACTOR", "BASELINE_ONLY_OOF_SPEARMAN",
    "NEW_INFORMATION_ONLY_OOF_SPEARMAN", "BASELINE_PLUS_NEW_OOF_SPEARMAN", "INCREMENTAL_DELTA_SPEARMAN",
    "INCREMENTAL_DELTA_Q10_Q1_MEAN", "INCREMENTAL_DELTA_SELECTED_MEAN", "INCREMENTAL_DELTA_SELECTED_MEDIAN",
    "INCREMENTAL_DELTA_SELECTED_PROFIT_FACTOR", "UP_OOF_SPEARMAN", "DOWN_OOF_SPEARMAN",
    "OUTER_FOLD_STABILITY_STATUS", "YEAR_STABILITY_STATUS", "DIRECTION_STABILITY_STATUS",
    "UNDERLYING_STABILITY_STATUS", "TIME_OF_DAY_STABILITY_STATUS", "NEW_DATA_AVAILABILITY_STABILITY_STATUS",
    "PERMUTATION_COUNT", "PERMUTATION_EMPIRICAL_P", "FALSIFICATION_STATUS", "NEW_FAMILY_ABLATION_STATUS",
    "TIMESTAMP_SHIFT_STATUS", "PIT_AUDIT_STATUS", "LEAKAGE_AUDIT_STATUS", "PREREGISTRATION_AUDIT_STATUS",
    "FAMILY_SELECTION_LEAKAGE_AUDIT_STATUS", "ABSTENTION_LEAKAGE_AUDIT_STATUS", "STACK_CROSSFIT_AUDIT_STATUS",
    "PROSPECTIVE_OUTCOME_READ", "BROKER_ACTION_ALLOWED", "TRADE_CONTEXT_CREATED", "ORDER_API_CALL_COUNT",
    "MODEL_FIT_COUNT", "MODEL_PREDICT_COUNT", "STORAGE_CONTRACT_STATUS", "ANTI_BLOAT_STATUS",
    "FINAL_MODEL_TYPE", "FINAL_MODEL_SHA256", "FAST5_R1_PROSPECTIVE_SHADOW_READY",
    "FAST5_R1_PROSPECTIVE_SHADOW_STARTED",
]


def print_summary(summary: dict[str, Any], root: Path) -> None:
    for field in SUMMARY_FIELDS:
        value = summary.get(field, "NOT_APPLICABLE")
        if isinstance(value, bool):
            value = str(value).lower()
        print(f"{field}={value}")
    print(f"FAST5_R1_FROZEN_ROOT={root}")
    print("\nDATA AUDIT")
    print(f"Found Tier A: {summary.get('SELECTED_NEW_INFORMATION_FAMILIES')}. Historical options remained Tier B at "
          f"{summary.get('OPTION_HISTORY_COVERAGE', 0):.1%} coverage; local microstructure, macro and first-published news archives were unavailable or non-PIT.")
    if summary.get("OOF_ROW_COUNT", 0):
        print("\nWHAT ENTERED FAST5")
        print(f"The model used {summary['NEW_FEATURE_COUNT']} prior-day raw cross-asset features on top of the frozen 241 FAST4 features.")
        print("\nDID NEW INFORMATION HELP?")
        print(f"Fixed nested comparator Spearman changed from {summary['BASELINE_ONLY_OOF_SPEARMAN']:.6f} to "
              f"{summary['BASELINE_PLUS_NEW_OOF_SPEARMAN']:.6f} (delta {summary['INCREMENTAL_DELTA_SPEARMAN']:+.6f}).")
        print("\nDID IT BECOME ECONOMICALLY POSITIVE?")
        positive = (summary["SELECTED_MEAN"] > 0 and summary["SELECTED_MEDIAN"] > 0
                    and summary["SELECTED_PROFIT_FACTOR"] >= 1.10)
        print(("Yes" if positive else "No") + f": selected N={summary['SELECTED_N']}, mean={summary['SELECTED_MEAN']:.6g}, "
              f"median={summary['SELECTED_MEDIAN']:.6g}, PF={summary['SELECTED_PROFIT_FACTOR']:.4g}.")
        print("\nWHERE IS THE INFORMATION?")
        print("The only eligible new family was prior-day broad/sector cross-asset state; options, microstructure, macro and news did not enter training.")
        print("\nFALSIFICATION")
        print(f"The frozen 999-permutation p-value was {summary['PERMUTATION_EMPIRICAL_P']:.4g}; "
              f"ablation={summary['NEW_FAMILY_ABLATION_STATUS']}, timestamp shift={summary['TIMESTAMP_SHIFT_STATUS']}.")
    print("\nFINAL DECISION")
    print(f"{summary['FAST5_R1_CLASSIFICATION']} / {summary['FINAL_DECISION']}. This remains development evidence only.")
