"""Noninstalled engineering candidate for the original C recovery owner.

These controls contain no policy, learner, risk or account implementation.
The canonical entry must verify SOURCE/cold/phase/ROOTLAST/resource/lock gates
before calling the transaction. This candidate grants no runtime admission.
"""
from contextlib import contextmanager
from types import CodeType
from collections import Counter
import hashlib
import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import inspect
import ast
import json
from pathlib import Path
import sys
from datetime import datetime

JOINT_NAME = 'scripts.research.a2.data.joint_input_binding'
JOINT_LOGICAL = Path('D:/us-tech-quant/scripts/research/a2/data/joint_input_binding.py')
JOINT_SHA = '786920c920f8c717f711e01a884f8749c7ae1b121ba7d30fd814f92b706ee6db'
JOINT_SNAPSHOT = Path('D:/us-tech-quant-cache/V24/C_SELECTOR/FULL_SELECTOR_FIXED_POLICY_FAST_R1/proposals/frozen_dependency_capsule_r1/joint_input_binding.' + JOINT_SHA + '.py')
JOINT_CONSUMERS = ('scripts.research.a2.data.full_selector_inputs',
                   'scripts.research.a2.data.full_selector_account_inputs',
                   'scripts.research.a2.training.selector_full_fixed_policy',
                   'scripts.research.a2.training.full_selector_workflow')
RESTORE_ACTION = 'ENGINEERING_ZERO_ENTRY_RESTORED'
SOURCE_GUARD_ERROR = 'EXECUTABLE_SOURCE_CHANGED:D:\\us-tech-quant\\scripts\\research\\a2\\data\\joint_input_binding.py'
_JOINT_ACTIVE = None
ALLOCATION_NAME = 'scripts.research.a2.portfolio.joint_allocation_methods'
ALLOCATION_LOGICAL = Path('D:/us-tech-quant')/'scripts/research/a2/portfolio/joint_allocation_methods.py'
ALLOCATION_SHA = 'd2869e7f837b4e4a58fa5a08d773a35ef6a3edd64530224e2435a75fbdb54917'
ALLOCATION_SNAPSHOT = Path('D:/us-tech-quant-cache/V24/C_SELECTOR/FULL_SELECTOR_FIXED_POLICY_FAST_R1/proposals/frozen_dependency_capsule_r1/joint_allocation_methods.'+ALLOCATION_SHA+'.py')
_ALLOCATION_ACTIVE = None
_ALLOCATION_SCOPE = None
ALLOCATION_CONSUMERS = ('scripts.research.a2.portfolio.shared_joint_adapter_r2','scripts.research.a2.inference.consensus_joint_policy',
    'scripts.research.a2.factors.selector_constrained_membership','scripts.research.a2.evaluation.consensus_method_extension',
    'scripts.research.a2.evaluation.joint_continuation','scripts.research.a2.inference.reused_feasible_policy',
    'scripts.research.a2.inference.joint_shr_anchor_policy_r4','scripts.research.a2.inference.joint_method_space_optimizer_r6',
    'scripts.research.a2.inference.joint_frozen_history_policy_r3','scripts.research.a2.evaluation.joint_method_accounts')
RUN = Path('D:/us-tech-quant-backtests/V24/20261010T151740+0000_642c1248')
REPO = Path('D:/us-tech-quant')
ID = 'V24_C_FULL_SELECTOR_FIXED_POLICY_FAST_R1'
SOURCE_SCHEMA = 'FULL_SELECTOR_POLICY_ZERO_ENTRY_EXACT_JOINT_ALLOCATION_SOURCE_R2'
SOURCE_NAME = 'ENGINEERING_POLICY_CHECKPOINT_EXACT_JOINT_ALLOCATION_SOURCE_R5.json'
CONTROL_PATH = REPO/'scripts/research/a2/training/full_selector_source_guard_recovery.py'
PRIOR_SOURCE_SHA = '3a2e25b7373f4e323bffcb21a9dee2196fde1eff070aa247090430773e6c9eef'
BOUNDARY_SHA = 'fa6d241f9063c144824cc480b0b451c5d56e7c001bbed23eed58b15d179afe9b'
EXPORT_REUSE_SHA = '03b18009b7774aebcc18db56c6b0a4700ef9be5e2e91b461a6e8d987ed38dbd1'
ACTUAL_PRESTATE = dict(nodes_sha256='420ca7b2898d21856997732f9a49b78c075de3078a9a47bed4395eaab80c5a99',
                      events_sha256='e0f86e396ba8f10a6cbec9b782c15df8f622e0601448ce6360ee8068794af6b2',
                      event_count=39961, ids_sha256='8f9f51bc3f9096bb450718855141a8ff206b0b821e6830d43f69d42fc598ed94',
                      target_count=3394, kind_counts={'MEMBER_SOLVE':1478, 'WHOLE_SET_GATE':1916}, error=SOURCE_GUARD_ERROR)
SOURCE_FIELDS = {'schema','status','research_id','design_ref','original_sources',
                 'prior_source_configuration_ref','prior_runtime_custody_refs','runtime_source_refs',
                 'joint_snapshot_ref','joint_live_capture_ref','independent_review_ref','actual_failure_ref','actual_audit_ref',
                 'zero_entry_proof_ref','original_ids_ref','independent_boundary_ref','independent_export_reuse_ref','preinstall_custody_ref','allocation_snapshot_ref',
                 'allocation_live_capture_ref','source_guard_epoch_transition_ref','prior_source_guard_epoch_ref','actual_cold_failure_ref'}
RUNTIME_PATHS = dict(entry=REPO/'scripts/research/a2/training/full_selector_engineering_continuation.py',
                     controller=REPO/'scripts/research/a2/training/selector_full_fixed_policy.py',
                     workflow=REPO/'scripts/research/a2/training/full_selector_workflow.py',
                     recovery_owner=REPO/'scripts/research/a2/training/full_selector_alpha_reboot_recovery.py',
                     source_guard_owner=CONTROL_PATH)


def require(ok, code):
    if not ok:
        raise ValueError(code)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     default=str, allow_nan=False).encode()).hexdigest()


def _physical(value):
    if isinstance(value, bytes):
        value = value.decode(sys.getfilesystemencoding(), errors='surrogateescape')
    if not isinstance(value, (str, Path)) or str(value).startswith('<'):
        return None
    return Path(value).resolve()


def _joint_local_exports(module):
    return {name: value for name, value in vars(module).items()
            if inspect.isfunction(value) and value.__module__ == JOINT_NAME}


def _joint_export_witnesses(module, exports):
    witnesses={}
    for name, value in exports.items():
        globals_used={key:module.__dict__[key] for key in value.__code__.co_names if key in module.__dict__}
        literals={key:digest(item) for key,item in globals_used.items()
                  if isinstance(item,(str,int,float,bool,list,tuple,dict,type(None))) and key!='__builtins__'}
        witnesses[name]=(value.__code__,value.__defaults__,dict(value.__kwdefaults__ or {}),globals_used,literals)
    attributes={}
    for name, attribute in [('Path','open'),('hashlib','file_digest'),('pq','ParquetFile')]:
        if name in module.__dict__:
            attributes[(name,attribute)]=getattr(module.__dict__[name],attribute)
    return witnesses,attributes


def _assert_joint_live_fence():
    try:
        with JOINT_LOGICAL.open('rb'):pass
    except ValueError as exc:require(str(exc)=='JOINT_CANONICAL_SOURCE_OPEN_FORBIDDEN','JOINT_OPEN_FENCE_WRONG_FAILURE')
    else:require(False,'JOINT_OPEN_FENCE_INACTIVE')
    try:compile('pass',str(JOINT_LOGICAL),'exec')
    except ValueError as exc:require(str(exc)=='JOINT_LIVE_COMPILE_FORBIDDEN','JOINT_COMPILE_FENCE_WRONG_FAILURE')
    else:require(False,'JOINT_COMPILE_FENCE_INACTIVE')


def verify_joint_loaded(module, captured_exports, captured_witnesses=None):
    """Recheck the same source/module/export objects at every source gate."""
    logical, snapshot = JOINT_LOGICAL.resolve(), JOINT_SNAPSHOT.resolve()
    parent_name, child = JOINT_NAME.rsplit('.', 1)
    require(sys.modules.get(JOINT_NAME) is module and
            getattr(sys.modules.get(parent_name), child, None) is module,
            'JOINT_MODULE_BINDING_CHANGED')
    require(_physical(module.__file__) == logical and
            _physical(module.__spec__.origin) == snapshot and
            _physical(module.__loader__.path) == snapshot and
            module.__spec__.loader is module.__loader__, 'JOINT_LOADER_ORIGIN_CHANGED')
    actual = _joint_local_exports(module)
    require(actual.keys() == captured_exports.keys() and actual and
            all(actual[k] is v and _physical(v.__code__.co_filename) == snapshot
                for k, v in captured_exports.items()), 'JOINT_EXPORT_OBJECT_CHANGED')
    if captured_witnesses is None:
        require(_JOINT_ACTIVE is not None and _JOINT_ACTIVE[0] is module,'JOINT_IMMUTABLE_EXPORT_WITNESS_REQUIRED')
        captured_witnesses=_JOINT_ACTIVE[2]
    witnesses,attributes=captured_witnesses
    for name,(code,defaults,kwdefaults,globals_used,literals) in witnesses.items():
        value=actual[name]
        require(value.__code__ is code and value.__defaults__ is defaults and
                (value.__kwdefaults__ or {})==kwdefaults,'JOINT_CODE_OR_DEFAULTS_CHANGED')
        require(all(module.__dict__.get(k) is v for k,v in globals_used.items()) and
                all(digest(module.__dict__[k])==v for k,v in literals.items()),'JOINT_FUNCTION_GLOBAL_FRAME_CHANGED')
    require(all(getattr(module.__dict__[name],attribute) is value for (name,attribute),value in attributes.items()),
            'JOINT_REACHABLE_LIBRARY_BINDING_CHANGED')
    with snapshot.open('rb') as handle:
        require(hashlib.file_digest(handle, 'sha256').hexdigest() == JOINT_SHA,
                'JOINT_FROZEN_EXECUTION_BYTES_CHANGED')
    for name in JOINT_CONSUMERS:
        consumer = sys.modules.get(name)
        if consumer is None:
            continue
        for key, value in vars(consumer).items():
            if inspect.isfunction(value) and value.__module__ == JOINT_NAME:
                require(value is captured_exports.get(value.__name__),
                        'JOINT_CONSUMER_FUNCTION_ALIAS_CHANGED:' + name + ':' + key)
            if getattr(value, '__name__', None) == JOINT_NAME and not inspect.isfunction(value):
                require(value is module, 'JOINT_CONSUMER_MODULE_ALIAS_CHANGED:' + name)
    return dict(logical_path=str(logical), expected_sha256=JOINT_SHA,
                actual_snapshot_path=str(snapshot), actual_sha256=JOINT_SHA,
                same_module_and_export_objects=True, local_function_count=len(actual))


@contextmanager
def _frozen_joint_scope_only():
    """Closed one-source transport; never labels this executable as nonexecuted."""
    global _JOINT_ACTIVE
    require(_JOINT_ACTIVE is None, 'ONLY_ONE_JOINT_TRANSPORT_SCOPE')
    logical, snapshot = JOINT_LOGICAL.resolve(), JOINT_SNAPSHOT.resolve()
    require(logical != snapshot and not any(name in sys.modules for name in
            (JOINT_NAME, *JOINT_CONSUMERS)), 'PRISTINE_JOINT_CONSUMERS_REQUIRED')
    for name, module in tuple(sys.modules.items()):
        if module is None:
            continue
        origins = [_physical(getattr(module, '__file__', None)),
                   _physical(getattr(getattr(module, '__spec__', None), 'origin', None))]
        origins.extend(_physical(v.__code__.co_filename) for v in vars(module).values()
                       if inspect.isfunction(v))
        require(not any(p in {logical, snapshot} for p in origins),
                'CACHED_JOINT_SOURCE_ALIAS_FORBIDDEN:' + name)
    with snapshot.open('rb') as handle:
        payload = handle.read()
    require(hashlib.sha256(payload).hexdigest() == JOINT_SHA, 'JOINT_CAPSULE_SHA_CHANGED')
    active = {'value': True}
    def audit(event, args):
        if not active['value']:
            return
        if event == 'open' and args and _physical(args[0]) == logical:
            raise ValueError('JOINT_CANONICAL_SOURCE_OPEN_FORBIDDEN')
        if event == 'import' and args and args[0] == JOINT_NAME and JOINT_NAME not in sys.modules:
            raise ValueError('JOINT_LIVE_IMPORT_FORBIDDEN')
        if event == 'compile' and len(args) > 1:
            origin = _physical(args[1]); body = args[0]
            body = body.encode('utf-8') if isinstance(body, str) else body
            actual = hashlib.sha256(body).hexdigest() if isinstance(body, (bytes, bytearray)) else None
            require(origin != logical, 'JOINT_LIVE_COMPILE_FORBIDDEN')
            if origin == snapshot:
                require(actual == JOINT_SHA, 'JOINT_COMPILE_BYTES_CHANGED')
            if actual == JOINT_SHA:
                require(origin == snapshot, 'JOINT_COMPILE_FILENAME_CHANGED')
        if event == 'exec' and args:
            require(_physical(getattr(args[0], 'co_filename', None)) != logical,
                    'JOINT_LIVE_EXEC_FORBIDDEN')
    parent_name, child = JOINT_NAME.rsplit('.', 1)
    parent = importlib.import_module(parent_name)
    missing = object(); previous = getattr(parent, child, missing)
    require(previous is missing, 'STALE_JOINT_PACKAGE_EXPORT')
    sys.addaudithook(audit)
    try:
        loader = importlib.machinery.SourceFileLoader(JOINT_NAME, str(snapshot))
        spec = importlib.util.spec_from_loader(JOINT_NAME, loader)
        module = importlib.util.module_from_spec(spec)
        module.__file__ = str(logical)
        sys.modules[JOINT_NAME] = module; setattr(parent, child, module)
        exec(compile(payload, str(snapshot), 'exec'), module.__dict__)
        captured = _joint_local_exports(module)
        witnesses = _joint_export_witnesses(module,captured)
        _JOINT_ACTIVE = (module, captured, witnesses)
        verify_joint_loaded(module, captured)
        _assert_joint_live_fence()
        yield module, captured
        verify_joint_loaded(module, captured)
    finally:
        _JOINT_ACTIVE = None
        sys.modules.pop(JOINT_NAME, None)
        if previous is missing:
            if hasattr(parent, child):
                delattr(parent, child)
        else:
            setattr(parent, child, previous)
        active['value'] = False



def _allocation_exports(module):
    exports={name:value for name,value in vars(module).items()
             if inspect.isfunction(value) and value.__module__==ALLOCATION_NAME}
    for name,cls in vars(module).items():
        if inspect.isclass(cls) and cls.__module__==ALLOCATION_NAME:
            for method,value in vars(cls).items():
                if isinstance(value,(staticmethod,classmethod)):value=value.__func__
                if inspect.isfunction(value):exports[name+'.'+method]=value
    return exports


def _allocation_callable_witnesses(exports):
    """Seal generated wrappers and their closed-over original functions too."""
    result={};pending=list(exports.values())
    while pending:
        value=pending.pop()
        if value in result:continue
        space=value.__globals__;used={k:space[k] for k in value.__code__.co_names if k in space}
        literals={k:digest(v) for k,v in used.items() if isinstance(v,(str,int,float,bool,list,tuple,dict,set,type(None))) and k!='__builtins__'}
        closure=[]
        for cell in value.__closure__ or ():
            try:content=cell.cell_contents
            except ValueError:require(False,'ALLOCATION_EMPTY_CLOSURE_NOT_ADMITTED')
            literal=digest(content) if isinstance(content,(str,int,float,bool,list,tuple,dict,set,type(None))) else None
            closure.append((cell,content,literal))
            if inspect.isfunction(content):pending.append(content)
        result[value]=(value.__code__,value.__defaults__,dict(value.__kwdefaults__ or {}),space,used,literals,tuple(closure))
    return result


def _allocation_library_roots(module):
    # Read raw descriptors: normal access may create a fresh wrapper every time.
    roots={}
    for root in ('np','np.linalg','hashlib','ast','Path'):
        parts=root.split('.');owner=module.__dict__.get(parts[0])
        for part in parts[1:]:
            owner=inspect.getattr_static(owner,part,None) if owner is not None else None
        if owner is not None:roots[root]=owner
    return roots


def _allocation_libraries(module,exports):
    names=set()
    def visit(code):
        names.update(code.co_names)
        for item in code.co_consts:
            if isinstance(item,CodeType):visit(item)
    for value in exports.values():visit(value.__code__)
    roots=_allocation_library_roots(module);bindings={}
    for root,owner in roots.items():
        for name in names:
            try:value=inspect.getattr_static(owner,name)
            except AttributeError:continue
            bindings[(root,name)]=(owner,value)
    return roots,bindings



def _assert_allocation_live_fence():
    try:
        with ALLOCATION_LOGICAL.open('rb'):pass
    except ValueError as exc:require(str(exc)=='ALLOCATION_CANONICAL_SOURCE_OPEN_FORBIDDEN','ALLOCATION_OPEN_FENCE_WRONG_FAILURE')
    else:require(False,'ALLOCATION_OPEN_FENCE_INACTIVE')
    try:compile('pass',str(ALLOCATION_LOGICAL),'exec')
    except ValueError as exc:require(str(exc)=='ALLOCATION_LIVE_COMPILE_FORBIDDEN','ALLOCATION_COMPILE_FENCE_WRONG_FAILURE')
    else:require(False,'ALLOCATION_COMPILE_FENCE_INACTIVE')


