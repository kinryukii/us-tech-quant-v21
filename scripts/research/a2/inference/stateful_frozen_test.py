"""No-fit 2025-artifact carry-forward for the three authorized 2026 policies.

Reuses the original feature encoder, native prediction/calibration and action
decoder. Old annual guards and serialized receipts remain unchanged. No model
is loaded, no source is fetched and no account is created on import.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import copy
import json
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from scripts.maintenance.research_inventory import _RetirementMetadataReader
from scripts.research.a2.evaluation import frozen_test_authority as admission
from scripts.research.a2.training import stateful_decision as decision
from scripts.research.a2.training import stateful_decision_models as models
from scripts.research.a2.training import stateful_final_action_packets as packets
from scripts.research.a2.training import stateful_values as values

RECEIPT_SHA256 = {
    'R6_BUY_TREE': 'a788e49145d1da7143136985b81e1ec3647d18b80e14e06b75c5bc8de8e3d1f7',
    'R6_REPLACE_TREE': '1edaea5afc487d09a707880de0f1e2339eda0b985adf755e1bce4ed6360b5569',
    'A_BREADTH_R1_ngboost_REF_s10': 'd1c98830f22a9d544c34a1b8bf99816cffe49c2334bcc108a0f92beaadea3c8a',
}
_SEAL = object()
_RECEIPT_FIELDS = frozenset(('status', 'year', 'seed', 'model_id', 'objective',
    'learner', 'model_path', 'model_sha256', 'scientific_tuple',
    'scientific_tuple_sha256', 'reuse_tuple', 'reuse_tuple_sha256',
    'train_label_maturity_max', 'calibration_label_maturity_max', 'dependency_paths',
    'scientific_feature_pit_qualified', 'scientific_target_qualified'))
_FORBIDDEN = packets.FORBIDDEN | frozenset(('y_open5', 'label_available',
    'account_event_unhandled', 'target_amount', 'realized_return'))


def _need(ok, code):
    if not ok:
        raise ValueError(code)


def _receipt_metadata(path):
    """Reuse the existing lexical reader; never decode omitted fit metrics."""
    with Path(path).open('rb') as stream:
        reader = _RetirementMetadataReader(stream)
        reader._space(); reader._expect(b'{'); reader._space()
        result, keys = {}, set()
        while reader.next != b'}':
            key = reader._string(True)
            _need(key not in keys, 'FROZEN_RECEIPT_DUPLICATE_KEY')
            keys.add(key); reader._space(); reader._expect(b':'); reader._space()
            if key in _RECEIPT_FIELDS:
                raw, pop = bytearray(), reader._pop
                def capture():
                    value = pop(); raw.extend(value); return value
                reader._pop = capture
                try:
                    reader._skip(1)
                finally:
                    reader._pop = pop
                result[key] = json.loads(bytes(raw))
            else:
                reader._skip(1)
            reader._space()
            if reader.next == b'}':
                break
            reader._expect(b','); reader._space()
            _need(reader.next != b'}', 'FROZEN_RECEIPT_TRAILING_COMMA')
        reader._expect(b'}'); reader._space()
        _need(not reader.next, 'FROZEN_RECEIPT_TRAILING_CONTENT')
        return result


def _day(value):
    stamp = pd.Timestamp(value)
    _need(not pd.isna(stamp) and stamp.tzinfo is None,
          'FROZEN_EXPLICIT_NAIVE_MATURITY_REQUIRED')
    return stamp


def _receipt_contract(path_id, receipt):
    _need(path_id in admission.MODEL_IDS, 'FROZEN_THREE_MODELS_ONLY')
    _need(receipt.get('status') == 'TRAINED' and type(receipt.get('year')) is int
          and receipt['year'] == 2025 and receipt.get('seed') == models.SEED,
          'FROZEN_TRAINED_2025_ARTIFACT_REQUIRED')
    _need(receipt.get('model_sha256') == admission.MODEL_SHA256[path_id],
          'FROZEN_MODEL_RECEIPT_SHA_CHANGED')
    if path_id.startswith('R6_'):
        objective = 'buy' if path_id == 'R6_BUY_TREE' else 'replace'
        spec = receipt.get('scientific_tuple', {})
        _need(receipt.get('objective') == objective and receipt.get('learner') == 'tree'
              and spec.get('slot', {}).get('year') == 2025
              and spec['slot'].get('objective') == objective
              and spec['slot'].get('learner') == 'tree', 'FROZEN_R6_SLOT_CHANGED')
        _need(values.digest(spec) == receipt.get('scientific_tuple_sha256'),
              'FROZEN_R6_SCIENTIFIC_TUPLE_CHANGED')
        boundary = _day(spec.get('calibration_start'))
        _need(_day(spec.get('training_signal_max')) < boundary
              and _day(spec.get('training_maturity_max')) < boundary
              and boundary < pd.Timestamp('2025-01-01'), 'FROZEN_R6_MATURITY_CHANGED')
        columns = decision.SINGLE if objective == 'buy' else decision.PAIR
        encoded = tuple(columns) + tuple(c + '__missing' for c in columns)
        _need(tuple(spec.get('feature_order', ())) == encoded,
              'FROZEN_R6_FEATURE_ORDER_CHANGED')
        return objective, tuple(columns)
    spec = receipt.get('reuse_tuple', {})
    _need(receipt.get('model_id') == 'ngboost' and spec.get('model_id') == 'ngboost'
          and spec.get('fold') == 'ANNUAL_2025'
          and values.digest(spec) == receipt.get('reuse_tuple_sha256'),
          'FROZEN_NGBOOST_TUPLE_CHANGED')
    _need(receipt.get('scientific_feature_pit_qualified') is True
          and receipt.get('scientific_target_qualified') is True,
          'FROZEN_NGBOOST_TRAINING_QUALIFICATION')
    cutoff = _day(spec.get('cutoff_exclusive'))
    train_end = _day(spec.get('training_signal_and_label_maturity_exclusive'))
    sessions = pd.DatetimeIndex(spec.get('calibration_sessions', []))
    _need(cutoff == pd.Timestamp('2025-01-01') and train_end < cutoff
          and _day(receipt.get('train_label_maturity_max')) < train_end
          and _day(receipt.get('calibration_label_maturity_max')) < cutoff
          and _day(spec.get('calibration_label_maturity_exclusive')) == cutoff
          and len(sessions) > 0 and not sessions.hasnans and sessions.tz is None
          and sessions.min() >= train_end and sessions.max() < cutoff,
          'FROZEN_NGBOOST_MATURITY_CHANGED')
    binding = spec.get('feature_binding', {})
    current = values.feature_binding()
    _need(binding == current, 'FROZEN_NGBOOST_FEATURE_BINDING_CHANGED')
    return 'ngboost', tuple(binding['features'])


@dataclass(frozen=True)
class Frozen2025Model:
    path_id: str
    objective: str
    features: tuple
    model: object = field(repr=False)
    receipt_json: str = field(repr=False)
    model_ref: dict
    receipt_ref: dict
    _seal: object = field(repr=False, compare=False)

    def __reduce__(self):
        raise TypeError('Revalidate physical frozen model references')


def _check_sources(bundle):
    receipt = json.loads(bundle.receipt_json)
    objective, features = _receipt_contract(bundle.path_id, receipt)
    _need(objective == bundle.objective and features == bundle.features,
          'FROZEN_HANDLE_FEATURE_OR_OBJECTIVE_CHANGED')
    if objective != 'ngboost':
        model = bundle.model
        expected = features + tuple(c + '__missing' for c in features)
        _need(type(model) is models.Model and model.objective == objective
              and model.learner == 'tree' and model.features == expected,
              'FROZEN_R6_SERIALIZED_MODEL_CHANGED')
        _need(model.metadata.get('source_sha256') == models.source_sha256()
              and model.metadata.get('native_source_sha256') == values.sha(values.NATIVE),
              'FROZEN_R6_SOURCE_CHANGED')
    else:
        model = bundle.model
        _need(type(model) is values.ValueFit, 'FROZEN_VALUEFIT_TYPE_REQUIRED')
        for key in ('reuse_tuple', 'reuse_tuple_sha256', 'year', 'model_id',
                    'train_label_maturity_max', 'calibration_label_maturity_max'):
            _need(model.receipt.get(key) == receipt.get(key),
                  'FROZEN_NGBOOST_EMBEDDED_RECEIPT_CHANGED:' + key)
        pins = receipt['reuse_tuple']['source_pins']
        for source, key in ((Path(values.__file__), 'module_sha256'),
                            (values.NATIVE, 'native_source_sha256'),
                            (values.READER_SOURCE, 'input_reader_sha256')):
            _need(values.sha(source) == pins.get(key), 'FROZEN_VALUE_SOURCE_CHANGED:' + key)
        _need(tuple(model.native.features) == features
              and model.native.model_id == 'ngboost'
              and model.calibration.get('model_id') == 'ngboost',
              'FROZEN_NGBOOST_SERIALIZED_MODEL_CHANGED')
    return receipt


def _load_frozen_model(path, objective):
    """Restore the original CLI pickle name only during NGBoost loading."""
    if objective != 'ngboost':
        return joblib.load(path)
    main = sys.modules.get('__main__')
    _need(main is not None, 'FROZEN_ORIGINAL_MAIN_NAMESPACE_REQUIRED')
    missing = object()
    original = getattr(main, 'ValueFit', missing)
    _need(original is missing or original is values.ValueFit,
          'FROZEN_VALUEFIT_NAMESPACE_CONFLICT')
    try:
        main.ValueFit = values.ValueFit
        return joblib.load(path)
    finally:
        if original is missing:
            del main.ValueFit
        else:
            main.ValueFit = original


def load_frozen_2025(path_id, model_ref, receipt_ref, authority):
    """Custody and maturity before deserialization; no receipt mutation."""
    authority = admission.load_descriptive_inference_authority(authority)
    _need(path_id in admission.MODEL_IDS, 'FROZEN_THREE_MODELS_ONLY')
    admission.require_descriptive_decision(authority, authority.start, path_id, inference_only=True)
    _need(isinstance(model_ref, dict) and model_ref.get('sha256') == admission.MODEL_SHA256[path_id]
          and isinstance(receipt_ref, dict) and receipt_ref.get('sha256') == RECEIPT_SHA256[path_id],
          'FROZEN_EXACT_ARTIFACT_AND_RECEIPT_REQUIRED')
    path = admission._physical(model_ref)
    receipt_path = admission._physical(receipt_ref)
    _need(receipt_path.parent == path.parent and receipt_path.name == 'fit_receipt.json',
          'FROZEN_RECEIPT_MODEL_COORDINATE_CHANGED')
    receipt = _receipt_metadata(receipt_path)
    _need(Path(receipt.get('model_path', '')).resolve() == path.resolve(),
          'FROZEN_RECEIPT_MODEL_PATH_CHANGED')
    objective, features = _receipt_contract(path_id, receipt)
    if objective == 'ngboost':
        values._native(receipt['dependency_paths'])
    model = _load_frozen_model(path, objective)
    bundle = Frozen2025Model(path_id, objective, features, model,
        json.dumps(receipt, sort_keys=True), copy.deepcopy(model_ref),
        copy.deepcopy(receipt_ref), _SEAL)
    _check_sources(bundle)
    return bundle


def _inference(bundle, frame, authority):
    _need(type(bundle) is Frozen2025Model and bundle._seal is _SEAL,
          'FROZEN_VALIDATED_MODEL_HANDLE_REQUIRED')
    _need(isinstance(frame, pd.DataFrame) and 'signal_date' in frame
          and not (set(frame.columns) & _FORBIDDEN), 'FROZEN_INFERENCE_ONLY_COLUMNS_REQUIRED')
    dates = pd.DatetimeIndex(pd.to_datetime(frame.signal_date))
    admission.validate_descriptive_input_dates(authority, dates)
    for date in dates.unique():
        admission.require_descriptive_decision(authority, date, bundle.path_id, inference_only=True)
    _need(dates.min() >= pd.Timestamp('2026-01-01')
          and dates.max() < pd.Timestamp('2027-01-01'), 'FROZEN_2026_ONLY')
    _need(set(bundle.features).issubset(frame.columns), 'FROZEN_FEATURE_COLUMNS_MISSING')
    _check_sources(bundle)


def predict_r6_frozen(bundle, frame, authority):
    _inference(bundle, frame, authority)
    _need(bundle.objective in ('buy', 'replace'), 'FROZEN_R6_MODEL_REQUIRED')
    x, names = decision.encode_features(frame, bundle.features)
    _need(names == bundle.model.features, 'FROZEN_R6_FEATURE_ORDER_CHANGED')
    native = models.predict(bundle.model, x)
    keys = ('signal_date', 'sample_id', 'ticker', 'security_id', 'incumbent',
            'incumbent_sid', 'cohort_age_sessions')
    out = frame[[c for c in keys if c in frame]].reset_index(drop=True).copy()
    out['p_superior'] = native['p_superior']
    out['action'] = (out.p_superior > .5).astype(int)
    out['model_year'] = 2025
    return out


def r6_proposals(bundle, frame, authority):
    output = predict_r6_frozen(bundle, frame, authority)
    return [packets.decode_r6_row(row, bundle.objective, i)
            for i, row in enumerate(output.to_dict('records'))]


def predict_value_frozen(bundle, frame, authority):
    _inference(bundle, frame, authority)
    _need(bundle.objective == 'ngboost', 'FROZEN_NGBOOST_MODEL_REQUIRED')
    _need({'ticker', 'feature_available', 'feature_source'}.issubset(frame.columns),
          'FROZEN_VALUE_INPUT_SCHEMA')
    mask = values._bool(frame.feature_available, 'feature_available')
    if 'input_present' in frame:
        mask &= values._bool(frame.input_present, 'input_present')
    _need(frame.loc[mask, 'feature_source'].isin(values.SOURCES).all(),
          'UNQUALIFIED_INFERENCE_SOURCE')
    out = frame[['signal_date', 'ticker']].reset_index(drop=True).copy()
    columns = ('prediction', 'value_sigma', *values.diagnostic_columns('ngboost'))
    for column in columns:
        out[column] = np.nan
    if mask.any():
        values._native(json.loads(bundle.receipt_json)['dependency_paths'])
        ids = np.flatnonzero(mask.to_numpy())
        x = values.transform(bundle.model.native.scaler,
                             frame.iloc[ids][list(bundle.features)].to_numpy(float))
        with threadpool_limits(limits=1):
            raw = bundle.model.native.raw_predict(x)
        mu, sigma = values.calibrated_values(bundle.model.calibration, raw)
        _need(np.isfinite(mu).all() and np.isfinite(sigma).all() and (sigma > 0).all(),
              'NONFINITE_QUALIFIED_VALUE_PREDICTION')
        fields = dict(prediction=mu, value_sigma=sigma, **values.raw_fields('ngboost', raw))
        for column, coordinate in fields.items():
            out.iloc[ids, out.columns.get_loc(column)] = coordinate
    receipt = json.loads(bundle.receipt_json)
    out['prediction_qualified'] = mask.to_numpy()
    out['year'], out['model_id'] = 2025, 'ngboost'
    out['model_reuse_tuple_sha256'] = receipt['reuse_tuple_sha256']
    out['model_sha256'] = receipt['model_sha256']
    return out
