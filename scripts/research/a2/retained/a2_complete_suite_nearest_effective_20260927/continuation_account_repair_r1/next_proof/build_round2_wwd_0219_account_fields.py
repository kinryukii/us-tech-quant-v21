"""Prove only the V13 WWD 2026-02-19 requested buy open and conditional mark."""

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
V13 = HERE.parent / "replay/repair_r2_v13_cvx_lly_followon_6"
CODE, TICKER, CUSIP = "US.WWD", "WWD", "980745103"
PREVIOUS, DAY = pd.Timestamp("2026-02-18"), pd.Timestamp("2026-02-19")
CASH, FACTOR = 0.32, 0.99918
RUNS = [f"joint_rl_ensemble_{bps}bps" for bps in (5, 10, 25)]
COORDINATE = "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN"
EVIDENCE_ID = "ROUND2_WWD_20260219_CASH_ACCOUNT_FIELD"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def one(frame: pd.DataFrame, label: str) -> pd.Series:
    assert len(frame) == 1, (label, len(frame))
    return frame.iloc[0]


def close(actual: float, expected: float, label: str, atol: float = 1e-7) -> None:
    assert np.isfinite(actual) and np.isfinite(expected), label
    assert np.isclose(actual, expected, rtol=0, atol=atol), (label, actual, expected)


