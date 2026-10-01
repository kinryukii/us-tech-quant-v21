"""Independent audit of frozen training boundaries and every completed replay ledger.

Does not train, predict, change results, or select a winning policy.
Only writes VERIFICATION.json. Missing final receipts remain PENDING, not PASS.
"""
from pathlib import Path
import hashlib, json, traceback
import numpy as np
import pandas as pd
from active_13f_gate import validate_active_13f_pool

ROOT=Path(__file__).resolve().parent
SOURCE=Path(r'D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1')
EPS=1e-5

def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def require(value,message):
    if not bool(value):raise AssertionError(message)
def maxerr(a,b):
    a=np.asarray(a,dtype=float);b=np.asarray(b,dtype=float)
    require(a.shape==b.shape,'shape mismatch')
    require(np.array_equal(np.isnan(a),np.isnan(b)),'NaN mismatch')
    good=np.isfinite(a)&np.isfinite(b)
    return float(np.max(np.abs(a[good]-b[good]))) if good.any() else 0.

def original_quarter_timing():
    return pd.read_parquet(SOURCE/'universe/quarterly_universe_manifest.parquet',
        columns=['quarter','effective_date','latest_actual_filing_timestamp']).rename(columns={
            'effective_date':'quarter_effective_date',
            'latest_actual_filing_timestamp':'latest_filing_date'})

def training_audit():
    linear=read(ROOT/'joint_linear_tree_artifacts_r2/FIT_RECEIPT.json')
    require(linear['test_rows_read']==0,'linear consumed test rows')
    verified=0
    for fit in linear['fits']:
        cutoff='2025-01-01' if fit['stage']=='validation' else '2026-01-01'
        require(pd.Timestamp(fit['train_label_end_max'])<pd.Timestamp(cutoff),'linear label cutoff')
        require(pd.Timestamp(fit['train_signal_max'])<pd.Timestamp(cutoff),'linear signal cutoff')
        require(sha(fit['artifact'])==fit['artifact_sha256'],'linear artifact changed')
        verified+=1
    for repair in linear.get('numerical_repairs',[]):
        require(sha(repair['artifact'])==repair['artifact_sha256'],'numerically repaired artifact changed')
        verified+=1
    neural=read(ROOT/'joint_neural_v3/TRAIN_RECEIPT.json')
    require(neural['fit_2026_rows']==0,'neural consumed test rows')
    for key in ['training_label_end_max','max_consumed_price_date','training_signal_max']:
        require(pd.Timestamp(neural[key])<pd.Timestamp('2026-01-01'),f'neural cutoff:{key}')
    require(sha(neural['specification']['source'])==neural['specification']['source_sha256'],'neural source changed')
    for log in neural['logs']:
        if log.get('stage')=='validation':require(pd.Timestamp(log['max_reward_signal'])<pd.Timestamp('2025-01-01'),'neural validation training crossed year')
        if log.get('stage')=='2025_validation':require(log['updates']==0,'neural updated during 2025 validation')
    risk=read(ROOT/'risk/TRAIN_RECEIPT.json')
    require(risk['fit_2026_rows']==0 and pd.Timestamp(risk['train_last'])<pd.Timestamp('2026-01-01'),'risk cutoff')
    require(sha(ROOT/'risk/frozen_covariance.npz')==risk['artifact_sha256'],'risk artifact changed')
    registry=read(ROOT/'models/model_registry.json')
    external=0
    for name,record in registry['models'].items():
        require(sha(record['path'])==record['sha256'],f'frozen reused model changed:{name}')
        external+=1
    j=pd.read_parquet(ROOT/'data/pre2026_joint_context.parquet',columns=[
        'signal_date','active_13f_quarter','quarter_effective_date','latest_filing_date',
        'new_buy_eligible','label_end_date','label_available','target_end_date'])
    require(j.signal_date.lt('2026-01-01').all(),'joint features crossed cutoff')
    require(j.loc[j.label_available,'label_end_date'].lt('2026-01-01').all(),'joint label crossed cutoff')
    active_13f=validate_active_13f_pool(j,original_quarter_timing(),quarter_column='active_13f_quarter')
    return {'status':'PASS','linear_artifact_hashes_checked':verified,'reused_registry_hashes_checked':external,
        'linear_validation_train_label_max':max(z['train_label_end_max'] for z in linear['fits'] if z['stage']=='validation'),
        'all_final_training_label_end_before':'2026-01-01','neural_2025_validation_updates':0,'test_rows_in_model_training':0,
        'active_13f_training_and_validation':active_13f}

