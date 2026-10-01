"""Prove only V18 BAC 2026-03-09 held-position and sell price fields."""

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
V18 = HERE.parent / "replay/repair_r2_v18_bac_mu_6"
TICKER, CODE, CUSIP = "BAC", "US.BAC", "060505104"
PRE_EVENT, EVENT, DAY = (pd.Timestamp(d) for d in ("2026-03-05", "2026-03-06", "2026-03-09"))
CASH, FACTOR = 0.28, 0.99437
RUNS = [f"joint_mlp_{bps}bps" for bps in (5, 10, 25)]
COORDINATE = "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN"
PRIOR_EVIDENCE_ID = "ROUND2_BAC_20260306_CASH_DIVIDEND_INDEX_UNIT"
EVIDENCE_ID = "ROUND2_BAC_20260309_CASH_SUCCESSOR_INDEX_UNIT"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def one(frame: pd.DataFrame, label: str) -> pd.Series:
    assert len(frame) == 1, (label, len(frame))
    return frame.iloc[0]


def close(actual: float, expected: float, label: str, atol: float = 1e-7) -> None:
    assert np.isfinite(actual) and np.isfinite(expected), label
    assert np.isclose(actual, expected, rtol=0, atol=atol), (label, actual, expected)


def main() -> None:
    paths = {
        "proof_builder": HERE / "build_round2_bac_0309_account_fields.py",
        "previous_0306_proof": HERE / "ROUND2_BAC_0306_PROOF.json",
        "previous_0306_allowlist": HERE / "ROUND2_BAC_0306_EVENT_ACCOUNT_PRICE_FIELDS.parquet",
        "v18_progress": V18 / "PROGRESS.json",
        "joint_prices": JOINT / "data/test_prices.parquet",
        "old_prices": OLD / "data/test_prices.parquet",
        "calendar": JOINT / "data/calendar.parquet",
        "consumed_events": OLD / "data/consumed_price_events.parquet",
        "event_audit": STAGE / "r4_event_pit/ALL_1094_EVENT_PRIORITY.csv",
        "security_identity": STAGE / "r4_event_pit/EVENT_SECURITY_PRIORITY.csv",
        "source_receipts": OLD / "data/PRICE_SOURCE_RECEIPTS.json",
        "fixed_raw": STAGE / "fixed_window_raw/RAW_US_BAC_K_DAY_NONE_RTH.parquet",
        "frozen_account_engine": JOINT / "engine.py",
    }
    for run in RUNS:
        paths[f"v18_{run}_checkpoint"] = V18 / run / "CHECKPOINT.json"
        paths[f"v18_{run}_consumed_approvals"] = V18 / run / "CONSUMED_APPROVALS.csv"
    hashes = {name: {"path": str(path), "sha256": sha(path)} for name, path in paths.items()}
    assert hashes["joint_prices"]["sha256"] == hashes["old_prices"]["sha256"]

    prior_proof = json.loads(paths["previous_0306_proof"].read_text(encoding="utf-8"))
    assert prior_proof["status"] == "EXACT_V13_BAC_HELD_SELL_ACCOUNT_FIELDS_PROVEN"
    assert prior_proof["candidate_pool_version"] == "R6_UNCHANGED"
    assert prior_proof["event"]["cusip"] == CUSIP
    assert prior_proof["event"]["cash_per_common_share"] == CASH
    assert prior_proof["event"]["original_factor_a"] == FACTOR
    assert prior_proof["event"]["issuer_announcement_at"] == "2026-02-03 16:15 Eastern"
    assert prior_proof["event"]["issuer_ex_date"] == "2026-03-06"
    assert prior_proof["output_sha256"][paths["previous_0306_allowlist"].name] == hashes["previous_0306_allowlist"]["sha256"]
    prior_allow = one(pd.read_parquet(paths["previous_0306_allowlist"]), "prior BAC allowlist")
    assert prior_allow.ticker == TICKER and prior_allow.trade_date == EVENT
    assert bool(prior_allow.open_authorized) and bool(prior_allow.close_authorized)
    assert prior_allow.evidence_id == PRIOR_EVIDENCE_ID
    assert prior_allow.fixed_raw_sha256 == hashes["fixed_raw"]["sha256"]

    progress = json.loads(paths["v18_progress"].read_text(encoding="utf-8"))
    assert progress["fit_guard_attempts"] == 0
    progress_rows = {item["run_id"]: item for item in progress["paths"]}
    assert set(RUNS) <= progress_rows.keys()
    expected = {
        (TICKER, "2026-03-09", "open", "held_position_pretrade_nav_or_exit"),
        (TICKER, "2026-03-09", "open", "requested_position_sell"),
        (TICKER, "2026-03-09", "close", "actual_held_position_valuation"),
    }
    needs, holdings = [], {}
    for run in RUNS:
        checkpoint = json.loads(paths[f"v18_{run}_checkpoint"].read_text(encoding="utf-8"))
        for item in (checkpoint, progress_rows[run]):
            assert item["run_id"] == run and item["status"] == "paused_before_uncertified_input"
            assert item["certified_through"] == "2026-03-06" and item["next_date"] == "2026-03-09"
            found = [x for x in item["next_required_inputs"] if x["ticker"] == TICKER]
            assert len(found) == 3
            assert {(x["ticker"], x["date"], x["field"], x["purpose"]) for x in found} == expected
            assert next(x for x in found if x["purpose"] == "held_position_pretrade_nav_or_exit")["pending_signal_date"] == "2026-03-06"
        assert checkpoint["new_predictor_fit_attempts"] == 0
        assert checkpoint["new_preprocessor_fit_attempts"] == 0
        held = checkpoint["holdings"][TICKER]
        assert held["index_units"] > 0 and held["mark_date"] == "2026-03-06"
        assert held["mark_source"] == "close"
        close(float(held["mark"]), float(prior_allow.close), "certified prior close mark")
        approvals = pd.read_csv(paths[f"v18_{run}_consumed_approvals"], dtype=str).fillna("")
        prior_consumed = approvals.loc[approvals.ticker.eq(TICKER) & approvals.trade_date.eq("2026-03-06")]
        assert len(prior_consumed) == 2 and set(prior_consumed.field) == {"open", "close"}
        assert set(prior_consumed.evidence_id) == {PRIOR_EVIDENCE_ID}
        for _, item in prior_consumed.iterrows():
            close(float(item.value), float(prior_allow[item.field]), "consumed prior licensed value")
        needs.extend([{"run_id": run, **x} for x in checkpoint["next_required_inputs"] if x["ticker"] == TICKER])
        holdings[run] = float(held["index_units"])

    calendar = pd.read_parquet(paths["calendar"])
    assert bool(one(calendar.loc[calendar.trade_date.eq(DAY)], "V18 next test date").is_test)
    prices = pd.read_parquet(paths["joint_prices"])
    pre = one(prices.loc[prices.ticker.eq(TICKER) & prices.trade_date.eq(PRE_EVENT)], "pre-event price")
    previous = one(prices.loc[prices.ticker.eq(TICKER) & prices.trade_date.eq(EVENT)], "prior licensed price")
    p = one(prices.loc[prices.ticker.eq(TICKER) & prices.trade_date.eq(DAY)], "V18 requested price")
    assert not bool(pre.price_quality_warning) and not bool(pre.unresolved_event_on_or_before)
    for row in (pre, previous, p):
        assert row.original_transport == row.transport_used == CODE
        assert row.price_coordinate == COORDINATE
        assert not bool(row.lifecycle_ended) and not bool(row.extreme_adjusted_jump)
        for field in ("open", "close", "raw_open", "raw_close", "volume"):
            assert np.isfinite(row[field]) and row[field] > 0
    for row in (previous, p):
        assert bool(row.unresolved_event_on_or_before) and bool(row.price_quality_warning)
    close(float(previous.open), float(prior_allow.open), "prior licensed open unchanged")
    close(float(previous.close), float(prior_allow.close), "prior licensed close unchanged")

    receipts = json.loads(paths["source_receipts"].read_text(encoding="utf-8"))
    receipt = [r for r in receipts if r["ticker"] == TICKER and r["original_code"] == CODE]
    assert len(receipt) == 1 and receipt[0]["transport"] == CODE
    fixed_receipt = [r for r in receipt[0]["paths"] if Path(r["path"]).name == paths["fixed_raw"].name]
    assert len(fixed_receipt) == 1 and fixed_receipt[0]["sha256"] == hashes["fixed_raw"]["sha256"]
    raw = pd.read_parquet(paths["fixed_raw"])
    rpre = one(raw.loc[raw.code.eq(CODE) & raw.trade_date.eq(PRE_EVENT)], "pre-event Raw")
    rprevious = one(raw.loc[raw.code.eq(CODE) & raw.trade_date.eq(EVENT)], "prior licensed Raw")
    r = one(raw.loc[raw.code.eq(CODE) & raw.trade_date.eq(DAY)], "V18 same-source Raw")
    close(float(rprevious.last_close), float(rpre.close), "event-day Raw continuity")
    close(float(r.last_close), float(rprevious.close), "successor-day Raw continuity")
    for adjusted, source in ((previous, rprevious), (p, r)):
        close(float(adjusted.raw_open), float(source.open), "same-source Raw open")
        close(float(adjusted.raw_close), float(source.close), "same-source Raw close")
        close(float(adjusted.volume), float(source.volume), "same-source Raw volume")

    events = pd.read_parquet(paths["consumed_events"])
    applied = events.loc[
        events.code.eq(CODE) & events.audit_kind.eq("APPLIED_CORPORATE_ACTION")
        & pd.to_datetime(events.event_date).between("2026-01-01", DAY)
    ]
    event = one(applied, "only original 2026 BAC event through 2026-03-09")
    audit = pd.read_csv(paths["event_audit"])
    original = one(audit.loc[audit.code.eq(CODE) & audit.source_event_date.eq("2026-03-06")], "R4 event")
    for item in (event, original):
        assert item.code == CODE and item.ticker == TICKER
        assert item.audit_kind == "APPLIED_CORPORATE_ACTION"
        assert pd.Timestamp(item.event_date) == EVENT and pd.Timestamp(item.source_event_date) == EVENT
        assert not bool(item.aligned_to_next_session) and not bool(item.share_event)
        close(float(item.factor_a), FACTOR, "original factor A", atol=1e-12)
        close(float(item.factor_b), 0.0, "original factor B", atol=1e-12)
    assert original.original_code == original.transport_code == CODE
    close(float(original.prior_raw_close), float(rpre.close), "R4 prior Raw close")
    close(float(original.total_cash_div), CASH, "issuer cash dividend")
    assert bool(original.simple_cash_floor_matches_vendor)
    factor = np.floor(((float(rpre.close) - CASH) / float(rpre.close)) * 100000) / 100000
    close(factor, FACTOR, "floor5 original factor", atol=1e-12)
    identity = pd.read_csv(paths["security_identity"], dtype={"cusip": str})
    security = identity.loc[
        identity.original_code.eq(CODE) & identity.transport_code.eq(CODE)
        & identity.source_event_date.eq("2026-03-06")
    ]
    assert set(security.quarter) == {"2025Q4", "2026Q1", "2026Q2"}
    assert set(security.cusip) == {CUSIP} and set(security.title_of_class) == {"COM"}
    assert security.total_cash_div.eq(CASH).all() and security.factor_a.eq(FACTOR).all()
    assert security.factor_b.eq(0).all() and not security.share_event.any()

    assert float(pre.raw_open) != float(pre.raw_close)
    alpha_before = (float(pre.open) - float(pre.close)) / (float(pre.raw_open) - float(pre.raw_close))
    beta_before = float(pre.open) - alpha_before * float(pre.raw_open)
    alpha_after = alpha_before / factor
    close(beta_before, 0.0, "affine beta", atol=1e-8)
    close(alpha_after, float(prior_proof["index_coordinate"]["alpha_after"]), "prior certified affine alpha")
    for adjusted, source in ((previous, rprevious), (p, r)):
        close(float(adjusted.open), alpha_after * float(source.open) + beta_before, "successor index open")
        close(float(adjusted.close), alpha_after * float(source.close) + beta_before, "successor index close")

    out = pd.DataFrame([{
        "ticker": TICKER, "trade_date": DAY, "open": float(p.open), "close": float(p.close),
        "open_authorized": True, "close_authorized": True,
        "evidence_id": EVIDENCE_ID, "candidate_pool_version": "R6_UNCHANGED",
        "fixed_raw_sha256": hashes["fixed_raw"]["sha256"],
    }])
    csv_path = HERE / "ROUND2_BAC_0309_EVENT_ACCOUNT_PRICE_FIELDS.csv"
    parquet_path = HERE / "ROUND2_BAC_0309_EVENT_ACCOUNT_PRICE_FIELDS.parquet"
    out.to_csv(csv_path, index=False)
    out.to_parquet(parquet_path, index=False)
    proof = {
        "status": "EXACT_V18_BAC_FOLLOWON_HELD_POSITION_AND_SELL_FIELDS_PROVEN",
        "authorized_keys": [[TICKER, "2026-03-09", "open"], [TICKER, "2026-03-09", "close"]],
        "excluded_scope": "No BAC date after 2026-03-09, other ticker, or other field is authorized; no sell fill or further replay is asserted.",
        "candidate_pool_version": "R6_UNCHANGED",
        "v18_required_input_rows": needs,
        "v18_previous_certified_holdings_index_units": holdings,
        "previous_0306_evidence_id": PRIOR_EVIDENCE_ID,
        "event": {
            "ticker": TICKER, "original_code": CODE, "transport": CODE,
            "cusip": CUSIP, "class": "COM", "original_applied_event_date": "2026-03-06",
            "issuer_announcement_at": "2026-02-03 16:15 Eastern",
            "issuer_announcement": "https://newsroom.bankofamerica.com/content/newsroom/press-releases/2026/02/bank-of-america-declares-first-quarter-2026-stock-dividends.html",
            "issuer_dividend_table": "https://investor.bankofamerica.com/shareholder-information/dividends",
            "issuer_ex_date": "2026-03-06", "issuer_record_date": "2026-03-06",
            "issuer_payable_date": "2026-03-27", "cash_per_common_share": CASH,
            "original_factor_a": factor, "original_factor_b": 0.0,
            "no_new_2026_applied_event_before_or_on_20260309": True,
        },
        "coordinate": {
            "name": COORDINATE, "alpha_before": alpha_before,
            "beta_before": beta_before, "alpha_after": alpha_after,
            "raw_open": float(r.open), "raw_close": float(r.close), "raw_volume": float(r.volume),
            "authorized_open": float(p.open), "authorized_close": float(p.close),
            "unit": "frozen-account price-index unit, not shareholder total return",
        },
        "historical_vendor_factor_receipt_observed": False,
        "issuer_page_bytes_archived": False,
        "input_sha256": hashes,
        "output_sha256": {csv_path.name: sha(csv_path), parquet_path.name: sha(parquet_path)},
        "model_fit_calls": 0, "preprocessor_fit_calls": 0, "account_replay_calls": 0,
    }
    (HERE / "ROUND2_BAC_0309_PROOF.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"authorized_keys": proof["authorized_keys"], "open": float(p.open), "close": float(p.close)}))


if __name__ == "__main__":
    main()
