# US Tech Quant Research System

A research-first quantitative ranking and strategy evaluation system for U.S. technology, semiconductor, DRAM, ETF, and related equity universes.

This repository is designed for **research, audit, ranking comparison, factor engineering, and forward validation**.
It is **not** a live trading bot and does **not** authorize broker execution by default.

---

## Current Status

**Current major version:** V21
**Current project mode:** Research-only
**Current data mode:** Moomoo local-cache-first
**Broker action:** Disabled unless explicitly approved
**Official strategy adoption:** Blocked unless all governance gates pass

Latest verified repair state:

```text
V21.264 final_status = PASS_V21_264_KNOWN_FAILURE_GROUPS_REPAIRED
final_decision = KNOWN_FAILURE_GROUPS_REPAIRED_READY_FOR_TARGETED_COMMIT_REVIEW
repaired_group_count = 4
failed_group_count = 0
```

Latest clean-worktree verification:

```text
V21.262 final_status = PASS_V21_262_GIT_WORKTREE_TRIAGE_READY
dirty_total_count = 0
tracked_deletion_count = 0
tracked_modification_count = 0
untracked_count = 0
staged_count = 0
highest_risk_class = LOW
```

Latest remaining-failure quarantine state:

```text
V21.263 final_status = PASS_V21_263_REMAINING_FAILURES_QUARANTINED
remaining_untracked_count = 0
observed_failed_file_count = 0
unexpected_untracked_count = 0
blocked_from_commit_count = 0
```

Latest known commit:

```text
23adfd4366eae5742f07469cf835d0067198eba2
Repair known failure groups and add V21.264 repair audit
```

---

## Project Objective

The system aims to build a strict research pipeline for:

1. Daily market data refresh and validation.
2. Factor panel construction.
3. Strategy ranking generation.
4. Random as-of backtesting.
5. Forward return tracking.
6. Strategy-switch governance.
7. Research-only trade-plan generation.
8. Retention, cache, and output safety audits.

The system intentionally separates:

```text
research signal
forward validation
strategy comparison
governance decision
broker execution
```

No ranking, factor weight, or trade plan should be treated as official unless the corresponding governance gates explicitly allow it.

---

## Core Principles

### 1. Research First

All current outputs are research artifacts.
The system can generate rankings, scores, strategy comparisons, and trade-plan references, but these are not automatic trading instructions.

### 2. Point-in-Time Discipline

The system prioritizes PIT-style validation and avoids obvious look-ahead leakage.
Forward evaluation, random as-of tests, and maturity checks are used before promoting any strategy.

### 3. Moomoo Local Cache First

The current daily chain is designed around local Moomoo cache usage.
External refreshes, Yahoo/yfinance usage, and broker-side operations are not part of the default safe path unless explicitly wired and approved.

### 4. No Broker Action by Default

The system includes explicit gates:

```text
broker_action_allowed = false
official_adoption_allowed = false
factor_promotion_allowed = false
```

These gates are intentional and should not be bypassed casually.

### 5. Retention and Cleanup Safety

Large artifacts, cache files, raw outputs, quarantine files, and historical research outputs are protected by retention audits.
Deletion and cleanup scripts must verify path class, hash, and external copy status before removing files.

---

## Current Accepted Daily Entrypoint

The current accepted daily research entrypoint is:

```powershell
.\scripts\v21\run_v21_256_daily_chain_master_wrapper_with_context_r1.ps1 -Execute
```

This entrypoint was registered by:

```text
V21.259_DAILY_RESEARCH_ENTRYPOINT_REGISTRY_R1
```

Status:

```text
final_status = PARTIAL_PASS_V21_259_ENTRYPOINT_REGISTERED_WITH_RETENTION_OBSERVATION
accepted_entrypoint_name = V21.256_DAILY_CHAIN_MASTER_WRAPPER_WITH_CONTEXT_R1
entrypoint_status = ACCEPTED_WITH_RETENTION_OBSERVATION
```

---

## Recommended Daily Workflow

Run from the repository root:

```powershell
cd D:\us-tech-quant
.\.venv\Scripts\python.exe --version
.\scripts\v21\run_v21_256_daily_chain_master_wrapper_with_context_r1.ps1 -Execute
```

After the run, inspect the generated summary files under:

```text
outputs/v21/
```

Typical post-run checks:

```powershell
git status --short
```

Do not commit blindly if new large outputs, cache files, quarantine artifacts, or unexpected raw data appear.

---

## Repository Layout

Typical structure:

```text
.
├── scripts/
│   └── v21/
│       ├── run_v21_*.ps1
│       ├── v21_*.py
│       └── test_v21_*.py
│
├── outputs/
│   └── v21/
│       ├── V21.*_*/
│       └── summary / audit / ranking / validation artifacts
│
├── docs/
│   └── optional documentation and reports
│
├── tests/
│   └── optional shared tests
│
└── README.md
```

