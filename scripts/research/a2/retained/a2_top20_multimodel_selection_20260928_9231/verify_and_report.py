"""Independent checks of frozen sources and actual account books; no fitting."""
from pathlib import Path
import hashlib,json
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parent

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))

def inspect(folder):
    done=read(folder/'DONE.json')
    d=pd.read_parquet(folder/'daily.parquet')
    trades=pd.read_parquet(folder/'trades.parquet')
    positions=pd.read_parquet(folder/'positions.parquet')
    targets=pd.read_parquet(folder/'target_decisions.parquet')
    checks={}
    assert done['policy']==folder.name
    assert done['year']==int(folder.parent.parent.name.split('_')[-1])
    assert done['cost_bps']==float(folder.parent.name.split('_')[-1])
    nav=np.r_[1e6,d.nav.to_numpy(float)]
    assert np.isclose(done['indicative_return'],nav[-1]/1e6-1,rtol=0,atol=1e-12)
    assert np.isclose(done['indicative_max_drawdown'],(nav/np.maximum.accumulate(nav)-1).min(),rtol=0,atol=1e-12)
    assert np.isclose(done['total_cost_dollars'],d.transaction_cost_amount.sum(),rtol=0,atol=1e-6)
    assert done['trades']==len(trades) and done['max_actual_names']==int(d.actual_name_count.max())
    assert d.cash.min()>=-1e-6
    assert d.actual_name_count.max()<=20
    for key in ['cash_flow_identity_error','cost_identity_error','nav_identity_error','open_self_finance_error']:
        x=d[key].dropna().abs();checks[key]=float(x.max()) if len(x) else 0.
        assert checks[key]<1e-6,(folder,key,checks[key])
    # Rebuild cash from trade rows, separately from the replay's own residuals.
    signed=pd.Series(0.,index=d.date)
    fees=pd.Series(0.,index=d.date)
    if len(trades):
        assert (trades.execution_date>trades.signal_date).all()
        assert np.allclose(trades.notional,trades.index_units*trades.price,rtol=1e-10,atol=1e-7)
        assert np.allclose(trades.transaction_cost,trades.notional*done['cost_bps']/10000,rtol=1e-10,atol=1e-7)
        flow=np.where(trades.side.eq('SELL'),trades.notional,-trades.notional)-trades.transaction_cost.to_numpy(float)
        signed=pd.Series(flow,index=trades.execution_date).groupby(level=0).sum().reindex(d.date,fill_value=0.)
        fees=trades.groupby('execution_date').transaction_cost.sum().reindex(d.date,fill_value=0.)
        buys=trades.loc[trades.side.eq('BUY')]
        assert buys.capacity_enforced.astype(bool).all()
        assert np.isfinite(buys.capacity_adv).all() and buys.capacity_adv.gt(0).all()
        assert (buys.notional<=buys.capacity_adv*.01+1e-6).all()
        assert (buys.capacity_adv_source_date==buys.signal_date).all()
        for _,group in trades.groupby('ticker',sort=False):
            ordered=group.sort_values('execution_date',kind='stable')
            change=np.where(ordered.side.eq('BUY'),ordered.index_units,-ordered.index_units)
            after=np.cumsum(change);before=np.r_[0.,after[:-1]]
            np.testing.assert_allclose(before,ordered.index_units_before,atol=1e-8,rtol=1e-9)
            np.testing.assert_allclose(after,ordered.index_units_after,atol=1e-8,rtol=1e-9)
    checks['cash_rebuilt_from_trades_error']=float(np.max(np.abs(1e6+signed.cumsum().to_numpy()-d.cash.to_numpy())))
    checks['cost_rebuilt_from_trades_error']=float(np.max(np.abs(fees.to_numpy()-d.transaction_cost_amount.to_numpy())))
    assert checks['cash_rebuilt_from_trades_error']<1e-5
    assert checks['cost_rebuilt_from_trades_error']<1e-6
    if len(positions):
        assert positions.groupby('date').ticker.nunique().max()<=20
        known=positions.mark_date.notna()
        assert (positions.loc[known,'mark_date']<=positions.loc[known,'date']).all()
        assert np.allclose(positions.market_value,positions.index_units*positions.mark,equal_nan=True,rtol=1e-10,atol=1e-6)
        mv=positions.groupby('date').market_value.sum().reindex(d.date,fill_value=0.)
        checks['nav_rebuilt_from_positions_error']=float(np.nanmax(np.abs(mv.to_numpy()+d.cash.to_numpy()-d.nav.to_numpy())))
        assert checks['nav_rebuilt_from_positions_error']<1e-5
        names=sorted(set(positions.ticker)|set(trades.ticker))
        delta=trades.assign(unit_delta=np.where(trades.side.eq('BUY'),trades.index_units,-trades.index_units))
        flow=delta.pivot_table(index='execution_date',columns='ticker',values='unit_delta',aggfunc='sum',fill_value=0.)
        rebuilt=flow.reindex(index=d.date,columns=names,fill_value=0.).fillna(0.).cumsum()
        observed=positions.pivot(index='date',columns='ticker',values='index_units').reindex(index=d.date,columns=names).fillna(0.)
        checks['units_rebuilt_from_trades_error']=float(np.max(np.abs(rebuilt.to_numpy()-observed.to_numpy())))
        np.testing.assert_allclose(rebuilt.to_numpy(),observed.to_numpy(),atol=1e-8,rtol=1e-9)
    if len(targets):
        # Preserved fixed units can legitimately drift above a target-weight cap.
        w=targets.loc[targets.order_type.ne('HOLD_UNITS'),'adapted_target_weight'].dropna()
        assert w.ge(-1e-10).all() and w.le(.1+1e-10).all()
        assert targets.groupby('signal_date').active_target_sum.first().le(.95+1e-8).all()
        assert (targets.active_target_sum<=np.maximum(.95-targets.reserved_weight,0.)+1e-8).all()
        assert targets.loc[targets.decision_semantic.eq('MODEL_ACTIVE_EXIT'),'explicit_model_decision'].all()
        assert targets.loc[targets.decision_semantic.eq('MODEL_NO_DECISION'),'order_type'].eq('HOLD_UNITS').all()
        held=targets.loc[targets.order_type.eq('HOLD_UNITS') & targets.execution_date.isin(d.date)]
        if len(held):
            observed=held.merge(positions[['date','ticker','index_units']],left_on=['execution_date','ticker'],
                right_on=['date','ticker'],how='left',validate='one_to_one')
            np.testing.assert_allclose(observed.hold_units,observed.index_units.fillna(0.),atol=1e-8,rtol=1e-9)
    return dict(path=str(folder.relative_to(ROOT)),status='PASS',checks=checks,**done)


