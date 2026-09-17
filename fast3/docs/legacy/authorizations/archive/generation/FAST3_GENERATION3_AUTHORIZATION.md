# FAST3 GENERATION 3 — NONLINEAR OPPORTUNITY / DIRECTION RESEARCH AUTHORIZATION

## 0. Explicit authorization and scope

This document explicitly authorizes a new FAST3 Generation 3 research program.

Generation 1 and Generation 2 remain immutable historical evidence. Do not
overwrite, relabel, delete, or reopen their final checkpoints. Generation 3 is
a separate research generation with a new frozen contract.

Repository:
`D:\us-tech-quant`

Read-only canonical data:
`D:\us-tech-quant-data`

Generation 3 result root:
`D:\us-tech-quant-results\fast3_autoresearch_generation3`

Safety invariants:

```text
broker_action_allowed=False
paper_broker_order_allowed=False
live_trading_allowed=False
official_adoption_allowed=False
order_generation_allowed=False
research_only=True
canonical_data_writable=False
```

Never create, send, serialize, or stage a broker order.

## 1. Prior evidence that must be preserved

Generation 1 concluded that large historical SOXX/QQQ moves exist, but its
predeclared predictability gate failed after real ETF costs.

Generation 2 tested a linear baseline, Development-only abstention, a compact
nonlinear challenger, a SOXX-only ablation, and prior-day CBOE VIX features.
No candidate cleared every frozen Validation net-expectancy and chronological
robustness gate. Its final state is `FAIL_NO_ROBUST_EDGE`, with zero
Confirmation reads and no champion.

Do not treat these failures as proof that every nonlinear relationship is
absent. They reject only the tested labels, feature contracts, model families,
thresholds, and validation procedure.

## 2. Generation 3 central hypothesis

The primary hypothesis is:

> SOXX factors have nonlinear, non-monotonic, interaction-dependent and
> regime-dependent relationships with tradable outcomes, and the earlier
> single-stage 60-minute direction target mixed genuine trend opportunities
> with noisy or economically irrelevant periods.

Generation 3 must first test label and architecture mismatch before adding
large numbers of technical indicators.

## 3. Mandatory exposure audit and deterministic split freeze

Before reading any Generation 3 economic result:

1. Read all Generation 1 and Generation 2 contracts, ledgers, checkpoints,
   summaries, randomized-window manifests, and exact date boundaries.
2. Build a date-level exposure ledger with at least:
   - PREVIOUSLY_EXPOSED_DEVELOPMENT
   - PREVIOUSLY_EXPOSED_VALIDATION
   - PREVIOUSLY_EXPOSED_RANDOMIZED_SELECTION
   - PREVIOUSLY_UNREAD_ELIGIBLE
   - EMBARGO
   - GENERATION3_DEVELOPMENT
   - GENERATION3_VALIDATION
   - GENERATION3_CONFIRMATION_UNREAD
   - FUTURE_ONLY
3. Freeze and hash the Generation 3 split before inspecting Generation 3
   Validation or Confirmation economics.
4. Never choose dates using returns, AUC, hit rate, expectancy, drawdown, or any
   target-derived statistic.

Deterministic default split rule:

- Generation 3 Development may use previously exposed dates through the latest
  Generation 2 Validation end solely as Development evidence.
- Preserve the next full calendar month as an embargo.
- The previously unread Generation 2 holdout may be reclassified for
  Generation 3 only after this new contract is written and hashed.
- Generation 3 Validation is the first two complete eligible calendar months
  after the first embargo.
- Preserve the next complete calendar month as a second embargo.
- Generation 3 Confirmation is the remaining complete eligible period.
- Confirmation requires at least 20 independent trading days and at least 75
  non-overlapping executed trades after the final strategy is frozen.
- If these deterministic requirements are not met, keep Confirmation unread
  and return `FAIL_INSUFFICIENT_INDEPENDENT_DATA`.
- Do not move boundaries to improve results.

Any implementation that reads Confirmation before a frozen champion exists
must fail closed with `FAIL_LEAKAGE_DETECTED`.

## 4. Three-layer target architecture

Generation 3 must not use only a single unconditional up/down label.

### Layer A — tradable opportunity

Estimate whether a sufficiently large, executable move exists:

```text
probability_tradable_opportunity
expected_absolute_soxx_move
expected_soxx_MFE
expected_soxx_MAE
expected_real_etf_net_opportunity
```

Use fixed 30m, 60m, and 120m horizons plus barrier/path labels. Barrier widths
may depend only on past ATR or realized volatility known at the decision time.
Labels may use future data; features may not.

Separate:

```text
TREND_OPPORTUNITY
REVERSAL_OPPORTUNITY
CHOPPY_OR_NO_EDGE
INSUFFICIENT_LIQUIDITY
DATA_UNTRUSTED
```

### Layer B — conditional direction

Only conditional on a tradable opportunity, estimate:

```text
probability_up_given_opportunity
probability_down_given_opportunity
directional_uncertainty
```

