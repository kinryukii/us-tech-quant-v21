"""Read-only reconstruction of actual-state score -> target -> execution evidence.

No model import/prediction/fit, no trading replay, no search, no changed inputs.
Every output lives below this script's bridge directory.
"""
from pathlib import Path
import hashlib
import json
import math
import time
import numpy as np
import pandas as pd

OUT=Path(__file__).resolve().parent
ROOT=OUT.parent.parent
WS=ROOT.parent
BASES=('ridge','elastic_net','logistic','hgb','q50','mlp')
ACTIONS=np.array([0.,.025,.05,.075,.1])
KEY=['signal_date','ticker']
LEDGERS=['raw_model_outputs','target_decisions','signal_contexts','operational_actions',
         'execution_results','trades','positions','daily']
INPUTS={}


def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def record(path):
    path=Path(path);INPUTS[str(path)]=sha(path);return path


def read_json(path):return json.loads(record(path).read_text(encoding='utf-8'))


def read_frame(path,**kwargs):return pd.read_parquet(record(path),**kwargs)


def dump(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str,allow_nan=False),encoding='utf-8')


def unique(frame,keys,name):
    if frame.duplicated(keys).any():raise AssertionError(f'DUPLICATE_{name}:{keys}')


def checked_merge(left,right,on,how='left',validate='one_to_one'):
    rows=len(left)
    result=left.merge(right,on=on,how=how,validate=validate)
    if how=='left' and len(result)!=rows:raise AssertionError('JOIN_ROW_INFLATION')
    return result


def distinct(values):return '|'.join(dict.fromkeys(str(x) for x in values if pd.notna(x)))


def source_tables(year):
    if year==2025:
        fp=WS/'a2_latest_effective_joint_20260927/data/pre2026_joint_context.parquet'
        pp=WS/'a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet'
        quarter='active_13f_quarter'
    else:
        fp=WS/'a2_qualification_holdings_v1_20260927/data/test_features_context.parquet'
        pp=WS/'a2_qualification_holdings_v1_20260927/data/test_prices.parquet'
        quarter='quarter'
    feature=read_frame(fp,columns=['signal_date','ticker','new_buy_eligible','avg_dollar_volume_20d',quarter])
    feature=feature.loc[feature.signal_date.dt.year.eq(year)].copy()
    feature.rename(columns={quarter:'source_13f_quarter','avg_dollar_volume_20d':'source_signal_adv'},inplace=True)
    feature['feature_row_present']=True
    prices=read_frame(pp)
    prices=prices.loc[prices.trade_date.dt.year.eq(year)].copy()
    if 'price_quality_warning' not in prices:prices['price_quality_warning']=False
    if 'price_qualification_reason' not in prices:prices['price_qualification_reason']='ORIGINAL_PRE2026_COORDINATE_NO_INDEPENDENT_CERTIFICATION'
    prices=prices[['trade_date','ticker','open','close','price_quality_warning','price_qualification_reason']]
    unique(feature,KEY,'FEATURE');unique(prices,['trade_date','ticker'],'PRICE')
    return feature,prices


