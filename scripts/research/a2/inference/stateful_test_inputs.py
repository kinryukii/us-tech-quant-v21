"""Thin 2026 input projections; existing owners retain feature/rank mathematics.

No model fitting, source discovery, account implementation or implicit authority.
Callers bind physical raw/factor/identity references before these pure functions.
"""
from __future__ import annotations
from copy import deepcopy
import numpy as np
import pandas as pd
from scripts.research.a2.training import stateful_inputs, stateful_decision as decision
from scripts.research.a2.training.stateful_inputs import FEATURES
from scripts.research.a2.training.stateful_final_action_packets import decode_r6_row
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays
from scripts.research.a2.evaluation import frozen_test_authority as authority
from scripts.research.a2.inference import stateful_frozen_test as frozen


def _need(ok, code):
    if not ok:
        raise ValueError(code)


def project_features(raw, factors, entry, calendar, start, end, *, adapter, wolf, feature_function):
    """Apply original event-date index and PIT32 function to an admitted raw leaf."""
    dates = pd.DatetimeIndex(pd.to_datetime(calendar))
    first, last = pd.Timestamp(start), pd.Timestamp(end)
    _need(not dates.has_duplicates and dates.is_monotonic_increasing
          and first in dates and last in dates and first <= last
          and last < pd.Timestamp('2027-01-01'), 'FEATURE_CALENDAR_BOUNDARY')
    raw = raw.copy()
    raw['trade_date'] = pd.to_datetime(raw.trade_date)
    _need(not raw.trade_date.isna().any() and raw.trade_date.max() <= last
          and not raw.trade_date.duplicated().any() and raw.trade_date.is_monotonic_increasing,
          'FEATURE_RAW_TIME_OR_DUPLICATE')
    _need({'ticker', 'code', 'price_basis'} <= set(entry)
          and entry['price_basis'] == 'PIT_FORWARD_REHAB_INDEX', 'FEATURE_ENTRY_IDENTITY')
    _need('ex_div_date' in factors or factors.empty, 'FEATURE_FACTOR_DATE_UNBOUND')
    if not factors.empty:
        _need(pd.to_datetime(factors.ex_div_date).lt(last + pd.Timedelta(days=1)).all(),
              'FEATURE_FUTURE_FACTOR_REJECTED')
    adjusted, events = adapter.adjusted_price_frame(entry['code'], entry['ticker'], raw, factors, wolf)
    feature = feature_function(adjusted[['ticker', 'trade_date', 'close', 'volume']])
    position = pd.Series(np.arange(len(dates)), index=dates)
    positions = feature.trade_date.map(position)
    contiguous = positions.diff().eq(1).rolling(120, min_periods=120).sum().eq(120)
    legal = (positions.sub(positions.shift(120)).eq(120) & contiguous
             & np.isfinite(feature[list(FEATURES)].to_numpy(float)).all(axis=1))
    use = legal & feature.trade_date.between(first, last)
    output = feature.loc[use, ['trade_date', 'ticker', *FEATURES]].copy()
    if entry.get('anchor_proof', {}).get('kind') == 'NEW_13F_MEMBER_NATIVE_RAW_ANCHOR':
        output = output.loc[output.trade_date.ge('2026-01-01')]
    return output.reset_index(drop=True), events


