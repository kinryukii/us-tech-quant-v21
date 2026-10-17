"""R4 four unchanged control sensitivity tuples over the existing account owner.

No estimator, price repair, new policy recipe, certified NAV or 2026 reader.
The immutable whole matrix plus descendant execution binding precedes inputs.
"""
from dataclasses import dataclass, asdict
from pathlib import Path
import argparse, json, os
import numpy as np
from scripts.research.a2.evaluation.joint_r4_runtime import guard, read_json, write, sha, _pin, ID, REPO
from scripts.research.a2.evaluation.joint_frozen_history_r3 import (
    FrozenHistoryAccountFreeze, _freeze_guard, _qualify, ACCOUNT, input_digests, source_pins)
from scripts.research.a2.evaluation import continuous_research_account as common
from scripts.research.a2.inference.joint_portfolio_policy import JointResearchPolicy
from scripts.research.a2.evaluation.joint_method_accounts import PARAMETERS
from scripts.research.a2.evaluation.joint_frozen_history_r3_runner import load_control_inputs
from scripts.common.storage_paths import assert_safe_output_path, resolve

@dataclass(frozen=True)
class SensitivityFreeze(FrozenHistoryAccountFreeze):
    scenario_path_ids: tuple=()
    @property
    def path_ids(self): return self.scenario_path_ids

def run_pair(market,scores,events,mask,parent,expected_parent_sha,cost,registration_sha,run_id):
    if cost not in (5,20): raise ValueError("ONLY_OLD_5_20_BPS_SENSITIVITY_TUPLES")
    _freeze_guard(parent,expected_parent_sha,market,scores,events,mask)
    paths=(f"B_R_00_S{cost}",f"B_R_01_S{cost}")
    values=asdict(parent)
    values.update(research_id=ID,parent_research_id=parent.research_id,run_id=run_id,
        registration_receipt_sha256=registration_sha,one_way_friction_bps=float(cost),
        scenario_path_ids=paths)
    freeze=SensitivityFreeze(**values)
    before=input_digests(market,scores,events,mask)
    mu=np.repeat(np.asarray(scores)[:,None,:],2,axis=1)
    sigma=np.where(np.isfinite(mu),0.,np.nan)
    policy=JointResearchPolicy(paths,mu,sigma,{},roles={paths[0]:dict(kind="raw"),paths[1]:dict(kind="simple")},parameters=PARAMETERS)
    gaps={path:[] for path in paths}
    def checked(day,ctx):
        needed=np.asarray(ctx.decision_mask,bool)&(np.asarray(ctx.buy_allowed,bool)|(ctx.current_units>1e-10))
        for row,col in zip(*np.nonzero(needed&~np.isfinite(mu[day]))):
            gaps[paths[row]].append(dict(date=str(ctx.signal_date),ticker=str(ctx.tickers[col]),reason="MISSING_ACTUAL_ELIGIBLE_FROZEN_SCORE"))
        return policy(day,ctx)
    friction=dict(kind="FIXED_ADVERSE_OPEN_SLIPPAGE",one_way_bps=cost,fee_bps=0,benchmark="NEXT_RAW_OPEN",authority="HYPOTHETICAL_RESEARCH_SCENARIO",scenario_id=ID+f"::S{cost}")
    replay=common.run_continuous_account(market,paths,checked,dict(ACCOUNT),execution_friction=friction,**events)
    if before!=input_digests(market,scores,events,mask): raise ValueError("SHARED_INPUT_MUTATION")
    qualification=_qualify(replay,market,mask,freeze,gaps)
    replay.metadata.update(controls=list(paths),scope="SENSITIVITY_NO_SELECTION",cost_bps=cost)
    return replay,qualification,freeze

def bind_execution(run,expected_matrix_sha):
    matrix=guard(run,expected_matrix_sha)
    spec=run/"B_POLICY_SPECIFICATION.json"
    if not any(Path(r["path"]).resolve()==spec.resolve() and r["sha256"]==sha(spec) for r in matrix["pinned_artifacts"]):
        raise ValueError("POLICY_SPEC_NOT_FROZEN")
    frozen=read_json(spec)
    actual=[r for r in frozen["original_sensitivity"] if r["id"] in ("B_R_00_S5","B_R_00_S20","B_R_01_S5","B_R_01_S20")]
    if len(actual)!=4 or any(r["risk"]!="NONE" or r["cost_bps"] not in (5,20) or r["configs"]!=1 for r in actual):
        raise ValueError("ORIGINAL_CONTROL_SENSITIVITY_SCOPE_CHANGED")
    pins=source_pins()
    pins[str(Path(__file__).resolve())]=sha(__file__)
    pins[str(Path(load_control_inputs.__code__.co_filename).resolve())]=sha(load_control_inputs.__code__.co_filename)
    binding=dict(schema="B_R4_CONTROL_SENSITIVITY_EXECUTION_BINDING_V1",research_id=ID,
        whole_matrix_ref=dict(path=str(run/"WHOLE_MATRIX_FREEZE.json"),sha256=expected_matrix_sha),
        policy_spec_ref=dict(path=str(spec),sha256=sha(spec)),code_pins=[dict(path=p,sha256=h) for p,h in pins.items()],
        exact_original_tuples=actual,scientific_recipe_unchanged=True,scientific_retry=0,
        test2026_reads=0,strict_PIT_promotion_eligible=False,fit_units=0)
    target=run/"CONTROL_SENSITIVITY_EXECUTION_BINDING_R1.json"
    if target.exists() and read_json(target)!=binding: raise ValueError("IMMUTABLE_BINDING_CHANGED")
    write(run,target.name,binding)
    return sha(target)

