"""Deterministic immutable evaluation-contract serialization."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, fields
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


class ContractError(ValueError):
    pass


_REQUIRED = {
    "contract_version", "evaluator_version", "dataset_manifest_path", "dataset_hash",
    "label_contract_id", "execution_contract_id", "cost_contract_id", "split_contract_id",
    "feature_set_id", "feature_set_hash", "model_id", "model_config_hash", "model_artifact_hash",
    "frozen_runner_path", "frozen_runner_hash", "recovery_manifest_path", "recovery_manifest_hash",
    "split_manifest_path", "purge_minutes", "embargo_minutes", "train_windows",
    "development_windows", "confirmation_windows", "final_windows", "random_seed",
    "top_k_definition", "attempted_model_count", "attempted_configuration_count",
    "attempted_seed_count", "source_branch", "source_commit",
}


def _finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractError("NONFINITE_CONTRACT_VALUE")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractError("NONSTRING_CONTRACT_KEY")
            _finite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _finite(item)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_thaw(v) for v in value]
    return value


def canonical_json(value: Any) -> str:
    _finite(value)
    return json.dumps(_thaw(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _path(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError("CONTRACT_PATH_REQUIRED")
    return str(Path(value).resolve(strict=False)).replace("\\", "/")


@dataclass(frozen=True)
class EvaluationContract:
    contract_version: str; evaluator_version: str; dataset_manifest_path: str; dataset_hash: str
    label_contract_id: str; execution_contract_id: str; cost_contract_id: str; split_contract_id: str
    feature_set_id: str; feature_set_hash: str; model_id: str; model_config_hash: str; model_artifact_hash: str
    frozen_runner_path: str; frozen_runner_hash: str; recovery_manifest_path: str; recovery_manifest_hash: str
    split_manifest_path: str; purge_minutes: int; embargo_minutes: int; train_windows: tuple[Any, ...]
    development_windows: tuple[Any, ...]; confirmation_windows: tuple[Any, ...]; final_windows: tuple[Any, ...]
    random_seed: int; top_k_definition: str; attempted_model_count: int; attempted_configuration_count: int
    attempted_seed_count: int; source_branch: str; source_commit: str

    def __post_init__(self) -> None:
        payload = {item.name: getattr(self, item.name) for item in fields(self)}
        if set(payload) != _REQUIRED:
            raise ContractError("CONTRACT_SCHEMA_INVALID")
        for name, value in payload.items():
            if value is None or value == "":
                raise ContractError(f"CONTRACT_REQUIRED:{name}")
            _finite(value)
        for name in ("dataset_manifest_path", "frozen_runner_path", "recovery_manifest_path", "split_manifest_path"):
            object.__setattr__(self, name, _path(getattr(self, name)))
        for name in ("train_windows", "development_windows", "confirmation_windows", "final_windows"):
            value = getattr(self, name)
            if not isinstance(value, (tuple, list)):
                raise ContractError(f"CONTRACT_WINDOW_TYPE:{name}")
            frozen = _freeze(value)
            for window in frozen:
                if not isinstance(window, Mapping) or set(window) < {"start", "end", "timezone"}:
                    raise ContractError(f"CONTRACT_WINDOW_INVALID:{name}")
            object.__setattr__(self, name, frozen)
        for name in ("purge_minutes", "embargo_minutes", "random_seed", "attempted_model_count", "attempted_configuration_count", "attempted_seed_count"):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 0 or (name in ("purge_minutes", "embargo_minutes") and value == 0):
                raise ContractError(f"CONTRACT_INTEGER_INVALID:{name}")

    def payload(self) -> dict[str, Any]:
        return {item.name: _thaw(getattr(self, item.name)) for item in fields(self)}

    @property
    def evaluation_contract_hash(self) -> str:
        return hashlib.sha256(canonical_json(self.payload()).encode("utf-8")).hexdigest()
