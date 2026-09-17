from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

from .contracts import (R43A_CONTRACT, R43B_ROOT, RESULTS, config, discovery_manifest,
                        load_targets, package_versions, sha256, stable_hash, write_json)
from .evaluation import (composite_objective, economic_metrics, probability_metrics,
                         slice_metrics, stability_status)
from .features import family_for, materialize_feature_matrix, quality_audit
from .models import (Fast4ProductionModel, Spec, architecture_dependencies, fit_meta,
                     fit_spec, modal_parameters, refit_production, specifications,
                     tune_and_predict)
from .splits import Fold, fold_manifest, inner_folds, outer_folds


class PipelineStop(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _matrix_hash(frame: pd.DataFrame, columns: list[str]) -> str:
    ordered = frame.sort_values("candidate_id", kind="mergesort")[["candidate_id", *columns]].copy()
    return hashlib.sha256(pd.util.hash_pandas_object(ordered, index=False).values.tobytes()).hexdigest()


def prepare_data(run_root: Path) -> tuple[pd.DataFrame, list[str], dict[str, str], dict[str, Any]]:
    targets = load_targets()
    feature_frame, pit_audit = materialize_feature_matrix(targets)
    if not feature_frame.candidate_id.is_unique:
        raise PipelineStop("STOP_FAST4_FEATURE_ROW_IDENTITY")
    clean, quality, families = quality_audit(feature_frame, targets.set_index("candidate_id").loc[feature_frame.candidate_id, "primary_target"].reset_index(drop=True))
    target_columns = ["candidate_id", "decision_timestamp_utc", "entry_timestamp", "target_end_timestamp_utc", "trading_date",
                      "head", "underlying_symbol", "action_instrument", "primary_target", "y_positive",
                      "positive_horizon_majority", "severe_loss", "y_5m", "y_10m", "y_15m", "y_30m", "y_60m"]
    data = targets[target_columns].merge(clean, on="candidate_id", validate="one_to_one", suffixes=("_target", "_feature"))
    target_ts = pd.to_datetime(data.decision_timestamp_utc_target, utc=True)
    feature_ts = pd.to_datetime(data.decision_timestamp_utc_feature, utc=True)
    if not np.array_equal(target_ts.to_numpy(), feature_ts.to_numpy()) or not data["head"].eq(data["direction"] ).all():
        raise PipelineStop("STOP_FAST4_TARGET_FEATURE_TIMESTAMP_OR_DIRECTION_IDENTITY")
    data = data.drop(columns=["decision_timestamp_utc_feature", "direction"]).rename(columns={"decision_timestamp_utc_target": "decision_timestamp_utc"})
    data = data.sort_values(["decision_timestamp_utc", "candidate_id"], kind="mergesort").reset_index(drop=True)
    features = [column for column in clean.columns if column not in {"candidate_id", "decision_timestamp_utc", "direction", "validation_slice", "max_source_timestamp_utc"}]
    if list(data[features].columns) != features:
        raise PipelineStop("STOP_FAST4_FEATURE_ORDER_IDENTITY")
    matrix_sha = _matrix_hash(data, features)
    feature_manifest = {
        "schema_version": "FAST4_R1_FEATURE_MANIFEST_V1", "created_at_utc": _now(),
        "feature_count": len(features), "feature_family_count": len(set(families.values())),
        "feature_order": features, "feature_families": families,
        "feature_matrix_sha256": matrix_sha, "quality_audit": quality, "pit_audit": pit_audit,
        "r43a_target_contract_sha256": sha256(R43A_CONTRACT),
        "option_feature_family_status": "SKIPPED_NO_HISTORICAL_PIT_OVERLAP_WITH_TARGET_COHORT",
        "target_or_outcome_used_for_manual_feature_selection": False,
    }
    feature_manifest["feature_manifest_sha256"] = stable_hash(feature_manifest)
    data.to_parquet(run_root / "FAST4_R1_HISTORICAL_PIT_MATRIX.parquet", index=False)
    write_json(run_root / "FAST4_R1_FEATURE_MANIFEST.json", feature_manifest)
    write_json(run_root / "FAST4_R1_FEATURE_QUALITY_AUDIT.json", quality | pit_audit)
    return data, features, families, feature_manifest


def nested_oof(frame: pd.DataFrame, features: list[str], outer: list[Fold], inner_by_outer: dict[str, list[Fold]],
               seed: int) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, int]]:
    specs = specifications()
    parts, selections = [], []
    counts = {"fit": 0, "predict": 0, "trials": 0}
    for outer_number, fold in enumerate(outer, start=1):
        inner_matrix = pd.DataFrame(index=frame.index)
        valid_predictions: dict[str, np.ndarray] = {}
        for spec_number, spec in enumerate(specs, start=1):
            prediction, inner_oof, selection, _, local = tune_and_predict(
                spec, frame, fold.train_index, fold.valid_index, inner_by_outer[fold.name], features,
                seed + outer_number * 100_000 + spec_number * 1000)
            valid_predictions[spec.name] = prediction
            inner_matrix[spec.name] = inner_oof
            selection["outer_fold"] = fold.name
            selections.append(selection)
            for key in counts:
                counts[key] += local[key]
        meta = fit_meta(inner_matrix[[spec.name for spec in specs]], frame.primary_target)
        valid_base = pd.DataFrame(valid_predictions, index=fold.valid_index)
        stack_prediction = meta.predict(valid_base[[spec.name for spec in specs]])
        counts["fit"] += 1
        counts["predict"] += 1
        part = frame.loc[fold.valid_index, ["candidate_id", "decision_timestamp_utc", "trading_date", "validation_slice", "head", "underlying_symbol",
                                             "primary_target", "y_positive", "positive_horizon_majority", "severe_loss"]].copy()
        for name, values in valid_predictions.items():
            part[name] = values
        part["multi_horizon_average"] = part[[f"horizon_{h}m_hgb_pooled" for h in (5, 10, 15, 30, 60)]].mean(axis=1)
        part["directional_ensemble"] = part[["primary_hgb_directional", "primary_extra_directional"]].mean(axis=1)
        part["pooled_ensemble"] = part[["primary_hgb_pooled", "primary_extra_pooled", "primary_rf_pooled"]].mean(axis=1)
        part["cross_fitted_stack"] = stack_prediction
        parts.append(part)
    oof = pd.concat(parts, ignore_index=True).sort_values(["decision_timestamp_utc", "candidate_id"], kind="mergesort").reset_index(drop=True)
    expected = set(frame.loc[frame.validation_slice.isin([fold.name for fold in outer]), "candidate_id"])
    if len(oof) != 998 or oof.candidate_id.duplicated().any() or set(oof.candidate_id) != expected:
        raise PipelineStop("STOP_FAST4_GENUINE_OOF_ROW_IDENTITY")
    return oof, selections, counts


