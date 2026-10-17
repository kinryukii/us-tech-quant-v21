"""Synthetic sensitivity cost transmission; no project data."""
import numpy as np
import pytest
from tests.research.a2.evaluation.test_joint_frozen_history_r3 import fixture, freeze_for
from scripts.research.a2.evaluation.joint_control_sensitivity_r4 import run_pair

@pytest.mark.parametrize("cost",[5,20])
def test_fixed_old_control_sensitivity_transmits_friction_and_preserves_inputs(cost):
    inputs=fixture();parent=freeze_for(*inputs)
    replay,qualification,freeze=run_pair(*inputs,parent,parent.digest(),cost,"a"*64,"synthetic-run")
    assert freeze.path_ids==(f"B_R_00_S{cost}",f"B_R_01_S{cost}")
    assert all(q["mechanism_accounting_consistent"] for q in qualification.values())
    assert replay.daily.certified_nav.isna().all()
    np.testing.assert_allclose(replay.fills.transaction_cost,replay.fills.benchmark_notional*cost/10000)
    assert replay.fills.transaction_fee.eq(0).all()
    assert replay.metadata["scope"]=="SENSITIVITY_NO_SELECTION"
    assert replay.metadata["annual_reset"] is False
    assert freeze.input_sha256==parent.input_sha256

@pytest.mark.parametrize("cost",[0,10,30])
def test_unfrozen_cost_is_rejected_before_account(cost):
    inputs=fixture();parent=freeze_for(*inputs)
    with pytest.raises(ValueError,match="ONLY_OLD"):
        run_pair(*inputs,parent,parent.digest(),cost,"a"*64,"synthetic-run")
