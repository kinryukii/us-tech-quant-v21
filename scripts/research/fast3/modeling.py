"""Bounded pooled stock research: fixed candidates, expanding annual nested CV.

Input features and security eligibility are supplied by the PIT data entrypoint.
This module never downloads data and never examines a 2026 outcome. All weights
give each represented trading day equal total weight, normalized to mean one.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import traceback
import warnings

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
import sklearn


SEED = 104729
CUTOFF = pd.Timestamp("2026-01-01", tz="UTC")
CANDIDATES = (
    {"id": "logit_c01", "family": "logistic", "C": 0.1},
    {"id": "logit_c1", "family": "logistic", "C": 1.0},
    {"id": "hgb_leaf7", "family": "hist_gradient_boosting", "max_leaf_nodes": 7},
    {"id": "hgb_leaf15", "family": "hist_gradient_boosting", "max_leaf_nodes": 15},
)
BASELINES = ("historical_prior", "market_sector_logit")
REQUIRED = {"sample_id", "ticker", "date", "prediction_at_utc", "label_end_utc", "return_3h", "y", "sector"}
FIT_BUDGET = {"candidate_inner": 20, "candidate_outer_selected": 4, "baseline_outer": 8,
              "baseline_final": 2, "selected_final": 1, "baseline_inner": 0, "maximum_total": 35}
CANDIDATE_CONTRACT = {"logit_C": [0.1, 1], "logit_max_iter": 1500, "hgb_max_iter": 150,
    "hgb_learning_rate": 0.05, "hgb_max_leaf_nodes": [7, 15], "hgb_l2_regularization": 10,
    "hgb_min_samples_leaf": 40, "early_stopping": False,
    "imputer": "fold_train_median_with_indicator_keep_empty", "scaler": "fold_train_standard_for_logit",
    "calibration": None, "ensemble": None}
FIXED_CONFIG = {"seed": SEED, "outer_years": [2022, 2023, 2024, 2025],
    "inner_years": [2021, 2022, 2023, 2024, 2025], "train_start": "2020-01-01",
    "min_train_days": 120, "min_validation_days": 60, "primary_metric": "equal_trading_day_log_loss",
    "threshold": 0.5, "reliability_edges": [index / 10 for index in range(11)],
    "bootstrap": {"unit": "trading_day", "method": "moving_block", "block_length": 20, "replications": 1000, "seed": SEED}}


def _validate_config(config):
    expected_specs = [
        {"id": "logit_c01", "family": "logistic", "C": CANDIDATE_CONTRACT["logit_C"][0]},
        {"id": "logit_c1", "family": "logistic", "C": CANDIDATE_CONTRACT["logit_C"][1]},
        {"id": "hgb_leaf7", "family": "hist_gradient_boosting", "max_leaf_nodes": CANDIDATE_CONTRACT["hgb_max_leaf_nodes"][0]},
        {"id": "hgb_leaf15", "family": "hist_gradient_boosting", "max_leaf_nodes": CANDIDATE_CONTRACT["hgb_max_leaf_nodes"][1]},
    ]
    if list(CANDIDATES) != expected_specs:
        raise ValueError("Frozen science configuration mismatch: code candidate specification drift")
    expected = {**FIXED_CONFIG, "candidate_ids": [spec["id"] for spec in CANDIDATES], "candidate_contract": CANDIDATE_CONTRACT}
    for key, value in expected.items():
        if key not in config or config[key] != value:
            raise ValueError(f"Frozen science configuration mismatch: {key}")


def _historical_prior_probability(frame):
    return float(frame.groupby("date").y.mean().mean())


def _maturity(frame):
    return frame["label_available_at_utc"] if "label_available_at_utc" in frame else frame.label_end_utc


def _final_training(frame):
    return frame[frame.date.ge("2020-01-01") & _maturity(frame).lt(CUTOFF)].copy()


def _json(path, payload):
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False, default=str), encoding="utf-8")


def _weights(frame):
    weight = 1.0 / frame.groupby("date")["date"].transform("size").to_numpy(float)
    return weight * len(frame) / weight.sum()


def _features(frame, columns):
    # No learned transform occurs here; infinities are treated as missing.
    return frame.loc[:, columns].apply(pd.to_numeric, errors="raise").replace([np.inf, -np.inf], np.nan)


def _make_model(spec):
    if spec["family"] == "logistic":
        return Pipeline([
            ("imputer", SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)),
            ("scale", StandardScaler()),
            ("model", LogisticRegression(C=spec["C"], max_iter=CANDIDATE_CONTRACT["logit_max_iter"], random_state=SEED)),
        ])
    return HistGradientBoostingClassifier(max_iter=CANDIDATE_CONTRACT["hgb_max_iter"], learning_rate=CANDIDATE_CONTRACT["hgb_learning_rate"],
        max_leaf_nodes=spec["max_leaf_nodes"], l2_regularization=CANDIDATE_CONTRACT["hgb_l2_regularization"],
        min_samples_leaf=CANDIDATE_CONTRACT["hgb_min_samples_leaf"], early_stopping=CANDIDATE_CONTRACT["early_stopping"], random_state=SEED)


def _predict(estimator, frame, columns):
    if isinstance(estimator, dict) and estimator.get("kind") == "historical_prior":
        return np.full(len(frame), estimator["probability_up"], dtype=float)
    classes = np.asarray(estimator.classes_)
    probability = estimator.predict_proba(_features(frame, columns))
    return probability[:, int(np.flatnonzero(classes == 1)[0])] if 1 in classes else np.zeros(len(frame))


def _loss_rows(y, probability):
    probability = np.clip(np.asarray(probability, float), 1e-15, 1 - 1e-15)
    y = np.asarray(y, float)
    return -(y * np.log(probability) + (1 - y) * np.log1p(-probability))


def daily_metrics(frame, probability):
    p = np.asarray(probability, float)
    if len(p) != len(frame) or not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
        raise ValueError("Invalid prediction vector")
    y = frame.y.to_numpy(int)
    rows = pd.DataFrame({"date": frame.date.to_numpy(), "log_loss": _loss_rows(y, p),
                         "accuracy": ((p >= 0.5) == y).astype(float), "brier": (p - y) ** 2})
    daily = rows.groupby("date", sort=True).mean()
    daily["rows"] = rows.groupby("date").size()
    prediction = pd.Series(p, index=frame.index)
    auc, rank = {}, {}
    for date, day in frame.groupby("date", sort=True):
        values = prediction.loc[day.index].to_numpy()
        auc[date] = float(roc_auc_score(day.y, values)) if day.y.nunique() == 2 else np.nan
        rank[date] = float(spearmanr(values, day.return_3h).statistic) if len(day) >= 3 and np.ptp(values) > 0 and day.return_3h.nunique() > 1 else np.nan
    daily["same_day_auc"] = pd.Series(auc)
    daily["same_day_return_spearman"] = pd.Series(rank)
    return daily.reset_index()


def aggregate_metrics(frame, probability, daily=None):
    daily = daily_metrics(frame, probability) if daily is None else daily
    result = {"rows": len(frame), "dates": len(daily), "flat_rows": int(frame.return_3h.eq(0).sum()),
              "up_rows": int(frame.y.sum()), "strict_down_rows": int(frame.return_3h.lt(0).sum())}
    for key in ("log_loss", "accuracy", "brier", "same_day_auc", "same_day_return_spearman"):
        value = daily[key].mean()
        result[key] = float(value) if pd.notna(value) else None
    result["same_day_auc_eligible_dates"] = int(daily.same_day_auc.notna().sum())
    result["same_day_spearman_eligible_dates"] = int(daily.same_day_return_spearman.notna().sum())
    result["auc_day_weighted_pooled"] = float(roc_auc_score(frame.y, probability, sample_weight=_weights(frame))) if frame.y.nunique() == 2 else None
    return result


def _reliability(frame, probability, name):
    p = np.asarray(probability)
    work = pd.DataFrame({"date": frame.date.to_numpy(), "y": frame.y.to_numpy(), "p": p,
                         "weight": _weights(frame), "bin": np.minimum((p * 10).astype(int), 9)})
    result = []
    for index in range(10):
        piece = work[work.bin.eq(index)]
        result.append({"model": name, "bin": index, "lower_inclusive": index / 10,
                       "upper": (index + 1) / 10, "upper_inclusive": index == 9,
                       "rows": len(piece), "dates": piece.date.nunique(),
                       "mean_probability": float(np.average(piece.p, weights=piece.weight)) if len(piece) else None,
                       "observed_up_fraction": float(np.average(piece.y, weights=piece.weight)) if len(piece) else None})
    return result


class FitRecorder:
    def __init__(self, output):
        self.path = Path(output) / "fit_events.jsonl"
        self.records = []

    def event(self, payload):
        payload = {"event_at_utc": datetime.now(timezone.utc).isoformat(), **payload}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str, allow_nan=False) + "\n")

    def fit(self, spec, frame, columns, category, phase, year):
        if len(self.records) >= FIT_BUDGET["maximum_total"]:
            raise RuntimeError("Frozen maximum fit budget exhausted; no extra fitting allowed")
        identity = len(self.records) + 1
        record = {"fit_id": identity, "model_id": spec["id"], "category": category, "phase": phase,
                  "year": year, "rows": len(frame), "dates": frame.date.nunique(),
                  "train_first_date": frame.date.min(), "train_last_date": frame.date.max(),
                  "max_label_end_utc": frame.label_end_utc.max().isoformat(), "features": list(columns)}
        record["max_label_maturity_utc"] = _maturity(frame).max().isoformat()
        self.records.append(record)
        self.event({**record, "event": "STARTED"})
        started = time.monotonic()
        try:
            if spec["id"] == "historical_prior":
                model = {"kind": "historical_prior", "probability_up": _historical_prior_probability(frame)}
            else:
                model = _make_model(spec)
                kwargs = {"model__sample_weight" if isinstance(model, Pipeline) else "sample_weight": _weights(frame)}
                with warnings.catch_warnings(record=True) as captured:
                    warnings.simplefilter("always")
                    model.fit(_features(frame, columns), frame.y.to_numpy(int), **kwargs)
                record["warnings"] = [{"category": item.category.__name__, "message": str(item.message)} for item in captured]
                fitted = model.named_steps["model"] if isinstance(model, Pipeline) else model
                record["iterations"] = np.asarray(getattr(fitted, "n_iter_", [])).tolist()
            record.update(status="SUCCEEDED", elapsed_seconds=time.monotonic() - started)
            self.event({**record, "event": "FINISHED"})
            return model
        except Exception as exc:
            record.update(status="FAILED", elapsed_seconds=time.monotonic() - started,
                          error=f"{type(exc).__name__}: {exc}")
            self.event({**record, "event": "FINISHED", "traceback": traceback.format_exc()})
            raise


def _validated_panel(panel, config):
    missing = REQUIRED - set(panel.columns)
    if missing:
        raise ValueError(f"Missing panel fields: {sorted(missing)}")
    frame = panel.copy()
    frame["date"] = frame.date.astype(str)
    if not frame.date.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all() or frame.date.ge("2026-01-01").any():
        raise ValueError("Panel must contain ISO pre2026 dates only")
    for field in ("prediction_at_utc", "label_end_utc"):
        frame[field] = pd.to_datetime(frame[field], utc=True, errors="raise")
        if frame[field].isna().any() or frame[field].ge(CUTOFF).any():
            raise ValueError(f"Invalid or post-cutoff {field}")
    if "label_available_at_utc" in frame:
        frame["label_available_at_utc"] = pd.to_datetime(frame.label_available_at_utc, utc=True, errors="raise")
        if frame.label_available_at_utc.isna().any() or frame.label_available_at_utc.ge(CUTOFF).any() or frame.label_available_at_utc.lt(frame.label_end_utc).any():
            raise ValueError("Invalid label_available_at_utc maturity")
    if frame.sample_id.duplicated().any() or frame.duplicated(["ticker", "date"]).any():
        raise ValueError("Duplicate sample identity")
    if (frame.label_end_utc <= frame.prediction_at_utc).any() or frame.groupby("date").prediction_at_utc.nunique().gt(1).any():
        raise ValueError("Invalid per-day prediction/maturity ordering")
    for field, expected_time in (("prediction_at_utc", "09:25"), ("label_end_utc", "12:30")):
        local = frame[field].dt.tz_convert("America/New_York")
        if not (local.dt.strftime("%Y-%m-%d").eq(frame.date) & local.dt.strftime("%H:%M").eq(expected_time)).all():
            raise ValueError(f"Fixed task timestamp mismatch: {field}")
    if not np.isfinite(frame.return_3h.to_numpy(float)).all() or not frame.y.isin([0, 1]).all() or not frame.y.eq(frame.return_3h.gt(0).astype(int)).all():
        raise ValueError("Invalid endpoint return or fixed direction label")
    for key in ("feature_columns", "baseline_columns"):
        columns = list(config[key])
        if not columns or len(set(columns)) != len(columns) or any(not column.startswith(("pm_", "lag_", "market_", "pit_")) for column in columns) or set(columns) & (REQUIRED | {"label_available_at_utc", "open_price", "price_12_30", "flat"}):
            raise ValueError(f"Invalid {key}; use explicit numeric PIT features")
        _features(frame.iloc[:0], columns)
    return frame.sort_values(["date", "ticker", "sample_id"]).reset_index(drop=True)


def _fold(frame, year):
    validation = frame[frame.date.between(f"{year}-01-01", f"{year}-12-31")].copy()
    if validation.empty:
        return frame.iloc[:0].copy(), validation, {"year": year, "status": "SKIPPED_INSUFFICIENT_HISTORY", "reason": "NO_VALIDATION_SAMPLES", "train_rows": 0, "train_dates": 0, "validation_rows": 0, "validation_dates": 0}
    first_prediction = validation.prediction_at_utc.min()
    nominal = frame[frame.date.ge("2020-01-01") & frame.date.lt(f"{year}-01-01")]
    training = nominal[_maturity(nominal).lt(first_prediction)].copy()
    detail = {"year": year, "train_rows": len(training), "train_dates": training.date.nunique(),
              "validation_rows": len(validation), "validation_dates": validation.date.nunique(),
              "purged_unmatured_rows": len(nominal) - len(training), "first_prediction_utc": first_prediction.isoformat(),
              "status": "ELIGIBLE" if training.date.nunique() >= 120 and validation.date.nunique() >= 60 else "SKIPPED_INSUFFICIENT_HISTORY"}
    return training, validation, detail


def paired_comparison(daily, model="selected", baselines=BASELINES):
    values = daily.pivot(index="date", columns="model", values="log_loss").sort_index()
    if values[[model, *baselines]].isna().any().any():
        raise ValueError("Baseline comparisons require identical complete dates")
    count = len(values)
    rng = np.random.default_rng(SEED)
    indices = []
    if count >= 20:
        for _ in range(1000):
            starts = rng.integers(0, count - 20 + 1, size=int(np.ceil(count / 20)))
            indices.append(np.concatenate([np.arange(start, start + 20) for start in starts])[:count])
    result = []
    for baseline in baselines:
        delta = (values[model] - values[baseline]).to_numpy(float)
        samples = np.asarray([delta[index].mean() for index in indices])
        lower, upper = np.quantile(samples, [0.025, 0.975]) if len(samples) else (None, None)
        result.append({"baseline": baseline, "paired_dates": count, "mean_daily_log_loss_delta": float(delta.mean()),
                       "ci_95_lower": float(lower) if lower is not None else None,
                       "ci_95_upper": float(upper) if upper is not None else None,
                       "method": "moving_non_circular_20_trading_day_block_bootstrap", "replicates": len(samples), "seed": SEED})
    return result


def predict_model(bundle, panel):
    """Return p(up) and p(not up); never label p(not up) as strict p(down)."""
    if isinstance(bundle, (str, Path)):
        bundle = joblib.load(bundle)
    result = panel.loc[:, [column for column in ("sample_id", "ticker", "date") if column in panel]].copy()
    probability = _predict(bundle["model"], panel, bundle["feature_columns"])
    result["probability_up"] = probability
    result["probability_not_up"] = 1 - probability
    result["predicted_up_at_0_5"] = probability >= 0.5
    result["model_id"] = bundle["selected_candidate"]
    return result


def train_research(panel, config, out):
    """Fit only the frozen workflow; output must be a fresh directory."""
    _validate_config(config)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    frame = _validated_panel(panel, config)
    feature_columns, baseline_columns = list(config["feature_columns"]), list(config["baseline_columns"])
    splits = {year: _fold(frame, year)[2] for year in range(2021, 2026)}
    protocol = {"seed": SEED, "candidates": list(CANDIDATES), "model_families": 2, "candidate_count": 4,
                "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "sklearn_version": sklearn.__version__,
                "scientific_config_sha256": hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest(),
                "outer_years": [2022, 2023, 2024, 2025], "inner_years": "2021 through outer_year-1; final 2021 through 2025",
                "training_start": "2020-01-01", "minimum_train_dates": 120, "minimum_validation_dates": 60,
                "feature_columns": feature_columns, "baseline_columns": baseline_columns,
                "primary_metric": "trading_day_equal_log_loss", "selection": "minimum_all_available_inner_OOF_daily_logloss; ties candidate order; any fit failure invalidates that candidate",
                "threshold": 0.5, "bins": [index / 10 for index in range(11)], "calibration": "NONE", "ensemble": "NONE",
                "sample_weight": "inverse within-day count normalized to mean 1 over training rows",
                "logistic": {"max_iter": 1500, "imputer": "training median, indicator, keep empty", "scaler": "StandardScaler trained in fold"},
                "hgb": {"max_iter": 150, "learning_rate": 0.05, "l2_regularization": 10, "min_samples_leaf": 40, "early_stopping": False, "native_missing": True},
                "baselines": ["training-day-equal historical up fraction", "fixed C=0.1 logit on baseline_columns"],
                "baseline_inner_policy": "FIXED_SPECIFICATIONS_NO_INNER_FITTING_OR_SELECTION", "fit_budget": FIT_BUDGET,
                "failed_candidate_policy": "Keep all fit events and failed inner records; any failed inner year invalidates that fixed candidate; no retry or replacement candidate; successful earlier year cache is reused.",
                "label_maturity": "label_available_at_utc when supplied, otherwise label_end_utc; strictly before first validation prediction and final UTC cutoff",
                "bootstrap": {"block_dates": 20, "replicates": 1000, "seed": SEED, "ci": [0.025, 0.975]},
                "adoptability": "both baseline delta CI upper bounds <0, at least 3 outer years and 250 OOS dates; research only otherwise",
                "folds": splits, "feature_infinity_policy": "replace with NaN", "data_scope_config": config,
                "prior_exposure": "Historical windows are not claimed pristine; outer results cannot alter this workflow."}
    _json(out / "frozen_protocol.json", protocol)  # Mandatory before first fit.
    identity_columns = sorted(REQUIRED | ({"label_available_at_utc"} if "label_available_at_utc" in frame else set()))
    frame.loc[:, identity_columns].to_parquet(out / "sample_manifest.parquet", index=False)
    recorder = FitRecorder(out)
    inner_cache, inner_records, inner_predictions, selection_records = {}, [], [], []
    outer_rows, gap_rows, outer_models, fold_records = [], [], {}, []
    baseline_specs = ({"id": BASELINES[0], "family": "prior"}, {"id": BASELINES[1], "family": "logistic", "C": 0.1})

    def select(years, stage):
        eligible = [year for year in years if splits[year]["status"] == "ELIGIBLE"]
        if not eligible:
            raise ValueError(f"No eligible inner annual folds: {stage}")
        scores = []
        for spec in CANDIDATES:
            losses, failed = [], False
            for year in eligible:
                key = (year, spec["id"])
                if key not in inner_cache:
                    training, validation, detail = _fold(frame, year)
                    record = {**detail, "candidate": spec["id"]}
                    try:
                        model = recorder.fit(spec, training, feature_columns, "candidate", "inner", year)
                        probability = _predict(model, validation, feature_columns)
                        daily = daily_metrics(validation, probability)
                        inner_cache[key] = daily.log_loss.to_numpy()
                        record.update(status="SUCCEEDED", metrics=aggregate_metrics(validation, probability, daily))
                        prediction = validation.loc[:, ["sample_id", "ticker", "date", "y", "return_3h"]].copy()
                        prediction["candidate"], prediction["inner_year"], prediction["probability_up"] = spec["id"], year, probability
                        inner_predictions.append(prediction)
                    except Exception as exc:
                        inner_cache[key] = None
                        record.update(status="FAILED", error=f"{type(exc).__name__}: {exc}")
                    inner_records.append(record)
                    _json(out / "inner_candidate_metrics.json", inner_records)
                value = inner_cache[key]
                failed |= value is None
                if value is not None:
                    losses.extend(value)
            score = float(np.mean(losses)) if losses and not failed else None
            scores.append({"candidate": spec["id"], "daily_log_loss": score, "valid": score is not None})
        valid = [(row["daily_log_loss"], index) for index, row in enumerate(scores) if row["valid"]]
        if not valid:
            raise ValueError(f"All frozen candidates failed: {stage}")
        selected = CANDIDATES[min(valid)[1]]
        selection_records.append({"stage": stage, "inner_years": eligible, "unavailable_inner_years": [year for year in years if year not in eligible], "scores": scores, "selected": selected["id"]})
        _json(out / "selections.json", selection_records)
        return selected

    try:
        for year in (2022, 2023, 2024, 2025):
            training, testing, detail = _fold(frame, year)
            if detail["status"] != "ELIGIBLE":
                fold_records.append(detail)
                continue
            try:
                selected = select(list(range(2021, year)), f"outer_{year}")
            except ValueError as exc:
                fold_records.append({**detail, "status": "SKIPPED_INSUFFICIENT_HISTORY" if "No eligible inner" in str(exc) else "UNTESTABLE_SELECTION", "error": str(exc)})
                continue
            model = recorder.fit(selected, training, feature_columns, "candidate", "outer_selected", year)
            predictions = {"selected": _predict(model, testing, feature_columns)}
            trained = {"selected": (model, feature_columns)}
            for spec in baseline_specs:
                columns = [] if spec["id"] == BASELINES[0] else baseline_columns
                baseline = recorder.fit(spec, training, columns, "baseline", "outer", year)
                predictions[spec["id"]] = _predict(baseline, testing, columns)
                trained[spec["id"]] = (baseline, columns)
            prediction = testing.loc[:, identity_columns].copy()
            prediction["outer_year"], prediction["selected_candidate"] = year, selected["id"]
            for name, probability in predictions.items():
                prediction[f"p_{name}"] = probability
                train_probability = _predict(trained[name][0], training, trained[name][1])
                train_loss = float(pd.Series(_loss_rows(training.y, train_probability)).groupby(training.date.to_numpy()).mean().mean())
                test_loss = float(pd.Series(_loss_rows(testing.y, probability)).groupby(testing.date.to_numpy()).mean().mean())
                gap_rows.append({"outer_year": year, "model": name, "train_daily_log_loss": train_loss, "oos_daily_log_loss": test_loss, "oos_minus_train": test_loss - train_loss})
            prediction["probability_not_up"] = 1 - predictions["selected"]
            outer_rows.append(prediction)
            outer_models[year] = {"selected_candidate": selected["id"], "models": trained}
            fold_records.append({**detail, "status": "EVALUATED", "selected_candidate": selected["id"]})
            pd.concat(outer_rows, ignore_index=True).to_parquet(out / "outer_oof_predictions.parquet", index=False)
            _json(out / "outer_folds.json", fold_records)
        if not outer_rows:
            raise ValueError("No outer folds evaluable under frozen date requirements")
        oof = pd.concat(outer_rows, ignore_index=True)
        daily_tables, overall, stability, reliability = [], {}, [], []
        for name in ("selected", *BASELINES):
            probability = oof[f"p_{name}"].to_numpy()
            daily = daily_metrics(oof, probability)
            daily["model"] = name
            daily_tables.append(daily)
            overall[name] = aggregate_metrics(oof, probability, daily)
            reliability.extend(_reliability(oof, probability, name))
            for dimension in ("outer_year", "sector"):
                for value, piece in oof.groupby(dimension, dropna=False):
                    stability.append({"dimension": dimension, "group": str(value), "model": name, **aggregate_metrics(piece, piece[f"p_{name}"].to_numpy())})
        daily = pd.concat(daily_tables, ignore_index=True)
        paired = paired_comparison(daily)
        adoptable = oof.outer_year.nunique() >= 3 and oof.date.nunique() >= 250 and all(row["ci_95_upper"] is not None and row["ci_95_upper"] < 0 for row in paired)
        adoption = "RESEARCH_ELIGIBLE_PREDICTIVE_EVIDENCE_ONLY" if adoptable else "RESEARCH_ONLY_NO_RELIABLE_ADVANTAGE"
        daily.to_csv(out / "daily_metrics.csv", index=False)
        pd.DataFrame(stability).to_csv(out / "stability.csv", index=False)
        pd.DataFrame(reliability).to_csv(out / "reliability.csv", index=False)
        pd.DataFrame(gap_rows).to_csv(out / "train_oos_gap.csv", index=False)
        _json(out / "evaluation.json", {"overall": overall, "paired_baselines": paired, "adoptability": adoption,
              "coverage": {"qualified_panel_rows": len(frame), "outer_requested_rows": int(frame.date.ge("2022-01-01").sum()), "oof_rows": len(oof), "oof_dates": oof.date.nunique(), "oof_row_coverage_of_qualified_outer_panel": len(oof) / int(frame.date.ge("2022-01-01").sum()), "outer_years": sorted(oof.outer_year.unique().tolist()), "upstream": config.get("coverage_metadata", {})},
              "limitations": ["A retrospective historical study, not an untouched holdout or proof against overfitting.", "Prediction evidence is not cost-adjusted strategy profit and grants no production/trading authorization."]})
        selected = select(list(range(2021, 2026)), "final_pre2026")
        final_training = _final_training(frame)
        final_model = recorder.fit(selected, final_training, feature_columns, "final", "final_refit_pre2026", 2025)
        final_baselines = {}
        for spec in baseline_specs:
            columns = [] if spec["id"] == BASELINES[0] else baseline_columns
            final_baselines[spec["id"]] = recorder.fit(spec, final_training, columns, "baseline", "final_refit_pre2026", 2025)
        bundle = {"model": final_model, "selected_candidate": selected["id"], "feature_columns": feature_columns,
                  "baseline_columns": baseline_columns, "baselines": final_baselines, "adoptability": adoption,
                  "training_cutoff_exclusive": CUTOFF.isoformat(), "training_max_label_end_utc": final_training.label_end_utc.max().isoformat(),
                  "training_max_label_maturity_utc": _maturity(final_training).max().isoformat(),
                  "protocol_sha256": hashlib.sha256((out / "frozen_protocol.json").read_bytes()).hexdigest(), "probability_semantics": "P(return_3h>0); complement includes flats"}
        joblib.dump(bundle, out / "final_research_model.joblib")
        joblib.dump(outer_models, out / "outer_evaluation_models.joblib")
        _json(out / "final_model_metadata.json", {key: value for key, value in bundle.items() if key not in {"model", "baselines"}})
        pd.concat(inner_predictions, ignore_index=True).to_parquet(out / "inner_oof_predictions.parquet", index=False)
        _json(out / "status.json", {"status": "COMPLETED", "adoptability": adoption, "selected_final_candidate": selected["id"]})
        return {"output": str(out), "adoptability": adoption, "selected_final_candidate": selected["id"], "overall": overall, "paired_baselines": paired}
    except Exception as exc:
        _json(out / "status.json", {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()})
        raise
    finally:
        if inner_predictions:
            pd.concat(inner_predictions, ignore_index=True).to_parquet(out / "inner_oof_predictions.parquet", index=False)
        if outer_models:
            joblib.dump(outer_models, out / "outer_evaluation_models.joblib")
        _json(out / "fit_summary.json", {"started": len(recorder.records), "succeeded": sum(row.get("status") == "SUCCEEDED" for row in recorder.records), "failed": sum(row.get("status") == "FAILED" for row in recorder.records), "category_counts": {category: sum(row["category"] == category for row in recorder.records) for category in ("baseline", "candidate", "final")}, "baseline_inner_fit_count": sum(row["category"] == "baseline" and row["phase"] == "inner" for row in recorder.records), "frozen_maximum_total_fits": FIT_BUDGET["maximum_total"], "fits": recorder.records})
        _json(out / "outer_folds.json", fold_records)