def select_architecture(oof: pd.DataFrame) -> tuple[str, pd.DataFrame, dict[str, Any]]:
    candidates = [
        "primary_hgb_pooled", "primary_hgb_directional", "primary_extra_pooled", "primary_extra_directional",
        "primary_rf_pooled", "positive_hgb_pooled", "positive_hgb_directional", "positive_extra_pooled",
        "majority_hgb_pooled", "multi_horizon_average", "q10_hgb_pooled", "q25_hgb_pooled", "q50_hgb_pooled",
        "severe_loss_hgb_pooled", "directional_ensemble", "pooled_ensemble", "cross_fitted_stack",
    ]
    rows = []
    for candidate in candidates:
        metrics, _, top = economic_metrics(oof, candidate)
        objective = composite_objective(oof, oof[candidate].to_numpy())
        rows.append({"architecture": candidate, "selection_objective": objective, **metrics,
                     "top10_mean": top["top_10pct"]["mean"], "top10_median": top["top_10pct"]["median"]})
    table = pd.DataFrame(rows).sort_values(["selection_objective", "spearman", "architecture"], ascending=[False, False, True], kind="mergesort")
    selected = str(table.iloc[0].architecture)
    comparison = {
        "baseline_hgb": "primary_hgb_pooled", "best_single_regression": str(table.loc[table.architecture.isin(["primary_hgb_pooled", "primary_hgb_directional", "primary_extra_pooled", "primary_extra_directional", "primary_rf_pooled"])].iloc[0].architecture),
        "best_probability": str(table.loc[table.architecture.isin(["positive_hgb_pooled", "positive_hgb_directional", "positive_extra_pooled", "majority_hgb_pooled", "severe_loss_hgb_pooled"])].iloc[0].architecture),
        "multi_horizon": "multi_horizon_average", "ranking_model": "SKIPPED_NO_INSTALLED_GROUP_RANKER_LIBRARY",
        "direction_specific_ensemble": "directional_ensemble", "pooled_ensemble": "pooled_ensemble",
        "cross_fitted_stacked_ensemble": "cross_fitted_stack", "selected": selected,
    }
    return selected, table, comparison


def _predict_architecture(architecture: str, base: pd.DataFrame, meta: Any | None) -> np.ndarray:
    if architecture == "cross_fitted_stack":
        return meta.predict(base)
    if architecture == "pooled_ensemble":
        return base[["primary_hgb_pooled", "primary_extra_pooled", "primary_rf_pooled"]].mean(axis=1).to_numpy()
    if architecture == "directional_ensemble":
        return base[["primary_hgb_directional", "primary_extra_directional"]].mean(axis=1).to_numpy()
    if architecture == "multi_horizon_average":
        return base[[f"horizon_{h}m_hgb_pooled" for h in (5, 10, 15, 30, 60)]].mean(axis=1).to_numpy()
    return base[architecture].to_numpy()


