"""Metadata/synthetic-only root-to-model protocol review; no physical fit or I/O."""
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import stateful_mechanism as r
from scripts.research.a2.training import stateful_mechanism_models as m

def estimator_units(family):
    family=m.canonical_family(family)
    return 3 if family=="HGBQuantile" else (3 if family in m.STOCHASTIC else 1)

def test_frozen_action_schedule_exact418_and_scaler_alias():
    estimators=0;scalers=set()
    for node in r.action_schedule():
        for family in node["families"]:
            estimators+=len(node["capacities"])*estimator_units(family)
        if any(m.canonical_family(f) in m.SCALED_FAMILIES for f in node["families"]):
            scalers.add((node["group"],str(node["horizon"]),"PREFIX" if node.get("prefix") else node["year"]))
    assert estimators==396
    assert len(scalers)==22
    assert estimators+len(scalers)==418
    multitask=[n for n in r.action_schedule() if n.get("target_columns")]
    assert len(multitask)==4
    assert sum(len(n["capacities"])*3 for n in multitask)==36
    assert all(n["target_columns"]==["target_H3","target_H5","target_H10","target_H20"] for n in multitask)

def test_source_pins_and_family_capacity_protocol_no_fit():
    pins=m.source_pins()
    spec=m.specifications()
    assert spec["source_pins"]==pins and set(pins)=={
        "adapter_sha256","native_sha256","extension_sha256",
        "fusion_native_sha256","fusion_owner_sha256"}
    for node in r.action_schedule():
        for family in node["families"]:
            for cap in node["capacities"]:
                for seed in r.seed_list(family):
                    normalized=m._node("opaque-audit-budget-id",
                        dict(family=family,capacity=cap,seed=seed,objective=node.get("objective","advantage")))
                    assert normalized["family"]==m.canonical_family(family)
    assert all(r.AUTHORITY[k] is False for k in r.inputs.FALSE_AUTHORITY)

def test_date_and_action_role_weights_are_keys_only():
    f=pd.DataFrame({"signal_date":pd.to_datetime(["2024-01-03"]*3+["2024-01-04"]*2),
                    "action_type":[0,1,1,0,1],"base_weight":[1,.5,.5,1,1],
                    "target":[-9.,3.,5.,99.,-99.]})
    w=r.role_weights(f)
    g=f.copy();g["target"]=-f.target
    assert np.array_equal(w,r.role_weights(g))
    assert w[:3].sum()==pytest.approx(w[3:].sum())
    assert w[0]==pytest.approx(w[1:3].sum())

def toy_frames():
    dates=pd.DatetimeIndex(list(pd.bdate_range("2023-10-02",periods=24))+
                           list(pd.bdate_range("2024-01-02",periods=24))+
                           list(pd.bdate_range("2025-01-02",periods=24)))
    n=len(dates)
    frame=pd.DataFrame({"signal_date":dates,"label_mature_date":dates+pd.Timedelta(days=7),
                        "label_qualified":True,"sample_id":[str(d.date())+"|toy" for d in dates],
                        "ticker":"TOY","security_id":"SYNTHETIC_SID",
                        "target":.003,"reference_action":0.,"base_weight":1.,
                        "raw_rank":2.,"realized_vol_20d":.02,"cohort_age_sessions":0.,
                        "i_raw_rank":2.,"i_realized_vol_20d":.02,"i_cohort_age_sessions":1.})
    return {"MEAN":{"ENTRY":frame.copy(),"INCUMBENT":frame.copy()}}

POINT_FAMILIES=("ridge","elasticnet","huber","hgb","xgb","lgb","catboost","extratrees",
                "mlp","resnet","ft_transformer","hgb_quantile","ngboost","gaussian_mlp")

def toy_publications(frames,include_prefix=True):
    pubs=[]
    for group in ("ENTRY","INCUMBENT"):
        for year,prefix in ((2023,True),(2024,False),(2025,False)):
            if prefix and not include_prefix:continue
            f=frames["MEAN"][group]
            f=f.loc[f.signal_date.dt.year.eq(year),["signal_date","sample_id"]].copy()
            for family in (("ridge","hgb") if prefix else POINT_FAMILIES):
                p=f.copy();p["q50" if family=="hgb_quantile" else "mean"]=.001 if family=="ridge" else .002
                pubs.append(dict(group=group,horizon="MEAN",family=family,capacity="MID",year=year,
                                 prefix=prefix,path="synthetic-not-read.parquet",frame=p))
    return pubs

