"""Read-only, exact-key inventory of r3's consumed 2026 adjustment events.

This deliberately does not infer historical vendor publication from ex-date,
factor arithmetic, file creation time, or an issuer announcement.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


R3 = Path(r"D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results\test2026\identity_feature_application_20260926_r3")
OUT = Path(__file__).resolve().parent
OUT.mkdir(parents=True, exist_ok=True)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


events = pd.read_parquet(R3 / "CONSUMED_REHAB_EVENT_AUDIT.parquet")
events = events.loc[events.audit_kind.eq("APPLIED_CORPORATE_ACTION") & events.event_date.between("2026-01-02", "2026-09-22")].copy()
events["event_date"] = pd.to_datetime(events.event_date).dt.normalize()
events["source_event_date"] = pd.to_datetime(events.source_event_date).dt.normalize()
events = events.drop_duplicates(["original_code", "code", "source_event_date", "event_date", "factor_a", "factor_b", "share_event"])
candidate = pd.read_parquet(R3 / "FINAL_111868_CANDIDATE_INPUT_GATE.parquet")
candidate["signal_date"] = pd.to_datetime(candidate.signal_date).dt.normalize()
sources = json.loads((R3 / "FEATURE_CONSUMPTION_REPORT.json").read_text(encoding="utf-8"))["rehab_sources"]
raw_sources = {x["original_code"]: x for x in json.loads((R3 / "CONSUMED_RAW_SOURCE_AUDIT.json").read_text(encoding="utf-8"))}

# The applied event must match the actually loaded factor snapshot by transport,
# original source ex date, and both coefficients. Multiple snapshots may hold the
# same event; list them all rather than guessing which response was first.
factor_parts = []
for src in sources:
    path = Path(src["factors_path"])
    if not path.exists():
        continue
    x = pd.read_parquet(path)
    x = x.loc[x.ex_div_date.astype(str).between("2026-01-02", "2026-09-22")].copy()
    x["source_event_date"] = pd.to_datetime(x.ex_div_date).dt.normalize()
    x["factor_a"] = pd.to_numeric(x.forward_adj_factorA, errors="coerce")
    x["factor_b"] = pd.to_numeric(x.forward_adj_factorB, errors="coerce")
    x["source_path"] = str(path)
    x["source_sha256"] = src["factors_sha256"]
    factor_parts.append(x)
factors = pd.concat(factor_parts, ignore_index=True)

rows = []
raw_frame_cache = {}
for ev in events.itertuples(index=False):
    keys = candidate.loc[candidate.moomoo_transport_code.eq(ev.original_code)]
    f = factors.loc[factors.code.eq(ev.code) & factors.source_event_date.eq(ev.source_event_date)
                    & np.isclose(factors.factor_a, ev.factor_a, atol=1e-12, rtol=0)
                    & np.isclose(factors.factor_b, ev.factor_b, atol=1e-12, rtol=0)]
    raw = raw_sources.get(ev.original_code, {})
    raw_paths = [Path(p) for p in raw.get("paths", []) if Path(p).exists()]
    # r3 builder selects the last duplicate by date after concatenating paths.
    # Use only rows with the exact transport code; compute the event's prior
    # session raw close using the same path order and deduplication semantics.
    prior_close = np.nan
    prior_date = ""
    if ev.original_code not in raw_frame_cache and raw_paths:
        pieces = []
        for p in raw_paths:
            part = pd.read_parquet(p, columns=["code", "time_key", "close"])
            part = part.loc[part.code.astype(str).str.upper().eq(str(ev.code).upper())].copy()
            pieces.append(part)
        if pieces:
            rf = pd.concat(pieces, ignore_index=True)
            rf["trade_date"] = pd.to_datetime(rf.time_key).dt.normalize()
            rf = rf.sort_values("trade_date", kind="mergesort").drop_duplicates("trade_date", keep="last")
            raw_frame_cache[ev.original_code] = rf
    rf = raw_frame_cache.get(ev.original_code)
    if rf is not None:
        prior = rf.loc[rf.trade_date.lt(ev.event_date)].tail(1)
        if len(prior):
            prior_close = float(prior.close.iloc[0])
            prior_date = str(prior.trade_date.iloc[0].date())
    for security, part in keys.groupby(["cusip", "title_of_class", "quarter"], dropna=False):
        affected = part.loc[part.signal_date.ge(ev.event_date)]
        if affected.empty:
            continue
        fin = affected.loc[affected["2026_event_publication_time_unverified"].astype(bool)]
        factor = f.iloc[0] if len(f) else None
        cash = float(factor.per_cash_div) if factor is not None and pd.notna(factor.per_cash_div) else np.nan
        special = float(factor.special_dividend) if factor is not None and pd.notna(factor.special_dividend) else np.nan
        total_cash = cash + (special if np.isfinite(special) else 0.0) if np.isfinite(cash) else np.nan
        expected_a = (prior_close - total_cash) / prior_close if np.isfinite(prior_close) and np.isfinite(total_cash) else np.nan
        floor_a_5 = np.floor(expected_a * 100000) / 100000 if np.isfinite(expected_a) else np.nan
        rows.append({
            "original_code": ev.original_code, "transport_code": ev.code,
            "cusip": security[0], "title_of_class": security[1], "quarter": security[2],
            "source_event_date": ev.source_event_date, "applied_event_date": ev.event_date,
            "aligned_to_next_session": bool(ev.aligned_to_next_session),
            "factor_a": ev.factor_a, "factor_b": ev.factor_b,
            "share_event": bool(ev.share_event), "manual_wolf": bool(ev.manual_wolf),
            "per_cash_div": cash, "special_dividend": special, "total_cash_div": total_cash,
            "prior_raw_date": prior_date, "prior_raw_close": prior_close,
            "simple_cash_expected_a": expected_a,
            "simple_cash_floor_a_5": floor_a_5,
            "simple_cash_floor_matches_vendor": bool(np.isfinite(floor_a_5) and np.isclose(ev.factor_a, floor_a_5, atol=1e-12, rtol=0)),
            "simple_cash_factor_difference": ev.factor_a - expected_a if np.isfinite(expected_a) else np.nan,
            "matching_snapshot_count": len(f),
            "matching_snapshot_paths": " | ".join(sorted(f.source_path.unique())) if len(f) else "",
            "matching_snapshot_hashes": " | ".join(sorted(f.source_sha256.unique())) if len(f) else "",
            "candidate_days_after_event": len(affected),
            "r3_pubtime_unknown_days_after_event": len(fin),
            "first_affected_signal": affected.signal_date.min(),
            "last_affected_signal": affected.signal_date.max(),
            "issuer_public_available_at_signal": "UNVERIFIED",
            "vendor_factor_value_available_at_signal": "UNVERIFIED",
            "vendor_version_available_at_signal": "UNVERIFIED",
            "r3_receipt_is_historical_pit": False,
            "decision": "UNKNOWN_EVENT_PUBLICATION_AND_VENDOR_VERSION",
        })

out = pd.DataFrame(rows).sort_values(["r3_pubtime_unknown_days_after_event", "candidate_days_after_event", "original_code"], ascending=[False, False, True])
out.to_parquet(OUT / "EVENT_SECURITY_DECISION_RANGES.parquet", index=False)
out.drop(columns=["matching_snapshot_paths", "matching_snapshot_hashes"]).to_csv(OUT / "EVENT_SECURITY_PRIORITY.csv", index=False)
agg = (out.groupby(["original_code", "transport_code", "source_event_date", "applied_event_date", "factor_a", "factor_b", "share_event"], dropna=False, as_index=False)
       .agg(candidate_days_after_event=("candidate_days_after_event", "sum"),
            r3_pubtime_unknown_days_after_event=("r3_pubtime_unknown_days_after_event", "sum"),
            security_ranges=("cusip", "size"),
            prior_raw_close=("prior_raw_close", "first"),
            total_cash_div=("total_cash_div", "first"),
            simple_cash_floor_matches_vendor=("simple_cash_floor_matches_vendor", "first")))
all_events = events.merge(agg, left_on=["original_code", "code", "source_event_date", "event_date", "factor_a", "factor_b", "share_event"], right_on=["original_code", "transport_code", "source_event_date", "applied_event_date", "factor_a", "factor_b", "share_event"], how="left", validate="one_to_one")
for col in ["candidate_days_after_event", "r3_pubtime_unknown_days_after_event", "security_ranges"]:
    all_events[col] = all_events[col].fillna(0).astype(int)
all_events["priority_basis"] = "affected candidate-days, no model scores; repeated events for one security overlap"
all_events["historical_vendor_version_status"] = "UNVERIFIED"
all_events.sort_values(["r3_pubtime_unknown_days_after_event", "candidate_days_after_event", "original_code"], ascending=[False, False, True]).to_csv(OUT / "ALL_1094_EVENT_PRIORITY.csv", index=False)
summary = {
    "r3_event_rows_2026": len(events),
    "r3_event_security_ranges": len(out),
    "all_events_priority_rows": len(all_events),
    "events_with_zero_candidate_days_after_event": int(all_events.candidate_days_after_event.eq(0).sum()),
    "transport_codes": int(events.original_code.nunique()),
    "event_ranges_with_matching_factor_snapshot": int(out.matching_snapshot_count.gt(0).sum()),
    "event_ranges_without_matching_factor_snapshot": int(out.matching_snapshot_count.eq(0).sum()),
    "event_ranges_with_prior_raw_close": int(out.prior_raw_close.notna().sum()),
    "cash_factor_arithmetic_comparable_ranges": int(out.simple_cash_expected_a.notna().sum()),
    "cash_factor_arithmetic_within_1e6_ranges": int(out.simple_cash_factor_difference.abs().le(1e-6).sum()),
    "simple_cash_floor_matches_vendor_ranges": int(out.simple_cash_floor_matches_vendor.sum()),
    "events_with_true_historical_vendor_factor_version_receipt": 0,
    "r3_input_sha256": {name: sha(R3 / name) for name in ["CONSUMED_REHAB_EVENT_AUDIT.parquet", "FINAL_111868_CANDIDATE_INPUT_GATE.parquet", "FEATURE_CONSUMPTION_REPORT.json", "CONSUMED_RAW_SOURCE_AUDIT.json"]},
    "interpretation": "This is a pre-evidence priority inventory. Factor arithmetic and ex dates check numerical consistency but do not date vendor publication. Separately adjudicated RLYB and first-tranche cash event ranges are recorded in their own overlays; do not treat this inventory's default UNKNOWN as their final verdict.",
}
(OUT / "EVENT_INVENTORY_REPORT.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(summary, indent=2, ensure_ascii=False))
