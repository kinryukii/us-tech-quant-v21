"""Maintained frozen-universe wiring. Importing never reads inputs or predicts/runs accounts.

Migrated from the preserved aggregate task runner, SHA256
269871dfc16805d3c373c4be1af4c4cd0a5313526398e81c09fb74dbbb80b205.
The old task artifact remains immutable; this owner serves only the two explicit
universe variants and reuses the original business owners.

Root supplies physical full-account admissions and typed source kwargs. The
existing owners retain ranking, model inference, proxy state, CA, account and
journal semantics. All callbacks are explicit; this file creates no authority.
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from scripts.research.a2.evaluation import aggregate_13f_retest as adapter
from scripts.research.a2.evaluation import frozen_test_authority as authority
from scripts.research.a2.evaluation import stateful_frozen_six_path as six
from scripts.research.a2.evaluation import continuous_research_account as common
from scripts.research.a2.inference import stateful_frozen_test as frozen
from scripts.research.a2.training import stateful_execution as execution
from scripts.research.a2.training import stateful_inputs
from scripts.storage.storage_r2a import sha256,write_json_atomic

ACCOUNT_REF=dict(path='D:/us-tech-quant-results/A2_STATEFUL_ACTION_AND_CASH_PRE2026_TEST2026_R1/R1_ACCOUNT_CONFIG.json',
    sha256='84d27ff5a16e7c26501cfb0ea61bbe38d76159c44695856503970273c7174635')


def _need(ok,code):
    if not ok: raise ValueError(code)


def _ref(path):
    return dict(path=str(path),sha256=sha256(Path(path)))


def _frame(ref,columns=None,filters=None):
    return pd.read_parquet(authority._physical(ref),columns=columns,filters=filters)


def prepare(run, *, expected_run_config_sha256, main_admitted, account_source_kwargs_by_group):
    """Real frozen prediction only when explicitly called by the admitted root."""
    run=Path(run).resolve()
    config_ref=dict(path=str(run/'run_config.json'),sha256=expected_run_config_sha256)
    config=authority._document(config_ref)
    task=config.get('strategy_id')
    _need(task in authority.universe_variant_tasks() and run.parent.name==task,
          'AGGREGATE_EXISTING_MANAGED_RUN_REQUIRED')
    refs=config['source_inputs']
    admitted=authority.load_descriptive_authority(main_admitted)
    _need(admitted.task_id==task and admitted.window_id=='MAIN','AGGREGATE_MAIN_AUTHORITY_REQUIRED')
    schedule=authority._document(refs['window_schedule'])
    six._schedule_keys(schedule)
    main=schedule['windows'][0]
    _need(str(admitted.start.date())==main['start'] and str(admitted.end.date())==main['end'],
          'AGGREGATE_MAIN_AUTHORITY_WINDOW_CHANGED')
    projection=authority._document(refs['input_projection'])
    artifacts=projection['artifacts']
    authority._physical(artifacts['thin_adapter'])  # Historical projection-source bytes.
    runtime=config['runtime_source_refs']
    for key,source in (('aggregate_adapter',Path(adapter.__file__)),('aggregate_runner',Path(__file__))):
        _need(authority._physical(runtime[key]).resolve()==source.resolve(),'AGGREGATE_RUNTIME_SOURCE_REF_CHANGED')
    account=adapter.replay._old().config_adapter(authority._document(ACCOUNT_REF))
    model_binding=authority._document(refs['model_bindings'])['models']
    bundles={cid:frozen.load_frozen_2025(cid,model_binding[cid]['model_ref'],model_binding[cid]['receipt_ref'],admitted)
             for cid in authority.MODEL_IDS}
    original=six.load_frozen_policies(refs['evaluation_plan'])
    candidates=authority._document(refs['candidate_manifest'])['candidates']
    _need(len(candidates)==6 and all(all(row.get(k)==v for k,v in source.items())
        for row,source in zip(candidates,original)),'AGGREGATE_ORIGINAL_CANDIDATES_CHANGED')
    six._validate_policy_rows(candidates)
    context=pd.DatetimeIndex(_frame(artifacts['proxy_context_calendar'],['trade_date']).trade_date)
    dates=context[(context>=admitted.start)&(context<=admitted.end)]
    bars=_frame(artifacts['bars'],['trade_date','ticker','open','close','quality'],
        [('trade_date','>=',admitted.start),('trade_date','<=',admitted.end)])
    target=execution.own_path(run,run/'derived/aggregate_frozen_inputs')
    manifest_path=target/'FROZEN_INFERENCE_INPUTS.json'
    binding=dict(task_id=task,source_inputs=refs,original_account_ref=ACCOUNT_REF,
        runtime_source_refs=runtime,
        main_start=main['start'],main_end=main['end'],real_fit=0,scientific_selection=0)
    if manifest_path.exists():
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        _need(manifest['binding']==binding,'AGGREGATE_FROZEN_INFERENCE_BINDING_CHANGED')
        saved=manifest['artifacts']
        flags=_frame(saved['flags'])
        heads={'inference_evidence':{}}
        for cid in authority.MODEL_IDS:
            evidence=dict(bundle=bundles[cid],predictions=_frame(saved[cid+'_predictions']),
                support=_frame(saved[cid+'_support']))
            if cid in authority.MODEL_IDS[:2]: evidence['samples']=_frame(saved[cid+'_samples'])
            heads['inference_evidence'][cid]=evidence
    else:
        _need(not (run/'ACCOUNT_PATH_LOG.jsonl').exists(),'AGGREGATE_NO_INFERENCE_REBUILD_AFTER_ACCOUNT')
        _need(not target.exists() or not any(target.iterdir()),'AGGREGATE_PARTIAL_INFERENCE_FILES_REQUIRE_REVIEW')
        features=_frame(artifacts['features'],['trade_date','ticker',*adapter.inputs.FEATURES],
            [('trade_date','>=',admitted.start),('trade_date','<=',admitted.end)])
        active=_frame(artifacts['universe_ledger'],filters=[('target_date','>=',admitted.start),('target_date','<=',admitted.end)])
        snapshots=active.snapshot_id.tolist()
        pool=dict(ledger=active,schedule=_frame(artifacts['universe_schedule'],filters=[('snapshot_id','in',snapshots)]),
            members=_frame(artifacts['universe_members'],filters=[('snapshot_id','in',snapshots)]),
            dated_identity=_frame(artifacts['dated_identity'],['signal_date','ticker','security_id','is_max_group'],
                [('signal_date','>=',admitted.start),('signal_date','<=',admitted.end)]))
        history=authority._document(refs['proxy_history_binding'])
        wanted=list(dict.fromkeys((*stateful_inputs.PRED_FLAGS,*adapter.inputs.FEATURES,*adapter.decision.PRED_EXTRA)))
        _need(history['column_projection']==wanted,'AGGREGATE_ORIGINAL_CAUSAL_COLUMNS_CHANGED')
        history_flags=adapter.replay._read_projection(history['original_source_ref'],wanted,'signal_date',
            [('signal_date','>=',pd.Timestamp('2023-01-01')),('signal_date','<',pd.Timestamp('2026-01-01'))])
        _need(len(history_flags)==history['selected_rows'],'AGGREGATE_PROXY_HISTORY_ROWCOUNT_CHANGED')
        models=authority._document(projection['models_ref'])
        ranked,coverage,flags=adapter.rank_and_flags(features,pool,models,admitted)
        heads=adapter.infer_heads(flags,context,bundles,admitted,history_flags=history_flags)
        frames=dict(ranked=ranked,rank_coverage=coverage,flags=flags)
        for cid,evidence in heads['inference_evidence'].items():
            for name in ('samples','predictions','support'):
                if isinstance(evidence.get(name),pd.DataFrame): frames[cid+'_'+name]=evidence[name]
        target.mkdir(parents=True,exist_ok=True)
        saved={name:adapter.ranking.write_frame(execution.own_path(run,target/(name+'.parquet')),frame)
               for name,frame in frames.items()}
        manifest=dict(binding=binding,artifacts=saved,sample_audit=heads['sample_audit'],
            status='FROZEN_INFERENCE_READY_NO_ACCOUNT_RUN',new_fit=0,
            raw_hgb_predict_calls=1,head_predict_calls={cid:int(not heads['inference_evidence'][cid]['predictions'].empty)
                for cid in authority.MODEL_IDS})
        write_json_atomic(manifest_path,manifest)
    full=adapter.assemble_six_path_inputs(main,admitted,flags=flags,bars=bars,calendar=context,
        account=account,account_source_kwargs_by_group=account_source_kwargs_by_group,heads=heads)
    return dict(task_id=task,run=run,expected_run_config_sha256=expected_run_config_sha256,schedule=schedule,
        candidates=candidates,full_inputs=full,inference_manifest_ref=_ref(manifest_path))


def _window_inputs(prepared,window,admitted,account_sources_for_window):
    kwargs=account_sources_for_window(window,admitted)
    _need(set(kwargs)==set(prepared['full_inputs']),'AGGREGATE_EXACT_THREE_SOURCE_GROUPS')
    return {group:adapter.slice_account_inputs(full,window,admitted,account_source_kwargs=kwargs[group])
            for group,full in prepared['full_inputs'].items()}


def preflight(prepared, *, authority_for_window, account_sources_for_window):
    """Validate every window/head/source binding without running any account."""
    task=prepared['task_id']
    checked=[]
    for window in prepared['schedule']['windows']:
        admitted=authority.load_descriptive_authority(authority_for_window(window))
        _need(admitted.task_id==task and admitted.window_id==window['window_id'],
              'AGGREGATE_PREFLIGHT_WINDOW_AUTHORITY')
        groups=_window_inputs(prepared,window,admitted,account_sources_for_window)
        fingerprints=None
        for group,data in groups.items():
            market=data['market'];kwargs=data['account_source_kwargs']
            _need(kwargs.get('entitlement_enabled') is True,'AGGREGATE_EXPLICIT_CA_ENABLED')
            _need(set(kwargs)<=set(('events','known_at','unsupported','entitlement_enabled','entitlement_events',
                'entitlement_security_tickers','entitlement_source_binding')),'AGGREGATE_UNKNOWN_ACCOUNT_OVERRIDE')
            events=tuple(kwargs['entitlement_events'])
            current=tuple(e.event_fingerprint for e in events)
            if fingerprints is None: fingerprints=current
            _need(current==fingerprints,'AGGREGATE_FULL_CATALOGUE_SHARED_BY_MARKETS')
            common._entitlement_binding(events,kwargs['entitlement_security_tickers'],kwargs['entitlement_source_binding'],
                corporate_actions=tuple(kwargs.get('events',())),corporate_action_known_at=kwargs.get('known_at'))
            authority.validate_reconstructed_accounting_events(admitted,events,require_exact=True)
            common.CorporateActionTransitionAdapter(tuple(kwargs.get('events',())))
            _need(market.open.shape==market.close.shape==market.row_present.shape==market.quality.shape
                  ==(len(market.dates),len(market.tickers)),'AGGREGATE_PREFLIGHT_MATRIX_COORDINATES')
            for event in events:
                _need(pd.Timestamp('2026-01-01')<=common._entitlement_effective_day(event)<=admitted.end,
                      'AGGREGATE_EVENT_OUTSIDE_FROZEN_2026_SOURCE_SCOPE')
            for event in kwargs.get('unsupported',()):
                _need({'ticker','effective_date','reason'}<=set(event),'AGGREGATE_UNSUPPORTED_EVENT_SCHEMA')
        for candidate in prepared['candidates']:
            cid=candidate['candidate_id'];group=cid if cid in authority.PATH_IDS[4:] else 'stocks'
            data=groups[group];market=data['market']
            authority.validate_descriptive_account(admitted,market.dates,[cid],data['account'],candidate['execution_friction'])
            _need(data['account']['max_weight']==1. and data['account']['max_positions']==20
                and data['account']['max_invested']==1. and data['account']['capacity_fraction'] is None,
                'AGGREGATE_PREFLIGHT_ORIGINAL_ACCOUNT_SCALARS')
            _need(market.signal_mask[0] and str(market.dates[1].date())==window['first_execution_date'],
                  'AGGREGATE_PREFLIGHT_EXECUTION_CLOCK')
            six._inference_coverage(candidate,data,admitted)
        checked.append(dict(window_id=window['window_id'],path_count=6,source_groups=3,account_executions=0))
    report=dict(status='PASS_ALL_INPUTS_NO_ACCOUNT_EXECUTION',windows=checked,
        account_paths_checked=len(checked)*6,model_predict_calls=0,account_executions=0,
        inference_manifest_ref=prepared['inference_manifest_ref'])
    path=execution.own_path(prepared['run'],prepared['run']/'derived/AGGREGATE_EXECUTION_PREFLIGHT.json')
    write_json_atomic(path,report)
    return report


def execute(prepared, *, authority_for_window, account_sources_for_window):
    """Root-only explicit launch; a shared input failure cannot spend path slots."""
    preflight(prepared,authority_for_window=authority_for_window,
        account_sources_for_window=account_sources_for_window)
    return six.execute_durable(prepared['run'],prepared['schedule'],prepared['candidates'],
        authority_for_window=authority_for_window,
        inputs_for_window=lambda window,admitted:_window_inputs(prepared,window,admitted,account_sources_for_window),
        expected_run_config_sha256=prepared['expected_run_config_sha256'])
