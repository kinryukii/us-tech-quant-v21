# US Tech Quant v21

**Research-first quantitative ranking, validation, and daily signal pipeline for U.S. equities and ETFs.**

US Tech Quant v21 is a Windows-first quantitative research system built with Python and PowerShell. It automates market-data validation, feature generation, multi-strategy stock ranking, historical testing, audit reporting, and guarded daily refresh workflows.

The project is designed for **reproducible research rather than direct trading execution**.

> **Version note**
>
> The public project name remains **US Tech Quant v21**.
> Some internal scripts and pipeline components use higher implementation identifiers such as `V22.xxx`. These identifiers describe internal workflow revisions and do not represent a change to the public release name.

---

## Overview

The system converts raw market data into auditable daily research outputs through a structured pipeline:

```text
Market Data
    ↓
Data Validation
    ↓
Feature Engineering
    ↓
ABCDE Strategy Scoring
    ↓
Cross-Sectional Ranking
    ↓
Same-Date Comparability Checks
    ↓
Top-20 Research Output
    ↓
Historical and Random-Window Validation
```

The current workflow covers more than 300 U.S. equities and ETFs and is designed to answer four practical research questions:

1. Which stocks rank highest under each strategy today?
2. Are all strategy outputs based on the same market date?
3. Do the signals remain effective across different historical periods?
4. Can every result be reproduced and audited from local artifacts?

---

## Core Features

### Daily Research Pipeline

The daily pipeline performs:

* raw and adjusted price refresh
* ticker-universe validation
* missing-data and duplicate checks
* feature construction
* ABCDE strategy scoring
* Top-20 ranking generation
* raw-score preservation
* same-date comparability validation
* summary and audit artifact generation
* hard-gate acceptance or rejection

The current stable daily entry point is:

```powershell
.\scripts\v22\run_v22_044_daily_single_entrypoint_freeze_and_guard_r1.ps1 -Execute
```

A successful run returns:

```text
PASS_V22_044_DAILY_SINGLE_ENTRYPOINT_FROZEN
```

The guard layer prevents incomplete or inconsistent daily outputs from being treated as accepted research results.

---

## ABCDE Strategy Framework

The system produces five independently scored rankings.

| Strategy            | Purpose                                       |
| ------------------- | --------------------------------------------- |
| `A1_CONTROL`        | Baseline multi-factor control strategy        |
| `B_STATIC_MOMENTUM` | Momentum-oriented ranking                     |
| `C`                 | Alternative factor-weight configuration       |
| `D`                 | Diversified or defensive factor configuration |
| `E_R1`              | Experimental research strategy                |

Each strategy produces:

* signal date
* ticker
* rank
* raw score
* normalized research fields
* Top-20 summary
* strategy-level diagnostics

The system preserves the original raw score rather than publishing only the final rank.

Example output:

```text
Rank  Ticker  RawScore
1     AAPL    0.898364
2     PANW    0.884938
3     PYPL    0.883704
```

---

## Factor Architecture

The research framework is organized around six factor families:

```text
Fundamental
Technical
Strategy
Risk
Market Regime
Data Trust
```

Technical inputs may include:

* relative strength
* momentum
* RSI
* KDJ
* Bollinger Bands
* moving averages
* exponential moving averages
* volume behavior
* volatility
* breakout strength
* drawdown characteristics

The final score is constructed from multiple factor families rather than from a single technical indicator.

---

## Same-Date Comparability

A ranking comparison is accepted only when all required strategies use the same canonical market date.

The daily guard checks fields such as:

```text
canonical_latest_date
abcde_latest_date
dram_latest_price_date
same_date_comparable_all_strategies
hard_gate_passed
```

A result is rejected when:

* one strategy is stale
* price data are incomplete
* the ranking date differs across strategies
* required output files are missing
* a child pipeline exits with an error
* integrity checks fail

This prevents rankings from different market dates from being compared as though they were generated simultaneously.

---

## Historical Validation

The project includes several forms of validation.

### Fixed-Period Backtests

Used to evaluate a strategy over a defined historical interval.

### Random-Window Backtests

Random starting dates are used to reduce dependence on a single favorable backtest period.

Supported research horizons include:

```text
20 trading days
60 trading days
120 trading days
252 trading days
504 trading days
```

### Year-Stratified Testing

Windows can be sampled independently within each calendar year to test whether performance is concentrated in a specific market regime.

### Benchmark Comparison

QQQ is used as the primary benchmark for technology-oriented strategy research.

Typical evaluation fields include:

* median return
* median excess return
* probability of beating QQQ
* maximum drawdown
* worst-window return
* turnover
* transaction-cost-adjusted return
* year-by-year stability

---

## Example Portfolio Rule

One researched portfolio rule is:

```text
Enter: ticker reaches Top 5
Exit: ticker falls below Top 10
Maximum holdings: 5
Initial allocation: 20% per slot
Replacement source: current Top 5 only
Rebalancing: disabled between entry and exit
Benchmark: QQQ
Transaction cost: configurable
```

This rule is a research configuration, not a guaranteed or recommended trading strategy.

The repository also contains infrastructure for testing alternative:

* entry thresholds
* exit thresholds
* holding periods
* replacement rules
* turnover controls
* regime filters
* benchmark fallback rules

