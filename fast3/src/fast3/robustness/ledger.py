"""External append-only JSONL experiment ledger."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

from .contract import canonical_json


class LedgerError(ValueError):
    pass


_FIELDS = {"experiment_id", "parent_experiment_id", "created_at_utc", "source_branch", "source_commit",
           "dirty_worktree", "evaluator_version", "evaluation_contract_hash", "dataset_hash", "feature_set_hash",
           "model_config_hash", "model_artifact_hash", "frozen_runner_hash", "random_seed",
           "attempted_model_count", "attempted_configuration_count", "attempted_seed_count", "train_window",
           "development_window", "confirmation_window", "final_window", "purge_minutes", "embargo_minutes",
           "cost_bps", "gross_metrics", "net_metrics", "robustness_metrics", "decision", "rejection_reason", "artifact_paths"}


def _valid(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise LedgerError("LEDGER_NONFINITE_VALUE")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str): raise LedgerError("LEDGER_NONSTRING_KEY")
            _valid(item)
    elif isinstance(value, (list, tuple)):
        for item in value: _valid(item)


class ExperimentLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    def _validate(self, record: dict[str, Any]) -> None:
        if set(record) != _FIELDS: raise LedgerError("LEDGER_SCHEMA_INVALID")
        if not isinstance(record["experiment_id"], str) or not record["experiment_id"]: raise LedgerError("LEDGER_EXPERIMENT_ID_INVALID")
        _valid(record)

    def append(self, record: dict[str, Any]) -> None:
        self._validate(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.touch(exist_ok=True)
        import msvcrt
        with self.lock_path.open("r+b") as lock:
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            try:
                seen: set[str] = set()
                if self.path.exists():
                    for line in self.path.read_text(encoding="utf-8").splitlines():
                        try: old = json.loads(line)
                        except json.JSONDecodeError as exc: raise LedgerError("LEDGER_EXISTING_JSON_INVALID") from exc
                        seen.add(old.get("experiment_id", ""))
                if record["experiment_id"] in seen: raise LedgerError("LEDGER_EXPERIMENT_ID_DUPLICATE")
                line = canonical_json(record) + "\n"
                with self.path.open("a", encoding="utf-8", newline="\n") as output:
                    output.write(line); output.flush(); os.fsync(output.fileno())
            finally:
                lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