def install_no_io(monkeypatch,dispatch):
    monkeypatch.setattr(r,"save",lambda *a,**k:None)
    monkeypatch.setattr(r,"blocked",lambda run,spec,reason,**details:{**spec,"reason":reason,"status":"BLOCKED_INPUT","fit_units":0,**details})
    monkeypatch.setattr(pd.DataFrame,"to_parquet",lambda *a,**k:None)
    monkeypatch.setattr(r.fit_owner,"sha",lambda *a,**k:"SYNTHETIC_SHA")
    monkeypatch.setattr(r,"ensemble_forecasts",lambda pub:pub["frame"].copy())
    monkeypatch.setattr(r,"publish_prediction",
        lambda run,spec,frame,pred:dict(path="C:/synthetic-only/oof.parquet",rows=len(frame)))
    monkeypatch.setattr(r,"scaler_job",
        lambda *a,**k:(object(),dict(receipt_path="synthetic_scaler",status="TRAINED",fit_units=1)))
    def job(run,design,spec,x,y,w,dates,features,**kw):
        dispatch.append((spec,kw))
        assert kw["operation"]=="fusion"
        assert spec["method"] in m.FUSION_METHODS
        assert kw["worker"] is m.fusion_worker
        return object(),dict(receipt_path="synthetic-model",status="TRAINED")
    monkeypatch.setattr(r,"physical_job",job)
    monkeypatch.setattr(m,"predict_fusion",
        lambda model,packet:dict(mean=np.ones(len(packet["experts"]))*.001,
                                probability=None,q10=None,q50=None,q90=None,sigma=None))

def test_root_fusion_dispatch_native_methods_operation_and_dict_prediction(monkeypatch):
    frames=toy_frames();dispatch=[]
    install_no_io(monkeypatch,dispatch)
    rec,pub=r.run_fusions(Path("C:/synthetic-only"),{},frames,toy_publications(frames))
    assert len(dispatch)==56
    assert len([p for p in pub if p.get("two_independent_experts")])==40
    assert all("mean" not in p for p in pub)  # Only references/metadata published.
    assert len([p for p in pub if p.get("fit_units")==0])==8

def test_deterministic_all14_does_not_depend_on_fitted_prefix_ooof(monkeypatch):
    frames=toy_frames();dispatch=[]
    install_no_io(monkeypatch,dispatch)
    rec,pub=r.run_fusions(Path("C:/synthetic-only"),{},frames,toy_publications(frames,include_prefix=False))
    deterministic=[p for p in pub if p.get("fit_units")==0]
    assert len([p for p in deterministic if p["year"]==2024])==4
    assert len([p for p in deterministic if p["year"]==2025])==4
    assert all(p["family"] in ("fusion_equal","fusion_median") for p in deterministic)

