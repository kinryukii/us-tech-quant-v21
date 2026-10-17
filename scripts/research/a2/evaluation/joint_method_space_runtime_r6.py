"""R6 independent admission and durable budget adapter over existing lifecycle."""
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime,timezone
import json
from scripts.common.storage_paths import resolve,assert_safe_output_path
from scripts.research.a2.evaluation import joint_frozen_history_risk_r3 as parent
from scripts.research.a2.evaluation.joint_method_space_design_r6 import ID,CAPS

FILENAME='R6_SCIENCE_AND_EXECUTION_FREEZE.json'

def guard_numeric(run,freeze_sha):
    run=Path(run).resolve();paths=resolve(parent.REPO)
    assert_safe_output_path(run,kind='backtest',paths=paths)
    if run.parent!=paths.backtest_root/'V24':raise ValueError('MANAGED_R6_RUN_REQUIRED')
    parent._pin(run/FILENAME,freeze_sha,'R6_PRE_NUMERIC_FREEZE')
    f=parent.read_json(run/FILENAME)
    if f.get('research_id')!=ID or f.get('status')!='FROZEN_BEFORE_NUMERIC' or f.get('budget_caps')!=CAPS or f.get('test2026_reads')!=0 or f.get('R5_numeric_economic_read') is not False:raise ValueError('EXACT_R6_FROZEN_BOUNDARY_REQUIRED')
    if any(f.get(k) is not False for k in ('strict_PIT_promotion_eligible','quote_qualified','certified_nav_qualified')):raise ValueError('UNCERTIFIED_MECHANISM_ONLY_REQUIRED')
    ref=f['source_authority_ref'];parent._pin(ref['source_ref'],ref['sha256'],'R6_AUTHORITY')
    a=parent.read_json(ref['source_ref'])
    if a.get('research_id')!=ID or a.get('test2026_reads')!=0 or a.get('EF_access') is not False or a.get('network_provider_fetch') is not False:raise ValueError('NO_EF_PROVIDER_TEST_ACCESS')
    if not f.get('source_code_pins') or not f.get('full_physical_dag_ref'):raise ValueError('COMPLETE_PHYSICAL_DAG_AND_CODE_REQUIRED')
    _r6_io_code_pin_guard(run,f,freeze_sha)
    for key in ('method_catalogue_ref','compatibility_matrix_ref','exact_reuse_audit_ref','full_physical_dag_ref','budget_proof_ref'):
        ref=f[key];parent._pin(ref['source_ref'],ref['sha256'],key)
    from scripts.maintenance import research_registry
    root=parent.read_json(parent.REPO/'config/research_registry.json')['registry_root']
    q=research_registry.query_registry(root,entity_id=ID)
    if q.get('status')!='PASS' or q.get('count')!=1:raise ValueError('ACCEPTED_R6_CANONICAL_IDENTITY_REQUIRED_BEFORE_NUMERIC')
    row=q['entities'][0];m=row.get('metadata',{})
    if row.get('status') not in ('OPEN','ACTIVE') or m.get('science_freeze_sha256')!=freeze_sha or m.get('source_authority_sha256')!=f['source_authority_ref']['sha256'] or m.get('strict_PIT_promotion_eligible') is not False or m.get('fit_authority') is not False:raise ValueError('REGISTERED_R6_EXACT_SOURCE_SCIENCE_REQUIRED')
    return run

def _r6_io_digest(value):
    import hashlib
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')).hexdigest()

def _r6_io_read(ref,*,json_body=False):
    import hashlib
    if not isinstance(ref,dict) or set(ref)!={'source_ref','sha256'} or not isinstance(ref['sha256'],str) or len(ref['sha256'])!=64 or any(c not in '0123456789abcdef' for c in ref['sha256']):raise ValueError('IO_EXACT_PHYSICAL_REFERENCE_REQUIRED')
    p=Path(ref['source_ref']);paths=resolve(parent.REPO)
    if not p.is_absolute() or p.drive.upper() in ('E:','F:') or p.resolve(strict=True)!=p.absolute() or p.suffix.lower() not in ('.py','.txt','.json'):raise ValueError('IO_SAFE_SOURCE_ONLY_REF_REQUIRED')
    if not any(p.is_relative_to(r) for r in (parent.REPO,paths.cache_root,paths.backtest_root)):raise ValueError('IO_MANAGED_SOURCE_SNAPSHOT_REQUIRED')
    if p.stat().st_size>2*1024*1024:raise ValueError('IO_BOUNDED_FULL_BODY_REQUIRED')
    raw=p.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=ref['sha256']:raise ValueError('IO_FULL_PHYSICAL_SHA_CHANGED')
    return json.loads(raw.decode('utf-8')) if json_body else raw

def _r6_io_mode_ast(old,new,function):
    import ast,copy
    left=ast.parse(old);right=ast.parse(new)
    fs=[n for n in right.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==function]
    if len(fs)!=1:raise ValueError('IO_EXACT_FUNCTION_REQUIRED')
    calls=[n for n in ast.walk(fs[0]) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='open' and n.args and isinstance(n.args[0],ast.Constant) and n.args[0].value=='r+b']
    if len(calls)!=1:raise ValueError('IO_EXACT_ONE_RDWR_MODE_REQUIRED')
    calls[0].args[0].value='rb'
    if ast.dump(left,include_attributes=False)!=ast.dump(right,include_attributes=False):raise ValueError('IO_OTHER_MODULE_AST_CHANGE_FORBIDDEN')
    needle=b"with temp.open('rb') as handle:os.fsync(handle.fileno())"
    changed=b"with temp.open('r+b') as handle:os.fsync(handle.fileno())"
    if old.count(needle)!=1 or old.replace(needle,changed,1)!=new:raise ValueError('IO_ONLY_EXACT_MODE_BYTES_ALLOWED')

def _r6_io_runtime_ast(old,new):
    import ast,copy
    left=ast.parse(old);right=ast.parse(new)
    names={'_r6_io_digest','_r6_io_read','_r6_io_mode_ast','_r6_io_runtime_ast','_r6_io_constraints','_r6_io_record','_r6_io_code_pin_guard','_r6_io_paid_mode_ast','_r6_io_paid_binding','guard_io_recovery'}
    added=[n for n in right.body if isinstance(n,ast.FunctionDef) and n.name in names]
    if {n.name for n in added}!=names or len(added)!=len(names):raise ValueError('IO_EXACT_RUNTIME_HELPER_SET_REQUIRED')
    right.body=[n for n in right.body if n not in added]
    lfn=next(n for n in left.body if isinstance(n,ast.FunctionDef) and n.name=='guard_numeric')
    rfn=next(n for n in right.body if isinstance(n,ast.FunctionDef) and n.name=='guard_numeric')
    loops=[n for n in lfn.body if isinstance(n,ast.For) and isinstance(n.iter,ast.Subscript) and ast.dump(n.iter,include_attributes=False)==ast.dump(ast.parse("f['source_code_pins']",mode='eval').body,include_attributes=False)]
    calls=[(i,n) for i,n in enumerate(rfn.body) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='_r6_io_code_pin_guard']
    if len(loops)!=1 or len(calls)!=1 or ast.dump(calls[0][1].value,include_attributes=False)!=ast.dump(ast.parse('_r6_io_code_pin_guard(run,f,freeze_sha)',mode='eval').body,include_attributes=False):raise ValueError('IO_ONLY_CODE_PIN_LOOP_ADAPTER_ALLOWED')
    rfn.body[calls[0][0]]=copy.deepcopy(loops[0])
    if ast.dump(left,include_attributes=False)!=ast.dump(right,include_attributes=False):raise ValueError('IO_OLD_RUNTIME_AST_CHANGED')

