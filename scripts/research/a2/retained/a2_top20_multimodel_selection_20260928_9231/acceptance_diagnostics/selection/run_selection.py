"""Read-only fixed-state sorting diagnostics; no fitting or account replay."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from scipy.stats import spearmanr
import torch
from threadpoolctl import threadpool_limits

OUT=Path(__file__).resolve().parent
ROOT=OUT.parent.parent
sys.path.insert(0,str(ROOT))
import evaluate as ev
import ensemble as en
import values as vm
from neural import NeuralAdapter,project

YEAR_END={2025:'2025-12-29',2026:'2026-09-22'}
GLW_CONFLICT_DATES={pd.Timestamp('2026-02-26'),pd.Timestamp('2026-02-27')}
WEIGHT=.95/20
COST_ROUND_TRIP=.002
ACTION_INDEX=2
POLICIES=ev.NAMES


def write(path,obj):ev.write(path,obj)


def ranking(score,tickers):
    score=np.asarray(score,float)
    if not np.isfinite(score).all():raise ValueError('NONFINITE_SORTING_SCORE')
    order=np.lexsort((np.asarray(tickers,str),-score))
    rank=np.empty(len(score),float);rank[order]=np.arange(1,len(score)+1)
    top=rank<=20
    ties=pd.Series(score).map(pd.Series(score).value_counts()).to_numpy(int)
    return rank,top,ties


def preference(weight):
    weight=np.asarray(weight,float)
    return -((.05-weight)/.1)**2+(weight/.1)**2


def finish_projection(weight):
    weight=np.asarray(weight,float).copy()
    keep=np.argsort(-weight,kind='stable')[:20]
    mask=np.zeros(len(weight));mask[keep]=1;weight*=mask
    if weight.sum()>.95:weight*=.95/weight.sum()
    return weight


def label_panel(panel,prices,calendar,year):
    """Join next two original sessions after signal without filtering candidates."""
    cal=pd.DatetimeIndex(calendar)
    next1={d:cal[i+1] if i+1<len(cal) else pd.NaT for i,d in enumerate(cal)}
    next2={d:cal[i+2] if i+2<len(cal) else pd.NaT for i,d in enumerate(cal)}
    f=panel.copy()
    f['signal_date']=pd.to_datetime(f.signal_date)
    f['candidate_eligible']=f.new_buy_eligible.astype(bool)
    f['feature_available']=np.isfinite(f[vm.FEATURES].to_numpy(float)).all(axis=1)
    f['ranking_eligible']=f.candidate_eligible&f.feature_available
    f['entry_date']=f.signal_date.map(next1)
    f['exit_date']=f.signal_date.map(next2)
    if prices.duplicated(['trade_date','ticker']).any():raise ValueError('DUPLICATE_PRICE_KEY')
    px=prices.copy()
    if 'price_quality_warning' not in px:px['price_quality_warning']=False
    else:px['price_quality_warning']=px.price_quality_warning.fillna(True).astype(bool)
    if 'price_qualification_reason' not in px:px['price_qualification_reason']='not_provided_in_original_source'
    for name in ['entry','exit']:
        piece=px[['trade_date','ticker','open','price_quality_warning','price_qualification_reason']].rename(columns={
            'trade_date':f'{name}_date','open':f'{name}_open',
            'price_quality_warning':f'{name}_warning','price_qualification_reason':f'{name}_qualification_reason'})
        f=f.merge(piece,on=['ticker',f'{name}_date'],how='left',validate='many_to_one')
    f['input_conflict']=f.ticker.eq('GLW')&f.signal_date.eq(pd.Timestamp('2026-02-26'))
    conflict_dates=set(f.loc[f.input_conflict&f.ranking_eligible,'signal_date'])
    f['input_conflict_day']=f.signal_date.isin(conflict_dates)
    f['known_event_conflict']=f.ticker.eq('GLW')&(f.entry_date.isin(GLW_CONFLICT_DATES)|f.exit_date.isin(GLW_CONFLICT_DATES))
    f['source_label_warning']=f.label_price_warning.fillna(True).astype(bool) if 'label_price_warning' in f else False
    entry_good=np.isfinite(f.entry_open)&f.entry_open.gt(0)
    exit_good=np.isfinite(f.exit_open)&f.exit_open.gt(0)
    raw_valid=entry_good&exit_good
    f['raw_label_available']=raw_valid
    f['raw_forward_return']=np.where(raw_valid,f.exit_open/f.entry_open-1,np.nan)
    reasons=[]
    for row in f.itertuples():
        codes=[]
        if pd.isna(row.entry_date) or pd.isna(row.exit_date):codes.append('NO_NEXT_TWO_SESSIONS')
        if not (np.isfinite(row.entry_open) and row.entry_open>0):codes.append('MISSING_OR_INVALID_ENTRY_OPEN')
        if not (np.isfinite(row.exit_open) and row.exit_open>0):codes.append('MISSING_OR_INVALID_EXIT_OPEN')
        if pd.notna(row.entry_warning) and bool(row.entry_warning):codes.append('ENTRY_PRICE_WARNING')
        if pd.notna(row.exit_warning) and bool(row.exit_warning):codes.append('EXIT_PRICE_WARNING')
        if row.source_label_warning:codes.append('SOURCE_LABEL_WARNING')
        if row.known_event_conflict:codes.append('KNOWN_EVENT_CONFLICT')
        reasons.append('|'.join(codes) if codes else 'OBSERVABLE_ORIGINAL_PRICE_COORDINATE')
    f['label_status']=reasons
    f['label_available']=f.label_status.eq('OBSERVABLE_ORIGINAL_PRICE_COORDINATE')
    f['forward_return']=f.raw_forward_return.where(f.label_available)
    f['coverage_status']='available_original_feature_pool' if year==2025 else 'retrospectively_qualified_subset_not_full_13f_universe'
    f['formal_price_certified']=False
    if 'y_next_open' in f:
        comparable=f.label_available&np.isfinite(f.y_next_open)
        error=np.abs(f.loc[comparable,'forward_return']-f.loc[comparable,'y_next_open'])
        if len(error) and error.max()>1e-10:raise ValueError('ORIGINAL_LABEL_COORDINATE_MISMATCH')
    return f


class Scorer:
    def __init__(self,stage):
        self.base=en.BasePredictions(stage)
        self.q90=vm.load_policy('q90',stage).models['q90']
        self.rl=NeuralAdapter('rl',stage=stage)
        self.zero=NeuralAdapter('rl',zero=True,stage=stage)
        self.meta=en.EnsemblePolicy('ensemble_stacking',stage).meta

    def neural_weights(self,day,adapter):
        x=np.clip((day[vm.FEATURES].to_numpy(float)-adapter.mean)/adapter.scale,-8,8)
        obs=torch.tensor(np.column_stack([x,np.zeros(len(day)),np.full(len(day),.95),np.zeros(len(day))]),dtype=torch.float32)
        upper=torch.full((len(day),),.1)
        with torch.no_grad():
            return [project(model(obs),upper=upper,max_names=20,max_exposure=.95).numpy() for model in adapter.models]

    def score(self,day):
        ranks,downside,raw,mlp=self.base.predict(day,0.,.95,0.)
        x=day[vm.FEATURES].to_numpy(float);n=len(day)
        mapped=vm.mapped_features(np.repeat(x,5,axis=0),np.zeros(n*5),np.full(n*5,.95),
            np.zeros(n*5),np.tile(vm.ACTIONS,n))
        raw['q90']=vm.predict_values(self.q90,'q90',mapped).reshape(n,5)
        scores={f'joint_{name}':raw[name][:,2]-raw[name][:,0] for name in ['ridge','elastic_net','logistic','hgb','q10','q50','q90','mlp']}
        q=np.stack([raw[name] for name in ['q10','q50','q90']],axis=-1)
        q.sort(axis=-1);qr=q[:,:,1]-.25*(q[:,:,1]-q[:,:,0])
        scores['joint_quantile_risk']=qr[:,2]-qr[:,0]
        rp=self.neural_weights(day,self.rl);zp=self.neural_weights(day,self.zero)
        projected={'joint_mlp':mlp,'joint_rl_seed20260928':rp[0],'joint_rl_seed20260929':rp[1],
            'joint_rl_ensemble':finish_projection(np.mean(rp,axis=0)),
            'joint_rl_zero_control':finish_projection(np.mean(zp,axis=0))}
        for name,weight in projected.items():scores[name]=preference(weight)
        scores['joint_hgb_lw']=scores['joint_hgb'].copy();scores['joint_hgb_pca']=scores['joint_hgb'].copy()
        contributions=[]
        for name in ['ensemble_equal','ensemble_disagreement','ensemble_stacking']:
            scores[name]=en.fuse(ranks,downside,name,self.meta if name=='ensemble_stacking' else None)[:,2]
            coef=self.meta.coef_ if name=='ensemble_stacking' else np.full(6,1/6)
            frame=day[['signal_date','ticker']].copy();frame['policy']=name
            for j,base in enumerate(en.BASE_NAMES):frame[f'contribution_{base}']=ranks[:,2,j]*coef[j]
            frame['disagreement_penalty']=.25*ranks[:,2,:].std(axis=-1) if name=='ensemble_disagreement' else 0.
            frame['downside_penalty']=.25*downside[:,2] if name=='ensemble_disagreement' else 0.
            frame['reference_score']=scores[name]
            reconstructed=frame[[f'contribution_{b}' for b in en.BASE_NAMES]].sum(axis=1)-frame.disagreement_penalty-frame.downside_penalty
            if not np.allclose(reconstructed,scores[name],rtol=1e-11,atol=1e-12):raise ValueError('CONTRIBUTION_RECONCILIATION')
            contributions.append(frame)
        comp=day[['signal_date','ticker']].copy()
        for j,name in enumerate(en.BASE_NAMES):
            comp[f'rank_{name}']=ranks[:,2,j]
            comp[f'raw_advantage_{name}']=raw[name][:,2]-raw[name][:,0]
        comp['six_arm_mean']=ranks[:,2,:].mean(axis=-1)
        comp['six_arm_disagreement']=ranks[:,2,:].std(axis=-1)
        comp['q10_downside_rank']=downside[:,2]
        comp['mlp_projected_weight']=mlp
        return scores,projected,comp,pd.concat(contributions,ignore_index=True)


def safe_ic(score,y):
    valid=np.isfinite(y)&np.isfinite(score)
    if valid.sum()<3 or np.unique(score[valid]).size<2 or np.unique(y[valid]).size<2:return np.nan
    return float(spearmanr(score[valid],y[valid]).statistic)


def daily_metric(day,policy,score,rank,top,ties):
    y=day.forward_return.to_numpy(float);valid=np.isfinite(y)
    complete=bool(valid.all() and not day.input_conflict_day.any())
    n=int(top.sum());observed=top&valid;rest=(~top)&valid
    top_mean=float(np.mean(y[observed])) if observed.any() else np.nan
    rest_mean=float(np.mean(y[rest])) if rest.any() else np.nan
    cash=policy=='cash_control'
    gross=0. if cash else float(WEIGHT*np.sum(y[top])) if valid[top].all() else np.nan
    net=gross-WEIGHT*n*COST_ROUND_TRIP
    observed_gross=float(WEIGHT*np.sum(y[observed])) if observed.any() else 0. if cash else np.nan
    ic=np.nan if cash else safe_ic(score,y)
    boundary_score=score[np.flatnonzero(rank==min(20,len(day)))[0]] if not cash and len(day) else np.nan
    return dict(year=int(day.signal_date.iloc[0].year),signal_date=day.signal_date.iloc[0],policy=policy,
        candidate_count=len(day),label_available_count=int(valid.sum()),label_coverage=float(valid.mean()),
        complete_common_pool=complete,input_conflict_day=bool(day.input_conflict_day.any()),
        price_complete_pool=bool(valid.all()),selected_count=n,selected_label_count=int(observed.sum()),
        top20_positive_score_count=int(np.sum(score[top]>0)),
        selected_label_coverage=float(valid[top].mean()) if n else 1.,
        score_unique_count=int(np.unique(score[np.isfinite(score)]).size),
        tied_security_fraction=float(np.mean(ties>1)) if not cash else np.nan,
        boundary_tie_count=int(np.sum(score==boundary_score)) if np.isfinite(boundary_score) else 0,
        observed_ic=ic,observed_top20_mean_return=top_mean,observed_rest_mean_return=rest_mean,
        observed_top20_minus_rest=top_mean-rest_mean,
        simple_gross_if_selected_labels_complete=gross,simple_net_if_selected_labels_complete=net,
        simple_target_exposure=WEIGHT*n,simple_round_trip_cost=WEIGHT*n*COST_ROUND_TRIP,
        observable_selected_gross_contribution=observed_gross,
        observable_selected_net_contribution=observed_gross-WEIGHT*int(observed.sum())*COST_ROUND_TRIP,
        main_ic=ic if complete else np.nan,main_top20_minus_rest=top_mean-rest_mean if complete else np.nan,
        main_simple_gross=gross if complete else np.nan,main_simple_net=net if complete else np.nan)


def method_mapping():
    rows=[]
    for name in POLICIES:
        if name=='cash_control':kind='no_ranking_cash_control';formula='no score or ranking; simple independent return zero'
        elif name in ['joint_hgb_lw','joint_hgb_pca']:kind='same_hgb_score_risk_decision_layer';formula='same fixed HGB score; covariance optimization belongs to original account decision layer'
        elif name.startswith('joint_rl') or name=='joint_mlp':kind='projected_weight_conditional_preference';formula='-((0.05-p)/0.1)^2 + (p/0.1)^2; p uses original hard TOP20 projection; many ties and full-section dependence'
        elif name=='joint_quantile_risk':kind='conditional_quantile_utility';formula='sort Q10/Q50/Q90 per action; Q50-0.25*(Q50-Q10), then 5% minus zero'
        elif name.startswith('ensemble_'):kind='original_six_arm_fusion';formula='original signed ranks and frozen fusion at 5% action versus zero'
        else:kind='conditional_action_value';formula='frozen action utility at 5% minus action zero; logistic is unitless positive-reward probability advantage'
        rows.append(dict(policy=name,rank_kind=kind,formula=formula,native_return_forecast=False,
            reference_current_weight=0.,reference_cash_weight=.95,reference_holding_age=0,
            score_action=.05,score_baseline_action=0.,risk_layer_alias=name in ['joint_hgb_lw','joint_hgb_pca']))
    return pd.DataFrame(rows)


def run(year):
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/f'COMPLETE_{year}.json').exists() or (OUT/f'scores_{year}.parquet').exists():
        raise RuntimeError('EXISTING_DIAGNOSTICS_PRESERVED')
    guard=ev.forbid_fitting();stage='validation' if year==2025 else 'final'
    if year==2025:
        paths=[ev.DATA/'pre2026_joint_context.parquet',ev.PRICE]
        panel=pd.read_parquet(paths[0]);panel=panel[panel.signal_date.ge('2025-01-01')&panel.signal_date.le(YEAR_END[year])].copy()
        prices=pd.read_parquet(paths[1]);calendar=pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq('QQQ')&prices.trade_date.ge('2025-01-01'),'trade_date'].unique()))
    else:
        paths=[ev.QUALIFIED/'test_features_context.parquet',ev.QUALIFIED/'test_prices.parquet',ev.DATA/'calendar.parquet']
        panel=pd.read_parquet(paths[0]);panel=panel[panel.signal_date.ge('2026-01-01')&panel.signal_date.le(YEAR_END[year])].copy()
        prices=pd.read_parquet(paths[1]);calendar=pd.DatetimeIndex(pd.read_parquet(paths[2]).query('is_test').trade_date)
    if panel.duplicated(['signal_date','ticker']).any():raise ValueError('DUPLICATE_CANDIDATE_KEY')
    paths += ev.model_files()+[ROOT/'acceptance_diagnostics/DIAGNOSTIC_CONTRACT.md',Path(__file__)]
    frozen={str(p):ev.sha(p) for p in sorted(set(paths))}
    write(OUT/f'PRE_INFERENCE_{year}.json',dict(status='FROZEN',year=year,stage=stage,
        created_utc=pd.Timestamp.now(tz='UTC').isoformat(),source_sha256=frozen,
        reference_state=dict(current_weight=0,cash_weight=.95,age=0),action_score='5%-0%',
        signal_end=YEAR_END[year],simple_weight_per_name=WEIGHT,round_trip_cost=COST_ROUND_TRIP,
        simple_compounding=False,fit_permitted=False,
        known_conflicts=dict(GLW_price_dates=['2026-02-26','2026-02-27'],GLW_signal_feature_date='2026-02-26'),
        main_eligibility='entire original available new-buy feature pool has qualified forward labels and no known input conflict; does not certify original universe or vendor arrival time'))
    candidates=label_panel(panel,prices,calendar,year)
    keep=['signal_date','ticker','candidate_eligible','feature_available','ranking_eligible','entry_date','exit_date',
        'entry_open','exit_open','entry_warning','exit_warning','entry_qualification_reason','exit_qualification_reason',
        'input_conflict','input_conflict_day','known_event_conflict','source_label_warning','raw_label_available',
        'raw_forward_return','label_status','label_available','forward_return','coverage_status','formal_price_certified']
    for c in ['new_buy_eligible','active_13f_quarter','quarter','latest_filing_date','quarter_effective_date','qualification_reason','pool_scope']:
        if c in candidates:keep.append(c)
    candidates[keep].to_parquet(OUT/f'candidates_{year}.parquet',index=False)
    usable=candidates[candidates.ranking_eligible].copy()
    if usable.empty:raise ValueError('NO_RANKING_CANDIDATES')
    scorer=Scorer(stage)
    writer=None;components=[];contributions=[];daily=[];start=time.monotonic();nrows=0
    try:
        for i,(date,day) in enumerate(usable.groupby('signal_date',sort=True)):
            day=day.sort_values('ticker',kind='stable').reset_index(drop=True)
            observable=day[['signal_date','ticker','new_buy_eligible',*vm.FEATURES]].copy()
            with threadpool_limits(limits=2),torch.no_grad():scores,projected,comp,cont=scorer.score(observable)
            comp['input_conflict_day']=bool(day.input_conflict_day.any())
            components.append(comp);contributions.append(cont);chunks=[]
            for name in POLICIES:
                if name=='cash_control':
                    score=np.full(len(day),np.nan);rank=np.full(len(day),np.nan);top=np.zeros(len(day),bool);ties=np.zeros(len(day),int)
                else:score=scores[name];rank,top,ties=ranking(score,day.ticker)
                chunk=day[['signal_date','ticker']].copy();chunk['policy']=name
                chunk['reference_score']=score;chunk['reference_rank']=rank;chunk['reference_top20']=top
                chunk['reference_score_positive']=score>0
                chunk['rank_tie_group_size']=ties
                chunk['reference_projection_weight']=projected.get(name,np.full(len(day),np.nan))
                chunk['ranking_eligible']=True;chunk['label_available']=day.label_available.to_numpy()
                chunk['label_status']=day.label_status.to_numpy();chunk['input_conflict_day']=day.input_conflict_day.to_numpy()
                chunk['forward_return']=day.forward_return.to_numpy();chunks.append(chunk)
                daily.append(daily_metric(day,name,score,rank,top,ties))
            scoreframe=pd.concat(chunks,ignore_index=True)
            table=pa.Table.from_pandas(scoreframe,preserve_index=False)
            if writer is None:writer=pq.ParquetWriter(OUT/f'scores_{year}.parquet',table.schema,compression='zstd')
            writer.write_table(table);nrows+=len(scoreframe)
            if i%40==0:print(json.dumps(dict(year=year,processed_days=i+1,signal=str(date.date()),seconds=round(time.monotonic()-start,2))),flush=True)
    finally:
        if writer is not None:writer.close()
    pd.concat(components,ignore_index=True).to_parquet(OUT/f'components_{year}.parquet',index=False)
    pd.concat(contributions,ignore_index=True).to_parquet(OUT/f'ensemble_contributions_{year}.parquet',index=False)
    pd.DataFrame(daily).to_parquet(OUT/f'daily_{year}.parquet',index=False)
    pd.DataFrame(daily).to_csv(OUT/f'daily_{year}.csv',index=False)
    if guard['attempts']!=0:raise ValueError('FIT_GUARD_ATTEMPT')
    for path,digest in frozen.items():
        if ev.sha(path)!=digest:raise ValueError(f'FROZEN_SOURCE_CHANGED:{path}')
    outputs={str(p):ev.sha(p) for p in OUT.glob(f'*_{year}.*') if p.suffix in ['.parquet','.csv']}
    write(OUT/f'COMPLETE_{year}.json',dict(status='PASS_FROZEN_SELECTION_DIAGNOSTIC',year=year,stage=stage,
        signal_days=usable.signal_date.nunique(),candidate_rows=len(candidates),ranking_rows=len(usable),
        score_rows=nrows,policies=len(POLICIES),seconds=time.monotonic()-start,fit_attempts=guard['attempts'],
        source_sha256_unchanged=True,output_sha256=outputs,
        main_price_complete_is_not_formal_certification=True,original_full_pool_certified=False))
    print(json.dumps(dict(status='COMPLETE',year=year,fit_attempts=guard['attempts'],seconds=time.monotonic()-start)),flush=True)


def mean(series):
    vals=series.dropna().to_numpy(float)
    return float(np.mean(vals)) if len(vals) else None


def aggregate():
    rows=[];year_info={}
    for year in [2025,2026]:
        receipt=json.loads((OUT/f'COMPLETE_{year}.json').read_text(encoding='utf-8'))
        if receipt['fit_attempts']!=0:raise ValueError('UNEXPECTED_FITTING')
        d=pd.read_parquet(OUT/f'daily_{year}.parquet')
        candidate=pd.read_parquet(OUT/f'candidates_{year}.parquet')
        perday=d[d.policy.eq('joint_hgb')]
        year_info[str(year)]={'signal_days':receipt['signal_days'],'ranking_candidate_rows':receipt['ranking_rows'],
            'complete_common_pool_days':int(perday.complete_common_pool.sum()),
            'incomplete_or_conflicted_days':int((~perday.complete_common_pool).sum()),
            'known_input_conflict_days':int(perday.input_conflict_day.sum()),
            'label_status_counts':candidate.loc[candidate.ranking_eligible,'label_status'].value_counts().to_dict(),
            'fit_attempts':receipt['fit_attempts']}
        for policy,g in d.groupby('policy',sort=False):
            for subset in ['complete_common_pool','incomplete_observable_only']:
                part=g[g.complete_common_pool] if subset=='complete_common_pool' else g[~g.complete_common_pool]
                rows.append(dict(year=year,policy=policy,subset=subset,signal_days=len(part),
                    total_signal_days=len(g),ic_available_days=int(part.observed_ic.notna().sum()),
                    simple_full_top20_available_days=int(part.simple_net_if_selected_labels_complete.notna().sum()),
                    mean_label_coverage=mean(part.label_coverage),mean_selected_coverage=mean(part.selected_label_coverage),
                    mean_ic=mean(part.observed_ic),mean_top20_minus_rest=mean(part.observed_top20_minus_rest),
                    mean_period_simple_gross=mean(part.simple_gross_if_selected_labels_complete),
                    mean_period_simple_net=mean(part.simple_net_if_selected_labels_complete),
                    mean_observable_selected_gross_contribution=mean(part.observable_selected_gross_contribution),
                    mean_observable_selected_net_contribution=mean(part.observable_selected_net_contribution),
                    mean_tied_security_fraction=mean(part.tied_security_fraction),
                    mean_top20_positive_score_count=mean(part.top20_positive_score_count),
                    mean_boundary_tie_count=mean(part.boundary_tie_count),
                    mean_score_unique_count=mean(part.score_unique_count)))
    summary=pd.DataFrame(rows);summary.to_csv(OUT/'aggregate.csv',index=False)
    method_mapping().to_csv(OUT/'method_mapping.csv',index=False)
    write(OUT/'SUMMARY.json',dict(status='PASS_FROZEN_DIAGNOSTIC',years=year_info,
        methods=method_mapping().to_dict(orient='records'),aggregate=rows,
        scope='Fixed reference-state selection diagnostic on original available pools; not actual-account decisions or original-universe certification',
        reference_state=dict(current_weight=0,cash_weight=.95,holding_age=0),
        score='frozen conditional preference: five-percent action minus zero action',
        simple_period_formula='0.0475*sum(selected forward returns) - 0.0475*selected_count*0.002; only finite when every selected label is qualified',
        simple_compounding=False,annualization=False,capacity_simulation=False,
        incomplete_observable_note='Observed IC and spread use only qualified observed labels after fixed rankings. Partial contribution is NOT a portfolio return; full-top20 simple return may still be available on some incomplete-pool days.',
        certification_note='Price-complete means local source/known-conflict gate only. Full 13F coverage, company-action correctness and historic vendor arrival timestamps remain unproven.',
        fit_attempts=0))
    lines=['# 冻结参考状态排序诊断','',
        '已完成原模型的只读排序诊断；没有重新训练、调参、更新权重或改写原回放。固定状态为单票持仓0、现金95%、持仓年龄0，统一分数是5%动作相对0动作的条件偏好。此榜单不代表原账本的实际下单依据。','',
        '简单检验每期独立：每只入选股票4.75%、最多20只，下一开盘买入、再下一开盘卖出，往返20bp按投入本金扣除。无复利、无年化、无容量或连续换仓模拟；报告单期均值，不将其合成为账户收益。','',
        '| 年份 | 原信号日 | 原价格门控下完整共同集合日 | 不完整/冲突日 |','| --- | ---: | ---: | ---: |']
    for year,info in year_info.items():lines.append(f"| {year} | {info['signal_days']} | {info['complete_common_pool_days']} | {info['incomplete_or_conflicted_days']} |")
    lines += ['', '“原价格门控下完整”只指本地已有可买特征池的标签通过原价格警告与已知冲突门槛；2025价格源没有价格警告列，默认未打标只表示内部可计算，不证明原始波动或公司行动已认证，亦不能等同于原始全13F宇宙或供应商到达时钟已认证。GLW在2026-02-26/27作为标签端点时记缺失冲突；02-26信号的输入冲突使当日不得进入主汇总，原股票和榜单完整保留。','',
        '逐方法结果见 aggregate.csv，逐日 IC、TOP20-rest、标签覆盖及简单毛/净贡献见 daily_2025.csv / daily_2026.csv。主结论只能来自 complete_common_pool；incomplete_observable_only 是标签可见子样本的事后诊断，部分持仓贡献不等于组合收益。','',
        '固定TOP20检验即使全部分数为负也照既定规则取前20只，不代表原策略建议买入。逐日保存TOP20正分数数量与第20位并列数量。MLP/RL分数来自原TOP20投影权重，因此有大量并列且依赖同日横截面；ticker升序仅用于预先固定的并列决胜，不能把并列中的精确序号误说成模型区分能力。Logistic及融合排名是条件偏好而非原生收益预测。LW/PCA引用完全相同的HGB分数，它们的差异在原仓位风险决策层；现金对照没有排序。','',
        'scores_*.parquet按policy/signal_date/ticker保存排名、TOP20与标签状态；candidates_*.parquet保留候选资格、端点价格及缺失/冲突原因；components_*.parquet保存六臂signed rank与分歧；ensemble_contributions_*.parquet保存冻结贡献及惩罚，逐行核对贡献和等于融合分数。所有fit守卫attempts=0，模型与输入哈希运行前后相同。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(status='SUMMARY_COMPLETE',years=year_info),ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--year',type=int,choices=[2025,2026]);parser.add_argument('--summarize',action='store_true')
    args=parser.parse_args()
    if args.summarize:aggregate()
    elif args.year:run(args.year)
    else:parser.error('Choose --year or --summarize')
