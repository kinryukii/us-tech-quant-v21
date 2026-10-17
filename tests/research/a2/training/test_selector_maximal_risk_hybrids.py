"""Pure synthetic composition tests; no actual targets, state, risk or solver."""
import copy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import selector_maximal_risk_hybrids as m
from scripts.research.a2.training import selector_maximal_breadth_estimators as estimator


class FakeScaler:
    fits = []
    def fit(self, x, sample_weight):
        assert x.shape[1] == 228 and np.isfinite(x).all()
        assert np.array_equal(sample_weight, np.full(len(x), .005))
        self.fits.append(len(x))
        return self
    def transform(self, x):
        assert x.shape[1] == 228
        return x


class FakeKernel:
    def __init__(self): self.calls = []
    def capacity_specs(self, *, input_feature_count):
        assert input_feature_count == 228
        return estimator.capacity_specs(input_feature_count=input_feature_count)
    component_specs = staticmethod(estimator.component_specs)
    def fit_component(self, head, x, y, tasks, dates, challenger, incumbent,
                      cap, seed, quantile, runtime, on_fit, *, input_feature_count):
        assert input_feature_count == x.shape[1] == 228
        assert runtime == 'synthetic retained predictor'
        assert seed == 20260928 and quantile is None and len(x) == len(y) == len(tasks)
        assert len(x) == pd.Series(dates).nunique() * 200
        on_fit(dict(operation='SYNTHETIC_COMPONENT'))
        self.calls.append((head, cap, len(x), pd.Timestamp(max(dates))))
        return SimpleNamespace(point={"LOW":.1,"MID":.2,"HIGH":.3}[cap])
    @staticmethod
    def predict_component(model, x): return dict(point=np.full(len(x), model.point))
    @staticmethod
    def combine_predictions(head, values):
        assert head in ('HGB', 'XGB') and tuple(values) == ((20260928, None),)
        return next(iter(values.values()))


class FakeJournal:
    def __init__(self, run, role, dates, events):
        self.run = Path(run).resolve(); self.dates = tuple(d.isoformat() for d in dates)
        self.roles = {role:dict(qualification_ref=dict(sha256='a'*64))}
        self.events = events; self.calls = []; self.models = {}; self.identities = {}
        self.fail_nodes = set(); self.decoder_failure = False; self.decoded = []
        self.slots = {}
        for cut in m.CUTS:
            self.slots[f'RX_SCALER|{role}|{cut}'] = dict(candidate_id=role,status='RESERVED',entered=0)
            for cap in m.owner.CAPACITIES if cut != m.CUTS[-1] else ('SELECTED',):
                self.slots[f'RX_MODEL|{role}|{cut}|{cap}|20260928|None'] = dict(candidate_id=role,status='RESERVED',entered=0)
        self.fit_ledger = SimpleNamespace(value=dict(slots=self.slots))
    def verify(self): self.events.append('verify')
    def stored_fit(self, node, identity, path, fit):
        assert Path(path) == self.run/'risk_execution'/'models'/(m.owner.content_hash(node)+'.joblib')
        self.calls.append(node); self.events.append('fit:'+node)
        slot = self.slots[node]
        if slot['status'] in ('FAILED','BLOCKED_DEPENDENCY'): return None
        if slot['status'] == 'COMPLETE':
            assert self.identities[node] == identity
            return self.models[node]
        self.identities[node] = copy.deepcopy(identity)
        slot['status'] = 'STARTED'
        def entered(event): slot['entered'] += 1
        if node in self.fail_nodes:
            entered(None); slot.update(status='FAILED',error='SYNTHETIC_NONRETRYABLE'); return None
        result = fit(entered)
        slot['status'] = 'COMPLETE'; self.models[node] = result
        return result
    def block_remaining(self, role, reason):
        for slot in self.slots.values():
            if slot['candidate_id'] == role and slot['status'] == 'RESERVED':
                slot.update(status='BLOCKED_DEPENDENCY',error=reason)
    def checkpoint_decode(self, token, raw, geometry, score, cid, eligible):
        assert token.startswith('HYBRID|'+cid+'|') and token not in self.decoded
        self.decoded.append(token)
        assert len(geometry) == 200 and np.array_equal(eligible, score > 0)
        if self.decoder_failure: raise ValueError('CHARGED_WITHOUT_COMPLETE_CACHE_NO_RETRY')
        frame = raw.copy()
        frame['score'] = frame.raw_score; frame['rank'] = frame.raw_rank; frame['candidate_id'] = cid
        return frame, geometry.iloc[:0].copy()


