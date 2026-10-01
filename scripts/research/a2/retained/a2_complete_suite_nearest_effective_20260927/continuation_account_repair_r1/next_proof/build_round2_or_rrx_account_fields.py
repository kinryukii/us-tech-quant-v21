"""Consume only the currently demanded OR/RRX 2026-03-31 fields."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from build_first_four_account_fields import main, sha


EVENTS = {
    "OR": {
        "cusip": "68390D106", "first": "2026-03-31", "next": "2026-06-30",
        "public": "2026-02-18", "cash": 0.055,
        "issuer_url": "https://orroyalties.com/or-royalties-declares-first-quarter-2026-dividend/",
    },
    "RRX": {
        "cusip": "758750103", "first": "2026-03-31", "next": "2026-06-30",
        "public": "2026-01-26", "cash": 0.35,
        "issuer_url": "https://s28.q4cdn.com/452460759/files/doc_news/Regal-Rexnord-Corporation-Declares-Quarterly-Dividend-of--35-per-share-2026.pdf",
    },
}


if __name__ == "__main__":
    main(EVENTS, "ROUND2_OR_RRX")
    here = Path(__file__).resolve().parent
    csv_path = here / "ROUND2_OR_RRX_EVENT_ACCOUNT_PRICE_FIELDS.csv"
    parquet_path = here / "ROUND2_OR_RRX_EVENT_ACCOUNT_PRICE_FIELDS.parquet"
    manifest_path = here / "ROUND2_OR_RRX_PROOF.json"
    all_checked = pd.read_parquet(parquet_path)
    assert len(all_checked) == 124
    workspace = here.parents[2]
    strict_stage = workspace / "a2_strict_method_retrain_20260926/test2026_stage"
    initial_path = strict_stage / "identity_feature_application_r1/CONSUMED_2026_INITIAL_ADJUSTMENT_STATE.csv"
    initial = pd.read_csv(initial_path)
    prices = pd.read_parquet(workspace / "a2_complete_suite_nearest_effective_20260927/data/test_prices.parquet")
    consumed = pd.read_parquet(workspace / "a2_complete_suite_20260927/data/consumed_price_events.parquet")
    initial_records = []
    for ticker in EVENTS:
        code = f"US.{ticker}"
        state = initial.loc[initial.moomoo_transport_code.eq(code)]
        assert len(state) == 1
        state = state.iloc[0]
        assert np.isfinite(state.initial_alpha_2026_01_02) and state.initial_alpha_2026_01_02 > 0
        assert np.isfinite(state.initial_beta_2026_01_02)
        assert state.consumed_prior_events > 0
        before = prices.loc[prices.ticker.eq(ticker) & prices.trade_date.eq(pd.Timestamp("2026-03-30"))]
        assert len(before) == 1 and not bool(before.price_quality_warning.iloc[0])
        before = before.iloc[0]
        assert np.isclose(before.open, state.initial_alpha_2026_01_02 * before.raw_open + state.initial_beta_2026_01_02, rtol=0, atol=1e-7)
        assert np.isclose(before.close, state.initial_alpha_2026_01_02 * before.raw_close + state.initial_beta_2026_01_02, rtol=0, atol=1e-7)
        earlier = consumed.loc[consumed.code.eq(code) & consumed.audit_kind.eq("APPLIED_CORPORATE_ACTION") & consumed.event_date.between("2026-01-02", "2026-03-30")]
        assert len(earlier) == 0
        initial_records.append({
            "ticker": ticker, "initial_alpha": float(state.initial_alpha_2026_01_02),
            "initial_beta": float(state.initial_beta_2026_01_02),
            "consumed_prior_events": int(state.consumed_prior_events),
            "pre_event_2026_events": len(earlier),
        })
    current = all_checked.loc[all_checked.trade_date.eq(pd.Timestamp("2026-03-31"))].copy()
    assert len(current) == 2 and set(current.ticker) == {"OR", "RRX"}
    assert current.open_authorized.all() and current.close_authorized.all()
    current.to_csv(csv_path, index=False)
    current.to_parquet(parquet_path, index=False)
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest["status"] = "CURRENT_2026_03_31_OR_RRX_FIELDS_PROVEN"
    manifest["scope"] = "ONLY_2026_03_31_EXECUTION_OPEN_AND_VALUATION_CLOSE"
    manifest["full_first_event_intervals_checked_but_not_whitelisted"] = 124
    manifest["total_unique_ticker_dates"] = 2
    manifest["verified_initial_adjustment_states"] = initial_records
    manifest["input_sha256"]["initial_adjustment_state"] = {"path": str(initial_path), "sha256": sha(initial_path)}
    for event in manifest["events"]:
        event["full_first_event_interval_checked_days"] = event["authorized_open_days"]
        event["authorized_open_days"] = 1
        event["authorized_close_days"] = 1
        event["first_authorized"] = "2026-03-31"
        event["last_authorized"] = "2026-03-31"
    manifest["output_sha256"] = {csv_path.name: sha(csv_path), parquet_path.name: sha(parquet_path)}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"current_authorized_ticker_dates": len(current), "tickers": sorted(current.ticker.tolist())}))
