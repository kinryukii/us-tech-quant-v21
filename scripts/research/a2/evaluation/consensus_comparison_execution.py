"""R12 wiring of existing source, estimator, PPO and account owners.

No read or run on import. The current human comparison scope is required by C;
this module adds no data, trading, source qualification or holdout authority.
"""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.storage.storage_r2a import write_json_atomic
from scripts.research.a2.evaluation import consensus_comparison_run as comparison
from scripts.research.a2.evaluation import consensus_method_extension as extension
from scripts.research.a2.evaluation import consensus_cash_account as cash
from scripts.research.a2.evaluation import consensus_account_source_private_consumer as C
from scripts.research.a2.data import consensus_comparison_inputs as inputs
from scripts.research.a2.training import consensus_forecast_recovery as recovery
from scripts.research.a2.training import consensus_account_rl as rl
from scripts.research.a2.training import consensus_predictors as predictors
from scripts.research.a2.risk.shared_risk_budget_r2 import LEARNED_KINDS

require = C.require
ref = comparison.ref


def checked(reference):
    path = Path(reference['path']).resolve()
    require(ref(path)['sha256'] == reference['sha256'], 'COMPARISON_RUNTIME_PIN_CHANGED')
    return path


def _metadata(reference, limit=262144):
    path = checked(reference)
    require(path.stat().st_size <= limit, 'BOUNDED_RUNTIME_METADATA_REQUIRED')
    return json.loads(path.read_text(encoding='utf8'))



def load_checkpoint(reference,expected):
    actual=checked(reference)
    require(actual==Path(expected).resolve(),'EXACT_RUNTIME_MODEL_PATH_REQUIRED')
    return joblib.load(actual)


def _atomic_joblib(path, value):
    assert_safe_output_path(path, kind='backtest', paths=resolve(predictors.REPO))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    joblib.dump(value, temporary, compress=0)
    os.replace(temporary, path)
    return ref(path)


class AsOfEvents:
    """Record offsets and identity clocks first; decode only legal event bodies."""
    def __init__(self, reference):
        self.reference, self.path = dict(reference), checked(reference)
        self.rows = []
        with self.path.open('rb') as handle:
            projection = C.inputs._JsonProjection(handle)
            projection.descend(('event_records',)); projection.expect(b'[')
            while True:
                projection.white()
                if projection.peek() == b']': projection.take(); break
                start = projection.tell()
                meta = projection.metadata_fields({'ticker','event_date'})
                end = projection.tell()
                require(end-start <= 16384, 'BOUNDED_EVENT_RECORD_REQUIRED')
                require(pd.Timestamp(meta['event_date']) < pd.Timestamp('2026-01-01'),
                        'EVENT_METADATA_PRE2026_REQUIRED')
                self.rows.append((meta['ticker'], meta['event_date'], start, end))
                projection.white()
                if projection.peek() == b',': projection.take()
                else: projection.expect(b']'); break

    def read(self, cutoff, assets):
        require(ref(self.path) == self.reference, 'EVENT_SOURCE_CHANGED')
        day = pd.Timestamp(cutoff).tz_convert('America/New_York').tz_localize(None).normalize()
        result = []
        with self.path.open('rb') as handle:
            for asset, date, start, end in self.rows:
                if asset in assets and pd.Timestamp(date) < day:
                    handle.seek(start); result.append(json.loads(handle.read(end-start)))
        return result


class NativeSource:
    def __init__(self, provider):
        self.provider = provider
        self.scope = provider.freeze['native_source_scope']
        references = self.scope['source_refs']
        self.events = AsOfEvents(references['event_binding'])
        path = checked(references['event_window_owner'])
        spec = importlib.util.spec_from_file_location('_r12_original_label_event_window', path)
        self.owner = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.owner)

    def __call__(self, cutoff, assets, domain, scope):
        require(scope == self.scope, 'NATIVE_SOURCE_SCOPE_CHANGED')
        prior = pd.Timestamp(cutoff).tz_convert('America/New_York').tz_localize(None).normalize()
        history = domain['identity_history']
        keys = history.loc[pd.to_datetime(history.signal_date).lt(prior),
                           ['signal_date','ticker','security_id']].copy()
        days = pd.DatetimeIndex(self.provider.calendar)
        start = days[max(0, days.searchsorted(prior)-326)]
        keys = keys.loc[pd.to_datetime(keys.signal_date).ge(start)]
        require(not keys.empty and set(keys.ticker) <= set(assets), 'EXACT_NATIVE_HISTORICAL_KEYS_REQUIRED')
        quotes = self.provider.reader.read('raw_open_close', ('trade_date','ticker','open'),
            date_field='trade_date', start=start, stop=prior, tickers=assets)
        return dict(keys=keys, sid_projection=keys.copy(), raw_quotes=quotes,
            event_records=self.events.read(cutoff,set(assets)), event_window=self.owner.apply_event_windows,
            source_refs=scope['source_refs'], risk_label_economic_semantics=inputs.LABEL_ECONOMICS)


