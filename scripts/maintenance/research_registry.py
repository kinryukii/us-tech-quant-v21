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
from urllib.parse import parse_qsl, unquote, urlsplit


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
    "maxdd",
    "mcc",
    "mdd",
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
    "economic_outcome",
    "false_positive_rate",
    "ks_statistic",
    "log_loss",
    "net_asset_value",
    "outcome_derived_metadata",
    "p_and_l",
    "pr_curve",
    "prospective_economic_outcome",
    "prospective_outcome",
    "realized_performance",
    "r_squared",
    "roc_curve",
    "true_positive_rate",
)
PERFORMANCE_COMPACT_KEY_NAMES = {
    "economicoutcome",
    "economicoutcomes",
    "maxdd",
    "maxdrawdown",
    "maximumdrawdown",
    "pnl",
    "profitandloss",
    "profitloss",
    "realizedperformance",
    "sharperatio",
}
SEMANTIC_DESCRIPTOR_FIELDS = {
    "field",
    "field_label",
    "field_name",
    "label",
    "measurement_label",
    "measurement_name",
    "metric",
    "metric_label",
    "metric_name",
    "metric_type",
    "name",
    "statistic_label",
    "statistic_name",
    "type",
}
SEMANTIC_VALUE_FIELDS = {
    "measurement",
    "measurements",
    "observation",
    "observations",
    "result",
    "results",
    "score",
    "scores",
    "value",
    "values",
}
STRICT_STRUCTURAL_IDENTITY_FIELDS = {
    "alias",
    "aliases",
    "canonical_name",
    "decision_layer",
    "entity_id",
    "entity_type",
    "evidence_source_temporal_status",
    "frozen_name",
    "lifecycle_state",
    "namespace",
    "parent_entity_id",
    "parent_entity_ids",
    "research_branch_cluster",
    "short_name",
    "status",
}
STRUCTURAL_DESCRIPTION_FIELDS = {
    "economic_role",
    "feature_input_family",
    "information_family",
    "information_source",
    "lifecycle_reason",
    "mechanism_family",
    "model_family",
    "outcome_horizon",
    "portfolio_action",
}
PERFORMANCE_VALUE_TERM = re.compile(
    r"\b(?:"
    r"accuracy|alpha|ap|auc|auroc|average\s+precision|brier(?:\s+score)?|calibration|"
    r"cagr|confusion\s+matrix|cross\s+entropy|drawdown|f1|false\s+positive\s+rate|"
    r"gini|hit\s+rate|ic|information\s+coefficient|ks\s+statistic|lift|log\s+loss|"
    r"economic\s+(?:outcomes?|performance)|mae|maxdd|mcc|mdd|mse|nav|net\s+asset\s+value|"
    r"p\s*(?:and|&)\s*l|pnl|precision|profit|"
    r"pr\s+curve|r(?:ank\s+)?ic|r\s*(?:squared|\^?2)|recall|return|returns|rmse|"
    r"realized\s+performance|roc\s+curve|sensitivity|sharpe|sortino|specificity|tail\s+event|"
    r"true\s+positive\s+rate|win\s+rate"
    r")\b",
    re.IGNORECASE,
)
NUMERIC_VALUE = re.compile(
    r"(?<![A-Za-z0-9])[-+]?(?:\d+(?:\.\d+)?|\.\d+)"
    r"(?:[eE][-+]?\d+)?%?(?![A-Za-z])"
)
PERCENT_VALUE_TERM = re.compile(
    r"(?<!\d)\d+(?:\.\d+)?\s*(?:pct|percent)\b",
    re.IGNORECASE,
)
BASIS_POINT_VALUE_TERM = re.compile(
    r"(?<![A-Za-z0-9])[-+]?(?:\d+(?:\.\d+)?|\.\d+)\s*"
    r"(?:bp|bps|basis[- ]?points?)\b",
    re.IGNORECASE,
)
IDENTIFIER_ENCODED_NUMERIC_VALUE_TERM = re.compile(
    r"\b(?:plus\s+|minus\s+)?(?:"
    r"\d+\s+p\s+\d+(?:\s+(?:pct|percent|bp|bps))?|"
    r"\d+\s+(?:e\s+(?:(?:plus|minus)\s+)?|e(?:plus|minus)\s+)\d+|"
    r"\d+\s+(?:pct|percent|bp|bps)"
    r")\b",
    re.IGNORECASE,
)
IDENTIFIER_COMPACT_PERFORMANCE_TERM = re.compile(
    r"(?:accuracy|alpha|ap|auc|auroc|averageprecision|brierscore|calibration|cagr|"
    r"confusionmatrix|crossentropy|drawdown|f1|falsepositiverate|gini|hitrate|ic|"
    r"informationcoefficient|ksstatistic|lift|logloss|economic(?:outcome|outcomes|performance)|"
    r"mae|maxdd|maxdrawdown|maximumdrawdown|mcc|mdd|mse|nav|netassetvalue|pandl|pnl|"
    r"precision|profit|prcurve|rankic|ric|r2|rsquared|recall|returns?|rmse|"
    r"realizedperformance|roccurve|sensitivity|sharpe|sortino|specificity|tailevent|"
    r"truepositiverate|winrate)"
    r"(?:acceptable|achieved|bad|beat|better|excellent|exceptional\d*|exceeded|failed|"
    r"favorable|good|high|improved|inferior|lagged|low|negative|outperformed|outstanding|"
    r"passed|poor|positive|profitable|remarkable|strong|superior|unacceptable|"
    r"underperformed|unprofitable|weak|worse|"
    r"(?:plus|minus)?(?:\d+p\d+(?:pct|percent|bp|bps)?|"
    r"\d+e(?:plus|minus)?\d+|\d+(?:pct|percent|bp|bps)))",
    re.IGNORECASE,
)
IDENTIFIER_COMPACT_BARE_NUMERIC_PERFORMANCE_TERM = re.compile(
    r"(?:accuracy|alpha|auc|auroc|averageprecision|brierscore|calibration|cagr|"
    r"confusionmatrix|crossentropy|drawdown|falsepositiverate|gini|hitrate|"
    r"informationcoefficient|ksstatistic|lift|logloss|economic(?:outcome|outcomes|performance)|"
    r"mae|maxdd|maxdrawdown|maximumdrawdown|mcc|mdd|mse|nav|netassetvalue|pandl|pnl|"
    r"precision|profit|prcurve|rankic|recall|returns?|rmse|realizedperformance|"
    r"roccurve|sensitivity|sharpe|sortino|specificity|tailevent|truepositiverate|winrate)"
    r"(?P<value>\d+)",
    re.IGNORECASE,
)
OUTCOME_EVALUATION_TERM = re.compile(
    r"\b(?:achieved|evaluation|evaluated|holdout|measured|observed|outcome|performance|"
    r"prospective|realized|reported|result|score|test(?:ed)?|validation|validated|2026)\b",
    re.IGNORECASE,
)
PERFORMANCE_PREDICATE_TERM = re.compile(
    r"\b(?:am|appear(?:ed|ing|s)?|are|be|became|become|becomes|been|being|feel(?:s|t)?|"
    r"grew|grow(?:ing|s)?|is|look(?:ed|ing|s)?|prove(?:d|n|s)?|rank(?:ed|ing|s)?|"
    r"rate(?:d|s)?|remain(?:ed|ing|s)?|seem(?:ed|ing|s)?|sound(?:ed|ing|s)?|"
    r"stay(?:ed|ing|s)?|stood|was|were)\b",
    re.IGNORECASE,
)
QUALITATIVE_VALUE_TERM = re.compile(
    r"\b(?:acceptable|achieved|bad|beat|better|excellent|exceptional\d*|exceeded|failed|"
    r"favorable|good|high|improved|inferior|lagged|low|negative|outperformed|outstanding|"
    r"passed|poor|positive|profitable|remarkable|strong|superior|unacceptable|"
    r"underperformed|unprofitable|weak|worse)\b",
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
PERFORMANCE_STORAGE_DENIAL_GLUE_TOKENS = {
    "and",
    "data",
    "evidence",
    "measurement",
    "measurements",
    "metric",
    "metrics",
    "nor",
    "observation",
    "observations",
    "or",
    "outcome",
    "outcomes",
    "prospective",
    "realized",
    "result",
    "results",
    "score",
    "scores",
    "statistic",
    "statistics",
    "value",
    "values",
}
PERFORMANCE_STORAGE_AUXILIARY_TOKENS = {
    "are",
    "be",
    "been",
    "being",
    "currently",
    "ever",
    "had",
    "has",
    "have",
    "is",
    "not",
    "was",
    "were",
}
PERFORMANCE_REFERENCE_GLUE_TOKENS = {
    "artifact",
    "contract",
    "field",
    "frozen",
    "historical",
    "identifier",
    "identity",
    "label",
    "metric",
    "name",
    "overlay",
    "r1",
    "r2",
    "r3",
    "reference",
    "registry",
    "research",
    "schema",
    "source",
    "version",
}
PERFORMANCE_IDENTITY_REFERENCE_FIELDS = {
    "alias",
    "aliases",
    "canonical_name",
    "decision_layer",
    "entity_id",
    "entity_type",
    "evidence_source_temporal_status",
    "frozen_name",
    "information_family",
    "lifecycle_state",
    "namespace",
    "parent_entity_id",
    "short_name",
    "status",
}
PERFORMANCE_REFERENCE_FIELD_SUFFIXES = (
    "_fingerprint",
    "_hash",
    "_ref",
    "_refs",
    "_sha256",
)
REFERENCE_NEUTRAL_NUMERIC_PATH_CONTEXTS = {
    "build",
    "part",
    "partition",
    "rev",
    "revision",
    "schema",
    "v",
    "ver",
    "version",
}
REFERENCE_NEUTRAL_QUERY_VALUE_FIELDS = {
    *REFERENCE_NEUTRAL_NUMERIC_PATH_CONTEXTS,
    "artifact_id",
    "artifact_ref",
    "artifact_refs",
    "artifact_sha256",
    "checksum",
    "commit",
    "commit_sha",
    "commit_sha256",
    "date",
    "datetime",
    "fingerprint",
    "hash",
    "id",
    "identity",
    "path",
    "ref",
    "refs",
    "reference",
    "sha",
    "sha256",
    "timestamp",
    "uri",
    "url",
    "uuid",
}
PERFORMANCE_REFERENCE_FILE_SUFFIX_TOKENS = {
    "bin",
    "csv",
    "json",
    "jsonl",
    "npy",
    "npz",
    "parquet",
    "pickle",
    "pkl",
    "txt",
    "yaml",
    "yml",
}


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
    text = unicodedata.normalize("NFKC", str(key))
    text = re.sub(
        r"(?<![A-Za-z0-9])p\s*(?:&|/|\band\b)\s*l(?![A-Za-z0-9])",
        "pnl",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", text)
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", text)
    return re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_")


def _normalized_performance_key(value: Any) -> str:
    key = _normalized_key(value)
    normalized_tokens: list[str] = []
    for token in key.split("_"):
        if token in {"f1", "r2"}:
            normalized_tokens.append(token)
            continue
        compact_metric = re.match(r"^(f1|r2)(?=[a-z0-9])", token)
        if compact_metric:
            normalized_tokens.append(compact_metric.group(1))
            token = token[compact_metric.end() :]
        token = re.sub(r"(?<=[a-z])(?=\d)", "_", token)
        token = re.sub(r"(?<=\d)(?=[a-z])", "_", token)
        normalized_tokens.extend(part for part in token.split("_") if part)
    return "_".join(normalized_tokens)


def _performance_key_is_forbidden(value: Any) -> bool:
    key = _normalized_performance_key(value)
    if not key:
        return False
    ordered_tokens = key.split("_")
    tokens = set(ordered_tokens)
    compact = key.replace("_", "")
    compact_token_windows = {
        "".join(ordered_tokens[start:end])
        for start in range(len(ordered_tokens))
        for end in range(start + 1, min(len(ordered_tokens), start + 3) + 1)
    }
    return (
        key in PERFORMANCE_KEY_NAMES
        or any(
            key == prefix_key or key.startswith(prefix_key + "_")
            for prefix_key in PERFORMANCE_KEY_PREFIXES
        )
        or any(phrase in key for phrase in PERFORMANCE_KEY_PHRASES)
        or bool(tokens & PERFORMANCE_KEY_TOKENS)
        or compact in PERFORMANCE_COMPACT_KEY_NAMES
        or bool(compact_token_windows & PERFORMANCE_COMPACT_KEY_NAMES)
    )


def _exact_structural_version_token(value: Any) -> bool:
    text = unicodedata.normalize("NFKC", str(value)).strip()
    return bool(re.fullmatch(r"[RrVv]\d+(?:\.\d+)*", text))


def _non_year_numeric_matches(value: Any) -> list[re.Match[str]]:
    text = _bounded_unquote(unicodedata.normalize("NFKC", str(value)))
    matches: list[re.Match[str]] = []
    for number in NUMERIC_VALUE.finditer(text):
        # NUMERIC_VALUE intentionally permits digit-following boundaries for
        # compact metric forms; do not let regex backtracking turn ``13F`` into
        # the numeric outcome ``1`` in a structural identity.
        if number.end() < len(text) and text[number.end()].isdigit():
            continue
        numeric = number.group(0).lstrip("+-").rstrip("%")
        if re.fullmatch(r"\d{4}", numeric) and 1900 <= int(numeric) <= 2100:
            continue
        matches.append(number)
    return matches


def _performance_qualification_present(value: Any) -> bool:
    """Recognize value qualifications, including identifier-safe encodings."""
    text = _bounded_unquote(unicodedata.normalize("NFKC", str(value))).strip()
    if (
        not text
        or _entire_opaque_structural_identity(text)
        or _exact_structural_version_token(text)
    ):
        return False
    metric_text = _normalized_performance_text(text)
    compact_qualification = _compact_performance_qualification_present(text)
    return bool(
        _non_year_numeric_matches(text)
        or IDENTIFIER_ENCODED_NUMERIC_VALUE_TERM.search(metric_text)
        or compact_qualification
        or QUALITATIVE_VALUE_TERM.search(metric_text)
        or SPELLED_NUMBER_TERM.search(metric_text)
        or PERCENT_VALUE_TERM.search(metric_text)
        or BASIS_POINT_VALUE_TERM.search(metric_text)
    )


def _compact_performance_qualification_present(value: Any) -> bool:
    compact_text = _normalized_key(value).replace("_", "")
    if IDENTIFIER_COMPACT_PERFORMANCE_TERM.search(compact_text):
        return True
    for match in IDENTIFIER_COMPACT_BARE_NUMERIC_PERFORMANCE_TERM.finditer(compact_text):
        number = match.group("value")
        if len(number) == 4 and 1900 <= int(number) <= 2100:
            continue
        return True
    return False


def _descriptor_context_has_outcome_leaf(value: Any) -> bool:
    return _performance_qualification_present(value)


def _strict_full_field_structural_identity(value: Any, field: str) -> bool:
    if field not in STRICT_STRUCTURAL_IDENTITY_FIELDS:
        return False
    text = _bounded_unquote(unicodedata.normalize("NFKC", str(value))).strip()
    if not text:
        return False
    if _entire_opaque_structural_identity(text) or _exact_structural_version_token(text):
        return True
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. -]*", text):
        return False
    metric_text = _normalized_performance_text(text)
    return not bool(
        _performance_qualification_present(text)
        or PERFORMANCE_PREDICATE_TERM.search(metric_text)
    )


def _performance_field_paths(
    value: Any, prefix: str = "", *,
    _active_descriptor_paths: tuple[str, ...] = (),
) -> list[str]:
    findings: list[str] = []
    if isinstance(value, Mapping):
        normalized_items = [
            (raw_key, child, _normalized_key(raw_key))
            for raw_key, child in value.items()
        ]
        local_descriptor_paths = tuple(
            f"{prefix}.{raw_key}" if prefix else str(raw_key)
            for raw_key, child, key in normalized_items
            if key in SEMANTIC_DESCRIPTOR_FIELDS
            and (
                isinstance(child, str) and _performance_key_is_forbidden(child)
                or isinstance(child, (list, tuple))
                and any(
                    isinstance(item, str) and _performance_key_is_forbidden(item)
                    for item in child
                )
            )
        )
        active_descriptor_paths = tuple(dict.fromkeys([
            *_active_descriptor_paths, *local_descriptor_paths,
        ]))
        if active_descriptor_paths and any(
            key in SEMANTIC_VALUE_FIELDS for _, _, key in normalized_items
        ):
            findings.extend(active_descriptor_paths)
        for raw_key, child, key in normalized_items:
            path = f"{prefix}.{raw_key}" if prefix else str(raw_key)
            if _performance_key_is_forbidden(key):
                findings.append(path)
            findings.extend(_performance_field_paths(
                child, path, _active_descriptor_paths=active_descriptor_paths,
            ))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            findings.extend(_performance_field_paths(
                child, f"{prefix}[{index}]",
                _active_descriptor_paths=_active_descriptor_paths,
            ))
    elif (
        _active_descriptor_paths
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
    ):
        # Transparent containers retain a prohibited descriptor's meaning at
        # numeric leaves; unrelated numeric governance metadata stays valid.
        findings.extend(_active_descriptor_paths)
    elif (
        _active_descriptor_paths
        and isinstance(value, str)
        and _descriptor_context_has_outcome_leaf(value)
    ):
        # Text values retain the same descriptor authority through transparent
        # wrappers and lists; neutral identity/version text remains structural.
        findings.extend(_active_descriptor_paths)
    return list(dict.fromkeys(findings))


def _bounded_unquote(value: Any, *, rounds: int = 3) -> str:
    text = str(value)
    for _ in range(rounds):
        decoded = unquote(text)
        if decoded == text:
            break
        text = decoded
    return text


def _normalized_performance_text(value: Any) -> str:
    text = _normalized_performance_key(_bounded_unquote(value)).replace("_", " ")
    text = re.sub(r"\bpn\s+l\b", "pnl", text)
    text = re.sub(r"\bprofit\s+(?:and\s+)?loss\b", "pnl", text)
    text = re.sub(r"\bsharpe\s+ratio\b", "sharpe", text)
    text = re.sub(r"\bmax(?:imum)?\s*drawdown\b", "maxdd", text)
    return re.sub(r"\bmax\s+dd\b", "maxdd", text)


def _opaque_reference_token(token: str) -> bool:
    # This exact authorized branch uses R2 as a version, never as r-squared.
    # Suffixes, numeric qualifications and other names still use metric guards.
    if token == "CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2":
        return True
    return bool(re.fullmatch(r"[a-f0-9]{8,}", token, re.IGNORECASE))


def _exact_uuid_token(token: str) -> bool:
    return bool(
        re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            token,
            re.IGNORECASE,
        )
    )


def _entire_opaque_structural_identity(value: Any) -> bool:
    token = unicodedata.normalize("NFKC", str(value)).strip()
    # Exact pinned continuation control paths are structural references. The
    # version-bearing branch plus timestamp must not resemble qualified R2.
    continuation = Path("D:/us-tech-quant-backtests/CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2/20261012T025603+0000_4a58260e")
    if token in {str(continuation / "CONTINUATION_SCOPE.json"), str(continuation / "ACCOUNT_CONVENTION_SCOPE.json")}:
        return True
    return bool(_opaque_reference_token(token) or _exact_uuid_token(token))


def _reference_component_has_performance_qualification(value: Any) -> bool:
    raw_text = _bounded_unquote(value)
    raw_token = unicodedata.normalize("NFKC", raw_text).strip()
    if _opaque_reference_token(raw_token) or _exact_uuid_token(raw_token):
        return False
    metric_text = _normalized_performance_text(value)
    metrics = list(PERFORMANCE_VALUE_TERM.finditer(metric_text))
    if not metrics:
        return False
    if (
        _performance_qualification_present(raw_text)
        or PERFORMANCE_PREDICATE_TERM.search(metric_text)
    ):
        return True
    if _terminal_r2_version_text(str(value), metrics):
        return False
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", raw_token):
        return False
    remainder = PERFORMANCE_VALUE_TERM.sub(" ", metric_text)
    for match in re.finditer(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
        raw_text,
        re.IGNORECASE,
    ):
        opaque_phrase = _normalized_performance_text(match.group(0))
        remainder = re.sub(rf"\b{re.escape(opaque_phrase)}\b", " ", remainder)
    tokens = set(re.findall(r"[a-z0-9]+", remainder))
    tokens -= PERFORMANCE_REFERENCE_GLUE_TOKENS
    tokens -= PERFORMANCE_REFERENCE_FILE_SUFFIX_TOKENS
    return any(not _opaque_reference_token(token) for token in tokens)


def _reference_component_has_performance_descriptor(value: Any) -> bool:
    token = unicodedata.normalize("NFKC", _bounded_unquote(value)).strip()
    if _opaque_reference_token(token) or _exact_uuid_token(token):
        return False
    return _performance_key_is_forbidden(token)


def _reference_component_has_outcome_value(value: Any) -> bool:
    raw_text = unicodedata.normalize("NFKC", _bounded_unquote(value)).strip()
    if not raw_text:
        return False
    if (
        _entire_opaque_structural_identity(raw_text)
        or _exact_structural_version_token(raw_text)
    ):
        return False
    normalized_key = _normalized_key(raw_text)
    metric_text = _normalized_performance_text(raw_text)
    if normalized_key in SEMANTIC_VALUE_FIELDS:
        return True
    if _performance_qualification_present(raw_text):
        return True
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", raw_text):
        return False
    return bool(
        QUALITATIVE_VALUE_TERM.search(metric_text)
        or OUTCOME_EVALUATION_TERM.search(metric_text)
        or PERFORMANCE_PREDICATE_TERM.search(metric_text)
        or SPELLED_NUMBER_TERM.search(metric_text)
        or PERCENT_VALUE_TERM.search(metric_text)
        or BASIS_POINT_VALUE_TERM.search(metric_text)
    )


def _reference_query_value_is_structurally_neutral(
    normalized_key: str, value: Any,
) -> bool:
    text = unicodedata.normalize("NFKC", _bounded_unquote(value)).strip()
    if not text:
        return True
    if _entire_opaque_structural_identity(text) or _exact_structural_version_token(text):
        return True
    if normalized_key in REFERENCE_NEUTRAL_NUMERIC_PATH_CONTEXTS and re.fullmatch(
        r"[Vv]?\d+(?:\.\d+)*", text,
    ):
        return True
    if normalized_key in {"date", "datetime", "timestamp"} and re.fullmatch(
        r"\d{4}(?:[-/:T ]\d{1,2})+(?:[.Z+:-][A-Za-z0-9]+)*", text,
        re.IGNORECASE,
    ):
        return True
    structural_field = bool(
        normalized_key in REFERENCE_NEUTRAL_QUERY_VALUE_FIELDS
        or normalized_key.endswith(PERFORMANCE_REFERENCE_FIELD_SUFFIXES)
        or normalized_key.endswith(("_id", "_ids", "_uuid", "_uuids"))
    )
    return structural_field and not _descriptor_context_has_outcome_leaf(text)


def _reference_query_semantics(query: str) -> tuple[bool, bool]:
    pairs = parse_qsl(query, keep_blank_values=True)
    if not pairs and query:
        pairs = [(unquote(query), "")]
    has_descriptor = False
    has_outcome_value = False
    for raw_key, raw_value in pairs:
        key = _normalized_key(_bounded_unquote(raw_key))
        if _reference_component_has_performance_descriptor(raw_key):
            has_descriptor = True
        if (
            key in SEMANTIC_DESCRIPTOR_FIELDS
            and _reference_component_has_performance_descriptor(raw_value)
        ):
            has_descriptor = True
        if key in SEMANTIC_VALUE_FIELDS and str(raw_value).strip():
            has_outcome_value = True
        elif (
            str(raw_value).strip()
            and not _reference_query_value_is_structurally_neutral(key, raw_value)
            and _descriptor_context_has_outcome_leaf(raw_value)
        ):
            has_outcome_value = True
    return has_descriptor, has_outcome_value


def _reference_query_has_performance_qualification(query: str) -> bool:
    pairs = parse_qsl(query, keep_blank_values=True)
    if not pairs and query:
        pairs = [(unquote(query), "")]
    has_descriptor, has_outcome_value = _reference_query_semantics(query)
    if has_descriptor and has_outcome_value:
        return True
    return any(
        _reference_component_has_performance_qualification(f"{key} {value}")
        for key, value in pairs
    )


def _reference_text_has_performance_qualification(value: str) -> bool:
    text = _bounded_unquote(unicodedata.normalize("NFKC", value)).strip()
    parsed = urlsplit(text)
    is_uri = bool(parsed.scheme and "://" in text)
    has_descriptor = False
    has_outcome_value = False
    if is_uri:
        if _reference_component_has_performance_qualification(parsed.scheme):
            return True
        has_descriptor = (
            has_descriptor
            or _reference_component_has_performance_descriptor(parsed.scheme)
        )
        host = parsed.hostname or ""
        for part in host.split("."):
            if not part:
                continue
            if _reference_component_has_performance_qualification(part):
                return True
            has_descriptor = (
                has_descriptor
                or _reference_component_has_performance_descriptor(part)
            )
        if parsed.username or parsed.password:
            if _reference_component_has_performance_qualification(
                f"{parsed.username or ''} {parsed.password or ''}"
            ):
                return True
            for credential in (parsed.username, parsed.password):
                if not credential:
                    continue
                has_descriptor = (
                    has_descriptor
                    or _reference_component_has_performance_descriptor(credential)
                )
                has_outcome_value = (
                    has_outcome_value
                    or _reference_component_has_outcome_value(credential)
                )
        path_text = _bounded_unquote(parsed.path)
        query = parsed.query
        fragment = _bounded_unquote(parsed.fragment)
    else:
        path_text = _bounded_unquote(text.split("?", 1)[0].split("#", 1)[0])
        query = text.split("?", 1)[1].split("#", 1)[0] if "?" in text else ""
        fragment = text.split("#", 1)[1] if "#" in text else ""

    segments = [part for part in re.split(r"[/\\]+", path_text) if part]
    bare_numeric_path_value = False
    for index, segment in enumerate(segments):
        if _reference_component_has_performance_qualification(segment):
            return True
        has_descriptor = (
            has_descriptor
            or _reference_component_has_performance_descriptor(segment)
        )
        segment_metric_text = _normalized_performance_text(segment)
        metric_segment = bool(PERFORMANCE_VALUE_TERM.search(segment_metric_text))
        metric_remainder_tokens = set(
            re.findall(
                r"[a-z0-9]+",
                PERFORMANCE_VALUE_TERM.sub(" ", segment_metric_text),
            )
        )
        metric_has_structural_glue = bool(metric_remainder_tokens) and bool(
            metric_remainder_tokens
            <= (
                PERFORMANCE_REFERENCE_GLUE_TOKENS
                | PERFORMANCE_REFERENCE_FILE_SUFFIX_TOKENS
            )
        )
        next_index = index + 1
        while (
            next_index < len(segments)
            and (
                _entire_opaque_structural_identity(
                    _bounded_unquote(segments[next_index])
                )
                or unicodedata.normalize(
                    "NFKC", _bounded_unquote(segments[next_index]),
                ).strip() in {".", ".."}
            )
        ):
            next_index += 1
        next_text = (
            unicodedata.normalize(
                "NFKC", _bounded_unquote(segments[next_index]),
            ).strip()
            if next_index < len(segments)
            else ""
        )
        next_is_bare_numeric = bool(
            re.fullmatch(r"[-+]?(?:\d+(?:\.\d+)?|\.\d+)", next_text)
        )
        next_is_year = bool(
            re.fullmatch(r"\d{4}", next_text)
            and 1900 <= int(next_text) <= 2100
        )
        next_is_neutral_numeric_context = bool(
            next_index < len(segments)
            and (
                _normalized_key(segments[next_index])
                in REFERENCE_NEUTRAL_NUMERIC_PATH_CONTEXTS
                or re.fullmatch(
                    r"v\d+(?:\.\d+)+",
                    next_text,
                    re.IGNORECASE,
                )
                or next_is_year
                or (next_is_bare_numeric and metric_has_structural_glue)
            )
        )
        current_text = unicodedata.normalize(
            "NFKC", _bounded_unquote(segment),
        ).strip()
        current_is_bare_numeric = bool(
            re.fullmatch(r"[-+]?(?:\d+(?:\.\d+)?|\.\d+)", current_text)
        )
        prior_index = index - 1
        while prior_index >= 0 and (
            _entire_opaque_structural_identity(
                _bounded_unquote(segments[prior_index])
            )
            or unicodedata.normalize(
                "NFKC", _bounded_unquote(segments[prior_index]),
            ).strip() in {".", ".."}
        ):
            prior_index -= 1
        prior_segment = segments[prior_index] if prior_index >= 0 else ""
        prior_metric_text = _normalized_performance_text(prior_segment)
        prior_metric_tokens = set(re.findall(
            r"[a-z0-9]+",
            PERFORMANCE_VALUE_TERM.sub(" ", prior_metric_text),
        ))
        prior_metric_is_structural = bool(
            PERFORMANCE_VALUE_TERM.search(prior_metric_text)
            and prior_metric_tokens
            and prior_metric_tokens <= (
                PERFORMANCE_REFERENCE_GLUE_TOKENS
                | PERFORMANCE_REFERENCE_FILE_SUFFIX_TOKENS
            )
        )
        date_path_component = bool(
            re.fullmatch(r"\d{4}", current_text)
            and 1900 <= int(current_text) <= 2100
            or index >= 1
            and re.fullmatch(r"\d{4}", segments[index - 1])
            and 1900 <= int(segments[index - 1]) <= 2100
            or index >= 2
            and re.fullmatch(r"\d{4}", segments[index - 2])
            and 1900 <= int(segments[index - 2]) <= 2100
        )
        current_is_neutral_numeric_context = bool(
            current_is_bare_numeric
            and (
                date_path_component
                or _normalized_key(prior_segment)
                in REFERENCE_NEUTRAL_NUMERIC_PATH_CONTEXTS
                or prior_metric_is_structural
            )
        )
        has_outcome_value = bool(
            has_outcome_value
            or (
                not current_is_neutral_numeric_context
                and _reference_component_has_outcome_value(segment)
            )
        )
        bare_numeric_path_value = bool(
            bare_numeric_path_value
            or current_is_bare_numeric and not current_is_neutral_numeric_context
        )
        if (
            metric_segment
            and next_index < len(segments)
            and not next_is_neutral_numeric_context
            and (
                _descriptor_context_has_outcome_leaf(segments[next_index])
                or _reference_component_has_outcome_value(segments[next_index])
            )
        ):
            if _reference_component_has_performance_qualification(
                f"{segment} {segments[next_index]}"
            ):
                return True

    if query:
        if _reference_query_has_performance_qualification(query):
            return True
        query_descriptor, query_outcome_value = _reference_query_semantics(query)
        has_descriptor = has_descriptor or query_descriptor
        has_outcome_value = has_outcome_value or query_outcome_value
    if fragment:
        if _reference_component_has_performance_qualification(fragment):
            return True
        if _reference_query_has_performance_qualification(fragment):
            return True
        fragment_descriptor, fragment_outcome_value = _reference_query_semantics(
            fragment
        )
        has_descriptor = (
            has_descriptor
            or fragment_descriptor
            or _reference_component_has_performance_descriptor(fragment)
        )
        has_outcome_value = (
            has_outcome_value
            or fragment_outcome_value
            or _reference_component_has_outcome_value(fragment)
        )
    return has_descriptor and (has_outcome_value or bare_numeric_path_value)


