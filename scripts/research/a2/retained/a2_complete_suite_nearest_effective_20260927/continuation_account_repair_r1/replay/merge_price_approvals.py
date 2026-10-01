"""Versioned, exact-key merge of two separately proved price-field ledgers."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("prior", type=Path)
    parser.add_argument("additional", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists() or args.output.with_suffix(".json").exists():
        raise RuntimeError("V3 output exists; preserve every input version")
    prior, additional = pd.read_csv(args.prior), pd.read_csv(args.additional)
    keys = ["ticker", "trade_date"]
    required = set(keys + ["open_authorized", "close_authorized", "evidence_id", "open", "close", "candidate_pool_version"])
    for name, frame in (("prior", prior), ("additional", additional)):
        if not required <= set(frame):
            raise ValueError(f"{name} lacks {sorted(required - set(frame))}")
        if frame.duplicated(keys).any() or not frame.candidate_pool_version.eq("R6_UNCHANGED").all():
            raise ValueError(f"{name} duplicate keys or candidate version mismatch")
    common = prior.merge(additional, on=keys, suffixes=("_old", "_new"))
    for row in common.itertuples(index=False):
        for field in ("open_authorized", "close_authorized", "open", "close"):
            old, new = getattr(row, f"{field}_old"), getattr(row, f"{field}_new")
            if field in {"open", "close"}:
                if not np.isclose(float(old), float(new), rtol=0, atol=1e-9):
                    raise ValueError(f"overlap {field} differs: {row.ticker}, {row.trade_date}")
            elif bool(old) != bool(new):
                raise ValueError(f"overlap authorization differs: {row.ticker}, {row.trade_date}, {field}")
    merged = pd.concat([prior, additional.loc[~additional.set_index(keys).index.isin(prior.set_index(keys).index)]],
                       ignore_index=True).sort_values(keys, kind="stable").reset_index(drop=True)
    if merged.duplicated(keys).any():
        raise AssertionError("merged duplicate keys")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(args.output, index=False)
    receipt = {"status": f"{args.output.stem.rsplit('_', 1)[-1]}_EXACT_KEY_MERGE",
               "candidate_pool_version": "R6_UNCHANGED",
               "prior": {"path": str(args.prior.resolve()), "sha256": digest(args.prior), "rows": len(prior)},
               "additional": {"path": str(args.additional.resolve()), "sha256": digest(args.additional), "rows": len(additional)},
               "overlap_exact_keys": len(common), "merged": {"path": str(args.output.resolve()),
                   "sha256": digest(args.output), "rows": len(merged)}}
    args.output.with_suffix(".json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()
