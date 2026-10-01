"""Assemble the economic interpretation of existing results, without rerunning them."""
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent


def link(label, name):
    return f"[{label}](<{(HERE / name).as_posix()}>)"


def main():
    v = pd.read_csv(HERE / "VALIDATION_2025_METRICS.csv")
    m = pd.read_csv(HERE / "MECHANISMS_2026.csv")
    w = pd.read_csv(HERE / "OBSERVED_2026_WINDOWS.csv")
    q = pd.read_csv(HERE / "FULL_2025_QUARTERS.csv")
    assert len(v) == 12 and len(m) == 14 and len(w) == 42 and len(q) == 48
    assert v.certified_days.eq(250).all() and v.nav_dates.eq(250).all()
    validation_rows = [f"| {r.policy} | {r.net_book_return_pct:.2f}% | {r.max_drawdown_pct:.2f}% | {r.annualized_vol_pct:.2f}% | {r.avg_stock_weight_pct:.2f}% | {r.transaction_cost_pct_initial:.2f}% | {r.delta_return_vs_hgb_pp:+.2f} |" for r in v.itertuples()]
    focus = ["joint_rl_ensemble", "joint_rl_zero_control", "joint_mlp", "hgb_return_baseline"]
    mechanisms = []
    for name in focus:
        r = m.set_index("policy").loc[name]
        mechanisms.append(f"| {name} | {int(r.model_active_exit_orders)} / {int(r.model_active_exit_actual_flatten_orders)} | {r.no_decision_names_mean_all_signal_days:.2f} | {int(r.no_decision_names_held_at_account_end)} | {r.no_decision_capital_fraction_at_account_end*100:.2f}% | {int(r.execution_rejected_orders)} | {int(r.certified_close_days)} / 183 |")
    risk = w.loc[w.cost_bps.eq(10) & w.policy.isin(["joint_hgb", "joint_hgb_lw", "joint_hgb_pca"])]
    assert risk.full_window_index_nav_certified.all()
    risk_rows = [f"| {r.policy} | {r.complete_window_net_index_return*100:.2f}% | {r.complete_window_max_drawdown*100:.2f}% | {r.average_book_gross_exposure*100:.2f}% | {r.relative_to_same_cost_joint_hgb_return_pp:+.2f} |" for r in risk.itertuples()]
    quarter_rows = [f"| {r.quarter} | {r.net_index_return*100:.2f}% | {r.minus_rl_zero_pp:+.2f} |" for r in q.loc[q.policy.eq("joint_rl_ensemble")].itertuples()]
    text = f"""本轮只消费 `qualification_holdings_v1` 已保存结果，未新增拟合、预测、参数、种子或账户回放。技术修复按已完成关闭；87个未知事件不重新打开默认清仓、单位保留、名额或原始目标留痕问题，30／27日抽样器也没有再次复现。

**现有经济证据是：2025年RL相对匹配零更新对照有一次正向增益观察，但当前联合策略没有在该年的净账面回报上超过收益基准。2026年能确认动作和约束的差异，尚不能用未核证账户的期末账面值确认学习增益。**

2025比较使用同一个完整窗口：2025-01-02—12-31，250个账户估值日、249个相邻收盘收益；12策略的3,000个账户日均为已核证估值，开收盘均无陈旧或未知标记。共同初始资金100万、单边10bp、既有仓位及执行规则均保持不变。已存阶段收据显示：2025验证所用拟合及标签截至2024年底，2026所用最终拟合及标签截至2025年底，没有2026拟合行。这里的已核证是**价格指数坐标的账户NAV**，不是原始股数、股息结算或股东总收益认证，也不是完整13F股票池声明。

| 2025策略 | 净账面回报 | 最大回撤 | 年化波动 | 平均股票敞口 | 累计费用/初始资金 | 相对收益基准，百分点 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(validation_rows)}

费用已在净回报中扣除；费用/初始资金只描述现金支出，不能再扣一次，也不能直接加回当作无费用策略回报。最大回撤为收盘回撤；年化波动为全部249个日收益的样本标准差乘√252。完整数值、换手及来源见{link('2025指标', 'VALIDATION_2025_METRICS.csv')}与{link('计算口径', 'VALIDATION_2025_NOTES.md')}。

RL为 **7.33%**，匹配零更新为 **4.69%**，差 **+2.65个百分点**；最大回撤由22.05%降为20.15%，改善1.91个百分点；年化波动由21.48%降至17.40%。RL平均现金61.34%，零更新58.65%；累计费用分别49,079.40和52,416.48，单边累计换手24.61倍和26.58倍。因此，正向观察同时伴随更低敞口、更低换手与费用，不能全部归为选股预测能力。

这是一条双种子集成策略与其对应初始参数的配对比较。两组使用相同阶段、种子20260927／20260928、标准化、网络、投影和执行规则；不是两个独立验证样本，也没有估计统计显著性或跨种子稳健性。按四个固定日历季度完整分区，RL两季领先、两季落后；没有丢弃任何一天：

| 固定季度 | RL季度净账面回报 | 相对零更新，百分点 |
| --- | ---: | ---: |
{chr(10).join(quarter_rows)}

季度差不能相加代替全年复合差。全12策略的固定季度明细见{link('完整季度分区', 'FULL_2025_QUARTERS.csv')}。

![2025保存的完整账户路径及RL相对零更新差值]({(HERE / 'VALIDATION_2025_TRAJECTORIES.png').as_posix()})

收益基准回报63.36%，但其平均股票敞口92.12%、最大回撤32.43%，与RL的38.66%敞口并非同风险预算。当前证据既没有证明联合方案的回报优势，也没有运行风险匹配后基准，不能仅凭低波动声称风险调整后胜出。Q90在联合策略中的本年回报最高，为54.97%，仍低于基准8.39个百分点，回撤42.58%、波动54.18%反而更高；这是描述结果，不据此挑选下一模型。

联合HGB净回报2.40%，单边换手140.44倍、费用24.52%初始资金；收益基准对应42.73倍、9.76%。MLP净回报−4.58%，换手80.52倍、费用15.28%。高换手与费用是已经观察到的经济负担，不是旧技术问题重开，也不能把费用差直接解释为全部收益差。Q10全年零交易、全部现金，零回撤不能当作预测能力证据。

**比较设计有两项必要限制。** MLP虽保存了单种子初始权重，却没有已经完成回放的匹配MLP-zero账户；现有两种子RL-zero不能替代，因此本轮不能量化MLP自身训练更新的增益。HGB收益基准确实使用2025样本外OOF分数，但历史从2020年开始，联合监督模型从2023年开始，训练预算、标签和仓位构造也不同。这支持当前整套方案的经济比较，不支持把差值全归于“联合学习”或神经／树算法本身。详见{link('对照与阶段设计', 'COMPARISON_DESIGN_NOTES.md')}。

**2026年可以分清主动模型动作、无决策保留、操作性退出要求和执行拒绝，但不能精确分摊收益差额。** 下表沿用主场景10bp、原完整183个账户日和181个信号日。“主动退出”只计实际已有持仓的显式零目标；“无决策”不代表看多持有。期末为9月24日，平均名额按全部181个信号日计算：

| 策略 | 显式退出目标 / 回放成交退出 | 无决策平均名额 | 期末无决策保留名额 | 期末保留账面占比 | 拒单 | 已核证收盘日 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(mechanisms)}

第一，主动动作确有差异。RL发生1,048次从空仓建仓、1,028次成交退出；零更新为624次、604次。这里是建仓事件，可含同一证券多次重新建仓，不是去重股票数。MLP仅69次主动退出，其余大量交易为已有仓位增减。原始模型目标、约束后目标与实际成交分别保存；显式目标与实际成交不能混为一个数字。

第二，无决策保留改变可分配资本与名额。MLP在167／181个信号日有此类保留，RL为165／181，零更新及收益基准均为145／181；MLP期末13个保留名称、约51.60%的账面占比，不能被描述成模型主动选择长期持有。表内资本比例含陈旧估值，只是账面占用；名额和单位记录可以辨认，不能据账面比例推断可兑现资金或未知期间回报。无决策保留本身也不必然造成坏估值：联合HGB有保留仓位，但183日均有合格估值。

第三，操作性退出要求独立于模型选择。所有策略收到127条EXAS运营通知，只有RL当时持有该证券；该仓位跨127日持续保留，运营退出成交为0。期末EXAS另占1个名额，陈旧账面值20,295.84、占指示性NAV约2.00%，不包含在表中10个无决策名额内。其余账户没有EXAS持仓，通知不能记作实际退出。

第四，执行拒绝决定目标是否兑现。RL的146条拒单中，127条对应上述EXAS已知卖出限制；另外19条是15条价格未核证、1条缺价格行、3条实际名额上限。零更新、MLP、收益基准分别有6、15、5条拒单。RL与零更新在本年实际费用分别44,262.68、31,203.86；2025年的费用优势没有原样延续。启用ADV检查不等于容量实际约束生效；仅到达已存1%ADV边界的成交也不能冒充拒单。

这些记录说明动作、保留和限制如何共同形成路径。没有去除限制、强制退出、统一敞口或改用完整价格的反事实回放，不能声称“2026收益差中多少个百分点由模型、多少由缺证保留或拒单贡献”。全14策略机制与原因细分见{link('2026机制表', 'MECHANISMS_2026.csv')}和{link('机制说明', 'MECHANISMS_2026_NOTES.md')}。

**2026年经济比较的可用范围。** 本批窗口为2026-01-02—09-24，并非2026全年。42个原场景全部保留，其中15个场景（5类策略×3档成本）拥有原完整183日的合格指数NAV，27个场景仍有未核证日。RL、零更新、MLP、收益基准分别有167、141、169、145个未核证日，因此它们的期末indicative值不能确认全窗增益，也不构成2025学习收益的独立复现。未另算各自或共同“正常日期”收益、未比较事后缩短前缀、未删除后来未知的股票。

HGB与两种风险变体共享同一冻结动作价值模型，且均有完整窗口资格，可描述风险层的有限取舍。10bp结果如下：

| 2026完整窗口策略 | 净指数账面回报 | 最大回撤 | 平均股票敞口 | 相对joint HGB回报，百分点 |
| --- | ---: | ---: | ---: | ---: |
{chr(10).join(risk_rows)}

5bp与25bp下也都是两个风险变体回撤略浅、净回报更低；这些共用模型和行情的成本压力场景不是独立测试样本，不据此调整风险系数或选择成本假设。另两类完整资格策略Q10与quantile-risk的平均股票敞口仅约0.477%和0.123%，接近现金的表现不能直接证明选股更强。完整42场景、同一窗口资格及费用见{link('原完整2026窗口表', 'OBSERVED_2026_WINDOWS.csv')}；未核证账户的可比较回报、回撤、波动列留空，原indicative值另列且明确不认证。

**工作边界。** 技术修复保持关闭，剩余事件和身份补证归共享数据工作，本轮没有继续误发的续接队列。监督抽样覆盖不足与训练未含ADV容量约束均作为已有设计限制保留，不自动触发下一轮全方法训练。未来若确需改变抽样、训练容量或控制组设计，应合并为一次明确设计并事先冻结；2026已经被多次观察，不再因更换名字、筛股票或改日期变回未触碰测试集。当前结论先用于认识已有证据，不启动新参数、种子、训练或54组重跑。
"""
    (HERE / "ECONOMIC_EVIDENCE_REPORT.md").write_text(text, encoding="utf-8")
    print("Saved economic_review/ECONOMIC_EVIDENCE_REPORT.md")


if __name__ == "__main__":
    main()
