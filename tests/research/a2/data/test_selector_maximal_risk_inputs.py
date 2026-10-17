"""Small synthetic payloads; no real publication, state, label or science call."""
import copy
import importlib.util
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.data import selector_maximal_risk_inputs as m
from scripts.research.a2.risk.event_risk_contract_r5 import structural_identity


_TEMPLATE = None


@pytest.fixture
def setup(tmp_path, monkeypatch):
    # Reuse the original synthetic roster builder, never read a real design/run.
    test_path = Path(__file__).with_name('test_selector_maximal_risk_binding.py')
    spec = importlib.util.spec_from_file_location('c14_inputs_original_synthetic', test_path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    matrix = module.matrix.__wrapped__()
    dates = [pd.Timestamp(d).isoformat() for d in matrix['roles'][0]['required_dates']]
    active = {'C14_RX_HGB_LW', 'C14_D01', 'C14_D05'}
    for r in matrix['roles']:
        r['required_dates'] = dates.copy()
        if r['current_status'] == 'WAITING_R5_PUBLICATION' and r['role'] not in active:
            r['current_status'] = 'BLOCKED_BY_CURRENT_B_SCOPE'
    frozen_matrix = copy.deepcopy(matrix)
    monkeypatch.setattr(m.b, 'frozen_contract', lambda: (None, None))
    monkeypatch.setattr(m.b, 'requirement_matrix', lambda *_: copy.deepcopy(frozen_matrix))
    run = tmp_path / 'run'; run.mkdir()
    bank_root = tmp_path / 'original-r5'; bank_root.mkdir()
    monkeypatch.setattr(m.b, 'RUN', run)
    monkeypatch.setattr(m.b.contract, 'B_RUN', bank_root)
    def synthetic_backtest_route(path, *, kind):
        assert kind == 'backtest' and Path(path).resolve().is_relative_to(bank_root.resolve())
    monkeypatch.setattr(m.b.contract, 'assert_safe_output_path', synthetic_backtest_route)
    global _TEMPLATE
    if _TEMPLATE is None:
        assets = [f'A{i:03d}' for i in range(40)]
        uids = {a: f'{i:09d}' for i, a in enumerate(assets)}
        epochs = {a: 'synthetic-epoch' for a in assets}
        starts = {a: '2022-12-01' for a in assets}
        signature = dict(ordered_assets=assets.copy(), asset_uids=uids.copy(), asset_epochs=epochs.copy())
        at = m.current_owner._clock(pd.Timestamp(dates[0]))
        cutoff = at - pd.Timedelta(days=3)
        event = dict(event_id='event-0', decision_date=str(pd.Timestamp(dates[0]).date()), decision_asof=at.isoformat(),
            requested_assets=assets.copy(), asset_uids=uids.copy(), asset_epochs=epochs.copy(), segment_starts=starts.copy(),
            complete_structural_signature=signature, structural_signature_sha256=m.b.content_hash(signature),
            dependency_local_event_ids={'PRIMARY': 'primary-0'}, dependency_local_signature_sha256={'PRIMARY': 'a'*64})
        pool = dict(assets=assets.copy(), asset_uids=uids.copy(), asset_epochs=epochs.copy(), segment_starts=starts.copy(), blocked_assets={})
        raw = pd.DataFrame([dict(signal_date=pd.Timestamp(d), ticker=a, security_uid='CUSIP:'+uids[a],
            U_t_fingerprint='synthetic-frozen-U', raw_rank=i+1) for d in dates for i, a in enumerate(assets)], columns=m.current_owner.RAW_META)
        current = {}
        for d, frame in raw.groupby('signal_date', sort=True):
            current[d.isoformat()] = m.current_owner.bind_current(frame, pool, event, m.current_owner._clock(d), {'primary': 'b'*64})
        _TEMPLATE = copy.deepcopy((assets,uids,epochs,starts,at,cutoff,event,raw,current))
    assets,uids,epochs,starts,at,cutoff,event,raw,current = copy.deepcopy(_TEMPLATE)
    # The exact native project/load entrypoints are stubbed; original binding,
    # payload sealing, namespace and numeric validation remain real.
    publication = m.b.PublicationBinding({}, {'events': [event]}, {}, {}, {})
    refs = {n: dict(path=str(bank_root / (n+'.json')), sha256='c'*64) for n in ('bank','freeze','qualification','ledger')}
    records = {}
    bindings = {}
    for family in ('LW', 'OAS'):
        path = bank_root / (family+'.joblib')
        path.write_bytes(('synthetic opaque '+family).encode())
        ref = dict(path=str(path), sha256=m.b.sha(path))
        c = current[dates[0]]
        binding = dict(family=family, method='synthetic::'+family, recipe_sha256='d'*64,
            parameters={'frozen':1}, history_recipe={'frozen':1}, representation='CONTINUOUS')
        record = dict(family=family, method=binding['method'], recipe_sha256=binding['recipe_sha256'],
            parameters=binding['parameters'], history_recipe=binding['history_recipe'], representation='CONTINUOUS',
            status='PASS_FROZEN_HISTORY_MECHANISM', strict_PIT_promotion_eligible=False,
            assets=assets.copy(), asset_uids=uids.copy(), asset_epochs=epochs.copy(),
            source_support_identity=c['source_support_identity'], security_coordinate=c['security_coordinate'],
            risk_state_id='synthetic-state-'+family, artifact_ref=ref, horizon_sessions=5,
            as_of=at.isoformat(), cutoff=cutoff.isoformat(), available_at=at.isoformat(),
            available_at_basis='FROZEN_EVENT_CLOSE_REPLAY_ASSUMPTION',
            structural_identity=structural_identity(assets=tuple(assets),uids=uids,epochs=epochs,
                security_coordinate=c['security_coordinate'],source_support_identity=c['source_support_identity']),
            event_policy_binding={'frozen':'event-0'}, source_still_valid=True, maturity_still_valid=True,
            coverage_dates=dates.copy(), psd_qualified='DEFERRED_NUMERIC_EXACT_OWNER_CHECK', finite_check=True,
            covariance_sha256=None)
        records[family], bindings[family] = record, binding
    projects, loads = [], []
    def project(pub, requirement, *, current, decision_asof):
        assert pub is publication
        projects.append((requirement['role'], str(decision_asof)))
        family = requirement['required_family_method']
        return m.b.bind_role_metadata(requirement, records[family], current, decision_asof,
                                     bindings[family], refs, required_dates=dates)
    def load(meta, pub, *, source_review):
        assert pub is publication and source_review['status'] == 'PASS'
        loads.append(meta.family)
        values = dict(family=meta.family,ordered_U=meta.current['assets'].copy(),
            uids=copy.deepcopy(meta.current['asset_uids']),epochs=copy.deepcopy(meta.current['asset_epochs']),
            covariance=np.eye(40),state_id=meta.header['risk_state_id'],method=meta.header['method'],
            recipe_sha256=meta.recipe_sha256,horizon_sessions=5,cutoff=meta.header['cutoff'],as_of=meta.header['as_of'],
            source_support_identity=copy.deepcopy(meta.current['source_support_identity']),parameters=copy.deepcopy(meta.parameters))
        return m.b.NativeRiskPayload(values,meta._seal,copy.deepcopy(meta.header['artifact_ref']),m.b.content_hash(values['covariance']))
    monkeypatch.setattr(m.b, 'project_r5_role', project)
    monkeypatch.setattr(m.b, 'load_qualified_state', load)
    review = dict(status='PASS', research_id=m.b.contract.ID, adapter_sha256=m.OWNER_PINS['data/selector_maximal_risk_binding.py'],
                  source_pins=m.source_pins())
    review_path = run / 'RISK_INPUT_SOURCE_REVIEW_R1.json'
    def save_review():
        review_path.write_text(json.dumps(review,sort_keys=True),encoding='utf-8')
        return dict(path=str(review_path),sha256=m.b.sha(review_path))
    ref = save_review()
    def make():
        return m.RiskInputs(publication,matrix,current,raw,source_review=review,source_review_ref=ref)
    return dict(make=make,review=review,review_ref=ref,save_review=save_review,matrix=matrix,current=current,raw=raw,
        publication=publication,dates=dates,records=records,projects=projects,loads=loads,load=load,project=project,
        active=active)


def test_complete_full752_gates_exact_cache_and_immutable_rebinding(setup):
    s=setup; inputs=s['make']()
    assert not s['loads'] and not s['projects']
    with pytest.raises(ValueError,match='FULL752'): inputs.get_risk('C14_D01',s['dates'][0])
    status=inputs.qualify()
    assert len(status['roles'])==23 and len(s['loads'])==2 and set(s['loads'])=={'LW','OAS'}
    assert status['counts']['native_states_loaded']==2
    assert inputs.role_gate('C14_D01') == status['roles']['C14_D01']
    with pytest.raises(ValueError,match='FULL752'): inputs.role_gate('C14_D02')
    for role in s['active']:
        gate=status['roles'][role]
        assert gate['phase']=='FULL752_NUMERIC_INPUT_QUALIFIED' and gate['full_required_dates_qualified']
        assert [x['decision_date'] for x in gate['states']]==s['dates']
        assert (gate['calendar_positions'],gate['full_risk_mature_positions'],gate['learned_positions'])==(752,732,482)
        assert not gate['realized_endpoint_qualified'] and not gate['strict_PIT_promotion_eligible']
    first,p1=inputs.get_risk('C14_D01',s['dates'][0]); last,p2=inputs.get_risk('C14_RX_HGB_LW',s['dates'][-1])
    assert first.header['as_of']==last.header['as_of'] and first.header['cutoff']==last.header['cutoff']
    assert first.decision_asof!=last.decision_asof and p1.metadata_seal==first._seal and p2.metadata_seal==last._seal
    assert p1['covariance'] is p2['covariance'] and len(s['loads'])==2
    with pytest.raises(ValueError): p1['covariance'][0,0]=9
    with pytest.raises(ValueError): p1['covariance'].setflags(write=True)
    p1.values['method']='caller-mutation'
    _,p3=inputs.get_risk('C14_D01',s['dates'][1]); assert p3['method']!='caller-mutation'
    with pytest.raises(ValueError,match='SINGLE_PASS'): inputs.qualify()
    assert all(status['counts'][k]==0 for k in ('selector_fit','risk_estimator_fit','solver','bootstrap','test2026_rows_read','EF_access','provider_fetch'))


@pytest.mark.parametrize('case',['status','missing_self','wrong_adapter','wrong_current','review_sha','review_body','short_current','short_raw','matrix','mask'])
def test_constructor_blocks_before_first_native_load(setup,case):
    s=setup
    if case=='status': s['review']['status']='BLOCKED'
    elif case=='missing_self': s['review']['source_pins'].pop(str(Path(m.__file__).resolve()))
    elif case=='wrong_adapter': s['review']['adapter_sha256']='0'*64
    elif case=='wrong_current': s['review']['source_pins'][str(Path(m.current_owner.__file__).resolve())]='0'*64
    elif case=='review_sha': s['review_ref']['sha256']='0'*64
    elif case=='review_body': s['review']['extra']='changed without physical update'
    elif case=='short_current': s['current'].pop(s['dates'][-1])
    elif case=='short_raw': s['raw'].drop(s['raw'].index[-40:],inplace=True)
    elif case=='matrix': s['matrix']['roles'][0]['required_family_method']='invented'
    elif case=='mask': s['matrix']['roles'][0]['learned_support_mask']=481
    if case in ('missing_self','wrong_adapter','wrong_current'): s['review_ref'].update(s['save_review']())
    with pytest.raises(ValueError): s['make']()
    assert not s['loads']


@pytest.mark.parametrize('case',['native_uid','epoch','source','namespace','key_sha','raw_uid','raw_rank','future'])
def test_independent_current_keys_fail_without_native_loading(setup,case):
    s=setup; inputs=s['make'](); day=s['dates'][0]
    value=inputs.current[day]
    if case=='native_uid': value['asset_uids']['A000']='000000099'
    elif case=='epoch': value['asset_epochs']['A000']='new-epoch'
    elif case=='source': value['source_support_identity']['source_pins']['primary']='e'*64
    elif case=='namespace': value['consumer_uids']['A000']='CUSIP:000000099'
    elif case=='key_sha': value['c14_current_key_sha256']='0'*64
    elif case=='raw_uid': inputs.raw[day].iloc[0,2]='CUSIP:000000099'
    elif case=='raw_rank': inputs.raw[day].iloc[0,4]=2
    elif case=='future': value['current_identity_asof']='2026-01-01T21:00:00Z'
    report=inputs.qualify()
    assert all(not report['roles'][r]['full_required_dates_qualified'] for r in s['active'])
    assert not s['loads']


@pytest.mark.parametrize('case',['method','recipe','params','cutoff','state_ref','covariance','psd','seal'])
def test_original_numeric_identity_and_digest_not_self_attested(setup,monkeypatch,case):
    s=setup; original=s['load']
    def bad(meta,pub,**kwargs):
        payload=original(meta,pub,**kwargs)
        if meta.family!='LW': return payload
        values=copy.deepcopy(payload.values)
        if case=='method': values['method']='wrong'
        elif case=='recipe': values['recipe_sha256']='0'*64
        elif case=='params': values['parameters']={'changed':1}
        elif case=='cutoff': values['cutoff']=values['as_of']
        elif case=='state_ref': return m.b.NativeRiskPayload(values,meta._seal,{'path':'wrong','sha256':'0'*64},payload.covariance_sha256)
        elif case in ('covariance','psd'):
            values['covariance'][0,0]=2 if case=='covariance' else -1
        elif case=='seal': payload.values['method']='unsealed'; return payload
        return m.b.NativeRiskPayload(values,meta._seal,payload.artifact_ref,payload.covariance_sha256)
    monkeypatch.setattr(m.b,'load_qualified_state',bad)
    inputs=s['make'](); result=inputs.qualify()
    assert result['roles']['C14_D01']['phase']=='BLOCKED_INPUT'
    assert result['roles']['C14_RX_HGB_LW']['phase']=='BLOCKED_INPUT'
    assert result['roles']['C14_D05']['full_required_dates_qualified'] is True
    assert s['loads'].count('LW')==1


def test_one_day_failure_is_partial_and_cannot_shorten_or_retry(setup,monkeypatch):
    s=setup; original=s['project']
    def failing(pub,r,**kwargs):
        if r['required_family_method']=='LW' and pd.Timestamp(kwargs['decision_asof']).tz_convert('UTC').tz_localize(None).normalize().isoformat()==s['dates'][2]:
            raise ValueError('synthetic exact day missing')
        return original(pub,r,**kwargs)
    monkeypatch.setattr(m.b,'project_r5_role',failing)
    inputs=s['make'](); result=inputs.qualify()
    gate=result['roles']['C14_D01']
    assert gate['phase']=='PARTIAL_INPUT_BLOCKED' and len(gate['states'])==2 and not gate['full_required_dates_qualified']
    assert gate['calendar_positions']==752 and result['roles']['C14_D05']['full_required_dates_qualified']
    with pytest.raises(ValueError,match='FULL752'): inputs.get_risk('C14_D01',s['dates'][0])


def test_changed_state_stat_blocks_reuse_without_reloading(setup):
    s=setup; inputs=s['make'](); inputs.qualify(); before=len(s['loads'])
    path=Path(s['records']['LW']['artifact_ref']['path']); path.write_bytes(b'changed synthetic opaque state')
    with pytest.raises(ValueError,match='PHYSICAL_PIN_CHANGED'): inputs.get_risk('C14_D01',s['dates'][-1])
    assert len(s['loads'])==before


def test_mutated_cached_payload_and_review_custody_fail_closed(setup):
    s=setup; inputs=s['make'](); inputs.qualify()
    cached=next(v for k,v in inputs._cache.items() if k[0]=='LW')
    cached['payload'].values['method']='mutated'
    with pytest.raises(ValueError,match='MUTATED_NATIVE'): inputs.get_risk('C14_D01',s['dates'][0])
    Path(s['review_ref']['path']).write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='CUSTODY_CHANGED'): inputs.get_risk('C14_D05',s['dates'][0])

