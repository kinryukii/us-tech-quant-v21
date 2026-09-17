# FAST3 GENERATION 3R3 — FAST FUNNEL DIAGNOSTIC AND ITERATIVE RESEARCH AUTHORIZATION

## 0. Explicit authorization

This document explicitly authorizes a new FAST3 research generation:

```text
FAST3_GENERATION3R3_FAST_FUNNEL_ITERATION
```

Generation 1, Generation 2, Generation 3, and Generation 3R2 remain immutable
historical evidence. Do not overwrite, reopen, relabel, delete, or silently
modify their outputs.

Repository:
`D:\us-tech-quant`

Canonical data root, read-only:
`D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical`

Generation 3R3 result root:
`D:\us-tech-quant-results\fast3_autoresearch_generation3r3`

Required symbols:

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
research_only=True
canonical_data_writable=False
broker_action_allowed=False
paper_broker_order_allowed=False
live_trading_allowed=False
official_adoption_allowed=False
order_generation_allowed=False
```

Never create, serialize, stage, or transmit a broker order.

## 1. Prior evidence and exact starting point

Generation 3R2 completed a Development-only three-layer research pass using
six predeclared candidate families and 100 chronological windows.

Observed Development evidence:

```text
C1_UNCONDITIONAL_REGIME:        0 final trades
C2_LINEAR_TWO_STAGE:           30 final non-overlapping trades
C3_HGB_TWO_STAGE:               0 final trades
C4_REGIME_HGB_MOE:              0 final trades
C5_EXTRATREES_TWO_STAGE:        0 final trades
C6_HGB_VIX_PRIOR_DAY:           0 final trades
```

The C2 linear candidate had positive Development economics in the recorded
sample, but 30 trades were far below the frozen 500-trade requirement.

Generation 3R2 Validation and Confirmation economics were not read.

Generation 3R3 must not assume that nonlinear models have no edge. The first
problem to solve is the unexplained signal-funnel collapse that produced zero
final trades in five nonlinear candidates.

## 2. Primary objective

Rapidly and truthfully determine:

1. at which exact funnel stage each candidate loses samples;
2. whether zero-trade behavior is caused by:
   - label imbalance;
   - degenerate model probabilities;
   - missing features;
   - probability miscalibration;
   - opportunity threshold;
   - direction threshold;
   - expected-net-return buffer;
   - regime fallback;
   - ETF timestamp mapping;
   - cost/delay filter;
   - overlap suppression;
   - implementation error;
3. whether a compact, predeclared Development-only repair can produce enough
   chronologically stable trades to justify one-time Validation.

Do not add large new factor sets until this funnel diagnosis is complete.

## 3. Fixed data split

Freeze and hash this split before Generation 3R3 economic evaluation:

```text
Development:
2023-03-01 through 2026-02-28

Embargo 1:
2026-03-01 through 2026-03-31

Validation:
2026-04-01 through 2026-05-31

Embargo 2:
2026-06-01 through 2026-06-30

