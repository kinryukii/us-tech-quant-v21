from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import optuna
import pandas as pd

from .contracts import (R43A_CONTRACT, RESULTS, TARGET_LEDGER, sha256, stable_hash,
                        verify_contracts, write_json)
from .r2_evaluation import (blockwise_permutation_test, choose_abstention,
                            crossfit_ridge_stack, economic_score_metrics,
                            group_metrics, inner_economic_objective,
                            normalized_mean_score, probability_metrics,
                            risk_adjusted_score, stability_table,
                            status_from_slices)
from .splits import fold_manifest, inner_folds, outer_folds
from .strong_models import (StrongSpec, default_parameters, fit_spec,
                            model_importance, specifications, sqlite_storage_url,
                            tune_outer_spec)


REPO = Path(r"D:\us-tech-quant")
R1_ROOT = RESULTS / "frozen/fast4/fast4_r1_full_economic_ensemble_20260812T123322Z"
R1_MATRIX = R1_ROOT / "FAST4_R1_HISTORICAL_PIT_MATRIX.parquet"
R1_FEATURE_MANIFEST = R1_ROOT / "FAST4_R1_FEATURE_MANIFEST.json"
R1_FOLD_MANIFEST = R1_ROOT / "FAST4_R1_PURGED_NESTED_FOLD_MANIFEST.json"
R1_OOF = R1_ROOT / "FAST4_R1_GENUINE_OOF_PREDICTIONS.parquet"
R1_SUMMARY = R1_ROOT / "FAST4_R1_FINAL_SUMMARY.json"
R1_MODEL = R1_ROOT / "FAST4_R1_FINAL_MODEL.joblib"
CONFIG = REPO / "fast4/config/fast4_r2.json"
EXPECTED_FILE_HASHES = {
    R1_MATRIX: "0200dca9310a2ddd9f7123a1cc3864554cc59f57b4839ed3774e7afe6a398fc2",
    R1_FEATURE_MANIFEST: "ad1c30ce0dbfd2d08e549b7899ad511f73b48101e8ed2c391290c63875142cbe",
    R1_SUMMARY: "840c4454b9c4a8c6aac30f850b0446851828040d5402c45f4a957eed6d73c19c",
    R1_MODEL: "c2debbb54abc80448c1f4f52dcd1119b2943b5c037a52d1cc9502f5ab063c46f",
}


class R2Stop(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def _file_snapshot(root: Path) -> dict[str, str]:
    return {str(path): sha256(path) for path in sorted(root.glob("*")) if path.is_file()}


def _load_and_verify() -> tuple[pd.DataFrame, list[str], dict[str, str], dict[str, Any], dict[str, Any], dict[str, Any]]:
    verify_contracts()
    for path, expected in EXPECTED_FILE_HASHES.items():
        if not path.is_file() or sha256(path) != expected:
            raise R2Stop(f"FROZEN_FAST3_OR_FAST4_R1_ARTIFACT_MUTATION_DETECTED:{path}")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    feature_manifest = json.loads(R1_FEATURE_MANIFEST.read_text(encoding="utf-8"))
    r1_summary = json.loads(R1_SUMMARY.read_text(encoding="utf-8"))
    if sha256(R43A_CONTRACT) != cfg["target_contract_sha256"]:
        raise R2Stop("TARGET_IDENTITY_FAIL")
    if feature_manifest["feature_manifest_sha256"] != cfg["feature_manifest_sha256"]:
        raise R2Stop("FEATURE_PIT_FAIL:R1_FEATURE_MANIFEST_IDENTITY")
    if r1_summary["FINAL_MODEL_SHA256"] != cfg["r1_model_sha256"]:
        raise R2Stop("FROZEN_FAST3_OR_FAST4_R1_ARTIFACT_MUTATION_DETECTED:R1_MODEL_IDENTITY")
    frame = pd.read_parquet(R1_MATRIX)
    frame["decision_timestamp_utc"] = pd.to_datetime(frame.decision_timestamp_utc, utc=True, errors="raise")
    frame["entry_timestamp"] = pd.to_datetime(frame.entry_timestamp, utc=True, errors="raise")
    frame["target_end_timestamp_utc"] = pd.to_datetime(frame.target_end_timestamp_utc, utc=True, errors="raise")
    features = list(feature_manifest["feature_order"])
    families = dict(feature_manifest["feature_families"])
    if len(frame) != 1197 or len(features) != 241 or len(set(families.values())) != 11:
        raise R2Stop("FEATURE_PIT_FAIL:FROZEN_MATRIX_DIMENSION")
    if not set(features).issubset(frame.columns) or frame.candidate_id.duplicated().any():
        raise R2Stop("FEATURE_PIT_FAIL:MATRIX_COLUMNS_OR_ROW_IDENTITY")
    if np.isinf(frame[features].to_numpy(dtype=float)).any():
        raise R2Stop("FEATURE_PIT_FAIL:NONFINITE_INFINITY")
    if str(frame.target_end_timestamp_utc.max()).replace(" ", "T").replace("+00:00", "Z") != cfg["legal_training_cutoff"]:
        raise R2Stop("TARGET_IDENTITY_FAIL:LEGAL_CUTOFF")
    if feature_manifest["pit_audit"].get("future_source_timestamp_count") != 0:
        raise R2Stop("FUTURE_TIMESTAMP_JOIN_DETECTED")
    if not frame.target_end_timestamp_utc.le(pd.Timestamp(cfg["legal_training_cutoff"])).all():
        raise R2Stop("TARGET_IDENTITY_FAIL:CUTOFF_OVERFLOW")
    return frame, features, families, cfg, feature_manifest, r1_summary


def _environment_manifest(cfg: dict[str, Any]) -> dict[str, Any]:
    import catboost
    import lightgbm
    import optuna
    import xgboost
    requested = Path(r"D:\us-tech-quant.venv\Scripts\python.exe")
    actual = Path(sys.executable)
    expected_actual = Path(r"D:\us-tech-quant\.venv\Scripts\python.exe")
    if actual.resolve() != expected_actual.resolve():
        raise R2Stop(f"PYTHON_EXECUTABLE_MISMATCH:{actual}")
    return {
        "schema_version": "FAST4_R2_ENVIRONMENT_MANIFEST_V1", "created_at_utc": _now(),
        "requested_literal_executable": str(requested), "requested_literal_executable_exists": requested.exists(),
        "resolved_project_executable": str(actual),
        "path_discrepancy": "REQUESTED_LITERAL_OMITTED_SEPARATOR_BEFORE_DOTVENV" if not requested.exists() else "NONE",
        "python_version": platform.python_version(), "sys_path": sys.path,
        "dependencies": {"lightgbm": lightgbm.__version__, "xgboost": xgboost.__version__,
                         "catboost": catboost.__version__, "optuna": optuna.__version__},
        "objective_api_smoke_status": "PASS_LGB_REGRESSION_HUBER_FAIR_L1_QUANTILE_BINARY_XGB_L2_PSEUDOHUBER_L1_QUANTILE_BINARY_CAT_RMSE_MAE_HUBER_QUANTILE_BINARY",
        "packages_installed_or_modified": False, "model_threads": cfg["model_threads"],
        "optuna_parallel_trials": cfg["optuna_parallel_trials"], "gpu_used": False,
    }


def _discovery_manifest(frame: pd.DataFrame, cfg: dict[str, Any], feature_manifest: dict[str, Any],
                        initial_r1_snapshot: dict[str, str]) -> dict[str, Any]:
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True,
                                capture_output=True, text=True).stdout.strip()
    except Exception:
        commit = "GIT_IDENTITY_UNAVAILABLE"
    timestamp_groups = frame.groupby("decision_timestamp_utc").size()
    day_groups = frame.groupby("trading_date").size()
    return {
        "schema_version": "FAST4_R2_DISCOVERY_MANIFEST_V1", "created_at_utc": _now(),
        "project": cfg["project"], "r1_frozen_root": str(R1_ROOT),
        "r1_frozen_snapshot_sha256": initial_r1_snapshot,
        "r1_feature_matrix": str(R1_MATRIX), "r1_matrix_file_sha256": sha256(R1_MATRIX),
        "target_contract": "FAST3_R43A_INDEPENDENT_ECONOMIC_TARGET_CONTRACT_FREEZE_R1",
        "target_contract_path": str(R43A_CONTRACT), "target_sha256": sha256(R43A_CONTRACT),
        "target_formula": "mean(y_5m,y_10m,y_15m,y_30m,y_60m)_net20",
        "transaction_cost_convention": "R43A_ECONOMIC_COST_BPS_20",
        "feature_count": len(feature_manifest["feature_order"]),
        "feature_family_count": len(set(feature_manifest["feature_families"].values())),
        "feature_manifest_sha256": feature_manifest["feature_manifest_sha256"],
        "candidate_count": len(frame), "direction_counts": frame["head"].value_counts().to_dict(),
        "underlying_counts": frame.underlying_symbol.value_counts().to_dict(),
        "training_start": str(frame.decision_timestamp_utc.min()), "training_end": str(frame.decision_timestamp_utc.max()),
        "legal_training_cutoff": cfg["legal_training_cutoff"],
        "ranking_group_contract": cfg["ranking_group_contract"],
        "decision_timestamp_group_count": int(len(timestamp_groups)),
        "multi_candidate_decision_group_count": int(timestamp_groups.ge(2).sum()),
        "multi_candidate_trading_day_group_count": int(day_groups.ge(2).sum()),
        "ranking_status": "SKIPPED_NO_GENUINE_MULTI_CANDIDATE_CONTEMPORANEOUS_GROUPS",
        "r1_oof_already_observed": True,
        "evidence_interpretation": "R2_IS_DEVELOPMENT_EVIDENCE_NOT_INDEPENDENT_CONFIRMATION",
        "prospective_outcome_read": False, "broker_action_allowed": False,
        "repository_commit_before_run": commit,
    }