@pytest.fixture
def synthetic(monkeypatch):
    dates = pd.to_datetime(['2023-01-03','2023-04-03','2023-08-01','2023-10-02',
        '2024-01-03','2024-04-01','2024-08-01','2024-10-01',
        '2025-01-02','2025-04-01','2025-08-01','2025-10-01'])
    # Tiny date mask substitutes only the two production cardinalities; all real
    # owner maturity/fold/key/loss/scaler/model functions remain exercised.
    monkeypatch.setattr(m, 'CALENDAR_DATES', len(dates)); monkeypatch.setattr(m, 'OUTER_DATES', 8)
    raw = pd.DataFrame([dict(signal_date=d,security_uid=f'CUSIP:{i:09}',ticker=f'A{i:02}',
        U_t_fingerprint='SYNTHETIC_FULL_U',raw_rank=i+1,raw_score=float(50-i),label_end_date=d+pd.Timedelta(days=20))
        for d in dates for i in range(45)])
    geometry = m.owner.pairs.geometry(raw); x = np.zeros((len(geometry),216)); events = []; writes = {}
    role = 'C14_RX_HGB_LW'; run = Path('D:/us-tech-quant-backtests/V24/20261004T070941+0000_13adcb4c')
    design = dict(research_id=m.owner.ID,risk=dict(hybrid_bindings=[dict(candidate_id=r,head=h,family=f) for r,(h,f) in m.ROLES.items()],
        hybrid_feature_recipe=dict(input_columns=228,new_per_asset=list(m.COORDS))))
    q = dict(research_id=m.owner.ID,pair_key_sha256=m.owner.pairs.pair_key_sha256(geometry),input_sources=dict(hlabels=dict(sha256='b'*64)))
    def labels(run, design, q, cutoff):
        events.append('labels:'+cutoff)
        valid = geometry.loc[geometry.signal_date.add(pd.Timedelta(days=20)).lt(cutoff)].reset_index(drop=True)
        ends = valid.signal_date.add(pd.Timedelta(days=20)); n = len(valid)
        return valid, np.zeros(n), np.zeros((n,4)), ends, dict(cutoff=cutoff,source='SYNTHETIC_ONLY')
    def get_risk(role, day):
        events.append('risk:'+pd.Timestamp(day).isoformat())
        meta = SimpleNamespace(role=role,family=m.ROLES[role][1],decision_asof=m.decision_close(day),
            uids=list(raw.loc[raw.signal_date.eq(day),'security_uid']))
        return meta, 'SYNTHETIC_NOT_A_STATE'
    def coords(meta, payload, raw40):
        assert payload == 'SYNTHETIC_NOT_A_STATE' and raw40 == meta.uids[:40]
        return np.column_stack((np.arange(45)+1, np.arange(45)+.5))
    def write_table(path, frame):
        assert Path(path).is_relative_to(run/'risk_execution')
        writes[str(path)] = frame.copy()
        return dict(path=str(path),sha256='c'*64,rows=len(frame))
    def write_json(path, value):
        assert Path(path).is_relative_to(run/'risk_execution')
        writes[str(path)] = copy.deepcopy(value)
    monkeypatch.setattr(m.owner,'label_pairs',labels)
    monkeypatch.setattr(m.risk,'_consumer_uids',lambda meta:meta.uids)
    monkeypatch.setattr(m.risk,'hybrid_coordinates',coords)
    monkeypatch.setattr(m.owner,'write_table',write_table); monkeypatch.setattr(m.owner,'write_json',write_json)
    import sklearn.preprocessing
    FakeScaler.fits = []
    monkeypatch.setattr(sklearn.preprocessing,'StandardScaler',FakeScaler)
    journal = FakeJournal(run,role,dates,events); kernel = FakeKernel()
    def execute(role=role,journal=journal):
        return m.execute_hybrid(run,design,q,raw,geometry,x,role,get_risk,journal,kernel,'synthetic retained predictor')
    return SimpleNamespace(**locals())