def expand_raw(raw,contexts,targets,operations,policy,year,coefficients):
    unique(raw,['signal_date'],'RAW');unique(contexts,['signal_date'],'CONTEXT')
    assert set(raw.signal_date)==set(contexts.signal_date)
    context={r.signal_date:r for r in contexts.itertuples()}
    extras={date:set(g.ticker) for date,g in targets.groupby('signal_date',sort=False)}
    for date,g in operations.groupby('signal_date',sort=False):extras.setdefault(date,set()).update(g.ticker)
    rows=[];fused_errors=[];raw_decision_errors=[]
    for r in raw.itertuples():
        c=context[r.signal_date]
        original=set(json.loads(r.original_input_tickers_json))
        decision=set(json.loads(r.decision_input_tickers_json))
        weights=json.loads(r.model_decisions_json)
        outputs=json.loads(r.raw_model_outputs_json or '{}') or {}
        units=json.loads(c.current_units_json)
        current=json.loads(c.current_weights_json or '{}')
        reserved=set(json.loads(c.final_reserved_tickers_json))
        universe=sorted(original|decision|set(weights)|set(outputs)|set(units)|extras.get(r.signal_date,set()))
        glw_day=year==2026 and r.signal_date==pd.Timestamp('2026-02-26')
        for ticker in universe:
            item=outputs.get(ticker,{})
            row=dict(year=year,policy=policy,signal_date=r.signal_date,ticker=ticker,
                state_basis='ACTUAL_ACCOUNT_AT_ORIGINAL_SIGNAL',original_input_present=ticker in original,
                decision_input_present=ticker in decision,raw_model_score_present=bool(item),
                raw_decision_present=ticker in weights,raw_chosen_weight=weights.get(ticker,np.nan),
                signal_current_units=units.get(ticker,0.),signal_current_weight=current.get(ticker,0.),
                signal_cash=c.cash,signal_nav=c.nav,signal_cash_weight=c.cash_weight,
                signal_reserved=ticker in reserved,reserved_slots=c.final_reserved_slots,
                reserved_weight=c.final_reserved_weight,available_slots=c.final_available_slots,
                available_weight=c.final_available_weight,account_active_target_count=c.active_target_count,
                account_active_target_weight=c.active_target_weight,
                signal_implied_cash_weight=1-c.final_reserved_weight-c.active_target_weight,
                known_glw_input_conflict=glw_day and ticker=='GLW' and ticker in decision,
                same_day_glw_in_decision_input=glw_day and 'GLW' in decision,
                same_day_glw_score_present=glw_day and bool(outputs.get('GLW',{})),
                actual_score_5pct_vs_exit=np.nan,score_provenance='NO_RECORDED_SCORE',
                score_action0=np.nan,score_action5pct=np.nan,max_action_advantage=np.nan,
                unconstrained_best_action=np.nan,raw_projected_weight=np.nan,
                base_rank_mean_5pct=np.nan,base_rank_std_5pct=np.nan,q10_downside_rank_5pct=np.nan,
                disagreement_penalty_5pct=0.,downside_penalty_5pct=0.)
            values=None
            if 'fused_action_values' in item:
                values=np.asarray(item['fused_action_values'],float)
                rank=np.array([item['base_rank_advantages'][name][2] for name in BASES])
                row['score_provenance']='RECORDED_ACTUAL_STATE_FUSED_ACTION_ADVANTAGE'
                row['base_rank_mean_5pct']=float(rank.mean())
                row['base_rank_std_5pct']=float(rank.std())
                row['q10_downside_rank_5pct']=float(item['q10_downside_rank'][2])
                if policy=='ensemble_stacking':coef=np.array([coefficients[name] for name in BASES])
                else:coef=np.repeat(1/6,6)
                if policy=='ensemble_disagreement':
                    row['disagreement_penalty_5pct']=.25*rank.std()
                    row['downside_penalty_5pct']=.25*row['q10_downside_rank_5pct']
                for index,name in enumerate(BASES):
                    base=item['base_action_values'][name]
                    row[f'base_{name}_raw_advantage_5pct']=float(base[2]-base[0])
                    row[f'base_{name}_rank_5pct']=float(rank[index])
                    row[f'base_{name}_contribution_5pct']=float(rank[index]*coef[index])
                expected=float(rank@coef-row['disagreement_penalty_5pct']-row['downside_penalty_5pct'])
                fused_errors.append(abs(expected-(values[2]-values[0])))
                row['raw_projected_weight']=item.get('mlp_projected_weight',np.nan)
            elif 'action_values' in item:
                values=np.asarray(item['action_values'],float)
                row['score_provenance']=('RECORDED_BASE_VALUE_BEFORE_PORTFOLIO_RISK_LAYER'
                    if policy in ('joint_hgb_lw','joint_hgb_pca') else 'RECORDED_ACTUAL_STATE_ACTION_ADVANTAGE')
            elif 'projected_weight' in item:
                projected=float(item['projected_weight'])
                values=-((ACTIONS-projected)/.1)**2
                row['raw_projected_weight']=projected
                row['neural_logits_json']=json.dumps(item.get('logits',[]),separators=(',',':'))
                row['score_provenance']='ORIGINAL_NEURAL_PROJECTED_WEIGHT_MAPPED_TO_5PCT_VS_0_PREFERENCE'
            elif policy=='cash_control':row['score_provenance']='CASH_CONTROL_HAS_NO_RANKING'
            if values is not None:
                assert values.shape==(5,) and np.isfinite(values).all()
                row.update(score_action0=float(values[0]),score_action5pct=float(values[2]),
                    actual_score_5pct_vs_exit=float(values[2]-values[0]),
                    max_action_advantage=float((values-values[0]).max()),
                    unconstrained_best_action=float(ACTIONS[np.argmax(values)]))
                if 'chosen_weight' in item and ticker in weights:
                    raw_decision_errors.append(abs(item['chosen_weight']-weights[ticker]))
            rows.append(row)
    frame=pd.DataFrame(rows)
    unique(frame,KEY,'EXPANDED_RAW')
    assert max(fused_errors,default=0.)<1e-10
    assert max(raw_decision_errors,default=0.)<1e-8
    ranked=frame.loc[frame.actual_score_5pct_vs_exit.notna()].sort_values(
        ['signal_date','actual_score_5pct_vs_exit','ticker'],ascending=[True,False,True],kind='stable').copy()
    ranked['actual_state_rank']=ranked.groupby('signal_date',sort=False).cumcount()+1
    frame=checked_merge(frame,ranked[KEY+['actual_state_rank']],KEY)
    frame['actual_state_top20']=frame.actual_state_rank.le(20)
    return frame,dict(fusion_reconstruction_max_abs_error=max(fused_errors,default=0.),
        raw_chosen_weight_max_abs_error=max(raw_decision_errors,default=0.),raw_universe_rows=len(frame))


