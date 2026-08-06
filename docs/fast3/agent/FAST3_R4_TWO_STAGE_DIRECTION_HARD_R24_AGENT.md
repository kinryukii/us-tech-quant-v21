# FAST3 R4 Two-Stage Direction — Hard Storage R2.4 Agent Contract

## Scope

Implement and unit-test exactly one R4 architecture study. Do not run the full historical study yourself. The outer launcher runs it exactly once after implementation and tests pass.

Compare only:

```text
A: R3-style direct UP_FIRST / DOWN_FIRST / NO_EVENT hgb_leaf7
B: two-stage EVENT / NO_EVENT, then UP_FIRST / DOWN_FIRST hgb_leaf7
```

The future path is the supervised label only. Every input feature must be computable at or before the decision timestamp.

## Storage contract

Use only the environment roots:

```text
FAST3_REPO_ROOT
FAST3_DATA_ROOT
FAST3_RUNTIME_ROOT
FAST3_SCRATCH_ROOT
FAST3_FROZEN_ROOT
FAST3_ARCHIVE_ROOT
FAST3_CACHE_ROOT
```

Repository writes are limited to the exact allowlist in the limits JSON and must contain source, unit tests or architecture documentation only.

Never create or touch `.local_results`. Never write predictions, checkpoints, logs, reports, models, manifests, hashes, JSON decisions, parquet outputs, caches or temporary files into the repository.

The canonical root is protected by an OS write-deny ACL and a filesystem watcher. Do not attempt to change it.

Do not execute Git commands. Existing tracked and untracked files must remain intact.

## Source freeze

Require external R3 evidence:

```text
R3 run: 20260802_211307
R3 decision: STOP_NO_SIGNIFICANT_GAIN_OVER_LEGACY
R3 model: hgb_leaf7
R3 stable feature count: 20
R3 post-audit: PASS_R3_ECONOMIC_IMPLEMENTATION_AUDIT_CLEAN
R3 post-audit unique primary trades: 429
```

Preserve the R3 decision.

## Fixed implementation

Reuse existing read-only FAST3 utilities where appropriate. Do not create a duplicate general framework.

The full research entrypoint must be:

```text
fast3/scripts/run/fast3_r4_two_stage_direction_hard_r24.py
```

It must accept:

```text
--repo-root
--data-root
--runtime-root
--scratch-root
--frozen-root
--cache-root
--source-r3-root
--source-r3-audit-root
--limits
--run-id
```

All output paths must come from these arguments. No fallback to `.local_results` or repository-relative result paths is permitted.

## Labels and leakage controls

```text
UP_FIRST
DOWN_FIRST
NO_EVENT
AMBIGUOUS -> exclude
```

Use:

```text
expanding-window training
24-hour purge
24-hour embargo
training-fold-only preprocessing
uniqueness_weight × training-fold class_weight × training-fold era_weight
natural test distribution
```

Random row splitting is forbidden.

## Frozen model and signal contract

Both architectures use the exact ordered 20 R3 features and three frozen interactions.

```text
HistGradientBoostingClassifier
max_iter=100
learning_rate=0.08
max_leaf_nodes=7
l2_regularization=1.0
```

```text
opportunity threshold=0.60
Top fraction=0.05
rank=max(P_UP_FIRST, P_DOWN_FIRST)
horizon=24 hours
ETF target=3%
costs=10 and 20 bps
single account, single position
QQQ UP/DOWN -> TQQQ/SQQQ
SOXX UP/DOWN -> SOXL/SOXS
```

No factor, interaction, model, hyperparameter, threshold, ranking, Top fraction, target, horizon, cost or schedule search.

## Bounded schedule

Freeze all eight blocks before fitting:

```text
4 development blocks × 3 seeds
4 non-prospective internal-holdout blocks × 5 seeds
```

Run development first. Stop immediately if the fixed development gate fails. Run the internal holdout only after a development pass.

Checkpoint each block/seed under scratch. Resume only when every relevant hash matches.

All historical results must be explicitly marked non-prospective. A pass only freezes one model for future blind research shadow.

## Metrics

Report separately:

```text
opportunity: hit rate, lift, AUROC, Brier
conditional direction: accuracy, balanced accuracy, UP/DOWN recall and precision
end-to-end: exact accuracy and legacy-compatible Top5 lift
economics: deduplicated 10/20 bps, target hit, drawdown,
remove-best-1%, block/ETF concentration, daily/monthly and occupancy
```

Use block-cluster uncertainty. Do not treat repeated seeds as independent blocks.

## Required artifacts

Always write every required frozen artifact. Unrun phases must contain a valid `NOT_RUN` object with the prior-stop reason. Create the artifact hash manifest last.

Do not perform broker, paper-order or live-order actions.
