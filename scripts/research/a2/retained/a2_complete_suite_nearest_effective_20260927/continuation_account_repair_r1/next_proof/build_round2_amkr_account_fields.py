"""Prove only the AMKR 2026-03-12 fields consumed by frozen RL-zero accounts."""

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
REPLAY = JOINT / "continuation_account_repair_r1/replay/repair_r2_v10_cvx_lly_ral_9"
DAY = pd.Timestamp("2026-03-12")
PREVIOUS = pd.Timestamp("2026-03-11")
CODE = "US.AMKR"
RUNS = [f"joint_rl_zero_control_{cost}bps" for cost in (5, 10, 25)]
ISSUER_ANNOUNCEMENT = "https://ir.amkor.com/news-releases/news-release-details/amkor-technology-declares-quarterly-dividend-10"
ISSUER_DIVIDEND_HISTORY = "https://ir.amkor.com/stock-information/dividends-splits"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def equal(a: float, b: float, label: str) -> None:
    assert np.isfinite(a) and np.isfinite(b) and abs(a - b) <= 1e-7, (label, a, b)


def main() -> None:
    paths = {
        "joint_prices": JOINT / "data/test_prices.parquet",
        "old_prices": OLD / "data/test_prices.parquet",
        "calendar": JOINT / "data/calendar.parquet",
        "consumed_events": OLD / "data/consumed_price_events.parquet",
        "event_audit": STAGE / "r4_event_pit/ALL_1094_EVENT_PRIORITY.csv",
        "identity": STAGE / "r4_event_pit/EVENT_SECURITY_PRIORITY.csv",
        "raw_receipts": OLD / "data/PRICE_SOURCE_RECEIPTS.json",
        "fixed_raw": STAGE / "fixed_window_raw/RAW_US_AMKR_K_DAY_NONE_RTH.parquet",
        "original_adjustment_builder": Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\scripts\run_rebuild.py"),
        "v10_complete": REPLAY / "COMPLETE.json",
    }
    for run in RUNS:
        paths[f"checkpoint_{run}"] = REPLAY / run / "CHECKPOINT.json"
    hashes = {name: {"path": str(path), "sha256": sha(path)} for name, path in paths.items()}
    assert hashes["joint_prices"]["sha256"] == hashes["old_prices"]["sha256"]

    expected_needs = [
        {"ticker": "AMKR", "date": "2026-03-12", "field": "open", "purpose": "held_position_pretrade_nav_or_exit", "pending_signal_date": "2026-03-11"},
        {"ticker": "AMKR", "date": "2026-03-12", "field": "close", "purpose": "actual_held_position_valuation"},
        {"ticker": "AMKR", "date": "2026-03-12", "field": "open", "purpose": "requested_position_sell"},
    ]
    requested_by = []
    for run in RUNS:
        checkpoint = json.loads(paths[f"checkpoint_{run}"].read_text("utf-8"))
        assert checkpoint["run_id"] == run
        assert checkpoint["status"] == "paused_before_uncertified_input"
        assert checkpoint["certified_through"] == "2026-03-11"
        assert checkpoint["next_date"] == "2026-03-12"
        assert checkpoint["next_required_inputs"] == expected_needs
        assert checkpoint["holdings"]["AMKR"]["index_units"] > 0
        assert checkpoint["holdings"]["AMKR"]["mark_date"] == "2026-03-11"
        assert checkpoint["pending_recomputed_by_frozen_policy"]["signal_date"] == "2026-03-11"
        assert checkpoint["pending_recomputed_by_frozen_policy"]["targets_from_new_frozen_policy"]["AMKR"] > 0
        requested_by.append({"run_id": run, "needs": expected_needs,
                             "held_index_units": checkpoint["holdings"]["AMKR"]["index_units"]})

    calendar = pd.read_parquet(paths["calendar"])
    assert bool(calendar.loc[calendar.trade_date.eq(DAY), "is_test"].iloc[0])
    prices = pd.read_parquet(paths["joint_prices"])
    now = prices.loc[prices.ticker.eq("AMKR") & prices.trade_date.eq(DAY)]
    prior = prices.loc[prices.ticker.eq("AMKR") & prices.trade_date.eq(PREVIOUS)]
    assert len(now) == len(prior) == 1
    now, prior = now.iloc[0], prior.iloc[0]
    assert not bool(prior.price_quality_warning)
    assert now.original_transport == now.transport_used == CODE
    assert now.price_coordinate == "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN"
    assert bool(now.unresolved_event_on_or_before) and bool(now.price_quality_warning)
    assert not bool(now.lifecycle_ended) and not bool(now.extreme_adjusted_jump)
    assert all(np.isfinite(float(now[field])) and float(now[field]) > 0
               for field in ("open", "close", "raw_open", "raw_close"))

    audit = pd.read_csv(paths["event_audit"])
    a = audit.loc[audit.code.eq(CODE) & audit.source_event_date.eq("2026-03-12")]
    consumed = pd.read_parquet(paths["consumed_events"])
    events = consumed.loc[consumed.audit_kind.eq("APPLIED_CORPORATE_ACTION") & consumed.code.eq(CODE)]
    e = events.loc[pd.to_datetime(events.source_event_date).eq(DAY)]
    assert len(a) == len(e) == 1
    a, e = a.iloc[0], e.iloc[0]
    for item in (a, e):
        assert pd.Timestamp(item.event_date) == DAY and not bool(item.aligned_to_next_session)
        equal(float(item.factor_a), 0.99809, "event factor")
        assert float(item.factor_b) == 0 and not bool(item.share_event)
    equal(float(a.total_cash_div), 0.08352, "cash dividend")
    equal(float(a.prior_raw_close), float(prior.raw_close), "prior raw close")
    factor = np.floor((1 - 0.08352 / float(prior.raw_close)) * 100000) / 100000
    equal(factor, 0.99809, "original floor5 factor")
    during_2026 = pd.to_datetime(events.loc[pd.to_datetime(events.event_date).ge("2026-01-01"), "event_date"])
    assert during_2026.min() == DAY

    identity = pd.read_csv(paths["identity"], dtype={"cusip": str})
    ids = identity.loc[identity.transport_code.eq(CODE) & identity.source_event_date.eq("2026-03-12")]
    assert len(ids) > 0 and set(ids.cusip) == {"031652100"} and set(ids.title_of_class) == {"COM"}
    receipts = json.loads(paths["raw_receipts"].read_text("utf-8"))
    receipt = [r for r in receipts if r["original_code"] == CODE]
    assert len(receipt) == 1 and receipt[0]["ticker"] == "AMKR" and receipt[0]["transport"] == CODE
    source = [r for r in receipt[0]["paths"] if Path(r["path"]).name == paths["fixed_raw"].name]
    assert len(source) == 1 and source[0]["sha256"] == hashes["fixed_raw"]["sha256"]
    raw = pd.read_parquet(paths["fixed_raw"], columns=["code", "trade_date", "open", "close"])
    raw["trade_date"] = pd.to_datetime(raw.trade_date)
    r = raw.loc[raw.code.eq(CODE) & raw.trade_date.eq(DAY)]
    assert len(r) == 1
    r = r.iloc[0]
    equal(float(now.raw_open), float(r.open), "same-source raw open")
    equal(float(now.raw_close), float(r.close), "same-source raw close")
    alpha_before = (prior.open - prior.close) / (prior.raw_open - prior.raw_close)
    beta_before = prior.open - alpha_before * prior.raw_open
    equal(float(now.open), alpha_before / factor * float(now.raw_open) + beta_before, "frozen open")
    equal(float(now.close), alpha_before / factor * float(now.raw_close) + beta_before, "frozen close")

    output = pd.DataFrame([{
        "ticker": "AMKR", "trade_date": DAY, "open": float(now.open), "close": float(now.close),
        "open_authorized": True, "close_authorized": True,
        "open_purpose": "held_position_pretrade_nav_or_exit_and_requested_position_sell",
        "close_purpose": "actual_held_position_valuation_if_still_held_after_frozen_orders",
        "evidence_id": "AMKR_20260312_FIRST_CASH_ACCOUNT_FIELD",
        "candidate_pool_version": "R6_UNCHANGED", "fixed_raw_sha256": hashes["fixed_raw"]["sha256"],
    }])
    csv_path = HERE / "ROUND2_AMKR_ACCOUNT_PRICE_FIELDS.csv"
    parquet_path = HERE / "ROUND2_AMKR_ACCOUNT_PRICE_FIELDS.parquet"
    if csv_path.exists() or parquet_path.exists():
        raise RuntimeError("preserve existing AMKR proof")
    output.to_csv(csv_path, index=False)
    output.to_parquet(parquet_path, index=False)
    proof = {
        "status": "ONE_DAY_HELD_POSITION_AND_REQUESTED_SELL_FIELDS_PROVEN",
        "ticker": "AMKR", "date": "2026-03-12", "cusip": "031652100", "class": "COM",
        "issuer_announcement_date": "2026-02-19", "issuer_record_date": "2026-03-12",
        "issuer_ex_date": "2026-03-12", "issuer_cash_per_common_share": 0.08352,
        "issuer_announcement_url": ISSUER_ANNOUNCEMENT,
        "issuer_dividend_history_url": ISSUER_DIVIDEND_HISTORY,
        "original_event_date": "2026-03-12", "factor_a": factor, "factor_b": 0,
        "prior_raw_close": float(prior.raw_close), "requested_by": requested_by,
        "scope": "2026-03-12_ONLY", "candidate_pool_version": "R6_UNCHANGED",
        "price_coordinate": "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN",
        "historical_vendor_receipt_observed": False,
        "source_sha256": hashes,
        "output_sha256": {csv_path.name: sha(csv_path), parquet_path.name: sha(parquet_path)},
        "model_fit_calls": 0, "preprocessor_fit_calls": 0, "account_replay_calls": 0,
    }
    proof_path = HERE / "ROUND2_AMKR_PROOF.json"
    if proof_path.exists():
        raise RuntimeError("preserve existing AMKR proof")
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"authorized_ticker_dates": len(output), "run_count": len(requested_by),
                      "open": float(now.open), "close": float(now.close)}))


if __name__ == "__main__":
    main()
