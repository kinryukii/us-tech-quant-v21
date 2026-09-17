# FAST3 V22.083 DELAY-ROBUST SPARSE EVENT ENGINE — AUTHORIZATION AND HARD CONTRACT

## 1. Scope and authority

The Agent is authorized to inspect, create, modify, test, and run research code inside:

- Repository: `D:\us-tech-quant`
- Data root: `D:\us-tech-quant-data`
- Results root: `D:\us-tech-quant-results`

The Agent may autonomously choose non-destructive technical details. It must execute real code and report truthful results. It may not create or submit broker orders.

## 2. Single-stage rule

The only stage is:

`V22.083_FAST3_DELAY_ROBUST_SPARSE_EVENT_ENGINE_R1`

Do not create V22.083A/B/C, R2/R3, or a parallel architecture. Maintain one engine, one runner, one focused test file, one config, one experiment registry, one generation registry, one checkpoint, and one concise report.

Canonical output root:

`D:\us-tech-quant-results\fast3_v22_083_delay_robust_sparse_event`

V22.081 and V22.082 frozen results are read-only inputs and must not be overwritten.

## 3. Frozen budgets

Unless the launcher budget is lower, enforce:

- Maximum generations: 4
- Maximum complete experiments per generation: 40
- Maximum complete experiments globally: 160
- Maximum active candidates: 3
- Maximum model families: 2
- Maximum active features: 25
- Consecutive generations without material improvement: 2
- Same primary failure twice without a genuinely new bounded hypothesis: stop

No experiment may silently exceed these limits.

## 4. Primary objective

Find sparse SOXL/SOXS event decisions that remain economically positive under realistic execution delay. Final actions are only:

- `LONG_SOXL`
- `LONG_SOXS`
- `NO_TRADE`

The engine must prefer no trade when opportunity, direction, entry quality, delay robustness, cost coverage, or risk constraints are insufficient. Target NO_TRADE rate is 70%–95%, but sample sufficiency remains mandatory.

## 5. Required V22.082 G03 diagnostic

Before model search, perform a read-only decomposition of G03 by year, month, VIX regime, trend regime, session, long/short side, entry delay, holding window, exit type, MFE, MAE, drawdown source, and profit concentration. Record reusable and rejected components. Do not patch individual losing dates.

## 6. Delay-robust labels

Every eligible decision time must evaluate actual tradable SOXL/SOXS paths with entry delays of 1, 3, and 5 minutes. Zero delay is diagnostic only and cannot select the champion.

Evaluate at least 30, 60, and 180 minute horizons using triple-barrier or an auditable equivalent. Record barrier order, net return, MFE, MAE, and execution path. Champion selection must prioritize conservative worst-case or conservative aggregate delay performance, never the best delay.

## 7. Three-stage decision contract

Implement logically separate outputs:

1. Opportunity: whether a net tradable path exists.
2. Direction: UP, DOWN, or UNCERTAIN.
3. Entry timing: ENTER_NOW, WAIT_3_MIN, WAIT_5_MIN, or NO_TRADE.

Uncertain or unsafe decisions must become NO_TRADE.

## 8. Feature and model controls

Use only point-in-time, fully closed-bar features with explicit timestamp, lag, missingness, availability, and leakage tests. Active features must not exceed 25. Each generation may add at most two and remove at most two.

Allowed primary model families:

- Elastic Net Logistic Regression
- Small constrained HistGradientBoosting or equivalent constrained gradient boosting

No deep learning, large forests, stacking, unlimited ensembles, unbounded Bayesian search, or automatic indicator explosion.

## 9. Time split and holdout consumption

Predeclare and hash all folds before model fitting:

`Train -> Purge -> Embargo -> Internal Validation -> Embargo -> Generation Validation -> Generation Confirmation`

Also predeclare one Global Final Holdout. Generation Validation and Confirmation are one-read gates. A consumed holdout can never be reopened as unseen. A generation-level failure closes that generation only. If another untouched predeclared fold remains and no global stop rule applies, classify the failure and continue to the next generation.

