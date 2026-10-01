"""Publish all frozen candidates, never pick a model using 2026 returns."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from evaluate import ROOT, DATA, QUALIFIED, TEST_DATA, NAMES, sha, write, forbid_fitting
from risk_aux import aux_predict

LABELS={'joint_ridge':'Ridge','joint_elastic_net':'Elastic Net','joint_logistic':'逻辑回归',
        'joint_hgb':'HGB','joint_q10':'Q10','joint_q50':'Q50','joint_q90':'Q90',
        'joint_quantile_risk':'分位数联合风险','joint_mlp':'小型 MLP',
        'joint_rl_ensemble':'RL 双种子集成','joint_rl_zero_control':'RL 零更新对照',
        'cash_control':'现金对照','joint_hgb_lw':'HGB + 协方差收缩','joint_hgb_pca':'HGB + PCA风险',
        'ensemble_equal_weight':'六模型等权协同','ensemble_stacked':'样本外堆叠集成'}

def percent(x):return '—' if pd.isna(x) else f'{100*x:.2f}%'

def main():
    guard=forbid_fitting()
    ver=json.loads((ROOT/'VERIFICATION.json').read_text(encoding='utf-8'))
    assert ver['status']=='PASS' and ver['ledger_runs_checked']==64
    frames=[];last_targets=[];last_cash=[];monthly=[]
    for year,cost in [(2025,10),(2026,10),(2026,5),(2026,25)]:
        folder=ROOT/f'evaluation_{year}'/f'cost_{cost}'
        frames.append(pd.read_csv(folder/'comparison.csv'))
        if cost!=10:continue
        for name in NAMES:
            d=pd.read_parquet(folder/name/'daily.parquet')
            d['month']=pd.to_datetime(d.date).dt.to_period('M').astype(str)
            ends=d.groupby('month',sort=True).tail(1).copy()
            ends['indicative_monthly_return']=ends.nav/ends.nav.shift(1).fillna(1e6)-1
            ends['policy']=name;ends['year']=year
            monthly.append(ends[['policy','year','month','indicative_monthly_return']])
            if year!=2026:continue
            target=pd.read_parquet(folder/name/'target_decisions.parquet')
            contexts=pd.read_parquet(folder/name/'signal_contexts.parquet')
            date=contexts.signal_date.max()
            active=target.loc[target.signal_date.eq(date)&target.target_weight.gt(0)].copy()
            active=active.sort_values(['target_weight','ticker'],ascending=[False,True])
            active.insert(0,'policy',name);active.insert(1,'rank',np.arange(1,len(active)+1))
            last_targets.append(active)
            last_context=contexts.loc[contexts.signal_date.eq(date)].iloc[-1]
            committed=last_context.final_reserved_weight+last_context.active_target_weight
            last_cash.append(dict(policy=name,last_signal=str(date.date()),target_names=len(active),
                target_cash_weight=1-float(committed),last_valuation=str(d.date.max().date()),
                actual_cash_weight=float(d.cash_weight.iloc[-1]),
                note='Historical frozen diagnostic target; not a live order or recommendation'))
    table=pd.concat(frames,ignore_index=True)
    table.to_csv(ROOT/'ALL_RESULTS.csv',index=False)
    comparisons=[]
    for (year,cost),group in table.groupby(['year','cost_bps']):
        for ensemble in ['ensemble_equal_weight','ensemble_stacked']:
            e=group.set_index('policy').loc[ensemble]
            for base in ['joint_ridge','joint_elastic_net','joint_logistic','joint_hgb','joint_quantile_risk','joint_mlp']:
                b=group.set_index('policy').loc[base]
                comparisons.append(dict(year=year,cost_bps=cost,ensemble=ensemble,base=base,
                    indicative_return_delta=e.indicative_return-b.indicative_return,
                    indicative_drawdown_delta=e.indicative_max_drawdown-b.indicative_max_drawdown,
                    cash_weight_delta=e.mean_cash_weight-b.mean_cash_weight,
                    costs_delta_dollars=e.total_cost_dollars-b.total_cost_dollars,
                    turnover_delta=e.turnover-b.turnover,
                    conclusion_scope='descriptive comparison; exposure and uncertified prices may explain differences'))
    pd.DataFrame(comparisons).to_csv(ROOT/'ENSEMBLE_COMPARISONS.csv',index=False)
    pd.concat(monthly,ignore_index=True).to_csv(ROOT/'MONTHLY_RESULTS.csv',index=False)
    pd.concat(last_targets,ignore_index=True).to_csv(ROOT/'LAST_TOP20_TARGETS.csv',index=False)
    pd.DataFrame(last_cash).to_csv(ROOT/'LAST_CASH_WEIGHTS.csv',index=False)
    auxiliary=[]
    for year,stage,path in [(2025,'validation',DATA/'pre2026_joint_context.parquet'),(2026,'final',TEST_DATA/'test_features_context.parquet')]:
        panel=pd.read_parquet(path);panel=panel.loc[panel.signal_date.dt.year.eq(year)]
        pred=aux_predict(panel,stage=stage)
        pred.to_parquet(ROOT/f'auxiliary_diagnostics_{year}.parquet',index=False)
        counts=pred.groupby('state_cluster').agg(rows=('ticker','size'),anomalies=('is_anomaly','sum')).reset_index()
        counts['year']=year;auxiliary.append(counts)
    pd.concat(auxiliary,ignore_index=True).to_csv(ROOT/'AUXILIARY_DIAGNOSTICS.csv',index=False)
    value=json.loads((ROOT/'value_artifacts/FIT_RECEIPT.json').read_text(encoding='utf-8'))
    neural=json.loads((ROOT/'neural_artifacts/TRAIN_RECEIPT.json').read_text(encoding='utf-8'))
    registry={'status':'TRAINED_AND_FROZEN_EVALUATED','created_utc':pd.Timestamp.now(tz='UTC').isoformat(),
        'train_cutoff_exclusive':'2026-01-01','validation_fit_cutoff_exclusive':'2025-01-01',
        'selected_champion':None,'selection_using_2026':False,'live_deployed':False,
        'policy_names':NAMES,'supervised':value['fits'],'neural':neural['artifacts'],
        'ensemble_receipts':[str(x) for x in sorted((ROOT/'ensemble_artifacts').rglob('*RECEIPT.json'))],
        'risk_auxiliary':{f'{k}/{s}':str(ROOT/k/s/'TRAIN_RECEIPT.json')
                         for k in ['risk_artifacts','aux_artifacts'] for s in ['validation','final']}}
    write(ROOT/'MODEL_REGISTRY.json',registry)
    lines=['# 多模型联合训练结果（2026-09-28）','',
        '**本轮多模型协同/集成训练、64 次冻结回放和独立账本检查已完成。训练边界检查通过；全池、原始时点与正式投资绩效认证尚未通过。**','',
        '本轮新拟合14个主监督模型、6个主神经策略；另有7个early监督模型、1个early MLP用于生成2024样本外预测，以及2个元模型。总计30个预测/策略工件，风险与辅助模型另列。旧权重未用于初始化本轮模型。',
        '拟合/调参未使用2026数据；validation仅截至2024，2025用于固定规格验证；final仅截至2025。2026是已被观察过的历史留出集，本轮不据其表现选模型或追加搜索。','',
        '## 联合任务是怎样实现的','',
        '- **六模型等权协同**：Ridge、ElasticNet、逻辑回归、HGB、分位数风险与MLP，在同一个实际账户状态上提出目标；融合同单位仓位与现金，再保留最多20只。没有直接混加概率、收益和logit。',
        '- **样本外堆叠集成**：第二层Ridge学习如何组合7个基础预测与MLP偏好，再统一决定动作和仓位。2023-fit基础模型预测2024、2023–24-fit模型预测2025；validation元模型只用2024 OOF，final元模型用2024–25 OOF，2026不参与学习。',
        '- Ridge/ElasticNet/HGB/分位数使用同一股票—状态—目标仓位动作评分，再通过成本和最多20只等约束共同决定入选、增减持和现金。监督目标是单步、固定100万美元的容量近似，不是完整多期最优。',
        '- 逻辑回归预测动作效用为正的概率，概率不是收益率；独立作为策略比较。',
        '- 小型MLP共享网络直接优化组合效用；RL用序列策略梯度，两个种子固定集成。二者均将容量限制后的持仓和现金反馈给后续状态。',
        '- 现金是组合权重的剩余，允许少于20只；单票目标≤10%、总目标≤95%。由于保留持仓和市场价格漂移，实际权重可能偏离目标。',
        '- 风险方法分别增加协方差或5因子相关风险约束；聚类与异常检测仅诊断，不自动变成买卖信号。','',
        '## 主成本场景：单边10bp','',
        '下表2026收益是**未认证研究价格指数的参考回放值**，不能理解成实际可获得的收益或完整原池回报。所有方法按预定顺序列出，不按2026排名选优。','',
        '| 方法 | 2025参考净收益 | 2026参考净收益 | 2026平均现金 | 2026交易费/初始资金 | 2026未认证估值日 |',
        '|---|---:|---:|---:|---:|---:|']
    for name in NAMES:
        a=table[(table.year==2025)&(table.cost_bps==10)&table.policy.eq(name)].iloc[0]
        b=table[(table.year==2026)&(table.cost_bps==10)&table.policy.eq(name)].iloc[0]
        lines.append(f'| {LABELS[name]} | {percent(a.indicative_return)} | {percent(b.indicative_return)} | {percent(b.mean_cash_weight)} | {percent(b.total_cost_dollars/1e6)} | {int(b.uncertified_valuation_days)} |')
    lines += ['', '完整收益、参考回撤、波动、Sharpe、换手、费用、买卖数及5/10/25bp压力场景见 `ALL_RESULTS.csv`；未认证2026数据上的风险指标同样只能作诊断。',
        '两种集成与六个成员逐一对比见 `ENSEMBLE_COMPARISONS.csv`，同时列出收益差、回撤差、现金差、费用差和换手差。更多现金或风险暴露变化不能直接归功于更强的预测能力。堆叠最终部署时基础模型的拟合样本较OOF阶段更多，存在常见的OOF到最终模型分布差异。','',
        '## 防泄漏、过拟合与收益虚高','',
        '- 候选池沿用最近已公开且按原系统第5个交易日生效的13F季度；新一期生效前延续上一期，不按季度末提前回填。',
        '- 监督标签同时检查signal_date和label_end_date：validation均<2025-01-01，final均<2026-01-01；所有拟合与标准化各阶段独立。',
        '- 监督训练每阶段保留全部成熟日期，在日内按固定哈希抽样；反事实扩增行不当作独立样本数。参数、epoch、种子、模型名单和成本场景事先固定，零搜索；仅允许同目标数值收敛修复。',
        '- 收盘信号、下一开盘成交；扣实际成交费用；缺价格不能成交；缺模型输入保留原单位并占用资金和名额。实际买入每股最多使用信号ADV的1%。',
        f'- `{ver["ledger_runs_checked"]}` 个账本全部独立重建现金和持仓，核对费用、成交时钟、股票池、买入容量、持仓数及源文件哈希；测试阶段fit/优化器更新尝试为0。','',
        '## 仍未解决的证据限制','',
        '- 2026是事后核验子池：原输入62,393条可买、62,476条上下文；因下述GLW隔离，本轮实际为62,392条可买、62,475条上下文。原池仍有47,271条未知，完整原池覆盖日为0，且新增1条明确隔离。选择/可得性偏差不能靠模型代码检查消除。',
        '- 已封住GLW 2026-02-26已知冲突的特征与价格消费：隔离1条观察、1条价格加warning，原始数值与证据保存；已有持仓不被虚构清仓。原始供应商时点和其他价格资格未完全证实，仍不能宣称全链路零未来信息泄漏。规则在首次测试前统一冻结，未按表现修改股票或窗口。',
        '- 本轮测试为2026-01-02至2026-09-22信号、09-23末执行、09-24末估值，不是完整全年。',
        '- 使用调整价格指数单位，未认证分红、公司行动权益和真实成交冲击；现金收益假定为0。10bp与1%ADV是固定研究假设，不是实盘成本保证。',
        '- 训练完成不证明复杂模型优于简单模型。没有根据2026结果晋级模型，也没有部署或下单。','',
        '## 交付与复用','',
        '- `MODEL_REGISTRY.json`：新模型路径和哈希；`value_artifacts`、`neural_artifacts`、`risk_artifacts`、`aux_artifacts`：全部训练工件。',
        '- `EXPERIMENT_CONTRACT.md` 与 `ENSEMBLE_CONTRACT.md`：预拟合合同和用户澄清后的集成补充；`audit/INPUT_AUDIT.md`：输入证据及限制；`VERIFICATION.json`：64次回放审计。',
        '- `LAST_TOP20_TARGETS.csv` 与 `LAST_CASH_WEIGHTS.csv`：每个策略最后历史信号的仓位与现金；不构成当前交易指令。',
        '- `evaluation_2025`、`evaluation_2026`：逐日净值、目标、成交、持仓、原始动作值及拒单；`auxiliary_diagnostics_*.parquet`：辅助模型冻结推理。',
        '- `README.md`：加载与验证入口。', '',
        '时点原则参考：[SEC Form 13F](https://www.sec.gov/files/form13f.pdf)、[scikit-learn 数据泄漏说明](https://scikit-learn.org/stable/common_pitfalls.html)。']
    (ROOT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    assert guard['attempts']==0
    outputs=['REPORT.md','ALL_RESULTS.csv','MONTHLY_RESULTS.csv','LAST_TOP20_TARGETS.csv','LAST_CASH_WEIGHTS.csv','MODEL_REGISTRY.json','VERIFICATION.json']
    write(ROOT/'COMPLETION.json',dict(status='TRAINING_AND_RESEARCH_EVALUATION_COMPLETE',
        pre2026_training_verified=True,full_pool_no_leakage_certified=False,live_deployed=False,
        supervised_fits=14,neural_fits=6,early_supervised_fits=7,early_neural_fits=1,meta_fits=2,
        evaluation_runs=64,outputs_sha256={x:sha(ROOT/x) for x in outputs}))
    print(json.dumps({'status':'TRAINING_AND_RESEARCH_EVALUATION_COMPLETE','report':str(ROOT/'REPORT.md')}),flush=True)

if __name__=='__main__':main()
