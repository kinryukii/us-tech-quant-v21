"""Synthetic runtime wiring tests; no real Source, market, models or fit worker."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.evaluation import consensus_comparison_execution as runtime
from scripts.research.a2.training import stateful_values as values


@pytest.fixture
def counted(tmp_path,monkeypatch):
    monkeypatch.setattr(runtime,'assert_safe_output_path',lambda *a,**k:None)
    monkeypatch.setattr(runtime.comparison,'assert_safe_output_path',lambda *a,**k:None)
    monkeypatch.setattr(values,'assert_write_path',lambda *a,**k:None)
    from scripts.storage import storage_r2a
    monkeypatch.setattr(storage_r2a,'assert_write_path',lambda *a,**k:None)
    return runtime.CountedStates(tmp_path,SimpleNamespace(values=values),dict(path='synthetic://input',sha256='a'*64))


def test_event_numeric_bodies_are_decoded_only_after_clock_and_asset_metadata(tmp_path,monkeypatch):
    path=tmp_path/'events.json'
    path.write_text(json.dumps(dict(event_records=[
        dict(ticker='A',event_date='2022-01-03',quantity_multiplier=2.),
        dict(ticker='A',event_date='2025-01-03',quantity_multiplier='FUTURE_NUMERIC_POISON'),
        dict(ticker='B',event_date='2021-01-03',quantity_multiplier='OTHER_ASSET_POISON')])))
    original=json.loads
    def guarded(raw,*a,**k):
        assert 'NUMERIC_POISON' not in str(raw) and 'ASSET_POISON' not in str(raw)
        return original(raw,*a,**k)
    monkeypatch.setattr(runtime.json,'loads',guarded)
    source=runtime.AsOfEvents(runtime.ref(path))
    rows=source.read(pd.Timestamp('2023-01-03T21:00:00Z'),{'A'})
    assert len(rows)==1 and rows[0]['quantity_multiplier']==2.


def test_runtime_reserves_same_global_counter_and_does_not_refund_duplicate(counted):
    event=dict(key='a'*64,kind='covariance',name='synthetic-cov',context=dict(cutoff='2022-01-01'),parameters={})
    counted.reserve_r2(event)
    with pytest.raises(ValueError,match='NO_RETRY'):counted.reserve_r2(event)
    rows=values._events(counted.log)
    assert len(rows)==1 and rows[0]['event']=='FIT_STARTED' and rows[0]['fit_units']==1
    assert rows[0]['budget_bucket']=='consensus_comparison_r2'
    assert counted._r2_events()==[event]


def test_account_observation_reuses_original_four_fields_and_refuses_uncertified():
    ctx=SimpleNamespace(path_ids=('one',),nav=np.array([3000.]),current_units=np.array([[2.,1.]]),
        current_weights=np.array([[.1,.05]]),settled_cash=np.array([2400.]),unsettled_cash=np.array([150.]),
        accounting_qualified=np.array([True]),signal_date=pd.Timestamp('2025-01-03'))
    observation,legal=runtime.causal_context_observation(0,ctx)
    np.testing.assert_allclose(observation,[.8,.05,.15,.1]);assert legal.all()
    ctx.accounting_qualified[0]=False
    with pytest.raises(ValueError,match='CERTIFIED'):runtime.causal_context_observation(0,ctx)


def test_publication_dispatch_is_explicit_and_never_opens_2026(monkeypatch):
    from scripts.research.a2.training import consensus_forecast_completion as completion
    monkeypatch.setattr(completion,'published_fusion_forecasts',lambda *a,**k:'addon')
    monkeypatch.setattr(runtime.recovery,'published_fusion_forecasts',lambda *a,**k:'original')
    assert runtime.publication_provider(None,'equal',2022,packet_id='core5')=='addon'
    assert runtime.publication_provider(None,'convex',2023,packet_id='broad29')=='addon'
    assert runtime.publication_provider(None,'equal',2023,packet_id='core5')=='original'
    with pytest.raises(ValueError,match='2026'):runtime.publication_provider(None,'equal',2026)


def _fixture_module():
    path=Path(__file__).with_name('test_consensus_method_extension.py')
    spec=importlib.util.spec_from_file_location('_r12_synthetic_extension_fixture',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def test_real_r2_owner_restarts_from_exact_frozen_state_without_new_fit(counted):
    typed,january,provider=_fixture_module().advancing_r2_provider()
    first=runtime.CountedR2(provider,counted)
    bundle,key=first('RU',cutoff=january,assets=typed.assets)
    before=sum(e['fit_units'] for e in values._events(counted.log))
    assert before>0 and bundle.status=='FITTED'
    second_counted=runtime.CountedStates(counted.run,counted.runner,counted.input_ref)
    restarted=runtime.CountedR2(provider,second_counted)
    recovered,recovered_key=restarted('RU',cutoff='2025-02-03',assets=typed.assets)
    assert recovered_key==key and recovered.fitted_state['typed_state'].risk_state_id==bundle.fitted_state['typed_state'].risk_state_id
    assert restarted.hook.last_reservation_delta==0
    assert sum(e['fit_units'] for e in values._events(counted.log))==before
    assert all(v.max_resident==2 for v in (restarted.hook.states,restarted.hook.bundles,restarted.hook.period_states))


def test_r2_resume_rejects_changed_input_identity(counted):
    typed,january,provider=_fixture_module().advancing_r2_provider()
    runtime.CountedR2(provider,counted)('RU',cutoff=january,assets=typed.assets)
    counted.input_ref=dict(path='synthetic://changed',sha256='b'*64)
    with pytest.raises(ValueError,match='INPUT_OR_RUNTIME_CHANGED'):runtime.CountedR2(provider,counted)


def test_global_spent_r2_survives_missing_auxiliary_reservation_append(counted):
    event=dict(key='c'*64,kind='covariance',name='synthetic-cov',context=dict(cutoff='2022-01-01'),parameters={})
    token=runtime.extension._digest(dict(input=counted.input_ref,reservation=event))
    counted.start('consensus_comparison_r2',event['name'],2022,event['kind'],token)
    assert not counted.reservations.exists()
    restarted=runtime.CountedStates(counted.run,counted.runner,counted.input_ref)
    with pytest.raises(ValueError,match='GLOBAL_SPENT_RESERVATION'):restarted.reserve_r2(event)
    assert len(values._events(counted.log))==1 and not counted.reservations.exists()


def test_prebound_publication_reads_under_account_lock_without_rebinding(tmp_path,monkeypatch):
    from scripts.research.a2.training import consensus_forecast_completion as completion
    run=tmp_path.resolve();(run/completion.FREEZE).write_text('{}')
    frozen=runtime.ref(run/completion.FREEZE);calls=[];locked=[False]
    def bind(actual):
        assert not locked[0];calls.append('bind')
        return SimpleNamespace(_completion_ref=frozen,published_fusion_forecasts=lambda *a,**k:('frame',{'year':2022}))
    monkeypatch.setattr(completion,'bind_fusion',bind)
    publish=runtime.prepared_publication_provider(run);locked[0]=True
    frame,pin=publish(run,'equal',2022,packet_id='core5')
    assert frame=='frame' and pin['completion_freeze_ref']==frozen and calls==['bind']
    with pytest.raises(ValueError,match='PRE2026'):publish(run,'equal',2026)


def test_rl_upstream_requires_actual_exact_nonempty_reference(tmp_path):
    spec=dict(packet_id='core5',fusion_method='equal')
    with pytest.raises(ValueError,match='EXACT_UPSTREAM'):
        runtime.validate_rl_upstream({},dict(upstream_forecast_refs=[{}]),spec)
    path=tmp_path/'publication.json';path.write_text('{}');reference=runtime.ref(path)
    pin=dict(publication_receipt_ref=reference,year=2022,packet_id='core5',method='equal')
    runtime.validate_rl_upstream(pin,dict(upstream_forecast_refs=[reference]),spec)
    pin['year']=2023
    with pytest.raises(ValueError,match='EXACT_UPSTREAM'):
        runtime.validate_rl_upstream(pin,dict(upstream_forecast_refs=[reference]),spec)


def test_rl_training_base_rejects_unqualified_pto_instead_of_learning_cash_only():
    base=SimpleNamespace(diagnostics=[],__call__=lambda *a:None)
    class Base:
        diagnostics=[dict(status='NOT_TESTABLE_RISK_PRESERVE_UNITS')]
        def __call__(self,*args):return 'decision'
    with pytest.raises(ValueError,match='BASE_PTO'):
        runtime.QualifiedRLBase(Base())(0,None)


def test_r2_bundle_restart_can_write_same_global_cache_key_without_new_fit(counted):
    typed,january,provider=_fixture_module().advancing_r2_provider()
    first=runtime.CountedR2(provider,counted);bundle,key=first('RU',cutoff=january,assets=typed.assets)
    shared=runtime.comparison.DiskRiskCache(counted.root/'shared',max_resident=2);shared[key]=bundle
    original=dict.__getitem__(shared,key).copy();snapshot=shared.snapshot_ref()
    restarted=runtime.CountedR2(provider,runtime.CountedStates(counted.run,counted.runner,counted.input_ref))
    recovered,key2=restarted('RU',cutoff='2025-02-03',assets=typed.assets)
    restored=runtime.comparison._restore_risk_cache(snapshot);restored[key2]=recovered
    assert dict.__getitem__(restored,key2)==original
    assert recovered.fitted_state['typed_state'].risk_state_id==bundle.fitted_state['typed_state'].risk_state_id


@pytest.mark.parametrize('defect',['redirect','tamper'])
def test_checkpoint_checks_the_same_exact_file_before_any_pickle_decode(tmp_path,monkeypatch,defect):
    original=tmp_path/'model.joblib';other=tmp_path/'other.joblib'
    runtime.joblib.dump({'frozen':'original'},original);runtime.joblib.dump({'frozen':'other'},other)
    reference=runtime.ref(original)
    if defect=='redirect':reference=runtime.ref(other)
    else:original.write_bytes(b'changed-unchecked-pickle')
    monkeypatch.setattr(runtime.joblib,'load',lambda *a,**k:pytest.fail('bad path must not be decoded'))
    with pytest.raises(ValueError,match='PIN_CHANGED|MODEL_PATH_REQUIRED'):
        runtime.load_checkpoint(reference,original)


def test_global_rl_component_rejects_spent_ordinal_even_without_receipt(counted):
    identity='e'*64
    counted.start('consensus_comparison_rl','rl_ppo',2022,'NETWORK',identity)
    restarted=runtime.CountedStates(counted.run,counted.runner,counted.input_ref)
    with pytest.raises(ValueError,match='GLOBAL_SPENT_COMPONENT'):
        restarted.start('consensus_comparison_rl','rl_ppo',2022,'NETWORK',identity)
    assert len(values._events(counted.log))==1
    restarted.start('consensus_comparison_rl','rl_reinforce',2022,'BASELINE_EPOCH2','f'*64)
    assert len(values._events(counted.log))==2


def test_rl_fit_identity_binds_actual_risk_inputs_parameters_and_account():
    import copy
    config=dict(rl_source_binding_ref={'sha256':'a'*64},rl_causal_schedule_ref={'sha256':'b'*64},
        comparison_scope_ref={'sha256':'c'*64})
    scope=dict(comparison=dict(risk_combinations={'MIX':dict(members=['LW','RE'],weights=[.5,.5])}),
        account=dict(initial_cash=3000,one_way_all_in_bps=10))
    key=('core5__equal','MIX','rl_ppo');input_ref={'sha256':'d'*64}
    original=runtime.rl_fit_identity(key,config,input_ref,scope)
    assert original!=runtime.rl_fit_identity(key,config,{'sha256':'e'*64},scope)
    changed=copy.deepcopy(scope);changed['comparison']['risk_combinations']['MIX']['weights']=[.25,.75]
    assert original!=runtime.rl_fit_identity(key,config,input_ref,changed)
    changed=copy.deepcopy(scope);changed['account']['one_way_all_in_bps']=25
    assert original!=runtime.rl_fit_identity(key,config,input_ref,changed)


def test_calendar_observer_exports_actual_arrays_only_and_rejects_sparse_year_labels(counted):
    dates=pd.bdate_range('2023-01-02','2025-12-31')
    loaded=dict(market=SimpleNamespace(dates=dates),settlement_calendar=dates,
        scope=dict(calendar_ref={'sha256':'a'*64},settlement_calendar_ref={'sha256':'b'*64}))
    reference=runtime.export_qualified_calendar(counted.run,loaded,{'sha256':'c'*64},{'sha256':'d'*64})
    saved=json.loads(Path(reference['path']).read_text())
    assert len(saved['account_sessions'])==len(dates) and not saved['market_values_exported']
    assert saved['settlement_calendar_source_ref']==loaded['scope']['settlement_calendar_ref']
    loaded['market'].dates=pd.DatetimeIndex(['2023-01-02','2024-01-02','2025-01-02'])
    with pytest.raises(ValueError,match='FULL_QUALIFIED'):
        runtime.export_qualified_calendar(counted.run,loaded,{'sha256':'c'*64},{'sha256':'d'*64})


def test_calendar_observer_preserves_independent_exchange_and_bank_days(counted):
    from scripts.research.a2.evaluation import consensus_cash_account as cash
    all_days=pd.bdate_range('2023-01-02','2025-12-31')
    exchange=all_days.drop(pd.Timestamp('2023-04-07'))
    bank=all_days.drop(pd.Timestamp('2023-10-09'))
    assert not exchange.isin(bank).all() and not bank.isin(exchange).all()
    loaded=dict(market=SimpleNamespace(dates=exchange),settlement_calendar=bank,
        scope=dict(calendar_ref={'sha256':'a'*64},settlement_calendar_ref={'sha256':'b'*64}))
    pin=runtime.export_qualified_calendar(counted.run,loaded,{'sha256':'c'*64},{'sha256':'d'*64})
    saved=json.loads(Path(pin['path']).read_text())
    assert saved['account_sessions']==[d.date().isoformat() for d in exchange]
    assert saved['settlement_sessions']==[d.date().isoformat() for d in bank]
    assert cash.settlement_date('2023-10-06',bank,trading_calendar=exchange)==pd.Timestamp('2023-10-11')
    assert cash.settlement_date('2023-04-06',bank,trading_calendar=exchange)==pd.Timestamp('2023-04-10')


@pytest.mark.parametrize('bad',['empty','duplicate','unsorted','before','after','missing_year','nat','tz','intraday','weekend'])
def test_calendar_observer_rejects_malformed_or_outside_boundary_settlement(counted,bad):
    dates=pd.bdate_range('2023-01-02','2025-12-31')
    invalid={'empty':pd.DatetimeIndex([]),'duplicate':dates.append(dates[-1:]),
        'unsorted':dates[::-1],'before':pd.DatetimeIndex(['2022-12-30']).append(dates),
        'after':dates.append(pd.DatetimeIndex(['2026-01-02'])),'missing_year':dates[dates.year!=2024],
        'nat':dates.append(pd.DatetimeIndex([pd.NaT])),'tz':dates.tz_localize('UTC'),
        'intraday':dates+pd.Timedelta(hours=1),
        'weekend':dates.append(pd.DatetimeIndex(['2025-12-27'])).sort_values()}[bad]
    loaded=dict(market=SimpleNamespace(dates=dates),settlement_calendar=invalid,
        scope=dict(calendar_ref={'sha256':'a'*64},settlement_calendar_ref={'sha256':'b'*64}))
    with pytest.raises(ValueError,match='EXACT_EXISTING_SETTLEMENT_CALENDAR_REQUIRED|Explicit ordered US equity session calendar required'):
        runtime.export_qualified_calendar(counted.run,loaded,{'sha256':'c'*64},{'sha256':'d'*64})
