"""Append r7 exact-key 2026 input evidence without overwriting earlier results."""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE = HERE / "test2026_stage"
R7 = STAGE / "r7_applied"
CASH = STAGE / "r7_cash_first_event_proposal"
IPO = STAGE / "r7_prewarm_ipo"
DEST = Path(r"D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results\test2026\evidence_continuation_20260927_r7")

SOURCES = {
    "CLOSEOUT.md": R7 / "CLOSEOUT.md",
    "R7_FINAL_CANDIDATE_INPUT_GATE.parquet": R7 / "R7_FINAL_CANDIDATE_INPUT_GATE.parquet",
    "R7_REMAINING_CANDIDATE_GAPS.parquet": R7 / "R7_REMAINING_CANDIDATE_GAPS.parquet",
    "R7_811_CASH_STATUS_TRANSITIONS.parquet": R7 / "R7_811_CASH_STATUS_TRANSITIONS.parquet",
    "R7_53_IPO_121_STATUS_TRANSITIONS.parquet": R7 / "R7_53_IPO_121_STATUS_TRANSITIONS.parquet",
    "R7_GATE_SUMMARY.json": R7 / "R7_GATE_SUMMARY.json",
    "R7_SIGNAL_DATE_GATE_SUMMARY.csv": R7 / "R7_SIGNAL_DATE_GATE_SUMMARY.csv",
    "R7_QUARTER_GATE_SUMMARY.csv": R7 / "R7_QUARTER_GATE_SUMMARY.csv",
    "cash/CLOSEOUT.md": CASH / "CLOSEOUT.md",
    "cash/EVENT_SOURCES.json": CASH / "EVENT_SOURCES.json",
    "cash/R7_811_EXACT_KEY_PASS_PROPOSAL.parquet": CASH / "R7_811_EXACT_KEY_PASS_PROPOSAL.parquet",
    "cash/R7_TWELVE_CASH_EVENT_VERDICTS.csv": CASH / "R7_TWELVE_CASH_EVENT_VERDICTS.csv",
    "cash/R7_PROPOSAL_REPORT.json": CASH / "R7_PROPOSAL_REPORT.json",
    "cash/build_r7_exact_keys.py": CASH / "build_r7_exact_keys.py",
    "ipo/CLOSEOUT.md": IPO / "CLOSEOUT.md",
    "ipo/IPO_FIRST_TRADE_SOURCES.json": IPO / "IPO_FIRST_TRADE_SOURCES.json",
    "ipo/R7_53_IPO_ORIGINAL_121_INELIGIBLE_EXACT_KEYS.parquet": IPO / "R7_53_IPO_ORIGINAL_121_INELIGIBLE_EXACT_KEYS.parquet",
    "ipo/R7_IPO_121_PROPOSAL_REPORT.json": IPO / "R7_IPO_121_PROPOSAL_REPORT.json",
    "ipo/verify_two_ipo_121.py": IPO / "verify_two_ipo_121.py",
    "ipo/NIQ_FIRST_TRADE_ORIGINAL.html": STAGE / "r4_identity_residual/first_trade_originals/NIQ_FIRST_TRADE_ORIGINAL.html",
    "ipo/STUB_FIRST_TRADE_ORIGINAL.pdf": STAGE / "r4_identity_residual/first_trade_originals/STUB_FIRST_TRADE_ORIGINAL.pdf",
    "ipo/FIRST_TRADE_ORIGINAL_FETCH_RECEIPTS.json": STAGE / "r4_identity_residual/FIRST_TRADE_ORIGINAL_FETCH_RECEIPTS.json",
    "scripts/apply_r7_exact_evidence.py": HERE / "apply_r7_exact_evidence.py",
    "scripts/package_r7_exact_evidence.py": HERE / "package_r7_exact_evidence.py",
}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    assert not DEST.exists(), f"Refuse overwrite: {DEST}"
    summary = json.loads((R7 / "R7_GATE_SUMMARY.json").read_text("utf-8"))
    assert (summary["candidate_days"], summary["verified"], summary["proven_ineligible"], summary["remaining_unknown"]) == (111868, 62774, 2257, 46837)
    assert sha(R7 / "R7_FINAL_CANDIDATE_INPUT_GATE.parquet") == summary["r7_final_sha256"]
    parent = DEST.parent / "evidence_contract_correction_20260927_r6" / "R6_FULL_CANDIDATE_INPUT_GATE.parquet"
    assert sha(parent) == summary["parent_r6_sha256"]
    for path in SOURCES.values():
        assert path.is_file(), path
    DEST.mkdir(parents=False)
    rows = []
    for rel, source in SOURCES.items():
        target = DEST / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        digest = sha(source)
        assert sha(target) == digest, rel
        rows.append({"relative_path": rel, "bytes": target.stat().st_size, "sha256": digest})
    with (DEST / "R7_FILE_MANIFEST.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["relative_path", "bytes", "sha256"])
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"path": str(DEST), "files": len(rows), "bytes": sum(r["bytes"] for r in rows),
                      "final_ledger_sha256": summary["r7_final_sha256"]}))


if __name__ == "__main__":
    main()