class CountedStates:
    """All physical operations ACK into the existing run's one FIT_LOG."""
    def __init__(self, run, runner, input_ref):
        self.run, self.runner, self.input_ref = Path(run), runner, input_ref
        self.log = self.run/'FIT_LOG.jsonl'
        self.root = self.run/'models/consensus_comparison_runtime'
        self.root.mkdir(parents=True,exist_ok=True)
        self.reservations = self.root/'r2_reservations.jsonl'
        self.seen = {e['key'] for e in self._r2_events()}
        self.means = comparison.DiskRiskCache(self.root/'scenario_mean_store',max_resident=2)

    def _r2_events(self):
        return [] if not self.reservations.exists() else [json.loads(s) for s in
            self.reservations.read_text(encoding='utf8').splitlines() if s]

    def start(self, bucket, model, year, component, identity):
        require(not any(e.get('event')=='FIT_STARTED' and e.get('reuse_tuple_sha256')==identity
            for e in self.runner.values._events(self.log)), 'GLOBAL_SPENT_COMPONENT_NO_RETRY')
        self.runner.values._component_start(self.log,dict(max_fit_units=10000,budget_bucket=bucket),
            2063,model,int(year),component,identity)

    def reserve_r2(self,event):
        if event['kind'] not in LEARNED_KINDS: return
        require(event['key'] not in self.seen,'R2_FAILED_OR_UNCHECKPOINTED_STATE_NO_RETRY')
        year = pd.Timestamp(event['context']['cutoff']).year
        token = extension._digest(dict(input=self.input_ref,reservation=event))
        require(not any(e.get('event')=='FIT_STARTED' and e.get('reuse_tuple_sha256')==token
            for e in self.runner.values._events(self.log)), 'R2_GLOBAL_SPENT_RESERVATION_NO_RETRY')
        self.start('consensus_comparison_r2',event['name'],year,event['kind'],token)
        self.seen.add(event['key'])
        self.runner.values._append(self.reservations,event)

    def fit_bank(self,method,past,*,params,dependencies,event):
        token = extension._digest(dict(input=self.input_ref,method=method,event=event,
            params=params,columns=list(past.columns),frame=extension._data_hash(past),dependencies={k:(extension._data_hash(v) if isinstance(v,(pd.DataFrame,pd.Series)) else v) for k,v in dependencies.items()} if isinstance(dependencies,dict) else dependencies))
        root=self.root/'bank'/token; root.mkdir(parents=True,exist_ok=True)
        receipt_path=root/'receipt.json'; model_path=root/'model.joblib'
        if receipt_path.exists():
            previous=json.loads(receipt_path.read_text(encoding='utf8'))
            require(previous.get('status')=='FITTED' and previous.get('identity')==token,
                    'FAILED_OR_UNCHECKPOINTED_RUNTIME_BANK_NO_RETRY')
            return load_checkpoint(previous['model_ref'],model_path)
        require(not any(e.get('event')=='FIT_STARTED' and e.get('reuse_tuple_sha256')==token
            for e in self.runner.values._events(self.log)), 'SPENT_RUNTIME_BANK_TUPLE_NO_RETRY')
        require(2063+sum(e.get('fit_units',0) for e in self.runner.values._events(self.log)
            if e.get('event')=='FIT_STARTED')+extension.risk_fit_unit_upper(method)<=10000,
            'CUMULATIVE_FIT_BUDGET_EXHAUSTED')
        receipt=dict(status='FITTING',identity=token,fit_units=0,receipt_path=str(receipt_path),
            input_ref=self.input_ref,event=event)
        write_json_atomic(receipt_path,receipt)
        try:
            bundle=self.runner.values._fit_job('risk',method,past,None,None,None,dependencies,[],params,
                log=self.log,auth=dict(max_fit_units=10000,budget_bucket='consensus_comparison_training_risk'),
                prior=2063,year=pd.Timestamp(params['fit_cutoff']).year,tuple_sha=token,receipt=receipt,
                worker_target=extension.risk_fit_worker)
            receipt.update(status='FITTED',model_ref=_atomic_joblib(model_path,bundle))
            write_json_atomic(receipt_path,receipt); return bundle
        except BaseException as error:
            receipt.update(status='FAILED',reason=type(error).__name__+':'+str(error))
            write_json_atomic(receipt_path,receipt); raise

    def scenario_mean(self,table,*,cutoff,assets,source_refs,identity,params):
        require(tuple(table.columns)==assets and table.index.max()<cutoff<pd.Timestamp('2026-01-01'),
                'EXACT_MATURE_SCENARIO_TABLE_REQUIRED')
        key=extension._digest(dict(source=source_refs,identity=identity,params=params))
        event=dict(method='DIAG',cutoff=str(cutoff),assets=list(assets),scenario_identity=identity)
        if key not in self.means:
            self.means[key]=self.fit_bank('DIAG',table,params=params,dependencies=[],event=event)
        state=self.means[key]
        return state,dict(identity=key,model_source_ref=self.input_ref,
            stored_state_ref=dict.__getitem__(self.means,key),fit_units=state.budget['total_state_estimations'])



