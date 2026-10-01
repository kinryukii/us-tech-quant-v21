"""Check only the 42 named missing transport tickers in saved 2026 annual Raw."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
TASKS = HERE / "R5_OTHER42_NO_RAW_2722_DAY_RESIDUAL.csv"
RAW = Path(r"D:\us-tech-quant-data\moomoo\source\prices_raw\year=2026\prices.parquet")
tasks = pd.read_csv(TASKS)
targets = set(tasks.ticker.astype(str))
assert len(targets) == 42
arrow = pq.read_table(RAW, columns=["ticker"])
available = set(arrow.column("ticker").to_pylist())
matched = sorted(targets & available)
h = hashlib.sha256()
with RAW.open("rb") as stream:
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        h.update(chunk)
result = {
    "saved_original_raw": str(RAW),
    "saved_original_raw_sha256": h.hexdigest(),
    "raw_rows_total": len(arrow),
    "target_codes": 42,
    "matched_target_codes": matched,
    "missing_target_codes": sorted(targets - available),
    "affected_candidate_days": int(tasks.affected_candidate_days.sum()),
    "scope": "2026 annual saved original Raw ticker column only; no provider request and no parent ledger edit",
}
assert not matched and result["affected_candidate_days"] == 2722
(HERE / "R5_OTHER42_SAVED_2026_RAW_CHECK.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"matched": len(matched), "missing": len(targets - available),
                  "days": result["affected_candidate_days"]}))
