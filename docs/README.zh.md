# US Tech Quant v21

**沿着一条美股投资思路，查看公开信息如何形成模型预测、组合目标与模拟订单。**

US Tech Quant 是一个研究与模拟系统，让投资决策背后的步骤可以逐项检查。它将按信息可得时间组织的数据层、机器学习研究、组合约束和账户对账连接到同一个三语工作台。

**[English](../README.md) · [中文](README.zh.md) · [日本語](README.ja.md)**

[项目概览](#overview) · [体验演示](#quickstart) · [架构](#architecture) · [技术设计](#engineering) · [研究状态](#research) · [验证](#verification) · [源码导航](#navigation)

<a id="overview"></a>
## 你能了解和使用什么

模型评分只是完整决策中的一步。系统围绕四个问题展开：

1. **当时知道什么？** 检查输入的来源、证券身份和公开时间。
2. **模型输出了什么？** 按照原本含义理解股票评分、动作价值或目标仓位。
3. **组合能够持有什么？** 在考虑现有持仓的同时，应用风险和配置约束。
4. **实际发生了什么？** 对照研究目标、账户目标、订单以及对账后的持仓。

例如，一份在**纽约时间 10:20** 才公开的公司文件，不能用于**当天上午 09:45 的决策**。即使稍后的预测满足信息时点要求，仍需通过组合和执行检查。这是用于解释系统时点规则的假设示例，不是市场观测。

### 已配置环境中的完整工作台

| 区域 | 可以查看的内容 |
| --- | --- |
| 技术展厅 | 沿导览理解信息时点、特征、学习方法、组合风险与模拟流程 |
| 方法案例 | 查看一种方法如何将输入转为其自身定义的输出，并进入模型检查与组合决策视图 |
| 研究记录与图表 | 查看所选方法的来源日期、个股历史、已记录决策、覆盖缺口及可用证据 |
| 每日模拟 | 在原有账户组件中查看账户目标、当前持仓、订单差异和对账状态 |

界面支持**中文、日文和英文**，提供研究与演示视图。记录按需加载；入门讲解无需加载研究历史或模型即可查看。详见[工作台说明](../apps/demo_console/README.md)。

### 在决策流程中理解机器学习

当前查询目录包含八种已登记方法，包括基于评分的基线、直方图梯度提升（HGB）、ElasticNet 和 Ridge 等正则化线性模型、树与神经网络方法，以及仓位控制方法。不同输出有不同用途：

| 输出 | 如何理解 |
| --- | --- |
| 股票评分 | 一种方法对候选股票的评价或排序 |
| 动作价值 | 模型对某项决策给出的价值，不会自动成为组合权重 |
| 仓位或目标权重 | 建议的资金配置，仍受对应账户和执行规则约束 |

展示名单从该目录中选取五种方法，并可按展示需要调整，与纸面账户成员和券商策略选择分别管理。不同方法的评分不合并为统一排名。目录说明已有实现；每种方法的验收状态与研究有效性仍须分别判断。

<a id="quickstart"></a>
## 体验演示

### 1. 运行公开离线演示

**需要：** Windows、PowerShell、Git，以及可通过 `python` 调用的 Python 3.12。手动模拟使用 Python 标准库和内置的合成目标、价格。

在新的 PowerShell 窗口中运行：

```powershell
git clone https://github.com/kinryukii/us-tech-quant-v21.git
Set-Location us-tech-quant-v21

# Give this demonstration its own state outside the source checkout.
$env:USTQ_DAILY_ROOT = Join-Path $env:LOCALAPPDATA 'US Tech Quant\demo-daily'
$demoState = Join-Path $env:USTQ_DAILY_ROOT ('paper-' + [guid]::NewGuid().ToString('N'))
python -B -m apps.moomoo_trading_component.moomoo_component `
  --repo-root $PWD.Path --data-dir $demoState --port 8766
```

打开 [localhost:8766](http://127.0.0.1:8766/)，依次使用以下中文按钮：

1. **载入离线演示：** 载入合成目标与价格。
2. **预览订单与风控：** 执行前检查拟生成的订单。
3. **执行一轮：** 手动执行一轮纸面模拟，再检查持仓与审计记录。

预期得到一个能追溯“目标 → 订单 → 持仓”的模拟账户。无需研究数据集、冻结模型、Moomoo SDK 或 OpenD 连接。演示保持手动纸面模式，按 `Ctrl+C` 停止服务。如果 8766 端口已被占用，可改用 `--port 18766` 等其他端口，并打开对应地址。

### 2. 在已配置环境中打开完整工作台

完整工作台运行于 **[localhost:8506](http://127.0.0.1:8506/)**，并嵌入 8766 端口的账户组件。其研究视图需要该环境使用的外部运行环境、数据集、冻结产物，以及通过资格核验的发布记录。

<details>
<summary>本机启动器、日常更新与依赖</summary>

请使用与离线示例不同的 PowerShell 窗口，避免继承其临时存储覆盖设置：

```powershell
Set-Location D:\us-tech-quant
.\打开DEMO.ps1
```

打开页面或切换语言、日期、展示模式，不会启动采集、拟合、回放或下单。明确需要日更时，使用现有入口：

```powershell
.\更新今日推荐.ps1
```

更新会检查已接受输入能否复用，并继续符合条件的未完成阶段。来源核验、各分支失败状态和最近已验证截止日会继续保留。明确需要同日重新采集时使用 `-RefreshData`。完成后重新加载发布缓存；详见[日更与恢复说明](../docs/daily_recommendation.md)。

`requirements.lock.txt` 记录基础环境。[工作台依赖](../apps/demo_console/requirements.txt)与[可选券商依赖](../apps/moomoo_trading_component/requirements-moomoo.txt)分别维护。[模拟说明](../apps/moomoo_trading_component/README.md)介绍纸面账户和可选的 Moomoo SIMULATE 接入；组件不提供 REAL 实盘下单能力。

</details>

<a id="architecture"></a>
## 各部分如何协作

```mermaid
flowchart LR
    A["市场数据<br/>与公开披露"] --> B["按信息可得时间组织的<br/>数据与特征"]
    B --> C["模型预测"]
    C --> D["受约束的<br/>组合目标"]
    D --> E["研究回放<br/>或账户模拟"]
```

工作台读取各阶段已发布的记录，并展示来源、日期与状态。研究回放、本地纸面账户和券商模拟各自保留独立的执行时钟与账目。研究历史曲线与账户确认成交是不同的记录。

| 层次 | 主要技术 | 职责 |
| --- | --- | --- |
| 数据 | Python、Pandas、NumPy、PyArrow、Parquet、SQLite | 查询有来源依据的数据，保留历史证券身份与信息可得性 |
| 建模 | scikit-learn；各任务使用的提升树和神经网络库 | 在适用研究契约内生成并解释模型原生预测 |
| 组合与回放 | Python 研究模块 | 将预测转为受约束目标，并评价账户行为 |
| 展示 | Streamlit、Altair、共享数据读取模块 | 用三种语言解释机制、检查发布记录 |
| 模拟与运维 | Python 标准库、SQLite、PowerShell | 持久保存状态、核对订单，恢复本系统管理的进程及日更阶段 |

源码和小型配置文件保存在 Git 中。数据、模型、实验、报告、缓存与账户状态通过统一的[存储配置](../config/storage_paths.json)和[路径解析器](../scripts/common/storage_paths.py)，分别进入不同的外部根目录。配置与管理职责见[存储布局](../docs/STORAGE_LAYOUT.md)。

<a id="engineering"></a>
## 值得查看的工程设计

### 按信息实际可得时间决定能否使用

季度持仓报告描述的是一个报告期，但只有在披露后才可使用。13F 重建会检查带时区的接收时间戳、决策截止时点、修订语义和历史证券身份；单凭股票代码不足以确定该身份。证据缺失或不一致时会明确呈现，不用今天的映射补齐过去。

[实现](../scripts/v22/pit_13f_reconstruction_r1.py) · [时点与身份测试定义](../scripts/v22/test_fast_a2_r0g1_dynamic_pit_13f_universe_reconstruction_and_exact_r4_rerun.py)

### 配置资金前先保留预测的原本含义

概率、排名与收益预测不能相互替代。桥接层保留每类输出的原本含义，并从拟合截止前结果已知的历史预测中学习转换。具体而言，它用按时间划分的折外预测（OOF）记录拟合缩放和 Ridge 桥接，保留原生预测坐标，并让每个日期的总权重相同。测试检查追加未来记录不会改变更早拟合的桥接。

[实现](../scripts/research/a2/ensemble/joint_oof_bridge.py) · [标签成熟与未来记录测试定义](../tests/research/a2/ensemble/test_joint_oof_bridge.py)

### 现有持仓始终属于组合约束

当前无法交易的持仓仍占用资金和仓位名额。组合策略先预留这两部分，再分配其余资金。目标不可行时会明确回退，而不会隐式地把持仓变成现金；共享引擎原有的业务退出规则仍然适用。持仓数量求解器采用确定性近似方法，不保证全局最优。

[实现](../scripts/research/a2/inference/joint_portfolio_policy.py) · [持仓与不可行目标测试定义](../tests/research/a2/inference/test_joint_portfolio_policy.py)

### 恢复前先核对所复用工作的身份

图表更新失败不应悄悄替换已接受的推荐。日更恢复会先核对来源、日期、当前启用的策略及引用内容，再复用已接受输入。它继续符合条件的未完成分支，同时保留各自的失败状态和实际覆盖日期。基准刷新等其他必要工作仍可能执行。

[实现](../scripts/daily_recommendation.py) · [恢复测试定义](../tests/test_daily_recommendation.py)

### 订单结果未知时，先保持未知再对账

网络超时可能发生在券商已经接受请求之后。模拟组件在发送前先持久保存具有稳定身份的订单意图；若提交结果未知，就明确记录，并停止自动重发。请求被接受不等于确认成交。这些措施控制重复提交风险，不承诺分布式系统中的“恰好执行一次”。

[实现](../apps/moomoo_trading_component/moomoo_component/core.py) · [订单生命周期测试定义](../apps/moomoo_trading_component/tests/test_core.py)

<a id="research"></a>
## 研究状态与限制

本仓库同时包含维护中的应用、研究实现和保留的历史源码。公开名称仍是 **v21**；`V22`、`A2`、`FAST3` 和 `FAST6` 指内部流水线或研究系列，名称本身不代表验收级别。

| 阶段 | 边界 |
| --- | --- |
| 训练与开发验证 | 内容严格早于 **2026-01-01**，包括预处理拟合、特征选择、校准、早停与模型选择 |
| 2026 评价 | 观测和目标限于 **2026-01-01 ≤ 时间 < 2027-01-01**，继续服从各组件更早的截止、实际信息可得性及结果成熟要求 |
| 冻结应用 | 应用既有变换和模型，不更新拟合参数 |

A2 的 2026 窗口已经暴露，不能称为新的独立留出集。依据已暴露记录挑选展面属于描述性展示。FAST3 按当前契约仍仅使用合成数据。[项目地图](../docs/PROJECT_MAP.md)用于定位适用的管理模块与契约；已接受注册表和 manifest 确定身份及状态。

仓库发布工程实现及其证据路径。预测是否有用、经济上是否有效、是否具备实盘执行条件，都需要各自的评价。完整数据集、模型权重、研究账本和账户状态不包含在本源码发布中。

<a id="verification"></a>
## 可检查的验证证据

**本地工程运行记录，2026-10-18：743 passed，1 skipped。** 跳过的 Windows PowerShell 检查受本机执行策略阻止，原执行策略保持不变。这是有日期的运行记录，不是实时 CI 状态标记。

[pytest.ini](../pytest.ini)选定已审阅的合成测试，覆盖存储、来源／目录核验、日更协调、维护和服务生命周期。上文的研究与组件测试链接提供额外测试定义，并非全部包含在此次默认运行中。

**离线首次运行检查，2026-10-18：** Python 3.12.10 在禁用第三方包加载后，完成了“载入合成示例 → 预览 → 执行 → 持仓／审计”的流程；重复执行未新增订单。检查使用新的隔离状态目录，保持纸面模式，未发生出站连接尝试。它验证 HTTP/API 流程，不证明浏览器易用性或券商执行行为。相关组件检查见 [HTTP 测试定义](../apps/moomoo_trading_component/tests/test_http.py)。

<details>
<summary>在已配置的本机仓库中复现默认测试</summary>

从仓库根目录运行，并使用新的外部临时目录：

```powershell
Set-Location D:\us-tech-quant
$projectPython = 'D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe'
$cacheRoot = (& $projectPython -B -c "from scripts.common.storage_paths import resolve; print(resolve().cache_root)").Trim()
$verificationRoot = Join-Path $cacheRoot ('_maintenance\readme-verification-' + [guid]::NewGuid().ToString('N'))
& $projectPython -B -m pytest -q `
  --basetemp (Join-Path $verificationRoot 'tmp') `
  -o "cache_dir=$(Join-Path $verificationRoot 'pytest-cache')"
```

保留配置中的测试选择。执行额外历史或研究测试前，须审阅其导入、数据访问、子进程和输出位置。该测试集不是全仓库覆盖。

</details>

<a id="navigation"></a>
## 源码导航

| 想了解的内容 | 从这里开始 |
| --- | --- |
| 界面与方法讲解 | [工作台说明](../apps/demo_console/README.md) |
| 订单、账户与对账 | [模拟说明](../apps/moomoo_trading_component/README.md) |
| 数据与历史信息可得性 | [数据层说明](../docs/DATA_LAYER.md)、[DataStore](../scripts/storage/storage_r2a.py) |
| 预测、风险与配置 | [预测桥接](../scripts/research/a2/ensemble/joint_oof_bridge.py)、[风险估计](../scripts/research/a2/risk/joint_risk_estimators.py)、[组合策略](../scripts/research/a2/inference/joint_portfolio_policy.py) |
| 研究身份与过往试验 | [研究导航](../docs/research/README.md)、[注册表](../scripts/maintenance/research_registry.py)、[生命周期](../scripts/maintenance/prospective_research_lifecycle.py) |
| 日常运行与恢复 | [日更说明](../docs/daily_recommendation.md) |
| 仓库组织与历史源码 | [仓库布局](../docs/governance/REPOSITORY_LAYOUT.md)、[保留源码说明](../scripts/research/a2/retained/README.md) |
| 项目全貌 | [项目地图](../docs/PROJECT_MAP.md)、[文档索引](../docs/README.md) |

<details>
<summary>初次阅读时可能遇到的术语</summary>

- **时点一致性（Point-in-time，PIT）：** 只使用决策时已知的信息重建输入。
- **折外预测（Out-of-fold，OOF）：** 对模型拟合／选择所用数据之外的记录生成预测；本项目还要求按时间排序并考虑结果何时成熟可用。
- **冻结模型：** 应用已记录的模型及其变换，不重新拟合或调参。
- **组合目标：** 希望达到的资金配置，与订单、成交和当前持仓分别记录。
- **对账：** 将已提交订单和记录持仓与账户确认状态核对。

</details>
