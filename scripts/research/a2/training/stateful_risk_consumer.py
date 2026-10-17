"""Frozen R11A1 thin consumer. No bank reader, covariance estimator or auto-run.

B owns typed RiskState, UID/event lineage and risk fitting. This module only
qualifies already bound objects, projects fixed columns, matches rows and routes
frozen nodes to the existing physical fit owner after explicit future authority.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
import copy
import json
import numpy as np
import pandas as pd
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.risk.shared_risk_engine_r2 import RiskState, SourceReceipt, COORDINATE, _time
from scripts.research.a2.risk.event_risk_contract_r5 import structural_identity, EventWitness
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash
from scripts.research.a2.risk.joint_risk_estimators import validate_covariance
from scripts.research.a2.portfolio.shared_joint_adapter_r2 import risk_state_sha256
from scripts.research.a2.training import stateful_values as owner
from scripts.research.a2.training import stateful_mechanism as parent
from scripts.research.a2.training import stateful_mechanism_models as models

RESEARCH_ID = 'V24_A_CONTINUOUS_EVENT_RISK_ACTION_R11A1'
B_RESEARCH_ID = 'V24_B_DYNAMIC_FULLPOOL_RISK_AND_IDENTITY_R5'
IDENTITY = 'A_EXPOSED_PRE2026_CONTINUOUS_EVENT_RISK_ACTION_MECHANISM'
DESIGN_SHA = '70d68db95aeffb294f23bcfbfba1b35fc71035bc68119b277b3e4488955b229e'
DAG_SHA = '520a62af197c9225c8ee0020ddd54dedd80b8240135821d0349ebec251a124fe'
DESIGN_CONTENT_SHA = '4dc15f1fab7088fa37c89133977e8d4172ec9b045715fb781a8fc0c51fc4464a'
DAG_CONTENT_SHA = '9fbc70915d8d28838d6ffe655328888db9fbad8b8871f6e2ff7247cff51c1fce'
FREEZE_TASK = 'V24_A_R11_B_R5_EXACT_HANDOFF_AND_R11A1_FREEZE_R1'
ENTRY_COLUMNS = ('H5_TYPED_SIGMA_I','H5_VARIANCE_I','H5_COV_I_RAW20','H5_RAW20_PORT_VARIANCE')
PAIR_COLUMNS = ('H5_TYPED_SIGMA_E','H5_VARIANCE_E','H5_COV_IE')
SOURCE_SLOTS = ('bank','freeze','qualification','ledger')
GATES = ('actual_formal_publications_bound','owner_ledger_qualified',
    'exact_R5_recipe_method_schema_match','H5_coordinate_units_match',
    'source_cutoff_and_historical_available_clock_qualified',
    'A_current_members_SIDs_UID_epochs_and_dates_qualified',
    'family_head_year_own_legal_mask_qualified','target_features_weights_and_matched_arms_qualified',
    'own_information_source_fingerprint_and_registry_admission',
    'A1_thin_projection_joint_scaler_adapter_reviewed','physical_budget_and_node_identity_valid',
    'applicable_numeric_execution_authority')
BOUNDARY = pd.Timestamp('2026-01-01',tz='UTC')

class ConsumerBlocked(ValueError):
    """Only the dependent row/node/scope is blocked; there is no fallback."""


def _need(condition, reason):
    if not condition: raise ConsumerBlocked(reason)


def _text(value):
    return isinstance(value,str) and bool(value.strip()) and value.strip().upper() not in ('UNKNOWN','NULL','NONE','UNBOUND')


def _sha(value):
    return isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)


def _identity(value):
    _need(isinstance(value,dict) and set(value)=={'sid','uid','epoch'} and all(_text(v) for v in value.values()), 'EXACT_SID_UID_EPOCH_REQUIRED')
    return (value['sid'],value['uid'],value['epoch'])


def _clock(value):
    try: return _time(value)
    except (ValueError,TypeError,OverflowError) as e: raise ConsumerBlocked('EXPLICIT_VALID_STATE_CLOCK_REQUIRED') from e


def validate_budget(planned, hard_cap=160):
    _need(type(planned) is int and 0<=planned<=hard_cap and type(hard_cap) is int and hard_cap==160,'HARD_PHYSICAL_CAP_EXCEEDED')
    return True


@dataclass(frozen=True)
class FrozenPlan:
    design: dict
    dag: dict

    @classmethod
    def load(cls, design_path=None, dag_path=None):
        base=resolve(owner.REPO).results_root/'_maintenance'/FREEZE_TASK
        design_path=Path(design_path or base/'R11A1_PREREGISTERED_DESIGN.json')
        dag_path=Path(dag_path or base/'R11A1_PHYSICAL_DAG.json')
        _need(owner.sha(design_path)==DESIGN_SHA and owner.sha(dag_path)==DAG_SHA,'FROZEN_A1_BYTES_CHANGED')
        design=json.loads(design_path.read_text(encoding='utf-8-sig'))
        dag=json.loads(dag_path.read_text(encoding='utf-8-sig'))
        _need(design['research_id']==RESEARCH_ID and design['scientific_identity']==IDENTITY and dag['research_id']==RESEARCH_ID,'FROZEN_IDENTITY_MISMATCH')
        _need(len(dag['scopes'])==28 and len(dag['nodes'])==140 and dag['estimator_slots']==112 and dag['scaler_units']==28,'FROZEN_DAG_COUNT')
        _need(dag['strict_planned_max']==140 and dag['hard_physical_cap']==160 and dag['unallocated']==20 and dag['unallocated_may_not_be_spent'] is True and dag['scientific_retry']==0 and dag['cross_family_dedup_assumed'] is False,'FROZEN_DAG_BUDGET')
        _need(len({n['node_id'] for n in dag['nodes']})==140,'FROZEN_NODE_DUPLICATE')
        for node in dag['nodes']:
            _need(node['node_spec_SHA']==owner.digest({k:v for k,v in node.items() if k!='node_spec_SHA'}),'FROZEN_NODE_SPEC_SHA')
        for path,sha in design['base_feature_contract']['source_code_pins'].items():
            _need(_parent_source_pin_matches(path,sha),'PARENT_SOURCE_PIN_CHANGED:'+path)
        return cls(design,dag)

    def verify(self):
        _need(owner.digest(self.design)==DESIGN_CONTENT_SHA and owner.digest(self.dag)==DAG_CONTENT_SHA,'FROZEN_PLAN_MUTATED_OR_UNSEALED')

    def family(self, name):
        self.verify()
        found=[x for x in self.design['source_compatibility_matrix'] if x['family']==name]
        _need(len(found)==1,'FAMILY_NOT_FROZEN')
        return found[0]

    def scope_nodes(self, scope):
        self.verify()
        _need(scope in self.dag['scopes'],'SCOPE_NOT_FROZEN')
        return copy.deepcopy([n for n in self.dag['nodes'] if n['scope']==scope])

    def runtime_nodes(self, package):
        _need(package['research_id']==RESEARCH_ID and package['design_sha256']==DESIGN_SHA and package['mode']=='train','FIT_SCOPE_REQUIRED')
        return [{**n,'mask_identity':package['mask_identity'],'input_identity':package['input_identity']} for n in self.scope_nodes(package['scope'])]


def project_state(plan,state,meta,binding,request,*,family,head,year,mode):
    """Use typed state only. Validate first; never repair or return a new C."""
    try:
        return _project(plan,state,meta,binding,request,family,head,year,mode)
    except ConsumerBlocked: raise
    except (KeyError,TypeError,ValueError,AttributeError,IndexError) as e:
        raise ConsumerBlocked('BLOCKED_INPUT_STATE_CONTRACT:'+str(e)) from e


def _project(plan,state,m,b,r,family,head,year,mode):
    spec=plan.family(family)
    _need(head in ('ENTRY','UNIFIED_INCUMBENT') and year in (2024,2025) and type(year) is int and mode in ('train','eval'),'FROZEN_SCOPE_ROLE')
    _need(type(state) is RiskState and type(m) is dict and type(b) is dict,'SHARED_TYPED_STATE_REQUIRED')
    required=('research_id','family','method','recipe_sha256','producer_sha256','source_path','source_sha256',
        'source_identity','source_version','bank_schema','state_schema','schema_version','state_available_at',
        'state_sha256','state_id','fit_dependency_ids','ledger_ref','ledger_sha256','ordered_U','security_ids','uids','epochs',
        'security_coordinate','source_support_identity','parameters','history_recipe','horizon','coordinate',
        'cutoff','as_of','psd_qualified','coverage_qualified','source_still_valid','maturity_still_valid','qualification_status')
    _need(all(k in m and m[k] is not None for k in required),'MISSING_OR_NULL_STATE_METADATA')
    equal=('research_id','family','method','recipe_sha256','producer_sha256','source_path','source_sha256',
        'source_identity','source_version','bank_schema','state_schema','schema_version','ledger_ref','ledger_sha256',
        'ordered_U','security_ids','uids','epochs','security_coordinate','source_support_identity','parameters','history_recipe','horizon','coordinate')
    _need(all(k in b and b[k] is not None and m[k]==b[k] for k in equal),'WRONG_BOUND_SOURCE_OR_IDENTITY')
    _need(m['research_id']==B_RESEARCH_ID and m['family']==family and m['method']==spec['method'] and m['recipe_sha256']==spec['recipe_SHA'] and m['producer_sha256']==spec['producer_SHA'],'FROZEN_METHOD_RECIPE_PRODUCER')
    _need(m['bank_schema']=='B_R5_EVENT_RISK_BANK_V1' and m['state_schema']=='SHARED_RISK_STATE_R2' and type(m['schema_version']) is int and m['schema_version']==1,'SOURCE_SCHEMA_VERSION')
    _need(all(_sha(m[k]) for k in ('recipe_sha256','producer_sha256','source_sha256','state_sha256','ledger_sha256')),'PHYSICAL_AND_STATE_SHA_REQUIRED')
    _need(all(_text(m[k]) for k in ('source_identity','source_version','ledger_ref','state_id','security_coordinate')) and Path(m['source_path']).is_absolute() and Path(m['ledger_ref']).is_absolute(),'ABSOLUTE_EXPLICIT_SOURCE_REFS_REQUIRED')
    _need(isinstance(m['parameters'],dict) and bool(m['parameters']) and isinstance(m['history_recipe'],dict) and bool(m['history_recipe']),'EXPLICIT_PARAMS_HISTORY_REQUIRED')
    _need(m['psd_qualified'] is True and m['coverage_qualified'] is True and m['source_still_valid'] is True and m['maturity_still_valid'] is True and m['qualification_status']=='QUALIFIED','LITERAL_STATE_QUALIFICATION_REQUIRED')
    _need(type(m['horizon']) is int and m['horizon']==5 and type(state.horizon) is int and state.horizon==5 and m['coordinate']==spec['coordinate'] and state.return_coordinate==COORDINATE and m['security_coordinate']==COORDINATE,'EXACT_H5_COORDINATE_REQUIRED')
    receipt=state.source_receipt
    if isinstance(receipt,dict):
        _need(set(receipt)==set(SourceReceipt.__dataclass_fields__),'EXACT_SHARED_SOURCE_RECEIPT_FIELDS_REQUIRED')
        receipt=SourceReceipt(**receipt)  # Existing schema only. State and state SHA stay untouched.
    _need(type(receipt) is SourceReceipt,'SHARED_SOURCE_RECEIPT_REQUIRED')
    _need(state.status==('PASS_SYNTHETIC' if receipt.synthetic else 'PASS_FROZEN_HISTORY_MECHANISM') and state.method==spec['method'] and state.risk_state_id==m['state_id'] and state.source_identity==m['source_identity'] and not state.blocked_assets,'TYPED_STATE_NOT_QUALIFIED')
    available,decision,asof,cutoff=map(_clock,(m['state_available_at'],r['decision_information_time'],m['as_of'],m['cutoff']))
    _need(decision<BOUNDARY and cutoff<asof<=available<=decision and _clock(state.as_of)==asof and _clock(state.cutoff)==cutoff,'NONFUTURE_RISK_STATE_CLOCK_REQUIRED')
    date=pd.Timestamp(r['decision_date'])
    _need(date.tzinfo is None and not pd.isna(date) and date==date.normalize() and date.date()==decision.date(),'EXACT_DECISION_DATE_REQUIRED')
    fold=_clock(f'{year}-01-01T00:00:00+00:00')
    if mode=='train': _need(decision<fold and available<fold and asof<fold and cutoff<fold,'OWN_FOLD_PRE_CUTOFF_REQUIRED')
    else: _need(fold<=decision<_clock(f'{year+1}-01-01T00:00:00+00:00'),'OWN_EVALUATION_YEAR_REQUIRED')
    assets=tuple(m['ordered_U'])
    _need(isinstance(m['ordered_U'],list) and tuple(state.assets)==assets and all(_text(a) for a in assets),'EXACT_ORDERED_U_REQUIRED')
    structural=structural_identity(assets=assets,uids=m['uids'],epochs=m['epochs'],security_coordinate=m['security_coordinate'],source_support_identity=m['source_support_identity'])
    epoch='R5_CURRENT_POOL_OBSERVED_UIDS:'+content_hash(m['epochs'])
    _need(state.identity_epoch==epoch,'POOLED_SECURITY_EPOCH_MISMATCH')
    lineage=state.notes['estimator_lineage']
    for key,val in (('family',family),('method_id',spec['method']),('recipe_sha256',spec['recipe_SHA']),('structural_identity',structural),('source_support_identity_sha256',content_hash(m['source_support_identity'])),('asset_uid_epoch_sha256',content_hash(dict(uids=m['uids'],epochs=m['epochs'])))):
        _need(lineage.get(key)==val,'ESTIMATOR_LINEAGE_MISMATCH:'+key)
    EventWitness(decision.isoformat(),structural,lineage['structural_identity'],m['source_still_valid'],m['maturity_still_valid']).validate(asof)
    _need(isinstance(m['fit_dependency_ids'],list) and len(m['fit_dependency_ids'])>0 and all(_text(v) for v in m['fit_dependency_ids']) and tuple(m['fit_dependency_ids'])==state.fit_dependency_ids,'LEARNED_STATE_DEPENDENCIES_REQUIRED')
    _need(type(receipt) is SourceReceipt and receipt.source_identity==m['source_identity'] and receipt.source_version==m['source_version'] and receipt.source_sha256==m['source_sha256'] and receipt.identity_epoch==state.identity_epoch and receipt.return_coordinate==COORDINATE,'TYPED_SOURCE_RECEIPT_MISMATCH')
    receipt.validate(cutoff)
    _need(_clock(receipt.available_at)<=available,'SOURCE_NOT_AVAILABLE_FOR_STATE')
    _need(state.notes.get('strict_PIT_promotion_eligible') is False and state.notes.get('quote_qualified') is False and state.notes.get('certified_nav_qualified') is False,'NO_ACCOUNT_OR_PIT_PROMOTION')
    _need(m['state_sha256']==risk_state_sha256(state),'TYPED_STATE_SHA_MISMATCH')
    _need(isinstance(state.coverage,Mapping) and set(state.coverage)==set(assets),'EXACT_COVERAGE_REQUIRED')
    for asset in assets:
        coverage=state.coverage[asset]
        _need(isinstance(coverage,dict) and coverage.get('uid')==m['uids'][asset] and coverage.get('identity_epoch')==m['epochs'][asset] and coverage.get('pooled_identity_epoch')==state.identity_epoch,'ASSET_COVERAGE_UID_EPOCH_MISMATCH')
    c=np.asarray(state.covariance);sigma=np.asarray(state.marginal_sigma)
    _need(c.dtype.kind=='f' and c.shape==(len(assets),len(assets)) and sigma.dtype.kind=='f' and sigma.shape==(len(assets),),'TYPED_RISK_DIMENSION_OR_TYPE')
    validate_covariance(c,regularize=False)  # Check only. Discard its symmetrized return.
    _need(np.isfinite(sigma).all() and np.all(sigma>=0) and np.allclose(sigma,np.sqrt(np.diag(c)),rtol=1e-10,atol=1e-12),'TYPED_SIGMA_DIAGONAL_INVARIANT')
    raw=r['raw20']
    _need(isinstance(raw,list) and len(raw)==20,'BLOCKED_INPUT_RAW20_RISK_COORDINATE')
    raw_ids=[_identity(x) for x in raw]
    _need(len({x[0] for x in raw_ids})==20 and len({x[1] for x in raw_ids})==20,'BLOCKED_INPUT_RAW20_RISK_COORDINATE')
    positions={a:j for j,a in enumerate(assets)}
    sid_map=m['security_ids']
    _need(isinstance(sid_map,dict) and set(sid_map)==set(assets) and all(_text(v) for v in sid_map.values()) and len(set(sid_map.values()))==len(assets),'EXACT_SOURCE_BOUND_ASSET_SID_MAPPING_REQUIRED')
    by_sid={sid:asset for asset,sid in sid_map.items()}
    def locate(identity):
        sid,uid,epoch_= _identity(identity)
        _need(sid in by_sid,'BLOCKED_INPUT_RAW20_RISK_COORDINATE')
        asset=by_sid[sid]
        _need(m['uids'][asset]==uid and m['epochs'][asset]==epoch_,'BLOCKED_INPUT_RAW20_RISK_COORDINATE')
        return positions[asset]
    rawpos=[locate(x) for x in raw];i=locate(r['actor'])
    _need(type(r['action_type']) in (int,float) and r['action_type'] in (0,1),'ORIGINAL_ACTION_TYPE_REQUIRED')
    w=np.zeros(len(assets));w[rawpos]=1/20
    result=[sigma[i],c[i,i],(c@w)[i],w@c@w]
    if head=='ENTRY':
        _need(r['entrant'] is None,'ENTRY_ACTOR_IS_ENTRANT_NO_PAIR')
    elif r['action_type']==0:
        _need(r['entrant'] is None,'SELL_STRUCTURAL_NO_ENTRANT_REQUIRED')
        result.extend([0.,0.,0.])
    else:
        _need(r['entrant'] is not None,'PAIR_ENTRANT_IDENTITY_REQUIRED')
        e=locate(r['entrant']);_need(e!=i,'PAIR_SELF_REPLACEMENT_FORBIDDEN')
        result.extend([sigma[e],c[e,e],c[i,e]])
    _need(np.isfinite(result).all(),'NONFINITE_FIXED_PROJECTION')
    return np.asarray(result,float)

def build_scope(plan,family,head,year,frame,packets,raw20_by_date,*,mode='train'):
    """One family/head/year mask. BASE/PLUS share one immutable input identity."""
    scope=f'{family}|{head}|{year}';plan.scope_nodes(scope)
    _need(mode in ('train','eval'),'EXPLICIT_ROW_ROLE_REQUIRED')
    required={'sample_id','signal_date','label_qualified','label_mature_date','target','base_weight',
        'actor_sid','actor_uid','actor_epoch','decision_information_time','execution_friction_bps','decoder','r8_pair_key'}
    _need(required.issubset(frame.columns),'NATIVE_ROW_CONTRACT_MISSING')
    _need(frame.attrs.get('target_contract')=='R10_NATIVE_HMEAN_NET_ACTION_ADVANTAGE_H3_H5_H10_H20','UNCHANGED_NATIVE_HMEAN_TARGET_BINDING_REQUIRED')
    _need(not frame.sample_id.duplicated().any() and frame.sample_id.map(_text).all(),'EXACT_UNIQUE_ORDERED_ROWS_REQUIRED')
    selected=parent.mature_train(frame,f'{year}-01-01') if mode=='train' else parent.outer(frame,year)
    selected=selected.sort_values(['signal_date','sample_id']).reset_index(drop=True)
    columns=parent.SINGLE if head=='ENTRY' else (*parent.PAIR,'action_type')
    blocked=[];keep=[];risk=[];state_bindings=[]
    for j,row in enumerate(selected.to_dict('records')):
        sid=row['sample_id']
        try:
            _need(row['execution_friction_bps']==10 and type(row['execution_friction_bps']) is int and row['decoder']=='P0','FROZEN_FRICTION_DECODER')
            _need(pd.notna(row['label_mature_date']) and _clock(pd.Timestamp(row['label_mature_date']).tz_localize('UTC').isoformat())<BOUNDARY,'PRE2026_LABEL_MATURITY_REQUIRED')
            _need(type(row['label_qualified']) is bool and row['label_qualified'] is True and np.isfinite(row['target']),'QUALIFIED_NATIVE_TARGET_REQUIRED')
            date=str(pd.Timestamp(row['signal_date']).date())
            action=row.get('action_type',0)
            entrant=None
            if head=='UNIFIED_INCUMBENT' and action==1:
                _need(_text(row['r8_pair_key']) and row['r8_pair_key']==sid,'EXACT_PRE_Y_R8_PAIR_KEY_REQUIRED')
                entrant={k:row['entrant_'+k] for k in ('sid','uid','epoch')}
            request=dict(decision_date=date,decision_information_time=row['decision_information_time'],
                actor={k:row['actor_'+k] for k in ('sid','uid','epoch')},entrant=entrant,
                raw20=raw20_by_date[date],action_type=action)
            state,meta,binding=packets[sid]
            projected=project_state(plan,state,meta,binding,request,family=family,head=head,year=year,mode=mode)
            keep.append(j);risk.append(projected);state_bindings.append(source_fingerprint(meta))
        except (ConsumerBlocked,KeyError,ValueError,TypeError) as e:
            blocked.append({'sample_id':sid,'status':'BLOCKED_INPUT','reason':str(e)})
    _need(bool(keep),'BLOCKED_INPUT_EMPTY_OWN_SCOPE')
    f=selected.iloc[keep].reset_index(drop=True)
    _need(np.isfinite(f.base_weight.to_numpy(float)).all() and (f.base_weight.to_numpy(float)>0).all(),'POSITIVE_ORIGINAL_PAIR_MASS_REQUIRED')
    base,base_names=parent.encode(f,columns);rr=np.stack(risk)
    _need(not np.isinf(base).any(),'PARENT_BASE_ENCODING_NONFINITE')
    weight=parent.role_weights(f);target=f.target.to_numpy(float)
    risk_names=ENTRY_COLUMNS+(PAIR_COLUMNS if head=='UNIFIED_INCUMBENT' else ())
    row_keys=f.sample_id.tolist();dates=[str(pd.Timestamp(v).date()) for v in f.signal_date]
    same=dict(row_keys=row_keys,dates=dates,target=target.tolist(),weights=weight.tolist(),
        cutoff=f'{year}-01-01',action_keys=row_keys,r8_pair_keys=f.r8_pair_key.tolist(),friction_bps=10,decoder='P0')
    mask_identity=owner.digest(dict(selected_rows=selected.sample_id.tolist(),legal_rows=row_keys,own_scope=scope))
    input_identity=owner.digest(dict(scope=scope,mask_identity=mask_identity,matched=same,
        BASE=content_hash(base),risk=content_hash(rr),BASE_columns=base_names,RISK_columns=risk_names,source_states=state_bindings))
    return dict(research_id=RESEARCH_ID,design_sha256=DESIGN_SHA,scope=scope,family=family,head=head,year=year,mode=mode,
        mask_identity=mask_identity,input_identity=input_identity,matched=same,frame=f,
        base=base,risk=rr,joint=np.concatenate([base,rr],axis=1),target=target,weights=weight,
        dates=f.signal_date.to_numpy(),base_names=base_names,risk_names=risk_names,
        source_state_fingerprints=tuple(state_bindings),blocked_rows=blocked)


def verify_package(package):
    try:
        _need(package['research_id']==RESEARCH_ID and package['design_sha256']==DESIGN_SHA and package['mode'] in ('train','eval'),'PACKAGE_IDENTITY_ROLE')
        _need(package['scope']==f"{package['family']}|{package['head']}|{package['year']}",'PACKAGE_SCOPE_CHANGED')
        f=package['frame'];same=package['matched']
        _need(same['row_keys']==f.sample_id.tolist() and same['action_keys']==f.sample_id.tolist() and same['r8_pair_keys']==f.r8_pair_key.tolist(),'MATCHED_ROW_KEYS_CHANGED')
        dates=[str(pd.Timestamp(v).date()) for v in f.signal_date]
        _need(same['dates']==dates and np.array_equal(package['dates'],f.signal_date.to_numpy()),'MATCHED_DATES_CHANGED')
        _need(same['target']==package['target'].tolist() and np.array_equal(package['target'],f.target.to_numpy(float)),'MATCHED_TARGET_CHANGED')
        _need(same['weights']==package['weights'].tolist() and np.array_equal(package['weights'],parent.role_weights(f)),'MATCHED_WEIGHTS_CHANGED')
        _need(same['cutoff']==f"{package['year']}-01-01" and same['friction_bps']==10 and same['decoder']=='P0' and f.execution_friction_bps.eq(10).all() and f.decoder.eq('P0').all(),'MATCHED_CUTOFF_FRICTION_DECODER_CHANGED')
        columns=parent.SINGLE if package['head']=='ENTRY' else (*parent.PAIR,'action_type')
        base,names=parent.encode(f,columns)
        _need(package['base_names']==names and np.array_equal(package['base'],base,equal_nan=True),'MATCHED_BASE_FEATURES_CHANGED')
        risk_names=ENTRY_COLUMNS+(PAIR_COLUMNS if package['head']=='UNIFIED_INCUMBENT' else ())
        _need(package['risk_names']==risk_names and package['risk'].shape==(len(f),len(risk_names)) and np.isfinite(package['risk']).all(),'FROZEN_RISK_COLUMNS_CHANGED')
        _need(np.array_equal(package['joint'],np.concatenate([base,package['risk']],axis=1),equal_nan=True),'JOINT_INPUT_CHANGED')
        identity=owner.digest(dict(scope=package['scope'],mask_identity=package['mask_identity'],matched=same,
            BASE=content_hash(base),risk=content_hash(package['risk']),BASE_columns=names,RISK_columns=risk_names,source_states=package['source_state_fingerprints']))
        _need(identity==package['input_identity'],'PACKAGE_INPUT_IDENTITY_CHANGED')
    except ConsumerBlocked: raise
    except (KeyError,ValueError,TypeError,AttributeError) as e: raise ConsumerBlocked('PACKAGE_INTEGRITY_INVALID') from e


def _runtime_node(plan,node,package):
    verify_package(package)
    nodes=plan.scope_nodes(package['scope'])
    original=next((n for n in nodes if n['node_id']==node.get('node_id')),None)
    _need(original is not None and all(node.get(k)==v for k,v in original.items()),'RUNTIME_NODE_FROZEN_MAPPING_CHANGED')
    _need(node.get('mask_identity')==package['mask_identity'] and node.get('input_identity')==package['input_identity'],'RUNTIME_NODE_MASK_OR_INPUT_CHANGED')
    return original


def scaler_identity(package):
    return owner.digest(dict(scope=package['scope'],mask=package['mask_identity'],joint=content_hash(package['joint']),
        weights=content_hash(package['weights']),cutoff=package['matched']['cutoff'],columns=(*package['base_names'],*package['risk_names'])))


def arm_input(package,node,*,scaler=None,scaler_binding=None):
    """Only transforms; no fit. Ridge takes BASE slice of one joint transform."""
    if node['kind']=='scaler': return package['joint'],(*package['base_names'],*package['risk_names'])
    plus=node['arm']=='BASE_PLUS_ONE_RISK_STATE'
    if node['learner']=='hgb':
        _need(node['scaler_dependency'] is None,'HGB_SCALER_DEPENDENCY_FORBIDDEN')
        x=package['joint'] if plus else package['base']
    else:
        _need(node['learner']=='ridge' and scaler is not None and scaler_binding==scaler_identity(package),'BLOCKED_INPUT_RIDGE_JOINT_SCALER')
        _need(type(scaler).__module__=='sklearn.preprocessing._data' and type(scaler).__name__=='StandardScaler','EXISTING_STANDARD_SCALER_REQUIRED')
        width=package['joint'].shape[1]
        _need(getattr(scaler,'n_features_in_',None)==width and np.asarray(scaler.mean_).shape==(width,) and np.asarray(scaler.scale_).shape==(width,) and np.isfinite(scaler.mean_).all() and np.isfinite(scaler.scale_).all() and np.all(scaler.scale_>0),'INVALID_FITTED_JOINT_SCALER')
        transformed=scaler.transform(package['joint'])
        x=transformed if plus else transformed[:,:len(package['base_names'])]
    _need(not np.isinf(x).any(),'INFINITE_ROUTED_INPUT')
    # Same missing-value recipe as the pinned parent: no new imputation fit.
    return np.nan_to_num(x,nan=0.),(*package['base_names'],*package['risk_names']) if plus else package['base_names']


REUSE_FIELDS=('source_states','ordered_rows','mask','y','weights','cutoff','parameters','seed','BASE_transform','scientific_tuple')

def exact_reuse_proof(current,previous):
    _need(isinstance(current,dict) and isinstance(previous,dict) and all(k in current and k in previous and (k=='seed' or (current[k] is not None and previous[k] is not None)) for k in REUSE_FIELDS),'COMPLETE_EXACT_REUSE_PROOF_REQUIRED')
    return all(content_hash(current[k])==content_hash(previous[k]) for k in REUSE_FIELDS)


def scientific_tuple(plan,node,package,*,scaler_binding=None):
    _runtime_node(plan,node,package)
    return dict(source_states=list(package['source_state_fingerprints']),ordered_rows=package['matched']['row_keys'],
        mask=package['mask_identity'],y=content_hash(package['target']),weights=content_hash(package['weights']),
        cutoff=node['cutoff'],parameters=node.get('parameters',{'algorithm':node['algorithm']} if node['kind']=='scaler' else {}),
        seed=node.get('seed'),BASE_transform=scaler_binding if node.get('learner')=='ridge' else 'RAW_PARENT_ENCODING',
        scientific_tuple=dict(research_id=RESEARCH_ID,design_sha256=DESIGN_SHA,DAG_sha256=DAG_SHA,
            node_spec_SHA=node['node_spec_SHA'],input_identity=package['input_identity']))


def exact_reuse_alias(plan,node,package,receipt,events,persist,*,scaler_binding=None):
    """Optional runtime proof; no assumed alias, new reservation or backend."""
    _runtime_node(plan,node,package)
    current=scientific_tuple(plan,node,package,scaler_binding=scaler_binding)
    _need(receipt.get('status')=='TRAINED' and receipt.get('research_id')==RESEARCH_ID and receipt.get('fit_units')==1,'TRAINED_ORIGINAL_RECEIPT_REQUIRED')
    _need(exact_reuse_proof(current,receipt.get('scientific_tuple')),'BLOCKED_EXACT_REUSE_NOT_PROVEN')
    reservation=receipt['reservation']
    _need(reservation.get('research_id')==RESEARCH_ID and reservation.get('design_sha256')==DESIGN_SHA and reservation.get('DAG_sha256')==DAG_SHA and reservation.get('scientific_tuple_sha256')==owner.digest(current),'EXACT_ORIGINAL_RESERVATION_REQUIRED')
    _need(not any(e.get('node_id')==node['node_id'] and e.get('event')=='A1_NODE_FAILED' for e in events),'FAILED_NODE_CANNOT_ALIAS_OR_RETRY')
    previous=[e for e in events if e.get('event')=='A1_NODE_RESERVED' and e.get('node_id')==reservation['node_id']]
    _need(len(previous)==1 and previous[0]==reservation and any(e.get('event')=='A1_NODE_COMPLETE' and e.get('node_id')==reservation['node_id'] and e.get('reservation_sha256')==owner.digest(reservation) for e in events),'ORIGINAL_LEDGER_CLOSURE_REQUIRED')
    _need(not any(e.get('event')=='A1_NODE_RESERVED' and e.get('node_id')==node['node_id'] and e!=reservation for e in events),'TARGET_ALREADY_ATTEMPTED_NO_ALIAS')
    path=Path(receipt['model_path']);assert_safe_output_path(path,kind='backtest')
    _need(_sha(receipt.get('model_sha256')) and owner.sha(path)==receipt['model_sha256'],'EXACT_TRAINED_ARTIFACT_SHA_REQUIRED')
    alias=dict(event='A1_NODE_EXACT_REUSED',research_id=RESEARCH_ID,node_id=node['node_id'],
        original_node_id=reservation['node_id'],scientific_tuple_sha256=owner.digest(current),
        model_path=str(path),model_sha256=receipt['model_sha256'],units=0,hypothesis_identity_preserved=True)
    persist(alias)
    return alias


def reserve_node(plan,node,tuple_,events,persist):
    """Append to the existing FIT_LOG before backend; no retries or refunds."""
    plan.verify()
    original=next((n for n in plan.dag['nodes'] if n['node_id']==node.get('node_id')),None)
    _need(original is not None and all(node.get(k)==v for k,v in original.items()),'RESERVATION_NODE_NOT_FROZEN')
    _need(_sha(node.get('mask_identity')) and _sha(node.get('input_identity')),'ACTUAL_RUNTIME_INPUT_BINDING_REQUIRED')
    _need(all(k in tuple_ and tuple_[k] is not None for k in REUSE_FIELDS if k!='seed'),'RESERVATION_SCIENTIFIC_TUPLE_REQUIRED')
    _need(tuple_['scientific_tuple']['node_spec_SHA']==node['node_spec_SHA'] and tuple_['mask']==node['mask_identity'],'RESERVATION_TUPLE_NODE_MISMATCH')
    reservations=[e for e in events if e.get('event')=='A1_NODE_RESERVED']
    _need(all(e.get('research_id')==RESEARCH_ID and e.get('design_sha256')==DESIGN_SHA and e.get('DAG_sha256')==DAG_SHA for e in reservations),'LEDGER_FOREIGN_IDENTITY')
    _need(not any(e['node_id']==node['node_id'] for e in reservations),'SCIENTIFIC_RETRY_FORBIDDEN')
    _need(len({e['node_id'] for e in reservations})==len(reservations) and all(e.get('units')==1 and type(e.get('units')) is int and e.get('node_id') in {n['node_id'] for n in plan.dag['nodes']} for e in reservations),'INVALID_FROZEN_RESERVATION_LEDGER')
    used=sum(e['units'] for e in reservations)
    validate_budget(used+1,160)
    _need(used+1<=140,'UNALLOCATED20_SPEND_FORBIDDEN')
    event=dict(event='A1_NODE_RESERVED',research_id=RESEARCH_ID,design_sha256=DESIGN_SHA,DAG_sha256=DAG_SHA,
        node_id=node['node_id'],units=1,scientific_tuple_sha256=owner.digest(tuple_),scope=node['scope'],attempt=1)
    _need(callable(persist),'DURABLE_RESERVATION_WRITER_REQUIRED')
    persist(copy.deepcopy(event))  # Failure prevents backend. No mutation before durable append.
    return event


def activation_check(authority):
    _need(isinstance(authority,dict) and authority.get('research_id')==RESEARCH_ID and authority.get('scientific_identity')==IDENTITY and authority.get('design_sha256')==DESIGN_SHA and authority.get('DAG_sha256')==DAG_SHA and authority.get('2026_locked') is True,'EXACT_A1_EXECUTION_AUTHORITY_REQUIRED')
    _need(all(authority.get(k) is True for k in GATES),'A1_LITERAL_TRUE_ACTIVATION_REQUIRED')
    _need(_sha(authority.get('information_source_fingerprint')) and authority.get('registry_admitted') is True,'OWN_SOURCE_FINGERPRINT_AND_ADMISSION_REQUIRED')
    publications=authority.get('publication_bindings')
    _need(isinstance(publications,dict) and set(publications)==set(SOURCE_SLOTS),'FOUR_FORMAL_PUBLICATIONS_REQUIRED')
    for v in publications.values():
        _need(isinstance(v,dict) and _text(v.get('path')) and Path(v['path']).is_absolute() and _sha(v.get('sha256')) and v.get('qualified') is True,'UNBOUND_SOURCE_PUBLICATION')
    return True


def dispatch_reserved(plan,node,package,events,persist,backend,authority,*,scaler=None,scaler_binding=None):
    activation_check(authority)
    _runtime_node(plan,node,package)
    _need(package['mode']=='train' and callable(backend),'TRAIN_ONLY_OWNER_BACKEND_REQUIRED')
    x,features=arm_input(package,node,scaler=scaler,scaler_binding=scaler_binding)
    tuple_=scientific_tuple(plan,node,package,scaler_binding=scaler_binding)
    reservation=reserve_node(plan,node,tuple_,events,persist)
    try:
        value=backend(node,x,features,package,reservation)
    except Exception:
        persist(dict(event='A1_NODE_FAILED',research_id=RESEARCH_ID,node_id=node['node_id'],reservation_sha256=owner.digest(reservation)))
        raise
    persist(dict(event='A1_NODE_COMPLETE',research_id=RESEARCH_ID,node_id=node['node_id'],reservation_sha256=owner.digest(reservation)))
    return value


def execute_node(plan,node,package,run,authority,*,scaler=None,scaler_binding=None):
    """Existing unique continuation lock covers reservation plus physical owner."""
    from scripts.research.a2.training.stateful_execution import continuation_lock
    activation_check(authority)
    run=Path(run);assert_safe_output_path(run,kind='backtest')
    with continuation_lock(run,owner.sha(__file__),namespace=RESEARCH_ID):
        return _execute_node_under_lock(plan,node,package,run,authority,scaler=scaler,scaler_binding=scaler_binding)


def _execute_node_under_lock(plan,node,package,run,authority,*,scaler=None,scaler_binding=None):
    """Explicit future hook to the SAME worker/ACK owner. Never called on import."""
    from scripts.storage.storage_r2a import write_json_atomic
    import joblib
    activation_check(authority)
    validate_parent_source_pins(plan)
    run=Path(run);assert_safe_output_path(run,kind='backtest')
    cfg=json.loads((run/'run_config.json').read_text(encoding='utf-8'))
    _need(cfg.get('research_id')==RESEARCH_ID and cfg.get('frozen_design_sha256')==DESIGN_SHA and cfg.get('frozen_DAG_sha256')==DAG_SHA,'EXACT_EXISTING_A1_RUN_REQUIRED')
    _need(cfg.get('execution_authority_sha256')==owner.digest(authority),'RUN_EXECUTION_AUTHORITY_MISMATCH')
    _need(cfg.get('information_source_fingerprint')==authority['information_source_fingerprint'],'RUN_SOURCE_FINGERPRINT_MISMATCH')
    _need(cfg.get('real_numeric_execution_authorized') is True,'REAL_EXECUTION_NOT_AUTHORIZED')
    verify_registry_acceptance(authority)
    _need(authority.get('scope_input_bindings',{}).get(package['scope'])==dict(input_identity=package['input_identity'],source_states=list(package['source_state_fingerprints'])),'EXACT_ADMITTED_SCOPE_INPUTS_REQUIRED')
    for pin in authority['publication_bindings'].values():
        _need(owner.sha(pin['path'])==pin['sha256'],'PUBLICATION_PHYSICAL_SHA_CHANGED')
    log=run/'FIT_LOG.jsonl';events=owner._events(log)
    def persist(event): owner._append(log,event)
    _runtime_node(plan,node,package)
    slot=run/'models/mechanism'/node['node_spec_SHA']
    cached=slot/'fit_receipt.json'
    if cached.exists():
        receipt=json.loads(cached.read_text(encoding='utf-8'))
        alias=exact_reuse_alias(plan,node,package,receipt,events,persist,scaler_binding=scaler_binding)
        return joblib.load(alias['model_path'])
    def backend(n,x,features,pkg,reservation):
        slot=run/'models/mechanism'/n['node_spec_SHA'];slot.mkdir(parents=True,exist_ok=True)
        rp=slot/'fit_receipt.json';mp=slot/'model.joblib'
        _need(not rp.exists() and not mp.exists(),'EXISTING_SLOT_NO_REFIT')
        receipt=dict(status='RUNNING',research_id=RESEARCH_ID,node_id=n['node_id'],reservation=reservation,fit_units=0,receipt_path=str(rp),scientific_tuple=scientific_tuple(plan,n,pkg,scaler_binding=scaler_binding))
        write_json_atomic(rp,receipt)
        payload=dict(family=n.get('learner','SCALER'),capacity=n.get('capacity','MID'),seed=n.get('seed',20260928),
            objective='ADVANTAGE',target=pkg['target'],weights=pkg['weights'],source_pins=models.source_pins())
        operation='mechanism_scaler' if n['kind']=='scaler' else 'mechanism'
        if n['kind']=='estimator': _need(models.parameters(models.canonical_family(n['learner']),'MID')==n['parameters'],'PINNED_BACKEND_PARAMETERS_CHANGED')
        try:
            model=owner._fit_job(operation,n['node_id'],x,payload,pkg['dates'],None,cfg['dependency_paths'],features,None,
                log=log,auth=dict(max_fit_units=140,max_new_bucket_fit_units=140,budget_bucket='R11A1'),prior=0,
                year=pkg['year'],tuple_sha=reservation['scientific_tuple_sha256'],receipt=receipt,worker_target=models.fit_worker)
            _need(receipt['fit_units']==1,'ONE_NODE_ONE_PHYSICAL_FIT_REQUIRED')
            joblib.dump(model,mp);receipt.update(status='TRAINED',model_sha256=owner.sha(mp),model_path=str(mp))
            write_json_atomic(rp,receipt);return model
        except Exception as e:
            receipt.update(status='FAILED',error=type(e).__name__+':'+str(e));write_json_atomic(rp,receipt);raise
    return dispatch_reserved(plan,node,package,events,persist,backend,authority,scaler=scaler,scaler_binding=scaler_binding)


def source_fingerprint(metadata):
    """Pure deterministic builder. No source read, registry write or activation."""
    keys=('source_path','source_sha256','source_version','bank_schema','state_schema','schema_version','cutoff',
        'state_available_at','ordered_U','security_ids','uids','epochs','horizon','coordinate','method','parameters','history_recipe',
        'state_sha256','ledger_ref','ledger_sha256','fit_dependency_ids','recipe_sha256','producer_sha256')
    _need(isinstance(metadata,dict) and all(k in metadata and metadata[k] is not None for k in keys),'FINGERPRINT_UNBOUND')
    _need(all(_sha(metadata[k]) for k in ('source_sha256','state_sha256','ledger_sha256','recipe_sha256','producer_sha256')),'FINGERPRINT_PHYSICAL_SHA_REQUIRED')
    return owner.digest({k:metadata[k] for k in keys})


def _parent_source_pin_matches(path,expected):
    observed=owner.sha(path)
    if observed==expected: return True
    from scripts.research.a2.training import stateful_risk_handoff as handoff
    if Path(path)!=handoff.REGISTRY_PATH or expected!=handoff.OLD_REGISTRY_SHA: return False
    try: proof=handoff.registry_descendant_compatibility()
    except (ConsumerBlocked,OSError,ValueError,TypeError,KeyError): return False
    return proof['semantic_compatible'] is True and observed==proof['current_sha256']


def validate_parent_source_pins(plan):
    plan.verify()
    for path,expected in plan.design['base_feature_contract']['source_code_pins'].items():
        _need(_parent_source_pin_matches(path,expected),'PARENT_SOURCE_PIN_CHANGED_AT_EXECUTION:'+path)
    return True


def verify_registry_acceptance(authority):
    """Query the existing canonical registry, never caller-created admission."""
    from scripts.maintenance import research_registry as registry
    activation_check(authority)
    root,_=registry._load_config(None,None)
    view=registry.query_registry(root,entity_id=RESEARCH_ID)
    _need(view.get('status')=='PASS' and view.get('count')==1,'A1_ACCEPTED_CANONICAL_ENTITY_REQUIRED')
    row=view['entities'][0]
    _need(view['head_sha256']==authority.get('registry_head_sha256') and row['row_hash']==authority.get('registry_row_hash'),'REGISTRY_SNAPSHOT_ROW_PIN_MISMATCH')
    _need(row['entity_id']==RESEARCH_ID and row['status'] in ('OPEN','ACTIVE') and row['information_source_fingerprint']==authority['information_source_fingerprint'],'OWN_A1_REGISTRY_ADMISSION_REQUIRED')
    metadata=row['metadata']
    _need(metadata.get('frozen_design_sha256')==DESIGN_SHA and metadata.get('frozen_DAG_sha256')==DAG_SHA and metadata.get('scientific_identity')==IDENTITY,'REGISTRY_FROZEN_DESIGN_BINDING')
    _need(metadata.get('publication_bindings')==authority['publication_bindings'] and metadata.get('scope_input_bindings')==authority.get('scope_input_bindings'),'REGISTRY_ACTUAL_SOURCE_INPUT_BINDING')
    _need(metadata.get('strict_PIT_promotion_eligible') is False and metadata.get('account_qualified') is False and metadata.get('2026_locked') is True and metadata.get('numeric_execution_authorized') is True,'REGISTRY_RESEARCH_ONLY_EXECUTION_SCOPE')
    return True


def handoff_schema():
    """Publication schema only: no fake bank or current qualification."""
    sha={'type':'string','pattern':'^[0-9a-f]{64}$'}
    ref={'type':'object','required':['path','sha256','schema','qualified'],
        'properties':{'path':{'type':'string','minLength':1},'sha256':sha,'schema':{'type':'string','minLength':1},'qualified':{'const':True}},'additionalProperties':False}
    state_keys=('research_id','state_id','state_sha256','state_available_at','cutoff','as_of','family','method','recipe_sha256','producer_sha256',
        'event_ids','ordered_U','security_ids','uids','epochs','security_coordinate','source_support_identity','horizon','coordinate',
        'fit_dependency_ids','parameters','history_recipe','psd_qualified','coverage_qualified','source_still_valid','maturity_still_valid',
        'source_identity','source_version','source_path','source_sha256','bank_schema','state_schema','schema_version','ledger_ref','ledger_sha256','qualification_status')
    props={k:{'type':'string','minLength':1} for k in ('state_id','family','method','security_coordinate','coordinate','source_identity','source_version','source_path','ledger_ref')}
    props.update({k:{'type':'string','format':'date-time'} for k in ('state_available_at','cutoff','as_of')})
    props.update({k:sha for k in ('state_sha256','recipe_sha256','producer_sha256','source_sha256','ledger_sha256')})
    props.update({k:{'type':'array','minItems':1,'uniqueItems':True,'items':{'type':'string','minLength':1}} for k in ('event_ids','ordered_U','fit_dependency_ids')})
    props.update({k:{'type':'object','minProperties':1} for k in ('security_ids','uids','epochs','source_support_identity','parameters','history_recipe')})
    props.update({k:{'const':True,'type':'boolean'} for k in ('psd_qualified','coverage_qualified','source_still_valid','maturity_still_valid')})
    props.update(horizon={'const':5,'type':'integer'},research_id={'const':B_RESEARCH_ID},
        bank_schema={'const':'B_R5_EVENT_RISK_BANK_V1'},state_schema={'const':'SHARED_RISK_STATE_R2'},schema_version={'const':1,'type':'integer'},qualification_status={'const':'QUALIFIED'})
    props['family']={'enum':['SHR_HP','SHR_CC','LW','OAS','EWMA','PCA_FACTOR','QQQ_RESIDUAL']}
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'R11A1_B_R5_HANDOFF_MANIFEST_SCHEMA_R1',
        'title':'R11A1 B R5 explicit publication metadata handoff','type':'object',
        'required':['schema','research_id','version',*SOURCE_SLOTS,'date_coverage','states'],
        'properties':{'schema':{'const':'R11A1_B_R5_HANDOFF_MANIFEST_R1'},'research_id':{'const':B_RESEARCH_ID},'version':{'const':1,'type':'integer'},
            **{k:ref for k in SOURCE_SLOTS},'date_coverage':{'type':'object','required':['start','end_exclusive'],
                'properties':{'start':{'type':'string','format':'date'},'end_exclusive':{'type':'string','format':'date'}},'additionalProperties':False},
            'states':{'type':'array','minItems':1,'items':{'type':'object','required':list(state_keys),'properties':props,'additionalProperties':False}}},'additionalProperties':False}
