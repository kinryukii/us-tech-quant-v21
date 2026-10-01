"""Extract exact newly proved ticker-days from the immutable V6 to V20 ledgers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
PRIOR = HERE / "inputs/APPROVED_PRICE_FIELDS_V6.csv"
CURRENT = HERE / "inputs/APPROVED_PRICE_FIELDS_V20.csv"
OUTPUT = HERE.parent / "ROUND2_PROVED_FIELD_DELTA.csv"
RECEIPT = HERE.parent / "ROUND2_PROVED_FIELD_DELTA_RECEIPT.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if OUTPUT.exists() or RECEIPT.exists():
        raise RuntimeError("preserve the prior field delta")
    prior = pd.read_csv(PRIOR)
    current = pd.read_csv(CURRENT)
    keys = ["ticker", "trade_date"]
    assert not prior.duplicated(keys).any() and not current.duplicated(keys).any()
    assert prior.candidate_pool_version.eq("R6_UNCHANGED").all()
    assert current.candidate_pool_version.eq("R6_UNCHANGED").all()
    p = prior.set_index(keys)
    c = current.set_index(keys)
    assert p.index.isin(c.index).all()
    overlap = c.loc[p.index]
    for field in ("open", "close"):
        assert np.allclose(overlap[field].astype(float), p[field].astype(float), rtol=0, atol=1e-9)
    for field in ("open_authorized", "close_authorized"):
        assert overlap[field].astype(bool).equals(p[field].astype(bool))
    delta = current.loc[~current.set_index(keys).index.isin(p.index)].copy()
    assert len(delta) == len(current) - len(prior)
    delta.to_csv(OUTPUT, index=False)
    counts = {field: int(delta[field].astype(bool).sum())
              for field in ("open_authorized", "close_authorized")}
    receipt = {
        "candidate_pool_version": "R6_UNCHANGED", "new_ticker_dates": len(delta),
        "new_authorized_field_counts": counts,
        "prior": {"path": str(PRIOR), "sha256": sha(PRIOR), "ticker_dates": len(prior)},
        "current": {"path": str(CURRENT), "sha256": sha(CURRENT), "ticker_dates": len(current)},
        "delta": {"path": str(OUTPUT), "sha256": sha(OUTPUT)},
        "model_fit_calls": 0, "preprocessor_fit_calls": 0, "account_replay_calls": 0,
    }
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ticker_dates": len(delta), **counts}))


if __name__ == "__main__":
    main()
