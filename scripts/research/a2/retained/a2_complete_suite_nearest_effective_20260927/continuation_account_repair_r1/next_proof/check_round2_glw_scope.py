"""Check which saved 2026 account ledgers actually held GLW on the disputed date."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


JOINT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "ROUND2_GLW_SCOPE_RECEIPT.json"
DAY = pd.Timestamp("2026-02-26")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(folder: Path, pattern: str) -> dict:
    files = sorted(folder.glob(pattern))
    hits = []
    for path in files:
        rows = pd.read_parquet(path, columns=["date", "ticker", "index_units"])
        matched = rows.loc[rows.ticker.eq("GLW") & rows.date.eq(DAY)]
        if not matched.empty:
            hits.append({"path": str(path), "sha256": digest(path),
                         "index_units": matched.index_units.astype(float).tolist()})
    return {"files_inspected": len(files), "matches": hits}


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preserve previous receipt")
    report = {
        "scope": "2026-02-26_GLW_HELD_POSITION_ONLY",
        "original_evaluation": inspect(JOINT / "evaluation_2026", "**/positions.parquet"),
        "saved_repair_versions": inspect(JOINT / "continuation_account_repair_r1/replay", "repair*/**/positions.parquet"),
        "interpretation": "Only HGB baseline 5/10/25bps held GLW on the disputed date in inspected saved account ledgers; all three remain quarantined before 2026-02-26.",
        "model_fit_calls": 0, "preprocessor_fit_calls": 0, "account_replay_calls": 0,
    }
    assert len(report["original_evaluation"]["matches"]) == 3
    assert len(report["saved_repair_versions"]["matches"]) == 3
    assert all("hgb_return_baseline" in row["path"]
               for section in ("original_evaluation", "saved_repair_versions")
               for row in report[section]["matches"])
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"original_files": report["original_evaluation"]["files_inspected"],
                      "repair_files": report["saved_repair_versions"]["files_inspected"],
                      "original_hits": len(report["original_evaluation"]["matches"])}))


if __name__ == "__main__":
    main()
