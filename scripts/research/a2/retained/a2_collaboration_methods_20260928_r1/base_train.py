"""Nine fixed-budget common-target base fits, physically pre-2026 inputs only.

--prepare freezes sampling keys/code/data/specs but does not fit. --fit also
requires the parent DESIGN_LOCK.json to bind the exact prepared contract.
No original training module, saved predictor, or 2026 panel is imported/read.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
from pathlib import Path
import platform
import sys
import time
import warnings

sys.dont_write_bytecode = True
import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

HERE = Path(__file__).resolve().parent
OUT = HERE / "base_artifacts"
UPSTREAM = HERE.parent / "a2_latest_effective_joint_20260927"
DATA = UPSTREAM / "data/pre2026_joint_context.parquet"
FEATURE_REGISTRY = UPSTREAM / "models/model_registry.json"
FEATURES = json.loads(FEATURE_REGISTRY.read_text(encoding="utf-8"))["feature_order"]
assert len(FEATURES) == 32 and len(set(FEATURES)) == 32
assert not set(FEATURES) & {"target", "target_end_date", "target_context_available", "y_next_open", "label_available"}
SEED = 20260928
MAX_ROWS = 50_000
VINTAGES = {"oof_2024": "2024-01-01", "oof_2025": "2025-01-01", "final": "2026-01-01"}
NAMES = ("ridge", "hgb", "mlp")
SPECS = {
    "ridge": {"alpha": 10.0, "solver": "auto"},
    "hgb": {"max_iter": 150, "max_depth": 3, "max_leaf_nodes": 15,
            "min_samples_leaf": 200, "l2_regularization": 5.0,
            "learning_rate": .05, "early_stopping": False, "random_state": SEED},
    "mlp": {"hidden_layer_sizes": (32, 16), "activation": "relu", "solver": "adam",
            "alpha": .01, "batch_size": 512, "max_iter": 40,
            "early_stopping": False, "learning_rate_init": .001,
            "n_iter_no_change": 41, "random_state": SEED},
}


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def estimator(name):
    if name == "ridge":
        return Pipeline([("scale", StandardScaler()), ("regressor", Ridge(**SPECS[name]))])
    if name == "hgb":
        return HistGradientBoostingRegressor(**SPECS[name])
    if name == "mlp":
        return Pipeline([("scale", StandardScaler()), ("regressor", MLPRegressor(**SPECS[name]))])
    raise ValueError(f"UNKNOWN_BASE_NAME:{name}")


def quota(counts, budget):
    counts = np.asarray(counts, dtype=np.int64)
    if len(counts) == 0 or len(counts) > budget or (counts <= 0).any():
        raise ValueError("MATURE_DATE_COVERAGE_INFEASIBLE")
    budget = min(int(budget), int(counts.sum()))
    lo, hi = 1, int(counts.max())
    while lo < hi:
        mid = (lo+hi+1)//2
        if int(np.minimum(counts, mid).sum()) <= budget:
            lo = mid
        else:
            hi = mid-1
    allocation = np.minimum(counts, lo)
    remaining = budget-int(allocation.sum())
    allocation[np.flatnonzero(allocation < counts)[:remaining]] += 1
    assert allocation.sum() == budget and (allocation > 0).all()
    return allocation


def mature_rows(frame, cutoff):
    return frame.loc[frame.signal_date.ge("2023-01-01") & frame.signal_date.lt(cutoff)
                     & frame.target_context_available.fillna(False)
                     & frame.target_end_date.notna() & frame.target_end_date.lt(cutoff)].copy()


def sample(frame, cutoff, budget=MAX_ROWS):
    eligible = mature_rows(frame, cutoff)
    counts = eligible.groupby("signal_date", sort=True).size()
    allocation = quota(counts.to_numpy(), budget)
    quotas = dict(zip(counts.index, allocation))
    eligible["sample_hash"] = [hashlib.sha256(f"{SEED}|{d.date()}|{t}".encode("utf-8")).hexdigest()
                                for d,t in zip(eligible.signal_date,eligible.ticker)]
    eligible = eligible.sort_values(["signal_date","sample_hash","ticker"],kind="mergesort")
    selected = eligible[eligible.groupby("signal_date",sort=False).cumcount().to_numpy()
                        < eligible.signal_date.map(quotas).to_numpy()].copy()
    selected = selected.sort_values(["signal_date","ticker"],kind="mergesort").reset_index(drop=True)
    n, days = len(selected), selected.signal_date.nunique()
    selected["sample_weight"] = n/(days*selected.groupby("signal_date").ticker.transform("size"))
    assert days == len(counts) and n <= budget and abs(selected.sample_weight.sum()-n) < 1e-8
    assert np.allclose(selected.groupby("signal_date").sample_weight.sum(),n/days,rtol=0,atol=1e-9)
    keys = selected[["signal_date","ticker","target_end_date","sample_hash","sample_weight"]].copy()
    quotas_frame = pd.DataFrame({"signal_date":counts.index,"eligible_rows":counts.to_numpy(),"selected_rows":allocation})
    audit = {"cutoff_exclusive":cutoff,"eligible_rows":len(eligible),"eligible_mature_days":len(counts),
             "selected_rows":n,"selected_mature_days":days,"selected_signal_min":str(selected.signal_date.min().date()),
             "selected_signal_max":str(selected.signal_date.max().date()),
             "selected_target_end_max":str(selected.target_end_date.max().date()),
             "quota_min":int(allocation.min()),"quota_max":int(allocation.max()),
             "sample_weight_sum":float(selected.sample_weight.sum()),"each_day_total_weight":n/days}
    return selected,keys,quotas_frame,audit


def read_frame():
    cols=["signal_date","ticker","target","target_end_date","target_context_available",
          "quarter_effective_date","next_quarter_effective_date",*FEATURES]
    frame=pd.read_parquet(DATA,columns=cols)
    if frame.signal_date.isna().any() or not frame.signal_date.between("2023-01-01","2025-12-31").all():
        raise RuntimeError("NON_PRE2026_PHYSICAL_INPUT")
    if frame.duplicated(["signal_date","ticker"]).any() or frame.ticker.isna().any():
        raise RuntimeError("INVALID_SOURCE_KEYS")
    if not np.isfinite(frame[FEATURES].to_numpy(float)).all():
        raise RuntimeError("NONFINITE_FEATURES_NO_IMPUTATION_AUTHORIZED")
    available=frame.target_context_available.fillna(False)
    if not np.isfinite(frame.loc[available,"target"].to_numpy(float)).all():
        raise RuntimeError("NONFINITE_AVAILABLE_TARGET")
    if frame.loc[available,"target_end_date"].isna().any() or not frame.loc[available,"target_end_date"].gt(frame.loc[available,"signal_date"]).all():
        raise RuntimeError("INVALID_TARGET_MATURITY")
    if not frame.quarter_effective_date.le(frame.signal_date).all() or not (frame.next_quarter_effective_date.isna()|frame.signal_date.lt(frame.next_quarter_effective_date)).all():
        raise RuntimeError("LATEST_EFFECTIVE_13F_BOUNDARY_FAILURE")
    return frame.sort_values(["signal_date","ticker"],kind="mergesort").reset_index(drop=True)


def self_tests():
    checks={}
    for counts,budget in [([1,9,30],12),([2,2],10),([4,4,4],5)]:
        allocation=quota(counts,budget)
        assert allocation.sum()==min(sum(counts),budget) and (allocation>0).all() and (allocation<=counts).all()
    checks["quota_cap_covers_every_day"]=True
    frame=pd.DataFrame({"signal_date":pd.to_datetime(["2023-01-03"]*5+["2023-01-04"]*5+["2023-12-29"]*3),
                        "ticker":[f"T{i}" for i in range(13)],"target_end_date":pd.to_datetime(["2023-02-01"]*10+["2024-01-01"]*3),
                        "target_context_available":[True]*13,"target":np.arange(13)/10})
    first,keys,_,_=sample(frame,"2024-01-01",7)
    changed=frame.sample(frac=1,random_state=91).copy();changed["target"]=-999.
    second,keys2,_,_=sample(changed,"2024-01-01",7)
    pd.testing.assert_frame_equal(keys,keys2)
    assert len(first)==7 and first.signal_date.nunique()==2 and first.target_end_date.lt("2024-01-01").all()
    checks["sample_unchanged_by_row_order_or_target_values"]=True
    checks["target_end_equal_cutoff_purged"]=True
    assert np.allclose(first.groupby("signal_date").sample_weight.sum(),3.5)
    checks["selected_date_weights_equal_and_total_n"]=True
    assert "sample_weight" in inspect.signature(MLPRegressor.fit).parameters
    assert "sample_weight" in inspect.signature(StandardScaler.fit).parameters
    checks["installed_mlp_and_scaler_support_sample_weight"]=True
    assert estimator("mlp").named_steps["regressor"].n_iter_no_change>40
    assert len(FEATURES)==32 and not set(FEATURES)&{"target","target_context_available","target_end_date"}
    checks["fixed_mlp_epoch_cap_and_feature_target_separation"]=True
    return {"status":"PASS","checks":checks,"fit_calls":0,"predict_calls":0}


def prepare():
    if (OUT/"BASE_PRE_FIT.json").exists():
        raise RuntimeError("PREPARED_BASE_CONTRACT_PRESERVED")
    OUT.mkdir(parents=True,exist_ok=True)
    tests=self_tests();write(OUT/"BASE_SELF_TEST.json",tests)
    source_sha={str(p):sha(p) for p in [DATA,FEATURE_REGISTRY,Path(__file__)]}
    frame=read_frame()
    stages={}
    for vintage,cutoff in VINTAGES.items():
        destination=OUT/vintage;destination.mkdir(exist_ok=True)
        _,keys,quotas,audit=sample(frame,cutoff)
        keys.to_parquet(destination/"SAMPLE_KEYS.parquet",index=False)
        quotas.to_csv(destination/"DATE_QUOTAS.csv",index=False)
        stages[vintage]={**audit,"sample_keys_sha256":sha(destination/"SAMPLE_KEYS.parquet"),
                         "date_quotas_sha256":sha(destination/"DATE_QUOTAS.csv")}
    assert all(sha(Path(p))==digest for p,digest in source_sha.items())
    specs={name:estimator(name).get_params(deep=True) for name in NAMES}
    # Pipeline step objects are represented by their standard constructor repr;
    # model parameters and installed package versions are also sealed explicitly.
    contract={"status":"PREPARED_NOT_FIT","physical_input":"pre2026_joint_context.parquet only",
              "source_sha256":source_sha,"features":FEATURES,"target":"target",
              "target_meaning":"existing matured original multi-horizon excess target, not y_next_open",
              "training_target_clip":[-.30,.30],"prediction_clip":None,"evaluation_target_clip":None,
              "training_eligibility":"2023-01-01 <= signal_date < cutoff and target_context_available and target_end_date < cutoff",
              "sampling":"per-day counts-only water-fill quota, chronological remaining quota, within-day SHA256(seed|date|ticker)",
              "sampling_seed":SEED,"per_fit_max_rows":MAX_ROWS,"date_equal_sample_weight":"N/(D*selected_rows_on_date); sum=N; scaler and regressor both consume identical training weights",
              "regressor_fit_budget":9,"scaler_fit_budget":6,"vintages":stages,"explicit_specs":SPECS,
              "full_estimator_params":specs,"oof_years":[2024,2025],"oof_candidate_filter":"all physical candidate rows of each year, including unavailable target rows",
              "oof_label_fields_not_prediction_inputs":["target","target_end_date","target_context_available"],
              "validation_deployment_vintage":"oof_2025","final_deployment_vintage":"final",
              "replaces_legacy_base_models":False,"shared_target_new_base_models":True,
              "warnings_policy":"record all warnings and observed iterations; no added rounds, seeds, retries or tuning",
              "preparation_tests_sha256":sha(OUT/"BASE_SELF_TEST.json"),"fits_performed_during_prepare":0,
              "python":platform.python_version(),"sklearn":sklearn.__version__,"numpy":np.__version__,"pandas":pd.__version__,
              "required_parent_lock":{"path":"DESIGN_LOCK.json","status":"LOCKED_BEFORE_NEW_FITS","fit_enabled":True,"base_prepare_sha256":"must equal SHA256 of this contract"}}
    write(OUT/"BASE_PRE_FIT.json",contract)
    print(json.dumps({"status":"PREPARED_NOT_FIT","contract":str(OUT/"BASE_PRE_FIT.json"),"sha256":sha(OUT/"BASE_PRE_FIT.json"),"vintages":stages}),flush=True)


def verify_contract():
    contract=read(OUT/"BASE_PRE_FIT.json")
    for path,digest in contract["source_sha256"].items():
        assert sha(Path(path))==digest,f"BASE_FROZEN_SOURCE_DRIFT:{path}"
    for vintage,record in contract["vintages"].items():
        for filename,key in [("SAMPLE_KEYS.parquet","sample_keys_sha256"),("DATE_QUOTAS.csv","date_quotas_sha256")]:
            assert sha(OUT/vintage/filename)==record[key],f"BASE_FROZEN_KEYS_DRIFT:{vintage}"
    assert contract["sklearn"]==sklearn.__version__ and contract["numpy"]==np.__version__ and contract["pandas"]==pd.__version__
    return contract


def predict_base(models,frame):
    """Feature-only prediction helper; arbitrary target columns are ignored."""
    values=frame[FEATURES].to_numpy(float)
    assert np.isfinite(values).all()
    with threadpool_limits(limits=2):
        result=pd.DataFrame({f"p_{name}":models[name].predict(values) for name in NAMES},index=frame.index)
    assert np.isfinite(result.to_numpy()).all()
    return result


def load_base_models(vintage="final"):
    """Return ridge/hgb/mlp estimators after verifying artifact receipt hashes."""
    if vintage not in VINTAGES:
        raise ValueError(f"UNKNOWN_VINTAGE:{vintage}")
    receipt=read(OUT/vintage/"TRAIN_RECEIPT.json")
    assert receipt["status"]=="PASS" and receipt["cutoff_exclusive"]==VINTAGES[vintage]
    assert receipt["features"]==FEATURES
    for filename,digest in receipt["artifacts_sha256"].items():
        assert sha(OUT/vintage/filename)==digest,f"FROZEN_BASE_ARTIFACT_DRIFT:{vintage}:{filename}"
    return {name:joblib.load(OUT/vintage/f"{name}.joblib") for name in NAMES}


def fit_all():
    contract=verify_contract()
    lock_path=HERE/"DESIGN_LOCK.json"
    lock=read(lock_path)
    assert lock["status"]=="LOCKED_BEFORE_NEW_FITS" and lock["fit_enabled"] is True
    assert lock["base_prepare_sha256"]==sha(OUT/"BASE_PRE_FIT.json"),"PARENT_LOCK_BASE_CONTRACT_MISMATCH"
    if (OUT/"FIT_STARTED.json").exists() or (OUT/"TRAIN_RECEIPT.json").exists():
        raise RuntimeError("NINE_FIT_BATCH_ALREADY_STARTED_OR_COMPLETE_PRESERVED")
    write(OUT/"FIT_STARTED.json",{"base_prepare_sha256":sha(OUT/"BASE_PRE_FIT.json"),"parent_design_lock_sha256":sha(lock_path),"authorized_regressor_fits":9})
    frame=read_frame();receipts=[];oof_parts=[];fit_count=0;scaler_count=0
    for vintage,cutoff in VINTAGES.items():
        verify_contract()
        selected,keys,_,audit=sample(frame,cutoff)
        pd.testing.assert_frame_equal(keys,pd.read_parquet(OUT/vintage/"SAMPLE_KEYS.parquet"))
        x=selected[FEATURES].to_numpy(float);y=np.clip(selected.target.to_numpy(float),-.30,.30)
        weights=selected.sample_weight.to_numpy(float)
        models={};fit_records=[]
        for name in NAMES:
            print(f"FIT_START {vintage}/{name} rows={len(selected)}",flush=True)
            model=estimator(name);started=time.monotonic()
            with warnings.catch_warnings(record=True) as captured,threadpool_limits(limits=2):
                warnings.simplefilter("always")
                if name in ["ridge","mlp"]:
                    model.fit(x,y,scale__sample_weight=weights,regressor__sample_weight=weights)
                    scaler_count+=1
                else:
                    model.fit(x,y,sample_weight=weights)
            fit_count+=1
            regressor=model.named_steps["regressor"] if isinstance(model,Pipeline) else model
            iterations=getattr(regressor,"n_iter_",None)
            if name=="mlp":
                assert int(iterations)==40,"FIXED_MLP_EPOCH_CONTRACT_FAILED_NO_EXTRA_FIT_AUTHORIZED"
            if name=="hgb":
                assert int(iterations)==150
            joblib.dump(model,OUT/vintage/f"{name}.joblib",compress=3)
            fit_record={"name":name,"rows":len(selected),"seconds":time.monotonic()-started,
                        "iterations":int(iterations) if np.isscalar(iterations) and iterations is not None else None,
                        "warnings":[{"category":w.category.__name__,"message":str(w.message)} for w in captured]}
            fit_records.append(fit_record);models[name]=model
            write(OUT/"FIT_PROGRESS.json",{"regressor_fits_completed":fit_count,"scaler_fits_completed":scaler_count,"last_fit":fit_record})
            print(f"FIT_DONE {vintage}/{name} seconds={fit_record['seconds']:.2f}",flush=True)
        record={"status":"PASS","vintage":vintage,"cutoff_exclusive":cutoff,"features":FEATURES,
                "target":"target","training_target_clip":[-.30,.30],"unclipped_evaluation_target":True,
                "sample":audit,"fits":fit_records,"regressor_fit_calls":3,"scaler_fit_calls":2,
                "training_clipped_target_rows":int((np.abs(selected.target.to_numpy(float))>.30).sum()),
                "base_prepare_sha256":sha(OUT/"BASE_PRE_FIT.json"),"parent_design_lock_sha256":sha(lock_path),
                "artifacts_sha256":{f"{n}.joblib":sha(OUT/vintage/f"{n}.joblib") for n in NAMES}}
        write(OUT/vintage/"TRAIN_RECEIPT.json",record);receipts.append(record)
        if vintage!="final":
            year=int(vintage.split("_")[1]);test=frame[frame.signal_date.dt.year.eq(year)].copy()
            assert test.signal_date.ge(cutoff).all()
            predictions=predict_base(models,test)
            output=test[["signal_date","ticker","target","target_end_date","target_context_available"]].copy()
            for name in NAMES:
                output[f"p_{name}"]=predictions[f"p_{name}"]
            output["base_cutoff"]=pd.Timestamp(cutoff);output["base_vintage"]=vintage
            output=output[["signal_date","ticker","p_ridge","p_hgb","p_mlp","target","target_end_date","target_context_available","base_cutoff","base_vintage"]]
            output.to_parquet(OUT/vintage/"OOF_PREDICTIONS.parquet",index=False);oof_parts.append(output)
    assert fit_count==9 and scaler_count==6
    oof=pd.concat(oof_parts,ignore_index=True).sort_values(["signal_date","ticker"],kind="mergesort").reset_index(drop=True)
    assert not oof.duplicated(["signal_date","ticker"]).any()
    assert oof.base_cutoff.le(oof.signal_date).all() and set(oof.signal_date.dt.year)=={2024,2025}
    assert len(oof)==int(frame.signal_date.dt.year.isin([2024,2025]).sum())
    oof.to_parquet(OUT/"OOF_PREDICTIONS.parquet",index=False)
    verify_contract()
    assert sha(lock_path)==read(OUT/"FIT_STARTED.json")["parent_design_lock_sha256"],"PARENT_DESIGN_CHANGED_DURING_BASE_FITS"
    final={"status":"PASS_FIXED_NINE_BASE_FITS","regressor_fit_calls":fit_count,"scaler_fit_calls":scaler_count,
           "read_2026_rows":0,"old_models_modified":False,"searches":0,"oof_rows":len(oof),
           "oof_signal_days":int(oof.signal_date.nunique()),"unavailable_target_rows_retained":int((~oof.target_context_available).sum()),
           "source_files_unchanged":True,"base_prepare_sha256":sha(OUT/"BASE_PRE_FIT.json"),
           "parent_design_lock_sha256":sha(lock_path),"stage_receipts_sha256":{v:sha(OUT/v/"TRAIN_RECEIPT.json") for v in VINTAGES},
           "oof_sha256":sha(OUT/"OOF_PREDICTIONS.parquet"),"prediction_clip":None,"evaluation_target_clip":None}
    write(OUT/"TRAIN_RECEIPT.json",final)
    print(json.dumps(final,ensure_ascii=False),flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    operation=parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--prepare",action="store_true")
    operation.add_argument("--fit",action="store_true")
    args=parser.parse_args()
    prepare() if args.prepare else fit_all()
