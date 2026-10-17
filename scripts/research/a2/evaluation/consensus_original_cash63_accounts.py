"""New cash63 evaluation orchestration; frozen owners retain all economic logic."""
from __future__ import annotations
import argparse, ast, copy, gc, hashlib, importlib.abc, importlib.util, json, os, shutil, sys, time
from pathlib import Path
TASK = 'A_STATEFUL_CASH63_CONSENSUS100_RETRAIN_20261017_R1'
REPO = Path('D:/us-tech-quant')
def need(v, message):
    if not v: raise ValueError(message)
def sha(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()
def reference(path): return dict(path=str(path), sha256=sha(path))
def physical(ref):
    path = Path(ref['path']); need(sha(path) == ref['sha256'], 'SOURCE_SHA_CHANGED:'+str(path)); return path
def read(ref): return json.loads(physical(ref).read_text(encoding='utf-8-sig'))
def canonical(value): return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
class SealedFinder(importlib.abc.MetaPathFinder):
    def __init__(self, sources): self.sources = {row['module']:row for row in sources if row['module'] and row['overlay_required']}
    def find_spec(self, fullname, path, target=None):
        row = self.sources.get(fullname)
        return importlib.util.spec_from_file_location(fullname, physical(row['copied_ref'])) if row else None

def bootstrap(config):
    """Restore exact old economic owners, without old saved-output authority routes."""
    sealed = read(config['sealed_recovery_config_ref'])
    original = read(config['old_account_config_ref'])
    need(sealed['original_config_ref'] == config['old_account_config_ref'], 'OLD_SOURCE_CONFIG_CHANGED')
    need([r['original_ref'] for r in sealed['sources']] == original['runtime_source_refs'], 'EXACT_ECONOMIC_OWNER_LIST_REQUIRED')
    for row in sealed['sources']:
        need(row['copied_ref']['sha256'] == row['original_ref']['sha256'], 'ECONOMIC_SOURCE_BYTES_CHANGED')
        physical(row['copied_ref'])
        if not row['overlay_required']: physical(row['original_ref'])
    finder = SealedFinder(sealed['sources'])
    need(not any(name in sys.modules for name in finder.sources), 'BOOTSTRAP_BEFORE_ECONOMIC_IMPORTS')
    sys.meta_path.insert(0, finder)
    from scripts.common.storage_paths import resolve
    from scripts.research.a2.evaluation import frozen_a94_profile as p
    p._roots = lambda: tuple(Path(getattr(resolve(REPO), name)).resolve() for name in ('results_root', 'cache_root', 'backtest_root'))
    # Only utility functions are consumed, never the old 175/153 runner entry.
    entry = next(row for row in sealed['sources'] if Path(row['original_ref']['path']).name == 'a_all_random_accounts.py')
    spec = importlib.util.spec_from_file_location('_cash63_frozen_account_utilities', physical(entry['copied_ref']))
    utility = importlib.util.module_from_spec(spec); sys.modules[spec.name] = utility; spec.loader.exec_module(utility)
    return sealed, original, utility

def run(config_ref, *, max_windows=None):
    config = read(config_ref)
    need(config.get('preflight_only') is not True, 'PREFLIGHT_CONFIG_CANNOT_EXECUTE')
    need(config['task_id'] == TASK and config['execution_release'] == 'ROOT_RELEASED_FROZEN_CASH63_2026', 'EXACT_NEW_BRANCH_RELEASE_REQUIRED')
    need(config['new_fit'] == 0 and config['tuning'] is False, 'NO_TRAINING_OR_TUNING')
    for ref in config['source_pins'].values(): physical(ref)
    sealed, oldconfig, utility = bootstrap(config)
    import numpy as np, pandas as pd, pyarrow as pa, pyarrow.parquet as pq
    from scripts.common.storage_paths import resolve, assert_safe_output_path
    from scripts.research.a2.evaluation import consensus_original_cash63_profile as route
    from scripts.research.a2.evaluation import stateful_frozen_a94 as controller, stateful_frozen_six_path as metrics_owner
    from scripts.research.a2.inference import stateful_test_inputs as inputs, frozen_a94_values as value_owner
    from scripts.research.a2.training import stateful_replay as replay
    route.install_routes(config_ref)
    binding = read(config['head_binding_ref']); schedule = read(config['schedule_ref'])
    rows = binding['configurations']; need(len(rows) == 63, 'EXACT63_REQUIRED')
    candidates = []
    for row in rows:
        c = copy.deepcopy(row['original_rule_specification'])
        c.update(candidate_id=row['candidate_id'], scientific_tuple_sha256=row['scientific_tuple_sha256'])
        candidates.append(c)
    ids = [c['candidate_id'] for c in candidates]
    need(len(set(ids)) == 63 and len(schedule['windows']) == 101, 'EXACT63x101_REQUIRED')
    out = Path(config['output_dir']); paths = resolve(REPO)
    assert_safe_output_path(out, kind='backtest', paths=paths)
    need(out.resolve().is_relative_to((paths.backtest_root/TASK).resolve()), 'NEW_BRANCH_OUTPUT_REQUIRED')
    out.mkdir(parents=True, exist_ok=True)
    economic_key = hashlib.sha256(canonical(config).encode()).hexdigest()
    bundle = read(oldconfig['bridge_bundle_ref']); source = read(bundle['source_bundle_ref']); flags_doc = read(bundle['flags_output_ref'])
    # Compile the exact accepted bounded reader rather than importing inference producers.
    bridge = next(r for r in sealed['sources'] if Path(r['original_ref']['path']).name == 'prepare_frozen_inputs.py')
    tree = ast.parse(physical(bridge['copied_ref']).read_text(encoding='utf-8-sig'))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'bounded_frame')
    namespace = dict(profile=utility.profile, pd=pd, pq=pq, pa=pa, need=need, sha=sha)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(bridge['copied_ref']['path']), 'exec'), namespace)
    bounded = namespace['bounded_frame']
    first, last = bundle['start'], bundle['end']
    need(first == '2026-01-02' and last == '2026-10-08', 'FROZEN_WINDOW_CHANGED')
    data = dict(flags=bounded(flags_doc['flags_ref'], flags_doc['flags_read_columns'], 'signal_date', first, last),
                bars=bounded(source['bars_ref'], source['bars_read_columns'], 'trade_date', first, last),
                account_catalog=read(bundle['account_catalog_ref']), value_outputs={})
    vd = read(config['new_value_outputs_ref'])
    need(vd['new_fit'] == 0, 'INFERENCE_ONLY_OUTPUT_REQUIRED')
    names = {c['value_model'] for c in candidates}
    for name in sorted(names):
        item = vd['outputs'][name]
        data['value_outputs'][name] = dict(frame=bounded(item['frame_ref'], item['read_columns'], 'signal_date', first, last), sigma=item['sigma'], lineage=item['lineage'])
    calendar = pd.DatetimeIndex(pd.to_datetime(schedule['common_sessions']))
    chunks = []
    for cost in (5, 10, 20):
        group = [c for c in candidates if c['execution_friction']['one_way_bps'] == cost]
        size = config['max_candidates_per_batch']
        for start in range(0, len(group), size): chunks.append((f'STATEFUL_OVERLAY_{cost}bps_{start//size+1:02d}', group[start:start+size]))
    started = time.monotonic(); completed = []
    for wi, window in enumerate(schedule['windows']):
        if max_windows is not None and wi >= max_windows: break
        cp = out/window['window_id']/'WINDOW_COMPLETION.json'
        if cp.exists():
            previous = read(reference(cp)); need(previous['economic_key'] == economic_key and previous['window'] == window and [r['strategy_id'] for r in previous['paths']] == ids, 'WINDOW_CHECKPOINT_CHANGED')
            for rr in previous['batch_completion_refs']:
                batch = read(rr)
                for ref in batch['artifacts'].values(): physical(ref)
            completed.append(reference(cp)); continue
        need(shutil.disk_usage(paths.backtest_root).free > 10*2**30, 'RESUME_AFTER_FREE_SPACE_RECOVERY_REQUIRED')
        auth = route.load_authority(window['window_id'])
        dates = calendar[(calendar >= pd.Timestamp(window['start'])) & (calendar <= pd.Timestamp(window['end']))]
        need(len(dates) == window['execution_sessions']+1 and str(dates[1].date()) == window['first_execution_date'], 'ORIGINAL_WINDOW_REQUIRED')
        view = inputs.project_window(data['flags'], data['bars'], dates, auth, values_function=replay._old().values)
        account, source_kwargs = utility.account_inputs(data['account_catalog'], auth)
        window_packets = utility.values_for(data, view, names)
        window_rows = {}; batch_refs = []
        for label, specs in chunks:
            checkpoint = out/window['window_id']/label/'completion.json'
            local_ids = [c['candidate_id'] for c in specs]
            if checkpoint.exists():
                prior = read(reference(checkpoint)); need(prior['economic_key'] == economic_key and prior['candidate_ids'] == local_ids, 'BATCH_CHECKPOINT_CHANGED')
                for ref in prior['artifacts'].values(): physical(ref)
                window_rows.update({r['strategy_id']:r for r in prior['paths']}); batch_refs.append(reference(checkpoint)); continue
            scoped = route.load_authority(window['window_id'], candidate_ids=local_ids)
            batches = controller.prepare_batches(scoped, specs); need(len(batches) == 1, 'ONE_COST_CHUNK_REQUIRED')
            batch = batches[0]; risk_methods = {c.get('risk','diag') for c in specs if c.get('gross','fixed') != 'fixed'}
            risk_handles = {}
            if risk_methods:
                loader = value_owner.FrozenStateLoader(batch.scoped_authority)
                risk_handles = {m:loader.load('old_risk:'+m) for m in risk_methods if m not in ('diag','diag20_reference')}
            provider, risk_audit = (value_owner.risk_provider(risk_handles, dates, view['vol']) if risk_methods else (None, []))
            packets = {name:window_packets[name] for name in {c['value_model'] for c in specs}}
            folder = checkpoint.parent
            folder.mkdir(parents=True, exist_ok=True)
            attempt = sum(p.is_dir() and p.name.startswith('attempt_') for p in folder.iterdir())+1
            need(attempt <= 4, 'DIAGNOSE_REPEATED_FAILURE_BEFORE_RETRY')
            leaf = folder/f'attempt_{attempt:03d}'; leaf.mkdir(exist_ok=False); batch_started = time.monotonic()
            try:
                result, frames = controller.execute_batch(batch, market=view['market'], packets=packets, top=view['top'], qualified=view['qualified'], vol=view['vol'], account=account, stock_present=view['stock_present'], raw_selector_present=view['raw_selector_present'], account_source_kwargs=source_kwargs, risk_provider=provider)
                frames = metrics_owner._dual_nav_frames(result, frames)
                artifacts = {name:utility.frame_write(leaf/(name+'.parquet'), frame) for name, frame in frames.items()}
                artifacts['risk_audit'] = utility.put(leaf/'risk_audit.json', dict(records=risk_audit, new_fit=0))
                local = []
                for c in batch.candidates:
                    cid = c['candidate_id']; q = utility.quality(result, frames, cid, dates); stats = None
                    if q['all_passed']:
                        d = frames['daily'].loc[frames['daily'].path_id.eq(cid)].sort_values('date')
                        stats = {**utility._full_metrics(c, frames), **metrics_owner.nav_descriptive_metrics(d.date, d.TOTAL_ECONOMIC_NAV, 3000.)}
                        statuses = frames['execution_results'].loc[frames['execution_results'].path_id.eq(cid), 'status']
                        stats.update(rejected_execution_count=int(statuses.eq('REJECTED').sum()), execution_status_counts={str(k):int(v) for k,v in statuses.value_counts().items()}, completed_trade_win_rate=None, completed_trade_win_rate_reason='Original owner has no defined completed-trade realized-PnL win statistic; not inferred from fills or daily wins.')
                    row = dict(task_id=TASK, window=window, strategy_id=cid, status='NATIVE_DESCRIPTIVE_COMPLETE' if q['all_passed'] else 'ACCOUNT_QUALIFICATION_FAILED', qualification=q, source_completeness_unknown=True, primary_metrics=None, native_diagnostic_metrics=stats, one_way_bps=c['execution_friction']['one_way_bps'], scientific_tuple_sha256=c['scientific_tuple_sha256'], new_fit=0)
                    local.append(row); window_rows[cid] = row
                batch_refs.append(utility.put(checkpoint, dict(task_id=TASK, economic_key=economic_key, candidate_ids=local_ids, paths=local, artifacts=artifacts)))
                print(json.dumps(dict(window=window['window_id'], batch=label, paths=len(local), seconds=round(time.monotonic()-batch_started,2))), flush=True)
                del result, frames, packets, risk_handles, provider; gc.collect()
            except Exception as exc:
                utility.put(leaf/'failure.json', dict(task_id=TASK, economic_key=economic_key, error_type=type(exc).__name__, message=str(exc)))
                raise
        need(set(window_rows) == set(ids), 'EXACT63_WINDOW_DENOMINATOR_REQUIRED')
        utility.put(cp, dict(task_id=TASK, economic_key=economic_key, window=window, expected_paths=63, paths=[window_rows[cid] for cid in ids], batch_completion_refs=batch_refs))
        completed.append(reference(cp)); print(json.dumps(dict(window=window['window_id'], windows_done=len(completed), windows_total=101, elapsed_seconds=round(time.monotonic()-started,2))), flush=True)
        del view, window_packets; gc.collect()
    if len(completed) == 101:
        final = out/'COMPLETION.json'
        value = dict(task_id=TASK, status='ALL_63x101_ACCOUNT_WINDOWS_TERMINAL', config_ref=config_ref, economic_key=economic_key, completed_windows=101, candidate_window_records=6363, window_completion_refs=completed, new_fit=0, tuning=False)
        if final.exists(): need(read(reference(final)) == value, 'FINAL_CHECKPOINT_CHANGED')
        else: utility.put(final, value)
    return dict(completed_windows=len(completed), total_windows=101, new_fit=0)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--config', required=True); parser.add_argument('--config-sha', required=True); parser.add_argument('--execute', action='store_true'); parser.add_argument('--max-windows', type=int); args=parser.parse_args()
    ref=dict(path=args.config, sha256=args.config_sha); read(ref)
    if not args.execute: print(json.dumps(dict(status='METADATA_ONLY_NO_ACCOUNT', config_ref=ref))); return
    print(json.dumps(run(ref, max_windows=args.max_windows)), flush=True)
if __name__ == '__main__': main()
