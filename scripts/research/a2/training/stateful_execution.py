"""Serial V24 execution around frozen stage APIs; only metadata is inspected here.

This controller never opens forecast vectors, model objects, account ledgers or
economic reports. Stage APIs own their authorized data access and computations.
One existing FIT_LOG and ACCOUNT_PATH_LOG retain all attempts, including failures.
"""
from __future__ import annotations
import argparse
import gc
import importlib
import json
import os
import subprocess
import sys
import uuid
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
import tempfile
import time

from scripts.research.a2.training import stateful_values as values
from scripts.storage.storage_r2a import assert_write_path, write_json_atomic

HERE = Path(__file__).resolve().parent
SOURCE_PATHS = {
    'module_sha256': Path(__file__),
    'values_module_sha256': HERE/'stateful_values.py',
    'fusion_module_sha256': HERE/'stateful_fusion.py',
    'repair_transport_sha256': HERE/'stateful_value_repair.py',
    'risk_adapter_sha256': HERE/'stateful_risk.py',
    'aux_module_sha256': HERE/'stateful_aux.py',
    'replay_module_sha256': HERE/'stateful_replay.py',
    'input_reader_sha256': HERE/'stateful_inputs.py',
    'extension_module_sha256': HERE/'stateful_value_extensions.py',
    'native_source_sha256': values.NATIVE,
    'joint_risk_source_sha256': values.REPO/'scripts/research/a2/risk/joint_risk_estimators.py',
    'policy_sha256': HERE/'stateful_account.py',
    'engine_sha256': values.REPO/'scripts/research/a2/evaluation/continuous_research_account.py',
    'fast_account_sha256': values.REPO/'scripts/research/a2/retained/a2_pto_full_compat_20260928_r2/fast_account.py',
    'reference_replay_sha256': Path('D:/us-tech-quant-results/A2_STATEFUL_ACTION_AND_CASH_PRE2026_TEST2026_R1/ACCOUNT_REPLAY_R1.py'),
    'parent_binding_sha256': Path('D:/us-tech-quant-results/A2_STATEFUL_ACTION_AND_CASH_PRE2026_TEST2026_R1/INPUT_BINDING_R1.json'),
    'account_config_sha256': Path('D:/us-tech-quant-results/A2_STATEFUL_ACTION_AND_CASH_PRE2026_TEST2026_R1/R1_ACCOUNT_CONFIG.json'),
    'fusion_native_source_sha256': values.NATIVE.with_name('fusion_models.py'),
    'fusion_common_source_sha256': values.NATIVE.with_name('common.py'),
    'garch_definition_source_sha256': values.REPO/'scripts/research/a2/retained/a2_pto_full_compat_20260928_r2/risk_models.py',
    'aux_factory_source_sha256': HERE/'selector_formulations.py',
    'aux_catalog_source_sha256': values.NATIVE.with_name('risk_models.py'),
}
YEARS = (2023, 2024, 2025)
EXPECTED = dict(status='FROZEN', training_cutoff_exclusive='2026-01-01',
                test_2026_rows_read=0, max_fit_units=882,
                max_model_year_attempts=201, max_account_paths=220,
                expected_candidates=70, poll_seconds=5, replay_chunk_size=8)
TERMINAL = frozenset(('TRAINED','EXACT_REUSED','FAILED','ERROR',
                     'NOT_ATTEMPTED_COMMON_BLOCK','FITTED','EXACT_METHOD_REUSED'))


class ExecutionBlocked(RuntimeError):
    pass


def read_json(path, receipt=False):
    # Float calibration states are deliberately not materialized by the controller.
    with Path(path).open(encoding='utf-8-sig') as stream:
        return json.load(stream, **({'parse_float': lambda token: None} if receipt else {}))


def own_path(run, path):
    path = Path(path).resolve()
    if not path.is_relative_to(run.resolve()):
        raise ExecutionBlocked('ARTIFACT_OUTSIDE_OWN_RUN:'+str(path))
    return path


def record(run, path, expected_sha=None):
    path = own_path(run, path)
    actual = values.sha(path)  # Opaque streamed bytes; never decode model/prediction data.
    if expected_sha is not None and actual != expected_sha:
        raise ExecutionBlocked('ARTIFACT_PUBLICATION_PIN_CHANGED:'+str(path))
    return dict(path=str(path), sha256=actual)


def event_snapshot(run, name='FIT_LOG.jsonl', allow_partial=False):
    """Only a not-yet-newline-terminated tail may be ignored by metadata polling."""
    path=run/name
    if not path.exists():return [],False
    data=path.read_bytes()
    partial=bool(data and not data.endswith(b'\n'))
    if partial:
        if not allow_partial:
            raise ExecutionBlocked('INCOMPLETE_METADATA_APPEND_TAIL:'+name)
        data=data[:data.rfind(b'\n')+1]
    history=[]
    for line_number,line in enumerate(data.splitlines(),1):
        if not line:continue
        try:history.append(json.loads(line))
        except (json.JSONDecodeError,UnicodeDecodeError) as exc:
            raise ExecutionBlocked('INVALID_COMPLETE_LOG_LINE:'+name+':'+str(line_number)) from exc
    return history,partial


def events(run, name='FIT_LOG.jsonl'):
    return event_snapshot(run,name,allow_partial=False)[0]


def outstanding(history, account=False):
    started_name = 'ACCOUNT_PATH_ATTEMPT_STARTED' if account else 'MODEL_YEAR_ATTEMPT_STARTED'
    finished_names = ('ACCOUNT_PATH_COMPLETE','ACCOUNT_PATH_FAILED') if account else ('MODEL_YEAR_COMPLETE','MODEL_YEAR_FAILED')
    key = (lambda event:event['candidate_id']) if account else (lambda event:(event['model_id'],event['year']))
    return ({key(event) for event in history if event.get('event') == started_name}
            - {key(event) for event in history if event.get('event') in finished_names})


def budget_snapshot(config, history, account_history):
    fits = config['prior_cumulative_fit_units'] + sum(event.get('fit_units',0) for event in history if event.get('event') == 'FIT_STARTED')
    attempts = sum(event.get('event') == 'MODEL_YEAR_ATTEMPT_STARTED' for event in history)
    paths = config['prior_account_paths'] + sum(event.get('event') == 'ACCOUNT_PATH_ATTEMPT_STARTED' for event in account_history)
    if fits > 882 or attempts > 201 or paths > 220:
        raise ExecutionBlocked('RECORDED_GLOBAL_BUDGET_EXCEEDED')
    return dict(cumulative_fit_units=fits,model_year_attempts=attempts,
                account_path_attempts_cumulative=paths,prior_fit_units=18,prior_account_paths=4)


def fatal_reason(progress):
    for slot in progress.get('slots',[]):
        text = str(slot.get('failure',{}).get('message',''))
        if any(token in text for token in ('BUDGET_EXHAUSTED','GLOBAL_ATTEMPT_BUDGET',
                'FINITE_CAP_EXHAUSTED','FROZEN_SOURCE_OR_INPUT_CHANGED','SOURCE_CLOSURE_CHANGED',
                'FROZEN_SOURCE_OR_INPUT_MANIFEST_CHANGED','SOURCE_OR_INPUT_MANIFEST_CHANGED')):
            return text
    return None


def validate_progress(progress, schedule, key_fields):
    expected = [tuple(slot[field] for field in key_fields) for slot in schedule]
    actual = [tuple(slot[field] for field in key_fields) for slot in progress.get('slots',[])]
    if (len(set(expected)) != len(expected) or actual != expected
            or progress.get('expected_slots') != len(expected)
            or progress.get('status') != 'ATTEMPTS_FINISHED'
            or any(slot.get('status') not in TERMINAL for slot in progress['slots'])):
        raise ExecutionBlocked('EXACT_FROZEN_STAGE_NOT_FINISHED')
    return dict(expected_slots=len(expected),engineering_failure=fatal_reason(progress),
                status_counts={status:sum(slot.get('status')==status for slot in progress['slots'])
                               for status in sorted(TERMINAL) if any(slot.get('status')==status for slot in progress['slots'])})


def frozen_contract(run_dir,allow_partial_logs=False):
    run = Path(run_dir).resolve()
    assert_write_path(run/'EXECUTION_STATUS.json','backtest')
    config = read_json(run/'run_config.json')
    auth = config.get('execution_training',{})
    if (config.get('phase') != 'FROZEN' or config.get('strategy_version') != 'V24'
            or config.get('training_cutoff_exclusive') != '2026-01-01'
            or config.get('evaluation_years') != list(YEARS)
            or config.get('prior_cumulative_fit_units') != 18
            or config.get('prior_account_paths') != 4):
        raise ExecutionBlocked('ROOT_V24_FREEZE_PRIOR_COUNTS_OR_BOUNDARY')
    if any(auth.get(key) != value for key,value in EXPECTED.items()):
        raise ExecutionBlocked('SERIAL_EXECUTION_AUTH_NOT_FROZEN')
    pins = {key:values.sha(path) for key,path in SOURCE_PATHS.items()}
    if auth.get('module_sha256') != pins['module_sha256'] or auth.get('source_pins') != pins:
        raise ExecutionBlocked('EXECUTION_SOURCE_CLOSURE_CHANGED')
    if values.sha(run/'input_manifest.json') != auth.get('input_manifest_sha256'):
        raise ExecutionBlocked('EXECUTION_INPUT_MANIFEST_CHANGED')
    preflight = own_path(run,auth['preflight_path'])
    if values.sha(preflight) != auth.get('preflight_sha256') or read_json(preflight).get('status') != 'PASS':
        raise ExecutionBlocked('PRETRAIN_PREFLIGHT_NOT_PINNED_PASS')
    candidates_path = own_path(run,auth['candidates_path'])
    if values.sha(candidates_path) != auth.get('candidates_sha256'):
        raise ExecutionBlocked('FROZEN_CANDIDATES_CHANGED')
    candidates = read_json(candidates_path)
    if (len(candidates) != 70 or len({candidate['candidate_id'] for candidate in candidates}) != 70
            or len({candidate['scientific_tuple_sha256'] for candidate in candidates}) != 70):
        raise ExecutionBlocked('EXACT70_CANDIDATES_REQUIRED')
    fit_history,_=event_snapshot(run,allow_partial=allow_partial_logs)
    account_history,_=event_snapshot(run,'ACCOUNT_PATH_LOG.jsonl',allow_partial=allow_partial_logs)
    budget_snapshot(config,fit_history,account_history)
    return run,config,auth,candidates,pins

def configure_environment(config):
    """Future stage children only; no relocation or cleanup of existing workers."""
    paths=values.resolve(values.REPO)
    cache=Path(config['cache_directory']).resolve()
    if not cache.is_relative_to(paths.cache_root.resolve()) or cache.name!='V24':
        raise ExecutionBlocked('TASK_CACHE_DIRECTORY_NOT_CANONICAL_V24')
    temporary=cache/'tmp';joblib_tmp=temporary/'joblib';package_cache=cache/'cache'
    for folder in (temporary,joblib_tmp,package_cache):
        if not folder.resolve().is_relative_to(cache):
            raise ExecutionBlocked('TEMPORARY_DIRECTORY_ESCAPES_TASK_CACHE')
        folder.mkdir(parents=True,exist_ok=True)
    chosen=dict(JOBLIB_TEMP_FOLDER=str(joblib_tmp),TMP=str(temporary),
                TEMP=str(temporary),TMPDIR=str(temporary))
    preserved=[]
    for key,default in (('XDG_CACHE_HOME',package_cache),('TORCH_HOME',package_cache/'torch')):
        existing=os.environ.get(key)
        path=Path(existing).resolve() if existing else default.resolve()
        legal_existing=bool(existing and path.is_dir() and
            (path.is_relative_to(paths.envs_root.resolve()) or path.is_relative_to(paths.cache_root.resolve())))
        if legal_existing:
            preserved.append(key)
        else:
            path=default.resolve();path.mkdir(parents=True,exist_ok=True)
        chosen[key]=str(path)
    os.environ.update(chosen)
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    tempfile.tempdir=None
    return dict(cache_root=str(paths.cache_root.resolve()),task_cache_directory=str(cache),
        environment=chosen,preserved_existing_approved_cache_variables=preserved,
        scope='THIS_CONTROLLER_AND_FUTURE_SPAWNED_CHILDREN_ONLY',package_install_or_download=False,
        existing_workers_relocated=False,existing_temporary_files_deleted=False)


def _research_requested(run_dir):
    path=Path(run_dir)/'run_config.json'
    if not path.is_file():return False
    from scripts.research.a2.training import stateful_research_account as child
    return read_json(path).get('research_account',{}).get('namespace') in child.NAMESPACES