def active_allocation_observation():
    require(_ALLOCATION_SCOPE is not None,'EXACT_ALLOCATION_EXECUTION_SCOPE_REQUIRED')
    require(_ALLOCATION_SCOPE['finder'] in sys.meta_path,'ALLOCATION_IMPORT_FINDER_CHANGED')
    if _ALLOCATION_ACTIVE is None:importlib.import_module(ALLOCATION_NAME)
    require(_ALLOCATION_ACTIVE is not None,'EXACT_ALLOCATION_PRIVATE_LOADER_REQUIRED')
    module,exports,witnesses,libraries,classes,source_defined=_ALLOCATION_ACTIVE
    parent,child=ALLOCATION_NAME.rsplit('.',1);logical=ALLOCATION_LOGICAL.resolve();snapshot=ALLOCATION_SNAPSHOT.resolve()
    require(sys.modules.get(ALLOCATION_NAME) is module and getattr(sys.modules.get(parent),child,None) is module,
            'ALLOCATION_MODULE_BINDING_CHANGED')
    require(_physical(module.__file__)==logical and _physical(module.__spec__.origin)==snapshot and
            _physical(module.__loader__.path)==snapshot and module.__spec__.loader is module.__loader__,
            'ALLOCATION_LOADER_ORIGIN_CHANGED')
    actual=_allocation_exports(module)
    require(actual.keys()==exports.keys() and actual and all(actual[k] is v for k,v in exports.items()) and
            source_defined<=set(actual) and all(_physical(actual[k].__code__.co_filename)==snapshot for k in source_defined) and
            all(module.__dict__.get(k) is v for k,v in classes.items()),'ALLOCATION_EXPORT_OBJECT_CHANGED')
    for value,(code,defaults,kwdefaults,space,globals_used,literals,closure) in witnesses.items():
        require(value.__code__ is code and value.__defaults__ is defaults and (value.__kwdefaults__ or {})==kwdefaults,
                'ALLOCATION_CODE_OR_DEFAULTS_CHANGED')
        require(value.__globals__ is space and all(space.get(k) is v for k,v in globals_used.items()) and
                all(digest(space[k])==v for k,v in literals.items()),'ALLOCATION_FUNCTION_GLOBAL_FRAME_CHANGED')
        current=value.__closure__ or ()
        require(len(current)==len(closure) and all(cell is old and cell.cell_contents is content and
                (literal is None or digest(cell.cell_contents)==literal)
                for cell,(old,content,literal) in zip(current,closure)),'ALLOCATION_CLOSURE_CELL_CHANGED')
    roots,bindings=libraries;current_roots=_allocation_library_roots(module)
    require(current_roots.keys()==roots.keys() and all(current_roots[k] is v for k,v in roots.items()),
            'ALLOCATION_LIBRARY_OWNER_CHANGED')
    missing=object()
    require(all(inspect.getattr_static(owner,name,missing) is value for (_,name),(owner,value) in bindings.items()),
            'ALLOCATION_LIBRARY_BINDING_CHANGED')
    pin({'path':str(snapshot),'sha256':ALLOCATION_SHA},snapshot)
    for name in ALLOCATION_CONSUMERS:
        consumer=sys.modules.get(name)
        if consumer is None:continue
        for key,value in tuple(vars(consumer).items()):
            if inspect.isfunction(value) and value.__module__==ALLOCATION_NAME:
                require(any(value is export for export in exports.values()),'ALLOCATION_FUNCTION_ALIAS_CHANGED:'+name+':'+key)
            if inspect.isclass(value) and value.__module__==ALLOCATION_NAME:
                require(value is classes.get(value.__name__),'ALLOCATION_CLASS_ALIAS_CHANGED:'+name+':'+key)
            if getattr(value,'__name__',None)==ALLOCATION_NAME and not inspect.isfunction(value):
                require(value is module,'ALLOCATION_MODULE_ALIAS_CHANGED:'+name+':'+key)
    _assert_allocation_live_fence()
    return dict(logical_path=str(logical),expected_sha256=ALLOCATION_SHA,actual_snapshot_path=str(snapshot),
                actual_sha256=ALLOCATION_SHA,same_module_and_export_objects=True,local_callable_count=len(exports),source_defined_callable_count=len(source_defined))


@contextmanager
def frozen_allocation_scope():
    """Arm before original owners import; load only through their normal imports.

    The source gate may force the exact import after the existing frozen owners
    are active. This avoids importing their dependencies ahead of that owner.
    """
    global _ALLOCATION_ACTIVE,_ALLOCATION_SCOPE
    require(_ALLOCATION_ACTIVE is None and _ALLOCATION_SCOPE is None and ALLOCATION_NAME not in sys.modules,
            'PRISTINE_ALLOCATION_SCOPE_REQUIRED')
    logical=ALLOCATION_LOGICAL.resolve();snapshot=ALLOCATION_SNAPSHOT.resolve()
    require(logical!=snapshot,'SEPARATE_ALLOCATION_EXECUTION_CAPSULE_REQUIRED')
    for name,module in tuple(sys.modules.items()):
        if module is None:continue
        origins=[_physical(getattr(module,'__file__',None)),_physical(getattr(getattr(module,'__spec__',None),'origin',None))]
        origins.extend(_physical(v.__code__.co_filename) for v in vars(module).values() if inspect.isfunction(v))
        require(not any(q in {logical,snapshot} for q in origins),'CACHED_ALLOCATION_SOURCE_ALIAS_FORBIDDEN:'+name)
    payload=pin({'path':str(snapshot),'sha256':ALLOCATION_SHA},snapshot).read_bytes()
    parent_name,child=ALLOCATION_NAME.rsplit('.',1);parent=importlib.import_module(parent_name)
    missing=object();previous=getattr(parent,child,missing);require(previous is missing,'STALE_ALLOCATION_PACKAGE_EXPORT')
    class Loader(importlib.machinery.SourceFileLoader):
        def exec_module(self,module):
            global _ALLOCATION_ACTIVE
            require(_ALLOCATION_SCOPE is not None and _ALLOCATION_ACTIVE is None,'ONE_EXACT_ALLOCATION_MODULE_EXECUTION')
            pin({'path':str(snapshot),'sha256':ALLOCATION_SHA},snapshot)
            module.__file__=str(logical)
            exec(compile(payload,str(snapshot),'exec'),module.__dict__)
            exports=_allocation_exports(module);witnesses=_allocation_callable_witnesses(exports)
            classes={k:v for k,v in vars(module).items() if inspect.isclass(v) and v.__module__==ALLOCATION_NAME}
            source_defined=set()
            for node in ast.parse(payload,filename=str(snapshot)).body:
                if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):source_defined.add(node.name)
                elif isinstance(node,ast.ClassDef):
                    source_defined.update(node.name+'.'+z.name for z in node.body if isinstance(z,(ast.FunctionDef,ast.AsyncFunctionDef)))
            _ALLOCATION_ACTIVE=(module,exports,witnesses,_allocation_libraries(module,exports),classes,source_defined)
    class Finder(importlib.abc.MetaPathFinder):
        def find_spec(self,fullname,path=None,target=None):
            if fullname==ALLOCATION_NAME:
                require(target is None,'ALLOCATION_RELOAD_FORBIDDEN')
                return importlib.util.spec_from_loader(fullname,Loader(fullname,str(snapshot)))
            return None
    finder=Finder();active={'value':True}
    def audit(event,args):
        if not active['value']:return
        if event=='open' and args and _physical(args[0])==logical:raise ValueError('ALLOCATION_CANONICAL_SOURCE_OPEN_FORBIDDEN')
        if event=='import' and args and args[0]==ALLOCATION_NAME:
            require(finder in sys.meta_path,'ALLOCATION_LIVE_IMPORT_FORBIDDEN')
        if event=='compile' and len(args)>1:
            origin=_physical(args[1]);body=args[0];body=body.encode() if isinstance(body,str) else body
            actual=hashlib.sha256(body).hexdigest() if isinstance(body,(bytes,bytearray)) else None
            require(origin!=logical,'ALLOCATION_LIVE_COMPILE_FORBIDDEN')
            if origin==snapshot:require(actual==ALLOCATION_SHA,'ALLOCATION_COMPILE_BYTES_CHANGED')
            if actual==ALLOCATION_SHA:require(origin==snapshot,'ALLOCATION_COMPILE_FILENAME_CHANGED')
        if event=='exec' and args:require(_physical(getattr(args[0],'co_filename',None))!=logical,'ALLOCATION_LIVE_EXEC_FORBIDDEN')
    try:
        _ALLOCATION_SCOPE={'finder':finder};sys.meta_path.insert(0,finder)
        sys.addaudithook(audit)
        yield
        active_allocation_observation()
    finally:
        _ALLOCATION_ACTIVE=None;_ALLOCATION_SCOPE=None;sys.modules.pop(ALLOCATION_NAME,None)
        if finder in sys.meta_path:sys.meta_path.remove(finder)
        if previous is missing:
            if hasattr(parent,child):delattr(parent,child)
        else:setattr(parent,child,previous)
        active['value']=False


@contextmanager
def frozen_joint_scope():
    """Two exact frozen executables; old joint transport body stays unchanged."""
    with _frozen_joint_scope_only() as joint:
        with frozen_allocation_scope():yield joint


def active_joint_observation():
    require(_JOINT_ACTIVE is not None, 'EXACT_JOINT_EXECUTION_SCOPE_REQUIRED')
    result=verify_joint_loaded(*_JOINT_ACTIVE)
    result['allocation_source']=active_allocation_observation()
    return result


def pin(value, expected_path=None):
    require(isinstance(value, dict) and set(value)=={'path','sha256'} and
            isinstance(value['sha256'], str) and len(value['sha256'])==64 and
            set(value['sha256'])<=set('0123456789abcdef'), 'CLOSED_SHA256_REF')
    p=Path(value['path']).resolve()
    require(expected_path is None or p==Path(expected_path).resolve(), 'EXACT_PHYSICAL_PATH_REQUIRED')
    with p.open('rb') as h:
        require(hashlib.file_digest(h,'sha256').hexdigest()==value['sha256'], 'PHYSICAL_REFERENCE_CHANGED:'+str(p))
    return p


def read_control(value, expected_path=None, limit=262144):
    p=pin(value,expected_path)
    require(p.stat().st_size<=limit,'BOUNDED_CONTROL_REQUIRED')
    return json.loads(p.read_bytes())


def validate_source_epoch(c, path, data):
    """Original99 current execution plus sealed historical SOURCE; no hash waiver.

    The unchanged six-source/account/capture transport remains its authority.
    Only the new canonical controller/control/entry and executed original joint
    snapshot are admitted by the later independent SOURCE payload review.
    """
    require(Path(__file__).resolve() == CONTROL_PATH.resolve() and Path(path).resolve() == (RUN / SOURCE_NAME).resolve(), 'CANONICAL_POLICY_SOURCE_EPOCH_ONLY')
    require(set(data) == SOURCE_FIELDS and data.get('schema') == SOURCE_SCHEMA and (data.get('status') == 'PASS') and (data.get('research_id') == ID), 'CLOSED_POLICY_SOURCE_EPOCH')
    prior, design_sources = _source_epoch_history_head(data)
    _source_epoch_validate_runtime(data)
    _source_epoch_history_tail(data, prior)
    accounts, captures, controller = _source_epoch_transport_scope(c, data, prior)
    for logical, expected in design_sources.items():
        _source_epoch_original_binding(c, logical, expected, prior, accounts, captures, controller)
    _source_epoch_independent_review(data)
    return data

def _source_epoch_history_head(data):
    require(data['prior_source_configuration_ref']['sha256'] == PRIOR_SOURCE_SHA, 'EXACT_CONSUMED_PRIOR_SOURCE_REQUIRED')
    prior = read_control(data['prior_source_configuration_ref'], RUN / 'ENGINEERING_RISK_NONEXECUTED_SOURCE_REFRESH_R1.json')
    require(prior['status'] == 'PASS' and prior['original_sources'] == data['original_sources'] and (prior['design_ref'] == data['design_ref']), 'UNCHANGED_ORIGINAL_SOURCE_AUTHORITY')
    design_path = pin(data['design_ref'], RUN / 'DESIGN_FREEZE.json')
    require(data['design_ref']['sha256'] == '20a855c2bf4df41b1e84fbc8159a473a04a575ccfb5ba76ed819d1975bcb8359', 'EXACT_ORIGINAL_DESIGN_REQUIRED')
    from scripts.common.json_projection import metadata_fields
    with design_path.open('rb') as h:
        design_sources = metadata_fields(h, {'sources'})['sources']
    require(data['original_sources'] == design_sources and len(design_sources) == 99, 'EXACT_ORIGINAL99_REQUIRED')
    return (prior, design_sources)

def _source_epoch_validate_runtime(data):
    require(set(data['runtime_source_refs']) == set(RUNTIME_PATHS), 'CLOSED_CURRENT_EXECUTION_OWNERS')
    for name, expected_path in RUNTIME_PATHS.items():
        pin(data['runtime_source_refs'][name], expected_path)
    require(data['runtime_source_refs']['workflow']['sha256'] == '3e9764be31de959f5ad04029420c6a771f5d6c96ac7c8301f1656496270aec8f' and data['runtime_source_refs']['recovery_owner']['sha256'] == '6fce70a9a33624f7517155aedfc3fe56d238274c2eac8a2db451508262c353ab', 'ORIGINAL_WORKFLOW_AND_EXISTING_TRANSPORT_UNCHANGED')

