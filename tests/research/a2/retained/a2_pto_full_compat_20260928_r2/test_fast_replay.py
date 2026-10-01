import numpy as np
import pytest
import optimization
from fast_replay import numeric_work_elimination
from cached_replay import eager_risk_load,EagerRiskArchive

@pytest.mark.parametrize('raises',[False,True])
def test_composed_adapters_restore_all_original_functions(tmp_path,raises):
    original_prox=optimization._prox_budget;original_cvar=optimization._smooth_cvar;original_load=np.load
    np.savez_compressed(tmp_path/'risk_cache.npz',x=np.array([-0.,1.,2.]))
    def execute():
        with eager_risk_load(),numeric_work_elimination():
            assert optimization._prox_budget is not original_prox and optimization._smooth_cvar is not original_cvar
            archive=np.load(tmp_path/'risk_cache.npz')
            assert isinstance(archive,EagerRiskArchive)
            assert np.array_equal(archive['x'].view(np.uint64),np.array([-0.,1.,2.]).view(np.uint64))
            if raises:raise RuntimeError('synthetic runtime failure')
    if raises:
        with pytest.raises(RuntimeError,match='synthetic'):execute()
    else:execute()
    assert optimization._prox_budget is original_prox
    assert optimization._smooth_cvar is original_cvar
    assert np.load is original_load