Global Final Holdout may be read once only. If untouched folds are insufficient, stop with `INSUFFICIENT_UNTOUCHED_HOLDOUT`.

## 10. Required stress conditions

Each candidate must be assessed at:

- Costs: 5, 10, 20, 30 bps
- Entry delay: 1, 3, 5 minutes
- Multiple contiguous-time walk-forward folds
- Multiple seeds where model stochasticity exists
- Relevant regimes and both SOXL/SOXS directions

## 11. Hard risk gates

Default hard gates:

- Single Validation fold maximum drawdown > 25%: reject
- Aggregate Validation maximum drawdown > 20%: reject
- Confirmation maximum drawdown > 20%: fail
- Material sign reversal at 3 or 5 minute delay: reject or explicit diagnostic downgrade
- Material collapse at 20 bps: reject
- Profit primarily from fewer than 5% of trades: reject or concentration failure
- Insufficient independent trade days: `INSUFFICIENT_SAMPLE`

High return cannot compensate for a hard-gate breach.

## 12. Bounded generation mutation

A generation may change at most:

- One model family
- Three model hyperparameters
- Two probability/trading thresholds
- One label horizon
- One exit rule
- Two feature additions and two removals

Every mutation must record parent generation, failure class, reason, changed features, parameters, thresholds, label, and exit rule.

## 13. Failure classes

Support at least:

`DELAY_SENSITIVITY`, `SIGN_REVERSAL`, `EXCESS_DRAWDOWN`, `REGIME_DEPENDENCE`, `LONG_SHORT_ASYMMETRY`, `PROFIT_CONCENTRATION`, `COST_SENSITIVITY`, `INSUFFICIENT_SAMPLE`, `WEIGHT_INSTABILITY`, `CALIBRATION_FAILURE`, `ENTRY_TIMING_FAILURE`, `DIRECTION_FAILURE`, `OPPORTUNITY_FAILURE`, `ETF_PATH_MAPPING_FAILURE`.

Failure must trigger bounded diagnosis and, when legal, a next generation—not a silent global stop.

## 14. Truthfulness and reproducibility

Do not fabricate data, tests, runs, metrics, files, hashes, or conclusions. Persist random seeds, data/split hashes, code/config hashes, candidate lineage, holdout-read counts, and exact failure reasons. Resume must be idempotent and must not duplicate experiments.

## 15. File-growth controls

Do not create one directory per experiment or one report per generation. Use:

- `experiment_registry.jsonl`
- `generation_registry.jsonl`
- `v22_083_checkpoint.json`
- `frozen_split_manifest.json`
- `champion_config.json`
- `v22_083_summary.json`
- `v22_083_summary.txt`
- `v22_083_report.md`

Keep only baseline plus top three model artifacts. Delete other model binaries after metrics/configuration are registered.

## 16. Required tests

Actually run tests for closed-bar PIT features, feature/label alignment, delay execution, ETF direction mapping, cost deduction, purge/embargo, non-overlap, consumed holdout protection, one-read Global Holdout, NO_TRADE execution, drawdown gates, concentration gates, budgets, feature/candidate caps, resume idempotency, checkpoint restoration, and broker/order permissions.

## 17. Terminal conditions

Create `V22_083_GLOBAL_DONE.flag` only when one of these is true:

- Legal global success after one-time Global Final Holdout
- Maximum generations or global experiments reached
- Two generations without material improvement
- Same primary failure twice with no genuine bounded next hypothesis
- No untouched holdout remains
- All allowed model families have stable negative evidence
- Insufficient sample prevents a defensible conclusion
- Unrepairable leakage/data-integrity defect
- Agent/compute budget is exhausted after persisting a resumable checkpoint

A candidate failure or generation failure alone is not global terminal.

## 18. Permissions

At all times before legal final success:

- `paper_trading_allowed=false`
- `shadow_allowed=false`
- `broker_action_allowed=false`
- `official_adoption_allowed=false`

Even after legal final success, only paper/shadow may become true. Broker action and official adoption remain false.