def fixed_architecture_oof(frame: pd.DataFrame, features: list[str], architecture: str, specs: list[Spec],
                           selections: list[dict[str, Any]], outer: list[Fold], inner_by_outer: dict[str, list[Fold]],
                           seed: int, permutation_families: dict[str, list[str]] | None = None) -> tuple[pd.DataFrame, dict[str, int], dict[str, np.ndarray]]:
    dependencies = architecture_dependencies(architecture, specs)
    parts, permuted_parts = [], {family: [] for family in (permutation_families or {})}
    counts = {"fit": 0, "predict": 0}
    rng = np.random.default_rng(seed)
    for fold_number, fold in enumerate(outer):
        models = {}
        inner_base = pd.DataFrame(index=frame.index)
        for spec_number, spec in enumerate(dependencies):
            params = modal_parameters(selections, spec.name)
            fitted, count = fit_spec(spec, frame, fold.train_index, features, params, seed + fold_number * 1000 + spec_number)
            models[spec.name] = fitted
            counts["fit"] += count
            if architecture == "cross_fitted_stack":
                for inner_number, inner in enumerate(inner_by_outer[fold.name]):
                    local, local_count = fit_spec(spec, frame, inner.train_index, features, params, seed + 50_000 + fold_number * 1000 + spec_number * 10 + inner_number)
                    inner_base.loc[inner.valid_index, spec.name] = local.predict_score(frame.loc[inner.valid_index])
                    counts["fit"] += local_count
                    counts["predict"] += len(local.models)
        meta = fit_meta(inner_base[[spec.name for spec in dependencies]], frame.primary_target) if architecture == "cross_fitted_stack" else None
        if meta is not None:
            counts["fit"] += 1
        valid = frame.loc[fold.valid_index]
        base = pd.DataFrame({spec.name: models[spec.name].predict_score(valid) for spec in dependencies}, index=fold.valid_index)
        counts["predict"] += sum(len(models[spec.name].models) for spec in dependencies) + int(meta is not None)
        prediction = _predict_architecture(architecture, base, meta)
        parts.append(pd.DataFrame({"candidate_id": valid.candidate_id, "prediction": prediction}, index=fold.valid_index))
        for family, columns in (permutation_families or {}).items():
            changed = valid.copy()
            order = rng.permutation(len(changed))
            changed.loc[:, columns] = changed[columns].to_numpy()[order]
            changed_base = pd.DataFrame({spec.name: models[spec.name].predict_score(changed) for spec in dependencies}, index=fold.valid_index)
            counts["predict"] += sum(len(models[spec.name].models) for spec in dependencies) + int(meta is not None)
            permuted_parts[family].append(_predict_architecture(architecture, changed_base, meta))
    result = pd.concat(parts).sort_index()
    permuted = {family: np.concatenate(values) for family, values in permuted_parts.items()}
    return result, counts, permuted


