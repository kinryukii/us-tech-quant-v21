# FAST3 V22.084 SAMPLE-RECOVERY SIDE-SPECIFIC ENGINE — AUTHORIZATION AND HARD CONTRACT

## 1. Authority and safety

The Agent may inspect, create, modify, test, and run research code inside:

- Repository: `D:\us-tech-quant`
- Data root: `D:\us-tech-quant-data`
- Results root: `D:\us-tech-quant-results`

It may make non-destructive technical choices without asking for confirmation. It must run real code and report truthfully. It may never create or submit a broker order.

## 2. Single-stage rule

The only new stage is:

`V22.084_FAST3_SAMPLE_RECOVERY_SIDE_SPECIFIC_ENGINE_R1`

Do not create V22.084A/B/C, R2/R3, or a parallel engine. Keep one implementation area, one runner, one focused test file, one config, shared registries, one checkpoint, and one concise final report.

Canonical output root:

`D:\us-tech-quant-results\fast3_v22_084_sample_recovery_side_specific`

V22.081, V22.082, V22.083, and canonical data are read-only inputs and must not be overwritten.

## 3. Frozen budgets

Unless the launcher is stricter:

- Maximum generations: 4
- Maximum complete experiments per generation: 30
- Maximum complete experiments globally: 120
- Maximum active candidates: 3
- Maximum model families: 2
- Maximum active features: 20
- Stop after 2 generations without material OOS improvement
- Stop after the same primary failure twice without a genuinely new bounded hypothesis

## 4. Frozen facts from V22.083

- Four generations and 160 Development experiments completed.
- G01 consumed Validation but post-read evaluation encountered a NaN-label runtime error and correctly failed closed.
- G02 had insufficient sample and negative 20-bps delay performance.
- G03 was delay-positive but had only 6 trades on 1 unique day.
- G04 produced zero trades.
- No Confirmation or Global Final Holdout was opened.

These are negative/insufficient research results, not evidence of a tradable strategy.

## 5. Primary objective

Repair the data/label contract, restore defensible statistical power without forcing trades, and determine whether SOXL-long and SOXS-long have separate, stable, cost- and delay-robust event edges.

Final actions remain:

- `LONG_SOXL`
- `LONG_SOXS`
- `NO_TRADE`

## 6. Pre-validation eligibility contract

Before any Generation Validation read, require explicit finite-value and timestamp checks:

- `FEATURE_NAN_COUNT=0`
- `LABEL_NAN_COUNT=0`
- `ENTRY_PRICE_NAN_COUNT=0`
- `EXIT_PRICE_NAN_COUNT=0`
- `METRIC_INPUT_NAN_COUNT=0`
- `TIMESTAMP_ALIGNMENT_ERROR_COUNT=0`
- `NONFINITE_VALUE_COUNT=0`

Future-path-incomplete, session-boundary-incomplete, ETF-misaligned, or delayed-entry-unavailable samples must be marked `INELIGIBLE` before splitting/evaluation. Ineligibility counts and reasons must be persisted. Never consume a holdout and then discover preventable NaN/alignment defects.

## 7. Separate side-specific models

Train and calibrate separate models:

- `SOXL_LONG_MODEL`
- `SOXS_LONG_MODEL`

Do not force one symmetric direction model to represent both paths. Report side-specific sample size, calibration, delay decay, cost sensitivity, drawdown, regimes, and thresholds. A valid result may exist on only one side; the other side must remain NO_TRADE.

## 8. Decision architecture

Use:

1. One Opportunity hard gate.
2. Side-specific probability for SOXL-long and SOXS-long.
3. Entry-quality score.
4. Risk hard gate.
5. `FINAL_CONFIDENCE` combining opportunity, side probability, and entry quality.
6. Absolute minimum floor plus bounded Top-K ranking.

Top-K must not force trades. No candidate below the absolute floor may trade. Default cap: at most one new entry per side per trading day and at most two total new entries per trading day. Avoid overlapping duplicate events unless explicitly proven independent.

## 9. Statistical-power contract

Before interpreting Validation returns, require at least:

- 20 trades in a Generation Validation fold
- 10 unique trading days in a Generation Validation fold
- Target aggregate evidence across legal folds: at least 80 trades and 40 unique trading days

Also report trades per month and effective independent event count. If minimum power is absent, output `INSUFFICIENT_STATISTICAL_POWER`; do not call a handful of positive trades an edge.