def _r6_io_constraints():
    return dict(science_changed=False,source_changed=False,methods_targets_parameters_changed=False,pools_or_DAG_changed=False,source_promotion=False,new_fit_for_recovery=0,new_reserve_for_recovery=0,budget_refund=False,old_failure_preserved=True,test2026_reads=0,R5_numeric_economic_read=False)

def _r6_io_record(record,f,run,freeze_sha,*,runtime_code_ref=None):
    import hashlib
    required={'schema','research_id','science_freeze_ref','source_authority_ref','original_source_code_pins','io_changes','runtime_guard_change','constraints','review_ref','recovery_proposal_ref','paid_recovery'}
    if not isinstance(record,dict) or set(record)!=required or record['schema']!='B_R6_EXECUTION_IO_EQUIVALENCE_V1' or record['research_id']!=ID or _r6_io_digest(record['constraints'])!=_r6_io_digest(_r6_io_constraints()):raise ValueError('IO_EXACT_CLOSED_SCHEMA_AND_BOUNDARY_REQUIRED')
    if record['science_freeze_ref']!=dict(source_ref=str(run/FILENAME),sha256=freeze_sha) or record['source_authority_ref']!=f['source_authority_ref'] or record['original_source_code_pins']!=f['source_code_pins']:raise ValueError('IO_ORIGINAL_FULL_FREEZE_SOURCE_AND_PINS_REQUIRED')
    pins={str(Path(r['source_ref']).resolve()):r['sha256'] for r in f['source_code_pins']}
    allowed={str((parent.REPO/'scripts/research/a2/evaluation/joint_method_space_risk_execution_r6.py').resolve()):'_artifact',str((parent.REPO/'scripts/research/a2/training/joint_method_space_gross_execution_r6.py').resolve()):'_save'}
    changes=record['io_changes']
    if not isinstance(changes,list) or not 1<=len(changes)<=2:raise ValueError('IO_FINITE_RISK_GROSS_CHANGES_ONLY')
    result={}
    for item in changes:
        if not isinstance(item,dict) or set(item)!={'source_ref','old_sha256','new_sha256','old_snapshot_ref','function','change'}:raise ValueError('IO_EXACT_CHANGE_SCHEMA_REQUIRED')
        p=str(Path(item['source_ref']).resolve())
        if p not in allowed or p in result or item['function']!=allowed[p] or item['change'] not in {'OPEN_RB_TO_R_PLUS_B_ONLY','OPEN_RB_TO_R_PLUS_B_AND_EXACT_PAID_RECOVERY'} or item['old_sha256']!=pins.get(p):raise ValueError('IO_EXACT_FROZEN_OWNER_REQUIRED')
        if item['old_snapshot_ref'].get('sha256')!=item['old_sha256']:raise ValueError('IO_OLD_SNAPSHOT_PIN_REQUIRED')
        old=_r6_io_read(item['old_snapshot_ref']);new=_r6_io_read(dict(source_ref=p,sha256=item['new_sha256']))
        if item['change']=='OPEN_RB_TO_R_PLUS_B_ONLY':_r6_io_mode_ast(old,new,item['function'])
        else:
            if item['function']!='_artifact' or record['paid_recovery'] is None:raise ValueError('IO_PAID_RISK_RECOVERY_ONLY')
            _r6_io_paid_mode_ast(old,new)
        result[p]=item['new_sha256']
    g=record['runtime_guard_change'];rp=str((parent.REPO/'scripts/research/a2/evaluation/joint_method_space_runtime_r6.py').resolve())
    if not isinstance(g,dict) or set(g)!={'source_ref','old_sha256','new_sha256','old_snapshot_ref','change'} or str(Path(g['source_ref']).resolve())!=rp or g['old_sha256']!=pins.get(rp) or g['old_snapshot_ref'].get('sha256')!=g['old_sha256'] or g['change']!='EXACT_REGISTERED_IO_PIN_LOOP_AND_CLOSED_HELPERS_ONLY':raise ValueError('IO_EXACT_RUNTIME_LINEAGE_REQUIRED')
    old=_r6_io_read(g['old_snapshot_ref']);runtime_ref=dict(source_ref=rp,sha256=g['new_sha256'])
    if runtime_code_ref is not None:
        if not isinstance(runtime_code_ref,dict) or g['new_sha256']!='21d6bb3fc28f396a8cebc06a84538f4097d848fae6d13b6569443e29eb6ee210' or runtime_code_ref.get('sha256')!=g['new_sha256']:raise ValueError('LEDGER_IO_R1_EXACT_HISTORICAL_RUNTIME_OVERRIDE_ONLY')
        runtime_ref=runtime_code_ref
    new=_r6_io_read(runtime_ref)
    _r6_io_runtime_ast(old,new);result[rp]=g['new_sha256']
    if Path(record['review_ref'].get('source_ref','')).name!='R6_EXECUTION_IO_INDEPENDENT_REVIEW_R1.json':raise ValueError('IO_EXACT_INDEPENDENT_REVIEW_FILENAME_REQUIRED')
    review=_r6_io_read(record['review_ref'],json_body=True)
    expected=dict(kind='INDEPENDENT_R6_EXECUTION_IO_REVIEW',status='PASS',independent=True,author='/root/r4_short_risk_audit',reviewer='/root',research_id=ID,science_freeze_sha256=freeze_sha,source_authority_sha256=f['source_authority_ref']['sha256'],equivalence_subject_sha256=_r6_io_digest({k:v for k,v in record.items() if k!='review_ref'}),accepted_new_code_pins=result,scope='EXACT_IO_MODES_PAID_ARTIFACT_RESTORE_AND_RUNTIME_LINEAGE_ONLY')
    if any(_r6_io_digest(review.get(k))!=_r6_io_digest(v) for k,v in expected.items()):raise ValueError('IO_ACTUAL_FULL_SUBJECT_INDEPENDENT_REVIEW_REQUIRED')
    if record['recovery_proposal_ref'] is not None:
        proof=_r6_io_read(record['recovery_proposal_ref'],json_body=True)
        expected_recovery=dict(original_failed_event_preserved=True,refund=False,new_reservation_units=0,new_compute_invocations=0,new_backend_invocations=0)
        if proof.get('schema')!='B_R6_RISK_IO_REPAIR_PROPOSAL_V1' or proof.get('research_id')!=ID or proof.get('original_science_freeze_ref',{}).get('sha256')!=freeze_sha or proof.get('source_authority_ref',{}).get('sha256')!=f['source_authority_ref']['sha256'] or any(_r6_io_digest(proof.get('recovery_protocol',{}).get(k))!=_r6_io_digest(v) for k,v in expected_recovery.items()):raise ValueError('IO_ZERO_COMPUTE_NONREFUNDABLE_RECOVERY_REQUIRED')
    if record['paid_recovery'] is not None:_r6_io_paid_binding(record['paid_recovery'],run,freeze_sha,f['source_authority_ref']['sha256'])
    return result

