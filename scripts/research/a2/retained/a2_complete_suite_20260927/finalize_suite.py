"""Assemble all frozen runs; descriptive reporting never selects or refits."""
from pathlib import Path
import json
import hashlib
import numpy as np
import pandas as pd
from risk import FrozenRisk

ROOT=Path(__file__).resolve().parent
LABELS={'joint_ridge':'Ridge 联合动作','joint_elastic_net':'Elastic Net 联合动作','joint_logistic':'逻辑回归联合动作',
    'joint_hgb':'HGB 联合动作','joint_q10':'Q10 联合动作','joint_q50':'Q50 联合动作','joint_q90':'Q90 联合动作',
    'joint_quantile_risk':'分位下行联合动作','joint_mlp':'MLP 直接联合策略','joint_rl_ensemble':'RL 双种子联合策略',
    'joint_rl_zero_control':'RL 零更新对照','hgb_return_baseline':'旧 HGB 排名固定仓位基准',
    'joint_hgb_lw':'HGB 联合动作 + 收缩风险','joint_hgb_pca':'HGB 联合动作 + PCA 风险'}

def write(path,obj):path.write_text(json.dumps(obj,indent=2,ensure_ascii=False,default=str,allow_nan=False),encoding='utf-8')
def pct(v):return '—' if pd.isna(v) else f'{float(v):+.2%}'

