'''Finite new-version account admission for the ten originally untestable rows.
Reuse the original TOP100 source/CA authority; never relax legacyA94 inventory.
No quotes, outcomes, model decoding, fits or account execution on import.
'''
from dataclasses import replace
import json
from pathlib import Path
import pandas as pd
TASK='A_ALL_REPAIR_AND_CONSENSUS_SENSITIVITY_20261011_R1'
SCHEMA='REMAINING10_DESCRIPTIVE_AUTHORITY_REF_R1'
ROOT=Path('D:/us-tech-quant-results/_maintenance')/TASK
SCOPE_REF=dict(path=str(ROOT/'REMAINING10_EVALUATION_SCOPE_R1.json'),sha256='09589dee7fb911b17cff332e1441bbc6dda7f6d7521d30a956c344c7f508916f')
VERSIONS={
 'A_TOP100_SOLVER_CONTINUATION_20261012_R1':(('R10_DIRECT_MEAN4_ELASTICNET_MID','R10_DIRECT_MEAN4_ELASTICNET_HIGH','R10_DIRECT_MEAN4_HUBER_LOW','R10_DIRECT_MEAN4_HUBER_HIGH'),'2025-01-01'),
 'A_TOP100_R7_GROSS_ACCOUNT_ADAPTER_20261012_R1':(('R7_GROSS_LINEAR','R7_GROSS_TREE','R7_GROSS_NEURAL'),'2024-10-07'),
 'A_TOP100_COX_LANDMARK_H5_CONFIRMATION_20261012_R1':(('R10_HAZARD_COX_LOW','R10_HAZARD_COX_MID','R10_HAZARD_COX_HIGH'),'2025-01-01'),
}
def source_execution_context(research_id):
    p,f=_owners();p._document(SCOPE_REF)
    _require(research_id in VERSIONS,"REMAINING10_EXACT_NEW_SOURCE_CONTEXT")
    from scripts.common.storage_paths import resolve
    roots=resolve(Path("D:/us-tech-quant"))
    helper=dict(path=str(roots.cache_root/"_maintenance"/TASK/"source_compatibility"/"ca_worktree_source.py"),sha256="8ae837dd4de365989465210492e4b04eaf1163afcf03dee8d12f962a12b35219")
    proof=dict(path=str(ROOT/"CA_EXACT_SOURCE_COMPATIBILITY_ROOT_SEAL_R2.json"),sha256="6bf8ce13870350e175a1e4299e4c09203675517cab60ee79e7447f1e64345d4d")
    p._physical(helper);p._document(proof)
    exclusion=dict(path=str(ROOT/"REMAINING10_UNUSED_FUSION_OWNER_EXCLUSION_R1.json"),sha256="022c2ebc8fd07614796efbe86f18648049c2a4ada8aa3f8a228313d4d98acf6c")
    p._document(exclusion)
    cbc=dict(path=str(ROOT/"CBC_FROZEN_RUNTIME_RECOVERY_ROOT_SEAL_R1.json"),sha256="6baf03486fe55cc9b3374bd66f4aa11daea12f28161b630ce8c91beeeb31e7ae")
    p._document(cbc)
    return dict(research_id=research_id,scope_ref=SCOPE_REF,helper_ref=helper,proof_ref=proof,unused_fusion_exclusion_ref=exclusion,cbc_recovery_proof_ref=cbc)
def verify_unused_fusion_owner(owner_ref,context):
    p,f=_owners()
    fusion=Path('D:/us-tech-quant/scripts/research/a2/training/stateful_fusion.py').resolve()
    if Path(owner_ref.get('path','')).resolve()!=fusion:return False
    _require(_exact(context,source_execution_context(context.get('research_id'))),'REMAINING10_EXACT_SOURCE_EXECUTION_CONTEXT')
    proof=p._document(context['unused_fusion_exclusion_ref'])
    _require(proof.get('schema')=='REMAINING10_UNUSED_FUSION_OWNER_EXCLUSION_R1' and proof.get('status')=='ROOT_REVIEWED_FINITE_NATIVE_SCOPE_EXCLUSION' and proof.get('scope_ref')==SCOPE_REF and context['research_id'] in proof.get('allowed_research_ids',()) and proof.get('global_fusion_math_equivalence_claim') is False and proof.get('original_bytes_executed') is False,'REMAINING10_UNUSED_OWNER_SCOPE_ONLY')
    _require(_exact(owner_ref,proof.get('legacy_expected_owner_ref')) and owner_ref.get('sha256')=='f83c8e09c0cf2856a61f98b51775cf6f382d70b6266878876ced1eba2754ae3b','REMAINING10_EXACT_ORIGINAL_UNUSED_FUSION')
    actual=proof.get('actual_unconsumed_owner_ref',{})
    _require(Path(actual.get('path','')).resolve()==fusion and actual.get('sha256')=='1e1609bf2ec9ac20793ca18b402e3b5ae6be1da8759b91bf2f557c1cd4157e7c','REMAINING10_EXACT_ACTUAL_UNUSED_FUSION')
    f._physical(actual);f._physical(proof['original_source_custody_ref'])
    _require(proof.get('baseline_state_ids')==['old_value:ridge'] and proof.get('baseline_policy_ids')==['RAW_s10'],'REMAINING10_BASELINE_RAW_RIDGE_ONLY')
    return True
