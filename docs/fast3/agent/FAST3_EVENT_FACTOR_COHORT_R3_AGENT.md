# FAST3 Event-Factor Cohort R3 Agent Contract

## 0. Mission

Execute one bounded real-data research cycle that follows this sequence:

1. discover factor laws on pre-frozen complete-cohort time blocks;
2. freeze the stable factor columns;
3. train the six already-approved model configurations on separate purged walk-forward blocks;
4. freeze one final configuration;
5. run one untouched historical robustness audit plus five null-economic baselines;
6. stop with one explicit allowed decision.

This is **not** authorization for an open-ended model search. Do not keep changing factors, thresholds, blocks, labels, models, or costs until a result passes.

R2 proved that 100% event-to-`NO_EVENT` matching is structurally infeasible for SOXX overnight and premarket under the fixed reuse and balance constraints. Therefore R3 must use the full non-ambiguous three-class cohort for discovery and fitting. R2 matching evidence is auxiliary only.

## 1. Mandatory prior evidence import

Read both prior runs from the environment:

- `FAST3_R1_INVALID_RUN_ROOT`
- `FAST3_R2_CONTROL_STOP_ROOT`

Validate before any R3 law result:

- R1 final decision is `STOP_IMPLEMENTATION_INVALID`;
- R1 event count is 517,196;
- R1 observed block count is at least 14;
- R2 final decision is `STOP_CONTROL_MATCH_INCOMPLETE_BEFORE_TRAINING`;
- R2 matched/unmatched counts are 477,456 / 39,740;
- R2 training rounds are 0;
- R2 factor-law/model fit and null audit are false.

Write `FAST3_PRIOR_RUN_IMPORT.json`.

Import every R1 observed block from `FAST3_ROUND_LEDGER.jsonl`, add the frozen 24-hour buffer on each side, and prohibit reuse in law discovery, model fitting, model selection, and final audit. R2 schedule-only blocks were never evaluated by a factor/model/final-audit result and are not automatically quarantined. State this distinction explicitly.

Do not use R1's seven observed stable factors as the R3 factor set. Recompute laws from the complete cohort.

## 2. Code scope

Allowed:

- modify only `fast3/src/fast3/event_factor_law_discovery.py`;
- optionally add one focused unit-test file;
- reuse existing FAST3 portfolio, PIT, and data-loading modules;
- add R3 stages and reports inside the existing implementation.

Forbidden:

- new core research modules;
- new V22 chain;
- Atlas, Guard, Registry, orchestration framework, or nested runner;
- factor additions;
- factor deletions based on model/economic results;
- new model families or configurations;
- threshold/top-fraction search;
- background or detached Python;
- canonical-data writes;
- Git stage/commit/push;
- Broker or order actions.

Record exact changed files in the final summary.

Before any real-data law result, run Python compilation and focused tests covering:

- complete cohort counts and Confirmation isolation;
- R1 observed-block quarantine and deterministic R3 schedule;
- train-only computation of weights, scaling, bins, splines, and sampling;
- prohibition on actual labels/future ETF paths in selection and priority;
- actual ETF target-hit timestamps releasing capital;
- identical execution contracts for learned and null models;
- decision-aware artifact validation for legal early stops.

A failed compile or focused test requires `STOP_DATA_OR_IMPLEMENTATION_INVALID`. Tests-only or synthetic-only execution is not completion.

## 3. Source and cohort gate

Use canonical minute data read-only. The logical clock is `timestamp_et` in `America/New_York`.

No row at or after `2025-02-08 00:00:00 ET` may be loaded into research data. The fixed Development cutoff is `2025-01-31 23:59:59 ET`.

Build or hash-verify the complete R3 cohort. Expected counts under the frozen source are:

- total candidate rows: 729,487
- `UP_FIRST`: 263,118
- `DOWN_FIRST`: 254,078
- `NO_EVENT`: 212,213
- `AMBIGUOUS`: 78
- total events: 517,196

If counts differ, compare source partition hashes with R1/R2 evidence. A documented source change must be identified before any law result; otherwise stop `STOP_DATA_OR_IMPLEMENTATION_INVALID`.

Write `FAST3_COHORT_AUDIT.json`.