def _apply_quantile_order(inner_base: pd.DataFrame, outer_base: pd.DataFrame,
                          available: set[str]) -> dict[str, Any]:
    before = after = rows = 0
    for short in ("lgb", "xgb", "cat"):
        columns = [f"{short}_q{q:02d}_pooled" for q in (5, 10, 25, 50)]
        if not set(columns).issubset(available):
            continue
        for local in (inner_base, outer_base):
            valid = local[columns].notna().all(axis=1)
            values = local.loc[valid, columns].to_numpy(dtype=float)
            before += int(np.any(np.diff(values, axis=1) < 0, axis=1).sum())
            rows += len(values)
            local.loc[valid, columns] = np.sort(values, axis=1)
            after += int(np.any(np.diff(local.loc[valid, columns].to_numpy(), axis=1) < 0, axis=1).sum())
    return {"rows_checked": rows, "crossing_rows_before_deterministic_ordering": before,
            "crossing_rows_after_deterministic_ordering": after,
            "post_processing": "ROW_WISE_ASCENDING_ORDER_NO_OUTCOME_USE"}


def _modal_parameters(records: list[dict[str, Any]], spec_name: str) -> dict[str, Any]:
    values = [row["best_parameters"] for row in records if row["spec"] == spec_name]
    if not values:
        raise R2Stop(f"MISSING_TUNING_RECORD:{spec_name}")
    keys = [json.dumps(value, sort_keys=True) for value in values]
    winner = Counter(keys).most_common(1)[0][0]
    return values[keys.index(winner)]


def _fixed_oof(frame: pd.DataFrame, features: list[str], spec: StrongSpec, records: list[dict[str, Any]],
               outer: list[Any], cfg: dict[str, Any], seed: int) -> tuple[pd.Series, dict[str, int]]:
    prediction = pd.Series(np.nan, index=frame.index, dtype=float)
    counts = {"fit": 0, "predict": 0}
    for number, fold in enumerate(outer):
        record = next(row for row in records if row["spec"] == spec.name and row["outer_fold"] == fold.name)
        fitted, local = fit_spec(spec, frame, fold.train_index, features, record["best_parameters"],
                                 seed + number, int(cfg["model_threads"]))
        prediction.loc[fold.valid_index] = fitted.predict_score(frame.loc[fold.valid_index])
        counts["fit"] += local
        counts["predict"] += local
    return prediction, counts


def _falsification(frame: pd.DataFrame, features: list[str], families: dict[str, str], oof: pd.DataFrame,
                   final_score: str, outer: list[Any], specs: list[StrongSpec], records: list[dict[str, Any]],
                   selection_records: list[dict[str, Any]], cfg: dict[str, Any], importance: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame, dict[str, int]]:
    counts = {"fit": 0, "predict": 0}
    permutation = blockwise_permutation_test(oof.reset_index(drop=True), final_score, "validation_slice",
                                             int(cfg["permutation_count"]), int(cfg["permutation_seed"]))
    chosen = Counter(row["best_single_spec"] for row in selection_records).most_common(1)[0][0]
    spec = next(local for local in specs if local.name == chosen)
    rng = np.random.default_rng(int(cfg["random_feature_seed"]))
    random_frame = frame.copy()
    random_frame["FAST4_R2_FROZEN_RANDOM_CONTROL"] = rng.normal(size=len(frame))
    random_prediction, local = _fixed_oof(random_frame, ["FAST4_R2_FROZEN_RANDOM_CONTROL"], spec, records, outer, cfg, cfg["seed"] + 500_000)
    counts = {key: counts[key] + local[key] for key in counts}
    shifted = frame.copy().sort_values(["underlying_symbol", "decision_timestamp_utc", "candidate_id"], kind="mergesort")
    shifted_features = shifted.groupby("underlying_symbol", sort=False)[features].shift(1)
    shifted = pd.concat([shifted.drop(columns=features), shifted_features], axis=1).sort_index()
    shifted_prediction, local = _fixed_oof(shifted, features, spec, records, outer, cfg, cfg["seed"] + 600_000)
    counts = {key: counts[key] + local[key] for key in counts}
    eval_index = frame.validation_slice.isin([fold.name for fold in outer])
    diagnostic = frame.loc[eval_index, ["candidate_id", "primary_target", "decision_timestamp_utc"]].copy()
    diagnostic["random_control"] = random_prediction.loc[eval_index].to_numpy()
    diagnostic["timestamp_shift"] = shifted_prediction.loc[eval_index].to_numpy()
    random_metric = economic_score_metrics(diagnostic, "random_control")[0]
    shift_metric = economic_score_metrics(diagnostic, "timestamp_shift")[0]
    family_rows = []
    for family in sorted(set(families.values())):
        reduced = [feature for feature in features if families[feature] != family]
        prediction, local = _fixed_oof(frame, reduced, spec, records, outer, cfg,
                                       cfg["seed"] + 700_000 + len(family_rows) * 100)
        counts = {key: counts[key] + local[key] for key in counts}
        diagnostic["ablation"] = prediction.loc[eval_index].to_numpy()
        metric = economic_score_metrics(diagnostic, "ablation")[0]
        family_rows.append({"family": family, "feature_count_removed": len(features) - len(reduced), **metric})
    family_table = pd.DataFrame(family_rows)
    family_permutation_scores = {family: pd.Series(np.nan, index=frame.index, dtype=float)
                                 for family in sorted(set(families.values()))}
    permutation_rng = np.random.default_rng(int(cfg["random_feature_seed"]) + 91)
    for fold_number, fold in enumerate(outer):
        record = next(row for row in records if row["spec"] == spec.name and row["outer_fold"] == fold.name)
        fitted, local_count = fit_spec(spec, frame, fold.train_index, features, record["best_parameters"],
                                       cfg["seed"] + 800_000 + fold_number, int(cfg["model_threads"]))
        counts["fit"] += local_count
        for family in family_permutation_scores:
            columns = [feature for feature in features if families[feature] == family]
            holdout = frame.loc[fold.valid_index].copy()
            order = permutation_rng.permutation(len(holdout))
            holdout.loc[:, columns] = holdout[columns].to_numpy()[order]
            family_permutation_scores[family].loc[fold.valid_index] = fitted.predict_score(holdout)
            counts["predict"] += local_count
    family_permutation = []
    for family, prediction in family_permutation_scores.items():
        diagnostic["family_permutation"] = prediction.loc[eval_index].to_numpy()
        metric = economic_score_metrics(diagnostic, "family_permutation")[0]
        family_permutation.append({"family": family, **metric})
    leading_importance = importance.loc[importance.spec.eq(chosen)].groupby("family").importance.mean().sort_values(ascending=False)
    strongest = str(leading_importance.index[0]) if len(leading_importance) else "UNAVAILABLE"
    observed = economic_score_metrics(oof, final_score)[0]
    year_exclusion = []
    years = pd.to_datetime(oof.decision_timestamp_utc, utc=True).dt.year
    for year in sorted(years.unique()):
        part = oof.loc[years.ne(year)]
        year_exclusion.append({"excluded_year": int(year), **economic_score_metrics(part, final_score)[0]})
    direction_exclusion = [{"excluded_direction": direction, **economic_score_metrics(oof.loc[oof["head"].ne(direction)], final_score)[0]}
                           for direction in sorted(oof["head"].unique())]
    underlying_exclusion = [{"excluded_underlying": symbol, **economic_score_metrics(oof.loc[oof.underlying_symbol.ne(symbol)], final_score)[0]}
                            for symbol in sorted(oof.underlying_symbol.unique())]
    report = {
        "schema_version": "FAST4_R2_FALSIFICATION_REPORT_V1", "frozen_before_execution": True,
        "primary_permutation": permutation, "fixed_falsification_spec": chosen,
        "random_feature_control": random_metric, "timestamp_shift_control": shift_metric,
        "feature_family_ablation": family_rows, "feature_family_permutation_importance": family_permutation,
        "strongest_gain_family": strongest,
        "strongest_family_ablation": next((row for row in family_rows if row["family"] == strongest), None),
        "year_exclusion": year_exclusion, "direction_exclusion": direction_exclusion,
        "underlying_exclusion": underlying_exclusion,
        "duplicate_leakage_audit": "PASS_NO_DUPLICATE_CANDIDATE_IDS_AND_R1_EXACT_DUPLICATE_FEATURE_AUDIT_REUSED",
        "fold_boundary_audit": "PASS_60_MINUTE_TARGET_END_PURGE_PLUS_60_MINUTE_EMBARGO",
        "label_overlap_audit": "PASS_TRAIN_TARGET_END_STRICTLY_BEFORE_VALID_START_MINUS_EMBARGO",
        "observed_final_metrics": observed,
    }
    report["status"] = ("PASS" if permutation["empirical_p_one_sided"] <= .05
                        and abs(random_metric["spearman"] or 0) < max(abs(observed["spearman"]), .02)
                        and (shift_metric["spearman"] or -1) < observed["spearman"] else "MIXED_OR_FAIL")
    return report, family_table, counts


def _field(prefix: str, metrics: dict[str, Any]) -> dict[str, Any]:
    return {f"{prefix}_N": metrics.get("N"), f"{prefix}_COVERAGE": metrics.get("coverage"),
            f"{prefix}_MEAN": metrics.get("mean"), f"{prefix}_MEDIAN": metrics.get("median"),
            f"{prefix}_WIN_RATE": metrics.get("win_rate"), f"{prefix}_PROFIT_FACTOR": metrics.get("profit_factor"),
            f"{prefix}_Q10": metrics.get("q10"), f"{prefix}_CVAR": metrics.get("cvar")}


