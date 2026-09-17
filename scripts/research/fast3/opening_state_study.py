"""Fixed shared Logistic state model; this section merges into the task entrypoint."""
from __future__ import annotations

import hashlib
import inspect
import json
import warnings

import numpy as np
import pandas as pd
import sklearn
import scipy
from sklearn.exceptions import ConvergenceWarning
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

STATE_MAIN = ("g", "abs_g", "o", "l", "s", "e", "p", "v", "q", "b", "d", "abs_d", "a", "sq", "sb")
STATE_INTERACTIONS = {"ov": ("o", "v"), "oe": ("o", "e"), "o_abs_g": ("o", "abs_g"),
                      "oa": ("o", "a"), "dv": ("d", "v"), "de": ("d", "e")}
STATE_MARKET = ("q", "b", "sq", "sb")
STATE_TICKERS = ("NVDA", "AMD", "AVGO", "ENPH")
STATE_L2, STATE_DEVIATION_MULTIPLIER = 0.01, 10.0
STATE_CUTOFF = pd.Timestamp("2026-01-01T00:00:00Z")


class FitFailure(RuntimeError):
    pass


class ConvergenceFailure(FitFailure):
    pass


def state_parameters(weight_sum, max_iter=2000):
    if weight_sum <= 0 or max_iter not in (2000, 4000):
        raise ValueError("Invalid fixed fit weight or iteration cap")
    return {"solver": "lbfgs", "l1_ratio": 0.0, "C": 1 / (STATE_L2 * weight_sum),
            "tol": 1e-6, "max_iter": max_iter, "class_weight": None,
            "fit_intercept": True, "random_state": 104729, "warm_start": False}


def state_model_contract(config):
    from sklearn.linear_model import _logistic
    from sklearn.linear_model._linear_loss import LinearModelLoss
    quality = _state_quality(config)
    return {"versions": {"sklearn": sklearn.__version__, "numpy": np.__version__, "scipy": scipy.__version__},
        "main_columns": list(STATE_MAIN), "interactions": {name: list(pair) for name, pair in STATE_INTERACTIONS.items()},
        "quality_columns": quality, "missing_flags": [f"missing_{c}" for c in (*STATE_MAIN, *STATE_INTERACTIONS)],
        "tickers": list(STATE_TICKERS), "objective": "equal_date_mean_LogLoss + .01/2*(public_coef_squared_sum + 10*stock_deviation_squared_sum)",
        "weight_rule": "each_training_date_total_1; S=number_of_dates; C=1/(.01*S)",
        "public_intercept_penalty": 0, "stock_columns": "fixed_intercept_and_transformed_o_slopes_divided_by_sqrt10_no_rescaling",
        "ordinary_numeric_transform": "T_row_median_keep_empty_zero; T_date_weighted_StandardScaler; clip[-5,5]",
        "missing_transform": "raw_missing_flags_0_1_shared_M0_M1; no_scaling",
        "BM_columns": [*STATE_MARKET, *[f"missing_{c}" for c in STATE_MARKET]],
        "native_example_parameters_S_180": LogisticRegression(**state_parameters(180)).get_params(),
        "effective_regularization": "L2 through sklearn1.9 l1_ratio=0.0; deprecated penalty API left at native default",
        "calibration": None, "cv": None, "early_stopping": None, "max_threads": 2,
        "lbfgs_source_sha256": hashlib.sha256(inspect.getsource(_logistic._logistic_regression_path).encode()).hexdigest(),
        "linear_loss_source_sha256": hashlib.sha256(inspect.getsource(LinearModelLoss.loss_gradient).encode()).hexdigest()}


def _state_quality(config):
    quality = list(config.get("quality_columns", []))
    if len(set(quality)) != len(quality) or set(quality) & set((*STATE_MAIN, *STATE_INTERACTIONS)):
        raise ValueError("Quality columns must be unique and distinct from numeric effects")
    if any(any(term in c.lower() for term in ("label", "return", "target", "future", "ticker", "security")) for c in quality):
        raise ValueError("Unsafe quality field")
    return quality


def _state_raw(frame, config):
    columns = [*STATE_MAIN, *_state_quality(config)]
    raw = frame.loc[:, columns].apply(pd.to_numeric, errors="raise").replace([np.inf, -np.inf], np.nan)
    for name, (left, right) in STATE_INTERACTIONS.items():
        values = (raw[left] * raw[right]).replace([np.inf, -np.inf], np.nan)
        if name in frame and not np.allclose(pd.to_numeric(frame[name], errors="raise"), values, rtol=0, atol=1e-12, equal_nan=True):
            raise FitFailure(f"RAW_INTERACTION_DEFINITION_MISMATCH:{name}")
        raw[name] = values
    return raw


def state_date_weights(frame, config):
    date_column = config.get("date_column", "date")
    dates = pd.Series(frame[date_column].to_numpy())
    if dates.empty or dates.isna().any():
        raise FitFailure("MISSING_TRAINING_DATES")
    return 1 / dates.groupby(dates).transform("size").to_numpy(float)


def _state_input_identity(frame, raw, config):
    identity = frame.loc[:, [config.get("date_column", "date"), "ticker"]].reset_index(drop=True)
    values = pd.concat([identity, raw.reset_index(drop=True)], axis=1)
    content = pd.util.hash_pandas_object(values, index=False).to_numpy().tobytes()
    return hashlib.sha256(content + json.dumps(list(values.columns)).encode()).hexdigest()


def make_preprocessor(train, config):
    """No labels are read; all models reuse exactly these T-only column statistics."""
    dates = pd.to_datetime(train[config.get("date_column", "date")], utc=True)
    cutoff = pd.Timestamp(config["fit_cutoff_utc"])
    if cutoff.tzinfo is None or dates.isna().any() or (dates >= min(cutoff, STATE_CUTOFF)).any():
        raise FitFailure("PREPROCESSOR_DATE_BOUNDARY")
    raw = _state_raw(train, config)
    imputer = SimpleImputer(strategy="median", keep_empty_features=True, add_indicator=False)
    filled = imputer.fit_transform(raw)
    scaler = StandardScaler().fit(filled, sample_weight=state_date_weights(train, config))
    return {"columns": list(raw.columns), "quality_columns": _state_quality(config),
            "imputer": imputer, "scaler": scaler,
            "training_input_identity": _state_input_identity(train, raw, config),
            "metadata": {"median": imputer.statistics_.tolist(), "mean": scaler.mean_.tolist(),
                         "scale": scaler.scale_.tolist(), "empty_columns": raw.columns[raw.isna().all()].tolist()}}


def state_design(preprocessor, frame, model_id, config, trained_tickers):
    if model_id not in ("M0", "M1", "BM"):
        raise ValueError("Unknown fixed model")
    unknown = set(frame.ticker.unique()) - set(STATE_TICKERS)
    if unknown:
        raise FitFailure(f"OUT_OF_FIXED_STOCK_SCOPE:{sorted(unknown)}")
    if model_id == "BM":
        # Only the four market values are read or transformed for this baseline.
        raw = frame.loc[:, list(STATE_MARKET)].apply(pd.to_numeric, errors="raise").replace([np.inf, -np.inf], np.nan)
        indices = [preprocessor["columns"].index(name) for name in STATE_MARKET]
        median = preprocessor["imputer"].statistics_[indices]
        filled = np.where(np.isnan(raw.to_numpy()), median, raw.to_numpy())
        scaled = (filled - preprocessor["scaler"].mean_[indices]) / preprocessor["scaler"].scale_[indices]
    else:
        raw = _state_raw(frame, config)
        if list(raw.columns) != preprocessor["columns"] or _state_quality(config) != preprocessor["quality_columns"]:
            raise FitFailure("PREPROCESSOR_SCHEMA_MISMATCH")
        scaled = preprocessor["scaler"].transform(preprocessor["imputer"].transform(raw))
    scaled = pd.DataFrame(scaled, columns=raw.columns, index=raw.index)
    numeric = (list(STATE_MARKET) if model_id == "BM" else
               [*STATE_MAIN, *_state_quality(config), *(STATE_INTERACTIONS if model_id == "M1" else [])])
    clipping = {name: int((scaled[name].abs() > 5).sum()) for name in numeric}
    design = scaled.loc[:, numeric].clip(-5, 5).copy()
    missing = STATE_MARKET if model_id == "BM" else (*STATE_MAIN, *STATE_INTERACTIONS)
    for name in missing:
        design[f"missing_{name}"] = raw[name].isna().astype(float)
    if model_id != "BM":
        for ticker in STATE_TICKERS:
            indicator = (frame.ticker.eq(ticker).astype(float) if ticker in trained_tickers else np.zeros(len(frame)))
            design[f"stock_intercept_{ticker}"] = indicator / np.sqrt(STATE_DEVIATION_MULTIPLIER)
            design[f"stock_o_{ticker}"] = indicator * scaled["o"].clip(-5, 5) / np.sqrt(STATE_DEVIATION_MULTIPLIER)
    return design, clipping


