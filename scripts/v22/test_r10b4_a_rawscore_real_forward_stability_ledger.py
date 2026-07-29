import unittest
import pandas as pd
import numpy as np
from scripts.v22.r10b4_a_rawscore_real_forward_stability_ledger import rank_percentile, metrics, EXPECTED

class R10B4UnitTests(unittest.TestCase):
    def test_rank_one_is_highest_percentile(self):
        p=rank_percentile(pd.Series([1,10]),pd.Series([10,10]))
        self.assertEqual(p.iloc[0],1.0); self.assertEqual(p.iloc[1],0.0)
    def test_percentile_order(self):
        p=rank_percentile(pd.Series([1,2,3]),pd.Series([3,3,3]))
        self.assertGreater(p.iloc[0],p.iloc[1]); self.assertGreater(p.iloc[1],p.iloc[2])
    def test_expected_real_strategies_exclude_proxy(self):
        self.assertEqual(EXPECTED, {"A1","B","C","D","E_R1"})
        self.assertNotIn("PROXY", EXPECTED)
    def test_top5_uses_highest_raw_score(self):
        s=pd.DataFrame({"signal_date":pd.to_datetime(["2026-01-02"]*6),"ticker":list("ABCDEF"),"a_raw_score":[1,2,3,4,5,6]})
        l=s[["signal_date","ticker"]].copy(); l["label_5d_mature"]=True; l["forward_excess_5d"]=[0,0,0,0,1,1]
        self.assertAlmostEqual(metrics(s,l,5)["top5_mean_excess"],.4)
    def test_unmatured_labels_are_excluded(self):
        s=pd.DataFrame({"signal_date":pd.to_datetime(["2026-01-02"]),"ticker":["A"],"a_raw_score":[1.]})
        l=s[["signal_date","ticker"]].copy(); l["label_20d_mature"]=False; l["forward_excess_20d"]=np.nan
        self.assertEqual(metrics(s,l,20)["mature_signal_date_count"],0)

if __name__ == '__main__': unittest.main()
