# US Tech Quant v21

**Research-first quantitative ranking, point-in-time universe reconstruction, machine-learning validation, and guarded signal infrastructure for U.S. equities and ETFs.**

US Tech Quant v21 is a Windows-first quantitative research platform built primarily with **Python** and **PowerShell**.

The project has evolved from a daily multi-factor ranking pipeline into a broader research system covering:

* daily cross-sectional stock ranking
* point-in-time 13F universe reconstruction
* A / A2 ranking-model research
* nonlinear machine-learning challengers
* stock-level risk modeling
* FAST3 multi-stage predictive research
* prospective / holdout validation
* Moomoo historical-data acquisition
* corporate-action accounting
* reproducibility and lineage controls
* repository anti-bloat governance
* guarded research execution

The system is designed for **reproducible quantitative research**.

It is **not** a production trading system and does not automatically place live orders.

> ### Version convention
>
> The public project name remains **US Tech Quant v21**.
>
> Internal modules use identifiers such as `V22.xxx`, `A2 R6`, `FAST3 R35`, and similar research-stage labels.
>
> These are internal experiment and pipeline revisions. They do not indicate a change to the public project version.

---

# Architecture

At a high level, the current research stack is:

```text
                         External Market / Filing Data
                                   │
                 ┌─────────────────┴─────────────────┐
                 │                                   │
           Moomoo Market Data                    SEC 13F Data
                 │                                   │
                 ↓                                   ↓
       Historical Data Layer              PIT 13F Reconstruction
                 │                                   │
                 └───────────────┬───────────────────┘
                                 ↓
                       Point-in-Time Universe
                                 ↓
                       Feature Engineering
                                 ↓
                    Cross-Sectional Models
                    ┌────────────┴────────────┐
                    │                         │
                  A / A2                    FAST3
                    │                         │
                    ↓                         ↓
             Ranking / Alpha           Predictive Research
                    │                         │
                    └────────────┬────────────┘
                                 ↓
                       Risk / Translation Layer
                                 ↓
                        OOS / Holdout Validation
                                 ↓
                       Audited Research Outputs
```

A separate governance layer controls:

```text
training-date isolation
PIT integrity
repository writes
storage boundaries
anti-bloat limits
frozen artifacts
broker-action permissions
```

---

# Current Research Status

The repository now contains several distinct research systems.

| Component                 | Current status                                       |
| ------------------------- | ---------------------------------------------------- |
| Daily ABCDE ranking chain | Frozen guarded daily workflow                        |
| A / A2 baseline           | Frozen clean historical research baseline            |
| 13F universe              | Authoritative dynamic PIT reconstruction             |
| A2 nonlinear challengers  | Pre-2026 research infrastructure                     |
| A2 stock-risk models      | Predictive and prospective research                  |
| FAST3                     | Multi-stage predictive / economic research framework |
| 2026 observations         | Holdout / prospective evaluation only                |
| Live broker execution     | Disabled by default                                  |
| Repository governance     | Anti-bloat and write guards active                   |

The project intentionally distinguishes:

```text
research evidence
≠
prospective validation
≠
deployment authorization
≠
live trading authorization
```

A model performing well in historical research does not automatically become an approved trading model.

---

# Daily Research Pipeline

The stable daily research entry point remains:

```powershell
.\scripts\v22\run_v22_044_daily_single_entrypoint_freeze_and_guard_r1.ps1 -Execute
```

A successful guarded run returns:

```text
PASS_V22_044_DAILY_SINGLE_ENTRYPOINT_FROZEN
```

The daily chain handles:

* market-data refresh
* RAW / adjusted-data validation
* universe validation
* feature generation
* ABCDE scoring
* Top-20 ranking
* score preservation
* same-date comparability
* machine-readable audit output
* fail-closed acceptance gates

Outputs are rejected when required data or contracts are incomplete.

---

# ABCDE Ranking Framework

The original daily architecture remains available as a multi-strategy control framework.

Representative strategy families include:

| Strategy            | Role                                  |
| ------------------- | ------------------------------------- |
| `A1_CONTROL`        | Multi-factor control                  |
| `B_STATIC_MOMENTUM` | Momentum-oriented ranking             |
| `C`                 | Alternative factor weighting          |
| `D`                 | Diversified / defensive configuration |
| `E_R1`              | Experimental research configuration   |

