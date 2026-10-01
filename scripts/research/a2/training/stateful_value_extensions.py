"""V24 shareholder-value extensions: native RBF SVC and masked daily L20 nets.

The input reader owns PIT vectors and keys; values owns fits, budgets, hard worker
timeouts, past-heldout calibration and the sole FIT_LOG. No I/O of research data,
row sampling, early stopping, calibration, or fitting occurs on import.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import hashlib
import importlib
import json
from pathlib import Path
import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from scripts.common.storage_paths import resolve
from scripts.research.a2.training.stateful_inputs import FEATURES, ALLOWED_SOURCES, BOUNDARY, _join_vectors

REPO = Path(__file__).resolve().parents[4]
TORCH_SNAPSHOT = Path('D:/us-tech-quant-envs/frozen_dependency_snapshots/development_contexts/fast3_minute_inventory_r1/fast3_torch_cpu/Lib/site-packages')
FAST3_SOURCE = REPO/'scripts/research/fast3/calibrated_models.py'
NATIVE_SOURCE = REPO/'scripts/research/a2/retained/a2_predict_then_optimize_20260928_r1/models_native.py'
NAMES = ('svc', 'tcn', 'lstm', 'gru')
SEED, LENGTH, HIDDEN, EPOCHS, BATCH = 20260928, 20, 32, 12, 512
TARGET_SCALE = .1  # Fixed native neural coordinate, not a target-statistics fit.


def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def specs():
    return dict(feature_order=list(FEATURES), sequence_role='DAILY_20_US_SESSION_STOCK_VALUE',
        minute_empirical_coverage=False, source_sha256=_sha(__file__),
        native_loss_source={'path': str(NATIVE_SOURCE), 'sha256': _sha(NATIVE_SOURCE)},
        svc_factory_source={'path': str(FAST3_SOURCE), 'sha256': _sha(FAST3_SOURCE)},
        seed=SEED, row_selection='ALL_CALLER_LABEL_QUALIFIED_KEYS_NO_SAMPLE_CAP',
        preprocessing='ONE_TRAIN_ONLY_STANDARD_SCALER_OBSERVED_HISTORY_CELLS; CENTERED_MISSING_ZERO_WITH_EXPLICIT_NEURAL_MISSING_MASK',
        target_clip='NONE', calibration='CALLER_CHRONOLOGICAL_60_SESSION_HELDOUT_ONLY',
        physical_fit_timeout_seconds=1800, timeout_owner='VALUES_SPAWN_PARENT_HARD_DEADLINE',
        svc=dict(kernel='rbf', C=1., gamma='scale', probability=False, cache_size=512,
                 tol=.001, max_iter=100000, random_state=SEED,
                 reused_factory='FAST3 make_spec(S1,A), factory(spec).named_steps[model]',
                 overridden_native_fields={'C': {'old': .1, 'new': 1.},
                    'cache_size': {'old': 200, 'new': 512},
                    'random_state': {'old': 104729, 'new': SEED}},
                 inherited_pipeline_used=False, output='SIGNED_NATIVE_DECISION_FUNCTION'),
        sequence=dict(length=LENGTH, hidden=HIDDEN, epochs=EPOCHS, batch_size=BATCH,
            learning_rate=.001, weight_decay=.01, optimizer='AdamW', gradient_clip=2.,
            target_scale_fixed=TARGET_SCALE, threads=2, device='cpu', deterministic=True,
            input_channels=64, mask='mask=True means observed; appended channel=1 means missing',
            ordering='oldest session to decision session inclusive', target_scaler_fit_count=0,
            early_stopping=False, final_epoch_only=True, seed_search=False,
            tcn={'layers': 4, 'kernel': 3, 'dilations': [1,2,4,8], 'padding': [2,4,8,16], 'receptive_field': 31,
                 'readout': 'last-session Linear(32,1)', 'dropout': 0.},
            recurrent={'layers': 1, 'bidirectional': False, 'dropout': 0.,
                       'readout': 'last-session Linear(32,1)'},
            previous_selector_distinction='A DAILY L20/32/12/full keys; retained selector L8/16/10/40000 is not this role'))


def _feature_order(order):
    if tuple(order) != FEATURES:
        raise ValueError('FROZEN_ORDERED_32_INPUTS_REQUIRED')


def _observed(X, mask, sequence):
    x = np.asarray(X, dtype=float)
    shape = (LENGTH, len(FEATURES)) if sequence else (len(FEATURES),)
    if x.ndim != (3 if sequence else 2) or x.shape[1:] != shape:
        raise ValueError('INPUT_REQUIRES_N_20_32' if sequence else 'INPUT_REQUIRES_N_32')
    observed = np.isfinite(x) if mask is None else np.asarray(mask)
    if observed.shape != x.shape or not np.isin(observed, [True, False]).all():
        raise ValueError('ELEMENT_OBSERVED_MASK_SHAPE_OR_BOOLEAN')
    observed = observed.astype(bool)
    if not np.isfinite(x[observed]).all():
        raise ValueError('OBSERVED_INPUT_MUST_BE_FINITE')
    return np.where(observed, x, np.nan), observed


def _standardized(scaler, X, mask, sequence):
    x, observed = _observed(X, mask, sequence)
    if not len(x):
        return np.empty((0,LENGTH,64) if sequence else (0,len(FEATURES)),dtype=np.float32)
    z = scaler.transform(x.reshape(-1, len(FEATURES))).reshape(x.shape)
    z = np.where(observed, z, 0.).astype(np.float32)
    if not np.isfinite(z).all():
        raise ValueError('NONFINITE_STANDARDIZED_INPUT')
    return np.concatenate([z, (~observed).astype(np.float32)], axis=2) if sequence else z


def _torch(dependency_paths=()):
    paths = tuple(Path(p).resolve() for p in dependency_paths)
    if TORCH_SNAPSHOT.resolve() not in paths:
        raise ValueError('FROZEN_TORCH_CPU_SNAPSHOT_NOT_BOUND')
    envs = resolve(REPO).envs_root.resolve()
    for path in paths:
        if not path.is_relative_to(envs) or not path.is_dir():
            raise ValueError('DEPENDENCY_SNAPSHOT_OUTSIDE_ENVS_ROOT')
        if str(path) not in sys.path:
            sys.path.append(str(path))
    torch = importlib.import_module('torch')
    if not Path(torch.__file__).resolve().is_relative_to(TORCH_SNAPSHOT.resolve()) or torch.version.cuda is not None:
        raise ValueError('TORCH_CPU_SNAPSHOT_ORIGIN_CHANGED')
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True)
    return torch


def _network(method, torch):
    nn = torch.nn
    if method not in ('tcn', 'lstm', 'gru'):
        raise ValueError('UNKNOWN_DAILY_SEQUENCE_MODEL')

    class DailyNetwork(nn.Module):
        def __init__(self):
            super().__init__()
            if method == 'tcn':
                self.layers = nn.ModuleList([nn.Conv1d(64 if i == 0 else HIDDEN,
                    HIDDEN, 3, dilation=d) for i,d in enumerate((1,2,4,8))])
            else:
                self.recurrent = (nn.LSTM if method == 'lstm' else nn.GRU)(64, HIDDEN,
                    num_layers=1, batch_first=True, bidirectional=False, dropout=0., bias=True)
            self.output = nn.Linear(HIDDEN, 1)
        def forward(self, x):
            if method == 'tcn':
                z = x.transpose(1,2)
                for layer,padding in zip(self.layers,(2,4,8,16)):
                    z = torch.relu(layer(nn.functional.pad(z,(padding,0))))
                z = z[:,:,-1]
            else:
                z,_ = self.recurrent(x)
                z = z[:,-1,:]
            return self.output(z).flatten()
    return DailyNetwork()


def _native_loss():
    # Reuse the retained un-clipped MSE and preserve append-only dependency order.
    saved = list(sys.path)
    try:
        return importlib.import_module('scripts.research.a2.retained.a2_predict_then_optimize_20260928_r1.models_native').torch_loss
    finally:
        sys.path[:] = saved


def _svc(feature_order):
    from scripts.research.fast3.calibrated_models import make_spec, factory
    native = factory(make_spec('S1','A',list(feature_order))).named_steps['model']
    return native.set_params(C=1., cache_size=512, random_state=SEED)


@dataclass
class ExtensionFit:
    method: str
    feature_order: tuple
    scaler: object
    estimator: object
    metadata: dict
    dependency_paths: tuple = ()
    _model: object = field(default=None, repr=False, compare=False)

    def __getstate__(self):
        state = self.__dict__.copy()
        state['_model'] = None
        return state

    def raw_predict(self, X, mask=None):
        return raw_predict(self, X, mask=mask)


def fit_extension(method, X, y, *, feature_order, mask=None, dependency_paths=(), on_fit_started=None):
    """Exactly one train-only scaler and one native predictor; callback before fits.

    All eligible keys must be supplied by values; no cap, downsampling, class
    balancing, target clipping or hidden calibration. Values hard-kills only its
    owned worker at 1800 seconds and records incomplete/failed component counts.
    """
    if method not in NAMES:
        raise ValueError('UNKNOWN_VALUE_EXTENSION')
    _feature_order(feature_order)
    sequence = method != 'svc'
    x,observed = _observed(X,mask,sequence)
    target = np.asarray(y,dtype=float)
    if not len(x) or target.shape != (len(x),) or not np.isfinite(target).all():
        raise ValueError('ALL_QUALIFIED_FINITE_TARGETS_REQUIRED')
    if method == 'svc' and not np.array_equal(np.unique(target>0),[False,True]):
        raise ValueError('SVC_REQUIRES_BOTH_TARGET_SIGN_CLASSES')
    flat = x.reshape(-1,len(FEATURES))
    if np.isnan(flat).all(axis=0).any():
        raise ValueError('NO_TRAIN_ONLY_MEAN_FOR_FEATURE')
    components=[]
    def started(component):
        if on_fit_started is not None:
            on_fit_started(component)
        components.append(component)
    started('FEATURE_SCALER')
    scaler = StandardScaler().fit(flat)
    if not np.isfinite(scaler.mean_).all() or not np.isfinite(scaler.scale_).all():
        raise ValueError('NONFINITE_TRAIN_ONLY_SCALER')
    z = _standardized(scaler,x,observed,sequence)
    metadata = dict(specs=specs(), training_rows=len(x), training_keys_retained=True,
        actual_fit_components=components, feature_scaler_fit_count=1,
        predictor_fit_count=0, target_scaler_fit_count=0, internal_imputer_fit_count=0,
        historical_observed_cells=int(observed.sum()), warnings=[])
    if method == 'svc':
        model = _svc(feature_order)
        started('PREDICTOR')
        with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=2):
            warnings.simplefilter('always')
            model.fit(z,(target>0).astype(int))
        metadata['warnings']=[dict(category=w.category.__name__,message=str(w.message)) for w in caught]
        if model.fit_status_ != 0 or any(issubclass(w.category,ConvergenceWarning) for w in caught):
            raise RuntimeError('NATIVE_SVC_FAILED_TO_CONVERGE_NO_RETRY_OR_APPROXIMATION')
        metadata.update(predictor_fit_count=1, raw_output_semantics='SIGNED_NATIVE_DECISION_FUNCTION',
                        actual_estimator_parameters=model.get_params(deep=False))
        return ExtensionFit(method,tuple(feature_order),scaler,model,metadata)
    torch = _torch(dependency_paths)
    torch.manual_seed(SEED)
    model = _network(method,torch)
    optimizer = torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.01)
    xx = torch.from_numpy(z)
    yy = torch.tensor(target/TARGET_SCALE,dtype=torch.float32)
    generator = torch.Generator().manual_seed(SEED)
    loss_function = _native_loss()
    started('PREDICTOR')
    model.train()
    losses=[]
    for epoch in range(EPOCHS):
        order=torch.randperm(len(xx),generator=generator)
        total=0.
        for start in range(0,len(xx),BATCH):
            ids=order[start:start+BATCH]
            optimizer.zero_grad(set_to_none=True)
            loss=loss_function(method,model(xx[ids]),yy[ids],torch.ones(len(ids)))
            if not torch.isfinite(loss):
                raise RuntimeError('NONFINITE_DAILY_SEQUENCE_TRAINING_LOSS')
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(),2.)
            optimizer.step()
            total+=float(loss.detach())*len(ids)
        losses.append(total/len(xx))
    model.eval()
    state={name:value.detach().cpu().numpy().copy() for name,value in model.state_dict().items()}
    metadata.update(predictor_fit_count=1, epochs=EPOCHS, optimizer_steps=EPOCHS*int(np.ceil(len(x)/BATCH)),
        loss_by_epoch=losses, raw_output_semantics='RAW_UNCLIPPED_SHAREHOLDER_RETURN_POINT',
        torch_version=torch.__version__, torch_source_path=torch.__file__, torch_init_sha256=_sha(torch.__file__))
    return ExtensionFit(method,tuple(feature_order),scaler,state,metadata,tuple(map(str,dependency_paths)))


def raw_predict(artifact, X, mask=None):
    _feature_order(artifact.feature_order)
    sequence=artifact.method!='svc'
    z=_standardized(artifact.scaler,X,mask,sequence)
    if not len(z):
        return np.empty(0,dtype=float)
    if not sequence:
        with threadpool_limits(limits=2):
            result=artifact.estimator.decision_function(z)
    else:
        torch=_torch(artifact.dependency_paths)
        if artifact._model is None:
            artifact._model=_network(artifact.method,torch)
            artifact._model.load_state_dict({k:torch.from_numpy(v.copy()) for k,v in artifact.estimator.items()})
            artifact._model.eval()
        parts=[]
        with torch.no_grad():
            for start in range(0,len(z),BATCH):
                parts.append(artifact._model(torch.from_numpy(z[start:start+BATCH])).numpy().astype(float)*TARGET_SCALE)
        result=np.concatenate(parts)
    result=np.asarray(result,dtype=float)
    if result.shape!=(len(z),) or not np.isfinite(result).all():
        raise RuntimeError('NONFINITE_EXTENSION_RAW_PREDICTIONS')
    return result


def sequence_windows(reader, framekeys, length=LENGTH):
    """Batch past joins through the sole reader; all keys retained with L20 masks.

    No labels are read. Each key has its own calendar<=decision window; future
    batch rows cannot enter an earlier key. Calendar-start padding is NaT/NaN and
    explicitly unobserved, never a fabricated zero return or session.
    """
    if length!=LENGTH:
        raise ValueError('FROZEN_L20_REQUIRED')
    keys=framekeys[['signal_date','ticker']].copy().reset_index(drop=True)
    keys['signal_date']=pd.to_datetime(keys.signal_date)
    if keys.empty or keys.duplicated().any() or keys.signal_date.ge(BOUNDARY).any():
        raise ValueError('SEQUENCE_KEYS_OR_BOUNDARY')
    positions=reader.calendar.get_indexer(keys.signal_date)
    if np.any(positions<0):
        raise ValueError('SEQUENCE_SIGNAL_NOT_ON_CALENDAR')
    known=pd.MultiIndex.from_frame(reader.pred_flags[['signal_date','ticker']])
    if not pd.MultiIndex.from_frame(keys).isin(known).all():
        raise ValueError('SEQUENCE_KEY_NOT_IN_FROZEN_PREDICTION_POOL')
    lags=positions[:,None]-np.arange(LENGTH-1,-1,-1)[None,:]
    valid=lags>=0
    dates=np.full(lags.shape,np.datetime64('NaT','ns'),dtype='datetime64[ns]')
    dates[valid]=reader.calendar.to_numpy()[lags[valid]]
    names=keys.ticker.unique().tolist()
    earliest=pd.Timestamp(dates[valid].min());latest=keys.signal_date.max()
    flags=reader.pred_flags.loc[reader.pred_flags.signal_date.between(earliest,latest)&reader.pred_flags.ticker.isin(names)].reset_index(drop=True)
    vectors=reader._vectors('prediction_feature_panel',['signal_date','ticker',*FEATURES],
        [('signal_date','>=',earliest),('signal_date','<=',latest),('ticker','in',names),
         ('feature_available','==',True),('feature_source','in',list(ALLOWED_SOURCES))])
    source=_join_vectors(flags,vectors).set_index(['signal_date','ticker'])
    lookup=pd.MultiIndex.from_arrays([dates[valid],np.broadcast_to(keys.ticker.to_numpy()[:,None],lags.shape)[valid]],names=['signal_date','ticker'])
    indices=source.index.get_indexer(lookup)
    x=np.full((len(keys),LENGTH,len(FEATURES)),np.nan,dtype=np.float32)
    available=indices>=0
    flat=x.reshape(-1,len(FEATURES));flat_ids=np.flatnonzero(valid.ravel())[available]
    flat[flat_ids]=source[list(FEATURES)].to_numpy(dtype=np.float32)[indices[available]]
    mask=np.isfinite(x)
    return dict(keys=keys, dates=dates, features=x, cell_observed=mask,
        step_available=mask.any(axis=2), window_complete=valid.all(axis=1),
        left_pad_sessions=(~valid).sum(axis=1), role='DAILY_20_US_SESSION_STOCK_VALUE')
