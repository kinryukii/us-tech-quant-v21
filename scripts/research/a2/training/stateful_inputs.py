"""V24 A input adapter: frozen PIT32 and unchanged supported-event five-session labels.
No fitting, cash entitlement inference, selector refit, or economic-result readers.
"""
from __future__ import annotations
import hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scripts.common.storage_paths import resolve

REPO=Path(__file__).resolve().parents[4]
PARENT=Path("D:/us-tech-quant-results/A2_STATEFUL_ACTION_AND_CASH_PRE2026_TEST2026_R1")
BOUNDARY=pd.Timestamp("2026-01-01")
LABEL="SHAREHOLDER_OPEN_T_PLUS_1_TO_T_PLUS_6_5_SESSION_RETURN_SUPPORTED_EVENTS_FAIL_CLOSED"
ALLOWED_SOURCES=("FROZEN_RAW_A2_TRAINING_MATRIX_32","FROZEN_RAW_A2_FULL_PIT32_LEDGER_PROJECTION")
FEATURES=tuple("ret_1d ret_3d ret_5d ret_10d ret_20d ret_40d ret_60d ret_120d price_vs_ma10 price_vs_ma20 price_vs_ma50 price_vs_ma120 ma10_vs_ma20 ma20_vs_ma50 ma50_vs_ma120 realized_vol_5d realized_vol_10d realized_vol_20d realized_vol_60d downside_vol_20d upside_vol_20d distance_from_high_20d distance_from_high_60d distance_from_low_20d distance_from_low_60d max_drawdown_20d max_drawdown_60d avg_volume_20d avg_volume_60d volume_ratio_5d_20d volume_ratio_20d_60d avg_dollar_volume_20d".split())
SOURCES={
 "value_training_panel":{"path":str(PARENT/"cache/value_training_panel_shareholder_pitguarded_r1.parquet"),"sha256":"db68417c267bf80daeb7f7564e91dc99e25ef9dc5c413c7b24583e273f05c174","date":"signal_date","rows":907902},
 "prediction_feature_panel":{"path":str(PARENT/"cache/prediction_feature_panel_pitguarded_r1.parquet"),"sha256":"dfe110afcdf13c4b0b43f3402cb844fcda02073d6ed8b6d05a278fbec8495427","date":"signal_date","rows":1003523},
 "calendar":{"path":str(PARENT/"cache/calendar_r1.parquet"),"sha256":"38aaf0fad388e38aa87d04ab8ab10a004a889cd0ef20e7774be4a62bb3a155b5","date":"trade_date","rows":1508},
 "raw_market_prices":{"path":"D:/us-tech-quant-results/TOP20_SELECTOR_CHALLENGER_PRE2026_TEST2026_R1/work/full848raw_pre2026.parquet","sha256":"20057f59e6188ac4a2d35923ec8c1689e43380aefbbc87a1a7c78312616693f8","date":"trade_date","rows":1154732}}
TRAIN_FLAGS=("signal_date","ticker","feature_available","feature_source","label_available","account_event_unhandled","label_mature_date","label_coordinate")
PRED_FLAGS=("signal_date","ticker","feature_available","feature_source","input_present","stock_forecast_input_present","raw_selector_input_present","decision_information_present_union","raw_top20_set_complete","raw_top20_set_count","is_raw_top20","is_max_group","new_buy_eligible","security_id","active_13f_quarter")
_PREPARED={}

def sha(path):
 with Path(path).open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()

def _bool(frame,column):
 s=frame[column]
 if s.isna().any() or not s.isin([True,False,0,1]).all():raise ValueError("INVALID_FLAG:"+column)
 return s.astype(bool)

