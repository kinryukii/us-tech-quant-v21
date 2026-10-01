"""Static price-gate check only; no policy, wealth calculation or replay."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from price_overlay import gate_prices_with_r7_exact

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main() -> None:
    source = ROOT / "data/test_prices.parquet"
    overlay = HERE / "R7_POLICY_INDEPENDENT_PRICE_OVERLAY.parquet"
    receipt = HERE / "R7_OVERLAY_RECEIPT.json"
    source_hash, overlay_hash, receipt_hash = sha(source), sha(overlay), sha(receipt)
    raw = pd.read_parquet(source)
    gated, check = gate_prices_with_r7_exact(
        raw, raw_price_sha256=source_hash, overlay_path=overlay,
        expected_overlay_sha256=overlay_hash, receipt_path=receipt,
        expected_receipt_sha256=receipt_hash)
    assert len(gated) == len(raw)
    assert raw.price_quality_warning.astype(bool).sum() == (
        gated.price_quality_warning.astype(bool).sum() + 811)
    assert gated.r7_overlay_applied.astype(bool).sum() == 811
    assert not raw.r7_overlay_applied.any() if "r7_overlay_applied" in raw else True
    first_key = pd.read_parquet(overlay, columns=["ticker", "date"]).iloc[0]
    bad = raw.copy()
    mask = bad.ticker.eq(first_key.ticker) & bad.trade_date.eq(first_key.date)
    assert mask.sum() == 1
    bad.loc[mask, "open"] = bad.loc[mask, "open"] + 0.01
    rejected = False
    try:
        gate_prices_with_r7_exact(
            bad, raw_price_sha256=source_hash, overlay_path=overlay,
            expected_overlay_sha256=overlay_hash, receipt_path=receipt,
            expected_receipt_sha256=receipt_hash)
    except ValueError as exc:
        rejected = "overlay open differs" in str(exc)
    assert rejected, "changed price must fail the frozen overlay comparison"
    assert sha(source) == source_hash and sha(overlay) == overlay_hash and sha(receipt) == receipt_hash
    output = {
        **check,
        "status": "R7_POLICY_INDEPENDENT_PRICE_ADAPTER_STATIC_CHECK_PASS",
        "source_rows": len(raw),
        "modified_quote_rejected": rejected,
        "source_unchanged": True,
        "code_sha256": {
            "price_overlay.py": sha(HERE / "price_overlay.py"),
            "build_r7_exact_overlay.py": sha(HERE / "build_r7_exact_overlay.py"),
            "verify_price_overlay_adapter.py": sha(Path(__file__)),
        },
    }
    (HERE / "OVERLAY_ADAPTER_TECHNICAL_CHECK.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: output[k] for k in ("status", "source_rows", "r7_exact_keys_restored", "remaining_warning_rows", "modified_quote_rejected")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