def aggregate_events(events):
    if events.empty:return pd.DataFrame(columns=KEY+['execution_event_count','execution_statuses','execution_reasons','has_recorded_rejection','has_recorded_partial'])
    groups={}
    for r in events.itertuples():
        key=(r.signal_date,r.ticker)
        if key not in groups:
            groups[key]=dict(signal_date=r.signal_date,ticker=r.ticker,execution_event_count=0,
                statuses=[],reasons=[],has_recorded_rejection=False,has_recorded_partial=False,details=[])
        g=groups[key];g['execution_event_count']+=1
        g['statuses'].append(r.status);g['reasons'].append(r.reason)
        g['has_recorded_rejection']|=r.status=='REJECTED'
        g['has_recorded_partial']|=r.status=='PARTIALLY_FILLED'
        g['details'].append(dict(status=r.status,reason=r.reason,side=r.side,notional=r.notional,
            index_units=r.index_units,transaction_cost=r.transaction_cost))
    for g in groups.values():
        g['execution_statuses']='|'.join(dict.fromkeys(g.pop('statuses')))
        g['execution_reasons']='|'.join(dict.fromkeys(g.pop('reasons')))
        g['execution_event_details_json']=json.dumps(g.pop('details'),separators=(',',':'))
    result=pd.DataFrame(groups.values());unique(result,KEY,'AGGREGATED_EVENTS');return result


def aggregate_trades(trades):
    columns=KEY+['buy_notional','sell_notional','recorded_cost','buy_units','sell_units','trade_count',
                 'first_trade_units_before','last_trade_units_after','trade_sides','capacity_enforced_all_buys','capacity_adv','capacity_adv_source_date']
    if trades.empty:return pd.DataFrame(columns=columns)
    rows=[]
    for (date,ticker),g in trades.groupby(KEY,sort=False):
        buy=g.loc[g.side.eq('BUY')];sell=g.loc[g.side.eq('SELL')]
        rows.append(dict(signal_date=date,ticker=ticker,buy_notional=float(buy.notional.sum()),
            sell_notional=float(sell.notional.sum()),recorded_cost=float(g.transaction_cost.sum()),
            buy_units=float(buy.index_units.sum()),sell_units=float(sell.index_units.sum()),trade_count=len(g),
            first_trade_units_before=float(g.iloc[0].index_units_before),
            last_trade_units_after=float(g.iloc[-1].index_units_after),trade_sides=distinct(g.side),
            capacity_enforced_all_buys=bool(buy.capacity_enforced.all()) if len(buy) else None,
            capacity_adv=float(buy.iloc[0].capacity_adv) if len(buy) else np.nan,
            capacity_adv_source_date=buy.iloc[0].capacity_adv_source_date if len(buy) else pd.NaT))
    result=pd.DataFrame(rows);unique(result,KEY,'AGGREGATED_TRADES');return result