def _r6_io_code_pin_guard(run,f,freeze_sha):
    from scripts.maintenance import research_registry
    root=parent.read_json(parent.REPO/'config/research_registry.json')['registry_root']
    q=research_registry.query_registry(root,entity_id=ID)
    if q.get('status')!='PASS' or q.get('count')!=1:raise ValueError('IO_CANONICAL_EXACT_R6_REQUIRED')
    row=q['entities'][0];m=row.get('metadata',{})
    if row.get('status') not in ('OPEN','ACTIVE') or m.get('science_freeze_sha256')!=freeze_sha or m.get('source_authority_sha256')!=f['source_authority_ref']['sha256'] or any(m.get(k) is not False for k in ('fit_authority','formal_freeze_authority','strict_PIT_promotion_eligible')):raise ValueError('IO_REGISTERED_ORIGINAL_R6_SCIENCE_SOURCE_REQUIRED')
    native_io=_r6_native_call_and_window_admission(m,run,f,freeze_sha)
    ledger_io=_r6_ledger_io_admission(m,run,f,freeze_sha,runtime_code_ref=(native_io['runtime_snapshot_ref'] if native_io is not None else None))
    binding=m.get('execution_io_equivalence_ref');overrides={}
    if binding is not None:
        if not isinstance(binding,dict) or Path(binding.get('source_ref',''))!=run/'R6_EXECUTION_IO_EQUIVALENCE_R1.json':raise ValueError('IO_ONE_EXACT_REGISTERED_EQUIVALENCE_REF_REQUIRED')
        overrides=_r6_io_record(_r6_io_read(binding,json_body=True),f,run,freeze_sha,runtime_code_ref=(ledger_io[0] if ledger_io is not None else None))
    if ledger_io is not None:
        overrides[str(Path(ledger_io[1]['source_ref']).resolve())]=ledger_io[1]['sha256']
    if native_io is not None:
        overrides.update(native_io['overrides'])
    for ref in f['source_code_pins']:
        p=str(Path(ref['source_ref']).resolve());parent._pin(ref['source_ref'],overrides.get(p,ref['sha256']),'R6_REGISTERED_IO_CODE')

def _r6_io_paid_mode_ast(old,new):
    import ast,copy
    left=ast.parse(old);right=ast.parse(new)
    helper=[n for n in right.body if isinstance(n,ast.FunctionDef) and n.name=='_commit_exact_paid_cache']
    if len(helper)!=1:raise ValueError('IO_ONE_COMMIT_RECOVERY_HELPER_REQUIRED')
    right.body.remove(helper[0])
    cls=next(n for n in right.body if isinstance(n,ast.ClassDef) and n.name=='RiskOperations')
    methods=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_restore_exact_paid_cache']
    if len(methods)!=1:raise ValueError('IO_ONE_CLASS_RECOVERY_METHOD_REQUIRED')
    cls.body.remove(methods[0])
    init=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
    expected=ast.parse('self._restore_exact_paid_cache()').body[0]
    if ast.dump(init.body[-1],include_attributes=False)!=ast.dump(expected,include_attributes=False):raise ValueError('IO_ONE_FINAL_RECOVERY_HOOK_ONLY')
    init.body.pop()
    fn=next(n for n in right.body if isinstance(n,ast.FunctionDef) and n.name=='_artifact')
    calls=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='open' and n.args and isinstance(n.args[0],ast.Constant) and n.args[0].value=='r+b']
    if len(calls)!=1:raise ValueError('IO_RECOVERY_ONE_MODE_REQUIRED')
    calls[0].args[0].value='rb'
    if ast.dump(left,include_attributes=False)!=ast.dump(right,include_attributes=False):raise ValueError('IO_OTHER_RISK_AST_CHANGE_FORBIDDEN')

def _r6_io_paid_binding(paid,run,freeze_sha,source_sha):
    from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash
    required={'failed_ledger_snapshot_ref','custody_ref','key','node_id','result_sha256','cache_event_sha256','temp_ref','final_path','recovery_receipt_relative'}
    key='fa55063abf9fd62d7ac8a2588ec6cefc46832bc9ea365bcb0442cae7d76801bb'
    if not isinstance(paid,dict) or set(paid)!=required or paid['key']!=key or paid['node_id']!='risk:'+key or paid['recovery_receipt_relative']!='work/R6_PAID_CACHE_RECOVERY_R1.json':raise ValueError('IO_ONE_EXACT_ALREADY_PAID_KEY_REQUIRED')
    custody=_r6_io_read(paid['custody_ref'],json_body=True);ledger=_r6_io_read(paid['failed_ledger_snapshot_ref'],json_body=True)
    if custody.get('schema')!='B_R6_RISK_IO_FAILURE_CUSTODY_V1' or custody.get('research_id')!=ID or custody.get('original_science_freeze_ref',{}).get('sha256')!=freeze_sha or custody.get('source_authority_ref',{}).get('sha256')!=source_sha or ledger.get('research_id')!=ID or ledger.get('freeze_sha256')!=freeze_sha:raise ValueError('IO_ORIGINAL_PAID_SOURCE_SCIENCE_CUSTODY_REQUIRED')
    frozen=custody.get('immutable_failed_ledger_snapshot_ref',{})
    if paid['failed_ledger_snapshot_ref']['sha256']!=frozen.get('sha256') or Path(paid['failed_ledger_snapshot_ref']['source_ref'])!=Path(frozen.get('path','')):raise ValueError('IO_EXACT_FAILED_SNAPSHOT_REQUIRED')
    rows=[e for e in ledger.get('physical_events',[]) if e.get('node_id')=='risk:'+key]
    if len(rows)!=1 or rows[0].get('status')!='FAILED_NONREFUNDABLE' or type(rows[0].get('units')) is not int or rows[0]['units']!=1 or rows[0].get('physical_kind')!='scaler':raise ValueError('IO_ORIGINAL_FAILED_SINGLE_DEBIT_REQUIRED')
    event=rows[0].get('details',{}).get('cache_event',{})
    if paid['cache_event_sha256']!=content_hash(event) or event.get('key')!=key or event.get('name')!='r6:market_mean' or event.get('kind')!='scaler' or paid['result_sha256']!=event.get('result_sha256') or paid['result_sha256']!=custody.get('cache_operation',{}).get('result_sha256'):raise ValueError('IO_ORIGINAL_CACHE_CONTEXT_AND_VALUE_DIGEST_REQUIRED')
    t=paid['temp_ref'];ct=custody.get('serialized_temp_ref',{})
    exact=run/'models/risk/primitives'/(key+'.joblib')
    if not isinstance(t,dict) or set(t)!={'source_ref','sha256','bytes'} or type(t['bytes']) is not int or t['bytes']!=ct.get('bytes') or t['sha256']!=ct.get('sha256') or Path(t['source_ref'])!=Path(ct.get('path','')) or Path(t['source_ref'])!=exact.with_suffix('.joblib.tmp') or Path(paid['final_path'])!=exact or Path(paid['final_path'])!=Path(custody.get('intended_final_path','')):raise ValueError('IO_EXACT_SERIALIZED_TEMP_CUSTODY_REQUIRED')
    return paid

def guard_io_recovery(run,freeze_sha):
    run=guard_numeric(run,freeze_sha)
    from scripts.maintenance import research_registry
    root=parent.read_json(parent.REPO/'config/research_registry.json')['registry_root']
    q=research_registry.query_registry(root,entity_id=ID)
    if q.get('status')!='PASS' or q.get('count')!=1:raise ValueError('IO_RECOVERY_ACCEPTED_CANONICAL_ENTITY_REQUIRED')
    m=q['entities'][0].get('metadata',{});binding=m.get('execution_io_equivalence_ref')
    if not isinstance(binding,dict) or Path(binding.get('source_ref',''))!=run/'R6_EXECUTION_IO_EQUIVALENCE_R1.json':raise ValueError('IO_RECOVERY_CANONICAL_PHYSICAL_BINDING_REQUIRED')
    record=_r6_io_read(binding,json_body=True);f=parent.read_json(run/FILENAME)
    native_io=_r6_native_call_and_window_admission(m,run,f,freeze_sha)
    ledger_io=_r6_ledger_io_admission(m,run,f,freeze_sha,runtime_code_ref=(native_io['runtime_snapshot_ref'] if native_io is not None else None))
    _r6_io_record(record,f,run,freeze_sha,runtime_code_ref=(ledger_io[0] if ledger_io is not None else None))
    paid=record['paid_recovery']
    if paid is None:raise ValueError('IO_EXACT_PAID_RECOVERY_NOT_ADMITTED')
    return dict(paid,io_equivalence_ref=dict(binding))


