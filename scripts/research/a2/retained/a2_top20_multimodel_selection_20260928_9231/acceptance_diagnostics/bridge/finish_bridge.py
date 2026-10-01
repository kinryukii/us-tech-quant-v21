"""Attach separately labelled fixed-reference ranks and readable bridge evidence."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

OUT=Path(__file__).resolve().parent
ROOT=OUT.parent.parent
SELECT=OUT.parent/'selection'


def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def write(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str),encoding='utf-8')


def cell(value,fmt=None):
    if value is None or pd.isna(value):return '—'
    if fmt:return format(value,fmt)
    return str(value).replace('|',' / ')


def main():
    receipt=json.loads((OUT/'COMPLETE.json').read_text(encoding='utf-8'))
    assert receipt['status']=='PASS' and receipt['paths']==38
    input_hashes={str(OUT/'COMPLETE.json'):sha(OUT/'COMPLETE.json')}
    joined_last=[];comparisons=[];missing_position_weight=0;false_eligible_zero_state=0
    glw=[];all_reasons=[];named_examples=[];implementation_daily=[]
    for year in [2025,2026]:
        refpath=SELECT/f'scores_{year}.parquet'
        ref=pd.read_parquet(refpath,columns=['signal_date','ticker','policy','reference_score','reference_rank','reference_top20','ranking_eligible'])
        input_hashes[str(refpath)]=sha(refpath)
        labelpath=SELECT/f'daily_{year}.parquet'
        labels=pd.read_parquet(labelpath,columns=['signal_date','policy','complete_common_pool'])
        input_hashes[str(labelpath)]=sha(labelpath)
        assert not labels.duplicated(['signal_date','policy']).any()
        assert not ref.duplicated(['signal_date','ticker','policy']).any()
        output=OUT/f'ACTUAL_VS_FIXED_REFERENCE_{year}.parquet';writer=None
        for entry in [s for s in receipt['paths_summary'] if s['year']==year]:
            actualpath=ROOT/entry['path'];assert sha(actualpath)==entry['sha256']
            f=pd.read_parquet(actualpath)
            missing_position_weight+=int((f.post_position_record_present&f.post_weight.isna()).sum())
            false_eligible_zero_state+=int((f.new_buy_eligible.eq(False)&f.signal_current_units.le(1e-12)&f.target_weight.eq(0)).sum())
            columns=['year','policy','signal_date','ticker','actual_state_rank','actual_score_5pct_vs_exit','raw_chosen_weight',
                'target_weight','target_order_type','execution_explanation','zero_target_explanation','post_weight',
                'post_units','signal_current_units','buy_notional','has_recorded_rejection',
                'known_glw_input_conflict','same_day_glw_score_present']
            r=ref.loc[ref.policy.eq(entry['policy'])]
            joined=f[columns].merge(r,on=['policy','signal_date','ticker'],how='left',validate='one_to_one',indicator=True)
            assert len(joined)==len(f)
            # No fixed-reference candidate may disappear from the original actual-account universe.
            assert int(joined['_merge'].eq('both').sum())==len(r)
            joined['comparison_basis']='ACTUAL_ACCOUNT_STATE_VS_SEPARATE_FIXED_REFERENCE_NOT_ORIGINAL_ORDER_CAUSE'
            joined['fixed_reference_row_present']=joined.pop('_merge').eq('both')
            table=pa.Table.from_pandas(joined,preserve_index=False)
            if writer is None:writer=pq.ParquetWriter(output,table.schema,compression='zstd')
            else:table=table.cast(writer.schema,safe=True)
            writer.write_table(table)
            if entry['policy'] in ['ensemble_equal','ensemble_disagreement','ensemble_stacking','joint_hgb']:
                selected=joined.loc[joined.reference_top20.fillna(False)].merge(labels,
                    on=['signal_date','policy'],how='left',validate='many_to_one')
                assert selected.complete_common_pool.notna().all()
                for date,g in selected.groupby('signal_date',sort=True):
                    implementation_daily.append(dict(year=year,policy=entry['policy'],signal_date=date,
                        sample_scope='COMPLETE_COMMON_DAYS' if g.complete_common_pool.iloc[0] else 'OTHER_DAYS',
                        reference_top20_instances=len(g),actual_positive_target_instances=int(g.target_weight.gt(0).sum()),
                        active_positive_target_instances=int((g.target_weight.gt(0)&g.target_order_type.ne('HOLD_UNITS')).sum()),
                        reserved_positive_target_instances=int((g.target_weight.gt(0)&g.target_order_type.eq('HOLD_UNITS')).sum()),
                        post_execution_positive_units_instances=int(g.post_units.gt(1e-12).sum()),
                        flat_to_new_buy_instances=int((g.signal_current_units.le(1e-12)&g.buy_notional.gt(0)).sum()),
                        actual_target_weight_on_reference_top20=float(g.target_weight.fillna(0.).sum()),
                        recorded_rejected_instances=int(g.has_recorded_rejection.sum())))
            last=f.loc[f.signal_date.eq(f.signal_date.max())].merge(r,on=['policy','signal_date','ticker'],how='left',validate='one_to_one')
            joined_last.append(last)
            comparisons.append(dict(year=year,policy=entry['policy'],actual_rows=len(f),reference_rows=len(r),
                actual_only_rows=int((~joined.fixed_reference_row_present).sum()),
                same_top20_rows=int((f.actual_state_top20.to_numpy()&joined.reference_top20.fillna(False).to_numpy()).sum())))
            if year==2026:
                g=f.loc[(f.ticker.eq('GLW')&f.signal_date.between('2026-02-25','2026-02-27'))|
                    (f.ticker.eq('GLW')&f.known_execution_price_date_conflict)].copy()
                if len(g):glw.append(g)
            for reason,count in entry['high_rank_zero_reasons'].items():
                all_reasons.append(dict(year=year,policy=entry['policy'],reason=reason,count=count))
            for category,mask in [('HIGH_RANK_ZERO',f.high_rank_zero_target),('POSITIVE_TARGET_NO_TRADE',f.positive_target_no_trade),
                ('CAPACITY_PARTIAL',f.reconstructed_capacity_limited),('HOLD_WITHOUT_INPUT',f.held_without_decision_input)]:
                part=f.loc[mask].head(1)
                if len(part):
                    item=part.iloc[0]
                    named_examples.append(dict(year=year,policy=entry['policy'],category=category,ticker=item.ticker,
                        signal_date=str(item.signal_date.date()),actual_rank=item.actual_state_rank,
                        score=item.actual_score_5pct_vs_exit,target_weight=item.target_weight,
                        requested_buy=item.reconstructed_requested_buy_notional,buy=item.buy_notional,sell=item.sell_notional,
                        fee=item.recorded_cost,post_units=item.post_units,
                        explanation=item.zero_target_explanation if category=='HIGH_RANK_ZERO' else item.execution_explanation,
                        recorded_reasons=item.execution_reasons))
        if writer is not None:writer.close()
    latest=pd.concat(joined_last,ignore_index=True)
    pd.DataFrame(comparisons).to_csv(OUT/'REFERENCE_JOIN_AUDIT.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(all_reasons).to_csv(OUT/'HIGH_RANK_ZERO_REASONS.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(named_examples).to_csv(OUT/'READABLE_EXPLANATION_EXAMPLES.csv',index=False,encoding='utf-8-sig')
    implementation=pd.DataFrame(implementation_daily)
    implementation.to_parquet(OUT/'REFERENCE_TOP20_IMPLEMENTATION_DAILY.parquet',index=False,compression='zstd')
    implementation_summary=implementation.groupby(['year','policy','sample_scope'],as_index=False).agg(
        signal_days=('signal_date','nunique'),reference_top20_instances=('reference_top20_instances','sum'),
        actual_positive_target_instances=('actual_positive_target_instances','sum'),
        active_positive_target_instances=('active_positive_target_instances','sum'),
        reserved_positive_target_instances=('reserved_positive_target_instances','sum'),
        post_execution_positive_units_instances=('post_execution_positive_units_instances','sum'),
        flat_to_new_buy_instances=('flat_to_new_buy_instances','sum'),
        mean_target_weight_on_reference_top20=('actual_target_weight_on_reference_top20','mean'),
        recorded_rejected_instances=('recorded_rejected_instances','sum'))
    implementation_summary['target_positive_fraction']=implementation_summary.actual_positive_target_instances/implementation_summary.reference_top20_instances
    implementation_summary['active_target_positive_fraction']=implementation_summary.active_positive_target_instances/implementation_summary.reference_top20_instances
    implementation_summary['post_units_positive_fraction']=implementation_summary.post_execution_positive_units_instances/implementation_summary.reference_top20_instances
    implementation_summary['interpretation']='SAME_DAY_SELECTION_TO_ACCOUNT_DIAGNOSTIC_NOT_RETURN_CAUSAL_ATTRIBUTION'
    implementation_summary.to_csv(OUT/'REFERENCE_TOP20_IMPLEMENTATION_BY_DAY_SCOPE.csv',index=False,encoding='utf-8-sig')
    if glw:pd.concat(glw,ignore_index=True).to_parquet(OUT/'GLW_CONFLICT_BRIDGE.parquet',index=False,compression='zstd')
    # The cost ledger amounts below are transactions already booked, never return-difference attribution.
    cost_rows=[]
    for year,cost in [(2025,10),(2026,5),(2026,10),(2026,25)]:
        for entry in [s for s in receipt['paths_summary'] if s['year']==year]:
            path=ROOT/f'evaluation_{year}/cost_{cost}'/entry['policy']/'DONE.json'
            saved=json.loads(path.read_text(encoding='utf-8'));input_hashes[str(path)]=sha(path)
            cost_rows.append(dict(year=year,cost_bps=cost,policy=entry['policy'],
                booked_transaction_cost_dollars=saved['total_cost_dollars'],trades=saved['trades'],
                attribution='RECORDED_COST_IN_ITS_OWN_FROZEN_PATH_NOT_RETURN_GAP_DECOMPOSITION'))
    pd.DataFrame(cost_rows).to_csv(OUT/'RECORDED_COST_SCENARIOS.csv',index=False,encoding='utf-8-sig')
    board=['# 原实际账户末日榜与固定参考榜的分列对照',
        '\n实际分数为原账户状态下5%相对0动作的偏好；参考排名来自独立固定状态(0,95%现金,年龄0)，不能当作原下单依据。顺序按实际排名，ticker打破并列。保留无输入持仓无实际评分，列在榜尾。成本为原账户已记账金额。']
    for (year,policy),g in latest.groupby(['year','policy'],sort=False):
        shown=g.loc[g.actual_state_top20|g.target_weight.gt(0)|g.post_units.gt(0)|g.has_recorded_rejection].sort_values(['actual_state_rank','ticker'])
        board+=['',f'## {year} · {policy} · {str(g.signal_date.max().date())}',
            f'\n信号现金 {g.signal_cash_weight.iloc[0]:.2%}；主动目标总权重 {g.account_active_target_weight.iloc[0]:.2%}；保留权重 {g.reserved_weight.iloc[0]:.2%}。',
            '\n|实际排位|股票|实际5%优势|固定参考排位|原目标|成交买/卖金额|已记费用|成交后权重|执行状态|',
            '|---:|---|---:|---:|---:|---:|---:|---:|---|']
        if shown.empty:board.append('|—|无排名或持仓|—|—|0|0|0|0|现金对照|')
        for r in shown.itertuples():
            board.append(f'|{cell(r.actual_state_rank,".0f")}|{r.ticker}|{cell(r.actual_score_5pct_vs_exit,".5g")}|{cell(r.reference_rank,".0f")}|{cell(r.target_weight,".2%")}|{r.buy_notional:.2f}/{r.sell_notional:.2f}|{r.recorded_cost:.2f}|{cell(r.post_weight,".2%")}|{cell(r.execution_explanation)}|')
    # The root produces one four-policy readable final-signal sheet. Do not emit
    # a second competing readable board; full-date comparison tables remain here.
    totals={key:sum(s[key] for s in receipt['paths_summary']) for key in ['rows','high_rank_zero_target','positive_target_no_trade','rejected_rows','capacity_limited_fills','held_without_decision_input','no_target_rows']}
    glw_policies=[s['policy'] for s in receipt['paths_summary'] if s['year']==2026 and s['glw_conflict_raw_score_rows']]
    reasons=pd.DataFrame(all_reasons).groupby('reason')['count'].sum().sort_values(ascending=False)
    lines=['# 实际排序、目标与成交三层对照',
        '\n本工作包只读取38条原2025/2026、10bp账本；模型调用、fit、更新和回放均为0。固定参考排序由独立工作包产出，本目录只按唯一键连接。',
        '\n## 范围与检查',
        f'\n完整机器表共 {totals["rows"]:,} 条 policy/signal_date/ticker 记录。来源原候选、实际持仓、明确目标与运营动作的并集；原始候选中没有目标记录的股票也被保留，未下单不等于拒单。',
        '\n逐路径通过：唯一键、事件和交易行数守恒、六模型贡献重建、原目标一致、交易金额与费用守恒、信号单位加净成交等于成交后单位、每日现金与NAV对齐。金额误差上限1e-5，单位误差上限1e-7，实际最大值见各CHECK文件。',
        '\n## 关键计数（证券日，不是独立交易次数）',
        '\n|事项|数量|','|---|---:|',
        f'|实际状态Top20但目标0|{totals["high_rank_zero_target"]:,}|',
        f'|主动目标>0但无成交|{totals["positive_target_no_trade"]:,}|',
        f'|有明确REJECTED事件|{totals["rejected_rows"]:,}|',
        f'|已成交但买入请求受ADV容量限制|{totals["capacity_limited_fills"]:,}|',
        f'|实际持有但无决策输入|{totals["held_without_decision_input"]:,}|',
        f'|原宇宙中没有目标记录|{totals["no_target_rows"]:,}|',
        '\n高排名指固定5%动作相对退出的实际账户分数排位，不是原优化器的完整五动作选择结果。它与目标为0可以同时成立：模型在比较其他动作、共同资金预算及组合风险。若原日志没有具体绑定证据，我们只记unknown，不从目标0猜测某个约束。',
        '\n|高排零目标的证据分类|数量|','|---|---:|']
    lines += [f'|{k}|{int(v):,}|' for k,v in reasons.items()]
    lines += ['\n## 分数与贡献的准确含义',
        '\n线性/树/分位数采用原存储五动作中的Q(5%)-Q(0)；最大动作优势与原chosen weight同时保留。神经方法仅把原已投影权重p映射成固定动作偏好10p-0.25，投影已经含横截面和名额/资金限制，并列可能很多，不能声称这是独立原始收益预测。LW/PCA的分数是风险决策层之前的HGB条件动作值，已知风险层生效但逐步惩罚没有完整写入原日志，因此不虚构其股票级约束归因。',
        '\n三集成保存每只股票六臂原动作优势、已存signed rank和贡献。等权/分歧臂每臂rank/6；分歧臂另减0.25×六臂总体标准差及0.25×Q10下行排名；stacking按对应阶段原非负系数逐臂相乘。贡献加总与原fused 5%优势逐条重建一致。',
        '\n## 成交与价格证据边界',
        '\n正目标无成交时，分别保留明确拒绝、已经满足目标、保留单位、没有目标或未知事件。容量部分成交由原目标×开盘NAV减原单位×开盘价恢复买入请求，再核对min(请求,信号ADV×1%)×原现金缩放与实际买额；这是可重建执行事实，不把它伪装成日志中已有的PARTIALLY_FILLED文本。',
        f'\n已知GLW事件日期冲突：2026-02-26有 {len(glw_policies)} 条非现金路径实际保存了GLW模型分数，名单为 {", ".join(glw_policies)}。即使GLW分配为0，也不能排除其对同日横截面排名、神经投影或集成的影响；所有同日行另有same_day_glw_score_present标记。02-26/27的信号、执行和标价冲突均显式覆盖旧warning字段，未因warning=False而认证。',
        '\ncurrent_close和旧价格warning只是原系统当时采用的门控证据，不是已认证股东回报。保留价格状态包括当前旧标记、陈旧估值、未知值和明确冲突；有持仓但未知权重保留NaN，不写成0。',
        f'\n本数据存在持仓但权重未知行 {missing_position_weight:,}；False资格且零现有单位/零目标行 {false_eligible_zero_state:,}。诊断实现最初的性能与bool/缺失值语义修复已在ABORTED_ATTEMPT.json记录；未动原模型或账本。',
        '\n成本只引用原已记账金额，见RECORDED_COST_SCENARIOS.csv（原5/10/25bp各自账户路径）。成本不同会改变后续持仓，不将两个最终收益之差称为精确成本分解。',
        '\nREFERENCE_TOP20_IMPLEMENTATION_BY_DAY_SCOPE.csv另按工作包2完全相同的完整共同日/其余日，统计三集成与HGB参考Top20实例实际目标>0比例、成交后单位>0比例和从零新买数量。target>0另拆主动目标与HOLD_UNITS保留权重，成交后持有也可能来自已有持仓，并不都等于当日新买。分组为事后诊断，仅说明同日从排序到配置/执行的重合；不能将独立单期简单持仓与原完整账户的收益差归因为账户规则消耗了全部优势。',
        '\n## 文件',
        '\n- actual_account_bridge_年份_模型.parquet：全日期实际三层机器表。',
        '- ACTUAL_VS_FIXED_REFERENCE_年份.parquet：分列实际/固定参考分数与排名；不宣称参考榜是原下单依据。',
        '- ../LAST_SIGNAL_THREE_LAYER.csv：主代理统一输出的四策略末日易读入口。',
        '- LAST_SIGNAL_ACTUAL_ACCOUNT_FULL.parquet、LAST_SIGNAL_READABLE.csv：主导出保留的末日实际账户数值。',
        '- READABLE_EXPLANATION_EXAMPLES.csv：高排零目标、未成交、容量及保留持仓实例。',
        '- GLW_CONFLICT_BRIDGE.parquet、HIGH_RANK_ZERO_REASONS.csv：冲突与原因分类。',
        '- COMPLETE.json、CHECK_*.json、SUPPLEMENT_RECEIPT.json：来源哈希和连接/会计验证。']
    (OUT/'BRIDGE_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    assert all(sha(path)==value for path,value in input_hashes.items())
    result=dict(status='PASS',reference_join_paths=len(comparisons),input_hashes_unchanged=True,input_sha256=input_hashes,
        model_fit_calls=0,model_predict_calls=0,replay_calls=0,totals=totals,
        present_position_unknown_weight_rows=missing_position_weight,false_eligible_zero_state_rows=false_eligible_zero_state,
        glw_actual_scored_policies=glw_policies,source_code_sha256=sha(__file__))
    write(OUT/'SUPPLEMENT_RECEIPT.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='input_sha256'},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
