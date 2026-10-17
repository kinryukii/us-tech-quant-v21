"""One bounded C13 successful-output reconstruction; frozen business code reused.

The original 115 successful output hashes authorize identity-checked arithmetic
reconstruction only. Every extra physical solve is charged; no FAILED slot retry,
new fit, Y access, algorithm/parameter change or original-file overwrite.
"""
from __future__ import annotations
import ast, copy, hashlib, inspect, json, os
from pathlib import Path
from scripts.research.a2.training import selector_constrained_risk as c
from scripts.research.a2.risk.shared_risk_budget_r2 import StateBudget, content_hash

class ReconstructionMismatch(BaseException):pass


def successful_prefix(events,dag):
    latest={}
    for event in events:latest[event['key']]=event
    expected=dag['nodes'][:115]
    if (set(latest)!={n['id'] for n in expected} or len(expected)!=115
        or any(n['candidate_id']!='C13_R06_D02' for n in expected)):
        raise ValueError('ONLY_EXACT_FIRST115_SUCCESSFUL_PREFIX')
    for n in expected:
        e=latest[n['id']]
        if (e['status']!='SUCCEEDED' or e.get('backend_entered') is not True
            or e['inputs_sha256']!=n['artifact']['sha256'] or not e.get('result_sha256')):
            raise ValueError('SUCCESSFUL_BOUND_OUTPUT_HASH_REQUIRED_NO_FAILED_RETRY')
    return [copy.deepcopy(latest[n['id']]) for n in expected]


def identical_output(out,event):
    got=content_hash(out)
    if got!=event['result_sha256']:raise ReconstructionMismatch('BLOCKED_OUTPUT_IDENTITY:'+event['key'])
    return got


def durable(path,event):
    c.assert_safe_output_path(path,kind='backtest')
    with path.open('a',encoding='utf-8') as stream:
        stream.write(json.dumps(event,default=str,allow_nan=False)+'\n');stream.flush();os.fsync(stream.fileno())


def physical_accounting(ledger,snap,verified):
    actual=int(ledger['actual_solver_calls'])
    extra_actual=sum(e.get('backend_entered',False) for e in snap['events'])
    if (len(ledger['events'])!=3708 or not 115<=actual<=3708
        or len(snap['events'])!=115 or extra_actual!=115 or verified!=115
        or any(e['status']!='SUCCEEDED' for e in snap['events'])):
        raise ValueError('EXACT_RESERVATIONS_VERIFIED_RECONSTRUCTION_REQUIRED')
    return dict(scientific_unique_slots=3708,scientific_physical_calls=actual,
        original_scientific_solve_reservations=3708,
        additional_reconstruction_physical_calls=extra_actual,
        additional_charged_reservations=115,total_physical_charged_reservations=3823,
        total_physical_solver_calls=actual+extra_actual,physical_solver_ceiling=3823,hard_cap=12000)


def reviewed_report(root,appendix,physical):
    _,results,_=c.paths(root);original=root/'DELIVERY_COMPLETE.json'
    marker=c.readj(original);report=c.pin(marker['report']);text=report.read_text(encoding='utf-8')
    prior=f"12. **optimizer实际solve**：{physical['scientific_physical_calls']}；charged solve reservation=3708"
    replacement=f"12. **optimizer实际solve**：{physical['total_physical_solver_calls']}（原科学槽实际{physical['scientific_physical_calls']} + 115次成功结果哈希恒等工程恢复）；charged scientific reservation=3708，额外工程physical reservation=115"
    if prior not in text:raise ValueError('EXACT_REPORT_COUNT_FACT_REQUIRED')
    text=text.replace(prior,replacement)
    text+='\n\n## 工程恢复事实审校\n\n首批115次求解已成功，随后因本run的predictions目录未初始化，输出写入失败；原日志与成功结果SHA保留。1次有界工程恢复初始化输出目录，按相同源码、状态artifact、UID、日期与参数重建115个成功输出，每个content_hash都与原日志完全一致。没有重试FAILED科学槽，没有读取收益后修改规则，没有新增拟合。\n\n原3708科学DAG和正式DESIGN不变；实际physical调用'+str(physical['total_physical_solver_calls'])+'；charged reservation和恢复后调用上界均为3823，包含115次额外工程重建，全部占用预算，低于原12000硬上限。科学retry=0，工程恢复事件=1。原FINAL_REPORT和DELIVERY_COMPLETE字节保留，本Reviewed报告只补计数与故障事实。\n\n工程证据：[ENGINEERING_RECOVERY_APPENDIX]('+str(root/'ENGINEERING_RECOVERY_APPENDIX.json')+')；[ACTUAL_PHYSICAL_SOLVE_SUMMARY]('+str(root/'ACTUAL_PHYSICAL_SOLVE_SUMMARY.json')+')。\n'
    dest=results/'FINAL_REPORT_REVIEWED.md'
    if dest.exists():raise FileExistsError('PRESERVE_REVIEWED_REPORT')
    dest.write_text(text,encoding='utf-8')
    receipt=dict(status=marker['status'],research_id=c.ID,original_delivery=c.ref(original),original_report=marker['report'],
        reviewed_report=c.ref(dest),engineering_appendix=c.ref(root/'ENGINEERING_RECOVERY_APPENDIX.json'),
        actual_physical_solves=c.ref(root/'ACTUAL_PHYSICAL_SOLVE_SUMMARY.json'),
        scientific_solves=physical['scientific_physical_calls'],scientific_reservations=3708,
        additional_reconstruction_solves=115,total_physical_solves=physical['total_physical_solver_calls'],physical_solver_ceiling=3823,
        source_design_unchanged=True,scientific_retry=0,engineering_recovery_events=1,
        new_learned_states=0,strict_PIT_promotion_eligible=False,test2026_locked=True)
    c.put(results/'REVIEWED_DELIVERY_COMPLETE.json',receipt)
    return receipt