S3_ADDITION='\n\ndef run_sequence_fusions(run,design,sequence_publications):\n    """Frozen S0/S1/S2 and four joint-architecture Ridge S3 identities.\n\n    Independent point comparisons never depend on S3 admission. S3 consumes\n    genuine same-target mature OOF only, and at most four scaler plus four\n    estimator fits. No sequence, seed, capacity or architecture selection.\n    """\n    from scripts.research.a2.training import stateful_mechanism_models as models\n    architectures=(\'tcn\',\'gru\',\'lstm\')\n    identities=((20,2024),(20,2025),(5,2025),(10,2025))\n    columns=(\'static_forecast\',\'sequence_forecast\',\'arch_tcn\',\'arch_gru\',\'arch_lstm\')\n    receipts=[];publications=[];fitted={}\n    def publication(group,family,year,prefix,length):\n        hits=[p for p in sequence_publications\n              if p.get(\'group\')==group and p.get(\'family\')==family\n              and p.get(\'capacity\')==\'MID\' and p.get(\'year\')==year\n              and bool(p.get(\'prefix\'))==prefix and p.get(\'path\')\n              and (group!=\'JOINT_SEQUENCE\' or p.get(\'lookback\')==length)]\n        if len(hits)>1:raise ValueError(\'S3_AMBIGUOUS_FROZEN_OOF_PUBLICATION\')\n        return hits[0] if hits else None\n    def packet(length,year,prefix,require_all):\n        static=publication(\'SEQUENCE_STATIC_L\'+str(length),\'hgb\',year,prefix,length)\n        if static is None:return None\n        base=ensemble_forecasts(static)\n        if \'mean\' not in base:return None\n        pieces=[]\n        for arch in architectures:\n            src=publication(\'JOINT_SEQUENCE\',arch,year,prefix,length)\n            if src is None:\n                if require_all:return None\n                continue\n            seq=ensemble_forecasts(src)\n            required=[\'sample_id\',\'signal_date\',\'security_id\',\'target\',\n                      \'label_qualified\',\'label_mature_date\',\'mean\']\n            if not set(required).issubset(base) or not set(required).issubset(seq):\n                raise ValueError(\'S3_SAME_TARGET_SOURCE_SCHEMA\')\n            keys=[\'sample_id\',\'signal_date\',\'security_id\']\n            side=seq[required].rename(columns={\n                \'target\':\'sequence_target\',\'label_qualified\':\'sequence_label_qualified\',\n                \'label_mature_date\':\'sequence_label_mature_date\',\'mean\':\'sequence_forecast\'})\n            p=base.rename(columns={\'mean\':\'static_forecast\'}).merge(\n                side,on=keys,how=\'left\',validate=\'one_to_one\')\n            jointly=p.label_qualified.eq(True)&p.sequence_label_qualified.eq(True)\n            finite=np.isfinite(p.target)&np.isfinite(p.sequence_target)\n            if not np.array_equal(p.loc[jointly&finite,\'target\'].to_numpy(),\n                                  p.loc[jointly&finite,\'sequence_target\'].to_numpy()):\n                raise ValueError(\'S3_DIFFERENT_NATIVE_ACTION_TARGET\')\n            p[\'label_qualified\']=jointly&finite&p.label_mature_date.notna()&p.sequence_label_mature_date.notna()\n            p[\'label_mature_date\']=pd.concat(\n                [pd.to_datetime(p.label_mature_date),\n                 pd.to_datetime(p.sequence_label_mature_date)],axis=1).max(axis=1)\n            p[\'architecture\']=arch\n            for one in architectures:p[\'arch_\'+one]=float(arch==one)\n            p[\'original_sample_id\']=p.sample_id\n            p[\'sample_id\']=p.sample_id.astype(str)+\'|ARCH=\'+arch\n            pieces.append(p)\n        return pd.concat(pieces,ignore_index=True) if pieces else None\n    for length in (5,10):\n        spec=dict(slot_id=f\'FUSION_SEQUENCE_S3_L{length}_2024\',family=\'ridge\',capacity=\'MID\',\n                  seed=SEEDS[0],year=2024,bucket=\'FUSION_GATING\',objective=\'ADVANTAGE\',\n                  group=\'S3_SEQUENCE\',lookback=length)\n        receipts.append(blocked(run,spec,\'BLOCKED_GENUINE_2023_PREFIX_OOF_NO_EXTRA_FIT\'))\n    for length,year in identities:\n        name=f\'FUSION_SEQUENCE_S3_L{length}_{year}\'\n        spec=dict(slot_id=name,family=\'ridge\',capacity=\'MID\',seed=SEEDS[0],year=year,\n                  bucket=\'FUSION_GATING\',objective=\'ADVANTAGE\',group=\'S3_SEQUENCE\',\n                  lookback=length,meta_members=[\'STATIC_HGB_MID\',\'TCN_MID\',\'GRU_MID\',\'LSTM_MID\'],\n                  meta_parameter=\'RIDGE_MID_ALPHA10\')\n        past=[]\n        for prior,prefix in ((2023,True),(2024,False)):\n            if prior>=year or (length!=20 and prefix):continue\n            p=packet(length,prior,prefix,require_all=True)\n            if p is not None:past.append(p)\n        if not past:\n            receipts.append(blocked(run,spec,\'BLOCKED_GENUINE_SAME_TARGET_OOF\'));continue\n        train=mature_train(pd.concat(past,ignore_index=True),f\'{year}-01-01\')\n        # Fixed three-architecture matched rows give equal architecture weight.\n        # Unknown source forecast drops its entire ex-ante source key; no replacement.\n        train[\'all_input_known\']=np.isfinite(train[list(columns)].to_numpy(float)).all(axis=1)\n        complete=train.groupby([\'signal_date\',\'original_sample_id\'],sort=False).all_input_known.agg([\'all\',\'size\'])\n        allowed=complete.index[complete[\'all\']&complete[\'size\'].eq(3)]\n        key=pd.MultiIndex.from_frame(train[[\'signal_date\',\'original_sample_id\']])\n        train=train.loc[key.isin(allowed)].reset_index(drop=True)\n        if len(train)<20:\n            receipts.append(blocked(run,spec,\'INSUFFICIENT_ALL_LEGAL_SAME_TARGET_OOF\',\n                                    training_rows=len(train)));continue\n        x=train[list(columns)].to_numpy(float)\n        weight=role_weights(train);dates=train.signal_date.to_numpy()\n        scaler,sr=scaler_job(run,design,\'FUSION_GATING\',name+\'_SCALER\',year,\n                            x,dates,columns,weights=weight)\n        receipts.append(sr)\n        if scaler is None:\n            receipts.append(blocked(run,spec,\'SHARED_S3_SCALER_FAILED\'));continue\n        model,mr=physical_job(run,design,spec,scaler.transform(x),\n                              train.target.to_numpy(float),weight,dates,columns,\n                              worker=models.fit_worker)\n        receipts.append(mr)\n        if model is not None:fitted[(length,year)]=(scaler,model,mr,spec)\n        update_progress(run,design)\n    # All six lookback/year pairs independently publish S0/S1/S2 whenever their\n    # own static+sequence OOF sources exist, including L5/L10 in 2024.\n    for length in (5,10,20):\n        for year in (2024,2025):\n            evaluation=packet(length,year,False,require_all=False)\n            if evaluation is None:continue\n            meta=fitted.get((length,year))\n            raw=evaluation[list(columns)].to_numpy(float)\n            input_known=np.isfinite(raw).all(axis=1)\n            if meta is not None:\n                scaler,model,mr,spec=meta\n                transformed=scaler.transform(raw)\n                score=models.predict(model,np.nan_to_num(transformed,nan=0.))[\'mean\']\n                s3=np.where(input_known,score,np.nan)\n            else:s3=None;mr=None\n            for arch in architectures:\n                pick=evaluation.architecture.eq(arch).to_numpy()\n                if not pick.any():continue\n                f=evaluation.loc[pick].copy().reset_index(drop=True)\n                f[\'sample_id\']=f.original_sample_id\n                point={\'S0\':f.static_forecast.to_numpy(float),\n                       \'S1\':f.sequence_forecast.to_numpy(float),\n                       \'S2\':(f.static_forecast.to_numpy(float)+f.sequence_forecast.to_numpy(float))/2}\n                if s3 is not None:point[\'S3\']=s3[pick]\n                shared=input_known[pick]\n                for variant,score in point.items():\n                    score=np.where(shared,score,np.nan)\n                    ps=dict(slot_id=f\'FUSION_SEQUENCE_L{length}_{year}_{arch}_{variant}\',\n                            family=arch+\'_\'+variant,capacity=\'MID\',seed=\'EQUAL_FIXED_SEEDS\',\n                            year=year,bucket=\'FUSION_GATING\',objective=\'ADVANTAGE\',\n                            group=\'SEQUENCE_COMPARISON\',lookback=length,meta_fit_units=0)\n                    pub=publish_prediction(run,ps,f,{\'mean\':score})\n                    daily,metrics=local_regret(\n                        f,np.where(np.isfinite(score),(score>0).astype(float),np.nan),score=score)\n                    path=Path(pub[\'path\']).with_name(\'daily_regret.parquet\')\n                    daily.to_parquet(path)\n                    pub.update(slot_id=ps[\'slot_id\'],group=\'SEQUENCE_COMPARISON\',horizon=\'MEAN\',\n                               lookback=length,year=year,architecture=arch,variant=variant,\n                               metrics=metrics,daily_path=str(path),daily_sha256=fit_owner.sha(path),\n                               dependency_meta_receipt=mr.get(\'receipt_path\') if variant==\'S3\' else None,\n                               uncertainty_capability=\'POINT_ONLY\',\n                               meta_parameter=\'RIDGE_MID_ALPHA10\' if variant==\'S3\' else None,\n                               architecture_selection=False,source_account_authority_upgraded=False)\n                    save(Path(pub[\'path\']).with_suffix(\'.receipt.json\'),pub);publications.append(pub)\n    save(run/\'SEQUENCE_FUSION_BATCH.json\',dict(\n        status=\'COMPLETE\',receipts=receipts,publications=publications,\n        max_new_physical_fits=8,scaler_count_max=4,estimator_count_max=4,\n        independent_point_comparison_not_blocked_by_meta=True))\n    return receipts,publications\n'


