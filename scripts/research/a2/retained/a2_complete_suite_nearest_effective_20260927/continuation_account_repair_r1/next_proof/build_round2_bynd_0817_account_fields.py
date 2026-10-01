"""Prove only the V8 Elastic Net BYND 2026-08-17 account fields."""

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
V8 = HERE.parent / "replay/repair_r2_v8_bynd_6"
TICKER, CODE = "BYND", "US.BYND"
SPLIT = pd.Timestamp("2026-08-14")
DAY = pd.Timestamp("2026-08-17")
COORDINATE = "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN"
EVIDENCE_ID = "ROUND2_BYND_20260817_SPLIT_SUCCESSOR_INDEX_UNIT"
RUNS = {f"joint_elastic_net_{bps}bps" for bps in (5, 10, 25)}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def close(actual: float, expected: float, label: str, atol: float = 1e-8) -> None:
    assert np.isfinite(actual) and np.isfinite(expected), label
    assert np.isclose(actual, expected, rtol=0, atol=atol), (label, actual, expected)


def one(frame: pd.DataFrame, label: str) -> pd.Series:
    assert len(frame) == 1, (label, len(frame))
    return frame.iloc[0]


def main() -> None:
    paths = {
        "old_dynamic_queue": HERE.parent / "DYNAMIC_NEXT_INPUT_QUEUE.csv",
        "previous_0814_proof": HERE / "ROUND2_BYND_PROOF.json",
        "previous_0814_allowlist": HERE / "ROUND2_BYND_EVENT_ACCOUNT_PRICE_FIELDS.parquet",
        "joint_prices": JOINT / "data/test_prices.parquet",
        "old_prices": OLD / "data/test_prices.parquet",
        "calendar": JOINT / "data/calendar.parquet",
        "consumed_events": OLD / "data/consumed_price_events.parquet",
        "event_audit": STAGE / "r4_event_pit/ALL_1094_EVENT_PRIORITY.csv",
        "security_identity": STAGE / "r4_event_pit/EVENT_SECURITY_PRIORITY.csv",
        "source_receipts": OLD / "data/PRICE_SOURCE_RECEIPTS.json",
        "fixed_raw": STAGE / "fixed_window_raw/RAW_US_BYND_K_DAY_NONE_RTH.parquet",
        "frozen_account_engine": JOINT / "engine.py",
    }
    for run in sorted(RUNS):
        paths[f"v8_{run}_checkpoint"] = V8 / run / "CHECKPOINT.json"
        paths[f"v8_{run}_consumed_approvals"] = V8 / run / "CONSUMED_APPROVALS.csv"
    hashes = {name: {"path": str(path), "sha256": sha(path)} for name, path in paths.items()}
    assert hashes["joint_prices"]["sha256"] == hashes["old_prices"]["sha256"]

    old_queue = pd.read_csv(paths["old_dynamic_queue"], dtype=str).fillna("")
    old_need = old_queue.loc[old_queue.ticker.eq(TICKER) & old_queue.date.eq("2026-08-14")]
    assert len(old_need) == 2 and set(old_need.field) == {"open", "close"}
    assert old_queue.loc[old_queue.ticker.eq(TICKER) & old_queue.date.eq("2026-08-17")].empty
    prior_proof = json.loads(paths["previous_0814_proof"].read_text("utf-8"))
    assert prior_proof["status"] == "EXACT_SPLIT_DAY_ACCOUNT_OPEN_CLOSE_PROVEN"
    assert prior_proof["authorized_keys"] == [[TICKER, "2026-08-14", "open"], [TICKER, "2026-08-14", "close"]]
    assert prior_proof["event"]["old_cusip"] == "08862E109"
    assert prior_proof["event"]["new_cusip"] == "08862E307"
    assert prior_proof["output_sha256"][paths["previous_0814_allowlist"].name] == hashes["previous_0814_allowlist"]["sha256"]
    prior_allow = pd.read_parquet(paths["previous_0814_allowlist"])
    assert len(prior_allow) == 1 and prior_allow.ticker.iloc[0] == TICKER
    assert prior_allow.trade_date.iloc[0] == SPLIT
    assert bool(prior_allow.open_authorized.iloc[0]) and bool(prior_allow.close_authorized.iloc[0])

    needs = []
    holdings = {}
    for run in sorted(RUNS):
        checkpoint = json.loads(paths[f"v8_{run}_checkpoint"].read_text("utf-8"))
        assert checkpoint["run_id"] == run and checkpoint["status"] == "paused_before_uncertified_input"
        assert checkpoint["certified_through"] == "2026-08-14" and checkpoint["next_date"] == "2026-08-17"
        assert checkpoint["new_predictor_fit_attempts"] == 0 and checkpoint["new_preprocessor_fit_attempts"] == 0
        found = checkpoint["next_required_inputs"]
        assert len(found) == 3
        assert {(x["ticker"], x["date"], x["field"], x["purpose"]) for x in found} == {
            (TICKER, "2026-08-17", "open", "held_position_pretrade_nav_or_exit"),
            (TICKER, "2026-08-17", "open", "requested_position_sell"),
            (TICKER, "2026-08-17", "close", "actual_held_position_valuation"),
        }
        held_need = one(pd.DataFrame(found).loc[lambda d: d.purpose.eq("held_position_pretrade_nav_or_exit")], "held open")
        assert held_need.pending_signal_date == "2026-08-14"
        position = checkpoint["holdings"][TICKER]
        assert position["index_units"] > 0 and position["mark_date"] == "2026-08-14"
        assert position["mark_source"] == "close"
        close(float(position["mark"]), float(prior_allow.close.iloc[0]), "previous certified mark")
        approvals = pd.read_csv(paths[f"v8_{run}_consumed_approvals"], dtype=str).fillna("")
        bynd = approvals.loc[approvals.ticker.eq(TICKER) & approvals.trade_date.eq("2026-08-14")]
        assert len(bynd) == 2 and set(bynd.field) == {"open", "close"}
        assert set(bynd.evidence_id) == {"ROUND2_BYND_20260814_REVERSE_SPLIT_INDEX_UNIT"}
        needs.extend([{"run_id": run, **item} for item in found])
        holdings[run] = float(position["index_units"])

    calendar = pd.read_parquet(paths["calendar"])
    assert bool(one(calendar.loc[calendar.trade_date.eq(DAY)], "calendar session").is_test)
    prices = pd.read_parquet(paths["joint_prices"])
    before = one(prices.loc[prices.ticker.eq(TICKER) & prices.trade_date.eq(pd.Timestamp("2026-08-13"))], "pre-split price")
    split = one(prices.loc[prices.ticker.eq(TICKER) & prices.trade_date.eq(SPLIT)], "split day price")
    p = one(prices.loc[prices.ticker.eq(TICKER) & prices.trade_date.eq(DAY)], "new account date price")
    for row in (split, p):
        assert row.original_transport == CODE and row.transport_used == CODE
        assert row.price_coordinate == COORDINATE
        assert bool(row.unresolved_event_on_or_before) and bool(row.price_quality_warning)
        assert not bool(row.lifecycle_ended) and not bool(row.extreme_adjusted_jump)
        for field in ("open", "close", "raw_open", "raw_close", "volume"):
            assert np.isfinite(row[field]) and row[field] > 0
    assert not bool(before.unresolved_event_on_or_before) and not bool(before.price_quality_warning)
    close(float(split.open), float(prior_allow.open.iloc[0]), "previous allowlisted open")
    close(float(split.close), float(prior_allow.close.iloc[0]), "previous allowlisted close")

    receipts = json.loads(paths["source_receipts"].read_text("utf-8"))
    receipt = [r for r in receipts if r["ticker"] == TICKER and r["original_code"] == CODE]
    assert len(receipt) == 1 and receipt[0]["transport"] == CODE
    raw_receipt = [r for r in receipt[0]["paths"] if Path(r["path"]).name == paths["fixed_raw"].name]
    assert len(raw_receipt) == 1 and raw_receipt[0]["sha256"] == hashes["fixed_raw"]["sha256"]
    raw = pd.read_parquet(paths["fixed_raw"])
    rsplit = one(raw.loc[raw.code.eq(CODE) & raw.trade_date.eq(SPLIT)], "same-source split-day Raw")
    r = one(raw.loc[raw.code.eq(CODE) & raw.trade_date.eq(DAY)], "same-source new-day Raw")
    assert r["name"] == "Beyond Meat"
    close(float(r.last_close), float(rsplit.close), "Raw continuity since split")
    close(float(p.raw_open), float(r.open), "same-source raw open")
    close(float(p.raw_close), float(r.close), "same-source raw close")

    events = pd.read_parquet(paths["consumed_events"])
    bynd_events = events.loc[events.code.eq(CODE) & pd.to_datetime(events.event_date).between("2026-01-01", DAY)]
    event = one(bynd_events, "only 2026 corporate action through new date")
    assert pd.Timestamp(event.event_date) == SPLIT and pd.Timestamp(event.source_event_date) == SPLIT
    assert bool(event.share_event) and not bool(event.aligned_to_next_session)
    close(float(event.factor_a), 30.0, "split factor a")
    close(float(event.factor_b), 0.0, "split factor b")
    audit = pd.read_csv(paths["event_audit"])
    original = one(audit.loc[audit.code.eq(CODE) & audit.source_event_date.eq("2026-08-14")], "r4 original event")
    assert original.original_code == CODE and original.transport_code == CODE
    close(float(original.factor_a), 30.0, "original split factor")
    identity = pd.read_csv(paths["security_identity"], dtype={"cusip": str})
    predecessor = identity.loc[identity.transport_code.eq(CODE) & identity.source_event_date.eq("2026-08-14")]
    assert set(predecessor.cusip) == {"08862E109"} and set(predecessor.title_of_class) == {"COM"}
    assert prior_proof["event"]["new_cusip"] == "08862E307"

    assert before.raw_open != before.raw_close
    alpha_before = (float(before.open) - float(before.close)) / (float(before.raw_open) - float(before.raw_close))
    beta_before = float(before.open) - alpha_before * float(before.raw_open)
    close(alpha_before, 1.0, "pre-split alpha")
    close(beta_before, 0.0, "pre-split beta")
    alpha_after = alpha_before / 30.0
    for adjusted, source in ((split, rsplit), (p, r)):
        close(float(adjusted.open), alpha_after * float(source.open) + beta_before, "successor index open")
        close(float(adjusted.close), alpha_after * float(source.close) + beta_before, "successor index close")
        close(float(adjusted.volume), 30.0 * float(source.volume), "successor index volume")

    out = pd.DataFrame([{
        "ticker": TICKER,
        "trade_date": DAY,
        "open": float(p.open),
        "close": float(p.close),
        "open_authorized": True,
        "close_authorized": True,
        "evidence_id": EVIDENCE_ID,
        "candidate_pool_version": "R6_UNCHANGED",
        "fixed_raw_sha256": hashes["fixed_raw"]["sha256"],
    }])
    csv_path = HERE / "ROUND2_BYND_0817_EVENT_ACCOUNT_PRICE_FIELDS.csv"
    parquet_path = HERE / "ROUND2_BYND_0817_EVENT_ACCOUNT_PRICE_FIELDS.parquet"
    out.to_csv(csv_path, index=False)
    out.to_parquet(parquet_path, index=False)
    proof = {
        "status": "EXACT_V8_ELASTIC_NET_SPLIT_SUCCESSOR_ACCOUNT_FIELDS_PROVEN",
        "authorized_keys": [[TICKER, "2026-08-17", "open"], [TICKER, "2026-08-17", "close"]],
        "excluded_scope": "No Q90 2026-08-17 demand or BYND date after 2026-08-17 is authorized by this proof.",
        "candidate_pool_version": "R6_UNCHANGED",
        "v8_current_run_ids": sorted(RUNS),
        "v8_required_input_rows": needs,
        "v8_previous_certified_holdings_index_units": holdings,
        "old_dynamic_queue_proved_only_20260814": True,
        "previous_0814_evidence_id": "ROUND2_BYND_20260814_REVERSE_SPLIT_INDEX_UNIT",
        "same_source_event": {
            "pre_split_cusip": "08862E109",
            "successor_cusip": "08862E307",
            "split_ratio": "1 post-split share for 30 pre-split shares",
            "issuer_announcement_date": "2026-08-11",
            "issuer_actual_effectiveness_8k_sec_accepted": "2026-08-14 07:02:14",
            "issuer_announcement": "https://www.sec.gov/Archives/edgar/data/1655210/000165521026000057/ex991pressreleaseannouncin.htm",
            "nasdaq_alert": "https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2026-568",
            "issuer_actual_effectiveness_8k_index": "https://www.sec.gov/Archives/edgar/data/1655210/000165521026000059/0001655210-26-000059-index.htm",
            "issuer_actual_effectiveness_8k": "https://www.sec.gov/Archives/edgar/data/1655210/000165521026000059/bynd-20260813.htm",
            "no_additional_consumed_corporate_action_through_20260817": True,
        },
        "index_coordinate": {
            "name": COORDINATE,
            "alpha_before": alpha_before,
            "beta_before": beta_before,
            "alpha_after": alpha_after,
            "raw_open": float(r.open),
            "raw_close": float(r.close),
            "raw_volume": float(r.volume),
            "authorized_open": float(p.open),
            "authorized_close": float(p.close),
            "adjusted_index_volume": float(p.volume),
            "unit": "frozen-account price-index unit, not raw post-split share",
        },
        "historical_vendor_factor_receipt_observed": False,
        "issuer_or_exchange_page_bytes_archived": False,
        "input_sha256": hashes,
        "output_sha256": {csv_path.name: sha(csv_path), parquet_path.name: sha(parquet_path)},
        "model_fit_calls": 0,
        "preprocessor_fit_calls": 0,
        "account_replay_calls": 0,
    }
    (HERE / "ROUND2_BYND_0817_PROOF.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"authorized_keys": proof["authorized_keys"], "v8_runs": sorted(RUNS)}))


if __name__ == "__main__":
    main()