Target NO_TRADE rate is 80%–98%, but sample sufficiency and independence remain mandatory.

## 10. Delay, cost, and labels

Evaluate actual SOXL/SOXS paths with 1, 3, and 5 minute execution delays and 5/10/20/30 bps costs. Zero-delay results are diagnostic only. Use 30/60/180 minute horizons and triple-barrier or an auditable equivalent.

Champion priority:

1. Worst-case 1/3/5-minute delay net performance
2. 20-bps net expectancy
3. Positive contiguous-fold rate
4. Maximum drawdown
5. Statistical power and independent days
6. Profit concentration
7. Simplicity

Never select by the best delay, best year, or best session.

## 11. Features and models

Use at most 20 active point-in-time, fully closed-bar features. Prefer existing reliable VIX, SOXX/QQQ relative strength, 5/15/30-minute returns, VWAP deviation, realized volatility, volume anomaly, gap, session, and trend/regime features. Semiconductor breadth is allowed only if already available with auditable PIT timestamps.

Allowed model families:

- Elastic Net Logistic Regression
- One constrained small HistGradientBoosting or equivalent

No deep learning, large forests, stacking, unlimited ensembles, unbounded optimization, or factor explosion.

Each generation may add at most two features and remove at most two. Each mutation may change one model family, three hyperparameters, two thresholds, one label horizon, and one exit rule.

## 12. Time splits and consumed holdouts

Audit all V22.081–V22.083 split manifests and holdout-read records. Previously opened Validation/Confirmation periods cannot be presented as untouched. Before fitting V22.084, predeclare and hash contiguous Development/Internal Validation/Generation Validation/Generation Confirmation folds plus one Global Final Holdout.

Use purge and embargo for maximum label horizon. A Generation Validation or Confirmation fold can be read once only. A consumed fold can never be reopened as unseen. If insufficient untouched data remains, stop with `INSUFFICIENT_UNTOUCHED_HOLDOUT`.

A generation failure closes that generation, not the entire stage, when a legal untouched next fold and budget remain.

## 13. Hard risk and robustness gates

Reject candidates for:

- Any single Validation-fold MDD >25%
- Aggregate Validation MDD >20%
- Confirmation MDD >20%
- Material 3-minute or 5-minute sign reversal
- Material collapse at 20 bps
- Profit dominated by fewer than 5% of trades
- Uncontrolled tail loss
- Insufficient independent days
- Side-specific calibration failure
- Weight/feature direction instability

High return cannot compensate for a hard-gate failure.

## 14. File-growth controls

Use shared artifacts:

- `data_eligibility_contract.json`
- `frozen_split_manifest.json`
- `experiment_registry.jsonl`
- `generation_registry.jsonl`
- `v22_084_checkpoint.json`
- `champion_config.json`
- `v22_084_summary.json`
- `v22_084_summary.txt`
- `v22_084_report.md`
- side-specific diagnostics and key trade detail tables

Do not create one directory/report per experiment. Keep only baseline and top three model binaries.

## 15. Tests

Actually run compile and focused tests covering:

- closed-bar PIT features
- feature/label alignment
- all finite-value and NaN eligibility gates
- delayed entry availability
- SOXL/SOXS side mapping and separate models
- cost deductions
- purge/embargo and fold non-overlap
- consumed holdout protection
- Global Holdout one-read protection
- absolute floor plus Top-K without forced trades
- daily entry caps and duplicate-event prevention
- statistical-power gates
- drawdown/concentration/tail gates
- experiment/generation/feature/candidate budgets
- resume idempotency and checkpoint restore
- broker/order permissions

## 16. Terminal conditions

Create `V22_084_GLOBAL_DONE.flag` only for a legal terminal state:

- Legal success after one-time Global Final Holdout
- Maximum generations or experiments reached
- Two generations without material OOS improvement
- Same primary failure twice without a new bounded hypothesis
- No untouched holdout remains
- Stable negative evidence across both allowed model families
- Insufficient statistical power that cannot be repaired within bounds
- Unrepairable leakage/data-integrity defect
- Agent/compute budget exhaustion after a valid resumable checkpoint

A candidate failure alone is not a global terminal state.

## 17. Permissions

Before legal final success:

- `paper_trading_allowed=false`
- `shadow_allowed=false`
- `broker_action_allowed=false`
- `official_adoption_allowed=false`

After legal final success, only paper/shadow may become true. Broker action and official adoption remain false.
