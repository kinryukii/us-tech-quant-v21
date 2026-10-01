import numpy as np
from scipy.optimize import minimize, linprog
from policy import prox_box_budget,solve_quadratic,solve_cvar,cvar_values,isolate_axis,PTOBatchPolicy

def test_exact_l1_prox_with_budget():
    z=np.array([[.2,.08,.3]]);c=np.array([[.04,.02,.01]]);u=np.full_like(z,.1);b=np.array([.15]);t=np.array([.03])
    w=prox_box_budget(z,c,t,u,b)
    f=lambda v:.5*np.sum((v-z[0])**2)+t[0]*np.abs(v-c[0]).sum()
    r=minimize(f,np.ones(3)*.05,bounds=[(0,.1)]*3,constraints={'type':'ineq','fun':lambda v:.15-v.sum()},method='SLSQP',options={'ftol':1e-12})
    assert r.success and abs(f(w[0])-r.fun)<1e-7
    assert w.sum()<=.15+1e-9

def test_quadratic_against_independent_scalar_solver():
    mu=np.array([[.003,.002,-.001]]);cov=np.array([[[.002,.0003,0],[.0003,.003,0],[0,0,.001]]])
    cur=np.array([[.03,.02,.01]]);upper=np.full_like(cur,.1);budget=np.array([.15])
    w,meta=solve_quadratic(mu,cov,cur,upper,budget)
    f=lambda v:-mu[0]@v+2*v@cov[0]@v+.001*np.abs(v-cur[0]).sum()
    r=minimize(f,cur[0],method='SLSQP',bounds=[(0,.1)]*3,constraints={'type':'ineq','fun':lambda v:.15-v.sum()},options={'ftol':1e-12,'maxiter':200})
    assert r.success and f(w[0])-r.fun<1e-6
    assert meta['solver_residual'][0]<1e-5

def test_cvar_with_fractional_tail_and_joint_base():
    s=np.array([[[.1,0],[-.2,.2],[.2,-.1],[0,.05]]]);w=np.array([[.1,.05]])
    base=np.array([[-.01,0,.03,0]])
    loss=-(s[0]@w[0]+base[0])
    got=cvar_values(s,w,tail=.375,base_returns=base)
    expect=(np.sort(loss)[-1]+.5*np.sort(loss)[-2])/1.5
    assert np.allclose(got,expect)
    val,g=cvar_values(s,w,tail=.375,with_gradient=True,base_returns=base)
    direction=np.array([[.01,-.01]])
    finite=(cvar_values(s,w+1e-6*direction,tail=.375,base_returns=base)-val)/1e-6
    assert np.allclose(finite,(g*direction).sum(1),atol=1e-7)

def test_cvar_feasible_best_iterate_and_gap():
    rng=np.random.default_rng(3);s=rng.normal(0,.02,(2,40,3));mu=np.array([[.01,.006,.004],[.002,.003,.001]])
    s+=mu[:,None,:];cur=np.zeros((2,3));u=np.full_like(cur,.1);b=np.array([.2,.2])
    w,m=solve_cvar(mu,s,cur,u,b)
    assert (w>=0).all() and (w<=u+1e-9).all() and (w.sum(1)<=b+1e-8).all()
    assert np.isfinite(m['objective']).all() and (m['solver_residual']>=-1e-10).all()
    assert (m['objective']<=1e-8).all()

def test_component_experiments_share_budget_and_cash_projection():
    p=np.array([[.08,.02,.01],[.02,.02,0]]);r=np.array([[.03,.07,0],[.02,.01,.01]])
    c=np.array([[.04,.03,0],[.01,.02,0]]);u=np.full_like(c,.1);b=np.array([.15,.15])
    cash=isolate_axis(p,r,c,['cash','cash'],u,b)
    assert np.allclose(cash.sum(1),p.sum(1))
    assert np.allclose(cash[0]/cash[0].sum(),r[0]/r[0].sum())
    for axis in ['buy','sell','joint']:
        w=isolate_axis(p,r,c,[axis,axis],u,b)
        assert (w.sum(1)<=b+1e-8).all() and (w>=0).all()

def test_missing_prediction_held_name_enters_fixed_risk_and_budget(monkeypatch):
    import policy
    n=21;current=np.zeros((1,n));current[0,20]=.08
    forecast=np.full((2,n),.01);forecast[:,20]=np.nan
    class Streams:
        def at(self,date,stream):return forecast
    obj=object.__new__(PTOBatchPolicy)
    obj.tickers=[str(i) for i in range(n)];obj.date=None;obj.streams=Streams()
    obj.risk_cov={'diagonal':np.full((n,n),.01)};obj.failures=[]
    seen={}
    def capture(mu,cov,cur,upper,budget,uncertainty=None):
        seen.update(mu=mu.copy(),budget=budget.copy(),upper=upper.copy())
        return np.zeros_like(mu),dict(objective=np.zeros(1),solver_residual=np.zeros(1),iterations=np.zeros(1),status=np.array(['SOLVED_TOLERANCE']))
    monkeypatch.setattr(policy,'solve_quadratic',capture)
    ctx=dict(current_weights=current,decision_mask=np.ones((1,n),bool),buy_allowed_mask=np.ones((1,n),bool),
        reserved_mask=np.zeros((1,n),bool),available_slots=np.array([20]),available_weight=np.array([.95]))
    target,decided,meta=obj._solve([dict(stream='ridge',risk='diagonal',optimizer='mean_variance',strategy='test')],ctx)
    assert np.allclose(seen['budget'],.87)
    assert np.count_nonzero(seen['upper'])==19
    assert np.allclose(seen['mu'][0,:19],.01-4*.01*.08)
    assert not decided[0,20] and meta['selected_count'][0]==19
