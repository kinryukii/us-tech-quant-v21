"""Prove only GOOG/GOOGL 2026-03-09 fields demanded by V18 MLP accounts."""

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
STAGE = WORKSPACE / "a2_strict_method_retrain_20260926/test2026_stage"
REPLAY = JOINT / "continuation_account_repair_r1/replay/repair_r2_v18_bac_mu_6"
DAY = pd.Timestamp("2026-03-09")
PREVIOUS = pd.Timestamp("2026-03-06")
TICKERS = {
    "GOOG": {"cusip": "02079K107", "class": "CAP STK CL C", "order": "requested_position_sell"},
    "GOOGL": {"cusip": "02079K305", "class": "CAP STK CL A", "order": "requested_target_buy"},
}
RUNS = [f"joint_mlp_{cost}bps" for cost in (5, 10, 25)]
ISSUER_8K = "https://www.sec.gov/Archives/edgar/data/1652044/000165204426000012/googexhibit991q42025.htm"
ISSUER_8K_HEADER = "https://www.sec.gov/Archives/edgar/data/1652044/000165204426000012/0001652044-26-000012-index-headers.html"
ISSUER_10K = "https://www.sec.gov/Archives/edgar/data/1652044/000165204426000018/goog-20251231.htm"
SEC_BOTH_CUSIPS = "https://www.sec.gov/Archives/edgar/data/1653926/000165392625000004/xslForm13F_X02/13F-0630-2025.xml"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def equal(a: float, b: float, label: str, tol: float = 1e-7) -> None:
    assert np.isfinite(a) and np.isfinite(b) and abs(a - b) <= tol, (label, a, b)


def single(frame: pd.DataFrame, label: str) -> pd.Series:
    assert len(frame) == 1, (label, len(frame))
    return frame.iloc[0]


