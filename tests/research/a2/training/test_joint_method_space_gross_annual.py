"""Single-fold composition tests use fake estimators and synthetic pre2026 rows."""
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import joint_method_space_gross_r6 as g


def reference(year, training):
    rows = []
    for day in pd.to_datetime([f'{year}-01-03', f'{year}-01-04']):
        for i in range(20):
            mu = .01 + i / 10000
            row = dict(signal_date=day, ticker=f'T{i:02}', security_uid=f'UID:EXACT:{i}',
                asset_epoch=1, fit_cutoff=pd.Timestamp(f'{year}-01-01'), source_qualified=True,
                identity_qualified=True, genuine_chronological_oof=True, mu=mu,
                realized_vol_20d=.02 + i / 10000, downside_vol_20d=.01, avg_dollar_volume_20d=1e6)
            if training:
                row.update(execution_date=day + pd.Timedelta(days=1),
                    label_end_date=day + pd.Timedelta(days=8), label_mature_date=day + pd.Timedelta(days=8),
                    label_available_at=(day + pd.Timedelta(days=8, hours=21)).tz_localize('UTC'), y_open5=mu + .005)
            rows.append(row)
    return pd.DataFrame(rows)


@pytest.fixture
def setup(monkeypatch):
    events = []
    active = []
    cache = {}
    class Scaler:
        def transform(self, x):
            assert active == ['deterministic_transform']
            events.append('transform')
            return np.asarray(x, float) / 2
    def scaler(x, payload, *, on_fit_started):
        assert active == ['scaler']
        assert np.isfinite(x).all() and np.array_equal(payload['weights'], np.ones(len(x)))
        on_fit_started('MECHANISM_DATE_WEIGHTED_SCALER')
        events.append('scaler_fit')
        return Scaler(), dict(actual_fit_count=1)
    def fit(kind, x, payload, *, quantile, dependencies, on_fit_started):
        assert active == ['model_fit']
        assert kind == 'RIDGE' and quantile is None and dependencies == ('SYNTHETIC_DEPENDENCY',)
        assert payload['family'] == 'Ridge' and payload['capacity'] == 'LOW' and payload['seed'] == 20260928
        assert payload['objective'] == 'GROSS' and np.isin(payload['target'], g.GRID).all()
        on_fit_started('MECHANISM_ESTIMATOR')
        events.append('ridge_fit')
        return SimpleNamespace(node=dict(family='Ridge', capacity='LOW', seed=g.SEED)), dict(actual_fit_count=1)
    monkeypatch.setattr(g.native, 'fit_weighted_scaler', scaler)
    monkeypatch.setattr(g.native, 'fit', fit)
    def predict(model, x):
        assert active == ['deterministic_transform']
        events.append('predict')
        return {'mean': np.linspace(.12, .88, len(x))}
    monkeypatch.setattr(g.native, 'predict', predict)
    def learn(kind, name, inputs, compute, parameters):
        assert kind == ('deterministic_transform' if parameters['physical_kind'] == 'deterministic_transform' else 'estimator_learned_state_fit')
        events.append(('owner_before_compute', name, parameters, inputs))
        if name in cache:
            return cache[name]
        active.append(parameters['physical_kind'])
        try:
            value = compute()
        finally:
            active.clear()
        cache[name] = value
        return value
    return reference(2022, True), reference(2023, False), learn, events, cache


def run(setup, **kwargs):
    train, infer, owner, _, _ = setup
    return g.fit_ridge_annual(train, infer, cutoff='2023-01-01', learn=owner,
        dependencies=('SYNTHETIC_DEPENDENCY',), **kwargs)


def test_exact_three_owner_states_original_recipe_and_inference_does_not_read_targets(setup):
    train, infer, _, events, _ = setup
    before = train.copy(deep=True)
    infer['y_open5'] = 'FORBIDDEN_INFERENCE_TARGET_BODY'
    out = run(setup)
    nodes = [event for event in events if isinstance(event, tuple)]
    assert [event[1] for event in nodes] == ['GROSS:R4_EQUAL_PRIOR_RMS:2023', 'GROSS:SCALER:2023',
        'GROSS:SCALER_TRANSFORM_TRAIN:2023', 'GROSS:SCALER_TRANSFORM_INFER:2023', 'GROSS:RIDGE:2023', 'GROSS:RIDGE_INFER:2023']
    assert [event[2]['physical_kind'] for event in nodes] == ['bridge_calibration', 'scaler',
        'deterministic_transform', 'deterministic_transform', 'model_fit', 'deterministic_transform']
    assert nodes[4][2]['learner_parameters'] == g.native.parameters('Ridge', 'LOW') == {'alpha': 100., 'solver': 'auto'}
    assert out['metadata']['required_learned_states'] == out['metadata']['actual_local_learned_states'] == 3
    assert out['metadata']['required_physical_operations'] == out['metadata']['actual_local_physical_operations'] == 6
    assert events.count('transform') == 2 and events.count('predict') == 1
    assert out['prior_rms'] == pytest.approx(.005)
    assert out['predictions'].gross.tolist() == [0., 1.]
    assert not out['predictions'].strict_PIT_promotion_eligible.any()
    assert events.index('scaler_fit') > events.index(nodes[1]) and events.index('ridge_fit') > events.index(nodes[4])
    pd.testing.assert_frame_equal(train, before)