class Controller:
    def __init__(self,run_dir):
        self.research = _research_requested(run_dir)
        if getattr(self,'research',False):
            from scripts.research.a2.training import stateful_research_account as child
            self.run,self.config,self.auth,self.candidates=child.contract(run_dir)
            self.continuation=False
            self.pins=self.auth['source_pins']
            self.path=self.run/'EXECUTION_STATUS.json'
            self.config_sha256=values.sha(self.run/'run_config.json')
            self.state=read_json(self.path) if self.path.exists() else dict(stages={})
            identity=dict(controller_source_sha256=values.sha(Path(__file__)),
                run_config_sha256=self.config_sha256,research_auth_sha256=values.digest(self.auth))
            for key,value in identity.items():
                if self.state.get(key,value)!=value:raise ExecutionBlocked('RESEARCH_STATUS_IDENTITY_CHANGED')
            self.state.update(identity,metadata_only=True,research_account=True,
                test_2026_rows_read=0,winner_selection_by_controller=False)
            return
        self.continuation = _continuation_requested(run_dir)
        if self.continuation:
            self.run,self.config,self.auth,self.candidates = continuation_contract(run_dir)
            self.pins = self.auth['source_pins']
            self.path = self.run/'EXECUTION_STATUS.json'
            self.state = _continuation_metadata(self.run,self.path,CONTINUATION_STATUS) if self.path.exists() else dict(stages={})
            for key,value in (('controller_source_sha256',self.pins['module_sha256']),
                              ('candidates_sha256',self.auth['candidates_sha256']),
                              ('input_manifest_sha256',self.auth['input_manifest_sha256']),
                              ('continuation_auth_sha256',values.digest(self.auth))):
                if self.state.get(key,value)!=value:raise ExecutionBlocked('CONTINUATION_STATUS_IDENTITY_CHANGED')
                self.state[key]=value
            self.config_sha256=values.sha(self.run/'run_config.json')
            if self.state.get('run_config_sha256',self.config_sha256)!=self.config_sha256:
                raise ExecutionBlocked('CONTINUATION_EXISTING_RUN_CONFIG_BYTES_CHANGED')
            self.state['run_config_sha256']=self.config_sha256
            self.state.update(metadata_only=True,continuation=True,test_2026_rows_read=0,
                              winner_selection_by_controller=False)
            return
        self.run,self.config,self.auth,self.candidates,self.pins = frozen_contract(run_dir,allow_partial_logs=True)
        self.path = self.run/'EXECUTION_STATUS.json'
        self.state = read_json(self.path) if self.path.exists() else dict(stages={})
        if self.state.get('controller_source_sha256',self.pins['module_sha256']) != self.pins['module_sha256']:
            raise ExecutionBlocked('EXISTING_CONTROLLER_STATUS_SOURCE_CHANGED')
        group_pins={key:values.digest(self.config.get(key,{}))
                    for key in ('value_training','fusion_training','value_repair','risk_training','aux_training')}
        if (self.state.get('candidates_sha256',self.auth['candidates_sha256'])!=self.auth['candidates_sha256']
                or self.state.get('input_manifest_sha256',self.auth['input_manifest_sha256'])!=self.auth['input_manifest_sha256']
                or self.state.get('scientific_auth_sha256',group_pins)!=group_pins):
            raise ExecutionBlocked('EXISTING_CONTROLLER_SCIENTIFIC_IDENTITY_CHANGED')
        self.group_pins=group_pins
        self.state.update(scientific_auth_sha256=group_pins,input_manifest_sha256=self.auth['input_manifest_sha256'])
        self.state.update(metadata_only=True,controller_source_sha256=self.pins['module_sha256'],
                          candidates_sha256=self.auth['candidates_sha256'],test_2026_rows_read=0)

    def save(self,status,stage,**metadata):
        self.state.update(status=status,stage=stage,**metadata)
        if getattr(self,'research',False):
            from scripts.research.a2.training import stateful_research_account as child
            self.state['budget']=child.history_budget(self.run,self.candidates,child.namespace(self.auth))
            write_json_atomic(self.path,self.state)
            return
        if self.continuation:
            try:self.state['budget']=continuation_budget(self.run,self.config,self.auth,self.candidates)
            except Exception as exc:
                if status!='BLOCKED':raise
                self.state['budget_violation_code']=str(exc).split(':',1)[0]
            write_json_atomic(self.path,self.state)
            return
        fit_history,fit_partial=event_snapshot(self.run,allow_partial=True)
        account_history,account_partial=event_snapshot(self.run,'ACCOUNT_PATH_LOG.jsonl',allow_partial=True)
        self.state['budget'] = budget_snapshot(self.config,fit_history,account_history)
        self.state['metadata_partial_tail']=dict(fit_log=fit_partial,account_log=account_partial,
            snapshot_excludes_unterminated_tail=fit_partial or account_partial)
        write_json_atomic(self.path,self.state)

    def guard(self,need_fit=False):
        if getattr(self,'research',False):
            if need_fit:raise ExecutionBlocked('RESEARCH_ACCOUNT_EXACT_REUSE_NO_NEW_FIT')
            from scripts.research.a2.training import stateful_research_account as child
            if values.sha(self.run/'run_config.json')!=self.config_sha256:
                raise ExecutionBlocked('RESEARCH_CONFIG_CHANGED_AFTER_START')
            _,cfg,auth,candidates=child.contract(self.run)
            if (cfg,auth,candidates)!=(self.config,self.auth,self.candidates):
                raise ExecutionBlocked('RESEARCH_IDENTITY_CHANGED_AFTER_START')
            return child.history_budget(self.run,self.candidates,child.namespace(self.auth))
        if self.continuation:
            if need_fit:raise ExecutionBlocked('CONTINUATION_REUSE_ONLY_NO_FIT_AUTHORIZATION')
            if values.sha(self.run/'run_config.json')!=self.config_sha256:
                raise ExecutionBlocked('CONTINUATION_RUN_CONFIG_BYTES_CHANGED_AFTER_START')
            _,cfg,auth,candidates=continuation_contract(self.run)
            if auth!=self.auth or candidates!=self.candidates or cfg!=self.config:
                raise ExecutionBlocked('CONTINUATION_IDENTITY_CHANGED_AFTER_START')
            return _continuation_events(self.run,'FIT_LOG.jsonl')
        _,self.config,self.auth,candidates,pins = frozen_contract(self.run)
        if pins != self.pins or candidates != self.candidates:
            raise ExecutionBlocked('EXECUTION_IDENTITY_CHANGED_AFTER_START')
        if any(values.digest(self.config.get(key,{}))!=pin for key,pin in self.group_pins.items()):
            raise ExecutionBlocked('SCIENTIFIC_STAGE_AUTH_CHANGED_AFTER_START')
        history = events(self.run)
        if outstanding(history):
            raise ExecutionBlocked('OUTSTANDING_FIT_ATTEMPT_NO_CONCURRENT_WRITER')
        budget = budget_snapshot(self.config,history,events(self.run,'ACCOUNT_PATH_LOG.jsonl'))
        if need_fit and (budget['cumulative_fit_units'] >= 882 or budget['model_year_attempts'] >= 201):
            raise ExecutionBlocked('GLOBAL_FIT_OR_MODEL_YEAR_BUDGET_EXHAUSTED')
        return history

    def run_continuation(self):
        if not self.continuation:raise ExecutionBlocked('CONTINUATION_DISPATCH_REQUIRED')
        return _run_continuation_controller(self)

    def can_fit(self):
        self.guard()
        snapshot=budget_snapshot(self.config,events(self.run),events(self.run,'ACCOUNT_PATH_LOG.jsonl'))
        allowed=snapshot['cumulative_fit_units']<882 and snapshot['model_year_attempts']<201
        if not allowed:
            self.state['additional_fits_blocked']=dict(reason='GLOBAL882_OR_MODEL_YEAR201_EXHAUSTED',
                engineering_block=True,budget=snapshot,account_and_report_legal_with_qualified_inputs=True)
        return allowed

    def blocked_fit_stage(self,name,expected_slots,attempted_slots=0):
        self.state['stages'][name]=dict(status='BLOCKED_ADDITIONAL_FITS_GLOBAL_BUDGET',
            expected_slots=expected_slots,attempted_slots=attempted_slots,scientific_complete=False)
        self.save('RUNNING',name.upper()+'_FIT_BLOCKED_ACCOUNT_REPORT_CONTINUE')

    def wait_value(self,sleep=time.sleep):
        from scripts.research.a2.training.stateful_fusion import validate_value_batch_complete
        schedule = self.config['value_training']['ordered_schedule']
        if len(schedule) != 93 or len({(slot['model_id'],slot['year']) for slot in schedule}) != 93:
            raise ExecutionBlocked('EXACT_VALUE93_SCHEDULE_REQUIRED')
        progress_path = self.run/'logs/value_batch_status.json'
        while True:
            frozen_contract(self.run,allow_partial_logs=True)
            history,partial_tail = event_snapshot(self.run,allow_partial=True)
            progress = read_json(progress_path) if progress_path.exists() else {}
            actual = [(slot.get('model_id'),slot.get('year')) for slot in progress.get('slots',[])]
            expected = [(slot['model_id'],slot['year']) for slot in schedule]
            if actual != expected[:len(actual)] or len(actual)>93:
                raise ExecutionBlocked('VALUE_PROGRESS_NOT_EXACT_FROZEN_ORDERED_PREFIX')
            if progress and progress.get('status') not in ('RUNNING','ATTEMPTS_FINISHED'):
                raise ExecutionBlocked('VALUE_PROGRESS_STATUS_NOT_OWN_CANONICAL_BATCH')
            reason = fatal_reason(progress)
            snapshot=budget_snapshot(self.config,history,event_snapshot(self.run,'ACCOUNT_PATH_LOG.jsonl',allow_partial=True)[0])
            global_exhausted=snapshot['cumulative_fit_units']>=882 or snapshot['model_year_attempts']>=201
            if reason and not global_exhausted and not partial_tail and not outstanding(history):
                raise ExecutionBlocked('VALUE_BATCH_STOPPED_ENGINEERING_SOURCE:'+reason)
            if global_exhausted and not partial_tail and not outstanding(history) and len(actual)<93:
                self.state['additional_fits_blocked']=dict(reason='VALUE_UNFINISHED_GLOBAL882_OR201',
                    engineering_block=True,budget=snapshot,account_and_report_legal_with_qualified_inputs=True)
                self.state['stages']['value']=dict(status='BLOCKED_UNFINISHED_GLOBAL_BUDGET',
                    expected_slots=93,attempted_slots=len(actual),scientific_complete=False)
                self.save('RUNNING','VALUE_FIT_BLOCKED_ACCOUNT_REPORT_CONTINUE')
                return
            try:
                validate_value_batch_complete(self.config,progress)
                summary = validate_progress(progress,schedule,('model_id','year'))
            except (RuntimeError,ExecutionBlocked):
                if progress.get('status') == 'ATTEMPTS_FINISHED':
                    raise ExecutionBlocked('FINISHED_VALUE_BATCH_IDENTITY_INVALID')
            else:
                if not partial_tail and not outstanding(history):
                    self.state['stages']['value'] = dict(status='COMPLETED',**summary)
                    self.save('RUNNING','VALUE_FINISHED')
                    return
            self.save('WAITING','VALUE_METADATA_ONLY',observed_value_slots=len(progress.get('slots',[])),
                      outstanding_fit_attempts=len(outstanding(history)),observed_partial_tail=partial_tail)
            sleep(5)

    def stage(self,name,module,schedule,key_fields,attempt_ids):
        self.guard()
        path = self.run/f'logs/{name}_batch_status.json'
        if path.exists():
            progress = read_json(path)
            try:summary = validate_progress(progress,schedule,key_fields)
            except ExecutionBlocked:
                actual=[tuple(slot[field] for field in key_fields) for slot in progress.get('slots',[])]
                expected=[tuple(slot[field] for field in key_fields) for slot in schedule]
                if actual==expected[:len(actual)] and not self.can_fit():
                    self.blocked_fit_stage(name,len(schedule),len(actual))
                    return
                raise
            self.state['stages'][name] = dict(status='REUSED_COMPLETED_STAGE',**summary)
            self.save('RUNNING',name.upper()+'_FINISHED')
            return
        previous = self.state['stages'].get(name,{})
        if previous or any(event.get('event')=='MODEL_YEAR_ATTEMPT_STARTED'
                           and event.get('model_id') in attempt_ids for event in events(self.run)):
            raise ExecutionBlocked('EXISTING_STAGE_ATTEMPTS_WITHOUT_COMPLETE_PROGRESS_NO_RETRY:'+name)
        if not self.can_fit():
            self.blocked_fit_stage(name,len(schedule))
            return
        self.state['stages'][name] = dict(status='STARTED')
        self.save('RUNNING',name.upper())
        module.run_batch(self.run)
        progress=read_json(path)
        try:summary = validate_progress(progress,schedule,key_fields)
        except ExecutionBlocked:
            actual=[tuple(slot[field] for field in key_fields) for slot in progress.get('slots',[])]
            expected=[tuple(slot[field] for field in key_fields) for slot in schedule]
            if actual==expected[:len(actual)] and not self.can_fit():
                self.blocked_fit_stage(name,len(schedule),len(actual))
                return
            raise
        self.guard()
        self.state['stages'][name] = dict(status='COMPLETED',**summary)
        self.save('RUNNING',name.upper()+'_FINISHED')
        gc.collect()

    def repair(self,module):
        from scripts.research.a2.training.stateful_inputs import InputReader
        reader = None
        for year in YEARS:
            self.guard()
            key = 'ebm_repair_'+str(year)
            rp = self.run/'models/value/ebm'/str(year)/module.GENERATION/'fit_receipt.json'
            history = events(self.run)
            attempted = any(event.get('event')=='MODEL_YEAR_ATTEMPT_STARTED'
                            and event.get('model_id')==module.LEDGER_ID and event.get('year')==year for event in history)
            old = read_json(rp,receipt=True) if rp.exists() else {}
            if old.get('status') == 'FAILED':
                self.state['stages'][key] = dict(status='FAILED_PRESERVED',failure=old.get('failure'),
                                               receipt_path=str(rp))
                self.save('RUNNING',key.upper())
                continue
            publication_path=self.run/'predictions/value/ebm'/f'{year}.receipt.json'
            if old.get('status')=='TRAINED' and publication_path.exists():
                module.frozen_contract(self.run,year)
                packet,missing=value_packet(self.run,'ebm','value',self.config)
                if str(year) not in packet['annual']:
                    raise ExecutionBlocked('TRAINED_REPAIR_PUBLICATION_NOT_QUALIFIED:'+str(year))
                self.state['stages'][key]=dict(status='REUSED_COMPLETED_STAGE',receipt_path=str(rp),
                    prediction_receipt_path=str(publication_path))
                self.save('RUNNING',key.upper())
                continue
            if (attempted and old.get('status')!='TRAINED') or (not old and key in self.state['stages']):
                raise ExecutionBlocked('INCOMPLETE_TECHNICAL_REPAIR_NO_SECOND_RETRY:'+str(year))
            if old.get('status')!='TRAINED' and not self.can_fit():
                self.blocked_fit_stage(key,1)
                continue
            self.state['stages'][key] = dict(status='STARTED_OR_EXACT_REUSE')
            self.save('RUNNING',key.upper())
            try:
                if reader is None:reader = InputReader(self.run)
                fitted = module.repair_annual(year,self.run,reader=reader)
                publication = module.publish_prediction(fitted,reader,self.run,year)
                self.state['stages'][key] = dict(status='COMPLETED',receipt_path=fitted.receipt['receipt_path'],
                    prediction_receipt_path=str(Path(publication['path']).with_suffix('.receipt.json')))
                del fitted,publication
            except Exception as exc:
                self.state['stages'][key] = dict(status='FAILED_PRESERVED',
                    failure=dict(type=type(exc).__name__,message=str(exc)))
                if fatal_reason(dict(slots=[self.state['stages'][key]])) and self.can_fit():
                    self.save('BLOCKED',key.upper())
                    raise ExecutionBlocked(str(exc)) from exc
            self.save('RUNNING',key.upper())
            gc.collect()

    def replay(self,module):
        self.guard()
        history = events(self.run,'ACCOUNT_PATH_LOG.jsonl')
        if outstanding(history,account=True):
            raise ExecutionBlocked('OUTSTANDING_ACCOUNT_ATTEMPT_NO_ALIAS_RETRY')
        started = {event['candidate_id'] for event in history if event.get('event')=='ACCOUNT_PATH_ATTEMPT_STARTED'}
        expected = {candidate['candidate_id'] for candidate in self.candidates}
        if not started.issubset(expected):
            raise ExecutionBlocked('ACCOUNT_LOG_HAS_NONFROZEN_CANDIDATE')
        pending = [candidate['candidate_id'] for candidate in self.candidates if candidate['candidate_id'] not in started]
        for offset in range(0,len(pending),8):
            chunk = pending[offset:offset+8]
            self.guard()
            if self.state['budget']['account_path_attempts_cumulative']+len(chunk)>220:
                raise ExecutionBlocked('GLOBAL_ACCOUNT_PATH_BUDGET_EXHAUSTED')
            self.save('RUNNING','REPLAY',pending_candidates=len(pending)-offset,current_chunk_ids=chunk)
            try:
                result = module.run(self.run,chunk)
                self.state.setdefault('replay_chunks',[]).append(dict(candidate_ids=chunk,status=result['status'],
                                                                      audit_path=result.get('audit_path')))
                del result
            except Exception as exc:
                self.state.setdefault('replay_chunks',[]).append(dict(candidate_ids=chunk,status='FAILED_RETAINED',
                    failure=dict(type=type(exc).__name__,message=str(exc))))
                if fatal_reason(dict(slots=[self.state['replay_chunks'][-1]])):
                    raise ExecutionBlocked(str(exc)) from exc
            after = events(self.run,'ACCOUNT_PATH_LOG.jsonl')
            consumed = {event['candidate_id'] for event in after if event.get('event')=='ACCOUNT_PATH_ATTEMPT_STARTED'}
            if not set(chunk).issubset(consumed) or outstanding(after,account=True):
                raise ExecutionBlocked('REPLAY_BEFORE_ATTEMPT_OR_UNFINISHED_NO_RETRY')
            self.save('RUNNING','REPLAY_CHUNK_FINISHED')
            gc.collect()
        self.state['stages']['replay'] = dict(status='COMPLETED_ALL70_ATTEMPTED',expected_candidates=70)
        self.save('RUNNING','REPLAY_FINISHED')


