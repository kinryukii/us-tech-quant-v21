"""Meaningful accounting and intervention edge cases; no original experiment imports."""
import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from cash_attribution import project, adapt, risk_projection, numeric_covariance, cancellation


class CashAttributionTests(unittest.TestCase):
    def test_member_empty_budget_and_cap_loss_identity(self):
        matrix=np.array([[.30,.10],[.20,0.],[.10,.10]])
        coefficients=np.array([.25,.75]); budget=.22
        p=project(matrix,coefficients,slots=2,budget=budget,consensus=True)
        retained=.95-budget
        components=[.05,float(coefficients@(budget-matrix.sum(axis=0))),
                    p['mean'].sum()-p['consensus'].sum(),p['consensus'].sum()-p['capped'].sum(),
                    p['capped'].sum()-p['topk'].sum(),p['topk'].sum()-p['budgeted'].sum()]
        self.assertAlmostEqual(sum(components),1-retained-p['budgeted'].sum())

    def test_topk_is_stable_and_zero_slots_remove_all(self):
        matrix=np.full((3,2),.05)
        p=project(matrix,[.5,.5],2,.95)
        np.testing.assert_allclose(p['topk'],[.05,.05,0])
        np.testing.assert_allclose(project(matrix,[.5,.5],0,.95)['budgeted'],0)

    def test_budget_cap_is_separate_from_topk(self):
        p=project(np.full((3,2),.1),[.5,.5],3,.15)
        self.assertAlmostEqual(p['topk'].sum(),.3)
        self.assertAlmostEqual(p['budgeted'].sum(),.15)

    def test_quantile_zero_member_exact_replacement(self):
        matrix=np.array([[.1,0.,.05],[0.,0.,.1]])
        a=project(matrix,[.2,.35,.45],2,.5,True)
        modified=matrix.copy(); modified[:,1]=0
        b=project(modified,[.2,.35,.45],2,.5,True)
        for k in a:
            np.testing.assert_array_equal(a[k],b[k])

    def test_target_cash_difference_is_signed(self):
        # Shrinkage can ease after removing a divergent, positive opinion;
        # therefore no global monotonic cash assumption is allowed.
        matrix=np.array([[.01,.1]])
        a=project(matrix,[.99,.01],1,.95,True)['budgeted']
        b=project(np.array([[.01,0]]),[.99,.01],1,.95,True)['budgeted']
        self.assertGreater(b.sum(),a.sum())

    def test_locked_risk_over_limit_kills_only_active(self):
        scale=risk_projection(np.array([.1]),np.array([.5]),np.diag([.02**2,.08**2]))
        self.assertEqual(scale,0.)

    def test_risk_projection_recalculates_boundary(self):
        cov=np.diag([.08**2,.01**2])
        w=np.array([.4]); locked=np.array([.2])
        scale=risk_projection(w,locked,cov)
        self.assertTrue(0<scale<1)
        full=np.r_[w*scale,locked]
        self.assertAlmostEqual(float(full@cov@full),.015**2,places=13)

    def test_unknown_covariance_diagonal_preserved(self):
        c=numeric_covariance(['A','MISSING'],{'A':0},np.array([[.0004]]))
        np.testing.assert_allclose(c,np.diag([.0004,.08**2]))

    def test_adapter_preserves_holding_priority_and_eligibility(self):
        active,losses=adapt(['A','B','C'],[.03,.09,.02],{'A':.02,'C':.01},{'A','C'},set(),{},
                           {'A':False,'B':True,'C':True},1,.95)
        self.assertEqual(active,{'A':.02,'B':0.,'C':0.})
        self.assertAlmostEqual(sum(losses.values()),.12)

    def test_reserved_holding_is_not_part_of_cash(self):
        active,_=adapt(['A','B'],[.1,.1],{'A':.4},{'A'},{'A'},{},{'B':True},1,.55)
        self.assertEqual(active,{'B':.1})
        self.assertAlmostEqual(1-.4-sum(active.values()),.5)

    def test_buy_sell_cancellation(self):
        result=cancellation(np.array([[0.,.1]]),np.array([.5,.5]),[.05])
        self.assertAlmostEqual(result['weighted_member_desired_gross_change'],.05)
        self.assertAlmostEqual(result['blended_desired_gross_change'],0)
        self.assertAlmostEqual(result['desired_change_cancellation'],.05)
        self.assertEqual(result['direction_conflict_tickers'],1)

    def test_finished_real_data_accounting(self):
        root=Path(__file__).resolve().parent
        if not (root/'cash_receipt.json').exists():
            self.skipTest('Run attribution first to validate its complete output')
        receipt=json.loads((root/'cash_receipt.json').read_text(encoding='utf-8'))
        self.assertEqual(receipt['scenario_count'],14)
        self.assertEqual(receipt['fit_calls'],0)
        self.assertEqual(receipt['trajectory_replays'],0)
        self.assertEqual(receipt['predictor_loads'],0)
        self.assertTrue(receipt['source_files_unchanged'])
        f=pd.read_csv(root/'cash_signals.csv')
        self.assertEqual(len(f),receipt['signal_rows'])
        self.assertLess(f.identity_error.abs().max(),2e-9)
        self.assertLess(f.projection_max_abs_error.abs().max(),2e-9)
        self.assertTrue(f.loc[~f.certified_nav_available,'ratio_scope'].eq('indicative_uncertified_NAV').all())
        self.assertTrue(f.loc[f.year.eq(2026),'economic_qualification'].eq('not_full_2026_economically_qualified').all())


if __name__=='__main__':
    unittest.main(verbosity=2)
