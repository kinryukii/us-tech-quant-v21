"""Deliver the completed finite experiment, including every negative and limit."""
from common import *
from datetime import datetime,timezone

def link(label,path):return f'[{label}]({(ROOT/path).as_posix()})'
def number(value,percent=False):
    if pd.isna(value):return '缺失'
    return f'{100*float(value):.2f}%' if percent else f'{float(value):.3f}'
def markdown(frame):
    cols=list(frame.columns)
    values=[[str(v).replace('|',' / ').replace('\n',' ') for v in row] for row in frame.itertuples(index=False,name=None)]
    return '\n'.join(['| '+' | '.join(cols)+' |','| '+' | '.join(['---']*len(cols))+' |']+['| '+' | '.join(row)+' |' for row in values])

def layer_effect_ranges(out):
    """Describe every non-reference method, with no winner assembly or selection."""
    specs=[('单成员预测','PREDICTOR_PAIRED_CONTRASTS.csv',['stream'],lambda t:t.bundle.eq('singleton')&t.stream.ne('ridge')),
        ('同集合预测融合','FUSION_PAIRED_CONTRASTS.csv',['bundle','fusion'],lambda t:t.fusion.ne('equal')),
        ('风险','RISK_PAIRED_CONTRASTS.csv',['risk'],lambda t:t.risk.ne('diagonal')),
        ('优化','OPTIMIZER_PAIRED_CONTRASTS.csv',['optimizer'],lambda t:t.optimizer.ne('mean_variance')),
        ('目标融合','TARGET_FUSION_PAIRED_CONTRASTS.csv',['target_fusion'],lambda t:t.target_fusion.ne('target_equal'))]
    metrics=['delta_indicative_return','delta_indicative_max_drawdown','delta_mean_gross_exposure','delta_fees']
    expected_counts={'单成员预测':(30,1080),'同集合预测融合':(40,1440),'风险':(11,2541),'优化':(2,1848),'目标融合':(1,36)}
    records=[]
    for label,file,dimensions,mask in specs:
        data=pd.read_csv(out/file);data=data.loc[mask(data)]
        for (year,axis),part in data.groupby(['year','axis']):
            if not np.isfinite(part[metrics].to_numpy(float)).all():raise RuntimeError('LAYER_RANGE_NONFINITE_PAIRED_SUPPORT:'+label)
            method_medians=[];switching=0
            for _,group in part.groupby(dimensions,dropna=False):
                method_medians.append({c:group.loc[np.isfinite(group[c]),c].median() for c in metrics})
                values=group.delta_indicative_return.to_numpy(float)
                values=values[np.isfinite(values)]
                switching+=int((values>1e-12).any() and (values<-1e-12).any())
            medians=pd.DataFrame(method_medians)
            if (len(medians),len(part))!=expected_counts[label]:raise RuntimeError('LAYER_RANGE_EXACT_SUPPORT_CHANGED:'+label)
            def interval(column,percent=True):
                values=medians.loc[np.isfinite(medians[column]),column]
                return number(values.min(),percent)+' 至 '+number(values.max(),percent)
            records.append({'年份':int(year),'轴':axis,'层':label,'非参照方法数':len(medians),'配对格数':len(part),
                '各方法收益差中位数范围':interval(metrics[0]),'回撤差中位数范围':interval(metrics[1]),
                '敞口差中位数范围':interval(metrics[2]),'费用差中位数范围USD':interval(metrics[3],False),
                '收益符号随搭配变化的方法数':switching})
    frame=pd.DataFrame(records)
    keys=set(zip(frame['年份'],frame['轴'],frame['层']))
    if len(frame)!=40 or keys!={(year,axis,label) for year in [2025,2026] for axis in AXES for label in expected_counts}:raise RuntimeError('LAYER_RANGE_EXACT_40_KEYS_CHANGED')
    return frame