External cache root, when enabled locally:

```text
D:\us-tech-quant-cache
```

The external cache is not meant to be committed to GitHub.

---

## Main System Modules

### 1. Data and Cache Layer

The cache architecture was formalized in:

```text
V21.223_LOCAL_CACHE_ARCHITECTURE_AND_IO_ROUTER
```

Purpose:

* Separate repository code from large market-data artifacts.
* Route large files to external cache.
* Keep repo outputs compact when possible.
* Maintain pointer manifests for externally stored artifacts.
* Reduce accidental Git bloat.

Default cache root:

```text
D:\us-tech-quant-cache
```

---

### 2. Moomoo Canonical Data Layer

The system uses Moomoo-derived local OHLCV data as the current preferred source.

Recent canonical Moomoo chain status included:

```text
qfq_success_count = 315
raw_success_count = 315
canonical_latest_date = 2026-07-01 or later depending on local refresh
```

The current design favors completed market dates and avoids treating an open trading session as a finalized daily bar.

---

### 3. Technical and Forward Panel Builder

Implemented in:

```text
V21.246_TECHNICAL_AND_FORWARD_PANEL_BUILD_FROM_MOOMOO_CACHE_R1
```

Purpose:

* Build technical indicators from local Moomoo cache.
* Generate forward-return panels.
* Support PIT-lite effectiveness audits.

Key indicator families include:

```text
RSI
KDJ
MACD
Bollinger Bands
MA20 / MA50
EMA
Volume
Volatility
Momentum
Relative strength
Breakout
Pullback
```

Latest known build status:

```text
final_status = PARTIAL_PASS_V21_246_TECHNICAL_FORWARD_PANEL_READY_WITH_WARNINGS
provider = MOOMOO
usable_ticker_count = 328
technical_indicator_count = 27
```

---

### 4. Technical Subfactor Effectiveness Audit

Implemented in:

```text
V21.247_TECHNICAL_SUBFACTOR_EFFECTIVENESS_PIT_LITE_AUDIT
```

Purpose:

* Evaluate technical indicators against future return horizons.
* Check IC and bucket behavior.
* Identify whether technical subfactors deserve promotion.

Latest known result:

```text
final_status = PARTIAL_PASS_V21_247_TECHNICAL_EFFECTIVENESS_SIGNAL_MIXED
technical_indicator_count = 27
tested_indicator_count = 27
candidate_for_v21_248_count = 0
official_adoption_allowed = false
broker_action_allowed = false
factor_promotion_allowed = false
```

Interpretation:

Technical factors are available for research, but no automatic promotion is allowed yet.

---

### 5. ABCDE Strategy Ranking System

The ABCDE framework compares multiple strategy variants, including baseline, momentum-enhanced, optimized, and experimental factor combinations.

A key output root:

```text
outputs/v21/V21.233_MOOMOO_ONLY_ABCDE_RERUN
```

Important artifacts include:

```text
abcde_strategy_ranking_master.csv
abcde_top20_summary.csv
abcde_top50_summary.csv
abcde_coverage_audit.csv
abcde_canonical_snapshot_audit.csv
```

This output should be archived with original data preserved when used for research records.

---

### 6. DRAM-Focused Research Chain

The user’s current long-term trading research focus is DRAM.
The system therefore includes a dedicated DRAM research and trade-plan chain.

Important DRAM modules include:

```text
V21.178_R1A_DAILY_DRAM_CHAIN_EXECUTION_MODE
V21.183_DRAM_INTRADAY_FORWARD_OUTCOME_UPDATER
V21.184_DRAM_INTRADAY_OUTCOME_DASHBOARD_AND_DECISION_SUMMARY
V21.185_DRAM_INTRADAY_TRIGGER_EVENT_ARCHIVE_AND_DAILY_APPEND
V21.186_DRAM_NO_TRADE_GATE
V21.201_DRAM_MOOMOO_R4_PLAN
V21.232_DRAM_CURRENTNESS_CHECK
```

DRAM outputs may include:

```text
entry price
no-chase price
stop price
currentness state
intraday trigger ledger
forward outcome dashboard
no-trade gate
```

All DRAM trade-plan outputs remain research-only unless explicitly approved.

---

### 7. Strategy Switch Governance

The strategy-switch system was designed to avoid jumping between strategies based on one-day noise.

Important modules include:

```text
V21.164_SWITCH_STATE_FORWARD_TRACKING_LEDGER
V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR
V21.170_SWITCH_TRIGGER_THRESHOLD_CALIBRATION_R1
V21.173_DAILY_CHAIN_ORCHESTRATOR_FOR_SWITCH_GOVERNANCE
```

Current governance posture:

```text
current_primary_control = A1_CONTROL
switch_allowed_research_only = false
official_adoption_allowed = false
broker_action_allowed = false
next_required_condition = continue daily switch ledger append and wait for matured 5D/10D/20D observations
```

---