def classify(row):
    target=row.target_weight
    highzero=bool(row.actual_state_top20 and pd.notna(target) and target<=1e-12)
    cause='NOT_APPLICABLE'
    if pd.notna(target) and target<=1e-12:
        if row.target_adaptation_reasons:
            cause='RECORDED_TARGET_ADAPTATION:'+row.target_adaptation_reasons
        elif row.operational_reason:
            cause='RECORDED_OPERATIONAL_EXIT'
        elif not row.decision_input_present:
            cause='NO_DECISION_INPUT_REASON_NOT_FULLY_RECORDED'
        elif row.available_slots<=0 or row.available_weight<=0:
            cause='OBSERVED_NO_AVAILABLE_SLOT_OR_CAPITAL'
        elif row.signal_current_units<=1e-12 and ((pd.notna(row.new_buy_eligible) and not bool(row.new_buy_eligible)) or not row.signal_close_gate_available):
            cause='OBSERVED_BUY_INELIGIBILITY_OR_CLOSE_GATE'
        elif row.score_provenance.startswith('ORIGINAL_NEURAL'):
            cause='NEURAL_ZERO_PROJECTION_COMPONENT_CAUSE_NOT_RECORDED'
        elif row.max_action_advantage<=1e-12:
            cause='RECORDED_NO_POSITIVE_ACTION_ADVANTAGE'
        else:
            cause='UNKNOWN_OPTIMIZER_ACTION_COMPETITION_OR_RISK_BINDING'
    if not row.target_record_present:
        execution='NO_TARGET_RECORD_NOT_A_REJECTION'
    elif row.target_order_type=='HOLD_UNITS':
        execution='PRESERVED_EXISTING_UNITS'
    elif row.has_recorded_rejection:
        execution='RECORDED_REJECTION_WITH_FILL' if row.trade_count else 'RECORDED_REJECTION_NO_FILL'
    elif row.trade_count:
        execution=('FILLED_WITH_RECONSTRUCTED_BUY_CAPACITY_LIMIT' if row.reconstructed_capacity_limited
                   else 'FILLED_WITH_RECORDED_CASH_SCALING' if row.cash_scaling_applied else 'FILLED')
    elif 'NO_ACTION' in row.execution_statuses:
        execution='RECORDED_NO_ACTION_TARGET_ALREADY_MET_OR_NO_POSITION'
    elif not row.execution_event_count:
        execution='NO_RECORDED_EXECUTION_EVENT_UNKNOWN'
    else:execution='OTHER_RECORDED_EXECUTION_EVENT'
    return highzero,cause,execution


