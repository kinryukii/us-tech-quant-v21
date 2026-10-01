"""Authorize only the actual MU 2026-03-30 V15 account fields."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from build_first_four_account_fields import main as check_first_event_interval, sha


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
JOINT = ROOT / "a2_complete_suite_nearest_effective_20260927"
OLD = ROOT / "a2_complete_suite_20260927"
STAGE = ROOT / "a2_strict_method_retrain_20260926/test2026_stage"
VENDOR = Path(r"D:\us-tech-quant-cache\13f_pit_v1\a_a2_quarterly_13f_r1")
REPLAY = JOINT / "continuation_account_repair_r1/replay/repair_r2_v15_amkr_0313_3"
EVENT = {
    "MU": {
        "cusip": "595112103", "first": "2026-03-30", "next": "2026-07-06",
        "public": "2026-03-18", "cash": 0.15,
        "issuer_url": "https://www.sec.gov/Archives/edgar/data/723125/000072312526000004/a2026q2ex991-pressrelease.htm",
    }
}


def one(frame: pd.DataFrame, label: str) -> pd.Series:
    assert len(frame) == 1, (label, len(frame))
    return frame.iloc[0]


def main() -> None:
    stem = "ROUND2_MU_0330_STAGING"
    staged = [
        HERE / f"{stem}_EVENT_ACCOUNT_PRICE_FIELDS.csv",
        HERE / f"{stem}_EVENT_ACCOUNT_PRICE_FIELDS.parquet",
        HERE / f"{stem}_PROOF.json",
    ]
    try:
        check_first_event_interval(EVENT, stem)
        full = pd.read_parquet(staged[1])
        parent_proof = json.loads(staged[2].read_text(encoding="utf-8"))
        assert len(full) == parent_proof["total_unique_ticker_dates"]
        assert full.ticker.eq("MU").all() and full.trade_date.min() == pd.Timestamp("2026-03-30")
        assert full.trade_date.max() < pd.Timestamp("2026-07-06")
        current = full.loc[full.trade_date.eq("2026-03-30")].copy()
        assert len(current) == 1 and bool(current.open_authorized.iloc[0]) and bool(current.close_authorized.iloc[0])

        initial_path = STAGE / "identity_feature_application_r1/CONSUMED_2026_INITIAL_ADJUSTMENT_STATE.csv"
        initial = pd.read_csv(initial_path)
        state = one(initial.loc[initial.moomoo_transport_code.eq("US.MU")], "MU initial state")
        alpha0, beta0 = float(state.initial_alpha_2026_01_02), float(state.initial_beta_2026_01_02)
        assert np.isfinite(alpha0) and alpha0 > 0 and beta0 == 0
        assert int(state.consumed_prior_events) == 18
        prices = pd.read_parquet(JOINT / "data/test_prices.parquet")
        before = one(prices.loc[prices.ticker.eq("MU") & prices.trade_date.eq("2026-03-27")], "03-27 price")
        after = one(prices.loc[prices.ticker.eq("MU") & prices.trade_date.eq("2026-03-30")], "03-30 price")
        assert not bool(before.price_quality_warning)
        assert np.isclose(before.open, alpha0 * before.raw_open + beta0, atol=1e-7, rtol=0)
        assert np.isclose(before.close, alpha0 * before.raw_close + beta0, atol=1e-7, rtol=0)
        assert float(before.raw_close) == 357.22
        assert np.isclose(after.open, alpha0 / 0.99958 * after.raw_open + beta0, atol=1e-7, rtol=0)
        assert np.isclose(after.close, alpha0 / 0.99958 * after.raw_close + beta0, atol=1e-7, rtol=0)
        assert float(after.volume) == 73833238.0

        vendor_path = VENDOR / "rehab_factors.parquet"
        vendor_status_path = VENDOR / "rehab_status.csv"
        vendor = pd.read_parquet(vendor_path)
        v = one(vendor.loc[vendor.code.eq("US.MU") & vendor.ex_div_date.eq("2026-03-30")], "vendor MU event")
        assert float(v.per_cash_div) == 0.15
        assert float(v.forward_adj_factorA) == 0.99958 and float(v.forward_adj_factorB) == 0
        status = pd.read_csv(vendor_status_path)
        vs = one(status.loc[status.code.eq("US.MU")], "vendor status")
        assert vs.status == "PASS" and int(vs.row_count) == 21

        checkpoints = []
        for cost in (5, 10, 25):
            path = REPLAY / f"joint_rl_zero_control_{cost}bps/CHECKPOINT.json"
            cp = json.loads(path.read_text(encoding="utf-8"))
            assert cp["certified_through"] == "2026-03-27" and cp["next_date"] == "2026-03-30"
            needs = [x for x in cp["next_required_inputs"] if x["ticker"] == "MU"]
            assert {x["field"] for x in needs} == {"open", "close"}
            assert {x["purpose"] for x in needs} == {
                "held_position_pretrade_nav_or_exit", "requested_target_buy", "actual_held_position_valuation"
            }
            assert all(x["date"] == "2026-03-30" for x in needs)
            assert float(cp["holdings"]["MU"]["index_units"]) > 0
            checkpoints.append({
                "run_id": cp["run_id"], "path": str(path), "sha256": sha(path),
                "certified_through": cp["certified_through"],
                "mu_held_index_units": float(cp["holdings"]["MU"]["index_units"]),
                "demand_purposes": sorted({x["purpose"] for x in needs}),
            })

        csv_path = HERE / "ROUND2_MU_0330_ACCOUNT_PRICE_FIELDS.csv"
        parquet_path = HERE / "ROUND2_MU_0330_ACCOUNT_PRICE_FIELDS.parquet"
        current.to_csv(csv_path, index=False)
        current.to_parquet(parquet_path, index=False)
        proof = {
            "status": "CURRENT_2026_03_30_MU_FIELDS_PROVEN",
            "scope": "ONLY_MU_2026_03_30_V15_RL_ZERO_ACTUAL_ACCOUNT_OPEN_AND_CLOSE",
            "issuer_pre_event_source": {
                "form": "8-K Exhibit 99.1", "accession": "0000723125-26-000004",
                "sec_accepted": "2026-03-18 16:02:14 ET",
                "url": EVENT["MU"]["issuer_url"], "record_date": "2026-03-30",
                "cash_per_common_share": 0.15, "issuer_bytes_archived": False,
            },
            "security": {"ticker": "MU", "cusip": "595112103", "class": "COM"},
            "original_event": {"source_and_apply_date": "2026-03-30", "factor_a": 0.99958,
                               "factor_b": 0, "next_unproved_event_exclusive": "2026-07-06",
                               "prior_raw_close": 357.22},
            "initial_adjustment_state": {"alpha": alpha0, "beta": beta0,
                                         "consumed_prior_events": int(state.consumed_prior_events)},
            "raw_current": {"open": float(after.raw_open), "close": float(after.raw_close), "volume": float(after.volume)},
            "original_adjusted_current": {"open": float(after.open), "close": float(after.close)},
            "price_coordinate": "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN",
            "candidate_pool_version": "R6_UNCHANGED",
            "full_first_event_interval_checked_days_but_not_whitelisted": len(full),
            "actual_checkpoint_demands": checkpoints,
            "input_sha256": parent_proof["input_sha256"] | {
                "initial_state": {"path": str(initial_path), "sha256": sha(initial_path)},
                "vendor_rehab": {"path": str(vendor_path), "sha256": sha(vendor_path)},
                "vendor_status": {"path": str(vendor_status_path), "sha256": sha(vendor_status_path)},
            },
            "output_sha256": {csv_path.name: sha(csv_path), parquet_path.name: sha(parquet_path)},
            "model_fit_calls": 0, "preprocessor_fit_calls": 0, "account_replay_calls": 0,
        }
        json_path = HERE / "ROUND2_MU_0330_PROOF.json"
        json_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": proof["status"], "authorized_ticker_dates": 1,
                          "csv_sha256": proof["output_sha256"][csv_path.name]}))
    finally:
        for path in staged:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
