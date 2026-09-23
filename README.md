# US Tech Quant v21

美股量化研究系统，涵盖 PIT 数据、股票排名、组合模拟、风险分析和前瞻观察。仓库保存代码、配置、测试与文档；数据、结果、缓存和运行状态保存在外部目录。

**常用入口：** [程序与模块地图](docs/PROJECT_MAP.md) · [研究复用表](docs/research/README.md) · [文档目录](docs/README.md) · [演示界面](apps/demo_console/README.md)

## 运行入口

在本地权威仓库 `D:\us-tech-quant` 中执行。路径配置见 [storage_paths.json](config/storage_paths.json)，依赖版本见 [requirements.lock.txt](requirements.lock.txt)。

| 用途 | 入口 |
| --- | --- |
| 展示已有研究结果 | `apps/demo_console/start.ps1 -Port 8504`，然后打开 <http://127.0.0.1:8504/> |
| 查看数据目录元信息 | `python -B -m scripts.storage.manage_data status` |
| 默认合成回归测试 | `python -B -m pytest -q`，从仓库根目录执行 |
| 当前日常研究链 | `scripts/v22/run_v22_044_daily_single_entrypoint_freeze_and_guard_r1.ps1 -Execute` |
| R1E 服务与 Dashboard | [服务入口与执行边界](docs/PROJECT_MAP.md#runtime-entrypoints-and-safe-regression-2026-09-14) |

上表中的 `python` 指 `D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe`。日常研究链和真实服务会使用实际运行环境，执行前按[项目地图](docs/PROJECT_MAP.md#runtime-entrypoints-and-safe-regression-2026-09-14)确认当前指针、配置及任务授权。

## 新研究先查已有工作

1. 先查[研究复用表](docs/research/README.md)，用 `research_inventory query --text` 检索机制关键词，再从[项目地图](docs/PROJECT_MAP.md)定位现有模块、调用方及测试。
2. 使用既有 [research_registry.py](research_registry.py) 查询研究身份及接受状态；注册表位置由 [config/research_registry.json](config/research_registry.json) 指定。
3. 对照已有机制、信息来源、目标期限及评价设计，检查已关闭、暂停、失败的工作。归档或改名不会重置研究身份。
4. 通过现有 `preflight-proposal` 检查后，优先扩展已有实现，并把试验和结论写入既有生命周期记录。

```powershell
& D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe -B -m scripts.maintenance.research_inventory query --repo-root . --text "机制关键词"
& D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe -B research_registry.py current
& D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe -B research_registry.py query --alias "已有名称或别名"
& D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe -B research_registry.py preflight-proposal --proposal <提案JSON路径>
```

注册表的接受快照、别名、清单和冻结身份决定研究身份状态。[研究复用表](docs/research/README.md)和原有 `A2_RESEARCH_REGISTRY_CURRENT/research_branch_registry_current.csv` 是合并注册表元信息与旧表内容的检索视图，由 `scripts/maintenance/research_inventory.py` 刷新；原表保留在外部结果根目录。

**身份状态与旧研究结论分开保留。** 旧表中的关闭原因、负面结论不会被新身份状态覆盖；不一致时标记待复核，不自动重启研究。查询未命中仍需检查未登记源码并通过提案检查，避免换名重复已经完成的工作。

## 目录

| 目录 | 内容 |
| --- | --- |
| `apps/` | 展示界面 |
| `scripts/storage/`、`scripts/common/` | 数据目录、统一读取与路径工具 |
| `scripts/maintenance/` | 维护、检查及 Harness |
| `scripts/research/` | 按研究类别组织的实现 |
| `scripts/v21/`、`scripts/v22/` | 仍有调用或契约绑定的运行入口与历史研究实现 |
| `fast3/` 至 `fast6/` | 各研究系列及其既有契约 |
| `config/`、`configs/` | 紧凑配置与控制元信息 |
| `tests/` 及配套 `test_*.py` | 合成与专项验证 |
| `docs/` | 使用说明、项目地图与研究契约 |
| `archive/research/legacy/scripts/` | 不被当前运行链依赖的 V18、V20 历史实现；按原相对目录收纳 |

根目录中部分脚本有固定路径或哈希绑定，保留原因见 [ROOT_AUTHORITY.md](ROOT_AUTHORITY.md)。版本号、文件年龄和目录位置不代表研究已被采用或可以删除。

项目默认用于研究。回测或界面展示不授权实盘交易；训练与选择遵守 `< 2026-01-01` 的既有边界，已暴露的 A2 2026+ 证据不能重新视为独立留出集。开发前阅读 [AGENTS.md](AGENTS.md)、[项目地图](docs/PROJECT_MAP.md)和 [Anti-Bloat 规则](docs/governance/ANTI_BLOAT_POLICY.md)。

完整技术介绍及详细命令保留在 [technical-overview.md](docs/technical-overview.md)。