def build_path(year,policy,features,prices):
    folder=ROOT/f'evaluation_{year}/cost_10'/policy
    data={name:read_frame(folder/f'{name}.parquet') for name in LEDGERS}
    metadata=read_json(folder/'metadata.json');done=read_json(folder/'DONE.json')
    targets=data['target_decisions'];ops=data['operational_actions'];daily=data['daily'];trades=data['trades'];positions=data['positions']
    for frame,name in [(targets,'TARGET'),(ops,'OPS')]:unique(frame,KEY,name)
    unique(daily,['date'],'DAILY');unique(positions,['date','ticker'],'POSITIONS')
    assert not metadata['initial_positions'] and metadata['initial_cash']==1e6
    coefficients=read_json(ROOT/f'ensemble_artifacts/{"validation" if year==2025 else "final"}_TRAIN_RECEIPT.json')['coefficients'] if policy=='ensemble_stacking' else {}
    bridge,checks=expand_raw(data['raw_model_outputs'],data['signal_contexts'],targets,ops,policy,year,coefficients)
    next_session=dict(zip(daily.date.iloc[:-1],daily.date.iloc[1:]))
    bridge['execution_date']=bridge.signal_date.map(next_session)
    columns={'order_type':'target_order_type','decision_semantic':'target_semantic',
        'adapted_target_weight':'target_weight','hold_units':'target_hold_units',
        'adaptation_reasons':'target_adaptation_reasons','signal_reservation_reasons':'target_reservation_reasons',
        'status':'target_record_status','raw_model_weight':'target_record_raw_weight'}
    selected=targets[KEY+list(columns)].rename(columns=columns).copy();selected['target_record_present']=True
    bridge=checked_merge(bridge,selected,KEY)
    bridge=checked_merge(bridge,features,KEY)
    if len(ops):
        selected=ops[KEY+['reason','known_at','source_id']].rename(columns={'reason':'operational_reason','known_at':'operational_known_at','source_id':'operational_source_id'})
        bridge=checked_merge(bridge,selected,KEY)
    else:bridge['operational_reason']=''
    bridge=checked_merge(bridge,aggregate_events(data['execution_results']),KEY)
    bridge=checked_merge(bridge,aggregate_trades(trades),KEY)
    for col in ['target_record_present','feature_row_present','has_recorded_rejection','has_recorded_partial']:
        bridge[col]=bridge[col].fillna(False).astype(bool)
    for col in ['execution_event_count','trade_count','buy_notional','sell_notional','recorded_cost','buy_units','sell_units']:
        bridge[col]=bridge[col].fillna(0)
    for col in ['target_adaptation_reasons','target_reservation_reasons','operational_reason','execution_statuses','execution_reasons']:
        bridge[col]=bridge[col].fillna('')
    px=prices.rename(columns={'trade_date':'signal_date','open':'signal_open','close':'signal_close',
        'price_quality_warning':'signal_original_price_warning','price_qualification_reason':'signal_original_price_qualification'})
    bridge=checked_merge(bridge,px,KEY,validate='many_to_one')
    px=prices.rename(columns={'trade_date':'execution_date','open':'execution_open','close':'execution_close',
        'price_quality_warning':'execution_original_price_warning','price_qualification_reason':'execution_original_price_qualification'})
    bridge=checked_merge(bridge,px,['execution_date','ticker'],validate='many_to_one')
    bridge['signal_close_gate_available']=bridge.signal_close.gt(0)&np.isfinite(bridge.signal_close)&~bridge.signal_original_price_warning.fillna(True).astype(bool)
    bridge['execution_open_gate_available']=bridge.execution_open.gt(0)&np.isfinite(bridge.execution_open)&~bridge.execution_original_price_warning.fillna(True).astype(bool)
    conflict_dates=[pd.Timestamp('2026-02-26'),pd.Timestamp('2026-02-27')]
    bridge['known_signal_price_date_conflict']=bridge.ticker.eq('GLW')&bridge.signal_date.isin(conflict_dates)
    bridge['known_execution_price_date_conflict']=bridge.ticker.eq('GLW')&bridge.execution_date.isin(conflict_dates)
    bridge['signal_price_status']=np.select([bridge.known_signal_price_date_conflict,~bridge.signal_close_gate_available],
        ['KNOWN_GLW_EVENT_DATE_CONFLICT','UNAVAILABLE_BY_ORIGINAL_GATE'],default='ORIGINAL_GATE_AVAILABLE_NOT_INDEPENDENTLY_CERTIFIED')
    pdict={'index_units':'post_units','weight':'post_weight','market_value':'post_market_value','mark':'post_mark',
        'mark_date':'post_mark_date','mark_source':'post_mark_source','stale':'post_stale','unknown':'post_unknown','current_close_reason':'post_close_reason'}
    post=positions[['date','ticker',*pdict]].rename(columns={'date':'execution_date',**pdict})
    post['post_position_record_present']=True
    bridge=checked_merge(bridge,post,['execution_date','ticker'],validate='many_to_one')
    bridge['post_position_record_present']=bridge.post_position_record_present.fillna(False).astype(bool)
    for col in ['post_units','post_market_value','post_weight']:
        # Missing position means zero; a present position with unknown valuation stays unknown.
        bridge.loc[~bridge.post_position_record_present,col]=0.
    ddict={'date':'execution_date','cash':'execution_cash','nav':'execution_nav','cash_weight':'execution_cash_weight',
        'pretrade_nav':'execution_pretrade_nav','valuation_status':'execution_account_valuation_status',
        'buy_cash_scale':'execution_buy_cash_scale','transaction_cost_amount':'execution_account_cost'}
    bridge=checked_merge(bridge,daily[list(ddict)].rename(columns=ddict),['execution_date'],validate='many_to_one')
    bridge['known_post_mark_conflict']=bridge.ticker.eq('GLW')&bridge.post_mark_date.isin(conflict_dates)
    bridge['post_price_status']=np.select([~bridge.post_position_record_present,bridge.known_post_mark_conflict,
        bridge.post_unknown.fillna(False).astype(bool),bridge.post_stale.fillna(False).astype(bool)],
        ['NO_POSITION','KNOWN_GLW_EVENT_DATE_CONFLICT','UNKNOWN_MARK','STALE_MARK'],default='ORIGINAL_LEDGER_CURRENT_MARK_NOT_SHAREHOLDER_CERTIFICATION')
    active=bridge.target_record_present&bridge.target_order_type.ne('HOLD_UNITS')&bridge.execution_open_gate_available
    desired=bridge.target_weight*bridge.execution_pretrade_nav
    opening=bridge.signal_current_units*bridge.execution_open
    bridge['reconstructed_requested_buy_notional']=np.where(active,np.maximum(desired-opening,0.),np.nan)
    bridge['signal_adv_buy_cap']=bridge.source_signal_adv*.01
    bridge['reconstructed_capacity_limited']=bridge.buy_notional.gt(0)&(bridge.reconstructed_requested_buy_notional>bridge.signal_adv_buy_cap+1e-6)
    bridge['cash_scaling_applied']=bridge.buy_notional.gt(0)&bridge.execution_buy_cash_scale.lt(1-1e-12)
    bridge['reconstructed_expected_buy_notional']=np.where(bridge.buy_notional.gt(0),
        np.minimum(bridge.reconstructed_requested_buy_notional,bridge.signal_adv_buy_cap)*bridge.execution_buy_cash_scale,np.nan)
    checks['buy_fill_reconstruction_max_abs_error']=float((bridge.loc[bridge.buy_notional.gt(0),'buy_notional']-
        bridge.loc[bridge.buy_notional.gt(0),'reconstructed_expected_buy_notional']).abs().max()) if bridge.buy_notional.gt(0).any() else 0.
    assert checks['buy_fill_reconstruction_max_abs_error']<1e-5
    bridge['reconstructed_unfilled_buy_notional']=np.where(bridge.buy_notional.gt(0),np.maximum(
        bridge.reconstructed_requested_buy_notional-bridge.buy_notional,0.),np.nan)
    bridge['no_target_is_not_rejection']=~bridge.target_record_present&~bridge.has_recorded_rejection
    classification=[classify(r) for r in bridge.itertuples()]
    bridge[['high_rank_zero_target','zero_target_explanation','execution_explanation']]=pd.DataFrame(classification,index=bridge.index)
    bridge['positive_target_no_trade']=bridge.target_weight.gt(0)&bridge.trade_count.eq(0)&bridge.target_order_type.ne('HOLD_UNITS')
    bridge['held_without_decision_input']=bridge.signal_current_units.gt(0)&~bridge.decision_input_present
    # Strict aggregate checks: all source records represented once after many-to-one joins.
    checks.update(target_source_rows=len(targets),target_bridge_rows=int(bridge.target_record_present.sum()),
        execution_source_events=len(data['execution_results']),execution_bridge_events=int(bridge.execution_event_count.sum()),
        trade_source_rows=len(trades),trade_bridge_rows=int(bridge.trade_count.sum()),
        buy_notional_error=abs(float(bridge.buy_notional.sum()-trades.loc[trades.side.eq('BUY'),'notional'].sum())),
        sell_notional_error=abs(float(bridge.sell_notional.sum()-trades.loc[trades.side.eq('SELL'),'notional'].sum())),
        recorded_cost_error=abs(float(bridge.recorded_cost.sum()-trades.transaction_cost.sum())))
    assert checks['target_source_rows']==checks['target_bridge_rows']
    assert checks['execution_source_events']==checks['execution_bridge_events']
    assert checks['trade_source_rows']==checks['trade_bridge_rows']
    assert max(checks['buy_notional_error'],checks['sell_notional_error'],checks['recorded_cost_error'])<1e-6
    checks['units_from_signal_plus_trades_error']=float((bridge.signal_current_units+bridge.buy_units-bridge.sell_units-bridge.post_units).abs().max())
    assert checks['units_from_signal_plus_trades_error']<1e-7
    byday=bridge.groupby('execution_date',sort=True).agg(post_mv=('post_market_value','sum'),fees=('recorded_cost','sum'),
        buy=('buy_notional','sum'),sell=('sell_notional','sum'))
    account=daily.set_index('date').loc[byday.index]
    checks['daily_positions_nav_error']=float((byday.post_mv+account.cash-account.nav).abs().max())
    checks['daily_recorded_cost_error']=float((byday.fees-account.transaction_cost_amount).abs().max())
    before_cash=bridge.groupby('execution_date').signal_cash.first()
    checks['daily_cash_flow_error']=float((before_cash+byday.sell-byday.buy-byday.fees-account.cash).abs().max())
    assert max(checks['daily_positions_nav_error'],checks['daily_recorded_cost_error'],checks['daily_cash_flow_error'])<1e-5
    unique(bridge,KEY,'FINAL_BRIDGE')
    bridge=bridge.sort_values(KEY,kind='stable').reset_index(drop=True)
    destination=OUT/f'actual_account_bridge_{year}_{policy}.parquet'
    bridge.to_parquet(destination,index=False,compression='zstd')
    path_summary=dict(year=year,policy=policy,rows=len(bridge),signals=int(bridge.signal_date.nunique()),
        scored_rows=int(bridge.actual_score_5pct_vs_exit.notna().sum()),zero_target_rows=int(bridge.target_weight.eq(0).sum()),
        high_rank_zero_target=int(bridge.high_rank_zero_target.sum()),
        high_rank_zero_reasons=bridge.loc[bridge.high_rank_zero_target,'zero_target_explanation'].value_counts().to_dict(),
        positive_target_no_trade=int(bridge.positive_target_no_trade.sum()),
        positive_target_no_trade_reasons=bridge.loc[bridge.positive_target_no_trade,'execution_explanation'].value_counts().to_dict(),
        rejected_rows=int(bridge.has_recorded_rejection.sum()),no_target_rows=int((~bridge.target_record_present).sum()),
        capacity_limited_fills=int(bridge.reconstructed_capacity_limited.sum()),cash_scaled_fills=int(bridge.cash_scaling_applied.sum()),
        held_without_decision_input=int(bridge.held_without_decision_input.sum()),recorded_cost_dollars=float(bridge.recorded_cost.sum()),
        source_recorded_cost_dollars=float(done['total_cost_dollars']),
        glw_conflict_raw_score_rows=int((bridge.ticker.eq('GLW')&bridge.same_day_glw_score_present).sum()),
        glw_conflict_cross_section_rows=int(bridge.same_day_glw_score_present.sum()),
        checks=checks,path=str(destination.relative_to(ROOT)),sha256=sha(destination))
    dump(OUT/f'CHECK_{year}_{policy}.json',path_summary)
    last=bridge.loc[bridge.signal_date.eq(bridge.signal_date.max())].copy()
    last['display_priority']=np.select([last.actual_state_top20,last.target_weight.gt(0),last.post_units.gt(0),last.has_recorded_rejection],[0,1,2,3],default=4)
    last=last.loc[last.display_priority.lt(4)].sort_values(['display_priority','actual_state_rank','ticker'],kind='stable')
    evidence=bridge.loc[bridge.high_rank_zero_target|bridge.positive_target_no_trade|bridge.reconstructed_capacity_limited|
        bridge.held_without_decision_input|bridge.known_glw_input_conflict].copy()
    # Keep representative examples only; complete dates remain in the per-path machine table.
    examples=[]
    for flag in ['high_rank_zero_target','positive_target_no_trade','reconstructed_capacity_limited','held_without_decision_input','known_glw_input_conflict']:
        sample=evidence.loc[evidence[flag]].head(3).copy();sample['example_category']=flag;examples.append(sample)
    return path_summary,last,pd.concat(examples,ignore_index=True)


