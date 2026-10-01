"""Behavioral checks of nesting, weighting, chronology, and interpretation."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import meta as m
import train_meta as trainer


class ContextualMetaTests(unittest.TestCase):
    def setUp(self):
        random=np.random.default_rng(716)
        self.p=random.normal(size=(120,12))
        self.z=random.normal(size=(120,4))
        self.basis=random.normal(size=(120,5))
        self.dates=np.repeat(np.array(['2024-02-01','2024-03-01','2024-04-01'],dtype='datetime64[D]'),[20,40,60])
        self.allowed=np.ones(120,bool)
        self.weights=m.date_equal_weights(self.dates,self.allowed)
        self.target=.003*self.p[:,0]-.002*self.p[:,3]+.01*self.p[:,2]*self.z[:,1]+.004*self.z[:,0]
        self.main,self.interaction=m.fit_scalers(self.p,self.z,self.basis,self.weights)

    def fit(self,kind,multiplier=0):
        return m.fit_meta(kind,'internal',self.p,self.z,self.basis,self.target,
            self.dates,self.allowed,self.main,self.interaction,multiplier,sample_weight=self.weights)

    def test_zero_interactions_strictly_nest_static_model(self):
        static=self.fit('M0')
        conditional=self.fit('M1',16)
        conditional.coefficients=np.r_[static.coefficients,np.zeros(48)]
        conditional.intercept=static.intercept
        np.testing.assert_allclose(conditional.predict(self.p,self.z,self.basis),
            static.predict(self.p,self.z,self.basis),rtol=1e-12,atol=1e-14)
        self.assertEqual(len(conditional.feature_order),69)
        self.assertEqual(conditional.feature_order[:21],static.feature_order)
        self.assertTrue(all('age_fraction' not in name for name in m.INTERACTION_FEATURES))

    def test_effective_coefficients_are_prediction_derivatives(self):
        conditional=self.fit('M1',4)
        effective=conditional.effective_coefficients(self.z)['raw']
        for column in (0,2,7,10,11):
            perturbed=self.p.copy()
            perturbed[:,column]+=1e-5
            actual=(conditional.predict(perturbed,self.z,self.basis)-conditional.predict(self.p,self.z,self.basis))/1e-5
            np.testing.assert_allclose(actual,effective[:,column],rtol=1e-7,atol=1e-10)
        diagnostic=conditional.diagnostic_frame(self.p,self.z,self.basis)
        contributions=diagnostic[[f'contribution_{expert}' for expert in m.EXPERT_FEATURES]].sum(axis=1)
        reconstructed=contributions+diagnostic.conditional_intercept+diagnostic.basis_contribution+diagnostic.state_contribution
        np.testing.assert_allclose(reconstructed,diagnostic.prediction_utility,rtol=1e-12,atol=1e-14)

    def test_weighted_solution_satisfies_declared_objective(self):
        conditional=self.fit('M1',64)
        design=conditional.design_chunk(self.p,self.z,self.basis)
        x=np.column_stack([np.ones(len(design)),design])
        penalties=np.r_[0,np.full(21,100),np.full(48,6400)]
        expected=np.linalg.solve(x.T@(x*self.weights[:,None])+np.diag(penalties),
            x.T@(self.target*self.weights))
        np.testing.assert_allclose(np.r_[conditional.intercept,conditional.coefficients],expected,rtol=1e-12,atol=1e-14)
        self.assertLess(conditional.metadata['stationarity_relative_residual'],1e-10)

    def test_duplicate_rows_do_not_inflate_date_information(self):
        reference=self.fit('M1',16)
        indices=np.repeat(np.arange(120),2)
        weights=m.date_equal_weights(self.dates[indices],self.allowed[indices],self.weights[indices]/2)
        main,interaction=m.fit_scalers(self.p[indices],self.z[indices],self.basis[indices],weights)
        duplicate=m.fit_meta('M1','internal',self.p[indices],self.z[indices],self.basis[indices],
            self.target[indices],self.dates[indices],self.allowed[indices],main,interaction,16,sample_weight=weights)
        np.testing.assert_allclose(duplicate.coefficients,reference.coefficients,rtol=1e-10,atol=1e-13)
        np.testing.assert_allclose(duplicate.main_scaler.mean_,reference.main_scaler.mean_,rtol=1e-11,atol=1e-13)

    def test_path_weights_preserved_and_illegal_actions_zero(self):
        dates=np.array(['2025-01-02']*6)
        allowed=np.array([1,1,1,0,1,1],bool)
        # Three legal path-A rows, two legal path-B rows, equal total mass.
        base=np.array([1/6,1/6,1/6,0,1/4,1/4])
        actual=m.date_equal_weights(dates,allowed,base)
        np.testing.assert_allclose(actual,base,rtol=0,atol=1e-15)
        self.assertAlmostEqual(actual[:4].sum(),.5)
        self.assertAlmostEqual(actual[4:].sum(),.5)
        errors=m.date_error_frame(dates,np.zeros(6),np.array([1,1,1,999,3,3]),allowed,base)
        self.assertAlmostEqual(errors.mse.iloc[0],5.)
        self.assertAlmostEqual(errors.mae.iloc[0],2.)

    def test_future_inference_cannot_mutate_train_scalers(self):
        conditional=self.fit('M1',4)
        before=trainer.hash_scaler_arrays(conditional.main_scaler)
        before_interaction=trainer.hash_scaler_arrays(conditional.interaction_scaler)
        conditional.predict(self.p*1000,self.z*1000,self.basis*1000)
        self.assertEqual(before,trainer.hash_scaler_arrays(conditional.main_scaler))
        self.assertEqual(before_interaction,trainer.hash_scaler_arrays(conditional.interaction_scaler))
        expected=np.average(np.column_stack([self.p,self.basis,self.z]),axis=0,weights=self.weights)
        np.testing.assert_allclose(conditional.main_scaler.mean_,expected,rtol=1e-12,atol=1e-14)

    def test_stage_signal_and_label_maturity_guards(self):
        with self.assertRaisesRegex(RuntimeError,'TIME_LEAKAGE'):
            m.fit_meta('M0','validation',self.p,self.z,self.basis,self.target,
                np.array(['2025-01-02']*120),self.allowed,self.main,self.interaction)
        panel=dict(row_dates=np.array(['2024-09-27'],dtype='datetime64[D]'),
                   label_end_dates=np.array(['2024-10-01'],dtype='datetime64[D]'))
        with self.assertRaisesRegex(RuntimeError,'LABEL_MATURITY'):
            trainer.fit_clock(panel,'internal')
        panel['label_end_dates']=np.array(['2024-09-30'],dtype='datetime64[D]')
        self.assertEqual(trainer.fit_clock(panel,'internal')['train_label_end_max'],'2024-09-30')

    def test_constant_state_column_stays_zero_information(self):
        constant=self.z.copy()
        constant[:,2]=20
        main,interaction=m.fit_scalers(self.p,constant,self.basis,self.weights)
        self.assertEqual(main.var_[19],0.)
        self.assertEqual(main.scale_[19],1.)
        conditional=m.fit_meta('M1','internal',self.p,constant,self.basis,self.target,
            self.dates,self.allowed,main,interaction,4,sample_weight=self.weights)
        self.assertAlmostEqual(conditional.coefficients[19],0.,places=14)
        np.testing.assert_allclose(conditional.coefficients[21:].reshape(12,4)[:,2],0,atol=1e-14)

    def test_receipt_handles_overlapping_metadata_without_losing_checked_clock(self):
        model=m.FittedMeta('M0','internal',self.main,self.interaction,np.zeros(21),0.,100.,0.,
            dict(alpha_main=100.,interaction_multiplier=0.,train_signal_max='2099-01-01',
                 train_label_end_max='2099-01-01',fit_rows=120))
        panel=dict(row_dates=self.dates,label_end_dates=self.dates)
        receipt=dict(fits=[],meta_fit_calls=0)
        with tempfile.TemporaryDirectory() as temporary, patch.object(trainer,'OUT',Path(temporary)):
            row=trainer.save_fit(model,panel,'internal',{},receipt)
            self.assertEqual(row['train_signal_max'],'2024-04-01')
            self.assertEqual(row['train_label_end_max'],'2024-04-01')
            self.assertEqual(row['alpha_main'],100.)
            self.assertEqual(receipt['meta_fit_calls'],1)
            self.assertTrue(Path(row['artifact']).is_file())


if __name__=='__main__':
    unittest.main()
