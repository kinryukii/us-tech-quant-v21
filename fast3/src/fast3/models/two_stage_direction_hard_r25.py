"""FAST3 R25: frozen R24 actionability with asymmetric direction abstention.

This is deliberately a small extension of R24.  The event head, features,
preprocessing, weighting, estimator parameters, and temporal split machinery
are inherited unchanged; only the conditional direction stage is split into
two independently fitted binary heads.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier

from fast3.models import two_stage_direction_hard_r24 as r24
from fast3.models import two_stage_direction_hard_r22 as base

UP, DOWN, NO_EVENT, AMBIGUOUS = base.UP, base.DOWN, base.NO_EVENT, base.AMBIGUOUS
R25ContractError = r24.R4ContractError
stable_hash, file_hash, write_json = r24.stable_hash, r24.file_hash, r24.write_json
prepare_cohort, deterministic_schedule, block_rows = r24.prepare_cohort, r24.deterministic_schedule, r24.block_rows
FoldPreprocessor, training_weights, MODEL_PARAMETERS = base.FoldPreprocessor, base.training_weights, base.MODEL_PARAMETERS

PRIMARY_SEED = 104729
ROBUSTNESS_SEEDS = (130363, 155921)
ALLOWED_CANDIDATES = ((0.55, 0.05), (0.55, 0.10), (0.60, 0.05), (0.60, 0.10))
PREDICTION_INDEX_POLICY = "CANONICAL_RANGE_INDEX_RESET_DROP"


def _binary_head(x: np.ndarray, target: pd.Series, weights: np.ndarray, seed: int):
    model: Any = base._model(seed) if target.nunique() > 1 else DummyClassifier(strategy="prior")
    model.fit(x, target, sample_weight=weights)
    return model


def _p1(model: Any, x: np.ndarray) -> np.ndarray:
    return base._probability(model, x, 1)


def canonicalize_predictions(predictions: pd.DataFrame) -> pd.DataFrame:
    """Apply R25's non-semantic, serialization-stable prediction index policy."""
    if "candidate_id" not in predictions:
        raise R25ContractError("R25_PREDICTION_CANDIDATE_ID_MISSING")
    out = predictions.copy().reset_index(drop=True)
    if out.candidate_id.isna().any() or not out.candidate_id.is_unique:
        raise R25ContractError("R25_PREDICTION_CANDIDATE_ID_INVALID")
    return out


def _prediction_schema(predictions: pd.DataFrame) -> dict[str, Any]:
    return {"columns": list(predictions.columns),
            "dtypes": {name: str(dtype) for name, dtype in predictions.dtypes.items()}}


def _candidate_id_sequence_hash(predictions: pd.DataFrame) -> str:
    return stable_hash(predictions.candidate_id.astype(str).tolist())