def verify_recovered_cbc_owner(owner_ref,context):
    p,f=_owners();canonical=Path('D:/us-tech-quant/scripts/research/a2/evaluation/continuous_research_account.py').resolve()
    if Path(owner_ref.get('path','')).resolve()!=canonical:return False
    _require(_exact(context,source_execution_context(context.get('research_id'))),'REMAINING10_EXACT_SOURCE_EXECUTION_CONTEXT')
    proof=p._document(context['cbc_recovery_proof_ref'])
    _require(proof.get('schema')=='CBC_FROZEN_RUNTIME_RECOVERY_ROOT_SEAL_R1' and proof.get('status')=='ROOT_AUTHORIZED_EXACT_FROZEN_CBC_LIVE_SOURCE_RECOVERY' and proof.get('scope_ref')==SCOPE_REF and context['research_id'] in proof.get('allowed_research_ids',()),'REMAINING10_ROOT_CBC_RECOVERY_SCOPE')
    _require(owner_ref==proof.get('expected_original_owner_ref') and owner_ref.get('sha256')=='4dd3b001485afab6bff4bb618391814f34063f7e262fb9a51a9864103fef9253' and proof.get('original_algorithm_bytes_exact') is True and proof.get('original_source_custody_direct_import') is False and proof.get('restored_original_algorithm_bytes_will_execute') is True,'REMAINING10_EXACT_LIVE_CBC_RECOVERY')
    actual=proof.get('actual_live_restored_source_ref',{})
    _require(Path(actual.get('path','')).resolve()==Path('D:/us-tech-quant-worktrees/a-repair-ca-source-20261011-r1/scripts/research/a2/evaluation/continuous_research_account.py').resolve() and actual.get('sha256')==owner_ref['sha256'],'REMAINING10_ONLY_APPROVED_LIVE_CBC')
    f._physical(actual)
    f._physical(proof['source_custody_ref'])
    return True
def require_no_fusion_states(states):
    for state in states.values():
        selectors=[str(state.get(k,'')).lower() for k in ('kind','state_type','family','method','objective','model_role')]
        selectors += [str(state.get('original_tuple',{}).get(k,'')).lower() for k in ('family','objective','model_role')]
        path=str(state.get('model_ref',{}).get('path','')).replace(chr(92),'/').lower()
        _require(not any('fusion' in x for x in selectors) and '/models/fusion/' not in path and state.get('consumes_fusion') is not True,'REMAINING10_FUSION_CONSUMPTION_FORBIDDEN')
def _owners():
    from scripts.research.a2.evaluation import frozen_a94_profile as p,frozen_test_authority as f
    return p,f
def _require(ok,code):
    _,f=_owners();f._require(ok,code)
def _exact(a,b):
    p,_=_owners();return p._exact(a,b)
def require_registry_reuse(release,science):
    p,_=_owners()
    preflight=p._document(release['registry_preflight_ref'])
    native=preflight.get('automatic_decision') if 'automatic_decision' in preflight else preflight
    _require(isinstance(native,dict),'REMAINING10_NATIVE_REUSE_DECISION_REQUIRED')
    verdicts=[native.get(key) for key in ('status','decision') if native.get(key) is not None]
    _require(bool(verdicts) and all(isinstance(x,str) and bool(x.strip()) for x in verdicts),'REMAINING10_NATIVE_REUSE_DECISION_REQUIRED')
    _require(not any(x.startswith(('BLOCKED','FAIL')) for x in verdicts),'REMAINING10_TERMINAL_OR_DUPLICATE_NOT_REOPENED')
    if any(x.startswith('REVIEW') and x!='REVIEWED' for x in verdicts):
        _require(release.get('registry_review_ref') is not None,'REMAINING10_FIXED_VERSION_REVIEW_REQUIRED')
        review=p._document(release['registry_review_ref'])
        _require(review.get('schema')=='REMAINING10_FIXED_VERSION_REUSE_REVIEW_R1' and review.get('status')=='APPROVED_EXPLICIT_USER_FIXED_NEW_VERSION' and review.get('research_id')==science and review.get('scope_ref')==SCOPE_REF and review.get('preflight_ref')==release['registry_preflight_ref'],'REMAINING10_FIXED_VERSION_REVIEW_REQUIRED')
