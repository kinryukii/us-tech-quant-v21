"""Read-only gate against the existing old R1 input continuation; no test return is computed."""
from __future__ import annotations

import hashlib
import json

import pandas as pd

from policy_engine import HERE


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    old = HERE.parent / "a2_13f_learned_sizing_pre2026_test2026_r1" / "continuation_2026_r1"
    manifest_path = old / "CONTINUATION_MANIFEST.json"
    csv_path = old / "REMAINING75_RESOLUTION.csv"
    audit_path = old / "REMAINING75_INPUT_AUDIT.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = pd.read_csv(csv_path)
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    frozen = json.loads((HERE / "RUN_MANIFEST.json").read_text(encoding="utf-8"))
    if manifest["fixed_test_asof"] != frozen["test_asof"]:
        raise RuntimeError("TEST_ASOF_CHANGED")
    unknown_rows = rows.loc[rows.unknown_days.gt(0)]
    count = int(unknown_rows.unknown_days.sum())
    outside = int(audit["outside_remaining75_unknown_candidate_days"])
    if (len(unknown_rows) != audit["remaining_unknown_codes"] or
        count != audit["remaining75_unknown_candidate_days"] or
        count + outside != audit["unknown_candidate_days"]):
        raise RuntimeError("LATEST_GAP_FILES_DISAGREE")
    if manifest["formal_2026_scope"]["partial_top20_status"] != "LOCAL_PRICE_SUBSET_CACHE_ONLY":
        raise RuntimeError("PARTIAL_SIGNAL_STATUS_CHANGED_REVIEW_REQUIRED")
    if any((HERE / p).exists() for p in ("TEST2026_POLICY_DAILY.parquet", "TEST2026_PREDICTIONS.parquet")):
        raise RuntimeError("FORMAL_2026_OUTPUT_EXISTS_REVIEW_REQUIRED")
    newest = unknown_rows[["original_code", "original_cusip", "unknown_days", "still_needed_signal_dates"]].copy()
    newest = newest.sort_values(["unknown_days", "original_code"], ascending=[False, True])
    output = {
        "status": "WAITING_TEST_INPUT" if count + outside else "NEEDS_FULL_INPUT_VALIDATION",
        "formal_2026_reveals": 0,
        "fixed_test_asof": frozen["test_asof"],
        "source": {p.name: {"path": str(p), "sha256": sha(p),
                             "last_write_unix_seconds": p.stat().st_mtime}
                   for p in (manifest_path, csv_path, audit_path)},
        "remaining75_rows": len(rows), "remaining75_codes_with_unknown": len(unknown_rows),
        "unknown_candidate_days_in_75_csv": count,
        "outside75_unknown_candidate_days": outside,
        "unknown_candidate_days_full_pool": count + outside,
        "candidate_status_complete_days_not_full_test_input": int(audit["candidate_state_complete_days_not_full_test_input"]),
        "partial_top20_status": manifest["formal_2026_scope"]["partial_top20_status"],
        "asof_company_action_version_qualified": bool(manifest["remaining75_resolution"]["asof_rehab_version_qualified"]),
        "formal_candidate_comparison_qualified": False,
        "formal_continuous_accounting_qualified": False,
        "top_unresolved_codes": newest.head(10).to_dict("records"),
        "remaining_code_dates_source": str(csv_path),
        "outside75_keys_source": str(audit_path),
        "old_manifest_legacy_4080_field": manifest["remaining75_resolution"]["unknown_candidate_days"],
        "legacy_field_note": "Earlier snapshot retained in old manifest; current 2830+768=3598 is supported by current CSV/audit.",
        "formal_policies_executed": False,
    }
    (HERE / "TEST2026_INPUT_GATE.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": output["status"], "unknown_codes": len(unknown_rows),
                      "unknown_candidate_days": count + outside,
                      "candidate_status_complete_days": output["candidate_status_complete_days_not_full_test_input"], "formal_reveals": 0}))


if __name__ == "__main__":
    main()