def slot_failure(run,kind,method,year,error,rp,publication):
    progress = run/f'logs/{kind}_batch_status.json'
    causes = []
    if progress.exists():
        for slot in read_json(progress).get('slots',[]):
            if slot.get('year')==year and slot.get('model_id',slot.get('method_id'))==method:
                if slot.get('failure'):causes.append(slot['failure'])
    if rp.exists():
        item=read_json(rp,receipt=True)
        if item.get('failure'):causes.append(item['failure'])
    return dict(year=year,receipt_path=str(rp),publication_path=str(publication) if publication else None,
                binding_failure=dict(type=type(error).__name__,message=str(error)),original_failures=causes)


def value_packet(run,model,kind,config):
    from scripts.research.a2.training import stateful_fusion as fusion
    source_kind = 'V24_FUSION_OUTPUTS' if kind=='fusion' else 'V24_VALUE_OUTPUTS'
    packet = dict(source_kind=source_kind,annual={})
    failures = []
    for year in YEARS:
        rp = run/f'models/{kind}'/model/str(year)/'fit_receipt.json'
        if model=='ebm' and kind=='value':
            rp = rp.parent/'technical_repair_1/fit_receipt.json'
        prediction = run/f'predictions/{kind}'/model/f'{year}.parquet'
        publication = prediction.with_suffix('.receipt.json')
        try:
            receipt = read_json(rp,receipt=True)
            if (receipt.get('status') not in ('TRAINED','EXACT_REUSED') or receipt.get('year')!=year
                    or receipt.get('model_id')!=model or receipt.get('scientific_target_qualified') is not True
                    or receipt.get('scientific_feature_pit_qualified') is not True):
                raise ValueError('UNQUALIFIED_OR_FAILED_ANNUAL_VALUE_RECEIPT')
            reuse = receipt.get('reuse_tuple',{})
            pins = reuse.get('source_pins',{})
            producer = values.sha(fusion.__file__) if kind=='fusion' else values.sha(values.__file__)
            if (reuse.get('label_definition')!=values.LABEL or reuse.get('fold')!=f'ANNUAL_{year}'
                    or pins.get('module_sha256')!=producer
                    or pins.get('input_manifest_sha256')!=values.sha(run/'input_manifest.json')):
                raise ValueError('VALUE_RECEIPT_SOURCE_OR_TARGET_IDENTITY')
            if model=='ebm' and (receipt.get('generation')!='technical_repair_1'
                    or pins.get('repair_transport_sha256')!=values.sha(HERE/'stateful_value_repair.py')):
                raise ValueError('EBM_REPAIR_RECEIPT_NOT_QUALIFIED')
            fit_record = record(run,rp)
            pub = read_json(publication,receipt=True)
            if (pub.get('status')!='PUBLISHED' or pub.get('year')!=year or pub.get('model_id')!=model
                    or pub.get('test_2026_rows_read')!=0 or pub.get('producer_source_sha256')!=producer
                    or pub.get('input_manifest_sha256')!=values.sha(run/'input_manifest.json')
                    or pub.get('fit_receipt_sha256')!=fit_record['sha256']
                    or pub.get('reuse_tuple_sha256')!=receipt.get('reuse_tuple_sha256')
                    or pub.get('model_sha256')!=receipt.get('model_sha256')
                    or Path(pub.get('path','')).resolve()!=prediction.resolve()
                    or Path(pub.get('fit_receipt_path','')).resolve()!=rp.resolve()):
                raise ValueError('MODEL_OOF_PUBLICATION_CLOSURE')
            record(run,receipt['model_path'],receipt['model_sha256'])
            annual = dict(receipt=fit_record,prediction=record(run,prediction,pub['sha256']),
                          prediction_receipt=record(run,publication))
            if kind=='value':annual['native_diagnostic_columns']=values.diagnostic_columns(model)
            packet['annual'][str(year)] = annual
        except Exception as exc:
            failures.append(slot_failure(run,kind,model,year,exc,rp,publication))
    return packet,failures


def bind_replay(controller,replay,risk):
    run = controller.run
    history = events(run,'ACCOUNT_PATH_LOG.jsonl')
    existing = controller.state['stages'].get('bindings',{})
    if history:
        if existing.get('status')!='COMPLETED' or values.digest(controller.config.get('stateful_replay',{}))!=existing.get('auth_sha256'):
            raise ExecutionBlocked('ACCOUNT_ATTEMPTS_REQUIRE_ORIGINAL_METADATA_BINDING')
        return
    value_packets,failures = {},{}
    for model in values.FIRST_MODELS:
        packet,missing = value_packet(run,model,'value',controller.config)
        value_packets[model]=packet
        if missing:failures[model]=missing
    from scripts.research.a2.training import stateful_fusion as fusion
    for model in fusion.METHODS.values():
        key='fusion::'+model
        packet,missing=value_packet(run,model,'fusion',controller.config)
        value_packets[key]=packet
        if missing:failures[key]=missing
    risk_packets = {}
    for method in risk.METHODS:
        if method=='HISTVOL':continue
        packet=dict(annual={});missing=[]
        for year in YEARS:
            rp=run/'models/risk'/method/str(year)/'fit_receipt.json'
            try:
                receipt=read_json(rp,receipt=True);reuse=receipt.get('reuse_tuple',{})
                if (receipt.get('status')!='FITTED' or receipt.get('method_id')!=method
                        or receipt.get('year')!=year or receipt.get('scientific_feature_pit_qualified') is not True
                        or receipt.get('scientific_return_proxy_qualified') is not True
                        or reuse.get('return_unit')!=risk.UNIT or reuse.get('return_horizon_sessions')!=1
                        or reuse.get('window_sessions')!=63 or reuse.get('annual_static') is not True
                        or reuse.get('source_pins',{}).get('joint_source_sha256')!=risk.JOINT_SHA):
                    raise ValueError('UNQUALIFIED_STATIC63_PIT_PROXY_RISK_RECEIPT')
                packet['annual'][str(year)]=dict(receipt=record(run,rp),
                    bundle=record(run,receipt['model_path'],receipt['model_sha256']))
            except Exception as exc:
                missing.append(slot_failure(run,'risk',method,year,exc,rp,None))
        risk_packets[method]=packet
        if missing:failures['risk::'+method]=missing
    config=read_json(run/'run_config.json')
    auth=dict(config.get('stateful_replay',{}))
    auth.update({key:values.sha(path) for key,path in replay.SOURCE_PATHS.items()})
    auth.update(status='FROZEN',input_manifest_sha256=controller.auth['input_manifest_sha256'],
        candidates_path=controller.auth['candidates_path'],candidates_sha256=controller.auth['candidates_sha256'],
        max_account_paths=220,value_packets=value_packets,risk_packets=risk_packets,
        fusion_module_sha256=controller.pins['fusion_module_sha256'],
        value_repair_transport_sha256=controller.pins['repair_transport_sha256'],
        risk_module_sha256=risk.JOINT_SHA,risk_static_window_sessions=63,risk_return_unit=risk.UNIT,
        risk_horizon_conversion='IID_1D_COVARIANCE_TIMES_5',packet_binding_failures=failures)
    config['stateful_replay']=auth
    write_json_atomic(run/'run_config.json',config)
    controller.config=config
    controller.state['stages']['bindings']=dict(status='COMPLETED',auth_sha256=values.digest(auth),
        value_method_count=len(value_packets),risk_method_count=len(risk_packets),failures=failures,
        missing_annual_count=sum(len(items) for items in failures.values()),selection_used=False)
    controller.save('RUNNING','REPLAY_SOURCES_BOUND_METADATA_ONLY')
    replay.frozen_contract(run)



# R2 is a continuation phase of this controller. R1 SOURCE_PATHS and stage APIs
# are intentionally retained; the parent source bytes remain in child custody.
CONTINUATION_SOURCE_PATHS = {**SOURCE_PATHS,
    'metadata_reader_sha256':HERE/'stateful_completion.py',
    'corporate_transition_source_sha256':values.REPO/'scripts/v22/corporate_action_transition_r1.py'}
CONTINUATION_NAMESPACE='R2'
R5_NAMESPACE='A_SOURCE_ACCOUNT_R5'
# This R5 extends one approved identity; these are metadata identities, not source authority.
R5_FROZEN37_MANIFEST_SHA256='c0ca38578f0879c2c477c02996487e971a85060b5a86c115acc979a5fcabb3ed'
R5_SOURCE_CANDIDATE_CATALOGUE_SHA256='611930988eeec394f8a2d5ac0466f63b382a02d87a362afcf361d0886495aeb8'
R5_SOURCE_SLOTS=('market_quote_authority','MKFG_settlement_authority',
    'MKFG_terminal_binding','security_identity_binding','cash_source_bundle')