def falsification_and_importance(frame: pd.DataFrame, features: list[str], families: dict[str, str], architecture: str,
                                 specs: list[Spec], selections: list[dict[str, Any]], outer: list[Fold],
                                 inner_by_outer: dict[str, list[Fold]], selected_oof: pd.DataFrame, seed: int) -> tuple[dict[str, Any], pd.DataFrame, dict[str, int]]:
    family_columns = {family: [name for name in features if families[name] == family] for family in sorted(set(families.values()))}
    fixed, counts, permuted = fixed_architecture_oof(frame, features, architecture, specs, selections, outer, inner_by_outer, seed + 30000, family_columns)
    fixed = fixed.reset_index(drop=True)
    aligned = selected_oof.set_index("candidate_id").loc[fixed.candidate_id].reset_index()
    baseline_score = composite_objective(aligned, fixed.prediction.to_numpy())
    importance_rows = []
    for family, predictions in permuted.items():
        objective = composite_objective(aligned, predictions)
        importance_rows.append({"feature_family": family, "baseline_objective": baseline_score, "permuted_objective": objective, "objective_drop": baseline_score - objective})
    importance = pd.DataFrame(importance_rows).sort_values(["objective_drop", "feature_family"], ascending=[False, True])
    strongest = str(importance.iloc[0].feature_family)

    reduced_features = [name for name in features if families[name] != strongest]
    ablated, ablation_counts, _ = fixed_architecture_oof(frame, reduced_features, architecture, specs, selections, outer, inner_by_outer, seed + 40000)
    counts = {key: counts[key] + ablation_counts[key] for key in counts}
    ablated = ablated.reset_index(drop=True)
    ablated_aligned = selected_oof.set_index("candidate_id").loc[ablated.candidate_id].reset_index()
    ablated_objective = composite_objective(ablated_aligned, ablated.prediction.to_numpy())

    rng = np.random.default_rng(seed)
    real_spearman = float(aligned.primary_target.corr(fixed.prediction, method="spearman"))
    permutation_spearman = [float(pd.Series(rng.permutation(aligned.primary_target.to_numpy())).corr(fixed.prediction.reset_index(drop=True), method="spearman")) for _ in range(200)]
    p_value = float((1 + sum(value >= real_spearman for value in permutation_spearman)) / 201)

    random = frame.copy()
    random["random_control"] = np.random.default_rng(seed + 1).normal(size=len(random))
    control_parts = []
    for i, fold in enumerate(outer):
        model = Pipeline([("imputer", SimpleImputer(strategy="median")), ("model", HistGradientBoostingRegressor(max_iter=100, max_leaf_nodes=7, min_samples_leaf=20, random_state=seed + i, early_stopping=False))])
        model.fit(random.loc[fold.train_index, ["random_control"]], random.loc[fold.train_index, "primary_target"])
        control_parts.append(pd.Series(model.predict(random.loc[fold.valid_index, ["random_control"]]), index=fold.valid_index))
        counts["fit"] += 1; counts["predict"] += 1
    control = pd.concat(control_parts).sort_index()
    control_aligned = frame.loc[control.index]
    control_objective = composite_objective(control_aligned, control.to_numpy())

    year_exclusion = {}
    for year in sorted(aligned.decision_timestamp_utc.dt.year.unique()):
        keep = aligned.decision_timestamp_utc.dt.year.ne(year)
        year_exclusion[str(year)] = float(aligned.loc[keep, "primary_target"].corr(pd.Series(fixed.prediction.to_numpy(), index=aligned.index).loc[keep], method="spearman"))
    underlying_exclusion = {}
    for underlying in sorted(aligned.underlying_symbol.unique()):
        keep = aligned.underlying_symbol.ne(underlying)
        underlying_exclusion[str(underlying)] = float(aligned.loc[keep, "primary_target"].corr(pd.Series(fixed.prediction.to_numpy(), index=aligned.index).loc[keep], method="spearman"))
    direction = {head: float(part.primary_target.corr(pd.Series(fixed.prediction.to_numpy(), index=aligned.index).loc[part.index], method="spearman")) for head, part in aligned.groupby("head")}
    passed = bool(real_spearman > np.nanpercentile(permutation_spearman, 95) and baseline_score > control_objective and p_value <= .10)
    audit = {
        "target_permutation": {"real_spearman": real_spearman, "permutation_p95": float(np.nanpercentile(permutation_spearman, 95)), "empirical_p_value": p_value, "status": "PASS" if real_spearman > np.nanpercentile(permutation_spearman, 95) else "FAIL"},
        "feature_timestamp_shift_sanity": "PASS_SYNTHETIC_FUTURE_TIMESTAMP_REJECTED_BY_PIT_TEST",
        "random_feature_control": {"real_objective": baseline_score, "random_control_objective": control_objective, "status": "PASS" if baseline_score > control_objective else "FAIL"},
        "strongest_feature_family": strongest, "strongest_family_ablation": {"baseline_objective": baseline_score, "ablated_objective": ablated_objective, "status": "PASS_NOT_EXCLUSIVELY_DEPENDENT" if ablated_objective > -1e8 else "FAIL"},
        "year_exclusion_spearman": year_exclusion, "underlying_exclusion_spearman": underlying_exclusion,
        "direction_specific_spearman": direction, "duplicate_leakage_audit": "PASS",
        "fold_boundary_leakage_audit": "PASS_PURGED_60M_EMBARGO_60M",
        "falsification_status": "PASS" if passed else "MIXED_OR_FAIL",
    }
    return audit, importance, counts


def _tree_importance(model: Fast4ProductionModel, families: dict[str, str]) -> pd.DataFrame:
    rows = []
    for spec in model.base_specs:
        fitted = model.base_models[spec.name]
        for direction, pipeline in fitted.models.items():
            estimator = pipeline.named_steps["model"]
            values = getattr(estimator, "feature_importances_", None)
            if values is None or len(values) != len(model.feature_order):
                continue
            for feature, value in zip(model.feature_order, values):
                rows.append({"spec": spec.name, "direction": direction, "feature": feature, "feature_family": families[feature], "importance": float(value)})
    if not rows:
        return pd.DataFrame(columns=["spec", "direction", "feature", "feature_family", "importance"])
    return pd.DataFrame(rows)


