"""Bound joint-batch MU/T 2026 price-warning proof, independent of policies.

This reads only the joint batch's already-fixed 2026 evaluation price/event and
identity inputs. It does not read holdings, scores, models, or results, and it
does not fit or replay anything. The issuer web facts are a separately reviewed
metadata file; their original HTTP bodies were not retained.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ASOF_EXCLUSIVE = pd.Timestamp("2026-09-25")
COORDINATE = "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN"
EXPECTED = {"MU": ("595112103", "COM", "US.MU", 124),
            "T": ("00206R102", "COM", "US.T", 177)}


def sha(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def save_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def main() -> None:
    inputs = {
        "prices": ROOT / "data/test_prices.parquet",
        "events": ROOT / "data/consumed_price_events.parquet",
        "features": ROOT / "data/test_features_context.parquet",
        "source_receipts": ROOT / "data/PRICE_SOURCE_RECEIPTS.json",
        "r7_overlay": HERE.parent / "R7_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet",
        "issuer_web_facts": HERE / "EVENT_PUBLIC_SOURCES.json",
    }
    input_hashes = {key: sha(path) for key, path in inputs.items()}
    if input_hashes["prices"] != "d056d46fc7d45b8eaaad770b2767ddb14b5d055dd7b17d6e9a0aedc463f68c91":
        raise ValueError("Joint batch original 2026 price identity changed")
    if input_hashes["r7_overlay"] != "4e6420236e57999911ae0bd6745f4d4b396418e5c5e72058c36667ec66eadd65":
        raise ValueError("Prior R7 overlay identity changed")
    facts = json.loads(inputs["issuer_web_facts"].read_text(encoding="utf-8"))
    if facts["original_http_bodies_saved"] or facts["historical_vendor_actual_receipt_observed"]:
        raise ValueError("Issuer page or vendor receipt evidence tier was overstated")
    public = pd.DataFrame(facts["events"])
    public["public_date"] = pd.to_datetime(public.public_date)
    public["event_date"] = pd.to_datetime(public.record_and_original_vendor_event_date)
    if len(public) != 5 or public.duplicated(["ticker", "event_date"]).any():
        raise ValueError("Expected five distinct issuer cash events")
    if public.groupby("ticker").size().to_dict() != {"MU": 2, "T": 3}:
        raise ValueError("Unexpected MU/T public event chain")

    price_cols = ["ticker", "trade_date", "open", "close", "raw_open", "raw_close",
                  "price_coordinate", "original_transport", "transport_used",
                  "price_quality_warning", "unresolved_event_on_or_before", "lifecycle_ended",
                  "extreme_adjusted_jump"]
    prices = pd.read_parquet(inputs["prices"], columns=price_cols)
    prices = prices.loc[prices.ticker.isin(EXPECTED)].sort_values(["ticker", "trade_date"]).reset_index(drop=True)
    if prices.duplicated(["ticker", "trade_date"]).any() or prices.trade_date.max() != ASOF_EXCLUSIVE - pd.Timedelta(days=1):
        raise ValueError("Original MU/T price key range changed")
    if not prices.price_coordinate.eq(COORDINATE).all():
        raise ValueError("Price coordinate differs from joint batch")
    if not prices[["open", "close", "raw_open", "raw_close"]].gt(0).all().all():
        raise ValueError("Nonpositive original price")
    if not prices.original_transport.eq(prices.transport_used).all():
        raise ValueError("MU/T transport switch needs separate review")

    identities = pd.read_parquet(inputs["features"], columns=[
        "ticker", "cusip", "title_of_class", "moomoo_transport_code", "transport_used", "final_input_gate"])
    identities = identities.loc[identities.ticker.isin(EXPECTED)]
    if identities.empty or identities.final_input_gate.ne("INPUT_VERIFIED_THIS_GATE").any():
        raise ValueError("Joint identity/gate evidence changed")
    for ticker, (cusip, title, transport, _) in EXPECTED.items():
        rows = identities.loc[identities.ticker.eq(ticker)]
        if rows.empty or not rows.cusip.eq(cusip).all() or not rows.title_of_class.eq(title).all():
            raise ValueError(f"Original joint 13F identity differs for {ticker}")
        if not rows.moomoo_transport_code.eq(transport).all() or not rows.transport_used.eq(transport).all():
            raise ValueError(f"Original joint transport differs for {ticker}")
        quoted = prices.loc[prices.ticker.eq(ticker)]
        if not quoted.original_transport.eq(transport).all():
            raise ValueError(f"Price identity differs for {ticker}")

    event_cols = ["audit_kind", "code", "ticker", "event_date", "source_event_date",
                  "aligned_to_next_session", "factor_a", "factor_b", "share_event", "manual_wolf"]
    events = pd.read_parquet(inputs["events"], columns=event_cols)
    events = events.loc[events.ticker.isin(EXPECTED) &
                        events.event_date.ge(pd.Timestamp("2026-01-01")) &
                        events.event_date.lt(ASOF_EXCLUSIVE)].copy()
    if len(events) != 5 or events.duplicated(["ticker", "event_date"]).any():
        raise ValueError("Original consumed MU/T event chain changed")
    if not events.audit_kind.eq("APPLIED_CORPORATE_ACTION").all():
        raise ValueError("Event kind changed")
    if (events.share_event.astype(bool).any() or events.manual_wolf.astype(bool).any() or
            events.aligned_to_next_session.astype(bool).any() or not events.factor_b.eq(0).all() or
            not events.event_date.eq(events.source_event_date).all()):
        raise ValueError("MU/T event is not an ordinary zero-B cash adjustment")
    checked = events.merge(public, on=["ticker", "event_date"], how="left", validate="one_to_one", indicator=True)
    if not checked._merge.eq("both").all():
        raise ValueError("Issuer event schedule differs from original consumed events")

    receipts = json.loads(inputs["source_receipts"].read_text(encoding="utf-8"))
    bound_raw = []
    for ticker in EXPECTED:
        receipt = [row for row in receipts if row["ticker"] == ticker]
        if len(receipt) != 1 or receipt[0]["transport"] != f"US.{ticker}":
            raise ValueError(f"Original source receipt absent for {ticker}")
        for source in receipt[0]["paths"]:
            source_path = Path(source["path"])
            if not source_path.is_file() or sha(source_path) != source["sha256"]:
                raise ValueError(f"Bound Raw source changed: {source_path}")
            bound_raw.append({"ticker": ticker, "path": str(source_path), "sha256": source["sha256"]})

    verdicts = []
    for row in checked.itertuples(index=False):
        quoted = prices.loc[prices.ticker.eq(row.ticker)].reset_index(drop=True)
        index = quoted.index[quoted.trade_date.eq(row.event_date)]
        if len(index) != 1 or index[0] == 0:
            raise ValueError(f"Original prior price unavailable for {row.ticker} {row.event_date}")
        prior = quoted.iloc[index[0] - 1]
        cash = float(row.cash_usd_per_original_share)
        reconstructed = math.floor((1.0 - cash / float(prior.raw_close)) * 100000) / 100000
        if not np.isclose(float(row.factor_a), reconstructed, rtol=0, atol=1e-10):
            raise ValueError(f"Issuer cash does not reproduce original factor: {row.ticker} {row.event_date}")
        if not row.public_date < prior.trade_date:
            raise ValueError("Issuer event announcement did not predate prior session")
        if cash / float(prior.raw_close) >= 0.25:
            raise ValueError("Large distribution requires separate ex-date rule")
        if (row.code_x != f"US.{row.ticker}" or row.code_y != row.code_x or
                row.cusip != EXPECTED[row.ticker][0] or row.security_class != EXPECTED[row.ticker][1]):
            raise ValueError("Issuer/security identity differs from original joint input")
        verdicts.append({
            "ticker": row.ticker, "code": row.code_x, "cusip": row.cusip,
            "title_of_class": row.security_class, "public_date": row.public_date,
            "record_and_original_vendor_event_date": row.event_date,
            "prior_original_raw_session": prior.trade_date,
            "prior_original_raw_close": float(prior.raw_close),
            "cash_usd_per_original_share": cash,
            "original_factor_a": float(row.factor_a), "reconstructed_floor5_factor_a": reconstructed,
            "factor_b": float(row.factor_b), "source_url": row.source_url,
            "source_tier": facts["evidence_tier"],
            "exdate_basis": "FINRA_11140_B1_SMALL_PREANNOUNCED_CASH_RECORD_EQUALS_EXDATE_WITH_ORIGINAL_VENDOR_EVENT_DATE",
            "issuer_original_http_body_sha256": "UNAVAILABLE_DIRECT_HTTP_DENIED",
        })
    verdict = pd.DataFrame(verdicts).sort_values(["ticker", "record_and_original_vendor_event_date"])
    verdict.to_csv(HERE / "R8_MU_T_FIVE_EVENT_VERDICTS.csv", index=False)

    overlay_parts = []
    coverage = {}
    for ticker, (cusip, title, transport, expected_count) in EXPECTED.items():
        quoted = prices.loc[prices.ticker.eq(ticker)].copy()
        chain = verdict.loc[verdict.ticker.eq(ticker)].sort_values("record_and_original_vendor_event_date")
        first = chain.record_and_original_vendor_event_date.min()
        warning = quoted.loc[quoted.price_quality_warning.astype(bool)].copy()
        after_first = quoted.loc[quoted.trade_date.ge(first)].copy()
        if len(warning) != expected_count or len(after_first) != expected_count:
            raise ValueError(f"Policy-independent warning count changed for {ticker}")
        if not warning[["unresolved_event_on_or_before", "price_quality_warning"]].astype(bool).all().all():
            raise ValueError("Non-cash-event price warning in overlay")
        if warning[["lifecycle_ended", "extreme_adjusted_jump"]].astype(bool).any().any():
            raise ValueError("Independent lifecycle/jump warning needs separate proof")
        if not warning.trade_date.equals(after_first.trade_date):
            raise ValueError("Cash event warning does not follow the entire event chain")
        latest_events = []
        publication_dates = []
        chain_lengths = []
        for date in warning.trade_date:
            prior_events = chain.loc[chain.record_and_original_vendor_event_date.le(date)]
            if prior_events.empty:
                raise ValueError("Warning precedes approved first event")
            latest_events.append(prior_events.record_and_original_vendor_event_date.iloc[-1])
            publication_dates.append(prior_events.public_date.iloc[-1])
            chain_lengths.append(len(prior_events))
        warning["date"] = warning.pop("trade_date")
        warning["scope"] = "POLICY_INDEPENDENT_POSTHOC_EVALUATION_PRICE_COORDINATE_ONLY"
        warning["cusip"] = cusip
        warning["title_of_class"] = title
        warning["latest_proven_event_date"] = latest_events
        warning["latest_issuer_public_date"] = publication_dates
        warning["proven_event_chain_length"] = chain_lengths
        warning["no_next_unproved_consumed_event_through_exclusive"] = ASOF_EXCLUSIVE
        overlay_parts.append(warning)
        coverage[ticker] = {"entire_original_warning_price_keys": len(warning),
                            "first_verified_event": str(first.date()),
                            "last_price_date": str(warning.date.max().date()),
                            "consumed_2026_cash_events_verified": len(chain)}
    overlay = pd.concat(overlay_parts, ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)
    r7 = pd.read_parquet(inputs["r7_overlay"], columns=["ticker", "date"])
    if len(overlay) != 301 or overlay.duplicated(["ticker", "date"]).any():
        raise ValueError("R8 policy-independent exact key set changed")
    if len(overlay.merge(r7, on=["ticker", "date"])):
        raise ValueError("R8 key overlaps an existing R7 restoration")
    if not (overlay.latest_issuer_public_date.lt(overlay.latest_proven_event_date) &
            overlay.latest_proven_event_date.le(overlay.date) &
            overlay.date.lt(overlay.no_next_unproved_consumed_event_through_exclusive)).all():
        raise ValueError("R8 event/publication clock failed")
    path = HERE / "R8_MU_T_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet"
    overlay.to_parquet(path, index=False)
    output_hashes = {item.name: sha(item) for item in [path, HERE / "R8_MU_T_FIVE_EVENT_VERDICTS.csv"]}
    save_json(HERE / "R8_MU_T_OVERLAY_RECEIPT.json", {
        "status": "R8_MU_T_PRICE_GATE_PREPARED_NO_ACCOUNT_REPLAY",
        "scope": "2026 evaluation price-coordinate proxy only; no 2026 training or policy selection",
        "issuer_original_http_bodies_saved": False,
        "issuer_source_tier": facts["evidence_tier"],
        "historical_vendor_actual_receipt_observed": False,
        "input_sha256": input_hashes,
        "original_raw_source_sha256": bound_raw,
        "event_verdicts": verdict.to_dict("records"),
        "policy_independent_exact_price_keys": len(overlay),
        "coverage": coverage,
        "prior_r7_keys_preserved_disjoint": len(r7),
        "excluded_extreme_jump_flyx_key": ["FLYX", "2026-01-08"],
        "reason_flyx_excluded": "Issuer primary source independently proves the close, but no issuer/exchange original open-price body was retained for a full open/close execution row.",
        "output_sha256": output_hashes,
        "model_fit_calls": 0,
        "policy_calls": 0,
        "ledger_replay_calls": 0,
    })
    print(json.dumps({"status": "PASS", "overlay_keys": len(overlay), "coverage": coverage,
                      "overlay_sha256": output_hashes[path.name]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