CONTINUATION_LOCK_ENV='USTQ_CONTINUATION_LOCK_TOKEN'


def _metadata_schemas():
    from scripts.research.a2.training import stateful_completion as meta
    a=meta.ALL
    ref={'path':a,'sha256':a}
    packet={'source_kind':a,'annual':{'*':{'receipt':ref,'prediction':ref,
        'prediction_receipt':ref,'bundle':ref,'native_diagnostic_columns':a}}}
    auth={k:a for k in ('status','reuse_only','module_sha256','input_manifest_sha256',
        'parent_run_config_sha256','parent_input_manifest_sha256','parent_fit_log_sha256',
        'parent_account_log_sha256','candidates_path','candidates_sha256','preflight_path',
        'preflight_sha256','baseline_candidate_id','diagnostic_candidate_ids','expected_candidates',
        'max_new_fit_units','max_new_account_paths','replay_chunk_size','poll_seconds',
        'worker_timeout_seconds','controller_custody_sha256','risk_module_sha256',
        'risk_static_window_sessions','risk_return_unit','risk_horizon_conversion',
        'qualification_only','namespace','source_account_binding','source_decision','frozen37_reference')}
    auth['source_pins']={k:a for k in CONTINUATION_SOURCE_PATHS}
    auth['value_packets']={'*':packet};auth['risk_packets']={'*':packet}
    config={k:a for k in ('phase','strategy_version','training_cutoff_exclusive','evaluation_years',
        'capital_usd','parent_run_dir','prior_cumulative_fit_units','prior_account_paths',
        'cache_directory','test_2026_rows_read','2026_rows_read','research_id','run_id','fractional_primary')}
    config['budget']={'new_fit_units_hard_limit':a,'new_account_attempts_hard_limit':a}
    config['execution_continuation']=auth
    config['stateful_replay']={'status':a,'module_sha256':a,'value_packets':{'*':packet},
        'risk_packets':{'*':packet}}
    candidate={k:a for k in ('candidate_id','source_method_ids','action','value_model','control',
        'gross','risk','target_role','scientific_tuple_sha256','action_cost_mode','execution_friction',
        'reference_identity','forecast','diagnostic_role')}
    event={**meta.EVENT,**{k:a for k in ('module_sha256','controller_module_sha256','continuation','namespace')}}
    receipt={**meta.RECEIPT,'model_path':a,'label_definition':a}
    receipt['reuse_tuple']={**meta.RECEIPT['reuse_tuple'],**{k:a for k in (
        'label_definition','calendar_sha256','calibration_sessions','feature_binding',
        'window_sessions','annual_static','return_unit','horizon_sessions')},
        'source_pins':{'module_sha256':a,'input_manifest_sha256':a,'joint_source_sha256':a}}
    audit={**meta.AUDIT,'continuation':a,'source_run':a,'input_manifest_sha256':a,
        'policy_and_execution_cost_schedule_identical':a,
        'source_closure':{'module_sha256':a},'qualification_checks':a}
    return meta,config,auth,candidate,event,receipt,audit


def _continuation_metadata(run,path,schema):
    meta=_metadata_schemas()[0]
    return meta.read_metadata(Path(run).resolve(),path,schema)


def _continuation_requested(run):
    path=Path(run).resolve()/'run_config.json'
    # Dispatch never reads scientific vectors, outcomes or calibration states.
    meta=_metadata_schemas()[0]
    cfg=meta.read_metadata(path.parent,path,{'execution_continuation':{'status':meta.ALL}})
    return 'execution_continuation' in cfg


def _continuation_events(run,name):
    meta,_,_,_,schema,_,_=_metadata_schemas()
    path=own_path(Path(run).resolve(),Path(run)/name)
    if not path.exists():return []
    if path.stat().st_size:
        with path.open('rb') as tail:
            tail.seek(-1,2)
            if tail.read(1)!=b'\n':raise ExecutionBlocked('CONTINUATION_INCOMPLETE_METADATA_APPEND_TAIL')
    history=[]
    with path.open(encoding='utf-8-sig') as stream:
        while True:
            parser=meta._Projection(stream);parser.ws()
            if not parser.c:break
            item=parser.value(schema);meta._boundary(item);history.append(item)
            if parser.c and not parser.c.isspace():raise ExecutionBlocked('CONTINUATION_LOG_DELIMITER')
    return history


def _positive_integer(value,code,limit):
    if isinstance(value,bool) or not isinstance(value,int) or not 1<=value<=limit:
        raise ExecutionBlocked(code)
    return value


def _sha_identity(value):
    return isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)


def _metadata_ref(parent,ref,*,opaque=False):
    if not isinstance(ref,dict) or not _sha_identity(ref.get('sha256')):
        raise ExecutionBlocked('CONTINUATION_PACKET_REFERENCE_INVALID')
    path=own_path(parent,ref['path'])
    if not path.is_file():raise ExecutionBlocked('CONTINUATION_PACKET_MISSING')
    # Model/forecast bytes belong to the replay worker. It checks their physical
    # pins before numerical access; the controller checks publication identity.
    if not opaque and values.sha(path)!=ref['sha256']:
        raise ExecutionBlocked('CONTINUATION_METADATA_REFERENCE_CHANGED')
    return path


def _validate_packet_metadata(parent,auth,parent_config):
    meta,_,_,_,_,schema,_=_metadata_schemas()
    old=parent_config.get('stateful_replay',{})
    manifest=meta.read_metadata(parent,parent/'input_manifest.json',{'annual_folds':{'*':{k:meta.ALL for k in (
        'calendar_sha256','calibration_start','calibration_sessions','cutoff_exclusive')}}})
    for kind in ('value_packets','risk_packets'):
        packets=auth.get(kind,{})
        if not isinstance(packets,dict) or not packets:raise ExecutionBlocked('CONTINUATION_PARENT_PACKETS_REQUIRED')
        for method,packet in packets.items():
            if packet!=old.get(kind,{}).get(method):raise ExecutionBlocked('CONTINUATION_PARENT_PACKET_IDENTITY_CHANGED')
            if set(packet.get('annual',{}))!={str(y) for y in YEARS}:raise ExecutionBlocked('CONTINUATION_PACKET_REQUIRES_THREE_YEARS')
            for year in YEARS:
                entry=packet['annual'][str(year)]
                rp=_metadata_ref(parent,entry['receipt'])
                receipt=meta.read_metadata(parent,rp,schema)
                if receipt.get('year')!=year or receipt.get('scientific_feature_pit_qualified') is not True:
                    raise ExecutionBlocked('CONTINUATION_PACKET_YEAR_OR_PIT_UNQUALIFIED')
                tup=receipt.get('reuse_tuple',{})
                if kind=='value_packets':
                    if (receipt.get('status') not in ('TRAINED','EXACT_REUSED')
                            or receipt.get('scientific_target_qualified') is not True
                            or tup.get('fold')!=f'ANNUAL_{year}' or tup.get('label_definition')!=values.LABEL
                            or tup.get('source_pins',{}).get('input_manifest_sha256')!=auth['parent_input_manifest_sha256']):
                        raise ExecutionBlocked('CONTINUATION_VALUE_TARGET_OR_FOLD_UNQUALIFIED')
                    fold=manifest.get('annual_folds',{}).get(str(year),{})
                    if (tup.get('calendar_sha256')!=fold.get('calendar_sha256')
                            or tup.get('calibration_sessions')!=fold.get('calibration_sessions')
                            or tup.get('training_signal_and_label_maturity_exclusive')!=fold.get('calibration_start')
                            or tup.get('feature_binding',{}).get('features')!=values.feature_binding()['features']
                            or tup.get('source_pins',{}).get('module_sha256')!=auth['source_pins']['values_module_sha256']):
                        raise ExecutionBlocked('CONTINUATION_VALUE_EXACT_PARENT_FOLD_OR_FEATURE_BINDING')
                    cutoff=f'{year}-01-01'
                    cal=tup.get('training_signal_and_label_maturity_exclusive','')
                    if (str(tup.get('cutoff_exclusive',''))[:10]!=cutoff
                            or str(tup.get('calibration_label_maturity_exclusive',''))[:10]!=cutoff
                            or len(tup.get('calibration_sessions',[]))!=60 or not cal
                            or not receipt.get('train_label_maturity_max') or not receipt.get('calibration_label_maturity_max')
                            or not str(receipt['train_label_maturity_max'])<str(cal)
                            or not str(receipt.get('calibration_label_maturity_max',''))[:10]<cutoff):
                        raise ExecutionBlocked('CONTINUATION_VALUE_MATURITY_BOUNDARY')
                    _metadata_ref(parent,entry['prediction'],opaque=True)
                    if entry.get('prediction_receipt'):_metadata_ref(parent,entry['prediction_receipt'])
                else:
                    if (receipt.get('status')!='FITTED' or receipt.get('scientific_return_proxy_qualified') is not True
                            or tup.get('window_sessions')!=63 or tup.get('annual_static') is not True
                            or tup.get('source_pins',{}).get('joint_source_sha256')!=auth['risk_module_sha256']):
                        raise ExecutionBlocked('CONTINUATION_STATIC63_RISK_UNQUALIFIED')
                    dates=receipt.get('fitted_dates',[])
                    if (len(dates)!=63 or dates!=sorted(set(dates)) or any(str(d)[:10]>=f'{year}-01-01' for d in dates)
                            or tup.get('return_unit')!=auth['risk_return_unit']
                            or str(tup.get('cutoff_exclusive',''))[:10]!=f'{year}-01-01'
                            or receipt.get('model_sha256')!=entry['bundle']['sha256']):
                        raise ExecutionBlocked('CONTINUATION_RISK_DATES_CUTOFF_OR_BUNDLE_IDENTITY')
                    _metadata_ref(parent,entry['bundle'],opaque=True)


def continuation_budget(run,config,auth,candidates):
    fit=_continuation_events(run,'FIT_LOG.jsonl')
    paths=_continuation_events(run,'ACCOUNT_PATH_LOG.jsonl')
    if any(e.get('event') in ('FIT_STARTED','MODEL_YEAR_ATTEMPT_STARTED') for e in fit):
        raise ExecutionBlocked('CONTINUATION_REUSE_ONLY_UNAUTHORIZED_FIT')
    starts=[e for e in paths if e.get('event')=='ACCOUNT_PATH_ATTEMPT_STARTED']
    terminal=[e for e in paths if e.get('event') in ('ACCOUNT_PATH_COMPLETE','ACCOUNT_PATH_FAILED')]
    declared={c['candidate_id']:c for c in candidates}
    if (len(starts)>auth['max_new_account_paths'] or len(starts)>len(candidates)
            or len({e.get('candidate_id') for e in starts})!=len(starts)
            or len({e.get('scientific_tuple_sha256') for e in starts})!=len(starts)):
        raise ExecutionBlocked('CONTINUATION_ACCOUNT_BUDGET_OR_DUPLICATE_ATTEMPT')
    for event in starts+terminal:
        identity=declared.get(event.get('candidate_id'))
        if not identity or event.get('scientific_tuple_sha256')!=identity['scientific_tuple_sha256']:
            raise ExecutionBlocked('CONTINUATION_UNDECLARED_ACCOUNT_IDENTITY')
        if (event.get('continuation') is not True or event.get('namespace')!=auth.get('namespace',CONTINUATION_NAMESPACE)
                or event.get('module_sha256')!=auth['source_pins']['replay_module_sha256']
                or event.get('controller_module_sha256')!=auth['module_sha256']):
            raise ExecutionBlocked('CONTINUATION_EVENT_PRODUCER_IDENTITY')
    if starts and starts[0].get('candidate_id')!=auth['baseline_candidate_id']:
        raise ExecutionBlocked('CONTINUATION_PRIMARY_BASELINE_MUST_BE_FIRST')
    if any(e.get('path_units')!=1 for e in starts):raise ExecutionBlocked('CONTINUATION_EXACT_ONE_PATH_UNIT')
    counts=Counter(e['candidate_id'] for e in terminal)
    if any(n!=1 for n in counts.values()) or not set(counts).issubset({e['candidate_id'] for e in starts}):
        raise ExecutionBlocked('CONTINUATION_TERMINAL_WITHOUT_UNIQUE_START')
    return dict(prior_fit_units=config['prior_cumulative_fit_units'],new_fit_units=0,
        cumulative_fit_units=config['prior_cumulative_fit_units'],new_fit_units_hard_limit=auth['max_new_fit_units'],
        fit_authorization='NONE_REUSE_ONLY',prior_account_paths=config['prior_account_paths'],
        new_account_path_attempts=len(starts),account_path_attempts_cumulative=config['prior_account_paths']+len(starts),
        new_account_path_hard_limit=auth['max_new_account_paths'],completed=sum(e['event']=='ACCOUNT_PATH_COMPLETE' for e in terminal),
        failed=sum(e['event']=='ACCOUNT_PATH_FAILED' for e in terminal),outstanding=len(starts)-len(terminal))