def _flags(frame,training=False):
 frame=frame.copy();frame["signal_date"]=pd.to_datetime(frame.signal_date)
 if frame.signal_date.isna().any() or frame.signal_date.ge(BOUNDARY).any() or frame.duplicated(["signal_date","ticker"]).any():raise ValueError("INPUT_KEYS_OR_TIME_BOUNDARY")
 legal=frame.feature_source.isin(ALLOWED_SOURCES)
 if not _bool(frame,"feature_available").eq(legal).all():raise ValueError("PIT_SOURCE_FLAG_NOT_BOUND")
 if training:
  frame["label_mature_date"]=pd.to_datetime(frame.label_mature_date)
  if not frame.label_coordinate.eq(LABEL).all():raise ValueError("SHAREHOLDER_LABEL_CHANGED")
  available=_bool(frame,"label_available");_bool(frame,"account_event_unhandled")
  if frame.loc[available,"label_mature_date"].isna().any() or frame.loc[available,"label_mature_date"].ge(BOUNDARY).any():raise ValueError("UNMATURED_AVAILABLE_LABEL")
 else:
  stock=_bool(frame,"stock_forecast_input_present");raw=_bool(frame,"raw_selector_input_present")
  if not stock.eq(_bool(frame,"feature_available")).all() or not stock.eq(_bool(frame,"input_present")).all():raise ValueError("STOCK_DIAGNOSTIC_FLAG_CHANGED")
  if not _bool(frame,"decision_information_present_union").eq(stock|raw).all():raise ValueError("GENERIC_INFORMATION_UNION_CHANGED")
  if not _bool(frame,"new_buy_eligible").eq(_bool(frame,"is_raw_top20")&_bool(frame,"is_max_group")).all():raise ValueError("FROZEN_BUY_BIT_CHANGED")
 return frame

def _training_masks(flags,fold):
 usable=_bool(flags,"feature_available")&_bool(flags,"label_available")&~_bool(flags,"account_event_unhandled")
 train=usable&flags.signal_date.lt(fold["calibration_start"])&flags.label_mature_date.lt(fold["calibration_start"])
 cal=usable&flags.signal_date.isin(fold["calibration_sessions"])&flags.label_mature_date.lt(fold["cutoff_exclusive"])
 return train,cal

def _join_vectors(flags,vectors,features=FEATURES):
 if vectors.duplicated(["signal_date","ticker"]).any():raise ValueError("DUPLICATE_VECTOR_KEY")
 expected=pd.MultiIndex.from_frame(flags.loc[flags.feature_available,["signal_date","ticker"]]);actual=pd.MultiIndex.from_frame(vectors[["signal_date","ticker"]])
 if len(actual)!=len(expected) or not actual.sort_values().equals(expected.sort_values()):raise ValueError("LEGAL_VECTOR_KEYS_NOT_COMPLETE")
 result=flags.merge(vectors,on=["signal_date","ticker"],how="left",sort=False,validate="one_to_one")
 if not result[["signal_date","ticker"]].equals(flags[["signal_date","ticker"]].reset_index(drop=True)):raise ValueError("INFERENCE_KEYS_DROPPED_OR_REORDERED")
 result.loc[~result.feature_available,list(features)]=np.nan
 if np.isinf(result[list(features)].to_numpy(float)).any():raise ValueError("INFINITE_FEATURE")
 return result

def _window(calendar,decision,length):
 d=pd.Timestamp(decision).normalize()
 if d>=BOUNDARY or d not in calendar or length<1:raise ValueError("HISTORY_DECISION_OR_LENGTH")
 return calendar[calendar<=d][-length:]

