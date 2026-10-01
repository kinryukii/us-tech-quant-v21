"""Restore only proved AAPL event-warning quote keys after the existing R8 gate.

This adapter does not inspect policies, holdings, scores or account results. The
caller must bind its source, evidence and policy identities before any replay.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


def _sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def gate_prices_with_r9_aapl_exact(
    r8_gated_prices: pd.DataFrame,
    *,
    raw_prices: pd.DataFrame,
    raw_price_sha256: str,
    overlay_path: Path,
    expected_overlay_sha256: str,
    receipt_path: Path,
    expected_receipt_sha256: str,
) -> tuple[pd.DataFrame, dict]:
    """Restore the original open/close on exactly 158 AAPL price-coordinate keys."""
    overlay_path, receipt_path = Path(overlay_path), Path(receipt_path)
    if _sha(overlay_path) != expected_overlay_sha256 or _sha(receipt_path) != expected_receipt_sha256:
        raise ValueError("R9 evidence differs from the caller's frozen manifest")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt["status"] != "R9_AAPL_PRICE_GATE_PREPARED_NO_ACCOUNT_REPLAY":
        raise ValueError("Unexpected R9 evidence status")
    if (receipt["policy_independent_exact_price_keys"] != 158 or
            receipt["prior_r7_keys_preserved_disjoint"] != 811 or
            receipt["prior_r8_keys_preserved_disjoint"] != 301):
        raise ValueError("R9 or prior exact key binding changed")
    if (receipt["input_sha256"]["prices"] != raw_price_sha256 or
            receipt["output_sha256"][overlay_path.name] != expected_overlay_sha256):
        raise ValueError("R9 original input or output hash binding changed")
    if receipt["issuer_original_http_bodies_saved"] or receipt["historical_vendor_actual_receipt_observed"]:
        raise ValueError("R9 source evidence tier overstated")

    required = {"ticker", "trade_date", "open", "close", "raw_open", "raw_close",
                "price_quality_warning", "unresolved_event_on_or_before", "lifecycle_ended",
                "extreme_adjusted_jump", "price_coordinate", "original_transport", "transport_used"}
    if not required.issubset(raw_prices) or not required.issubset(r8_gated_prices):
        raise ValueError("Price source columns missing")
    if not {"original_price_quality_warning", "r7_overlay_applied", "r8_overlay_applied"}.issubset(r8_gated_prices):
        raise ValueError("R9 requires R7 then R8 gate output")
    if (len(raw_prices) != len(r8_gated_prices) or
            raw_prices.duplicated(["ticker", "trade_date"]).any() or
            not raw_prices[["ticker", "trade_date"]].equals(r8_gated_prices[["ticker", "trade_date"]])):
        raise ValueError("Original and R8 price key order differs")
    original_warning = raw_prices.price_quality_warning.astype(bool)
    if not r8_gated_prices.original_price_quality_warning.astype(bool).equals(original_warning):
        raise ValueError("R8 original warning audit field changed")
    r7 = r8_gated_prices.r7_overlay_applied.astype(bool)
    r8 = r8_gated_prices.r8_overlay_applied.astype(bool)
    if int(r7.sum()) != 811 or int(r8.sum()) != 301 or bool((r7 & r8).any()):
        raise ValueError("Prior R7/R8 gate no longer exactly preserved")

    overlay = pd.read_parquet(overlay_path)
    if len(overlay) != 158 or overlay.duplicated(["ticker", "date"]).any() or not overlay.ticker.eq("AAPL").all():
        raise ValueError("R9 overlay keys changed")
    if not overlay.scope.eq("POLICY_INDEPENDENT_POSTHOC_EVALUATION_PRICE_COORDINATE_ONLY").all():
        raise ValueError("R9 scope changed")
    if not (overlay.latest_issuer_public_date.lt(overlay.latest_proven_event_date) &
            overlay.latest_proven_event_date.le(overlay.date) &
            overlay.date.lt(overlay.no_next_unproved_consumed_event_through_exclusive)).all():
        raise ValueError("R9 issuer-event-price time chain broken")
    if (overlay.price_coordinate.ne("PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN").any() or
            overlay.original_transport.ne("US.AAPL").any() or
            overlay.transport_used.ne("US.AAPL").any() or
            overlay.cusip.ne("037833100").any() or
            overlay.title_of_class.ne("COM").any()):
        raise ValueError("R9 security or price coordinate changed")
    raw_keys = pd.MultiIndex.from_frame(raw_prices[["ticker", "trade_date"]])
    overlay_keys = pd.MultiIndex.from_frame(overlay[["ticker", "date"]].rename(columns={"date": "trade_date"}))
    positions = raw_keys.get_indexer(overlay_keys)
    if (positions < 0).any() or len(set(positions)) != 158:
        raise ValueError("R9 contains absent original price keys")
    source = raw_prices.iloc[positions].reset_index(drop=True)
    prior = r8_gated_prices.iloc[positions].reset_index(drop=True)
    for field in ("open", "close", "raw_open", "raw_close"):
        if not np.array_equal(source[field].to_numpy(), overlay[field].to_numpy()):
            raise ValueError(f"R9 {field} differs from original saved quote")
    for field in ("price_coordinate", "original_transport", "transport_used"):
        if not source[field].eq(overlay[field]).all():
            raise ValueError(f"R9 {field} differs from original saved quote")
    if (not source[["price_quality_warning", "unresolved_event_on_or_before"]].astype(bool).all().all() or
            source[["lifecycle_ended", "extreme_adjusted_jump"]].astype(bool).any().any() or
            not overlay[["open", "close", "raw_open", "raw_close"]].gt(0).all().all()):
        raise ValueError("R9 contains non-event warning or invalid original quote")
    if (prior.r7_overlay_applied.astype(bool).any() or prior.r8_overlay_applied.astype(bool).any() or
            not prior.price_quality_warning.astype(bool).all() or
            not prior[["open", "close"]].isna().all().all()):
        raise ValueError("R9 overlaps or bypasses prior price gate")

    result = r8_gated_prices.copy()
    result["r9_overlay_applied"] = False
    result.iloc[positions, result.columns.get_indexer(["open", "close"])] = source[["open", "close"]].to_numpy()
    result.iloc[positions, result.columns.get_loc("price_quality_warning")] = False
    result.iloc[positions, result.columns.get_loc("r9_overlay_applied")] = True
    r9 = result.r9_overlay_applied.astype(bool)
    if (int(r9.sum()) != 158 or int(result.r7_overlay_applied.astype(bool).sum()) != 811 or
            int(result.r8_overlay_applied.astype(bool).sum()) != 301 or
            bool((r9 & (r7 | r8)).any())):
        raise AssertionError("R9 or prior overlay count changed")
    if not result.loc[original_warning & ~(r7 | r8 | r9), ["open", "close"]].isna().all().all():
        raise AssertionError("Off-overlay warning was made tradable")
    if not result.loc[r7 | r8 | r9, ["open", "close"]].gt(0).all().all():
        raise AssertionError("Approved price missing")
    return result, {
        "status": "R9_AAPL_POLICY_INDEPENDENT_PRICE_GATE_READY_FOR_FROZEN_REPLAY",
        "original_price_sha256": raw_price_sha256,
        "r9_overlay_sha256": expected_overlay_sha256,
        "r9_receipt_sha256": expected_receipt_sha256,
        "original_warning_rows": int(original_warning.sum()),
        "r7_exact_keys_preserved": int(r7.sum()),
        "r8_exact_keys_preserved": int(r8.sum()),
        "r9_aapl_exact_keys_restored": int(r9.sum()),
        "remaining_warning_rows": int(result.price_quality_warning.astype(bool).sum()),
        "model_fit_calls": 0,
        "policy_calls": 0,
        "ledger_replay_calls": 0,
    }