def assemble_flags(features, ranked, dated_identity):
    """Keep original opportunity/feature union and unknown SID fallback explicit.

    dated_identity is a caller-proven date/ticker/SID projection; this function
    never fills identity gaps with today's mapping or guesses a historical SID.
    """
    f = features.rename(columns={'trade_date': 'signal_date'}).copy()
    r = ranked.rename(columns={'target_date': 'signal_date', 'rank': 'raw_a2_rank',
        'score': 'raw_a2_prediction', 'universe_quarter': 'active_13f_quarter'}).copy()
    identity = dated_identity[['signal_date', 'ticker', 'security_id', 'is_max_group']].copy()
    for frame in (f, r, identity):
        frame['signal_date'] = pd.to_datetime(frame.signal_date)
        _need(not frame.signal_date.isna().any() and not frame.duplicated(['signal_date','ticker']).any()
              and (frame.empty or frame.signal_date.max() < pd.Timestamp('2027-01-01')), 'FLAG_KEYS_OR_TIME')
    _need(np.isfinite(f[list(FEATURES)].to_numpy(float)).all(), 'NONFINITE_ADMITTED_FEATURE')
    _need(np.isfinite(r.raw_a2_rank.to_numpy(float)).all()
          and r.raw_a2_rank.gt(0).all() and r.raw_a2_rank.mod(1).eq(0).all()
          and not r.duplicated(['signal_date','raw_a2_rank']).any(),
          'RAW_RANK_IDENTITY')
    raw = r[['signal_date','ticker','raw_a2_rank','raw_a2_prediction','active_13f_quarter']].copy()
    raw['raw_selector_input_present'] = True
    out = f.merge(raw,on=['signal_date','ticker'],how='outer',validate='one_to_one')
    out = out.merge(identity,on=['signal_date','ticker'],how='left',validate='one_to_one')
    out['feature_available'] = np.isfinite(out[list(FEATURES)].to_numpy(float)).all(axis=1)
    out['feature_source'] = np.where(out.feature_available,
        'FROZEN_RAW_A2_FULL_PIT32_LEDGER_PROJECTION','UNAVAILABLE')
    out['input_present'] = out.feature_available
    out['stock_forecast_input_present'] = out.feature_available
    out['raw_selector_input_present'] = out.raw_selector_input_present.eq(True)
    out['decision_information_present_union'] = out.feature_available | out.raw_selector_input_present
    out['is_max_group'] = out.is_max_group.eq(True)
    out['is_raw_top20'] = out.raw_a2_rank.le(20)
    counts = out.groupby('signal_date').is_raw_top20.sum()
    _need(counts.isin([0,20]).all(), 'INCOMPLETE_RAW20_CANNOT_BE_PROMOTED')
    out['raw_top20_set_count'] = out.signal_date.map(counts).astype(int)
    out['raw_top20_set_complete'] = out.raw_top20_set_count.eq(20)
    out['new_buy_eligible'] = out.is_raw_top20 & out.is_max_group
    out['raw_a2_oof_split'] = 'FROZEN_FULL_PRE2026_APPLIED_2026_NO_REFIT'
    return out.sort_values(['signal_date','ticker']).reset_index(drop=True)


def build_proxy_samples(history_pred, test_flags, calendar, admitted):
    """Original R6 cohort phase from complete 2023 history, without any labels.

    Build once on the admitted MAIN horizon. Random fresh accounts slice these
    exogenous states; they never restart the original proxy cohort process.
    """
    dates = pd.DatetimeIndex(calendar)
    _need(not dates.empty and not dates.hasnans and dates.is_unique
          and dates.is_monotonic_increasing and dates[0] >= pd.Timestamp('2023-01-01'),
          'PROXY_ORDERED_2023_CONTEXT_REQUIRED')
    columns = list(dict.fromkeys((*stateful_inputs.PRED_FLAGS, *FEATURES, *decision.PRED_EXTRA)))
    for frame in (history_pred, test_flags):
        _need(not (set(frame) & frozen._FORBIDDEN) and set(columns) <= set(frame),
              'PROXY_CAUSAL_INPUT_COLUMNS_REQUIRED')
    history = history_pred[columns].copy()
    future = test_flags[columns].copy()
    history['signal_date'] = pd.to_datetime(history.signal_date)
    future['signal_date'] = pd.to_datetime(future.signal_date)
    prior_dates = dates[dates < pd.Timestamp('2026-01-01')]
    _need(not prior_dates.empty and prior_dates[0].year == 2023
          and pd.DatetimeIndex(history.signal_date.drop_duplicates().sort_values()).equals(prior_dates)
          and history.signal_date.lt('2026-01-01').all()
          and future.signal_date.ge('2026-01-01').all(), 'PROXY_COMPLETE_PRE2026_PHASE_REQUIRED')
    authority.validate_descriptive_input_dates(admitted, dates, feature_context=True)
    authority.validate_descriptive_input_dates(admitted, future.signal_date)
    pred = pd.concat([history, future], ignore_index=True)
    empty_labels = pd.DataFrame(columns=decision.LABEL_COLS)
    outputs, audit = decision.build_samples(pred, empty_labels, dates,
        descriptive_evaluation_authority=admitted)
    result = {}
    for objective, features in (('buy', decision.SINGLE), ('replace', decision.PAIR)):
        keys = ('signal_date', 'sample_id', 'ticker', 'security_id', 'incumbent', 'incumbent_sid')
        wanted = list(dict.fromkeys((*keys, *features)))
        frame = outputs[objective]
        if frame.empty:
            result[objective] = pd.DataFrame(columns=wanted)
        else:
            result[objective] = frame.loc[frame.signal_date.ge('2026-01-01'),
                [c for c in wanted if c in frame]].reset_index(drop=True)
    return result, dict(audit, label_rows_read=0, new_fit=0,
                       phase='ORIGINAL_2023_EXOGENOUS_COHORT_NOT_FRESH_ACCOUNT_STATE')


