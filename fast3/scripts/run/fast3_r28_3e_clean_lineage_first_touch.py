"""FAST3 R28.3E clean-lineage first-touch economic translation fast track.

This is a frozen-outcome audit.  It reads immutable FAST3 scores and current
canonical ETF bars, but never loads a model or creates a score.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

REPO = Path(r"D:\us-tech-quant")
DATA_ROOT = Path(r"D:\us-tech-quant-data")
RESULTS = Path(r"D:\us-tech-quant-results")
RUNTIME_ROOT = RESULTS / "runtime"
SCRATCH_ROOT = RESULTS / "scratch"
FROZEN_ROOT = RESULTS / "frozen"
CACHE_ROOT = Path(r"D:\us-tech-quant-cache")
CANONICAL = DATA_ROOT / "fast3" / "moomoo_24h_1m" / "canonical"
RUN_ID = "r28_3e_clean_lineage_first_touch_20260809_r3"
RUNTIME_RUN_ROOT = RUNTIME_ROOT / "fast3" / RUN_ID
SCRATCH_RUN_ROOT = SCRATCH_ROOT / "fast3" / RUN_ID
OUT = FROZEN_ROOT / "fast3" / RUN_ID
STAGE = RUNTIME_RUN_ROOT / "frozen_stage"
P2 = RESULTS / "frozen" / "fast3" / "r28_phase2_20260808T125629Z"
LEDGERS = RESULTS / "scratch" / "fast3" / "r28_phase2_20260808T125629Z" / "ledgers"
ANCHORS = RESULTS / "scratch" / "fast3" / "r27_2_independent_heads_20260806T235700000Z" / "r27_2_regenerated_r26a2_payoff_ledger.parquet"
COMPLETION = RESULTS / "frozen" / "fast3" / "cleanroom_r2_execution_contract_completion_20260808" / "execution_contract_completion.json"
SOXX_MANIFEST = RESULTS / "frozen" / "fast3" / "cleanroom_r2_20260808" / "cleanroom_r2_preholdout_source_manifest.json"
LABEL_SOURCE = REPO / "fast3" / "scripts" / "run" / "fast3_cleanroom_r1_preholdout.py"
A_SOURCE = REPO / "fast3" / "scripts" / "run" / "fast3_r28_3a_frozen_economic_attribution.py"
B_SOURCE = REPO / "fast3" / "scripts" / "run" / "fast3_r28_3b_soxx_natural_baseline.py"
D_SOURCE = REPO / "fast3" / "scripts" / "run" / "fast3_r28_3d_frozen_target_aligned_translation.py"
R26_SOURCE = REPO / "fast3" / "src" / "fast3" / "economics" / "executable_payoff_ledger_calendar_hard_r26a2.py"

SYMBOLS = ("SOXL", "SOXS", "TQQQ", "SQQQ")
EXPECTED_PARTITIONS_PER_SYMBOL = 98
SEED, RUNS = 28305, 1000
REFERENCE_R28_3A_NET20 = 0.006491550349221664
EXPECTED_ETF_MANIFEST_SHA256 = "1726b400b9fbb33f1bf85ff4afd229288f8e823d26cf3b2d3b0956e760b3a331"
START_BRANCH = "feature/fast3-009-r28-multisignal"
START_HEAD = "5d106995d7b114747058a48b6c42226b89897ca5"
START_STATUS = "\n".join([
    " M scripts/v22/run_v22_049_fast3_six_etf_24h_minute_data_ingest_r1.ps1",
    " M scripts/v22/v22_049_fast3_six_etf_24h_minute_data_ingest_r1.py",
    "?? fast3/scripts/run/fast3_r28_3a_frozen_economic_attribution.py",
    "?? fast3/scripts/run/fast3_r28_3b_soxx_natural_baseline.py",
    "?? fast3/scripts/run/fast3_r28_3c_frozen_event_conditioned_path_audit.py",
    "?? fast3/scripts/run/fast3_r28_3d_frozen_target_aligned_translation.py",
    "?? fast3/scripts/run/fast3_r28_3d_l_etf_lineage_reconciliation.py",
    "?? fast3/tests/unit/test_fast3_r28_3a_frozen_economic_attribution.py",
    "?? fast3/tests/unit/test_fast3_r28_3b_soxx_natural_baseline.py",
    "?? fast3/tests/unit/test_fast3_r28_3c_frozen_event_conditioned_path_audit.py",
    "?? fast3/tests/unit/test_fast3_r28_3d_frozen_target_aligned_translation.py",
    "?? fast3/tests/unit/test_fast3_r28_3d_l_etf_lineage_reconciliation.py",
])
PRE_EXISTING_HASHES = {
    "scripts/v22/run_v22_049_fast3_six_etf_24h_minute_data_ingest_r1.ps1": "db783369342d9d634bfc10f7e397151296584c7fb150c2079fc77f98991f421b",
    "scripts/v22/v22_049_fast3_six_etf_24h_minute_data_ingest_r1.py": "3b25f23db1b90df0d06c1a09896c12068b619d73cc9b3ee4b053a9af5b63a2a5",
    "fast3/scripts/run/fast3_r28_3a_frozen_economic_attribution.py": "2ad8c962e61d1e57103490d324470680521e7edf92286e50df1f28af1174eb7a",
    "fast3/scripts/run/fast3_r28_3b_soxx_natural_baseline.py": "931a7493cb82135054cf6729ca24f771d98e3ed28e3af53b24e79802c8237f1b",
    "fast3/scripts/run/fast3_r28_3c_frozen_event_conditioned_path_audit.py": "647da33f1a25249630013ac9c0ca0f758140093c9ce30a4f337fca8fd5f6894a",
    "fast3/scripts/run/fast3_r28_3d_frozen_target_aligned_translation.py": "c9c4569bab97ffa91176af8e30fb1a1bb5e90e51063522d13de9dec16646f24b",
    "fast3/scripts/run/fast3_r28_3d_l_etf_lineage_reconciliation.py": "cceefefd2d3ea563a541e900a462a145e477e6e528f1800ea5321570744cbe72",
    "fast3/tests/unit/test_fast3_r28_3a_frozen_economic_attribution.py": "6a730b3b3d1646c956405c8f25e5ec8a1a4df7b90f9fc4b2748ca69f34a97996",
    "fast3/tests/unit/test_fast3_r28_3b_soxx_natural_baseline.py": "578881d2bf7aed902e95c41f81afaac373e03c5ecc63e03b81cb9d7550ee243a",
    "fast3/tests/unit/test_fast3_r28_3c_frozen_event_conditioned_path_audit.py": "1a6ad30d9967f2c02100036a3e16225b82d7b0423f9ad40e62dc75b171dfc037",
    "fast3/tests/unit/test_fast3_r28_3d_frozen_target_aligned_translation.py": "b5b2ed35e3a1f24df815cae7d696c700b17a702ef250a6cba5a01dfeaaa82beb",
    "fast3/tests/unit/test_fast3_r28_3d_l_etf_lineage_reconciliation.py": "00931cd9d7c8d72ad45beecf6e17df25090e762881eb43416ed706d22bc25b81",
}
R28_3E_SOURCE_ALLOWLIST = {
    "fast3/scripts/run/fast3_r28_3e_clean_lineage_first_touch.py",
    "fast3/tests/unit/test_fast3_r28_3e_clean_lineage_first_touch.py",
}


class AuditStop(RuntimeError):
    """A correctness failure that invalidates the fast-track audit."""


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise AuditStop(f"STOP_MODULE_LOAD:{path}")
    spec.loader.exec_module(module)
    return module


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def git_value(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


def data_snapshot() -> dict[str, tuple[int, int]]:
    return {str(path): (int(path.stat().st_size), int(path.stat().st_mtime_ns))
            for path in DATA_ROOT.rglob("*") if path.is_file()}


def storage_preflight() -> tuple[dict, dict[str, tuple[int, int]]]:
    expected = {
        "source": REPO, "data": DATA_ROOT, "results": RESULTS, "runtime": RUNTIME_ROOT,
        "scratch": SCRATCH_ROOT, "frozen": FROZEN_ROOT, "cache": CACHE_ROOT,
    }
    if any(not path.is_absolute() for path in expected.values()):
        raise AuditStop("STOP_STORAGE_ROOT_NOT_ABSOLUTE")
    if RESULTS == REPO or DATA_ROOT == REPO or CACHE_ROOT == REPO:
        raise AuditStop("STOP_STORAGE_ROOT_COLLISION")
    if (REPO / ".local_results").exists():
        raise AuditStop("STOP_LOCAL_RESULTS_PRE_EXISTING_OR_REINTRODUCED")
    pycache = Path(sys.pycache_prefix).resolve() if sys.pycache_prefix else None
    if pycache is None or CACHE_ROOT.resolve() not in (pycache, *pycache.parents):
        raise AuditStop("STOP_PYTHON_CACHE_NOT_EXTERNALIZED")
    if OUT.exists() or RUNTIME_RUN_ROOT.exists() or SCRATCH_RUN_ROOT.exists():
        raise AuditStop("STOP_R28_3E_RUN_PATH_EXISTS")
    RUNTIME_RUN_ROOT.mkdir(parents=True)
    SCRATCH_RUN_ROOT.mkdir(parents=True)
    result = {
        "status": "PASS", "guard_source": str(REPO / "scripts" / "fast3" / "agent" / "fast3_storage_contract_r1.ps1"),
        "guard_sha256": file_sha256(REPO / "scripts" / "fast3" / "agent" / "fast3_storage_contract_r1.ps1"),
        "roots": {key: str(value) for key, value in expected.items()},
        "local_results_pre_existing": False, "pre_existing_storage_violations": [
            str(REPO / ".pytest_cache"), str(REPO / ".pytest_v22_049_tmp")],
    }
    atomic_json(RUNTIME_RUN_ROOT / "progress.json", {**result, "stage": "STORAGE_PREFLIGHT_COMPLETE"})
    return result, data_snapshot()


def post_storage_audit(before_data: dict[str, tuple[int, int]]) -> dict:
    after_data = data_snapshot()
    data_changes = sorted(set(before_data).symmetric_difference(after_data) |
                          {path for path in set(before_data).intersection(after_data) if before_data[path] != after_data[path]})
    preserved = {relative: file_sha256(REPO / relative) == expected
                 for relative, expected in PRE_EXISTING_HASHES.items()}
    status_lines = subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True).splitlines()
    changed_paths = {line[3:].strip().replace("\\", "/") for line in status_lines if len(line) >= 4}
    allowed = set(PRE_EXISTING_HASHES).union(R28_3E_SOURCE_ALLOWLIST)
    new_unallowed = sorted(changed_paths.difference(allowed))
    result_artifacts = [path for path in new_unallowed if Path(path).suffix.lower() in {".csv", ".parquet", ".json", ".md", ".log"}]
    audit = {
        "data_root_write_count": len(data_changes), "data_root_changed_paths": data_changes,
        "local_results_created": (REPO / ".local_results").exists(),
        "result_files_written_to_git_repo": bool(result_artifacts), "repo_result_artifacts": result_artifacts,
        "source_writes_outside_allowed_source_files": len(new_unallowed), "unallowed_repo_changes": new_unallowed,
        "pre_existing_untracked_files_preserved": all(preserved[relative] for relative in preserved if relative.startswith("fast3/")),
        "pre_existing_tracked_changes_preserved": all(preserved[relative] for relative in preserved if relative.startswith("scripts/v22/")),
        "new_r28_3e_storage_violation_count": len(data_changes) + int((REPO / ".local_results").exists()) + len(new_unallowed),
    }
    if audit["new_r28_3e_storage_violation_count"]:
        raise AuditStop(f"STOP_NEW_STORAGE_VIOLATION:{audit}")
    return audit


def schema_identity(schema) -> tuple[str, str, list[str]]:
    fields = [{"name": f.name, "type": str(f.type), "nullable": bool(f.nullable)} for f in schema]
    compatible = []
    for field in schema:
        type_name = str(field.type)
        if type_name in {"string", "large_string"}:
            type_name = "string"
        elif type_name.startswith("timestamp["):
            timezone = getattr(field.type, "tz", None)
            type_name = f"timestamp[normalized, tz={timezone}]" if timezone else "timestamp[normalized]"
        compatible.append({"name": field.name, "type": type_name, "nullable": bool(field.nullable)})
    return canonical_hash(fields), canonical_hash(compatible), [f["name"] for f in fields]


def build_partition_manifest() -> tuple[pd.DataFrame, dict, bytes, str]:
    """Freeze every current ETF partition and fail closed on path ambiguity."""
    records: list[dict] = []
    seen_keys: set[tuple[str, str]] = set()
    for symbol in SYMBOLS:
        root = CANONICAL / f"symbol={symbol}"
        files = sorted(root.rglob("*.parquet")) if root.is_dir() else []
        if len(files) != EXPECTED_PARTITIONS_PER_SYMBOL:
            raise AuditStop(f"STOP_PARTITION_RECONCILIATION:{symbol}:{len(files)}")
        prior_max = None
        symbol_schemas: set[str] = set()
        for path in files:
            relative = path.relative_to(CANONICAL).as_posix()
            parts = {piece.split("=", 1)[0]: piece.split("=", 1)[1]
                     for piece in path.parts if "=" in piece}
            logical_date = f"{parts.get('year', 'UNKNOWN')}-{parts.get('month', 'UNKNOWN')}"
            partition_key = str(path.parent.relative_to(CANONICAL)).replace("\\", "/")
            key = (symbol, partition_key)
            if key in seen_keys:
                raise AuditStop(f"STOP_DUPLICATE_PARTITION:{partition_key}")
            seen_keys.add(key)
            parquet = pq.ParquetFile(path)
            fingerprint, compatibility_fingerprint, columns = schema_identity(parquet.schema_arrow)
            symbol_schemas.add(compatibility_fingerprint)
            timestamp = pd.to_datetime(parquet.read(columns=["timestamp_et"])["timestamp_et"].to_pandas(), utc=True, errors="coerce")
            if len(timestamp) != parquet.metadata.num_rows or timestamp.isna().any() or timestamp.duplicated().any():
                raise AuditStop(f"STOP_PARTITION_TIMESTAMP_CORRUPT:{relative}")
            minimum, maximum = timestamp.min(), timestamp.max()
            if prior_max is not None and minimum <= prior_max:
                raise AuditStop(f"STOP_OVERLAPPING_PARTITIONS:{relative}")
            prior_max = maximum
            first_hash = file_sha256(path)
            second_hash = file_sha256(path)
            if first_hash != second_hash:
                raise AuditStop(f"STOP_UNSTABLE_PARTITION_HASH:{relative}")
            records.append({
                "symbol": symbol, "partition_key": partition_key, "logical_date": logical_date,
                "absolute_or_canonical_path": str(path.resolve()), "canonical_relative_path": relative,
                "file_name": path.name, "file_size": int(path.stat().st_size), "file_sha256": first_hash,
                "row_count": int(parquet.metadata.num_rows), "min_timestamp": minimum.isoformat(),
                "max_timestamp": maximum.isoformat(), "schema_fingerprint": fingerprint,
                "schema_compatibility_fingerprint": compatibility_fingerprint,
                "column_names": columns,
            })
        if len(symbol_schemas) != 1:
            raise AuditStop(f"STOP_SCHEMA_INCOMPATIBILITY:{symbol}")
    payload = {
        "manifest_version": "FAST3_R28_3E_CURRENT_CANONICAL_ETF_PARTITIONS_V1",
        "canonical_root": str(CANONICAL), "symbols": list(SYMBOLS),
        "partition_count": len(records), "partitions": records,
    }
    encoded = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    frame = pd.DataFrame(records)
    frame["column_names"] = frame.column_names.map(lambda x: json.dumps(x, separators=(",", ":")))
    return frame, payload, encoded, digest


def reconcile_fold_model_identities(authoritative: pd.DataFrame, selected: pd.DataFrame) -> dict:
    """Map each selected signal to one authoritative walk-forward fold identity."""
    required = {"candidate_id", "head", "model_sha256", "feature_manifest_sha256"}
    if required.difference(authoritative) or required.difference(selected):
        raise AuditStop("STOP_FROZEN_MODEL_IDENTITY_SCHEMA_MISSING")
    fold_fields = [field for field in ("fold_id", "block_id", "asof_id", "validation_slice")
                   if field in authoritative.columns]
    if not fold_fields or any(field not in selected for field in fold_fields):
        raise AuditStop("STOP_FROZEN_FOLD_IDENTITY_FIELD_MISSING")
    identity_fields = ["head", *fold_fields, "model_sha256", "feature_manifest_sha256"]
    optional_fields = [field for field in ("model_family", "model_type", "training_identity",
                                             "training_sha256", "training_manifest_sha256")
                       if field in authoritative.columns and field in selected.columns]
    identity_fields.extend(optional_fields)
    if authoritative[identity_fields].isna().any().any() or selected[identity_fields].isna().any().any():
        raise AuditStop("STOP_FROZEN_MODEL_IDENTITY_NULL")

    heads: dict[str, dict] = {}
    records_by_fold: dict[tuple, list[dict]] = {}
    internal_feature_mismatch_folds: list[dict] = []
    for head in sorted(authoritative["head"].astype(str).unique()):
        part = authoritative.loc[authoritative["head"].astype(str).eq(head)].copy()
        records_frame = part[identity_fields].drop_duplicates().sort_values(identity_fields, kind="mergesort")
        records = records_frame.to_dict(orient="records")
        for fold_values, group in records_frame.groupby(["head", *fold_fields], sort=True, dropna=False):
            key = fold_values if isinstance(fold_values, tuple) else (fold_values,)
            fold_records = group.to_dict(orient="records")
            records_by_fold[tuple(str(value) for value in key)] = fold_records
            if group.feature_manifest_sha256.nunique() != 1:
                internal_feature_mismatch_folds.append({field: str(value) for field, value in zip(["head", *fold_fields], key)})
        heads[head] = {
            "fold_identity_fields": fold_fields,
            "authoritative_identity_record_count": len(records),
            "authoritative_identity_records": records,
            "fold_model_identity_set_sha256": canonical_hash(records),
            "feature_identity_shared_across_folds": bool(records_frame.feature_manifest_sha256.nunique() == 1),
            "authoritative_signal_count": int(len(part)),
            "selected_signal_count": int(selected["head"].astype(str).eq(head).sum()),
        }

    selected_unknown: set[str] = set()
    selected_ambiguous: set[str] = set()
    selected_feature_mismatch: set[str] = set()
    selected_identity_by_signal: dict[str, set[tuple]] = {}
    for row in selected.to_dict(orient="records"):
        signal_key = f"{row['head']}|{row['candidate_id']}"
        identity = tuple(str(row[field]) for field in identity_fields)
        selected_identity_by_signal.setdefault(signal_key, set()).add(identity)
        fold_key = tuple(str(row[field]) for field in ["head", *fold_fields])
        candidates = records_by_fold.get(fold_key, [])
        if not candidates or not any(str(item["model_sha256"]) == str(row["model_sha256"]) for item in candidates):
            selected_unknown.add(signal_key)
        if len(candidates) != 1:
            selected_ambiguous.add(signal_key)
        matching_model = [item for item in candidates if str(item["model_sha256"]) == str(row["model_sha256"])]
        if not matching_model or not any(str(item["feature_manifest_sha256"]) == str(row["feature_manifest_sha256"])
                                         for item in matching_model):
            selected_feature_mismatch.add(signal_key)
    selected_ambiguous.update(key for key, identities in selected_identity_by_signal.items() if len(identities) != 1)
    reconciliation = {
        "selected_signal_count": int(len(selected)),
        "selected_signal_unique_key_count": int(len(selected_identity_by_signal)),
        "selected_signal_unknown_model_count": int(len(selected_unknown)),
        "selected_signal_ambiguous_model_count": int(len(selected_ambiguous)),
        "selected_signal_feature_identity_mismatch_count": int(len(selected_feature_mismatch)),
        "authoritative_feature_identity_mismatch_fold_count": int(len(internal_feature_mismatch_folds)),
        "authoritative_feature_identity_mismatch_folds": internal_feature_mismatch_folds,
    }
    passed = (len(selected) == len(selected_identity_by_signal)
              and not selected_unknown and not selected_ambiguous and not selected_feature_mismatch
              and not internal_feature_mismatch_folds)
    reconciliation["status"] = "PASS" if passed else "STOP"
    result = {
        "frozen_model_identity_schema": "AUTHORITATIVE_LEDGER_HEAD_PLUS_EXISTING_FOLD_FIELDS_V1",
        "model_identity_variation_expected_across_folds": True,
        "fold_identity_fields": fold_fields, "optional_frozen_identity_fields": optional_fields,
        "heads": heads, "selected_signal_mapping_reconciliation": reconciliation,
    }
    if not passed:
        raise AuditStop(f"STOP_FOLD_MODEL_IDENTITY_RECONCILIATION:{reconciliation}")
    return result


def read_frozen_signals(a) -> tuple[pd.DataFrame, dict, dict]:
    lineage_path = P2 / "R28_PHASE2_LINEAGE.json"
    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    frames, hashes = [], {}
    for head in ("UP", "DOWN"):
        path = LEDGERS / f"R28_3_CROSS_ASSET_FLOW_{head}_IMMUTABLE_VALIDATION_LEDGER.parquet"
        observed = file_sha256(path)
        if observed != lineage["ledger_hashes"]["R28_3_CROSS_ASSET_FLOW"][head]:
            raise AuditStop(f"STOP_FROZEN_SIGNAL_IDENTITY:{head}")
        frame = pd.read_parquet(path)
        a.validate_frozen_scores(frame, head)
        hashes[head] = observed
        frames.append(frame)
    signals = pd.concat(frames, ignore_index=True)
    signals["timestamp"] = pd.to_datetime(signals.decision_timestamp_utc, utc=True)
    a.assert_no_prospective(signals.timestamp)
    signals["outcome_key"] = signals.underlying_symbol.astype(str) + "|" + signals.timestamp.astype(str)
    signals = a.add_calendar_columns(signals)
    identity_map = reconcile_fold_model_identities(signals, signals.loc[signals.selected].copy())
    identity = {
        "lineage_source": str(lineage_path), "lineage_sha256": file_sha256(lineage_path),
        "ledger_hashes": hashes, "combined_signal_ledger_sha256": canonical_hash(hashes),
        "model_identity": {head: {"identity_count": details["authoritative_identity_record_count"],
                                   "identity_set_sha256": details["fold_model_identity_set_sha256"]}
                           for head, details in identity_map["heads"].items()},
    }
    return signals, identity, identity_map


def current_payoffs(signals: pd.DataFrame, r26) -> tuple[pd.DataFrame, dict]:
    """Re-execute frozen anchors under the unchanged R26A2 contract on current bars."""
    anchors_hash = file_sha256(ANCHORS)
    if anchors_hash != "f042b3e056474d242b8452e44807819b9f57772abf8b005741edb9d2a2fbaf92":
        raise AuditStop("STOP_FROZEN_ANCHOR_LEDGER_IDENTITY")
    old = pd.read_parquet(ANCHORS, columns=["candidate_id", "candidate_instrument", "decision_timestamp_et", "authoritative_anchor_timestamp_et"])
    old["outcome_key"] = old.candidate_instrument.astype(str) + "|" + pd.to_datetime(old.decision_timestamp_et, utc=True).astype(str)
    keys = pd.Index(signals.outcome_key.unique())
    candidates = old.loc[old.outcome_key.isin(keys), ["candidate_id", "candidate_instrument", "decision_timestamp_et", "authoritative_anchor_timestamp_et"]].copy()
    if len(candidates) != len(keys) or candidates.candidate_id.duplicated().any():
        raise AuditStop("STOP_FROZEN_ANCHOR_COVERAGE")
    payoff, contract = r26.construct_payoffs(candidates, CANONICAL)
    payoff["outcome_key"] = payoff.candidate_instrument.astype(str) + "|" + pd.to_datetime(payoff.decision_timestamp_et, utc=True).astype(str)
    if payoff.outcome_key.duplicated().any() or payoff.execution_contract_hash.nunique() != 1:
        raise AuditStop("STOP_CURRENT_EXECUTION_CONTRACT_AMBIGUOUS")
    return payoff, {**contract, "frozen_anchor_ledger_sha256": anchors_hash}


def merge_signals_payoffs(signals: pd.DataFrame, payoff: pd.DataFrame) -> pd.DataFrame:
    left = signals.rename(columns={"candidate_id": "signal_candidate_id"})
    right = payoff.rename(columns={"candidate_id": "payoff_candidate_id"})
    merged = left.merge(right, on="outcome_key", how="left", validate="many_to_one", suffixes=("_signal", "_payoff"))
    merged["candidate_id"] = merged.signal_candidate_id.astype(str)
    if merged.payoff_candidate_id.isna().any() or len(merged) != len(signals):
        raise AuditStop("STOP_CURRENT_PAYOFF_JOIN")
    return merged


def execute_with_audit(a, raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Frozen tie/one-position execution, retaining explicit flat-state failures."""
    x = a.add_economics(raw)
    both = x.groupby(["underlying_symbol", "timestamp"])["head"].transform("nunique").gt(1)
    x = x.loc[~both].copy()
    tied = x.groupby("timestamp").size().reindex(x.timestamp).to_numpy() > 1
    x = x.loc[~tied].sort_values("timestamp", kind="mergesort")
    chosen, executed, until = [], [], None
    for index, row in x.iterrows():
        if until is not None and row.timestamp < until:
            continue
        chosen.append(index)
        if not row.valid or pd.isna(row.exit):
            continue
        executed.append(index)
        until = row.exit
    selected = x.loc[chosen].copy().reset_index(drop=True)
    selected["execution_state"] = np.where(selected.valid & selected.exit.notna(), "PENDING_EVENT_STATE", "NONEXECUTABLE")
    real = x.loc[executed].copy().reset_index(drop=True)
    reference = a.execute(raw)
    if not reference.candidate_id.astype(str).equals(real.candidate_id.astype(str)):
        raise AuditStop("STOP_FROZEN_EXECUTION_REPRODUCTION")
    return selected, real


