"""Assemble one acceptance report from completed, read-only work packages."""
from pathlib import Path
import json

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FOCUS = ['joint_hgb', 'ensemble_equal', 'ensemble_disagreement', 'ensemble_stacking']
LABELS = {'joint_hgb': 'HGB', 'ensemble_equal': '等权集成',
          'ensemble_disagreement': '分歧惩罚集成', 'ensemble_stacking': 'Stacking'}


def link(name, label=None):
    return f'[{label or name}]({(HERE / name).as_posix()})'


def read(name):
    return json.loads((HERE / name).read_text(encoding='utf-8'))


def main():
    integrity = read('ORIGINAL_INTEGRITY_VERIFICATION.json')
    assert not integrity['failures']
    selection = read('selection/SUMMARY.json')
    bridge = read('bridge/COMPLETE.json')
    evidence = read('evidence/FINAL_EVIDENCE_SUMMARY.json')
    independent = read('SELECTION_INDEPENDENT_VERIFICATION.json')
    assert bridge['paths'] == 38 and bridge['original_inputs_unchanged']
    assert bridge['model_fit_calls'] == selection['fit_attempts'] == 0
    assert independent['status'] == 'PASS'
    aggregate = pd.read_csv(HERE / 'selection/aggregate.csv')
    comparisons = pd.read_csv(ROOT / 'MODEL_COMPARISON.csv')
    summaries = pd.read_csv(HERE / 'bridge/POLICY_SUMMARY.csv')
    lines = [
        '# 原批次验收与冻结选股诊断', '',
        '三个限定工作包已完成。原批次模型、参数、融合权重、预测期限和回放未改；没有新增训练、种子或规格搜索。工程一致性核验通过，但完整候选宇宙、公司行动及历史可得性认证仍未达标。原模型保持原批次身份，不能称为“数据已修复的模型”，本轮结果也不是新的盲测。', '',
        '## 证据验收', '',
        '- 2025回放使用validation基础模型和仅以2024 OOF训练的元模型；元模型标签末日2024-12-31。用于2026的final元模型才使用2024+2025 OOF，标签末日2025-12-31。',
        '- 13F沿原24机构合池规则：当季最晚披露后的第5个交易日生效，继任季度生效前沿用上一期。313,668条训练上下文及62,393条2026可买记录的季度时轴均无错配。该结论不等同于静态身份表或历史价格当时可得。',
        '- 2026Q2另做逐成员版本核验：22个信号日的原完整池均沿初始575个成员键，重报生效前13日未发现重报独有成员提前进入；但2026-09-10后9日仍沿初始池。最近有效重报版本的合规性未认证，不能把“季度名称正确”扩展成“始终使用最新13F版本”。本轮没有替换候选池重算成绩。',
        '- 312,707条成熟训练标签由原冻结开盘价格逐条重建，误差为0。这只证明同源计算一致。',
        '- 训练样本选择限制已确认发生在2026年前：冻结季度成员有479,163个证券日，162,773个因冻结源缺价未入池，2,722个因不足或不连续121日历史未入池，留下313,668行。静态季度身份阶段另有124条未解析及24条已确认去重碰撞。它们不是仅影响2026的评估问题。',
        '- 13条既有大收益警告对应的后续特征依赖窗口，命中46个final监督实采证券日；85个没有供应商事件解释的Raw大波动对应窗口命中56个。两组可能重叠，不能相加。依赖被使用已经确认，错误数值或未来泄露尚未由此证实。监督抽样未选中某条异常标签，也不能推成特征未受相关价格影响。',
        '- WOLF 2025-09-29事件未进入本批股票特征/标签行；final风险窗口确实消费该日收益，按原风险规则由−84.7455%截断至−50%后进入LW/PCA。validation风险窗口止于2024年，没有直接消费该事件；更早历史修订的影响仍为UNKNOWN。',
        '- 2026候选111,868个证券日中，可买子池62,393、未知47,271、已证不合格2,204；没有一个信号日达到原始候选全池完整。97个事件资格记录中87个仍为UNKNOWN。',
        '- GLW 2026-02-26/27除息日期冲突属于这笔2026评估事件，不能自动外推为pre2026同证券训练错误。57条2026成本/路径记录当日有GLW输入，54条非现金路径实际评分；均为零目标、无该日期后的GLW持仓或交易，但横截面评分/投影对其他订单的影响仍不能排除。',
        f'- 全76条原路径中，按原账本标记和已知GLW冲突识别的持仓已按证券、日期、策略和成本列出，共{evidence["actual_position_impacts"]["uncertified_or_conflict_position_rows"]:,}个路径-持仓日，涉及{len(evidence["actual_position_impacts"]["securities"])}只证券。这些不是独立统计样本。', '',
        '详细事件、候选分类、实际训练键和具体持仓日期见 ' + link('evidence/EVIDENCE_ACCEPTANCE.md', '证据验收报告') + '；WOLF窗口见 ' + link('selection/RISK_WINDOW_REVIEW.md', '风险窗口独立核查') + '。', '',
        '## 选股本身：同池、同时点、单一期限', '',
        '固定参考状态为单票持仓0、现金95%、年龄0；统一评分为5%动作相对0动作的条件偏好。只使用原“下一开盘→再下一开盘”期限。先在完整可用候选集合排名，再标记未来标签缺失，缺价不补零、不改TOP20。此分数不是原生独立收益预测。', '',
        '两年429个信号日、19条既有方法共输出3,283,789条逐股记录，其中现金对照无评分和排名。2025有245/248日、2026有88/181日满足原价格门控下整个可用候选集合标签完整且没有已知当日输入冲突。下表只比较这些同日共同集合；它们仍是事后可观察子集，不能代表完整13F全池或整段2026。', '',
        '| 年份 / 共同日数 | 方法 | 平均Spearman IC | TOP20−其余候选（bp/期） | 简单95%等权净贡献（bp/期） |',
        '| --- | --- | ---: | ---: | ---: |',
    ]
    for year in [2025, 2026]:
        for policy in FOCUS:
            row = aggregate.loc[aggregate.year.eq(year) & aggregate.policy.eq(policy)
                                & aggregate.subset.eq('complete_common_pool')].iloc[0]
            lines.append(f'| {year} / {int(row.signal_days)} | {LABELS[policy]} | {row.mean_ic:.4f} | '
                         f'{row.mean_top20_minus_rest * 10000:+.2f} | {row.mean_period_simple_net * 10000:+.2f} |')
    lines += ['',
        '简单检验每期独立：TOP20各4.75%、现金5%，按投入本金扣20bp往返费用，即账户本金19bp；不复利、不年化、不做连续账户模拟。2026完整子集上Stacking的TOP20更强，2025却更弱，因此没有跨年份稳定优于HGB的证据。整段原账户的收益差不能唯一归因于模型排序、仓位或费用中的某一个因素。', '',
        '六输入保持不变。final Stacking只有ElasticNet、Logistic、HGB为非零系数；Ridge、Q50、MLP系数为零。等权与分歧集成继续包含全部六臂。逐证券贡献、分歧及惩罚均已保存并对上融合分数。MLP/RL经硬投影后有大量并列；例如2026完整子集MLP第20位平均有29.68只并列。固定TOP20即使分数全负也取前20，不能把排名当作原策略买入建议。', '',
        '全部方法、93个2026不完整/冲突日的独立覆盖说明见 ' + link('selection/SELECTION_READOUT.md', '排序结果解读') + ' 和 ' + link('selection/aggregate.csv', '完整汇总表') + '。', '',
        '## 从榜单到组合、再到执行', '',
        f'原2025/2026的10bp场景共38条路径、{bridge["rows"]:,}条证券日已逐一连接。实际账户状态评分与固定参考榜分列，保留原目标、现金、约束、交易、执行后持仓和价格状态。没有目标记录不算拒单；目标已满足而不交易也不算执行失败。', '',
        '2025 Q10有4,960条实际状态前20但目标为零的记录，全部是原动作没有正优势。HGB有2,344条高排零目标，原日志不足以确认具体优化器竞争原因，因此保留UNKNOWN。容量部分成交则由目标、开盘、已有单位及信号ADV重建，并与成交金额逐笔核对。', '',
        '有目标而未成交也能定位：2026-01-07，Logistic对WDC的2.5%目标被明确以LIVE_POSITION_LIMIT拒绝，同路径另9条正目标记录因PRICE_QUALITY_UNCERTIFIED未成交。这些属于已记录的执行结果，与模型主动零权重分开。', '',
        '| 2026、原10bp全窗 | 高排零目标记录 | 容量受限的实际买单 | 拒绝记录 | 已记账费用（美元） | 平均现金 | 原门控未认证估值日 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: |',
    ]
    for policy in FOCUS:
        b = summaries.loc[summaries.year.eq(2026) & summaries.policy.eq(policy)].iloc[0]
        c = comparisons.loc[comparisons.year.eq(2026) & comparisons.cost_bps.eq(10) & comparisons.policy.eq(policy)].iloc[0]
        lines.append(f'| {LABELS[policy]} | {int(b.high_rank_zero_target):,} | {int(b.capacity_limited_fills):,} | '
                     f'{int(b.rejected_rows)} | {b.recorded_cost_dollars:,.2f} | {c.mean_cash_weight:.2%} | {int(c.uncertified_valuation_days)} |')
    lines += ['',
        '表中高排名依据实际状态下的5%动作评分切片，原优化器使用完整五动作和整体预算，因此不能把零目标都称为“选对但没买”。费用是实际记账的现金支出；成本情景会改变后续持仓路径，不能把收益差或把累计费用加回净值当成精确的无成本反事实。', '',
        'HGB在原2026路径记账费用约19.92万美元，高于Stacking约10.42万美元，因此不能把Stacking较弱的原账户净回报简单解释成“它支付了更多费用”。固定参考排序、实际状态决策、仓位大小、交易可执行性及尚未认证日期都需要分别查看。', '',
        '把比较限制在完全相同的2026年88日，每法均有1,760个参考TOP20证券日：Stacking中55.80%获得实际正目标，执行后持有比例同为55.80%；HGB两者均为60.74%，等权为41.31%，分歧为30.06%。这些参考入选项的拒单数均为0，且主动目标与保留权重已分开。这说明这项“覆盖数量”差异已在参考排名到实际配置的映射中出现，不能说是拒单造成，更不能说它解释了全部收益差。容量仍可能削减已成交的仓位大小。', '',
        '这些参考TOP20平均合计获得的目标权重分别为Stacking 49.69%、HGB 67.19%、等权37.16%、分歧25.51%；这是参考20只占账户的目标资金，不是账户总仓位。原账户还可能持有参考榜以外的股票。完整同日实施表见 ' + link('bridge/REFERENCE_TOP20_IMPLEMENTATION_BY_DAY_SCOPE.csv', '排序到配置/持有的同日对照') + '。', '',
        '直接审阅 ' + link('LAST_SIGNAL_THREE_LAYER.csv', '末信号三层合并表') + '：排名/数值及六臂贡献 → 目标/现金/零权重原因 → 成交/未成交/实际持仓/价格状态。完整日期与全部路径的文件对应关系见 ' + link('READING_GUIDE.md', '字段与证据阅读说明') + '。', '',
        '## 验证与最终状态', '',
        f'- {integrity["checked_files"]:,}个原源码、模型、收据、报告、Parquet账本及指定输入文件哈希核对一致；旧RUN_MANIFEST和模型均未改。',
        '- fit守卫触发0次，未重训、重估协方差、更新融合或重跑账户。',
        '- 独立重算8,151条逐日简单持仓/价差指标、252条IC；518,493条融合贡献对账通过；同池、排序、并列、缺失标签和风险层别名检查通过。',
        '- 三层连接的唯一键、交易数、成交金额、费用、单位、现金和NAV核对通过。',
        '- 计算与追溯工作完成；数据认证仍未通过。未知供应商历史到达、静态身份与完整候选覆盖、部分公司行动及神经训练逐证券奖励归属不能由现有证据补成PASS。若未来补正训练数据，需要另立可追溯批次，不能把本批改名为已修复模型。', '',
        '验证收据：' + link('ORIGINAL_INTEGRITY_VERIFICATION.json', '原批次不变核验') + '、' + link('SELECTION_INDEPENDENT_VERIFICATION.json', '排序独立核验') + '、' + link('bridge/COMPLETE.json', '三层对账收据') + '。',
    ]
    (HERE / 'ACCEPTANCE_REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('ACCEPTANCE_REPORT.md assembled from completed work packages.')


if __name__ == '__main__':
    main()
