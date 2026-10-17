import dataclasses
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.risk import joint_method_space_risk_r6 as r
from scripts.research.a2.risk.shared_risk_budget_r2 import StateBudget, StateCache, StateBudgetError


def inputs(n=180,p=12):
    rng=np.random.default_rng(62026); dates=pd.date_range("2024-01-02",periods=n,freq="B",tz="UTC")
    market=pd.Series(rng.normal(0,.009,n),index=dates,name="SYNTHETIC_QQQ")
    raw=market.to_numpy()[:,None]*np.linspace(.06,.14,p)[None,:]+rng.normal(0,.006,(n,p))
    assets=["SYN_"+str(j) for j in range(p)]
    return r.RiskInputs(pd.DataFrame(raw,index=dates,columns=assets),"2025-01-01T00:00:00Z","2025-01-02T00:00:00Z",
        dict(zip(assets,["UID_"+str(j) for j in range(p)])),"a"*64,dates[-1],market,
        identity_epochs={a:"E1" for a in assets})


def cache(i,limit=2500):
    b=StateBudget(limit)
    return b,StateCache(b,source_identity="SYNTHETIC_R6",cutoff=i.cutoff,assets=tuple(i.returns.columns),
        return_coordinate="shareholder_value_open_return",horizon=5,identity_epoch=i.identity_epochs)


@pytest.mark.parametrize("method",[m for m in r.METHODS if m not in {"NONLINEAR","EVT"}])
def test_actual_recipes_have_legal_distinct_representations(method):
    i=inputs();b,c=cache(i); result=r.compute_risk(method,i,learn=c.learn)
    assert result.method.startswith("R6::") and result.status=="PASS_SYNTHETIC"
    assert result.assets==tuple(i.returns.columns)
    assert b.learned_total<=r.LEARNED_UPPER[method]
    if method=="EMPIRICAL_CVAR":
        assert result.covariance is None and result.representation=="TAIL_SCENARIOS"
        assert result.scenarios.equals(i.returns)
    else:
        assert result.covariance.shape==(12,12)
        assert np.linalg.eigvalsh(result.covariance).min()>0
        assert result.notes["quote_qualified"] is False


def test_shared_actual_callback_union_is_exact_not_matrix_dimension():
    i=inputs();b,c=cache(i)
    for method in r.METHODS:
        if method in {"NONLINEAR","EVT"}:continue
        r.compute_risk(method,i,learn=c.learn)
    # EVT qualification, if pre-frozen, adds threshold+one pooled GPD call.
    assert b.learned_total==29
    assert len({e["key"] for e in b.events})==len(b.events)
    assert all(e["status"]=="SUCCEEDED" for e in b.events)
    assert sum(e["name"]=="r6:market_mean" for e in b.events)==1
    assert sum(e["name"]=="r6:pca" for e in b.events)==1
    before=b.learned_total
    r.compute_risk("AVERAGE",i,learn=c.learn)
    assert b.learned_total==before


def test_nonlinear_has_no_substitute_or_reservation():
    i=inputs();b,c=cache(i)
    with pytest.raises(r.RiskInputBlocked,match="GENUINE_NONLINEAR"):
        r.compute_risk("NONLINEAR",i,learn=c.learn)
    assert b.learned_total==0


def test_evt_requires_explicit_qualified_profile_before_any_fit():
    i=inputs();b,c=cache(i)
    with pytest.raises(r.RiskInputBlocked,match="QUALIFIED_POOLED_TAIL"):
        r.compute_risk("EVT",i,learn=c.learn)
    assert b.learned_total==0


def test_qualified_evt_is_one_pooled_fit_not_asset_count():
    i=dataclasses.replace(inputs(),tail_source_qualified=True);b,c=cache(i)
    result=r.compute_risk("EVT",i,learn=c.learn)
    assert b.learned_total==3 and result.notes["backend_calls"]==1
    assert result.covariance is None and result.tail_state["coverage_certified"] is False