def _r6_read_ledger(run):
    """Read only this managed R6 ledger; leave generic metadata limits intact."""
    import stat
    run=Path(run)
    if not run.is_absolute() or run.drive.upper() in ('E:','F:'):raise ValueError('R6_LEDGER_ABSOLUTE_ACCESSIBLE_DRIVE_REQUIRED')
    paths=resolve(parent.REPO)
    if run.parent!=paths.backtest_root/'V24':raise ValueError('R6_LEDGER_EXACT_MANAGED_RUN_REQUIRED')
    p=run/'work/R6_PHYSICAL_LEDGER.json'
    # Inspect lexical ancestors from root to leaf before resolving any link.
    for item in reversed((p,*p.parents)):
        info=item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400):raise ValueError('R6_LEDGER_LINK_OR_REPARSE_FORBIDDEN')
    if run.resolve(strict=True)!=run.absolute() or p.resolve(strict=True)!=p.absolute():raise ValueError('R6_LEDGER_EXACT_ABSOLUTE_PATH_REQUIRED')
    assert_safe_output_path(p,kind='backtest',paths=paths)
    limit=1024*1024*1024
    if p.stat().st_size>limit:raise ValueError('R6_LEDGER_BOUNDED_READ_LIMIT')
    with p.open('rb') as handle:raw=handle.read(limit+1)
    if len(raw)>limit:raise ValueError('R6_LEDGER_GROWTH_OVER_BOUND')
    value=json.loads(raw.decode('utf-8'))
    if not isinstance(value,dict) or value.get('research_id')!=ID:raise ValueError('R6_LEDGER_EXACT_RESEARCH_ID_REQUIRED')
    return value

def _r6_ledger_io_policy():
    return dict(relative_path='work/R6_PHYSICAL_LEDGER.json',maximum_bytes=1024*1024*1024,absolute_managed_V24_run_required=True,EF_access=False,symlink_or_reparse_allowed=False,resolved_must_equal_absolute=True,stat_before_bounded_read=True,growth_over_bound_rejected=True,research_id=ID,generic_parent_reader_changed=False)

def _r6_ledger_io_constraints():
    return dict(science_changed=False,source_changed=False,methods_targets_parameters_changed=False,pools_or_DAG_changed=False,state_keys_changed=False,debits_changed=False,generic_parent_reader_changed=False,source_promotion=False,new_fit_for_recovery=0,new_reserve_for_recovery=0,budget_refund=False,old_failure_preserved=True,scientific_retry=0,test2026_reads=0,R5_numeric_economic_read=False)

def _r6_ledger_io_ast(old,new):
    """Normalize only the declared ledger I/O adapter, then compare whole AST."""
    import ast,copy
    left=ast.parse(old);right=ast.parse(new)
    names={'_r6_read_ledger','_r6_ledger_io_policy','_r6_ledger_io_constraints','_r6_ledger_io_ast','_r6_ledger_io_admission'}
    added=[n for n in right.body if isinstance(n,ast.FunctionDef) and n.name in names]
    if {n.name for n in added}!=names or len(added)!=len(names):raise ValueError('LEDGER_IO_EXACT_ADDED_HELPER_SET_REQUIRED')
    right.body=[n for n in right.body if n not in added]
    def function(tree,name):
        matches=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name]
        if len(matches)!=1:raise ValueError('LEDGER_IO_EXACT_FUNCTION_REQUIRED:'+name)
        return matches[0]
    def block(fn,new_text,old_text):
        wanted=ast.parse(new_text).body;replacement=ast.parse(old_text).body
        fingerprint=lambda nodes:[ast.dump(n,include_attributes=False) for n in nodes]
        expected=fingerprint(wanted);matches=[]
        for node in ast.walk(fn):
            for field,value in ast.iter_fields(node):
                if isinstance(value,list):
                    for i in range(len(value)-len(wanted)+1):
                        if all(isinstance(n,ast.AST) for n in value[i:i+len(wanted)]) and fingerprint(value[i:i+len(wanted)])==expected:matches.append((value,i))
        if len(matches)!=1:raise ValueError('LEDGER_IO_EXACT_TECHNICAL_BLOCK_REQUIRED')
        value,i=matches[0];value[i:i+len(wanted)]=copy.deepcopy(replacement)
    lrecord=function(left,'_r6_io_record');rrecord=function(right,'_r6_io_record')
    expected=copy.deepcopy(lrecord.args)
    expected.kwonlyargs.append(ast.arg(arg='runtime_code_ref'));expected.kw_defaults.append(ast.Constant(value=None))
    if ast.dump(rrecord.args,include_attributes=False)!=ast.dump(expected,include_attributes=False):raise ValueError('LEDGER_IO_ONLY_KEYWORD_SNAPSHOT_ARGUMENT_ALLOWED')
    rrecord.args=copy.deepcopy(lrecord.args)
    block(rrecord,"""old=_r6_io_read(g['old_snapshot_ref']);runtime_ref=dict(source_ref=rp,sha256=g['new_sha256'])
if runtime_code_ref is not None:
    if not isinstance(runtime_code_ref,dict) or g['new_sha256']!='21d6bb3fc28f396a8cebc06a84538f4097d848fae6d13b6569443e29eb6ee210' or runtime_code_ref.get('sha256')!=g['new_sha256']:raise ValueError('LEDGER_IO_R1_EXACT_HISTORICAL_RUNTIME_OVERRIDE_ONLY')
    runtime_ref=runtime_code_ref
new=_r6_io_read(runtime_ref)""","""old=_r6_io_read(g['old_snapshot_ref']);new=_r6_io_read(dict(source_ref=rp,sha256=g['new_sha256']))""")
    fn=function(right,'_r6_io_code_pin_guard')
    block(fn,'ledger_io=_r6_ledger_io_admission(m,run,f,freeze_sha)','')
    block(fn,"overrides=_r6_io_record(_r6_io_read(binding,json_body=True),f,run,freeze_sha,runtime_code_ref=(ledger_io[0] if ledger_io is not None else None))","overrides=_r6_io_record(_r6_io_read(binding,json_body=True),f,run,freeze_sha)")
    block(fn,"""if ledger_io is not None:
    overrides[str(Path(ledger_io[1]['source_ref']).resolve())]=ledger_io[1]['sha256']""",'')
    fn=function(right,'guard_io_recovery')
    block(fn,"m=q['entities'][0].get('metadata',{});binding=m.get('execution_io_equivalence_ref')","binding=q['entities'][0].get('metadata',{}).get('execution_io_equivalence_ref')")
    block(fn,'ledger_io=_r6_ledger_io_admission(m,run,f,freeze_sha)','')
    block(fn,'_r6_io_record(record,f,run,freeze_sha,runtime_code_ref=(ledger_io[0] if ledger_io is not None else None))','_r6_io_record(record,f,run,freeze_sha)')
    cls=next(n for n in right.body if isinstance(n,ast.ClassDef) and n.name=='R6Ledger')
    init=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
    calls=[n for n in ast.walk(init) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='_r6_read_ledger']
    if len(calls)!=1 or ast.dump(calls[0],include_attributes=False)!=ast.dump(ast.parse('_r6_read_ledger(self.run)',mode='eval').body,include_attributes=False):raise ValueError('LEDGER_IO_ONLY_EXACT_CONSTRUCTOR_READ_ALLOWED')
    calls[0].func=ast.Attribute(value=ast.Name(id='parent',ctx=ast.Load()),attr='read_json',ctx=ast.Load());calls[0].args=[ast.Name(id='path',ctx=ast.Load())]
    if ast.dump(left,include_attributes=False)!=ast.dump(right,include_attributes=False):raise ValueError('LEDGER_IO_OTHER_MODULE_AST_CHANGE_FORBIDDEN')

