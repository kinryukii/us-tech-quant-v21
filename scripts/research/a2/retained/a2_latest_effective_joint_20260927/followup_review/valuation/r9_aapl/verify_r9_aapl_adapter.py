"""Bound R7 -> R8 -> R9 price-gate technical check; no policy or account call."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd


HERE = Path(__file__).resolve().parent
VALUATION = HERE.parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(VALUATION))
from price_overlay import gate_prices_with_r7_exact  # noqa: E402
from price_overlay_r8_mu_t import gate_prices_with_r8_mu_t_exact  # noqa: E402
from price_overlay_r9_aapl import gate_prices_with_r9_aapl_exact  # noqa: E402


def sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main() -> None:
    raw = ROOT / "data/test_prices.parquet"
    r7 = VALUATION / "R7_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet"
    r7_receipt = VALUATION / "R7_OVERLAY_RECEIPT.json"
    r8 = VALUATION / "r8_mu_t/R8_MU_T_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet"
    r8_receipt = VALUATION / "r8_mu_t/R8_MU_T_OVERLAY_RECEIPT.json"
    r9 = HERE / "R9_AAPL_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet"
    r9_receipt = HERE / "R9_AAPL_OVERLAY_RECEIPT.json"
    original = pd.read_parquet(raw)
    r7_prices, r7_result = gate_prices_with_r7_exact(
        original, raw_price_sha256=sha(raw), overlay_path=r7,
        expected_overlay_sha256=sha(r7), receipt_path=r7_receipt,
        expected_receipt_sha256=sha(r7_receipt))
    r8_prices, r8_result = gate_prices_with_r8_mu_t_exact(
        r7_prices, raw_prices=original, raw_price_sha256=sha(raw), overlay_path=r8,
        expected_overlay_sha256=sha(r8), receipt_path=r8_receipt,
        expected_receipt_sha256=sha(r8_receipt))
    r9_prices, r9_result = gate_prices_with_r9_aapl_exact(
        r8_prices, raw_prices=original, raw_price_sha256=sha(raw), overlay_path=r9,
        expected_overlay_sha256=sha(r9), receipt_path=r9_receipt,
        expected_receipt_sha256=sha(r9_receipt))
    assert r7_result["r7_exact_keys_restored"] == 811
    assert r8_result["r8_mu_t_exact_keys_restored"] == 301
    assert r9_result["r9_aapl_exact_keys_restored"] == 158
    assert r9_result["remaining_warning_rows"] == 31757
    assert r9_prices.r7_overlay_applied.equals(r8_prices.r7_overlay_applied)
    assert r9_prices.r8_overlay_applied.equals(r8_prices.r8_overlay_applied)
    off = ~r9_prices.r9_overlay_applied.astype(bool)
    for field in ("open", "close", "price_quality_warning"):
        assert r9_prices.loc[off, field].equals(r8_prices.loc[off, field])
    assert r9_prices.loc[r9_prices.r9_overlay_applied, ["open", "close"]].gt(0).all().all()
    bad = original.copy()
    first = r9_prices.index[r9_prices.r9_overlay_applied.astype(bool)][0]
    bad.loc[first, "open"] = float(bad.loc[first, "open"]) + 1.0
    try:
        gate_prices_with_r9_aapl_exact(
            r8_prices, raw_prices=bad, raw_price_sha256=sha(raw), overlay_path=r9,
            expected_overlay_sha256=sha(r9), receipt_path=r9_receipt,
            expected_receipt_sha256=sha(r9_receipt))
    except ValueError as error:
        assert "differs from original saved quote" in str(error)
    else:
        raise AssertionError("Tampered AAPL original quote was accepted")
    result = {
        "status": "R9_AAPL_TECHNICAL_PRICE_GATE_PASS_NO_ACCOUNT_REPLAY",
        "raw_prices_sha256": sha(raw),
        "r7_overlay_sha256": sha(r7),
        "r8_overlay_sha256": sha(r8),
        "r9_overlay_sha256": sha(r9),
        "r9_receipt_sha256": sha(r9_receipt),
        "r9_adapter_sha256": sha(VALUATION / "price_overlay_r9_aapl.py"),
        "r7_restored_preserved": 811,
        "r8_restored_preserved": 301,
        "r9_aapl_restored": 158,
        "remaining_warning_rows": 31757,
        "off_r9_price_and_gate_unchanged": True,
        "tampered_quote_rejected": True,
        "model_fit_calls": 0,
        "policy_calls": 0,
        "account_replay_calls": 0,
    }
    (HERE / "R9_ADAPTER_TECHNICAL_CHECK.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