def frozen_contract(release_ref):
    p,f=_owners()
    release_path=p._physical(release_ref)
    _require(release_path.is_relative_to(ROOT.resolve()),'REMAINING10_RELEASE_EXTERNAL_TASK_ROOT')
    d=p._document(release_ref);science=d.get('research_id')
    _require(d.get('schema')=='REMAINING10_ROOT_ACCOUNT_RELEASE_R1' and d.get('task_id')==TASK and science in VERSIONS,'REMAINING10_EXACT_NEW_IDENTITY')
    _require(d.get('status')=='ROOT_SINGLE_HEAVY_WORKER_RELEASED' and d.get('scope_ref')==SCOPE_REF,'REMAINING10_ROOT_RELEASE_REQUIRED')
    scope=p._document(SCOPE_REF)
    _require(scope.get('schema')=='REMAINING10_EXPOSED2026_NEW_VERSION_SCOPE_R1' and science in scope.get('versions',{}),'REMAINING10_FIXED_SHARED_SCOPE')
    expected,cutoff=VERSIONS[science];ids=tuple(d.get('candidate_ids',()))
    _require(len(ids)==len(expected) and set(ids)==set(expected) and len(set(ids))==len(ids),'REMAINING10_FIXED_FAMILY_IDS')
    _require(d.get('new_account_fit_count')==0 and type(d.get('new_account_fit_count')) is int and d.get('selection_using2026') is False,'REMAINING10_NO_FIT_OR_SELECTION')
    resource=d.get('resource_admission',{})
    _require(resource.get('exclusive_heavy_worker') is True and resource.get('physical_available_min_gib',0)>=1.5 and resource.get('page_available_min_gib',0)>=8.,'REMAINING10_ORIGINAL_RESOURCE_FLOORS')
    version=p._document(d.get('version_contract_ref'))
    _require(version.get('research_id')==science and version.get('status','').startswith('FROZEN'),'REMAINING10_VERSION_CONTRACT_REQUIRED')
    _require(d.get('schedule_ref')==scope['original_schedule_ref'] and d.get('consensus_manifest_ref')==scope['original_consensus_manifest_ref'],'REMAINING10_ORIGINAL_SCHEDULE_AND_POOL')
    schedule=p._document(d['schedule_ref'])
    _require(len(schedule.get('windows',()))==101 and _exact(d.get('windows'),schedule['windows']),'REMAINING10_ORIGINAL101_WINDOWS')
    _require(d.get('baseline_authority_ref',{}).get('schema')=='A_2026_DESCRIPTIVE_AUTHORITY_REF_R1' and d['baseline_authority_ref'].get('task_id')==TASK and d['baseline_authority_ref'].get('pool_variant_id')=='TOP100' and d['baseline_authority_ref'].get('repaired_group_release_ref') is None,'REMAINING10_RAW_TOP100_BASELINE_ONLY')
    models=p._document(d.get('model_closure_ref'))
    _require(models.get('schema')=='REMAINING10_FROZEN_ACCOUNT_MODEL_CLOSURE_R1' and models.get('research_id')==science and models.get('candidate_ids')==list(ids),'REMAINING10_MODEL_CLOSURE_REQUIRED')
    states=models.get('states',{})
    _require(isinstance(states,dict) and len(states)>=len(ids),'REMAINING10_ALL_MODEL_STATES_REQUIRED')
    require_no_fusion_states(states)
    for state_id,state in states.items():
        _require(state.get('candidate_id') in ids and state.get('fit_or_selection_using2026') is False and state.get('signal_cutoff_exclusive')==cutoff and state.get('label_maturity_cutoff_exclusive')==cutoff,'REMAINING10_ORIGINAL_EARLIER_MODEL_BOUNDARY')
        p._physical(state['model_ref']);p._document(state['receipt_ref'])
        document=p._document(state['training_audit_ref']);kind=state.get('training_clock_kind')
        solver=document.get('schema')=='REMAINING10_SOLVER_COMPONENT_TRAINING_AUDIT_R2'
        if solver:
            _require(science=='A_TOP100_SOLVER_CONTINUATION_20261012_R1' and document.get('research_id')==science and state_id in document.get('states',{}),'REMAINING10_SOLVER_CLOCK_STATE_ID')
            audit=document['states'][state_id]
            _require(audit.get('original_receipt_ref')==state['receipt_ref'] and _exact(audit.get('original_tuple'),state.get('original_tuple')) and audit.get('original_tuple',{}).get('cutoff_exclusive')==cutoff and audit.get('fitting_using2026') is False and audit.get('training_clock_kind')==kind,'REMAINING10_EXACT_TRAINING_CLOCK_AUDIT')
            expected_guards={
                str(Path('D:/us-tech-quant/scripts/research/a2/training/stateful_mechanism.py').resolve()):'0b2553f90927ebbe86a1f6e34475a7a45baad31d4a9ef534ced669a1f106dbe9',
                str(Path('D:/us-tech-quant/scripts/research/a2/training/stateful_mechanism_inputs.py').resolve()):'2ffeaeca4fb4993b4f17b9fa78af17788fdfaba504ef36790ea1eeca373e6f17'}
            guards=audit.get('original_cutoff_guard_source_refs',[])
            _require(isinstance(guards,list) and {str(Path(g.get('path','')).resolve()):g.get('sha256') for g in guards}==expected_guards and audit.get('guard_call_chain')=='model_role(year=2025) -> mature_train(frame,2025-01-01) -> legal_rows requires signal<cutoff and mature<cutoff','REMAINING10_ORIGINAL_STRICT_CLOCK_GUARDS')
            for g in guards:f._physical(g)
        else:
            audit=document
            _require(audit.get('schema')=='REMAINING10_MODEL_TRAINING_CLOCK_AUDIT_R1' and audit.get('candidate_id')==state['candidate_id'] and audit.get('model_ref')==state['model_ref'] and audit.get('receipt_ref')==state['receipt_ref'] and audit.get('training_clock_kind')==kind and audit.get('signal_cutoff_exclusive')==cutoff and audit.get('label_maturity_cutoff_exclusive')==cutoff,'REMAINING10_EXACT_TRAINING_CLOCK_AUDIT')
        if kind in ('OBSERVED_ARRAY_MAX','OBSERVED_MAX_FROM_EXACT_ORIGINAL_INPUT_COMMITMENTS'):
            _require((kind=='OBSERVED_MAX_FROM_EXACT_ORIGINAL_INPUT_COMMITMENTS')==solver,'REMAINING10_EXACT_OBSERVED_CLOCK_KIND')
            for field in ('training_signal_max','training_maturity_max'):
                _require(audit.get(field)==state.get(field) and pd.Timestamp(state.get(field))<pd.Timestamp(cutoff),'REMAINING10_MATURE_TRAINING_BOUNDARY')
            if solver:
                inputs=p._document(audit['input_ref'])
                _require(inputs.get('signal_max')==audit['training_signal_max'] and inputs.get('maturity_max')==audit['training_maturity_max'] and _exact(inputs.get('arrays',{}).get('dates'),audit.get('date_array_ref')) and audit.get('maturity_clock_source')=='EXACT_EXISTING_INPUTS_SIGNAL_AND_MATURITY_MAX_VERIFIED_PREPARATION_METADATA','REMAINING10_ORIGINAL_INPUT_MAX_COMMITMENT')
                p._physical(audit['date_array_ref'])
            else:
                for field in ('signal_dates_ref','label_maturity_dates_ref'):p._physical(audit[field])
        elif kind=='CERTIFIED_UPPER_BOUND_FROM_ORIGINAL_STRICT_CUTOFF_GUARD':
            _require('training_signal_max' not in state and 'training_maturity_max' not in state,'REMAINING10_UPPER_BOUND_IS_NOT_OBSERVED_MAX')
            for field in ('training_signal_upper_bound','training_maturity_upper_bound'):
                _require(audit.get(field)==state.get(field) and pd.Timestamp(state.get(field))<pd.Timestamp(cutoff),'REMAINING10_MATURE_TRAINING_UPPER_BOUND')
            if not solver:
                _require(audit.get('strict_signal_cutoff_guard') is True and audit.get('strict_label_maturity_cutoff_guard') is True,'REMAINING10_ORIGINAL_STRICT_CLOCK_GUARDS')
                for field in ('training_owner_ref','label_maturity_guard_owner_ref'):f._physical(audit[field])
                p._physical(audit['guard_evidence_ref'])
        else:_require(False,'REMAINING10_KNOWN_TRAINING_CLOCK_PROOF_REQUIRED')
    _require(set(s['candidate_id'] for s in states.values())==set(ids),'REMAINING10_COMPLETE_ALL_CANDIDATES')
    bindings=d.get('candidate_bindings')
    _require(isinstance(bindings,list) and tuple(x.get('candidate_id') for x in bindings)==ids,'REMAINING10_EXACT_CANDIDATE_BINDINGS')
    for row in bindings:
        specification=row.get('specification',{})
        _require(specification.get('candidate_id')==row['candidate_id'] and specification.get('research_id')==science and _exact(specification.get('execution_friction'),d.get('execution_friction')),'REMAINING10_FROZEN_FULL_SPEC')
        _require(row.get('dependency_closure',{}).get('status')=='COMPLETE' and set(row['dependency_closure'].get('state_ids',()))<=set(states) and bool(row['dependency_closure'].get('state_ids')),'REMAINING10_FULL_DECLARED_DEPENDENCIES')
    manifest=p._document(d.get('candidate_manifest_ref'))
    _require(manifest.get('task_id')==TASK and manifest.get('research_id')==science and manifest.get('scope_ref')==SCOPE_REF and _exact(manifest.get('candidates'),bindings),'REMAINING10_EXACT_NEW_CANDIDATE_MANIFEST')
    inputs=p._document(d.get('input_closure_ref'))
    _require(inputs.get('schema')=='REMAINING10_FROZEN_FORWARD_INPUT_CLOSURE_R1' and inputs.get('research_id')==science and inputs.get('candidate_ids')==list(ids) and inputs.get('pool_variant_id')=='TOP100','REMAINING10_NEW_INPUT_CLOSURE')
    _require(inputs.get('new_fit_count')==0 and type(inputs.get('new_fit_count')) is int and inputs.get('outcome_columns_in_model_features')==0 and inputs.get('source_ready_policy_ids')==list(ids),'REMAINING10_FROZEN_FORWARD_ONLY')
    _require(inputs.get('scope_ref')==SCOPE_REF and inputs.get('schedule_ref')==d['schedule_ref'] and inputs.get('consensus_manifest_ref')==d['consensus_manifest_ref'],'REMAINING10_SOURCE_CLOCK_AND_POOL_BINDING')
    _require(isinstance(inputs.get('feature_frame_refs'),dict) and bool(inputs['feature_frame_refs']) and inputs.get('label_columns_decoded')==0,'REMAINING10_BOUNDED_CAUSAL_INPUTS')
    for value in inputs['feature_frame_refs'].values():p._physical(value)
    _require(isinstance(d.get('parent_original_failure_refs'),list) and bool(d['parent_original_failure_refs']),'REMAINING10_ORIGINAL_FAILURES_RETAINED')
    for value in d['parent_original_failure_refs']:p._document(value)
    for value in d.get('runtime_source_refs',{}).values():f._physical(value)
    sources=d.get('runtime_source_refs',{})
    for key,path in dict(profile=p.__file__,remaining10_profile=__file__,authority=f.__file__).items():
        _require(key in sources and Path(sources[key].get('path','')).resolve()==Path(path).resolve(),'REMAINING10_CURRENT_RUNTIME_PINS_REQUIRED')
        f._physical(sources[key])
    _require(d.get('registry_preflight_ref') is not None,'REMAINING10_REUSE_PREFLIGHT_REQUIRED')
    require_registry_reuse(d,science)
    return dict(release=d,release_ref=release_ref,scope=scope,version=version,model_states=states,inputs=inputs,candidate_bindings=bindings,candidate_ids=ids)
