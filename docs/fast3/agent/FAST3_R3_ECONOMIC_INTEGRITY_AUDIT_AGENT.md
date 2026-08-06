# FAST3 R3 Economic Integrity Post-Audit Agent

## Mission

Audit the already-frozen R3 economic outputs without changing or rerunning the research model.

Source R3:

- run id: `20260802_211307`
- final decision: `STOP_NO_SIGNIFICANT_GAIN_OVER_LEGACY`
- frozen model: `hgb_leaf7`
- accepted record count: 696
- target-hit records: 691
- timeout records: 5

The audit asks whether the strong historical economic result survives:

1. removal of seed-level duplicate counting;
2. target-hit timestamp verification;
3. conservative execution stress;
4. clustering by the five final blocks and natural weeks;
5. subgroup and concentration decomposition.

A clean audit does **not** change R3's predictive stop and does not promote the strategy. It only determines whether a separately pre-registered two-stage R4 is methodologically worth testing.

## Hard boundary

Do not:

- run factor discovery;
- fit or refit any model;
- select a model;
- regenerate predictions;
- execute the R3 research pipeline;
- alter the 0.60 threshold, Top5, labels, target, horizon, ETF mapping, costs, or portfolio rules;
- modify any repository code;
- write canonical data;
- read Confirmation rows;
- perform Git or Broker actions;
- start background/detached Python.

All scripts, notebooks, temporary files and final artifacts must be created only under `FAST3_RESULTS_ROOT`.

## 1. Validate and hash frozen inputs

Read `FAST3_R3_SOURCE_ROOT` and validate the exact summary fields in the limits file.

Require the frozen files listed under `read_only_inputs`. Record for each:

- absolute path;
- byte size;
- SHA256;
- modified time.

Write `FAST3_R3_POST_AUDIT_EVIDENCE.json`.

Do not alter the source R3 directory.

## 2. Reconstruct accepted frozen records only

Read `fast3_event_predictions.parquet`.

Use the exact filter:

```text
trade_accepted == True
and mapping_status == "SUCCESS"
```

Validate:

- 696 accepted records;
- 691 target hits;
- 5 timeouts;
- all records belong to the frozen five Final Audit blocks;
- no record is after the Development/allowed frozen horizon;
- no target-hit exit is after its frozen horizon;
- entry, actual exit, timeout and horizon timestamp units are coherent.

Use existing columns where available. Resolve semantically equivalent names explicitly in the evidence. Do not infer values from labels or future outcomes.

## 3. Deduplication audit

Produce all required duplicate statistics.

Primary unique key:

```text
candidate_id + predicted_label + execution_etf
```

For duplicate records sharing this key, require identical:

- underlying;
- decision and entry timestamps;
- horizon;
- predicted direction;
- execution ETF;
- target-hit flag;
- actual exit timestamp;
- gross return;
- 10bps and 20bps net returns.

A discrepancy is an integrity failure.

Create `fast3_r3_unique_trade_ledger.parquet` by retaining the lexical-lowest seed record only after equality checks. Add:

- `seed_multiplicity`;
- sorted list of contributing seeds;
- sorted list of contributing block/seed units;
- conflict flags;
- natural decision week.

Also report unique candidate count, unique decision-time count, multiplicity distribution, seed-pair Jaccard overlaps, and direction disagreements.

Write `FAST3_R3_DEDUP_AUDIT.json`.

## 4. Target-hit timing audit

For seed-weighted accepted records and the primary deduplicated ledger:

- calculate minutes from frozen entry to frozen actual target exit;
- validate units against canonical minute timestamps;
- report the frozen cumulative bins: 1, 5, 15, 60, 180, 360, 720, 1440 minutes;
- report the required quantiles;
- break down by block, ETF, direction, and session.

Write:

- `FAST3_R3_TARGET_HIT_TIMING_AUDIT.json`
- `fast3_r3_target_hit_timing.csv`

## 5. Read-only canonical execution verification

Read only TQQQ/SQQQ/SOXL/SOXS canonical minute rows required by the 696 frozen accepted records from entry through horizon.

Do not load any row at or after the Confirmation start. Do not write canonical files.

For every trade verify:

- entry open maps to the frozen entry;
- frozen first-hit minute high reaches the target;
- previous valid minute before the first hit does not reach it;
- hit minute validity and volume;
- next valid minute open;
- timeout minute and price;
- actual exit timestamp.

Any timestamp-unit or first-hit contradiction is invalid.

## 6. Frozen execution stress

Evaluate the exact pre-registered scenarios from the limits file:

- `BASELINE_FROZEN`
- `TARGET_EXIT_HAIRCUT_5BPS`
- `TARGET_EXIT_HAIRCUT_10BPS`
- `NEXT_VALID_MINUTE_OPEN_AFTER_HIT`
- `POSITIVE_VOLUME_HIT_REQUIRED`

Do not search additional target prices, waiting periods, thresholds or execution variants.

Calculate both seed-weighted and primary-deduplicated results at 10bps and 20bps. Preserve the already accepted trade timestamps; do not perform new signal selection.

Write:

- `FAST3_R3_EXECUTION_STRESS_AUDIT.json`
- `fast3_r3_execution_stress_results.csv`

## 7. Subgroup decomposition

Using the frozen accepted records and primary deduplicated ledger, report the required metrics by:

- underlying;
- ETF;
- predicted direction;
- session;
- Final Audit block;
- seed.

Write `fast3_r3_subgroup_audit.csv`.

Calculate positive PnL contribution using sums of positive 10bps PnL. Report maximum block and ETF concentrations.

## 8. Correct clustered uncertainty

Run exactly 10,000 resamples for each frozen method and seed.

A. Final-block cluster bootstrap:

- sample the five Final Audit blocks with replacement;
- retain all seed rows in a sampled block;
- estimate baseline net10 and net20 uncertainty.

B. Natural-week bootstrap:

- use primary deduplicated trades;
- sample natural decision weeks with replacement.

C. Primary-trade bootstrap:

- sample primary unique trades with replacement.

D. Learned versus strongest null:

- read `fast3_null_model_results.csv`;
- identify the strongest null using its frozen mean 10bps result;
- resample Final Audit blocks, not block-by-seed rows;
- report learned-minus-null net10 and lift CIs.

Write `FAST3_R3_CLUSTERED_UNCERTAINTY_AUDIT.json`.

## 9. Decision

Apply the exact decision order and gates from the limits file.

Allowed decisions only:

- `STOP_R3_DATA_OR_IMPLEMENTATION_INVALID`
- `STOP_R3_DUPLICATE_INFLATION_MATERIAL`
- `STOP_R3_EXECUTION_ASSUMPTION_FRAGILE`
- `STOP_R3_CLUSTER_UNCERTAINTY_NOT_ROBUST`
- `PASS_R3_ECONOMIC_IMPLEMENTATION_AUDIT_CLEAN`

Regardless of the audit result, preserve:

```text
SOURCE_R3_DECISION=STOP_NO_SIGNIFICANT_GAIN_OVER_LEGACY
MODEL_OR_FACTOR_RETRAINING_PERFORMED=false
```

Write:

- `fast3_r3_post_audit_summary.json`
- `FAST3_R3_POST_AUDIT_REPORT.md`

Every required summary key must be present. Use explicit null/zero values for stages that could not complete.

End your final message with compact key-value lines and the exact report path.
