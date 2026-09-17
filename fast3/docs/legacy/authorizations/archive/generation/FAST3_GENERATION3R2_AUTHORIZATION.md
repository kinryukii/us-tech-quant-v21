# FAST3 GENERATION 3R2 — THREE-YEAR NONLINEAR AUTORESEARCH AUTHORIZATION

## 0. Explicit authorization

This document explicitly authorizes a new and separate FAST3 research
generation named Generation 3R2.

Generation 1, Generation 2, and Generation 3 remain immutable historical
evidence. Do not overwrite, reopen, relabel, or delete their outputs.

Repository:
`D:\us-tech-quant`

Canonical data root, read-only:
`D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical`

Generation 3R2 output root:
`D:\us-tech-quant-results\fast3_autoresearch_generation3r2`

The six required instruments are:

```text
QQQ
SOXX
TQQQ
SQQQ
SOXL
SOXS
```

Safety invariants:

```text
broker_action_allowed=False
paper_broker_order_allowed=False
live_trading_allowed=False
official_adoption_allowed=False
order_generation_allowed=False
canonical_data_writable=False
research_only=True
```

Never create or transmit real or paper broker orders.

## 1. Research purpose

Use the existing local three-year minute history to test whether SOXX factors
have nonlinear, non-monotonic, interaction-dependent, and regime-dependent
relationships with economically tradable SOXL/SOXS outcomes.

Do not use only an unconditional future-direction target.

The required architecture is:

```text
Layer A: tradable opportunity
Layer B: direction conditional on opportunity
Layer C: LONG / SHORT / FLAT execution decision
```

The immediate objective is not to add unlimited indicators. First determine
whether the existing PIT information becomes useful when the target and model
architecture match the actual trading objective.

## 2. Fixed Generation 3R2 data contract

Before reading any Generation 3R2 Validation or Confirmation economics, verify
the following fixed date contract and write it to JSON with SHA256.

```text
Development:
2023-03-01 00:00:00 America/New_York
through
2026-02-28 23:59:59.999999 America/New_York

Embargo 1:
2026-03-01 through 2026-03-31

Validation:
2026-04-01 through 2026-05-31

Embargo 2:
2026-06-01 through 2026-06-30

Confirmation:
2026-07-01 through the latest common six-symbol canonical timestamp available
on or before 2026-07-31
```

The currently known common history ends around 2026-07-28. This new contract is
authorized before economic research and therefore uses the following fixed
Confirmation feasibility requirements:

```text
minimum independent Confirmation trading days = 15
minimum non-overlapping executed Confirmation trades = 75
```

Do not move these date boundaries or lower these requirements after reading
returns.

If any required symbol lacks adequate coverage for Development, Validation, or
Confirmation, fail closed with:

```text
FINAL_STATUS=FAIL_DATA_CONTRACT
```

All earlier exposure must be recorded in a date-level ledger. Prior exposed
dates may be used only as Development evidence in this new generation.
Generation 3R2 Validation and Confirmation must remain economically unread
until their respective gates are legally reached.

## 3. PIT and leakage rules

For every feature row, record or verify:

```text
decision_timestamp
maximum_source_timestamp
availability_lag
completed_bar_semantics
source_symbol
source_field
lookback
```

Require:

```text
maximum_source_timestamp <= decision_timestamp
```

Features may use only information available at the decision timestamp. Labels
may use future data.

Never:

- use centered rolling windows;
- backfill from future observations;
- fit scalers, imputers, calibrators, regimes, or thresholds on Validation;
- randomly shuffle minute rows;
- select favorable dates;
- use Confirmation during Development or Validation;
- silently repair canonical data;
- tune after Validation.

Any violation must produce:

```text
FINAL_STATUS=FAIL_LEAKAGE_DETECTED
```

## 4. Three-layer labels

### Layer A — tradable opportunity

At fixed 5-minute decision points, create PIT-consistent labels for 30, 60, and
120 minute horizons using SOXX path and real SOXL/SOXS execution.

Required outputs include:

```text
opportunity_30m
opportunity_60m
opportunity_120m
expected_absolute_soxx_move
SOXX_MFE
SOXX_MAE
barrier_first_hit
path_class
real_etf_best_net_return_10bps
real_etf_best_net_return_20bps
```

Path classes:

```text
TREND_OPPORTUNITY
REVERSAL_OPPORTUNITY
CHOPPY_OR_NO_EDGE
INSUFFICIENT_LIQUIDITY
DATA_UNTRUSTED
```