@pytest.mark.parametrize('role', tuple(m.ROLES))
def test_complete_original_folds_exact_nodes_reuse_and_full_u(synthetic,role):
    s = synthetic; j = FakeJournal(s.run,role,s.dates,s.events)
    result = s.execute(role,j)
    assert result['status'] == 'HYBRID_COMPLETE' and result['complete_candidates'] == [role]
    assert result['feature_count'] == len(result['feature_order']) == 228
    assert all(v['status']=='COMPLETE' and v['entered']==1 for v in j.slots.values())
    assert len(j.slots)==14 and len(s.kernel.calls)==10 and len(FakeScaler.fits)==4
    # The Jan24 chosen model is loaded for full-year prediction without re-fit.
    node=f'RX_MODEL|{role}|2024-01-01|LOW|20260928|None'
    assert j.calls.count(node)==2 and j.slots[node]['entered']==1
    assert j.calls.count(f'RX_MODEL|{role}|2025-01-01|SELECTED|20260928|None')==1
    assert result['capacity_selection']['choices']=={'2024':'LOW','2025':'LOW'}
    records=result['capacity_selection']['records']; assert len(records)==9
    assert {r['fit_cutoff'] for r in records} == set(m.CUTS[:3])
    assert all(pd.Timestamp(r['max_label_end'])<pd.Timestamp(r['validation_end']) for r in records)
    before_label=s.events[:next(i for i,e in enumerate(s.events) if e.startswith('labels:'))]
    assert sum(e.startswith('risk:') for e in before_label)==len(s.dates)
    assert len(j.decoded)==8 and not any('|2023-' in t for t in j.decoded)
    panel=s.writes[result['panels'][role]['path']]
    assert len(panel)==len(s.raw) and panel.signal_date.nunique()==12
    assert panel.groupby('signal_date').size().eq(45).all()
    fallback=panel.loc[panel.signal_date.dt.year.eq(2023)]
    expected=s.raw.loc[s.raw.signal_date.dt.year.eq(2023)]
    assert np.array_equal(fallback.score,expected.raw_score) and np.array_equal(fallback['rank'],expected.raw_rank)
    assert result['forecast2026_rows']==0 and result['scientific_retry']==0 and not result['strict_PIT_promotion_eligible']
    assert all(len(i['feature_order'])==228 for i in j.identities.values())


def test_native_feature_coordinates_full_u_and_finite_missing_flags(synthetic):
    s=synthetic
    x=m.qualified_features(s.raw,s.geometry,s.x,s.role,s.get_risk,s.journal)
    assert x.shape==(2400,228) and np.isfinite(x).all()
    # First canonical pair is Raw21 challenger / Raw11 incumbent.
    assert np.array_equal(x[0,216:222],[21,20.5,11,10.5,10,10])
    assert not x[:,222:].any()


@pytest.mark.parametrize('bad',('unactivated','full_u','clock','nonfinite','geometry'))
def test_input_failure_precedes_any_labels_or_fits(synthetic,bad,monkeypatch):
    s=synthetic
    if bad=='unactivated':s.journal.roles={}
    if bad=='full_u':monkeypatch.setattr(m.risk,'_consumer_uids',lambda meta:meta.uids[:-1])
    if bad=='clock':
        original=s.get_risk
        def wrong(role,day):
            meta,payload=original(role,day);meta.decision_asof=m.decision_close(day)-pd.Timedelta(days=1);return meta,payload
        s.get_risk=wrong
    if bad=='nonfinite':s.x[0,0]=np.nan
    if bad=='geometry':s.geometry=s.geometry.iloc[:-1]
    with pytest.raises((ValueError,KeyError)):
        m.execute_hybrid(s.run,s.design,s.q,s.raw,s.geometry,s.x,s.role,s.get_risk,s.journal,s.kernel,'synthetic retained predictor')
    assert not any(e.startswith(('labels:','fit:')) for e in s.events) and not s.journal.decoded
    assert not s.writes