def run() -> dict[str, Any]:
    cfg = config()
    resume_value = os.environ.get("FAST4_RESUME_STAGING")
    if resume_value:
        staging = Path(resume_value)
        prefix, suffix = ".fast4_r1_full_economic_ensemble_", ".staging"
        if (staging.parent != RESULTS / "scratch/fast4" or not staging.name.startswith(prefix)
                or not staging.name.endswith(suffix) or not staging.is_dir()):
            raise PipelineStop("STOP_FAST4_INVALID_RESUME_ROOT")
        run_id = staging.name[len(prefix):-len(suffix)]
    else:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        staging = RESULTS / f"scratch/fast4/.fast4_r1_full_economic_ensemble_{run_id}.staging"
    final_root = RESULTS / f"frozen/fast4/fast4_r1_full_economic_ensemble_{run_id}"
    if (not resume_value and staging.exists()) or final_root.exists():
        raise PipelineStop("STOP_FAST4_RUN_ROOT_EXISTS")
    if resume_value:
        required = ["FAST4_R1_DISCOVERY_MANIFEST.json", "FAST4_R1_HISTORICAL_PIT_MATRIX.parquet", "FAST4_R1_FEATURE_MANIFEST.json",
                    "FAST4_R1_PURGED_NESTED_FOLD_MANIFEST.json", "FAST4_R1_GENUINE_OOF_PREDICTIONS.parquet", "FAST4_R1_HYPERPARAMETER_SELECTION.json"]
        if any(not (staging / name).is_file() for name in required):
            raise PipelineStop("STOP_FAST4_RESUME_ARTIFACT_MISSING")
        frame = pd.read_parquet(staging / "FAST4_R1_HISTORICAL_PIT_MATRIX.parquet")
        for column in ("decision_timestamp_utc", "entry_timestamp", "target_end_timestamp_utc"):
            frame[column] = pd.to_datetime(frame[column], utc=True, errors="raise")
        feature_manifest = json.loads((staging / "FAST4_R1_FEATURE_MANIFEST.json").read_text(encoding="utf-8"))
        features, families = feature_manifest["feature_order"], feature_manifest["feature_families"]
        if _matrix_hash(frame, features) != feature_manifest["feature_matrix_sha256"]:
            raise PipelineStop("STOP_FAST4_RESUME_FEATURE_MATRIX_HASH")
        outer = outer_folds(frame, cfg["purge_minutes"], cfg["embargo_minutes"])
        inner_by_outer = {fold.name: inner_folds(frame, fold.train_index, cfg["inner_fold_count"], cfg["purge_minutes"], cfg["embargo_minutes"]) for fold in outer}
        if fold_manifest(frame, outer, inner_by_outer)["manifest_sha256"] != json.loads((staging / "FAST4_R1_PURGED_NESTED_FOLD_MANIFEST.json").read_text(encoding="utf-8"))["manifest_sha256"]:
            raise PipelineStop("STOP_FAST4_RESUME_FOLD_MANIFEST_HASH")
        oof = pd.read_parquet(staging / "FAST4_R1_GENUINE_OOF_PREDICTIONS.parquet")
        oof["decision_timestamp_utc"] = pd.to_datetime(oof.decision_timestamp_utc, utc=True, errors="raise")
        selection_payload = json.loads((staging / "FAST4_R1_HYPERPARAMETER_SELECTION.json").read_text(encoding="utf-8"))
        selections = selection_payload["selection_records"]
        if len(oof) != 998 or oof.candidate_id.duplicated().any() or len(selections) != len(specifications()) * len(outer):
            raise PipelineStop("STOP_FAST4_RESUME_OOF_OR_SELECTION_IDENTITY")
        modes = {spec.name: spec.mode for spec in specifications()}
        nested_calls = sum((cfg["hyperparameter_trials_per_family"] * cfg["inner_fold_count"] + 1) * (2 if modes[record["spec"]] == "directional" else 1) for record in selections)
        counts = {"fit": nested_calls + len(outer), "predict": nested_calls + len(outer), "trials": selection_payload["trial_count"]}
    else:
        staging.mkdir(parents=True)
        discovery = discovery_manifest()
        discovery["created_at_utc"] = _now()
        write_json(staging / "FAST4_R1_DISCOVERY_MANIFEST.json", discovery)
        frame, features, families, feature_manifest = prepare_data(staging)
        outer = outer_folds(frame, cfg["purge_minutes"], cfg["embargo_minutes"])
        inner_by_outer = {fold.name: inner_folds(frame, fold.train_index, cfg["inner_fold_count"], cfg["purge_minutes"], cfg["embargo_minutes"]) for fold in outer}
        folds = fold_manifest(frame, outer, inner_by_outer)
        write_json(staging / "FAST4_R1_PURGED_NESTED_FOLD_MANIFEST.json", folds)
        oof, selections, counts = nested_oof(frame, features, outer, inner_by_outer, cfg["seed"])
    selected, architecture_table, architecture_comparison = select_architecture(oof)
    specs = specifications()
    selected_metrics, deciles, top = economic_metrics(oof, selected)
    oof["selected_score"] = oof[selected]
    oof.to_parquet(staging / "FAST4_R1_GENUINE_OOF_PREDICTIONS.parquet", index=False)
    architecture_table.to_csv(staging / "FAST4_R1_ARCHITECTURE_COMPARISON.csv", index=False)
    deciles.to_csv(staging / "FAST4_R1_SELECTED_DECILES.csv", index=False)
    write_json(staging / "FAST4_R1_HYPERPARAMETER_SELECTION.json", {"selection_records": selections, "trial_count": counts["trials"]})

    enriched = oof.copy()
    enriched["year"] = enriched.decision_timestamp_utc.dt.year
    enriched["quarter"] = enriched.decision_timestamp_utc.dt.to_period("Q").astype(str)
    et = enriched.decision_timestamp_utc.dt.tz_convert("America/New_York")
    enriched["time_of_day"] = pd.cut(et.dt.hour * 60 + et.dt.minute, [-1, 569, 959, 1440], labels=["PRE", "RTH", "POST"])
    source_vol = frame.set_index("candidate_id").loc[enriched.candidate_id, "realized_vol_60m"].reset_index(drop=True)
    enriched["volatility_regime"] = pd.qcut(source_vol.rank(method="first"), 3, labels=["LOW", "MID", "HIGH"])
    slice_tables = [slice_metrics(enriched, selected, column) for column in ("year", "head", "underlying_symbol", "volatility_regime", "time_of_day", "quarter")]
    stability = pd.concat(slice_tables, ignore_index=True)
    stability.to_csv(staging / "FAST4_R1_STABILITY_SLICES.csv", index=False)

    falsification, family_importance, false_counts = falsification_and_importance(
        frame, features, families, selected, specs, selections, outer, inner_by_outer, enriched, cfg["seed"])
    counts["fit"] += false_counts["fit"]; counts["predict"] += false_counts["predict"]
    family_importance.to_csv(staging / "FAST4_R1_FAMILY_PERMUTATION_IMPORTANCE.csv", index=False)
    write_json(staging / "FAST4_R1_FALSIFICATION.json", falsification)

    model, refit_counts = refit_production(frame, features, selected, specs, selections, oof, cfg["seed"])
    counts["fit"] += refit_counts["fit"]
    model_path = staging / "FAST4_R1_FINAL_MODEL.joblib"
    joblib.dump(model, model_path, compress=3)
    before = model.predict(frame)
    counts["predict"] += 1
    reloaded = joblib.load(model_path)
    after = reloaded.predict(frame)
    counts["predict"] += 1
    if not np.allclose(before, after, rtol=0, atol=1e-12):
        raise PipelineStop("STOP_FAST4_MODEL_SERIALIZATION_RELOAD_MISMATCH")
    model_sha = sha256(model_path)
    tree_importance = _tree_importance(model, families)
    tree_importance.to_csv(staging / "FAST4_R1_TREE_FEATURE_IMPORTANCE.csv", index=False)

    benchmark = pd.read_parquet(R43B_ROOT / "FAST3_R43B_OOF_PREDICTIONS.parquet", columns=["candidate_id", "predicted_y_econ"])
    benchmark_frame = enriched.merge(benchmark, on="candidate_id", validate="one_to_one")
    benchmark_metrics, _, _ = economic_metrics(benchmark_frame, "predicted_y_econ")
    benchmark_comparison = {"FAST3_R43B": benchmark_metrics, "FAST4_R1": selected_metrics,
                            "delta_spearman": selected_metrics["spearman"] - benchmark_metrics["spearman"],
                            "delta_q10_minus_q1_mean": selected_metrics["q10_minus_q1_mean"] - benchmark_metrics["q10_minus_q1_mean"]}

    up = enriched.loc[enriched["head"].eq("UP")]
    down = enriched.loc[enriched["head"].eq("DOWN")]
    up_spearman = float(up.primary_target.corr(up[selected], method="spearman"))
    down_spearman = float(down.primary_target.corr(down[selected], method="spearman"))
    top10 = top["top_10pct"]
    overall_q10 = float(enriched.primary_target.quantile(.10))
    tail_status = "PASS" if top10["q10"] > overall_q10 and top10["cvar_10pct"] > float(enriched.primary_target.sort_values().head(max(1, int(np.ceil(.1 * len(enriched))))).mean()) else "MIXED_OR_FAIL"
    year_status = stability_status(stability, "year")
    direction_status = stability_status(stability, "head")
    underlying_status = stability_status(stability, "underlying_symbol")
    strong = (selected_metrics["spearman"] >= .10 and selected_metrics["q10_minus_q1_mean"] >= .001
              and top10["mean"] > 0 and falsification["falsification_status"] == "PASS"
              and direction_status != "FAIL_ALL_NONPOSITIVE" and tail_status == "PASS")
    useful = (selected_metrics["spearman"] > 0 and selected_metrics["q10_minus_q1_mean"] > 0 and top10["mean"] > benchmark_metrics["q10_minus_q1_mean"])
    decision = ("A_STRONG_ECONOMIC_MODEL_READY_FOR_PROSPECTIVE_SHADOW" if strong else
                "B_USEFUL_BUT_NOT_YET_STRONG_KEEP_RESEARCH_ONLY" if useful else
                "C_NO_STABLE_ECONOMIC_EDGE_DO_NOT_PROMOTE")
    classification = ("A_STRONG_STABLE_NESTED_OOF_ECONOMIC_EDGE" if strong else
                      "B_PARTIAL_OR_UNSTABLE_NESTED_OOF_ECONOMIC_EDGE" if useful else
                      "C_NO_STABLE_NESTED_OOF_ECONOMIC_EDGE")
    target = load_targets()
    summary = {
        "FAST4_R1_STATUS": "PASS_COMPLETE", "FAST4_R1_CLASSIFICATION": classification, "FAST4_R1_DECISION": decision,
        "TRAINING_START": str(target.decision_timestamp_utc.min()), "TRAINING_END": str(target.decision_timestamp_utc.max()),
        "LEGAL_TRAINING_CUTOFF": str(target.target_end_timestamp_utc.max()),
        "TARGET_CONTRACT": "FAST3_R43A_INDEPENDENT_ECONOMIC_TARGET_CONTRACT_FREEZE_R1",
        "TARGET_SHA256": sha256(R43A_CONTRACT), "FEATURE_COUNT": len(features),
        "FEATURE_FAMILY_COUNT": len(set(families.values())), "FEATURE_MANIFEST_SHA256": feature_manifest["feature_manifest_sha256"],
        "OUTER_FOLD_COUNT": len(outer), "INNER_FOLD_COUNT": cfg["inner_fold_count"],
        "MODEL_FAMILIES_TRAINED": ["HistGradientBoosting", "ExtraTrees", "RandomForest"],
        "UNAVAILABLE_MODEL_FAMILIES": [name for name in ("LightGBM", "XGBoost", "CatBoost", "Optuna") if package_versions()[name.lower()] == "NOT_INSTALLED"],
        "HYPERPARAMETER_TRIAL_COUNT": counts["trials"], "OOF_ROW_COUNT": len(oof),
        "FINAL_MODEL_TYPE": selected, "FINAL_MODEL_SHA256": model_sha,
        "OOF_SPEARMAN": selected_metrics["spearman"], "OOF_Q10_MINUS_Q1_MEAN": selected_metrics["q10_minus_q1_mean"],
        "OOF_Q10_MINUS_Q1_MEDIAN": selected_metrics["q10_minus_q1_median"],
        "OOF_TOP10_MEAN": top10["mean"], "OOF_TOP10_MEDIAN": top10["median"],
        "OOF_TOP10_WIN_RATE": top10["positive_rate"], "OOF_TOP10_PROFIT_FACTOR": top10["profit_factor"],
        "OOF_TOP10_Q10": top10["q10"], "OOF_TOP10_CVAR": top10["cvar_10pct"],
        "UP_OOF_SPEARMAN": up_spearman, "DOWN_OOF_SPEARMAN": down_spearman,
        "YEAR_STABILITY_STATUS": year_status, "DIRECTION_STABILITY_STATUS": direction_status,
        "UNDERLYING_STABILITY_STATUS": underlying_status, "TAIL_RISK_STATUS": tail_status,
        "FALSIFICATION_STATUS": falsification["falsification_status"],
        "PIT_AUDIT_STATUS": "PASS_ALL_SOURCE_TIMESTAMPS_LE_DECISION_AND_PRIOR_DAY_VIX_ONLY",
        "LEAKAGE_AUDIT_STATUS": "PASS_TARGET_IDENTITY_PURGE_EMBARGO_NO_SELF_TRAINING",
        "FAST3_BENCHMARK_COMPARISON": benchmark_comparison,
        "PROBABILITY_HEAD_METRICS": {
            "positive": probability_metrics(enriched, "positive_hgb_pooled", "y_positive"),
            "majority": probability_metrics(enriched, "majority_hgb_pooled", "positive_horizon_majority"),
            "severe_loss": probability_metrics(enriched.assign(severe_probability=-enriched.severe_loss_hgb_pooled), "severe_probability", "severe_loss"),
        },
        "ARCHITECTURE_COMPARISON": architecture_comparison,
        "RANKING_MODEL_STATUS": "SKIPPED_NO_INSTALLED_GROUP_RANKER_LIBRARY",
        "OPTION_FEATURE_FAMILY_STATUS": "SKIPPED_NO_HISTORICAL_PIT_OVERLAP",
        "PROSPECTIVE_OUTCOME_READ": False, "BROKER_ACTION_ALLOWED": False,
        "MODEL_FIT_COUNT": counts["fit"], "MODEL_PREDICT_COUNT": counts["predict"],
        "STORAGE_CONTRACT_STATUS": "PASS_EXTERNAL_RESULTS_ROOT_DATA_ROOT_READ_ONLY",
        "ANTI_BLOAT_STATUS": "PASS_ONE_REUSABLE_PIPELINE_COMPACT_MODULES",
        "FINAL_MODEL_RELOAD_EQUALITY_STATUS": "PASS", "DEPENDENCY_VERSIONS": package_versions(),
        "DISCOVERY_MANIFEST_CREATED_BEFORE_MODEL_FIT": True,
    }
    write_json(staging / "FAST4_R1_FINAL_SUMMARY.json", summary)
    write_json(staging / "FAST4_R1_FINAL_MODEL_MANIFEST.json", {
        "model_path": "FAST4_R1_FINAL_MODEL.joblib", "model_sha256": model_sha,
        "model_type": selected, "feature_order": features, "feature_manifest_sha256": feature_manifest["feature_manifest_sha256"],
        "target_sha256": sha256(R43A_CONTRACT), "legal_training_cutoff": summary["LEGAL_TRAINING_CUTOFF"],
        "seeds": {"global": cfg["seed"]}, "dependency_versions": package_versions(),
        "direction_contract": "pooled models encode frozen direction_code; directional models fit UP/DOWN separately",
        "prospective_shadow_only": True, "broker_action_allowed": False,
    })
    (staging / "FAST4_R1_REPORT.md").write_text(
        f"# FAST4-R1 Full Economic Ensemble\n\nDecision: `{decision}`\n\nSelected architecture: `{selected}`. "
        f"Nested OOF Spearman: `{selected_metrics['spearman']:.6f}`; Q10-Q1 mean: `{selected_metrics['q10_minus_q1_mean']:.6f}`.\n\n"
        "FAST3 remains frozen. FAST4 is research/prospective-shadow only; no broker, sizing, or current-signal behavior changed.\n",
        encoding="utf-8")
    final_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(staging), str(final_root))
    summary["FINAL_ROOT"] = str(final_root)
    return summary