def continuation_contract(run_dir):
    run=Path(run_dir).resolve();assert_write_path(run/'EXECUTION_STATUS.json','backtest')
    meta,config_schema,_,candidate_schema,_,_,_=_metadata_schemas()
    cfg=meta.read_metadata(run,run/'run_config.json',config_schema);auth=cfg.get('execution_continuation',{})
    qualification=auth.get('qualification_only') is True
    r5=auth.get('namespace')==R5_NAMESPACE
    prior_paths=89 if r5 else 88 if qualification else 74
    if (cfg.get('phase')!='FROZEN' or cfg.get('strategy_version')!='V24'
            or cfg.get('training_cutoff_exclusive')!='2026-01-01' or cfg.get('evaluation_years')!=list(YEARS)
            or cfg.get('capital_usd')!=3000 or cfg.get('prior_cumulative_fit_units')!=455
            or cfg.get('prior_account_paths')!=prior_paths or auth.get('status')!='FROZEN' or auth.get('reuse_only') is not True):
        raise ExecutionBlocked('CONTINUATION_FREEZE_OR_BOUNDARY_REQUIRED')
    fit_cap,path_cap=(0,38) if r5 else (0,1) if qualification else (72,80)
    if (auth.get('max_new_fit_units')!=fit_cap or auth.get('max_new_account_paths')!=path_cap
            or cfg.get('budget',{}).get('new_fit_units_hard_limit')!=fit_cap
            or cfg.get('budget',{}).get('new_account_attempts_hard_limit')!=path_cap):
        raise ExecutionBlocked('CONTINUATION_EXACT_BOUNDED_REUSE_AUTH_REQUIRED')
    _positive_integer(auth.get('replay_chunk_size'),'CONTINUATION_CHUNK_BOUND',8)
    _positive_integer(auth.get('worker_timeout_seconds'),'CONTINUATION_WORKER_TIMEOUT_BOUND',7200)
    if auth.get('poll_seconds')!=5:raise ExecutionBlocked('CONTINUATION_POLL_BOUND')
    pins={key:values.sha(path) for key,path in CONTINUATION_SOURCE_PATHS.items()}
    if auth.get('source_pins')!=pins or auth.get('module_sha256')!=pins['module_sha256']:
        raise ExecutionBlocked('CONTINUATION_CURRENT_SOURCE_CLOSURE_CHANGED')
    custody=own_path(run,run/'contracts/source_custody/stateful_execution.py')
    if not _sha_identity(auth.get('controller_custody_sha256')) or values.sha(custody)!=auth['controller_custody_sha256']:
        raise ExecutionBlocked('CONTINUATION_PRIOR_CONTROLLER_CUSTODY_CHANGED')
    if values.sha(run/'input_manifest.json')!=auth.get('input_manifest_sha256'):
        raise ExecutionBlocked('CONTINUATION_INPUT_MANIFEST_CHANGED')
    manifest=meta.read_metadata(run,run/'input_manifest.json',{k:meta.ALL for k in (
        'inputs_verified','training_cutoff_exclusive','source_reader_sha256','reuse_only','parent_input_manifest_sha256')})
    if (manifest.get('inputs_verified') is not True or manifest.get('training_cutoff_exclusive')!='2026-01-01'
            or manifest.get('source_reader_sha256')!=pins['input_reader_sha256']
            or manifest.get('parent_input_manifest_sha256')!=auth.get('parent_input_manifest_sha256')
            or manifest.get('reuse_only') is not True):
        raise ExecutionBlocked('CONTINUATION_REUSE_INPUT_MANIFEST_UNQUALIFIED')
    parent=Path(cfg['parent_run_dir']).resolve()
    root=values.resolve(values.REPO).backtest_root.resolve()
    if parent==run or not parent.is_relative_to(root):raise ExecutionBlocked('CONTINUATION_PARENT_RUN_OUTSIDE_CANONICAL_ROOT')
    for name,key in (('run_config.json','parent_run_config_sha256'),('input_manifest.json','parent_input_manifest_sha256'),
                     ('FIT_LOG.jsonl','parent_fit_log_sha256'),('ACCOUNT_PATH_LOG.jsonl','parent_account_log_sha256')):
        if values.sha(own_path(parent,parent/name))!=auth.get(key):raise ExecutionBlocked('CONTINUATION_PARENT_CUSTODY_CHANGED:'+name)
    parent_cfg=meta.read_metadata(parent,parent/'run_config.json',config_schema)
    parent_fit=_continuation_events(parent,'FIT_LOG.jsonl');parent_paths=_continuation_events(parent,'ACCOUNT_PATH_LOG.jsonl')
    prior_fits=parent_cfg.get('prior_cumulative_fit_units',0)+sum(e.get('fit_units',0) for e in parent_fit if e.get('event')=='FIT_STARTED')
    prior_paths=parent_cfg.get('prior_account_paths',0)+sum(e.get('event')=='ACCOUNT_PATH_ATTEMPT_STARTED' for e in parent_paths)
    if (parent_cfg.get('phase')!='FROZEN' or parent_cfg.get('evaluation_years')!=list(YEARS)
            or parent_cfg.get('training_cutoff_exclusive')!='2026-01-01' or prior_fits!=455 or prior_paths!=74
            or outstanding(parent_fit) or outstanding(parent_paths,account=True)):
        raise ExecutionBlocked('CONTINUATION_PARENT_HISTORY_NOT_COMPLETE_BOUND_IDENTITY')
    preflight=own_path(run,auth['preflight_path'])
    gate=meta.read_metadata(run,preflight,{'status':meta.ALL,'test_2026_rows_read':meta.ALL,'2026_rows_read':meta.ALL})
    if values.sha(preflight)!=auth.get('preflight_sha256') or gate.get('status')!='PASS':
        raise ExecutionBlocked('CONTINUATION_PREFLIGHT_NOT_PINNED_PASS')
    cp=own_path(run,auth['candidates_path'])
    if values.sha(cp)!=auth.get('candidates_sha256'):raise ExecutionBlocked('CONTINUATION_CANDIDATES_CHANGED')
    candidates=meta.read_metadata(run,cp,[candidate_schema])
    n=_positive_integer(auth.get('expected_candidates'),'CONTINUATION_CANDIDATE_BOUND',80)
    ids=[c.get('candidate_id') for c in candidates];tuples=[c.get('scientific_tuple_sha256') for c in candidates]
    if len(candidates)!=n or len(set(ids))!=n or any(not isinstance(i,str) or not i for i in ids) or len(set(tuples))!=n or any(not _sha_identity(t) for t in tuples):
        raise ExecutionBlocked('CONTINUATION_EXACT_EXPLICIT_CANDIDATES_REQUIRED')
    diagnostics=auth.get('diagnostic_candidate_ids',[]);baseline=auth.get('baseline_candidate_id')
    if not isinstance(diagnostics,list) or len(set(diagnostics))!=len(diagnostics) or not set(diagnostics).issubset(ids) or baseline not in diagnostics:
        raise ExecutionBlocked('CONTINUATION_EXPLICIT_DIAGNOSTIC_GROUP_REQUIRED')
    for c in candidates:
        if (not all(k in c for k in ('source_method_ids','action','value_model','control','gross','risk','target_role'))
                or c['value_model'] not in ('ridge','hgb') or c.get('action_cost_mode') not in ('blind','aware')
                or c['action'] not in ('raw','stateful') or c['target_role']!='shareholder5d'
                or c['control'] not in ('none','no_trade_band','hysteresis','partial_rebalancing','minimum_trade_usd')
                or c['gross'] not in ('fixed','volatility_targeting','risk_constrained_cash','dynamic')
                or c.get('forecast','none') not in ('none','return_shrink','black_litterman')
                or not isinstance(c['source_method_ids'],list) or not c['source_method_ids']
                or any(not isinstance(m,str) or len(m)!=4 or not m.startswith('M') or not m[1:].isdigit()
                       or not 1<=int(m[1:])<=106 for m in c['source_method_ids'])):
            raise ExecutionBlocked('CONTINUATION_FROZEN_RAW_TWO_SUCCESSFUL_VALUE_SCOPE')
        f=c.get('execution_friction',{})
        if (set(f)!={'kind','scenario_id','one_way_bps','fee_bps','benchmark','authority'}
                or f['kind']!='FIXED_ADVERSE_OPEN_SLIPPAGE' or f['one_way_bps'] not in (5,10,20)
                or isinstance(f['one_way_bps'],bool) or f['fee_bps']!=0 or not isinstance(f['scenario_id'],str)
                or not f['scenario_id'] or f['benchmark']!='NEXT_RAW_OPEN'
                or f['authority']!='HYPOTHETICAL_RESEARCH_SCENARIO'):
            raise ExecutionBlocked('CONTINUATION_NONZERO_FIXED_FRICTION_REQUIRED_ZERO_IS_PRIOR_REFERENCE')
    b=next(c for c in candidates if c['candidate_id']==baseline)
    if (b['action']!='raw' or b['action_cost_mode']!='blind' or b['execution_friction']['one_way_bps']!=10
            or b['gross']!='fixed' or b['control']!='none' or b.get('forecast','none')!='none'):
        raise ExecutionBlocked('CONTINUATION_PRIMARY10_RAW_BASELINE_REQUIRED')
    if set(auth.get('value_packets',{}))!={'ridge','hgb'} or len(auth.get('risk_packets',{}))!=12:
        raise ExecutionBlocked('CONTINUATION_TWO_VALUE_TWELVE_COMPLETE_RISK_PACKETS_REQUIRED')
    if (auth.get('risk_module_sha256')!=pins['joint_risk_source_sha256']
            or auth.get('risk_static_window_sessions')!=63
            or auth.get('risk_return_unit')!='ACCEPTED_FROZEN_PIT32_RET_1D_PROXY_FRACTIONAL'
            or auth.get('risk_horizon_conversion')!='IID_1D_COVARIANCE_TIMES_5'):
        raise ExecutionBlocked('CONTINUATION_RISK_PROXY_UNIT_OR_HORIZON')
    if any(c['risk'] not in ('diag','diag20_reference') and c['risk'] not in auth['risk_packets'] for c in candidates):
        raise ExecutionBlocked('CONTINUATION_UNBOUND_RISK_METHOD')
    if r5:
        _r5_identity(run,cfg,auth,candidates)
    elif qualification:
        _qualification_identity(run,cfg,auth,candidates)
    elif auth.get('namespace',CONTINUATION_NAMESPACE)!=CONTINUATION_NAMESPACE or auth.get('source_account_binding') is not None:
        raise ExecutionBlocked('UNDECLARED_SOURCE_ACCOUNT_PHASE')
    _validate_packet_metadata(parent,auth,parent_cfg)
    continuation_budget(run,cfg,auth,candidates)
    return run,cfg,auth,candidates


def _qualification_identity(run,cfg,auth,candidates):
    """New source/account identity, one baseline only; no R2 pin rewriting."""
    from scripts.research.a2.training import stateful_completion as meta
    binding=auth.get('source_account_binding',{})
    if (auth.get('namespace')!='A_SOURCE_ACCOUNT_R3' or len(candidates)!=1
            or auth.get('expected_candidates')!=1 or auth.get('replay_chunk_size')!=1
            or auth.get('diagnostic_candidate_ids')!=[auth['baseline_candidate_id']]
            or candidates[0]['candidate_id']!=auth['baseline_candidate_id']
            or candidates[0]['risk']!='diag20_reference'
            or binding.get('status')!='FROZEN_SOURCE_ACCOUNT_BINDING'
            or binding.get('training_label_contract')!='IMMUTABLE_PARENT_NO_CASH_GAP_LABEL_FILL'
            or binding.get('currency')!='USD' or binding.get('amount_unit')!='USD_PER_RAW_OLD_SHARE'
            or binding.get('quantity_coordinate')!='RAW_OLD_SECURITY_SHARES'
            or binding.get('execution_contract')!=candidates[0]['execution_friction']
            or binding.get('candidate_activation_allowed') is not False
            or binding.get('quote_quality_authority',{}).get('expand_domain') is not False
            or binding.get('quote_quality_authority',{}).get('kind')!='ORIGINAL_RAW_SUPPORTED_AND_UNSUPPORTED_EVENT_DAY_BLOCK'):
        raise ExecutionBlocked('SOURCE_ACCOUNT_ONE_BASELINE_EXACT_SCOPE_REQUIRED')
    required=('cash_input_freeze','cash_input_receipt','cash_source_bundle','security_identity_inputs','source_precedence_policy','entitlement_catalogue','A_stale_projection')
    roots=values.resolve(values.REPO)
    for key in required:
        item=binding.get(key,{})
        path=Path(item.get('path','')).resolve()
        if (not any(path.is_relative_to(getattr(roots,k).resolve()) for k in ('backtest_root','results_root'))
                or not _sha_identity(item.get('sha256')) or values.sha(path)!=item['sha256']):
            raise ExecutionBlocked('SOURCE_ACCOUNT_REQUIRED_PIN_CHANGED:'+key)
    quality=binding['quote_quality_authority']
    quality_path=values.REPO/'scripts/research/a2/evaluation/joint_method_accounts.py'
    if quality.get('helper_sha256')!=values.sha(quality_path):
        raise ExecutionBlocked('SOURCE_ACCOUNT_QUOTE_AUTHORITY_CHANGED')
    receipt_ref=binding['cash_input_receipt'];rp=Path(receipt_ref['path']).resolve()
    receipt=meta.read_metadata(rp.parent,rp,{k:meta.ALL for k in ('status','artifact','freeze_sha256','source_binding','original_training_labels_unchanged','quote_quality_domain_preserved','qualification_basis')})
    if (receipt.get('status')!='SOURCE_BOUND_CASH_INPUT_REVISION_READY'
            or receipt.get('artifact')!=binding['cash_source_bundle']
            or receipt.get('freeze_sha256')!=binding['cash_input_freeze']['sha256']
            or receipt.get('original_training_labels_unchanged') is not True
            or receipt.get('quote_quality_domain_preserved') is not True
            or receipt.get('qualification_basis')!='SOURCE_DECLARED_GROSS'
            or receipt.get('source_binding',{}).get('source_fingerprint')!=binding.get('cash_binding_semantic_fingerprint')
            or receipt.get('source_binding',{}).get('event_fingerprints')!=binding.get('entitlement_catalogue_fingerprints')
            or receipt.get('source_binding',{}).get('security_tickers')!=binding.get('security_tickers')):
        raise ExecutionBlocked('SOURCE_ACCOUNT_CATALOGUE_OR_SECURITY_BINDING_CHANGED')
    lineage=binding.get('R2_lineage',{})
    prior=Path(lineage.get('run_dir','')).resolve()
    if not prior.is_relative_to(roots.backtest_root.resolve()) or prior==run:
        raise ExecutionBlocked('SOURCE_ACCOUNT_R2_LINEAGE_OUTSIDE_RUN_ROOT')
    for name in ('run_config.json','ACCOUNT_PATH_LOG.jsonl','EXECUTION_STATUS.json'):
        pin=lineage.get('pins',{}).get(name)
        if not _sha_identity(pin) or values.sha(prior/name)!=pin:
            raise ExecutionBlocked('SOURCE_ACCOUNT_R2_LINEAGE_CHANGED')
    history=_continuation_events(prior,'ACCOUNT_PATH_LOG.jsonl')
    starts=[e for e in history if e.get('event')=='ACCOUNT_PATH_ATTEMPT_STARTED']
    if len(starts)!=14 or outstanding(history,account=True) or cfg['prior_account_paths']!=74+len(starts):
        raise ExecutionBlocked('SOURCE_ACCOUNT_R2_ACCOUNT_HISTORY_NOT_COMPLETE')
    if len(set(binding['entitlement_catalogue_fingerprints']))!=39 or not binding['security_tickers']:
        raise ExecutionBlocked('SOURCE_ACCOUNT_REQUIRED_CATALOGUE_ABSENT')


