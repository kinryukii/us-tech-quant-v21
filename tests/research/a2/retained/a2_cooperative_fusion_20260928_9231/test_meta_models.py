"""Prediction/attribution behavior checks; these tests never fit a model."""
import numpy as np
import pandas as pd
import pytest
import meta_models as m


def frame():
    f=pd.DataFrame({name:[.2,.4,.6] for name in m.dc.RANK_COLUMNS})
    f['q10_downside_rank']=[.1,.2,.3];f['current_weight']=0.;f['cash_weight']=.95
    f['age']=[0.,300.,30.];f['action']=[0.,.025,.05]
    return f


def actor(name,payload):
    a=m.MetaModels.__new__(m.MetaModels);a.name=name;a.stage='validation';a.payload=payload
    return a


class ProductModel:
    def predict(self,x):return x[:,0]*x[:,1]


class LinearModel:
    coef_=np.arange(11,dtype=float)/100
    def predict(self,x):return x@self.coef_


def test_zero_nnls_does_not_fall_back_to_equal_weights():
    p={'coefficients':np.zeros(6),'normalized_weights':m.normalize_nonnegative(np.zeros(6))}
    scores,diag=actor('fusion_learned_weights',p).predict(frame())
    assert not scores.any()
    assert not np.concatenate([diag[f'normalized_weight_{name}'] for name in m.dc.RANK_COLUMNS]).any()
    with pytest.raises(ValueError):m.normalize_nonnegative(np.array([-1.,0,0,0,0,0]))


def test_nnls_raw_predictions_do_not_use_normalized_weights():
    w=np.array([1.,2.,0,0,0,0]);f=frame()
    scores,diag=actor('fusion_learned_weights',{'coefficients':w,'normalized_weights':m.normalize_nonnegative(w)}).predict(f)
    np.testing.assert_allclose(scores,m.rank_matrix(f)@w)
    np.testing.assert_allclose(scores,sum(diag[f'contribution_{name}'] for name in m.dc.RANK_COLUMNS))
    assert not np.allclose(scores,m.rank_matrix(f)@m.normalize_nonnegative(w))


def test_anchor_and_linear_residual_reconcile_and_no_action_zero_subtraction():
    f=frame();a=actor('fusion_hgb_then_linear',{'anchor_coefficient':.5,'model':LinearModel()})
    scores,diag=a.predict(f)
    np.testing.assert_allclose(scores,diag['anchor_prediction']+diag['residual_prediction'])
    np.testing.assert_allclose(diag['residual_prediction'],sum(diag[f'linear_residual_contribution_{c}'] for c in m.dc.META_COLUMNS))
    assert scores[0]!=0. # The caller, not predict(), applies action-zero subtraction.
    assert m.hgb_anchor_coefficient(np.array([1.,2.]),np.array([-1.,-2.]))==0.


def test_nonlinear_zeroing_sensitivities_are_not_additive_attributions():
    scores,diag=actor('fusion_nonlinear_stacking',{'model':ProductModel()}).predict(frame())
    effect=sum(diag[f'nonadditive_zero_{c}_sensitivity'] for c in m.dc.RANK_COLUMNS)
    np.testing.assert_allclose(effect,2*scores)
    assert not np.allclose(effect,scores)
    assert set(k for k in diag if k.startswith('input_'))=={f'input_{c}' for c in m.dc.META_COLUMNS}


def test_stage_names_cannot_select_unbounded_training_year():
    with pytest.raises(ValueError):m.check_name_stage('fusion_nonlinear_stacking','2026')