@pytest.mark.parametrize('case', ['runtime', 'eof', 'unpickling'])
def test_loader_engineering_exception_blocks_state_once_and_preserves_independent_role(setup, monkeypatch, case):
    import pickle
    s = setup; original = s['load']; attempts = []
    error_class = {'runtime': RuntimeError, 'eof': EOFError, 'unpickling': pickle.UnpicklingError}[case]
    def failed_loader(meta, pub, **kwargs):
        attempts.append(meta.family)
        if meta.family == 'LW': raise error_class('synthetic original-loader engineering failure')
        return original(meta, pub, **kwargs)
    monkeypatch.setattr(m.b, 'load_qualified_state', failed_loader)
    inputs = s['make'](); report = inputs.qualify()
    for role in ('C14_D01', 'C14_RX_HGB_LW'):
        gate = report['roles'][role]
        assert gate['phase'] == 'BLOCKED_INPUT' and not gate['full_required_dates_qualified']
        assert error_class.__name__ in ';'.join(gate['reasons'])
    assert attempts.count('LW') == 1 and attempts.count('OAS') == 1
    assert report['counts']['native_state_load_attempts'] == report['counts']['risk_numeric_read'] == 2
    assert report['counts']['native_states_loaded'] == 1
    independent = inputs.role_gate('C14_D05')
    assert independent['full_required_dates_qualified'] and len(independent['states']) == 752
    assert independent['calendar_positions'] == 752 and independent['full_risk_mature_positions'] == 732 and independent['learned_positions'] == 482
    assert all(report['counts'][k] == 0 for k in ('selector_fit', 'risk_estimator_fit', 'solver', 'bootstrap', 'test2026_rows_read', 'EF_access', 'provider_fetch'))
    before = len(attempts)
    with pytest.raises(ValueError, match='FULL752'): inputs.get_risk('C14_D01', s['dates'][0])
    with pytest.raises(ValueError, match='SINGLE_PASS'): inputs.qualify()
    assert len(attempts) == before