def r6_supported_samples(samples, objective):
    """Frozen SID and 0..20 cohort support; never use label availability."""
    _need(objective in ('buy', 'replace'), 'ONLY_BUY_REPLACE_SUPPORT')
    if samples.empty:
        return samples.copy()
    _need(not (set(samples) & frozen._FORBIDDEN), 'PROXY_INFERENCE_FORBIDS_LABELS')
    legal = samples.security_id.map(decision._valid_sid)
    ages = ('cohort_age_sessions',) if objective == 'buy' else ('e_cohort_age_sessions','i_cohort_age_sessions')
    for col in ages:
        legal &= samples[col].between(0,20)
    if objective == 'replace':
        legal &= samples.incumbent_sid.map(decision._valid_sid)
    return samples.loc[legal].reset_index(drop=True)


def project_window(flags, bars, dates, admitted, *, values_function):
    """Original old.values/MarketArrays layout; the caller supplies raw quotes."""
    dates = pd.DatetimeIndex(dates)
    authority.validate_descriptive_input_dates(admitted, dates)
    flags = flags.loc[pd.to_datetime(flags.signal_date).isin(dates)].copy()
    bars = bars.rename(columns={'trade_date':'signal_date'}).copy()
    bars['signal_date'] = pd.to_datetime(bars.signal_date)
    bars = bars.loc[bars.signal_date.isin(dates)]
    flags['signal_date'] = pd.to_datetime(flags.signal_date)
    names = sorted(set(flags.ticker.astype(str)) | set(bars.ticker.astype(str)))
    _need(bool(names), 'WINDOW_TICKERS_UNBOUND')
    arrays = {key: values_function(flags, dates, names, column, False, bool) for key,column in
        dict(top='is_raw_top20',qualified='is_max_group',union='decision_information_present_union',
             stock='stock_forecast_input_present',raw='raw_selector_input_present',buy='new_buy_eligible').items()}
    _need(np.array_equal(arrays['union'],arrays['stock']|arrays['raw'])
          and np.array_equal(arrays['buy'],arrays['top']&arrays['qualified'])
          and np.isin(arrays['top'].sum(axis=1),[0,20]).all(), 'WINDOW_FROZEN_INFORMATION_BITS_CHANGED')
    vol = values_function(flags,dates,names,'realized_vol_20d') * np.sqrt(5.)
    vol = np.where(arrays['stock'],vol,np.nan)
    market = MarketArrays(dates,names,values_function(bars,dates,names,'open'),
        values_function(bars,dates,names,'close'),quality=np.zeros(arrays['top'].shape,bool),
        row_present=values_function(bars.assign(present=True),dates,names,'present',False,bool),
        input_present=arrays['union'],new_buy_eligible=arrays['buy'],
        signal_asof=[d.tz_localize('America/New_York')+pd.Timedelta(hours=16) for d in dates])
    return dict(market=market,top=arrays['top'],qualified=arrays['qualified'],vol=vol,
        stock_present=arrays['stock'],raw_selector_present=arrays['raw'],
        sid_by_key={(pd.Timestamp(r.signal_date),str(r.ticker)):r.security_id for r in flags.itertuples()})