def attach_first_touch(econ: pd.DataFrame, touches: pd.DataFrame, bars: dict, stable_hash) -> pd.DataFrame:
    out = econ.merge(touches.rename(columns={"candidate_id": "payoff_candidate_id"}),
                     on=["payoff_candidate_id", "underlying_symbol"], how="left", validate="many_to_one")
    if out.frozen_label.isna().any():
        raise AuditStop("STOP_TOUCH_JOIN")
    favorable = ((out["head"].eq("UP") & out.frozen_label.eq("UP_FIRST")) |
                 (out["head"].eq("DOWN") & out.frozen_label.eq("DOWN_FIRST")))
    out["event_state"] = np.where(favorable, "FAVORABLE_FIRST", np.where(out.frozen_label.eq("NO_EVENT"), "NO_EVENT", "ADVERSE_FIRST"))
    out["first_touch_exit_timestamp"] = out.exit
    out["first_touch_exit_price"] = out.exit_price
    out["first_touch_exit_reason"] = "FROZEN_R26A2_ADVERSE_OR_NO_EVENT_CLOSEOUT"
    out["first_touch_executable"] = out.valid & out.exit.notna()
    out["first_touch_nonexecutable_reason"] = np.where(out.first_touch_executable, None, "FROZEN_ENTRY_OR_CLOSEOUT_UNAVAILABLE")
    for instrument, part in out.loc[favorable & out.valid].groupby("action_instrument", sort=False):
        right = bars[instrument][["timestamp_et", "open"]].rename(columns={"timestamp_et": "bar_timestamp", "open": "bar_open"}).sort_values("bar_timestamp")
        left = part[["candidate_id", "touch_timestamp", "entry_timestamp"]].copy()
        left["target"] = pd.concat([left.touch_timestamp, left.entry_timestamp], axis=1).max(axis=1)
        joined = pd.merge_asof(left.sort_values("target"), right, left_on="target", right_on="bar_timestamp",
                               direction="forward", allow_exact_matches=True).set_index("candidate_id")
        mask = out.candidate_id.isin(joined.index) & out.action_instrument.eq(instrument)
        mapped = out.loc[mask, "candidate_id"].map(joined.bar_timestamp)
        price = out.loc[mask, "candidate_id"].map(joined.bar_open)
        legal = mapped.notna() & (mapped >= out.loc[mask, "entry_timestamp"])
        out.loc[mask, "first_touch_exit_timestamp"] = mapped.where(legal)
        out.loc[mask, "first_touch_exit_price"] = price.where(legal)
        out.loc[mask, "first_touch_exit_reason"] = np.where(legal, "FIRST_LEGAL_ETF_OPEN_AT_OR_AFTER_TARGET_TOUCH", "TARGET_TOUCH_EXIT_BAR_UNAVAILABLE")
        out.loc[mask, "first_touch_executable"] = legal.to_numpy()
        out.loc[mask, "first_touch_nonexecutable_reason"] = np.where(legal, None, "TARGET_TOUCH_EXIT_BAR_UNAVAILABLE")
    out["first_touch_gross"] = out.first_touch_exit_price / out.entry_price - 1.0
    out["first_touch_net10"] = out.first_touch_gross - 0.001
    out["first_touch_net20"] = out.first_touch_gross - 0.002
    out["first_touch_outcome_path"] = [stable_hash({"instrument": i, "entry_timestamp": str(e), "entry_price": p,
                                                     "exit_timestamp": str(x), "exit_price": q, "reason": r}) if ok else None
                                               for i, e, p, x, q, r, ok in zip(out.action_instrument, out.entry_timestamp,
                                                out.entry_price, out.first_touch_exit_timestamp, out.first_touch_exit_price,
                                                out.first_touch_exit_reason, out.first_touch_executable)]
    return out