def main():
    scenarios=[];all_rows=[];last=[]
    for year,cost in [(2025,10),(2026,10),(2026,5),(2026,25)]:
        out=ROOT/f'evaluation_{year}'/f'cost_{cost}'
        complete=read(out/'COMPLETE.json');assert complete['fit_attempts']==0
        frozen=read(out/'FROZEN_BEFORE_REPLAY.json')
        assert complete['policies']==len(frozen['roster'])==19
        assert all(sha(p)==h for p,h in frozen['source_sha256'].items()),'Frozen input changed'
        for name in frozen['roster']:
            row=inspect(out/name);all_rows.append(row)
            if year==2026 and cost==10:
                t=pd.read_parquet(out/name/'target_decisions.parquet')
                if len(t):
                    t=t.loc[t.signal_date.eq(t.signal_date.max())].copy();t['policy']=name;last.append(t)
        scenarios.append(dict(year=year,cost=cost,policies=len(frozen['roster']),source_hashes_verified=True))
    summary=pd.DataFrame([{k:v for k,v in r.items() if k not in ['checks']} for r in all_rows])
    summary.to_csv(ROOT/'MODEL_COMPARISON.csv',index=False)
    if last:pd.concat(last,ignore_index=True).to_csv(ROOT/'LAST_TEST_SIGNAL_TOP20_AND_ACTIONS.csv',index=False)
    result=dict(status='PASS',scenarios=scenarios,paths=all_rows,full_pool_certified=False,
                blind_test=False,fit_2026_rows=0,checks='cash, costs, mark values, positions, clock, capacity, constraints, source hashes')
    (ROOT/'VERIFICATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    table=[]
    val=summary.loc[(summary.year==2025)&summary.cost_bps.eq(10)].set_index('policy')
    test=summary.loc[(summary.year==2026)&summary.cost_bps.eq(10)].set_index('policy')
    ordered=['ensemble_equal','ensemble_disagreement','ensemble_stacking']+[n for n in test.index if not n.startswith('ensemble_')]
    for name in ordered:
        r=test.loc[name]
        table.append(f"| {name} | {val.loc[name,'indicative_return']:.2%} | {r.indicative_return:.2%} | {r.indicative_max_drawdown:.2%} | {r.mean_cash_weight:.2%} | {int(r.uncertified_valuation_days)} |")
    report='''# TOP20 多模型选股新训练结果\n\n所有预定模型均在本目录重新拟合；2026没有拟合、更新或选参。2025使用截至2024年的独立模型，2026使用截至2025年的最终模型。测试年已被其他实验观察，本批不称首次盲测，不根据结果选择冠军。\n\n## 输入与时钟\n\n训练上下文为2023–2025共313,668行/752日；成熟单步标签最终312,707行，验证拟合201,385行。各时点取最近公开且按原规则生效的13F季度池（当季24家机构披露完成后第5个交易日）；新期未生效时沿用旧期。线性、树与分位数每阶段按日期/证券键抽样13,333基础行、199,995状态动作行，覆盖每个成熟交易日；神经模型按完整序列训练。\n\n2026信号窗为01-02至09-22，共181日，末成交09-23，末估值09-24。原111,868候选行仍有47,271个未知候选日，完整覆盖日为0；本批62,393可新买行加83持仓上下文行只支持核验子池诊断。历史训练池也经过证券身份、价格可得性及121日特征历史筛选。真实供应商到达时间、完整幸存偏差与GLW事件日期冲突未解决。\n\n## 统一评估\n\n收盘决策、下一开盘成交；最多20个实际持仓，单票目标最多10%，总目标95%，初始研究本金100万美元；单边10bp，买入不超过信号ADV的1%。已有持仓缺模型输入时保留单位、资金与名额。保留真实费用、未成交、现金、目标和实际持仓账。研究使用调整价格指数单位，以下收益为期内费用后指示性价格指数收益，不能当作认证股东收益或完整2026全年回报。\n\n| 路径 | 2025验证收益 | 2026测试收益（非认证） | 2026最大回撤 | 平均现金 | 未认证估值日 |\n|---|---:|---:|---:|---:|---:|\n'''+ '\n'.join(table)
    report+='''\n\n5bp及25bp冻结成本压力结果见 MODEL_COMPARISON.csv；不同费用会改变后续持仓路径，因此不是从10bp终值简单减一笔费用。分位数模型估计的是单步含成本状态动作效用分布；逻辑回归估计正效用概率。MLP优化组合效用，RL为双种子REINFORCE，其单种子路径只用于稳定性诊断。PCA/LW分别在2024及2025边界拟合；聚类/异常只作诊断，不事后删除亏损样本。\n\nVERIFICATION.json包含64条账户路径的独立现金/交易费用/持仓估值重建、持仓数量、成交时间、容量约束和来源哈希检查。METHOD_COVERAGE.json和TRAINING_SUMMARY.md记录真实拟合与更新次数。LAST_TEST_SIGNAL_TOP20_AND_ACTIONS.csv为历史测试末信号各模型目标与动作，含明确退出和保留持仓，不是当前买入建议。\n\n已完成本批新训练及可用数据上的冻结评估；完整原始13F全池认证测试未完成，不能用子池成绩代替。\n'''
    report=report.replace('64条账户路径',f'{len(all_rows)}条账户路径')
    intro='''## 本次重点：六模型协同\n\n融合输入是 Ridge、Elastic Net、逻辑回归、HGB、Q50 和小MLP。先把不同单位的输出转成保留正负号的动作优势排名，再用三种固定方案组合：等权均值、均值减模型分歧与Q10下行惩罚、非负Ridge第二层融合。三个方案最终都共同决定TOP20与目标仓位，单模型保留作对照。\n\nStacking使用2024和2025真实按时间隔离的基础预测，不能用基础模型的拟合内预测代替。每年6000证券日×3账户状态×5动作，90,000条OOF行；validation元模型只用2024，final元模型用2024+2025。所有跨截面排名在完整当日可用池生成，之后才抽取训练标签。六个元模型系数见TRAINING_SUMMARY.md，系数不是实际持仓比例。\n\n'''
    report=report.replace('## 输入与时钟',intro+'## 输入与时钟')
    (ROOT/'REPORT.md').write_text(report,encoding='utf-8')
    print(json.dumps({'status':'PASS','paths':len(all_rows),'full_pool_certified':False}))

if __name__=='__main__':main()
