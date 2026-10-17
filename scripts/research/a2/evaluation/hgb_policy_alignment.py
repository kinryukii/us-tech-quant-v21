"""Fixed user-specified HGB risk-policy alignment; reuse frozen models and replay."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.portfolio import selected_hgb as selected
from scripts.research.a2.evaluation import three_strategy_extension as extension

TASK_ID = 'hgb_direct_risk_alignment_20261004_r1'
SOURCE_FILES = (
    'scripts/research/a2/portfolio/selected_hgb.py',
    'scripts/research/a2/evaluation/three_strategy_extension.py',
    'scripts/research/a2/evaluation/hgb_policy_alignment.py',
    'scripts/research/a2/evaluation/selected_performance_update.py',
    'scripts/daily_recommendation.py',
    'apps/demo_console/adapters/selected_strategies_reader.py',
    'apps/moomoo_trading_component/moomoo_component/applied_source.py',
)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    path = Path(path)
    assert_safe_output_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def record_path(paths):
    return paths.results_root/'_maintenance'/TASK_ID/'task_record.json'


def peak_working_set():
    # Windows process high-water mark, without installing monitoring packages.
    try:
        import ctypes
        from ctypes import wintypes
        class Memory(ctypes.Structure):
            _fields_ = [('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD),
                        *[(n,ctypes.c_size_t) for n in ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]]
        info=Memory(); info.cb=ctypes.sizeof(info)
        kernel=ctypes.WinDLL('kernel32'); kernel.GetCurrentProcess.restype=wintypes.HANDLE
        get_info=ctypes.WinDLL('psapi').GetProcessMemoryInfo
        get_info.argtypes=(wintypes.HANDLE,ctypes.POINTER(Memory),wintypes.DWORD)
        get_info.restype=wintypes.BOOL
        if get_info(kernel.GetCurrentProcess(),ctypes.byref(info),info.cb):
            return int(info.PeakWorkingSetSize)
    except Exception:
        pass
    return None


def freeze(paths):
    task=read(record_path(paths))
    if task.get('run_root'):
        raise ValueError('USE_EXISTING_RUN_NO_REFREEZE')
    sys.path.insert(0,str(paths.repo_root/'scripts/storage'))
    from backtest_run_manager import create_backtest_run
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=paths.repo_root,text=True).strip()
    root=create_backtest_run(TASK_ID,commit,'2026-01-01','2026-10-02',[])
    contract={'schema_version':1,'research_id':TASK_ID,'parent_policy_id':selected.LEGACY_POLICY,
        'policy_id':selected.DIRECT_POLICY,'candidate_count':2,'candidate_ids':list(selected.STRATEGY_IDS),
        'candidate_rule':'Frozen shared pred_hgb descending, ticker ascending, Top20 of original Raw Top40',
        'outside_candidate_rule':'No increase; target <= min(signal-close account weight,10%)',
        'risk_parameters':{'lambda':5,'horizon_sessions':5,'cost_one_way':.0005,'max_weight':.10,'max_gross':1.,'zero_cutoff':.0025,'q10_coefficient':0.},
        'train_validation_end_exclusive':'2026-01-01','test_start':'2026-01-01','test_end_exclusive':'2027-01-01',
        'as_of_client_date':'2026-10-04 Asia/Tokyo','requested_end_date':'2026-10-02',
        'baseline_ids':['RAW_A2','LEGACY_HGB_DIAG_5','LEGACY_HGB_FACTOR_5'],
        'primary_metrics':['cumulative_return','max_drawdown','turnover','mean_cash','nav_cost_identity','candidate_and_offcandidate_invariants'],
        'search_trials':0,'model_fit_calls':0,'stopping_rule':task['stopping_rule'],
        'exposure':task['selection_exposure'],'outcomes_independent':False,
        'broker_action_allowed':False,'official_adoption_allowed':False,
        'frozen_source_hashes':selected.FROZEN_HASHES,
        'source_refs':{name:extension.reference(paths.repo_root/name) for name in SOURCE_FILES},
        'created_at':datetime.now(timezone.utc).isoformat()}
    write(root/'frozen_contract.json',contract)
    cfg=read(root/'run_config.json')
    cfg.update(strategy_version=selected.DIRECT_POLICY,execution_assumption='SIGNAL_CLOSE_NEXT_SESSION_OPEN',cost_assumption='5bp one-way absolute turnover',frozen_contract=extension.reference(root/'frozen_contract.json'),train_validation_cutoff='2026-01-01',test_end_exclusive='2027-01-01',model_fit_calls=0)
    write(root/'run_config.json',cfg)
    task.update(run_root=str(root),frozen_contract=extension.reference(root/'frozen_contract.json'),status='FROZEN_READY_FOR_DESCRIPTIVE_EVALUATION')
    write(record_path(paths),task)
    print(json.dumps({'run_root':str(root),'contract_sha256':task['frozen_contract']['sha256']},ensure_ascii=False),flush=True)


def _checked_frozen_contract(paths, reader):
    # One original chain algorithm, shared by default and metadata-only callers.
    task=reader(record_path(paths), {'frozen_contract','engineering_repair_receipts'}); ref=task['frozen_contract']
    extension.verify_refs([ref]); contract=reader(ref['path'], {'source_refs'})
    source_refs=dict(contract['source_refs'])
    for receipt_ref in task.get('engineering_repair_receipts',[]):
        extension.verify_refs([receipt_ref]);receipt=reader(receipt_ref['path'], {'source_name','frozen_contract_sha256','old_ref','new_ref'})
        name=receipt['source_name']
        if receipt['frozen_contract_sha256']!=ref['sha256'] or receipt['old_ref']!=source_refs[name]:
            raise ValueError('ENGINEERING_REPAIR_LINEAGE_MISMATCH')
        source_refs[name]=receipt['new_ref']
    extension.verify_refs(list(source_refs.values()))
    return task,contract,source_refs


def _engineering_metadata(path, fields):
    from scripts.common.json_projection import metadata_fields
    path = Path(path)
    if path.stat().st_size > 16 * 1024**2:
        raise ValueError('ENGINEERING_REPAIR_DOCUMENT_SIZE_LIMIT')
    with path.open('rb') as handle:
        return metadata_fields(handle, fields)


def frozen_contract(paths, *, metadata_only=False):
    reader = _engineering_metadata if metadata_only else lambda path, fields: read(path)
    task,contract,_ = _checked_frozen_contract(paths, reader)
    return task,contract


def _engineering_record_span(handle):
    """Locate only the original record's repair array; skip opaque values."""
    from scripts.common.json_projection import _parser_type
    parser = _parser_type()(handle)
    parser.expect(b'{'); names = set(); data = {}; span = None
    while True:
        parser.white()
        if parser.peek() == b'}':
            parser.take(); break
        key = parser.scalar(limit=4096)
        if not isinstance(key, str) or key in names:
            raise ValueError('ENGINEERING_REPAIR_RECORD_DUPLICATE_OR_INVALID_KEY')
        names.add(key); parser.expect(b':'); parser.white(); start = parser.tell()
        if key in ('frozen_contract', 'engineering_repair_receipts'):
            data[key] = parser.scalar(limit=65536)
            if key == 'engineering_repair_receipts':
                span = (start, parser.tell())
        else:
            parser.skip()
        parser.white(); separator = parser.take()
        if separator == b'}': break
        if separator != b',': raise ValueError('ENGINEERING_REPAIR_RECORD_FORMAT')
        parser.white()
        if parser.peek() == b'}': raise ValueError('ENGINEERING_REPAIR_RECORD_FORMAT')
    parser.white()
    if parser.peek() or set(data) != {'frozen_contract','engineering_repair_receipts'} or span is None:
        raise ValueError('ENGINEERING_REPAIR_RECORD_FORMAT')
    if not isinstance(data['engineering_repair_receipts'], list):
        raise ValueError('ENGINEERING_REPAIR_REFS_REQUIRED')
    return data,span


