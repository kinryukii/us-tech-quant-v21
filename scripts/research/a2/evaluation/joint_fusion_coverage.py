"""Serial B five-day meta/residual orchestration over existing frozen OOF."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scripts.research.a2.data.joint_input_binding import FEATURES,guard_parquet,load_training_inputs,load_held_features
from scripts.research.a2.ensemble import joint_five_day_fusion as fusion
from scripts.research.a2.ensemble import joint_oof_bridge as bridge
from scripts.research.a2.evaluation.joint_execution_resume import digest
from scripts.research.a2.evaluation.joint_method_coverage import JointMethodCoverage
from scripts.research.a2.evaluation.joint_method_stages import task_writer
from scripts.research.a2.evaluation.joint_native_coverage import _frame_sha,_json_sha

META_MAPPING={32:"equal",33:"median",34:"fixed_weighted",35:"nnls",36:"simplex",37:"ridge_stack",38:"elastic_stack",39:"hgb_stack",40:"mlp_stack",41:"linear_gate",42:"mlp_gate"}
RESID_MAPPING={43:"ridge_then_hgb",44:"hgb_then_ridge"}
TRUTH_COLUMNS=("signal_date","ticker","execution_date","label_end_date","label_mature_date","y_open5","fit_eligible","trade_eligible","label_available")

def read_bound_oof(task,relative,receipt_relative,columns):
    """Hash/own-date footer gate before authorized projection; no inferred lineage."""
    receipt=task.read(receipt_relative);path=task.out(relative)
    expected=receipt.get("sha256")
    if not expected:raise RuntimeError("OOF receipt missing content digest:"+relative)
    parquet,metadata=guard_parquet(path,expected,["signal_date"])
    if any(c not in parquet.schema_arrow.names for c in columns):raise RuntimeError("Required OOF field absent:"+relative)
    return parquet.read(columns=list(columns)).to_pandas(),{
        "path":str(path),"sha256":expected,"receipt_path":str(task.out(receipt_relative)),
        "receipt_sha256":digest(task.out(receipt_relative)),"footer":metadata,"receipt":receipt}

def source_dependencies():
    from scripts.research.a2.evaluation import joint_sequential_training as runtime
    from scripts.research.a2.evaluation import joint_method_coverage as parent
    from scripts.research.a2.data import joint_input_binding as data
    from scripts.research.a2.evaluation import joint_native_coverage as native
    from scripts.research.a2.evaluation import joint_method_stages as stages
    fusion._source_guard()
    paths=(Path(__file__),Path(fusion.__file__),Path(bridge.__file__),Path(parent.__file__),
           Path(runtime.__file__),Path(runtime.runtime_bootstrap.__file__),
           fusion._SOURCE,fusion._COOP,bridge._RETAINED,Path(data.__file__),Path(native.__file__),Path(stages.__file__))
    return {str(p.resolve()):digest(p) for p in paths}

class JointFusionCoverage(JointMethodCoverage):
    def _freeze(self):
        sources=source_dependencies()
        obj={"status":"FROZEN_BEFORE_B_FULL_ROW_FIVE_DAY_META_RESIDUAL_FIT", "spec":fusion.SPEC,
            "meta_mapping":{str(k):v for k,v in META_MAPPING.items()},"residual_mapping":{str(k):v for k,v in RESID_MAPPING.items()},
            "meta_years":[2023,2024,2025],"residual_years":[2022,2023,2024,2025],
            "input_binding_sha256":self.input_sha,"run_config_sha256":digest(self.out("RUN_CONFIG.json")),
            "source_sha256":sources,"native_base_refits":0,"B_primary_refits":0,
            "writer":"existing task_writer lease","test2026_pages_read":0}
        path=self.out("receipts/FIVE_DAY_FUSION_FREEZE.json")
        if path.exists():
            if self.read("receipts/FIVE_DAY_FUSION_FREEZE.json")!=obj:raise RuntimeError("Meta/residual frozen identity changed")
        else:self.write("receipts/FIVE_DAY_FUSION_FREEZE.json",obj)
        return sources,digest(path)

    def _save(self,prefix,name,year,block,identity,report):
        rel=f"OOF/{prefix}_{name}_{year}.parquet";receipt_rel=f"receipts/{prefix}_{name}_{year}.json"
        path=self.out(rel);receipt_path=self.out(receipt_rel)
        if path.exists() or receipt_path.exists():
            if not path.exists() or not receipt_path.exists():raise RuntimeError("Unregistered output preserved:"+rel)
            old=self.read(receipt_rel)
            if old.get("identity")!=identity or old.get("sha256")!=digest(path):raise RuntimeError("Frozen output identity/bytes changed:"+rel)
            return old
        block.to_parquet(path,index=False)
        result={**report,"identity":identity,"oof_path":str(path),"sha256":digest(path),"rows":len(block),"test2026_pages_read":0}
        self.write(receipt_rel,result);return result

    def _native_surface(self,year,truth):
        block=truth.loc[truth.signal_date.ge(pd.Timestamp(year,1,1))&truth.signal_date.lt(pd.Timestamp(year+1,1,1))].copy()
        dependencies=[];reference_keys=None
        for name in fusion.MEMBERS:
            rel=f"OOF/B_NATIVE_{name}_{year}.parquet";receipt_rel=f"receipts/B_NATIVE_{name}_{year}.json"
            native,dep=read_bound_oof(self,rel,receipt_rel,["signal_date","ticker","mu","bridge_cutoff","source_cutoff"])
            receipt=dep["receipt"]
            if receipt["identity"]["input_binding_sha256"]!=self.input_sha:raise RuntimeError("Native bridge B input identity changed")
            keys=native[["signal_date","ticker"]].sort_values(["signal_date","ticker"]).reset_index(drop=True)
            if keys.duplicated().any():raise RuntimeError("Duplicate native member key")
            if reference_keys is None:reference_keys=keys
            elif not keys.equals(reference_keys):raise RuntimeError("Native fixed member key mismatch; do not shrink intersection")
            if not keys.merge(block[["signal_date","ticker"]],on=["signal_date","ticker"],how="left",indicator=True)._merge.eq("both").all():
                raise RuntimeError("Native member has unbound B truth keys")
            model=self.out(f"models/five_day_native_bridge_{name}_{year}.joblib")
            if digest(model)!=receipt["identity"]["bridge_model_sha256"]:raise RuntimeError("Native B bridge model changed")
            native=native.rename(columns={"mu":name+"__mu","bridge_cutoff":name+"__bridge_cutoff","source_cutoff":name+"__source_cutoff"})
            native[name+"__bridge_label_mature_max"]=pd.Timestamp(receipt["source_label_mature_max"])
            block=block.merge(native,on=["signal_date","ticker"],how="inner",validate="one_to_one",sort=False)
            dependencies.append(dep)
        return block,dependencies

    def fit_meta(self,sources,freeze_sha):
        truth=load_training_inputs(self.out("INPUT_BINDING.json"))
        needed=[*TRUTH_COLUMNS,*fusion.CONTEXT]
        truth=truth[[c for c in dict.fromkeys(needed) if c in truth]]
        surfaces={};deps={};result={"status":"META_RUNNING","methods":{},"missing_dependencies":[],"freeze_sha256":freeze_sha}
        for year in range(2022,2026):
            try:surfaces[year],deps[year]=self._native_surface(year,truth)
            except FileNotFoundError as exc:result["missing_dependencies"].append({"year":year,"reason":str(exc)})
        for method in fusion.METHODS:
            result["methods"][method]={"completed_years":[],"folds":[]}
            for year in range(2023,2026):
                years=list(range(2022,year))
                if year not in surfaces or any(y not in surfaces for y in years):continue
                history=pd.concat([surfaces[y] for y in years],ignore_index=True)
                try:train,cut=fusion.prepare_fusion_training(history,pd.Timestamp(year,1,1))
                except fusion.FusionDependencyError as exc:
                    result["missing_dependencies"].append({"method":method,"year":year,"reason":str(exc)});continue
                key={"method":method,"spec":fusion.SPEC,"source_sha256":sources,
                     "prior_B_native_OOF_dependencies":[d for y in years for d in deps[y]],
                     "actual_meta_predictor_values_sha256":_frame_sha(train),"sampling":"ALL_PRIOR_MATURED_ROWS"}
                for path,sha in sources.items():
                    if digest(path)!=sha:raise RuntimeError("Meta fitted source changed:"+path)
                kind="five_day_meta_"+method
                bundle=self.fit_state(kind,year,key,train,lambda:fusion.fit_five_day_fusion(history,cut,method),fusion.fusion_fit_units(method))
                block=fusion.apply_five_day_fusion(surfaces[year],bundle)
                block["source_fit_cutoff"]=cut;block["fold_year"]=year
                identity={"fit_key_sha256":_json_sha(key),"model_sha256":digest(self.out(f"models/{kind}_{year}.joblib")),
                    "application_dependencies":deps[year],"freeze_sha256":freeze_sha,"input_binding_sha256":self.input_sha}
                report=self._save("B_META",method,year,block,identity,{"status":"REAL_FULL_ROW_FIVE_DAY_CHRONOLOGICAL_META_OOF","method":method,**bundle["receipt"]})
                result["methods"][method]["completed_years"].append(year);result["methods"][method]["folds"].append(report)
                self.write("receipts/FIVE_DAY_META_SUMMARY.json",result)
        result["status"]="META_COMPLETE" if all(v["completed_years"]==[2023,2024,2025] for v in result["methods"].values()) else "META_PARTIAL_DEPENDENCIES"
        self.write("receipts/FIVE_DAY_META_SUMMARY.json",result)
        return result

    def fit_residual(self,sources,freeze_sha):
        truth=load_training_inputs(self.out("INPUT_BINDING.json"))
        truth=truth[[c for c in TRUTH_COLUMNS if c in truth]]
        features=load_held_features(self.out("INPUT_BINDING.json"))[["signal_date","ticker",*FEATURES]]
        initial={};deps={}
        for year in range(2021,2026):
            block,dep=read_bound_oof(self,f"OOF/INITIAL_{year}.parquet",f"receipts/INITIAL_{year}.json",
                ["signal_date","ticker","source_fit_cutoff","Ridge_raw","HGB_raw"])
            block=block.merge(features,on=["signal_date","ticker"],how="left",validate="one_to_one",sort=False)
            primary_artifacts={}
            for name in ("Ridge","HGB"):
                artifact=self.out(f"models/five_day_{name}_{year}.joblib")
                record=next((r for r in self.status["records"] if r["identity"]["kind"]=="five_day_"+name and r["identity"]["cutoff_exclusive"]==f"{year}-01-01"),None)
                if record is None or record["status"]!="FIT_COMPLETE" or digest(artifact)!=record["sha256"]:
                    raise RuntimeError("Existing B primary model digest/fit lineage changed")
                primary_artifacts[name]={"path":str(artifact),"sha256":record["sha256"],"identity":record["identity"]}
            dep["primary_artifacts"]=primary_artifacts
            dep["initial_fit_freeze_sha256"]=digest(self.out("receipts/INITIAL_FIT_FREEZE.json"))
            initial[year]=block.merge(truth,on=["signal_date","ticker"],how="left",validate="one_to_one",sort=False);deps[year]=dep
        result={"status":"RESIDUAL_RUNNING","methods":{},"freeze_sha256":freeze_sha}
        for method in RESID_MAPPING.values():
            result["methods"][method]={"completed_years":[],"folds":[]};composite_history=[];composite_deps=[]
            for year in range(2022,2026):
                cutoff=pd.Timestamp(year,1,1);history=pd.concat([initial[y] for y in range(2021,year)],ignore_index=True)
                train,cut,primary=fusion.prepare_residual_training(history,cutoff,method)
                key={"method":method,"source_sha256":sources,"spec":fusion.SPEC,
                    "prior_existing_B_primary_OOF_dependencies":[deps[y] for y in range(2021,year)],
                    "actual_primary_OOF_predictor_and_residual_values_sha256":_frame_sha(train),"primary_refit_units":0}
                for path,sha in sources.items():
                    if digest(path)!=sha:raise RuntimeError("Residual fitted source changed:"+path)
                kind="five_day_feature_residual_"+method
                bundle=self.fit_state(kind,year,key,train,lambda:fusion.fit_oof_residual(history,cutoff,method),2)
                raw=fusion.apply_oof_residual(initial[year],bundle)
                bridge_kind="five_day_residual_calibration_"+method;calibration_identity=None
                if composite_history:
                    prior=pd.concat(composite_history,ignore_index=True)
                    spec={"native_name":method,"native_role":"return","B_target":fusion.UNIT,"native_target":"B_PRIMARY_RAW_PLUS_CANONICAL32_OOF_RESIDUAL","alpha":100,"minimum_rows":100}
                    prepared,_=bridge.prepare_native_training(prior,truth,cutoff,spec)
                    bridge_key={"spec":spec,"source_sha256":sources,"prior_true_composite_OOF_dependencies":composite_deps,
                        "actual_composite_predictor_values_sha256":_frame_sha(prepared)}
                    calibrated=self.fit_state(bridge_kind,year,bridge_key,prepared,lambda:bridge.fit_native_bridge(prior,truth,cutoff,spec),3)
                    block=bridge.apply_native_bridge(raw,calibrated)
                    calibration_identity={"key_sha256":_json_sha(bridge_key),"model_sha256":digest(self.out(f"models/{bridge_kind}_{year}.joblib"))}
                else:
                    block=raw.copy();block["mu"]=np.nan;block["sigma"]=np.nan;block["bridge_available"]=False
                    block["bridge_status"]="NO_EARLIER_TRUE_COMPOSITE_OOF";block["expected_return_coordinate"]=fusion.UNIT
                block["source_fit_cutoff"]=cutoff;block["fold_year"]=year
                identity={"fit_key_sha256":_json_sha(key),"secondary_model_sha256":digest(self.out(f"models/{kind}_{year}.joblib")),
                    "calibration":calibration_identity,"application_existing_B_primary_OOF_dependency":deps[year],
                    "freeze_sha256":freeze_sha,"input_binding_sha256":self.input_sha}
                report=self._save("B_RESID",method,year,block,identity,{"status":"REAL_EXISTING_PRIMARY_OOF_CANONICAL32_SECONDARY","method":method,"year":year,
                    "secondary_receipt":bundle["receipt"],"prior_composite_calibrated":bool(composite_history),"primary_refit_units":0,
                    "bridge_fit_units":3 if composite_history else 0})
                composite_history.append(raw[["signal_date","ticker","source_cutoff","source_label_mature_max",method+"__raw"]].copy())
                composite_deps.append({"oof_path":report["oof_path"],"sha256":report["sha256"],"identity":report["identity"]})
                result["methods"][method]["completed_years"].append(year);result["methods"][method]["folds"].append(report)
                self.write("receipts/FIVE_DAY_RESIDUAL_SUMMARY.json",result)
        result["status"]="RESIDUAL_COMPLETE";self.write("receipts/FIVE_DAY_RESIDUAL_SUMMARY.json",result);return result

    def fit_fusion(self):
        sources,freeze_sha=self._freeze();meta=self.fit_meta(sources,freeze_sha);residual=self.fit_residual(sources,freeze_sha)
        coverage=pd.read_csv(self.out("METHOD_COVERAGE.csv"))
        for mapping,result,years,status in ((META_MAPPING,meta,[2023,2024,2025],"REAL_FULL_ROW_FIVE_DAY_TRUE_OOF_META_COMPLETE"),(RESID_MAPPING,residual,[2022,2023,2024,2025],"REAL_EXISTING_PRIMARY_OOF_CANONICAL32_RESIDUAL_COMPLETE")):
            for number,method in mapping.items():
                if result["methods"].get(method,{}).get("completed_years")!=years:continue
                mask=coverage.method_id.eq(f"M{number:03d}")
                coverage.loc[mask,"status"]=status
                prefix="B_META" if mapping is META_MAPPING else "B_RESID"
                coverage.loc[mask,"evidence"]=f"receipts/FIVE_DAY_FUSION_FREEZE.json;OOF/{prefix}_{method}_"+"..".join(map(str,(years[0],years[-1])))+".parquet"
        coverage.to_csv(self.out("METHOD_COVERAGE.csv"),index=False)
        self.status["status"]="FIVE_DAY_FUSION_AND_RESIDUAL_COMPLETE" if meta["status"]=="META_COMPLETE" else "FIVE_DAY_FUSION_PARTIAL_NATIVE_DEPENDENCIES"
        self.checkpoint()
        return {"meta":meta["status"],"residual":residual["status"]}

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--task-root",required=True)
    parser.add_argument("command",choices=("fit-fusion",));args=parser.parse_args()
    with task_writer(args.task_root):result=JointFusionCoverage(args.task_root).fit_fusion()
    print(json.dumps(result),flush=True)

if __name__=="__main__":main()
