# US Tech Quant v21

Point-in-time US equity research, portfolio simulation, risk analysis, and audited workflows.

[中文](#中文) · [English](#english) · [日本語](#日本語)

> Research software only. This repository does not authorize live trading, broker execution, or investment decisions.

---

## 中文

### 项目简介

US Tech Quant v21 是一个以可复现性和时间点一致性（point-in-time）为核心的美股量化研究系统，覆盖数据治理、股票排序、组合模拟、风险分析、前瞻观察和审计型研究流程。

仓库只保存轻量代码与控制面。大规模数据、缓存、Python 环境、结果、每日状态和回测产物均存放在 `config/storage_paths.json` 声明的外部目录中。`V22.xxx`、`A2`、`FAST3` 等是内部管线或研究版本标识；项目对外名称仍为 **US Tech Quant v21**。

### 核心能力

- 可追溯的 PIT 数据目录、清单、快照与只读接口
- A2 与 FAST3 研究管线、冻结合约和配套验证
- 股票排序、组合模拟、风险归因与前瞻观察
- 只读 Streamlit 展示控制台
- 失败关闭、证据保留和研究复核机制

### 快速开始

```powershell
# 查看数据目录状态（只读）
Set-Location D:\us-tech-quant
& D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe -B -m scripts.storage.manage_data status

# 启动展示 Demo
& .\apps\demo_console\start.ps1 -Port 8504

# 运行默认回归测试
& D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe -B -m pytest -q
```

Demo 地址：<http://127.0.0.1:8504/?language=%E4%B8%AD%E6%96%87>。它只读取已有研究产物，不训练模型、不重跑策略、不连接券商，也不改写权威数据。

### 目录导航

| 路径 | 用途 |
| --- | --- |
| `apps/demo_console/` | 只读 Streamlit 展示界面 |
| `scripts/storage/` | 数据目录、读取层、快照与显式刷新工具 |
| `scripts/research/` | 当前 A2 与 FAST3 研究实现 |
| `scripts/v21/`, `scripts/v22/` | 兼容入口、运行组件与历史模块 |
| `fast3/`–`fast6/` | 受约束的研究家族及其合约与测试 |
| `tests/` | 合成测试与范围化验证 |
| `docs/` | 架构、数据层、存储和治理文档 |

### 为什么根目录仍有长文件名？

部分 Python 文件、配套测试和 PowerShell 启动器被现有研究合约绑定了精确路径或内容哈希。移动或改名会破坏冻结身份、研究注册表或兼容入口，因此暂时保留在根目录。它们不是新代码的推荐布局；新实现应进入对应的 `scripts/`、`tests/` 或研究目录。详情见 [`ROOT_AUTHORITY.md`](ROOT_AUTHORITY.md)。

### 重要边界

- 默认用途仅限研究；排名、回测、仪表盘和前瞻观察均不构成实盘授权。
- 训练、拟合、校准和模型选择原则上必须使用 `2026-01-01` 之前的信息，除非后续人工批准的合约明确变更边界。
- 2026 年及以后的 A2 证据仅用于评估，不得用作未见留出集或调参输入。
- 缺少 PIT 血缘、可用时间、版本、身份或成熟度证据时，相关结论不可检验。
- 负结果、无增量价值结果和不可检验结果都是有效研究结论，应保留证据。

详细说明：[`项目地图`](docs/PROJECT_MAP.md) · [`数据层`](docs/DATA_LAYER.md) · [`防膨胀规则`](docs/governance/ANTI_BLOAT_POLICY.md)

---

## English

### Overview

US Tech Quant v21 is a reproducibility-first, point-in-time research system for US equities. It covers data governance, stock ranking, portfolio simulation, risk analysis, forward observation, and auditable workflows.

This repository is the lightweight code and control plane. Bulk data, caches, Python environments, results, daily state, and backtests live under the external roots declared in `config/storage_paths.json`. Names such as `V22.xxx`, `A2`, and `FAST3` identify internal revisions; the public project name remains **US Tech Quant v21**.

### Capabilities

- Traceable PIT catalogs, manifests, snapshots, and read-only access
- A2 and FAST3 pipelines with frozen contracts and validation
- Stock ranking, portfolio simulation, risk attribution, and forward observation
- A read-only Streamlit presentation console
- Fail-closed governance, evidence preservation, and reviewable records

### Quick start

```powershell
# Inspect catalog status without acquisition
Set-Location D:\us-tech-quant
& D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe -B -m scripts.storage.manage_data status

# Start the presentation demo
& .\apps\demo_console\start.ps1 -Port 8504

# Run the reviewed default regression suite
& D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe -B -m pytest -q
```

Demo: <http://127.0.0.1:8504/?language=English>. It reads existing research artifacts only; it does not train models, rerun strategies, connect to a broker, or modify authoritative data.

### Repository map

| Path | Purpose |
| --- | --- |
| `apps/demo_console/` | Read-only Streamlit presentation |
| `scripts/storage/` | Catalog, read layer, snapshots, and explicit refresh tools |
| `scripts/research/` | Current A2 and FAST3 implementations |
| `scripts/v21/`, `scripts/v22/` | Compatibility entrypoints, operations, and historical modules |
| `fast3/`–`fast6/` | Bounded research families with contracts and tests |
| `tests/` | Synthetic and scoped verification |
| `docs/` | Architecture, data, storage, and governance documentation |

### Why are long filenames kept in the root?

Some Python modules, paired tests, and PowerShell launchers are bound to exact paths or content hashes by existing research contracts. Moving or renaming them would break frozen identities, registry records, or compatibility entrypoints, so they remain at the repository root for now. They are not the preferred layout for new code; new work belongs in the relevant `scripts/`, `tests/`, or research directory. See [`ROOT_AUTHORITY.md`](ROOT_AUTHORITY.md).

### Research boundaries

- The default posture is research-only; rankings, backtests, dashboards, and forward observations do not authorize live execution.
- Training, fitting, calibration, and model selection must normally use information from before `2026-01-01`, unless a later human-approved contract changes that boundary.
- A2 evidence from 2026 onward is evaluation-only and cannot be reused as a pristine holdout or tuning input.
- Missing PIT lineage, availability, revision, identity, or maturity evidence makes a dependent conclusion untestable.
- Negative, non-incremental, and untestable outcomes are valid research results and their evidence must be preserved.

Read next: [`Project map`](docs/PROJECT_MAP.md) · [`Data layer`](docs/DATA_LAYER.md) · [`Anti-bloat policy`](docs/governance/ANTI_BLOAT_POLICY.md)

---

## 日本語

### 概要

US Tech Quant v21 は、再現性と point-in-time（PIT）整合性を重視した米国株式向けクオンツ・リサーチシステムです。データガバナンス、銘柄ランキング、ポートフォリオ・シミュレーション、リスク分析、フォワード観測、監査可能な研究ワークフローを扱います。

このリポジトリには軽量なコードと制御情報のみを保存します。大規模データ、キャッシュ、Python 環境、実行結果、日次状態、バックテスト成果物は `config/storage_paths.json` で定義された外部ディレクトリに配置します。`V22.xxx`、`A2`、`FAST3` などは内部リビジョンの識別子で、公開名は **US Tech Quant v21** のままです。

### 主な機能

- 追跡可能な PIT カタログ、マニフェスト、スナップショット、読み取り専用アクセス
- 凍結契約と検証を備えた A2 / FAST3 研究パイプライン
- 銘柄ランキング、ポートフォリオ・シミュレーション、リスク寄与分析、フォワード観測
- 読み取り専用の Streamlit デモコンソール
- fail-closed 設計、証拠保存、レビュー可能な研究記録

### クイックスタート

```powershell
# データ取得を行わずにカタログ状態を確認
Set-Location D:\us-tech-quant
& D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe -B -m scripts.storage.manage_data status

# デモを起動
& .\apps\demo_console\start.ps1 -Port 8504

# 標準回帰テストを実行
& D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe -B -m pytest -q
```

デモ：<http://127.0.0.1:8504/?language=%E6%97%A5%E6%9C%AC%E8%AA%9E>。既存の研究成果物を読み取るだけで、モデル学習、戦略の再実行、ブローカー接続、正本データの変更は行いません。

### リポジトリ構成

| パス | 用途 |
| --- | --- |
| `apps/demo_console/` | 読み取り専用 Streamlit デモ |
| `scripts/storage/` | カタログ、読み取り層、スナップショット、明示的な更新ツール |
| `scripts/research/` | 現行の A2 / FAST3 研究実装 |
| `scripts/v21/`, `scripts/v22/` | 互換エントリポイント、運用部品、過去のモジュール |
| `fast3/`–`fast6/` | 契約とテストを持つ限定的な研究系列 |
| `tests/` | 合成テストと範囲を限定した検証 |
| `docs/` | アーキテクチャ、データ、ストレージ、ガバナンス文書 |

### なぜルートに長いファイル名が残っているのか

一部の Python モジュール、対応テスト、PowerShell ランチャーは、既存の研究契約によって正確なパスまたはコンテンツハッシュに固定されています。移動や改名を行うと凍結済み識別子、研究レジストリ、互換エントリポイントが壊れるため、現時点ではルートに残しています。新規コードの推奨配置ではありません。新しい実装は対応する `scripts/`、`tests/`、または研究ディレクトリに追加してください。詳細は [`ROOT_AUTHORITY.md`](ROOT_AUTHORITY.md) を参照してください。

### 研究上の境界

- 既定では研究専用です。ランキング、バックテスト、ダッシュボード、フォワード観測は実取引を許可しません。
- 学習、フィッティング、校正、モデル選択は、後続の人手承認契約で変更されない限り、原則として `2026-01-01` より前の情報を使用します。
- 2026 年以降の A2 証拠は評価専用で、未観測ホールドアウトやチューニング入力として再利用できません。
- PIT 系譜、利用可能時刻、改訂、識別子、成熟度の証拠が不足する場合、依存する結論は検証不能です。
- 否定的結果、追加価値なしの結果、検証不能な結果も有効な研究結果であり、証拠を保存します。

次に読む文書：[`プロジェクトマップ`](docs/PROJECT_MAP.md) · [`データ層`](docs/DATA_LAYER.md) · [`肥大化防止ポリシー`](docs/governance/ANTI_BLOAT_POLICY.md)

---

## License and disclaimer

This software is intended for quantitative research and audit. It does not provide financial advice and does not guarantee investment performance.