def _state_training_info(train, horizon, config):
    if horizon not in ("H15", "H60", "H1230"):
        raise ValueError("Unknown fixed horizon")
    date_column = config.get("date_column", "date")
    dates = pd.to_datetime(train[date_column], utc=True)
    y = train[config.get("label_columns", {}).get(horizon, f"y_{horizon}")].to_numpy()
    maturity = pd.to_datetime(train[config.get("maturity_columns", {}).get(horizon, f"label_available_{horizon}")], utc=True)
    cutoff = pd.Timestamp(config["fit_cutoff_utc"])
    if cutoff.tzinfo is None:
        raise FitFailure("FIT_CUTOFF_REQUIRES_TIMEZONE")
    if dates.isna().any() or maturity.isna().any() or (maturity >= min(cutoff, STATE_CUTOFF)).any() or (dates >= STATE_CUTOFF).any():
        raise FitFailure("LABEL_MATURITY_OR_PRE2026_BOUNDARY")
    if dates.nunique() < 180:
        raise FitFailure("INSUFFICIENT_180_TRAINING_DATES")
    if not np.array_equal(np.unique(y), [0, 1]):
        raise FitFailure("SINGLE_CLASS_OR_INVALID_LABEL")
    date_text = dates.dt.strftime("%Y-%m-%d")
    if not np.array_equal(date_text, maturity.dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")):
        raise FitFailure("LABEL_MATURITY_DATE_MISMATCH")
    return y.astype(int), {"rows": len(train), "dates": int(dates.nunique()),
        "first_date": date_text.min(), "last_date": date_text.max(),
        "max_label_available_at": maturity.max().isoformat(), "fit_cutoff_utc": cutoff.isoformat()}


def fit_state(train, horizon, model_id, config, preprocessor=None, max_iter=2000, on_fit=None):
    y, metadata = _state_training_info(train, horizon, config)
    preprocessor = make_preprocessor(train, config) if preprocessor is None else preprocessor
    raw = _state_raw(train, config)
    if preprocessor["training_input_identity"] != _state_input_identity(train, raw, config):
        raise FitFailure("PREPROCESSOR_NOT_FROM_EXACT_TRAINING_INPUTS")
    trained_tickers = sorted(train.ticker.unique())
    design, clipping = state_design(preprocessor, train, model_id, config, trained_tickers)
    weight = state_date_weights(train, config)
    total_weight = float(weight.sum())
    params = state_parameters(total_weight, max_iter)
    estimator = LogisticRegression(**params)
    event = {"kind": "base", "horizon": horizon, "model_id": model_id, "max_iter": max_iter}
    if on_fit:
        on_fit({**event, "status": "STARTED"})
    try:
        with threadpool_limits(limits=2), warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter("always")
            estimator.fit(design, y, sample_weight=weight)
        if any(issubclass(w.category, ConvergenceWarning) for w in seen):
            raise ConvergenceFailure("LBFGS_NUMERICAL_NONCONVERGENCE")
        if not np.array_equal(estimator.classes_, [0, 1]) or not np.isfinite(estimator.coef_).all() or not np.isfinite(estimator.intercept_).all():
            raise FitFailure("INVALID_FITTED_CLASS_OR_COEFFICIENT")
        coefficient = estimator.coef_[0]
        score = estimator.decision_function(design)
        probability = estimator.predict_proba(design)[:, 1]
        ll = float(weight @ (np.logaddexp(0, score) - y * score) / total_weight)
        penalty = float(STATE_L2 / 2 * (coefficient @ coefficient))
        gradient = design.to_numpy().T @ (weight * (probability - y)) / total_weight + STATE_L2 * coefficient
        deviations = {name: float(value / np.sqrt(10)) for name, value in zip(design.columns, coefficient) if name.startswith("stock_")}
        metadata.update(S=total_weight, C=params["C"], actual_params=estimator.get_params(),
            weights=weight.tolist(), weight_rule="each_date_total_1", coef_names=list(design.columns),
            coefficients=coefficient.tolist(), intercept=float(estimator.intercept_[0]), stock_deviation=deviations,
            stock_deviation_basis="intercept and clipped standardized o; effective deviation=design coefficient/sqrt10; absent-T ticker deviation zero",
            preprocessor_identity=preprocessor["training_input_identity"], clip_counts_train=clipping,
            n_iter=estimator.n_iter_.tolist(), optimizer_status="CONVERGED_NO_CONVERGENCE_WARNING",
            warnings=[str(w.message) for w in seen], train_log_loss=ll, objective=ll + penalty,
            regularization_penalty=penalty, max_abs_gradient=float(max(np.max(np.abs(gradient)), abs(weight @ (probability-y) / total_weight))))
        if on_fit:
            on_fit({**event, "status": "FINISHED", "metadata": metadata})
        return {"model_id": model_id, "horizon": horizon, "estimator": estimator,
            "preprocessor": preprocessor, "config": dict(config), "trained_tickers": trained_tickers, "metadata": metadata}
    except Exception as exc:
        if on_fit:
            on_fit({**event, "status": "FAILED", "reason": f"{type(exc).__name__}: {exc}"})
        raise


def predict_state(bundle, frame):
    if not np.array_equal(bundle["estimator"].classes_, [0, 1]):
        raise FitFailure("INVALID_PREDICTION_CLASS_ORDER")
    design, clipping = state_design(bundle["preprocessor"], frame, bundle["model_id"], bundle["config"], bundle["trained_tickers"])
    if list(design.columns) != bundle["metadata"]["coef_names"]:
        raise FitFailure("PREDICTION_DESIGN_MISMATCH")
    with threadpool_limits(limits=2):
        probability = bundle["estimator"].predict_proba(design)[:, 1]
        score = bundle["estimator"].decision_function(design)
    if not np.isfinite(probability).all() or not np.isfinite(score).all():
        raise FitFailure("NONFINITE_PREDICTION")
    return {"p_up": probability, "p_not_up": 1-probability, "raw_score": score,
            "predicted_up": (probability >= 0.5).astype(int), "clip_counts": clipping}


# Quarterly orchestration and evaluation for the fixed state/horizon experiment.
# This fragment is joined to model_part.py before installing one research module.
from datetime import datetime, timezone
from pathlib import Path
import time
import hashlib
import json
import joblib
from sklearn.metrics import roc_auc_score
from . import opening_study as evidence

STATE_TASK = 'FAST3_OPENING_STATE_HORIZON_R1'
FULL_STATE_TASK = 'FAST3_SHARE_UNIT_RECOVERY_AND_FULL_STATE_TEST_R1'
FULL_STATE_AUTH = {'ADOPTION_ALLOWED':False,'LIVE_TRADING_ALLOWED':False,
                   'TRADE_API_ALLOWED':False,'ORDER_GENERATION_ALLOWED':False,
                   'READ_ONLY_CORPORATE_ACTION_QUERY_ALLOWED':True}
HORIZONS = {'H15': ('10:01', '10:02'), 'H60': ('10:46', '10:47'), 'H1230': ('12:30', '12:31')}
QUARTERS = tuple(f'{year}Q{quarter}' for year in (2023,2024,2025) for quarter in (1,2,3,4))
GLOBAL_CUTOFF = pd.Timestamp('2026-01-01T00:00:00Z')
PROTECTED = {'ADOPTION_ALLOWED': False, 'LIVE_TRADING_ALLOWED': False, 'BROKER_ACTION_ALLOWED': False}
FIXED_MODELS = ('M0', 'M1', 'BM')


def is_full_state(config):
    return config.get('task_id')==FULL_STATE_TASK


def public_state_id(model_id, config):
    return model_id+'_FULL' if is_full_state(config) and model_id in ('M0','M1') else model_id


def state_code_identity(config=None):
    root = Path(__file__).parent
    names=['opening_state_data.py','opening_state_study.py','opening_data.py','opening_study.py','stock_open_3h.py']
    if config and is_full_state(config):
        names.append('share_unit_data.py')
    return {name:evidence.sha(root/name) for name in names}


def full_state_baseline_reuse(panel,config):
    """Component identity, without a new estimator or preprocessor fit."""
    if config.get('core_input_gate',{}).get('status')!='PASS':
        raise ValueError('FULL_STATE_INPUT_GAP_NO_REAL_FIT')
    parent=Path(config['parent_result_root'])
    manifest=json.loads((parent/'delivery-manifest.json').read_text(encoding='utf-8'))
    pins={x['path']:x['sha256'] for x in manifest['artifacts']}
    if config.get('parent_manifest_sha256') and evidence.sha(parent/'delivery-manifest.json')!=config['parent_manifest_sha256']:
        raise ValueError('PARENT_MANIFEST_IDENTITY_CHANGED')
    refs={}
    def check(name):
        actual=evidence.sha(parent/name)
        if actual!=pins[name]:
            raise ValueError('PARENT_COMPONENT_CHANGED:'+name)
        refs[name]=actual
        return parent/name
    old_protocol=json.loads(check('evaluation/frozen_protocol.json').read_text(encoding='utf-8'))
    if state_model_contract(config)!=old_protocol['model_contract']:
        raise ValueError('PARENT_ESTIMATOR_CONTRACT_CHANGED')
    old=validate_state_panel(pd.read_parquet(check('research-data/panel.parquet')),config)
    allowed={'g','abs_g','v','a','ov','o_abs_g','oa','dv','quality_gap_unit_uncertified',
             'quality_volume_unit_uncertified','unit_gap_reason','unit_volume_reason'}
    unchanged=[c for c in old if c not in allowed]
    pd.testing.assert_frame_equal(old[unchanged],panel[unchanged],check_exact=True)
    baseline_oos=pd.read_parquet(check('evaluation/oos_predictions.parquet'))
    priors=json.loads(check('evaluation/prior_estimates.json').read_text(encoding='utf-8'))
    expected_prior_keys={(q,h) for q in (*QUARTERS,'FINAL') for h in HORIZONS}
    if len(priors)!=39 or {(r['quarter'],r['horizon']) for r in priors}!=expected_prior_keys:
        raise ValueError('PARENT_PRIOR_KEYS_NOT_EXACT_39')
    rows=[]
    for quarter in QUARTERS:
        boundary=quarter_boundary(quarter)
        for h in HORIZONS:
            old_t,new_t=training_rows(old,h,boundary),training_rows(panel,h,boundary)
            np.testing.assert_array_equal(state_date_weights(old_t,config),state_date_weights(new_t,config))
            model=joblib.load(check(f'evaluation/models/{quarter}_{h}_BM.joblib'))
            if model.get('kind')!='learner':
                raise ValueError('PARENT_BM_NOT_REUSABLE_LEARNER')
            for segment,a,b in [('T',old_t,new_t),('E',old[pd.PeriodIndex(old.date,freq='Q')==quarter],panel[pd.PeriodIndex(panel.date,freq='Q')==quarter])]:
                da,_=state_design(model['preprocessor'],a,'BM',model['config'],model['trained_tickers'])
                db,_=state_design(model['preprocessor'],b,'BM',model['config'],model['trained_tickers'])
                pd.testing.assert_frame_equal(da,db,check_exact=True)
                expected=[*STATE_MARKET,*['missing_'+c for c in STATE_MARKET]]
                if list(da)!=expected:
                    raise ValueError('BM_CONSUMES_NONMARKET_INPUT')
                rows.append({'quarter':quarter,'horizon':h,'segment':segment,'rows':len(a),
                             'sample_ids_identity':evidence.identity(a.sample_id.tolist()),
                             'design_identity':hashlib.sha256(pd.util.hash_pandas_object(da,index=False).to_numpy().tobytes()).hexdigest()})
            for mid in ('B0','B1'):
                check(f'evaluation/models/{quarter}_{h}_{mid}.joblib')
            for mid in ('B0','B1','BM'):
                saved=baseline_oos[(baseline_oos.quarter==quarter)&(baseline_oos.horizon==h)&(baseline_oos.model_id==mid)]
                expected_rows=panel[pd.PeriodIndex(panel.date,freq='Q')==quarter]
                if saved.sample_id.duplicated().any() or len(saved)!=len(expected_rows) or set(saved.sample_id)!=set(expected_rows.sample_id):
                    raise ValueError('BASELINE_PREDICTION_POPULATION_MISMATCH')
    for item in priors:
        boundary=GLOBAL_CUTOFF if item['quarter']=='FINAL' else quarter_boundary(item['quarter'])
        t=training_rows(panel,item['horizon'],boundary)
        if not np.isclose(prior_probability(t,item['horizon']),item['p_up'],rtol=0,atol=1e-15):
            raise ValueError('PRIOR_COMPONENT_CHANGED')
    check('evaluation/diagnostics.json')
    check('evaluation/model_metadata.json')
    check('evaluation/fold_sample_ids.parquet')
    return {'status':'EXACT_COMPONENT_REUSE','parent_result_root':str(parent),'parent_manifest_sha256':evidence.sha(parent/'delivery-manifest.json'),
            'source_sha256':refs,'BM_objects_reused':36,'B0_B1_objects_reused':72,'B1_estimates_reused':39,
            'new_supervised_fits':0,'new_preprocessor_fits':0,'training_prior_checks_are_validation_not_new_estimates':True,
            'T_E_market_design_checks':rows,'contract':'Same identity, labels/maturity, weights, quarters, four raw market columns/missing flags, per-column T transform and eight-column BM design; changing unrelated panel hash does not invalidate this component.'}


def validate_state_panel(panel, config):
    required = ['sample_id','date','ticker','security_uid','prediction_at_utc','feature_cutoff_utc','label_start_utc',
                *config['main_columns'],*config['interaction_columns'],*config['quality_columns']]
    required += [name+h for h in HORIZONS for name in ('y_','return_','label_available_','label_end_','label_reason_')]
    if set(required)-set(panel):
        raise ValueError('Missing panel fields: '+str(set(required)-set(panel)))
    if panel.sample_id.duplicated().any() or set(panel.ticker.unique()) != {'AMD','NVDA','AVGO','ENPH'}:
        raise ValueError('Historical prediction population changed')
    if 'eligible' in panel and not panel.eligible.all():
        raise ValueError('Ineligible predictions')
    clock_columns = {'prediction_at_utc':'09:45','feature_cutoff_utc':'09:44','label_start_utc':'09:46'}
    for h,(end,mature) in HORIZONS.items():
        clock_columns['label_end_'+h] = end
        clock_columns['label_available_'+h] = mature
    for col,clock in clock_columns.items():
        panel[col] = pd.to_datetime(panel[col],utc=True)
        local = panel[col].dt.tz_convert('America/New_York')
        if panel[col].isna().any() or not local.dt.strftime('%H:%M').eq(clock).all() or not local.dt.strftime('%Y-%m-%d').eq(panel.date).all():
            raise ValueError('Clock/date mismatch: '+col)
        if panel[col].ge(GLOBAL_CUTOFF).any():
            raise ValueError('2026 data reached training interface')
    for h in HORIZONS:
        valid = panel['y_'+h].notna()
        if not panel.loc[valid,'y_'+h].eq(panel.loc[valid,'return_'+h].gt(0).astype(int)).all():
            raise ValueError('Target definition mismatch '+h)
        if not np.isfinite(panel.loc[valid,'return_'+h]).all():
            raise ValueError('Invalid finite target '+h)
    return panel.sort_values(['date','ticker']).reset_index(drop=True)


def quarter_boundary(quarter):
    return pd.Timestamp(pd.Period(quarter,freq='Q').start_time,tz='UTC')


def training_rows(panel,horizon,boundary):
    return panel.loc[panel['y_'+horizon].notna() & panel['label_available_'+horizon].lt(min(boundary,GLOBAL_CUTOFF))].copy()


def state_segment(frame,horizon):
    return {'rows':len(frame),'dates':frame.date.nunique(),'first_date':frame.date.min(),'last_date':frame.date.max(),
            'label_maturity_max':frame['label_available_'+horizon].max(),
            'sample_ids_sha256':evidence.identity(frame.sample_id.tolist())}


def freeze_state(dataset,output):
    dataset,output = Path(dataset),Path(output)
    output.mkdir(parents=True,exist_ok=True)
    if (output/'frozen_protocol.json').exists() or (output/'fit_events.jsonl').exists():
        raise ValueError('Existing study freeze/fit evidence is immutable')
    config = json.loads((dataset/'data_config.json').read_text(encoding='utf-8'))
    if evidence.sha(dataset/'panel.parquet') != config['panel_sha256']:
        raise ValueError('Input identity mismatch')
    panel = validate_state_panel(pd.read_parquet(dataset/'panel.parquet'),config)
    full=is_full_state(config)
    reuse=full_state_baseline_reuse(panel,config) if full else None
    folds,ids = [],[]
    for quarter in (*QUARTERS,'FINAL'):
        boundary = GLOBAL_CUTOFF if quarter=='FINAL' else quarter_boundary(quarter)
        test = panel.iloc[:0] if quarter=='FINAL' else panel[pd.PeriodIndex(panel.date,freq='Q')==quarter]
        for h in HORIZONS:
            train = training_rows(panel,h,boundary)
            if len(test) and len(train) and train['label_available_'+h].max() >= test.prediction_at_utc.min():
                raise ValueError('Unmatured quarterly label')
            status = ('EXECUTABLE' if train.date.nunique()>=180 and train['y_'+h].nunique()==2
                      else 'FALLBACK_INSUFFICIENT_OR_SINGLE_CLASS')
            folds.append({'quarter':quarter,'horizon':h,'boundary_utc':boundary,'train':state_segment(train,h),
                          'prediction':state_segment(test,h),'evaluable_test_rows':int(test['y_'+h].notna().sum()),
                          'status':status})
            for part,rows in [('T',train),('E',test)]:
                ids.extend({'quarter':quarter,'horizon':h,'segment':part,'sample_id':sid} for sid in rows.sample_id)
    pd.DataFrame(ids).to_parquet(output/'fold_sample_ids.parquet',index=False)
    plan = [{'quarter':q,'horizon':h,'models':list(FIXED_MODELS) if q!='FINAL' else ['M1']}
            for q in (*QUARTERS,'FINAL') for h in HORIZONS]
    protocol = {'task_id':STATE_TASK,'frozen_before_first_fit_utc':datetime.now(timezone.utc).isoformat(),
        'panel_sha256':config['panel_sha256'],'sample_manifest_sha256':config['sample_manifest_sha256'],
        'data_config_sha256':evidence.sha(dataset/'data_config.json'),
        'fold_sample_ids_sha256':evidence.sha(output/'fold_sample_ids.parquet'),'source_code':state_code_identity(),
        'model_contract':state_model_contract(config),'folds':folds,'fit_plan':plan,
        'horizons':HORIZONS,'primary_horizon':'H1230','clock':'NY 09:45; end-stamped features <=09:44; start=09:47 bar open',
        'evaluation':'fixed specifications; quarterly expanding-window OOS; no inner CV or candidate selection',
        'budget':{'quarterly_models':108,'final_M1':3,'planned_supervised':111,'hard_cap':132,
                  'retry_reserve':21,'retry':'one max_iter=4000 retry for nonconvergence, identical data/objective',
                  'B1_quarterly_estimates':36,'B1_final_offline_fallback_estimates':3,'synthetic_fits':'separate ledger'},
        'preprocessing':'T-only shared M0/M1 transform; raw interactions and their shared missing flags before imputation',
        'input_fallback':{'M0_M1':'o nonfinite -> prior B1; g/v isolation never itself triggers fallback',
                          'BM':'q,b,sq,sb all missing -> prior B1','empty_prior':'B0',
                          'fit_failure':'preserve quarter and all predictions; B1/B0 fallback; support withheld for engineering failure'},
        'statistics':{'unit':'trading_day','loss_clip':[1e-6,1-1e-6],'direction_threshold':.5,
                      'reliability_edges':[i/10 for i in range(11)],'bootstrap':'noncircular moving block',
                      'block_dates':20,'replications':10000,'seed':104729,'same_indices_for_all_contrasts':True,
                      'raw_quantiles':[.025,.975],'adjusted_quantiles':[.05/6,1-.05/6],
                      'confidence_adjusted':1-.05/3,'minimum_years':3,'minimum_dates':250,
                      'contrasts':['M1-M0','M1-B0','M1-B1','M1-BM'],
                      'support':'all four adjusted upper bounds <0 plus coverage and no model failure; no 12-comparison simultaneous claim'},
        'unit_and_feature_scope':config.get('unit_audit',{}),
        'final_role':'Always fit three final M1 research models. Default H1230 is B0 unless H1230 supports; short support never changes default',
        'history':'Exploratory after prior FAST3 exposures; no pristine holdout or independent information claim',**PROTECTED}
    if full:
        parent=Path(config['parent_result_root'])
        old_protocol=json.loads((parent/'evaluation/frozen_protocol.json').read_text(encoding='utf-8'))
        pd.testing.assert_frame_equal(pd.read_parquet(output/'fold_sample_ids.parquet'),pd.read_parquet(parent/'evaluation/fold_sample_ids.parquet'),check_exact=True)
        if protocol['statistics']!=old_protocol['statistics'] or protocol['folds']!=old_protocol['folds']:
            # Timestamps in the new in-memory fold records are normalized before comparison.
            serialized_folds=json.loads(json.dumps(evidence.clean(protocol['folds']),default=str))
            if serialized_folds!=old_protocol['folds'] or protocol['statistics']!=old_protocol['statistics']:
                raise ValueError('PARENT_FOLD_OR_INFERENCE_DEFINITION_CHANGED')
        protocol.update(task_id=FULL_STATE_TASK,source_code=state_code_identity(config),component_reuse=reuse,
                        core_input_gate=config['core_input_gate'],public_model_ids={'M0':'M0_FULL','M1':'M1_FULL'},
                        parent_frozen_protocol_sha256=evidence.sha(parent/'evaluation/frozen_protocol.json'),**FULL_STATE_AUTH)
        protocol['fit_plan']=[{**entry,'models':['M0','M1'] if entry['quarter']!='FINAL' else ['M1']} for entry in plan]
        protocol['budget'].update(quarterly_models=72,planned_supervised=75,BM_new_fits=0,
            BM_reused_models=36,B1_quarterly_estimates=0,B1_final_offline_fallback_estimates=0,B1_reused_estimates=39,
            conditional_plan_upper_bound=111,conditional_BM_refit_rule='Only if component identity fails; this frozen run has exact reuse, so no BM refits')
        protocol['unit_and_feature_scope']=config.get('unit_recovery',config.get('unit_audit',{}))
        protocol.pop('BROKER_ACTION_ALLOWED',None)
        evidence.write_json(output/'component_reuse.json',reuse)
    evidence.write_json(output/'frozen_protocol.json',protocol)
    print(json.dumps({'frozen':str(output/'frozen_protocol.json'),'planned_supervised_fits':protocol['budget']['planned_supervised']}),flush=True)
    return protocol


def state_metrics(rows):
    valid = rows.y.notna() & np.isfinite(rows.p_up)
    x = rows.loc[valid].copy()
    if x.empty:
        return {},pd.DataFrame(columns=['date','log_loss','brier','accuracy','rows'])
    y,p = x.y.to_numpy(float),x.p_up.to_numpy(float)
    bounded = np.clip(p,1e-6,1-1e-6)
    row_loss = -(y*np.log(bounded)+(1-y)*np.log1p(-bounded))
    d = pd.DataFrame({'date':x.date.to_numpy(),'log_loss':row_loss,'brier':(p-y)**2,'accuracy':((p>=.5)==y).astype(float)})
    daily = d.groupby('date',sort=True).mean()
    daily['rows'] = d.groupby('date').size()
    total = {'rows':len(x),'dates':len(daily),'years':x.date.str[:4].nunique(),
             **{k:float(daily[k].mean()) for k in ('log_loss','brier','accuracy')},
             'flat_rows':int(x.r.eq(0).sum()),'strict_down_rows':int(x.r.lt(0).sum()),'up_rows':int(x.y.sum()),
             'auc_pooled':float(roc_auc_score(y,p)) if x.y.nunique()==2 else None,
             'auc_date_weighted_pooled':float(roc_auc_score(y,p,sample_weight=1/x.groupby('date').date.transform('size'))) if x.y.nunique()==2 else None}
    return total,daily.reset_index()


def state_reliability(rows):
    x = rows[rows.y.notna()].copy()
    x['w'] = 1/x.groupby('date').date.transform('size')
    x['bin'] = np.minimum((x.p_up*10).astype(int),9)
    return [{'bin':i,'lower':i/10,'upper':(i+1)/10,'rows':len(g),'dates':g.date.nunique(),
             'mean_probability':float(np.average(g.p_up,weights=g.w)) if len(g) else None,
             'observed_up':float(np.average(g.y,weights=g.w)) if len(g) else None}
            for i in range(10) for g in [x[x.bin==i]]]


def prior_probability(train,horizon):
    return float(train.groupby('date')['y_'+horizon].mean().mean()) if len(train) else .5


def constant_state(model_id,horizon,probability,cutoff=None,reason=None):
    return {'kind':'constant','task_id':STATE_TASK,'model_id':model_id,'horizon':horizon,'p_up':probability,
            'metadata':{'max_label_available_at':cutoff},'fallback_reason':reason,**PROTECTED}


def prediction_rows(bundle,frame,horizon,model_id,prior,quarter):
    names = ['sample_id','ticker','security_uid','date','prediction_at_utc','feature_cutoff_utc','label_start_utc']
    x = frame[names].copy()
    x['label_end_utc'],x['label_available_at_utc'] = frame['label_end_'+horizon],frame['label_available_'+horizon]
    x['r'],x['y'],x['label_reason'] = frame['return_'+horizon],frame['y_'+horizon],frame['label_reason_'+horizon]
    if bundle.get('kind')=='constant':
        raw = np.full(len(x),np.nan)
        p = np.full(len(x),bundle['p_up'])
        reason = pd.Series(bundle.get('fallback_reason'),index=x.index,dtype='object')
        clips = {}
    else:
        prediction_error = None
        try:
            out = predict_state(bundle,frame)
        except (FitFailure, ValueError, FloatingPointError) as exc:
            prediction_error = f'{type(exc).__name__}:{exc}'
            out = {'p_up':np.full(len(x),prior),'raw_score':np.full(len(x),np.nan)}
        p,raw = np.asarray(out['p_up'],float),np.asarray(out['raw_score'],float)
        required_missing = (~np.isfinite(frame.o.to_numpy(float)) if model_id in ('M0','M1')
                            else (~np.isfinite(frame[['q','b','sq','sb']].to_numpy(float))).all(axis=1))
        invalid = ~np.isfinite(p) | (p<0) | (p>1)
        p = p.copy()
        p[required_missing|invalid] = prior
        reason = pd.Series(None,index=x.index,dtype='object')
        prior_id = bundle['metadata'].get('prior_predictor_id','B1')
        reason.loc[required_missing] = 'NECESSARY_INPUT_MISSING_'+prior_id
        reason.loc[invalid] = 'INVALID_MODEL_PROBABILITY_'+prior_id
        if prediction_error is not None:
            reason[:] = 'PREDICTION_FAILURE_'+prior_id+':'+prediction_error
        clips = out.get('clip_counts',{})
    x['p_up'],x['p_not_up'],x['raw_score'],x['predicted_up'] = p,1-p,raw,(p>=.5).astype(int)
    x['model_id'],x['horizon'],x['quarter'] = model_id,horizon,quarter
    x['actual_predictor'] = np.where(reason.notna(),bundle['metadata'].get('prior_predictor_id','B1'),model_id)
    x['fallback_reason'] = reason
    x['fit_cutoff'] = bundle['metadata'].get('max_label_available_at')
    return x,clips


def recorded_state_fit(budget,train,h,model_id,config,preprocessor,quarter,protocol):
    if train.date.nunique()<180 or train['y_'+h].nunique()!=2:
        raise FitFailure('INSUFFICIENT_HISTORY_OR_SINGLE_CLASS')
    key = evidence.identity({'quarter':quarter,'horizon':h,'model_id':model_id,'sample_ids':train.sample_id.tolist(),
                             'panel':protocol['panel_sha256'],'code':protocol['source_code'],'contract':protocol['model_contract']})
    for attempt,max_iter in enumerate((2000,4000)):
        if budget.calls>=132 or (attempt and budget.retries>=21):
            raise RuntimeError('FIT_BUDGET_EXHAUSTED')
        fields = {'quarter':quarter,'horizon':h,'model_id':model_id,'public_model_id':public_state_id(model_id,config),
                  'category':'final' if quarter=='FINAL' else 'quarterly','stage':'base','attempt':attempt,
                  'max_iter':max_iter,'cache_key':key}
        started = time.perf_counter()
        actual_started = False
        def on_fit(event):
            nonlocal actual_started
            if event['status']=='STARTED':
                budget.calls+=1; budget.retries+=int(attempt>0)
                fields['fit_number']=budget.calls
                actual_started=True
            budget.event({**fields,**event,'seconds':time.perf_counter()-started})
        try:
            bundle = fit_state(train,h,model_id,config,preprocessor=preprocessor,max_iter=max_iter,on_fit=on_fit)
            bundle.update(kind='learner',task_id=FULL_STATE_TASK if is_full_state(config) else STATE_TASK,
                          horizon=h,model_id=model_id,cache_key=key,**PROTECTED)
            if is_full_state(config):
                bundle.update(public_model_id=public_state_id(model_id,config),**FULL_STATE_AUTH)
                bundle.pop('BROKER_ACTION_ALLOWED',None)
            return bundle
        except Exception as exc:
            if not actual_started:
                budget.event({**fields,'status':'PREFLIGHT_REJECTED','seconds':time.perf_counter()-started,'error':f'{type(exc).__name__}: {exc}'})
            if isinstance(exc,ConvergenceFailure) and attempt==0:
                continue
            raise


def train_state(dataset,output):
    dataset,output = Path(dataset),Path(output)
    config = json.loads((dataset/'data_config.json').read_text(encoding='utf-8'))
    protocol = json.loads((output/'frozen_protocol.json').read_text(encoding='utf-8'))
    full=is_full_state(config)
    expected_task=FULL_STATE_TASK if full else STATE_TASK
    if protocol['task_id']!=expected_task or state_code_identity(config if full else None)!=protocol['source_code'] or state_model_contract(config)!=protocol['model_contract']:
        raise ValueError('Frozen science code/dependency/contract drift')
    for file,expected in [(dataset/'panel.parquet',protocol['panel_sha256']),
                          (dataset/'sample_manifest.parquet',protocol['sample_manifest_sha256']),
                          (dataset/'data_config.json',protocol['data_config_sha256']),
                          (output/'fold_sample_ids.parquet',protocol['fold_sample_ids_sha256'])]:
        if evidence.sha(file)!=expected:
            raise ValueError('Frozen data/fold changed '+str(file))
    panel = validate_state_panel(pd.read_parquet(dataset/'panel.parquet'),config)
    parent_oos,parent_priors,parent_diagnostics=None,None,None
    if full:
        if config.get('core_input_gate',{}).get('status')!='PASS' or protocol['core_input_gate']!=config['core_input_gate']:
            raise ValueError('FULL_STATE_INPUT_GAP_NO_REAL_FIT')
        reuse=protocol['component_reuse']
        parent=Path(reuse['parent_result_root'])
        if evidence.sha(parent/'delivery-manifest.json')!=reuse['parent_manifest_sha256']:
            raise ValueError('PARENT_MANIFEST_CHANGED')
        for name,expected in reuse['source_sha256'].items():
            if evidence.sha(parent/name)!=expected:
                raise ValueError('REUSED_COMPONENT_CHANGED:'+name)
        parent_oos=pd.read_parquet(parent/'evaluation/oos_predictions.parquet')
        parent_priors={(r['quarter'],r['horizon']):r for r in json.loads((parent/'evaluation/prior_estimates.json').read_text(encoding='utf-8'))}
        parent_diagnostics=json.loads((parent/'evaluation/diagnostics.json').read_text(encoding='utf-8'))
    budget = evidence.Budget(output/'fit_events.jsonl',hard_cap=132,retry_cap=21)
    (output/'models').mkdir(exist_ok=True)
    predictions,diagnostics,failures,priors,model_metadata = [],[],[],[],[]
    preprocessor_fits,preprocessor_reuses=0,0
    for quarter in QUARTERS:
        boundary = quarter_boundary(quarter)
        e = panel[pd.PeriodIndex(panel.date,freq='Q')==quarter].copy()
        for h in HORIZONS:
            t = training_rows(panel,h,boundary)
            cfg = {**config,'fit_cutoff_utc':boundary.isoformat()}
            prior = parent_priors[(quarter,h)]['p_up'] if full else prior_probability(t,h)
            priors.append({'quarter':quarter,'horizon':h,'p_up':prior,'train':state_segment(t,h),
                           'is_estimate':bool(len(t)) and not full,'reused_parent_estimate':full})
            cutoff = t['label_available_'+h].max().isoformat() if len(t) else None
            if full:
                saved=parent_oos[(parent_oos.quarter==quarter)&(parent_oos.horizon==h)&parent_oos.model_id.isin(['B0','B1','BM'])].copy()
                saved['prediction_source']='EXACT_PARENT_COMPONENT_REUSE'
                predictions.append(saved)
                diagnostics.extend({**r,'reused_parent_component':True} for r in parent_diagnostics
                    if r['quarter']==quarter and r['horizon']==h and r['model_id']=='BM')
            for baseline,p in ([] if full else [('B0',.5),('B1',prior)]):
                reason='EMPTY_TRAINING_PREFIX_B0' if baseline=='B1' and not len(t) else None
                bundle = constant_state(baseline,h,p,cutoff if baseline=='B1' else None,reason)
                bundle['metadata']['prior_predictor_id']='B1' if len(t) else 'B0'
                rows,_ = prediction_rows(bundle,e,h,baseline,prior,quarter)
                predictions.append(rows)
                joblib.dump(bundle,output/'models'/f'{quarter}_{h}_{baseline}.joblib')
            pp = make_preprocessor(t,cfg) if len(t) else None
            preprocessor_fits+=int(pp is not None)
            preprocessor_reuses+=(1 if full else 2)*int(pp is not None)
            for model_id in (('M0','M1') if full else FIXED_MODELS):
                print(json.dumps({'quarter':quarter,'horizon':h,'model':public_state_id(model_id,config),'fit_count':budget.calls}),flush=True)
                try:
                    bundle = recorded_state_fit(budget,t,h,model_id,cfg,pp,quarter,protocol)
                    model_metadata.append({'quarter':quarter,'horizon':h,'model_id':model_id,**bundle['metadata']})
                except FitFailure as exc:
                    reason = str(exc)
                    failures.append({'quarter':quarter,'horizon':h,'model_id':model_id,'reason':reason})
                    bundle = constant_state(model_id,h,prior,cutoff,'MODEL_FAILURE_B1:'+reason)
                bundle['metadata'].update(historical_prior=prior,prior_predictor_id='B1' if len(t) else 'B0')
                if full:
                    bundle.update(task_id=FULL_STATE_TASK,public_model_id=public_state_id(model_id,config),**FULL_STATE_AUTH)
                    bundle.pop('BROKER_ACTION_ALLOWED',None)
                joblib.dump(bundle,output/'models'/f'{quarter}_{h}_{public_state_id(model_id,config)}.joblib',compress=3)
                for segment,frame in [('T',t),('E',e)]:
                    rows,clips = prediction_rows(bundle,frame,h,model_id,prior,quarter)
                    engineering = rows.fallback_reason.fillna('').str.startswith(('PREDICTION_FAILURE','INVALID_MODEL_PROBABILITY'))
                    if engineering.any():
                        failures.append({'quarter':quarter,'horizon':h,'model_id':model_id,'segment':segment,
                                         'reason':rows.loc[engineering,'fallback_reason'].iloc[0],'rows':int(engineering.sum())})
                    metrics,_ = state_metrics(rows)
                    diagnostics.append({'quarter':quarter,'horizon':h,'model_id':model_id,'segment':segment,
                                        'metrics':metrics,'clip_counts':clips,'fallback_rows':int(rows.fallback_reason.notna().sum())})
                    if segment=='E':
                        if full:
                            rows['prediction_source']='NEW_FULL_STATE_FIT'
                        predictions.append(rows)
        evidence.write_json(output/'failures.json',failures)
        evidence.write_json(output/'diagnostics.json',diagnostics)
    oos = pd.concat(predictions,ignore_index=True)
    if full:
        oos['public_model_id']=oos.model_id.map(lambda m:public_state_id(m,config))
        oos['public_actual_predictor']=oos.actual_predictor.map(lambda m:public_state_id(m,config))
    oos.to_parquet(output/'oos_predictions.parquet',index=False)
    final_models = {}
    for h in HORIZONS:
        t = training_rows(panel,h,GLOBAL_CUTOFF)
        cfg = {**config,'fit_cutoff_utc':GLOBAL_CUTOFF.isoformat()}
        prior = parent_priors[('FINAL',h)]['p_up'] if full else prior_probability(t,h)
        priors.append({'quarter':'FINAL','horizon':h,'p_up':prior,'train':state_segment(t,h),
                       'is_estimate':bool(len(t)) and not full,'reused_parent_estimate':full})
        try:
            pp = make_preprocessor(t,cfg)
            preprocessor_fits+=1
            bundle = recorded_state_fit(budget,t,h,'M1',cfg,pp,'FINAL',protocol)
            model_metadata.append({'quarter':'FINAL','horizon':h,'model_id':'M1',**bundle['metadata']})
        except FitFailure as exc:
            bundle = constant_state('M1',h,prior,t['label_available_'+h].max().isoformat(),'FINAL_MODEL_FAILURE_B1:'+str(exc))
            failures.append({'quarter':'FINAL','horizon':h,'model_id':'M1','reason':str(exc)})
        bundle['role']='RESEARCH_REPRODUCTION_ONLY'
        if full:
            bundle.update(task_id=FULL_STATE_TASK,public_model_id='M1_FULL',**FULL_STATE_AUTH)
            bundle.pop('BROKER_ACTION_ALLOWED',None)
        bundle['metadata'].update(historical_prior=prior,prior_predictor_id='B1' if len(t) else 'B0')
        final_models[h]=bundle
        joblib.dump(bundle,output/f'final_{public_state_id("M1",config)}_{h}.joblib',compress=3)
    evidence.write_json(output/'model_metadata.json',model_metadata)
    evidence.write_json(output/'prior_estimates.json',priors)
    evidence.write_json(output/'failures.json',failures)
    starts=[e for e in budget.events if e['status']=='STARTED']
    counts={'supervised_total':budget.calls,'base_fits':budget.calls,'calibration_fits':0,'retries':budget.retries,
            'succeeded':sum(e['status']=='FINISHED' for e in budget.events),'failed':sum(e['status']=='FAILED' for e in budget.events),
            'prior_estimates':sum(e['is_estimate'] for e in priors),
            'by_model':pd.Series([e['model_id'] for e in starts]).value_counts().to_dict(),
            'quarterly':sum(e['category']=='quarterly' for e in starts),'final':sum(e['category']=='final' for e in starts),
            'preprocessor_fits':preprocessor_fits,'shared_preprocessor_reuses':preprocessor_reuses,'duplicate_model_fits':0,
            'bootstrap_model_refits':0,'historical_model_replay_fits':0}
    if full:
        counts.update(BM_new_fits=0,BM_models_reused=36,B0_B1_objects_reused=72,B1_estimates_reused=len(priors),
            parent_historical_fits_not_new=111,public_by_model={public_state_id(k,config):v for k,v in counts['by_model'].items()})
    evidence.write_json(output/'fit_counts.json',counts)
    result=evaluate_state(oos,panel,output,failures)
    use_final = result['PRIMARY_H1230_VERDICT']=='EXPLORATORY_SUPPORT' and final_models['H1230'].get('kind')=='learner'
    default = final_models['H1230'] if use_final else constant_state('B0','H1230',.5,None,'H1230_NO_SUPPORT_OR_FINAL_MODEL_UNAVAILABLE')
    default['role']='EXPLORATORY_RESEARCH_CANDIDATE' if default.get('kind')=='learner' else 'NO_MODEL_SIGNAL'
    if full:
        default.update(task_id=FULL_STATE_TASK,public_model_id=public_state_id(default['model_id'],config),**FULL_STATE_AUTH)
        default.pop('BROKER_ACTION_ALLOWED',None)
    joblib.dump(default,output/'default_predictor.joblib',compress=3)
    final_record={h:{k:v for k,v in bundle.items() if k not in ('estimator','preprocessor')} for h,bundle in final_models.items()}
    evidence.write_json(output/'final_models.json',{'research_models':final_record,'default':{k:v for k,v in default.items() if k not in ('estimator','preprocessor')}})
    result.update(EXECUTION_STATUS='COMPLETED',DEFAULT_PREDICTOR_ROLE=default['role'],
                  RESEARCH_MODEL_ROLE='RESEARCH_REPRODUCTION_ONLY',fit_counts=counts,**PROTECTED)
    if full:
        result.pop('BROKER_ACTION_ALLOWED',None)
        result.update(task_id=FULL_STATE_TASK,UNIT_RECOVERY_STATUS='RECOVERED_SOURCE_CONDITIONAL',
            CORE_GAP_STATUS='RECOVERED',CORE_RELATIVE_VOLUME_STATUS='RECOVERED',
            FULL_SIX_INTERACTION_INPUT_STATUS='PASS',FULL_STATE_TEST_STATUS='COMPLETED',
            DATA_SCOPE_AND_LIMITS='Same fixed four historical-qualification stocks and original prediction rows; all six original interactions restored under scoped raw-share-unit certification. Parent 17-stock denominator retained. Exploratory after historical exposures; current historical-action evidence is not complete data-vintage certification.',
            public_model_ids={'M0':'M0_FULL','M1':'M1_FULL'},component_reuse_status=protocol['component_reuse']['status'],**FULL_STATE_AUTH)
    evidence.write_json(output/'result.json',result)
    print(json.dumps(evidence.clean(result),ensure_ascii=False),flush=True)
    return result


def paired_state(daily_by_model):
    matrices=[]
    reference=daily_by_model['M1'].set_index('date').sort_index()
    for model_id in ('M0','B0','B1','BM'):
        comparator=daily_by_model[model_id].set_index('date').sort_index()
        if not reference.index.equals(comparator.index):
            raise ValueError('Comparator trading dates do not align')
        matrices.append(reference.log_loss.to_numpy()-comparator.log_loss.to_numpy())
    deltas=np.column_stack(matrices); n=len(reference)
    if n<20:
        return {},pd.DataFrame()
    rng=np.random.default_rng(104729)
    starts=rng.integers(0,n-20+1,size=(10000,int(np.ceil(n/20))))
    indices=(starts[:,:,None]+np.arange(20)).reshape(10000,-1)[:,:n]
    results={}
    for i,name in enumerate(('M0','B0','B1','BM')):
        samples=deltas[indices,i].mean(axis=1)
        q=np.quantile(samples,[.025,.975,.05/6,1-.05/6])
        results['M1-'+name]={'delta_log_loss':float(deltas[:,i].mean()),'ci95_low':float(q[0]),'ci95_high':float(q[1]),
                            'ci_adjusted_low':float(q[2]),'ci_adjusted_high':float(q[3]),'dates':n,
                            'years':reference.index.str[:4].nunique(),'draw_identity':hashlib.sha256(starts.tobytes()).hexdigest()}
    frame=pd.DataFrame(deltas,columns=list(results)); frame.insert(0,'date',reference.index)
    return results,frame


def evaluate_state(oos,panel,output,failures):
    totals,comparisons,verdicts,groups,reliability,dailies,deltas,common_stats={},{},{},[],[],[],[],[]
    common_ids=set(panel.loc[panel[['y_'+h for h in HORIZONS]].notna().all(axis=1),'sample_id'])
    for h in HORIZONS:
        by_model={}
        population=None
        for model_id,rows in oos[oos.horizon==h].groupby('model_id'):
            labelled_ids=set(rows.loc[rows.y.notna(),'sample_id'])
            if population is not None and labelled_ids!=population:
                raise ValueError('Models do not share evaluable stock-day rows')
            population=labelled_ids
            stats,daily=state_metrics(rows)
            totals[h+'_'+model_id]=stats; by_model[model_id]=daily
            dailies.append(daily.assign(horizon=h,model_id=model_id))
            reliability.extend({'horizon':h,'model_id':model_id,**r} for r in state_reliability(rows))
            for dimension in ('ticker','year','quarter'):
                work=rows.assign(year=rows.date.str[:4])
                for value,part in work.groupby(dimension):
                    stat,_=state_metrics(part)
                    groups.append({'horizon':h,'model_id':model_id,'dimension':dimension,'value':value,**stat})
            stat,_=state_metrics(rows[rows.sample_id.isin(common_ids)])
            common_stats.append({'horizon':h,'model_id':model_id,**stat})
        comparison,delta=paired_state(by_model)
        comparisons[h]=comparison; deltas.append(delta.assign(horizon=h))
        sufficient=totals[h+'_M1'].get('dates',0)>=250 and totals[h+'_M1'].get('years',0)>=3 and len(comparison)==4
        h_failures=[f for f in failures if f['horizon']==h and f['quarter']!='FINAL']
        if not sufficient or h_failures:
            verdict='INSUFFICIENT_EVIDENCE'
        elif all(c['ci_adjusted_high']<0 for c in comparison.values()):
            verdict='EXPLORATORY_SUPPORT'
        else:
            verdict='NO_RELIABLE_ADVANTAGE'
        verdicts[h]=verdict
    pd.concat(dailies,ignore_index=True).to_parquet(output/'daily_metrics.parquet',index=False)
    pd.concat(deltas,ignore_index=True).to_parquet(output/'paired_daily_deltas.parquet',index=False)
    for name,value in [('metrics',totals),('comparisons',comparisons),('grouped_metrics',groups),('reliability',reliability),('common_sample_metrics',common_stats)]:
        evidence.write_json(output/(name+'.json'),value)
    state_description(oos,panel,output)
    interactions={h:('INSUFFICIENT_EVIDENCE' if verdicts[h]=='INSUFFICIENT_EVIDENCE' else
                      'RELATIVE_SUPPORT' if c.get('M1-M0',{}).get('ci_adjusted_high',1)<0 else 'NOT_SUPPORTED') for h,c in comparisons.items()}
    coverage=[{'horizon':h,'prediction_rows':len(x),'prediction_dates':x.date.nunique(),'labelled_rows':int(x.y.notna().sum()),
               'unlabelled_rows':int(x.y.isna().sum()),'fallback_rows':int(x.fallback_reason.notna().sum())}
              for h in HORIZONS for x in [oos[(oos.horizon==h)&(oos.model_id=='M1')]]]
    return {'PRIMARY_H1230_VERDICT':verdicts['H1230'],'H15_VERDICT':verdicts['H15'],'H60_VERDICT':verdicts['H60'],
            'STATE_INTERACTION_VERDICT':interactions,'coverage':coverage,'unique_stock_days':oos.sample_id.nunique(),
            'unique_trading_days':oos.date.nunique(),'quarters':12,'related_labels_are_not_independent_samples':True,
            'DATA_SCOPE_AND_LIMITS':'Fixed four historical-qualification stocks; parent 17-stock denominator retained; unit-uncertified gap/relative-volume dependent fields isolated; only two of six numerical interactions certified',
            'short_horizon_role':'SHORT_HORIZON_EXPLORATORY' if any(verdicts[h]=='EXPLORATORY_SUPPORT' for h in ('H15','H60')) else 'NO_SHORT_HORIZON_SUPPORT'}


def state_description(oos,panel,output):
    meta=panel[['sample_id','g','o','v']].copy()
    missing_gap=~np.isfinite(meta.g)|~np.isfinite(meta.o)
    meta['gap_opening_group']=np.select([missing_gap,meta.g.eq(0)|meta.o.eq(0),np.sign(meta.g).eq(np.sign(meta.o))],
                                       ['MISSING','ZERO_CHANGE','SAME_DIRECTION'],default='OPPOSITE_DIRECTION')
    meta['volume_group']=np.select([~np.isfinite(meta.v),meta.v.gt(0)],['MISSING','ABOVE_HISTORY'],default='NOT_ABOVE_HISTORY')
    descriptions=[]
    for h in HORIZONS:
        x=oos[(oos.horizon==h)&(oos.model_id=='M1')].merge(meta,on='sample_id',validate='one_to_one')
        x['continuation']=np.where(x.r.notna() & x.o.notna() & x.r.ne(0) & x.o.ne(0),(np.sign(x.r)==np.sign(x.o)).astype(float),np.nan)
        for dimension in ('gap_opening_group','volume_group'):
            for value,part in x.groupby(dimension):
                stat,_=state_metrics(part)
                descriptions.append({'horizon':h,'dimension':dimension,'value':value,'prediction_rows':len(part),
                                     'distinct_dates':part.date.nunique(),'evaluable_rows':int(part.y.notna().sum()),
                                     'mean_return':float(part.groupby('date').r.mean().mean()),
                                     'continuation_fraction':float(part.groupby('date').continuation.mean().mean()),
                                     'continuation_defined_rows':int(part.continuation.notna().sum()),
                                     'excluded_zero_opening_rows':int(part.o.eq(0).sum()),'future_flat_rows':int(part.r.eq(0).sum()),**stat})
    path=panel[['sample_id','ticker','date','price_start',*['price_end_'+h for h in HORIZONS]]].copy()
    path=path[path[['price_start',*['price_end_'+h for h in HORIZONS]]].notna().all(axis=1)]
    path['log_0946_1001']=np.log(path.price_end_H15/path.price_start)
    path['log_1001_1046']=np.log(path.price_end_H60/path.price_end_H15)
    path['log_1046_1230']=np.log(path.price_end_H1230/path.price_end_H60)
    residual=path[['log_0946_1001','log_1001_1046','log_1046_1230']].sum(axis=1)-np.log(path.price_end_H1230/path.price_start)
    if len(residual) and residual.abs().max()>1e-12:
        raise ValueError('Log-return path identity failed')
    path=path.merge(oos[oos.model_id=='M1'].pivot(index='sample_id',columns='horizon',values='p_up').add_prefix('score_0945_'),on='sample_id',how='inner')
    path.to_parquet(output/'path_decomposition.parquet',index=False)
    path_stats=[]
    for score in [c for c in path if c.startswith('score_')]:
        for leg in ('log_0946_1001','log_1001_1046','log_1046_1230'):
            path_stats.append({'score':score,'future_leg':leg,'rows':len(path),'dates':path.date.nunique(),
                               'mean_log_return_daily':float(path.groupby('date')[leg].mean().mean()),
                               'descriptive_correlation':float(path[score].corr(path[leg]))})
    evidence.write_json(output/'state_and_path_diagnostics.json',{'fixed_groups':descriptions,'path':path_stats,
                        'log_additivity_max_error':float(residual.abs().max()),
                        'later_leg_scores':'All scores issued at 09:45; no later input or model update; no half-life or causal claim'})


def predict_state_offline(bundle,frame,horizon='H1230'):
    if bundle.get('task_id') not in (STATE_TASK,FULL_STATE_TASK) or bundle.get('horizon')!=horizon:
        raise ValueError('Wrong task/horizon predictor; default horizon is H1230')
    for col,clock in [('prediction_at_utc','09:45'),('feature_cutoff_utc','09:44'),('label_start_utc','09:46')]:
        t=pd.to_datetime(frame[col],utc=True).dt.tz_convert('America/New_York')
        if not t.dt.strftime('%H:%M').eq(clock).all() or not t.dt.strftime('%Y-%m-%d').eq(frame.date).all():
            raise ValueError('Inference clock mismatch')
    if not frame.ticker.isin(['NVDA','AMD','AVGO','ENPH']).all():
        raise ValueError('No automatic stock-universe expansion')
    if bundle.get('kind')=='constant':
        p=np.full(len(frame),bundle['p_up']); reason=np.full(len(frame),bundle.get('fallback_reason'),dtype=object)
    else:
        try:
            p=predict_state(bundle,frame)['p_up']
            prediction_error=None
        except (FitFailure, ValueError, FloatingPointError) as exc:
            p=np.full(len(frame),bundle['metadata']['historical_prior'])
            prediction_error=f'PREDICTION_FAILURE_PRIOR:{type(exc).__name__}:{exc}'
        missing=~np.isfinite(frame.o.to_numpy(float))
        p=np.asarray(p).copy(); p[missing]=bundle['metadata']['historical_prior']
        reason=np.where(missing,'NECESSARY_INPUT_MISSING_PRIOR',None)
        if prediction_error:
            reason[:]=prediction_error
    out=frame[['security_uid','ticker','date','prediction_at_utc','feature_cutoff_utc','label_start_utc']].copy()
    out=out.rename(columns={'date':'decision_date','prediction_at_utc':'prediction_timestamp','feature_cutoff_utc':'input_cutoff','label_start_utc':'target_start'})
    out['target_end']=pd.to_datetime(frame.date+' '+HORIZONS[horizon][0]).dt.tz_localize('America/New_York').dt.tz_convert('UTC')
    out['horizon'],out['p_up'],out['p_not_up']=horizon,p,1-p
    out['model_id'],out['model_role']=bundle.get('public_model_id',bundle['model_id']),bundle.get('role','RESEARCH_REPRODUCTION_ONLY')
    out['train_cutoff']=bundle['metadata'].get('max_label_available_at')
    default_quality=('SOURCE_BOUND_SHARE_UNITS;LOCAL_FIELD_MISSINGNESS_RETAINED'
                     if bundle.get('task_id')==FULL_STATE_TASK else 'SOURCE_BOUND_FEATURES;UNIT_FIELDS_ISOLATED')
    out['data_quality']=frame.get('data_quality',default_quality)
    out['fallback_reason']=reason
    # No bullish mechanical class is displayed for the 50% no-signal fallback.
    out['predicted_up']=pd.Series(pd.NA,index=out.index,dtype='Int64') if bundle.get('kind')=='constant' else (p>=.5).astype(int)
    for key,value in (FULL_STATE_AUTH if bundle.get('task_id')==FULL_STATE_TASK else PROTECTED).items():
        out[key]=value
    return out