Each ranking contains information such as:

```text
signal_date
ticker
rank
raw_score
strategy
data_date
diagnostics
```

Top-20 outputs preserve both rank and raw score so that changes in ranking magnitude remain observable.

---

# A / A2 Research Line

A and A2 form the main cross-sectional ranking research line.

The current clean baseline includes:

* historical PIT candidate-universe reconstruction
* quarterly 13F universe transitions
* corporate-action-aware economic accounting
* Top-20 portfolio translation
* transaction-cost accounting
* deterministic model vintages
* reproducibility manifests
* frozen baseline verification

The A/A2 clean baseline is treated as a **frozen research baseline** rather than continuously rewritten whenever a new challenger is tested.

New models are evaluated against the frozen baseline instead of silently changing the benchmark.

---

# Authoritative 13F Point-in-Time Universe

The current authoritative A/A2 historical universe uses a fixed set of **24 stable institutional managers**.

The active configuration is:

```text
config/v22/authoritative_24_manager_master_r1.json
```

An older 30-manager configuration is retained for legacy research compatibility but is not the authoritative historical universe.

## Quarterly construction rule

For each manager:

```text
maximum qualifying holdings per quarter = Top 100
```

After combining managers:

```text
deduplicate securities
↓
apply deterministic auditable truncation if required
↓
final universe size <= 900 securities
```

## PIT activation rule

A new quarterly universe does **not** become active immediately when the first filing appears.

The activation process is:

```text
wait for all authoritative managers
        ↓
latest actual filing timestamp
        ↓
+ 5 U.S. equity trading sessions
        ↓
new quarterly universe becomes active
```

Before that activation date, the previous valid quarterly universe remains in force.

This prevents future filing information from being applied retroactively.

---

# Historical Eligibility

PIT membership and market-data availability are treated as separate concepts.

A security may legitimately enter a historical 13F universe while lacking sufficient historical price coverage.

In that case:

```text
PIT universe membership = valid
historical test eligibility = false
```

The security may therefore be excluded from a specific historical test window.

Future data availability must never be used to retroactively change past eligibility.

---

# 2026 Isolation Policy

One of the most important research contracts in the repository is the temporal training boundary.

For current research:

```text
TRAINING_DATE < 2026-01-01
```

Data from 2026 and later may be collected and stored, but may only be used for:

* frozen inference
* holdout evaluation
* prospective shadow evaluation
* diagnostics that do not modify the fitted system

2026 observations must not participate in:

* model fitting
* hyperparameter optimization
* supervised feature selection
* threshold optimization
* economic-rule selection
* model selection

Relevant pipelines include explicit hard assertions around training dates.

The current audited FAST3 training path has:

```text
2026 fit rows = 0
```

This boundary exists to preserve genuinely out-of-sample evidence.

---

# A2 Nonlinear Modeling

A2 research now includes nonlinear cross-sectional model challengers in addition to the original fixed-factor formulation.

The repository contains infrastructure for:

* nonlinear alpha baselines
* PIT-universe recovery
* historical eligibility reconstruction
* cross-sectional modeling
* execution-contract freezing
* signal-lag analysis
* ranking-objective challengers
* portfolio translation
* execution-price reconstruction

Machine-learning challengers are evaluated against the frozen A2 baseline rather than replacing it automatically.

A better pooled score is not sufficient for adoption if performance is:

* unstable across folds
* dominated by one period
* dependent on weak common support
* economically inconsistent
* insufficiently prospective

---

# Stock-Level Risk Modeling

The A2 research line also contains a dedicated stock-level risk program.

Rather than predicting only expected returns, the risk models investigate the probability and severity of adverse outcomes.

Research stages include:

```text
R1–R5     early risk-model experiments
R6        bad-outcome asymmetry classifier
R6E       economic exposure study
R7–R9     alternative classification / severity designs
R10/R11   frozen prospective evaluation
```

The current research evidence suggests that cross-sectional downside-risk prediction is possible, but the system deliberately separates:

