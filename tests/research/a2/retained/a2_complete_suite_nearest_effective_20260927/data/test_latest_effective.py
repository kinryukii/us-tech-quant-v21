"""Small contract checks for signal-time 13F pool selection."""
import unittest

import pandas as pd

from build_joint_inputs import latest_effective_mask


class LatestEffectiveQuarterTest(unittest.TestCase):
    def setUp(self):
        self.timing=pd.DataFrame({
            'quarter':['2025Q3','2025Q4','2026Q1','2026Q2'],
            'latest_filing_date':pd.to_datetime(['2025-11-14','2026-02-18','2026-05-15','2026-08-14']),
            'quarter_effective_date':pd.to_datetime(['2025-11-21','2026-02-25','2026-05-22','2026-08-21'])})

    def test_old_pool_persists_until_new_effective_date(self):
        frame=pd.DataFrame({
            'signal_date':pd.to_datetime(['2026-01-02','2026-02-24','2026-02-25',
                '2026-05-21','2026-05-22','2026-08-20','2026-08-21']),
            'quarter':['2025Q3','2025Q3','2025Q4','2025Q4','2026Q1','2026Q1','2026Q2']})
        self.assertTrue(latest_effective_mask(frame,self.timing,'quarter').all())

    def test_future_or_superseded_quarter_rejected(self):
        for quarter in ['2025Q4','2025Q2']:
            frame=pd.DataFrame({'signal_date':[pd.Timestamp('2026-01-02')],
                'quarter':[quarter]})
            with self.assertRaises(ValueError):
                latest_effective_mask(frame,self.timing,'quarter')

    def test_filing_must_precede_effective_date(self):
        invalid=self.timing.copy()
        invalid.loc[1,'latest_filing_date']=pd.Timestamp('2026-02-26')
        frame=pd.DataFrame({'signal_date':[pd.Timestamp('2026-02-25')],
            'quarter':['2025Q4']})
        with self.assertRaises(ValueError):
            latest_effective_mask(frame,invalid,'quarter')


if __name__=='__main__':unittest.main()