def _r6_ledger_io_admission(m,run,f,freeze_sha,*,runtime_code_ref=None):
    """Validate the closed registered R2 subject before accepting new runtime."""
    binding=m.get('execution_ledger_io_equivalence_ref')
    if binding is None:return None
    if not isinstance(binding,dict) or Path(binding.get('source_ref',''))!=run/'R6_LEDGER_IO_EQUIVALENCE_V2.json':raise ValueError('LEDGER_IO_ONE_EXACT_REGISTERED_REF_REQUIRED')
    record=_r6_io_read(binding,json_body=True)
    required={'schema','research_id','science_freeze_ref','source_authority_ref','prior_execution_io_equivalence_ref','original_source_code_pins','runtime_ledger_change','ledger_read_policy','constraints','review_ref','fault_custody_ref'}
    if not isinstance(record,dict) or set(record)!=required or record['schema']!='B_R6_LEDGER_IO_EQUIVALENCE_V2' or record['research_id']!=ID or _r6_io_digest(record['ledger_read_policy'])!=_r6_io_digest(_r6_ledger_io_policy()) or _r6_io_digest(record['constraints'])!=_r6_io_digest(_r6_ledger_io_constraints()):raise ValueError('LEDGER_IO_EXACT_CLOSED_SCHEMA_BOUNDARY_REQUIRED')
    if record['science_freeze_ref']!=dict(source_ref=str(run/FILENAME),sha256=freeze_sha) or record['source_authority_ref']!=f['source_authority_ref'] or record['original_source_code_pins']!=f['source_code_pins']:raise ValueError('LEDGER_IO_ORIGINAL_SCIENCE_SOURCE_FULL_PINS_REQUIRED')
    prior=record['prior_execution_io_equivalence_ref']
    if prior!=m.get('execution_io_equivalence_ref') or not isinstance(prior,dict) or Path(prior.get('source_ref',''))!=run/'R6_EXECUTION_IO_EQUIVALENCE_R1.json':raise ValueError('LEDGER_IO_ORIGINAL_REGISTERED_R1_REQUIRED')
    _r6_io_read(prior,json_body=True)
    g=record['runtime_ledger_change'];rp=str((parent.REPO/'scripts/research/a2/evaluation/joint_method_space_runtime_r6.py').resolve())
    paths=resolve(parent.REPO);snapshot=paths.cache_root/'V24/B_METHOD_SPACE_R6'/run.name/'source_audit/joint_method_space_runtime_r6_21d6_snapshot.py'
    if not isinstance(g,dict) or set(g)!={'source_ref','old_sha256','new_sha256','old_snapshot_ref','change'} or Path(g['source_ref'])!=Path(rp) or g['old_sha256']!='21d6bb3fc28f396a8cebc06a84538f4097d848fae6d13b6569443e29eb6ee210' or g['old_snapshot_ref']!=dict(source_ref=str(snapshot),sha256=g['old_sha256']) or g['change']!='EXACT_R6_LEDGER_ONLY_1GIB_READER_AND_CLOSED_LEDGER_ADMISSION_ONLY':raise ValueError('LEDGER_IO_EXACT_RUNTIME_SNAPSHOT_LINEAGE_REQUIRED')
    old=_r6_io_read(g['old_snapshot_ref']);live=dict(source_ref=rp,sha256=g['new_sha256']);runtime_ref=live
    if runtime_code_ref is not None:
        if not isinstance(runtime_code_ref,dict) or g['new_sha256']!='76f4051f1b7c66798a5d108c427e773023067e5a8c742b27c1f97e9ab74dffce' or runtime_code_ref.get('sha256')!=g['new_sha256']:raise ValueError('NATIVE_V3_EXACT_V2_HISTORICAL_RUNTIME_ONLY')
        runtime_ref=runtime_code_ref
    new=_r6_io_read(runtime_ref)
    _r6_ledger_io_ast(old,new)
    fault_ref=record['fault_custody_ref']
    if not isinstance(fault_ref,dict) or Path(fault_ref.get('source_ref',''))!=run/'work/R6_OPPORTUNITY_PREFIT_ENGINEERING_EXIT_RECEIPT_R1.json':raise ValueError('LEDGER_IO_EXACT_ORIGINAL_PREFIT_FAULT_REQUIRED')
    fault=_r6_io_read(fault_ref,json_body=True)
    expected_fault=dict(schema='B_R6_OPPORTUNITY_PREFIT_ENGINEERING_EXIT_RECEIPT_V1',research_id=ID,status='ENGINEERING_BLOCK_BEFORE_TRAINING_LOOP',exit_code=1,whole_freeze_sha256=freeze_sha,ledger_same_as_risk_terminal=True,new_fit=0,new_reservation=0,new_backend=0,scientific_retry=0,test2026_reads=0,R5_results_reads=0,EF_access=False,provider_fetch=False)
    if any(_r6_io_digest(fault.get(k))!=_r6_io_digest(v) for k,v in expected_fault.items()):raise ValueError('LEDGER_IO_ORIGINAL_ZERO_FIT_FAILURE_CUSTODY_REQUIRED')
    review_ref=record['review_ref']
    if not isinstance(review_ref,dict) or Path(review_ref.get('source_ref',''))!=run/'work/R6_LEDGER_IO_INDEPENDENT_REVIEW_V2.json':raise ValueError('LEDGER_IO_EXACT_INDEPENDENT_REVIEW_REF_REQUIRED')
    review=_r6_io_read(review_ref,json_body=True)
    expected=dict(kind='INDEPENDENT_R6_LEDGER_IO_REVIEW',status='PASS',independent=True,author='/root/r4_short_risk_audit',reviewer='/root',research_id=ID,science_freeze_sha256=freeze_sha,source_authority_sha256=f['source_authority_ref']['sha256'],prior_execution_io_equivalence_sha256=prior['sha256'],equivalence_subject_sha256=_r6_io_digest({k:v for k,v in record.items() if k!='review_ref'}),accepted_new_code_pins={rp:g['new_sha256']},scope='EXACT_MANAGED_R6_LEDGER_BOUNDED_READ_AND_REGISTERED_TECHNICAL_LINEAGE_ONLY')
    if any(_r6_io_digest(review.get(k))!=_r6_io_digest(v) for k,v in expected.items()):raise ValueError('LEDGER_IO_WHOLE_SUBJECT_INDEPENDENT_REVIEW_REQUIRED')
    return dict(g['old_snapshot_ref']),live

def _r6_native_call_and_window_constraints():
    return dict(science_changed=False,source_changed=False,target_changed=False,methods_parameters_capacity_seed_loop_changed=False,inputs_pool_PIT_or_DAG_changed=False,state_keys_changed=False,debits_or_caps_changed=False,failed_paid_rows_preserved=True,scientific_retry=0,new_fit_for_recovery=0,new_reserve_for_recovery=0,new_backend_for_recovery=0,budget_refund=False,source_promotion=False,test2026_reads=0,R5_numeric_economic_read=False,EF_access=False,network_provider_fetch=False)

