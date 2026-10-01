"""All results and matched contrasts, without selecting models for another run."""
from common import *
import argparse
from itertools import product

METRICS=['indicative_return','indicative_max_drawdown','mean_gross_exposure','mean_cash','fees','half_turnover','uncertified_days']

def contrast(table,keys,reference_dim,reference_value,tag):
    base=table[table[reference_dim].eq(reference_value)][keys+METRICS].rename(columns={m:'reference_'+m for m in METRICS})
    x=table.merge(base,on=keys,how='left',validate='many_to_one')
    for m in METRICS:x['delta_'+m]=x[m]-x['reference_'+m]
    x['contrast']=tag;x['reference_value']=reference_value
    return x

def factorial_interactions(table):
    results=[]
    for (year,axis),g in table[table.target_fusion.eq('none')].groupby(['year','axis']):
        cells=g.set_index(['stream','risk','optimizer'])
        for stream in g.stream.unique():
            for risk in RISKS:
                for opt in OPTIMIZERS:
                    point=(stream,risk,opt)
                    if point not in cells.index:continue
                    record={'year':year,'axis':axis,'stream':stream,'risk':risk,'optimizer':opt}
                    specifications={'prediction_x_risk':[(stream,risk,opt,1),(stream,'diagonal',opt,-1),('ridge',risk,opt,-1),('ridge','diagonal',opt,1)],
                        'prediction_x_optimizer':[(stream,risk,opt,1),(stream,risk,'mean_variance',-1),('ridge',risk,opt,-1),('ridge',risk,'mean_variance',1)],
                        'risk_x_optimizer':[(stream,risk,opt,1),(stream,risk,'mean_variance',-1),(stream,'diagonal',opt,-1),(stream,'diagonal','mean_variance',1)],
                        'prediction_x_risk_x_optimizer':[(stream,risk,opt,1),(stream,'diagonal',opt,-1),('ridge',risk,opt,-1),('ridge','diagonal',opt,1),
                            (stream,risk,'mean_variance',-1),(stream,'diagonal','mean_variance',1),('ridge',risk,'mean_variance',1),('ridge','diagonal','mean_variance',-1)]}
                    for name,terms in specifications.items():
                        for metric in ['indicative_return','mean_gross_exposure','indicative_max_drawdown','fees']:
                            value=sum(sign*cells.loc[(s,r,o),metric] for s,r,o,sign in terms) if all((s,r,o) in cells.index for s,r,o,sign in terms) else np.nan
                            record[name+'__'+metric]=value
                    results.append(record)
    return pd.DataFrame(results)

def cooperation_interactions(table):
    """Fusion interactions within the same member bundle, including target fusion."""
    rows=[]
    specifications=[('prediction_fusion',table[(table.target_fusion.eq('none'))&table.bundle.ne('singleton')],'fusion','equal','bundle'),
        ('target_fusion',table[table.target_fusion.ne('none')],'target_fusion','target_equal','bundle')]
    for layer,part,dim,anchor,group_dim in specifications:
        for (year,axis,bundle),g in part.groupby(['year','axis',group_dim]):
            cells=g.set_index([dim,'risk','optimizer'])
            for name,risk,opt in cells.index:
                record=dict(year=year,axis=axis,bundle=bundle,layer=layer,method=name,risk=risk,optimizer=opt)
                active=[name,risk,opt];base=[anchor,'diagonal','mean_variance']
                for tag,dimensions in [('fusion_x_risk',[0,1]),('fusion_x_optimizer',[0,2]),('fusion_x_risk_x_optimizer',[0,1,2])]:
                    terms=[]
                    for bits in product([0,1],repeat=len(dimensions)):
                        key=active.copy()
                        for d,bit in zip(dimensions,bits):key[d]=active[d] if bit else base[d]
                        terms.append((tuple(key),(-1)**(len(dimensions)-sum(bits))))
                    for metric in ['indicative_return','mean_gross_exposure','indicative_max_drawdown','fees']:
                        record[tag+'__'+metric]=sum(sign*cells.loc[key,metric] for key,sign in terms) if all(key in cells.index for key,_ in terms) else np.nan
                rows.append(record)
    return pd.DataFrame(rows)