def main():
    pieces=[]
    for cost in [10,5,25]:
        folder=ROOT/'evaluation_2026'/f'cost_{cost}'
        done=json.loads((folder/'COMPLETE.json').read_text(encoding='utf-8'))
        assert done['evaluations']==14 and done['fit_guard_attempts']==0
        pieces.append(pd.read_csv(folder/'comparison.csv'))
    comparison=pd.concat(pieces,ignore_index=True)
    comparison.to_csv(ROOT/'evaluation_2026/comparison.csv',index=False)
    val=pd.read_csv(ROOT/'evaluation_2025/comparison.csv')
    assert len(val)==12 and (ROOT/'evaluation_2025/COMPLETE.json').exists()
    data=json.loads((ROOT/'data/DATA_AUDIT.json').read_text(encoding='utf-8'))
    fit=json.loads((ROOT/'joint_linear_tree_artifacts_r2/FIT_RECEIPT.json').read_text(encoding='utf-8'))
    neural=json.loads((ROOT/'joint_neural_v3/TRAIN_RECEIPT.json').read_text(encoding='utf-8'))
    risk=FrozenRisk()
    risk_rows=[];actions=[];latest=[];stale_stress=[]
    features=pd.read_parquet(ROOT/'data/test_features_context.parquet')
    state=pd.read_csv(ROOT/'evaluation_2026/cost_10/state_anomaly.csv')
    for name in LABELS:
        folder=ROOT/'evaluation_2026/cost_10'/f'{name}_10bps'
        targets=pd.read_parquet(folder/'target_decisions.parquet')
        trades=pd.read_parquet(folder/'trades.parquet')
        daily=pd.read_parquet(folder/'daily.parquet')
        positions=pd.read_parquet(folder/'positions.parquet')
        terminal=positions[positions.date.eq(daily.date.max())]
        stale_value=float(terminal.loc[terminal.stale,'market_value'].sum())
        terminal_nav=float(daily.nav.iloc[-1])
        stale_stress.append(dict(policy=name,terminal_stale_index_value=stale_value,
            terminal_stale_weight=stale_value/terminal_nav if terminal_nav>0 else None,
            terminal_full_writeoff_stress_return=(terminal_nav-stale_value)/1e6-1,
            interpretation='scenario: mark all still-stale index positions to zero; not a certified return or statistical confidence bound'))
        for d,g in targets.groupby('signal_date',sort=True):
            active=g[g.target_weight>0].copy()
            names=active.ticker.tolist();w=active.target_weight.to_numpy(float)
            c=risk.covariance_for(names);cf=risk.covariance_for(names,True)
            risk_rows.append(dict(policy=name,signal_date=d,names=len(names),gross_exposure=float(w.sum()),
                effective_names=float(w.sum()**2/(w@w)) if (w@w)>0 else 0.,
                predicted_daily_vol=float(np.sqrt(w@c@w)),pca_predicted_daily_vol=float(np.sqrt(w@cf@w)),
                unknown_risk_names=sum(t not in risk.lookup for t in names)))
        latest_date=targets.signal_date.max()
        one=targets[(targets.signal_date==latest_date)&targets.ticker.notna()].copy()
        one['policy']=name
        one['intended_action']=np.select([one.target_weight.le(1e-8)&one.current_weight.gt(1e-8),
            one.current_weight.le(1e-8)&one.target_weight.gt(1e-8),one.target_weight.gt(one.current_weight+.0025),
            one.target_weight.lt(one.current_weight-.0025)],['退出','买入','加仓','减仓'],default='持有/等待')
        latest.append(one)
        counts=trades.action.value_counts().to_dict() if len(trades) else {}
        actions.append(dict(policy=name,**counts))
    pd.DataFrame(risk_rows).to_csv(ROOT/'portfolio_risk_diagnostics.csv',index=False)
    pd.DataFrame(actions).fillna(0).to_csv(ROOT/'actual_action_counts.csv',index=False)
    pd.DataFrame(stale_stress).to_csv(ROOT/'stale_position_stress.csv',index=False)
    last=pd.concat(latest,ignore_index=True)
    last=last.merge(features[['signal_date','ticker','cusip','quarter','new_buy_eligible']],on=['signal_date','ticker'],how='left',validate='many_to_one')
    last.to_csv(ROOT/'LAST_TEST_DATE_TARGETS.csv',index=False,encoding='utf-8-sig')
    main=comparison[comparison.cost_bps_per_side.eq(10)].set_index('policy')
    validation=val.set_index('policy')
    lines=['# TOP20 与买卖仓位联合训练：交付报告','',
        '**联合训练、2025验证及2026局部池测试均已执行。完整原13F股票池的正式测试仍未通过数据完整性资格。**',
        '本批主模型在同一个决策任务中学习股票入选及目标仓位，买入、持有、加仓、减仓、退出由同一目标输出决定。旧收益预测再固定仓位仅为对照。没有根据2026成绩选择赢家或追加调参。','',
        '## 实际训练内容','',
        '- Ridge、Elastic Net、逻辑回归、HGB、Q10/Q50/Q90：7种状态动作估计器，各训练折和最终折各一次，共14次有效拟合；Elastic验证折另有一次相同凸目标的数值继续。状态动作特征含股票特征、当前仓位、现金、持有年龄和目标仓位交互。求解器直接在全候选上联合选择0/2.5%/5%/7.5%/10%及最多20票，不先筛独立收益TOP20。属于一步反事实动作值近似。',
        f'- MLP和双种子RL：每类都有2023–2024训练/2025验证与2023–2025最终工件，有效版本v3共6个策略拟合、{neural["actual_parameter_updates"]:,}次参数更新。共享网络同时输入特征、模拟当前仓位和现金；TOP20投影、连续权重、费用、风险项均在训练循环里。MLP使用截断历史梯度的一步组合效用；RL使用有历史持仓状态的随机动作和折扣奖励。双种子同账户平均目标，零更新对照保留。',
        '- PCA五因子、LedoitWolf收缩风险在2025年末冻结，覆盖857只历史证券；两种风险矩阵也与联合HGB动作值共同求解组合。KMeans复用pre2026模型，IsolationForest另实际拟合一次，仅做状态诊断。',
        '- 所有拟合、标准化、风险估计及训练奖励消费价日期均早于2026；标签终点最多2025-12-31。验证按日期，不随机拆散股票日。固定模型/训练预算，无2026搜索。旧费用错误和神经v1/v2实现修复均保留，详见TRAINING_SUMMARY.md。','',
        '## 股票池与执行口径','',
        f'- 上一自然季度且当时已公开的13F，沿用现有24家机构来源和原源季度生效时点，未覆盖SEC全部机构申报。2026核证新买池为{data["signals"]["rows"]:,}行、{data["signals"]["days"]}个信号日；另108日无新买资格，允许现金和旧仓继续持有/退出，禁止新增买单。新买资格在成交层再次检查，防止隔夜权重漂移导致错误补仓。',
        '- 覆盖2026-01-02至09-22信号、下一会话开盘执行、09-24收盘终端估值，不是完整2026年。旧原合同使用开盘终端估值，本新分支明确采用每日收盘账本，不能直接与旧数值混榜。',
        '- 初始名义资金100万美元，单票目标<=10%、最多20个持仓目标、总目标<=95%；每日收盘定权重、次日开盘按届时NAV执行目标权重订单。新买交易受已知20日美元量1%容量代理限制；卖出采用允许退出的流动性假设并逐笔披露。单边综合费用/滑点代理10bp，另测试5bp和25bp。',
        '- 价格采用既有向前复权指数坐标，持仓单位为指数份额，未建立原始股份、拆股及分红现金权益账。下列数值是价格指数模拟，**不是认证股东总回报**。缺价或警示价格在被用于成交/估值当天设为不可用，不反向删除前一日候选。','',
        '## 固定候选比较','',
        '2025列为独立时间验证模型；2026列为最终pre2026模型。2026所有结果均限回顾性已验证子池，存在覆盖/幸存偏差，且过去已查看过2026信息。缺价天数大于0时，整条累计收益只作带陈旧估值的诊断，不认证其真实收益或回撤。','',
        '| 固定方案 | 2025验证指数收益 | 2026诊断指数收益 | 2026诊断最大回撤 | 2026平均现金 | 未核证估值日 |',
        '|---|---:|---:|---:|---:|---:|']
    for name,label in LABELS.items():
        r=main.loc[name];v=validation.loc[name].indicative_return if name in validation.index else np.nan
        lines.append(f'| {label} | {pct(v)} | {pct(r.indicative_return)} | {pct(r.indicative_max_drawdown)} | {r.mean_cash:.1%} | {int(r.uncertified_days)} |')
    lines+=['','PCA/收缩风险扩展没有用最终2025风险矩阵反算2025验证成绩，故该两格为空，防止验证期泄露。RL零更新是必要控制，不是挑选出的替代赢家。','',
        '## 成本压力测试','', '| 方案 | 单边5bp | 单边10bp | 单边25bp |','|---|---:|---:|---:|']
    for name,label in LABELS.items():
        r=comparison[comparison.policy.eq(name)].set_index('cost_bps_per_side')
        lines.append(f'| {label} | '+ ' | '.join(pct(r.loc[c].indicative_return) for c in [5,10,25])+' |')
    lines+=['','各成本情景重新回放同一冻结策略，反映现金和实际持仓路径差异；没有针对压力结果重训。`stale_position_stress.csv`另外给出期末陈旧持仓全部减记为零的压力情景，防止把陈旧估值当成已实现盈利；它不是正式收益或统计置信区间。','',
        '## 验证和剩余限制','',
        '- 新执行引擎与联合神经策略的32项定向测试通过，包括下一开盘不进入决策、未来标签列扰动不影响推理、费用双边实际扣款、现金恒等、部分卖出、缺价不成交、终端不额外交易、旧季度禁止实际加仓和未知持仓价拒绝训练奖励。联合离散动作求解还通过穷举及约束测试。',
        '- 最终独立全账本复核PASS：54次回放、86,108笔交易；41,941次买入/加仓的信号资格及下一会话成交全部通过；实际最多20持仓，现金累计重算最大误差3.96e-9，费用/NAV/成交价误差0；216项冻结源哈希无漂移、测试fit调用0。详见VERIFICATION.json。',
        '- 42个2026成本情景中36个存在未核证估值，最多145/183日。剩余6个是Q10三成本全现金与Q50三成本，并不免除子池偏差和价格指数限制。不能用上表数值给2026正式绩效排名。',
        '- 原全池共有111,868候选日，47,701仍未知，没有任何完整原池信号日获认证。本批只完成已核证子池研究，不能称全池TOP20或完整正式2026测试。进一步补齐数据是剩余实质工作；没有让这一缺口阻断已授权的联合模型训练和局部测试。',
        '- 线性/树模型使用有限的反事实账户状态和一步标签；MLP截断历史梯度；RL历史重复回放不增加独立市场样本。训练没有执行测试账本的成交量约束，两者差异保留。不存在防过拟合或未来可盈利的保证。',
        '- 本批不按测试收益宣称哪个方法有效。核证覆盖、价格坐标、模型迁移和成本误差解决前，结果不足以认证实盘表现。','',
        '## 交付入口','',
        '- `TRAINING_SUMMARY.md`：实际训练计数、修复及模型路径。',
        '- `evaluation_2025/comparison.csv`、`evaluation_2026/comparison.csv`：全部固定候选与成本结果。',
        '- `evaluation_2026/cost_10/<方案>_10bps/`：逐日净值、实际成交、持仓、目标、缺价和费用账；其它成本同结构。',
        '- `LAST_TEST_DATE_TARGETS.csv`：最后测试信号日各策略TOP20目标及买持加减退，属于历史测试输出，不是当前交易建议。',
        '- `portfolio_risk_diagnostics.csv`、`actual_action_counts.csv`：风险集中与真实动作统计。',
        '- `data/`：训练/测试观察、成熟标签、13F时点和原始缺口；`JOINT_CONTRACT.md`：用户澄清后的任务合同。',
        '- `run_suite.py`：冻结推理入口，`joint_linear_tree.py`和`joint_neural.py`：联合训练入口，`engine.py`：会计回放。已有完成输出受保护，重跑应复制到新目录。',
        '- 外部时间口径参考：[SEC Form 13F FAQ](https://www.sec.gov/rules-regulations/staff-guidance/division-investment-management-frequently-asked-questions/frequently-asked-questions-about-form-13f)。实际候选启用时点由本地申报/季度生效表逐行检查，不以季度末代替公开时间。','']
    (ROOT/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    write(ROOT/'evaluation_2026/COMPLETE.json',dict(status='VERIFIED_SUBSET_DIAGNOSTIC_COMPLETE',policies=14,evaluations=42,
        full_pool_formal_test=False,model_selection_from_2026=False,fit_guard_attempts=0,
        covered_signal_last='2026-09-22',terminal_close_valuation='2026-09-24'))
    print('Report and all result indices assembled',flush=True)

if __name__=='__main__':main()
