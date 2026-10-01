"""Consume three actual dynamic frozen-account open/close cash-event needs."""

import json
from pathlib import Path

import pandas as pd

from build_first_four_account_fields import main, sha


EVENTS = {
    "PH": {
        "cusip": "701094104", "first": "2026-02-06", "next": "2026-05-08",
        "public": "2026-01-22", "cash": 1.80,
        "issuer_url": "https://investors.parker.com/news-events/press-releases/detail/498/parker-declares-quarterly-cash-dividend",
    },
    "AAPL": {
        "cusip": "037833100", "first": "2026-02-09", "next": "2026-05-11",
        "public": "2026-01-29", "cash": 0.26,
        "issuer_url": "https://www.apple.com/newsroom/2026/01/apple-reports-first-quarter-results/",
    },
    "CHRW": {
        "cusip": "12541W209", "first": "2026-03-06", "next": "2026-06-05",
        "public": "2026-02-05", "cash": 0.63,
        "issuer_url": "https://investor.chrobinson.com/news/press-releases/news-details/2026/C-H--Robinson-Declares-Quarterly-Cash-Dividend/default.aspx",
    },
}


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    queue_path = here.parent / "DYNAMIC_NEXT_INPUT_QUEUE.csv"
    queue = pd.read_csv(queue_path, dtype=str).fillna("")
    expected = {("PH", "2026-02-06", "open"), ("AAPL", "2026-02-09", "open"),
                ("AAPL", "2026-02-09", "close"), ("CHRW", "2026-03-06", "open")}
    selected = queue.loc[queue.apply(lambda r: (r.ticker, r.date, r.field) in expected, axis=1)].copy()
    assert len(selected) == len(expected)
    assert not selected.duplicated(["ticker", "date", "field"]).any()
    assert selected.current_repaired_account_need.eq("True").all()
    assert selected.frozen_price_field_status.eq("FROZEN_FIELD_PRESENT_BUT_UNRESOLVED_EVENT_ON_OR_BEFORE").all()
    assert selected.current_run_ids.str.len().gt(0).all()
    main(EVENTS, "ROUND2_EARLY")
    authorized = pd.read_parquet(here / "ROUND2_EARLY_EVENT_ACCOUNT_PRICE_FIELDS.parquet")
    allow_keys = set(zip(authorized.ticker, authorized.trade_date.dt.strftime("%Y-%m-%d")))
    assert all((ticker, day) in allow_keys for ticker, day, _ in expected)
    binding = {
        "status": "EXACT_DYNAMIC_ACCOUNT_DEMAND_BOUND_TO_FIELD_PROOF",
        "candidate_pool_version": "R6_UNCHANGED",
        "queue_path": str(queue_path), "queue_sha256": sha(queue_path),
        "exact_required_rows": selected[["ticker", "date", "field", "current_run_ids", "purposes", "pending_signal_dates", "historical_run_ids", "demand_origins", "source_files"]].to_dict("records"),
        "allowlist_parquet_sha256": sha(here / "ROUND2_EARLY_EVENT_ACCOUNT_PRICE_FIELDS.parquet"),
        "model_fit_calls": 0, "preprocessor_fit_calls": 0, "account_replay_calls": 0,
    }
    (here / "ROUND2_EARLY_DYNAMIC_BINDING.json").write_text(json.dumps(binding, ensure_ascii=False, indent=2) + "\n", "utf-8")
