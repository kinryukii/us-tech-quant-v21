# US Tech Quant project instructions

Research-first code/control plane for U.S. technology quantitative work.
Backtests and governance validation never authorize production trading.

## Authority and required reading

- Follow the platform instruction hierarchy and the current human task scope.
  Root rules apply project-wide; local instructions and task templates may add
  constraints, never relax PIT, freezes, safety, or authorization boundaries.
- Read `docs/governance/ANTI_BLOAT_POLICY.md` and `docs/PROJECT_MAP.md` before
  material work. Links do not load their targets automatically.
- Before research/data work, read the map's contract rules and the applicable
  registry/contract through an authorized read path.
- Accepted registries/manifests establish identity and status; the map navigates.
  Missing/conflicting acceptance means UNKNOWN; HEAD, timestamps and candidates
  do not imply acceptance. Preserve historical records and frozen raw bytes.
- Governance edits never expand authorization. Work remains bounded by the
  permissions and hard rules effective at task start.

## Four protections

1. Prevent engineering and governance bloat: REUSE BEFORE BUILD.
   EXTEND BEFORE PARALLELIZE. MINIMUM SUFFICIENT CHANGE. EVIDENCE BEFORE CLAIM.
2. Prevent overfitting and result-driven rule changes across the full selection
   process, not only the final fit. Preserve failed trials and exposed windows.
3. Prevent future-data and future-information leakage through the whole PIT
   chain, including availability, revisions, identity and label maturity.
4. Prevent duplicate implementation and research: resolve canonical identity,
   aliases, prior failures and closed/parked conclusions before new work.

## Research and information boundaries

- HARD TIME SPLIT: training content and development validation must be strictly
  before `2026-01-01`; test observations/targets must be in
  `[2026-01-01, 2027-01-01)`. No 2026 test content may enter fitting,
  estimation/selection of preprocessing or calibration, early stopping or any
  model/rule selection. Authorized PIT evaluation may apply frozen pre-2026
  transformations and inference without updating fitted state. Use only actually
  available/mature test observations as of the declared evaluation time; never
  invent the unfinished 2026 period. 2027+ is prospective, not this test set.
  This calendar split does not override an earlier component freeze/read boundary
  or restore an already exposed holdout. See the map for fold/label/PIT details.
- Before a new data-dependent run, record the existing identity/reuse decision,
  fold and information boundaries, selection budget/stopping rule, applicable
  freeze/exposure status and resolved output destinations in the existing task
  contract. Use the actionable checks in the map; do not invent another registry.

- Training and all fitting/selection of preprocessing, calibration, features,
  models, thresholds, universe, portfolio, costs and execution rules must use
  content strictly before `2026-01-01`; obey any earlier fold cutoff and
  label-maturity boundary too. This limits learned/selected state, not applying
  already frozen transformations to authorized test inputs.
- Distinguish exploration, candidate freeze, confirmatory evaluation and forward
  observation. Declare train/validation/test/holdout/prospective roles. Read the
  map's detailed contract rules before changing or evaluating a research design.
- 2026+ information requires separate applicable read/evaluation authorization;
  it cannot feed tuning, winner selection or refitting. This includes indirect
  exposure via charts, summaries, tool outputs and delegated agent context.
  A2 exposure is already recorded: a new session, name or freeze cannot restore
  pristine holdout status.
- A date in documentation or a synthetic test is not real-result access.
  Do not use model/train/2026 keyword bans to reject legal pre-2026 work.
  Governance development grants no real 2026 data, label or outcome access.
- Read permission is content-specific. Reports, logs and caches can expose results.
  Never load a prohibited mixed-year file whole and filter afterward. Use a
  proven isolated source/read boundary; if unavailable, stop that dependent unit.
- Information must be available by its decision timestamp. Preserve availability,
  revision, identity, maturity, purge and embargo lineage as detailed in the map;
  today's database or mappings cannot substitute for authoritative PIT inputs.
- Missing authoritative PIT input makes the affected result untestable; do not
  guess, silently fill or fabricate a mapping. Continue independent legal work.
- Follow the map's pre-evaluation freeze and trial-record rules. Negative or
  untestable results can complete research; never weaken a rule or frozen
  expectation to obtain PASS or preserve a false independent-test claim.

## Discover, reuse and preserve

- First inspect `git status --short` and relevant processes. Preserve unrelated
  dirty files, other branches/worktrees and running workers; never stop them.
- Before proposing a new research implementation, search `docs/research/README.md`
  and run `python -B -m scripts.maintenance.research_inventory query --text "<concept>"`.
  This reuses the accepted identity registry and searches retained source names
  plus `docs/research/retired_sources.json`, the Git recovery catalog for removed code.
  A missing identity is not permission to rebuild; inspect unregistered matches
  and use `python -B -m scripts.maintenance.research_registry preflight-proposal`.