def load_authority(authority):
    p,f=_owners()
    _require(isinstance(authority,dict) and authority.get('schema')==SCHEMA and authority.get('task_id')==TASK,'REMAINING10_NEW_AUTHORITY_SCHEMA_REQUIRED')
    c=frozen_contract(authority.get('root_release_ref'));d=c['release'];window=authority.get('window_id')
    _require(authority.get('research_id')==d['research_id'],'REMAINING10_RELEASE_SCIENCE_CHANGED')
    _require(window in [w['window_id'] for w in d['windows']],'REMAINING10_ORIGINAL_WINDOW_REQUIRED')
    baseline=dict(d['baseline_authority_ref']);baseline['window_id']=window
    # Call the existing source/CA admission before creating any new capability.
    original=p.load_authority(baseline,source_execution_context=source_execution_context(d['research_id']));old=json.loads(original.provenance_json)
    _require(original.task_id==TASK and old.get('pool_variant_id')=='TOP100' and 'RAW_s10' in original.source_ready_policy_ids,'REMAINING10_BASELINE_SOURCE_NOT_READY')
    _require(d.get('source_bundle_ref')==old.get('source_bundle_ref') and d.get('baseline_source_qualification_ref')==old.get('source_qualification_ref'),'REMAINING10_EXACT_BASELINE_SOURCES')
    _require(_exact(c['inputs'].get('baseline_source_refs'),old.get('source_refs')),'REMAINING10_INPUT_SOURCE_CUSTODY_CHANGED')
    original_qualification=p._document(d['baseline_source_qualification_ref'])
    qualification=p._document(d.get('source_qualification_ref'))
    _require(qualification.get('schema')=='A_2026_DESCRIPTIVE_SOURCE_QUALIFICATION_R1' and qualification.get('task_id')==TASK and qualification.get('remaining10_research_id')==d['research_id'] and qualification.get('baseline_source_qualification_ref')==d['baseline_source_qualification_ref'],'REMAINING10_NEW_FINITE_QUALIFICATION_REQUIRED')
    for key in ('source_refs','groups','source_slices','raw_selector_binding','as_of','common_calendar_start','common_calendar_end','common_calendar_selection'):
        _require(_exact(qualification.get(key),original_qualification.get(key)),'REMAINING10_SOURCE_QUALIFICATION_DRIFT')
    _require(qualification.get('new_fit')==0 and type(qualification.get('new_fit')) is int and _exact(qualification.get('action_feature_inputs'),c['inputs'].get('action_feature_inputs')),'REMAINING10_EXACT_ACTION_INPUT_PROOFS')
    for proof in qualification.get('action_feature_inputs',{}).values():
        _require(proof.get('status')=='SOURCE_BOUND_COMPLETE_ORIGINAL_COMPUTED_STATE' and proof.get('source_ref')==old['source_refs']['action_inputs'] and proof.get('new_fit_count')==0 and proof.get('outcome_columns_in_model_features')==0,'REMAINING10_FIXED_FORWARD_FEATURE_PROOF')
    provenance={**old,'schema':SCHEMA,'research_id':d['research_id'],'remaining10_release_ref':c['release_ref'],'remaining10_scope_ref':SCOPE_REF,'candidate_bindings':c['candidate_bindings'],'candidate_manifest_ref':d['candidate_manifest_ref'],'state_refs':c['model_states'],'source_ready_policy_ids':list(c['candidate_ids']),'runtime_policy_ids':[],'parent_original_failure_refs':d['parent_original_failure_refs'],'new_account_fit_count':0,'source_qualification_ref':d['source_qualification_ref'],'baseline_source_qualification_ref':d['baseline_source_qualification_ref'],'source_gate_level':'REUSED_EXACT_TOP100_BASELINE_PLUS_FIXED_NEW_VERSION_MODEL_AND_INPUT_CUSTODY'}
    if d['research_id']=='A_TOP100_COX_LANDMARK_H5_CONFIRMATION_20261012_R1' and d.get('phase')=='ACCOUNT':
        source=p._document(d['source_prediction_receipt_ref'])
        worker=p._document(source['worker_receipt_ref'])
        source_release=p._document(source['root_source_release_ref'])
        clock_ref=dict(path=str(ROOT/'COX_REUSED_HAZARD_DECISION_INPUT_CLOCK_PROOF_R1.json'),sha256='abd16b2f0fd6ab7036d2d4191c641fa6506b1dafc00730557fda4a7deeeded8a')
        _require(c['inputs'].get('origin_clock_proof_ref')==clock_ref,'COX_FROZEN_DECISION_CLOCK_REF')
        clock=p._document(clock_ref)
        for prediction_ref in source.get('prediction_refs',{}).values():f._physical(prediction_ref)
        provenance['cox_calendar_custody']=_cox_calendar_payload(c,qualification,source,worker,source_release,clock)
    # Canonical authority owner creates custody only after all inherited/new checks.
    return replace(original,allowed_path_ids=c['candidate_ids'],provenance_json=json.dumps(provenance,sort_keys=True,allow_nan=False),runtime_policy_ids=(),source_ready_policy_ids=c['candidate_ids'],_source_policy_custody=f._SourcePolicyCustody(TASK,c['candidate_ids'],f._SEAL))
