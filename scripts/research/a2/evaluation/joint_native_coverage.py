"""Source-bound C native OOF reuse with full-row B five-day bridges.

The inspect command reads hashes, sidecars, and Parquet footers only. The fit
command is deliberately a serial V24 state writer. C target/score columns are
never projected, and no C base estimator is refitted by B.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scripts.research.a2.data.joint_input_binding import FEATURES,load_training_inputs
from scripts.research.a2.ensemble import joint_oof_bridge as bridge
from scripts.research.a2.evaluation.joint_execution_resume import digest
from scripts.research.a2.evaluation.joint_method_coverage import JointMethodCoverage,SEED
from scripts.research.a2.evaluation.joint_method_stages import task_writer

NATIVE_NAMES=(
    "ridge","elastic","huber","ebm","rf","extra","hgb","xgb","lgb","cat",
    "mlp","resnet","fttransformer","logistic","rf_class","hgb_class","xgb_class",
    "lgb_class","cat_class","mlp_class","linear_q","hgb_q","xgb_q","lgb_q",
    "cat_q","mlp_q","ngboost","gaussian_mlp","cat_uncertainty","xgb_rank",
    "lgb_rank","svc","tcn","lstm","gru","pca_ridge","fa_ridge","kmeans_ridge",
    "gmm_ridge","iforest_ridge")
METHOD_NATIVE={
    1:("ridge",),2:("elastic",),3:("huber",),4:("logistic",),
    5:("hgb","hgb_class"),6:("xgb","xgb_class"),7:("lgb","lgb_class"),
    8:("cat","cat_class"),9:("rf","rf_class"),10:("extra",),11:("ebm",),
    12:("mlp","mlp_class"),13:("resnet",),14:("fttransformer",),15:("tcn",),
    16:("lstm",),17:("gru",),18:("xgb_rank",),19:("lgb_rank",),
    20:("linear_q",),21:("hgb_q",),22:("xgb_q",),23:("lgb_q",),
    24:("cat_q",),25:("mlp_q",),26:("ngboost",),27:("gaussian_mlp",),
    28:("cat_uncertainty",),29:("svc",),45:("kmeans_ridge",),
    46:("gmm_ridge",),47:("iforest_ridge",),48:("pca_ridge",),49:("fa_ridge",)}
KEY_FIELDS=("signal_date","ticker","security_uid","U_t_fingerprint","source_kind","source_cutoff")
SUFFIXES=("raw","p","q10","q50","q90","location","scale","rank")
NATIVE_TARGET="MEAN_ER_3D_5D_10D_20D"
DEFAULT_NATIVE_ROOT=Path("D:/us-tech-quant-backtests/V24/20261001T091119+0000_126f67f0")

class NativeDependencyError(ValueError):
    """An unproven source is unavailable; do not substitute a model or row."""

def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

def _json_sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,default=str,allow_nan=False).encode()).hexdigest()

def _frame_sha(frame):
    header=json.dumps([(str(c),str(frame[c].dtype)) for c in frame],separators=(",",":"))
    h=hashlib.sha256(header.encode())
    h.update(pd.util.hash_pandas_object(frame,index=False).to_numpy().tobytes())
    return h.hexdigest()

def _checked_path(root,relative,declared):
    expected=(root/relative).resolve()
    if not expected.is_relative_to(root) or Path(declared).resolve()!=expected:
        raise NativeDependencyError("NATIVE_SOURCE_PATH_MISMATCH:"+relative)
    return expected

def bind_native_design(native_root):
    """Verify frozen design, current source bytes and input hashes, without pages."""
    root=Path(native_root).resolve();path=root/"DESIGN_FREEZE.json"
    if not path.exists():raise NativeDependencyError("MISSING_NATIVE_DESIGN")
    sha=digest(path);declared=_read_json(root/"DESIGN_FREEZE_SHA.json")["sha256"]
    if sha!=declared:raise NativeDependencyError("NATIVE_DESIGN_HASH_MISMATCH")
    design=_read_json(path)
    if (design.get("version")!="V24" or design.get("line")!="C_SELECTOR"
        or design.get("target")!=NATIVE_TARGET or design.get("features")!=list(FEATURES)
        or set(design.get("base",[]))!=set(NATIVE_NAMES)
        or design.get("years")!=list(range(2021,2026))
        or design.get("training_sample",{}).get("max_rows")!=40000
        or design.get("training_sample",{}).get("seed")!=SEED):
        raise NativeDependencyError("UNEXPECTED_NATIVE_DESIGN_IDENTITY")
    sources=design.get("sources",{});inputs=design.get("inputs",{})
    if not sources or not {"training","features","members","raw_oof"}.issubset(inputs):
        raise NativeDependencyError("MISSING_NATIVE_FROZEN_DEPENDENCIES")
    for source,expected in sources.items():
        if not Path(source).exists() or digest(source)!=expected:
            raise NativeDependencyError("NATIVE_FROZEN_SOURCE_HASH_MISMATCH:"+source)
    for name,item in inputs.items():
        if not Path(item["path"]).exists() or digest(item["path"])!=item["sha256"]:
            raise NativeDependencyError("NATIVE_INPUT_HASH_MISMATCH:"+name)
    return {"root":str(root),"design":design,"design_sha256":sha,
            "design_sidecar_sha256":digest(root/"DESIGN_FREEZE_SHA.json"),
            "fitted_source_sha256":dict(sources),"input_dependencies":inputs}

def inspect_native_fold(binding,name,year):
    """Validate authoritative TRAINED sidecar and allowed-column physical boundary."""
    if name not in NATIVE_NAMES or year not in range(2021,2026):
        raise NativeDependencyError("UNREGISTERED_NATIVE_FOLD")
    root=Path(binding["root"]).resolve();sidepath=root/f"models/{name}/{year}.json"
    if not sidepath.exists():raise NativeDependencyError("MISSING_NATIVE_SIDECAR")
    side=_read_json(sidepath);spec=side.get("spec",{});cutoff=pd.Timestamp(year,1,1)
    if side.get("status")!="TRAINED":
        raise NativeDependencyError("NATIVE_FOLD_NOT_TRAINED:"+str(side.get("status")))
    expected={"name":name,"year":year,"cutoff":str(cutoff.date()),
              "target":NATIVE_TARGET,"seed":SEED,"features":list(FEATURES),
              "design_sha256":binding["design_sha256"],
              "training_sha256":binding["input_dependencies"]["training"]["sha256"],
              "feature_sha256":binding["input_dependencies"]["features"]["sha256"]}
    if any(spec.get(k)!=v for k,v in expected.items()):
        raise NativeDependencyError("NATIVE_FOLD_IDENTITY_MISMATCH")
    maturity=pd.Timestamp(spec.get("max_train_label_end"))
    if pd.isna(maturity) or maturity>=cutoff or not spec.get("sampled_keys_sha256"):
        raise NativeDependencyError("NATIVE_LABEL_MATURITY_NOT_PRIOR_TO_FIT")
    sampled=root/f"derived/training_keys_{year}.parquet"
    if not sampled.exists() or digest(sampled)!=spec["sampled_keys_sha256"]:
        raise NativeDependencyError("NATIVE_SAMPLED_KEYS_HASH_MISMATCH")
    pred=_checked_path(root,f"predictions/native_{name}_{year}.parquet",side.get("prediction_path",""))
    model=_checked_path(root,f"models/{name}/{year}.joblib",side.get("model_path",""))
    for label,path in (("prediction",pred),("model",model)):
        if not path.exists() or digest(path)!=side.get(label+"_sha256"):
            raise NativeDependencyError("NATIVE_"+label.upper()+"_HASH_MISMATCH")
    parquet=pq.ParquetFile(pred);schema=parquet.schema_arrow.names
    required={"signal_date","ticker","source_cutoff"}
    if not required.issubset(schema):raise NativeDependencyError("MISSING_NATIVE_KEY_LINEAGE")
    columns=[c for c in KEY_FIELDS if c in schema]
    columns += [name+"__"+s for s in SUFFIXES if name+"__"+s in schema]
    typed=bridge._schema(pd.DataFrame(columns=columns),{"native_name":name})
    bounds=[]
    for group in range(parquet.num_row_groups):
        row={}
        for field in ("signal_date","source_cutoff"):
            stats=parquet.metadata.row_group(group).column(schema.index(field)).statistics
            if stats is None or not stats.has_min_max or stats.null_count:
                raise NativeDependencyError("MISSING_COMPLETE_NATIVE_DATE_FOOTER")
            low=pd.Timestamp(stats.min);high=pd.Timestamp(stats.max)
            if field=="signal_date":
                if low<cutoff or high>=pd.Timestamp(year+1,1,1) or high>=pd.Timestamp("2026-01-01"):
                    raise NativeDependencyError("NATIVE_PHYSICAL_SIGNAL_BOUNDARY")
            elif low!=cutoff or high!=cutoff:
                raise NativeDependencyError("NATIVE_PHYSICAL_FIT_CUTOFF_BOUNDARY")
            row[field]={"min":str(low),"max":str(high)}
        bounds.append(row)
    if parquet.metadata.num_rows!=side.get("rows") or not parquet.metadata.num_rows:
        raise NativeDependencyError("NATIVE_PREDICTION_ROW_COUNT_MISMATCH")
    return {"name":name,"year":year,"status":"READY_NATIVE_PROJECTION",
            "sidecar_path":str(sidepath),"sidecar_sha256":digest(sidepath),
            "prediction_path":str(pred),"prediction_sha256":side["prediction_sha256"],
            "model_path":str(model),"model_sha256":side["model_sha256"],
            "design_sha256":binding["design_sha256"],
            "fitted_source_sha256":binding["fitted_source_sha256"],
            "training_sha256":spec["training_sha256"],"feature_sha256":spec["feature_sha256"],
            "sampled_keys_path":str(sampled),"sampled_keys_sha256":spec["sampled_keys_sha256"],
            "source_label_mature_max":str(maturity),"source_cutoff":str(cutoff),
            "rows":parquet.metadata.num_rows,"row_groups":parquet.num_row_groups,
            "projection_columns":columns,"native_schema":typed,"date_bounds":bounds,
            "excluded_columns":sorted(set(schema)-set(columns)),
            "reuse":"DIFFERENT_TARGET_NATIVE_REUSE; C_BASE_MAX40000; B_BRIDGE_FULL_ROWS"}

def read_native_fold(binding,record):
    """Recheck bytes, then project only authorized keys and native fields."""
    fresh=inspect_native_fold(binding,record["name"],record["year"])
    if fresh!=record:raise NativeDependencyError("NATIVE_DEPENDENCY_CHANGED_AFTER_INSPECTION")
    frame=pq.ParquetFile(record["prediction_path"]).read(columns=record["projection_columns"]).to_pandas()
    frame["signal_date"]=pd.to_datetime(frame.signal_date)
    frame["source_cutoff"]=pd.to_datetime(frame.source_cutoff)
    frame["source_label_mature_max"]=pd.Timestamp(record["source_label_mature_max"])
    bridge._check_raw(frame,True)
    if len(frame)!=record["rows"]:raise NativeDependencyError("NATIVE_PROJECTED_ROWS_CHANGED")
    return frame

def inspect_native_sources(native_root,names=NATIVE_NAMES):
    """A metadata readiness snapshot; zero prediction/target pages or fit writes."""
    binding=bind_native_design(native_root);records=[]
    for name in names:
        if name not in NATIVE_NAMES:raise NativeDependencyError("UNREGISTERED_NATIVE_NAME")
        for year in range(2021,2026):
            try:records.append(inspect_native_fold(binding,name,year))
            except (NativeDependencyError,bridge.BridgeDependencyError) as exc:
                records.append({"name":name,"year":year,"status":"MISSING_OR_UNPROVEN_DEPENDENCY","reason":str(exc)})
    ready=sum(r["status"]=="READY_NATIVE_PROJECTION" for r in records)
    return {"status":"METADATA_READY" if ready==len(records) else "PARTIAL_NATIVE_READINESS",
            "binding":binding,"folds":records,"ready_folds":ready,"requested_folds":len(records),
            "prediction_pages_read":0,"C_target_or_score_pages_read":0,"new_fit_units":0}

def bridge_fit_key(binding,prior,train,spec,source_sha):
    """Bind all predictor bytes and exact transformed joined values omitted by parent."""
    columns=["signal_date","ticker","source_cutoff","source_label_mature_max",
             *bridge._schema(train,spec)["native_columns"],
             *[c for c in train if c.startswith("_bridge_x_")],
             "y_open5","label_mature_date","label_end_date"]
    columns=[c for c in columns if c in train]
    return {"spec":spec,"sources":source_sha,"native_design_sha256":binding["design_sha256"],
            "native_fitted_source_sha256":binding["fitted_source_sha256"],
            "prior_native_fold_dependencies":prior,
            "joined_predictor_value_columns":columns,
            "joined_predictor_values_sha256":_frame_sha(train[columns]),
            "C_native_target":NATIVE_TARGET,"C_native_sample_cap":40000,
            "B_bridge_sampling":"NONE_ALL_ELIGIBLE_ROWS","B_target_clip":None}

def update_native_coverage(coverage,summary):
    """Append native evidence while preserving prior real-fit and failure status."""
    out=coverage.copy()
    for number,names in METHOD_NATIVE.items():
        mask=out.method_id.eq(f"M{number:03d}")
        if not mask.any():continue
        completed=all(summary["methods"].get(name,{}).get("completed_years")==[2022,2023,2024,2025] for name in names)
        if not completed:continue
        for row in out.index[mask]:
            evidence="receipts/NATIVE_BRIDGE_SUMMARY.json;"+";".join(f"OOF/B_NATIVE_{name}_2022..2025.parquet" for name in names)
            old=out.at[row,"evidence"]
            out.at[row,"evidence"]=";".join(dict.fromkeys((str(old).split(";") if pd.notna(old) and str(old) else [])+evidence.split(";")))
            if out.at[row,"status"]=="REGISTERED_NOT_RUN":
                out.at[row,"status"]="DIFFERENT_TARGET_NATIVE_REUSE_AND_FULL_ROW_5DAY_BRIDGE_COMPLETE"
    return out

class JointNativeCoverage(JointMethodCoverage):
    def fit_native(self,native_root,names=NATIVE_NAMES):
        snapshot=inspect_native_sources(native_root,names)
        binding=snapshot["binding"]
        source_sha={str(path):digest(path) for path in (
            Path(__file__).resolve(),Path(bridge.__file__).resolve(),
            Path(__import__("scripts.research.a2.data.joint_input_binding",fromlist=["x"]).__file__).resolve(),
            Path(__import__("scripts.research.a2.evaluation.joint_method_coverage",fromlist=["x"]).__file__).resolve(),
            bridge._RETAINED)}
        freeze={"status":"FROZEN_BEFORE_NATIVE_BRIDGE_FIT","names":list(names),
                "years":[2022,2023,2024,2025],"source_sha256":source_sha,
                "input_binding_sha256":self.input_sha,"run_config_sha256":digest(self.out("RUN_CONFIG.json")),
                "native_design_sha256":binding["design_sha256"],
                "native_source_sha256":binding["fitted_source_sha256"],
                "native_target":NATIVE_TARGET,"native_fit_row_cap":40000,
                "B_target":self.parameters["target"],"bridge_alpha":100,"minimum_rows":100,
                "B_sampling":"NONE_ALL_EARLIER_MATURED_OOF","target_clip":None,
                "weighting":"equal decision date mass","native_base_refit_units":0,
                "estimated_states":["StandardScaler","Ridge","residual_RMS","native_scale_ratio_for_distribution_or_quantiles"],
                "writer_mode":"SERIAL_WITH_OTHER_V24_STATE_WRITERS","test2026_pages_read":0}
        freeze_path=self.out("receipts/NATIVE_BRIDGE_FREEZE.json")
        if freeze_path.exists():
            if self.read("receipts/NATIVE_BRIDGE_FREEZE.json")!=freeze:
                raise RuntimeError("Native bridge freeze changed; preserve earlier identity")
        else:self.write("receipts/NATIVE_BRIDGE_FREEZE.json",freeze)
        truth=load_training_inputs(self.out("INPUT_BINDING.json"))
        columns=["signal_date","ticker","execution_date","label_end_date","label_mature_date",
                 "y_open5","fit_eligible","trade_eligible","label_available"]
        truth=truth[[c for c in columns if c in truth]].copy()
        records={(r["name"],r["year"]):r for r in snapshot["folds"]}
        summary={"status":"NATIVE_BRIDGES_RUNNING","methods":{},"native_base_refits":0,
                 "native_training_sample_cap":40000,"B_sampling":"ALL_EARLIER_MATURED_OOF_ROWS",
                 "C_target_or_score_pages_read":0,"test2026_pages_read":0,
                 "freeze_sha256":digest(freeze_path),"missing_dependencies":[]}
        for name in names:
            history=[];prior=[];method={"completed_years":[],"folds":[]};summary["methods"][name]=method
            for year in range(2021,2026):
                record=records[(name,year)]
                if record["status"]!="READY_NATIVE_PROJECTION":
                    summary["missing_dependencies"].append(record);break
                raw=read_native_fold(binding,record)
                if year==2021:
                    history.append(raw);prior.append(record);continue
                cutoff=pd.Timestamp(year,1,1)
                spec={"native_name":name,"native_role":record["native_schema"]["role"],
                      "alpha":100,"minimum_rows":100,"native_target":NATIVE_TARGET,
                      "B_target":self.parameters["target"]["name"],"native_fit_row_cap":40000,
                      "native_source_receipt":[r["sidecar_sha256"] for r in prior]}
                all_prior=pd.concat(history,ignore_index=True)
                try:train,schema=bridge.prepare_native_training(all_prior,truth,cutoff,spec)
                except bridge.BridgeDependencyError as exc:
                    blocked={"name":name,"year":year,"status":"BLOCKED_BRIDGE_INPUT","reason":str(exc),
                             "prior_native_fold_dependencies":prior,"new_fit_units":0}
                    method["folds"].append(blocked);summary["missing_dependencies"].append(blocked)
                    self.write("receipts/NATIVE_BRIDGE_SUMMARY.json",summary)
                    break
                for source,expected in {**source_sha,**binding["fitted_source_sha256"]}.items():
                    if digest(source)!=expected:raise RuntimeError("Bridge fitted source changed before fit:"+source)
                key=bridge_fit_key(binding,prior,train,spec,source_sha)
                kind="five_day_native_bridge_"+name
                bundle=self.fit_state(kind,year,key,train,
                    lambda:bridge.fit_native_bridge(all_prior,truth,cutoff,spec),
                    4 if schema["role"] in ("distribution","quantile") else 3)
                artifact=self.out(f"models/{kind}_{year}.joblib")
                output=self.out(f"OOF/B_NATIVE_{name}_{year}.parquet")
                receipt_rel=f"receipts/B_NATIVE_{name}_{year}.json"
                receipt_path=self.out(receipt_rel)
                identity={"bridge_model_sha256":digest(artifact),"fit_key_sha256":_json_sha(key),
                          "application_native_dependencies":record,"freeze_sha256":digest(freeze_path),
                          "input_binding_sha256":self.input_sha}
                if output.exists() or receipt_path.exists():
                    if not output.exists() or not receipt_path.exists():
                        raise RuntimeError("Unregistered native OOF preserved")
                    old=self.read(receipt_rel)
                    if old.get("identity")!=identity or old.get("sha256")!=digest(output):
                        raise RuntimeError("Frozen native OOF identity or bytes changed")
                    report=old
                else:
                    block=bridge.apply_native_bridge(raw,bundle)
                    block=block.merge(truth,on=["signal_date","ticker"],how="left",validate="one_to_one",sort=False)
                    block["fold_year"]=year
                    block["source_fit_cutoff"]=cutoff
                    block.to_parquet(output,index=False)
                    report={"status":"REAL_PRIOR_NATIVE_OOF_FULL_ROW_FIVE_DAY_BRIDGE","name":name,"year":year,
                            "identity":identity,"oof_path":str(output),"sha256":digest(output),
                            "fit_rows":bundle["fit_rows"],"fit_dates":bundle["fit_dates"],
                            "source_label_mature_max":bundle["label_mature_max"],
                            "native_prediction_rows":len(block),"bridge_available_rows":int(block.bridge_available.sum()),
                            "trade_eligible_rows":int(block.trade_eligible.eq(True).sum()),
                            "native_role":schema["role"],"native_target":NATIVE_TARGET,
                            "expected_return_coordinate":bundle["B_target"],"learned_states":bundle["fit_units"],
                            "native_base_fit_units_by_B":0,"native_base_training_sample_max_rows":40000,
                            "B_full_eligible_samples":True,"target_clip":None,
                            "uncertainty_scope":bundle["uncertainty_scope"],"test2026_pages_read":0}
                    self.write(receipt_rel,report)
                method["completed_years"].append(year);method["folds"].append(report)
                self.write("receipts/NATIVE_BRIDGE_SUMMARY.json",summary)
                history.append(raw);prior.append(record)
                del train,all_prior
            del history
        complete=all(m["completed_years"]==[2022,2023,2024,2025] for m in summary["methods"].values())
        summary["status"]="NATIVE_BRIDGES_COMPLETE" if complete else "NATIVE_BRIDGES_PARTIAL_DEPENDENCIES"
        self.write("receipts/NATIVE_BRIDGE_SUMMARY.json",summary)
        coverage=pd.read_csv(self.out("METHOD_COVERAGE.csv"))
        update_native_coverage(coverage,summary).to_csv(self.out("METHOD_COVERAGE.csv"),index=False)
        self.status["status"]=summary["status"];self.checkpoint()
        return summary

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("command",choices=("inspect","fit-native"))
    parser.add_argument("--native-root",default=str(DEFAULT_NATIVE_ROOT))
    parser.add_argument("--task-root")
    parser.add_argument("--names",nargs="*",choices=NATIVE_NAMES)
    args=parser.parse_args();names=tuple(args.names) if args.names else NATIVE_NAMES
    if len(names)!=len(set(names)):parser.error("Duplicate names would duplicate method identities")
    if args.command=="inspect":
        snapshot=inspect_native_sources(args.native_root,names)
        print(json.dumps(snapshot,ensure_ascii=False,default=str,allow_nan=False),flush=True)
    else:
        if not args.task_root:parser.error("fit-native requires --task-root")
        with task_writer(args.task_root):
            summary=JointNativeCoverage(args.task_root).fit_native(args.native_root,names)
        print(json.dumps({"status":summary["status"],"methods":len(summary["methods"]),
                          "missing_dependencies":len(summary["missing_dependencies"])},ensure_ascii=False),flush=True)

if __name__=="__main__":main()
