# FAST3 Event-Factor Law Discovery R2 — Restricted Repair Contract

## 0. Mission and authority

This is **one bounded R2 repair**, not a new strategy search. Execute real data now. The sole authorized research changes are:

1. repair the R1 event-to-NO_EVENT matched-control integrity failure;
2. quarantine every random block observed in R1;
3. add frozen null-economic baselines to determine whether the apparent leveraged-ETF profit comes from prediction or from the execution/path rule;
4. rerun the same factor-law and six-configuration research chain on new continuous time blocks.

Do not add factors, delete factors for performance, alter the ±1% label, alter the 24-hour horizon, alter 0.60, alter Top5%, alter costs, alter the four ETF mappings, add model families, or search new hyperparameters.

The authoritative machine-readable limits file is:

`config/fast3/agent/FAST3_EVENT_FACTOR_LAW_DISCOVERY_R2_LIMITS.json`

If this document and that JSON differ, use the stricter requirement.

## 1. Required R1 source and status

Read the immutable R1 invalid run from `FAST3_R1_INVALID_RUN_ROOT`, expected to resolve to run `20260802_184840`. Verify before any repair:

- `FINAL_STATUS=EXECUTED_REAL_DATA_CONTRACT_INTEGRITY_FAILURE`
- `FINAL_DECISION=STOP_IMPLEMENTATION_INVALID`
- event count 517,196
- matched event count 505,308
- unmatched event count 11,888
- no post-audit retraining occurred

R1 performance numbers are invalid for adoption. R1 may be read only to import retired blocks, freeze the exact factor dictionary/model list, diagnose unmatched strata, and verify hashes.

## 2. Preserve R1 and isolate R2

Never overwrite or edit R1 artifacts. Write every R2 artifact only under `FAST3_RESULTS_ROOT`.

Before any factor-law computation, produce:

- `FAST3_EVIDENCE_LEDGER.json`
- `FAST3_R1_RETIREMENT_IMPORT.json`
- `FAST3_R2_REPAIR_CONTRACT.json`

Import every R1 `START`/`END` random block from `FAST3_ROUND_LEDGER.jsonl`. Apply a 24-hour quarantine buffer to both sides. Rows inside those ranges are forbidden from R2 factor selection, fitting, model selection, training-block evaluation, and final audit. `R1_RETIRED_BLOCK_REUSE_COUNT` must equal zero.

## 3. Diagnose the 11,888 unmatched events before changing matching

Using the immutable R1 event ledger, write `FAST3_UNMATCHED_CONTROL_DIAGNOSTIC.csv` with at least:

- underlying
- direction label
- raw and normalized session
- year and era
- volatility bucket
- time-of-week bucket
- weekday
- month
- VIX bucket if present
- candidate-control count at each frozen matching tier

This diagnostic is descriptive only. It may not be used to invent a new tier, new covariate, factor, threshold, or subgroup after viewing it. The matching tiers are already frozen in the limits JSON.

## 4. Deterministic matched-control repair

Recompute control matching for every `UP_FIRST` and `DOWN_FIRST` event. Use exactly one primary `NO_EVENT` control per event. Matching covariates must be available at the decision time. Event and control decision timestamps must be separated by at least 48 hours.

Apply tiers 0–4 in the exact frozen order from the limits JSON. Within a tier choose by:

1. lowest current control reuse;
2. lowest frozen standardized distance;
3. earliest control timestamp;
4. lexical control ID.

A control may be reused at most eight times. No synthetic controls, no label substitution, no dropping unmatched events, no changing buckets, and no post-result tier widening.

Before any law discovery or model fit, write:

- `FAST3_CONTROL_MATCH_AUDIT.json`
- `fast3_event_control_pairs.parquet`

Hard pre-training gates:

- every real event has exactly one eligible control;
- unmatched count is zero;
- no control exceeds reuse 8;
- tiers 0–3 cover at least 95%;
- tier 4 covers at most 3%;
- absolute standardized mean difference for every frozen matching covariate is at most 0.10;
- no event/control pair violates the 48-hour separation;
- no Confirmation row is read.

If any gate fails, stop **before** factor-law discovery and training with `STOP_CONTROL_MATCH_INCOMPLETE_BEFORE_TRAINING`. Preserve diagnostics and do not loosen the rules.

## 5. Freeze factors and configurations exactly

Import and hash the R1 `FAST3_FACTOR_DICTIONARY.json`. The R2 dictionary, base channels, derived columns, nine-turn definitions, and eight interactions must match R1 exactly.

The R1 seven-factor stable subset is not automatically accepted because R1 matching was invalid. Recompute linear and nonlinear laws after the repaired matching, using the same pre-registered stability tests. No factor addition or performance-driven deletion is allowed.

Use exactly six configurations:

