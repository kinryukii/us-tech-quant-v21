"""Single-account non-overlapping FAST3 portfolio contract."""
from __future__ import annotations

import pandas as pd


def simulate_primary_portfolio(labels: pd.DataFrame, initial_nav: float = 100_000.0) -> tuple[pd.DataFrame, dict]:
    """Accept at most one full-notional ETF position; known exits free capital."""
    x = labels.copy()
    if x.empty:
        return x, {"RAW_SIGNAL_COUNT": 0, "DEDUPED_SIGNAL_COUNT": 0, "ACCEPTED_TRADE_COUNT": 0,
                   "REJECTED_OVERLAP_COUNT": 0, "REJECTED_CAPITAL_COUNT": 0, "REJECTED_CONFLICT_COUNT": 0, "ending_nav": initial_nav}
    x["decision_timestamp_et"] = pd.to_datetime(x["decision_timestamp_et"])
    x["exit_timestamp_et"] = pd.to_datetime(x["exit_timestamp_et"])
    raw = len(x)
    x = x.sort_values(["event_id", "decision_timestamp_et"], kind="mergesort").drop_duplicates("event_id", keep="first")
    deduped = len(x)
    x = x.sort_values(["decision_timestamp_et", "priority", "event_id"], ascending=[True, False, True], kind="mergesort").reset_index(drop=True)
    active = None
    nav = initial_nav
    counters = {"REJECTED_OVERLAP_COUNT": 0, "REJECTED_CAPITAL_COUNT": 0, "REJECTED_CONFLICT_COUNT": 0}
    rows = []
    for r in x.itertuples(index=False):
        item = r._asdict()
        item["capital_available"] = nav if active is None or pd.Timestamp(r.decision_timestamp_et) >= pd.Timestamp(active["exit_timestamp_et"]) else 0.0
        item["trade_accepted"] = False
        item["trade_rejection_reason"] = None
        if active is not None and pd.Timestamp(r.decision_timestamp_et) < pd.Timestamp(active["exit_timestamp_et"]):
            item["trade_rejection_reason"] = "CONFLICT" if r.direction != active["direction"] else "OVERLAP"
            counters["REJECTED_CONFLICT_COUNT" if item["trade_rejection_reason"] == "CONFLICT" else "REJECTED_OVERLAP_COUNT"] += 1
        elif nav <= 0:
            item["trade_rejection_reason"] = "CAPITAL"
            counters["REJECTED_CAPITAL_COUNT"] += 1
        else:
            item["trade_accepted"] = True
            item["position_notional"] = nav
            nav *= 1.0 + float(r.net_return)
            active = item
        rows.append(item)
    result = pd.DataFrame(rows)
    return result, {"RAW_SIGNAL_COUNT": raw, "DEDUPED_SIGNAL_COUNT": deduped,
                    "ACCEPTED_TRADE_COUNT": int(result.trade_accepted.sum()), **counters, "ending_nav": nav}