def s3_function_without_source_application():
    namespace=dict(r.__dict__)
    exec(compile(S3_ADDITION,"synthetic-unapplied-S3","exec"),namespace)
    return namespace["run_sequence_fusions"],namespace

def toy_sequence_publications(include_prefix=True):
    frames=toy_frames()["MEAN"]["INCUMBENT"]
    pubs=[]
    for length in (5,10,20):
        for year,prefix in ((2023,True),(2024,False),(2025,False)):
            if prefix and (length!=20 or not include_prefix):continue
            f=frames.loc[frames.signal_date.dt.year.eq(year)].copy()
            f["action_type"]=0.;f["mean"]=.001
            pubs.append(dict(group="SEQUENCE_STATIC_L"+str(length),family="hgb",capacity="MID",
                             year=year,prefix=prefix,path="synthetic-only",frame=f))
            for arch in ("tcn","gru","lstm"):
                p=f.copy();p["mean"]=.002
                pubs.append(dict(group="JOINT_SEQUENCE",family=arch,capacity="MID",
                                 year=year,prefix=prefix,lookback=length,path="synthetic-only",frame=p))
    return pubs

def test_unapplied_s3_exact_eight_units_and_independent_s0_s1_s2(monkeypatch):
    fn,ns=s3_function_without_source_application()
    counts={"scaler":0,"model":0}
    class Scaler:
        def transform(self,x):return x
    def scaler(*a,**k):
        counts["scaler"]+=1
        return Scaler(),dict(receipt_path="synthetic-scaler",fit_units=1)
    def job(run,design,spec,x,target,weights,dates,features,**kw):
        counts["model"]+=1
        assert spec["family"]=="ridge" and spec["capacity"]=="MID"
        assert tuple(features)==("static_forecast","sequence_forecast","arch_tcn","arch_gru","arch_lstm")
        assert pd.to_datetime(dates).max()<pd.Timestamp(str(spec["year"])+"-01-01")
        assert kw["worker"] is m.fit_worker
        return object(),dict(receipt_path="synthetic-estimator",fit_units=1)
    monkeypatch.setitem(ns,"scaler_job",scaler)
    monkeypatch.setitem(ns,"physical_job",job)
    monkeypatch.setitem(ns,"ensemble_forecasts",lambda p:p["frame"].copy())
    monkeypatch.setitem(ns,"blocked",lambda run,spec,reason,**k:dict(**spec,reason=reason,fit_units=0))
    monkeypatch.setitem(ns,"save",lambda *a,**k:None)
    monkeypatch.setitem(ns,"update_progress",lambda *a,**k:None)
    monkeypatch.setitem(ns,"publish_prediction",lambda *a,**k:dict(path="C:/synthetic-only/oof.parquet"))
    monkeypatch.setattr(pd.DataFrame,"to_parquet",lambda *a,**k:None)
    monkeypatch.setattr(r.fit_owner,"sha",lambda *a,**k:"SYNTHETIC_SHA")
    monkeypatch.setattr(m,"predict",lambda model,x:dict(mean=np.ones(len(x))*.002))
    rec,pub=fn(Path("C:/synthetic-only"),{},toy_sequence_publications())
    assert counts=={"scaler":4,"model":4}
    assert len(pub)==66
    assert len([p for p in pub if p["variant"]=="S3"])==12
    independent2024=[p for p in pub if p["year"]==2024 and p["lookback"] in (5,10)]
    assert len(independent2024)==18 and all(p["variant"]!="S3" for p in independent2024)
    assert len([r for r in rec if r.get("reason")=="BLOCKED_GENUINE_2023_PREFIX_OOF_NO_EXTRA_FIT"])==2