def _fold(calendar,year):
 if year not in (2021,2022,2023,2024,2025):raise ValueError("UNREGISTERED_ANNUAL_YEAR")
 cutoff=pd.Timestamp(f"{year}-01-01");prior=calendar[calendar<cutoff]
 if len(prior)<60:raise ValueError("LESS_THAN_60_PRE_FOLD_SESSIONS")
 dates=prior[-60:]
 digest=hashlib.sha256(json.dumps([d.isoformat() for d in prior],sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
 return {"year":year,"packet_role":"INTERNAL_PACKET_OOF" if year<2023 else "OUTER_EVALUATION_OOF","fold":f"ANNUAL_{year}","cutoff_exclusive":cutoff,"calibration_start":dates[0],"calibration_sessions":dates,"calendar_sha256":digest}

def prepare_inputs(run_dir):
 """Batch hashes/footer/schema, then keys/flags only; never numeric vectors/y."""
 run=Path(run_dir).resolve();paths=resolve(REPO)
 if not run.is_relative_to(paths.backtest_root.resolve()) or run.is_symlink() or not run.exists():raise ValueError("RUN_OUTSIDE_EXISTING_BACKTEST_ROOT")
 manifest_path=run/"input_manifest.json"
 if not manifest_path.exists():raise ValueError("EXISTING_RUN_INPUT_MANIFEST_REQUIRED")
 existing=json.loads(manifest_path.read_text(encoding="utf-8"));records={}
 for name,pin in SOURCES.items():
  p=Path(pin["path"]);stat=p.stat();fingerprint={"size":stat.st_size,"mtime_ns":stat.st_mtime_ns}
  old=existing.get("input_sources",{}).get(name,{})
  cached=old.get("sha256")==pin["sha256"] and old.get("file_fingerprint")==fingerprint and old.get("hash_verified") is True
  if not cached and sha(p)!=pin["sha256"]:raise ValueError("FROZEN_SOURCE_HASH_MISMATCH:"+name)
  pf=pq.ParquetFile(p);schema=pf.schema_arrow.names
  required=set(TRAIN_FLAGS)|set(FEATURES)|{"y_open5"} if name=="value_training_panel" else set(PRED_FLAGS)|set(FEATURES) if name=="prediction_feature_panel" else {pin["date"]} if name=="calendar" else {"ticker","trade_date","code","open","close","alpha","beta"}
  if not required.issubset(schema) or pf.metadata.num_rows!=pin["rows"]:raise ValueError("FROZEN_SCHEMA_OR_ROWS_CHANGED:"+name)
  ranges=[]
  for i in range(pf.num_row_groups):
   st=pf.metadata.row_group(i).column(schema.index(pin["date"])).statistics
   if not st or not st.has_min_max or pd.Timestamp(st.max)>=BOUNDARY:raise ValueError("SOURCE_NOT_PHYSICALLY_PRE2026:"+name)
   ranges.append({"min":str(st.min),"max":str(st.max),"rows":pf.metadata.row_group(i).num_rows})
  records[name]={**pin,"file_fingerprint":fingerprint,"hash_verified":True,"schema":schema,"rowgroups":ranges}
 # Every source above passes before any table is materialized.
 calendar=pd.DatetimeIndex(pd.to_datetime(pq.read_table(SOURCES["calendar"]["path"],columns=["trade_date"]).to_pandas().trade_date))
 if calendar.has_duplicates or not calendar.is_monotonic_increasing or calendar.hasnans:raise ValueError("INVALID_BOUND_CALENDAR")
 train=_flags(pq.read_table(SOURCES["value_training_panel"]["path"],columns=list(TRAIN_FLAGS)).to_pandas(),True)
 pred=_flags(pq.read_table(SOURCES["prediction_feature_panel"]["path"],columns=list(PRED_FLAGS)).to_pandas())
 if not train.signal_date.isin(calendar).all() or not pred.signal_date.isin(calendar).all():raise ValueError("SIGNAL_NOT_ON_BOUND_CALENDAR")
 guards={"training_keys":len(train),"prediction_keys":len(pred),"calendar_sessions":len(calendar),"unavailable_prediction_keys_preserved":int((~pred.feature_available).sum()),"numeric_y_or_32_read":False,"all_sources_pass_before_flags":True}
 existing.update(input_sources=records,data_files=[{"path":x["path"],"sha256":x["sha256"]} for x in records.values()],inputs_verified=True,input_data_copied=False,frozen_feature_order=list(FEATURES),allowed_feature_sources=list(ALLOWED_SOURCES),label_coordinate=LABEL,training_cutoff_exclusive="2026-01-01",guard_receipts=guards,
  source_reader_path=str(Path(__file__)),source_reader_sha256=sha(Path(__file__)),information_semantics={"physical_input_present":"STOCK32_DIAGNOSTIC","common_input_present":"decision_information_present_union","forecast_missing":"NaN; no y-dependent inference row filtering","risk_return_coordinate":"accepted PIT_FORWARD_REHAB_INDEX ret_1d proxy; not settled cash shareholder return","sequence_role":"DAILY_20_SESSION; no minute-input claim","unsettled_cash_events":"LOCAL_ACCOUNT_QUALIFICATION_BLOCK; no factor-derived cash"},
  conditional_metadata_sources={"industry":{"path":"D:/us-tech-quant-results/A2_FREE_PIT_SECURITY_IDENTITY_SIC_FF48_AND_FACTOR_RISK_FOUNDATION_R1/pit_sec_sic_ff12_ff48_eligible_surface.parquet","sha256":"591ecea001bf1f0b1b6ef7059a65b7e6efd45890befa149c0377d45b6aad6646","status":"PARTIAL_NOT_INCLUDED_IN_FIXED32"},"fundamental":{"path":"D:/us-tech-quant-results/A2_PIT_SEC_FUNDAMENTAL_ACCELERATION_ALPHA_R1/fundamental_feature_ledger.parquet","sha256":"2789c80596e9758c7a984529f034a389594aa6aa7cbf9d88bc99c8cd9c933aef","status":"CONDITIONAL_ASOF_NOT_INCLUDED_IN_FIXED32"}})
 existing["annual_folds"]={str(y):{k:[d.isoformat() for d in v] if k=="calibration_sessions" else v.isoformat() if isinstance(v,pd.Timestamp) else v for k,v in _fold(calendar,y).items()} for y in (2021,2022,2023,2024,2025)}
 content=json.dumps(existing,ensure_ascii=False,indent=2)
 if manifest_path.read_text(encoding="utf-8")!=content:manifest_path.write_text(content,encoding="utf-8")
 _PREPARED[str(run)]=(existing,calendar,train,pred)
 return existing

class InputReader:
 def __init__(self,run_dir):
  self.run=Path(run_dir).resolve()
  if str(self.run) not in _PREPARED:prepare_inputs(self.run)
  self.manifest,self.calendar,self.train_flags,self.pred_flags=_PREPARED[str(self.run)]
 def annual_fold(self,year):
  return _fold(self.calendar,year)
 def _vectors(self,source,columns,filters):
  record=self.manifest["input_sources"][source];path=Path(record["path"])
  stat=path.stat()
  if {"size":stat.st_size,"mtime_ns":stat.st_mtime_ns}!=record["file_fingerprint"]:raise ValueError("FROZEN_FILE_CHANGED_AFTER_METADATA_GUARD")
  frame=pd.read_parquet(path,columns=columns,filters=filters)
  after=path.stat()
  if {"size":after.st_size,"mtime_ns":after.st_mtime_ns}!=record["file_fingerprint"]:raise ValueError("FROZEN_FILE_CHANGED_DURING_READ")
  if "signal_date" in frame:frame["signal_date"]=pd.to_datetime(frame.signal_date)
  return frame
 def read_training_fold(self,year):
  fold=self.annual_fold(year);trainmask,calmask=_training_masks(self.train_flags,fold)
  shared=[("feature_available","==",True),("feature_source","in",list(ALLOWED_SOURCES)),("label_available","==",True),("account_event_unhandled","==",False)]
  cols=list(TRAIN_FLAGS)+["y_open5",*FEATURES]
  specs=[(trainmask,shared+[("signal_date","<",fold["calibration_start"]),("label_mature_date","<",fold["calibration_start"])]),(calmask,shared+[("signal_date",">=",fold["calibration_start"]),("signal_date","<",fold["cutoff_exclusive"]),("label_mature_date","<",fold["cutoff_exclusive"])])]
  result=[]
  for mask,filters in specs:
   f=self._vectors("value_training_panel",cols,filters).sort_values(["signal_date","ticker"]).reset_index(drop=True)
   expected=self.train_flags.loc[mask,["signal_date","ticker"]].sort_values(["signal_date","ticker"]).reset_index(drop=True)
   if not f[["signal_date","ticker"]].equals(expected):raise ValueError("TRAINING_VECTOR_KEYS_NOT_PREAPPROVED")
   if not np.isfinite(f.y_open5).all() or np.isinf(f[list(FEATURES)].to_numpy(float)).any():raise ValueError("NONFINITE_TRAINING_INPUT")
   result.append(f)
  return tuple(result)
 def read_inference(self,year):
  fold=self.annual_fold(year);start=fold["cutoff_exclusive"];end=pd.Timestamp(f"{year+1}-01-01")
  flags=self.pred_flags.loc[self.pred_flags.signal_date.ge(start)&self.pred_flags.signal_date.lt(end)].reset_index(drop=True)
  vectors=self._vectors("prediction_feature_panel",["signal_date","ticker",*FEATURES],[("signal_date",">=",start),("signal_date","<",end),("feature_available","==",True),("feature_source","in",list(ALLOWED_SOURCES))])
  return _join_vectors(flags,vectors)
 def read_return_history(self,tickers,decision_date,lookback=60):
  dates=_window(self.calendar,decision_date,lookback);names=list(dict.fromkeys(map(str,tickers)))
  if not names:raise ValueError("EMPTY_HISTORY_TICKERS")
  f=self._vectors("prediction_feature_panel",["signal_date","ticker","ret_1d"],[("signal_date",">=",dates[0]),("signal_date","<=",dates[-1]),("ticker","in",names),("feature_available","==",True),("feature_source","in",list(ALLOWED_SOURCES))])
  idx=pd.MultiIndex.from_product([dates,names],names=["signal_date","ticker"])
  f=f.set_index(["signal_date","ticker"]).reindex(idx);f["return_available"]=np.isfinite(f.ret_1d)
  return f.reset_index()
 def sequence_window(self,tickers,decision_date,length=20):
  valid_dates=_window(self.calendar,decision_date,length);complete=len(valid_dates)==length
  dates=pd.DatetimeIndex([pd.NaT]*(length-len(valid_dates))).append(valid_dates);names=list(dict.fromkeys(map(str,tickers)))
  if not names:raise ValueError("EMPTY_SEQUENCE_TICKERS")
  vectors=self._vectors("prediction_feature_panel",["signal_date","ticker",*FEATURES],[("signal_date",">=",valid_dates[0]),("signal_date","<=",valid_dates[-1]),("ticker","in",names),("feature_available","==",True),("feature_source","in",list(ALLOWED_SOURCES))])
  idx=pd.MultiIndex.from_product([names,dates],names=["ticker","signal_date"]);f=vectors.set_index(["ticker","signal_date"]).reindex(idx)
  x=f[list(FEATURES)].to_numpy(float).reshape(len(names),len(dates),len(FEATURES))
  flags=self.pred_flags.loc[self.pred_flags.ticker.isin(names)&self.pred_flags.signal_date.isin(dates),["ticker","signal_date","feature_available"]].set_index(["ticker","signal_date"]).reindex(idx)
  mask=flags.feature_available.fillna(False).to_numpy(bool).reshape(len(names),len(dates))
  return {"tickers":names,"dates":dates,"features":x,"step_available":mask,"cell_observed":np.isfinite(x),"window_complete":complete,"left_pad_sessions":length-len(valid_dates),"role":"DAILY_SESSION_SEQUENCE"}
