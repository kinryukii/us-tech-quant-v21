"""Bind five preannounced dividend events to exact saved factor and Raw values."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
events = pd.read_parquet(HERE / "EVENT_SECURITY_DECISION_RANGES.parquet")
extract = HERE / "PRIMARY_SOURCE_WEB_EXTRACTS.md"
extract_sha = hashlib.sha256(extract.read_bytes()).hexdigest()
source = {
    "US.APD": ("2025-11-20", "https://investors.airproducts.com/static-files/c828aa86-b3a8-4dfb-97b9-dee499c4d136", "issuer 2025 annual report records board declaration 2025-11-19"),
    "US.FERG": ("2025-12-09", "https://www.sec.gov/Archives/edgar/data/2011641/000201164125000057/exhibit991pressreleaseocto.htm", "SEC-hosted issuer exhibit dated 2025-12-09"),
    "US.AXP": ("2025-12-17", "https://ir.americanexpress.com/news/investor-relations-news/investor-relations-news-details/2025/American-Express-Declares-Regular-Quarterly-Dividend-on-Common-Shares/default.aspx", "issuer release dated 2025-12-17"),
    "US.ROP": ("2025-11-05", "https://investors.ropertech.com/stock-information/dividends-splits", "issuer dividend table records declaration 2025-11-05"),
    "US.PGR": ("2025-12-08", "https://investors.progressive.com/financials/financial-news-releases/news-details/2025/Progressive-Announces-Dividend-Information-And-2026-Annual-Meeting-Record-Date/default.aspx", "issuer release dated 2025-12-08, including 13.50 annual and 0.10 quarterly cash dividends"),
}
selected = events.loc[events.original_code.isin(source) & events.source_event_date.eq(pd.Timestamp("2026-01-02"))].copy()
selected = selected.drop_duplicates(["original_code", "cusip", "source_event_date", "factor_a", "factor_b"])
selected["source_public_date"] = selected.original_code.map(lambda x: source[x][0])
selected["primary_source_url"] = selected.original_code.map(lambda x: source[x][1])
selected["source_description"] = selected.original_code.map(lambda x: source[x][2])
selected["saved_web_rendered_excerpt_sha256"] = extract_sha
selected["factor_arithmetic_exact_floor5"] = selected.simple_cash_floor_matches_vendor.astype(bool)
selected["public_amount_and_record_or_exdate_by_signal"] = "PROVEN_ON_OR_BEFORE_FIRST_SIGNAL"
selected["issuer_explicit_exdate"] = selected.original_code.map({"US.FERG": True, "US.AXP": False, "US.ROP": True, "US.APD": False, "US.PGR": False})
selected["prior_raw_close_date_by_signal"] = selected.prior_raw_date.astype(str)
selected["vendor_factor_value_at_historical_signal"] = "NOT_PROVEN_BY_VENDOR_SNAPSHOT"
selected["vendor_factor_version_at_historical_signal"] = "NOT_PROVEN_BY_VENDOR_SNAPSHOT"
selected["r3_candidate_gate_change"] = "NONE_IN_THIS_EVIDENCE_FILE_PARENT_LEDGER_RECOMPUTES_ALL_DEPENDENCIES"
cols = ["original_code", "cusip", "title_of_class", "source_event_date", "factor_a", "factor_b", "per_cash_div", "special_dividend", "total_cash_div", "prior_raw_date", "prior_raw_close", "simple_cash_expected_a", "simple_cash_floor_a_5", "factor_arithmetic_exact_floor5", "source_public_date", "primary_source_url", "source_description", "saved_web_rendered_excerpt_sha256", "public_amount_and_record_or_exdate_by_signal", "issuer_explicit_exdate", "vendor_factor_value_at_historical_signal", "vendor_factor_version_at_historical_signal", "r3_candidate_gate_change"]
selected[cols].to_csv(HERE / "FIRST_TRANCHE_PRIMARY_EVENT_AND_VALUE_PROOF.csv", index=False)
assert len(selected) == 5
assert selected.factor_arithmetic_exact_floor5.all()
report = {
    "first_tranche_events": len(selected),
    "all_public_event_amount_dates_preannounced": True,
    "all_saved_factors_reproduced_by_truncated_5_decimal_simple_cash_formula": True,
    "web_rendered_excerpt_sha256": extract_sha,
    "web_rendered_excerpt_is_original_http_body": False,
    "vendor_historical_factor_value_or_version_proven": False,
    "r3_candidate_rows_upgraded": 0,
    "interpretation": "Issuer/SEC public announcements predate the January 2 signals, and the five saved factor values match floor((1-total_cash/prior_raw_close)*1e5)/1e5. This is arithmetic reproduction, not a historical vendor-version receipt. The frozen contract does not explicitly require such a receipt. Only FERG/ROP inspected primary pages explicitly state Jan-2 ex-date; APD/AXP/PGR announcements state record date and original vendor rehab supplies ex-date. Parent ledger must check the ex-date proof gap and other dependencies before PASS.",
}
(HERE / "FIRST_TRANCHE_REPORT.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(report, indent=2, ensure_ascii=False))
