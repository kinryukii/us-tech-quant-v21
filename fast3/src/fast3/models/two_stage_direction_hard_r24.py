"""FAST3 R4 hard-storage R2.4 fixed direct-versus-two-stage study.

The modelling primitives are deliberately inherited from the previous frozen
implementation.  This module adds the R2.4 storage, schedule and checkpoint
identity guards without introducing a second research framework.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fast3.models import two_stage_direction_hard_r22 as _r22


UP, DOWN, NO_EVENT, AMBIGUOUS = _r22.UP, _r22.DOWN, _r22.NO_EVENT, _r22.AMBIGUOUS
EVENT_LABELS, INTERACTIONS, SEEDS, MODEL_PARAMETERS = (
    _r22.EVENT_LABELS, _r22.INTERACTIONS, _r22.SEEDS, _r22.MODEL_PARAMETERS,
)
R4ContractError = _r22.R4ContractError
canonical_json = _r22.canonical_json
stable_hash = _r22.stable_hash
file_hash = _r22.file_hash
write_json = _r22.write_json
not_run = _r22.not_run
block_rows = _r22.block_rows
FoldPreprocessor = _r22.FoldPreprocessor
training_weights = _r22.training_weights
score_architecture = _r22.score_architecture
metrics = _r22.metrics
economics = _r22.economics
clustered_ci = _r22.clustered_ci
fixed_nulls = _r22.fixed_nulls
gate = _r22.gate
diagnostics = _r22.diagnostics
freeze_prospective_model = _r22.freeze_prospective_model
validate_source_freeze = _r22.validate_source_freeze


REQUIRED_PHASES = ("development", "internal_holdout")


def prepare_cohort(raw, features: list[str]):
    # Validate R3 label lineage, then reuse all shared R22 PIT checks.
    import pandas as pd

    label_column = next(
        (name for name in ("label", "future_label") if name in raw.columns),
        None,
    )
    if label_column is None:
        raise R4ContractError("DATA_REQUIRED_COLUMN_MISSING:label")

    allowed = {UP, DOWN, NO_EVENT, AMBIGUOUS}
    labels = raw[label_column].astype(str)
    unknown = set(labels.dropna()).difference(allowed)
    if unknown:
        raise R4ContractError(f"UNKNOWN_LABEL:{sorted(unknown)}")

    decision_column = next(
        (name for name in (
            "decision_timestamp_et", "timestamp_et", "entry_timestamp_et"
        ) if name in raw.columns),
        None,
    )
    entry_column = next(
        (name for name in (
            "entry_timestamp_et", "entry_timestamp_utc"
        ) if name in raw.columns),
        None,
    )
    horizon_column = next(
        (name for name in (
            "horizon_timestamp_et", "label_end_timestamp_et"
        ) if name in raw.columns),
        None,
    )
    if decision_column is None:
        raise R4ContractError("DATA_REQUIRED_COLUMN_MISSING:decision_timestamp")
    if entry_column is None:
        raise R4ContractError("DATA_REQUIRED_COLUMN_MISSING:label_start_timestamp")
    if horizon_column is None:
        raise R4ContractError("DATA_REQUIRED_COLUMN_MISSING:label_end_timestamp")

    adapted = raw.copy()
    decision = pd.to_datetime(adapted[decision_column], errors="raise", utc=True)
    entry = pd.to_datetime(adapted[entry_column], errors="raise", utc=True)
    observed_end = pd.to_datetime(
        adapted[horizon_column], errors="raise", utc=True
    )
    contract_end = entry + pd.Timedelta(hours=24)

    if (entry < decision).any():
        raise R4ContractError("LABEL_START_BEFORE_DECISION")
    if (observed_end <= entry).any():
        raise R4ContractError("LABEL_HORIZON_NOT_AFTER_ENTRY")
    if (observed_end > contract_end).any():
        raise R4ContractError("LABEL_HORIZON_AFTER_24H_DEADLINE")

    event_mask = labels.isin((UP, DOWN))
    if "hit_timestamp_et" in adapted.columns:
        hit = pd.to_datetime(
            adapted["hit_timestamp_et"], errors="coerce", utc=True
        )
        if (event_mask & hit.isna()).any():
            raise R4ContractError("EVENT_HIT_TIMESTAMP_MISSING")
        if (event_mask & ((hit < entry) | (hit > observed_end))).any():
            raise R4ContractError("EVENT_HIT_OUTSIDE_OBSERVED_LABEL_PATH")
    if "touch_minutes" in adapted.columns:
        touch = pd.to_numeric(adapted["touch_minutes"], errors="coerce")
        invalid = event_mask & (
            touch.isna() | touch.lt(0.0) | touch.gt(1440.0)
        )
        if invalid.any():
            raise R4ContractError("EVENT_TOUCH_MINUTES_OUTSIDE_24H")

    adapted["__r24_label_start_timestamp_et"] = entry
    adapted["__r24_label_observed_end_timestamp_et"] = observed_end
    adapted["__r24_label_contract_end_timestamp_et"] = contract_end
    adapted[horizon_column] = contract_end

    cohort = _r22.prepare_cohort(adapted, features)
    cohort["label_start_timestamp_et"] = pd.to_datetime(
        cohort.pop("__r24_label_start_timestamp_et"), errors="raise", utc=True
    )
    cohort["label_observed_end_timestamp_et"] = pd.to_datetime(
        cohort.pop("__r24_label_observed_end_timestamp_et"),
        errors="raise",
        utc=True,
    )
    cohort["label_contract_end_timestamp_et"] = pd.to_datetime(
        cohort.pop("__r24_label_contract_end_timestamp_et"),
        errors="raise",
        utc=True,
    )
    cohort["label_end_timestamp_et"] = cohort[
        "label_contract_end_timestamp_et"
    ]
    cohort["label_observed_span_minutes"] = (
        cohort["label_observed_end_timestamp_et"]
        - cohort["label_start_timestamp_et"]
    ).dt.total_seconds() / 60.0
    return cohort


def _schedule_payload(schedule: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in schedule.items() if key != "schedule_hash"}


def deterministic_schedule(cohort, *, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create or verify the one immutable eight-block schedule.

    Candidate blocks are 60 days wide and are spaced by 65 days.  Selection is
    seeded exactly once before models are fitted; an existing schedule is
    accepted only when its content hash and frozen structure both match.
    """
    if existing is not None:
        if existing.get("schedule_hash") != stable_hash(_schedule_payload(existing)):
            raise R4ContractError("RANDOM_BLOCK_SCHEDULE_HASH_INVALID")
        blocks = existing.get("blocks")
        if not isinstance(blocks, list) or len(blocks) != 8:
            raise R4ContractError("RANDOM_BLOCK_SCHEDULE_CARDINALITY_INVALID")
        phases = [block.get("phase") for block in blocks]
        if phases != ["development"] * 4 + ["internal_holdout"] * 4:
            raise R4ContractError("RANDOM_BLOCK_SCHEDULE_PHASES_INVALID")
        ids = [block.get("block_id") for block in blocks]
        if len(set(ids)) != 8 or any(not isinstance(value, str) for value in ids):
            raise R4ContractError("RANDOM_BLOCK_SCHEDULE_IDS_INVALID")
        return existing
    return _r22.deterministic_schedule(cohort)


