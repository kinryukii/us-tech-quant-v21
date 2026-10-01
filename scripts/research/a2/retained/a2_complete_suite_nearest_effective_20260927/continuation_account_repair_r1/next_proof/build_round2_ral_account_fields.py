"""Verify the single RAL account input needed by the V7 RL-zero paths."""

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
DAY = pd.Timestamp("2026-03-09")
PREVIOUS = pd.Timestamp("2026-03-06")
CODE = "US.RAL"
RUNS = [f"joint_rl_zero_control_{cost}bps" for cost in (5, 10, 25)]
REPLAY_VERSION = "repair_r2_v7_early_or_rrx_15"
ISSUER_URL = "https://investors.ralliant.com/news-events/press-releases/detail/118/ralliant-declares-regular-quarterly-dividend"
SEC_URL = "https://investors.ralliant.com/sec-filings/all-sec-filings/content/0002041385-26-000004/ralq42025-ex991.htm"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        "fixed_raw": STAGE / "fixed_window_raw/RAW_US_RAL_K_DAY_NONE_RTH.parquet",
        "original_adjustment_builder": Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\scripts\run_rebuild.py"),
    }
    for run in RUNS:
        paths[f"checkpoint_{run}"] = JOINT / "continuation_account_repair_r1/replay" / REPLAY_VERSION / run / "CHECKPOINT.json"
    hashes = {name: {"path": str(path), "sha256": sha(path)} for name, path in paths.items()}
    assert hashes["joint_prices"]["sha256"] == hashes["old_prices"]["sha256"]

    expected_needs = [
        {"ticker": "RAL", "date": "2026-03-09", "field": "open", "purpose": "held_position_pretrade_nav_or_exit", "pending_signal_date": "2026-03-06"},
        {"ticker": "RAL", "date": "2026-03-09", "field": "close", "purpose": "actual_held_position_valuation"},
        {"ticker": "RAL", "date": "2026-03-09", "field": "open", "purpose": "requested_position_sell"},
    ]
    checkpoints = []
    for run in RUNS:
        checkpoint = json.loads(paths[f"checkpoint_{run}"].read_text("utf-8"))
        assert checkpoint["run_id"] == run
        assert checkpoint["status"] == "paused_before_uncertified_input"
        assert checkpoint["certified_through"] == "2026-03-06"
        assert checkpoint["next_date"] == "2026-03-09"
        assert checkpoint["next_required_inputs"] == expected_needs
        assert checkpoint["holdings"]["RAL"]["index_units"] > 0
        assert checkpoint["holdings"]["RAL"]["mark_date"] == "2026-03-06"
        assert checkpoint["pending_recomputed_by_frozen_policy"]["signal_date"] == "2026-03-06"
        assert "RAL" not in checkpoint["pending_recomputed_by_frozen_policy"]["targets_from_new_frozen_policy"]
        checkpoints.append({
            "run_id": run,
            "certified_through": checkpoint["certified_through"],
            "held_index_units": checkpoint["holdings"]["RAL"]["index_units"],
            "next_required_inputs": checkpoint["next_required_inputs"],
        })

    prices = pd.read_parquet(paths["joint_prices"])
    p = prices.loc[prices.ticker.eq("RAL") & prices.trade_date.eq(DAY)]
    previous = prices.loc[prices.ticker.eq("RAL") & prices.trade_date.eq(PREVIOUS)]
    assert len(p) == len(previous) == 1
    p, previous = p.iloc[0], previous.iloc[0]
    calendar = pd.read_parquet(paths["calendar"])
    assert bool(calendar.loc[calendar.trade_date.eq(DAY), "is_test"].iloc[0])
    assert not bool(previous.price_quality_warning)
    assert p.original_transport == p.transport_used == CODE
    assert p.price_coordinate == "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN"
    assert bool(p.unresolved_event_on_or_before) and bool(p.price_quality_warning)
    assert not bool(p.lifecycle_ended) and not bool(p.extreme_adjusted_jump)
    for field in ("open", "close", "raw_open", "raw_close"):
        assert np.isfinite(p[field]) and p[field] > 0

    audit = pd.read_csv(paths["event_audit"])
    original = audit.loc[audit.code.eq(CODE) & audit.source_event_date.eq("2026-03-09")]
    consumed = pd.read_parquet(paths["consumed_events"])
    all_events = consumed.loc[consumed.audit_kind.eq("APPLIED_CORPORATE_ACTION") & consumed.code.eq(CODE)]
    event = all_events.loc[pd.to_datetime(all_events.source_event_date).eq(DAY)]
    assert len(original) == len(event) == 1
    original, event = original.iloc[0], event.iloc[0]
    for item in (original, event):
        assert pd.Timestamp(item.event_date) == DAY and not bool(item.aligned_to_next_session)
        assert float(item.factor_a) == 0.99887 and float(item.factor_b) == 0
        assert not bool(item.share_event)
    assert float(original.total_cash_div) == 0.05
    equal(float(original.prior_raw_close), float(previous.raw_close), "prior_close")
    factor = np.floor((1 - 0.05 / float(previous.raw_close)) * 100000) / 100000
    equal(factor, 0.99887, "floor5_factor")
    future_events = pd.to_datetime(all_events.loc[pd.to_datetime(all_events.event_date).ge("2026-01-01"), "event_date"])
    assert len(future_events) == 2 and future_events.min() == DAY

    identity = pd.read_csv(paths["identity"], dtype={"cusip": str})
    one_identity = identity.loc[identity.transport_code.eq(CODE) & identity.source_event_date.eq("2026-03-09")]
    assert len(one_identity) > 0 and set(one_identity.cusip) == {"750940108"}
    assert set(one_identity.title_of_class) == {"COM"}
    receipts = json.loads(paths["raw_receipts"].read_text("utf-8"))
    receipt = [r for r in receipts if r["original_code"] == CODE]
    assert len(receipt) == 1 and receipt[0]["ticker"] == "RAL" and receipt[0]["transport"] == CODE
    fixed_receipt = [r for r in receipt[0]["paths"] if Path(r["path"]).name == paths["fixed_raw"].name]
    assert len(fixed_receipt) == 1 and fixed_receipt[0]["sha256"] == hashes["fixed_raw"]["sha256"]
    raw = pd.read_parquet(paths["fixed_raw"], columns=["code", "trade_date", "open", "close"])
    raw["trade_date"] = pd.to_datetime(raw.trade_date)
    r = raw.loc[raw.code.eq(CODE) & raw.trade_date.eq(DAY)]
    assert len(r) == 1
    r = r.iloc[0]
    equal(float(p.raw_open), float(r.open), "raw_open")
    equal(float(p.raw_close), float(r.close), "raw_close")
    alpha_before = (previous.open - previous.close) / (previous.raw_open - previous.raw_close)
    beta_before = previous.open - alpha_before * previous.raw_open
    equal(float(p.open), alpha_before / factor * float(p.raw_open) + beta_before, "adjusted_open")
    equal(float(p.close), alpha_before / factor * float(p.raw_close) + beta_before, "adjusted_close")

    output = pd.DataFrame([{
        "ticker": "RAL", "trade_date": DAY, "open": float(p.open), "close": float(p.close),
        "open_authorized": True, "close_authorized": True,
        "open_purpose": "held_position_pretrade_nav_or_exit_and_requested_position_sell",
        "close_purpose": "actual_held_position_valuation_if_still_held_after_frozen_orders",
        "evidence_id": "RAL_20260309_FIRST_CASH_ACCOUNT_FIELD",
        "candidate_pool_version": "R6_UNCHANGED", "fixed_raw_sha256": hashes["fixed_raw"]["sha256"],
    }])
    csv_path = HERE / "ROUND2_RAL_ACCOUNT_PRICE_FIELDS.csv"
    parquet_path = HERE / "ROUND2_RAL_ACCOUNT_PRICE_FIELDS.parquet"
    output.to_csv(csv_path, index=False)
    output.to_parquet(parquet_path, index=False)
    report = {
        "status": "ONE_DAY_HELD_POSITION_EXIT_OPEN_AND_CONDITIONAL_VALUATION_CLOSE_PROVEN",
        "ticker": "RAL", "date": "2026-03-09", "cusip": "750940108", "class": "COM",
        "issuer_public_date": "2026-01-29", "issuer_record_date": "2026-03-09",
        "issuer_payable_date": "2026-03-23", "issuer_cash_per_common_share": 0.05,
        "issuer_source_url": ISSUER_URL, "contemporary_sec_corrob_url": SEC_URL,
        "original_event_date": "2026-03-09", "factor_a": factor, "factor_b": 0,
        "prior_raw_close": float(previous.raw_close),
        "requested_by": checkpoints, "scope": "2026-03-09_ONLY",
        "candidate_pool_version": "R6_UNCHANGED",
        "price_coordinate": "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN",
        "historical_vendor_receipt_observed": False, "issuer_page_bytes_archived": False,
        "input_sha256": hashes,
        "output_sha256": {csv_path.name: sha(csv_path), parquet_path.name: sha(parquet_path)},
        "model_fit_calls": 0, "preprocessor_fit_calls": 0, "account_replay_calls": 0,
    }
    (HERE / "ROUND2_RAL_PROOF.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"authorized_ticker_dates": len(output), "run_count": len(checkpoints), "date": "2026-03-09"}))


if __name__ == "__main__":
    main()