def _source_epoch_history_tail(data, prior):
    require(set(data['prior_runtime_custody_refs']) == {'entry', 'controller'}, 'CLOSED_ACTUAL_PRIOR_RUNTIME_CUSTODY')
    require(data['preinstall_custody_ref']['sha256'] == '0952a382fed3b6c228b4af168ff02308fff119426f060b8c32a2828d6b62637b', 'EXACT_ACTUAL_PREINSTALL_CUSTODY')
    preinstall = read_control(data['preinstall_custody_ref'])
    require(data['prior_runtime_custody_refs'] == preinstall['prior_runtime_custody'] and data['joint_live_capture_ref'] == preinstall['joint_live_capture_ref'], 'SOURCE_LINKS_ACTUAL_WHOLE_BYTE_PREINSTALL_CUSTODY')
    for name, expected in [('entry', 'f924af70ae3fc15a632742faff6a008b54da45b95d7e1abe65f516014731eca2'), ('controller', '73c9672498211ac1fbd9b5357a6ff2725f678583dfedea1c97e21642a7800626')]:
        custody = pin(data['prior_runtime_custody_refs'][name])
        require(data['prior_runtime_custody_refs'][name]['sha256'] == expected and custody.is_relative_to((RUN / 'source_corrections/POLICY_ZERO_ENTRY_SOURCE_GUARD_R1').resolve()), 'ACTUAL_PREVIOUS_CONTROL_WHOLE_BYTES_REQUIRED')
    read_control(prior['independent_review_ref'])
    for key, expected_sha in [('actual_failure_ref', 'b572f5e8eb2735fc2e63b57c46b8b7db7c06a7242d2fa99a96293aeabd803ae6'), ('actual_audit_ref', '3c8dc63212be0e04275150fc1cada9ec19f13fba0f31d8bddbd044cb89e11111'), ('zero_entry_proof_ref', '9618e362688f7ddfb41d3495b59dbcf3592b0a30a082892d6fd2a698fb37f9e1'), ('original_ids_ref', '27238085acb2b968e25bea792eaa552147a44d12e9199b8c830c2fb204c16bcb'), ('independent_boundary_ref', BOUNDARY_SHA), ('independent_export_reuse_ref', EXPORT_REUSE_SHA)]:
        require(data[key]['sha256'] == expected_sha, 'EXACT_ACTUAL_ENGINEERING_BOUNDARY:' + key)
        pin(data[key])
    require(data['joint_snapshot_ref'] == {'path': str(JOINT_SNAPSHOT.resolve()), 'sha256': JOINT_SHA}, 'ONLY_ORIGINAL_FROZEN_JOINT_SNAPSHOT')
    pin(data['joint_snapshot_ref'], JOINT_SNAPSHOT)
    capture = read_control(data['joint_live_capture_ref'])
    require(set(capture) == {'schema', 'logical_observation_ref', 'immutable_custody_ref', 'captured_at_utc', 'exact_at_capture', 'current_after_capture_unknown'} and capture['schema'] == 'FULL_SELECTOR_POLICY_JOINT_LIVE_NONEXECUTED_CAPTURE_R1' and (Path(capture['logical_observation_ref']['path']).resolve() == JOINT_LOGICAL.resolve()) and (capture['logical_observation_ref']['sha256'] == capture['immutable_custody_ref']['sha256']) and (capture['exact_at_capture'] is True) and (capture['current_after_capture_unknown'] is True), 'EXPLICIT_CURRENT_AS_CAPTURED_JOINT_CUSTODY_ONLY')
    live_custody = pin(capture['immutable_custody_ref'])
    require(live_custody != JOINT_LOGICAL.resolve() and live_custody.is_relative_to((RUN / 'source_corrections/POLICY_ZERO_ENTRY_SOURCE_GUARD_R1').resolve()), 'SEPARATE_CURRENT_NONEXECUTED_SOURCE_CUSTODY')
    require(data['allocation_snapshot_ref'] == {'path': str(ALLOCATION_SNAPSHOT.resolve()), 'sha256': ALLOCATION_SHA}, 'ONLY_ORIGINAL_FROZEN_ALLOCATION_SNAPSHOT')
    pin(data['allocation_snapshot_ref'], ALLOCATION_SNAPSHOT)
    prior_epoch = read_control(data['prior_source_guard_epoch_ref'], RUN / 'ENGINEERING_POLICY_ZERO_ENTRY_EXACT_JOINT_SOURCE_R1.json')
    require(data['prior_source_guard_epoch_ref']['sha256'] == '12fab2976afcfff4ce1f2ff91b1ee491ca1c7a1f6b9a2b778c06cf7b0d1c220b' and prior_epoch['original_sources'] == data['original_sources'], 'ACTUAL_FAILED_SOURCE_EPOCH_HISTORY_REQUIRED')
    failure = read_control(data['actual_cold_failure_ref'], RUN / 'maintenance/POLICY_ZERO_ENTRY_ACTUAL_COLD_FAILURE_ROOT_RECEIPT_R1.json')
    require(data['actual_cold_failure_ref']['sha256'] == '4a0d7692739b080f4c3bdd7eadcdf73351ec8c79b083632b7b142d4956645b74' and failure['status'] == 'ACTUAL_NATURAL_ENGINEERING_COLD_FAILURE_COLLECTED_ONCE' and (failure['native_exit_code'] == 1) and (failure['collection_count'] == 1), 'ACTUAL_COLD_FAILURE_RETAINED_NOT_SCIENTIFIC_RETRY')
    transition = read_control(data['source_guard_epoch_transition_ref'])
    require(transition['schema'] == 'FULL_SELECTOR_POLICY_ALLOCATION_EXACT_SOURCE_EPOCH_TRANSITION_R2' and transition['prior_source_epoch_ref'] == data['prior_source_guard_epoch_ref'] and (transition['actual_cold_failure_ref'] == data['actual_cold_failure_ref']) and (transition['allocation_live_capture_ref'] == data['allocation_live_capture_ref']) and (set(transition['prior_runtime_whole_custody_refs']) == {'entry', 'controller', 'source_guard_owner'}), 'CLOSED_ACTUAL_SOURCE_EPOCH_TRANSITION')
    for key, value in transition['prior_runtime_whole_custody_refs'].items():
        require(value['sha256'] == prior_epoch['runtime_source_refs'][key]['sha256'], 'ACTUAL_R3_BEFORE_RUNTIME_WHOLE_BYTES')
        q = pin(value)
        require(q.is_relative_to((RUN / 'source_corrections/POLICY_ZERO_ENTRY_ALLOCATION_SOURCE_GUARD_R1').resolve()), 'ALLOCATION_EPOCH_CUSTODY_ROOT')
    descriptor = transition.get('descriptor_recovery')
    require(isinstance(descriptor, dict) and set(descriptor) == {'schema', 'prior_source_epoch_ref', 'prior_installation_ref', 'prior_transition_ref', 'actual_cold_failure_ref', 'prior_runtime_whole_custody_refs', 'actual_exception_code', 'scientific_admission', 'original3394_restored'} and (descriptor['schema'] == 'FULL_SELECTOR_POLICY_ALLOCATION_DESCRIPTOR_RECOVERY_R3') and (descriptor['actual_exception_code'] == 'ALLOCATION_LIBRARY_BINDING_CHANGED') and (descriptor['scientific_admission'] is False) and (descriptor['original3394_restored'] is False), 'CLOSED_ACTUAL_DESCRIPTOR_RECOVERY_HISTORY')
    require(descriptor['prior_source_epoch_ref']['sha256'] == 'eb6946ba2e0edc4ccd204833017a092eceffdf37172821589acf13159536e9e3' and descriptor['prior_installation_ref']['sha256'] == '700e26519b492884261a1f13eb828fae13e7e7c52ceb46ca616fa62e5c3d0981' and (descriptor['prior_transition_ref']['sha256'] == 'f3c75614b502d4f2ebdbbd5d5d55bd94a8ff17c29290064d062594419429be72') and (descriptor['actual_cold_failure_ref']['sha256'] == '1cc054fa5ae78aaf37f72f7c87faa1ebea7bac68d0fb4cb07b4279d4325756b3'), 'EXACT_ACTUAL_R2_FAILED_COLD_HISTORY')
    descriptor_source = read_control(descriptor['prior_source_epoch_ref'], RUN / 'ENGINEERING_POLICY_ZERO_ENTRY_EXACT_JOINT_ALLOCATION_SOURCE_R2.json')
    read_control(descriptor['prior_installation_ref'], RUN / 'maintenance/POLICY_ZERO_ENTRY_ACTUAL_SOURCE_INSTALLATION_R2.json')
    read_control(descriptor['prior_transition_ref'])
    descriptor_failure = read_control(descriptor['actual_cold_failure_ref'], RUN / 'maintenance/POLICY_ZERO_ENTRY_ACTUAL_COLD_FAILURE_ROOT_RECEIPT_R2.json')
    require(descriptor_failure['native_exit_code'] == 1 and descriptor_failure['collection_count'] == 1 and (descriptor_failure['session_id'] == 44363) and (descriptor_failure['original3394_restored'] is False), 'ACTUAL_R2_FAILURE_CLOSED_ONCE_NO_RESTORE')
    require(set(descriptor['prior_runtime_whole_custody_refs']) == {'entry', 'controller', 'source_guard_owner'}, 'CLOSED_ACTUAL_DESCRIPTOR_PRIOR_CODE_CUSTODY')
    for name, value in descriptor['prior_runtime_whole_custody_refs'].items():
        require(value['sha256'] == descriptor_source['runtime_source_refs'][name]['sha256'], 'ACTUAL_R2_RUNTIME_WHOLE_BYTES')
        q = pin(value)
        require(q.is_relative_to((RUN / 'source_corrections/POLICY_ZERO_ENTRY_DESCRIPTOR_GUARD_R3').resolve()), 'DESCRIPTOR_EPOCH_CUSTODY_ROOT')
    native_history = transition.get('native_wait_recovery')
    require(isinstance(native_history, dict) and set(native_history) == {'schema', 'prior_source_epoch_ref', 'prior_installation_ref', 'actual_native_unknown_boundary_ref', 'prior_runtime_whole_custody_refs'} and (native_history['schema'] == 'FULL_SELECTOR_POLICY_ZERO_ENTRY_NATIVE_WAIT_RECOVERY_R4'), 'CLOSED_ACTUAL_NATIVE_WAIT_RECOVERY_HISTORY')
    require(native_history['prior_source_epoch_ref']['sha256'] == 'c74a8e1085aee7e545433bc09e82907ca6c80e9b9dad250d02329a85c71afc42' and native_history['prior_installation_ref']['sha256'] == 'd5d008cb1a68c63f3e8545d315c03891d01488afb66f37b1efafd2c7f9751d3b' and (native_history['actual_native_unknown_boundary_ref']['sha256'] == 'abbc42622dbbd9040f3478166eeea45f99e9c4e72efb1af68f9fd517e6090d2d'), 'EXACT_ACTUAL_R3_NATIVE_UNKNOWN_HISTORY')
    native_source = read_control(native_history['prior_source_epoch_ref'], RUN / 'ENGINEERING_POLICY_ZERO_ENTRY_EXACT_JOINT_ALLOCATION_SOURCE_R3.json')
    read_control(native_history['prior_installation_ref'], RUN / 'maintenance/POLICY_ZERO_ENTRY_ACTUAL_SOURCE_INSTALLATION_R3.json')
    native_boundary = read_control(native_history['actual_native_unknown_boundary_ref'], RUN / 'maintenance/POLICY_ZERO_ENTRY_COLD_R3_STARTUP_IDENTITY_RACE_BOUNDARY_R1.json')
    require(native_boundary['status'] == 'ACTUAL_METADATA_COLD_PASS_NATIVE_LIFECYCLE_UNKNOWN_NOT_ADMITTED' and native_boundary['native_exit_code'] is None and (native_boundary['native_Wait_observed'] is False) and (native_boundary['collection_count'] == 0) and (native_boundary['scientific_admission'] is False) and (native_boundary['original3394_restored'] is False), 'R3_NATIVE_UNKNOWN_CANNOT_BECOME_ADMISSION')
    require(set(native_history['prior_runtime_whole_custody_refs']) == {'entry', 'controller', 'source_guard_owner'}, 'CLOSED_R3_NATIVE_UNKNOWN_PRIOR_CODE_CUSTODY')
    for name, value in native_history['prior_runtime_whole_custody_refs'].items():
        require(value['sha256'] == native_source['runtime_source_refs'][name]['sha256'], 'ACTUAL_R3_BEFORE_NATIVE_WAIT_REPAIR')
        q = pin(value)
        require(q.is_relative_to((RUN / 'source_corrections/POLICY_ZERO_ENTRY_NATIVE_WAIT_GUARD_R4').resolve()), 'NATIVE_WAIT_EPOCH_CUSTODY_ROOT')
    validate_checkpoint_epoch_history(data)
    allocation_capture = read_control(data['allocation_live_capture_ref'])
    require(set(allocation_capture) == {'schema', 'logical_observation_ref', 'immutable_custody_ref', 'captured_at_utc', 'exact_at_capture', 'current_after_capture_unknown'} and allocation_capture['schema'] == 'FULL_SELECTOR_POLICY_ALLOCATION_LIVE_NONEXECUTED_CAPTURE_R2' and (Path(allocation_capture['logical_observation_ref']['path']).resolve() == ALLOCATION_LOGICAL.resolve()) and (allocation_capture['logical_observation_ref']['sha256'] == allocation_capture['immutable_custody_ref']['sha256']) and (allocation_capture['exact_at_capture'] is True) and (allocation_capture['current_after_capture_unknown'] is True), 'EXPLICIT_ALLOCATION_LIVE_NONEXECUTED_CUSTODY')
    q = pin(allocation_capture['immutable_custody_ref'])
    require(q != ALLOCATION_LOGICAL.resolve() and q.is_relative_to((RUN / 'source_corrections/POLICY_ZERO_ENTRY_ALLOCATION_SOURCE_GUARD_R1').resolve()), 'ALLOCATION_LIVE_CAPTURE_CUSTODY_ROOT')

def _source_epoch_transport_scope(c, data, prior):
    active_joint_observation()
    _assert_joint_live_fence()
    transport = read_control(prior['source_transport_ref'])
    c._source_r5_assert_live_fence(prior, transport)
    c._source_r4_loaded_modules(transport)
    accounts = c._frozen_account_loaded_sources(prior)
    require(c._REGISTRY_METADATA_SCOPE is not None and c._REGISTRY_METADATA_SCOPE.get('capture_mode') is True, 'ORIGINAL_NONEXECUTED_CAPTURE_SCOPE_REQUIRED')
    c._registry_metadata_assert_fence()
    captures = c._registry_metadata_fixed_sources()
    controller = str(RUNTIME_PATHS['controller'].resolve())
    require(prior['replacements'][controller]['runtime_ref']['sha256'] == data['prior_runtime_custody_refs']['controller']['sha256'], 'PRIOR_ACTUAL_CONTROLLER_SOURCE_LINK_REQUIRED')
    return (accounts, captures, controller)

def _source_epoch_original_binding(c, logical, expected, prior, accounts, captures, controller):
    resolved = str(Path(logical).resolve())
    if resolved == str(JOINT_LOGICAL.resolve()):
        require(expected == JOINT_SHA, 'ORIGINAL_JOINT_SOURCE_IN99_REQUIRED')
    elif resolved == str(ALLOCATION_LOGICAL.resolve()):
        require(expected == ALLOCATION_SHA, 'ORIGINAL_ALLOCATION_SOURCE_IN99_REQUIRED')
        active_allocation_observation()
    elif logical in prior['replacements']:
        item = prior['replacements'][logical]
        require(item['original_ref'] == dict(path=logical, sha256=expected) and item['custody_ref']['sha256'] == expected, 'ORIGINAL_REPLACEMENT_CUSTODY_REQUIRED')
        pin(item['custody_ref'])
        if resolved != controller:
            pin(item['runtime_ref'])
    elif resolved in accounts:
        require(accounts[resolved]['original_logical_ref'] == dict(path=logical, sha256=expected) and accounts[resolved]['actual_snapshot_ref']['sha256'] == expected, 'ORIGINAL_ACCOUNT_EXECUTION_BYTES')
    elif Path(logical).resolve() in captures:
        require(captures[Path(logical).resolve()][0] == expected, 'ORIGINAL_REGISTERED_CAPTURE_SOURCE')
    else:
        pin(dict(path=logical, sha256=expected))

def _source_epoch_independent_review(data):
    review = read_control(data['independent_review_ref'], RUN / 'maintenance/POLICY_CHECKPOINT_EXACT_JOINT_ALLOCATION_SOURCE_INDEPENDENT_REVIEW_R5.json')
    payload = {key: value for key, value in data.items() if key not in {'status', 'independent_review_ref'}}
    require(review.get('schema') == 'FULL_SELECTOR_POLICY_ZERO_ENTRY_EXACT_JOINT_ALLOCATION_SOURCE_INDEPENDENT_REVIEW_R2' and review.get('status') == 'PASS' and (review.get('research_id') == ID) and (review.get('source_payload_sha256') == digest(payload)) and all((review.get(k) is True for k in ('independent_from_entry_writer', 'independent_from_source_writer', 'original99_authority_preserved', 'existing_six_snapshot_account_capture_transport_preserved', 'original_joint_capsule_execution_required_by_runtime_guard', 'business_math_and_original_once_unchanged', 'actual_current_and_whole_history_source_custody_verified', 'original_allocation_capsule_execution_required_by_runtime_guard', 'actual_cold_R1_failure_preserved_no_science', 'actual_cold_R2_failure_preserved_no_science', 'actual_cold_R3_native_boundary_preserved_no_science', 'actual_R4_science_interruption_checkpoint_preserved_no_retry'))) and (review.get('historical_whole_joint_module_identity') == 'UNKNOWN') and (review.get('reuse_basis') == 'BOUNDED_REACHABLE_EXPORT_EQUIVALENCE'), 'NEW_EXACT_SOURCE_REVIEW_REQUIRED')


@contextmanager
def original_once_scope(c, ids):
    """Entry/event fence around the unchanged original once implementation."""
    allowed=frozenset(ids);owner=c._TaskLedger;old_once=owner.once;old_event=owner.event
    def once(journal,node,identity,work):
        if node not in allowed:
            require(journal.status(node)['status'] in {'COMPLETE','FAILED','SOURCE_NOT_TESTABLE','BLOCKED_DEPENDENCY'},
                    'NON_TARGET_FIRST_ENTRY_FORBIDDEN')
        def guarded(enter):
            require(node in allowed,'NON_TARGET_BACKEND_FORBIDDEN')
            return work(enter)
        return old_once(journal,node,identity,guarded)
    def event(journal,node,action,payload):
        require(node in allowed and action in {'BEGIN','BACKEND_ENTER','COMPLETE','FAILED','BLOCKED_DEPENDENCY'},
                'ONLY_ORIGINAL_TARGET_EVENT_ACTIONS')
        return old_event(journal,node,action,payload)
    owner.once=once;owner.event=event
    try:yield
    finally:owner.once=old_once;owner.event=old_event


COLD_OS_FIELDS={'schema','status','observed_utc','launch_ref','caller_ref','runtime_entry_ref',
                'phase_configuration_ref','source_bindings_ref','installation_ref','before_process_levels',
                'after_process_levels','wait_for_exit_observed','exit_code','exit_utc','terminated_by_agent',
                'stdout_ref','stderr_ref','stdout_bytes','stderr_bytes','actual_output_ref'}
PROCESS_LEVEL_FIELDS={'pid','parent_pid','creation_utc','executable','command'}
THREAD_FIELDS={'OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS',
               'BLIS_NUM_THREADS','VECLIB_MAXIMUM_THREADS','LOKY_MAX_CPU_COUNT'}


def validate_actual_cold_native(osr, cold, review, cfg, root_terminal_ref):
    """Same closed20 cold writer contract plus its actual launch/birth/once chain."""
    return _validate_actual_cold_native_profile(osr, cold, review, cfg, root_terminal_ref, RUN / 'maintenance/POLICY_CHECKPOINT_COLD_ACTUAL_LAUNCH_R5.json', RUN / 'maintenance/POLICY_CHECKPOINT_ACTUAL_SOURCE_INSTALLATION_R5.json', RUN / 'maintenance/POLICY_CHECKPOINT_ACTUAL_COLD_ROOT_TERMINAL_R5.json', 'post-risk-policy-source-guard-checkpoint-cold-r5')

