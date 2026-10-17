"""Thin aggregate-13F input adapter for the frozen six-path descriptive replay.

The source owner selects amount Top100 before identity/price coverage. This module
only joins admitted inputs and calls existing rank, flag, sample and inference
owners. It discovers no sources, writes no artifacts, fits no models and owns no
account, source qualification, authority or trial journal.
"""
from __future__ import annotations
from copy import deepcopy
import numpy as np
import pandas as pd
from scripts.research.a2.inference import historical_top40 as ranking
from scripts.research.a2.inference import stateful_test_inputs as inputs
from scripts.research.a2.inference import stateful_frozen_test as inference
from scripts.research.a2.evaluation import frozen_test_authority as authority
from scripts.research.a2.training import stateful_decision as decision
from scripts.research.a2.training import stateful_replay as replay
from scripts.research.a2.training.stateful_final_action_packets import decode_r6_row

TASK = "V24_A_13F_AGGREGATE_TOP100_RETEST_20261008_R1"


def _need(ok, code):
    if not ok:
        raise ValueError(code)


def project_universe(schedule, members, dated_identity, sessions, *, task_id=TASK, selection_rule=None,
                     pool_variant_id=None, source_manifest_ref=None):
    """Project already selected Top100 to the latest available quarter per close.

    Identity rows are caller-qualified as-of mappings keyed by signal_date/CUSIP.
    Missing mappings stay in every declared pool. Per-day snapshot IDs preserve
    dated identity changes without rewriting the source snapshot's membership.
    """
    from scripts.research.a2.evaluation import frozen_a94_profile as profile
    all_consensus = task_id == profile.ALL_TASK
    sensitivity = task_id == 'A_ALL_REPAIR_AND_CONSENSUS_SENSITIVITY_20261011_R1'
    expected_n = 100
    if sensitivity:
        import json
        _need(isinstance(source_manifest_ref, dict) and source_manifest_ref.get('sha256') ==
              '112c596625e3cef490c01f902294924f738b498f50098172348e2e2d6c5ac644',
              'SENSITIVITY_FROZEN_SOURCE_MANIFEST_REQUIRED')
        manifest = json.loads(authority._physical(source_manifest_ref).read_text(encoding='utf-8'))
        _need(manifest.get('task_id') == task_id and pool_variant_id in manifest.get('variants', {}),
              'SENSITIVITY_DECLARED_VARIANT_REQUIRED')
        selected = manifest['variants'][pool_variant_id]
        expected_n = selected['n']
        _need(type(expected_n) is int and expected_n in (100, 200, 300, 400),
              'SENSITIVITY_DECLARED_SIZE_REQUIRED')
        for actual, name in ((schedule, 'schedule_ref'), (members, 'members_ref')):
            frozen = pd.read_parquet(authority._physical(selected[name]))
            _need(actual.equals(frozen), 'SENSITIVITY_FROZEN_LIST_CONTENT_CHANGED')
        _need(schedule.institution_count.eq(selected['cohort_count']).all(),
              'SENSITIVITY_DECLARED_COHORT_REQUIRED')
    else:
        _need(pool_variant_id is None and source_manifest_ref is None,
              'SENSITIVITY_ARGUMENTS_REQUIRE_EXACT_TASK')
    if all_consensus:
        contract = profile.profile_contract(task_id)
        _need(contract['raw_selector_binding'].get('universe_variant') == 'CONSENSUS100',
              'ALL_A_CONSENSUS_PROJECTION_SCOPE_REQUIRED')
    _need(all_consensus or sensitivity or task_id in authority.universe_variant_tasks(), 'AGGREGATE_EXACT_TASK_REQUIRED')
    consensus = all_consensus or sensitivity or task_id in authority.consensus_variant_tasks()
    expected_rule = 'MANAGER_COUNT_WEIGHT_SUM' if consensus else 'AGGREGATE_USD'
    _need(selection_rule in (None, expected_rule), 'AGGREGATE_SELECTION_RULE_TASK_MISMATCH')
    rank_column = 'consensus_rank' if consensus else 'amount_rank'
    schedule, members, identity = schedule.copy(), members.copy(), dated_identity.copy()
    if consensus:
        _need({'manager_count','holding_weight_sum_exact'} <= set(members)
              and 'amount_rank' not in members, 'CONSENSUS_SOURCE_RANK_ROLE_REQUIRED')
    dates = pd.DatetimeIndex(pd.to_datetime(sessions))
    _need(len(dates) > 0 and dates.tz is None and dates.is_unique and dates.is_monotonic_increasing
          and dates.equals(dates.normalize()) and dates.max() < pd.Timestamp('2027-01-01'), 'AGGREGATE_SESSION_BOUNDARY')
    _need({'snapshot_id','quarter','effective_at','institution_count'} <= set(schedule)
          and {'snapshot_id','cusip',rank_column} <= set(members)
          and {'signal_date','cusip','ticker','security_id'} <= set(identity), 'AGGREGATE_SOURCE_SCHEMA')
    _need(not schedule.snapshot_id.duplicated().any()
          and not members.duplicated(['snapshot_id','cusip']).any(), 'AGGREGATE_SOURCE_DUPLICATE')
    _need(set(members.snapshot_id) == set(schedule.snapshot_id), 'AGGREGATE_SNAPSHOT_MEMBERS_MISMATCH')
    schedule['effective_at'] = schedule.effective_at.map(pd.Timestamp)
    _need(schedule.effective_at.map(lambda d: not pd.isna(d) and d.tzinfo is not None).all(), 'AGGREGATE_PUBLICATION_CLOCK_REQUIRED')
    schedule['quarter_order'] = schedule.quarter.map(lambda q: pd.Period(q, freq='Q').ordinal)
    _need(not schedule.duplicated(['quarter','effective_at']).any(), 'AGGREGATE_AMBIGUOUS_REVISION')
    for _, pool in members.groupby('snapshot_id'):
        _need(len(pool) == expected_n and sorted(pool[rank_column].tolist()) == list(range(1,expected_n+1)), 'AGGREGATE_ORIGINAL_AMOUNT_TOP100_REQUIRED')
    _need(pd.to_numeric(schedule.institution_count).gt(0).all(), 'AGGREGATE_DECLARED_ROSTER_REQUIRED')
    identity['signal_date'] = pd.to_datetime(identity.signal_date)
    _need(not identity.duplicated(['signal_date','cusip']).any()
          and identity.signal_date.isin(dates).all(), 'AGGREGATE_DATED_IDENTITY_KEYS')
    if 'available_at' in identity:
        for row in identity.itertuples():
            if pd.notna(row.ticker) or pd.notna(row.security_id):
                stamp = pd.Timestamp(row.available_at)
                close = (row.signal_date + pd.Timedelta(hours=16)).tz_localize('America/New_York')
                _need(not pd.isna(stamp) and stamp.tzinfo is not None and stamp <= close, 'AGGREGATE_FUTURE_IDENTITY')
    out_schedule, out_members, ledger, identity_flags = [], [], [], []
    for day in dates:
        close = (day + pd.Timedelta(hours=16)).tz_localize('America/New_York')
        available = schedule.loc[schedule.effective_at.le(close)]
        if available.empty:
            ledger.append(dict(target_date=day, snapshot_id=None))
            continue
        row = available.sort_values(['quarter_order','effective_at']).iloc[-1]
        _need(pd.Period(row.quarter,freq='Q') < pd.Period(day,freq='Q'), 'AGGREGATE_FUTURE_REPORT_PERIOD')
        snapshot = str(row.snapshot_id) + '__' + str(day.date())
        pool = members.loc[members.snapshot_id.eq(row.snapshot_id)].drop(columns=['ticker','security_id'],errors='ignore')
        current = identity.loc[identity.signal_date.eq(day), ['cusip','ticker','security_id']]
        pool = pool.merge(current,on='cusip',how='left',validate='one_to_one')
        mapped = pool.ticker.notna() & pool.security_id.notna()
        _need(not pool.loc[mapped,'ticker'].duplicated().any()
              and not pool.loc[mapped,'security_id'].duplicated().any(), 'AGGREGATE_IDENTITY_COLLISION')
        pool['source_snapshot_id'], pool['snapshot_id'] = row.snapshot_id, snapshot
        out_members.append(pool)
        out_schedule.append(dict(snapshot_id=snapshot,source_snapshot_id=row.snapshot_id,
            universe_id=task_id,quarter=row.quarter,effective_date=str(day.date()),
            snapshot_effective_date=str(day.date()),source_effective_at=row.effective_at,
            universe_member_count=expected_n,mapped_count=int(mapped.sum()),institution_count=int(row.institution_count)))
        if sensitivity:
            out_schedule[-1]['pool_variant_id'] = pool_variant_id
        ledger.append(dict(target_date=day,snapshot_id=snapshot))
        current = identity.loc[identity.signal_date.eq(day)].copy()
        current['is_max_group'] = current.cusip.isin(pool.cusip) & current.ticker.notna() & current.security_id.notna()
        current = current.loc[current.ticker.notna(), ['signal_date','ticker','security_id','is_max_group']]
        _need(not current.duplicated(['signal_date','ticker']).any(), 'AGGREGATE_DATED_TICKER_COLLISION')
        identity_flags.append(current)
    _need(bool(out_members), 'AGGREGATE_NO_AVAILABLE_SNAPSHOT')
    return dict(schedule=pd.DataFrame(out_schedule),members=pd.concat(out_members,ignore_index=True),
        ledger=pd.DataFrame(ledger),dated_identity=pd.concat(identity_flags,ignore_index=True))