def score_asymmetric(train: pd.DataFrame, test: pd.DataFrame, features: list[str], seed: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Score R24's event head and independent P(UP|event), P(DOWN|event)."""
    preprocess = FoldPreprocessor.fit(train, features)
    x_train, x_test = preprocess.transform(train, features), preprocess.transform(test, features)
    event_target = train.label.isin((UP, DOWN)).astype(int)
    event_head = _binary_head(x_train, event_target, training_weights(train, event_target), seed)
    events = train.loc[event_target.astype(bool)].copy()
    if events.empty:
        raise R25ContractError("NO_EVENT_ROWS_FOR_DIRECTION_HEADS")
    x_events = preprocess.transform(events, features)
    up_target = (events.label == UP).astype(int)
    down_target = (events.label == DOWN).astype(int)
    up_head = _binary_head(x_events, up_target, training_weights(events, up_target), seed)
    down_head = _binary_head(x_events, down_target, training_weights(events, down_target), seed)
    result = canonicalize_predictions(test[["candidate_id", "event_id", "decision_timestamp_et", "label_end_timestamp_et", "underlying", "label"]])
    result["p_event"] = _p1(event_head, x_test)
    result["p_up"] = _p1(up_head, x_test)
    result["p_down"] = _p1(down_head, x_test)
    result["confidence"] = np.maximum(result.p_up, result.p_down)
    result["margin"] = np.abs(result.p_up - result.p_down)
    result["direction"] = np.where(result.p_up >= result.p_down, UP, DOWN)
    for name in ("gross_return", "target_hit", "actual_exit_timestamp_et", "exit_timestamp_et"):
        if name in test:
            result[name] = test[name].to_numpy()
    return canonicalize_predictions(result), {"preprocessor": preprocess, "event_head": event_head, "up_head": up_head, "down_head": down_head}


def apply_abstention(predictions: pd.DataFrame, confidence: float, margin: float) -> pd.DataFrame:
    if (confidence, margin) not in ALLOWED_CANDIDATES:
        raise R25ContractError("IMMUTABLE_THRESHOLD_SET_VIOLATION")
    out = predictions.copy()
    # R24 event/actionability remains frozen: p_event >= .60, then the existing
    # top-five-percent execution selection is applied by the economics routine.
    out["abstain"] = (out.confidence < confidence) | (out.margin < margin)
    out["predicted_label"] = np.where(out.abstain, "ABSTAIN", out.direction)
    out["combined_score"] = out.p_event * out.confidence
    return out


def direction_metrics(predictions: pd.DataFrame) -> dict[str, Any]:
    active = predictions.loc[~predictions.abstain].copy()
    events = active.loc[active.label.isin((UP, DOWN))]
    if len(events):
        from sklearn.metrics import balanced_accuracy_score, recall_score
        balanced = float(balanced_accuracy_score(events.label, events.predicted_label))
        up = float(recall_score(events.label, events.predicted_label, pos_label=UP, zero_division=0))
        down = float(recall_score(events.label, events.predicted_label, pos_label=DOWN, zero_division=0))
    else:
        balanced = up = down = float("nan")
    return {"primary_direction_metric": balanced, "up_recall": up, "down_recall": down,
            "active_rows": int(len(active)), "event_rows": int(len(events)),
            "coverage": float((~predictions.abstain).mean()) if len(predictions) else 0.0,
            "abstain_count": int(predictions.abstain.sum()), "test_rows": int(len(predictions))}


def _economics(predictions: pd.DataFrame, block_id: str) -> dict[str, Any]:
    # Preserve R24 first-stage eligibility and top-5% execution mechanics.
    eligible = predictions.loc[(~predictions.abstain) & predictions.p_event.ge(.60)].copy()
    if eligible.empty:
        return {"unique_primary_trades": 0, "mean_net_10bps": float("nan"), "median_net_10bps": float("nan"),
                "positive_pnl": 0.0, "daily_count": 0, "instrument_count": 0, "by_direction": {UP: 0, DOWN: 0}}
    eligible = eligible.nlargest(max(1, int(np.ceil(len(predictions) * .05))), "combined_score", keep="first")
    # base.economics expects p_event and a directional predicted_label, which are now guaranteed.
    details, trades = base.economics(eligible, block_id)
    details["by_direction"] = {str(k): int(v) for k, v in eligible.predicted_label.value_counts().items()}
    details["instrument_count"] = int(trades.underlying.nunique()) if not trades.empty else 0
    details["daily_count"] = int(trades.decision_timestamp_et.dt.normalize().nunique()) if not trades.empty else 0
    return details


def checkpoint_fingerprint(source: dict[str, Any], schedule: dict[str, Any], block_id: str, seed: int) -> str:
    return stable_hash({"r25_hypothesis": "ASYMMETRIC_DIRECTION_WITH_ABSTENTION", "source": source,
                        "schedule_hash": schedule["schedule_hash"], "block_id": block_id, "seed": int(seed),
                        "model_parameters": MODEL_PARAMETERS, "event_actionability": {"threshold": .60, "top_fraction": .05},
                        "allowed_candidates": ALLOWED_CANDIDATES, "purge_hours": 24, "embargo_hours": 24})


def score_block(train: pd.DataFrame, test: pd.DataFrame, source: dict[str, Any], schedule: dict[str, Any], block_id: str, seed: int, scratch: Path) -> pd.DataFrame:
    fingerprint = checkpoint_fingerprint(source, schedule, block_id, seed)
    expected_candidate_id_hash = _candidate_id_sequence_hash(canonicalize_predictions(test))
    path = Path(scratch) / "predictions" / f"{block_id}_{seed}.parquet"
    metadata = path.with_suffix(".json")
    if path.is_file() and metadata.is_file():
        import json
        cached = json.loads(metadata.read_text(encoding="utf-8"))
        if (cached.get("fingerprint") == fingerprint
                and cached.get("prediction_index_policy") == PREDICTION_INDEX_POLICY
                and cached.get("candidate_id_sequence_sha256") == expected_candidate_id_hash):
            resumed = canonicalize_predictions(pd.read_parquet(path))
            if (_candidate_id_sequence_hash(resumed) == expected_candidate_id_hash
                    and cached.get("prediction_schema") == _prediction_schema(resumed)):
                return resumed
    raw, _ = score_asymmetric(train, test, source["features"], seed)
    raw = canonicalize_predictions(raw)
    path.parent.mkdir(parents=True, exist_ok=True); raw.to_parquet(path, index=False)
    write_json(metadata, {"status": "COMPLETE", "fingerprint": fingerprint, "block_id": block_id, "seed": seed,
                          "prediction_index_policy": PREDICTION_INDEX_POLICY,
                          "candidate_id_sequence_sha256": _candidate_id_sequence_hash(raw),
                          "prediction_schema": _prediction_schema(raw)})
    return raw


def candidate_result(raw_by_block: dict[str, pd.DataFrame], confidence: float, margin: float) -> dict[str, Any]:
    blocks = []
    for block_id, raw in raw_by_block.items():
        pred = apply_abstention(raw, confidence, margin)
        blocks.append({"block_id": block_id, "metrics": direction_metrics(pred), "economic": _economics(pred, block_id)})
    metric_values = [x["metrics"]["primary_direction_metric"] for x in blocks]
    finite = [x for x in metric_values if np.isfinite(x)]
    coverage = [x["metrics"]["coverage"] for x in blocks]
    events = sum(x["metrics"]["event_rows"] for x in blocks)
    return {"confidence": confidence, "margin": margin, "blocks": blocks,
            "pooled_primary_direction_metric": float(np.mean(finite)) if finite else float("nan"),
            "minimum_block_coverage": float(min(coverage)) if coverage else 0.0,
            "coverage_range": float(max(coverage) - min(coverage)) if coverage else float("inf"),
            "event_rows": int(events), "selection_gate": bool(len(blocks) == 2 and events >= 60 and min(coverage) > 0.0)}


def choose_candidate(results: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [x for x in results if x["selection_gate"] and np.isfinite(x["pooled_primary_direction_metric"])]
    if not valid:
        raise R25ContractError("R25_SELECTION_COVERAGE_OR_SAMPLE_GATE_FAILED")
    # Metric first; material ties (1e-12) choose the lower threshold only when
    # its block coverage is at least as stable, then deterministic tuple order.
    valid.sort(key=lambda x: (-x["pooled_primary_direction_metric"], x["coverage_range"], x["confidence"], x["margin"]))
    return valid[0]


def candidate_freeze(source: dict[str, Any], schedule: dict[str, Any], selection: dict[str, Any], training_hashes: dict[str, str], code_hashes: dict[str, str]) -> dict[str, Any]:
    payload = {"status": "FROZEN", "hypothesis": "ASYMMETRIC_DIRECTION_WITH_ABSTENTION", "source_hashes": source,
               "training_row_hashes": training_hashes, "estimator": "HistGradientBoostingClassifier",
               "estimator_parameters": MODEL_PARAMETERS, "features": source["features"], "interactions": source["interactions"],
               "preprocessing": "FoldPreprocessor train-fold medians plus frozen interactions", "primary_seed": PRIMARY_SEED,
               "robustness_seeds": list(ROBUSTNESS_SEEDS), "confidence": selection["confidence"], "margin": selection["margin"],
               "selection_metric": "conditional_direction_balanced_accuracy pooled D1+D2",
               "tie_break": "metric desc; coverage stability; lower confidence; lower margin", "schedule_hash": schedule["schedule_hash"],
               "code_hashes": code_hashes, "allowed_candidates": [list(x) for x in ALLOWED_CANDIDATES]}
    payload["candidate_freeze_sha256"] = stable_hash(payload)
    return payload


def assert_frozen_candidate(freeze: dict[str, Any], confidence: float, margin: float) -> None:
    if freeze.get("candidate_freeze_sha256") != stable_hash({k: v for k, v in freeze.items() if k != "candidate_freeze_sha256"}):
        raise R25ContractError("R25_CANDIDATE_FREEZE_HASH_INVALID")
    if (freeze.get("confidence"), freeze.get("margin")) != (confidence, margin):
        raise R25ContractError("R25_CANDIDATE_MUTATION_FORBIDDEN")
