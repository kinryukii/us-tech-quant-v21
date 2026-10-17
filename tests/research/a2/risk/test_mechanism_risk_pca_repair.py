"""Review unapplied R3/PCA repair against generated whole RiskStates only."""
import types,hashlib,copy,importlib.util
from pathlib import Path
from dataclasses import replace
import numpy as np
import pytest
from scripts.research.a2.risk import mechanism_risk_adapter as frozen_adapter

CANDIDATE=Path("D:/us-tech-quant-cache/research/V24_A_STATEFUL_ACTION_RISK_FULL_BREADTH_R10/R10_R3_PCA_CONSUMER_REPAIR_candidate.py.txt")
CANDIDATE_SHA="2011d302182cfb8dacf482b447a14d96193263a92a5f420bb34f54cffbcc8b4f"


@pytest.fixture(scope="module")
def candidate():
    assert hashlib.sha256(CANDIDATE.read_bytes()).hexdigest()==CANDIDATE_SHA
    module=types.ModuleType("scripts.research.a2.risk._review_pca_patch")
    module.__package__="scripts.research.a2.risk";module.__file__=frozen_adapter.__file__
    exec(compile(CANDIDATE.read_text(encoding="utf-8"),module.__file__,"exec"),module.__dict__)
    # Candidate is intentionally NOT applied. Simulate only its actual self pin;
    # every other owner is the already frozen physical source/unchanged module.
    old=frozen_adapter.code_pins();old[str(Path(module.__file__))]=module.R3_REPAIR_OLD_ADAPTER_SHA
    new={**old,str(Path(module.__file__)):CANDIDATE_SHA}
    module.code_pins=lambda:dict(new)
    return module,old,new


def receipt(candidate):
    module,old,new=candidate
    return dict(schema="R10_R3_PCA_CONSUMER_ENGINEERING_REPAIR_R1",approved=True,reviewed=True,
        old_adapter_sha256=module.R3_REPAIR_OLD_ADAPTER_SHA,new_adapter_sha256=CANDIDATE_SHA,
        human_request_sha256=module.R3_REPAIR_HUMAN_REQUEST_SHA,parent_design_sha256=module.R3_REPAIR_PARENT_DESIGN_SHA,
        old_code_pins=old,new_code_pins=new,risk_fit_started_before_repair=0,
        repair_scope="PREDECLARED_R3_FACTOR_PCA_CONSUMER_OMISSION_ONLY",scientific_target_changed=False,
        budget_changed=False,source_authority_activated=False,**{"2026_locked":True})


@pytest.fixture(scope="module")
def generated():
    path=Path(__file__).with_name("test_mechanism_risk_adapter.py")
    spec=importlib.util.spec_from_file_location("pca_review_generated_fixture",path)
    fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
    inputs,asof=fixture.generated()
    out=fixture.run(inputs,asof,methods=("PCA",))
    assert out["status"]=="COMPLETE_MECHANISM_ONLY"
    state=out["states"]["PCA"]
    args=dict(assets=inputs.assets,uids=inputs.asset_uids,reference_assets=inputs.assets,decision_at=asof,
        verified_state_refs={"PCA":{"verified":True,"risk_state_id":state.risk_state_id}})
    return state,args


def test_pca_predeclared_whole_view_consumed_when_no_qqq_ff48(candidate,generated):
    module,_,_=candidate;state,args=generated
    out=module.consumer_projection({"PCA":state},"R3",**args)
    assert out["features"]["factor_view"]=="PCA_SHARED_WHOLE_STATE"
    np.testing.assert_array_equal(out["reference_covariance"],state.covariance)
    assert not out["account_qualified"] and not out["quote_authority_qualified"]
    before=CANDIDATE.with_name("R10_R3_PCA_CONSUMER_REPAIR_frozen_source.py.txt")
    assert hashlib.sha256(before.read_bytes()).hexdigest()==module.R3_REPAIR_OLD_ADAPTER_SHA
    baseline=types.ModuleType("scripts.research.a2.risk._review_before_pca_patch")
    baseline.__package__="scripts.research.a2.risk";baseline.__file__=frozen_adapter.__file__
    exec(compile(before.read_text(encoding="utf-8"),baseline.__file__,"exec"),baseline.__dict__)
    with pytest.raises(ValueError):baseline.consumer_projection({"PCA":state},"R3",**args)


def test_qualified_qqq_ff48_joint_view_always_priority_not_economic_value(candidate,generated):
    module,_,_=candidate;state,args=generated
    rb=replace(state,method="RB",risk_state_id="b"*64,qqq_relative_state={"beta":np.zeros(len(state.assets))})
    rh=replace(state,method="RH",risk_state_id="c"*64,qqq_relative_state={"pooled_specific_variance":np.ones(len(state.assets))})
    refs={m:{"verified":True,"risk_state_id":s.risk_state_id} for m,s in {"PCA":state,"RB":rb,"RH":rh}.items()}
    out=module.consumer_projection({"PCA":state,"RB":rb,"RH":rh},"R3",**{**args,"verified_state_refs":refs})
    assert out["features"]["factor_view"]=="QQQ_FF48_SHARED_WHOLE_STATES"


