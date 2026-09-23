# 文档目录

按任务选择入口；研究身份和接受状态以既有注册表、清单及冻结记录为准。

## 使用与维护

| 文档 | 用途 |
| --- | --- |
| [项目地图](PROJECT_MAP.md) | 当前模块、运行入口、研究边界与复用位置 |
| [完整技术介绍](technical-overview.md) | 原三语技术介绍、架构、验证证据与快速查看命令 |
| [数据层](DATA_LAYER.md) | 数据目录、统一读取、来源及采集流程 |
| [存储布局](STORAGE_LAYOUT.md) | 本地代码与外部数据、结果、缓存的分工 |
| [仓库布局](governance/REPOSITORY_LAYOUT.md) | 代码、测试、治理入口与历史源码恢复位置 |
| [日常链说明](DAILY_CHAIN_RUNBOOK.md) | 日常链操作；当前入口以项目地图及现有指针为准 |
| [日常存储维护](DAILY_STORAGE_MAINTENANCE.md) | 维护命令与保留边界 |
| [Moomoo 数据说明](DATA_SOURCE_MOOMOO_README.md) | 数据来源与读取约定 |
| [演示界面](../apps/demo_console/README.md) | 展示范围、数据来源及启动方式 |

## 研究复用与规则

| 入口 | 用途 |
| --- | --- |
| [研究复用表](research/README.md) | 按现有注册表生成的研究身份、别名与复用导航 |
| [研究注册表实现](../scripts/maintenance/research_registry.py) / [位置配置](../config/research_registry.json) | 查询身份、别名、接受快照及新提案重复检查 |
| [研究视图维护](../scripts/maintenance/research_inventory.py) | 查询并刷新上述视图及外部旧表 `A2_RESEARCH_REGISTRY_CURRENT/research_branch_registry_current.csv` |
| [研究生命周期](../scripts/maintenance/prospective_research_lifecycle.py) | 复用现有试验、冻结与回执机制 |
| [已删除源码索引](research/retired_sources.json) | 按旧路径和文件名查重，定位精确 Git 恢复提交；不另设研究状态 |
| [V21 系统表](V21_ACTIVE_SYSTEM_REGISTRY.md) | 既有组件导航；状态需结合当前链和注册表确认 |
| [research_governance/](research_governance/) | 按研究领域维护的契约与历史任务记录 |
| [Anti-Bloat 规则](governance/ANTI_BLOAT_POLICY.md) | 代码复用、存储、归档及删除边界 |

新任务先查研究身份、别名及已关闭/暂停结论，再查调用方、测试和适用契约。能够复用时扩展原实现；导航表和 Git 恢复索引不另建研究状态来源。身份状态与旧科学结论分列保留，冲突标记待复核，不自动覆盖或重启研究。

## 历史资料

[V20 文档](v20/)和 [FAST3 阶段文档](fast3/)保存既有开发记录；FAST3 当前目录入口见[项目说明](../fast3/README.md)。不被当前运行链依赖的历史源码已从工作树移除，查重和恢复使用[源码索引](research/retired_sources.json)及[整理前的 Git 提交](https://github.com/kinryukii/us-tech-quant-v21/tree/3d0783a8c864552273394358268292f6d389e99b)。历史任务说明不自动成为当前执行授权；是否仍适用，以[项目地图](PROJECT_MAP.md)指向的状态、注册表和契约为准。

数据、回测、冻结结果及运行日志保存在 [storage_paths.json](../config/storage_paths.json) 指定的外部目录。查找历史工作时通过既有注册表、清单或索引定位，避免将结果副本重新堆入仓库。
