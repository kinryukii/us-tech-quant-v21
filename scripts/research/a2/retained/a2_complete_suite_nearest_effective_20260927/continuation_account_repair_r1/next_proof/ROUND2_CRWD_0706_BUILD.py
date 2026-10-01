"""Single-day continuation of certified CRWD split coordinate for V16."""

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
REPLAY = JOINT / "continuation_account_repair_r1/replay/repair_r2_v16_crwd_0702_3"
PRIOR_PROOF = HERE / "ROUND2_CRWD_0702_PROOF.json"
PRIOR_FIELDS = HERE / "ROUND2_CRWD_0702_ACCOUNT_PRICE_FIELDS.csv"


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
    prior = json.loads(PRIOR_PROOF.read_text(encoding="utf-8"))
    assert prior["status"] == "CURRENT_2026_07_02_CRWD_SPLIT_FIELDS_PROVEN"
    assert prior["scope"] == "ONLY_CRWD_2026_07_02_V14_LOGISTIC_ACTUAL_ACCOUNT_OPEN_AND_CLOSE"
    assert sha(PRIOR_FIELDS) == prior["output_sha256"][PRIOR_FIELDS.name]
    for item in prior["input_sha256"].values():
        assert sha(Path(item["path"])) == item["sha256"]
    first = one(pd.read_csv(PRIOR_FIELDS), "07-02 approved field")
    assert first.ticker == "CRWD" and first.trade_date == "2026-07-02"
    assert bool(first.open_authorized) and bool(first.close_authorized)
    assert first.candidate_pool_version == "R6_UNCHANGED"
    assert float(first.open) == 765.02 and float(first.close) == 775.92

    prices_path = JOINT / "data/test_prices.parquet"
    raw_path = STAGE / "fixed_window_raw/RAW_US_CRWD_K_DAY_NONE_RTH.parquet"
    events_path = OLD / "data/consumed_price_events.parquet"
    calendar_path = JOINT / "data/calendar.parquet"
    source_receipts_path = OLD / "data/PRICE_SOURCE_RECEIPTS.json"
    prices = pd.read_parquet(prices_path)
    p02 = one(prices.loc[prices.ticker.eq("CRWD") & prices.trade_date.eq("2026-07-02")], "07-02 original price")
    p06 = one(prices.loc[prices.ticker.eq("CRWD") & prices.trade_date.eq("2026-07-06")], "07-06 original price")
    assert np.isclose(p02.open, first.open, atol=1e-7, rtol=0)
    assert np.isclose(p02.close, first.close, atol=1e-7, rtol=0)
    calendar = pd.read_parquet(calendar_path)
    sessions = calendar.loc[
        calendar.is_test.astype(bool)
        & calendar.trade_date.between("2026-07-02", "2026-07-06"), "trade_date"
    ]
    assert list(sessions) == [pd.Timestamp("2026-07-02"), pd.Timestamp("2026-07-06")]

    events = pd.read_parquet(events_path)
    applied = events.loc[
        events.audit_kind.eq("APPLIED_CORPORATE_ACTION") & events.code.eq("US.CRWD")
    ].copy()
    applied["event_date"] = pd.to_datetime(applied.event_date)
    assert len(applied) == 1
    split = one(applied.loc[applied.event_date.eq("2026-07-02")], "split event")
    assert bool(split.share_event) and float(split.factor_a) == 0.25 and float(split.factor_b) == 0
    assert not bool(split.aligned_to_next_session)

    raw_sha = sha(raw_path)
    assert raw_sha == prior["input_sha256"]["raw"]["sha256"]
    receipts = json.loads(source_receipts_path.read_text(encoding="utf-8"))
    receipt = next(x for x in receipts if x["original_code"] == "US.CRWD")
    matching_raw = [x for x in receipt["paths"] if Path(x["path"]).name == raw_path.name]
    assert len(matching_raw) == 1 and matching_raw[0]["sha256"] == raw_sha
    raw = pd.read_parquet(raw_path)
    raw["trade_date"] = pd.to_datetime(raw.trade_date)
    r02 = one(raw.loc[raw.code.eq("US.CRWD") & raw.trade_date.eq("2026-07-02")], "07-02 Raw")
    r06 = one(raw.loc[raw.code.eq("US.CRWD") & raw.trade_date.eq("2026-07-06")], "07-06 Raw")
    assert p06.original_transport == p06.transport_used == "US.CRWD"
    assert p06.price_coordinate == "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN"
    assert bool(p06.unresolved_event_on_or_before) and bool(p06.price_quality_warning)
    assert not bool(p06.lifecycle_ended) and not bool(p06.extreme_adjusted_jump)
    assert float(r06.last_close) == float(r02.close)
    for field in ("open", "close"):
        assert np.isfinite(float(r06[field])) and float(r06[field]) > 0
        assert np.isclose(float(p06[f"raw_{field}"]), float(r06[field]), atol=1e-7, rtol=0)
        assert np.isclose(float(p06[field]), float(r06[field]) / 0.25, atol=1e-7, rtol=0)
    assert np.isfinite(float(r06.volume)) and float(r06.volume) > 0
    assert np.isclose(float(p06.volume), float(r06.volume) * 0.25, atol=1e-7, rtol=0)

    checkpoints = []
    for cost in (5, 10, 25):
        path = REPLAY / f"joint_logistic_{cost}bps/CHECKPOINT.json"
        cp = json.loads(path.read_text(encoding="utf-8"))
        assert cp["certified_through"] == "2026-07-02" and cp["next_date"] == "2026-07-06"
        needs = [x for x in cp["next_required_inputs"] if x["ticker"] == "CRWD"]
        assert {x["field"] for x in needs} == {"open", "close"}
        assert {x["purpose"] for x in needs} == {
            "held_position_pretrade_nav_or_exit", "requested_position_sell", "actual_held_position_valuation"
        }
        assert all(x["date"] == "2026-07-06" for x in needs)
        assert float(cp["holdings"]["CRWD"]["index_units"]) > 0
        assert np.isclose(float(cp["holdings"]["CRWD"]["mark"]), float(first.close), atol=1e-7, rtol=0)
        checkpoints.append({
            "run_id": cp["run_id"], "path": str(path), "sha256": sha(path),
            "certified_through": cp["certified_through"],
            "crwd_held_index_units": float(cp["holdings"]["CRWD"]["index_units"]),
            "demand_purposes": sorted({x["purpose"] for x in needs}),
        })

    row = {
        "ticker": "CRWD", "trade_date": "2026-07-06",
        "open_authorized": True, "close_authorized": True,
        "evidence_id": "ROUND2_CRWD_2026-07-02_SPLIT_CONTINUED_TO_2026-07-06_ACCOUNT_FIELDS",
        "open": float(p06.open), "close": float(p06.close),
        "candidate_pool_version": "R6_UNCHANGED", "next_unproved_event_exclusive": "",
        "fixed_raw_sha256": raw_sha,
    }
    csv_path = HERE / "ROUND2_CRWD_0706_ACCOUNT_PRICE_FIELDS.csv"
    parquet_path = HERE / "ROUND2_CRWD_0706_ACCOUNT_PRICE_FIELDS.parquet"
    pd.DataFrame([row]).to_csv(csv_path, index=False)
    pd.DataFrame([row]).to_parquet(parquet_path, index=False)
    proof = {
        "status": "CURRENT_2026_07_06_CRWD_SPLIT_CONTINUATION_FIELDS_PROVEN",
        "scope": "ONLY_CRWD_2026_07_06_V16_LOGISTIC_ACTUAL_ACCOUNT_OPEN_AND_CLOSE",
        "prior_2026_07_02_proof": {"path": str(PRIOR_PROOF), "sha256": sha(PRIOR_PROOF),
                                   "approved_csv_sha256": sha(PRIOR_FIELDS)},
        "issuer_pre_event_source": prior["issuer_pre_event_source"],
        "security": prior["security"],
        "original_split_event": {"date": "2026-07-02", "factor_a": 0.25, "factor_b": 0,
                                 "no_new_consumed_event_through": "2026-07-06"},
        "calendar_sessions": [x.date().isoformat() for x in sessions],
        "raw_2026_07_06": {"open": float(r06.open), "close": float(r06.close), "volume": float(r06.volume)},
        "original_index_coordinate_2026_07_06": {"open": float(p06.open), "close": float(p06.close),
                                                 "volume": float(p06.volume)},
        "index_transform": "adjusted_open_close = raw_open_close / 0.25; adjusted_volume = raw_volume * 0.25",
        "price_coordinate": "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN",
        "candidate_pool_version": "R6_UNCHANGED",
        "authorization_end_exclusive": "2026-07-07; no later day approved or implied",
        "checkpoint_receipts": checkpoints,
        "input_sha256": {str(path): sha(path) for path in (
            prices_path, raw_path, events_path, calendar_path, source_receipts_path
        )},
        "output_sha256": {csv_path.name: sha(csv_path), parquet_path.name: sha(parquet_path)},
        "model_fit_calls": 0, "preprocessor_fit_calls": 0, "account_replay_calls": 0,
    }
    json_path = HERE / "ROUND2_CRWD_0706_PROOF.json"
    json_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": proof["status"], "approved_ticker_dates": 1,
                      "csv_sha256": proof["output_sha256"][csv_path.name]}))


if __name__ == "__main__":
    main()
