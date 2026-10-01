"""Thin V24 continuous-account runner; no fitting or independent accounting.

Only explicit frozen candidates run. The sole PIT input adapter owns source
identity; the immutable common account engine owns fills, units, corporate share
transitions and persistent state. No test-year or other-task economic reader.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from scripts.research.a2.training.stateful_inputs import InputReader, FEATURES, LABEL, BOUNDARY
from scripts.research.a2.training.stateful_account import StatefulOverlay
from scripts.research.a2.evaluation.continuous_research_account import run_continuous_account
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays
from scripts.storage.storage_r2a import assert_write_path, write_json_atomic

REPO=Path(__file__).resolve().parents[4]
PARENT=Path('D:/us-tech-quant-results/A2_STATEFUL_ACTION_AND_CASH_PRE2026_TEST2026_R1')
REFERENCE=PARENT/'ACCOUNT_REPLAY_R1.py'
REFERENCE_SHA='d965dbb67af5be000a0aa90f335f68ccbf6b83647ea918f98018790a3a9c421c'
SOURCE_PATHS={'module_sha256':Path(__file__),
 'policy_sha256':REPO/'scripts/research/a2/training/stateful_account.py',
 'values_module_sha256':REPO/'scripts/research/a2/training/stateful_values.py',
 'engine_sha256':REPO/'scripts/research/a2/evaluation/continuous_research_account.py',
 'fast_account_sha256':REPO/'scripts/research/a2/retained/a2_pto_full_compat_20260928_r2/fast_account.py',
 'reference_replay_sha256':REFERENCE,'parent_binding_sha256':PARENT/'INPUT_BINDING_R1.json',
 'account_config_sha256':PARENT/'R1_ACCOUNT_CONFIG.json'}
MAX_PATHS=220
_VERIFIED_RECORDS={}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def _json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _pin(path,pin):
    if not isinstance(pin,str) or len(pin)!=64 or sha(path)!=pin:
        raise ValueError('FROZEN_REPLAY_PIN_CHANGED:'+str(path))


def _old():
    _pin(REFERENCE,REFERENCE_SHA)
    name='_stateful_v24_reference_replay_functions'
    if name not in sys.modules:
        spec=importlib.util.spec_from_file_location(name,REFERENCE)
        module=importlib.util.module_from_spec(spec);sys.modules[name]=module
        saved=list(sys.path)
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path[:]=saved
    return sys.modules[name]


def frozen_contract(run_dir):
    run=Path(run_dir).resolve();assert_write_path(run/'ledgers/stateful','backtest')
    config=_json(run/'run_config.json');auth=config.get('stateful_replay',{})
    if config.get('phase')!='FROZEN' or auth.get('status')!='FROZEN':
        raise ValueError('STATEFUL_REPLAY_ROOT_FREEZE_REQUIRED')
    if config.get('strategy_version')!='V24' or config.get('training_cutoff_exclusive')!='2026-01-01' or config.get('evaluation_years')!=[2023,2024,2025] or config.get('capital_usd')!=3000.:
        raise ValueError('STATEFUL_REPLAY_IDENTITY_OR_PRE2026_BOUNDARY')
    for key,path in SOURCE_PATHS.items():_pin(path,auth.get(key))
    _pin(run/'input_manifest.json',auth.get('input_manifest_sha256'))
    manifest=_json(run/'input_manifest.json')
    _pin(REPO/'scripts/research/a2/training/stateful_inputs.py',manifest.get('source_reader_sha256'))
    if not manifest.get('inputs_verified') or manifest.get('training_cutoff_exclusive')!='2026-01-01':
        raise ValueError('UNVERIFIED_PIT_INPUT_MANIFEST')
    if auth.get('max_account_paths')!=MAX_PATHS or config.get('prior_account_paths')!=4:
        raise ValueError('ACCOUNT_PATH_BUDGET_OR_PRIOR_COUNT_CHANGED')
    if 'candidates_path' in auth:
        p=Path(auth['candidates_path']).resolve()
        if not p.is_relative_to(run):raise ValueError('CANDIDATE_LIST_OUTSIDE_OWN_RUN')
        _pin(p,auth.get('candidates_sha256'));candidates=_json(p)
    else:
        candidates=config.get('stateful_candidates')
        pin=hashlib.sha256(json.dumps(candidates,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        if pin!=auth.get('candidates_sha256'):raise ValueError('EXPLICIT_CANDIDATE_LIST_HASH_CHANGED')
    if not isinstance(candidates,list) or not candidates:raise ValueError('EXPLICIT_CANDIDATES_REQUIRED')
    ids=set();tuples=set()
    for c in candidates:
        required={'candidate_id','source_method_ids','action','value_model','control','gross','risk','target_role','scientific_tuple_sha256'}
        if not required.issubset(c) or c['candidate_id'] in ids or c['scientific_tuple_sha256'] in tuples:
            raise ValueError('CANDIDATE_SCHEMA_OR_DUPLICATE_CANONICAL_TUPLE')
        if not str(c['candidate_id']).replace('_','').replace('-','').isalnum() or len(c['scientific_tuple_sha256'])!=64:
            raise ValueError('UNSAFE_CANDIDATE_ID_OR_TUPLE')
        if c.get('forecast','none') not in ('none','return_shrink','black_litterman'):raise ValueError('UNREGISTERED_FORECAST_COORDINATE')
        if c['action'] not in ('raw','stateful') or c['target_role']!='shareholder5d' or c['control'] not in ('none','no_trade_band','hysteresis','partial_rebalancing','minimum_trade_usd') or c['gross'] not in ('fixed','volatility_targeting','risk_constrained_cash','dynamic'):
            raise ValueError('UNREGISTERED_STATEFUL_CANDIDATE_COMPONENT')
        ids.add(c['candidate_id']);tuples.add(c['scientific_tuple_sha256'])
    return run,config,auth,candidates


def _verify_record(record):
    """Large immutable files hash once, then exact stat identity on every reuse."""
    p=Path(record['path']).resolve();stat=p.stat();fingerprint=(stat.st_size,stat.st_mtime_ns)
    key=(str(p),record['sha256']);previous=_VERIFIED_RECORDS.get(key)
    if previous is not None and previous!=fingerprint:raise ValueError('FORECAST_CHANGED_AFTER_HASH_GUARD')
    if previous is None:
        _pin(p,record['sha256']);_VERIFIED_RECORDS[key]=fingerprint
    return p,fingerprint


def _read_projection(record,columns,date_column,filters=()):
    p,fingerprint=_verify_record(record)
    pf=pq.ParquetFile(p);names=pf.schema_arrow.names
    if not set(columns).issubset(names):raise ValueError('FORECAST_SCHEMA_MISSING')
    for i in range(pf.num_row_groups):
        s=pf.metadata.row_group(i).column(names.index(date_column)).statistics
        if not s or not s.has_min_max or pd.Timestamp(s.max)>=BOUNDARY:raise ValueError('FORECAST_NOT_PHYSICALLY_PRE2026')
    out=pd.read_parquet(p,columns=columns,filters=list(filters));out[date_column]=pd.to_datetime(out[date_column])
    after=p.stat()
    if (after.st_size,after.st_mtime_ns)!=fingerprint:raise ValueError('FORECAST_CHANGED_DURING_PROJECTED_READ')
    return out


def _packet_key_guard(expected,meta,flag,allow_unavailable=False):
    check=expected.merge(meta,on=['signal_date','ticker'],how='outer',validate='one_to_one',indicator=True)
    actual_flag=flag+'_y' if flag=='feature_available' else flag
    source_flag='feature_available_x' if flag=='feature_available' else 'feature_available'
    if not check['_merge'].eq('both').all() or check[actual_flag].isna().any():
        raise ValueError('FORECAST_DROPPED_OR_ADDED_ORIGINAL_KEYS')
    if not check[actual_flag].isin([True,False]).all():raise ValueError('INVALID_FORECAST_QUALIFICATION_FLAG')
    if allow_unavailable:
        if (check[actual_flag]&~check[source_flag]).any():raise ValueError('FORECAST_SOURCE_FLAG_NOT_BOUND')
    elif not check[source_flag].eq(check[actual_flag]).all():raise ValueError('FORECAST_SOURCE_FLAG_NOT_BOUND')


def _common_sigma(values,expected):
    if expected is None or not np.isfinite(expected) or expected<=0 or not np.allclose(values,float(expected),rtol=0,atol=0):
        raise ValueError('COMMON_FOLD_RESIDUAL_SIGMA_REQUIRED_NO_DAILY_WIDTH_COLLAPSE')
    return float(expected)


def read_risk_packets(auth,reader,candidates,dates,vol,run_dir):
    methods={c['risk'] for c in candidates if c['risk'] not in ('diag','diag20_reference')}
    if not methods:return None,[]
    path=REPO/'scripts/research/a2/risk/joint_risk_estimators.py'
    _pin(path,auth.get('risk_module_sha256'))
    if auth.get('risk_static_window_sessions')!=63 or auth.get('risk_horizon_conversion')!='IID_1D_COVARIANCE_TIMES_5' or not isinstance(auth.get('risk_return_unit'),str) or auth.get('risk_return_unit')=='CALLER_UNSPECIFIED':
        raise ValueError('ANNUAL_STATIC63_RISK_AND_IID_HORIZON_NOT_FROZEN')
    from scripts.research.a2.risk.joint_risk_estimators import canonical_method,risk_matrix
    bundles={};pins=[];metadata=[]
    for method in methods:
        canonical=canonical_method(method)
        for year in (2023,2024,2025):
            record=auth['risk_packets'][method]['annual'][str(year)]
            for item in ('bundle','receipt'):
                p=Path(record[item]['path']).resolve()
                if not p.is_relative_to(run_dir):raise ValueError('RISK_PACKET_NOT_OWN_RUN_SOURCE')
                _pin(p,record[item]['sha256'])
            receipt=_json(record['receipt']['path'])
            if receipt.get('status') not in ('FITTED','TRAINED') or receipt.get('scientific_feature_pit_qualified') is not True:
                raise ValueError('UNQUALIFIED_ANNUAL_RISK_RECEIPT')
            bundle=joblib.load(record['bundle']['path']);cut=pd.Timestamp(f'{year}-01-01')
            window=reader.calendar[reader.calendar<cut][-63:]
            if bundle.status!='FITTED' or bundle.method_id!=canonical or not pd.DatetimeIndex(bundle.fitted_dates).equals(window):
                raise ValueError('RISK_BUNDLE_NOT_EXACT_ANNUAL_STATIC63')
            if pd.Timestamp(bundle.specification.get('fit_cutoff'))!=cut or bundle.fitted_state.get('return_horizon_sessions')!=1 or bundle.fitted_state.get('return_unit')!=auth.get('risk_return_unit'):
                raise ValueError('RISK_RETURN_UNIT_OR_CLOCK_NOT_FROZEN')
            history=reader.pred_flags.loc[reader.pred_flags.signal_date.lt(cut)&reader.pred_flags.feature_available,'ticker'].astype(str)
            if not set(bundle.assets).issubset(set(history)):raise ValueError('RISK_ASSETS_BACKFILLED_FROM_FUTURE_MEMBERSHIP')
            bundles[(method,year)]=bundle;pins.append(record)
    def provider(di,selected,tickers,method):
        if method in ('diag','diag20_reference'):
            return np.diag(vol[di,selected]**2)
        year=dates[di].year
        matrix,details=risk_matrix(bundles[(method,year)],np.asarray(tickers)[selected],return_metadata=True)
        metadata.append({'signal_date':dates[di],'risk_method':method,'fit_year':year,
            'unknown_assets':json.dumps(details['unknown_assets']),'fallback_variance':details['fallback_variance'],
            'strategy_eligibility_upgraded':details['strategy_eligibility_upgraded'],
            'risk_clock':'ANNUAL_STATIC_LAST63_PREJAN1; NO_DAILY_FIT',
            'return_unit':details['return_unit'],'return_horizon_sessions_input':1,
            'return_horizon_sessions_output':5,'horizon_conversion':'IID_1D_COVARIANCE_TIMES_5'})
        return matrix*5.
    return provider,metadata


def _fusion_receipt_guard(receipt,record,auth,reader,year):
    """Pin fusion and past expert publications before forecast numeric projection."""
    if not isinstance(auth,dict):raise ValueError('FROZEN_FUSION_AUTH_REQUIRED')
    paths={'module_sha256':REPO/'scripts/research/a2/training/stateful_fusion.py',
        'native_source_sha256':REPO/'scripts/research/a2/retained/a2_predict_then_optimize_20260928_r1/fusion_models.py',
        'native_common_sha256':REPO/'scripts/research/a2/retained/a2_predict_then_optimize_20260928_r1/common.py',
        'value_module_sha256':SOURCE_PATHS['values_module_sha256'],
        'input_reader_sha256':REPO/'scripts/research/a2/training/stateful_inputs.py',
        'input_manifest_sha256':reader.run/'input_manifest.json'}
    _pin(paths['module_sha256'],auth.get('fusion_module_sha256'))
    pins={key:sha(path) for key,path in paths.items()}
    reuse=receipt['reuse_tuple']
    if reuse.get('source_pins')!=pins:raise ValueError('FUSION_SOURCE_RECEIPT_NOT_CURRENT_FROZEN_CLOSURE')
    if reuse.get('feature_binding_role')!='UNDERLYING_SOURCE32_NOT_FUSION_ESTIMATOR_INPUTS':raise ValueError('FUSION_UNDERLYING32_ROLE_NOT_DECLARED')
    packet=reuse.get('packet',[])
    if len(packet)!=3 or set(packet)!={'ridge','hgb','lgb'}:raise ValueError('FUSION_THREE_EXPERT_INPUTS_NOT_FROZEN')
    model_id=receipt.get('model_id','')
    state=['state_mean_ret20d','state_mean_realized_vol20d','state_breadth_price_vs_ma20_positive','state_expert_disagreement'] if model_id.startswith(('gate_','residual_')) else []
    if reuse.get('model_input_columns')!=['expert_'+m for m in packet]+state:raise ValueError('FUSION_ESTIMATOR_INPUTS_NOT_EXPLICIT')
    publication_record=record.get('prediction_receipt')
    if not publication_record:raise ValueError('FUSION_PREDICTION_PUBLICATION_PIN_REQUIRED')
    publication_path=Path(publication_record['path']).resolve()
    if publication_path!=Path(record['prediction']['path']).resolve().with_suffix('.receipt.json') or not publication_path.is_relative_to(reader.run):raise ValueError('FUSION_PUBLICATION_NOT_CANONICAL_OWN_RUN')
    _pin(publication_path,publication_record['sha256']);publication=_json(publication_path)
    expected={'status':'PUBLISHED','prediction_role':'MODEL_OOF','sha256':record['prediction']['sha256'],
        'model_sha256':receipt['model_sha256'],'reuse_tuple_sha256':receipt['reuse_tuple_sha256'],
        'fit_receipt_sha256':record['receipt']['sha256'],'producer_source_sha256':pins['module_sha256'],
        'input_manifest_sha256':pins['input_manifest_sha256'],'year':year,'model_id':model_id,'test_2026_rows_read':0}
    if any(publication.get(k)!=v for k,v in expected.items()) or Path(publication.get('path','')).resolve()!=Path(record['prediction']['path']).resolve() or Path(publication.get('fit_receipt_path','')).resolve()!=Path(record['receipt']['path']).resolve():raise ValueError('UNQUALIFIED_FUSION_MODEL_OOF_PUBLICATION')
    experts=reuse.get('expert_oof_pins',[]);seen=set()
    if not experts:raise ValueError('FUSION_PAST_MODEL_OOF_PINS_REQUIRED')
    for expert in experts:
        ey=expert.get('year');em=expert.get('model_id')
        if type(ey) is not int or ey not in range(2021,year) or em not in ('ridge','hgb','lgb') or (ey,em) in seen:raise ValueError('FUSION_META_USED_CURRENT_OR_FUTURE_EXPERT_YEAR')
        seen.add((ey,em))
        ep=Path(expert['path']).resolve();er=Path(expert['receipt_path']).resolve();mp=Path(expert['model_path']).resolve()
        if any(not path.is_relative_to(reader.run) for path in (ep,er,mp)):raise ValueError('FUSION_EXPERT_OUTSIDE_OWN_RUN')
        for path,key in ((ep,'sha256'),(er,'receipt_sha256'),(mp,'model_sha256')):_verify_record({'path':str(path),'sha256':expert[key]})
        epp=ep.with_suffix('.receipt.json');_pin(epp,expert['prediction_receipt_sha256'])
        pub=_json(epp);fit=_json(er);tup=fit.get('reuse_tuple',{})
        if pub.get('status')!='PUBLISHED' or pub.get('sha256')!=expert['sha256'] or pub.get('fit_receipt_sha256')!=expert['receipt_sha256'] or pub.get('model_sha256')!=expert['model_sha256'] or pub.get('year')!=ey or pub.get('model_id')!=em or pub.get('test_2026_rows_read')!=0 or pub.get('producer_source_sha256')!=pins['value_module_sha256'] or pub.get('input_manifest_sha256')!=pins['input_manifest_sha256'] or pub.get('reuse_tuple_sha256')!=fit.get('reuse_tuple_sha256'):raise ValueError('UNQUALIFIED_FUSION_EXPERT_PUBLICATION')
        if fit.get('status') not in ('TRAINED','EXACT_REUSED') or fit.get('scientific_target_qualified') is not True or fit.get('scientific_feature_pit_qualified') is not True or fit.get('model_sha256')!=expert['model_sha256'] or fit.get('year')!=ey or fit.get('model_id')!=em or tup.get('label_definition')!=LABEL or pd.Timestamp(tup.get('cutoff_exclusive'))!=pd.Timestamp(f'{ey}-01-01'):raise ValueError('FUSION_EXPERT_NOT_ANNUAL_PAST_MODEL_OOF')
        expected_producer={'module_sha256':pins['value_module_sha256'],'input_reader_sha256':pins['input_reader_sha256'],'input_manifest_sha256':pins['input_manifest_sha256'],'native_source_sha256':sha(REPO/'scripts/research/a2/retained/a2_predict_then_optimize_20260928_r1/models_native.py')}
        if any(tup.get('source_pins',{}).get(k)!=v for k,v in expected_producer.items()):raise ValueError('FUSION_EXPERT_PRODUCER_CLOSURE_CHANGED')
        trainmax=pd.Timestamp(fit.get('train_label_maturity_max'));calmax=pd.Timestamp(fit.get('calibration_label_maturity_max'));traincut=pd.Timestamp(tup.get('training_signal_and_label_maturity_exclusive'))
        if pd.isna(trainmax) or pd.isna(calmax) or pd.isna(traincut) or trainmax>=traincut or calmax>=pd.Timestamp(f'{ey}-01-01'):raise ValueError('FUSION_EXPERT_LABEL_MATURITY_NOT_PAST')
    if seen!={(ey,em) for ey in range(2021,year) for em in ('ridge','hgb','lgb')}:raise ValueError('FUSION_PAST_THREE_EXPERT_YEAR_GRID_INCOMPLETE')


def read_packet(spec,reader,dates,tickers,auth=None):
    old=_old();mu=np.full((len(dates),len(tickers)),np.nan);sigma=np.full(len(dates),np.nan)
    lineage=np.full(len(dates),'',dtype=object);receipts=[]
    if spec.get('source_kind') not in ('V24_VALUE_OUTPUTS','V24_FUSION_OUTPUTS','FROZEN_R1_OOF'):
        raise ValueError('UNREGISTERED_VALUE_PACKET_SOURCE')
    records=spec.get('annual',{})
    for year in (2023,2024,2025):
        r=records[str(year)];receipt_path=Path(r['receipt']['path']);_pin(receipt_path,r['receipt']['sha256']);receipt=_json(receipt_path)
        if receipt.get('status') not in ('TRAINED','EXACT_REUSED') or not receipt.get('scientific_target_qualified') or not receipt.get('scientific_feature_pit_qualified'):
            raise ValueError('UNQUALIFIED_VALUE_MODEL_RECEIPT')
        reuse=receipt.get('reuse_tuple',receipt.get('model_reuse_tuple',{}))
        fold=reader.annual_fold(year)
        if reuse.get('fold')!=f'ANNUAL_{year}' or reuse.get('calendar_sha256')!=fold['calendar_sha256'] or pd.DatetimeIndex(reuse.get('calibration_sessions',[])).equals(fold['calibration_sessions']) is False:
            raise ValueError('MODEL_FOLD_CALENDAR_OR_HELD60_NOT_EXACT')
        if pd.Timestamp(reuse['training_signal_and_label_maturity_exclusive'])!=fold['calibration_start'] or pd.Timestamp(reuse['cutoff_exclusive'])!=fold['cutoff_exclusive']:
            raise ValueError('MODEL_TRAIN_CALIBRATION_BOUNDARIES_NOT_EXACT')
        if 'calibration_label_maturity_max' in receipt and pd.Timestamp(receipt['calibration_label_maturity_max'])>=fold['cutoff_exclusive']:
            raise ValueError('UNMATURED_HELDOUT_CALIBRATION_RECEIPT')
        if reuse.get('label_definition')!=LABEL or tuple(reuse.get('feature_binding',{}).get('features',()))!=FEATURES:
            raise ValueError('MODEL_TARGET_OR_ORDERED_FEATURES_NOT_FROZEN')
        if pd.Timestamp(reuse['calibration_label_maturity_exclusive'])!=pd.Timestamp(f'{year}-01-01'):
            raise ValueError('MODEL_CALIBRATION_CLOCK_MISMATCH')
        if 'train_label_maturity_max' in receipt and pd.Timestamp(receipt['train_label_maturity_max'])>=pd.Timestamp(reuse['training_signal_and_label_maturity_exclusive']):
            raise ValueError('MODEL_TRAIN_LABEL_CLOCK_MISMATCH')
        model_path=Path(receipt['model_path']);_pin(model_path,receipt['model_sha256'])
        is_r1=spec['source_kind']=='FROZEN_R1_OOF';is_fusion=spec['source_kind']=='V24_FUSION_OUTPUTS'
        if is_r1:
            _pin(PARENT/'TRAINING_BACKEND.py',reuse['backend_source_sha256'])
        elif is_fusion:
            _fusion_receipt_guard(receipt,r,auth,reader,year)
        elif reuse.get('source_pins',{}).get('module_sha256')!=sha(SOURCE_PATHS['values_module_sha256']) or reuse.get('source_pins',{}).get('input_manifest_sha256')!=sha(reader.run/'input_manifest.json'):
            raise ValueError('VALUE_MODEL_SOURCE_RECEIPT_NOT_CURRENT_FROZEN_SOURCE')
        if receipt.get('repair_transport_sha256') or reuse.get('source_pins',{}).get('repair_transport_sha256'):
            transport=receipt.get('repair_transport_sha256') or reuse['source_pins']['repair_transport_sha256']
            if not isinstance(auth,dict) or auth.get('value_repair_transport_sha256')!=transport:raise ValueError('EBM_REPAIR_TRANSPORT_NOT_FROZEN')
            _pin(REPO/'scripts/research/a2/training/stateful_value_repair.py',transport)
        flag='feature_available' if is_r1 else 'prediction_qualified'
        tuplecol='model_reuse_tuple_sha256'
        columns=['signal_date','ticker',flag,'model_sha256',tuplecol]
        start=pd.Timestamp(f'{year}-01-01');end=pd.Timestamp(f'{year+1}-01-01')
        filters=[('signal_date','>=',start),('signal_date','<',end)]
        meta=_read_projection(r['prediction'],columns,'signal_date',filters)
        expected=reader.pred_flags.loc[reader.pred_flags.signal_date.ge(start)&reader.pred_flags.signal_date.lt(end),['signal_date','ticker','feature_available']]
        _packet_key_guard(expected,meta,flag,allow_unavailable=is_fusion)
        tuple_sha=receipt.get('reuse_tuple_sha256',receipt.get('model_reuse_tuple_sha256'))
        if not meta.model_sha256.eq(receipt['model_sha256']).all() or not meta[tuplecol].eq(tuple_sha).all():raise ValueError('FORECAST_MODEL_LINEAGE_CHANGED')
        vectorcols=['signal_date','ticker','prediction','value_sigma',*r.get('native_diagnostic_columns',[])]
        if any(c in ('y_open5','label','return','target') for c in vectorcols):raise ValueError('LABEL_IN_POLICY_PACKET')
        vectors=_read_projection(r['prediction'],vectorcols,'signal_date',filters+[(flag,'==',True)])
        lawful=meta.loc[meta[flag],['signal_date','ticker']]
        if len(vectors)!=len(lawful) or not pd.MultiIndex.from_frame(vectors[['signal_date','ticker']]).sort_values().equals(pd.MultiIndex.from_frame(lawful).sort_values()):raise ValueError('LEGAL_FORECAST_KEYS_INCOMPLETE')
        if not np.isfinite(vectors[['prediction','value_sigma']].to_numpy(float)).all() or (vectors.value_sigma<=0).any():raise ValueError('NONFINITE_LEGAL_FORECAST')
        joint=receipt.get('calibration',{}).get('sigma',receipt.get('sigma'))
        _common_sigma(vectors.value_sigma,joint)
        rows=old.values(vectors,dates,tickers,'prediction');mask=np.isfinite(rows);mu[mask]=rows[mask]
        active=dates.year==year;sigma[active]=float(joint);lineage[active]=f'ANNUAL_{year}|{receipt["model_sha256"]}|{tuple_sha}'
        receipts.append({'year':year,'receipt':r['receipt'],'prediction':r['prediction'],'model_sha256':receipt['model_sha256'],'native_diagnostic_columns':r.get('native_diagnostic_columns',[]),'source_kind':spec['source_kind'],'prediction_receipt':r.get('prediction_receipt')})
    return {'mu':mu,'sigma':sigma,'lineage':lineage,'source_receipts':receipts}


def read_market(reader):
    old=_old();dates=reader.calendar[reader.calendar>=pd.Timestamp('2023-01-01')]
    if len(dates)!=752 or dates[-1]!=pd.Timestamp('2025-12-31') or dates[0]!=pd.Timestamp('2023-01-03'):
        raise ValueError('FULL_ORIGINAL_752_SESSION_GRID_REQUIRED')
    flags=reader.pred_flags.loc[reader.pred_flags.signal_date.isin(dates)].copy()
    bars=reader._vectors('raw_market_prices',['ticker','trade_date','code','open','close'],
                         [('trade_date','>=',dates[0]),('trade_date','<',BOUNDARY)]).rename(columns={'trade_date':'signal_date'})
    bars['signal_date']=pd.to_datetime(bars.signal_date)
    tickers=sorted(set(flags.ticker.astype(str))|set(bars.ticker.astype(str)))
    top=old.values(flags,dates,tickers,'is_raw_top20',False,bool)
    qualified=old.values(flags,dates,tickers,'is_max_group',False,bool)
    union=old.values(flags,dates,tickers,'decision_information_present_union',False,bool)
    stock=old.values(flags,dates,tickers,'stock_forecast_input_present',False,bool)
    raw=old.values(flags,dates,tickers,'raw_selector_input_present',False,bool)
    buy=old.values(flags,dates,tickers,'new_buy_eligible',False,bool)
    if not np.array_equal(union,stock|raw) or not np.array_equal(buy,top&qualified) or not np.isin(top.sum(axis=1),[0,20]).all():
        raise ValueError('FROZEN_COMMON_INFORMATION_OR_TOP20_BUY_BIT_CHANGED')
    vol=np.full(top.shape,np.nan)
    for year in (2023,2024,2025):
        frame=reader.read_inference(year)[['signal_date','ticker','realized_vol_20d']]
        array=old.values(frame,dates,tickers,'realized_vol_20d');mask=np.isfinite(array);vol[mask]=array[mask]*np.sqrt(5.)
    vol=np.where(stock,vol,np.nan)
    market=MarketArrays(dates,tickers,old.values(bars,dates,tickers,'open'),old.values(bars,dates,tickers,'close'),
        quality=np.zeros(top.shape,bool),row_present=old.values(bars.assign(present=True),dates,tickers,'present',False,bool),
        input_present=union,new_buy_eligible=buy,signal_asof=[d.tz_localize('America/New_York')+pd.Timedelta(hours=16) for d in dates])
    return market,top,qualified,vol,stock,raw


def execute_market(market,candidates,packets,top,qualified,vol,account,*,stock_present=None,raw_selector_present=None,events=(),known_at=None,unsupported=(),risk_provider=None):
    """No I/O: real shared fills update previous action; targets never update it."""
    if stock_present is None or raw_selector_present is None or not np.array_equal(market.input_present,np.asarray(stock_present,bool)|np.asarray(raw_selector_present,bool)):
        raise ValueError('EXPLICIT_COMMON_INFORMATION_SOURCE_BITS_REQUIRED')
    ids=tuple(c['candidate_id'] for c in candidates);pi={p:i for i,p in enumerate(ids)};ti={t:i for i,t in enumerate(market.tickers)}
    previous=np.full((len(ids),len(ti)),'NO_ACTUAL_FILL',dtype=object)
    last_fill=np.full(previous.shape,np.datetime64('NaT','ns'),dtype='datetime64[ns]')
    holding_chunks=[];action_chunks=[]
    overlay=StatefulOverlay(candidates,packets,top,qualified,vol,risk_provider=risk_provider)
    def callback(name,frame):
        if name=='fills':
            for r in frame.itertuples():
                previous[pi[r.path_id],ti[r.ticker]]=r.action;last_fill[pi[r.path_id],ti[r.ticker]]=r.execution_date
        elif name=='positions':
            f=frame.copy();f['previous_actual_action']=[previous[pi[p],ti[t]] for p,t in zip(f.path_id,f.ticker)]
            f['previous_actual_fill_date']=[last_fill[pi[p],ti[t]] for p,t in zip(f.path_id,f.ticker)];holding_chunks.append(f)
    def policy(di,ctx):
        target=overlay(di,ctx)
        for p,c in enumerate(candidates):
            held=ctx.current_units[p]>1e-10;indexes=np.flatnonzero(top[di]|held|target.explicit_mask[p]|(target.weights[p]>0))
            if not len(indexes):continue
            packet=packets[c['value_model']];count=int(top[di].sum());weights=target.weights[p,indexes];explicit=target.explicit_mask[p,indexes]
            action=np.where(~explicit,np.where(held[indexes],'HOLD','SKIP'),np.where(weights>ctx.current_weights[p,indexes]+1e-10,'BUY_OR_ADD',np.where(weights<ctx.current_weights[p,indexes]-1e-10,'SELL_OR_REDUCE','HOLD')))
            action_chunks.append(pd.DataFrame({'path_id':c['candidate_id'],'signal_date':ctx.signal_date,'ticker':market.tickers[indexes],
                'is_raw_top20':top[di,indexes],'qualified':qualified[di,indexes],'new_buy_eligible':market.new_buy_eligible[di,indexes],
                'decision_information_present_union':market.input_present[di,indexes],
                'stock_forecast_input_present':stock_present[di,indexes],'raw_selector_input_present':raw_selector_present[di,indexes],
                'prediction':packet['mu'][di,indexes],'value_sigma':packet['sigma'][di],'model_lineage':packet['lineage'][di],
                'vol5':vol[di,indexes],'held_before_decision':held[indexes],'actual_fractional_shares':ctx.current_units[p,indexes],
                'actual_weight':ctx.current_weights[p,indexes],'holding_age':ctx.holding_age[p,indexes],'entry_date':ctx.entry_date[p,indexes],
                'entry_price':ctx.entry_price[p,indexes],'entry_execution_open':ctx.entry_execution_open[p,indexes],
                'previous_actual_action':previous[p,indexes],'previous_actual_fill_date':last_fill[p,indexes],
                'policy_explicit':explicit,'policy_weight':weights,'policy_action':action,
                'raw_top20_count':count,'source_intent_equal_weight':np.where(top[di,indexes],1./count if count else 0.,0.),
                'signal_close_available':np.isfinite(market.close[di,indexes])&(market.close[di,indexes]>0),
                'planned_execution_date':market.dates[di+1] if di+1<len(market.dates) else pd.NaT}))
        return target
    replay=run_continuous_account(market,ids,policy,account,corporate_actions=events,
        corporate_action_known_at=known_at,unsupported_events=unsupported,ledger_callback=callback)
    actions=pd.concat(action_chunks,ignore_index=True) if action_chunks else pd.DataFrame()
    holdings=pd.concat(holding_chunks,ignore_index=True) if holding_chunks else replay.positions
    if len(actions):
        orders=replay.orders[['path_id','signal_date','ticker','decision_semantic']].rename(columns={'decision_semantic':'engine_order_decision_semantic'})
        actions=actions.merge(orders,on=['path_id','signal_date','ticker'],how='left',validate='one_to_one')
        actions['engine_order_recorded']=actions.engine_order_decision_semantic.notna()
    terminal=[]
    for p,path in enumerate(ids):
        terminal.append({'path_id':path,'as_of':market.dates[-1],'row_type':'CASH','ticker':'__CASH_USD__','cash':float(replay.final_state['cash'][p]),'fractional_shares':0.})
        for t in np.flatnonzero(replay.final_state['fractional_shares'][p]>1e-10):
            terminal.append({'path_id':path,'as_of':market.dates[-1],'row_type':'HOLDING','ticker':market.tickers[t],
                'cash':0.,'fractional_shares':float(replay.final_state['fractional_shares'][p,t]),
                'engine_units':float(replay.final_state['engine_units'][p,t]),'holding_age':int(replay.final_state['holding_age'][p,t]),
                'entry_date':replay.final_state['entry_date'][p,t],'entry_price':float(replay.final_state['entry_price'][p,t]),
                'entry_execution_open':float(replay.final_state['entry_execution_open'][p,t]),
                'previous_actual_action':previous[p,t],'previous_actual_fill_date':last_fill[p,t]})
    continuation=pd.DataFrame(terminal);continuation['annual_reset']=False
    continuation['accounting_qualified']=continuation.path_id.map({path:bool(replay.final_state['accounting_qualified'][i]) for i,path in enumerate(ids)})
    continuation['pending_orders_semantics']='FROZEN_FULL_PREFIX_RECONSTRUCTION_REQUIRED; NO_FABRICATED_2026_FILL'
    frames={'daily':replay.daily,'positions':holdings,'fills':replay.fills,'orders':replay.orders,
        'execution_results':replay.execution_results,'actions':actions,'source_intents':actions[['path_id','signal_date','ticker','is_raw_top20','qualified','new_buy_eligible','raw_top20_count','source_intent_equal_weight','stock_forecast_input_present','raw_selector_input_present','decision_information_present_union']].copy(),'gross':pd.DataFrame(overlay.audit),
        'cash':replay.daily[['path_id','date','cash','accounting_qualified']].copy(),'continuation':continuation,
        'contexts':replay.contexts,'costs':replay.daily[['path_id','date','transaction_cost_amount','buy_notional','sell_notional']].copy()}
    for f in frames.values():f['scenario']='V24_PRE2026_USD3000_FRACTIONAL_RESEARCH_REPLAY'
    return replay,frames


def _events(path):
    return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s] if path.exists() else []


def _append(path,event):
    assert_write_path(path,'backtest')
    with path.open('a',encoding='utf-8',newline='\n') as stream:
        stream.write(json.dumps(event,sort_keys=True,allow_nan=False)+'\n');stream.flush()


def run(run_dir,candidate_ids=None):
    run_dir,config,auth,candidates=frozen_contract(run_dir)
    if candidate_ids is not None:
        requested=set(candidate_ids)
        if not requested or not requested.issubset({c['candidate_id'] for c in candidates}):raise ValueError('UNKNOWN_REQUESTED_FROZEN_CANDIDATE')
        candidates=[c for c in candidates if c['candidate_id'] in requested]
    log=run_dir/'ACCOUNT_PATH_LOG.jsonl';history=_events(log)
    started=[e for e in history if e['event']=='ACCOUNT_PATH_ATTEMPT_STARTED']
    if any(c['candidate_id'] in {e['candidate_id'] for e in started} or c['scientific_tuple_sha256'] in {e['scientific_tuple_sha256'] for e in started} for c in candidates):
        raise ValueError('ALREADY_ATTEMPTED_ACCOUNT_ID_OR_TUPLE_NO_ALIAS_RETRY')
    if config['prior_account_paths']+len(started)+len(candidates)>MAX_PATHS:raise ValueError('FULL_ACCOUNT_PATH_BUDGET_EXHAUSTED')
    batch=len({e['batch'] for e in started})+1;folder=run_dir/'ledgers/stateful'/f'attempt_{batch:04d}'
    assert_write_path(folder,'backtest')
    if folder.exists():raise ValueError('EXISTING_ACCOUNT_OUTPUTS_PRESERVED')
    folder.mkdir(parents=True)
    for c in candidates:_append(log,{'event':'ACCOUNT_PATH_ATTEMPT_STARTED','path_units':1,'batch':batch,'candidate_id':c['candidate_id'],'scientific_tuple_sha256':c['scientific_tuple_sha256'],'reference_replay':c.get('reference_identity'),'module_sha256':auth['module_sha256']})
    try:
        reader=InputReader(run_dir);market,top,qualified,vol,stock,raw=read_market(reader)
        packets={};model_failures={};risk_failures={};providers={};risk_metadata=[]
        for model in {c['value_model'] for c in candidates}:
            try:
                packets[model]=read_packet(auth['value_packets'][model],reader,market.dates,market.tickers,auth=auth)
                packets[model]['mu']=np.where(stock,packets[model]['mu'],np.nan)
            except Exception as exc:
                model_failures[model]={'type':type(exc).__name__,'message':str(exc)}
        for method in {c['risk'] for c in candidates if c['risk'] not in ('diag','diag20_reference')}:
            try:
                provider,details=read_risk_packets(auth,reader,[c for c in candidates if c['risk']==method],market.dates,vol,run_dir)
                providers[method]=provider;risk_metadata.append(details)
            except Exception as exc:
                risk_failures[method]={'type':type(exc).__name__,'message':str(exc)}
        blocked={c['candidate_id']:model_failures.get(c['value_model'],risk_failures.get(c['risk'])) for c in candidates if c['value_model'] in model_failures or c['risk'] in risk_failures}
        for c in candidates:
            if c['candidate_id'] in blocked:
                _append(log,{'event':'ACCOUNT_PATH_FAILED','batch':batch,'candidate_id':c['candidate_id'],'scientific_tuple_sha256':c['scientific_tuple_sha256'],'failure':blocked[c['candidate_id']],'stage':'MODEL_OR_RISK_SOURCE_BEFORE_ACCOUNT'})
        active=[c for c in candidates if c['candidate_id'] not in blocked]
        if not active:
            audit={'status':'BLOCKED_ALL_REQUESTED_CANDIDATES_DATA_OR_MODEL','account_paths_created':0,'attempt_units':len(candidates),'blocked':blocked,'fit_units':0,'2026_rows_read':0}
            write_json_atomic(folder/'audit.json',audit)
            return {'status':audit['status'],'audit_path':str(folder/'audit.json'),'blocked':blocked}
        def risk_provider(di,selected,tickers,method):
            if method in ('diag','diag20_reference'):return np.diag(vol[di,selected]**2)
            return providers[method](di,selected,tickers,method)
        old=_old();account=old.config_adapter(_json(PARENT/'R1_ACCOUNT_CONFIG.json'))
        events,known,unsupported,event_receipt=old.frozen_events(_json(PARENT/'INPUT_BINDING_R1.json'))
        replay,frames=execute_market(market,active,packets,top,qualified,vol,account,stock_present=stock,raw_selector_present=raw,events=events,known_at=known,unsupported=unsupported,risk_provider=risk_provider)
        risk_records=[record for group in risk_metadata for record in group]
        if risk_records:frames['risk_metadata']=pd.DataFrame(risk_records)
        expected=pd.MultiIndex.from_product([market.dates,[c['candidate_id'] for c in active]],names=['date','path_id'])
        actual=pd.MultiIndex.from_frame(replay.daily[['date','path_id']])
        if not actual.sort_values().equals(expected.sort_values()):raise ValueError('ACCOUNT_DROPPED_FULL_DATE_PATH_GRID')
        records={}
        for name,frame in frames.items():
            path=folder/(name+'.parquet');assert_write_path(path,'backtest');frame.to_parquet(path,index=False)
            records[name]={'path':str(path),'sha256':sha(path),'rows':len(frame),'schema':list(frame.columns)}
        frozen_contract(run_dir)
        eligibility={}
        for c in active:
            d=replay.daily.loc[replay.daily.path_id.eq(c['candidate_id'])].sort_values('date')
            eligibility[c['candidate_id']]={str(y):{'sessions':int(d.date.dt.year.eq(y).sum()),
                'accounting_qualified_all':bool(d.loc[d.date.dt.year.eq(y),'accounting_qualified'].all()),
                'certified_nav_positive_and_finite_all':bool((np.isfinite(d.loc[d.date.dt.year.eq(y),'certified_nav'])&(d.loc[d.date.dt.year.eq(y),'certified_nav']>0)).all()),
                'net_return_finite_except_initial':bool(np.isfinite(d.loc[d.date.dt.year.eq(y)&d.date.ne(market.dates[0]),'net_return']).all())} for y in (2023,2024,2025)}
        audit={'status':'ACTUAL_CONTINUOUS_PRE2026_REPLAY_COMPLETE','batch':batch,'candidate_ids':[c['candidate_id'] for c in candidates],
            'account_paths_created':len(active),'blocked_candidates':blocked,'account_path_attempts_cumulative':config['prior_account_paths']+len(started)+len(candidates),
            'source_closure':{k:sha(p) for k,p in SOURCE_PATHS.items()},'input_manifest_sha256':auth['input_manifest_sha256'],
            'candidates_sha256':auth['candidates_sha256'],'account_config':account,'source_events':event_receipt,
            'packet_sources':{k:v['source_receipts'] for k,v in packets.items()},'calendar_sessions':752,'annual_reset':False,
            'artifacts':records,'selection_eligibility':eligibility,'accounting_exceptions':replay.accounting_exceptions.to_dict('records'),
            'prefix_identity':replay.prefix_identity,'selection_performed':False,'fit_units':0,'2026_rows_read':0,
            'state_updates':'ACTUAL_FILLS_SUPPORTED_EVENTS_ONLY; NEVER_TARGET_WEIGHTS',
            'reference_paths_are_new_account_replays_not_old_artifact_reuse':True,
            'cash_authority':'ZERO_INTEREST; NO_CASH_COMPONENT_INFERENCE; UNSUPPORTED_EVENTS_FAIL_CLOSED',
            'deployment_role':'PRE2026_RESEARCH_ONLY; NO_LOCKED_TEST_OR_LIVE_DEPLOYMENT'}
        write_json_atomic(folder/'audit.json',audit)
        for c in active:_append(log,{'event':'ACCOUNT_PATH_COMPLETE','batch':batch,'candidate_id':c['candidate_id'],'scientific_tuple_sha256':c['scientific_tuple_sha256'],'audit_path':str(folder/'audit.json'),'audit_sha256':sha(folder/'audit.json')})
        return {'status':audit['status'],'audit_path':str(folder/'audit.json'),'rows':{k:v['rows'] for k,v in records.items()},'selection_eligibility':eligibility}
    except Exception as exc:
        failure={'type':type(exc).__name__,'message':str(exc)}
        write_json_atomic(folder/'audit.json',{'status':'FAILED_ACCOUNT_ATTEMPT_RETAINED','batch':batch,'candidate_ids':[c['candidate_id'] for c in candidates],'account_path_units_consumed':len(candidates),'failure':failure,'fit_units':0,'2026_rows_read':0})
        for c in candidates:
            if c['candidate_id'] not in locals().get('blocked',{}):_append(log,{'event':'ACCOUNT_PATH_FAILED','batch':batch,'candidate_id':c['candidate_id'],'scientific_tuple_sha256':c['scientific_tuple_sha256'],'failure':failure})
        raise


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--candidate',action='append')
    args=p.parse_args(argv);print(json.dumps(run(args.run_dir,args.candidate),sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
