"""Immutable, review-gated registry for research branches and aliases.

The registry stores compact control-plane metadata only. Factor and trial
ledgers remain external references; outcome/performance metrics are forbidden.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import posixpath
import re
import shutil
import unicodedata
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = 1
GENESIS = "GENESIS"
CURRENT_FILE = "CURRENT.json"
EVENTS_FILE = "events.jsonl"
SNAPSHOTS_DIR = "snapshots"
REGISTRY_FILE = "research_registry.parquet"
ALIASES_FILE = "registry_aliases.parquet"
MANIFEST_FILE = "manifest.json"
VALIDATION_FILE = "validation.json"
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
TERMINAL_STATUSES = {"CLOSED", "TOMBSTONED", "SUPERSEDED"}
ENTITY_STATUSES = {"OPEN", "ACTIVE", "CLOSED", "TOMBSTONED", "SUPERSEDED"}
PROPOSAL_DECISIONS = {
    "PASS_DISTINCT_INFORMATION_SOURCE",
    "EXTEND_EXISTING",
    "BLOCKED_EXACT_DUPLICATE",
    "BLOCKED_FUNCTIONAL_REDUNDANCY",
    "BLOCKED_CLOSED_BRANCH",
    "BLOCKED_SUPERSEDED_BRANCH",
    "BLOCKED_ALIAS_CONFLICT",
    "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE",
}

LINEAGE_FIELD_KINDS = {
    "parent_entity_id": "ancestry",
    "parent_entity_ids": "ancestry",
    "base_entity_id": "ancestry",
    "base_entity_ids": "ancestry",
    "derived_from_entity_id": "ancestry",
    "derived_from_entity_ids": "ancestry",
    "predecessor_entity_id": "ancestry",
    "predecessor_entity_ids": "ancestry",
    "replaces_entity_id": "ancestry",
    "replaces_entity_ids": "ancestry",
    "equivalent_to": "equivalence",
    "equivalent_to_entity_id": "equivalence",
    "equivalent_to_entity_ids": "equivalence",
    "duplicate_with": "equivalence",
    "duplicate_with_entity_id": "equivalence",
    "duplicate_with_entity_ids": "equivalence",
    "canonical_or_duplicate_target": "equivalence",
    "canonical_or_duplicate_target_id": "equivalence",
    "canonical_or_duplicate_target_ids": "equivalence",
}
AUTHORITATIVE_REFERENCE_FIELDS = {
    "authoritative_artifact_ref",
    "authoritative_artifact_refs",
    "distinct_source_contract_ref",
    "distinct_source_contract_refs",
    "frozen_source_contract_ref",
    "frozen_source_contract_refs",
    "source_contract_ref",
    "source_contract_refs",
}
IDENTITY_STEM_DISCARD_TOKENS = {
    "branch",
    "mechanism",
    "model",
    "models",
    "rename",
    "renamed",
    "renaming",
    "repackage",
    "repackaged",
    "repackaging",
    "retry",
    "swap",
    "threshold",
    "thresholds",
    "tweak",
    "tweaked",
    "variant",
    "wrapper",
    "xgboost",
    "lightgbm",
    "catboost",
    "randomforest",
    "svm",
    "transformer",
    "classifier",
    "ensemble",
}
MODEL_LABEL_TOKENS = {
    "catboost",
    "classifier",
    "ensemble",
    "lightgbm",
    "randomforest",
    "svm",
    "transformer",
    "xgboost",
}
RAW_IDENTITY_PLACEHOLDERS = {
    "human-contract-named-family-only",
    "not-applicable",
    "unavailable",
    "unknown",
}

ENTITY_COLUMNS = (
    "entity_id",
    "canonical_name",
    "entity_type",
    "status",
    "specification_fingerprint",
    "information_source_fingerprint",
    "mechanism_fingerprint",
    "decision_layer",
    "evidence_source_temporal_status",
    "excluded_source_refs_json",
    "temporal_evidence_limitations_json",
    "factor_ledger_ref",
    "trial_ledger_ref",
    "trial_ledger_failure_row_count",
    "post_2025_observation_count",
    "minimum_system_manifest_ref",
    "parent_entity_id",
    "metadata_json",
    "row_hash",
)
ALIAS_COLUMNS = ("alias_normalized", "alias", "entity_id", "row_hash")
ENTITY_LOGICAL_FIELDS = (
    "entity_id",
    "canonical_name",
    "entity_type",
    "status",
    "specification_fingerprint",
    "information_source_fingerprint",
    "mechanism_fingerprint",
    "decision_layer",
    "evidence_source_temporal_status",
    "excluded_source_refs",
    "temporal_evidence_limitations",
    "factor_ledger_ref",
    "trial_ledger_ref",
    "trial_ledger_failure_row_count",
    "post_2025_observation_count",
    "minimum_system_manifest_ref",
    "parent_entity_id",
)
REQUIRED_ENTITY_FIELDS = (
    "entity_id",
    "canonical_name",
    "entity_type",
    "status",
    "specification_fingerprint",
    "information_source_fingerprint",
    "mechanism_fingerprint",
    "decision_layer",
    "evidence_source_temporal_status",
    "excluded_source_refs",
    "temporal_evidence_limitations",
)
PERFORMANCE_KEY_TOKENS = {
    "accuracy",
    "alpha",
    "ap",
    "auc",
    "auroc",
    "cagr",
    "calibration",
    "drawdown",
    "f1",
    "ic",
    "information_ratio",
    "gini",
    "lift",
    "mae",
    "mcc",
    "metric",
    "mse",
    "nav",
    "performance",
    "pnl",
    "precision",
    "profit",
    "recall",
    "return",
    "returns",
    "rmse",
    "r2",
    "sharpe",
    "sensitivity",
    "specificity",
    "sortino",
}
PERFORMANCE_KEY_NAMES = {
    "hit_rate",
    "information_ratio",
    "rank_ic",
    "win_rate",
}
PERFORMANCE_KEY_PREFIXES = (
    "classification",
    "hit_rate",
    "realized_label",
    "tail_event",
    "win_rate",
)
PERFORMANCE_KEY_PHRASES = (
    "area_under_roc_curve",
    "brier_score",
    "confusion_matrix",
    "cross_entropy",
    "false_positive_rate",
    "ks_statistic",
    "log_loss",
    "net_asset_value",
    "outcome_derived_metadata",
    "p_and_l",
    "pr_curve",
    "r_squared",
    "roc_curve",
    "true_positive_rate",
)
PERFORMANCE_VALUE_TERM = re.compile(
    r"\b(?:"
    r"accuracy|alpha|ap|auc|auroc|average\s+precision|brier(?:\s+score)?|calibration|"
    r"cagr|confusion\s+matrix|cross\s+entropy|drawdown|f1|false\s+positive\s+rate|"
    r"gini|hit\s+rate|ic|information\s+coefficient|ks\s+statistic|lift|log\s+loss|"
    r"mae|mcc|mse|nav|net\s+asset\s+value|p\s*(?:and|&)\s*l|pnl|precision|profit|"
    r"pr\s+curve|r(?:ank\s+)?ic|r\s*(?:squared|\^?2)|recall|return|returns|rmse|"
    r"roc\s+curve|sensitivity|sharpe|sortino|specificity|tail\s+event|"
    r"true\s+positive\s+rate|win\s+rate"
    r")\b",
    re.IGNORECASE,
)
NUMERIC_VALUE = re.compile(
    r"(?<![A-Za-z0-9])[-+]?(?:\d+(?:\.\d+)?|\.\d+)%?(?![A-Za-z])"
)
OUTCOME_EVALUATION_TERM = re.compile(
    r"\b(?:achieved|evaluation|evaluated|holdout|measured|observed|outcome|performance|"
    r"prospective|realized|reported|result|score|test(?:ed)?|validation|validated|2026)\b",
    re.IGNORECASE,
)
QUALITATIVE_VALUE_TERM = re.compile(
    r"\b(?:bad|better|failed|good|high|improved|low|passed|poor|strong|weak|worse)\b",
    re.IGNORECASE,
)
SPELLED_NUMBER_TERM = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|"
    r"forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|percent)\b",
    re.IGNORECASE,
)
STRUCTURAL_FORWARD_TARGET = re.compile(
    r"\b(?:\d+\s*[- ]?\s*(?:day|week|month|year|d|w|m|y)s?\s+(?:forward|ahead)|"
    r"(?:forward|ahead)\s+\d+\s*[- ]?\s*(?:day|week|month|year|d|w|m|y)s?)\b"
    r".{0,32}\b(?:return|label|target)\b",
    re.IGNORECASE,
)
SAFE_STRUCTURAL_VALUE_FIELDS = {
    "economic_thesis",
    "label_definition",
    "prior_negative_evidence",
    "research_thesis",
    "tail_target_definition",
    "target_definition",
    "target_specification",
    "winner_target_definition",
}
TARGET_DEFINITION_FIELDS = {
    "label_definition",
    "tail_target_definition",
    "target_definition",
    "target_specification",
    "winner_target_definition",
}
HARD_REALIZED_CONTEXT = re.compile(
    r"\b(?:achieved|holdout|measured|observed|prospective|realized|reported)\b|"
    r"\b(?:evaluation|test|validation)\s+(?:metric|result|score|value)\b|"
    r"\bpost[- ]?2025\b|(?<!pre-)(?<!pre )\b2026\b",
    re.IGNORECASE,
)


class RegistryError(ValueError):
    """Fail-closed registry contract violation."""


def canonical_json(value: Any) -> bytes:
    """Return the one canonical byte representation used by every hash."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RegistryError(f"NON_CANONICAL_JSON:{exc}") from exc


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def specification_fingerprint(specification: Any) -> str:
    """Produce a deterministic specification identity."""
    return sha256_value(specification)


def normalize_alias(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value)).casefold().strip()
    normalized = "-".join("".join(ch if ch.isalnum() else " " for ch in text).split())
    if not normalized:
        raise RegistryError("EMPTY_ALIAS")
    return normalized


def _require_sha(value: Any, field: str) -> str:
    text = str(value).strip().lower()
    if not HEX_SHA256.fullmatch(text):
        raise RegistryError(f"INVALID_SHA256:{field}")
    return text


def _string(value: Any, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    text = str(value).strip()
    if not text:
        if optional:
            return None
        raise RegistryError(f"EMPTY_FIELD:{field}")
    return text


def _string_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        raise RegistryError(f"FIELD_MUST_BE_STRING_LIST:{field}")
    return sorted({str(item).strip() for item in values if str(item).strip()})


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise RegistryError(f"FIELD_MUST_BE_NONNEGATIVE_INTEGER:{field}")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise RegistryError(f"FIELD_MUST_BE_NONNEGATIVE_INTEGER:{field}") from exc
    if result < 0 or (isinstance(value, float) and not math.isclose(value, result)):
        raise RegistryError(f"FIELD_MUST_BE_NONNEGATIVE_INTEGER:{field}")
    return result


def _optional_nonnegative_int(value: Any, field: str) -> int | None:
    return None if value is None else _nonnegative_int(value, field)


def _failure_count_regressed(old: int | None, new: int | None) -> bool:
    return old is not None and (new is None or new < old)


def _normalized_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key).casefold()).strip("_")


def _performance_field_paths(value: Any, prefix: str = "") -> list[str]:
    findings: list[str] = []
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = _normalized_key(raw_key)
            path = f"{prefix}.{raw_key}" if prefix else str(raw_key)
            tokens = set(key.split("_"))
            if (
                key in PERFORMANCE_KEY_NAMES
                or any(key == prefix_key or key.startswith(prefix_key + "_") for prefix_key in PERFORMANCE_KEY_PREFIXES)
                or any(phrase in key for phrase in PERFORMANCE_KEY_PHRASES)
                or bool(tokens & PERFORMANCE_KEY_TOKENS)
            ):
                findings.append(path)
            findings.extend(_performance_field_paths(child, path))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            findings.extend(_performance_field_paths(child, f"{prefix}[{index}]"))
    return findings