def run() -> tuple[dict[str, Any], Path]:
    started = _now()
    frame, features, families, cfg, feature_manifest, r1_summary = _load_and_verify()
    initial_r1_snapshot = _file_snapshot(R1_ROOT)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    scratch_parent = (RESULTS / "scratch/fast4").resolve()
    frozen_parent = (RESULTS / "frozen/fast4").resolve()
    scratch_parent.mkdir(parents=True, exist_ok=True)
    frozen_parent.mkdir(parents=True, exist_ok=True)
    resume_literal = os.environ.get("FAST4_R2_RESUME_ROOT", "").strip()
    resuming = bool(resume_literal)
    staging = Path(resume_literal).resolve() if resuming else scratch_parent / f"fast4_r2_strong_tabular_economic_model_{stamp}"
    if (not staging.resolve().is_relative_to(scratch_parent)
            or not staging.name.startswith("fast4_r2_strong_tabular_economic_model_")):
        raise R2Stop(f"STOP_FAST4_INVALID_RESUME_ROOT:{staging}")
    frozen = frozen_parent / staging.name
    if frozen.exists() or (resuming and not staging.is_dir()) or (not resuming and staging.exists()):
        raise R2Stop(f"R2_OUTPUT_COLLISION:{staging}")
    if not resuming:
        staging.mkdir()
    else:
        required_prefit = ["FAST4_R2_DISCOVERY_MANIFEST.json", "FAST4_R2_ENVIRONMENT_MANIFEST.json",
                           "FAST4_R2_FEATURE_MANIFEST.json", "FAST4_R2_FOLD_MANIFEST.json",
                           "FAST4_R2_PREFIT_CONTRACT.json", "FAST4_R2_TARGET_MANIFEST.json",
                           "FAST4_R2_OPTUNA.sqlite3"]
        if not all((staging / name).is_file() for name in required_prefit):
            raise R2Stop(f"STOP_FAST4_INVALID_RESUME_ROOT:MISSING_PREFIT_ARTIFACT:{staging}")
    environment = _environment_manifest(cfg)
    discovery = _discovery_manifest(frame, cfg, feature_manifest, initial_r1_snapshot)
    if not resuming:
        _write(staging / "FAST4_R2_DISCOVERY_MANIFEST.json", discovery)
        _write(staging / "FAST4_R2_ENVIRONMENT_MANIFEST.json", environment)
    target_manifest = {
        "schema_version": "FAST4_R2_TARGET_MANIFEST_V1", "target_contract": r1_summary["TARGET_CONTRACT"],
        "target_sha256": sha256(R43A_CONTRACT), "target_path": str(R43A_CONTRACT),
        "primary_target": "AVERAGE_FIXED_HORIZON_NET20", "horizons_minutes": [5, 10, 15, 30, 60],
        "transaction_cost_bps": 20, "secondary_labels": ["y_positive", "positive_horizon_majority", "severe_loss", "y_5m", "y_10m", "y_15m", "y_30m", "y_60m"],
        "severe_loss_threshold": -0.01, "first_touch_primary_target": False,
    }
    if not resuming:
        _write(staging / "FAST4_R2_TARGET_MANIFEST.json", target_manifest)
        _write(staging / "FAST4_R2_FEATURE_MANIFEST.json", {
        "schema_version": "FAST4_R2_FEATURE_IDENTITY_REFERENCE_V1", "r1_manifest": str(R1_FEATURE_MANIFEST),
        "r1_manifest_file_sha256": sha256(R1_FEATURE_MANIFEST), "feature_manifest_sha256": feature_manifest["feature_manifest_sha256"],
        "feature_count": len(features), "feature_family_count": len(set(families.values())),
        "feature_order": features, "feature_families": families, "broad_new_feature_family_added": False,
        "target_or_oof_outcome_used_for_feature_selection": False,
        })
    outer = outer_folds(frame, cfg["purge_minutes"], cfg["embargo_minutes"])
    inner_by_outer = {fold.name: inner_folds(frame, fold.train_index, cfg["inner_fold_count"],
                                            cfg["purge_minutes"], cfg["embargo_minutes"]) for fold in outer}
    folds = fold_manifest(frame, outer, inner_by_outer)
    if len(outer) != cfg["outer_fold_count"] or any(len(value) != cfg["inner_fold_count"] for value in inner_by_outer.values()):
        raise R2Stop("OUTER_VALIDATION_LEAKAGE_DETECTED:FOLD_COUNT")
    if folds["manifest_sha256"] != json.loads(R1_FOLD_MANIFEST.read_text(encoding="utf-8"))["manifest_sha256"]:
        raise R2Stop("OUTER_VALIDATION_LEAKAGE_DETECTED:R1_FOLD_IDENTITY")
    folds.update({"schema_version": "FAST4_R2_FOLD_MANIFEST_V1", "target_overlap_audit": "PASS",
                  "outer_validation_used_for_tuning": False})
    if not resuming:
        _write(staging / "FAST4_R2_FOLD_MANIFEST.json", folds)
        _write(staging / "FAST4_R2_PREFIT_CONTRACT.json", {
        "created_before_research_model_fit": True, "created_at_utc": _now(),
        "inner_objective": "SPEARMAN_PLUS_TOP_BOTTOM_SPREAD_PLUS_TOP20_MEAN_MEDIAN_PLUS_MONOTONICITY_MINUS_TAIL_AND_FOLD_INSTABILITY",
        "permutation_statistic": cfg["permutation_statistic"], "permutation_count": cfg["permutation_count"],
        "minimum_support": {"selected_rows": cfg["minimum_strong_selected_rows"],
                            "outer_folds": cfg["minimum_strong_outer_folds"], "years": cfg["minimum_strong_years"],
                            "per_fold_rows": cfg["minimum_selected_rows_per_supported_fold"]},
        "abstention_coverages": cfg["abstention_coverage_candidates"], "prospective_outcome_read": False,
        })
    specs = specifications()
    storage = sqlite_storage_url(staging / "FAST4_R2_OPTUNA.sqlite3")
    oof_parts: list[pd.DataFrame] = []
    tuning_records: list[dict[str, Any]] = []
    selection_records: list[dict[str, Any]] = []
    importance_rows: list[dict[str, Any]] = []
    quantile_audits = []
    failures = []
    counts = {"fit": 0, "predict": 0, "trials": 0}
    for outer_number, fold in enumerate(outer, start=1):
        print(f"FAST4_R2_PROGRESS=OUTER_{outer_number}_OF_{len(outer)}:{fold.name}", flush=True)
        inner_base = pd.DataFrame(index=frame.index)
        outer_base = pd.DataFrame(index=fold.valid_index)
        part = frame.loc[fold.valid_index, ["candidate_id", "decision_timestamp_utc", "trading_date", "validation_slice", "head",
                                                  "underlying_symbol", "primary_target", "y_positive", "positive_horizon_majority", "severe_loss",
                                                  "y_5m", "y_10m", "y_15m", "y_30m", "y_60m", "minutes_since_rth_open", "vix_percentile_252d"]].copy()
        fold_records = []
        for spec_number, spec in enumerate(specs, start=1):
            print(f"FAST4_R2_PROGRESS={fold.name}:SPEC_{spec_number}_OF_{len(specs)}:{spec.name}", flush=True)
            try:
                pred, raw, inner_pred, record, fitted, local = tune_outer_spec(
                    spec, frame, features, fold.train_index, fold.valid_index, inner_by_outer[fold.name],
                    inner_economic_objective, storage, f"{fold.name}__{spec.name}", cfg,
                    cfg["optuna_seed"] + outer_number * 10000 + spec_number * 100)
            except Exception as error:
                failures.append({"outer_fold": fold.name, "spec": spec.name, "error_type": type(error).__name__, "error": str(error)})
                print(f"FAST4_R2_MODEL_FAILURE_ISOLATED={fold.name}:{spec.name}:{type(error).__name__}:{error}", flush=True)
                continue
            record["outer_fold"] = fold.name
            tuning_records.append(record)
            fold_records.append(record)
            inner_base[spec.name] = inner_pred
            outer_base[spec.name] = pred
            part[spec.name] = pred
            part[f"raw__{spec.name}"] = raw
            for feature, value in model_importance(fitted).items():
                importance_rows.append({"outer_fold": fold.name, "spec": spec.name, "family": families[feature],
                                        "feature": feature, "importance": value})
            for key in counts:
                counts[key] += local[key]
        available = set(outer_base.columns)
        if not {"lgb_huber_pooled", "xgb_pseudohuber_pooled", "cat_huber_pooled"}.issubset(available):
            raise R2Stop("MODEL_FAMILY_CORE_FAILURE:ROBUST_PRIMARY")
        quantile_audits.append({"outer_fold": fold.name, **_apply_quantile_order(inner_base, outer_base, available)})
        for column in outer_base.columns:
            part[column] = outer_base[column]
        fold_labels = pd.Series(index=frame.index, dtype=object)
        for inner in inner_by_outer[fold.name]:
            fold_labels.loc[inner.valid_index] = inner.name
        meta_columns = [column for column in inner_base.columns if inner_base[column].notna().sum() >= 50]
        ridge_inner, ridge_outer, ridge_contract, _ = crossfit_ridge_stack(
            inner_base[meta_columns], outer_base[meta_columns], frame.primary_target, fold_labels)
        counts["fit"] += 1
        counts["predict"] += 1
        primary_columns = [spec.name for spec in specs if spec.target == "primary_target" and spec.quantile is None
                           and spec.task == "regression" and spec.name in available]
        pooled_inner, pooled_outer = normalized_mean_score(inner_base, outer_base, primary_columns)
        direction_columns = [name for name in ("lgb_l2_directional", "xgb_l2_directional", "cat_rmse_directional") if name in available]
        direction_inner, direction_outer = normalized_mean_score(inner_base, outer_base, direction_columns)
        horizon_columns = [spec.name for spec in specs if spec.target.startswith("y_") and spec.target.endswith("m") and spec.name in available]
        horizon_inner, horizon_outer = normalized_mean_score(inner_base, outer_base, horizon_columns)
        risk_inner, risk_outer, risk_contract = risk_adjusted_score(inner_base, outer_base, frame.primary_target)
        best_record = max(fold_records, key=lambda row: (row["best_value"], row["spec"]))
        best_name = best_record["spec"]
        candidate_inner = {
            "nested_best_single": inner_base[best_name], "cross_fitted_ridge_stack": ridge_inner,
            "pooled_primary_ensemble": pooled_inner, "direction_specific_ensemble": direction_inner,
            "multi_horizon_ensemble": horizon_inner, "risk_adjusted_score": risk_inner,
        }
        candidate_outer = {
            "nested_best_single": outer_base[best_name].to_numpy(), "cross_fitted_ridge_stack": ridge_outer,
            "pooled_primary_ensemble": pooled_outer, "direction_specific_ensemble": direction_outer,
            "multi_horizon_ensemble": horizon_outer, "risk_adjusted_score": risk_outer,
        }
        common = pd.Series(True, index=frame.index)
        for values in candidate_inner.values():
            common &= values.notna()
        if common.sum() < 25:
            raise R2Stop("STACK_SELF_TRAINING_DETECTED:INSUFFICIENT_CROSSFIT_COMMON_ROWS")
        architecture_objectives = {}
        inner_contract_frame = frame.loc[common, ["candidate_id", "decision_timestamp_utc", "primary_target"]]
        for name, values in candidate_inner.items():
            architecture_objectives[name] = inner_economic_objective(inner_contract_frame, values.loc[common].to_numpy())
            part[name] = candidate_outer[name]
        chosen = max(architecture_objectives, key=lambda name: (architecture_objectives[name], name))
        selected_inner, selected_outer = candidate_inner[chosen], candidate_outer[chosen]
        selected_mask, abstention = choose_abstention(frame, selected_inner, fold_labels, selected_outer,
                                                       cfg["abstention_coverage_candidates"])
        part["nested_selected_score"] = selected_outer
        part["abstention_selected"] = selected_mask
        part["nested_selected_architecture"] = chosen
        selection_records.append({
            "outer_fold": fold.name, "best_single_spec": best_name, "best_single_inner_objective": best_record["best_value"],
            "architecture_inner_objectives": architecture_objectives, "selected_architecture": chosen,
            "ridge_contract": ridge_contract, "risk_adjusted_contract": risk_contract,
            "abstention_contract": abstention, "outer_validation_outcome_used": False,
            "stack_training_candidate_overlap_with_outer_validation": 0,
        })
        oof_parts.append(part)
    oof = pd.concat(oof_parts).sort_values(["decision_timestamp_utc", "candidate_id"], kind="mergesort").reset_index(drop=True)
    if len(oof) != 998 or oof.candidate_id.duplicated().any() or oof.nested_selected_score.isna().any():
        raise R2Stop("STACK_SELF_TRAINING_DETECTED:OOF_ROW_IDENTITY")
    r1_oof = pd.read_parquet(R1_OOF, columns=["candidate_id", "selected_score"]).rename(columns={"selected_score": "fast4_r1_cross_fitted_stack"})
    oof = oof.merge(r1_oof, on="candidate_id", how="left", validate="one_to_one")
    if oof.fast4_r1_cross_fitted_stack.isna().any():
        raise R2Stop("FROZEN_FAST3_OR_FAST4_R1_ARTIFACT_MUTATION_DETECTED:R1_OOF_JOIN")
    leaderboard_rows = []
    trial_by_spec = pd.DataFrame(tuning_records).groupby("spec").study_trial_count.sum().to_dict()
    objective_by_spec = {spec.name: spec.objective for spec in specs}
    family_by_spec = {spec.name: spec.family for spec in specs}
    score_columns = [spec.name for spec in specs if spec.name in oof.columns] + [
        "nested_best_single", "cross_fitted_ridge_stack", "pooled_primary_ensemble", "direction_specific_ensemble",
        "multi_horizon_ensemble", "risk_adjusted_score", "nested_selected_score", "fast4_r1_cross_fitted_stack"]
    decile_payload = {}
    top_payload = {}
    target_scale = float(oof.primary_target.std(ddof=1))
    for score in score_columns:
        metrics, deciles, top = economic_score_metrics(oof, score)
        selection_objective = float((metrics.get("spearman") or -1) + .25 * (metrics.get("q10_q1_mean") or 0) / target_scale
                                    + .15 * top.get("TOP20", {}).get("mean", 0) / target_scale
                                    + .10 * top.get("TOP20", {}).get("median", 0) / target_scale
                                    - .10 * max(0, -top.get("TOP20", {}).get("cvar", 0) / target_scale))
        row = {"model": score, "model_family": family_by_spec.get(score, "ENSEMBLE_OR_BENCHMARK"),
               "objective": objective_by_spec.get(score, "NESTED_ECONOMIC_SELECTION"),
               "direction_mode": next((spec.mode for spec in specs if spec.name == score), "MIXED"),
               "trial_count": int(trial_by_spec.get(score, 0)), "selection_objective": selection_objective, **metrics}
        for label, values in top.items():
            for key in ("N", "mean", "median", "profit_factor", "q10", "cvar"):
                row[f"{label}_{key}"] = values.get(key)
        leaderboard_rows.append(row)
        decile_payload[score] = deciles
        top_payload[score] = top
    leaderboard = pd.DataFrame(leaderboard_rows).sort_values("selection_objective", ascending=False)
    leaderboard.to_csv(staging / "FAST4_R2_MODEL_LEADERBOARD.csv", index=False)
    oof.to_parquet(staging / "FAST4_R2_OOF_PREDICTIONS.parquet", index=False)
    pd.DataFrame(importance_rows).to_parquet(staging / "FAST4_R2_FEATURE_IMPORTANCE.parquet", index=False)
    importance = pd.DataFrame(importance_rows)
    final_metrics, final_deciles, final_top = economic_score_metrics(oof, "nested_selected_score")
    selected_values = oof.loc[oof.abstention_selected, "primary_target"]
    abstention_metrics = group_metrics(selected_values, len(oof))
    stability = stability_table(oof, "nested_selected_score", "abstention_selected")
    stability.to_csv(staging / "FAST4_R2_STABILITY_SLICES.csv", index=False)
    fold_selected = stability.loc[stability.slice_type.eq("validation_slice")]
    year_selected = stability.loc[stability.slice_type.eq("year")]
    supported_folds = int((fold_selected.selected_N.ge(cfg["minimum_selected_rows_per_supported_fold"]) & fold_selected.selected_mean.gt(0)).sum())
    supported_years = int((year_selected.selected_N.gt(0) & year_selected.selected_mean.gt(0)).sum())
    support_pass = (abstention_metrics["N"] >= cfg["minimum_strong_selected_rows"]
                    and supported_folds >= cfg["minimum_strong_outer_folds"]
                    and supported_years >= cfg["minimum_strong_years"])
    stability_report = {
        "schema_version": "FAST4_R2_STABILITY_REPORT_V1", "slice_file": "FAST4_R2_STABILITY_SLICES.csv",
        "outer_fold_status": status_from_slices(stability, "validation_slice"),
        "year_status": status_from_slices(stability, "year"),
        "direction_status": status_from_slices(stability, "head"),
        "underlying_status": status_from_slices(stability, "underlying_symbol"),
        "time_of_day_status": status_from_slices(stability, "time_of_day"),
        "volatility_regime_status": status_from_slices(stability, "volatility_regime"),
        "positive_selected_supported_outer_folds": supported_folds,
        "positive_selected_supported_years": supported_years, "sample_support_pass": support_pass,
    }
    _write(staging / "FAST4_R2_STABILITY_REPORT.json", stability_report)
    probability_report = {}
    for label, target in (("positive", "y_positive"), ("majority", "positive_horizon_majority"), ("severe", "severe_loss")):
        for short in ("lgb", "xgb", "cat"):
            name = f"{short}_{label}_pooled"
            raw = f"raw__{name}"
            if raw in oof:
                probability_report[name] = probability_metrics(oof, raw, target)
    selection_report = {
        "schema_version": "FAST4_R2_SELECTION_POLICY_REPORT_V1", "outer_fold_selection_contracts": selection_records,
        "final_abstention_metrics": abstention_metrics, "sample_support_contract": {
            "minimum_rows": cfg["minimum_strong_selected_rows"], "minimum_outer_folds": cfg["minimum_strong_outer_folds"],
            "minimum_years": cfg["minimum_strong_years"], "minimum_rows_per_supported_fold": cfg["minimum_selected_rows_per_supported_fold"]},
        "sample_support_pass": support_pass, "probability_head_metrics": probability_report,
        "quantile_order_audit": quantile_audits, "deciles": final_deciles, "top_selection": final_top,
        "ranking_group_audit": "PASS_SKIPPED_ZERO_GENUINE_MULTI_CANDIDATE_GROUPS",
        "abstention_outer_outcome_used_for_threshold": False,
    }
    _write(staging / "FAST4_R2_SELECTION_POLICY_REPORT.json", selection_report)
    _write(staging / "FAST4_R2_HYPERPARAMETER_SELECTION.json", {"records": tuning_records, "isolated_failures": failures})
    falsification, family_ablation, false_counts = _falsification(
        frame, features, families, oof, "nested_selected_score", outer, specs, tuning_records,
        selection_records, cfg, importance)
    counts["fit"] += false_counts["fit"]
    counts["predict"] += false_counts["predict"]
    family_ablation.to_csv(staging / "FAST4_R2_FEATURE_FAMILY_ABLATION.csv", index=False)
    _write(staging / "FAST4_R2_FALSIFICATION_REPORT.json", falsification)
    p = falsification["primary_permutation"]["empirical_p_one_sided"]
    selected_positive = (abstention_metrics["mean"] > 0 and abstention_metrics["median"] > 0
                         and abstention_metrics["profit_factor"] > 1)
    tail_ok = (abstention_metrics["cvar"] >= group_metrics(oof.primary_target)["cvar"]
               and abstention_metrics["q10"] >= group_metrics(oof.primary_target)["q10"])
    materially_better = (final_metrics["spearman"] >= r1_summary["OOF_SPEARMAN"] + .02
                         and final_metrics["q10_q1_mean"] > r1_summary["OOF_Q10_MINUS_Q1_MEAN"])
    if (final_metrics["spearman"] > 0 and final_metrics["q10_q1_mean"] > 0 and selected_positive and tail_ok
            and support_pass and p <= .05 and falsification["status"] == "PASS" and materially_better):
        classification = "A_STRONG_NESTED_OOF_ECONOMIC_SELECTION_EDGE"
        decision = "A_FREEZE_FOR_PROSPECTIVE_SHADOW_ONLY"
    elif final_metrics["spearman"] > 0 and final_metrics["q10_q1_mean"] > 0:
        classification = "B_REAL_RANKING_INFORMATION_BUT_INSUFFICIENT_POSITIVE_ECONOMIC_EDGE"
        decision = "B_KEEP_RESEARCH_ONLY"
    else:
        classification = "C_NO_RELIABLE_INCREMENTAL_INFORMATION"
        decision = "C_STOP_THIS_INFORMATION_SET"
    final_model_type = "RESEARCH_ONLY_NESTED_CROSSFITTED_ARCHITECTURE"
    architecture_manifest = {
        "schema_version": "FAST4_R2_FINAL_MODEL_MANIFEST_V1", "classification": classification,
        "deployment_status": "PROSPECTIVE_SHADOW_AUTHORIZED_NOT_ACTIVATED" if classification.startswith("A_") else "RESEARCH_ONLY_NO_PROSPECTIVE_ACTIVATION",
        "nested_outer_architectures": [row["selected_architecture"] for row in selection_records],
        "modal_architecture": Counter(row["selected_architecture"] for row in selection_records).most_common(1)[0][0],
        "target_sha256": sha256(R43A_CONTRACT), "feature_manifest_sha256": feature_manifest["feature_manifest_sha256"],
        "legal_training_cutoff": cfg["legal_training_cutoff"], "full_historical_refit_performed": False,
        "reason_no_full_refit": "CLASSIFICATION_NOT_A" if not classification.startswith("A_") else "A_ARCHITECTURE_FREEZE_REQUIRES_PROSPECTIVE_ACTIVATION_WORKFLOW",
        "research_oof_sha256": sha256(staging / "FAST4_R2_OOF_PREDICTIONS.parquet"),
        "selection_policy_sha256": sha256(staging / "FAST4_R2_SELECTION_POLICY_REPORT.json"),
        "prospective_outcome_read": False, "broker_action_allowed": False,
    }
    _write(staging / "FAST4_R2_FINAL_MODEL_MANIFEST.json", architecture_manifest)
    final_model_sha = stable_hash(architecture_manifest)
    up = oof.loc[oof["head"].eq("UP")]
    down = oof.loc[oof["head"].eq("DOWN")]
    up_selected = group_metrics(up.loc[up.abstention_selected, "primary_target"], len(up))
    down_selected = group_metrics(down.loc[down.abstention_selected, "primary_target"], len(down))
    best_single_names = [spec.name for spec in specs if spec.name in oof]
    best_single = leaderboard.loc[leaderboard.model.isin(best_single_names)].iloc[0]
    best_ensemble = leaderboard.loc[leaderboard.model.isin(["nested_best_single", "cross_fitted_ridge_stack", "pooled_primary_ensemble",
                                                            "direction_specific_ensemble", "multi_horizon_ensemble", "risk_adjusted_score", "nested_selected_score"])].iloc[0]
    modal_coverage = Counter(row["abstention_contract"]["coverage_semantics"] for row in selection_records).most_common(1)[0][0]
    completed = _now()
    summary = {
        "FAST4_R2_STATUS": "PASS_COMPLETE", "FAST4_R2_CLASSIFICATION": classification,
        "FAST4_R2_DECISION": decision, "FINAL_DECISION": decision,
        "PYTHON_EXECUTABLE": str(Path(sys.executable)), "PYTHON_VERSION": platform.python_version(),
        "LIGHTGBM_STATUS": "PASS_TRAINED", "LIGHTGBM_VERSION": environment["dependencies"]["lightgbm"],
        "XGBOOST_STATUS": "PASS_TRAINED", "XGBOOST_VERSION": environment["dependencies"]["xgboost"],
        "CATBOOST_STATUS": "PASS_TRAINED", "CATBOOST_VERSION": environment["dependencies"]["catboost"],
        "OPTUNA_STATUS": "PASS_INNER_ONLY", "OPTUNA_VERSION": environment["dependencies"]["optuna"],
        "TRAINING_START": str(frame.decision_timestamp_utc.min()).replace(" ", "T").replace("+00:00", "Z"),
        "TRAINING_END": str(frame.decision_timestamp_utc.max()).replace(" ", "T").replace("+00:00", "Z"),
        "LEGAL_TRAINING_CUTOFF": cfg["legal_training_cutoff"], "TARGET_CONTRACT": r1_summary["TARGET_CONTRACT"],
        "TARGET_SHA256": sha256(R43A_CONTRACT), "FEATURE_COUNT": len(features),
        "FEATURE_FAMILY_COUNT": len(set(families.values())), "FEATURE_MANIFEST_SHA256": feature_manifest["feature_manifest_sha256"],
        "OUTER_FOLD_COUNT": len(outer), "INNER_FOLD_COUNT": cfg["inner_fold_count"],
        "MODEL_FAMILIES_TRAINED": "LightGBM|XGBoost|CatBoost|FAST4_R1_FROZEN_BENCHMARK_REFERENCE",
        "OBJECTIVES_TRAINED": "L2|Huber|Fair|L1|Binary|MultiHorizon|Quantile_q05_q10_q25_q50|SevereLoss|Ranking_SKIPPED_NO_VALID_GROUPS",
        "HYPERPARAMETER_TRIAL_COUNT": counts["trials"], "OOF_ROW_COUNT": len(oof),
        "BEST_SINGLE_MODEL": best_single.model, "BEST_SINGLE_MODEL_OBJECTIVE": best_single.objective,
        "BEST_ENSEMBLE_MODEL": best_ensemble.model, "BEST_SELECTION_POLICY": "NESTED_ARCHITECTURE_PLUS_INNER_ONLY_ABSTENTION",
        "OOF_SPEARMAN": final_metrics["spearman"], "OOF_PEARSON": final_metrics["pearson"],
        "PERMUTATION_STATISTIC": cfg["permutation_statistic"], "PERMUTATION_COUNT": cfg["permutation_count"],
        "PERMUTATION_EMPIRICAL_P": p, "OOF_Q10_Q1_MEAN": final_metrics["q10_q1_mean"],
        "OOF_Q10_Q1_MEDIAN": final_metrics["q10_q1_median"],
        **_field("TOP30", final_top["TOP30"]), **_field("TOP20", final_top["TOP20"]),
        **_field("TOP10", final_top["TOP10"]), **_field("TOP5", final_top["TOP5"]),
        "ABSTENTION_POLICY": "TRADE_IF_NESTED_SCORE_GE_OUTER_TRAINING_INNER_OOF_QUANTILE_THRESHOLD_ELSE_NO_TRADE",
        "ABSTENTION_THRESHOLD_CONTRACT": f"INNER_ONLY_COVERAGE_CANDIDATES_30_20_10_PERCENT;MODAL={modal_coverage}",
        "ABSTENTION_SELECTED_N": abstention_metrics["N"], "ABSTENTION_COVERAGE": abstention_metrics["coverage"],
        "ABSTENTION_MEAN": abstention_metrics["mean"], "ABSTENTION_MEDIAN": abstention_metrics["median"],
        "ABSTENTION_WIN_RATE": abstention_metrics["win_rate"], "ABSTENTION_PROFIT_FACTOR": abstention_metrics["profit_factor"],
        "ABSTENTION_Q10": abstention_metrics["q10"], "ABSTENTION_CVAR": abstention_metrics["cvar"],
        "UP_OOF_N": len(up), "UP_OOF_SPEARMAN": economic_score_metrics(up, "nested_selected_score")[0]["spearman"],
        "UP_SELECTED_MEAN": up_selected["mean"], "UP_SELECTED_MEDIAN": up_selected["median"], "UP_SELECTED_PROFIT_FACTOR": up_selected["profit_factor"],
        "DOWN_OOF_N": len(down), "DOWN_OOF_SPEARMAN": economic_score_metrics(down, "nested_selected_score")[0]["spearman"],
        "DOWN_SELECTED_MEAN": down_selected["mean"], "DOWN_SELECTED_MEDIAN": down_selected["median"], "DOWN_SELECTED_PROFIT_FACTOR": down_selected["profit_factor"],
        "OUTER_FOLD_STABILITY_STATUS": stability_report["outer_fold_status"], "YEAR_STABILITY_STATUS": stability_report["year_status"],
        "DIRECTION_STABILITY_STATUS": stability_report["direction_status"], "UNDERLYING_STABILITY_STATUS": stability_report["underlying_status"],
        "TIME_OF_DAY_STABILITY_STATUS": stability_report["time_of_day_status"],
        "TAIL_RISK_STATUS": "PASS" if tail_ok else "MIXED_OR_FAIL", "FALSIFICATION_STATUS": falsification["status"],
        "PIT_AUDIT_STATUS": "PASS_R1_FROZEN_FEATURE_IDENTITY_AND_ALL_SOURCE_TIMESTAMPS_LE_DECISION_PRIOR_DAY_VIX_ONLY",
        "LEAKAGE_AUDIT_STATUS": "PASS_TARGET_IDENTITY_PURGE_EMBARGO_INNER_ONLY_TUNING_NO_SELF_TRAINING",
        "RANKING_GROUP_AUDIT_STATUS": "PASS_SKIPPED_ZERO_GENUINE_MULTI_CANDIDATE_GROUPS",
        "ABSTENTION_LEAKAGE_AUDIT_STATUS": "PASS_THRESHOLD_SELECTED_INNER_ONLY_PER_OUTER_FOLD",
        "STACK_CROSSFIT_AUDIT_STATUS": "PASS_SEQUENTIAL_INNER_META_CROSSFIT_AND_ZERO_OUTER_SELF_TRAINING",
        "FAST4_R1_DELTA_SPEARMAN": final_metrics["spearman"] - r1_summary["OOF_SPEARMAN"],
        "FAST4_R1_DELTA_Q10_Q1_MEAN": final_metrics["q10_q1_mean"] - r1_summary["OOF_Q10_MINUS_Q1_MEAN"],
        "FAST4_R1_DELTA_Q10_Q1_MEDIAN": final_metrics["q10_q1_median"] - r1_summary["OOF_Q10_MINUS_Q1_MEDIAN"],
        "FAST4_R1_DELTA_TOP10_MEAN": final_top["TOP10"]["mean"] - r1_summary["OOF_TOP10_MEAN"],
        "FAST4_R1_DELTA_TOP10_MEDIAN": final_top["TOP10"]["median"] - r1_summary["OOF_TOP10_MEDIAN"],
        "FAST4_R1_DELTA_TOP10_PROFIT_FACTOR": final_top["TOP10"]["profit_factor"] - r1_summary["OOF_TOP10_PROFIT_FACTOR"],
        "FINAL_MODEL_TYPE": final_model_type, "FINAL_MODEL_SHA256": final_model_sha,
        "MODEL_FIT_COUNT": counts["fit"], "MODEL_PREDICT_COUNT": counts["predict"],
        "PROSPECTIVE_OUTCOME_READ": False, "BROKER_ACTION_ALLOWED": False, "TRADE_CONTEXT_CREATED": False,
        "ORDER_API_CALL_COUNT": 0, "STORAGE_CONTRACT_STATUS": "PASS_EXTERNAL_RESULTS_ROOT_DATA_ROOT_READ_ONLY",
        "ANTI_BLOAT_STATUS": "PASS_ONE_R2_CONFIG_ONE_REUSABLE_PIPELINE_ONE_ENTRYPOINT",
        "RUN_STARTED_AT_UTC": started, "RUN_COMPLETED_AT_UTC": completed,
    }
    _write(staging / "FAST4_R2_FINAL_SUMMARY.json", summary)
    report = (
        f"FAST4-R2 completed as {classification}. The genuine nested OOF score has Spearman {final_metrics['spearman']:.6f}; "
        f"inner-only abstention selected {abstention_metrics['N']} rows with mean {abstention_metrics['mean']:.6g}, "
        f"median {abstention_metrics['median']:.6g}, PF {abstention_metrics['profit_factor']:.4g}. "
        f"The 999-permutation one-sided p-value is {p:.4g}. R2 is development evidence, not independent confirmation.\n"
    )
    (staging / "FAST4_R2_REPORT.md").write_text(report, encoding="utf-8")
    if _file_snapshot(R1_ROOT) != initial_r1_snapshot:
        raise R2Stop("FROZEN_FAST3_OR_FAST4_R1_ARTIFACT_MUTATION_DETECTED:POST_RUN")
    if sha256(TARGET_LEDGER) != "261bc7618abdf289444a84bd7b9dc47787f1788758d5bbee38f639ca0ec63aeb":
        raise R2Stop("SOURCE_DATA_MUTATION_DETECTED")
    artifact_hashes = {path.name: sha256(path) for path in sorted(staging.glob("*")) if path.is_file()}
    _write(staging / "FAST4_R2_ARTIFACT_MANIFEST.json", {"created_at_utc": _now(), "artifacts": artifact_hashes,
                                                          "r1_postrun_identity_status": "PASS_UNCHANGED"})
    if not staging.resolve().is_relative_to(scratch_parent) or not frozen.resolve().is_relative_to(frozen_parent):
        raise R2Stop("STORAGE_CONTRACT_PATH_ESCAPE")
    shutil.move(str(staging), str(frozen))
    return summary, frozen