---

## Audit and Research Integrity

The project emphasizes failure visibility rather than silently producing a result.

Audit checks include:

* duplicated ticker-date rows
* missing price fields
* stale snapshots
* inconsistent strategy dates
* invalid universe membership
* unexpected ticker deletion
* strategy-specific window deletion
* signal leakage risks
* output-file completeness
* frozen-configuration verification
* transaction lifecycle integrity
* forced-exit accounting
* benchmark-window consistency

Where complete historical point-in-time data are unavailable, the limitation is reported rather than hidden.

---

## Quick Start

### Requirements

* Windows 10 or Windows 11
* PowerShell 5.1 or later
* Python 3.10 or later
* Git
* local market-data source or compatible cached dataset

### Clone the Repository

```powershell
git clone https://github.com/kinryukii/us-tech-quant-v21.git
cd us-tech-quant-v21
```

### Create a Virtual Environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Install project dependencies when a requirements file is available:

```powershell
pip install -r requirements.txt
```

### Allow Local PowerShell Scripts

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### Run the Daily Research Chain

```powershell
.\scripts\v22\run_v22_044_daily_single_entrypoint_freeze_and_guard_r1.ps1 -Execute
```

### Check Repository Status

```powershell
git status
```

---

## Repository Structure

A simplified project layout:

```text
us-tech-quant-v21/
├─ scripts/
│  ├─ v21/
│  └─ v22/
│     ├─ daily pipeline entry points
│     ├─ ranking and validation modules
│     ├─ random-window backtests
│     ├─ annual stability diagnostics
│     └─ regression tests
├─ config/
│  └─ strategy and runtime configuration
├─ docs/
│  └─ methodology and research notes
├─ tests/
│  └─ validation and regression tests
└─ README.md
```

Large datasets, generated outputs, logs, virtual environments, and local caches are intentionally excluded from Git.

Typical excluded content includes:

```text
data/
outputs/
results/
.venv/
__pycache__/
*.log
*.parquet
```

---

## Data Storage

The repository is designed to separate source code from large research data.

Recommended structure:

```text
Project code:
D:\us-tech-quant

Market data:
D:\us-tech-quant-data

Backtest and archived results:
D:\us-tech-quant-results
```

This separation provides:

* a smaller Git repository
* faster commits and cloning
* independent backtest result directories
* reduced risk of accidentally publishing proprietary or large datasets
* clearer separation between code, data, and generated research artifacts

---

## Reproducibility

For reproducible research, each run should preserve:

* strategy configuration
* ticker universe
* signal date
* data date
* random seed
* transaction-cost assumptions
* benchmark series
* test-window manifest
* summary JSON
* ranking CSV
* integrity diagnostics

Randomized tests should always use an explicitly recorded seed.

Example:

```text
MASTER_SEED=2026071604
```

A result without its configuration, seed, date range, and universe definition should not be treated as independently reproducible.

---

## Current Research Status

The current system can:

* run the daily ABCDE ranking workflow
* generate five same-date-comparable strategy rankings
* print Top-20 tickers with raw scores
* maintain local historical price caches
* run fixed and random-window backtests
* compare strategy performance with QQQ
* test annual stability
* measure turnover and drawdown
* reject incomplete daily runs
* preserve machine-readable audit summaries

The research results also show that a ranking signal can perform differently across years and market regimes. Therefore, the project does not treat a strong aggregate backtest as sufficient evidence of a robust strategy.

---

## Known Limitations

The public repository should not be interpreted as a complete institutional-grade point-in-time research platform.

Current limitations may include:

* incomplete historical index membership
* survivorship-bias risk
* incomplete delisted-security coverage
* limited historical publication-date fundamentals
* incomplete historical corporate-action metadata
* dependence on local data availability
* broker or vendor-specific data differences
* simplified transaction-cost and liquidity assumptions
* limited live-execution validation

Historical proxy rankings must be distinguished from rankings reconstructed using complete point-in-time data.

---

## Safety and Execution Policy

This repository is research-first.

By default:

```text
broker_action_allowed = False
official_adoption_allowed = False
```

Research output must not automatically trigger:

* live orders
* portfolio reallocation
* broker actions
* official strategy adoption

Any future execution layer should remain isolated behind explicit configuration, additional validation, and manual approval.

---

## Roadmap

Planned research directions include:

* stronger point-in-time data support
* historical universe reconstruction
* delisted-security coverage
* improved fundamental-data lineage
* walk-forward validation
* strategy ensemble analysis
* factor-decay measurement
* market-regime attribution
* turnover-aware portfolio construction
* transaction-cost stress testing
* paper-trading isolation
* automated PDF research reports
* multi-agent research workflows

---

## Disclaimer

This repository is provided for software engineering, quantitative research, and educational purposes only.

It does not constitute:

* investment advice
* a solicitation to trade
* a guarantee of future performance
* a production-ready trading system

Backtested or simulated performance does not represent actual trading results. Historical results may be affected by data quality, survivorship bias, look-ahead bias, market impact, liquidity constraints, transaction costs, and implementation assumptions.

Use the software and research outputs at your own risk.

---

## Project

**US Tech Quant v21**

Quantitative ranking, validation, backtesting, and guarded daily research infrastructure for U.S. equities and ETFs.
