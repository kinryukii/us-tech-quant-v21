"""Train all 31 frozen prediction members on physical pre-2026 data only.

Point, event-probability, quantile, distribution and rank interfaces remain
distinct. 2026 prediction is deliberately absent from this training command.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import importlib
import json
from pathlib import Path
import platform
import sys
import time
import traceback
import warnings

ROOT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
import common
# Append model-only dependency locations. Existing NumPy/scikit-learn stay
# authoritative rather than importing replacement copies from a vendor folder.
for _dependency in [ROOT/"vendor", Path(r"D:\us-tech-quant-envs\us-tech-quant-main\Lib\site-packages")]:
    if _dependency.is_dir() and str(_dependency) not in sys.path:
        sys.path.append(str(_dependency))

import joblib
import numpy as np
import pandas as pd
import scipy
import sklearn
from sklearn.ensemble import (ExtraTreesRegressor, HistGradientBoostingClassifier,
    HistGradientBoostingRegressor, RandomForestClassifier, RandomForestRegressor)
from sklearn.linear_model import (ElasticNet, HuberRegressor, LogisticRegression,
                                 QuantileRegressor, Ridge)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from nn_models import TorchEstimator

FEATURES = ['ret_1d', 'ret_3d', 'ret_5d', 'ret_10d', 'ret_20d', 'ret_40d', 'ret_60d', 'ret_120d',
    'price_vs_ma10', 'price_vs_ma20', 'price_vs_ma50', 'price_vs_ma120', 'ma10_vs_ma20',
    'ma20_vs_ma50', 'ma50_vs_ma120', 'realized_vol_5d', 'realized_vol_10d', 'realized_vol_20d',
    'realized_vol_60d', 'downside_vol_20d', 'upside_vol_20d', 'distance_from_high_20d',
    'distance_from_high_60d', 'distance_from_low_20d', 'distance_from_low_60d', 'max_drawdown_20d',
    'max_drawdown_60d', 'avg_volume_20d', 'avg_volume_60d', 'volume_ratio_5d_20d',
    'volume_ratio_20d_60d', 'avg_dollar_volume_20d']
if FEATURES != common.FEATURES:
    raise RuntimeError("COMMON_FEATURE_ORDER_MISMATCH")
SEED = common.SEED
DEFAULT_DATA = common.DATA_SOURCE
STAGES = common.CUTOFFS
PREDICTION_YEAR = {"development": 2024, "validation": 2025}
MODELS = ROOT/"models/base"
PREDICTIONS = ROOT/"predictions/base"
POINT_MEMBERS = common.POINT
CLASS_MEMBERS = common.CLASSIFIERS
QUANTILE_MEMBERS = common.QUANTILES
DISTRIBUTION_MEMBERS = common.DISTRIBUTIONS
RANK_MEMBERS = common.RANKERS
MEMBERS = common.MEMBERS
assert len(MEMBERS) == 31 and len(set(MEMBERS)) == 31
QUANTILES = (.1, .5, .9)
ALIASES = {"elastic":"elastic_net", "rf":"random_forest", "et":"extra_trees",
    "xgb":"xgboost", "lgb":"lightgbm", "cat":"catboost",
    **{name:name.replace("prob_", "clf_") for name in CLASS_MEMBERS},
    **{name:name.replace("quant_", "quantile_") for name in QUANTILE_MEMBERS},
    "dist_mlp":"dist_gaussian_mlp", "dist_cat":"dist_cat_uncertainty"}
TREE = dict(max_iter=80, max_depth=3, max_leaf_nodes=8, min_samples_leaf=100,
    learning_rate=.05, l2_regularization=10., early_stopping=False, random_state=SEED)
RANDOM_TREE = dict(n_estimators=64, max_depth=6, min_samples_leaf=50,
                   random_state=SEED, n_jobs=2)
OUTPUT_COLUMNS = ["mu", "p_up", "q10", "q50", "q90", "sigma", "rank_score"]


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
        default=str, allow_nan=False), encoding="utf-8")


def json_parameter(value):
    """Encode optional estimator sentinels without inventing finite values."""
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return {"native_nonfinite_parameter":repr(float(value))}
    if isinstance(value, dict):
        return {str(key):json_parameter(item) for key,item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_parameter(item) for item in value]
    if isinstance(value, np.generic):
        return json_parameter(value.item())
    return value


def fitted_diagnostic(model, quantile=None, recorded_warnings=None):
    record = {"quantile":quantile, "warnings":recorded_warnings or []}
    actual = model[-1] if hasattr(model, "steps") else model
    if hasattr(actual, "n_iter_"):
        record["iterations"] = np.asarray(actual.n_iter_).tolist()
    if hasattr(actual, "optimizer_steps_"):
        record["optimizer_steps"] = actual.optimizer_steps_
        record["loss_history"] = actual.loss_history_
        record["epochs"] = actual.epochs
    if hasattr(model, "get_params"):
        record["parameters"] = json_parameter({key:value for key,value in model.get_params(deep=False).items()
            if value is None or isinstance(value, (str, bool, int, float, np.generic))})
    if hasattr(model, "get_booster"):
        record["trained_boosting_rounds"] = int(model.get_booster().num_boosted_rounds())
    if hasattr(model, "base_models"):
        record["trained_boosting_rounds"] = len(model.base_models)
    if hasattr(model, "tree_count_"):
        record["trained_boosting_rounds"] = int(model.tree_count_)
    return record


def source_frame(path):
    frame = pd.read_parquet(path)
    for key in ["signal_date", "label_end_date"]:
        frame[key] = pd.to_datetime(frame[key])
    if frame.signal_date.isna().any() or not frame.signal_date.lt("2026-01-01").all():
        raise RuntimeError("TRAINER_REQUIRES_PHYSICAL_PRE2026_SOURCE")
    if frame.duplicated(["signal_date", "ticker"]).any():
        raise RuntimeError("DUPLICATE_SOURCE_KEYS")
    return frame.sort_values(["signal_date", "ticker"], kind="stable").reset_index(drop=True)


def sample_stage(frame, stage):
    picked = common.training_sample(frame, STAGES[stage])
    if picked.empty:
        raise RuntimeError(f"NO_VALID_TRAINING_ROWS:{stage}")
    if picked.groupby("signal_date").size().max() > 80:
        raise RuntimeError("TRAIN_DAILY_HASH_BUDGET_VIOLATION")
    return picked


def xgb_parameters():
    return dict(n_estimators=80, max_depth=3, min_child_weight=100., learning_rate=.05,
        reg_lambda=10., subsample=1., colsample_bytree=1., random_state=SEED,
        n_jobs=2, tree_method="hist", verbosity=0)


def lgb_parameters():
    return dict(n_estimators=80, max_depth=3, num_leaves=8, min_child_samples=100,
        learning_rate=.05, reg_lambda=10., random_state=SEED, n_jobs=2,
        verbosity=-1, deterministic=True, force_col_wise=True)


def cat_parameters():
    return dict(iterations=80, depth=3, min_data_in_leaf=100, grow_policy="Depthwise",
        learning_rate=.05, l2_leaf_reg=10., random_seed=SEED, thread_count=2,
        verbose=False, allow_writing_files=False, use_best_model=False)


def estimator(member, quantile=None):
    member = ALIASES.get(member, member)
    if member == "ridge":
        return make_pipeline(StandardScaler(), Ridge(alpha=10., solver="lsqr", tol=1e-6))
    if member == "elastic_net":
        return make_pipeline(StandardScaler(), ElasticNet(alpha=.0001, l1_ratio=.5,
            max_iter=5000, tol=1e-5, random_state=SEED, selection="cyclic"))
    if member == "huber":
        return make_pipeline(StandardScaler(), HuberRegressor(max_iter=1000,
            epsilon=1.35, alpha=.0001, tol=1e-5))
    if member == "ebm":
        from interpret.glassbox import ExplainableBoostingRegressor
        return ExplainableBoostingRegressor(interactions=3, outer_bags=2, inner_bags=0,
            max_rounds=100, early_stopping_rounds=0, validation_size=0.,
            random_state=SEED, n_jobs=2)
    if member == "random_forest":
        return RandomForestRegressor(**RANDOM_TREE)
    if member == "extra_trees":
        return ExtraTreesRegressor(**RANDOM_TREE)
    if member == "hgb":
        return HistGradientBoostingRegressor(**TREE)
    if member == "xgboost":
        from xgboost import XGBRegressor
        return XGBRegressor(objective="reg:squarederror", **xgb_parameters())
    if member == "lightgbm":
        from lightgbm import LGBMRegressor
        return LGBMRegressor(objective="regression", **lgb_parameters())
    if member == "catboost":
        from catboost import CatBoostRegressor
        return CatBoostRegressor(loss_function="RMSE", **cat_parameters())
    if member in ["mlp", "resnet", "ft_transformer"]:
        return TorchEstimator(kind=member)
    if member == "clf_logistic":
        return make_pipeline(StandardScaler(), LogisticRegression(C=.3,
            max_iter=1000, solver="lbfgs", random_state=SEED))
    if member == "clf_rf":
        return RandomForestClassifier(**RANDOM_TREE)
    if member == "clf_hgb":
        return HistGradientBoostingClassifier(**TREE)
    if member == "clf_xgb":
        from xgboost import XGBClassifier
        return XGBClassifier(objective="binary:logistic", **xgb_parameters())
    if member == "clf_lgb":
        from lightgbm import LGBMClassifier
        return LGBMClassifier(objective="binary", **lgb_parameters())
    if member == "clf_cat":
        from catboost import CatBoostClassifier
        return CatBoostClassifier(loss_function="Logloss", **cat_parameters())
    if member == "clf_mlp":
        return TorchEstimator(task="classification")
    if member == "quantile_linear":
        return make_pipeline(StandardScaler(), QuantileRegressor(quantile=quantile,
            alpha=.001, solver="highs"))
    if member == "quantile_hgb":
        return HistGradientBoostingRegressor(loss="quantile", quantile=quantile, **TREE)
    if member == "quantile_xgb":
        from xgboost import XGBRegressor
        return XGBRegressor(objective="reg:quantileerror", quantile_alpha=quantile,
                            **xgb_parameters())
    if member == "quantile_lgb":
        from lightgbm import LGBMRegressor
        return LGBMRegressor(objective="quantile", alpha=quantile, **lgb_parameters())
    if member == "quantile_cat":
        from catboost import CatBoostRegressor
        return CatBoostRegressor(loss_function=f"Quantile:alpha={quantile}", **cat_parameters())
    if member == "quantile_mlp":
        return TorchEstimator(task="quantile", quantile=quantile)
    if member == "dist_ngboost":
        from ngboost import NGBRegressor
        from ngboost.distns import Normal
        from sklearn.tree import DecisionTreeRegressor
        return NGBRegressor(Dist=Normal, Base=DecisionTreeRegressor(max_depth=3,
            min_samples_leaf=100, random_state=SEED), n_estimators=80,
            learning_rate=.05, random_state=SEED, verbose=False,
            minibatch_frac=1., col_sample=1., natural_gradient=True)
    if member == "dist_gaussian_mlp":
        return TorchEstimator(task="normal")
    if member == "dist_cat_uncertainty":
        from catboost import CatBoostRegressor
        return CatBoostRegressor(loss_function="RMSEWithUncertainty", **cat_parameters())
    if member == "rank_xgb":
        from xgboost import XGBRanker
        return XGBRanker(objective="rank:pairwise", **xgb_parameters())
    if member == "rank_lgb":
        from lightgbm import LGBMRanker
        return LGBMRanker(objective="lambdarank", label_gain=[0, 1, 3, 7, 15], **lgb_parameters())
    raise ValueError(f"UNKNOWN_MEMBER:{member}")


def relevance_labels(train, target):
    # Five fixed within-signal relevance bins; sorting score is never a return.
    result = pd.Series(target).groupby(train.signal_date, sort=False).rank(method="average", pct=True)
    return np.minimum(4, np.floor(result.to_numpy()*5)).astype(int)


def fit_member(member, train):
    x = train[FEATURES].to_numpy(float)
    target = np.clip(train.y_next_open.to_numpy(float), -.20, .20)
    payload = {"member":member, "features":FEATURES, "target":"y_next_open",
        "horizon":"next_open_to_following_open_1_session", "return_clip":[-.2,.2],
        "models":[], "normalization":"per-estimator fitted only on training rows"}
    positive = target[target > 0.]
    nonpositive = target[target <= 0.]
    payload["positive_amplitude"] = float(positive.mean()) if len(positive) else 0.
    payload["nonpositive_amplitude"] = float(nonpositive.mean()) if len(nonpositive) else 0.
    payload["positive_count"], payload["nonpositive_count"] = len(positive), len(nonpositive)
    diagnostics = []
    for quantile in QUANTILES if member in QUANTILE_MEMBERS else [None]:
        model = estimator(member, quantile)
        fit_target = (target > 0.).astype(int) if member in CLASS_MEMBERS else target
        if member in RANK_MEMBERS:
            fit_target = relevance_labels(train, target)
        with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=2):
            warnings.simplefilter("always")
            if member == "rank_xgb":
                model.fit(x, fit_target, qid=pd.factorize(train.signal_date, sort=False)[0])
            elif member == "rank_lgb":
                model.fit(x, fit_target, group=train.groupby("signal_date", sort=False).size().to_numpy())
            else:
                model.fit(x, fit_target)
        record = fitted_diagnostic(model, quantile, [{"category":w.category.__name__,
            "message":str(w.message)} for w in caught])
        if any(w.category.__name__ == "ConvergenceWarning" for w in caught):
            raise RuntimeError("FIXED_BUDGET_CONVERGENCE_WARNING:"+json.dumps(record["warnings"]))
        payload["models"].append(model)
        diagnostics.append(record)
    payload["raw_object"] = ("conditional_quantile_knots" if member in QUANTILE_MEMBERS else
        "event_probability_and_train_amplitude" if member in CLASS_MEMBERS else
        "conditional_normal_distribution" if member in DISTRIBUTION_MEMBERS else
        "within_signal_ranking_score" if member in RANK_MEMBERS else
        "robust_return_location" if member == "huber" else "point_return")
    return payload, diagnostics


def predict_payload(payload, frame):
    """Return raw typed outputs; q/rank never receive a fabricated mu field."""
    member = payload["member"]
    internal_member = ALIASES.get(member, member)
    result = frame[["signal_date", "ticker"]].copy()
    for column in OUTPUT_COLUMNS:
        result[column] = np.nan
    valid = np.isfinite(frame[FEATURES].to_numpy(float)).all(axis=1)
    result["prediction_status"] = np.where(valid, "PREDICTED", "MISSING_FEATURES")
    if not valid.any():
        return result
    x = frame.loc[valid, FEATURES].to_numpy(float)
    model = payload["models"][0]
    with threadpool_limits(limits=2):
        if member in CLASS_MEMBERS:
            p = np.asarray(model.predict_proba(x))[:, 1]
            result.loc[valid, "p_up"] = p
            result.loc[valid, "mu"] = p*payload["positive_amplitude"] + (1.-p)*payload["nonpositive_amplitude"]
        elif member in QUANTILE_MEMBERS:
            for quantile, model in zip(QUANTILES, payload["models"]):
                result.loc[valid, f"q{int(quantile*100)}"] = np.asarray(model.predict(x)).reshape(-1)
        elif member == "dist_ngboost":
            distribution = model.pred_dist(x)
            result.loc[valid, "mu"] = np.asarray(distribution.params["loc"]).reshape(-1)
            result.loc[valid, "sigma"] = np.asarray(distribution.params["scale"]).reshape(-1)
        elif internal_member == "dist_gaussian_mlp":
            mean, scale = model.predict_normal(x)
            result.loc[valid, "mu"], result.loc[valid, "sigma"] = mean, scale
        elif internal_member == "dist_cat_uncertainty":
            # CatBoost VirtEnsembles uncertainty prediction exposes mean and
            # aleatoric variance. Its ordinary predict() uses the loss's linked
            # uncertainty output; use the documented RawFormulaVal log-sigma.
            raw = np.asarray(model.predict(x, prediction_type="RawFormulaVal"))
            result.loc[valid, "mu"] = raw[:, 0]
            result.loc[valid, "sigma"] = np.exp(np.clip(raw[:, 1], -30., 30.))
        elif member in RANK_MEMBERS:
            result.loc[valid, "rank_score"] = np.asarray(model.predict(x)).reshape(-1)
        else:
            result.loc[valid, "mu"] = np.asarray(model.predict(x)).reshape(-1)
    relevant = (["p_up", "mu"] if member in CLASS_MEMBERS else ["q10", "q50", "q90"]
        if member in QUANTILE_MEMBERS else ["rank_score"] if member in RANK_MEMBERS else
        ["mu", "sigma"] if member in DISTRIBUTION_MEMBERS else ["mu"])
    if not np.isfinite(result.loc[valid, relevant].to_numpy(float)).all():
        raise RuntimeError(f"NONFINITE_RAW_PREDICTION:{member}")
    if "sigma" in relevant and not result.loc[valid, "sigma"].gt(0).all():
        raise RuntimeError(f"NONPOSITIVE_PREDICTIVE_SCALE:{member}")
    return result


def load_payload(member, stage):
    receipt_path = MODELS/member/f"{stage}_RECEIPT.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    artifact = MODELS/member/f"{stage}.joblib"
    if receipt["status"] != "PASS" or sha(artifact) != receipt["artifact_sha256"]:
        raise RuntimeError(f"FROZEN_BASE_ARTIFACT_FAILED:{member}:{stage}")
    return joblib.load(artifact)


def write_predictions(payload, stage, frame):
    if stage not in PREDICTION_YEAR:
        return None
    year = PREDICTION_YEAR[stage]
    day_frame = frame.loc[frame.signal_date.dt.year.eq(year)].copy()
    result = predict_payload(payload, day_frame)
    folder = PREDICTIONS/stage
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder/f"{payload['member']}.parquet"
    if destination.exists():
        raise RuntimeError(f"PRESERVE_EXISTING_BASE_PREDICTIONS:{destination}")
    result.to_parquet(destination, index=False)
    return {"path":str(destination), "sha256":sha(destination), "rows":len(result),
        "year":year, "signal_min":str(result.signal_date.min().date()),
        "signal_max":str(result.signal_date.max().date()),
        "raw_object":payload["raw_object"], "columns":list(result.columns),
        "prediction_failures":int(result.prediction_status.ne("PREDICTED").sum())}


def recover_xgb_development_receipt():
    """Recover the serialization-only interruption without fitting or writes
    to the existing model and prediction files.
    """
    member, stage = "xgb", "development"
    folder = MODELS/member
    receipt_path = folder/f"{stage}_RECEIPT.json"
    if receipt_path.exists():
        raise RuntimeError("RECOVERY_RECEIPT_ALREADY_EXISTS")
    artifact, prediction_path = folder/f"{stage}.joblib", PREDICTIONS/stage/f"{member}.parquet"
    original_pre = folder/f"{stage}_PRE_FIT.json"
    metadata = json.loads(original_pre.read_text(encoding="utf-8"))
    paused = json.loads((ROOT/"PAUSED.json").read_text(encoding="utf-8"))
    original_hashes = paused["artifact_sha256"]
    for path in [artifact, prediction_path, original_pre, Path(metadata["source"]), Path(metadata["sample_keys_path"])]:
        relative = path.relative_to(ROOT).as_posix()
        if sha(path) != original_hashes[relative]:
            raise RuntimeError(f"PAUSED_RECOVERY_HASH_DRIFT:{relative}")
    payload = joblib.load(artifact)
    if (payload["member"] != member or payload["stage"] != stage
            or payload["features"] != FEATURES or payload["cutoff_exclusive"] != STAGES[stage]):
        raise RuntimeError("RECOVERY_PAYLOAD_CONTRACT_MISMATCH")
    model = payload["models"][0]
    params = model.get_params()
    if any(params[key] != value for key,value in xgb_parameters().items()):
        raise RuntimeError("RECOVERY_MODEL_SPEC_MISMATCH")
    if model.get_booster().num_boosted_rounds() != 80:
        raise RuntimeError("RECOVERY_BOOSTING_BUDGET_MISMATCH")
    saved = pd.read_parquet(prediction_path)
    frame = source_frame(metadata["source"])
    replayed = predict_payload(payload, frame.loc[frame.signal_date.dt.year.eq(2024)])
    pd.testing.assert_frame_equal(saved.reset_index(drop=True), replayed.reset_index(drop=True),
                                  check_exact=True)
    metadata.update(status="PASS", artifact=str(artifact), artifact_sha256=sha(artifact),
        diagnostics=[fitted_diagnostic(model)], estimator_fit_count=1,
        raw_object=payload["raw_object"], prediction={"path":str(prediction_path),
            "sha256":sha(prediction_path), "rows":len(saved), "year":2024,
            "signal_min":str(saved.signal_date.min().date()), "signal_max":str(saved.signal_date.max().date()),
            "raw_object":payload["raw_object"], "columns":list(saved.columns),
            "prediction_failures":int(saved.prediction_status.ne("PREDICTED").sum())},
        positive_amplitude=payload["positive_amplitude"],
        nonpositive_amplitude=payload["nonpositive_amplitude"],
        positive_count=payload["positive_count"], nonpositive_count=payload["nonpositive_count"],
        runtime_seconds=max(0., prediction_path.stat().st_mtime-original_pre.stat().st_mtime),
        runtime_precision="estimated from pre-fit and completed prediction file mtimes; original timer lost",
        recovery={"reason":"Strict receipt JSON rejected optional NaN missing-value sentinel",
            "refit_calls":0, "existing_model_written":False, "existing_prediction_written":False,
            "saved_predictions_exactly_reproduced":True, "original_prefit_sha256":sha(original_pre),
            "recovery_code_sha256":sha(__file__), "warnings_from_original_fit":"not retained after serialization failure"})
    write_json(receipt_path, metadata)
    return {"status":"PASS_RECOVERED_NO_REFIT", "member":member, "stage":stage,
            "artifact_sha256":metadata["artifact_sha256"], "prediction_rows":len(saved)}


def run(data_source, members, stages):
    data_source = Path(data_source).resolve()
    frame = source_frame(data_source)
    source_hash = sha(data_source)
    contracts = {str(path):sha(path) for path in ROOT.glob("*CONTRACT*") if path.is_file()}
    code_hashes = {str(path):sha(path) for path in [Path(__file__), ROOT/"nn_models.py"]}
    for stage in stages:
        train = sample_stage(frame, stage)
        keys_path = MODELS/f"sample_keys_{stage}.parquet"
        MODELS.mkdir(parents=True, exist_ok=True)
        keys = train[["signal_date", "ticker", "label_end_date"]]
        if keys_path.exists():
            pd.testing.assert_frame_equal(pd.read_parquet(keys_path), keys.reset_index(drop=True))
        else:
            keys.to_parquet(keys_path, index=False)
        base = {"stage":stage, "cutoff_exclusive":STAGES[stage], "features":FEATURES,
            "source":str(data_source), "source_sha256":source_hash, "seed":SEED,
            "target":"y_next_open", "horizon":"next_open_to_following_open_1_session",
            "return_clip":[-.2,.2], "train_rows":len(train),
            "train_days":int(train.signal_date.nunique()),
            "train_signal_min":str(train.signal_date.min().date()),
            "train_signal_max":str(train.signal_date.max().date()),
            "train_label_end_max":str(train.label_end_date.max().date()),
            "sample_keys_path":str(keys_path), "sample_keys_sha256":sha(keys_path),
            "sampling":"per mature eligible date SHA256(date|ticker|seed) first 80; common.training_sample",
            "code_sha256":code_hashes, "contract_sha256":contracts,
            "fit_2026_rows":0, "prediction_2026_rows":0,
            "hyperparameter_search_count":0, "python":platform.python_version(),
            "versions":{"numpy":np.__version__, "scipy":scipy.__version__, "sklearn":sklearn.__version__}}
        for member in members:
            folder = MODELS/member
            folder.mkdir(parents=True, exist_ok=True)
            receipt_path, artifact = folder/f"{stage}_RECEIPT.json", folder/f"{stage}.joblib"
            if receipt_path.exists():
                existing = json.loads(receipt_path.read_text(encoding="utf-8"))
                if existing["source_sha256"] != source_hash or existing["sample_keys_sha256"] != base["sample_keys_sha256"]:
                    raise RuntimeError(f"EXISTING_MEMBER_SOURCE_CHANGED:{member}:{stage}")
                if existing["status"] == "PASS" and sha(artifact) != existing["artifact_sha256"]:
                    raise RuntimeError(f"EXISTING_MEMBER_ARTIFACT_CHANGED:{member}:{stage}")
                print(json.dumps({"status":"PRESERVED", "member":member, "stage":stage,
                                  "previous_status":existing["status"]}), flush=True)
                continue
            if artifact.exists():
                raise RuntimeError(f"UNRECEIPTED_ARTIFACT_PRESERVED:{artifact}")
            start = time.monotonic()
            receipt = {**base, "member":member, "status":"RUNNING"}
            prefit_path = folder/f"{stage}_PRE_FIT.json"
            if prefit_path.exists():
                old_prefit = json.loads(prefit_path.read_text(encoding="utf-8"))
                if (old_prefit["source_sha256"] != source_hash
                        or old_prefit["sample_keys_sha256"] != base["sample_keys_sha256"]):
                    raise RuntimeError(f"INTERRUPTED_PREFIT_SAMPLE_DRIFT:{member}:{stage}")
                receipt["resumed_from_interrupted_prefit_sha256"] = sha(prefit_path)
                receipt["pause_receipt_sha256"] = sha(MODELS/"PAUSE_RECEIPT.json")
                prefit_path = folder/f"{stage}_RESUME_PRE_FIT.json"
            write_json(prefit_path, receipt)
            print(json.dumps({"status":"FIT_STARTED", "member":member, "stage":stage,
                              "train_rows":len(train)}), flush=True)
            try:
                payload, diagnostics = fit_member(member, train)
                # Test the training object's typed output on actual training
                # rows before artifact finalization. No fit follows this check.
                predict_payload(payload, train.iloc[:256])
                payload.update(stage=stage, cutoff_exclusive=STAGES[stage])
                joblib.dump(payload, artifact, compress=3)
                prediction = write_predictions(payload, stage, frame)
                receipt.update(status="PASS", artifact=str(artifact),
                    artifact_sha256=sha(artifact), diagnostics=diagnostics,
                    estimator_fit_count=len(payload["models"]),
                    raw_object=payload["raw_object"], prediction=prediction,
                    positive_amplitude=payload["positive_amplitude"],
                    nonpositive_amplitude=payload["nonpositive_amplitude"],
                    positive_count=payload["positive_count"], nonpositive_count=payload["nonpositive_count"])
                del payload
            except Exception as exc:
                receipt.update(status="FAILED", failure_type=type(exc).__name__,
                    failure_reason=str(exc), traceback=traceback.format_exc(),
                    artifact_exists=artifact.exists(),
                    failure_policy="fixed member remains in coverage; no alternate model or hyperparameter search")
            receipt["runtime_seconds"] = time.monotonic()-start
            write_json(receipt_path, receipt)
            print(json.dumps({"status":receipt["status"], "member":member, "stage":stage,
                "seconds":receipt["runtime_seconds"], "failure_reason":receipt.get("failure_reason")}), flush=True)
            gc.collect()
        del train
        gc.collect()
    if sha(data_source) != source_hash or any(sha(path) != digest for path,digest in code_hashes.items()):
        raise RuntimeError("BASE_TRAINING_SOURCE_OR_CODE_CHANGED")
    return summarize()


def summarize():
    rows = []
    for path in sorted(MODELS.glob("*/*_RECEIPT.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        rows.append({key:value.get(key) for key in ["member", "stage", "status", "train_rows",
            "train_days", "train_signal_max", "train_label_end_max", "runtime_seconds",
            "artifact_sha256", "failure_type", "failure_reason"]})
    summary = {"members":MEMBERS, "scheduled_member_stages":93, "completed_receipts":len(rows),
        "pass_count":sum(row["status"] == "PASS" for row in rows),
        "failure_count":sum(row["status"] == "FAILED" for row in rows),
        "fit_2026_rows":0, "prediction_2026_rows":0, "rows":rows}
    write_json(MODELS/"BASE_TRAINING_SUMMARY.json", summary)
    write_json(MODELS/"TRAINING_RECEIPT.json", summary)
    pd.DataFrame(rows).to_csv(MODELS/"BASE_TRAINING_COVERAGE.csv", index=False)
    return summary


def smoke():
    # Interface test on synthetic data is not candidate fitting or selection.
    generator = np.random.default_rng(SEED)
    x = generator.normal(size=(256, 32))
    y = .01*x[:, 0]+generator.normal(scale=.01, size=len(x))
    results = {}
    for kind,task in [("mlp","regression"), ("resnet","regression"),
                      ("ft_transformer","regression"), ("mlp","classification"),
                      ("mlp","quantile"), ("mlp","normal")]:
        estimator = TorchEstimator(kind=kind, task=task, epochs=1)
        estimator.fit(x, (y > 0).astype(float) if task == "classification" else y)
        raw = estimator.raw_predict(x[:16])
        assert np.isfinite(raw).all() and raw.shape == (16, 2 if task == "normal" else 1)
        results[f"{kind}:{task}"] = {"shape":list(raw.shape), "steps":estimator.optimizer_steps_}
    print(json.dumps({"status":"PASS_SYNTHETIC_INTERFACE", "models":results}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-source", default=str(DEFAULT_DATA))
    parser.add_argument("--members", nargs="+", choices=MEMBERS, default=MEMBERS)
    parser.add_argument("--stages", nargs="+", choices=list(STAGES), default=list(STAGES))
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--summarize", action="store_true")
    parser.add_argument("--recover-xgb", action="store_true")
    options = parser.parse_args()
    if options.smoke:
        smoke()
    elif options.recover_xgb:
        print(json.dumps(recover_xgb_development_receipt()), flush=True)
    elif options.summarize:
        result = summarize()
        print(json.dumps({key:result[key] for key in ["completed_receipts", "pass_count", "failure_count"]}), flush=True)
    else:
        result = run(options.data_source, options.members, options.stages)
        print(json.dumps({key:result[key] for key in ["completed_receipts", "pass_count", "failure_count"]}), flush=True)