def main() -> None:
    paths = {
        "joint_prices": JOINT / "data/test_prices.parquet",
        "old_prices": OLD / "data/test_prices.parquet",
        "calendar": JOINT / "data/calendar.parquet",
        "consumed_events": OLD / "data/consumed_price_events.parquet",
        "event_audit": STAGE / "r4_event_pit/ALL_1094_EVENT_PRIORITY.csv",
        "security_identity": STAGE / "r4_event_pit/EVENT_SECURITY_PRIORITY.csv",
        "source_receipts": OLD / "data/PRICE_SOURCE_RECEIPTS.json",
        "fixed_raw": STAGE / "fixed_window_raw/RAW_US_WWD_K_DAY_NONE_RTH.parquet",
        "v13_progress": V13 / "PROGRESS.json",
        "frozen_account_engine": JOINT / "engine.py",
    }
    for run in RUNS:
        paths[f"v13_{run}_checkpoint"] = V13 / run / "CHECKPOINT.json"
    hashes = {name: {"path": str(path), "sha256": sha(path)} for name, path in paths.items()}
    assert hashes["joint_prices"]["sha256"] == hashes["old_prices"]["sha256"]

    needs = []
    targets = {}
    for run in RUNS:
        checkpoint = json.loads(paths[f"v13_{run}_checkpoint"].read_text("utf-8"))
        assert checkpoint["run_id"] == run and checkpoint["status"] == "paused_before_uncertified_input"
        assert checkpoint["certified_through"] == "2026-02-18" and checkpoint["next_date"] == "2026-02-19"
        assert checkpoint["new_predictor_fit_attempts"] == 0
        assert checkpoint["new_preprocessor_fit_attempts"] == 0
        assert checkpoint["next_required_inputs"] == [{
            "ticker": TICKER, "date": "2026-02-19", "field": "open", "purpose": "requested_target_buy"
        }]
        assert TICKER not in checkpoint["holdings"]
        pending = checkpoint["pending_recomputed_by_frozen_policy"]
        assert pending["signal_date"] == "2026-02-18"
        target = float(pending["targets_from_new_frozen_policy"][TICKER])
        assert target > 0
        targets[run] = target
        needs.append({"run_id": run, **checkpoint["next_required_inputs"][0]})

    calendar = pd.read_parquet(paths["calendar"])
    assert bool(one(calendar.loc[calendar.trade_date.eq(DAY)], "test calendar date").is_test)
    prices = pd.read_parquet(paths["joint_prices"])
    pre = one(prices.loc[prices.ticker.eq(TICKER) & prices.trade_date.eq(PREVIOUS)], "prior price")
    p = one(prices.loc[prices.ticker.eq(TICKER) & prices.trade_date.eq(DAY)], "requested price")
    assert not bool(pre.price_quality_warning) and not bool(pre.unresolved_event_on_or_before)
    assert pre.original_transport == pre.transport_used == CODE
    for row in (pre, p):
        assert row.original_transport == row.transport_used == CODE
        assert row.price_coordinate == COORDINATE
        assert not bool(row.lifecycle_ended) and not bool(row.extreme_adjusted_jump)
        for field in ("open", "close", "raw_open", "raw_close", "volume"):
            assert np.isfinite(row[field]) and row[field] > 0
    assert bool(p.unresolved_event_on_or_before) and bool(p.price_quality_warning)

    receipts = json.loads(paths["source_receipts"].read_text("utf-8"))
    receipt = [r for r in receipts if r["ticker"] == TICKER and r["original_code"] == CODE]
    assert len(receipt) == 1 and receipt[0]["transport"] == CODE
    fixed_receipt = [r for r in receipt[0]["paths"] if Path(r["path"]).name == paths["fixed_raw"].name]
    assert len(fixed_receipt) == 1 and fixed_receipt[0]["sha256"] == hashes["fixed_raw"]["sha256"]
    raw = pd.read_parquet(paths["fixed_raw"])
    rpre = one(raw.loc[raw.code.eq(CODE) & raw.trade_date.eq(PREVIOUS)], "prior same-source Raw")
    r = one(raw.loc[raw.code.eq(CODE) & raw.trade_date.eq(DAY)], "same-source Raw")
    close(float(r.last_close), float(rpre.close), "Raw last_close continuity")
    for adjusted, source in ((pre, rpre), (p, r)):
        close(float(adjusted.raw_open), float(source.open), "Raw open")
        close(float(adjusted.raw_close), float(source.close), "Raw close")
        close(float(adjusted.volume), float(source.volume), "Raw volume")

    events = pd.read_parquet(paths["consumed_events"])
    applied = events.loc[
        events.code.eq(CODE) & events.audit_kind.eq("APPLIED_CORPORATE_ACTION")
        & pd.to_datetime(events.event_date).between("2026-01-01", DAY)
    ]
    event = one(applied, "one original 2026 corporate action through requested day")
    audit = pd.read_csv(paths["event_audit"])
    original = one(audit.loc[audit.code.eq(CODE) & audit.source_event_date.eq("2026-02-19")], "R4 event")
    for item in (event, original):
        assert item.code == CODE and item.ticker == TICKER
        assert item.audit_kind == "APPLIED_CORPORATE_ACTION"
        assert pd.Timestamp(item.event_date) == DAY and pd.Timestamp(item.source_event_date) == DAY
        assert not bool(item.aligned_to_next_session) and not bool(item.share_event)
        close(float(item.factor_a), FACTOR, "factor A", atol=1e-12)
        close(float(item.factor_b), 0.0, "factor B", atol=1e-12)
    assert original.original_code == original.transport_code == CODE
    close(float(original.prior_raw_close), float(rpre.close), "event prior Raw close")
    close(float(original.total_cash_div), CASH, "issuer common cash dividend")
    assert bool(original.simple_cash_floor_matches_vendor)
    factor = np.floor(((float(rpre.close) - CASH) / float(rpre.close)) * 100000) / 100000
    close(factor, FACTOR, "floor5 cash factor", atol=1e-12)
    identity = pd.read_csv(paths["security_identity"], dtype={"cusip": str})
    security = identity.loc[
        identity.original_code.eq(CODE) & identity.transport_code.eq(CODE)
        & identity.source_event_date.eq("2026-02-19")
    ]
    assert len(security) > 0 and set(security.cusip) == {CUSIP}
    assert set(security.title_of_class) == {"COM"} and security.total_cash_div.eq(CASH).all()

    assert float(pre.raw_open) != float(pre.raw_close)
    alpha_before = (float(pre.open) - float(pre.close)) / (float(pre.raw_open) - float(pre.raw_close))
    beta_before = float(pre.open) - alpha_before * float(pre.raw_open)
    alpha_after = alpha_before / factor
    close(beta_before, 0.0, "affine beta", atol=1e-8)
    close(float(p.open), alpha_after * float(r.open) + beta_before, "frozen index open")
    close(float(p.close), alpha_after * float(r.close) + beta_before, "frozen index close")

    out = pd.DataFrame([{
        "ticker": TICKER, "trade_date": DAY, "open": float(p.open), "close": float(p.close),
        "open_authorized": True, "close_authorized": True,
        "close_purpose": "conditional_same_day_mark_only_if_frozen_buy_fills",
        "evidence_id": EVIDENCE_ID, "candidate_pool_version": "R6_UNCHANGED",
        "fixed_raw_sha256": hashes["fixed_raw"]["sha256"],
    }])
    csv_path = HERE / "ROUND2_WWD_0219_EVENT_ACCOUNT_PRICE_FIELDS.csv"
    parquet_path = HERE / "ROUND2_WWD_0219_EVENT_ACCOUNT_PRICE_FIELDS.parquet"
    out.to_csv(csv_path, index=False)
    out.to_parquet(parquet_path, index=False)
    proof = {
        "status": "EXACT_V13_WWD_BUY_OPEN_AND_CONDITIONAL_CLOSE_PROVEN",
        "authorized_keys": [[TICKER, "2026-02-19", "open"], [TICKER, "2026-02-19", "close"]],
        "close_is_conditional": True,
        "close_condition": "Only same-day held-position valuation if the frozen requested buy actually fills.",
        "excluded_scope": "No WWD date after 2026-02-19 is authorized; no fill is claimed here.",
        "candidate_pool_version": "R6_UNCHANGED", "v13_required_input_rows": needs,
        "v13_frozen_positive_target_weights": targets,
        "event": {
            "ticker": TICKER, "original_code": CODE, "transport": CODE,
            "cusip": CUSIP, "class": "COM", "original_applied_event_date": "2026-02-19",
            "issuer_board_approval_date": "2026-01-28",
            "sec_8k_accepted_at": "2026-02-02 07:00:29 ET",
            "sec_8k_index": "https://www.sec.gov/Archives/edgar/data/108312/000117184326000553/0001171843-26-000553-index.htm",
            "sec_8k_document": "https://www.sec.gov/Archives/edgar/data/108312/000117184326000553/f8k_013126.htm",
            "sec_2025_identity_13f": "https://www.sec.gov/Archives/edgar/data/920441/000092044125000007/xslForm13F_X02/LKA-13f.xml",
            "issuer_record_date": "2026-02-19", "issuer_payable_date": "2026-03-05",
            "issuer_cash_per_common_share": CASH,
            "issuer_ex_date_stated_in_cited_8k": False,
            "original_factor_a": factor, "original_factor_b": 0.0,
            "no_other_2026_applied_event_through_20260219": True,
        },
        "coordinate": {
            "name": COORDINATE, "alpha_before": alpha_before, "beta_before": beta_before,
            "alpha_after": alpha_after, "prior_raw_close": float(rpre.close),
            "raw_open": float(r.open), "raw_close": float(r.close), "raw_volume": float(r.volume),
            "authorized_open": float(p.open), "conditional_close": float(p.close),
            "unit": "frozen-account price-index unit, not shareholder total return",
        },
        "historical_vendor_factor_receipt_observed": False,
        "issuer_page_bytes_archived": False,
        "input_sha256": hashes,
        "output_sha256": {csv_path.name: sha(csv_path), parquet_path.name: sha(parquet_path)},
        "model_fit_calls": 0, "preprocessor_fit_calls": 0, "account_replay_calls": 0,
    }
    (HERE / "ROUND2_WWD_0219_PROOF.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"authorized_keys": proof["authorized_keys"], "open": float(p.open), "conditional_close": float(p.close)}))


if __name__ == "__main__":
    main()