def _string_has_performance_value(value: str, path: str = "") -> bool:
    text = unicodedata.normalize("NFKC", value)
    metric_matches = list(PERFORMANCE_VALUE_TERM.finditer(text))
    if not metric_matches:
        return False
    numeric_values: list[re.Match[str]] = []
    for number in NUMERIC_VALUE.finditer(text):
        numeric = number.group(0).lstrip("+-").rstrip("%")
        if re.fullmatch(r"\d{4}", numeric) and 1900 <= int(numeric) <= 2100:
            continue
        numeric_values.append(number)
    outcome_context = bool(OUTCOME_EVALUATION_TERM.search(text))
    qualitative_value = bool(QUALITATIVE_VALUE_TERM.search(text))
    spelled_value = bool(SPELLED_NUMBER_TERM.search(text))
    governance_denial = bool(
        re.search(
            r"\b(?:excluded|never|no|not|omitted|unavailable|without)\b",
            text,
            re.IGNORECASE,
        )
    )
    field = _normalized_key(path.rsplit(".", 1)[-1].split("[", 1)[0]) if path else ""
    hard_context_text = (
        re.sub(r"\brealized\b", "structural-label", text, flags=re.IGNORECASE)
        if field in TARGET_DEFINITION_FIELDS
        else text
    )
    assignment_value = bool(
        re.search(
            r"=\s*[-+]?(?:\d+(?:\.\d+)?|\.\d+)\s*%?\b",
            text,
            re.IGNORECASE,
        )
    )
    spelled_appended_value = bool(
        re.search(
            r"\breturn\b\s+(?:(?:is|of|was)\s+)?(?:minus\s+|negative\s+|plus\s+|positive\s+)?"
            r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
            r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|"
            r"forty|fifty|sixty|seventy|eighty|ninety|hundred)(?:[ -]+(?:one|two|three|four|"
            r"five|six|seven|eight|nine|ten|hundred))*[ -]+percent\b",
            text,
            re.IGNORECASE,
        )
    )
    if (
        field in SAFE_STRUCTURAL_VALUE_FIELDS
        and not HARD_REALIZED_CONTEXT.search(hard_context_text)
        and not (
            field in TARGET_DEFINITION_FIELDS
            and (assignment_value or spelled_appended_value)
        )
    ):
        return False
    if outcome_context:
        if governance_denial and not numeric_values and not qualitative_value and not spelled_value:
            return False
        return True
    structural_target = STRUCTURAL_FORWARD_TARGET.search(text)
    if (
        structural_target
        and not qualitative_value
        and not spelled_value
        and all(
            structural_target.start() <= number.start()
            and number.end() <= structural_target.end()
            for number in numeric_values
        )
    ):
        return False
    if qualitative_value or spelled_value:
        return True
    for number in numeric_values:
        if any(
            not (number.start() < metric.end() and metric.start() < number.end())
            and min(abs(number.start() - metric.end()), abs(metric.start() - number.end())) <= 64
            for metric in metric_matches
        ):
            return True
    return False


def _performance_value_paths(value: Any, prefix: str = "") -> list[str]:
    findings: list[str] = []
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            path = f"{prefix}.{raw_key}" if prefix else str(raw_key)
            findings.extend(_performance_value_paths(child, path))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            findings.extend(_performance_value_paths(child, f"{prefix}[{index}]"))
    elif isinstance(value, str) and _string_has_performance_value(value, prefix):
        findings.append(prefix or "<string>")
    return findings


def _nonzero_post_2025_paths(value: Any, prefix: str = "") -> list[str]:
    findings: list[str] = []
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = _normalized_key(raw_key)
            path = f"{prefix}.{raw_key}" if prefix else str(raw_key)
            is_counter = bool(
                re.search(r"(?:post_?2025|after_?2025|2026).*(?:count|counter|rows|samples|labels|observations)", key)
                or re.search(r"(?:count|counter|rows|samples|labels|observations).*(?:post_?2025|after_?2025|2026)", key)
            )
            if is_counter and isinstance(child, (int, float)) and not isinstance(child, bool) and child != 0:
                findings.append(path)
            findings.extend(_nonzero_post_2025_paths(child, path))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            findings.extend(_nonzero_post_2025_paths(child, f"{prefix}[{index}]"))
    return findings


def _reject_outcome_fields(value: Any) -> None:
    fields = _performance_field_paths(value)
    if fields:
        raise RegistryError(f"PERFORMANCE_METRIC_FIELDS_FORBIDDEN:{fields[:5]}")
    values = _performance_value_paths(value)
    if values:
        raise RegistryError(f"PERFORMANCE_METRIC_VALUES_FORBIDDEN:{values[:5]}")
    counters = _nonzero_post_2025_paths(value)
    if counters:
        raise RegistryError(f"POST_2025_COUNTER_NONZERO:{counters[:5]}")


def _similarity_control_paths(value: Any, prefix: str = "") -> list[str]:
    findings: list[str] = []
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = _normalized_key(raw_key)
            path = f"{prefix}.{raw_key}" if prefix else str(raw_key)
            semantic_similarity_control = (
                ("similarity" in key or "equivalence" in key)
                and ("score" in key or "threshold" in key)
            )
            negative_creation_attestation = (
                child is False and key.startswith("new_") and key.endswith("_created")
            )
            if semantic_similarity_control and not negative_creation_attestation:
                findings.append(path)
            findings.extend(_similarity_control_paths(child, path))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            findings.extend(_similarity_control_paths(child, f"{prefix}[{index}]"))
    return findings


def _reject_similarity_controls(value: Any) -> None:
    paths = _similarity_control_paths(value)
    if paths:
        raise RegistryError(f"SIMILARITY_SCORE_OR_THRESHOLD_FORBIDDEN:{paths[:5]}")