Confirmation:
2026-07-01 through the latest common six-symbol date on or before 2026-07-31
```

Prior exposed periods may be used only as Development evidence.

Validation and Confirmation must remain economically unread until their legal
gates are reached.

Minimum Confirmation feasibility remains:

```text
independent trading days >= 15
non-overlapping executed trades >= 75
```

Do not change date boundaries after observing returns.

## 4. Fast execution mode

The purpose is rapid iteration without process inflation.

Required operating rules:

1. Reuse and refactor the existing Generation 3R2 implementation where safe.
2. Do not duplicate large modules unnecessarily.
3. Do not recursively dump the repository, huge CSV files, Parquet contents,
   event JSONL, or full logs into the conversation.
4. Use targeted searches, `head`, summaries, row counts, descriptive
   statistics, and hashes.
5. Do not reread immutable large files every round.
6. Make one primary research change per registered iteration.
7. Compile and run focused tests after each meaningful change.
8. Run the actual Development research after the tests.
9. Save a checkpoint and concise registry row after every iteration.
10. Continue autonomously while a distinct legal Development hypothesis exists.
11. Stop repeated no-op turns.
12. Never create version-number or test-file proliferation without necessity.
13. Prefer a small number of high-information experiments over a large blind
    hyperparameter search.

## 5. Mandatory funnel instrumentation

Before changing thresholds or models, instrument every candidate with the
following counts:

```text
raw_decision_timestamp_count
completed_bar_eligible_count
valid_feature_row_count
feature_missing_rejection_count
opportunity_label_positive_count
opportunity_label_negative_count
opportunity_model_scored_count
opportunity_probability_pass_count
direction_training_sample_count
direction_model_scored_count
direction_confidence_pass_count
expected_net_long_pass_count
expected_net_short_pass_count
flat_due_to_opportunity_count
flat_due_to_direction_count
flat_due_to_expected_return_count
long_before_execution_count
short_before_execution_count
etf_timestamp_mapping_success_count
etf_timestamp_mapping_failure_count
cost_filter_pass_count
delay_filter_pass_count
overlap_suppressed_count
final_nonoverlap_long_count
final_nonoverlap_short_count
final_nonoverlap_trade_count
```

Every rejected row must have exactly one primary reason code:

```text
INVALID_FEATURE
DATA_UNTRUSTED
NO_OPPORTUNITY
LOW_OPPORTUNITY_PROBABILITY
LOW_DIRECTION_CONFIDENCE
EXPECTED_NET_BELOW_BUFFER
ETF_MAPPING_FAILURE
COST_FAILURE
DELAY_FAILURE
OVERLAP_SUPPRESSED
OTHER_FAIL_CLOSED
```

Required diagnostic artifacts:

```text
generation3r3_candidate_funnel_counts.csv
generation3r3_flat_reason_counts.csv
generation3r3_feature_missingness.csv
generation3r3_probability_distributions.csv
generation3r3_probability_calibration.csv
generation3r3_regime_coverage.csv
generation3r3_overlap_attrition.csv
generation3r3_execution_mapping_audit.csv
```

The first milestone must report exactly where C3/C4/C5/C6 collapse.

## 6. Diagnostic integrity gates

Before any threshold repair:

```text
maximum_source_timestamp <= decision_timestamp
completed bar strictly precedes decision
Validation economics read = False
Confirmation economics read = False
all six required symbols mapped
feature missingness by candidate reported
probability quantiles reported
reason-code totals reconcile to candidate counts
funnel count monotonicity holds
```

Any reconciliation or PIT failure must produce:

```text
FINAL_STATUS=FAIL_LEAKAGE_DETECTED
```

or:

```text
FINAL_STATUS=FAIL_IMPLEMENTATION_CONTRACT
```

Do not compensate for an implementation bug by changing model thresholds.

## 7. Development-only staged repair program

All repair selection must occur inside Development with nested chronological
walk-forward. Validation remains unread.

### Stage A — label and probability viability

For every model report:

```text
opportunity prevalence by month/session/regime
direction prevalence conditional on opportunity
probability min/p01/p05/p10/p25/p50/p75/p90/p95/p99/max
Brier score
log loss
calibration slope/intercept
reliability bins
```

Detect:

```text
single-class fold
probability collapse
all probabilities below threshold
all probabilities inside FLAT band
regime expert without adequate samples
```

### Stage B — coverage-first threshold surface

Run the following fixed compact Development-only diagnostic grid:

```text
opportunity probability threshold:
0.35, 0.40, 0.45, 0.50, 0.55, 0.60

direction confidence margin from 0.50:
0.00, 0.02, 0.04, 0.06, 0.08, 0.10

expected-net-return safety buffer:
0bps, 5bps, 10bps, 15bps, 20bps