def test_failed_selected_capacity_has_no_raw_success_or_retry(synthetic):
    s=synthetic
    node=f'RX_MODEL|{s.role}|2024-01-01|LOW|20260928|None'
    s.journal.fail_nodes.add(node)
    result=s.execute()
    assert result['status']=='HYBRID_FAILED' and not result['panels'] and not result['complete_candidates']
    assert node in result['fit_failures'] and s.journal.slots[node]['entered']==1
    assert s.journal.calls.count(node)==2 and len(s.kernel.calls)==9 and not s.journal.decoded
    assert result['failed_or_untestable'][s.role]=='BLOCKED_INCOMPLETE_LEARNED_OUTER_NO_RAW_SUCCESS'


def test_unavailable_capacity_terminalizes_only_unentered_reserved_nodes(synthetic):
    s=synthetic
    for cut in m.CUTS[1:3]:
        for cap in m.owner.CAPACITIES:s.journal.fail_nodes.add(f'RX_MODEL|{s.role}|{cut}|{cap}|20260928|None')
    result=s.execute()
    assert result['status']=='HYBRID_FAILED' and result['capacity_selection']['choices']['2025'] is None
    for n,v in s.journal.slots.items():
        if '|2025-01-01' in n:assert v['status']=='BLOCKED_DEPENDENCY' and v['entered']==0
    assert not s.journal.decoded and not result['panels']


def test_charged_decoder_failure_is_typed_and_never_retried(synthetic):
    s=synthetic;s.journal.decoder_failure=True
    result=s.execute()
    assert result['status']=='HYBRID_FAILED' and len(s.journal.decoded)==1
    assert 'CHARGED_WITHOUT_COMPLETE_CACHE_NO_RETRY' in result['failed_or_untestable'][s.role]
    assert not result['panels'] and not result['native_pair_predictions']
    assert all(v['status']=='COMPLETE' for v in s.journal.slots.values())


def test_unfrozen_head_or_recipe_is_rejected_before_input(synthetic):
    s=synthetic
    with pytest.raises(ValueError,match='ONLY_TWO'):s.execute('C14_RX_CAT_SHR_HP')
    s.design['risk']['hybrid_feature_recipe']['input_columns']=216
    with pytest.raises(ValueError,match='RECIPE_CHANGED'):s.execute()
    assert not s.events and not s.writes



@pytest.mark.parametrize('recovery',['source_metadata_recovery_r1','source_guard_recovery_r1'])
def test_recovery_hybrid_routes_only_artifacts_keeps_original_nodes_and_model_authority(synthetic,recovery):
    s=synthetic;root=s.run/'risk_execution'/recovery
    result=m.execute_hybrid(s.run,s.design,s.q,s.raw,s.geometry,s.x,s.role,s.get_risk,s.journal,s.kernel,
        'synthetic retained predictor',artifact_root=root)
    assert result['status']=='HYBRID_COMPLETE' and len(s.journal.slots)==14 and len(s.kernel.calls)==10
    assert len(s.journal.decoded)==8 and all(Path(p).is_relative_to(root) for p in s.writes)
    assert all(v['entered']==1 for v in s.journal.slots.values())
    assert s.journal.run==s.run.resolve()


@pytest.mark.parametrize('root_kind',['alternate','foreign','models','descendant'])
def test_hybrid_rejects_any_nonfixed_artifact_root_before_input_or_fit(synthetic,root_kind):
    s=synthetic;root={'alternate':s.run/'risk_execution/recovery2','foreign':s.run.parent/'other',
        'models':s.run/'risk_execution/models','descendant':s.run/'risk_execution/source_guard_recovery_r1/nested'}[root_kind]
    with pytest.raises(ValueError,match='ARTIFACT_ROOT'):
        m.execute_hybrid(s.run,s.design,s.q,s.raw,s.geometry,s.x,s.role,s.get_risk,s.journal,s.kernel,
            'synthetic retained predictor',artifact_root=root)
    assert not s.events and not s.writes and not s.kernel.calls and not s.journal.decoded