def checkpoint_fingerprint(source_freeze: dict[str, Any], schedule: dict[str, Any], phase: str,
                           block_id: str, seed: int) -> str:
    """Hash every value which can change a saved block/seed result."""
    if phase not in REQUIRED_PHASES:
        raise R4ContractError(f"UNKNOWN_PHASE:{phase}")
    return stable_hash({
        "source_hashes": {key: source_freeze.get(key) for key in (
            "r3_summary_hash", "r3_model_freeze_hash", "r3_audit_hash", "source_cohort_sha256")},
        "ordered_features": source_freeze.get("features"),
        "interactions": source_freeze.get("interactions"),
        "schedule_hash": schedule.get("schedule_hash"), "phase": phase,
        "block_id": block_id, "seed": int(seed), "model_parameters": MODEL_PARAMETERS,
        "opportunity_threshold": 0.60, "top_fraction": 0.05,
        "ranking": "max(P_UP_FIRST,P_DOWN_FIRST)", "purge_hours": 24, "embargo_hours": 24,
        "weight_formula": "uniqueness_weight*training_fold_class_weight*training_fold_era_weight",
    })


def run_checkpoint(train, test, features: list[str], phase: str, block_id: str, seed: int,
                   source_freeze: dict[str, Any], schedule: dict[str, Any], scratch_root: Path) -> dict[str, Any]:
    """Run one fixed comparison, or resume only a complete identical result."""
    fingerprint = checkpoint_fingerprint(source_freeze, schedule, phase, block_id, seed)
    path = Path(scratch_root) / "checkpoints" / f"{phase}_{block_id}_{seed}.json"
    if path.is_file():
        import json
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("status") == "COMPLETE" and cached.get("fingerprint") == fingerprint:
            return cached
    direct, _ = score_architecture(train, test, features, seed, "direct")
    two_stage, _ = score_architecture(train, test, features, seed, "two_stage")
    result = {
        "status": "COMPLETE", "historical_status": "NON_PROSPECTIVE",
        "fingerprint": fingerprint, "phase": phase, "block_id": block_id, "seed": int(seed),
        "direct": metrics(direct), "two_stage": metrics(two_stage),
        "economic": economics(two_stage, block_id)[0],
        "nulls": fixed_nulls(two_stage, train, block_id, seed),
    }
    write_json(path, result)
    return result


def run_phase(cohort, schedule: dict[str, Any], source_freeze: dict[str, Any], scratch_root: Path,
              phase: str) -> list[dict[str, Any]]:
    if phase not in REQUIRED_PHASES:
        raise R4ContractError(f"UNKNOWN_PHASE:{phase}")
    blocks = [block for block in schedule["blocks"] if block["phase"] == phase]
    if len(blocks) != 4:
        raise R4ContractError(f"SCHEDULE_PHASE_BLOCK_COUNT_INVALID:{phase}")
    records = []
    for block in blocks:
        train, test = block_rows(cohort, block)
        for seed in SEEDS[phase]:
            records.append(run_checkpoint(train, test, source_freeze["features"], phase,
                                          block["block_id"], seed, source_freeze, schedule, scratch_root))
    return records