holding horizon:
30m, 60m, 120m
```

This is not a full Cartesian blind search.

Use staged coordinate diagnostics:

1. freeze model and horizon; vary opportunity threshold for coverage and
   calibration only;
2. freeze a viable opportunity band using non-economic criteria;
3. vary direction confidence for coverage and calibration only;
4. freeze a viable direction band;
5. vary expected-net buffer and horizon using nested Development economics;
6. evaluate the resulting compact combinations in outer walk-forward.

Maximum fully evaluated economic combinations per candidate family: 18.

### Stage C — probability calibration

Compare only these deterministic calibrators inside training folds:

```text
none
sigmoid / Platt
isotonic only when fold sample count >= 5000 and both classes are adequate
```

Never calibrate on outer test folds.

### Stage D — overlap diagnosis

Report results both before and after non-overlap suppression.

Pre-overlap signals are diagnostic only and may not be treated as independent
trades.

Compare fixed non-overlap policies:

```text
one active position globally
one active position per direction
cooldown 15m
cooldown 30m
cooldown equal to selected holding horizon
```

Select only inside Development.

### Stage E — compact model repair

Allowed model changes:

```text
linear two-stage baseline
HistGradientBoosting with compact depth/leaf variants
ExtraTrees with compact leaf-size variants
regime-specific model with deterministic global fallback
prior-day VIX interaction challenger
```

Maximum model variants per family: 4.

No AutoML, neural network, Transformer, LSTM, Bayesian optimization, genetic
search, or unrestricted random search.

## 8. Development evaluation

Use nested chronological walk-forward with purging and embargo.

Required structures:

```text
12-month train -> next 1 month
18-month train -> next 1 month
24-month train -> next 1 month
expanding train -> next 1 month
```

Run at least 100 fixed-seed continuous chronological as-of windows.

Do not shuffle rows.

Report:

```text
trade count
pre-overlap signal count
mean and median net returns
10bps and 20bps costs
1/3/5 minute delays
profit factor
hit rate
monthly stability
non-overlapping block stability
maximum drawdown
LONG/SHORT attribution
regime attribution
top-5 trade concentration
single-ETF concentration
worst-window result
5th/25th/50th/75th/95th percentiles
```

## 9. Generation 3R3 promotion gates

The Generation 3R2 fixed 500-trade requirement is not reused blindly. Before
Validation and before reading its economics, Generation 3R3 uses these
predeclared coverage tiers:

```text
Tier A:
Development non-overlapping trades >= 300

Tier B:
Development non-overlapping trades >= 150
and at least 18 independent active months
and no active month contributes more than 15% of all trades

