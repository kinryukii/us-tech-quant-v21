"""Read-only resolution of the three champion registries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from .schemas import ComponentIdentity, ROLES


EXPECTED = {
    "ALPHA": ("ALPHA_CHAMPION", "A2_HGB", "model_artifact", "model_sha256"),
    "RISK": ("RISK_CHAMPION", "R6_BAD_ASYMMETRY", "model_artifact", "model_sha256"),
    "EXECUTION": ("EXECUTION_CHAMPION", "E5_COMBINED_CONSERVATIVE", "config_artifact", "config_sha256"),
}


class RegistryResolutionError(ValueError):
    pass


def resolve_components(
    registry_paths: Mapping[str, str],
    *,
    synthetic_overrides: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, ComponentIdentity]:
    overrides = synthetic_overrides or {}
    resolved = {}
    for role in ROLES:
        if role not in registry_paths:
            raise RegistryResolutionError(f"registry path missing for {role}")
        path = Path(registry_paths[role])
        registry = json.loads(path.read_text(encoding="utf-8"))
        expected_role, expected_id, artifact_field, hash_field = EXPECTED[role]
        matches = [item for item in registry.get("models", []) if item.get("role") == expected_role]
        if len(matches) != 1:
            raise RegistryResolutionError(f"expected exactly one {expected_role}")
        entry = matches[0]
        if entry.get("model_id") != expected_id or entry.get("model_family") != role:
            raise RegistryResolutionError(f"champion identity mismatch for {role}")
        override = overrides.get(role, {})
        resolved[role] = ComponentIdentity(
            role=role, model_id=entry["model_id"], registry_role=entry["role"], status=entry["status"],
            freeze_id=str(override.get("freeze_id", entry.get("benchmark_id", "UNKNOWN"))),
            artifact_path=str(override.get("artifact_path", entry.get(artifact_field, "UNKNOWN"))),
            artifact_sha256=str(override.get("artifact_sha256", entry.get(hash_field, "UNKNOWN"))),
            training_cutoff=str(entry.get("training_cutoff", "UNKNOWN")),
            uses_2026_training=entry.get("uses_2026_training", "UNKNOWN"),
            uses_2026_parameter_search=entry.get("uses_2026_parameter_search", "UNKNOWN"),
            uses_2026_model_selection=entry.get("uses_2026_model_selection", "UNKNOWN"),
            prospective_start_date=str(override.get("prospective_start_date", entry.get("prospective_start_date", "UNKNOWN"))),
        )
    return resolved
