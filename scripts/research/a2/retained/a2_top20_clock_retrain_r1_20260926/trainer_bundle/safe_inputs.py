"""Bundle-local read-only loader; no source-root or network fallback."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent
CUTOFF = pd.Timestamp("2026-01-01")


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def guarded_parquet(path: Path, column: str) -> pd.DataFrame:
    source = pq.ParquetFile(path)
    index = source.schema_arrow.names.index(column)
    for group in range(source.metadata.num_row_groups):
        stats = source.metadata.row_group(group).column(index).statistics
        if stats is None or not stats.has_min_max or pd.Timestamp(stats.max) >= CUTOFF:
            raise RuntimeError(f"UNPROVEN_TRAINING_DATE:{path.name}:{group}")
    frame = source.read().to_pandas()
    if frame.empty or pd.to_datetime(frame[column]).max() >= CUTOFF:
        raise RuntimeError(f"TRAINING_DATE_BOUNDARY:{path.name}")
    return frame


def load_inputs():
    manifest = json.loads((ROOT / "input_manifest.json").read_text(encoding="utf-8"))
    risk_path = ROOT / "data" / "risk_panel.parquet"
    price_path = ROOT / "data" / "prices.parquet"
    if sha(risk_path) != manifest["risk_panel_sha256"] or sha(price_path) != manifest["prices_sha256"]:
        raise RuntimeError("CLEAN_INPUT_HASH_MISMATCH")
    panel = guarded_parquet(risk_path, "signal_date")
    prices = guarded_parquet(price_path, "trade_date")
    return panel, prices, None, {"status": "BUNDLE_LOCAL_PRE2026_ONLY",
                                  "input_manifest_sha256": sha(ROOT / "input_manifest.json")}