@pytest.mark.parametrize("defect",["PCA_missing","PCA_unqualified","PCA_ref1","PCA_future","PCA_wrongSID"])
def test_pca_invalid_has_no_unqualified_fallback(candidate,generated,defect):
    module,_,_=candidate;state,args=generated
    states={"PCA":state};args=copy.deepcopy(args)
    if defect=="PCA_missing":states={}
    elif defect=="PCA_unqualified":states["PCA"]=replace(state,status="BLOCKED")
    elif defect=="PCA_ref1":args["verified_state_refs"]["PCA"]["verified"]=1
    elif defect=="PCA_future":states["PCA"]=replace(state,as_of=state.as_of+__import__('pandas').Timedelta(days=1))
    elif defect=="PCA_wrongSID":args["uids"][state.assets[0]]="WRONG"
    with pytest.raises(ValueError,match="R3_PREDECLARED"):module.consumer_projection(states,"R3",**args)


def test_r7_other_groups_still_missing_failclosed(candidate,generated):
    module,_,_=candidate;state,args=generated
    with pytest.raises(ValueError):module.consumer_projection({"PCA":state},"R7",**args)


def spec(candidate):
    module,old,_=candidate
    return module._seal(dict(schema=module.STUDY_SCHEMA,code_pins=old,max_risk_learned_units=220,
        max_scheduled_learned_units=216,**{k:False for k in module.FLAGS},**{"2026_locked":True}))


def test_exact_single_adapter_repair_admission(candidate):
    module,old,new=candidate
    module._check_study_spec(spec(candidate),receipt(candidate))
    with pytest.raises(ValueError):module._check_study_spec(spec(candidate))
    mutated={**spec(candidate),"hard_cap":221}
    with pytest.raises(ValueError):module._check_study_spec(mutated,receipt(candidate))


@pytest.mark.parametrize("field,value",[("approved",1),("reviewed",None),("risk_fit_started_before_repair",False),
    ("risk_fit_started_before_repair",1),("human_request_sha256","wrong"),("parent_design_sha256","wrong"),
    ("new_adapter_sha256","wrong"),("old_adapter_sha256","wrong"),("budget_changed",True),
    ("scientific_target_changed",True),("source_authority_activated",True),("2026_locked",1)])
def test_repair_receipt_every_bound_field_failclosed(candidate,field,value):
    module,_,_=candidate;r=receipt(candidate);r[field]=value
    with pytest.raises(ValueError):module._check_study_spec(spec(candidate),r)


def test_other_owner_pin_change_never_whitelisted(candidate):
    module,old,new=candidate
    keys=[k for k in old if k!=str(Path(module.__file__))]
    wrong=copy.deepcopy(new);wrong[keys[0]]="d"*64
    original=module.code_pins;module.code_pins=lambda:wrong
    try:
        with pytest.raises(ValueError):module._check_study_spec(spec(candidate),receipt(candidate))
    finally:module.code_pins=original



def test_actual_producer_pca_selection_r3_and_strict_r7_integration(candidate,monkeypatch):
    module,old,new=candidate
    path=Path(__file__).with_name("test_shared_risk_engine_r2.py")
    loader=importlib.util.spec_from_file_location("pca_review_whole_shared_fixture",path)
    fixture=importlib.util.module_from_spec(loader);loader.loader.exec_module(fixture)
    inputs,asof=fixture.synthetic_input()
    proof=inputs.observations.loc[inputs.observations.horizon.eq(5),["asset","origin_at"]].copy();proof["qualified"]=True
    ack=lambda e:dict(ack=True,plan_sha256=e["plan_sha256"],reserved_units=e["required_units"],reservation_id="GENERATED_PCA_REPAIR")
    original=module._shared_produce
    def without_qqq_factor_views(*args,**kwargs):
        result=original(*args,**kwargs)
        # Retain actual old shared-engine tail/regime/uncertainty states; make only
        # the factor source views unavailable to exercise the prespecified PCA.
        result["states"]={k:v for k,v in result["states"].items() if k not in {"RB","RH"}}
        return result
    monkeypatch.setattr(module,"_shared_produce",without_qqq_factor_views)
    study_spec=module._seal(dict(schema=module.STUDY_SCHEMA,years=[2025],code_pins=old,
        max_risk_learned_units=220,max_scheduled_learned_units=216,shared_direction_max_units_per_year=36,
        representations=["R3","R7"],shared_domain_priority=[],**{k:False for k in module.FLAGS},**{"2026_locked":True}))
    request=dict(date="2025-01-01",decision_at=asof,assets=inputs.assets,uids=inputs.asset_uids,
        reference_assets=inputs.assets,horizon=5,cohort="GENERATED_ONLY")
    out=module.produce_study_risk(None,{"risk_study_spec":study_spec},reserve_callback=ack,on_component_start=lambda e:{"ack":True},
        synthetic_inputs={(2025,5,"PRIMITIVE"):(inputs,proof,asof)},projection_requests=[request],engineering_repair_receipt=receipt(candidate))
    assert any(s.method=="PCA" for s in out["states"])
    views={p["representation"]:p for p in out["projections"]}
    assert set(views)=={"R3","R7"},out["coverage"]
    assert views["R3"]["projection"]["features"]["factor_view"]=="PCA_SHARED_WHOLE_STATE"
    assert views["R7"]["projection"]["features"]["group_features"]["R3"]["factor_view"]=="PCA_SHARED_WHOLE_STATE"
    assert "PCA" in views["R3"]["state_refs"]
    assert not any("p_high_vol" in k for k in views["R7"]["projection"]["features"]["group_features"]["R5"])


def test_no_import_receipt_io_and_single_real_lazy_receipt_path(candidate):
    module,_,_=candidate
    import inspect
    source=CANDIDATE.read_text(encoding="utf-8")
    assert source.index("receipt_path=Path(")>source.index("def produce_study_risk(")
    assert "engineering_repair_receipt is None and synthetic_inputs is None" in source
    assert "if receipt_path.stat().st_size>65536" in source