def main() -> None:
    paths = {
        "joint_prices": JOINT / "data/test_prices.parquet",
        "old_prices": OLD / "data/test_prices.parquet",
        "calendar": JOINT / "data/calendar.parquet",
        "consumed_events": OLD / "data/consumed_price_events.parquet",
        "event_audit": STAGE / "r4_event_pit/ALL_1094_EVENT_PRIORITY.csv",
        "identity": STAGE / "r4_event_pit/EVENT_SECURITY_PRIORITY.csv",
        "initial_state": STAGE / "identity_feature_application_r1/CONSUMED_2026_INITIAL_ADJUSTMENT_STATE.csv",
        "raw_receipts": OLD / "data/PRICE_SOURCE_RECEIPTS.json",
        "v18_complete": REPLAY / "COMPLETE.json",
    }
    for ticker in TICKERS:
        paths[f"fixed_raw_{ticker}"] = STAGE / f"fixed_window_raw/RAW_US_{ticker}_K_DAY_NONE_RTH.parquet"
    for run in RUNS:
        paths[f"checkpoint_{run}"] = REPLAY / run / "CHECKPOINT.json"
        paths[f"consumed_approvals_{run}"] = REPLAY / run / "CONSUMED_APPROVALS.csv"
    hashes = {name: {"path": str(path), "sha256": sha(path)} for name, path in paths.items()}
    assert hashes["joint_prices"]["sha256"] == hashes["old_prices"]["sha256"]
    assert hashes["fixed_raw_GOOG"]["sha256"] != hashes["fixed_raw_GOOGL"]["sha256"]

    prices = pd.read_parquet(paths["joint_prices"])
    calendar = pd.read_parquet(paths["calendar"])
    assert bool(single(calendar.loc[calendar.trade_date.eq(DAY)], "test calendar").is_test)
    events = pd.read_parquet(paths["consumed_events"])
    audit = pd.read_csv(paths["event_audit"])
    identity = pd.read_csv(paths["identity"], dtype={"cusip": str})
    initial = pd.read_csv(paths["initial_state"])
    receipts = json.loads(paths["raw_receipts"].read_text(encoding="utf-8"))
    checkpoint_demands = []

    for run in RUNS:
        cp = json.loads(paths[f"checkpoint_{run}"].read_text(encoding="utf-8"))
        assert cp["run_id"] == run and cp["status"] == "paused_before_uncertified_input"
        assert cp["certified_through"] == "2026-03-06" and cp["next_date"] == "2026-03-09"
        assert cp["pending_recomputed_by_frozen_policy"]["signal_date"] == "2026-03-06"
        consumed = pd.read_csv(paths[f"consumed_approvals_{run}"])
        assert not consumed.ticker.isin(TICKERS).any(), (run, "unexpected prior Alphabet approval")
        run_demands = {}
        for ticker, detail in TICKERS.items():
            wanted = [
                {"ticker": ticker, "date": "2026-03-09", "field": "open",
                 "purpose": "held_position_pretrade_nav_or_exit", "pending_signal_date": "2026-03-06"},
                {"ticker": ticker, "date": "2026-03-09", "field": "close",
                 "purpose": "actual_held_position_valuation"},
                {"ticker": ticker, "date": "2026-03-09", "field": "open",
                 "purpose": detail["order"]},
            ]
            actual = [row for row in cp["next_required_inputs"] if row["ticker"] == ticker]
            assert actual == wanted, (run, ticker, actual)
            holding = cp["holdings"][ticker]
            prior = single(prices.loc[prices.ticker.eq(ticker) & prices.trade_date.eq(PREVIOUS)],
                           f"{ticker} 03-06 prior")
            assert not bool(prior.price_quality_warning) and not bool(prior.unresolved_event_on_or_before)
            assert float(holding["index_units"]) > 0
            assert holding["mark_date"] == "2026-03-06" and holding["mark_source"] == "close"
            equal(float(holding["mark"]), float(prior.close), f"{run} {ticker} prior held mark")
            assert cp["pending_recomputed_by_frozen_policy"]["targets_from_new_frozen_policy"][ticker] > 0
            run_demands[ticker] = {"held_index_units": float(holding["index_units"]),
                                   "prior_mark": float(holding["mark"]),
                                   "requested_order": detail["order"], "needs": wanted}
        checkpoint_demands.append({"run_id": run, "tickers": run_demands})

    rows = []
    event_proof = {}
    for ticker, detail in TICKERS.items():
        code = f"US.{ticker}"
        now = single(prices.loc[prices.ticker.eq(ticker) & prices.trade_date.eq(DAY)], f"{ticker} 03-09")
        prior = single(prices.loc[prices.ticker.eq(ticker) & prices.trade_date.eq(PREVIOUS)], f"{ticker} 03-06")
        assert now.original_transport == now.transport_used == prior.original_transport == prior.transport_used == code
        assert now.price_coordinate == prior.price_coordinate == "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN"
        assert bool(now.price_quality_warning) and bool(now.unresolved_event_on_or_before)
        assert not bool(now.lifecycle_ended) and not bool(now.extreme_adjusted_jump)
        assert all(np.isfinite(float(now[field])) and float(now[field]) > 0
                   for field in ("open", "close", "raw_open", "raw_close", "volume"))

        e_all = events.loc[events.audit_kind.eq("APPLIED_CORPORATE_ACTION") & events.code.eq(code)]
        e_pre = e_all.loc[pd.to_datetime(e_all.event_date).between("2026-01-01", "2026-03-09")]
        e = single(e_pre, f"{ticker} first 2026 consumed event")
        a = single(audit.loc[audit.code.eq(code) & audit.source_event_date.eq("2026-03-09")],
                   f"{ticker} original event audit")
        for item in (e, a):
            assert pd.Timestamp(item.source_event_date) == DAY
            assert pd.Timestamp(item.event_date) == DAY and not bool(item.aligned_to_next_session)
            equal(float(item.factor_a), 0.99929, f"{ticker} original event A")
            assert float(item.factor_b) == 0 and not bool(item.share_event)
        assert a.original_code == a.transport_code == code
        equal(float(a.total_cash_div), 0.21, f"{ticker} original cash")
        equal(float(a.prior_raw_close), float(prior.raw_close), f"{ticker} prior raw close")
        assert bool(a.simple_cash_floor_matches_vendor)
        factor = np.floor((1 - 0.21 / float(prior.raw_close)) * 100000) / 100000
        equal(factor, 0.99929, f"{ticker} cash floor5 factor", 1e-12)

        ids = identity.loc[identity.transport_code.eq(code) & identity.source_event_date.eq("2026-03-09")]
        assert len(ids) == 3 and set(ids.cusip) == {detail["cusip"]}
        assert set(ids.title_of_class) == {detail["class"]} and set(ids.original_code) == {code}
        assert set(ids.quarter) == {"2025Q4", "2026Q1", "2026Q2"}
        assert all(np.isclose(ids.per_cash_div.astype(float), 0.21))

        receipt = [r for r in receipts if r["original_code"] == code]
        assert len(receipt) == 1 and receipt[0]["ticker"] == ticker and receipt[0]["transport"] == code
        matching_path = [r for r in receipt[0]["paths"]
                         if Path(r["path"]).name == paths[f"fixed_raw_{ticker}"].name]
        assert len(matching_path) == 1
        assert matching_path[0]["sha256"] == hashes[f"fixed_raw_{ticker}"]["sha256"]
        raw = pd.read_parquet(paths[f"fixed_raw_{ticker}"],
                              columns=["code", "trade_date", "open", "close", "volume", "last_close"])
        raw.trade_date = pd.to_datetime(raw.trade_date)
        r = single(raw.loc[raw.code.eq(code) & raw.trade_date.eq(DAY)], f"{ticker} fixed raw event day")
        r_prior = single(raw.loc[raw.code.eq(code) & raw.trade_date.eq(PREVIOUS)], f"{ticker} fixed raw prior")
        equal(float(r.last_close), float(r_prior.close), f"{ticker} raw continuity", 1e-12)
        for field in ("open", "close"):
            equal(float(now[f"raw_{field}"]), float(r[field]), f"{ticker} same-source {field}", 1e-12)
            equal(float(prior[f"raw_{field}"]), float(r_prior[field]), f"{ticker} prior same-source {field}", 1e-12)
        equal(float(now.volume) * 20, float(r.volume), f"{ticker} volume coordinate")

        state = single(initial.loc[initial.moomoo_transport_code.eq(code)], f"{ticker} initial state")
        alpha_before = float(state.initial_alpha_2026_01_02)
        beta_before = float(state.initial_beta_2026_01_02)
        assert alpha_before > 0 and beta_before == 0 and int(state.consumed_prior_events) == 8
        for field in ("open", "close"):
            equal(float(prior[field]), alpha_before * float(prior[f"raw_{field}"]) + beta_before,
                  f"{ticker} unflagged prior affine {field}")
            equal(float(now[field]), alpha_before / factor * float(now[f"raw_{field}"]) + beta_before,
                  f"{ticker} original event-day affine {field}")

        rows.append({
            "ticker": ticker, "trade_date": DAY, "open": float(now.open), "close": float(now.close),
            "open_authorized": True, "close_authorized": True,
            "open_purpose": f"held_position_pretrade_nav_or_exit_and_{detail['order']}",
            "close_purpose": "actual_held_position_valuation_after_frozen_orders",
            "evidence_id": f"ROUND2_{ticker}_20260309_CASH_DIVIDEND_INDEX_UNIT",
            "candidate_pool_version": "R6_UNCHANGED",
            "fixed_raw_sha256": hashes[f"fixed_raw_{ticker}"]["sha256"],
        })
        event_proof[ticker] = {
            "cusip": detail["cusip"], "class": detail["class"], "original_transport": code,
            "original_event_date": "2026-03-09", "original_factor_a": float(e.factor_a),
            "original_factor_b": float(e.factor_b), "cash_per_class_share": 0.21,
            "prior_raw_close": float(prior.raw_close), "floor5_factor_from_own_raw_close": float(factor),
            "initial_alpha": alpha_before, "initial_beta": beta_before,
            "raw_event_open": float(r.open), "raw_event_close": float(r.close),
            "raw_event_volume": float(r.volume),
            "adjusted_index_open": float(now.open), "adjusted_index_close": float(now.close),
            "prior_unflagged_index_close": float(prior.close),
        }

    output = pd.DataFrame(rows)
    assert len(output) == 2 and set(output.ticker) == set(TICKERS)
    assert output.trade_date.nunique() == 1 and output.trade_date.iloc[0] == DAY
    csv_path = HERE / "ROUND2_ALPHABET_0309_ACCOUNT_PRICE_FIELDS.csv"
    parquet_path = HERE / "ROUND2_ALPHABET_0309_ACCOUNT_PRICE_FIELDS.parquet"
    proof_path = HERE / "ROUND2_ALPHABET_0309_PROOF.json"
    assert not any(path.exists() for path in (csv_path, parquet_path, proof_path))
    output.to_csv(csv_path, index=False)
    output.to_parquet(parquet_path, index=False)
    proof = {
        "status": "TWO_CLASS_ONE_DAY_HELD_POSITION_FIELDS_PROVEN",
        "scope": "ONLY_GOOG_AND_GOOGL_2026_03_09_V18_MLP_ACTUAL_ACCOUNT_OPEN_CLOSE",
        "issuer_public_evidence": {
            "announcement": "Alphabet 2025 Q4 results, SEC 8-K Exhibit 99.1",
            "sec_accepted": "2026-02-04 16:01:37 ET", "url": ISSUER_8K,
            "sec_header_url": ISSUER_8K_HEADER, "record_date": "2026-03-09",
            "payment_date": "2026-03-16", "cash_per_share": 0.21,
            "applicable_classes": ["Class A", "Class B", "Class C"],
            "issuer_10k_ticker_class_url": ISSUER_10K,
            "both_class_cusips_sec_source": SEC_BOTH_CUSIPS,
            "note": "Issuer record date is not treated as independent proof of US ex-date; original applied event provides the account date.",
        },
        "separate_security_event_and_coordinate_checks": event_proof,
        "actual_checkpoint_demands": checkpoint_demands,
        "price_coordinate": "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN",
        "candidate_pool_version": "R6_UNCHANGED",
        "historical_vendor_pit_receipt_observed": False,
        "source_sha256": hashes,
        "output_sha256": {csv_path.name: sha(csv_path), parquet_path.name: sha(parquet_path)},
        "model_fit_calls": 0, "preprocessor_fit_calls": 0, "account_replay_calls": 0,
    }
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": proof["status"], "authorized_ticker_dates": len(output),
                      "run_count": len(checkpoint_demands),
                      "fields": {row["ticker"]: {"open": row["open"], "close": row["close"]}
                                 for row in rows}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