def _r5_reference(ref):
    """Custody only: hash approved D roots, never decode numeric artifacts."""
    roots=values.resolve(values.REPO)
    if not isinstance(ref,dict) or not isinstance(ref.get('path'),str) or not _sha_identity(ref.get('sha256')):
        raise ExecutionBlocked('R5_SOURCE_REFERENCE_UNKNOWN')
    p=Path(ref['path']).resolve()
    if not any(p.is_relative_to(getattr(roots,k).resolve()) for k in ('backtest_root','results_root')):
        raise ExecutionBlocked('R5_SOURCE_REFERENCE_OUTSIDE_APPROVED_ROOT')
    if not p.is_file() or values.sha(p)!=ref['sha256']:raise ExecutionBlocked('R5_SOURCE_REFERENCE_CHANGED')
    return p


def r5_source_decision(auth,*,verify_refs=True):
    d=auth.get('source_decision')
    claims={'S':'STRICT_HISTORICAL_PIT','N':'DECLARED_RESEARCH_POLICY_NOT_STRICT_HISTORICAL_PIT'}
    if (not isinstance(d,dict) or d.get('branch_id') not in claims
            or any(d.get(k) is not True for k in ('adopted','approved','source_qualified'))
            or d.get('qualification_claim')!=claims[d['branch_id']]):
        raise ExecutionBlocked('R5_SOURCE_DECISION_UNKNOWN_OR_UNAPPROVED')
    slots=d.get('slots')
    if not isinstance(slots,dict) or set(slots)!=set(R5_SOURCE_SLOTS):raise ExecutionBlocked('R5_SOURCE_SLOTS_UNKNOWN')
    for key in R5_SOURCE_SLOTS:
        item=slots[key]
        if (not isinstance(item,dict) or item.get('approved') is not True
                or item.get('source_qualified') is not True or not isinstance(item.get('ref'),dict)
                or not isinstance(item['ref'].get('path'),str) or not _sha_identity(item['ref'].get('sha256'))):
            raise ExecutionBlocked('R5_SOURCE_SLOT_UNKNOWN:'+key)
        if verify_refs:_r5_reference(item['ref'])
    return dict(branch_id=d['branch_id'],qualification_claim=d['qualification_claim'],
                adopted=True,approved=True,source_qualified=True)


def _r5_identity(run,cfg,auth,candidates):
    """New 0-fit/38-path identity; R2/R3 branches retain their old exact gates."""
    meta,_,_,schema,_,_,_=_metadata_schemas();b=auth.get('source_account_binding',{})
    if (auth.get('qualification_only') is not True or cfg.get('fractional_primary') is not True
            or len(candidates)!=38 or auth.get('expected_candidates')!=38
            or auth.get('baseline_candidate_id')!='RAW_s10' or auth.get('diagnostic_candidate_ids')!=['RAW_s10']
            or candidates[0]['candidate_id']!='RAW_s10' or candidates[0]['risk']!='diag20_reference'
            or not isinstance(b,dict) or b.get('status')!='FROZEN_SOURCE_ACCOUNT_BINDING'
            or b.get('candidate_activation_allowed') is not True
            or b.get('training_label_contract')!='IMMUTABLE_PARENT_NO_CASH_GAP_LABEL_FILL'
            or b.get('currency')!='USD' or b.get('amount_unit')!='USD_PER_RAW_OLD_SHARE'
            or b.get('quantity_coordinate')!='RAW_OLD_SECURITY_SHARES'
            or b.get('execution_contract')!=candidates[0]['execution_friction']
            or b.get('quote_quality_authority',{}).get('expand_domain') is not False
            or b.get('quote_quality_authority',{}).get('kind')!='ORIGINAL_RAW_SUPPORTED_AND_UNSUPPORTED_EVENT_DAY_BLOCK'):
        raise ExecutionBlocked('R5_EXACT_BASELINE_TO37_SCOPE_REQUIRED')
    r5_source_decision(auth)
    frozen=auth.get('frozen37_reference',{});manifest_ref=frozen.get('manifest_ref')
    if (frozen.get('sha256')!=R5_SOURCE_CANDIDATE_CATALOGUE_SHA256
            or not isinstance(manifest_ref,dict) or manifest_ref.get('sha256')!=R5_FROZEN37_MANIFEST_SHA256):
        raise ExecutionBlocked('R5_APPROVED_FROZEN_IDENTITY_HASH_REQUIRED')
    fp=_r5_reference(frozen);mp=_r5_reference(manifest_ref)
    identity_schema={k:meta.ALL for k in ('candidate_id','scientific_tuple_sha256')}
    manifest_schema={'source_candidate_catalogue':{'path':meta.ALL,'sha256':meta.ALL},
        'baseline':identity_schema,'frozen_remaining_candidates':[identity_schema]}
    manifest=meta.read_metadata(mp.parent,mp,manifest_schema)
    catalogue_ref=manifest.get('source_candidate_catalogue')
    # Provenance may retain its canonical path when exact metadata bytes are copied.
    # The physically supplied catalogue has already been hashed; do not open the provenance path.
    if (not isinstance(catalogue_ref,dict) or not isinstance(catalogue_ref.get('path'),str)
            or catalogue_ref.get('sha256')!=R5_SOURCE_CANDIDATE_CATALOGUE_SHA256
            or catalogue_ref['sha256']!=frozen['sha256']):
        raise ExecutionBlocked('R5_FROZEN_MANIFEST_CATALOGUE_CHANGED')
    projected=manifest.get('frozen_remaining_candidates');baseline=manifest.get('baseline',{})
    if (not isinstance(projected,list) or len(projected)!=37
            or any(not isinstance(v,dict) or not isinstance(v.get('candidate_id'),str)
                or not v['candidate_id'] or not _sha_identity(v.get('scientific_tuple_sha256')) for v in projected)
            or not isinstance(baseline,dict) or baseline.get('candidate_id')!='RAW_s10'
            or baseline.get('scientific_tuple_sha256')!=candidates[0]['scientific_tuple_sha256']):
        raise ExecutionBlocked('R5_FROZEN_MANIFEST_IDENTITIES_REQUIRED')
    ids=[v['candidate_id'] for v in projected]
    if (len(set(ids))!=37 or frozen.get('candidate_ids')!=ids
            or [c['candidate_id'] for c in candidates[1:]]!=ids
            or any(c['scientific_tuple_sha256']!=v['scientific_tuple_sha256']
                for c,v in zip(candidates[1:],projected))):
        raise ExecutionBlocked('R5_EXACT_FROZEN37_REFERENCE_REQUIRED')
    original=meta.read_metadata(fp.parent,fp,[schema])
    source={c['candidate_id']:c for c in original}
    fields=('source_method_ids','action','value_model','control','gross','risk','target_role',
            'action_cost_mode','execution_friction','forecast','scientific_tuple_sha256')
    # The baseline retains the same original catalogue tuple as all37.
    for c in candidates:
        if c['candidate_id'] not in source or any(c.get(k,'none' if k=='forecast' else None)!=
                source[c['candidate_id']].get(k,'none' if k=='forecast' else None) for k in fields):
            raise ExecutionBlocked('R5_BASELINE_OR_FROZEN37_SCIENTIFIC_IDENTITY_CHANGED')
    for key in ('cash_input_freeze','cash_input_receipt','cash_source_bundle','security_identity_inputs',
                'source_precedence_policy','entitlement_catalogue','A_stale_projection',
                'market_quote_authority','MKFG_terminal_binding','MKFG_settlement_authority'):_r5_reference(b.get(key))
    slot_fields={'market_quote_authority':'market_quote_authority','MKFG_terminal_binding':'MKFG_terminal_binding',
        'MKFG_settlement_authority':'MKFG_settlement_authority','security_identity_binding':'security_identity_inputs',
        'cash_source_bundle':'cash_source_bundle'}
    if any(b[field]!=auth['source_decision']['slots'][slot]['ref'] for slot,field in slot_fields.items()):
        raise ExecutionBlocked('R5_SOURCE_SLOT_AND_CONSUMER_DIFFER')
    if (not _sha_identity(b.get('MKFG_terminal_event_fingerprint'))
            or not _sha_identity(b.get('cash_binding_semantic_fingerprint'))):
        raise ExecutionBlocked('R5_BOUND_TERMINAL_AND_CASH_IDENTITY_REQUIRED')
    helper=values.REPO/'scripts/research/a2/evaluation/joint_method_accounts.py'
    if b['quote_quality_authority'].get('helper_sha256')!=values.sha(helper):
        raise ExecutionBlocked('R5_ORIGINAL_RAW_QUOTE_HELPER_CHANGED')
    rp=Path(b['cash_input_receipt']['path']).resolve()
    receipt_schema={k:meta.ALL for k in ('status','artifact','freeze_sha256',
        'original_training_labels_unchanged','quote_quality_domain_preserved','qualification_basis')}
    receipt_schema['source_binding']={k:meta.ALL for k in ('source_fingerprint','event_fingerprints','security_tickers')}
    # Producer projects identities of actually consumed bundle objects, not arbitrary approved documents.
    attestation_fields=('status','consumer','cash_source_bundle','cash_binding_semantic_fingerprint',
        'MKFG_terminal_event_fingerprint','MKFG_terminal_binding','MKFG_settlement_authority',
        'market_quote_authority','security_identity_inputs','entitlement_catalogue',
        'quote_quality_helper_sha256','terminal_and_settlement_are_separate_consumed_objects',
        'quote_authority_is_consumed_by_preserved_quote_quality_helper','original_raw_matrix_and_labels_unchanged')
    receipt_schema['consumer_binding_attestation']={k:meta.ALL for k in attestation_fields}
    receipt=meta.read_metadata(rp.parent,rp,receipt_schema)
    f=b.get('entitlement_catalogue_fingerprints');sb=receipt.get('source_binding',{})
    if (receipt.get('status')!='SOURCE_BOUND_CASH_INPUT_REVISION_READY'
            or receipt.get('artifact')!=b['cash_source_bundle'] or receipt.get('freeze_sha256')!=b['cash_input_freeze']['sha256']
            or receipt.get('original_training_labels_unchanged') is not True
            or receipt.get('quote_quality_domain_preserved') is not True or receipt.get('qualification_basis')!='SOURCE_DECLARED_GROSS'
            or not isinstance(f,list) or not f or len(set(f))!=len(f) or any(not _sha_identity(v) for v in f)
            or not b.get('security_tickers') or sb.get('source_fingerprint')!=b.get('cash_binding_semantic_fingerprint')
            or sb.get('event_fingerprints')!=f or sb.get('security_tickers')!=b.get('security_tickers')):
        raise ExecutionBlocked('R5_SOURCE_ACCOUNT_RECEIPT_CHANGED')
    att=receipt.get('consumer_binding_attestation',{})
    object_fields=('cash_source_bundle','cash_binding_semantic_fingerprint','MKFG_terminal_event_fingerprint',
        'MKFG_terminal_binding','MKFG_settlement_authority','market_quote_authority','security_identity_inputs','entitlement_catalogue')
    if (att.get('status')!='FROZEN_CONSUMED_SOURCE_OBJECTS_BOUND'
            or att.get('consumer')!='EXISTING_STATEFUL_REPLAY_CASH_ENTITLEMENT_TERMINAL'
            or any(att.get(k)!=b.get(k) for k in object_fields)
            or att.get('quote_quality_helper_sha256')!=b['quote_quality_authority']['helper_sha256']
            or any(att.get(k) is not True for k in ('terminal_and_settlement_are_separate_consumed_objects',
                'quote_authority_is_consumed_by_preserved_quote_quality_helper','original_raw_matrix_and_labels_unchanged'))):
        raise ExecutionBlocked('R5_APPROVED_SOURCE_NOT_ATTESTED_AS_CONSUMED_OBJECT')
    roots=values.resolve(values.REPO)
    for key,count in (('R2_lineage',14),('R3_lineage',1)):
        item=b.get(key,{});prior=Path(item.get('run_dir','')).resolve()
        if not prior.is_relative_to(roots.backtest_root.resolve()) or prior==run:
            raise ExecutionBlocked('R5_PRIOR_LINEAGE_OUTSIDE_ROOT')
        for name in ('run_config.json','ACCOUNT_PATH_LOG.jsonl','EXECUTION_STATUS.json'):
            if not _sha_identity(item.get('pins',{}).get(name)) or values.sha(prior/name)!=item['pins'][name]:
                raise ExecutionBlocked('R5_PRIOR_LINEAGE_CHANGED')
        history=_continuation_events(prior,'ACCOUNT_PATH_LOG.jsonl')
        starts=[e for e in history if e.get('event')=='ACCOUNT_PATH_ATTEMPT_STARTED']
        ends=[e for e in history if e.get('event') in ('ACCOUNT_PATH_COMPLETE','ACCOUNT_PATH_FAILED')]
        if (len(starts)!=count or len({e.get('candidate_id') for e in starts})!=count
                or len(ends)!=count or len({e.get('candidate_id') for e in ends})!=count or outstanding(history,account=True)):
            raise ExecutionBlocked('R5_PRIOR_ACCOUNT_ATTEMPTS_INCOMPLETE')