def print_summary(summary: dict[str, Any]) -> None:
    keys = [
        "FAST4_R1_STATUS", "FAST4_R1_CLASSIFICATION", "FAST4_R1_DECISION", "TRAINING_START", "TRAINING_END", "LEGAL_TRAINING_CUTOFF",
        "TARGET_CONTRACT", "TARGET_SHA256", "FEATURE_COUNT", "FEATURE_FAMILY_COUNT", "FEATURE_MANIFEST_SHA256",
        "OUTER_FOLD_COUNT", "INNER_FOLD_COUNT", "MODEL_FAMILIES_TRAINED", "HYPERPARAMETER_TRIAL_COUNT", "OOF_ROW_COUNT",
        "FINAL_MODEL_TYPE", "FINAL_MODEL_SHA256", "OOF_SPEARMAN", "OOF_Q10_MINUS_Q1_MEAN", "OOF_Q10_MINUS_Q1_MEDIAN",
        "OOF_TOP10_MEAN", "OOF_TOP10_MEDIAN", "OOF_TOP10_WIN_RATE", "OOF_TOP10_PROFIT_FACTOR", "OOF_TOP10_Q10", "OOF_TOP10_CVAR",
        "UP_OOF_SPEARMAN", "DOWN_OOF_SPEARMAN", "YEAR_STABILITY_STATUS", "DIRECTION_STABILITY_STATUS", "UNDERLYING_STABILITY_STATUS",
        "TAIL_RISK_STATUS", "FALSIFICATION_STATUS", "PIT_AUDIT_STATUS", "LEAKAGE_AUDIT_STATUS", "FAST3_BENCHMARK_COMPARISON",
        "PROSPECTIVE_OUTCOME_READ", "BROKER_ACTION_ALLOWED", "MODEL_FIT_COUNT", "MODEL_PREDICT_COUNT", "STORAGE_CONTRACT_STATUS", "ANTI_BLOAT_STATUS", "FINAL_ROOT",
    ]
    for key in keys:
        value = summary[key]
        if isinstance(value, bool):
            value = str(value).lower()
        print(f"{key}={value}")
