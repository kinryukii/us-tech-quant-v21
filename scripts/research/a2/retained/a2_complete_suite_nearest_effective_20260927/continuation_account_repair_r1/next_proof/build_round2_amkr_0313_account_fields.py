"""Prove only V12 AMKR 2026-03-13 held-position and sell fields."""

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
V12 = HERE.parent / "replay/repair_r2_v12_amkr_3"
TICKER, CODE, CUSIP = "AMKR", "US.AMKR", "031652100"
PRE_EVENT = pd.Timestamp("2026-03-11")
EVENT = pd.Timestamp("2026-03-12")
DAY = pd.Timestamp("2026-03-13")
FACTOR, CASH = 0.99809, 0.08352
RUNS = {f"joint_rl_zero_control_{bps}bps" for bps in (5, 10, 25)}
COORDINATE = "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN"
PRIOR_EVIDENCE_ID = "AMKR_20260312_FIRST_CASH_ACCOUNT_FIELD"
EVIDENCE_ID = "ROUND2_AMKR_20260313_CASH_SUCCESSOR_INDEX_UNIT"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def close(actual: float, expected: float, label: str, atol: float = 1e-7) -> None:
    assert np.isfinite(actual) and np.isfinite(expected), label
    assert np.isclose(actual, expected, rtol=0, atol=atol), (label, actual, expected)


def one(frame: pd.DataFrame, label: str) -> pd.Series:
    assert len(frame) == 1, (label, len(frame))
    return frame.iloc[0]


