import copy
import pytest

from scripts.research.a2.evaluation.joint_mechanism_control_qualification_r3 import (
    analyze_control_qualification, ControlQualificationError, ANALYSIS_IDENTITY_SHA256,
)
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash


def inputs():
    bindings = dict(parent_control_result_sha256="a"*64, account_freeze_sha256="b"*64,
                    source_snapshot_sha256="c"*64)
    gap = dict(date="2025-01-02 00:00:00", ticker="LOCAL_DUMMY", reason="PRICE_QUALITY_UNCERTIFIED")
    q = dict(mechanism_accounting_consistent=False, raw_endpoints_finite=True,
             quality_source_only_or_clear=True, unresolved_economic_exception_count=0,
             execution_audit_pass=True, selection_input_complete=True, actual_execution_inputs_complete=False,
             selection_input_gaps=[], actual_execution_input_gaps=[gap], strict_PIT_promotion_eligible=False,
             certified_NAV=False, quote_qualified=False)
    original = {"DUMMY_RAW":copy.deepcopy(q), "DUMMY_EQUAL":copy.deepcopy(q)}
    audit = dict(cash_identity_error_max=0., cost_identity_error_max=0., self_finance_error_max=0.,
                 nav_identity_error_max=0., actual_cash_flow_identity_error_max=0., next_open_violations=0,
                 capacity_violations=0, max_actual_names=20, minimum_cash=0.)
    facts = [dict(path_id=path, date="2025-01-02", ticker="LOCAL_DUMMY", status="REJECTED",
                  reason="PRICE_QUALITY_UNCERTIFIED", raw_row_present=True, raw_open_positive_finite=True,
                  raw_close_positive_finite=True, signal_adv_positive_finite=True, actual_fill_count=0,
                  previous_held_position_count=0, current_held_position_count=0,
                  economic_coordinate_not_used=True, unsupported_events_preserved=True, **bindings) for path in original]
    kw = dict(**bindings, baseline_economic_consistent={path:True for path in original},
              baseline_daily_flags_sha256="d"*64)
    return original,audit,facts,kw


def test_declared_rejections_are_conditional_without_mutating_original_failure_or_source_flags():
    q,a,f,k=inputs(); before=copy.deepcopy((q,a,f,k))
    result=analyze_control_qualification(q,a,f,**k)
    assert (q,a,f,k)==before
    assert result["conditional_mechanism_eligible"] is True
    assert result["analysis_identity_sha256"]==ANALYSIS_IDENTITY_SHA256
    assert result["new_account_attempts"]==result["new_fit_units"]==0
    for path,v in result["qualification"].items():
        assert v["original_aggregate_mechanism_accounting_consistent"] is False
        assert len(v["declared_execution_constraints"])==1 and not v["blocking_conditions"]
        assert v["strict_PIT_promotion_eligible"] is v["certified_NAV"] is v["quote_qualified"] is False
    sha=result.pop("analysis_payload_sha256")
    assert sha==content_hash(result)


@pytest.mark.parametrize("field,value",[
    ("raw_row_present",False),("raw_open_positive_finite",False),("raw_close_positive_finite",False),
    ("signal_adv_positive_finite",False),("actual_fill_count",1),("previous_held_position_count",1),
    ("current_held_position_count",1),("economic_coordinate_not_used",False),
    ("unsupported_events_preserved",False),("actual_fill_count",False),("raw_row_present",1),
])
def test_true_execution_or_economic_dependencies_are_never_waived(field,value):
    q,a,f,k=inputs();f[0][field]=value
    r=analyze_control_qualification(q,a,f,**k)
    assert r["conditional_mechanism_eligible"] is False
    assert r["qualification"]["DUMMY_RAW"]["blocking_conditions"]


@pytest.mark.parametrize("field,value",[
    ("raw_endpoints_finite",False),("quality_source_only_or_clear",False),
    ("unresolved_economic_exception_count",1),("execution_audit_pass",False),
    ("selection_input_complete",False),("selection_input_gaps",[{"reason":"MISSING_SCORE"}]),
    ("quote_qualified",True),("strict_PIT_promotion_eligible",True),("certified_NAV",True),
])
def test_original_non_rejection_failures_and_source_promotion_still_block(field,value):
    q,a,f,k=inputs();q["DUMMY_RAW"][field]=value
    assert not analyze_control_qualification(q,a,f,**k)["conditional_mechanism_eligible"]