def _engineering_sha(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def _engineering_ref(value):
    if (not isinstance(value, dict) or set(value) != {'path','sha256'}
            or not isinstance(value['path'], str) or not Path(value['path']).is_absolute()
            or not isinstance(value['sha256'], str) or len(value['sha256']) != 64
            or any(char not in '0123456789abcdef' for char in value['sha256'])):
        raise ValueError('ENGINEERING_REPAIR_EXACT_REF_REQUIRED')
    return value


def _engineering_copy(handle, output, count):
    while count:
        chunk = handle.read(min(count, 65536))
        if not chunk: raise ValueError('ENGINEERING_REPAIR_RECORD_TRUNCATED')
        output.write(chunk); count -= len(chunk)


def _engineering_span_sha(path, start, stop):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        handle.seek(start)
        while start < stop:
            chunk = handle.read(min(stop - start, 65536))
            if not chunk: raise ValueError('ENGINEERING_REPAIR_RECORD_TRUNCATED')
            digest.update(chunk); start += len(chunk)
    return digest.hexdigest()


def append_engineering_repair_refs(paths, receipt_refs, *, expected_before_sha256,
                                  expected_frozen_contract_sha256, expected_existing_refs):
    """Atomically append reviewed metadata refs without decoding other fields.

    This is registration only. It does not qualify a scientific change or grant
    account/execution authority. All receipts must already exist and be reviewed.
    """
    import os
    import uuid
    from scripts.common.daily_support import single_update
    record = record_path(paths)
    assert_safe_output_path(record, kind='results', paths=paths)
    if (not isinstance(receipt_refs, list) or not 1 <= len(receipt_refs) <= len(SOURCE_FILES)
            or not isinstance(expected_existing_refs, list)):
        raise ValueError('ENGINEERING_REPAIR_APPEND_REFS_REQUIRED')
    supplied = [_engineering_ref(dict(ref)) for ref in receipt_refs]
    expected = [_engineering_ref(dict(ref)) for ref in expected_existing_refs]
    _engineering_ref({'path':str(record.resolve()), 'sha256':expected_before_sha256})
    _engineering_ref({'path':str(record.resolve()), 'sha256':expected_frozen_contract_sha256})
    identities = [(ref['path'], ref['sha256']) for ref in expected + supplied]
    if len(set(identities)) != len(identities):
        raise ValueError('ENGINEERING_REPAIR_DUPLICATE_RECEIPT')
    with single_update(paths.daily_root / 'A2_today_recommendation'):
        if record.stat().st_size > 16 * 1024**2 or _engineering_sha(record) != expected_before_sha256:
            raise ValueError('ENGINEERING_REPAIR_BEFORE_SHA_MISMATCH')
        with record.open('rb') as handle: previous,(start,stop) = _engineering_record_span(handle)
        if previous['engineering_repair_receipts'] != expected:
            raise ValueError('ENGINEERING_REPAIR_PREFIX_MISMATCH')
        if _engineering_ref(previous['frozen_contract'])['sha256'] != expected_frozen_contract_sha256:
            raise ValueError('ENGINEERING_REPAIR_FROZEN_CONTRACT_MISMATCH')
        for ref in supplied:
            assert_safe_output_path(ref['path'], kind='results', paths=paths)
            extension.verify_refs([ref])
            receipt = _engineering_metadata(ref['path'], {'source_name','frozen_contract_sha256','old_ref','new_ref'})
            name = receipt.get('source_name')
            if name not in SOURCE_FILES:
                raise ValueError('ENGINEERING_REPAIR_SOURCE_NOT_IN_ORIGINAL_SEVEN')
            for key in ('old_ref','new_ref'):
                source_ref = _engineering_ref(receipt.get(key))
                if Path(source_ref['path']).resolve() != (paths.repo_root / name).resolve():
                    raise ValueError('ENGINEERING_REPAIR_SOURCE_PATH_MISMATCH')
        combined = expected + supplied
        replacement = json.dumps(combined, ensure_ascii=False, indent=2, allow_nan=False).replace('\n','\n  ').encode('utf-8')
        if len(replacement) > 65536:
            raise ValueError('ENGINEERING_REPAIR_REFS_SIZE_LIMIT')
        staged = record.with_name('.' + record.name + '.engineering-repair-' + uuid.uuid4().hex + '.tmp')
        assert_safe_output_path(staged, kind='results', paths=paths)
        committed = created = False
        try:
            size = record.stat().st_size
            with record.open('rb') as handle, staged.open('xb') as output:
                created = True
                _engineering_copy(handle, output, start); output.write(replacement)
                handle.seek(stop); _engineering_copy(handle, output, size - stop)
                output.flush(); os.fsync(output.fileno())
            def staged_reader(path, fields):
                return _engineering_metadata(staged if Path(path).resolve() == record.resolve() else path, fields)
            checked,contract,terminal = _checked_frozen_contract(paths, staged_reader)
            if (checked['frozen_contract'] != previous['frozen_contract']
                    or checked['engineering_repair_receipts'] != combined
                    or set(contract['source_refs']) != set(SOURCE_FILES) or set(terminal) != set(SOURCE_FILES)):
                raise ValueError('ENGINEERING_REPAIR_STAGED_IDENTITY_MISMATCH')
            for name,ref in terminal.items():
                if Path(ref['path']).resolve() != (paths.repo_root / name).resolve():
                    raise ValueError('ENGINEERING_REPAIR_SOURCE_PATH_MISMATCH')
            tail = start + len(replacement)
            if (_engineering_span_sha(record,0,start) != _engineering_span_sha(staged,0,start)
                    or _engineering_span_sha(record,stop,size) != _engineering_span_sha(staged,tail,staged.stat().st_size)):
                raise ValueError('ENGINEERING_REPAIR_OPAQUE_BYTES_CHANGED')
            if _engineering_sha(record) != expected_before_sha256:
                raise ValueError('ENGINEERING_REPAIR_BEFORE_SHA_MISMATCH')
            after_sha = _engineering_sha(staged)
            os.replace(staged, record); committed = True
            try:
                current,_ = frozen_contract(paths, metadata_only=True)
                if (current != checked or _engineering_sha(record) != after_sha):
                    raise ValueError('ENGINEERING_REPAIR_POSTCOMMIT_CHANGED')
            except Exception as exc:
                raise RuntimeError('ENGINEERING_REPAIR_COMMITTED_POSTCHECK_FAILED:' + after_sha) from exc
            return {'status':'ORIGINAL_FROZEN_CONTRACT_STRONG_CLOSURE_PASS',
                'record_before_sha256':expected_before_sha256, 'record_after_sha256':after_sha,
                'frozen_contract':previous['frozen_contract'], 'repair_count':len(combined),
                'appended_refs':supplied, 'non_chain_bytes_preserved':True}
        finally:
            if created and not committed and staged.exists(): staged.unlink()


def accepted_inputs(paths):
    owner=read(paths.daily_root/'A2_selected_hgb/latest.json')
    ref=owner['performance_extension']['manifest']; extension.verify_refs([ref])
    manifest=read(ref['path'])
    input_refs=[r for r in manifest['source_refs'] if Path(r['path']).name in {'three_strategy_price_inputs.json','price_inputs.json'}]
    candidates=[]
    for input_ref in input_refs:
        extension.verify_refs([input_ref]); metadata=read(input_ref['path'])
        if metadata.get('price_basis')==extension.BASIS and metadata.get('captured_prices') in manifest['source_refs']:
            candidates.append((input_ref,metadata))
    if len(candidates)!=1:
        raise ValueError('ACCEPTED_PRICE_INPUT_IDENTITY_AMBIGUOUS')
    input_ref,metadata=candidates[0]
    prices=metadata['captured_prices']; extension.verify_refs([prices])
    return Path(prices['path']),Path(input_ref['path']),[ref,input_ref,prices]


def direct_package(paths, manifest_path, report_path=None):
    package=selected.build_package(paths,current_report_path=report_path,policy=selected.DIRECT_POLICY,replay_manifest=manifest_path)
    task,_=frozen_contract(paths)
    package['source_refs']['policy/frozen_contract']=task['frozen_contract']
    package['source_hashes']['policy/frozen_contract']=task['frozen_contract']['sha256']
    package['policy_id']=selected.DIRECT_POLICY
    return package


def evaluate(paths):
    task,contract=frozen_contract(paths); root=Path(task['run_root'])
    prices,inputs,refs=accepted_inputs(paths)
    write(root/'input_manifest.json',{'research_id':TASK_ID,'source_refs':refs,'frozen_contract':task['frozen_contract'],'broker_action_allowed':False,'official_adoption_allowed':False,'research_only':True,'input_data_copied':False,'duplicate_market_data_count':0})
    print('Running fixed direct + legacy policies on the same qualified clock',flush=True)
    replay_path=root/'derived/replay/manifest.json'
    previous_peak=0
    if replay_path.is_file():
        checkpoint=read(root/'summary.json');extension.verify_refs([checkpoint['manifest']])
        manifest=read(replay_path)
        if manifest.get('policy_id')!=selected.DIRECT_POLICY or manifest.get('requested_end_date')!=contract['requested_end_date']:
            raise ValueError('REPLAY_CHECKPOINT_CONTRACT_MISMATCH')
        extension.verify_refs([r for item in {**manifest['strategies'],**manifest['comparisons']}.values() for r in item['outputs'].values()])
        previous_peak=checkpoint.get('peak_working_set_bytes') or 0
        print('Reuse verified completed replay; resume package publication only',flush=True)
    else:
        manifest=extension.run_extension(prices,inputs,root/'derived/replay',repo_root=paths.repo_root,target_date=contract['requested_end_date'],policy=selected.DIRECT_POLICY,include_legacy=True)
    # All comparisons share a single prefix chosen only by qualification failures.
    rows=[]
    for sid,item in {**manifest['strategies'],**manifest['comparisons']}.items():
        row={'strategy_id':sid,**item['summary']}
        import pandas as pd
        ledger=pd.read_parquet(item['outputs']['daily']['path'])
        row.update(transaction_cost=float(ledger.transaction_cost_amount.sum()),identity_error=float(max(ledger.nav_identity_error.abs().max(),ledger.cost_identity_error.abs().max())))
        targets=pd.read_parquet(item['outputs']['targets']['path'])
        row['solver_fallback_days']=int(targets.loc[targets.solver_failed,'signal_date'].nunique())
        if sid in selected.STRATEGY_IDS:
            import numpy as np
            by_day={day:{r['ticker'] for r in sorted(rows,key=lambda r:(-r['pred_hgb'],r['ticker']))[:20]} for day,rows in __import__('itertools').groupby(manifest['shared_scores_historical'],key=lambda r:r['signal_date'])}
            bad=0
            for r in targets.itertuples():
                if r.ticker not in by_day[str(pd.Timestamp(r.signal_date).date())] and r.target_weight>r.signal_close_weight+1e-7:
                    bad+=1
            row['outside_candidate_increase_count']=bad
            if bad: raise ValueError('DIRECT_OUTSIDE_CANDIDATE_INCREASE')
        rows.append(row)
    evidence={'policy_id':selected.DIRECT_POLICY,'period':manifest['performance_period'],'requested_end_date':contract['requested_end_date'],'blocked_next':manifest['blocked_next'],'status':manifest['status'],'rows':rows,'peak_working_set_bytes':peak_working_set(),'model_fit_calls':0,'search_trials':0,'broker_calls':0,'outcomes_independent':False,'manifest':extension.reference(root/'derived/replay/manifest.json')}
    write(root/'summary.json',evidence)
    package=direct_package(paths,root/'derived/replay/manifest.json')
    from apps.demo_console.adapters.selected_strategies_reader import validate_package
    validate_package(package)
    output=paths.daily_root/'A2_selected_hgb/direct_hgb_r1/latest.json'
    selected.publish(package,output)
    # Activation is a source configuration; it does not replay or submit orders.
    setting={'schema_version':1,'policy_id':selected.DIRECT_POLICY,'package_relative_path':'A2_selected_hgb/direct_hgb_r1/latest.json','research_id':TASK_ID,'frozen_contract':task['frozen_contract'],'activation_basis':'USER_SPECIFIED_SIGNAL_ALIGNMENT_NOT_OUTCOME_SELECTION'}
    (paths.repo_root/'config/research_governance/selected_hgb_policy.json').write_text(json.dumps(setting,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    consumed=__import__('apps.demo_console.adapters.selected_strategies_reader',fromlist=['load_package']).load_package()
    if consumed['policy_id']!=selected.DIRECT_POLICY: raise ValueError('DEMO_CONSUMPTION_POLICY_MISMATCH')
    evidence['peak_working_set_bytes']=max(previous_peak,peak_working_set() or 0)
    evidence['peak_memory_scope']='Maximum observed scientific worker high-water mark across replay and publication continuation; excludes other services'
    write(root/'summary.json',evidence)
    task.update(status='EVALUATED_AND_PUBLISHED',evaluation_summary=extension.reference(root/'summary.json'),published_package=extension.reference(output),demo_consumer='load_package read and validated active direct policy',remaining=['A3 report, default acceptance and final audit'])
    write(record_path(paths),task)
    print(json.dumps(evidence,ensure_ascii=False),flush=True)


def refresh_direct(paths,current_report_path,output_path=None,progress=None,*,held_price_reuse=None,
                   execution_open_manifest=None,execution_end=None):
    task,contract=frozen_contract(paths)
    target=selected._date(read(current_report_path)['data_date'])
    output=Path(output_path or selected.active_policy(paths)[1])
    from scripts.research.a2.evaluation.selected_performance_update import (
        replay_with_held_updates, verified_direct_research, merge_extension)
    previous=current=None
    prior_ref=None
    if output.is_file():
        previous,package_ref=extension._capture_json(output)
        from apps.demo_console.adapters.selected_strategies_reader import validate_package
        validate_package(previous)
        # A validated display overlay owns newer research, while its canonical
        # score/target bytes still identify the unchanged execution package.
        _,display_prior,display_ref,_=extension.bound_direct_research(paths)
        if display_ref!=previous['performance_extension']['manifest']:
            from scripts.research.a2.evaluation.selected_performance_update import merge_extension
            previous=merge_extension(previous,display_prior,display_ref['path'],history_root=output.parent/'history')
        if (previous.get('source_refs',{}).get('policy/frozen_contract')!=task['frozen_contract']
                or previous.get('source_hashes',{}).get('policy/frozen_contract')!=task['frozen_contract']['sha256']):
            raise ValueError('DIRECT_DAILY_FROZEN_CONTRACT_UNBOUND')
        prior,prior_ref=verified_direct_research(previous)
        from scripts import daily_recommendation_inputs as calendar_inputs
        calendar=calendar_inputs.latest_completed_session(
            calendar_inputs.load_frozen_binding(paths.repo_root),datetime.now(timezone.utc))
        if target not in calendar['sessions'] or target>calendar['target_date']:
            raise ValueError('DIRECT_DAILY_COMPLETED_SESSION_REQUIRED')
        if prior['performance_period']['end']>target:
            raise ValueError('DIRECT_DAILY_EXECUTION_DATE_REGRESSED')
        extension.verify_refs([package_ref])
        # The same verified execution window needs only new frozen inference.
        # New close signals enter the research ledger at the following opening.
        current=direct_package(paths,prior_ref['path'],current_report_path)
        if (execution_open_manifest is None and execution_end is None
                and prior['status']=='READY' and prior.get('blocked_next') is None
                and prior['performance_period']['end']==target
                and prior.get('requested_end_date')==target):
            if progress: progress('复用已验证同执行日研究账本；仅更新当前收盘目标，不重复行情采集或回放。')
            selected.publish(current,output)
            return current
    sys.path.insert(0,str(paths.repo_root/'scripts/storage'))
    from backtest_run_manager import create_backtest_run
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=paths.repo_root,text=True).strip()
    root=create_backtest_run(TASK_ID,commit,'2026-01-01',target,[])
    if progress: progress('按冻结 HGB Top20 生成两风险目标，并复用原账本回放。')
    open_args=({'execution_open_manifest':execution_open_manifest,'execution_end':execution_end}
        if execution_open_manifest is not None or execution_end is not None else {})
    prior_args=({'prior_research_manifest':prior_ref} if prior_ref is not None else {})
    failed_ref=None
    try:
        prices,inputs=extension.capture_full_prices(root/'derived/inputs',repo_root=paths.repo_root,current_report_path=current_report_path,**open_args,**prior_args)
        manifest,manifest_path=replay_with_held_updates(paths,root/'derived',prices,inputs,target,progress,
            policy=selected.DIRECT_POLICY,**open_args,**prior_args,**({'held_price_reuse':held_price_reuse} if held_price_reuse is not None else {}))
        if current is None:
            package=direct_package(paths,manifest_path,current_report_path)
        else:
            failed_ref=extension.reference(manifest_path)
            if manifest['performance_period']['end']<previous['performance_period']['end']:
                raise ValueError('DIRECT_DAILY_VERIFIED_CUTOFF_REGRESSED')
            package=merge_extension(current,manifest,manifest_path,history_root=output.parent/'history')
        selected.publish(package,output)
        return package
    except Exception as exc:
        if current is None or target<=current['performance_period']['end']:
            raise
        # Keep the immutable previous research and the actually inferred current
        # decision. A failed extension is explicit; it cannot retract old charts.
        current['performance_extension'].update(status='PARTIAL',requested_end_date=target,
            blocked_next={'signal_date':current['performance_period']['end'],
                'execution_date':target,'reason':'DIRECT_DAILY_REPLAY_UNVERIFIED:'+str(exc),
                **({'attempted_manifest':failed_ref} if failed_ref is not None else {})})
        if progress: progress('研究扩展未通过；保留已验证曲线及新收盘目标：'+str(exc))
        selected.publish(current,output)
        return current


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['freeze','evaluate'])
    args=parser.parse_args();paths=resolve()
    if args.action=='freeze': freeze(paths)
    else: evaluate(paths)

if __name__=='__main__':main()