def _validate_actual_cold_native_profile(osr, cold, review, cfg, root_terminal_ref, launch_path, installation_path, terminal_path, phase_name, control_reader=None):
    """Same closed20 cold writer contract plus its actual launch/birth/once chain."""
    if control_reader is None:control_reader=read_control
    require(set(osr) == COLD_OS_FIELDS and osr.get('schema') == 'FIXED214_POLICY_ZERO_ENTRY_SOURCE_COLD_OS_EXIT_R1' and (osr.get('status') == 'ACTUAL_POLICY_ZERO_ENTRY_COLD_NATURAL_OS_EXIT') and (osr.get('wait_for_exit_observed') is True) and (type(osr.get('exit_code')) is int) and (osr['exit_code'] == 0) and (osr.get('terminated_by_agent') is False) and (osr.get('after_process_levels') == []), 'EXACT_CURRENT_COLD_STRICT20_NATIVE_EXIT')
    require(osr['runtime_entry_ref'] == cfg['runtime_entry_ref'] and osr['phase_configuration_ref'] == review['configuration_ref'] and (osr['source_bindings_ref'] == cfg['source_configuration_ref']) and (osr['actual_output_ref'] == review['actual_cold_ref']) and (osr['caller_ref'] == cold['caller_ref']), 'SAME_ACTUAL_COLD_CONFIG_SOURCE_ENTRY_CALLER_OUTPUT')
    for key in ('caller_ref', 'runtime_entry_ref', 'phase_configuration_ref', 'source_bindings_ref'):
        pin(osr[key])
    launch = control_reader(osr['launch_ref'], launch_path)
    require(launch.get('schema') == 'FIXED214_POLICY_ZERO_ENTRY_SOURCE_COLD_ACTUAL_LAUNCH_R1' and launch.get('status') == 'ACTUAL_POLICY_ZERO_ENTRY_SOURCE_COLD_SINGLE_STARTED' and (launch.get('research_id') == ID) and (launch.get('phase') == phase_name), 'CURRENT_ACTUAL_COLD_LAUNCH_IDENTITY')
    for key in ('caller_ref', 'runtime_entry_ref', 'phase_configuration_ref', 'source_bindings_ref', 'installation_ref'):
        require(launch.get(key) == osr[key], 'COLD_LAUNCH_BINDING_CHANGED:' + key)
    installation = control_reader(osr['installation_ref'], installation_path)
    require(installation.get('status') == 'ACTUAL_REVIEWED_SOURCE_INSTALLED_NO_COLD_OR_SCIENCE' and installation.get('runtime_source_refs') == cfg['phase_source_refs'] and (installation.get('actual_ledger_changes') == 0) and (installation.get('scientific_calls') == 0), 'ACTUAL_SOURCE_INSTALLATION_BEFORE_COLD_REQUIRED')
    expected_args = ['-B', osr['caller_ref']['path'], '--output', review['actual_cold_ref']['path']]
    require(launch.get('arguments') == expected_args and launch.get('threads') == 2 and (launch.get('UTF8') is True) and (launch.get('worker_limit') == 1) and (launch.get('task_budget_GiB') == 8) and (launch.get('prestart_minimum_available_GiB') == 1.5) and (launch.get('physical_available_GiB', 0) >= 1.5) and (launch.get('pre_import_thread_environment') == {name: '2' for name in THREAD_FIELDS}), 'ORIGINAL_COLD_ARGS_THREADS_RAM_SINGLE_WORKER')
    before = osr['before_process_levels']
    require(isinstance(before, list) and len(before) == 2 and (before == launch.get('before_process_levels')) and all((isinstance(z, dict) and set(z) == PROCESS_LEVEL_FIELDS and (type(z['pid']) is int) and (z['pid'] > 0) and (type(z['parent_pid']) is int) and (z['parent_pid'] > 0) and isinstance(z['creation_utc'], str) for z in before)), 'EXACT_ACTUAL_COLD_TWO_PROCESS_LEVELS')
    require(before[0]['pid'] == launch.get('launcher_pid') and before[0]['parent_pid'] == launch.get('handle_holder_pid') and (before[1]['parent_pid'] == before[0]['pid']) and (before[0]['pid'] != before[1]['pid']), 'ACTUAL_COLD_LAUNCHER_CHILD_PARENT_CHAIN')
    expected_executables = [Path('D:/us-tech-quant-envs/us-tech-quant-main/Scripts/python.exe').resolve(), Path('C:/Users/Lenovo/AppData/Local/Programs/Python/Python312/python.exe').resolve()]
    for level, executable in zip(before, expected_executables):
        require(Path(level['executable']).resolve() == executable and level['command'] == '"' + level['executable'] + '" ' + ' '.join(expected_args), 'EXACT_COLD_EXECUTABLE_AND_FULL_COMMAND')
        datetime.fromisoformat(level['creation_utc'].replace('Z', '+00:00'))
    require(datetime.fromisoformat(before[0]['creation_utc'].replace('Z', '+00:00')) <= datetime.fromisoformat(before[1]['creation_utc'].replace('Z', '+00:00')), 'COLD_BIRTH_ORDER')
    for stream in ('stdout', 'stderr'):
        value = osr[stream + '_ref']
        path = pin(value)
        require(value['path'] == launch.get(stream + '_path') and type(osr[stream + '_bytes']) is int and (osr[stream + '_bytes'] == path.stat().st_size), 'ACTUAL_OPAQUE_COLD_LOG_REFERENCE')
    terminal = control_reader(root_terminal_ref, terminal_path)
    require(terminal.get('schema') == 'FULL_SELECTOR_POLICY_ZERO_ENTRY_ACTUAL_COLD_ROOT_TERMINAL_R1' and terminal.get('status') == 'ACTUAL_NATURAL_COLD_TERMINAL_COLLECTED_ONCE' and (terminal.get('actual_cold_ref') == review['actual_cold_ref']) and (terminal.get('actual_os_ref') == review['actual_cold_os_ref']) and (terminal.get('actual_launch_ref') == osr['launch_ref']) and (terminal.get('before_process_levels') == before) and (terminal.get('after_process_levels') == []) and (terminal.get('native_process_wait_for_exit_observed') is True) and (type(terminal.get('native_exit_code')) is int) and (terminal['native_exit_code'] == 0) and (terminal.get('terminated_by_agent') is False) and (type(terminal.get('collection_count')) is int) and (terminal['collection_count'] == 1) and (type(terminal.get('session_id')) is int) and bool(terminal.get('collection_tool')), 'ACTUAL_COLD_NATIVE_ONCE_COLLECTION_ROOT_CHAIN')
    observation = control_reader(terminal['process_observation_ref'])
    require(observation.get('status') == 'SUCCESS_AUTHORIZED_EXACT_PID_BIRTH_COMMAND_CIM' and observation.get('expected_original_process_levels') == before and (observation.get('after_process_levels') == []) and bool(observation.get('successful_tool_id')), 'ACTUAL_COLD_ORIGINAL_BIRTHS_GONE_CIM_CHAIN')
    return dict(closed20=True, actual_launch_and_two_births_exact=True, native_exit_code=0, actual_once_collection_root_ref=root_terminal_ref)


def zero_entry_plan(rows, events, ids, expected):
    """Pure finite validation; expected comes from the separately admitted contract."""
    require(set(expected) == {'nodes_sha256', 'events_sha256', 'event_count',
            'ids_sha256', 'target_count', 'kind_counts', 'error'}, 'CLOSED_ZERO_ENTRY_PRESTATE')
    require(len(ids) == len(set(ids)) == expected['target_count'] and
            ids == sorted(ids) and digest(ids) == expected['ids_sha256'], 'EXACT_ORIGINAL_ID_SET')
    require(digest(rows) == expected['nodes_sha256'] and digest(events) == expected['events_sha256']
            and len(events) == expected['event_count'], 'EXACT_WHOLE_LEDGER_PRESTATE')
    targets = set(ids); by_id = {r[0]: r for r in rows if r[0] in targets}
    require(len(by_id) == len(ids), 'ALL_ORIGINAL_TARGETS_EXIST')
    require(dict(Counter(r[1] for r in by_id.values())) == expected['kind_counts'], 'EXACT_TARGET_KINDS')
    history = {node: [] for node in ids}
    for event in events:
        if event[1] in history:
            history[event[1]].append(event)
    result = []
    for node in ids:
        row = by_id[node]
        require(tuple(row[2:6]) == ('BLOCKED_DEPENDENCY', 0, None, None) and
                row[6] == expected['error'], 'ONLY_EXACT_ZERO_ENTRY_SOURCE_GUARD_BLOCKS')
        old = history[node]
        require(len(old) == 1 and old[0][2] == 'BLOCKED_DEPENDENCY' and
                json.loads(old[0][3]) == {'reason': row[6]}, 'ORIGINAL_SINGLE_BLOCK_HISTORY_REQUIRED')
        result.append(dict(node_id=node, kind=row[1], old_row_sha256=digest(row),
                           old_block_sequence=old[0][0], old_block_event_sha256=digest(old[0])))
    return result


def restore_zero_entry_transaction(db, ids, expected, admission_ref, utc):
    """Atomic mechanical transition only; caller already holds the original worker lock.

    No scientific callback, TaskLedger constructor, deletion or budget mutation.
    Repeated calls fail the exact prestate. Old rows are retained by hash and the
    independently sealed whole prestate; original BLOCK events remain untouched.
    """
    require(not db.in_transaction, 'RESTORE_REQUIRES_SEPARATE_TRANSACTION')
    require(set(admission_ref) == {'path', 'sha256'} and len(admission_ref['sha256']) == 64,
            'CLOSED_ACTUAL_PHASE_ADMISSION_REF_REQUIRED')
    db.execute('BEGIN IMMEDIATE')
    try:
        rows = db.execute('SELECT node_id,kind,status,entered,identity,artifact,error FROM nodes ORDER BY node_id').fetchall()
        events = db.execute('SELECT sequence,node_id,action,payload,utc FROM events ORDER BY sequence').fetchall()
        authority = db.execute('SELECT design_sha256 FROM authority ORDER BY design_sha256').fetchall()
        require(len(authority)==1,'SOLE_EXISTING_AUTHORITY_REQUIRED')
        plan = zero_entry_plan(rows, events, ids, expected)
        expected_suffix=[];next_sequence=events[-1][0]+1 if events else 1
        for item in plan:
            require(db.execute("UPDATE nodes SET status='NAMED',error=NULL WHERE node_id=? AND status='BLOCKED_DEPENDENCY' AND entered=0 AND identity IS NULL AND artifact IS NULL AND error=?",
                               (item['node_id'], expected['error'])).rowcount == 1, 'RESTORE_CAS_FAILED')
            record = dict(**item, phase_admission_ref=admission_ref,
                          original_prefix_sha256=expected['events_sha256'],
                          actual_backend_entries=0, budget_charge_delta=0)
            encoded=json.dumps(record,sort_keys=True,separators=(',', ':'),ensure_ascii=False,allow_nan=False)
            db.execute('INSERT INTO events(node_id,action,payload,utc) VALUES (?,?,?,?)',
                       (item['node_id'], RESTORE_ACTION, encoded, utc))
            expected_suffix.append((next_sequence,item['node_id'],RESTORE_ACTION,encoded,utc));next_sequence+=1
        after = db.execute('SELECT node_id,kind,status,entered,identity,artifact,error FROM nodes ORDER BY node_id').fetchall()
        targets = set(ids)
        expected_rows = [(r[0], r[1], 'NAMED', 0, None, None, None) if r[0] in targets else r for r in rows]
        require(after == expected_rows, 'RESTORE_OFF_SCOPE_NODE_CHANGE')
        all_after_events=db.execute('SELECT sequence,node_id,action,payload,utc FROM events ORDER BY sequence').fetchall()
        require(all_after_events[:len(events)]==events,'RESTORE_OLD_PREFIX_CHANGED')
        require(db.execute('SELECT design_sha256 FROM authority ORDER BY design_sha256').fetchall()==authority,
                'RESTORE_SOLE_AUTHORITY_CHANGED')
        suffix=all_after_events[len(events):]
        require(suffix==expected_suffix,'EXACT_FULL_ZERO_CHARGE_ADMIN_SUFFIX_BEFORE_COMMIT')
        db.commit()
        return dict(original_event_count=len(events), restored_original_ids=len(plan),
                    restored_ids_sha256=digest(ids), administrative_event_count=len(suffix),
                    before_nodes_sha256=digest(rows), after_nodes_sha256=digest(after),
                    original_events_sha256=digest(events), actual_backend_entries=0,
                    budget_charge_delta=0, phase_admission_ref=admission_ref,restored_at_utc=utc)
    except BaseException:
        db.rollback()
        raise


def zero_entry_history(before_rows, before_events, after_rows, after_events, ids, expected, admission_ref, restored_at_utc):
    """New explicit seam: old BLOCK -> zero-charge restoration -> original once.

    The original 5af first-NAMED rule remains unchanged and is not represented
    as accepting old BLOCK history. Original callbacks are never implemented here.
    """
    plan = zero_entry_plan(before_rows, before_events, ids, expected)
    require(after_events[:len(before_events)] == before_events, 'ORIGINAL_39961_PREFIX_CHANGED')
    before = {r[0]: r for r in before_rows}
    after = {r[0]: r for r in after_rows}
    require(before.keys() == after.keys(), 'ORIGINAL_NODE_NAMESPACE_CHANGED')
    targets = set(ids)
    require(all((after[k] == before[k] for k in before.keys() - targets)), 'NON_TARGET_ROWS_CHANGED')
    suffix = after_events[len(before_events):]
    require(len(suffix) >= len(ids), 'ALL_ADMIN_EVENTS_REQUIRED')
    start = before_events[-1][0] + 1 if before_events else 1
    require([v[0] for v in suffix] == list(range(start, start + len(suffix))), 'CONTIGUOUS_ORIGINAL_EVENT_SEQUENCE_REQUIRED')
    admin = suffix[:len(ids)]
    for item, event in zip(plan, admin):
        payload = dict(**item, phase_admission_ref=admission_ref, original_prefix_sha256=expected['events_sha256'], actual_backend_entries=0, budget_charge_delta=0)
        require(event[1] == item['node_id'] and event[2] == RESTORE_ACTION and (event[3] == json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)) and (event[4] == restored_at_utc), 'EXACT_AUTHORIZED_ADMIN_RESTORE_REQUIRED')
    chains = {node: [] for node in ids}
    for event in suffix[len(ids):]:
        require(event[1] in targets, 'NON_TARGET_EVENT_FORBIDDEN')
        chains[event[1]].append(event)
    counts = Counter()
    for node, chain in chains.items():
        counts[_source_original_once_row_history(node, chain, before, after)] += 1
    return dict(status='PASS_METADATA_HISTORY_ONLY', counts=dict(counts), original_prefix_preserved=True, non_target_rows_preserved=True, restored_original_ids=len(ids), administrative_charge_delta=0)

def _source_original_once_row_history(node, chain, before, after):
    row = after[node]
    actions = [v[2] for v in chain]
    require(row[1] == before[node][1], 'TARGET_KIND_CHANGED')
    if actions == []:
        require(tuple(row[2:]) == ('NAMED', 0, None, None, None), 'UNENTERED_RESTORED_ROW_CHANGED')
    elif actions == ['BLOCKED_DEPENDENCY']:
        require(tuple(row[2:6]) == ('BLOCKED_DEPENDENCY', 0, None, None) and json.loads(chain[0][3]) == {'reason': row[6]}, 'BLOCK_CHAIN_ROW_CHANGED')
    elif actions in (['BEGIN', 'BACKEND_ENTER', 'COMPLETE'], ['BEGIN', 'BACKEND_ENTER', 'FAILED']):
        require(row[2] == actions[-1] and row[3] == 1 and (row[4] == digest(json.loads(chain[0][3]))), 'ORIGINAL_ONCE_IDENTITY_ENTRY_REQUIRED')
        if actions[-1] == 'COMPLETE':
            artifact = json.loads(row[5])
            terminal = json.loads(chain[-1][3])
            require(isinstance(artifact, dict) and set(artifact) == {'path', 'sha256'} and isinstance(artifact['path'], str) and bool(artifact['path']) and isinstance(artifact['sha256'], str) and (len(artifact['sha256']) == 64) and (set(artifact['sha256']) <= set('0123456789abcdef')) and (row[6] is None) and (artifact == terminal), 'ORIGINAL_COMPLETE_ARTIFACT_METADATA_REQUIRED')
        else:
            require(row[5] is None and bool(row[6]) and (json.loads(chain[-1][3]).get('entered') == 1), 'ORIGINAL_FAILED_HISTORY_REQUIRED')
    else:
        raise ValueError('ONLY_SINGLE_ORIGINAL_ONCE_OR_BLOCK_CHAIN')
    return row[2]


"""Root-authored additive controls; proposal only, no I/O at import or science."""

def validate_checkpoint_epoch_history(data):
    """Seal the actual interrupted R4 source and accepted partial checkpoint."""
    transition=read_control(data['source_guard_epoch_transition_ref'])
    item=transition.get('checkpoint_recovery')
    fields={'schema','prior_source_epoch_ref','prior_installation_ref','actual_disappearance_boundary_ref',
            'actual_finite_audit_ref','actual_partial_checkpoint_ref','pristine_original_ids_ref',
            'independent_checkpoint_acceptance_ref','prior_runtime_whole_custody_refs',
            'publication_checkpoint_custody_ref'}
    require(isinstance(item,dict) and set(item)==fields and
            item['schema']=='FULL_SELECTOR_POLICY_R4_INTERRUPTION_CHECKPOINT_RECOVERY_R5',
            'CLOSED_ACTUAL_R4_CHECKPOINT_SOURCE_HISTORY')
    exact={
        'prior_source_epoch_ref':('ENGINEERING_POLICY_ZERO_ENTRY_EXACT_JOINT_ALLOCATION_SOURCE_R4.json','d0e84ebac9847a6ec988bed9fbb29dfa4bd05e459fc82c84cc1b9761b49212bb'),
        'prior_installation_ref':('maintenance/POLICY_ZERO_ENTRY_ACTUAL_SOURCE_INSTALLATION_R4.json','9226a8bbe2e9196ff384bc6459b4d1fadab4edafde560aeda958fdb0ebb35bb9'),
        'actual_disappearance_boundary_ref':('maintenance/POLICY_ZERO_ENTRY_R4_ACTUAL_PROCESS_DISAPPEARANCE_BOUNDARY_R1.json','bfbf7fd3dba507654daf3342a0615a11ddf72455d3cb51b6705d87a5a96be7ed')}
    for key,(name,expected) in exact.items():
        require(item[key]['sha256']==expected,'EXACT_R4_HISTORY:'+key)
        read_control(item[key],RUN/name)
    expected={
        'actual_finite_audit_ref':'f05467c5e432b96d9562ae954b1d631d753ef67aff1864f140d108d052e69447',
        'actual_partial_checkpoint_ref':'eb371c870b747bcb620be68410b2438b46fb189c07382a1b2f595ea3b2f74fe5',
        'pristine_original_ids_ref':'d3fbf9ef8b9a7cf3340e5b1e42cf26fbd611ce48ed459eccf2bea70a0fe4fb7b',
        'independent_checkpoint_acceptance_ref':'cf92bb916a8abd555a702c610785da4353a8c3bd289305a02f33369701d976b8'}
    for key,expected_sha in expected.items():
        require(item[key]['sha256']==expected_sha,'EXACT_ACCEPTED_PARTIAL_CHECKPOINT:'+key)
        pin(item[key])
    cp=read_control(item['actual_partial_checkpoint_ref'])
    review=read_control(item['independent_checkpoint_acceptance_ref'])
    require(cp['native_exit_code'] is None and cp['native_wait_completion_observed'] is False and
            cp['session48898_collected'] is False and cp['scientific_recovery_admitted'] is False and
            cp['actual_disappearance_boundary_ref']==item['actual_disappearance_boundary_ref'] and
            cp['pristine_original1664_ids_ref']==item['pristine_original_ids_ref'] and
            cp['original3394_status_counts']=={'COMPLETE':1730,'NAMED':1664},
            'R4_NATIVE_UNKNOWN_AND_PARTIAL_SCOPE_PRESERVED')
    require(review.get('status')=='PASS' and review.get('independent_from_audit_writer') is True and
            review.get('approved_actual_audit_ref')==item['actual_finite_audit_ref'] and
            review.get('approved_partial_checkpoint_ref')==item['actual_partial_checkpoint_ref'] and
            review.get('approved_pristine1664_original_ids_ref')==item['pristine_original_ids_ref'] and
            review.get('can_prepare_R5_nonexecuted_source_cold_phase_candidates') is True and
            review.get('scientific_recovery_admission') is False,
            'ACTUAL_INDEPENDENT_CHECKPOINT_SCOPE_NOT_SCIENCE_ADMISSION')
    prior=read_control(item['prior_source_epoch_ref'])
    require(set(item['prior_runtime_whole_custody_refs'])=={'entry','controller','source_guard_owner'},
            'ALL_R4_BEFORE_CONTROL_CUSTODIES')
    for key,value in item['prior_runtime_whole_custody_refs'].items():
        require(value['sha256']==prior['runtime_source_refs'][key]['sha256'],'R4_BEFORE_CONTROL_BYTES_EXACT')
        require(pin(value).is_relative_to((RUN/'source_corrections/POLICY_CHECKPOINT_GUARD_R5').resolve()),
                'R5_TASK_PRIVATE_BEFORE_CONTROL_CUSTODY')
    custody=read_control(item['publication_checkpoint_custody_ref'])
    require(custody.get('schema')=='FULL_SELECTOR_POLICY_R4_CHECKPOINT_PUBLICATION_CUSTODY_R5' and
            custody.get('actual_partial_checkpoint_ref')==item['actual_partial_checkpoint_ref'] and
            custody.get('scientific_calls')==0 and custody.get('ledger_writes')==0 and
            isinstance(custody.get('publication_custody_refs'),dict) and len(custody['publication_custody_refs'])==9,
            'EXACT_CHECKPOINT_MUTABLE_PUBLICATION_CUSTODY')
    for value in custody['publication_custody_refs'].values():
        require(set(value)=={'original_observation_ref','immutable_custody_ref'} and
                value['original_observation_ref']['sha256']==value['immutable_custody_ref']['sha256'],
                'CHECKPOINT_PUBLICATION_WHOLE_BYTES')
        require(pin(value['immutable_custody_ref']).is_relative_to(
            (RUN/'source_corrections/POLICY_CHECKPOINT_GUARD_R5').resolve()),'CHECKPOINT_PUBLICATION_CUSTODY_ROOT')
    return item,cp,custody