def contract_for_authority(value):
    p,_=_owners();prov=json.loads(value.provenance_json);c=frozen_contract(prov['remaining10_release_ref'])
    _require(prov.get('research_id')==c['release']['research_id'] and prov.get('remaining10_scope_ref')==SCOPE_REF and prov.get('source_qualification_ref')==c['release']['source_qualification_ref'] and _exact(prov.get('candidate_bindings'),c['candidate_bindings']),'REMAINING10_AUTHORITY_CUSTODY_CHANGED')
    base=p.profile_contract(TASK,pool_variant_id='TOP100',source_execution_context=source_execution_context(c['release']['research_id']))
    metadata={**base['metadata_refs'],'inventory':c['release']['candidate_manifest_ref']}
    return {**base,'metadata_refs':metadata,'candidate_bindings':c['candidate_bindings'],'state_refs':c['model_states'],'remaining10_release_ref':c['release_ref'],'remaining10_research_id':c['release']['research_id']}

def numerical_calendar_capable(value):
    "No IO; only already validated fixed four numerical descendants."
    _,f=_owners();value=f._verified(value)
    science='A_TOP100_SOLVER_CONTINUATION_20261012_R1';ids=VERSIONS[science][0]
    if value.task_id!=TASK or value.allowed_path_ids!=value.source_ready_policy_ids or value.allowed_path_ids!=ids or value.runtime_policy_ids!=ids:
        return False
    provenance=json.loads(value.provenance_json)
    if (provenance.get('schema')!=SCHEMA or provenance.get('research_id')!=science or provenance.get('remaining10_scope_ref')!=SCOPE_REF
            or provenance.get('pool_variant_id')!='TOP100' or provenance.get('new_account_fit_count')!=0
            or type(provenance.get('new_account_fit_count')) is not int or provenance.get('runtime_policy_ids')!=list(ids)
            or provenance.get('source_ready_policy_ids')!=list(ids)):
        return False
    release=provenance.get('remaining10_release_ref',{})
    if (not isinstance(release,dict) or not isinstance(release.get('path'),str) or not release['path']
            or not isinstance(release.get('sha256'),str) or len(release['sha256'])!=64
            or any(c not in '0123456789abcdef' for c in release['sha256'].lower())):
        return False
    rows=provenance.get('candidate_bindings',[]);states=provenance.get('state_refs',{})
    return (isinstance(rows,list) and tuple(r.get('candidate_id') for r in rows)==ids
        and all(r.get('runtime_owner')=='FINAL_ACTION_OVERLAY'
            and r.get('required_action_roles')==['R10:ENTRY','R10:INCUMBENT']
            and r.get('specification',{}).get('candidate_id')==r['candidate_id']
            and r.get('specification',{}).get('research_id')==science
            and r.get('dependency_closure',{}).get('status')=='COMPLETE'
            and bool(r['dependency_closure'].get('state_ids'))
            and set(r['dependency_closure']['state_ids'])<=set(states) for r in rows))


