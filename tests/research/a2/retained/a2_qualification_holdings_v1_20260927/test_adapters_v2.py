import unittest
from types import SimpleNamespace
import pandas as pd
import numpy as np
from adapters_v2 import PolicyV2,FROZEN
from run_v2 import TEST_NAMES,clocks
from joint_neural_v2 import FEATURES


class AdapterCapacityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data=pd.read_parquet(FROZEN/'data/pre2026_joint_context.parquet')
        cls.day=data[data.signal_date.eq('2025-01-02')].head(12).copy()
        cls.day['baseline_hgb']=np.arange(len(cls.day))/1000
        assert len(cls.day)==12
        cls.actors={name:PolicyV2(name,'final') for name in TEST_NAMES}

    def context(self,slots=2,budget=.075):
        return SimpleNamespace(current_weights={'RESERVED':.2},current_units={'RESERVED':1.},
            cash_weight=.8,available_slots=slots,available_weight=budget,
            buy_restricted_tickers=(),reserved_tickers=('RESERVED',),reserved_weights={'RESERVED':.2})

    def test_all_methods_obey_residual_constraints_and_export_zeros(self):
        for name,actor in self.actors.items():
            with self.subTest(policy=name):
                result=actor(self.day,self.context())
                self.assertEqual(set(result.model_decisions),set(self.day.ticker))
                w=np.array(list(result.model_decisions.values()))
                self.assertLessEqual(int((w>1e-8).sum()),2)
                self.assertLessEqual(w.sum(),.07500001)
                self.assertTrue(np.isfinite(w).all())
                self.assertTrue(result.raw_model_outputs)

    def test_zero_budget_has_explicit_feasible_decisions(self):
        for name,actor in self.actors.items():
            with self.subTest(policy=name):
                result=actor(self.day,self.context(0,0.))
                self.assertEqual(sum(result.model_decisions.values()),0.)

    def test_early_session_close(self):
        c=clocks(pd.DatetimeIndex(['2025-07-03','2025-12-24','2026-07-02']))
        self.assertEqual(c[pd.Timestamp('2025-07-03')],pd.Timestamp('2025-07-03T17:00:00Z'))
        self.assertEqual(c[pd.Timestamp('2025-12-24')],pd.Timestamp('2025-12-24T18:00:00Z'))
        self.assertEqual(c[pd.Timestamp('2026-07-02')],pd.Timestamp('2026-07-02T20:00:00Z'))


if __name__=='__main__':unittest.main()
