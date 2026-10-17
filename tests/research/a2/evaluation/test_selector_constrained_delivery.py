"""Synthetic C13 report/terminal receipt tests; no Raw, models, labels or outcomes."""
from copy import deepcopy
from pathlib import Path
import hashlib,json,re
import pytest
from scripts.research.a2.evaluation import selector_constrained_delivery as d
from scripts.research.a2.evaluation import selector_constrained_evidence as ev


def design():
    return dict(research_id=ev.RESEARCH_ID,official_freeze=True,formal_freeze_applied=True,roles=list(ev.ROLES),active_roles=list(ev.ACTIVE_ROLES),
        target=ev.TARGET,primary_eval_years=list(ev.YEARS),mechanism_research_eligible=True,strict_PIT_promotion_eligible=False,
        test2026_locked=True,new2026_estimation_authorized=False,evaluation=dict(common_mature_date_count=732,original_calendar_dates=752,
        year_counts=ev.YEAR_COUNTS,legacy_numeric=147,legacy_exposure=178,legacy_failed=31,exposure_namespace=226,new_numeric=0,
        partial_only=True,risk_efficiency_support_requires_full732=True,primary='MEAN_REPLACEMENT_EDGE',
        bootstrap=dict(draws=5000,block=20,seed=20260928,method=ev.BOOT_METHOD)))


def evidence():
    return dict(status=d.STATUS,numeric_complete_series=147,new_numeric_complete_series=0,exposure_namespace=226,supported=[],
        complete_common_732_candidates=[],strict_PIT_promotion_eligible=False,test2026_locked=True,risk_efficiency_supported=[],
        fit2026_rows=0,evaluation2026_rows=0,outcome2026_reads=0,new2026_state_estimations=0,
        tests=[dict(candidate_id=cid,supported=False,pooled_edge=None,simultaneous_lower_95=None) for cid in ev.ROLES],
        bootstrap=dict(exact_legacy_maxT_reuse=True,new_bootstrap_draws=0,numeric_complete_series=147,exposure_namespace=226,
        repeats=5000,block_sessions=20,seed=20260928,critical_max_t=3.2))


def terminal():
    names=['DESIGN_FREEZE.json','FORMAL_FREEZE_REVIEW.json','FIT_LEDGER.json','SOLVE_LEDGER.json','SCORE_ASSEMBLY.json',
        'FINAL_DECISIONS_FREEZE.json','SELECTION_EVIDENCE.json','ROLE_DESCRIPTIVE_SUMMARY.json']
    b={name:dict(path='D:/synthetic_c13/'+name,sha256=hashlib.sha256(name.encode()).hexdigest()) for name in names}
    f=dict(status='PASS',decision_frozen=True,all_decisions_terminal=True,outcome_reads_before_gate=0,research_id=ev.RESEARCH_ID,
        design_sha256=b['DESIGN_FREEZE.json']['sha256'],review_sha256=b['FORMAL_FREEZE_REVIEW.json']['sha256'],
        fit_ledger_ref=b['FIT_LEDGER.json'],solve_ledger_ref=b['SOLVE_LEDGER.json'],score_assembly_ref=b['SCORE_ASSEMBLY.json'])
    x=dict(status=d.STATUS,design=b['DESIGN_FREEZE.json'],final_gate=b['FINAL_DECISIONS_FREEZE.json'],ledger=b['SOLVE_LEDGER.json'],
        assembly=b['SCORE_ASSEMBLY.json'],evaluation=b['SELECTION_EVIDENCE.json'],summary=b['ROLE_DESCRIPTIVE_SUMMARY.json'],
        strict_PIT_promotion_eligible=False,read2026=0,fit2026=0,state2026=0,evaluation2026=0)
    return design(),evidence(),f,x,b


def summary(edge=1.,pred=.9,real=.8):
    return dict(candidate_id=ev.ACTIVE_ROLES[0],applicable_dates=115,common_mature_dates=115,mean_edge_bp=edge,
        edge_by_year_bp={'2023':edge,'2024':edge,'2025':edge},mean_predicted_variance_ratio=pred,
        mean_raw_overlap=18.,mean_replacements=2.,mean_raw_rank_sacrifice=3.,selector_supported=False,risk_efficiency_supported=False,
        realized_summary=[dict(year='POOLED',valid_h5_dates=100,selected=dict(std_ddof1=real,downside_uncentered=.4,cvar_loss_q05=.2),
        raw=dict(std_ddof1=1.,downside_uncentered=.5,cvar_loss_q05=.3))])


def test_all_thirty_answers_all_roles_and_null_not_statistical_rejection():
    text=d.render_report(design(),dict(rows=313668,dates=752,state_refs=[],families={}),
        dict(fit=dict(new_backend_fit_calls=0),solve=dict(actual_solver_calls=10,charged_reservations=12)),
        {},evidence(),[],{},dict(status='PASS'),{})
    assert re.findall(r'^([0-9]+)\. \*\*',text,re.M)==[str(i) for i in range(1,31)]
    assert all(cid in text for cid in ev.ROLES)
    assert 'null（不能判定）' in text
    assert '不能将不完整实验解释成统计负结论' in text
    assert 'C6A=BLOCKED_INPUT' in text and 'C8=BLOCKED_DEPENDENCY' in text and 'C11-B=BLOCKED_SHARED_RISK' in text
    assert 'unique CUSIP=None' in text


