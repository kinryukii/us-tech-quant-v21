"""Consume saved R7 first-cash-event proof for frozen R6 account price fields.

No model, strategy, or account code is imported. This script only reads saved
evidence and writes a bounded open/close allowlist beside itself.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
JOINT = HERE.parents[1]
WORKSPACE = JOINT.parent
OLD = WORKSPACE / "a2_complete_suite_20260927"
STRICT = WORKSPACE / "a2_strict_method_retrain_20260926"
STAGE = STRICT / "test2026_stage"
PROPOSAL = STAGE / "r7_cash_first_event_proposal"
APPLIED = STAGE / "r7_applied"
KEY = ["cusip", "title_of_class", "quarter", "signal_date"]
END = pd.Timestamp("2026-09-24")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assert_close(a: np.ndarray, b: np.ndarray, what: str) -> None:
    assert np.isfinite(a).all() and np.isfinite(b).all(), what
    assert np.allclose(a, b, rtol=0, atol=1e-7), (what, np.max(np.abs(a - b)))


def main() -> None:
    paths = {
        "joint_prices": JOINT / "data/test_prices.parquet",
        "old_prices": OLD / "data/test_prices.parquet",
        "calendar": JOINT / "data/calendar.parquet",
        "old_consumed_price_events": OLD / "data/consumed_price_events.parquet",
        "old_price_source_receipts": OLD / "data/PRICE_SOURCE_RECEIPTS.json",
        "r7_first_cash_verdicts": PROPOSAL / "R7_TWELVE_CASH_EVENT_VERDICTS.csv",
        "r7_exact_proposal": PROPOSAL / "R7_811_EXACT_KEY_PASS_PROPOSAL.parquet",
        "r7_applied_gate": APPLIED / "R7_FINAL_CANDIDATE_INPUT_GATE.parquet",
        "r7_issuer_sources": PROPOSAL / "EVENT_SOURCES.json",
        "original_event_audit": STAGE / "r4_event_pit/ALL_1094_EVENT_PRIORITY.csv",
        "affected_holding_union": JOINT / "continuation_valuation_r1/AFFECTED_TICKER_DATE_UNION.csv",
        "original_adjustment_builder": Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\scripts\run_rebuild.py"),
    }
    hashes = {name: {"path": str(path), "sha256": sha(path)} for name, path in paths.items()}
    assert hashes["joint_prices"]["sha256"] == hashes["old_prices"]["sha256"]

    verdicts = pd.read_csv(paths["r7_first_cash_verdicts"], dtype={"cusip": str})
    proposal = pd.read_parquet(paths["r7_exact_proposal"])
    applied = pd.read_parquet(paths["r7_applied_gate"])
    prices = pd.read_parquet(paths["joint_prices"])
    calendar = pd.read_parquet(paths["calendar"])
    events = pd.read_parquet(paths["old_consumed_price_events"])
    event_audit = pd.read_csv(paths["original_event_audit"])
    affected = pd.read_csv(paths["affected_holding_union"])
    receipts = json.loads(paths["old_price_source_receipts"].read_text("utf-8"))
    issuer_sources = json.loads(paths["r7_issuer_sources"].read_text("utf-8"))
    issuer_by_code = {item["code"]: item for item in issuer_sources["events"]}
    assert len(verdicts) == len(issuer_by_code) == 12
    assert len(proposal) == 811 and not proposal.duplicated(KEY).any()
    exact = proposal[KEY].merge(applied[KEY + ["final_input_gate"]], on=KEY, validate="one_to_one")
    assert len(exact) == 811 and exact.final_input_gate.eq("INPUT_VERIFIED_THIS_GATE").all()
    assert len(affected) == 6011 and not affected.duplicated(["ticker", "date"]).any()
    affected["date"] = pd.to_datetime(affected.date)
    held_keys = set(zip(affected.ticker, affected.date))
    receipts_by_code = {r["original_code"]: r for r in receipts}
    assert not prices.duplicated(["ticker", "trade_date"]).any()
    assert not events.loc[events.audit_kind.eq("APPLIED_CORPORATE_ACTION")].duplicated(
        ["code", "source_event_date", "event_date"]
    ).any()

    approved = []
    event_summaries = []
    for verdict in verdicts.itertuples(index=False):
        code = verdict.event_code
        ticker = code.removeprefix("US.")
        event_day = pd.Timestamp(verdict.record_and_original_vendor_exdate)
        next_day = pd.Timestamp(verdict.next_unproved_event_exclusive)
        assert code in issuer_by_code and next_day <= END
        assert issuer_by_code[code]["record_date"] == event_day.date().isoformat()
        assert issuer_by_code[code]["public_date"] == verdict.source_public_date
        assert pd.Timestamp(verdict.source_public_date) < event_day
        assert bool(verdict.all_other_original_gates_pass)
        assert not bool(verdict.historical_vendor_actual_receipt_observed)
        assert abs(verdict.original_factor_a - verdict.reconstructed_floor5_factor_a) < 1e-12

        matched_proposal = proposal.loc[proposal.event_code.eq(code)].copy()
        assert len(matched_proposal) == verdict.exact_candidate_keys
        assert matched_proposal.cusip.astype(str).eq(str(verdict.cusip)).all()
        assert matched_proposal.title_of_class.astype(str).map(lambda x: " ".join(x.split())).eq(verdict.normalized_class).all()
        proposal_dates = set(pd.to_datetime(matched_proposal.signal_date))

        original = event_audit.loc[
            event_audit.code.eq(code) & event_audit.source_event_date.eq(event_day.date().isoformat())
        ]
        consumed = events.loc[
            events.audit_kind.eq("APPLIED_CORPORATE_ACTION")
            & events.code.eq(code)
            & pd.to_datetime(events.source_event_date).eq(event_day)
        ]
        assert len(original) == len(consumed) == 1, code
        original, consumed = original.iloc[0], consumed.iloc[0]
        for e in (original, consumed):
            assert float(e.factor_a) == float(verdict.original_factor_a), code
            assert float(e.factor_b) == 0.0 and not bool(e.share_event), code
            assert pd.Timestamp(e.event_date) == event_day, code
            assert not bool(e.aligned_to_next_session), code
        relevant_actions = events.loc[
            events.audit_kind.eq("APPLIED_CORPORATE_ACTION")
            & events.code.eq(code)
            & pd.to_datetime(events.event_date).between("2026-01-01", next_day, inclusive="left")
        ]
        assert len(relevant_actions) == 1, (code, "other unproved event in interval")
        next_actions = events.loc[
            events.audit_kind.eq("APPLIED_CORPORATE_ACTION")
            & events.code.eq(code)
            & pd.to_datetime(events.event_date).ge(next_day)
        ]
        assert len(next_actions) > 0 and pd.to_datetime(next_actions.event_date).min() == next_day

        price = prices.loc[
            prices.ticker.eq(ticker) & prices.trade_date.ge(event_day) & prices.trade_date.lt(next_day)
        ].copy()
        sessions = set(calendar.loc[
            calendar.is_test.astype(bool) & calendar.trade_date.ge(event_day) & calendar.trade_date.lt(next_day),
            "trade_date",
        ])
        assert len(price) == len(sessions) == len(proposal_dates) == len(matched_proposal), code
        assert set(price.trade_date) == sessions == proposal_dates, code
        assert price.original_transport.eq(code).all() and price.transport_used.eq(code).all(), code
        assert price.price_coordinate.eq("PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN").all(), code
        assert price.unresolved_event_on_or_before.all() and price.price_quality_warning.all(), code
        assert not price.lifecycle_ended.any() and not price.extreme_adjusted_jump.any(), code
        for field in ["open", "close", "raw_open", "raw_close"]:
            assert np.isfinite(price[field]).all() and price[field].gt(0).all(), (code, field)

        receipt = receipts_by_code[code]
        assert receipt["ticker"] == ticker and receipt["transport"] == code
        fixed_name = f"RAW_{code.replace('.', '_')}_K_DAY_NONE_RTH.parquet"
        fixed_raw = STAGE / "fixed_window_raw" / fixed_name
        fixed_receipt = [item for item in receipt["paths"] if Path(item["path"]).name == fixed_name]
        assert len(fixed_receipt) == 1, code
        fixed_hash = sha(fixed_raw)
        assert fixed_hash == fixed_receipt[0]["sha256"], code
        raw = pd.read_parquet(fixed_raw, columns=["code", "trade_date", "open", "close"])
        raw["trade_date"] = pd.to_datetime(raw.trade_date)
        raw = raw.loc[raw.code.eq(code) & raw.trade_date.isin(sessions)]
        assert len(raw) == len(price) and not raw.duplicated("trade_date").any(), code
        matching = price.merge(raw[["trade_date", "open", "close"]], on="trade_date", validate="one_to_one", suffixes=("", "_saved_raw"))
        assert_close(matching.raw_open.to_numpy(float), matching.open_saved_raw.to_numpy(float), f"{code}:raw_open")
        assert_close(matching.raw_close.to_numpy(float), matching.close_saved_raw.to_numpy(float), f"{code}:raw_close")

        before = prices.loc[prices.ticker.eq(ticker) & prices.trade_date.lt(event_day)].tail(1)
        assert len(before) == 1 and before.raw_open.iloc[0] != before.raw_close.iloc[0], code
        previous = before.iloc[0]
        assert not bool(previous.price_quality_warning), (code, "preceding price state unproved")
        alpha_before = (previous.open - previous.close) / (previous.raw_open - previous.raw_close)
        beta_before = previous.open - alpha_before * previous.raw_open
        alpha_after = alpha_before / float(verdict.original_factor_a)
        beta_after = beta_before  # Original consumed factor_b is exactly zero.
        assert_close(price.open.to_numpy(float), alpha_after * price.raw_open.to_numpy(float) + beta_after, f"{code}:adjusted_open")
        assert_close(price.close.to_numpy(float), alpha_after * price.raw_close.to_numpy(float) + beta_after, f"{code}:adjusted_close")

        price = price.sort_values("trade_date")
        price["open_authorized"] = True
        price["close_authorized"] = True
        price["evidence_id"] = f"R7_FIRST_CASH_{code}_{event_day.date().isoformat()}"
        price["candidate_pool_version"] = "R6_UNCHANGED"
        price["r7_candidate_evidence"] = True
        price["old_affected_holding"] = [
            (ticker, date) in held_keys for date in price.trade_date
        ]
        price["next_unproved_event_exclusive"] = next_day.date().isoformat()
        price["fixed_raw_sha256"] = fixed_hash
        approved.append(price[[
            "ticker", "trade_date", "open_authorized", "close_authorized", "evidence_id",
            "open", "close", "candidate_pool_version", "r7_candidate_evidence",
            "old_affected_holding", "next_unproved_event_exclusive", "fixed_raw_sha256",
        ]])
        event_summaries.append({
            "ticker": ticker, "event_day": event_day.date().isoformat(),
            "last_authorized_day": price.trade_date.max().date().isoformat(),
            "next_unproved_event_exclusive": next_day.date().isoformat(),
            "authorized_open_days": len(price), "authorized_close_days": len(price),
            "old_affected_holding_days": int(price.old_affected_holding.sum()),
            "potential_new_demand_days": int((~price.old_affected_holding).sum()),
            "fixed_raw_sha256": fixed_hash,
        })

    whitelist = pd.concat(approved, ignore_index=True).sort_values(["ticker", "trade_date"])
    assert len(whitelist) == 811 and not whitelist.duplicated(["ticker", "trade_date"]).any()
    assert int(whitelist.old_affected_holding.sum()) == 339
    whitelist.to_csv(HERE / "R7_EVENT_PRICE_FIELD_ALLOWLIST.csv", index=False)
    whitelist.to_parquet(HERE / "R7_EVENT_PRICE_FIELD_ALLOWLIST.parquet", index=False)

    verdict_by_ticker = {v.event_code.removeprefix("US."): v for v in verdicts.itertuples(index=False)}
    allow_keys = set(zip(whitelist.ticker, whitelist.trade_date))
    affected["open_authorized"] = [(t, d) in allow_keys for t, d in zip(affected.ticker, affected.date)]
    affected["close_authorized"] = affected.open_authorized
    affected["reason"] = [
        "R7_FIRST_CASH_EVENT_EXACT_PRICE_PROOF" if (t, d) in allow_keys else
        "EXAS_EXIT_OR_CORPORATE_ACTION_SETTLEMENT_UNPROVED" if t == "EXAS" else
        "DTP_DTE_SOURCE_PRICE_ROW_ABSENT" if t == "DTP" and not bool(saved) else
        "DTP_DTE_EVENT_PRICE_VERSION_UNPROVED" if t == "DTP" else
        "AFTER_NEXT_UNPROVED_EVENT" if t in verdict_by_ticker and d >= pd.Timestamp(verdict_by_ticker[t].next_unproved_event_exclusive) else
        "NO_SAVED_R7_PRICE_EVENT_PROOF_FOR_THIS_SECURITY_DATE"
        for t, d, saved in zip(affected.ticker, affected.date, affected.saved_price_row)
    ]
    assert int(affected.open_authorized.sum()) == 339
    affected[["ticker", "date", "open_authorized", "close_authorized", "reason", "affected_runs"]].to_csv(
        HERE / "AFFECTED_UNION_R7_FIELD_STATUS.csv", index=False
    )

    summary = {
        "status": "BOUNDED_SAVED_R7_EVENT_PRICE_FIELD_PROOF",
        "candidate_pool_version": "R6_UNCHANGED",
        "authorized_ticker_dates": len(whitelist),
        "authorized_old_affected_holding_ticker_dates": int(whitelist.old_affected_holding.sum()),
        "other_authorized_ticker_dates_for_potential_new_demand": int((~whitelist.old_affected_holding).sum()),
        "affected_union_total_ticker_dates": len(affected),
        "affected_union_still_unproved_ticker_dates": int((~affected.open_authorized).sum()),
        "affected_union_unproved_reasons": affected.loc[~affected.open_authorized, "reason"].value_counts().to_dict(),
        "event_summaries": event_summaries,
        "input_sha256": hashes,
        "output_sha256": {
            name: sha(HERE / name) for name in [
                "R7_EVENT_PRICE_FIELD_ALLOWLIST.csv", "R7_EVENT_PRICE_FIELD_ALLOWLIST.parquet",
                "AFFECTED_UNION_R7_FIELD_STATUS.csv",
            ]
        },
        "model_fit_calls": 0, "preprocessor_fit_calls": 0, "account_replay_calls": 0,
    }
    (HERE / "PROOF_SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({key: summary[key] for key in [
        "authorized_ticker_dates", "authorized_old_affected_holding_ticker_dates",
        "affected_union_still_unproved_ticker_dates", "affected_union_unproved_reasons",
    ]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
