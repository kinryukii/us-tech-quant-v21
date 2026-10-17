"""Independent synthetic forecast-coordinate checks; no artifact/data reads or fits."""
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import stateful_account as policy


def inputs():
    mu=np.linspace(-.02,.10,21)
    vol5=np.linspace(.01,.08,21)
    raw=np.arange(21)<20
    return mu,vol5,raw


def test_identity_view_posterior_matches_dense_equation_with_fixed_raw_reference():
    mu,vol5,raw=inputs()
    sigma=.025
    covariance=np.diag(vol5**2)
    prior=covariance @ (raw.astype(float)/20.)
    scaled=.05*covariance
    expected=prior+scaled @ np.linalg.solve(scaled+sigma**2*np.eye(21),mu-prior)
    actual=policy.forecast_overlay('black_litterman',mu,sigma,vol5,raw)
    np.testing.assert_allclose(actual,expected,rtol=1e-13,atol=1e-15)
    # A held stock outside Raw20 still receives its identity view, with zero prior.
    assert prior[-1]==0. and actual[-1]>0.


def test_missing_view_or_risk_fails_locally_without_reforming_reference_pool():
    mu,vol5,raw=inputs()
    healthy=policy.forecast_overlay('black_litterman',mu,.025,vol5,raw)
    mu[2]=np.nan
    vol5[4]=np.nan
    vol5[6]=-.1
    actual=policy.forecast_overlay('black_litterman',mu,.025,vol5,raw)
    missing=np.isin(np.arange(21),[2,4,6])
    assert np.isnan(actual[missing]).all()
    np.testing.assert_array_equal(actual[~missing],healthy[~missing])
    assert raw.sum()==20
    assert np.isnan(policy.forecast_overlay('black_litterman',mu,np.nan,vol5,raw)).all()


def test_zero_risk_variance_does_not_invent_posterior_return():
    mu,vol5,raw=inputs()
    vol5[3]=0.
    actual=policy.forecast_overlay('black_litterman',mu,.025,vol5,raw)
    assert actual[3]==0.
    assert np.isfinite(actual).all()
    # Zero view uncertainty with positive variance is the exact identity view.
    vol5[3]=.04
    np.testing.assert_allclose(policy.forecast_overlay('black_litterman',mu,0.,vol5,raw),mu)


@pytest.mark.parametrize('raw_count',[19,21])
def test_noncomplete_raw20_returns_unavailable_without_mutating_membership(raw_count):
    mu,vol5,_=inputs()
    raw=np.arange(21)<raw_count
    originals=[v.copy() for v in (mu,vol5,raw)]
    actual=policy.forecast_overlay('black_litterman',mu,.025,vol5,raw)
    assert np.isnan(actual).all()
    for value,original in zip((mu,vol5,raw),originals):
        np.testing.assert_array_equal(value,original)


def test_shrink_and_none_are_forecast_copies_and_preserve_missingness():
    mu,vol5,raw=inputs()
    mu[2]=np.nan
    original=mu.copy()
    shrink=policy.forecast_overlay('return_shrink',mu,.025,vol5,raw)
    np.testing.assert_allclose(shrink,.5*original,equal_nan=True)
    unmodified=policy.forecast_overlay('none',mu,.025,vol5,raw)
    np.testing.assert_allclose(unmodified,original,equal_nan=True)
    unmodified[0]=999.
    np.testing.assert_allclose(mu,original,equal_nan=True)
    with pytest.raises(ValueError,match='UNREGISTERED_FORECAST_OVERLAY'):
        policy.forecast_overlay('new_mode',mu,.025,vol5,raw)


def test_action_and_gross_receive_same_transformed_mu_without_state_or_selector_mutation(monkeypatch):
    mu,vol5,raw=inputs()
    packet={'mu':mu[None,:].copy(),'sigma':np.array([.025]),'lineage':np.array(['SYNTHETIC'])}
    captures={}
    proposed=np.zeros(21)
    proposed[1:20]=.045
    proposed[-1]=.10
    selected=np.flatnonzero(proposed>0)
    class FrozenActionSpy:
        def __init__(self,value,*args):
            self.value=value
        def __call__(self,di,context):
            captures['action_mu']=self.value[di].copy()
            captures['units']=context.current_units.copy()
            return policy.TargetDecision(proposed[None,:].copy(),explicit_mask=np.ones((1,21),bool))
    def gross_spy(mode,relative,value,sigma,covariance):
        captures.update(gross_mode=mode,gross_mu=value.copy(),covariance=covariance.copy(),relative=relative.copy())
        return .5
    monkeypatch.setattr(policy,'reference_policy_class',lambda:FrozenActionSpy)
    monkeypatch.setattr(policy,'exposure_budget',gross_spy)
    units=np.zeros((1,21));units[0,-1]=10.
    current=np.zeros((1,21));current[0,-1]=.10
    ctx=SimpleNamespace(path_ids=('synthetic',),signal_date=pd.Timestamp('2023-01-03'),
        tickers=tuple('T%02d'%i for i in range(21)),max_positions=20,current_units=units,
        current_weights=current,cash=np.array([2700.]),nav=np.array([3000.]),
        available_budget=np.array([1.]),decision_mask=np.ones((1,21),bool),
        buy_allowed=np.ones((1,21),bool),holding_age=np.ones((1,21),int),
        entry_date=np.full((1,21),np.datetime64('2023-01-02')),
        entry_price=np.ones((1,21)),entry_execution_open=np.ones((1,21)))
    candidate={'candidate_id':'synthetic','value_model':'synthetic','action':'stateful',
        'gross':'dynamic','control':'none','forecast':'black_litterman','risk':'diag20_reference'}
    top=raw[None,:].copy();qual=np.ones((1,21),bool)
    originals=(packet['mu'].copy(),top.copy(),units.copy(),current.copy())
    overlay=policy.StatefulOverlay([candidate],{'synthetic':packet},top,qual,vol5[None,:].copy())
    decision=overlay(0,ctx)
    expected=policy.forecast_overlay('black_litterman',mu,.025,vol5,raw)
    np.testing.assert_array_equal(captures['action_mu'],expected)
    np.testing.assert_array_equal(captures['gross_mu'],expected[selected])
    np.testing.assert_array_equal(captures['covariance'],np.diag(vol5[selected]**2))
    assert captures['gross_mode']=='dynamic'
    np.testing.assert_allclose(decision.weights[0,selected],.5*proposed[selected]/proposed.sum())
    for actual,original in zip((packet['mu'],top,units,current),originals):
        np.testing.assert_array_equal(actual,original)
    assert overlay.audit[0]['forecast_overlay_fits']==0