class CountedR2:
    """Reuse exact original R2 states across restart, with two resident per map."""
    def __init__(self,input_provider,counted):
        self.counted=counted
        self.hook=extension.R2FitHook(input_provider,durable_reserve=counted.reserve_r2)
        self.receipt_path=counted.root/'r2_hook_receipt.json'
        saved=json.loads(self.receipt_path.read_text(encoding='utf8')) if self.receipt_path.exists() else None
        if saved:
            require(saved['input_ref']==counted.input_ref and saved['runtime_ref']==ref(__file__),
                    'R2_CHECKPOINT_INPUT_OR_RUNTIME_CHANGED')
            proof=saved.get('reservation_log_prefix')
            if proof:
                path=Path(proof['path']);require(path==counted.reservations and 0<=proof['bytes']<=16777216,
                    'R2_RESERVATION_PREFIX_REQUIRED')
                with path.open('rb') as stream:
                    require(hashlib.sha256(stream.read(proof['bytes'])).hexdigest()==proof['sha256'],
                        'R2_SPENT_RESERVATION_PREFIX_CHANGED')
            require(set(saved['snapshots'])=={'states','bundles','period_states'},'EXACT_R2_CHECKPOINT_MAPS_REQUIRED')
            for name,reference in saved['snapshots'].items():
                restored=comparison._restore_risk_cache(reference)
                require(restored.root==(counted.root/('r2_'+name)).resolve() and restored.max_resident==2,
                    'EXACT_R2_CHECKPOINT_STORE_REQUIRED')
                setattr(self.hook,name,restored)
        else:
            for name in ('states','bundles','period_states'):
                setattr(self.hook,name,comparison.DiskRiskCache(counted.root/('r2_'+name),max_resident=2))
        events=counted._r2_events();self.hook.budget.events=events
        self.hook.budget._keys={e['key'] for e in events}
        for event in events:self.hook.budget.counts[event['kind']]+=1

    def __call__(self,method,*,cutoff,assets):
        out=self.hook(method,cutoff=cutoff,assets=assets)
        snapshots={name:getattr(self.hook,name).snapshot_ref() for name in ('states','bundles','period_states')}
        proof=None
        if self.counted.reservations.exists():
            proof=dict(ref(self.counted.reservations),bytes=self.counted.reservations.stat().st_size)
        write_json_atomic(self.receipt_path,dict(snapshots=snapshots,input_ref=self.counted.input_ref,
            runtime_ref=ref(__file__),reservation_log_prefix=proof))
        return out