```text
predictive usefulness
from
economic deployment approval
```

Risk models may therefore remain research-only even when AUROC or event concentration improves.

---

# FAST3 Research Framework

FAST3 is a separate multi-stage research framework for predictive and economic signal discovery.

The repository now contains research stages covering:

* event-conditioned analysis
* factor cartography
* economic target design
* downside decomposition
* liquidity and volume information
* payoff decomposition
* conditional gain / loss magnitude
* probability calibration
* expected-payoff ordering
* prospective tail-risk validation
* independent economic-target research

Representative stages include:

```text
R28
R30–R33
R34
R35
R36
R37–R43
```

The FAST3 design philosophy is:

```text
predictive signal
        ↓
out-of-fold validation
        ↓
economic translation
        ↓
frozen evaluation
        ↓
prospective evidence
```

A predictive model is not treated as economically useful simply because classification metrics improve.

---

# Option Context and Risk Overlay Research

The repository also contains an isolated FAST3 options-research layer.

Current modules include:

```text
fast3/src/fast3/options/
```

with functionality for:

* option data acquisition
* option-context features
* option shadow research
* risk overlays

These modules remain part of research infrastructure.

They do not authorize live option execution.

---

# Corporate Actions and Economic Accounting

The project contains explicit handling and forensic checks for:

* stock splits
* reverse splits
* price adjustments
* execution-price mapping
* NAV accounting
* turnover
* transaction cost
* forced exits
* corporate-action transitions

Economic results are accepted only when accounting identities and execution mappings pass validation.

---

# Validation Philosophy

The project uses several validation layers.

## Temporal folds

Models are evaluated across multiple historical periods rather than a single train/test split.

## Out-of-fold predictions

OOF predictions are preferred when comparing model quality and downstream economic translation.

## Holdout evaluation

2026 observations are currently isolated from training and reserved for evaluation.

## Prospective shadow evaluation

Frozen models may continue generating predictions after model selection has stopped.

## Common-support analysis

When two models depend on different data coverage, comparisons distinguish:

```text
full-universe comparison
```

from:

```text
matched common-support comparison
```

This prevents data availability from being mistaken for model superiority.

---

# Research Metrics

Depending on the experiment, evaluation may include:

### Predictive metrics

```text
Information Coefficient
Spearman correlation
AUROC
Average Precision
NDCG@20
top-decile lift
event capture rate
```

### Economic metrics

```text
CAGR
annualized volatility
Sharpe ratio
Sortino ratio
Calmar ratio
maximum drawdown
Profit Factor
turnover
transaction costs
NAV
```

Metrics are never interpreted in isolation.

For example:

```text
higher CAGR + much larger drawdown
```

may not represent an improvement in risk-adjusted quality.

---

# Moomoo Data Layer

Moomoo JP is used as an important source for market-data acquisition and historical backfill.

Historical data engineering is deliberately separated from model research.

The design supports:

* historical-security quota management
* canonical rebuilds
* RAW / adjusted data
* daily incremental refresh
* historical backlog completion
* data-source policy enforcement

Historical backfill does not automatically authorize the newly collected data for model training.

Data availability and research authorization remain separate controls.

---

# Storage Architecture

Large data and generated results are intentionally kept outside the Git repository.

Typical layout:

```text
Repository:
D:\us-tech-quant

External results:
D:\us-tech-quant-results

External runtime environments:
D:\us-tech-quant-envs

Market-data root:
configured through the canonical storage configuration
```

Relevant configuration and helpers include:

```text
config/storage_paths.json
scripts/common/storage_paths.py
scripts/common/storage_paths.ps1
```

Canonical market-data directories are treated as read-only where required by governance.

---

# Anti-Bloat Governance

The repository enforces explicit storage limits.

Current policy:

```text
Preferred repository size: <= 150 MB
Required upper target:     <= 300 MB
Hard failure threshold:    >= 500 MB
```

Repository-local Python virtual environments are forbidden:

```text
REPO_LOCAL_VENV_FORBIDDEN = true
```

Therefore, do **not** create:

```text
D:\us-tech-quant\.venv
```

Use an external environment instead.

Example architecture:

```text
D:\us-tech-quant-envs\us-tech-quant-main
```