def _cox_ref_valid(value):
    return (isinstance(value,dict) and isinstance(value.get('path'),str) and bool(value['path'])
        and isinstance(value.get('sha256'),str) and len(value['sha256'])==64
        and all(c in '0123456789abcdef' for c in value['sha256']))

def _cox_calendar_payload(c,qualification,source,worker,source_release,clock):
    "Validated canonical model/input custody plus actual SOURCE completion, never a ready flag."
    science='A_TOP100_COX_LANDMARK_H5_CONFIRMATION_20261012_R1';ids=VERSIONS[science][0]
    release=c['release'];inputs=c['inputs'];proofs=inputs.get('action_feature_inputs',{})
    _require(release.get('phase')=='ACCOUNT' and release.get('status')=='ROOT_SINGLE_HEAVY_WORKER_RELEASED'
        and c['version'].get('scientific_specification_sha256')=='a85c80316e41704e3abd02a0e7d2a1921f45fab3b10c6d65ce1935a373d9344c','COX_FIXED_ACCOUNT_CALENDAR_VERSION')
    _require(inputs.get('status')=='METADATA_SEALED_REUSED_ORIGINAL_FORWARD_FEATURES_ROOT_ADMISSION_PENDING'
        and set(proofs)=={'R10:HAZARD'} and inputs.get('label_columns_decoded')==0
        and type(inputs.get('label_columns_decoded')) is int,'COX_REAL_CANONICAL_INPUT_CLOSURE')
    _require(source.get('schema')=='COX_FROZEN_SOURCE_PREDICTION_RECEIPT_R1'
        and source.get('status')=='FROZEN_SOURCE_PREDICTIONS_COMPLETE'
        and source.get('task_id')==TASK and source.get('research_id')==science
        and source.get('candidate_ids')==list(ids) and source.get('new_fit')==0
        and type(source.get('new_fit')) is int and source.get('models_predicted')==3
        and source.get('account_replay')==0 and source.get('label_columns_decoded')==0
        and source.get('original_frozen_proxy_not_actual_account_state') is True,'COX_ACTUAL_SOURCE_COMPLETION_REQUIRED')
    _require(source_release.get('schema')=='REMAINING10_ROOT_ACCOUNT_RELEASE_R1'
        and source_release.get('status')=='ROOT_SINGLE_HEAVY_WORKER_RELEASED'
        and source_release.get('phase')=='SOURCE' and source_release.get('task_id')==TASK
        and source_release.get('research_id')==science and source_release.get('candidate_ids')==list(ids)
        and source_release.get('new_account_fit_count')==0 and source_release.get('selection_using2026') is False,'COX_ACTUAL_SOURCE_ROOT_CUSTODY')
    for key in ('input_closure_ref','model_closure_ref','scope_ref','schedule_ref','source_bundle_ref'):
        _require(source.get(key)==release.get(key)==source_release.get(key) and _cox_ref_valid(release.get(key)),'COX_SOURCE_ACCOUNT_EXACT_ENTITY_CUSTODY')
    _require(source.get('contract_ref')==release.get('version_contract_ref')==source_release.get('version_contract_ref')
        and source_release.get('scope_ref')==SCOPE_REF,'COX_FIXED_SOURCE_ACCOUNT_CONTRACT')
    predictions=source.get('prediction_refs',{})
    _require(worker.get('schema')=='COX_ISOLATED_PREDICTION_COMPLETION_R1'
        and worker.get('research_id')==science and worker.get('models_predicted')==3
        and worker.get('rows_per_model')==645 and worker.get('new_fit')==0
        and type(worker.get('new_fit')) is int and worker.get('account_replay')==0
        and worker.get('prediction_refs')==predictions and set(predictions)==set(ids)
        and all(_cox_ref_valid(r) for r in predictions.values()),'COX_REAL_THREE_NATIVE_PREDICTIONS')
    _require(clock.get('status')=='PASS_REUSED_DECISION_INPUT_STATE_METADATA_ONLY'
        and clock.get('key_semantics')=='DECISION_INPUT_STATE_COMMITMENT'
        and clock.get('fixed_proxy_age_not_actual_account_age') is True
        and clock.get('prior_probe_mature_before_current_decision') is True
        and clock.get('causal_rule')=='previous_probe_mature_date < current_signal_date'
        and source.get('origin_clock_proof_ref')==inputs.get('origin_clock_proof_ref'),'COX_ORIGINAL_SEALED_CLOCK_CUSTODY')
    coverage=release.get('actual_action_packet_coverage')
    _require(isinstance(coverage,dict) and coverage==source.get('coverage')==qualification.get('action_packet_coverage'),'COX_ACTUAL_FULL_SOURCE_COVERAGE')
    return dict(source_status=source['status'],source_prediction_receipt_ref=release['source_prediction_receipt_ref'],source_root_release_ref=source['root_source_release_ref'],worker_receipt_ref=source['worker_receipt_ref'],input_closure_ref=release['input_closure_ref'],model_closure_ref=release['model_closure_ref'],origin_clock_proof_ref=inputs['origin_clock_proof_ref'],action_feature_inputs=proofs,coverage=coverage,computed_signal_dates=clock['computed_signal_dates'],key_sha256=clock['key_sha256'],origin_role_keys=clock['origin_role_keys'],as_of_utc=clock['as_of_utc'],account_phase=release['phase'])