def _normalize_entity(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise RegistryError("ENTITY_MUST_BE_OBJECT")
    _reject_outcome_fields(raw)
    missing = [field for field in REQUIRED_ENTITY_FIELDS if field not in raw]
    if missing:
        raise RegistryError(f"ENTITY_REQUIRED_FIELDS_MISSING:{missing}")
    status = str(raw["status"]).strip().upper()
    if status not in ENTITY_STATUSES:
        raise RegistryError(f"INVALID_ENTITY_STATUS:{status}")
    post_count = _nonnegative_int(raw.get("post_2025_observation_count", 0), "post_2025_observation_count")
    if post_count:
        raise RegistryError("POST_2025_COUNTER_NONZERO:post_2025_observation_count")
    failure_count_raw = raw.get(
        "trial_ledger_failure_row_count",
        raw.get("trial_failure_row_count", raw.get("failure_row_count")),
    )
    entity: dict[str, Any] = {
        "entity_id": _string(raw["entity_id"], "entity_id"),
        "canonical_name": _string(raw["canonical_name"], "canonical_name"),
        "entity_type": _string(raw["entity_type"], "entity_type"),
        "status": status,
        "specification_fingerprint": _require_sha(raw["specification_fingerprint"], "specification_fingerprint"),
        "information_source_fingerprint": _require_sha(raw["information_source_fingerprint"], "information_source_fingerprint"),
        "mechanism_fingerprint": _require_sha(raw["mechanism_fingerprint"], "mechanism_fingerprint"),
        "decision_layer": _string(raw["decision_layer"], "decision_layer"),
        "evidence_source_temporal_status": _string(raw["evidence_source_temporal_status"], "evidence_source_temporal_status"),
        "excluded_source_refs": _string_list(raw["excluded_source_refs"], "excluded_source_refs"),
        "temporal_evidence_limitations": _string_list(raw["temporal_evidence_limitations"], "temporal_evidence_limitations"),
        "factor_ledger_ref": _string(raw.get("factor_ledger_ref"), "factor_ledger_ref", optional=True),
        "trial_ledger_ref": _string(raw.get("trial_ledger_ref"), "trial_ledger_ref", optional=True),
        "trial_ledger_failure_row_count": _optional_nonnegative_int(
            failure_count_raw,
            "trial_ledger_failure_row_count",
        ),
        "post_2025_observation_count": post_count,
        "minimum_system_manifest_ref": _string(raw.get("minimum_system_manifest_ref"), "minimum_system_manifest_ref", optional=True),
        "parent_entity_id": _string(raw.get("parent_entity_id"), "parent_entity_id", optional=True),
    }
    seed = raw.get("metadata", {})
    if not isinstance(seed, Mapping):
        raise RegistryError("ENTITY_METADATA_MUST_BE_OBJECT")
    known = set(ENTITY_LOGICAL_FIELDS) | {
        "aliases",
        "metadata",
        "row_hash",
        "trial_failure_row_count",
        "failure_row_count",
    }
    metadata = {str(key): value for key, value in seed.items()}
    metadata.update({str(key): value for key, value in raw.items() if key not in known})
    for key, value in metadata.items():
        normalized = _normalized_key(key)
        inline_ledger_container = (
            ("factor_ledger" in normalized or "trial_ledger" in normalized)
            and isinstance(value, (Mapping, list, tuple, set))
            and not normalized.endswith("_refs")
        )
        if normalized in {"factor_ledger", "trial_ledger"} or inline_ledger_container:
            raise RegistryError(f"LEDGER_MUST_BE_REFERENCE:{key}")
    _reject_outcome_fields(metadata)
    entity["metadata"] = metadata
    entity["row_hash"] = sha256_value({key: entity[key] for key in (*ENTITY_LOGICAL_FIELDS, "metadata")})
    return entity


def _entity_without_hash(entity: Mapping[str, Any]) -> dict[str, Any]:
    return {key: entity[key] for key in (*ENTITY_LOGICAL_FIELDS, "metadata")}


def _entity_to_storage(entity: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "entity_id": entity["entity_id"],
        "canonical_name": entity["canonical_name"],
        "entity_type": entity["entity_type"],
        "status": entity["status"],
        "specification_fingerprint": entity["specification_fingerprint"],
        "information_source_fingerprint": entity["information_source_fingerprint"],
        "mechanism_fingerprint": entity["mechanism_fingerprint"],
        "decision_layer": entity["decision_layer"],
        "evidence_source_temporal_status": entity["evidence_source_temporal_status"],
        "excluded_source_refs_json": canonical_json(entity["excluded_source_refs"]).decode("utf-8"),
        "temporal_evidence_limitations_json": canonical_json(entity["temporal_evidence_limitations"]).decode("utf-8"),
        "factor_ledger_ref": entity["factor_ledger_ref"],
        "trial_ledger_ref": entity["trial_ledger_ref"],
        "trial_ledger_failure_row_count": entity["trial_ledger_failure_row_count"],
        "post_2025_observation_count": entity["post_2025_observation_count"],
        "minimum_system_manifest_ref": entity["minimum_system_manifest_ref"],
        "parent_entity_id": entity["parent_entity_id"],
        "metadata_json": canonical_json(entity["metadata"]).decode("utf-8"),
        "row_hash": entity["row_hash"],
    }


def _entity_from_storage(row: Mapping[str, Any]) -> dict[str, Any]:
    try:
        raw: dict[str, Any] = {
            "entity_id": row["entity_id"],
            "canonical_name": row["canonical_name"],
            "entity_type": row["entity_type"],
            "status": row["status"],
            "specification_fingerprint": row["specification_fingerprint"],
            "information_source_fingerprint": row["information_source_fingerprint"],
            "mechanism_fingerprint": row["mechanism_fingerprint"],
            "decision_layer": row["decision_layer"],
            "evidence_source_temporal_status": row["evidence_source_temporal_status"],
            "excluded_source_refs": json.loads(row["excluded_source_refs_json"]),
            "temporal_evidence_limitations": json.loads(row["temporal_evidence_limitations_json"]),
            "factor_ledger_ref": row["factor_ledger_ref"],
            "trial_ledger_ref": row["trial_ledger_ref"],
            "trial_ledger_failure_row_count": row["trial_ledger_failure_row_count"],
            "post_2025_observation_count": row["post_2025_observation_count"],
            "minimum_system_manifest_ref": row["minimum_system_manifest_ref"],
            "parent_entity_id": row["parent_entity_id"],
        }
        metadata = json.loads(row["metadata_json"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RegistryError(f"INVALID_ENTITY_PARQUET_ROW:{exc}") from exc
    if not isinstance(metadata, dict):
        raise RegistryError("INVALID_ENTITY_METADATA_JSON")
    raw.update(metadata)
    entity = _normalize_entity(raw)
    if row.get("row_hash") != entity["row_hash"]:
        raise RegistryError(f"ENTITY_ROW_HASH_MISMATCH:{entity['entity_id']}")
    return entity


def _alias_row(alias: str, entity_id: str) -> dict[str, str]:
    normalized = normalize_alias(alias)
    core = {"alias_normalized": normalized, "alias": str(alias).strip(), "entity_id": str(entity_id).strip()}
    if not core["alias"] or not core["entity_id"]:
        raise RegistryError("EMPTY_ALIAS_OR_ENTITY_ID")
    return {**core, "row_hash": sha256_value(core)}


def _validate_alias_rows(rows: Iterable[Mapping[str, Any]], entity_ids: set[str]) -> list[dict[str, str]]:
    by_alias: dict[str, dict[str, str]] = {}
    for raw in rows:
        row = _alias_row(str(raw.get("alias", "")), str(raw.get("entity_id", "")))
        if raw.get("alias_normalized") not in (None, row["alias_normalized"]):
            raise RegistryError(f"ALIAS_NORMALIZATION_MISMATCH:{raw.get('alias')}")
        if raw.get("row_hash") not in (None, row["row_hash"]):
            raise RegistryError(f"ALIAS_ROW_HASH_MISMATCH:{raw.get('alias')}")
        if row["entity_id"] not in entity_ids:
            raise RegistryError(f"ALIAS_TARGET_MISSING:{row['entity_id']}")
        prior = by_alias.get(row["alias_normalized"])
        if prior and prior["entity_id"] != row["entity_id"]:
            raise RegistryError(f"ALIAS_COLLISION:{row['alias_normalized']}:{prior['entity_id']}:{row['entity_id']}")
        if prior is None or (row["alias"], row["entity_id"]) < (prior["alias"], prior["entity_id"]):
            by_alias[row["alias_normalized"]] = row
    return [by_alias[key] for key in sorted(by_alias)]


def _parquet_modules():
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise RegistryError("PYARROW_REQUIRED_FOR_CANONICAL_PARQUET") from exc
    return pa, pq


def _entity_schema(pa: Any) -> Any:
    integer_fields = {"trial_ledger_failure_row_count", "post_2025_observation_count"}
    return pa.schema([pa.field(name, pa.int64() if name in integer_fields else pa.string(), nullable=True) for name in ENTITY_COLUMNS])


def _alias_schema(pa: Any) -> Any:
    return pa.schema([pa.field(name, pa.string(), nullable=False) for name in ALIAS_COLUMNS])


def _write_parquet(path: Path, rows: list[dict[str, Any]], *, aliases: bool = False) -> None:
    pa, pq = _parquet_modules()
    schema = _alias_schema(pa) if aliases else _entity_schema(pa)
    table = pa.Table.from_pylist(rows, schema=schema)
    pq.write_table(table, path, compression="NONE", use_dictionary=False, write_statistics=True, data_page_version="1.0")
    with path.open("r+b") as handle:
        handle.flush()
        os.fsync(handle.fileno())


def _read_parquet(path: Path, *, aliases: bool = False) -> list[dict[str, Any]]:
    pa, pq = _parquet_modules()
    expected = _alias_schema(pa) if aliases else _entity_schema(pa)
    table = pq.read_table(path)
    if table.schema.names != expected.names:
        raise RegistryError(f"PARQUET_SCHEMA_MISMATCH:{path.name}")
    return table.to_pylist()


def _read_entities(snapshot_dir: Path) -> list[dict[str, Any]]:
    rows = [_entity_from_storage(row) for row in _read_parquet(snapshot_dir / REGISTRY_FILE)]
    if [row["entity_id"] for row in rows] != sorted(row["entity_id"] for row in rows):
        raise RegistryError("ENTITY_ROWS_NOT_DETERMINISTICALLY_SORTED")
    if len({row["entity_id"] for row in rows}) != len(rows):
        raise RegistryError("DUPLICATE_ENTITY_ID")
    return rows


def _read_aliases(snapshot_dir: Path, entity_ids: set[str]) -> list[dict[str, str]]:
    rows = _read_parquet(snapshot_dir / ALIASES_FILE, aliases=True)
    aliases = _validate_alias_rows(rows, entity_ids)
    if [row["alias_normalized"] for row in rows] != [row["alias_normalized"] for row in aliases]:
        raise RegistryError("ALIAS_ROWS_NOT_DETERMINISTICALLY_SORTED")
    return aliases


def _snapshot_payload(parent: str, entities: list[dict[str, Any]], aliases: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "parent_snapshot_sha256": parent,
        "entities": [_entity_without_hash(row) | {"row_hash": row["row_hash"]} for row in entities],
        "aliases": aliases,
    }


def _snapshot_sha(parent: str, entities: list[dict[str, Any]], aliases: list[dict[str, str]]) -> str:
    return sha256_value(_snapshot_payload(parent, entities, aliases))


def _json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"INVALID_JSON:{path}:{exc}") from exc


def _write_json(path: Path, value: Any) -> None:
    with path.open("xb") as handle:
        handle.write(canonical_json(value) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _current_head(root: Path) -> str:
    path = root / CURRENT_FILE
    if not path.is_file():
        return GENESIS
    pointer = _json_file(path)
    if not isinstance(pointer, Mapping) or set(pointer) != {
        "schema_version",
        "head_sha256",
        "snapshot_id",
        "manifest_path",
    }:
        raise RegistryError("CURRENT_POINTER_SCHEMA_INVALID")
    if pointer.get("schema_version") != SCHEMA_VERSION:
        raise RegistryError("CURRENT_POINTER_SCHEMA_VERSION_INVALID")
    head = str(pointer.get("head_sha256", "")).strip().lower()
    if not HEX_SHA256.fullmatch(head):
        raise RegistryError("CURRENT_POINTER_INVALID")
    if pointer.get("snapshot_id") != head:
        raise RegistryError("CURRENT_POINTER_SNAPSHOT_ID_MISMATCH")
    expected_manifest = f"{SNAPSHOTS_DIR}/{head}/{MANIFEST_FILE}"
    if pointer.get("manifest_path") != expected_manifest:
        raise RegistryError("CURRENT_POINTER_MANIFEST_PATH_INVALID")
    snapshot_dir = root / SNAPSHOTS_DIR / head
    if not snapshot_dir.is_dir():
        raise RegistryError(f"CURRENT_SNAPSHOT_MISSING:{head}")
    manifest = _json_file(snapshot_dir / MANIFEST_FILE)
    if manifest.get("snapshot_id") != head or manifest.get("snapshot_sha256") != head:
        raise RegistryError("CURRENT_POINTER_MANIFEST_IDENTITY_MISMATCH")
    return head


def _snapshot_dir(root: Path, snapshot: str | None = None) -> Path:
    head = _current_head(root) if snapshot in (None, "CURRENT") else str(snapshot).strip().lower()
    if head == GENESIS:
        raise RegistryError("REGISTRY_EMPTY")
    if not HEX_SHA256.fullmatch(head):
        raise RegistryError(f"INVALID_SNAPSHOT_SHA:{head}")
    path = root / SNAPSHOTS_DIR / head
    if not path.is_dir():
        raise RegistryError(f"SNAPSHOT_NOT_FOUND:{head}")
    return path


def _load_snapshot(
    root: Path,
    snapshot: str | None = None,
    *,
    validate_integrity: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, str]]]:
    directory = _snapshot_dir(root, snapshot)
    if validate_integrity:
        errors = _validate_one_snapshot(root, directory.name)
        if errors:
            raise RegistryError(f"SNAPSHOT_INTEGRITY_INVALID:{errors}")
    manifest = _json_file(directory / MANIFEST_FILE)
    entities = _read_entities(directory)
    aliases = _read_aliases(directory, {row["entity_id"] for row in entities})
    return manifest, entities, aliases


def _load_live_snapshot(
    root: Path,
) -> tuple[str, dict[str, Any] | None, list[dict[str, Any]], list[dict[str, str]]]:
    head, _ = _validated_event_head(root)
    if head == GENESIS:
        return head, None, [], []
    manifest, entities, aliases = _load_snapshot(root, head, validate_integrity=True)
    return head, manifest, entities, aliases


def _validated_event_head(root: Path) -> tuple[str, dict[str, Any]]:
    head = _current_head(root)
    chain = validate_event_chain(root)
    if chain["status"] != "PASS":
        raise RegistryError(f"EVENT_CHAIN_INVALID:{chain['errors']}")
    if chain["tail_head_sha256"] != head:
        raise RegistryError(
            f"EVENT_CHAIN_HEAD_MISMATCH:events={chain['tail_head_sha256']}:current={head}"
        )
    return head, chain


def _load_snapshot_for_read(
    root: Path,
    snapshot: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, str]]]:
    live_head, chain = _validated_event_head(root)
    target = live_head if snapshot in (None, "CURRENT") else str(snapshot).strip().lower()
    if target == GENESIS:
        raise RegistryError("REGISTRY_EMPTY")
    if not HEX_SHA256.fullmatch(target):
        raise RegistryError(f"INVALID_SNAPSHOT_SHA:{target}")
    lineage = set(chain.get("lineage_snapshot_sha256", []))
    if target not in lineage:
        raise RegistryError(f"SNAPSHOT_NOT_IN_EVENT_CHAIN_LINEAGE:{target}")
    return _load_snapshot(root, target, validate_integrity=True)


def current_state(root: Path | str) -> dict[str, Any]:
    registry_root = Path(root)
    head, manifest, _, _ = _load_live_snapshot(registry_root)
    if head == GENESIS:
        return {"status": "EMPTY", "head_sha256": GENESIS, "snapshot": None}
    return {"status": "PASS", "head_sha256": head, "snapshot": manifest}


def _event_rows(root: Path) -> list[dict[str, Any]]:
    path = root / EVENTS_FILE
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                raise RegistryError(f"EVENT_EMPTY_LINE:{number}")
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RegistryError(f"EVENT_JSON_INVALID:{number}") from exc
            if not isinstance(row, dict):
                raise RegistryError(f"EVENT_NOT_OBJECT:{number}")
            rows.append(row)
    return rows


