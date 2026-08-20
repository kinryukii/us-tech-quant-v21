#!/usr/bin/env python
"""FAST3 R35 authoritative frozen deployment model materialization."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor


REPO_ROOT = Path(r"D:\us-tech-quant")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
R33_CLOSEOUT = RESULTS_ROOT / "frozen/fast3/r34_frozen_probability_risk_prospective_20260810T072428Z/FAST3_R33_CLOSEOUT_CONTRACT_R1.json"
R33_CLOSEOUT_SHA256 = "9763c4f775940eb5a1b51fc48b4f4e002d2740c8db06e369531a5ae6a31a078b"
R32A_ROOT = RESULTS_ROOT / "frozen/fast3/r32a_full_universe_20260810T120000Z"
R32A_PREREG = R32A_ROOT / "FAST3_R32A_R32B_PREREGISTRATION.json"
R32A_LABEL_MANIFEST = R32A_ROOT / "FAST3_R32A_FULL_UNIVERSE_LABEL_MANIFEST_R1.json"
R32B_SUMMARY = RESULTS_ROOT / "frozen/fast3/r32b_full_universe_20260810T160000Z/FAST3_R32B_SUMMARY.json"
T5_CONTRACT = RESULTS_ROOT / "frozen/fast3/r33b_conditional_loss_severity_20260810T200000Z/FAST3_R33_T5_CONDITIONAL_LOSS_SEVERITY_CONTRACT_R1.json"
T6_CONTRACT = RESULTS_ROOT / "frozen/fast3/r33d_conditional_gain_magnitude_20260811T000000Z/FAST3_R33D_T6_CONDITIONAL_GAIN_CONTRACT_R1.json"
FEATURE_MANIFEST = RESULTS_ROOT / "frozen/fast3/r30b_factor_expansion_20260809T140000Z/FAST3_R30B_EXPANDED_FEATURE_MANIFEST_R1.json"
R32A_RUNNER = REPO_ROOT / "fast3/scripts/run/fast3_r32a_full_universe_economic_label_audit.py"
R32B_RUNNER = REPO_ROOT / "fast3/scripts/run/fast3_r32b_full_universe_economic_baseline_training.py"
R33B_RUNNER = REPO_ROOT / "fast3/scripts/run/fast3_r33b_conditional_loss_severity_learning.py"
R33D_RUNNER = REPO_ROOT / "fast3/scripts/run/fast3_r33d_t6_conditional_gain_magnitude_validation.py"
R30A_RUNNER = REPO_ROOT / "fast3/scripts/run/fast3_r30a_economic_target_baseline_training.py"

EXPECTED_SHA256 = {
    R33_CLOSEOUT: R33_CLOSEOUT_SHA256,
    R32A_PREREG: "0d0c2a8c281009b1ebb335994e0a0b07f958eb4ab1513ee7f18b872a74423a61",
    R32A_LABEL_MANIFEST: "12356e0dd8d75c8cefa4233900942e73dffd5ae0688d685be6915d99ac38cc29",
    R32B_SUMMARY: "9e09d7b0561d934fd145a2a291c6c0e25a75ee7f3fa8415a478067a272c55bb1",
    T5_CONTRACT: "d491b24943fc484577449b375a1bed3f34aa122773c0f007e674951193d1db3a",
    T6_CONTRACT: "6b04a42e0489fb94921724b025f84162d03cf1e5c91df3546af837899874e3e2",
    FEATURE_MANIFEST: "248c4d1eabcbcee545ffc95f5f366390889c13199ec90d84d5bbd0f6332f4718",
    R32A_RUNNER: "e3fe20e10bfeef8bd48635514e9ce9eda23d4aebc73274ade708992c8e50caf3",
    R32B_RUNNER: "a55d3e719e453f789704f96ea304ac974f3521664ebb9801fafa2af308b669a0",
    R33B_RUNNER: "d7843078b656f1d7353081579e527057a4604e804720191939b1ddfcbbab55d9",
    R33D_RUNNER: "45bff66eb918e005414ae3c362f71f1a10dd13e785ad1d187d6157b3c1aae68b",
    R30A_RUNNER: "38fee3ba5b4e77b066b7141683e03224b43a6cef09415d2736fa35b623bb91b7",
}
AUTHORITATIVE_HEADS = ("T1", "T5", "T6")
EXPECTED_FIT_COUNTS = {"T1": 2, "T5": 2, "T6": 2}
FEATURE_MANIFEST_SHA256 = EXPECTED_SHA256[FEATURE_MANIFEST]
TRUE_HOLDOUT_START = pd.Timestamp("2025-02-01T05:00:00Z")
RUN_ID_TIMESTAMP_SEMANTICS = "REAL_UTC_WALL_CLOCK"
ALLOWED_STATUSES = {
    "PASS", "STOPPED_AUTHORITATIVE_RESEARCH_CONTRACT_NOT_RECOVERABLE",
    "STOPPED_AUTHORITATIVE_DEPLOYMENT_FIT_FAILED", "STOPPED_DATA_OR_LINEAGE_INTEGRITY",
    "STOPPED_STORAGE_CONTRACT_VIOLATION", "STOPPED_PREREGISTRATION_ORDER_VIOLATION",
    "STOPPED_RESEARCH_CHOICE_CHANGED", "STOPPED_ANTI_BLOAT_VIOLATION",
}


class R35Stop(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (Path, pd.Timestamp, datetime)):
        return str(value)
    if pd.isna(value):
        return None
    raise TypeError(type(value).__name__)


def stable_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, default=json_default, allow_nan=False) + "\n").encode("utf-8")


def write_json(path: Path, value: Any) -> None:
    path.write_bytes(stable_json(value))


def import_file(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise R35Stop("STOPPED_AUTHORITATIVE_RESEARCH_CONTRACT_NOT_RECOVERABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_storage() -> None:
    if REPO_ROOT != Path(r"D:\us-tech-quant") or RESULTS_ROOT != Path(r"D:\us-tech-quant-results"):
        raise R35Stop("STOPPED_STORAGE_CONTRACT_VIOLATION")
    if not REPO_ROOT.is_dir() or not RESULTS_ROOT.is_dir() or REPO_ROOT == RESULTS_ROOT:
        raise R35Stop("STOPPED_STORAGE_CONTRACT_VIOLATION")


def feature_order_sha256(features: tuple[str, ...]) -> str:
    return sha256_bytes(("\n".join(features) + "\n").encode("utf-8"))


def git_value(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True).strip()


def recover_contracts() -> tuple[dict[str, Any], tuple[str, ...], Any, Any, Any, Any]:
    for path, expected in EXPECTED_SHA256.items():
        if not path.is_file() or sha256(path) != expected:
            raise R35Stop("STOPPED_AUTHORITATIVE_RESEARCH_CONTRACT_NOT_RECOVERABLE")
    closeout = read_json(R33_CLOSEOUT)
    t1_prereg, t5, t6 = read_json(R32A_PREREG), read_json(T5_CONTRACT), read_json(T6_CONTRACT)
    r32b_summary = read_json(R32B_SUMMARY)
    feature_manifest = read_json(FEATURE_MANIFEST)
    features = tuple(t1_prereg.get("FEATURES", ()))
    if (
        closeout.get("R33_RESEARCH_PHASE_STATUS") != "CLOSED"
        or closeout.get("AUTHORITATIVE_HEAD_SET") != list(AUTHORITATIVE_HEADS)
        or closeout.get("T7_STATUS") != "REJECTED_REDUNDANT_WITH_T5"
        or closeout.get("T8_PLUS_STATUS") != "PROHIBITED"
        or closeout.get("FURTHER_HEAD_EXPANSION_ALLOWED") is not False
        or t1_prereg.get("STATUS") != "PREREGISTERED_NOT_EXECUTED"
        or t1_prereg.get("UNIVERSE") != "full pre-score eligible TRAIN+DEVELOPMENT economic universe"
        or t1_prereg.get("FEATURE_MANIFEST_SHA256") != FEATURE_MANIFEST_SHA256
        or t1_prereg.get("MODEL_FAMILY") != ["HistGradientBoostingClassifier", "HistGradientBoostingRegressor"]
        or t1_prereg.get("TARGETS") != ["T1", "T2"]
        or r32b_summary.get("FINAL_CONFIRMATION_DATA_USED") is not False
        or t5.get("TARGET_NAME") != "T5_CONDITIONAL_LOSS_SEVERITY"
        or t5.get("TRAINING_ELIGIBILITY") != "label_valid == true AND net20 < 0"
        or t5.get("FEATURE_NAMES") != list(features)
        or t5.get("FEATURE_MANIFEST_SHA256") != FEATURE_MANIFEST_SHA256
        or t5.get("MODEL_FAMILY") != "HistGradientBoostingRegressor independent UP/DOWN"
        or t6.get("TARGET_NAME") != "T6_CONDITIONAL_GAIN_MAGNITUDE"
        or t6.get("TRAINING_ELIGIBILITY") != "label_valid == true AND net20 > 0"
        or t6.get("FEATURE_NAMES") != list(features)
        or t6.get("FEATURE_MANIFEST_SHA256") != FEATURE_MANIFEST_SHA256
        or t6.get("MODEL_FAMILY") != "HistGradientBoostingRegressor independent UP/DOWN"
        or feature_manifest.get("arms", {}).get("ARM_ALL") != list(features)
        or len(features) != 29
    ):
        raise R35Stop("STOPPED_AUTHORITATIVE_RESEARCH_CONTRACT_NOT_RECOVERABLE")
    r32b = import_file(R32B_RUNNER, "r35_r32b")
    r33b = import_file(R33B_RUNNER, "r35_r33b")
    r33d = import_file(R33D_RUNNER, "r35_r33d")
    r30a = import_file(R30A_RUNNER, "r35_r30a")
    if (
        r30a.HGB_PARAMS != t5["HGB_PARAMETERS"] or r30a.HGB_PARAMS != t6["HGB_PARAMETERS"]
        or r30a.HGB_PARAMS.get("random_state") != 1729
        or tuple(r30a.CATEGORICAL) != ("symbol_code", "session_code")
        or len(r30a.ECONOMIC_FOLDS) != 5
    ):
        raise R35Stop("STOPPED_AUTHORITATIVE_RESEARCH_CONTRACT_NOT_RECOVERABLE")
    source = {
        "T1": {
            "source_research_stage": "R32B_FULL_UNIVERSE_T1",
            "source_preregistration_sha256": EXPECTED_SHA256[R32A_PREREG],
            "source_contract_sha256": EXPECTED_SHA256[R32B_SUMMARY],
            "model_family": "HistGradientBoostingClassifier independent UP/DOWN",
            "hyperparameters": r30a.HGB_PARAMS, "seed": 1729,
            "target_definition": "T1_POSITIVE_NET20 = 1[net20 > 0]",
            "target_transform": "NONE_BINARY_INDICATOR", "training_eligibility": "all label_valid rows",
        },
        "T5": {
            "source_research_stage": "R33B_CONDITIONAL_LOSS_SEVERITY",
            "source_preregistration_sha256": EXPECTED_SHA256[T5_CONTRACT],
            "source_contract_sha256": EXPECTED_SHA256[T5_CONTRACT],
            "model_family": t5["MODEL_FAMILY"], "hyperparameters": t5["HGB_PARAMETERS"], "seed": 1729,
            "target_definition": t5["FORMULA"], "target_transform": t5["TRANSFORMATION"],
            "training_eligibility": t5["TRAINING_ELIGIBILITY"],
        },
        "T6": {
            "source_research_stage": "R33D_CONDITIONAL_GAIN_MAGNITUDE",
            "source_preregistration_sha256": t6["R33C_T6_PREREGISTRATION_SHA256"],
            "source_contract_sha256": EXPECTED_SHA256[T6_CONTRACT],
            "model_family": t6["MODEL_FAMILY"], "hyperparameters": t6["HGB_PARAMETERS"], "seed": 1729,
            "target_definition": t6["TARGET_FORMULA"], "target_transform": "NATURAL_LOG1P_GAIN_WINNERS_ONLY",
            "training_eligibility": t6["TRAINING_ELIGIBILITY"],
        },
    }
    for record in source.values():
        record.update({
            "feature_manifest_sha256": FEATURE_MANIFEST_SHA256,
            "feature_column_order_sha256": feature_order_sha256(features),
            "feature_count": len(features), "feature_column_order": list(features),
            "direction_handling": "independent UP/DOWN deployment fits",
            "sample_weighting": "none", "missing_value_handling": "native HistGradientBoosting NaN handling; no imputer/scaler and no incomplete-row deletion",
            "expected_fit_count": 2,
        })
    return source, features, r32b, r33b, r33d, r30a


def construct_training_dataset(r32b: Any, r33b: Any, r33d: Any, features: tuple[str, ...]) -> pd.DataFrame:
    _, manifest, authoritative_features = r32b.guard_authority()
    if tuple(authoritative_features) != features:
        raise R35Stop("STOPPED_AUTHORITATIVE_RESEARCH_CONTRACT_NOT_RECOVERABLE")
    dataset, _, _, _ = r32b.construct_dataset(manifest, features)
    dataset["actual_t5"] = r33b.derive_t5(dataset.raw_net20)
    dataset["actual_t6"] = r33d.derive_t6(dataset.raw_net20)
    if (
        len(dataset) != 1_456_595 or dataset.candidate_id.duplicated().any()
        or set(dataset["head"]) != {"UP", "DOWN"}
        or int(dataset.raw_net20.lt(0).sum()) != 680_402
        or int(dataset.raw_net20.gt(0).sum()) != 776_193
        or dataset.decision_timestamp_utc.max() >= TRUE_HOLDOUT_START
        or dataset.label_information_end_utc.max() >= TRUE_HOLDOUT_START
        or not dataset.max_feature_timestamp_utc.le(dataset.decision_timestamp_utc).all()
        or np.isinf(dataset[list(features)].to_numpy(dtype=float, copy=False)).any()
    ):
        raise R35Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    return dataset


def stable_population_sha(frame: pd.DataFrame, target: str) -> str:
    digest = hashlib.sha256()
    ordered = frame.sort_values(["candidate_id"], kind="mergesort")
    for row in ordered[["candidate_id", "decision_timestamp_utc", "head", target]].itertuples(index=False, name=None):
        value = float(row[3])
        payload = f"{row[0]}\t{pd.Timestamp(row[1]).isoformat()}\t{row[2]}\t{value.hex()}\n"
        digest.update(payload.encode("utf-8"))
    return digest.hexdigest()


def population_metadata(dataset: pd.DataFrame, source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    populations = {
        "T1": (dataset, "T1_POSITIVE_NET20"),
        "T5": (dataset.loc[dataset.raw_net20.lt(0)], "actual_t5"),
        "T6": (dataset.loc[dataset.raw_net20.gt(0)], "actual_t6"),
    }
    metadata = {}
    for head, (frame, target) in populations.items():
        metadata[head] = {
            "target_column": target, "training_row_count": len(frame),
            "training_start": frame.decision_timestamp_utc.min(), "training_end": frame.decision_timestamp_utc.max(),
            "training_label_information_end": frame.label_information_end_utc.max(),
            "training_population_sha256": stable_population_sha(frame, target),
            "direction_counts": {key: int(value) for key, value in frame.groupby("head", observed=True).size().items()},
        }
        source[head].update(metadata[head])
    if [metadata[key]["training_row_count"] for key in AUTHORITATIVE_HEADS] != [1_456_595, 680_402, 776_193]:
        raise R35Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    return metadata


def preregistration(source: dict[str, Any], created_at: str) -> dict[str, Any]:
    return {
        "CONTRACT_ID": "FAST3_R35_PREREGISTRATION_R1", "STATUS": "FROZEN_BEFORE_FIRST_FIT",
        "TASK": "AUTHORITATIVE_FROZEN_DEPLOYMENT_MODEL_MATERIALIZATION",
        "R33_CLOSEOUT_SHA256": R33_CLOSEOUT_SHA256, "AUTHORITATIVE_HEADS": list(AUTHORITATIVE_HEADS),
        "HEAD_CONTRACTS": source, "EXPECTED_FIT_COUNTS": EXPECTED_FIT_COUNTS,
        "EXPECTED_TOTAL_DEPLOYMENT_FIT_COUNT": sum(EXPECTED_FIT_COUNTS.values()),
        "NEW_FEATURE_ALLOWED": False, "NEW_TARGET_ALLOWED": False, "MODEL_SEARCH_ALLOWED": False,
        "HYPERPARAMETER_SEARCH_ALLOWED": False, "TRAINING_WINDOW_SEARCH_ALLOWED": False,
        "OOF_REBUILD_ALLOWED": False, "FINAL_ALLOWED": False, "PROSPECTIVE_ACTIVATION_ALLOWED": False,
        "ECONOMIC_SCORE_ALLOWED": False, "T7_MODEL_ALLOWED": False, "T8_MODEL_ALLOWED": False,
        "DEPLOYMENT_REFIT_DUE_TO_PERFORMANCE_COUNT": 0,
        "CREATED_AT_UTC": created_at, "RUN_ID_TIMESTAMP_SEMANTICS": RUN_ID_TIMESTAMP_SEMANTICS,
        "RESEARCH_CHOICE_CHANGED_AFTER_FIRST_FIT": False,
    }


def strict_predict(model: Any, frame: pd.DataFrame, features: tuple[str, ...], classifier: bool) -> np.ndarray:
    if tuple(frame.columns) != features:
        raise R35Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    values = model.predict_proba(frame)[:, 1] if classifier else model.predict(frame)
    values = np.asarray(values, dtype=float)
    if not np.isfinite(values).all():
        raise R35Stop("STOPPED_AUTHORITATIVE_DEPLOYMENT_FIT_FAILED")
    return values


def bundle_sha(model_hashes: dict[str, str]) -> str:
    return sha256_bytes("".join(f"{key}:{model_hashes[key]}\n" for key in sorted(model_hashes)).encode("utf-8"))


def fit_and_serialize(
    dataset: pd.DataFrame,
    source: dict[str, Any],
    features: tuple[str, ...],
    frozen_root: Path,
    prereg_path: Path,
    prereg_sha: str,
) -> tuple[dict[str, Any], dict[str, int], int]:
    categorical = [name in ("symbol_code", "session_code") for name in features]
    params = {**next(iter(source.values()))["hyperparameters"], "categorical_features": categorical}
    eligibility = {
        "T1": pd.Series(True, index=dataset.index),
        "T5": dataset.raw_net20.lt(0),
        "T6": dataset.raw_net20.gt(0),
    }
    target = {"T1": "T1_POSITIVE_NET20", "T5": "actual_t5", "T6": "actual_t6"}
    outputs: dict[str, Any] = {}
    counts = {head: 0 for head in AUTHORITATIVE_HEADS}
    sanity_calls = 0
    for head in AUTHORITATIVE_HEADS:
        artifact_paths, artifact_hashes, sanity = {}, {}, {}
        for direction in ("UP", "DOWN"):
            if not prereg_path.is_file() or sha256(prereg_path) != prereg_sha:
                raise R35Stop("STOPPED_PREREGISTRATION_ORDER_VIOLATION")
            mask = eligibility[head] & dataset["head"].eq(direction)
            training = dataset.loc[mask]
            if training.empty:
                raise R35Stop("STOPPED_AUTHORITATIVE_DEPLOYMENT_FIT_FAILED")
            estimator = HistGradientBoostingClassifier(**params) if head == "T1" else HistGradientBoostingRegressor(**params)
            y = training[target[head]].astype(int if head == "T1" else float)
            try:
                estimator.fit(training[list(features)], y)
            except Exception as exc:
                raise R35Stop(f"STOPPED_AUTHORITATIVE_DEPLOYMENT_FIT_FAILED:{head}:{direction}:{type(exc).__name__}:{exc}") from exc
            counts[head] += 1
            path = frozen_root / f"FAST3_{head}_{direction}_DEPLOYMENT_MODEL.joblib"
            joblib.dump(estimator, path, compress=3)
            artifact_paths[direction] = str(path)
            artifact_hashes[direction] = sha256(path)
            fixture = training.sort_values(["decision_timestamp_utc", "candidate_id"], kind="mergesort").head(32)[list(features)]
            first = strict_predict(joblib.load(path), fixture, features, head == "T1")
            second = strict_predict(joblib.load(path), fixture, features, head == "T1")
            sanity_calls += 2
            if not np.array_equal(first, second):
                raise R35Stop("STOPPED_AUTHORITATIVE_DEPLOYMENT_FIT_FAILED")
            sanity[direction] = {
                "fixture_row_count": len(fixture), "repeat_max_abs_difference": float(np.max(np.abs(first - second))),
                "nan_count": int(np.isnan(first).sum()), "inf_count": int(np.isinf(first).sum()),
            }
            del estimator
        outputs[head] = {
            "artifact_paths": artifact_paths, "artifact_sha256s": artifact_hashes,
            "deployment_model_sha256": bundle_sha(artifact_hashes), "sanity": sanity,
        }
    return outputs, counts, sanity_calls


def deployment_contract(head: str, source: dict[str, Any], models: dict[str, Any], source_sha: str) -> dict[str, Any]:
    return {
        "CONTRACT_ID": f"FAST3_{head}_DEPLOYMENT_CONTRACT_R1", "STATUS": "FROZEN_AUTHORITATIVE",
        "head_name": head, "deployment_role": {"T1": "winner probability source", "T5": "conditional loser loss severity", "T6": "conditional winner gain ranking diagnostic only"}[head],
        **source, "serialized_model_paths": models["artifact_paths"], "serialized_model_sha256": models["artifact_sha256s"],
        "deployment_model_sha256": models["deployment_model_sha256"], "actual_fit_count": 2,
        "serialization_format": "joblib compress=3", "serialization_sanity": models["sanity"],
        "code_HEAD": git_value("rev-parse", "HEAD"), "source_file_sha256": source_sha,
        "FINAL_CONFIRMATION_DATA_USED": False, "PROSPECTIVE_ACTIVATION": False,
    }


def print_summary(summary: dict[str, Any]) -> None:
    keys = [
        "FAST3_R35_STATUS", "FAST3_R35_CLASSIFICATION", "FAST3_R35_DECISION",
        "R35_PREREGISTRATION_VERIFIED", "R35_PREREGISTRATION_SHA256",
        "R33_CLOSEOUT_RECONCILIATION_STATUS", "R33_CLOSEOUT_SHA256", "AUTHORITATIVE_HEAD_SET",
    ]
    for head in AUTHORITATIVE_HEADS:
        keys.extend([
            f"{head}_SOURCE_RESEARCH_STAGE", f"{head}_SOURCE_CONTRACT_SHA256", f"{head}_MODEL_FAMILY",
            f"{head}_FEATURE_MANIFEST_SHA256", f"{head}_DEPLOYMENT_TRAINING_POPULATION_SHA256",
            f"{head}_TRAINING_ROW_COUNT", f"{head}_TRAINING_START", f"{head}_TRAINING_END",
            f"{head}_DEPLOYMENT_MODEL_SHA256", f"{head}_DEPLOYMENT_STATUS",
        ])
    keys.extend([
        "EXPECTED_T1_DEPLOYMENT_FIT_COUNT", "EXPECTED_T5_DEPLOYMENT_FIT_COUNT", "EXPECTED_T6_DEPLOYMENT_FIT_COUNT",
        "EXPECTED_TOTAL_DEPLOYMENT_FIT_COUNT", "ACTUAL_T1_DEPLOYMENT_FIT_COUNT",
        "ACTUAL_T5_DEPLOYMENT_FIT_COUNT", "ACTUAL_T6_DEPLOYMENT_FIT_COUNT",
        "ACTUAL_TOTAL_DEPLOYMENT_FIT_COUNT", "DEPLOYMENT_SANITY_PREDICT_CALL_COUNT",
        "DEPLOYMENT_DESERIALIZATION_STATUS", "DETERMINISTIC_REPEAT_PREDICTION_STATUS",
        "FINITE_PREDICTION_STATUS", "R35_DEPLOYMENT_MANIFEST_SHA256", "NEW_HEAD_COUNT",
        "NEW_FEATURE_COUNT", "NEW_TARGET_COUNT", "MODEL_FAMILY_SEARCH_COUNT", "HYPERPARAMETER_SEARCH_COUNT",
        "FEATURE_SEARCH_COUNT", "TARGET_SEARCH_COUNT", "TARGET_TRANSFORM_SEARCH_COUNT",
        "TRAINING_WINDOW_SEARCH_COUNT", "NEW_OOF_PREDICTION_COUNT", "SCIENTIFIC_PERFORMANCE_METRIC_COUNT",
        "P_PROSPECTIVE_CALIBRATION_BUILD_COUNT", "L_PROSPECTIVE_CALIBRATION_BUILD_COUNT",
        "PROSPECTIVE_PREDICT_CALL_COUNT", "PROSPECTIVE_SIGNAL_COUNT", "R34_PROSPECTIVE_CONTRACT_CREATED",
        "R34_PROSPECTIVE_START_CREATED", "ABSOLUTE_EV_CONSTRUCTION_COUNT", "RELATIVE_SCORE_CONSTRUCTION_COUNT",
        "EV_COMBINATION_SEARCH_COUNT", "WEIGHT_SEARCH_COUNT", "THRESHOLD_SEARCH_COUNT",
        "TRADING_SIMULATION_COUNT", "EXECUTION_SIMULATION_COUNT", "POSITION_SIZING_SEARCH_COUNT",
        "BROKER_ACTION_ALLOWED", "T7_MODEL_FIT_COUNT", "T8_MODEL_FIT_COUNT", "FURTHER_HEAD_EXPANSION_ALLOWED",
        "FINAL_CONFIRMATION_DATA_USED", "FINAL_CONFIRMATION_DATA_LOADED", "FINAL_HOLDOUT_INSPECTED",
        "DEPLOYMENT_REFIT_DUE_TO_PERFORMANCE_COUNT", "DEPLOYMENT_MODEL_DUPLICATE_COPY_COUNT",
        "ARTIFACT_BLOAT_GUARD_STATUS", "ANTI_BLOAT_STATUS", "RUN_ID_TIMESTAMP_SEMANTICS",
        "PRIMARY_RESEARCH_INTERPRETATION", "NEXT_STAGE",
    ])
    for key in keys:
        value = summary[key]
        if isinstance(value, bool):
            value = str(value).lower()
        print(f"{key}={value}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        raise R35Stop("USE_--run")
    validate_storage()
    started = datetime.now(timezone.utc)
    run_id = f"r35_authoritative_deployment_models_{started.strftime('%Y%m%dT%H%M%SZ')}"
    frozen_root = RESULTS_ROOT / "frozen/fast3" / run_id
    if frozen_root.exists():
        raise R35Stop("STOPPED_ANTI_BLOAT_VIOLATION")
    source, features, r32b, r33b, r33d, _ = recover_contracts()
    dataset = construct_training_dataset(r32b, r33b, r33d, features)
    metadata = population_metadata(dataset, source)
    frozen_root.mkdir(parents=True)
    prereg_path = frozen_root / "FAST3_R35_PREREGISTRATION_R1.json"
    prereg = preregistration(source, started.isoformat())
    write_json(prereg_path, prereg)
    prereg_sha = sha256(prereg_path)
    if read_json(prereg_path) != json.loads(stable_json(prereg)):
        raise R35Stop("STOPPED_PREREGISTRATION_ORDER_VIOLATION")

    models, actual_counts, sanity_calls = fit_and_serialize(dataset, source, features, frozen_root, prereg_path, prereg_sha)
    if actual_counts != EXPECTED_FIT_COUNTS or sum(actual_counts.values()) != 6:
        raise R35Stop("STOPPED_AUTHORITATIVE_DEPLOYMENT_FIT_FAILED")
    source_sha = sha256(Path(__file__))
    contract_paths, contract_hashes = {}, {}
    for head in AUTHORITATIVE_HEADS:
        path = frozen_root / f"FAST3_{head}_DEPLOYMENT_CONTRACT_R1.json"
        write_json(path, deployment_contract(head, source[head], models[head], source_sha))
        contract_paths[head], contract_hashes[head] = str(path), sha256(path)

    manifest_path = frozen_root / "FAST3_R35_DEPLOYMENT_MANIFEST_R1.json"
    manifest = {
        "CONTRACT_ID": "FAST3_R35_DEPLOYMENT_MANIFEST_R1", "STATUS": "FROZEN_AUTHORITATIVE",
        "R35_preregistration_sha256": prereg_sha, "R33_closeout_sha256": R33_CLOSEOUT_SHA256,
        "git_branch": git_value("branch", "--show-current"), "git_HEAD": git_value("rev-parse", "HEAD"),
        "authoritative_head_set": list(AUTHORITATIVE_HEADS),
        "heads": {head: {
            "deployment_contract_path": contract_paths[head], "deployment_contract_sha256": contract_hashes[head],
            "model_artifacts": models[head]["artifact_paths"], "model_sha256s": models[head]["artifact_sha256s"],
            "deployment_model_sha256": models[head]["deployment_model_sha256"],
            "feature_manifest_sha256": FEATURE_MANIFEST_SHA256,
            "training_population_sha256": metadata[head]["training_population_sha256"],
        } for head in AUTHORITATIVE_HEADS},
        "total_expected_fit_count": 6, "total_actual_fit_count": 6,
        "Final_prohibited": True, "prospective_activation": False, "economic_score_construction": False,
    }
    write_json(manifest_path, manifest)
    manifest_sha = sha256(manifest_path)

    summary_path = frozen_root / "FAST3_R35_SUMMARY.json"
    report_path = frozen_root / "FAST3_R35_REPORT.md"
    summary: dict[str, Any] = {
        "FAST3_R35_STATUS": "PASS", "FAST3_R35_CLASSIFICATION": "A_AUTHORITATIVE_FROZEN_DEPLOYMENT_MODELS_MATERIALIZED",
        "FAST3_R35_DECISION": "AUTHORIZE_R34_PROSPECTIVE_ACTIVATION_RETRY",
        "R35_PREREGISTRATION_VERIFIED": True, "R35_PREREGISTRATION_SHA256": prereg_sha,
        "PREREGISTRATION_EXISTS_BEFORE_FIRST_FIT": True,
        "R33_CLOSEOUT_RECONCILIATION_STATUS": "PASS", "R33_CLOSEOUT_SHA256": R33_CLOSEOUT_SHA256,
        "SOURCE_RESEARCH_CONTRACT_UNIQUELY_IDENTIFIED": True, "AUTHORITATIVE_HEAD_SET": ",".join(AUTHORITATIVE_HEADS),
        "EXPECTED_T1_DEPLOYMENT_FIT_COUNT": 2, "EXPECTED_T5_DEPLOYMENT_FIT_COUNT": 2,
        "EXPECTED_T6_DEPLOYMENT_FIT_COUNT": 2, "EXPECTED_TOTAL_DEPLOYMENT_FIT_COUNT": 6,
        "ACTUAL_T1_DEPLOYMENT_FIT_COUNT": actual_counts["T1"], "ACTUAL_T5_DEPLOYMENT_FIT_COUNT": actual_counts["T5"],
        "ACTUAL_T6_DEPLOYMENT_FIT_COUNT": actual_counts["T6"], "ACTUAL_TOTAL_DEPLOYMENT_FIT_COUNT": sum(actual_counts.values()),
        "DEPLOYMENT_SANITY_PREDICT_CALL_COUNT": sanity_calls, "DEPLOYMENT_DESERIALIZATION_STATUS": "PASS",
        "DETERMINISTIC_REPEAT_PREDICTION_STATUS": "PASS", "FINITE_PREDICTION_STATUS": "PASS",
        "R35_DEPLOYMENT_MANIFEST_SHA256": manifest_sha, "DEPLOYMENT_MANIFEST_PATH": str(manifest_path),
        "PIT_CONTRACT_STATUS": "PASS", "FUTURE_FEATURE_ROW_COUNT": 0, "TRAINING_LABEL_LEAKAGE_ROW_COUNT": 0,
        "PROSPECTIVE_DATA_USED_FOR_TRAINING": False, "POST_R33_RESEARCH_DATA_USED_FOR_TRAINING": False,
        "NEW_HEAD_COUNT": 0, "NEW_FEATURE_COUNT": 0, "REMOVED_FEATURE_COUNT": 0, "NEW_TARGET_COUNT": 0,
        "AUTHORITATIVE_DEPLOYMENT_HEAD_COUNT": 3, "MODEL_FAMILY_SEARCH_COUNT": 0,
        "HYPERPARAMETER_SEARCH_COUNT": 0, "FEATURE_SEARCH_COUNT": 0, "TARGET_SEARCH_COUNT": 0,
        "TARGET_TRANSFORM_SEARCH_COUNT": 0, "TRAINING_WINDOW_SEARCH_COUNT": 0, "SEED_SEARCH_COUNT": 0,
        "EARLY_STOPPING_SEARCH_COUNT": 0, "NEW_OOF_PREDICTION_COUNT": 0, "NEW_CV_SPLIT_COUNT": 0,
        "CV_SEARCH_COUNT": 0, "SCIENTIFIC_PERFORMANCE_METRIC_COUNT": 0,
        "P_PROSPECTIVE_CALIBRATION_BUILD_COUNT": 0, "L_PROSPECTIVE_CALIBRATION_BUILD_COUNT": 0,
        "PROSPECTIVE_PREDICT_CALL_COUNT": 0, "PROSPECTIVE_SIGNAL_COUNT": 0,
        "R34_PROSPECTIVE_CONTRACT_CREATED": False, "R34_PROSPECTIVE_START_CREATED": False,
        "ABSOLUTE_EV_CONSTRUCTION_COUNT": 0, "RELATIVE_SCORE_CONSTRUCTION_COUNT": 0,
        "EV_COMBINATION_SEARCH_COUNT": 0, "SCORE_FORMULA_SEARCH_COUNT": 0,
        "WEIGHT_SEARCH_COUNT": 0, "THRESHOLD_SEARCH_COUNT": 0,
        "TRADING_SIMULATION_COUNT": 0, "EXECUTION_SIMULATION_COUNT": 0,
        "POSITION_SIZING_SEARCH_COUNT": 0, "BROKER_ACTION_ALLOWED": False,
        "T7_MODEL_FIT_COUNT": 0, "T7_MODEL_CREATED": False, "T8_MODEL_FIT_COUNT": 0,
        "T8_MODEL_CREATED": False, "FURTHER_HEAD_EXPANSION_ALLOWED": False,
        "FINAL_CONFIRMATION_DATA_USED": False, "FINAL_CONFIRMATION_DATA_LOADED": False,
        "FINAL_HOLDOUT_INSPECTED": False, "FINAL_HOLDOUT_ROW_COUNT": 0,
        "DEPLOYMENT_REFIT_DUE_TO_PERFORMANCE_COUNT": 0, "DEPLOYMENT_MODEL_DUPLICATE_COPY_COUNT": 0,
        "RESEARCH_CHOICE_CHANGED_AFTER_FIRST_FIT": False, "ARTIFACT_BLOAT_GUARD_STATUS": "PASS",
        "ANTI_BLOAT_STATUS": "PASS", "RUN_ID_TIMESTAMP_SEMANTICS": RUN_ID_TIMESTAMP_SEMANTICS,
        "PRIMARY_RESEARCH_INTERPRETATION": "AUTHORITATIVE_DEPLOYMENT_MODELS_MATERIALIZED_WITHOUT_NEW_RESEARCH_CHOICE",
        "NEXT_STAGE": "R34R_FROZEN_PROSPECTIVE_ACTIVATION", "RUN_ID": run_id,
        "RUN_STARTED_AT_UTC": started.isoformat(), "REPORT_PATH": str(report_path), "SUMMARY_JSON_PATH": str(summary_path),
    }
    for head in AUTHORITATIVE_HEADS:
        prefix = head
        summary.update({
            f"{prefix}_SOURCE_RESEARCH_STAGE": source[head]["source_research_stage"],
            f"{prefix}_SOURCE_CONTRACT_SHA256": source[head]["source_contract_sha256"],
            f"{prefix}_MODEL_FAMILY": source[head]["model_family"],
            f"{prefix}_FEATURE_MANIFEST_SHA256": FEATURE_MANIFEST_SHA256,
            f"{prefix}_RESEARCH_FEATURE_MANIFEST_SHA256": FEATURE_MANIFEST_SHA256,
            f"{prefix}_DEPLOYMENT_FEATURE_MANIFEST_SHA256": FEATURE_MANIFEST_SHA256,
            f"{prefix}_FEATURE_MANIFEST_EXACT_MATCH": True,
            f"{prefix}_DEPLOYMENT_TRAINING_POPULATION_SHA256": metadata[head]["training_population_sha256"],
            f"{prefix}_TRAINING_ROW_COUNT": metadata[head]["training_row_count"],
            f"{prefix}_TRAINING_START": metadata[head]["training_start"],
            f"{prefix}_TRAINING_END": metadata[head]["training_end"],
            f"{prefix}_DEPLOYMENT_MODEL_SHA256": models[head]["deployment_model_sha256"],
            f"{prefix}_DEPLOYMENT_STATUS": "PASS",
            f"{prefix}_DEPLOYMENT_CONTRACT_PATH": contract_paths[head],
            f"{prefix}_DEPLOYMENT_CONTRACT_SHA256": contract_hashes[head],
        })
    write_json(summary_path, summary)
    report_path.write_text(f"""# FAST3 R35 — Authoritative Deployment Model Materialization

`PASS`: six deterministic deployment submodels were fit exactly once from the frozen recipes (T1/T5/T6 × UP/DOWN), serialized with joblib, deserialized twice, and produced bitwise-identical finite fixture predictions.

Training used only the frozen full TRAIN+DEVELOPMENT label universe ending {dataset.decision_timestamp_utc.max()}, with label maturity ending {dataset.label_information_end_utc.max()}. No Final/prospective rows, OOF rebuild, scientific performance metric, calibration, economic score, threshold, or trading action was used.
""", encoding="utf-8")
    if sha256(prereg_path) != prereg_sha or sha256(R33_CLOSEOUT) != R33_CLOSEOUT_SHA256:
        raise R35Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    print_summary(summary)
    print(f"DEPLOYMENT_MANIFEST_PATH={manifest_path}")
    print(f"REPORT_PATH={report_path}")
    print(f"SUMMARY_JSON_PATH={summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
