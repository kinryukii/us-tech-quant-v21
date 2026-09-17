"""Immutable input verification and externally routed attribution outputs."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd


RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
VALID_IMMUTABLE_STATUSES = {
    "FROZEN_IMMUTABLE", "COMPLETE_IMMUTABLE", "PASS_FROZEN_IMMUTABLE_RESEARCH_BASELINE",
}
FORBIDDEN_LIVE_RUN_IDS = {"A2_OVERNIGHT_OPEN_RESEARCH_20260821_R1"}


class ImmutableInputError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def verify_immutable_manifest(manifest_path: Path, supplied: Mapping[str, Path]) -> dict[str, Any]:
    if any(token.lower() in str(manifest_path).lower() for token in FORBIDDEN_LIVE_RUN_IDS):
        raise ImmutableInputError("live Overnight Research manifest path is forbidden")
    if any(token in manifest_path.name.lower() for token in (".tmp", "latest")):
        raise ImmutableInputError("mutable-looking manifest name is forbidden")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") not in VALID_IMMUTABLE_STATUSES:
        raise ImmutableInputError("immutable manifest status is absent or invalid")
    if str(manifest.get("freeze_id") or "").upper() in {"", "UNKNOWN"}:
        raise ImmutableInputError("immutable manifest requires freeze_id")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ImmutableInputError("immutable manifest requires an artifacts object")
    if set(supplied) != set(artifacts):
        raise ImmutableInputError("supplied artifacts must exactly match immutable manifest")
    for name, supplied_path in supplied.items():
        entry = artifacts[name]
        expected_path = Path(str(entry.get("path") or ""))
        expected_hash = str(entry.get("sha256") or "").lower()
        if len(expected_hash) != 64 or any(character not in "0123456789abcdef" for character in expected_hash):
            raise ImmutableInputError(f"invalid sha256 for {name}")
        if any(token.lower() in str(supplied_path).lower() for token in FORBIDDEN_LIVE_RUN_IDS):
            raise ImmutableInputError("live Overnight Research artifact path is forbidden")
        if any(token in supplied_path.name.lower() for token in (".tmp", "latest")):
            raise ImmutableInputError(f"mutable-looking artifact name forbidden: {supplied_path.name}")
        if _path_key(supplied_path) != _path_key(expected_path):
            raise ImmutableInputError(f"artifact path mismatch: {name}")
        if not supplied_path.is_file():
            raise ImmutableInputError(f"artifact missing: {name}")
        if sha256_file(supplied_path) != expected_hash:
            raise ImmutableInputError(f"artifact hash mismatch: {name}")
        for identity in ("strategy_id", "model_id", "date_start", "date_end"):
            if str(entry.get(identity) or "").upper() in {"", "UNKNOWN"}:
                raise ImmutableInputError(f"artifact identity missing: {name}.{identity}")
    for provenance in ("training_cutoff", "universe_id"):
        if str(manifest.get(provenance) or "").upper() in {"", "UNKNOWN"}:
            raise ImmutableInputError(f"immutable manifest requires {provenance}")
    for provenance in ("data_manifest_sha256", "model_sha256"):
        values = manifest.get(provenance)
        values = list(values.values()) if isinstance(values, dict) else [values]
        if not values or any(
            len(str(value or "")) != 64
            or any(character not in "0123456789abcdef" for character in str(value).lower())
            for value in values
        ):
            raise ImmutableInputError(f"immutable manifest requires valid {provenance}")
    return manifest


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".parquet":
        return pd.read_parquet(path)
    raise ImmutableInputError(f"unsupported immutable table format: {suffix}")


def verify_loaded_identity(name: str, frame: pd.DataFrame, artifact: Mapping[str, Any]) -> None:
    if frame.empty or "date" not in frame:
        raise ImmutableInputError(f"empty or dateless artifact: {name}")
    dates = pd.to_datetime(frame.date, errors="coerce")
    if dates.isna().any():
        raise ImmutableInputError(f"invalid dates: {name}")
    observed_start, observed_end = dates.min().date().isoformat(), dates.max().date().isoformat()
    if (observed_start, observed_end) != (str(artifact["date_start"]), str(artifact["date_end"])):
        raise ImmutableInputError(f"date coverage mismatch: {name}")
    for field in ("strategy_id", "model_id"):
        if field in frame:
            values = set(frame[field].astype(str))
            if values != {str(artifact[field])}:
                raise ImmutableInputError(f"{field} mismatch: {name}")


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
        return None
    return value


def validate_output_dir(output_dir: Path) -> None:
    resolved = output_dir.resolve()
    if not resolved.is_relative_to(RESULTS_ROOT.resolve()):
        raise ImmutableInputError(f"output must be under approved results root: {RESULTS_ROOT}")


def _concat_tables(tables: Mapping[str, pd.DataFrame], label: str) -> pd.DataFrame:
    rows = []
    for name, frame in tables.items():
        item = frame.copy()
        item.insert(0, label, name)
        rows.append(item)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def write_outputs(
    a2_result: dict[str, Any], incremental: dict[str, Any], output_dir: Path,
) -> None:
    validate_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    summary = dict(a2_result["summary"])
    summary["a_vs_a2_incremental_status"] = incremental["status"]
    (output_dir / "summary.json").write_text(
        json.dumps(json_safe(summary), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8",
    )
    a2_result["security_attribution"].to_csv(output_dir / "security_attribution.csv", index=False, lineterminator="\n")
    _concat_tables(a2_result["time_attribution"], "period_type").to_csv(
        output_dir / "time_attribution.csv", index=False, lineterminator="\n",
    )
    a2_result["rank_bucket_attribution"].to_csv(output_dir / "rank_bucket_attribution.csv", index=False, lineterminator="\n")
    _concat_tables({"sector": a2_result["sector_attribution"], "industry": a2_result["industry_attribution"]}, "group_type").to_csv(
        output_dir / "group_attribution.csv", index=False, lineterminator="\n",
    )
    drawdown_tables = {}
    for diagnostic in a2_result["drawdown_window_attribution"]:
        for dimension in ("security", "sector", "rank_bucket"):
            drawdown_tables[f"{diagnostic['episode_id']}:{dimension}"] = diagnostic[dimension]
    _concat_tables(drawdown_tables, "episode_dimension").to_csv(
        output_dir / "drawdown_window_attribution.csv", index=False, lineterminator="\n",
    )
    incremental["aligned"].to_csv(output_dir / "incremental_a_vs_a2_attribution.csv", index=False, lineterminator="\n")
    reconciliation = {
        "attribution": {key: value for key, value in a2_result["reconciliation"].items() if key != "daily"},
        "incremental": {key: value for key, value in incremental["identity"].items() if key != "daily"},
    }
    (output_dir / "reconciliation.json").write_text(
        json.dumps(json_safe(reconciliation), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8",
    )
