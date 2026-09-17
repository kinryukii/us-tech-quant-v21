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
  registry/contract through an authorized read path. Before Harness work, read
  its map entry and paired tests.
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

- Training, fitting, calibration, preprocessing and all feature/model/threshold/
  universe/portfolio/cost/execution-rule selection must be strictly before
  `2026-01-01`; obey any earlier fold cutoff and label-maturity boundary too.
- Distinguish exploration, candidate freeze, confirmatory evaluation and forward
  observation. Declare train/validation/test/holdout/prospective roles. Read the
  map's detailed contract rules before changing or evaluating a research design.
- 2026+ information requires separate applicable read/evaluation authorization;
  it cannot feed tuning, winner selection or refitting. A2 exposure is already
  recorded: a new session, name or freeze cannot restore pristine holdout status.
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
- Search names with `rg --files | rg -i '<concept>'`, then relevant symbols with
  `rg -n -i '<terms>' scripts fast3 tests config docs` and root canonical modules.
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
  Reuse maintenance/Harness/ops entrypoints and protected compatibility paths;
  do not create version-suffix families.

## Storage and bounded autonomy

- Resolve destinations first via `config/storage_paths.json` and
  `scripts/common/storage_paths.py` / `.ps1`. Canonical data_root is read-only.
  Results, backtests, daily state, environments and caches stay in external roots.
- Use `D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe`.
  No repository `.venv`, unnecessary dependency, background service or new CI.
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

- Use the existing read-only `scripts/maintenance/harness_preflight.py` only when
  its actual reads are authorized. Its `independent-code` path checks Git/control
  metadata, source identities and the repository budget without reading research
  contracts, model artifacts, holdout outcomes or arbitrary changed data files.
  Documentation and maintenance code use that no-result scope. Research checks
  omitted for the scope are NOT_CHECKED, never research clearance. A research
  scope label does not grant content-read permission or bypass hard gates.
- Focused tests: `& D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe -B -m pytest -q <test-path>`.
- Default development acceptance: run that Python's `-B -m pytest -q` from the
  repository root with no test path. The exact reviewed `pytest.ini` entries cover
  storage/maintenance, preflight read boundaries and synthetic R1D/R1E lifecycle.
  Additional tests require review before selection; full Harness task tests and
  historical research tests are not part of default acceptance.
- Anti-Bloat consistency: `& D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe -B -m pytest -q scripts/maintenance/test_anti_bloat_policy_consistency.py`.
  Use an authorized external temporary/cache root; preserve inaccessible residue.
- Harness is optional for one human-authorized goal; see the map for start/control
  commands. Do not launch a real Harness/research task to test these instructions.
- Complete DISCOVER -> REUSE -> CHECK_BOUNDARIES -> MINIMAL_CHANGE -> TARGETED_TEST
  -> APPLICABLE_RESEARCH_VALIDATION -> REVIEW -> TASK_TEMP_CLEANUP -> REPORT.
- Separately verify references, executable behavior and isolated instruction
  loading. Text search and model self-report cannot prove access enforcement.
- Deliver one results_root report: changes, authority/reuse, tests, evidence and
  gaps. Distinguish document update, loading, interception, research validity and
  live readiness; never claim an untested layer passed.
- Functional success cannot override a hard research or Anti-Bloat gate. Finish
  when the authorized objective is met; do not invent a follow-on audit task.
