"""Append the validated r6 input-gate correction without touching older outputs."""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE = HERE / "test2026_stage"
R6 = STAGE / "r6_contract_correction"
DEST = Path(r"D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results\test2026\evidence_contract_correction_20260927_r6")

SOURCES = {
    "CLOSEOUT.md": R6 / "CLOSEOUT.md",
    "R6_FULL_CANDIDATE_INPUT_GATE.parquet": R6 / "R6_FULL_CANDIDATE_INPUT_GATE.parquet",
    "R6_REMAINING_CANDIDATE_GAPS.parquet": R6 / "R6_REMAINING_CANDIDATE_GAPS.parquet",
    "R6_SIGNAL_DATE_GATE_SUMMARY.csv": R6 / "R6_SIGNAL_DATE_GATE_SUMMARY.csv",
    "R6_QUARTER_GATE_SUMMARY.csv": R6 / "R6_QUARTER_GATE_SUMMARY.csv",
    "R6_GATE_SUMMARY.json": R6 / "R6_GATE_SUMMARY.json",
    "R6_CASH_APPLICATION_REPORT.json": R6 / "R6_CASH_APPLICATION_REPORT.json",
    "R6_SINGLE_EVENT_APPLICATION_REPORT.json": R6 / "R6_SINGLE_EVENT_APPLICATION_REPORT.json",
    "R6_TEN_CASH_EVENTS_585_STATUS_TRANSITIONS.parquet": R6 / "R6_TEN_CASH_EVENTS_585_STATUS_TRANSITIONS.parquet",
    "R6_FOUR_SINGLE_EVENTS_511_STATUS_TRANSITIONS.parquet": R6 / "R6_FOUR_SINGLE_EVENTS_511_STATUS_TRANSITIONS.parquet",
    "FOUR_SINGLE_EVENTS_511_EXACT_KEY_PROOF.parquet": R6 / "FOUR_SINGLE_EVENTS_511_EXACT_KEY_PROOF.parquet",
    "FOUR_SINGLE_EVENT_PRIMARY_VERDICTS.json": R6 / "FOUR_SINGLE_EVENT_PRIMARY_VERDICTS.json",
    "FOUR_SINGLE_EVENT_FETCH_RECEIPTS.json": R6 / "FOUR_SINGLE_EVENT_FETCH_RECEIPTS.json",
    "TEN_CASH_EVENTS_585_EXACT_KEY_PASS_PROPOSAL.parquet": STAGE / "r4_event_pit" / "TEN_CASH_EVENTS_585_EXACT_KEY_PASS_PROPOSAL.parquet",
    "TEN_CASH_EVENTS_ORIGINAL_CONTRACT_VERDICTS.csv": STAGE / "r4_event_pit" / "TEN_CASH_EVENTS_ORIGINAL_CONTRACT_VERDICTS.csv",
    "TEN_CASH_EVENTS_ORIGINAL_CONTRACT_REPORT.json": STAGE / "r4_event_pit" / "TEN_CASH_EVENTS_ORIGINAL_CONTRACT_REPORT.json",
    "TEN_CASH_EVENTS_CONTRACT_REVIEW.md": STAGE / "r4_event_pit" / "TEN_CASH_EVENTS_CONTRACT_REVIEW.md",
    "R5_UNKNOWN_CUMULATIVE_2026_EVENT_EXPOSURES.parquet": STAGE / "r5_dependency_analysis" / "R5_UNKNOWN_CUMULATIVE_2026_EVENT_EXPOSURES.parquet",
    "finra_rule_11140_2026_snapshot.html": STAGE / "finra_rule_11140_2026_snapshot.html",
    "scripts/apply_r6_cash_contract_evidence.py": HERE / "apply_r6_cash_contract_evidence.py",
    "scripts/apply_r6_four_single_events.py": HERE / "apply_r6_four_single_events.py",
    "scripts/finalize_r6_contract_gate.py": HERE / "finalize_r6_contract_gate.py",
    "scripts/package_r6_contract_correction.py": HERE / "package_r6_contract_correction.py",
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    assert not DEST.exists(), f"Refuse overwrite: {DEST}"
    gate = json.loads((R6 / "R6_GATE_SUMMARY.json").read_text("utf-8"))
    assert (gate["candidate_days"], gate["verified"], gate["proven_ineligible"], gate["remaining_unknown"]) == (111868, 61963, 2204, 47701)
    assert gate["r6_final_sha256"] == digest(R6 / "R6_FULL_CANDIDATE_INPUT_GATE.parquet")
    parent = DEST.parent / "evidence_continuation_20260927_r5" / "R5_FINAL_CANDIDATE_INPUT_GATE.parquet"
    assert gate["parent_r5_sha256"] == digest(parent)
    for source in SOURCES.values():
        assert source.is_file(), source
    DEST.mkdir(parents=False)
    rows = []
    for rel, source in SOURCES.items():
        target = DEST / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        before = digest(source)
        after = digest(target)
        assert before == after, rel
        rows.append({"relative_path": rel, "bytes": target.stat().st_size, "sha256": after})
    with (DEST / "R6_FILE_MANIFEST.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["relative_path", "bytes", "sha256"])
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"path": str(DEST), "files": len(rows), "bytes": sum(r["bytes"] for r in rows),
                      "final_ledger_sha256": gate["r6_final_sha256"]}))


if __name__ == "__main__":
    main()