def check_run(directory,panel,prices,calendar,year):
    d=pd.read_parquet(directory/'daily.parquet').sort_values('date').reset_index(drop=True)
    t=pd.read_parquet(directory/'trades.parquet')
    p=pd.read_parquet(directory/'positions.parquet')
    q=pd.read_parquet(directory/'target_decisions.parquet')
    meta=read(directory/'metadata.json');cost=float(meta['cost_bps_one_way'])/1e4
    require(pd.DatetimeIndex(d.date).equals(calendar),'daily calendar missing/reordered')
    require(d.cash.ge(-EPS).all(),'negative cash')
    require(d.actual_name_count.le(20).all(),'over 20 actual positions')
    require(d.actual_name_count.ge(0).all(),'negative position count')
    require(not d.date.duplicated().any(),'duplicate ledger dates')
    px=prices.set_index(['ticker','trade_date'])
    next_day=pd.Series(calendar[1:],index=calendar[:-1])
    trade_price_error=0.;fee_error=0.;eligibility_checked=0;units_error=0.
    if len(t):
        require(t.execution_date.eq(t.signal_date.map(next_day)).all(),'non-next-session fill')
        require(t.signal_date.lt(t.execution_date).all(),'same-day trade')
        require(t.execution_date.dt.year.eq(year).all(),'trade outside test year')
        require(t.notional.gt(0).all() and t.price.gt(0).all(),'nonpositive fill')
        expected=px.open.reindex(pd.MultiIndex.from_frame(t[['ticker','execution_date']])).to_numpy()
        require(np.isfinite(expected).all(),'traded unavailable/flagged open')
        trade_price_error=maxerr(t.price,expected);require(trade_price_error<EPS,'fill price mismatch')
        fee_error=maxerr(t.transaction_cost,t.notional*cost);require(fee_error<EPS,'one-way cost mismatch')
        require(maxerr(t.notional,t.index_units*t.price)<EPS,'notional/units mismatch')
        require(t.cost_bps.eq(cost*1e4).all(),'trade cost parameter mismatch')
        buys=t.loc[t.side.eq('BUY')]
        eligibility=panel.set_index(['signal_date','ticker']).new_buy_eligible
        allowed=eligibility.reindex(pd.MultiIndex.from_frame(buys[['signal_date','ticker']])).fillna(False)
        require(allowed.all(),'BUY/INCREASE outside signal-day eligible universe')
        eligibility_checked=len(buys)
        if len(buys):
            require(buys.capacity_adv_source_date.eq(buys.signal_date).all(),'buy capacity consumed non-signal-day ADV')
            limited=buys.loc[buys.capacity_enforced]
            require((limited.notional<=limited.capacity_adv*meta['capacity_fraction']+EPS).all(),'buy exceeds capacity limit')
        holdings={}
        for row in t.itertuples(index=False):
            old=holdings.get(row.ticker,0.)
            units_error=max(units_error,abs(old-row.index_units_before))
            new=old+row.index_units*(1 if row.side=='BUY' else -1)
            require(new>=-EPS,'sold nonexistent units')
            units_error=max(units_error,abs(new-row.index_units_after))
            holdings[row.ticker]=max(0.,new)
        require(units_error<1e-5,'unit continuity error')
    # Reconstruct cash directly from actual trades, ignoring engine identity columns.
    signed=t.assign(signed=np.where(t.side.eq('BUY'),-t.notional,t.notional)-t.transaction_cost) if len(t) else t
    flows=signed.groupby('execution_date').signed.sum().reindex(calendar,fill_value=0) if len(t) else pd.Series(0.,index=calendar)
    independent_cash=meta['initial_cash']+flows.cumsum().to_numpy()
    cash_error=maxerr(d.cash,independent_cash);require(cash_error<EPS,'cash does not equal cumulative net fills')
    fees=t.groupby('execution_date').transaction_cost.sum().reindex(calendar,fill_value=0) if len(t) else pd.Series(0.,index=calendar)
    require(maxerr(d.transaction_cost_amount,fees)<EPS,'daily fees differ from trades')
    if len(p):
        require(not p.duplicated(['date','ticker']).any(),'duplicate position key')
        require(p.index_units.gt(0).all(),'nonpositive position units')
        require(p.mark_date.le(p.date).fillna(p.unknown).all(),'future valuation mark')
        current=p.loc[~p.stale&~p.unknown]
        expected=px.close.reindex(pd.MultiIndex.from_frame(current[['ticker','date']])).to_numpy()
        require(np.isfinite(expected).all(),'certified position uses unavailable/flagged close')
        require(maxerr(current.mark,expected)<EPS,'certified mark differs from current close')
        known=p.loc[~p.unknown]
        require(maxerr(known.market_value,known.index_units*known.mark)<EPS,'position value mismatch')
        count=p.groupby('date').size().reindex(calendar,fill_value=0)
        require(np.array_equal(count.to_numpy(),d.actual_name_count.to_numpy()),'actual position count mismatch')
        known_value=known.groupby('date').market_value.sum().reindex(calendar,fill_value=0)
    else:known_value=pd.Series(0.,index=calendar)
    require(maxerr(d.known_position_value,known_value)<EPS,'known NAV components mismatch')
    finite=d.nav.notna()
    nav_error=maxerr(d.loc[finite,'nav'],d.loc[finite,'cash']+d.loc[finite,'known_position_value'])
    require(nav_error<EPS,'NAV does not equal cash plus positions')
    bad=d.valuation_status.ne('certified')
    require(d.loc[bad,'certified_nav'].isna().all(),'uncertified NAV marked certified')
    require(d.loc[d.unknown_count.gt(0),'nav'].isna().all(),'unknown position valued as finite NAV')
    if len(q):
        submitted=q.loc[q.status.eq('submitted')]
        require(submitted.execution_date.eq(submitted.signal_date.map(next_day)).all(),'decision targets wrong execution day')
        require(submitted.target_weight.fillna(0).between(0,.1000001).all(),'target outside per-stock limit')
        require(submitted.target_sum.le(.9500001).all(),'target exceeds invested limit')
        positive=submitted.loc[submitted.target_weight.gt(1e-10)]
        require(positive.groupby('signal_date').size().le(20).all(),'more than 20 positive target names')
    require(meta['terminal_liquidation'] is False,'unexpected terminal liquidation assumption')
    return {'status':'PASS','directory':directory.name,'year':year,'days':len(d),'trades':len(t),'buys_and_increases_eligibility_checked':eligibility_checked,
        'max_actual_names':int(d.actual_name_count.max()),'uncertified_days':int(bad.sum()),'max_independent_cash_error':cash_error,
        'max_fee_error':fee_error,'max_nav_error':nav_error,'max_trade_price_error':trade_price_error,'max_units_continuity_error':units_error,
        'minimum_cash':float(d.cash.min()),'valuation_limits':'uncertified NAV never upgraded; all performance diagnostic only'}

