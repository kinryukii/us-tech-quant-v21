"""Bounded price-field proof for the first four frozen-account blocks.

This consumes saved issuer-independent Raw, original event records, and a
documented pre-event issuer announcement. It never imports a model or replay.
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
STAGE = WORKSPACE / "a2_strict_method_retrain_20260926" / "test2026_stage"
EVENTS = {
    "T": {
        "cusip": "00206R102", "first": "2026-01-12", "next": "2026-04-10",
        "public": "2025-12-15", "cash": 0.2775,
        "issuer_url": "https://about.att.com/story/2025/february-stock-dividend-2026.html",
    },
    "CAT": {
        "cusip": "149123101", "first": "2026-01-20", "next": "2026-04-20",
        "public": "2025-12-10", "cash": 1.51,
        "issuer_url": "https://investors.caterpillar.com/news/news-details/2025/Caterpillar-Inc--Maintains-Dividend-3c0eba38e/default.aspx",
    },
    "ENTG": {
        "cusip": "29362U104", "first": "2026-01-28", "next": "2026-04-29",
        "public": "2026-01-14", "cash": 0.10,
        "issuer_url": "https://investor.entegris.com/news/news-details/2026/Entegris-Declares-Quarterly-Cash-Dividend/default.aspx",
    },
    "AMAT": {
        "cusip": "038222105", "first": "2026-02-19", "next": "2026-05-21",
        "public": "2025-12-12", "cash": 0.46,
        "issuer_url": "https://ir.appliedmaterials.com/news-releases/news-release-details/applied-materials-announces-cash-dividend-67",
    },
}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def same(a: pd.Series, b: pd.Series, label: str) -> None:
    x = a.to_numpy(float)
    y = b.to_numpy(float)
    assert np.isfinite(x).all() and np.isfinite(y).all(), label
    assert np.allclose(x, y, rtol=0, atol=1e-7), (label, np.max(np.abs(x - y)))


def main(event_specs: dict[str, dict] | None = None, output_stem: str = "FIRST_FOUR") -> None:
    if event_specs is None:
        event_specs = EVENTS
    paths = {
        "joint_prices": JOINT / "data/test_prices.parquet",
        "old_prices": OLD / "data/test_prices.parquet",
        "calendar": JOINT / "data/calendar.parquet",
        "consumed_events": OLD / "data/consumed_price_events.parquet",
        "event_audit": STAGE / "r4_event_pit/ALL_1094_EVENT_PRIORITY.csv",
        "security_event_identity": STAGE / "r4_event_pit/EVENT_SECURITY_PRIORITY.csv",
        "source_receipts": OLD / "data/PRICE_SOURCE_RECEIPTS.json",
    }
    hashes = {name: {"path": str(path), "sha256": sha(path)} for name, path in paths.items()}
    assert hashes["joint_prices"]["sha256"] == hashes["old_prices"]["sha256"]
    prices = pd.read_parquet(paths["joint_prices"])
    calendar = pd.read_parquet(paths["calendar"])
    consumed = pd.read_parquet(paths["consumed_events"])
    audit = pd.read_csv(paths["event_audit"])
    identity = pd.read_csv(paths["security_event_identity"], dtype={"cusip": str})
    receipts = json.loads(paths["source_receipts"].read_text("utf-8"))
    receipts = {item["original_code"]: item for item in receipts}
    assert not prices.duplicated(["ticker", "trade_date"]).any()
    assert not consumed.loc[consumed.audit_kind.eq("APPLIED_CORPORATE_ACTION")].duplicated(
        ["code", "source_event_date", "event_date"]
    ).any()

    allowed = []
    proof = []
    for ticker, spec in event_specs.items():
        code = f"US.{ticker}"
        first = pd.Timestamp(spec["first"])
        next_day = pd.Timestamp(spec["next"])
        assert pd.Timestamp(spec["public"]) < first < next_day
        one_identity = identity.loc[identity.transport_code.eq(code) & identity.source_event_date.eq(spec["first"])]
        assert len(one_identity) > 0 and set(one_identity.cusip) == {spec["cusip"]}
        assert one_identity.share_event.eq(False).all() and one_identity.factor_b.eq(0).all()
        assert one_identity.total_cash_div.eq(spec["cash"]).all()

        original = audit.loc[audit.code.eq(code) & audit.source_event_date.eq(spec["first"])]
        event = consumed.loc[
            consumed.audit_kind.eq("APPLIED_CORPORATE_ACTION")
            & consumed.code.eq(code)
            & pd.to_datetime(consumed.source_event_date).eq(first)
        ]
        assert len(original) == len(event) == 1, code
        original, event = original.iloc[0], event.iloc[0]
        for item in (original, event):
            assert pd.Timestamp(item.event_date) == first and not bool(item.aligned_to_next_session)
            assert float(item.factor_b) == 0.0 and not bool(item.share_event)
            assert float(item.factor_a) == float(original.factor_a)
        assert float(original.total_cash_div) == spec["cash"]
        assert bool(original.simple_cash_floor_matches_vendor)
        prior_close = float(original.prior_raw_close)
        factor = np.floor(((prior_close - spec["cash"]) / prior_close) * 100000) / 100000
        assert abs(factor - float(original.factor_a)) < 1e-12, (code, factor)
        in_interval = consumed.loc[
            consumed.audit_kind.eq("APPLIED_CORPORATE_ACTION")
            & consumed.code.eq(code)
            & pd.to_datetime(consumed.event_date).between(first, next_day, inclusive="left")
        ]
        next_events = consumed.loc[
            consumed.audit_kind.eq("APPLIED_CORPORATE_ACTION")
            & consumed.code.eq(code)
            & pd.to_datetime(consumed.event_date).ge(next_day)
        ]
        assert len(in_interval) == 1 and len(next_events) > 0
        assert pd.to_datetime(next_events.event_date).min() == next_day

        p = prices.loc[prices.ticker.eq(ticker) & prices.trade_date.ge(first) & prices.trade_date.lt(next_day)].copy()
        sessions = set(calendar.loc[
            calendar.is_test.astype(bool)
            & calendar.trade_date.ge(first)
            & calendar.trade_date.lt(next_day), "trade_date"
        ])
        assert len(p) == len(sessions) and set(p.trade_date) == sessions, code
        assert p.original_transport.eq(code).all() and p.transport_used.eq(code).all()
        assert p.price_coordinate.eq("PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN").all()
        assert p.unresolved_event_on_or_before.all() and p.price_quality_warning.all()
        assert not p.lifecycle_ended.any() and not p.extreme_adjusted_jump.any()
        for field in ["open", "close", "raw_open", "raw_close"]:
            assert np.isfinite(p[field]).all() and p[field].gt(0).all(), (code, field)

        receipt = receipts[code]
        assert receipt["ticker"] == ticker and receipt["transport"] == code
        raw_path = STAGE / "fixed_window_raw" / f"RAW_US_{ticker}_K_DAY_NONE_RTH.parquet"
        raw_sha = sha(raw_path)
        receipt_row = [r for r in receipt["paths"] if Path(r["path"]).name == raw_path.name]
        assert len(receipt_row) == 1 and receipt_row[0]["sha256"] == raw_sha
        raw = pd.read_parquet(raw_path, columns=["code", "trade_date", "open", "close"])
        raw["trade_date"] = pd.to_datetime(raw.trade_date)
        raw = raw.loc[raw.code.eq(code) & raw.trade_date.isin(sessions)]
        assert len(raw) == len(p) and not raw.duplicated("trade_date").any()
        merged = p.merge(raw[["trade_date", "open", "close"]], on="trade_date", validate="one_to_one", suffixes=("", "_source"))
        same(merged.raw_open, merged.open_source, f"{code}:raw_open")
        same(merged.raw_close, merged.close_source, f"{code}:raw_close")

        before = prices.loc[prices.ticker.eq(ticker) & prices.trade_date.lt(first)].tail(1)
        assert len(before) == 1 and not bool(before.price_quality_warning.iloc[0]), code
        before = before.iloc[0]
        assert abs(before.raw_close - prior_close) < 1e-7, code
        assert before.raw_open != before.raw_close, code
        alpha_before = (before.open - before.close) / (before.raw_open - before.raw_close)
        beta_before = before.open - alpha_before * before.raw_open
        alpha_after = alpha_before / factor
        same(p.open, alpha_after * p.raw_open + beta_before, f"{code}:adjusted_open")
        same(p.close, alpha_after * p.raw_close + beta_before, f"{code}:adjusted_close")

        p["open_authorized"] = True
        p["close_authorized"] = True
        p["evidence_id"] = f"FIRST_CASH_{code}_{spec['first']}"
        p["candidate_pool_version"] = "R6_UNCHANGED"
        p["next_unproved_event_exclusive"] = spec["next"]
        p["fixed_raw_sha256"] = raw_sha
        allowed.append(p[["ticker", "trade_date", "open_authorized", "close_authorized", "evidence_id", "open", "close", "candidate_pool_version", "next_unproved_event_exclusive", "fixed_raw_sha256"]])
        proof.append({
            "ticker": ticker, "cusip": spec["cusip"], "first": spec["first"],
            "last_authorized": p.trade_date.max().date().isoformat(),
            "next_unproved_event_exclusive": spec["next"],
            "issuer_public_date": spec["public"], "issuer_url": spec["issuer_url"],
            "issuer_record_date": spec["first"], "issuer_cash_per_common_share": spec["cash"],
            "original_event_factor_a": factor, "original_event_factor_b": 0,
            "prior_raw_close": prior_close, "authorized_open_days": len(p),
            "authorized_close_days": len(p), "fixed_raw_sha256": raw_sha,
            "historical_vendor_receipt_observed": False,
            "issuer_page_bytes_archived": False,
        })
    result = pd.concat(allowed, ignore_index=True).sort_values(["ticker", "trade_date"])
    assert not result.duplicated(["ticker", "trade_date"]).any()
    csv_path = HERE / f"{output_stem}_EVENT_ACCOUNT_PRICE_FIELDS.csv"
    parquet_path = HERE / f"{output_stem}_EVENT_ACCOUNT_PRICE_FIELDS.parquet"
    result.to_csv(csv_path, index=False)
    result.to_parquet(parquet_path, index=False)
    manifest = {
        "status": "ISSUER_PRE_EVENT_PLUS_SAVED_RAW_AND_EXACT_PRICE_RECONSTRUCTION",
        "scope": "EXECUTION_OPEN_AND_VALUATION_CLOSE_FIELDS_ONLY",
        "candidate_pool_version": "R6_UNCHANGED",
        "price_coordinate": "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN",
        "events": proof,
        "total_unique_ticker_dates": len(result),
        "input_sha256": hashes,
        "output_sha256": {csv_path.name: sha(csv_path), parquet_path.name: sha(parquet_path)},
        "model_fit_calls": 0, "preprocessor_fit_calls": 0, "account_replay_calls": 0,
    }
    (HERE / f"{output_stem}_PROOF.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(json.dumps({"rows": len(result), "events": [{"ticker": x["ticker"], "days": x["authorized_open_days"]} for x in proof]}))


if __name__ == "__main__":
    main()