def rank_and_flags(features, projection, models, admitted):
    """Score only the 2026 amount pool with the original frozen HGB and flags."""
    admitted = authority.load_descriptive_authority(admitted)
    _need(admitted.task_id in authority.universe_variant_tasks(), 'AGGREGATE_EXACT_TASK_ADMISSION_REQUIRED')
    _need(pd.to_datetime(features.trade_date).ge('2026-01-01').all(),
          'AGGREGATE_RAW_SCORING_2026_ONLY_USE_FROZEN_PROXY_HISTORY')
    authority.validate_descriptive_input_dates(admitted,features.trade_date)
    _need(tuple(models['feature_columns']) == tuple(inputs.FEATURES), 'AGGREGATE_FROZEN_FEATURE_ORDER')
    pinned = {'2025':'2e829c40cad28f85eff145db172a0eeea2d24a9d8f6150cedbd767f3a3aa57b2',
              '2026':authority.RAW_SELECTOR_SHA256}
    years = set(pd.to_datetime(features.trade_date).dt.year.astype(str))
    _need(years <= set(pinned) and all(models['artifacts'].get(y,{}).get('sha256') == pinned[y]
          for y in years), 'AGGREGATE_EXACT_RAW_MODEL_VINTAGES_REQUIRED')
    _need(projection['schedule'].universe_id.eq(admitted.task_id).all(), 'AGGREGATE_PROJECTION_TASK_MISMATCH')
    ranked, coverage = ranking.ranked_predictions(features,projection['schedule'],projection['members'],
        projection['ledger'],models,list(inputs.FEATURES))
    # Preserve the original owner's PARTIAL coverage semantics. Unavailable
    # members remain in the 100-name denominator and are never replaced by 101.
    # Original assemble_flags below still enforces the complete Raw Top20 set.
    _need(np.equal(ranked['rank'],np.floor(ranked['rank'])).all(), 'AGGREGATE_NONINTEGER_RAW_RANK')
    flags = inputs.assemble_flags(features,ranked,projection['dated_identity'])
    return ranked, coverage, flags


