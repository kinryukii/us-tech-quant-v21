"""Bind five public dividend announcements to exact first-event candidate keys."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
R3 = Path(r"D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results\test2026\identity_feature_application_20260926_r3")

sources = {
    "US.GEV": ("2025-12-09", "https://www.gevernova.com/news/press-releases/ge-vernova-declares-increased-first-quarter-2026-dividend-increases-buyback-authorization", "raw_second/GEV_2025_12_09_DIVIDEND.html", "ISSUER_ORIGINAL_BYTES_RECORD_DATE_ONLY"),
    "US.JPM": ("2025-12-09", "https://www.jpmorganchase.com/ir/news/2025/jpmc-declares-common-stock-dividend-12-9", "raw_second/JPM_2025_12_09_DIVIDEND.html", "ISSUER_ANNOUNCEMENT_BYTES_PLUS_DIRECT_ISSUER_HISTORY_RENDER"),
    "US.MA": ("2025-12-09", "https://s25.q4cdn.com/479285134/files/doc_news/Mastercard-Board-of-Directors-Announces-Quarterly-Dividend-and-14-Billion-Share-Repurchase-Program-2025.pdf", "raw_second/MA_2025_12_09_original.pdf", "ISSUER_ORIGINAL_BYTES_RECORD_DATE_ONLY"),
    "US.MRVL": ("2025-12-12", "https://investor.marvell.com/sec-filings/all-sec-filings/content/0001628280-25-056774/marvelltechnologyinc_divid.htm", "raw_second/MRVL_2025_12_12_SEC_EX99_1.html", "ISSUER_ORIGINAL_BYTES_RECORD_DATE_ONLY"),
    "US.ORCL": ("2025-12-10", "https://s23.q4cdn.com/440135859/files/doc_earnings/2026/q2/earnings-result/2q26-pressrelease-final.pdf", "raw_second/ORCL_2025_12_10_original.pdf", "ISSUER_ORIGINAL_BYTES_RECORD_DATE_ONLY"),
}
first = {
    "US.GEV": "2026-01-05",
    "US.JPM": "2026-01-06",
    "US.MA": "2026-01-09",
    "US.MRVL": "2026-01-09",
    "US.ORCL": "2026-01-09",
}
events = pd.read_parquet(R3 / "CONSUMED_REHAB_EVENT_AUDIT.parquet")
events = events.loc[events.audit_kind.eq("APPLIED_CORPORATE_ACTION")]
candidates = pd.read_parquet(R3 / "FINAL_111868_CANDIDATE_INPUT_GATE.parquet")
range_table = pd.read_parquet(HERE / "EVENT_SECURITY_DECISION_RANGES.parquet")
checks = ["raw_on_signal", "rehab_pass", "coordinate_match", "has_32_finite", "version_checked", "lookback_121_eligible"]
rows = []
keys = []
for code, event_day in first.items():
    declared, url, rel, tier = sources[code]
    path = HERE / rel
    assert path.exists(), path
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    event_date = pd.Timestamp(event_day)
    next_date = events.loc[events.original_code.eq(code) & events.event_date.gt(event_date), "event_date"].min()
    assert pd.notna(next_date)
    x = range_table.loc[range_table.original_code.eq(code) & range_table.source_event_date.eq(event_date)].iloc[0]
    assert bool(x.simple_cash_floor_matches_vendor)
    block = candidates.loc[candidates.moomoo_transport_code.eq(code) & candidates.signal_date.ge(event_date) & candidates.signal_date.lt(next_date)].copy()
    assert len(block) > 0 and block[checks].all().all()
    assert not block.proven_lifecycle_ineligible.any()
    assert not block.multi_cusip_transport_interval_pending.any()
    assert block.final_input_gate.eq("UNKNOWN_CONSUMED_2026_EVENT_PUBLICATION_TIME").all()
    official_ex = code == "US.JPM"
    block["r4_event_code"] = code
    block["r4_event_date"] = event_day
    block["r4_next_unproved_event_exclusive"] = str(next_date.date())
    block["r4_primary_original_sha256"] = sha
    block["r4_announcement_has_explicit_exdate"] = False
    block["r4_direct_issuer_history_has_explicit_exdate"] = official_ex
    block["r4_direct_history_original_bytes_saved"] = False
    block["r4_value_floor5_reproduced"] = True
    block["r4_formal_gate_upgrade"] = False
    block["r4_reason"] = "JPM_EXDATE_DIRECT_PRIMARY_RENDER_ONLY_HISTORY_BYTES_UNAVAILABLE" if official_ex else "ISSUER_ANNOUNCEMENT_RECORD_DATE_ONLY"
    keys.append(block[["cusip", "title_of_class", "quarter", "signal_date", "ticker", "moomoo_transport_code", "r4_event_code", "r4_event_date", "r4_next_unproved_event_exclusive", "r4_primary_original_sha256", "r4_announcement_has_explicit_exdate", "r4_direct_issuer_history_has_explicit_exdate", "r4_direct_history_original_bytes_saved", "r4_value_floor5_reproduced", "r4_formal_gate_upgrade", "r4_reason"]])
    rows.append({"original_code": code, "cusip": x.cusip, "title_of_class": x.title_of_class, "event_date_from_vendor_rehab": event_day, "issuer_public_date": declared,
                 "issuer_original_url": url, "issuer_original_path": str(path), "issuer_original_sha256": sha, "issuer_original_bytes": path.stat().st_size,
                 "evidence_tier": tier, "issuer_announcement_explicit_exdate": False, "direct_primary_history_explicit_exdate": official_ex,
                 "direct_history_url": "https://jpmorganchaseco.gcs-web.com/ir/shareholder-information/dividend-history?field_nir_div_year_value=1977" if official_ex else "",
                 "direct_history_original_bytes_saved": False, "direct_history_row": "Declared 12/9/2025 | Ex-Date 1/6/2026 | Record 1/6/2026 | Payable 1/31/2026 | Amount 1.50" if official_ex else "",
                 "cash_dividend": float(x.total_cash_div), "prior_raw_date": str(x.prior_raw_date)[:10], "prior_raw_close": float(x.prior_raw_close),
                 "consumed_factor_a": float(x.factor_a), "cash_floor5_factor_a": float(x.simple_cash_floor_a_5), "cash_factor_exact": bool(x.simple_cash_floor_matches_vendor),
                 "next_unproved_event_exclusive": str(next_date.date()), "candidate_first": str(block.signal_date.min().date()), "candidate_last": str(block.signal_date.max().date()),
                 "exact_candidate_days": len(block), "all_other_r3_input_checks_pass": True, "historical_vendor_version_receipt": False,
                 "formal_candidate_gate_upgrade": False,
                 "unresolved": "Issuer announcement has record date only; direct history has explicit ex-date but original HTTP body could not be retained" if official_ex else "Issuer original records amount and record date, not explicit ex-date"})

verdicts = pd.DataFrame(rows)
overlay = pd.concat(keys, ignore_index=True)
assert len(overlay) == 294 and not overlay.duplicated(["cusip", "title_of_class", "quarter", "signal_date"]).any()
verdicts.to_csv(HERE / "SECOND_TRANCHE_PRIMARY_EVENT_VERDICTS.csv", index=False)
overlay.to_parquet(HERE / "SECOND_TRANCHE_294_EXACT_CANDIDATE_KEYS.parquet", index=False)
report = {
    "events": len(verdicts), "exact_first_event_candidate_keys": len(overlay), "event_only_value_reproduced_keys": len(overlay),
    "saved_issuer_original_bodies": len(verdicts), "saved_original_bodies_with_explicit_exdate": 0,
    "direct_primary_render_exdate_keys_without_saved_history_bytes": int(overlay.r4_direct_issuer_history_has_explicit_exdate.sum()),
    "formal_candidate_gate_upgrades": 0,
    "raw_and_factor_32_feature_and_121_checks": "All true in r3 for these exact 294 rows; original full-vs-prefix rebuild not rerun in this tranche",
    "decision": "Five issuer originals support preannouncement and cash amount; original Raw previous closes reproduce each consumed vendor A factor. The originals state record dates, not explicit ex-dates. JPM issuer dividend-history direct page explicitly states ex-date but its HTTP body could not be saved after bounded attempts. Preserve source hierarchy and leave parent formal candidate ledger unchanged.",
}
(HERE / "SECOND_TRANCHE_PRIMARY_REPORT.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(report, indent=2, ensure_ascii=False))