def test_completed_owner_objects_can_be_reused_without_any_refit(setup):
    first = run(setup)
    second = run(setup)
    assert second['metadata']['actual_local_learned_states'] == 0
    assert second['metadata']['actual_local_physical_operations'] == 0
    assert second['metadata']['required_learned_states'] == 3
    assert second['model'] is first['model'] and second['scaler'] is first['scaler']
    assert setup[3].count('ridge_fit') == setup[3].count('scaler_fit') == 1
    assert setup[3].count('transform') == 2 and setup[3].count('predict') == 1


@pytest.mark.parametrize('change', ['empty_train', 'empty_infer', 'late_mature', 'late_available',
    'bad_train_truth', 'bad_infer_feature', 'unqualified', 'short_reference', 'infer_wrong_year'])
def test_complete_both_domain_preflight_fails_before_any_learned_state(setup, change):
    train, infer, owner, events, _ = setup
    if change == 'empty_train': train = train.iloc[:0]
    elif change == 'empty_infer': infer = infer.iloc[:0]
    elif change == 'late_mature': train.loc[0, 'label_mature_date'] = pd.Timestamp('2023-01-01')
    elif change == 'late_available': train.loc[0, 'label_available_at'] = pd.Timestamp('2023-01-01T00:00:00Z')
    elif change == 'bad_train_truth': train.loc[0, 'y_open5'] = np.inf
    elif change == 'bad_infer_feature': infer.loc[0, 'mu'] = np.nan
    elif change == 'unqualified': train.loc[0, 'source_qualified'] = False
    elif change == 'short_reference': train = train.iloc[1:]
    elif change == 'infer_wrong_year': infer.loc[0, 'signal_date'] = pd.Timestamp('2026-01-01')
    with pytest.raises(ValueError):
        g.fit_ridge_annual(train, infer, cutoff='2023-01-01', learn=owner)
    assert events == []


@pytest.mark.parametrize('cutoff', ['2026-01-01', '2023-01-02', 'NaT'])
def test_only_frozen_annual_cutoffs_and_required_owner(setup, cutoff):
    with pytest.raises(ValueError, match='ANNUAL_GROSS_CUTOFF'):
        g.fit_ridge_annual(setup[0], setup[1], cutoff=cutoff, learn=setup[2])
    with pytest.raises(ValueError, match='DURABLE_GROSS_LEARN_OWNER'):
        g.fit_ridge_annual(setup[0], setup[1], cutoff='2023-01-01', learn=None)
    assert setup[3] == []


def test_nonfinite_native_prediction_never_quantized_to_a_valid_gross(setup, monkeypatch):
    monkeypatch.setattr(g.native, 'predict', lambda model, x: {'mean': np.full(len(x), np.nan)})
    with pytest.raises(ValueError, match='FINITE_EXACT_GROSS_PREDICTION'):
        run(setup)


def test_duplicate_owner_compute_fails_before_second_estimation(setup):
    calls = []
    def bad_owner(kind, name, inputs, compute, parameters):
        calls.append(name)
        compute()
        return compute()
    with pytest.raises(ValueError, match='DUPLICATE_GROSS_COMPUTE'):
        g.fit_ridge_annual(setup[0], setup[1], cutoff='2023-01-01', learn=bad_owner)
    assert len(calls) == 1 and setup[3] == []


def test_native_backend_must_ack_exactly_once_after_owner_start(setup, monkeypatch):
    monkeypatch.setattr(g.native, 'fit_weighted_scaler', lambda *a, **kw: (object(), {'actual_fit_count': 1}))
    with pytest.raises(ValueError, match='EXACT_ONE_NATIVE_GROSS_FIT_ACK'):
        run(setup)
    assert 'ridge_fit' not in setup[3]