def _support(dates, rows):
    counts = rows.groupby('signal_date').size() if len(rows) else pd.Series(dtype=int)
    frame = pd.DataFrame(dict(signal_date=dates,eligible_count=[int(counts.get(d,0)) for d in dates]))
    frame['status'] = np.where(frame.eligible_count.gt(0),'INFERRED','NO_SUPPORT')
    frame['reason'] = np.where(frame.eligible_count.gt(0),'','ORIGINAL_PRODUCER_SUPPORT_MASK_EMPTY')
    return frame


def infer_heads(flags, calendar, bundles, admitted, *, history_flags):
    """Original 2023 pre-test proxy phase persists across all fresh accounts.

    history_flags is the frozen pre2026 causal source; 2025 aggregate-pool
    scores are not a substitute and no random start rebuilds proxy state.
    """
    admitted = authority.load_descriptive_authority(admitted)
    _need(set(bundles) == set(authority.MODEL_IDS), 'AGGREGATE_THREE_FROZEN_HEADS_REQUIRED')
    dates = pd.DatetimeIndex(pd.to_datetime(calendar))
    dates = dates[(dates >= admitted.start) & (dates <= admitted.end)]
    _need(pd.to_datetime(flags.signal_date).ge('2026-01-01').all(),
          'AGGREGATE_TEST_FLAGS_MUST_START_2026')
    samples, audit = inputs.build_proxy_samples(history_flags,flags,calendar,admitted)
    evidence, actions = {}, {}
    for cid in authority.MODEL_IDS[:2]:
        bundle = bundles[cid]
        original = samples[bundle.objective]
        if original.empty:
            original = pd.DataFrame(columns=['signal_date','sample_id','ticker','security_id',*bundle.features])
        else:
            original = original.loc[original.signal_date.isin(dates)].copy()
        # Original producer labels are empty annotations, never inference inputs.
        original = original.drop(columns=list(inference._FORBIDDEN),errors='ignore')
        legal = original.security_id.map(decision._valid_sid).astype(bool)
        ages = ('cohort_age_sessions',) if bundle.objective == 'buy' else ('e_cohort_age_sessions','i_cohort_age_sessions')
        for name in ages:
            legal &= original[name].between(0,20)
        if bundle.objective == 'replace' and not original.empty:
            legal &= original.incumbent_sid.map(decision._valid_sid)
        eligible = original.loc[legal]
        if eligible.empty:
            predicted = pd.DataFrame(columns=['signal_date','sample_id','ticker','security_id','p_superior','model_year'])
        else:
            predicted = inference.predict_r6_frozen(bundle,eligible,admitted)
        perdate = {}
        for order, row in enumerate(predicted.to_dict('records')):
            perdate.setdefault(pd.Timestamp(row['signal_date']),[]).append(decode_r6_row(row,bundle.objective,order))
        actions[cid] = perdate
        evidence[cid] = dict(bundle=bundle,samples=original,predictions=predicted,support=_support(dates,predicted))
    cid = authority.MODEL_IDS[2]
    frame = flags.loc[flags.signal_date.isin(dates)].drop(columns=list(inference._FORBIDDEN),errors='ignore')
    predicted = inference.predict_value_frozen(bundles[cid],frame,admitted)
    evidence[cid] = dict(bundle=bundles[cid],predictions=predicted,
        support=_support(dates,predicted.loc[predicted.prediction_qualified]))
    return dict(inference_evidence=evidence,action_packets=actions,sample_audit=audit)


