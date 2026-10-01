"""Single-day CRWD split price and volume proof for actual V14 account demand."""

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
VENDOR = Path(r"D:\us-tech-quant-cache\13f_pit_v1\a_a2_quarterly_13f_r1")
REPLAY = JOINT / "continuation_account_repair_r1/replay/repair_r2_v14_or_rrx_0401_3"


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
    paths = {
        "prices": JOINT / "data/test_prices.parquet",
        "consumed_events": OLD / "data/consumed_price_events.parquet",
        "security_identity": STAGE / "r4_event_pit/EVENT_SECURITY_PRIORITY.csv",
        "event_priority": STAGE / "r4_event_pit/ALL_1094_EVENT_PRIORITY.csv",
        "initial_state": STAGE / "identity_feature_application_r1/CONSUMED_2026_INITIAL_ADJUSTMENT_STATE.csv",
        "raw": STAGE / "fixed_window_raw/RAW_US_CRWD_K_DAY_NONE_RTH.parquet",
        "source_receipts": OLD / "data/PRICE_SOURCE_RECEIPTS.json",
        "vendor_rehab": VENDOR / "rehab_factors.parquet",
        "vendor_status": VENDOR / "rehab_status.csv",
    }
    hashes = {name: {"path": str(path), "sha256": sha(path)} for name, path in paths.items()}
    identity = pd.read_csv(paths["security_identity"], dtype={"cusip": str})
    match = identity.loc[
        identity.transport_code.eq("US.CRWD") & identity.source_event_date.eq("2026-07-02")
    ]
    assert len(match) >= 1 and set(match.cusip) == {"22788C105"}
    assert set(match.title_of_class) == {"CL A"}
    assert match.share_event.eq(True).all() and match.factor_a.eq(0.25).all()
    assert match.factor_b.eq(0).all() and match.aligned_to_next_session.eq(False).all()
    priority = pd.read_csv(paths["event_priority"])
    audit = one(priority.loc[
        priority.code.eq("US.CRWD") & priority.source_event_date.eq("2026-07-02")
    ], "original event priority")
    assert audit.event_date == "2026-07-02" and bool(audit.share_event)
    assert float(audit.factor_a) == 0.25 and float(audit.factor_b) == 0
    assert float(audit.prior_raw_close) == 772.74

    vendor = pd.read_parquet(paths["vendor_rehab"])
    split = one(vendor.loc[
        vendor.code.eq("US.CRWD") & vendor.ex_div_date.eq("2026-07-02")
    ], "original vendor split")
    assert float(split.split_base) == 1.0 and float(split.split_ert) == 4.0
    assert float(split.split_ratio) == 0.25
    assert float(split.forward_adj_factorA) == 0.25 and float(split.forward_adj_factorB) == 0
    vendor_status = pd.read_csv(paths["vendor_status"])
    vstatus = one(vendor_status.loc[vendor_status.code.eq("US.CRWD")], "vendor status")
    assert vstatus.status == "PASS" and int(vstatus.row_count) == 1

    events = pd.read_parquet(paths["consumed_events"])
    applied = events.loc[
        events.audit_kind.eq("APPLIED_CORPORATE_ACTION") & events.code.eq("US.CRWD")
    ].copy()
    applied["event_date"] = pd.to_datetime(applied.event_date)
    assert len(applied) == 1
    event = one(applied.loc[applied.event_date.eq("2026-07-02")], "consumed event")
    assert pd.Timestamp(event.source_event_date) == pd.Timestamp("2026-07-02")
    assert not bool(event.aligned_to_next_session) and bool(event.share_event)
    assert float(event.factor_a) == 0.25 and float(event.factor_b) == 0

    initial = pd.read_csv(paths["initial_state"])
    state = one(initial.loc[initial.moomoo_transport_code.eq("US.CRWD")], "initial state")
    assert float(state.initial_alpha_2026_01_02) == 1.0
    assert float(state.initial_beta_2026_01_02) == 0.0
    assert int(state.consumed_prior_events) == 0

    source_receipts = json.loads(paths["source_receipts"].read_text(encoding="utf-8"))
    receipt = next(x for x in source_receipts if x["original_code"] == "US.CRWD")
    assert receipt["ticker"] == "CRWD" and receipt["transport"] == "US.CRWD"
    matching_raw = [x for x in receipt["paths"] if Path(x["path"]).name == paths["raw"].name]
    assert len(matching_raw) == 1 and matching_raw[0]["sha256"] == hashes["raw"]["sha256"]

    prices = pd.read_parquet(paths["prices"])
    p01 = one(prices.loc[prices.ticker.eq("CRWD") & prices.trade_date.eq("2026-07-01")], "07-01 price")
    p02 = one(prices.loc[prices.ticker.eq("CRWD") & prices.trade_date.eq("2026-07-02")], "07-02 price")
    raw = pd.read_parquet(paths["raw"])
    raw["trade_date"] = pd.to_datetime(raw.trade_date)
    r01 = one(raw.loc[raw.code.eq("US.CRWD") & raw.trade_date.eq("2026-07-01")], "07-01 raw")
    r02 = one(raw.loc[raw.code.eq("US.CRWD") & raw.trade_date.eq("2026-07-02")], "07-02 raw")
    assert p01.original_transport == p01.transport_used == "US.CRWD"
    assert p02.original_transport == p02.transport_used == "US.CRWD"
    assert p01.price_coordinate == p02.price_coordinate == "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN"
    assert not bool(p01.price_quality_warning)
    assert bool(p02.unresolved_event_on_or_before) and bool(p02.price_quality_warning)
    assert not bool(p02.lifecycle_ended) and not bool(p02.extreme_adjusted_jump)
    assert np.isclose(float(p01.close), float(r01.close), atol=1e-7, rtol=0)
    assert np.isclose(float(p01.raw_close), float(r01.close), atol=1e-7, rtol=0)
    assert np.isclose(float(r02.last_close), float(r01.close), atol=1e-7, rtol=0)
    for label in ("open", "close"):
        assert np.isfinite(float(r02[label])) and float(r02[label]) > 0
        assert np.isclose(float(p02[f"raw_{label}"]), float(r02[label]), atol=1e-7, rtol=0)
        assert np.isclose(float(p02[label]), float(r02[label]) / 0.25, atol=1e-7, rtol=0)
    assert np.isfinite(float(r02.volume)) and float(r02.volume) > 0
    assert np.isclose(float(p02.volume), float(r02.volume) * 0.25, atol=1e-7, rtol=0)

    checkpoint_receipts = []
    for cost in (5, 10, 25):
        path = REPLAY / f"joint_logistic_{cost}bps/CHECKPOINT.json"
        cp = json.loads(path.read_text(encoding="utf-8"))
        assert cp["certified_through"] == "2026-07-01" and cp["next_date"] == "2026-07-02"
        needs = [x for x in cp["next_required_inputs"] if x["ticker"] == "CRWD"]
        assert {x["field"] for x in needs} == {"open", "close"}
        assert {x["purpose"] for x in needs} == {
            "held_position_pretrade_nav_or_exit", "requested_target_buy", "actual_held_position_valuation"
        }
        assert all(x["date"] == "2026-07-02" for x in needs)
        assert float(cp["holdings"]["CRWD"]["index_units"]) > 0
        checkpoint_receipts.append({
            "run_id": cp["run_id"], "path": str(path), "sha256": sha(path),
            "certified_through": cp["certified_through"],
            "crwd_held_index_units": float(cp["holdings"]["CRWD"]["index_units"]),
            "demand_purposes": sorted({x["purpose"] for x in needs}),
        })

    row = {
        "ticker": "CRWD", "trade_date": "2026-07-02",
        "open_authorized": True, "close_authorized": True,
        "evidence_id": "ROUND2_CRWD_2026-07-02_4FOR1_SPLIT_ACCOUNT_FIELDS",
        "open": float(p02.open), "close": float(p02.close),
        "candidate_pool_version": "R6_UNCHANGED",
        "next_unproved_event_exclusive": "",
        "fixed_raw_sha256": hashes["raw"]["sha256"],
    }
    csv_path = HERE / "ROUND2_CRWD_0702_ACCOUNT_PRICE_FIELDS.csv"
    parquet_path = HERE / "ROUND2_CRWD_0702_ACCOUNT_PRICE_FIELDS.parquet"
    pd.DataFrame([row]).to_csv(csv_path, index=False)
    pd.DataFrame([row]).to_parquet(parquet_path, index=False)
    manifest = {
        "status": "CURRENT_2026_07_02_CRWD_SPLIT_FIELDS_PROVEN",
        "scope": "ONLY_CRWD_2026_07_02_V14_LOGISTIC_ACTUAL_ACCOUNT_OPEN_AND_CLOSE",
        "issuer_pre_event_source": {
            "form": "8-K", "accession": "0001535527-26-000022",
            "sec_accepted": "2026-06-03 16:06:20 ET",
            "url": "https://www.sec.gov/Archives/edgar/data/1535527/000153552726000022/crwd-20260603.htm",
            "class": "Class A common stock", "record_date": "2026-06-25",
            "distribution_after_close": "2026-07-01", "ex_split_trade_date": "2026-07-02",
            "split_base": 1, "split_result": 4, "issuer_bytes_archived": False,
        },
        "security": {"ticker": "CRWD", "cusip": "22788C105", "class": "CL A"},
        "original_consumed_factor_a": 0.25, "original_consumed_factor_b": 0,
        "raw_2026_07_02": {"open": float(r02.open), "close": float(r02.close), "volume": float(r02.volume)},
        "original_index_coordinate_2026_07_02": {"open": float(p02.open), "close": float(p02.close), "volume": float(p02.volume)},
        "index_transform": "adjusted_open_close = raw_open_close / 0.25; adjusted_volume = raw_volume * 0.25",
        "price_coordinate": "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN",
        "candidate_pool_version": "R6_UNCHANGED",
        "authorization_end_exclusive": "2026-07-03; no later day approved or implied",
        "checkpoint_receipts": checkpoint_receipts,
        "input_sha256": hashes,
        "output_sha256": {csv_path.name: sha(csv_path), parquet_path.name: sha(parquet_path)},
        "model_fit_calls": 0, "preprocessor_fit_calls": 0, "account_replay_calls": 0,
    }
    json_path = HERE / "ROUND2_CRWD_0702_PROOF.json"
    json_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "approved_ticker_dates": 1,
                      "csv_sha256": manifest["output_sha256"][csv_path.name]}))


if __name__ == "__main__":
    main()
