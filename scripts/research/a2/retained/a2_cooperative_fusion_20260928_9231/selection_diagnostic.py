"""Frozen fixed-state sorting diagnostics; reuse original labels and controls."""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import torch
from threadpoolctl import threadpool_limits

import policy as cp

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'selection'
OLD=cp.BASE_ROOT/'acceptance_diagnostics/selection'
spec=importlib.util.spec_from_file_location('frozen_original_selection',OLD/'run_selection.py')
old=importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)
ev=old.ev
if Path(ev.__file__).resolve()!=cp.BASE_ROOT/'evaluate.py':
    raise RuntimeError('WRONG_ORIGINAL_EVALUATOR_IMPORT')
CONTROLS=['joint_hgb','ensemble_equal','ensemble_stacking']
EXPECTED={2025:dict(days=248,complete=245,rows=110438),2026:dict(days=181,complete=88,rows=62393)}
STATE=dict(current_weight=0.,cash_weight=.95,age=0.)
ACTION_INDEX=2


def write(path,obj):ev.write(path,obj)


class Streams:
    def __init__(self):self.writers={};self.rows={}
    def add(self,path,frame):
        table=pa.Table.from_pandas(frame,preserve_index=False)
        if path not in self.writers:
            self.writers[path]=pq.ParquetWriter(path,table.schema,compression='zstd')
            self.rows[path]=0
        else:table=table.cast(self.writers[path].schema)
        self.writers[path].write_table(table)
        self.rows[path]+=len(frame)
    def close(self):
        for writer in self.writers.values():writer.close()


def inputs(year):
    feature=ev.DATA/'pre2026_joint_context.parquet' if year==2025 else ev.QUALIFIED/'test_features_context.parquet'
    sources=ev.model_files()+[feature,OLD/f'candidates_{year}.parquet',OLD/f'daily_{year}.parquet',
        OLD/f'components_{year}.parquet',OLD/f'COMPLETE_{year}.json',OLD/'run_selection.py',Path(__file__),
        ROOT/'policy.py',ROOT/'meta_models.py',ROOT/'gate.py',ROOT/'data_context.py',ROOT/'EXPERIMENT_CONTRACT.md']
    for folder in ['meta_artifacts','gate_artifacts']:
        sources.extend(p for p in (ROOT/folder).glob('*') if p.suffix in ['.json','.joblib','.pt','.npz'])
    return feature,{str(p):ev.sha(p) for p in sorted(set(sources))}


def forbid_fit():
    guard=ev.forbid_fitting()
    import scipy.optimize
    import meta_models
    def denied(*args,**kwargs):
        guard['attempts']+=1
        raise RuntimeError('NNLS_FORBIDDEN_DURING_SELECTION')
    scipy.optimize.nnls=denied;meta_models.nnls=denied
    return guard