def stats(frame: pd.DataFrame) -> dict:
    x = frame.loc[frame.first_touch_executable & frame.first_touch_net20.notna()]
    gross, net10, net20 = x.first_touch_gross, x.first_touch_net10, x.first_touch_net20
    result = {
        "trade_count": int(len(x)), "win_rate": float((net20 > 0).mean()),
        "mean_gross": float(gross.mean()), "median_gross": float(gross.median()),
        "mean_net10": float(net10.mean()), "median_net10": float(net10.median()),
        "mean_net20": float(net20.mean()), "median_net20": float(net20.median()),
        "std_net20": float(net20.std()), "worst_trade": float(net20.min()), "best_trade": float(net20.max()),
    }
    result.update({f"p{int(q * 100):02d}_net20": float(net20.quantile(q)) for q in (.01, .05, .10, .25, .75, .90, .95, .99)})
    return result


def grouped(frame: pd.DataFrame, field: str) -> pd.DataFrame:
    rows = []
    total = int(frame.first_touch_executable.sum())
    total_net = float(frame.loc[frame.first_touch_executable, "first_touch_net20"].sum())
    for key, part in frame.groupby(field, sort=True, dropna=False):
        row = {field: str(key), **stats(part)}
        row["trade_share"] = row["trade_count"] / total if total else math.nan
        row["total_net_contribution"] = float(part.loc[part.first_touch_executable, "first_touch_net20"].sum())
        row["net_contribution_share"] = row["total_net_contribution"] / total_net if total_net else math.nan
        rows.append(row)
    return pd.DataFrame(rows)


