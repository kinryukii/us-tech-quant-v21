import sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
import v22_065a_fast3_premarket_0925_edge_attribution_r1 as m

def test_stats_and_consensus():
    x=pd.DataFrame({"account_return":[.1,-.05,.02]})
    assert m.stats(x)["trade_count"] == 3
    assert m.consensus(pd.Series({"qqq_gap_at_signal":.01,"soxx_gap_at_signal":.02})) == "BOTH_UP"

def test_time_bucket_and_no_future_quantile():
    ts=pd.Timestamp("2024-01-02 11:00",tz="UTC")
    assert m.time_bucket(ts.tz_convert("America/New_York")) == "06:00-06:29 ET"
    x=pd.DataFrame({"trade_id":[1,2,3],"signal_timestamp":pd.date_range("2024-01-01",periods=3,tz="UTC"),"study_period":["2018-2022_DEVELOPMENT"]*3,"x":[1.,2.,999.]})
    assert (m.prior_quintiles(x,"x","b") == "INSUFFICIENT_TRAINING").all()

def test_combined_excludes_development():
    x=pd.DataFrame({"study_period":["2018-2022_DEVELOPMENT","2023-2024_VALIDATION","2025-2026_YTD_CONFIRMATION"],"direction":["LONG"]*3,"account_return":[.9,.1,.1]})
    y=m.summaries(x,"direction")
    assert y.loc[y.report_period.eq("COMBINED_VALIDATION_CONFIRMATION"),"trade_count"].iloc[0] == 2