### 8. Retention Guard and Cleanup Safety

Important modules include:

```text
V21.223_LOCAL_CACHE_ARCHITECTURE_AND_IO_ROUTER
V21.228 external copy verification
V21.235_REPO_CLEAN_DELETE_AFTER_VERIFICATION
V21.240 retention audit
V21.241 daily chain with retention guard
V21.262 git worktree triage
V21.263 remaining failures quarantine
V21.264 known failure repair audit
```

Cleanup rules:

* Do not delete cache files without external-copy verification.
* Do not delete active-chain outputs.
* Do not delete protected outputs.
* Do not delete quarantine artifacts unless explicitly reviewed.
* Do not run broad `git clean` without triage.
* Do not use `git add .` blindly when large outputs are present.

---

## Factor Families

The system currently organizes alpha and risk logic around six required factor families:

```text
Fundamental
Technical
Strategy
Risk
Market Regime
Data Trust
```

These families should sum to:

```text
1.00
```

Baseline family-weight direction historically used:

```text
Fundamental   0.20
Technical     0.25
Strategy      0.20
Risk          0.15
Market Regime 0.10
Data Trust    0.10
```

Dynamic weights are research-only unless forward validation and governance approval pass.

---

## Safety Gates

Every major script should preserve explicit safety outputs when relevant:

```text
official_adoption_allowed
broker_action_allowed
factor_promotion_allowed
protected_outputs_modified
cache_mutated
canonical_mutated
research_only
```

Default expected posture:

```text
official_adoption_allowed = false
broker_action_allowed = false
```

Any script that changes this behavior must be reviewed carefully.

---

## Testing

Most V21 modules include paired pytest files:

```text
scripts/v21/test_v21_*.py
```

Run an individual test:

```powershell
.\.venv\Scripts\python.exe -m pytest -q scripts\v21\test_v21_xxx.py
```

Run a specific known test module, for example:

```powershell
.\.venv\Scripts\python.exe -m pytest -q scripts\v21\test_v21_247_technical_subfactor_effectiveness_pit_lite_audit.py
```

Expected style:

```text
all tests passed
wrapper run succeeded
summary JSON produced
final_status recorded
final_decision recorded
```

---

## Output Conventions

Each major V21 module should write outputs under:

```text
outputs/v21/V21.xxx_MODULE_NAME/
```

Typical output files:

```text
v21_xxx_summary.json
V21.xxx_report.txt
*.csv
*_audit.csv
*_latest.csv
*_ledger.csv
```

Every important run should include:

```text
final_status
final_decision
input roots
output roots
row counts
warning count
error count
mutation flags
research/broker/adoption gates
```

---

## Git Hygiene

Before committing:

```powershell
git status --short
```

Recommended safe flow:

```powershell
git status --short
git diff --stat
git diff --name-only
```

Commit only targeted source, test, wrapper, and small audit files.

Avoid committing:

```text
large raw market data
external cache files
temporary notebooks
local credentials
broker exports
unreviewed quarantine files
large generated CSVs
binary artifacts unless intentionally archived
```

Do not run broad destructive cleanup commands unless a dedicated retention or cleanup module has verified the candidate files.

---

## Development Rules

When adding a new V21 module:

1. Add the Python script under `scripts/v21/`.
2. Add a matching pytest file.
3. Add a PowerShell wrapper if the module is run directly.
4. Write all outputs to a unique `outputs/v21/V21.xxx_*` folder.
5. Include `final_status` and `final_decision`.
6. Include explicit research/broker/adoption gates.
7. Avoid hidden data mutation.
8. Avoid external network access unless the script name and summary make it explicit.
9. Keep large artifacts outside the Git repo when possible.
10. Run pytest before committing.

Suggested naming:

```text
scripts/v21/v21_265_example_module_name_r1.py
scripts/v21/test_v21_265_example_module_name_r1.py
scripts/v21/run_v21_265_example_module_name_r1.ps1
outputs/v21/V21.265_EXAMPLE_MODULE_NAME_R1/
```

---

## Research-Only Disclaimer

This repository is for quantitative research, data validation, ranking experiments, and strategy governance.

It does not provide financial advice.
It does not guarantee investment returns.
It does not authorize live trading.
It does not replace independent risk management.

All broker actions, if any, require explicit human approval outside the default research chain.

---

## Current Operating Summary

The current system can be summarized as:

```text
Moomoo local-cache-first daily research chain
+ ABCDE ranking comparison
+ DRAM-focused research workflow
+ technical factor PIT-lite audit
+ forward validation
+ strategy-switch governance
+ retention-safe output management
+ broker-action hard block
```

Current practical recommendation:

```text
Use the V21.256 daily master wrapper as the main research entrypoint.
Treat all rankings and trade plans as research-only.
Preserve raw outputs for important ABCDE and DRAM runs.
Do not promote factor weights or strategy switches until forward maturity gates pass.
```