def main():
    result={'status':'PENDING','training':None,'evaluations':{},'failures':[],'pending':[],
        'scope':'Independent ledger, source-hash and timing audit. Does not prove complete universe, shareholder return or absence of selection bias.'}
    try:result['training']=training_audit()
    except Exception as e:result['failures'].append({'scope':'training','error':f'{type(e).__name__}:{e}'})
    testprice=pd.read_parquet(ROOT/'data/test_prices.parquet')
    testprice.loc[testprice.price_quality_warning.astype(bool),['open','close']]=np.nan
    preprice=pd.read_parquet(ROOT.parent/'a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet')
    preprice['trade_date']=pd.to_datetime(preprice.trade_date)
    scenarios=[(2025,ROOT/'evaluation_2025')]
    shards=sorted((ROOT/'evaluation_2026').glob('cost_*'))
    scenarios.extend((2026,p) for p in shards) if shards else scenarios.append((2026,ROOT/'evaluation_2026'))
    for year,folder in scenarios:
        scenario_key=str(folder.relative_to(ROOT))
        completepath=folder/'COMPLETE.json'
        if not completepath.exists():result['pending'].append(f'{scenario_key}/COMPLETE.json');continue
        try:
            complete=read(completepath)
            require(complete['fit_guard_attempts']==0,'test fit guard triggered')
            require(complete['training_2026_rows']==0,'test rows entered training')
            require(complete['full_pool_formal_result'] is False,'diagnostic upgraded to formal')
            if year==2026:
                seal=read(folder/'FROZEN_BEFORE_SCORING.json')
                require(seal['inference_only'] and not seal['full_pool'],'invalid test seal')
                for rel,h in seal['source_hashes'].items():require(sha(ROOT/rel)==h,f'frozen source drift:{rel}')
                panel=pd.read_parquet(ROOT/'data/test_features_context.parquet')
                panel=panel.loc[panel.signal_date.le('2026-09-22')].copy()
                timing=pd.read_csv(ROOT/'data/quarter_timing.csv')
                quarter_column='quarter'
                prices=testprice
                calendar=pd.DatetimeIndex(pd.read_parquet(ROOT/'data/calendar.parquet').query('is_test').trade_date)
            else:
                panel=pd.read_parquet(ROOT/'data/pre2026_joint_context.parquet').query(
                    'signal_date >= "2025-01-01" and signal_date <= "2025-12-29"')
                timing=original_quarter_timing()
                quarter_column='active_13f_quarter'
                prices=preprice
                calendar=pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq('QQQ')&prices.trade_date.ge('2025-01-01'),'trade_date'].unique()))
            active_13f=validate_active_13f_pool(panel,timing,quarter_column=quarter_column)
            require(read(folder/'ACTIVE_13F_AUDIT.json')==active_13f,'active 13F evaluation audit differs from current source timing')
            require(complete['active_13f_qualification']==active_13f,'active 13F completion receipt differs from source timing')
            comp=pd.read_csv(folder/'comparison.csv')
            require(len(comp)==complete['evaluations'],'comparison incomplete')
            require(not comp.duplicated(['policy','cost_bps_per_side']).any(),'duplicate evaluation combination')
            require(comp.groupby('cost_bps_per_side').policy.nunique().eq(complete['policies']).all(),'policy missing at cost scenario')
            require(comp.formal_full_pool_return.isna().all(),'reported formal return for incomplete pool')
            rows=[]
            for row in comp.itertuples(index=False):
                directory=folder/f'{row.policy}_{row.cost_bps_per_side:g}bps'
                rows.append(check_run(directory,panel,prices,calendar,year))
            result['evaluations'][scenario_key]={'status':'PASS','fit_guard_attempts':complete['fit_guard_attempts'],
                'frozen_source_hashes_checked':len(seal['source_hashes']) if year==2026 else 0,
                'active_13f_quarter_timing':active_13f,'runs':rows}
        except Exception as e:
            result['failures'].append({'scope':scenario_key,'error':f'{type(e).__name__}:{e}','traceback':traceback.format_exc()[-1800:]})
    if shards:
        aggregate=ROOT/'evaluation_2026/COMPLETE.json'
        if not aggregate.exists():result['pending'].append('evaluation_2026/COMPLETE.json (aggregate)')
        else:
            try:
                comp=pd.read_csv(ROOT/'evaluation_2026/comparison.csv')
                require(len(comp)==42,'combined 2026 expected 42 scenarios')
                require(not comp.duplicated(['policy','cost_bps_per_side']).any(),'duplicate combined scenario')
                require(set(comp.cost_bps_per_side)=={5,10,25},'missing cost scenario')
                require(comp.groupby('cost_bps_per_side').policy.nunique().eq(14).all(),'combined policy roster incomplete')
                require(comp.formal_full_pool_return.isna().all(),'aggregate upgraded incomplete pool return')
                result['aggregate_2026']={'status':'PASS','evaluations':42,'cost_bps':[5,10,25]}
            except Exception as e:result['failures'].append({'scope':'aggregate_2026','error':f'{type(e).__name__}:{e}'})
    result['status']='FAIL' if result['failures'] else 'PENDING' if result['pending'] else 'PASS'
    (ROOT/'VERIFICATION.json').write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    print(json.dumps({'status':result['status'],'pending':result['pending'],'failures':result['failures'],
        'verified_runs':sum(len(x.get('runs',[])) for x in result['evaluations'].values())},indent=2,ensure_ascii=False))
    if result['failures']:raise SystemExit(1)

if __name__=='__main__':main()