- Search names with `rg --files | rg -i '<concept>'`, then relevant symbols with
  `rg -n -i '<terms>' scripts fast3 tests config docs`.
  Check callers, tests, configs, aliases, manifests and accepted prior conclusions.
- Classify AUTHORITATIVE / ACTIVE / FROZEN / SUPERSEDED / EXPERIMENTAL / UNKNOWN.
  Prefer the existing canonical implementation. Explain any necessary thin
  adapter or new component; it must not become a second business implementation.
- Apply the Anti-Bloat policy to code and governance. No parallel authorities or
  per-debug governance trees. Check callers, freezes and retention before retiring
  content; length, age or similar names alone never justify deletion.
- Frozen assets stay byte-identical; verify identity before use. Hash recording
  alone does not freeze active governance: follow its actual change-control rules.
- Preserve `fast3/docs/governance/anti_bloat_frozen_legacy_baseline.json` and its
  exact path/rule/SHA contract. Never rewrite historical hashes to hide changes.
- New A2 work uses `scripts/research/a2/<category>/` and corresponding tests.
  Reuse maintenance/ops entrypoints and retained compatibility paths;
  do not create version-suffix families.
- Repository navigation lives in `docs/governance/REPOSITORY_LAYOUT.md`.
  Registry and lifecycle implementations live in `scripts/maintenance/`; do not
  recreate root wrappers or retired research code. Restore a historical source
  from the catalog's exact Git commit only when the current task needs it.

## Storage and bounded autonomy

- Resolve destinations first via `config/storage_paths.json` and
  `scripts/common/storage_paths.py` / `.ps1`. Canonical data_root is read-only.
  Results, backtests, daily state, environments and caches stay in external roots.
- Use `D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe`.
  No repository `.venv`, unnecessary dependency, background service or new CI.
- Apply `docs/STORAGE_LAYOUT.md` before the first write: check actual resolved
  paths, artifact purpose and approved root, including junction/symlink targets.
  Repository-external is necessary but does not prove the correct destination.
  Do not use the C: chat workspace as a second research/output repository.
- Complete authorized locating, edits, focused refactors, deterministic bug fixes,
  tests, review and delivery autonomously. Fix stale schemas/assertions only with
  authority evidence; never substitute favorable expectations for a real freeze.
- Use bounded repair/retry for ordinary failures. An unwritable cache may be
  redirected to an already-authorized external cache; keep unrelated work moving.
  Explicit access denial must not be bypassed via another path, tool, user or ACL.
- Stop only the affected operation for real permission, safety, PIT, freeze,
  budget, destructive-action or live-trading boundaries. WAITING_HUMAN is not
  the default response to a test failure. Never escalate privileges or permissions.
- No `reset --hard`, `git clean`, `git add -A`, broad deletion, cross-branch merge,
  push, research reopening, promotion, data purchase or Moomoo history fetch
  without applicable task authorization. Governance work implies none of these.

## Validation and completion

- Focused tests: `& D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe -B -m pytest -q <test-path>`.
- Default development acceptance: run that Python's `-B -m pytest -q` from the
  repository root with no test path. The exact reviewed `pytest.ini` entries cover
  storage/maintenance and synthetic R1D/R1E lifecycle. Additional tests require
  review before selection; historical research tests are not part of default acceptance.
- Anti-Bloat consistency: `& D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe -B -m pytest -q scripts/maintenance/test_anti_bloat_policy_consistency.py`.
  Use an authorized external temporary/cache root; preserve inaccessible residue.
- Complete DISCOVER -> REUSE -> CHECK_BOUNDARIES -> MINIMAL_CHANGE -> TARGETED_TEST
  -> APPLICABLE_RESEARCH_VALIDATION -> REVIEW -> TASK_TEMP_CLEANUP -> REPORT.
- Separately verify references, executable behavior and isolated instruction
  loading. Text search and model self-report cannot prove access enforcement.
- Deliver one results_root report: changes, authority/reuse, tests, evidence and
  gaps. Distinguish document update, loading, interception, research validity and
  live readiness; never claim an untested layer passed.
- Functional success cannot override a hard research or Anti-Bloat gate. Finish
  when the authorized objective is met; do not invent a follow-on audit task.

## Code Review Rules

- Flag a fit/selection step using 2026 test or later-fold information, in-sample
  stacking, omitted failed trials, post-result changes to a freeze, or an exposed
  window presented as untouched. Apply the map's checks to the whole pipeline.
- Flag PIT joins without availability/revision/label-maturity evidence, or
  restricted outcomes exposed through whole-file reads, reports or agent context.
- Flag a duplicate business implementation/registry or outputs written to the
  wrong root. Prefer an existing component and check resolved destination/purpose.
- Review the changed scope with relevant synthetic/isolated tests. Do not import
  historical research just to validate instructions; passing tests do not prove
  a new access interceptor, independent holdout, scientific validity or adoption.