The anti-bloat system distinguishes between:

* tracked source
* legitimate reference metadata
* generated results
* local caches
* external data
* grandfathered legacy artifacts
* newly created files

New files do not automatically inherit legacy grandfathering exceptions.

---

# Repository Write Governance

The project contains fail-closed repository-write controls.

These are designed to reduce accidental:

* writes into canonical data roots
* generated-result commits
* repository bloat
* runtime pollution
* silent policy weakening

Policy uncertainty is treated as a failure rather than silently accepted.

---

# Repository Structure

A simplified current structure is:

```text
us-tech-quant/
│
├─ config/
│  ├─ fast3/
│  ├─ v21/
│  └─ v22/
│
├─ configs/
│  ├─ anti_bloat_policy.toml
│  ├─ v21/
│  └─ v22/
│
├─ docs/
│  └─ governance/
│
├─ fast3/
│  ├─ configs/
│  ├─ docs/
│  ├─ scripts/
│  │  ├─ audit/
│  │  └─ run/
│  ├─ src/
│  │  └─ fast3/
│  └─ tests/
│
├─ scripts/
│  ├─ common/
│  ├─ fast3/
│  ├─ maintenance/
│  ├─ v21/
│  └─ v22/
│
└─ README.md
```

Large generated artifacts are intentionally excluded.

Typical exclusions include:

```text
results/
outputs/
__pycache__/
.pytest_cache/
*.log
*.parquet
runtime environments
large market datasets
generated backtest artifacts
```

---

# Environment

The project is primarily developed on Windows.

Recommended environment:

```text
Windows 10 / Windows 11
PowerShell 5.1+
Python 3.12
Git
```

Do not create a virtual environment inside the repository.

Instead, activate a compatible external environment.

Example:

```powershell
& D:\us-tech-quant-envs\us-tech-quant-main\Scripts\Activate.ps1
```

Then:

```powershell
Set-Location D:\us-tech-quant
```

---

# Quick Start

Clone the repository:

```powershell
git clone https://github.com/kinryukii/us-tech-quant-v21.git
cd us-tech-quant-v21
```

Configure external storage and a compatible Python runtime.

Allow local PowerShell execution for the current process if required:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Run the guarded daily research chain:

```powershell
.\scripts\v22\run_v22_044_daily_single_entrypoint_freeze_and_guard_r1.ps1 -Execute
```

Check repository state:

```powershell
git status
```

---

# Reproducibility

Research artifacts should preserve enough information to independently reconstruct the experiment.

Important metadata include:

* Git commit
* strategy configuration
* model configuration
* feature definition
* universe definition
* PIT activation schedule
* training date range
* evaluation date range
* random seed
* transaction-cost assumptions
* benchmark
* fold definition
* output manifest
* frozen artifact hashes

Frozen artifacts may additionally preserve SHA-256 manifests.

A result without its data lineage, universe definition, model version, and temporal boundaries should not be treated as fully reproducible.

---

# Failure-Closed Research

A central engineering principle of this repository is:

```text
unknown != pass
```

If evidence is incomplete, the preferred result is:

```text
STOP
FAIL_CLOSED
INSUFFICIENT_EVIDENCE
ENVIRONMENT_BLOCKED
```

rather than manufacturing an apparently successful result.

Examples include:

* missing PIT source evidence
* incomplete historical coverage
* unavailable frozen artifacts
* permission failures
* inconsistent execution mappings
* training-boundary violations
* repository-accounting uncertainty

This philosophy is intentional.

---

# Safety and Execution Policy

The repository remains research-first.

By default:

```text
broker_action_allowed = False
official_adoption_allowed = False
```

Research output must not automatically trigger:

* live orders
* broker actions
* portfolio reallocation
* capital deployment
* formal model adoption

Any future execution system should remain isolated behind:

* explicit configuration
* independent risk controls
* paper / shadow validation
* broker-state validation
* manual authorization
* emergency disable controls

---

# What This Repository Does Not Claim

This project does **not** claim that:

* historical performance guarantees future returns
* the current models are production-ready
* every historical security is perfectly covered
* every model challenger improves the incumbent
* predictive quality automatically produces economic alpha
* 2026 results are training evidence
* a research PASS authorizes live trading

