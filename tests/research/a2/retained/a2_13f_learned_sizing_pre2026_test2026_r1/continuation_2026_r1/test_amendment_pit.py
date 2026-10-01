"""Future 13F amendments cannot change prior coverage or fallback state."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from build_pre2026_panel import fifth_session_after, qqq_calendar  # noqa: E402


def main():
    panel = pd.read_parquet(BASE / "PIT_PRE2026_TOP20_VH_PANEL.parquet")
    days = panel[["signal_date", "report_quarter", "full_vh_usable"]].drop_duplicates("signal_date")
    assert len(days) == 750
    amendments = pd.read_csv(BASE / "AMENDMENT_CANDIDATES.csv", dtype=str)
    amendments["filing_date"] = pd.to_datetime(amendments.filing_date)
    amendments["quarter"] = amendments.report_quarter
    timing = pd.read_parquet("D:/us-tech-quant-results/A2_PIT13F_MATERIALIZATION_R1/quarterly_universe.parquet")
    timing = timing.set_index("report_quarter")
    calendar = qqq_calendar()

    def mask(events: pd.DataFrame) -> np.ndarray:
        selected = np.zeros(len(days), dtype=bool)
        for event in events.itertuples(index=False):
            if event.quarter not in timing.index:
                continue
            state = timing.loc[event.quarter]
            activation = fifth_session_after(calendar, pd.Timestamp(event.filing_date))
            if pd.isna(activation):
                continue
            start = max(pd.Timestamp(state.effective_date), activation)
            stop = min(pd.Timestamp(state.effective_end), pd.Timestamp("2025-12-31"))
            selected |= (days.report_quarter.eq(event.quarter) & days.signal_date.between(start, stop)).to_numpy()
        return selected

    actual = ~days.full_vh_usable.to_numpy()
    from_all_events = mask(amendments)
    assert np.array_equal(actual, from_all_events)
    for cutoff in sorted(amendments.filing_date.unique()):
        truncated = amendments.loc[amendments.filing_date.le(cutoff)]
        earlier = days.signal_date.le(cutoff).to_numpy()
        assert np.array_equal(mask(truncated)[earlier], from_all_events[earlier])
    tested_cuts = []
    for future_date in (pd.Timestamp("2023-08-01"), pd.Timestamp("2024-04-01"),
                        pd.Timestamp("2025-08-01")):
        before = amendments.loc[amendments.filing_date.lt(future_date)].copy()
        synthetic = pd.DataFrame([{"quarter": "2024Q2", "filing_date": future_date + pd.Timedelta(days=20)}])
        prior = mask(before)
        after = mask(pd.concat([before, synthetic], ignore_index=True))
        earlier = days.signal_date.lt(synthetic.filing_date.iloc[0]).to_numpy()
        assert np.array_equal(prior[earlier], after[earlier])
        tested_cuts.append(str(future_date.date()))
    assert (amendments.filing_date.max() > days.signal_date.min())
    result = {"status": "PASS_NO_FUTURE_AMENDMENT_ROLLBACK", "original_amendment_candidates": len(amendments),
              "historical_unknown_days_reproduced": int(from_all_events.sum()),
              "synthetic_cutoffs": tested_cuts, "real_outcomes_read": False}
    (Path(__file__).parent / "AMENDMENT_PIT_TEST.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
