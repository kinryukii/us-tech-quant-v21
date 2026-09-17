"""Champion/challenger registry validation and immutable transition gates."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Iterable

from .schemas import MODEL_FAMILIES


REQUIRED_MODEL_FIELDS = {
    "model_id", "model_family", "role", "status", "created_at", "training_cutoff",
    "universe_id", "feature_set_id", "model_artifact", "model_sha256", "config_artifact",
    "config_sha256", "benchmark_id", "research_run_id", "promotion_state",
    "prospective_state", "notes", "uses_2026_training", "uses_2026_parameter_search",
    "uses_2026_model_selection",
}
ALLOWED_TRANSITIONS = {
    "RESEARCH_CANDIDATE": {"VALID_PRE2026"},
    "VALID_PRE2026": {"STABLE_CHALLENGER"},
    "STABLE_CHALLENGER": {"PROSPECTIVE_SHADOW"},
    "PROSPECTIVE_SHADOW": {"PROMOTION_ELIGIBLE"},
    "PROMOTION_ELIGIBLE": {"PROMOTED_CHAMPION"},
    "PROMOTED_CHAMPION": set(),
}
CHAMPION_ROLES = {"ALPHA_CHAMPION", "RISK_CHAMPION", "EXECUTION_CHAMPION"}


class RegistryError(ValueError):
    pass


def load_registry(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_registry(payload)
    return payload


def load_registries(directory: Path) -> dict[str, dict[str, Any]]:
    result = {}
    for family in sorted(MODEL_FAMILIES):
        path = directory / f"{family.lower()}_registry.json"
        result[family] = load_registry(path)
    return result


def validate_registry(payload: dict[str, Any]) -> None:
    family = payload.get("model_family")
    if family not in MODEL_FAMILIES:
        raise RegistryError(f"invalid registry model_family: {family}")
    governance = payload.get("governance", {})
    if governance.get("auto_promotion_forbidden") is not True:
        raise RegistryError("AUTO_PROMOTION_FORBIDDEN must be true")
    if governance.get("requires_explicit_user_authorization") is not True:
        raise RegistryError("explicit user authorization gate is required")
    entries = payload.get("models")
    if not isinstance(entries, list) or not entries:
        raise RegistryError("registry must contain models")
    ids: set[str] = set()
    champions = 0
    for entry in entries:
        missing = REQUIRED_MODEL_FIELDS - set(entry)
        if missing:
            raise RegistryError(f"{entry.get('model_id', '<unknown>')} missing fields: {sorted(missing)}")
        if entry["model_family"] != family:
            raise RegistryError(f"family contamination: {entry['model_id']}")
        if entry["model_id"] in ids:
            raise RegistryError(f"duplicate model_id: {entry['model_id']}")
        ids.add(entry["model_id"])
        if entry["role"] in CHAMPION_ROLES:
            champions += 1
    if champions != 1:
        raise RegistryError(f"{family} registry must have exactly one champion, got {champions}")


def transition_model(
    registry: dict[str, Any],
    model_id: str,
    target_state: str,
    *,
    explicit_user_authorization: bool = False,
) -> dict[str, Any]:
    """Return a transitioned copy; never mutates the supplied registry."""
    validate_registry(registry)
    updated = copy.deepcopy(registry)
    entry = next((item for item in updated["models"] if item["model_id"] == model_id), None)
    if entry is None:
        raise RegistryError(f"unknown model_id: {model_id}")
    current = entry["promotion_state"]
    if target_state not in ALLOWED_TRANSITIONS.get(current, set()):
        raise RegistryError(f"invalid transition: {current} -> {target_state}")
    if target_state == "PROMOTED_CHAMPION" and not explicit_user_authorization:
        raise RegistryError("PROMOTED_CHAMPION requires explicit user authorization")
    if entry["role"] in CHAMPION_ROLES:
        raise RegistryError("ordinary transitions cannot alter an incumbent champion")
    entry["promotion_state"] = target_state
    if target_state == "PROMOTED_CHAMPION":
        incumbent = next(item for item in updated["models"] if item["role"] in CHAMPION_ROLES)
        incumbent["role"] = f"FORMER_{updated['model_family']}_CHAMPION"
        incumbent["status"] = "SUPERSEDED_BY_EXPLICIT_AUTHORIZATION"
        entry["role"] = f"{updated['model_family']}_CHAMPION"
        entry["status"] = "PROMOTED_CHAMPION"
    validate_registry(updated)
    return updated


def build_leaderboard(
    registry: dict[str, Any], judgements: Iterable[dict[str, Any]], *, family: str,
) -> dict[str, Any]:
    """Group evidence by governance class. It deliberately performs no metric sort."""
    validate_registry(registry)
    if family != registry["model_family"]:
        raise RegistryError("requested family does not match registry")
    champion = next(item for item in registry["models"] if item["role"] in CHAMPION_ROLES)
    buckets: dict[str, list[dict[str, Any]]] = {
        "STABLE_CHALLENGERS": [], "PROMISING": [], "NO_MATERIAL_EDGE": [], "UNSTABLE": [], "INVALID": [],
    }
    bucket_for = {
        "A_STABLE_CHALLENGER": "STABLE_CHALLENGERS",
        "B_PROMISING_BUT_UNPROVEN": "PROMISING",
        "C_NO_MATERIAL_EDGE": "NO_MATERIAL_EDGE",
        "D_UNSTABLE": "UNSTABLE",
        "E_INVALID": "INVALID",
    }
    for judgement in judgements:
        if judgement.get("model_family") != family:
            continue
        classification = judgement.get("classification")
        if classification not in bucket_for:
            raise RegistryError(f"unknown classification: {classification}")
        buckets[bucket_for[classification]].append(judgement)
    judged_ids = {str(item.get("model_id")) for rows in buckets.values() for item in rows}
    for entry in registry["models"]:
        if entry["role"] in CHAMPION_ROLES or entry["model_id"] in judged_ids:
            continue
        registry_only = {
            "model_id": entry["model_id"], "model_family": family, "trial_id": None,
            "registry_status": entry["status"], "evidence_source": "REGISTRY_ONLY",
        }
        target = "UNSTABLE" if "UNSTABLE" in entry["status"] else "PROMISING"
        buckets[target].append(registry_only)
    for rows in buckets.values():
        rows.sort(key=lambda row: (str(row.get("model_id", "")), str(row.get("trial_id", ""))))
    return {"model_family": family, "champion": champion, **buckets}
