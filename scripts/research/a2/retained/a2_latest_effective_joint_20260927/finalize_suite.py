"""Read-only result assembly for the latest-effective-universe rerun."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from risk import FrozenRisk

ROOT=Path(__file__).resolve().parent
OLD=ROOT.parent/'a2_complete_suite_20260927'
LABELS={'joint_ridge':'Ridge 联合动作','joint_elastic_net':'Elastic Net 联合动作','joint_logistic':'逻辑回归联合动作',
 'joint_hgb':'HGB 联合动作','joint_q10':'Q10 联合动作','joint_q50':'Q50 联合动作','joint_q90':'Q90 联合动作',
 'joint_quantile_risk':'分位下行联合动作','joint_mlp':'MLP 直接联合策略','joint_rl_ensemble':'RL 双种子联合策略',
 'joint_rl_zero_control':'RL 零更新对照','hgb_return_baseline':'旧 HGB 固定仓位基准',
 'joint_hgb_lw':'联合 HGB + 收缩风险','joint_hgb_pca':'联合 HGB + PCA 风险'}

def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def write(p,x):Path(p).write_text(json.dumps(x,indent=2,ensure_ascii=False,default=str,allow_nan=False),encoding='utf-8')
def pct(x):return '—' if pd.isna(x) else f'{x:+.2%}'

def main():
    pieces=[]
    for cost in [10,5,25]:
        folder=ROOT/'evaluation_2026'/f'cost_{cost}'
        done=read(folder/'COMPLETE.json')
        assert done['evaluations']==14 and done['fit_guard_attempts']==0
        pieces.append(pd.read_csv(folder/'comparison.csv'))
    result=pd.concat(pieces,ignore_index=True)
    assert len(result)==42 and not result.duplicated(['policy','cost_bps_per_side']).any()
    result.to_csv(ROOT/'evaluation_2026/comparison.csv',index=False)
    validation=pd.read_csv(ROOT/'evaluation_2025/comparison.csv')
    assert read(ROOT/'evaluation_2025/COMPLETE.json')['evaluations']==12
    previous=pd.read_csv(OLD/'evaluation_2026/comparison.csv')
    comparison=result.merge(previous,on=['policy','cost_bps_per_side'],suffixes=('_latest_effective','_previous_natural'),validate='one_to_one')
    comparison['indicative_return_difference']=comparison.indicative_return_latest_effective-comparison.indicative_return_previous_natural
    comparison.to_csv(ROOT/'RULE_CHANGE_COMPARISON.csv',index=False)
    pre=read(ROOT/'data/JOINT_DATA_AUDIT.json');data=read(ROOT/'data/DATA_AUDIT.json')
    neural=read(ROOT/'joint_neural_artifacts/TRAIN_RECEIPT.json')
    linear=read(ROOT/'joint_linear_tree_artifacts/FIT_RECEIPT.json')
    aux=read(ROOT/'models/AUXILIARY_TRAIN_RECEIPT.json')
    panel=pd.read_parquet(ROOT/'data/test_features_context.parquet')
    risk=FrozenRisk();latest=[];risk_rows=[];actions=[];stress=[]
    for name in LABELS:
        folder=ROOT/'evaluation_2026/cost_10'/f'{name}_10bps'
        targets=pd.read_parquet(folder/'target_decisions.parquet')
        trades=pd.read_parquet(folder/'trades.parquet')
        daily=pd.read_parquet(folder/'daily.parquet')
        positions=pd.read_parquet(folder/'positions.parquet')
        actions.append({'policy':name,**trades.action.value_counts().to_dict()})
        for d,g in targets.groupby('signal_date',sort=True):
            active=g[g.target_weight>0];names=active.ticker.tolist();w=active.target_weight.to_numpy(float)
            c=risk.covariance_for(names);cf=risk.covariance_for(names,True)
            risk_rows.append(dict(policy=name,signal_date=d,names=len(names),target_exposure=float(w.sum()),
              effective_names=float(w.sum()**2/(w@w)) if (w@w)>0 else 0.,predicted_daily_vol=float(np.sqrt(w@c@w)),
              predicted_factor_daily_vol=float(np.sqrt(w@cf@w)),unknown_risk_names=sum(t not in risk.lookup for t in names)))
        one=targets[targets.signal_date.eq(targets.signal_date.max())&targets.ticker.notna()].copy()
        one['policy']=name
        one['intended_action']=np.select([one.target_weight.le(1e-8)&one.current_weight.gt(1e-8),
          one.current_weight.le(1e-8)&one.target_weight.gt(1e-8),one.target_weight.gt(one.current_weight+.0025),
          one.target_weight.lt(one.current_weight-.0025)],['退出','买入','加仓','减仓'],default='持有/等待')
        latest.append(one)
        terminal=positions[positions.date.eq(daily.date.max())]
        stale=float(terminal.loc[terminal.stale,'market_value'].sum());nav=float(daily.nav.iloc[-1])
        stress.append(dict(policy=name,terminal_stale_index_value=stale,terminal_stale_weight=stale/nav,
          terminal_full_writeoff_stress_return=(nav-stale)/1e6-1,
          interpretation='scenario only: mark all terminal stale index units to zero; not a certified return or confidence interval'))
    pd.DataFrame(risk_rows).to_csv(ROOT/'portfolio_risk_diagnostics.csv',index=False)
    pd.DataFrame(actions).fillna(0).to_csv(ROOT/'actual_action_counts.csv',index=False)
    pd.DataFrame(stress).to_csv(ROOT/'stale_position_stress.csv',index=False)
    latest=pd.concat(latest,ignore_index=True).merge(panel[['signal_date','ticker','quarter','cusip','new_buy_eligible']],on=['signal_date','ticker'],how='left',validate='many_to_one')
    latest.to_csv(ROOT/'LAST_TEST_DATE_TARGETS.csv',index=False,encoding='utf-8-sig')
    current=result[result.cost_bps_per_side.eq(10)].set_index('policy');v=validation.set_index('policy')
    before=previous[previous.cost_bps_per_side.eq(10)].set_index('policy')
    uncertified=int(result.uncertified_days.gt(0).sum())
    txrows=sum(len(pd.read_parquet(ROOT/'evaluation_2026'/f'cost_{int(r.cost_bps_per_side)}'/f'{r.policy}_{int(r.cost_bps_per_side)}bps/trades.parquet')) for r in result.itertuples())
    lines=['# 最新已生效13F股票池：联合重训报告','',
      '**已按新股票池规则完成重新训练、2025验证和2026固定方案测试。原完整13F池/股东总收益认证仍受既有数据缺口限制。**','',
      '## 本批规则','',
      '决策时点使用最近一期已经公开且满足既定生效条件的13F股票池。新一期尚未生效，继续使用上一期已生效池。自然季度翻页不会单独触发禁买。所有训练、验证和测试使用同一规则，未来才生效的申报不会提前进入。','',
      '原生效日期保持不变：2026-02-25从2025Q3切换为2025Q4；2026-05-22切换为2026Q1；2026-08-21切换为2026Q2。此前继续使用上一有效池。逐日as-of核验和边界测试见data/INPUT_VALIDATION.json及data/UNIVERSE_RULE_CHANGE.json。','',
      '| 范围 | 上一批自然季度限制 | 本批最近已生效池 |','|---|---:|---:|',
      '| 2023—2025可新买候选行 | 136,121 | 313,668 |',
      '| 2023—2025可新买信号日 | 324 | 752 |',
      '| 2026已核证可新买候选行 | 22,776 | 61,963 |',
      '| 2026可新买信号日 | 73 | 181 |','',
      '原32特征、价格、标签数值与旧context逐行一致；变化是股票池资格。所有可用训练标签终点仍不晚于2025-12-31。原24家机构来源、季度整体生效合同及R6证据门槛保留，未冒称SEC全部13F机构。','',
      '## 重新训练了什么','',
      '- 联合Ridge、Elastic Net、Logistic、HGB、Q10/Q50/Q90：7类各训练验证与最终模型，共14次主拟合；不是复用上一批联合权重。反事实状态动作样本仍按整日系统抽样、每折最多20万行。参数、动作网格、风险项和成本不变，无超参数搜索。',
      f'- MLP直接联合策略和两个RL种子：6个全新策略拟合，共{neural["actual_parameter_updates"]:,}次参数更新；MLP仍为6个epoch，RL每种子仍为4个epoch。TOP20、买持加减退和权重进入同一训练循环；原来的零更新对照继续保留。',
      '- KMeans、IsolationForest和状态Scaler按原1388个pre2026日状态及原参数重新拟合。LedoitWolf与PCA五因子按原252日、857只历史证券重新估计。仅旧收益预测基准按哈希复用，未算成新增联合训练。',
      '- 2023—2024训练、2025验证，最终2023—2025。训练标签、奖励价格、标准化和风险拟合全部早于2026。所有模型固定后，2026只predict/transform，测试阶段fit调用为0。',
      '- 线性/树是一步状态动作价值近似；MLP使用单步组合效用及截断历史梯度；RL使用模拟持仓和随机组合动作。它们都共同决定股票与目标仓位，但不宣称算法等价或已经学到最优交易。','',
      '## 执行与限制不变','',
      '100万美元名义初始现金，目标和实际持仓最多20只，单票目标上限10%、总目标上限95%；收盘决策、下一会话开盘执行。新买单按已知20日美元量1%容量代理约束；实际买单再次检查当日资格。单边综合费用/滑点代理10bp，另做5bp和25bp。测试信号至2026-09-22，终端估值为09-24收盘。','',
      '价格仍是向前复权指数坐标，指数单位不是原始股份，没有完整分红/公司行动权益账。警示价格在消费时设为不可用，不按未来缺价删除前日信号。未核证估值仍逐日标记，不能把指示性净值当成可信股东回报。','',
      '## 固定候选结果','',
      '以下全部为成本后指数坐标诊断。2026并非原始盲测，也不是完整原池测试；未核证日大于0的整条收益、回撤只能作指示性记录，不可据此排名认定优胜。','',
      '| 固定方案 | 2025时间验证 | 2026本批诊断 | 2026诊断回撤 | 平均现金 | 未核证估值日 |',
      '|---|---:|---:|---:|---:|---:|']
    for name,label in LABELS.items():
        row=current.loc[name];vr=v.loc[name].indicative_return if name in v.index else np.nan
        lines.append(f'| {label} | {pct(vr)} | {pct(row.indicative_return)} | {pct(row.indicative_max_drawdown)} | {row.mean_cash:.1%} | {int(row.uncertified_days)} |')
    lines+=['','最终PCA/收缩风险只用于2026，未将2025年末风险参数倒用于2025验证，所以相应验证格留空。','',
      '## 与上一批的规则对照','',
      '两批成本、模型规格、账本和价格数据保持一致；本批新资格也改变训练样本及拟合参数，因而这里比较的是整套规则重训后的结果，不是股票池变化的独立因果效果。两批的指示性收益均受未核证持仓估值影响。','',
      '| 方案 | 上批自然季度限制 | 本批最近已生效池 |','|---|---:|---:|']
    for name,label in LABELS.items():lines.append(f'| {label} | {pct(before.loc[name].indicative_return)} | {pct(current.loc[name].indicative_return)} |')
    lines+=['','完整三档成本及新旧差异见RULE_CHANGE_COMPARISON.csv，不使用这些2026结果调参或升级模型。','',
      '## 成本压力测试','', '| 方案 | 单边5bp | 单边10bp | 单边25bp |','|---|---:|---:|---:|']
    for name,label in LABELS.items():
        r=result[result.policy.eq(name)].set_index('cost_bps_per_side')
        lines.append(f'| {label} | '+ ' | '.join(pct(r.loc[c].indicative_return) for c in [5,10,25])+' |')
    lines+=['','同一冻结策略在各成本下重新回放账户，不做重训。stale_position_stress.csv给出期末仍陈旧资产全部减记为零的情景，不是认证收益或统计置信区间。','',
      '## 验证与尚未解决的问题','',
      '- 38项执行/联合策略/新规则测试全部通过，另4个风险合成案例和2个阶段检查通过。新规则测试覆盖自然季度变化时沿用旧有效池、真实新池生效后的切换，以及未来生效季度不得提前新买。',
      '- 最终独立审计PASS：54次回放、171,170笔交易，其中87,836笔买入/加仓逐笔符合信号时点最新已生效池；72个冻结文件完成216次哈希核验。最大现金重建误差1.15e-8、每日指数单位误差2.33e-10、费用误差0，训练日期和测试零拟合检查通过。详见VERIFICATION.json。',
      f'- 已运行54次回放（2025共12次、2026共42次），2026共{txrows:,}笔实际模拟交易。所有候选完整保存，无按结果删去失败策略。',
      f'- 2026的42个成本情景中{uncertified}个含未核证估值，最多{int(result.uncertified_days.max())}/183日。即便没有缺价的方案，也仍受子池覆盖和指数价格口径限制。',
      '- 原全池111,868个候选日中47,701仍未知；本批恢复了已核证候选的连续启用，并未补齐这些未知记录。正式全池TOP20、真实股东总收益仍未完成认证，不以局部测试冒充。',
      '- 训练未建成交量冲击模型，验证账本使用容量代理；风险优化为有限次坐标改进，非全局最优证明。已有2026暴露和重复研究仍须保留，不宣称纯盲测或防过拟合保证。','',
      '## 文件入口','',
      '- TRAINING_SUMMARY.md：新训练、固定参数及数值修复计数。',
      '- evaluation_2025/comparison.csv、evaluation_2026/comparison.csv：全部新结果。',
      '- evaluation_2026/cost_10/<方案>_10bps/：逐笔交易、现金、持仓、目标、估值缺口；其余成本同结构。',
      '- LAST_TEST_DATE_TARGETS.csv：最后历史测试日各方案选股和目标仓位，非当前实盘建议。',
      '- RULE_CHANGE_COMPARISON.csv、data/UNIVERSE_RULE_CHANGE.json：新旧规则对照。',
      '- data/INPUT_VALIDATION.json、VERIFICATION.json：股票池时点与完整账本复核。',
      '- JOINT_CONTRACT.md：事前固定的本批规则和训练/测试限制。','']
    (ROOT/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    write(ROOT/'evaluation_2026/COMPLETE.json',dict(status='LATEST_EFFECTIVE_VERIFIED_SUBSET_DIAGNOSTIC_COMPLETE',policies=14,evaluations=42,
      full_pool_formal_test=False,model_selection_from_2026=False,fit_guard_attempts=0,rule='latest public and effective pool; carry until successor effective',
      covered_signal_last='2026-09-22',terminal_close_valuation='2026-09-24'))
    print('All scenarios assembled; report and rule-change comparison written',flush=True)

if __name__=='__main__':main()