def checkpoint_plan(rows,events,original_ids,remaining_ids,checkpoint,*,original_expected,
                    original_history,admission_ref,restored_at_utc):
    """Read-only metadata predicate; the caller seals this contract physically."""
    require(checkpoint.get('schema')=='FULL_SELECTOR_POLICY_ZERO_ENTRY_R4_ACTUAL_PARTIAL_CHECKPOINT_R1' and
            checkpoint.get('status')=='ACTUAL_METADATA_CHECKPOINT_NOT_SCIENTIFIC_OR_NATIVE_TERMINAL' and
            checkpoint.get('native_exit_code') is None and checkpoint.get('native_wait_completion_observed') is False and
            checkpoint.get('session48898_collected') is False and checkpoint.get('scientific_recovery_admitted') is False,
            'CHECKPOINT_NOT_NATIVE_OR_SCIENCE_TERMINAL')
    require(original_ids==sorted(set(original_ids)) and len(original_ids)==original_expected['target_count'] and
            digest(original_ids)==original_expected['ids_sha256'] and
            remaining_ids==sorted(set(remaining_ids)) and set(remaining_ids)<=set(original_ids),
            'ORIGINAL_NAMESPACE_AND_DERIVED_REMAINING_SUBSET')
    require(checkpoint['actual_ledger_poststate']==dict(nodes_sha256=digest(rows),
            events_sha256=digest(events),event_count=len(events)),'EXACT_WHOLE_PARTIAL_CHECKPOINT')
    targets=set(original_ids);pending=set(remaining_ids)
    by_id={r[0]:r for r in rows}
    require(len(by_id)==len(rows) and targets<=by_id.keys() and not any(r[2]=='STARTED' for r in rows),
            'NO_MISSING_OR_DUPLICATE_OR_STARTED_CHECKPOINT_NODE')
    require(all(tuple(by_id[node][2:])==('NAMED',0,None,None,None) for node in remaining_ids),
            'ONLY_PRISTINE_ORIGINAL_FIRST_ENTRIES')
    completed=sorted(targets-pending)
    require(all(by_id[node][2]=='COMPLETE' for node in completed) and
            checkpoint['original3394_status_counts']=={'COMPLETE':len(completed),'NAMED':len(remaining_ids)} and
            checkpoint['completed_original1730_ids_sha256']==digest(completed),
            'EXACT_COMPLETED_AND_REMAINING_CHECKPOINT_PARTITION')
    artifacts=[(json.loads(by_id[node][5])['path'],json.loads(by_id[node][5])['sha256']) for node in completed]
    require(digest(artifacts)==checkpoint['completed_original1730_artifact_metadata_digest'] and
            checkpoint['new_backend_entries']==len(completed) and checkpoint['new_scientific_FAILED']==0 and
            checkpoint['remaining1664_entered']==0,'COMPLETED_ORIGINAL_ONCE_METADATA_PRESERVED')
    old_count=original_expected['event_count']
    require(not any(e[1] in pending for e in events[old_count+len(original_ids):]),
            'REMAINING_IDS_HAVE_NO_POST_ADMIN_EVENT')
    # This inverse projection is verified against the genuine whole prestate
    # digests by the unchanged original predicate. It is not a new old receipt.
    reconstructed=[(r[0],r[1],'BLOCKED_DEPENDENCY',0,None,None,original_expected['error'])
                   if r[0] in targets else r for r in rows]
    original_events=events[:old_count]
    require(digest(reconstructed)==original_expected['nodes_sha256'] and
            digest(original_events)==original_expected['events_sha256'],'VERIFIED_ORIGINAL_PRESTATE_RECONSTRUCTION')
    history=original_history(reconstructed,original_events,rows,events,original_ids,
                             original_expected,admission_ref,restored_at_utc)
    require(history['status']=='PASS_METADATA_HISTORY_ONLY','ORIGINAL_HISTORY_REQUIRED')
    return dict(status='PASS_CHECKPOINT_METADATA_ONLY',remaining_original_ids=len(remaining_ids),
                completed_original_ids=len(completed),new_ADMIN_events=0,
                original_history=history,checkpoint_event_count=len(events))


def checkpoint_history(before_rows,before_events,after_rows,after_events,original_ids,remaining_ids,checkpoint,*,
                       original_expected,original_history,admission_ref,restored_at_utc):
    """Protect the entire checkpoint and delegate every chain to the old owner."""
    checkpoint_plan(before_rows,before_events,original_ids,remaining_ids,checkpoint,
        original_expected=original_expected,original_history=original_history,
        admission_ref=admission_ref,restored_at_utc=restored_at_utc)
    before={r[0]:r for r in before_rows};after={r[0]:r for r in after_rows};pending=set(remaining_ids)
    require(len(after)==len(after_rows) and before.keys()==after.keys(),'CHECKPOINT_NODE_NAMESPACE_UNCHANGED')
    require(all(after[n]==before[n] for n in before.keys()-pending),'ALL_NON_REMAINING_CHECKPOINT_ROWS_EXACT')
    require(after_events[:len(before_events)]==before_events,'WHOLE48545_CHECKPOINT_EVENT_PREFIX_EXACT')
    allowed={'BEGIN','BACKEND_ENTER','COMPLETE','FAILED','BLOCKED_DEPENDENCY'}
    require(all(e[1] in pending and e[2] in allowed for e in after_events[len(before_events):]),
            'ONLY_ORIGINAL_REMAINING_ONCE_NO_SECOND_ADMIN')
    targets=set(original_ids)
    reconstructed=[(r[0],r[1],'BLOCKED_DEPENDENCY',0,None,None,original_expected['error'])
                   if r[0] in targets else r for r in before_rows]
    history=original_history(reconstructed,before_events[:original_expected['event_count']],
        after_rows,after_events,original_ids,original_expected,admission_ref,restored_at_utc)
    return dict(status='PASS_CHECKPOINT_METADATA_HISTORY_ONLY',original_history=history,
                actual_checkpoint_prefix_preserved=True,all_non_remaining_rows_preserved=True,
                second_ADMIN_events=0,remaining_original_ids=len(remaining_ids))


# P-only future catalog1655 control additions. No installation or execution admission.
_CATALOG_LIMITED_PRESTATE_R6 = dict(
    nodes_sha256="70bd0eca46850a37ef59247e3bbb5279c280bfb13cd513a283f04707908290a0",
    events_sha256="e57274e3a37b21e5b255b3fd11afb68aa7e4b969b3005b9d19d8185ad3b84f0a",
    event_count=50215)
_CATALOG_LIMITED_PENDING_DIGEST_R6 = "ec4c4d7dfa598f0a2da87a49a75f620e492a66296fa272b736b391384abf4ac8"
_CATALOG_LIMITED_TARGET_DIGEST_R6 = "3cdac858754c39ff5e78ce91d51195706f644ef438c65232a00a9192e185dbfe"
_CATALOG_LIMITED_ERROR_SHA_R6 = "464dd320ddf80a2c8e693e2facd721cb54e890ea6c722c0bc5afcd22904b43b6"
_CATALOG_LIMITED_COMPLETED3_DIGEST_R6 = "ecfedae2017420f647207c771983241645e5e0324b239e8a020d8ddad586fd9f"
_CATALOG_LIMITED_OTHER6_DIGEST_R6 = "71e2190564b301268f555adc34015bdd02b5b407c933101e600e5c4073f1d6e8"
_CATALOG_LIMITED_QUESTION_ITEM_R6 = '["request_user_input_async","call_d37671712236463a9076221da369b7cb",0]'
_CATALOG_LIMITED_CONTROL_ROOT_R6 = Path("D:/us-tech-quant-cache/V24/C_SELECTOR/FULL_SELECTOR_FIXED_POLICY_FAST_R1/proposals")
_CATALOG_LIMITED_HUMAN_REF_R6 = dict(
    path=str(RUN/"maintenance/POLICY_CHECKPOINT_ORIGINAL1655_LIMITED_SECOND_ADMIN_HUMAN_AUTHORIZATION_R1.json"),
    sha256="ef52a7ffbe447a715600b1d7fbe802ba69f252f3d1e502ac7fd9530621a7dd02")
_CATALOG_LIMITED_TRANSCRIPT_REF_R6 = dict(
    path=str(RUN/"maintenance/POLICY_CHECKPOINT_ORIGINAL1655_HUMAN_AUTHORIZATION_QUESTION_TRANSCRIPT_CLARIFICATION_R1.json"),
    sha256="e54b9bb8d0a24a1ff6031892eb44f8a8baa70698d5695e2036cf32932c34f6b0")
_CATALOG_LIMITED_PREVIEW_REF_R6 = dict(
    path=str(_CATALOG_LIMITED_CONTROL_ROOT_R6/"POLICY_CHECKPOINT_R5_MINIMAL_ZERO_ENTRY_RECOVERY_PREVIEW_R1.json"),
    sha256="ca3c06473ca9808514873be289a0b2420a04fcce3dd559de0b7eb2715d6c3b96")
_CATALOG_LIMITED_IDS_REF_R6 = dict(
    path=str(_CATALOG_LIMITED_CONTROL_ROOT_R6/"POLICY_CHECKPOINT_R5_SEALED_ENGINEERING_ZERO_ENTRY1655_ORIGINAL_IDS_R1.json"),
    sha256="dd73f13df78f09d90766e9b57a9066ee040784006f0194e524cb3cc45c89de63")

def catalog_limited1655_validate_human_payloads(authority, transcript, sealed, preview):
    """Pure validation of pinned human controls; this grants no execution phase."""
    require(authority.get("schema") == "POLICY_CHECKPOINT_ORIGINAL1655_LIMITED_SECOND_ADMIN_HUMAN_AUTHORIZATION_R1"
            and authority.get("status") == "HUMAN_EXPLICIT_LIMITED_EXCEPTION_APPROVED"
            and authority.get("authority") == "DIRECT_HUMAN_ASYNC_QUESTION_REPLY_IN_CURRENT_CHAT"
            and authority.get("question_item_id") == _CATALOG_LIMITED_QUESTION_ITEM_R6
            and authority.get("exact_human_answer") == "批准上述限定例外"
            and authority.get("target_count") == 1655 and authority.get("zero_entry_scope_only") is True
            and authority.get("excluded_completed_count") == 3
            and authority.get("excluded_other_dependency_count") == 6,
            "CATALOG_LIMITED_DIRECT_HUMAN_1655_ONLY")
    require(authority.get("execution_conditions") == [
                "ACTUAL_SOURCE_REPAIR_AND_CURRENT_HISTORY", "NECESSARY_VALIDATION", "ACTUAL_COLD",
                "ORIGINAL_SOLEPEER_INDEPENDENT_PHASE", "FORMAL_ACCEPTANCE", "ROOTLAST",
                "FRESH_RESOURCES", "ORIGINAL_LOCK"]
            and authority.get("all_FAILED_saved5_original_fee_once_and_ID_budget_preserved") is True
            and authority.get("original_second_ADMIN_forbidden_retained_outside_this_named_exception") is True
            and authority.get("original_ids_file_is_not_new_scientific_identity_authority") is True
            and authority.get("no_old_launcher_or_session_reuse") is True
            and authority.get("old70445_collection_count") == 1
            and authority.get("actual_live_ledger_restore_performed") is False
            and authority.get("actual_scientific_start_admitted") is False
            and authority.get("ACCOUNT_STAT_admitted") is False,
            "CATALOG_LIMITED_HUMAN_CONDITIONS_NOT_EXECUTION_ADMISSION")
    require(authority.get("preview_ref") == dict(_CATALOG_LIMITED_PREVIEW_REF_R6, bytes=4488)
            and authority.get("sealed_original1655_ids_ref") == dict(_CATALOG_LIMITED_IDS_REF_R6, bytes=62088),
            "CATALOG_LIMITED_APPROVED_EXACT_DERIVED_SET")
    require(transcript.get("schema") == "POLICY_CHECKPOINT_HUMAN_AUTHORIZATION_QUESTION_TRANSCRIPT_CLARIFICATION_R1"
            and transcript.get("original_authorization_receipt_ref") == _CATALOG_LIMITED_HUMAN_REF_R6
            and transcript.get("question_item_id") == _CATALOG_LIMITED_QUESTION_ITEM_R6
            and transcript.get("verbatim_answer") == authority["exact_human_answer"]
            and transcript.get("authorization_scope_target_IDs_conditions_and_human_answer_unchanged") is True
            and transcript.get("original_receipt_exact_question_field_is_normalized_question_summary_not_verbatim") is True
            and type(transcript.get("verbatim_question")) is str
            and "1655" in transcript["verbatim_question"] and "第二次ADMIN机械恢复" in transcript["verbatim_question"],
            "CATALOG_LIMITED_CONSUME_VERBATIM_TRANSCRIPT_CORRECTION")
    require(preview.get("schema") == "POLICY_CHECKPOINT_R5_MINIMAL_ZERO_ENTRY_RECOVERY_PREVIEW_R1"
            and preview.get("derived_target_ids_ref") == dict(_CATALOG_LIMITED_IDS_REF_R6, bytes=62088)
            and preview.get("ledger_poststate") == _CATALOG_LIMITED_PRESTATE_R6
            and preview.get("proposed_only_target_count") == 1655
            and preview.get("preserved_paid_complete_original_count") == 3
            and preview.get("preserved_other_dependency_original_count") == 6
            and preview.get("every_proposed_target_has_zero_backend_entry") is True
            and preview.get("original_id_authority_unchanged") is True
            and preview.get("paid_scientific_retry") is False,
            "CATALOG_LIMITED_ACCEPTED_PREVIEW_NOT_NEW_AUTHORITY")
    require(sealed.get("schema") == "POLICY_CHECKPOINT_R5_SEALED_ENGINEERING_ZERO_ENTRY_ORIGINAL_IDS_DERIVATION_R1"
            and sealed.get("authority") is False
            and sealed.get("scope") == "EXACT_SUBSET_OF_ORIGINAL_R5_1664_NOT_NEW_SCIENTIFIC_IDS"
            and sealed.get("original_order_preserved") is True
            and sealed.get("original_ids_digest") == _CATALOG_LIMITED_PENDING_DIGEST_R6
            and sealed.get("target_count") == 1655
            and sealed.get("target_ids_digest") == _CATALOG_LIMITED_TARGET_DIGEST_R6
            and sealed.get("error_sha256") == _CATALOG_LIMITED_ERROR_SHA_R6
            and sealed.get("excluded_original_completed_count") == 3
            and sealed.get("excluded_original_completed_ids_digest") == _CATALOG_LIMITED_COMPLETED3_DIGEST_R6
            and sealed.get("excluded_other_dependency_count") == 6
            and sealed.get("excluded_other_dependency_ids_digest") == _CATALOG_LIMITED_OTHER6_DIGEST_R6,
            "CATALOG_LIMITED_SEALED_ORIGINAL1655_DERIVATION")
    targets = sealed.get("original_node_ids")
    require(type(targets) is list and all(type(x) is str for x in targets)
            and targets == sorted(set(targets)) and len(targets) == 1655
            and digest(targets) == _CATALOG_LIMITED_TARGET_DIGEST_R6,
            "CATALOG_LIMITED_TARGET_LIST_ORDER_AND_DIGEST")
    return dict(schema="CATALOG_LIMITED1655_HUMAN_SCOPE_R6",
                scope="ORIGINAL1655_LIMITED_SECOND_ADMIN_AFTER_ALL_OTHER_GATES",
                human_authorization_ref=dict(_CATALOG_LIMITED_HUMAN_REF_R6),
                transcript_clarification_ref=dict(_CATALOG_LIMITED_TRANSCRIPT_REF_R6),
                preview_ref=dict(_CATALOG_LIMITED_PREVIEW_REF_R6),
                derived_ids_ref=dict(_CATALOG_LIMITED_IDS_REF_R6),
                original_node_ids=list(targets), source_or_phase_admission=False,
                scientific_execution_authorized=False)