def validate_event_chain(root: Path | str) -> dict[str, Any]:
    registry_root = Path(root)
    errors: list[str] = []
    try:
        rows = _event_rows(registry_root)
    except RegistryError as exc:
        return {
            "status": "FAIL",
            "errors": [str(exc)],
            "event_count": 0,
            "tail_event_hash": GENESIS,
            "tail_head_sha256": GENESIS,
            "lineage_snapshot_sha256": [],
        }
    previous = GENESIS
    expected_base_head = GENESIS
    expected_keys = {
        "schema_version", "sequence", "event_type", "previous_event_hash",
        "base_head_sha256", "new_head_sha256", "patch_sha256", "event_time_utc", "event_hash",
    }
    lineage: list[str] = []
    for index, row in enumerate(rows, 1):
        if set(row) != expected_keys:
            errors.append(f"EVENT_SCHEMA_MISMATCH:{index}")
            previous = str(row.get("event_hash", ""))
            continue
        core = {key: row[key] for key in expected_keys if key != "event_hash"}
        if row.get("sequence") != index:
            errors.append(f"EVENT_SEQUENCE_MISMATCH:{index}")
        if row.get("previous_event_hash") != previous:
            errors.append(f"EVENT_PREVIOUS_HASH_MISMATCH:{index}")
        if row.get("base_head_sha256") != expected_base_head:
            errors.append(f"EVENT_BASE_HEAD_MISMATCH:{index}")
        new_head = str(row.get("new_head_sha256", ""))
        if not HEX_SHA256.fullmatch(new_head):
            errors.append(f"EVENT_NEW_HEAD_INVALID:{index}")
        else:
            lineage.append(new_head)
            snapshot_dir = registry_root / SNAPSHOTS_DIR / new_head
            if not snapshot_dir.is_dir():
                errors.append(f"EVENT_SNAPSHOT_MISSING:{index}:{new_head}")
            else:
                try:
                    manifest = _json_file(snapshot_dir / MANIFEST_FILE)
                    if manifest.get("snapshot_sha256") != new_head or manifest.get("snapshot_id") != new_head:
                        errors.append(f"EVENT_SNAPSHOT_IDENTITY_MISMATCH:{index}")
                    if manifest.get("parent_snapshot_sha256") != row.get("base_head_sha256"):
                        errors.append(f"EVENT_SNAPSHOT_PARENT_MISMATCH:{index}")
                    if manifest.get("patch_sha256") != row.get("patch_sha256"):
                        errors.append(f"EVENT_SNAPSHOT_PATCH_MISMATCH:{index}")
                except RegistryError as exc:
                    errors.append(f"EVENT_SNAPSHOT_MANIFEST_INVALID:{index}:{exc}")
        if row.get("event_hash") != sha256_value(core):
            errors.append(f"EVENT_HASH_MISMATCH:{index}")
        previous = str(row.get("event_hash", ""))
        expected_base_head = new_head
    return {
        "status": "FAIL" if errors else "PASS",
        "errors": errors,
        "event_count": len(rows),
        "tail_event_hash": previous,
        "tail_head_sha256": rows[-1].get("new_head_sha256", GENESIS) if rows else GENESIS,
        "lineage_snapshot_sha256": lineage,
    }


def _append_event(root: Path, event: dict[str, Any]) -> None:
    with (root / EVENTS_FILE).open("ab") as handle:
        handle.write(canonical_json(event) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())


def _review_gate(patch: Mapping[str, Any]) -> dict[str, Any]:
    validation = patch.get("validation")
    review = patch.get("independent_review")
    if not isinstance(validation, Mapping) or str(validation.get("status", "")).upper() != "PASS":
        raise RegistryError("VALIDATION_PASS_REQUIRED")
    if not isinstance(review, Mapping) or str(review.get("status", "")).upper() != "PASS":
        raise RegistryError("INDEPENDENT_REVIEW_PASS_REQUIRED")
    if review.get("independent") is not True:
        raise RegistryError("INDEPENDENT_REVIEW_ATTESTATION_REQUIRED")
    reviewer = _string(review.get("reviewer"), "independent_review.reviewer")
    author = _string(patch.get("author"), "author", optional=True)
    if author and reviewer.casefold() == author.casefold():
        raise RegistryError("INDEPENDENT_REVIEWER_MUST_DIFFER_FROM_AUTHOR")
    _reject_outcome_fields(validation)
    _reject_outcome_fields(review)
    return {"status": "PASS", "independent": True, "reviewer": reviewer}


def _patch_integrity(patch: Mapping[str, Any], *, audited_bootstrap: bool) -> dict[str, Any]:
    operations = patch.get("operations")
    if not isinstance(operations, list) or not operations:
        raise RegistryError("PATCH_OPERATIONS_REQUIRED")
    declared_count = _nonnegative_int(patch.get("operation_count"), "operation_count")
    if declared_count != len(operations):
        raise RegistryError(
            f"PATCH_OPERATION_COUNT_MISMATCH:declared={declared_count}:actual={len(operations)}"
        )
    declared_sha = _require_sha(patch.get("operations_sha256"), "operations_sha256")
    actual_sha = sha256_value(operations)
    if declared_sha != actual_sha:
        raise RegistryError(
            f"PATCH_OPERATIONS_SHA256_MISMATCH:declared={declared_sha}:actual={actual_sha}"
        )
    source_pin: str | None = None
    inventory_pin: str | None = None
    if audited_bootstrap:
        source_pin = _require_sha(
            patch.get("pinned_bootstrap_source_sha256"),
            "pinned_bootstrap_source_sha256",
        )
        inventory_pin = _require_sha(
            patch.get("pinned_outcome_blind_inventory_sha256"),
            "pinned_outcome_blind_inventory_sha256",
        )
    return {
        "patch_purpose": "AUDITED_INVENTORY_BOOTSTRAP" if audited_bootstrap else "STANDARD",
        "operation_count": declared_count,
        "operations_sha256": declared_sha,
        "pinned_bootstrap_source_sha256": source_pin,
        "pinned_outcome_blind_inventory_sha256": inventory_pin,
    }


def _candidate(raw: Mapping[str, Any]) -> dict[str, Any]:
    candidate = dict(raw)
    for fingerprint_field, content_field in (
        ("specification_fingerprint", "specification"),
        ("information_source_fingerprint", "information_source"),
        ("mechanism_fingerprint", "mechanism"),
    ):
        if not candidate.get(fingerprint_field) and content_field in candidate:
            candidate[fingerprint_field] = sha256_value(candidate[content_field])
    for field in ("specification_fingerprint", "information_source_fingerprint", "mechanism_fingerprint"):
        if candidate.get(field):
            candidate[field] = _require_sha(candidate[field], field)
    candidate["entity_id"] = str(candidate.get("entity_id", candidate.get("proposed_entity_id", ""))).strip()
    candidate["canonical_name"] = str(candidate.get("canonical_name", candidate.get("name", ""))).strip()
    candidate["decision_layer"] = str(candidate.get("decision_layer", "")).strip()
    candidate["aliases"] = _string_list(candidate.get("aliases", []), "aliases")
    return candidate


def _variant_repackaging(proposal: Mapping[str, Any], candidate: Mapping[str, Any]) -> bool:
    values = (
        proposal.get("change_type", ""),
        proposal.get("claimed_novelty", ""),
        candidate.get("entity_id", ""),
        candidate.get("canonical_name", ""),
        *candidate.get("aliases", []),
    )
    description = " ".join(str(value) for value in values)
    normalized = normalize_alias(description).replace("-", " ") if description.strip() else ""
    tokens = normalized.split()
    marker_tokens = {
        "model",
        "rename",
        "renamed",
        "renaming",
        "repackage",
        "repackaged",
        "repackaging",
        "retry",
        "swap",
        "threshold",
        "tweak",
        "tweaked",
        "wrapper",
    }
    if marker_tokens.intersection(tokens) or MODEL_LABEL_TOKENS.intersection(tokens):
        return True
    if tokens and tokens[-1].isdigit() and int(tokens[-1]) >= 2:
        return True
    if any(token in {"mk", "mark"} for token in tokens) and any(
        re.fullmatch(r"(?:ii|iii|iv|v|vi|vii|viii|ix|x|[2-9]|[1-9][0-9]+)", token)
        for token in tokens
    ):
        return True
    if any(re.fullmatch(r"retry(?:r)?(?:[2-9]|[1-9][0-9]+)", token) for token in tokens):
        return True
    if any(
        re.fullmatch(r"(?:r|v|version|attempt)(?:[2-9]|[1-9][0-9]+)", token)
        for token in tokens
    ):
        return True
    if any(re.search(r"[a-z0-9]r(?:[2-9]|[1-9][0-9]+)$", token) for token in tokens):
        return True
    return any(
        tokens[index] == "r"
        and index + 1 < len(tokens)
        and re.fullmatch(r"(?:[2-9]|[1-9][0-9]+)", tokens[index + 1])
        for index in range(len(tokens))
    )