Do not force a direction for every candidate timestamp.

### Layer C — real execution and abstention

Map only passed opportunities:

```text
LONG  -> SOXL
SHORT -> SOXS
FLAT  -> no position
```

Use real SOXL/SOXS OHLC, next-valid-bar execution, timestamp tolerances, 10bps
base cost, 20bps stress cost, delay stress, and fail-closed data-quality gates.

The final decision must be based on:

```text
expected_net_return_long
expected_net_return_short
estimated_MFE
estimated_MAE
estimated_uncertainty
```

A trade is allowed in research output only when expected net return exceeds the
frozen cost and safety buffer. Otherwise output FLAT.

## 5. First registered candidate set: architecture before new factors

The first registered Generation 3 candidate set must use existing PIT feature
families only. Its purpose is to test whether the old information was obscured
by the wrong target or a single global model.

Required baselines:

1. unconditional and regime-only baselines;
2. linear logistic / ridge baselines;
3. two-stage HistGradientBoosting opportunity + direction model;
4. compact regime-specific mixture-of-experts;
5. optional GAM/EBM only if already installed locally and deterministic.

Do not install large new ML frameworks. Prefer existing scikit-learn
dependencies. No LSTM, Transformer, large neural network, genetic search,
Bayesian hyperparameter search, or unrestricted AutoML.

The candidate list, model classes, hyperparameters, feature groups, thresholds,
random seeds, scoring rule, and tie-break rule must all be frozen before
opening Generation 3 Validation.

## 6. Regime-specific nonlinear structure

Predeclare regimes using only information available at the decision time:

```text
LOW_VOL_RANGE
HIGH_VOL_RANGE
UP_TREND
DOWN_TREND
GAP_TREND
REVERSAL
OVERNIGHT
PREMARKET
RTH_OPEN
RTH_MIDDAY
RTH_CLOSE
AFTER_HOURS
DATA_UNTRUSTED
```

Test interactions such as:

```text
momentum × volatility
RSI/KDJ/Bollinger position × trend regime
VWAP distance × session
gap × volume confirmation
SOXX relative strength × QQQ trend
direction × prior-day VIX regime
```

A regime may use an independent compact expert only when Development has
adequate sample size. Otherwise fall back to the global model.

## 7. Factor expansion after architecture evaluation

Do not add all factors at once. Register one factor group at a time, and only
after the architecture-only candidate set is complete.

Priority order:

1. Existing SOXX multiscale trend / VWAP / volatility / volume factors.
2. Existing QQQ and leveraged-ETF cross-asset consistency factors.
3. Validated prior-day CBOE VIX factors.
4. Intraday VIX, VIX9D, VVIX, term structure, or VIX futures only if a local
   timestamped PIT source already exists and passes an availability audit.
5. Semiconductor constituent breadth, dispersion, and weighted-versus-equal
   strength only if local timestamp-aligned constituent data exist.
6. Other cross-asset risk factors only if local PIT provenance is available.

Never fabricate unavailable order-book, spread, constituent, macro, or VIX
data. Record `SOURCE_DATA_MISSING` or `NOT_AVAILABLE`.

Each factor group must have:

```text
economic_mechanism
source_symbol
source_field
lookback
availability_lag
maximum_source_timestamp
missing_value_contract
PIT_test
Development ablation
turnover/cost impact
```

## 8. Validation discipline and multiple-testing control

Use Development only for:

- model fitting;
- feature transformation;
- regime definition;
- hyperparameter choice;
- calibration;
- threshold and abstention selection;
- candidate rejection;
- randomized as-of research.

Within Development:

- use nested chronological walk-forward;
- use purging and embargo;
- run at least 100 fixed-seed continuous as-of windows when sample size allows;
- report the full distribution, not the best seed;
- group overlapping samples by trading day or move family;
- calculate selection exposure and an overfitting-risk diagnostic.

Validation:

- open once after the complete small candidate set is frozen;
- evaluate every predeclared candidate in the same pass;
- do not create a new candidate after seeing Validation;
- use fixed non-overlapping chronological blocks;
- select at most one champion using a predeclared score and tie-break;
- apply a multiple-testing penalty or deflated-performance diagnostic.

Maximum predeclared candidate families before Confirmation: 6.

If all frozen candidates fail Validation, stop Generation 3. Do not retune on
the same Validation.

## 9. Minimum pre-Confirmation gates

A candidate may be frozen for Confirmation only if all applicable gates pass:

```text
validation_executed_trade_count >= 100
mean_net_return_10bps > 0
mean_net_return_20bps > 0
profit_factor_10bps >= 1.15
positive_validation_month_ratio >= 0.60
positive_nonoverlap_block_ratio_10bps >= 0.60
positive_nonoverlap_block_ratio_20bps >= 0.55
maximum_drawdown <= 0.25
single_execution_etf_profit_contribution < 0.70
top5_trade_profit_concentration < 0.25
no material Development/Validation feature-direction reversal
no leakage or timestamp-contract failure
```