- `linear_0.1`
- `linear_1.0`
- `spline_0.1`
- `spline_1.0`
- `hgb_leaf7`
- `hgb_leaf15`

Use exactly five seeds: 104729, 130363, 155921, 196613, 262147.

## 6. New continuous-block schedule

After importing R1 quarantine ranges, but before seeing repaired control, factor, or model results, freeze 14 entirely new non-overlapping 60-calendar-day blocks:

- three training rounds × three blocks;
- one final audit × five blocks.

Each block needs 24-hour purge and 24-hour embargo, at least five calendar days from another R2 block, and zero overlap with any quarantined R1 interval including its buffer. Observed R2 blocks are retired immediately. Never call these historical blocks a clean holdout.

## 7. Bounded execution

Run only checkpointed foreground stages. Do not spawn detached/background Python. Ordinary implementation defects may be repaired only before a valid stage result exists and must be logged. They do not authorize parameter or factor changes.

Run:

1. evidence/R1 import and schedule freeze;
2. unmatched diagnostic and full matching;
3. pre-training integrity gate;
4. linear and nonlinear factor laws;
5. three fixed training rounds;
6. freeze the candidate;
7. exactly one final audit;
8. null-economic audit inside the same final blocks;
9. final integrity and artifact verification.

Final audit may never trigger more fitting, feature selection, threshold changes, or new blocks.

## 8. Null-economic audit

The learned candidate must be compared with the five frozen nulls in the limits JSON using the same final blocks, seeds, Top5 mechanics, 0.60 threshold where applicable, single-account portfolio, leveraged ETF mapping, 3% target/24-hour timeout path, and 10/20bps costs.

For same-selected-timestamp nulls, preserve the learned candidate's selected timestamps and underlyings, changing only the specified direction component. For score nulls, use the full candidate universe and the same selected-count/Top5 contract. Never use realized labels to choose priority or direction.

Report for learned and every null:

- selected signals and accepted trades;
- direction accuracy;
- target hit rate and timeout rate;
- mean timeout return;
- lift;
- net 10bps and 20bps;
- overlap rejections;
- drawdown and concentration.

Use 10,000 paired block-level bootstrap resamples. The learned model must beat the strongest null with CI lower bound above zero for both net 10bps and lift. Otherwise stop with `STOP_NULL_ECONOMIC_BASELINE_NOT_BEATEN`. Do not retune.

## 9. Execution sanity

A 3% gross return may be assigned only after the mapped ETF path actually crosses the 3% target after entry and before timeout. The selected score, priority, direction, entry, or exit must never use the realized event label or future ETF path.

Explicitly test and report:

- target-hit net 10bps does not exceed 2.90001%;
- accepted-trade direction accuracy is computed from frozen predictions;
- timeout returns use the actual valid timeout price;
- learned and null strategies use identical portfolio/cost machinery;
- all PIT/leakage tests pass;
- Confirmation rows read = 0.

## 10. Final decision order

Use the first applicable outcome:

1. control gate failed → `STOP_CONTROL_MATCH_INCOMPLETE_BEFORE_TRAINING`;
2. data, leakage, retirement, or execution integrity failed → `STOP_DATA_CONTRACT_INVALID` or `STOP_IMPLEMENTATION_INVALID`;
3. no stable factor law → `STOP_NO_STABLE_FACTOR_LAWS`;
4. learned candidate failed to beat strongest null → `STOP_NULL_ECONOMIC_BASELINE_NOT_BEATEN`;
5. lift/significance failed → `STOP_NO_SIGNIFICANT_PREDICTIVE_GAIN`;
6. cost gate failed → `STOP_NOT_ECONOMIC_AFTER_COST`;
7. random-block stability failed → `STOP_RANDOM_TIME_BLOCK_INSTABILITY`;
8. all gates passed → `PASS_READY_FOR_PROSPECTIVE_FORWARD_SHADOW`.

Historical success never authorizes trading or Frozen Validation. It only permits a new prospective forward shadow.

## 11. Required final artifacts

All artifacts listed in the limits JSON must exist and contain real, non-placeholder results. The final summary is `fast3_event_factor_r2_summary.json`; the report is `FAST3_EVENT_FACTOR_R2_REPORT.md`.

The final console message must include:

- `FINAL_STATUS`
- `FINAL_DECISION`
- `RUN_ID`
- control coverage, tier ratios, max reuse, balance gate
- R1 retired-block import and reuse count
- factor/config/seed/round counts
- learned lift, legacy delta CI
- learned 10/20bps economics
- strongest null and learned-minus-null CIs
- target-hit and timeout diagnostics
- accepted trades, drawdown, concentration
- leakage tests and Confirmation reads
- code files added/modified
- report path

No Git stage/commit/push, no canonical-data write, no broker call, and no order generation.