def r5_baseline_gate(run,auth,candidate='RAW_s10'):
    """Only the seven approved groups; no new numerical/economic prerequisite."""
    groups=dict.fromkeys(('accounting','quote_source','certified_nav','cash','entitlement',
                          'terminal','required_audits'),False)
    complete=[e for e in _continuation_events(run,'ACCOUNT_PATH_LOG.jsonl')
              if e.get('candidate_id')==candidate and e.get('event')=='ACCOUNT_PATH_COMPLETE']
    if len(complete)>1:raise ExecutionBlocked('R5_BASELINE_TERMINAL_DUPLICATE')
    if complete:
        event=complete[0];p=own_path(run,event['audit_path'])
        if values.sha(p)!=event.get('audit_sha256'):raise ExecutionBlocked('R5_BASELINE_AUDIT_CHANGED')
        meta,_,_,_,_,_,schema=_metadata_schemas()
        schema['qualification_checks']={k:meta.ALL for k in (
            'accounting_qualified','quote_qualified','certified_NAV_all_window_finite','cash_identity_correct',
            'entitlement_identity_correct','terminal_identity_correct','terminal_settlement_qualified',
            'full_window_752_sessions','eligible_for_selection')}
        audit=meta.read_metadata(run,p,schema);q=audit.get('qualification_checks',{})
        if not isinstance(q,dict):q={}
        eligibility=audit.get('selection_eligibility',{})
        annual=eligibility.get(candidate,{}) if isinstance(eligibility,dict) else {}
        if not isinstance(annual,dict):annual={}
        annual_good=(set(annual)=={str(y) for y in YEARS} and all(
            isinstance(annual[str(y)],dict) and annual[str(y)].get('sessions')==n and all(annual[str(y)].get(k) is True
            for k in ('accounting_qualified_all','certified_nav_positive_and_finite_all','net_return_finite_except_initial'))
            for y,n in zip(YEARS,(250,252,250))))
        identity_good=(audit.get('status')=='ACTUAL_CONTINUOUS_PRE2026_REPLAY_COMPLETE'
            and audit.get('continuation') is True and audit.get('annual_reset') is False
            and audit.get('calendar_sessions')==752 and audit.get('candidates_sha256')==auth['candidates_sha256']
            and audit.get('source_closure',{}).get('module_sha256')==auth['source_pins']['replay_module_sha256']
            and audit.get('policy_and_execution_cost_schedule_identical') is True
            and audit.get('fit_units')==0 and audit.get('2026_rows_read')==0)
        try:source=r5_source_decision(auth,verify_refs=False)['source_qualified'] is True
        except ExecutionBlocked:source=False
        groups.update(accounting=q.get('accounting_qualified') is True,
            quote_source=q.get('quote_qualified') is True and source,
            certified_nav=q.get('certified_NAV_all_window_finite') is True,
            cash=q.get('cash_identity_correct') is True,
            entitlement=q.get('entitlement_identity_correct') is True,
            terminal=q.get('terminal_identity_correct') is True and q.get('terminal_settlement_qualified') is True,
            required_audits=identity_good and annual_good and q.get('full_window_752_sessions') is True
                            and q.get('eligible_for_selection') is True)
    good=all(value is True for value in groups.values())
    return dict(groups=groups,all_passed=good,decision='ACTIVATE_FROZEN37' if good else 'NOT_TESTABLE')



CONTINUATION_STATUS=None


def _status_schema():
    meta=_metadata_schemas()[0];a=meta.ALL
    return {k:a for k in ('status','stage','stages','metadata_only','continuation','test_2026_rows_read',
        'controller_source_sha256','candidates_sha256','input_manifest_sha256','continuation_auth_sha256',
        'winner_selection_by_controller','budget','baseline_qualified','scientific_status','candidate_states',
        'report','temporary_environment','selection_performed','finished_account_attempts','fail_reason',
        'run_config_sha256','budget_violation_code','baseline_gate','activation_decision','source_decision_summary')}