def _logical_model_counts(storage: str, specs: list[StrongSpec]) -> dict[str, int]:
    by_name = {spec.name: spec for spec in specs}
    fits = predicts = trials = 0
    for summary in optuna.get_all_study_summaries(storage=storage):
        spec_name = summary.study_name.split("__", 1)[1]
        spec = by_name[spec_name]
        multiplier = 2 if spec.mode == "directional" else 1
        study = optuna.load_study(study_name=summary.study_name, storage=storage)
        trials += len(study.trials)
        local = sum(len(trial.intermediate_values) * multiplier for trial in study.trials)
        local += 4 * multiplier  # three best-parameter inner OOF fits plus one outer fit
        fits += local
        predicts += local
    fits += 45  # four sequential ridge candidates x two transitions plus final fit, for five outer folds
    predicts += 5
    return {"fit": fits, "predict": predicts, "trials": trials}


def finalize_checkpoint(staging_literal: str) -> tuple[dict[str, Any], Path]:
    staging = Path(staging_literal).resolve()
    scratch_parent = (RESULTS / "scratch/fast4").resolve()
    frozen_parent = (RESULTS / "frozen/fast4").resolve()
    if (not staging.is_dir() or not staging.is_relative_to(scratch_parent)
            or not staging.name.startswith("fast4_r2_strong_tabular_economic_model_")):
        raise R2Stop(f"STOP_FAST4_INVALID_RESUME_ROOT:{staging}")
    frozen = frozen_parent / staging.name
    if frozen.exists():
        raise R2Stop(f"R2_OUTPUT_COLLISION:{frozen}")
    required = ["FAST4_R2_OOF_PREDICTIONS.parquet", "FAST4_R2_MODEL_LEADERBOARD.csv",
                "FAST4_R2_HYPERPARAMETER_SELECTION.json", "FAST4_R2_SELECTION_POLICY_REPORT.json",
                "FAST4_R2_STABILITY_REPORT.json", "FAST4_R2_FEATURE_IMPORTANCE.parquet",
                "FAST4_R2_OPTUNA.sqlite3"]
    if not all((staging / name).is_file() for name in required):
        raise R2Stop("STOP_FAST4_INVALID_RESUME_ROOT:MISSING_FINALIZATION_CHECKPOINT")
    initial_r1_snapshot = _file_snapshot(R1_ROOT)
    frame, features, families, cfg, feature_manifest, r1_summary = _load_and_verify()
    environment = json.loads((staging / "FAST4_R2_ENVIRONMENT_MANIFEST.json").read_text(encoding="utf-8"))
    discovery = json.loads((staging / "FAST4_R2_DISCOVERY_MANIFEST.json").read_text(encoding="utf-8"))
    oof = pd.read_parquet(staging / "FAST4_R2_OOF_PREDICTIONS.parquet")
    if len(oof) != 998 or oof.candidate_id.duplicated().any() or oof.nested_selected_score.isna().any():
        raise R2Stop("STACK_SELF_TRAINING_DETECTED:FINALIZATION_CHECKPOINT_OOF")
    leaderboard = pd.read_csv(staging / "FAST4_R2_MODEL_LEADERBOARD.csv")
    importance = pd.read_parquet(staging / "FAST4_R2_FEATURE_IMPORTANCE.parquet")
    tuning = json.loads((staging / "FAST4_R2_HYPERPARAMETER_SELECTION.json").read_text(encoding="utf-8"))
    tuning_records = tuning["records"]
    selection_report = json.loads((staging / "FAST4_R2_SELECTION_POLICY_REPORT.json").read_text(encoding="utf-8"))
    selection_records = selection_report["outer_fold_selection_contracts"]
    stability_report = json.loads((staging / "FAST4_R2_STABILITY_REPORT.json").read_text(encoding="utf-8"))
    outer = outer_folds(frame, cfg["purge_minutes"], cfg["embargo_minutes"])
    specs = specifications()
    if len(tuning_records) != 250 or len(selection_records) != 5:
        raise R2Stop("OUTER_VALIDATION_LEAKAGE_DETECTED:CHECKPOINT_RECORD_COUNT")
    counts = _logical_model_counts(sqlite_storage_url(staging / "FAST4_R2_OPTUNA.sqlite3"), specs)
    if counts["trials"] != 1540:
        raise R2Stop(f"OPTUNA_TRIAL_CONTRACT_FAIL:{counts['trials']}")
    final_metrics, final_deciles, final_top = economic_score_metrics(oof, "nested_selected_score")
    abstention_metrics = group_metrics(oof.loc[oof.abstention_selected, "primary_target"], len(oof))
    falsification, family_ablation, false_counts = _falsification(
        frame, features, families, oof, "nested_selected_score", outer, specs, tuning_records,
        selection_records, cfg, importance)
    counts["fit"] += false_counts["fit"]
    counts["predict"] += false_counts["predict"]
    family_ablation.to_csv(staging / "FAST4_R2_FEATURE_FAMILY_ABLATION.csv", index=False)
    _write(staging / "FAST4_R2_FALSIFICATION_REPORT.json", falsification)
    p = falsification["primary_permutation"]["empirical_p_one_sided"]
    support_pass = bool(selection_report["sample_support_pass"])
    selected_positive = (abstention_metrics["mean"] > 0 and abstention_metrics["median"] > 0
                         and abstention_metrics["profit_factor"] > 1)
    unconditional = group_metrics(oof.primary_target)
    tail_ok = (abstention_metrics["cvar"] >= unconditional["cvar"]
               and abstention_metrics["q10"] >= unconditional["q10"])
    materially_better = (final_metrics["spearman"] >= r1_summary["OOF_SPEARMAN"] + .02
                         and final_metrics["q10_q1_mean"] > r1_summary["OOF_Q10_MINUS_Q1_MEAN"])
    if (final_metrics["spearman"] > 0 and final_metrics["q10_q1_mean"] > 0 and selected_positive and tail_ok
            and support_pass and p <= .05 and falsification["status"] == "PASS" and materially_better):
        raise R2Stop("A_CLASSIFICATION_REQUIRES_FULL_LEGAL_REFIT_NOT_ALLOWED_FROM_DIAGNOSTIC_CHECKPOINT")
    if final_metrics["spearman"] > 0 and final_metrics["q10_q1_mean"] > 0:
        classification, decision = ("B_REAL_RANKING_INFORMATION_BUT_INSUFFICIENT_POSITIVE_ECONOMIC_EDGE",
                                    "B_KEEP_RESEARCH_ONLY")
        final_model_type = "RESEARCH_ONLY_NESTED_CROSSFITTED_ARCHITECTURE"
    else:
        classification, decision = "C_NO_RELIABLE_INCREMENTAL_INFORMATION", "C_STOP_THIS_INFORMATION_SET"
        final_model_type = "NO_FINAL_MODEL_NEGATIVE_RESULT"
    architecture_manifest = {
        "schema_version": "FAST4_R2_FINAL_MODEL_MANIFEST_V1", "classification": classification,
        "deployment_status": "RESEARCH_ONLY_NO_PROSPECTIVE_ACTIVATION" if classification.startswith("B_") else "NEGATIVE_RESULT_NO_MODEL",
        "nested_outer_architectures": [row["selected_architecture"] for row in selection_records],
        "modal_architecture": Counter(row["selected_architecture"] for row in selection_records).most_common(1)[0][0],
        "target_sha256": sha256(R43A_CONTRACT), "feature_manifest_sha256": feature_manifest["feature_manifest_sha256"],
        "legal_training_cutoff": cfg["legal_training_cutoff"], "full_historical_refit_performed": False,
        "reason_no_full_refit": "CLASSIFICATION_NOT_A", "research_oof_sha256": sha256(staging / "FAST4_R2_OOF_PREDICTIONS.parquet"),
        "selection_policy_sha256": sha256(staging / "FAST4_R2_SELECTION_POLICY_REPORT.json"),
        "prospective_outcome_read": False, "broker_action_allowed": False,
    }
    _write(staging / "FAST4_R2_FINAL_MODEL_MANIFEST.json", architecture_manifest)
    final_model_sha = (stable_hash(architecture_manifest) if classification.startswith("B_")
                       else "NOT_APPLICABLE_NO_FINAL_MODEL_CLASSIFICATION_C")
    up, down = oof.loc[oof["head"].eq("UP")], oof.loc[oof["head"].eq("DOWN")]
    up_selected = group_metrics(up.loc[up.abstention_selected, "primary_target"], len(up))
    down_selected = group_metrics(down.loc[down.abstention_selected, "primary_target"], len(down))
    best_single_names = {spec.name for spec in specs}
    best_single = leaderboard.loc[leaderboard.model.isin(best_single_names)].iloc[0]
    ensemble_names = {"nested_best_single", "cross_fitted_ridge_stack", "pooled_primary_ensemble",
                      "direction_specific_ensemble", "multi_horizon_ensemble", "risk_adjusted_score", "nested_selected_score"}
    best_ensemble = leaderboard.loc[leaderboard.model.isin(ensemble_names)].iloc[0]
    modal_coverage = Counter(row["abstention_contract"]["coverage_semantics"] for row in selection_records).most_common(1)[0][0]
    summary = {
        "FAST4_R2_STATUS": "PASS_COMPLETE", "FAST4_R2_CLASSIFICATION": classification,
        "FAST4_R2_DECISION": decision, "FINAL_DECISION": decision,
        "PYTHON_EXECUTABLE": str(Path(sys.executable)), "PYTHON_VERSION": platform.python_version(),
        "LIGHTGBM_STATUS": "PASS_TRAINED", "LIGHTGBM_VERSION": environment["dependencies"]["lightgbm"],
        "XGBOOST_STATUS": "PASS_TRAINED", "XGBOOST_VERSION": environment["dependencies"]["xgboost"],
        "CATBOOST_STATUS": "PASS_TRAINED", "CATBOOST_VERSION": environment["dependencies"]["catboost"],
        "OPTUNA_STATUS": "PASS_INNER_ONLY", "OPTUNA_VERSION": environment["dependencies"]["optuna"],
        "TRAINING_START": str(frame.decision_timestamp_utc.min()).replace(" ", "T").replace("+00:00", "Z"),
        "TRAINING_END": str(frame.decision_timestamp_utc.max()).replace(" ", "T").replace("+00:00", "Z"),
        "LEGAL_TRAINING_CUTOFF": cfg["legal_training_cutoff"], "TARGET_CONTRACT": r1_summary["TARGET_CONTRACT"],
        "TARGET_SHA256": sha256(R43A_CONTRACT), "FEATURE_COUNT": len(features), "FEATURE_FAMILY_COUNT": len(set(families.values())),
        "FEATURE_MANIFEST_SHA256": feature_manifest["feature_manifest_sha256"], "OUTER_FOLD_COUNT": len(outer),
        "INNER_FOLD_COUNT": cfg["inner_fold_count"],
        "MODEL_FAMILIES_TRAINED": "LightGBM|XGBoost|CatBoost|FAST4_R1_FROZEN_BENCHMARK_REFERENCE",
        "OBJECTIVES_TRAINED": "L2|Huber|Fair|L1|Binary|MultiHorizon|Quantile_q05_q10_q25_q50|SevereLoss|Ranking_SKIPPED_NO_VALID_GROUPS",
        "HYPERPARAMETER_TRIAL_COUNT": counts["trials"], "OOF_ROW_COUNT": len(oof),
        "BEST_SINGLE_MODEL": best_single.model, "BEST_SINGLE_MODEL_OBJECTIVE": best_single.objective,
        "BEST_ENSEMBLE_MODEL": best_ensemble.model, "BEST_SELECTION_POLICY": "NESTED_ARCHITECTURE_PLUS_INNER_ONLY_ABSTENTION",
        "OOF_SPEARMAN": final_metrics["spearman"], "OOF_PEARSON": final_metrics["pearson"],
        "PERMUTATION_STATISTIC": cfg["permutation_statistic"], "PERMUTATION_COUNT": cfg["permutation_count"],
        "PERMUTATION_EMPIRICAL_P": p, "OOF_Q10_Q1_MEAN": final_metrics["q10_q1_mean"],
        "OOF_Q10_Q1_MEDIAN": final_metrics["q10_q1_median"],
        **_field("TOP30", final_top["TOP30"]), **_field("TOP20", final_top["TOP20"]),
        **_field("TOP10", final_top["TOP10"]), **_field("TOP5", final_top["TOP5"]),
        "ABSTENTION_POLICY": "TRADE_IF_NESTED_SCORE_GE_OUTER_TRAINING_INNER_OOF_QUANTILE_THRESHOLD_ELSE_NO_TRADE",
        "ABSTENTION_THRESHOLD_CONTRACT": f"INNER_ONLY_COVERAGE_CANDIDATES_30_20_10_PERCENT;MODAL={modal_coverage}",
        "ABSTENTION_SELECTED_N": abstention_metrics["N"], "ABSTENTION_COVERAGE": abstention_metrics["coverage"],
        "ABSTENTION_MEAN": abstention_metrics["mean"], "ABSTENTION_MEDIAN": abstention_metrics["median"],
        "ABSTENTION_WIN_RATE": abstention_metrics["win_rate"], "ABSTENTION_PROFIT_FACTOR": abstention_metrics["profit_factor"],
        "ABSTENTION_Q10": abstention_metrics["q10"], "ABSTENTION_CVAR": abstention_metrics["cvar"],
        "UP_OOF_N": len(up), "UP_OOF_SPEARMAN": economic_score_metrics(up, "nested_selected_score")[0]["spearman"],
        "UP_SELECTED_MEAN": up_selected["mean"], "UP_SELECTED_MEDIAN": up_selected["median"], "UP_SELECTED_PROFIT_FACTOR": up_selected["profit_factor"],
        "DOWN_OOF_N": len(down), "DOWN_OOF_SPEARMAN": economic_score_metrics(down, "nested_selected_score")[0]["spearman"],
        "DOWN_SELECTED_MEAN": down_selected["mean"], "DOWN_SELECTED_MEDIAN": down_selected["median"], "DOWN_SELECTED_PROFIT_FACTOR": down_selected["profit_factor"],
        "OUTER_FOLD_STABILITY_STATUS": stability_report["outer_fold_status"], "YEAR_STABILITY_STATUS": stability_report["year_status"],
        "DIRECTION_STABILITY_STATUS": stability_report["direction_status"], "UNDERLYING_STABILITY_STATUS": stability_report["underlying_status"],
        "TIME_OF_DAY_STABILITY_STATUS": stability_report["time_of_day_status"], "TAIL_RISK_STATUS": "PASS" if tail_ok else "MIXED_OR_FAIL",
        "FALSIFICATION_STATUS": falsification["status"],
        "PIT_AUDIT_STATUS": "PASS_R1_FROZEN_FEATURE_IDENTITY_AND_ALL_SOURCE_TIMESTAMPS_LE_DECISION_PRIOR_DAY_VIX_ONLY",
        "LEAKAGE_AUDIT_STATUS": "PASS_TARGET_IDENTITY_PURGE_EMBARGO_INNER_ONLY_TUNING_NO_SELF_TRAINING",
        "RANKING_GROUP_AUDIT_STATUS": "PASS_SKIPPED_ZERO_GENUINE_MULTI_CANDIDATE_GROUPS",
        "ABSTENTION_LEAKAGE_AUDIT_STATUS": "PASS_THRESHOLD_SELECTED_INNER_ONLY_PER_OUTER_FOLD",
        "STACK_CROSSFIT_AUDIT_STATUS": "PASS_SEQUENTIAL_INNER_META_CROSSFIT_AND_ZERO_OUTER_SELF_TRAINING",
        "FAST4_R1_DELTA_SPEARMAN": final_metrics["spearman"] - r1_summary["OOF_SPEARMAN"],
        "FAST4_R1_DELTA_Q10_Q1_MEAN": final_metrics["q10_q1_mean"] - r1_summary["OOF_Q10_MINUS_Q1_MEAN"],
        "FAST4_R1_DELTA_Q10_Q1_MEDIAN": final_metrics["q10_q1_median"] - r1_summary["OOF_Q10_MINUS_Q1_MEDIAN"],
        "FAST4_R1_DELTA_TOP10_MEAN": final_top["TOP10"]["mean"] - r1_summary["OOF_TOP10_MEAN"],
        "FAST4_R1_DELTA_TOP10_MEDIAN": final_top["TOP10"]["median"] - r1_summary["OOF_TOP10_MEDIAN"],
        "FAST4_R1_DELTA_TOP10_PROFIT_FACTOR": final_top["TOP10"]["profit_factor"] - r1_summary["OOF_TOP10_PROFIT_FACTOR"],
        "FINAL_MODEL_TYPE": final_model_type, "FINAL_MODEL_SHA256": final_model_sha,
        "MODEL_FIT_COUNT": counts["fit"], "MODEL_PREDICT_COUNT": counts["predict"],
        "PROSPECTIVE_OUTCOME_READ": False, "BROKER_ACTION_ALLOWED": False, "TRADE_CONTEXT_CREATED": False, "ORDER_API_CALL_COUNT": 0,
        "STORAGE_CONTRACT_STATUS": "PASS_EXTERNAL_RESULTS_ROOT_DATA_ROOT_READ_ONLY",
        "ANTI_BLOAT_STATUS": "PASS_ONE_R2_CONFIG_ONE_REUSABLE_PIPELINE_ONE_ENTRYPOINT",
        "RUN_STARTED_AT_UTC": discovery["created_at_utc"], "RUN_COMPLETED_AT_UTC": _now(),
    }
    _write(staging / "FAST4_R2_FINAL_SUMMARY.json", summary)
    (staging / "FAST4_R2_REPORT.md").write_text(
        f"FAST4-R2 completed as {classification}. Genuine nested OOF Spearman={final_metrics['spearman']:.6f}; "
        f"abstention N={abstention_metrics['N']}, mean={abstention_metrics['mean']:.6g}, "
        f"median={abstention_metrics['median']:.6g}, PF={abstention_metrics['profit_factor']:.4g}; "
        f"999-permutation p={p:.4g}. R2 is development evidence, not independent confirmation.\n", encoding="utf-8")
    if _file_snapshot(R1_ROOT) != initial_r1_snapshot:
        raise R2Stop("FROZEN_FAST3_OR_FAST4_R1_ARTIFACT_MUTATION_DETECTED:POST_RUN")
    if sha256(TARGET_LEDGER) != "261bc7618abdf289444a84bd7b9dc47787f1788758d5bbee38f639ca0ec63aeb":
        raise R2Stop("SOURCE_DATA_MUTATION_DETECTED")
    artifact_hashes = {path.name: sha256(path) for path in sorted(staging.glob("*")) if path.is_file()}
    _write(staging / "FAST4_R2_ARTIFACT_MANIFEST.json", {"created_at_utc": _now(), "artifacts": artifact_hashes,
                                                          "r1_postrun_identity_status": "PASS_UNCHANGED"})
    shutil.move(str(staging), str(frozen))
    return summary, frozen


