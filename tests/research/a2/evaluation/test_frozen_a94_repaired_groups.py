"""Pure small metadata refusals and existing toy action-owner compatibility."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import json
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.evaluation import frozen_a94_profile as p
from scripts.research.a2.inference import frozen_a94_actions as c
from tests.research.a2.inference.test_frozen_a94_actions import context,ref

@pytest.fixture
def group(monkeypatch,tmp_path):
    docs={}
    def add(name,d):
        rr=dict(path=str(tmp_path/name),sha256=c.base.values.digest(d));docs[name]=deepcopy(d);return rr
    def get(rr):return deepcopy(docs[Path(rr['path']).name])
    monkeypatch.setattr(p,'_document',get)
    monkeypatch.setattr(p,'_physical',lambda r:Path(r['path']))
    monkeypatch.setattr(p._common(),'_physical',lambda r:Path(r['path']))
    monkeypatch.setattr(p,'_REPAIR_ROOT',tmp_path)
    monkeypatch.setattr(p,'_REPAIR_ACCOUNT_GROUPS',('R10_SEQUENCE_GRU_L20_LOW',)+tuple('FIXED_'+str(i) for i in range(18)))
    frec=dict(path=str(tmp_path/'MISSING_COMPONENT_CONTRACT.json'),sha256='f2be0d964ae9141b354ff0fbcfcc642ac940927d9f39274e58eff44155e18cf5')
    iref=dict(path=str(tmp_path/'REPAIRED_CANDIDATE_INVENTORY_R1.json'),sha256='a1f19af2cb01c5908779b7515e970e1b3009aa5a3c66c86b1e57fdb806cc1174')
    leaf=add('leaf.json',dict(toy=True));cid='R10_SEQUENCE_GRU_L20_LOW';sid='HAZARD_SEQUENCE_JOINTSEQ_L20_2025_gru_LOW_20260928';scid='HAZARD_SEQUENCE_JOINTSEQ_L20_2025_SCALER'
    bundle=dict(kind='R10_JOINT_SEQUENCE',family='gru',capacity='LOW',lookback=20,seeds_by_group={'JOINT_SEQUENCE':[20260928]})
    spec=dict(candidate_id=cid,frozen_bundle=bundle,scientific_tuple_sha256='original',execution_friction={'one_way_bps':10})
    original=dict(candidate_id=cid,specification=spec,scientific_tuple_sha256='original',source_group='R10',runtime_owner='FINAL_ACTION_OVERLAY',required_action_roles=['R10:JOINT_SEQUENCE'],lookback=20,model_ids=[sid])
    allowed=[original]+[dict(original,candidate_id='FIXED_'+str(i)) for i in range(18)]
    parentref=add('parent.json',dict(candidates=allowed));docs['REPAIRED_CANDIDATE_INVENTORY_R1.json']=dict(task_id=p.REPAIR_TASK,candidates=deepcopy(allowed))
    keys=dict(slot_id=sid,family='gru',capacity='LOW',seed=20260928,group='JOINT_SEQUENCE',lookback=20,horizon='MEAN',year=2025,bucket='HAZARD_SEQUENCE',objective='ADVANTAGE',cutoff_exclusive='2025-01-01',prefix=False)
    failure=add('failure.json',keys);sfail=add('sfailure.json',dict(status='FAIL'))
    mp=dict(path=str(tmp_path/'model.bin'),sha256='model');sp=dict(path=str(tmp_path/'scale.bin'),sha256='scale')
    design='design';sources=[leaf];params=dict(epochs=12,width=16)
    arrays={k:dict(array_sha256=k,shape=[2,20,1] if k=='x' else [2]) for k in ('x','target','dates','weights')}
    tup=dict(keys,design_sha256=design,features=['a'],x_shape=[2,20,1],target_shape=[2],**{k+'_sha256':k for k in arrays})
    stup=dict(slot_id=scid,family='SCALER',capacity='SHARED',seed=None,objective='PREPROCESSOR',year=2025,design_sha256=design,features=['a'],x_shape=[40,1],target_shape=[40],x_sha256='sx',dates_sha256='sd',weights_sha256='sw',target_sha256='st')
    sinput=add('sinput.json',dict(status='ORIGINAL_SCALER_INPUT_COMMITMENTS_EXACT',new_fit=0,original_scaler_ref=sfail,features=['a'],signal_max='2024-11-29',maturity_max='2024-12-31',arrays={k:dict(array_sha256=stup[k+'_sha256'],shape=stup['x_shape'] if k=='x' else [40]) for k in ('x','dates','weights')}))
    sr=add('sreceipt.json',dict(schema='ORIGINAL_COMPONENT_RECOVERY_FIT_R1',task_id=p.REPAIR_TASK,contract_ref=frec,original_failure_ref=sfail,model_ref=sp,model_predict=0,account_replay=0,fit_units=1,source_refs=sources,driver_ref=leaf,input_ref=sinput,original_scientific_tuple=stup,status='TRAINED'))
    inp=add('input.json',dict(task_id=p.REPAIR_TASK,contract_ref=frec,new_fit=0,status='ORIGINAL_L20_SCALER_TRANSFORM_PREPARED',signal_max='2024-11-29',maturity_max='2024-12-31',features=['a'],arrays=arrays,scaler_model_ref=sp,scaler_receipt_ref=sr,source_input_ref=sinput))
    mr=add('receipt.json',dict(schema='ORIGINAL_L20_COMPONENT_RECOVERY_R1',task_id=p.REPAIR_TASK,contract_ref=frec,original_failure_ref=failure,model_ref=mp,model_predict=0,account_replay=0,fit_units=1,original_source_refs=sources,driver_ref=leaf,input_ref=inp,scientific_tuple=tup,scientific_tuple_sha256=c.base.values.digest(tup),original_failed_spec=keys,status='TRAINED',metadata=dict(parameters=params,epochs=12,final_epoch_only=True)))
    node=dict(slot_id=sid,original_failure_ref=failure,external_scaler_dependencies=[scid],original_model_configuration=params,original_scientific_tuple=None,existing_model_ref=None)
    definition=dict(candidate_id=cid,classification='RECOVERABLE',original_runtime_owner='FINAL_ACTION_OVERLAY',frozen_bundle=bundle,nodes=[node],original_contract_ref=dict(path='design',sha256=design))
    components=[definition]+[dict(definition,candidate_id='FIXED_'+str(i)) for i in range(18)]
    rec=dict(schema='A_MISSING_COMPONENT_CONTRACT_R1',task_id=p.REPAIR_TASK,inventory_ref=parentref,components=components,shared_scalers=[dict(slot_id=scid,receipt_ref=sfail,model_ref=None,scientific_tuple=stup)],original_source_refs=sources)
    docs['MISSING_COMPONENT_CONTRACT.json']=rec
    cr=add('closure.json',dict(schema='ORIGINAL_MISSING_CANDIDATE_COMPONENT_CLOSURE_R1',task_id=p.REPAIR_TASK,candidate_id=cid,contract_ref=frec,status='MODEL_DEPENDENCY_CLOSURE_COMPLETE',model_dependencies_complete=True,frozen_bundle=bundle,nodes=[dict(slot_id=sid,model_ref=mp,receipt_ref=mr)],scalers=[dict(slot_id=scid,model_ref=sp,receipt_ref=sr)]))
    def row(t,m,r):
        out={k:t[k] for k in ('slot_id','year','family','capacity','seed','objective')};out.update(stage='R10',status='TRAINED',group=t.get('group','JOINT_SEQUENCE'),lookback=20,feature_order=t['features'],model_path=m['path'],model_sha256=m['sha256'],receipt_ref=r);return out
    old_candidate=dict(candidate_id=cid,model_ids=[sid],external_scaler_ids=[],scientific_tuple_sha256='original')
    old=add('old_states.json',dict(candidate_rows=[old_candidate],authority_refs={'R10_contract':leaf}))
    states={'new_model:'+sid:dict(model_ref=mp,receipt_ref=mr),'new_scaler:'+scid:dict(model_ref=sp,receipt_ref=sr)}
    nr=add('new_states.json',dict(schema='A_REPAIR_GROUP_FROZEN_STATE_DEPENDENCIES_R1',task_id=p.REPAIR_TASK,candidate_id=cid,closure_ref=cr,authority_refs={'R10_contract':leaf},model_states=[row(tup,mp,mr)],external_scaler_states=[row(stup,sp,sr)],state_refs=states,candidate_rows=[dict(old_candidate,external_scaler_ids=[scid])]))
    raw=dict(task_id=p.REPAIR_TASK,pool_variant_id='TOP100',source_catalog_ref=leaf,source_bundle_ref=leaf,common_runtime_contract_ref=leaf,metadata_refs=dict(plan=leaf,new_states=old),state_refs={'old_value:ridge':dict(model_ref=leaf,receipt_ref=leaf)})
    rr=add('release.json',dict(schema='A_REPAIR_ORIGINAL_GROUP_RELEASE_R1',task_id=p.REPAIR_TASK,status='ROOT_RELEASED_ORIGINAL_COMPONENT_GROUP',plan_ref=leaf,recovery_contract_ref=frec,candidate_inventory_ref=iref,pool_variant_id='TOP100',source_catalog_ref=leaf,source_bundle_ref=leaf,common_runtime_contract_ref=leaf,new_fit_in_inference=0,candidate_id=cid,closure_ref=cr,new_states_ref=nr))
    return SimpleNamespace(d=docs,raw=raw,release=rr,call=lambda:p._repaired_group_contract(raw,rr),sid=sid,scid=scid,cid=cid)

def test_complete_is_exact_original_single_group(group):
    z=group.call();assert len(z['candidate_bindings'])==1 and len(z['state_refs'])==3
    assert z['candidate_bindings'][0]['specification']==group.d['parent.json']['candidates'][0]['specification']
    assert z['candidate_bindings'][0]['dependency_closure']['status']=='COMPLETE'
    assert len(z['recovered_state_receipt_views'])==2

@pytest.mark.parametrize('doc,key,value',[
 ('release.json','schema','ANY'),('release.json','status','PENDING'),('release.json','task_id','OTHER'),
 ('release.json','pool_variant_id','TOP200'),('release.json','new_fit_in_inference',True),
 ('release.json','candidate_id','unknown'),('release.json','source_bundle_ref',{}),('release.json','common_runtime_contract_ref',{}),
 ('closure.json','model_dependencies_complete',False),('closure.json','status','TRAINED'),
 ('closure.json','candidate_id','OTHER'),('new_states.json','schema','ANY'),('new_states.json','authority_refs',{}),
 ('receipt.json','status','FAILED'),('receipt.json','model_ref',{}),('receipt.json','fit_units',2),
 ('receipt.json','account_replay',1),('receipt.json','contract_ref',{}),('receipt.json','original_source_refs',[]),
 ('receipt.json','original_failed_spec',{}),('receipt.json','scientific_tuple_sha256','bad'),
 ('input.json','maturity_max','2025-01-01'),('input.json','signal_max','2026-01-01'),
 ('input.json','scaler_model_ref',{}),('input.json','features',['BAD']),('sinput.json','original_scaler_ref',{}),
 ('sinput.json','maturity_max','2025-01-01'),('sreceipt.json','original_failure_ref',{})])
def test_exact_refs_closure_time_and_original_model_refusals(group,doc,key,value):
    group.d[doc][key]=value
    with pytest.raises((ValueError,KeyError,StopIteration)):group.call()

@pytest.mark.parametrize('field',['family','seed','lookback','cutoff_exclusive','design_sha256'])
def test_recovered_tuple_cannot_change_original_science(group,field):
    q=group.d['receipt.json'];q['scientific_tuple'][field]='CHANGED';q['scientific_tuple_sha256']=c.base.values.digest(q['scientific_tuple'])
    with pytest.raises(ValueError):group.call()

def test_training_parameters_cannot_change(group):
    group.d['receipt.json']['metadata']['parameters']['epochs']=99
    with pytest.raises(ValueError,match='FIXED_MODEL_CONFIGURATION'):group.call()

def test_cannot_borrow_gru_account_for_original_r7(group):
    for d in ('parent.json','REPAIRED_CANDIDATE_INVENTORY_R1.json'):group.d[d]['candidates'][0]['runtime_owner']='UNSUPPORTED_ORIGINAL_OWNER'
    group.d['MISSING_COMPONENT_CONTRACT.json']['components'][0]['original_runtime_owner']='UNSUPPORTED_ORIGINAL_OWNER'
    with pytest.raises(ValueError,match='KNOWN19|DECODER_UNAVAILABLE'):group.call()

def test_changed_inventory_spec_is_not_new_policy(group):
    group.d['REPAIRED_CANDIDATE_INVENTORY_R1.json']['candidates'][0]['specification']['execution_friction']['one_way_bps']=5
    with pytest.raises(ValueError,match='KNOWN19'):group.call()

def test_missing_or_reordered_model_bundle_refused(group):
    group.d['closure.json']['nodes']=[]
    with pytest.raises(ValueError,match='MODEL_BUNDLE'):group.call()

def test_actual_metadata_must_match_derived_rows(group):
    group.d['new_states.json']['model_states'][0]['seed']=999
    with pytest.raises(ValueError,match='STATE_METADATA'):group.call()

def test_second_group_or_seed_not_hidden_in_newer(group):
    group.d['new_states.json']['model_states'].append(deepcopy(group.d['new_states.json']['model_states'][0]))
    with pytest.raises(ValueError,match='STATE_METADATA'):group.call()

def test_outer_authority_cannot_swap_recovery_release():
    co=dict(task_id=p.REPAIR_TASK,pool_variant_id='TOP100',metadata_refs={'source_catalog':1,'source_bundle':2,'common_runtime':3},repaired_group_id='G',repaired_group_release_ref={'path':'G','sha256':'h'})
    doc=dict(pool_variant_id='TOP100',source_catalog_ref=1,source_bundle_ref=2,common_runtime_contract_ref=3,repaired_group_id='G',repaired_group_release_ref=co['repaired_group_release_ref'])
    p._require_repair_binding(doc,co);doc['repaired_group_release_ref']={'path':'OTHER','sha256':'h'}
    with pytest.raises(ValueError,match='BINDING_CHANGED'):p._require_repair_binding(doc,co)

def test_action_loader_uses_exact_recovery_schema_view(context,monkeypatch):
    original_contract=context.loader.context._check();contract=deepcopy(original_contract)
    key=next(k for k in context.states if k.startswith('new_model:HAZARD_SEQUENCE_JOINTSEQ_L5_2025_gru'))
    rr=context.states[key]['receipt_ref'];view=json.loads(Path(rr['path']).read_text('utf8'))
    contract.update(repaired_group_id='SYNTHETIC_GROUP',recovered_state_receipt_views={key:view})
    auth=replace(context.auth,task_id=c.base.profile.REPAIR_TASK,provenance_json=json.dumps(dict(context.prov,repaired_group_id='SYNTHETIC_GROUP')))
    monkeypatch.setattr(c.base.profile,'contract_for_authority',lambda a:deepcopy(contract))
    loader=c.FrozenActionLoader(auth);assert loader.load(key).kind=='r10'
    contract['recovered_state_receipt_views'][key]['model_sha256']='wrong'
    assert loader.load(key).kind=='r10'  # existing sealed view is immutable
    with pytest.raises(ValueError,match='RECEIPT_OR'):c.FrozenActionLoader(auth).load(key)

def test_repair_l20_has_own_input_commitment(context):
    old=context.publish('R10:JOINT_SEQUENCE');role=old.role;frame=old.frame.copy();tensor=np.repeat(old.tensor[:,:1,:],20,axis=1);mask=old.supported.copy()
    cid='ORIGINAL_L20';rows={cid:dict(lookback=20,required_action_roles=[role])}
    proof=deepcopy(context.qual['action_feature_inputs'][role]);proof['commitment']=c.input_commitment(frame,old.features,tensor,mask)
    context.qual['action_feature_inputs'][role+':L20']=proof;qref=ref(Path(context.qual_ref['path']),context.qual)
    prov=dict(context.prov,source_qualification_ref=qref,repaired_group_id=cid)
    auth=replace(context.auth,task_id=c.base.profile.REPAIR_TASK,allowed_path_ids=(cid,),runtime_policy_ids=(cid,),provenance_json=json.dumps(prov))
    loader=SimpleNamespace(_check=lambda:{'repaired_group_id':cid},authority=auth,_candidates=rows)
    value=c.bind_action_input(loader,role,frame,tensor=tensor,supported=mask,lookback=20);assert value.tensor.shape[1]==20
    with pytest.raises(ValueError,match='SEQUENCE_LENGTH'):c.bind_action_input(loader,role,frame,tensor=old.tensor,supported=mask,lookback=5)
    loader._check=lambda:{}
    with pytest.raises(ValueError,match='SEQUENCE_MASK'):c.bind_action_input(loader,role,frame,tensor=tensor,supported=mask,lookback=20)


def test_repaired_calendar_capability_no_io(context,monkeypatch):
    cid='R10_SEQUENCE_GRU_L20_LOW';release={'path':'C:/toy/release.json','sha256':'f'*64}
    prov=dict(repaired_group_id=cid,pool_variant_id='TOP100',repaired_group_release_ref=release,
        metadata_refs=dict(recovery_release=release,recovery_contract=dict(path=str(p._REPAIR_ROOT/'MISSING_COMPONENT_CONTRACT.json'),sha256='f2be0d964ae9141b354ff0fbcfcc642ac940927d9f39274e58eff44155e18cf5')),
        candidate_bindings=[dict(candidate_id=cid,runtime_owner='FINAL_ACTION_OVERLAY',dependency_closure={'status':'COMPLETE'})])
    auth=replace(context.auth,task_id=p.REPAIR_TASK,allowed_path_ids=(cid,),runtime_policy_ids=(cid,),provenance_json=json.dumps(prov))
    monkeypatch.setattr(p,'_document',lambda *a:pytest.fail('NO_IO'))
    assert p.repaired_group_calendar_capable(auth)
    for field,value in [('pool_variant_id','TOP200'),('repaired_group_id','RAW_s10'),('repaired_group_id','R7_GROSS_TREE'),('repaired_group_release_ref',{'path':'other','sha256':'f'*64})]:
        changed=dict(prov,**{field:value});assert not p.repaired_group_calendar_capable(replace(auth,provenance_json=json.dumps(changed)))
    assert not p.repaired_group_calendar_capable(replace(auth,runtime_policy_ids=()))
    with pytest.raises(ValueError):p.repaired_group_calendar_capable(replace(auth,_seal=None))


@pytest.mark.parametrize('key,value',[('fit_units',True),('model_predict',False),('account_replay',False)])
def test_receipt_counters_are_original_integer_counts(group,key,value):
    group.d['receipt.json'][key]=value
    with pytest.raises(ValueError,match='RECEIPT_IDENTITY'):group.call()

def test_original_fit_schema_not_a_new_tuple(group):
    r=group.d['receipt.json'];t=r.pop('scientific_tuple');r['schema']='ORIGINAL_COMPONENT_RECOVERY_FIT_R1';r['original_scientific_tuple']=t
    group.d['MISSING_COMPONENT_CONTRACT.json']['components'][0]['nodes'][0]['original_scientific_tuple']=deepcopy(t)
    i=group.d['input.json'];i['status']='ORIGINAL_INPUT_COMMITMENTS_EXACT';i['slot_ids']=[group.sid];i['scaler_ref']=r['model_ref']
    i['scaler_ref']=group.d['closure.json']['scalers'][0]['model_ref']
    assert group.call()['recovered_state_receipt_views']['new_model:'+group.sid]['scientific_tuple']==t
    i['arrays']['target']['array_sha256']='changed'
    with pytest.raises(ValueError,match='SCALER_OR_TARGET'):group.call()

def test_existing_original_state_keeps_original_receipt(group):
    r=group.d['receipt.json'];t=deepcopy(r['scientific_tuple']);node=group.d['MISSING_COMPONENT_CONTRACT.json']['components'][0]['nodes'][0]
    node['original_scientific_tuple']=t;node['existing_model_ref']=r['model_ref'];fref=node['original_failure_ref']
    group.d['failure.json']=dict(status='TRAINED',scientific_tuple=t)
    group.d['closure.json']['nodes'][0]['receipt_ref']=fref
    newer=group.d['new_states.json'];newer['model_states'][0]['receipt_ref']=fref;newer['state_refs']['new_model:'+group.sid]['receipt_ref']=fref
    result=group.call();assert 'new_model:'+group.sid not in result['recovered_state_receipt_views']

def test_group_cash_authorization_cannot_be_borrowed_by_raw_or_reverse(monkeypatch):
    old={'path':'raw','sha256':'a'*64};new={'path':'group','sha256':'b'*64};plan={'path':'plan','sha256':'c'*64};inv={'path':'inv','sha256':'d'*64}
    monkeypatch.setattr(p,'_post_verified_decision_ref',lambda task,**kw:old)
    monkeypatch.setattr(p,'_contract_as_of',lambda con:'2026-10-08T21:00:00Z')
    prohibitions={k:False for k in ('model_or_H5_input_authority','new_fit','parameter_or_rule_change','strategy_selection','production_qualified','strict_PIT_promotion_eligible','broker_orders','source_or_account_admitted_by_decision_alone','economic_window_extended')}
    decision=dict(schema='A94_POST_VERIFIED_CASH_TERMINAL_SOURCE_DECISION_R1',task_id=p.REPAIR_TASK,status='HUMAN_AUTHORIZED_NOT_SOURCE_OR_RUNTIME_ADMISSION',candidate_scope='EXACT_ORIGINAL_KNOWN19_RECOVERED_SINGLE_GROUP_TOP100_FRESH_RANDOM_RESEARCH',clock_role='POST_VERIFIED_ACCOUNTING_ONLY',original_plan_ref=plan,candidate_manifest_ref=inv,economic_as_of_utc='2026-10-08T21:00:00Z',separate_A6_permission_inherited=False,prohibitions=prohibitions)
    monkeypatch.setattr(p,'_document',lambda r:decision)
    contract=dict(task_id=p.REPAIR_TASK,repaired_group_id='G',recovery_accounting_decision_ref=new,metadata_refs=dict(plan=plan,inventory=inv))
    bound=dict(post_verified_accounting_decision_ref=new,research_cash_reconstruction=dict(task_id=p.REPAIR_TASK,authorization_ref=old,events=[{}]))
    with pytest.raises(ValueError,match='EXACT_GROUP_ACCOUNTING'):p._accounting_decision(bound,contract)
