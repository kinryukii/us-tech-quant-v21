"""Read-only GLW 2026-02-26/27 ex-date conflict receipt; no replay or fit."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
JOINT = ROOT / "a2_complete_suite_nearest_effective_20260927"
OLD = ROOT / "a2_complete_suite_20260927"
STAGE = ROOT / "a2_strict_method_retrain_20260926/test2026_stage"
VENDOR = Path(r"D:\us-tech-quant-cache\13f_pit_v1\a_a2_quarterly_13f_r1")
CHECKPOINTS = JOINT / "continuation_account_repair_r1/replay/repair_r2_glw_conflict_quarantine_3"


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
        "original_vendor_get_rehab_saved_frame": VENDOR / "rehab_factors.parquet",
        "original_vendor_get_rehab_status": VENDOR / "rehab_status.csv",
        "fixed_same_source_raw": STAGE / "fixed_window_raw/RAW_US_GLW_K_DAY_NONE_RTH.parquet",
        "fixed_source_receipts": OLD / "data/PRICE_SOURCE_RECEIPTS.json",
        "saved_joint_price_frame": JOINT / "data/test_prices.parquet",
        "original_consumed_events": OLD / "data/consumed_price_events.parquet",
        "original_event_security_identity": STAGE / "r4_event_pit/EVENT_SECURITY_PRIORITY.csv",
        "initial_adjustment_state": STAGE / "identity_feature_application_r1/CONSUMED_2026_INITIAL_ADJUSTMENT_STATE.csv",
    }
    for cost in (5, 10, 25):
        paths[f"paused_hgb_{cost}bps_checkpoint"] = (
            CHECKPOINTS / f"hgb_return_baseline_{cost}bps/CHECKPOINT.json"
        )
    source_hashes = {name: {"path": str(path), "sha256": sha(path)} for name, path in paths.items()}

    vendor = pd.read_parquet(paths["original_vendor_get_rehab_saved_frame"])
    event = one(vendor.loc[
        vendor.code.eq("US.GLW")
        & pd.to_datetime(vendor.ex_div_date).eq(pd.Timestamp("2026-02-27"))
    ], "original GLW get_rehab row")
    assert float(event.per_cash_div) == 0.28
    assert float(event.forward_adj_factorA) == 0.99813
    assert float(event.forward_adj_factorB) == 0.0
    assert not (vendor.code.eq("US.GLW") & pd.to_datetime(vendor.ex_div_date).eq("2026-02-26")).any()
    status = pd.read_csv(paths["original_vendor_get_rehab_status"])
    vendor_status = one(status.loc[status.code.eq("US.GLW")], "vendor status")
    assert vendor_status.status == "PASS" and int(vendor_status.row_count) == 95

    identity = pd.read_csv(paths["original_event_security_identity"], dtype={"cusip": str})
    id_rows = identity.loc[
        identity.transport_code.eq("US.GLW")
        & identity.source_event_date.eq("2026-02-27")
    ]
    assert len(id_rows) >= 1 and set(id_rows.cusip) == {"219350105"}
    assert set(id_rows.title_of_class) == {"COM"}
    assert id_rows.share_event.eq(False).all() and id_rows.factor_a.eq(0.99813).all()
    assert id_rows.total_cash_div.eq(0.28).all()

    initial = pd.read_csv(paths["initial_adjustment_state"])
    state = one(initial.loc[initial.moomoo_transport_code.eq("US.GLW")], "GLW initial state")
    alpha0 = float(state.initial_alpha_2026_01_02)
    beta0 = float(state.initial_beta_2026_01_02)
    assert alpha0 > 0 and np.isfinite(alpha0) and beta0 == 0.0
    consumed = pd.read_parquet(paths["original_consumed_events"])
    actions = consumed.loc[
        consumed.audit_kind.eq("APPLIED_CORPORATE_ACTION") & consumed.code.eq("US.GLW")
    ].copy()
    actions["event_date"] = pd.to_datetime(actions.event_date)
    assert not actions.event_date.between("2026-01-02", "2026-02-26").any()
    consumed_event = one(actions.loc[actions.event_date.eq("2026-02-27")], "original consumption")
    assert pd.Timestamp(consumed_event.source_event_date) == pd.Timestamp("2026-02-27")
    assert not bool(consumed_event.aligned_to_next_session)
    assert float(consumed_event.factor_a) == 0.99813 and float(consumed_event.factor_b) == 0
    next_event = actions.loc[actions.event_date.gt("2026-02-27"), "event_date"].min()
    assert next_event == pd.Timestamp("2026-05-29")

    receipts = json.loads(paths["fixed_source_receipts"].read_text(encoding="utf-8"))
    receipt = one(pd.DataFrame(receipts).loc[pd.DataFrame(receipts).original_code.eq("US.GLW")], "GLW receipt")
    matching = [item for item in receipt.paths if Path(item["path"]).name == paths["fixed_same_source_raw"].name]
    assert len(matching) == 1 and matching[0]["sha256"] == source_hashes["fixed_same_source_raw"]["sha256"]

    raw = pd.read_parquet(paths["fixed_same_source_raw"])
    raw["trade_date"] = pd.to_datetime(raw.trade_date)
    raw = raw.loc[raw.code.eq("US.GLW") & raw.trade_date.between("2026-02-25", "2026-02-27")]
    prices = pd.read_parquet(paths["saved_joint_price_frame"])
    prices = prices.loc[prices.ticker.eq("GLW") & prices.trade_date.between("2026-02-25", "2026-02-27")]
    assert len(raw) == len(prices) == 3
    assert not raw.duplicated("trade_date").any() and not prices.duplicated("trade_date").any()
    m = prices.merge(raw[["trade_date", "open", "close"]], on="trade_date", validate="one_to_one", suffixes=("", "_source"))
    assert np.allclose(m.raw_open, m.open_source, atol=1e-7, rtol=0)
    assert np.allclose(m.raw_close, m.close_source, atol=1e-7, rtol=0)
    assert m.original_transport.eq("US.GLW").all() and m.transport_used.eq("US.GLW").all()
    assert m.price_coordinate.eq("PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN").all()
    for field in ("open", "close", "raw_open", "raw_close"):
        assert np.isfinite(m[field]).all() and m[field].gt(0).all()
    before = one(m.loc[m.trade_date.eq("2026-02-25")], "02-25 saved price")
    d26 = one(m.loc[m.trade_date.eq("2026-02-26")], "02-26 saved price")
    d27 = one(m.loc[m.trade_date.eq("2026-02-27")], "02-27 saved price")
    assert not any((before.price_quality_warning, d26.price_quality_warning))
    assert bool(d27.price_quality_warning) and bool(d27.unresolved_event_on_or_before)
    for row in (before, d26):
        assert np.isclose(row.open, alpha0 * row.raw_open + beta0, atol=1e-7, rtol=0)
        assert np.isclose(row.close, alpha0 * row.raw_close + beta0, atol=1e-7, rtol=0)
    alpha27 = alpha0 / 0.99813
    assert np.isclose(d27.open, alpha27 * d27.raw_open + beta0, atol=1e-7, rtol=0)
    assert np.isclose(d27.close, alpha27 * d27.raw_close + beta0, atol=1e-7, rtol=0)
    assert float(d26.raw_close) == 150.30 and float(before.raw_close) == 160.43
    assert math.floor(((150.30 - 0.28) / 150.30) * 100000) / 100000 == 0.99813
    hypothetical_26_factor = math.floor(((160.43 - 0.28) / 160.43) * 100000) / 100000
    assert hypothetical_26_factor == 0.99825

    paused_paths = []
    for cost in (5, 10, 25):
        checkpoint = json.loads(paths[f"paused_hgb_{cost}bps_checkpoint"].read_text(encoding="utf-8"))
        assert checkpoint["certified_through"] == "2026-02-25"
        assert checkpoint["next_date"] == "2026-02-26"
        glw_needs = [x for x in checkpoint["next_required_inputs"] if x["ticker"] == "GLW"]
        assert {x["field"] for x in glw_needs} == {"open", "close"}
        assert {x["purpose"] for x in glw_needs} == {
            "held_position_pretrade_nav_or_exit", "requested_position_sell", "actual_held_position_valuation"
        }
        paused_paths.append({
            "run_id": checkpoint["run_id"],
            "certified_through": checkpoint["certified_through"],
            "next_date": checkpoint["next_date"],
            "glw_index_units_at_checkpoint": float(checkpoint["holdings"]["GLW"]["index_units"]),
            "glw_pending_target_weight": float(checkpoint["pending_recomputed_by_frozen_policy"]["targets_from_new_frozen_policy"]["GLW"]),
            "actual_next_input_purposes": sorted({x["purpose"] for x in glw_needs}),
        })

    blocked = []
    for row in (d26, d27):
        blocked.append({
            "ticker": "GLW", "trade_date": row.trade_date.date().isoformat(),
            "open_authorized": False, "close_authorized": False,
            "evidence_id": "GLW_20260226_VS_20260227_EXDATE_CONFLICT",
            "raw_open": float(row.raw_open), "raw_close": float(row.raw_close),
            "saved_adjusted_open": float(row.open), "saved_adjusted_close": float(row.close),
            "candidate_pool_version": "R6_UNCHANGED",
            "reason": "issuer_security_ex_date_conflicts_with_saved_original_vendor_ex_div_date; exchange_exception_absence_not_exhaustive_positive_security_proof",
        })
    csv_path = HERE / "ROUND2_GLW_ADJUDICATION_BLOCKED_FIELDS.csv"
    pd.DataFrame(blocked).to_csv(csv_path, index=False)
    receipt = {
        "status": "EX_DATE_CONFLICT_UNRESOLVED_NO_GLW_FIELDS_APPROVED",
        "earliest_affected_input": "GLW 2026-02-26 open",
        "blocked_ticker_dates": 2,
        "blocked_fields": 4,
        "scope_note": "Only the two current adjudication dates are enumerated; no later GLW adjustment suffix is approved by this receipt.",
        "issuer": {"ticker": "GLW", "cusip": "219350105", "class": "COM",
                   "cash": 0.28, "issuer_announcement_date": "2026-02-11",
                   "issuer_dividend_history_ex_date": "2026-02-26", "record_date": "2026-02-27"},
        "original_vendor": {"saved_get_rehab_ex_div_date": "2026-02-27", "forward_factor_a": 0.99813,
                            "forward_factor_b": 0.0, "saved_rows_for_glw": 95,
                            "historical_response_receipt_observed": False},
        "nyse_exception_report_observation": {
            "page": "https://www.nyse.com/trade/ex-date-dividends",
            "record_2026_02_27_filter": "one result MET PRA, GLW absent; ex-date filters blank",
            "coverage_crosscheck_record_2025_08_28": "zero results although issuer dividend history and saved vendor both list GLW ex-date 2025-08-29",
            "inference": "absence cannot uniquely adjudicate GLW 2026 security date",
            "query_observed_utc_date": "2026-09-27",
            "page_response_archived": False,
        },
        "saved_adjustment": {"initial_alpha_2026_01_02": alpha0, "initial_beta_2026_01_02": beta0,
                             "original_02_27_alpha": alpha27,
                             "original_event_date": "2026-02-27", "next_event_date": "2026-05-29",
                             "prior_close_original_02_27": 150.30,
                             "conditional_if_issuer_02_26_were_correct_factor": hypothetical_26_factor,
                             "conditional_factor_is_not_approved": True,
                             "price_coordinate": "PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN"},
        "unadjudicated_original_adjustment_suffix": "2026-02-27 through 2026-05-28 inclusive, subject to actual repaired account demand",
        "paused_repair_paths": paused_paths,
        "required_unique_resolution": "original supplier event provenance with historical applicable ex-date, or exchange per-security action notice / corrected issuer confirmation; then revalidate 02-26 open/close and 02-27 continuation and replay from pre-02-26 checkpoint",
        "source_sha256": source_hashes,
        "output_sha256": {csv_path.name: sha(csv_path)},
        "model_fit_calls": 0, "preprocessor_fit_calls": 0, "account_replay_calls": 0,
    }
    json_path = HERE / "ROUND2_GLW_ADJUDICATION.json"
    json_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "blocked_fields": 4,
                      "earliest": receipt["earliest_affected_input"],
                      "csv_sha256": receipt["output_sha256"][csv_path.name]}))


if __name__ == "__main__":
    main()