def _r6_native_call_and_window_pure_ast(old,new,change):
    import ast,copy,hashlib
    left=ast.parse(old);right=ast.parse(new)
    def function(tree,name):
        matches=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name]
        if len(matches)!=1:raise ValueError('NATIVE_V3_EXACT_PURE_FUNCTION_REQUIRED')
        return matches[0]
    fn=function(right,'fit_model');calls=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='function']
    if len(calls)!=1:raise ValueError('NATIVE_V3_ONE_EXACT_MODEL_CALL_REQUIRED')
    kws=[k for k in calls[0].keywords if k.arg=='quantile']
    if len(kws)!=1 or not isinstance(kws[0].value,ast.Constant) or kws[0].value.value is not None:raise ValueError('NATIVE_V3_EXACT_ORIGINAL_NONE_DEFAULT_ONLY')
    calls[0].keywords.remove(kws[0]);before=function(left,'build_windows');after=function(right,'build_windows')
    body_digest=lambda node:hashlib.sha256(ast.dump(node,include_attributes=False).encode()).hexdigest()
    if change.get('window_before_ast_sha256')!=body_digest(before) or change.get('window_after_ast_sha256')!=body_digest(after):raise ValueError('NATIVE_V3_EXACT_REVIEWED_WINDOW_BODY_REQUIRED')
    after.body=copy.deepcopy(before.body)
    if ast.dump(left,include_attributes=False)!=ast.dump(right,include_attributes=False):raise ValueError('NATIVE_V3_OTHER_PURE_MODULE_AST_CHANGE_FORBIDDEN')

def _r6_native_call_and_window_runtime_ast(old,new):
    import ast,copy
    left=ast.parse(old);right=ast.parse(new)
    names={'_r6_native_call_and_window_constraints','_r6_native_call_and_window_pure_ast','_r6_native_call_and_window_runtime_ast','_r6_native_call_and_window_admission'}
    added=[n for n in right.body if isinstance(n,ast.FunctionDef) and n.name in names]
    if {n.name for n in added}!=names or len(added)!=len(names):raise ValueError('NATIVE_V3_EXACT_RUNTIME_HELPER_SET_REQUIRED')
    right.body=[n for n in right.body if n not in added]
    def function(tree,name):
        matches=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name]
        if len(matches)!=1:raise ValueError('NATIVE_V3_EXACT_RUNTIME_FUNCTION_REQUIRED')
        return matches[0]
    def block(fn,new_text,old_text):
        wanted=ast.parse(new_text).body;replacement=ast.parse(old_text).body
        fingerprint=lambda nodes:[ast.dump(n,include_attributes=False) for n in nodes]
        expected=fingerprint(wanted);matches=[]
        for node in ast.walk(fn):
            for field,value in ast.iter_fields(node):
                if isinstance(value,list):
                    for i in range(len(value)-len(wanted)+1):
                        if all(isinstance(n,ast.AST) for n in value[i:i+len(wanted)]) and fingerprint(value[i:i+len(wanted)])==expected:matches.append((value,i))
        if len(matches)!=1:raise ValueError('NATIVE_V3_ONE_EXACT_TECHNICAL_BLOCK_REQUIRED')
        value,i=matches[0];value[i:i+len(wanted)]=copy.deepcopy(replacement)
    oldfn=function(left,'_r6_ledger_io_admission');newfn=function(right,'_r6_ledger_io_admission')
    expected=copy.deepcopy(oldfn.args);expected.kwonlyargs.append(ast.arg(arg='runtime_code_ref'));expected.kw_defaults.append(ast.Constant(value=None))
    if ast.dump(newfn.args,include_attributes=False)!=ast.dump(expected,include_attributes=False):raise ValueError('NATIVE_V3_ONLY_HISTORICAL_SNAPSHOT_KEYWORD_ALLOWED')
    newfn.args=copy.deepcopy(oldfn.args)
    block(newfn,"""old=_r6_io_read(g['old_snapshot_ref']);live=dict(source_ref=rp,sha256=g['new_sha256']);runtime_ref=live
if runtime_code_ref is not None:
    if not isinstance(runtime_code_ref,dict) or g['new_sha256']!='76f4051f1b7c66798a5d108c427e773023067e5a8c742b27c1f97e9ab74dffce' or runtime_code_ref.get('sha256')!=g['new_sha256']:raise ValueError('NATIVE_V3_EXACT_V2_HISTORICAL_RUNTIME_ONLY')
    runtime_ref=runtime_code_ref
new=_r6_io_read(runtime_ref)""","old=_r6_io_read(g['old_snapshot_ref']);live=dict(source_ref=rp,sha256=g['new_sha256']);new=_r6_io_read(live)")
    for name in ('_r6_io_code_pin_guard','guard_io_recovery'):
        block(function(right,name),"""native_io=_r6_native_call_and_window_admission(m,run,f,freeze_sha)
ledger_io=_r6_ledger_io_admission(m,run,f,freeze_sha,runtime_code_ref=(native_io['runtime_snapshot_ref'] if native_io is not None else None))""",'ledger_io=_r6_ledger_io_admission(m,run,f,freeze_sha)')
    block(function(right,'_r6_io_code_pin_guard'),"""if native_io is not None:
    overrides.update(native_io['overrides'])""",'')
    if ast.dump(left,include_attributes=False)!=ast.dump(right,include_attributes=False):raise ValueError('NATIVE_V3_OTHER_RUNTIME_MODULE_AST_CHANGE_FORBIDDEN')

