"""Preparation-side inventory and date boundary verification; no fitting."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent / "trainer_bundle"
FILES = {"CLEAN_CONTRACT.md", "fit_supervised.py", "handoff.sh", "input_manifest.json",
         "isolation_probe.py", "ledger.py", "optimize_route.py", "prepare.py",
         "requirements.txt", "risk_aux.py", "rl_core.py", "rl_train.py",
         "run_training.py", "safe_inputs.py", "technical_tests.py"}
DATA = {"panel.parquet", "risk_panel.parquet", "prices.parquet"}
CUTOFF = pd.Timestamp("2026-01-01")


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def column_max(path: Path, column: str):
    source = pq.ParquetFile(path)
    index = source.schema_arrow.names.index(column)
    values = []
    for i in range(source.metadata.num_row_groups):
        stats = source.metadata.row_group(i).column(index).statistics
        if stats is None or not stats.has_min_max:
            raise RuntimeError(f"NO_PHYSICAL_DATE_STATS:{path.name}:{column}:{i}")
        values.append(pd.Timestamp(stats.max))
    maximum = max(values)
    if maximum >= CUTOFF:
        raise RuntimeError(f"POST_CUTOFF_DATE:{path.name}:{column}")
    return str(maximum.date())


def main():
    actual = {p.name for p in ROOT.iterdir() if p.is_file()}
    if actual != FILES:
        raise RuntimeError(f"BUNDLE_FILE_INVENTORY:{sorted(actual ^ FILES)}")
    if {p.name for p in (ROOT / "data").iterdir()} != DATA:
        raise RuntimeError("BUNDLE_DATA_INVENTORY")
    if {p.name for p in ROOT.iterdir() if p.is_dir()} != {"data"}:
        raise RuntimeError("UNEXPECTED_BUNDLE_DIRECTORY")
    for path in ROOT.rglob("*"):
        if path.is_symlink() or path.is_junction():
            raise RuntimeError(f"BUNDLE_ALIAS:{path}")
    manifest = json.loads((ROOT / "input_manifest.json").read_text(encoding="utf-8"))
    for relative, key in (("data/panel.parquet", "panel_sha256"),
                          ("data/risk_panel.parquet", "risk_panel_sha256"),
                          ("data/prices.parquet", "prices_sha256"),
                          ("ledger.py", "patched_ledger_sha256")):
        if sha(ROOT / relative) != manifest[key]:
            raise RuntimeError(f"INPUT_HASH_MISMATCH:{relative}")
    for name, expected in manifest["training_code_sha256"].items():
        if sha(ROOT / name) != expected:
            raise RuntimeError(f"CODE_HASH_MISMATCH:{name}")
    dates = {"panel_signal_max": column_max(ROOT / "data" / "panel.parquet", "signal_date"),
             "panel_label_end_max": column_max(ROOT / "data" / "panel.parquet", "label_end_date_5"),
             "risk_signal_max": column_max(ROOT / "data" / "risk_panel.parquet", "signal_date"),
             "price_max": column_max(ROOT / "data" / "prices.parquet", "trade_date")}
    print(json.dumps({"status": "CLEAN_BUNDLE_PREPARATION_PASS", "dates": dates,
                      "scope": "preparation_only_no_fit_accounting"}, indent=2))


if __name__ == "__main__":
    main()