def main() -> None:
    paths = {
        "previous_0312_proof": HERE / "ROUND2_AMKR_PROOF.json",
        "previous_0312_allowlist": HERE / "ROUND2_AMKR_ACCOUNT_PRICE_FIELDS.parquet",
        "joint_prices": JOINT / "data/test_prices.parquet",
        "old_prices": OLD / "data/test_prices.parquet",
        "calendar": JOINT / "data/calendar.parquet",
        "consumed_events": OLD / "data/consumed_price_events.parquet",
        "event_audit": STAGE / "r4_event_pit/ALL_1094_EVENT_PRIORITY.csv",
        "security_identity": STAGE / "r4_event_pit/EVENT_SECURITY_PRIORITY.csv",
        "source_receipts": OLD / "data/PRICE_SOURCE_RECEIPTS.json",
        "fixed_raw": STAGE / "fixed_window_raw/RAW_US_AMKR_K_DAY_NONE_RTH.parquet",
        "frozen_account_engine": JOINT / "engine.py",
    }
    for run in sorted(RUNS):
        paths[f"v12_{run}_checkpoint"] = V12 / run / "CHECKPOINT.json"
        paths[f"v12_{run}_consumed_approvals"] = V12 / run / "CONSUMED_APPROVALS.csv"
    hashes = {name: {"path": str(path), "sha256": sha(path)} for name, path in paths.items()}
    assert hashes["joint_prices"]["sha256"] == hashes["old_prices"]["sha256"]

    prior_proof = json.loads(paths["previous_0312_proof"].read_text("utf-8"))
    assert prior_proof["status"] == "ONE_DAY_HELD_POSITION_AND_REQUESTED_SELL_FIELDS_PROVEN"
    assert prior_proof["date"] == "2026-03-12" and prior_proof["ticker"] == TICKER
    assert prior_proof["cusip"] == CUSIP and prior_proof["issuer_announcement_date"] == "2026-02-19"
    assert prior_proof["issuer_record_date"] == "2026-03-12"
    assert prior_proof["issuer_ex_date"] == "2026-03-12"
    assert prior_proof["issuer_cash_per_common_share"] == CASH
    assert prior_proof["factor_a"] == FACTOR and prior_proof["factor_b"] == 0
    assert prior_proof["candidate_pool_version"] == "R6_UNCHANGED"
    assert prior_proof["output_sha256"][paths["previous_0312_allowlist"].name] == hashes["previous_0312_allowlist"]["sha256"]
    assert pd.Timestamp(prior_proof["issuer_announcement_date"]) < EVENT < DAY
    prior_allow = pd.read_parquet(paths["previous_0312_allowlist"])
    prior_allow = one(prior_allow.loc[prior_allow.ticker.eq(TICKER) & prior_allow.trade_date.eq(EVENT)], "prior allowlist")
    assert bool(prior_allow.open_authorized) and bool(prior_allow.close_authorized)
    assert prior_allow.evidence_id == PRIOR_EVIDENCE_ID
    assert prior_allow.fixed_raw_sha256 == hashes["fixed_raw"]["sha256"]

    needs = []
    holdings = {}
    for run in sorted(RUNS):
        checkpoint = json.loads(paths[f"v12_{run}_checkpoint"].read_text("utf-8"))
        assert checkpoint["run_id"] == run and checkpoint["status"] == "paused_before_uncertified_input"
        assert checkpoint["certified_through"] == "2026-03-12" and checkpoint["next_date"] == "2026-03-13"
        assert checkpoint["new_predictor_fit_attempts"] == 0 and checkpoint["new_preprocessor_fit_attempts"] == 0
        found = checkpoint["next_required_inputs"]
        assert len(found) == 3
        assert {(x["ticker"], x["date"], x["field"], x["purpose"]) for x in found} == {
            (TICKER, "2026-03-13", "open", "held_position_pretrade_nav_or_exit"),
            (TICKER, "2026-03-13", "open", "requested_position_sell"),
            (TICKER, "2026-03-13", "close", "actual_held_position_valuation"),
        }
        held_need = one(pd.DataFrame(found).loc[lambda d: d.purpose.eq("held_position_pretrade_nav_or_exit")], "held open")
        assert held_need.pending_signal_date == "2026-03-12"
        position = checkpoint["holdings"][TICKER]
        assert position["index_units"] > 0 and position["mark_date"] == "2026-03-12"
        assert position["mark_source"] == "close"
        close(float(position["mark"]), float(prior_allow.close), "certified prior close mark")
        approvals = pd.read_csv(paths[f"v12_{run}_consumed_approvals"], dtype=str).fillna("")
        prior_consumed = approvals.loc[approvals.ticker.eq(TICKER) & approvals.trade_date.eq("2026-03-12")]
        assert len(prior_consumed) == 2 and set(prior_consumed.field) == {"open", "close"}
        assert set(prior_consumed.evidence_id) == {PRIOR_EVIDENCE_ID}
        needs.extend([{"run_id": run, **item} for item in found])
        holdings[run] = float(position["index_units"])

    calendar = pd.read_parquet(paths["calendar"])
    assert bool(one(calendar.loc[calendar.trade_date.eq(DAY)], "new calendar day").is_test)
    prices = pd.read_parquet(paths["joint_prices"])
    pre = one(prices.loc[prices.ticker.eq(TICKER) & prices.trade_date.eq(PRE_EVENT)], "pre-event price")
    previous = one(prices.loc[prices.ticker.eq(TICKER) & prices.trade_date.eq(EVENT)], "prior certified price")
    p = one(prices.loc[prices.ticker.eq(TICKER) & prices.trade_date.eq(DAY)], "new account date price")
    assert not bool(pre.price_quality_warning) and not bool(pre.unresolved_event_on_or_before)
    for row in (previous, p):
        assert row.original_transport == CODE and row.transport_used == CODE
        assert row.price_coordinate == COORDINATE
        assert bool(row.unresolved_event_on_or_before) and bool(row.price_quality_warning)
        assert not bool(row.lifecycle_ended) and not bool(row.extreme_adjusted_jump)
        for field in ("open", "close", "raw_open", "raw_close", "volume"):
            assert np.isfinite(row[field]) and row[field] > 0
    close(float(previous.open), float(prior_allow.open), "prior licensed open unchanged")
    close(float(previous.close), float(prior_allow.close), "prior licensed close unchanged")

    receipts = json.loads(paths["source_receipts"].read_text("utf-8"))
    receipt = [r for r in receipts if r["ticker"] == TICKER and r["original_code"] == CODE]
    assert len(receipt) == 1 and receipt[0]["transport"] == CODE
    raw_receipt = [r for r in receipt[0]["paths"] if Path(r["path"]).name == paths["fixed_raw"].name]
    assert len(raw_receipt) == 1 and raw_receipt[0]["sha256"] == hashes["fixed_raw"]["sha256"]
    raw = pd.read_parquet(paths["fixed_raw"])
    rpre = one(raw.loc[raw.code.eq(CODE) & raw.trade_date.eq(PRE_EVENT)], "pre-event same-source Raw")
    rprevious = one(raw.loc[raw.code.eq(CODE) & raw.trade_date.eq(EVENT)], "prior same-source Raw")
    r = one(raw.loc[raw.code.eq(CODE) & raw.trade_date.eq(DAY)], "new same-source Raw")
    close(float(rprevious.last_close), float(rpre.close), "event-day Raw continuity")
    close(float(r.last_close), float(rprevious.close), "new-day Raw continuity")
    for adjusted, source in ((previous, rprevious), (p, r)):
        close(float(adjusted.raw_open), float(source.open), "same-source raw open")
        close(float(adjusted.raw_close), float(source.close), "same-source raw close")
        close(float(adjusted.volume), float(source.volume), "same-source volume")

    events = pd.read_parquet(paths["consumed_events"])
    through_day = events.loc[
        events.code.eq(CODE) & events.audit_kind.eq("APPLIED_CORPORATE_ACTION")
        & pd.to_datetime(events.event_date).between("2026-01-01", DAY)
    ]
    event = one(through_day, "only 2026 event through 2026-03-13")
    audit = pd.read_csv(paths["event_audit"])
    original = one(audit.loc[audit.code.eq(CODE) & audit.source_event_date.eq("2026-03-12")], "original event audit")
    for item in (event, original):
        assert item.code == CODE and item.ticker == TICKER
        assert item.audit_kind == "APPLIED_CORPORATE_ACTION"
        assert pd.Timestamp(item.event_date) == EVENT and pd.Timestamp(item.source_event_date) == EVENT
        assert not bool(item.aligned_to_next_session) and not bool(item.share_event)
        close(float(item.factor_a), FACTOR, "original factor a", atol=1e-12)
        close(float(item.factor_b), 0.0, "original factor b", atol=1e-12)
    assert original.original_code == CODE and original.transport_code == CODE
    close(float(original.prior_raw_close), float(rpre.close), "audited prior Raw close")
    close(float(original.total_cash_div), CASH, "issuer cash amount")
    assert bool(original.simple_cash_floor_matches_vendor)
    factor = np.floor(((float(rpre.close) - CASH) / float(rpre.close)) * 100000) / 100000
    close(factor, FACTOR, "original cash factor formula", atol=1e-12)
    identity = pd.read_csv(paths["security_identity"], dtype={"cusip": str})
    security = identity.loc[
        identity.original_code.eq(CODE) & identity.transport_code.eq(CODE)
        & identity.source_event_date.eq("2026-03-12")
    ]
    assert len(security) > 0 and set(security.cusip) == {CUSIP}
    assert set(security.title_of_class) == {"COM"} and security.total_cash_div.eq(CASH).all()

    assert pre.raw_open != pre.raw_close
    alpha_before = (float(pre.open) - float(pre.close)) / (float(pre.raw_open) - float(pre.raw_close))
    beta_before = float(pre.open) - alpha_before * float(pre.raw_open)
    alpha_after = alpha_before / factor
    close(beta_before, 0.0, "affine beta", atol=1e-8)
    for adjusted, source in ((previous, rprevious), (p, r)):
        close(float(adjusted.open), alpha_after * float(source.open) + beta_before, "successor index open")
        close(float(adjusted.close), alpha_after * float(source.close) + beta_before, "successor index close")

    out = pd.DataFrame([{
        "ticker": TICKER, "trade_date": DAY,
        "open": float(p.open), "close": float(p.close),
        "open_authorized": True, "close_authorized": True,
        "evidence_id": EVIDENCE_ID, "candidate_pool_version": "R6_UNCHANGED",
        "fixed_raw_sha256": hashes["fixed_raw"]["sha256"],
    }])
    csv_path = HERE / "ROUND2_AMKR_0313_EVENT_ACCOUNT_PRICE_FIELDS.csv"
    parquet_path = HERE / "ROUND2_AMKR_0313_EVENT_ACCOUNT_PRICE_FIELDS.parquet"
    out.to_csv(csv_path, index=False)
    out.to_parquet(parquet_path, index=False)
    proof = {
        "status": "EXACT_V12_AMKR_FOLLOWON_ACCOUNT_FIELDS_PROVEN",
        "authorized_keys": [[TICKER, "2026-03-13", "open"], [TICKER, "2026-03-13", "close"]],
        "excluded_scope": "No AMKR date after 2026-03-13 is authorized by this proof.",
        "candidate_pool_version": "R6_UNCHANGED",
        "v12_run_ids": sorted(RUNS), "v12_required_input_rows": needs,
        "v12_previous_certified_holdings_index_units": holdings,
        "previous_0312_evidence_id": PRIOR_EVIDENCE_ID,
        "event": {
            "cusip": CUSIP, "class": "COM", "original_event_date": "2026-03-12",
            "issuer_announcement_date": "2026-02-19",
            "issuer_announcement": "https://ir.amkor.com/news-releases/news-release-details/amkor-technology-declares-quarterly-dividend-10",
            "issuer_hosted_third_party_dividend_table": "https://ir.amkor.com/stock-information/dividends-splits",
            "issuer_cash_per_share": CASH, "issuer_record_date": "2026-03-12",
            "dividend_table_ex_date": "2026-03-12",
            "original_factor_a": factor, "original_factor_b": 0.0,
            "no_additional_consumed_corporate_action_before_or_on_20260313": True,
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
    (HERE / "ROUND2_AMKR_0313_PROOF.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"authorized_keys": proof["authorized_keys"], "open": float(p.open), "close": float(p.close)}))


if __name__ == "__main__":
    main()
