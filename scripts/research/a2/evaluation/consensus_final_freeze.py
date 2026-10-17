"""Exact-task metadata-only closure of completed consensus research receipts.

No estimator, model loading, numeric decoder, selection or test input is called.
The existing source preflight may project only pre2026 identity/calendar metadata.
Only the root's explicit publish action may write the one final system freeze.
That document never grants a 2026 numeric read.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import pandas as pd
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.storage.storage_r2a import write_json_atomic
from scripts.maintenance import consensus100_registry_review as registry
from scripts.research.a2.training import consensus_predictors as predictors, consensus_fusion as fusion, consensus_downstream_run as downstream
from scripts.research.a2.evaluation import consensus_evaluation_run as evaluation

TASK=predictors.TASK
RUN_LEAF='20261011T170254+0000_bf592a79'
EXPECTED_RUN=resolve(predictors.REPO).backtest_root/TASK/RUN_LEAF
FILENAME='CONSENSUS_FINAL_SYSTEM_FREEZE.json'
RECOVERY_DIRECTORY='engineering_recovery/FUSION_PARENT_BOOTSTRAP_R1'
NAMED_MAIN_DIRECTORY='engineering_recovery/FUSION_NAMED_MAIN_R2'
ACCOUNT_RECOVERY_DIRECTORY='engineering_recovery/ACCOUNT_CONTROL_CAP_R3'
SOURCE_ENV_DIRECTORY='engineering_recovery/ACCOUNT_SOURCE_ENVIRONMENT_R4'
SOURCE_ENV_MANIFEST_SHA256='168a76e820823b660d498956e28f5f5c54916c4a4b2c9f5905772a9859a6d15b'
EXACT_CASH_SHA256='8f57a1b233d3b4bc19421724964b9cb4902591ac580412b359fa03347d163f9e'
SOURCE_ENV_OLD_RUNNER_SHA256='b8d008c6855cf2499effcccbaf7324a432b7281b16ca18b7f9f16ed24036968f'
EXACT_CASH_RECOVERED_PATH=resolve(predictors.REPO).cache_root/'V24/V24_B_FAST_TRACK_PAIR_COMPLETION_R1/source_audit/original_frozen'/('joint_cash_bindings_'+EXACT_CASH_SHA256+'.py')
ACCOUNT_RECOVERY_MANIFEST_SHA256='06f998e2adf72c1af0e3065fbe8edfd57872736b7cb7523648295afeb853ded8'
ACCOUNT_SOURCE_CUSTODY_ROOT=resolve(predictors.REPO).results_root/'_maintenance'/TASK/'account_control_cap_recovery/original_sources'
ACCOUNT_OLD_SOURCE_SHA256=dict(evaluation_runner='74894aa22b6e525ba39b6307c9ce5164b40ea3056703d59779fb21c0d3de2030',joint_policy='bda082d6effe1295cb063d60c7cb5b25e2bf8d7d151be9959b7f284ff472024c')
TERMINAL_AUDIT_FILENAME='CONSENSUS_RESEARCH_TERMINAL_AUDIT.json'
NAMED_MAIN_MANIFEST_SHA256='2b92d7a50d6592fb55a8e0637070a4cd299f352ecf9a22bc451acd3ab02efc9c'
RECOVERY_MANIFEST_SHA256='f20df131e57ea3868fdf3f20604cb881a5f2bc6821473dd3cb956a3c38fb2d69'
STATUS='FROZEN_PRE2026_SYSTEM_NO_TEST_READ_AUTHORITY'
TERMINAL={'TRAINED','FAILED','FAILED_NO_RETRY','NOT_TESTABLE'}
values=predictors.values
require=predictors.require

# One bundle per monthly policy state; stage2 LW/cost_aware reuses stage1.
# Every fixed diagnostic can add one final-cutoff state; no annual account reset.
MAX_ACCOUNT_FLOWS=len(evaluation.RECIPE['fusion_methods'])+len(evaluation.RECIPE['stage2'])-1+len(evaluation.RECIPE['diagnostic_sensitivities'])
MAX_FINAL_RISK_STATES=1+len(evaluation.RECIPE['diagnostic_sensitivities'])
MAX_RISK_BUNDLES=MAX_ACCOUNT_FLOWS*12*len(evaluation.YEARS)+MAX_FINAL_RISK_STATES
PER_BUNDLE_METADATA_BYTES=1024  # primary owner: five integer budget keys, optional fixed failure convention, bounded cache-key string
ACCOUNT_METADATA_LIMIT=262144+MAX_RISK_BUNDLES*PER_BUNDLE_METADATA_BYTES
SUMMARY_METADATA_LIMIT=max(32*1024*1024,(MAX_ACCOUNT_FLOWS+1+MAX_FINAL_RISK_STATES)*ACCOUNT_METADATA_LIMIT+262144)


def _run(run):
    run=Path(run).resolve()
    require(run in (EXPECTED_RUN.resolve(),fusion.CONTINUATION_RUN.resolve()),'EXACT_TASK_RUN_REQUIRED')
    assert_safe_output_path(run,kind='backtest',paths=resolve(predictors.REPO))
    require(not any((run/p).exists() for p in ('CONSENSUS_FIT.lock','CONSENSUS_DOWNSTREAM.lock')),'ACTIVE_FIT_OR_DOWNSTREAM_NO_FINAL_FREEZE')
    return run


def _metadata(path,*,summary=False,account=False,continuation=False):
    path=Path(path)
    bundles_limit=MAX_RISK_BUNDLES+(12*len(evaluation.YEARS) if continuation else 0)
    account_limit=262144+bundles_limit*PER_BUNDLE_METADATA_BYTES
    summary_limit=max(SUMMARY_METADATA_LIMIT,(MAX_ACCOUNT_FLOWS+2+MAX_FINAL_RISK_STATES)*account_limit+262144) if continuation else SUMMARY_METADATA_LIMIT
    limit=summary_limit if summary else account_limit if account else 262144
    require(path.is_absolute() and path.resolve(strict=True)==path.absolute()
        and path.stat().st_size<=limit,'BOUNDED_CANONICAL_METADATA_REQUIRED')
    result=json.loads(path.read_text(encoding='utf-8'))
    require(isinstance(result,dict),'METADATA_OBJECT_REQUIRED')
    if account and 'actual_risk_bundle_budgets' in result:
        bundles=result['actual_risk_bundle_budgets']
        require(isinstance(bundles,list) and len(bundles)<=bundles_limit,'FINITE_PRIMARY_BUNDLE_SNAPSHOT_LIMIT')
        require(all(len(json.dumps(b,ensure_ascii=True).encode('utf-8'))<=PER_BUNDLE_METADATA_BYTES for b in bundles),
            'PRIMARY_BUNDLE_METADATA_SCHEMA_SIZE_LIMIT')
    return result


def _ref(path):return dict(path=str(Path(path)),sha256=values.sha(path))


def _pin(record,expected=None):
    path=Path(record['path'])
    require(path.is_absolute() and path.resolve(strict=True)==path.absolute(),'CANONICAL_REFERENCE_REQUIRED')
    require(expected is None or path==expected,'REFERENCE_PATH_CHANGED')
    require(values.sha(path)==record['sha256'],'REFERENCE_BYTES_CHANGED:'+str(path))
    return path


def _pin_tree(node):
    if isinstance(node,dict):
        if 'path' in node and 'sha256' in node:_pin(node)
        for value in node.values():_pin_tree(value)
    elif isinstance(node,list):
        for value in node:_pin_tree(value)


def _account_source_custody(freeze_ref,scope_ref,*,continuation=False):
    # The canonical owner alone authenticates exact fe3 CA and1775/8a code-byte
    # transports. Historical declarations are never treated as live producers.
    bound=evaluation.account_inputs.metadata_preflight(frozen_contract_ref=freeze_ref,source_scope_ref=scope_ref)
    require(bound['frozen_contract_ref']==freeze_ref and bound['source_scope_ref']==scope_ref
        and bound['numeric_prices_read'] is False and bound['quote_numeric_evidence_read'] is False,
        'SOURCE_METADATA_ONLY_PREFLIGHT_REQUIRED')
    scope=bound['scope'];physical={}
    for path,expected in bound['physical_stats'].items():
        path=Path(path);stat=path.stat()
        require(dict(size=stat.st_size,mtime_ns=stat.st_mtime_ns)==expected,'ACCOUNT_SOURCE_PHYSICAL_STATS_CHANGED')
        physical[str(path)]=_ref(path)
        stat=path.stat();require(dict(size=stat.st_size,mtime_ns=stat.st_mtime_ns)==expected,'ACCOUNT_SOURCE_CHANGED_DURING_HASH')
    # These current physical entrypoints were also checked by the source owner;
    # ADV is the separately pinned feature source used by the frozen evaluator.
    for name in ('pool_ref','calendar_ref','settlement_calendar_ref','signal_adv_source_ref','signal_quote_domain_ref'):
        record=scope.get(name)
        if record is not None:
            path=bound['pin'](record);physical[str(path)]=dict(path=str(path),sha256=record['sha256'])
    result=dict(physical_or_frozen_custody_refs=[physical[p] for p in sorted(physical)],
        construction_transport_proof=bound['metadata_proofs']['source_fact_construction_transport'],
        historical_transport_declarations={name:scope.get(name) for name in ('legacy_source_transport','source_fact_construction_transport','signal_quote_legacy_source_transport')},
        historical_ref_role='SOURCE_FACT_DECLARATIONS_NOT_CURRENT_PRODUCERS',
        qualification_owner='consensus_account_inputs.metadata_preflight',numeric_prices_read=False,quote_numeric_evidence_read=False)
    if continuation:
        require(bound.get('source_completion') is not None,'CANONICAL_SOURCE_COMPLETION_PREFLIGHT_REQUIRED')
        result.update(source_dependency_custody_proof=bound.get('source_dependency_custody_proof'),
            source_completion_manifest_ref=bound['source_completion']['manifest_ref'],
            historical_dependency_declarations=scope.get('source_dependency_custody'))
    return result


def _clocks(reuse,year):
    cut=pd.Timestamp(f'{year}-01-01');sessions=pd.DatetimeIndex(reuse['calibration_sessions'])
    require(reuse['task_id']==TASK and len(sessions)==60 and sessions.is_unique and sessions.is_monotonic_increasing
        and sessions.max()<cut<=pd.Timestamp('2026-01-01')
        and pd.Timestamp(reuse['train_maturity_exclusive'])==sessions[0]
        and pd.Timestamp(reuse['calibration_maturity_exclusive'])==cut,'PRE2026_MATURE_CHRONOLOGICAL_CALIBRATION_REQUIRED')


def _progress(run,path,slots,keys):
    progress=_metadata(run/path)
    require(progress['status']=='COMPLETED_ALL_FIXED_SLOTS'
        and progress['slots_complete']==progress['total_slots']==len(slots)
        and progress['test_2026_content_read'] is False,'ALL_FIXED_SLOTS_TERMINAL_REQUIRED')
    require([{k:r[k] for k in keys} for r in progress['rows']]==[{k:s[k] for k in keys} for s in slots],
        'FIXED_SLOT_DISPOSITIONS_CANNOT_SHRINK')
    return progress['rows'],_ref(run/path)


def _fitted(run,slot,frozen,freeze_ref,kind,*,publication_run=None):
    if kind=='predictor':
        model,year,h=slot['model_id'],slot['year'],slot['horizon']
        _,rp,mp,cp=predictors.slot_paths(run,model,year,h)
    else:
        model,year=slot['method'],slot['year'];_,rp,mp=fusion.slot_paths(run,slot['packet_id'],model,year)
    receipt=_metadata(rp);status=receipt['status']
    require(status in TERMINAL,'NONTERMINAL_MODEL_RECEIPT')
    require((receipt['model_id'],receipt['year'])==(model,year) and receipt['source_pins']==frozen['source_pins'],
        'FIT_RECEIPT_IDENTITY_OR_SOURCE_CHANGED')
    require(kind!='predictor' or receipt['horizon']==h,'PREDICTOR_HORIZON_CHANGED')
    require(kind!='fusion' or receipt['packet_id']==slot['packet_id'],'FUSION_PACKET_CHANGED')
    artifacts={};reuse=receipt.get('reuse_tuple')
    if reuse is not None:
        require(receipt['reuse_tuple_sha256']==values.digest(reuse) and reuse['freeze_ref']==freeze_ref
            and reuse['source_pins']==frozen['source_pins'],'FITTED_REUSE_CUSTODY_CHANGED')
        _clocks(reuse,year)
        require((reuse['model_id'],reuse['year'])==(model,year),'REUSE_SLOT_IDENTITY_CHANGED')
        if kind=='predictor':
            require(reuse['horizon']==h and reuse['authorized_spec']==frozen['authorized_spec']
                and reuse['input_binding_sha256']==frozen['input_binding_sha256']
                and reuse['membership_sha256']==frozen['membership_sha256'],'PREDICTOR_INPUT_ORIGIN_CHANGED')
        else:require(reuse['packet_id']==slot['packet_id'] and reuse['predictor_freeze_ref']==frozen['predictor_freeze_ref'],
            'FUSION_INPUT_ORIGIN_CHANGED')
    else:require(kind=='fusion' and status=='NOT_TESTABLE' and receipt['freeze_ref']==freeze_ref,'MISSING_FIT_CUSTODY')
    if status=='TRAINED':
        require(reuse is not None,'TRAINED_REUSE_REQUIRED')
        artifacts['model']=dict(path=str(mp),sha256=receipt['model_sha256']);_pin(artifacts['model'])
        if kind=='predictor':
            artifacts['calibration']=dict(path=str(cp),sha256=receipt['calibration_predictions_sha256']);_pin(artifacts['calibration'])
        else:
            require(reuse['members']==slot['members'],'FUSION_MEMBERS_CANNOT_SHRINK')
            evaluation.validate_past_publication_pins(run if publication_run is None else publication_run,slot['members'],year,reuse['past_publication_pins'])
    return dict(slot=slot,status=status,receipt=_ref(rp),artifacts=artifacts),receipt




def _log_prefix_sha(path,size):
    digest=hashlib.sha256();remaining=size
    with Path(path).open('rb') as stream:
        while remaining:
            chunk=stream.read(min(65536,remaining));require(bool(chunk),'RECOVERY_LOG_PREFIX_TRUNCATED')
            digest.update(chunk);remaining-=len(chunk)
    return digest.hexdigest()


def _log_snapshot_prefix(current_ref,snapshot_ref):
    # A completed downstream job records the log before account FITs append.
    # Authenticate its hash at raw JSONL boundaries; never decode past rows.
    path=_pin(current_ref)
    require(Path(snapshot_ref['path'])==path,'RECOVERY_LOG_SNAPSHOT_PATH_CHANGED')
    digest=hashlib.sha256();size=0
    with path.open('rb') as stream:
        while True:
            line=stream.readline(65537)
            if not line:break
            require(len(line)<=65536 and line.endswith(b'\n'),'BOUNDED_RECOVERY_LOG_RECORD_REQUIRED')
            digest.update(line);size+=len(line)
            if digest.hexdigest()==snapshot_ref['sha256']:return size
    require(False,'RECOVERY_DOWNSTREAM_LOG_SNAPSHOT_NOT_PRESERVED')




def _source_environment_authority(run,cap_manifest,cap_ref):
    base=run/SOURCE_ENV_DIRECTORY;path=base/'SOURCE_ENVIRONMENT_RECOVERY_MANIFEST_R4.json'
    if not path.exists():
        require(not base.exists(),'SOURCE_ENVIRONMENT_MANIFEST_MISSING');return None
    ref=dict(path=str(path),sha256=SOURCE_ENV_MANIFEST_SHA256);_pin(ref,path);m=_metadata(path)
    require(m['schema']=='CONSENSUS_ACCOUNT_EXACT_SOURCE_ENVIRONMENT_RECOVERY_R4'
        and m['status']=='ROOT_AUTHORIZED_EXACT_FROZEN_SOURCE_ENVIRONMENT_REPAIR' and m['task_id']==TASK and Path(m['run'])==run
        and m['account_cap_recovery_manifest_ref']==cap_ref and m['root_engineering_attempt']==4
        and m['canonical_source_bootstrap_at_module_top_level'] is True and m['failed_previous_job_additional_fit_units']==0
        and all(m[k] is False for k in ('fit_log_reset','fixed_recipe_changed','source_policy_changed','data_or_clock_changed',
            'native_scientific_retries','selection_feedback','predictor_fusion_auxiliary_refit','test_2026_read_authorized')),
        'EXACT_NO_FIT_SOURCE_ENVIRONMENT_RECOVERY_REQUIRED')
    transport=m['exact_source_transport'];canonical='scripts.research.a2.data.joint_cash_bindings'
    original=transport['original_ref'];custody=transport['custody_ref'];recovered=transport['recovered_original_ref']
    require(transport['schema']=='EXACT_BYTE_CANONICAL_MODULE_TRANSPORT_R1' and transport['canonical_module']==canonical
        and transport['original_bytes_unchanged'] is True and transport['current_project_file_modified'] is False
        and transport['data_clock_changed'] is False and transport['source_vintage_changed'] is False
        and Path(original['path'])==predictors.REPO/'scripts/research/a2/data/joint_cash_bindings.py'
        and original['sha256']==custody['sha256']==recovered['sha256']==EXACT_CASH_SHA256,'ONLY_EXACT_8F_SOURCE_TRANSPORT_ALLOWED')
    _pin(custody,run/'source_custody/joint_cash_bindings_8f57_source.py');_pin(recovered,EXACT_CASH_RECOVERED_PATH)
    fields=('account_cap_recovery_manifest_ref','failed_previous_account_job_ref','old_source_scope_ref','new_source_scope_ref',
        'old_account_freeze_ref','new_account_freeze_ref','old_runner_custody_ref','metadata_preflight_ref','named_main_launcher_ref','before_account_fit_log_ref')
    require(m['required_immutable_refs']==[m[k] for k in fields]+[custody,recovered],'EXACT_TWELVE_SOURCE_ENV_CUSTODY_REFS_REQUIRED')
    _pin_tree(m['required_immutable_refs'])
    require(m['current_evaluation_source_pins']==evaluation.source_pins(),'SOURCE_ENV_CURRENT_PRODUCERS_CHANGED');_pin_tree(m['current_evaluation_source_pins'])
    old_runner=m['old_runner_source_ref'];archive=m['old_runner_custody_ref']
    require(old_runner==cap_manifest['current_evaluation_source_pins']['runner'] and Path(old_runner['path'])==Path(evaluation.__file__)
        and old_runner['sha256']==archive['sha256']==SOURCE_ENV_OLD_RUNNER_SHA256,'HISTORICAL_R2_RUNNER_IDENTITY_CHANGED')
    _pin(archive,ACCOUNT_SOURCE_CUSTODY_ROOT/'evaluation_runner_before_source_environment_r4.py')
    require(Path(archive['path']).stat().st_size<=65536 and Path(evaluation.__file__).stat().st_size<=65536,'BOUNDED_RUNNER_SOURCE_BYTES_REQUIRED')
    old_bytes=Path(archive['path']).read_bytes();fragment=b"FREEZE='CONSENSUS_ACCOUNT_EVALUATION_FREEZE_R2.json'"
    require(old_bytes.count(fragment)==1
        and old_bytes.replace(fragment,b"FREEZE='CONSENSUS_ACCOUNT_EVALUATION_FREEZE_R3.json'",1)==Path(evaluation.__file__).read_bytes(),
        'RUNNER_SOURCE_ENV_DELTA_MUST_ONLY_CHANGE_FREEZE_FILENAME')
    require({k:v for k,v in cap_manifest['current_evaluation_source_pins'].items() if k!='runner'}
        =={k:v for k,v in m['current_evaluation_source_pins'].items() if k!='runner'},'OTHER_ACCOUNT_PRODUCERS_CANNOT_CHANGE')
    _pin(m['old_source_scope_ref'],run/'ACCOUNT_SOURCE_SCOPE.json');_pin(m['new_source_scope_ref'],run/'ACCOUNT_SOURCE_SCOPE_R2.json')
    old_scope=_metadata(m['old_source_scope_ref']['path']);new_scope=_metadata(m['new_source_scope_ref']['path'])
    require(new_scope.pop('executable_source_transport')==transport
        and old_scope['source_dependency_refs']['joint_cash_bindings']==original
        and new_scope['source_dependency_refs']['joint_cash_bindings']==custody,'SOURCE_SCOPE_EXACT_TRANSPORT_REQUIRED')
    new_scope['source_dependency_refs']['joint_cash_bindings']=original
    require(new_scope==old_scope,'SOURCE_SCOPE_MAY_ONLY_TRANSPORT_EXECUTABLE_PATH')
    require(m['old_account_freeze_ref']==cap_manifest['new_account_freeze_ref'],'R2_ACCOUNT_FREEZE_HISTORY_CHANGED')
    _pin(m['old_account_freeze_ref'],run/'CONSENSUS_ACCOUNT_EVALUATION_FREEZE_R2.json');_pin(m['new_account_freeze_ref'],run/evaluation.FREEZE)
    old_freeze=_metadata(m['old_account_freeze_ref']['path']);new_freeze=_metadata(m['new_account_freeze_ref']['path'])
    require(old_freeze['account_source_scope_ref']==m['old_source_scope_ref'] and new_freeze['account_source_scope_ref']==m['new_source_scope_ref']
        and new_freeze['previous_account_freeze_ref']==m['old_account_freeze_ref'] and 'source_environment_revision' in new_freeze,
        'SOURCE_ENV_FREEZE_SCOPE_LINEAGE_REQUIRED')
    normalized=dict(new_freeze);normalized.pop('source_environment_revision');normalized['previous_account_freeze_ref']=old_freeze['previous_account_freeze_ref']
    normalized['account_source_scope_ref']=old_freeze['account_source_scope_ref'];normalized['source_pins']=dict(new_freeze['source_pins'])
    normalized['source_pins']['runner']=old_freeze['source_pins']['runner']
    require(normalized==old_freeze,'SOURCE_ENV_FREEZE_MAY_ONLY_BIND_FILENAME_SCOPE_PATH_AND_RUNNER_LINEAGE')
    old_job_path=run/ACCOUNT_RECOVERY_DIRECTORY/'ACCOUNT_JOB_R3.json';_pin(m['failed_previous_account_job_ref'],old_job_path);job=_metadata(old_job_path)
    require(job['status']=='FAILED_NO_RESTART' and job['task_id']==TASK and Path(job['run'])==run and job['manifest_ref']==cap_ref
        and job['root_engineering_attempt']==3 and job['account_freeze_ref']==m['old_account_freeze_ref']
        and job['test_2026_read_authorized'] is False and job['failure']==dict(type='ValueError',message='ACCOUNT_SOURCE_CUSTODY_CHANGED:'+str(Path(original['path']))),
        'FAILED_R3_SOURCE_GATE_JOB_MUST_REMAIN_FAILED')
    _pin(m['before_account_fit_log_ref'],base/'before_account_FIT_LOG.jsonl');_pin(m['before_source_gate_fit_log_ref'],run/ACCOUNT_RECOVERY_DIRECTORY/'FIT_LOG.jsonl')
    require(m['before_source_gate_fit_log_ref']==cap_manifest['old_fit_log_ref']
        and m['before_account_fit_log_ref']['sha256']==m['before_source_gate_fit_log_ref']['sha256']==m['before_account_fit_log_ref_current']['sha256']
        and Path(m['before_account_fit_log_ref_current']['path'])==run/'FIT_LOG.jsonl','FAILED_SOURCE_GATE_MUST_ADD_ZERO_FIT_BYTES')
    current_cash=evaluation.account_inputs.existing.source.cash
    require(current_cash.__name__==canonical and Path(current_cash.__file__)==Path(custody['path']),
        'ROOT_MUST_CANONICAL_BOOTSTRAP_EXACT_8F_BEFORE_BUILDER')
    proof=_metadata(m['metadata_preflight_ref']['path'])
    def same_ref(a,b):return Path(a['path'])==Path(b['path']) and a['sha256']==b['sha256']
    require(proof['status']=='PASS_ACTUAL_R4_HELPER_PARENT_AND_SPAWN_PLUS_METADATA_ONLY' and proof['task_id']==TASK
        and same_ref(proof['scope_ref'],m['new_source_scope_ref']) and same_ref(proof['evaluation_freeze_ref'],m['new_account_freeze_ref'])
        and proof['metadata_only']['status']=='PASS' and proof['metadata_only']['numeric_prices_read'] is False
        and proof['metadata_only']['quote_numeric_evidence_read'] is False
        and all(proof['boundaries'][k] is False for k in ('load_account_inputs_called','real_prices_decoded','real_features_or_labels_read','real_2026_read','fits_started')),
        'EXACT_HELPER_PARENT_SPAWN_METADATA_PREFLIGHT_REQUIRED')
    identity=proof['actual_helper_identity']
    require(identity['fresh_named_process'] is True and identity['bootstrap_executed_once_per_process'] is True
        and identity['actual_helper_main_called'] is False and identity['synthetic_empty_dataclass_roundtrip'] is True,
        'SOURCE_ENV_FRESH_PROCESS_ROUNDTRIP_REQUIRED')
    for key in ('parent','spawn_child'):
        record=identity[key]
        require(same_ref(record['actual_helper_ref'],m['named_main_launcher_ref']) and same_ref(record['cash_source_ref'],custody)
            and all(record[k] is True for k in ('canonical_single_bootstrap','scope_dep_matches_owner_path','e_reader_same_module',
                'existing_source_cash_same_object','d456_fact_owner_cash_same_object','private_factory_cash_same_object','package_and_sysmodules_same_object','ca_class_namespace_shared'))
            and record['actual_helper_main_called'] is False and record['actual_data_load_or_fit_called'] is False,
            'SOURCE_ENV_ACTUAL_PARENT_AND_CHILD_CANONICAL_IDENTITY_REQUIRED')
    return dict(manifest=m,manifest_ref=ref,exact_source_transport=transport,
        historical_role='ORIGINAL_SOURCE_CURRENT_LOG_AND_OLD_RUNNER_DECLARATIONS_AUTHENTICATED_BY_EXACT_CUSTODY_AND_LOG_PREFIX')


def _account_recovery_authority(run):
    base=run/ACCOUNT_RECOVERY_DIRECTORY;path=base/'ACCOUNT_RECOVERY_MANIFEST_R3.json'
    if not path.exists():
        require(not base.exists(),'ACCOUNT_RECOVERY_MANIFEST_MISSING')
        return None
    manifest_ref=dict(path=str(path),sha256=ACCOUNT_RECOVERY_MANIFEST_SHA256);_pin(manifest_ref,path);m=_metadata(path)
    require(m['schema']=='CONSENSUS_ACCOUNT_DECLARED_CAP_ENGINEERING_RECOVERY_R3'
        and m['status']=='ROOT_AUTHORIZED_EXISTING_CAP_EXECUTION_REPAIR' and m['task_id']==TASK and Path(m['run'])==run
        and m['root_engineering_attempt']==3 and m['recipe_unchanged'] is True and m['source_scope_unchanged'] is True
        and all(m[k] is False for k in ('fit_log_reset','model_selection_feedback_from_failure','predictor_fusion_auxiliary_refit','test_2026_read_authorized'))
        and m['engineering_scope']=='ENFORCE_EXISTING_EXPLICIT_10_PERCENT_TARGET_CAP_AFTER_FIXED_CONTROLS_NO_SELECTOR_OR_RECIPE_CHANGE',
        'EXACT_EXISTING_CAP_ACCOUNT_RECOVERY_REQUIRED')
    source=m['source_custody'];require(set(source)==set(ACCOUNT_OLD_SOURCE_SHA256),'EXACT_TWO_HISTORICAL_SOURCE_ROLES_REQUIRED')
    roles=dict(evaluation_runner=(Path(evaluation.__file__),'evaluation_runner_before_freeze_r2.py'),
        joint_policy=(Path(evaluation.joint.__file__),'joint_policy_before_cap_fix.py'))
    for role,(original_path,name) in roles.items():
        old=source[role]['original_ref'];archive=source[role]['archived_ref']
        require(Path(old['path'])==original_path and old['sha256']==archive['sha256']==ACCOUNT_OLD_SOURCE_SHA256[role],
            'HISTORICAL_ACCOUNT_SOURCE_IDENTITY_CHANGED')
        _pin(archive,ACCOUNT_SOURCE_CUSTODY_ROOT/name)  # original_ref is a fact, never a live producer pin.
    environment=_source_environment_authority(run,m,manifest_ref)
    if environment is None:
        require(m['current_evaluation_source_pins']==evaluation.source_pins(),'CURRENT_ACCOUNT_RECOVERY_SOURCE_CHANGED')
        _pin_tree(m['current_evaluation_source_pins'])
    else:
        _pin_tree({k:v for k,v in m['current_evaluation_source_pins'].items() if k!='runner'})
    old_ref=m['old_account_freeze_ref'];archived_ref=m['archived_old_account_freeze_ref'];new_ref=m['new_account_freeze_ref']
    _pin(old_ref,run/'CONSENSUS_ACCOUNT_EVALUATION_FREEZE.json');_pin(archived_ref,base/'CONSENSUS_ACCOUNT_EVALUATION_FREEZE.json')
    _pin(new_ref,Path(environment['manifest']['old_account_freeze_ref']['path']) if environment is not None else run/evaluation.FREEZE)
    require(old_ref['sha256']==archived_ref['sha256'],'ORIGINAL_ACCOUNT_FREEZE_ARCHIVE_CHANGED')
    old=_metadata(old_ref['path']);new=_metadata(new_ref['path'])
    require(old['recipe']==new['recipe'] and old['account_source_scope_ref']==new['account_source_scope_ref'],
        'ACCOUNT_RECIPE_OR_SOURCE_SCOPE_CHANGED')
    fields=('old_account_freeze_ref','archived_old_account_freeze_ref','new_account_freeze_ref','old_account_job_ref',
        'old_account_job_before_stop_ref','stop_evidence_ref','old_fit_log_ref','named_main_launcher_ref','policy_preflight_ref','policy_independent_review_ref')
    receipts=m['old_account_receipts'];flows=[evaluation.flow_id(x) for x in ('equal','fixed_weight','median')]
    require([r['flow_id'] for r in receipts]==flows,'EXACT_THREE_ORIGINAL_ACCOUNT_FLOWS_REQUIRED')
    artifact_names=('accounting_exceptions','daily','diagnostics','entitlements','execution_results','fills','orders','positions','settlement_ledger','state')
    expected_artifacts=[['state'],[],list(artifact_names)]
    refs=[m[k] for k in fields]+[source[k]['archived_ref'] for k in sorted(source)]+[r['receipt_ref'] for r in receipts]
    for r,names in zip(receipts,expected_artifacts):
        require(sorted(r['artifact_refs'])==sorted(r['artifact_custody'])==names,'ORIGINAL_ACCOUNT_ARTIFACT_ROLES_CHANGED')
        for name in names:
            custody=r['artifact_custody'][name];filename=name+('.joblib' if name=='state' else '.parquet')
            require(custody['original_ref']==r['artifact_refs'][name]
                and Path(custody['original_ref']['path'])==run/'evaluation/consensus_account'/r['flow_id']/filename
                and custody['original_ref']['sha256']==custody['archived_ref']['sha256'],'ORIGINAL_ACCOUNT_ARTIFACT_IDENTITY_CHANGED')
            _pin(custody['archived_ref'],base/'first_account_flows'/r['flow_id']/filename);refs.append(custody['archived_ref'])
    require(len(refs)==26 and m['required_immutable_refs']==refs,'EXACT_26_ACCOUNT_RECOVERY_CUSTODY_REFS_REQUIRED');_pin_tree(refs)
    statuses=['FAILED_NO_RETRY','IN_PROGRESS','NOT_TESTABLE'];units=[66,0,12]
    failures=[dict(type='ValueError',reason='invalid explicit target weights'),None,dict(type='NotTestable',reason='ACCOUNT_CORPORATE_LIFECYCLE_UNQUALIFIED')]
    for r,status,fit_units,failure in zip(receipts,statuses,units,failures):
        path=base/'first_account_flows'/r['flow_id']/'receipt.json';_pin(r['receipt_ref'],path);arch=_metadata(path,account=True)
        require(r['status']==arch['status']==status and r['fit_units']==arch['fit_units']==fit_units
            and r['failure']==arch.get('failure')==failure and r['identity_sha256']==arch['identity_sha256']
            and arch['task_id']==TASK and arch['flow_id']==r['flow_id'] and arch['freeze_ref']==old_ref
            and Path(arch['receipt_path'])==run/'evaluation/consensus_account'/r['flow_id']/'receipt.json'
            and arch['artifacts']==r['artifact_refs'],'ORIGINAL_ACCOUNT_FAILURE_OR_CUSTODY_CHANGED')
    require(m['archived_risk_fit_units']==sum(units)==78,'ORIGINAL_78_RISK_FIT_UNITS_MUST_REMAIN')
    old_job_path=run/'logs/ACCOUNT_EVALUATION_NAMED_MAIN_R2.json';_pin(m['old_account_job_ref'],old_job_path);job=_metadata(old_job_path)
    require(job['status']=='FAILED_NO_RESTART' and job['task_id']==TASK and Path(job['run'])==run
        and job['test_2026_read_authorized'] is False and job['terminated_between_native_workers'] is True
        and job['previous_state_ref']==m['old_account_job_before_stop_ref']
        and job['failure']==dict(type='ConfirmedEngineeringFailure',message='PARTIAL_REBALANCING_REINTRODUCES_WEIGHT_ABOVE_DECLARED_10_PERCENT_CAP'),
        'ORIGINAL_ACCOUNT_CAP_FAILURE_MUST_REMAIN')
    _pin(job['upstream_recovery_job_ref'],run/NAMED_MAIN_DIRECTORY/'RECOVERY_JOB_R2.json')
    _pin(m['old_account_job_before_stop_ref'],base/'FIRST_ACCOUNT_JOB_BEFORE_STOP.json')
    _pin(m['stop_evidence_ref'],base/'STOP_AND_SOURCE_CUSTODY.json');stop=_metadata(m['stop_evidence_ref']['path'])
    require(stop['status']=='CONFIRMED_CONTROL_CAP_ENGINEERING_FAILURE_PRESERVED' and stop['terminated_between_native_workers'] is True
        and stop['parent_pid']==job['verified_terminated_parent_pid']>0 and stop['old_account_job_ref']==m['old_account_job_ref']
        and stop['old_account_freeze_ref']==archived_ref and stop['old_fit_log_ref']==m['old_fit_log_ref']
        and stop['source_custody']==source and stop['predictor_fusion_auxiliary_refit'] is False
        and stop['fit_log_reset'] is False and stop['test_2026_content_read'] is False,'ACCOUNT_STOP_AND_HISTORICAL_CUSTODY_REQUIRED')
    preflight=_metadata(m['policy_preflight_ref']['path']);review=_metadata(m['policy_independent_review_ref']['path']);policy=m['current_evaluation_source_pins']['joint_policy']
    for item in (preflight,review):
        require(item['task_id']==TASK and Path(item['source_ref']['path'])==Path(policy['path']) and item['source_ref']['sha256']==policy['sha256'],
            'CAP_REPAIR_REVIEW_SOURCE_CHANGED')
    require(preflight['status']=='PASS_SYNTHETIC_ONLY_PENDING_INDEPENDENT_REVIEW' and review['status']=='PASS_WITH_SCOPE_LIMITS'
        and review['engineering_receipt_ref']==m['policy_preflight_ref'] and review['real_2026_data_or_observations_read'] is False
        and review['actual_fit_or_replay_by_reviewer'] is False,'INDEPENDENT_SYNTHETIC_CAP_REPAIR_REVIEW_REQUIRED')
    return dict(manifest=m,manifest_ref=manifest_ref,source_environment=environment,historical_source_custody=source,
        historical_reference_role='ORIGINAL_SOURCE_AND_ARTIFACT_FACTS_AUTHENTICATED_BY_ARCHIVED_BYTES_NOT_CURRENT_PRODUCERS')


def _account_recovery_history(run,authority,freeze_ref,summary,summary_ref,fit_log_ref):
    if authority is None:return None
    m=authority['manifest'];base=run/ACCOUNT_RECOVERY_DIRECTORY
    environment=authority['source_environment']
    expected_freeze=environment['manifest']['new_account_freeze_ref'] if environment is not None else m['new_account_freeze_ref']
    require(expected_freeze==freeze_ref,'NEW_ACCOUNT_FREEZE_NOT_BOUND_TO_RECOVERY')
    old_log=m['old_fit_log_ref'];_pin(old_log,base/'FIT_LOG.jsonl');old_size=Path(old_log['path']).stat().st_size
    require(0<old_size<=Path(fit_log_ref['path']).stat().st_size and _log_prefix_sha(fit_log_ref['path'],old_size)==old_log['sha256'],
        'ACCOUNT_PRIOR_FIT_LOG_PREFIX_CHANGED')
    path=run/SOURCE_ENV_DIRECTORY/'ACCOUNT_JOB_R4.json' if environment is not None else base/'ACCOUNT_JOB_R3.json';job=_metadata(path)
    execution=environment['manifest'] if environment is not None else m
    execution_ref=environment['manifest_ref'] if environment is not None else authority['manifest_ref']
    require(job['status']=='COMPLETED' and job['task_id']==TASK and Path(job['run'])==run
        and job['manifest_ref']==execution_ref and job['root_engineering_attempt']==(4 if environment is not None else 3)
        and job['account_freeze_ref']==freeze_ref and job['named_main_launcher_ref']==execution['named_main_launcher_ref']
        and job['test_2026_read_authorized'] is False and job['summary_ref']==summary_ref
        and job['scientific_result_status']==summary['status'] and job['final_fit_log_ref']==fit_log_ref,
        'ACCOUNT_RECOVERY_JOB_SUCCESSFUL_TERMINAL_REQUIRED')
    source_environment=None
    if environment is not None:
        env=environment['manifest'];prefix_ref=env['before_account_fit_log_ref'];prefix_size=Path(prefix_ref['path']).stat().st_size
        require(_log_prefix_sha(fit_log_ref['path'],prefix_size)==prefix_ref['sha256']
            and job['source_scope_ref']==env['new_source_scope_ref'] and job['executable_source_ref']==env['exact_source_transport']['custody_ref']
            and job['predictor_fusion_auxiliary_refit'] is False,'SOURCE_ENV_EXECUTION_OR_LOG_PREFIX_CHANGED')
        source_environment=dict(manifest_ref=environment['manifest_ref'],account_job_ref=_ref(path),
            failed_previous_account_job_ref=env['failed_previous_account_job_ref'],old_account_freeze_ref=env['old_account_freeze_ref'],
            new_account_freeze_ref=freeze_ref,old_source_scope_ref=env['old_source_scope_ref'],new_source_scope_ref=env['new_source_scope_ref'],
            old_runner_source_ref=env['old_runner_source_ref'],old_runner_custody_ref=env['old_runner_custody_ref'],
            exact_source_transport=environment['exact_source_transport'],metadata_preflight_ref=env['metadata_preflight_ref'],
            named_main_launcher_ref=env['named_main_launcher_ref'],before_account_fit_log_ref=prefix_ref,
            before_account_fit_log_ref_current=env['before_account_fit_log_ref_current'],historical_role=environment['historical_role'],
            source_gate_additional_fit_units=0,foreign_project_source_observation=env['foreign_project_source_observation'],test_2026_read_authorized=False)
    return dict(manifest_ref=authority['manifest_ref'],account_job_ref=_ref(path),old_account_job_ref=m['old_account_job_ref'],
        old_account_job_before_stop_ref=m['old_account_job_before_stop_ref'],stop_evidence_ref=m['stop_evidence_ref'],
        old_account_freeze_ref=m['old_account_freeze_ref'],archived_old_account_freeze_ref=m['archived_old_account_freeze_ref'],new_account_freeze_ref=freeze_ref,
        historical_source_custody=authority['historical_source_custody'],historical_reference_role=authority['historical_reference_role'],source_environment=source_environment,
        original_account_dispositions=m['old_account_receipts'],archived_risk_fit_units=78,old_fit_log_ref=old_log,final_fit_log_ref=fit_log_ref,
        named_main_launcher_ref=execution['named_main_launcher_ref'],original_cap_launcher_ref=m['named_main_launcher_ref'],policy_preflight_ref=m['policy_preflight_ref'],policy_independent_review_ref=m['policy_independent_review_ref'],
        predictor_fusion_auxiliary_refit=False,selection_feedback=False,test_2026_read_authorized=False,own_account_launcher_terminated_between_native_workers=True)


def _named_main_correction(run,original,original_ref,frozen,slots,account_authority=None):
    base=run/NAMED_MAIN_DIRECTORY;path=base/'LAUNCHER_CORRECTION_MANIFEST_R2.json'
    if not path.exists():
        require(not base.exists(),'NAMED_MAIN_CORRECTION_MANIFEST_MISSING')
        return None
    manifest_ref=dict(path=str(path),sha256=NAMED_MAIN_MANIFEST_SHA256);_pin(manifest_ref,path)
    m=_metadata(path)
    require(m['schema']=='CONSENSUS_FUSION_NAMED_MAIN_ENGINEERING_CORRECTION_R2'
        and m['status']=='ROOT_AUTHORIZED_NAMED_MAIN_CALLER_CORRECTION'
        and m['task_id']==TASK and Path(m['run'])==run and m['root_engineering_attempt']==2
        and m['original_recovery_manifest_ref']==original_ref and m['source_pins']==frozen['source_pins']
        and m['engineering_retry_slots']==original['engineering_retry_slots']
        and m['test_2026_read_authorized'] is False
        and m['source_spec_seed_parameters_data_sampling_selection_rule_changed'] is False
        and m['additional_scientific_retries_authorized'] is False
        and m['stdin_recovery_extra_attempt_started_events']==1 and m['stdin_recovery_native_fit_started_events']==0,
        'EXACT_UNFITTED_NAMED_MAIN_CORRECTION_REQUIRED')
    fields=('original_recovery_manifest_ref','failed_stdin_recovery_job_ref','failed_account_wait_job_ref','named_main_launcher_ref',
        'first_stdin_progress_ref','first_stdin_fit_log_ref','stop_evidence_ref','unfitted_spawn_receipt_ref')
    require(m['required_immutable_refs']==[m[k] for k in fields],'EXACT_EIGHT_CORRECTION_CUSTODY_REFS_REQUIRED')
    _pin_tree(m['required_immutable_refs']);_pin_tree(m['source_pins'])
    failed_path=run/RECOVERY_DIRECTORY/'RECOVERY_JOB.json';_pin(m['failed_stdin_recovery_job_ref'],failed_path)
    failed=_metadata(failed_path)
    require(failed['status']=='FAILED_NO_RESTART' and failed['task_id']==TASK and Path(failed['run'])==run
        and failed['manifest_ref']==original_ref and failed['root_engineering_attempt']==1 and failed['retry_validation']==[]
        and failed['native_fit_started_in_recovery'] is False and failed['verified_no_child_processes'] is True
        and failed['test_2026_read_authorized'] is False
        and failed['failure']['type']=='LauncherEngineeringFailure'
        and failed['failure']['message']=='WINDOWS_MP_SPAWN_STDIN_MAIN_INVALID_ARGUMENT_BLOCKED_BEFORE_NATIVE_FIT_START',
        'ORIGINAL_STDIN_RECOVERY_FAILURE_MUST_REMAIN')
    _pin(failed['previous_state_ref'],base/'FIRST_LAUNCHER_JOB_BEFORE_STOP.json')
    wait_path=run/'logs/ACCOUNT_EVALUATION_RECOVERY_WAIT_JOB.json';_pin(m['failed_account_wait_job_ref'],wait_path);wait=_metadata(wait_path)
    require(wait['status']=='FAILED_NO_RESTART' and wait['task_id']==TASK and Path(wait['run'])==run
        and wait['test_2026_read_authorized'] is False and Path(wait['upstream_job'])==failed_path
        and wait['failure']['message']=='ENGINEERING_RECOVERY_FAILED_NO_RESTART','UNFITTED_ACCOUNT_WAIT_FAILURE_MUST_REMAIN')
    if account_authority is None:account_authority=_account_recovery_authority(run)
    if account_authority is None:
        _pin(wait['evaluation_freeze_ref'],run/evaluation.FREEZE);_pin(wait['source_ref'],Path(evaluation.__file__))
    else:
        account_manifest=account_authority['manifest']
        require(wait['evaluation_freeze_ref']==account_manifest['old_account_freeze_ref']
            and wait['source_ref']==account_manifest['source_custody']['evaluation_runner']['original_ref'],
            'LEGACY_WAIT_EVALUATOR_FACT_NOT_AUTHENTICATED_BY_ACCOUNT_CUSTODY')
        _pin(wait['evaluation_freeze_ref'],run/'CONSENSUS_ACCOUNT_EVALUATION_FREEZE.json')
    progress_path=base/'FUSION_PROGRESS.json';_pin(m['first_stdin_progress_ref'],progress_path);progress=_metadata(progress_path)
    keys=('packet_id','method','year')
    require(progress['status']=='RUNNING' and progress['slots_complete']==len(progress['rows'])==16 and progress['total_slots']==len(slots)
        and progress['test_2026_content_read'] is False
        and [{k:r[k] for k in keys} for r in progress['rows']]==[{k:r[k] for k in keys} for r in slots[:16]],
        'FIRST_STDIN_PROGRESS_FIXED_SIXTEEN_REQUIRED')
    spawn_path=base/'unfitted_spawn_slot/core5/convex/2023/receipt.json';_pin(m['unfitted_spawn_receipt_ref'],spawn_path);spawn=_metadata(spawn_path)
    archive=_metadata(original['engineering_retry_slots'][0]['archived_receipt_ref']['path'])
    require(spawn['status']=='IN_PROGRESS' and spawn['fit_units']==0 and spawn['task_id']==TASK
        and (spawn['packet_id'],spawn['model_id'],spawn['year'])==('core5','convex',2023)
        and spawn['reuse_tuple']==archive['reuse_tuple'] and spawn['reuse_tuple_sha256']==archive['reuse_tuple_sha256']
        and spawn['source_pins']==frozen['source_pins']
        and Path(spawn['receipt_path'])==fusion.slot_paths(run,'core5','convex',2023)[1],'STDIN_SPAWN_MUST_BE_SAME_UNFITTED_TUPLE')
    stop_path=base/'STOP_EVIDENCE.json';_pin(m['stop_evidence_ref'],stop_path);stop=_metadata(stop_path)
    require(stop['status']=='VERIFIED_UNFITTED_STDIN_PARENT_TERMINATED' and stop['fit_units']==0
        and stop['no_child_processes'] is True and stop['parent_pid']==failed['verified_terminated_parent_pid']>0
        and stop['source_spec_data_sampling_seed_parameters_changed'] is False and stop['test_2026_rows_read']==0
        and stop['spawn_slot_archived_receipt_ref']==m['unfitted_spawn_receipt_ref'],'UNFITTED_SELF_LAUNCHER_STOP_EVIDENCE_REQUIRED')
    stdin_log=base/'FIT_LOG.jsonl';_pin(m['first_stdin_fit_log_ref'],stdin_log)
    first_ref=original['first_pass_fit_log_ref'];_pin(first_ref);first_size=Path(first_ref['path']).stat().st_size;stdin_size=stdin_log.stat().st_size
    require(0<first_size<stdin_size and stdin_size-first_size<=16384
        and _log_prefix_sha(stdin_log,first_size)==first_ref['sha256'],'FIRST_STDIN_LOG_MUST_PRESERVE_ORIGINAL_PREFIX')
    with stdin_log.open('rb') as stream:stream.seek(first_size);tail=stream.read(16385)
    lines=tail.splitlines();require(len(lines)==1,'STDIN_RECOVERY_SINGLE_UNFITTED_START_REQUIRED');event=json.loads(lines[0])
    expected_event=dict(event='CONSENSUS_FUSION_SLOT_STARTED',packet_id='core5',model_id='convex',year=2023,reuse_tuple_sha256=spawn['reuse_tuple_sha256'])
    require(event==expected_event==stop['native_fit_log_tail'],'STDIN_RECOVERY_NATIVE_FIT_MUST_NOT_HAVE_STARTED')
    job_path=base/'RECOVERY_JOB_R2.json';job=_metadata(job_path)
    require(job['status']=='COMPLETED' and job['task_id']==TASK and Path(job['run'])==run and job['manifest_ref']==manifest_ref
        and job['root_engineering_attempt']==2 and job['named_main_launcher_ref']==m['named_main_launcher_ref']
        and job['fusion_slots']==len(slots) and job['auxiliary_status']==_metadata(run/'models/consensus_auxiliary/final_pre2026/receipt.json')['status']
        and job['test_2026_read_authorized'] is False,'NAMED_MAIN_JOB_SUCCESSFUL_TERMINAL_REQUIRED')
    return dict(manifest_ref=manifest_ref,recovery_job_ref=_ref(job_path),job=job,failed_stdin_recovery_job_ref=m['failed_stdin_recovery_job_ref'],
        failed_account_wait_job_ref=m['failed_account_wait_job_ref'],first_launcher_state_ref=failed['previous_state_ref'],
        named_main_launcher_ref=m['named_main_launcher_ref'],first_stdin_progress_ref=m['first_stdin_progress_ref'],
        first_stdin_fit_log_ref=m['first_stdin_fit_log_ref'],first_stdin_fit_log_bytes=stdin_size,
        stop_evidence_ref=m['stop_evidence_ref'],unfitted_spawn_receipt_ref=m['unfitted_spawn_receipt_ref'],
        own_unfitted_launcher_terminated=True,original_stdin_native_fit_started=False,additional_scientific_retries_authorized=False)


def _engineering_recovery(run,frozen,freeze_ref,slots,fusions,fit_log_ref,account_authority=None):
    base=run/RECOVERY_DIRECTORY;path=base/'RECOVERY_MANIFEST.json'
    if not path.exists():
        require(not base.exists() and not (run/NAMED_MAIN_DIRECTORY).exists(),'RECOVERY_MANIFEST_MISSING')
        return None
    manifest_ref=dict(path=str(path),sha256=RECOVERY_MANIFEST_SHA256);_pin(manifest_ref,path)
    manifest=_metadata(path)
    require(manifest['schema']=='CONSENSUS_FUSION_PARENT_BOOTSTRAP_ENGINEERING_RECOVERY_R1'
        and manifest['status']=='ROOT_AUTHORIZED_SINGLE_IMPORT_ENVIRONMENT_RECOVERY'
        and manifest['task_id']==TASK and Path(manifest['run'])==run
        and manifest['test_2026_read_authorized'] is False
        and manifest['source_spec_seed_parameters_data_sampling_selection_rule_changed'] is False
        and manifest['global_fit_log_preserved'] is True
        and manifest['fusion_freeze_ref']==freeze_ref and manifest['source_pins']==frozen['source_pins'],
        'EXACT_IMPORT_RECOVERY_SCOPE_REQUIRED')
    _pin_tree(manifest['source_pins'])
    expected=[dict(packet_id='core5',method=m,year=y) for m in ('convex','stack_ridge','stack_elastic','stack_hgb','stack_mlp') for y in (2023,2024,2025,2026)]
    retries=manifest['engineering_retry_slots']
    require([r['slot'] for r in retries]==expected,'EXACT_20_ENGINEERING_RETRIES_REQUIRED')
    first_progress_ref=manifest['first_pass_progress_ref'];_pin(first_progress_ref,base/'FIRST_PASS_FUSION_PROGRESS.json')
    first=_metadata(first_progress_ref['path']);first_rows=first['rows'];keys=('packet_id','method','year')
    require(first['test_2026_content_read'] is False and first['total_slots']==len(slots)
        and first['slots_complete']==len(first_rows)<=len(slots)
        and [{k:r[k] for k in keys} for r in first_rows]==[{k:r[k] for k in keys} for r in slots[:len(first_rows)]],
        'FIRST_FAILURE_FIXED_PLAN_REQUIRED')
    correction=_named_main_correction(run,manifest,manifest_ref,frozen,slots,account_authority)
    if correction is None:
        job_path=base/'RECOVERY_JOB.json';job=_metadata(job_path)
        require(job['status']=='COMPLETED' and job['task_id']==TASK and Path(job['run'])==run
            and job['manifest_ref']==manifest_ref and job['root_engineering_attempt']==1
            and job['bootstrap']=='fusion.owner._native(spec[dependency_paths])'
            and job['test_2026_read_authorized'] is False,'RECOVERY_JOB_SUCCESSFUL_TERMINAL_REQUIRED')
    else:
        job_path=Path(correction['recovery_job_ref']['path']);job=correction.pop('job')
    validations=job['retry_validation']
    require([r['slot'] for r in validations]==expected,'RECOVERY_TERMINAL_VALIDATION_CANNOT_SHRINK')
    closure=[]
    common_failure=dict(type='ModuleNotFoundError',message="No module named 'common'")
    for retry,validation in zip(retries,validations):
        slot=retry['slot'];packet,method,year=(slot[k] for k in keys)
        live_path=fusion.slot_paths(run,packet,method,year)[1]
        archive_ref=retry['archived_receipt_ref'];_pin(archive_ref,base/'failed_import_slots'/packet/method/str(year)/'receipt.json')
        archive=_metadata(archive_ref['path']);live=_metadata(live_path)
        old_row=next((r for r in first_rows if all(r[k]==slot[k] for k in keys)),None)
        final=next(f for f in fusions if all(f['slot'][k]==slot[k] for k in keys))
        require(archive['status']=='FAILED' and archive['failure']==common_failure
            and archive['task_id']==TASK and (archive['packet_id'],archive['model_id'],archive['year'])==(packet,method,year)
            and Path(archive['receipt_path'])==Path(retry['original_receipt_path'])==live_path
            and archive['source_pins']==frozen['source_pins']
            and archive['reuse_tuple']['freeze_ref']==freeze_ref
            and archive['reuse_tuple_sha256']==values.digest(archive['reuse_tuple'])==retry['expected_reuse_tuple_sha256']
            and archive['fit_units']==retry['previous_fit_units']==(1 if method=='convex' else 2)
            and retry['root_authorized_engineering_attempt_limit']==1
            and old_row is not None and old_row['status']=='FAILED' and old_row['failure']==common_failure
            and Path(old_row['receipt_path'])==live_path,'FIRST_ARCHIVED_COMMON_IMPORT_FAILURE_REQUIRED')
        require(live['reuse_tuple']==archive['reuse_tuple'] and live['reuse_tuple_sha256']==archive['reuse_tuple_sha256']
            and (correction is not None or validation['same_reuse_tuple'] is True) and validation['reuse_tuple_sha256']==archive['reuse_tuple_sha256']
            and validation['status']==live['status']==final['status'] and live['status'] in {'TRAINED','FAILED'}
            and validation['receipt_ref']==final['receipt'],'RECOVERY_SAME_TUPLE_OR_TERMINAL_CUSTODY_CHANGED')
        _pin(validation['receipt_ref'],live_path)
        closure.append(dict(slot=slot,first_failed_receipt_ref=archive_ref,recovered_receipt_ref=validation['receipt_ref'],
            previous_fit_units=archive['fit_units'],reuse_tuple_sha256=archive['reuse_tuple_sha256'],status=live['status']))
    scientific=manifest['scientific_failures_preserved_without_retry']
    require(len(scientific)==1 and scientific[0]['slot']==dict(packet_id='core5',method='nnls',year=2024),
        'SCIENTIFIC_FAILURE_MUST_REMAIN_OUTSIDE_ENGINEERING_RETRY')
    scientific_path=fusion.slot_paths(run,'core5','nnls',2024)[1]
    _pin(scientific[0]['receipt_ref'],scientific_path);failed=_metadata(scientific_path)
    require(failed['status']=='FAILED' and failed['failure']==scientific[0]['failure']
        and 'NNLS_ZERO_OR_INVALID_SUM_NO_SUBSTITUTE' in failed['failure']['message'],
        'SCIENTIFIC_FAILURE_BYTES_OR_DISPOSITION_CHANGED')
    probe_ref=manifest['synthetic_probe_ref'];_pin(probe_ref)
    probe=_metadata(probe_ref['path'])
    require(probe['status']=='PASS_4_FRESH_PARENT_SPAWN_CASES' and probe['source']=='PURE_SYNTHETIC'
        and [(r['method'],r['parent_preloaded']) for r in probe['records']]==[(m,b) for m in ('convex','stack_ridge') for b in (False,True)]
        and all(r['source']=='PURE_SYNTHETIC' and r['real_inputs_read'] is False and r['real_2026_read'] is False
            and r['actual_receipts_changed'] is False
            and r['status']==('PASS_ORIGINAL_WORKER_WITH_PARENT_BOOTSTRAP' if r['parent_preloaded'] else 'EXPECTED_COMMON_IMPORT_FAILURE')
            for r in probe['records']),'PURE_SYNTHETIC_PARENT_BOOTSTRAP_PROOF_REQUIRED')
    first_log_ref=manifest['first_pass_fit_log_ref'];_pin(first_log_ref,base/'FIRST_PASS_FIT_LOG.jsonl')
    first_size=Path(first_log_ref['path']).stat().st_size;final_log=_pin(fit_log_ref,run/'FIT_LOG.jsonl')
    require(0<first_size<=final_log.stat().st_size,'FIRST_PASS_FIT_CONSUMPTION_MUST_REMAIN')
    require(_log_prefix_sha(final_log,first_size)==first_log_ref['sha256'],'FIRST_PASS_FIT_LOG_PREFIX_CHANGED')
    if correction is not None:
        stdin_size=correction['first_stdin_fit_log_bytes']
        require(_log_prefix_sha(final_log,stdin_size)==correction['first_stdin_fit_log_ref']['sha256'],'UNFITTED_STDIN_LOG_PREFIX_CHANGED')
        snapshot_size=_log_snapshot_prefix(fit_log_ref,job['fit_log_ref'])
        require(snapshot_size>=stdin_size,'DOWNSTREAM_SNAPSHOT_MUST_FOLLOW_UNFITTED_STDIN_START')
        correction['completed_downstream_fit_log_snapshot']=dict(ref=job['fit_log_ref'],authenticated_prefix_bytes=snapshot_size,
            role='HISTORICAL_DOWNSTREAM_COMPLETION_LOG_PREFIX_BEFORE_ACCOUNT_APPENDS')
    return dict(manifest_ref=manifest_ref,recovery_job_ref=_ref(job_path),named_main_correction=correction,first_pass_progress_ref=first_progress_ref,
        first_pass_fit_log_ref=first_log_ref,synthetic_probe_ref=probe_ref,slots=closure,
        scientific_failures_preserved_without_retry=scientific,previous_failed_fit_units=sum(r['previous_fit_units'] for r in closure),
        final_fit_log_ref=fit_log_ref,scientific_selection_changed=False,test_2026_read_authorized=False)


def _account_record(run,record,freeze_ref,*,final_risk=False,continuation=False):
    flow=record['selected_flow'] if final_risk else record['flow_id']
    path=run/('models/consensus_final_policy' if final_risk else 'evaluation/consensus_account')/flow/'receipt.json'
    require(Path(record['receipt_path'])==path and _metadata(path,account=not final_risk,continuation=continuation)==record and record['task_id']==TASK
        and record['freeze_ref']==freeze_ref,'ACCOUNT_SUMMARY_CUSTODY_CHANGED')
    require(record['status'] in {'COMPLETE','NOT_TESTABLE','FAILED_NO_RETRY'},'ACCOUNT_SELECTION_NOT_TERMINAL')
    for name,pin in record.get('artifacts',{}).items():
        _pin(pin,path.parent/(name+'.joblib' if name=='state' else name+'.parquet'))
    if record['status']=='COMPLETE':require('state' in record['artifacts'],'ACCOUNT_FINAL_STATE_REQUIRED')
    if final_risk:
        expected_identity=values.digest(dict(selected_flow=flow,selected_receipt_sha256=values.sha(run/'evaluation/consensus_account'/flow/'receipt.json'),freeze_ref=freeze_ref))
        require(record['identity_sha256']==expected_identity,'FINAL_RISK_SELECTION_CUSTODY_CHANGED')
        require(record['status']=='COMPLETE' and record['test_rows_read']==0
            and record['final_risk_fit_cutoff']=='2026-01-01 exclusive','FINAL_RISK_NOT_FROZEN_PRE2026')
    return dict(flow_id=flow,status=record['status'],receipt=_ref(path),artifacts=record.get('artifacts',{}))


def source_pins():
    return {name:_ref(module.__file__) for name,module in dict(builder=__import__(__name__,fromlist=['x']),
        registry=registry,predictor=predictors,fusion=fusion,downstream=downstream,evaluation=evaluation).items()}


def _candidate_dispositions(run,spec,pf,pf_ref,ff,ff_ref):
    pslots=predictors.planned_slots(spec);fslots=fusion.planned_slots(spec)
    prows,pp=_progress(run,'logs/PREDICTOR_PROGRESS.json',pslots,('model_id','year','horizon'))
    frows,fp=_progress(run,'logs/FUSION_PROGRESS.json',fslots,('packet_id','method','year'))
    models=[];fusions=[]
    for kind,slots,rows,frozen,fr,out in (('predictor',pslots,prows,pf,pf_ref,models),('fusion',fslots,frows,ff,ff_ref,fusions)):
        for slot,row in zip(slots,rows):
            entry,receipt=_fitted(run,slot,frozen,fr,kind)
            allowed={'PUBLISHED','TRAINED'} if receipt['status']=='TRAINED' else {receipt['status']}
            unavailable_current=(kind=='fusion' and slot['year']<2026 and receipt['status']=='TRAINED'
                and row['status']=='NOT_TESTABLE' and bool(row.get('reason')))
            require(row['status'] in allowed or unavailable_current,'PROGRESS_FIT_DISPOSITION_CHANGED')
            progress_path=row['receipt_path']
            if progress_path is None:
                # PacketUnavailable is returned before fit and deliberately omits
                # receipt_path; authenticate its fixed canonical metadata receipt.
                require(kind=='fusion' and row['status']==receipt['status']=='NOT_TESTABLE'
                    and receipt.get('reuse_tuple') is None and receipt.get('receipt_path') is None
                    and receipt.get('task_id')==TASK and receipt.get('fit_units')==0
                    and receipt.get('owner_id')==slot['owner_id'] and receipt.get('members')==slot['members']
                    and isinstance(row.get('reason'),str) and bool(row['reason']) and row['reason']==receipt.get('reason'),
                    'NULL_PROGRESS_RECEIPT_ONLY_FOR_BOUND_UNFITTED_FUSION')
                entry['progress_receipt_binding']='CANONICAL_UNFITTED_NOT_TESTABLE_RECEIPT'
                entry['unavailable_fit_reason']=receipt['reason']
            else:
                require(isinstance(progress_path,(str,Path)) and Path(progress_path)==Path(entry['receipt']['path']),
                    'PROGRESS_RECEIPT_PATH_CHANGED')
            entry['publication_disposition']=row['status']
            if unavailable_current:entry['unavailable_publication_reason']=row['reason']
            if slot['year']==2026:require(row['status']==receipt['status'],'FINAL_SLOT_IS_TRAINING_ONLY')
            if row['status']=='PUBLISHED':
                model=slot['model_id'] if kind=='predictor' else slot['method']
                output=run/'predictions'/('consensus_predictors/'+model+f"/{slot['horizon']}d" if kind=='predictor' else 'consensus_fusion/'+slot['packet_id']+'/'+model)/f"{slot['year']}.parquet"
                pub=_metadata(output.with_suffix('.receipt.json'))
                require(pub['status']=='PUBLISHED' and pub['test_2026_rows_read']==0 and pub['source_pins']==frozen['source_pins']
                    and pub['fit_receipt_sha256']==entry['receipt']['sha256'] and Path(pub['fit_receipt_path'])==Path(entry['receipt']['path'])
                    and pub['reuse_tuple_sha256']==receipt['reuse_tuple_sha256'],'PUBLICATION_FIT_CUSTODY_CHANGED')
                entry['publication']=_ref(output.with_suffix('.receipt.json'));entry['prediction']=dict(path=str(output),sha256=pub['sha256']);_pin(entry['prediction'])
            out.append(entry)
    return models,fusions,dict(predictor=pp,fusion=fp),fslots


def _auxiliary_disposition(run):
    af,_,af_ref=downstream.auxiliary_contract(run);ap=run/'models/consensus_auxiliary/final_pre2026/receipt.json';aux=_metadata(ap)
    require(aux['status'] in {'TRAINED_DIAGNOSTICS','TRAINED_WITH_COMPONENT_FAILURES','FAILED_NO_RETRY','NOT_TESTABLE'}
        and aux['task_id']==TASK and aux['source_pins']==af['source_pins']
        and aux['reuse_tuple']['freeze_ref']==af_ref and aux['reuse_tuple_sha256']==values.digest(aux['reuse_tuple'])
        and aux['primary_pto_changed'] is False,'AUXILIARY_FINAL_DISPOSITION_REQUIRED')
    auxiliary=dict(status=aux['status'],receipt=_ref(ap),freeze_ref=af_ref,diagnostics_only=True)
    if aux['status'].startswith('TRAINED'):
        auxiliary['model']=dict(path=str(ap.with_name('model.joblib')),sha256=aux['model_sha256']);_pin(auxiliary['model'])
    return auxiliary


def build(run=EXPECTED_RUN):
    run=_run(run)
    return _build_continuation(run) if run==fusion.CONTINUATION_RUN else _build(run)


def _build(run):
    spec,pf,pf_ref=predictors.contract(run,'ridge',2026,5)
    _,ef,ef_ref=evaluation.contract(run)
    summary_path=run/'evaluation/consensus_account_summary.json';summary=_metadata(summary_path,summary=True)
    require(summary['status']=='COMPLETE' and summary['task_id']==TASK and summary['freeze_ref']==ef_ref
        and summary['test_2026_rows_read']==0 and summary['sensitivity_selection_feedback'] is False
        and summary['conditional_research_only'] is True and summary['strict_PIT_certified'] is False,'COMPLETE_PRE2026_SELECTION_REQUIRED')
    method=summary['selected_fusion']
    _,method,_,ff,selected_slot,ff_ref=fusion.contract(run,'core5',method,2026)
    require(selected_slot['members']==[dict(model_id=m,horizon=5) for m in fusion.CORE],'EXACT_SELECTED_CORE5_REQUIRED')
    models,fusions,progress_refs,fslots=_candidate_dispositions(run,spec,pf,pf_ref,ff,ff_ref)
    selected_models=[m for m in models if m['slot']['year']==2026 and m['slot']['horizon']==5 and m['slot']['model_id'] in fusion.CORE]
    require(len(selected_models)==5 and all(m['status']=='TRAINED' for m in selected_models),'ALL_FIVE_SELECTED_FINAL_MODELS_REQUIRED')
    selected_fusion=next(f for f in fusions if f['slot']==selected_slot)
    require(selected_fusion['status']=='TRAINED','SELECTED_FINAL_FUSION_REQUIRED')
    stage1=summary['stage1'];stage2=summary['stage2']
    require([r['flow_id'] for r in stage1]==[evaluation.flow_id(m) for m in evaluation.RECIPE['fusion_methods']]
        and [r['flow_id'] for r in stage2]==[evaluation.flow_id(method,p['risk_method'],p['allocation_method']) for p in evaluation.RECIPE['stage2']],
        'ALL_PRE2026_ACCOUNT_SELECTION_PATHS_REQUIRED')
    dispositions=[_account_record(run,r,ef_ref) for r in stage1+stage2]
    selected=[r for r in stage2 if r['flow_id']==summary['selected_flow']]
    require(len(selected)==1 and selected[0]['status']=='COMPLETE' and selected[0]['fusion_method']==method
        and selected[0]['fee_config']==evaluation.RECIPE['fee_config'],'SELECTED_ACCOUNT_RULES_REQUIRED')
    diagnostics=summary['sensitivities'];dplan=evaluation.RECIPE['diagnostic_sensitivities'];chosen=selected[0]
    require([r['flow_id'] for r in diagnostics]==[evaluation.flow_id(method,chosen['risk_method'],chosen['allocation_method'],d['tag']) for d in dplan],
        'FIXED_DIAGNOSTIC_DISPOSITIONS_REQUIRED')
    dispositions += [_account_record(run,r,ef_ref) for r in diagnostics]
    final_risk=_account_record(run,summary['final_risk_receipt'],ef_ref,final_risk=True)
    require(final_risk['flow_id']==summary['selected_flow'],'SELECTED_FINAL_RISK_CHANGED')
    diagnostic_risk=summary['sensitivity_final_risk']
    require([r['selected_flow'] for r in diagnostic_risk]==[r['flow_id'] for r in diagnostics if r['status']=='COMPLETE'],'DIAGNOSTIC_FINAL_RISK_CLOSURE_REQUIRED')
    risks=[_account_record(run,r,ef_ref,final_risk=True) for r in diagnostic_risk]
    auxiliary=_auxiliary_disposition(run)
    custody={name:record for name,record in registry.REVIEW_SCOPE.items() if name.endswith('_ref')};_pin_tree(custody)
    _pin(ef['account_source_scope_ref']);source_custody=_account_source_custody(ef_ref,ef['account_source_scope_ref'])
    fit_log_ref=_ref(run/'FIT_LOG.jsonl');_pin(fit_log_ref,run/'FIT_LOG.jsonl')
    account_authority=_account_recovery_authority(run)
    recovery=_engineering_recovery(run,ff,ff_ref,fslots,fusions,fit_log_ref,account_authority)
    account_recovery=_account_recovery_history(run,account_authority,ef_ref,summary,_ref(summary_path),fit_log_ref)
    result=dict(schema='CONSENSUS_FINAL_SYSTEM_FREEZE_R1',status=STATUS,task_id=TASK,run=str(run),
        source_pins=source_pins(),custody_refs=custody,authorized_spec_ref=pf['authorized_spec'],
        predictor_freeze_ref=pf_ref,fusion_freeze_ref=ff_ref,evaluation_freeze_ref=ef_ref,
        account_source_scope_ref=ef['account_source_scope_ref'],account_source_custody=source_custody,selection_summary_ref=_ref(summary_path),
        progress_refs=progress_refs,fit_log_ref=fit_log_ref,engineering_recovery=recovery,account_engineering_recovery=account_recovery,
        candidate_predictors=models,candidate_fusions=fusions,
        selected_predictors=selected_models,selected_fusion=selected_fusion,selected_flow=summary['selected_flow'],
        selected_risk=chosen['risk_method'],selected_allocation=chosen['allocation_method'],final_risk=final_risk,
        account_dispositions=dispositions,diagnostic_final_risk=risks,auxiliary=auxiliary,
        account_recipe=ef['recipe'],source_policy='FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY',strict_PIT_certified=False,
        vintage='UNKNOWN_RETAINED',A2_already_exposed=True,evaluation_role='DESCRIPTIVE_DIAGNOSTIC_ONLY',
        test_exposure_scope=dict(actual_2026_numeric_datasets_or_test_rows_read=False,
            family='ALREADY_EXPOSED_A2_FAMILY',legacy_literal='OLD_SOURCE_CODE_OUTCOME_LITERAL_SEEN_BY_READINESS_AGENT',
            fresh_blind_holdout=False,selection_feedback=False,FAST3_Confirmation_read=False,
            precondition='Actual2026 datasets/clocks/targets/metrics must not enter this round fitting or selection; existing exposure retained'),
        test_2026_numeric_read_authorized=False,FAST3_Confirmation_access=False,
        test_source_qualification_required=True,forbidden_test_updates=['fit','scale','calibration','risk estimation','selection'])
    result['semantic_sha256']=values.digest(result)
    return result




FINAL_CALIBRATION_SCHEMA='CONSENSUS_FINAL_CALIBRATION_COMPLETION_R1'
FINAL_CALIBRATION_STATUS='COMPLETE_PRE2026_CALIBRATION_NO_TEST_READ_AUTHORITY'
FINAL_CALIBRATION_RELATIVE='models/consensus_final_calibration_completion/receipt.json'


def _qualified_metadata_ref(record,*,name,expected_patch=None):
    path=_pin(record);value=_metadata(path)
    patch_status='SOURCE_QUALIFIED_TWO_ORIGINAL_MATURE_KEYS_ONLY_PENDING_CALIBRATION_FIT_AUTHORITY'
    label_patch=name=='final_calibration_source' and value.get('status')==patch_status
    require(label_patch or (isinstance(value.get('status'),str) and value['status'].startswith(('PASS','COMPLETE','QUALIFIED','ACCEPTED'))),
        'QUALIFIED_METADATA_REQUIRED:'+name)
    require(not any(value.get(k) is True for k in ('test_2026_content_read','test_2026_numeric_read_authorized',
        'FAST3_Confirmation_access','selection_feedback')),'QUALIFICATION_CANNOT_OPEN_TEST_OR_FEEDBACK:'+name)
    if label_patch:
        require(value['schema']=='CONSENSUS_SOURCE_QUALIFIED_FINAL_CALIBRATION_LABEL_PATCH_R1'
            and value['task_id']==TASK and value['research_id']==fusion.CONTINUATION_RESEARCH_ID
            and value['patch_ref']==expected_patch and value['rows']==2
            and value['exact_signal_keys']==['2025-10-07|BN','2025-10-08|BN']
            and value['fold_year_key']==2026 and value['fold_cutoff_exclusive']=='2026-01-01'
            and pd.Timestamp(value['calibration_start'])==pd.Timestamp('2025-10-07')
            and value['all_changed_keys_calibration_only'] is True and value['native_training_rows_changed']==0
            and value['original_masks_and_support_unchanged'] is True and value['canonical_inputs_overwritten'] is False
            and value['features_or_prices_or_2026_payload_read'] is False, 'EXACT_SOURCE_QUALIFIED_TWO_KEY_CALIBRATION_PATCH_REQUIRED')
        _pin(value['patch_ref'])
        for role in ('support_ref','official_share_right_ref','source_panel_ref','label_formula_owner_ref','generator_ref'):_pin(value[role])
    return value


def _child_fusion_dispositions(run,ff,ff_ref,parent,spec):
    slots=fusion.continuation_slots(spec)
    require(ff['ordered_slots']==slots and len(slots)==4,'EXACT_FOUR_NEW_FUSION_SLOTS_REQUIRED')
    rows,progress=_progress(run,'logs/FUSION_PROGRESS.json',slots,('packet_id','method','year'))
    result=[]
    for slot,row in zip(slots,rows):
        entry,receipt=_fitted(run,slot,ff,ff_ref,'fusion',publication_run=parent)
        require(receipt['reuse_tuple']['research_id']==fusion.CONTINUATION_RESEARCH_ID
            and receipt['reuse_tuple']['continuation_scope_ref']==ff['continuation_scope_ref']
            and receipt['reuse_tuple']['prior_fit_units']==ff['prior_fit_units'], 'CHILD_FUSION_REUSE_LINEAGE_CHANGED')
        require(row['status']==('PUBLISHED' if receipt['status']=='TRAINED' and slot['year']<2026 else receipt['status'])
            and Path(row['receipt_path'])==Path(entry['receipt']['path']),'CHILD_COMPLETE_PUBLICATION_DISPOSITION_REQUIRED')
        entry['publication_disposition']=row['status']
        if row['status']=='PUBLISHED':
            output=run/'predictions/consensus_fusion'/slot['packet_id']/slot['method']/f"{slot['year']}.parquet"
            pub=_metadata(output.with_suffix('.receipt.json'))
            require(pub['status']=='PUBLISHED' and pub['test_2026_rows_read']==0 and pub['source_pins']==ff['source_pins']
                and pub['fit_receipt_sha256']==entry['receipt']['sha256']
                and Path(pub['fit_receipt_path'])==Path(entry['receipt']['path'])
                and pub['reuse_tuple_sha256']==receipt['reuse_tuple_sha256']
                and pub['model_sha256']==entry['artifacts']['model']['sha256'] and pub['prediction_role']=='MODEL_OOF'
                and (pub['packet_id'],pub['model_id'],pub['year'])==(slot['packet_id'],slot['method'],slot['year']),
                'CHILD_PUBLICATION_FIT_CUSTODY_CHANGED')
            entry['publication']=_ref(output.with_suffix('.receipt.json'))
            entry['prediction']=dict(path=str(output),sha256=pub['sha256']);_pin(entry['prediction'])
        result.append(entry)
    return result,progress


def _historical_auxiliary(parent,audit):
    # The parent audit pins the original auxiliary receipt/model and its freeze;
    # current changed downstream source is not relabelled as that old producer.
    auxiliary=audit['auxiliary'];ap=parent/'models/consensus_auxiliary/final_pre2026/receipt.json'
    _pin(auxiliary['receipt'],ap);_pin(auxiliary['freeze_ref'],parent/'CONSENSUS_AUXILIARY_FREEZE.json')
    receipt=_metadata(ap);frozen=_metadata(auxiliary['freeze_ref']['path'])
    require(receipt['status']==auxiliary['status'] and receipt['task_id']==TASK
        and receipt['primary_pto_changed'] is False and receipt['source_pins']==frozen['source_pins']
        and receipt['reuse_tuple']['freeze_ref']==auxiliary['freeze_ref']
        and receipt['reuse_tuple_sha256']==values.digest(receipt['reuse_tuple']), 'PARENT_AUXILIARY_HISTORICAL_CUSTODY_CHANGED')
    if receipt['status'].startswith('TRAINED'):
        require(auxiliary['model']==dict(path=str(ap.with_name('model.joblib')),sha256=receipt['model_sha256']),
            'PARENT_AUXILIARY_MODEL_ROLE_CHANGED');_pin(auxiliary['model'])
    return dict(auxiliary,historical_parent_fact=True,current_source_relabelled=False)


def _child_source_closure(ef,ef_ref):
    custody=_account_source_custody(ef_ref,ef['account_source_scope_ref'],continuation=True)
    scope=_metadata(_pin(ef['account_source_scope_ref']))
    manifest_ref=scope.get('source_completion_manifest_ref')
    require(manifest_ref is not None,'SOURCE_COMPLETION_MANIFEST_REQUIRED_FOR_CHILD_FINAL_FREEZE')
    manifest=_metadata(_pin(manifest_ref))
    require(manifest['schema']=='CONSENSUS_SOURCE_COMPLETION_ACCOUNT_INPUT_MANIFEST_R1'
        and manifest['status']=='QUALIFIED_SOURCE_FACTS_FOR_PRE2026_ACCOUNTING_ONLY'
        and manifest['task_id']==TASK and manifest['research_id']==fusion.CONTINUATION_RESEARCH_ID
        and manifest['scope_start']=='2023-01-01' and manifest['scope_end_exclusive']=='2026-01-01'
        and manifest['strict_PIT'] is False and manifest['target_support_expansion'] is False,
        'CHILD_SOURCE_COMPLETION_ROLE_OR_CLOCK_CHANGED')
    # canonical metadata_preflight checked the nested references with its exact
    # transport owner; the generic physical pin must never target historical refs.
    for key in ('account_convention_scope_ref','account_fx_convention_scope_ref','fx_source_availability_qualification_ref'):
        _pin(ef[key])
    _qualified_metadata_ref(ef['actual_input_preflight_ref'],name='actual_input_preflight')
    reviews=ef['independent_review_refs'];require(isinstance(reviews,list) and bool(reviews),'INDEPENDENT_SOURCE_REVIEWS_REQUIRED')
    for r in reviews:_qualified_metadata_ref(r,name='independent_source_review')
    _qualified_metadata_ref(ef['research_identity_review_ref'],name='research_identity_review')
    return dict(custody,source_completion_manifest_ref=manifest_ref,
        source_completion_role=manifest['status'],account_convention_scope_ref=ef['account_convention_scope_ref'],
        account_fx_convention_scope_ref=ef['account_fx_convention_scope_ref'],
        fx_source_availability_qualification_ref=ef['fx_source_availability_qualification_ref'],
        actual_input_preflight_ref=ef['actual_input_preflight_ref'],independent_review_refs=reviews,
        research_identity_review_ref=ef['research_identity_review_ref'])


def _final_calibration_completion(run,ef,models,fusions,scope_ref):
    ref=ef.get('final_calibration_completion_ref')
    require(ref is not None,'FINAL_CALIBRATION_COMPLETION_REQUIRED_BEFORE_TEST_FREEZE')
    path=_pin(ref,run/FINAL_CALIBRATION_RELATIVE);c=_metadata(path,summary=True,continuation=True)
    require(c['schema']==FINAL_CALIBRATION_SCHEMA and c['status']==FINAL_CALIBRATION_STATUS
        and c['task_id']==TASK and c['research_id']==fusion.CONTINUATION_RESEARCH_ID and Path(c['run'])==run
        and c['continuation_scope_ref']==scope_ref and c['native_training_refitted'] is False
        and c['original_support_preserved'] is True and c['test_2026_content_read'] is False
        and c['cutoff']=='2026-01-01 exclusive','QUALIFIED_FINAL_CALIBRATION_COMPLETION_REQUIRED')
    sp=_metadata(_pin(c['completion_spec_ref']));_pin(c['correction_sidecar_ref'])
    require(sp['schema']=='CONSENSUS_SOURCE_CORRECTION_FINAL_CALIBRATION_SUPPLEMENT_R1'
        and sp['status']=='AUTHORIZED_PRE2026_CALIBRATION_ONLY' and sp['task_id']==TASK
        and sp['research_id']==fusion.CONTINUATION_RESEARCH_ID and Path(sp['run'])==run
        and sp['continuation_scope_ref']==scope_ref and sp['prior_fit_units']==1098 and sp['max_fit_units']==10000
        and sp['correction_sidecar_ref']==c['correction_sidecar_ref'] and sp['source_qualification_ref']==c['source_qualification_ref']
        and sp['independent_review_refs']==c['independent_review_refs'] and sp['native_training_refit_authorized'] is False
        and sp['test_2026_read_authorized'] is False, 'FINAL_CALIBRATION_SCIENTIFIC_SUPPLEMENT_NOT_AUTHORIZED')
    _pin_tree(sp['source_pins'])
    log_prefix_size=_log_snapshot_prefix(_ref(run/'FIT_LOG.jsonl'),c['fit_log_snapshot_ref'])
    _qualified_metadata_ref(c['source_qualification_ref'],name='final_calibration_source',expected_patch=c['correction_sidecar_ref'])
    require(bool(c['independent_review_refs']),'FINAL_CALIBRATION_INDEPENDENT_REVIEW_REQUIRED')
    for r in c['independent_review_refs']:_qualified_metadata_ref(r,name='final_calibration_review')
    expected_p=[m for m in models if m['slot']['year']==2026 and m['status']=='TRAINED']
    expected_f=[f for f in fusions if f['slot']['year']==2026 and f['slot']['packet_id']=='core5' and f['status']=='TRAINED']
    require(len(expected_p)==37 and len(expected_f)==14,'ORIGINAL_SUCCESSFUL_FINAL_37_PLUS_14_CALIBRATION_SCOPE_REQUIRED')
    require(sp['predictor_slots']==[e['slot'] for e in expected_p] and sp['fusion_slots']==[e['slot'] for e in expected_f],
        'FINAL_CALIBRATION_AUTHORIZED_SLOT_SCOPE_CHANGED')
    completed=[]
    for kind,entries,originals in (('predictor',c['predictor_completions'],expected_p),('fusion',c['fusion_completions'],expected_f)):
        require([e['slot'] for e in entries]==[e['slot'] for e in originals],'FINAL_CALIBRATION_SUPPORT_CANNOT_CHANGE_OR_SHRINK')
        for e,original in zip(entries,originals):
            require(e['status']=='CALIBRATION_COMPLETED' and e['original_fit_receipt_ref']==original['receipt']
                and e['original_model_ref']==original['artifacts']['model']
                and e['raw_estimator_and_scaler_reused_same_bytes'] is True,'FINAL_CALIBRATION_NATIVE_ORIGIN_CHANGED')
            if kind=='predictor':require(e['original_calibration_ref']==original['artifacts']['calibration'],'ORIGINAL_CALIBRATION_FACT_CHANGED')
            rp=_pin(e['artifacts']['receipt']);r=_metadata(rp)
            require(r['status']=='CALIBRATION_COMPLETED' and r['kind']==kind and r['slot']==e['slot']
                and r['research_id']==fusion.CONTINUATION_RESEARCH_ID and r['task_id']==TASK
                and r['completion_spec_ref']==c['completion_spec_ref'] and r['correction_sidecar_ref']==c['correction_sidecar_ref']
                and r['original_fit_receipt_ref']==original['receipt'] and r['original_model_ref']==original['artifacts']['model']
                and r['native_training_refitted'] is False and r['test_2026_content_read'] is False,
                'FINAL_CALIBRATION_ARTIFACT_RECEIPT_ROLE_CHANGED')
            original_receipt=_metadata(original['receipt']['path']);original_reuse=original_receipt['reuse_tuple']
            _clocks(r['reuse_tuple'],2026)
            require(r['reuse_tuple_sha256']==values.digest(r['reuse_tuple'])
                and r['original_reuse_tuple_sha256']==original_receipt['reuse_tuple_sha256']
                and r['reuse_tuple']['train_frame_sha256']==original_reuse['train_frame_sha256']
                and all(r['reuse_tuple'][k]==original_reuse[k] for k in ('calibration_sessions','train_maturity_exclusive','calibration_maturity_exclusive')),
                'FINAL_CALIBRATION_REUSE_OR_TRAIN_FRAME_CHANGED')
            for role in ('model','calibration'):
                ar=e['artifacts'][role]
                require(Path(ar['path']).is_relative_to(run/'models/consensus_final_calibration_completion')
                    and ar['sha256']==r[role+'_sha256'],'FINAL_CALIBRATION_NEW_ARTIFACT_ROLE_CHANGED');_pin(ar)
            completed.append(dict(e,kind=kind))
    return dict(ref=ref,manifest=c,fit_log_snapshot_prefix_bytes=log_prefix_size),completed


def _child_fit_budget(run,facts):
    path=run/'FIT_LOG.jsonl';ref=_ref(path);_pin(ref,path);units=0
    with path.open('r',encoding='utf-8') as stream:
        for line in stream:
            require(len(line)<=65536,'CHILD_FIT_LOG_RECORD_TOO_LARGE')
            if not line.strip():continue
            event=json.loads(line)
            if event.get('event')=='FIT_STARTED':
                require(event.get('fit_units')==1,'CHILD_PHYSICAL_FIT_UNIT_CHANGED');units+=1
    require(facts['prior']==1098 and facts['prior']+units<=10000,'INHERITED_GLOBAL_FIT_BUDGET_EXCEEDED')
    return dict(parent_fit_log_ref=facts['scope']['parent_custody']['parent_fit_log_ref'],prior_fit_units=facts['prior'],
        child_fit_log_ref=ref,child_fit_units=units,total_fit_units=facts['prior']+units,max_fit_units=10000,no_fit_budget_reset=True)


def _build_continuation(run):
    parent=fusion.reader_run(run);facts=fusion._continuation_facts(run)
    require(parent==facts['parent'],'CHILD_READER_PARENT_CHANGED')
    spec,pf,old_ff=facts['spec'],facts['pf'],facts['ff'];refs=facts['scope']['parent_custody'];pf_ref=refs['predictor_freeze_ref']
    _,_,_,ff,_,ff_ref=fusion.contract(run,'core5',fusion.owner.NNLS_ZERO_ABSTAIN,2026)
    _,ef,ef_ref=evaluation.contract(run)
    require(ef['research_id']==fusion.CONTINUATION_RESEARCH_ID and ef['recipe']==evaluation.recipe_for_run(run)
        and ef['continuation_scope_ref']==facts['scope_ref'] and ef['prior_fit_units']==facts['prior'], 'CHILD_ACCOUNT_RECIPE_OR_LINEAGE_CHANGED')
    models,old_fusions,progress,_=_candidate_dispositions(parent,spec,pf,pf_ref,old_ff,refs['fusion_freeze_ref'])
    require(models==facts['audit']['candidate_predictors'] and old_fusions==facts['audit']['candidate_fusions'],
        'IMMUTABLE_PARENT_TERMINAL_DISPOSITIONS_CHANGED')
    new_fusions,child_progress=_child_fusion_dispositions(run,ff,ff_ref,parent,spec);fusions=old_fusions+new_fusions
    summary_path=run/'evaluation/consensus_account_summary.json';summary=_metadata(summary_path,summary=True,continuation=True)
    require(summary['status']=='COMPLETE' and summary['task_id']==TASK and summary['freeze_ref']==ef_ref
        and summary['test_2026_rows_read']==0 and summary['sensitivity_selection_feedback'] is False
        and summary['conditional_research_only'] is True and summary['strict_PIT_certified'] is False,'COMPLETE_PRE2026_SELECTION_REQUIRED')
    method=summary['selected_fusion'];recipe=ef['recipe'];flow=lambda m,r='LW',a='cost_aware',t=None:evaluation.flow_id(m,r,a,t,run=run)
    require(len(recipe['fusion_methods'])==14 and len(recipe['stage2'])==17,'EXACT_CHILD_ACCOUNT_SELECTION_SCOPE_REQUIRED')
    require([r['flow_id'] for r in summary['stage1']]==[flow(m) for m in recipe['fusion_methods']]
        and [r['flow_id'] for r in summary['stage2']]==[flow(method,p['risk_method'],p['allocation_method']) for p in recipe['stage2']],
        'ALL_CHILD_ACCOUNT_SELECTION_PATHS_REQUIRED')
    selected=[r for r in summary['stage2'] if r['flow_id']==summary['selected_flow']]
    require(len(selected)==1 and selected[0]['status']=='COMPLETE' and selected[0]['fusion_method']==method
        and selected[0]['fee_config']==recipe['fee_config'],'SELECTED_ACCOUNT_RULES_REQUIRED');chosen=selected[0]
    diagnostics=summary['sensitivities']
    require([r['flow_id'] for r in diagnostics]==[flow(method,chosen['risk_method'],chosen['allocation_method'],d['tag']) for d in recipe['diagnostic_sensitivities']],
        'FIXED_DIAGNOSTIC_DISPOSITIONS_REQUIRED')
    accounts=[_account_record(run,r,ef_ref,continuation=True) for r in summary['stage1']+summary['stage2']+diagnostics]
    final_risk=_account_record(run,summary['final_risk_receipt'],ef_ref,final_risk=True,continuation=True)
    require(final_risk['flow_id']==summary['selected_flow'],'SELECTED_FINAL_RISK_CHANGED')
    dr=summary['sensitivity_final_risk']
    require([r['selected_flow'] for r in dr]==[r['flow_id'] for r in diagnostics if r['status']=='COMPLETE'],'DIAGNOSTIC_FINAL_RISK_CLOSURE_REQUIRED')
    risks=[_account_record(run,r,ef_ref,final_risk=True,continuation=True) for r in dr]
    completion,completed=_final_calibration_completion(run,ef,models,fusions,facts['scope_ref'])
    selected_models=[e for e in completed if e['kind']=='predictor' and e['slot']['horizon']==5 and e['slot']['model_id'] in fusion.CORE]
    sf=[e for e in completed if e['kind']=='fusion' and e['slot']['method']==method]
    require(len(selected_models)==5 and len(sf)==1,'COMPLETE_SELECTED_FINAL_CALIBRATED_CORE5_REQUIRED')
    source_custody=_child_source_closure(ef,ef_ref);budget=_child_fit_budget(run,facts)
    result=dict(schema='CONSENSUS_FINAL_SYSTEM_FREEZE_CONTINUATION_R2',status=STATUS,task_id=TASK,
        research_id=fusion.CONTINUATION_RESEARCH_ID,run=str(run),parent_run=str(parent),source_pins=source_pins(),
        continuation_scope_ref=facts['scope_ref'],parent_custody=refs,authorized_spec_ref=pf['authorized_spec'],
        predictor_freeze_ref=pf_ref,parent_fusion_freeze_ref=refs['fusion_freeze_ref'],fusion_freeze_ref=ff_ref,evaluation_freeze_ref=ef_ref,
        selection_summary_ref=_ref(summary_path),progress_refs=dict(parent=progress,child_fusion=child_progress),fit_budget=budget,
        candidate_predictors=models,candidate_fusions=fusions,parent_candidate_fusions=old_fusions,child_candidate_fusions=new_fusions,
        selected_predictors=selected_models,selected_fusion=sf[0],final_calibration_completion=completion,
        selected_flow=summary['selected_flow'],selected_risk=chosen['risk_method'],selected_allocation=chosen['allocation_method'],
        account_source_scope_ref=ef['account_source_scope_ref'],account_source_custody=source_custody,account_recipe=recipe,
        account_dispositions=accounts,final_risk=final_risk,diagnostic_final_risk=risks,auxiliary=_historical_auxiliary(parent,facts['audit']),
        original_failures_preserved=True,all_parent_coordinates_exact_equivalent=False,final_calibration_source_completion_required=True,
        source_policy='FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY',strict_PIT_certified=False,vintage='UNKNOWN_RETAINED',
        A2_already_exposed=True,evaluation_role='DESCRIPTIVE_DIAGNOSTIC_ONLY',fresh_blind_holdout=False,selection_feedback=False,
        legacy_literal='OLD_SOURCE_CODE_OUTCOME_LITERAL_SEEN_BY_READINESS_AGENT',actual_2026_numeric_datasets_or_test_rows_read=False,
        test_2026_numeric_read_authorized=False,FAST3_Confirmation_access=False,test_source_qualification_required=True,
        forbidden_test_updates=['fit','scale','calibration','risk estimation','selection'])
    result['semantic_sha256']=values.digest(result);return result

def _terminal_audit(run):
    spec,pf,pf_ref=predictors.contract(run,'ridge',2026,5);_,ef,ef_ref=evaluation.contract(run)
    summary_path=run/'evaluation/consensus_account_summary.json';summary=_metadata(summary_path,summary=True)
    require(summary['status'] in {'NOT_TESTABLE','FINAL_RISK_NOT_FROZEN_NO_TEST_USE'} and summary['task_id']==TASK
        and summary['freeze_ref']==ef_ref and summary['test_2026_rows_read']==0,'HONEST_NONCOMPLETE_ACCOUNT_TERMINAL_REQUIRED')
    _,_,_,ff,_,ff_ref=fusion.contract(run,'core5','equal',2026)  # fixed metadata entry, never a selected substitute.
    models,fusions,progress,fslots=_candidate_dispositions(run,spec,pf,pf_ref,ff,ff_ref)
    stage1=summary['stage1'];stage2=summary['stage2'];method=summary.get('selected_fusion')
    require([r['flow_id'] for r in stage1]==[evaluation.flow_id(m) for m in evaluation.RECIPE['fusion_methods']],
        'TERMINAL_ALL_STAGE1_DISPOSITIONS_REQUIRED')
    require((method is None and stage2==[] and not summary.get('selected_flow') and not summary.get('final_risk_receipt'))
        or (method in evaluation.RECIPE['fusion_methods'] and [r['flow_id'] for r in stage2]==[
            evaluation.flow_id(method,p['risk_method'],p['allocation_method']) for p in evaluation.RECIPE['stage2']]),
        'TERMINAL_STAGE2_SCOPE_CANNOT_BE_INVENTED')
    accounts=[_account_record(run,r,ef_ref) for r in stage1+stage2+summary.get('sensitivities',[])]
    if summary['status']=='NOT_TESTABLE':
        relevant=stage2 if method is not None else stage1
        require(not any(r['status']=='COMPLETE' for r in relevant),'NO_WINNER_TERMINAL_CANNOT_HIDE_SUCCESSFUL_PATH')
    risk=[]
    for r in ([summary['final_risk_receipt']] if 'final_risk_receipt' in summary else [])+summary.get('sensitivity_final_risk',[]):
        path=run/'models/consensus_final_policy'/r['selected_flow']/'receipt.json'
        require(Path(r['receipt_path'])==path and _metadata(path)==r and r['task_id']==TASK and r['freeze_ref']==ef_ref
            and r['status'] in {'COMPLETE','FAILED_NO_RETRY','NOT_TESTABLE'},'TERMINAL_RISK_DISPOSITION_CUSTODY_CHANGED')
        for name,pin in r.get('artifacts',{}).items():_pin(pin,path.parent/(name+'.joblib' if name=='state' else name+'.parquet'))
        risk.append(dict(status=r['status'],receipt=_ref(path),artifacts=r.get('artifacts',{})))
    auxiliary=_auxiliary_disposition(run);_pin(ef['account_source_scope_ref'])
    source_custody=_account_source_custody(ef_ref,ef['account_source_scope_ref'])
    fit_log=_ref(run/'FIT_LOG.jsonl');_pin(fit_log,run/'FIT_LOG.jsonl');authority=_account_recovery_authority(run)
    recovery=_engineering_recovery(run,ff,ff_ref,fslots,fusions,fit_log,authority)
    account_recovery=_account_recovery_history(run,authority,ef_ref,summary,_ref(summary_path),fit_log)
    custody={k:v for k,v in registry.REVIEW_SCOPE.items() if k.endswith('_ref')};_pin_tree(custody)
    result=dict(schema='CONSENSUS_RESEARCH_TERMINAL_AUDIT_R1',status='RESEARCH_TERMINAL_NO_COMPLETE_SELECTED_SYSTEM',task_id=TASK,run=str(run),
        scientific_result_status=summary['status'],selection_summary_ref=_ref(summary_path),source_pins=source_pins(),custody_refs=custody,
        predictor_freeze_ref=pf_ref,fusion_freeze_ref=ff_ref,evaluation_freeze_ref=ef_ref,account_source_scope_ref=ef['account_source_scope_ref'],
        account_source_custody=source_custody,progress_refs=progress,candidate_predictors=models,candidate_fusions=fusions,
        account_dispositions=accounts,partial_risk_dispositions=risk,auxiliary=auxiliary,fit_log_ref=fit_log,
        engineering_recovery=recovery,account_engineering_recovery=account_recovery,
        selected_fusion=method,selected_flow=summary.get('selected_flow'),complete_selected_system_frozen=False,
        source_policy='FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY',vintage='UNKNOWN_RETAINED',strict_PIT_certified=False,A2_already_exposed=True,
        fresh_blind_holdout=False,selection_feedback=False,test_2026_numeric_read_authorized=False,FAST3_Confirmation_access=False,
        audit_role='RESEARCH_TERMINAL_EVIDENCE_ONLY_NO_MODEL_SUBSTITUTE_OR_TEST_ACCESS')
    result['semantic_sha256']=values.digest(result);return result


def audit_terminal(run=EXPECTED_RUN):
    run=_run(run);require(run==EXPECTED_RUN.resolve(),'CHILD_TERMINAL_AUDIT_REQUIRES_OWN_ACCOUNT_TERMINAL_CONTRACT')
    return _terminal_audit(run)


def publish_terminal_root(run=EXPECTED_RUN):
    run=_run(run);require(run==EXPECTED_RUN.resolve(),'CHILD_TERMINAL_AUDIT_REQUIRES_OWN_ACCOUNT_TERMINAL_CONTRACT');path=run/TERMINAL_AUDIT_FILENAME
    if path.exists():
        stored=_metadata(path,summary=True);require(stored==audit_terminal(run),'TERMINAL_AUDIT_CUSTODY_CHANGED');return stored
    with predictors.fit_lock(run):
        require(not (run/'CONSENSUS_DOWNSTREAM.lock').exists() and not path.exists(),'ACTIVE_OR_EXISTING_TERMINAL_AUDIT')
        write_json_atomic(path,_terminal_audit(run))
    stored=_metadata(path,summary=True);require(stored==audit_terminal(run),'TERMINAL_AUDIT_CUSTODY_CHANGED');return stored


def validate(run=EXPECTED_RUN):
    run=_run(run);stored=_metadata(run/FILENAME,summary=True,continuation=run==fusion.CONTINUATION_RUN)
    require(stored==build(run),'FINAL_SYSTEM_FREEZE_CUSTODY_CHANGED')
    return stored


def publish_root(run=EXPECTED_RUN):
    run=_run(run);path=run/FILENAME
    if path.exists():return validate(run)
    # Rebuild inside the canonical lock so receipts cannot change between hash
    # validation and publication. The internal builder never calls fitting.
    with predictors.fit_lock(run):
        require(not (run/'CONSENSUS_DOWNSTREAM.lock').exists(),'ACTIVE_DOWNSTREAM_NO_FINAL_FREEZE')
        require(not path.exists(),'FINAL_SYSTEM_FREEZE_ALREADY_EXISTS')
        write_json_atomic(path,_build_continuation(run) if run==fusion.CONTINUATION_RUN else _build(run))
    return validate(run)


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--run',default=str(EXPECTED_RUN))
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--publish-root',action='store_true');mode.add_argument('--validate',action='store_true')
    mode.add_argument('--terminal-audit',action='store_true');mode.add_argument('--publish-terminal-root',action='store_true')
    args=parser.parse_args(argv)
    result=publish_terminal_root(args.run) if args.publish_terminal_root else audit_terminal(args.run) if args.terminal_audit else publish_root(args.run) if args.publish_root else validate(args.run) if args.validate else build(args.run)
    print(json.dumps(dict(status=result['status'],selected_flow=result.get('selected_flow'),semantic_sha256=result['semantic_sha256'],test_gate='CLOSED')))


if __name__=='__main__':main()
