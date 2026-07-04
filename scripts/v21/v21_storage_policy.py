"""Shared V21 storage policy helpers.

Defaults are intentionally compact. Full intermediate artifacts require an
explicit environment override by the operator or a failure/debug preservation
path in the calling stage.
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any, Iterable


COMPACT_MODE = "compact"
FULL_MODE = "full"
DEFAULT_MAX_ROWS = 5000
SENSITIVE_CURRENT_CHAIN_TOKENS = {
    "canonical",
    "price_history",
    "ohlcv",
    "kline",
    "moomoo",
    "dram",
    "abcde",
    "trade_plan",
    "ledger",
    "ranking",
    "latest",
    "current_chain",
    "protected",
}


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "y", "on"}


def get_output_mode() -> str:
    mode = os.environ.get("V21_OUTPUT_MODE", COMPACT_MODE).strip().lower()
    return FULL_MODE if mode == FULL_MODE else COMPACT_MODE


def keep_full_artifacts() -> bool:
    return get_output_mode() == FULL_MODE or _env_true("V21_KEEP_FULL_ARTIFACTS")


def should_write_full_artifact(stage_name: str, artifact_name: str, final_status: str = "", debug_preservation_enabled: bool = False) -> bool:
    if keep_full_artifacts():
        return True
    if final_status.startswith("FAIL") and debug_preservation_enabled:
        return True
    text = f"{stage_name} {artifact_name}".lower()
    if any(token in text for token in SENSITIVE_CURRENT_CHAIN_TOKENS):
        return False
    return False


def cap_dataframe_rows(df: Any, max_rows: int = DEFAULT_MAX_ROWS) -> Any:
    if hasattr(df, "head"):
        return df.head(max_rows)
    return df


def write_compact_csv(rows_or_df: Any, path: str | Path, max_rows: int = DEFAULT_MAX_ROWS) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(rows_or_df, "head") and hasattr(rows_or_df, "to_csv"):
        capped = rows_or_df.head(max_rows)
        capped.to_csv(path, index=False)
        return len(capped)
    rows = list(rows_or_df)[:max_rows]
    if not rows:
        path.write_text("", encoding="utf-8")
        return 0
    if isinstance(rows[0], dict):
        fields = list(rows[0].keys())
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    else:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerows(rows)
    return len(rows)


def write_artifact_manifest(artifacts: Iterable[dict[str, Any]], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(artifacts)
    fields = ["artifact_path", "artifact_type", "size_bytes", "retention_class", "notes"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def enforce_output_budget(current_size_bytes: int, budget_bytes: int, stage_name: str = "") -> dict[str, Any]:
    over = max(0, int(current_size_bytes) - int(budget_bytes))
    return {
        "stage_name": stage_name,
        "current_size_bytes": int(current_size_bytes),
        "budget_bytes": int(budget_bytes),
        "within_budget": over == 0,
        "over_budget_bytes": over,
        "output_mode": get_output_mode(),
    }


def write_json_compact(payload: dict[str, Any], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")
