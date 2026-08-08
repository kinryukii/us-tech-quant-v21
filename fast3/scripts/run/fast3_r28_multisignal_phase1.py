#!/usr/bin/env python
"""R28 Phase 1: small, outcome-blind feature-generation dry run only."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

SOURCE_ROOT = Path(r"D:\us-tech-quant")
DATA_ROOT = Path(r"D:\us-tech-quant-data")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
CACHE_ROOT = Path(r"D:\us-tech-quant-cache")
CANONICAL = DATA_ROOT / "fast3" / "moomoo_24h_1m" / "canonical"
sys.path.insert(0, str(SOURCE_ROOT / "fast3" / "src"))
from fast3.r28_multisignal import (  # noqa: E402
    BASELINE_FEATURES, BLOCKED_FACTORS, FEATURE_FAMILIES, R28_FEATURES, build_features, pit_audit,
)


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_sample(symbol: str, rows: int) -> pd.DataFrame:
    path = CANONICAL / f"symbol={symbol}" / "year=2024" / "month=01" / "data.parquet"
    if not path.is_file():
        raise RuntimeError(f"R28_SOURCE_DATA_MISSING:{symbol}")
    return pd.read_parquet(path, columns=["timestamp_utc", "open", "high", "low", "close", "volume"]).head(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--sample-rows", type=int, default=360)
    args = parser.parse_args()
    if args.sample_rows < 180:
        raise RuntimeError("R28_SAMPLE_TOO_SMALL")
    if any(SOURCE_ROOT.rglob(".local_results")):
        raise RuntimeError("R28_LOCAL_RESULTS_FORBIDDEN")
    runtime = RESULTS_ROOT / "runtime" / "fast3" / f"r28_multisignal_{args.run_id}"
    scratch = RESULTS_ROOT / "scratch" / "fast3" / f"r28_multisignal_{args.run_id}"
    frozen = RESULTS_ROOT / "frozen" / "fast3" / f"r28_phase1_{args.run_id}"
    for directory in (runtime, scratch, frozen):
        directory.mkdir(parents=True, exist_ok=False)
    qqq = load_sample("QQQ", args.sample_rows)
    soxx = load_sample("SOXX", args.sample_rows)
    qqq_features = build_features(qqq, soxx).assign(underlying_symbol="QQQ", peer_symbol="SOXX")
    soxx_features = build_features(soxx, qqq).assign(underlying_symbol="SOXX", peer_symbol="QQQ")
    qqq_complete = qqq_features.dropna(subset=list(R28_FEATURES)).reset_index(drop=True)
    soxx_complete = soxx_features.dropna(subset=list(R28_FEATURES)).reset_index(drop=True)
    complete = pd.concat([qqq_complete, soxx_complete], ignore_index=True).sort_values(["underlying_symbol", "timestamp_utc"], kind="mergesort").reset_index(drop=True)
    per_symbol_audit = {"QQQ": pit_audit(qqq_complete), "SOXX": pit_audit(soxx_complete)}
    audit = {"row_count": int(len(complete)), "per_symbol": per_symbol_audit,
             "pit_pass": bool(all(value["pit_pass"] for value in per_symbol_audit.values()))}
    deterministic = complete.equals(pd.concat([
        build_features(qqq, soxx).assign(underlying_symbol="QQQ", peer_symbol="SOXX"),
        build_features(soxx, qqq).assign(underlying_symbol="SOXX", peer_symbol="QQQ"),
    ], ignore_index=True).sort_values(["underlying_symbol", "timestamp_utc"], kind="mergesort").dropna(subset=list(R28_FEATURES)).reset_index(drop=True))
    if not audit["pit_pass"] or not deterministic or complete.empty:
        raise RuntimeError("R28_DRY_RUN_PIT_OR_DETERMINISM_FAILURE")
    feature_path = scratch / "r28_dry_run_features.parquet"
    complete.to_parquet(feature_path, index=False)
    contract_path = SOURCE_ROOT / "fast3" / "configs" / "contracts" / "FAST3_R28_MULTISIGNAL_RESEARCH_CONTRACT.json"
    frozen_contract = frozen / "R28_RESEARCH_CONTRACT.json"
    frozen_contract.write_bytes(contract_path.read_bytes())
    manifest = {
        "status": "PASS", "decision": "PASS_R28_PHASE1_RESEARCH_READY", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "baseline_feature_count": len(BASELINE_FEATURES), "new_feature_count": len(R28_FEATURES),
        "feature_families": FEATURE_FAMILIES, "blocked_factors": BLOCKED_FACTORS,
        "dry_run_row_count": int(len(complete)), "sample_rows_per_symbol": args.sample_rows,
        "pit_audit": audit, "deterministic_output": bool(deterministic),
        "data_root_write_count": 0, "model_training_executed": False, "holdout_scoring_executed": False,
        "storage_contract_pass": True, "feature_path_sha256": sha256(feature_path), "contract_sha256": sha256(frozen_contract),
    }
    write_json(runtime / "R28_DRY_RUN_SUMMARY.json", manifest)
    write_json(frozen / "R28_PHASE1_DECISION.json", manifest)
    write_json(frozen / "R28_PIT_AUDIT.json", audit)
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
