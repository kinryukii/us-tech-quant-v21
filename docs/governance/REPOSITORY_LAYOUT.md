# 仓库布局

根目录保留项目说明、开发约定、依赖与测试配置。程序实现、测试和研究资料按职责放入子目录；不生成根目录兼容副本。

| 用途 | 位置 |
| --- | --- |
| 研究身份、别名和重复提案检查 | [注册表实现](../../scripts/maintenance/research_registry.py)、[位置配置](../../config/research_registry.json) |
| 试验记录、完成回执与研究生命周期 | [生命周期实现](../../scripts/maintenance/prospective_research_lifecycle.py) |
| 治理合成测试 | [tests/governance/](../../tests/governance/) |
| 研究复用查询与旧表刷新 | [research_inventory.py](../../scripts/maintenance/research_inventory.py) |
| 按领域保留的研究实现 | [scripts/research/](../../scripts/research/) |
| FAST3 使用的 PIT 基础实现 | [a2_free_pit_foundation_r1.py](../../scripts/research/a2/data/a2_free_pit_foundation_r1.py) |
| 当前日常运行链及仍被调用的组件 | [scripts/v21/](../../scripts/v21/)、[scripts/v22/](../../scripts/v22/)；入口以[项目地图](../PROJECT_MAP.md)为准 |
| FAST3 研究与兼容入口 | [fast3/README.md](../../fast3/README.md)、[fast3/compatibility/](../../fast3/compatibility/) |
| 当前数据采集依赖 | [fast6/](../../fast6/) |
| 已删除源码查重与 Git 恢复信息 | [retired_sources.json](../research/retired_sources.json) |

注册表仍是原来的身份与接受状态来源。新位置的命令为：

```powershell
python -B -m scripts.maintenance.research_inventory query --repo-root . --text "机制关键词"
python -B -m scripts.maintenance.research_registry current
python -B -m scripts.maintenance.research_registry preflight-proposal --proposal <proposal.json>
```

从仓库根目录执行；`python` 使用开发约定中的外部解释器。新 checkout 和工作树直接使用这些路径，无需初始化根目录别名。

本次清理移除了当前程序不依赖的旧研究实现、测试和重复启动入口，也移除了原 `archive/research/` 源码副本及退役的 FAST4/FAST5 目录。仍被运行链调用的旧代码继续保留；是否退役取决于调用和契约检查，不取决于版本号。

[源码恢复索引](../research/retired_sources.json)只记录文件路径、哈希与[整理前提交 `3d0783a8`](https://github.com/kinryukii/us-tech-quant-v21/tree/3d0783a8c864552273394358268292f6d389e99b)中的恢复位置。它参与查重，不另设研究身份、状态或科学结论。必要时按索引在独立 checkout 中恢复对应版本，再核对适用契约和依赖；不要因找不到旧文件就重新实现同一研究。

[研究复用表](../research/README.md)继续保留旧结论、别名与接受注册表的派生信息。历史冻结引用、注册表接受状态和外部研究记录不因目录清理而改写；删除源码不代表研究重新开放。外部数据、结果、运行状态及绑定到其他 worktree 的冻结源码保持原有归属。
