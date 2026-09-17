from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .contracts import stable_hash


class SplitError(RuntimeError):
    pass


@dataclass(frozen=True)
class Fold:
    name: str
    train_index: np.ndarray
    valid_index: np.ndarray


BLOCKS = ("OOF_2020", "OOF_2021", "OOF_2022", "OOF_2023", "OOF_2024", "OOF_2025_JAN")
VALIDATION_BLOCKS = BLOCKS[1:]


def _validate_fold(frame: pd.DataFrame, fold: Fold, purge_minutes: int, embargo_minutes: int) -> None:
    train, valid = frame.loc[fold.train_index], frame.loc[fold.valid_index]
    if train.empty or valid.empty or set(fold.train_index) & set(fold.valid_index):
        raise SplitError(f"STOP_FAST4_FOLD_OVERLAP_OR_EMPTY:{fold.name}")
    valid_start = valid.decision_timestamp_utc.min()
    if not (train.decision_timestamp_utc < valid_start).all():
        raise SplitError(f"STOP_FAST4_NONCHRONOLOGICAL_FOLD:{fold.name}")
    if not (train.target_end_timestamp_utc < valid_start - pd.Timedelta(minutes=embargo_minutes)).all():
        raise SplitError(f"STOP_FAST4_PURGE_EMBARGO_FAILURE:{fold.name}")
    if (train.candidate_id.isin(valid.candidate_id)).any():
        raise SplitError(f"STOP_FAST4_CANDIDATE_OVERLAP:{fold.name}")


def outer_folds(frame: pd.DataFrame, purge_minutes: int = 60, embargo_minutes: int = 60) -> list[Fold]:
    folds = []
    for valid_block in VALIDATION_BLOCKS:
        position = BLOCKS.index(valid_block)
        valid_mask = frame.validation_slice.eq(valid_block)
        valid_start = frame.loc[valid_mask, "decision_timestamp_utc"].min()
        train_mask = frame.validation_slice.isin(BLOCKS[:position]) & frame.target_end_timestamp_utc.lt(valid_start - pd.Timedelta(minutes=embargo_minutes))
        fold = Fold(valid_block, frame.index[train_mask].to_numpy(), frame.index[valid_mask].to_numpy())
        _validate_fold(frame, fold, purge_minutes, embargo_minutes)
        folds.append(fold)
    return folds


def inner_folds(frame: pd.DataFrame, outer_train_index: np.ndarray, count: int = 3,
                purge_minutes: int = 60, embargo_minutes: int = 60) -> list[Fold]:
    subset = frame.loc[outer_train_index].sort_values(["trading_date", "decision_timestamp_utc", "candidate_id"], kind="mergesort")
    days = np.array(sorted(subset.trading_date.unique()))
    if len(days) < 8:
        raise SplitError("STOP_FAST4_INSUFFICIENT_INNER_DAYS")
    boundaries = np.linspace(0.50, 1.0, count + 1)
    folds = []
    for i in range(count):
        left = max(1, int(np.floor(boundaries[i] * len(days))))
        right = len(days) if i == count - 1 else max(left + 1, int(np.floor(boundaries[i + 1] * len(days))))
        valid_days = set(days[left:right])
        valid_mask = subset.trading_date.isin(valid_days)
        valid_start = subset.loc[valid_mask, "decision_timestamp_utc"].min()
        train_mask = subset.trading_date.isin(set(days[:left])) & subset.target_end_timestamp_utc.lt(valid_start - pd.Timedelta(minutes=embargo_minutes))
        fold = Fold(f"INNER_{i + 1}", subset.index[train_mask].to_numpy(), subset.index[valid_mask].to_numpy())
        _validate_fold(frame, fold, purge_minutes, embargo_minutes)
        folds.append(fold)
    return folds


def fold_manifest(frame: pd.DataFrame, outer: list[Fold], inner_by_outer: dict[str, list[Fold]]) -> dict[str, Any]:
    def row(fold: Fold) -> dict[str, Any]:
        train, valid = frame.loc[fold.train_index], frame.loc[fold.valid_index]
        return {
            "name": fold.name, "train_count": len(train), "valid_count": len(valid),
            "train_start": str(train.decision_timestamp_utc.min()), "train_end": str(train.decision_timestamp_utc.max()),
            "train_target_end_max": str(train.target_end_timestamp_utc.max()),
            "valid_start": str(valid.decision_timestamp_utc.min()), "valid_end": str(valid.decision_timestamp_utc.max()),
            "train_candidate_sha256": stable_hash(sorted(train.candidate_id.astype(str))),
            "valid_candidate_sha256": stable_hash(sorted(valid.candidate_id.astype(str))),
            "overlap_count": len(set(train.candidate_id) & set(valid.candidate_id)),
        }
    payload = {"purge_minutes": 60, "embargo_minutes": 60, "outer": []}
    for fold in outer:
        payload["outer"].append({**row(fold), "inner": [row(inner) for inner in inner_by_outer[fold.name]]})
    payload["manifest_sha256"] = stable_hash(payload)
    return payload
