"""Build a retrospective handoff from saved evidence; never train or replay."""
from pathlib import Path
import json
import hashlib
import math
import pandas as pd

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent
NEW = WORK / "a2_collaboration_methods_20260928_r1"
OLD = WORK / "a2_buy_sell_cash_multimodel_20260928"
ATTR = WORK / "a2_ensemble_attribution_20260928_r1"
REF = WORK / "original_A2_scores_common_account_reference_r1"
LABELS = {
    "base_ridge": "同基础 Ridge", "base_hgb": "同基础 HGB", "base_mlp": "同基础 MLP",
    "fixed_pred": "固定预测融合", "learned_fixed": "学习固定权重",
    "stack_ridge": "线性 Stacking", "stack_mlp": "小型 MLP Stacking",
    "conditional_gate": "条件门控", "ridge_then_hgb": "Ridge→HGB 残差修正",
    "hgb_then_ridge": "HGB→Ridge 残差修正", "decision_blend": "目标仓位融合",
    "ensemble_equal": "旧六成员等权", "ensemble_consensus_risk": "旧分歧风险",
    "ensemble_stacked": "旧收益代理学习权重",
    "original_A2_scores_common_account_reference_r1": "原 A2 分数共同账户参照"}
METHODS = ["fixed_pred", "learned_fixed", "stack_ridge", "stack_mlp", "conditional_gate",
           "ridge_then_hgb", "hgb_then_ridge", "decision_blend"]


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def link(label, path):
    return f"[{label}]({Path(path).resolve().as_posix()})"


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def comparison_table(frame):
    lines = ["|政策|净记账／指示收益|最大回撤|实际现金均值|费用美元|未认证估值日|",
             "|---|---:|---:|---:|---:|---:|"]
    for row in frame.itertuples():
        lines.append(f"|{LABELS[row.policy]}|{row.indicative_net_return*100:.2f}%|{row.indicative_max_drawdown*100:.2f}%|{row.mean_actual_cash*100:.2f}%|{row.fees_usd:,.0f}|{row.uncertified_days}|")
    return "\n".join(lines)


