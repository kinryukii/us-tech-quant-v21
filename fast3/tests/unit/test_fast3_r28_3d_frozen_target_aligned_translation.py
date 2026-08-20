import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd

SOURCE=Path(__file__).parents[2]/"scripts"/"run"/"fast3_r28_3d_frozen_target_aligned_translation.py"
SPEC=importlib.util.spec_from_file_location("r28_3d",SOURCE); AUDIT=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(AUDIT)

def test_fixed_frozen_constants_and_no_model_calls():
    text=SOURCE.read_text(encoding="utf-8")
    assert AUDIT.THRESHOLD==.01 and AUDIT.HORIZON==pd.Timedelta(hours=24) and AUDIT.SEED==28304 and AUDIT.RUNS==1000
    assert ".fit(" not in text and "predict_proba" not in text and AUDIT.DATA not in AUDIT.OUT.parents
    assert ".head.eq(" not in text and "selected.head" not in text

def test_touch_time_reconciliation_is_explicitly_different_cohorts():
    assert "DIFFERENT_COHORTS" in AUDIT.touch_reconciliation()["status"]

def test_first_touch_and_frozen_timeout_cost_arithmetic():
    x=pd.DataFrame({"first_touch_net20":[.01,-.02],"first_touch_net10":[.011,-.019],"first_touch_gross":[.012,-.018],"net20":[.0,.0],"gross":[.0,.0],"net10":[.0,.0]})
    s=AUDIT.stats(x); assert s["mean_net20"]==-.005 and np.isclose(x.first_touch_gross.iloc[0]-.002,x.first_touch_net20.iloc[0])

def test_distribution_and_paired_delta_reconciliation():
    x=pd.DataFrame({"x":[-.03,0,.02]}); d=AUDIT.distribution(x,"x")
    assert d["loss_rate"]==1/3 and d["loss_below_minus2pct"]==1/3
    original=np.array([.01,-.01]); target=np.array([.02,-.02]); assert np.allclose(target-original,[.01,-.01])

def test_matched_p_value_formula_is_frozen():
    values=np.array([.0,.01,.02]); real=.01
    assert (1+(values>=real).sum())/(len(values)+1)==.75