@pytest.mark.parametrize("change",[
    dict(cutoff="2025-12-31T23:30:00-05:00",as_of="2025-12-31T23:45:00-05:00"),
    dict(cutoff="2025-01-01"),dict(mature_max="2025-01-01T00:00Z"),
    dict(source_sha256="not-a-hash"),dict(asset_uids={}),
])
def test_clock_uid_source_failure_is_before_estimation(change):
    i=dataclasses.replace(inputs(),**change);calls=[]
    with pytest.raises(r.RiskInputBlocked):r.compute_risk("HUBER",i,learn=lambda *a:calls.append(a))
    assert calls==[]


def test_classical_incomplete_domain_never_silently_drops_asset():
    i=inputs();f=i.returns.copy();f.iloc[:170,-1]=np.nan;i=dataclasses.replace(i,returns=f)
    b,c=cache(i)
    with pytest.raises(r.RiskInputBlocked,match="COMPLETE_CLASSICAL"):
        r.compute_risk("HUBER",i,learn=c.learn)
    assert b.learned_total==0


def test_known_n0_posterior_and_explicit_completion_preserve_full_pool():
    i=inputs();f=i.returns.copy();f.iloc[:,-1]=np.nan;i=dataclasses.replace(i,returns=f)
    b,c=cache(i);prior=r.compute_risk("POSTERIOR_PREDICTIVE",i,learn=c.learn)
    assert np.isfinite(prior.covariance).all() and prior.assets==tuple(f.columns)
    completed=r.compute_risk("HUBER",i,learn=c.learn,prior_covariance=prior.covariance)
    assert completed.covariance.shape==prior.covariance.shape
    assert "R6_CLASSICAL" in completed.notes["completion"]["scientific_method"]
    assert completed.notes["completion"]["observations_fabricated"] is False
    assert completed.notes["completion"]["prior_only_positions"]==[11]


@pytest.mark.parametrize("method",["EMPIRICAL_CVAR","SEMIVARIANCE","EVT"])
def test_prior_covariance_cannot_fabricate_joint_tail_scenarios(method):
    i=inputs();f=i.returns.copy();f.iloc[:,-1]=np.nan;i=dataclasses.replace(i,returns=f,tail_source_qualified=True)
    with pytest.raises(r.RiskInputBlocked,match="COMPLETE_CLASSICAL"):
        r.compute_risk(method,i,prior_covariance=np.eye(12))


def test_posterior_views_share_fits_but_have_distinct_uncertainty_semantics():
    i=inputs();b,c=cache(i)
    hierarchy=r.compute_risk("HIER_POSTERIOR",i,learn=c.learn)
    assert b.learned_total==7
    predictive=r.compute_risk("POSTERIOR_PREDICTIVE",i,learn=c.learn)
    assert b.learned_total==7
    assert np.all(np.diag(predictive.covariance)>np.diag(hierarchy.covariance))
    r.compute_risk("BAYES_FACTOR",i,learn=c.learn)
    assert b.learned_total==8


def test_failed_fixed_recipe_is_reserved_and_cannot_retry(monkeypatch):
    i=inputs();b,c=cache(i)
    def failure(*a,**k):raise RuntimeError("fixed numerical failure")
    monkeypatch.setattr(r.GraphicalLasso,"fit",failure)
    with pytest.raises(RuntimeError):r.compute_risk("GRAPHICAL",i,learn=c.learn)
    assert b.learned_total==2 and b.events[-1]["status"]=="FAILED"
    with pytest.raises(StateBudgetError,match="FAILED"):
        r.compute_risk("GRAPHICAL",i,learn=c.learn)
    assert b.learned_total==2


def test_budget_refuses_next_state_before_backend(monkeypatch):
    i=inputs();b,c=cache(i,limit=1);calls=[]
    monkeypatch.setattr(r.GraphicalLasso,"fit",lambda *a:calls.append(1))
    with pytest.raises(StateBudgetError,match="CAP_EXCEEDED"):
        r.compute_risk("GRAPHICAL",i,learn=c.learn)
    assert b.learned_total==1 and calls==[]


def test_robust_and_dynamic_are_not_static_pca_aliases():
    i=inputs();f=i.returns.copy();f.iloc[-1,0]*=20;i=dataclasses.replace(i,returns=f)
    dynamic=r.compute_risk("DYNAMIC_FACTOR",i).covariance
    robust=r.compute_risk("ROBUST_FACTOR",i).covariance
    assert not np.allclose(dynamic,robust,rtol=1e-3,atol=1e-10)


