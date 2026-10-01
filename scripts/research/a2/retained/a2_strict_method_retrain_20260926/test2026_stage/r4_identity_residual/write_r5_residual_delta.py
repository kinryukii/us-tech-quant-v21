"""Write bounded r5 residual evidence without changing the frozen gate."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
STAGE = HERE.parent
GATE = STAGE / "r4_continuation" / "R4_FINAL_CANDIDATE_INPUT_GATE.parquet"
TASKS = STAGE / "r4_identity" / "NO_SAVED_RAW_43_CODE_TASKS.csv"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


gate = pd.read_parquet(GATE)
keys = ["signal_date", "quarter", "ticker", "cusip", "title_of_class", "moomoo_transport_code"]
prewarm = gate.loc[gate.final_input_gate.eq("UNKNOWN_121_HISTORY"), keys + [
    "raw_121_calendar_ready", "lookback_121_eligible", "final_input_gate"
]].copy()
assert len(prewarm) == 559 and prewarm[keys].duplicated().sum() == 0
prewarm["r5_disposition"] = "STILL_UNKNOWN_ORIGINAL_FIRST_TRADE_AND_121_BINDING_NOT_ALL_SAVED"
prewarm.loc[prewarm.ticker.eq("Q"), "r5_disposition"] = "STILL_UNKNOWN_Q_WI_TO_REGULAR_TRANSPORT_BINDING"
prewarm["r5_source_receipt"] = str(HERE / "FIRST_TRADE_ORIGINAL_FETCH_RECEIPTS.json")
prewarm.to_csv(HERE / "R5_PREWARM_559_EXACT_KEY_RESIDUAL.csv", index=False)

tasks = pd.read_csv(TASKS).fillna("")
others = tasks.loc[tasks.ticker.ne("OLPX")].copy()
assert len(others) == 42 and int(others.affected_candidate_days.sum()) == 2722
others["r5_disposition"] = "STILL_UNKNOWN_NO_SAVED_2026_RAW_OR_ORIGINAL_REHAB_PASS"
others["r5_note"] = "Prior provider subscription rejection is bounded evidence of access failure, not terminal lifecycle proof"
others.to_csv(HERE / "R5_OTHER42_NO_RAW_2722_DAY_RESIDUAL.csv", index=False)

olpx = gate.loc[gate.ticker.eq("OLPX") & gate.final_input_gate.eq("UNKNOWN_RAW_REHAB_OR_ALIAS_IDENTITY"),
                keys + ["final_input_gate"]].copy()
assert len(olpx) == 65
olpx["r5_raw_121_32_diagnostic"] = "PASS_NUMERIC_DIAGNOSTIC_ONLY"
olpx["r5_formal_status"] = "STILL_UNKNOWN_REHAB_PASS_OR_VENDOR_ZERO_EVENT_PROOF_MISSING"
olpx["r5_evidence"] = str(HERE / "OLPX_SAVED_RAW_FEATURE_REPORT.json")
olpx.to_csv(HERE / "R5_OLPX_65_EXACT_KEY_GATE_UNCHANGED.csv", index=False)

report = {
    "scope": "r5 bounded identity/Raw/121 residual; no parent ledger change",
    "parent_gate_sha256": sha(GATE),
    "prior_43_task_sha256": sha(TASKS),
    "olpx_65": {
        "raw_121_32_numeric_diagnostic": "pass",
        "formal_gate": "unknown",
        "reason": "No saved original vendor rehab PASS or independently proven no-event state; one bounded original OpenD rehab query returned unknown stock",
        "raw_report": str(HERE / "OLPX_SAVED_RAW_FEATURE_REPORT.json"),
        "raw_report_sha256": sha(HERE / "OLPX_SAVED_RAW_FEATURE_REPORT.json"),
        "source_hashes": str(HERE / "OLPX_SAVED_ANNUAL_SOURCE_HASHES.csv"),
        "source_hashes_sha256": sha(HERE / "OLPX_SAVED_ANNUAL_SOURCE_HASHES.csv"),
        "vendor_rehab_receipt": str(HERE / "OLPX_REHAB_SINGLE_QUERY_RECEIPT.json"),
        "vendor_rehab_receipt_sha256": sha(HERE / "OLPX_REHAB_SINGLE_QUERY_RECEIPT.json"),
    },
    "other_42_missing_raw": {"codes": 42, "candidate_days": 2722,
                             "saved_2026_raw_check": str(HERE / "R5_OTHER42_SAVED_2026_RAW_CHECK.json"),
                             "saved_2026_raw_check_sha256": sha(HERE / "R5_OTHER42_SAVED_2026_RAW_CHECK.json"),
                             "disposition": "unknown; no blanket lifecycle closure or replacement vendor"},
    "prewarm_559": {"codes": int(prewarm.ticker.nunique()), "candidate_days": 559,
                    "disposition": "unknown pending complete original first-trade and transport binding; Q WI ambiguity held"},
    "official_original_fetch": {
        "receipt": str(HERE / "FIRST_TRADE_ORIGINAL_FETCH_RECEIPTS.json"),
        "receipt_sha256": sha(HERE / "FIRST_TRADE_ORIGINAL_FETCH_RECEIPTS.json"),
        "attempts": 16, "saved": 2, "access_failures": 14,
        "note": "Issuer page access failure is not evidence of ineligibility; saved originals alone do not close 121 test"},
    "AZNCF_62": {"formal_gate": "unknown", "reason": "original ordinary-share CUSIP versus AZN ADS transport binding not proven"},
    "new_model_fit_calls": 0, "new_preprocessor_fit_calls": 0,
}
(HERE / "R5_IDENTITY_RAW_121_RESIDUAL_DELTA.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"prewarm_rows": len(prewarm), "other_codes": len(others),
                  "other_days": int(others.affected_candidate_days.sum()),
                  "olpx_rows": len(olpx)}, ensure_ascii=False))