def _terminal_r2_version_text(
    value: str, metric_matches: Sequence[re.Match[str]]
) -> bool:
    if not metric_matches:
        return False
    if any(match.group(0).casefold() != "r2" for match in metric_matches):
        return False
    text = _bounded_unquote(unicodedata.normalize("NFKC", value)).strip()
    normalized_text = _normalized_performance_text(text)
    if (
        QUALITATIVE_VALUE_TERM.search(normalized_text)
        or OUTCOME_EVALUATION_TERM.search(normalized_text)
        or PERFORMANCE_PREDICATE_TERM.search(normalized_text)
        or SPELLED_NUMBER_TERM.search(normalized_text)
        or PERCENT_VALUE_TERM.search(normalized_text)
        or BASIS_POINT_VALUE_TERM.search(normalized_text)
    ):
        return False
    return bool(
        re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.:/\\ -]*[_.:/\\ -]R2",
            text,
            re.IGNORECASE,
        )
    )


def _terminal_r2_identity_version(
    value: str, field: str, metric_matches: Sequence[re.Match[str]]
) -> bool:
    return bool(
        field in PERFORMANCE_IDENTITY_REFERENCE_FIELDS
        and _terminal_r2_version_text(value, metric_matches)
    )


def _performance_clause_has_value(value: str, path: str = "") -> bool:
    text = _bounded_unquote(unicodedata.normalize("NFKC", value))
    metric_scan_text = _normalized_performance_text(text)
    metric_matches = list(PERFORMANCE_VALUE_TERM.finditer(metric_scan_text))
    compact_performance = _compact_performance_qualification_present(text)
    if compact_performance:
        return True
    if not metric_matches:
        return False
    numeric_values: list[re.Match[str]] = []
    for number in NUMERIC_VALUE.finditer(text):
        numeric = number.group(0).lstrip("+-").rstrip("%")
        if re.fullmatch(r"\d{4}", numeric) and 1900 <= int(numeric) <= 2100:
            continue
        numeric_values.append(number)
    outcome_context = bool(
        OUTCOME_EVALUATION_TERM.search(text)
        or OUTCOME_EVALUATION_TERM.search(metric_scan_text)
    )
    qualitative_value = bool(
        QUALITATIVE_VALUE_TERM.search(text)
        or QUALITATIVE_VALUE_TERM.search(metric_scan_text)
    )
    spelled_value = bool(
        SPELLED_NUMBER_TERM.search(text)
        or SPELLED_NUMBER_TERM.search(metric_scan_text)
    )
    percent_value = bool(
        PERCENT_VALUE_TERM.search(text)
        or PERCENT_VALUE_TERM.search(metric_scan_text)
    )
    basis_point_value = bool(
        BASIS_POINT_VALUE_TERM.search(text)
        or BASIS_POINT_VALUE_TERM.search(metric_scan_text)
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
    reference_field = field.endswith(PERFORMANCE_REFERENCE_FIELD_SUFFIXES)
    reference_shape = bool(
        reference_field
        and not re.search(r"\s", text)
        and (
            re.fullmatch(r"[A-Za-z0-9_.-]+", text)
            or "://" in text
            or re.search(r"[/\\?#]", text)
        )
    )
    if reference_shape:
        return _reference_text_has_performance_qualification(text)
    if (
        field in STRICT_STRUCTURAL_IDENTITY_FIELDS
        and _performance_qualification_present(text)
    ):
        return True
    if _strict_full_field_structural_identity(text, field):
        return False
    if (
        field in STRUCTURAL_DESCRIPTION_FIELDS
        and not HARD_REALIZED_CONTEXT.search(hard_context_text)
        and not numeric_values
        and not qualitative_value
        and not spelled_value
        and not percent_value
        and not basis_point_value
    ):
        return False
    if (
        field in SAFE_STRUCTURAL_VALUE_FIELDS
        and not HARD_REALIZED_CONTEXT.search(hard_context_text)
        and not (
            field in TARGET_DEFINITION_FIELDS
            and (assignment_value or spelled_appended_value)
        )
    ):
        return False
    if PERFORMANCE_PREDICATE_TERM.search(text):
        return True
    if percent_value or basis_point_value:
        return True
    if outcome_context:
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
    remainder = PERFORMANCE_VALUE_TERM.sub(" ", metric_scan_text)
    qualification_tokens = set(re.findall(r"[a-z0-9]+", remainder))
    if _terminal_r2_identity_version(text, field, metric_matches):
        return False
    return not qualification_tokens <= PERFORMANCE_REFERENCE_GLUE_TOKENS


def _strip_performance_storage_denials(value: str) -> str:
    # Existing registry governance prose may explicitly deny an alpha claim or
    # record that an alpha identity is unresolved. Blank only those grammatical
    # denials; adjacent economic conclusions remain available to the firewall.
    for pattern in (
        r"\bnot\s+(?:an?\s+)?(?:separate\s+)?alpha\s+claim\b",
        r"\balpha\s+identity\s+(?:is|remain(?:s|ed)?)\s+"
        r"(?:inconclusive|unproven|unresolved)\b",
    ):
        value = re.sub(
            pattern,
            lambda match: " " * len(match.group(0)),
            value,
            flags=re.IGNORECASE,
        )
    denial = re.compile(
        r"\b(?:no|never)\b[^.;:\n]{0,160}?\b"
        r"(?:available|imported|persisted|recorded|retained|stored)\b",
        re.IGNORECASE,
    )

    def strip_if_metric_is_subject(match: re.Match[str]) -> str:
        denial_text = match.group(0)
        storage_matches = list(
            re.finditer(
                r"\b(?:available|imported|persisted|recorded|retained|stored)\b",
                denial_text,
                re.IGNORECASE,
            )
        )
        if not storage_matches or re.search(
            r"(?:=|\bequals?\b)", denial_text, re.IGNORECASE
        ):
            return denial_text
        subject_tokens = _normalized_key(
            denial_text[: storage_matches[-1].start()]
        ).split("_")
        if subject_tokens and subject_tokens[0] in {"no", "never"}:
            subject_tokens.pop(0)
        while (
            subject_tokens
            and subject_tokens[-1] in PERFORMANCE_STORAGE_AUXILIARY_TOKENS
        ):
            subject_tokens.pop()
        metric_text = " ".join(subject_tokens)
        metric_text = re.sub(r"\bpn\s+l\b", "pnl", metric_text)
        metric_text = re.sub(r"\bprofit\s+and\s+loss\b", "pnl", metric_text)
        metric_text = re.sub(r"\bmax\s+dd\b", "maxdd", metric_text)
        metrics = list(PERFORMANCE_VALUE_TERM.finditer(metric_text))
        remainder = PERFORMANCE_VALUE_TERM.sub(" ", metric_text)
        remainder_tokens = set(re.findall(r"[a-z0-9]+", remainder))
        structurally_bare = (
            bool(metrics)
            and metrics[0].start() <= 32
            and remainder_tokens <= PERFORMANCE_STORAGE_DENIAL_GLUE_TOKENS
        )
        if (
            structurally_bare
            and not NUMERIC_VALUE.search(denial_text)
            and not SPELLED_NUMBER_TERM.search(denial_text)
            and not BASIS_POINT_VALUE_TERM.search(denial_text)
        ):
            return " " * len(denial_text)
        return denial_text

    return denial.sub(strip_if_metric_is_subject, value)


def _string_has_performance_value(value: str, path: str = "") -> bool:
    normalized_value = unicodedata.normalize("NFKC", value)
    if _entire_opaque_structural_identity(normalized_value):
        return False
    text = _strip_performance_storage_denials(normalized_value)
    coordination_separator = r"[\s._,/\\-]+"
    punctuation_separator = r"\s*[._,/\\-]+\s*"
    text = re.sub(
        rf"\bp(?:{coordination_separator}and{coordination_separator}|[\s._,\\-]*&[\s._,\\-]*|"
        rf"[\s._,\\-]*/[\s._,\\-]*)l\b",
        "pnl",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        rf"\bprofit{coordination_separator}(?:and{coordination_separator})?loss\b",
        "profit_loss",
        text,
        flags=re.IGNORECASE,
    )
    for pattern, replacement in (
        (rf"\bsharpe{punctuation_separator}ratio\b", "sharpe_ratio"),
        (rf"\beconomic{punctuation_separator}outcomes?\b", "economic_outcome"),
        (rf"\brealized{punctuation_separator}performance\b", "realized_performance"),
        (rf"\bmax(?:imum)?{punctuation_separator}drawdown\b", "max_drawdown"),
        (rf"\bmax{punctuation_separator}dd\b", "maxdd"),
    ):
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    text = re.sub(
        r",(?=\s*[-+]?(?:\d+(?:\.\d+)?|\.\d+)\s*%?)", ":", text,
    )
    field = _normalized_key(path.rsplit(".", 1)[-1].split("[", 1)[0]) if path else ""
    reference_field = field.endswith(PERFORMANCE_REFERENCE_FIELD_SUFFIXES)
    identity_field = bool(
        field in STRICT_STRUCTURAL_IDENTITY_FIELDS
        or set(field.split("_"))
        & {
            "alias", "aliases", "code", "codes", "id", "ids", "identity",
            "identities", "key", "keys", "label", "labels", "name", "names",
            "type", "types",
        }
    )
    if (
        not reference_field
        and identity_field
        and PERFORMANCE_VALUE_TERM.search(_normalized_performance_text(text))
        and _performance_qualification_present(text)
    ):
        # Identity metadata cannot use punctuation to separate a metric from
        # its qualification. Reference fields retain their path/query-aware
        # neutral-version handling below; ordinary prose remains clause-aware.
        return True
    if (
        field in STRICT_STRUCTURAL_IDENTITY_FIELDS
        or reference_field
    ):
        # Identity/reference separators are structural syntax, not semantic
        # clause boundaries.  Evaluate the complete field so ``SHARPE. 1P2``
        # and equivalent encoded qualifications cannot split from the metric.
        return _performance_clause_has_value(text, path)
    clauses = re.split(
        r";|\n+|[.,](?=\s|$)|"
        r"\b(?:although|and|but|however|though|while|whereas|yet)\b",
        text,
        flags=re.IGNORECASE,
    )
    return any(
        _performance_clause_has_value(clause, path)
        for clause in clauses
        if clause.strip()
    )


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


def _nonzero_post_2025_paths(
    value: Any, prefix: str = "", *, _counter_context: bool = False,
) -> list[str]:
    findings: list[str] = []
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = _normalized_key(raw_key)
            path = f"{prefix}.{raw_key}" if prefix else str(raw_key)
            is_counter = bool(
                re.search(r"(?:post_?2025|after_?2025|2026).*(?:count|counter|rows|samples|labels|observations)", key)
                or re.search(r"(?:count|counter|rows|samples|labels|observations).*(?:post_?2025|after_?2025|2026)", key)
            )
            findings.extend(_nonzero_post_2025_paths(
                child, path, _counter_context=_counter_context or is_counter,
            ))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            findings.extend(_nonzero_post_2025_paths(
                child, f"{prefix}[{index}]", _counter_context=_counter_context,
            ))
    elif (
        _counter_context
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value != 0
    ):
        findings.append(prefix or "<counter>")
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
    # The writer hashes metadata as a nested namespace. Flattening a same-name
    # metadata key here can overwrite a logical column and break that identity.
    raw["metadata"] = metadata
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

    # A version suffix alone does not repackage this exact predeclared new
    # learner/objective question. This narrow classification correction occurs
    # after terminal identity/lineage/stem/authority/specification/geometry gates;
    # it cannot override their BLOCKED decisions or produce automatic PASS.
    breadth_parent = entity_by_id.get(R3_REVIEW_PARENT_ID, {})
    version_only_breadth_question = (
        candidate["entity_id"] == BREADTH_REVIEW_ENTITY_ID
        and candidate["canonical_name"] == BREADTH_REVIEW_ENTITY_ID
        and not candidate["aliases"] and candidate.get("status") == "OPEN"
        and candidate.get("entity_type") == "RESEARCH_BRANCH"
        and candidate["decision_layer"] == "PURE_SELECTOR"
        and proposal.get("change_type") == "EXPLICIT_HUMAN_SAME_INFORMATION_LEARNER_OBJECTIVE_BREADTH"
        and not proposal.get("claimed_novelty")
        and candidate.get("parent_entity_id") == R3_REVIEW_PARENT_ID
        and proposal.get("parent_entity_id") == R3_REVIEW_PARENT_ID
        and breadth_parent.get("status") == "ACTIVE"
        and breadth_parent.get("information_source_fingerprint") == R3_REVIEW_INFORMATION_SHA256
        and breadth_parent.get("metadata", {}).get("target_definition")
            == "Mean QQQ-relative excess return over 3D 5D 10D and 20D"
        and candidate["information_source_fingerprint"] == R3_REVIEW_INFORMATION_SHA256
        and candidate["specification_fingerprint"] == sha256_value(BREADTH_REVIEW_SPECIFICATION)
        and canonical_json(candidate.get("specification")) == canonical_json(BREADTH_REVIEW_SPECIFICATION)
        and candidate["mechanism_fingerprint"] == sha256_value(BREADTH_REVIEW_MECHANISM)
        and canonical_json(candidate.get("mechanism")) == canonical_json(BREADTH_REVIEW_MECHANISM)
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
            and variant_repackaging and not version_only_breadth_question
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


# Task-scoped architecture update: retain automatic classification, and record
# this one explicitly authorized same-source scientific question as OPEN metadata.
R3_REVIEW_ENTITY_ID = "V24_C_SELECTOR_PIT_MONTHLY_RISK_R3"
R3_REVIEW_PARENT_ID = "RAW_A2_HGB_BASELINE"
R3_REVIEW_INFORMATION_SHA256 = "2381b2d70d63755a4f51e32da048586029db41a234bb2182eb9a7851101bbc15"
R3_REVIEW_SPECIFICATION = {
    "target": "MEAN_ER_3D_5D_10D_20D",
    "risk_cadence": "MONTHLY", "head_cadence": "ANNUAL",
    "lookback_sessions": 63, "min_observations": 30,
    "core": ["DIAG", "LW", "OAS", "PCA", "EWMA"],
    "role_ids": ["MONTHLY_FIXED_CORE_RIDGE", "MONTHLY_FIXED_CORE_HGB",
                 "MONTHLY_COVERAGE_FLAG_ONLY_RIDGE", "MONTHLY_COVERAGE_FLAG_ONLY_HGB"],
    "monthly_risk_state_slots": 240, "matched_annual_risk_state_slots": 20,
    "backend_fit_calls": 192, "configs_per_role": 1, "seeds": [20260928],
    "retry_allowance": 0, "test2026": "LOCKED", "legacy_role_exposure_count": 91,
    "identity_policy": "NO_CROSS_IDENTITY_STITCHING",
    "training_years": [2022, 2023, 2024, 2025], "evaluation_years": [2023, 2024, 2025],
}
R3_REVIEW_MECHANISM = {
    "question": "risk state refresh timing",
    "fixed_comparisons": ["monthly full vs annual full", "monthly full vs monthly flag-only"],
    "base_state": "DIRECT_REUSE_CALIBRATED_OOF", "downstream_state": "FROZEN",
}


# The explicitly authorized successor changes the authority premise, not raw
# bytes or base fits. Keep the automatic reuse decision and require independent
# review of this exact OPEN mechanism-only identity; no terminal override.
FH_REVIEW_ENTITY_ID = "V24_C_SELECTOR_FROZEN_HISTORY_MONTHLY_RISK_R4"
FH_REVIEW_SPECIFICATION = {
    **R3_REVIEW_SPECIFICATION,
    "source_contract_mode": "FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY",
    "mechanism_research_eligible": True,
    "strict_PIT_promotion_eligible": False,
}
FH_REVIEW_MECHANISM = {
    **R3_REVIEW_MECHANISM,
    "authority_premise": "DECLARED_FROZEN_HISTORY_NOT_STRICT_HISTORICAL_PIT",
}


# The same-input successor is a fixed learner/objective study, not a new source,
# risk search, reopening of R4, or general override of automatic decisions.
BREADTH_REVIEW_ENTITY_ID = "V24_C_SELECTOR_ALGORITHM_BREADTH_R5"
BREADTH_REVIEW_ROLE_IDS = [
    "BOUNDARY_LOGISTIC", "BOUNDARY_RF", "BOUNDARY_EXTRA", "BOUNDARY_HGB",
    "BOUNDARY_XGB", "BOUNDARY_LGB", "BOUNDARY_CAT", "BOUNDARY_MLP",
    "PAIRWISE_LINEAR", "PAIRWISE_MLP", "PAIRWISE_RESNET", "PAIRWISE_FT",
    "LISTWISE_MLP", "LISTWISE_RESNET", "LISTWISE_FT",
    "RANK_XGB_NDCG", "RANK_LGB_XENDCG", "RANK_CAT_YETIRANK",
]
BREADTH_REVIEW_FEATURES = [
    "ret_1d", "ret_3d", "ret_5d", "ret_10d", "ret_20d", "ret_40d", "ret_60d", "ret_120d",
    "price_vs_ma10", "price_vs_ma20", "price_vs_ma50", "price_vs_ma120", "ma10_vs_ma20",
    "ma20_vs_ma50", "ma50_vs_ma120", "realized_vol_5d", "realized_vol_10d", "realized_vol_20d",
    "realized_vol_60d", "downside_vol_20d", "upside_vol_20d", "distance_from_high_20d",
    "distance_from_high_60d", "distance_from_low_20d", "distance_from_low_60d",
    "max_drawdown_20d", "max_drawdown_60d", "avg_volume_20d", "avg_volume_60d",
    "volume_ratio_5d_20d", "volume_ratio_20d_60d", "avg_dollar_volume_20d",
]
BREADTH_REVIEW_SPECIFICATION = {
    "target": "MEAN_ER_3D_5D_10D_20D",
    "role_ids": BREADTH_REVIEW_ROLE_IDS, "feature_count": 32,
    "feature_order_sha256": sha256_value(BREADTH_REVIEW_FEATURES),
    "input_artifact_sha256": {
        "training": "31cc2b3dd2aa7a7c3372d56d5f3f351746b4ad06ef984563de576071913615fb",
        "features": "0cb9a5acaa0c9f9e2170bf3964292388395c5bfce446fb25a4ad3dcdcc1d1b3b",
        "members": "c03cc35f3569cb968c3d48cefd08488c75c02389e5e430d11526a0284ad2b637",
        "raw_oof": "e336be6c267167356ce3d39fa629f80fe7b2968711112a9c976fdb002c693468",
    },
    "raw_score_sha256": "bdd3191c8537b419c187ecd274c5ae43b6dfdaf5d55d0015c5ca020b1b38274b",
    "configs_per_role": 1, "seeds": [20260928], "retry_allowance": 0,
    "backend_fit_calls": 108, "model_fit_calls": 54, "scaler_fit_calls": 54,
    "risk_state_fit_calls": 0, "statistical_adapter_state_slots": 0, "base_reference_refits": 0,
    "training_years": [2023, 2024, 2025], "prediction_years": [2023, 2024, 2025],
    "evaluation_years": [2023, 2024, 2025], "legacy_role_exposure_count": 99,
    "failure_policy": "RETAIN_FAILED_UNTESTABLE_NO_REFUND_NO_RERUN",
    "sampling": {"max_rows": 40000, "method": "uniform no-replacement by decision date, same keys for all roles; seed fixed; target never used for sampling", "seed": 20260928},
    "fitting_weights": "fixed day-balanced sampled keys; each input row weight one, no explicit equal-total-date sample_weight",
    "identity_policy": "EXACT_FROZEN_MEMBERSHIP_CUSIP_UID; no recomputed identity/history",
    "risk_representation": "EXACT_ORIGINAL_PIT32_ONLY; NO_R4_RISK_OR_COVERAGE_COLUMNS",
    "train_cutoff": "signal_date < Jan1(year) AND target_end_date < Jan1(year)",
    "boundary_transform": "fold mature full training U_t: target descending, security_uid ascending, first min(20,pool size); then same sampled keys",
    "pair_transform": "each anchor four uniform distinct non-self partners sampled without target; same fixed seed; target difference sign; ties zero loss; each anchor unit total weight",
    "list_transform": "sampled group full-pool Top20 indicator normalized to mass; zero-positive group zero loss; group weight equals sampled row count",
    "native_relevance": "sampled training date group target pct rank average; floor(rank*5) clipped to 4",
    "base_reference_policy": "EXACT_REUSE_ALL_COMPLETE_NATIVE_DIRECT_OOF; NO_RESELECT_OLD_FINALISTS",
    "selection_rule": "FROZEN_TOP20_REPLACEMENT_EDGE_AND_SHARED_20_SESSION_STUDENTIZED_ONE_SIDED_MAXT",
    "test2026": "LOCKED", "source_contract_mode": "FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY",
    "mechanism_research_eligible": True, "strict_PIT_promotion_eligible": False,
}
BREADTH_REVIEW_MECHANISM = {
    "question": "same-information learner and selection-aligned objective breadth",
    "objective_families": ["TOP20_BOUNDARY_CLASSIFICATION", "PAIRWISE_TARGET_ORDER",
                           "LISTWISE_TOP20_MASS", "NATIVE_LISTWISE_RANK"],
    "base_state": "DIRECT_REUSE_ALL_COMPLETE_NATIVE_OOF", "downstream_state": "FROZEN",
    "risk_state": "NO_NEW_RISK_OR_COVERAGE_INPUTS", "prior_R4": "CLOSED_NO_REOPEN",
    "authority_premise": "DECLARED_FROZEN_HISTORY_NOT_STRICT_HISTORICAL_PIT",
}


BREADTH_REVIEW_SCOPE = {
    "schema_version": 1, "research_id": BREADTH_REVIEW_ENTITY_ID,
    "parent_entity_id": R3_REVIEW_PARENT_ID,
    "information_source_fingerprint": R3_REVIEW_INFORMATION_SHA256,
    "specification": BREADTH_REVIEW_SPECIFICATION, "mechanism": BREADTH_REVIEW_MECHANISM,
    "source_contract_mode": "FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY",
    "mechanism_research_eligible": True, "strict_PIT_promotion_eligible": False,
    "fit_authority": False, "formal_freeze_authority": False,
    "source_gate": "FROZEN_HISTORY_CONTRACT_AND_FORMAL_FREEZE_REQUIRED",
}


def _r3_review_record(reference: Any, digest: Any, filename: str) -> dict[str, Any]:
    """Read an exact, bounded, newly authored metadata evidence reference."""
    path = Path(_string(reference, filename))
    pinned = _require_sha(digest, filename + ".sha256")
    if not path.is_absolute() or path.name != filename:
        raise RegistryError("R3_REVIEW_METADATA_REFERENCE_INVALID")
    try:
        if path.resolve(strict=True) != path.absolute() or path.stat().st_size > 65_536:
            raise RegistryError("R3_REVIEW_METADATA_REFERENCE_UNSAFE")
        data = path.read_bytes()
        if len(data) > 65_536 or hashlib.sha256(data).hexdigest() != pinned:
            raise RegistryError("R3_REVIEW_METADATA_SHA256_MISMATCH")
        record = json.loads(data.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RegistryError("R3_REVIEW_METADATA_UNREADABLE") from exc
    if not isinstance(record, dict):
        raise RegistryError("R3_REVIEW_METADATA_OBJECT_REQUIRED")
    _reject_outcome_fields(record)
    _reject_similarity_controls(record)
    return record


from scripts.maintenance.consensus100_registry_review import REVIEW_SCOPE as _CONSENSUS100_REVIEW_SCOPE
from scripts.maintenance.consensus100_registry_review import CONTINUATION_REVIEW_SCOPE as _CONSENSUS100_CONTINUATION_REVIEW_SCOPE
from scripts.maintenance.consensus100_registry_review import COMPARISON_REVIEW_SCOPE as _CONSENSUS100_COMPARISON_REVIEW_SCOPE


# Exact already-human-authorized account-authority child. No generic override.
_A_RESEARCH_ACCOUNT_REVIEW_ID = "V24_A_FROZEN_HISTORY_RESEARCH_ACCOUNT_AND_POLICY_EVALUATION_R1"
_A_RESEARCH_ACCOUNT_CANDIDATE_ROW = "53efc65557c66e9de9a0da294d19c35e152cbb7ed01328df8ca0245e602f3d4c"
_A_RESEARCH_ACCOUNT_CONTRACT_SHA = "5803399951d2b76918ca6ff8a718d805804ddb5f8e336c6773f4cce83e88621e"
_A_RESEARCH_ACCOUNT_HUMAN_SHA = "149e4158ede7294506c39c075fbc216649a01ea80bf510e7b26e2f284cc8533a"


_A_RESEARCH_ACCOUNT_REVIEW_SCOPE = {'additional_binding': {},
 'additional_custody': (),
 'candidate_row_hash': '53efc65557c66e9de9a0da294d19c35e152cbb7ed01328df8ca0245e602f3d4c',
 'change_type': 'EXPLICIT_HUMAN_AUTHORIZED_SOURCE_AND_ACCOUNT_AUTHORITY_CHILD',
 'contract_path': 'D:/us-tech-quant-results/_maintenance/V24_A_FROZEN_HISTORY_RESEARCH_ACCOUNT_AND_POLICY_EVALUATION_R1/RESEARCH_ACCOUNT_SCIENTIFIC_CONTRACT.json',
 'contract_sha256': '5803399951d2b76918ca6ff8a718d805804ddb5f8e336c6773f4cce83e88621e',
 'frozen57_path': 'D:/us-tech-quant-results/_maintenance/V24_A_FROZEN_HISTORY_RESEARCH_ACCOUNT_AND_POLICY_EVALUATION_R1/FROZEN_RESEARCH57_CANDIDATES.json',
 'frozen57_sha256': 'dc009c7596b80439eb2cdea8a410c1169213f2242b8a76e2ab55298db023daed',
 'human_premise_field': 'source_premise_unchanged',
 'human_record_filename': 'A_RESEARCH_ACCOUNT_REGISTRY_HUMAN_AUTHORIZATION.json',
 'independent_review_kind': 'INDEPENDENT_A_RESEARCH_ACCOUNT_REGISTRY_REVIEW',
 'nonredundancy_basis': 'EXPOST_EXECUTION_ACCOUNTING_RECONSTRUCTION_AUTHORITY_ONLY',
 'parent_entity_id': 'RAW_A2_HGB_BASELINE',
 'parent_row_hash': 'a3e06a95645a4271b4ace17c1ef3659a5558c9842eb645e106eacb71c0188ea6',
 'parent_status': 'ACTIVE',
 'request_path': 'C:/Users/Lenovo/.codex/attachments/e48ccc4c-a7ba-4b6c-bc73-e4123c2f5930/已粘贴的文本.txt',
 'request_sha256': '149e4158ede7294506c39c075fbc216649a01ea80bf510e7b26e2f284cc8533a',
 'research_id': 'V24_A_FROZEN_HISTORY_RESEARCH_ACCOUNT_AND_POLICY_EVALUATION_R1',
 'resolution_kind': 'EXACT_FROZEN_HISTORY_RESEARCH_ACCOUNT_CHILD',
 'review_record_filename': 'A_RESEARCH_ACCOUNT_REGISTRY_INDEPENDENT_REVIEW.json',
 'scientific_identity': 'FROZEN_HISTORY_RESEARCH_ACCOUNT'}

_A_RESEARCH_QUOTE_DOMAIN_REVIEW_SCOPE = {'additional_binding': {'certified_market_quote_authority': False,
                        'population_sha256': '411b3f0adf19027c1ad513e7f9f7c3a9aef8370de58117990c6355a05fc9427b',
                        'source_general_rule_sha256': 'b16b5e2c3f8aa6cf4a23d75a310d5d50f19008a6cb7c5edb177607db3f851e9a'},
 'additional_custody': [{'maximum_bytes': 65536,
                         'path': 'D:\\us-tech-quant-results\\_maintenance\\V24_A_FROZEN_HISTORY_RESEARCH_QUOTE_DOMAIN_DESCENDANT_R1\\source_population_typed_terminal\\QUOTE_DOMAIN_FREEZE.json',
                         'sha256': 'b16b5e2c3f8aa6cf4a23d75a310d5d50f19008a6cb7c5edb177607db3f851e9a'},
                        {'maximum_bytes': 8817719,
                         'path': 'D:\\us-tech-quant-results\\_maintenance\\V24_A_FROZEN_HISTORY_RESEARCH_QUOTE_DOMAIN_DESCENDANT_R1\\source_population_typed_terminal\\QUOTE_MASK_POPULATION_CENSUS.json',
                         'sha256': '411b3f0adf19027c1ad513e7f9f7c3a9aef8370de58117990c6355a05fc9427b'}],
 'candidate_row_hash': 'f452dd8fd36c8215f11b4d838c9aa9296bcf309e9e495a063a6c4cd03f2546ea',
 'change_type': 'EXPLICIT_HUMAN_AUTHORIZED_SOURCE_AND_ACCOUNT_AUTHORITY_CHILD',
 'contract_path': 'D:\\us-tech-quant-results\\_maintenance\\V24_A_FROZEN_HISTORY_RESEARCH_QUOTE_DOMAIN_DESCENDANT_R1\\RESEARCH_QUOTE_DOMAIN_SCIENTIFIC_CONTRACT.json',
 'contract_sha256': 'd117ea1fade72e3e47bc65b2f4f0a02dc3e22adc8479d21f6394ffeeb2abaa81',
 'frozen57_path': 'D:\\us-tech-quant-results\\_maintenance\\V24_A_FROZEN_HISTORY_RESEARCH_ACCOUNT_AND_POLICY_EVALUATION_R1\\FROZEN_RESEARCH57_CANDIDATES.json',
 'frozen57_sha256': 'dc009c7596b80439eb2cdea8a410c1169213f2242b8a76e2ab55298db023daed',
 'human_premise_field': 'source_premise_matches_frozen_contract',
 'human_record_filename': 'A_RESEARCH_QUOTE_DOMAIN_REGISTRY_HUMAN_AUTHORIZATION.json',
 'independent_review_kind': 'INDEPENDENT_A_RESEARCH_QUOTE_DOMAIN_REGISTRY_REVIEW',
 'nonredundancy_basis': 'EXPOST_FROZEN_HISTORY_RESEARCH_QUOTE_DOMAIN_AUTHORITY_ONLY',
 'parent_entity_id': 'V24_A_FROZEN_HISTORY_RESEARCH_ACCOUNT_AND_POLICY_EVALUATION_R1',
 'parent_row_hash': '787f55a05ea1d64f48d03c5934fa27d1e86a9e4e0701d397334a4c51e796e4ec',
 'parent_status': 'OPEN',
 'request_path': 'D:\\us-tech-quant-results\\_maintenance\\V24_A_FROZEN_HISTORY_RESEARCH_QUOTE_DOMAIN_DESCENDANT_R1\\HUMAN_AUTHORIZATION.json',
 'request_sha256': '9266ac83eea7a8f4aa32c718593fca79cdfdd8e28ce71edf553143a11cd75047',
 'research_id': 'V24_A_FROZEN_HISTORY_RESEARCH_QUOTE_DOMAIN_DESCENDANT_R1',
 'resolution_kind': 'EXACT_FROZEN_HISTORY_RESEARCH_QUOTE_DOMAIN_CHILD',
 'review_record_filename': 'A_RESEARCH_QUOTE_DOMAIN_REGISTRY_INDEPENDENT_REVIEW.json',
 'scientific_identity': 'FROZEN_HISTORY_RESEARCH_QUOTE_DOMAIN'}


_A_SESSION_BOUNDARY_CA_REVIEW_SCOPE = {'additional_binding': {'certified_market_quote_authority': False,
                        'population_sha256': '411b3f0adf19027c1ad513e7f9f7c3a9aef8370de58117990c6355a05fc9427b',
                        'real_effective_clock_proven': False,
                        'research_session_boundary_assumption': True,
                        'session_boundary_population_sha256': '91ae0889d3b0d7a924810c989ad8c16c53c19346180fee40f95658dce574f336',
                        'session_boundary_rule_sha256': '3ad8a1e2e44424e8e563070a5e47a98893f9800eb32e19cdcc3ed950deef78a8',
                        'source_general_rule_sha256': 'b16b5e2c3f8aa6cf4a23d75a310d5d50f19008a6cb7c5edb177607db3f851e9a'},
 'additional_custody': [{'maximum_bytes': 65536,
                         'path': 'D:\\us-tech-quant-results\\_maintenance\\V24_A_FROZEN_HISTORY_RESEARCH_QUOTE_DOMAIN_DESCENDANT_R1\\source_population_typed_terminal\\QUOTE_DOMAIN_FREEZE.json',
                         'sha256': 'b16b5e2c3f8aa6cf4a23d75a310d5d50f19008a6cb7c5edb177607db3f851e9a'},
                        {'maximum_bytes': 8817719,
                         'path': 'D:\\us-tech-quant-results\\_maintenance\\V24_A_FROZEN_HISTORY_RESEARCH_QUOTE_DOMAIN_DESCENDANT_R1\\source_population_typed_terminal\\QUOTE_MASK_POPULATION_CENSUS.json',
                         'sha256': '411b3f0adf19027c1ad513e7f9f7c3a9aef8370de58117990c6355a05fc9427b'},
                        {'maximum_bytes': 65536,
                         'path': 'D:\\us-tech-quant-results\\_maintenance\\V24_A_FROZEN_HISTORY_SESSION_BOUNDARY_CA_ACCOUNTING_R1\\SESSION_BOUNDARY_CA_RULE.json',
                         'sha256': '3ad8a1e2e44424e8e563070a5e47a98893f9800eb32e19cdcc3ed950deef78a8'},
                        {'maximum_bytes': 4813300,
                         'path': 'D:\\us-tech-quant-results\\_maintenance\\V24_A_FROZEN_HISTORY_SESSION_BOUNDARY_CA_ACCOUNTING_R1\\SESSION_BOUNDARY_CA_POPULATION.json',
                         'sha256': '91ae0889d3b0d7a924810c989ad8c16c53c19346180fee40f95658dce574f336'}],
 'candidate_row_hash': 'ffe45528390b56e9bca01a35d79e9246f33bd4bc85907468fe792fac87fefab9',
 'change_type': 'EXPLICIT_HUMAN_AUTHORIZED_SOURCE_AND_ACCOUNT_AUTHORITY_CHILD',
 'contract_path': 'D:\\us-tech-quant-results\\_maintenance\\V24_A_FROZEN_HISTORY_SESSION_BOUNDARY_CA_ACCOUNTING_R1\\SESSION_BOUNDARY_CA_ACCOUNTING_CONTRACT.json',
 'contract_sha256': 'dec3076f9f100c0dbaf1d4cb9ead4980aaa00dfc17a378c52594ea5fb9f190df',
 'frozen57_path': 'D:\\us-tech-quant-results\\_maintenance\\V24_A_FROZEN_HISTORY_RESEARCH_ACCOUNT_AND_POLICY_EVALUATION_R1\\FROZEN_RESEARCH57_CANDIDATES.json',
 'frozen57_sha256': 'dc009c7596b80439eb2cdea8a410c1169213f2242b8a76e2ab55298db023daed',
 'human_premise_field': 'source_premise_matches_frozen_contract',
 'human_record_filename': 'A_SESSION_BOUNDARY_CA_REGISTRY_HUMAN_AUTHORIZATION.json',
 'independent_review_kind': 'INDEPENDENT_A_SESSION_BOUNDARY_CA_REGISTRY_REVIEW',
 'nonredundancy_basis': 'EXPOST_SESSION_PRE_OPEN_CA_ACCOUNTING_CONVENTION_ONLY',
 'parent_entity_id': 'V24_A_FROZEN_HISTORY_RESEARCH_QUOTE_DOMAIN_DESCENDANT_R1',
 'parent_row_hash': '17e3d0f25166af7dd19037eb25483e6f535fea4ee74c7b0b4665e446361a640a',
 'parent_status': 'OPEN',
 'request_path': 'D:\\us-tech-quant-results\\_maintenance\\V24_A_FROZEN_HISTORY_SESSION_BOUNDARY_CA_ACCOUNTING_R1\\HUMAN_AUTHORIZATION.json',
 'request_sha256': '8fa389745f3767092b729f5c6bd0e70ed710a055708db62622f928fa42bf2d87',
 'research_id': 'V24_A_FROZEN_HISTORY_SESSION_BOUNDARY_CA_ACCOUNTING_R1',
 'resolution_kind': 'EXACT_FROZEN_HISTORY_SESSION_BOUNDARY_CA_ACCOUNTING_CHILD',
 'review_record_filename': 'A_SESSION_BOUNDARY_CA_REGISTRY_INDEPENDENT_REVIEW.json',
 'scientific_identity': 'FROZEN_HISTORY_SESSION_BOUNDARY_CA_ACCOUNTING'}



# One exact, human-authorized final consumption child. The manifest is authored
# and physically frozen before outcome access; it grants no fit or source promotion.
_A_FINAL_ACTION_ID = "V24_A_FINAL_ACTION_COVERAGE_AND_STATEFUL_DECISION_R1"
_A_FINAL_ACTION_RESULTS = Path("D:/us-tech-quant-results/_maintenance") / _A_FINAL_ACTION_ID
_A_FINAL_ACTION_MANIFEST = _A_FINAL_ACTION_RESULTS / "A_FINAL_ACTION_COVERAGE_MANIFEST.json"
_A_FINAL_ACTION_REFERENCE_RUN = Path(
    "D:/us-tech-quant-backtests/V24_A_FROZEN_HISTORY_SESSION_BOUNDARY_CA_ACCOUNTING_R1/"
    "20261007T085556+0000_bb17fb09")
_A_FINAL_ACTION_HUMAN_REQUEST = Path(
    "C:/Users/Lenovo/.codex/attachments/839211df-f83a-4d7c-9b8c-ff5ddd159fcf/已粘贴的文本.txt")
_A_FINAL_ACTION_HUMAN_SHA = "44a2c1eead79cb34d33eb16961f60f03264264ca4e9e0a28dc34bcd03ac8743f"
_A_FINAL_ACTION_GATES = (
    "DECISION_INFORMATION_FIREWALL", "EXECUTION_QUOTE_COORDINATE",
    "SECURITY_ACCOUNTING_CONTINUITY", "DOUBLE_ENTRY_ACCOUNTING", "CASH_IDENTITY",
    "CORPORATE_ACTION_AND_ENTITLEMENT", "RECEIVABLE_ACCOUNTING", "NAV_IDENTITY",
    "CONTINUOUS_YEAR_BOUNDARY", "SOURCE_CUSTODY_AND_REPRODUCIBILITY")
_A_FINAL_ACTION_REGISTRY_MECHANISM = {
    "question": "Consume existing frozen A direct/sequence/native action assets in qualified continuous research account; exact original R9 typed input closure",
    "asset_policy": "EARLIEST_COMPLETE_ORIGINAL_IDENTITY_NO_OUTCOME_SELECTION",
    "consumer": "FIXED_ORIGINAL_ORDER_ATOMIC_INCUMBENT_THEN_ENTRY_RESOURCE_REFERENCE_FALLBACK",
    "reference": "RAW_s10", "new_fit": 0,
    "source_authority": "EXACT_SESSION_BOUNDARY_FROZEN_HISTORY_RESEARCH_ONLY",
    "R9_disposition": "NOT_TESTABLE_CAUSAL_INPUT_GROSS_SCHEMA_UNBOUND",
}
_A_FINAL_ACTION_REVIEW_SCOPE = {
    "research_id": _A_FINAL_ACTION_ID,
    "scientific_identity": "FINAL_ACTION_COVERAGE_AND_STATEFUL_DECISION",
    "parent_entity_id": "V24_A_FROZEN_HISTORY_SESSION_BOUNDARY_CA_ACCOUNTING_R1",
    "parent_row_hash": "55160a845a5bc3c500f41285a158dee9e54bfb19671f541e6f640aa158b1f533",
    "parent_status": "OPEN",
    "change_type": "EXPLICIT_HUMAN_AUTHORIZED_EXISTING_ACTION_ACCOUNT_CONSUMPTION",
    "resolution_kind": "EXACT_A_FINAL_ACTION_ACCOUNT_CONSUMPTION_CHILD",
    "human_record_filename": "A_FINAL_ACTION_REGISTRY_HUMAN_AUTHORIZATION.json",
    "review_record_filename": "A_FINAL_ACTION_REGISTRY_INDEPENDENT_REVIEW.json",
    "independent_review_kind": "INDEPENDENT_A_FINAL_ACTION_REGISTRY_REVIEW",
    "human_premise_field": "source_premise_matches_frozen_contract",
    "nonredundancy_basis": "EXACT_EXISTING_DIRECT_SEQUENCE_NATIVE_ACTION_ACCOUNT_CONSUMPTION",
    "frozen57_path": _A_RESEARCH_ACCOUNT_REVIEW_SCOPE["frozen57_path"],
    "frozen57_sha256": _A_RESEARCH_ACCOUNT_REVIEW_SCOPE["frozen57_sha256"],
}


def _a_final_action_physical_ref(reference, *, maximum_bytes=8_388_608):
    """Check task-selected metadata/source custody; never grant generic admission."""
    if not isinstance(reference, Mapping):
        raise RegistryError("A_FINAL_ACTION_PHYSICAL_REFERENCE_REQUIRED")
    path = Path(_string(reference.get("path"), "reference.path"))
    pinned = _require_sha(reference.get("sha256"), "reference.sha256")
    try:
        if (not path.is_absolute() or path.resolve(strict=True) != path.absolute()
                or path.stat().st_size > maximum_bytes or sha256_file(path) != pinned):
            raise RegistryError("A_FINAL_ACTION_PHYSICAL_CUSTODY_MISMATCH")
    except OSError as exc:
        raise RegistryError("A_FINAL_ACTION_PHYSICAL_CUSTODY_UNREADABLE") from exc
    return path, {"path": str(path), "sha256": pinned, "maximum_bytes": maximum_bytes}


def _a_final_action_metadata(reference, *, maximum_bytes=2_097_152):
    path, custody = _a_final_action_physical_ref(reference, maximum_bytes=maximum_bytes)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RegistryError("A_FINAL_ACTION_METADATA_UNREADABLE") from exc
    if not isinstance(payload, dict):
        raise RegistryError("A_FINAL_ACTION_METADATA_OBJECT_REQUIRED")
    return payload, custody


def _a_final_action_audit_projection(path):
    """Reuse the inventory's byte lexer; unselected audit values are skipped."""
    from scripts.maintenance.research_inventory import _RetirementMetadataReader

    class AuditMetadata(_RetirementMetadataReader):
        def _object(self, fields, depth):
            if depth > 128:
                self._fail()
            if fields is None:
                return super()._object(None, depth)
            self._expect(b"{"); self._space()
            result = {}
            if self.next == b"}":
                self._pop(); return result
            while True:
                key = self._string(True)
                self._space(); self._expect(b":"); self._space()
                kind = fields.get(key)
                if kind is None:
                    self._skip(depth + 1)
                    if set(fields) == set(_A_FINAL_ACTION_GATES):
                        result[key] = None  # Preserve unknown gate names; exact ten must fail.
                else:
                    if key in result:
                        self._fail()
                    if isinstance(kind, dict):
                        value = self._object(kind, depth + 1)
                    elif kind == "text":
                        value = self._string(True)
                    elif kind == "terms":
                        value = self._array("terms", depth + 1)
                    else:
                        if self.next not in (b"t", b"f", b"n"):
                            self._fail()
                        token = {b"t": b"true", b"f": b"false", b"n": b"null"}[self.next]
                        for byte in token:
                            self._expect(bytes([byte]))
                        value = {b"true": True, b"false": False, b"null": None}[token]
                    result[key] = value
                self._space()
                if self.next == b"}":
                    self._pop(); return result
                self._expect(b","); self._space()

        def read(self):
            fields = {"candidate_ids": "terms", "namespace": "text",
                "strict_PIT_promotion_eligible": "flag", "production_qualified": "flag",
                "certified_market_quote_authority": "flag",
                "research_integrity": {"RAW_s10": {"groups": {
                    gate: "flag" for gate in _A_FINAL_ACTION_GATES},
                    "all_passed": "flag", "gate_role": "text"}}}
            self._space(); record = self._object(fields, 0); self._space()
            if self.next:
                self._fail()
            return record

    try:
        with path.open("rb") as stream:
            return AuditMetadata(stream).read()
    except (OSError, ValueError, UnicodeError) as exc:
        raise RegistryError("A_FINAL_ACTION_REFERENCE_AUDIT_METADATA_INVALID") from exc



_A_FINAL_ACTION_CENSUS_SHA = "8bfc87f1c7c9a6f9c4122022a16754cee8722b507ef8a9400f8e319ba8b86da9"
_A_FINAL_ACTION_DECLARATION_SOURCE_REF = {
    "path": str(_A_FINAL_ACTION_RESULTS / "SOURCE_AND_CODE_FREEZE.json"),
    "sha256": "ceb23d396c36b667e1218a482a1f032e6b7a14d664e2e297960edef84d3f06e9",
}


_A_FINAL_ACTION_ENGINEERING_MANIFEST_SHA = "eee22010f3239882025b426e87a54f7fb7b7c4506637df218a8cf05942a0df7a"
_A_FINAL_ACTION_ENGINEERING_RUN = _A_FINAL_ACTION_REFERENCE_RUN.parents[1] / _A_FINAL_ACTION_ID / "20261007T122047+0000_d32d75f1"
_A_FINAL_ACTION_ENGINEERING_SCOPE = "EXACT_TWO_SOURCE_CONSUMPTION_AND_REPLAY_QUOTE_PIN_ONLY"
_A_FINAL_ACTION_COMPLETE_ENGINEERING_SCOPE = "EXACT_TWO_SOURCE_AND_COMPLETE_RESEARCH_ENVELOPE_TRANSPORT_ONLY"


def _a_final_action_engineering_custody(reference, manifest):
    """Consume only this task's independently reviewed pre-attempt repair."""
    def exact_ref(value, name):
        if not isinstance(value, Mapping) or Path(str(value.get("path", ""))) != _A_FINAL_ACTION_RESULTS / name:
            raise RegistryError("A_FINAL_ACTION_ENGINEERING_EXACT_PROOF_PATH_REQUIRED")
        return _a_final_action_metadata(value)

    complete = isinstance(reference, Mapping) and Path(str(reference.get("path", ""))) == _A_FINAL_ACTION_RESULTS / "A_FINAL_ACTION_COMPLETE_RUNTIME_SOURCE_CUSTODY.json"
    prefix = "A_FINAL_ACTION_COMPLETE_RUNTIME" if complete else "A_FINAL_ACTION_ENGINEERING"
    scope = _A_FINAL_ACTION_COMPLETE_ENGINEERING_SCOPE if complete else _A_FINAL_ACTION_ENGINEERING_SCOPE
    envelope, _ = exact_ref(reference, prefix + "_SOURCE_CUSTODY.json")
    if any(envelope.get(k) != v for k, v in {
        "schema": "A_FINAL_ACTION_ENGINEERING_SOURCE_CUSTODY_R1", "task_id": _A_FINAL_ACTION_ID,
        "status": "ACCEPTED_ENGINEERING_BEFORE_ACCOUNT_ATTEMPT"}.items()):
        raise RegistryError("A_FINAL_ACTION_ENGINEERING_ACCEPTANCE_REQUIRED")
    receipt, _ = exact_ref(envelope.get("receipt_ref"), prefix + "_TRANSPORT_REPAIR.json")
    review, _ = exact_ref(envelope.get("independent_review_ref"), prefix + "_TRANSPORT_INDEPENDENT_REVIEW.json")
    expected_manifest = {"path": str(_A_FINAL_ACTION_MANIFEST), "sha256": _A_FINAL_ACTION_ENGINEERING_MANIFEST_SHA}
    actual_manifest, _ = _a_final_action_metadata(expected_manifest)
    if canonical_json(actual_manifest) != canonical_json(manifest):
        raise RegistryError("A_FINAL_ACTION_ENGINEERING_IMMUTABLE_MANIFEST_REQUIRED")
    expected = {"schema": "A_FINAL_ACTION_ENGINEERING_TRANSPORT_REPAIR_R1", "task_id": _A_FINAL_ACTION_ID,
        "scientific_identity": _A_FINAL_ACTION_REVIEW_SCOPE["scientific_identity"],
        "scope": scope, "manifest_ref": expected_manifest,
        "new_fit": 0, "new_account_attempts": 0, "strict_PIT_promotion_eligible": False,
        "production_qualified": False, "certified_market_quote_authority": False}
    if any(type(receipt.get(k)) is not type(v) or receipt[k] != v for k, v in expected.items()):
        raise RegistryError("A_FINAL_ACTION_ENGINEERING_EXACT_RECEIPT_REQUIRED")
    run_ref = receipt.get("run_config_ref")
    if not isinstance(run_ref, Mapping) or Path(str(run_ref.get("path", ""))) != _A_FINAL_ACTION_ENGINEERING_RUN / "run_config.json":
        raise RegistryError("A_FINAL_ACTION_ENGINEERING_EXACT_RUN_REQUIRED")
    run_config, _ = _a_final_action_metadata(run_ref)
    if (run_config.get("final_action_namespace") != _A_FINAL_ACTION_ID
            or canonical_json(run_config.get("coverage_manifest_ref")) != canonical_json(expected_manifest)):
        raise RegistryError("A_FINAL_ACTION_ENGINEERING_RUN_MANIFEST_MISMATCH")
    for key in ("source_diff_ref", "synthetic_acceptance_ref"):
        path, _ = _a_final_action_physical_ref(receipt.get(key))
        if not path.is_relative_to(_A_FINAL_ACTION_RESULTS):
            raise RegistryError("A_FINAL_ACTION_ENGINEERING_TASK_EVIDENCE_REQUIRED")
    if (review.get("schema") != "A_FINAL_ACTION_ENGINEERING_TRANSPORT_INDEPENDENT_REVIEW_R1"
            or review.get("task_id") != _A_FINAL_ACTION_ID or review.get("status") != "PASS"
            or review.get("independent") is not True or review.get("scope") != scope
            or not isinstance(review.get("author"), str) or not review["author"].strip()
            or not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip()
            or review["author"] == review["reviewer"]
            or any(canonical_json(review.get(k)) != canonical_json(v) for k, v in {
                "receipt_ref": envelope["receipt_ref"], "manifest_ref": expected_manifest,
                "run_config_ref": run_ref}.items())):
        raise RegistryError("A_FINAL_ACTION_ENGINEERING_INDEPENDENT_REVIEW_REQUIRED")
    updates = receipt.get("source_updates")
    owner = Path(__file__).resolve()
    allowed = {owner, owner.parents[1] / "research/a2/training/stateful_final_action.py"}
    original = {Path(row["path"]): row["sha256"] for row in manifest["source_pins"]}
    if (not isinstance(updates, list) or len(updates) != 2
            or any(not isinstance(row, Mapping) for row in updates)
            or {Path(str(row.get("path", ""))) for row in updates} != allowed):
        raise RegistryError("A_FINAL_ACTION_ENGINEERING_ONLY_TWO_OWNER_SOURCES")
    effective = dict(original)
    for row in updates:
        path = Path(row["path"])
        before_path, before = _a_final_action_physical_ref(row.get("before_ref"))
        if (row.get("before_sha256") != original.get(path) or before["sha256"] != row["before_sha256"]
                or before_path != _A_FINAL_ACTION_RESULTS / "runtime_source_before" / path.name):
            raise RegistryError("A_FINAL_ACTION_ENGINEERING_ORIGINAL_SOURCE_CUSTODY_REQUIRED")
        _, current = _a_final_action_physical_ref({"path": str(path), "sha256": row.get("after_sha256")})
        effective[path] = current["sha256"]
    parent, _ = _a_final_action_metadata(manifest["reference_run_config_ref"])
    old_quote, _ = _a_final_action_metadata(parent["research_account"]["quote_domain_ref"])
    quote, _ = exact_ref(receipt.get("quote_domain_ref"), "FINAL_ACTION_QUOTE_DOMAIN_ENGINEERING_ENVELOPE.json")
    replay_path = owner.parents[1] / "research/a2/training/stateful_replay.py"
    expected_quote = json.loads(canonical_json(old_quote))
    replay_key = str(replay_path)
    if replay_key not in expected_quote.get("source_pins", {}) or replay_path not in original:
        raise RegistryError("A_FINAL_ACTION_ENGINEERING_REPLAY_LINEAGE_REQUIRED")
    expected_quote["source_pins"][replay_key] = original[replay_path]
    _a_final_action_physical_ref({"path": replay_key, "sha256": original[replay_path]})
    if canonical_json(quote) != canonical_json(expected_quote):
        raise RegistryError("A_FINAL_ACTION_ENGINEERING_QUOTE_ONLY_REPLAY_PIN_REQUIRED")
    result = {"effective_source_pins": [{"path": row["path"], "sha256": effective[Path(row["path"])]}
            for row in manifest["source_pins"]], "quote_domain_ref": dict(receipt["quote_domain_ref"]),
        "engineering_run_dir": str(_A_FINAL_ACTION_ENGINEERING_RUN), "engineering_receipt_ref": dict(reference)}
    if complete:
        original_session, _ = _a_final_action_metadata(parent["research_account"]["research_ca_accounting_convention"])
        session, _ = exact_ref(receipt.get("session_convention_ref"), "FINAL_ACTION_SESSION_CA_ENGINEERING_ENVELOPE.json")
        expected_session = json.loads(canonical_json(original_session))
        session_paths = {owner, replay_path, replay_path.with_name("stateful_execution.py")}
        session_pins = expected_session.get("code_pins")
        if (not isinstance(session_pins, dict) or any(str(path) not in session_pins or path not in effective
                for path in session_paths)):
            raise RegistryError("A_FINAL_ACTION_ENGINEERING_SESSION_LINEAGE_REQUIRED")
        for path in session_paths:
            session_pins[str(path)] = effective[path]
        if canonical_json(session) != canonical_json(expected_session):
            raise RegistryError("A_FINAL_ACTION_ENGINEERING_SESSION_ONLY_THREE_CODE_PINS_REQUIRED")
        for path, pinned in session["code_pins"].items():
            _a_final_action_physical_ref({"path": path, "sha256": pinned})
        result["session_convention_ref"] = dict(receipt["session_convention_ref"])
    return result


def validate_a_final_action_manifest_metadata(manifest: Mapping[str, Any], *, engineering_receipt_ref=None) -> dict[str, Any]:
    """Scan all values except physically proved original declaration tokens.

    This task-local projection changes neither the manifest nor the global
    firewall. Original IDs must resolve to exact immutable census members;
    source paths to the prior frozen dependency set; contrast IDs to the
    original ordered same-cost57 contract. Unverified tokens get no exemption.
    """
    if (not isinstance(manifest, Mapping) or manifest.get("task_id") != _A_FINAL_ACTION_ID
            or manifest.get("schema") != "A_FINAL_ACTION_COVERAGE_MANIFEST_R1"):
        raise RegistryError("A_FINAL_ACTION_DECLARATION_TASK_SCOPE_REQUIRED")
    _reject_similarity_controls(manifest)
    engineering = _a_final_action_engineering_custody(engineering_receipt_ref, manifest) if engineering_receipt_ref is not None else None
    effective = {Path(row["path"]): row["sha256"] for row in engineering["effective_source_pins"]} if engineering else {}
    census_ref = manifest.get("census_ref")
    if (not isinstance(census_ref, Mapping)
            or Path(str(census_ref.get("path", ""))) != _A_FINAL_ACTION_RESULTS / "A_EXISTING_ACTION_ASSET_CENSUS.json"
            or census_ref.get("sha256") != _A_FINAL_ACTION_CENSUS_SHA):
        raise RegistryError("A_FINAL_ACTION_EXACT_IMMUTABLE_CENSUS_REQUIRED")
    census, _ = _a_final_action_metadata(census_ref, maximum_bytes=8_388_608)
    if census.get("schema") != "A_EXISTING_ACTION_ASSET_CENSUS_R1" or census.get("task_id") != _A_FINAL_ACTION_ID:
        raise RegistryError("A_FINAL_ACTION_ORIGINAL_CENSUS_SCHEMA_REQUIRED")
    representatives = {row["representative_id"]: row for row in census["representatives"]
        if row["classification"] in {"A_DIRECT_ACTION_COMPATIBLE", "A_SEQUENCE_ACTION_COMPATIBLE"}}
    objects = census["objects"]
    by_slot = {row["slot_id"]: (i, row) for i, row in enumerate(objects)}
    projection = json.loads(canonical_json(manifest))
    ids = []
    if not isinstance(manifest.get("candidates"), list):
        raise RegistryError("A_FINAL_ACTION_ORIGINAL_DECLARED_CANDIDATES_REQUIRED")
    for original, projected in zip(manifest["candidates"], projection["candidates"]):
        if not isinstance(original, Mapping):
            raise RegistryError("A_FINAL_ACTION_ORIGINAL_CANDIDATE_RECORD_REQUIRED")
        identity = original.get("candidate_id")
        if identity not in representatives:
            raise RegistryError("A_FINAL_ACTION_CANDIDATE_NOT_ORIGINAL_CENSUS_REPRESENTATIVE")
        representative = representatives[identity]
        expected_members = []
        for slot in representative["member_slot_ids"]:
            ordinal, member = by_slot[slot]
            if member.get("status") != "TRAINED":
                raise RegistryError("A_FINAL_ACTION_ORIGINAL_MEMBER_NOT_TRAINED")
            expected_members.append({"census_object_ordinal": ordinal, "census_ref": census_ref,
                "original_scientific_identity": member["scientific_identity"],
                "fit_receipt_sha256": member["receipt_ref"]["sha256"],
                "model_sha256": member["model_sha256"],
                "publication_sha256": member["oof_sha256"] if "oof_path" in member else member["publication"]["sha256"],
                "original_fit_tuple_sha256": member.get("scientific_tuple_sha256"),
                "producer_pin_group": member["producer_ref"]})
        members = original.get("original_member_refs")
        if (not isinstance(members, list) or len(members) != len(expected_members)
                or any(not isinstance(actual, Mapping) or not set(expected).issubset(actual)
                    or canonical_json({key: actual.get(key) for key in expected}) != canonical_json(expected)
                    for actual, expected in zip(members, expected_members))):
            raise RegistryError("A_FINAL_ACTION_ORIGINAL_MEMBER_DECLARATION_MISMATCH")
        ids.append(identity)
        projected.pop("candidate_id")
    if len(set(ids)) != len(ids):
        raise RegistryError("A_FINAL_ACTION_DUPLICATE_ORIGINAL_DECLARATION")
    prior, _ = _a_final_action_metadata(_A_FINAL_ACTION_DECLARATION_SOURCE_REF)
    if prior.get("task_id") != _A_FINAL_ACTION_ID or prior.get("status") != "FROZEN_PRE_OUTCOME":
        raise RegistryError("A_FINAL_ACTION_PRIOR_FROZEN_SOURCE_DECLARATION_REQUIRED")
    allowed_sources = {Path(row["path"]) for row in prior["source_pins"]}
    pins = manifest.get("source_pins")
    if not isinstance(pins, list):
        raise RegistryError("A_FINAL_ACTION_PHYSICAL_SOURCE_PINS_REQUIRED")
    paths = []
    for original, projected in zip(pins, projection["source_pins"]):
        pin = {**original, "sha256": effective.get(Path(str(original.get("path", ""))), original.get("sha256"))}
        path, _ = _a_final_action_physical_ref(pin)
        if path not in allowed_sources or path.suffix != ".py":
            raise RegistryError("A_FINAL_ACTION_SOURCE_PATH_NOT_PRIOR_FROZEN_DECLARATION")
        paths.append(path)
        projected.pop("path")
    if len(set(paths)) != len(paths) or set(paths) != allowed_sources:
        raise RegistryError("A_FINAL_ACTION_EXACT_PRIOR_SOURCE_PATH_SET_REQUIRED")
    statistics = manifest.get("statistical_design")
    if statistics is not None:
        if not isinstance(statistics, Mapping):
            raise RegistryError("A_FINAL_ACTION_STATISTICAL_DECLARATION_REQUIRED")
        frozen_ref = {"path": _A_FINAL_ACTION_REVIEW_SCOPE["frozen57_path"],
            "sha256": _A_FINAL_ACTION_REVIEW_SCOPE["frozen57_sha256"]}
        frozen_path, _ = _a_final_action_physical_ref(frozen_ref, maximum_bytes=65_536)
        frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
        rules = [row["candidate_id"] for row in frozen if row["candidate_id"] != "RAW_s10"
            and row["execution_friction"]["one_way_bps"] == 10]
        if statistics.get("rule_reference_ids") != rules:
            raise RegistryError("A_FINAL_ACTION_RULE_REFERENCE_NOT_ORIGINAL_FROZEN_ORDER")
        expected = [(identity, reference, "PRIMARY" if reference == "RAW_s10" else "RULE_REFERENCE")
            for identity in ids for reference in ["RAW_s10", *rules]]
        contrasts = statistics.get("contrasts")
        if (not isinstance(contrasts, list) or any(not isinstance(row, Mapping) for row in contrasts)
                or [(row.get("candidate"), row.get("reference"), row.get("kind")) for row in contrasts] != expected):
            raise RegistryError("A_FINAL_ACTION_CONTRAST_NOT_ORIGINAL_DECLARED_PRODUCT")
        projected_statistics = projection["statistical_design"]
        projected_statistics.pop("rule_reference_ids")
        for row in projected_statistics["contrasts"]:
            row.pop("candidate"); row.pop("reference")
    _reject_outcome_fields(projection)
    return {"status": "PASS", "task_id": _A_FINAL_ACTION_ID,
        "candidate_declarations": len(ids), "physical_source_declarations": len(paths),
        "manifest_modified": False, "generic_firewall_modified": False}


def _a_final_action_review_scope(operation, normalized, entity_map, *, engineering_receipt_ref=None):
    """Derive only this task's exact scope from its frozen physical manifest."""
    base = _A_FINAL_ACTION_REVIEW_SCOPE
    candidate = _candidate(operation["entity"])
    reference = candidate.get("metadata", {}).get("final_action_manifest_ref")
    if not isinstance(reference, Mapping) or Path(str(reference.get("path", ""))) != _A_FINAL_ACTION_MANIFEST:
        raise RegistryError("A_FINAL_ACTION_EXACT_MANIFEST_PATH_REQUIRED")
    manifest, commitment = _a_final_action_metadata(reference)
    validate_a_final_action_manifest_metadata(manifest, engineering_receipt_ref=engineering_receipt_ref)
    engineering = _a_final_action_engineering_custody(engineering_receipt_ref, manifest) if engineering_receipt_ref is not None else None
    effective = {Path(row["path"]): row["sha256"] for row in engineering["effective_source_pins"]} if engineering else {}
    expected = {"schema": "A_FINAL_ACTION_COVERAGE_MANIFEST_R1", "task_id": _A_FINAL_ACTION_ID,
        "status": "FROZEN_PRE_OUTCOME", "phase0_frozen": True, "2026_locked": True,
        "parent_entity_id": base["parent_entity_id"], "reference_candidate_id": "RAW_s10",
        "strict_PIT_promotion_eligible": False, "production_qualified": False,
        "certified_market_quote_authority": False, "test2026": "LOCKED",
        "MKFG_settlement_authority": "UNKNOWN"}
    for key, value in expected.items():
        if type(manifest.get(key)) is not type(value) or manifest[key] != value:
            raise RegistryError("A_FINAL_ACTION_FROZEN_MANIFEST_MISMATCH:" + key)
    for key in ("new_fit_budget", "real_fit_budget"):
        if type(manifest.get(key)) is not int or manifest[key] != 0:
            raise RegistryError("A_FINAL_ACTION_ZERO_NEW_FIT_REQUIRED")
    candidates = manifest.get("candidates")
    count = manifest.get("existing_candidate_count")
    if not isinstance(candidates, list) or type(count) is not int or count != len(candidates) or not 0 <= count <= 37:
        raise RegistryError("A_FINAL_ACTION_EXISTING_CANDIDATE_CAP_OR_COUNT")
    ids, tuples = [], []
    for row in candidates:
        if not isinstance(row, Mapping):
            raise RegistryError("A_FINAL_ACTION_CANDIDATE_RECORD_REQUIRED")
        ids.append(_string(row.get("candidate_id"), "candidate_id"))
        tuples.append(_require_sha(row.get("scientific_tuple_sha256"), "scientific_tuple_sha256"))
    if len(set(ids)) != count or len(set(tuples)) != count or "RAW_s10" in ids:
        raise RegistryError("A_FINAL_ACTION_DUPLICATE_OR_REFERENCE_CANDIDATE")
    ref = manifest.get("reference")
    if (not isinstance(ref, Mapping) or ref.get("candidate_id") != "RAW_s10"
            or not isinstance(ref.get("raw_candidate"), Mapping)
            or ref["raw_candidate"].get("candidate_id") != "RAW_s10"
            or canonical_json(ref.get("audit_ref")) != canonical_json(manifest.get("reference_audit_ref"))
            or canonical_json(ref.get("config_ref")) != canonical_json(manifest.get("reference_run_config_ref"))):
        raise RegistryError("A_FINAL_ACTION_REFERENCE_DECLARATION_MISMATCH")
    custody = []
    for key in ("census_ref", "R9_recovery_ref", "reference_audit_ref", "reference_run_config_ref",
                "source_and_code_freeze_ref", "human_authorization_ref", "independent_review_ref"):
        path, item = _a_final_action_physical_ref(manifest.get(key))
        custody.append(item)
        if key == "reference_audit_ref":
            if path != _A_FINAL_ACTION_REFERENCE_RUN / "ledgers/stateful/attempt_0001/audit.json":
                raise RegistryError("A_FINAL_ACTION_EXACT_QUALIFIED_REFERENCE_AUDIT_REQUIRED")
            audit = _a_final_action_audit_projection(path)
        elif key == "reference_run_config_ref" and path != _A_FINAL_ACTION_REFERENCE_RUN / "run_config.json":
            raise RegistryError("A_FINAL_ACTION_EXACT_QUALIFIED_REFERENCE_CONFIG_REQUIRED")
    gate = audit.get("research_integrity", {}).get("RAW_s10", {})
    groups = gate.get("groups", {})
    if (audit.get("candidate_ids") != ["RAW_s10"]
            or audit.get("namespace") != "FROZEN_HISTORY_SESSION_BOUNDARY_CA_ACCOUNTING"
            or any(audit.get(key) is not False for key in ("strict_PIT_promotion_eligible",
                "production_qualified", "certified_market_quote_authority"))
            or set(groups) != set(_A_FINAL_ACTION_GATES) or any(groups[key] is not True for key in groups)
            or gate.get("all_passed") is not True or gate.get("gate_role") != "RESEARCH_INTEGRITY_ONLY"):
        raise RegistryError("A_FINAL_ACTION_ACTUAL_REFERENCE_TEN_GATES_REQUIRED")
    recovery, _ = _a_final_action_metadata(manifest["R9_recovery_ref"])
    if (Path(manifest["R9_recovery_ref"]["path"]) != _A_FINAL_ACTION_RESULTS / "A_R9_ORIGINAL_RECOVERY_AND_ADMISSION.json"
            or recovery.get("status") != "NOT_TESTABLE_CAUSAL_INPUT"
            or recovery.get("specific_reason") != "R9_GROSS_FEATURE_PROJECTION_UNBOUND_IN_ORIGINAL_CONTRACT"):
        raise RegistryError("A_FINAL_ACTION_ORIGINAL_R9_CAUSAL_GAP_MUST_BE_PRESERVED")
    pins = manifest.get("source_pins")
    if not isinstance(pins, list) or not pins:
        raise RegistryError("A_FINAL_ACTION_PHYSICAL_SOURCE_PINS_REQUIRED")
    source_paths = []
    for pin in pins:
        pin = {**pin, "sha256": effective.get(Path(str(pin.get("path", ""))), pin.get("sha256"))}
        path, item = _a_final_action_physical_ref(pin)
        if path.suffix != ".py":
            raise RegistryError("A_FINAL_ACTION_SOURCE_PIN_MUST_BE_CODE")
        source_paths.append(path); custody.append(item)
    required_sources = {Path(__file__).resolve(), Path(__file__).resolve().with_name("research_inventory.py")}
    if len(set(source_paths)) != len(source_paths) or not required_sources.issubset(set(source_paths)):
        raise RegistryError("A_FINAL_ACTION_OWNER_AND_METADATA_READER_SOURCE_PINS_REQUIRED")
    human_path = Path(manifest["human_authorization_ref"]["path"])
    if human_path != _A_FINAL_ACTION_HUMAN_REQUEST:
        if human_path != _A_FINAL_ACTION_RESULTS / "HUMAN_AUTHORIZATION.json":
            raise RegistryError("A_FINAL_ACTION_EXACT_HUMAN_REQUEST_REQUIRED")
        human, _ = _a_final_action_metadata(manifest["human_authorization_ref"], maximum_bytes=65_536)
        human_ref = human.get("request_ref")
    else:
        human_ref = manifest["human_authorization_ref"]
    request, human_custody = _a_final_action_physical_ref(human_ref, maximum_bytes=65_536)
    if request != _A_FINAL_ACTION_HUMAN_REQUEST or human_custody["sha256"] != _A_FINAL_ACTION_HUMAN_SHA:
        raise RegistryError("A_FINAL_ACTION_EXACT_HUMAN_REQUEST_REQUIRED")
    custody.append(human_custody)
    parent = entity_map.get(base["parent_entity_id"], {})
    spec = {"final_action_manifest_ref": {"path": str(_A_FINAL_ACTION_MANIFEST), "sha256": commitment["sha256"]}}
    if (canonical_json(candidate.get("specification")) != canonical_json(spec)
            or candidate.get("specification_fingerprint") != sha256_value(spec)
            or canonical_json(manifest.get("registry_mechanism")) != canonical_json(_A_FINAL_ACTION_REGISTRY_MECHANISM)
            or canonical_json(candidate.get("mechanism")) != canonical_json(_A_FINAL_ACTION_REGISTRY_MECHANISM)
            or candidate.get("mechanism_fingerprint") != sha256_value(_A_FINAL_ACTION_REGISTRY_MECHANISM)
            or candidate.get("decision_layer") != "STATEFUL_ACTION_CONTINUOUS_RESEARCH_ACCOUNT"
            or candidate.get("information_source_fingerprint") != parent.get("information_source_fingerprint")
            or _information_family(candidate) != _information_family(parent)):
        raise RegistryError("A_FINAL_ACTION_EXACT_SCIENTIFIC_DECLARATION_REQUIRED")
    metadata = normalized["metadata"]
    for key, value in {"scientific_identity": base["scientific_identity"], "fit_authority": False,
        "formal_freeze_authority": False, "source_gate_required": True,
        "strict_PIT_promotion_eligible": False, "production_qualified": False,
        "certified_market_quote_authority": False}.items():
        if type(metadata.get(key)) is not type(value) or metadata[key] != value:
            raise RegistryError("A_FINAL_ACTION_OPEN_METADATA_ONLY_REQUIRED:" + key)
    return {**base, "candidate_row_hash": normalized["row_hash"],
        "contract_path": str(_A_FINAL_ACTION_MANIFEST), "contract_sha256": commitment["sha256"],
        "contract_maximum_bytes": 2_097_152,
        "request_path": str(human_path), "request_sha256": manifest["human_authorization_ref"]["sha256"],
        "additional_custody": custody,
        "additional_binding": {"certified_market_quote_authority": False,
            "real_effective_clock_proven": False, "research_session_boundary_assumption": True,
            "new_fit_budget": 0, "existing_candidate_count": count,
            "reference_candidate_id": "RAW_s10", "test2026": "LOCKED",
            "MKFG_settlement_authority": "UNKNOWN", "manifest_sha256": commitment["sha256"],
            "reference_audit_sha256": manifest["reference_audit_ref"]["sha256"],
            "R9_recovery_sha256": manifest["R9_recovery_ref"]["sha256"]}}



def verify_a_final_action_admission(root: Path | str, *, final_action_manifest_ref: Mapping[str, Any]) -> dict[str, Any]:
    """Recheck canonical OPEN identity and frozen custody before account dispatch."""
    head, _, entities, _ = _load_live_snapshot(Path(root))
    entity_map = {row["entity_id"]: row for row in entities}
    row = entity_map.get(_A_FINAL_ACTION_ID)
    if row is None:
        raise RegistryError("A_FINAL_ACTION_CANONICAL_ADMISSION_MISSING")
    metadata = row["metadata"]
    if (row.get("status") != "OPEN" or row.get("entity_type") != "RESEARCH_BRANCH"
            or row.get("parent_entity_id") != _A_FINAL_ACTION_REVIEW_SCOPE["parent_entity_id"]
            or metadata.get("explicit_review_decision") != "ACCEPT_OPEN_METADATA_ONLY"
            or canonical_json(metadata.get("final_action_manifest_ref")) != canonical_json(final_action_manifest_ref)):
        raise RegistryError("A_FINAL_ACTION_CANONICAL_ADMISSION_MISMATCH")
    before_metadata = {key: value for key, value in metadata.items() if key not in {
        "automatic_preflight_decision", "explicit_review_decision", "human_authorization_ref",
        "human_authorization_sha256", "independent_review_ref", "independent_review_sha256", "engineering_receipt_ref"}}
    raw = {**_entity_without_hash(row), "metadata": before_metadata,
        "specification": metadata.get("specification"), "mechanism": metadata.get("mechanism"), "aliases": []}
    before = _normalize_entity(raw)
    engineering_ref = metadata.get("engineering_receipt_ref")
    scope = _a_final_action_review_scope({"entity": raw}, before, entity_map, engineering_receipt_ref=engineering_ref)
    parent = entity_map.get(scope["parent_entity_id"], {})
    automatic = metadata.get("automatic_preflight_decision", {})
    if (parent.get("status") != scope["parent_status"] or parent.get("row_hash") != scope["parent_row_hash"]
            or automatic.get("decision") != "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE"
            or automatic.get("status") != "REVIEW_REQUIRED"
            or automatic.get("reasons") != ["raw information_source or feature_input_family overlaps existing history"]):
        raise RegistryError("A_FINAL_ACTION_CANONICAL_PARENT_OR_REVIEW_MISMATCH")
    expected = {"research_id": _A_FINAL_ACTION_ID, "scientific_identity": scope["scientific_identity"],
        "registry_head_sha256": automatic.get("registry_head_sha256"),
        "proposal_sha256": automatic.get("proposal_sha256"),
        "candidate_pre_admission_row_hash": before["row_hash"],
        "parent_entity_id": scope["parent_entity_id"], "parent_row_hash": scope["parent_row_hash"],
        "frozen_contract_sha256": scope["contract_sha256"], "strict_PIT_promotion_eligible": False,
        "production_qualified": False, "fit_authority": False, "formal_freeze_authority": False,
        "source_gate_required": True, "prior_artifact_reopened": False, "legacy_exposure_retained": True,
        **scope["additional_binding"]}
    records = []
    for prefix, filename in (("human_authorization", scope["human_record_filename"]),
                             ("independent_review", scope["review_record_filename"])):
        record = _r3_review_record(metadata.get(prefix + "_ref"), metadata.get(prefix + "_sha256"), filename)
        if any(canonical_json(record.get(key)) != canonical_json(value) for key, value in expected.items()):
            raise RegistryError("A_FINAL_ACTION_CANONICAL_REVIEW_REFERENCE_MISMATCH")
        records.append(record)
    human, review = records
    if (human.get("kind") != "HUMAN_AUTHORIZATION_RECORD" or human.get("human_user_authorized") is not True
            or human.get("human_request_sha256") != scope["request_sha256"]
            or Path(str(human.get("human_request_ref", ""))) != Path(scope["request_path"])
            or human.get(scope["human_premise_field"]) is not True
            or review.get("kind") != scope["independent_review_kind"] or review.get("status") != "PASS"
            or review.get("independent") is not True or review.get("scope") != "OPEN_METADATA_ONLY"
            or review.get("human_authorization_sha256") != metadata["human_authorization_sha256"]):
        raise RegistryError("A_FINAL_ACTION_CANONICAL_HUMAN_OR_INDEPENDENT_REVIEW_INVALID")
    engineering = _a_final_action_engineering_custody(engineering_ref, _a_final_action_metadata(final_action_manifest_ref)[0]) if engineering_ref is not None else {}
    return {"status": "PASS", "admission": "OPEN_METADATA_ONLY", "entity_id": _A_FINAL_ACTION_ID,
        "registry_head_sha256": head, "admission_base_head_sha256": automatic["registry_head_sha256"],
        "manifest_sha256": scope["contract_sha256"], "new_fit_budget": 0,
        "strict_PIT_promotion_eligible": False, "production_qualified": False,
        "certified_market_quote_authority": False, "source_gate_required": True, **engineering}


# Exact human-authorized six-combination child; metadata only.
_A_BASE_GROSS_COMBINATION_REVIEW_SCOPE = {'additional_binding': {'new_account_execution_authority': False,
                        'new_training_authority': False,
                        'six_candidate_manifest_sha256': '47832a9280c354890a73ebdc8a21cee6214502374de549c1a2bceca2ef40169b'},
 'additional_custody': [{'maximum_bytes': 65536,
                         'path': 'D:\\us-tech-quant-results\\_maintenance\\A_BASE_CONDITIONED_GROSS_6_COMBINATIONS_20261013_R1\\SIX_COMBINATION_INPUT_MANIFEST.json',
                         'sha256': '47832a9280c354890a73ebdc8a21cee6214502374de549c1a2bceca2ef40169b'},
                        {'maximum_bytes': 65536,
                         'path': 'D:\\us-tech-quant-backtests\\V24_A_STATEFUL_ACTION_RISK_FULL_BREADTH_R10\\20261003T202647+0000_977bc52d\\models\\mechanism\\ACTION_VALUE_ENTRY_HMEAN_2024_elasticnet_MID_20260928\\fit_receipt.json',
                         'sha256': '72a8166a2e4c3712c96781939ef754512f77156152fcb425d716775dc72d868c'},
                        {'maximum_bytes': 65536,
                         'path': 'D:\\us-tech-quant-backtests\\V24_A_STATEFUL_ACTION_RISK_FULL_BREADTH_R10\\20261003T202647+0000_977bc52d\\models\\mechanism\\ACTION_VALUE_INCUMBENT_HMEAN_2024_elasticnet_MID_20260928\\fit_receipt.json',
                         'sha256': '01a6d6d6847ec3e9f3de034a79becd539f3f7a75f277e9f90eeadb7f84b7c0a1'},
                        {'maximum_bytes': 65536,
                         'path': 'D:\\us-tech-quant-backtests\\V24_A_DIRECT_DECISION_LEARNING_PRE2026_R6\\20261003T092432+0000_c8d50146\\FROZEN_SPECIFICATION.json',
                         'sha256': '0ba687ab64abf5ba6abee257d5203b1f6a431d55e31dbdc8ab4cf2d2a5179dd0'}],
 'automatic_reasons': ['existing information source is reused without enough non-redundancy '
                       'evidence'],
 'candidate_row_hash': '94ae1837a24c66fd7a36a63d71e85483d66486acaf7b3f839f5ad3ba12ada110',
 'change_type': 'NEW_ECONOMIC_MECHANISM',
 'contract_path': 'D:\\us-tech-quant-results\\_maintenance\\A_BASE_CONDITIONED_GROSS_6_COMBINATIONS_20261013_R1\\RESEARCH_CONTRACT.json',
 'contract_sha256': '2329b8edb6e03ca387c57d83eb28fff41d0cd9ed7cd1aafe978af1eb38eb23ff',
 'human_premise_field': 'fixed_six_design_authorized',
 'human_record_filename': 'COMBINATION_REGISTRY_HUMAN_AUTHORIZATION.json',
 'independent_review_kind': 'INDEPENDENT_BASE_CONDITIONED_GROSS_REGISTRY_REVIEW',
 'nonredundancy_basis': 'BASE_SPECIFIC_WEIGHTED_TARGET_AND_RETRAINED_GROSS_FIXED_SIX',
 'parent_entity_id': 'V24_A_LEARNED_GROSS_CASH_PRE2026_R7',
 'parent_row_hash': 'b4817cd647cc162684f22217e65b3d511d96baae614971f0259498eb38dbe1a2',
 'parent_status': 'OPEN',
 'request_path': 'D:\\us-tech-quant-results\\_maintenance\\A_BASE_CONDITIONED_GROSS_6_COMBINATIONS_20261013_R1\\HUMAN_AUTHORIZATION.json',
 'request_sha256': 'ea1558979ae7137c6e3504de5de0ccfb03c669f174a54e98c046108e40650861',
 'research_id': 'A_BASE_CONDITIONED_GROSS_6_COMBINATIONS_20261013_R1',
 'resolution_kind': 'EXACT_HUMAN_FIXED_SIX_BASE_CONDITIONED_GROSS',
 'review_record_filename': 'COMBINATION_REGISTRY_INDEPENDENT_REVIEW.json',
 'scientific_identity': 'BASE_CONDITIONED_GROSS_FIXED_SIX'}


def _resolve_a_frozen_research_child_review(operation, patch, normalized, decision, entity_map, head_sha256, *, scope):
    """Admit only exact OPEN child metadata; runtime/account gates remain separate."""
    if (scope is not _A_RESEARCH_ACCOUNT_REVIEW_SCOPE and scope is not _A_RESEARCH_QUOTE_DOMAIN_REVIEW_SCOPE
            and scope is not _A_SESSION_BOUNDARY_CA_REVIEW_SCOPE and scope is not _A_FINAL_ACTION_REVIEW_SCOPE
            and scope is not _CONSENSUS100_REVIEW_SCOPE and scope is not _CONSENSUS100_CONTINUATION_REVIEW_SCOPE
            and scope is not _A_BASE_GROSS_COMBINATION_REVIEW_SCOPE
            and scope is not _CONSENSUS100_COMPARISON_REVIEW_SCOPE):
        raise RegistryError("A_RESEARCH_ACCOUNT_REVIEW_SCOPE_NOT_AUTHORIZED")
    consensus_scope = scope is _CONSENSUS100_REVIEW_SCOPE or scope is _CONSENSUS100_CONTINUATION_REVIEW_SCOPE or scope is _CONSENSUS100_COMPARISON_REVIEW_SCOPE
    if consensus_scope:
        if (decision.get("decision") != "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE"
                or decision.get("matched_entity_ids") != []
                or decision.get("reasons") != ["existing information source is reused without enough non-redundancy evidence"]):
            raise RegistryError("CONSENSUS_REVIEW_EXACT_AUTOMATIC_DECISION_REQUIRED")
        from scripts.maintenance.consensus100_registry_review import validate_scope, validate_continuation_scope, validate_comparison_scope
        validator = (validate_comparison_scope if scope is _CONSENSUS100_COMPARISON_REVIEW_SCOPE else
                     validate_continuation_scope if scope is _CONSENSUS100_CONTINUATION_REVIEW_SCOPE else validate_scope)
        scope = validator(operation, normalized, entity_map)
    if scope is _A_FINAL_ACTION_REVIEW_SCOPE:
        if (decision.get("decision") != "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE"
                or decision.get("reasons") != ["raw information_source or feature_input_family overlaps existing history"]):
            raise RegistryError("A_RESEARCH_ACCOUNT_REVIEW_AUTOMATIC_DECISION_REQUIRED")
        scope = _a_final_action_review_scope(operation, normalized, entity_map)
    resolution = operation.get("review_resolution", {})
    candidate = _candidate(operation["entity"])
    parent = entity_map.get(scope["parent_entity_id"], {})
    if (decision.get("decision") != "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE"
            or decision.get("reasons") != scope.get("automatic_reasons", ["raw information_source or feature_input_family overlaps existing history"])):
        raise RegistryError("A_RESEARCH_ACCOUNT_REVIEW_AUTOMATIC_DECISION_REQUIRED")
    if (candidate["entity_id"] != scope["research_id"]
            or candidate["canonical_name"] != scope["research_id"]
            or candidate["aliases"] or normalized.get("row_hash") != scope["candidate_row_hash"]
            or operation.get("change_type") != scope["change_type"]
            or candidate.get("parent_entity_id") != scope["parent_entity_id"]
            or operation.get("parent_entity_id") != scope["parent_entity_id"]
            or normalized.get("status") != "OPEN" or normalized.get("entity_type") != "RESEARCH_BRANCH"):
        raise RegistryError("A_RESEARCH_ACCOUNT_REVIEW_EXACT_CHILD_REQUIRED")
    if (parent.get("status") != scope["parent_status"]
            or parent.get("row_hash") != scope["parent_row_hash"]
            or _information_family(parent) != _information_family(candidate)):
        raise RegistryError("A_RESEARCH_ACCOUNT_REVIEW_RAW_PARENT_UNCHANGED_REQUIRED")
    if (not isinstance(resolution, Mapping)
            or resolution.get("kind") != scope["resolution_kind"]
            or canonical_json(resolution.get("automatic_decision")) != canonical_json(decision)):
        raise RegistryError("A_RESEARCH_ACCOUNT_REVIEW_EXACT_DECISION_BINDING_REQUIRED")
    author = _string(patch.get("author"), "author")
    reviewer = _review_gate(patch)["reviewer"]
    contract = Path(scope["contract_path"])
    request = Path(scope["request_path"])
    for target, expected in ((contract, scope["contract_sha256"]), (request, scope["request_sha256"])):
        maximum = scope.get("contract_maximum_bytes", 65_536) if target == contract else 65_536
        if target.resolve(strict=True) != target.absolute() or target.stat().st_size > maximum or sha256_file(target) != expected:
            raise RegistryError("A_RESEARCH_ACCOUNT_REVIEW_FROZEN_CUSTODY_REQUIRED")
    if not consensus_scope and scope is not _A_BASE_GROSS_COMBINATION_REVIEW_SCOPE:
        frozen57 = Path(scope["frozen57_path"])
        if (frozen57.resolve(strict=True) != frozen57.absolute() or frozen57.stat().st_size > 65_536
                or sha256_file(frozen57) != scope["frozen57_sha256"]):
            raise RegistryError("A_RESEARCH_ACCOUNT_REVIEW_FROZEN57_CUSTODY_REQUIRED")
    for reference in scope.get("additional_custody", ()):
        target = Path(reference["path"])
        if (target.resolve(strict=True) != target.absolute()
                or target.stat().st_size > reference["maximum_bytes"]
                or sha256_file(target) != reference["sha256"]):
            raise RegistryError("A_RESEARCH_ACCOUNT_REVIEW_ADDITIONAL_FROZEN_CUSTODY_REQUIRED")
    subjects = [{key: value for key, value in row.items() if key != "review_resolution"} for row in patch["operations"]]
    binding = {
        "schema_version": 1, "research_id": scope["research_id"],
        "scientific_identity": scope["scientific_identity"],
        "registry_head_sha256": head_sha256, "proposal_sha256": decision["proposal_sha256"],
        "candidate_pre_admission_row_hash": scope["candidate_row_hash"],
        "review_operations_subject_sha256": sha256_value(subjects),
        "parent_entity_id": scope["parent_entity_id"], "parent_row_hash": parent["row_hash"],
        "frozen_contract_sha256": scope["contract_sha256"],
        "strict_PIT_promotion_eligible": False, "production_qualified": False,
        "fit_authority": False, "formal_freeze_authority": False, "source_gate_required": True,
        "prior_artifact_reopened": False, "legacy_exposure_retained": True,
    }
    binding.update(scope.get("additional_binding", {}))
    human = _r3_review_record(resolution.get("human_authorization_ref"), resolution.get("human_authorization_sha256"),
                              scope["human_record_filename"])
    review = _r3_review_record(resolution.get("independent_review_ref"), resolution.get("independent_review_sha256"),
                               scope["review_record_filename"])
    for record in (human, review):
        for key, expected in binding.items():
            if canonical_json(record.get(key)) != canonical_json(expected):
                raise RegistryError("A_RESEARCH_ACCOUNT_REVIEW_EVIDENCE_BINDING_MISMATCH:" + key)
    if (human.get("kind") != "HUMAN_AUTHORIZATION_RECORD" or human.get("human_user_authorized") is not True
            or human.get("authorization_source") != "CURRENT_HUMAN_REQUEST"
            or human.get("recorded_by") != author or human.get("human_request_sha256") != scope["request_sha256"]
            or Path(str(human.get("human_request_ref", ""))) != request
            or human.get(scope["human_premise_field"]) is not True):
        raise RegistryError("A_RESEARCH_ACCOUNT_REVIEW_HUMAN_AUTHORIZATION_REQUIRED")
    if (review.get("kind") != scope["independent_review_kind"]
            or review.get("status") != "PASS" or review.get("independent") is not True
            or review.get("author") != author or review.get("reviewer") != reviewer
            or review.get("scope") != "OPEN_METADATA_ONLY"
            or review.get("nonredundancy_basis") != scope["nonredundancy_basis"]
            or review.get("human_authorization_sha256") != resolution["human_authorization_sha256"]):
        raise RegistryError("A_RESEARCH_ACCOUNT_REVIEW_INDEPENDENT_REVIEW_REQUIRED")
    normalized["metadata"].update(
        automatic_preflight_decision=dict(decision), explicit_review_decision="ACCEPT_OPEN_METADATA_ONLY",
        human_authorization_ref=resolution["human_authorization_ref"],
        human_authorization_sha256=resolution["human_authorization_sha256"],
        independent_review_ref=resolution["independent_review_ref"],
        independent_review_sha256=resolution["independent_review_sha256"], source_gate_required=True)
    return _normalize_entity(_entity_without_hash(normalized))


def _resolve_a_research_account_review(operation, patch, normalized, decision, entity_map, head_sha256):
    'Preserve original exact account child; no source/fit/account authority.'
    return _resolve_a_frozen_research_child_review(
        operation, patch, normalized, decision, entity_map, head_sha256,
        scope=_A_RESEARCH_ACCOUNT_REVIEW_SCOPE,
    )


def _resolve_r3_review(
    operation: Mapping[str, Any], patch: Mapping[str, Any],
    normalized: dict[str, Any], decision: Mapping[str, Any],
    entity_map: Mapping[str, Mapping[str, Any]], head_sha256: str,
) -> dict[str, Any]:
    """Accept one reviewed OPEN identity; never confer source/freeze/fit authority.

    This is not an automatic proposal PASS or a general review override. All
    automatic BLOCKED decisions remain final for this path. Human authorization
    is an evidence record of the actual user instruction, not a forged signature.
    """
    if str(operation["entity"].get("entity_id", "")) == _CONSENSUS100_COMPARISON_REVIEW_SCOPE["research_id"]:
        return _resolve_a_frozen_research_child_review(
            operation, patch, normalized, decision, entity_map, head_sha256,
            scope=_CONSENSUS100_COMPARISON_REVIEW_SCOPE,
        )
    if str(operation["entity"].get("entity_id", "")) == _A_BASE_GROSS_COMBINATION_REVIEW_SCOPE["research_id"]:
        return _resolve_a_frozen_research_child_review(
            operation, patch, normalized, decision, entity_map, head_sha256,
            scope=_A_BASE_GROSS_COMBINATION_REVIEW_SCOPE,
        )
    if str(operation["entity"].get("entity_id", "")) == _CONSENSUS100_CONTINUATION_REVIEW_SCOPE["research_id"]:
        return _resolve_a_frozen_research_child_review(
            operation, patch, normalized, decision, entity_map, head_sha256,
            scope=_CONSENSUS100_CONTINUATION_REVIEW_SCOPE,
        )
    if str(operation["entity"].get("entity_id", "")) == _CONSENSUS100_REVIEW_SCOPE["research_id"]:
        return _resolve_a_frozen_research_child_review(
            operation, patch, normalized, decision, entity_map, head_sha256,
            scope=_CONSENSUS100_REVIEW_SCOPE,
        )
    if str(operation["entity"].get("entity_id", "")) == _A_FINAL_ACTION_ID:
        return _resolve_a_frozen_research_child_review(
            operation, patch, normalized, decision, entity_map, head_sha256,
            scope=_A_FINAL_ACTION_REVIEW_SCOPE,
        )
    if str(operation["entity"].get("entity_id", "")) == _A_SESSION_BOUNDARY_CA_REVIEW_SCOPE["research_id"]:
        return _resolve_a_frozen_research_child_review(
            operation, patch, normalized, decision, entity_map, head_sha256,
            scope=_A_SESSION_BOUNDARY_CA_REVIEW_SCOPE,
        )
    if str(operation["entity"].get("entity_id", "")) == _A_RESEARCH_QUOTE_DOMAIN_REVIEW_SCOPE["research_id"]:
        return _resolve_a_frozen_research_child_review(
            operation, patch, normalized, decision, entity_map, head_sha256,
            scope=_A_RESEARCH_QUOTE_DOMAIN_REVIEW_SCOPE,
        )
    if str(operation["entity"].get("entity_id", "")) == _A_RESEARCH_ACCOUNT_REVIEW_ID:
        return _resolve_a_research_account_review(operation, patch, normalized, decision, entity_map, head_sha256)
    if str(operation["entity"].get("entity_id", "")) == "V24_B_JOINT_MAXIMAL_BREADTH_PRE2026_R4":
        return _resolve_b_r4_review(operation, patch, normalized, decision, entity_map, head_sha256)
    if str(operation["entity"].get("entity_id", "")) == "V24_B_JOINT_METHOD_SPACE_COMPLETION_PRE2026_R6":
        return _b_r6_resolve_review(operation, patch, normalized, decision, entity_map, head_sha256)
    if str(operation["entity"].get("entity_id", "")) == "V24_B_DYNAMIC_FULLPOOL_RISK_AND_IDENTITY_R5":
        return _resolve_b_r5_review(operation, patch, normalized, decision, entity_map, head_sha256)
    if str(operation["entity"].get("entity_id", "")) in A_DECISION_REVIEW_SCOPES:
        return _resolve_a_decision_review(operation, patch, normalized, decision, entity_map, head_sha256)
    if str(operation["entity"].get("entity_id", "")) == A_BREADTH_REVIEW_ENTITY_ID:
        return _resolve_a_breadth_review(operation, patch, normalized, decision, head_sha256)
    resolution = operation.get("review_resolution")
    if not isinstance(resolution, Mapping):
        raise RegistryError("R3_REVIEW_RESOLUTION_REQUIRED")
    if decision.get("decision") != "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE":
        raise RegistryError(f"PROPOSAL_NOT_APPLYABLE:{decision.get('decision')}")
    allowed_reasons = {
        "existing information source is reused without enough non-redundancy evidence",
        "raw information_source or feature_input_family overlaps existing history",
    }
    if not decision.get("reasons") or not set(decision["reasons"]).issubset(allowed_reasons):
        raise RegistryError("R3_REVIEW_UNSUPPORTED_AUTOMATIC_REASON")
    candidate = _candidate(operation["entity"])
    frozen_history = candidate["entity_id"] == FH_REVIEW_ENTITY_ID
    breadth = candidate["entity_id"] == BREADTH_REVIEW_ENTITY_ID
    mechanism_only = frozen_history or breadth
    identity = (BREADTH_REVIEW_ENTITY_ID if breadth else
                FH_REVIEW_ENTITY_ID if frozen_history else R3_REVIEW_ENTITY_ID)
    specification = (BREADTH_REVIEW_SPECIFICATION if breadth else
                     FH_REVIEW_SPECIFICATION if frozen_history else R3_REVIEW_SPECIFICATION)
    mechanism = (BREADTH_REVIEW_MECHANISM if breadth else
                 FH_REVIEW_MECHANISM if frozen_history else R3_REVIEW_MECHANISM)
    change_type = ("EXPLICIT_HUMAN_SAME_INFORMATION_LEARNER_OBJECTIVE_BREADTH" if breadth else
                   "EXPLICIT_HUMAN_FROZEN_HISTORY_MONTHLY_CADENCE" if frozen_history else
                   "EXPLICIT_HUMAN_NEW_MONTHLY_CADENCE")
    evidence_prefix = "BREADTH" if breadth else "FH" if frozen_history else "R3"
    source_gate = "FROZEN_HISTORY_CONTRACT_AND_FORMAL_FREEZE_REQUIRED" if mechanism_only else "BLOCKED_SOURCE_QUALIFICATION"
    if (candidate["entity_id"] != identity
            or candidate["canonical_name"] != identity
            or candidate["aliases"] or normalized["status"] != "OPEN"
            or normalized["entity_type"] != "RESEARCH_BRANCH"
            or candidate.get("decision_layer") != "PURE_SELECTOR"
            or operation.get("change_type") != change_type):
        raise RegistryError("R3_REVIEW_ENTITY_NOT_AUTHORIZED")
    for field, expected in (("specification", specification),
                            ("mechanism", mechanism)):
        if (canonical_json(candidate.get(field)) != canonical_json(expected)
                or candidate.get(field + "_fingerprint") != sha256_value(expected)):
            raise RegistryError(f"R3_REVIEW_CONTRACT_MISMATCH:{field}")
    parent = entity_map.get(R3_REVIEW_PARENT_ID, {})
    parent_target = parent.get("metadata", {}).get("target_definition")
    if (parent.get("status") != "ACTIVE"
            or candidate.get("parent_entity_id") != R3_REVIEW_PARENT_ID
            or operation.get("parent_entity_id", R3_REVIEW_PARENT_ID) != R3_REVIEW_PARENT_ID
            or parent.get("information_source_fingerprint") != R3_REVIEW_INFORMATION_SHA256
            or candidate.get("information_source_fingerprint") != R3_REVIEW_INFORMATION_SHA256
            or parent_target != "Mean QQQ-relative excess return over 3D 5D 10D and 20D"):
        raise RegistryError("R3_REVIEW_PARENT_SOURCE_TARGET_MISMATCH")
    if breadth:
        prior = entity_map.get(FH_REVIEW_ENTITY_ID, {})
        prior_metadata = prior.get("metadata", {})
        if (prior.get("status") != "CLOSED"
                or prior_metadata.get("scientific_disposition") != "R4_CLOSED_NO_MECHANISM_SUPPORT"
                or prior_metadata.get("fit_authority") is not False
                or prior.get("information_source_fingerprint") != R3_REVIEW_INFORMATION_SHA256
                or prior.get("specification_fingerprint") != sha256_value(FH_REVIEW_SPECIFICATION)
                or prior.get("mechanism_fingerprint") != sha256_value(FH_REVIEW_MECHANISM)
                or canonical_json(prior_metadata.get("specification")) != canonical_json(FH_REVIEW_SPECIFICATION)
                or canonical_json(prior_metadata.get("mechanism")) != canonical_json(FH_REVIEW_MECHANISM)):
            raise RegistryError("BREADTH_REVIEW_PRIOR_R4_CLOSURE_REQUIRED")
    metadata = normalized["metadata"]
    allowed_metadata = {"specification", "mechanism", "information_family",
                        "authoritative_artifact_refs", "scope_metadata_ref", "scope_metadata_sha256",
                        "fit_authority", "formal_freeze_authority", "source_gate"}
    if mechanism_only:
        allowed_metadata.update({"mechanism_research_eligible", "strict_PIT_promotion_eligible"})
    if not set(metadata).issubset(allowed_metadata):
        raise RegistryError("R3_REVIEW_UNSUPPORTED_METADATA")
    if breadth or "scope_metadata_ref" in metadata or "scope_metadata_sha256" in metadata:
        if not isinstance(metadata.get("scope_metadata_ref"), str) or not metadata["scope_metadata_ref"].strip():
            raise RegistryError("R3_REVIEW_SCOPE_REFERENCE_REQUIRED")
        _require_sha(metadata.get("scope_metadata_sha256"), "scope_metadata_sha256")
        if breadth:
            scope_record = _r3_review_record(metadata["scope_metadata_ref"], metadata["scope_metadata_sha256"],
                                             "REGISTRY_SCOPE.json")
            if canonical_json(scope_record) != canonical_json(BREADTH_REVIEW_SCOPE):
                raise RegistryError("BREADTH_REVIEW_SCOPE_CONTRACT_MISMATCH")
    if (metadata.get("fit_authority") is not False
            or metadata.get("formal_freeze_authority") is not False
            or metadata.get("source_gate") != source_gate):
        raise RegistryError("R3_REVIEW_OPEN_METADATA_ONLY_REQUIRED")
    if mechanism_only and (metadata.get("mechanism_research_eligible") is not True
            or metadata.get("strict_PIT_promotion_eligible") is not False):
        raise RegistryError(evidence_prefix + "_REVIEW_MECHANISM_ONLY_REQUIRED")
    expected_kind = ("BREADTH_SAME_INFORMATION_LEARNER_OBJECTIVE" if breadth else
                     "FH_SAME_BYTES_MONTHLY_CADENCE" if frozen_history else "R3_SAME_SOURCE_MONTHLY_CADENCE")
    if (resolution.get("kind") != expected_kind
            or canonical_json(resolution.get("automatic_decision")) != canonical_json(decision)):
        raise RegistryError("R3_REVIEW_AUTOMATIC_DECISION_MISMATCH")
    if not isinstance(patch.get("author"), str) or not patch["author"].strip():
        raise RegistryError("R3_REVIEW_PATCH_AUTHOR_REQUIRED")
    author = _string(patch.get("author"), "author")
    reviewer = _review_gate(patch)["reviewer"]
    subjects = [{key: value for key, value in row.items() if key != "review_resolution"}
                for row in patch["operations"]]
    binding = {
        "schema_version": 1, "research_id": identity,
        "registry_head_sha256": head_sha256, "proposal_sha256": decision["proposal_sha256"],
        "specification_fingerprint": candidate["specification_fingerprint"],
        "mechanism_fingerprint": candidate["mechanism_fingerprint"],
        "information_source_fingerprint": R3_REVIEW_INFORMATION_SHA256,
        "parent_entity_id": R3_REVIEW_PARENT_ID,
        "review_operations_subject_sha256": sha256_value(subjects),
        "constraints_sha256": sha256_value(specification),
        "fit_authority": False, "formal_freeze_authority": False, "source_gate_required": True,
    }
    human = _r3_review_record(resolution.get("human_authorization_ref"),
                              resolution.get("human_authorization_sha256"),
                              evidence_prefix + "_HUMAN_AUTHORIZATION.json")
    review = _r3_review_record(resolution.get("independent_review_ref"),
                               resolution.get("independent_review_sha256"),
                               evidence_prefix + "_INDEPENDENT_REGISTRY_REVIEW.json")
    for record in (human, review):
        for key, expected in binding.items():
            if canonical_json(record.get(key)) != canonical_json(expected):
                raise RegistryError(f"R3_REVIEW_EVIDENCE_BINDING_MISMATCH:{key}")
    if mechanism_only:
        for record in (human, review):
            if (record.get("mechanism_research_eligible") is not True
                    or record.get("strict_PIT_promotion_eligible") is not False
                    or record.get("source_contract_mode") != "FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY"):
                raise RegistryError(evidence_prefix + "_REVIEW_AUTHORITY_PREMISE_REQUIRED")
    if (human.get("kind") != "HUMAN_AUTHORIZATION_RECORD"
            or human.get("human_user_authorized") is not True
            or human.get("authorization_source") != "CURRENT_HUMAN_REQUEST"
            or human.get("recorded_by") != author):
        raise RegistryError("R3_REVIEW_HUMAN_AUTHORIZATION_REQUIRED")
    _require_sha(human.get("human_request_sha256"), "human_request_sha256")
    if (review.get("kind") != "INDEPENDENT_" + evidence_prefix + "_REGISTRY_REVIEW"
            or review.get("status") != "PASS" or review.get("independent") is not True
            or review.get("author") != author or review.get("reviewer") != reviewer
            or review.get("scope") != "OPEN_METADATA_ONLY"
            or review.get("nonredundancy_basis") != ("PREREGISTERED_SELECTION_ALIGNED_OBJECTIVES" if breadth
                                                    else "MONTHLY_VS_ANNUAL_TIMING_WITH_FLAG_ONLY_CONTROL")
            or review.get("prior_artifact_reopened") is not False
            or review.get("legacy_exposure_retained") is not True
            or review.get("human_authorization_sha256") != resolution["human_authorization_sha256"]):
        raise RegistryError("R3_REVIEW_INDEPENDENT_PATCH_REVIEW_REQUIRED")
    metadata.update({
        "automatic_preflight_decision": dict(decision),
        "explicit_review_decision": "ACCEPT_OPEN_METADATA_ONLY",
        "human_authorization_ref": resolution["human_authorization_ref"],
        "human_authorization_sha256": resolution["human_authorization_sha256"],
        "independent_review_ref": resolution["independent_review_ref"],
        "independent_review_sha256": resolution["independent_review_sha256"],
        "source_gate_required": True,
    })
    return _normalize_entity(_entity_without_hash(normalized))






# Exact R6 full-subject admission; other registry paths remain unchanged.
import sys as _b_r6_sys
_b_r6_registry=_b_r6_sys.modules[__name__]
"""UNAPPLIED narrow R6 full-subject decoder; no registry writes or numeric calls.
Candidate code is inserted in the existing canonical registry only after review.
Original full bodies remain intact; typed declarations are exact path/type/value
claims bound to one full frozen subject, not generic outcome guard exceptions.
"""
_b_r6_IDENTITY='V24_B_JOINT_METHOD_SPACE_COMPLETION_PRE2026_R6'
_b_r6_PARENT='V24_B_JOINT_MAXIMAL_BREADTH_PRE2026_R4'
_b_r6_HUMAN_SHA='9a327ad0da2e876931f32ed7bfcd2306cc308ef3df2ffff7c4e95502dfa38ee6'
_b_r6_SOURCE_SHA='4a87deb43b77d67ac0192045b260d442c972aa0dcbefa231c7631cbdac6c8e19'
_b_r6_SOURCE_LITERAL='{"2026_locked": true, "EF_access": false, "R5_cap_preserved": 4096, "R5_numeric_economic_read": false, "R6_draft_authority_predecessor_sha256": "e63f047a5afaad8ea81acb48002e53af0255e2aa289626d08d85286dcd900c1e", "cash_coordinate": "SOURCE_DECLARED_GROSS_RAW_OLD_SECURITY_SHARES", "certified_nav_qualified": false, "conditional_benchmark_proxy_coordinate": "FROZEN_QFQ_PRICE_RETURN_PROXY_NOT_SHAREHOLDER_RAW_OPEN", "evaluation_window": ["2023-01-01", "2026-01-01"], "forecast_output_roles": {"CURRENT_ELIGIBLE_ALPHA_OOF": {"domain": "complete ex-ante legally eligible keys with past-only identity; cannot shrink by outcome", "eligible_for_policy": false, "genuine_annual_oof_years": [2022, 2023, 2024, 2025], "held_coverage_claim": false, "purpose": "opportunity/fusion scientific study, not portfolio qualification"}, "FULL_REQUIRED_ELIGIBLE_PLUS_HELD_POLICY_OOF": {"domain": "all actual required eligible union current-held keys", "no_held_domain_shrinking": true, "one_unknown_blocks_qualified_publication": true, "requirements": ["security_id", "security_id_type", "cusip where required by source identity", "active_13f_quarter", "quarter_universe_fingerprint", "UID", "epoch", "security-class", "past-only source/as-of"]}}, "forecast_scale_semantics": "native raw 5D shareholder-target mu; uncertainty from native posterior/distribution or strictly earlier genuine OOF/probe-heldout RMS; no in-fit residual bridge; no new affine/probability/quantile coverage calibration", "gross_semantics": "fixed grid controller in {0,.25,.5,.75,1}; G_effective=min(G_controller, independent continuous optimizer gross_cap); cap is not a new grid-selection axis", "historical_quote_authority_status": "UNKNOWN", "independent_budget": {"account_mechanism_paths": 120, "deterministic_optimizer_policy_solves": 20000, "estimator_learned_state_fits": 2500, "scientific_retry": 0}, "input_data_copied": false, "mechanism_mark_policy": "CURRENT_FROZEN_RAW_CLOSE_WITH_EXPLICIT_UNCERTIFIED_QUALITY", "network_provider_fetch": false, "no_previous_or_next_mark_replacement": true, "parent_source_authority_ref": "D:\\\\us-tech-quant-backtests\\\\V24\\\\20261003T061818+0000_49b1a578\\\\SOURCE_AUTHORITY.json", "parent_source_authority_sha256": "d3fa7021d66e077b1710bd1da5a0a2c8c81c784942ca6a261b684eccedaffdc8", "publication_vintage_proven": false, "quote_qualified": false, "raw_fill_coordinate": "RAW_FRACTIONAL_SECURITY_SHARES_NEXT_OPEN", "research_id": "V24_B_JOINT_METHOD_SPACE_COMPLETION_PRE2026_R6", "revision_vintage_proven": false, "risk_primary_coordinate": "SHAREHOLDER_OPEN_T_PLUS_1_TO_T_PLUS_6_5_SESSION_RETURN_SUPPORTED_EVENTS_FAIL_CLOSED", "source_inputs_ref": "D:\\\\us-tech-quant-backtests\\\\V24\\\\20261003T061818+0000_49b1a578\\\\FAMILY_SOURCE_INPUTS.json", "source_inputs_sha256": "04d17931c7437f9c7bc1277b33820c52ec2e527a995b0f1c587dc26f5b2c2fd8", "source_limitations": ["LEGACY_QUOTE_AUTHORITY_UNRESOLVED_EF_UNAVAILABLE", "provider historic publication/session/revision/security custody unresolved", "cash vendor precision unresolved; no full-domain accepted coverage claim"], "source_policy": "B_FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY", "source_quality_flags_preserved": true, "strict_PIT_promotion_eligible": false, "tail_auxiliary_covariance": {"EMPIRICAL_CVAR": "POSTERIOR_PREDICTIVE", "EVT": "POSTERIOR_PREDICTIVE", "requirements": "same ordered UID/epoch/source/cutoff; no fabricated tail scenarios or renaming covariance as tail estimator"}, "target_clock_semantics": "monthly first or observed source/UID/epoch/ordered-pool structural change; carry q target otherwise; daily action/Gross; unsupported structural change blocks account rather than creating extra solves", "task_scope": "METHOD_SPACE_COMPLETION_INDEPENDENT_OF_R5_RESULTS", "test2026_reads": 0, "training_exclusive_boundary": "2026-01-01", "unsupported_economic_events": "RETAIN_AND_BLOCK_DEPENDENT_PATH"}'
_b_r6_EXPECTED_SOURCE=json.loads(_b_r6_SOURCE_LITERAL)
_b_r6_FALSE_FIELDS={'quote_qualified','strict_PIT_promotion_eligible','certified_nav_qualified','publication_vintage_proven','revision_vintage_proven','input_data_copied','network_provider_fetch','EF_access','R5_numeric_economic_read'}
_b_r6_ZERO_FIELDS={'test2026_reads'}
_b_r6_INHERITED_SEMANTIC_FIELDS={'risk_primary_coordinate','conditional_benchmark_proxy_coordinate','source_limitations'}
_b_r6_R6_TYPED_PLAN_SEMANTIC_FIELDS={'forecast_output_roles','forecast_scale_semantics'}
_b_r6_SOURCE_PHYSICAL_SHA256='4a87deb43b77d67ac0192045b260d442c972aa0dcbefa231c7631cbdac6c8e19'

def _b_r6__same(value,expected):
 return type(value) is type(expected) and _b_r6_registry.canonical_json(value)==_b_r6_registry.canonical_json(expected)

def _b_r6_source_record(record):
 """Closed complete schema: typed controls/coordinates; generic other fields.
 All expected values, including every source limitation, are checked before
 semantic classification. Nothing is removed from or rewritten in the record.
 """
 expected=_b_r6_EXPECTED_SOURCE
 if not isinstance(record,dict) or set(record)!=set(expected):raise _b_r6_registry.RegistryError('R6_EXACT_COMPLETE_SOURCE_KEYS_REQUIRED')
 for key,want in expected.items():
  if not _b_r6__same(record[key],want):raise _b_r6_registry.RegistryError('R6_SOURCE_TYPE_OR_VALUE_CHANGED:'+key)
 checked=[]
 for key,value in record.items():
  if key in _b_r6_FALSE_FIELDS:
   if type(value) is not bool or value is not False:raise _b_r6_registry.RegistryError('R6_SOURCE_PROMOTION_FORBIDDEN:'+key)
   checked.append(key)
  elif key in _b_r6_ZERO_FIELDS:
   if type(value) is not int or value!=0:raise _b_r6_registry.RegistryError('R6_POST_BOUNDARY_READ_FORBIDDEN:'+key)
   checked.append(key)
  elif key in _b_r6_INHERITED_SEMANTIC_FIELDS or key in _b_r6_R6_TYPED_PLAN_SEMANTIC_FIELDS:
   checked.append(key) # complete exact inherited/typed R6 plan body checked; never clipped
  else:
   _b_r6_registry._reject_outcome_fields({key:value})
 _b_r6_registry._reject_similarity_controls(record)
 return {'original':record,'typed_checked_fields':tuple(sorted(checked)),'all_fields_checked':len(record)}


_b_r6_MAX_JSON_BYTES=32*1024*1024
_b_r6_KINDS={'FALSE_QUALIFICATION_CONTROL','FROZEN_ALGORITHM_PARAMETER','FROZEN_METHOD_ROLE_OR_INPUT_DECLARATION','PHYSICAL_SOURCE_CODE_REFERENCE','FULL_ORIGINAL_HUMAN_INSTRUCTION','FROZEN_METHOD_IDENTIFIER','FROZEN_SOURCE_COORDINATE','FROZEN_SECURITY_IDENTITY_METADATA','ZERO_INFORMATION_READ_COUNTER','ACTIVE_CODE_CUSTODY_HASH_FIELD','FALSE_INFORMATION_READ_ATTESTATION','EMPTY_FORBIDDEN_NUMERIC_PROJECTION','FROZEN_SOURCE_ACCOUNT_SCOPE_DECLARATION','FROZEN_EXECUTION_COST_PARAMETER'}

def _b_r6__full_ref(ref,*,filename=None,read_json=True,max_bytes=_b_r6_MAX_JSON_BYTES):
 if not isinstance(ref,dict) or set(ref)-{'source_ref','sha256','semantic_digest'} or not {'source_ref','sha256'}<=set(ref):raise _b_r6_registry.RegistryError('B_R6_EXACT_REFERENCE_REQUIRED')
 text,digest=ref['source_ref'],ref['sha256']
 if not isinstance(text,str) or not isinstance(digest,str) or not _b_r6_registry.HEX_SHA256.fullmatch(digest):raise _b_r6_registry.RegistryError('B_R6_REFERENCE_TYPE_REQUIRED')
 p=Path(text)
 if p.drive.upper() in {'E:','F:'}:raise _b_r6_registry.RegistryError('B_R6_EF_REFERENCE_FORBIDDEN')
 if not p.is_absolute() or p.resolve(strict=True)!=p.absolute() or filename and p.name!=filename:raise _b_r6_registry.RegistryError('B_R6_EXACT_PHYSICAL_FILENAME_REQUIRED')
 if p.stat().st_size>max_bytes:raise _b_r6_registry.RegistryError('B_R6_FULL_BODY_BOUND_EXCEEDED')
 data=p.read_bytes()
 if hashlib.sha256(data).hexdigest()!=digest:raise _b_r6_registry.RegistryError('B_R6_FULL_BODY_PHYSICAL_SHA_MISMATCH')
 if not read_json:return data
 o=json.loads(data.decode('utf-8-sig'))
 if not isinstance(o,dict):raise _b_r6_registry.RegistryError('B_R6_FULL_JSON_OBJECT_REQUIRED')
 return o

def _b_r6__walk(o,path=''):
 if isinstance(o,dict):
  for k,v in o.items():
   p=f'{path}.{k}' if path else str(k)
   yield p,v
   yield from _b_r6__walk(v,p)
 elif isinstance(o,(list,tuple)):
  for i,v in enumerate(o):
   p=f'{path}[{i}]';yield p,v;yield from _b_r6__walk(v,p)

def _b_r6__findings(o):
 """Same original classifiers; memoization preserves exact field context.
 _string_has_performance_value derives context only from its last field. No
 strings, values or paths are rewritten. All full-source counters are scanned.
 """
 fields=_b_r6_registry._performance_field_paths(o);values=[];memo={}
 for path,value in _b_r6__walk(o):
  if isinstance(value,str):
   field=path.rsplit('.',1)[-1].split('[',1)[0]
   key=(field,value)
   if key not in memo:memo[key]=_b_r6_registry._string_has_performance_value(value,path)
   if memo[key]:values.append(path)
 return dict(fields=fields,values=values,post=_b_r6_registry._nonzero_post_2025_paths(o))

def _b_r6__typed_full(o,declarations,*,record_sha,expected_sha):
 if record_sha!=expected_sha:raise _b_r6_registry.RegistryError('B_R6_EXACT_REVIEWED_FULL_RECORD_REQUIRED')
 if not isinstance(declarations,list):raise _b_r6_registry.RegistryError('B_R6_TYPED_DECLARATIONS_REQUIRED')
 locations=dict(_b_r6__walk(o));seen=set();allowed={'fields':set(),'values':set()}
 for d in declarations:
  if not isinstance(d,dict) or set(d)!={'path','classifier','semantic_kind','expected_type','full_value'}:raise _b_r6_registry.RegistryError('B_R6_DECLARATION_SCHEMA_REQUIRED')
  path=d['path'];classifier=d['classifier'];kind=d['semantic_kind'];value=locations.get(path)
  if classifier not in allowed or kind not in _b_r6_KINDS or (path,classifier) in seen:raise _b_r6_registry.RegistryError('B_R6_DUPLICATE_OR_UNKNOWN_DECLARATION')
  seen.add((path,classifier))
  if path not in locations or type(value).__name__!=d['expected_type'] or _b_r6_registry.canonical_json(value)!=_b_r6_registry.canonical_json(d['full_value']):raise _b_r6_registry.RegistryError('B_R6_DECLARED_FIELD_TYPE_OR_VALUE_MISMATCH:'+path)
  leaf=path.rsplit('.',1)[-1].split('[',1)[0]
  if kind=='FALSE_QUALIFICATION_CONTROL' and (value is not False or leaf not in {'certified_nav_qualified','certified_NAV_qualified','strict_PIT_promotion_eligible','quote_qualified','eligible_for_policy','held_coverage_claim','opportunity_alpha_only_not_policy_authority'}):raise _b_r6_registry.RegistryError('B_R6_QUALIFICATION_PROMOTION_FORBIDDEN')
  if kind=='FROZEN_METHOD_IDENTIFIER' and leaf not in {'node_id','path_id','role','component','family','method','track','phase','cohort','name','output_role','owner_node_id','sensitivity_parent'}:raise _b_r6_registry.RegistryError('B_R6_METHOD_ID_FIELD_REQUIRED')
  if kind=='FROZEN_METHOD_ROLE_OR_INPUT_DECLARATION' and not any(t in path.lower() for t in ('feature','input','recipe','selection','target','role','method','risk','forecast','policy','gross','mechanism','lineage','native','binding','source','support','requirement','output','component','terminal_limits')):raise _b_r6_registry.RegistryError('B_R6_KNOWN_DECLARATIVE_RECIPE_PATH_REQUIRED:'+path)
  if kind=='FROZEN_EXECUTION_COST_PARAMETER' and not path.startswith('cost_assumption.'):raise _b_r6_registry.RegistryError('B_R6_EXACT_COST_PARAMETER_PATH_REQUIRED')
  if kind=='FROZEN_SOURCE_ACCOUNT_SCOPE_DECLARATION' and (path!='scope' or not isinstance(value,str)):raise _b_r6_registry.RegistryError('B_R6_EXACT_SCOPE_DECLARATION_PATH_REQUIRED')
  if kind=='EMPTY_FORBIDDEN_NUMERIC_PROJECTION' and (path!='reads.raw_mu_sigma_y_return_economic_columns' or type(value) is not list or value):raise _b_r6_registry.RegistryError('B_R6_NO_FORBIDDEN_PROJECTION_REQUIRED')
  if kind=='FALSE_INFORMATION_READ_ATTESTATION' and (value is not False or not path.startswith('reads.')):raise _b_r6_registry.RegistryError('B_R6_READ_DENIAL_FLAG_REQUIRED')
  if kind=='ZERO_INFORMATION_READ_COUNTER' and (type(value) is not int or value!=0 or leaf not in {'return_value_reads','numeric_reads','outcome_reads','feature_label_prediction_values_read','new_numeric_feature_label_prediction_reads','real_numeric_values_read'}):raise _b_r6_registry.RegistryError('B_R6_READ_COUNTER_NOT_HARD_ZERO')
  if kind=='FROZEN_SECURITY_IDENTITY_METADATA' and (not isinstance(value,str) or not value.strip() or not any(v in path.lower() for v in ('asset_uid','asset_epoch','security_coordinate','cusip','identity_epoch'))):raise _b_r6_registry.RegistryError('B_R6_TYPED_SECURITY_IDENTITY_PATH_REQUIRED')
  if kind=='ACTIVE_CODE_CUSTODY_HASH_FIELD' and ('source_code_pins.' not in path or not isinstance(value,str) or not _b_r6_registry.HEX_SHA256.fullmatch(value)):raise _b_r6_registry.RegistryError('B_R6_ACTIVE_CODE_HASH_FIELD_REQUIRED')
  if kind=='FROZEN_ALGORITHM_PARAMETER' and not ('.recipes.' in path or '.parameters.' in path or '.specification.' in path or '.primitive_dag.' in path or path.startswith('failure_governance.')):raise _b_r6_registry.RegistryError('B_R6_PARAMETER_OUTSIDE_FROZEN_RECIPE')
  if kind=='PHYSICAL_SOURCE_CODE_REFERENCE' and not (path.endswith('source_ref') or path.endswith('.path')):raise _b_r6_registry.RegistryError('B_R6_CODE_REFERENCE_FIELD_REQUIRED')
  if kind=='FULL_ORIGINAL_HUMAN_INSTRUCTION' and path!='full_text':raise _b_r6_registry.RegistryError('B_R6_FULL_HUMAN_TEXT_PATH_REQUIRED')
  allowed[classifier].add(path)
 findings=_b_r6__findings(o)
 if findings['post']:raise _b_r6_registry.RegistryError('POST_2025_COUNTER_NONZERO:'+str(findings['post'][:5]))
 for classifier in ('fields','values'):
  unknown=set(findings[classifier])-allowed[classifier]
  stale=allowed[classifier]-set(findings[classifier])
  if unknown or stale:raise _b_r6_registry.RegistryError('B_R6_UNDECLARED_OR_STALE_GENERIC_FINDING:'+str(sorted(unknown|stale)[:5]))
 _b_r6_registry._reject_similarity_controls(o)
 return o

def _b_r6_validate_subject(freeze_ref,manifest_ref,*,expected_science_sha,expected_manifest_sha):
 if freeze_ref.get('sha256')!=expected_science_sha or manifest_ref.get('sha256')!=expected_manifest_sha:raise _b_r6_registry.RegistryError('B_R6_EXACT_FULL_SUBJECT_PIN_REQUIRED')
 f=_b_r6__full_ref(freeze_ref,filename='R6_SCIENCE_AND_EXECUTION_FREEZE.json')
 m=_b_r6__full_ref(manifest_ref,filename='B_R6_FULL_SUBJECT_TYPED_DECLARATIONS.json')
 if m.get('schema')!='B_R6_ONE_FULL_SUBJECT_TYPED_DECLARATIONS_V1' or m.get('research_id')!=_b_r6_IDENTITY or m.get('science_ref')!=freeze_ref:raise _b_r6_registry.RegistryError('B_R6_COMPLETE_DECLARATION_SUBJECT_REQUIRED')
 if f.get('schema')!='B_R6_METHOD_SPACE_FULL_PHYSICAL_DAG_V1' or f.get('research_id')!=_b_r6_IDENTITY or f.get('status')!='FROZEN_BEFORE_NUMERIC':raise _b_r6_registry.RegistryError('B_R6_FORMAL_FULL_SCIENCE_REQUIRED')
 if f.get('budget_caps')!=dict(estimator_learned_state_fit=2500,deterministic_optimizer_policy_solve=20000,account_mechanism_paths=120,scientific_retry=0):raise _b_r6_registry.RegistryError('B_R6_EXACT_INDEPENDENT_BUDGET_REQUIRED')
 for k in ('strict_PIT_promotion_eligible','quote_qualified','certified_nav_qualified','R5_numeric_economic_read','policy_provider_ready','full_required_policy_qualified','real_account_admission'):
  if f.get(k) is not False:raise _b_r6_registry.RegistryError('B_R6_NO_AUTHORITY_PROMOTION:'+k)
 for k in ('real_fit_count','real_solve_count','real_account_count','test2026_reads'):
  if type(f.get(k)) is not int or f[k]!=0:raise _b_r6_registry.RegistryError('B_R6_PRE_NUMERIC_BOUNDARY:'+k)
 if f.get('remaining_binding_blockers') or f.get('account_status')!='BLOCKED_ACCOUNT':raise _b_r6_registry.RegistryError('B_R6_BINDING_COMPLETE_ACCOUNT_STILL_BLOCKED_REQUIRED')
 if not m.get('documents') or not m.get('code_references'):raise _b_r6_registry.RegistryError('B_R6_FULL_DOCUMENT_AND_CODE_INVENTORY_REQUIRED')
 docs={}
 for row in m['documents']:
  if set(row)!={'ref','declarations'}:raise _b_r6_registry.RegistryError('B_R6_FULL_DOCUMENT_INVENTORY_ROW_REQUIRED')
  r=row['ref'];o=_b_r6__full_ref(r);_b_r6__typed_full(o,row['declarations'],record_sha=r['sha256'],expected_sha=r['sha256']);docs[r['source_ref']]=o
 if docs.get(freeze_ref['source_ref'])!=f:raise _b_r6_registry.RegistryError('B_R6_SCIENCE_FULL_BODY_NOT_VALIDATED')
 code={}
 repo=Path('D:/us-tech-quant').resolve(strict=True)
 for r in m['code_references']:
  p=Path(r['source_ref'])
  if p.suffix!='.py' or not p.is_relative_to(repo):raise _b_r6_registry.RegistryError('B_R6_REPO_CODE_REFERENCE_REQUIRED')
  data=_b_r6__full_ref(r,read_json=False);code[r['source_ref']]=r['sha256']
 if code!={r['source_ref']:r['sha256'] for r in f['source_code_pins']}:raise _b_r6_registry.RegistryError('B_R6_FULL_ACTIVE_CODE_CLOSURE_REQUIRED')
 for k,v in f.items():
  if k.endswith('_ref') and isinstance(v,dict) and v.get('source_ref','').endswith('.json'):
   if v['source_ref'] not in docs:raise _b_r6_registry.RegistryError('B_R6_FULL_REFERENCED_JSON_NOT_VALIDATED:'+k)
 a=docs[f['source_authority_ref']['source_ref']]
 _b_r6_source_record(a)
 if f['source_authority_ref']['sha256']!=_b_r6_SOURCE_SHA or a.get('research_id')!=_b_r6_IDENTITY or a.get('test2026_reads')!=0 or a.get('EF_access') is not False or a.get('network_provider_fetch') is not False:raise _b_r6_registry.RegistryError('B_R6_EXACT_UNCERTIFIED_SOURCE_REQUIRED')
 human=docs[f['human_scope_ref']['source_ref']]
 raw=_b_r6__full_ref(f['full_human_attachment_ref'],read_json=False)
 if f['full_human_attachment_ref']['sha256']!=_b_r6_HUMAN_SHA or human.get('full_text')!=raw.decode('utf-8-sig') or human.get('attachment_ref')!=f['full_human_attachment_ref'] or human.get('not_synopsis') is not True:raise _b_r6_registry.RegistryError('B_R6_FULL_ORIGINAL_HUMAN_BYTES_REQUIRED')
 dag=docs[f['full_physical_dag_ref']['source_ref']];proof=docs[f['budget_proof_ref']['source_ref']]
 counts=dag.get('node_counts')
 if counts!=dict(estimator_components=2273,whole_solve_upper=19310,accounts=114) or proof.get('fits')!=2273 or proof.get('policy_solves_upper')!=19310:raise _b_r6_registry.RegistryError('B_R6_COMPLETE_PHYSICAL_COUNTS_REQUIRED')
 nodes=dag.get('estimator_fit_nodes',[]);ids={n['node_id'] for n in nodes}
 if len(nodes)!=2273 or len(ids)!=2273 or sum(n.get('units',0) for n in nodes)!=2273:raise _b_r6_registry.RegistryError('B_R6_FIT_NODE_UNION_REQUIRED')
 for n in nodes:
  if set(n.get('dependencies',[]))-ids:raise _b_r6_registry.RegistryError('B_R6_FIT_DEPENDENCY_MISSING')
 seen=set();pending=set();lookup={n['node_id']:n for n in nodes}
 def visit(k):
  if k in pending:raise _b_r6_registry.RegistryError('B_R6_PHYSICAL_DAG_CYCLE')
  if k in seen:return
  pending.add(k)
  for dep in lookup[k].get('dependencies',[]):visit(dep)
  pending.remove(k);seen.add(k)
 for k in lookup:visit(k)
 if dag.get('RL_admitted_fit_nodes')!=[]:raise _b_r6_registry.RegistryError('B_R6_RL_NOT_ADMITTED')
 if len(dag.get('optimizer_policy_solve_nodes',[]))!=19310 or len(dag.get('account_nodes',[]))!=114 or any(n.get('status')!='BLOCKED_ACCOUNT' for n in dag['account_nodes']):raise _b_r6_registry.RegistryError('B_R6_ACCOUNT_NO_AUTHORITY_REQUIRED')
 status=docs[f['policy_provider_status_ref']['source_ref']]
 if status.get('schema')!='B_R6_POLICY_PROVIDER_UNAVAILABLE_V1' or status.get('status')!='BLOCKED_ACCOUNT' or status.get('provider_ready') is not False or status.get('real_account_admission') is not False or status.get('full_required_support',{}).get('rows')!=1052972 or status.get('full_required_support',{}).get('blocked')!=522897 or status.get('unqualified_keys_removed')!=0:raise _b_r6_registry.RegistryError('B_R6_ACTUAL_FULL_REQUIRED_DOMAIN_BLOCK_RETAINED')
 return f,m

# Resolver candidate appended after full-subject physical pins are final. It must
# admit OPEN metadata only; unchanged automatic BLOCK and _review_gate precede it.

# These two pins are bound only after the actual full formal subject is built.
_b_r6_EXPECTED_SCIENCE_SHA='124aaf3efea9c465c0024590452fcea93d7aba599ccb447142e65792def5535a'
_b_r6_EXPECTED_MANIFEST_SHA='59a054da02326e6986f62983cbddfee1651f93f09ef595447f02c437d35fddf1'
_b_r6_EXPECTED_SPECIFICATION={'research_id': 'V24_B_JOINT_METHOD_SPACE_COMPLETION_PRE2026_R6', 'scientific_freeze_sha256': '124aaf3efea9c465c0024590452fcea93d7aba599ccb447142e65792def5535a', 'independent_method_space': 'FIXED_FULL_COMPONENT_DAG_AND_NONREDUNDANT_POLICY_INTERACTIONS', 'budget_caps': {'estimator_learned_state_fit': 2500, 'deterministic_optimizer_policy_solve': 20000, 'account_mechanism_paths': 120, 'scientific_retry': 0}, 'pre2026_frozen_history_only': True, 'test_locked': True, 'legacy_exposure_retained': True}
_b_r6_EXPECTED_MECHANISM={'family': 'b-independent-method-space-sequence-bayesian-fusion-risk-q-action-gross', 'role': 'joint-portfolio-policy', 'question': 'Finite full method space with explicit source-dependent conditional nodes and actual physical-component accounting', 'nonredundancy': 'sequence-and-bayesian-opportunity-plus-finite-fusion-risk-optimizer-action-gross-interactions-typed-full-held-source-qualification', 'source': 'same-existing-frozen-history-no-new-information-or-strict-promotion', 'no_R5_numeric_economic_dependency': True}

def _b_r6_resolve_review(operation,patch,normalized,decision,entity_map,head_sha256):
 candidate=_b_r6_registry._candidate(operation['entity']);resolution=operation.get('review_resolution',{});parent=entity_map.get(_b_r6_PARENT,{})
 allowed={'authoritative source/contract reference overlaps existing history','existing information source is reused without enough non-redundancy evidence','raw information_source or feature_input_family overlaps existing history'}
 if decision.get('decision')!='REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE' or not decision.get('reasons') or not set(decision['reasons'])<=allowed:raise _b_r6_registry.RegistryError('B_R6_AUTOMATIC_BLOCK_IS_FINAL')
 if candidate.get('entity_id')!=_b_r6_IDENTITY or candidate.get('canonical_name')!=_b_r6_IDENTITY or candidate.get('aliases') or normalized.get('status')!='OPEN' or normalized.get('entity_type')!='RESEARCH_BRANCH' or candidate.get('decision_layer')!='joint-portfolio-policy' or candidate.get('parent_entity_id')!=_b_r6_PARENT or operation.get('parent_entity_id')!=_b_r6_PARENT or operation.get('change_type')!='NEW_ECONOMIC_MECHANISM' or parent.get('status') not in {'OPEN','ACTIVE'}:raise _b_r6_registry.RegistryError('B_R6_EXACT_INDEPENDENT_OPEN_IDENTITY_REQUIRED')
 if candidate.get('information_source_fingerprint')!=parent.get('information_source_fingerprint') or candidate.get('mechanism_fingerprint')==parent.get('mechanism_fingerprint'):raise _b_r6_registry.RegistryError('B_R6_SAME_INFORMATION_DISTINCT_MECHANISM_REQUIRED')
 for field in ('specification','mechanism'):
  if candidate.get(field+'_fingerprint')!=_b_r6_registry.sha256_value(candidate.get(field)):raise _b_r6_registry.RegistryError('B_R6_EXACT_SCIENCE_FINGERPRINT_REQUIRED:'+field)
 if _b_r6_registry.canonical_json(candidate.get('specification'))!=_b_r6_registry.canonical_json(_b_r6_EXPECTED_SPECIFICATION) or _b_r6_registry.canonical_json(candidate.get('mechanism'))!=_b_r6_registry.canonical_json(_b_r6_EXPECTED_MECHANISM):raise _b_r6_registry.RegistryError('B_R6_EXACT_TYPED_SCIENTIFIC_IDENTITY_REQUIRED')
 meta=normalized['metadata']
 for flag in ('fit_authority','formal_freeze_authority','strict_PIT_promotion_eligible'):
  if meta.get(flag) is not False:raise _b_r6_registry.RegistryError('B_R6_METADATA_ADMISSION_NOT_NUMERIC_AUTHORITY')
 fref=dict(source_ref=meta.get('science_freeze_ref'),sha256=meta.get('science_freeze_sha256'));mref=dict(source_ref=meta.get('typed_declarations_ref'),sha256=meta.get('typed_declarations_sha256'))
 f,m=_b_r6_validate_subject(fref,mref,expected_science_sha=_b_r6_EXPECTED_SCIENCE_SHA,expected_manifest_sha=_b_r6_EXPECTED_MANIFEST_SHA)
 if meta.get('source_authority_ref')!=f['source_authority_ref']['source_ref'] or meta.get('source_authority_sha256')!=_b_r6_SOURCE_SHA or candidate.get('source_contract_ref')!=meta['source_authority_ref'] or candidate['specification'].get('scientific_freeze_sha256')!=_b_r6_EXPECTED_SCIENCE_SHA:raise _b_r6_registry.RegistryError('B_R6_CANDIDATE_COMPLETE_SUBJECT_BINDING_REQUIRED')
 if resolution.get('kind')!='B_R6_SAME_SOURCE_METHOD_SPACE_COMPLETION' or _b_r6_registry.canonical_json(resolution.get('automatic_decision'))!=_b_r6_registry.canonical_json(decision):raise _b_r6_registry.RegistryError('B_R6_AUTOMATIC_REVIEW_EXACT_BINDING_REQUIRED')
 author=_b_r6_registry._string(patch.get('author'),'author');reviewer=_b_r6_registry._review_gate(patch)['reviewer']
 subjects=[{k:v for k,v in row.items() if k!='review_resolution'} for row in patch['operations']]
 binding=dict(schema_version=1,research_id=_b_r6_IDENTITY,parent_entity_id=_b_r6_PARENT,registry_head_sha256=head_sha256,proposal_sha256=decision['proposal_sha256'],specification_fingerprint=candidate['specification_fingerprint'],mechanism_fingerprint=candidate['mechanism_fingerprint'],information_source_fingerprint=parent['information_source_fingerprint'],review_operations_subject_sha256=_b_r6_registry.sha256_value(subjects),fit_authority=False,formal_freeze_authority=False,strict_PIT_promotion_eligible=False,source_contract_mode='FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY',science_freeze_sha256=_b_r6_EXPECTED_SCIENCE_SHA,source_authority_sha256=_b_r6_SOURCE_SHA,typed_declarations_sha256=_b_r6_EXPECTED_MANIFEST_SHA,full_human_request_sha256=_b_r6_HUMAN_SHA,prior_artifact_reopened=False,R5_numeric_economic_read=False)
 human=_b_r6_registry._r3_review_record(resolution.get('human_authorization_ref'),resolution.get('human_authorization_sha256'),'B_R6_HUMAN_AUTHORIZATION.json')
 review=_b_r6_registry._r3_review_record(resolution.get('independent_review_ref'),resolution.get('independent_review_sha256'),'B_R6_INDEPENDENT_REGISTRY_REVIEW.json')
 for o in (human,review):
  for k,v in binding.items():
   if _b_r6_registry.canonical_json(o.get(k))!=_b_r6_registry.canonical_json(v):raise _b_r6_registry.RegistryError('B_R6_FULL_EVIDENCE_BINDING_MISMATCH:'+k)
 if human.get('kind')!='HUMAN_AUTHORIZATION_RECORD' or human.get('human_user_authorized') is not True or human.get('authorization_source')!='CURRENT_HUMAN_REQUEST' or human.get('recorded_by')!=author or human.get('human_request_sha256')!=_b_r6_HUMAN_SHA:raise _b_r6_registry.RegistryError('B_R6_ACTUAL_COMPLETE_HUMAN_REQUEST_REQUIRED')
 if review.get('kind')!='INDEPENDENT_B_R6_REGISTRY_REVIEW' or review.get('status')!='PASS' or review.get('independent') is not True or review.get('author')!=author or review.get('reviewer')!=reviewer or review.get('scope')!='OPEN_METADATA_ONLY' or review.get('nonredundancy_basis')!='INDEPENDENT_FULL_METHOD_SPACE_PHYSICAL_DAG' or review.get('legacy_exposure_retained') is not True or review.get('human_authorization_sha256')!=resolution['human_authorization_sha256']:raise _b_r6_registry.RegistryError('B_R6_INDEPENDENT_FULL_SUBJECT_REVIEW_REQUIRED')
 meta.update(automatic_preflight_decision=dict(decision),explicit_review_decision='ACCEPT_OPEN_METADATA_ONLY',human_authorization_ref=resolution['human_authorization_ref'],human_authorization_sha256=resolution['human_authorization_sha256'],independent_review_ref=resolution['independent_review_ref'],independent_review_sha256=resolution['independent_review_sha256'],source_gate_required=True)
 return _b_r6_registry._normalize_entity(_b_r6_registry._entity_without_hash(normalized))


def _resolve_b_r4_review(operation, patch, normalized, decision, entity_map, head_sha256):
    """One same-input B R4 admission; source/freeze/fit gates remain separate."""
    identity = "V24_B_JOINT_MAXIMAL_BREADTH_PRE2026_R4"
    parent_id = "V24_B_JOINT_FROZEN_HISTORY_RISK_R3"
    resolution = operation.get("review_resolution", {})
    parent = entity_map.get(parent_id, {})
    candidate = _candidate(operation["entity"])
    allowed = {"authoritative source/contract reference overlaps existing history",
        "existing information source is reused without enough non-redundancy evidence",
        "raw information_source or feature_input_family overlaps existing history"}
    if (decision.get("decision") != "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE"
        or not decision.get("reasons") or not set(decision["reasons"]).issubset(allowed)):
        raise RegistryError("B_R4_REVIEW_AUTOMATIC_REASON_NOT_SUPPORTED")
    if (candidate.get("entity_id") != identity or candidate.get("canonical_name") != identity
        or candidate.get("aliases") or normalized.get("status") != "OPEN"
        or normalized.get("entity_type") != "RESEARCH_BRANCH"
        or candidate.get("decision_layer") != "joint-portfolio-policy"
        or candidate.get("parent_entity_id") != parent_id
        or operation.get("change_type") != "NEW_ECONOMIC_MECHANISM"
        or parent.get("status") not in {"OPEN", "ACTIVE"}):
        raise RegistryError("B_R4_REVIEW_ENTITY_SCOPE_REQUIRED")
    parent_metadata = parent.get("metadata", {})
    if (candidate.get("information_source_fingerprint") != parent.get("information_source_fingerprint")
        or candidate.get("source_contract_ref") != parent_metadata.get("source_contract_ref")
        or candidate.get("information_source") != parent_metadata.get("information_source", parent_metadata.get("information_family"))):
        raise RegistryError("B_R4_REVIEW_SAME_SOURCE_REQUIRED")
    if (candidate.get("mechanism_fingerprint") == parent.get("mechanism_fingerprint")
        or candidate.get("specification_fingerprint") != "773cfcfdadfeea5559fed1f98b8e368fe3150c74da8b2755814799b136252f57"
        or candidate.get("mechanism_fingerprint") != "e187c3c6210bafc188236bb5835730ed633950a08ca20a3bb499ebb10b636aba"):
        raise RegistryError("B_R4_DISTINCT_EXACT_MECHANISM_REQUIRED")
    for field in ("specification", "mechanism"):
        if candidate.get(field+"_fingerprint") != sha256_value(candidate.get(field)):
            raise RegistryError("B_R4_REVIEW_SCIENCE_HASH_REQUIRED")
    metadata = normalized["metadata"]
    if (metadata.get("fit_authority") is not False
        or metadata.get("formal_freeze_authority") is not False
        or metadata.get("strict_PIT_promotion_eligible") is not False):
        raise RegistryError("B_R4_REVIEW_METADATA_ONLY_REQUIRED")
    if (resolution.get("kind") != "B_R4_SAME_SOURCE_NATIVE_BREADTH_AND_SHORT_HISTORY"
        or canonical_json(resolution.get("automatic_decision")) != canonical_json(decision)):
        raise RegistryError("B_R4_REVIEW_AUTOMATIC_BINDING_REQUIRED")
    author = _string(patch.get("author"), "author")
    reviewer = _review_gate(patch)["reviewer"]
    subjects = [{k:v for k,v in row.items() if k != "review_resolution"} for row in patch["operations"]]
    binding = dict(schema_version=1, research_id=identity, parent_entity_id=parent_id,
        registry_head_sha256=head_sha256, proposal_sha256=decision["proposal_sha256"],
        specification_fingerprint=candidate["specification_fingerprint"],
        mechanism_fingerprint=candidate["mechanism_fingerprint"],
        information_source_fingerprint=parent["information_source_fingerprint"],
        review_operations_subject_sha256=sha256_value(subjects),
        fit_authority=False, formal_freeze_authority=False,
        source_contract_mode="FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY",
        strict_PIT_promotion_eligible=False, prior_artifact_reopened=False)
    human = _r3_review_record(resolution.get("human_authorization_ref"), resolution.get("human_authorization_sha256"), "B_R4_HUMAN_AUTHORIZATION.json")
    review = _r3_review_record(resolution.get("independent_review_ref"), resolution.get("independent_review_sha256"), "B_R4_INDEPENDENT_REGISTRY_REVIEW.json")
    for record in (human, review):
        for key,value in binding.items():
            if canonical_json(record.get(key)) != canonical_json(value):
                raise RegistryError("B_R4_REVIEW_EVIDENCE_BINDING_MISMATCH:"+key)
    if (human.get("kind") != "HUMAN_AUTHORIZATION_RECORD"
        or human.get("human_user_authorized") is not True
        or human.get("authorization_source") != "CURRENT_HUMAN_REQUEST"
        or human.get("recorded_by") != author):
        raise RegistryError("B_R4_REVIEW_DIRECT_B_AUTHORIZATION_REQUIRED")
    _require_sha(human.get("human_request_sha256"), "human_request_sha256")
    if (review.get("kind") != "INDEPENDENT_B_R4_REGISTRY_REVIEW"
        or review.get("status") != "PASS" or review.get("independent") is not True
        or review.get("author") != author or review.get("reviewer") != reviewer
        or review.get("scope") != "OPEN_METADATA_ONLY"
        or review.get("nonredundancy_basis") != "NATIVE_GENUINE_OOF_CAPACITY_AND_SHORT_HISTORY_RISK"
        or review.get("legacy_exposure_retained") is not True
        or review.get("human_authorization_sha256") != resolution["human_authorization_sha256"]):
        raise RegistryError("B_R4_INDEPENDENT_EXACT_REVIEW_REQUIRED")
    metadata.update(automatic_preflight_decision=dict(decision),
        explicit_review_decision="ACCEPT_OPEN_METADATA_ONLY",
        human_authorization_ref=resolution["human_authorization_ref"],
        human_authorization_sha256=resolution["human_authorization_sha256"],
        independent_review_ref=resolution["independent_review_ref"],
        independent_review_sha256=resolution["independent_review_sha256"], source_gate_required=True)
    return _normalize_entity(_entity_without_hash(normalized))


# Narrow R5 source schema only. This does not change the generic reader/firewall.
_B_R5_SOURCE_TYPES = {
    'research_id': str,
    'source_policy': str,
    'historical_quote_authority_status': str,
    'quote_qualified': bool,
    'strict_PIT_promotion_eligible': bool,
    'certified_nav_qualified': bool,
    'publication_vintage_proven': bool,
    'revision_vintage_proven': bool,
    'training_exclusive_boundary': str,
    'evaluation_window': list,
    'test2026_reads': int,
    'input_data_copied': bool,
    'raw_fill_coordinate': str,
    'mechanism_mark_policy': str,
    'no_previous_or_next_mark_replacement': bool,
    'source_quality_flags_preserved': bool,
    'cash_coordinate': str,
    'source_limitations': list,
    'risk_primary_coordinate': str,
    'conditional_benchmark_proxy_coordinate': str,
    'unsupported_economic_events': str,
    'network_provider_fetch': bool,
    'EF_access': bool,
    'parent_source_authority': dict,
    'authorisation': str,
    '2026_locked': bool,
    'legacy_provenance_closed': bool,
    'source_qualified_for_mechanism': str,
    'created_timestamp_role': str,
    'source_inputs_ref': dict,
    'actual_snapshot_timestamp': str,
    'snapshot_timestamp_semantic': str,
    'snapshot_timestamp_reference': str,
    'current_identity_clock': str,
    'risk_history_clock': str,
    'risk_refresh_clock': str,
    'new_known_uid_prior': str,
    'price_semantics_unchanged': bool,
    'mechanism_not_strict_PIT': bool,
}
_B_R5_SOURCE_FLAGS = {'quote_qualified': False, 'strict_PIT_promotion_eligible': False, 'certified_nav_qualified': False, 'publication_vintage_proven': False, 'revision_vintage_proven': False, 'input_data_copied': False, 'no_previous_or_next_mark_replacement': True, 'source_quality_flags_preserved': True, 'network_provider_fetch': False, 'EF_access': False, '2026_locked': True, 'legacy_provenance_closed': True, 'price_semantics_unchanged': True, 'mechanism_not_strict_PIT': True}
_B_R5_SOURCE_CONSTANTS = {'research_id': 'V24_B_DYNAMIC_FULLPOOL_RISK_AND_IDENTITY_R5', 'source_policy': 'B_FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY', 'historical_quote_authority_status': 'UNKNOWN', 'training_exclusive_boundary': '2026-01-01', 'evaluation_window': ['2023-01-03', '2026-01-01'], 'raw_fill_coordinate': 'RAW_FRACTIONAL_SECURITY_SHARES_NEXT_OPEN', 'mechanism_mark_policy': 'CURRENT_FROZEN_RAW_CLOSE_WITH_EXPLICIT_UNCERTIFIED_QUALITY', 'cash_coordinate': 'SOURCE_DECLARED_GROSS_RAW_OLD_SECURITY_SHARES', 'source_limitations': ['LEGACY_QUOTE_AUTHORITY_UNRESOLVED_EF_UNAVAILABLE', 'provider historic publication/session/revision/security custody unresolved', 'cash vendor precision unresolved; no full-domain accepted coverage claim'], 'risk_primary_coordinate': 'SHAREHOLDER_OPEN_T_PLUS_1_TO_T_PLUS_6_5_SESSION_RETURN_SUPPORTED_EVENTS_FAIL_CLOSED', 'conditional_benchmark_proxy_coordinate': 'FROZEN_QFQ_PRICE_RETURN_PROXY_NOT_SHAREHOLDER_RAW_OPEN', 'unsupported_economic_events': 'RETAIN_AND_BLOCK_DEPENDENT_PATH', 'parent_source_authority': {'path': 'D:\\us-tech-quant-backtests\\V24\\20261003T181407+0000_ddb7b537\\SOURCE_AUTHORITY.json', 'sha256': 'f2fbe46b6a70d533ce2fbceecc51a7550e16260c31b62e49b803a0fdd1b9007c'}, 'authorisation': 'Current typed human R5 event-driven full-pool risk and held identity task; inherited human-authorised B frozen-history mechanism scope; no C authority inherited', 'source_qualified_for_mechanism': 'Exact frozen bytes/coordinate/UID/maturity qualification only; historical publication/revision/session/custody remain UNKNOWN', 'created_timestamp_role': 'ADMINISTRATIVE_ONLY_NOT_HISTORICAL_AVAILABLE_AT', 'source_inputs_ref': {'path': 'D:\\us-tech-quant-backtests\\V24\\20261003T061818+0000_49b1a578\\FAMILY_SOURCE_INPUTS.json', 'sha256': '04d17931c7437f9c7bc1277b33820c52ec2e527a995b0f1c587dc26f5b2c2fd8'}, 'actual_snapshot_timestamp': '2026-10-03T07:00:00.758297+00:00', 'snapshot_timestamp_semantic': 'Inherited R3 physical frozen-history snapshot timestamp; not historical quote available_at', 'snapshot_timestamp_reference': 'D:\\us-tech-quant-backtests\\V24\\20261003T061818+0000_49b1a578\\FAMILY_DESIGN_FREEZE.json', 'current_identity_clock': 'Decision current legal Close; no prior-close substitution of current UID', 'risk_history_clock': 'Strictly matured and available before previous legal session Close; current UID contiguous segment only', 'risk_refresh_clock': 'Event-driven structural support identity; new scientific identity, not legacy cadence equivalence', 'new_known_uid_prior': 'Planned explicit R5 prior-predictive descendant for known UID N<10; fitted hierarchical donor priors use only prior-cutoff supported history; no observations fabricated; unknown UID/source still blocks'}



def _b_r5_no_reparse_before_resolve(path: Path) -> None:
    """Inspect D ancestors root-first, before following any link or junction."""
    if not path.is_absolute() or path.drive.upper() != 'D:':
        raise RegistryError('B_R5_D_ONLY_REFERENCE_REQUIRED_BEFORE_IO')
    try:
        for parent in reversed((path, *path.parents)):
            info = parent.stat(follow_symlinks=False)
            if getattr(info, 'st_file_attributes', 0) & 0x400:
                raise RegistryError('B_R5_REPARSE_REFERENCE_FORBIDDEN_BEFORE_RESOLVE')
    except OSError as exc:
        raise RegistryError('B_R5_SOURCE_CUSTODY_PATH_UNREADABLE') from exc

def _b_r5_source_record(reference: Any, digest: Any) -> dict[str, Any]:
    """Read full, exact R5 source metadata; never an outcome/compact fallback."""
    filename = "SOURCE_AUTHORITY.json"
    path = Path(_string(reference, filename))
    if path.drive.upper() in {"E:", "F:"}:
        raise RegistryError("B_R5_EF_REFERENCE_FORBIDDEN_BEFORE_IO")
    pinned = _require_sha(digest, filename + ".sha256")
    if not path.is_absolute() or path.name != filename:
        raise RegistryError("B_R5_SOURCE_REFERENCE_INVALID")
    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise RegistryError("B_R5_SOURCE_DUPLICATE_KEY")
            value[key] = item
        return value
    _b_r5_no_reparse_before_resolve(path)
    try:
        if path.resolve(strict=True) != path.absolute() or path.stat().st_size > 65_536:
            raise RegistryError("B_R5_SOURCE_REFERENCE_UNSAFE")
        data = path.read_bytes()
        if len(data) > 65_536 or hashlib.sha256(data).hexdigest() != pinned:
            raise RegistryError("B_R5_SOURCE_SHA256_MISMATCH")
        record = json.loads(data.decode("utf-8"), object_pairs_hook=unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RegistryError("B_R5_SOURCE_UNREADABLE") from exc
    if not isinstance(record, dict) or set(record) != set(_B_R5_SOURCE_TYPES):
        raise RegistryError("B_R5_EXACT_SOURCE_SCHEMA_REQUIRED")
    for key, expected_type in _B_R5_SOURCE_TYPES.items():
        if type(record[key]) is not expected_type or (expected_type is str and not record[key].strip()):
            raise RegistryError("B_R5_SOURCE_FIELD_TYPE_REQUIRED:" + key)
    for key, expected in _B_R5_SOURCE_FLAGS.items():
        if record[key] is not expected:
            raise RegistryError("B_R5_SOURCE_FLAG_REQUIRED:" + key)
    if type(record["test2026_reads"]) is not int or record["test2026_reads"] != 0:
        raise RegistryError("B_R5_SOURCE_PRE2026_ZERO_COUNTER_REQUIRED")
    for key, expected in _B_R5_SOURCE_CONSTANTS.items():
        if canonical_json(record[key]) != canonical_json(expected):
            raise RegistryError("B_R5_SOURCE_LITERAL_REQUIRED:" + key)
    for key in ("parent_source_authority", "source_inputs_ref"):
        ref = record[key]
        if (set(ref) != {"path", "sha256"} or not isinstance(ref["path"], str)
                or not Path(ref["path"]).is_absolute()):
            raise RegistryError("B_R5_SOURCE_CUSTODY_REFERENCE_REQUIRED:" + key)
        _require_sha(ref["sha256"], key + ".sha256")
    # These four descriptors were validated above, including exact false and
    # exact literal text. No arbitrary outcome field/value is removed. The
    # returned ORIGINAL full object retains all descriptors and source flags.
    screen = dict(record)
    screen.pop("certified_nav_qualified")
    screen.pop("risk_primary_coordinate")
    screen.pop("conditional_benchmark_proxy_coordinate")
    screen["source_limitations"] = record["source_limitations"][:2]
    _reject_outcome_fields(screen)
    _reject_similarity_controls(record)
    return record


# Exact existing English SOURCE-ONLY synopsis; not verbatim human text or a
# digest of the full Chinese request. Unknown/changed clauses require new review.
_B_R5_HUMAN_SCOPE = {'document_kind': 'SOURCE_ONLY_HUMAN_SCOPE_EXCERPTS', 'full_human_message_digest_claimed': False, 'authority': 'CURRENT_TYPED_HUMAN_R5_REQUEST', 'task_id': 'V24_B_DYNAMIC_FULLPOOL_RISK_AND_IDENTITY_R5', 'excerpts': ['Dynamic Full-Pool Risk Refresh: EXACT REUSE when ordered asset set, UID/epoch unchanged, maturity/source still valid; NEW RISK REFRESH on asset entry/exit, UID, epoch, security-coordinate or source-support change. No returns, NAV or model performance trigger.', 'Current-held OOF Identity Completion is independent; required security_id, security_id_type, cusip, active_13f_quarter, quarter_universe_fingerprint. No UNKNOWN, future identity or held-domain shrinking.', 'Shared primitive only fit once at actual scientific state changes; unique support epoch x applicable risk family, not blind daily refits.', 'Continuous consumable full-risk-state chain from 2023-01-03 through 2025-12-31 is primary objective.', 'Preserve parent 30 risk-linked main, 12 risk sensitivity, 12 interaction contrasts and 4 SHR anchor paths as explicit descendants.', 'No expanded opportunity learner, boosting, transformer variants, seeds or epochs.'], 'risk_families': ['LW', 'OAS', 'EWMA', 'CONSTANT_CORRELATION', 'PCA_FACTOR', 'QQQ_RESIDUAL', 'FF48_HIERARCHICAL', 'DOWNSIDE_SEMIVARIANCE', 'TAIL_CVAR', 'REGIME_COVARIANCE', 'UNCERTAINTY_JACKKNIFE', 'DISAGREEMENT_ENSEMBLE', 'SHR_HP', 'SHR_EB', 'SHR_CC', 'SHR_FACTOR'], 'inherited_constraints': ['PRE2026_ONLY', 'NO_EF_ACCESS', 'NO_PROVIDER_FETCH', 'NO_2026_READ', 'STRICT_PIT_PROMOTION_INELIGIBLE', 'NO_LEGACY_QUOTE_INVESTIGATION'], 'budget': {'prior_cumulative': 3027, 'cumulative_cap': 4096, 'maximum_new': 1069, 'planning_not_spend_target': True}}


def _b_r5_scope_record(reference: Any, digest: Any) -> dict[str, Any]:
    filename = "HUMAN_SCOPE_EXCERPTS.json"
    path = Path(_string(reference, filename))
    if path.drive.upper() in {"E:", "F:"}:
        raise RegistryError("B_R5_EF_REFERENCE_FORBIDDEN_BEFORE_IO")
    pinned = _require_sha(digest, filename + ".sha256")
    if not path.is_absolute() or path.name != filename:
        raise RegistryError("B_R5_SCOPE_REFERENCE_INVALID")
    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise RegistryError("B_R5_SCOPE_DUPLICATE_KEY")
            value[key] = item
        return value
    _b_r5_no_reparse_before_resolve(path)
    try:
        if path.resolve(strict=True) != path.absolute() or path.stat().st_size > 65_536:
            raise RegistryError("B_R5_SCOPE_REFERENCE_UNSAFE")
        data = path.read_bytes()
        if len(data) > 65_536 or hashlib.sha256(data).hexdigest() != pinned:
            raise RegistryError("B_R5_SCOPE_SHA256_MISMATCH")
        record = json.loads(data.decode("utf-8"), object_pairs_hook=unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RegistryError("B_R5_SCOPE_UNREADABLE") from exc
    if not isinstance(record, dict) or set(record) != set(_B_R5_HUMAN_SCOPE):
        raise RegistryError("B_R5_EXACT_SCOPE_SCHEMA_REQUIRED")
    for key, expected in _B_R5_HUMAN_SCOPE.items():
        if type(record[key]) is not type(expected) or canonical_json(record[key]) != canonical_json(expected):
            raise RegistryError("B_R5_FULL_SCOPE_LITERAL_REQUIRED:" + key)
    # Every full clause and all scope contents were matched, not replaced by
    # compact counts/pins. Only the known synopsis text leaves the generic scan
    # COPY; original full evidence and its physical digest remain unchanged.
    screen = dict(record)
    screen.pop("excerpts")
    _reject_outcome_fields(screen)
    _reject_similarity_controls(record)
    return record



# Only fixed R5 physical source-code references leave a COPY of the full scan.
# All original science fields remain present, checked and returned unchanged.
_B_R5_SCIENCE_KEYS = frozenset(('schema','research_id','status','source_authority_ref','plan_ref','qualification_ref','human_scope_ref','support_ref','parent_policy_ref','risk_families','continuous_families','maximum_new_fit_units','prior_cumulative_fit_units','cumulative_fit_cap','opportunity_expansion','numeric_reads_before_freeze','new_fits_before_freeze','accounts_before_freeze','test2026_reads','provider_fetches','EF_accesses','identity_completion_required_for_dependent_consumers','execution_boundary','scientific_identity','reuse_policy','wholefreeze_role','method_and_trigger_authority','source_code_pins'))
_B_R5_CODE_PATHS = ('scripts/common/storage_paths.py', 'scripts/research/a2/data/joint_event_risk_support_r5.py', 'scripts/research/a2/data/joint_held_identity_completion_r5.py', 'scripts/research/a2/data/shared_risk_inputs_r3.py', 'scripts/research/a2/evaluation/continuous_research_account.py', 'scripts/research/a2/evaluation/joint_control_sensitivity_r4.py', 'scripts/research/a2/evaluation/joint_event_account_dispatch_r5.py', 'scripts/research/a2/evaluation/joint_event_risk_execution_r5.py', 'scripts/research/a2/evaluation/joint_frozen_history_r3.py', 'scripts/research/a2/evaluation/joint_frozen_history_risk_r3.py', 'scripts/research/a2/evaluation/joint_method_accounts.py', 'scripts/research/a2/evaluation/joint_r5_runtime.py', 'scripts/research/a2/evaluation/joint_short_risk_execution_r4.py', 'scripts/research/a2/inference/joint_event_policy_r5.py', 'scripts/research/a2/inference/joint_event_risk_chain_r5.py', 'scripts/research/a2/inference/joint_frozen_history_policy_r3.py', 'scripts/research/a2/inference/joint_portfolio_policy.py', 'scripts/research/a2/inference/joint_stateful_policy.py', 'scripts/research/a2/portfolio/joint_allocation_methods.py', 'scripts/research/a2/portfolio/shared_joint_adapter_r2.py', 'scripts/research/a2/retained/a2_pto_full_compat_20260928_r2/fast_account.py', 'scripts/research/a2/risk/event_risk_contract_r5.py', 'scripts/research/a2/risk/joint_event_risk_estimators_r5.py', 'scripts/research/a2/risk/joint_risk_estimators.py', 'scripts/research/a2/risk/shared_risk_budget_r2.py', 'scripts/research/a2/risk/shared_risk_engine_r2.py', 'scripts/research/a2/risk/shared_risk_extensions_r2.py', 'scripts/research/a2/risk/short_history_risk_r4.py', 'scripts/v22/corporate_action_transition_r1.py')
_B_R5_SCIENCE_LITERALS = {
    'schema': 'B_R5_SCIENCE_AND_EXECUTION_FREEZE_V1',
    'research_id': 'V24_B_DYNAMIC_FULLPOOL_RISK_AND_IDENTITY_R5',
    'status': 'FROZEN_BEFORE_NUMERIC',
    'maximum_new_fit_units': 1056, 'prior_cumulative_fit_units': 3027,
    'cumulative_fit_cap': 4096, 'opportunity_expansion': False,
    'numeric_reads_before_freeze': 0, 'new_fits_before_freeze': 0,
    'accounts_before_freeze': 0, 'test2026_reads': 0, 'provider_fetches': 0,
    'EF_accesses': 0, 'identity_completion_required_for_dependent_consumers': True,
    'execution_boundary': 'PRE2026_ONLY; current legal Close identity; prior legal Close strictly matured history; known same UID epoch only',
    'scientific_identity': 'EXPLICIT_EVENT_FULLPOOL_AND_CONDITIONAL_PRIOR_COMPLETION_CHILD',
    'reuse_policy': 'EXACT_ORDERED_SUPPORT_UID_EPOCH_COORDINATE_SOURCE_NO_CHANGE_REUSE',
    'wholefreeze_role': 'IMMUTABLE_PRE_NUMERIC_SPECIFICATION_ONLY; separate accepted registry binding required before numerical execution',
    'method_and_trigger_authority': 'Complete pinned finite plan remains authoritative; all method bindings, structural and forbidden refresh predicates are verified by its physical content identity',
}

def _b_r5_science_record(reference: Any, digest: Any) -> dict[str, Any]:
    filename = 'R5_SCIENCE_AND_EXECUTION_FREEZE.json'
    path = Path(_string(reference, filename))
    if path.drive.upper() in {"E:", "F:"}:
        raise RegistryError("B_R5_EF_REFERENCE_FORBIDDEN_BEFORE_IO")
    pinned = _require_sha(digest, filename + ".sha256")
    if not path.is_absolute() or path.name != filename:
        raise RegistryError('B_R5_SCIENCE_REFERENCE_INVALID')
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise RegistryError('B_R5_SCIENCE_DUPLICATE_KEY')
            result[key] = value
        return result
    _b_r5_no_reparse_before_resolve(path)
    try:
        if path.resolve(strict=True) != path.absolute() or path.stat().st_size > 65536:
            raise RegistryError('B_R5_SCIENCE_REFERENCE_UNSAFE')
        blob = path.read_bytes()
        if len(blob) > 65536 or hashlib.sha256(blob).hexdigest() != pinned:
            raise RegistryError('B_R5_SCIENCE_SHA256_MISMATCH')
        record = json.loads(blob.decode('utf-8'), object_pairs_hook=unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RegistryError('B_R5_SCIENCE_UNREADABLE') from exc
    return _b_r5_validate_science(record)

def _b_r5_validate_science(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict) or set(record) != _B_R5_SCIENCE_KEYS:
        raise RegistryError('B_R5_FULL_SCIENCE_SCHEMA_REQUIRED')
    for key, expected in _B_R5_SCIENCE_LITERALS.items():
        if type(record[key]) is not type(expected) or canonical_json(record[key]) != canonical_json(expected):
            raise RegistryError('B_R5_FULL_SCIENCE_LITERAL_REQUIRED:' + key)
    if record['risk_families'] != _B_R5_HUMAN_SCOPE['risk_families']:
        raise RegistryError('B_R5_FULL_FROZEN_FAMILY_ROSTER_REQUIRED')
    if (type(record['continuous_families']) is not list
            or len(record['continuous_families']) != 7
            or len(set(record['continuous_families'])) != 7
            or set(record['continuous_families']) != {'LW','OAS','EWMA','PCA_FACTOR','QQQ_RESIDUAL','SHR_HP','SHR_CC'}):
        raise RegistryError('B_R5_FULL_CONTINUOUS_FAMILY_ROSTER_REQUIRED')
    for key in ('source_authority_ref','plan_ref','qualification_ref','human_scope_ref','support_ref','parent_policy_ref'):
        ref = record[key]
        if (type(ref) is not dict or set(ref) != {'path','sha256'}
                or type(ref['path']) is not str or not Path(ref['path']).is_absolute()):
            raise RegistryError('B_R5_FULL_SCIENCE_REFERENCE_REQUIRED:' + key)
        _require_sha(ref['sha256'], key + '.sha256')
    refs = record['source_code_pins']
    if type(refs) is not list or len(refs) != len(_B_R5_CODE_PATHS):
        raise RegistryError('B_R5_COMPLETE_CODE_CLOSURE_REQUIRED')
    root = Path(__file__).resolve().parents[2]
    required = {(root / relative).absolute() for relative in _B_R5_CODE_PATHS}
    actual = set()
    screened = []
    for ref in refs:
        if type(ref) is not dict or set(ref) != {'path','sha256'} or type(ref['path']) is not str:
            raise RegistryError('B_R5_CODE_CUSTODY_SCHEMA_REQUIRED')
        source = Path(ref['path'])
        if source.drive.upper() in {'E:', 'F:'}:
            raise RegistryError('B_R5_EF_REFERENCE_FORBIDDEN_BEFORE_IO')
        if source.absolute() not in required:
            raise RegistryError('B_R5_EXACT_CODE_CUSTODY_PATH_REQUIRED')
        _b_r5_no_reparse_before_resolve(source)
        pin = _require_sha(ref['sha256'], 'source_code_pins.sha256')
        if (not source.is_absolute() or source.resolve(strict=True) != source.absolute()
                or source.resolve() not in required or source.resolve() in actual):
            raise RegistryError('B_R5_EXACT_CODE_CUSTODY_PATH_REQUIRED')
        with source.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != pin:
                raise RegistryError('B_R5_PHYSICAL_CODE_CUSTODY_HASH_REQUIRED')
        actual.add(source.resolve())
        screened.append({'path':'VALIDATED_R5_PHYSICAL_CODE_REFERENCE','sha256':pin})
    if actual != required:
        raise RegistryError('B_R5_COMPLETE_EXACT_CODE_CLOSURE_REQUIRED')
    screen = dict(record)
    screen['source_code_pins'] = screened
    _reject_outcome_fields(screen)
    _reject_similarity_controls(record)
    return record

def _resolve_b_r5_review(operation, patch, normalized, decision, entity_map, head_sha256):
    """Admit only this human-scoped R5 OPEN record; no numeric/source promotion.

    Same-source automatic REVIEW remains visible. Automatic BLOCKED is final.
    Physical frozen scope, source contract and two independent evidence records
    bind this one event-driven experiment; legacy entities remain unchanged.
    """
    identity = "V24_B_DYNAMIC_FULLPOOL_RISK_AND_IDENTITY_R5"
    parent_id = "V24_B_JOINT_MAXIMAL_BREADTH_PRE2026_R4"
    candidate, resolution = _candidate(operation["entity"]), operation.get("review_resolution", {})
    parent = entity_map.get(parent_id, {})
    allowed = {"authoritative source/contract reference overlaps existing history",
               "existing information source is reused without enough non-redundancy evidence",
               "raw information_source or feature_input_family overlaps existing history"}
    if (decision.get("decision") != "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE"
            or not decision.get("reasons") or not set(decision["reasons"]).issubset(allowed)):
        raise RegistryError("B_R5_AUTOMATIC_BLOCK_CANNOT_BE_OVERRIDDEN")
    if (candidate.get("entity_id") != identity or candidate.get("canonical_name") != identity
            or candidate.get("aliases") or normalized.get("status") != "OPEN"
            or normalized.get("entity_type") != "RESEARCH_BRANCH"
            or candidate.get("decision_layer") != "joint-portfolio-policy"
            or candidate.get("parent_entity_id") != parent_id
            or operation.get("parent_entity_id") != parent_id
            or operation.get("change_type") != "EXPLICIT_HUMAN_B_EVENT_FULLPOOL_RISK_AND_IDENTITY"
            or parent.get("status") not in {"OPEN", "ACTIVE"}
            or candidate.get("information_source_fingerprint") != parent.get("information_source_fingerprint")):
        raise RegistryError("B_R5_EXACT_OPEN_SAME_SOURCE_SCOPE_REQUIRED")
    for field in ("specification", "mechanism"):
        if candidate.get(field+"_fingerprint") != sha256_value(candidate.get(field)):
            raise RegistryError("B_R5_SCIENCE_HASH_REQUIRED:" + field)
    metadata = normalized["metadata"]
    if (metadata.get("fit_authority") is not False or metadata.get("formal_freeze_authority") is not False
            or metadata.get("strict_PIT_promotion_eligible") is not False):
        raise RegistryError("B_R5_METADATA_ONLY_NO_AUTHORITY_REQUIRED")
    for value in (metadata.get("event_science_freeze_ref"), metadata.get("event_source_authority_ref"),
                  metadata.get("human_scope_excerpt_ref"), resolution.get("human_authorization_ref"),
                  resolution.get("independent_review_ref")):
        if isinstance(value, str) and Path(value).drive.upper() in {"E:", "F:"}:
            raise RegistryError("B_R5_EF_REFERENCE_FORBIDDEN_BEFORE_IO")
    freeze = _b_r5_science_record(metadata.get("event_science_freeze_ref"),
        metadata.get("event_science_freeze_sha256"))
    authority = _b_r5_source_record(metadata.get("event_source_authority_ref"),
        metadata.get("event_source_authority_sha256"))
    scope = _b_r5_scope_record(metadata.get("human_scope_excerpt_ref"),
        metadata.get("human_scope_excerpt_sha256"))
    if (freeze.get("research_id") != identity or freeze.get("status") != "FROZEN_BEFORE_NUMERIC"
            or freeze.get("prior_cumulative_fit_units") != 3027
            or type(freeze.get("maximum_new_fit_units")) is not int
            or not 0 <= freeze["maximum_new_fit_units"] <= 1069
            or freeze.get("cumulative_fit_cap") != 4096
            or freeze.get("test2026_reads") != 0
            or freeze.get("provider_fetches") != 0 or freeze.get("EF_accesses") != 0
            or freeze.get("opportunity_expansion") is not False):
        raise RegistryError("B_R5_FROZEN_EVENT_BUDGET_BOUNDARY_REQUIRED")
    if (authority.get("research_id") != identity or authority.get("strict_PIT_promotion_eligible") is not False
            or authority.get("quote_qualified") is not False
            or authority.get("certified_nav_qualified") is not False
            or authority.get("EF_access") is not False or authority.get("network_provider_fetch") is not False
            or authority.get("2026_locked") is not True
            or candidate.get("source_contract_ref") != metadata.get("event_source_authority_ref")
            or freeze.get("source_authority_ref", {}).get("sha256") != metadata.get("event_source_authority_sha256")):
        raise RegistryError("B_R5_UNCERTIFIED_SOURCE_CONTRACT_REQUIRED")
    if (scope.get("task_id") != identity or scope.get("authority") != "CURRENT_TYPED_HUMAN_R5_REQUEST"
            or scope.get("full_human_message_digest_claimed") is not False
            or scope.get("risk_families") != freeze.get("risk_families")):
        raise RegistryError("B_R5_EXACT_HUMAN_SCOPE_EXCERPT_REQUIRED")
    if (resolution.get("kind") != "B_R5_SAME_SOURCE_EVENT_FULLPOOL_RISK_AND_IDENTITY"
            or canonical_json(resolution.get("automatic_decision")) != canonical_json(decision)):
        raise RegistryError("B_R5_AUTOMATIC_REVIEW_BINDING_REQUIRED")
    author, reviewer = _string(patch.get("author"), "author"), _review_gate(patch)["reviewer"]
    subjects = [{k:v for k,v in row.items() if k != "review_resolution"} for row in patch["operations"]]
    binding = dict(schema_version=1, research_id=identity, parent_entity_id=parent_id,
        registry_head_sha256=head_sha256, proposal_sha256=decision["proposal_sha256"],
        specification_fingerprint=candidate["specification_fingerprint"],
        mechanism_fingerprint=candidate["mechanism_fingerprint"],
        information_source_fingerprint=parent["information_source_fingerprint"],
        review_operations_subject_sha256=sha256_value(subjects), fit_authority=False,
        formal_freeze_authority=False, strict_PIT_promotion_eligible=False,
        source_contract_mode="FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY",
        event_science_freeze_sha256=metadata["event_science_freeze_sha256"],
        event_source_authority_sha256=metadata["event_source_authority_sha256"],
        human_scope_excerpt_sha256=metadata["human_scope_excerpt_sha256"])
    human = _r3_review_record(resolution.get("human_authorization_ref"),
        resolution.get("human_authorization_sha256"), "B_R5_HUMAN_AUTHORIZATION.json")
    review = _r3_review_record(resolution.get("independent_review_ref"),
        resolution.get("independent_review_sha256"), "B_R5_INDEPENDENT_REGISTRY_REVIEW.json")
    for record in (human, review):
        for key, expected in binding.items():
            if canonical_json(record.get(key)) != canonical_json(expected):
                raise RegistryError("B_R5_REVIEW_EVIDENCE_BINDING_MISMATCH:" + key)
    if (human.get("kind") != "HUMAN_AUTHORIZATION_RECORD" or human.get("human_user_authorized") is not True
            or human.get("authorization_source") != "CURRENT_HUMAN_REQUEST"
            or human.get("recorded_by") != author
            or human.get("human_request_sha256") != metadata["human_scope_excerpt_sha256"]):
        raise RegistryError("B_R5_DIRECT_HUMAN_AUTHORIZATION_REQUIRED")
    if (review.get("kind") != "INDEPENDENT_B_R5_REGISTRY_REVIEW" or review.get("status") != "PASS"
            or review.get("independent") is not True or review.get("author") != author
            or review.get("reviewer") != reviewer or review.get("scope") != "OPEN_METADATA_ONLY"
            or review.get("nonredundancy_basis") != "EVENT_FULLPOOL_RISK_CHAIN_AND_INDEPENDENT_HELD_IDENTITY"
            or review.get("prior_artifact_reopened") is not False or review.get("legacy_exposure_retained") is not True
            or review.get("human_authorization_sha256") != resolution["human_authorization_sha256"]):
        raise RegistryError("B_R5_INDEPENDENT_EXACT_REVIEW_REQUIRED")
    metadata.update(automatic_preflight_decision=dict(decision), explicit_review_decision="ACCEPT_OPEN_METADATA_ONLY",
        source_gate_required=True, human_authorization_ref=resolution["human_authorization_ref"],
        human_authorization_sha256=resolution["human_authorization_sha256"],
        independent_review_ref=resolution["independent_review_ref"], independent_review_sha256=resolution["independent_review_sha256"])
    return _normalize_entity(_entity_without_hash(normalized))


# One authorized A continuation-bank design. Admission records an OPEN design,
# not a new source, frozen-history adoption, account qualification or execution.
A_BREADTH_REVIEW_ENTITY_ID = "V24_A_BREADTH_PRE2026_R1"
A_BREADTH_REVIEW_INFORMATION_SHA256 = "9da06d947af82ee53a8e23b1781f0f43edc83127922ee3a35258fe731801e0ce"
A_BREADTH_REVIEW_SPECIFICATION = {
    "frozen_design_sha256": "d9ca279bcbe22c1f2ea5a9d17d2c76ecf8f98d1b5b4dac1c4c212dad64669488",
    "frozen_specification_sha256": "a9f1cd52cc1c665cc4c7d63439a528cda641fc95264b182f8531bf5d3cf849a2",
    "candidate_order_sha256": "3c14a11ad51304b197e502661d91719195675516485905d76f7a01cf8e1a80b4",
    "target_identity": "EXACT_PARENT_SHAREHOLDER_5D",
    "ordered_feature_sha256": "6e2020a8d99dabc657c7cb1fe5ec67dbff28a3b1da832581bdd90988d867f7a4",
    "value_main_count": 9, "fusion_main_count": 4, "interaction_count": 6,
    "new_fit": 0, "new_account_attempt_limit": 19, "automatic_retry_limit": 0,
    "raw_a2_selection": "FROZEN", "R5_and_frozen37": "UNCHANGED",
    "breadth_is_R5_prerequisite": False, "test2026": "LOCKED",
    "source_contract_mode": "UNBOUND_SOURCE_ACCOUNT_EXACT_BANK_REUSE",
}
A_BREADTH_REVIEW_MECHANISM = {
    "question": "Continuation learner and fusion main effects with sparse predeclared policy interactions",
    "role": "CONTINUATION_ACTION_VALUE_ONLY",
    "bank": "EXACT_EXISTING_VALUE_FUSION_RISK_REUSE",
    "comparison": "FIXED_REFERENCE_POLICY_AND_PREREGISTERED_CONTRASTS",
}
A_BREADTH_REQUIRED_CONTROLLER_PINS = {
    "stateful_execution": "b59030b6ec8da7e600297c46f3f078adf743a74b793ea20a65e844abafab446d",
    "stateful_completion": "59df0e8d389c5c905c737df60cab2d183ac5b7a8b7c87f23f8a8b87573073bf0",
}

A_BREADTH_REVIEW_PERMISSIONS = {
    "fit_authority": False, "formal_freeze_authority": False,
    "real_account_authority": False, "source_activation_authority": False,
    "branch_N_adopted": False, "strict_PIT_promotion_eligible": False,
    "source_gate_required": True, "source_gate": "BLOCKED_SOURCE_ACCOUNT_AUTHORITY",
}


def _resolve_a_breadth_review(
    operation: Mapping[str, Any], patch: Mapping[str, Any],
    normalized: dict[str, Any], decision: Mapping[str, Any], head_sha256: str,
) -> dict[str, Any]:
    """Admit only this OPEN metadata identity; automatic BLOCKED stays final."""
    if decision.get("decision") != "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE":
        raise RegistryError(f"PROPOSAL_NOT_APPLYABLE:{decision.get('decision')}")
    allowed_reasons = {
        "authoritative distinct-source contract/reference is required",
        "existing information source is reused without enough non-redundancy evidence",
        "raw information_source or feature_input_family overlaps existing history",
        "new fingerprint reuses an existing normalized information family",
    }
    if not decision.get("reasons") or not set(decision["reasons"]).issubset(allowed_reasons):
        raise RegistryError("A_BREADTH_REVIEW_UNSUPPORTED_AUTOMATIC_REASON")
    candidate = _candidate(operation["entity"])
    if (candidate["entity_id"] != A_BREADTH_REVIEW_ENTITY_ID
            or candidate["canonical_name"] != A_BREADTH_REVIEW_ENTITY_ID
            or candidate["aliases"] or normalized["status"] != "OPEN"
            or normalized["entity_type"] != "RESEARCH_BRANCH"
            or candidate["decision_layer"] != "CONTINUATION_STATEFUL_ACCOUNT_POLICY"
            or candidate.get("parent_entity_id") is not None
            or operation.get("parent_entity_id") is not None
            or candidate["information_source_fingerprint"] != A_BREADTH_REVIEW_INFORMATION_SHA256
            or operation.get("change_type") != "EXPLICIT_HUMAN_A_PREREGISTERED_EXACT_BANK_REUSE"):
        raise RegistryError("A_BREADTH_REVIEW_IDENTITY_NOT_AUTHORIZED")
    for field, expected in (("specification", A_BREADTH_REVIEW_SPECIFICATION),
                            ("mechanism", A_BREADTH_REVIEW_MECHANISM)):
        if (canonical_json(candidate.get(field)) != canonical_json(expected)
                or candidate.get(field + "_fingerprint") != sha256_value(expected)):
            raise RegistryError("A_BREADTH_REVIEW_CONTRACT_MISMATCH:" + field)
    metadata = normalized["metadata"]
    allowed_metadata = {"specification", "mechanism", "information_family", "design_custody_ref",
                        "execution_source_pins", *A_BREADTH_REVIEW_PERMISSIONS}
    if set(metadata) != allowed_metadata:
        raise RegistryError("A_BREADTH_REVIEW_UNSUPPORTED_METADATA")
    if metadata.get("information_family") != "frozen-r1-continuation-source32-and-current-account-state":
        raise RegistryError("A_BREADTH_REVIEW_INFORMATION_FAMILY_MISMATCH")
    if (not isinstance(metadata.get("design_custody_ref"), str)
            or not metadata["design_custody_ref"].strip()):
        raise RegistryError("A_BREADTH_REVIEW_DESIGN_CUSTODY_REQUIRED")
    _a_breadth_execution_pins(metadata.get("execution_source_pins"))
    for key, expected in A_BREADTH_REVIEW_PERMISSIONS.items():
        if canonical_json(metadata.get(key)) != canonical_json(expected):
            raise RegistryError("A_BREADTH_REVIEW_AUTHORITY_FORBIDDEN:" + key)
    resolution = operation.get("review_resolution")
    if (not isinstance(resolution, Mapping)
            or resolution.get("kind") != "A_BREADTH_EXACT_BANK_REUSE_OPEN_METADATA"
            or canonical_json(resolution.get("automatic_decision")) != canonical_json(decision)):
        raise RegistryError("A_BREADTH_REVIEW_AUTOMATIC_DECISION_MISMATCH")
    author = _string(patch.get("author"), "author")
    reviewer = _review_gate(patch)["reviewer"]
    subjects = [{key: value for key, value in row.items() if key != "review_resolution"}
                for row in patch["operations"]]
    binding = {
        "schema_version": 1, "research_id": A_BREADTH_REVIEW_ENTITY_ID,
        "registry_head_sha256": head_sha256, "proposal_sha256": decision["proposal_sha256"],
        "specification_fingerprint": candidate["specification_fingerprint"],
        "mechanism_fingerprint": candidate["mechanism_fingerprint"],
        "information_source_fingerprint": A_BREADTH_REVIEW_INFORMATION_SHA256,
        "parent_entity_id": None, "review_operations_subject_sha256": sha256_value(subjects),
        "execution_source_pins": metadata["execution_source_pins"],
        "constraints_sha256": sha256_value(A_BREADTH_REVIEW_SPECIFICATION),
        **A_BREADTH_REVIEW_PERMISSIONS,
    }
    records = []
    for prefix in ("human_authorization", "independent_review"):
        filename = ("A_BREADTH_REGISTRY_HUMAN_AUTHORIZATION.json" if prefix == "human_authorization"
                    else "A_BREADTH_REGISTRY_INDEPENDENT_REVIEW.json")
        record = _r3_review_record(resolution.get(prefix + "_ref"),
                                  resolution.get(prefix + "_sha256"), filename)
        for key, expected in binding.items():
            if canonical_json(record.get(key)) != canonical_json(expected):
                raise RegistryError("A_BREADTH_REVIEW_EVIDENCE_BINDING_MISMATCH:" + key)
        records.append(record)
    human, review = records
    if (human.get("kind") != "HUMAN_AUTHORIZATION_RECORD"
            or human.get("human_user_authorized") is not True
            or human.get("authorization_source") != "CURRENT_HUMAN_REQUEST"
            or human.get("recorded_by") != author):
        raise RegistryError("A_BREADTH_REVIEW_HUMAN_AUTHORIZATION_REQUIRED")
    _require_sha(human.get("human_request_sha256"), "human_request_sha256")
    if (review.get("kind") != "INDEPENDENT_A_BREADTH_REGISTRY_REVIEW"
            or review.get("status") != "PASS" or review.get("independent") is not True
            or review.get("author") != author or review.get("reviewer") != reviewer
            or review.get("scope") != "OPEN_METADATA_ONLY"
            or review.get("nonredundancy_basis") != "PREREGISTERED_CONTINUATION_POLICY_MAIN_EFFECTS_AND_INTERACTIONS"
            or review.get("prior_artifact_reopened") is not False
            or review.get("legacy_exposure_retained") is not True
            or review.get("source_fingerprint_is_bank_custody_only") is not True
            or review.get("accepted_registry_parent_claimed") is not False
            or review.get("human_authorization_sha256") != resolution["human_authorization_sha256"]):
        raise RegistryError("A_BREADTH_REVIEW_INDEPENDENT_REVIEW_REQUIRED")
    metadata.update({
        "automatic_preflight_decision": dict(decision),
        "explicit_review_decision": "ACCEPT_OPEN_METADATA_ONLY",
        "human_authorization_ref": resolution["human_authorization_ref"],
        "human_authorization_sha256": resolution["human_authorization_sha256"],
        "independent_review_ref": resolution["independent_review_ref"],
        "independent_review_sha256": resolution["independent_review_sha256"],
    })
    return _normalize_entity(_entity_without_hash(normalized))



def _a_breadth_execution_pins(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"breadth_adapter", *A_BREADTH_REQUIRED_CONTROLLER_PINS}:
        raise RegistryError("A_BREADTH_EXECUTION_SOURCE_PINS_REQUIRED")
    result = {key: _require_sha(digest, key + ".sha256") for key, digest in value.items()}
    if any(result[key] != digest for key, digest in A_BREADTH_REQUIRED_CONTROLLER_PINS.items()):
        raise RegistryError("A_BREADTH_R5_SOURCE_PINS_CHANGED")
    return result


def verify_a_breadth_admission(
    root: Path | str, *, design_sha256: str, execution_source_pins: Mapping[str, str],
) -> dict[str, Any]:
    """Verify accepted canonical metadata; caller dicts cannot self-certify OPEN."""
    if design_sha256 != A_BREADTH_REVIEW_SPECIFICATION["frozen_design_sha256"]:
        raise RegistryError("A_BREADTH_RUNTIME_DESIGN_MISMATCH")
    pins = _a_breadth_execution_pins(execution_source_pins)
    live = query_registry(root, entity_id=A_BREADTH_REVIEW_ENTITY_ID)
    if len(live["entities"]) != 1:
        raise RegistryError("A_BREADTH_CANONICAL_ADMISSION_MISSING")
    row = live["entities"][0]
    metadata = row["metadata"]
    if (row["status"] != "OPEN" or row["parent_entity_id"] is not None
            or row["decision_layer"] != "CONTINUATION_STATEFUL_ACCOUNT_POLICY"
            or row["information_source_fingerprint"] != A_BREADTH_REVIEW_INFORMATION_SHA256
            or row["specification_fingerprint"] != sha256_value(A_BREADTH_REVIEW_SPECIFICATION)
            or row["mechanism_fingerprint"] != sha256_value(A_BREADTH_REVIEW_MECHANISM)
            or canonical_json(metadata.get("specification")) != canonical_json(A_BREADTH_REVIEW_SPECIFICATION)
            or canonical_json(metadata.get("mechanism")) != canonical_json(A_BREADTH_REVIEW_MECHANISM)
            or canonical_json(metadata.get("execution_source_pins")) != canonical_json(pins)
            or metadata.get("explicit_review_decision") != "ACCEPT_OPEN_METADATA_ONLY"):
        raise RegistryError("A_BREADTH_CANONICAL_ADMISSION_MISMATCH")
    for key, expected in A_BREADTH_REVIEW_PERMISSIONS.items():
        if canonical_json(metadata.get(key)) != canonical_json(expected):
            raise RegistryError("A_BREADTH_CANONICAL_AUTHORITY_MISMATCH:" + key)
    automatic = metadata.get("automatic_preflight_decision", {})
    if (automatic.get("decision") != "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE"
            or automatic.get("status") != "REVIEW_REQUIRED"):
        raise RegistryError("A_BREADTH_CANONICAL_AUTOMATIC_DECISION_MISMATCH")
    for prefix, filename in (
        ("human_authorization", "A_BREADTH_REGISTRY_HUMAN_AUTHORIZATION.json"),
        ("independent_review", "A_BREADTH_REGISTRY_INDEPENDENT_REVIEW.json"),
    ):
        record = _r3_review_record(metadata.get(prefix + "_ref"),
                                  metadata.get(prefix + "_sha256"), filename)
        if (record.get("research_id") != A_BREADTH_REVIEW_ENTITY_ID
                or record.get("proposal_sha256") != automatic.get("proposal_sha256")
                or record.get("registry_head_sha256") != automatic.get("registry_head_sha256")
                or canonical_json(record.get("execution_source_pins")) != canonical_json(pins)):
            raise RegistryError("A_BREADTH_CANONICAL_REVIEW_REFERENCE_MISMATCH")
    return {
        "status": "PASS", "admission": "OPEN_METADATA_ONLY",
        "entity_id": A_BREADTH_REVIEW_ENTITY_ID,
        "registry_head_sha256": live["head_sha256"],
        "admission_base_head_sha256": automatic["registry_head_sha256"],
        "proposal_sha256": automatic["proposal_sha256"],
        "design_sha256": design_sha256, "execution_source_pins": pins,
        **A_BREADTH_REVIEW_PERMISSIONS,
    }



# Two explicitly authorized new supervised questions on the retained A input
# bank. This admission never authorizes accounts, source adoption, or holdout.
A_DECISION_REVIEW_SCOPES = {
    "V24_A_DIRECT_DECISION_LEARNING_PRE2026_R6": {
        "decision_layer": "DIRECT_STATEFUL_DECISION_SUPERVISED",
        "model_year_attempt_cap": 45, "physical_fit_attempt_cap": 81,
        "future_candidate_count": 15,
        "prior_comparison": "ACTION_ML_BUY_SELL_SIZING",
        "objective_structure": "BUY_HOLD_REPLACE_DURATION_DISTRIBUTIONAL",
    },
    "V24_A_LEARNED_GROSS_CASH_PRE2026_R7": {
        "decision_layer": "SCALAR_GROSS_CASH_SUPERVISED",
        "model_year_attempt_cap": 9, "physical_fit_attempt_cap": 15,
        "future_candidate_count": 3,
        "prior_comparison": "GENERIC_MARKET_RISK_GROSS_OVERLAYS",
        "objective_structure": "LEARNED_SCALAR_GROSS_CASH_ONLY",
    },
}
A_DECISION_REVIEW_SCOPE = "SUPERVISED_PRE2026_NO_ACCOUNT"
A_DECISION_REVIEW_CONSTRAINTS = {
    "scope": A_DECISION_REVIEW_SCOPE, "cutoff_exclusive": "2026-01-01",
    "annual_years": [2023, 2024, 2025], "seed_count": 1,
    "grid_count": 0, "optuna_count": 0, "scientific_retry_count": 0,
    "raw_a2_membership_frozen": True, "raw_a2_rank_frozen": True,
    "stock_q_frozen": True, "RL_allowed": False, "R5_frozen37_unchanged": True,
    "breadth19_unchanged": True, "real_account_count": 0, "test2026_locked": True,
}
A_DECISION_REVIEW_PERMISSIONS = {
    "fit_authority": True, "supervised_fit_authority": True,
    "formal_freeze_authority": False, "real_account_authority": False,
    "source_activation_authority": False, "branch_N_adopted": False,
    "strict_PIT_promotion_eligible": False, "test2026_locked": True,
    "source_gate": "BLOCKED_SOURCE_ACCOUNT_AUTHORITY",
}
A_DECISION_REVIEW_PARENTS = {"RAW_A2_HGB_BASELINE", "RAW_A2_BROAD_OOF_PREDICTIONS"}


def _a_decision_custody(reference: Any, digest: Any, label: str, *, source: bool = False) -> Path:
    """Verify bounded physical custody; never read prices, models or ledgers."""
    path = Path(_string(reference, label))
    pinned = _require_sha(digest, label + ".sha256")
    if (not path.is_absolute() or path.drive.casefold() in {"e:", "f:"}
            or (source and path.suffix != ".py")
            or (not source and path.suffix not in {".json", ".txt"})):
        raise RegistryError("A_DECISION_REVIEW_CUSTODY_REFERENCE_INVALID:" + label)
    try:
        if path.resolve(strict=True) != path.absolute() or path.stat().st_size > 262_144:
            raise RegistryError("A_DECISION_REVIEW_CUSTODY_REFERENCE_UNSAFE:" + label)
        if sha256_file(path) != pinned:
            raise RegistryError("A_DECISION_REVIEW_CUSTODY_SHA256_MISMATCH:" + label)
    except OSError as exc:
        raise RegistryError("A_DECISION_REVIEW_CUSTODY_UNREADABLE:" + label) from exc
    return path


def _a_decision_contract(candidate: Mapping[str, Any], entity_map: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    research_id = candidate.get("entity_id")
    limits = A_DECISION_REVIEW_SCOPES.get(str(research_id))
    if limits is None:
        raise RegistryError("A_DECISION_REVIEW_IDENTITY_NOT_AUTHORIZED")
    if (candidate.get("canonical_name") != research_id or candidate.get("aliases", [])
            or candidate.get("status") != "OPEN" or candidate.get("entity_type") != "RESEARCH_BRANCH"
            or candidate.get("decision_layer") != limits["decision_layer"]
            or candidate.get("information_source_fingerprint") != A_BREADTH_REVIEW_INFORMATION_SHA256):
        raise RegistryError("A_DECISION_REVIEW_IDENTITY_NOT_AUTHORIZED")
    parent_id = candidate.get("parent_entity_id")
    parent = entity_map.get(str(parent_id), {})
    if parent_id not in A_DECISION_REVIEW_PARENTS or parent.get("status") != "ACTIVE":
        raise RegistryError("A_DECISION_REVIEW_ACTIVE_RAW_PARENT_REQUIRED")
    specification = candidate.get("specification", candidate.get("metadata", {}).get("specification"))
    required_spec = {**A_DECISION_REVIEW_CONSTRAINTS,
                     **{key: limits[key] for key in ("model_year_attempt_cap", "physical_fit_attempt_cap", "future_candidate_count")}}
    if not isinstance(specification, Mapping) or set(specification) != {*required_spec, "frozen_spec_sha256"}:
        raise RegistryError("A_DECISION_REVIEW_SPECIFICATION_REQUIRED")
    for key, expected in required_spec.items():
        if canonical_json(specification.get(key)) != canonical_json(expected):
            raise RegistryError("A_DECISION_REVIEW_CONSTRAINT_MISMATCH:" + key)
    _require_sha(specification["frozen_spec_sha256"], "frozen_spec_sha256")
    if candidate.get("specification_fingerprint") != sha256_value(specification):
        raise RegistryError("A_DECISION_REVIEW_SPECIFICATION_FINGERPRINT_MISMATCH")
    mechanism = candidate.get("mechanism", candidate.get("metadata", {}).get("mechanism"))
    required_mechanism = {"objective_structure": limits["objective_structure"],
                          "label_contract_sha256": None, "policy_parameters_frozen": True}
    if not isinstance(mechanism, Mapping) or set(mechanism) != set(required_mechanism):
        raise RegistryError("A_DECISION_REVIEW_MECHANISM_REQUIRED")
    if (mechanism.get("objective_structure") != limits["objective_structure"]
            or mechanism.get("policy_parameters_frozen") is not True
            or candidate.get("mechanism_fingerprint") != sha256_value(mechanism)):
        raise RegistryError("A_DECISION_REVIEW_MECHANISM_MISMATCH")
    _require_sha(mechanism.get("label_contract_sha256"), "label_contract_sha256")
    normalized = _normalize_entity(candidate)
    metadata = normalized["metadata"]
    custody_fields = {"frozen_spec_ref", "frozen_spec_sha256", "input_manifest_ref", "input_manifest_sha256",
                      "future_candidates_ref", "future_candidates_sha256", "training_source_pins",
                      "user_attachment_ref", "user_attachment_sha256", "prior_comparison_rows"}
    allowed = {"specification", "mechanism", "information_family", *custody_fields, *A_DECISION_REVIEW_PERMISSIONS}
    accepted_fields = {"automatic_preflight_decision", "explicit_review_decision",
                       "human_authorization_ref", "human_authorization_sha256",
                       "independent_review_ref", "independent_review_sha256"}
    if set(metadata) not in (allowed, allowed | accepted_fields):
        raise RegistryError("A_DECISION_REVIEW_UNSUPPORTED_METADATA")
    if metadata.get("information_family") != "frozen-r1-continuation-source32-and-current-account-state":
        raise RegistryError("A_DECISION_REVIEW_INFORMATION_FAMILY_MISMATCH")
    for key, expected in A_DECISION_REVIEW_PERMISSIONS.items():
        if canonical_json(metadata.get(key)) != canonical_json(expected):
            raise RegistryError("A_DECISION_REVIEW_AUTHORITY_FORBIDDEN:" + key)
    if metadata.get("frozen_spec_sha256") != specification["frozen_spec_sha256"]:
        raise RegistryError("A_DECISION_REVIEW_FROZEN_SPEC_PIN_MISMATCH")
    for prefix in ("frozen_spec", "input_manifest", "future_candidates", "user_attachment"):
        _a_decision_custody(metadata.get(prefix + "_ref"), metadata.get(prefix + "_sha256"), prefix)
    future = _json_file(Path(metadata["future_candidates_ref"]))
    items = future.get("candidates") if isinstance(future, Mapping) else None
    if not isinstance(items, list) or len(items) != limits["future_candidate_count"]:
        raise RegistryError("A_DECISION_REVIEW_FUTURE_CANDIDATE_COUNT_MISMATCH")
    _reject_outcome_fields(future)
    identities = [item.get("candidate_id") if isinstance(item, Mapping) else None for item in items]
    if (any(not isinstance(item, str) or not item.strip() for item in identities)
            or len(set(identities)) != len(identities)):
        raise RegistryError("A_DECISION_REVIEW_FUTURE_CANDIDATE_IDENTITIES_REQUIRED")
    declared_pins = metadata.get("training_source_pins")
    descriptor_fields = {"frozen_spec_ref", "frozen_spec_sha256", "pinset_sha256"}
    if isinstance(declared_pins, Mapping) and set(declared_pins) == descriptor_fields:
        if (declared_pins["frozen_spec_ref"] != metadata["frozen_spec_ref"]
                or declared_pins["frozen_spec_sha256"] != metadata["frozen_spec_sha256"]):
            raise RegistryError("A_DECISION_REVIEW_SOURCE_SPEC_REFERENCE_MISMATCH")
        source_spec = _json_file(Path(metadata["frozen_spec_ref"]))
        if (not isinstance(source_spec, Mapping)
                or source_spec.get("schema_id") != "A_R6_R7_FROZEN_SUPERVISED_SPECIFICATION_R1"
                or not isinstance(source_spec.get("source_pins"), Mapping)):
            raise RegistryError("A_DECISION_REVIEW_FROZEN_SOURCE_SPEC_SCHEMA_REQUIRED")
        pins = dict(source_spec["source_pins"])
        if _require_sha(declared_pins["pinset_sha256"], "pinset_sha256") != sha256_value(pins):
            raise RegistryError("A_DECISION_REVIEW_SOURCE_PINSET_SHA256_MISMATCH")
    elif isinstance(declared_pins, Mapping):
        pins = dict(declared_pins)
    else:
        raise RegistryError("A_DECISION_REVIEW_TRAINING_SOURCE_PINS_REQUIRED")
    if not pins or len(pins) > 12:
        raise RegistryError("A_DECISION_REVIEW_TRAINING_SOURCE_PINS_REQUIRED")
    for path, digest in pins.items():
        _a_decision_custody(path, digest, "training_source_pin", source=True)
    prior = entity_map.get(limits["prior_comparison"], {})
    comparison = metadata.get("prior_comparison_rows")
    expected_comparison = [{
        "entity_id": limits["prior_comparison"], "status": "CLOSED",
        "row_hash": prior.get("row_hash"), "relationship": "PRIOR_NEGATIVE_COMPARISON_NOT_TRAINING_PARENT",
        "prior_artifact_reopened": False, "prior_conclusion_retained": True,
    }]
    if prior.get("status") != "CLOSED" or canonical_json(comparison) != canonical_json(expected_comparison):
        raise RegistryError("A_DECISION_REVIEW_PRIOR_CLOSURE_REQUIRED")
    return {
        "research_id": research_id, "parent_entity_id": parent_id,
        "parent_row_hash": parent.get("row_hash"), "scope": A_DECISION_REVIEW_SCOPE,
        "specification_fingerprint": candidate["specification_fingerprint"],
        "mechanism_fingerprint": candidate["mechanism_fingerprint"],
        "information_source_fingerprint": A_BREADTH_REVIEW_INFORMATION_SHA256,
        "custody_sha256": sha256_value({key: metadata[key] for key in sorted(custody_fields)}),
        "frozen_spec_sha256": metadata["frozen_spec_sha256"],
        "input_manifest_sha256": metadata["input_manifest_sha256"],
        "future_candidates_sha256": metadata["future_candidates_sha256"],
        "user_attachment_sha256": metadata["user_attachment_sha256"],
        "training_source_pins": dict(pins), **required_spec, **A_DECISION_REVIEW_PERMISSIONS,
    }



def a_decision_review_binding(
    root: Path | str, *, proposal: Mapping[str, Any], operation: Mapping[str, Any],
) -> dict[str, Any]:
    """Prepare exact review bindings read-only; never produce approval."""
    head, _, entities, aliases = _load_live_snapshot(Path(root))
    expected_proposal = {
        "candidate": operation.get("entity"), "change_type": operation.get("change_type"),
        "parent_entity_id": operation.get("parent_entity_id"),
    }
    if canonical_json(proposal) != canonical_json(expected_proposal):
        raise RegistryError("A_DECISION_REVIEW_PROPOSAL_OPERATION_MISMATCH")
    decision = evaluate_proposal(proposal, entities, aliases, head_sha256=head)
    if decision["decision"] != "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE":
        raise RegistryError(f"PROPOSAL_NOT_APPLYABLE:{decision['decision']}")
    binding = _a_decision_contract(_candidate(operation["entity"]), {row["entity_id"]: row for row in entities})
    subjects = [{key: value for key, value in operation.items() if key != "review_resolution"}]
    binding.update({"schema_version": 1, "registry_head_sha256": head,
                    "proposal_sha256": decision["proposal_sha256"],
                    "review_operations_subject_sha256": sha256_value(subjects)})
    binding["training_source_pins"] = _normalize_entity(operation["entity"])["metadata"]["training_source_pins"]
    return {"automatic_decision": decision, "review_binding": binding}


def _resolve_a_decision_review(
    operation: Mapping[str, Any], patch: Mapping[str, Any], normalized: dict[str, Any],
    decision: Mapping[str, Any], entity_map: Mapping[str, Mapping[str, Any]], head_sha256: str,
) -> dict[str, Any]:
    """Accept only two supervised identities, preserving every automatic BLOCKED."""
    if decision.get("decision") != "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE":
        raise RegistryError(f"PROPOSAL_NOT_APPLYABLE:{decision.get('decision')}")
    allowed_reasons = {
        "existing information source is reused without enough non-redundancy evidence",
        "raw information_source or feature_input_family overlaps existing history",
        "new fingerprint reuses an existing normalized information family",
    }
    if not decision.get("reasons") or not set(decision["reasons"]).issubset(allowed_reasons):
        raise RegistryError("A_DECISION_REVIEW_UNSUPPORTED_AUTOMATIC_REASON")
    candidate = _candidate(operation["entity"])
    if (operation.get("change_type") != "EXPLICIT_HUMAN_A_NEW_SUPERVISED_DECISION_STRUCTURE"
            or operation.get("parent_entity_id") != candidate.get("parent_entity_id")):
        raise RegistryError("A_DECISION_REVIEW_CHANGE_TYPE_REQUIRED")
    binding = _a_decision_contract(candidate, entity_map)
    resolution = operation.get("review_resolution")
    if (not isinstance(resolution, Mapping)
            or resolution.get("kind") != "A_DIRECT_DECISION_SUPERVISED_PRE2026"
            or canonical_json(resolution.get("automatic_decision")) != canonical_json(decision)):
        raise RegistryError("A_DECISION_REVIEW_AUTOMATIC_DECISION_MISMATCH")
    author = _string(patch.get("author"), "author")
    reviewer = _review_gate(patch)["reviewer"]
    subjects = [{key: value for key, value in row.items() if key != "review_resolution"}
                for row in patch["operations"]]
    binding.update({"schema_version": 1, "registry_head_sha256": head_sha256,
                    "proposal_sha256": decision["proposal_sha256"],
                    "review_operations_subject_sha256": sha256_value(subjects)})
    binding["training_source_pins"] = normalized["metadata"]["training_source_pins"]
    records = []
    stage = "R6" if str(candidate["entity_id"]).endswith("_R6") else "R7"
    for prefix, suffix in (("human_authorization", "HUMAN_AUTHORIZATION"), ("independent_review", "INDEPENDENT_REVIEW")):
        filename = f"A_{stage}_REGISTRY_{suffix}.json"
        record = _r3_review_record(resolution.get(prefix + "_ref"), resolution.get(prefix + "_sha256"), filename)
        for key, expected in binding.items():
            if canonical_json(record.get(key)) != canonical_json(expected):
                raise RegistryError("A_DECISION_REVIEW_EVIDENCE_BINDING_MISMATCH:" + key)
        records.append(record)
    human, review = records
    if (human.get("kind") != "HUMAN_AUTHORIZATION_RECORD" or human.get("human_user_authorized") is not True
            or human.get("authorization_source") != "CURRENT_HUMAN_REQUEST"
            or human.get("recorded_by") != author
            or human.get("human_request_sha256") != binding["user_attachment_sha256"]):
        raise RegistryError("A_DECISION_REVIEW_HUMAN_AUTHORIZATION_REQUIRED")
    if (review.get("kind") != "INDEPENDENT_A_DECISION_REGISTRY_REVIEW"
            or review.get("status") != "PASS" or review.get("independent") is not True
            or review.get("author") != author or review.get("reviewer") != reviewer
            or review.get("scope") != A_DECISION_REVIEW_SCOPE
            or review.get("nonredundancy_basis") != "NEW_FROZEN_DIRECT_DECISION_TARGET_STRUCTURE"
            or review.get("prior_artifact_reopened") is not False
            or review.get("legacy_exposure_retained") is not True
            or review.get("source_fingerprint_is_bank_custody_only") is not True
            or review.get("human_authorization_sha256") != resolution["human_authorization_sha256"]):
        raise RegistryError("A_DECISION_REVIEW_INDEPENDENT_REVIEW_REQUIRED")
    normalized["metadata"].update({
        "automatic_preflight_decision": dict(decision),
        "explicit_review_decision": "ACCEPT_SUPERVISED_PRE2026_NO_ACCOUNT",
        **{key: resolution[key] for key in ("human_authorization_ref", "human_authorization_sha256",
                                          "independent_review_ref", "independent_review_sha256")},
    })
    return _normalize_entity(_entity_without_hash(normalized))


def verify_a_decision_admission(
    root: Path | str, *, research_id: str, frozen_spec_sha256: str,
    input_manifest_sha256: str, training_source_pins: Mapping[str, str],
) -> dict[str, Any]:
    """Recheck canonical admission and physical evidence before supervised fit."""
    head, _, entities, _ = _load_live_snapshot(Path(root))
    entity_map = {row["entity_id"]: row for row in entities}
    row = entity_map.get(research_id)
    if row is None or research_id not in A_DECISION_REVIEW_SCOPES:
        raise RegistryError("A_DECISION_CANONICAL_ADMISSION_MISSING")
    binding = _a_decision_contract(_entity_without_hash(row), entity_map)
    metadata = row["metadata"]
    if (binding["frozen_spec_sha256"] != frozen_spec_sha256
            or binding["input_manifest_sha256"] != input_manifest_sha256
            or canonical_json(binding["training_source_pins"]) != canonical_json(training_source_pins)
            or metadata.get("explicit_review_decision") != "ACCEPT_SUPERVISED_PRE2026_NO_ACCOUNT"):
        raise RegistryError("A_DECISION_CANONICAL_ADMISSION_MISMATCH")
    automatic = metadata.get("automatic_preflight_decision", {})
    if (automatic.get("decision") != "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE"
            or automatic.get("status") != "REVIEW_REQUIRED"):
        raise RegistryError("A_DECISION_CANONICAL_AUTOMATIC_DECISION_MISMATCH")
    binding.update({"schema_version": 1, "registry_head_sha256": automatic.get("registry_head_sha256"),
                    "proposal_sha256": automatic.get("proposal_sha256")})
    stage = "R6" if research_id.endswith("_R6") else "R7"
    evidence_binding = {**binding, "training_source_pins": metadata["training_source_pins"]}
    records = []
    for prefix, suffix in (("human_authorization", "HUMAN_AUTHORIZATION"), ("independent_review", "INDEPENDENT_REVIEW")):
        record = _r3_review_record(metadata.get(prefix + "_ref"), metadata.get(prefix + "_sha256"),
                                  f"A_{stage}_REGISTRY_{suffix}.json")
        for key, expected in evidence_binding.items():
            if canonical_json(record.get(key)) != canonical_json(expected):
                raise RegistryError("A_DECISION_CANONICAL_REVIEW_REFERENCE_MISMATCH:" + key)
        records.append(record)
    human, review = records
    if (human.get("kind") != "HUMAN_AUTHORIZATION_RECORD" or human.get("human_user_authorized") is not True
            or human.get("authorization_source") != "CURRENT_HUMAN_REQUEST"
            or human.get("human_request_sha256") != binding["user_attachment_sha256"]
            or review.get("kind") != "INDEPENDENT_A_DECISION_REGISTRY_REVIEW"
            or review.get("status") != "PASS" or review.get("independent") is not True
            or review.get("scope") != A_DECISION_REVIEW_SCOPE
            or not human.get("recorded_by") or review.get("author") != human["recorded_by"]
            or not review.get("reviewer") or review["reviewer"] == review["author"]
            or review.get("nonredundancy_basis") != "NEW_FROZEN_DIRECT_DECISION_TARGET_STRUCTURE"
            or review.get("prior_artifact_reopened") is not False
            or review.get("legacy_exposure_retained") is not True
            or review.get("source_fingerprint_is_bank_custody_only") is not True
            or review.get("human_authorization_sha256") != metadata["human_authorization_sha256"]):
        raise RegistryError("A_DECISION_CANONICAL_REVIEW_AUTHORITY_INVALID")
    return {**binding, "status": "PASS", "admission": A_DECISION_REVIEW_SCOPE,
            "registry_head_sha256": head, "admission_base_head_sha256": automatic["registry_head_sha256"]}

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
    if any(isinstance(row, Mapping) and "review_resolution" in row for row in operations):
        if (audited_inventory_bootstrap or len(operations) != 1
                or str(operations[0].get("op", "")) != "add_entity"
                or not isinstance(operations[0].get("entity"), Mapping)
                or str(operations[0]["entity"].get("entity_id", "")) in entity_map):
            raise RegistryError("R3_REVIEW_SINGLE_NEW_ENTITY_OPERATION_REQUIRED")
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
                    if "review_resolution" in operation:
                        normalized = _resolve_r3_review(
                            operation, patch, normalized, decision, entity_map, head_sha256,
                        )
                    elif decision["decision"] not in {"PASS_DISTINCT_INFORMATION_SOURCE", "EXTEND_EXISTING"}:
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


def _b_r5_query_source_alias(row: Mapping[str, Any]) -> dict[str, Any]:
    """Exact selected R5 public alias of accepted metadata; no source reads."""
    if row.get("entity_id") != "V24_B_DYNAMIC_FULLPOOL_RISK_AND_IDENTITY_R5":
        return row
    metadata = row.get("metadata", {})
    source = metadata.get("event_source_authority_ref") if isinstance(metadata, Mapping) else None
    digest = metadata.get("event_source_authority_sha256") if isinstance(metadata, Mapping) else None
    if (not isinstance(metadata, Mapping) or not isinstance(source, str)
            or not source or not Path(source).is_absolute()
            or Path(source).drive.upper() != "D:"
            or Path(source).name != "SOURCE_AUTHORITY.json"
            or not isinstance(digest, str) or not HEX_SHA256.fullmatch(digest)
            or metadata.get("explicit_review_decision") != "ACCEPT_OPEN_METADATA_ONLY"
            or any(metadata.get(key) is not False for key in
                   ("fit_authority", "formal_freeze_authority", "strict_PIT_promotion_eligible"))):
        raise RegistryError("R5_QUERY_ACCEPTED_SOURCE_METADATA_REQUIRED")
    if "source_contract_ref" in row and row["source_contract_ref"] != source:
        raise RegistryError("R5_QUERY_SOURCE_CONTRACT_ALIAS_CONFLICT")
    return dict(row) | {"source_contract_ref": source}


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
    if entity_id == "V24_B_DYNAMIC_FULLPOOL_RISK_AND_IDENTITY_R5":
        public_rows = [_b_r5_query_source_alias(row) for row in public_rows]
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
    default = Path(__file__).resolve().parents[2] / "config" / "research_registry.json"
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
