"""Controlled, idempotent promotion of the frozen 2026-08-12 COMPACT evidence.

This is intentionally a thin permission-bound wrapper around the existing
V22.050 and R10C1 writers.  It never fetches market data or recalculates
signals: the only source is the frozen V21.233 ranking artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pandas as pd

DATE = "2026-08-12"
NEXT_DATE = "2026-08-13"
ROOT = Path(__file__).resolve().parents[2]
FROZEN = Path(r"D:\us-tech-quant-results\historical_backfills\2026-08-12_v22-040_pit\abcde_strategy_ranking_master.csv")
CANONICAL = Path(r"D:\us-tech-quant-data\canonical\v22\ABCDE_COMPACT_V1_DAILY_HISTORY_R1\abcde_compact_v1_daily_2026.parquet")
LEDGER = Path(r"D:\us-tech-quant-data\research_ledger\v22\R10C1_ABCDE_COMPACT_V1_FORWARD_STABILITY_LEDGER_R1")
KEY = ["signal_date", "model_version", "strategy_name", "ticker"]
SIGNAL_KEY = ["signal_date", "ticker", "model_version"]


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest_frame(frame: pd.DataFrame, columns: list[str]) -> str:
    ordered = frame.loc[:, columns].sort_values(columns).to_csv(index=False, lineterminator="\n")
    return hashlib.sha256(ordered.encode()).hexdigest()


def date_rows(frame: pd.DataFrame, value: str) -> pd.DataFrame:
    return frame[frame["signal_date"].astype(str).str[:10] == value].copy()


def frozen_rows() -> pd.DataFrame:
    rows = pd.read_csv(FROZEN)
    if len(rows) != 1625 or set(rows["latest_date"].astype(str)) != {DATE}:
        raise RuntimeError("FROZEN_EVIDENCE_NOT_EXACT_2026_08_12")
    if set(rows.groupby("strategy_name").size().to_dict().values()) != {325}:
        raise RuntimeError("FROZEN_EVIDENCE_UNIVERSE_MISMATCH")
    return rows


def identity_matches(canonical_rows: pd.DataFrame, frozen: pd.DataFrame, source_hash: str) -> bool:
    if len(canonical_rows) != len(frozen) or canonical_rows[KEY].duplicated().any():
        return False
    required = {"raw_score", "rank", "source_snapshot_fingerprint", "source_snapshot_path"}
    if not required <= set(canonical_rows.columns):
        return False
    expected = frozen[["strategy_name", "ticker", "score", "rank"]].rename(columns={"score": "raw_score"})
    actual = canonical_rows[["strategy_name", "ticker", "raw_score", "rank"]]
    merged = actual.merge(expected, on=["strategy_name", "ticker", "raw_score", "rank"], how="outer", indicator=True)
    return bool((merged["_merge"] == "both").all()) and set(canonical_rows["source_snapshot_fingerprint"].astype(str)) == {source_hash} and set(canonical_rows["source_snapshot_path"].astype(str)) == {str(FROZEN)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="perform the controlled promotion; default is read-only validation")
    args = parser.parse_args(argv)
    frozen = frozen_rows()
    source_hash = hashlib.sha256(FROZEN.read_bytes()).hexdigest()
    canonical = pd.read_parquet(CANONICAL)
    existing = date_rows(canonical, DATE)
    signal_path = LEDGER / "compact_signal_ledger.parquet"
    forward_path = LEDGER / "compact_forward_label_ledger.parquet"
    signal = pd.read_parquet(signal_path)
    forward = pd.read_parquet(forward_path)
    before_0813 = {"canonical": digest_frame(date_rows(canonical, NEXT_DATE), list(canonical.columns)), "signal": digest_frame(date_rows(signal, NEXT_DATE), list(signal.columns)), "forward": digest_frame(date_rows(forward, NEXT_DATE), list(forward.columns))}
    if not existing.empty:
        if identity_matches(existing, frozen, source_hash) and len(date_rows(signal, DATE)) == 325 and len(date_rows(forward, DATE)) == 325:
            print("IDEMPOTENT_PASS_FROZEN_2026_08_12_ALREADY_PROMOTED")
            return 0
        raise RuntimeError("EXISTING_2026_08_12_IDENTITY_CONFLICT")
    if not args.execute:
        print("DRY_RUN_PASS_2026_08_12_ABSENT_PROMOTION_REQUIRED")
        return 0

    production = load(ROOT / "scripts/v22/v22_050_compact_abcde_production_versioning.py", "v22_050_controlled")
    r10c1 = load(ROOT / "scripts/v22/r10c1_abcde_compact_v1_forward_stability_ledger.py", "r10c1_controlled")
    production.SRC = FROZEN
    production.run()
    r10c1.CAN, r10c1.LED = CANONICAL, LEDGER
    r10c1.main()

    canonical_after = pd.read_parquet(CANONICAL)
    signal_after, forward_after = pd.read_parquet(signal_path), pd.read_parquet(forward_path)
    if not identity_matches(date_rows(canonical_after, DATE), frozen, source_hash):
        raise RuntimeError("POSTWRITE_2026_08_12_IDENTITY_FAILED")
    if len(date_rows(signal_after, DATE)) != 325 or len(date_rows(forward_after, DATE)) != 325:
        raise RuntimeError("POSTWRITE_2026_08_12_LEDGER_ROWCOUNT_FAILED")
    if canonical_after[KEY].duplicated().sum() or signal_after[SIGNAL_KEY].duplicated().sum():
        raise RuntimeError("POSTWRITE_DUPLICATE_DATE_KEY_FAILED")
    after_0813 = {"canonical": digest_frame(date_rows(canonical_after, NEXT_DATE), list(canonical_after.columns)), "signal": digest_frame(date_rows(signal_after, NEXT_DATE), list(signal_after.columns)), "forward": digest_frame(date_rows(forward_after, NEXT_DATE), list(forward_after.columns))}
    if before_0813 != after_0813:
        raise RuntimeError("POSTWRITE_2026_08_13_CHANGED")
    print("PROMOTION_PASS_FROZEN_2026_08_12_COMPACT_R10C1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