Barrier widths may depend only on past ATR or realized volatility known at the
decision point. Predeclare barrier formulas before Development economics.

### Layer B — conditional direction

Only for opportunity-positive samples, estimate:

```text
P(UP | opportunity)
P(DOWN | opportunity)
directional_uncertainty
```

Do not force a direction for all timestamps.

### Layer C — execution and abstention

Map:

```text
LONG  -> SOXL
SHORT -> SOXS
FLAT  -> no trade
```

Use real next-valid-open entry, fixed execution timestamp tolerance, 30/60/120
minute exits, 10bps base cost, 20bps stress cost, and 1/3/5 minute delay stress.

The final action must depend on:

```text
expected_net_return_long
expected_net_return_short
expected_MFE
expected_MAE
uncertainty
cost_and_delay_buffer
```

FLAT is mandatory whenever no side clears the frozen net-return and risk gate.

## 5. Existing feature families first

The architecture-only candidate stage must use local PIT features already
derivable from SOXX, QQQ, SOXL, and SOXS:

```text
SOXX returns: 1/3/5/15/30/60/120m
SOXX realized volatility: 5/15/30/60/120m
SOXX range and ATR-normalized range
SOXX volume ratios and volume acceleration
VWAP distance and VWAP-side persistence
MA/EMA slope and distance
RSI / KDJ / Bollinger position
breakout / pullback / drawdown state
QQQ returns and volatility
SOXX/QQQ relative strength
SOXL/SOXS consistency and divergence
session and time-of-day
gap and overnight/premarket state
validated prior-day CBOE VIX features
```

Do not fabricate intraday VIX, constituents, order book, spreads, or macro data.

After the architecture stage, one additional local factor group may be tested
only if it already exists with auditable PIT timestamps. Add one group at a
time and record an ablation.

## 6. Predeclared candidate families

Maximum candidate families before Validation: 6.

Freeze all hyperparameters, thresholds, feature groups, seeds, scoring rules,
and tie-breaks before opening Validation.

Required families:

1. unconditional / regime-only baselines;
2. linear two-stage logistic or ridge baseline;
3. two-stage HistGradientBoosting;
4. regime-specific HistGradientBoosting mixture-of-experts;
5. compact ExtraTrees two-stage challenger;
6. best architecture plus validated prior-day VIX interaction challenger.

No unrestricted parameter search. No AutoML, LSTM, Transformer, neural network,
genetic search, or Bayesian optimization.

Keep model grids compact and deterministic. Any threshold selection must occur
inside Development only.

## 7. Development research and random backtesting

Development is 2023-03-01 through 2026-02-28.

Use nested chronological walk-forward. Required outer structures include at
least:

```text
12-month train -> next 1-month test
18-month train -> next 1-month test
24-month train -> next 1-month test
expanding train -> next 1-month test
```

Use purging and embargo consistent with the maximum label horizon.

Run at least 100 fixed-seed continuous chronological as-of windows when sample
size allows. Do not shuffle rows. Report the full distribution, including:

```text
mean
median
standard deviation
5th/25th/75th/95th percentiles
positive-window ratio
worst window
best window
trade count
turnover
cost sensitivity
delay sensitivity
drawdown
LONG/SHORT attribution
regime attribution
```

Use fixed seeds beginning with:

```text
20260801
20260802
20260803
```

Record every candidate and rejection in the experiment registry.

## 8. Development gates before Validation

A candidate may enter the frozen Validation candidate set only if all
Development requirements pass:

```text
walk-forward executed trades >= 500
mean net return 10bps > 0
median window net return 10bps > 0
positive-window ratio 10bps >= 0.60
positive-window ratio 20bps >= 0.55
no single month contributes >= 35% of total profit
no single execution ETF contributes >= 75% of total profit
top 5 trades contribute < 25% of total profit
maximum drawdown <= 0.30
no material leakage or timestamp failure
```

These gates are fixed before Development results.

Freeze at most 3 finalists for Validation, selected using the predeclared
Development score:

```text
0.35 * median_window_net_10bps
+ 0.25 * positive_window_ratio_10bps
+ 0.15 * positive_window_ratio_20bps
+ 0.15 * worst_quartile_mean_net_10bps
- 0.10 * normalized_drawdown
```

Tie-break:

```text
lower candidate complexity
then fewer trades
then lexical candidate_id
```

## 9. One-time Validation

Open 2026-04-01 through 2026-05-31 exactly once after finalists are frozen.