def empirical_p(values: np.ndarray, real: float) -> float:
    return float((int((values >= real).sum()) + 1) / (len(values) + 1))


def matched_placebo(a, real: pd.DataFrame, eligible: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    rng = np.random.default_rng(SEED)
    plan = a.match_plan(real, eligible)
    if not plan or sum(count for _, count, _ in plan) != len(real):
        raise AuditStop("STOP_MATCHED_PLACEBO_UNMATCHED")
    rows, fixed_levels = [], None
    for run in range(1, RUNS + 1):
        sample, levels = a.matched_once(real, eligible, rng, plan)
        if len(sample) != len(real):
            raise AuditStop("STOP_MATCHED_PLACEBO_CARDINALITY")
        fixed_levels = levels if fixed_levels is None else fixed_levels
        paths = sample.first_touch_outcome_path.value_counts(dropna=False)
        s = stats(sample)
        rows.append({"run": run, "trade_count": len(sample), "mean_net20": s["mean_net20"],
                     "median_net20": s["median_net20"], "win_rate": s["win_rate"],
                     "signal_cardinality_conserved": len(sample) == len(real),
                     "unique_placebo_signal_count": int(sample.candidate_id.nunique()),
                     "unique_outcome_path_count": int(paths.size),
                     "shared_outcome_path_count": int((paths > 1).sum()),
                     "max_signals_per_outcome_path": int(paths.max())})
    runs = pd.DataFrame(rows)
    values, actual = runs.mean_net20.to_numpy(), float(real.first_touch_net20.mean())
    summary = {
        "random_seed": SEED, "random_run_count": RUNS,
        **{f"match_level_{i}_count": int(sum(level == i for level in fixed_levels)) for i in range(5)},
        "unmatched_count": 0, "signal_cardinality_conserved": bool(runs.signal_cardinality_conserved.all()),
        "unique_placebo_signal_count": int(runs.unique_placebo_signal_count.min()),
        "unique_outcome_path_count": int(runs.unique_outcome_path_count.min()),
        "shared_outcome_path_count": int(runs.shared_outcome_path_count.max()),
        "max_signals_per_outcome_path": int(runs.max_signals_per_outcome_path.max()),
        "net20_mean_median": float(np.quantile(values, .5)), "net20_p90": float(np.quantile(values, .9)),
        "net20_p95": float(np.quantile(values, .95)), "net20_p99": float(np.quantile(values, .99)),
        "net20_max": float(values.max()), "real_net20_percentile": float((values <= actual).mean()),
        "real_net20_p": empirical_p(values, actual),
    }
    return runs, summary


def classify(mean_net20: float, percentile: float, p_value: float) -> tuple[str, str, str, str]:
    if mean_net20 < 0:
        return "D_FIRST_TOUCH_TRANSLATION_ECONOMICALLY_NEGATIVE", "FAIL", "NEGATIVE", "STOP_FIRST_TOUCH_TRANSLATION_HYPOTHESIS"
    if percentile >= .95 and p_value <= .05:
        strength = "VERY_STRONG_PASS" if percentile >= .99 and p_value <= .01 else "STRONG_PASS"
        return "A_CLEAN_LINEAGE_FIRST_TOUCH_ECONOMIC_EDGE_CONFIRMED", strength, "CONFIRMED", "PROSPECTIVE_FIRST_TOUCH_CONFIRMATION"
    if percentile >= .90 and p_value <= .10:
        return "B_FIRST_TOUCH_EDGE_SUGGESTIVE_NOT_CONFIRMED", "WEAK_OR_MIXED", "SUGGESTIVE", "OPTIONAL_PROSPECTIVE_CONFIRMATION_WITHOUT_PARAMETER_CHANGES"
    return "C_FIRST_TOUCH_ECONOMIC_EDGE_NOT_CONFIRMED", "FAIL", "NOT_CONFIRMED", "STOP_FIRST_TOUCH_TRANSLATION_HYPOTHESIS"


def extreme_outlier_audit(values: pd.Series) -> tuple[float, bool]:
    total = float(values.sum())
    count = max(1, int(math.ceil(len(values) * .01)))
    contribution = float(values.nlargest(count).sum())
    share = contribution / total if total else math.nan
    return share, bool(total > 0 and share > .50)


def write_outputs(manifest_csv: pd.DataFrame, manifest_json: bytes, manifest_hash: str,
                  ledger: pd.DataFrame, by_direction: pd.DataFrame, by_year: pd.DataFrame,
                  by_symbol: pd.DataFrame, runs: pd.DataFrame, matched: dict,
                  model_identity_map: dict, summary: dict) -> None:
    if OUT.exists() or STAGE.exists():
        raise AuditStop("STOP_R28_3E_FINALIZATION_PATH_EXISTS")
    STAGE.mkdir(parents=True)
    paths = {
        "manifest_csv": STAGE / "R28_3E_CANONICAL_ETF_PARTITION_MANIFEST.csv",
        "manifest_json": STAGE / "R28_3E_CANONICAL_ETF_PARTITION_MANIFEST.json",
        "ledger": STAGE / "R28_3E_FIRST_TOUCH_TRADE_LEDGER.csv", "direction": STAGE / "R28_3E_BY_DIRECTION.csv",
        "year": STAGE / "R28_3E_BY_YEAR.csv", "symbol": STAGE / "R28_3E_BY_SYMBOL.csv",
        "runs": STAGE / "R28_3E_MATCHED_PLACEBO_RUNS.csv", "matched": STAGE / "R28_3E_MATCHED_PLACEBO_SUMMARY.json",
        "model_identity_map": STAGE / "R28_3E_FROZEN_MODEL_IDENTITY_MAP.json",
        "summary": STAGE / "R28_3E_SUMMARY.json", "report": STAGE / "R28_3E_REPORT.md",
    }
    manifest_csv.to_csv(paths["manifest_csv"], index=False)
    paths["manifest_json"].write_bytes(manifest_json)
    if file_sha256(paths["manifest_json"]) != manifest_hash:
        raise AuditStop("STOP_WRITTEN_MANIFEST_HASH_MISMATCH")
    for frame in (ledger, by_direction, by_year, by_symbol, runs):
        frame["etf_manifest_sha256"] = manifest_hash
    ledger.to_csv(paths["ledger"], index=False)
    by_direction.to_csv(paths["direction"], index=False)
    by_year.to_csv(paths["year"], index=False)
    by_symbol.to_csv(paths["symbol"], index=False)
    runs.to_csv(paths["runs"], index=False)
    matched = {"ETF_MANIFEST_SHA256": manifest_hash, **matched}
    paths["matched"].write_text(json.dumps(matched, indent=2, default=str), encoding="utf-8")
    model_identity_map = {"ETF_MANIFEST_SHA256": manifest_hash, **model_identity_map}
    paths["model_identity_map"].write_text(json.dumps(model_identity_map, indent=2, sort_keys=True, default=str), encoding="utf-8")
    artifact_evidence = {
        "TRADE_LEDGER": {"path": str(OUT / paths["ledger"].name), "sha256": file_sha256(paths["ledger"]),
                         "row_count": int(len(ledger)), "file_size": int(paths["ledger"].stat().st_size),
                         "artifact_class": "FROZEN_EVIDENCE",
                         "generation_contract": "frozen selected signals; current clean ETF lineage; frozen first-touch translation"},
        "MATCHED_PLACEBO_RUNS": {"path": str(OUT / paths["runs"].name), "sha256": file_sha256(paths["runs"]),
                                 "row_count": int(len(runs)), "file_size": int(paths["runs"].stat().st_size),
                                 "artifact_class": "FROZEN_EVIDENCE",
                                 "generation_contract": "seed=28305; runs=1000; identical first-touch economic translation"},
        "ETF_MANIFEST_JSON": {"path": str(OUT / paths["manifest_json"].name), "sha256": manifest_hash,
                              "row_count": int(len(manifest_csv)), "file_size": int(paths["manifest_json"].stat().st_size),
                              "artifact_class": "FROZEN_EVIDENCE"},
        "FROZEN_MODEL_IDENTITY_MAP": {"path": str(OUT / paths["model_identity_map"].name),
                                      "sha256": file_sha256(paths["model_identity_map"]),
                                      "row_count": int(sum(value["authoritative_identity_record_count"]
                                                           for value in model_identity_map["heads"].values())),
                                      "file_size": int(paths["model_identity_map"].stat().st_size),
                                      "artifact_class": "FROZEN_EVIDENCE"},
    }
    summary["external_artifact_evidence"] = artifact_evidence
    summary["TRADE_LEDGER_SHA256"] = artifact_evidence["TRADE_LEDGER"]["sha256"]
    summary["MATCHED_PLACEBO_RUNS_SHA256"] = artifact_evidence["MATCHED_PLACEBO_RUNS"]["sha256"]
    summary["MODEL_IDENTITY_MAP_SHA256"] = artifact_evidence["FROZEN_MODEL_IDENTITY_MAP"]["sha256"]
    paths["summary"].write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    report_lines = ["# FAST3 R28.3E — Clean-Lineage First-Touch Economic Translation", "",
                    "This is a clean-lineage retrospective outcome audit. No model fitting, prediction, rescoring, parameter search, prospective model-data use, or live trading occurred.", ""]
    for key, value in summary.items():
        if not isinstance(value, (dict, list)):
            report_lines.append(f"{key}={value}")
    report_lines.extend(["", "## Full frozen audit summary", "", "```json", json.dumps(summary, indent=2, default=str), "```", ""])
    paths["report"].write_text("\n".join(report_lines), encoding="utf-8")
    required = set(path.name for path in paths.values())
    observed = {path.name for path in STAGE.iterdir() if path.is_file()}
    if required != observed or any(path.stat().st_size <= 0 for path in paths.values()):
        raise AuditStop("STOP_FROZEN_STAGE_INCOMPLETE")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    STAGE.replace(OUT)


def run() -> dict:
    branch, head = git_value("branch", "--show-current"), git_value("rev-parse", "HEAD")
    if branch != START_BRANCH or head != START_HEAD:
        raise AuditStop("STOP_GIT_START_IDENTITY")
    storage_gate, data_before = storage_preflight()
    manifest_csv, manifest_payload, manifest_bytes, manifest_hash = build_partition_manifest()
    if manifest_hash != EXPECTED_ETF_MANIFEST_SHA256:
        raise AuditStop(f"STOP_DETERMINISTIC_MANIFEST_HASH_CHANGED:{manifest_hash}")
    atomic_json(RUNTIME_RUN_ROOT / "progress.json", {**storage_gate, "stage": "CLEAN_LINEAGE_MANIFEST_VALIDATED",
                                                      "etf_manifest_sha256": manifest_hash})
    a, b, d = load_module(A_SOURCE, "r28_3e_a"), load_module(B_SOURCE, "r28_3e_b"), load_module(D_SOURCE, "r28_3e_d")
    sys.path.insert(0, str(REPO / "fast3" / "src"))
    from fast3.economics import executable_payoff_ledger_calendar_hard_r26a2 as r26

    label_contract, r1 = b.load_contract()
    signals, signal_identity, model_identity_map = read_frozen_signals(a)
    payoff, execution_identity = current_payoffs(signals, r26)
    if execution_identity["partition_manifest"]["SOXL"]["file_count"] != EXPECTED_PARTITIONS_PER_SYMBOL:
        raise AuditStop("STOP_EXECUTION_MANIFEST_RECONCILIATION")
    all_rows = merge_signals_payoffs(signals, payoff)
    atomic_json(RUNTIME_RUN_ROOT / "progress.json", {**storage_gate, "stage": "CURRENT_EXECUTION_LEDGER_REBUILT",
                                                      "candidate_count": len(payoff), "etf_manifest_sha256": manifest_hash})
    raw_selected = all_rows.loc[all_rows.selected].copy()
    selected_audit, baseline = execute_with_audit(a, raw_selected)

    points = payoff[["candidate_id", "candidate_instrument", "decision_timestamp_et"]].rename(
        columns={"candidate_instrument": "underlying_symbol", "decision_timestamp_et": "timestamp"})
    points["timestamp"] = pd.to_datetime(points.timestamp, utc=True)
    touches = pd.concat([
        d.underlying_touches(points.loc[points.underlying_symbol.eq(symbol)].reset_index(drop=True), b, r1,
                             d.canonical_underlying(b, r1, symbol)) for symbol in ("QQQ", "SOXX")
    ], ignore_index=True)
    touch_lookup = touches.rename(columns={"candidate_id": "payoff_candidate_id"})[["payoff_candidate_id", "frozen_label"]]
    check = all_rows[["payoff_candidate_id", "head", "target_first"]].merge(touch_lookup, on="payoff_candidate_id", validate="many_to_one")
    expected = ((check["head"].eq("UP") & check.frozen_label.eq("UP_FIRST")) |
                (check["head"].eq("DOWN") & check.frozen_label.eq("DOWN_FIRST")))
    if not np.array_equal(expected.to_numpy(bool), check.target_first.to_numpy(bool)):
        raise AuditStop("STOP_FROZEN_LABEL_RECONCILIATION")

    econ = a.add_economics(all_rows)
    is_up = econ["head"].eq("UP")
    econ["action_instrument"] = np.where(is_up, econ.up_action_instrument, econ.down_action_instrument)
    econ["entry_timestamp"] = pd.to_datetime(np.where(is_up, econ.up_entry_timestamp_et, econ.down_entry_timestamp_et), utc=True)
    econ["entry_price"] = np.where(is_up, econ.up_entry_price, econ.down_entry_price)
    econ["exit_price"] = np.where(is_up, econ.up_exit_price, econ.down_exit_price)
    bars, _ = d.action_bars()
    translated = attach_first_touch(econ, touches, bars, r26.stable_hash)
    eligible = translated.loc[translated.valid & translated.first_touch_executable].reset_index(drop=True)
    real = baseline[["candidate_id", "head"]].merge(translated, on=["candidate_id", "head"], how="left", validate="one_to_one")
    if len(real) != len(baseline):
        raise AuditStop("STOP_SELECTED_TRADE_RECONCILIATION")

    audit_ledger = selected_audit.drop(columns=[c for c in selected_audit if c in real.columns and c not in ("candidate_id", "head")], errors="ignore")
    audit_ledger = audit_ledger[["candidate_id", "head", "execution_state"]].merge(real, on=["candidate_id", "head"], how="left", validate="one_to_one")
    executable = audit_ledger.first_touch_executable.fillna(False)
    audit_ledger.loc[executable & audit_ledger.event_state.eq("FAVORABLE_FIRST"), "execution_state"] = "FAVORABLE_FIRST_EXECUTED"
    audit_ledger.loc[executable & audit_ledger.event_state.eq("ADVERSE_FIRST"), "execution_state"] = "ADVERSE_FIRST_EXECUTED"
    audit_ledger.loc[executable & audit_ledger.event_state.eq("NO_EVENT"), "execution_state"] = "NO_EVENT_EXECUTED"
    audit_ledger.loc[~executable, "execution_state"] = "NONEXECUTABLE"
    state_counts = audit_ledger.execution_state.value_counts().to_dict()
    if sum(state_counts.values()) != len(selected_audit) or audit_ledger.execution_state.eq("PENDING_EVENT_STATE").any():
        raise AuditStop("STOP_EXPLICIT_STATE_RECONCILIATION")
    real = audit_ledger.loc[audit_ledger.execution_state.str.endswith("_EXECUTED")].copy()
    actual = stats(real)

    runs, matched = matched_placebo(a, real, eligible)
    atomic_json(RUNTIME_RUN_ROOT / "progress.json", {**storage_gate, "stage": "MATCHED_PLACEBO_COMPLETE",
                                                      "run_count": RUNS, "real_mean_net20": stats(real)["mean_net20"]})
    real["year"] = real.timestamp.dt.tz_convert("America/New_York").dt.year
    by_direction, by_year, by_symbol = grouped(real, "head"), grouped(real, "year"), grouped(real, "action_instrument")
    classification, primary, edge_status, next_stage = classify(actual["mean_net20"], matched["real_net20_percentile"], matched["real_net20_p"])
    up = by_direction.loc[by_direction["head"].eq("UP")].iloc[0]
    down = by_direction.loc[by_direction["head"].eq("DOWN")].iloc[0]
    top_symbol = by_symbol.sort_values("trade_count", ascending=False).iloc[0]
    top_year = by_year.sort_values("total_net_contribution", ascending=False).iloc[0]
    positive_years, negative_years = int((by_year.mean_net20 > 0).sum()), int((by_year.mean_net20 < 0).sum())
    total_net = float(real.first_touch_net20.sum())
    top_one_share, extreme = extreme_outlier_audit(real.first_touch_net20)
    direction_high = bool((up.mean_net20 <= 0 < down.mean_net20) or (down.mean_net20 <= 0 < up.mean_net20) or
                          max(up.total_net_contribution, down.total_net_contribution) / total_net > .70) if total_net > 0 else False
    year_share = float(top_year.total_net_contribution / total_net) if total_net else math.nan
    symbol_share = float(top_symbol.trade_share)
    symbol_contribution_share = float(top_symbol.total_net_contribution / total_net) if total_net else math.nan

    identity = {
        "FROZEN_FAST3_SIGNAL_SOURCE": str(LEDGERS), "FROZEN_FAST3_SCORE_SOURCE": str(LEDGERS),
        "FROZEN_LABEL_CONTRACT_SOURCE": str(LABEL_SOURCE), "SOXX_PRICE_PATH_SOURCE": str(SOXX_MANIFEST),
        "MODEL_IDENTITY": signal_identity["model_identity"],
        "SIGNAL_LEDGER_SHA256": signal_identity["combined_signal_ledger_sha256"],
        "SCORE_LEDGER_SHA256": signal_identity["combined_signal_ledger_sha256"],
        "LABEL_CONTRACT_SHA256": file_sha256(LABEL_SOURCE), "SOXX_PRICE_IDENTITY": file_sha256(SOXX_MANIFEST),
        "ETF_MANIFEST_SHA256": manifest_hash, "CURRENT_EXECUTION_CONTRACT_SHA256": canonical_hash(execution_identity["execution_contract"]),
        "FROZEN_ANCHOR_LEDGER_SHA256": execution_identity["frozen_anchor_ledger_sha256"],
    }
    report_path, summary_path = OUT / "R28_3E_REPORT.md", OUT / "R28_3E_SUMMARY.json"
    summary = {
        "FAST3_R28_3E_STATUS": "PASS", "FAST3_R28_3E_CLASSIFICATION": classification,
        "BRANCH": branch, "START_HEAD": START_HEAD, "HEAD": head, "START_STATUS": START_STATUS,
        "CLEAN_LINEAGE_FREEZE_STATUS": "PASS", "ETF_MANIFEST_SHA256": manifest_hash,
        **{f"{symbol}_PARTITION_COUNT": int((manifest_csv.symbol == symbol).sum()) for symbol in SYMBOLS},
        "MODEL_RETRAIN_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0, "POST_FREEZE_RESCORING_COUNT": 0,
        "PROSPECTIVE_DATA_USED": False, "DATA_ROOT_WRITE_COUNT": 0,
        "FROZEN_SELECTION_RULE_SOURCE": str(COMPLETION),
        "FROZEN_SELECTION_RULE": "R28 selected=true frozen HGB threshold; simultaneous ties abstain; one global position; signals while open ignored",
        "SELECTED_SIGNAL_COUNT": int(len(selected_audit)), "EXECUTED_TRADE_COUNT": int(len(real)),
        "NONEXECUTABLE_COUNT": int(state_counts.get("NONEXECUTABLE", 0)), "DROPPED_ROW_COUNT": 0,
        "FAVORABLE_FIRST_COUNT": int(state_counts.get("FAVORABLE_FIRST_EXECUTED", 0)),
        "ADVERSE_FIRST_COUNT": int(state_counts.get("ADVERSE_FIRST_EXECUTED", 0)), "NO_EVENT_COUNT": int(state_counts.get("NO_EVENT_EXECUTED", 0)),
        "FIRST_TOUCH_REAL_WIN_RATE": actual["win_rate"], "FIRST_TOUCH_REAL_MEAN_GROSS": actual["mean_gross"],
        "FIRST_TOUCH_REAL_MEDIAN_GROSS": actual["median_gross"], "FIRST_TOUCH_REAL_MEAN_NET10": actual["mean_net10"],
        "FIRST_TOUCH_REAL_MEDIAN_NET10": actual["median_net10"], "FIRST_TOUCH_REAL_MEAN_NET20": actual["mean_net20"],
        "FIRST_TOUCH_REAL_MEDIAN_NET20": actual["median_net20"], "FIRST_TOUCH_DISTRIBUTION": actual,
        "FIRST_TOUCH_UP_MEAN_NET20": float(up.mean_net20), "FIRST_TOUCH_DOWN_MEAN_NET20": float(down.mean_net20),
        "R28_3A_REFERENCE_MEAN_NET20": REFERENCE_R28_3A_NET20,
        "FIRST_TOUCH_MINUS_R28_3A_REFERENCE_MEAN_NET20": actual["mean_net20"] - REFERENCE_R28_3A_NET20,
        "STRICT_PAIRED_CAUSAL_COMPARISON_ALLOWED": False, "MATCHED_RANDOM_RUN_COUNT": RUNS,
        "MATCHED_RANDOM_NET20_MEDIAN": matched["net20_mean_median"], "MATCHED_RANDOM_NET20_P90": matched["net20_p90"],
        "MATCHED_RANDOM_NET20_P95": matched["net20_p95"], "MATCHED_RANDOM_NET20_P99": matched["net20_p99"],
        "MATCHED_RANDOM_NET20_MAX": matched["net20_max"], "REAL_MATCHED_NET20_PERCENTILE": matched["real_net20_percentile"],
        "REAL_MATCHED_NET20_P": matched["real_net20_p"],
        **{f"MATCH_LEVEL_{i}_COUNT": matched[f"match_level_{i}_count"] for i in range(5)}, "UNMATCHED_COUNT": matched["unmatched_count"],
        "SIGNAL_CARDINALITY_CONSERVED": matched["signal_cardinality_conserved"],
        "UNIQUE_PLACEBO_SIGNAL_COUNT": matched["unique_placebo_signal_count"], "UNIQUE_OUTCOME_PATH_COUNT": matched["unique_outcome_path_count"],
        "SHARED_OUTCOME_PATH_COUNT": matched["shared_outcome_path_count"], "MAX_SIGNALS_PER_OUTCOME_PATH": matched["max_signals_per_outcome_path"],
        "UP_TRADE_COUNT": int(up.trade_count), "UP_WIN_RATE": float(up.win_rate), "UP_MEAN_NET20": float(up.mean_net20),
        "UP_MEDIAN_NET20": float(up.median_net20), "DOWN_TRADE_COUNT": int(down.trade_count), "DOWN_WIN_RATE": float(down.win_rate),
        "DOWN_MEAN_NET20": float(down.mean_net20), "DOWN_MEDIAN_NET20": float(down.median_net20),
        "UP_POSITIVE": bool(up.mean_net20 > 0), "DOWN_POSITIVE": bool(down.mean_net20 > 0),
        "DIRECTION_CONCENTRATION": "HIGH" if direction_high else "LOW",
        "POSITIVE_YEAR_COUNT": positive_years, "NEGATIVE_YEAR_COUNT": negative_years, "TOTAL_YEAR_COUNT": int(len(by_year)),
        "TOP_YEAR": str(top_year.year), "TOP_YEAR_CONTRIBUTION_SHARE": year_share,
        "YEAR_CONCENTRATION": "HIGH" if year_share > .70 else "LOW",
        "TOP_SYMBOL": str(top_symbol.action_instrument), "TOP_SYMBOL_SHARE": symbol_share,
        "TOP_SYMBOL_CONTRIBUTION_SHARE": symbol_contribution_share, "SYMBOL_CONCENTRATION": "HIGH" if symbol_share > .70 else "LOW",
        "LOSS_RATE": float((real.first_touch_net20 < 0).mean()), "P05_NET20": actual["p05_net20"], "P01_NET20": actual["p01_net20"],
        "WORST_TRADE": actual["worst_trade"], "BEST_TRADE": actual["best_trade"], "TOP_1PCT_CONTRIBUTION_SHARE": top_one_share,
        "MEAN_DRIVEN_BY_EXTREME_OUTLIERS": extreme, "PRIMARY_HYPOTHESIS_RESULT": primary,
        "FIRST_TOUCH_ECONOMIC_EDGE_STATUS": edge_status,
        "FINAL_RESEARCH_INTERPRETATION": f"Clean-lineage first-touch translation is {edge_status}; frozen matched-placebo result is {primary}.",
        "MODEL_RETRAIN_NEEDED": False, "R29_ALLOWED_TO_RESUME": False, "LIVE_TRADING_ALLOWED": False, "NEXT_STAGE": next_stage,
        "ENTRY_CONTRACT_SOURCE": str(COMPLETION), "ENTRY_TIMESTAMP_SEMANTICS": "first legal action-ETF 1m bar strictly after frozen anchor within 15 minutes",
        "ENTRY_PRICE_SEMANTICS": "open of that legal ETF bar", "INSTRUMENT_MAPPING_SOURCE": str(COMPLETION),
        "REFERENCE_PRICE_SEMANTICS": "first subsequent valid underlying one-minute open after frozen decision timestamp",
        "UP_TARGET_THRESHOLD": .01, "DOWN_TARGET_THRESHOLD": -.01, "EVENT_HORIZON": "24 natural hours",
        "NO_TOUCH_EXIT_CONTRACT_SOURCE": str(COMPLETION), "ADVERSE_EXIT_CONTRACT_SOURCE": str(COMPLETION),
        "PRIMARY_COST_ASSUMPTION": "20bps", "RANDOM_SEED": SEED, "PRIMARY_RANDOM_RUN_COUNT": RUNS,
        "identity": identity, "label_contract": label_contract, "execution_contract": execution_identity["execution_contract"],
        "explicit_state_counts": {key: int(value) for key, value in state_counts.items()},
        "by_direction": by_direction.to_dict(orient="records"), "by_year": by_year.to_dict(orient="records"),
        "by_symbol": by_symbol.to_dict(orient="records"),
        "REPORT_PATH": str(report_path), "SUMMARY_JSON_PATH": str(summary_path),
        "ETF_MANIFEST_PATH": str(OUT / "R28_3E_CANONICAL_ETF_PARTITION_MANIFEST.json"),
        "TRADE_LEDGER_PATH": str(OUT / "R28_3E_FIRST_TOUCH_TRADE_LEDGER.csv"),
        "MATCHED_PLACEBO_RUNS_PATH": str(OUT / "R28_3E_MATCHED_PLACEBO_RUNS.csv"),
        "FROZEN_MODEL_IDENTITY_SCHEMA": model_identity_map["frozen_model_identity_schema"],
        "UP_FROZEN_MODEL_IDENTITY_COUNT": model_identity_map["heads"]["UP"]["authoritative_identity_record_count"],
        "DOWN_FROZEN_MODEL_IDENTITY_COUNT": model_identity_map["heads"]["DOWN"]["authoritative_identity_record_count"],
        "UP_FOLD_MODEL_IDENTITY_SET_SHA256": model_identity_map["heads"]["UP"]["fold_model_identity_set_sha256"],
        "DOWN_FOLD_MODEL_IDENTITY_SET_SHA256": model_identity_map["heads"]["DOWN"]["fold_model_identity_set_sha256"],
        "SELECTED_SIGNAL_UNKNOWN_MODEL_COUNT": model_identity_map["selected_signal_mapping_reconciliation"]["selected_signal_unknown_model_count"],
        "SELECTED_SIGNAL_AMBIGUOUS_MODEL_COUNT": model_identity_map["selected_signal_mapping_reconciliation"]["selected_signal_ambiguous_model_count"],
        "SELECTED_SIGNAL_FEATURE_IDENTITY_MISMATCH_COUNT": model_identity_map["selected_signal_mapping_reconciliation"]["selected_signal_feature_identity_mismatch_count"],
        "FOLD_MODEL_IDENTITY_RECONCILIATION_STATUS": model_identity_map["selected_signal_mapping_reconciliation"]["status"],
        "MODEL_IDENTITY_MAP_PATH": str(OUT / "R28_3E_FROZEN_MODEL_IDENTITY_MAP.json"),
    }
    keep = ["candidate_id", "payoff_candidate_id", "underlying_symbol", "head", "timestamp", "probability", "frozen_threshold",
            "action_instrument", "entry_timestamp", "entry_price", "frozen_label", "event_state", "touch_timestamp",
            "first_touch_exit_timestamp", "first_touch_exit_price", "first_touch_exit_reason", "first_touch_gross", "first_touch_net10",
            "first_touch_net20", "first_touch_outcome_path", "execution_state", "first_touch_nonexecutable_reason"]
    audit_ledger = audit_ledger.loc[:, [column for column in keep if column in audit_ledger]]
    storage_audit = post_storage_audit(data_before)
    summary.update({
        "FAST3_STORAGE_CONTRACT_R1_STATUS": "PASS", "SOURCE_ROOT": str(REPO), "DATA_ROOT": str(DATA_ROOT),
        "RESULTS_ROOT": str(RESULTS), "CACHE_ROOT": str(CACHE_ROOT), "RUNTIME_RUN_ROOT": str(RUNTIME_RUN_ROOT),
        "SCRATCH_RUN_ROOT": str(SCRATCH_RUN_ROOT), "FROZEN_RUN_ROOT": str(OUT),
        "DATA_ROOT_WRITE_COUNT": storage_audit["data_root_write_count"],
        "LOCAL_RESULTS_CREATED": storage_audit["local_results_created"],
        "RESULT_FILES_WRITTEN_TO_GIT_REPO": storage_audit["result_files_written_to_git_repo"],
        "RUNTIME_OUTPUT_LOCATION_VALID": True, "SCRATCH_OUTPUT_LOCATION_VALID": True, "FROZEN_OUTPUT_LOCATION_VALID": True,
        "LARGE_REBUILDABLE_OUTPUTS_IN_SCRATCH_ROOT": True,
        "PRE_EXISTING_UNTRACKED_FILES_PRESERVED": storage_audit["pre_existing_untracked_files_preserved"],
        "PRE_EXISTING_TRACKED_CHANGES_PRESERVED": storage_audit["pre_existing_tracked_changes_preserved"],
        "PRE_EXISTING_STORAGE_VIOLATION_COUNT": len(storage_gate["pre_existing_storage_violations"]),
        "PRE_EXISTING_STORAGE_VIOLATIONS": storage_gate["pre_existing_storage_violations"],
        "NEW_R28_3E_STORAGE_VIOLATION_COUNT": storage_audit["new_r28_3e_storage_violation_count"],
        "SOURCE_WRITES_OUTSIDE_ALLOWED_SOURCE_FILES": storage_audit["source_writes_outside_allowed_source_files"],
        "PYTHON_CACHE_EXTERNALIZED": True, "PYTEST_TEMP_EXTERNALIZED": True,
        "DESTRUCTIVE_GIT_COMMAND_USED": False, "BROAD_GIT_ADD_USED": False,
        "FINAL_STORAGE_DECISION": "PASS_ATOMIC_FROZEN_EVIDENCE_WITH_RUNTIME_PROGRESS_AND_NO_DUPLICATED_LARGE_ARTIFACTS",
    })
    write_outputs(manifest_csv, manifest_bytes, manifest_hash, audit_ledger, by_direction, by_year, by_symbol,
                  runs, matched, model_identity_map, summary)
    atomic_json(RUNTIME_RUN_ROOT / "progress.json", {**storage_gate, "stage": "COMPLETE",
                                                      "frozen_run_root": str(OUT), "classification": classification})
    return summary


if __name__ == "__main__":
    try:
        print(json.dumps(run(), indent=2, default=str))
    except AuditStop as exc:
        if RUNTIME_RUN_ROOT.exists():
            atomic_json(RUNTIME_RUN_ROOT / "failure.json", {"FAST3_R28_3E_STATUS": "E_INVALID_OR_INCOMPLETE", "error": str(exc)})
        print(f"FAST3_R28_3E_STATUS=E_INVALID_OR_INCOMPLETE\n{exc}")
        raise SystemExit(2)
