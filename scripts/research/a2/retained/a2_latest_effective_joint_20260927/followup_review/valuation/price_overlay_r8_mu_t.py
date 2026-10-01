"""Apply the exact, post-hoc MU/T cash-event price gate after the frozen R7 gate.

This is a price-input adapter only. It never reads models, policies, holdings or
account results; the caller must freeze its own complete replay before using it.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


def _sha(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def gate_prices_with_r8_mu_t_exact(
    r7_gated_prices: pd.DataFrame,
    *,
    raw_prices: pd.DataFrame,
    raw_price_sha256: str,
    overlay_path: Path,
    expected_overlay_sha256: str,
    receipt_path: Path,
    expected_receipt_sha256: str,
) -> tuple[pd.DataFrame, dict]:
    """Restore only 301 independently qualified MU/T quote keys on R7 input.

    Original event warnings remain closed on all other keys. This does not
    mutate the caller's input or add dividend cash; it retains the joint batch's
    forward-rehab index price-coordinate proxy only.
    """
    overlay_path, receipt_path = Path(overlay_path), Path(receipt_path)
    if _sha(overlay_path) != expected_overlay_sha256 or _sha(receipt_path) != expected_receipt_sha256:
        raise ValueError("R8 evidence identity differs from caller's frozen manifest")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt["status"] != "R8_MU_T_PRICE_GATE_PREPARED_NO_ACCOUNT_REPLAY":
        raise ValueError("Unexpected R8 evidence status")
    if receipt["policy_independent_exact_price_keys"] != 301 or receipt["prior_r7_keys_preserved_disjoint"] != 811:
        raise ValueError("R8 exact key or R7 binding count changed")
    if receipt["input_sha256"]["prices"] != raw_price_sha256:
        raise ValueError("R8 was prepared on a different original price file")
    if receipt["output_sha256"][overlay_path.name] != expected_overlay_sha256:
        raise ValueError("R8 overlay not bound by its own receipt")
    if receipt["issuer_original_http_bodies_saved"] or receipt["historical_vendor_actual_receipt_observed"]:
        raise ValueError("R8 issuer/vendor evidence tier was overstated")
    required = {"ticker", "trade_date", "open", "close", "raw_open", "raw_close",
                "price_quality_warning", "unresolved_event_on_or_before", "lifecycle_ended",
                "extreme_adjusted_jump", "price_coordinate", "original_transport", "transport_used"}
    if not required.issubset(raw_prices) or not required.issubset(r7_gated_prices):
        raise ValueError("Price input missing original source columns")
    if not {"original_price_quality_warning", "r7_overlay_applied"}.issubset(r7_gated_prices):
        raise ValueError("R8 adapter requires the existing R7 gate's audited output")
    if len(raw_prices) != len(r7_gated_prices):
        raise ValueError("R7 prices differ in row count from original")
    if raw_prices.duplicated(["ticker", "trade_date"]).any():
        raise ValueError("Original price keys duplicate")
    if not raw_prices[["ticker", "trade_date"]].equals(r7_gated_prices[["ticker", "trade_date"]]):
        raise ValueError("R7 price row order or key identity changed")
    if not r7_gated_prices.original_price_quality_warning.astype(bool).equals(
            raw_prices.price_quality_warning.astype(bool)):
        raise ValueError("R7 original warning audit field changed")
    if int(r7_gated_prices.r7_overlay_applied.astype(bool).sum()) != 811:
        raise ValueError("R7 restoration count changed")

    overlay = pd.read_parquet(overlay_path)
    if len(overlay) != 301 or overlay.duplicated(["ticker", "date"]).any():
        raise ValueError("R8 overlay key multiplicity changed")
    if overlay.groupby("ticker").size().to_dict() != {"MU": 124, "T": 177}:
        raise ValueError("R8 ticker price-date domain changed")
    if not overlay.scope.eq("POLICY_INDEPENDENT_POSTHOC_EVALUATION_PRICE_COORDINATE_ONLY").all():
        raise ValueError("R8 scope changed")
    if not (overlay.latest_issuer_public_date.lt(overlay.latest_proven_event_date) &
            overlay.latest_proven_event_date.le(overlay.date) &
            overlay.date.lt(overlay.no_next_unproved_consumed_event_through_exclusive)).all():
        raise ValueError("R8 event timing changed")
    if not overlay.price_coordinate.eq("PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN").all():
        raise ValueError("R8 price coordinate changed")
    raw_keys = pd.MultiIndex.from_frame(raw_prices[["ticker", "trade_date"]])
    overlay_keys = pd.MultiIndex.from_frame(overlay[["ticker", "date"]].rename(columns={"date": "trade_date"}))
    positions = raw_keys.get_indexer(overlay_keys)
    if (positions < 0).any() or len(set(positions)) != 301:
        raise ValueError("R8 contains a key absent from original joint prices")
    source_rows = raw_prices.iloc[positions].reset_index(drop=True)
    gated_rows = r7_gated_prices.iloc[positions].reset_index(drop=True)
    for field in ("open", "close", "raw_open", "raw_close"):
        if not np.array_equal(source_rows[field].to_numpy(), overlay[field].to_numpy()):
            raise ValueError(f"R8 {field} differs from original saved quote")
    for field in ("price_coordinate", "original_transport", "transport_used"):
        if not source_rows[field].eq(overlay[field]).all():
            raise ValueError(f"R8 {field} differs from original saved quote")
    if not source_rows[["price_quality_warning", "unresolved_event_on_or_before"]].astype(bool).all().all():
        raise ValueError("R8 contains a non-event warning")
    if source_rows[["lifecycle_ended", "extreme_adjusted_jump"]].astype(bool).any().any():
        raise ValueError("R8 contains an independently blocked row")
    if gated_rows.r7_overlay_applied.astype(bool).any() or not gated_rows.price_quality_warning.astype(bool).all():
        raise ValueError("R8 overlaps or bypasses R7 warning handling")
    if not gated_rows[["open", "close"]].isna().all().all():
        raise ValueError("R8 source rows were already available before restoration")
    if not overlay[["open", "close", "raw_open", "raw_close"]].gt(0).all().all():
        raise ValueError("R8 contains invalid original quotes")

    result = r7_gated_prices.copy()
    result["r8_overlay_applied"] = False
    result.iloc[positions, result.columns.get_indexer(["open", "close"])] = source_rows[["open", "close"]].to_numpy()
    result.iloc[positions, result.columns.get_loc("price_quality_warning")] = False
    result.iloc[positions, result.columns.get_loc("r8_overlay_applied")] = True
    new_mask = result.r8_overlay_applied.astype(bool)
    r7_mask = result.r7_overlay_applied.astype(bool)
    original_warning = raw_prices.price_quality_warning.astype(bool)
    if int(new_mask.sum()) != 301 or int(r7_mask.sum()) != 811 or bool((new_mask & r7_mask).any()):
        raise AssertionError("R8 exact restoration or R7 preservation failed")
    if not result.loc[original_warning & ~(new_mask | r7_mask), ["open", "close"]].isna().all().all():
        raise AssertionError("Warning outside R7/R8 overlay became tradable")
    if not result.loc[new_mask | r7_mask, ["open", "close"]].gt(0).all().all():
        raise AssertionError("An approved overlay quote is missing")
    return result, {
        "status": "R8_MU_T_POLICY_INDEPENDENT_PRICE_GATE_READY_FOR_FROZEN_REPLAY",
        "original_price_sha256": raw_price_sha256,
        "r8_overlay_sha256": expected_overlay_sha256,
        "r8_receipt_sha256": expected_receipt_sha256,
        "original_warning_rows": int(original_warning.sum()),
        "r7_exact_keys_preserved": int(r7_mask.sum()),
        "r8_mu_t_exact_keys_restored": int(new_mask.sum()),
        "remaining_warning_rows": int(result.price_quality_warning.astype(bool).sum()),
        "policy_calls": 0,
        "model_fit_calls": 0,
        "ledger_replay_calls": 0,
    }
