"""R26 contract tests; all generated files stay in FAST3_CACHE_ROOT."""
from __future__ import annotations
import json, os
from pathlib import Path
import numpy as np, pandas as pd, pytest
from sklearn.linear_model import Ridge
from fast3.models import two_stage_economic_value_hard_r26 as m

FEATURES=["nine_5m_signed__level","realized_vol_60m__level","vix_level__level","vwap_distance__level"]+[f"f{i}" for i in range(16)]
def rows():
 d=pd.DataFrame({"candidate_id":["a","b"],"decision_timestamp_et":pd.to_datetime(["2020-01-02","2020-01-03"],utc=True),"fold_train_end":pd.to_datetime(["2020-01-01","2020-01-02"],utc=True),"p_up":[.8,.2],"p_down":[.1,.7],"confidence":[.8,.7],"margin":[.7,.5],"direction":["UP_FIRST","DOWN_FIRST"],"session_code":[1,2],"underlying":["QQQ","SOXX"],"gross_return":[.01,-.01],"actual_exit_timestamp_et":pd.to_datetime(["2020-01-03","2020-01-04"],utc=True),"target_hit":[True,False]})
 for i,x in enumerate(FEATURES): d[x]=float(i)
 return d
def test_exact_ridge_and_target_reproduction():
 d=rows(); assert np.allclose(m.reproduce_economic_target(d),[.009,-.011]); x=m.economic_feature_frame(d,FEATURES); head=m.fit_economic_head(x,m.reproduce_economic_target(d)); assert isinstance(head["model"],Ridge); assert head["model"].get_params()["alpha"]==10.0 and head["model"].get_params()["solver"]=="lsqr" and head["model"].get_params()["tol"]==1e-6
def test_rejects_missing_authoritative_target_and_in_sample_probabilities():
 with pytest.raises(m.R26ContractError,match="AUTHORITATIVE"):m.assert_authoritative_economic_target(rows().drop(columns=["gross_return"]))
 bad=rows(); bad.loc[0,"fold_train_end"]=bad.loc[0,"decision_timestamp_et"]
 with pytest.raises(m.R26ContractError,match="IN_SAMPLE"):m.assert_strict_oof(bad)
def test_threshold_set_and_future_columns_are_immutable():
 assert m.ECONOMIC_THRESHOLDS==(0.0,.0005,.001,.002); d=rows(); d["predicted_net_10bps"]=[0.,.003]
 with pytest.raises(m.R26ContractError,match="IMMUTABLE"):m.apply_economic_gate(d,.6,.1,.003)
 assert not set(m.economic_feature_names(FEATURES)).intersection(m.FUTURE_OR_TARGET_COLUMNS)
def test_frozen_r25_candidate_hash_and_threshold_loading(tmp_path):
 p=tmp_path/"R25_CANDIDATE_FREEZE.json"; v={"confidence":.6,"margin":.1}; v["candidate_freeze_sha256"]=m.stable_hash(v); p.write_text(json.dumps(v)); assert m.load_r25_candidate(str(p))["confidence"]==.6
 p.write_text(json.dumps({**v,"margin":.2}));
 with pytest.raises(m.R26ContractError,match="HASH"):m.load_r25_candidate(str(p))
def test_predeclared_selection_tie_break_prefers_safer_threshold_last():
 x={"pooled_mean_net_return_10bps":.01,"both_d1_d2_positive":True,"concentration":.2,"pooled_mean_net_return_20bps":.009,"trade_count":100,"selection_gate":True}
 assert m.choose_threshold([{**x,"threshold":0.0},{**x,"threshold":.002}])["threshold"]==.002
