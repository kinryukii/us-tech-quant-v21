"""Typed contracts for unified forward-shadow orchestration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


ROLES = ("ALPHA", "RISK", "EXECUTION")
RUNNER_VERSION = "A2_FORWARD_SHADOW_UNIFIED_RUNNER_R1"
STATES = (
    "PREPARED", "STAGED", "VALIDATED", "COMMITTING", "COMMITTED",
    "FAILED_PRE_COMMIT", "FAILED_COMMIT", "RECOVERY_REQUIRED",
)
FAILURE_CODES = {
    "FAIL_PREFLIGHT", "FAIL_CANONICAL_NOT_READY", "FAIL_FROZEN_IDENTITY", "FAIL_GOVERNANCE",
    "FAIL_COMPONENT_ALPHA", "FAIL_COMPONENT_RISK", "FAIL_COMPONENT_EXECUTION",
    "FAIL_DATE_ALIGNMENT", "FAIL_LINEAGE", "FAIL_SECURITY_ALIGNMENT",
    "FAIL_DUPLICATE_CONFLICT", "FAIL_HISTORY_CHAIN", "FAIL_COMMIT", "RECOVERY_REQUIRED",
}


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def valid_sha256(value: Any) -> bool:
    text = str(value or "").lower()
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


@dataclass(frozen=True)
class ComponentIdentity:
    role: str
    model_id: str
    registry_role: str
    status: str
    freeze_id: str
    artifact_path: str
    artifact_sha256: str
    training_cutoff: str
    uses_2026_training: bool | str
    uses_2026_parameter_search: bool | str
    uses_2026_model_selection: bool | str
    prospective_start_date: str = "UNKNOWN"

    @property
    def hashes_materialized(self) -> bool:
        return valid_sha256(self.artifact_sha256)


@dataclass(frozen=True)
class RunIdentity:
    target_date: str
    canonical_manifest_sha256: str
    universe_id: str
    config_sha256: str
    components: Mapping[str, ComponentIdentity]
    trading_calendar_id: str = "UNKNOWN"
    trading_calendar_sha256: str = "UNKNOWN"
    runner_version: str = RUNNER_VERSION

    def immutable_payload(self) -> dict[str, Any]:
        return {
            "target_date": self.target_date,
            "canonical_manifest_sha256": self.canonical_manifest_sha256,
            "universe_id": self.universe_id,
            "config_sha256": self.config_sha256,
            "runner_version": self.runner_version,
            "trading_calendar_id": self.trading_calendar_id,
            "trading_calendar_sha256": self.trading_calendar_sha256,
            "components": {
                role: {
                    "model_id": component.model_id,
                    "freeze_id": component.freeze_id,
                    "artifact_sha256": component.artifact_sha256,
                }
                for role, component in sorted(self.components.items())
            },
        }

    @property
    def shadow_key(self) -> str:
        return canonical_sha256(self.immutable_payload())

    @property
    def run_id(self) -> str:
        return f"FS_{self.target_date.replace('-', '')}_{self.shadow_key[:16]}"

    def to_dict(self) -> dict[str, Any]:
        return {**self.immutable_payload(), "shadow_key": self.shadow_key, "run_id": self.run_id}


@dataclass(frozen=True)
class ComponentResult:
    role: str
    status: str
    target_date: str
    run_id: str
    model_id: str
    records: tuple[Mapping[str, Any], ...] = ()
    input_alpha_run_id: str | None = None
    input_risk_run_id: str | None = None
    fit_called: bool = False
    training_rows_2026: int = 0
    parameter_search_run: bool = False
    threshold_search_run: bool = False
    model_selection_run: bool = False
    broker_action: bool = False
    security_alignment_reason: str | None = None
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RunnerConfig:
    schema_version: str = "1.0.0"
    runner_id: str = RUNNER_VERSION
    require_frozen_hashes: bool = True
    append_only: bool = True
    allow_overwrite: bool = False
    allow_duplicate_identical: bool = False
    require_same_target_date: bool = True
    require_lineage_match: bool = True
    auto_canonical_refresh: bool = False
    broker_action_allowed: bool = False
    training_allowed: bool = False
    parameter_search_allowed: bool = False
    model_selection_allowed: bool = False
    staging_root: str = "REQUIRED_AT_PRODUCTION"
    authoritative_shadow_root: str = "REQUIRED_AT_PRODUCTION"
    readiness_root: str = "REQUIRED_AT_PRODUCTION"
    production_binding_manifest: str = "REQUIRED_AT_PRODUCTION"
    production_binding_sha256: str = "UNKNOWN"
    history_hash_chain_enabled: bool = True
    retain_failed_staging: bool = True
    risk_must_be_subset_of_alpha: bool = True
    require_risk_for_every_alpha: bool = False
    execution_must_be_subset_of_alpha: bool = True
    allow_execution_subset_with_reason: bool = True
    registry_paths: Mapping[str, str] = field(default_factory=dict)
    production_adapters: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RunnerConfig":
        unknown = set(payload) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"unknown runner config fields: {sorted(unknown)}")
        result = cls(**dict(payload))
        result.validate()
        return result

    def validate(self) -> None:
        if self.runner_id != RUNNER_VERSION:
            raise ValueError("runner identity mismatch")
        if set(self.registry_paths) != set(ROLES) or set(self.production_adapters) != set(ROLES):
            raise ValueError("exact ALPHA/RISK/EXECUTION configuration is required")
        required_true = (
            "require_frozen_hashes", "append_only", "require_same_target_date",
            "require_lineage_match", "history_hash_chain_enabled", "retain_failed_staging",
        )
        required_false = (
            "allow_overwrite", "allow_duplicate_identical", "auto_canonical_refresh", "broker_action_allowed", "training_allowed",
            "parameter_search_allowed", "model_selection_allowed",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise ValueError("fail-closed runner gates must remain enabled")
        if any(getattr(self, name) is not False for name in required_false):
            raise ValueError("unsafe runner capability enabled")


@dataclass(frozen=True)
class CanonicalReadiness:
    target_date: str
    as_of_date: str
    canonical_manifest: str
    canonical_manifest_sha256: str
    universe_id: str
    available_dates: tuple[str, ...]
    eligible_trading_dates: tuple[str, ...]
    feature_ready_dates: tuple[str, ...]
    universe_ready_dates: tuple[str, ...]
    partial_dates: tuple[str, ...] = ()
    trading_calendar_id: str = "UNKNOWN"
    trading_calendar_sha256: str = "UNKNOWN"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CanonicalReadiness":
        values = dict(payload)
        for name in (
            "available_dates", "eligible_trading_dates", "feature_ready_dates",
            "universe_ready_dates", "partial_dates",
        ):
            values[name] = tuple(values.get(name, ()))
        return cls(**values)