def _catalog_limited1655_read_fixed_control(name):
    """Pre-cap and pin the same bytes from one handle; four fixed controls only."""
    import hashlib
    import os
    slots = {
        "authority": (_CATALOG_LIMITED_HUMAN_REF_R6, 2328, 4096),
        "transcript": (_CATALOG_LIMITED_TRANSCRIPT_REF_R6, 1468, 4096),
        "sealed": (_CATALOG_LIMITED_IDS_REF_R6, 62088, 65536),
        "preview": (_CATALOG_LIMITED_PREVIEW_REF_R6, 4488, 8192),
    }
    require(type(name) is str and name in slots, "CATALOG_LIMITED_FOUR_FIXED_CONTROL_NAMES_ONLY")
    value, expected_size, cap = slots[name]
    path = Path(value["path"])
    with path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        identity = (before.st_size, before.st_mtime_ns, before.st_ino, before.st_dev)
        require(0 < before.st_size == expected_size <= cap, "CATALOG_LIMITED_CONTROL_SIZE_BEFORE_READ")
        payload = handle.read(before.st_size)
        after = os.fstat(handle.fileno())
        require(len(payload) == before.st_size
                and (after.st_size, after.st_mtime_ns, after.st_ino, after.st_dev) == identity,
                "CATALOG_LIMITED_CONTROL_HANDLE_CHANGED")
    require(hashlib.sha256(payload).hexdigest() == value["sha256"], "CATALOG_LIMITED_CONTROL_SAME_BYTES_PIN")
    def closed_pairs(pairs):
        result = {}
        for key, item in pairs:
            require(key not in result, "CATALOG_LIMITED_DUPLICATE_CONTROL_KEY")
            result[key] = item
        return result
    def reject_constant(value):
        raise ValueError("CATALOG_LIMITED_NONFINITE_CONTROL_VALUE")
    result = json.loads(payload, object_pairs_hook=closed_pairs, parse_constant=reject_constant, parse_float=_catalog_finite_control_float)
    require(type(result) is dict, "CATALOG_LIMITED_CONTROL_OBJECT_REQUIRED")
    return result

def catalog_limited1655_human_scope():
    """Only four fixed controls; no ledger/model reads and no phase admission."""
    authority = _catalog_limited1655_read_fixed_control("authority")
    transcript = _catalog_limited1655_read_fixed_control("transcript")
    sealed = _catalog_limited1655_read_fixed_control("sealed")
    preview = _catalog_limited1655_read_fixed_control("preview")
    return catalog_limited1655_validate_human_payloads(authority, transcript, sealed, preview)

def catalog_limited1655_plan(rows, events, original_ids, pending1664, human_scope):
    """Pure R5 terminal metadata plan; no SQL, ADMIN, budget or scientific calls."""
    import hashlib
    from collections import defaultdict
    require(type(human_scope) is dict
            and human_scope.get("schema") == "CATALOG_LIMITED1655_HUMAN_SCOPE_R6"
            and human_scope.get("scope") == "ORIGINAL1655_LIMITED_SECOND_ADMIN_AFTER_ALL_OTHER_GATES"
            and human_scope.get("human_authorization_ref") == _CATALOG_LIMITED_HUMAN_REF_R6
            and human_scope.get("transcript_clarification_ref") == _CATALOG_LIMITED_TRANSCRIPT_REF_R6
            and human_scope.get("derived_ids_ref") == _CATALOG_LIMITED_IDS_REF_R6
            and human_scope.get("source_or_phase_admission") is False
            and human_scope.get("scientific_execution_authorized") is False,
            "CATALOG_LIMITED_HUMAN_SCOPE_REQUIRED_NOT_ADMISSION")
    require(type(original_ids) is list and original_ids == sorted(set(original_ids))
            and len(original_ids) == 3394 and digest(original_ids) == ACTUAL_PRESTATE["ids_sha256"]
            and type(pending1664) is list and pending1664 == sorted(set(pending1664))
            and len(pending1664) == 1664 and set(pending1664) <= set(original_ids)
            and digest(pending1664) == _CATALOG_LIMITED_PENDING_DIGEST_R6,
            "CATALOG_LIMITED_SAME_ORIGINAL3394_AND_PRIOR1664")
    targets = human_scope["original_node_ids"]
    require(type(targets) is list and targets == sorted(set(targets))
            and len(targets) == 1655 and set(targets) <= set(pending1664)
            and digest(targets) == _CATALOG_LIMITED_TARGET_DIGEST_R6,
            "CATALOG_LIMITED_APPROVED_TARGETS_NO_NEW_IDS")
    require(all(len(q) == 7 for q in rows) and all(len(e) == 5 for e in events)
            and digest(rows) == _CATALOG_LIMITED_PRESTATE_R6["nodes_sha256"]
            and digest(events) == _CATALOG_LIMITED_PRESTATE_R6["events_sha256"]
            and len(events) == _CATALOG_LIMITED_PRESTATE_R6["event_count"],
            "CATALOG_LIMITED_EXACT_ACCEPTED50215_BEFORESTATE")
    by_id = {q[0]: q for q in rows}
    require(len(by_id) == len(rows) and set(original_ids) <= set(by_id),
            "CATALOG_LIMITED_ORIGINAL_NODE_NAMESPACE_INTACT")
    pending_set = set(pending1664)
    actions = defaultdict(list)
    for seq, node, action, payload, utc in events:
        if seq > 48545 and node in pending_set:
            actions[node].append(action)
    completed, engineering, other = [], [], []
    other_errors = defaultdict(int)
    for node in pending1664:
        q = by_id[node]
        require(type(q[3]) is int and q[3] in (0, 1), "CATALOG_LIMITED_EXACT_ENTERED_TYPE")
        if q[2] == "COMPLETE":
            require(q[3] == 1 and q[4] is not None and q[5] is not None and q[6] is None
                    and actions[node] == ["BEGIN", "BACKEND_ENTER", "COMPLETE"],
                    "CATALOG_LIMITED_ORIGINAL3_PAID_COMPLETE_PRESERVED")
            completed.append(node)
        else:
            require(q[2] == "BLOCKED_DEPENDENCY" and q[3] == 0 and q[4] is None
                    and q[5] is None and type(q[6]) is str
                    and actions[node] == ["BLOCKED_DEPENDENCY"],
                    "CATALOG_LIMITED_BLOCK_WITHOUT_ANY_BACKEND_ENTRY")
            fingerprint = hashlib.sha256(q[6].encode("utf-8")).hexdigest()
            if fingerprint == _CATALOG_LIMITED_ERROR_SHA_R6:
                require(len(q[6]) == 81 and q[6].startswith("PHYSICAL_REFERENCE_CHANGED:"),
                        "CATALOG_LIMITED_EXACT_ENGINEERING_ERROR")
                engineering.append(node)
            else:
                require(q[6].startswith("RISK_FAMILY_SOURCE_OR_TRAINING_NOT_TESTABLE"),
                        "CATALOG_LIMITED_UNRELATED_BLOCK_NOT_RECOVERABLE")
                other.append(node); other_errors[fingerprint] += 1
    require(engineering == targets and len(completed) == 3 and len(other) == 6
            and digest(completed) == _CATALOG_LIMITED_COMPLETED3_DIGEST_R6
            and digest(other) == _CATALOG_LIMITED_OTHER6_DIGEST_R6
            and dict(other_errors) == {
                "a37c7919b6d6157064be9a72386a8f361f9db9bc7875c6bf4d73299a91f289c9": 3,
                "952d529ecfef5f7a9acc071951b03681fb70b7a70c7901049f574171b6a5b8d7": 3},
            "CATALOG_LIMITED_EXCLUDE_ALL3_PAID_AND_OTHER6_DEPENDENCIES")
    old_complete = [by_id[node] for node in original_ids if node not in pending_set]
    require(len(old_complete) == 1730 and all(
                q[2] == "COMPLETE" and q[3] == 1 and q[4] is not None
                and q[5] is not None and q[6] is None for q in old_complete),
            "CATALOG_LIMITED_PRIOR1730_ONCE_ROWS_UNCHANGED")
    return dict(schema="CATALOG_LIMITED1655_ZERO_ENTRY_METADATA_PLAN_R6",
                ledger_prestate=dict(_CATALOG_LIMITED_PRESTATE_R6),
                original3394_count=3394, prior_pending1664_count=1664,
                restore_target_count=1655, target_ids_sha256=digest(targets),
                preserved_original_complete_count=1733,
                excluded_new_paid_complete_count=3, excluded_other_dependency_count=6,
                required_ADMIN_event_count=1655, permitted_transition="BLOCKED_DEPENDENCY_TO_NAMED",
                entered_identity_artifact_remain_pristine=True,
                exact_engineering_error_sha256=_CATALOG_LIMITED_ERROR_SHA_R6,
                wholebefore_capture_required=True, all_other_gates_required=True,
                ledger_mutation_performed=False, source_or_phase_admission=False,
                scientific_execution_authorized=False)


CATALOG_SOURCE_SCHEMA = "FULL_SELECTOR_POLICY_CATALOG_LIMITED1655_SOURCE_R6"
CATALOG_SOURCE_NAME = "ENGINEERING_POLICY_CATALOG_LIMITED1655_SOURCE_R6.json"
CATALOG_SOURCE_FIELDS = {"schema","status","research_id","design_ref","original_sources",
    "prior_checkpoint_source_ref","runtime_source_refs","catalog_nonexecuted_annex_ref",
    "catalog_epoch_transition_ref","independent_review_ref"}
CATALOG_TRANSITION_FIELDS = {"schema","status","research_id","prior_R5_source_ref",
    "R5_terminal_gate_ref","R5_terminal_collection_ref","R5_terminal_audit_ref","R5_terminal_independent_ref",
    "human_authorization_ref","human_transcript_ref","prior_runtime_whole_custody_refs",
    "expected_ledger_metadata","old_science_native_exit_code","old_science_collection_count",
    "catalog_historical_old_identity","current_runtime_source_refs","grants_scientific_execution"}
_CATALOG_CONTROL_FILES = {
    "source": (RUN/CATALOG_SOURCE_NAME, 32768),
    "phase_cfg": (RUN/"continuation/POST_RISK_POLICY_CATALOG_LIMITED1655_FIRST_R6_CONFIGURATION.json",32768),
    "phase_acceptance": (RUN/"continuation/POST_RISK_POLICY_CATALOG_LIMITED1655_FIRST_R6_ACCEPTANCE.json",16384),
    "phase_root": (RUN/"maintenance/POLICY_CATALOG_LIMITED1655_ROOT_LAST_ACTUAL_PHASE_ADMISSION_R6.json",16384),
    "phase_resource": (RUN/"maintenance/POLICY_CATALOG_LIMITED1655_SCIENCE_FRESH_RESOURCE_PERMIT_R6.json",8192),
    "actual_cold": (Path("D:/us-tech-quant-cache/V24/C_SELECTOR/FULL_SELECTOR_FIXED_POLICY_FAST_R1/proposals/POLICY_CATALOG_LIMITED1655_ACTUAL_COLD_R6.json"),32768),
    "actual_cold_os": (RUN/"maintenance/POLICY_CATALOG_LIMITED1655_COLD_OS_R6.json",16384),
    "actual_cold_root": (RUN/"maintenance/POLICY_CATALOG_LIMITED1655_ACTUAL_COLD_ROOT_TERMINAL_R6.json",16384),
    "actual_cold_identity": (RUN/"maintenance/POLICY_CATALOG_LIMITED1655_COLD_NATIVE_BIRTH_IDENTITY_R6.json",8192),
    "actual_cold_observation": (RUN/"maintenance/POLICY_CATALOG_LIMITED1655_COLD_PROCESS_OBSERVATION_R6.json",16384),
    "actual_cold_launch": (RUN/"maintenance/POLICY_CATALOG_LIMITED1655_COLD_ACTUAL_LAUNCH_R6.json",16384),
    "actual_cold_installation": (RUN/"maintenance/POLICY_CATALOG_LIMITED1655_ACTUAL_SOURCE_INSTALLATION_R6.json",32768),
    "old_phase_cfg": (RUN/"continuation/POST_RISK_POLICY_SOURCE_GUARD_CHECKPOINT_NAMED_FIRST_R5_CONFIGURATION.json",32768),
    "original_ids": (Path("D:/us-tech-quant-cache/V24/C_SELECTOR/FULL_SELECTOR_FIXED_POLICY_FAST_R1/proposals/POLICY_REBOOT_SOURCE_GUARD_ZERO_ENTRY_ORIGINAL_IDS_R1.json"),262144),
    "prior_remaining_ids": (Path("D:/us-tech-quant-cache/V24/C_SELECTOR/FULL_SELECTOR_FIXED_POLICY_FAST_R1/proposals/POLICY_ZERO_ENTRY_R4_ACTUAL_PRISTINE1664_ORIGINAL_IDS_R1.json"),131072),
    "wholebefore": (RUN/"maintenance/POLICY_CATALOG_LIMITED1655_PRE_RESTORE_WHOLEBEFORE_R6.json",32768),
    "metadata_evidence": (RUN/"maintenance/POLICY_CATALOG_LIMITED1655_ACTUAL_SOURCE_METADATA_PROBE_R6.json",32768),
    "metadata_registry_capture": (RUN/"maintenance/FIXED214_POLICY_CATALOG_SOURCE_METADATA_R6_PRIOR_TWO_CAPTURE.json",32768),
    "metadata_catalog_capture": (RUN/"maintenance/FIXED214_POLICY_CATALOG_SOURCE_METADATA_R6_NONEXECUTED_CAPTURE.json",32768),
    "intent": (RUN/"maintenance/POLICY_CATALOG_LIMITED1655_SOURCE_INTENT_R6.json",32768),
    "prior": (RUN/SOURCE_NAME, 32768),
    "annex": (RUN/"ENGINEERING_POLICY_CATALOG_NONEXECUTED_SOURCE_ANNEX_R2.json",32768),
    "transition": (RUN/"maintenance/POLICY_CATALOG_LIMITED1655_SOURCE_EPOCH_TRANSITION_R6.json",32768),
    "review": (RUN/"maintenance/POLICY_CATALOG_LIMITED1655_SOURCE_INDEPENDENT_REVIEW_R6.json",32768),
    "terminal_gate": (RUN/"maintenance/POLICY_CHECKPOINT_R5_ACTUAL_SCIENCE_TERMINAL_OWNER_GATE_R1.json",16384),
    "collection": (RUN/"maintenance/POLICY_CHECKPOINT_R5_ACTUAL_SCIENCE_COLLECTION_R1.json",8192),
    "audit": (Path("D:/us-tech-quant-results/_maintenance")/ID/"POLICY_CHECKPOINT_R5_ACTUAL_TERMINAL_FINITE_METADATA_AUDIT_R1.json",65536),
    "peer": (Path("D:/us-tech-quant-cache/V24/C_SELECTOR/FULL_SELECTOR_FIXED_POLICY_FAST_R1/proposals/POLICY_CHECKPOINT_R5_ACTUAL_TERMINAL_FINITE_METADATA_INDEPENDENT_ACCEPTANCE_R1.json"),32768),
}
_CATALOG_OLD_TERMINAL_PINS = {
    "terminal_gate":"772c55b12b7353419e92f716b91974a1c0aa8207f2a5a6f9efbb03c88d399845",
    "collection":"b224e35992b99a22291a405e3231cd15a30f15678e63667ac5d8cb8a83ea64b2",
    "audit":"5f2b9d074f301e2c31a7c3b2ccc7c73f963ea6d6b23876271f78824a62e08348",
    "peer":"e63fc99404a106ad20b8138546d9babd8852ef931b017ed526395c37b99b1f64"}
_CATALOG_SOURCE_REVIEW_CHECKS = frozenset({
    "independent_from_entry_writer","independent_from_source_writer","original99_and_existing_transport_preserved",
    "specific_catalog_only_nonexecuted_branch","actual_catalog_and_registry_capture_verified",
    "whole_history_and_prior_runtime_custody_verified","R5_failure_native1_collection1_preserved",
    "both_human_authorization_receipts_verified","limited1655_scope_only_no_id_or_budget_change",
    "math_precision_order_rng_and_once_unchanged","metadata_cold_firstentry_slots_separate",
    "intent_and_full_source_payload_digests_distinct","no_source_or_phase_admission_from_annex"})