def causal_context_observation(di,ctx):
    require(len(ctx.path_ids)==1 and np.asarray(ctx.nav).shape==(1,), 'SINGLE_RL_ACCOUNT_CONTEXT_REQUIRED')
    qualified=np.asarray(getattr(ctx,'accounting_qualified',[False]),bool)
    require(qualified.shape==(1,) and qualified.all(), 'RL_INFERENCE_CERTIFIED_CONTEXT_REQUIRED')
    require(pd.Timestamp(ctx.signal_date)<pd.Timestamp('2026-01-01'),'RL_INFERENCE_PRE2026_REQUIRED')
    nav=float(ctx.nav[0]);units=np.asarray(ctx.current_units,float)[0]
    state=dict(nav=nav,position_units=units,position_market_values=np.asarray(ctx.current_weights,float)[0]*nav,
        settled_cash=float(ctx.settled_cash[0]),unsettled_receivable=float(ctx.unsettled_cash[0]))
    return rl.account_observation(state),np.ones(5,dtype=bool)


def publication_provider(run,method,year,reader=None,*,packet_id='core5'):
    require(year in (2022,2023,2024,2025),'REAL_2026_PUBLICATION_FORBIDDEN')
    from scripts.research.a2.training import consensus_forecast_completion as completion
    recovered=year==2022 or (year==2023 and (packet_id,method) in
        {('broad29','convex'),('broad29','stack_ridge'),('multih38','convex')})
    producer=completion if recovered else recovery
    return producer.published_fusion_forecasts(run,method,year,reader,packet_id=packet_id)



def prepared_publication_provider(run):
    """Bind the pure publication reader before taking the family fit lock."""
    from scripts.research.a2.training import consensus_forecast_completion as completion
    run=Path(run).resolve();module=completion.bind_fusion(run);frozen=module._completion_ref
    def publish(actual,method,year,reader=None,*,packet_id='core5'):
        require(Path(actual).resolve()==run and year in (2022,2023,2024,2025),
                'EXACT_PRE2026_COMPARISON_PUBLICATION_RUN_REQUIRED')
        addon=year==2022 or (year==2023 and (packet_id,method) in
            {('broad29','convex'),('broad29','stack_ridge'),('multih38','convex')})
        if not addon:return recovery.published_fusion_forecasts(run,method,year,reader,packet_id=packet_id)
        require(completion.ref(run/completion.FREEZE)==frozen,'PREBOUND_COMPLETION_SCOPE_CHANGED')
        frame,published=module.published_fusion_forecasts(run,method,year,reader,packet_id=packet_id)
        return frame,dict(published,completion_route=completion.SCHEMA,completion_freeze_ref=frozen)
    return publish


class QualifiedRLBase:
    def __init__(self,base):self.base=base
    def __getattr__(self,name):return getattr(self.base,name)
    def __call__(self,di,ctx):
        decision=self.base(di,ctx)
        if self.base.diagnostics:
            require(not str(self.base.diagnostics[-1].get('status','')).startswith('NOT_TESTABLE'),
                    'RL_BASE_PTO_RISK_OR_ALLOCATION_UNQUALIFIED')
        return decision



def export_qualified_calendar(run,loaded,consumer_freeze_ref,master_scope_ref):
    """Export only the existing qualified owner calendars, never market values."""
    dates=cash.validate_calendar(loaded['market'].dates)
    settlement=cash.validate_calendar(loaded['settlement_calendar'])
    require(dates.is_unique and dates.is_monotonic_increasing and len(dates)>500
        and dates.min()>=pd.Timestamp('2023-01-01') and dates.max()<pd.Timestamp('2026-01-01')
        and set(dates.year)=={2023,2024,2025},'FULL_QUALIFIED_DEVELOPMENT_CALENDAR_REQUIRED')
    require(settlement.is_unique and settlement.is_monotonic_increasing and len(settlement)>500
        and settlement.min()>=pd.Timestamp('2023-01-01') and settlement.max()<pd.Timestamp('2026-01-01')
        and set(settlement.year)=={2023,2024,2025},'EXACT_EXISTING_SETTLEMENT_CALENDAR_REQUIRED')
    value=dict(schema='CONSENSUS_COMPARISON_ACCOUNT_CALENDAR_R12',master_scope_ref=master_scope_ref,
        consumer_freeze_ref=consumer_freeze_ref,full_account_calendar=True,
        account_sessions=[d.date().isoformat() for d in dates],
        settlement_sessions=[d.date().isoformat() for d in settlement],
        calendar_source_ref=loaded['scope']['calendar_ref'],
        settlement_calendar_source_ref=loaded['scope']['settlement_calendar_ref'],
        source='ACTUAL_C_QUALIFIED_LOADED_ARRAYS_METADATA_ONLY',market_values_exported=False)
    path=Path(run)/'COMPARISON_QUALIFIED_ACCOUNT_CALENDAR.json'
    if path.exists():require(json.loads(path.read_text(encoding='utf8'))==value,'QUALIFIED_CALENDAR_CHANGED')
    else:write_json_atomic(path,value)
    return ref(path)


