import numpy as np
import accelerated_optimizer as jit
import optimizers as original

def test_jit_prox_preserves_bisection_and_turnover_map():
    r=np.random.default_rng(72)
    for b,n in [(1,1),(1,20),(7,20),(31,20)]:
        values=r.normal(size=(b,n));upper=r.uniform(0,.1,(b,n));budget=r.uniform(0,.95,b);current=r.uniform(0,.2,(b,n));penalty=r.uniform(0,.02,b)
        a=jit.ORIGINAL_PROJECTION(values,upper,budget,current=current,penalty=penalty)
        z=jit.project_box_budget(values,upper,budget,current=current,penalty=penalty)
        np.testing.assert_allclose(a,z,atol=1e-10,rtol=1e-10)
        a=jit.ORIGINAL_DUAL_PROJECTION(r.normal(size=(b,64)),1/6.4)
        assert np.isfinite(a).all()

def test_all_80_round_solvers_preserve_outputs():
    r=np.random.default_rng(73);mu=r.normal(.001,.007,(3,20));raw=r.normal(size=(3,20,20))*.006
    cov=raw@raw.transpose(0,2,1);scenario=r.normal(0,.015,(3,64,20))+mu[:,None,:];current=r.uniform(0,.03,(3,20))
    for method in ['mv','robust','cvar']:
        jit.disable();a,am=original.solve_batch(mu,cov,method=method,scenarios=scenario,current=current)
        jit.enable();b,bm=original.solve_batch(mu,cov,method=method,scenarios=scenario,current=current)
        np.testing.assert_allclose(a,b,atol=1e-8,rtol=1e-8)
        assert [m['iterations'] for m in bm]==[80]*3
        for x,y in zip(am,bm):assert abs(x['objective_utility']-y['objective_utility'])<1e-9
    jit.disable()