def test_baseline_daily_accounting_failure_not_hidden_by_zero_exception_count():
    q,a,f,k=inputs();k["baseline_economic_consistent"]["DUMMY_RAW"]=False
    assert not analyze_control_qualification(q,a,f,**k)["conditional_mechanism_eligible"]


@pytest.mark.parametrize("reason",["MISSING_PRICE_ROW","MISSING_OR_INVALID_OPEN","MISSING_SIGNAL_ADV","UNKNOWN_NAV"])
def test_other_execution_gaps_are_not_reclassified(reason):
    q,a,f,k=inputs();q["DUMMY_RAW"]["actual_execution_input_gaps"][0]["reason"]=reason;f=f[1:]
    assert not analyze_control_qualification(q,a,f,**k)["conditional_mechanism_eligible"]


@pytest.mark.parametrize("field,value",[("nav_identity_error_max",float("nan")),("capacity_violations",1),
    ("next_open_violations",1),("max_actual_names",21),("minimum_cash",-1.)])
def test_common_audit_failure_blocks_without_nav_or_return_access(field,value):
    q,a,f,k=inputs();a[field]=value
    assert not analyze_control_qualification(q,a,f,**k)["conditional_mechanism_eligible"]


def test_missing_fact_blocks_and_extra_duplicate_or_foreign_fact_cannot_create_eligibility():
    q,a,f,k=inputs()
    assert not analyze_control_qualification(q,a,f[1:],**k)["conditional_mechanism_eligible"]
    with pytest.raises(ControlQualificationError,match="DUPLICATE"):
        analyze_control_qualification(q,a,f+[f[0]],**k)
    f[0]["ticker"]="OTHER"
    with pytest.raises(ControlQualificationError,match="WITHOUT_ORIGINAL"):
        analyze_control_qualification(q,a,f,**k)
    f[0]["path_id"]="FOREIGN"
    with pytest.raises(ControlQualificationError,match="FOREIGN"):
        analyze_control_qualification(q,a,f,**k)


@pytest.mark.parametrize("field",["parent_control_result_sha256","account_freeze_sha256","source_snapshot_sha256"])
def test_every_rejection_fact_binds_same_original_source_and_control_freeze(field):
    q,a,f,k=inputs();f[0][field]="e"*64
    with pytest.raises(ControlQualificationError,match="PROVENANCE"):
        analyze_control_qualification(q,a,f,**k)


def test_no_hidden_economic_payload_or_2026_fact_is_accepted():
    q,a,f,k=inputs();f[0]["nav"]=3000
    with pytest.raises(ControlQualificationError,match="ONLY_DECLARED_METADATA"):
        analyze_control_qualification(q,a,f,**k)
    del f[0]["nav"];f[0]["date"]="2026-01-01"
    with pytest.raises(ControlQualificationError,match="PRE2026"):
        analyze_control_qualification(q,a,f,**k)


def test_baseline_requires_exact_paths_and_valid_projection_binding():
    q,a,f,k=inputs();k["baseline_economic_consistent"]={"DUMMY_RAW":True}
    with pytest.raises(ControlQualificationError,match="EXACT_BASELINE"):
        analyze_control_qualification(q,a,f,**k)
    q,a,f,k=inputs();k["baseline_daily_flags_sha256"]=""
    with pytest.raises(ControlQualificationError,match="SHA256"):
        analyze_control_qualification(q,a,f,**k)


def test_original_metadata_cannot_hide_nav_or_return_payloads():
    q,a,f,k=inputs();q["DUMMY_RAW"]["nav"]=3000
    with pytest.raises(ControlQualificationError,match="ONLY_ORIGINAL_QUALIFICATION_METADATA"):
        analyze_control_qualification(q,a,f,**k)
    del q["DUMMY_RAW"]["nav"];q["DUMMY_RAW"]["actual_execution_input_gaps"][0]["return"]=.1
    with pytest.raises(ControlQualificationError,match="ONLY_ORIGINAL_GAP_METADATA"):
        analyze_control_qualification(q,a,f,**k)
