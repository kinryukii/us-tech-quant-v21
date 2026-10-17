"""R4 metadata producer over the unchanged R3 control qualification analysis.

Fixed JSON scanner and genuine projected account snapshots remain existing
owners. No account replay, price/cache load, forecast, fitting or result metric.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import json
from types import FunctionType
import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import pyarrow as pa
from scripts.common.storage_paths import resolve,assert_safe_output_path
from scripts.research.a2.evaluation import joint_r4_runtime as runtime
from scripts.research.a2.evaluation import joint_mechanism_control_qualification_r3 as gate
from scripts.research.a2.evaluation import joint_frozen_history_risk_bank_r3 as bank
from scripts.research.a2.data.joint_input_binding import guard_parquet
from scripts.research.a2.evaluation.joint_native_coverage import _frame_sha
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash

SCHEMA="B_R4_CONTROL_SENSITIVITY_QUALIFICATION_PRODUCER_V1"
REASON="PRICE_QUALITY_UNCERTIFIED"
COLS=dict(daily=["path_id","date","accounting_qualified"],
    positions=["path_id","date","ticker","fractional_shares"],
    fills=["path_id","execution_date","ticker"],
    execution_results=["path_id","execution_date","ticker","status","reason"])
_ROOT={"status","cost_bps","qualification","audit","artifacts","freeze","freeze_sha256",
    "input_reuse","exact39_uncertified_mask_preserved","new_fits","account_attempts",
    "strict_PIT_promotion_eligible","quote_qualified","certified_nav_qualified","test2026_reads","scope"}
_FREEZE={"research_id","parent_research_id","run_id","registration_receipt_sha256","input_sha256",
    "source_sha256","identity_assumption","status","research_kind","valuation","raw_price_coordinate",
    "quantity_coordinate","source_authority","historical_availability","historical_revision",
    "identity_coordinate_consistent","strict_PIT_promotion_eligible","certified_NAV","quote_qualified",
    "initial_cash_usd","one_way_friction_bps","fee_bps","cash_interest","synthetic","scenario_path_ids"}

class SensitivityQualificationError(ValueError):pass

def _field(path,key,profile):
    """Fixed existing indent2 parser policy, only control metadata is decoded."""
    if not path:
        if key not in _ROOT:raise SensitivityQualificationError("UNKNOWN_CONTROL_RESULT_FIELD")
        return key!="input_reuse"
    if path==("qualification",):return True
    if len(path)==2 and path[0]=="qualification":allowed=gate._QUALIFICATION_FIELDS
    elif len(path)==4 and path[0]=="qualification" and path[2] in ("actual_execution_input_gaps","selection_input_gaps"):
        allowed={"date","ticker","reason"}
    elif path==("audit",):allowed={*gate._AUDIT_ERRORS,"max_actual_names","minimum_cash","next_open_violations","capacity_violations"}
    elif path==("artifacts",):
        if key not in {"daily","positions","orders","fills","execution_results","contexts","operational_actions","accounting_exceptions","entitlements"}:
            raise SensitivityQualificationError("UNKNOWN_CONTROL_ARTIFACT")
        return key in COLS
    elif len(path)==2 and path[0]=="artifacts":allowed={"path","sha256","rows"}
    elif path==("freeze",):
        if key not in _FREEZE:raise SensitivityQualificationError("UNKNOWN_CONTROL_FREEZE_FIELD")
        return key in {"input_sha256","source_sha256","one_way_friction_bps","scenario_path_ids",
            "strict_PIT_promotion_eligible","certified_NAV","quote_qualified"}
    elif path==("freeze","input_sha256"):allowed={"market","raw_scores","events","uncertified_quality_only"}
    elif path==("freeze","source_sha256"):return True
    else:raise SensitivityQualificationError("UNKNOWN_CONTROL_METADATA_PATH")
    if key not in allowed:raise SensitivityQualificationError("UNKNOWN_SELECTED_CONTROL_METADATA_FIELD")
    return True

class _ControlProjection(bank._FixedProducerProjection):pass
# The scanner stays byte-for-byte with its owner; selection is local to this
# subclass's function globals and never mutates the frozen module.
_ControlProjection.value=FunctionType(bank._FixedProducerProjection.value.__code__,
    dict(bank._FixedProducerProjection.value.__globals__,_fixed_field=_field),
    name="value",argdefs=bank._FixedProducerProjection.value.__defaults__)

def project_result_lines(lines):
    return _ControlProjection(lines,"control_sensitivity",65536).parse()

def _result(path):
    if Path(path).stat().st_size>1024*1024:raise SensitivityQualificationError("CONTROL_RESULT_BOUND_EXCEEDED")
    with Path(path).open(encoding="utf-8",newline="") as stream:
        return project_result_lines(iter(lambda:stream.readline(65537),""))

def path_mapping(cost,parent_paths):
    if type(cost) is not int or cost not in (5,20):raise SensitivityQualificationError("ONLY_FROZEN_S5_S20")
    raw=[p for p in parent_paths if p.endswith("::CONTROL_RAW_A2_POLICY@10bps")]
    equal=[p for p in parent_paths if p.endswith("::JOINT_SIMPLE_EQUAL@10bps")]
    if len(raw)!=1 or len(equal)!=1 or len(parent_paths)!=2:
        raise SensitivityQualificationError("EXACT_PARENT_RAW_EQUAL_IDENTITIES_REQUIRED")
    return {f"B_R_00_S{cost}":raw[0],f"B_R_01_S{cost}":equal[0]}

def _date(value):
    t=pd.Timestamp(value)
    if pd.isna(t) or t!=t.normalize():raise SensitivityQualificationError("SESSION_MIDNIGHT_REQUIRED")
    if t.tzinfo is not None:t=t.tz_convert("UTC")
    if t.year<2023 or t>=pd.Timestamp("2026-01-01",tz=t.tz):
        raise SensitivityQualificationError("PRE2026_CONTROL_SESSION_REQUIRED")
    return t.date().isoformat()

def _frames(frames,paths):
    normalized={}
    for name,columns in COLS.items():
        f=frames[name].copy()
        if list(f.columns)!=columns:raise SensitivityQualificationError("EXACT_BODY_PROJECTION_REQUIRED")
        if not f.path_id.isin(paths).all():raise SensitivityQualificationError("FOREIGN_PROJECTED_ACCOUNT_PATH")
        clock="execution_date" if name in {"fills","execution_results"} else "date"
        f[clock]=f[clock].map(_date)
        normalized[name]=f
    daily=normalized["daily"]
    if daily.duplicated(["path_id","date"]).any():raise SensitivityQualificationError("DUPLICATE_DAILY_BASELINE")
    for path in paths:
        if not daily.path_id.eq(path).any():raise SensitivityQualificationError("MISSING_PATH_DAILY_BASELINE")
    pos=normalized["positions"]
    if pos.duplicated(["path_id","date","ticker"]).any():raise SensitivityQualificationError("AMBIGUOUS_POSITION_SNAPSHOT")
    if not np.isfinite(pos.fractional_shares.to_numpy(float)).all() or pos.fractional_shares.lt(0).any():
        raise SensitivityQualificationError("NONFINITE_OR_NEGATIVE_POSITION_PROOF")
    for name in ("positions","fills","execution_results"):
        clock="execution_date" if name!="positions" else "date"
        f=normalized[name]
        joined=f[["path_id",clock]].rename(columns={clock:"date"}).merge(
            daily[["path_id","date"]],on=["path_id","date"],how="left",indicator=True)
        if joined["_merge"].ne("both").any():raise SensitivityQualificationError("MISSING_DAILY_SESSION_FOR_PROJECTED_EVENT")
    return normalized

def build_facts(result,parent_freeze,parent_bound,frames,*,result_sha):
    cost=result["cost_bps"];mapping=path_mapping(cost,parent_bound["original_qualification"])
    if (set(result["qualification"])!=set(mapping)
        or result["freeze"]["input_sha256"]!=parent_freeze["freeze"]["input_sha256"]
        or result["freeze"]["source_sha256"]!=parent_freeze["freeze"]["source_sha256"]
        or result["freeze"]["one_way_friction_bps"]!=cost
        or result["freeze"]["scenario_path_ids"]!=list(mapping)
        or result.get("exact39_uncertified_mask_preserved") is not True
        or result.get("new_fits")!=0 or result.get("test2026_reads")!=0
        or result.get("account_attempts")!=2
        or any(result.get(f) is not False for f in ("strict_PIT_promotion_eligible","quote_qualified","certified_nav_qualified"))):
        raise SensitivityQualificationError("INPUT_SOURCE_OR_FIXED_SCENARIO_NOT_IDENTICAL")
    for flag in gate._FALSE_SOURCE_FLAGS:
        if result["freeze"].get(flag) is not False:raise SensitivityQualificationError("SOURCE_FLAGS_CHANGED")
    f=_frames(frames,set(mapping));daily=f["daily"];positions=f["positions"];fills=f["fills"];executions=f["execution_results"]
    original={(r["path_id"],_date(r["date"]),r["ticker"]):r for r in parent_bound["rejection_facts"]}
    if len(original)!=len(parent_bound["rejection_facts"]):raise SensitivityQualificationError("AMBIGUOUS_PARENT_FACT")
    current=[];baseline={p:bool(daily.loc[daily.path_id.eq(p),"accounting_qualified"].map(lambda x:type(x) in (bool,np.bool_) and bool(x)).all()) for p in mapping}
    for path,qualification in result["qualification"].items():
        parent=parent_bound["original_qualification"][mapping[path]]
        old_keys={( _date(g["date"]),g["ticker"],g["reason"]) for g in parent["actual_execution_input_gaps"]}
        new_keys={( _date(g["date"]),g["ticker"],g["reason"]) for g in qualification["actual_execution_input_gaps"]}
        if old_keys!=new_keys or len(new_keys)!=len(qualification["actual_execution_input_gaps"]):
            raise SensitivityQualificationError("NEW_GAPS_NOT_EXACT_PARENT_COORDINATES")
        sessions=sorted(daily.loc[daily.path_id.eq(path),"date"].tolist())
        for gap in qualification["actual_execution_input_gaps"]:
            day=_date(gap["date"]);ticker=gap["ticker"]
            if day not in sessions:raise SensitivityQualificationError("MISSING_REJECTION_DAILY_SESSION")
            before=[d for d in sessions if d<day]
            if not before:raise SensitivityQualificationError("NO_PREVIOUS_ACCOUNT_SNAPSHOT")
            raw=original[(mapping[path],day,ticker)]
            if any(raw.get(k)!=parent_bound[k] for k in gate._BINDINGS):
                raise SensitivityQualificationError("PARENT_FACT_CUSTODY_CHANGED")
            matched=executions.loc[executions.path_id.eq(path)&executions.execution_date.eq(day)&executions.ticker.eq(ticker)]
            rejection=bool(len(matched)==1 and matched.iloc[0]["status"]=="REJECTED" and matched.iloc[0]["reason"]==REASON)
            held=lambda date:int(positions.loc[positions.path_id.eq(path)&positions.date.eq(date)&positions.ticker.eq(ticker),"fractional_shares"].gt(0).sum())
            fill_count=int((fills.path_id.eq(path)&fills.execution_date.eq(day)&fills.ticker.eq(ticker)).sum())
            prev,currentheld=held(before[-1]),held(day)
            fact={k:raw[k] for k in ("raw_row_present","raw_open_positive_finite","raw_close_positive_finite","signal_adv_positive_finite")}
            fact.update(path_id=path,date=day,ticker=ticker,status="REJECTED" if rejection else "UNPROVEN",
                reason=gap["reason"],actual_fill_count=fill_count,previous_held_position_count=prev,
                current_held_position_count=currentheld,economic_coordinate_not_used=rejection and fill_count==prev==currentheld==0,
                unsupported_events_preserved=raw.get("unsupported_events_preserved") is True,
                parent_control_result_sha256=result_sha,account_freeze_sha256=result["freeze_sha256"],
                source_snapshot_sha256=parent_bound["source_snapshot_sha256"])
            current.append(fact)
    return current,baseline,f,mapping

def _read_projected(run,cost,result):
    frames={};proof=[]
    for name,columns in COLS.items():
        ref=result["artifacts"][name];path=Path(ref["path"])
        expected=Path(run)/"derived"/f"control_sensitivity_{cost}bps"/(name+".parquet")
        if path.resolve()!=expected.resolve():raise SensitivityQualificationError("FOREIGN_CONTROL_TRACE_PATH")
        clock="execution_date" if name in {"fills","execution_results"} else "date"
        pf,footer=guard_parquet(path,ref["sha256"],[clock])
        field=pf.schema_arrow.field(clock);tz=field.type.tz if pa.types.is_timestamp(field.type) else None
        start=pd.Timestamp("2023-01-01",tz=tz).to_pydatetime()
        stop=pd.Timestamp("2026-01-01",tz=tz).to_pydatetime()
        predicate=(ds.field(clock)>=pa.scalar(start,type=field.type))&(ds.field(clock)<pa.scalar(stop,type=field.type))
        table=ds.dataset(path,format="parquet").scanner(columns=columns,filter=predicate,use_threads=False).to_table()
        frames[name]=table.to_pandas()
        proof.append(dict(artifact=deepcopy(ref),projection_columns=columns,physical_footer=footer,
            predicate=f"2023-01-01 <= {clock} < 2026-01-01",projected_rows=len(table),
            body_projection_sha256=_frame_sha(frames[name]),excluded_value_columns_not_decoded=True))
    return frames,proof

def execute(run):
    run=Path(run);runtime.guard(run)
    paths=resolve(runtime.REPO);assert_safe_output_path(run,kind="backtest",paths=paths)
    state=runtime.read_json(run/"EXECUTION_STATE.json");parent=Path(state["parent_run"])
    parent_freeze=runtime.read_json(parent/"CONTROL_ACCOUNT_FREEZE.json")
    parent_bound=runtime.read_json(parent/"CONTROL_QUALIFIER_BOUND_INPUTS.json")
    parent_analysis=runtime.read_json(parent/"CONTROL_QUALIFICATION_ANALYSIS_R2.json")
    if (parent_analysis.get("analysis_identity_sha256")!=gate.ANALYSIS_IDENTITY_SHA256
        or parent_analysis.get("conditional_mechanism_eligible") is not True
        or parent_analysis.get("rejection_facts_sha256")!=content_hash(parent_bound["rejection_facts"])
        or parent_analysis.get("original_qualification_sha256")!=content_hash(parent_bound["original_qualification"])
        or parent_analysis.get("baseline_daily_flags_sha256")!=parent_bound["baseline_daily_flags_sha256"]
        or any(parent_analysis.get("bindings",{}).get(k)!=parent_bound[k] for k in gate._BINDINGS)
        or any(parent_analysis.get(k) is not False for k in ("strict_PIT_promotion_eligible","quote_qualified","certified_NAV"))
        or runtime.sha(parent/"CONTROL_ACCOUNT_FREEZE.json")!=parent_bound["account_freeze_sha256"]):
        raise SensitivityQualificationError("PARENT_QUALIFIER_CUSTODY_UNPROVED")
    manifest=parent/"input_manifest.json"
    if not manifest.exists():raise SensitivityQualificationError("PARENT_INPUT_MANIFEST_REQUIRED")
    custody=dict(parent_bound_inputs_ref=dict(path=str(parent/"CONTROL_QUALIFIER_BOUND_INPUTS.json"),sha256=runtime.sha(parent/"CONTROL_QUALIFIER_BOUND_INPUTS.json")),
        parent_analysis_ref=dict(path=str(parent/"CONTROL_QUALIFICATION_ANALYSIS_R2.json"),sha256=runtime.sha(parent/"CONTROL_QUALIFICATION_ANALYSIS_R2.json")),
        parent_input_manifest_ref=dict(path=str(manifest),sha256=runtime.sha(manifest)),
        parent_account_freeze_ref=dict(path=str(parent/"CONTROL_ACCOUNT_FREEZE.json"),sha256=runtime.sha(parent/"CONTROL_ACCOUNT_FREEZE.json")),
        original_analysis_identity_sha256=gate.ANALYSIS_IDENTITY_SHA256)
    analyses={};allfacts={};flags={}
    for cost in (5,20):
        path=run/f"CONTROL_SENSITIVITY_S{cost}_RESULT.json";result=_result(path)
        result_sha=runtime.sha(path)
        # Identity/input equality precedes any parquet BODY read.
        mapping=path_mapping(cost,parent_bound["original_qualification"])
        if result["freeze"]["input_sha256"]!=parent_freeze["freeze"]["input_sha256"]:
            raise SensitivityQualificationError("SOURCE_FACT_REUSE_INPUT_MISMATCH")
        if result["freeze"]["source_sha256"]!=parent_freeze["freeze"]["source_sha256"]:
            raise SensitivityQualificationError("SOURCE_OWNER_CODE_CHANGED")
        for p,h in result["freeze"]["source_sha256"].items():runtime._pin(p,h,"control_common_owner")
        frames,projection=_read_projected(run,cost,result)
        facts,baseline,normalized,mapping=build_facts(result,parent_freeze,parent_bound,frames,result_sha=result_sha)
        baseline_proof=dict(path_dates=normalized["daily"].to_dict(orient="records"),
            daily_projection_sha256=_frame_sha(normalized["daily"]),baseline_economic_consistent=baseline,
            projection=projection)
        baseline_digest=content_hash(baseline_proof)
        analysis=gate.analyze_control_qualification(result["qualification"],result["audit"],facts,
            parent_control_result_sha256=result_sha,account_freeze_sha256=result["freeze_sha256"],
            source_snapshot_sha256=parent_bound["source_snapshot_sha256"],
            baseline_economic_consistent=baseline,baseline_daily_flags_sha256=baseline_digest)
        analyses[str(cost)]=dict(result_ref=dict(path=str(path),sha256=result_sha),analysis=analysis,
            new_to_parent_path_mapping=mapping,source_input_digests_exactly_identical=True,
            account_freeze_binding_kind="PRODUCER_FREEZE_DIGEST_IN_HASH_BOUND_SENSITIVITY_RESULT")
        allfacts[str(cost)]=facts;flags[str(cost)]=baseline_proof
    common=dict(schema=SCHEMA,producer_sha256=runtime.sha(__file__),parent_custody=custody,
        whole_matrix_sha256=runtime.sha(run/"WHOLE_MATRIX_FREEZE.json"),new_fit_units=0,
        new_account_attempts=0,market_cache_loaded=False,price_columns_decoded=False,
        NAV_return_Sharpe_columns_decoded=False,test2026_rows_read=0,
        strict_PIT_promotion_eligible=False,quote_qualified=False,certified_nav_qualified=False,
        original_results_and_traces_preserved=True,source_only_conditional_analysis=True)
    payload=dict(**common,costs=analyses,conditional_mechanism_eligible=all(a["analysis"]["conditional_mechanism_eligible"] for a in analyses.values()))
    runtime.write(run,"CONTROL_SENSITIVITY_QUALIFICATION_FACTS_R1.json",dict(**common,rejection_facts=allfacts),immutable=True)
    runtime.write(run,"CONTROL_SENSITIVITY_PROJECTED_ECONOMIC_FLAGS_R1.json",dict(**common,projected_flags=flags),immutable=True)
    runtime.write(run,"CONTROL_SENSITIVITY_QUALIFICATION_ANALYSIS_R1.json",payload,immutable=True)
    return dict(conditional_mechanism_eligible=payload["conditional_mechanism_eligible"],
        by_cost={c:{p:dict(eligible=v["conditional_mechanism_eligible"],declared_constraints=len(v["declared_execution_constraints"]),blocks=v["blocking_conditions"])
            for p,v in a["analysis"]["qualification"].items()} for c,a in analyses.items()},
        new_fit_units=0,new_account_attempts=0,test2026_rows_read=0)

def main():
    p=argparse.ArgumentParser();p.add_argument("--run",required=True);args=p.parse_args()
    print(json.dumps(execute(args.run),sort_keys=True),flush=True)
if __name__=="__main__":main()