def test_unapplied_s3_oof_failure_does_not_block_point_comparisons(monkeypatch):
    fn,ns=s3_function_without_source_application()
    class Scaler:
        def transform(self,x):return x
    monkeypatch.setitem(ns,"scaler_job",lambda *a,**k:(Scaler(),dict(receipt_path="synthetic")))
    monkeypatch.setitem(ns,"physical_job",lambda *a,**k:(object(),dict(receipt_path="synthetic")))
    monkeypatch.setitem(ns,"ensemble_forecasts",lambda p:p["frame"].copy())
    monkeypatch.setitem(ns,"blocked",lambda run,spec,reason,**k:dict(**spec,reason=reason,fit_units=0))
    monkeypatch.setitem(ns,"save",lambda *a,**k:None)
    monkeypatch.setitem(ns,"update_progress",lambda *a,**k:None)
    monkeypatch.setitem(ns,"publish_prediction",lambda *a,**k:dict(path="C:/synthetic-only/oof.parquet"))
    monkeypatch.setattr(pd.DataFrame,"to_parquet",lambda *a,**k:None)
    monkeypatch.setattr(r.fit_owner,"sha",lambda *a,**k:"SYNTHETIC_SHA")
    monkeypatch.setattr(m,"predict",lambda model,x:dict(mean=np.ones(len(x))*.002))
    rec,pub=fn(Path("C:/synthetic-only"),{},toy_sequence_publications(include_prefix=False))
    assert len([p for p in pub if p["variant"] in ("S0","S1","S2")])==54
    assert not any(p["variant"]=="S3" and p["year"]==2024 for p in pub)
    assert len([p for p in pub if p["variant"]=="S3" and p["year"]==2025])==9