def assemble_stock_inputs(flags, bars, dates, heads, reference_packet, account, account_source_kwargs):
    """Fill the existing replay schema; caller owns physical source admission.

    reference_packet is the original bound Raw/ridge diagnostic packet, never a
    fabricated substitute. bars requires caller-admitted quality per raw quote.
    """
    dates = pd.DatetimeIndex(pd.to_datetime(dates))
    flags = flags.loc[flags.signal_date.isin(dates)].copy()
    bars = bars.rename(columns={'trade_date':'signal_date'}).copy()
    bars['signal_date'] = pd.to_datetime(bars.signal_date)
    bars = bars.loc[bars.signal_date.isin(dates)]
    _need({'ticker','open','close','quality'} <= set(bars)
          and not bars.duplicated(['signal_date','ticker']).any(), 'AGGREGATE_BOUND_RAW_QUOTE_SCHEMA')
    tickers = sorted(set(flags.ticker.astype(str)) | set(bars.ticker.astype(str)))
    values = replay._old().values
    top = values(flags,dates,tickers,'is_raw_top20',False,bool)
    qualified = values(flags,dates,tickers,'is_max_group',False,bool)
    stock = values(flags,dates,tickers,'stock_forecast_input_present',False,bool)
    raw = values(flags,dates,tickers,'raw_selector_input_present',False,bool)
    union = values(flags,dates,tickers,'decision_information_present_union',False,bool)
    buy = values(flags,dates,tickers,'new_buy_eligible',False,bool)
    _need(np.array_equal(union,stock|raw) and np.array_equal(buy,top&qualified)
          and np.isin(top.sum(axis=1),[0,20]).all(), 'AGGREGATE_ORIGINAL_INFORMATION_BITS')
    vol = np.where(stock,values(flags,dates,tickers,'realized_vol_20d')*np.sqrt(5.),np.nan)
    market = replay.MarketArrays(dates,tickers,values(bars,dates,tickers,'open'),values(bars,dates,tickers,'close'),
        quality=values(bars,dates,tickers,'quality',False,bool),
        row_present=values(bars.assign(present=True),dates,tickers,'present',False,bool),
        input_present=union,new_buy_eligible=buy,
        signal_asof=[(d+pd.Timedelta(hours=16)).tz_localize('America/New_York') for d in dates])
    _need(set(('mu','sigma','lineage')) <= set(reference_packet)
          and np.shape(reference_packet['mu']) == top.shape
          and np.shape(reference_packet['sigma']) == (len(dates),)
          and np.shape(reference_packet['lineage']) == (len(dates),), 'AGGREGATE_ORIGINAL_REFERENCE_PACKET_REQUIRED')
    pred = heads['inference_evidence'][authority.MODEL_IDS[2]]['predictions']
    pred = pred.loc[pred.prediction_qualified & pred.signal_date.isin(dates)]
    sigma = np.full(len(dates),np.nan)
    for i,d in enumerate(dates):
        sigmas = pred.loc[pred.signal_date.eq(d),'value_sigma'].unique()
        _need(len(sigmas) <= 1, 'AGGREGATE_ORIGINAL_COMMON_SIGMA_CHANGED')
        if len(sigmas): sigma[i] = sigmas[0]
    ngboost = dict(mu=np.where(stock,values(pred,dates,tickers,'prediction'),np.nan),sigma=sigma,
        lineage=np.full(len(dates),authority.MODEL_SHA256[authority.MODEL_IDS[2]],dtype=object))
    return dict(market=market,top=top,qualified=qualified,stock_present=stock,raw_selector_present=raw,
        vol=vol,packets={'ridge':deepcopy(reference_packet),'ngboost':ngboost},account=deepcopy(account),
        account_source_kwargs=deepcopy(account_source_kwargs),
        sid_by_key={(pd.Timestamp(r.signal_date),str(r.ticker)):r.security_id for r in flags.itertuples()},
        action_packets=heads['action_packets'],inference_evidence=heads['inference_evidence'])