def _r6_native_call_and_window_admission(m,run,f,freeze_sha):
    binding=m.get('execution_native_call_and_window_equivalence_ref')
    if binding is None:return None
    if not isinstance(binding,dict) or Path(binding.get('source_ref',''))!=run/'R6_NATIVE_CALL_AND_WINDOW_EQUIVALENCE_V3.json':raise ValueError('NATIVE_V3_EXACT_CANONICAL_REF_REQUIRED')
    record=_r6_io_read(binding,json_body=True)
    required={'schema','research_id','science_freeze_ref','source_authority_ref','original_source_code_pins','prior_execution_io_equivalence_ref','prior_ledger_io_equivalence_ref','pure_change','runtime_guard_change','constraints','window_equivalence_proof_ref','call_defaults_test_ref','call_byte_equivalence_proof_ref','fault_custody_ref','review_ref'}
    if not isinstance(record,dict) or set(record)!=required or record['schema']!='B_R6_NATIVE_CALL_AND_WINDOW_EQUIVALENCE_V3' or record['research_id']!=ID or _r6_io_digest(record['constraints'])!=_r6_io_digest(_r6_native_call_and_window_constraints()):raise ValueError('NATIVE_V3_CLOSED_BOUNDARY_REQUIRED')
    if record['science_freeze_ref']!=dict(source_ref=str(run/FILENAME),sha256=freeze_sha) or record['source_authority_ref']!=f['source_authority_ref'] or record['original_source_code_pins']!=f['source_code_pins']:raise ValueError('NATIVE_V3_ORIGINAL_SCIENCE_SOURCE_AND_40_PINS_REQUIRED')
    priors=(('prior_execution_io_equivalence_ref','execution_io_equivalence_ref','R6_EXECUTION_IO_EQUIVALENCE_R1.json','e0f8ebd3eaca3ac210795dfaa1e4fbc2ee0d114cd8e1b2c2929de315f3bf8e94'),('prior_ledger_io_equivalence_ref','execution_ledger_io_equivalence_ref','R6_LEDGER_IO_EQUIVALENCE_V2.json','29be3b9946f1afeb577ad2f2897bbf3bd4ded2b7ff2ddfaa77a3385f05beb6f3'))
    for field,key,filename,sha in priors:
        expected=dict(source_ref=str(run/filename),sha256=sha)
        if record[field]!=expected or record[field]!=m.get(key):raise ValueError('NATIVE_V3_ORIGINAL_REGISTERED_R1_AND_V2_REQUIRED')
        _r6_io_read(record[field],json_body=True)
    paths=resolve(parent.REPO);base=paths.cache_root/'V24/B_METHOD_SPACE_R6'/run.name/'source_audit'
    pure_path=str((parent.REPO/'scripts/research/a2/training/joint_method_space_opportunity_r6.py').resolve());runtime_path=str((parent.REPO/'scripts/research/a2/evaluation/joint_method_space_runtime_r6.py').resolve())
    pins={str(Path(ref['source_ref']).resolve()):ref['sha256'] for ref in f['source_code_pins']};pc=record['pure_change'];rc=record['runtime_guard_change']
    if not isinstance(pc,dict) or set(pc)!={'source_ref','old_sha256','new_sha256','old_snapshot_ref','change','window_before_ast_sha256','window_after_ast_sha256'} or pc['source_ref']!=pure_path or pc['old_sha256']!='2ffc0775b995ce018181011c7b4dcb5a443ec614b97111efdc711a38e27d0ec4' or pins.get(pure_path)!=pc['old_sha256'] or pc['old_snapshot_ref']!=dict(source_ref=str(base/'joint_method_space_opportunity_r6_2ffc_snapshot.py'),sha256=pc['old_sha256']) or pc['change']!='EXACT_QUANTILE_NONE_AND_PROVEN_LAZY_WINDOW_MEMO_ONLY':raise ValueError('NATIVE_V3_EXACT_FROZEN_PURE_LINEAGE_REQUIRED')
    if not isinstance(rc,dict) or set(rc)!={'source_ref','old_sha256','new_sha256','old_snapshot_ref','change'} or rc['source_ref']!=runtime_path or rc['old_sha256']!='76f4051f1b7c66798a5d108c427e773023067e5a8c742b27c1f97e9ab74dffce' or rc['old_snapshot_ref']!=dict(source_ref=str(base/'joint_method_space_runtime_r6_76f405_snapshot.py'),sha256=rc['old_sha256']) or rc['change']!='EXACT_REGISTERED_NATIVE_DEFAULT_AND_WINDOW_TECHNICAL_ADMISSION_ONLY':raise ValueError('NATIVE_V3_EXACT_PREVIOUS_RUNTIME_LINEAGE_REQUIRED')
    pure_old=_r6_io_read(pc['old_snapshot_ref']);pure_new=_r6_io_read(dict(source_ref=pure_path,sha256=pc['new_sha256']))
    runtime_old=_r6_io_read(rc['old_snapshot_ref']);runtime_new=_r6_io_read(dict(source_ref=runtime_path,sha256=rc['new_sha256']))
    _r6_native_call_and_window_pure_ast(pure_old,pure_new,pc);_r6_native_call_and_window_runtime_ast(runtime_old,runtime_new)
    window_ref=record['window_equivalence_proof_ref']
    if not isinstance(window_ref,dict) or Path(window_ref.get('source_ref',''))!=base/'R6_WINDOW_MEMO_BITWISE_EQUIVALENCE_V3.json':raise ValueError('NATIVE_V3_EXACT_WINDOW_EQUIVALENCE_REF_REQUIRED')
    window=_r6_io_read(window_ref,json_body=True)
    expected_window=dict(schema='B_R6_WINDOW_MEMO_EQUIVALENCE_V3',status='PASS',window_before_ast_sha256=pc['window_before_ast_sha256'],window_after_ast_sha256=pc['window_after_ast_sha256'],synthetic_bitwise_equal=True,mask_reasons_keys_dtype_order_equal=True,requested_domain_and_error_gates_equal=True,restricted_data_reads=0,realfit=0,original_ref=dict(pc['old_snapshot_ref'],bytes=len(pure_old)),combined_candidate_ref=dict(source_ref=str(base/'joint_method_space_opportunity_r6_window_memo_candidate_v3.py'),sha256=pc['new_sha256'],bytes=len(pure_new)))
    if any(_r6_io_digest(window.get(k))!=_r6_io_digest(v) for k,v in expected_window.items()):raise ValueError('NATIVE_V3_FULL_WINDOW_BITWISE_PROOF_REQUIRED')
    call_ref=record['call_defaults_test_ref'];byte_ref=record['call_byte_equivalence_proof_ref']
    if not isinstance(call_ref,dict) or Path(call_ref.get('source_ref',''))!=base/'R6_CALL_DEFAULTS_SYNTHETIC_FIT_PREDICT_V3.json' or not isinstance(byte_ref,dict) or Path(byte_ref.get('source_ref',''))!=base/'R6_CALL_DEFAULTS_SYNTHETIC_BYTE_EQUIVALENCE_V3.json':raise ValueError('NATIVE_V3_EXACT_NATIVE_CALL_TEST_REFS_REQUIRED')
    call=_r6_io_read(call_ref,json_body=True);byte=_r6_io_read(byte_ref,json_body=True)
    expected_call=dict(schema='R6_CALL_DEFAULTS_SYNTHETIC_FIT_PREDICT_V3',candidate_sha256='88017a76607947c572bb55fdbc7f0db61a83d9ef37f55716eeb66fdf2e53049f',tests_run=11,passed=11,failures=0,errors=0,real_fit=0,real_reserve=0,actual_dataset_reads=0,actual_model_or_ledger_reads=0,test2026_reads=0,R5_numeric_economic_read=False,EF_access=False,live_modified=False)
    expected_byte=dict(schema='B_R6_CALL_DEFAULTS_SYNTHETIC_BYTE_EQUIVALENCE_V3',status='PASS',candidate_sha256='88017a76607947c572bb55fdbc7f0db61a83d9ef37f55716eeb66fdf2e53049f',TCN_native_state_byte_equal=True,TCN_prediction_byte_equal=True,TemporalMLP_native_state_byte_equal=True,TemporalMLP_prediction_byte_equal=True,real_fit=0,real_reserve=0,actual_dataset_or_ledger_or_model_reads=0,test2026_reads=0,R5_numeric_economic_read=False,EF_access=False,live_modified=False)
    if any(_r6_io_digest(call.get(k))!=_r6_io_digest(v) for k,v in expected_call.items()) or any(_r6_io_digest(byte.get(k))!=_r6_io_digest(v) for k,v in expected_byte.items()):raise ValueError('NATIVE_V3_FULL_NATIVE_DEFAULT_FIT_PREDICT_PROOF_REQUIRED')
    fault_ref=record['fault_custody_ref']
    if not isinstance(fault_ref,dict) or Path(fault_ref.get('source_ref',''))!=run/'work/R6_OPPORTUNITY_CONTROLLED_ENGINEERING_SUSPENSION_V3.json':raise ValueError('NATIVE_V3_EXACT_CONTROLLED_SUSPENSION_REF_REQUIRED')
    fault=_r6_io_read(fault_ref,json_body=True)
    expected_fault=dict(schema='B_R6_OPPORTUNITY_CONTROLLED_ENGINEERING_SUSPENSION_V3',research_id=ID,status='STOPPED_AT_ZERO_INFLIGHT_PREANNUAL_CHECKPOINT',whole_freeze_sha256=freeze_sha,source_authority_sha256=f['source_authority_ref']['sha256'],process_exit_observed=True,worker_alive=False,started_physical_nodes=0,annual_oof_files=0,annual_model_artifacts=0,new_scientific_fit_for_recovery=0,new_reservation_for_recovery=0,new_backend_for_recovery=0,scientific_retry=0,test2026_reads=0,R5_results_reads=0,R5_numeric_economic_read=False,EF_access=False,network_provider_fetch=False,refund=False,no_cache_or_paid_artifact_deleted=True,source_cause='SOURCE_REPRODUCED_PRE_FIT_INTERFACE_ERROR',real_deep_exception_message_observed=False)
    if any(_r6_io_digest(fault.get(k))!=_r6_io_digest(v) for k,v in expected_fault.items()):raise ValueError('NATIVE_V3_ACTUAL_ZERO_INFLIGHT_NO_RETRY_SUSPENSION_REQUIRED')
    review_ref=record['review_ref']
    if not isinstance(review_ref,dict) or Path(review_ref.get('source_ref',''))!=run/'work/R6_NATIVE_CALL_AND_WINDOW_INDEPENDENT_REVIEW_V3.json':raise ValueError('NATIVE_V3_EXACT_INDEPENDENT_FULL_REVIEW_REF_REQUIRED')
    review=_r6_io_read(review_ref,json_body=True);overrides={pure_path:pc['new_sha256'],runtime_path:rc['new_sha256']}
    expected_review=dict(kind='ROOT_INTEGRATION_R6_NATIVE_CALL_AND_WINDOW_REVIEW',status='PASS',independent=True,author='/root',reviewer='/root',research_id=ID,science_freeze_sha256=freeze_sha,source_authority_sha256=f['source_authority_ref']['sha256'],prior_execution_io_equivalence_sha256=record['prior_execution_io_equivalence_ref']['sha256'],prior_ledger_io_equivalence_sha256=record['prior_ledger_io_equivalence_ref']['sha256'],equivalence_subject_sha256=_r6_io_digest({k:v for k,v in record.items() if k!='review_ref'}),accepted_new_code_pins=overrides,scope='EXACT_DEFAULT_QUANTILE_NONE_LAZY_WINDOW_MEMO_AND_REGISTERED_RUNTIME_LINEAGE_ONLY')
    if any(_r6_io_digest(review.get(k))!=_r6_io_digest(v) for k,v in expected_review.items()):raise ValueError('NATIVE_V3_FULL_SUBJECT_INDEPENDENT_REVIEW_REQUIRED')
    component_refs=review.get('exactcomponent_independent_reviews')
    if not isinstance(component_refs,dict) or set(component_refs)!={'call','window','runtime'}:raise ValueError('NATIVE_V3_EXACT_NONAUTHOR_COMPONENT_REVIEW_SET_REQUIRED')
    import ast,hashlib
    fit_node=next(n for n in ast.parse(pure_new).body if isinstance(n,ast.FunctionDef) and n.name=='fit_model')
    fit_digest=hashlib.sha256(ast.dump(fit_node,include_attributes=False).encode()).hexdigest()
    components={
        'call':(base/'R6_NATIVE_CALL_DEFAULT_COMPONENT_REVIEW_V3.json',dict(schema='B_R6_NATIVE_CALL_DEFAULT_COMPONENT_REVIEW_V3',status='PASS',independent=True,author='/root/r4_opportunity_audit',reviewer='/root/r4_short_risk_audit',scope='EXACT_ORIGINAL_QUANTILE_NONE_DEFAULT_CALL_ONLY',fit_model_ast_sha256=fit_digest,full_fit_predict_evidence_ref=call_ref,byte_equivalence_evidence_ref=byte_ref)),
        'window':(run/'work/R6_WINDOW_COMPONENT_INDEPENDENT_REVIEW_V3.json',dict(kind='INDEPENDENT_R6_WINDOW_MEMO_COMPONENT_REVIEW',status='PASS',independent=True,author='/root/r4_opportunity_audit',code_author='/root/risk_budget_manifest_r2',reviewer='/root',scope='ONLY_BUILD_WINDOWS_EXACT_PER_CALL_LAZY_MEMO',accepted_pure_sha256=pc['new_sha256'],proof_sha256=window_ref['sha256'])),
        'runtime':(run/'work/R6_RUNTIME_COMPONENT_INDEPENDENT_REVIEW_V3.json',dict(kind='INDEPENDENT_R6_NATIVE_RUNTIME_COMPONENT_REVIEW',status='PASS',independent=True,author='/root/risk_budget_manifest_r2',code_author='/root/r4_short_risk_audit',reviewer='/root',scope='ONLY_REGISTERED_NATIVE_CALL_WINDOW_RUNTIME_LINEAGE',accepted_runtime_sha256=rc['new_sha256']))}
    for key,(path,expected) in components.items():
        ref=component_refs[key]
        if not isinstance(ref,dict) or Path(ref.get('source_ref',''))!=path:raise ValueError('NATIVE_V3_EXACT_COMPONENT_PHYSICAL_REF_REQUIRED')
        component=_r6_io_read(ref,json_body=True)
        if any(_r6_io_digest(component.get(k))!=_r6_io_digest(v) for k,v in expected.items()):raise ValueError('NATIVE_V3_ACTUAL_NONAUTHOR_COMPONENT_REVIEW_REQUIRED')
    return dict(runtime_snapshot_ref=dict(rc['old_snapshot_ref']),overrides=overrides)