def test_real_mode_is_not_activated_by_math_module():
    i=dataclasses.replace(inputs(),synthetic=False)
    with pytest.raises(r.RiskInputBlocked,match="RESERVATION_CALLBACK"):
        r.compute_risk("HUBER",i)


def test_no_extra_parameters_or_dependency_installation_claim():
    spec=r.specification()
    assert len(spec["methods"])==16 and spec["parameters"]["scientific_retry"]==0
    assert spec["source_readiness"]=="UNKNOWN_UNTIL_R6_METADATA_DISCOVERY"
    assert len(r.code_pins())==3


def test_fully_qualified_synthetic_union_is_31_actual_reserved_operations():
    i=dataclasses.replace(inputs(),tail_source_qualified=True);b,c=cache(i)
    for m in r.METHODS:
        if m!="NONLINEAR":r.compute_risk(m,i,learn=c.learn)
    assert b.learned_total==31
    assert {e["name"][3:] for e in b.events if e["kind"]!="deterministic_transform"}==set(o for m in r.METHODS for o in r.OPERATIONS[m])
    assert all(e["status"]=="SUCCEEDED" for e in b.events)
    assert b.counts["scaler"]==2 and b.counts["covariance"]==28 and b.counts["regime_threshold"]==1
    proof=r.learned_union_upper(55)
    assert proof["total"]==1705 and proof["per_exact_common_event"]==31


def test_joint_posterior_systems_are_reported_separately_from_state_units():
    i=inputs();b,c=cache(i);result=r.compute_risk("POSTERIOR_PREDICTIVE",i,learn=c.learn)
    assert b.learned_total==7 and result.notes["coefficient_systems"]==24
    assert result.notes["backend_calls"]==1
    binding=r.recipe_dag()["posterior_joint_model"]
    assert binding["common_factor"] and binding["conditional_independence_given_factor"]
    assert not binding["per_asset_capacity_seed_optimizer"]


def test_prior_rms_is_exact_view_of_shared_qqq_states_not_new_fit():
    i=inputs();q=i.market.to_numpy();mean=q.mean();cov=np.array([[np.mean((q-mean)**2)]])
    assert np.isclose(r.prior_scale_from_market_states(mean,cov),np.sqrt(np.mean(q*q)))


def test_typed_prior_uid_or_epoch_swap_blocks_before_completion():
    i=inputs();b,c=cache(i);prior=r.compute_risk("POSTERIOR_PREDICTIVE",i,learn=c.learn)
    f=i.returns.copy();f.iloc[:,-1]=np.nan
    wrong=dataclasses.replace(prior,assets=tuple(reversed(prior.assets)))
    with pytest.raises(r.RiskInputBlocked,match="EXACT_PRIOR_SOURCE"):
        r.compute_risk("HUBER",dataclasses.replace(i,returns=f),learn=c.learn,prior_covariance=wrong)


def test_typed_prior_full_domain_preserved_for_ensemble_completion():
    i=inputs();f=i.returns.copy();f.iloc[:,-1]=np.nan;i=dataclasses.replace(i,returns=f)
    b,c=cache(i);prior=r.compute_risk("POSTERIOR_PREDICTIVE",i,learn=c.learn)
    result=r.compute_risk("AVERAGE",i,learn=c.learn,prior_covariance=prior)
    assert result.assets==tuple(f.columns) and result.covariance.shape==(12,12)


def test_metadata_known_donor_gap_stops_all_fits():
    i=inputs(n=35);b,c=cache(i)
    with pytest.raises(r.RiskInputBlocked,match="QUALIFIED_DONOR"):
        r.compute_risk("POSTERIOR_PREDICTIVE",i,learn=c.learn)
    assert b.learned_total==0


def test_graphical_recipe_is_fixed_mathematical_normalization_not_old_retry():
    s=r.specification();g=s["primitive_dag"]["graphical"]
    assert g["old_alpha"]==.01 and g["old_failures_preserved"] and not g["grid"]
    assert "sqrt(log(max(p,2))/(n/5))" in g["new_alpha"]


def test_identity_epoch_or_boolean_mode_ambiguity_blocks():
    for change in (dict(identity_epochs={}),dict(synthetic=1),dict(asset_uids={**inputs().asset_uids,"SYN_0":" unknown "})):
        with pytest.raises(r.RiskInputBlocked):r.compute_risk("HUBER",dataclasses.replace(inputs(),**change))