def assemble_six_path_inputs(window, admitted, *, flags, bars, calendar, account,
                             account_source_kwargs_by_group, heads):
    """Reuse the six-path provider and preserve admitted per-quote bad flags.

    Build once for MAIN; slice_account_inputs supplies fresh random accounts
    without rebuilding the exogenous proxy or predicting any head again.
    """
    from dataclasses import replace
    admitted = authority.load_descriptive_authority(admitted)
    _need(admitted.task_id in authority.universe_variant_tasks(), 'AGGREGATE_EXACT_TASK_ADMISSION_REQUIRED')
    benchmark_ids = authority.PATH_IDS[4:]
    benchmark_tickers = [cid.split('_',1)[0] for cid in benchmark_ids]
    _need(not flags.ticker.isin(benchmark_tickers).any(), 'AGGREGATE_BENCHMARK_NOT_STOCK_POOL')
    quotes = bars.rename(columns={'trade_date':'signal_date'}).copy()
    quotes['signal_date'] = pd.to_datetime(quotes.signal_date)
    quotes = quotes.loc[quotes.signal_date.between(admitted.start,admitted.end)]
    _need({'ticker','open','close','quality'} <= set(quotes)
          and not quotes.duplicated(['signal_date','ticker']).any()
          and pd.api.types.is_bool_dtype(quotes.quality)
          and not quotes.quality.isna().any(), 'AGGREGATE_BOUND_RAW_QUOTE_SCHEMA')
    groups = {'stocks':quotes.loc[~quotes.ticker.isin(benchmark_tickers)]}
    groups.update({cid:quotes.loc[quotes.ticker.eq(ticker)]
                   for cid,ticker in zip(benchmark_ids,benchmark_tickers)})
    values = replay._old().values
    templates = inputs.window_inputs(window,admitted,flags=flags,stock_bars=groups['stocks'],
        etf_bars={ticker:groups[cid] for cid,ticker in zip(benchmark_ids,benchmark_tickers)},
        calendar=calendar,account=account,account_source_kwargs_by_group=account_source_kwargs_by_group,
        model_evidence=heads['inference_evidence'],values_function=values)
    for group,template in templates.items():
        market = template['market']
        quote = groups[group]
        present = values(quote.assign(present=True),market.dates,market.tickers,'present',False,bool)
        _need(np.array_equal(market.row_present,present), 'AGGREGATE_PROVIDER_QUOTE_ROWS_CHANGED')
        template['market'] = replace(market,quality=values(quote,market.dates,market.tickers,'quality',False,bool))
    return templates


