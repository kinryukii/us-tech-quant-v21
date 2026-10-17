# Repository Agent Constitution + Navigation Map

Protect invariants, not implementation details.

## Mission and authority

- Complete the authorized user task end-to-end by default. Analysis, planning,
  review, explanation, design-only and read-only tasks stop at their requested
  deliverable; action tasks continue through working behavior and required evidence.
- A plan, discovered bug/blocker, code edit, training stage, passing test, artifact
  or report alone is not completion. Continue to the task's acceptance contract.
- Follow the platform instruction hierarchy and current human scope. Authorization
  persists across milestones; later clarification steers the task unless cancelled.
  Governance edits, permission profiles and historical success expand no authority.
- Root rules are the constitution. Nested guidance adds only local differences;
  it may tighten but cannot silently cancel hard invariants. Links are navigation,
  not automatically loaded instructions or permission to read their targets.
- Before material work read [Anti-Bloat policy](docs/governance/ANTI_BLOAT_POLICY.md)
  and the relevant [project map](docs/PROJECT_MAP.md) sections. Detailed execution,
  recovery, statuses, evidence and resumable task records live in the map.

## Hard invariants

- Training and development validation content, including every fitting/selection
  step, must be strictly before `2026-01-01`; test observations/targets are only
  `[2026-01-01, 2027-01-01)`. Earlier component/fold cutoffs and label maturity
  still apply. Frozen inference on mature, actually available test inputs needs
  applicable authorization; 2027+ is prospective. A2 holdout exposure persists.
- Preserve PIT/as-of availability, revisions, identity, labels, purge/embargo and
  no-leakage semantics. Restricted information includes reports, logs, tools and
  agent handoffs. Never read prohibited mixed content whole and then filter.
- A scientific change is not an engineering fix. Changes to question/target,
  information or selection freedom, evaluation, economics, execution/account
  semantics, frozen identity or authority are substantive; use the map's full
  contract test and applicable change control. Never silently tune against holdout.
- Accepted registries/manifests establish identity and status; the map navigates.
  Missing/conflicting authority is UNKNOWN. Preserve failed trials, frozen bytes
  and the exact Anti-Bloat legacy path/rule/SHA contract; never rewrite history.
- Resolve actual output purpose and physical destination before writing using
  `config/storage_paths.json`, the common resolver and [storage layout](docs/STORAGE_LAYOUT.md).
  Canonical data is read-only; runtime artifacts go to their approved external
  root, maintained source/control files to the approved checkout. Preserve freezes.
- Preserve unrelated dirty files, worktrees and running workers. Never use reset,
  clean, checkout or broad deletion to discard user work. Cleanup targets only
  proven task-owned transient files/processes under the applicable retention gate.
- No automatic merge, push, deploy, production promotion, real trading, research
  reopening, data purchase or provider history acquisition without applicable
  authorization. Accounting/margin code and test success authorize no real account.
- Never fabricate execution, tests, receipts, hashes, paths, metrics, provenance,
  Git state or completion. Engineering PASS, economic PASS, consumer use and
  production authorization are distinct evidence claims.

## Reuse and bounded autonomy

- REUSE -> EXTEND -> ADAPT -> BUILD NEW. Search current modules, callers, config,
  tests, identities, aliases and failed/closed research before implementation.
  Use `rg --files` then targeted `rg`; use `docs/research/README.md` and
  `python -B -m scripts.maintenance.research_inventory query --text "<concept>"`
  for research, then the existing registry's `preflight-proposal` when needed.
- Explain existing implementation, why reuse is insufficient, the concrete gap
  and source-of-truth ownership before a new system. Use minimum sufficient
  structure; no parallel registry, engine, evaluator or governance hierarchy.
- When several compliant implementation choices exist, choose a reasonable
  reversible option and proceed. Code structure, equivalent algorithms/libraries,
  batching, caching/streaming, workers, memory, temporary formats, test order,
  compatibility repairs, checkpoints/resume and bounded retry are autonomous.
- Equivalence must preserve the scientific contract and numerical/economic
  interpretation. Changes to hard constraints, external state, authority,
  significant cost or irreversible actions need applicable authorization.
- Use `D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe`; no repository
  `.venv` or unnecessary dependency/service/CI. Task-required infrastructure work
  follows its existing owner and authorization, with no new general framework.

## Recovery and delivery

- A normal engineering failure is not a final blocker. Diagnose, preserve valid
  work, repair, retry with new evidence, reduce resources or change equivalent
  strategy, resume checkpoints and isolate the failure. Do not blindly repeat.
- If one branch is blocked, continue all independent work. A branch BLOCKED is
  not a task BLOCKED. Ordinary OOM/path/schema/cache/process/provider failures
  and test failures are recovery work; do not default to WAITING_HUMAN.
- Stop only work requiring a real hard-boundary violation, irreplaceable missing
  input/authority, unauthorized external/irreversible/scientific action, or an
  environment unrecoverable after reasonable safe diagnosis and alternatives.
  Never bypass explicit access denial through paths, tools, ACLs or identities.
- Long/multistage/expensive work updates the existing external task record as a
  resumable ExecPlan. Milestone -> record progress -> continue; it is not a new
  approval gate. Resume validates identity, inputs and checkpoint provenance.
- Completion is based on working behavior and required evidence, not activity.
  Use proportional checks; material runtime changes run the reviewed default
  synthetic suite plus relevant reviewed tests. Small prose/config edits use
  focused checks. Never import real research just to validate governance.
- From the repo root use canonical Python `-B -m pytest -q` for default acceptance;
  `pytest.ini` lists exact reviewed files, not full-repository coverage. Review
  additional tests' imports/subprocesses/data/output scope before selecting them.
  Use external task-owned cache/temp and the existing Anti-Bloat consistency test.
- Deliver changes, reuse/authority, actual validation, evidence level and remaining
  limitations; material work records one report in `results_root/_maintenance/<task_id>/`.
  For blockers give exact missing object, necessity, affected/unaffected scope,
  completed work and minimal unblocking action. End when the objective is met.

## Review priorities

Flag contract drift/leakage, holdout-driven selection, omitted failed trials,
duplicate implementation, illegal output paths, frozen/dirty asset damage, and
unsupported evidence promotion. Review changed behavior with synthetic/isolated
checks; document consistency does not prove instruction loading, universal write
interception, research validity, consumer adoption or live readiness.
