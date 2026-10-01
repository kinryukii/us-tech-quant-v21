"""Policy-independent AAPL cash-event price proof for the existing joint batch.

Only original price, event, identity and source receipts are read. There is no
policy, holding, model, score, training or account dependency in key selection.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pandas as pd


HERE = Path(__file__).resolve().parent
VALUATION = HERE.parent
ROOT = HERE.parents[2]
ASOF_EXCLUSIVE = pd.Timestamp("2026-09-25")
COORDINATE = "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN"
EXPECTED_EVENTS = ("2026-02-09", "2026-05-11", "2026-08-10")


def sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main() -> None:
    inputs = {
        "prices": ROOT / "data/test_prices.parquet",
        "events": ROOT / "data/consumed_price_events.parquet",
        "features": ROOT / "data/test_features_context.parquet",
        "source_receipts": ROOT / "data/PRICE_SOURCE_RECEIPTS.json",
        "r7_overlay": VALUATION / "R7_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet",
        "r8_overlay": VALUATION / "r8_mu_t/R8_MU_T_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet",
        "issuer_web_facts": VALUATION / "aapl_triage/EVENT_PUBLIC_SOURCES.json",
    }
    hashes = {name: sha(path) for name, path in inputs.items()}
    if hashes["prices"] != "d056d46fc7d45b8eaaad770b2767ddb14b5d055dd7b17d6e9a0aedc463f68c91":
        raise ValueError("Original joint price identity changed")
    if hashes["r7_overlay"] != "4e6420236e57999911ae0bd6745f4d4b396418e5c5e72058c36667ec66eadd65":
        raise ValueError("R7 exact overlay identity changed")
    if hashes["r8_overlay"] != "016127789e974f8d6183313d0326055c6984b035a980142df225bc3b05847457":
        raise ValueError("R8 exact overlay identity changed")

    facts = json.loads(inputs["issuer_web_facts"].read_text(encoding="utf-8"))
    if facts["original_http_bodies_saved"] or facts["historical_vendor_actual_receipt_observed"]:
        raise ValueError("Issuer or vendor source evidence overstated")
    public = pd.DataFrame(facts["events"])
    public["event_date"] = pd.to_datetime(public.record_and_original_vendor_event_date)
    public["public_date"] = pd.to_datetime(public.public_date)
    if (len(public) != 3 or public.ticker.ne("AAPL").any() or
            tuple(public.event_date.dt.strftime("%Y-%m-%d")) != EXPECTED_EVENTS):
        raise ValueError("Unexpected issuer announcement schedule")
    if (public.code.ne("US.AAPL").any() or public.cusip.ne("037833100").any() or
            public.security_class.ne("COM").any()):
        raise ValueError("Issuer source security identity changed")

    prices = pd.read_parquet(inputs["prices"])
    prices = prices.loc[prices.ticker.eq("AAPL")].sort_values("trade_date").reset_index(drop=True)
    if (prices.empty or prices.duplicated(["ticker", "trade_date"]).any() or
            prices.trade_date.max() != ASOF_EXCLUSIVE - pd.Timedelta(days=1)):
        raise ValueError("AAPL original price-date domain changed")
    if (prices.price_coordinate.ne(COORDINATE).any() or
            prices.original_transport.ne("US.AAPL").any() or
            prices.transport_used.ne("US.AAPL").any() or
            not prices[["open", "close", "raw_open", "raw_close"]].gt(0).all().all()):
        raise ValueError("Original AAPL price coordinate or transport changed")
    identities = pd.read_parquet(inputs["features"], columns=[
        "ticker", "cusip", "title_of_class", "moomoo_transport_code", "transport_used", "final_input_gate"])
    identities = identities.loc[identities.ticker.eq("AAPL")]
    if (identities.empty or identities.cusip.ne("037833100").any() or
            identities.title_of_class.ne("COM").any() or
            identities.moomoo_transport_code.ne("US.AAPL").any() or
            identities.transport_used.ne("US.AAPL").any() or
            identities.final_input_gate.ne("INPUT_VERIFIED_THIS_GATE").any()):
        raise ValueError("Original joint AAPL 13F identity not proved")

    events = pd.read_parquet(inputs["events"])
    events = events.loc[(events.ticker.eq("AAPL") &
                         events.event_date.ge(pd.Timestamp("2026-01-01")) &
                         events.event_date.lt(ASOF_EXCLUSIVE))].sort_values("event_date")
    if len(events) != 3 or tuple(events.event_date.dt.strftime("%Y-%m-%d")) != EXPECTED_EVENTS:
        raise ValueError("Original consumed AAPL event prefix changed")
    if (events.audit_kind.ne("APPLIED_CORPORATE_ACTION").any() or
            events.code.ne("US.AAPL").any() or
            events.share_event.astype(bool).any() or events.manual_wolf.astype(bool).any() or
            events.aligned_to_next_session.astype(bool).any() or
            events.factor_b.ne(0).any() or
            not events.event_date.equals(events.source_event_date)):
        raise ValueError("Consumed AAPL events are not the original cash-only chain")
    receipt_list = json.loads(inputs["source_receipts"].read_text(encoding="utf-8"))
    source_rows = [item for item in receipt_list if item.get("ticker") == "AAPL"]
    if len(source_rows) != 1 or source_rows[0]["transport"] != "US.AAPL":
        raise ValueError("Bound AAPL Raw source receipt missing")
    bound_raw = []
    for item in source_rows[0]["paths"]:
        path = Path(item["path"])
        if not path.is_file() or sha(path) != item["sha256"]:
            raise ValueError(f"Bound original Raw source changed: {path}")
        bound_raw.append({"path": str(path), "sha256": item["sha256"]})

    verdicts = []
    for original, issuer in zip(events.itertuples(index=False), public.itertuples(index=False), strict=True):
        if original.event_date != issuer.event_date:
            raise ValueError("Issuer and original event dates differ")
        match = prices.index[prices.trade_date.eq(original.event_date)]
        if len(match) != 1 or match[0] == 0:
            raise ValueError("Original previous Raw close unavailable")
        prior = prices.iloc[match[0] - 1]
        cash = float(issuer.cash_usd_per_original_share)
        floor5 = math.floor((1.0 - cash / float(prior.raw_close)) * 100000) / 100000
        if abs(float(original.factor_a) - floor5) > 1e-10:
            raise ValueError("Original A factor does not match issuer cash and Raw prior close")
        if not issuer.public_date < prior.trade_date or cash / float(prior.raw_close) >= .25:
            raise ValueError("Publication or normal cash ex-date qualification failed")
        verdicts.append({
            "ticker": "AAPL", "code": "US.AAPL", "cusip": "037833100", "title_of_class": "COM",
            "public_date": issuer.public_date, "record_and_original_vendor_event_date": issuer.event_date,
            "prior_original_raw_session": prior.trade_date,
            "prior_original_raw_close": float(prior.raw_close),
            "cash_usd_per_original_share": cash,
            "original_factor_a": float(original.factor_a),
            "reconstructed_floor5_factor_a": floor5,
            "factor_b": float(original.factor_b),
            "source_url": issuer.source_url,
            "source_tier": facts["evidence_tier"],
            "exdate_basis": "FINRA_11140_B1_SMALL_PREANNOUNCED_CASH_RECORD_EQUALS_EXDATE_WITH_ORIGINAL_VENDOR_EVENT_DATE",
            "issuer_original_http_body_sha256": "UNAVAILABLE_NOT_SAVED",
        })
    verdict_path = HERE / "R9_AAPL_THREE_EVENT_VERDICTS.csv"
    pd.DataFrame(verdicts).to_csv(verdict_path, index=False)

    warnings = prices.loc[prices.price_quality_warning.astype(bool)].copy()
    after_first = prices.loc[prices.trade_date.ge(pd.Timestamp(EXPECTED_EVENTS[0]))].copy()
    if len(warnings) != 158 or warnings.trade_date.tolist() != after_first.trade_date.tolist():
        raise ValueError("AAPL original warning domain is not exactly the 158 post-event dates")
    if (not warnings.unresolved_event_on_or_before.astype(bool).all() or
            warnings.lifecycle_ended.astype(bool).any() or
            warnings.extreme_adjusted_jump.astype(bool).any()):
        raise ValueError("An independent AAPL warning remains unqualified")
    latest = []
    public_dates = []
    chain_lengths = []
    for date in warnings.trade_date:
        prefix = public.loc[public.event_date.le(date)]
        if prefix.empty:
            raise ValueError("Warning predates complete issuer event prefix")
        latest.append(prefix.event_date.iloc[-1])
        public_dates.append(prefix.public_date.iloc[-1])
        chain_lengths.append(len(prefix))
    if pd.Series(chain_lengths).value_counts().sort_index().to_dict() != {1: 63, 2: 62, 3: 33}:
        raise ValueError("AAPL original three-event warning segments changed")
    warnings["date"] = warnings.pop("trade_date")
    warnings["scope"] = "POLICY_INDEPENDENT_POSTHOC_EVALUATION_PRICE_COORDINATE_ONLY"
    warnings["cusip"] = "037833100"
    warnings["title_of_class"] = "COM"
    warnings["latest_proven_event_date"] = latest
    warnings["latest_issuer_public_date"] = public_dates
    warnings["proven_event_chain_length"] = chain_lengths
    warnings["no_next_unproved_consumed_event_through_exclusive"] = ASOF_EXCLUSIVE
    for key, count in (("r7_overlay", 811), ("r8_overlay", 301)):
        earlier = pd.read_parquet(inputs[key], columns=["ticker", "date"])
        if len(earlier) != count or len(warnings.merge(earlier, on=["ticker", "date"])):
            raise ValueError(f"R9 key overlaps or changes {key}")
    if not (warnings.latest_issuer_public_date.lt(warnings.latest_proven_event_date) &
            warnings.latest_proven_event_date.le(warnings.date) &
            warnings.date.lt(warnings.no_next_unproved_consumed_event_through_exclusive)).all():
        raise ValueError("AAPL publication/event/date prefix broken")
    overlay_path = HERE / "R9_AAPL_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet"
    warnings.to_parquet(overlay_path, index=False)
    outputs = {path.name: sha(path) for path in (overlay_path, verdict_path)}
    receipt = {
        "status": "R9_AAPL_PRICE_GATE_PREPARED_NO_ACCOUNT_REPLAY",
        "scope": "2026 evaluation price-coordinate proxy only; not shareholder total return",
        "issuer_source_tier": facts["evidence_tier"],
        "issuer_original_http_bodies_saved": False,
        "historical_vendor_actual_receipt_observed": False,
        "input_sha256": hashes,
        "original_raw_source_sha256": bound_raw,
        "event_verdicts": verdicts,
        "policy_independent_exact_price_keys": 158,
        "three_event_segment_counts": {"2026-02-09": 63, "2026-05-11": 62, "2026-08-10": 33},
        "prior_r7_keys_preserved_disjoint": 811,
        "prior_r8_keys_preserved_disjoint": 301,
        "output_sha256": outputs,
        "model_fit_calls": 0,
        "policy_calls": 0,
        "ledger_replay_calls": 0,
    }
    (HERE / "R9_AAPL_OVERLAY_RECEIPT.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "keys": 158, "segments": receipt["three_event_segment_counts"],
                      "overlay_sha256": outputs[overlay_path.name]}))


if __name__ == "__main__":
    main()