def diagnostic_frame(day,name,scores,diagnostic):
    n=len(day);frame=day[['signal_date','ticker']].copy();frame['policy']=name
    frame['reference_score']=scores[:,ACTION_INDEX]
    frame['reference_action_values']=[x.tolist() for x in scores]
    for key,value in diagnostic.items():
        array=np.asarray(value)
        if array.ndim>=2 and array.shape[:2]==(n,5):array=array[:,ACTION_INDEX]
        if array.ndim==0:frame[key]=array.item()
        elif array.shape==(n,):frame[key]=array
        elif array.shape==(n,6):
            for j,base in enumerate(cp.BASE_NAMES):frame[f'{key}_{base}']=array[:,j]
        else:raise ValueError(f'UNHANDLED_DIAGNOSTIC_SHAPE:{name}:{key}:{array.shape}')
    if name in ['fusion_fixed_non_equal','fusion_conditional_gate']:
        reconstructed=sum(frame[f'contributions_{base}'].to_numpy() for base in cp.BASE_NAMES)
        kind='additive_six_expert_score_terms'
    elif name=='fusion_learned_weights':
        reconstructed=sum(frame[f'contribution_rank_{base}'].to_numpy() for base in cp.BASE_NAMES)
        kind='additive_nnls_raw_coefficient_score_terms'
    elif name=='fusion_target_decisions':
        mixed=sum(frame[f'target_contributions_{base}'].to_numpy() for base in cp.BASE_NAMES)
        if not np.allclose(mixed,frame.mixed_target,atol=1e-12,rtol=1e-12):raise ValueError('MIXED_TARGET_RECONCILIATION')
        reconstructed=10.*mixed-.25
        frame['score_transform_constant']=-.25
        kind='additive_target_weights_then_squared_distance_score; score5minus0=10*mixed_target-.25'
    else:
        reconstructed=frame.anchor_prediction.to_numpy()+frame.residual_prediction.to_numpy()
        kind='anchor_plus_residual_score; zero_rank_sensitivities_are_nonadditive_noncausal'
        if name=='fusion_hgb_then_linear':
            terms=[c for c in frame if c.startswith('linear_residual_contribution_')]
            if not np.allclose(frame[terms].sum(axis=1),frame.residual_prediction,atol=1e-10,rtol=1e-10):
                raise ValueError('LINEAR_RESIDUAL_TERM_RECONCILIATION')
    error=float(np.abs(reconstructed-scores[:,ACTION_INDEX]).max())
    if error>1e-8:raise ValueError(f'SCORE_DECOMPOSITION_RECONCILIATION:{name}:{error}')
    frame['diagnostic_semantic']=kind
    return frame,error