def execute(run,expected_matrix_sha,expected_binding_sha):
    run=Path(run);guard(run,expected_matrix_sha)
    binding_path=run/"CONTROL_SENSITIVITY_EXECUTION_BINDING_R1.json"
    _pin(binding_path,expected_binding_sha,"r4_control_execution")
    binding=read_json(binding_path)
    for ref in [binding["whole_matrix_ref"],binding["policy_spec_ref"]]+binding["code_pins"]:
        _pin(ref["path"],ref["sha256"],"r4_control_dependency")
    if binding["scientific_recipe_unchanged"] is not True or binding["scientific_retry"]!=0:
        raise ValueError("CONTROL_EXECUTION_SCOPE_CHANGED")
    parent_run=Path(read_json(run/"EXECUTION_STATE.json")["parent_run"])
    payload=read_json(parent_run/"CONTROL_ACCOUNT_FREEZE.json")
    parent=FrozenHistoryAccountFreeze(**payload["freeze"])
    # The existing loader verifies every acquisition/cash/raw receipt before body read.
    market,scores,events,mask,raw_reuse,keys=load_control_inputs(parent_run)
    out={}
    for cost in (5,20):
        result_name=f"CONTROL_SENSITIVITY_S{cost}_RESULT.json"
        if (run/result_name).exists():
            out[str(cost)]=read_json(run/result_name);continue
        claim=run/"work"/f"CONTROL_SENSITIVITY_S{cost}_ATTEMPT_CLAIM.json"
        assert_safe_output_path(claim,kind="backtest",paths=resolve(REPO));claim.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(claim,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            json.dump(dict(cost_bps=cost,account_attempts=2,pid=os.getpid(),scientific_retry=0),stream);stream.flush();os.fsync(stream.fileno())
        try:
            replay,qualification,freeze=run_pair(market,scores,events,mask,parent,payload["expected_freeze_sha256"],cost,sha(run/"REGISTRATION_RECEIPT.json"),run.name)
            artifacts={}
            for name in ("daily","positions","orders","fills","execution_results","contexts","operational_actions","accounting_exceptions","entitlements"):
                frame=getattr(replay,name,None)
                if frame is None:continue
                target=run/"derived"/f"control_sensitivity_{cost}bps"/(name+".parquet")
                assert_safe_output_path(target,kind="backtest",paths=resolve(REPO));target.parent.mkdir(parents=True,exist_ok=True)
                frame.to_parquet(target,index=False);artifacts[name]=dict(path=str(target),sha256=sha(target),rows=len(frame))
            result=dict(status="COMPLETE_CONTROL_SENSITIVITY_MECHANISM_REPLAY",cost_bps=cost,
                qualification=qualification,audit=replay.audit,artifacts=artifacts,freeze=asdict(freeze),freeze_sha256=freeze.digest(),
                input_reuse=raw_reuse,exact39_uncertified_mask_preserved=True,new_fits=0,account_attempts=2,
                strict_PIT_promotion_eligible=False,quote_qualified=False,certified_nav_qualified=False,test2026_reads=0,scope="SENSITIVITY_NO_SELECTION")
            write(run,result_name,result);out[str(cost)]=result
        except Exception as exc:
            write(run,f"CONTROL_SENSITIVITY_S{cost}_FAILURE.json",dict(status="FAILED_ATTEMPTS_RETAINED",error=type(exc).__name__+":"+str(exc),account_attempts=2,new_fits=0,scientific_retry=0,test2026_reads=0));raise
    return out

def main():
    p=argparse.ArgumentParser();p.add_argument("--run",required=True);p.add_argument("--expected-matrix-sha",required=True)
    p.add_argument("--expected-binding-sha");p.add_argument("--phase",choices=("bind","execute"),required=True)
    args=p.parse_args();run=Path(args.run)
    if args.phase=="bind":print(bind_execution(run,args.expected_matrix_sha),flush=True)
    else:
        result=execute(run,args.expected_matrix_sha,args.expected_binding_sha)
        print(json.dumps({k:{a:v[a] for a in ("status","account_attempts","new_fits","test2026_reads")} for k,v in result.items()}),flush=True)
if __name__=="__main__":main()
