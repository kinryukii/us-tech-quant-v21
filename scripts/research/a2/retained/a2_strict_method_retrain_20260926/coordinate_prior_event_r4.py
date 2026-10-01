"""Deduplicate the pre-2026 initial adjustment chain for r3 no-overlap rows."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
R3 = ROOT / "test2026_stage/identity_feature_application_r1"
OUT = ROOT / "test2026_stage/r4_coordinate"
OLD = ROOT.parent / "a2_13f_learned_sizing_pre2026_test2026_r1/continuation_2026_r1"
REHAB = [OLD / "REHAB_NEW_OCCUPIED_ONLY", OLD / "REHAB_SUBSCRIPTION_ONLY"]


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1 << 20), b""):
            h.update(part)
    return h.hexdigest()


def main() -> None:
    mapping = pd.read_parquet(OUT / "COORDINATE_14841_EXACT_CANDIDATE_MAPPING.parquet")
    rows = mapping.loc[mapping.coordinate_evidence_class.eq("PRIOR_EVENT_CHAIN_INITIAL_VERSION_PENDING")].copy()
    assert len(rows) == 3148 and rows.moomoo_transport_code.nunique() == 94
    audit = pd.read_parquet(R3 / "CONSUMED_REHAB_EVENT_AUDIT.parquet")
    events = audit.loc[audit.audit_kind.eq("APPLIED_CORPORATE_ACTION")
                       & audit.original_code.isin(rows.moomoo_transport_code)
                       & audit.event_date.lt(pd.Timestamp("2026-01-02"))].copy()
    assert len(events) == 1090 and events.original_code.nunique() == 94
    assert not events.duplicated(["original_code", "source_event_date"]).any()
    factor_parts, source_parts, manifests = [], [], []
    for folder in REHAB:
        status_path, factor_path = folder / "rehab_status.csv", folder / "rehab_factors.parquet"
        status = pd.read_csv(status_path)
        factors = pd.read_parquet(factor_path)
        active = set(rows.moomoo_transport_code) & set(status.loc[status.status.eq("PASS"), "code"])
        selected = factors.loc[factors.code.isin(active)].copy()
        selected["factor_snapshot"] = folder.name
        factor_parts.append(selected)
        source_parts.extend({"code": code, "factor_snapshot": folder.name,
                             "factor_path": str(factor_path), "factor_sha256": digest(factor_path),
                             "status_path": str(status_path), "status_sha256": digest(status_path)}
                            for code in active)
        manifests.append({"factor_snapshot": folder.name, "factor_path": str(factor_path),
                          "factor_sha256": digest(factor_path), "status_path": str(status_path),
                          "status_sha256": digest(status_path), "relevant_codes": len(active),
                          "factor_file_mtime_utc": datetime.fromtimestamp(factor_path.stat().st_mtime,
                                                                           timezone.utc).isoformat()})
    source = pd.DataFrame(source_parts)
    assert len(source) == 94 and not source.duplicated("code").any()
    factors = pd.concat(factor_parts, ignore_index=True)
    factors["ex_div_date"] = pd.to_datetime(factors.ex_div_date).dt.normalize()
    keep = ["code", "ex_div_date", "split_base", "split_ert", "join_base", "join_ert",
            "split_ratio", "per_cash_div", "special_dividend", "forward_adj_factorA",
            "forward_adj_factorB", "factor_snapshot"]
    assert not factors.duplicated(["code", "ex_div_date"]).any()
    events = events.merge(factors[keep], left_on=["code", "source_event_date"],
                          right_on=["code", "ex_div_date"], how="left", validate="one_to_one")
    assert events.factor_snapshot.notna().all()
    assert events.factor_snapshot.eq(events.code.map(source.set_index("code").factor_snapshot)).all()
    events = events.merge(source.drop(columns="factor_snapshot"), on="code", validate="many_to_one")
    assert len(events) == 1090
    events["reference_price_or_vendor_factor_version_required"] = ~events.share_event
    events["historical_publication_or_supplier_version_record_present"] = False
    events["missing_fact"] = events.share_event.map({
        True: "Contemporaneous issuer/exchange record for split ratio and effective date, plus original supplier factor version if contract requires it",
        False: "Contemporaneous exact forward_adj_factorA/B or cash distribution with reference-price and supplier version publication clock"})
    columns = ["original_code", "ticker", "event_date", "source_event_date", "aligned_to_next_session",
               "factor_a", "factor_b", "share_event", "split_ratio", "per_cash_div", "special_dividend",
               "forward_adj_factorA", "forward_adj_factorB", "factor_snapshot", "factor_path",
               "factor_sha256", "status_path", "status_sha256",
               "reference_price_or_vendor_factor_version_required",
               "historical_publication_or_supplier_version_record_present", "missing_fact"]
    events[columns].to_csv(OUT / "PRIOR_EVENT_1090_UNIQUE_INITIAL_CHAIN_TASKS.csv", index=False)
    summary = events.groupby("original_code", as_index=False).agg(
        prior_events=("event_date", "size"), share_events=("share_event", "sum"),
        first_prior_event=("event_date", "min"), last_prior_event=("event_date", "max"))
    summary["cash_or_other_events"] = summary.prior_events - summary.share_events
    summary = summary.merge(source, left_on="original_code", right_on="code", validate="one_to_one")
    by_code = rows.groupby("moomoo_transport_code", as_index=False).agg(
        candidate_days=("signal_date", "size"), first_signal=("signal_date", "min"),
        last_signal=("signal_date", "max"), other_saved_close_exact_days=("other_saved_close_exact", "sum"),
        other_saved_volume_exact_days=("other_saved_volume_exact", "sum"))
    summary = summary.merge(by_code, left_on="original_code", right_on="moomoo_transport_code", validate="one_to_one")
    summary.to_csv(OUT / "PRIOR_EVENT_94_CODE_INITIAL_CHAIN_STATUS.csv", index=False)
    exact = rows[["cusip", "title_of_class", "quarter", "signal_date", "ticker",
                  "moomoo_transport_code", "consumed_prior_events", "initial_alpha_2026_01_02",
                  "initial_beta_2026_01_02", "other_saved_close_exact", "other_saved_volume_exact"]].copy()
    exact["still_missing"] = "HISTORICAL_FACTOR_VERSION_AND_ANCHOR_EVIDENCE"
    exact.to_parquet(OUT / "PRIOR_EVENT_3148_EXACT_KEY_REMAINDER.parquet", index=False)
    report = {
        "candidate_days": len(rows), "codes": rows.moomoo_transport_code.nunique(),
        "unique_consumed_pre2026_events": len(events),
        "cash_or_other_non_share_events": int((~events.share_event).sum()),
        "non_share_events_with_nonzero_regular_cash": int((~events.share_event & events.per_cash_div.fillna(0).ne(0)).sum()),
        "events_with_nonzero_factor_b": int(events.factor_b.fillna(0).ne(0).sum()),
        "share_events": int(events.share_event.sum()),
        "share_only_codes": int(summary.cash_or_other_events.eq(0).sum()),
        "share_only_candidate_days": int(summary.loc[summary.cash_or_other_events.eq(0), "candidate_days"].sum()),
        "other_saved_close_and_volume_exact_days": int((rows.other_saved_close_exact & rows.other_saved_volume_exact).sum()),
        "other_saved_mismatch_days": int((~(rows.other_saved_close_exact & rows.other_saved_volume_exact)).sum()),
        "rehab_snapshot_sources": manifests,
        "conclusion": "No exact-key closure from existing evidence: the two relevant rehab files were already saved before this batch's 2026 TEST_ASOF, but in September 2026, after all tested signal dates. Their save times do not establish historical factor availability or original supplier versions at each decision. The older adjusted output is a separately truncated coordinate and disagrees on some rows. The 5 share-only codes are cheaper targeted primary-source tasks but their historic originals are not pinned locally.",
        "formal_model_calls": 0, "preprocessor_fit_calls": 0,
    }
    (OUT / "PRIOR_EVENT_INITIAL_CHAIN_REPORT.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("candidate_days", "codes", "unique_consumed_pre2026_events",
                                           "share_only_candidate_days", "other_saved_mismatch_days")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
