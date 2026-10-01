"""Bounded local-only check for five high-impact 2026 cash events."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
R3 = Path(r"D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results\test2026\identity_feature_application_20260926_r3")
PRIOR = Path(r"C:\Users\Lenovo\Documents\CODING开发\a2_13f_learned_sizing_pre2026_test2026_r1\continuation_2026_r1")
IDENTITY = HERE.parent / "r4_identity"
R31 = Path(r"D:\us-tech-quant-results\massive_r3_remaining31_external_authority_r2\20260903T131804Z\raw")
CODES = ["US.GEV", "US.JPM", "US.MA", "US.MRVL", "US.ORCL"]

events = pd.read_parquet(R3 / "CONSUMED_REHAB_EVENT_AUDIT.parquet")
events = events.loc[events.audit_kind.eq("APPLIED_CORPORATE_ACTION") & events.event_date.between("2026-01-02", "2026-09-22")]
candidate = pd.read_parquet(R3 / "FINAL_111868_CANDIDATE_INPUT_GATE.parquet")
ranges = pd.read_parquet(HERE / "EVENT_SECURITY_DECISION_RANGES.parquet")

search_roots = [HERE / "raw", IDENTITY, PRIOR, R31]
names = {
    "US.GEV": ["GEV", "GE_VERNOVA", "GEVERNOVA"],
    "US.JPM": ["JPM", "JPMORGAN"],
    "US.MA": ["MA_DIVIDEND", "MASTERCARD"],
    "US.MRVL": ["MRVL", "MARVELL"],
    "US.ORCL": ["ORCL", "ORACLE"],
}
rows = []
for code in CODES:
    code_events = events.loc[events.original_code.eq(code)].sort_values("event_date")
    event = code_events.iloc[0]
    next_date = code_events.event_date.iloc[1] if len(code_events) > 1 else pd.Timestamp("2026-09-23")
    r = ranges.loc[ranges.original_code.eq(code) & ranges.applied_event_date.eq(event.event_date)].iloc[0]
    keys = candidate.loc[candidate.moomoo_transport_code.eq(code) & candidate.signal_date.ge(event.event_date) & candidate.signal_date.lt(next_date)]
    exact = []
    for root in search_roots:
        if not root.exists():
            continue
        for p in root.iterdir():
            if p.is_file() and p.suffix.lower() in {".html", ".htm", ".pdf", ".txt"} and any(term in p.name.upper() for term in names[code]):
                exact.append(str(p))
    rows.append({
        "original_code": code, "original_cusip": r.cusip, "original_class": r.title_of_class,
        "event_date": str(event.event_date.date()), "factor_a": float(event.factor_a), "factor_b": float(event.factor_b),
        "saved_rehab_cash_amount": float(r.total_cash_div), "prior_original_raw_date": r.prior_raw_date,
        "prior_original_raw_close": float(r.prior_raw_close),
        "simple_cash_factor_floor5_matches": bool(r.simple_cash_floor_matches_vendor),
        "next_unproved_event_date": str(next_date.date()),
        "first_interval_candidate_days": len(keys),
        "first_interval_signal_first": str(keys.signal_date.min().date()),
        "first_interval_signal_last": str(keys.signal_date.max().date()),
        "local_primary_event_original_paths": " | ".join(exact),
        "local_primary_original_found": bool(exact),
        "public_amount_historical_time": "UNVERIFIED_NO_TARGETED_LOCAL_PRIMARY",
        "independently_proven_ex_date": "UNVERIFIED_NO_TARGETED_LOCAL_PRIMARY",
        "event_dependency_closed": False,
        "candidate_status_change": "NONE",
    })

out = pd.DataFrame(rows)
assert len(out) == 5 and not out.local_primary_original_found.any()
out.to_csv(HERE / "SECOND_TRANCHE_FIVE_LOCAL_ONLY_AUDIT.csv", index=False)
report = {
    "targets": CODES,
    "first_event_candidate_days_to_next_event": int(out.first_interval_candidate_days.sum()),
    "matching_cash_factor_arithmetic": int(out.simple_cash_factor_floor5_matches.sum()),
    "saved_issuer_sec_exchange_originals_for_these_events": int(out.local_primary_original_found.sum()),
    "candidate_days_closed": 0,
    "checked_directories": [str(x) for x in search_roots],
    "not_counted_as_event_original": "Existing Raw/rebhab snapshots and Q2 source/identity receipts do not establish the original issuer declaration amount/time or ex date for these five 2026 events.",
    "decision": "No local event primary body was found in the scoped saved assets. The factor arithmetic confirms numerical consistency only. Do not upgrade any candidate key or infer publication time from the ex-date. No network request was made for this tranche.",
    "model_fit_calls": 0,
    "preprocessor_fit_calls": 0,
}
(HERE / "SECOND_TRANCHE_FIVE_LOCAL_ONLY_REPORT.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(report, indent=2, ensure_ascii=False))