def solver_quality_summary(out):
    receipt=json.loads((out/'SOLVER_QUALITY_RECEIPT.json').read_text(encoding='utf-8'))
    if not receipt['complete']:raise RuntimeError('SOLVER_QUALITY_NOT_COMPLETE_FOR_REPORT')
    ordinary=pd.read_csv(out/'SOLVER_QUALITY_BY_STRATEGY.csv')
    ordinary=ordinary.loc[ordinary.target_fusion.eq('none')]
    experts=pd.read_csv(out/'SOLVER_QUALITY_BY_TARGET_EXPERT.csv')
    records=[]
    for label,data,prefix in [('普通预测账户',ordinary,'outer'),('同账户目标专家',experts,'expert')]:
        for (year,opt),group in data.groupby(['year','optimizer']):
            denominator=int(group[prefix+'_certificate_denominator_records'].sum())
            certified=int(group[prefix+'_certified_status_records'].sum())
            approximate=int(group[prefix+'_approximate_budget_records'].sum())
            support=group[prefix+'_approximate_residual_finite_records'].to_numpy(float)
            means=group[prefix+'_approximate_residual_mean'].to_numpy(float)
            finite=(support>0)&np.isfinite(means)
            n=int(support[finite].sum())
            mean=float((support[finite]*means[finite]).sum()/n) if n else np.nan
            maximum=group[prefix+'_approximate_residual_max'].max()
            missing=int(group[[prefix+'_approximate_residual_'+tag+'_records' for tag in ['missing','nonfinite','nonnumeric']]].sum().sum())
            records.append({'年份':int(year),'优化':opt,'范围':label,'全部源调用分母':denominator,
                '容差或现金状态比例':certified/denominator if denominator else np.nan,
                '固定预算近似比例':approximate/denominator if denominator else np.nan,
                '近似有限残差数':n,'近似残差均值':mean,'近似残差最大':maximum,'近似缺失或无效残差数':missing})
    frame=pd.DataFrame(records)
    if len(frame)!=12 or set(zip(frame['年份'],frame['优化'],frame['范围']))!={(year,opt,label) for year in [2025,2026] for opt in OPTIMIZERS for label in ['普通预测账户','同账户目标专家']}:raise RuntimeError('SOLVER_SUMMARY_EXACT12_KEYS')
    frame.to_csv(out/'SOLVER_QUALITY_SUMMARY.csv',index=False)
    display=frame.copy()
    for column in ['容差或现金状态比例','固定预算近似比例']:display[column]=display[column].map(lambda v:number(v,True))
    for column in ['近似残差均值','近似残差最大']:display[column]=display[column].map(lambda v:'无近似调用' if pd.isna(v) else f'{v:.3g}')
    return display