Tier C:
Development non-overlapping trades >= 90
and at least 24 independent active months
and at least 45 LONG and 45 SHORT trades
```

Only Tier A, B, or C candidates can be considered for Validation.

All candidates must also pass:

```text
mean net return 10bps > 0
median chronological-window net return 10bps > 0
positive-window ratio 10bps >= 0.58
positive-window ratio 20bps >= 0.52
1-minute-delay mean net return 10bps > 0
profit factor 10bps >= 1.10
maximum drawdown <= 0.30
top-5 trade profit concentration < 0.25
single-ETF profit concentration < 0.75
no material probability or direction instability
no leakage or timestamp failure
```

These gates are frozen before Generation 3R3 Development results.

Freeze at most 3 Validation finalists.

Apply an explicit multiple-testing penalty or deflated-performance diagnostic.

## 10. One-time Validation

Only after the complete finalist set is frozen:

```text
Validation = 2026-04-01 through 2026-05-31
```

Open Validation exactly once and evaluate all finalists together.

No post-Validation candidate creation, threshold change, feature change,
calibration change, horizon change, overlap-policy change, or model repair.

Minimum Validation requirements:

```text
executed non-overlapping trades >= 30
mean net return 10bps > 0
mean net return 20bps > 0
profit factor 10bps >= 1.10
positive non-overlap block ratio 10bps >= 0.55
positive non-overlap block ratio 20bps >= 0.50
1-minute-delay mean net return 10bps > 0
maximum drawdown <= 0.25
top-5 trade concentration < 0.35
no material Development/Validation sign reversal
```

The lower Validation trade minimum reflects the fixed two-month period and is
predeclared before Validation economics. It does not waive stability,
concentration, cost, or delay gates.

Select at most one champion using the frozen score and tie-break.

If no finalist passes:

```text
FINAL_STATUS=FAIL_NO_ROBUST_EDGE
```

## 11. One-time Confirmation

Only after one frozen champion passes every Validation gate:

```text
Confirmation = 2026-07-01 through the latest common six-symbol date
on or before 2026-07-31
```

Freeze full strategy JSON and SHA256, refit once on permitted data, and read
Confirmation exactly once.

Requirements:

```text
independent trading days >= 15
non-overlapping trades >= 75
mean net return 10bps > 0
mean net return 20bps > 0
1-minute-delay mean net return 10bps > 0
block-bootstrap lower confidence evidence reported
concentration and drawdown gates reported
```

Never alter the strategy after Confirmation.

## 12. Iteration policy

Each registered iteration must contain:

```text
iteration_id
parent_iteration
hypothesis
observed funnel failure
one changed component
expected mechanism
frozen Development folds
fixed seeds
tests run
actual command
coverage metrics
economic metrics
accept/reject/inconclusive
next legal action
```

Continue autonomously through informative failures.

A failed challenger is not automatically terminal while a distinct,
predeclared Development-only funnel hypothesis remains.

Stop when:

```text
funnel collapse is explained and no legal repair passes Development;
a finalist set is frozen and Validation rejects all;
Confirmation accepts or rejects the champion;
a data/leakage contract fails;
a real resource boundary is reached.
```

## 13. Required outputs

Write only under:

`D:\us-tech-quant-results\fast3_autoresearch_generation3r3`

Required artifacts:

```text
generation3r3_data_usage_ledger.csv
generation3r3_split_contract.json
generation3r3_split_contract_sha256.txt
generation3r3_feature_contract.json
generation3r3_label_contract.json
generation3r3_candidate_registry.csv
generation3r3_candidate_funnel_counts.csv
generation3r3_flat_reason_counts.csv
generation3r3_feature_missingness.csv
generation3r3_probability_distributions.csv
generation3r3_probability_calibration.csv
generation3r3_regime_coverage.csv
generation3r3_overlap_attrition.csv
generation3r3_execution_mapping_audit.csv
generation3r3_threshold_coverage_surface.csv
generation3r3_development_walkforward_metrics.csv
generation3r3_random_window_metrics.csv
generation3r3_validation_frozen_candidates.json
generation3r3_validation_metrics.csv
generation3r3_leakage_audit.json
generation3r3_champion_record.json
generation3r3_checkpoint.json
generation3r3_final_summary.json
generation3r3_final_report.md
generation3r3_final_checkpoint.json
```

Do not copy canonical data or persist huge feature matrices.

## 14. Required tests

Before completing a meaningful stage:

```text
py_compile
focused pytest
actual runner execution
output-contract validation
registry update
checkpoint update
```

Test at least:

```text
PIT maximum-source timestamp
completed-bar semantics
30/60/120 path labels
funnel-count reconciliation
one primary rejection reason per row
probability quantile output
single-class fold handling
calibrator train-only isolation
regime fallback
ETF mapping
cost and delay
overlap suppression
deterministic seeds
Validation one-time guard
Confirmation zero-read and one-time guard
no broker/order object
idempotent rerun
```

## 15. Terminal statuses

Use exactly one terminal status:

```text
PASS_GENERATION3R3_CONFIRMATION_ACCEPTED
PASS_GENERATION3R3_VALIDATION_CHAMPION_FROZEN
PASS_GENERATION3R3_FUNNEL_DIAGNOSIS_COMPLETE
FAIL_IMPLEMENTATION_CONTRACT
FAIL_DATA_CONTRACT
FAIL_LEAKAGE_DETECTED
FAIL_FUNNEL_COLLAPSE_UNRESOLVED
FAIL_OVERFITTING_RISK
FAIL_NO_ROBUST_EDGE
FAIL_COST_SENSITIVITY
FAIL_DELAY_SENSITIVITY
FAIL_CONFIRMATION
PARTIAL_RESOURCE_LIMIT_CHECKPOINT_SAVED
```

A terminal response must print:

```text
FINAL_STATUS=<status>
```

A truly terminal checkpoint must contain:

```text
exact_resume_command=NONE_FAST3_GENERATION3R3_RESEARCH_STOPPED
```

Only `PARTIAL_RESOURCE_LIMIT_CHECKPOINT_SAVED` is resumable.

## 16. Immediate execution order

1. inspect only relevant Generation 3R2 code and artifacts;
2. freeze and hash the Generation 3R3 split and contracts;
3. implement complete funnel instrumentation;
4. reproduce C1-C6 and locate each zero-trade collapse;
5. fix any implementation contract defect before research changes;
6. run staged Development-only threshold and calibration diagnostics;
7. run compact model/fallback/overlap repairs;
8. run nested chronological walk-forward and 100 windows;
9. freeze at most 3 finalists;
10. open Validation once only if legal;
11. freeze at most one champion;
12. open Confirmation once only if legal;
13. finalize truthful artifacts and checkpoint.

Do not merely summarize this authorization. Begin actual implementation,
testing, execution, and iteration now.