Many experiments intentionally end in rejection or insufficient-evidence classifications.

Those failures are part of the research record.

---

# Known Limitations

Important limitations remain.

They include:

* incomplete historical coverage for some securities
* incomplete delisted-security coverage
* vendor-specific market-data differences
* historical identifier changes
* imperfect historical liquidity reconstruction
* corporate-action edge cases
* simplified market-impact assumptions
* varying common-support coverage across model families
* limited prospective sample sizes
* dependence on external market and filing data
* limited live-execution evidence

The project therefore distinguishes strict PIT evidence from proxy or incomplete historical evidence.

---

# Development Principles

The repository follows several practical rules:

```text
Research before deployment
PIT before performance
OOS before optimization
Audit before adoption
Fail closed on uncertainty
Keep data outside Git
Keep generated results outside source
Preserve frozen baselines
Do not rewrite failed experiments
```

---

# Current Development Direction

Current research priorities include:

* stronger stock-level downside-risk modeling
* nonlinear A2 challengers
* improved common-support evaluation
* factor attribution
* better economic target design
* prospective evidence accumulation
* FAST3 economic alignment
* option-context research
* historical data completion
* improved PIT coverage
* corporate-action integrity
* stronger experiment lineage and reproducibility

Neural-network and other higher-capacity models may be investigated when the available sample size and experimental design justify the additional complexity.

They are not adopted solely because they are more sophisticated.

---

# 中文简介

**US Tech Quant v21** 是一个面向美国股票和 ETF 的研究优先型量化研究平台。

项目目前已经从最初的 ABCDE 每日排名系统发展为包含以下模块的完整研究基础设施：

* A / A2 横截面排名研究
* 24 家机构组成的 authoritative 13F PIT 动态股票池
* 每机构 Top100、合并后最多 900 只股票的历史候选池
* 非线性机器学习 Challenger
* 个股风险预测
* FAST3 多阶段预测与经济验证
* Moomoo 历史数据工程
* 公司行动与 NAV 核算
* 2026 严格样本外隔离
* Anti-Bloat 仓库治理
* Frozen baseline 与 SHA 审计

当前硬性研究原则为：

```text
训练数据 < 2026-01-01
```

2026 年及以后数据只允许用于：

```text
holdout
prospective evaluation
frozen inference
```

不得用于训练、调参或模型选择。

本项目仍然是**研究系统，不是实盘自动交易系统**。

---

# 日本語概要

**US Tech Quant v21** は、米国株式および ETF を対象とする research-first 型の定量研究プラットフォームです。

現在のシステムには以下が含まれます。

* A / A2 クロスセクションランキング
* 24 機関による authoritative 13F point-in-time universe
* 1 機関あたり最大 Top100
* 統合 universe 最大 900 銘柄
* 非線形機械学習 challenger
* 個別株 downside-risk modeling
* FAST3 multi-stage research
* Moomoo historical data engineering
* corporate-action accounting
* 2026 holdout isolation
* anti-bloat governance
* frozen baseline verification

現在の temporal contract は：

```text
training date < 2026-01-01
```

です。

2026 年以降のデータは holdout / prospective evaluation として利用できますが、モデル学習、パラメータ探索、モデル選択には使用しません。

本リポジトリは引き続き**定量リサーチ基盤**であり、自動実売買システムではありません。

---

# Disclaimer

This repository is provided for:

* software engineering research
* quantitative research
* data analysis
* educational purposes

It does not constitute:

* investment advice
* a recommendation to buy or sell securities
* a solicitation to trade
* a guarantee of future performance
* authorization to deploy any strategy with real capital

Backtested and simulated results may be affected by:

* survivorship bias
* look-ahead bias
* data leakage
* missing data
* transaction costs
* liquidity
* market impact
* corporate actions
* model selection
* parameter instability
* vendor differences

Use of this repository and its research outputs is entirely at the user's own risk.

---

# Project

**US Tech Quant v21**

Research-first quantitative ranking, point-in-time universe reconstruction, machine-learning validation, risk modeling, and guarded research infrastructure for U.S. equities and ETFs.
