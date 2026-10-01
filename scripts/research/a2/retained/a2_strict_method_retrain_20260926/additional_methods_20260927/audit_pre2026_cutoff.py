"""Read-only training cutoff audit shared by the newly authorized methods."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent
MATRIX = Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\A2\training_matrix.parquet")
PRICES = Path(r"D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results\pre2026_original_price_coordinate.parquet")
CUTOFF = pd.Timestamp("2026-01-01")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    matrix_hash = sha(MATRIX)
    assert matrix_hash == "31cc2b3dd2aa7a7c3372d56d5f3f351746b4ad06ef984563de576071913615fb"
    m = pd.read_parquet(MATRIX, columns=["signal_date", "target_end_date"])
    signal = pd.to_datetime(m.signal_date)
    end = pd.to_datetime(m.target_end_date)
    assert len(m) == 520328 and signal.notna().all() and end.notna().all()
    assert signal.lt(CUTOFF).all() and end.lt(CUTOFF).all() and end.ge(signal).all()
    price_date = pd.to_datetime(pd.read_parquet(PRICES, columns=["trade_date"]).trade_date)
    assert len(price_date) == 1195013 and price_date.notna().all() and price_date.lt(CUTOFF).all()
    out = {
        "status": "ALL_ORIGINAL_NEW_METHOD_TRAINING_TARGETS_AND_PRICES_PRE2026",
        "cutoff_exclusive": "2026-01-01",
        "training_matrix_sha256": matrix_hash,
        "training_matrix_rows": len(m),
        "max_signal_date": str(signal.max().date()),
        "max_target_end_date": str(end.max().date()),
        "targets_maturing_in_2026_or_later": int(end.ge(CUTOFF).sum()),
        "null_target_end_dates": int(end.isna().sum()),
        "source_price_sha256": sha(PRICES),
        "source_price_rows": len(price_date),
        "max_price_date": str(price_date.max().date()),
        "price_rows_in_2026_or_later": int(price_date.ge(CUTOFF).sum()),
        "model_fit_calls_by_this_audit": 0,
    }
    (OUT / "TRAINING_CUTOFF_AUDIT.json").write_text(json.dumps(out, indent=2) + "\n", "utf-8")
    print(json.dumps({"matrix_rows": len(m), "max_target_end": out["max_target_end_date"],
                      "price_rows": len(price_date), "max_price": out["max_price_date"]}))


if __name__ == "__main__":
    main()