## 4. Event and execution definition

Do not change:

- underlying: QQQ/SOXX;
- five-minute decision grid;
- entry: next valid minute open;
- horizon: 24 natural hours;
- first passage: +1% or -1%;
- classes: `UP_FIRST`, `DOWN_FIRST`, `NO_EVENT`;
- same-minute dual hit: `AMBIGUOUS`, excluded;
- opportunity probability threshold: 0.60;
- Top fraction: 5%;
- ETF mapping: TQQQ/SQQQ/SOXL/SOXS;
- costs: 10bps and 20bps round trip;
- one account, one full-notional position.

The model score is:

- `opportunity_probability = P(UP_FIRST)+P(DOWN_FIRST)`
- `combined_score = max(P(UP_FIRST), P(DOWN_FIRST))`
- predicted direction is the larger directional probability.

Selection and priority must never use actual labels, future ETF paths, target-hit information, or realized returns.

Correct capital occupancy must be used:

- if the ETF first reaches +3%, exit timestamp is the actual first target-hit minute;
- otherwise exit timestamp is the timeout minute at/before the 24-hour horizon.

Do not hold a target-hit trade until the horizon merely for convenience. The null models must use the same actual exits.

## 5. Complete-cohort weighting

Use every non-ambiguous row. A matched control is not required.

Inside each training fold only, compute:

- uniqueness weight = inverse concurrent 24-hour label-window count;
- class weight = `N_train/(3*N_class)`, normalized to mean 1;
- era weight = inverse train-row count per frozen two-year era, normalized to mean 1;
- total weight = product, clipped to [0.05, 10].

Do not balance, resample, or alter the natural test-block distribution.

Random row splitting is forbidden.

## 6. Freeze random blocks before law results

Use scheduler seed `314159`.

After importing R1 observed blocks and before producing any R3 law result:

1. find eligible 60-calendar-day windows before the Development cutoff;
2. exclude every R1 observed block plus 24 hours on both sides;
3. require new blocks to be non-overlapping and separated by at least five calendar days;
4. deterministically choose 14 blocks with the fixed seed;
5. sort them chronologically;
6. assign roles:
   - first 3: `LAW_DISCOVERY`;
   - next 2: `MODEL_ROUND_1`;
   - next 2: `MODEL_ROUND_2`;
   - next 2: `MODEL_ROUND_3`;
   - final 5: `FINAL_AUDIT`.

Write `FAST3_RANDOM_BLOCK_SCHEDULE.json` and the frozen schedule hash into `FAST3_R3_COHORT_CONTRACT.json`.

If 14 valid windows cannot be frozen without changing these rules, stop before law discovery with `STOP_INSUFFICIENT_FRESH_BLOCKS`.

Historical blocks are Development/Robustness evidence, not clean frozen validation.

## 7. Factor law discovery

The factor dictionary, 20 base channels, 80 derived columns, nine-turn fields, and eight interactions must exactly match the R1 dictionary hash.

Use only the three `LAW_DISCOVERY` blocks to discover laws.

For every frozen derived column, separately estimate weighted one-vs-rest linear effects for:

- `UP_FIRST`;
- `DOWN_FIRST`;
- `NO_EVENT`.

Also produce pre-frozen quintile curves and restricted quadratic-spline marginal curves. All bins, scaling, imputation, and splines are fit inside the applicable training block only.

Do not rely on ordinary row-level p-values from hundreds of thousands of overlapping observations. Stability is determined by time-block direction, clustered/block uncertainty, trimmed direction, session support, and year support.

A stable column must satisfy the thresholds in the limits file. Rank stable columns only by the frozen stability ranking. Economic returns, Top5 lift, and ETF outcomes are forbidden from factor ranking.

Freeze no more than 24 columns and no more than 12 base channels in `FAST3_FACTOR_LAW_FREEZE.json`.

If no stable column survives, write the linear/nonlinear files, summary, report, and stop `STOP_NO_STABLE_FACTOR_LAWS`.

## 8. Model rounds

Run the exact six configurations:

- `linear_0.1`
- `linear_1.0`
- `spline_0.1`
- `spline_1.0`
- `hgb_leaf7`
- `hgb_leaf15`