def _governance_containers(row: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    containers: list[Mapping[str, Any]] = [row]
    metadata = row.get("metadata")
    if isinstance(metadata, Mapping):
        containers.append(metadata)
        nested = metadata.get("governance_metadata")
        if isinstance(nested, Mapping):
            containers.append(nested)
    governance = row.get("governance_metadata")
    if isinstance(governance, Mapping):
        containers.append(governance)
    return containers


def _governance_values(row: Mapping[str, Any], key: str) -> list[Any]:
    normalized_key = _normalized_key(key)
    values: list[Any] = []
    for container in _governance_containers(row):
        for raw_key, value in container.items():
            if _normalized_key(raw_key) == normalized_key and value is not None:
                values.append(value)
    return values


def _governance_value(row: Mapping[str, Any], key: str) -> Any:
    values = _governance_values(row, key)
    return values[0] if values else None


def _information_family(row: Mapping[str, Any]) -> str:
    value = _governance_value(row, "information_family")
    return normalize_alias(str(value)) if value is not None and str(value).strip() else ""


def _identity_stem(value: Any) -> str:
    if value is None or not str(value).strip():
        return ""
    tokens = normalize_alias(str(value)).split("-")
    stem: list[str] = []
    skip_numeric = False
    for token in tokens:
        if skip_numeric and token.isdigit():
            skip_numeric = False
            continue
        skip_numeric = False
        if token in {"r", "v", "version", "mk", "mark"}:
            skip_numeric = True
            continue
        if token == "retry":
            skip_numeric = True
            continue
        if token in IDENTITY_STEM_DISCARD_TOKENS:
            continue
        if re.fullmatch(r"(?:r|v|version|retryr?|attempt|mk|mark)[0-9]+", token):
            continue
        suffixed = re.fullmatch(r"(.+?)r[0-9]+", token)
        if suffixed:
            token = suffixed.group(1)
        if token:
            stem.append(token)
    if stem and (
        (stem[-1].isdigit() and int(stem[-1]) >= 2)
        or re.fullmatch(r"(?:ii|iii|iv|v|vi|vii|viii|ix|x)", stem[-1])
    ):
        stem.pop()
    return "-".join(stem)


def _identity_stems(values: Iterable[Any]) -> set[str]:
    return {
        stem
        for stem in (_identity_stem(value) for value in values)
        if len(stem.replace("-", "")) >= 3
    }


def _normalized_reference(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).strip().replace("\\", "/").casefold()
    text = " ".join(text.split())
    scheme = re.fullmatch(r"([a-z][a-z0-9+.-]*://)(.*)", text)
    if scheme:
        normalized_tail = posixpath.normpath("/" + scheme.group(2)).lstrip("/")
        return scheme.group(1) + ("" if normalized_tail == "." else normalized_tail)
    normalized = posixpath.normpath(text)
    return "" if normalized == "." else normalized


def _authoritative_references(row: Mapping[str, Any]) -> tuple[set[str], list[str]]:
    references: set[str] = set()
    invalid: list[str] = []
    for field in sorted(AUTHORITATIVE_REFERENCE_FIELDS):
        for raw_value in _governance_values(row, field):
            if isinstance(raw_value, str):
                values: Sequence[Any] = [raw_value]
            elif isinstance(raw_value, (list, tuple, set)):
                values = list(raw_value)
            else:
                invalid.append(field)
                continue
            for value in values:
                if not isinstance(value, str) or not value.strip():
                    invalid.append(field)
                    continue
                references.add(_normalized_reference(value))
    return references, sorted(set(invalid))


def _raw_information_identities(row: Mapping[str, Any]) -> dict[str, set[str]]:
    identities: dict[str, set[str]] = {
        "information_source": set(),
        "feature_input_family": set(),
    }
    for field in identities:
        for raw_value in _governance_values(row, field):
            values: Sequence[Any]
            if isinstance(raw_value, str):
                values = [raw_value]
            elif isinstance(raw_value, (list, tuple, set)):
                values = list(raw_value)
            elif isinstance(raw_value, Mapping):
                identities[field].add(f"structured:{sha256_value(raw_value)}")
                continue
            else:
                continue
            for value in values:
                if isinstance(value, str) and value.strip():
                    normalized = normalize_alias(value)
                    if (
                        normalized not in RAW_IDENTITY_PLACEHOLDERS
                        and not normalized.startswith("unavailable-")
                        and not normalized.startswith("unknown-")
                    ):
                        identities[field].add(normalized)
                elif isinstance(value, Mapping):
                    identities[field].add(f"structured:{sha256_value(value)}")
    return identities


def _portfolio_geometry_fingerprints(row: Mapping[str, Any]) -> set[str]:
    values: set[str] = set()
    for raw_value in _governance_values(row, "portfolio_geometry_fingerprint"):
        if isinstance(raw_value, str) and HEX_SHA256.fullmatch(raw_value.strip().lower()):
            values.add(raw_value.strip().lower())
    return values


def _lineage_references(
    *sources: Mapping[str, Any],
) -> tuple[dict[str, set[str]], list[str]]:
    references: dict[str, set[str]] = {}
    invalid: list[str] = []
    for source in sources:
        for container in _governance_containers(source):
            for raw_key, raw_value in container.items():
                field = _normalized_key(raw_key)
                kind = LINEAGE_FIELD_KINDS.get(field)
                if kind is None or raw_value is None:
                    continue
                if isinstance(raw_value, str):
                    if field.endswith("_ids"):
                        invalid.append(field)
                        continue
                    values: Sequence[Any] = [raw_value]
                elif isinstance(raw_value, (list, tuple, set)):
                    values = list(raw_value)
                else:
                    invalid.append(field)
                    continue
                for value in values:
                    if not isinstance(value, str) or not value.strip():
                        invalid.append(field)
                        continue
                    references.setdefault(value.strip(), set()).add(kind)
    return references, sorted(set(invalid))


def evaluate_proposal(
    proposal: Mapping[str, Any],
    entities: Sequence[Mapping[str, Any]],
    aliases: Sequence[Mapping[str, Any]],
    *,
    head_sha256: str = GENESIS,
) -> dict[str, Any]:
    """Return one fail-closed proposal decision without mutation."""
    if not isinstance(proposal, Mapping):
        raise RegistryError("PROPOSAL_MUST_BE_OBJECT")
    _reject_outcome_fields(proposal)
    _reject_similarity_controls(proposal)
    raw_candidate = proposal.get("candidate", proposal.get("entity", proposal))
    if not isinstance(raw_candidate, Mapping):
        raise RegistryError("PROPOSAL_CANDIDATE_MUST_BE_OBJECT")
    candidate = _candidate(raw_candidate)
    proposal_sha = sha256_value(proposal)

    def result(decision: str, matched: Iterable[str], reasons: Iterable[str]) -> dict[str, Any]:
        if decision not in PROPOSAL_DECISIONS:
            raise RegistryError(f"INVALID_PROPOSAL_DECISION:{decision}")
        status = "PASS" if decision in {"PASS_DISTINCT_INFORMATION_SOURCE", "EXTEND_EXISTING"} else "BLOCKED" if decision.startswith("BLOCKED_") else "REVIEW_REQUIRED"
        return {
            "status": status,
            "decision": decision,
            "matched_entity_ids": sorted(set(matched)),
            "reasons": sorted(set(reasons)),
            "registry_head_sha256": head_sha256,
            "proposal_sha256": proposal_sha,
        }

    required = ("entity_id", "canonical_name", "specification_fingerprint", "information_source_fingerprint", "mechanism_fingerprint", "decision_layer")
    missing = [field for field in required if not candidate.get(field)]
    if missing:
        return result("REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE", [], [f"missing:{field}" for field in missing])

    alias_map = {str(row["alias_normalized"]): str(row["entity_id"]) for row in aliases}
    entity_by_id = {str(row["entity_id"]): row for row in entities}
    identity_values_by_id: dict[str, list[str]] = {
        entity_id: [entity_id, str(row.get("canonical_name", ""))]
        for entity_id, row in entity_by_id.items()
    }
    identity_lookup: dict[str, set[str]] = {}
    for entity_id, values in identity_values_by_id.items():
        for value in values:
            if value.strip():
                identity_lookup.setdefault(normalize_alias(value), set()).add(entity_id)
    for alias_row in aliases:
        entity_id = str(alias_row["entity_id"])
        alias_value = str(alias_row.get("alias", alias_row["alias_normalized"]))
        identity_values_by_id.setdefault(entity_id, []).append(alias_value)
        identity_lookup.setdefault(str(alias_row["alias_normalized"]), set()).add(entity_id)

    def terminal_result(entity_ids: Iterable[str], reason: str) -> dict[str, Any]:
        terminal_ids = sorted(
            {
                entity_id
                for entity_id in entity_ids
                if entity_id in entity_by_id
                and entity_by_id[entity_id].get("status") in TERMINAL_STATUSES
            }
        )
        superseded = [
            entity_id
            for entity_id in terminal_ids
            if entity_by_id[entity_id].get("status") == "SUPERSEDED"
        ]
        if superseded:
            return result("BLOCKED_SUPERSEDED_BRANCH", superseded, [reason])
        return result("BLOCKED_CLOSED_BRANCH", terminal_ids, [reason])

    candidate_identity_values = [
        candidate["entity_id"],
        candidate["canonical_name"],
        *candidate["aliases"],
    ]
    candidate_identity_aliases = {
        normalize_alias(value)
        for value in [candidate["canonical_name"], *candidate["aliases"]]
    }
    exact_identity_ids: set[str] = set()
    for value in candidate_identity_values:
        exact_identity_ids.update(identity_lookup.get(normalize_alias(value), set()))
    terminal_identity_ids = {
        entity_id
        for entity_id in exact_identity_ids
        if entity_by_id[entity_id].get("status") in TERMINAL_STATUSES
    }
    if terminal_identity_ids:
        return terminal_result(terminal_identity_ids, "exact terminal identity cannot be reused")

    collisions = {
        alias_map[normalized]
        for normalized in candidate_identity_aliases
        if normalized in alias_map and alias_map[normalized] != candidate["entity_id"]
    }
    if candidate["entity_id"] in entity_by_id:
        collisions.add(candidate["entity_id"])
    if collisions:
        return result(
            "BLOCKED_ALIAS_CONFLICT",
            collisions,
            ["normalized alias or entity ID already belongs to an existing entity"],
        )

    lineage_refs, invalid_lineage_fields = _lineage_references(proposal, candidate)
    resolved_lineage: dict[str, set[str]] = {}
    unknown_lineage: list[str] = []
    ambiguous_lineage: list[str] = []
    for reference, kinds in lineage_refs.items():
        if reference in entity_by_id:
            matching_ids = {reference}
        else:
            matching_ids = identity_lookup.get(normalize_alias(reference), set())
        if len(matching_ids) == 1:
            resolved_lineage.setdefault(next(iter(matching_ids)), set()).update(kinds)
        elif matching_ids:
            ambiguous_lineage.append(reference)
        else:
            unknown_lineage.append(reference)
    terminal_lineage_ids = {
        entity_id
        for entity_id in resolved_lineage
        if entity_by_id[entity_id].get("status") in TERMINAL_STATUSES
    }
    if terminal_lineage_ids:
        return terminal_result(
            terminal_lineage_ids,
            "declared lineage resolves to a terminal branch",
        )

    candidate_normalized_identities = {
        normalize_alias(value) for value in candidate_identity_values
    }
    terminal_extension_ids = {
        entity_id
        for entity_id, row in entity_by_id.items()
        if row.get("status") in TERMINAL_STATUSES
        and any(
            candidate_identity.startswith(existing_identity + "-")
            for candidate_identity in candidate_normalized_identities
            for existing_identity in {
                normalize_alias(value)
                for value in identity_values_by_id.get(entity_id, [])
                if len(normalize_alias(value).replace("-", "")) >= 3
            }
        )
    }
    if terminal_extension_ids:
        return terminal_result(
            terminal_extension_ids,
            "terminal canonical-name/alias/entity identity cannot be extended or versioned",
        )

    variant_repackaging = _variant_repackaging(proposal, candidate)
    if variant_repackaging:
        candidate_stems = _identity_stems(candidate_identity_values)
        terminal_stem_ids = {
            entity_id
            for entity_id, row in entity_by_id.items()
            if row.get("status") in TERMINAL_STATUSES
            and candidate_stems.intersection(
                _identity_stems(identity_values_by_id.get(entity_id, []))
            )
        }
        if terminal_stem_ids:
            return terminal_result(
                terminal_stem_ids,
                "terminal canonical-name/alias/entity lineage stem cannot be repackaged",
            )

    candidate_authority, invalid_authority = _authoritative_references(candidate)
    proposal_authority, invalid_proposal_authority = _authoritative_references(proposal)
    candidate_authority.update(proposal_authority)
    invalid_authority = sorted(set(invalid_authority + invalid_proposal_authority))
    authority_to_ids: dict[str, set[str]] = {}
    for entity_id, row in entity_by_id.items():
        row_authority, _ = _authoritative_references(row)
        for reference in row_authority:
            authority_to_ids.setdefault(reference, set()).add(entity_id)
    authority_overlap_ids: set[str] = set()
    for reference in candidate_authority:
        authority_overlap_ids.update(authority_to_ids.get(reference, set()))
    terminal_authority_ids = {
        entity_id
        for entity_id in authority_overlap_ids
        if entity_by_id[entity_id].get("status") in TERMINAL_STATUSES
    }
    if terminal_authority_ids:
        return terminal_result(
            terminal_authority_ids,
            "authoritative source/contract reference overlaps terminal history",
        )

    exact = [
        str(row["entity_id"])
        for row in entities
        if row.get("specification_fingerprint") == candidate["specification_fingerprint"]
        and row.get("entity_id") != candidate["entity_id"]
    ]
    if exact:
        return result("BLOCKED_EXACT_DUPLICATE", exact, ["identical specification fingerprint"])

    candidate_exact_geometry = _portfolio_geometry_fingerprints(candidate)
    exact_geometry_ids = {
        str(row["entity_id"])
        for row in entities
        if candidate_exact_geometry
        and candidate_exact_geometry.intersection(_portfolio_geometry_fingerprints(row))
        and row.get("information_source_fingerprint") == candidate["information_source_fingerprint"]
        and row.get("mechanism_fingerprint") == candidate["mechanism_fingerprint"]
        and row.get("entity_id") != candidate["entity_id"]
    }
    terminal_exact_geometry_ids = {
        entity_id
        for entity_id in exact_geometry_ids
        if entity_by_id[entity_id].get("status") in TERMINAL_STATUSES
    }
    if terminal_exact_geometry_ids:
        return terminal_result(
            terminal_exact_geometry_ids,
            "identical portfolio geometry overlaps terminal history",
        )
    if exact_geometry_ids:
        return result(
            "BLOCKED_FUNCTIONAL_REDUNDANCY",
            exact_geometry_ids,
            ["identical information, mechanism, and portfolio geometry already exist"],
        )

    active_equivalence_ids = {
        entity_id
        for entity_id, kinds in resolved_lineage.items()
        if "equivalence" in kinds
        and entity_by_id[entity_id].get("status") not in TERMINAL_STATUSES
    }
    if active_equivalence_ids:
        return result(
            "BLOCKED_FUNCTIONAL_REDUNDANCY",
            active_equivalence_ids,
            ["declared equivalence or duplicate target already exists"],
        )
    if invalid_lineage_fields or unknown_lineage or ambiguous_lineage:
        reasons = [f"invalid_lineage_field:{field}" for field in invalid_lineage_fields]
        reasons.extend(f"unknown_lineage_reference:{value}" for value in unknown_lineage)
        reasons.extend(f"ambiguous_lineage_reference:{value}" for value in ambiguous_lineage)
        return result("REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE", [], reasons)
    if invalid_authority:
        return result(
            "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE",
            [],
            [f"invalid_authoritative_reference_field:{field}" for field in invalid_authority],
        )
    active_authority_ids = {
        entity_id
        for entity_id in authority_overlap_ids
        if entity_by_id[entity_id].get("status") not in TERMINAL_STATUSES
    }
    if active_authority_ids:
        return result(
            "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE",
            active_authority_ids,
            ["authoritative source/contract reference overlaps existing history"],
        )

    info = candidate["information_source_fingerprint"]
    candidate_family = _information_family(candidate)
    candidate_raw_information = _raw_information_identities(candidate)
    proposal_raw_information = _raw_information_identities(proposal)
    for field, values in proposal_raw_information.items():
        candidate_raw_information[field].update(values)
    raw_information_by_id = {
        str(row["entity_id"]): _raw_information_identities(row)
        for row in entities
    }

    def raw_overlap_fields(row: Mapping[str, Any]) -> set[str]:
        row_identities = raw_information_by_id[str(row["entity_id"])]
        return {
            field
            for field in candidate_raw_information
            if candidate_raw_information[field].intersection(row_identities[field])
        }

    candidate_geometry = _portfolio_geometry_fingerprints(candidate)
    geometry_match_ids = {
        str(row["entity_id"])
        for row in entities
        if candidate_geometry
        and candidate_geometry.intersection(_portfolio_geometry_fingerprints(row))
        and (
            row.get("information_source_fingerprint") == info
            or bool(raw_overlap_fields(row))
        )
        and row.get("mechanism_fingerprint") == candidate["mechanism_fingerprint"]
        and row.get("entity_id") != candidate["entity_id"]
    }
    terminal_geometry_ids = {
        entity_id
        for entity_id in geometry_match_ids
        if entity_by_id[entity_id].get("status") in TERMINAL_STATUSES
    }
    if terminal_geometry_ids:
        return terminal_result(
            terminal_geometry_ids,
            "identical portfolio geometry overlaps terminal history",
        )
    if geometry_match_ids:
        return result(
            "BLOCKED_FUNCTIONAL_REDUNDANCY",
            geometry_match_ids,
            ["identical information, mechanism, and portfolio geometry already exist"],
        )

    terminal_matches: list[Mapping[str, Any]] = []
    for row in entities:
        same_information = (
            row.get("information_source_fingerprint") == info
            or bool(raw_overlap_fields(row))
        )
        row_family = _information_family(row)
        same_family = bool(candidate_family and row_family and candidate_family == row_family)
        if (
            row.get("status") in TERMINAL_STATUSES
            and (same_information or same_family)
            and variant_repackaging
        ):
            terminal_matches.append(row)
    if terminal_matches:
        return terminal_result(
            [str(row["entity_id"]) for row in terminal_matches],
            "terminal branch information identity cannot be repackaged",
        )

    same_surface = [
        str(row["entity_id"])
        for row in entities
        if (
            row.get("information_source_fingerprint") == info
            or bool(candidate_family and _information_family(row) == candidate_family)
            or bool(raw_overlap_fields(row))
        )
        and row.get("mechanism_fingerprint") == candidate["mechanism_fingerprint"]
        and row.get("decision_layer") == candidate["decision_layer"]
        and row.get("entity_id") != candidate["entity_id"]
    ]
    if same_surface:
        return result(
            "BLOCKED_FUNCTIONAL_REDUNDANCY",
            same_surface,
            ["exact information identity, mechanism, and decision layer already exist"],
        )

    raw_overlap_ids = [
        str(row["entity_id"])
        for row in entities
        if raw_overlap_fields(row)
        and row.get("entity_id") != candidate["entity_id"]
    ]
    declared_active_parents = {
        entity_id
        for entity_id, kinds in resolved_lineage.items()
        if "ancestry" in kinds
        and entity_by_id[entity_id].get("status") not in TERMINAL_STATUSES
    }
    extension_change_type = _normalized_key(str(proposal.get("change_type", "")))
    if len(declared_active_parents) == 1 and extension_change_type == "new_portfolio_geometry_only":
        parent_id = next(iter(declared_active_parents))
        parent = entity_by_id[parent_id]
        same_exact_information = parent.get("information_source_fingerprint") == info
        distinct_contract = parent.get("specification_fingerprint") != candidate["specification_fingerprint"]
        same_mechanism = parent.get("mechanism_fingerprint") == candidate["mechanism_fingerprint"]
        distinct_decision_surface = parent.get("decision_layer") != candidate["decision_layer"]
        if (
            same_exact_information
            and distinct_contract
            and same_mechanism
            and distinct_decision_surface
            and len(candidate_geometry) == 1
            and candidate_authority
            and parent_id in raw_overlap_ids
        ):
            return result(
                "EXTEND_EXISTING",
                [parent_id],
                ["same authoritative information and mechanism with an explicitly parented distinct frozen portfolio geometry"],
            )
    if raw_overlap_ids:
        return result(
            "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE",
            raw_overlap_ids,
            ["raw information_source or feature_input_family overlaps existing history"],
        )

    all_existing_info = {str(row.get("information_source_fingerprint", "")) for row in entities}
    existing_families = {_information_family(row) for row in entities if _information_family(row)}
    distinct_information = not entities or info not in all_existing_info
    distinct_family = bool(candidate_family and candidate_family not in existing_families)
    no_family_evidence = not candidate_family and not existing_families
    if distinct_information and (distinct_family or no_family_evidence):
        if not candidate_authority:
            return result(
                "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE",
                [],
                ["authoritative distinct-source contract/reference is required"],
            )
        return result(
            "PASS_DISTINCT_INFORMATION_SOURCE",
            [],
            ["information identity is distinct and anchored by an authoritative source/contract reference"],
        )
    if distinct_information and candidate_family in existing_families:
        same_family_ids = [str(row["entity_id"]) for row in entities if _information_family(row) == candidate_family]
        return result(
            "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE",
            same_family_ids,
            ["new fingerprint reuses an existing normalized information family"],
        )
    if distinct_information and not candidate_family and existing_families:
        return result(
            "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE",
            [],
            ["information_family missing while existing family evidence is available"],
        )

    reasons = ["existing information source is reused without enough non-redundancy evidence"]
    return result("REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE", same_surface, reasons)


def preflight_proposal(root: Path | str, proposal: Mapping[str, Any]) -> dict[str, Any]:
    registry_root = Path(root)
    head, _, entities, aliases = _load_live_snapshot(registry_root)
    return evaluate_proposal(proposal, entities, aliases, head_sha256=head)


def _logical_entity_for_update(entity: Mapping[str, Any]) -> dict[str, Any]:
    return _entity_without_hash(entity)


def _add_alias(alias_map: dict[str, dict[str, str]], alias: str, entity_id: str) -> None:
    row = _alias_row(alias, entity_id)
    prior = alias_map.get(row["alias_normalized"])
    if prior and prior["entity_id"] != entity_id:
        raise RegistryError(f"ALIAS_COLLISION:{row['alias_normalized']}:{prior['entity_id']}:{entity_id}")
    if prior is None or row["alias"] < prior["alias"]:
        alias_map[row["alias_normalized"]] = row


def _apply_operations(
    base_entities: Sequence[Mapping[str, Any]],
    base_aliases: Sequence[Mapping[str, str]],
    patch: Mapping[str, Any],
    *,
    head_sha256: str,
    audited_inventory_bootstrap: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    entity_map = {str(row["entity_id"]): dict(row) for row in base_entities}
    alias_map = {str(row["alias_normalized"]): dict(row) for row in base_aliases}
    operations = patch.get("operations")
    if not isinstance(operations, list) or not operations:
        raise RegistryError("PATCH_OPERATIONS_REQUIRED")
    for index, operation in enumerate(operations):
        if not isinstance(operation, Mapping):
            raise RegistryError(f"PATCH_OPERATION_NOT_OBJECT:{index}")
        kind = str(operation.get("op", "")).strip().lower().replace("-", "_")
        if kind in {"add", "add_entity", "update", "update_entity", "upsert"}:
            raw_entity = operation.get("entity")
            if not isinstance(raw_entity, Mapping):
                raise RegistryError(f"PATCH_ENTITY_REQUIRED:{index}")
            entity_id = str(raw_entity.get("entity_id", "")).strip()
            exists = entity_id in entity_map
            if kind in {"add", "add_entity"} and exists:
                raise RegistryError(f"ENTITY_ALREADY_EXISTS:{entity_id}")
            if kind in {"update", "update_entity"} and not exists:
                raise RegistryError(f"ENTITY_NOT_FOUND:{entity_id}")
            if exists:
                old = entity_map[entity_id]
                if old["status"] in TERMINAL_STATUSES:
                    raise RegistryError(f"TERMINAL_ENTITY_IMMUTABLE:{entity_id}")
                merged = _logical_entity_for_update(old)
                merged.update(raw_entity)
                normalized = _normalize_entity(merged)
                if _failure_count_regressed(
                    old["trial_ledger_failure_row_count"],
                    normalized["trial_ledger_failure_row_count"],
                ):
                    raise RegistryError(f"TRIAL_LEDGER_FAILURE_COUNT_REDUCED:{entity_id}")
            else:
                normalized = _normalize_entity(raw_entity)
                if not audited_inventory_bootstrap:
                    proposal = {
                        "candidate": dict(raw_entity),
                        "change_type": operation.get("change_type"),
                        "parent_entity_id": operation.get("parent_entity_id", raw_entity.get("parent_entity_id")),
                    }
                    proposal = {key: value for key, value in proposal.items() if value is not None}
                    decision = evaluate_proposal(proposal, list(entity_map.values()), list(alias_map.values()), head_sha256=head_sha256)
                    if decision["decision"] not in {"PASS_DISTINCT_INFORMATION_SOURCE", "EXTEND_EXISTING"}:
                        raise RegistryError(f"PROPOSAL_NOT_APPLYABLE:{decision['decision']}")
            entity_map[entity_id] = normalized
            _add_alias(alias_map, normalized["canonical_name"], entity_id)
            for alias in _string_list(raw_entity.get("aliases", []), "aliases"):
                _add_alias(alias_map, alias, entity_id)
        elif kind in {"set_status", "close", "tombstone", "supersede"}:
            entity_id = str(operation.get("entity_id", "")).strip()
            if entity_id not in entity_map:
                raise RegistryError(f"ENTITY_NOT_FOUND:{entity_id}")
            status = {"close": "CLOSED", "tombstone": "TOMBSTONED", "supersede": "SUPERSEDED"}.get(kind, str(operation.get("status", "")).upper())
            if status not in TERMINAL_STATUSES:
                raise RegistryError(f"STATUS_TRANSITION_NOT_TERMINAL:{status}")
            if entity_map[entity_id]["status"] in TERMINAL_STATUSES:
                raise RegistryError(f"TERMINAL_ENTITY_IMMUTABLE:{entity_id}")
            updated = _logical_entity_for_update(entity_map[entity_id])
            updated["status"] = status
            entity_map[entity_id] = _normalize_entity(updated)
        elif kind in {"add_alias", "alias"}:
            entity_id = str(operation.get("entity_id", "")).strip()
            if entity_id not in entity_map:
                raise RegistryError(f"ALIAS_TARGET_MISSING:{entity_id}")
            _add_alias(alias_map, str(operation.get("alias", "")), entity_id)
        else:
            raise RegistryError(f"PATCH_OPERATION_UNSUPPORTED:{kind or index}")
    entities = [entity_map[key] for key in sorted(entity_map)]
    aliases = _validate_alias_rows(alias_map.values(), set(entity_map))
    return entities, aliases


@contextmanager
def _registry_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".research_registry.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RegistryError("REGISTRY_LOCKED") from exc
    try:
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        yield
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def _write_snapshot(
    root: Path,
    parent: str,
    entities: list[dict[str, Any]],
    aliases: list[dict[str, str]],
    patch_sha: str,
    review: Mapping[str, Any],
    patch_integrity: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    snapshot_sha = _snapshot_sha(parent, entities, aliases)
    snapshots = root / SNAPSHOTS_DIR
    snapshots.mkdir(parents=True, exist_ok=True)
    final = snapshots / snapshot_sha
    if final.exists():
        raise RegistryError(f"IMMUTABLE_SNAPSHOT_ALREADY_EXISTS:{snapshot_sha}")
    staging = snapshots / f".staging-{snapshot_sha[:12]}-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        _write_parquet(staging / REGISTRY_FILE, [_entity_to_storage(row) for row in entities])
        _write_parquet(staging / ALIASES_FILE, aliases, aliases=True)
        validation = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "snapshot_sha256": snapshot_sha,
            "validation_gates": {
                "alias_collision": "PASS",
                "deterministic_row_hashes": "PASS",
                "independent_review": "PASS",
                "no_performance_metrics": "PASS",
                "post_2025_counter_zero": "PASS",
                "trial_ledger_failure_count_monotonic": "PASS",
            },
            "independent_review": dict(review),
            "patch_sha256": patch_sha,
            **dict(patch_integrity),
        }
        _write_json(staging / VALIDATION_FILE, validation)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": snapshot_sha,
            "snapshot_sha256": snapshot_sha,
            "parent_snapshot_sha256": parent,
            "entity_count": len(entities),
            "alias_count": len(aliases),
            "patch_sha256": patch_sha,
            **dict(patch_integrity),
            "files": {
                REGISTRY_FILE: sha256_file(staging / REGISTRY_FILE),
                ALIASES_FILE: sha256_file(staging / ALIASES_FILE),
                VALIDATION_FILE: sha256_file(staging / VALIDATION_FILE),
            },
        }
        _write_json(staging / MANIFEST_FILE, manifest)
        _fsync_directory(staging)
        staging.rename(final)
        _fsync_directory(snapshots)
        return snapshot_sha, manifest
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def apply_patch(root: Path | str, patch: Mapping[str, Any]) -> dict[str, Any]:
    """Apply one reviewed patch to a new immutable snapshot."""
    if not isinstance(patch, Mapping):
        raise RegistryError("PATCH_MUST_BE_OBJECT")
    if patch.get("schema_version") != SCHEMA_VERSION:
        raise RegistryError("PATCH_SCHEMA_VERSION_INVALID")
    _reject_outcome_fields(patch)
    _reject_similarity_controls(patch)
    purpose = str(patch.get("patch_purpose", "STANDARD")).strip().upper()
    audited_bootstrap = purpose == "AUDITED_INVENTORY_BOOTSTRAP"
    if purpose not in {"STANDARD", "AUDITED_INVENTORY_BOOTSTRAP"}:
        raise RegistryError(f"PATCH_PURPOSE_UNSUPPORTED:{purpose}")
    integrity = _patch_integrity(patch, audited_bootstrap=audited_bootstrap)
    review = _review_gate(patch)
    registry_root = Path(root)
    with _registry_lock(registry_root):
        head = _current_head(registry_root)
        if audited_bootstrap and head != GENESIS:
            raise RegistryError("AUDITED_INVENTORY_BOOTSTRAP_REQUIRES_GENESIS")
        expected = str(patch.get("expected_base_head_sha256", patch.get("expected_base_head_sha", ""))).strip()
        if expected != head:
            raise RegistryError(f"EXPECTED_BASE_HEAD_MISMATCH:expected={expected}:actual={head}")
        chain = validate_event_chain(registry_root)
        if chain["status"] != "PASS":
            raise RegistryError(f"EVENT_CHAIN_INVALID:{chain['errors']}")
        if chain["tail_head_sha256"] != head:
            raise RegistryError("EVENT_CHAIN_HEAD_MISMATCH")
        if head == GENESIS:
            base_entities: list[dict[str, Any]] = []
            base_aliases: list[dict[str, str]] = []
        else:
            check = validate_registry(registry_root, snapshot=head, validate_all=False)
            if check["status"] != "PASS":
                raise RegistryError(f"BASE_SNAPSHOT_INVALID:{check['errors']}")
            _, base_entities, base_aliases = _load_snapshot(registry_root, head)
        if audited_bootstrap:
            operations = patch.get("operations")
            if not isinstance(operations, list):
                raise RegistryError("PATCH_OPERATIONS_REQUIRED")
            unsupported = [
                str(operation.get("op", "")) if isinstance(operation, Mapping) else f"non_object:{index}"
                for index, operation in enumerate(operations)
                if not isinstance(operation, Mapping) or str(operation.get("op", "")).strip().lower().replace("-", "_") not in {"add", "add_entity", "add_alias", "alias"}
            ]
            if unsupported:
                raise RegistryError(f"AUDITED_INVENTORY_BOOTSTRAP_OPERATION_UNSUPPORTED:{unsupported}")
        entities, aliases = _apply_operations(
            base_entities,
            base_aliases,
            patch,
            head_sha256=head,
            audited_inventory_bootstrap=audited_bootstrap,
        )
        patch_sha = sha256_value(patch)
        snapshot_sha, manifest = _write_snapshot(
            registry_root,
            head,
            entities,
            aliases,
            patch_sha,
            review,
            integrity,
        )
        events = _event_rows(registry_root)
        event_core = {
            "schema_version": SCHEMA_VERSION,
            "sequence": len(events) + 1,
            "event_type": "APPLY_PATCH",
            "previous_event_hash": events[-1]["event_hash"] if events else GENESIS,
            "base_head_sha256": head,
            "new_head_sha256": snapshot_sha,
            "patch_sha256": patch_sha,
            "event_time_utc": patch.get("event_time_utc"),
        }
        event = {**event_core, "event_hash": sha256_value(event_core)}
        _append_event(registry_root, event)
        pointer = {
            "schema_version": SCHEMA_VERSION,
            "head_sha256": snapshot_sha,
            "snapshot_id": snapshot_sha,
            "manifest_path": f"{SNAPSHOTS_DIR}/{snapshot_sha}/{MANIFEST_FILE}",
        }
        _atomic_write_text(
            registry_root / CURRENT_FILE,
            canonical_json(pointer).decode("utf-8") + "\n",
        )
        return {"status": "PASS", "base_head_sha256": head, "head_sha256": snapshot_sha, "manifest": manifest, "event": event}


def _validate_one_snapshot(root: Path, snapshot: str) -> list[str]:
    errors: list[str] = []
    directory = root / SNAPSHOTS_DIR / snapshot
    required = {REGISTRY_FILE, ALIASES_FILE, MANIFEST_FILE, VALIDATION_FILE}
    actual = {path.name for path in directory.iterdir()} if directory.is_dir() else set()
    if actual != required:
        return [f"SNAPSHOT_FILE_SET_MISMATCH:{snapshot}:{sorted(actual)}"]
    try:
        manifest = _json_file(directory / MANIFEST_FILE)
        validation = _json_file(directory / VALIDATION_FILE)
        if manifest.get("schema_version") != SCHEMA_VERSION:
            errors.append(f"MANIFEST_SCHEMA_VERSION:{snapshot}")
        if manifest.get("snapshot_id") != snapshot or manifest.get("snapshot_sha256") != snapshot:
            errors.append(f"MANIFEST_SNAPSHOT_ID_MISMATCH:{snapshot}")
        for name in (REGISTRY_FILE, ALIASES_FILE, VALIDATION_FILE):
            if manifest.get("files", {}).get(name) != sha256_file(directory / name):
                errors.append(f"SNAPSHOT_FILE_HASH_MISMATCH:{snapshot}:{name}")
        entities = _read_entities(directory)
        aliases = _read_aliases(directory, {row["entity_id"] for row in entities})
        parent = str(manifest.get("parent_snapshot_sha256", ""))
        if parent != GENESIS and not HEX_SHA256.fullmatch(parent):
            errors.append(f"PARENT_SHA_INVALID:{snapshot}")
        elif parent != GENESIS and not (root / SNAPSHOTS_DIR / parent).is_dir():
            errors.append(f"PARENT_SNAPSHOT_MISSING:{snapshot}:{parent}")
        if _snapshot_sha(parent, entities, aliases) != snapshot:
            errors.append(f"SNAPSHOT_LOGICAL_HASH_MISMATCH:{snapshot}")
        if manifest.get("entity_count") != len(entities) or manifest.get("alias_count") != len(aliases):
            errors.append(f"SNAPSHOT_COUNT_MISMATCH:{snapshot}")
        if validation.get("status") != "PASS" or validation.get("snapshot_sha256") != snapshot:
            errors.append(f"SNAPSHOT_VALIDATION_NOT_PASS:{snapshot}")
        if validation.get("patch_sha256") != manifest.get("patch_sha256"):
            errors.append(f"SNAPSHOT_PATCH_SHA_MISMATCH:{snapshot}")
        integrity_fields = (
            "patch_purpose",
            "operation_count",
            "operations_sha256",
            "pinned_bootstrap_source_sha256",
            "pinned_outcome_blind_inventory_sha256",
        )
        for field in integrity_fields:
            if validation.get(field) != manifest.get(field):
                errors.append(f"SNAPSHOT_PATCH_INTEGRITY_MISMATCH:{snapshot}:{field}")
        if not isinstance(manifest.get("operation_count"), int) or manifest.get("operation_count", 0) <= 0:
            errors.append(f"SNAPSHOT_OPERATION_COUNT_INVALID:{snapshot}")
        if not HEX_SHA256.fullmatch(str(manifest.get("operations_sha256", ""))):
            errors.append(f"SNAPSHOT_OPERATIONS_SHA_INVALID:{snapshot}")
        if manifest.get("patch_purpose") == "AUDITED_INVENTORY_BOOTSTRAP":
            for field in ("pinned_bootstrap_source_sha256", "pinned_outcome_blind_inventory_sha256"):
                if not HEX_SHA256.fullmatch(str(manifest.get(field, ""))):
                    errors.append(f"SNAPSHOT_BOOTSTRAP_PIN_INVALID:{snapshot}:{field}")
        elif manifest.get("patch_purpose") != "STANDARD":
            errors.append(f"SNAPSHOT_PATCH_PURPOSE_INVALID:{snapshot}")
        review = validation.get("independent_review", {})
        if review.get("status") != "PASS" or review.get("independent") is not True or not review.get("reviewer"):
            errors.append(f"SNAPSHOT_INDEPENDENT_REVIEW_NOT_PASS:{snapshot}")
        if _performance_field_paths([_entity_without_hash(row) for row in entities]):
            errors.append(f"PERFORMANCE_METRIC_FIELDS_FORBIDDEN:{snapshot}")
        if _nonzero_post_2025_paths([_entity_without_hash(row) for row in entities]):
            errors.append(f"POST_2025_COUNTER_NONZERO:{snapshot}")
        if parent != GENESIS and (root / SNAPSHOTS_DIR / parent).is_dir():
            parent_entities = {row["entity_id"]: row for row in _read_entities(root / SNAPSHOTS_DIR / parent)}
            current_entities = {row["entity_id"]: row for row in entities}
            missing_ids = sorted(set(parent_entities) - set(current_entities))
            if missing_ids:
                errors.append(f"ENTITY_HISTORY_REMOVED:{snapshot}:{missing_ids[:5]}")
            for entity_id in sorted(set(parent_entities) & set(current_entities)):
                if _failure_count_regressed(
                    parent_entities[entity_id]["trial_ledger_failure_row_count"],
                    current_entities[entity_id]["trial_ledger_failure_row_count"],
                ):
                    errors.append(f"TRIAL_LEDGER_FAILURE_COUNT_REDUCED:{snapshot}:{entity_id}")
    except (OSError, RegistryError, TypeError, AttributeError) as exc:
        errors.append(f"SNAPSHOT_INVALID:{snapshot}:{exc}")
    return errors


def validate_registry(root: Path | str, *, snapshot: str | None = None, validate_all: bool = True) -> dict[str, Any]:
    registry_root = Path(root)
    errors: list[str] = []
    try:
        head = _current_head(registry_root)
    except RegistryError as exc:
        return {"status": "FAIL", "errors": [str(exc)], "head_sha256": None, "validated_snapshots": []}
    snapshots_root = registry_root / SNAPSHOTS_DIR
    if snapshot:
        targets = [snapshot]
    elif validate_all and snapshots_root.is_dir():
        targets = sorted(path.name for path in snapshots_root.iterdir() if path.is_dir() and HEX_SHA256.fullmatch(path.name))
        staging = sorted(path.name for path in snapshots_root.iterdir() if path.is_dir() and not HEX_SHA256.fullmatch(path.name))
        errors.extend(f"UNCOMMITTED_STAGING_DIRECTORY:{name}" for name in staging)
    elif head != GENESIS:
        targets = [head]
    else:
        targets = []
    for target in targets:
        if not HEX_SHA256.fullmatch(str(target)):
            errors.append(f"INVALID_SNAPSHOT_SHA:{target}")
        else:
            errors.extend(_validate_one_snapshot(registry_root, str(target)))
    chain = validate_event_chain(registry_root)
    errors.extend(chain["errors"])
    if chain["tail_head_sha256"] != head:
        errors.append(f"EVENT_CHAIN_HEAD_MISMATCH:events={chain['tail_head_sha256']}:current={head}")
    if head != GENESIS and head not in targets and validate_all:
        errors.append(f"CURRENT_NOT_IN_VALIDATED_SNAPSHOTS:{head}")
    return {"status": "FAIL" if errors else "PASS", "errors": errors, "head_sha256": head, "validated_snapshots": targets, "event_chain": chain}


def resolve_alias(root: Path | str, alias: str, *, snapshot: str | None = None) -> dict[str, Any]:
    registry_root = Path(root)
    manifest, entities, aliases = _load_snapshot_for_read(registry_root, snapshot)
    normalized = normalize_alias(alias)
    matches = [row for row in aliases if row["alias_normalized"] == normalized]
    if not matches:
        raise RegistryError(f"ALIAS_NOT_FOUND:{alias}")
    entity_id = matches[0]["entity_id"]
    entity = next(row for row in entities if row["entity_id"] == entity_id)
    return {
        "status": "PASS",
        "head_sha256": manifest["snapshot_sha256"],
        "alias": alias,
        "alias_normalized": normalized,
        "entity_id": entity_id,
        "entity": _entity_without_hash(entity) | {"row_hash": entity["row_hash"]},
    }


def query_registry(
    root: Path | str,
    *,
    snapshot: str | None = None,
    entity_id: str | None = None,
    alias: str | None = None,
    filters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    registry_root = Path(root)
    manifest, entities, _ = _load_snapshot_for_read(registry_root, snapshot)
    if alias:
        entity_id = resolve_alias(registry_root, alias, snapshot=manifest["snapshot_sha256"])["entity_id"]
    rows = list(entities)
    if entity_id:
        rows = [row for row in rows if row["entity_id"] == entity_id]
    for key, expected in sorted((filters or {}).items()):
        rows = [row for row in rows if row.get(key, row.get("metadata", {}).get(key)) == expected]
    public_rows = [_entity_without_hash(row) | {"row_hash": row["row_hash"]} for row in rows]
    return {"status": "PASS", "head_sha256": manifest["snapshot_sha256"], "count": len(public_rows), "entities": public_rows}


def export_context(
    root: Path | str,
    output: Path | str,
    *,
    entity_ids: Sequence[str] = (),
    aliases_to_resolve: Sequence[str] = (),
    snapshot: str | None = None,
) -> dict[str, Any]:
    registry_root = Path(root)
    manifest, entities, aliases = _load_snapshot_for_read(registry_root, snapshot)
    selected = {str(value) for value in entity_ids}
    alias_map = {row["alias_normalized"]: row["entity_id"] for row in aliases}
    for alias in aliases_to_resolve:
        normalized = normalize_alias(alias)
        if normalized not in alias_map:
            raise RegistryError(f"ALIAS_NOT_FOUND:{alias}")
        selected.add(alias_map[normalized])
    if not selected:
        selected = {row["entity_id"] for row in entities}
    missing = sorted(selected - {row["entity_id"] for row in entities})
    if missing:
        raise RegistryError(f"CONTEXT_ENTITY_NOT_FOUND:{missing}")
    context = {
        "context_schema_version": SCHEMA_VERSION,
        "registry_head_sha256": manifest["snapshot_sha256"],
        "entities": [_entity_without_hash(row) | {"row_hash": row["row_hash"]} for row in entities if row["entity_id"] in selected],
        "aliases": [row for row in aliases if row["entity_id"] in selected],
    }
    _reject_outcome_fields(context)
    _atomic_write_text(Path(output), canonical_json(context).decode("utf-8") + "\n")
    return {"status": "PASS", "output": str(Path(output)), "entity_count": len(context["entities"]), "head_sha256": manifest["snapshot_sha256"]}


def diff_snapshots(root: Path | str, before: str, after: str) -> dict[str, Any]:
    registry_root = Path(root)
    before_manifest, before_rows, before_aliases = _load_snapshot_for_read(registry_root, before)
    after_manifest, after_rows, after_aliases = _load_snapshot_for_read(registry_root, after)
    left = {row["entity_id"]: row for row in before_rows}
    right = {row["entity_id"]: row for row in after_rows}
    left_alias = {row["alias_normalized"]: row["entity_id"] for row in before_aliases}
    right_alias = {row["alias_normalized"]: row["entity_id"] for row in after_aliases}
    return {
        "status": "PASS",
        "from_snapshot_sha256": before_manifest["snapshot_sha256"],
        "to_snapshot_sha256": after_manifest["snapshot_sha256"],
        "entities_added": sorted(set(right) - set(left)),
        "entities_removed": sorted(set(left) - set(right)),
        "entities_changed": sorted(key for key in set(left) & set(right) if left[key]["row_hash"] != right[key]["row_hash"]),
        "aliases_added": sorted(set(right_alias) - set(left_alias)),
        "aliases_removed": sorted(set(left_alias) - set(right_alias)),
        "aliases_remapped": sorted(key for key in set(left_alias) & set(right_alias) if left_alias[key] != right_alias[key]),
    }


def _load_config(config_path: Path | str | None, root_override: Path | str | None) -> tuple[Path, dict[str, Any]]:
    default = Path(__file__).resolve().parent / "config" / "research_registry.json"
    path = Path(config_path) if config_path else default
    config = _json_file(path)
    if config.get("schema_version") != SCHEMA_VERSION:
        raise RegistryError("CONFIG_SCHEMA_VERSION_INVALID")
    root_value = root_override if root_override is not None else config.get("registry_root")
    if not root_value:
        raise RegistryError("REGISTRY_ROOT_NOT_CONFIGURED")
    root = Path(root_value)
    if not root.is_absolute():
        root = (path.parent / root).resolve()
    return root, config


def _read_input_json(path: Path | str) -> Mapping[str, Any]:
    value = _json_file(Path(path))
    if not isinstance(value, Mapping):
        raise RegistryError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def _read_patch_input(path: Path | str) -> Mapping[str, Any]:
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        records: list[Mapping[str, Any]] = []
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RegistryError(f"PATCH_JSONL_INVALID:{number}") from exc
            if not isinstance(record, Mapping):
                raise RegistryError(f"PATCH_JSONL_RECORD_NOT_OBJECT:{number}")
            records.append(record)
        if not records or records[0].get("record_type") != "PATCH_HEADER":
            raise RegistryError("PATCH_JSONL_HEADER_REQUIRED")
        header = dict(records[0])
        header.pop("record_type", None)
        operations: list[dict[str, Any]] = []
        for index, record in enumerate(records[1:], 2):
            if record.get("record_type") != "OPERATION":
                raise RegistryError(f"PATCH_JSONL_OPERATION_RECORD_REQUIRED:{index}")
            operation = dict(record)
            operation.pop("record_type", None)
            operations.append(operation)
        header["operations"] = operations
        value = header
    if not isinstance(value, Mapping):
        raise RegistryError(f"PATCH_OBJECT_REQUIRED:{path}")
    return value


def _print_json(value: Any) -> None:
    print(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="compact registry configuration JSON")
    parser.add_argument("--root", help="override the configured registry root")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("current", help="show CURRENT and its manifest")
    validate = commands.add_parser("validate", help="validate snapshots and event chain")
    validate.add_argument("--snapshot")
    query = commands.add_parser("query", help="query entities in a snapshot")
    query.add_argument("--snapshot")
    query.add_argument("--entity-id")
    query.add_argument("--alias")
    query.add_argument("--field", action="append", default=[])
    query.add_argument("--value", action="append", default=[])
    resolve = commands.add_parser("resolve-alias", help="resolve a canonical name or alias")
    resolve.add_argument("alias")
    resolve.add_argument("--snapshot")
    export = commands.add_parser("export-context", help="write compact task-readable context JSON")
    export.add_argument("--output", required=True)
    export.add_argument("--entity-id", action="append", default=[])
    export.add_argument("--alias", action="append", default=[])
    export.add_argument("--snapshot")
    proposal = commands.add_parser("preflight-proposal", help="classify a proposal without mutation")
    proposal.add_argument("--proposal", required=True)
    proposal.add_argument("--output")
    apply_command = commands.add_parser("apply-patch", help="apply one reviewed JSON/JSONL patch")
    apply_command.add_argument("--patch", required=True)
    diff = commands.add_parser("diff-snapshots", help="compare two immutable snapshots")
    diff.add_argument("--from-snapshot", required=True)
    diff.add_argument("--to-snapshot", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        root, config = _load_config(args.config, args.root)
        if args.command == "current":
            result = current_state(root)
        elif args.command == "validate":
            result = validate_registry(root, snapshot=args.snapshot)
        elif args.command == "query":
            if len(args.field) != len(args.value):
                raise RegistryError("QUERY_FIELD_VALUE_ARITY_MISMATCH")
            result = query_registry(root, snapshot=args.snapshot, entity_id=args.entity_id, alias=args.alias, filters=dict(zip(args.field, args.value)))
        elif args.command == "resolve-alias":
            result = resolve_alias(root, args.alias, snapshot=args.snapshot)
        elif args.command == "export-context":
            result = export_context(root, args.output, entity_ids=args.entity_id, aliases_to_resolve=args.alias, snapshot=args.snapshot)
        elif args.command == "preflight-proposal":
            result = preflight_proposal(root, _read_input_json(args.proposal))
            if args.output:
                _atomic_write_text(Path(args.output), canonical_json(result).decode("utf-8") + "\n")
        elif args.command == "apply-patch":
            result = apply_patch(root, _read_patch_input(args.patch))
        elif args.command == "diff-snapshots":
            result = diff_snapshots(root, args.from_snapshot, args.to_snapshot)
        else:  # pragma: no cover
            raise RegistryError(f"UNKNOWN_COMMAND:{args.command}")
        _print_json(result)
        return 2 if result.get("status") in {"FAIL", "BLOCKED", "REVIEW_REQUIRED"} else 0
    except (OSError, RegistryError, ValueError) as exc:
        _print_json({"status": "FAIL", "error": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