def prediction_diagnostics(stage):
    from raw_prediction_diagnostics import actual_labels
    year=2025 if stage=='validation' else 2026
    prefix='pre' if year==2025 else 'test'
    truth=pd.read_parquet(ROOT/f'data/{prefix}.parquet')
    truth=truth[pd.to_datetime(truth.signal_date).dt.year.eq(year)].reset_index(drop=True)
    price=pd.read_parquet(ROOT/f'data/{prefix}_prices.parquet')
    calendar=pd.read_parquet(ROOT/f'data/{prefix}_calendar.parquet')
    actual,label_info=actual_labels(truth,price,calendar,year,exclude_source_extreme_warning=False)
    rows=[];daily=[]
    for stream in [s['stream'] for s in registry()[0]]:
        path=ROOT/f'predictions/streams/{stage}/{stream}.parquet'
        if not path.exists():rows.append({'year':year,'stream':stream,'status':'MISSING_PREDICTION'});continue
        p=pd.read_parquet(path);j=p.merge(actual,on=['signal_date','ticker'],how='left',validate='one_to_one')
        prediction_rows=len(p);mature_rows=int(j.label_available.fillna(False).sum());finite_label_rows=int((j.label_available.fillna(False)&np.isfinite(j.y_next_open)).sum())
        j=j[j.label_available.fillna(False)&np.isfinite(j.y_next_open)&np.isfinite(j.mu)]
        y=j.y_next_open.to_numpy(float);mu=j.mu.to_numpy(float)
        record={'year':year,'stream':stream,'status':'DIAGNOSTIC','rows':len(j),'rmse_unclipped':float(np.sqrt(np.mean((mu-y)**2))),
            'rmse_clipped_target':float(np.sqrt(np.mean((mu-np.clip(y,-.2,.2))**2))),
            'prediction_mean':float(np.mean(mu)),'actual_mean':float(np.mean(y)),'prediction_std':float(np.std(mu)),
            'extreme_label_rows':int((np.abs(y)>.2).sum()),'not_a_selection_criterion':True,
            'prediction_rows':prediction_rows,'mature_label_rows':mature_rows,'finite_label_rows':finite_label_rows,'excluded_label_or_prediction_rows':prediction_rows-len(j),
            'label_status_counts':json.dumps(label_info['label_status_counts'],sort_keys=True),
            'endpoint_price_quality_column_available':label_info['quality_column_available'],
            'source_extreme_label_warning_rows':int(truth.label_price_warning.fillna(False).sum()) if year==2025 else 0,
            'source_extreme_warning_rows_excluded':0,
            'label_contract':'Next two positive finite and quality-valid opens plus original maturity/availability; abs-return source extreme warnings are retained, not treated as proven bad prices.'}
        scale=j.sigma.to_numpy(float);residual=(y-mu)/scale
        record['calibrated_scale_mean']=float(np.mean(scale));record['standardized_residual_second_moment']=float(np.mean(residual**2))
        record['residual_1sigma_coverage']=float((np.abs(residual)<=1).mean());record['residual_1_96sigma_coverage']=float((np.abs(residual)<=1.95996398454).mean())
        record['normal_proxy_nll']=float(np.mean(.5*np.log(2*np.pi)+np.log(scale)+.5*residual**2))
        record['normal_proxy_is_claimed_distribution']=stream in DISTRIBUTIONS
        if 'p_up' in j:record['brier_raw_probability']=float(np.mean((j.p_up.to_numpy(float)-(y>0))**2))
        if {'q10','q50','q90'}.issubset(j):
            for a,c in [(.1,'q10'),(.5,'q50'),(.9,'q90')]:
                e=y-j[c].to_numpy(float);record['coverage_'+c]=float((e<=0).mean());record['pinball_'+c]=float(np.mean(np.maximum(a*e,(a-1)*e)))
            record['q10_q90_coverage']=float(((y>=j.q10)&(y<=j.q90)).mean())
        rows.append(record)
        for date,g in j.groupby('signal_date'):
            ic=g.mu.corr(g.y_next_open,method='spearman') if g.mu.nunique()>1 else np.nan
            daily.append({'year':year,'stream':stream,'date':date,'rank_ic':ic,'n':len(g)})
    return pd.DataFrame(rows),pd.DataFrame(daily)