def window_inputs(window, admitted, *, flags, stock_bars, etf_bars, calendar, account,
                  account_source_kwargs_by_group, model_evidence, values_function):
    """Pure six-path provider from admitted projections and already frozen outputs.

    Never calls model prediction. Evidence contains original validated bundles,
    causal samples and the thin adapter's predictions. No result/outcome is an
    input, and missing heads remain missing for the per-path execution gate.
    """
    dates = pd.DatetimeIndex(calendar)
    dates = dates[(dates >= pd.Timestamp(window['start'])) & (dates <= pd.Timestamp(window['end']))]
    _need(len(dates)>=2 and dates[0]==admitted.start and dates[-1]==admitted.end
          and str(dates[1].date())==window['first_execution_date'], 'PROVIDER_WINDOW_CLOCK_CHANGED')
    stock = project_window(flags,stock_bars,dates,admitted,values_function=values_function)
    shape = stock['top'].shape
    # The original RAW/R6 alias B indexes this packet but never uses its values.
    # NaN is an explicitly unused interface carrier, not a Ridge forecast.
    packets = dict(ridge=dict(mu=np.full(shape,np.nan),sigma=np.full(len(dates),np.nan),
        lineage=np.full(len(dates),'RAW_REFERENCE_UNUSED_VALUE_CARRIER_NO_PREDICTION',dtype=object),
        packet_role='UNUSED_INTERFACE_CARRIER_NO_RIDGE_INFERENCE'))
    evidence, actions = {}, {}
    for cid in authority.MODEL_IDS:
        if cid not in model_evidence:
            continue
        original = model_evidence[cid]
        bundle = original['bundle']
        full = original['predictions'].reset_index(drop=True)
        mask = pd.to_datetime(full.signal_date).isin(dates)
        predictions = full.loc[mask].reset_index(drop=True)
        if cid in authority.MODEL_IDS[:2]:
            samples = original['samples']
            samples = samples.loc[pd.to_datetime(samples.signal_date).isin(dates)].reset_index(drop=True)
            eligible = r6_supported_samples(samples,bundle.objective)
            actions[cid] = {}
            for order, row in zip(np.flatnonzero(mask),predictions.to_dict('records')):
                date = pd.Timestamp(row['signal_date'])
                actions[cid].setdefault(date,[]).append(decode_r6_row(row,bundle.objective,int(order)))
        else:
            samples = None
            eligible = predictions.loc[predictions.prediction_qualified.eq(True)]
            sigma = float(bundle.model.calibration['sigma'])
            _need(np.isfinite(sigma) and sigma>0
                  and eligible.value_sigma.eq(sigma).all(), 'PROVIDER_FROZEN_SIGMA_CHANGED')
            packets['ngboost'] = dict(mu=values_function(eligible,dates,stock['market'].tickers,'prediction'),
                sigma=np.full(len(dates),sigma),lineage=np.full(len(dates),
                'FROZEN_2025|'+bundle.model_ref['sha256'],dtype=object))
        counts = eligible.groupby('signal_date').size() if not eligible.empty else pd.Series(dtype=int)
        support = pd.DataFrame(dict(signal_date=dates,
            eligible_count=[int(counts.get(date,0)) for date in dates]))
        support['status'] = np.where(support.eligible_count.gt(0),'INFERRED','NO_SUPPORT')
        support['reason'] = np.where(support.eligible_count.gt(0),'',
            'ORIGINAL_SID_AGE_FEATURE_SUPPORT_MASK_EMPTY' if samples is not None else 'NO_FEATURE_SUPPORTED_ROWS')
        evidence[cid] = dict(bundle=bundle,samples=samples,predictions=predictions,support=support)
    stock.update(packets=packets,action_packets=actions,inference_evidence=evidence,
        account=deepcopy(account),account_source_kwargs=deepcopy(account_source_kwargs_by_group['stocks']))
    result = dict(stocks=stock)
    result.update(benchmark_window_inputs(dates, etf_bars=etf_bars, account=account,
        account_source_kwargs_by_group=account_source_kwargs_by_group, values_function=values_function))
    return result


def benchmark_window_inputs(dates, *, etf_bars, account, account_source_kwargs_by_group, values_function):
    """Original ETF-only source projection shared with the six-path provider."""
    dates = pd.DatetimeIndex(dates)
    result = {}
    for cid in authority.PATH_IDS[4:]:
        ticker = cid.split('_',1)[0]
        bars = etf_bars[ticker].rename(columns={'trade_date':'signal_date'}).copy()
        bars['signal_date'] = pd.to_datetime(bars.signal_date)
        bars = bars.loc[bars.signal_date.isin(dates)]
        _need(bars.ticker.eq(ticker).all(), 'PROVIDER_ETF_TICKER_CHANGED')
        shape = (len(dates),1)
        market = MarketArrays(dates,[ticker],values_function(bars,dates,[ticker],'open'),
            values_function(bars,dates,[ticker],'close'),quality=np.zeros(shape,bool),
            row_present=values_function(bars.assign(present=True),dates,[ticker],'present',False,bool),
            signal_asof=[d.tz_localize('America/New_York')+pd.Timedelta(hours=16) for d in dates])
        result[cid] = dict(market=market,account=deepcopy(account),
            account_source_kwargs=deepcopy(account_source_kwargs_by_group[cid]))
    return result
