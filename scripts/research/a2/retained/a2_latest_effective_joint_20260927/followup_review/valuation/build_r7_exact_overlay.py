"""Bind already-applied local R7 cash-event proof to saved joint holdings.

The output is a candidate price overlay and fixed-unit mark snapshot only. It
never edits the joint batch's original input or account files and never calls
the policy, fits a model, or advances account state.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
R7 = ROOT.parent / "a2_strict_method_retrain_20260926/test2026_stage/r7_applied"
VERDICTS = ROOT.parent / "a2_strict_method_retrain_20260926/test2026_stage/r7_cash_first_event_proposal/R7_TWELVE_CASH_EVENT_VERDICTS.csv"


def sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main() -> None:
    paths = {
        "gaps": HERE / "SAVED_VALUATION_GAPS_10BPS.parquet",
        "transitions": R7 / "R7_811_CASH_STATUS_TRANSITIONS.parquet",
        "r7_gate": R7 / "R7_FINAL_CANDIDATE_INPUT_GATE.parquet",
        "r7_summary": R7 / "R7_GATE_SUMMARY.json",
        "verdicts": VERDICTS,
        "proposal_exact": VERDICTS.parent / "R7_811_EXACT_KEY_PASS_PROPOSAL.parquet",
        "consumed_events": ROOT / "data/consumed_price_events.parquet",
        "prices": ROOT / "data/test_prices.parquet",
        "quarter_timing": ROOT / "data/quarter_timing.csv",
        "calendar": ROOT / "data/calendar.parquet",
        "source_receipts": ROOT / "data/PRICE_SOURCE_RECEIPTS.json",
    }
    source_sha256 = {key: sha(path) for key, path in paths.items()}
    r7_summary = json.loads(paths["r7_summary"].read_text(encoding="utf-8"))
    assert r7_summary["parent_r6_sha256"] == "46b4af4c87c760817bd9244ec82886b258a844b1b14dac96f3acfd5e0764e830"
    assert r7_summary["r7_final_sha256"] == source_sha256["r7_gate"]
    assert r7_summary["cash_proposal_sha256"] == source_sha256["proposal_exact"]
    transitions = pd.read_parquet(paths["transitions"])
    assert len(transitions) == r7_summary["new_verified_cash_exact_keys"] == 811
    transitions = transitions.rename(columns={"signal_date": "date"})
    assert not transitions.duplicated(["ticker", "date"]).any()
    assert transitions.final_input_gate.eq("INPUT_VERIFIED_THIS_GATE").all()
    proposed = pd.read_parquet(paths["proposal_exact"])
    key_fields = ["cusip", "title_of_class", "quarter", "signal_date", "ticker", "moomoo_transport_code"]
    assert len(proposed) == len(transitions)
    assert proposed.proposed_input_gate.eq("INPUT_VERIFIED_THIS_GATE").all()
    assert proposed[key_fields].sort_values(key_fields).reset_index(drop=True).equals(
        transitions.rename(columns={"date": "signal_date"})[key_fields]
        .sort_values(key_fields).reset_index(drop=True))
    gate = pd.read_parquet(paths["r7_gate"], columns=["ticker", "signal_date", "cusip", "title_of_class", "quarter", "final_input_gate"])
    gate = gate.rename(columns={"signal_date": "date"})
    assert not gate.duplicated(["ticker", "date"]).any()
    proof = transitions.merge(gate, on=["ticker", "date", "cusip", "title_of_class", "quarter", "final_input_gate"],
                              how="left", validate="one_to_one", indicator="gate_join")
    assert proof.gate_join.eq("both").all()
    timing = pd.read_csv(paths["quarter_timing"], parse_dates=["quarter_effective_date", "next_quarter_effective_date"])
    proof = proof.merge(timing[["quarter", "quarter_effective_date", "next_quarter_effective_date"]],
                        on="quarter", validate="many_to_one")
    assert proof.date.ge(proof.quarter_effective_date).all()
    assert (proof.next_quarter_effective_date.isna() | proof.date.lt(proof.next_quarter_effective_date)).all()
    verdicts = pd.read_csv(paths["verdicts"], parse_dates=["source_public_date", "record_and_original_vendor_exdate",
                                                             "next_unproved_event_exclusive"])
    verdicts = verdicts.rename(columns={"event_code": "moomoo_transport_code", "record_and_original_vendor_exdate": "event_date"})
    proof = proof.merge(verdicts[["moomoo_transport_code", "source_public_date", "event_date",
                                  "next_unproved_event_exclusive", "original_factor_a", "reconstructed_floor5_factor_a",
                                  "cash_usd_per_original_share", "source_publication_tier", "source_url",
                                  "historical_vendor_actual_receipt_observed"]],
                        on="moomoo_transport_code", validate="many_to_one")
    assert proof.source_public_date.lt(proof.date).all()
    sessions = sorted(pd.read_parquet(paths["calendar"], columns=["trade_date"]).trade_date.unique())
    prior_session = {sessions[i]: sessions[i - 1] for i in range(1, len(sessions))}
    proof["prior_session"] = proof.date.map(prior_session)
    assert proof.prior_session.notna().all() and proof.source_public_date.lt(proof.prior_session).all()
    assert proof.event_date.le(proof.date).all()
    assert proof.date.lt(proof.next_unproved_event_exclusive).all()
    assert np.allclose(proof.original_factor_a, proof.reconstructed_floor5_factor_a, atol=5e-6, rtol=0)
    assert proof.historical_vendor_actual_receipt_observed.eq(False).all()
    events = pd.read_parquet(paths["consumed_events"])
    events = events.loc[events.audit_kind.eq("APPLIED_CORPORATE_ACTION"),
                        ["code", "ticker", "event_date", "factor_a", "factor_b"]].rename(columns={"code": "moomoo_transport_code"})
    event_keys = proof[["moomoo_transport_code", "ticker", "event_date", "original_factor_a"]].drop_duplicates()
    event_keys = event_keys.merge(events, on=["moomoo_transport_code", "ticker", "event_date"],
                                  validate="one_to_one", indicator="event_join")
    assert event_keys.event_join.eq("both").all()
    assert np.allclose(event_keys.factor_a, event_keys.original_factor_a, atol=5e-6, rtol=0)
    assert event_keys.factor_b.eq(0).all()
    price_columns = ["ticker", "trade_date", "open", "close", "raw_open", "raw_close", "price_coordinate",
                     "original_transport", "transport_used", "price_quality_warning",
                     "unresolved_event_on_or_before", "lifecycle_ended", "extreme_adjusted_jump"]
    prices = pd.read_parquet(paths["prices"], columns=price_columns).rename(columns={"trade_date": "date"})
    full = proof.merge(prices, on=["ticker", "date"], how="left", validate="one_to_one", indicator="price_join")
    assert full.price_join.eq("both").all()
    assert full.price_quality_warning.eq(True).all() and full.unresolved_event_on_or_before.eq(True).all()
    assert full.lifecycle_ended.eq(False).all() and full.extreme_adjusted_jump.eq(False).all()
    assert full[["open", "close", "raw_open", "raw_close"]].gt(0).all().all()
    assert full.original_transport.eq(full.moomoo_transport_code).all()
    assert full.price_coordinate.eq("PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN").all()
    receipts = {item["ticker"]: item for item in json.loads(paths["source_receipts"].read_text(encoding="utf-8"))}
    assert all(receipts[row.ticker]["original_code"] == row.original_transport and
               receipts[row.ticker]["transport"] == row.transport_used for row in full.itertuples())
    policy_independent_columns = ["ticker", "date", "cusip", "title_of_class", "quarter", "open", "close",
                                  "raw_open", "raw_close", "price_coordinate", "original_transport", "transport_used",
                                  "source_public_date", "prior_session", "event_date", "next_unproved_event_exclusive",
                                  "original_factor_a", "cash_usd_per_original_share", "source_publication_tier", "source_url"]
    full_overlay = full[policy_independent_columns].copy()
    full_overlay["scope"] = "POLICY_INDEPENDENT_POSTHOC_EVALUATION_PRICE_COORDINATE_ONLY"
    full_path = HERE / "R7_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet"
    full_overlay.sort_values(["date", "ticker"]).to_parquet(full_path, index=False)
    assert len(full_overlay) == 811 and not full_overlay.duplicated(["ticker", "date"]).any()
    gaps = pd.read_parquet(paths["gaps"])
    matched = gaps.merge(proof, on=["ticker", "date"], how="inner", validate="many_to_one")
    assert matched.year.eq(2026).all() and matched.reason.eq("UNRESOLVED_EVENT_GATE").all()
    assert matched.price_quality_warning.eq(True).all()
    assert matched.original_transport.eq(matched.moomoo_transport_code).all()
    assert matched["open"].gt(0).all() and matched["close"].gt(0).all()
    assert matched["raw_open"].gt(0).all() and matched["raw_close"].gt(0).all()
    assert matched.price_coordinate.eq("PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN").all()
    assert all(receipts[row.ticker]["original_code"] == row.original_transport and
               receipts[row.ticker]["transport"] == row.transport_used for row in matched.itertuples())
    assert len(matched) == len(matched[["ticker", "date"]].drop_duplicates()) == 339
    overlay_columns = ["ticker", "date", "policy", "cusip", "title_of_class", "quarter", "open", "close",
                       "raw_open", "raw_close", "price_coordinate", "original_transport", "transport_used",
                       "source_public_date", "prior_session", "event_date", "next_unproved_event_exclusive",
                       "original_factor_a", "cash_usd_per_original_share", "source_publication_tier", "source_url"]
    overlay = matched[overlay_columns].copy()
    overlay["scope"] = "POSTHOC_EVALUATION_PRICE_PROOF_ONLY_NO_DECISION_INPUT_REWRITE"
    overlay_path = HERE / "R7_EXACT_VALUATION_OVERLAY_CANDIDATES.parquet"
    overlay.to_parquet(overlay_path, index=False)
    snap = matched[["policy", "date", "ticker", "index_units", "mark", "mark_date", "mark_source",
                    "market_value", "nav", "cash", "close", "source_public_date", "event_date"]].copy()
    snap = snap.rename(columns={"mark": "original_stale_mark", "market_value": "original_stale_market_value",
                                "nav": "original_indicative_nav", "close": "r7_bound_close"})
    snap["r7_bound_fixed_units_market_value"] = snap.index_units * snap.r7_bound_close
    snap["fixed_units_mark_delta"] = snap.r7_bound_fixed_units_market_value - snap.original_stale_market_value
    snap["snapshot_nav_if_only_mark_changes"] = snap.original_indicative_nav + snap.fixed_units_mark_delta
    snap["not_policy_replay"] = True
    snapshot_path = HERE / "R7_FIXED_UNITS_MARK_SNAPSHOT_IMPACT.csv"
    snap.sort_values(["policy", "date", "ticker"]).to_csv(snapshot_path, index=False)
    original_accounts = gaps.groupby(["policy", "date"], as_index=False).agg(
        original_unverified_names=("ticker", "nunique"),
        original_unverified_indicative_value=("market_value", "sum"),
        original_indicative_nav=("nav", "first"))
    covered_accounts = snap.groupby(["policy", "date"], as_index=False).agg(
        exact_r7_names=("ticker", "nunique"),
        original_r7_stale_value=("original_stale_market_value", "sum"),
        mark_delta=("fixed_units_mark_delta", "sum"))
    account_impact = original_accounts.merge(covered_accounts, on=["policy", "date"],
                                             how="inner", validate="one_to_one")
    account_impact["fixed_units_snapshot_nav"] = account_impact.original_indicative_nav + account_impact.mark_delta
    account_impact["remaining_original_unverified_names"] = account_impact.original_unverified_names - account_impact.exact_r7_names
    account_impact["remaining_original_unverified_value"] = (
        account_impact.original_unverified_indicative_value - account_impact.original_r7_stale_value)
    account_impact["fixed_units_delta_fraction_original_nav"] = account_impact.mark_delta / account_impact.original_indicative_nav
    account_impact["policy_replayed"] = False
    account_path = HERE / "R7_FIXED_UNITS_ACCOUNT_DATE_IMPACT.csv"
    account_impact.sort_values(["policy", "date"]).to_csv(account_path, index=False)
    all_accounts = original_accounts.merge(covered_accounts, on=["policy", "date"], how="left", validate="one_to_one")
    for column in ("exact_r7_names", "original_r7_stale_value", "mark_delta"):
        all_accounts[column] = all_accounts[column].fillna(0)
    all_accounts["fixed_units_snapshot_nav"] = all_accounts.original_indicative_nav + all_accounts.mark_delta
    all_accounts["conditional_remaining_unverified_names"] = all_accounts.original_unverified_names - all_accounts.exact_r7_names
    all_accounts["conditional_remaining_unverified_value"] = (
        all_accounts.original_unverified_indicative_value - all_accounts.original_r7_stale_value)
    all_accounts["before_unverified_fraction_indicative_nav"] = (
        all_accounts.original_unverified_indicative_value / all_accounts.original_indicative_nav)
    all_accounts["conditional_after_unverified_fraction_snapshot_nav"] = (
        all_accounts.conditional_remaining_unverified_value / all_accounts.fixed_units_snapshot_nav)
    all_accounts["is_causal_replay"] = False
    all_account_path = HERE / "ALL_ACCOUNT_DATE_CONDITIONAL_OVERLAY_EXPOSURE.csv"
    all_accounts.sort_values(["policy", "date"]).to_csv(all_account_path, index=False)
    remaining_rows = gaps.merge(overlay[["ticker", "date"]].drop_duplicates(), on=["ticker", "date"],
                                how="left", indicator="overlay_match", validate="many_to_one")
    remaining_rows = remaining_rows.loc[remaining_rows.overlay_match.eq("left_only")]
    before_reason = gaps.groupby("reason").agg(policy_position_days=("ticker", "size")).to_dict("index")
    after_reason = remaining_rows.groupby("reason").agg(policy_position_days=("ticker", "size")).to_dict("index")
    for label, frame, target in (("before", gaps, before_reason), ("conditional_fixed_mark_after", remaining_rows, after_reason)):
        for reason, group in frame.groupby("reason"):
            target[reason]["unique_security_dates"] = int(group[["ticker", "date"]].drop_duplicates().shape[0])
    for path, prior in source_sha256.items():
        assert sha(paths[path]) == prior
    report = {
        "status": "R7_EXACT_PROOF_OVERLAY_PREPARED_NO_ACCOUNT_REPLAY",
        "policy_independent_r7_price_keys": len(full_overlay),
        "policy_independent_excluded_keys": 0,
        "policy_independent_tickers": sorted(full_overlay.ticker.unique().tolist()),
        "r7_exact_security_dates": len(overlay), "tickers": sorted(overlay.ticker.unique().tolist()),
        "matched_saved_position_rows": len(snap),
        "matched_account_dates": int(snap[["policy", "date"]].drop_duplicates().shape[0]),
        "account_dates_with_all_original_mark_gaps_covered": int(account_impact.remaining_original_unverified_names.eq(0).sum()),
        "fixed_units_snapshot_delta_min": float(snap.fixed_units_mark_delta.min()),
        "fixed_units_snapshot_delta_max": float(snap.fixed_units_mark_delta.max()),
        "account_date_delta_fraction_original_nav_min": float(account_impact.fixed_units_delta_fraction_original_nav.min()),
        "account_date_delta_fraction_original_nav_max": float(account_impact.fixed_units_delta_fraction_original_nav.max()),
        "before_reason_counts": before_reason,
        "conditional_fixed_mark_after_reason_counts": after_reason,
        "actual_account_replay_after_reason_counts": before_reason,
        "before_max_account_date_unverified_fraction": float(all_accounts.before_unverified_fraction_indicative_nav.max()),
        "conditional_fixed_mark_after_max_account_date_unverified_fraction": float(all_accounts.conditional_after_unverified_fraction_snapshot_nav.max()),
        "original_uncertified_account_dates": len(all_accounts),
        "conditional_fixed_mark_after_uncertified_account_dates": int(all_accounts.conditional_remaining_unverified_names.gt(0).sum()),
        "remaining_original_unique_gap_keys_if_only_exact_rows_marked": 6011 - len(overlay),
        "r7_price_evidence_limits": [
            "R7 verifies an exact original cash-event and candidate key; it does not certify total shareholder return.",
            "The historical vendor receipt instant was not observed; R7 used issuer publication and original vendor ex-date.",
            "Raw 2026 quotes are consumed only at their date for execution or valuation; no preceding decision input is overwritten.",
            "A mark snapshot uses saved units and cash. Actual sales, purchases, future holdings, and policy decisions require causal replay after policy freeze.",
        ],
        "source_sha256": source_sha256,
        "output_sha256": {p.name: sha(p) for p in (full_path, overlay_path, snapshot_path, account_path, all_account_path)},
        "market_fit_calls": 0, "model_inference_calls": 0, "ledger_replay_calls": 0,
    }
    (HERE / "R7_OVERLAY_RECEIPT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("status", "r7_exact_security_dates", "tickers", "remaining_original_unique_gap_keys_if_only_exact_rows_marked")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
