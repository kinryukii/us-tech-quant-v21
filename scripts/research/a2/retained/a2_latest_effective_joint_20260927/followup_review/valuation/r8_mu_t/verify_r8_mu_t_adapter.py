"""One bounded price-gate technical check; no model or account execution."""
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


def sha(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def main() -> None:
    raw_path = ROOT / "data/test_prices.parquet"
    r7_path = VALUATION / "R7_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet"
    r7_receipt = VALUATION / "R7_OVERLAY_RECEIPT.json"
    r8_path = HERE / "R8_MU_T_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet"
    r8_receipt = HERE / "R8_MU_T_OVERLAY_RECEIPT.json"
    original = pd.read_parquet(raw_path)
    r7, r7_check = gate_prices_with_r7_exact(
        original, raw_price_sha256=sha(raw_path), overlay_path=r7_path,
        expected_overlay_sha256=sha(r7_path), receipt_path=r7_receipt,
        expected_receipt_sha256=sha(r7_receipt))
    r8, r8_check = gate_prices_with_r8_mu_t_exact(
        r7, raw_prices=original, raw_price_sha256=sha(raw_path),
        overlay_path=r8_path, expected_overlay_sha256=sha(r8_path),
        receipt_path=r8_receipt, expected_receipt_sha256=sha(r8_receipt))
    assert r7_check["r7_exact_keys_restored"] == 811
    assert r8_check["r8_mu_t_exact_keys_restored"] == 301
    assert r8_check["remaining_warning_rows"] == 31915
    assert r8.r7_overlay_applied.equals(r7.r7_overlay_applied)
    # R7 quotes, all other original warnings, and all unrelated prices remain
    # byte-identical at the DataFrame field level after the R8 addition.
    off = ~r8.r8_overlay_applied.astype(bool)
    for field in ("open", "close", "price_quality_warning"):
        assert r8.loc[off, field].equals(r7.loc[off, field])
    assert not r8.loc[off, "r8_overlay_applied"].astype(bool).any()
    assert r8.loc[r8.r8_overlay_applied, "open"].gt(0).all()
    assert r8.loc[r8.r8_overlay_applied, "close"].gt(0).all()
    output = {
        "status": "R8_MU_T_TECHNICAL_PRICE_GATE_PASS_NO_ACCOUNT_REPLAY",
        "raw_prices_sha256": sha(raw_path),
        "r7_overlay_sha256": sha(r7_path),
        "r8_overlay_sha256": sha(r8_path),
        "r8_receipt_sha256": sha(r8_receipt),
        "r8_adapter_sha256": sha(VALUATION / "price_overlay_r8_mu_t.py"),
        "r7_restored_preserved": 811,
        "r8_mu_t_restored": 301,
        "remaining_warning_rows": 31915,
        "off_r8_price_and_gate_unchanged": True,
        "model_fit_calls": 0,
        "policy_calls": 0,
        "account_replay_calls": 0,
    }
    (HERE / "R8_ADAPTER_TECHNICAL_CHECK.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output))


if __name__ == "__main__":
    main()
