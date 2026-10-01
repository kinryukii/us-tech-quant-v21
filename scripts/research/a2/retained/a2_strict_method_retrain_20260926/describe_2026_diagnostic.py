"""Describe already saved limited-scope predictions; never fits or backtests."""
from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
DIR = HERE / "test2026_stage"


def main():
    top = pd.read_parquet(DIR / "top20_known_window.parquet")
    cov = pd.read_csv(DIR / "daily_coverage_known_window.csv")
    pairs = {}
    for a, b in combinations(("hgb", "ridge", "elastic_net", "mlp"), 2):
        aa = top.loc[top.method.eq(a), ["signal_date", "ticker"]]
        bb = top.loc[top.method.eq(b), ["signal_date", "ticker"]]
        common = aa.merge(bb, on=["signal_date", "ticker"], validate="one_to_one")
        count = common.groupby("signal_date").size().reindex(sorted(top.signal_date.unique()), fill_value=0)
        pairs[f"{a}__{b}"] = {"mean_names": float(count.mean()), "min_names": int(count.min()), "max_names": int(count.max())}
    record = {"scope": "PARTIAL_POOL_DESCRIPTION_NOT_FORMAL_TEST", "days": len(cov),
        "date_start": cov.signal_date.min(), "date_end": cov.signal_date.max(),
        "min_unknown_members_per_day": int((cov.UNKNOWN_NO_RAW_FILE + cov.UNKNOWN_NO_DAILY_PRICE_OR_LIFECYCLE).min()),
        "max_unknown_members_per_day": int((cov.UNKNOWN_NO_RAW_FILE + cov.UNKNOWN_NO_DAILY_PRICE_OR_LIFECYCLE).max()),
        "every_day_has_unknown_qualification": bool(((cov.UNKNOWN_NO_RAW_FILE + cov.UNKNOWN_NO_DAILY_PRICE_OR_LIFECYCLE) > 0).all()),
        "top20_pairwise_overlap": pairs,
        "execution_price_gap": "NOT_ASSESSED_FOR_FORMAL_PORTFOLIO; partial-pool selections are invalid as formal orders",
        "holding_price_gap": "NOT_ASSESSED_FOR_FORMAL_PORTFOLIO; no formal positions initialized",
        "mature_label_metrics": "NOT_REPORTED_AS_FORMAL_PREDICTION_TEST; incomplete pool and price surface",
        "portfolio_metrics": "NOT_COMPUTED; no valid complete-pool TOP20 or full-window input"}
    (DIR / "known_window_description.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps(record), flush=True)


if __name__ == "__main__":
    main()