def catalog_source_read_control(ref, name):
    """Only these fixed control files; cap and hash the same binary handle."""
    import os, stat
    require(name in _CATALOG_CONTROL_FILES,"CATALOG_FIXED_CONTROL_NAME")
    expected,cap=_CATALOG_CONTROL_FILES[name]
    require(type(ref) is dict and set(ref)=={"path","sha256"}
        and type(ref["path"]) is str and Path(ref["path"]).resolve()==expected.resolve()
        and type(ref["sha256"]) is str and len(ref["sha256"])==64
        and all(ch in "0123456789abcdef" for ch in ref["sha256"]),"CATALOG_CLOSED_FIXED_CONTROL_REF")
    def pairs(items):
        result={}
        for key,value in items:
            require(key not in result,"CATALOG_DUPLICATE_CONTROL_KEY")
            result[key]=value
        return result
    def nonfinite(value):
        raise ValueError("CATALOG_NONFINITE_CONTROL_VALUE")
    with expected.open("rb") as handle:
        before=os.fstat(handle.fileno())
        require(stat.S_ISREG(before.st_mode) and 0<before.st_size<=cap,"CATALOG_CONTROL_CAP_BEFORE_READ")
        raw=handle.read(before.st_size);after=os.fstat(handle.fileno())
        require(len(raw)==before.st_size and tuple(getattr(before,k) for k in ("st_size","st_mtime_ns","st_ino","st_dev"))==
            tuple(getattr(after,k) for k in ("st_size","st_mtime_ns","st_ino","st_dev")),"CATALOG_CONTROL_HANDLE_CHANGED")
    require(hashlib.sha256(raw).hexdigest()==ref["sha256"],"CATALOG_CONTROL_HASH_CHANGED")
    result=json.loads(raw.decode("utf-8"),object_pairs_hook=pairs,parse_constant=nonfinite,parse_float=_catalog_finite_control_float)
    require(type(result) is dict,"CATALOG_CONTROL_OBJECT_REQUIRED")
    return result

def catalog_source_intent_payload(data):
    require(type(data) is dict and set(data)==CATALOG_SOURCE_FIELDS,"CATALOG_CLOSED_SOURCE_FOR_INTENT")
    return {key:value for key,value in data.items()
        if key not in {"status","independent_review_ref","catalog_nonexecuted_annex_ref"}}

def _catalog_source_predecessor(ref):
    require(ref==dict(path=str(RUN/SOURCE_NAME),sha256="95b948bc6c949afac49e1957c9b9dd1a759d0b6102e43a8c8a2331b71006165e"),
        "CATALOG_ONLY_SEALED_R5_PREDECESSOR")
    old=catalog_source_read_control(ref,"prior")
    require(set(old)==SOURCE_FIELDS and old["schema"]==SOURCE_SCHEMA and old["status"]=="PASS"
        and old["research_id"]==ID,"CATALOG_CLOSED_OLD_R5_HISTORY")
    prior,design_sources=_source_epoch_history_head(old)
    _source_epoch_history_tail(old,prior)
    _source_epoch_independent_review(old)
    return old,prior,design_sources

def _catalog_source_transition(data, old):
    transition=catalog_source_read_control(data["catalog_epoch_transition_ref"],"transition")
    require(set(transition)==CATALOG_TRANSITION_FIELDS
        and transition["schema"]=="FULL_SELECTOR_POLICY_CATALOG_LIMITED1655_SOURCE_EPOCH_TRANSITION_R6"
        and transition["status"]=="PASS" and transition["research_id"]==ID
        and transition["prior_R5_source_ref"]==data["prior_checkpoint_source_ref"]
        and transition["current_runtime_source_refs"]==data["runtime_source_refs"]
        and transition["expected_ledger_metadata"]==dict(nodes_sha256="70bd0eca46850a37ef59247e3bbb5279c280bfb13cd513a283f04707908290a0",
            events_sha256="e57274e3a37b21e5b255b3fd11afb68aa7e4b969b3005b9d19d8185ad3b84f0a",event_count=50215)
        and type(transition["old_science_native_exit_code"]) is int and transition["old_science_native_exit_code"]==1
        and type(transition["old_science_collection_count"]) is int and transition["old_science_collection_count"]==1
        and transition["catalog_historical_old_identity"]=="UNKNOWN"
        and transition["grants_scientific_execution"] is False,"CATALOG_CLOSED_NEW_HISTORY_TRANSITION")
    for name,key in (("terminal_gate","R5_terminal_gate_ref"),("collection","R5_terminal_collection_ref"),
                     ("audit","R5_terminal_audit_ref"),("peer","R5_terminal_independent_ref")):
        require(transition[key]["sha256"]==_CATALOG_OLD_TERMINAL_PINS[name],"CATALOG_EXACT_R5_TERMINAL_HISTORY")
        catalog_source_read_control(transition[key],name)
    human=catalog_limited1655_human_scope()
    require(transition["human_authorization_ref"]==human["human_authorization_ref"]
        and transition["human_transcript_ref"]==human["transcript_clarification_ref"],"CATALOG_BOTH_HUMAN_RECEIPTS_REQUIRED")
    custody=transition["prior_runtime_whole_custody_refs"]
    require(type(custody) is dict and set(custody)=={"entry","controller","source_guard_owner"},"CATALOG_BEFORE_THREE_CUSTODY")
    for name,value in custody.items():
        require(value["sha256"]==old["runtime_source_refs"][name]["sha256"],"CATALOG_EXACT_OLD_R5_RUNTIME_WHOLE_BYTES")
        physical=pin(value)
        require(physical.is_relative_to((RUN/"source_corrections/POLICY_CATALOG_LIMITED1655_SOURCE_R6").resolve()),
            "CATALOG_SEPARATE_NEW_EPOCH_BEFORE_CUSTODY")
    return transition

def _catalog_source_current_bindings(c, data, old, prior, design_sources):
    require(data["design_ref"]==old["design_ref"] and data["original_sources"]==design_sources,
        "CATALOG_UNCHANGED_ORIGINAL99")
    _source_epoch_validate_runtime(data)
    role_pairs={"policy_catalog_source_metadata_r6":"policy_catalog_source_metadata_r6",
        "policy_catalog_nonexecuted_cold_r1":"policy_catalog_cold_r6",
        "policy_catalog_nonexecuted_firstentry_r1":"policy_catalog_firstentry_r6"}
    catalog_state=c._CATALOG_METADATA_SCOPE
    registry_state=c._REGISTRY_METADATA_SCOPE
    require(catalog_state is not None and registry_state is not None
        and registry_state.get("observation",{}).get("capture_stage")==role_pairs.get(catalog_state["capture_stage"]),
        "CATALOG_EXACT_REGISTRY_AND_CATALOG_ROLE_PAIR_REQUIRED")
    accounts,captures,controller=_source_epoch_transport_scope(c,old,prior)
    for logical,expected in design_sources.items():
        if Path(logical).resolve()==c._CATALOG_METADATA_PATH.resolve():
            binding=c._catalog_metadata_source_binding(logical,expected,design_sources)
            require(binding["purpose"]=="NONEXECUTED_CLOSURE_METADATA"
                and binding["old_physical_identity"]=="UNKNOWN"
                and binding["scientific_execution_admission"] is False,"CATALOG_METADATA_BINDING_ONLY")
        else:
            _source_epoch_original_binding(c,logical,expected,prior,accounts,captures,controller)

def _catalog_source_metadata_intent(c, annex_ref, design_sources, intent_ref):
    require(Path(__file__).resolve()==CONTROL_PATH.resolve(),"CANONICAL_CATALOG_METADATA_INTENT_OWNER")
    annex=c._catalog_metadata_authority(RUN,"policy_catalog_source_metadata_r6",annex_ref,design_sources)
    intent=catalog_source_read_control(intent_ref,"intent")
    require(set(intent)==CATALOG_SOURCE_FIELDS-{"status","independent_review_ref","catalog_nonexecuted_annex_ref"}
        and intent["schema"]==CATALOG_SOURCE_SCHEMA and intent["research_id"]==ID
        and digest(intent)==annex["source_intent_payload_sha256"]
        and intent["runtime_source_refs"]==annex["current_runtime_source_refs"],
        "CATALOG_REAL_SEVEN_FIELD_INTENT_REQUIRED")
    old,prior,original=_catalog_source_predecessor(annex["prior_R5_source_ref"])
    require(intent["prior_checkpoint_source_ref"]==annex["prior_R5_source_ref"]
        and intent["design_ref"]==old["design_ref"] and intent["original_sources"]==original
        and design_sources==original,"CATALOG_INTENT_PRIOR_SOURCE_AND99_LINK")
    _catalog_source_transition(intent,old)
    _source_epoch_validate_runtime(intent)
    c._catalog_metadata_approved_root_paths(annex,original)
    return intent,old,prior,original

def catalog_source_metadata_preflight(c, annex_ref, design_sources, intent_ref):
    """Call before either new registry or catalog slot is opened."""
    intent,old,prior,original=_catalog_source_metadata_intent(c,annex_ref,design_sources,intent_ref)
    return dict(source_intent_payload_sha256=digest(intent),intent_ref=dict(intent_ref),
        checked_before_capture=True,source_admission=False,phase_admission=False,science_admission=False)

def catalog_source_metadata_probe(c, annex_ref, design_sources, intent_ref):
    """Inside both scopes, verify actual bindings without activating main SOURCE."""
    intent,old,prior,original=_catalog_source_metadata_intent(c,annex_ref,design_sources,intent_ref)
    state=c._CATALOG_METADATA_SCOPE
    require(state is not None and state["capture_stage"]=="policy_catalog_source_metadata_r6"
        and state["authority_ref"]==annex_ref,"CATALOG_METADATA_PROBE_STAGE_ONLY")
    _catalog_source_current_bindings(c,intent,old,prior,original)
    return dict(status="PASS_CURRENT_AND_HISTORY_METADATA_PROBE_ONLY",
        source_intent_payload_sha256=digest(intent),intent_ref=dict(intent_ref),
        original99_sources_sha256=digest(original),catalog_capture_ref=dict(state["receipt_ref"]),
        source_admission=False,phase_admission=False,ledger_mutated=False,science_executed=False)

def validate_catalog_source_epoch(c, path, data):
    require(Path(__file__).resolve()==CONTROL_PATH.resolve()
        and Path(path).resolve()==(RUN/CATALOG_SOURCE_NAME).resolve(),"CANONICAL_NEW_CATALOG_SOURCE_ONLY")
    require(type(data) is dict and set(data)==CATALOG_SOURCE_FIELDS and data["schema"]==CATALOG_SOURCE_SCHEMA
        and data["status"]=="PASS" and data["research_id"]==ID,"CATALOG_CLOSED_NEW_MAIN_SOURCE")
    old,prior,design_sources=_catalog_source_predecessor(data["prior_checkpoint_source_ref"])
    _catalog_source_transition(data,old)
    state=c._CATALOG_METADATA_SCOPE
    require(state is not None and state["capture_stage"] in {
        "policy_catalog_nonexecuted_cold_r1","policy_catalog_nonexecuted_firstentry_r1"}
        and state["authority_ref"]==data["catalog_nonexecuted_annex_ref"],"CATALOG_MAIN_SOURCE_ONLY_COLD_OR_FIRSTENTRY")
    annex=c._catalog_metadata_authority(RUN,state["capture_stage"],data["catalog_nonexecuted_annex_ref"],design_sources)
    require(annex["source_intent_payload_sha256"]==digest(catalog_source_intent_payload(data))
        and annex["current_runtime_source_refs"]==data["runtime_source_refs"],"CATALOG_EXACT_SEVEN_FIELD_INTENT")
    _catalog_source_current_bindings(c,data,old,prior,design_sources)
    _catalog_source_main_review(c,data)
    return data

def _catalog_source_main_review(c,data):
    review=catalog_source_read_control(data["independent_review_ref"],"review")
    require(set(review)=={"schema","status","research_id","source_payload_sha256","checks",
            "historical_actual_old_catalog_bytes","grants_scientific_execution","actual_metadata_evidence_ref"}
        and review["schema"]=="FULL_SELECTOR_POLICY_CATALOG_LIMITED1655_SOURCE_INDEPENDENT_REVIEW_R6"
        and review["status"]=="PASS" and review["research_id"]==ID
        and review["source_payload_sha256"]==digest({k:v for k,v in data.items() if k not in {"status","independent_review_ref"}})
        and type(review["checks"]) is dict and set(review["checks"])==_CATALOG_SOURCE_REVIEW_CHECKS
        and all(v is True for v in review["checks"].values())
        and review["historical_actual_old_catalog_bytes"]=="UNKNOWN"
        and review["grants_scientific_execution"] is False,"CATALOG_NEW_FULL_MAIN_SOURCE_REVIEW_REQUIRED")
    _catalog_source_actual_metadata_evidence(c,data,review["actual_metadata_evidence_ref"])
    return data

def catalog_source_review_preflight(c, source_ref, annex_ref, intent_sha256):
    """Require actual main review before any cold/first-entry capture slot."""
    require(Path(__file__).resolve()==CONTROL_PATH.resolve(),"CANONICAL_CATALOG_PREFLIGHT_OWNER")
    data=catalog_source_read_control(source_ref,"source")
    require(set(data)==CATALOG_SOURCE_FIELDS and data["schema"]==CATALOG_SOURCE_SCHEMA
        and data["status"]=="PASS" and data["research_id"]==ID
        and data["catalog_nonexecuted_annex_ref"]==annex_ref
        and digest(catalog_source_intent_payload(data))==intent_sha256,"CATALOG_FULL_SOURCE_PREFLIGHT_BINDING")
    old,prior,design_sources=_catalog_source_predecessor(data["prior_checkpoint_source_ref"])
    _catalog_source_transition(data,old)
    _source_epoch_validate_runtime(data)
    _catalog_source_main_review(c,data)
    return dict(source_ref=dict(source_ref),source_intent_payload_sha256=intent_sha256,
        source_only_preflight=True,phase_admission=False,science_admission=False)

def _catalog_source_actual_metadata_evidence(c,data,evidence_ref):
    evidence=catalog_source_read_control(evidence_ref,"metadata_evidence")
    fields={"schema","status","research_id","actual","synthetic","intent_ref","source_intent_payload_sha256",
        "annex_ref","current_runtime_source_refs","original99_sources_sha256","prior_R5_source_ref",
        "registry_capture_ref","catalog_capture_ref","source_admission","phase_admission","science_executed"}
    require(set(evidence)==fields and evidence["schema"]=="FULL_SELECTOR_POLICY_CATALOG_ACTUAL_SOURCE_METADATA_PROBE_R6"
        and evidence["status"]=="PASS_CURRENT_AND_HISTORY_METADATA_PROBE_ONLY" and evidence["research_id"]==ID
        and evidence["actual"] is True and evidence["synthetic"] is False
        and evidence["source_admission"] is False and evidence["phase_admission"] is False
        and evidence["science_executed"] is False
        and evidence["source_intent_payload_sha256"]==digest(catalog_source_intent_payload(data))
        and evidence["annex_ref"]==data["catalog_nonexecuted_annex_ref"]
        and evidence["current_runtime_source_refs"]==data["runtime_source_refs"]
        and evidence["original99_sources_sha256"]==digest(data["original_sources"])
        and evidence["prior_R5_source_ref"]==data["prior_checkpoint_source_ref"],
        "CATALOG_ACTUAL_SOURCE_METADATA_EVIDENCE_BINDING")
    intent=catalog_source_read_control(evidence["intent_ref"],"intent")
    require(intent==catalog_source_intent_payload(data),"CATALOG_ACTUAL_CAPTURE_SAME_INTENT")
    annex=catalog_source_read_control(evidence["annex_ref"],"annex")
    registry=catalog_source_read_control(evidence["registry_capture_ref"],"metadata_registry_capture")
    capture=catalog_source_read_control(evidence["catalog_capture_ref"],"metadata_catalog_capture")
    require(registry.get("run")==str(RUN.resolve())
        and registry.get("capture_stage")=="policy_catalog_source_metadata_r6"
        and type(registry.get("entries")) is dict and set(registry["entries"])=={"registry","stateful_fusion"}
        and registry.get("capture_policy",{}).get("scientific_source_acceptance") is False,
        "CATALOG_ACTUAL_PRIOR_TWO_METADATA_CAPTURE_REQUIRED")
    require(capture.get("schema")=="FIXED214_CATALOG_NONEXECUTED_CLOSURE_CAPTURE_R1"
        and capture.get("run")==str(RUN.resolve()) and capture.get("capture_stage")=="policy_catalog_source_metadata_r6"
        and capture.get("authority_ref")==data["catalog_nonexecuted_annex_ref"]
        and capture.get("policy")==annex["nonexecuted_capture_policy"]
        and capture.get("original99_sources_sha256")==digest(data["original_sources"])
        and capture.get("original_logical_ref")==annex["catalog_original_ref"]
        and capture.get("source_execution_authorized") is False
        and capture.get("full_SOURCE_phase_admission_still_required") is True
        and capture.get("historical_actual_old_catalog_bytes")=="UNKNOWN",
        "CATALOG_ACTUAL_FIXED_METADATA_STAGE_RECEIPT_REQUIRED")
    require(registry.get("schema")==c._REGISTRY_CAPTURE_SCHEMA
        and registry["capture_policy"]==c._registry_metadata_capture_policy(),
        "CATALOG_ACTUAL_ORIGINAL_TWO_SCHEMA_AND_POLICY")
    fixed={
        "registry":(c._REGISTRY_METADATA_PATH,c._REGISTRY_METADATA_OLD_SHA),
        "stateful_fusion":(c._STATEFUL_FUSION_METADATA_PATH,c._STATEFUL_FUSION_METADATA_OLD_SHA)}
    for name,(logical,oldsha) in fixed.items():
        entry=registry["entries"][name]
        require(type(entry) is dict and set(entry)=={"original_logical_ref","observed_live_ref","custody_ref","bytes",
            "captured_utc","exact_at_capture","current_after_capture_unknown","source_purpose",
            "source_execution_authorized","original_actual_bytes_status"}
            and entry["original_logical_ref"]==dict(path=str(logical),sha256=oldsha)
            and data["original_sources"][str(logical)]==oldsha
            and entry["observed_live_ref"]==dict(path=str(logical),sha256=entry["custody_ref"]["sha256"])
            and entry["exact_at_capture"] is True and entry["current_after_capture_unknown"] is True
            and entry["source_purpose"]=="NONEXECUTED_IMPORT_CLOSURE_METADATA"
            and entry["source_execution_authorized"] is False
            and entry["original_actual_bytes_status"]=="UNKNOWN_ACTUAL_OLD_BYTES_NOT_FOUND"
            and type(entry["captured_utc"]) is str,"CATALOG_ACTUAL_TWO_COMPLETE_BINDINGS")
        datetime.fromisoformat(entry["captured_utc"].replace("Z","+00:00"))
        custody=RUN/"maintenance"/("FIXED214_POLICY_CATALOG_SOURCE_METADATA_R6_PRIOR_TWO_CAPTURE."+name+".opaque-source")
        _catalog_source_pin_fixed_opaque(entry["custody_ref"],custody,entry["bytes"],1048576)
    require(capture["observed_live_ref"]==dict(path=str(c._CATALOG_METADATA_PATH),sha256=capture["custody_ref"]["sha256"])
        and capture["original_logical_ref"]==dict(path=str(c._CATALOG_METADATA_PATH),sha256=c._CATALOG_METADATA_OLD_SHA)
        and data["original_sources"][str(c._CATALOG_METADATA_PATH)]==c._CATALOG_METADATA_OLD_SHA,
        "CATALOG_ACTUAL_THIRD_COMPLETE_BINDING")
    _catalog_source_pin_fixed_opaque(capture["custody_ref"],
        RUN/"maintenance/FIXED214_POLICY_CATALOG_SOURCE_METADATA_R6_NONEXECUTED_CAPTURE.catalog.opaque-source",
        capture["bytes"],32768)
    return evidence