AUC is diagnostic only. Economic path performance and stability are primary.

## 10. One-time Confirmation

Only after one champion is frozen:

1. Freeze feature list, transformations, model structure, parameters,
   calibration, thresholds, regimes, execution mapping, target/stop/timeout,
   costs, delays, overlap handling, and missing-value rules.
2. Write a contract JSON and SHA256.
3. Refit once on permitted Development + Validation data.
4. Read Confirmation exactly once.
5. Never alter the strategy after seeing Confirmation.

Confirmation must evaluate real SOXL/SOXS trades, 10bps/20bps costs, 1/3/5
minute delay stress, block bootstrap confidence intervals, monthly stability,
drawdown, concentration, and LONG/SHORT attribution.

If no candidate reaches the pre-Confirmation gates:

```text
CONFIRMATION_READ_COUNT=0
```

## 11. Prospective shadow

Only after Confirmation acceptance may the agent create an idempotent,
zero-order prospective shadow recorder. It must not modify V22.044, generate
orders, connect to broker execution, or claim future validation.

## 12. Required implementation and testing

Before ending each meaningful stage:

```text
py_compile
focused pytest
actual runner execution
output-contract validation
checkpoint update
experiment registry update
```

Tests must cover at least:

- PIT maximum-source-timestamp guard;
- completed-bar semantics;
- split purge/embargo;
- Confirmation zero-read guard;
- barrier/path label semantics;
- opportunity/direction separation;
- LONG/SHORT/FLAT abstention;
- real ETF timestamp mapping;
- cost and delay calculations;
- deterministic seeds;
- repeated-run idempotency;
- no broker/order object.

Do not claim unexecuted work.

## 13. Output contract

Write Generation 3 outputs only under:

`D:\us-tech-quant-results\fast3_autoresearch_generation3`

At minimum produce:

```text
generation3_data_usage_ledger.csv
generation3_split_contract.json
generation3_split_contract_sha256.txt
generation3_feature_contract.json
generation3_label_contract.json
generation3_candidate_registry.csv
generation3_development_walkforward_metrics.csv
generation3_validation_metrics.csv
generation3_random_window_metrics.csv
generation3_ablation_metrics.csv
generation3_leakage_audit.json
generation3_champion_record.json
generation3_checkpoint.json
generation3_final_summary.json
generation3_final_report.md
generation3_final_checkpoint.json
```

If Confirmation is legally reached, also produce its frozen contract and
one-time results. Do not output large feature matrices or canonical-data copies.

## 14. Terminal statuses

Use exactly one of these final statuses:

```text
PASS_GENERATION3_PROSPECTIVE_SHADOW_DEPLOYED_AWAITING_SAMPLE
PASS_GENERATION3_CANDIDATE_READY_FOR_CONFIRMATION
PASS_GENERATION3_CONFIRMATION_ACCEPTED
PASS_GENERATION3_PIPELINE_COMPLETE_NO_EDGE_CONFIRMED
FAIL_DATA_CONTRACT
FAIL_LEAKAGE_DETECTED
FAIL_INSUFFICIENT_INDEPENDENT_DATA
FAIL_OVERFITTING_RISK
FAIL_NO_ROBUST_EDGE
FAIL_COST_SENSITIVITY
FAIL_DELAY_SENSITIVITY
FAIL_CONFIRMATION
PARTIAL_RESOURCE_LIMIT_CHECKPOINT_SAVED
```

A negative result is valid and must not be beautified.

When the generation is genuinely terminal, print an exact line:

```text
FINAL_STATUS=<one terminal status>
```

and set:

```text
EXACT_RESUME_COMMAND=NONE_FAST3_GENERATION3_RESEARCH_STOPPED
```

`PARTIAL_RESOURCE_LIMIT_CHECKPOINT_SAVED` is resumable and must include a real
exact resume command.

## 15. Immediate execution order

Start actual work now:

1. inspect repository and Git status without destructive commands;
2. read this authorization and all prior FAST3 evidence;
3. audit previous exposure;
4. freeze and hash the deterministic Generation 3 split;
5. implement and test the three-layer labels;
6. predeclare the complete compact candidate set;
7. run Development nested walk-forward and 100-window research;
8. freeze the candidate set;
9. open Validation once;
10. select at most one champion by the frozen rule;
11. read Confirmation once only if every gate passes;
12. otherwise finalize truthfully;
13. save complete artifacts and checkpoint.

Never:

```text
FABRICATE RESULTS
BEAUTIFY FAILURE
USE FUTURE DATA IN FEATURES
READ CONFIRMATION DURING DEVELOPMENT
RETUNE AFTER VALIDATION
OPTIMIZE DIRECTLY FOR THE BEST BACKTEST
LOWER COSTS AFTER FAILURE
CREATE LIVE OR PAPER BROKER ORDERS
OVERWRITE GENERATION 1 OR GENERATION 2 EVIDENCE
REPEAT NO-OP RESUME TURNS
```