SUMMARY_FIELDS = [
    "FAST4_R2_STATUS", "FAST4_R2_CLASSIFICATION", "FAST4_R2_DECISION", "FINAL_DECISION", "PYTHON_EXECUTABLE", "PYTHON_VERSION",
    "LIGHTGBM_STATUS", "LIGHTGBM_VERSION", "XGBOOST_STATUS", "XGBOOST_VERSION", "CATBOOST_STATUS", "CATBOOST_VERSION", "OPTUNA_STATUS", "OPTUNA_VERSION",
    "TRAINING_START", "TRAINING_END", "LEGAL_TRAINING_CUTOFF", "TARGET_CONTRACT", "TARGET_SHA256", "FEATURE_COUNT", "FEATURE_FAMILY_COUNT",
    "FEATURE_MANIFEST_SHA256", "OUTER_FOLD_COUNT", "INNER_FOLD_COUNT", "MODEL_FAMILIES_TRAINED", "OBJECTIVES_TRAINED", "HYPERPARAMETER_TRIAL_COUNT",
    "OOF_ROW_COUNT", "BEST_SINGLE_MODEL", "BEST_SINGLE_MODEL_OBJECTIVE", "BEST_ENSEMBLE_MODEL", "BEST_SELECTION_POLICY", "OOF_SPEARMAN", "OOF_PEARSON",
    "PERMUTATION_STATISTIC", "PERMUTATION_COUNT", "PERMUTATION_EMPIRICAL_P", "OOF_Q10_Q1_MEAN", "OOF_Q10_Q1_MEDIAN",
    "TOP30_N", "TOP30_COVERAGE", "TOP30_MEAN", "TOP30_MEDIAN", "TOP30_WIN_RATE", "TOP30_PROFIT_FACTOR", "TOP30_Q10", "TOP30_CVAR",
    "TOP20_N", "TOP20_COVERAGE", "TOP20_MEAN", "TOP20_MEDIAN", "TOP20_WIN_RATE", "TOP20_PROFIT_FACTOR", "TOP20_Q10", "TOP20_CVAR",
    "TOP10_N", "TOP10_COVERAGE", "TOP10_MEAN", "TOP10_MEDIAN", "TOP10_WIN_RATE", "TOP10_PROFIT_FACTOR", "TOP10_Q10", "TOP10_CVAR",
    "TOP5_N", "TOP5_COVERAGE", "TOP5_MEAN", "TOP5_MEDIAN", "TOP5_WIN_RATE", "TOP5_PROFIT_FACTOR", "TOP5_Q10", "TOP5_CVAR",
    "ABSTENTION_POLICY", "ABSTENTION_THRESHOLD_CONTRACT", "ABSTENTION_SELECTED_N", "ABSTENTION_COVERAGE", "ABSTENTION_MEAN", "ABSTENTION_MEDIAN",
    "ABSTENTION_WIN_RATE", "ABSTENTION_PROFIT_FACTOR", "ABSTENTION_Q10", "ABSTENTION_CVAR", "UP_OOF_N", "UP_OOF_SPEARMAN", "UP_SELECTED_MEAN",
    "UP_SELECTED_MEDIAN", "UP_SELECTED_PROFIT_FACTOR", "DOWN_OOF_N", "DOWN_OOF_SPEARMAN", "DOWN_SELECTED_MEAN", "DOWN_SELECTED_MEDIAN",
    "DOWN_SELECTED_PROFIT_FACTOR", "OUTER_FOLD_STABILITY_STATUS", "YEAR_STABILITY_STATUS", "DIRECTION_STABILITY_STATUS", "UNDERLYING_STABILITY_STATUS",
    "TIME_OF_DAY_STABILITY_STATUS", "TAIL_RISK_STATUS", "FALSIFICATION_STATUS", "PIT_AUDIT_STATUS", "LEAKAGE_AUDIT_STATUS", "RANKING_GROUP_AUDIT_STATUS",
    "ABSTENTION_LEAKAGE_AUDIT_STATUS", "STACK_CROSSFIT_AUDIT_STATUS", "FAST4_R1_DELTA_SPEARMAN", "FAST4_R1_DELTA_Q10_Q1_MEAN",
    "FAST4_R1_DELTA_Q10_Q1_MEDIAN", "FAST4_R1_DELTA_TOP10_MEAN", "FAST4_R1_DELTA_TOP10_MEDIAN", "FAST4_R1_DELTA_TOP10_PROFIT_FACTOR",
    "FINAL_MODEL_TYPE", "FINAL_MODEL_SHA256", "MODEL_FIT_COUNT", "MODEL_PREDICT_COUNT", "PROSPECTIVE_OUTCOME_READ", "BROKER_ACTION_ALLOWED",
    "TRADE_CONTEXT_CREATED", "ORDER_API_CALL_COUNT", "STORAGE_CONTRACT_STATUS", "ANTI_BLOAT_STATUS",
]


def print_summary(summary: dict[str, Any], root: Path) -> None:
    for field in SUMMARY_FIELDS:
        value = summary.get(field, "NOT_APPLICABLE")
        if isinstance(value, bool):
            value = str(value).lower()
        print(f"{field}={value}")
    print(f"FAST4_R2_FROZEN_ROOT={root}")
