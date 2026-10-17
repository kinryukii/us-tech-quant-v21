"""Only synthetic metadata; poison economic fields never decoded."""
from copy import deepcopy
import json
import pandas as pd
import pytest
from scripts.research.a2.evaluation import joint_control_sensitivity_qualification_r4 as e

OLD_RAW="R3::CONTROL_RAW_A2_POLICY@10bps"
OLD_EQUAL="R3::JOINT_SIMPLE_EQUAL@10bps"

def fixture(cost=5):
    inputs=dict(market="a"*64,raw_scores="b"*64,events="c"*64,uncertified_quality_only="d"*64)
    parent=dict(freeze=dict(input_sha256=inputs,source_sha256={"owner.py":"a"*64}))
    def q():
        return dict(mechanism_accounting_consistent=False,raw_endpoints_finite=True,
            quality_source_only_or_clear=True,unresolved_economic_exception_count=0,
            execution_audit_pass=True,selection_input_complete=True,actual_execution_inputs_complete=False,
            selection_input_gaps=[],actual_execution_input_gaps=[dict(date="2023-01-03",ticker="S",reason=e.REASON)],
            strict_PIT_promotion_eligible=False,certified_NAV=False,quote_qualified=False,status="BLOCKED")
    bindings=dict(parent_control_result_sha256="e"*64,account_freeze_sha256="f"*64,source_snapshot_sha256="1"*64)
    facts=[]
    for path in (OLD_RAW,OLD_EQUAL):
        facts.append(dict(path_id=path,date="2023-01-03",ticker="S",status="REJECTED",reason=e.REASON,
            **{k:True for k in e.gate._TRUE_FACTS},**{k:0 for k in e.gate._ZERO_FACTS},**bindings))
    bound=dict(original_qualification={OLD_RAW:q(),OLD_EQUAL:q()},rejection_facts=facts,**bindings)
    mapping=e.path_mapping(cost,bound["original_qualification"])
    result=dict(status="COMPLETE_CONTROL_SENSITIVITY_MECHANISM_REPLAY",cost_bps=cost,
        qualification={p:q() for p in mapping},audit=dict(
            **{k:0. for k in e.gate._AUDIT_ERRORS},max_actual_names=20,minimum_cash=0.,
            next_open_violations=0,capacity_violations=0),artifacts={},
        freeze=dict(**parent["freeze"],one_way_friction_bps=cost,scenario_path_ids=list(mapping),
            strict_PIT_promotion_eligible=False,certified_NAV=False,quote_qualified=False,
            initial_cash_usd="POISON_NAV_DO_NOT_DECODE"),
        freeze_sha256="2"*64,input_reuse=dict(nav="POISON_NAV_DO_NOT_DECODE"),
        exact39_uncertified_mask_preserved=True,new_fits=0,account_attempts=2,
        strict_PIT_promotion_eligible=False,quote_qualified=False,certified_nav_qualified=False,
        test2026_reads=0,scope="SENSITIVITY_NO_SELECTION")
    daily=pd.DataFrame([dict(path_id=p,date=d,accounting_qualified=True) for p in mapping for d in ("2023-01-02","2023-01-03")])
    frames=dict(daily=daily,positions=pd.DataFrame(columns=e.COLS["positions"]),
        fills=pd.DataFrame(columns=e.COLS["fills"]),
        execution_results=pd.DataFrame([dict(path_id=p,execution_date="2023-01-03",ticker="S",status="REJECTED",reason=e.REASON) for p in mapping]))
    return parent,bound,result,frames

def analyze(result,bound,facts,baseline):
    return e.gate.analyze_control_qualification(result["qualification"],result["audit"],facts,
        parent_control_result_sha256="3"*64,account_freeze_sha256=result["freeze_sha256"],
        source_snapshot_sha256=bound["source_snapshot_sha256"],
        baseline_economic_consistent=baseline,baseline_daily_flags_sha256="4"*64)

