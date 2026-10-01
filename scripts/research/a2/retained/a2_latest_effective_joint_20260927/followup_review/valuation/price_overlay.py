"""Thin, policy-independent R7 price gate adapter for a later frozen replay.

This module has no model, policy or account code. It does not read test data on
import. Call it only from the existing joint-batch 2026 runner after that
runner's model/roster/price-overlay hashes have been frozen.
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


def gate_prices_with_r7_exact(
    raw_prices: pd.DataFrame,
    *,
    raw_price_sha256: str,
    overlay_path: Path,
    expected_overlay_sha256: str,
    receipt_path: Path,
    expected_receipt_sha256: str,
) -> tuple[pd.DataFrame, dict]:
    """Apply original warning gate, then restore only frozen R7 exact keys.

    The caller supplies all expected hashes from its freeze manifest. Quoted
    prices are consumed on their own date; no candidate feature or earlier
    decision is changed here. Returned prices retain the original flags in
    ``original_price_quality_warning`` for audit and expose an effective flag.
    """
    overlay_path = Path(overlay_path)
    receipt_path = Path(receipt_path)
    if _sha(overlay_path) != expected_overlay_sha256 or _sha(receipt_path) != expected_receipt_sha256:
        raise ValueError("R7 overlay identity differs from frozen manifest")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt["status"] != "R7_EXACT_PROOF_OVERLAY_PREPARED_NO_ACCOUNT_REPLAY":
        raise ValueError("R7 overlay has an unexpected review status")
    if receipt["policy_independent_r7_price_keys"] != 811 or receipt["policy_independent_excluded_keys"] != 0:
        raise ValueError("R7 policy-independent key count changed")
    if receipt["source_sha256"]["prices"] != raw_price_sha256:
        raise ValueError("raw 2026 price file differs from the verified source")
    if receipt["output_sha256"][overlay_path.name] != expected_overlay_sha256:
        raise ValueError("overlay not bound by R7 review receipt")
    required = {"ticker", "trade_date", "open", "close", "price_quality_warning",
                "unresolved_event_on_or_before", "lifecycle_ended", "extreme_adjusted_jump",
                "price_coordinate", "original_transport", "transport_used"}
    if not required.issubset(raw_prices):
        raise ValueError(f"price source missing columns {sorted(required - set(raw_prices))}")
    if raw_prices.duplicated(["ticker", "trade_date"]).any():
        raise ValueError("duplicate original price keys")
    overlay = pd.read_parquet(overlay_path)
    if len(overlay) != 811 or overlay.duplicated(["ticker", "date"]).any():
        raise ValueError("overlay keys are not the frozen exact 811")
    if not overlay.scope.eq("POLICY_INDEPENDENT_POSTHOC_EVALUATION_PRICE_COORDINATE_ONLY").all():
        raise ValueError("overlay scope changed")
    if not (overlay.source_public_date.lt(overlay.prior_session) &
            overlay.event_date.le(overlay.date) &
            overlay.date.lt(overlay.next_unproved_event_exclusive)).all():
        raise ValueError("overlay event clock failed")
    if not overlay.price_coordinate.eq("PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN").all():
        raise ValueError("overlay price coordinate changed")
    original_keys = pd.MultiIndex.from_frame(raw_prices[["ticker", "trade_date"]])
    overlay_keys = pd.MultiIndex.from_frame(overlay[["ticker", "date"]].rename(columns={"date": "trade_date"}))
    positions = original_keys.get_indexer(overlay_keys)
    if (positions < 0).any() or len(set(positions)) != 811:
        raise ValueError("overlay contains price keys absent from original file")
    original_rows = raw_prices.iloc[positions].reset_index(drop=True)
    for col in ("open", "close", "raw_open", "raw_close"):
        if not np.array_equal(original_rows[col].to_numpy(), overlay[col].to_numpy()):
            raise ValueError(f"overlay {col} differs from original saved price")
    for col in ("price_coordinate", "original_transport", "transport_used"):
        if not original_rows[col].eq(overlay[col]).all():
            raise ValueError(f"overlay {col} differs from original saved price")
    if not (original_rows.price_quality_warning.astype(bool).all() and
            original_rows.unresolved_event_on_or_before.astype(bool).all() and
            not bool(original_rows.lifecycle_ended.astype(bool).any()) and
            not bool(original_rows.extreme_adjusted_jump.astype(bool).any())):
        raise ValueError("overlay contains an unapproved warning reason")
    if not overlay[["open", "close", "raw_open", "raw_close"]].gt(0).all().all():
        raise ValueError("overlay contains an invalid quote")
    result = raw_prices.copy()
    original_warning = result.price_quality_warning.astype(bool)
    result["original_price_quality_warning"] = original_warning
    result["r7_overlay_applied"] = False
    result.loc[original_warning, ["open", "close"]] = np.nan
    result.iloc[positions, result.columns.get_indexer(["open", "close"])] = original_rows[["open", "close"]].to_numpy()
    result.iloc[positions, result.columns.get_loc("price_quality_warning")] = False
    result.iloc[positions, result.columns.get_loc("r7_overlay_applied")] = True
    restored = result.r7_overlay_applied.astype(bool)
    if restored.sum() != 811 or not result.loc[original_warning & ~restored, ["open", "close"]].isna().all().all():
        raise AssertionError("original warning gate not preserved off overlay")
    if not result.loc[restored, ["open", "close"]].gt(0).all().all():
        raise AssertionError("verified overlay prices were not restored")
    return result, {
        "status": "R7_POLICY_INDEPENDENT_PRICE_GATE_READY_FOR_FROZEN_REPLAY",
        "original_price_sha256": raw_price_sha256,
        "overlay_sha256": expected_overlay_sha256,
        "receipt_sha256": expected_receipt_sha256,
        "original_warning_rows": int(original_warning.sum()),
        "r7_exact_keys_restored": int(restored.sum()),
        "remaining_warning_rows": int(result.price_quality_warning.astype(bool).sum()),
        "policy_calls": 0,
        "model_fit_calls": 0,
        "ledger_replay_calls": 0,
    }