def execute(run,runner,route,freeze_ref,config):
    """One family process: source setup -> upstream-ready callbacks -> accounts."""
    run=Path(run).resolve()
    require(config.get('runtime_source_ref')==ref(__file__),'REVIEWED_RUNTIME_SOURCE_PIN_REQUIRED')
    scope=_metadata(config['comparison_scope_ref'])
    require(config['method_matrix_scope_ref']==ref(run/'CONSENSUS_METHOD_MATRIX_FREEZE.json'),
            'EXACT_MATRIX_EXECUTION_SCOPE_REQUIRED')
    publisher=prepared_publication_provider(run)
    with predictors.fit_lock(run):
        bound=runner.account_inputs.metadata_preflight(frozen_contract_ref=freeze_ref,
            source_scope_ref=route['reader_scope_ref'])
        reader_root=C.routing.FEATURE_ORIGIN
        reader=runner.ConsensusInputs(reader_root,reader_root/'derived/consensus100_daily.parquet')
        _,pf,_=predictors.contract(reader_root,'ridge',2023,5); predictors.reader_integrity(reader,pf)
        adv,returns,_=runner.qualified_vectors(reader,bound['scope'])
        loaded=runner.account_inputs.load_account_inputs(bound,signal_adv_by_key=adv); loaded['returns']=returns
        export_qualified_calendar(run,loaded,freeze_ref,config['comparison_scope_ref'])
        provider=inputs.ComparisonInputProvider(config['comparison_input_freeze_ref'])
        provider.native_source_provider=NativeSource(provider)
        counted=CountedStates(run,runner,config['comparison_input_freeze_ref'])
        r2_fit=CountedR2(provider.typed_r2,counted)
        market=loaded['market']; dates=pd.DatetimeIndex(market.dates)
        def scenarios(date,full,required):
            if not required:return None
            return provider.scenario(date,required,mean_state_provider=counted.scenario_mean,
                account_assets=full,inactive_zero_padding_assets=tuple(a for a in full if a not in set(required)))
        def references(date,full,required):
            require(tuple(map(str,market.tickers))==full,'REFERENCE_ACCOUNT_ORDER_CHANGED')
            return provider.reference(market,int(dates.get_loc(pd.Timestamp(date))))
        rl_factory=FrozenRLFactory(run,runner,scope,reader,provider,counted,r2_fit,config,publisher)
        return comparison.run_all(run,runner,loaded,reader,freeze_ref,scope,
            bank_dependencies=provider.bank_dependencies,r2_fit=r2_fit,scenarios=scenarios,
            references=references,rl_factory=rl_factory,publication_provider=publisher)


def validate_rl_upstream(pin,schedule,specification):
    upstream=pin.get('publication_receipt_ref')
    require(isinstance(upstream,dict) and set(upstream)>={'path','sha256'}
        and upstream in schedule['upstream_forecast_refs'] and pin.get('year')==2022
        and pin.get('packet_id')==specification['packet_id']
        and pin.get('method')==specification['fusion_method'],
        'RL_2022_EXACT_UPSTREAM_PUBLICATION_REQUIRED')
    checked(upstream)


def rl_fit_identity(coordinate,config,risk_input_ref,scope):
    return extension._digest(dict(coordinate=coordinate,source=config['rl_source_binding_ref'],
        schedule=config['rl_causal_schedule_ref'],runtime=ref(__file__),risk_input_ref=risk_input_ref,
        comparison_scope_ref=config['comparison_scope_ref'],
        risk_combination=scope['comparison']['risk_combinations'][coordinate[1]],account=scope['account']))