def cox_calendar_capable(value):
    "No IO; only canonically verified full three-Cox model/input/SOURCE custody."
    _,f=_owners();value=f._verified(value)
    science='A_TOP100_COX_LANDMARK_H5_CONFIRMATION_20261012_R1';ids=VERSIONS[science][0]
    if (value.capability!='ACCOUNT' or value.task_id!=TASK
            or value.allowed_path_ids!=value.source_ready_policy_ids or value.allowed_path_ids!=ids or value.runtime_policy_ids!=ids):return False
    try:
        provenance=json.loads(value.provenance_json)
        if (provenance.get('schema')!=SCHEMA or provenance.get('research_id')!=science
                or provenance.get('remaining10_scope_ref')!=SCOPE_REF or provenance.get('pool_variant_id')!='TOP100'
                or provenance.get('new_account_fit_count')!=0 or type(provenance.get('new_account_fit_count')) is not int
                or provenance.get('runtime_policy_ids')!=list(ids) or provenance.get('source_ready_policy_ids')!=list(ids)
                or not _cox_ref_valid(provenance.get('remaining10_release_ref'))):return False
        rows=provenance.get('candidate_bindings',[]);states=provenance.get('state_refs',{});custody=provenance.get('cox_calendar_custody',{})
        if not (isinstance(rows,list) and tuple(r.get('candidate_id') for r in rows)==ids and isinstance(states,dict)
                and set(states)==set(ids) and custody.get('account_phase')=='ACCOUNT'
                and custody.get('source_status')=='FROZEN_SOURCE_PREDICTIONS_COMPLETE'
                and all(_cox_ref_valid(custody.get(k)) for k in ('source_prediction_receipt_ref','source_root_release_ref','worker_receipt_ref','input_closure_ref','model_closure_ref','origin_clock_proof_ref'))):return False
        from datetime import datetime
        cutoff=datetime.fromisoformat('2025-01-01')
        for row in rows:
            cid=row['candidate_id'];state=states[cid];spec=row.get('specification',{});deps=row.get('dependency_closure',{})
            if (row.get('source_group')!='COX_FIXED_NEW_H5_LANDMARK' or row.get('runtime_owner')!='FINAL_ACTION_OVERLAY'
                    or row.get('required_action_roles')!=['R10:HAZARD'] or row.get('lookback')!=5
                    or spec.get('candidate_id')!=cid or spec.get('research_id')!=science
                    or spec.get('scientific_specification_sha256')!='a85c80316e41704e3abd02a0e7d2a1921f45fab3b10c6d65ce1935a373d9344c'
                    or deps.get('status')!='COMPLETE' or deps.get('state_ids')!=[cid]
                    or state.get('candidate_id')!=cid or state.get('component_kind')!='MODEL'
                    or not all(_cox_ref_valid(state.get(k)) for k in ('model_ref','receipt_ref','training_audit_ref','shared_scaler_receipt_ref'))
                    or state.get('fit_or_selection_using2026') is not False or state.get('training_clock_kind')!='OBSERVED_ARRAY_MAX'
                    or state.get('signal_cutoff_exclusive')!='2025-01-01' or state.get('label_maturity_cutoff_exclusive')!='2025-01-01'
                    or not datetime.fromisoformat(state['training_signal_max'])<cutoff
                    or not datetime.fromisoformat(state['training_maturity_max'])<cutoff):return False
        proofs=custody.get('action_feature_inputs',{});coverage=custody.get('coverage',{});dates=custody.get('computed_signal_dates',[])
        if (set(proofs)!= {'R10:HAZARD'} or len(dates)!=193 or dates!=sorted(set(dates)) or dates[0]!='2026-01-02' or dates[-1]!='2026-10-08'
                or any(datetime.fromisoformat(d).date().isoformat()!=d for d in dates)):return False
        proof=proofs['R10:HAZARD'];src=provenance.get('source_refs',{}).get('action_inputs');probe=coverage.get('matured_probe_state',{})
        if (proof.get('status')!='SOURCE_BOUND_COMPLETE_ORIGINAL_COMPUTED_STATE' or proof.get('source_ref')!=src
                or not _cox_ref_valid(proof.get('frame_ref')) or proof.get('prior_probe_mature_before_current_decision') is not True
                or proof.get('commitment',{}).get('rows')!=645 or proof.get('label_columns_decoded')!=0
                or proof.get('new_fit_count')!=0 or proof.get('outcome_columns_in_model_features')!=0
                or coverage.get('source_ref')!=src or coverage.get('candidate_ids')!=list(ids) or coverage.get('decision_dates')!=dates
                or not all(type(coverage.get(k)) is int and coverage[k]==0 for k in ('new_fit_count','future_unmatured_probe_outcomes_read','outcome_columns_in_model_features'))
                or not all(isinstance(coverage.get(k),str) and len(coverage[k])==64 and all(c in '0123456789abcdef' for c in coverage[k]) for k in ('action_packets_sha256','sid_by_key_sha256'))
                or probe.get('source_ref')!=src or probe.get('key_semantics')!='DECISION_INPUT_STATE_COMMITMENT'
                or probe.get('key_sha256')!=custody.get('key_sha256') or probe.get('origin_role_keys')!=custody.get('origin_role_keys')
                or probe.get('origin_clock_proof_ref')!=custody.get('origin_clock_proof_ref')
                or probe.get('causal_rule')!='previous_probe_mature_date < current_signal_date'
                or probe.get('prior_probe_mature_before_current_decision') is not True or probe.get('as_of_utc')!=custody.get('as_of_utc')):return False
        clock=datetime.fromisoformat(probe['as_of_utc'].replace('Z','+00:00'));asof=datetime.fromisoformat(str(value.as_of).replace('Z','+00:00'))
        if clock.tzinfo is None or asof.tzinfo is None or clock>asof:return False
        computed=coverage.get('computed_sessions',{})
        if set(computed)!=set(ids):return False
        for cid in ids:
            if set(computed[cid])!=set(dates):return False
            for row in computed[cid].values():
                count=row.get('proposal_count')
                if type(count) is not int or count<0 or row.get('status')!=('COMPUTED_WITH_PROPOSALS' if count else 'COMPUTED_NO_PROPOSALS'):return False
        return True
    except (KeyError,TypeError,ValueError,AttributeError):return False