def run(year):
    OUT.mkdir(exist_ok=True)
    if (OUT/f'PRE_INFERENCE_{year}.json').exists() or (OUT/f'scores_{year}.parquet').exists():
        raise RuntimeError('EXISTING_SELECTION_OUTPUT_PRESERVED')
    torch.set_num_threads(2)
    guard=forbid_fit();stage='validation' if year==2025 else 'final'
    feature,frozen=inputs(year)
    write(OUT/f'PRE_INFERENCE_{year}.json',dict(status='FROZEN',created_utc=pd.Timestamp.now(tz='UTC'),
        year=year,stage=stage,source_sha256=frozen,policies=cp.NAMES,controls=CONTROLS,
        reference_state=STATE,score='5 percent action minus zero action',
        ranking='Full original ranking_eligible pool first; descending score then ascending ticker; future labels never filter top20',
        labels='Unmodified original candidates table; no relabeling or additional price reads',
        simple_weight=.0475,round_trip_cost=.002,independent_single_period=True,compounding=False,
        fitting_allowed=False,hyperparameter_search_trials=0,expected=EXPECTED[year],
        scope='Already observed history; not new blind test or full 13F price/universe certification',
        sensitivity='One base rank set to zero: descriptive nonadditive perturbation, not causal attribution'))
    candidates=pd.read_parquet(OLD/f'candidates_{year}.parquet')
    columns=['signal_date','ticker','new_buy_eligible',*cp.vm.FEATURES]
    panel=pd.read_parquet(feature,columns=columns)
    panel=panel[panel.signal_date.ge(f'{year}-01-01')&panel.signal_date.le(old.YEAR_END[year])].copy()
    keys=['signal_date','ticker']
    if panel.duplicated(keys).any() or candidates.duplicated(keys).any():raise ValueError('DUPLICATE_CANDIDATE_FEATURE_KEY')
    joined=candidates.merge(panel,on=keys,how='left',validate='one_to_one',suffixes=('','_source'),indicator=True)
    if len(joined)!=len(candidates) or not joined['_merge'].eq('both').all():raise ValueError('CANDIDATE_FEATURE_LEFT_JOIN_MISMATCH')
    if not joined.new_buy_eligible.equals(joined.new_buy_eligible_source):raise ValueError('CANDIDATE_ELIGIBILITY_MISMATCH')
    feature_available=np.isfinite(joined[cp.vm.FEATURES].to_numpy(float)).all(axis=1)
    if not np.array_equal(feature_available,joined.feature_available.to_numpy(bool)):raise ValueError('FEATURE_GATE_MISMATCH')
    if not np.array_equal(joined.ranking_eligible,feature_available&joined.new_buy_eligible.to_numpy(bool)):
        raise ValueError('RANKING_GATE_MISMATCH')
    usable=joined[joined.ranking_eligible].copy()
    if len(usable)!=EXPECTED[year]['rows'] or usable.signal_date.nunique()!=EXPECTED[year]['days']:
        raise ValueError('ORIGINAL_POOL_COUNT_MISMATCH')
    # All input model objects are constructed only after fitting has been disabled.
    policies={name:cp.CooperativePolicy(name,stage) for name in cp.NAMES}
    base=next(iter(policies.values())).base
    reference_components=pd.read_parquet(OLD/f'components_{year}.parquet').set_index(keys)
    controls=pd.read_parquet(OLD/f'daily_{year}.parquet')
    controls=controls[controls.policy.isin(CONTROLS)].copy()
    controls['diagnostic_origin']='original_frozen_control_no_recomputation'
    streams=Streams();daily=[];start=time.monotonic();max_error={name:0. for name in cp.NAMES};base_error=0.
    try:
        for index,(date,day) in enumerate(usable.groupby('signal_date',sort=True)):
            day=day.sort_values('ticker',kind='stable').reset_index(drop=True)
            observable=day[columns].copy()
            # No label/status/endpoint or future information can enter either base or policy.score.
            if observable.columns.tolist()!=columns:raise ValueError('INFERENCE_COLUMN_BOUNDARY')
            with threadpool_limits(limits=2),torch.no_grad():
                shared=base.predict(observable,0.,.95,0.)
                ranks,downside,raw,projected=shared
                component=day[keys].copy()
                for j,expert in enumerate(cp.BASE_NAMES):
                    component[f'rank_{expert}']=ranks[:,2,j]
                    component[f'raw_advantage_{expert}']=raw[expert][:,2]-raw[expert][:,0]
                component['six_arm_mean']=ranks[:,2,:].mean(axis=-1)
                component['six_arm_disagreement']=ranks[:,2,:].std(axis=-1)
                component['q10_downside_rank']=downside[:,2]
                component['mlp_projected_weight']=projected
                component['input_conflict_day']=day.input_conflict_day.to_numpy()
                old_piece=reference_components.loc[pd.MultiIndex.from_frame(component[keys])]
                numeric=[c for c in component if c not in keys+['input_conflict_day']]
                error=float(np.max(np.abs(component[numeric].to_numpy(float)-old_piece[numeric].to_numpy(float))))
                base_error=max(base_error,error)
                if error>1e-8:raise ValueError(f'ORIGINAL_SHARED_BASE_OUTPUT_MISMATCH:{error}')
                streams.add(OUT/f'components_{year}.parquet',component)
                chunks=[]
                for name,policy in policies.items():
                    scores,_,_,_,_,info=policy.score(observable,0.,.95,0.,base_outputs=shared)
                    score=scores[:,2]
                    rank,top,ties=old.ranking(score,day.ticker)
                    chunk=day[keys].copy();chunk['policy']=name
                    chunk['reference_score']=score;chunk['reference_rank']=rank;chunk['reference_top20']=top
                    chunk['reference_score_positive']=score>0;chunk['rank_tie_group_size']=ties
                    chunk['ranking_eligible']=True
                    for column in ['label_available','label_status','input_conflict_day','forward_return']:
                        chunk[column]=day[column].to_numpy()
                    chunks.append(chunk)
                    diagnostic,error=diagnostic_frame(day,name,scores,info)
                    max_error[name]=max(max_error[name],error)
                    streams.add(OUT/f'diagnostics_{year}_{name}.parquet',diagnostic)
                    daily.append(old.daily_metric(day,name,score,rank,top,ties))
                streams.add(OUT/f'scores_{year}.parquet',pd.concat(chunks,ignore_index=True))
            if index%20==0:
                print(json.dumps(dict(year=year,processed_days=index+1,total_days=EXPECTED[year]['days'],
                    signal=str(date.date()),seconds=round(time.monotonic()-start,2))),flush=True)
    finally:streams.close()
    daily=pd.DataFrame(daily);daily['diagnostic_origin']='new_cooperative_frozen_reference_state'
    if daily.duplicated(['policy','signal_date']).any():raise ValueError('DUPLICATE_DAILY_KEY')
    expected_scope=controls[controls.policy.eq('joint_hgb')].set_index('signal_date')
    for name,part in daily.groupby('policy'):
        aligned=part.set_index('signal_date').sort_index()
        expected=expected_scope.sort_index()
        for column in ['complete_common_pool','candidate_count','label_available_count','input_conflict_day']:
            if not np.array_equal(aligned[column],expected[column]):raise ValueError(f'CONTROL_SCOPE_MISMATCH:{name}:{column}')
        if int(aligned.complete_common_pool.sum())!=EXPECTED[year]['complete']:raise ValueError('COMPLETE_COMMON_DAY_COUNT')
    daily.to_parquet(OUT/f'daily_{year}.parquet',index=False)
    daily.to_csv(OUT/f'daily_{year}.csv',index=False)
    controls.to_parquet(OUT/f'controls_daily_{year}.parquet',index=False)
    if guard['attempts']:raise ValueError('FIT_ATTEMPTED')
    for path,digest in frozen.items():
        if ev.sha(path)!=digest:raise ValueError(f'FROZEN_INPUT_CHANGED:{path}')
    outputs={str(p):ev.sha(p) for p in OUT.glob(f'*{year}*') if p.suffix in ['.csv','.parquet']}
    write(OUT/f'COMPLETE_{year}.json',dict(status='PASS_FROZEN_SELECTION_DIAGNOSTIC',year=year,stage=stage,
        signal_days=EXPECTED[year]['days'],complete_common_pool_days=EXPECTED[year]['complete'],
        candidate_rows=len(candidates),ranking_rows=len(usable),score_rows=streams.rows[OUT/f'scores_{year}.parquet'],
        diagnostic_rows_by_policy={name:streams.rows[OUT/f'diagnostics_{year}_{name}.parquet'] for name in cp.NAMES},
        fit_attempts=guard['attempts'],source_sha256_unchanged=True,output_sha256=outputs,
        maximum_additive_reconstruction_error=max_error,maximum_old_shared_base_output_error=base_error,
        inference_columns=columns,all_seven_policies_same_candidate_keys=True,seconds=time.monotonic()-start,
        original_full_pool_certified=False,formal_price_certified=False))
    print(json.dumps(dict(status='COMPLETE',year=year,seconds=time.monotonic()-start,fit_attempts=0)),flush=True)