class FrozenRLFactory:
    """Train only on the separately admitted 2022 source; outer usage is frozen."""
    def __init__(self,run,runner,scope,reader,provider,counted,r2_fit,config,publisher):
        self.run,self.runner,self.scope,self.reader=run,runner,scope,reader
        self.provider,self.counted,self.r2_fit,self.config=provider,counted,r2_fit,config
        self.loaded=None;self.fits={};self.publisher=publisher
        self.cache=comparison.DiskRiskCache(counted.root/'rl_training_risk_store',max_resident=2)

    def __call__(self,method,forecasts,past_daily_returns,*,config,fee_config,base_policy,**kwargs):
        coordinate=base_policy.matrix_coordinate
        key=(coordinate['forecast_pack'],coordinate['risk_combination'],method)
        identity=rl_fit_identity(key,self.config,self.counted.input_ref,self.scope)
        root=self.counted.root/'rl'/identity;root.mkdir(parents=True,exist_ok=True)
        receipt_path=root/'receipt.json';model_path=root/'policy.joblib'
        if key not in self.fits:
            if receipt_path.exists():
                receipt=json.loads(receipt_path.read_text(encoding='utf8'))
                require(receipt.get('status')=='FITTED' and receipt.get('identity')==identity,
                    'FAILED_OR_UNCHECKPOINTED_RL_TUPLE_NO_RETRY')
                self.fits[key]=load_checkpoint(receipt['model_ref'],model_path)
            else:
                from scripts.research.a2.data import consensus_rl_source_2021_2022 as sources
                if self.loaded is None:self.loaded=sources.load_account_inputs(self.config['rl_source_binding_ref'])
                schedule_ref=self.config['rl_causal_schedule_ref'];schedule=_metadata(schedule_ref)
                specification=self.scope['comparison']['forecast_packs'][key[0]]
                frame,pin=self.publisher(self.run,specification['fusion_method'],2022,self.reader,
                    packet_id=specification['packet_id'])
                validate_rl_upstream(pin,schedule,specification)
                causal_forecasts=self.runner.compatible_forecasts(frame)
                frozen=comparison.extension_scope(self.scope)
                base_coordinate=extension.Coordinate(key[0],key[1],'cost_aware')
                binding=extension.bind_joint(self.runner.joint,scope=frozen,coordinate=base_coordinate,
                    bank_fit=self.counted.fit_bank,bank_dependencies=self.provider.bank_dependencies,r2_fit=self.r2_fit)
                def policy_factory(year,market):
                    require(year==2022,'RL_2022_REWARD_ONLY')
                    return QualifiedRLBase(binding.ConsensusJointPolicy(causal_forecasts,self.loaded['returns'],
                        config=binding.PolicyConfig(key[1],'cost_aware',120),fee_config=fee_config,shared_risk_cache=self.cache))
                receipt=dict(status='FITTING',identity=identity,coordinate=list(key),fit_units=0,
                    source_ref=self.config['rl_source_binding_ref'],schedule_ref=schedule_ref,training_reward_years=[2022],
                    outer_rewards_used=False)
                write_json_atomic(receipt_path,receipt)
                def started(event):
                    token=extension._digest(dict(identity=identity,event=event,physical_ordinal=receipt['fit_units']))
                    self.counted.start('consensus_comparison_rl',method,2022,event['component'],token)
                    receipt['fit_units']+=1;write_json_atomic(receipt_path,receipt)
                try:
                    env=sources.account_environment_2022(self.loaded,policy_factory,schedule_ref)
                    fitted=sources.fit_activity_policy_2022(method.removeprefix('rl_'),env,
                        on_fit_started=started,schedule_ref=schedule_ref)
                    require(isinstance(fitted,rl.auxiliary.RLFit),'RL_ACTUAL_SOURCE_REWARD_FIT_NOT_TESTABLE:'+str(fitted.get('reason','NO_RLFIT'))[:512] if isinstance(fitted,dict) else 'RL_ACTUAL_SOURCE_REWARD_FIT_NOT_TESTABLE')
                    fitted._model=None
                    receipt.update(status='FITTED',model_ref=_atomic_joblib(model_path,fitted),fit_receipt=fitted.receipt)
                    write_json_atomic(receipt_path,receipt);self.fits[key]=fitted
                except BaseException as error:
                    receipt.update(status='FAILED',reason=type(error).__name__+':'+str(error))
                    write_json_atomic(receipt_path,receipt);raise
        return rl.FrozenActivityPolicy(base_policy,self.fits[key],causal_context_observation,rl.activity_delta_gate)
