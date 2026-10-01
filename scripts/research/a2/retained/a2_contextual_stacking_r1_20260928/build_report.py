"""Render the final research report from frozen receipts and saved results."""
from pathlib import Path
import json
import pandas as pd

ROOT = Path(__file__).resolve().parent


def read(relative):
    return json.loads((ROOT/relative).read_text(encoding='utf-8'))


def link(relative, label=None):
    return f'[{label or relative}]({(ROOT/relative).as_posix()})'


def main():
    results = pd.read_csv(ROOT/'paired_analysis/ALL_RESULTS.csv')
    assert len(results) == 12
    assert read('paired_analysis/ANALYSIS_RECEIPT.json')['status'] == 'FROZEN_PAIRED_ANALYSIS_COMPLETE'
    assert read('INDEPENDENT_LEDGER_CHECKS.json')['status'] == 'PASS'
    assert read('independent_audit/META_CONTRACT_AUDIT.json')['status'] == 'PASS'
    assert read('OLD_SOURCE_AFTER.json')['status'] == 'PASS'
    disposition = read('RESEARCH_DISPOSITION.json')
    assert disposition['status'] == 'FROZEN_R1_NOT_ADOPTED' and not disposition['uses_2026_results']
    fit = read('meta_artifacts/FIT_RECEIPT.json')
    cash = read('cash_diagnostic/CASH_DIAGNOSTIC_RECEIPT.json')['models']
    same = read('paired_analysis/SAME_ACCOUNT_DIAGNOSTIC.json')
    concentration = read('paired_analysis/2025_CONCENTRATION_AND_LABEL_WARNING.json')
    proof = pd.DataFrame(read('paired_analysis/LEDGER_CASHFLOW_PROOF.json')['paths'])
    def row(year, cost, model):
        return results.loc[(results.year == year) & (results.cost_bps == cost) & (results.policy == model)].iloc[0]
    m0, m1 = row(2025, 10, 'M0'), row(2025, 10, 'M1')
    p0, p1 = (proof.loc[(proof.year == 2025) & (proof.cost_bps == 10) & (proof.method == method)].iloc[0]
              for method in ('M0', 'M1'))
    lines = ['# A2_CONTEXTUAL_STACKING_R1：完成报告', '',
        '**本轮已完成并冻结。条件集成M1没有通过2025主比较，按预拟合合同不晋升、不追加搜索。** '
        f'单边10bp、初始100万美元下，静态M0模拟净收益{m0.indicative_return:.2%}，条件M1为{m1.indicative_return:.2%}，'
        f'差{(m1.indicative_return-m0.indicative_return)*100:.2f}个百分点。M1平均现金{m1.mean_cash_weight:.2%}，'
        '仅少数交易参与市场且损失集中；较小回撤不构成有效现金择时证据。', '',
        '本结果属于已观察历史上的回溯研究，采用原价格指数坐标、原股票池和认证规则。2026只作冻结诊断，未参与正则选择或本轮处置。', '',
        '## 完成的联合训练', '',
        '冻结Ridge、Elastic Net、Logistic、HGB、Q10／Q50／Q90和MLP专家；新建真实可行账户OOF面板，训练静态M0与条件M1。'
        '基础专家输出→合成动作效用→共同TOP20分配器→原执行账本，联合产生选股、买入／持有／卖出与现金。'
        '本轮是监督融合训练加完整经济评价，标签沿用单股单步效用近似，未声称端到端优化全年组合收益。', '',
        'M0有21个共同主项，M1只增加48个专家×四状态交互；主项预处理共享且仅使用对应训练期。'
        '四状态为现金、当前单股仓位、原可用名额和原20日波动。8个MLP恒定交互在动作减零中抵消，最多40项直接影响分配增量；全部48项保留参与绝对效用拟合。'
        '有效系数承担异质输出刻度转换，不是资金比例或正确概率。', '',
        '2024固定early HGB行为路径提供50,000动作行／250日期；2025固定旧equal、stacked账户提供100,000动作行／248日期。'
        '每个日期总权重1，同日路径等权；150,000行不是150,000次独立市场实验。增广状态矩阵两年均满秩5，现金与单票仓位相关约−0.010、−0.057。'
        '这修复旧共线覆盖问题，但边际范围内不证明联合状态样本充足。原三状态网格外推限制指冻结监督价值专家，MLP保留其自身训练支持限制。', '',
        '内部按2024-10-01切分，186训练日／62验证日并清除2个未成熟标签日；只比较预定交互惩罚倍率4、16、64，选中16。'
        '主项惩罚100，交互惩罚1600；该日期加权尺度与旧未加权90,000行alpha100不同。'
        '实际完成8次生产元拟合，基础专家拟合0次、2026拟合行0。', '',
        '| 元层阶段 | OOF专家与训练日期 | 元层/预处理标签成熟末日 | 使用阶段 |',
        '|---|---|---|---|',
        '| validation M0/M1 | early输出，2024的250日期 | 2024-12-31 | 2025冻结验证，专家为validation |',
        '| final M0/M1 | early 2024＋validation 2025，共498日期 | 2025-12-31 | 2026只推理，专家为final |', '',
        '## 2025预测与完整经济评价', '',
        '| 日期／路径等权，未裁剪标签 | M0 | M1 | M1相对变化 |',
        '|---|---:|---:|---:|']
    metrics = fit['validation_panel_prediction']['metrics']
    for output, title in [('absolute_utility','绝对动作效用'), ('action_minus_zero_utility','动作减零效用')]:
        a = next(r for r in metrics if r['kind']=='M0' and r['target']=='target_unclipped' and r['output']==output)
        b = next(r for r in metrics if r['kind']=='M1' and r['target']=='target_unclipped' and r['output']==output)
        lines.append(f'| {title}MSE | {a["date_equal_mse"]:.8g} | {b["date_equal_mse"]:.8g} | {(b["date_equal_mse"]/a["date_equal_mse"]-1)*100:+.4f}% |')
        lines.append(f'| {title}MAE | {a["date_equal_mae"]:.8g} | {b["date_equal_mae"]:.8g} | {(b["date_equal_mae"]/a["date_equal_mae"]-1)*100:+.4f}% |')
    lines += ['', 'M1绝对MAE改善221/248日，但动作减零MSE仅改善110/248日且总体更差；日误差差分的描述性HAC区间均跨零。'
        '绝对校准改善未证明动作信息改善。新增交互确有实际作用：动作减零交互RMS约1.2942e−4，M1−M0总变化RMS约1.2591e−4。'
        'Ridge／Elastic可比效用输出相关0.9922，其合计动作贡献RMS从5.7084e−5降至5.1209e−5。具体日期、股票、有效系数范围和联合贡献见'+link('meta_artifacts/INTERPRETATION_SUPPLEMENT.md','预测解释')+'。', '',
        '| 2025主成本10bp | M0 | M1 |', '|---|---:|---:|',
        f'| 模拟净收益 | {m0.indicative_return:.2%} | {m1.indicative_return:.2%} |',
        f'| 最大回撤 | {m0.indicative_max_drawdown:.2%} | {m1.indicative_max_drawdown:.2%} |',
        f'| 年化日收益波动 | {m0.indicative_annualized_volatility:.2%} | {m1.indicative_annualized_volatility:.2%} |',
        f'| 平均收盘现金 | {m0.mean_cash_weight:.2%} | {m1.mean_cash_weight:.2%} |',
        f'| 实际模拟费用（美元） | {m0.total_cost_dollars:,.2f} | {m1.total_cost_dollars:,.2f} |',
        f'| 账本累计换手 | {m0.turnover:.3f} | {m1.turnover:.3f} |', '',
        f'M1−M0净损益为{p1.net_stock_pnl-p0.net_stock_pnl:,.2f}美元，可精确分解为价格损益差{p1.gross_price_pnl-p0.gross_price_pnl:,.2f}美元减去费用差{p1.fees-p0.fees:,.2f}美元。'
        '费用节省抵回部分价格损失，整体仍显著退化。价格损益来自实际执行路径的期末市值＋卖出额−买入额，不是另跑零费用策略的收益。', '',
        '## 现金在哪一步形成，以及亏损来自哪里', '',
        '| 主2025路径的阶段事实 | M0 | M1 |', '|---|---:|---:|',
        f'| 有可行正增量候选的信号日 | {cash["M0"]["signals"]-cash["M0"]["dates_no_positive_feasible_gain"]}/248 | {cash["M1"]["signals"]-cash["M1"]["dates_no_positive_feasible_gain"]}/248 |',
        f'| 零股票目标信号日 | {cash["M0"]["dates_zero_target"]} | {cash["M1"]["dates_zero_target"]} |',
        f'| 分配后平均目标现金（248信号日） | {cash["M0"]["target_cash_date_mean"]:.2%} | {cash["M1"]["target_cash_date_mean"]:.2%} |',
        f'| 实际平均收盘现金（250估值日） | {cash["M0"]["closing_actual_cash_date_mean"]:.2%} | {cash["M1"]["closing_actual_cash_date_mean"]:.2%} |',
        f'| 最大目标股票数量 | {cash["M0"]["max_selected_names"]} | {cash["M1"]["max_selected_names"]} |', '',
        'M1在235天没有可行正动作增量，同时235天配置零股票目标；用>0或>1e−12定义正增量的计数完全相同。全部248天可用名额20、保留资本0；非零目标最多一只股票、最大目标股票仓位10%。'
        '因此近乎全现金主要由条件动作评分和共同分配器形成。其少数成交后的估值漂移、容量及费用进一步影响实际现金；不同日期口径的均值差不能直接当作执行现金的因果分解。'
        '实际收盘最高单票权重11.36%来自价格漂移，不能当成目标上限违规。', '',
        'M1仅交易INBX、PLTR、BYND、MU四只股票，共13轮BUY／EXIT、26笔成交。BYND在10月22日到11月17日间的9轮贡献净损失114,843.71美元，约占全路径净损失99.11%；'
        '前两轮分别净损失52,310.13及37,725.52美元。全年只有13个估值日持有股票，低年度平均敞口掩盖了稀少但高度集中的交易风险。'
        '逐轮账本价格、金额和费用见'+link('cash_diagnostic/M1_roundtrips.csv','M1逐轮账本')+'，阶段分解见'+link('cash_diagnostic/CASH_DIAGNOSTIC_RECEIPT.json','现金分解收据')+'。', '',
        '9个BYND非零目标的事前realized_vol_20d约0.4414–0.4664，全部超过validation训练最大0.30611，且全部配置10%目标；其余4个INBX／PLTR／MU目标为2.5%，状态在训练边际范围内。'
        '因此13个非零目标中9个（69.23%）落在元层状态范围外。全部候选动作的越界率很小，也不能推出实际下注安全；需要同时查看选中目标的支持范围。'
        '这个尾部外推集中性仅作已保存路径诊断，未按结果截尾、删股或重跑。详见'+link('paired_analysis/2025_SELECTED_STATE_SUPPORT.json','选中目标状态支持收据')+'。', '',
        f'在相同M0实际账户状态上，冻结M1的事后平均目标现金为{same["date_equal_M1_target_cash"]:.2%}，M0为{same["date_equal_M0_target_cash"]:.2%}；'
        f'目标集合日均Jaccard为{same["date_equal_mean_jaccard"]:.4f}，日均目标L1差为{same["date_equal_mean_target_l1"]:.4f}，反向交易动作{same["opposite_directions"]}次。'
        'M1自身接近全现金的完整账户路径与这些共同状态目标差异很大，显示条件决策对账户状态及路径敏感。'
        '这些M1假设目标未进入M0账本，不能当作另一条M1全年收益，也不能仅凭边际状态范围声称联合适用性充分。', '',
        '## 固定成本敏感性与原结果参照', '',
        '| 2025单边成本 | M0净收益 | M1净收益 | M1−M0，百分点 | M0费用美元 | M1费用美元 |',
        '|---|---:|---:|---:|---:|---:|']
    for cost in (5,10,25):
        a,b = row(2025,cost,'M0'),row(2025,cost,'M1')
        lines.append(f'| {cost}bp | {a.indicative_return:.2%} | {b.indicative_return:.2%} | {(b.indicative_return-a.indicative_return)*100:+.2f} | {a.total_cost_dollars:,.2f} | {b.total_cost_dollars:,.2f} |')
    lines += ['', '25bp时M1小幅领先M0，但两者均亏损；M1几乎全现金并大幅少交易，费用节省是重要来源。'
        '主10bp及5bp明显退化，不能改用高成本场景晋升。M0本身换手高、成本敏感，未超过旧堆叠／HGB／MLP的既有2025主净收益，也不晋升。', '',
        '| 直接复用的旧2025／10bp整体参照 | 净收益 | 最大回撤 | 平均现金 |', '|---|---:|---:|---:|']
    references=pd.read_csv(ROOT/'paired_analysis/PRIOR_FROZEN_REFERENCES.csv')
    for name,label in [('ensemble_equal_weight','旧六模型等权'),('ensemble_stacked','旧堆叠'),('joint_hgb','旧HGB'),('joint_mlp','旧MLP')]:
        r=references.loc[(references.year==2025)&(references.cost_bps==10)&(references.policy==name)].iloc[0]
        lines.append(f'| {label} | {r.indicative_return:.2%} | {r.indicative_max_drawdown:.2%} | {r.mean_cash_weight:.2%} |')
    lines += ['', '旧工件直接复用、没有重训或重跑。它们与新元层存在面板、收缩尺度或融合位置差别，属于整体参照；主比较仍是同规格M1对M0，用于评价增加状态交互的影响。', '',
        '## 2026冻结诊断与数据限定', '',
        '| 2026单边成本 | M0诊断净值变化 | M1诊断净值变化 | M0平均现金 | M1平均现金 | M0／M1未认证估值日 |',
        '|---|---:|---:|---:|---:|---:|']
    for cost in (5,10,25):
        a,b=row(2026,cost,'M0'),row(2026,cost,'M1')
        lines.append(f'| {cost}bp | {a.indicative_return:.2%} | {b.indicative_return:.2%} | {a.mean_cash_weight:.2%} | {b.mean_cash_weight:.2%} | {int(a.uncertified_valuation_days)}／{int(b.uncertified_valuation_days)} |')
    lines += ['', '2026使用按合同以2024＋2025合法OOF拟合的final元层，参数与2025的validation元层不同；现金输出变化沿这两个明确阶段解释，不能用final回填2025。'
        '2026沿用原GLW事件隔离后的冻结子池和价格，信号截至2026-09-22、估值截至2026-09-24。'
        '这些是原坐标的诊断净值，保留原覆盖和价格认证缺口；即使某条账户路径无未认证估值日，也不恢复全池或全新盲测身份。'
        '本轮处置在2025主结果后锁定，2026不参与选择、校准或救回失败模型。', '',
        '原2025源含3个价格警告事件；新OOF面板采到3个路径key，对应BYND的2个股票日期。约0.0151%的日期加权样本贡献16.51%的M0原始平方误差。'
        '警告样本局部改善不足抵消其他样本恶化，未静默删除、改价或据此重选。M1交易信号key与原警告key精确匹配为0，但首次BYND买入执行日10月22日与10月20日警告标签终点重合，不能写成价格日期毫无交集。'
        '该原始警告只有bool，未建立实际成交错误证据，也不能证明价格正确。', '',
        f'按保存账本作事后区间交叉，3个警告事件窗口股票的M1−M0净损益合计{concentration["inherited_warning_event_stockday_net_delta"]:,.2f}美元，'
        f'相关股票全年差额{concentration["inherited_warning_whole_stock_year_net_delta"]:,.2f}美元。'
        '这些是受原价格源限制的会计分解，不是价格错误的因果归因。', '',
        '## 证据链与可用交付', '',
        '拟合前合同、选定倍率、成熟标签、训练期标准化器、恢复模型和12次实际运行时加载已绑定核验。'
        '独立审计从实物重算标准化矩和目标一阶条件；15项元层测试及8项桥接／日志测试通过，包含未来标签、阶段冒用、标准化器不一致和哈希篡改拒绝。'
        '12条账本的现金、净值、逐股损益、实际费用、下一开盘、1%信号ADV、TOP20及目标上限检查通过，回放拟合尝试0。'
        '旧批次与旧审查1038个实质文件、冻结输入及合同前后哈希一致。', '',
        '| 工件 | 阶段 | 训练标签最晚日 | 模型SHA256前16位 | 主标准化器前16位 | 交互标准化器前16位 |',
        '|---|---|---|---|---|---|']
    for stage in ('validation','final'):
        for method in ('M0','M1'):
            r=next(r for r in fit['fits'] if r['stage']==stage and r['kind']==method)
            lines.append(f'| {stage}_{method}.joblib | {stage} | {r["train_label_end_max"]} | {r["artifact_sha256"][:16]} | {r["main_scaler_sha256"][:16]} | {r["interaction_scaler_sha256"][:16]} |')
    lines += ['', '上表仅为阅读简写；完整哈希和每个实际回放加载对应关系见'+link('meta_artifacts/FIT_RECEIPT.json','拟合收据')+'、'
        +link('independent_audit/META_CONTRACT_AUDIT.md','独立阶段绑定审计')+'及各路径RUNTIME_LOAD_RECEIPT.json。', '',
        '回放经历两次实现层中断：源码文件清单收集在任何信号前失败；随后日志整数／浮点schema导致35信号日后中断。'
        '修复只处理清单和序列化，失败产物保留；77,485动作行及15,076同账户诊断行的重放前缀预测和目标全部差0，未重新拟合。证据见'
        +link('evaluation_2025/cost_10/RECOVERY_PREFIX_PROOF.json','恢复前缀核验')+'。', '',
        '- '+link('METHOD_AND_ARTIFACTS.md','方法、完整工件目录与语义说明'),
        '- '+link('paired_analysis/ECONOMIC_ANALYSIS.md','12条路径的完整经济分解'),
        '- '+link('paired_analysis/ALL_RESULTS.csv','12条固定回放结果CSV'),
        '- '+link('delivery_tables/README.md','逐日净值／现金、有效系数范围、完整成交和期末持仓CSV'),
        '- '+link('INDEPENDENT_LEDGER_CHECKS.json','12账本独立核算'),
        '- '+link('RESEARCH_DISPOSITION.json','只由2025结果锁定的处置'),
        '- '+link('COMPLETION.json','完成状态、运行绑定和总工件哈希清单'), '',
        '各路径action_diagnostics.parquet保留逐股票逐动作有效系数、贡献和效用；target_decisions／positions／trades／daily保留完整目标、实际仓位和账本。'
        '查看表不会以最后一次有持仓日期替代最后估值日；M1若期末全现金，其期末持仓表为空表。', '',
        f'![冻结10bp的净值与现金路径]({(ROOT/"paired_analysis/paired_paths.png").as_posix()})', '',
        '**处置保持FROZEN_R1_NOT_ADOPTED：保留本轮全部模型和证据，M1不作为策略升级，M0也不晋升；本任务完成，不扩搜。**', '']
    (ROOT/'REPORT.md').write_text('\n'.join(lines), encoding='utf-8')
    print('REPORT.md written from 12 complete frozen paths')


if __name__ == '__main__': main()
