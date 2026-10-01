"""Descriptive balanced-factor comparisons; no selection or feedback to learning."""
from common import *
import pandas as pd
from itertools import combinations
from concurrent.futures import ThreadPoolExecutor

METRICS=['net_return','max_drawdown','mean_gross_exposure','total_fees','turnover','annualized_log_vol',
         'optimizer_approx_unconverged_days','target_blend_unconverged_member_days']

def hac_mean(series,lag=5):
    x=np.asarray(series,float);x=x[np.isfinite(x)];n=len(x)
    if not n:return dict(days=0,mean_daily_log_difference=None,hac_se_lag5=None,positive_day_fraction=None)
    z=x-x.mean();variance=float(z@z/n)
    for k in range(1,min(lag,n-1)+1):variance+=2*(1-k/(lag+1))*float(z[k:]@z[:-k]/n)
    return dict(days=n,mean_daily_log_difference=float(x.mean()),hac_se_lag5=float(np.sqrt(max(0.,variance)/n)),
                positive_day_fraction=float((x>0).mean()))

def daily_matrix(year,rows):
    def load(sid):
        f=pd.read_parquet(ROOT/f'evaluation_{year}'/sid/'daily.parquet',columns=['date','nav'])
        dates=pd.DatetimeIndex(f.date)
        if not dates.is_monotonic_increasing or not dates.is_unique:raise ValueError('UNORDERED_OR_DUPLICATE_ACCOUNT_DATES: '+sid)
        return sid,pd.Series(np.log(f.nav.to_numpy(float)/f.nav.shift().to_numpy(float)),index=pd.DatetimeIndex(f.date))
    with ThreadPoolExecutor(max_workers=8) as pool:loaded=list(pool.map(load,rows.strategy_id))
    matrix=pd.DataFrame({sid:series for sid,series in loaded}).sort_index()
    matrix.columns.name='strategy_id';return matrix

def comparison(left_frame,right_frame,daily,match_keys,expected_cells=None,**labels):
    merged=left_frame.merge(right_frame,on=match_keys,suffixes=('_left','_right'),validate='one_to_one')
    coverage=left_frame[match_keys].merge(right_frame[match_keys],on=match_keys,how='outer',indicator=True,validate='one_to_one')
    expected=len(coverage) if expected_cells is None else int(expected_cells)
    if len(coverage)>expected:raise ValueError('PAIRED_COMPARISON_EXCEEDS_PRESPECIFIED_GRID')
    ls=merged.strategy_id_left.tolist();rs=merged.strategy_id_right.tolist()
    delta=daily[ls].to_numpy()-daily[rs].to_numpy()
    valid=np.isfinite(delta).all(axis=1) if len(merged) else np.zeros(len(daily),dtype=bool)
    result=dict(**labels,expected_cells=expected,matched_cells=len(merged),
                left_success_cells=len(left_frame),right_success_cells=len(right_frame),
                left_only_success_cells=int(coverage._merge.eq('left_only').sum()),
                right_only_success_cells=int(coverage._merge.eq('right_only').sum()),
                both_missing_cells=expected-len(coverage),complete_matched_grid=len(merged)==expected,
                calendar_rows=len(daily),common_valid_return_days=int(valid.sum()),
                omitted_return_days=int((~valid).sum()),hac_lag_basis='retained common valid return dates',
                first_common_valid_return_date=str(daily.index[valid][0].date()) if valid.any() else None,
                last_common_valid_return_date=str(daily.index[valid][-1].date()) if valid.any() else None,
                successful_intersection_only=True,paired_cells_are_not_independent_samples=True,
                **hac_mean(delta[valid].mean(axis=1) if len(merged) else []))
    for k in METRICS:
        if k in left_frame and k in right_frame:
            result['delta_'+k]=float((merged[k+'_left']-merged[k+'_right']).mean()) if len(merged) else None
    result['left_ids_json']=json.dumps(ls);result['right_ids_json']=json.dumps(rs)
    return result

