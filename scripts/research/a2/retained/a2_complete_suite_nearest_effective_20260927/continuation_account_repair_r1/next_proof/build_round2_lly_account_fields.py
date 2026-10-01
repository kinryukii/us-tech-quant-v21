"""Prove only LLY's 2026-02-13 frozen-account open and close fields."""

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
V7 = HERE.parent / "replay/repair_r2_v7_early_or_rrx_15"
DAY = pd.Timestamp("2026-02-13")
PREVIOUS = pd.Timestamp("2026-02-12")
TICKER = "LLY"
CODE = "US.LLY"
CUSIP = "532457108"
CASH = 1.73
COORDINATE = "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN"
EVIDENCE_ID = "ROUND2_LLY_20260213_CASH_DIVIDEND_INDEX_UNIT"


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
        "v7_next_required_inputs": V7 / "NEXT_REQUIRED_INPUTS.csv",
        "dynamic_queue": HERE.parent / "DYNAMIC_NEXT_INPUT_QUEUE.csv",
        "blocked_buy_queue": HERE.parent / "queue/KNOWN_BLOCKED_BUY_DEMAND.csv",
        "joint_prices": JOINT / "data/test_prices.parquet",
        "old_prices": OLD / "data/test_prices.parquet",
        "calendar": JOINT / "data/calendar.parquet",
        "consumed_events": OLD / "data/consumed_price_events.parquet",
        "event_audit": STAGE / "r4_event_pit/ALL_1094_EVENT_PRIORITY.csv",
        "security_identity": STAGE / "r4_event_pit/EVENT_SECURITY_PRIORITY.csv",
        "source_receipts": OLD / "data/PRICE_SOURCE_RECEIPTS.json",
        "fixed_raw": STAGE / "fixed_window_raw/RAW_US_LLY_K_DAY_NONE_RTH.parquet",
        "frozen_account_engine": JOINT / "engine.py",
    }
    hashes = {name: {"path": str(path), "sha256": sha(path)} for name, path in paths.items()}
    assert hashes["joint_prices"]["sha256"] == hashes["old_prices"]["sha256"]

    expected_runs = {f"joint_mlp_{bps}bps" for bps in (5, 10, 25)}
    v7 = pd.read_csv(paths["v7_next_required_inputs"], dtype=str).fillna("")
    needed = v7.loc[v7.ticker.eq(TICKER) & v7.date.eq("2026-02-13")]
    expected_purposes = {
        (run, field, purpose)
        for run in expected_runs
        for field, purpose in (
            ("open", "held_position_pretrade_nav_or_exit"),
            ("open", "requested_target_buy"),
            ("close", "actual_held_position_valuation"),
        )
    }
    assert len(needed) == 9
    assert set(zip(needed.run_id, needed.field, needed.purpose)) == expected_purposes
    assert not needed.duplicated(["run_id", "ticker", "date", "field", "purpose"]).any()
    assert needed.loc[needed.purpose.eq("held_position_pretrade_nav_or_exit"), "pending_signal_date"].eq("2026-02-12").all()

    # The static queue predates V7: it records the old blocked buy open only.
    queue = pd.read_csv(paths["dynamic_queue"], dtype=str).fillna("")
    old_demand = one(queue.loc[queue.ticker.eq(TICKER) & queue.date.eq("2026-02-13")], "static dynamic queue")
    assert old_demand.field == "open" and old_demand.historical_initial_or_blocked_need == "True"
    assert old_demand.pending_signal_dates == "2026-02-12"
    assert set(old_demand.historical_run_ids.split("|")) == expected_runs
    blocked = pd.read_csv(paths["blocked_buy_queue"], dtype=str).fillna("")
    blocked = one(blocked.loc[blocked.ticker.eq(TICKER) & blocked.execution_date.eq("2026-02-13")], "old blocked buy")
    assert blocked.signal_date == "2026-02-12" and blocked.old_blocked_buy_path_count == "3"
    assert set(blocked.old_blocked_buy_run_ids.split("|")) == expected_runs
    assert "qualified_execution_open" in blocked.needed_field
    assert blocked.price_quality_warning == "True" and blocked.unresolved_event_on_or_before == "True"
    assert blocked.lifecycle_ended == "False" and blocked.extreme_adjusted_jump == "False"

    calendar = pd.read_parquet(paths["calendar"])
    assert bool(one(calendar.loc[calendar.trade_date.eq(DAY)], "calendar session").is_test)
    prices = pd.read_parquet(paths["joint_prices"])
    p0 = one(prices.loc[prices.ticker.eq(TICKER) & prices.trade_date.eq(PREVIOUS)], "prior price")
    p1 = one(prices.loc[prices.ticker.eq(TICKER) & prices.trade_date.eq(DAY)], "ex-date price")
    for row in (p0, p1):
        assert row.original_transport == CODE and row.transport_used == CODE
        assert row.price_coordinate == COORDINATE
        for field in ("open", "close", "raw_open", "raw_close", "volume"):
            assert np.isfinite(row[field]) and row[field] > 0, field
        assert not bool(row.lifecycle_ended) and not bool(row.extreme_adjusted_jump)
    assert not bool(p0.unresolved_event_on_or_before) and not bool(p0.price_quality_warning)
    assert bool(p1.unresolved_event_on_or_before) and bool(p1.price_quality_warning)
    close(float(blocked.open), float(p1.open), "old blocked execution open")
    close(float(blocked.close), float(p1.close), "old conditional close")

    receipts = json.loads(paths["source_receipts"].read_text("utf-8"))
    receipt = [r for r in receipts if r["ticker"] == TICKER and r["original_code"] == CODE]
    assert len(receipt) == 1 and receipt[0]["transport"] == CODE
    raw_receipt = [r for r in receipt[0]["paths"] if Path(r["path"]).name == paths["fixed_raw"].name]
    assert len(raw_receipt) == 1 and raw_receipt[0]["sha256"] == hashes["fixed_raw"]["sha256"]
    raw = pd.read_parquet(paths["fixed_raw"])
    r0 = one(raw.loc[raw.code.eq(CODE) & raw.trade_date.eq(PREVIOUS)], "prior same-source Raw")
    r1 = one(raw.loc[raw.code.eq(CODE) & raw.trade_date.eq(DAY)], "ex-date same-source Raw")
    for adjusted, source in ((p0, r0), (p1, r1)):
        close(float(adjusted.raw_open), float(source.open), "same-source Raw open")
        close(float(adjusted.raw_close), float(source.close), "same-source Raw close")
        close(float(adjusted.volume), float(source.volume), "same-source volume")
    close(float(r1.last_close), float(r0.close), "Raw previous close")

    events = pd.read_parquet(paths["consumed_events"])
    event = one(events.loc[
        events.code.eq(CODE)
        & events.audit_kind.eq("APPLIED_CORPORATE_ACTION")
        & pd.to_datetime(events.event_date).between("2026-01-01", DAY)
    ], "consumed LLY event through day")
    audit = pd.read_csv(paths["event_audit"])
    original = one(audit.loc[audit.code.eq(CODE) & audit.source_event_date.eq("2026-02-13")], "original event")
    for item in (event, original):
        assert item.audit_kind == "APPLIED_CORPORATE_ACTION"
        assert item.code == CODE and item.ticker == TICKER
        assert pd.Timestamp(item.event_date) == DAY and pd.Timestamp(item.source_event_date) == DAY
        assert not bool(item.aligned_to_next_session) and not bool(item.share_event)
        close(float(item.factor_b), 0.0, "no additive factor")
    assert original.original_code == CODE and original.transport_code == CODE
    close(float(original.prior_raw_close), float(r0.close), "audited prior Raw close")
    close(float(original.total_cash_div), CASH, "audited cash dividend")
    assert bool(original.simple_cash_floor_matches_vendor)
    factor = np.floor(((float(r0.close) - CASH) / float(r0.close)) * 100000) / 100000
    close(float(original.factor_a), factor, "original five-place factor", atol=1e-12)
    close(float(event.factor_a), factor, "consumed five-place factor", atol=1e-12)
    identity = pd.read_csv(paths["security_identity"], dtype={"cusip": str})
    security = identity.loc[identity.original_code.eq(CODE) & identity.transport_code.eq(CODE) & identity.source_event_date.eq("2026-02-13")]
    assert set(security.quarter) == {"2025Q3", "2025Q4", "2026Q1", "2026Q2"}
    assert set(security.cusip) == {CUSIP} and set(security.title_of_class) == {"COM"}
    assert security.total_cash_div.eq(CASH).all() and security.factor_a.eq(factor).all()
    assert security.factor_b.eq(0).all() and not security.share_event.any()

    assert p0.raw_open != p0.raw_close
    alpha_before = (float(p0.open) - float(p0.close)) / (float(p0.raw_open) - float(p0.raw_close))
    beta_before = float(p0.open) - alpha_before * float(p0.raw_open)
    alpha_after = alpha_before / factor
    close(beta_before, 0.0, "pre-event affine beta", atol=1e-8)
    close(float(p1.open), alpha_after * float(r1.open) + beta_before, "index open")
    close(float(p1.close), alpha_after * float(r1.close) + beta_before, "index close")

    out = pd.DataFrame([{
        "ticker": TICKER,
        "trade_date": DAY,
        "open": float(p1.open),
        "close": float(p1.close),
        "open_authorized": True,
        "close_authorized": True,
        "evidence_id": EVIDENCE_ID,
        "candidate_pool_version": "R6_UNCHANGED",
        "fixed_raw_sha256": hashes["fixed_raw"]["sha256"],
    }])
    csv_path = HERE / "ROUND2_LLY_EVENT_ACCOUNT_PRICE_FIELDS.csv"
    parquet_path = HERE / "ROUND2_LLY_EVENT_ACCOUNT_PRICE_FIELDS.parquet"
    out.to_csv(csv_path, index=False)
    out.to_parquet(parquet_path, index=False)
    proof = {
        "status": "EXACT_CASH_EX_DATE_ACCOUNT_OPEN_CLOSE_PROVEN",
        "authorized_keys": [[TICKER, "2026-02-13", "open"], [TICKER, "2026-02-13", "close"]],
        "authorized_ticker_dates": 1,
        "excluded_scope": "No LLY date after 2026-02-13 and no other ticker or field is authorized by this proof.",
        "candidate_pool_version": "R6_UNCHANGED",
        "v7_current_run_ids": sorted(expected_runs),
        "v7_next_required_input_rows": len(needed),
        "old_blocked_buy_paths": 3,
        "old_blocked_buy_signal_date": "2026-02-12",
        "actually_consumed_by_a_replay": False,
        "event": {
            "cusip": CUSIP,
            "class": "common stock",
            "cash_per_share": CASH,
            "issuer_declaration_date": "2025-12-08",
            "issuer_ex_date": "2026-02-13",
            "issuer_record_date": "2026-02-13",
            "issuer_payable_date": "2026-03-10",
            "issuer_dividend_news_pdf": "https://investor.lilly.com/node/53501/pdf",
            "issuer_dividend_table": "https://investor.lilly.com/stock-information/dividends-splits",
            "cusip_sec_source": "https://www.sec.gov/Archives/edgar/data/59478/000031601126000007/xslSCHEDULE_13G_X01/primary_doc.xml",
            "prior_raw_close": float(r0.close),
            "original_factor_a": factor,
            "original_factor_b": 0.0,
        },
        "index_coordinate": {
            "name": COORDINATE,
            "alpha_before": alpha_before,
            "beta_before": beta_before,
            "alpha_after": alpha_after,
            "raw_open": float(r1.open),
            "raw_close": float(r1.close),
            "authorized_open": float(p1.open),
            "authorized_close": float(p1.close),
            "unit": "frozen-account price-index unit, not shareholder total return",
        },
        "historical_vendor_factor_receipt_observed": False,
        "issuer_page_bytes_archived": False,
        "input_sha256": hashes,
        "output_sha256": {csv_path.name: sha(csv_path), parquet_path.name: sha(parquet_path)},
        "model_fit_calls": 0,
        "preprocessor_fit_calls": 0,
        "account_replay_calls": 0,
    }
    (HERE / "ROUND2_LLY_PROOF.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"authorized_keys": proof["authorized_keys"], "factor": factor, "raw_sha256": hashes["fixed_raw"]["sha256"]}))


if __name__ == "__main__":
    main()