@contextmanager
def stage_writer(run,stage):
    if stage not in ('freeze','qualification','opportunity','fusion','risk','gross','policy','report'):raise ValueError('EXACT_R6_STAGE_REQUIRED')
    run=Path(run);assert_safe_output_path(run,kind='backtest',paths=resolve(parent.REPO))
    # Same single-run writer owner/lock, so independent stages cannot race ledger.
    with parent.task_writer(run):yield

class R6Ledger(parent.DurableFitLedger):
    """New scope/counters; inherited atomic fsync persistence and writer discipline."""
    def __init__(self,run,freeze_sha):
        self.run=guard_numeric(run,freeze_sha);self.freeze_sha=freeze_sha
        path=self.run/'work/R6_PHYSICAL_LEDGER.json'
        self.status=_r6_read_ledger(self.run) if path.exists() else dict(research_id=ID,freeze_sha256=freeze_sha,budget_caps=CAPS,actual_counts={k:0 for k in CAPS},physical_events=[],deterministic_counters={},scientific_retry=0,test2026_reads=0,R5_numeric_economic_read=False)
        if self.status.get('freeze_sha256')!=freeze_sha or self.status.get('budget_caps')!=CAPS or self.status.get('test2026_reads')!=0 or self.status.get('R5_numeric_economic_read') is not False:raise ValueError('R6_LEDGER_IDENTITY_CHANGED')
        for k,limit in CAPS.items():
            value=self.status['actual_counts'].get(k)
            if type(value) is not int or not 0<=value<=limit:raise ValueError('R6_NONREFUNDABLE_COUNTER_CHANGED')
    def checkpoint(self):parent.write(self.run,'work/R6_PHYSICAL_LEDGER.json',self.status)
    def reserve(self,kind,node_id,units=1,*,physical_kind=None):
        if kind not in CAPS or type(units) is not int or units<0 or not node_id:raise ValueError('EXACT_PHYSICAL_DEBIT_REQUIRED')
        if any(e['node_id']==node_id for e in self.status['physical_events']):raise ValueError('STARTED_COMPLETED_FAILED_NODE_NO_SCIENTIFIC_RETRY')
        if self.status['actual_counts'][kind]+units>CAPS[kind]:raise ValueError('B_R6_BUDGET_EXHAUSTED_WITH_FROZEN_QUEUE')
        self.status['actual_counts'][kind]+=units
        self.status['physical_events'].append(dict(node_id=node_id,kind=kind,units=units,physical_kind=physical_kind or kind,status='STARTED',started_utc=datetime.now(timezone.utc).isoformat()))
        self.checkpoint() # backend may start only after this fsynced reservation.
    def _terminal(self,node_id,status,details):
        row=next((e for e in self.status['physical_events'] if e['node_id']==node_id),None)
        if row is None or row['status']!='STARTED':raise ValueError('EXACT_STARTED_PHYSICAL_NODE_REQUIRED')
        row.update(status=status,finished_utc=datetime.now(timezone.utc).isoformat(),details=details);self.checkpoint()
    def complete(self,node_id,**details):self._terminal(node_id,'COMPLETE',details)
    def fail(self,node_id,**details):self._terminal(node_id,'FAILED_NONREFUNDABLE',details)
    def deterministic(self,kind,units=1):
        if type(units) is not int or units<0:raise ValueError('DETERMINISTIC_COUNT_REQUIRED')
        d=self.status['deterministic_counters'];d[kind]=d.get(kind,0)+units;self.checkpoint()