def main():
    out=ROOT/'analysis';out.mkdir(exist_ok=True)
    registry_frame=pd.DataFrame([{**p,'members':'|'.join(p['members'])} for p in registry()[1]])
    summaries=[];coverage=[];solver=[];failures=[];learning_fallbacks=[];risk_inference=[]
    for year in [2025,2026]:
        for batch in sorted((ROOT/f'results/{year}').glob('batch_*')):
            done=batch/'COMPLETE.json';bad=batch/'FAILED.json'
            if done.exists():
                receipt=json.loads(done.read_text(encoding='utf-8'));data=pd.read_csv(batch/'SUMMARY.csv')
                if data.strategy.duplicated().any() or set(data.strategy)!=set(receipt['strategies']):raise RuntimeError('SUMMARY_STRATEGY_COVERAGE_MISMATCH:'+str(batch))
                if sha(batch/'SUMMARY.csv')!=receipt['summary_sha256'] or sha(batch/'metadata.json')!=receipt['metadata_sha256']:raise RuntimeError('REPLAY_RECEIPT_HASH_CHANGED:'+str(batch))
                data['year']=year;summaries.append(data)
                policy=json.loads((batch/'POLICY_RECEIPT.json').read_text(encoding='utf-8'))
                risk_inference.append({'year':year,'batch':batch.name,**policy['risk_fallback_counts'],**policy['scenario_approximations'],
                    'counts_are_queries_not_unique_tickers':True,'fits_during_replay':policy['fit_calls']})
                for status,count in policy['solver_counts'].items():solver.append({'year':year,'batch':batch.name,'status':status,'decisions':count})
                affected={}
                for f in policy['failures']:
                    for strategy in f['strategies']:
                        failures.append({**f,'strategies':None,'strategy':strategy,'year':year,'batch':batch.name})
                        affected[strategy]=affected.get(strategy,0)+1
                for strategy in receipt['strategies']:
                    coverage.append({'year':year,'strategy':strategy,'status':'REPLAYED_WITH_SOLVER_FAILURES' if strategy in affected else 'REPLAYED_DIAGNOSTIC',
                        'batch':batch.name,'reason':'Decision-level failures preserved actual units; see POLICY_FAILURES.csv.' if strategy in affected else '',
                        'solver_failure_records':affected.get(strategy,0)})
            elif bad.exists():
                receipt=json.loads(bad.read_text(encoding='utf-8'))
                for strategy in receipt['strategies']:coverage.append({'year':year,'strategy':strategy,'status':'FAILED','batch':batch.name,'reason':receipt['reason']})
        present={c['strategy'] for c in coverage if c['year']==year}
        for strategy in registry_frame.strategy:
            if strategy not in present:coverage.append({'year':year,'strategy':strategy,'status':'NOT_EXECUTED','batch':'','reason':'Required execution has not completed.'})
    pd.DataFrame(coverage).merge(registry_frame,on='strategy',validate='many_to_one').to_csv(out/'COMBINATION_COVERAGE.csv',index=False)
    formal=registry_frame.copy();formal['year']=2026;formal['status']='BLOCKED_DATA'
    formal['reason']='47271 original UNKNOWN plus 1 GLW event-date conflict; 2204 proven ineligible retained. No 2026 signal day has certified full candidate coverage. Qualified-subpool diagnostics do not supply full-pool TOP20.'
    formal['original_unknown_security_days']=47271;formal['current_unknown_security_days']=47272;formal['certified_complete_signal_days']=0
    formal.to_csv(out/'FORMAL_FULL_POOL_COVERAGE.csv',index=False)
    pd.DataFrame(solver).to_csv(out/'SOLVER_STATUS.csv',index=False)
    pd.DataFrame(risk_inference).to_csv(out/'RISK_INFERENCE_DIAGNOSTICS.csv',index=False)
    pd.DataFrame(failures,columns=['year','batch','strategy','date','risk','optimizer','reason']).to_csv(out/'POLICY_FAILURES.csv',index=False)
    for stage in ['validation','final']:
        garch=json.loads((ROOT/f'models/risk/{stage}/GARCH_FIT_RECORDS.json').read_text(encoding='utf-8'))
        for row in garch:
            if row['status']!='FITTED':learning_fallbacks.append({'stage':stage,**row})
    pd.DataFrame(learning_fallbacks).to_csv(out/'RISK_FIT_FAILURES_AND_FALLBACKS.csv',index=False)
    if not summaries:return
    table=pd.concat(summaries,ignore_index=True).merge(registry_frame,on='strategy',validate='many_to_one')
    if table.duplicated(['year','strategy']).any():raise RuntimeError('DUPLICATE_REPLAYED_ACCOUNT')
    expected={(year,s) for year in [2025,2026] for s in registry_frame.strategy}
    actual=set(zip(table.year,table.strategy));complete=actual==expected
    table['research_status']=np.where(table.year.eq(2026),'OBSERVED_HISTORY_QUALIFIED_SUBPOOL_DIAGNOSTIC','PRE2026_AVAILABLE_CONTEXT_DIAGNOSTIC')
    table['certified_shareholder_total_return']=False;table['selected_for_deployment']=False
    table.to_csv(out/'ALL_POSITIVE_NEGATIVE_RESULTS.csv',index=False)
    core=table[table.target_fusion.eq('none')]
    contrast(core,['year','risk','optimizer','axis'],'stream','ridge','prediction_vs_ridge').to_csv(out/'PREDICTOR_PAIRED_CONTRASTS.csv',index=False)
    contrast(table,['year','stream','optimizer','axis','target_fusion'],'risk','diagonal','risk_vs_diagonal').to_csv(out/'RISK_PAIRED_CONTRASTS.csv',index=False)
    contrast(table,['year','stream','risk','axis','target_fusion'],'optimizer','mean_variance','optimizer_vs_mv').to_csv(out/'OPTIMIZER_PAIRED_CONTRASTS.csv',index=False)
    fusion=core[core.bundle.ne('singleton')]
    contrast(fusion,['year','bundle','risk','optimizer','axis'],'fusion','equal','fusion_vs_equal_members').to_csv(out/'FUSION_PAIRED_CONTRASTS.csv',index=False)
    target=table[table.target_fusion.ne('none')]
    contrast(target,['year','risk','optimizer','axis'],'target_fusion','target_equal','target_median_vs_equal').to_csv(out/'TARGET_FUSION_PAIRED_CONTRASTS.csv',index=False)
    point=core[core.stream.isin(POINT)][['year','risk','optimizer','axis','stream']+METRICS].rename(columns={'stream':'point_expert',**{m:'point_account_'+m for m in METRICS}})
    target_vs_point=target.merge(point,on=['year','risk','optimizer','axis'],how='left',validate='many_to_many')
    for m in METRICS:target_vs_point['delta_vs_point_account_'+m]=target_vs_point[m]-target_vs_point['point_account_'+m]
    target_vs_point['comparison_scope']='Separate actual account paths; same-account expert targets remain in expert matrices, not hypothetical expert NAV.'
    target_vs_point.to_csv(out/'TARGET_FUSION_VS_POINT_ACCOUNT_PATHS.csv',index=False)
    contrast(table,['year','stream','risk','optimizer','target_fusion'],'axis','joint','component_vs_joint').to_csv(out/'BUY_SELL_CASH_PAIRED_CONTRASTS.csv',index=False)
    factorial_interactions(table).to_csv(out/'LAYER_INTERACTIONS.csv',index=False)
    cooperation_interactions(table).to_csv(out/'FUSION_LAYER_INTERACTIONS.csv',index=False)
    for axis in AXES:
        part=core[core.axis.eq(axis)]
        for dim in ['stream','fusion','risk','optimizer']:
            dimensions=['year','bundle',dim] if dim=='fusion' else ['year',dim]
            part.groupby(dimensions)[METRICS].agg(['count','mean','median','min','max']).to_csv(out/f'{axis}_{dim.upper()}_COMPARISON.csv')
    diagnostic_receipt=json.loads((out/'STREAM_PREDICTION_DIAGNOSTICS_RECEIPT.json').read_text(encoding='utf-8'))
    if diagnostic_receipt['status']!='PASS_ALL150_FROZEN_STREAM_DIAGNOSTICS' or diagnostic_receipt['analysis_rows']!=150:raise RuntimeError('ALL_STREAM_DIAGNOSTICS_INCOMPLETE')
    if diagnostic_receipt['fit_calls'] or diagnostic_receipt['learning_update_calls'] or diagnostic_receipt['selection_or_tuning_calls']:raise RuntimeError('STREAM_DIAGNOSTIC_SCOPE_CHANGED')
    for file,h in diagnostic_receipt['source_sha256'].items():
        if sha(ROOT/file)!=h:raise RuntimeError('STREAM_DIAGNOSTIC_SOURCE_CHANGED:'+file)
    for file,h in diagnostic_receipt['output_sha256'].items():
        if sha(out/file)!=h:raise RuntimeError('STREAM_DIAGNOSTIC_OUTPUT_CHANGED:'+file)
    diagnostics=pd.read_csv(out/'PREDICTION_DIAGNOSTICS.csv')
    expected_diagnostics={(year,s['stream']) for year in [2025,2026] for s in registry()[0]}
    if len(diagnostics)!=150 or set(zip(diagnostics.year,diagnostics.stream))!=expected_diagnostics:raise RuntimeError('STREAM_DIAGNOSTIC_EXACT_KEYS_FAILED')
    table.sort_values(['year','axis','indicative_return'],ascending=[True,True,False]).groupby(['year','axis']).head(20).to_csv(out/'DESCRIPTIVE_TOP20_COMPLETE_STRATEGIES.csv',index=False)
    write_json(out/'ANALYSIS_RECEIPT.json',{'rows':len(table),'expected_rows':2*11088,'complete':complete,'unique_account_keys_verified':True,
        'selection_or_retraining_calls':0,'formal_2026_full_pool_status':'BLOCKED_DATA','factorial_contrasts':'Matched complete strategy accounts; interactions are difference-in-differences.',
        'original_unknown_candidate_keys':47271,'current_unknown_candidate_keys':47272,'proven_ineligible_keys':2204,'currently_not_buy_eligible_keys':49476,
        'exposure_normalization':'Gross-return/lagged invested fraction on >1% exposure days; descriptive, not another tradable account or proof of learning.'})

if __name__=='__main__':main()