@contextmanager
def continuation_lock(run,controller_sha,namespace=CONTINUATION_NAMESPACE):
    path=own_path(run,run/'CONTINUATION_LOCK.json');assert_write_path(path,'backtest')
    token=uuid.uuid4().hex
    payload=dict(token=token,pid=os.getpid(),controller_source_sha256=controller_sha,namespace=namespace,
                 run_config_sha256=values.sha(run/'run_config.json'))
    try:
        with path.open('x',encoding='utf-8') as stream:
            json.dump(payload,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
    except FileExistsError as exc:raise ExecutionBlocked('CONTINUATION_OWNED_LOCK_ALREADY_EXISTS_NO_TAKEOVER') from exc
    try:yield token
    finally:
        meta=_metadata_schemas()[0]
        current=meta.read_metadata(run,path,{k:meta.ALL for k in payload})
        if current!=payload:raise ExecutionBlocked('CONTINUATION_OWNED_LOCK_REPLACED')
        path.unlink()


def continuation_worker_guard(run_dir):
    run,cfg,auth,candidates=continuation_contract(run_dir)
    token=os.environ.get(CONTINUATION_LOCK_ENV)
    meta=_metadata_schemas()[0]
    path=own_path(run,run/'CONTINUATION_LOCK.json')
    if not token or not path.is_file():raise ExecutionBlocked('CONTINUATION_WORKER_REQUIRES_OWNED_CONTROLLER_LOCK')
    lock=meta.read_metadata(run,path,{'token':meta.ALL,'controller_source_sha256':meta.ALL,'namespace':meta.ALL,'run_config_sha256':meta.ALL})
    if (lock.get('token')!=token or lock.get('controller_source_sha256')!=auth['module_sha256']
            or lock.get('namespace')!=auth.get('namespace',CONTINUATION_NAMESPACE)
            or lock.get('run_config_sha256')!=values.sha(run/'run_config.json')):
        raise ExecutionBlocked('CONTINUATION_WORKER_LOCK_IDENTITY')
    return run,cfg,auth,candidates


def _baseline_qualified(run,auth,candidate):
    if auth.get('namespace')==R5_NAMESPACE:return r5_baseline_gate(run,auth,candidate)['all_passed']
    history=_continuation_events(run,'ACCOUNT_PATH_LOG.jsonl')
    matches=[e for e in history if e.get('candidate_id')==candidate and e.get('event')=='ACCOUNT_PATH_COMPLETE']
    if not matches:return False
    if len(matches)!=1:raise ExecutionBlocked('CONTINUATION_BASELINE_TERMINAL_DUPLICATE')
    event=matches[0];path=own_path(run,event['audit_path'])
    if values.sha(path)!=event.get('audit_sha256'):raise ExecutionBlocked('CONTINUATION_BASELINE_AUDIT_CHANGED')
    meta,_,_,_,_,_,schema=_metadata_schemas()
    audit=meta.read_metadata(run,path,schema)
    if (audit.get('status')!='ACTUAL_CONTINUOUS_PRE2026_REPLAY_COMPLETE'
            or audit.get('continuation') is not True or audit.get('annual_reset') is not False
            or audit.get('calendar_sessions')!=752 or audit.get('candidates_sha256')!=auth['candidates_sha256']
            or audit.get('source_closure',{}).get('module_sha256')!=auth['source_pins']['replay_module_sha256']
            or audit.get('policy_and_execution_cost_schedule_identical') is not True
            or audit.get('fit_units')!=0 or audit.get('2026_rows_read')!=0):
        raise ExecutionBlocked('CONTINUATION_BASELINE_AUDIT_IDENTITY_OR_FULL_CALENDAR')
    if auth.get('qualification_only') is True:
        checks=audit.get('qualification_checks',{})
        if checks.get('eligible_for_selection') is not True:return False
    q=audit.get('selection_eligibility',{}).get(candidate,{})
    return (set(q)=={str(y) for y in YEARS} and all(q[str(y)].get('sessions')==n and
        all(q[str(y)].get(k) is True for k in ('accounting_qualified_all',
            'certified_nav_positive_and_finite_all','net_return_finite_except_initial'))
        for y,n in zip(YEARS,(250,252,250))))


def _run_continuation_batch(control,candidate_ids,token):
    control.guard();before=continuation_budget(control.run,control.config,control.auth,control.candidates)
    if before['outstanding']:raise ExecutionBlocked('CONTINUATION_OUTSTANDING_ACCOUNT_NO_SECOND_WRITER')
    if before['new_account_path_attempts']+len(candidate_ids)>control.auth['max_new_account_paths']:
        raise ExecutionBlocked('CONTINUATION_FULL_ACCOUNT_PATH_CAP')
    env=os.environ.copy();env[CONTINUATION_LOCK_ENV]=token;env['PYTHONDONTWRITEBYTECODE']='1'
    command=[sys.executable,'-B','-m','scripts.research.a2.training.stateful_replay',
             '--run-dir',str(control.run),'--continuation']
    for candidate in candidate_ids:command+=['--candidate',candidate]
    # Child output is discarded instead of decoding arbitrary scientific output.
    child=subprocess.Popen(command,cwd=values.REPO,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    start=time.monotonic()
    while child.poll() is None:
        if time.monotonic()-start>control.auth['worker_timeout_seconds']:
            child.kill();child.wait();raise ExecutionBlocked('CONTINUATION_WORKER_TIMEOUT_ATTEMPT_PRESERVED')
        time.sleep(control.auth['poll_seconds'])
    control.guard()
    history=_continuation_events(control.run,'ACCOUNT_PATH_LOG.jsonl')
    for candidate in candidate_ids:
        if sum(e.get('candidate_id')==candidate and e.get('event')=='ACCOUNT_PATH_ATTEMPT_STARTED' for e in history)!=1 or sum(
            e.get('candidate_id')==candidate and e.get('event') in ('ACCOUNT_PATH_COMPLETE','ACCOUNT_PATH_FAILED') for e in history)!=1:
            raise ExecutionBlocked('CONTINUATION_WORKER_MISSING_UNIQUE_ATTEMPT_TERMINAL_NO_RETRY')
    # A nonzero exit can have retained terminal FAILED records. Such scientific
    # failures consume budget and do not cause an implicit retry or global stop.
    return dict(return_code=child.returncode,candidate_ids=list(candidate_ids))


def _run_continuation_controller(control):
    with continuation_lock(control.run,control.auth['module_sha256'],control.auth.get('namespace',CONTINUATION_NAMESPACE)) as token:
        try:
            control.guard()
            if control.state.get('status')=='COMPLETED':return control.state
            budget=continuation_budget(control.run,control.config,control.auth,control.candidates)
            if budget['outstanding']:raise ExecutionBlocked('CONTINUATION_OUTSTANDING_ACCOUNT_NO_RESUME_RETRY')
            control.state['temporary_environment']=configure_environment(control.config)
            control.save('RUNNING','PRIMARY10_BASELINE_PROBE')
            history=_continuation_events(control.run,'ACCOUNT_PATH_LOG.jsonl')
            done={e['candidate_id'] for e in history if e.get('event')=='ACCOUNT_PATH_ATTEMPT_STARTED'}
            baseline=control.auth['baseline_candidate_id']
            if baseline not in done:_run_continuation_batch(control,[baseline],token)
            qualified=_baseline_qualified(control.run,control.auth,baseline)
            if control.auth.get('namespace')==R5_NAMESPACE:
                gate=r5_baseline_gate(control.run,control.auth,baseline)
                control.state.update(baseline_gate=gate['groups'],activation_decision=gate['decision'],
                    source_decision_summary=r5_source_decision(control.auth,verify_refs=False))
                qualified=gate['all_passed']
            allowed={c['candidate_id'] for c in control.candidates} if qualified else set(control.auth['diagnostic_candidate_ids'])
            if not qualified and not done.issubset(allowed):
                raise ExecutionBlocked('CONTINUATION_CONDITIONAL_ATTEMPT_WITHOUT_QUALIFIED_BASELINE')
            control.save('RUNNING','QUALIFIED_CONTINUATION' if qualified else 'BASELINE_UNQUALIFIED_DIAGNOSTICS_ONLY',
                baseline_qualified=qualified,scientific_status='PRE2026_EXPLORATORY_RESEARCH' if qualified else 'NOT_TESTABLE',
                selection_performed=False)
            history=_continuation_events(control.run,'ACCOUNT_PATH_LOG.jsonl')
            done={e['candidate_id'] for e in history if e.get('event')=='ACCOUNT_PATH_ATTEMPT_STARTED'}
            pending=[c for c in control.candidates if c['candidate_id'] in allowed and c['candidate_id'] not in done]
            while pending:
                first=pending[0]
                if control.auth.get('namespace')==R5_NAMESPACE:
                    # Preserve the original frozen order; never skip over another friction case.
                    group=[]
                    for candidate in pending:
                        if (candidate['execution_friction']!=first['execution_friction']
                                or len(group)>=control.auth['replay_chunk_size']):break
                        group.append(candidate)
                else:
                    group=[c for c in pending if c['execution_friction']==first['execution_friction']][:control.auth['replay_chunk_size']]
                ids=[c['candidate_id'] for c in group];_run_continuation_batch(control,ids,token)
                pending=[c for c in pending if c['candidate_id'] not in ids]
                control.save('RUNNING','ACCOUNT_ATTEMPTS_METADATA_UPDATED')
            history=_continuation_events(control.run,'ACCOUNT_PATH_LOG.jsonl')
            terminal={e['candidate_id']:e['event'] for e in history if e.get('event') in ('ACCOUNT_PATH_COMPLETE','ACCOUNT_PATH_FAILED')}
            control.state['candidate_states']={c['candidate_id']:terminal.get(c['candidate_id'],
                'NOT_EXECUTED_REQUIRED_BASELINE_UNQUALIFIED') for c in control.candidates}
            control.save('RUNNING','METADATA_REPORT_BUILD',finished_account_attempts=len(terminal))
            meta=importlib.import_module('scripts.research.a2.training.stateful_completion')
            if not hasattr(meta,'build_continuation_report'):raise ExecutionBlocked('BLOCKED_REPORT_CONTINUATION_BUILDER_NOT_READY')
            report=meta.build_continuation_report(control.run)
            # Reporter returns only paths/status, not outcome statistics.
            if not isinstance(report,dict):raise ExecutionBlocked('BLOCKED_REPORT_METADATA_RECEIPT_REQUIRED')
            control.state['report']={k:v for k,v in report.items() if k in ('status','report_paths','paths','outputs','results_directory','finite_execution_complete','task_record_path','report_path','budget_audit_path','coverage_report_path')}
            if report.get('finite_execution_complete') is not True:
                raise ExecutionBlocked('BLOCKED_REPORT_CONTINUATION_NOT_COMPLETE')
            control.guard()
            control.save('COMPLETED','REPORT_BUILT',selection_performed=False,winner_selection_by_controller=False)
        except Exception as exc:
            # No terminal account event is fabricated here. Replay is sole writer.
            control.save('BLOCKED','CONTINUATION_ENGINEERING_OR_PUBLICATION_BLOCK',
                fail_reason=dict(type=type(exc).__name__,message=str(exc).split(':',1)[0]))
        return control.state


CONTINUATION_STATUS=_status_schema()


def _run_research_batch(control,candidate_ids,token):
    control.guard()
    before=events(control.run,'ACCOUNT_PATH_LOG.jsonl')
    if outstanding(before,account=True):raise ExecutionBlocked('RESEARCH_OUTSTANDING_ATTEMPT_NO_SECOND_WRITER')
    starts=[e for e in before if e.get('event')=='ACCOUNT_PATH_ATTEMPT_STARTED']
    if len(starts)+len(candidate_ids)>57:raise ExecutionBlocked('RESEARCH_ACCOUNT_PATH_CAP')
    if any(e.get('candidate_id') in candidate_ids for e in starts):
        raise ExecutionBlocked('RESEARCH_ACCOUNT_ALREADY_ATTEMPTED_NO_RETRY')
    env=os.environ.copy();env[CONTINUATION_LOCK_ENV]=token;env['PYTHONDONTWRITEBYTECODE']='1'
    command=[sys.executable,'-B','-m','scripts.research.a2.training.stateful_replay',
        '--run-dir',str(control.run),'--research-account']
    for candidate in candidate_ids:command+=['--candidate',candidate]
    child=subprocess.Popen(command,cwd=values.REPO,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    start=time.monotonic()
    while child.poll() is None:
        if time.monotonic()-start>control.auth.get('worker_timeout_seconds',1800):
            child.kill();child.wait();raise ExecutionBlocked('RESEARCH_WORKER_TIMEOUT_ATTEMPT_PRESERVED')
        time.sleep(control.auth.get('poll_seconds',5))
    control.guard()
    history=events(control.run,'ACCOUNT_PATH_LOG.jsonl')
    for candidate in candidate_ids:
        if (sum(e.get('candidate_id')==candidate and e.get('event')=='ACCOUNT_PATH_ATTEMPT_STARTED' for e in history)!=1
            or sum(e.get('candidate_id')==candidate and e.get('event') in ('ACCOUNT_PATH_COMPLETE','ACCOUNT_PATH_FAILED') for e in history)!=1):
            raise ExecutionBlocked('RESEARCH_WORKER_MISSING_UNIQUE_TERMINAL')
    return dict(return_code=child.returncode,candidate_ids=list(candidate_ids))


def _run_research_controller(control):
    from scripts.research.a2.training import stateful_research_account as child
    with continuation_lock(control.run,values.sha(Path(__file__)),child.namespace(control.auth)) as token:
        try:
            control.guard()
            if control.state.get('status')=='COMPLETED':return control.state
            if outstanding(events(control.run,'ACCOUNT_PATH_LOG.jsonl'),account=True):
                raise ExecutionBlocked('RESEARCH_OUTSTANDING_ATTEMPT_NO_IMPLICIT_RETRY')
            control.state['temporary_environment']=configure_environment(control.config)
            control.save('RUNNING','RESEARCH_RAW_s10')
            done={e['candidate_id'] for e in events(control.run,'ACCOUNT_PATH_LOG.jsonl') if e.get('event')=='ACCOUNT_PATH_ATTEMPT_STARTED'}
            if 'RAW_s10' not in done:_run_research_batch(control,['RAW_s10'],token)
            gate=child.baseline_gate(control.run,control.auth)
            groups=gate.get('groups',{})
            passed=(gate.get('all_passed') is True and set(groups)==set(child.GATES)
                and all(groups.get(name) is True for name in child.GATES))
            control.state.update(baseline_gate=groups,baseline_qualified=passed,
                activation_decision='ACTIVATE_FROZEN56' if passed else 'RESEARCH_ACCOUNT_BASELINE_BLOCKED')
            if passed:
                # Exact original order, with no model/friction/parameter substitution.
                for stage,subset in (('ORIGINAL_FROZEN37',control.candidates[1:38]),('ORIGINAL_BREADTH19',control.candidates[38:])):
                    control.save('RUNNING',stage)
                    done={e['candidate_id'] for e in events(control.run,'ACCOUNT_PATH_LOG.jsonl') if e.get('event')=='ACCOUNT_PATH_ATTEMPT_STARTED'}
                    pending=[c for c in subset if c['candidate_id'] not in done]
                    while pending:
                        group=[]
                        for c in pending:
                            if c['execution_friction']!=pending[0]['execution_friction'] or len(group)>=control.auth.get('replay_chunk_size',4):break
                            group.append(c)
                        ids=[c['candidate_id'] for c in group]
                        _run_research_batch(control,ids,token)
                        pending=[c for c in pending if c['candidate_id'] not in ids]
                        control.save('RUNNING',stage)
            elif any(e.get('candidate_id')!='RAW_s10' for e in events(control.run,'ACCOUNT_PATH_LOG.jsonl')):
                raise ExecutionBlocked('RESEARCH_CANDIDATE_WITHOUT_QUALIFIED_BASELINE')
            control.save('RUNNING','RESEARCH_ACCOUNT_REPORT')
            report=child.build_report(control.run)
            control.state['report']=report
            control.save('COMPLETED','RESEARCH_ACCOUNT_REPORT_BUILT',scientific_status=report['status'],selection_performed=False)
        except Exception as exc:
            control.save('BLOCKED','RESEARCH_ENGINEERING_OR_HISTORICAL_FACT_BLOCK',
                fail_reason=dict(type=type(exc).__name__,message=str(exc)))
        return control.state


def run_controller(run_dir):
    # Exact final-action child; existing owner/lock and account engine remain unique.
    cfg_path=Path(run_dir)/"run_config.json"
    if cfg_path.is_file() and read_json(cfg_path).get("final_action_namespace")=="V24_A_FINAL_ACTION_COVERAGE_AND_STATEFUL_DECISION_R1":
        from scripts.research.a2.training import stateful_final_action as child
        return child.run_owned(run_dir)
    control=Controller(run_dir)
    if getattr(control,'research',False):return _run_research_controller(control)
    if control.continuation:return control.run_continuation()
    try:
        control.state['temporary_environment']=configure_environment(control.config)
        control.save('WAITING','FUTURE_STAGE_ENVIRONMENT_RESOLVED')
        control.wait_value()
        from scripts.research.a2.training import stateful_fusion as fusion
        from scripts.research.a2.training import stateful_value_repair as repair
        from scripts.research.a2.training import stateful_risk as risk
        from scripts.research.a2.training import stateful_aux as aux
        from scripts.research.a2.training import stateful_replay as replay
        control.stage('fusion',fusion,control.config['fusion_training']['ordered_schedule'],
                      ('model_id','year'),set(fusion.METHODS.values()))
        control.repair(repair)
        control.stage('risk',risk,[dict(method_id=method,year=year) for method in risk.METHODS for year in YEARS],
                      ('method_id','year'),{'RISK::'+method for method in risk.METHODS})
        control.stage('aux',aux,[dict(method=method,year=year) for method in aux.METHODS for year in YEARS],
                      ('method','year'),{'AUX::'+method for method in aux.METHODS})
        control.guard()
        bind_replay(control,replay,risk)
        control.replay(replay)
        control.guard()
        completion_path=HERE/'stateful_completion.py'
        expected=control.auth.get('completion_module_sha256')
        if not completion_path.exists() or not isinstance(expected,str) or len(expected)!=64:
            raise ExecutionBlocked('BLOCKED_REPORT_COMPLETION_SOURCE_NOT_READY; RESUME_WITHOUT_REFITS')
        if values.sha(completion_path)!=expected:
            raise ExecutionBlocked('BLOCKED_REPORT_COMPLETION_SOURCE_CHANGED')
        completion=importlib.import_module('scripts.research.a2.training.stateful_completion')
        completion.build_report(control.run)
        control.state['stages']['report']=dict(status='COMPLETED',producer_source_sha256=expected)
        control.save('BLOCKED_FITS_REPORT_BUILT' if control.state.get('additional_fits_blocked') else 'COMPLETED',
                     'REPORT_BUILT',scientific_qualification_authority='stateful_completion',
                     winner_selection_by_controller=False)
        return control.state
    except Exception as exc:
        control.save('BLOCKED_REPORT' if 'BLOCKED_REPORT' in str(exc) else 'BLOCKED',
                     control.state.get('stage','INITIALIZATION'),
                     fail_reason=dict(type=type(exc).__name__,message=str(exc)))
        return control.state


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--check-only',action='store_true')
    args=parser.parse_args(argv)
    if args.check_only and _continuation_requested(args.run_dir):
        run,config,auth,candidates=continuation_contract(args.run_dir)
        print(json.dumps(dict(status='READY',metadata_only=True,continuation=True,
            controller_fit_started=0,live_budget=continuation_budget(run,config,auth,candidates))))
        return 0
    if args.check_only:
        _,config,_,_,_=frozen_contract(args.run_dir,allow_partial_logs=True)
        print(json.dumps(dict(status='READY',metadata_only=True,controller_fit_started=0,
            live_budget=budget_snapshot(config,event_snapshot(Path(args.run_dir),allow_partial=True)[0],
                                       event_snapshot(Path(args.run_dir),'ACCOUNT_PATH_LOG.jsonl',allow_partial=True)[0]))))
        return 0
    state=run_controller(args.run_dir)
    print(json.dumps(dict(status=state['status'],stage=state['stage'],metadata_only=True,
                         fail_reason=state.get('fail_reason')),sort_keys=True))
    return 0 if state['status']=='COMPLETED' else 2


if __name__=='__main__':
    raise SystemExit(main())