def run(root=c.RUN):
    root,results,_,design=c.checked(root)
    if (root/'ENGINEERING_RECOVERY_START.json').exists():raise FileExistsError('ONE_RECOVERY_ONLY')
    if (root/'SOLVE_LEDGER.json').exists() or (root/'FINAL_DECISIONS_FREEZE.json').exists():raise ValueError('ONLY_PRE_OUTPUT_FAILURE_RECOVERY')
    baseline=root/'logs/optimizer_calls.jsonl';original_log_ref=c.ref(baseline)
    events=[json.loads(line) for line in baseline.read_text(encoding='utf-8').splitlines()]
    dag=c.readj(c.pin(design['physical_dag']));prefix=successful_prefix(events,dag);prior={e['key']:e for e in prefix}
    source_ref=c.ref(Path(__file__))
    audit_path=results/'ENGINEERING_RECOVERY_INDEPENDENT_AUDIT.json';audit=c.readj(audit_path)
    if (audit.get('status')!='PASS' or audit.get('recovery_source',{}).get('sha256')!=source_ref['sha256']
        or audit.get('design_sha256')!=c.sha(root/'DESIGN_FREEZE.json')
        or audit.get('original_success_journal_sha256')!=original_log_ref['sha256']):
        raise ValueError('EXACT_INDEPENDENT_ENGINEERING_AUDIT_REQUIRED_BEFORE_CALLS')
    source=inspect.getsource(c.execute)
    tree=ast.parse(source);function=tree.body[0]
    # Only the single-launch guard and journal filename differ. All original
    # selection, source checks, assembly, terminal gate, evaluation and delivery
    # statements execute from the pinned original controller, without copying them.
    function.body=[n for n in function.body if 'EXECUTION_START.json' not in ast.unparse(n)]
    function.body.insert(1,ast.Expr(ast.Call(ast.Name('_engineering_start',ast.Load()),[ast.Name('root',ast.Load())],[])))
    class JournalName(ast.NodeTransformer):
        def visit_Constant(self,node):
            if node.value=='logs/optimizer_calls.jsonl':return ast.copy_location(ast.Constant('logs/optimizer_calls_resume1.jsonl'),node)
            return node
    tree=JournalName().visit(tree);ast.fix_missing_locations(tree)
    patch_sha=hashlib.sha256(ast.dump(tree,include_attributes=False).encode()).hexdigest()
    appendix=dict(status='AUTHORIZED_BOUNDED_ENGINEERING_RECONSTRUCTION',research_id=c.ID,
        original_design=c.ref(root/'DESIGN_FREEZE.json'),original_controller=c.ref(c.__file__),original_success_journal=original_log_ref,
        original_error_log=c.ref(root/'logs/training.stderr.log'),recovery_source=source_ref,patched_AST_sha256=patch_sha,
        original_physical_dag=design['physical_dag'],original_successful_node_ids=list(prior),independent_engineering_audit=c.ref(audit_path),
        source_parameters_unchanged=True,algorithm_unchanged=True,scientific_retry=0,engineering_recovery_limit=1,
        extra_physical_nodes=[dict(id=k+'@OUTPUT_RECONSTRUCTION1',original_scientific_id=k,expected_output_sha256=e['result_sha256']) for k,e in prior.items()],
        original_scientific_solve_slots=3708,additional_reconstruction_ceiling=115,total_physical_ceiling=3823,original_solve_hard_cap=12000,
        failure_policy='Hash mismatch aborts before Y; no output acceptance; no second reconstruction',outcome_reads=0,new_fits=0,new_state_estimations=0)
    c.put(root/'ENGINEERING_RECOVERY_APPENDIX.json',appendix)
    extra=StateBudget(0,limits={'deterministic_transform':115},reserve_callback=lambda e:durable(root/'logs/engineering_reconstruction.jsonl',e))
    active={'key':None};verified={};physical_extra={};original_select=c.rules.select;original_gate=c.decision_gate
    class RestoredBudget(StateBudget):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            self.events=copy.deepcopy(prefix);self._keys=set(prior);self.counts['deterministic_transform']=len(prefix);self.reconstructed=set()
        def reserve(self,key,kind,name,context,inputs_sha256,parameters):
            active['key']=key
            if key not in prior:return super().reserve(key,kind,name,context,inputs_sha256,parameters)
            if key in self.reconstructed:raise ValueError('ONE_RECONSTRUCTION_PER_SUCCESS')
            old=prior[key]
            if (kind!=old['kind'] or name!=old['name'] or context!=old['context']
                or inputs_sha256!=old['inputs_sha256'] or parameters!=old['parameters']):
                raise ReconstructionMismatch('RECONSTRUCTION_INPUT_IDENTITY_CHANGED')
            self.reconstructed.add(key)
            physical_extra[key]=extra.reserve(key+'@OUTPUT_RECONSTRUCTION1',kind,name,
                {**context,'engineering_reconstruction':True},inputs_sha256,parameters)
            return next(e for e in self.events if e['key']==key)
    def guarded_select(*args,**kwargs):
        key=active['key'];event=physical_extra.get(key)
        if event is not None:
            event['backend_entered']=True;durable(root/'logs/engineering_reconstruction.jsonl',event)
        out=original_select(*args,**kwargs)
        if key in prior:
            digest=identical_output(out,prior[key]);verified[key]=digest
            event.update(status='SUCCEEDED',result_sha256=digest,original_result_sha256=prior[key]['result_sha256'],hash_identical=True)
            durable(root/'logs/engineering_reconstruction.jsonl',event)
        return out
    def engineering_start(path):
        for name in ('predictions','derived','diagnostics','logs'):
            dest=path/name;c.assert_safe_output_path(dest,kind='backtest');dest.mkdir(parents=True,exist_ok=True)
        c.put(path/'ENGINEERING_RECOVERY_START.json',dict(research_id=c.ID,at=c.now(),pid=os.getpid(),appendix=c.ref(path/'ENGINEERING_RECOVERY_APPENDIX.json')))
    def guarded_gate(path,d,assembly,ledger,requested):
        if set(verified)!=set(prior) or any(e['status']!='SUCCEEDED' for e in extra.events):raise ReconstructionMismatch('RECONSTRUCTION_NOT_ALL_IDENTICAL_NO_Y')
        snap=extra.snapshot();c.put(path/'ENGINEERING_RECONSTRUCTION_LEDGER.json',snap)
        physical=dict(research_id=c.ID,**physical_accounting(ledger,snap,len(verified)),
            scientific_retry=0,engineering_recovery_events=1,verified_original_success_outputs=len(verified),all_hash_identical=True,
            new_learned_states=0,new_state_estimations=0,outcome_reads_before_gate=0,
            original_success_journal=original_log_ref,reconstruction_ledger=c.ref(path/'ENGINEERING_RECONSTRUCTION_LEDGER.json'))
        c.put(path/'ACTUAL_PHYSICAL_SOLVE_SUMMARY.json',physical)
        gate=original_gate(path,d,assembly,ledger,requested)
        gate['engineering_recovery_appendix']=c.ref(path/'ENGINEERING_RECOVERY_APPENDIX.json');gate['actual_physical_solves']=c.ref(path/'ACTUAL_PHYSICAL_SOLVE_SUMMARY.json')
        return gate
    c.StateBudget=RestoredBudget;c.rules.select=guarded_select;c.decision_gate=guarded_gate;c.__dict__['_engineering_start']=engineering_start
    exec(compile(tree,'C13_FROZEN_EXECUTE_BOUNDED_ENGINEERING_RECOVERY','exec'),c.__dict__)
    c.execute(root)
    if c.sha(baseline)!=original_log_ref['sha256']:raise ValueError('ORIGINAL_JOURNAL_CHANGED')
    return reviewed_report(root,appendix,c.readj(root/'ACTUAL_PHYSICAL_SOLVE_SUMMARY.json'))

if __name__=='__main__':run()