import numpy as np
import pytest
from scripts.research.a2.training.joint_method_space_gross_r6 import target_grid,recipes,fit

def test_reference_utility_grid_is_cost_aware_and_not_account_outcome():
    np.testing.assert_allclose(target_grid([.2,-.2],[.01,.01]),[1.,0.])
    assert recipes()['components_upper']==21
    with pytest.raises(ValueError):target_grid([.1],[.1],cost_bps=20)

def test_future_maturity_rejected_before_native_fit():
    with pytest.raises(ValueError,match='PAST_MATURE'):
        fit('RIDGE',np.ones((2,7)),np.ones(2),np.ones(2),dates=['2022-12-29','2022-12-30'],mature_dates=['2022-12-30','2023-01-05'],cutoff='2023-01-01')