def factor_decomposition(rows,metric='net_return'):
    """Balanced 152 x 10 x 3 (or other complete forecast grid) algebra."""
    g=rows[['forecast_id','risk','optimizer',metric]].copy()
    sizes=g.groupby('forecast_id').size()
    if not (sizes.eq(30).all() and len(g)==g.forecast_id.nunique()*30):
        raise ValueError('FACTOR_GRID_INCOMPLETE: failed routes cannot be silently dropped')
    if g.duplicated(['forecast_id','risk','optimizer']).any():raise ValueError('DUPLICATE_FACTOR_CELL')
    expected_grid={(r,o) for r in RISKS for o in OPTIMIZERS}
    for forecast,part in g.groupby('forecast_id'):
        if set(zip(part.risk,part.optimizer))!=expected_grid:
            raise ValueError('FACTOR_GRID_NOT_PRESPECIFIED_CARTESIAN_PRODUCT: '+str(forecast))
    grand=g[metric].mean();f=g.groupby('forecast_id')[metric].mean();r=g.groupby('risk')[metric].mean();o=g.groupby('optimizer')[metric].mean()
    fr=g.groupby(['forecast_id','risk'])[metric].mean();fo=g.groupby(['forecast_id','optimizer'])[metric].mean();ro=g.groupby(['risk','optimizer'])[metric].mean()
    result=g.rename(columns={metric:'observed'})
    result['grand_mean']=grand
    result['forecast_main']=[f[x]-grand for x in g.forecast_id]
    result['risk_main']=[r[x]-grand for x in g.risk]
    result['optimizer_main']=[o[x]-grand for x in g.optimizer]
    result['forecast_risk_interaction']=[fr[a,b]-f[a]-r[b]+grand for a,b in zip(g.forecast_id,g.risk)]
    result['forecast_optimizer_interaction']=[fo[a,b]-f[a]-o[b]+grand for a,b in zip(g.forecast_id,g.optimizer)]
    result['risk_optimizer_interaction']=[ro[a,b]-r[a]-o[b]+grand for a,b in zip(g.risk,g.optimizer)]
    effects=['grand_mean','forecast_main','risk_main','optimizer_main','forecast_risk_interaction',
             'forecast_optimizer_interaction','risk_optimizer_interaction']
    result['three_way_interaction']=result.observed-result[effects].sum(axis=1)
    result['metric']=metric
    assert np.allclose(result[effects+['three_way_interaction']].sum(axis=1),result.observed,rtol=0,atol=1e-12)
    return result

def analyze_year(year,out):
    rows=pd.read_csv(ROOT/f'evaluation_{year}/comparison.csv')
    if len(rows)!=5053:raise ValueError('FULL_PRESPECIFIED_COMPARISON_MISSING')
    good=rows.loc[rows.status.eq('REPLAY_COMPLETE')].copy()
    daily=daily_matrix(year,good);daily.to_parquet(out/f'daily_log_returns_{year}.parquet')
    base=good.loc[good.route.eq('prediction_fusion')&good.optimizer.isin(OPTIMIZERS)]
    if len(base)==4560:
        for metric in ['net_return','max_drawdown','mean_gross_exposure','mean_daily_log_return']:
            factor_decomposition(base,metric).to_csv(out/f'factor_interactions_{year}_{metric}.csv',index=False)
    summaries=[]
    for universe,frame in [('all_152_forecasts',base),('31_single_predictors',base.loc[base.coalition.eq('single')])]:
        for dimension in ['forecast_id','risk','optimizer']:
            table=frame.groupby(dimension,dropna=False)[METRICS].agg(['mean','min','max'])
            table.columns=['__'.join(c) for c in table.columns];table=table.reset_index()
            table.insert(0,'dimension',dimension);table.insert(0,'universe',universe);summaries.append(table)
    pd.concat(summaries,ignore_index=True).to_csv(out/f'main_effect_summaries_{year}.csv',index=False)
    pairs=[]
    forecast_count=len(PROVIDERS)+len(COALITIONS)*len(FUSIONS)
    for a,b in combinations(RISKS,2):
        row=comparison(base.loc[base.risk.eq(a)],base.loc[base.risk.eq(b)],daily,['forecast_id','optimizer'],
            expected_cells=forecast_count*len(OPTIMIZERS),comparison='risk',left=a,right=b,year=year)
        if row:pairs.append(row)
    for a,b in combinations(OPTIMIZERS,2):
        row=comparison(base.loc[base.optimizer.eq(a)],base.loc[base.optimizer.eq(b)],daily,['forecast_id','risk'],
            expected_cells=forecast_count*len(RISKS),comparison='optimizer',left=a,right=b,year=year)
        if row:pairs.append(row)
    for a,b in combinations(PROVIDERS,2):
        row=comparison(base.loc[base.forecast_id.eq('single__'+a)],base.loc[base.forecast_id.eq('single__'+b)],daily,['risk','optimizer'],
            expected_cells=len(RISKS)*len(OPTIMIZERS),comparison='single_predictor',left=a,right=b,year=year)
        if row:pairs.append(row)
    for group in COALITIONS:
        frame=base.loc[base.coalition.eq(group)]
        equal=frame.loc[frame.fusion.eq('equal')]
        for method in [m for m in FUSIONS if m!='equal']:
            row=comparison(frame.loc[frame.fusion.eq(method)],equal,daily,['risk','optimizer'],
                expected_cells=len(RISKS)*len(OPTIMIZERS),comparison='fusion_within_fixed_members',coalition=group,left=method,right='equal',year=year)
            if row:pairs.append(row)
        target=good.loc[good.route.eq('target_fusion')&good.coalition.eq(group)&good.optimizer.isin(OPTIMIZERS)]
        row=comparison(target,frame.loc[frame.fusion.eq('convex')],daily,['risk','optimizer'],
            expected_cells=len(RISKS)*len(OPTIMIZERS),comparison='target_vs_prediction_fusion',coalition=group,left='target_blend',right='convex_forecast',year=year)
        if row:pairs.append(row)
    pd.DataFrame(pairs).to_csv(out/f'matched_dimension_comparisons_{year}.csv',index=False)
    equal=good.loc[good.optimizer.eq('equal_top20')].copy()
    adjusted=good.loc[good.optimizer.isin(OPTIMIZERS)].merge(equal,on=['route','forecast_id'],suffixes=('','_fixed_gross'),validate='many_to_one')
    for k in METRICS:
        adjusted['delta_'+k]=adjusted[k]-adjusted[k+'_fixed_gross']
    adjusted.to_csv(out/f'optimization_vs_fixed_gross_{year}.csv',index=False)
    interactions=[]
    for group in COALITIONS:
        for method in [m for m in FUSIONS if m!='equal']:
            for risk in RISKS:
                left=base.loc[base.forecast_id.eq(group+'__'+method)&base.risk.eq(risk)]
                right=base.loc[base.forecast_id.eq(group+'__equal')&base.risk.eq(risk)]
                row=comparison(left,right,daily,['optimizer'],comparison='fusion_effect_conditional_on_risk',
                               expected_cells=len(OPTIMIZERS),coalition=group,left=method,right='equal',risk=risk,year=year)
                if row:interactions.append(row)
    pd.DataFrame(interactions).to_csv(out/f'fusion_risk_conditional_comparisons_{year}.csv',index=False)
    return rows,daily

