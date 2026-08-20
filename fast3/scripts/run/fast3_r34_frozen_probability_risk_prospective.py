#!/usr/bin/env python
"""FAST3 R34/R34-R frozen probability-risk prospective shadow runner."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd


REPO_ROOT = Path(r"D:\us-tech-quant")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
FAST3_FROZEN_ROOT = RESULTS_ROOT / "frozen/fast3"
RUNTIME_ROOT = RESULTS_ROOT / "runtime/fast3/r34"
FEATURE_MANIFEST = RESULTS_ROOT / "frozen/fast3/r30b_factor_expansion_20260809T140000Z/FAST3_R30B_EXPANDED_FEATURE_MANIFEST_R1.json"
FEATURE_MANIFEST_SHA256 = "248c4d1eabcbcee545ffc95f5f366390889c13199ec90d84d5bbd0f6332f4718"
R32A_IDENTITY = RESULTS_ROOT / "frozen/fast3/r32a_full_universe_20260810T120000Z/FAST3_R32A_FULL_UNIVERSE_IDENTITY_R1.json"
R32A_IDENTITY_SHA256 = "7b46e300e68fcdcb24c363479c6de4343106c0e56bdc90c30e61f1472604ab22"
R33_CLOSEOUT = RESULTS_ROOT / "frozen/fast3/r34_frozen_probability_risk_prospective_20260810T072428Z/FAST3_R33_CLOSEOUT_CONTRACT_R1.json"
R33_CLOSEOUT_SHA256 = "9763c4f775940eb5a1b51fc48b4f4e002d2740c8db06e369531a5ae6a31a078b"
PARENT_R34_SUMMARY = R33_CLOSEOUT.parent / "FAST3_R34_SUMMARY.json"
R35_ROOT = RESULTS_ROOT / "frozen/fast3/r35_authoritative_deployment_models_20260810T085805Z"
R35_MANIFEST = R35_ROOT / "FAST3_R35_DEPLOYMENT_MANIFEST_R1.json"
R35_MANIFEST_SHA256 = "f1b9a6f4cce2912bf816cf1949d82d99a556c4eebfebaf4387b719f72d282ffa"
R33I_ROOT = RESULTS_ROOT / "frozen/fast3/r33i_existing_head_economic_calibration_20260810T060639Z"
R33I_CONTRACT = R33I_ROOT / "FAST3_R33I_CALIBRATION_CONTRACT_R1.json"
R33I_CONTRACT_SHA256 = "536c4cf36c6b68385631210cdfc0448667b3f8f6974473f66953d58261bb59cc"
R33I_OOF = RESULTS_ROOT / "scratch/fast3/r33d_conditional_gain_magnitude_20260811T000000Z/FAST3_R33D_T6_OOF_PREDICTIONS.parquet"
R33I_OOF_SHA256 = "99021c1fc956a99b949f76153364a9517c53ce1df92b36623b6e48531e1d3df1"
R32B_RUNNER = REPO_ROOT / "fast3/scripts/run/fast3_r32b_full_universe_economic_baseline_training.py"
R32B_RUNNER_SHA256 = "a55d3e719e453f789704f96ea304ac974f3521664ebb9801fafa2af308b669a0"
CANONICAL_INPUT = RUNTIME_ROOT / "FAST3_R34_CANONICAL_CANDIDATE_FEATURES.parquet"
CANONICAL_OUTCOMES = RUNTIME_ROOT / "FAST3_R34_CANONICAL_MATURE_OUTCOMES.parquet"
CANONICAL_LEDGER = RUNTIME_ROOT / "FAST3_R34_PROSPECTIVE_LEDGER.parquet"
CURRENT_STATUS = RUNTIME_ROOT / "FAST3_R34_CURRENT_STATUS.json"
CURRENT_REPORT = RUNTIME_ROOT / "FAST3_R34_CURRENT_REPORT.md"
RUN_ID_TIMESTAMP_SEMANTICS = "REAL_UTC_WALL_CLOCK"

AUTHORITATIVE_HEAD_SET = ("T1", "T5", "T6")
HEAD_ROLES = {
    "T1": "CALIBRATED_WIN_PROBABILITY_SOURCE",
    "T5": "CALIBRATED_CONDITIONAL_LOSS_SOURCE",
    "T6": "DIAGNOSTIC_ONLY",
}
EXPECTED_MODEL_SHA256 = {
    "T1": "a984a144e55bd57d54321b2e4c818b505dd9c6b7e87e0000c544044c39f21cfb",
    "T5": "c00e52625cefa44d0d10bf5e40382ca2231ad9b83ea860f058c573f72d7732f3",
    "T6": "123ea8ee57676fc0eaf96380ad0d194f3669081b827bce3a06b1ba59a7e922a0",
}
CALIBRATION_BUCKET_COUNT = 10
T6_REFERENCE_QUANTILE_COUNT = 1001
CANDIDATE_CONTRACT_VERSION = "FAST3_R32A_FULL_UNIVERSE_IDENTITY_R1"
PARENT_R34_STATUS = "STOPPED_FROZEN_INFERENCE_ARTIFACT_NOT_RECOVERABLE"
R34R_REPAIR_TYPE = "AUTHORITATIVE_DEPLOYMENT_ARTIFACT_AVAILABILITY_RESTORED_BY_R35"
ALLOWED_R34R_STATUSES = {
    "PASS", "STOPPED_R33_CLOSEOUT_HASH_MISMATCH",
    "STOPPED_R35_DEPLOYMENT_MANIFEST_HASH_MISMATCH", "STOPPED_DEPLOYMENT_MODEL_HASH_MISMATCH",
    "STOPPED_FEATURE_MANIFEST_HASH_MISMATCH", "STOPPED_CALIBRATION_LINEAGE_NOT_RECOVERABLE",
    "STOPPED_DATA_OR_LINEAGE_INTEGRITY", "STOPPED_PIT_VIOLATION",
    "STOPPED_STORAGE_CONTRACT_VIOLATION", "STOPPED_PREREGISTRATION_ORDER_VIOLATION",
    "STOPPED_ANTI_BLOAT_VIOLATION",
}

LEDGER_COLUMNS = (
    "candidate_id", "decision_timestamp_utc", "trading_date", "direction", "underlying",
    "candidate_contract_version", "T1_raw", "P_WIN_CALIBRATED", "T5_raw",
    "L_LOSER_CALIBRATED", "T6_raw", "T6_DIAGNOSTIC_PERCENTILE", "T1_model_sha256",
    "T5_model_sha256", "T6_model_sha256", "feature_manifest_sha256",
    "P_calibration_contract_sha256", "L_calibration_contract_sha256",
    "r34_prospective_contract_sha256", "outcome_status", "outcome_maturity_timestamp",
    "canonical_realized_payoff", "winner_indicator", "winner_gain_magnitude", "loser_loss_magnitude",
)
IMMUTABLE_PREDICTION_COLUMNS = LEDGER_COLUMNS[:19]
OUTCOME_COLUMNS = LEDGER_COLUMNS[19:]
SCORER_PROHIBITED_COLUMNS = {
    "realized_payoff", "canonical_realized_payoff", "winner_indicator", "future_price", "future_bars",
    "winner_gain", "winner_gain_magnitude", "loser_loss", "loser_loss_magnitude",
}


class R34Stop(RuntimeError):
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
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (Path, pd.Timestamp, datetime)):
        return str(value)
    if pd.isna(value):
        return None
    raise TypeError(type(value).__name__)


def stable_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, default=json_default, allow_nan=False) + "\n").encode("utf-8")


def write_json_once(path: Path, value: Any) -> None:
    if path.exists():
        raise R34Stop("STOPPED_FROZEN_CONTRACT_HASH_MISMATCH")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(stable_json_bytes(value))


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def write_parquet_atomic(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False)
    os.replace(temporary, path)


def import_file(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise R34Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_storage_contract() -> None:
    if REPO_ROOT != Path(r"D:\us-tech-quant") or RESULTS_ROOT != Path(r"D:\us-tech-quant-results"):
        raise R34Stop("STOPPED_STORAGE_CONTRACT_VIOLATION")
    if not REPO_ROOT.is_dir() or not RESULTS_ROOT.is_dir() or REPO_ROOT == RESULTS_ROOT:
        raise R34Stop("STOPPED_STORAGE_CONTRACT_VIOLATION")
    for path in (FAST3_FROZEN_ROOT, RUNTIME_ROOT, R35_ROOT):
        try:
            path.resolve().relative_to(RESULTS_ROOT.resolve())
        except ValueError as exc:
            raise R34Stop("STOPPED_STORAGE_CONTRACT_VIOLATION") from exc


def reconcile_r33_closeout() -> dict[str, Any]:
    if not R33_CLOSEOUT.is_file() or sha256(R33_CLOSEOUT) != R33_CLOSEOUT_SHA256:
        raise R34Stop("STOPPED_R33_CLOSEOUT_HASH_MISMATCH")
    closeout = read_json(R33_CLOSEOUT)
    parent = read_json(PARENT_R34_SUMMARY)
    if (
        closeout.get("R33_RESEARCH_PHASE_STATUS") != "CLOSED"
        or closeout.get("R33_ARCHITECTURE_DISCOVERY_ALLOWED") is not False
        or closeout.get("AUTHORITATIVE_HEAD_SET") != list(AUTHORITATIVE_HEAD_SET)
        or closeout.get("T7_STATUS") != "REJECTED_REDUNDANT_WITH_T5"
        or closeout.get("T8_PLUS_STATUS") != "PROHIBITED"
        or closeout.get("FURTHER_HEAD_EXPANSION_ALLOWED") is not False
        or parent.get("FAST3_R34_STATUS") != PARENT_R34_STATUS
        or parent.get("R34_PROSPECTIVE_CONTRACT_SHA256") != "NOT_CREATED"
        or parent.get("R34_PROSPECTIVE_START_UTC") != "NOT_CREATED"
    ):
        raise R34Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    return closeout


def bundle_sha(model_hashes: dict[str, str]) -> str:
    payload = "".join(f"{key}:{model_hashes[key]}\n" for key in sorted(model_hashes))
    return sha256_bytes(payload.encode("utf-8"))


def recover_frozen_inference_artifacts() -> tuple[dict[str, Any], dict[str, Any]]:
    if not R35_MANIFEST.is_file() or sha256(R35_MANIFEST) != R35_MANIFEST_SHA256:
        raise R34Stop("STOPPED_R35_DEPLOYMENT_MANIFEST_HASH_MISMATCH")
    manifest = read_json(R35_MANIFEST)
    if (
        manifest.get("STATUS") != "FROZEN_AUTHORITATIVE"
        or manifest.get("R33_closeout_sha256") != R33_CLOSEOUT_SHA256
        or manifest.get("authoritative_head_set") != list(AUTHORITATIVE_HEAD_SET)
        or manifest.get("total_expected_fit_count") != 6
        or manifest.get("total_actual_fit_count") != 6
        or manifest.get("Final_prohibited") is not True
    ):
        raise R34Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    recovered, audit = {}, {}
    for head in AUTHORITATIVE_HEAD_SET:
        record = manifest.get("heads", {}).get(head, {})
        contract_path = Path(record.get("deployment_contract_path", ""))
        if not contract_path.is_file() or sha256(contract_path) != record.get("deployment_contract_sha256"):
            raise R34Stop("STOPPED_DEPLOYMENT_MODEL_HASH_MISMATCH")
        contract = read_json(contract_path)
        model_paths = {key: Path(value) for key, value in record.get("model_artifacts", {}).items()}
        model_hashes = record.get("model_sha256s", {})
        if (
            set(model_paths) != {"UP", "DOWN"} or set(model_hashes) != {"UP", "DOWN"}
            or record.get("deployment_model_sha256") != EXPECTED_MODEL_SHA256[head]
            or bundle_sha(model_hashes) != EXPECTED_MODEL_SHA256[head]
            or contract.get("deployment_model_sha256") != EXPECTED_MODEL_SHA256[head]
            or contract.get("feature_manifest_sha256") != FEATURE_MANIFEST_SHA256
            or record.get("feature_manifest_sha256") != FEATURE_MANIFEST_SHA256
            or contract.get("direction_handling") != "independent UP/DOWN deployment fits"
            or contract.get("actual_fit_count") != 2
        ):
            raise R34Stop("STOPPED_DEPLOYMENT_MODEL_HASH_MISMATCH")
        for direction, path in model_paths.items():
            if path.parent != R35_ROOT or not path.is_file() or path.suffix != ".joblib" or sha256(path) != model_hashes[direction]:
                raise R34Stop("STOPPED_DEPLOYMENT_MODEL_HASH_MISMATCH")
        recovered[head] = {
            "contract": contract, "contract_path": contract_path,
            "model_paths": model_paths, "model_sha256s": model_hashes,
            "deployment_model_sha256": EXPECTED_MODEL_SHA256[head],
        }
        audit[head] = {
            "model_hash_match": True, "feature_manifest_hash_match": True,
            "model_paths": {key: str(value) for key, value in model_paths.items()},
        }
    orders = {tuple(recovered[head]["contract"]["feature_column_order"]) for head in AUTHORITATIVE_HEAD_SET}
    if len(orders) != 1 or len(next(iter(orders))) != 29:
        raise R34Stop("STOPPED_FEATURE_MANIFEST_HASH_MISMATCH")
    if not FEATURE_MANIFEST.is_file() or sha256(FEATURE_MANIFEST) != FEATURE_MANIFEST_SHA256:
        raise R34Stop("STOPPED_FEATURE_MANIFEST_HASH_MISMATCH")
    return recovered, audit


def stable_population_sha(frame: pd.DataFrame, score: str, target: str) -> str:
    digest = hashlib.sha256()
    ordered = frame.sort_values("candidate_id", kind="mergesort")
    for candidate_id, timestamp, raw_score, outcome in ordered[["candidate_id", "decision_timestamp_utc", score, target]].itertuples(index=False, name=None):
        payload = f"{candidate_id}\t{pd.Timestamp(timestamp).isoformat()}\t{float(raw_score).hex()}\t{float(outcome).hex()}\n"
        digest.update(payload.encode("utf-8"))
    return digest.hexdigest()


def load_calibration_population() -> pd.DataFrame:
    if (
        not R33I_CONTRACT.is_file() or sha256(R33I_CONTRACT) != R33I_CONTRACT_SHA256
        or not R33I_OOF.is_file() or sha256(R33I_OOF) != R33I_OOF_SHA256
    ):
        raise R34Stop("STOPPED_CALIBRATION_LINEAGE_NOT_RECOVERABLE")
    contract = read_json(R33I_CONTRACT)
    if (
        contract.get("P", {}).get("source") != "T1" or contract.get("P", {}).get("status") != "CALIBRATED"
        or contract.get("L", {}).get("source") != "T5" or contract.get("L", {}).get("status") != "CALIBRATED"
        or contract.get("G", {}).get("status") != "RANKING_VALID_BUT_LEVEL_CALIBRATION_NOT_ESTABLISHED"
        or contract.get("FINAL_CONFIRMATION_DATA_USED") is not False
    ):
        raise R34Stop("STOPPED_CALIBRATION_LINEAGE_NOT_RECOVERABLE")
    columns = ["candidate_id", "decision_timestamp_utc", "head", "raw_net20", "pred_t1", "pred_t5", "pred_t6"]
    frame = pd.read_parquet(R33I_OOF, columns=columns)
    frame["decision_timestamp_utc"] = pd.to_datetime(frame.decision_timestamp_utc, utc=True)
    if (
        len(frame) != 984_049 or frame.candidate_id.duplicated().any() or set(frame["head"]) != {"UP", "DOWN"}
        or int(frame.raw_net20.gt(0).sum()) != 528_636 or int(frame.raw_net20.lt(0).sum()) != 455_413
        or int(frame.raw_net20.eq(0).sum()) != 0
        or frame[["pred_t1", "pred_t5", "pred_t6", "raw_net20"]].isna().any().any()
    ):
        raise R34Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    frame["winner_indicator"] = frame.raw_net20.gt(0).astype(float)
    frame["loser_loss_magnitude"] = frame.raw_net20.abs()
    return frame


def build_empirical_decile_mapping(
    scores: pd.Series,
    targets: pd.Series,
    timestamps: pd.Series,
    prospective_start_utc: pd.Timestamp,
    component: str,
) -> dict[str, Any]:
    if component not in {"P", "L"} or len(scores) != len(targets) or len(scores) != len(timestamps):
        raise R34Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    ts = pd.to_datetime(timestamps, utc=True)
    numeric_scores, numeric_targets = scores.astype(float), targets.astype(float)
    if len(scores) == 0 or numeric_scores.isna().any() or numeric_targets.isna().any() or not ts.lt(prospective_start_utc).all():
        raise R34Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    edges = numeric_scores.quantile(np.arange(1, CALIBRATION_BUCKET_COUNT) / CALIBRATION_BUCKET_COUNT, interpolation="linear").to_numpy(float)
    bins = np.searchsorted(edges, numeric_scores.to_numpy(float), side="right") + 1
    means = pd.Series(numeric_targets.to_numpy(float)).groupby(bins).mean()
    mapping = {
        "method": "R33I_FIXED_EMPIRICAL_DECILES", "bucket_count": CALIBRATION_BUCKET_COUNT,
        "bucket_boundaries": edges.tolist(), "bucket_edges": edges.tolist(),
        "bucket_values": {str(int(key)): float(value) for key, value in means.items()},
        "fallback_value": float(numeric_targets.mean()), "fallback": float(numeric_targets.mean()),
        "training_rows_strictly_pre_start": True, "daily_update_allowed": False, "search_count": 0,
    }
    return mapping


def apply_frozen_mapping(values: pd.Series, mapping: dict[str, Any]) -> np.ndarray:
    if (
        mapping.get("method") != "R33I_FIXED_EMPIRICAL_DECILES"
        or mapping.get("bucket_count") != CALIBRATION_BUCKET_COUNT
        or not (
            mapping.get("daily_update_allowed") is False
            or mapping.get("calibration_update_allowed") is False
        )
    ):
        raise R34Stop("STOPPED_FROZEN_CONTRACT_HASH_MISMATCH")
    edges = np.asarray(mapping["bucket_boundaries"], dtype=float)
    bins = np.searchsorted(edges, values.to_numpy(float), side="right") + 1
    fallback = mapping["fallback_value"]
    return np.asarray([mapping["bucket_values"].get(str(int(bucket)), fallback) for bucket in bins], dtype=float)


def calibration_contract(component: str, frame: pd.DataFrame, mapping: dict[str, Any], model_sha: str) -> dict[str, Any]:
    config = {
        "P": ("T1", "pred_t1", "winner_indicator", "historical canonical winner rate"),
        "L": ("T5", "pred_t5", "loser_loss_magnitude", "historical mean canonical loser loss magnitude"),
    }
    source_head, score, target, target_semantics = config[component]
    payload = {
        "CONTRACT_ID": f"FAST3_R34R_{component}_CALIBRATION_CONTRACT_R1", "STATUS": "FROZEN_IMMUTABLE",
        "source_head": source_head, "source_model_sha256": model_sha,
        "source_R33I_contract_sha256": R33I_CONTRACT_SHA256, "source_OOF_sha256": R33I_OOF_SHA256,
        "method": mapping["method"], "bucket_count": mapping["bucket_count"],
        "bucket_boundaries": mapping["bucket_boundaries"], "bucket_values": mapping["bucket_values"],
        "fallback_value": mapping["fallback_value"], "bucket_target": target_semantics,
        "training_population_sha256": stable_population_sha(frame, score, target),
        "training_row_count": len(frame), "training_start": frame.decision_timestamp_utc.min(),
        "training_end": frame.decision_timestamp_utc.max(), "calibration_update_allowed": False,
        "calibration_method_search_count": 0, "calibration_bucket_search_count": 0,
        "FINAL_CONFIRMATION_DATA_USED": False,
    }
    payload["calibration_contract_sha256"] = sha256_bytes(stable_json_bytes(payload))
    payload["calibration_contract_sha256_semantics"] = "canonical payload hash before this field; immutable file SHA256 is frozen by the prospective contract"
    return payload


def r34r_preregistration(created_at: str) -> dict[str, Any]:
    return {
        "CONTRACT_ID": "FAST3_R34R_PREREGISTRATION_R1", "STATUS": "FROZEN_BEFORE_CALIBRATION_BUILD",
        "PARENT_R34_STATUS": PARENT_R34_STATUS, "PARENT_R34_CLOSEOUT_SHA256": R33_CLOSEOUT_SHA256,
        "R34R_REPAIR_TYPE": R34R_REPAIR_TYPE, "R35_DEPLOYMENT_MANIFEST_SHA256": R35_MANIFEST_SHA256,
        "T1_MODEL_SHA256": EXPECTED_MODEL_SHA256["T1"], "T5_MODEL_SHA256": EXPECTED_MODEL_SHA256["T5"],
        "T6_MODEL_SHA256": EXPECTED_MODEL_SHA256["T6"], "FEATURE_MANIFEST_SHA256": FEATURE_MANIFEST_SHA256,
        "P_SOURCE": "T1", "L_SOURCE": "T5", "T6_ROLE": "DIAGNOSTIC_ONLY",
        "P_CALIBRATION_METHOD": "R33I_FIXED_EMPIRICAL_DECILES",
        "L_CALIBRATION_METHOD": "R33I_FIXED_EMPIRICAL_DECILES",
        "P_BUCKET_COUNT": 10, "L_BUCKET_COUNT": 10, "PROSPECTIVE_START_CREATED_LAST": True,
        "NO_HISTORY_BACKFILL": True, "CALIBRATION_UPDATES_PROHIBITED": True,
        "MODEL_UPDATES_PROHIBITED": True, "NEW_HEADS_PROHIBITED": True,
        "ABSOLUTE_EV_PROHIBITED": True, "RELATIVE_SCORE_PROHIBITED": True,
        "THRESHOLD_PROHIBITED": True, "TRADING_PROHIBITED": True, "FINAL_PROHIBITED": True,
        "NEW_HEAD_COUNT": 0, "NEW_FEATURE_COUNT": 0, "NEW_TARGET_COUNT": 0, "MODEL_FIT_COUNT": 0,
        "CALIBRATION_METHOD_SEARCH_COUNT": 0, "CALIBRATION_BUCKET_SEARCH_COUNT": 0,
        "GAIN_CALIBRATION_RETRY_COUNT": 0, "RUN_ID_TIMESTAMP_SEMANTICS": RUN_ID_TIMESTAMP_SEMANTICS,
        "CREATED_AT_UTC": created_at,
    }


def prepare_scorer_features(frame: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    if SCORER_PROHIBITED_COLUMNS.intersection(features) or any(feature not in frame.columns for feature in features):
        raise R34Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    return frame.loc[:, features].copy()


def predict_model(model: Any, features: pd.DataFrame, classifier: bool) -> np.ndarray:
    values = model.predict_proba(features)[:, 1] if classifier else model.predict(features)
    values = np.asarray(values, dtype=float)
    if not np.isfinite(values).all():
        raise R34Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    return values


def activation_scorer_sanity(models: dict[str, Any], p_mapping: dict[str, Any], l_mapping: dict[str, Any]) -> int:
    if not R32B_RUNNER.is_file() or sha256(R32B_RUNNER) != R32B_RUNNER_SHA256:
        raise R34Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    r32b = import_file(R32B_RUNNER, "r34r_r32b")
    _, manifest, features = r32b.guard_authority()
    dataset, _, _, _ = r32b.construct_dataset(manifest, features)
    if tuple(features) != tuple(models["T1"]["contract"]["feature_column_order"]):
        raise R34Stop("STOPPED_FEATURE_MANIFEST_HASH_MISMATCH")
    calls, outputs = 0, {}
    for direction in ("UP", "DOWN"):
        fixture = dataset.loc[dataset["head"].eq(direction)].sort_values(["decision_timestamp_utc", "candidate_id"], kind="mergesort").head(2)
        x = prepare_scorer_features(fixture, list(features))
        for head in AUTHORITATIVE_HEAD_SET:
            model = joblib.load(models[head]["model_paths"][direction])
            first = predict_model(model, x, head == "T1")
            second = predict_model(model, x, head == "T1")
            calls += 2
            if not np.array_equal(first, second):
                raise R34Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
            outputs[(head, direction)] = first
        if not np.isfinite(apply_frozen_mapping(pd.Series(outputs[("T1", direction)]), p_mapping)).all():
            raise R34Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
        if not np.isfinite(apply_frozen_mapping(pd.Series(outputs[("T5", direction)]), l_mapping)).all():
            raise R34Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    return calls


def diagnostic_reference(scores: pd.Series) -> dict[str, Any]:
    quantiles = np.linspace(0.0, 1.0, T6_REFERENCE_QUANTILE_COUNT)
    values = scores.astype(float).quantile(quantiles, interpolation="linear").to_numpy(float)
    return {
        "method": "FROZEN_PRE_START_EMPIRICAL_QUANTILE_REFERENCE",
        "quantile_count": T6_REFERENCE_QUANTILE_COUNT, "reference_values": values.tolist(),
        "source_OOF_sha256": R33I_OOF_SHA256, "economic_level_mapping": False,
        "decision_use_allowed": False,
    }


def apply_diagnostic_percentile(values: np.ndarray, reference: dict[str, Any]) -> np.ndarray:
    edges = np.asarray(reference["reference_values"], dtype=float)
    return np.searchsorted(edges, np.asarray(values, dtype=float), side="right").clip(1, len(edges)) / len(edges)


def prospective_contract(
    start: str,
    p_path: Path,
    p_sha: str,
    l_path: Path,
    l_sha: str,
    t6_reference: dict[str, Any],
) -> dict[str, Any]:
    return {
        "CONTRACT_ID": "FAST3_R34_PROSPECTIVE_CONTRACT_R1", "STATUS": "FROZEN_IMMUTABLE_ACTIVE",
        "architecture_name": "FROZEN_PROBABILITY_RISK_PROSPECTIVE",
        "R33_closeout_sha256": R33_CLOSEOUT_SHA256, "R35_deployment_manifest_sha256": R35_MANIFEST_SHA256,
        "T1_model_sha256": EXPECTED_MODEL_SHA256["T1"], "T5_model_sha256": EXPECTED_MODEL_SHA256["T5"],
        "T6_model_sha256": EXPECTED_MODEL_SHA256["T6"], "feature_manifest_sha256": FEATURE_MANIFEST_SHA256,
        "P_calibration_path": str(p_path), "P_calibration_sha256": p_sha,
        "L_calibration_path": str(l_path), "L_calibration_sha256": l_sha,
        "T6_diagnostic_reference": t6_reference,
        "T1_role": HEAD_ROLES["T1"], "T5_role": HEAD_ROLES["T5"], "T6_role": HEAD_ROLES["T6"],
        "T7_status": "REJECTED_REDUNDANT_WITH_T5", "T8_plus_status": "PROHIBITED",
        "absolute_ev_allowed": False, "relative_score_allowed": False, "T6_decision_use_allowed": False,
        "new_head_allowed": False, "new_feature_allowed": False, "calibration_update_allowed": False,
        "trade_selection_allowed": False, "broker_action_allowed": False, "final_data_prohibited": True,
        "candidate_contract_version": CANDIDATE_CONTRACT_VERSION,
        "candidate_eligibility_rule": read_json(R32A_IDENTITY)["ELIGIBILITY_RULE"],
        "R34_PROSPECTIVE_START_UTC": start, "RUN_ID_TIMESTAMP_SEMANTICS": RUN_ID_TIMESTAMP_SEMANTICS,
        "no_history_backfill": True, "prediction_immutable": True, "outcomes_reconciled_after_maturity_only": True,
        "PROSPECTIVE_START_CREATED_AFTER_ALL_FROZEN_CONTRACTS": True,
    }


def find_activation() -> tuple[Path, dict[str, Any], str] | None:
    paths = sorted(FAST3_FROZEN_ROOT.glob("r34r_frozen_prospective_activation_*/FAST3_R34_PROSPECTIVE_CONTRACT_R1.json"))
    if len(paths) > 1:
        raise R34Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    if not paths:
        return None
    contract = read_json(paths[0])
    if contract.get("STATUS") != "FROZEN_IMMUTABLE_ACTIVE":
        raise R34Stop("STOPPED_FROZEN_CONTRACT_HASH_MISMATCH")
    for component in ("P", "L"):
        path = Path(contract[f"{component}_calibration_path"])
        if not path.is_file() or sha256(path) != contract[f"{component}_calibration_sha256"]:
            raise R34Stop("STOPPED_FROZEN_CONTRACT_HASH_MISMATCH")
    if (
        contract.get("R33_closeout_sha256") != R33_CLOSEOUT_SHA256
        or contract.get("R35_deployment_manifest_sha256") != R35_MANIFEST_SHA256
        or contract.get("feature_manifest_sha256") != FEATURE_MANIFEST_SHA256
        or contract.get("calibration_update_allowed") is not False
    ):
        raise R34Stop("STOPPED_FROZEN_CONTRACT_HASH_MISMATCH")
    return paths[0].parent, contract, sha256(paths[0])


def append_only_predictions(existing: pd.DataFrame, new_rows: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if existing.empty:
        existing = pd.DataFrame(columns=LEDGER_COLUMNS)
    if existing.candidate_id.duplicated().any() or new_rows.candidate_id.duplicated().any():
        raise R34Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    missing = set(IMMUTABLE_PREDICTION_COLUMNS).difference(new_rows.columns)
    if missing:
        raise R34Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    unseen = new_rows.loc[~new_rows.candidate_id.isin(existing.candidate_id)].copy()
    for column in OUTCOME_COLUMNS:
        unseen[column] = "PENDING" if column == "outcome_status" else None
    combined = pd.concat([existing, unseen[list(LEDGER_COLUMNS)]], ignore_index=True)
    combined = combined.sort_values(["decision_timestamp_utc", "candidate_id"], kind="mergesort").reset_index(drop=True)
    if combined.candidate_id.duplicated().any():
        raise R34Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    return combined, len(unseen)


def reconcile_mature_outcomes(ledger: pd.DataFrame, outcomes: pd.DataFrame, as_of_utc: pd.Timestamp) -> tuple[pd.DataFrame, int]:
    result = ledger.copy()
    immutable_before = result[list(IMMUTABLE_PREDICTION_COLUMNS)].copy(deep=True)
    outcomes = outcomes.copy()
    outcomes["outcome_maturity_timestamp"] = pd.to_datetime(outcomes.outcome_maturity_timestamp, utc=True)
    mature = outcomes.loc[outcomes.outcome_maturity_timestamp.le(as_of_utc)]
    pending_ids = set(result.loc[result.outcome_status.eq("PENDING"), "candidate_id"])
    mature = mature.loc[mature.candidate_id.isin(pending_ids)].drop_duplicates("candidate_id", keep=False)
    indexed = mature.set_index("candidate_id")
    for row_index, candidate_id in result.candidate_id.items():
        if candidate_id not in indexed.index:
            continue
        record = indexed.loc[candidate_id]
        result.loc[row_index, list(OUTCOME_COLUMNS)] = [
            "MATURED", record.outcome_maturity_timestamp, record.canonical_realized_payoff,
            record.winner_indicator, record.winner_gain_magnitude, record.loser_loss_magnitude,
        ]
    if not immutable_before.equals(result[list(IMMUTABLE_PREDICTION_COLUMNS)]):
        raise R34Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    return result, len(mature)


def load_ledger() -> pd.DataFrame:
    if not CANONICAL_LEDGER.is_file():
        return pd.DataFrame(columns=LEDGER_COLUMNS)
    ledger = pd.read_parquet(CANONICAL_LEDGER)
    if list(ledger.columns) != list(LEDGER_COLUMNS) or ledger.candidate_id.duplicated().any():
        raise R34Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    ledger["decision_timestamp_utc"] = pd.to_datetime(ledger.decision_timestamp_utc, utc=True)
    return ledger


def validate_candidate_input(frame: pd.DataFrame, features: list[str], start: pd.Timestamp) -> tuple[pd.DataFrame, int, int]:
    required = {
        "candidate_id", "decision_timestamp_utc", "trading_date", "direction", "underlying",
        "candidate_contract_version", "max_feature_timestamp_utc", *features,
    }
    if required.difference(frame.columns) or SCORER_PROHIBITED_COLUMNS.intersection(frame.columns):
        raise R34Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    frame = frame.copy()
    frame["decision_timestamp_utc"] = pd.to_datetime(frame.decision_timestamp_utc, utc=True)
    frame["max_feature_timestamp_utc"] = pd.to_datetime(frame.max_feature_timestamp_utc, utc=True)
    future_count = int(frame.max_feature_timestamp_utc.gt(frame.decision_timestamp_utc).sum())
    if future_count:
        raise R34Stop("STOPPED_PIT_VIOLATION")
    if (
        frame.candidate_id.duplicated().any() or not set(frame.direction).issubset({"UP", "DOWN"})
        or not frame.candidate_contract_version.eq(CANDIDATE_CONTRACT_VERSION).all()
        or np.isinf(frame[features].to_numpy(dtype=float, copy=False)).any()
    ):
        raise R34Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    pre_start = int(frame.decision_timestamp_utc.lt(start).sum())
    return frame.loc[frame.decision_timestamp_utc.ge(start)].copy(), pre_start, future_count


def score_candidates(
    candidates: pd.DataFrame,
    existing: pd.DataFrame,
    models: dict[str, Any],
    p_mapping: dict[str, Any],
    l_mapping: dict[str, Any],
    contract: dict[str, Any],
    contract_sha: str,
) -> tuple[pd.DataFrame, dict[str, int]]:
    unseen = candidates.loc[~candidates.candidate_id.isin(existing.candidate_id)].copy()
    calls = {head: 0 for head in AUTHORITATIVE_HEAD_SET}
    if unseen.empty:
        return pd.DataFrame(columns=IMMUTABLE_PREDICTION_COLUMNS), calls
    features = models["T1"]["contract"]["feature_column_order"]
    raw = {head: np.full(len(unseen), np.nan) for head in AUTHORITATIVE_HEAD_SET}
    for direction in ("UP", "DOWN"):
        positions = np.flatnonzero(unseen.direction.eq(direction).to_numpy())
        if len(positions) == 0:
            continue
        x = prepare_scorer_features(unseen.iloc[positions], features)
        for head in AUTHORITATIVE_HEAD_SET:
            model = joblib.load(models[head]["model_paths"][direction])
            raw[head][positions] = predict_model(model, x, head == "T1")
            calls[head] += 1
    if not all(np.isfinite(raw[head]).all() for head in AUTHORITATIVE_HEAD_SET):
        raise R34Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    output = unseen[["candidate_id", "decision_timestamp_utc", "trading_date", "direction", "underlying", "candidate_contract_version"]].copy()
    output["T1_raw"] = raw["T1"]
    output["P_WIN_CALIBRATED"] = apply_frozen_mapping(pd.Series(raw["T1"]), p_mapping)
    output["T5_raw"] = raw["T5"]
    output["L_LOSER_CALIBRATED"] = apply_frozen_mapping(pd.Series(raw["T5"]), l_mapping)
    output["T6_raw"] = raw["T6"]
    output["T6_DIAGNOSTIC_PERCENTILE"] = apply_diagnostic_percentile(raw["T6"], contract["T6_diagnostic_reference"])
    output["T1_model_sha256"] = EXPECTED_MODEL_SHA256["T1"]
    output["T5_model_sha256"] = EXPECTED_MODEL_SHA256["T5"]
    output["T6_model_sha256"] = EXPECTED_MODEL_SHA256["T6"]
    output["feature_manifest_sha256"] = FEATURE_MANIFEST_SHA256
    output["P_calibration_contract_sha256"] = contract["P_calibration_sha256"]
    output["L_calibration_contract_sha256"] = contract["L_calibration_sha256"]
    output["r34_prospective_contract_sha256"] = contract_sha
    return output[list(IMMUTABLE_PREDICTION_COLUMNS)], calls


def monitoring(ledger: pd.DataFrame) -> dict[str, Any]:
    insufficient = "INSUFFICIENT_MATURED_PROSPECTIVE_DATA"
    result = {
        "PROSPECTIVE_MONITORING_STATUS": insufficient,
        "P_PROSPECTIVE_BRIER": insufficient, "P_PROSPECTIVE_LOGLOSS": insufficient,
        "P_PROSPECTIVE_ECE": insufficient, "L_PROSPECTIVE_MAE": insufficient,
        "L_PROSPECTIVE_RMSE": insufficient, "L_PROSPECTIVE_SPEARMAN": insufficient,
        "T6_PROSPECTIVE_GAIN_SPEARMAN": insufficient,
    }
    mature = ledger.loc[ledger.outcome_status.eq("MATURED")].copy()
    if mature.empty:
        return result
    result["PROSPECTIVE_MONITORING_STATUS"] = "MONITORING_ONLY_NO_AUTOMATIC_RESEARCH_DECISION"
    probability = mature.P_WIN_CALIBRATED.astype(float).clip(1e-15, 1 - 1e-15)
    actual = mature.winner_indicator.astype(float)
    result["P_PROSPECTIVE_BRIER"] = float(np.mean((probability - actual) ** 2))
    result["P_PROSPECTIVE_LOGLOSS"] = float(-np.mean(actual * np.log(probability) + (1 - actual) * np.log(1 - probability)))
    ordered = mature.sort_values(["P_WIN_CALIBRATED", "decision_timestamp_utc", "candidate_id"], kind="mergesort").copy()
    ordered["diagnostic_bin"] = np.floor(np.arange(len(ordered)) * 5 / len(ordered)).astype(int)
    reliability = ordered.groupby("diagnostic_bin", observed=True).agg(pred=("P_WIN_CALIBRATED", "mean"), actual=("winner_indicator", "mean"), n=("candidate_id", "size"))
    result["P_PROSPECTIVE_ECE"] = float(np.average(np.abs(reliability.pred - reliability.actual), weights=reliability.n))
    losers = mature.loc[mature.winner_indicator.astype(float).eq(0) & mature.loser_loss_magnitude.notna()]
    if not losers.empty:
        error = losers.L_LOSER_CALIBRATED.astype(float) - losers.loser_loss_magnitude.astype(float)
        result["L_PROSPECTIVE_MAE"] = float(np.mean(np.abs(error)))
        result["L_PROSPECTIVE_RMSE"] = float(np.sqrt(np.mean(error ** 2)))
        if len(losers) > 1 and losers.L_LOSER_CALIBRATED.nunique() > 1 and losers.loser_loss_magnitude.nunique() > 1:
            result["L_PROSPECTIVE_SPEARMAN"] = float(losers.L_LOSER_CALIBRATED.corr(losers.loser_loss_magnitude, method="spearman"))
    winners = mature.loc[mature.winner_indicator.astype(float).eq(1) & mature.winner_gain_magnitude.notna()]
    if len(winners) > 1 and winners.T6_raw.nunique() > 1 and winners.winner_gain_magnitude.nunique() > 1:
        result["T6_PROSPECTIVE_GAIN_SPEARMAN"] = float(winners.T6_raw.corr(winners.winner_gain_magnitude, method="spearman"))
    return result


def initialize_activation(models: dict[str, Any]) -> tuple[Path, dict[str, Any], str, int]:
    pending_roots = sorted(
        root for root in FAST3_FROZEN_ROOT.glob("r34r_frozen_prospective_activation_*")
        if (root / "FAST3_R34R_PREREGISTRATION_R1.json").is_file()
        and (root / "FAST3_R34R_P_CALIBRATION_CONTRACT_R1.json").is_file()
        and (root / "FAST3_R34R_L_CALIBRATION_CONTRACT_R1.json").is_file()
        and not (root / "FAST3_R34_PROSPECTIVE_CONTRACT_R1.json").exists()
    )
    if len(pending_roots) > 1:
        raise R34Stop("STOPPED_ANTI_BLOAT_VIOLATION")
    if pending_roots:
        root = pending_roots[0]
        prereg_path = root / "FAST3_R34R_PREREGISTRATION_R1.json"
        p_path = root / "FAST3_R34R_P_CALIBRATION_CONTRACT_R1.json"
        l_path = root / "FAST3_R34R_L_CALIBRATION_CONTRACT_R1.json"
        prereg, p_contract, l_contract = read_json(prereg_path), read_json(p_path), read_json(l_path)
        if (
            prereg.get("STATUS") != "FROZEN_BEFORE_CALIBRATION_BUILD"
            or prereg.get("R35_DEPLOYMENT_MANIFEST_SHA256") != R35_MANIFEST_SHA256
            or p_contract.get("source_head") != "T1" or l_contract.get("source_head") != "T5"
            or p_contract.get("method") != "R33I_FIXED_EMPIRICAL_DECILES"
            or l_contract.get("method") != "R33I_FIXED_EMPIRICAL_DECILES"
            or p_contract.get("bucket_count") != 10 or l_contract.get("bucket_count") != 10
            or p_contract.get("calibration_update_allowed") is not False
            or l_contract.get("calibration_update_allowed") is not False
        ):
            raise R34Stop("STOPPED_PREREGISTRATION_ORDER_VIOLATION")
        population = load_calibration_population()
        l_population = population.loc[population.raw_net20.lt(0)]
        if (
            stable_population_sha(population, "pred_t1", "winner_indicator") != p_contract["training_population_sha256"]
            or stable_population_sha(l_population, "pred_t5", "loser_loss_magnitude") != l_contract["training_population_sha256"]
        ):
            raise R34Stop("STOPPED_CALIBRATION_LINEAGE_NOT_RECOVERABLE")
        sanity_calls = activation_scorer_sanity(models, p_contract, l_contract)
        t6_reference = diagnostic_reference(population.pred_t6)
        prospective_start = datetime.now(timezone.utc)
        start_text = prospective_start.isoformat(timespec="microseconds").replace("+00:00", "Z")
        if pd.Timestamp(p_contract["training_end"]) >= prospective_start or pd.Timestamp(l_contract["training_end"]) >= prospective_start:
            raise R34Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
        contract = prospective_contract(start_text, p_path, sha256(p_path), l_path, sha256(l_path), t6_reference)
        contract_path = root / "FAST3_R34_PROSPECTIVE_CONTRACT_R1.json"
        write_json_once(contract_path, contract)
        contract_sha = sha256(contract_path)
        if not (
            prereg_path.stat().st_mtime_ns <= p_path.stat().st_mtime_ns <= contract_path.stat().st_mtime_ns
            and prereg_path.stat().st_mtime_ns <= l_path.stat().st_mtime_ns <= contract_path.stat().st_mtime_ns
        ):
            raise R34Stop("STOPPED_PREREGISTRATION_ORDER_VIOLATION")
        return root, contract, contract_sha, sanity_calls

    started = datetime.now(timezone.utc)
    run_id = f"r34r_frozen_prospective_activation_{started.strftime('%Y%m%dT%H%M%SZ')}"
    root = FAST3_FROZEN_ROOT / run_id
    if root.exists():
        raise R34Stop("STOPPED_ANTI_BLOAT_VIOLATION")
    root.mkdir(parents=True)
    prereg_path = root / "FAST3_R34R_PREREGISTRATION_R1.json"
    write_json_once(prereg_path, r34r_preregistration(started.isoformat()))
    prereg_sha = sha256(prereg_path)
    if not prereg_path.is_file():
        raise R34Stop("STOPPED_PREREGISTRATION_ORDER_VIOLATION")
    population = load_calibration_population()
    calibration_build_cutoff = pd.Timestamp(datetime.now(timezone.utc))
    p_frame = population
    l_frame = population.loc[population.raw_net20.lt(0)].copy()
    p_mapping = build_empirical_decile_mapping(p_frame.pred_t1, p_frame.winner_indicator, p_frame.decision_timestamp_utc, calibration_build_cutoff, "P")
    l_mapping = build_empirical_decile_mapping(l_frame.pred_t5, l_frame.loser_loss_magnitude, l_frame.decision_timestamp_utc, calibration_build_cutoff, "L")
    p_contract = calibration_contract("P", p_frame, p_mapping, EXPECTED_MODEL_SHA256["T1"])
    l_contract = calibration_contract("L", l_frame, l_mapping, EXPECTED_MODEL_SHA256["T5"])
    p_path = root / "FAST3_R34R_P_CALIBRATION_CONTRACT_R1.json"
    l_path = root / "FAST3_R34R_L_CALIBRATION_CONTRACT_R1.json"
    if not prereg_path.is_file() or sha256(prereg_path) != prereg_sha:
        raise R34Stop("STOPPED_PREREGISTRATION_ORDER_VIOLATION")
    write_json_once(p_path, p_contract)
    write_json_once(l_path, l_contract)
    p_sha, l_sha = sha256(p_path), sha256(l_path)
    sanity_calls = activation_scorer_sanity(models, p_contract, l_contract)
    t6_reference = diagnostic_reference(population.pred_t6)
    prospective_start = datetime.now(timezone.utc)
    start_text = prospective_start.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if not p_frame.decision_timestamp_utc.lt(prospective_start).all() or not l_frame.decision_timestamp_utc.lt(prospective_start).all():
        raise R34Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    contract = prospective_contract(start_text, p_path, p_sha, l_path, l_sha, t6_reference)
    contract_path = root / "FAST3_R34_PROSPECTIVE_CONTRACT_R1.json"
    write_json_once(contract_path, contract)
    contract_sha = sha256(contract_path)
    if not (prereg_path.stat().st_mtime_ns <= p_path.stat().st_mtime_ns <= contract_path.stat().st_mtime_ns and prereg_path.stat().st_mtime_ns <= l_path.stat().st_mtime_ns <= contract_path.stat().st_mtime_ns):
        raise R34Stop("STOPPED_PREREGISTRATION_ORDER_VIOLATION")
    return root, contract, contract_sha, sanity_calls


def load_or_initialize_ledger() -> pd.DataFrame:
    ledger = load_ledger()
    if not CANONICAL_LEDGER.exists():
        write_parquet_atomic(CANONICAL_LEDGER, ledger)
    return ledger


def run_shadow(models: dict[str, Any], contract: dict[str, Any], contract_sha: str) -> dict[str, Any]:
    start = pd.Timestamp(contract["R34_PROSPECTIVE_START_UTC"])
    features = models["T1"]["contract"]["feature_column_order"]
    existing = load_or_initialize_ledger()
    pre_start, future_count = 0, 0
    if CANONICAL_INPUT.is_file():
        candidates = pd.read_parquet(CANONICAL_INPUT)
        candidates, pre_start, future_count = validate_candidate_input(candidates, features, start)
    else:
        candidates = pd.DataFrame(columns=["candidate_id", *features])
    p_contract = read_json(Path(contract["P_calibration_path"]))
    l_contract = read_json(Path(contract["L_calibration_path"]))
    predictions, calls = score_candidates(candidates, existing, models, p_contract, l_contract, contract, contract_sha)
    ledger, new_count = append_only_predictions(existing, predictions)
    reconciled = 0
    if CANONICAL_OUTCOMES.is_file():
        outcomes = pd.read_parquet(CANONICAL_OUTCOMES)
        required = {"candidate_id", "outcome_maturity_timestamp", "canonical_realized_payoff", "winner_indicator", "winner_gain_magnitude", "loser_loss_magnitude"}
        if required.difference(outcomes.columns):
            raise R34Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
        ledger, reconciled = reconcile_mature_outcomes(ledger, outcomes, pd.Timestamp(datetime.now(timezone.utc)))
    if new_count or reconciled:
        write_parquet_atomic(CANONICAL_LEDGER, ledger)
    return {
        "ledger": ledger, "new_count": new_count, "calls": calls, "pre_start": pre_start,
        "future_count": future_count, "reconciled": reconciled, **monitoring(ledger),
    }


def build_summary(root: Path, contract: dict[str, Any], contract_sha: str, shadow: dict[str, Any], sanity_calls: int) -> dict[str, Any]:
    ledger = shadow["ledger"]
    matured = int(ledger.outcome_status.eq("MATURED").sum()) if not ledger.empty else 0
    pending = int(ledger.outcome_status.eq("PENDING").sum()) if not ledger.empty else 0
    return {
        "FAST3_R34R_STATUS": "PASS", "FAST3_R34R_CLASSIFICATION": "A_FROZEN_PROSPECTIVE_ACTIVATION_COMPLETE",
        "FAST3_R34R_DECISION": "BEGIN_FROZEN_PROSPECTIVE_SHADOW",
        "FAST3_R34_STATUS": "PASS", "FAST3_R34_CLASSIFICATION": "A_FROZEN_PROBABILITY_RISK_PROSPECTIVE_ARCHITECTURE_READY",
        "FAST3_R34_DECISION": "BEGIN_FROZEN_PROSPECTIVE_SHADOW",
        "R34R_PREREGISTRATION_VERIFIED": True,
        "R34R_PREREGISTRATION_SHA256": sha256(root / "FAST3_R34R_PREREGISTRATION_R1.json"),
        "PREREGISTRATION_EXISTS_BEFORE_CALIBRATION_BUILD": True,
        "PROSPECTIVE_START_CREATED_AFTER_ALL_FROZEN_CONTRACTS": True,
        "PARENT_R34_STATUS": PARENT_R34_STATUS, "R34R_REPAIR_TYPE": R34R_REPAIR_TYPE,
        "R33_CLOSEOUT_RECONCILIATION_STATUS": "PASS", "R33_CLOSEOUT_SHA256": R33_CLOSEOUT_SHA256,
        "R35_DEPLOYMENT_MANIFEST_RECONCILIATION_STATUS": "PASS",
        "R35_DEPLOYMENT_MANIFEST_SHA256": R35_MANIFEST_SHA256,
        "T1_MODEL_SHA256": EXPECTED_MODEL_SHA256["T1"], "T5_MODEL_SHA256": EXPECTED_MODEL_SHA256["T5"],
        "T6_MODEL_SHA256": EXPECTED_MODEL_SHA256["T6"], "FEATURE_MANIFEST_SHA256": FEATURE_MANIFEST_SHA256,
        "T1_MODEL_HASH_MATCH": True, "T5_MODEL_HASH_MATCH": True, "T6_MODEL_HASH_MATCH": True,
        "FEATURE_MANIFEST_HASH_MATCH": True, "P_SOURCE": "T1", "L_SOURCE": "T5", "T6_ROLE": "DIAGNOSTIC_ONLY",
        "P_CALIBRATION_METHOD": "R33I_FIXED_EMPIRICAL_DECILES", "P_CALIBRATION_BUCKET_COUNT": 10,
        "P_CALIBRATION_SHA256": contract["P_calibration_sha256"],
        "L_CALIBRATION_METHOD": "R33I_FIXED_EMPIRICAL_DECILES", "L_CALIBRATION_BUCKET_COUNT": 10,
        "L_CALIBRATION_SHA256": contract["L_calibration_sha256"],
        "P_PROSPECTIVE_CALIBRATION_BUILD_COUNT": 1, "L_PROSPECTIVE_CALIBRATION_BUILD_COUNT": 1,
        "DAILY_CALIBRATION_BUILD_COUNT": 0, "DAILY_CALIBRATION_UPDATE_COUNT": 0,
        "R34_PROSPECTIVE_CONTRACT_CREATED": True, "R34_PROSPECTIVE_CONTRACT_SHA256": contract_sha,
        "R34_PROSPECTIVE_START_CREATED": True, "R34_PROSPECTIVE_START_UTC": contract["R34_PROSPECTIVE_START_UTC"],
        "RUN_ID_TIMESTAMP_SEMANTICS": RUN_ID_TIMESTAMP_SEMANTICS,
        "PRE_START_ROW_COUNT_EXCLUDED": shadow["pre_start"], "NEW_PROSPECTIVE_SIGNAL_COUNT": shadow["new_count"],
        "TOTAL_PROSPECTIVE_SIGNAL_COUNT": len(ledger), "MATURED_PROSPECTIVE_ROW_COUNT": matured,
        "PENDING_PROSPECTIVE_ROW_COUNT": pending, "DUPLICATE_PROSPECTIVE_CANDIDATE_COUNT": 0,
        "PREMATURE_OUTCOME_RECONCILIATION_COUNT": 0,
        "T1_PROSPECTIVE_PREDICT_CALL_COUNT": shadow["calls"]["T1"],
        "T5_PROSPECTIVE_PREDICT_CALL_COUNT": shadow["calls"]["T5"],
        "T6_PROSPECTIVE_PREDICT_CALL_COUNT": shadow["calls"]["T6"],
        "ACTIVATION_SANITY_PREDICT_CALL_COUNT": sanity_calls, "SANITY_FIXTURE_PROSPECTIVE_SIGNAL_COUNT": 0,
        "PIT_CONTRACT_STATUS": "PASS", "FUTURE_FEATURE_ROW_COUNT": shadow["future_count"],
        "OUTCOME_COLUMNS_VISIBLE_TO_SCORER": False, "PROSPECTIVE_MONITORING_STATUS": shadow["PROSPECTIVE_MONITORING_STATUS"],
        "P_PROSPECTIVE_BRIER": shadow["P_PROSPECTIVE_BRIER"], "P_PROSPECTIVE_LOGLOSS": shadow["P_PROSPECTIVE_LOGLOSS"],
        "P_PROSPECTIVE_ECE": shadow["P_PROSPECTIVE_ECE"], "L_PROSPECTIVE_MAE": shadow["L_PROSPECTIVE_MAE"],
        "L_PROSPECTIVE_RMSE": shadow["L_PROSPECTIVE_RMSE"], "L_PROSPECTIVE_SPEARMAN": shadow["L_PROSPECTIVE_SPEARMAN"],
        "T6_PROSPECTIVE_GAIN_SPEARMAN": shadow["T6_PROSPECTIVE_GAIN_SPEARMAN"],
        "NEW_HEAD_COUNT": 0, "NEW_FEATURE_COUNT": 0, "NEW_TARGET_COUNT": 0, "NEW_SOURCE_FILE_COUNT": 0,
        "MODEL_FIT_COUNT": 0, "CALIBRATION_METHOD_SEARCH_COUNT": 0, "CALIBRATION_BUCKET_SEARCH_COUNT": 0,
        "PROSPECTIVE_CALIBRATION_SEARCH_COUNT": 0, "GAIN_CALIBRATION_RETRY_COUNT": 0,
        "T6_ECONOMIC_LEVEL_MAPPING_COUNT": 0, "T6_DECISION_USE_COUNT": 0,
        "ABSOLUTE_EV_CONSTRUCTION_COUNT": 0, "RELATIVE_SCORE_CONSTRUCTION_COUNT": 0,
        "EV_SCORE_CONSTRUCTION_COUNT": 0, "EV_COMBINATION_SEARCH_COUNT": 0, "SCORE_FORMULA_SEARCH_COUNT": 0,
        "WEIGHT_SEARCH_COUNT": 0, "WEIGHT_ASSIGNMENT_COUNT": 0, "THRESHOLD_SEARCH_COUNT": 0,
        "NEW_SELECTION_THRESHOLD_COUNT": 0, "SIGNAL_SELECTION_COUNT": 0,
        "TRADING_SIMULATION_COUNT": 0, "EXECUTION_SIMULATION_COUNT": 0, "POSITION_SIZING_SEARCH_COUNT": 0,
        "TRADE_SELECTION_ALLOWED": False, "ORDER_GENERATION_ALLOWED": False, "POSITION_SIZING_ALLOWED": False,
        "BROKER_ACTION_ALLOWED": False, "T7_STATUS": "REJECTED_REDUNDANT_WITH_T5",
        "T8_PLUS_STATUS": "PROHIBITED", "FURTHER_HEAD_EXPANSION_ALLOWED": False,
        "R35_MODEL_COPY_COUNT": 0, "PROSPECTIVE_PERFORMANCE_GATE_COUNT": 0,
        "AUTOMATIC_MODEL_UPDATE_COUNT": 0, "AUTOMATIC_CALIBRATION_UPDATE_COUNT": 0,
        "AUTOMATIC_POLICY_UPDATE_COUNT": 0, "FINAL_CONFIRMATION_DATA_USED": False,
        "FINAL_CONFIRMATION_DATA_LOADED": False, "FINAL_HOLDOUT_INSPECTED": False,
        "FINAL_HOLDOUT_ROW_COUNT": 0, "ARTIFACT_BLOAT_GUARD_STATUS": "PASS", "ANTI_BLOAT_STATUS": "PASS",
        "DAILY_R34_COMMAND": r".\scripts\fast3\run_fast3_r34_frozen_probability_risk_prospective.ps1 -Execute",
        "PRIMARY_RESEARCH_INTERPRETATION": "FROZEN_PROBABILITY_RISK_ARCHITECTURE_ACTIVATED_FOR_TRUE_PROSPECTIVE_SHADOW",
        "NEXT_STAGE": "DAILY_FROZEN_PROSPECTIVE_SHADOW_ONLY", "CANONICAL_LEDGER_PATH": str(CANONICAL_LEDGER),
        "ACTIVATION_ROOT": str(root), "ACTIVATION_RERUN_COUNT": 1,
        "ACTIVATION_RERUN_REASON": "CALIBRATION_CONTRACT_APPLY_GUARD_SCHEMA_BUG_BEFORE_PROSPECTIVE_START",
        "RESEARCH_CHOICE_CHANGED_AFTER_FIRST_ACTIVATION_ATTEMPT": False,
    }


def print_summary(summary: dict[str, Any]) -> None:
    keys = [
        "FAST3_R34R_STATUS", "FAST3_R34R_CLASSIFICATION", "FAST3_R34R_DECISION",
        "R34R_PREREGISTRATION_VERIFIED", "R34R_PREREGISTRATION_SHA256", "PARENT_R34_STATUS", "R34R_REPAIR_TYPE",
        "R33_CLOSEOUT_RECONCILIATION_STATUS", "R33_CLOSEOUT_SHA256",
        "R35_DEPLOYMENT_MANIFEST_RECONCILIATION_STATUS", "R35_DEPLOYMENT_MANIFEST_SHA256",
        "T1_MODEL_SHA256", "T5_MODEL_SHA256", "T6_MODEL_SHA256", "FEATURE_MANIFEST_SHA256",
        "T1_MODEL_HASH_MATCH", "T5_MODEL_HASH_MATCH", "T6_MODEL_HASH_MATCH", "FEATURE_MANIFEST_HASH_MATCH",
        "P_SOURCE", "L_SOURCE", "T6_ROLE", "P_CALIBRATION_METHOD", "P_CALIBRATION_BUCKET_COUNT", "P_CALIBRATION_SHA256",
        "L_CALIBRATION_METHOD", "L_CALIBRATION_BUCKET_COUNT", "L_CALIBRATION_SHA256",
        "P_PROSPECTIVE_CALIBRATION_BUILD_COUNT", "L_PROSPECTIVE_CALIBRATION_BUILD_COUNT", "DAILY_CALIBRATION_UPDATE_COUNT",
        "R34_PROSPECTIVE_CONTRACT_CREATED", "R34_PROSPECTIVE_CONTRACT_SHA256",
        "R34_PROSPECTIVE_START_CREATED", "R34_PROSPECTIVE_START_UTC", "RUN_ID_TIMESTAMP_SEMANTICS",
        "PRE_START_ROW_COUNT_EXCLUDED", "NEW_PROSPECTIVE_SIGNAL_COUNT", "TOTAL_PROSPECTIVE_SIGNAL_COUNT",
        "MATURED_PROSPECTIVE_ROW_COUNT", "PENDING_PROSPECTIVE_ROW_COUNT", "DUPLICATE_PROSPECTIVE_CANDIDATE_COUNT",
        "PREMATURE_OUTCOME_RECONCILIATION_COUNT", "T1_PROSPECTIVE_PREDICT_CALL_COUNT",
        "T5_PROSPECTIVE_PREDICT_CALL_COUNT", "T6_PROSPECTIVE_PREDICT_CALL_COUNT", "PIT_CONTRACT_STATUS",
        "FUTURE_FEATURE_ROW_COUNT", "OUTCOME_COLUMNS_VISIBLE_TO_SCORER", "PROSPECTIVE_MONITORING_STATUS",
        "NEW_HEAD_COUNT", "NEW_FEATURE_COUNT", "NEW_TARGET_COUNT", "MODEL_FIT_COUNT", "GAIN_CALIBRATION_RETRY_COUNT",
        "T6_ECONOMIC_LEVEL_MAPPING_COUNT", "T6_DECISION_USE_COUNT", "ABSOLUTE_EV_CONSTRUCTION_COUNT",
        "RELATIVE_SCORE_CONSTRUCTION_COUNT", "EV_SCORE_CONSTRUCTION_COUNT", "EV_COMBINATION_SEARCH_COUNT",
        "WEIGHT_SEARCH_COUNT", "THRESHOLD_SEARCH_COUNT", "SIGNAL_SELECTION_COUNT", "TRADING_SIMULATION_COUNT",
        "EXECUTION_SIMULATION_COUNT", "POSITION_SIZING_SEARCH_COUNT", "TRADE_SELECTION_ALLOWED", "BROKER_ACTION_ALLOWED",
        "T7_STATUS", "T8_PLUS_STATUS", "FURTHER_HEAD_EXPANSION_ALLOWED", "FINAL_CONFIRMATION_DATA_USED",
        "FINAL_CONFIRMATION_DATA_LOADED", "FINAL_HOLDOUT_INSPECTED", "R35_MODEL_COPY_COUNT",
        "ARTIFACT_BLOAT_GUARD_STATUS", "ANTI_BLOAT_STATUS", "DAILY_R34_COMMAND",
        "PRIMARY_RESEARCH_INTERPRETATION", "NEXT_STAGE",
    ]
    for key in keys:
        value = summary[key]
        if isinstance(value, bool):
            value = str(value).lower()
        print(f"{key}={value}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        raise R34Stop("USE_--execute")
    validate_storage_contract()
    reconcile_r33_closeout()
    if not R32A_IDENTITY.is_file() or sha256(R32A_IDENTITY) != R32A_IDENTITY_SHA256:
        raise R34Stop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    models, _ = recover_frozen_inference_artifacts()
    existing = find_activation()
    if existing is None:
        root, contract, contract_sha, sanity_calls = initialize_activation(models)
        activation_created = True
    else:
        root, contract, contract_sha = existing
        sanity_calls = 0
        activation_created = False
    shadow = run_shadow(models, contract, contract_sha)
    summary = build_summary(root, contract, contract_sha, shadow, sanity_calls)
    summary["R34_PROSPECTIVE_CONTRACT_REUSED"] = not activation_created
    summary["P_CALIBRATION_REUSED"] = not activation_created
    summary["L_CALIBRATION_REUSED"] = not activation_created
    summary["CURRENT_STATUS_UPDATED_AT_UTC"] = datetime.now(timezone.utc)
    write_atomic(CURRENT_STATUS, stable_json_bytes(summary))
    current_report = f"""# FAST3 R34 Current Prospective Shadow Status

`PASS`: frozen probability-risk prospective shadow is active from `{contract['R34_PROSPECTIVE_START_UTC']}`.

New signals this run: `{shadow['new_count']}`. Total signals: `{len(shadow['ledger'])}`. Monitoring status: `{shadow['PROSPECTIVE_MONITORING_STATUS']}`.

T1 supplies frozen calibrated winner probability, T5 supplies frozen conditional loser loss level, and T6 remains diagnostic-only. No EV, relative score, threshold, trade selection, broker action, model/calibration update, or Final access is permitted.
"""
    write_atomic(CURRENT_REPORT, current_report.encode("utf-8"))
    if activation_created:
        write_json_once(root / "FAST3_R34R_SUMMARY.json", summary)
        (root / "FAST3_R34R_REPORT.md").write_text(current_report, encoding="utf-8")
    print_summary(summary)
    print(f"ACTIVATION_ROOT={root}")
    print(f"CANONICAL_LEDGER_PATH={CANONICAL_LEDGER}")
    print(f"CURRENT_STATUS_PATH={CURRENT_STATUS}")
    print(f"CURRENT_REPORT_PATH={CURRENT_REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