def test_predicted_and_realized_frontiers_use_distinct_given_coordinates():
    r=summary()
    assert d.frontier_points([r])[0][1]==pytest.approx(-.1)
    assert d.frontier_points([r],True)[0][1]==pytest.approx(-.2)
    r['mean_predicted_variance_ratio']=None
    assert d.frontier_points([r])==[] and len(d.frontier_points([r],True))==1


@pytest.mark.parametrize('value',[None,'missing',float('nan'),float('inf'),True])
def test_unknown_fields_never_make_fake_zero(value):
    assert d.number(value) is None
    r=summary(edge=value)
    assert d.frontier_points([r])==[]


def test_exact_count_separates_charge_from_actual_and_unknown():
    assert d.actual_count(dict(new_backend_fit_calls=0))==0
    assert d.actual_count({},'actual_solver_calls') is None
    assert d.actual_count(dict(actual_solver_calls=10,charged_reservations=12),'actual_solver_calls')==10
    assert d.actual_count(dict(events=[dict(backend_entered=True),dict(backend_entered=False)]),'actual_solver_calls')==1
    assert d.actual_count(dict(events=[dict(status='SUCCEEDED'),dict(status='FAILED')]),'actual_solver_calls') is None


def test_short_history_unique_uid_vs_refresh_pairs_and_overlap_proxy():
    s=dict(record=dict(method='SHR_HP',as_of='2023-01-03T21:00:00+00:00',asset_uids={'A':'037833100','B':'009066101'}),
        nominal_n={'A':16,'B':40},overlap_n_div5_proxy={'A':3,'B':8})
    t=deepcopy(s);t['record']['as_of']='2023-04-03T20:00:00+00:00'
    out=d.short_history(dict(state_refs=[s,t]))
    assert out['unique_uids']==1 and out['state_asset_pairs']==2
    assert out['refreshes'][0]['min_n_div5_proxy']==3


def test_terminal_true_partial_exact_pins_pass():
    d.validate_terminal(*terminal())


@pytest.mark.parametrize('change',['pre_gate_read','unfrozen','terminal','design','review','fit','solve','assembly','primary','expo','support','test2026','strict','realized_support','missing_role','fake_zero','new_draws','new_numeric'])
def test_terminal_rejects_drift_and_promotion(change):
    dd,e,f,x,b=terminal()
    if change=='pre_gate_read': f['outcome_reads_before_gate']=1
    if change=='unfrozen': f['decision_frozen']=False
    if change=='terminal': f['all_decisions_terminal']=False
    if change=='design': f['design_sha256']='f'*64
    if change=='review': f['review_sha256']='f'*64
    if change in ('fit','solve','assembly'):
        key={'fit':'fit_ledger_ref','solve':'solve_ledger_ref','assembly':'score_assembly_ref'}[change]
        f[key]={**f[key],'sha256':'f'*64}
    if change=='primary': e['complete_common_732_candidates']=[ev.ACTIVE_ROLES[0]]
    if change=='expo': e['exposure_namespace']=225
    if change=='support': e['supported']=[ev.ACTIVE_ROLES[0]]
    if change=='test2026': x['read2026']=1
    if change=='strict': e['strict_PIT_promotion_eligible']=True
    if change=='realized_support': e['risk_efficiency_supported']=[ev.ACTIVE_ROLES[0]]
    if change=='missing_role': e['tests'].pop()
    if change=='fake_zero': e['tests'][0]['pooled_edge']=0.
    if change=='new_draws': e['bootstrap']['new_bootstrap_draws']=1
    if change=='new_numeric': e['new_numeric_complete_series']=1
    with pytest.raises(ValueError):d.validate_terminal(dd,e,f,x,b)


def test_png_is_descriptive_and_not_generated_for_no_points(tmp_path):
    empty=tmp_path/'empty.png';assert d.frontier_chart([],empty) is None and not empty.exists()
    p=tmp_path/'actual.png';out=d.frontier_chart(d.frontier_points([summary()],True),p,True)
    assert p.read_bytes().startswith(b'\x89PNG') and out['coordinate']=='REALIZED_H5_STD'
    assert out['descriptive_only'] is True


def test_delivery_source_has_no_raw_matrix_label_reader_or_new_evaluator():
    import ast
    tree=ast.parse(Path(d.__file__).read_text(encoding='utf-8'))
    calls=[ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)]
    assert not any(x in calls for x in ('pd.read_parquet','pq.read_table','joblib.load','pre2026','fit','produce','reuse_statistics','shared_max_t'))
    assert d.delivery is d.run

def test_strict_cvar_field_and_separate_deterministic_bootstrap_counts():
    r=summary();z=r['realized_summary'][0]
    z['selected']['cvar_loss_alpha95']=.123
    z['selected']['cvar_loss_q05']=.777
    z['raw']['cvar_loss_alpha95']=.234
    z['raw']['cvar_loss_q05']=.888
    text=d.render_report(design(),dict(state_refs=[],families={}),
        dict(fit=dict(new_backend_fit_calls=0),solve=dict(actual_solver_calls=10,membership_deterministic_transform_calls=8,bootstrap_estimations=0)),
        {},evidence(),[r],{},dict(status='PASS'),{})
    assert '| 0.123000 | 0.234000 |' in text
    assert '0.777000' not in text and '0.888000' not in text
    assert 'cvar_loss_q05/q05/exceedance' in text
    assert 'membership deterministic transform calls=8' in text
    assert 'bootstrap estimations=0' in text