def main():
    r=json.loads((ROOT/'COMPLETION.json').read_text(encoding='utf-8'))
    if r['status']!='COMPLETE_REGISTERED_DIAGNOSTICS_FORMAL_FULL_POOL_BLOCKED_DATA':raise RuntimeError('COMPLETED_REGISTERED_EXPERIMENT_REQUIRED')
    out=ROOT/'analysis';table=pd.read_csv(out/'ALL_POSITIVE_NEGATIVE_RESULTS.csv');rl=pd.read_csv(out/'RL_RESULTS.csv')
    all_results=pd.concat([table.assign(route='PTO'),rl.assign(route='RL')],ignore_index=True)
    if len(all_results)!=22184 or table.duplicated(['year','strategy']).any() or rl.duplicated(['year','policy']).any():raise RuntimeError('DELIVERY_RESULT_ROWS_NOT_EXACT22184')
    all_results.to_csv(out/'ALL_STRATEGY_RESULTS.csv',index=False)
    summary=[]
    for (year,axis),g in table.groupby(['year','axis']):
        finite=g[np.isfinite(g.indicative_return)]
        missing=len(g)-len(finite)
        if int(finite.indicative_return.gt(0).sum()+finite.indicative_return.lt(0).sum()+finite.indicative_return.eq(0).sum())+missing!=len(g):raise RuntimeError('RESULT_SIGN_COUNTS_DO_NOT_CLOSE')
        summary.append({'年份':year,'轴':axis,'账户':len(g),'正收益':int(finite.indicative_return.gt(0).sum()),'负收益':int(finite.indicative_return.lt(0).sum()),
            '零收益':int(finite.indicative_return.eq(0).sum()),'非有限收益':missing,'收益中位数':number(finite.indicative_return.median(),True),
            '平均敞口中位数':number(g.mean_gross_exposure.median(),True),'费用中位数USD':number(g.fees.median())})
    winners=[]
    for (year,axis),g in table.groupby(['year','axis']):
        best=g.sort_values(['indicative_return','strategy'],ascending=[False,True]).iloc[0]
        winners.append({'年份':year,'轴':axis,'完整组合':best.strategy,'指示收益':number(best.indicative_return,True),
            '指示最大回撤':number(best.indicative_max_drawdown,True),'平均敞口':number(best.mean_gross_exposure,True),
            '费用USD':number(best.fees),'未认证估值日':int(best.uncertified_days)})
    solver=pd.read_csv(out/'SOLVER_STATUS.csv');risk=pd.read_csv(out/'RISK_INFERENCE_DIAGNOSTICS.csv')
    fallbacks=pd.read_csv(out/'RISK_FIT_FAILURES_AND_FALLBACKS.csv')
    layer_ranges=layer_effect_ranges(out)
    layer_ranges.to_csv(out/'LAYER_EFFECT_RANGES.csv',index=False)
    quality_summary=solver_quality_summary(out)
    lines=['# A2 Predict-then-Optimize 有限全兼容组合实验',
        '',f'交付时间：{datetime.now(timezone.utc).isoformat()}。全部事前注册学习与可用输入诊断已执行：93 个基础成员阶段（129 个实际估计器）、75 预测流、12 风险、3 优化、4 轴；目标融合单列。2025 与2026 各11088个PTO账户，共22176；RL另8个，共22184个独立账户。完成固定清单后停止，没有新增成员、种子、期限、权重或训练预算。',
        '', '**正式完整13F池仍为 BLOCKED_DATA。** 2026全部111868候选键保留；当前62392合格、47272未知（原47271加GLW日期冲突1行）、2204已证不适格。181个信号日完整候选覆盖为0。因此本报告的2026成绩是资格子池诊断，不能称完整候选池TOP20结果。训练时钟合法也不能修复原静态身份、历史供应商到达/版本及仿射价格指数的认证限制。',
        '',link('完整账户覆盖与状态','analysis/COMBINATION_COVERAGE.csv')+' · '+link('正式全池逐路径阻塞表','analysis/FORMAL_FULL_POOL_COVERAGE.csv')+' · '+link('全部正负结果含RL','analysis/ALL_STRATEGY_RESULTS.csv')+' · '+link('最终核验收据','COMPLETION.json'),
        '', '## 固定合同、13F与冻结',
        '', '股票池沿用原24家机构规则：合格股权持仓按reported USD value每机构前100，原protected core/机构数/conviction/value并集规则及900上限，原身份映射和去重。季度未公开或未到第五后续交易日生效时沿用上一有效季度，必要时递归最近历史池；不按自然季度清空、不提前消费未来季度。Citadel Q2重报按9/10生效，原函数重建后仍575只。',
        '', '统一32特征；收盘信号，下一开盘成交，再下一开盘目标终点，一交易日期限。每成熟可买信号日同SHA256顺序80个样本，唯一seed20260928；训练目标截断±20%，评估原值。2024预测来自仅2023训练，2025预测来自仅截至2024训练；最终仅截至2025训练。接口与融合用嵌套时间合法OOF，残差修正第一层只用元窗口前半段、第二层后半段。',
        '',f'全部学习完成后冻结{r["frozen_files_verified"]}个工件，随后才进行本批2026推理与账户回放，0次2026 fit/update。Raw A2与旧冻结批次均保持原工件，旧源文件按哈希核验，没有用本批模型覆盖。旧2026暴露记录保留，结果是冻结的已观察历史评估，不能称盲测。2026信号为1/2–9/22，下一开盘执行与期限/估值日历至9/24；不是完整全年。',
        '', '本金100万美元、最多20个实际名字、主动单票目标10%、投资预算95%、单边10bp、信号ADV1%买入容量；现金零收益，下一开盘执行，无终端清仓。缺预测、缺输入、未认证报价持仓保留单位、预算与名额；明确零才是退出，卖不出去不能提前释放名额。价格单位是研究指数单位，收益未认证为股东总收益。10%/95%是主动目标上限，持仓随价格漂移可超过，逐行另记。',
        '',link('事前合同与清单','EXPERIMENT_CONTRACT.md')+' · '+link('逐组合兼容矩阵','COMPATIBILITY_MATRIX.csv')+' · '+link('统计接口兼容说明','INPUT_OUTPUT_COMPATIBILITY.md')+' · '+link('模块训练全覆盖','analysis/MODULE_TRAINING_COVERAGE.csv')+' · '+link('旧工件不匹配理由','analysis/ARTIFACT_REUSE_COMPATIBILITY.csv')+' · '+link('全批冻结','FREEZE.json'),
        '', '## 全部账户结果及完整组合',
        '', '下表包含每轴所有路径；正、负、零收益均保留。净值与费用来自各策略独立实际单位和现金，未平均其他账户来代替融合。',
        '',markdown(pd.DataFrame(summary)),
        '', '以下仅为已完成诊断账户的事后收益最高组合，不作为再训练或部署选择。完整表保留全部对手、回撤、暴露、现金、费用、换手及估值状态。收益最高不代表该预测器或某层普遍占优，也不建立未来可交易能力。',
        '',markdown(pd.DataFrame(winners)),
        '', '## 各层作用、合作及交互',
        '', '配对差分均固定其余注册维度、年份与轴，比较的是完整独立资金账户路径；资金独立不等于统计独立，配对格数与胜率不是重复试验样本量。其内生持仓与现金会不同，不能解释成相同瞬时状态下的独立因果效应。预测对Ridge、风险对diagonal、优化对mean_variance；预测融合在同成员集合内对equal，目标融合median对equal。两阶差分为Y11−Y10−Y01+Y00，三阶采用八格；回撤为负值，正差分表示回撤变浅，费用正差分表示成本增加，不能把正交互统一称为有利。2025回放使用截至2024的阶段工件，但2025标签用于本批最终学习，2025不是整批最终工件的独立验证年。',
        '',link('预测流配对','analysis/PREDICTOR_PAIRED_CONTRASTS.csv')+' · '+link('同集合预测融合配对','analysis/FUSION_PAIRED_CONTRASTS.csv')+' · '+link('风险配对','analysis/RISK_PAIRED_CONTRASTS.csv')+' · '+link('优化配对','analysis/OPTIMIZER_PAIRED_CONTRASTS.csv')+' · '+link('买卖现金轴配对','analysis/BUY_SELL_CASH_PAIRED_CONTRASTS.csv'),
        '',link('预测/风险/优化交互','analysis/LAYER_INTERACTIONS.csv')+' · '+link('固定集合融合及目标融合交互','analysis/FUSION_LAYER_INTERACTIONS.csv')+' · '+link('同账户13专家目标贡献','analysis/TARGET_EXPERT_CONTRIBUTIONS.csv')+' · '+link('目标融合与独立点预测账户对照','analysis/TARGET_FUSION_VS_POINT_ACCOUNT_PATHS.csv'),
        '', '13个专家各自先选TOP20。等权目标融合可能形成更宽的名字并集，共同名额投影删除较小目标后不重配被删资本；逐票中位数在多数专家给零时也给零。这两种机制本身能提高现金比例。投影前后gross、名字数、专家零目标和同账户目标分歧全部保存，低回撤不能据此直接归因于专家学习改善。',
        '', '各层边际均值、中位数、范围、格数另按joint/buy/sell/cash保存；融合汇总按成员集合分层。图与配对摘要基于全部注册路径，不采用每层挑冠军拼接。',
        '', '边际CSV使用75条预测流的core网格：每风险/年份/轴225格；风险与优化配对表另含2种目标融合，对应每风险231格，两者支持总体不同。singleton/identity边际汇总合并31个不同单成员，不能当同成员集合的融合消融；真正预测融合配对只在4个固定集合内进行，每方法/集合/年份/轴36格。交互表保留参照格按定义产生的结构零，它们的零比例不能作为模型无交互的证据。',
        '', '下表先对每个非参照方法在合法搭配内计算配对差中位数，再列出全部方法的范围；没有选出某层冠军。最后一列统计同一方法在不同搭配中同时出现正、负收益差的数量，可直接检查其作用是否依赖搭配。回撤差、敞口差和费用差与收益差同时呈现，正差分不统一等于改进。',
        '',markdown(layer_ranges),
        '',link('全部层效应范围与符号变化','analysis/LAYER_EFFECT_RANGES.csv'),
        '',link('买点全部方法比较','analysis/COMPARISON_BUY.md')+' · '+link('卖点全部方法比较','analysis/COMPARISON_SELL.md')+' · '+link('现金比例全部方法比较','analysis/COMPARISON_CASH.md')+' · '+link('联合全部方法比较','analysis/COMPARISON_JOINT.md'),
        '', '## 预测诊断、风险及数值状态',
        '', 'RMSE分别使用原值与截断目标，prob Brier、原始rank IC、分位数pinball/crossing/覆盖、Normal原分布NLL/PIT与校准尺度覆盖均只作诊断，并报告有效标签支持。概率经OOF映射到同单位收益；分位数中位数和rank不冒称均值。个股分位数不是组合联合分布。CVaR先将共同历史标准残差白化并映射到所选风险协方差；Normal分支按该风险情景的共同秩改为正态边际，分位数分支改变正负尾部形状，均再保持情景边际尺度。因此保留的是风险映射后的情景秩，不是未经处理的原始历史秩；边际变换仍可能改变线性相关，三分位数也未构成精确完整边际分布。秩不足/近似及默认风险支持显式记录，不宣称情景具有任意精确协方差。',
        '', '结构风险矩阵及252个联合历史情景冻结在各阶段截止前的收盘收益窗口，2026未滚动重估。监督风险尺度学习log绝对单期收益代理，不是已识别的条件标准差；GARCH/GJR使用冻结阶段末预测尺度，本批没有2026递推更新。结构风险与监督尺度的区别、及缺支持基线，须据收据解释，不能将所有风险改进归因于学习。',
        '',link('75流完整标签诊断','analysis/PREDICTION_DIAGNOSTICS.csv')+' · '+link('31原始对象完整标签诊断','analysis/RAW_PREDICTION_DIAGNOSTICS_INCLUSIVE_EXTREME_HINTS.csv')+' · '+link('原始rank完整标签日IC','analysis/RAW_RANK_DAILY_IC_INCLUSIVE_EXTREME_HINTS.csv')+' · '+link('保留的排提示敏感性诊断','analysis/RAW_PREDICTION_DIAGNOSTICS.csv')+' · '+link('推理风险回退与情景近似','analysis/RISK_INFERENCE_DIAGNOSTICS.csv'),
        '', '源label_price_warning仅是绝对研究指数收益超过80%的提示，不是已证坏价。冻结学习按原合同保留提示；两条2024提示进入样本，收益/接口/融合目标截断±20%，风险绝对收益代理不截断；三条2025提示未被hash80抽中。主75流诊断保留全部110438条2025合法成熟标签；此前31原始对象保守诊断排除3条提示、支持110435，另保留含提示的完整原始对象诊断供对照。没有因误差或账户结果删除训练样本或重训。',
        '',link('源极端收益提示与冻结样本审计','audits/PRE_SOURCE_EXTREME_RETURN_WARNING_AUDIT.json'),
        '',f'GARCH/GJR预训练逐票失败/基线回退共{len(fallbacks)}条，原因全部保存，不冒称成功。所有PTO求解状态汇总如下；达到容差、现金数学证书、固定预算近似及专家融合分开记录。近似不是精确最优，专家内部状态另存；决策异常采用保存单位规则并逐策略列原因。',
        '',markdown(solver.groupby(['year','status'],as_index=False).decisions.sum()),
        '', '逐策略数值质量已与同来源独立批级状态计数闭合。下表普通预测账户与同账户13专家分别计数，分母包含失败/保存单位等源调用，排除目标融合协调层。QP固定点残差与CVaR Frank–Wolfe支持gap含义不同，残差大小须在各自优化器内阅读；这些残差描述原优化调用，不能证明经轴替换/共同投影后的最终目标仍最优。容差或现金状态比例只是源状态统计，不等于全部目标的精确最优性证明。共同参考优化调用的质量未被源JSON单独保存，无法认证其数值精度，本批没有重跑补证。',
        '',markdown(quality_summary),
        '',link('逐策略数值状态、残差与支持','analysis/SOLVER_QUALITY_BY_STRATEGY.csv')+' · '+link('逐目标专家数值状态与残差','analysis/SOLVER_QUALITY_BY_TARGET_EXPERT.csv')+' · '+link('全部源状态支持','analysis/SOLVER_QUALITY_STATUS_SUPPORT.csv')+' · '+link('逐策略质量核验收据','analysis/SOLVER_QUALITY_RECEIPT.json'),
        '',link('风险拟合失败与回退','analysis/RISK_FIT_FAILURES_AND_FALLBACKS.csv')+' · '+link('策略决策失败原因','analysis/POLICY_FAILURES.csv')+' · '+link('优化数值定义','OPTIMIZATION_IMPLEMENTATION.md'),
        '', '## 暴露、现金、费用与RL',
        '', '买/卖轴使用同账户的固定Ridge+diagonal+MV参考，但无买入增量或待测保留部分超过参考时不能强行保持参考敞口；reference gross、gross gap、axis replacement与slot projection均单列。reference_gross/raw_gross/final_gross是执行前主动目标合计，排除缺输入而保留的reserved units；它们不等于成交后实际总敞口。axis_replacement_l1还包含轴处理末尾的box/budget投影，joint也可能非零，不能单独当纯轴替换效应。cash轴采用参考股票比例与待测总敞口。参考为空时不能凭空产生股票配置。现金零计息；平均现金和真实费用直接展示。按滞后敞口归一化的日指标仅为描述性代理，会剔除低敞口日且受日内换仓影响，不能当另一条可交易反事实或学习能力证明。低回撤可能来自低敞口/现金，必须一起阅读。',
        '', 'RL是独立joint路线，不接入收益预测网格。REINFORCE/PPO各唯一种子、固定四次更新与匹配零更新，各账户同池、成本、时钟和约束。所有八个账户与四个更新/零更新差分均保留。',
        '',markdown(rl[['year','policy','indicative_return','indicative_max_drawdown','mean_gross_exposure','fees']].assign(
            indicative_return=lambda d:d.indicative_return.map(lambda x:number(x,True)),
            indicative_max_drawdown=lambda d:d.indicative_max_drawdown.map(lambda x:number(x,True)),
            mean_gross_exposure=lambda d:d.mean_gross_exposure.map(lambda x:number(x,True)),fees=lambda d:d.fees.map(number))),
        '',link('RL全部结果','analysis/RL_RESULTS.csv')+' · '+link('RL更新对零更新','analysis/RL_UPDATED_VS_ZERO.csv')+' · '+link('RL账本独立核验','audits/RL_EVALUATION_VERIFICATION.json'),
        '', '## 账本、验证与未完成的正式数据条件',
        '',f'PTO共{r["actual_pto_account_days"]}个实际账户日，独立核验覆盖所有注册账户/逐笔成交/现金单位/源报价净值/费用/容量资格/目标与订单链/明确零与遗漏掩码；RL另1732账户日。批共享市场数组，策略独立推进账户。所有预测文件、目标矩阵、专家贡献、订单成交、持仓、费用净值和异常原因保存在results/2025及results/2026；零目标以完整压缩矩阵存储，不因订单稀疏而丢失。目标融合每行prediction_files关联13个真实源预测；旧单数prediction_file保留占位语义，不指向融合工件。certified_days只表示源报价及质量标记完整日数，不认证PIT、全池或股东总收益。',
        '',link('预测至净值账本读取说明','LEDGER_ARTIFACT_GUIDE.md')+' · '+link('全部账户独立验证','INDEPENDENT_VERIFICATION.json')+' · '+link('验证失败表','INDEPENDENT_VERIFICATION_FAILURES.csv')+' · '+link('持仓及现金漂移','INDEPENDENT_VERIFICATION_DRIFT.csv')+' · '+link('数据1763项验证','data/TEST_DATA_VERIFICATION.json')+' · '+link('GLW与窗口解释','audits/TEST_DATA_SCOPE_CLARIFICATION.json'),
        '',f'末次核验旧源文件{r["old_sources_verified"]}个及所有冻结工件不变。运行中的加载/类型兼容错误与独立核验器的两次语义修正都保留首失败证据；仅修复新入口/核验器，不重训、不改冻结模型/优化器或历史账本。',
        '', '首轮统计导出在pandas 3.0.2中因GroupBy对axis属性的兼容路径失败，首失败原字节已保留。新增统计入口仅在该进程中恢复整数行轴axis=0，运行原分析及交付脚本后恢复原属性；含axis列的小样与独立count/mean/median/min/max计算一致，组键与指标未变。原analyze.py、预测诊断缓存和663个冻结工件前后按SHA核验不变，四次入口收据记录0学习、优化、账户派发或筛选。该入口是统计导出兼容修复，未增加模型或候选，也未更改任何结果值。',
        '',link('统计兼容入口','run_pandas_compat.py')+' · '+link('首失败字节与来源收据','audits/PRODUCTION_HANDOFF_ANALYZE_FAILURE_20260928T2130/PRESERVATION_RECEIPT.json')+' · '+link('兼容小样与属性恢复QA','analysis/PANDAS_COMPAT_QA.json'),
        '',link('完整分析恢复收据','analysis/PANDAS_COMPAT_analyze_RECEIPT.json')+' · '+link('四轴报告恢复收据','analysis/PANDAS_COMPAT_dimension_reports_RECEIPT.json')+' · '+link('全部图表恢复收据','analysis/PANDAS_COMPAT_figures_RECEIPT.json')+' · '+link('最终报告恢复收据','analysis/PANDAS_COMPAT_build_report_RECEIPT.json'),
        '', '图表首轮实际查看发现全局标题与子图标题重叠、费用注释跨列，下一轮又发现裁边遗漏全局标题；两轮原始PNG/PDF、统计摘要和生成收据均保留。最终仅修复标题间距、完整画布导出及费用显示格式，并逐张实际检查17张PNG；费用注释为3位有效数字，k表示1000美元，未舍入统计值继续保存在CSV，配对差分和交互统计与修复前完全一致。',
        '',link('首轮视觉失败与原图字节','audits/FIGURE_VISUAL_FAILURE_INITIAL_20260928T2230/FAILURE_RECEIPT.json')+' · '+link('裁边失败与原图字节','audits/FIGURE_VISUAL_FAILURE_TIGHT_EXPORT_20260928T2242/FAILURE_RECEIPT.json')+' · '+link('17张最终实际视觉验收','analysis/FIGURE_VISUAL_QA.json'),
        '', '最终验收原先只接受简写PASS，与原基础预测收据的资格子池诊断状态不符。仅修正未冻结验收脚本，使其精确检查原诊断状态、全部31成员和62份输出、类型与键、资格计数、零更新和前后663份冻结哈希，并保留正式全池阻塞边界；原预测及收据字节未改。实际收据和11个负例验证了该门槛。',
        '',link('验收状态不匹配首失败证据','audits/COMPLETION_SCHEMA_FAILURE_BASE_20260928T2251/PRESERVATION_RECEIPT.json')+' · '+link('精确收据门槛与负例QA','analysis/COMPLETION_GATE_SCHEMA_QA.json'),
        '', '正式全池所欠的是47272个未知候选证券日的可复核资格/事件/输入证据及继承的PIT/价格会计认证；有数值特征不能补足资格。EXAS现金权益/结算仍缺证，运营退出证据不等于现金到账。没有完整池正式收益排名，也没有从诊断结果回流训练或扩候选来补救。事前清单执行完成后即停止。']
    lines+=['',link('全部不可新买候选键及具体原因','analysis/ALL_INPUT_BLOCKED_CANDIDATE_KEYS.csv')+' · '+link('按缺证原因归纳','analysis/INPUT_BLOCKERS_BY_REASON.csv')+' · '+link('按证券归纳','analysis/INPUT_BLOCKERS_BY_TICKER.csv'),
        '',link('比较与解释边界独立审查','analysis/INTERPRETATION_AND_COMPARISON_AUDIT.md')]
    figure_dir=out/'figures'
    if figure_dir.exists():
        lines+=['','## 全格图示']
        for path in sorted(figure_dir.glob('*.png')):lines+=['',f'![{path.stem}]({path.as_posix()})']
    if (out/'EFFECTS_SUMMARY.json').exists():lines+=['',link('配对差分与交互全方法摘要','analysis/EFFECTS_SUMMARY.json')]
    (ROOT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    write_json(ROOT/'DELIVERY_RECEIPT.json',{'status':r['status'],'report_sha256':sha(ROOT/'REPORT.md'),
        'all_strategy_results_rows':len(all_results),'all_strategy_results_sha256':sha(out/'ALL_STRATEGY_RESULTS.csv'),
        'layer_effect_ranges_rows':len(layer_ranges),'layer_effect_ranges_sha256':sha(out/'LAYER_EFFECT_RANGES.csv'),
        'solver_quality_summary_rows':len(quality_summary),'solver_quality_summary_sha256':sha(out/'SOLVER_QUALITY_SUMMARY.csv'),
        'registered_list_stopped':True,'formal_full_pool_status':'BLOCKED_DATA'})
    print('REPORT_READY',len(all_results),flush=True)

if __name__=='__main__':main()