def summarize():
    rows=[];receipts={}
    for year in [2025,2026]:
        receipt=json.loads((OUT/f'COMPLETE_{year}.json').read_text(encoding='utf-8'))
        if receipt['fit_attempts']!=0:raise ValueError('FIT_ATTEMPTED')
        for path,digest in receipt['output_sha256'].items():
            if ev.sha(path)!=digest:raise ValueError('OUTPUT_HASH_CHANGED')
        receipts[year]=receipt
        combined=pd.concat([pd.read_parquet(OUT/f'daily_{year}.parquet'),pd.read_parquet(OUT/f'controls_daily_{year}.parquet')],ignore_index=True)
        for name,group in combined.groupby('policy',sort=False):
            for subset in ['complete_common_pool','incomplete_observable_only']:
                part=group[group.complete_common_pool] if subset=='complete_common_pool' else group[~group.complete_common_pool]
                row=dict(year=year,policy=name,subset=subset,signal_days=len(part),diagnostic_origin=group.diagnostic_origin.iloc[0])
                for source,target in [('observed_ic','mean_ic'),('observed_top20_minus_rest','mean_top20_minus_rest'),
                    ('simple_gross_if_selected_labels_complete','mean_period_simple_gross'),
                    ('simple_net_if_selected_labels_complete','mean_period_simple_net'),
                    ('label_coverage','mean_label_coverage'),('selected_label_coverage','mean_selected_coverage'),
                    ('tied_security_fraction','mean_tied_security_fraction'),('boundary_tie_count','mean_boundary_tie_count'),
                    ('top20_positive_score_count','mean_top20_positive_score_count'),('score_unique_count','mean_score_unique_count'),
                    ('observable_selected_net_contribution','mean_observable_selected_net_contribution')]:row[target]=old.mean(part[source])
                row['simple_full_top20_available_days']=int(part.simple_net_if_selected_labels_complete.notna().sum())
                rows.append(row)
    aggregate=pd.DataFrame(rows);aggregate.to_csv(OUT/'aggregate.csv',index=False)
    aggregate.to_parquet(OUT/'aggregate.parquet',index=False)
    write(OUT/'SUMMARY.json',dict(status='PASS_FROZEN_REFERENCE_SELECTION',receipts=receipts,aggregate=rows,
        fit_attempts=0,hyperparameter_search_trials=0,state=STATE,score='5%-0%',weight_per_name=.0475,
        round_trip_cost=.002,simple_compounding=False,account_replay=False,
        labels='Original candidate files reused with no modification; no forward-label filtering before TOP20',
        controls='Three old fixed reference controls copied without recomputation',
        attribution='Linear/gate contributions reconstruct; nonlinear zero-arm sensitivities are neither additive nor causal',
        limitations='Observed-history diagnostic; original 13F pool completeness, historical data arrival and corporate action prices not certified. Incomplete-pool observed slices are not full portfolio returns.'))
    lines=['# 协同模型固定参考状态排序诊断','',
        '七种协同方法已冻结推理完成。没有拟合、重训、搜参或重新生成标签；原HGB、等权融合、线性Stacking作为同日原始对照直接引用。',
        '固定状态为单票0、现金95%、年龄0，评分为5%动作相对0动作；先在原可排名全池取TOP20，再查看标签。即使分数为负也按规则取20，不等于实际账户会买入。',
        '2025共248日，其中245个共同完整日；2026共181日，其中88个共同完整日。主比较只使用共同完整日，其余为不完整可观察子样本。',
        '简单单期检验每票4.75%、往返20bp；下一开盘至再下一开盘，无复利、年化或连续账户/容量模拟。价格完整不等于全13F池或公司行动价格已认证；GLW冲突和原资格限制保留。','',
        '| 年份 | 方法 | 共同完整日 | 平均IC | 平均单期简单净值变化(bp) |',
        '| --- | --- | ---: | ---: | ---: |']
    for row in aggregate[aggregate.subset.eq('complete_common_pool')].itertuples():
        lines.append(f'| {row.year} | {row.policy} | {row.signal_days} | {row.mean_ic:.6f} | {row.mean_period_simple_net*10000:.4f} |')
    lines += ['', 'scores为全日期证券分数/名次/标签状态；components为共享六臂rank/原优势/分歧/投影；每策略diagnostics保存五动作输出、5%-0贡献/门控权重/锚和修正/目标贡献。非线性单臂置零敏感性是描述性扰动，不可相加或解释成因果贡献。',
        'NNLS保存原系数贡献与归一化展示比例，预测不将系数强行归一化。目标融合保存专家目标及加权项，其5%-0分数为10×混合目标−0.25；目标权重项与预测分数有不同单位。',
        '所有可加分解已逐行对账；共享六臂输出与旧诊断逐日对账。两阶段模型、源码、资格、标签和对照文件哈希运行前后不变，fit守卫计数0。此结果是已观察历史研究，不构成新盲测或冠军选择。']
    (OUT/'REPORT.md').write_text('\n\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(status='SUMMARY_COMPLETE',fit_attempts=0,rows=len(rows))),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--year',type=int,choices=[2025,2026]);parser.add_argument('--summarize',action='store_true')
    args=parser.parse_args()
    if args.summarize:summarize()
    elif args.year:run(args.year)
    else:parser.error('Choose --year or --summarize')
