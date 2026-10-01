"""Report-only QQQ benchmark NA adapter for the existing native stock ledger."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
PARENT=HERE.parent
REPO=Path(r"D:\us-tech-quant")
if str(REPO) not in sys.path:sys.path.insert(0,str(REPO))
from scripts.v22 import fast_a2_r0f_corporate_action_and_nav_forensic_audit as r0f


def reconstruct_with_benchmark_na(*,model,target_map,stock_prices,signal_dates,calendar,cost_bps):
    """Use the original native accounting path; QQQ contributes dates and NA prices only."""
    if any("QQQ" in targets for targets in target_map.values()):
        raise ValueError("QQQ_IS_A_TARGET_POSITION_CANNOT_USE_BENCHMARK_NA")
    if stock_prices.ticker.eq("QQQ").any():
        raise ValueError("STOCK_PRICES_CONTAIN_QQQ")
    dates=pd.DatetimeIndex(calendar).unique().sort_values()
    if dates.empty or not pd.DatetimeIndex(signal_dates).isin(dates).all():
        raise ValueError("CALENDAR_MISSING_SIGNAL_DATE")
    calendar_only=pd.DataFrame({"ticker":"QQQ","trade_date":dates,
                                "open":np.nan,"close":np.nan})
    stock_prices=stock_prices.copy()
    stock_prices["trade_date"]=pd.to_datetime(stock_prices.trade_date)
    native=r0f.reconstruct_path(model=model,target_map=target_map,
                                qfq=pd.concat([stock_prices,calendar_only],ignore_index=True),
                                signal_dates=signal_dates,cost_bps=cost_bps)
    report=native.daily.copy()
    report["benchmark_return"]=np.nan
    report["benchmark_nav"]=np.nan
    return native,report


def check_saved_pre2026_slice():
    weights=pd.read_parquet(PARENT/"PRE2026_FINAL_FIT_INSAMPLE_WEIGHTS.parquet")
    dates=pd.DatetimeIndex(sorted(weights.loc[weights.signal_date.between("2025-01-02","2025-01-06"),"signal_date"].unique()))
    chosen=weights.loc[weights.policy.eq("M_FULL")&weights.signal_date.isin(dates)]
    assert len(dates)==3 and chosen.groupby("signal_date").size().eq(20).all()
    target={pd.Timestamp(date):dict(zip(group.ticker,group.target_weight)) for date,group in chosen.groupby("signal_date")}
    wanted=set(chosen.ticker)|{"QQQ"}
    prices=pd.read_parquet(Path(r"D:\us-tech-quant-data\moomoo\source\prices_qfq\year=2025\prices.parquet"),
                           columns=["ticker","trade_date","open","close"])
    prices=prices.loc[prices.ticker.isin(wanted)&prices.trade_date.between("2025-01-02","2025-01-08")].copy()
    prices["trade_date"]=pd.to_datetime(prices.trade_date)
    calendar=pd.DatetimeIndex(prices.loc[prices.ticker.eq("QQQ"),"trade_date"])
    baseline=r0f.reconstruct_path(model="M_FULL",target_map=target,qfq=prices,
                                  signal_dates=dates,cost_bps=10)
    adapted,report=reconstruct_with_benchmark_na(model="M_FULL",target_map=target,
                                                  stock_prices=prices.loc[prices.ticker.ne("QQQ")],
                                                  signal_dates=dates,calendar=calendar,cost_bps=10)
    pd.testing.assert_frame_equal(baseline.daily,adapted.daily)
    pd.testing.assert_frame_equal(baseline.positions,adapted.positions)
    pd.testing.assert_frame_equal(baseline.trades,adapted.trades)
    assert report[["benchmark_return","benchmark_nav"]].isna().all().all()
    result={"status":"PASS_SAVED_PRE2026_NATIVE_PATH_EXACT",
            "saved_weight_source":"PRE2026_FINAL_FIT_INSAMPLE_WEIGHTS.parquet",
            "policy":"M_FULL","signal_dates":[str(x.date()) for x in dates],
            "daily_rows":len(baseline.daily),"position_rows":len(baseline.positions),
            "trade_rows":len(baseline.trades),"native_daily_positions_trades_exact":True,
            "benchmark_columns":"NA","fit_calls":0,"formal_2026_reveals":0,
            "scope":"Only usable if full stock inputs and independent qualified calendar pass."}
    (HERE/"QQQ_BENCHMARK_NA_ADAPTER_CHECK.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result))


if __name__=="__main__":check_saved_pre2026_slice()