def build():
    started=time.monotonic()
    if (OUT/'COMPLETE.json').exists():raise RuntimeError('BRIDGE_ALREADY_COMPLETE')
    record(OUT.parent/'DIAGNOSTIC_CONTRACT.md');record(Path(__file__))
    summaries=[];lasts=[];examples=[]
    for year in (2025,2026):
        frozen=read_json(ROOT/f'evaluation_{year}/cost_10/FROZEN_BEFORE_REPLAY.json')
        complete=read_json(ROOT/f'evaluation_{year}/cost_10/COMPLETE.json')
        assert complete['policies']==len(frozen['roster'])==19
        features,prices=source_tables(year)
        for policy in frozen['roster']:
            print(json.dumps({'starting_bridge':policy,'year':year}),flush=True)
            summary,last,example=build_path(year,policy,features,prices)
            summaries.append(summary);lasts.append(last);examples.append(example)
            print(json.dumps({k:summary[k] for k in ['year','policy','rows','high_rank_zero_target','positive_target_no_trade','capacity_limited_fills','recorded_cost_dollars']}),flush=True)
    final=pd.concat(lasts,ignore_index=True)
    final.to_parquet(OUT/'LAST_SIGNAL_ACTUAL_ACCOUNT_FULL.parquet',index=False,compression='zstd')
    easy=['year','policy','signal_date','ticker','actual_state_rank','actual_score_5pct_vs_exit','raw_chosen_weight',
        'target_weight','target_order_type','target_semantic','signal_current_weight','signal_cash_weight',
        'new_buy_eligible','target_adaptation_reasons','zero_target_explanation','execution_explanation',
        'execution_reasons','buy_notional','sell_notional','recorded_cost','post_weight','post_price_status']
    final[easy].to_csv(OUT/'LAST_SIGNAL_READABLE.csv',index=False,encoding='utf-8-sig')
    pd.concat(examples,ignore_index=True).to_parquet(OUT/'EXPLANATION_EXAMPLES.parquet',index=False,compression='zstd')
    pd.DataFrame([{k:v for k,v in row.items() if not isinstance(v,dict)} for row in summaries]).to_csv(OUT/'POLICY_SUMMARY.csv',index=False,encoding='utf-8-sig')
    for path,expected in INPUTS.items():assert sha(path)==expected,f'ORIGINAL_CHANGED:{path}'
    receipt=dict(status='PASS',scope='Actual-account state; original 2025/2026 cost10 ledgers only',
        paths=len(summaries),rows=sum(s['rows'] for s in summaries),model_fit_calls=0,model_predict_calls=0,replay_calls=0,
        original_inputs_unchanged=True,input_sha256=INPUTS,paths_summary=summaries,seconds=time.monotonic()-started,
        fixed_reference_state='Separate outputs in ../selection; never claimed to drive original actual orders',
        score_rule='Recorded action value at .05 minus action value at 0; neural preference from original projected weight: 10p-.25',
        ranking_rule='Recorded actual-state scored securities, descending score then ascending ticker; unscored input/reserved names retained with null rank',
        price_scope='Existing close gate and recorded mark status only; known GLW Feb26/27 conflict overrides authentication claims',
        attribution_limit='Original optimizer binding constraints not recorded: positive-advantage zero allocations remain UNKNOWN, never inferred from zero alone')
    dump(OUT/'COMPLETE.json',receipt)
    print(json.dumps({'status':'PASS','paths':len(summaries),'rows':receipt['rows'],'seconds':receipt['seconds']}),flush=True)


if __name__=='__main__':build()