@pytest.mark.parametrize("cost",[5,20])
def test_new_cost_identity_maps_exact_raw_equal_with_fresh_exposure_proof(cost):
    parent,bound,result,frames=fixture(cost)
    facts,baseline,normalized,mapping=e.build_facts(result,parent,bound,frames,result_sha="3"*64)
    assert list(mapping)==[f"B_R_00_S{cost}",f"B_R_01_S{cost}"]
    assert len(facts)==2 and all(f["actual_fill_count"]==f["previous_held_position_count"]==f["current_held_position_count"]==0 for f in facts)
    out=analyze(result,bound,facts,baseline)
    assert out["conditional_mechanism_eligible"] and out["analysis_identity_sha256"]==e.gate.ANALYSIS_IDENTITY_SHA256
    assert out["new_account_attempts"]==out["new_fit_units"]==0
    assert not out["quote_qualified"] and not out["strict_PIT_promotion_eligible"]
    assert result["qualification"]["B_R_00_S"+str(cost)]["mechanism_accounting_consistent"] is False

@pytest.mark.parametrize("scenario",["previous_held","current_held","fill","daily","rejection"])
def test_nonzero_new_holdings_or_fills_and_failed_flags_never_reuse_parent_zero(scenario):
    parent,bound,result,frames=fixture()
    p="B_R_00_S5"
    if scenario in ("previous_held","current_held"):
        day="2023-01-02" if scenario=="previous_held" else "2023-01-03"
        frames["positions"]=pd.DataFrame([dict(path_id=p,date=day,ticker="S",fractional_shares=.01)])
    elif scenario=="fill":frames["fills"]=pd.DataFrame([dict(path_id=p,execution_date="2023-01-03",ticker="S")])
    elif scenario=="daily":frames["daily"].loc[0,"accounting_qualified"]=False
    else:frames["execution_results"].loc[0,"status"]="FILLED"
    facts,baseline,*_=e.build_facts(result,parent,bound,frames,result_sha="3"*64)
    out=analyze(result,bound,facts,baseline)
    assert not out["conditional_mechanism_eligible"]
    assert out["qualification"][p]["blocking_conditions"]

@pytest.mark.parametrize("scenario",["input","owner","cost","foreign_path","missing_previous","duplicate_daily","nonfinite_shares","extra_gap"])
def test_custody_and_snapshot_support_fail_closed(scenario):
    parent,bound,result,frames=fixture()
    if scenario=="input":result["freeze"]["input_sha256"]=dict(parent["freeze"]["input_sha256"],market="f"*64)
    elif scenario=="owner":result["freeze"]["source_sha256"]={"owner.py":"f"*64}
    elif scenario=="cost":result["freeze"]["one_way_friction_bps"]=20
    elif scenario=="foreign_path":frames["daily"].loc[0,"path_id"]="B_R_00_S20"
    elif scenario=="missing_previous":frames["daily"]=frames["daily"].loc[frames["daily"].date.eq("2023-01-03")]
    elif scenario=="duplicate_daily":frames["daily"]=pd.concat([frames["daily"],frames["daily"].iloc[:1]])
    elif scenario=="nonfinite_shares":frames["positions"]=pd.DataFrame([dict(path_id="B_R_00_S5",date="2023-01-03",ticker="S",fractional_shares=float("nan"))])
    else:result["qualification"]["B_R_00_S5"]["actual_execution_input_gaps"].append(dict(date="2023-01-03",ticker="OTHER",reason=e.REASON))
    with pytest.raises(e.SensitivityQualificationError):
        e.build_facts(result,parent,bound,frames,result_sha="3"*64)

def test_fixed_parser_skips_economic_values_before_any_json_decode(monkeypatch):
    *_,result,frames=fixture()
    lines=(json.dumps(result,indent=2)+"\n").splitlines(keepends=True)
    loads=json.loads
    def checked(value,*args,**kwargs):
        assert "POISON_NAV_DO_NOT_DECODE" not in value
        return loads(value,*args,**kwargs)
    monkeypatch.setattr(json,"loads",checked)
    projected=e.project_result_lines(lines)
    assert "input_reuse" not in projected and "initial_cash_usd" not in projected["freeze"]
    assert projected["qualification"]==result["qualification"]
    assert projected["freeze"]["input_sha256"]==result["freeze"]["input_sha256"]

def test_body_projection_cannot_gain_nav_or_other_economic_column():
    parent,bound,result,frames=fixture()
    frames["daily"]["nav"]="POISON"
    with pytest.raises(e.SensitivityQualificationError,match="EXACT_BODY_PROJECTION_REQUIRED"):
        e.build_facts(result,parent,bound,frames,result_sha="3"*64)
