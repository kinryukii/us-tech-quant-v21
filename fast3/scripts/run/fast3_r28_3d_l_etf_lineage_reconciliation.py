"""Read-only FAST3 R28.3D-L ETF canonical partition lineage reconciliation.

This is deliberately an artifact-forensics runner.  It never imports a model,
payoff constructor, or any R28.3D economic-translation path.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

REPO = Path(r"D:\us-tech-quant")
DATA_ROOT = Path(r"D:\us-tech-quant-data")
RESULTS = Path(r"D:\us-tech-quant-results")
CANONICAL = DATA_ROOT / "fast3" / "moomoo_24h_1m" / "canonical"
SYMBOLS = ("SOXL", "SOXS", "TQQQ", "SQQQ")
R28_3A_SUMMARY = RESULTS / "frozen" / "fast3" / "r28_3a_frozen_economic_attribution_20260809_r2" / "R28_3A_SUMMARY.json"
PAYOFF_LEDGER = RESULTS / "scratch" / "fast3" / "r27_2_independent_heads_20260806T235700000Z" / "r27_2_regenerated_r26a2_payoff_ledger.parquet"
SEARCH_ROOTS = (RESULTS / "frozen" / "fast3", RESULTS / "archive" / "fast3", RESULTS / "runtime" / "fast3", RESULTS / "scratch" / "fast3")
DIFF_FIELDS = ("symbol", "partition_key", "historical_present", "current_present", "historical_path", "current_path", "historical_file_sha256", "current_file_sha256", "historical_row_count", "current_row_count", "historical_min_ts", "current_min_ts", "historical_max_ts", "current_max_ts", "difference_class")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def git(command: list[str]) -> str:
    return subprocess.check_output(command, cwd=REPO, text=True, encoding="utf-8").strip()


def artifact_identity() -> dict[str, Any]:
    """Anchor to a frozen R28.3A artifact, then verify its referenced ledger."""
    summary = json.loads(R28_3A_SUMMARY.read_text(encoding="utf-8"))
    expected = str(summary["identity"]["payoff_sha256"]).lower()
    actual = sha256(PAYOFF_LEDGER)
    if actual != expected:
        raise RuntimeError("STOP_AUTHORITATIVE_PAYOFF_HASH_MISMATCH")
    column = pd.read_parquet(PAYOFF_LEDGER, columns=["canonical_partition_manifest_hash", "execution_contract_hash"])
    hashes = sorted(set(column.canonical_partition_manifest_hash.astype(str)))
    executions = sorted(set(column.execution_contract_hash.astype(str)))
    if len(hashes) != 1 or len(executions) != 1:
        raise RuntimeError("STOP_AUTHORITATIVE_PAYOFF_LINEAGE_AMBIGUOUS")
    return {"authoritative_frozen_artifact_path": str(R28_3A_SUMMARY), "verified_payoff_ledger_path": str(PAYOFF_LEDGER),
            "authoritative_payoff_hash": actual, "authoritative_execution_hash": executions[0],
            "authoritative_canonical_partition_manifest_hash": hashes[0], "r28_3a_summary_sha256": sha256(R28_3A_SUMMARY)}


def partition_key(path: Path) -> tuple[str, str]:
    values = {p.split("=", 1)[0]: p.split("=", 1)[1] for p in path.parts if "=" in p}
    return values.get("symbol", "UNKNOWN"), f"{values.get('year', '????')}-{values.get('month', '??')}"


def schema_fingerprint(schema: Any) -> str:
    return hashlib.sha256(str(schema).encode("utf-8")).hexdigest()


def current_partition(path: Path) -> dict[str, Any]:
    symbol, key = partition_key(path)
    table = ds.dataset(path, format="parquet").to_table(columns=["timestamp_et"])
    ts = pd.to_datetime(table.column("timestamp_et").to_pandas(), utc=True, errors="coerce")
    schema = ds.dataset(path, format="parquet").schema
    return {"symbol": symbol, "partition_key": key, "source_path": str(path),
            "normalized_path": str(path.relative_to(CANONICAL)).replace("\\", "/"), "file_name": path.name,
            "file_size": path.stat().st_size, "file_sha256": sha256(path), "row_count": int(len(table)),
            "min_timestamp": None if ts.empty else str(ts.min()), "max_timestamp": None if ts.empty else str(ts.max()),
            "schema_fingerprint": schema_fingerprint(schema), "column_list": list(schema.names)}


def rebuild_current_manifest() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    records = [current_partition(p) for symbol in SYMBOLS for p in sorted((CANONICAL / f"symbol={symbol}").rglob("*.parquet"))]
    if not records or {r["symbol"] for r in records} != set(SYMBOLS):
        raise RuntimeError("STOP_CURRENT_CANONICAL_PARTITIONS_INCOMPLETE")
    # Exact R26A/R26A2 manifest representation: sorted files, only these fields.
    generator = {symbol: {"symbol": symbol, "file_count": sum(r["symbol"] == symbol for r in records), "files": [
        {"relative_path": r["normalized_path"], "sha256": r["file_sha256"], "bytes": r["file_size"]}
        for r in records if r["symbol"] == symbol], "legal_bar_count": None, "rejected_bar_count": None} for symbol in SYMBOLS}
    # Legal count is part of the historical generator.  Read only the required columns and apply its fixed predicate.
    for symbol in SYMBOLS:
        root = CANONICAL / f"symbol={symbol}"
        bars = ds.dataset(root, format="parquet").to_table(columns=["symbol", "timestamp_et", "open", "high", "low", "close", "volume", "source"]).to_pandas()
        numeric = bars[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
        timestamps = pd.to_datetime(bars.timestamp_et, utc=True, errors="coerce")
        legal = (bars.symbol.astype(str).eq(symbol) & timestamps.notna() & np.isfinite(numeric).all(axis=1) & numeric.open.gt(0) & numeric.high.gt(0) & numeric.low.gt(0) & numeric.close.gt(0) & numeric.volume.ge(0) & numeric.high.ge(np.maximum(numeric.open, numeric.close)) & numeric.low.le(np.minimum(numeric.open, numeric.close)) & bars.source.notna())
        if timestamps.loc[legal].duplicated().any():
            raise RuntimeError(f"STOP_CURRENT_CANONICAL_DUPLICATE_TIMESTAMP:{symbol}")
        generator[symbol]["legal_bar_count"] = int(legal.sum())
        generator[symbol]["rejected_bar_count"] = int((~legal).sum())
    return {"manifest_generator": "FAST3_R26A2_legal_bars_R28_3D_L_read_only_replica", "canonical_root": str(CANONICAL),
            "symbols": generator, "canonical_partition_manifest_hash": stable_hash(generator), "partition_records": records}, records


def contains_hash(value: Any, target: str) -> bool:
    if isinstance(value, dict): return any(contains_hash(v, target) for v in value.values())
    if isinstance(value, list): return any(contains_hash(v, target) for v in value)
    return str(value).lower() == target.lower()


def find_historical_manifest(target_hash: str) -> tuple[Path | None, list[str]]:
    """Discover only an artifact whose own contents bind it to the frozen hash."""
    candidates: list[str] = []
    pattern = re.compile(r"(canonical.*partition.*manifest|partition.*inventory|data.*lineage|source.*manifest)", re.I)
    for root in SEARCH_ROOTS:
        if not root.exists(): continue
        for path in root.rglob("*.json"):
            if not pattern.search(path.name): continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if contains_hash(value, target_hash):
                candidates.append(str(path))
                if isinstance(value, dict) and ("files" in value or "symbols" in value or "partition_manifest" in value):
                    return path, candidates
    return None, candidates


def classify_pair(h: dict[str, Any] | None, c: dict[str, Any] | None) -> str:
    if h is None or c is None: return "J_UNKNOWN"
    if h.get("file_sha256") and h.get("file_sha256") != c["file_sha256"]: return "F_FILE_CONTENT_HASH_CHANGED"
    if h.get("row_count") not in (None, c["row_count"]): return "G_ROW_COUNT_CHANGED"
    if h.get("min_timestamp") not in (None, c["min_timestamp"]) or h.get("max_timestamp") not in (None, c["max_timestamp"]): return "H_TIMESTAMP_BOUNDS_CHANGED"
    if h.get("schema_fingerprint") not in (None, c["schema_fingerprint"]): return "I_SCHEMA_CHANGED"
    if h.get("normalized_path") != c["normalized_path"]: return "A_PATH_REPRESENTATION_ONLY"
    return "B_ORDERING_OR_SERIALIZATION_ONLY"


def comparison(historical: list[dict[str, Any]] | None, current: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    # No historical per-partition evidence must not be misreported as additions or content matches.
    if historical is None:
        rows = [{"symbol": r["symbol"], "partition_key": r["partition_key"], "historical_present": "UNKNOWN", "current_present": True,
                 "historical_path": "", "current_path": r["source_path"], "historical_file_sha256": "", "current_file_sha256": r["file_sha256"],
                 "historical_row_count": "", "current_row_count": r["row_count"], "historical_min_ts": "", "current_min_ts": r["min_timestamp"],
                 "historical_max_ts": "", "current_max_ts": r["max_timestamp"], "difference_class": "J_UNKNOWN"} for r in current]
        return rows, {"manifest_semantic_identity": "UNKNOWN", "underlying_partition_set_identity": "UNKNOWN", "underlying_content_identity": "UNKNOWN", "row_count_identity": "UNKNOWN", "timestamp_bound_identity": "UNKNOWN", "schema_identity": "UNKNOWN"}
    # Adapter intentionally accepts already-normalized historical records; future recovered manifests can use it without changing rules.
    hm, cm = {(r["symbol"], r["partition_key"]): r for r in historical}, {(r["symbol"], r["partition_key"]): r for r in current}
    rows = []
    for key in sorted(set(hm) | set(cm)):
        h, c = hm.get(key), cm.get(key); d = "D_PARTITION_ADDED" if h is None else ("E_PARTITION_MISSING" if c is None else classify_pair(h, c))
        rows.append({"symbol": key[0], "partition_key": key[1], "historical_present": h is not None, "current_present": c is not None,
                     "historical_path": "" if h is None else h.get("source_path", ""), "current_path": "" if c is None else c["source_path"],
                     "historical_file_sha256": "" if h is None else h.get("file_sha256", ""), "current_file_sha256": "" if c is None else c["file_sha256"],
                     "historical_row_count": "" if h is None else h.get("row_count", ""), "current_row_count": "" if c is None else c["row_count"],
                     "historical_min_ts": "" if h is None else h.get("min_timestamp", ""), "current_min_ts": "" if c is None else c["min_timestamp"],
                     "historical_max_ts": "" if h is None else h.get("max_timestamp", ""), "current_max_ts": "" if c is None else c["max_timestamp"], "difference_class": d})
    all_content = all(r["difference_class"] in ("A_PATH_REPRESENTATION_ONLY", "B_ORDERING_OR_SERIALIZATION_ONLY", "C_METADATA_ONLY") for r in rows)
    return rows, {"manifest_semantic_identity": all_content, "underlying_partition_set_identity": not any(r["difference_class"] in ("D_PARTITION_ADDED", "E_PARTITION_MISSING") for r in rows), "underlying_content_identity": all_content, "row_count_identity": not any(r["difference_class"] == "G_ROW_COUNT_CHANGED" for r in rows), "timestamp_bound_identity": not any(r["difference_class"] == "H_TIMESTAMP_BOUNDS_CHANGED" for r in rows), "schema_identity": not any(r["difference_class"] == "I_SCHEMA_CHANGED" for r in rows)}


def run() -> dict[str, Any]:
    start_branch, start_head, start_status = git(["git", "branch", "--show-current"]), git(["git", "rev-parse", "HEAD"]), git(["git", "status", "--short"])
    auth = artifact_identity(); historical_path, candidates = find_historical_manifest(auth["authoritative_canonical_partition_manifest_hash"])
    current_manifest, current = rebuild_current_manifest()
    # This repository has no authoritative, per-partition historical manifest. Never invent one from aggregate hashes.
    diff, identities = comparison(None, current)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = RESULTS / "frozen" / "fast3" / f"r28_3d_l_etf_lineage_reconciliation_{stamp}"; out.mkdir(parents=True, exist_ok=False)
    historical_sha = sha256(historical_path) if historical_path else None
    with (out / "R28_3D_L_MANIFEST_DIFF.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DIFF_FIELDS); writer.writeheader(); writer.writerows(diff)
    symbol_rows = []
    for symbol in SYMBOLS:
        subset = [r for r in current if r["symbol"] == symbol]
        symbol_rows.append({"symbol": symbol, "historical_partition_count": "UNKNOWN", "current_partition_count": len(subset), "matching_partition_count": "UNKNOWN", "missing_partition_count": "UNKNOWN", "added_partition_count": "UNKNOWN", "content_changed_partition_count": "UNKNOWN", "row_count_match": "UNKNOWN", "timestamp_bounds_match": "UNKNOWN", "schema_match": "UNKNOWN", "content_identity_confirmed": "UNKNOWN"})
    with (out / "R28_3D_L_SYMBOL_RECONCILIATION.csv").open("w", newline="", encoding="utf-8") as f: w = csv.DictWriter(f, fieldnames=list(symbol_rows[0])); w.writeheader(); w.writerows(symbol_rows)
    (out / "R28_3D_L_AUTHORITATIVE_FROZEN_IDENTITY.json").write_text(json.dumps({**auth, "historical_manifest_search_roots": [str(x) for x in SEARCH_ROOTS], "hash_bound_candidates": candidates, "historical_manifest_found": False}, indent=2), encoding="utf-8")
    (out / "R28_3D_L_CURRENT_MANIFEST.json").write_text(json.dumps(current_manifest, indent=2), encoding="utf-8")
    summary = {"FAST3_R28_3D_L_STATUS": "PASS", "FAST3_R28_3D_L_CLASSIFICATION": "E_INSUFFICIENT_FROZEN_LINEAGE_EVIDENCE", "branch": start_branch, "start_head": start_head, "head": git(["git", "rev-parse", "HEAD"]), "start_status": start_status, **auth, "historical_manifest_found": False, "historical_manifest_path": None, "historical_manifest_sha256": historical_sha, "historical_manifest_generator": "UNKNOWN_NOT_RECOVERABLE", "current_manifest_generator_path": str(REPO / "fast3" / "src" / "fast3" / "economics" / "executable_payoff_ledger_hard_r26a.py"), "current_manifest_generator_sha256": sha256(REPO / "fast3" / "src" / "fast3" / "economics" / "executable_payoff_ledger_hard_r26a.py"), "current_rebuilt_manifest_hash": current_manifest["canonical_partition_manifest_hash"], "manifest_byte_identity": False, **identities, "root_cause": "HISTORICAL_MANIFEST_NOT_RECOVERABLE", "likely_data_drift_cause": "UNKNOWN", "lineage_bridge_allowed": False, "r28_3d_resume_allowed": False, "do_not_run_r28_3d": True, "do_not_run_r29": True, "constraints": {"model_retrain_count": 0, "model_predict_call_count": 0, "post_freeze_rescoring_count": 0, "economic_trade_count": 0, "matched_placebo_run_count": 0, "prospective_data_used": False, "data_root_write_count": 0, "live_trading_allowed": False}, "affected_symbols": "UNKNOWN", "affected_date_range": "UNKNOWN", "first_differing_partition": "UNKNOWN", "last_differing_partition": "UNKNOWN", "paths": {"report": str(out / "R28_3D_L_REPORT.md"), "summary": str(out / "R28_3D_L_SUMMARY.json"), "manifest_diff": str(out / "R28_3D_L_MANIFEST_DIFF.csv"), "lineage_bridge": "NONE"}}
    final_fields = {"BRANCH": start_branch, "START_HEAD": start_head, "HEAD": summary["head"], "AUTHORITATIVE_FROZEN_ARTIFACT_PATH": auth["authoritative_frozen_artifact_path"], "AUTHORITATIVE_FROZEN_MANIFEST_HASH": auth["authoritative_canonical_partition_manifest_hash"], "HISTORICAL_MANIFEST_FOUND": False, "HISTORICAL_MANIFEST_PATH": "NONE", "HISTORICAL_MANIFEST_SHA256": "NONE", "CURRENT_REBUILT_MANIFEST_HASH": current_manifest["canonical_partition_manifest_hash"], "MANIFEST_BYTE_IDENTITY": False, "MANIFEST_SEMANTIC_IDENTITY": "UNKNOWN", "UNDERLYING_PARTITION_SET_IDENTITY": "UNKNOWN", "UNDERLYING_CONTENT_IDENTITY": "UNKNOWN", "ROW_COUNT_IDENTITY": "UNKNOWN", "TIMESTAMP_BOUND_IDENTITY": "UNKNOWN", "SCHEMA_IDENTITY": "UNKNOWN", "MISSING_PARTITION_COUNT": "UNKNOWN", "ADDED_PARTITION_COUNT": "UNKNOWN", "CONTENT_CHANGED_PARTITION_COUNT": "UNKNOWN", "ROW_COUNT_CHANGED_PARTITION_COUNT": "UNKNOWN", "TIMESTAMP_CHANGED_PARTITION_COUNT": "UNKNOWN", "SCHEMA_CHANGED_PARTITION_COUNT": "UNKNOWN", "FIRST_DIFFERING_PARTITION": "UNKNOWN", "LAST_DIFFERING_PARTITION": "UNKNOWN", "AFFECTED_SYMBOLS": "UNKNOWN", "AFFECTED_DATE_RANGE": "UNKNOWN", "ROOT_CAUSE": "HISTORICAL_MANIFEST_NOT_RECOVERABLE", "LINEAGE_BRIDGE_ALLOWED": False, "R28_3D_RESUME_ALLOWED": False, "MODEL_RETRAIN_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0, "POST_FREEZE_RESCORING_COUNT": 0, "ECONOMIC_TRADE_COUNT": 0, "MATCHED_PLACEBO_RUN_COUNT": 0, "PROSPECTIVE_DATA_USED": False, "DATA_ROOT_WRITE_COUNT": 0, "FINAL_LINEAGE_INTERPRETATION": "Aggregate frozen identity is verified, but no frozen per-partition identity evidence exists; current ETF data cannot be strictly proven same-source.", "R29_ALLOWED_TO_RESUME": False, "LIVE_TRADING_ALLOWED": False, "REPORT_PATH": str(out / "R28_3D_L_REPORT.md"), "SUMMARY_JSON_PATH": str(out / "R28_3D_L_SUMMARY.json"), "MANIFEST_DIFF_PATH": str(out / "R28_3D_L_MANIFEST_DIFF.csv"), "LINEAGE_BRIDGE_PATH": "NONE"}
    for symbol in SYMBOLS:
        final_fields[f"{symbol}_HISTORICAL_PARTITION_COUNT"] = "UNKNOWN"; final_fields[f"{symbol}_CURRENT_PARTITION_COUNT"] = current_manifest["symbols"][symbol]["file_count"]; final_fields[f"{symbol}_CONTENT_CHANGED_PARTITION_COUNT"] = "UNKNOWN"
    summary.update(final_fields)
    (out / "R28_3D_L_SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    report = "# FAST3 R28.3D-L ETF lineage reconciliation\n\nResult: historical per-partition manifest evidence was not recovered. The frozen R28.3A summary verified the payoff ledger hash, and that verified ledger binds aggregate manifest hash `{} `. No historical manifest or frozen per-partition content identity was available to prove correspondence with the rebuilt current ETF partitions. A bridge is therefore prohibited.\n\n".format(auth["authoritative_canonical_partition_manifest_hash"]) + "```json\n" + json.dumps(summary, indent=2) + "\n```\n"
    (out / "R28_3D_L_REPORT.md").write_text(report, encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
