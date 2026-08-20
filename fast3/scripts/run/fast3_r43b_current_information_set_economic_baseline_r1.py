#!/usr/bin/env python
"""FAST3 R43B frozen current-information-set economic OOF baseline."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import (average_precision_score, brier_score_loss, mean_absolute_error,
                             mean_squared_error, r2_score, roc_auc_score)


REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
AUTHORITATIVE_ROOT = RESULTS / "frozen/fast3/r43b_current_information_set_economic_baseline_r1"
STAGING_ROOT = RESULTS / "scratch/fast3/.r43b_current_information_set_economic_baseline_r1.staging"

R42R_ROOT = RESULTS / "frozen/fast3/r42r_frozen_confirmation_preregistration_repair_r1"
R42R_PREREG = R42R_ROOT / "FAST3_R42R_CONFIRMATION_PREREGISTRATION.json"
R42R_SHA256 = "2df064f334d6a8bc45d79d8bd4f308ee9b82a33c97129a6ae36ba6aecfc9c3e1"
R43A_ROOT = RESULTS / "frozen/fast3/r43a_independent_economic_target_contract_freeze_r1"
R43A_CONTRACT = R43A_ROOT / "FAST3_R43A_ECONOMIC_TARGET_CONTRACT.json"
R43A_SUMMARY = R43A_ROOT / "FAST3_R43A_SUMMARY.json"
R43A_SHA256 = "a5d43651433c6dde50eef791facd02047db2be073a0097acaf31cd1af25d2d6a"

R28_PHASE2_SOURCE = REPO / "fast3/scripts/run/fast3_r28_phase2_fixed_training.py"
R28_FEATURE_SOURCE = REPO / "fast3/src/fast3/r28_multisignal.py"
R28_PHASE2_ROOT = RESULTS / "frozen/fast3/r28_phase2_20260808T125629Z"
R28_FEATURE_MANIFEST = R28_PHASE2_ROOT / "R28_FEATURE_MANIFEST.json"
R28_PHASE2_DECISION = R28_PHASE2_ROOT / "R28_PHASE2_DECISION.json"
R28_CONTROL_ROOT = RESULTS / "frozen/fast3/cleanroom_r2_20260808"
R28_CONTROL_MANIFEST = R28_CONTROL_ROOT / "cleanroom_r2_freeze_manifest.json"
R28_SOURCE_MANIFEST = R28_CONTROL_ROOT / "cleanroom_r2_preholdout_source_manifest.json"
R28_MODELS_ROOT = RESULTS / "frozen/fast3/r28_phase3_20260808T131135Z/models"
R28_PROSPECTIVE_RUNTIME = RESULTS / "runtime/fast3/r28_prospective_dual_shadow_r1"
R28_PROSPECTIVE_SEALED = RESULTS / "frozen/fast3/r28_prospective_dual_shadow_r1"

R36_LEDGER = RESULTS / "scratch/fast3/r36_payoff_path_decomposition_r1_20260810T131648Z/FAST3_R36_PATH_DIAGNOSTIC_LEDGER.parquet"
R41_SCORE_ROOT = RESULTS / "scratch/fast3/r28_phase2_20260808T125629Z/ledgers"
R41_SCORE_PATHS = {
    head: R41_SCORE_ROOT / f"R28_3_CROSS_ASSET_FLOW_{head}_IMMUTABLE_VALIDATION_LEDGER.parquet"
    for head in ("UP", "DOWN")
}

FEATURES = (
    "return_5m", "return_15m", "return_60m", "realized_vol_15m", "realized_vol_60m",
    "relative_volume", "range_position", "symbol_code", "direction_code", "session_code",
    "volume_zscore_60m", "signed_volume_pressure_15m", "peer_return_15m", "relative_return_15m",
)
CATEGORICAL_FEATURES = ("symbol_code", "session_code")
BLOCKS = ("OOF_2020", "OOF_2021", "OOF_2022", "OOF_2023", "OOF_2024", "OOF_2025_JAN")
VALIDATION_FOLDS = BLOCKS[1:]
HORIZONS = (5, 10, 15, 30, 60)
RETURN_COLUMNS = tuple(f"return_{minute}m_net20" for minute in HORIZONS)
QUINTILES = ("Q1", "Q2", "Q3", "Q4", "Q5")
HGB_STRUCTURE = {
    "learning_rate": 0.08,
    "max_iter": 100,
    "max_leaf_nodes": 7,
    "min_samples_leaf": 200,
    "l2_regularization": 1.0,
    "random_state": 1729,
    "early_stopping": False,
}
MIN_MEANINGFUL_QUINTILE_SAMPLE = 25
EXPECTED = {
    "R43A_SUMMARY": "e7094b0e87f7370368d41406b69170ade124dff5430928e98dd62f0b99a704c5",
    "R28_PHASE2_SOURCE": "7906f1e29936e1cd98368eb0b2a25eb15e92ea8e64f33a91836f374fae84dd12",
    "R28_FEATURE_SOURCE": "584d390e26da27af342400ca90260eecc70beee50c580f9dc42e08d942e8c504",
    "R28_FEATURE_MANIFEST": "3cac01f22f8a0b308f2d666d06e36abe13643c4d60948bdc312a5a1a01b96ab3",
    "R28_PHASE2_DECISION": "ed3a803165f2e2516903433c31b36d01b12a63895fc5ab4d7d7e6a773a7d90c7",
    "R28_CONTROL_MANIFEST": "38352151a703737d74b4d61dbe68f82a9c6f3d5058aa72bd2a1896e19a5cb412",
    "R28_SOURCE_MANIFEST": "8ef4126e586350a8c67180e6c375309867d498370ddfffcd93a93eee7fc62610",
    "R36_LEDGER": "261bc7618abdf289444a84bd7b9dc47787f1788758d5bbee38f639ca0ec63aeb",
    "UP_SCORE_LEDGER": "6e9cae3e9226bae3acc54ac3e7f50575b5614983db35bf639b66c2b515c25b9b",
    "DOWN_SCORE_LEDGER": "bb14261a8727df883ae6c8fdd001bedc7d6e626b6437e444c507a9919e1a3ee1",
}


class BaselineIdentityStop(RuntimeError):
    pass


class OOFContractStop(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                       allow_nan=False) + "\n").encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, np.integer): return int(value)
    if isinstance(value, np.floating): return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, Path)): return str(value)
    if pd.isna(value): return None
    raise TypeError(type(value).__name__)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                               default=json_default, allow_nan=False) + "\n", encoding="utf-8")


def tree_hashes(root: Path, allow_missing: bool = False) -> dict[str, str]:
    if not root.exists():
        if allow_missing: return {}
        raise BaselineIdentityStop(f"STOP_REQUIRED_FROZEN_ROOT_MISSING:{root}")
    return {str(path.relative_to(root)).replace("\\", "/"): sha256(path)
            for path in sorted(root.rglob("*")) if path.is_file()}


def frozen_isolation_snapshot() -> dict[str, Any]:
    return {
        "R42R_TREE": tree_hashes(R42R_ROOT),
        "R43A_TREE": tree_hashes(R43A_ROOT),
        "R28_PROSPECTIVE_RUNTIME": tree_hashes(R28_PROSPECTIVE_RUNTIME, allow_missing=True),
        "R28_PROSPECTIVE_SEALED": tree_hashes(R28_PROSPECTIVE_SEALED, allow_missing=True),
        "R28_PRODUCTION_MODELS": tree_hashes(R28_MODELS_ROOT),
    }


def verify_contracts_and_sources() -> tuple[dict[str, Any], dict[str, str]]:
    if sha256(R42R_PREREG) != R42R_SHA256:
        raise BaselineIdentityStop("STOP_R42R_PREREGISTRATION_SHA256_MISMATCH")
    if sha256(R43A_CONTRACT) != R43A_SHA256 or sha256(R43A_SUMMARY) != EXPECTED["R43A_SUMMARY"]:
        raise BaselineIdentityStop("STOP_R43A_TARGET_CONTRACT_SHA256_MISMATCH")
    paths = {
        "R28_PHASE2_SOURCE": R28_PHASE2_SOURCE, "R28_FEATURE_SOURCE": R28_FEATURE_SOURCE,
        "R28_FEATURE_MANIFEST": R28_FEATURE_MANIFEST, "R28_PHASE2_DECISION": R28_PHASE2_DECISION,
        "R28_CONTROL_MANIFEST": R28_CONTROL_MANIFEST, "R28_SOURCE_MANIFEST": R28_SOURCE_MANIFEST,
        "R36_LEDGER": R36_LEDGER, "UP_SCORE_LEDGER": R41_SCORE_PATHS["UP"],
        "DOWN_SCORE_LEDGER": R41_SCORE_PATHS["DOWN"],
    }
    if any(not path.is_file() for path in paths.values()):
        raise BaselineIdentityStop("STOP_BASELINE_SOURCE_MISSING")
    hashes = {name: sha256(path) for name, path in paths.items()}
    if hashes != {name: EXPECTED[name] for name in paths}:
        raise BaselineIdentityStop("STOP_BASELINE_SOURCE_HASH_MISMATCH")
    contract = json.loads(R43A_CONTRACT.read_text(encoding="utf-8"))
    if (contract.get("PRIMARY_TARGET_NAME") != "AVERAGE_FIXED_HORIZON_NET20"
            or contract.get("SECONDARY_TARGET_NAME") != "MULTI_HORIZON_POSITIVE_MAJORITY_K3"
            or contract.get("HORIZONS") != list(HORIZONS)
            or contract.get("TARGET_PAYOFF_MECHANICAL_COUPLING") is not False):
        raise BaselineIdentityStop("STOP_R43A_TARGET_CONTRACT_CONTENT_MISMATCH")
    feature_manifest = json.loads(R28_FEATURE_MANIFEST.read_text(encoding="utf-8"))
    if tuple(feature_manifest["candidates"]["R28_3_CROSS_ASSET_FLOW"]) != FEATURES:
        raise BaselineIdentityStop("STOP_R28_14_FEATURE_IDENTITY_MISMATCH")
    r42r = json.loads(R42R_PREREG.read_text(encoding="utf-8"))
    if tuple(r42r["R28_PRODUCTION_IDENTITY"]["FEATURES"]) != FEATURES:
        raise BaselineIdentityStop("STOP_R42R_R28_FEATURE_IDENTITY_MISMATCH")
    return contract, hashes


def preregistration(created_at: str, source_hashes: dict[str, str]) -> dict[str, Any]:
    feature_hash = canonical_sha256(list(FEATURES))
    fold_contract = [
        {"fold": fold, "train_blocks": list(BLOCKS[:BLOCKS.index(fold)]), "valid_block": fold}
        for fold in VALIDATION_FOLDS
    ]
    return {
        "CONTRACT_ID": "FAST3_R43B_CURRENT_INFORMATION_SET_ECONOMIC_BASELINE_R1",
        "CREATED_AT_UTC": created_at,
        "STATUS": "FROZEN_BEFORE_FEATURE_VALUE_MATERIALIZATION_AND_MODEL_FIT",
        "RESEARCH_NATURE": "FROZEN_BASELINE_MODEL_TEST",
        "PRIMARY_TARGET": "AVERAGE_FIXED_HORIZON_NET20",
        "SECONDARY_TARGET": "MULTI_HORIZON_POSITIVE_MAJORITY_K3",
        "R43A_TARGET_CONTRACT_SHA256": R43A_SHA256,
        "R42R_PREREGISTRATION_SHA256": R42R_SHA256,
        "BASELINE_FEATURE_COUNT": 14,
        "BASELINE_FEATURES": list(FEATURES),
        "BASELINE_FEATURES_SHA256": feature_hash,
        "FEATURE_SELECTION_ALLOWED": False,
        "FEATURE_ADDITION_ALLOWED": False,
        "MISSINGNESS_FEATURE_EXPANSION_ALLOWED": False,
        "PCA_OR_INTERACTION_SEARCH_ALLOWED": False,
        "DIRECTIONS_MODELED_SEPARATELY": ["UP", "DOWN"],
        "MODEL_FAMILY": "sklearn HistGradientBoosting",
        "MAX_MODEL_FAMILY_COUNT": 1,
        "PRIMARY_MODEL": "HistGradientBoostingRegressor",
        "SECONDARY_MODEL": "HistGradientBoostingClassifier",
        "HGB_BASELINE_CONFIG": HGB_STRUCTURE,
        "CATEGORICAL_FEATURES": list(CATEGORICAL_FEATURES),
        "PRIMARY_LOSS": "squared_error",
        "SECONDARY_LOSS": "log_loss",
        "REGRESSOR_CONFIG_MAPPING": (
            "Reuse all R28 HGB structural parameters; map classifier objective to squared_error; "
            "set early_stopping=false explicitly because R28 auto resolves false at these sample sizes and no internal random split is allowed"
        ),
        "PARAMETER_SEARCH_ALLOWED": False,
        "MODEL_CONFIG_CHANGED_AFTER_RESULT": False,
        "CHRONOLOGICAL_BLOCKS": list(BLOCKS),
        "OOF_FOLD_COUNT": 5,
        "OOF_FOLD_CONTRACT": fold_contract,
        "OOF_2020_ROLE": "INITIAL_TRAINING_BLOCK_ONLY_NO_EARLIER_ECONOMIC_LABEL_BLOCK_EXISTS",
        "SHUFFLE_ALLOWED": False,
        "RANDOM_CV_ALLOWED": False,
        "MIN_MEANINGFUL_QUINTILE_SAMPLE": MIN_MEANINGFUL_QUINTILE_SAMPLE,
        "LOW_SAMPLE_RULE": "direction-fold validation count <25 is LOW_SAMPLE_DESCRIPTIVE_ONLY and has no Q5-Q1",
        "PRIMARY_PREDICTION_BUCKETS": list(QUINTILES),
        "PRIMARY_BUCKET_METHOD": (
            "within direction, stable ascending mergesort(predicted_Y_ECON, decision_timestamp_utc, candidate_id), "
            "then bucket=min(floor(position*5/n),4)"
        ),
        "ORDERING_RULES": {
            "MONOTONIC_POSITIVE": "all four adjacent differences >=0",
            "MOSTLY_POSITIVE": "at least three adjacent differences >0 and Q5>Q1",
            "MONOTONIC_NEGATIVE": "all four adjacent differences <=0, evaluated after positive rules",
            "NON_MONOTONIC": "otherwise",
        },
        "CURRENT_INFORMATION_SIGNAL_GATE": {
            "A": "OOF Spearman>=0.05", "B": "Q5-Q1 realized mean>0",
            "C": "ordering MONOTONIC_POSITIVE or MOSTLY_POSITIVE",
            "D": ">=3 evaluable folds and strictly more than half have Spearman>0",
        },
        "STRONG_SIGNAL_GATE": {
            "A": "OOF Spearman>=0.10", "B": "Q5-Q1 realized mean>=0.001",
            "C": "Q5 realized mean>0", "D": "same fold-stability gate",
        },
        "FOLD_EVALUABILITY": "validation count>=25 and nonconstant primary prediction",
        "TAIL_ROBUSTNESS": {
            "Q5_MEAN_EXCLUSION": "remove one highest/lowest realized Y_ECON within Q5, candidate_id ascending breaks equal-value ties",
            "SPREAD_EXCLUSION": "remove one highest/lowest realized Y_ECON across Q1 union Q5, then recompute Q5-Q1",
            "TRAINING_TARGET_WINSORIZATION_ALLOWED": False,
        },
        "FUTURE_FAMILY_MIN_DELTA_SPEARMAN": 0.02,
        "FUTURE_FAMILY_MIN_DELTA_Q5_Q1": 0.0005,
        "FUTURE_NO_MAJORITY_FOLD_DEGRADATION_RULE": (
            "among common evaluable direction-folds, degraded Spearman fold count must be <=floor(common fold count/2)"
        ),
        "SECONDARY_TARGET_IS_SUPPORTING_ONLY": True,
        "SECONDARY_CANNOT_ACCEPT_FEATURE_FAMILY_ALONE": True,
        "PRIMARY_REGRESSION_FIT_BUDGET": 10,
        "SECONDARY_CLASSIFICATION_FIT_BUDGET": 10,
        "MODEL_FIT_BUDGET": 20,
        "FULL_SAMPLE_REFIT_ALLOWED": False,
        "HORIZON_SELECTION_ALLOWED": False,
        "ECONOMIC_THRESHOLD_SEARCH_ALLOWED": False,
        "ACCOUNT_CAGR_ALLOWED": False,
        "POSITION_SIZING_ALLOWED": False,
        "STOP_OR_TAKE_PROFIT_ALLOWED": False,
        "SOURCE_SHA256": source_hashes,
    }


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None: raise BaselineIdentityStop(f"STOP_MODULE_LOAD_FAILURE:{path}")
    spec.loader.exec_module(module)
    return module


def reconstruct_features() -> pd.DataFrame:
    if str(REPO / "fast3/src") not in sys.path:
        sys.path.insert(0, str(REPO / "fast3/src"))
    p2 = load_module(R28_PHASE2_SOURCE, "r28_phase2_for_r43b")
    control, source, records = p2.control_inputs()
    if source.get("sha256") != "943ced982f93e3661456a8d62e7fe8147123b1260cb19a0952487cbffaafe21a":
        raise BaselineIdentityStop("STOP_R28_SOURCE_MANIFEST_IDENTITY")
    paths = p2.exact_paths(records)
    data = {symbol: p2.read_symbol(paths[symbol]) for symbol in p2.R1.SYMBOLS}
    universe, audit = p2.build_common_universe(data)
    if audit.get("common_comparable_row_count") != 1282618:
        raise BaselineIdentityStop("STOP_R28_COMMON_UNIVERSE_REPRODUCTION")
    result = universe[["candidate_id", "decision_timestamp_utc", "direction", *FEATURES]].copy()
    if result["candidate_id"].duplicated().any():
        raise BaselineIdentityStop("STOP_R28_FEATURE_UNIVERSE_DUPLICATE")
    return result


def load_targets_and_folds() -> pd.DataFrame:
    columns = ["candidate_id", "decision_timestamp_utc", "head", "path_complete", *RETURN_COLUMNS]
    target = pd.read_parquet(R36_LEDGER, columns=columns)
    numeric = target.loc[:, RETURN_COLUMNS].apply(pd.to_numeric, errors="coerce")
    if (len(target) != 1197 or target["candidate_id"].duplicated().any()
            or not target["path_complete"].eq(True).all()
            or not np.isfinite(numeric.to_numpy(dtype=float)).all()):
        raise BaselineIdentityStop("STOP_R43A_TARGET_ROW_IDENTITY")
    target["realized_y_econ"] = numeric.mean(axis=1)
    target["realized_positive_majority"] = numeric.gt(0).sum(axis=1).ge(3).astype(int)
    fold_columns = ["candidate_id", "validation_slice", "selected", "head", "direction"]
    folds = pd.concat([pd.read_parquet(path, columns=fold_columns) for path in R41_SCORE_PATHS.values()], ignore_index=True)
    joined = target.merge(folds, on="candidate_id", how="left", validate="one_to_one",
                          suffixes=("", "_score"), indicator=True)
    if (not joined["_merge"].eq("both").all() or not joined["selected"].eq(True).all()
            or not joined["head"].eq(joined["head_score"]).all()
            or not joined["head"].eq(joined["direction"]).all()
            or set(joined["validation_slice"]) != set(BLOCKS)):
        raise BaselineIdentityStop("STOP_R43A_CHRONOLOGICAL_FOLD_IDENTITY")
    r43a = json.loads(R43A_SUMMARY.read_text(encoding="utf-8"))
    for head in ("UP", "DOWN"):
        part = joined.loc[joined["head"].eq(head), "realized_y_econ"]
        if (len(part) != r43a[f"{head}_PRIMARY_TARGET_VALID_COUNT"]
                or not np.isclose(part.mean(), r43a[f"{head}_PRIMARY_TARGET_MEAN"], atol=1e-15, rtol=0)
                or not np.isclose(part.median(), r43a[f"{head}_PRIMARY_TARGET_MEDIAN"], atol=1e-15, rtol=0)):
            raise BaselineIdentityStop(f"STOP_R43A_TARGET_AGGREGATE_REPRODUCTION:{head}")
    joined["decision_timestamp_utc"] = pd.to_datetime(joined["decision_timestamp_utc"], utc=True, errors="raise")
    return joined.drop(columns=["_merge"])


def feature_identity_bytes(frame: pd.DataFrame) -> bytes:
    columns = ["candidate_id", "decision_timestamp_utc", "direction", "validation_slice", *FEATURES]
    ordered = frame.sort_values(["candidate_id"], kind="mergesort").loc[:, columns].copy()
    ordered["decision_timestamp_utc"] = pd.to_datetime(ordered["decision_timestamp_utc"], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    buffer = io.StringIO(newline="")
    ordered.to_csv(buffer, index=False, lineterminator="\n", float_format="%.17g", na_rep="NaN")
    return buffer.getvalue().encode("utf-8")


def materialize_baseline_frame() -> tuple[pd.DataFrame, str]:
    target = load_targets_and_folds()
    features = reconstruct_features()
    frame = target.merge(features, on="candidate_id", how="left", validate="one_to_one",
                         suffixes=("_target", "_feature"), indicator=True)
    if not frame["_merge"].eq("both").all():
        raise BaselineIdentityStop("STOP_R28_FEATURE_TO_R43A_TARGET_JOIN")
    target_ts = pd.to_datetime(frame["decision_timestamp_utc_target"], utc=True)
    feature_ts = pd.to_datetime(frame["decision_timestamp_utc_feature"], utc=True)
    if (not np.array_equal(target_ts.to_numpy(dtype="datetime64[us]"), feature_ts.to_numpy(dtype="datetime64[us]"))
            or not frame["head"].eq(frame["direction_feature"]).all()):
        raise BaselineIdentityStop("STOP_R28_FEATURE_ROW_TIMESTAMP_DIRECTION_IDENTITY")
    frame = frame.rename(columns={"decision_timestamp_utc_target": "decision_timestamp_utc",
                                  "direction_feature": "direction"})
    required = ["candidate_id", "decision_timestamp_utc", "head", "direction", "validation_slice",
                "realized_y_econ", "realized_positive_majority", *FEATURES]
    frame = frame.loc[:, required].copy()
    non_feature = ["candidate_id", "decision_timestamp_utc", "head", "direction", "validation_slice",
                   "realized_y_econ", "realized_positive_majority"]
    if frame[non_feature].isna().any().any():
        raise BaselineIdentityStop("STOP_BASELINE_NONFEATURE_VALUE_MISSING")
    identity_hash = hashlib.sha256(feature_identity_bytes(frame)).hexdigest()
    return frame, identity_hash


def model_config(model_type: str) -> dict[str, Any]:
    config = dict(HGB_STRUCTURE)
    config["categorical_features"] = [name in CATEGORICAL_FEATURES for name in FEATURES]
    config["loss"] = "squared_error" if model_type == "regressor" else "log_loss"
    return config


def make_model(model_type: str):
    config = model_config(model_type)
    return HistGradientBoostingRegressor(**config) if model_type == "regressor" else HistGradientBoostingClassifier(**config)


def build_fold_schedule(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for fold in VALIDATION_FOLDS:
        position = BLOCKS.index(fold)
        train = frame.loc[frame["validation_slice"].isin(BLOCKS[:position])]
        valid = frame.loc[frame["validation_slice"].eq(fold)]
        if train.empty or valid.empty or train["decision_timestamp_utc"].max() >= valid["decision_timestamp_utc"].min():
            raise OOFContractStop(f"STOP_CHRONOLOGICAL_OOF_ORDER:{fold}")
        row = {
            "fold": fold,
            "train_start": str(train["decision_timestamp_utc"].min()),
            "train_end": str(train["decision_timestamp_utc"].max()),
            "valid_start": str(valid["decision_timestamp_utc"].min()),
            "valid_end": str(valid["decision_timestamp_utc"].max()),
        }
        for head in ("UP", "DOWN"):
            row[f"{head.lower()}_train_count"] = int(train["head"].eq(head).sum())
            row[f"{head.lower()}_valid_count"] = int(valid["head"].eq(head).sum())
            row[f"{head.lower()}_sample_status"] = (
                "LOW_SAMPLE_DESCRIPTIVE_ONLY" if row[f"{head.lower()}_valid_count"] < MIN_MEANINGFUL_QUINTILE_SAMPLE
                else "EVALUABLE"
            )
        rows.append(row)
    return pd.DataFrame(rows)


def run_oof(frame: pd.DataFrame, model_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    predictions, manifest = [], []
    primary_fits = secondary_fits = 0
    model_dir.mkdir(parents=True)
    for fold in VALIDATION_FOLDS:
        position = BLOCKS.index(fold)
        for head in ("UP", "DOWN"):
            train = frame.loc[frame["head"].eq(head) & frame["validation_slice"].isin(BLOCKS[:position])].copy()
            valid = frame.loc[frame["head"].eq(head) & frame["validation_slice"].eq(fold)].copy()
            if train.empty or valid.empty or train["realized_positive_majority"].nunique() != 2:
                raise OOFContractStop(f"STOP_OOF_TRAIN_OR_CLASS_IDENTITY:{head}:{fold}")
            x_train, x_valid = train.loc[:, FEATURES], valid.loc[:, FEATURES]
            regressor = make_model("regressor")
            regressor.fit(x_train, train["realized_y_econ"])
            primary_fits += 1
            classifier = make_model("classifier")
            classifier.fit(x_train, train["realized_positive_majority"].astype(int))
            secondary_fits += 1
            reg_path = model_dir / f"{head}_{fold}_PRIMARY_REGRESSOR.joblib"
            cls_path = model_dir / f"{head}_{fold}_SECONDARY_CLASSIFIER.joblib"
            joblib.dump(regressor, reg_path, compress=3)
            joblib.dump(classifier, cls_path, compress=3)
            manifest.extend([
                {"direction": head, "fold": fold, "role": "PRIMARY_REGRESSOR", "path": f"models/{reg_path.name}", "sha256": sha256(reg_path)},
                {"direction": head, "fold": fold, "role": "SECONDARY_CLASSIFIER", "path": f"models/{cls_path.name}", "sha256": sha256(cls_path)},
            ])
            out = valid[["candidate_id", "decision_timestamp_utc", "validation_slice", "head",
                         "realized_y_econ", "realized_positive_majority"]].copy()
            out["predicted_y_econ"] = regressor.predict(x_valid)
            out["constant_y_econ_prediction"] = float(train["realized_y_econ"].mean())
            out["predicted_positive_majority_probability"] = classifier.predict_proba(x_valid)[:, 1]
            out["training_primary_mean"] = float(train["realized_y_econ"].mean())
            out["training_secondary_base_rate"] = float(train["realized_positive_majority"].mean())
            predictions.append(out)
    counts = {
        "PRIMARY_REGRESSION_FIT_COUNT": primary_fits,
        "SECONDARY_CLASSIFICATION_FIT_COUNT": secondary_fits,
        "MODEL_FIT_COUNT": primary_fits + secondary_fits,
    }
    if counts != {"PRIMARY_REGRESSION_FIT_COUNT": 10, "SECONDARY_CLASSIFICATION_FIT_COUNT": 10, "MODEL_FIT_COUNT": 20}:
        raise OOFContractStop("STOP_MODEL_FIT_BUDGET_IDENTITY")
    return pd.concat(predictions, ignore_index=True), pd.DataFrame(manifest), counts


def stable_quintiles(frame: pd.DataFrame, prediction_column: str) -> pd.Series:
    result = pd.Series(index=frame.index, dtype="object")
    for _, index in frame.groupby("head", sort=True).groups.items():
        ordered = frame.loc[index].sort_values(
            [prediction_column, "decision_timestamp_utc", "candidate_id"], kind="mergesort"
        )
        n = len(ordered)
        bucket = np.minimum(np.floor(np.arange(n) * 5 / n).astype(int), 4)
        result.loc[ordered.index] = [QUINTILES[value] for value in bucket]
    if result.isna().any(): raise OOFContractStop("STOP_OOF_QUINTILE_ASSIGNMENT")
    return result


def ordering(values: list[float]) -> str:
    delta = np.diff(np.asarray(values, dtype=float))
    if np.all(delta >= 0): return "MONOTONIC_POSITIVE"
    if int((delta > 0).sum()) >= 3 and values[-1] > values[0]: return "MOSTLY_POSITIVE"
    if np.all(delta <= 0): return "MONOTONIC_NEGATIVE"
    return "NON_MONOTONIC"


def correlation(x: pd.Series, y: pd.Series, method: str) -> float | None:
    if len(x) < 2 or x.nunique(dropna=True) < 2 or y.nunique(dropna=True) < 2: return None
    value = x.corr(y, method=method)
    return float(value) if pd.notna(value) else None


def remove_one(part: pd.DataFrame, best: bool) -> pd.DataFrame:
    if part.empty: return part
    ordered = part.sort_values(["realized_y_econ", "candidate_id"], ascending=[not best, True], kind="mergesort")
    return part.drop(index=ordered.index[0])


def primary_metrics(predictions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    metric_rows, quintile_rows, robustness_rows = [], [], []
    for head, part in predictions.groupby("head", sort=True):
        actual, predicted, constant = part["realized_y_econ"], part["predicted_y_econ"], part["constant_y_econ_prediction"]
        mae = float(mean_absolute_error(actual, predicted)); rmse = float(np.sqrt(mean_squared_error(actual, predicted)))
        const_mae = float(mean_absolute_error(actual, constant)); const_rmse = float(np.sqrt(mean_squared_error(actual, constant)))
        metric_rows.append({
            "direction": head, "oof_count": len(part),
            "spearman": correlation(predicted, actual, "spearman"),
            "pearson": correlation(predicted, actual, "pearson"),
            "mae": mae, "rmse": rmse, "r2": float(r2_score(actual, predicted)),
            "baseline_constant_mae": const_mae, "baseline_constant_rmse": const_rmse,
            "model_minus_constant_mae": mae - const_mae,
            "model_minus_constant_rmse": rmse - const_rmse,
        })
        for quintile in QUINTILES:
            q = part.loc[part["primary_prediction_quintile"].eq(quintile)]
            quintile_rows.append({
                "direction": head, "quintile": quintile, "count": len(q),
                "mean_prediction": float(q["predicted_y_econ"].mean()),
                "realized_y_econ_mean": float(q["realized_y_econ"].mean()),
                "realized_y_econ_median": float(q["realized_y_econ"].median()),
                "realized_y_econ_p05": float(q["realized_y_econ"].quantile(.05)),
                "realized_y_econ_p95": float(q["realized_y_econ"].quantile(.95)),
                "positive_y_econ_rate": float(q["realized_y_econ"].gt(0).mean()),
            })
        q1 = part.loc[part["primary_prediction_quintile"].eq("Q1")]
        q5 = part.loc[part["primary_prediction_quintile"].eq("Q5")]
        union = pd.concat([q1, q5])
        q5_ex_best = remove_one(q5, True); q5_ex_worst = remove_one(q5, False)
        union_ex_best = remove_one(union, True); union_ex_worst = remove_one(union, False)
        def spread(sample: pd.DataFrame) -> float:
            return float(sample.loc[sample["primary_prediction_quintile"].eq("Q5"), "realized_y_econ"].mean()
                         - sample.loc[sample["primary_prediction_quintile"].eq("Q1"), "realized_y_econ"].mean())
        robustness_rows.append({
            "direction": head,
            "q5_realized_y_econ_mean_raw": float(q5["realized_y_econ"].mean()),
            "q5_realized_y_econ_mean_excluding_best_1": float(q5_ex_best["realized_y_econ"].mean()),
            "q5_realized_y_econ_mean_excluding_worst_1": float(q5_ex_worst["realized_y_econ"].mean()),
            "q5_minus_q1_raw": spread(union),
            "q5_minus_q1_ex_best1": spread(union_ex_best),
            "q5_minus_q1_ex_worst1": spread(union_ex_worst),
        })
    metrics = pd.DataFrame(metric_rows)
    quintiles = pd.DataFrame(quintile_rows)
    robustness = pd.DataFrame(robustness_rows)
    for row in metrics.itertuples():
        means = quintiles.loc[quintiles["direction"].eq(row.direction)].set_index("quintile").loc[list(QUINTILES), "realized_y_econ_mean"].tolist()
        metrics.loc[metrics["direction"].eq(row.direction), "primary_ordering"] = ordering(means)
        metrics.loc[metrics["direction"].eq(row.direction), "q5_minus_q1_realized_y_econ_mean"] = means[-1] - means[0]
    return metrics, quintiles, robustness


def fold_stability(predictions: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, dict[str, Any]]]:
    rows = []
    for (head, fold), part in predictions.groupby(["head", "validation_slice"], sort=True):
        low_sample = len(part) < MIN_MEANINGFUL_QUINTILE_SAMPLE
        spearman = correlation(part["predicted_y_econ"], part["realized_y_econ"], "spearman")
        evaluable = bool(not low_sample and spearman is not None)
        q5_q1: float | None = None
        q_status = "NOT_AVAILABLE_LOW_SAMPLE" if low_sample else "NOT_AVAILABLE_NONUNIQUE_PREDICTION"
        if not low_sample and part["predicted_y_econ"].nunique() >= 5:
            local = part.copy()
            local["local_quintile"] = stable_quintiles(local, "predicted_y_econ")
            q5_q1 = float(local.loc[local["local_quintile"].eq("Q5"), "realized_y_econ"].mean()
                          - local.loc[local["local_quintile"].eq("Q1"), "realized_y_econ"].mean())
            q_status = "AVAILABLE"
        rows.append({
            "direction": head, "validation_slice": fold, "sample_count": len(part),
            "sample_status": "LOW_SAMPLE_DESCRIPTIVE_ONLY" if low_sample else "STANDARD",
            "prediction_unique_count": int(part["predicted_y_econ"].nunique()),
            "spearman": spearman, "spearman_evaluable": evaluable,
            "q5_minus_q1": q5_q1, "q5_minus_q1_status": q_status,
        })
    table = pd.DataFrame(rows)
    flags: dict[str, dict[str, Any]] = {}
    for head in ("UP", "DOWN"):
        part = table.loc[table["direction"].eq(head)]
        eval_s = part.loc[part["spearman_evaluable"]]
        eval_q = part.loc[part["q5_minus_q1_status"].eq("AVAILABLE")]
        positive_s = int(eval_s["spearman"].gt(0).sum())
        positive_q = int(eval_q["q5_minus_q1"].gt(0).sum())
        fold_gate = bool(len(eval_s) >= 3 and positive_s > len(eval_s) / 2)
        flags[head] = {
            "POSITIVE_SPEARMAN_FOLD_COUNT": positive_s,
            "EVALUABLE_SPEARMAN_FOLD_COUNT": len(eval_s),
            "POSITIVE_Q5_MINUS_Q1_FOLD_COUNT": positive_q,
            "EVALUABLE_Q5_MINUS_Q1_FOLD_COUNT": len(eval_q),
            "FOLD_STABILITY_GATE": fold_gate,
        }
    return table, flags


def secondary_metrics(predictions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    metrics, quintiles = [], []
    for head, part in predictions.groupby("head", sort=True):
        actual = part["realized_positive_majority"].astype(int)
        probability = part["predicted_positive_majority_probability"]
        metrics.append({
            "direction": head, "count": len(part), "base_rate": float(actual.mean()),
            "auroc": float(roc_auc_score(actual, probability)),
            "pr_auc": float(average_precision_score(actual, probability)),
            "brier_score": float(brier_score_loss(actual, probability)),
        })
        for quintile in QUINTILES:
            q = part.loc[part["secondary_probability_quintile"].eq(quintile)]
            quintiles.append({
                "direction": head, "quintile": quintile, "count": len(q),
                "mean_predicted_probability": float(q["predicted_positive_majority_probability"].mean()),
                "positive_majority_rate": float(q["realized_positive_majority"].mean()),
            })
    metric_table = pd.DataFrame(metrics); quintile_table = pd.DataFrame(quintiles)
    for head in ("UP", "DOWN"):
        values = quintile_table.loc[quintile_table["direction"].eq(head)].set_index("quintile").loc[list(QUINTILES), "positive_majority_rate"].tolist()
        metric_table.loc[metric_table["direction"].eq(head), "secondary_q1_to_q5_ordering"] = ordering(values)
    return metric_table, quintile_table


def classify(primary: pd.DataFrame, quintiles: pd.DataFrame, fold_flags: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    flags: dict[str, Any] = {}; has_signal = strong_signal = False
    for head in ("UP", "DOWN"):
        row = primary.loc[primary["direction"].eq(head)].iloc[0]
        q = quintiles.loc[quintiles["direction"].eq(head)].set_index("quintile")
        fold_gate = fold_flags[head]["FOLD_STABILITY_GATE"]
        signal = bool(row["spearman"] is not None and row["spearman"] >= .05
                      and row["q5_minus_q1_realized_y_econ_mean"] > 0
                      and row["primary_ordering"] in ("MONOTONIC_POSITIVE", "MOSTLY_POSITIVE")
                      and fold_gate)
        strong = bool(row["spearman"] is not None and row["spearman"] >= .10
                      and row["q5_minus_q1_realized_y_econ_mean"] >= .001
                      and q.loc["Q5", "realized_y_econ_mean"] > 0 and fold_gate)
        flags[f"{head}_CURRENT_INFORMATION_SIGNAL"] = signal
        flags[f"{head}_STRONG_ECONOMIC_SIGNAL"] = strong
        has_signal = has_signal or signal; strong_signal = strong_signal or strong
    classification = (
        "B_CURRENT_INFORMATION_SET_STRONG_ECONOMIC_BASELINE" if strong_signal else
        "A_CURRENT_INFORMATION_SET_HAS_INDEPENDENT_ECONOMIC_SIGNAL" if has_signal else
        "C_CURRENT_INFORMATION_SET_NO_USEFUL_ECONOMIC_SIGNAL"
    )
    flags["CURRENT_INFORMATION_SET_HAS_ECONOMIC_SIGNAL"] = has_signal
    flags["CURRENT_INFORMATION_SET_STRONG_ECONOMIC_SIGNAL"] = strong_signal
    return classification, flags


def summary_payload(feature_hash: str, predictions: pd.DataFrame, primary: pd.DataFrame,
                    quintiles: pd.DataFrame, robustness: pd.DataFrame, folds: pd.DataFrame,
                    fold_flags: dict[str, dict[str, Any]], secondary: pd.DataFrame,
                    fit_counts: dict[str, int], isolation_unchanged: bool) -> dict[str, Any]:
    classification, flags = classify(primary, quintiles, fold_flags)
    summary: dict[str, Any] = {
        "FAST3_R43B_STATUS": "PASS", "FAST3_R43B_CLASSIFICATION": classification,
        "FAST3_R43B_DECISION": "R43C_REGIME_INFORMATION_FAMILY_INCREMENTAL_TEST",
        "NEXT_STAGE": "R43C_REGIME_INFORMATION_FAMILY_INCREMENTAL_TEST",
        "PRIMARY_TARGET": "AVERAGE_FIXED_HORIZON_NET20",
        "SECONDARY_TARGET": "MULTI_HORIZON_POSITIVE_MAJORITY_K3",
        "BASELINE_FEATURE_COUNT": 14, "BASELINE_FEATURES": list(FEATURES),
        "BASELINE_FEATURES_SHA256": canonical_sha256(list(FEATURES)),
        "BASELINE_FEATURE_VALUE_SNAPSHOT_SHA256": feature_hash,
        "OOF_FOLD_COUNT": 5, "OOF_PREDICTION_COUNT": len(predictions),
        "HGB_BASELINE_CONFIG": {"regressor": model_config("regressor"), "classifier": model_config("classifier")},
        "REGRESSOR_CONFIG_MAPPING": preregistration("fixed", {})["REGRESSOR_CONFIG_MAPPING"],
        "MODEL_CONFIG_CHANGED_AFTER_RESULT": False,
        **flags, **fit_counts,
        "MAX_MODEL_FAMILY_COUNT": 1, "FULL_SAMPLE_REFIT_COUNT": 0,
        "FUTURE_FAMILY_MIN_DELTA_SPEARMAN": 0.02,
        "FUTURE_FAMILY_MIN_DELTA_Q5_Q1": 0.0005,
        "SECONDARY_TARGET_IS_SUPPORTING_ONLY": True,
        "TARGET_TRAINING_WINSORIZATION_COUNT": 0,
        "R43A_TARGET_CONTRACT_SHA256_VERIFIED": True,
        "R42R_PREREGISTRATION_SHA256_VERIFIED": True,
        "R28_PROSPECTIVE_LINE_ISOLATION": isolation_unchanged,
        "R28_MODEL_CHANGED": False, "R28_FEATURE_CHANGED": False,
        "R28_THRESHOLD_CHANGED": False, "R28_PREREGISTRATION_CHANGED": False,
        "R28_CONFIRMATION_LEDGER_CHANGED": False,
        "PIT_STATUS": "PASS_R28_DECISION_TIME_FEATURE_RECONSTRUCTION",
        "OOF_INTEGRITY_STATUS": "PASS_FIVE_EXPANDING_CHRONOLOGICAL_FOLDS_NO_SHUFFLE",
        "TARGET_CONTRACT_STATUS": "PASS_R43A_EXACT_HASH_AND_TARGET_AGGREGATE_REPRODUCTION",
        "CORPORATE_ACTION_STATUS": "PASS_INHERITED_R43A_R36_FROZEN_NORMALIZATION",
        "STORAGE_CONTRACT_STATUS": "PASS_FAST3_STORAGE_CONTRACT_R1_EXTERNAL_GENERATION_RESEARCH_ONLY",
    }
    for head in ("UP", "DOWN"):
        p = primary.loc[primary["direction"].eq(head)].iloc[0]
        q = quintiles.loc[quintiles["direction"].eq(head)].set_index("quintile")
        s = secondary.loc[secondary["direction"].eq(head)].iloc[0]
        rob = robustness.loc[robustness["direction"].eq(head)].iloc[0]
        summary.update({
            f"{head}_PRIMARY_OOF_SPEARMAN": p["spearman"],
            f"{head}_PRIMARY_OOF_PEARSON": p["pearson"],
            f"{head}_PRIMARY_MAE": p["mae"], f"{head}_PRIMARY_RMSE": p["rmse"], f"{head}_PRIMARY_R2": p["r2"],
            f"{head}_BASELINE_CONSTANT_MAE": p["baseline_constant_mae"],
            f"{head}_BASELINE_CONSTANT_RMSE": p["baseline_constant_rmse"],
            f"{head}_MODEL_MINUS_CONSTANT_MAE": p["model_minus_constant_mae"],
            f"{head}_MODEL_MINUS_CONSTANT_RMSE": p["model_minus_constant_rmse"],
            f"{head}_Q1_REALIZED_Y_ECON_MEAN": q.loc["Q1", "realized_y_econ_mean"],
            f"{head}_Q5_REALIZED_Y_ECON_MEAN": q.loc["Q5", "realized_y_econ_mean"],
            f"{head}_Q5_MINUS_Q1_REALIZED_Y_ECON_MEAN": p["q5_minus_q1_realized_y_econ_mean"],
            f"{head}_PRIMARY_ORDERING": p["primary_ordering"],
            f"{head}_POSITIVE_SPEARMAN_FOLD_COUNT": fold_flags[head]["POSITIVE_SPEARMAN_FOLD_COUNT"],
            f"{head}_EVALUABLE_SPEARMAN_FOLD_COUNT": fold_flags[head]["EVALUABLE_SPEARMAN_FOLD_COUNT"],
            f"{head}_POSITIVE_Q5_MINUS_Q1_FOLD_COUNT": fold_flags[head]["POSITIVE_Q5_MINUS_Q1_FOLD_COUNT"],
            f"{head}_EVALUABLE_Q5_MINUS_Q1_FOLD_COUNT": fold_flags[head]["EVALUABLE_Q5_MINUS_Q1_FOLD_COUNT"],
            f"{head}_SECONDARY_BASE_RATE": s["base_rate"], f"{head}_SECONDARY_AUROC": s["auroc"],
            f"{head}_SECONDARY_PR_AUC": s["pr_auc"], f"{head}_SECONDARY_BRIER_SCORE": s["brier_score"],
            f"{head}_SECONDARY_Q1_TO_Q5_ORDERING": s["secondary_q1_to_q5_ordering"],
            **{f"{head}_{key.upper()}": rob[key] for key in (
                "q5_realized_y_econ_mean_raw", "q5_realized_y_econ_mean_excluding_best_1",
                "q5_realized_y_econ_mean_excluding_worst_1", "q5_minus_q1_raw",
                "q5_minus_q1_ex_best1", "q5_minus_q1_ex_worst1")},
        })
    return summary


def render_terminal(summary: dict[str, Any]) -> str:
    keys = [
        "FAST3_R43B_STATUS", "FAST3_R43B_CLASSIFICATION", "FAST3_R43B_DECISION",
        "PRIMARY_TARGET", "SECONDARY_TARGET", "BASELINE_FEATURE_COUNT", "BASELINE_FEATURES_SHA256", "OOF_FOLD_COUNT",
        "UP_PRIMARY_OOF_SPEARMAN", "DOWN_PRIMARY_OOF_SPEARMAN",
        "UP_PRIMARY_OOF_PEARSON", "DOWN_PRIMARY_OOF_PEARSON",
        "UP_PRIMARY_MAE", "DOWN_PRIMARY_MAE", "UP_PRIMARY_R2", "DOWN_PRIMARY_R2",
        "UP_Q1_REALIZED_Y_ECON_MEAN", "UP_Q5_REALIZED_Y_ECON_MEAN",
        "UP_Q5_MINUS_Q1_REALIZED_Y_ECON_MEAN", "UP_PRIMARY_ORDERING",
        "DOWN_Q1_REALIZED_Y_ECON_MEAN", "DOWN_Q5_REALIZED_Y_ECON_MEAN",
        "DOWN_Q5_MINUS_Q1_REALIZED_Y_ECON_MEAN", "DOWN_PRIMARY_ORDERING",
        "UP_POSITIVE_SPEARMAN_FOLD_COUNT", "DOWN_POSITIVE_SPEARMAN_FOLD_COUNT",
        "UP_SECONDARY_BASE_RATE", "DOWN_SECONDARY_BASE_RATE", "UP_SECONDARY_AUROC", "DOWN_SECONDARY_AUROC",
        "UP_SECONDARY_PR_AUC", "DOWN_SECONDARY_PR_AUC",
        "CURRENT_INFORMATION_SET_HAS_ECONOMIC_SIGNAL", "CURRENT_INFORMATION_SET_STRONG_ECONOMIC_SIGNAL",
        "FUTURE_FAMILY_MIN_DELTA_SPEARMAN", "FUTURE_FAMILY_MIN_DELTA_Q5_Q1",
        "PRIMARY_REGRESSION_FIT_COUNT", "SECONDARY_CLASSIFICATION_FIT_COUNT", "MODEL_FIT_COUNT",
        "R43A_TARGET_CONTRACT_SHA256_VERIFIED", "R42R_PREREGISTRATION_SHA256_VERIFIED",
        "R28_PROSPECTIVE_LINE_ISOLATION", "PIT_STATUS", "OOF_INTEGRITY_STATUS", "TARGET_CONTRACT_STATUS",
        "CORPORATE_ACTION_STATUS", "STORAGE_CONTRACT_STATUS", "NEXT_STAGE",
    ]
    def value(item: Any) -> str:
        if isinstance(item, bool): return str(item).lower()
        if item is None or (isinstance(item, float) and not np.isfinite(item)): return "NOT_AVAILABLE"
        return str(item)
    return "\n".join(f"{key}={value(summary[key])}" for key in keys)


def execute() -> dict[str, Any]:
    if AUTHORITATIVE_ROOT.exists(): raise BaselineIdentityStop("STOP_AUTHORITATIVE_R43B_ALREADY_EXISTS")
    if STAGING_ROOT.exists(): raise BaselineIdentityStop("STOP_R43B_STAGING_ALREADY_EXISTS")
    isolation_before = frozen_isolation_snapshot()
    _, source_hashes = verify_contracts_and_sources()
    STAGING_ROOT.mkdir(parents=True)
    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    prereg = preregistration(created_at, source_hashes)
    prereg_path = STAGING_ROOT / "FAST3_R43B_PREREGISTRATION.json"
    write_json(prereg_path, prereg)
    prereg_hash = sha256(prereg_path)

    frame, feature_value_hash = materialize_baseline_frame()
    identity_path = STAGING_ROOT / "FAST3_R43B_FEATURE_IDENTITY.csv"
    identity_path.write_bytes(feature_identity_bytes(frame))
    if sha256(identity_path) != feature_value_hash: raise BaselineIdentityStop("STOP_FEATURE_IDENTITY_FILE_HASH")
    schedule = build_fold_schedule(frame)
    predictions, model_manifest, fit_counts = run_oof(frame, STAGING_ROOT / "models")
    predictions["primary_prediction_quintile"] = stable_quintiles(predictions, "predicted_y_econ")
    predictions["secondary_probability_quintile"] = stable_quintiles(predictions, "predicted_positive_majority_probability")
    primary, primary_quintiles, robustness = primary_metrics(predictions)
    folds, fold_flags = fold_stability(predictions)
    secondary, secondary_quintiles = secondary_metrics(predictions)
    isolation_after = frozen_isolation_snapshot()
    isolation_unchanged = isolation_before == isolation_after
    if not isolation_unchanged: raise BaselineIdentityStop("STOP_R28_OR_R43A_FROZEN_LINE_MUTATION")
    summary = summary_payload(feature_value_hash, predictions, primary, primary_quintiles, robustness,
                              folds, fold_flags, secondary, fit_counts, isolation_unchanged)
    summary.update({
        "CREATED_AT_UTC": created_at, "R43B_PREREGISTRATION_SHA256": prereg_hash,
        "MODEL_CONFIG_CHANGED_AFTER_RESULT": False, "RESEARCH_CHOICE_CHANGED_AFTER_RESULT": False,
        "BRANCH": subprocess.check_output(["git", "branch", "--show-current"], cwd=REPO, text=True).strip(),
        "HEAD": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        "SOURCE_SHA256": source_hashes, "FROZEN_ISOLATION_TREE_SHA256": isolation_before,
    })
    acceptance = {
        "CONTRACT_ID": "FAST3_R43B_FUTURE_FEATURE_FAMILY_INCREMENTAL_ACCEPTANCE_R1",
        "R43B_PREREGISTRATION_SHA256": prereg_hash,
        "BASELINE_REFERENCE": {
            head: {
                "OOF_SPEARMAN": summary[f"{head}_PRIMARY_OOF_SPEARMAN"],
                "Q5_MINUS_Q1_REALIZED_Y_ECON_MEAN": summary[f"{head}_Q5_MINUS_Q1_REALIZED_Y_ECON_MEAN"],
            } for head in ("UP", "DOWN")
        },
        "FUTURE_FAMILY_MIN_DELTA_SPEARMAN": .02,
        "FUTURE_FAMILY_MIN_DELTA_Q5_Q1": .0005,
        "NO_MAJORITY_FOLD_DEGRADATION": True,
        "DIRECTION_MUST_BE_EXPLICIT": True,
        "SECONDARY_TARGET_IS_SUPPORTING_ONLY": True,
        "PRIMARY_INCREMENTAL_ACCEPTANCE": (
            "for at least one explicitly named direction: delta Spearman>=0.02 AND delta Q5-Q1>=0.0005 "
            "AND degraded common-evaluable folds <=floor(common-evaluable fold count/2)"
        ),
    }
    schedule.to_csv(STAGING_ROOT / "FAST3_R43B_OOF_FOLD_SCHEDULE.csv", index=False)
    predictions.to_parquet(STAGING_ROOT / "FAST3_R43B_OOF_PREDICTIONS.parquet", index=False)
    model_manifest.to_csv(STAGING_ROOT / "FAST3_R43B_MODEL_MANIFEST.csv", index=False)
    primary.to_csv(STAGING_ROOT / "FAST3_R43B_PRIMARY_METRICS.csv", index=False)
    primary_quintiles.to_csv(STAGING_ROOT / "FAST3_R43B_PRIMARY_QUINTILES.csv", index=False)
    robustness.to_csv(STAGING_ROOT / "FAST3_R43B_PRIMARY_TAIL_ROBUSTNESS.csv", index=False)
    folds.to_csv(STAGING_ROOT / "FAST3_R43B_FOLD_STABILITY.csv", index=False)
    secondary.to_csv(STAGING_ROOT / "FAST3_R43B_SECONDARY_METRICS.csv", index=False)
    secondary_quintiles.to_csv(STAGING_ROOT / "FAST3_R43B_SECONDARY_QUINTILES.csv", index=False)
    write_json(STAGING_ROOT / "FAST3_R43B_FUTURE_FAMILY_ACCEPTANCE_CONTRACT.json", acceptance)
    write_json(STAGING_ROOT / "FAST3_R43B_SUMMARY.json", summary)
    report = [
        "# FAST3 R43B Current Information Set Economic Baseline R1", "",
        f"- Classification: `{summary['FAST3_R43B_CLASSIFICATION']}`",
        f"- Decision: `{summary['FAST3_R43B_DECISION']}`",
        f"- Model fits: `{summary['MODEL_FIT_COUNT']}` (OOF only; no full-sample refit)", "",
        "The baseline uses exactly the frozen R28 14-feature set, one HGB family, five expanding chronological validation folds, and the exact R43A targets. No feature, target, model-family, hyperparameter, or economic threshold search occurred.", "",
        "## Terminal summary", "", "```text", render_terminal(summary), "```", "",
    ]
    (STAGING_ROOT / "FAST3_R43B_REPORT.md").write_text("\n".join(report), encoding="utf-8")
    AUTHORITATIVE_ROOT.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(STAGING_ROOT), str(AUTHORITATIVE_ROOT))
    summary["ARTIFACT_ROOT"] = str(AUTHORITATIVE_ROOT)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--execute", action="store_true"); args = parser.parse_args()
    if not args.execute:
        print("FAST3_R43B_STATUS=READY_REQUIRES_EXECUTE"); return 0
    try: summary = execute()
    except BaselineIdentityStop as exc:
        print("FAST3_R43B_STATUS=STOP\nFAST3_R43B_CLASSIFICATION=D_INVALID_BASELINE_IDENTITY")
        print(f"FAST3_R43B_DECISION={exc}"); return 2
    except OOFContractStop as exc:
        print("FAST3_R43B_STATUS=STOP\nFAST3_R43B_CLASSIFICATION=E_INVALID_OOF_OR_TARGET_CONTRACT")
        print(f"FAST3_R43B_DECISION={exc}"); return 2
    print(render_terminal(summary)); print(f"ARTIFACT_ROOT={summary['ARTIFACT_ROOT']}"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
