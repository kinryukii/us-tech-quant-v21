"""Prove SLMT split-day and suffix index-coordinate account fields only."""

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
FIRST = pd.Timestamp("2026-05-14")
END = pd.Timestamp("2026-09-24")
CODE = "US.SLMT"
TICKER = "SLMT"
ORIGINAL_CUSIP = "G13311116"
SUCCESSOR_CUSIP = "G13311132"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def same(a: pd.Series, b: pd.Series, label: str) -> None:
    x, y = a.to_numpy(float), b.to_numpy(float)
    assert np.isfinite(x).all() and np.isfinite(y).all(), label
    assert np.allclose(x, y, rtol=0, atol=1e-7), (label, np.max(np.abs(x - y)))


def main() -> None:
    paths = {
        "joint_prices": JOINT / "data/test_prices.parquet",
        "old_prices": OLD / "data/test_prices.parquet",
        "calendar": JOINT / "data/calendar.parquet",
        "consumed_events": OLD / "data/consumed_price_events.parquet",
        "event_audit": STAGE / "r4_event_pit/ALL_1094_EVENT_PRIORITY.csv",
        "security_identity": STAGE / "r4_event_pit/EVENT_SECURITY_PRIORITY.csv",
        "source_receipts": OLD / "data/PRICE_SOURCE_RECEIPTS.json",
        "original_adjustment_builder": Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\scripts\run_rebuild.py"),
        "frozen_account_engine": JOINT / "engine.py",
        "fixed_raw": STAGE / "fixed_window_raw/RAW_US_SLMT_K_DAY_NONE_RTH.parquet",
    }
    hashes = {name: {"path": str(path), "sha256": sha(path)} for name, path in paths.items()}
    assert hashes["joint_prices"]["sha256"] == hashes["old_prices"]["sha256"]
    p = pd.read_parquet(paths["joint_prices"])
    calendar = pd.read_parquet(paths["calendar"])
    events = pd.read_parquet(paths["consumed_events"])
    audit = pd.read_csv(paths["event_audit"])
    identity = pd.read_csv(paths["security_identity"], dtype={"cusip": str})
    receipts = json.loads(paths["source_receipts"].read_text("utf-8"))
    receipt = [r for r in receipts if r["original_code"] == CODE]
    assert len(receipt) == 1 and receipt[0]["transport"] == CODE and receipt[0]["ticker"] == TICKER
    fixed_receipt = [r for r in receipt[0]["paths"] if Path(r["path"]).name == paths["fixed_raw"].name]
    assert len(fixed_receipt) == 1 and fixed_receipt[0]["sha256"] == hashes["fixed_raw"]["sha256"]
    one_identity = identity.loc[identity.transport_code.eq(CODE) & identity.source_event_date.eq("2026-05-14")]
    assert len(one_identity) > 0 and set(one_identity.cusip) == {ORIGINAL_CUSIP}
    assert one_identity.share_event.eq(True).all() and one_identity.factor_a.eq(10).all()

    e = events.loc[events.audit_kind.eq("APPLIED_CORPORATE_ACTION") & events.code.eq(CODE)]
    e2026 = e.loc[pd.to_datetime(e.event_date).ge("2026-01-01")]
    assert len(e2026) == 1 and pd.Timestamp(e2026.event_date.iloc[0]) == FIRST
    original = audit.loc[audit.code.eq(CODE) & audit.source_event_date.eq("2026-05-14")]
    assert len(original) == 1
    for item in (e2026.iloc[0], original.iloc[0]):
        assert pd.Timestamp(item.event_date) == FIRST
        assert pd.Timestamp(item.source_event_date) == FIRST
        assert float(item.factor_a) == 10.0 and float(item.factor_b) == 0.0
        assert bool(item.share_event) and not bool(item.aligned_to_next_session)

    before = p.loc[p.ticker.eq(TICKER) & p.trade_date.lt(FIRST)].sort_values("trade_date").tail(1)
    assert len(before) == 1 and not bool(before.price_quality_warning.iloc[0])
    before = before.iloc[0]
    assert before.trade_date == pd.Timestamp("2026-05-13")
    assert before.raw_open != before.raw_close
    alpha_before = (before.open - before.close) / (before.raw_open - before.raw_close)
    beta_before = before.open - alpha_before * before.raw_open
    assert abs(alpha_before - 0.1) < 1e-12 and abs(beta_before) < 1e-12

    raw = pd.read_parquet(paths["fixed_raw"], columns=["code", "trade_date", "open", "close", "volume"])
    raw["trade_date"] = pd.to_datetime(raw.trade_date)
    raw_before = raw.loc[raw.code.eq(CODE) & raw.trade_date.eq(before.trade_date)]
    assert len(raw_before) == 1 and raw_before.volume.iloc[0] > 0
    same(pd.Series([before.raw_open]), raw_before.open, "prior_raw_open")
    same(pd.Series([before.raw_close]), raw_before.close, "prior_raw_close")
    volume_scale_before = before.volume / float(raw_before.volume.iloc[0])
    assert abs(volume_scale_before - 10.0) < 1e-12

    q = p.loc[p.ticker.eq(TICKER) & p.trade_date.between(FIRST, END)].copy()
    sessions = set(calendar.loc[
        calendar.is_test.astype(bool) & calendar.trade_date.between(FIRST, END), "trade_date"
    ])
    assert len(q) == len(sessions) and set(q.trade_date) == sessions
    assert q.original_transport.eq(CODE).all() and q.transport_used.eq(CODE).all()
    assert q.price_coordinate.eq("PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN").all()
    assert q.unresolved_event_on_or_before.all() and q.price_quality_warning.all()
    assert not q.lifecycle_ended.any() and not q.extreme_adjusted_jump.any()
    for field in ["open", "close", "raw_open", "raw_close", "volume"]:
        assert np.isfinite(q[field]).all() and q[field].gt(0).all(), field
    r = raw.loc[raw.code.eq(CODE) & raw.trade_date.isin(sessions)]
    assert len(r) == len(q) and not r.duplicated("trade_date").any()
    merged = q.merge(r[["trade_date", "open", "close", "volume"]], on="trade_date", validate="one_to_one", suffixes=("", "_source"))
    same(merged.raw_open, merged.open_source, "raw_open")
    same(merged.raw_close, merged.close_source, "raw_close")
    same(merged.open, alpha_before / 10.0 * merged.raw_open + beta_before, "adjusted_open")
    same(merged.close, alpha_before / 10.0 * merged.raw_close + beta_before, "adjusted_close")
    same(merged.volume, volume_scale_before * 10.0 * merged.volume_source, "adjusted_index_volume")

    out = q[["ticker", "trade_date", "open", "close"]].copy()
    out["open_authorized"] = True
    out["close_authorized"] = True
    out["evidence_id"] = "SLMT_20260514_CLASS_B_REVERSE_SPLIT_INDEX_UNIT"
    out["candidate_pool_version"] = "R6_UNCHANGED"
    out["pre_split_cusip"] = ORIGINAL_CUSIP
    out["post_split_cusip"] = SUCCESSOR_CUSIP
    out["fixed_raw_sha256"] = hashes["fixed_raw"]["sha256"]
    csv_path = HERE / "SLMT_SPLIT_ACCOUNT_PRICE_FIELDS.csv"
    parquet_path = HERE / "SLMT_SPLIT_ACCOUNT_PRICE_FIELDS.parquet"
    out.to_csv(csv_path, index=False)
    out.to_parquet(parquet_path, index=False)
    proof = {
        "status": "CLASS_B_SPLIT_IDENTITY_AND_INDEX_UNITS_PROVEN_FOR_ACCOUNT_FIELDS",
        "first_authorized": "2026-05-14", "last_authorized": str(out.trade_date.max().date()),
        "authorized_ticker_dates": len(out), "open_authorized": True, "close_authorized": True,
        "candidate_pool_version": "R6_UNCHANGED",
        "pre_split_cusip": ORIGINAL_CUSIP, "post_split_cusip": SUCCESSOR_CUSIP,
        "split_ratio": "1 post-split Class B share for 10 pre-split Class B shares",
        "same_symbol": TICKER, "original_consumed_factor_a": 10.0,
        "alpha_before": alpha_before, "alpha_after": alpha_before / 10.0,
        "volume_scale_before": volume_scale_before, "volume_scale_after": volume_scale_before * 10.0,
        "engine_unit": "per-security price-index unit, not raw share",
        "issuer_public_date": "2026-05-12",
        "issuer_sec_exhibit": "https://www.sec.gov/Archives/edgar/data/1939965/000121390026054724/ea029020401ex99-1.htm",
        "old_cusip_class_b_sec_source": "https://www.sec.gov/Archives/edgar/data/1939965/000172982926000003/xslSCHEDULE_13G_X01/primary_doc.xml",
        "nasdaq_split_and_new_cusip_source": "https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2026-318",
        "historical_vendor_receipt_observed": False,
        "issuer_page_bytes_archived": False,
        "price_coordinate": "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN",
        "input_sha256": hashes,
        "output_sha256": {csv_path.name: sha(csv_path), parquet_path.name: sha(parquet_path)},
        "model_fit_calls": 0, "preprocessor_fit_calls": 0, "account_replay_calls": 0,
    }
    (HERE / "SLMT_SPLIT_PROOF.json").write_text(json.dumps(proof, indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(json.dumps({"authorized_ticker_dates": len(out), "first": proof["first_authorized"], "last": proof["last_authorized"]}))


if __name__ == "__main__":
    main()
