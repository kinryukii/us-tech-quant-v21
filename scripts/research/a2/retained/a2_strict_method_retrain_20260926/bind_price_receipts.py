"""Bind prior same-source receipts to this batch's fixed clock and new Raw."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OTHER = HERE.parent / "a2_13f_learned_sizing_pre2026_test2026_r1" / "continuation_2026_r1"
OUT = HERE / "test2026_stage" / "fixed_window_binding"
RAW_RECEIPT = HERE / "test2026_stage" / "fixed_window_raw" / "FIXED_WINDOW_RAW_RECEIPT.json"
ASOF = datetime.fromisoformat("2026-09-25T18:10:21.6494935+00:00")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    names = ["SUBSCRIPTION_PILOT_RECEIPT.json", "SUBSCRIPTION_BATCH_RECEIPT.json",
             "SUBSCRIPTION_TARGETED_RECEIPT.json", "SUBSCRIPTION_ADJUSTED_OVERLAP_CHECK.json",
             "Q2_INTAKE_AUDIT.json", "REMAINING75_RESOLUTION.csv", "REMAINING75_INPUT_AUDIT.json"]
    receipts = {name: sha(OTHER / name) for name in names}
    pilot, batch, targeted, overlap = [json.loads((OTHER / name).read_text(encoding="utf-8")) for name in names[:4]]
    timestamps = [pilot["requested_at_utc"], batch["started_at_utc"], targeted["started_at_utc"]]
    assert all(datetime.fromisoformat(s.replace("Z", "+00:00")) < ASOF for s in timestamps)
    assert pilot["subscription_type"] == batch["ktype"] == targeted["ktype"] == "K_DAY"
    assert batch["autype"] == targeted["autype"] == "NONE"
    assert batch["session"] == targeted["session"] == "RTH"
    assert overlap["exact_overlap"] is True
    prior = pd.read_csv(OTHER / "SUBSCRIPTION_RAW_FILES_MANIFEST.csv")
    assert len(prior) == 533 and prior.code.is_unique
    assert prior.kline_type.eq("K_DAY").all() and prior.autype.eq("NONE").all() and prior.session.eq("RTH").all()
    assert prior.last_date.le("2026-09-22").all() and prior.post_cutoff_rows_in_file.eq(0).all()
    current = json.loads(RAW_RECEIPT.read_text(encoding="utf-8"))
    assert current["test_asof_utc"] == "2026-09-25T18:10:21.6494935Z"
    status = pd.Series([r["status"] for r in current["records"]]).value_counts().to_dict()
    tail = [r for r in current["records"] if r.get("has_09_23") and r.get("has_09_24")]
    pre_asof_tail_codes = sorted({r["code"] for d in (pilot, batch, targeted)
        for r in d.get("codes", d.get("records", [])) if r.get("last_returned_date", "") >= "2026-09-24"})
    rehab_paths = [Path(r"D:\us-tech-quant-cache\13f_pit_v1\a_a2_quarterly_13f_r1\rehab_factors.parquet")]
    rehab_paths += sorted(OTHER.glob("REHAB_*_ONLY/rehab_factors.parquet"))
    rehab = []
    for p in rehab_paths:
        modified = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
        rehab.append({"path": str(p), "sha256": sha(p), "filesystem_modified_utc": modified.isoformat(),
                      "modified_before_current_test_asof": modified < ASOF})
    report = {
        "status": "PRIOR_RAW_BOUND_CURRENT_TAIL_INPUT_ONLY_PIT_AND_FORMAL_ELIGIBILITY_PENDING",
        "test_asof_utc": current["test_asof_utc"],
        "prior_other_task_cutoff_not_imported": "2026-09-22",
        "prior_raw_file_count": len(prior),
        "prior_raw_manifest_sha256": sha(OTHER / "SUBSCRIPTION_RAW_FILES_MANIFEST.csv"),
        "prior_raw_k_day_none_rth": True,
        "prior_raw_observed_before_this_asof": True,
        "prior_raw_terminal_date_max": str(prior.last_date.max()),
        "codes_with_09_24_returned_before_this_asof_count": len(pre_asof_tail_codes),
        "codes_with_09_24_returned_before_this_asof": pre_asof_tail_codes,
        "prior_adjusted_overlap_rows": int(overlap["overlap_rows"]),
        "prior_adjusted_overlap_codes": int(overlap["overlap_codes"]),
        "prior_adjusted_overlap_exact": True,
        "prior_adjusted_overlap_does_not_certify_new_dates": True,
        "current_raw_fetch_started_utc": current["request_started_utc"],
        "current_raw_fetch_after_test_asof": datetime.fromisoformat(current["request_started_utc"]) > ASOF,
        "current_raw_target_count": current["target_count"],
        "current_raw_record_count": len(current["records"]),
        "current_raw_status_counts": status,
        "current_raw_codes_with_both_09_23_and_09_24": len(tail),
        "current_raw_fetch_receipt_sha256": sha(RAW_RECEIPT),
        "rehab_snapshots": rehab,
        "rehab_publication_clock_gap": "Retrieved source snapshots lack per-event historical publication timestamps; filesystem time only binds local possession",
        "current_tail_asof_availability_gap": "Prior receipts show 09-24 provider returns for the listed codes before this ASOF, but omitted their values; other codes have no equivalent pre-ASOF receipt",
        "not_approved": ["unverified_uid_or_share_class", "missing_raw_or_121_prewarm", "event_version_clock", "execution_open", "held_position_valuation"],
        "source_receipt_sha256": receipts,
        "new_model_fit_calls": 0, "new_preprocessor_fit_calls": 0,
    }
    (OUT / "PRICE_SOURCE_BINDING.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"current_raw_record_count": report["current_raw_record_count"],
                      "current_raw_codes_with_both_tail_dates": len(tail), "status_counts": status}))


if __name__ == "__main__":
    main()