def main():
    comparisons = pd.read_csv(NEW / "ALL_COMPARISONS.csv")
    old_scenarios = pd.read_csv(OLD / "ALL_SCENARIOS.csv")
    verification = read(NEW / "VERIFICATION.json")
    assert len(comparisons) == 29 and len(old_scenarios) == 70
    assert verification["new_replay_paths"] == 22 and verification["reused_old_paths"] == 7
    assert read(REF / "COMPLETE.json")["status"].startswith("PASS")
    mechanics = pd.read_csv(NEW / "POLICY_MECHANICS.csv")
    h2 = comparisons.loc[comparisons.year.eq(2025)]
    future = comparisons.loc[comparisons.year.eq(2026)]
    controls = h2.set_index("policy")
    weights = {stage: read(NEW / f"meta_artifacts/{stage}/learned_fixed.json")["coefficients"] for stage in ["validation", "final"]}
    design_refs = [OLD / "EXPERIMENT_CONTRACT.md", OLD / "ENSEMBLE_CONTRACT.md",
                   ATTR / "ANALYSIS_CONTRACT.md", ATTR / "CONTROL_PLAN.md",
                   REF / "REFERENCE_CONTRACT.md", NEW / "DESIGN_CONTRACT.md", NEW / "DESIGN_LOCK.json"]
    method_records = []
    descriptions = {
        "fixed_pred": "同目标预测按事前固定0.20/0.50/0.30融合",
        "learned_fixed": "成熟时间OOF上以MSE及固定正则学习凸权重，评价时冻结",
        "stack_ridge": "基础输出标准化后Ridge alpha100",
        "stack_mlp": "基础输出标准化后8隐藏节点MLP，固定80轮",
        "conditional_gate": "4候选池当时状态输入，8隐藏节点门控，固定120轮",
        "ridge_then_hgb": "Ridge初始预测，HGB拟合折外残差",
        "hgb_then_ridge": "HGB初始预测，Ridge拟合折外残差",
        "decision_blend": "同当前账户状态生成三个成员目标，再融合并截断"}
    for method in METHODS:
        signature = {
            "batch_contract_sha256": sha(NEW / "DESIGN_CONTRACT.md"),
            "design_lock_sha256": sha(NEW / "DESIGN_LOCK.json"),
            "method": method, "description": descriptions[method],
            "base_target": "MEAN_ER_3D_5D_10D_20D",
            "base_feature_count": 32, "base_seed": 20260928,
            "stages": {"validation": "strictly before 2025-07-01", "final": "strictly before 2026-01-01"},
            "execution_contract": "1000000 empty; one-way 10bp; 20 names; total .95; mapper .0475; buy ADV .01; next open; preserve missing-input units"}
        method_records.append({
            "experiment_id": "A2_COLLAB_FIXED_R1_" + method.upper(),
            "method": method, "semantic_specification": signature,
            "specification_fingerprint": hashlib.sha256(canonical(signature).encode()).hexdigest(),
            "record_state": "COMPLETED_FIXED_BATCH_FROZEN_REUSE_REQUIRED",
            "owner_authority": "existing research registry only; this index is a lookup document",
            "evidence_ref": str(NEW / "REPORT.md"),
            "evidence_sha256": sha(NEW / "REPORT.md"),
            "do_not_repeat": "reuse saved stages, forecasts and ledgers for the same specification; do not add epochs, seeds or weights based on exposed outcomes"})
    account_records = []
    for row in old_scenarios.itertuples():
        folder = Path(row.path)
        receipt = folder / "PATH_COMPLETE.json"
        assert receipt.is_file() and sha(receipt) == row.path_complete_sha256
        signature = {"phase": "legacy_multimodel", "policy": row.policy, "window": row.window,
                     "year": int(row.year), "one_way_cost_bps": float(row.cost_bps),
                     "experiment_contract_sha256": sha(OLD / "EXPERIMENT_CONTRACT.md"),
                     "ensemble_contract_sha256": sha(OLD / "ENSEMBLE_CONTRACT.md")}
        account_records.append({"account_id": f"legacy|{row.policy}|{row.window}|{row.year}|{row.cost_bps}",
            "phase": "legacy_multimodel", "policy": row.policy, "year": int(row.year),
            "one_way_cost_bps": float(row.cost_bps), "folder": str(folder),
            "path_complete_sha256": sha(receipt),
            "specification_fingerprint": hashlib.sha256(canonical(signature).encode()).hexdigest(),
            "record_state": "SAVED_FROZEN_ACCOUNT_REUSE_ONLY"})
    for row in comparisons.loc[comparisons.source.eq("new_fixed_collaboration_batch")].itertuples():
        folder = NEW / f"evaluation_{row.year}" / row.policy
        account_records.append({"account_id": f"new_collaboration|{row.policy}|{row.year}|10",
            "phase": "new_collaboration", "policy": row.policy, "year": int(row.year),
            "one_way_cost_bps": 10, "folder": str(folder),
            "path_complete_sha256": sha(folder / "PATH_COMPLETE.json"),
            "record_state": "SAVED_FROZEN_ACCOUNT_REUSE_ONLY"})
    account_records.append({"account_id": "original_A2_common_account|2025H2|10",
        "phase": "original_A2_reference", "policy": "original_A2_scores_common_account_reference_r1",
        "year": 2025, "one_way_cost_bps": 10, "folder": str(REF / "account"),
        "path_complete_sha256": sha(REF / "account/PATH_COMPLETE.json"),
        "record_state": "COMPLETED_MISSING_CONTROL_QUESTION_CLOSED"})
    assert len(account_records) == 93 and len({item["account_id"] for item in account_records}) == 93
    index = {"schema_version": 1, "document_role": "DERIVED_TASK_LOOKUP_NOT_IDENTITY_OR_AUTHORIZATION_AUTHORITY",
        "scope": "four phases of this conversation; excludes sibling research tasks",
        "canonical_identity_registry": "D:/us-tech-quant-results/US_TECH_QUANT_RESEARCH_REGISTRY",
        "method_records": method_records, "saved_account_records": account_records,
        "unique_saved_account_count": 93, "reused_comparison_paths_not_new_accounts": 7,
        "independent_sample_count": "UNKNOWN; account scenarios and stock rows are dependent",
        "source_contract_sha256": {str(path): sha(path) for path in design_refs}}
    write(ROOT / "EXPERIMENT_INDEX.json", index)
    repeat_rules = [
        {"rule_id": "REUSE_ENGINE", "condition": "same holding-aware cash/cost/ADV/next-session account responsibility",
         "action": "reuse frozen engine_v2.py and its adapters/tests; do not build another account engine"},
        {"rule_id": "REUSE_OOF", "condition": "same 32 features, target, vintage and sample contract",
         "action": "read saved OOF/model/scaler artifacts after hash and stage validation; do not refit to reconstruct them"},
        {"rule_id": "REFERENCE_COMPLETED", "condition": "2025H2 original A2 saved-score common-account reference",
         "action": "reuse original_A2_scores_common_account_reference_r1 COMPLETE and account; CONTROL_PLAN historical TODO is resolved"},
        {"rule_id": "LEGACY_BATCH_SEALED", "condition": "same 70 legacy scenario specifications or attribution question",
         "action": "read original ledgers and saved cash/execution decompositions; do not rerun all scenarios for another comparison table"},
        {"rule_id": "EIGHT_METHODS_SEALED", "condition": "same eight fixed collaboration designs",
         "action": "reuse this method index and 22 saved paths; no outcome-driven additional epochs, seeds, ratios or searches"},
        {"rule_id": "KNOWN_CONVERGENCE_LIMIT", "condition": "base MLP40 or stacking MLP80",
         "action": "retain convergence warning; changing the budget is a new exploratory specification, not a silent completion repair"},
        {"rule_id": "GATE_KNOWN_BEHAVIOR", "condition": "day-dependent weights interpreted as proof of economic complementarity",
         "action": "reuse saved gate fit/update evidence and diagnostic weights; separate real training from economic benefit"},
        {"rule_id": "TARGET_BLEND_COLLAPSE", "condition": "same three member targets, same slots/ticket weights and HGB coefficient dominates other two sum",
         "action": "reuse the proven same-context HGB set identity; first demonstrate a materially changed mechanism before repeating a diversity claim"},
        {"rule_id": "NEAR_CASH_MEMBER", "condition": "legacy joint quantile risk policy included in six-member blend",
         "action": "reuse near-cash/projection attribution; do not label low exposure as proven complementary alpha"},
        {"rule_id": "NO_BLIND_RESET", "condition": "2026 results already exposed",
         "action": "do not relabel as pristine holdout or tune using them; preserve all candidate and problem dates"},
        {"rule_id": "ECONOMIC_QUALIFICATION", "condition": "inference from a certified price path to complete-pool or shareholder total-return qualification",
         "action": "require authoritative PIT identity, prices, corporate cash rights and settlement evidence; current bookkeeping PASS is insufficient"},
        {"rule_id": "CLOSED_REGISTRY_IDENTITIES", "condition": "closed/tombstoned/superseded related registry identity",
         "action": "preserve authority status; do not register a renamed wrapper or reopen through this handoff"}
    ]
    guard = {"schema_version": 1, "role": "TASK_REPEAT_LOOKUP_GUIDANCE_NOT_A_NEW_GOVERNANCE_ENGINE",
        "user_instructions_take_precedence_within_platform_rules": True,
        "this_report_does_not_authorize_new_training_replay_or_reopening": True,
        "experiment_index_ref": str(ROOT / "EXPERIMENT_INDEX.json"),
        "experiment_index_sha256": sha(ROOT / "EXPERIMENT_INDEX.json"), "rules": repeat_rules,
        "related_terminal_entity_ids": ["ACTION_ML_BUY_SELL_SIZING", "PORTFOLIO_WEIGHTING_VARIANTS",
            "PORTFOLIO_SYSTEMIC_RISK_OS", "STOCK_RISK_MODEL_VARIANTS", "TOPK_PORTFOLIO_SIZE"],
        "changed_specification_requires": [
            "state the new legal information, falsifiable mechanism or invalidating defect",
            "record the existing lineage and what is materially different",
            "freeze the new budget, cutoffs, target, benchmarks and stopping rule before evaluation",
            "do not reset exposed-window status; use applicable fresh prospective evidence for new confirmation"]}
    write(ROOT / "REPEAT_GUARD.json", guard)
    lower_weights = ", ".join(f"{100*w:.2f}%" for w in weights["validation"])
    final_weights = ", ".join(f"{100*w:.2f}%" for w in weights["final"])
    fee_saved = controls.loc["base_hgb"].fees_usd - controls.loc["learned_fixed"].fees_usd
    target_blend = mechanics.loc[mechanics.year.eq(2025) & mechanics.policy.eq("decision_blend")].iloc[0]
    sources = {
        "旧训练与70场景报告": OLD / "REPORT.md", "旧场景明细": OLD / "ALL_SCENARIOS.csv",
        "归因收口报告": ATTR / "REPORT.md", "原A2身份与OOF准入": ATTR / "qualification_original_a2_oof_admissibility.json",
        "原A2共同参照": REF / "RESULT.md", "参照完成收据": REF / "COMPLETE.json",
        "新组合设计": NEW / "DESIGN_CONTRACT.md", "新组合全部结果": NEW / "ALL_COMPARISONS.csv",
        "新基础拟合收据": NEW / "base_artifacts/TRAIN_RECEIPT.json", "新组合拟合收据": NEW / "meta_artifacts/TRAIN_RECEIPT.json",
        "门控参数更新审计": NEW / "meta_artifacts/POST_FIT_AUDIT.json", "时间资格独立审查": NEW / "GUARD_REVIEW.json",
        "新账本独立审查": NEW / "INDEPENDENT_LEDGER_AUDIT.json", "比较独立审查": NEW / "COMPARISON_REVIEW.json",
        "新现金机制独立审查": NEW / "POLICY_MECHANICS_REVIEW.json", "新批封存清单": NEW / "VERIFICATION.json"}
    source_lines = "\n".join(f"- {link(label,path)}；SHA256：{sha(path)}。" for label,path in sources.items())
    report = f"""# A2买卖、现金与多模型协作：训练复盘和开发交接

日期：2026-09-28。范围：本对话中的四个已完成阶段。本轮整理新增训练、预测、策略回放、权重搜索、行情下载均为0；不混入其他并行任务的研究结果。

## 1. 可供后续开发采用的结论

我们已经建立并实际运行了多模型买卖与现金决策原型，完成六类协作的固定尝试，解释了两批集成中重要的现金来源，并补齐2025H2原A2保存分数的共同账户参照。代码、冻结模型、时间折外预测、成交、持仓、现金、比较和独立核验均可复用。

本任务完成了工程与固定研究交付，尚未训练出可声明优于原A2的最终政策。新学习固定权重在H2相对同新HGB收益提高，但对原A2参照仍更低、回撤更大；2026未支持稳定增量结论，且经济资格本身未完成。MLP固定轮数未收敛、近现金分位数成员、目标融合退化为HGB成员名单等负面或不足证据全部保留。

未来开发先使用已有工件回答已回答的问题，再定义有实质差异的新问题。重复同一规格不会增加独立证据。报告记录的失败只针对相应数据、目标、预算、投影与评价规格，不是宣布某个模型家族普遍无效。

## 2. 原始目标与持续适用的约束

目标是以原A2研究结果为起点，训练买入、继续持有、退出和仓位相关政策，并让多个模型共同形成决策；考察固定融合、学习固定权重、Stacking、条件门控、分层残差修正、目标仓位融合六类方法。

|约束|本任务实际执行|仍需注意|
|---|---|---|
|候选池|固定24机构，按当时最近公开且已生效的13F季度；保守约定为披露后第5个QQQ会话生效|不等于每家供应商真实历史到达时点已证明|
|时间防泄漏|signal和标签末端同时严格早于该阶段截止；scaler、门控、权重和风险估计遵守对应截止|全局target可用标记不能替代逐阶段成熟检查|
|训练截止|所有真实训练和成熟标签早于2026-01-01；H2组合还有2025-07-01的更早截止|最终含2025训练的模型不能回算H2后声称样本外|
|控制样本膨胀|新基础每次50000行、新组合每阶段40000键；日期配额、固定键哈希、每日总权重相等|证券行、重叠多期标签、不同政策与成本场景不是独立样本|
|控制过拟合|固定参数、预算和种子；不按已见结果追加epoch/seed/比重/股票数搜索|有限预算与正则不能证明已经消除过拟合|
|账户公平性|100万美元空仓、同价、同引擎、收盘信号/次会话开盘、逐边10bp、买入ADV1%、最多20持仓|原生A2的初态、成本口径和敞口不同，不能直接相减|
|旧仓与坏日|缺输入/缺价旧仓保留单位、占用资金与名额；所有问题日、未知候选留存|保留旧仓不代表模型重新看好，缺价不默认清仓|
|2026角色|冻结参数后的事后核验，183账户日，并非全年|已观察过，不能恢复盲测、选冠军或调参|
|历史保留|旧批、归因、参照和新批各自留存；本轮不修改冻结研究字节|容量配对旧封口不重开|

## 3. 四阶段研究链与训练量

|阶段|目的与实际产物|新增工作计数|结论与接续状态|
|---|---|---|---|
|A：旧多模型共同账户|线性/树/分位数、直接MLP、RL、风险/诊断及六成员目标协作；保存70场景|14主线性/树拟合＋2个同样本同目标Elastic数值收敛修复；6个训练神经模型；风险/诊断另计；2个集成权重求解|固定批完成，原型可运行；旧70场景封存|
|B：封存与现金/执行归因|封存976个非缓存原件及797依赖；拆解成员现金、投影、旧仓、执行和资格|新训练/预测/权重搜索/策略回放均0|现金机制已解释；不产生替代政策收益路径|
|C：原A2共同账户参照|核实原OOF身份、价格/特征与时钟准入，完成唯一H2原分数参照|新模型拟合0，新增固定账户回放1|CONTROL_PLAN所述缺失H2对照已经闭合|
|D：六类新协作|同目标Ridge/HGB/MLP，8组合＋3同基础控制，两窗口固定评价|9基础回归器拟合＋6基础scaler；12组合拟合/求解；22新账户；7旧账本复用|全部固定设计和交付完成，未确认优于原A2|

旧神经训练为2个direct MLP阶段和4个RL阶段/种子模型，共7820次参数更新；旧风险部分6模型fit、2诊断scaler和2因子分解，不能与神经更新步简单相加称作独立模型。70场景由56基础/对照账户和14集成账户组成。旧批与新批的模型目标、输入和预算不同，禁止把同名HGB或MLP视为同一个模型。

本任务累计保存93条不同账户轨迹：旧70＋原A2参照1＋新22。新比较表29行含7条复用轨迹，不能再次计为新增账户，更不能把93当成独立研究样本。有效独立样本数没有在本任务中得到证明。

阶段目录分别为：

- {link("A：旧多模型",OLD / "REPORT.md")}。
- {link("B：归因收口",ATTR / "REPORT.md")}。
- {link("C：原A2参照",REF / "RESULT.md")}。
- {link("D：新协作",NEW / "REPORT.md")}。

## 4. 模型能力到底进入了哪里

|方法家族|本任务的真实使用|可复用结论／限制|
|---|---|---|
|Ridge／Elastic Net／逻辑回归|旧批正式训练并进入成员目标或对照；新批Ridge为同目标基础、Stacking和残差元模型|保留线性对照；逻辑概率不能直接与收益/神经logit相加|
|HGB／GBDT|旧批动作价值/分位数和已有预测工具；新批同目标基础与残差修正；原A2另有已核OOF|原A2、旧joint HGB、新HGB是三种身份，必须分开|
|小型MLP|旧direct政策参与六成员目标；新基础32→16及8节点Stacking真实拟合|固定40/80轮未收敛，预算完成与优化收敛不同|
|分位数／分布预测|旧Q10/Q50/Q90与联合分位数风险政策真实使用|联合风险成员在此规格主要近现金；不证明分布预测家族无效|
|PCA／因子与协方差收缩|旧阶段专属风险估计、HGB+LW/HGB+PCA和集成风险工具|矩阵存在不等于每个最终风险上限生效，需读实际调用/缩放|
|成本和约束优化|统一账户预算/名额/旧仓、容量及风险投影形成实际订单|本任务没有证明全局最优；新六类批未另造一套优化器|
|聚类／异常检测|旧训练阶段诊断；新门控用已知候选池状态|异常不是自动删除样本或买卖信号|
|强化学习|旧两种子正式训练、零更新对照与共同账户回放|本新组合批不追加RL；更新参数不等于经济决策学得更好|

分钟级精准进出价、真实券商撮合、完整股息/并购现金结算没有在本任务中完成。当前买卖由日频预测/排名及目标仓位生成。

## 5. 关键设计选择及得失

### 5.1 先统一目标，再比较预测协作

旧成员分别输出动作价值、概率、分位风险和直接目标政策，量纲不同。旧批采用目标仓位级融合。新批为预测融合新增有限的同目标Ridge/HGB/MLP版本，沿用32特征和原MEAN_ER_3D_5D_10D_20D成熟目标。

好处是组合系数、Stacking与残差具有明确输出单位；代价是基础目标和训练规格也改变。因此必须增加3条同基础单模型控制，先比较新组合与这些控制，再比较整套政策与原A2。不能把新基础改变带来的差额全部称为集成收益。

### 5.2 用成熟时间OOF学习，避免最终模型回算历史

pre2024基础只消费2023成熟标签生成2024 OOF；pre2025只消费2023—2024成熟标签生成2025 OOF及H2；pre2026基础消费2023—2025成熟标签用于2026。OOF共216412行、502日；9583条目标不可用记录完整留存并排除拟合，另行执行严格成熟截止。

H2组合取2024＋2025H1 OOF且标签末端严格早于2025-07-01，最后signal为2025-05-30、标签成熟2025-06-30。最终组合只取2024—2025 OOF且标签末端早于2026-01-01，最后signal2025-12-02、标签成熟2025-12-31。

这种设计减少训练内预测充当元模型输入的泄漏。它仍依赖现有数据的PIT身份与价格资格；时间边界检查通过不能补足供应商到达或股东经济映射。

### 5.3 固定预算，接受不足结果

基础Ridge alpha10；HGB150轮、depth3、15叶、最小叶200、l2=5、lr=.05；基础MLP32→16、alpha=.01、batch512、lr=.001、固定40轮。训练目标裁剪±.30，保存预测与评价目标不裁剪；所有scaler只fit对应训练样本。

每次基础50000行上限、每组合阶段40000键，按成熟日配额和固定键哈希抽样，逐日总权重相等，种子20260928。好处是计算量及搜索范围可核对，减少某日股票数量过多造成的支配；代价是并未证明这些容量和正则是最优。基础MLP与Stacking MLP未收敛是已知不足，不能静默追加轮数补成“成功”。

### 5.4 同一账户中的协作，接受现金和路径后果

各成员或组合在同一当日账户状态下生成目标。保留旧仓先占名额和预算；政策映射每票至多4.75%，总目标至多95%，新批只在预算不足时下缩，目标截断后不回补。信号收盘、下一会话开盘执行，买入受信号ADV1%限制，卖出不施加同一ADV上限，末尾不强平。

好处是目标、实际成交、费用和现金都能落账；代价是预测相似或成员权重大的政策可能退化为同一名单，目标融合可能增加机械现金。共同账户也使不同模型输出的差异通过后续持仓路径放大，汇总收益不能分离各部件因果贡献。

## 6. 六类协作的实际规格和逐项判定

|类别／实际设计|固定实现|本规格结论|
|---|---|---|
|固定融合|Ridge/HGB/MLP=.20/.50/.30|H2亏损6.17%，不支持此比例；不能推断所有固定融合无效|
|学习固定权重|OOF目标MSE＋prior L2=.001；权重各[.05,.85]、和1|H2相对同基础有正收益差，但回撤扩大且未超过原A2|
|线性Stacking|3基础输出标准化→Ridge alpha100|H2仅比新HGB多0.34pp，费用显著更高，未证明实质优势|
|小型非线性Stacking|3输出标准化→8节点MLP，alpha.1，80轮|H2回撤较小、收益较低、换手费用高；未收敛|
|条件门控|4→8 tanh→3；.05＋.85×softmax；Adam .01，120轮|参数确有训练更新，权重确按日变化；H2未改善同基础HGB收益|
|Ridge→HGB修正|HGB拟合target−Ridge残差；3预测＋4状态；100轮depth2/7叶/minleaf200|H2收益9.49%、费用高；本顺序不支持改善|
|HGB→Ridge修正|标准化3预测＋4状态；Ridge alpha100拟合target−HGB残差|H2收益20.72%，略低于同HGB且回撤更大|
|目标仓位融合|3基础同账户形成TOP20目标，按学习系数融合后截断|主要改变票重和现金；不能声称扩大最终选股名单|

H2学习系数Ridge/HGB/MLP为{lower_weights}；最终用于2026的系数为{final_weights}。5%的MLP下限是事前约束，不能把它解释为“模型证明MLP应贡献恰好5%”。这些是目标预测误差上的贡献比例，不是收益归因份额。

门控状态为候选池过去20日收益均值、20日波动均值、高于MA20的比例和3预测分歧日均值。2026只能用可核验子池，83条held-only行接收同日状态、不进入均值。两阶段w1/b1/w2/b2初始至最终L2差全部非零；各跑120轮，torch/numpy推断一致。真实训练与动态输出都已证实，但动态不自动等于更好的交易。

## 7. 2025H2完整共同账户比较

128账户日，2025-07-01—12-31；126信号日；100万美元空仓；逐边10bp；同价、同引擎、同旧仓保留与容量。以下为研究指数坐标的净记账结果，不自动取得真实股东总收益资格。

{comparison_table(h2)}

学习固定权重相对同新HGB净记账收益增加7.99个百分点，最大回撤由−16.90%扩大至−18.35%；费用仅节省约{fee_saved:,.0f}美元、平均实际现金仅多0.47个百分点。这个正差不能简单归于现金替代或降费，也不足以证明互补的因果贡献。

相对原A2共同参照，学习固定权重收益低7.43个百分点、回撤更大；全部8个新组合在此窗口的收益均未超过原A2参照。原A2参照是原保存分数经共同账户映射形成的研究控制，不能扩大为原生A2实盘结果的完整证明。

原A2原生TOP20各5%、总100%、归一资金1.0且历史连续持仓；其标称10bp公式实际每边5bp。本共同参照改为各4.75%、总95%、100万空仓、每边10bp和1%ADV，使整套新增决策政策的差异可以在共同口径下比较。

![预设顺序下的H2收益、回撤和现金比较]({(NEW / 'H2_COMPARISON.png').as_posix()})

## 8. 现金、持仓和费用：两批研究学到了什么

### 8.1 旧近现金成员与投影

旧H2目标现金按固定算法顺序分解：

|路线|目标现金均值|固定储备|成员未用预算|其中分位数成员|分歧收缩|名额截断|保留旧仓股票敞口|
|---|---:|---:|---:|---:|---:|---:|---:|
|等权|39.200%|5.000%|15.311%|14.864%|0|18.889%|5.618%|
|分歧风险|66.343%|5.000%|16.458%|15.397%|35.078%|9.807%|2.417%|
|旧学习权重|55.213%|5.000%|33.041%|32.939%|0|17.173%|0.691%|

分位数成员项包含在“未用预算”中，不能再次相加；保留旧仓是股票敞口，不是现金。原日账户状态下把联合分位数风险成员股票目标设为0，三路线H2最终目标126/126不变；2026为180/181不变。该成员在这套投影中主要近现金，其偶尔目标通常被截断。核对未演化替代账户，因此没有得到“用现金替换后的收益”。

旧学习权重相对分歧风险H2净损益多25164.65美元，费用节省9262.76美元；相对等权却少赚68352.12美元，虽节省30025.05美元费用。这说明评价要明确比较对象，不能笼统称学习权重改善收益。费用加回是既定路径会计拆分，不是零费用策略重新运行的结果。

### 8.2 新目标融合为何有20%现金

H2新目标融合126信号日平均移除12.3671个百分点目标权重，政策总预算二次缩放未触发，损失来自TOP名额截断。信号隐含目标现金均值{target_blend.mean_signal_implied_cash*100:.2f}%，128个收盘账户日实际现金均值20.00%；时钟和分母不同，不能强行将这两个均值逐项相减做因果归因。

307/307个信号日，政策TOP投影后、进入账本资格适配前的保留集合都等于同账户状态的HGB成员集合。原因是各成员采用相同名额和单票权重，HGB系数大于另外两者之和。这不是独立base_hgb账户的路径完全相同，更不是2026适配后的名单保证相同。

2026有15日进一步因SIGNAL_NEW_CAPITAL_INELIGIBLE降权，BYND6日、SLMT9日。目标权重和NAV含未认证估值，比例只能指示性阅读。未来要尝试不同决策级协作，先证明新机制改变了此退化条件，再按新合同评价，不应重跑当前相同参数。

### 8.3 实际成交与旧仓语义

显式0目标、无模型决定、保留单位和操作退出分别记录。旧H2三集成受ADV限制的买成交为63/43/18笔；累计未满足订单流不能当作期末现金或解除限制的收益。旧2026每条10bp路径的127条EXAS退出通知均无实际持仓，不验证并购现金结算。

新22路径共3421账户日，独立现金重建最大误差约3.08e−9美元，交易金额/10bp费用误差为0，持仓单位累计误差约1.24e−10，无决定旧仓单位保留误差为0。通过的是会计和执行实现，不能取代经济数据资格。

## 9. 2026冻结事后核验及资格边界

窗口2026-01-02—09-24，183账户日、181信号日，并非全年。以下所有收益、回撤和涉及NAV的现金数值只作指示值；不能据此选赢家或追加训练。

{comparison_table(future)}

在现有价格坐标下，8个新组合的指示收益都未超过同新HGB的10.75%。这是一条需要保留的负面观察，不能据此证明所有组合方法无效，也不能在数据资格未完成时声称正式经济比较已经通过。

完整原候选111868行：62393合格、47271未知、2204已证不合格；新评价输入另含83条held-only行。完整原池合格信号日为0。旧问题记录包括5118未认证账户日、29619问题持仓行及32811价格警告或GLW冲突披露行，未删除。

GLW 2026-02-26事件时点/调整特征冲突仍在；后续价格标记不等于冲突已经济修复。真实原股数、股息/并购现金权利、结算时点、供应商历史到达、完整候选池幸存者偏差仍缺证。调整指数价格、完整现金恒等式和哈希身份分别解决不同问题。

新线性Stacking有0未认证估值日，已核完整183日/181信号、3629持仓记录均有当日有效close，首日后19—20只持仓。它只通过现有路径价格门，不能升级为完整13F池、GLW经济输入或真实股东回报合格。

## 10. 成功、失败、不足和未回答问题

|类型|可确认事实|后续应如何使用|
|---|---|---|
|工程成功|六类协作真实训练/目标形成；门控参数更新；买卖/现金共同落账|复用模块和冻结工件，避免再从接口原型开始|
|时间/核验成功|逐阶段成熟、OOF身份、候选状态广播、次会话时钟、日期、账本和比较均独立通过|沿用已通过边界，不削弱门禁|
|对照完成|真正原A2保存OOF的唯一H2共同参照已生成|缺失对照问题闭合；直接消费原件|
|本规格失败|固定20/50/30 H2负收益；两残差顺序未改善；条件门控未改善H2新HGB|保存失败规格，不能靠改名重复或概括家族失败|
|优化不足|3个基础MLP40轮、2个Stacking MLP80轮未收敛|明确预算限制；若未来改变预算，另记录新探索|
|经济优势未证明|本新8组合H2未超原A2；2026未支持稳定增量|不升级冠军、生产或正式优势|
|互补未识别|近现金成员、名单退化、费用与现金混合影响|不能把剩余损益差直接命名为互补alpha|
|输入资格不足|未知池、GLW、到达/现金映射仍未完成|缺证保留，不删坏日、缩窗口或默认清仓|
|未在本任务完成|分钟级买卖价、真实撮合/税费/冲击、2026原A2完整共同参照|不能在报告中补写为已完成，也不默认启动新工作|

实施性修复与研究设计改变分开记录。旧Elastic两次是同样本同目标的收敛数值修复；新批在组合拟合和回放前修正年度OOF/stage身份、candidate-only状态及基础收据匹配，保留原设计锁及IMPLEMENTATION_GUARDS哈希链，未改模型参数和预算。独立分析脚本的索引对齐修复不改训练或策略路径。

## 11. 后续开发的接续顺序

1. 先查权威注册表及本任务工件目录，确认已有机制、身份、失败与封口状态。目录或名字未匹配不代表从未做过。
2. 能用现有预测/账本回答的问题，直接读缓存和保存收据；同H2比较、现金来源、门控是否真实训练已回答，不重训/重放。
3. 如果目标是正式2026经济资格，先补真实PIT证券身份、事件、价格和现金结算证据；另存修订版本，保留旧新逐行差与全部窗口。此任务没有实施补数。
4. 如果研究新的组合机制，写明它与固定八设计的实质差异，事先锁定目标、样本、预算、基准、现金/投影规则及停止条件。不能仅增加seed/epoch或更换名称掩盖重复。
5. 新确认需要适用的未被用于选型的未来证据；已暴露2026不会因为换任务或文件名恢复盲测。训练与选择仍遵守原严格截止，除非未来有明确适用的变更授权。

可提出的新问题示例是：如何在同账户约束下避免目标融合名单退化；预测误差改善为何没有转换成扣成本收益；如何区分近现金替代与模型互补。这里只登记问题，不启动新的训练、搜索或回放，也不预先指定原A2必须先行。

## 12. 复用入口与禁止重复范围

{link("REUSE_COMPONENTS.json",ROOT / "REUSE_COMPONENTS.json")}登记69组件，包括实际路径/SHA、阶段截止、生产者、最小调用及限制；其中覆盖22新＋7复用完整账本。{link("DEVELOPMENT_HANDOFF_NOTES.md",ROOT / "DEVELOPMENT_HANDOFF_NOTES.md")}给出load/read的最小接续示例。示例不会自动执行拟合。

{link("TRAINING_LESSONS_NOTES.md",ROOT / "TRAINING_LESSONS_NOTES.md")}展开训练次数、模型结构、组合设计、现金与执行归因的得失，并逐项连接原始证据；与本报告共同构成详细开发交接。

{link("EXPERIMENT_INDEX.json",ROOT / "EXPERIMENT_INDEX.json")}登记8个固定方法规格及93条已保存账户位置，属于检索文件，不是第二权威注册表。{link("REPEAT_GUARD.json",ROOT / "REPEAT_GUARD.json")}标明同规格应复用、已闭合对照、已知失败机制、旧70和容量配对不重开，以及实质新证据条件。

这些文件建立可查的研究记忆和默认复用要求，没有新增通用调度器、重复预测/账户引擎或运行时训练拦截系统。未来明确用户指令仍按适用权限处理；报告自身不授权研究重开或放松2026边界。

## 13. 现有注册表的更新设计与状态依据

唯一身份权威为D:/us-tech-quant-results/US_TECH_QUANT_RESEARCH_REGISTRY。首次只读发现时accepted head为84e29c33d770de6fd17db69b5c62dc6e38361881e69949a62aba05bc035ed92b，60实体/171别名/23事件。准备期间出现另一任务的并发登记，实际提交须基于最新有效head重新构造并独立审阅，准确起点和终点以更新收据为准。

登记仅给以下既有非终结条目追加本任务报告、规格检索和复用引用及SHA：

- RAW_A2_HGB_BASELINE：原A2共同参照与模型身份区别。
- RAW_A2_BROAD_OOF_PREDICTIONS：保存OOF、成熟边界、不得用最终模型回算H2。
- A2_COST_NAV_REPLAY_ENGINE：账户/成本/保留仓/现金核验和已有账本入口。
- A2_TEMPORAL_PIT_FEATURE_CONTRACT：折外、成熟、候选广播及经济限制。
- THIRTEEN_F_LEVEL_AND_LIFECYCLE_LINEAGE：本任务研究知识与原13F总结的关联，保留旧知识引用。

原实体status、canonical identity、fingerprints、aliases、时间资格和旧metadata均保留。ACTION_ML_BUY_SELL_SIZING、PORTFOLIO_WEIGHTING_VARIANTS等既有CLOSED身份不可修改或通过新名字重开。新批结果作为已授权任务的外部研究记录接续，不授予这些旧方向新的研究资格。

权威注册表只存元信息和外部引用，不内联表现数值或2026结果计数。详细结果在本报告与原CSV中。实际补丁独立审阅、C盘副本演练、权威新快照/事件链及派生检索表同步结果见{link("REGISTRY_UPDATE_RECEIPT.json",ROOT / "REGISTRY_UPDATE_RECEIPT.json")}；交付完成状态以该收据为准，不能把stage副本当成权威。

## 14. 核验与来源

新批369项原封存清单在本轮保持字节不变。旧冻结工件不被本报告或注册表变更覆盖。独立账本、比较、时间边界与现金机制审查均通过；29行指标、72组差值和逐路径实际日期一致。旧2026三个集成metadata起始写非交易日01-01，新写首交易日01-02，实际信号/账户日期相同，该差异已解释。

报告数值取自保存账本/收据；没有新增收益选择、显著性筛选或经济资格升级。引用按实际文件SHA绑定；后续新版本不得悄悄修改这些原件。

{source_lines}
"""
    (ROOT / "TASK_RESEARCH_REPORT.md").write_text(report, encoding="utf-8")
    write(ROOT / "HANDOFF_BUILD_RECEIPT.json", {
        "status": "PASS_REPORT_AND_TASK_LOOKUP_BUILT",
        "fit_calls": 0, "prediction_calls": 0, "replay_calls": 0, "downloads": 0,
        "training_scope": "saved four-phase task only",
        "new_method_records": len(method_records), "saved_account_records": len(account_records),
        "independent_sample_count": "UNKNOWN",
        "source_sha256": {str(path): sha(path) for path in sources.values()},
        "output_sha256": {str(ROOT / name): sha(ROOT / name) for name in [
            "TASK_RESEARCH_REPORT.md", "EXPERIMENT_INDEX.json", "REPEAT_GUARD.json"]},
        "original_new_batch_verification_sha256": sha(NEW / "VERIFICATION.json")})
    print(json.dumps({"status": "PASS", "method_records": 8, "saved_account_records": 93,
        "report_characters": len(report), "new_fits": 0, "new_replays": 0}))


if __name__ == "__main__":
    main()