def slice_account_inputs(full, window, admitted, *, account_source_kwargs):
    """Fresh account window with inherited frozen inference and proxy context.

    Corporate-action subsets/bindings must be supplied by their source owner for
    this window. No inherited holdings/claims/pending orders are copied here.
    """
    from dataclasses import replace
    admitted = authority.load_descriptive_authority(admitted)
    market = full['market']
    start, end = pd.Timestamp(window['start']), pd.Timestamp(window['end'])
    _need(start == admitted.start and end == admitted.end, 'AGGREGATE_WINDOW_AUTHORITY_MISMATCH')
    select = (market.dates >= start) & (market.dates <= end)
    dates = market.dates[select]
    _need(len(dates) >= 2 and dates[0] == start and dates[-1] == end
          and str(dates[1].date()) == window['first_execution_date'], 'AGGREGATE_WINDOW_CALENDAR_MISMATCH')
    names = ('open','close','quality','adv','input_present','new_buy_eligible','row_present',
             'buy_restricted','sell_restricted','signal_mask')
    fields = {name:np.asarray(getattr(market,name))[select].copy() for name in names}
    fields['signal_asof'] = [s for s,keep in zip(market.signal_asof,select) if keep]
    fields['operational_exits'] = {d:v for d,v in market.operational_exits.items() if d in dates}
    restriction = market.known_restrictions_evidence
    if restriction is not None:
        restriction = pd.DataFrame(restriction)
        fields['known_restrictions_evidence'] = restriction.loc[pd.to_datetime(restriction.signal_date).isin(dates)].copy()
    result = dict(market=replace(market,dates=dates,**fields),account=deepcopy(full['account']),
        account_source_kwargs=deepcopy(account_source_kwargs))
    if 'packets' not in full:
        return result
    for key in ('top','qualified','vol','stock_present','raw_selector_present'):
        result[key] = np.asarray(full[key])[select].copy()
    result['packets'] = {name:{key:(np.asarray(value)[select].copy() if key in ('mu','sigma','lineage') else deepcopy(value))
        for key,value in packet.items()} for name,packet in full['packets'].items()}
    result['sid_by_key'] = {key:value for key,value in full['sid_by_key'].items() if key[0] in dates}
    result['action_packets'] = {cid:{d:deepcopy(rows) for d,rows in packet.items() if d in dates}
        for cid,packet in full['action_packets'].items()}
    result['inference_evidence'] = {}
    for cid,evidence in full['inference_evidence'].items():
        item = dict(evidence)
        for name in ('samples','predictions','support'):
            if isinstance(item.get(name),pd.DataFrame):
                item[name] = item[name].loc[pd.to_datetime(item[name].signal_date).isin(dates)].copy()
        result['inference_evidence'][cid] = item
    return result


def raw_diagnostic_packet(dates, tickers):
    """No forecast for fixed-gross Raw/R6 paths; never represented as ridge output.

    The inherited packet slot is named ridge by the frozen policy schema. Its
    fixed Raw branch never consumes forecast utility; all fields are explicitly
    unavailable and no fourth model is fitted or inferred.
    """
    return dict(mu=np.full((len(dates),len(tickers)),np.nan),sigma=np.full(len(dates),np.nan),
        lineage=np.full(len(dates),'NOT_APPLICABLE_RAW_BRANCH_NO_VALUE_FORECAST',dtype=object))