Use the exact five seeds:

- 104729
- 130363
- 155921
- 196613
- 262147

All six configurations must run on all six model blocks. The three rounds are repeated robustness evaluations of the same frozen configurations, not an invitation to modify anything between rounds.

For each test block:

- training rows must be chronologically earlier than the block;
- apply at least 24-hour purge and 24-hour embargo;
- exclude all R1 quarantined rows;
- fit imputation, scaling, splines, sampling, and weights only on training rows;
- use the fixed seed-stratified cap of 12,000 rows per class per seed;
- preserve the natural test distribution.

Checkpoint each foreground block. No detached process.

Write:

- `fast3_model_selection_results.csv`
- `fast3_training_predictions.parquet`
- `FAST3_MODEL_FREEZE.json`

Select the final configuration by the exact hierarchy in the limits file. Freeze it before the first final-audit result.

## 9. Final audit and nulls

Run the frozen configuration once across the five `FINAL_AUDIT` blocks under the fixed five seeds and frozen walk-forward procedure.

After the learned model is evaluated, run these nulls on the same block/seed units and execution contract:

1. shuffled direction on the learned model's selected timestamps;
2. shuffled score pairs over full candidates while preserving the learned direction labels;
3. random score plus random direction;
4. always UP on the learned selected timestamps;
5. always DOWN on the learned selected timestamps.

The null audit may not trigger any retraining, factor change, model change, block change, threshold change, or rerun.

Write:

- `fast3_final_audit_results.csv`
- `fast3_null_model_results.csv`
- `fast3_event_predictions.parquet`
- `FAST3_EXECUTION_SANITY_AUDIT.json`

The execution sanity audit must include target-hit/timeout decomposition, direction/economic cross-tabs, overlap rejection, actual target-hit exits, and checks that no trade exceeds the mechanically possible target return after costs.

## 10. Auxiliary matched diagnostic

Only after factor and model freezes, read R2 matched pairs as a common-support explanatory diagnostic.

Report:

- R2 coverage and unmatched count;
- R2 balance failure and Tier-4 excess;
- sign concordance of the R3 frozen laws inside the available R2 matched subset.

This diagnostic must not select factors/models, change the final decision, or cause retraining.

Write `FAST3_AUX_MATCHED_DIAGNOSTIC.json`.

## 11. Final decision order

Use this decision order:

1. Any source, leakage, implementation, artifact, schedule, score-selection, target-exit, or contract violation:
   `STOP_DATA_OR_IMPLEMENTATION_INVALID`
2. Insufficient frozen blocks before laws:
   `STOP_INSUFFICIENT_FRESH_BLOCKS`
3. No stable laws:
   `STOP_NO_STABLE_FACTOR_LAWS`
4. Final lift below 1.50, or paired lift improvement over legacy 1.36122855 does not have CI lower bound > 0:
   `STOP_NO_SIGNIFICANT_GAIN_OVER_LEGACY`
5. Learned model does not significantly beat the strongest null in both lift and 10bps net return:
   `STOP_NULL_ECONOMIC_BASELINE_NOT_BEATEN`
6. Cost or trimmed-return gates fail:
   `STOP_NOT_ECONOMIC_AFTER_COST`
7. random-block, seed, concentration, or accepted-trade stability gates fail:
   `STOP_RANDOM_TIME_BLOCK_INSTABILITY`
8. All gates pass:
   `PASS_READY_FOR_PROSPECTIVE_FORWARD_SHADOW`

A pass authorizes only a prospective forward shadow, not paper/live orders and not historical frozen-validation claims.

## 12. Required final summary

Always write:

- `fast3_event_factor_r3_summary.json`
- `FAST3_EVENT_FACTOR_R3_REPORT.md`
- `FAST3_ROUND_LEDGER.jsonl`

The summary must contain every key listed in the limits file. For stages not reached, use explicit `NOT_RUN`, `null`, or zero values rather than omitting keys.

The launcher uses decision-aware artifact requirements. A valid early stop must not be mislabeled incomplete merely because downstream training artifacts correctly do not exist.

End the Codex final message with compact key-value lines and the exact local report path.
