"""Authorize only actually demanded OR/RRX 2026-04-01 account price fields."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
JOINT = ROOT / "a2_complete_suite_nearest_effective_20260927"
OLD = ROOT / "a2_complete_suite_20260927"
STAGE = ROOT / "a2_strict_method_retrain_20260926/test2026_stage"
REPLAY = JOINT / "continuation_account_repair_r1/replay/repair_r2_v7_early_or_rrx_15"
PRIOR = HERE / "ROUND2_OR_RRX_PROOF.json"
PRIOR_FIELDS = HERE / "ROUND2_OR_RRX_EVENT_ACCOUNT_PRICE_FIELDS.csv"
SPECS = {"OR": ("68390D106", 0.99843), "RRX": ("758750103", 0.99803)}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def one(frame: pd.DataFrame, label: str) -> pd.Series:
    assert len(frame) == 1, (label, len(frame))
    return frame.iloc[0]


def main() -> None:
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    assert prior["status"] == "CURRENT_2026_03_31_OR_RRX_FIELDS_PROVEN"
    assert prior["total_unique_ticker_dates"] == 2
    assert prior["candidate_pool_version"] == "R6_UNCHANGED"
    for item in prior["input_sha256"].values():
        assert sha(Path(item["path"])) == item["sha256"]
    assert sha(PRIOR_FIELDS) == prior["output_sha256"][PRIOR_FIELDS.name]
    prior_rows = pd.read_csv(PRIOR_FIELDS)
    assert len(prior_rows) == 2 and set(prior_rows.ticker) == set(SPECS)
    assert prior_rows.open_authorized.all() and prior_rows.close_authorized.all()
    assert prior_rows.trade_date.eq("2026-03-31").all()
    assert prior_rows.next_unproved_event_exclusive.eq("2026-06-30").all()

    prices_path = JOINT / "data/test_prices.parquet"
    events_path = OLD / "data/consumed_price_events.parquet"
    identity_path = STAGE / "r4_event_pit/EVENT_SECURITY_PRIORITY.csv"
    initial_path = STAGE / "identity_feature_application_r1/CONSUMED_2026_INITIAL_ADJUSTMENT_STATE.csv"
    receipts_path = OLD / "data/PRICE_SOURCE_RECEIPTS.json"
    prices = pd.read_parquet(prices_path)
    events = pd.read_parquet(events_path)
    identity = pd.read_csv(identity_path, dtype={"cusip": str})
    initial = pd.read_csv(initial_path)
    receipt = {r["original_code"]: r for r in json.loads(receipts_path.read_text(encoding="utf-8"))}
    checked = []
    approved = []
    for ticker, (cusip, factor) in SPECS.items():
        code = f"US.{ticker}"
        spec = next(x for x in prior["events"] if x["ticker"] == ticker)
        assert spec["cusip"] == cusip and float(spec["original_event_factor_a"]) == factor
        assert spec["first"] == "2026-03-31" and spec["next_unproved_event_exclusive"] == "2026-06-30"
        assert spec["issuer_public_date"] < "2026-03-31"
        id_rows = identity.loc[identity.transport_code.eq(code) & identity.source_event_date.eq("2026-03-31")]
        assert len(id_rows) >= 1 and set(id_rows.cusip) == {cusip}
        assert id_rows.share_event.eq(False).all() and id_rows.factor_a.eq(factor).all()
        action = events.loc[
            events.audit_kind.eq("APPLIED_CORPORATE_ACTION")
            & events.code.eq(code)
        ].copy()
        action["event_date"] = pd.to_datetime(action.event_date)
        first = one(action.loc[action.event_date.eq("2026-03-31")], f"{code} first event")
        assert first.source_event_date == pd.Timestamp("2026-03-31")
        assert not bool(first.aligned_to_next_session)
        assert float(first.factor_a) == factor and float(first.factor_b) == 0
        assert not action.event_date.between("2026-03-31", "2026-04-01", inclusive="right").any()
        assert action.loc[action.event_date.gt("2026-03-31"), "event_date"].min() == pd.Timestamp("2026-06-30")

        state = one(initial.loc[initial.moomoo_transport_code.eq(code)], f"{code} initial state")
        alpha_before = float(state.initial_alpha_2026_01_02)
        beta_before = float(state.initial_beta_2026_01_02)
        assert alpha_before > 0 and np.isfinite(alpha_before) and np.isfinite(beta_before)
        assert not action.event_date.between("2026-01-02", "2026-03-30").any()
        p30 = one(prices.loc[prices.ticker.eq(ticker) & prices.trade_date.eq("2026-03-30")], "03-30 price")
        p31 = one(prices.loc[prices.ticker.eq(ticker) & prices.trade_date.eq("2026-03-31")], "03-31 price")
        p01 = one(prices.loc[prices.ticker.eq(ticker) & prices.trade_date.eq("2026-04-01")], "04-01 price")
        assert not bool(p30.price_quality_warning)
        assert np.isclose(p30.open, alpha_before * p30.raw_open + beta_before, atol=1e-7, rtol=0)
        assert np.isclose(p30.close, alpha_before * p30.raw_close + beta_before, atol=1e-7, rtol=0)
        assert np.isclose(p30.raw_close, float(spec["prior_raw_close"]), atol=1e-7, rtol=0)
        assert np.isclose(p31.open, float(prior_rows.loc[prior_rows.ticker.eq(ticker), "open"].iloc[0]), atol=1e-7, rtol=0)
        assert np.isclose(p31.close, float(prior_rows.loc[prior_rows.ticker.eq(ticker), "close"].iloc[0]), atol=1e-7, rtol=0)
        assert p01.original_transport == code and p01.transport_used == code
        assert p01.price_coordinate == "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN"
        assert bool(p01.unresolved_event_on_or_before) and bool(p01.price_quality_warning)
        assert not bool(p01.lifecycle_ended) and not bool(p01.extreme_adjusted_jump)
        for field in ("open", "close", "raw_open", "raw_close", "volume"):
            assert np.isfinite(float(p01[field])) and float(p01[field]) > 0

        raw_path = STAGE / f"fixed_window_raw/RAW_US_{ticker}_K_DAY_NONE_RTH.parquet"
        raw_sha = sha(raw_path)
        assert raw_sha == spec["fixed_raw_sha256"]
        rec = receipt[code]
        assert rec["ticker"] == ticker and rec["transport"] == code
        matches = [x for x in rec["paths"] if Path(x["path"]).name == raw_path.name]
        assert len(matches) == 1 and matches[0]["sha256"] == raw_sha
        raw = pd.read_parquet(raw_path, columns=["code", "trade_date", "open", "close"])
        raw["trade_date"] = pd.to_datetime(raw.trade_date)
        raw01 = one(raw.loc[raw.code.eq(code) & raw.trade_date.eq("2026-04-01")], f"{code} Raw")
        assert np.isclose(p01.raw_open, raw01.open, atol=1e-7, rtol=0)
        assert np.isclose(p01.raw_close, raw01.close, atol=1e-7, rtol=0)
        alpha_after = alpha_before / factor
        assert np.isclose(p01.open, alpha_after * raw01.open + beta_before, atol=1e-7, rtol=0)
        assert np.isclose(p01.close, alpha_after * raw01.close + beta_before, atol=1e-7, rtol=0)
        evidence_id = f"ROUND2_{code}_2026-03-31_EVENT_TO_2026-04-01_ACCOUNT_FIELDS"
        approved.append({
            "ticker": ticker, "trade_date": "2026-04-01", "open_authorized": True,
            "close_authorized": True, "evidence_id": evidence_id,
            "open": float(p01.open), "close": float(p01.close),
            "candidate_pool_version": "R6_UNCHANGED", "next_unproved_event_exclusive": "2026-06-30",
            "fixed_raw_sha256": raw_sha,
        })
        checked.append({
            "ticker": ticker, "cusip": cusip, "raw_open": float(raw01.open),
            "raw_close": float(raw01.close), "saved_open": float(p01.open), "saved_close": float(p01.close),
            "initial_alpha": alpha_before, "initial_beta": beta_before, "event_factor_a": factor,
            "alpha_after_event": alpha_after, "next_event_exclusive": "2026-06-30",
            "raw_path": str(raw_path), "raw_sha256": raw_sha,
        })

    checkpoint_receipts = []
    for cost in (5, 10, 25):
        path = REPLAY / f"joint_logistic_{cost}bps/CHECKPOINT.json"
        cp = json.loads(path.read_text(encoding="utf-8"))
        assert cp["certified_through"] == "2026-03-31" and cp["next_date"] == "2026-04-01"
        needs = [x for x in cp["next_required_inputs"] if x["ticker"] in SPECS]
        assert {(x["ticker"], x["field"]) for x in needs} == {
            (ticker, field) for ticker in SPECS for field in ("open", "close")
        }
        assert all(x["date"] == "2026-04-01" for x in needs)
        assert {x["purpose"] for x in needs} == {
            "held_position_pretrade_nav_or_exit", "requested_position_sell", "actual_held_position_valuation"
        }
        checkpoint_receipts.append({
            "run_id": cp["run_id"], "path": str(path), "sha256": sha(path),
            "certified_through": cp["certified_through"],
            "actual_or_rrx_next_input_purposes": sorted({x["purpose"] for x in needs}),
            "holdings_index_units": {ticker: float(cp["holdings"][ticker]["index_units"]) for ticker in SPECS},
        })

    out = pd.DataFrame(approved).sort_values(["ticker", "trade_date"])
    assert len(out) == 2 and not out.duplicated(["ticker", "trade_date"]).any()
    csv_path = HERE / "ROUND2_OR_RRX_0401_ACCOUNT_PRICE_FIELDS.csv"
    parquet_path = HERE / "ROUND2_OR_RRX_0401_ACCOUNT_PRICE_FIELDS.parquet"
    out.to_csv(csv_path, index=False)
    out.to_parquet(parquet_path, index=False)
    manifest = {
        "status": "CURRENT_2026_04_01_OR_RRX_FIELDS_PROVEN",
        "scope": "ONLY_2026_04_01_LOGISTIC_EXECUTION_OPEN_AND_HELD_VALUATION_CLOSE",
        "candidate_pool_version": "R6_UNCHANGED",
        "price_coordinate": "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN",
        "derived_from_prior_proof": {"path": str(PRIOR), "sha256": sha(PRIOR),
                                     "prior_approved_csv_sha256": sha(PRIOR_FIELDS)},
        "checked": checked, "actual_checkpoint_demands": checkpoint_receipts,
        "approved_unique_ticker_dates": 2, "approved_open_fields": 2, "approved_close_fields": 2,
        "input_sha256": {str(path): sha(path) for path in (prices_path, events_path, identity_path, initial_path, receipts_path)},
        "output_sha256": {csv_path.name: sha(csv_path), parquet_path.name: sha(parquet_path)},
        "model_fit_calls": 0, "preprocessor_fit_calls": 0, "account_replay_calls": 0,
    }
    json_path = HERE / "ROUND2_OR_RRX_0401_PROOF.json"
    json_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "rows": len(out),
                      "csv_sha256": manifest["output_sha256"][csv_path.name]}))


if __name__ == "__main__":
    main()