@pytest.mark.parametrize("method",["EMPIRICAL_CVAR","EVT"])
def test_actual_tail_scenarios_keep_same_full_source_uid_epoch_clock_binding(method):
    i=dataclasses.replace(inputs(),tail_source_qualified=True)
    result=r.compute_risk(method,i)
    assert all(result.notes[k]==v for k,v in r.source_notes(i).items())
    assert result.covariance is None and result.notes["covariance_proxy"] is False
    assert result.scenarios.equals(i.returns)


def test_completion_notes_bind_original_full_domain_not_classical_subset():
    i=inputs();f=i.returns.copy();f.iloc[:,-1]=np.nan;i=dataclasses.replace(i,returns=f)
    b,c=cache(i);prior=r.compute_risk("POSTERIOR_PREDICTIVE",i,learn=c.learn)
    result=r.compute_risk("HUBER",i,learn=c.learn,prior_covariance=prior)
    assert result.notes["asset_uids"]==i.asset_uids
    assert result.notes["identity_epochs"]==i.identity_epochs


# Focused execution-boundary checks use only pre-existing synthetic transport.
from scripts.research.a2.evaluation import joint_method_space_risk_execution_r6 as ex
import copy
import importlib.util
from pathlib import Path

def execution_fixture():
    path=ex.old.REPO/'tests/research/a2/evaluation/test_joint_event_risk_execution_r5.py'
    spec=importlib.util.spec_from_file_location('synthetic_r5_transport_fixture',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    f=module.fixture();features=f['features'];event=f['event'];event['event_id']='a'*64
    identity=features[['ticker','signal_date','security_id']].rename(columns={'security_id':'security_uid'})
    identity['asset_epoch']=[event['asset_epochs'][a] if d>=pd.Timestamp(event['segment_starts'][a]) else 'OLD_EPOCH'
        for a,d in identity[['ticker','signal_date']].itertuples(index=False,name=None)]
    identity['segment_start']=identity.ticker.map(event['segment_starts'])
    identity['identity_qualified']=True;identity['source_qualified']=True
    identity['class_coordinate_status']='EXACT_FROZEN_INTERVAL_COORDINATE_FOR_MECHANISM';identity['is_current_pool']=True
    return {k:f[k] for k in ('labels','base_uids','qqq','source','science','days','event')}|dict(identity=identity)

class SyntheticLedger:
    def __init__(self):self.status=dict(physical_events=[]);self.deterministic_counts={}
    def reserve(self,kind,node_id,units,physical_kind):
        assert not any(r['node_id']==node_id for r in self.status['physical_events'])
        self.status['physical_events'].append(dict(node_id=node_id,kind=kind,units=units,physical_kind=physical_kind,status='STARTED'))
    def complete(self,node_id,**details):
        next(r for r in self.status['physical_events'] if r['node_id']==node_id).update(status='COMPLETE',details=copy.deepcopy(details))
    def fail(self,node_id,**details):
        next(r for r in self.status['physical_events'] if r['node_id']==node_id).update(status='FAILED_NONREFUNDABLE',details=copy.deepcopy(details))
    def deterministic(self,k,n):self.deterministic_counts[k]=self.deterministic_counts.get(k,0)+n

def test_r6_transport_meta_retains_known_n0_without_creating_values():
    args=execution_fixture();typed,s,d=ex.assemble_context(**args)
    assert typed.assets==tuple('ABCDEZ') and s['nominal_n']['Z']==0
    assert not typed.observations.asset.eq('Z').any() and typed.observations.return_value.isna().all()
    assert s['parent_origin_window_sha256'] and s['QQQ_full_window_support']
    assert len(s['classical_complete_cohort'])==5 and d['inference_support']['Z'] is False
    q=ex.method_qualification(s)
    assert q['HUBER']['status']=='METADATA_QUALIFIED_NUMERIC_FINITE_UNKNOWN'
    assert q['POSTERIOR_PREDICTIVE']['status']=='METADATA_QUALIFIED_NUMERIC_FINITE_UNKNOWN'
    assert q['EMPIRICAL_CVAR']['status']=='BLOCKED_SOURCE_OR_INPUT'
    assert q['EVT']['status']=='BLOCKED_SOURCE_OR_INPUT'

@pytest.mark.parametrize('change',['unknown','extra','epoch','future','source'])
def test_r6_current_identity_gate_never_shrinks_or_carries(change):
    a=execution_fixture();rows=a['identity'];last=rows.index[-1]
    if change=='unknown':rows.loc[last,'identity_qualified']=False
    elif change=='extra':
        new=rows.iloc[-1].copy();new.ticker='NEW';a['identity']=pd.concat([rows,pd.DataFrame([new])],ignore_index=True)
    elif change=='epoch':rows.loc[last,'asset_epoch']='DIFFERENT'
    elif change=='future':rows.loc[last,'signal_date']+=pd.Timedelta(days=3)
    else:rows.loc[last,'source_qualified']=False
    with pytest.raises(ex.Blocked):ex.assemble_context(**a)

def test_r6_metadata_refuses_value_columns_before_assembler():
    a=execution_fixture();a['labels']['y_open5']=object()
    with pytest.raises(ex.Blocked,match='VALUE_PROJECTION'):ex.assemble_context(**a)

def test_r6_numeric_loader_denial_is_before_any_body_or_reader(monkeypatch):
    calls=[]
    def denied(*a):raise ex.Blocked('REGISTRATION_PENDING')
    monkeypatch.setattr(ex.runtime,'guard_numeric',denied)
    monkeypatch.setattr(ex.old,'ProjectedReader',lambda *a,**k:calls.append(1))
    with pytest.raises(ex.Blocked,match='PENDING'):ex.InputLoader('x',{},'x',{},freeze_sha='a'*64)
    assert calls==[]

def test_r6_loader_value_projection_requires_activation_even_with_injected_reader():
    loader=object.__new__(ex.InputLoader);loader.authorised=False
    with pytest.raises(ex.Blocked,match='ADMISSION'):loader.load({},numeric=True)

def test_r6_original_numeric_panel_preserves_full_axes_and_cold_nan():
    a=execution_fixture();rng=np.random.default_rng(4);a['labels']['y_open5']=rng.normal(0,.01,len(a['labels']))
    a['qqq']['open']=100*np.exp(np.arange(len(a['qqq']))*.0001)
    typed,s,_=ex.assemble_context(**a,numeric=True);i=ex.mathematical_inputs(typed,s)
    assert list(i.returns.columns)==list('ABCDEZ') and i.returns['Z'].isna().all()
    assert i.synthetic is False and i.market.notna().all()
    assert i.mature_max<i.cutoff and not i.tail_source_qualified
    r.validate_inputs(i)

def test_r6_31_unique_reservations_and_recovery_reuse_without_backend():
    i=dataclasses.replace(inputs(),tail_source_qualified=True);ledger=SyntheticLedger();op=ex.RiskOperations(ledger,'synthetic',persist=False)
    s=dict(risk_support_identity='a'*64);op.bind(i,s)
    for m in r.METHODS:
        if m!='NONLINEAR':r.compute_risk(m,i,learn=op.learn)
    assert op.budget.learned_total==31 and sum(row['units'] for row in ledger.status['physical_events'])==31
    before=len(ledger.status['physical_events']);recovered=ex.RiskOperations(ledger,'synthetic',persist=False);recovered.bind(i,s)
    again=r.compute_risk('AVERAGE',i,learn=recovered.learn)
    assert recovered.budget.learned_total==31 and len(ledger.status['physical_events'])==before
    assert again.notes['backend_calls']==0


def test_r6_failed_reservation_retained_blocks_retry_and_independent_recipe_continues(monkeypatch):
    i=inputs();ledger=SyntheticLedger();op=ex.RiskOperations(ledger,'synthetic',persist=False);op.bind(i,dict(risk_support_identity='a'*64))
    def fail(*a,**k):raise RuntimeError('FIXED_BACKEND_FAILED')
    monkeypatch.setattr(r.GraphicalLasso,'fit',fail)
    with pytest.raises(RuntimeError):r.compute_risk('GRAPHICAL',i,learn=op.learn)
    assert op.budget.learned_total==2 and ledger.status['physical_events'][-1]['status']=='FAILED_NONREFUNDABLE'
    recovered=ex.RiskOperations(ledger,'synthetic',persist=False);recovered.bind(i,dict(risk_support_identity='a'*64))
    with pytest.raises(StateBudgetError,match='NO_RETRY'):r.compute_risk('GRAPHICAL',i,learn=recovered.learn)
    r.compute_risk('HUBER',i,learn=recovered.learn)
    assert recovered.budget.learned_total==3


def test_r6_tail_aux_is_covariance_only_and_never_fabricates_scenarios():
    i=inputs();ledger=SyntheticLedger();op=ex.RiskOperations(ledger,'synthetic',persist=False)
    s=dict(risk_support_identity='a'*64,primary_source_sha256='b'*64)
    q={m:dict(status='METADATA_QUALIFIED_NUMERIC_FINITE_UNKNOWN',reason=None) for m in r.METHODS}
    q['NONLINEAR']=dict(status='BLOCKED_SOURCE_OR_INPUT',reason='dependency');q['EVT']=dict(status='BLOCKED_SOURCE_OR_INPUT',reason='source')
    result,rows=ex.execute_group(i,s,q,op)
    tail=result['EMPIRICAL_CVAR']
    assert tail.covariance is None and tail.scenarios.equals(i.returns)
    assert tail.notes['covariance_auxiliary_is_not_tail_scenarios'] is True
    assert tail.notes['risk_support_identity']=='a'*64
    assert len(rows)==16 and all(row['status']!='PENDING' for row in rows)


def test_r6_exact_source_value_projection_filters_before_body():
    import pyarrow as pa
    import pyarrow.dataset as ds
    a=execution_fixture();target=(a['labels'].ticker=='A')&(a['labels'].signal_date==a['days'][300])
    a['labels'].loc[target,'label_available']=False;a['event']['history_support']['nominal_n']['A']-=1
    typed,s,_=ex.assemble_context(**a)
    pool,_,_=ex.identity_pool(a['identity'],a['event'],a['days'])
    values=a['labels'].copy();values['y_open5']=.01
    dataset=ds.dataset(pa.Table.from_pandas(values,preserve_index=False));path=Path('synthetic_labels.parquet').resolve()
    class Reader:
        datasets={str(path):dataset};audit=[]
        _scalar=staticmethod(ex.old.ProjectedReader._scalar)
    out=ex.exact_mature_values(Reader,a['source']|dict(sources={'extended_shareholder_y5':dict(path=str(path))}),typed,
        dict(label_metadata=a['labels'],base_uid_metadata=a['base_uids'],identity_pool=pool),s,a['days'][-2])
    assert len(out)==sum(s['nominal_n'].values())
    assert not ((out.ticker=='A')&(out.signal_date==a['days'][300])).any()
    assert not out.ticker.eq('Z').any()
    assert Reader.audit[-1]['prebody_exact_uid_epoch_source_predicate']


def test_evt_only_full_genuine_joint_source_is_qualified_before_numeric():
    a=execution_fixture();_,s,_=ex.assemble_context(**a)
    assert ex.method_qualification(s)['EVT']['status']=='BLOCKED_SOURCE_OR_INPUT'
    full=dict(s,classical_complete_cohort=s['assets'],donors=s['assets'],QQQ_full_window_support=True)
    assert ex.method_qualification(full)['EVT']['status']=='METADATA_QUALIFIED_NUMERIC_FINITE_UNKNOWN'
    assert ex.method_qualification(dict(full,QQQ_full_window_support=False))['EVT']['status']=='BLOCKED_SOURCE_OR_INPUT'
    spec=r.specification()['evt_source_requirements']
    assert not spec['posterior_fabrication'] and not spec['pre_existing_binary_macro_state_claim']
    assert spec['fixed_parent_origins']==252


def test_numerical_nan_cannot_be_reinterpreted_as_fewer_qualified_metadata_rows():
    a=execution_fixture();a['labels']['y_open5']=.01;a['labels'].loc[a['labels'].ticker.eq('A'),'y_open5']=np.nan
    a['qqq']['open']=100*np.exp(np.arange(len(a['qqq']))*.0001)
    typed,s,_=ex.assemble_context(**a,numeric=True)
    with pytest.raises(ex.Blocked,match='NO_SILENT_N_DOWNGRADE'):ex.mathematical_inputs(typed,s)


def test_tail_and_completion_closure_contains_exact_shared_posterior_dependency():
    i=inputs();f=i.returns.copy();f.iloc[:,-1]=np.nan;i=dataclasses.replace(i,returns=f)
    ledger=SyntheticLedger();op=ex.RiskOperations(ledger,'synthetic',persist=False)
    s=dict(risk_support_identity='a'*64,primary_source_sha256='b'*64)
    q={m:dict(status='METADATA_QUALIFIED_NUMERIC_FINITE_UNKNOWN',reason=None) for m in r.METHODS}
    for m in ['NONLINEAR','EVT','EMPIRICAL_CVAR','SEMIVARIANCE']:q[m]=dict(status='BLOCKED_SOURCE_OR_INPUT',reason='source')
    _,rows=ex.execute_group(i,s,q,op);by={row['method']:row for row in rows}
    assert set(by['POSTERIOR_PREDICTIVE']['fit_dependency_ids']).issubset(by['HUBER']['fit_dependency_ids'])
    assert by['HUBER']['posterior_completion_or_auxiliary_dependency_ids']==by['POSTERIOR_PREDICTIVE']['fit_dependency_ids']


def test_source_only_31_component_registry_dependencies_are_complete():
    dag=r.recipe_dag();nodes=dag['operation_registry']
    assert len(nodes)==31
    assert sum(n['kind']=='scaler' for n in nodes.values())==2
    assert all(d[3:] in nodes for n in nodes.values() for d in n['dependencies'])
    assert nodes['market_mean']['dependencies']==[]
    assert 'r6:market_mean' in nodes['market_lw']['dependencies']
    assert not dag['FF48_dependency']



def test_original_source_research_id_is_retained_for_parent_receipt_eager_default(monkeypatch):
    # Source provenance remains original; the new scientific identity is explicit.
    a=execution_fixture();source=a['source']
    source.update(research_id='ORIGINAL_R3_SOURCE_PROVENANCE',schema='SYNTHETIC_ORIGINAL_SOURCE_METADATA',family_design_freeze_sha256='b'*64)
    run=Path('D:/us-tech-quant-backtests/V24/synthetic_r6')
    authority=dict(research_id=ex.ID,source_inputs_sha256=ex.SOURCE_SHA,
        source_inputs_ref=str(run/'source.json'),test2026_reads=0,
        EF_access=False,network_provider_fetch=False,R5_numeric_economic_read=False,
        quote_qualified=False,strict_PIT_promotion_eligible=False,certified_nav_qualified=False)
    class Paths:backtest_root=run.parent.parent
    monkeypatch.setattr(ex,'resolve',lambda *args:Paths())
    monkeypatch.setattr(ex,'assert_safe_output_path',lambda *args,**kwargs:None)
    monkeypatch.setattr(ex.old,'read_json',lambda p:authority)
    monkeypatch.setattr(ex.old,'_safe_source',lambda p:Path(p))
    monkeypatch.setattr(ex.old,'_pin',lambda *args:None)
    seen=[]
    def projection(path,keys):
        seen.append(set(keys))
        if path.name=='FAMILY_DESIGN_FREEZE.json':
            return dict(actual_snapshot_timestamp=a['science']['actual_snapshot_timestamp'])
        return {key:source[key] for key in keys}
    monkeypatch.setattr(ex,'_metadata_projection',projection)
    _,bound,_,snapshot=ex.source_binding(run)
    assert 'research_id' in seen[0]
    assert bound['research_id']=='ORIGINAL_R3_SOURCE_PROVENANCE'
    science=dict(scientific_contract_identity=ex.ID,
        scientific_contract_sha256='a'*64,actual_snapshot_timestamp=snapshot)
    receipt=ex.old._receipt(bound,science,pd.Timestamp(a['event']['fit_history_cutoff']),'current_epoch')
    assert receipt.scientific_contract_identity==ex.ID
    assert receipt.scientific_contract_sha256=='a'*64
    assert receipt.synthetic is False and receipt.mechanism is True
    assert ex.QUAL=='support/R6_RISK_METADATA_QUALIFICATION_R1.json'
