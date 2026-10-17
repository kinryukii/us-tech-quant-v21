"""Synthetic no-fit carry-forward acceptance; no real model/data loads."""
from dataclasses import replace
import copy
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import HistGradientBoostingClassifier

from scripts.research.a2.inference import stateful_frozen_test as adapter


class SyntheticClassifier:
    classes_ = np.array([0, 1])
    def predict_proba(self, x):
        p = np.clip(.5 + x[:, 0] * .1, 0, 1)
        return np.column_stack((1 - p, p))
    def fit(self, *args, **kwargs):
        raise AssertionError('fit forbidden')


class SyntheticNative:
    model_id = 'ngboost'
    scaler = None
    def __init__(self, features):
        self.features = list(features)
    def raw_predict(self, x):
        return np.column_stack((x[:, 0] * .02, np.full(len(x), .1)))
    def fit(self, *args, **kwargs):
        raise AssertionError('fit forbidden')


class PresetScaler:
    def transform(self, x):
        return np.asarray(x) / 2
    def fit(self, *args, **kwargs):
        raise AssertionError('scaler fit forbidden')


@pytest.fixture(autouse=True)
def no_fitting(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('No model, scaler or calibration fit is allowed')
    for owner, name in ((adapter.models, 'fit'), (adapter.values, '_fit_job'),
                        (adapter.values, 'heldout_calibration'),
                        (StandardScaler, 'fit'), (HistGradientBoostingClassifier, 'fit')):
        monkeypatch.setattr(owner, name, forbidden)


@pytest.fixture
def authority():
    a = adapter.admission
    return a.ValidatedDescriptiveAuthority(a.TASK, 'SYNTHETIC_WINDOW',
        pd.Timestamp('2026-01-02'), pd.Timestamp('2026-10-06'),
        pd.Timestamp('2026-10-08T00:00:00Z'), pd.Timestamp('2023-01-01'),
        a.PATH_IDS, '{}', a._SEAL)


def synthetic_r6(path_id):
    objective = 'buy' if path_id == 'R6_BUY_TREE' else 'replace'
    columns = adapter.decision.SINGLE if objective == 'buy' else adapter.decision.PAIR
    features = tuple(columns) + tuple(c + '__missing' for c in columns)
    metadata = dict(source_sha256=adapter.models.source_sha256(),
        native_source_sha256=adapter.models.NATIVE_SHA256,
        seed=adapter.models.SEED, specifications=adapter.models.specifications(),
        input_features=list(features), sklearn_version=importlib.metadata.version('scikit-learn'))
    model = adapter.models.Model(objective, 'tree', SyntheticClassifier(), None,
                                 features, (), metadata)
    spec = dict(slot=dict(year=2025, objective=objective, learner='tree'),
        calibration_start='2024-10-07', training_signal_max='2024-09-24',
        training_maturity_max='2024-10-02', feature_order=list(features))
    receipt = dict(status='TRAINED', year=2025, seed=adapter.models.SEED,
        objective=objective, learner='tree', scientific_tuple=spec,
        scientific_tuple_sha256=adapter.values.digest(spec))
    return model, receipt


def synthetic_value():
    v = adapter.values
    binding = v.feature_binding()
    spec = dict(model_id='ngboost', fold='ANNUAL_2025', cutoff_exclusive='2025-01-01',
        training_signal_and_label_maturity_exclusive='2024-10-07',
        calibration_label_maturity_exclusive='2025-01-01',
        calibration_sessions=['2024-10-07', '2024-12-31'], feature_binding=binding,
        source_pins=dict(module_sha256=v.sha(Path(v.__file__)),
                         native_source_sha256=v.sha(v.NATIVE),
                         input_reader_sha256=v.sha(v.READER_SOURCE)))
    receipt = dict(status='TRAINED', year=2025, seed=adapter.models.SEED,
        model_id='ngboost', reuse_tuple=spec, reuse_tuple_sha256=v.digest(spec),
        train_label_maturity_max='2024-10-04', calibration_label_maturity_max='2024-12-31',
        dependency_paths=[], scientific_feature_pit_qualified=True,
        scientific_target_qualified=True)
    model = v.ValueFit(SyntheticNative(binding['features']),
        dict(model_id='ngboost', kind='point', offset=.003, sigma=.2), copy.deepcopy(receipt))
    return model, receipt


def write_bound_model(tmp_path, monkeypatch, path_id, *, alter=None, preset_scaler=False):
    model, receipt = synthetic_value() if 'ngboost' in path_id else synthetic_r6(path_id)
    if preset_scaler:
        model.native.scaler = PresetScaler()
    path = tmp_path / 'model.joblib'
    joblib.dump(model, path)
    model_sha = adapter.values.sha(path)
    receipt.update(model_path=str(path), model_sha256=model_sha)
    if alter:
        alter(receipt)
    receipt_path = tmp_path / 'fit_receipt.json'
    receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
    receipt_sha = adapter.values.sha(receipt_path)
    monkeypatch.setitem(adapter.admission.MODEL_SHA256, path_id, model_sha)
    monkeypatch.setitem(adapter.RECEIPT_SHA256, path_id, receipt_sha)
    return dict(path=str(path), sha256=model_sha), dict(path=str(receipt_path), sha256=receipt_sha)


def frame_for(bundle, year=2026):
    frame = pd.DataFrame({c: [1., 0., -1.] for c in bundle.features})
    frame['signal_date'] = pd.to_datetime([f'{year}-01-05'] * 3)
    frame['ticker'] = ['A', 'B', 'C']
    frame['sample_id'] = ['a', 'b', 'c']
    frame['security_id'] = ['SID-A', 'SID-B', 'SID-C']
    if bundle.objective == 'replace':
        frame['incumbent'] = ['X', 'Y', 'Z']
        frame['incumbent_sid'] = ['SID-X', 'SID-Y', 'SID-Z']
    if bundle.objective == 'ngboost':
        frame['feature_available'] = True
        frame['feature_source'] = sorted(adapter.values.SOURCES)[0]
    return frame


@pytest.mark.parametrize('path_id', adapter.admission.MODEL_IDS[:2])
def test_r6_exact_predictions_and_original_decoder(tmp_path, monkeypatch, authority, path_id):
    refs = write_bound_model(tmp_path, monkeypatch, path_id)
    bundle = adapter.load_frozen_2025(path_id, *refs, authority)
    frame = frame_for(bundle)
    before = [adapter.values.sha(r['path']) for r in refs]
    x, _ = adapter.decision.encode_features(frame, bundle.features)
    expected = adapter.models.predict(bundle.model, x)
    out = adapter.predict_r6_frozen(bundle, frame, authority)
    np.testing.assert_array_equal(out.p_superior, expected['p_superior'])
    proposals = adapter.r6_proposals(bundle, frame, authority)
    assert proposals == [adapter.packets.decode_r6_row(row, bundle.objective, i)
                         for i, row in enumerate(out.to_dict('records'))]
    assert proposals[1]['kind'] == 'REFERENCE'
    assert json.loads(bundle.receipt_json)['year'] == 2025
    assert before == [adapter.values.sha(r['path']) for r in refs]


def test_ngboost_original_predict_equivalence_without_mutating_year(tmp_path, monkeypatch, authority):
    policy = adapter.admission.MODEL_IDS[2]
    refs = write_bound_model(tmp_path, monkeypatch, policy)
    bundle = adapter.load_frozen_2025(policy, *refs, authority)
    frame = frame_for(bundle)
    # Legacy method remains pre2026-only; use the same synthetic coordinates in 2025.
    legacy = frame.copy(); legacy['signal_date'] = pd.Timestamp('2025-01-05')
    legacy_model = adapter.values.ValueFit(bundle.model.native, bundle.model.calibration,
        dict(bundle.model.receipt, model_sha256=refs[0]['sha256']))
    baseline = legacy_model.predict(legacy)
    state = copy.deepcopy(bundle.model.receipt)
    out = adapter.predict_value_frozen(bundle, frame, authority)
    for column in ('prediction', 'value_sigma', 'native_mu', 'native_sigma', 'prediction_qualified'):
        np.testing.assert_array_equal(out[column], baseline[column])
    assert out.year.eq(2025).all()
    assert bundle.model.receipt == state
    with pytest.raises(ValueError, match='ANNUAL_PRE2026_SCOPE'):
        bundle.model.predict(frame)


def test_value_preset_scaler_and_missing_support(tmp_path, monkeypatch, authority):
    refs = write_bound_model(tmp_path, monkeypatch, adapter.admission.MODEL_IDS[2], preset_scaler=True)
    bundle = adapter.load_frozen_2025(adapter.admission.MODEL_IDS[2], *refs, authority)
    frame = frame_for(bundle); frame.loc[2, 'feature_available'] = False
    result = adapter.predict_value_frozen(bundle, frame, authority)
    assert result.prediction.iloc[0] == pytest.approx(.013)
    assert not result.prediction_qualified.iloc[2]
    assert pd.isna(result.prediction.iloc[2])


@pytest.mark.parametrize('path_id', adapter.admission.MODEL_IDS)
@pytest.mark.parametrize('date', ['2025-12-31', '2026-10-07', '2027-01-01', None])
def test_wrong_inference_boundaries_reject(tmp_path, monkeypatch, authority, path_id, date):
    refs = write_bound_model(tmp_path, monkeypatch, path_id)
    bundle = adapter.load_frozen_2025(path_id, *refs, authority)
    frame = frame_for(bundle); frame['signal_date'] = pd.Timestamp(date)
    with pytest.raises(ValueError):
        (adapter.predict_value_frozen if bundle.objective == 'ngboost' else adapter.predict_r6_frozen)(bundle, frame, authority)


@pytest.mark.parametrize('alter', [
    lambda r: r.update(status='FAILED'), lambda r: r.update(year=2026),
    lambda r: r.update(seed=123), lambda r: r['scientific_tuple'].update(training_maturity_max='2026-01-01'),
    lambda r: r['scientific_tuple'].update(feature_order=[]),
])
def test_bad_r6_receipt_blocks_before_deserialization(tmp_path, monkeypatch, authority, alter):
    refs = write_bound_model(tmp_path, monkeypatch, 'R6_BUY_TREE', alter=alter)
    monkeypatch.setattr(adapter.joblib, 'load', lambda *args: pytest.fail('bad receipt deserialized'))
    with pytest.raises(ValueError):
        adapter.load_frozen_2025('R6_BUY_TREE', *refs, authority)


@pytest.mark.parametrize('field,bad', [('train_label_maturity_max', '2024-10-07'),
    ('calibration_label_maturity_max', '2025-01-01'), ('scientific_target_qualified', False),
    ('scientific_feature_pit_qualified', None)])
def test_bad_value_receipt_blocks_before_deserialization(tmp_path, monkeypatch, authority, field, bad):
    policy = adapter.admission.MODEL_IDS[2]
    refs = write_bound_model(tmp_path, monkeypatch, policy, alter=lambda r: r.update({field: bad}))
    monkeypatch.setattr(adapter.joblib, 'load', lambda *args: pytest.fail('bad receipt deserialized'))
    with pytest.raises(ValueError):
        adapter.load_frozen_2025(policy, *refs, authority)


@pytest.mark.parametrize('target', [0, 1])
def test_changed_physical_hash_blocks_before_deserialization(tmp_path, monkeypatch, authority, target):
    refs = write_bound_model(tmp_path, monkeypatch, 'R6_BUY_TREE')
    with Path(refs[target]['path']).open('ab') as stream:
        stream.write(b'changed')
    monkeypatch.setattr(adapter.joblib, 'load', lambda *args: pytest.fail('changed artifact deserialized'))
    with pytest.raises(ValueError, match='SOURCE_SHA_CHANGED'):
        adapter.load_frozen_2025('R6_BUY_TREE', *refs, authority)


@pytest.mark.parametrize('policy', ['R6_HOLD_TREE', 'R6_BUY_NEURAL', 'RAW_s10', 'QQQ_BUY_AND_HOLD'])
def test_scope_cannot_expand(authority, policy):
    with pytest.raises(ValueError, match='THREE_MODELS_ONLY'):
        adapter.load_frozen_2025(policy, {}, {}, authority)


@pytest.mark.parametrize('column', ['target', 'y_open5', 'label_mature_date', 'local_regret'])
def test_labels_are_not_accepted_as_inputs(tmp_path, monkeypatch, authority, column):
    refs = write_bound_model(tmp_path, monkeypatch, 'R6_BUY_TREE')
    bundle = adapter.load_frozen_2025('R6_BUY_TREE', *refs, authority)
    frame = frame_for(bundle); frame[column] = 0
    with pytest.raises(ValueError, match='INFERENCE_ONLY_COLUMNS'):
        adapter.predict_r6_frozen(bundle, frame, authority)


def test_changed_source_or_features_reject(tmp_path, monkeypatch, authority):
    refs = write_bound_model(tmp_path, monkeypatch, 'R6_BUY_TREE')
    bundle = adapter.load_frozen_2025('R6_BUY_TREE', *refs, authority)
    frame = frame_for(bundle)
    with pytest.raises(ValueError, match='FEATURE_COLUMNS_MISSING'):
        adapter.predict_r6_frozen(bundle, frame.drop(columns=bundle.features[0]), authority)
    bundle.model.metadata['source_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='SOURCE_CHANGED'):
        adapter.predict_r6_frozen(bundle, frame, authority)


@pytest.mark.parametrize('source_key', ['module_sha256', 'native_source_sha256', 'input_reader_sha256'])
def test_value_original_source_pins_remain_required(tmp_path, monkeypatch, authority, source_key):
    policy = adapter.admission.MODEL_IDS[2]
    refs = write_bound_model(tmp_path, monkeypatch, policy)
    bundle = adapter.load_frozen_2025(policy, *refs, authority)
    original = adapter.values.sha
    sources = dict(module_sha256=Path(adapter.values.__file__),
        native_source_sha256=adapter.values.NATIVE,
        input_reader_sha256=adapter.values.READER_SOURCE)
    monkeypatch.setattr(adapter.values, 'sha', lambda p:
        '0' * 64 if Path(p) == sources[source_key] else original(p))
    with pytest.raises(ValueError, match='VALUE_SOURCE_CHANGED'):
        adapter.predict_value_frozen(bundle, frame_for(bundle), authority)


@pytest.mark.parametrize('field,bad,error', [
    ('training_maturity_max', '2024-10-07', 'MATURITY_CHANGED'),
    ('feature_order', [], 'FEATURE_ORDER_CHANGED'),
])
def test_r6_tuple_rehash_cannot_relax_maturity_or_features(tmp_path, monkeypatch, authority, field, bad, error):
    def alter(receipt):
        receipt['scientific_tuple'][field] = bad
        receipt['scientific_tuple_sha256'] = adapter.values.digest(receipt['scientific_tuple'])
    refs = write_bound_model(tmp_path, monkeypatch, 'R6_BUY_TREE', alter=alter)
    monkeypatch.setattr(adapter.joblib, 'load', lambda *args: pytest.fail('bad metadata deserialized'))
    with pytest.raises(ValueError, match=error):
        adapter.load_frozen_2025('R6_BUY_TREE', *refs, authority)


def test_receipt_projection_never_decodes_fit_metrics(tmp_path, monkeypatch):
    path = tmp_path / 'receipt.json'
    path.write_bytes(b'{"status":"TRAINED","forbidden_metrics":{"secret":"UNREAD",'
        b'"number":123.456},"year":2025}')
    original = json.loads
    def selected_only(raw, *args, **kwargs):
        assert b'UNREAD' not in raw if isinstance(raw, bytes) else 'UNREAD' not in raw
        return original(raw, *args, **kwargs)
    monkeypatch.setattr(adapter.json, 'loads', selected_only)
    assert adapter._receipt_metadata(path) == {'status': 'TRAINED', 'year': 2025}


@pytest.mark.parametrize('payload', [b'{"year":2025,"year":2025}',
    b'{"year":2025,}', b'{"year":2025} []', b'{"year":NaN}'])
def test_receipt_parser_fails_closed(tmp_path, payload):
    path = tmp_path / 'receipt.json'; path.write_bytes(payload)
    with pytest.raises(ValueError):
        adapter._receipt_metadata(path)


def test_unvalidated_authority_or_handle_reject(tmp_path, monkeypatch, authority):
    refs = write_bound_model(tmp_path, monkeypatch, 'R6_BUY_TREE')
    bundle = adapter.load_frozen_2025('R6_BUY_TREE', *refs, authority)
    with pytest.raises(ValueError):
        adapter.predict_r6_frozen(bundle, frame_for(bundle), {})
    with pytest.raises(ValueError, match='HANDLE_REQUIRED'):
        adapter.predict_r6_frozen(replace(bundle, _seal=None), frame_for(bundle), authority)


@pytest.mark.parametrize('already_bound', [False, True])
def test_legacy_valuefit_namespace_is_exact_and_restored(monkeypatch, already_bound):
    main = sys.modules['__main__']
    if already_bound:
        monkeypatch.setattr(main, 'ValueFit', adapter.values.ValueFit, raising=False)
    else:
        monkeypatch.delattr(main, 'ValueFit', raising=False)
    marker = object()
    def load_only(path):
        assert main.ValueFit is adapter.values.ValueFit
        return marker
    monkeypatch.setattr(adapter.joblib, 'load', load_only)
    assert adapter._load_frozen_model('SYNTHETIC_NOT_READ', 'ngboost') is marker
    if already_bound:
        assert main.ValueFit is adapter.values.ValueFit
    else:
        assert not hasattr(main, 'ValueFit')


def test_legacy_valuefit_namespace_conflict_rejects_before_load(monkeypatch):
    main = sys.modules['__main__']; different = object()
    monkeypatch.setattr(main, 'ValueFit', different, raising=False)
    monkeypatch.setattr(adapter.joblib, 'load', lambda *args: pytest.fail('conflict deserialized'))
    with pytest.raises(ValueError, match='NAMESPACE_CONFLICT'):
        adapter._load_frozen_model('SYNTHETIC_NOT_READ', 'ngboost')
    assert main.ValueFit is different


def test_legacy_valuefit_namespace_restores_on_load_error(monkeypatch):
    main = sys.modules['__main__']
    monkeypatch.delattr(main, 'ValueFit', raising=False)
    def fail(path):
        assert main.ValueFit is adapter.values.ValueFit
        raise RuntimeError('SYNTHETIC_LOAD_ERROR')
    monkeypatch.setattr(adapter.joblib, 'load', fail)
    with pytest.raises(RuntimeError, match='SYNTHETIC_LOAD_ERROR'):
        adapter._load_frozen_model('SYNTHETIC_NOT_READ', 'ngboost')
    assert not hasattr(main, 'ValueFit')


# Reuse the existing synthetic admission fixture; no real source/model readers.
_common_spec = importlib.util.spec_from_file_location('_inference_only_common_fixture',
    Path(__file__).resolve().parents[4] / 'tests/research/a2/evaluation/test_continuous_research_account.py')
_common_fixture = importlib.util.module_from_spec(_common_spec)
_common_spec.loader.exec_module(_common_fixture)
descriptive_fixture = _common_fixture.descriptive_fixture


@pytest.fixture
def inference_documents(descriptive_fixture):
    path, bound, ref, qualification = descriptive_fixture
    a = adapter.admission
    bound.update(schema='A_2026_FROZEN_MODEL_INFERENCE_ADMISSION_R1',
        status='SOURCE_AND_POLICY_BOUND_FOR_FROZEN_INFERENCE_ONLY',
        capability='INFERENCE_ONLY', account_execution_allowed=False,
        allowed_path_ids=list(a.MODEL_IDS))
    bound['source_refs'].pop('corporate_actions')
    qualification.update(schema='A_2026_FROZEN_MODEL_INFERENCE_SOURCE_QUALIFICATION_R1',
        status='QUALIFIED_FOR_FROZEN_INFERENCE_ONLY', capability='INFERENCE_ONLY')
    qualification['groups'].pop('corporate_actions')
    def persist():
        bound['source_qualification_ref'] = _common_fixture._synthetic_ref(
            path / 'qualification.json', qualification)
        result = ref()
        result.update(schema=a.INFERENCE_REF_SCHEMA, capability='INFERENCE_ONLY')
        return result
    return dict(path=path, bound=bound, qualification=qualification, persist=persist)


@pytest.mark.parametrize('group', adapter.admission.INFERENCE_SOURCE_GROUPS)
@pytest.mark.parametrize('bad', [False, None, 'MISSING'])
def test_inference_each_four_source_gate_is_literal_true(inference_documents, group, bad):
    d = inference_documents
    if bad == 'MISSING':
        d['qualification']['groups'].pop(group)
    else:
        d['qualification']['groups'][group] = bad
    with pytest.raises(ValueError, match='SOURCE_GATE_NOT_TRUE'):
        adapter.admission.load_descriptive_inference_authority(d['persist']())


def test_inference_no_corporate_source_and_no_account_or_policy_capability(inference_documents):
    a = adapter.admission
    ref = inference_documents['persist']()
    value = a.load_descriptive_inference_authority(ref)
    assert value.capability == 'INFERENCE_ONLY' and value.allowed_path_ids == a.MODEL_IDS
    assert 'corporate_actions' not in inference_documents['bound']['source_refs']
    assert 'corporate_actions' not in inference_documents['qualification']['groups']
    assert json.loads(value.provenance_json)['account_execution_allowed'] is False
    for handle in (ref, value):
        with pytest.raises(ValueError, match='INFERENCE_ONLY_CANNOT_RUN_ACCOUNT'):
            a.load_descriptive_authority(handle)
        with pytest.raises(ValueError, match='INFERENCE_ONLY_CANNOT_RUN_ACCOUNT'):
            a.validate_descriptive_account(handle, ['2026-01-02', '2026-01-08'],
                ['R6_BUY_TREE'], dict(initial_nav=3000), dict(one_way_bps=10))
        with pytest.raises(ValueError, match='INFERENCE_ONLY_CANNOT_RUN_ACCOUNT'):
            a.validate_descriptive_policy(handle, [dict(candidate_id='R6_BUY_TREE')])
    with pytest.raises(ValueError, match='INFERENCE_ONLY_CANNOT_RUN_ACCOUNT'):
        a.require_descriptive_decision(value, '2026-01-05', 'R6_BUY_TREE')
    assert a.require_descriptive_decision(value, '2026-01-05', 'R6_BUY_TREE',
        inference_only=True) is value
    assert a.validate_descriptive_input_dates(value, ['2023-01-03'], feature_context=True) is value
    with pytest.raises(ValueError, match='POLICY_NOT_REGISTERED'):
        a.require_descriptive_decision(value, '2026-01-05', 'RAW_s10', inference_only=True)


@pytest.mark.parametrize('path_id', adapter.admission.MODEL_IDS)
def test_exact_three_synthetic_inference_without_cash_admission(tmp_path, monkeypatch,
        inference_documents, authority, path_id):
    d = inference_documents
    refs = write_bound_model(tmp_path, monkeypatch, path_id)
    d['bound']['model_refs'][path_id] = refs[0]
    candidate_path = Path(d['bound']['candidate_manifest_ref']['path'])
    candidates = json.loads(candidate_path.read_text(encoding='utf-8'))
    next(row for row in candidates['candidates'] if row['candidate_id'] == path_id)['model_ref'] = refs[0]
    d['bound']['candidate_manifest_ref'] = _common_fixture._synthetic_ref(candidate_path, candidates)
    ref = d['persist']()
    value = adapter.admission.load_descriptive_inference_authority(ref)
    bundle = adapter.load_frozen_2025(path_id, *refs, ref)
    frame = frame_for(bundle)
    predict = adapter.predict_value_frozen if bundle.objective == 'ngboost' else adapter.predict_r6_frozen
    actual = predict(bundle, frame, value)
    expected = predict(bundle, frame, authority)
    pd.testing.assert_frame_equal(actual, expected)
    assert json.loads(bundle.receipt_json)['year'] == 2025
    for date in ['2025-12-31', '2026-01-09', '2027-01-01']:
        bad = frame.copy(); bad['signal_date'] = pd.Timestamp(date)
        with pytest.raises(ValueError, match='INPUT_OUTSIDE_WINDOW'):
            predict(bundle, bad, value)
    bad = frame.copy(); bad['y_open5'] = 0.
    with pytest.raises(ValueError, match='INFERENCE_ONLY_COLUMNS'):
        predict(bundle, bad, value)


@pytest.mark.parametrize('bad', [False, None])
def test_old_account_corporate_gate_still_literal_true(descriptive_fixture, bad):
    path, bound, ref, qualification = descriptive_fixture
    qualification['groups']['corporate_actions'] = bad
    bound['source_qualification_ref'] = _common_fixture._synthetic_ref(path / 'qualification.json', qualification)
    with pytest.raises(ValueError, match='SOURCE_GATE_NOT_TRUE'):
        adapter.admission.load_descriptive_authority(ref())


@pytest.mark.parametrize('task', [adapter.admission.AGGREGATE_TASK, 'DEMO_VS_A_STATEFUL_FROZEN_TEST2026_R1', 'OTHER'])
def test_inference_new_capability_is_exact_task_only(inference_documents, task):
    ref = inference_documents['persist'](); ref['task_id'] = task
    with pytest.raises(ValueError, match='EXACT_TASK_REQUIRED'):
        adapter.admission.load_descriptive_inference_authority(ref)


@pytest.mark.parametrize('key,bad', [('allowed_path_ids', ['R6_BUY_TREE']),
    ('capability', 'ACCOUNT'), ('account_execution_allowed', True), ('new_fit', 1),
    ('feature_history_start', '2022-01-01'), ('as_of', '2026-01-07T22:00:00Z')])
def test_inference_shared_contract_not_weakened(inference_documents, key, bad):
    inference_documents['bound'][key] = bad
    with pytest.raises(ValueError):
        adapter.admission.load_descriptive_inference_authority(inference_documents['persist']())


@pytest.mark.parametrize('mutation', ['model', 'tuple', 'source_bytes', 'window'])
def test_inference_identity_and_source_custody_reject(inference_documents, mutation):
    d = inference_documents
    if mutation == 'model':
        d['bound']['model_refs']['R6_BUY_TREE']['sha256'] = '0' * 64
    elif mutation == 'tuple':
        p = Path(d['bound']['candidate_manifest_ref']['path'])
        rows = json.loads(p.read_text(encoding='utf-8'))
        rows['candidates'][1]['scientific_tuple_sha256'] = '0' * 64
        d['bound']['candidate_manifest_ref'] = _common_fixture._synthetic_ref(p, rows)
    elif mutation == 'source_bytes':
        p = Path(d['bound']['source_refs']['action_inputs']['path'])
        p.write_bytes(p.read_bytes() + b'CORRUPTED_SYNTHETIC_SOURCE')
    else:
        d['bound']['windows'][0]['end'] = '2027-01-01'
    with pytest.raises(ValueError):
        adapter.admission.load_descriptive_inference_authority(d['persist']())


def test_inference_cached_capability_keeps_seal_and_does_not_rehash(inference_documents, monkeypatch):
    a = adapter.admission
    value = a.load_descriptive_inference_authority(inference_documents['persist']())
    monkeypatch.setattr(a, '_physical', lambda *args: pytest.fail('cached authority rehashed'))
    assert a.load_descriptive_inference_authority(value) is value
    with pytest.raises(ValueError, match='VALIDATED_DESCRIPTIVE_AUTHORITY_REQUIRED'):
        a.load_descriptive_inference_authority(replace(value, _seal=None))
    with pytest.raises(ValueError, match='EXACT_THREE_INFERENCE_REQUIRED'):
        a.load_descriptive_inference_authority(replace(value, task_id=a.AGGREGATE_TASK))


def test_inference_capability_cannot_be_upgraded_by_dataclass_replace(inference_documents):
    a = adapter.admission
    value = a.load_descriptive_inference_authority(inference_documents['persist']())
    forged = replace(value, capability='ACCOUNT', allowed_path_ids=a.PATH_IDS)
    for loader in (a.load_descriptive_authority, a.load_descriptive_inference_authority):
        with pytest.raises(ValueError, match='VALIDATED_DESCRIPTIVE_AUTHORITY_REQUIRED'):
            loader(forged)
    with pytest.raises(ValueError, match='VALIDATED_DESCRIPTIVE_AUTHORITY_REQUIRED'):
        a.require_descriptive_decision(forged, '2026-01-05', 'R6_BUY_TREE')
