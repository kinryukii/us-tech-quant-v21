# US Tech Quant agent map

This repository is the lightweight code/control plane for a research-first U.S.
technology quantitative system. It does not authorize production trading. Large
data, environments, backtests, daily state, and results live in external roots.

## Read first

1. Read `docs/governance/ANTI_BLOAT_POLICY.md`; its hard gates are mandatory.
2. Read `docs/PROJECT_MAP.md`; it maps domains, status evidence, and frozen assets.
3. Run the cheap preflight:
   `& D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe scripts\maintenance\harness_preflight.py`
4. Inspect `git status --short` and relevant processes before writing. Preserve
   unrelated work in a dirty tree and do not stop workers.

## One-task autonomous Harness

Use `scripts/maintenance/harness_task.py` only for one bounded, human-authorized
task. It runs R1 preflight, records reuse discovery, creates a branch worktree
under `D:\us-tech-quant-worktrees`, dispatches a Codex worker, validates and
reviews the diff, then stops. It never merges into the primary tree, deletes a
worktree, promotes research, or invents a second task.

- Start: `& D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe -B scripts\maintenance\harness_task.py start --goal "<bounded task>"`
- Observe: use `status`, `inspect`, or `timeline` after the script name.
- Control: use `pause`, `resume`, `steer "<instruction>"`, `review`, or `stop`.
- State and compact timeline live under `D:\us-tech-quant-daily\harness_r2`;
  active task worktrees and useful diffs are preserved for human integration.
- Pause and stop are cooperative: no new action is dispatched, and an active
  Codex turn is asked to reach a safe checkpoint rather than killed mid-write.
- Steering is recorded and takes effect at the next safe boundary. It cannot
  weaken the pre-2026, PIT, frozen-asset, canonical-data, or Anti-Bloat gates.
- A scoped blocker stops only the affected task surface. An unavailable external
  worktree is a hard blocker for autonomous mutation, not for read-only work.

## Harness priorities

Apply these in order:

1. Prevent overfitting, lookahead, and data leakage.
2. Prevent repository, artifact, dependency, and process bloat.
3. Prevent duplicate implementation and rebuilding existing components.
4. Preserve human observability and control.
5. Complete the single authorized task without expanding its goal.

Functional success cannot override a hard research or Anti-Bloat gate.

## Hard research boundaries

- Default training boundary: every training and label-maturity timestamp must be
  strictly earlier than `2026-01-01`.
- Treat 2026+ as holdout, evaluation, prospective, or forward-monitoring data.
  Never use it for fitting, feature/parameter/threshold/portfolio-rule search,
  model selection, experiment winner selection, or feedback into those steps.
- A2's 2026 outcome has already been exposed. See the project map and preflight.
  Do not optimize against it or restore a pristine-holdout claim.
- For every decision timestamp, information availability must be no later than
  that timestamp. Preserve existing PIT, purge, embargo, and maturity guards.
- Declare train, validation, test, holdout, and prospective roles in research
  contracts. A strong backtest is evidence, never production authorization.
- Do not weaken a temporal, holdout, frozen, or promotion gate to improve a
  result or make a test pass. Boundary weakening requires explicit human approval.

## Frozen and protected assets

- Canonical data under `D:\us-tech-quant-data` is read-only by default.
- Results and evidence under the approved external roots are preserved.
- Hash-identified models, configs, manifests, baselines, and forward contracts
  are frozen. Verify their registry/manifest identity before depending on them.
- `fast3/docs/governance/anti_bloat_frozen_legacy_baseline.json` is an immutable,
  exact-path/rule/SHA legacy baseline; do not edit or extend it casually.
- Do not modify frozen source or outputs. Do not delete old research because it
  appears duplicated or superseded.

## Search before create

Use `DISCOVER -> CLASSIFY -> REUSE/EXTEND -> CREATE ONLY IF NECESSARY`.

Before adding a module, runner, loader, feature, model/risk/execution wrapper,
guard, audit, report, backtest, or preflight:

- Search filenames: `rg --files | rg -i '<concept>'`.
- Search symbols and semantics: `rg -n -i '<terms>' scripts fast3 tests config docs`.
- Check callers, paired tests, configs, registries, manifests, and older versions.
- Classify matches as `AUTHORITATIVE`, `ACTIVE`, `FROZEN`, `SUPERSEDED`,
  `EXPERIMENTAL`, or `UNKNOWN`. When evidence is insufficient, use `UNKNOWN`.
- Prefer an authoritative or active implementation; extend it when responsibilities
  match. Reference frozen code but do not modify it.
- Create only if reuse is unsafe/impossible, would violate a freeze, or clean
  separation is technically necessary. Record the reason briefly in the report.

Never infer status from an `R1/R2/R3`, `final`, or newer-looking filename.

## Storage and runtime

- Resolve destinations through `config/storage_paths.json` and
  `scripts/common/storage_paths.py` / `.ps1`.
- Canonical runtime:
  `D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe`.
- A repository-local `.venv` is forbidden. Add no dependency unless necessary;
  keep package caches and environments external.
- Write large/rebuildable cache to `D:\us-tech-quant-cache`, backtests to
  `D:\us-tech-quant-backtests`, daily state to `D:\us-tech-quant-daily`, and
  durable research evidence to `D:\us-tech-quant-results`.
- Choose the destination before writing. Prefer a few authoritative artifacts;
  remove task-created temporary files after validation.

## Preflight and tests

The preflight is read-only and task-scoped. Its default scope is independent code
development; use `--task-scope 2026-optimization`, `2026-evaluation`,
`pre2026-research`, `historical-fetch`, or `frozen-dependent` when applicable.
A scoped hard blocker stops only matching work; a global hard blocker stops all
material work. Soft warnings do not stop independent safe phases.

Run focused tests with the canonical runtime, for example:

`& D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe -m pytest -q <test-path>`

Run Anti-Bloat consistency with:

`& D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe -m pytest -q scripts\maintenance\test_anti_bloat_policy_consistency.py`

## Default work loop

`DISCOVER -> SEARCH_EXISTING -> CHECK_BOUNDARIES -> IMPLEMENT_MINIMAL_CHANGE -> TARGETED_TEST -> RESEARCH_VALIDATION (when applicable) -> SELF_REVIEW -> CLEANUP -> REPORT`

Continue safe independent phases after an unrelated failure. Use `HARD_BLOCKER`
only for invalid research, leakage, corruption, frozen-asset violation,
destructive modification, or materially incorrect results. Use `SOFT_WARNING`
for real but task-independent issues and `INFORMATIONAL` for context.

## Do not

- Do not fetch Moomoo history during ordinary development or Harness validation.
- Do not mutate canonical data, active experiments, research result directories,
  frozen baselines, or unrelated dirty files.
- Do not add orchestration platforms, dashboards, databases, background daemons,
  new CI systems, or large audit/documentation trees for routine work.
- Do not create version-suffix families when an existing implementation should be
  repaired or extended. Do not perform broad cleanup without explicit authority.
