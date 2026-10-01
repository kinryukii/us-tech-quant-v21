"""Single-day MU cash-event coordinate continuation for V18 RL-zero."""

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
REPLAY = JOINT / "continuation_account_repair_r1/replay/repair_r2_v18_bac_mu_6"
PRIOR_PROOF = HERE / "ROUND2_MU_0330_PROOF.json"
PRIOR_FIELDS = HERE / "ROUND2_MU_0330_ACCOUNT_PRICE_FIELDS.csv"


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
    assert prior["status"] == "CURRENT_2026_03_30_MU_FIELDS_PROVEN"
    assert prior["scope"] == "ONLY_MU_2026_03_30_V15_RL_ZERO_ACTUAL_ACCOUNT_OPEN_AND_CLOSE"
    assert sha(PRIOR_FIELDS) == prior["output_sha256"][PRIOR_FIELDS.name]
    for item in prior["input_sha256"].values():
        assert sha(Path(item["path"])) == item["sha256"]
    p30_approved = one(pd.read_csv(PRIOR_FIELDS), "03-30 approved field")
    assert p30_approved.ticker == "MU" and p30_approved.trade_date == "2026-03-30"
    assert bool(p30_approved.open_authorized) and bool(p30_approved.close_authorized)
    assert p30_approved.candidate_pool_version == "R6_UNCHANGED"

    paths = {
        "prices": JOINT / "data/test_prices.parquet",
        "raw": STAGE / "fixed_window_raw/RAW_US_MU_K_DAY_NONE_RTH.parquet",
        "events": OLD / "data/consumed_price_events.parquet",
        "calendar": JOINT / "data/calendar.parquet",
        "source_receipts": OLD / "data/PRICE_SOURCE_RECEIPTS.json",
        "initial_state": STAGE / "identity_feature_application_r1/CONSUMED_2026_INITIAL_ADJUSTMENT_STATE.csv",
    }
    prices = pd.read_parquet(paths["prices"])
    p30 = one(prices.loc[prices.ticker.eq("MU") & prices.trade_date.eq("2026-03-30")], "03-30 original price")
    p31 = one(prices.loc[prices.ticker.eq("MU") & prices.trade_date.eq("2026-03-31")], "03-31 original price")
    assert np.isclose(float(p30.open), float(p30_approved.open), atol=1e-7, rtol=0)
    assert np.isclose(float(p30.close), float(p30_approved.close), atol=1e-7, rtol=0)
    calendar = pd.read_parquet(paths["calendar"])
    sessions = calendar.loc[
        calendar.is_test.astype(bool)
        & calendar.trade_date.between("2026-03-30", "2026-03-31"), "trade_date"
    ]
    assert list(sessions) == [pd.Timestamp("2026-03-30"), pd.Timestamp("2026-03-31")]

    events = pd.read_parquet(paths["events"])
    applied = events.loc[
        events.audit_kind.eq("APPLIED_CORPORATE_ACTION") & events.code.eq("US.MU")
    ].copy()
    applied["event_date"] = pd.to_datetime(applied.event_date)
    cash = one(applied.loc[applied.event_date.eq("2026-03-30")], "cash event")
    assert float(cash.factor_a) == 0.99958 and float(cash.factor_b) == 0
    assert not bool(cash.share_event) and not bool(cash.aligned_to_next_session)
    assert not applied.event_date.eq("2026-03-31").any()
    assert applied.loc[applied.event_date.gt("2026-03-30"), "event_date"].min() == pd.Timestamp("2026-07-06")

    initial = pd.read_csv(paths["initial_state"])
    state = one(initial.loc[initial.moomoo_transport_code.eq("US.MU")], "initial state")
    alpha0 = float(state.initial_alpha_2026_01_02)
    beta0 = float(state.initial_beta_2026_01_02)
    assert np.isfinite(alpha0) and alpha0 > 0 and beta0 == 0
    assert np.isclose(float(p30.open), alpha0 / 0.99958 * float(p30.raw_open), atol=1e-7, rtol=0)
    assert np.isclose(float(p30.close), alpha0 / 0.99958 * float(p30.raw_close), atol=1e-7, rtol=0)

    raw_sha = sha(paths["raw"])
    receipt = next(x for x in json.loads(paths["source_receipts"].read_text(encoding="utf-8"))
                   if x["original_code"] == "US.MU")
    matching_raw = [x for x in receipt["paths"] if Path(x["path"]).name == paths["raw"].name]
    assert len(matching_raw) == 1 and matching_raw[0]["sha256"] == raw_sha
    raw = pd.read_parquet(paths["raw"])
    raw["trade_date"] = pd.to_datetime(raw.trade_date)
    r30 = one(raw.loc[raw.code.eq("US.MU") & raw.trade_date.eq("2026-03-30")], "03-30 Raw")
    r31 = one(raw.loc[raw.code.eq("US.MU") & raw.trade_date.eq("2026-03-31")], "03-31 Raw")
    assert p31.original_transport == p31.transport_used == "US.MU"
    assert p31.price_coordinate == "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN"
    assert bool(p31.unresolved_event_on_or_before) and bool(p31.price_quality_warning)
    assert not bool(p31.lifecycle_ended) and not bool(p31.extreme_adjusted_jump)
    assert float(r31.last_close) == float(r30.close)
    for field in ("open", "close"):
        assert np.isfinite(float(r31[field])) and float(r31[field]) > 0
        assert np.isclose(float(p31[f"raw_{field}"]), float(r31[field]), atol=1e-7, rtol=0)
        assert np.isclose(float(p31[field]), alpha0 / 0.99958 * float(r31[field]) + beta0, atol=1e-7, rtol=0)
    assert np.isfinite(float(r31.volume)) and float(r31.volume) > 0
    assert np.isclose(float(p31.volume), float(r31.volume), atol=1e-7, rtol=0)

    checkpoints = []
    for cost in (5, 10, 25):
        path = REPLAY / f"joint_rl_zero_control_{cost}bps/CHECKPOINT.json"
        cp = json.loads(path.read_text(encoding="utf-8"))
        assert cp["certified_through"] == "2026-03-30" and cp["next_date"] == "2026-03-31"
        needs = [x for x in cp["next_required_inputs"] if x["ticker"] == "MU"]
        assert {x["field"] for x in needs} == {"open", "close"}
        assert {x["purpose"] for x in needs} == {
            "held_position_pretrade_nav_or_exit", "requested_position_sell", "actual_held_position_valuation"
        }
        assert all(x["date"] == "2026-03-31" for x in needs)
        assert float(cp["holdings"]["MU"]["index_units"]) > 0
        assert np.isclose(float(cp["holdings"]["MU"]["mark"]), float(p30_approved.close), atol=1e-7, rtol=0)
        checkpoints.append({
            "run_id": cp["run_id"], "path": str(path), "sha256": sha(path),
            "certified_through": cp["certified_through"],
            "mu_held_index_units": float(cp["holdings"]["MU"]["index_units"]),
            "demand_purposes": sorted({x["purpose"] for x in needs}),
        })

    row = {
        "ticker": "MU", "trade_date": "2026-03-31",
        "open_authorized": True, "close_authorized": True,
        "evidence_id": "ROUND2_MU_2026-03-30_CASH_EVENT_CONTINUED_TO_2026-03-31_ACCOUNT_FIELDS",
        "open": float(p31.open), "close": float(p31.close),
        "candidate_pool_version": "R6_UNCHANGED", "next_unproved_event_exclusive": "2026-07-06",
        "fixed_raw_sha256": raw_sha,
    }
    csv_path = HERE / "ROUND2_MU_0331_ACCOUNT_PRICE_FIELDS.csv"
    parquet_path = HERE / "ROUND2_MU_0331_ACCOUNT_PRICE_FIELDS.parquet"
    pd.DataFrame([row]).to_csv(csv_path, index=False)
    pd.DataFrame([row]).to_parquet(parquet_path, index=False)
    proof = {
        "status": "CURRENT_2026_03_31_MU_CASH_CONTINUATION_FIELDS_PROVEN",
        "scope": "ONLY_MU_2026_03_31_V18_RL_ZERO_ACTUAL_ACCOUNT_OPEN_AND_CLOSE",
        "prior_2026_03_30_proof": {"path": str(PRIOR_PROOF), "sha256": sha(PRIOR_PROOF),
                                   "approved_csv_sha256": sha(PRIOR_FIELDS)},
        "issuer_pre_event_source": prior["issuer_pre_event_source"],
        "security": prior["security"],
        "original_cash_event": {"date": "2026-03-30", "factor_a": 0.99958, "factor_b": 0,
                                "no_new_consumed_event_through": "2026-03-31",
                                "next_event_exclusive": "2026-07-06"},
        "calendar_sessions": [x.date().isoformat() for x in sessions],
        "raw_2026_03_31": {"open": float(r31.open), "close": float(r31.close), "volume": float(r31.volume)},
        "original_index_coordinate_2026_03_31": {"open": float(p31.open), "close": float(p31.close),
                                                 "volume": float(p31.volume)},
        "index_transform": "adjusted_open_close = initial_alpha / 0.99958 * raw_open_close + initial_beta; volume unchanged",
        "price_coordinate": "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN",
        "candidate_pool_version": "R6_UNCHANGED",
        "authorization_end_exclusive": "2026-04-01; no later day approved or implied",
        "checkpoint_receipts": checkpoints,
        "input_sha256": {str(path): sha(path) for path in paths.values()},
        "output_sha256": {csv_path.name: sha(csv_path), parquet_path.name: sha(parquet_path)},
        "model_fit_calls": 0, "preprocessor_fit_calls": 0, "account_replay_calls": 0,
    }
    json_path = HERE / "ROUND2_MU_0331_PROOF.json"
    json_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": proof["status"], "approved_ticker_dates": 1,
                      "csv_sha256": proof["output_sha256"][csv_path.name]}))


if __name__ == "__main__":
    main()
