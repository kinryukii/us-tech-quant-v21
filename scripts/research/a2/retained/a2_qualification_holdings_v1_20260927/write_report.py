"""Write the delivery summary from completed, independently checked receipts."""
from pathlib import Path
import json
import pandas as pd

ROOT = Path(__file__).resolve().parent


def read(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def link(label, name):
    return f"[{label}](<{(ROOT / name).as_posix()}>)"


def main():
    audit = read("audit/VERIFICATION.json")
    assert audit["status"] == "PASS", "Full independent replay audit is required"
    data = read("data/DATA_RECEIPT.json")
    assert read("data/DATA_VALIDATION.json")["status"] == "PASS"
    comp = pd.read_csv(ROOT / "ALL_VERSIONED_SCENARIOS.csv")
    assert len(comp) == 54
    mapped = pd.read_csv(ROOT / "LEGACY54_QUALIFICATION_MAPPING.csv")
    assert len(mapped) == 54 and mapped.ticker.nunique() == 45
    states = pd.read_csv(ROOT / "DECISION_STATE_COUNTS.csv")
    principal = comp.loc[comp.year.eq(2026) & comp.cost_bps.eq(10)].merge(states, on="policy", validate="one_to_one")
    state_rows = []
    for r in principal.itertuples():
        state_rows.append(f"| {r.policy} | {r.max_actual_names} | {r.model_active_exit} | {r.model_no_decision} | {r.operational_exit_required} | {r.execution_rejected} | {r.uncertified_days} |")
    outcomes = mapped.qualification_outcome.value_counts()
    restored = int(outcomes.get("INPUT_AND_EXECUTION_PRICE_QUALIFIED", 0))
    pending_ops = int(outcomes.get("OPERATIONAL_EXIT_REQUIRED_SETTLEMENT_UNKNOWN", 0))
    unresolved = int(outcomes.get("MODEL_NO_DECISION_QUALIFICATION_REMAINS_UNKNOWN", 0))
    text = f"""本次数据资格修复、旧仓语义修复、受影响模型重训及版本回放已完成。新版本为 `qualification_holdings_v1`；旧批 `a2_latest_effective_joint_20260927` 保持冻结。结果适用于当前已核证子池，原全池仍不完整。

本次以原54条旧仓所涉及的45只证券为入口，按证券身份和事件去重核证，再映射账户。97个唯一事件中，10个已核证、87个仍未知；一个事件通过不代表该证券后续全部事件通过。身份与生命周期另行核对，事件、身份、原始行情、价格坐标及当时股票池条件必须同时成立。没有新增行情下载，也没有改动价格数值。

| 数据变化 | 数量与含义 |
| --- | --- |
| 恢复当期候选 | 491条，原阻断原因是现已核证的事件证据 |
| 已有持仓专用输入 | 83条，只对实际持有账户开放，不得新买或增持 |
| 明确降为未知 | APD 61条，原公开时间证据不足 |
| 新版本输入 | 62,476条＝62,393条当期候选＋83条已有持仓专用输入 |
| 价格资格变化 | 519条恢复、302条保守降级；全部211,482条价格的数值不变 |
| 原全池候选 | 111,868条：62,393条合格、47,271条未知、2,204条已证不合格 |

302条价格降级中，241条早于该证券已有合格账户身份依据，61条属于APD。不能将较晚发现的身份依据倒灌至更早交易日。数据逐行变化、来源哈希和检查见{link('数据收据', 'data/DATA_RECEIPT.json')}、{link('验证结果', 'data/DATA_VALIDATION.json')}及{link('数据冻结清单', 'data/DATA_FREEZE.json')}。{link('事件核证结果', 'evidence/events/event_qualification.csv')}保留每个UNKNOWN及原因。

原54条记录映射到共享资格后，**{restored}条恢复输入与执行价格资格**（BYND 4条、CRWD 2条、SLMT 3条），**{unresolved}条仍为缺输入／资格未知**，**{pending_ops}条为EXAS操作性退出要求、结算未知**。这是一组旧案例的资格映射，不代表新策略账户仍持有同一批股票，也不代表已成交。详见{link('54条逐笔映射', 'LEGACY54_QUALIFICATION_MAPPING.csv')}。

EXAS的已公开生命周期证据有独立时间戳，操作性退出与模型输出分开；没有确定结算到账日，不给账户虚构现金。DTP只保留已核证为233331107普通股、实际使用US.DTE行情的既有区间，不把US.DTP另一证券当作同一股票；9月23日至24日缺少相应原始行情，仍不能成交。BYND、SLMT按同一证券类别的明确CUSIP衔接处理，不能跨类别合并。见{link('身份与生命周期报告', 'evidence/identity/REPORT.md')}。

**旧仓决策与执行现在是分开的状态。**

| 状态 | 触发与账户处理 |
| --- | --- |
| 模型主动退出 | 模型有合法输入且显式输出零；提交退出目标，成交另验 |
| 模型没有给出决策 | 缺输入、信号时点已知限制，或输出遗漏；保留原单位，占用资本和名额 |
| 操作性退出要求 | 使用单独来源及已知时点；即使模型无输入也能记录，不能假装已卖出 |
| 执行被拒绝 | 下一开盘才发现的缺价、未核证价格或实际名额不足；不成交，不回写前一日决策 |

所有已有仓位始终进入账户约束。信号日先预留受限旧仓资本和名额，再在剩余容量中联合决定选股与目标仓位；最大20个实际名称，允许少于20个。模型对实际考虑的输入保留显式零，缺行不再自动变为退出。下一交易日先卖后买，卖单失败留下的仓位继续占位，新买按实际现金和名额检查。原始评分、模型目标、约束后目标、操作依据、订单与结果用同一决策／订单标识关联。

原批54条旧仓在9月22日至24日单位均未改变，原账户估值均未获认证；旧账面金额不能称为可兑现资金。名额限制涉及49条策略×证券订单，来自7个策略账户、同一信号日，包含41只去重股票。各账户占用名额、账面金额、权重及新资格恢复数见{link('旧仓资本汇总', 'audit/LEGACY54_CAPITAL_SUMMARY.csv')}和{link('口径说明', 'audit/LEGACY54_CAPITAL_NOTES.md')}。这些数字直接复用原收据。

**训练影响已按模型区分，并未当成报表修补。**

| 模型部分 | 本次处理 |
| --- | --- |
| MLP、RL | 历史持仓转移、状态及奖励发生变化，validation/final合计6个模型重新初始化训练，7,820次实际参数更新 |
| Ridge、Elastic Net、Logistic、HGB、q10/q50/q90 | 训练样本、反事实状态动作网格及一步奖励未改，复用14个阶段模型；剩余容量分配属于新的执行策略版本 |
| PCA、协方差收缩、辅助模型 | 继续使用冻结参数，不使用2026重估 |

validation阶段训练只用2023—2024，final阶段只用2023—2025。标准化、标签和奖励消费最晚均为2025年12月31日，2026训练行数为0。MLP固定6轮，RL两个固定种子各4轮，不按2026成绩改参数或挑种子。原30／27个训练抽样日、final的27／36个月覆盖继续保留；覆盖不足仍是后续单独版本的设计事项，本次没有替换。详见{link('训练与复用独立核查', 'audit/TRAINING_REUSE_REVIEW.md')}和{link('模型复用清单', 'MODEL_REUSE.json')}。

已完成**54组回放**：2025年12策略×10bp；2026年14策略×5／10／25bp。2026信号覆盖1月2日至9月22日，执行／估值延伸至9月24日。回放拟合尝试为0，运行前后源码及输入哈希不变。独立检查器不导入执行引擎，只读取现有成交、持仓、目标和现金收据核对恒等式；覆盖3,991,134条目标和151,499笔成交，全部54组通过。引擎22项、神经训练边界4项、适配器3项定向测试通过，事件及数据时间边界检查通过。旧冻结批72个源工件哈希仍匹配。

下面是2026主成本10bp的实际状态次数。前三种决策只统计当时有持仓的记录；同一股票连续多日可重复出现，不能当作去重股票数。拒绝列是执行记录数。未核证日是账户级估值限制。

| 策略 | 最多实际名称 | 主动退出 | 没有决策 | 操作性退出要求 | 执行拒绝 | 未核证估值日 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(state_rows)}

本版本各场景`comparison.csv`的`operational_exits`包含对未持有EXAS的操作通知；上表和{link('状态计数', 'DECISION_STATE_COUNTS.csv')}已明确限制为实际旧仓，不能用通知条数声称退出了相同数量的持仓。完整场景数字保留在{link('54组结果', 'ALL_VERSIONED_SCENARIOS.csv')}；该表的`indicative_return`是带估值限制的价格指数账面回报，不是认证股东总收益，不据此宣布优胜策略。最后信号的原目标、适配目标和执行结果见{link('最后信号决策', 'LAST_SIGNAL_DECISIONS.csv')}。独立验证见{link('全部回放验证', 'audit/VERIFICATION.json')}。

独立核验确认39,987条保留单位订单完整保留，447次卖单拒绝未丢失单位，21次新买被实际持仓上限阻止。逐笔重算的持仓数始终不超过20；现金最大重建误差1.17e-8、NAV误差4.66e-10，费用与成交价误差为0。这些是浮点核对误差。54组中仍有27个策略成本案例出现未核证估值，合计3,678个账户会话日；这些日子的certified NAV保持为空，不能把核验PASS解释为净值已获认证。

仍未解决的边界明确保留：87个事件未知、47,271条原候选未知；历史供应商实际到达时间未获证明；现金分红及拆并股使用可核对的价格指数坐标，并未完成原始股数与股东总收益结算。训练没有ADV容量约束，而严格执行使用信号时点ADV代理。锁定单位的权重可随行情漂移，不能把目标权重上限等同于任何时点实际权重都不漂移。2026已被观察且资格修复由旧案例触发，本结果是有版本的诊断回放，不重新包装成原始盲测。

“108天禁买”旧问题按既有报告关闭；最新已公开且生效的13F股票池规则保持不变。以上未知项不会通过重复下载、补零、隐含清仓或虚构现金消失。该版本可以复用证券／事件证据及冻结模型继续补证重放；以后若再次改变训练中的持仓转移、状态或奖励，须另开版本重训受影响部分。
"""
    (ROOT / "REPORT.md").write_text(text, encoding="utf-8")
    print(json.dumps({"report": str(ROOT / "REPORT.md"), "scenarios": len(comp), "audit": audit["status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
