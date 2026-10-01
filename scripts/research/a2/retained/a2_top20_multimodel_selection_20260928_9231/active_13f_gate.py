"""Check that inference candidates use the latest disclosed, effective 13F pool."""
from __future__ import annotations

import numpy as np
import pandas as pd


def validate_active_13f_pool(
    panel: pd.DataFrame, timing: pd.DataFrame, *, quarter_column: str
) -> dict[str, object]:
    """Reject stale quarter membership or an obsolete buy flag before scoring.

    The panel contains candidate securities in the active quarterly pool, not
    former-pool holdings retained solely for exit accounting. Holding exits are
    handled by the account ledger even when a ticker is absent from this panel.
    """
    needed = {"signal_date", quarter_column, "quarter_effective_date",
              "latest_filing_date", "new_buy_eligible"}
    missing = needed - set(panel)
    if missing:
        raise ValueError(f"13F candidate panel missing {sorted(missing)}")
    if panel.empty:
        raise ValueError("13F candidate panel is empty")
    qneeded = {"quarter", "quarter_effective_date", "latest_filing_date"}
    missing = qneeded - set(timing)
    if missing:
        raise ValueError(f"13F timing table missing {sorted(missing)}")
    q = timing[list(qneeded)].copy()
    q["quarter_effective_date"] = pd.to_datetime(q.quarter_effective_date)
    q["latest_filing_date"] = pd.to_datetime(q.latest_filing_date)
    q = q.sort_values("quarter_effective_date").reset_index(drop=True)
    if (q.empty or q.isna().any().any() or q.quarter.duplicated().any()
            or q.quarter_effective_date.duplicated().any()
            or q.latest_filing_date.ge(q.quarter_effective_date).any()):
        raise ValueError("13F timing table has missing, duplicate, or impossible effective dates")

    dates = pd.to_datetime(panel.signal_date)
    if dates.isna().any():
        raise ValueError("13F candidate signal date is missing")
    index = np.searchsorted(
        q.quarter_effective_date.to_numpy(dtype="datetime64[ns]"),
        dates.to_numpy(dtype="datetime64[ns]"), side="right"
    ) - 1
    if (index < 0).any():
        raise ValueError("13F candidate precedes the first effective quarter")
    expected = q.quarter.to_numpy()[index]
    actual = panel[quarter_column].astype(str).to_numpy()
    if not np.array_equal(actual, expected):
        bad = int(np.flatnonzero(actual != expected)[0])
        raise ValueError(
            f"13F candidate does not use latest effective quarter: "
            f"{dates.iloc[bad].date()} has {actual[bad]}, expected {expected[bad]}"
        )
    for column in ("quarter_effective_date", "latest_filing_date"):
        reported = pd.to_datetime(panel[column])
        authoritative = q[column].to_numpy(dtype="datetime64[ns]")[index]
        if reported.isna().any() or not np.array_equal(
            reported.to_numpy(dtype="datetime64[ns]"), authoritative
        ):
            raise ValueError(f"13F candidate {column} differs from quarter timing")
    if dates.le(pd.to_datetime(panel.latest_filing_date)).any():
        raise ValueError("13F candidate filing was not yet public at signal time")
    eligible = panel.new_buy_eligible
    if not pd.api.types.is_bool_dtype(eligible) or eligible.isna().any() or not eligible.all():
        raise ValueError("13F active candidate has an obsolete or missing new-buy flag")
    prior_natural_quarter = (dates.dt.to_period("Q") - 1).astype(str).to_numpy()
    carried = actual != prior_natural_quarter
    return {
        "status": "PASS",
        "definition": "latest publicly filed and effective 13F quarter at signal close",
        "candidate_rows": int(len(panel)),
        "signal_days": int(dates.nunique()),
        "carry_forward_rows": int(carried.sum()),
        "carry_forward_days": int(dates[carried].nunique()),
        "active_quarters": sorted(set(actual)),
        "new_buy_eligible_rows": int(eligible.sum()),
    }
