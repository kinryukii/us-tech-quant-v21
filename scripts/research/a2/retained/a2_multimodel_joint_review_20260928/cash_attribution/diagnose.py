"""Read-only 2025 ledger attribution; no fit, prediction, replay, or weight search."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
WS = OUT.parents[1]
ROOT = WS / 'a2_multimodel_joint_20260928'
SRC = ROOT / 'evaluation_2025/cost_10/ensemble_equal_weight'
PRICE = WS / 'a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet'


def write_json(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def members():
    raw = pd.read_parquet(SRC / 'raw_model_outputs.parquet')
    ctx = pd.read_parquet(SRC / 'signal_contexts.parquet').set_index('signal_date')
    targets = pd.read_parquet(SRC / 'target_decisions.parquet').set_index(['signal_date','ticker'])
    records = []
    daily = []
    for r in raw.itertuples():
        c = ctx.loc[r.signal_date]
        current = json.loads(c.current_weights_json)
        detail = json.loads(r.raw_model_outputs_json)
        mean = {t: np.mean(list(x['member_targets'].values())) for t,x in detail.items()}
        keep = set(sorted(mean, key=lambda t: (-mean[t], t))[:int(c.available_slots)])
        for t,x in detail.items():
            target = targets.loc[(r.signal_date,t)]
            for member,w in x['member_targets'].items():
                records.append(dict(signal_date=r.signal_date,ticker=t,member=member,
                    member_target=w,current_weight=current.get(t,0.),
                    cash_weight=c.cash_weight,reserved_weight=c.reserved_weight,
                    available_slots=c.available_slots,available_weight=c.available_weight,
                    equal_pre_target=mean[t],equal_post_target=x['equal_weight_target'],
                    adapted_target=target.adapted_target_weight,
                    top20_truncated=bool(mean[t]>0 and t not in keep),
                    top20_kept=t in keep))
        member_names = sorted(next(iter(detail.values()))['member_targets'])
        row = dict(signal_date=r.signal_date,signal_nav=c.nav,
            actual_signal_cash_weight=c.cash_weight,reserved_signal_weight=c.reserved_weight,
            reserved_slots=c.reserved_slots,available_slots=c.available_slots,
            final_reserved_weight=c.final_reserved_weight,
            average_active_target_weight=sum(mean.values()),
            post_top20_active_target_weight=sum(x['equal_weight_target'] for x in detail.values()),
            adapted_active_target_weight=c.active_target_weight,
            union_positive_names=sum(v>1e-10 for v in mean.values()),
            top20_active_names=sum(x['equal_weight_target']>1e-10 for x in detail.values()),
            top20_dropped_names=sum(v>1e-10 and t not in keep for t,v in mean.items()))
        for name in member_names:
            active = sum(x['member_targets'][name] for x in detail.values())
            row[name+'_active_weight'] = active
            row[name+'_cash_weight'] = 1-c.reserved_weight-active
        row['mean_member_cash_weight'] = np.mean([row[n+'_cash_weight'] for n in member_names])
        row['average_target_cash_weight'] = 1-c.reserved_weight-row['average_active_target_weight']
        row['average_cash_identity_residual'] = row['average_target_cash_weight']-row['mean_member_cash_weight']
        row['post_top20_cash_weight'] = 1-c.reserved_weight-row['post_top20_active_target_weight']
        row['top20_cash_added_weight'] = row['average_active_target_weight']-row['post_top20_active_target_weight']
        row['adapted_target_cash_weight'] = 1-c.final_reserved_weight-c.active_target_weight
        row['adapter_cash_added_weight'] = row['adapted_target_cash_weight']-row['post_top20_cash_weight']
        daily.append(row)
    pd.DataFrame(records).to_parquet(OUT/'member_targets_2025.parquet',index=False)
    frame = pd.DataFrame(daily)
    frame.to_csv(OUT/'signal_cash_stages.csv',index=False)
    print('MEMBER_EXPORT_READY',len(records),flush=True)
    return frame


def ledger_attribution():
    d = pd.read_parquet(SRC/'daily.parquet').sort_values('date')
    p = pd.read_parquet(SRC/'positions.parquet')
    t = pd.read_parquet(SRC/'trades.parquet')
    target = pd.read_parquet(SRC/'target_decisions.parquet')
    px = pd.read_parquet(PRICE)
    px = px[px.trade_date.ge('2025-01-01')].set_index(['trade_date','ticker'])
    assert not px.index.duplicated().any()
    prices = px[['open','close']].to_dict('index')
    positions = {dt: g.set_index('ticker').to_dict('index') for dt,g in p.groupby('date')}
    trades = {(dt,ticker): g for (dt,ticker),g in t.groupby(['execution_date','ticker'])}
    target_groups = {dt: g for dt,g in target.groupby('execution_date')}
    stages = pd.read_csv(OUT/'signal_cash_stages.csv',parse_dates=['signal_date']).set_index('signal_date')
    previous = {}
    prev_nav = 1e6
    records, execution_records, waterfalls = [],[],[]
    for day in d.itertuples():
        post = positions.get(day.date,{})
        names = sorted(set(previous)|set(post)|set(t.loc[t.execution_date.eq(day.date),'ticker']))
        for ticker in names:
            old = previous.get(ticker,{})
            new = post.get(ticker,{})
            q0,q1 = old.get('index_units',0.),new.get('index_units',0.)
            price = prices[(day.date,ticker)]
            op,cl = price['open'],price['close']
            assert np.isfinite([op,cl]).all() and min(op,cl)>0
            tt = trades.get((day.date,ticker))
            buy = sell = fees = buyq = sellq = 0.
            action = 'HOLD'
            if tt is not None:
                assert len(tt)==1
                tr = tt.iloc[0]
                action = tr.action
                fees = tr.transaction_cost
                if tr.side=='BUY': buy,buyq = tr.notional,tr.index_units
                else: sell,sellq = tr.notional,tr.index_units
                assert abs(tr.price-op)<1e-8
            assert abs(q1-(q0+buyq-sellq))<1e-7
            oldcl = old.get('mark',op)
            overnight = q0*(op-oldcl)
            intraday = q1*(cl-op)
            retained = max(0.,q0-sellq)
            cashflow_pnl = new.get('market_value',0.)-old.get('market_value',0.)+sell-buy-fees
            records.append(dict(date=day.date,month=str(day.date.to_period('M')),ticker=ticker,
                action=action,pre_units=q0,post_units=q1,open=op,close=cl,
                previous_close=oldcl,buy_notional=buy,sell_notional=sell,fees=fees,
                overnight_pnl=overnight,intraday_pnl=intraday,
                gross_pnl=overnight+intraday,net_pnl=overnight+intraday-fees,
                cashflow_pnl=cashflow_pnl,identity_residual=overnight+intraday-fees-cashflow_pnl,
                overnight_sold_units_pnl=sellq*(op-oldcl),
                overnight_retained_units_pnl=retained*(op-oldcl),
                intraday_retained_units_pnl=retained*(cl-op),
                intraday_bought_units_pnl=buyq*(cl-op)))
        if pd.notna(day.signal_date):
            s = stages.loc[day.signal_date].to_dict()
            s.update(signal_date=day.signal_date,execution_date=day.date)
            N=day.open_pretrade_nav
            desired_equity=reserved_open=actual_equity=capacity_gap=other_gap=0.
            for tr in target_groups[day.date].itertuples():
                q0=previous.get(tr.ticker,{}).get('index_units',0.)
                q1=post.get(tr.ticker,{}).get('index_units',0.)
                if q0==q1==0 and (tr.order_type=='HOLD_UNITS' or tr.adapted_target_weight==0):
                    continue
                op=prices[(day.date,tr.ticker)]['open']
                before=q0*op
                after=q1*op
                wanted=before if tr.order_type=='HOLD_UNITS' else tr.adapted_target_weight*N
                desired_equity+=wanted
                actual_equity+=after
                if tr.order_type=='HOLD_UNITS':reserved_open+=before
                req_buy=max(0.,wanted-before)
                expected_cap_gap=max(0.,req_buy-tr.signal_day_adv*.01) if req_buy>0 and np.isfinite(tr.signal_day_adv) else 0.
                gap=wanted-after
                capacity_gap+=expected_cap_gap
                other_gap+=gap-expected_cap_gap
                tt=trades.get((day.date,tr.ticker))
                fee=0. if tt is None else tt.transaction_cost.sum()
                execution_records.append(dict(signal_date=day.signal_date,execution_date=day.date,ticker=tr.ticker,
                    order_type=tr.order_type,signal_target_weight=tr.adapted_target_weight,
                    open_pretrade_nav=N,open_pre_value=before,open_desired_value=wanted,
                    open_actual_value=after,desired_less_actual_value=gap,
                    requested_buy=req_buy,capacity_limit=tr.signal_day_adv*.01,
                    capacity_cash_added_dollars=expected_cap_gap,
                    other_execution_gap_dollars=gap-expected_cap_gap,fee=fee,
                    actual_open_weight_pre_fee_nav=after/N,
                    actual_open_weight_post_fee_nav=after/day.open_posttrade_nav,
                    actual_close_weight=post.get(tr.ticker,{}).get('weight',0.)))
            fees=day.transaction_cost_amount
            signal_target_cash=s['adapted_target_cash_weight']
            open_ideal_cash=1-desired_equity/N
            open_cash_on_pre_nav=day.cash/N
            open_cash_on_post_nav=day.cash/day.open_posttrade_nav
            s.update(open_pretrade_nav=N,open_posttrade_nav=day.open_posttrade_nav,
                reserved_open_weight=reserved_open/N,
                reserved_overnight_cash_delta=open_ideal_cash-signal_target_cash,
                ideal_open_cash_weight_pre_fee_nav=open_ideal_cash,
                capacity_cash_added_dollars=capacity_gap,
                capacity_cash_added_weight=capacity_gap/N,
                other_execution_cash_added_dollars=other_gap,
                other_execution_cash_added_weight=other_gap/N,
                fees=fees,fee_cash_amount_delta_weight=-fees/N,
                actual_open_cash_weight_pre_fee_nav=open_cash_on_pre_nav,
                fee_denominator_delta_weight=open_cash_on_post_nav-open_cash_on_pre_nav,
                actual_open_cash_weight_post_fee_nav=open_cash_on_post_nav,
                intraday_cash_drift_weight=day.cash_weight-open_cash_on_post_nav,
                actual_close_cash_weight=day.cash_weight,
                execution_equity_identity_residual=actual_equity-(day.open_posttrade_nav-day.cash),
                execution_cash_identity_residual=day.cash-(N-desired_equity+capacity_gap+other_gap-fees),
                waterfall_weight_residual=day.cash_weight-(signal_target_cash+
                    (open_ideal_cash-signal_target_cash)+capacity_gap/N+other_gap/N-fees/N+
                    (open_cash_on_post_nav-open_cash_on_pre_nav)+(day.cash_weight-open_cash_on_post_nav)))
            waterfalls.append(s)
        previous=post
        prev_nav=day.nav
    detail=pd.DataFrame(records)
    detail.to_parquet(OUT/'stock_daily_pnl.parquet',index=False)
    numeric=['buy_notional','sell_notional','fees','overnight_pnl','intraday_pnl','gross_pnl','net_pnl',
             'overnight_sold_units_pnl','overnight_retained_units_pnl','intraday_retained_units_pnl','intraday_bought_units_pnl']
    stock=detail.groupby('ticker')[numeric].sum().sort_values('net_pnl')
    terminal=p[p.date.eq(d.date.max())].set_index('ticker').market_value
    stock['terminal_value']=terminal.reindex(stock.index).fillna(0)
    stock['cashflow_net_pnl']=stock.terminal_value+stock.sell_notional-stock.buy_notional-stock.fees
    stock['cashflow_identity_residual']=stock.net_pnl-stock.cashflow_net_pnl
    stock.to_csv(OUT/'stock_pnl.csv')
    detail.groupby('month')[numeric].sum().to_csv(OUT/'monthly_pnl.csv')
    detail.groupby('action')[numeric].sum().to_csv(OUT/'trade_action_pnl.csv')
    detail.groupby(['ticker','action'])[numeric].sum().to_csv(OUT/'stock_trade_action_pnl.csv')
    detail.groupby(['month','action'])[numeric].sum().to_csv(OUT/'monthly_trade_action_pnl.csv')
    detail.groupby('date')[numeric].sum().to_csv(OUT/'daily_pnl.csv')
    costs=t.groupby('action').agg(trades=('action','size'),notional=('notional','sum'),fees=('transaction_cost','sum'))
    costs.to_csv(OUT/'trade_action_costs.csv')
    pd.DataFrame(execution_records).to_parquet(OUT/'target_to_execution_2025.parquet',index=False)
    waterfall=pd.DataFrame(waterfalls)
    waterfall.to_csv(OUT/'daily_cash_waterfall.csv',index=False)
    # Separate independently run account paths; this is not a common-state causal effect.
    account=[]
    for name in ['ensemble_equal_weight','joint_hgb','joint_mlp','joint_ridge','joint_elastic_net','joint_logistic','joint_quantile_risk']:
        folder=SRC.parent/name
        dd=pd.read_parquet(folder/'daily.parquet')
        tt=pd.read_parquet(folder/'trades.parquet')
        pp=pd.read_parquet(folder/'positions.parquet')
        final=pp[pp.date.eq(dd.date.max())].groupby('ticker').market_value.sum()
        buys=tt[tt.side.eq('BUY')].groupby('ticker').notional.sum()
        sells=tt[tt.side.eq('SELL')].groupby('ticker').notional.sum()
        f=tt.groupby('ticker').transaction_cost.sum()
        ss=pd.concat([final.rename('terminal_value'),buys.rename('buy_notional'),sells.rename('sell_notional'),f.rename('fees')],axis=1).fillna(0)
        ss['gross_pnl']=ss.terminal_value+ss.sell_notional-ss.buy_notional
        ss['net_pnl']=ss.gross_pnl-ss.fees
        ss['policy']=name
        ss.reset_index().to_csv(OUT/(name+'_independent_stock_pnl.csv'),index=False)
        account.append(dict(policy=name,net_pnl=dd.nav.iloc[-1]-1e6,gross_pnl=ss.gross_pnl.sum(),
            fees=tt.transaction_cost.sum(),trades=len(tt),turnover=dd.turnover.sum(),
            mean_cash_weight=dd.cash_weight.mean(),stock_identity_residual=ss.net_pnl.sum()-(dd.nav.iloc[-1]-1e6)))
    pd.DataFrame(account).to_csv(OUT/'independent_account_comparison.csv',index=False)
    x=detail.groupby('date').net_pnl.sum().reindex(d.date,fill_value=0).to_numpy()
    check=dict(status='PASS',scope='2025 existing ledger read-only; no refit, no model inference, no replay',
        signal_pairs=len(waterfall),calendar_days=len(d),member_target_rows=len(pd.read_parquet(OUT/'member_targets_2025.parquet')),
        all_250_day_cash_mean=d.cash_weight.mean(),paired_248_close_cash_mean=waterfall.actual_close_cash_weight.mean(),
        unpaired_dates=d.loc[d.signal_date.isna(),['date','cash_weight']].to_dict('records'),
        net_pnl=detail.net_pnl.sum(),gross_pnl=detail.gross_pnl.sum(),fees=detail.fees.sum(),
        terminal_nav=d.nav.iloc[-1],net_pnl_identity_residual=detail.net_pnl.sum()-(d.nav.iloc[-1]-1e6),
        max_daily_pnl_identity_residual=float(np.max(np.abs(x-np.diff(np.r_[1e6,d.nav])))),
        max_stock_cashflow_identity_residual=stock.cashflow_identity_residual.abs().max(),
        max_waterfall_weight_residual=waterfall.waterfall_weight_residual.abs().max(),
        max_execution_cash_identity_residual=waterfall.execution_cash_identity_residual.abs().max(),
        max_execution_equity_identity_residual=waterfall.execution_equity_identity_residual.abs().max(),
        max_other_execution_cash_added_dollars=waterfall.other_execution_cash_added_dollars.abs().max(),
        max_adapter_cash_added_weight=waterfall.adapter_cash_added_weight.abs().max(),
        max_average_cash_identity_residual=waterfall.average_cash_identity_residual.abs().max(),
        rejected_execution_rows=int((pd.read_parquet(SRC/'execution_results.parquet').status=='REJECTED').sum()),
        min_buy_cash_scale=d.buy_cash_scale.min(),certified_close_days=int(d.certified_nav.notna().sum()),
        overnight_pnl=detail.overnight_pnl.sum(),intraday_pnl=detail.intraday_pnl.sum(),
        mean_cash_stages=waterfall.select_dtypes('number').mean().to_dict())
    assert abs(check['net_pnl_identity_residual'])<1e-6
    assert check['max_daily_pnl_identity_residual']<1e-6
    assert check['max_stock_cashflow_identity_residual']<1e-6
    assert check['max_waterfall_weight_residual']<1e-10
    assert check['max_execution_cash_identity_residual']<1e-6
    assert check['max_other_execution_cash_added_dollars']<1e-6
    write_json('CHECKS.json',check)
    print(json.dumps({k:v for k,v in check.items() if k!='mean_cash_stages'},default=str),flush=True)


def supplemental():
    member = pd.read_parquet(OUT/'member_targets_2025.parquet')
    common = member[member.member.eq('joint_hgb')].copy()
    trades = pd.read_parquet(SRC/'trades.parquet')
    joined = trades.merge(common[['signal_date','ticker','equal_pre_target','equal_post_target',
        'current_weight','top20_truncated','available_slots']],on=['signal_date','ticker'],how='left',validate='many_to_one')
    joined['exit_reason_group']=np.where(joined.action.eq('EXIT'),
        np.where(joined.top20_truncated.eq(True),'MEAN_POSITIVE_TOP20_ZERO','MEAN_ZERO'), 'NOT_EXIT')
    joined.groupby(['action','exit_reason_group']).agg(trades=('action','size'),
        notional=('notional','sum'),fees=('transaction_cost','sum')).to_csv(OUT/'top20_exit_mechanism.csv')
    joined[joined.action.eq('EXIT')].to_parquet(OUT/'exit_target_evidence.parquet',index=False)
    joined[joined.ticker.eq('SOC')].to_csv(OUT/'SOC_trade_target_evidence.csv',index=False)
    p=pd.read_parquet(OUT/'stock_daily_pnl.parquet')
    cols=['overnight_pnl','intraday_pnl','gross_pnl','fees','net_pnl',
          'intraday_bought_units_pnl','intraday_retained_units_pnl']
    p[p.ticker.eq('SOC')].groupby(['month','action'])[cols].sum().to_csv(OUT/'SOC_month_action_pnl.csv')
    member[member.ticker.eq('SOC')].groupby('member').agg(mean_member_weight=('member_target','mean'),
        positive_days=('member_target',lambda x: int(x.gt(0).sum())),max_weight=('member_target','max')).to_csv(OUT/'SOC_member_target_summary.csv')
    common[common.ticker.eq('SOC')].to_csv(OUT/'SOC_signal_target_evidence.csv',index=False)
    ex=pd.read_parquet(OUT/'target_to_execution_2025.parquet')
    ex.groupby('ticker').agg(capacity_gap_days=('capacity_cash_added_dollars',lambda x: int(x.gt(1e-7).sum())),
        sum_requested_but_unfilled_dollars=('capacity_cash_added_dollars','sum')).sort_values(
        'sum_requested_but_unfilled_dollars',ascending=False).to_csv(OUT/'capacity_gap_by_stock.csv')
    joined.groupby('ticker').agg(trades=('action','size'),entry_count=('action',lambda x:int(x.eq('BUY').sum())),
        exit_count=('action',lambda x:int(x.eq('EXIT').sum())),fees=('transaction_cost','sum')).to_csv(OUT/'stock_trade_counts.csv')
    # Build independent-account stock differences, never interpreted as same-state effects.
    eq=pd.read_csv(OUT/'ensemble_equal_weight_independent_stock_pnl.csv').set_index('ticker')
    for policy in ['joint_hgb','joint_mlp']:
        other=pd.read_csv(OUT/(policy+'_independent_stock_pnl.csv')).set_index('ticker')
        names=eq.index.union(other.index)
        z=pd.DataFrame(index=names)
        for col in ['gross_pnl','fees','net_pnl']:
            z['equal_'+col]=eq[col].reindex(names,fill_value=0)
            z[policy+'_'+col]=other[col].reindex(names,fill_value=0)
            z['equal_minus_'+policy+'_'+col]=z['equal_'+col]-z[policy+'_'+col]
        z.sort_values('equal_minus_'+policy+'_net_pnl').to_csv(OUT/(policy+'_independent_stock_difference.csv'))
    sources=list(SRC.glob('*.parquet'))+[SRC/'metadata.json',SRC/'DONE.json',PRICE,
        ROOT/'engine_v2.py',ROOT/'adapters.py',ROOT/'evaluate.py']
    for name in ['joint_hgb','joint_mlp','joint_ridge','joint_elastic_net','joint_logistic','joint_quantile_risk']:
        sources.extend(SRC.parent/name/file for file in ['daily.parquet','trades.parquet','positions.parquet'])
    write_json('SOURCE_HASHES.json',{str(p):sha(p) for p in sources})
    print('SUPPLEMENTAL_READY',flush=True)


if __name__ == '__main__':
    import sys
    mode=sys.argv[1] if len(sys.argv)>1 else 'members'
    if mode=='members': members()
    elif mode=='ledger': ledger_attribution()
    elif mode=='supplemental': supplemental()