Evaluate all finalists in one pass with no retuning.

Minimum Validation gates:

```text
executed trades >= 100
mean net return 10bps > 0
mean net return 20bps > 0
profit factor 10bps >= 1.15
positive calendar-month ratio >= 0.50
positive non-overlapping block ratio 10bps >= 0.60
positive non-overlapping block ratio 20bps >= 0.55
maximum drawdown <= 0.25
top 5 trade profit concentration < 0.25
single ETF profit concentration < 0.70
1-minute delay remains positive at 10bps
no material Development/Validation direction reversal
```

Select at most one champion using a predeclared score and tie-break. Apply a
multiple-testing or deflated-performance diagnostic.

If all finalists fail, stop:

```text
FINAL_STATUS=FAIL_NO_ROBUST_EDGE
```

Do not create new candidates after seeing Validation.

## 10. One-time Confirmation

Only after one frozen champion clears all Validation gates:

1. freeze complete strategy JSON and SHA256;
2. refit once on permitted Development + Validation data;
3. read Confirmation exactly once;
4. evaluate 10bps/20bps costs;
5. evaluate 1/3/5 minute delays;
6. evaluate non-overlapping blocks and monthly stability;
7. evaluate bootstrap confidence intervals;
8. evaluate LONG/SHORT and regime concentration;
9. never modify the strategy afterward.

Confirmation period:

```text
2026-07-01 through latest common six-symbol date on or before 2026-07-31
```

Require at least 15 independent trading days and 75 non-overlapping trades.

If Confirmation fails:

```text
FINAL_STATUS=FAIL_CONFIRMATION
```

If accepted:

```text
FINAL_STATUS=PASS_GENERATION3_CONFIRMATION_ACCEPTED
```

## 11. Output contract

Write only under:

`D:\us-tech-quant-results\fast3_autoresearch_generation3r2`

Required outputs:

```text
generation3r2_data_usage_ledger.csv
generation3r2_split_contract.json
generation3r2_split_contract_sha256.txt
generation3r2_feature_contract.json
generation3r2_label_contract.json
generation3r2_candidate_registry.csv
generation3r2_development_walkforward_metrics.csv
generation3r2_random_window_metrics.csv
generation3r2_ablation_metrics.csv
generation3r2_validation_frozen_candidates.json
generation3r2_validation_metrics.csv
generation3r2_leakage_audit.json
generation3r2_champion_record.json
generation3r2_checkpoint.json
generation3r2_final_summary.json
generation3r2_final_report.md
generation3r2_final_checkpoint.json
```

If Confirmation is reached, also produce its frozen contract, hash, detailed
metrics, and one-time-read evidence.

Do not copy canonical data or output huge feature matrices.

## 12. Required testing

Before claiming a stage complete:

```text
python compile
focused pytest
actual runner execution
output-contract validation
checkpoint update
registry update
```

Tests must cover:

- PIT timestamp maximum;
- completed-bar semantics;
- barrier and path labels;
- opportunity/direction separation;
- LONG/SHORT/FLAT abstention;
- purge and embargo;
- deterministic seeds;
- non-overlapping trade logic;
- real SOXL/SOXS timestamp mapping;
- costs and delay;
- Confirmation zero-read guard;
- one-time Validation guard;
- idempotent rerun;
- no broker/order object.

Do not claim unexecuted work.

## 13. Terminal statuses

Use exactly one:

```text
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

A terminal response must include:

```text
FINAL_STATUS=<status>
```

A terminal checkpoint must contain:

```text
exact_resume_command=NONE_FAST3_GENERATION3R2_RESEARCH_STOPPED
```

Only `PARTIAL_RESOURCE_LIMIT_CHECKPOINT_SAVED` is resumable.

## 14. Immediate execution order

1. inspect repository and current Git status;
2. read this authorization and prior generation evidence;
3. audit common six-symbol coverage and previous exposure;
4. freeze and hash the fixed 3R2 split;
5. implement three-layer labels and tests;
6. implement existing PIT feature families;
7. predeclare the compact six-family candidate set;
8. run real Development nested walk-forward;
9. run at least 100 chronological random windows;
10. freeze finalists;
11. open Validation exactly once;
12. select at most one champion;
13. read Confirmation exactly once only if legal;
14. finalize complete artifacts and truthful status.

Never fabricate, beautify, lower gates after results, retune on Validation,
read Confirmation early, modify canonical data, create orders, or repeat no-op
resume turns.