CATALOG_LIMITED_PHASE = "post-risk-policy-catalog-limited1655-first-r6"
CATALOG_LIMITED_NAME = "POST_RISK_POLICY_CATALOG_LIMITED1655_FIRST_R6"
CATALOG_LIMITED_ADMIN_ACTION = "ENGINEERING_ZERO_ENTRY_RESTORED"

def _catalog_limited1655_entry_gate(c, cfg):
    """Re-enter the pinned actual entry's gate while it holds the original lock."""
    import types
    require(Path(__file__).resolve()==CONTROL_PATH.resolve()
        and c._CATALOG_METADATA_SCOPE is not None
        and c._CATALOG_METADATA_SCOPE["capture_stage"]=="policy_catalog_nonexecuted_firstentry_r1"
        and c._ENGINEERING_SOURCE_CONFIGURATION is not None,"CATALOG_RESTORE_INSIDE_ACTUAL_FIRSTENTRY_SOURCE_SCOPE")
    pin(cfg["runtime_entry_ref"],RUNTIME_PATHS["entry"])
    candidates=[sys.modules.get("__main__"),sys.modules.get("scripts.research.a2.training.full_selector_engineering_continuation")]
    owners=[m for m in candidates if type(m) is types.ModuleType
        and Path(vars(m).get("__file__","")).resolve()==RUNTIME_PATHS["entry"].resolve()
        and vars(m).get("_RISK_ACTIVE_CONTROLLER") is c
        and vars(m).get("_CATALOG_ORIGINAL_LOCK_HELD") is True]
    require(len({id(m) for m in owners})==1,"CATALOG_ORIGINAL_WORKER_LOCK_ENTRY_WITNESS")
    entry=owners[0];gate=vars(entry).get("policy_catalog_load_authority")
    require(type(gate) is types.FunctionType and Path(gate.__code__.co_filename).resolve()==RUNTIME_PATHS["entry"].resolve(),
        "CATALOG_CANONICAL_FULL_PHASE_GATE_FUNCTION")
    source=c._source_correction(cfg["source_configuration_ref"])
    state=c._ENGINEERING_SOURCE_CONFIGURATION
    require(type(state) is dict and set(state)=={"ref","payload_sha256"}
        and state["ref"]==cfg["source_configuration_ref"] and state["payload_sha256"]==digest(source),
        "CATALOG_SAME_ACTIVE_REVIEWED_SOURCE_SCOPE")
    review,admission_ref,root_ref=gate(RUN,cfg)
    require(Path(admission_ref["path"]).resolve()==(RUN/"continuation"/(CATALOG_LIMITED_NAME+"_ACCEPTANCE.json")).resolve()
        and Path(root_ref["path"]).resolve()==(RUN/"maintenance/POLICY_CATALOG_LIMITED1655_ROOT_LAST_ACTUAL_PHASE_ADMISSION_R6.json").resolve(),
        "CATALOG_EXACT_NEW_PHASE_AND_ROOT_LAST_REFS")
    return admission_ref,root_ref

def _catalog_limited1655_admin_record(row, admission_ref, root_ref, human_scope):
    return dict(schema="CATALOG_ORIGINAL1655_LIMITED_SECOND_ADMIN_RECORD_R6",generation=2,
        node_id=row[0],kind=row[1],prior_row_sha256=digest(row),
        prior_status="BLOCKED_DEPENDENCY",new_status="NAMED",
        prior_error_sha256=_CATALOG_LIMITED_ERROR_SHA_R6,
        phase_admission_ref=dict(admission_ref),root_last_ref=dict(root_ref),
        human_authorization_ref=dict(human_scope["human_authorization_ref"]),
        transcript_clarification_ref=dict(human_scope["transcript_clarification_ref"]),
        target_ids_sha256=_CATALOG_LIMITED_TARGET_DIGEST_R6,
        original_prefix_event_count=50215,original_prefix_sha256=_CATALOG_LIMITED_PRESTATE_R6["events_sha256"],
        original_nodes_sha256=_CATALOG_LIMITED_PRESTATE_R6["nodes_sha256"],
        actual_backend_entries=0,budget_charge_delta=0,identity_generated=False,artifact_created=False)

def catalog_limited1655_restore_transaction(c, db, cfg, original_ids, pending1664, human_scope, utc):
    """Only this approved second generation; validate real phase before any SQL."""
    admission_ref,root_ref=_catalog_limited1655_entry_gate(c,cfg)
    require(type(utc) is str and utc.endswith("Z"),"CATALOG_ADMIN_EXPLICIT_UTC")
    stamp=datetime.fromisoformat(utc.replace("Z","+00:00"))
    require(stamp.utcoffset().total_seconds()==0,"CATALOG_ADMIN_UTC_ZERO_OFFSET")
    require(not db.in_transaction,"CATALOG_ADMIN_SEPARATE_TRANSACTION")
    targets=human_scope["original_node_ids"];target_set=set(targets)
    db.execute("BEGIN IMMEDIATE")
    try:
        rows=db.execute("SELECT node_id,kind,status,entered,identity,artifact,error FROM nodes ORDER BY node_id").fetchall()
        events=db.execute("SELECT sequence,node_id,action,payload,utc FROM events ORDER BY sequence").fetchall()
        authority=db.execute("SELECT design_sha256 FROM authority ORDER BY design_sha256").fetchall()
        require(authority==[("20a855c2bf4df41b1e84fbc8159a473a04a575ccfb5ba76ed819d1975bcb8359",)],
            "CATALOG_ADMIN_SOLE_UNCHANGED_ORIGINAL_AUTHORITY")
        plan=catalog_limited1655_plan(rows,events,original_ids,pending1664,human_scope)
        by_id={row[0]:row for row in rows};expected_suffix=[]
        require(events[-1][0]==50215,"CATALOG_ADMIN_EXACT_ACCEPTED_EVENT_SEQUENCE")
        for sequence,node in enumerate(targets,50216):
            row=by_id[node]
            changed=db.execute("UPDATE nodes SET status='NAMED',error=NULL WHERE node_id=? AND kind=? "
                "AND status='BLOCKED_DEPENDENCY' AND entered=0 AND identity IS NULL AND artifact IS NULL AND error=?",
                (node,row[1],row[6])).rowcount
            require(changed==1,"CATALOG_ADMIN_EXACT_TARGET_CAS")
            record=_catalog_limited1655_admin_record(row,admission_ref,root_ref,human_scope)
            encoded=json.dumps(record,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)
            db.execute("INSERT INTO events(node_id,action,payload,utc) VALUES (?,?,?,?)",
                (node,CATALOG_LIMITED_ADMIN_ACTION,encoded,utc))
            expected_suffix.append((sequence,node,CATALOG_LIMITED_ADMIN_ACTION,encoded,utc))
        after=db.execute("SELECT node_id,kind,status,entered,identity,artifact,error FROM nodes ORDER BY node_id").fetchall()
        after_events=db.execute("SELECT sequence,node_id,action,payload,utc FROM events ORDER BY sequence").fetchall()
        expected_rows=[(r[0],r[1],"NAMED",0,None,None,None) if r[0] in target_set else r for r in rows]
        require(after==expected_rows,"CATALOG_ADMIN_ONLY1655_PRISTINE_ROW_TRANSITIONS")
        require(after_events[:len(events)]==events and after_events[len(events):]==expected_suffix,
            "CATALOG_ADMIN_ENTIRE50215_PREFIX_AND_FULL1655_RECORDS_EXACT")
        require(db.execute("SELECT design_sha256 FROM authority ORDER BY design_sha256").fetchall()==authority,
            "CATALOG_ADMIN_ORIGINAL_AUTHORITY_UNCHANGED")
        # No filesystem receipt in this atomic transaction. A later receipt failure
        # must retain the committed state and must never re-run this restoration.
        c._source_correction(cfg["source_configuration_ref"])
        db.commit()
        return dict(schema="CATALOG_ORIGINAL1655_SECOND_ADMIN_TRANSACTION_RESULT_R6",
            phase_admission_ref=admission_ref,root_last_ref=root_ref,restored_at_utc=utc,
            restored_original_ids=1655,target_ids_sha256=digest(targets),generation=2,
            original_event_count=50215,administrative_event_count=1655,post_ADMIN_event_count=51870,
            before_nodes_sha256=digest(rows),after_nodes_sha256=digest(after),
            original_events_sha256=digest(events),post_ADMIN_events_sha256=digest(after_events),
            actual_backend_entries=0,budget_charge_delta=0,scientific_retries=0,
            source_or_phase_admission=False)
    except BaseException:
        db.rollback()
        raise

def catalog_limited1655_history(before_rows,before_events,after_rows,after_events,
        original_ids,pending1664,human_scope,admission_ref,root_ref,restored_at_utc):
    """Three explicit segments: accepted R5, generation2 ADMIN, original once."""
    catalog_limited1655_plan(before_rows,before_events,original_ids,pending1664,human_scope)
    before={r[0]:r for r in before_rows};after={r[0]:r for r in after_rows}
    targets=human_scope["original_node_ids"];target_set=set(targets)
    require(len(after)==len(after_rows) and before.keys()==after.keys(),"CATALOG_HISTORY_UNCHANGED_NAMESPACE")
    require(all(after[n]==before[n] for n in before.keys()-target_set),
        "CATALOG_HISTORY_ALL_PAID3_OTHER6_FAILED_AND_ALL_NON_TARGET_ROWS_EXACT")
    require(after_events[:50215]==before_events,"CATALOG_HISTORY_GENUINE50215_PREFIX_EXACT")
    suffix=after_events[50215:]
    require(len(suffix)>=1655 and [e[0] for e in suffix]==list(range(50216,50216+len(suffix))),
        "CATALOG_HISTORY_CONTIGUOUS_GENERATION2_AND_ONCE_SUFFIX")
    for node,event in zip(targets,suffix[:1655]):
        record=_catalog_limited1655_admin_record(before[node],admission_ref,root_ref,human_scope)
        encoded=json.dumps(record,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)
        require(event[1:]==(node,CATALOG_LIMITED_ADMIN_ACTION,encoded,restored_at_utc),
            "CATALOG_HISTORY_FULL_SECOND_ADMIN_RECORD_AND_GIVEN_UTC")
    chains={n:[] for n in targets}
    for event in suffix[1655:]:
        require(event[1] in target_set and event[2] in {"BEGIN","BACKEND_ENTER","COMPLETE","FAILED","BLOCKED_DEPENDENCY"},
            "CATALOG_HISTORY_ONLY_ORIGINAL1655_ONCE_NO_THIRD_ADMIN_OR_ENV_REENTER")
        chains[event[1]].append(event)
    counts=Counter()
    for node,chain in chains.items():
        require(type(after[node][3]) is int,"CATALOG_HISTORY_EXACT_ENTERED_INTEGER")
        counts[_source_original_once_row_history(node,chain,before,after)]+=1
    return dict(status="PASS_LIMITED1655_GENERATION2_METADATA_HISTORY_ONLY",counts=dict(counts),
        original50215_prefix_preserved=True,all_non_target_rows_preserved=True,
        original_unchanged_once_chain_predicate_reused=True,second_ADMIN_events=1655,
        third_ADMIN_events=0,administrative_charge_delta=0,scientific_retries=0)

def validate_catalog_actual_cold_native(osr,cold,review,cfg,root_terminal_ref):
    result=_validate_actual_cold_native_profile(osr,cold,review,cfg,root_terminal_ref,
        RUN/"maintenance/POLICY_CATALOG_LIMITED1655_COLD_ACTUAL_LAUNCH_R6.json",
        RUN/"maintenance/POLICY_CATALOG_LIMITED1655_ACTUAL_SOURCE_INSTALLATION_R6.json",
        RUN/"maintenance/POLICY_CATALOG_LIMITED1655_ACTUAL_COLD_ROOT_TERMINAL_R6.json",
        "post-risk-policy-catalog-limited1655-cold-r6",control_reader=_catalog_actual_cold_read_control)
    terminal=catalog_source_read_control(root_terminal_ref,"actual_cold_root")
    identity=catalog_source_read_control(terminal["native_birth_identity_ref"],"actual_cold_identity")
    require(set(identity)=={"schema","status","launch_ref","before_process_levels","native_identities","api_errors"}
        and identity["schema"]=="CATALOG_LIMITED1655_ACTUAL_COLD_NATIVE_BIRTH_IDENTITY_R6"
        and identity["status"]=="EXACT_NATIVE_FILETIME_IDENTITIES_OBSERVED"
        and identity["launch_ref"]==osr["launch_ref"] and identity["before_process_levels"]==osr["before_process_levels"]
        and identity["api_errors"]==[] and type(identity["native_identities"]) is list
        and len(identity["native_identities"])==2,"CATALOG_ACTUAL_COLD_EXACT_NATIVE_BIRTH_EVIDENCE")
    from datetime import timedelta,timezone
    for level,native in zip(osr["before_process_levels"],identity["native_identities"]):
        require(set(native)=={"pid","creation_filetime","creation_utc"}
            and type(native["pid"]) is int and native["pid"]==level["pid"]
            and type(native["creation_filetime"]) is int and native["creation_filetime"]>0,
            "CATALOG_ACTUAL_COLD_FILETIME_INTEGER")
        seconds,fraction=divmod(native["creation_filetime"],10000000)
        base=datetime(1601,1,1,tzinfo=timezone.utc)+timedelta(seconds=seconds)
        exact=base.strftime("%Y-%m-%dT%H:%M:%S")+"."+format(fraction,"07d")+"Z"
        require(native["creation_utc"]==level["creation_utc"]==exact,"CATALOG_ACTUAL_COLD_EXACT_100NS_UTC_NO_TOLERANCE")
    observation=catalog_source_read_control(terminal["process_observation_ref"],"actual_cold_observation")
    require(observation.get("native_birth_identity_ref")==terminal["native_birth_identity_ref"]
        and observation.get("original_native_births_gone") is True,
        "CATALOG_ACTUAL_COLD_BOTH_PRECISE_NATIVE_BIRTHS_GONE")
    return dict(result,native_100ns_births_exact=True,original_native_births_gone=True)

def _catalog_source_pin_fixed_opaque(ref, expected_path, expected_bytes, cap):
    """Hash exact fixed custody bytes in bounded chunks; never decode/execute."""
    import os,stat
    require(type(ref) is dict and set(ref)=={"path","sha256"}
        and Path(ref["path"]).resolve()==expected_path.resolve()
        and type(ref["sha256"]) is str and len(ref["sha256"])==64
        and all(ch in "0123456789abcdef" for ch in ref["sha256"])
        and type(expected_bytes) is int and 0<expected_bytes<=cap,"CATALOG_CLOSED_FIXED_OPAQUE_REF")
    checksum=hashlib.sha256()
    with expected_path.open("rb") as handle:
        before=os.fstat(handle.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_size==expected_bytes,
            "CATALOG_FIXED_OPAQUE_SIZE_BEFORE_READ")
        remaining=expected_bytes
        while remaining:
            chunk=handle.read(min(65536,remaining))
            require(bool(chunk),"CATALOG_FIXED_OPAQUE_TRUNCATED")
            remaining-=len(chunk);checksum.update(chunk)
        after=os.fstat(handle.fileno())
        require(tuple(getattr(before,k) for k in ("st_size","st_mtime_ns","st_ino","st_dev"))==
            tuple(getattr(after,k) for k in ("st_size","st_mtime_ns","st_ino","st_dev")),
            "CATALOG_FIXED_OPAQUE_HANDLE_CHANGED")
    require(checksum.hexdigest()==ref["sha256"],"CATALOG_FIXED_OPAQUE_HASH_CHANGED")
    return expected_path

def _catalog_finite_control_float(token):
    """Preserve normal JSON float parsing; reject exponent overflow to infinity."""
    import math
    value=float(token)
    require(math.isfinite(value),"CATALOG_NONFINITE_CONTROL_NUMBER")
    return value


def _catalog_actual_cold_read_control(value, expected=None):
    """Only four exact new cold chain slots, including reads inside shared strict20."""
    require(type(value) is dict and set(value)=={"path","sha256"},"CATALOG_CLOSED_COLD_CHAIN_REF")
    physical=Path(value["path"]).resolve()
    if expected is not None:
        require(physical==Path(expected).resolve(),"CATALOG_EXACT_COLD_CHAIN_EXPECTED_PATH")
    matches=[name for name in ("actual_cold_launch","actual_cold_installation","actual_cold_root","actual_cold_observation")
        if physical==_CATALOG_CONTROL_FILES[name][0].resolve()]
    require(len(matches)==1,"CATALOG_FIXED_COLD_CHAIN_CONTROL_PATH")
    return catalog_source_read_control(value,matches[0])
