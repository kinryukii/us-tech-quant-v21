"""Derive exact Jan-2 event-only intervals before each next unproved event."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
R3 = Path(r"D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results\test2026\identity_feature_application_20260926_r3")
e = pd.read_parquet(R3 / "CONSUMED_REHAB_EVENT_AUDIT.parquet")
e = e.loc[e.audit_kind.eq("APPLIED_CORPORATE_ACTION") & e.event_date.between("2026-01-02", "2026-09-22")]
c = pd.read_parquet(R3 / "FINAL_111868_CANDIDATE_INPUT_GATE.parquet")
first = pd.read_csv(HERE / "FIRST_TRANCHE_PRIMARY_EVENT_AND_VALUE_PROOF.csv")
rows = []
exact = []
official_exdate = {"US.FERG": True, "US.AXP": False, "US.ROP": True, "US.APD": False, "US.PGR": False}
raw_body_saved = {"US.FERG": False, "US.AXP": True, "US.ROP": False, "US.APD": False, "US.PGR": False}
checks = ["raw_on_signal", "rehab_pass", "coordinate_match", "has_32_finite", "version_checked"]
for item in first.itertuples():
    code = item.original_code
    next_date = e.loc[e.original_code.eq(code) & e.event_date.gt(pd.Timestamp("2026-01-02")), "event_date"].min()
    block = c.loc[c.moomoo_transport_code.eq(code) & c.signal_date.ge(pd.Timestamp("2026-01-02")) & c.signal_date.lt(next_date)].copy()
    assert len(block) > 0 and block[checks].all().all()
    assert block.lookback_121_eligible.astype(bool).all()
    assert ~block.proven_lifecycle_ineligible.any() and ~block.multi_cusip_transport_interval_pending.any()
    assert block.final_input_gate.eq("UNKNOWN_CONSUMED_2026_EVENT_PUBLICATION_TIME").all()
    block["r4_event_tranche"] = "JAN02_PUBLIC_CASH_VALUE_REPRODUCED_BEFORE_NEXT_EVENT"
    block["r4_event_only_safe_through"] = str(block.signal_date.max().date())
    block["r4_first_next_unproved_event"] = str(next_date.date())
    block["r4_official_exdate_explicit"] = official_exdate[code]
    block["r4_saved_original_http_body"] = raw_body_saved[code]
    block["r4_public_reconstructibility_verdict"] = "PASS_UNDER_ORIGINAL_FORWARD_PIT_SEMANTICS"
    block["r4_historical_vendor_version_receipt"] = "NOT_AVAILABLE_NOT_EXPLICIT_ORIGINAL_GATE"
    exact.append(block[["cusip", "title_of_class", "quarter", "signal_date", "ticker", "moomoo_transport_code", "r4_event_tranche", "r4_event_only_safe_through", "r4_first_next_unproved_event", "r4_official_exdate_explicit", "r4_saved_original_http_body", "r4_public_reconstructibility_verdict", "r4_historical_vendor_version_receipt"]])
    rows.append({"original_code": code, "cusip": item.cusip, "first_event_date": "2026-01-02", "public_source_date": item.source_public_date,
                 "first_next_unproved_event": str(next_date.date()), "safe_signal_first": str(block.signal_date.min().date()), "safe_signal_last": str(block.signal_date.max().date()),
                 "candidate_days": len(block), "official_exdate_explicit_in_source": official_exdate[code], "saved_original_http_body": raw_body_saved[code],
                 "cash_value_exact_vendor_factor_by_floor5": bool(item.factor_arithmetic_exact_floor5),
                 "original_builder_requires_vendor_historical_receipt": False,
                 "unknown_vendor_actual_historical_version": True})
pd.DataFrame(rows).to_csv(HERE / "FIRST_TRANCHE_EVENT_ONLY_SAFE_INTERVALS.csv", index=False)
pd.concat(exact, ignore_index=True).to_parquet(HERE / "FIRST_TRANCHE_291_EXACT_CANDIDATE_KEYS.parquet", index=False)
summary = {"event_only_safe_candidate_days": sum(row["candidate_days"] for row in rows),
           "official_exdate_explicit_candidate_days": sum(row["candidate_days"] for row in rows if row["official_exdate_explicit_in_source"]),
           "issuer_record_date_only_candidate_days": sum(row["candidate_days"] for row in rows if not row["official_exdate_explicit_in_source"]),
           "original_http_body_saved_candidate_days": sum(row["candidate_days"] for row in rows if row["saved_original_http_body"]),
           "full_window_candidate_days_closed": 0,
           "interpretation": "The original builder and frozen test contract do not explicitly require a historical vendor-version receipt. Exact public cash values plus the previous saved Raw close reproduce each consumed A value before the first affected signal. This gives a 291-key value-proof interval through, but excluding, each next unproved event. Only FERG/ROP directly inspected primary pages explicitly label Jan-2 ex-date (106 keys); APD/AXP/PGR announcements state record date while original vendor rehab supplies ex-date (185 keys). AXP dynamic issuer dividend table search snippet is not counted as directly inspected row. Reevaluate ex-date evidence and all other dependencies before candidate PASS. Historical vendor actual receipt is unknown and is not claimed."}
(HERE / "FIRST_TRANCHE_INTERVAL_REPORT.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(summary, indent=2, ensure_ascii=False))
