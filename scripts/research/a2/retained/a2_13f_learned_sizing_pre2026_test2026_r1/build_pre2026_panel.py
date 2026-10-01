"""Bind full initial V/H to frozen Raw A2 pre-2026 TOP20, with amendment mask."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


OUT = Path(__file__).resolve().parent
OLD = Path("C:/Users/Lenovo/Documents/CODING开发/a2_top20_13f_sizing_pilot_r1")
RESULTS = Path("D:/us-tech-quant-results")
BASE = RESULTS / "A_VS_A2_QUARTERLY_13F_R1"
PIT = RESULTS / "A2_PIT13F_MATERIALIZATION_R1"


def qqq_calendar() -> pd.DatetimeIndex:
    parts = []
    for year in (2023, 2024, 2025):
        path = Path(f"D:/us-tech-quant-data/moomoo/source/prices_qfq/year={year}/prices.parquet")
        frame = pd.read_parquet(path, columns=["ticker", "trade_date"])
        parts.append(frame.loc[frame.ticker.astype(str).eq("QQQ"), "trade_date"])
    return pd.DatetimeIndex(sorted(pd.to_datetime(pd.concat(parts)).drop_duplicates()))


def fifth_session_after(calendar: pd.DatetimeIndex, public_date: pd.Timestamp) -> pd.Timestamp:
    position = calendar.searchsorted(public_date, side="right")
    if position + 4 >= len(calendar):
        return pd.NaT
    return pd.Timestamp(calendar[position + 4])


def main() -> None:
    signals = pd.read_parquet(BASE / "A2/top20_selections.parquet")
    assert signals.signal_date.min() == pd.Timestamp("2023-01-03")
    assert signals.signal_date.max() == pd.Timestamp("2025-12-29")
    assert signals.groupby("signal_date").size().eq(20).all()
    intervals = pd.read_parquet(PIT / "effective_universe_intervals.parquet")
    timing = pd.read_parquet(PIT / "quarterly_universe.parquet").sort_values("effective_date")
    dates = pd.DataFrame({"signal_date": sorted(signals.signal_date.unique())})
    active = pd.merge_asof(dates, timing[["report_quarter", "report_date", "latest_included_filing_timestamp",
                                              "effective_date", "effective_end"]],
                           left_on="signal_date", right_on="effective_date", direction="backward")
    assert active.report_quarter.notna().all() and active.signal_date.le(active.effective_end).all()
    signal = signals.merge(active, on="signal_date", validate="many_to_one")
    mapped = signal.merge(intervals[["report_quarter", "ticker", "cusip", "mapping_status"]],
                          on=["report_quarter", "ticker"], how="left", validate="many_to_one")
    assert mapped.cusip.notna().all() and mapped.mapping_status.eq("RESOLVED").all()
    # Trainer may open only this pre-2026-only materialization, never the mixed
    # 2026 initial-holdings container.
    info = pd.read_parquet(OUT / "PRE2026_FULL_INITIAL_INFOTABLE.parquet")
    info = info.loc[info.eligible & info.quarter.isin(set(active.report_quarter))].copy()
    h = pd.read_csv(OUT / "FULL_INITIAL_H.csv")
    h = h.loc[h.quarter.isin(set(active.report_quarter))].copy()
    managers = sorted(h.manager_id.unique())
    assert len(managers) == 24 and h.groupby("quarter").manager_id.nunique().eq(24).all()
    assert h.full_eligible_equity_value_usd.gt(0).all()
    v = info.groupby(["quarter", "manager_id", "cusip"], as_index=False).value_usd.sum()
    states = mapped[["report_quarter", "ticker", "cusip"]].drop_duplicates()
    assert not states.duplicated(["report_quarter", "ticker"]).any()
    manager_grid = h[["quarter", "manager_id", "accession_key", "filing_date", "full_eligible_equity_value_usd"]].merge(
        states, left_on="quarter", right_on="report_quarter", validate="many_to_many")
    manager_grid = manager_grid.merge(v, on=["quarter", "manager_id", "cusip"], how="left", validate="many_to_one")
    manager_grid["public_equity_amount_usd"] = manager_grid.value_usd.fillna(0.0)
    manager_grid["amount_status"] = np.where(manager_grid.value_usd.notna(), "LISTED_FULL_INITIAL", "COMPLETE_PUBLIC_INITIAL_NOT_LISTED")
    manager_grid["holding_share"] = manager_grid.public_equity_amount_usd / manager_grid.full_eligible_equity_value_usd
    assert manager_grid.groupby(["quarter", "ticker"]).manager_id.nunique().eq(24).all()
    assert (manager_grid.holding_share >= 0).all() and (manager_grid.holding_share <= 1 + 1e-10).all()
    manager_grid.to_parquet(OUT / "PRE2026_QUARTER_MANAGER_STOCK_VH.parquet", index=False, compression="zstd")
    agg = manager_grid.groupby(["quarter", "ticker"], as_index=False).agg(
        M_full_initial_usd=("public_equity_amount_usd", "sum"),
        C_full_initial=("holding_share", "mean"),
        B_full_initial=("public_equity_amount_usd", lambda s: float((s > 0).sum()) / 24),
        listed_manager_count=("value_usd", lambda s: int(s.notna().sum())),
        H_known_manager_count=("full_eligible_equity_value_usd", "count"))
    panel = mapped.merge(agg, left_on=["report_quarter", "ticker"], right_on=["quarter", "ticker"],
                         how="left", validate="many_to_one")
    assert len(panel) == 15000 and panel.H_known_manager_count.eq(24).all()
    amendments = pd.read_csv(OUT / "AMENDMENT_CANDIDATES.csv", dtype=str)
    amendments["filed_date"] = pd.to_datetime(amendments.FILING_DATE, format="%d-%b-%Y")
    amendments["report_quarter"] = pd.to_datetime(amendments.PERIODOFREPORT, format="%d-%b-%Y").dt.to_period("Q").astype(str)
    calendar = qqq_calendar()
    windows = []
    for row in amendments.itertuples(index=False):
        quarter = str(row.report_quarter)
        match = timing.loc[timing.report_quarter.eq(quarter)]
        if match.empty:
            continue
        state = match.iloc[0]
        activated = fifth_session_after(calendar, pd.Timestamp(row.filed_date))
        if pd.isna(activated):
            continue
        unknown_start = max(pd.Timestamp(state.effective_date), activated)
        unknown_end = min(pd.Timestamp(state.effective_end), pd.Timestamp("2025-12-31"))
        if unknown_start <= unknown_end:
            windows.append({"report_quarter": quarter, "accession": row.ACCESSION_NUMBER,
                            "filed_date": row.filed_date, "unknown_from": unknown_start,
                            "unknown_through": unknown_end,
                            "reason": "AMENDMENT_SUBTYPE_UNAVAILABLE_LOCAL_SEC_NETWORK_BLOCKED"})
    windows_frame = pd.DataFrame(windows)
    windows_frame.to_csv(OUT / "PRE2026_AMENDMENT_UNKNOWN_WINDOWS.csv", index=False)
    panel["input_status"] = "FULL_INITIAL_PUBLIC_EQUITY_KNOWN"
    panel["fallback_reason"] = ""
    for window in windows:
        mask = (panel.report_quarter.eq(window["report_quarter"]) &
                panel.signal_date.between(window["unknown_from"], window["unknown_through"]))
        panel.loc[mask, "input_status"] = "UNKNOWN_AMENDMENT_VERSION"
        panel.loc[mask, "fallback_reason"] = "UNKNOWN_AMENDMENT_VERSION"
    panel["full_vh_usable"] = panel.input_status.eq("FULL_INITIAL_PUBLIC_EQUITY_KNOWN")
    panel["G"] = 1.0
    panel["b"] = 0.05
    sums = panel.groupby("signal_date").M_full_initial_usd.transform("sum")
    panel["B2_full_uncapped_raw_weight"] = np.where(panel.full_vh_usable & sums.gt(0), panel.M_full_initial_usd / sums, np.nan)
    old = pd.read_csv(OLD / "WEIGHTS.csv", usecols=["signal_date", "ticker", "B2_OBSERVED_TOP100"])
    old.signal_date = pd.to_datetime(old.signal_date)
    panel = panel.merge(old, on=["signal_date", "ticker"], validate="one_to_one")
    panel["full_minus_old_top100_weight"] = panel.B2_full_uncapped_raw_weight - panel.B2_OBSERVED_TOP100
    panel.to_parquet(OUT / "PIT_PRE2026_TOP20_VH_PANEL.parquet", index=False, compression="zstd")
    panel[["signal_date", "ticker", "report_quarter", "report_date", "latest_included_filing_timestamp",
           "effective_date", "cusip", "M_full_initial_usd", "C_full_initial", "B_full_initial",
           "H_known_manager_count", "listed_manager_count", "input_status", "fallback_reason",
           "B2_full_uncapped_raw_weight", "B2_OBSERVED_TOP100", "full_minus_old_top100_weight"]].to_csv(
               OUT / "PRE2026_INPUT_COVERAGE.csv", index=False)
    daily = panel.groupby("signal_date").agg(report_quarter=("report_quarter", "first"),
                                              full_vh_usable=("full_vh_usable", "all"),
                                              stock_rows=("ticker", "size"),
                                              H_known_managers=("H_known_manager_count", "min"),
                                              fallback_reason=("fallback_reason", "first")).reset_index()
    daily.to_csv(OUT / "PRE2026_DAILY_COVERAGE.csv", index=False)
    valid = panel.loc[panel.full_vh_usable]
    coverage = {
        "status": "CONDITIONAL_INITIAL_FULL_VH_WITH_UNKNOWN_AMENDMENT_DAYS",
        "signal_days": int(daily.shape[0]), "signal_stock_rows": len(panel),
        "full_initial_H_manager_quarter_states": len(h),
        "active_quarters": int(panel.report_quarter.nunique()),
        "original_institutions": 24,
        "full_vh_usable_days": int(daily.full_vh_usable.sum()),
        "full_vh_usable_stock_days": len(valid),
        "fallback_unknown_amendment_days": int((~daily.full_vh_usable).sum()),
        "amendment_unknown_windows": len(windows),
        "old_top100_observed_stock_days": 15000,
        "old_full_report_amount_known_stock_days": 0,
        "mean_abs_full_minus_old_raw_weight_on_usable_days": float(valid.full_minus_old_top100_weight.abs().mean()),
        "new_data_limit": "Initial complete public information tables exist. Amendment subtype cannot be verified locally; affected effective days are UNKNOWN. Later 2026Q2 package absent. Cross-filer shared-management identity not proven to be duplicate or unique.",
        "no_2026_policy_outcomes_read": True
    }
    (OUT / "COVERAGE_SNAPSHOT.json").write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(coverage, indent=2))


if __name__ == "__main__":
    main()
