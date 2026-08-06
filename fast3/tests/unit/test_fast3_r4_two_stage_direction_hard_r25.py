"""R25 contract tests: no external data or result roots are touched."""
from __future__ import annotations
import json, os, uuid
from pathlib import Path
import numpy as np, pandas as pd, pytest
from fast3.models import two_stage_direction_hard_r25 as m

CACHE=Path(os.environ["FAST3_CACHE_ROOT"]); FEATURES=["nine_5m_signed__level","realized_vol_60m__level","vix_level__level","vwap_distance__level"]+[f"f{i}" for i in range(16)]
def sample(rows=820):
 t=pd.date_range("2017-01-01",periods=rows,freq="D",tz="UTC"); rng=np.random.default_rng(25)
 d=pd.DataFrame({"decision_timestamp_et":t,"entry_timestamp_et":t,"horizon_timestamp_et":t+pd.Timedelta(hours=24),"feature_available_at_et":t,"underlying":np.where(np.arange(rows)%2,"QQQ","SOXX"),"label":np.where(np.arange(rows)%3==0,m.UP,np.where(np.arange(rows)%3==1,m.DOWN,m.NO_EVENT)),"event_id":[f"x{i}" for i in range(rows)],"candidate_id":[f"x{i}" for i in range(rows)],"era":"e","uniqueness_weight":1.0})
 for n in FEATURES:d[n]=rng.normal(size=rows)
 return d
def source(): return {"features":FEATURES,"interactions":list(m.base.INTERACTIONS),"r3_summary_hash":"a","r3_model_freeze_hash":"b","r3_audit_hash":"c"}
def test_label_mapping_and_asymmetric_abstain_behavior():
 c=m.prepare_cohort(sample(),FEATURES); sch=m.deterministic_schedule(c); tr,te=m.block_rows(c,sch["blocks"][0]); raw,_=m.score_asymmetric(tr,te,FEATURES,m.PRIMARY_SEED)
 assert raw.p_up.between(0,1).all() and raw.p_down.between(0,1).all()
 out=m.apply_abstention(raw,.60,.10); assert set(out.predicted_label)<= {m.UP,m.DOWN,"ABSTAIN"}; assert (out.loc[out.abstain,"predicted_label"]=="ABSTAIN").all()
def test_threshold_set_and_candidate_freeze_are_immutable_and_deterministic():
 with pytest.raises(m.R25ContractError,match="IMMUTABLE"):m.apply_abstention(pd.DataFrame({"p_up":[.9],"p_down":[.1],"p_event":[.8]}),.51,.01)
 s=source(); sch={"schedule_hash":"x"}; selected={"confidence":.55,"margin":.05}; f=m.candidate_freeze(s,sch,selected,{"D1":"a"},{"code":"b"})
 m.assert_frozen_candidate(f,.55,.05)
 with pytest.raises(m.R25ContractError,match="MUTATION"):m.assert_frozen_candidate(f,.60,.05)
 assert m.candidate_freeze(s,sch,selected,{"D1":"a"},{"code":"b"})["candidate_freeze_sha256"]==f["candidate_freeze_sha256"]
def test_schedule_purge_embargo_and_checkpoint_resume_are_deterministic():
 c=m.prepare_cohort(sample(),FEATURES); sch=m.deterministic_schedule(c); tr,te=m.block_rows(c,sch["blocks"][0]); assert tr.label_end_timestamp_et.max()<pd.Timestamp(sch["blocks"][0]["start"])-pd.Timedelta(hours=48)
 scratch=CACHE/f"r25-{uuid.uuid4().hex}"
 fresh=m.score_block(tr,te,source(),sch,"D1",m.PRIMARY_SEED,scratch)
 resumed=m.score_block(tr,te,source(),sch,"D1",m.PRIMARY_SEED,scratch)
 resumed_twice=m.score_block(tr,te,source(),sch,"D1",m.PRIMARY_SEED,scratch)
 assert m.PREDICTION_INDEX_POLICY == "CANONICAL_RANGE_INDEX_RESET_DROP"
 assert isinstance(fresh.index,pd.RangeIndex) and isinstance(resumed.index,pd.RangeIndex) and isinstance(resumed_twice.index,pd.RangeIndex)
 assert fresh.index.equals(pd.RangeIndex(len(fresh))) and resumed.index.equals(pd.RangeIndex(len(resumed))) and resumed_twice.index.equals(pd.RangeIndex(len(resumed_twice)))
 assert fresh.candidate_id.tolist()==resumed.candidate_id.tolist()==resumed_twice.candidate_id.tolist()
 assert fresh.columns.tolist()==resumed.columns.tolist()==resumed_twice.columns.tolist()
 assert fresh.dtypes.equals(resumed.dtypes) and fresh.dtypes.equals(resumed_twice.dtypes)
 pd.testing.assert_frame_equal(fresh,resumed,check_exact=True,check_dtype=True)
 pd.testing.assert_frame_equal(fresh,resumed_twice,check_exact=True,check_dtype=True)
 round_trip=scratch/"round_trip.parquet"; fresh.to_parquet(round_trip,index=False)
 restored=m.canonicalize_predictions(pd.read_parquet(round_trip))
 assert restored.index.equals(pd.RangeIndex(len(restored)))
 pd.testing.assert_frame_equal(fresh,restored,check_exact=True,check_dtype=True)
 reordered=fresh.iloc[::-1].reset_index(drop=True)
 with pytest.raises(AssertionError): pd.testing.assert_frame_equal(fresh,reordered,check_exact=True,check_dtype=True)
 changed_candidate_id=fresh.copy(); changed_candidate_id.loc[changed_candidate_id.index[0],"candidate_id"]="tampered-candidate-id"
 with pytest.raises(AssertionError): pd.testing.assert_frame_equal(fresh,changed_candidate_id,check_exact=True,check_dtype=True)
def test_selection_is_exactly_four_and_uses_only_two_blocks():
 c=m.prepare_cohort(sample(),FEATURES); sch=m.deterministic_schedule(c); raw={}
 for k,b in zip(("D1","D2"),sch["blocks"][:2]):
  tr,te=m.block_rows(c,b); raw[k],_=m.score_asymmetric(tr,te,FEATURES,m.PRIMARY_SEED)
 rs=[m.candidate_result(raw,a,b) for a,b in m.ALLOWED_CANDIDATES]; assert len(rs)==4; assert m.choose_candidate(rs)["confidence"] in (.55,.60)
