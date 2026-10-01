"""Prove only BYND's 2026-08-14 frozen-account open and close fields."""

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
STAGE = WORKSPACE / "a2_strict_method_retrain_20260926" / "test2026_stage"
DAY = pd.Timestamp("2026-08-14")
PREVIOUS = pd.Timestamp("2026-08-13")
TICKER = "BYND"
CODE = "US.BYND"
OLD_CUSIP = "08862E109"
NEW_CUSIP = "08862E307"
RATIO = 30.0
COORDINATE = "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN"
EVIDENCE_ID = "ROUND2_BYND_20260814_REVERSE_SPLIT_INDEX_UNIT"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_close(actual: float, expected: float, label: str) -> None:
    assert np.isfinite(actual) and np.isfinite(expected), label
    assert np.isclose(actual, expected, rtol=0, atol=1e-9), (label, actual, expected)


def exactly_one(frame: pd.DataFrame, label: str) -> pd.Series:
    assert len(frame) == 1, (label, len(frame))
    return frame.iloc[0]


def main() -> None:
    paths = {
        "dynamic_queue": HERE.parent / "DYNAMIC_NEXT_INPUT_QUEUE.csv",
        "blocked_buy_queue": HERE.parent / "queue/KNOWN_BLOCKED_BUY_DEMAND.csv",
        "joint_prices": JOINT / "data/test_prices.parquet",
        "old_prices": OLD / "data/test_prices.parquet",
        "calendar": JOINT / "data/calendar.parquet",
        "consumed_events": OLD / "data/consumed_price_events.parquet",
        "event_audit": STAGE / "r4_event_pit/ALL_1094_EVENT_PRIORITY.csv",
        "security_identity": STAGE / "r4_event_pit/EVENT_SECURITY_PRIORITY.csv",
        "source_receipts": OLD / "data/PRICE_SOURCE_RECEIPTS.json",
        "fixed_raw": STAGE / "fixed_window_raw/RAW_US_BYND_K_DAY_NONE_RTH.parquet",
        "frozen_account_engine": JOINT / "engine.py",
    }
    hashes = {name: {"path": str(path), "sha256": sha(path)} for name, path in paths.items()}
    assert hashes["joint_prices"]["sha256"] == hashes["old_prices"]["sha256"]

    queue = pd.read_csv(paths["dynamic_queue"], dtype=str).fillna("")
    needed = queue.loc[queue.ticker.eq(TICKER) & queue.date.eq("2026-08-14")]
    assert len(needed) == 2 and set(needed.field) == {"open", "close"}
    assert not needed.duplicated(["ticker", "date", "field"]).any()
    assert needed.current_repaired_account_need.eq("True").all()
    assert needed.frozen_price_field_status.eq("FROZEN_FIELD_PRESENT_BUT_UNRESOLVED_EVENT_ON_OR_BEFORE").all()
    expected_runs = {
        f"joint_{strategy}_{bps}bps"
        for strategy in ("elastic_net", "q90") for bps in (5, 10, 25)
    }
    assert all(set(r.split("|")) == expected_runs for r in needed.current_run_ids)
    assert needed.actually_consumed_by_run_ids.eq("").all()
    open_need = exactly_one(needed.loc[needed.field.eq("open")], "open queue")
    close_need = exactly_one(needed.loc[needed.field.eq("close")], "close queue")
    assert open_need.pending_signal_dates == "2026-08-13"
    assert {"requested_target_buy", "requested_position_sell", "held_position_pretrade_nav_or_exit"}.issubset(
        set(open_need.purposes.split("|"))
    )
    assert "actual_held_position_valuation" in close_need.purposes.split("|")

    old_buy = pd.read_csv(paths["blocked_buy_queue"], dtype=str).fillna("")
    old_buy = exactly_one(old_buy.loc[old_buy.ticker.eq(TICKER) & old_buy.execution_date.eq("2026-08-14")], "old blocked buy")
    assert old_buy.signal_date == "2026-08-13" and old_buy.old_blocked_buy_path_count == "3"
    assert set(old_buy.old_blocked_buy_run_ids.split("|")) == {
        f"hgb_return_baseline_{bps}bps" for bps in (5, 10, 25)
    }
    assert "qualified_execution_open" in old_buy.needed_field

    calendar = pd.read_parquet(paths["calendar"])
    session = exactly_one(calendar.loc[calendar.trade_date.eq(DAY)], "calendar day")
    assert bool(session.is_test)
    prices = pd.read_parquet(paths["joint_prices"])
    p0 = exactly_one(prices.loc[prices.ticker.eq(TICKER) & prices.trade_date.eq(PREVIOUS)], "prior price")
    p1 = exactly_one(prices.loc[prices.ticker.eq(TICKER) & prices.trade_date.eq(DAY)], "split-day price")
    for row in (p0, p1):
        assert row.original_transport == CODE and row.transport_used == CODE
        assert row.price_coordinate == COORDINATE
        for field in ("open", "close", "raw_open", "raw_close", "volume"):
            assert np.isfinite(row[field]) and row[field] > 0, (row.trade_date, field)
        assert not bool(row.lifecycle_ended) and not bool(row.extreme_adjusted_jump)
    assert not bool(p0.unresolved_event_on_or_before) and not bool(p0.price_quality_warning)
    assert bool(p1.unresolved_event_on_or_before) and bool(p1.price_quality_warning)

    receipts = json.loads(paths["source_receipts"].read_text("utf-8"))
    receipt = [r for r in receipts if r["ticker"] == TICKER and r["original_code"] == CODE]
    assert len(receipt) == 1 and receipt[0]["transport"] == CODE
    raw_receipt = [r for r in receipt[0]["paths"] if Path(r["path"]).name == paths["fixed_raw"].name]
    assert len(raw_receipt) == 1 and raw_receipt[0]["sha256"] == hashes["fixed_raw"]["sha256"]
    raw = pd.read_parquet(paths["fixed_raw"])
    r0 = exactly_one(raw.loc[raw.code.eq(CODE) & raw.trade_date.eq(PREVIOUS)], "prior same-source Raw")
    r1 = exactly_one(raw.loc[raw.code.eq(CODE) & raw.trade_date.eq(DAY)], "split-day same-source Raw")
    assert r0["name"] == "Beyond Meat" and r1["name"] == "Beyond Meat"
    for adjusted, source in ((p0, r0), (p1, r1)):
        is_close(adjusted.raw_open, source.open, "source raw open")
        is_close(adjusted.raw_close, source.close, "source raw close")
    is_close(r1.last_close, r0.close, "same-source prior close")
    is_close(r1.last_close, 0.407, "original prior close")

    audit = pd.read_csv(paths["event_audit"])
    event_audit = exactly_one(
        audit.loc[audit.code.eq(CODE) & audit.source_event_date.eq("2026-08-14")], "r4 event audit"
    )
    events = pd.read_parquet(paths["consumed_events"])
    e2026 = events.loc[
        events.code.eq(CODE) & pd.to_datetime(events.event_date).between("2026-01-01", DAY)
    ]
    event = exactly_one(e2026, "2026 consumed event through authorized day")
    for item in (event_audit, event):
        assert item.audit_kind == "APPLIED_CORPORATE_ACTION"
        assert item.code == CODE and item.ticker == TICKER
        assert pd.Timestamp(item.event_date) == DAY
        assert pd.Timestamp(item.source_event_date) == DAY
        assert not bool(item.aligned_to_next_session) and bool(item.share_event)
        is_close(float(item.factor_a), RATIO, "split factor a")
        is_close(float(item.factor_b), 0.0, "split factor b")
    assert event_audit.original_code == CODE and event_audit.transport_code == CODE
    is_close(float(event_audit.prior_raw_close), r0.close, "audited prior Raw close")

    identity = pd.read_csv(paths["security_identity"], dtype={"cusip": str})
    old_identity = identity.loc[
        identity.original_code.eq(CODE)
        & identity.transport_code.eq(CODE)
        & identity.source_event_date.eq("2026-08-14")
    ]
    assert set(old_identity.quarter) == {"2026Q1", "2026Q2"}
    assert set(old_identity.cusip) == {OLD_CUSIP}
    assert set(old_identity.title_of_class) == {"COM"}
    assert old_identity.factor_a.eq(RATIO).all() and old_identity.factor_b.eq(0.0).all()
    assert old_identity.share_event.all()

    # The frozen engine operates on price-index units. The 1:30 reverse split
    # maps post-split raw prices to one-thirtieth of their raw share price.
    assert p0.raw_open != p0.raw_close
    alpha_before = (p0.open - p0.close) / (p0.raw_open - p0.raw_close)
    beta_before = p0.open - alpha_before * p0.raw_open
    is_close(alpha_before, 1.0, "pre-split index alpha")
    is_close(beta_before, 0.0, "pre-split index beta")
    is_close(p0.volume, r0.volume, "pre-split index volume")
    alpha_after = alpha_before / RATIO
    is_close(p1.open, alpha_after * r1.open + beta_before, "split-day index open")
    is_close(p1.close, alpha_after * r1.close + beta_before, "split-day index close")
    is_close(p1.volume, RATIO * r1.volume, "split-day index volume")
    is_close(r1.open, 12.21, "post-split raw open")
    is_close(r1.close, 13.47, "post-split raw close")
    is_close(p1.open, 0.407, "frozen-account open")
    is_close(p1.close, 0.449, "frozen-account close")

    out = pd.DataFrame([{
        "ticker": TICKER,
        "trade_date": DAY,
        "open": round(float(p1.open), 9),
        "close": round(float(p1.close), 9),
        "open_authorized": True,
        "close_authorized": True,
        "evidence_id": EVIDENCE_ID,
        "candidate_pool_version": "R6_UNCHANGED",
        "pre_split_cusip": OLD_CUSIP,
        "post_split_cusip": NEW_CUSIP,
        "fixed_raw_sha256": hashes["fixed_raw"]["sha256"],
    }])
    csv_path = HERE / "ROUND2_BYND_EVENT_ACCOUNT_PRICE_FIELDS.csv"
    parquet_path = HERE / "ROUND2_BYND_EVENT_ACCOUNT_PRICE_FIELDS.parquet"
    out.to_csv(csv_path, index=False)
    out.to_parquet(parquet_path, index=False)
    proof = {
        "status": "EXACT_SPLIT_DAY_ACCOUNT_OPEN_CLOSE_PROVEN",
        "authorized_keys": [[TICKER, "2026-08-14", "open"], [TICKER, "2026-08-14", "close"]],
        "authorized_ticker_dates": 1,
        "excluded_scope": "No BYND date after 2026-08-14 and no other ticker or field is authorized by this proof.",
        "candidate_pool_version": "R6_UNCHANGED",
        "current_account_run_ids": sorted(expected_runs),
        "prior_signal_date_for_open": "2026-08-13",
        "old_blocked_buy_path_count": 3,
        "old_blocked_buy_run_ids": sorted(old_buy.old_blocked_buy_run_ids.split("|")),
        "actually_consumed_by_current_runs": False,
        "event": {
            "type": "1-for-30 reverse stock split of common stock",
            "old_cusip": OLD_CUSIP,
            "new_cusip": NEW_CUSIP,
            "same_symbol": TICKER,
            "expected_effective_et": "2026-08-13 23:59",
            "post_split_trading_open": "2026-08-14",
            "issuer_public_8k_sec_filing_date": "2026-08-11",
            "issuer_public_8k_sec_acceptance_display": "2026-08-11 07:07:18",
            "nasdaq_alert_date": "2026-08-12",
            "issuer_sec_index": "https://www.sec.gov/Archives/edgar/data/1655210/000165521026000057/0001655210-26-000057-index.htm",
            "issuer_sec_exhibit": "https://www.sec.gov/Archives/edgar/data/1655210/000165521026000057/ex991pressreleaseannouncin.htm",
            "nasdaq_alert": "https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2026-568",
            "old_cusip_sec_source": "https://www.sec.gov/Archives/edgar/data/1655210/000159588826000005/xslSCHEDULE_13G_X01/primary_doc.xml",
        },
        "index_coordinate": {
            "name": COORDINATE,
            "alpha_before": alpha_before,
            "beta_before": beta_before,
            "alpha_after": alpha_after,
            "raw_open": float(r1.open),
            "raw_close": float(r1.close),
            "raw_volume": float(r1.volume),
            "authorized_open": round(float(p1.open), 9),
            "authorized_close": round(float(p1.close), 9),
            "adjusted_index_volume": float(p1.volume),
            "unit": "frozen-account price-index unit, not raw post-split share",
        },
        "historical_vendor_factor_receipt_observed": False,
        "issuer_or_exchange_page_bytes_archived": False,
        "input_sha256": hashes,
        "output_sha256": {csv_path.name: sha(csv_path), parquet_path.name: sha(parquet_path)},
        "model_fit_calls": 0,
        "preprocessor_fit_calls": 0,
        "account_replay_calls": 0,
    }
    (HERE / "ROUND2_BYND_PROOF.json").write_text(
        json.dumps(proof, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )
    print(json.dumps({"authorized_keys": proof["authorized_keys"], "index_open": p1.open, "index_close": p1.close}))


if __name__ == "__main__":
    main()