def map_source_pool(schedule, members, frozen_members, calendar, frozen_ref, *, source_ref):
    """Keep aggregate holding provenance distinct from dated identity evidence."""
    from scripts.research.a2.inference import historical_top40_universe as owner
    versions=[]
    for row in schedule.itertuples():
        effective=pd.Timestamp(row.effective_at).tz_convert('America/New_York').tz_localize(None).normalize()
        versions.append(dict(quarter=row.quarter,effective_date=effective,
            snapshot_effective_date=effective,institution_count=int(row.institution_count),
            source_snapshot_id=row.snapshot_id,source_sha256=source_ref['sha256'],
            frame=members.loc[members.snapshot_id.eq(row.snapshot_id)].drop(columns=['snapshot_id']),
            universe_id=row.snapshot_id))
    return owner._assemble(versions,frozen_members,pd.DatetimeIndex(calendar),'registry25',
        {'frozen_members':frozen_ref,'aggregate_source':source_ref})


def append_new_raw_sessions(original, current, sessions, *, ticker, source_refs):
    """Preserve the bound prefix; append newly observed sessions in its RAW units.

    A later snapshot's overlap is diagnostic and never revises the prefix. Each
    overlap row must pin the same price coordinate through an exactly identical
    positive OHLC field, with at least five entirely identical OHLCV rows. The
    explicitly native whole-share volume schema must hold in both snapshots.
    No tolerance, rescaling or source-wide equivalence is granted here.
    """
    from scripts.research.a2.inference import historical_top40_prices as owner
    fields = ['open','high','low','close','volume']
    left, right = original.copy(), current.copy()
    for frame in (left,right):
        frame['trade_date'] = pd.to_datetime(frame.trade_date)
        _need(not frame.trade_date.duplicated().any()
              and frame.trade_date.is_monotonic_increasing
              and np.isfinite(frame[fields].to_numpy(float)).all()
              and frame.volume.ge(0).all() and frame.volume.mod(1).eq(0).all(),
              'RAW_NATIVE_WHOLE_SHARE_SCHEMA_UNBOUND')
    joined = left.merge(right,on='trade_date',suffixes=('_prefix','_current'),validate='one_to_one')
    equal = np.column_stack([joined[f+'_prefix'].eq(joined[f+'_current']) for f in fields])
    _need(len(joined)>=5 and equal.all(axis=1).sum()>=5,
          'RAW_OVERLAP_FIVE_EXACT_ROWS_REQUIRED')
    _need(equal[:,:4].any(axis=1).all()
          and (joined[[f+'_prefix' for f in fields[:4]]]>0).all().all(),
          'RAW_PRICE_COORDINATE_CONFLICT')
    conflicts=[]
    for index,row in enumerate(joined.to_dict('records')):
        if not equal[index].all():
            conflicts.append(dict(trade_date=str(pd.Timestamp(row['trade_date']).date()),
                fields={f:dict(prefix=float(row[f+'_prefix']),current=float(row[f+'_current']))
                        for k,f in enumerate(fields) if not equal[index,k]}))
    cutoff=left.trade_date.max()
    tail=right.loc[right.trade_date.gt(cutoff),['trade_date',*fields]].copy()
    merged=owner._append_raw(left,tail,pd.DatetimeIndex(sessions))
    _need(left.reset_index(drop=True).equals(merged.loc[merged.trade_date.le(cutoff)].reset_index(drop=True)),
          'RAW_PREFIX_MUTATED')
    proof=dict(ticker=ticker,selection='NEW_SESSIONS_ONLY',preserve_parent_prefix=True,
        prefix_cutoff=str(cutoff.date()),source_refs=deepcopy(source_refs),
        overlap_rows=len(joined),exact_ohlcv_overlap_rows=int(equal.all(axis=1).sum()),
        overlap_coordinate_by_day=[dict(trade_date=str(pd.Timestamp(day).date()),
            exact_ohlcv_fields=[field for k,field in enumerate(fields) if equal[index,k]])
            for index,day in enumerate(joined.trade_date)],
        every_overlap_row_has_exact_positive_price_coordinate=True,
        volume_unit='NATIVE_WHOLE_SHARES_BOTH_SOURCES',overlap_conflicts=conflicts,
        full_snapshot_equivalence_claimed=False,tail_rows=len(tail))
    return merged,tail,proof
