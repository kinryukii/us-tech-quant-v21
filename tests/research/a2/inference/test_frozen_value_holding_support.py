"""Synthetic-only causal value-support binding; no model/real data/account use."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import hashlib,json
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.inference import frozen_a94_values as c

def ref(path,obj):
 path.write_text(json.dumps(obj,sort_keys=True),encoding="utf-8")
 return {"path":str(path),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()}

@pytest.fixture
def scenario(tmp_path,monkeypatch):
 features=list(c.values.feature_binding()["features"]);dates=["2026-01-02","2026-01-05"]
 names={dates[0]:["S%03d"%i for i in range(100)],dates[1]:["S%03d"%i for i in range(1,101)]}
 rows=[]
 for day in dates:
  for i,ticker in enumerate(names[day]):rows.append({"signal_date":pd.Timestamp(day),"ticker":ticker,"security_id":"SID_"+ticker,"feature_available":True,"input_present":True,"feature_source":next(iter(c.values.SOURCES)),**{k:float(i)/100 for k in features}})
 base=pd.DataFrame(rows);extra=base.iloc[[0]].copy();extra["signal_date"]=pd.Timestamp(dates[1]);support=pd.concat([base,extra],ignore_index=True)
 fake=lambda name:ref(tmp_path/(name+".json"),{"synthetic":name})
 poolref=fake("daily100");feature_ref=fake("features");identity_ref=fake("identity");flags_ref=fake("flags");support_ref=fake("support");source_ref=fake("source");universe_ref=fake("universe")
 original={"origin":"CONSENSUS_TOP100_FULL_PIT32_APPLICATION_POOL","universe_variant":"CONSENSUS100","universe_source_ref":universe_ref,"universe_contract_sha256":c.values.digest({"synthetic_consensus":100}),"source_ref":source_ref,"physical_pool_ref":poolref,"feature_order_sha256":c.values.digest(features),"sessions":{day:c.pool_session_commitment(base.loc[base.signal_date.eq(pd.Timestamp(day))],features) for day in dates}}
 first={}
 for day in dates:
  for ticker in names[day]:first.setdefault(ticker,day)
 proof={"origin":"CONSENSUS100_ASOF_HOLDING_VALUE_SUPPORT","role":"OFFPOOL_HOLDING_VALUE_CONTINUITY_ONLY","domain_policy":"CURRENT_POOL_UNION_PREVIOUSLY_EFFECTIVE_MEMBERS_ASOF","no_future_first_membership":True,"no_new_buy_eligibility":True,"universe_variant":"CONSENSUS100","universe_source_ref":universe_ref,"universe_contract_sha256":original["universe_contract_sha256"],"feature_order_sha256":original["feature_order_sha256"],"daily_top100_sessions":original["sessions"],"daily_top100_tickers":names,"first_membership_by_ticker":first}
 manifest={"task_id":c.profile.ALL_TASK,"physical_support_ref":support_ref,"physical_daily_top100_ref":poolref,"source_features_ref":feature_ref,"source_dated_identity_ref":identity_ref,"source_flags_ref":flags_ref}
 raw={"application_pool_origin":original["origin"],"universe_variant":"CONSENSUS100","universe_source_ref":universe_ref,"original_universe_contract":{"synthetic_consensus":100},"ordered_32_features":features}
 auth=SimpleNamespace(task_id=c.profile.ALL_TASK,provenance_json="")
 loader=SimpleNamespace(authority=auth,_check=lambda:{"raw_selector_binding":raw})
 def freeze(frame=support):
  proof["sessions"]={str(pd.Timestamp(day).date()):c.pool_session_commitment(g,features) for day,g in frame.groupby("signal_date",sort=False)}
  manifest["value_holding_support"]=deepcopy(proof);mr=ref(tmp_path/"manifest.json",manifest)
  q={"full_pit32_pool":original,"full_pit32_value_support":{**proof,"support_manifest_ref":mr,"source_ref":source_ref}}
  qr=ref(tmp_path/"qualification.json",q);auth.provenance_json=json.dumps({"source_qualification_ref":qr,"source_refs":{"action_inputs":source_ref}})
 monkeypatch.setattr(c.profile,"_roots",lambda:(tmp_path.resolve(),))
 def dates_only(a,ds):
  assert a is auth
  if not (pd.DatetimeIndex(ds)>=pd.Timestamp(dates[0])).all() or not (pd.DatetimeIndex(ds)<=pd.Timestamp(dates[-1])).all():raise ValueError("SYNTHETIC_AUTHORITY_DATE_BOUNDARY")
 monkeypatch.setattr(c.admission,"validate_descriptive_input_dates",dates_only);freeze()
 return SimpleNamespace(loader=loader,base=base,support=support,proof=proof,manifest=manifest,freeze=freeze,auth=auth,feature_ref=feature_ref)

def test_new_support_preserves_original100_binding_and_original_flags(scenario):
 x=scenario;before=x.support.copy(deep=True)
 original=c.bind_pool(x.loader,x.base);bound=c.bind_value_support(x.loader,x.support)
 pd.testing.assert_frame_equal(original.frame,x.base.reset_index(drop=True));pd.testing.assert_frame_equal(bound.frame,x.support.reset_index(drop=True));pd.testing.assert_frame_equal(x.support,before)
 assert bound.frame.groupby("signal_date").size().tolist()==[100,101]
 with pytest.raises(ValueError,match="FULL_POOL_KEYS_OR_CONTENT_CHANGED"):c.bind_pool(x.loader,x.support)

def test_future_member_rejected_even_if_support_commitment_itself_matches(scenario):
 x=scenario;future=x.base.loc[x.base.ticker.eq("S100")].copy();future["signal_date"]=pd.Timestamp("2026-01-02");frame=pd.concat([x.support,future],ignore_index=True);x.freeze(frame)
 with pytest.raises(ValueError,match="FUTURE_FIRST_MEMBERSHIP_FORBIDDEN"):c.bind_value_support(x.loader,frame)

def test_false_early_first_membership_is_recomputed_from_daily100(scenario):
 x=scenario;x.proof["first_membership_by_ticker"]["S100"]="2026-01-02";x.freeze()
 with pytest.raises(ValueError,match="FIRST_MEMBERSHIP_CHANGED"):c.bind_value_support(x.loader,x.support)

def test_changed_current100_value_rejected_even_when_support_proof_is_updated(scenario):
 x=scenario;frame=x.support.copy();frame.loc[0,"ret_1d"]+=.123;x.freeze(frame)
 with pytest.raises(ValueError,match="ORIGINAL_TOP100_VALUES_CHANGED"):c.bind_value_support(x.loader,frame)

@pytest.mark.parametrize("field",["no_future_first_membership","no_new_buy_eligibility"])
def test_weakened_domain_claim_rejected(scenario,field):
 x=scenario;x.proof[field]=False;x.freeze()
 with pytest.raises(ValueError,match="VALUE_SUPPORT_ROLE_REQUIRED"):c.bind_value_support(x.loader,x.support)

def test_support_cannot_supply_new_buy_flag(scenario):
 x=scenario;frame=x.support.assign(new_buy_eligible=True)
 with pytest.raises(ValueError,match="CANNOT_SUPPLY_BUY_FLAGS"):c.bind_value_support(x.loader,frame)

def test_other_task_and_replaced_physical_source_rejected(scenario):
 x=scenario;x.auth.task_id=c.profile.TASK
 with pytest.raises(ValueError,match="VALUE_SUPPORT_SCOPE_REQUIRED"):c.bind_value_support(x.loader,x.support)
 x.auth.task_id=c.profile.ALL_TASK;Path(x.feature_ref["path"]).write_text("changed",encoding="utf-8")
 with pytest.raises(ValueError):c.bind_value_support(x.loader,x.support)