def main():
    from freeze_batch import validate_global_freeze
    validate_global_freeze()
    out=ROOT/'report';out.mkdir(exist_ok=True)
    allrows=[]
    for year in [2025,2026]:
        rows,daily=analyze_year(year,out);allrows.append(rows)
        print(json.dumps(dict(year=year,status='COMPARISONS_WRITTEN',rows=len(rows))),flush=True)
    pd.concat(allrows,ignore_index=True).to_csv(out/'ALL_PTO_RESULTS.csv',index=False)
    write(out/'ANALYSIS_METHOD.json',dict(status='DESCRIPTIVE_FIXED_GRID',model_selection_performed=False,
          duplicated_paths_are_independent_samples=False,hac_lag=5,
          hac_lag_basis='five retained common valid return dates; missing-date removal can span more than five original sessions',
          temporal_unit='shared daily log-return difference, averaging matched factor cells before HAC',
          daily_mean_factor_metric='descriptive algebra of each account available-day mean; not shared-date interaction inference if date coverage differs',
          portfolio_dimension_effects_are_conditional=True,causal_effect_claimed=False,
          full_pool_2026_certified=False,blind_test=False,exposure_requires_separate_comparison=True,
          fixed_gross_controls='same forecast and route, canonical risk none and equal_top20; <=.95 account budget with identical eligibility and caps',
          fixed_gross_is_realized_constant=False,pure_exposure_causal_effect_identified=False,
          target_fusion_comparison='same prespecified coalition, OOF convex coefficients, risk and optimizer; independently evolved accounts; CVaR native-member versus fused-Normal scenario semantics may also differ',
          pure_target_fusion_order_causal_effect_identified=False,
          paired_failure_coverage='expected and left/right-only/both-missing cells reported; zero-match comparisons retained without imputed returns',
          factor_grid='152 forecasts x 10 risks x 3 optimizers, target fusion separately; algebraic terminal-return and daily-log-mean interactions',
          missing_paths='never fill failed returns with zero; no factorial decomposition unless balanced 4560-cell grid completes'))

if __name__=='__main__':main()
