# Project map

This is the compact navigation map for the repository. It identifies where to
look; registries, manifests, hashes, and tests remain the status authorities.
Never classify an asset from its filename or apparent age alone. Read this map
and the Anti-Bloat policy before material work, as required by root AGENTS.md.
Read the research contract section before research/data-dependent work. A pointer
is not permission to read its contents; use task-authorized non-result metadata.

## Status vocabulary

- `ACTIVE`: current code/control surface supported by repository evidence.
- `FROZEN`: referenceable, hash/contract protected, and not to be modified.
- `EVALUATION_ONLY`: inference, holdout, prospective, or diagnostic use; no tuning.
- `SUPERSEDED`: use only when an authoritative registry/manifest says so.
- `EXPERIMENTAL`: bounded research, not an adopted production component.
- `UNKNOWN`: inspect callers, tests, manifests, and evidence before use or change.

## Current navigation

- [Runtime and development entrypoints](../README.md)
- [Research reuse table](research/README.md): derived from the existing accepted identity registry and the retained branch table.
- [Repository layout](governance/REPOSITORY_LAYOUT.md): current code and test locations.
- [Retired source catalog](research/retired_sources.json): old paths, hashes and exact Git recovery locations; included in reuse queries.

## Domain locations

| Domain | Evidence-backed status | Start here |
| --- | --- | --- |
| Research identity and anti-duplication | `ACTIVE` implementation; accepted registry head controls identity | `scripts/maintenance/research_registry.py`, `config/research_registry.json`, `tests/governance/test_research_registry.py`; external metadata-only registry, aliases and accepted manifests |
| Research lifecycle and trials | `ACTIVE` helpers; per-task contracts remain scoped | `scripts/maintenance/prospective_research_lifecycle.py`, `tests/governance/test_prospective_research_lifecycle.py`; existing receipts/trial records, no second registry |
| Storage routing and canonical data | `ACTIVE`; canonical data read-only | `config/storage_paths.json`, `scripts/common/storage_paths.py`, `scripts/common/storage_paths.ps1`, `docs/STORAGE_LAYOUT.md` |
| 13F PIT engineering | `ACTIVE` PIT utilities; individual experiments otherwise `UNKNOWN` | `scripts/v22/pit_13f_reconstruction_r1.py`, its callers/tests, and external lineage manifests |
| Shared PIT foundation | Retained source dependency of FAST3 inputs | `scripts/research/a2/data/a2_free_pit_foundation_r1.py`; source bytes retained and loaded by the existing FAST3 PIT input adapter |
| A / A2 alpha research | `ACTIVE` and `EXPERIMENTAL`; frozen identities only where a hash/contract says so | `scripts/v22/abcde_a2_*`, paired `test_*.py`, and, when present, `config/research_governance/alpha_registry.json` |
| A2 risk research | `ACTIVE`; R6 is a frozen prospective reference in current evidence | `scripts/v22/a2_stock_risk_r6.py`, `scripts/v22/a2_stock_risk_r10_r11_fast_track.py`, paired tests, and the risk registry when present |
| Execution / portfolio policy | `ACTIVE` research; adopted identities may be `FROZEN` | `scripts/v22/abcde_a2_r1c_execution_contract_freeze_r1.py`, `scripts/v22/abcde_a2_r4_portfolio_translation_using_hgb_incumbent.py`, and the execution registry when present |
| DEMO daily performance synchronization | `ACTIVE` descriptive presentation adapters; no fitting or new research selection | `scripts/daily_recommendation.py`, `scripts/research/a2/evaluation/demo_performance.py`, `three_strategy_extension.py`, `selected_performance_update.py`; frozen policy/engine reuse, verified ledgers under external `daily_root/A2_selected_hgb/research_runs/`, paired evaluation and DEMO reader tests |
| 2026 holdout | `EVALUATION_ONLY` and already exposed for A2 | `D:\us-tech-quant-results\A2_ALGORITHM_R2_2026_FROZEN_HOLDOUT\status.json`; protected content, not an ordinary-development read target; prior exposure blocks pristine-holdout reuse/optimization |
| Forward / prospective evaluation | `EVALUATION_ONLY`; no training/search/selection | `scripts/v22/forward_shadow/`, `config/research_governance/a2_forward_shadow_unified_r1.json`, and `docs/research_governance/` when present |
| FAST3 | `ACTIVE` implementation, currently synthetic-only; frozen confirmation remains unread | `fast3/state/FAST3_STATE.json`, `fast3/manifests/registries/FAST3_STAGE_REGISTRY.json`, `fast3/FAST3_STATUS.md` |
| FAST6 data collection | Retained current provider dependency | `fast6/`; follow its existing callers and data contracts |
| FAST legacy/supersession | Mixed; use registries, not version names | `fast3/manifests/registries/`, `fast3/scripts/audit/build_fast3_inventory.py`, and compatibility/legacy mappings |
| Tests | `ACTIVE` existing pytest system | Paired `scripts/v*/test_*.py`, `fast3/tests/`, `tests/`, and `pytest.ini` |
| Anti-Bloat | `ACTIVE`; policy and thresholds are authoritative | `docs/governance/ANTI_BLOAT_POLICY.md`, `configs/anti_bloat_policy.toml`, `fast3/scripts/audit/run_fast3_guard.py` |
| V21 daily/history | Mixed; do not assume obsolete | `docs/V21_ACTIVE_SYSTEM_REGISTRY.md`, `config/v21/active_chain_manifest.json`, and the V22 active/deprecated output manifest implementation |
| Results and evidence | Protected external evidence | `D:\us-tech-quant-results`, `D:\us-tech-quant-backtests`, `D:\us-tech-quant-daily`; never rewrite for ordinary development |

13F manager completeness is scoped to a declared cohort, not a universal fixed
24/25 count. The original Raw A2 authoritative 24-manager configuration excludes
Situational Awareness and remains its frozen historical identity. Current cohort
consumers reuse `scripts/storage/refresh_13f_quarter.py::active_managers` and
`manager_roster_identity` with quarter-effective registry intervals; an institution
before its applicable start is not a missing filer. A finite observed filing
history does not imply an end date. Keep task-specific `ALL_APPLICABLE` versus
explicitly authorized `DISCLOSED_ONLY` coverage separate; a disclosed subset is
not evidence that a stricter whole-qualified-snapshot contract passed. Preserve
old frozen bindings and use an explicit quarter roster binding for new cohorts.

Broad `scripts/v22` contents are not collectively authoritative. Multiple versions
and experiments coexist. Locate a candidate with `rg`, inspect paired tests and
callers, then confirm status from a registry, manifest, freeze hash, or current
task contract. If those disagree or are missing, classify it `UNKNOWN`.

New A2 category work uses `scripts/research/a2/<category>/` and
`tests/research/a2/<category>/`; preserve older implementations still required by
current callers or their applicable contracts. Retired files are found through
the Git recovery catalog rather than recreated as root wrappers.

## Research contracts: read before research or data-dependent work

Use existing contracts and the research registry above; this section adds no
registry, permanent task budget or automatic permission to reopen research.

- Distinguish exploration, candidate freeze, confirmation and prospective
  observation. Pre-2026 exploration may change a hypothesis with recorded lineage
  and the resulting selection limitations; it need not promise positive results.
- Apply strict fold cutoffs to every selection step: imputation, scaling,
  dimensionality reduction, features, hyperparameters, models, thresholds, stock
  pools, sector constraints, portfolio, cost, execution, risk and holding periods.
  A pre-cutoff observation with a label maturing outside its fold is ineligible.
- Record material changes and failed/abandoned trials in the existing mechanism.
  Do not log only winners, reset identity/counts by renaming, or confuse raw trials
  with effective independent trials; report unknown effective counts as unknown.
  Use the current task budget, not an old task's temporary search allowance.
- Before confirmation, freeze candidate, data/time scope, benchmark, primary
  metric, cost/execution assumptions, evaluation method and stopping conditions.
  After outcome access, changing any of these requires a new recorded exploratory
  decision and forfeits the original independent-test claim. Do not trim adverse
  years/samples or lower frozen expectations to obtain a favorable conclusion.
- Compare research identity by economic hypothesis, available information set,
  target/horizon, mechanism and evaluation design. Check canonical aliases,
  failed/closed/parked/tombstoned conclusions and reusable artifacts first.
  Reopening needs new legal information, a materially distinct falsifiable
  mechanism, or repair of a defect that made the prior test invalid. Explain the
  change with preserved canonical lineage and the original conclusions, using
  the existing lifecycle's required new research_id rather than overwriting or
  reopening the old record in place; governance updates reopen nothing.
- PIT is an information-chain contract: distinguish report period from actual
  financial/13F disclosure, database vintage/revision from event time, and raw
  versus adjusted prices from their authoritative PIT lineage. Carry availability
  limits into features, caches, models and intermediate artifacts. Check timezone,
  session and after-close availability; current mappings cannot reconstruct
  historical identity/industry/universe without authoritative historical support.
- Read only the authorized content. For mixed-year files, prove the reader avoids
  prohibited contents before access; whole-file reads followed by filtering fail
  this boundary. Synthetic dates and document references remain legal. Missing
  PIT inputs stop only dependent units and never authorize guessed substitutes.
- Correct negative, no-incremental-value and untestable conclusions are complete
  research outcomes. Prior exposure survives new sessions, names and freezes;
  separately authorized descriptive evaluation is not an untouched test.

Temporal authorities and limitations:

- HARD TIME SPLIT (human requirement, 2026-10-01): training inputs/labels and
  development-validation content must be `< 2026-01-01`; test observations and
  target periods are only `2026-01-01 <= t < 2027-01-01`. All learned
  preprocessing/calibration fitting, selection and early stopping use pre-2026
  content. Authorized PIT evaluation may transform/predict 2026 inputs using
  frozen state; it may not fit, adapt or select that state on test content.
  Labels must mature before their own fit/fold cutoff, also strictly pre-2026.
  Validation is carved from the pre-2026 development period, not the 2026 test.
- Define these roles by actual content, availability and label intervals, not
  folder names. A 2026 decision may use a legitimate pre-2026 history buffer;
  that buffer is an input context, not 2026 test outcomes or a refitting license.
  Test targets crossing into 2027 are excluded from this 2026 test contract.
  Evaluate only the 2026 observations whose inputs/outcomes have actually become
  available by the declared as_of time. Mark partial-year coverage explicitly;
  do not synthesize remaining dates or claim full-year performance prematurely.
  2027+ observations belong to a separately scoped prospective evaluation.
- Changing this calendar split requires a later explicit human task instruction;
  directory/config edits and successful tests do not authorize a change. Earlier
  component/fold/Confirmation freezes and access restrictions remain in force;
  frozen historical records retain their original bytes and interpretation.
- Existing tracked guards include strict cutoff, target-maturity/purge, filing
  availability, and lookahead checks in the A2/13F modules listed above.
- 2026 A2 outcome evidence predates a later attempted pristine holdout contract.
  Treat further tuning against that evidence as overfitting risk. Frozen forward
  inference may continue only under its specific no-fit/no-search contract.
- FAST3 uses its own earlier Development/Confirmation boundary in
  `fast3/state/FAST3_STATE.json`; its Confirmation data is frozen and unread.
- Backtest success, synthetic validation, or prospective support does not grant
  broker action, official adoption, or production authorization.


### Actionable research checks (2026-10-01)

These are project research constraints, not a new permission layer or a new
registry. Put required facts in the existing proposal/contract, run configuration,
trial record and final report. An ordinary typo/UI/document edit does not require
a research experiment or reading outcomes.

1. **Before fitting or selection:** resolve canonical identity and prior work
   using authorized registry/source metadata; explain reuse or the distinct
   increment. Record hypothesis, baseline, primary metric, train/validation/
   locked-test roles and exact intervals, decision/availability/label-maturity
   cutoffs, purge/embargo rationale, search scope/budget and stopping rule.
   Use the applicable task budget; do not introduce a universal trial allowance.
   Do not inspect locked outcomes to decide this design.

2. **During development:** use chronological rolling/walk-forward validation;
   never randomly split dependent financial observations for an independent
   generalization claim. Remove overlapping label windows across folds and
   document any embargo from the actual information/label horizon. Fit all
   learned transformations on that fold's training data only. Feature discovery,
   asset-pool selection, seed/model/hyperparameter search, early stopping,
   calibration, portfolio/risk/cost/execution choices and metric/baseline/window
   selection are part of the same selection process. Record failed, abandoned
   and manual trials as well as winners; report unknown counts as UNKNOWN.
   Repeated validation inspection can overfit validation too: bound search and
   retain a separate locked evaluation of the complete selected pipeline.

3. **Ensembles and evidence:** train stacking/calibration/learned weights on
   chronological out-of-fold predictions (OOF: each row predicted by a model
   whose fit and selection did not use that row's label or future information).
   Include source model/fold/time lineage; in-sample predictions are not OOF.
   Compare to the frozen baseline under the same sample, information, capital,
   cost and execution assumptions. Report selection history, relevant subperiod
   stability, uncertainty and multiple-comparison limitations; preserve serial
   dependence in uncertainty estimation. A best seed, peak Sharpe, one interval
   or synthetic PASS alone cannot establish incremental value or generalization.

4. **Before confirmation:** freeze source/config/model identities and the entire
   declared evaluation design before first outcome access. Confirmation executes
   that design, not a winner search. Preserve every exposure and any defect/
   correction/retest lineage. An infrastructure fix may justify a corrected run;
   it does not authorize tuning, changing frozen expectations, resetting trials
   or calling the already exposed window untouched. Separately authorized
   descriptive/forward evaluation remains clearly labeled. Without valid inputs
   or independent evidence, report BLOCKED_DATA/UNTESTABLE or the applicable
   existing contract status; never fabricate a substitute PASS.

5. **PIT across the pipeline:** for each signal enforce
   `available_at <= decision_at < execution_at` with explicit timezone/session
   semantics; the execution time must allow realistic computation/order latency.
   Event/report dates alone are insufficient. A completed bar/closing price is
   unavailable earlier within that bar/session; its closing fill cannot be assumed
   executable after using that close. Fit rows require labels matured before
   their own fold's fit cutoff as well as the project cutoff. Use as-of joins and
   historical revisions, ticker/security identity, universe/sector membership,
   delisting and corporate-action lineage; do not backfill from today's snapshot.
   Cached/derived features, preprocessing, OOF and model selection inherit the
   same information limits. Missing availability evidence blocks that dependency.

Current web descriptions, today's company narratives/classifications and an
LLM's current knowledge are not authoritative historical PIT features or labels.
A prompt asking the LLM to "use only pre-2026 knowledge" does not isolate its
information set. Historical use needs archived, time-stamped source evidence
and a declared construction/selection process; otherwise label it retrospective
and do not claim an independent historical information set. Human/agent review,
summaries, images, logs, caches, tool results and sub-agent handoffs must obey the
same authorized read scope. Research lookup never authorizes reading protected
results. Establish a content-level isolated reader before real restricted access;
metadata/date checks and reading a whole file then filtering are insufficient.

For code changes that affect time/data boundaries, reuse paired synthetic tests
to check exact-cutoff and late-publication/revision rejection, fold label overlap,
OOF lineage, and **future append/truncation invariance**: adding records unavailable
at decision time must not change earlier eligible features, decisions or fitted
objects. Inspect test imports/subprocesses and input/output scope first; a legal
property test does not make a mixed real-data suite safe. Do not add mirror tests
for documentation edits or launch real research to validate governance text.

## Frozen-asset lookup

Check, in order: the component registry/config, its manifest, recorded SHA-256,
then the paired guard/test. The immutable Anti-Bloat legacy baseline is
`fast3/docs/governance/anti_bloat_frozen_legacy_baseline.json`. A2 model/config
hashes are recorded in research-governance registries when those active files are
present. Preserve unknown or inaccessible evidence; do not repair by overwriting.

## Instruction sources and retained history

- Root `AGENTS.md` owns project-wide agent routing. `.codex/config.toml` supplies
  project configuration; permission profiles are not research authorizations.
  No relevant local AGENTS.override.md or configured fallback instruction file
  was found. Local task rules cannot weaken the root or platform hierarchy.
- Within FAST3, `fast3/docs/governance/FAST3_ANTI_BLOAT_POLICY.md` explicitly names
  `FAST3_CURRENT_STAGE_DIRECTIVE.md` as the sole current stage directive and
  `FAST3_GOVERNANCE.md` as its governance view. Stage applicability must still be
  checked against state and registry; an old stage title is not current approval.
- `fast3/docs/governance/FAST3_AUTONOMOUS_MASTER_DIRECTIVE.md` and
  `FAST3_AUTORESEARCH_AGENT_SPEC.md` are retained historical task specifications,
  not active project-wide authorization. They are not in the discovered Codex
  loading chain. Their old branch/path/full-chain instructions must not
  launch research, Confirmation access or promotion. Preserve original bytes and
  FAST3 inventory records; a generic inventory canonical flag is not acceptance
  of every historical task instruction. This map retires their execution role.
- `CODEX_GOAL.md`, `CODEX_PLAN.md`, `CODEX_STATUS.md` occur in inventory generator
  compatibility code but are absent at the project root and are not configured
  Codex fallbacks. Do not recreate them as parallel permanent governing files.
- `docs/research_governance/` contains domain contracts and historical task views.
  Read only the applicable authorized contract, not the whole directory. These
  domain views do not supersede accepted research identities or global gates.


## Maintenance consolidation (2026-09-14)

- `scripts/maintenance/audit_repo_size_r1.py` is the compatibility CLI for the
  existing FAST3 repository budget check. Thresholds come from the existing
  policy; incomplete accounting is reported and returns a nonzero exit status.
- `run_storage_maintenance_r1.ps1 -AllSafe` performs budget and retention dry-run
  checks only. Migration and retention execution require their explicit switches;
  a failed preceding step prevents subsequent execution.
- Twenty-three unreferenced V18 `.bak` repair copies and ten unused V20 launcher
  wrappers were retired. Their exact lists and recovery commit are in
  `D:/us-tech-quant-results/_maintenance/SYSTEM_CONSOLIDATION_20260914/`.
  This dated consolidation report describes the earlier layout. The later
  repository cleanup removed unused source; consult the current Git recovery
  catalog instead of assuming its old local paths still exist. Running restored
  source remains subject to the applicable research/data authorization.
- Legacy source still required by current callers is retained. Retirement follows
  dependency review, not version names or an old candidate plan. Historical
  inventories retain their original meaning and bytes.
- Migrated CSV cache at `cache_root/migrated_from_repo/cache` uses transparent
  NTFS compression. All 7,701 file hashes and paths were verified unchanged;
  no cache path or dataset identity was migrated or removed.

## Runtime entrypoints and safe regression (2026-09-14)

This section navigates existing implementations; it creates no new registry.
The current daily pointer under
`daily_root/current/V22.044_DAILY_SINGLE_ENTRYPOINT_FREEZE_AND_GUARD_R1/current_daily_research_entrypoint.json`
selects V22.044 -> V22.040 and marks old V21 daily wrappers `historical_only`.
Its recorded acceptance is not a fresh health check or permission to fetch data.

| Purpose | Existing entrypoint | Execution boundary |
| --- | --- | --- |
| Inspect data catalog / prepare acquisition request | `python -m scripts.storage.manage_data status` / `plan` | Status reads catalog metadata; plan writes an explicit destination. `prices` reads actual values and needs the applicable data scope. |
| Explicit data acquisition | `scripts/storage/refresh_market_data.py`; provider-specific `refresh_*.py` | Use their existing plan/execute parameters. Data management is separate from strategy membership; do not launch acquisition as a test. |
| Current daily research | `scripts/v22/run_v22_044_daily_single_entrypoint_freeze_and_guard_r1.ps1` -> V22.040 -> current V21 components | `-Execute` runs the real daily chain. V21.256 remains an internal governance component, not another primary entrypoint. |
| A2 research development | `scripts/research/a2/<category>/`, `scripts/maintenance/research_registry.py` and `scripts/maintenance/prospective_research_lifecycle.py` | Locate the accepted identity and contract first. There is no single universally safe command for all research. Historical frozen references remain unchanged and may resolve through the Git recovery catalog. |
| Read-only research presentation | `apps/demo_console/start.ps1` | Uses `envs_root/demo-console`; reads existing artifacts through its adapters. See that app's README for the authorized presentation scope. |
| Local strategy simulation | `apps/moomoo_trading_component/start.ps1` | Existing three paper books and the original MOOMOO SIMULATE identity; state under `daily_root/moomoo_trading_component`. Explicit activation only; opening delay defaults to zero and records actual quote/order/fill times. REAL execution remains unavailable. See the component README. |
| R1E service and Dashboard V2 | `scripts/v22/start_v22_047_r1e_service.ps1`, `start_v22_047_r1e_ui.ps1`, `status_v22_047_r1e_service.ps1` | These and `install_v22_047_r1e_tasks.ps1` reuse `Get-UstqStoragePaths -RepoRoot`; task actions use external Python. A service start is not a unit test. |

Run the default core regressions **from the repository root with no test path**:

```powershell
Set-Location D:\us-tech-quant
& D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe -B -m pytest -q
```

`pytest.ini` lists individually reviewed synthetic storage/maintenance and
R1D/R1E service test files. Its collection-isolation test checks that unselected
research modules are not imported. The removed Harness/preflight suite is not
part of current default acceptance; do not recreate it from an old staged copy.
It excludes unreviewed legacy modules before import/collection. An isolated
subprocess regression proves that default discovery does not import unselected
research scripts, while explicitly selected tests remain available. This is a
default collection boundary, not a general sandbox or full-repository coverage.
Passing `.`, `scripts`, an old test path, or running from another directory can
change discovery. Review each additional test's imports, subprocesses, inputs
and output locations before running it. Some V20 tests execute their real stage
scripts and read/write historical results even when their names look like tests.

R1E focused synthetic regression also remains explicitly selectable:
`python -B -m pytest -q scripts/v22/test_v22_047_r1e_windows_service_hardening.py`.
Use an authorized external cache/temp location when the configured cache is
unwritable. No historical research
script becomes safe merely by passing an explicit path to pytest.

The paired R1D/R1E suites run the real lock, Engine, service manager and Windows
stop entry against temporary repositories with synthetic market/account bridges
and worker substitutes. They cover cancellation, disconnect/reconnect, failures,
restart and owned-process cleanup. They do not execute real account, strategy or
PAPER worker implementations. An alive worker with a stale heartbeat remains
degraded under the existing policy; forcibly killing the manager outside its
exception handler is not a promise of automatic process-tree cleanup.

Reuse map after consolidation:

- Data reading: `scripts/storage/storage_r2a.py::DataStore`; the legacy daily
  functions already delegate to it. Raw, adjusted and provider-specific lineage
  contracts remain distinct. Do not merge readers by filename similarity.
- Runtime paths: `scripts/common/storage_paths.py` / `.ps1`. Explicit checkout
  selection wins over a stale copied `repo_root`; R1E no longer creates a second
  runtime choice by assuming a repository-local `.venv`.
- Dates: daily coverage uses the existing V21 broad-date gate; option timestamp
  and session validation uses `scripts/research/a2/options/contracts.py`.
  A coverage date, a timezone-aware availability timestamp and a trading session
  are different contracts and must not be collapsed into one loose parser.
- Costs: intraday continuation already loads the pinned R4
  `calculate_weight_rebalance` pure definition; its half-notional turnover cost
  differs from the options adapter's per-contract/per-share commission and
  minimum fee. Preserve each contract and the pinned source identity.
- Maintenance: retain the shared FAST3 budget implementation and explicit
  retention/migration switches described above; no new cleanup framework.

## Startup acceptance and checkout retirement (2026-09-14)

For an explicitly authorized live connectivity check, the existing R1E launcher
now accepts a bounded prerequisite-only mode:

```powershell
& D:\us-tech-quant\scripts\v22\start_v22_047_r1e_service.ps1 -RepoRoot D:\us-tech-quant -StartupCheckOnly -WaitSeconds 20 -StartupCheckOutput D:\us-tech-quant-results\_maintenance\SYSTEM_CONSOLIDATION_20260914\r1e-startup-check.json
```

This checks the real service lock, connection profile, network, OpenD TCP and
the existing five-symbol current-quote API. It does not initialize service
outputs, change authorization, request historical bars, query an account or
start the engine, watchdog or strategy workers. Success is
`STARTUP_PREREQUISITES_READY`, not acceptance of the full service business loop.
An explicit output must resolve under canonical `results_root/_maintenance`;
without an override, the independent file is the service's `startup_check.json`.
An existing live service lock blocks the check; stale locks retain the existing
SingleInstance recovery behavior. OpenD must already be available at the profile
endpoint. The check does not launch OpenD. SDK logs stay beside the check output.
Check the current process exit code and report timestamp together; a failure
before lock acquisition can leave an older report in place. `WaitSeconds` limits
retries and sleeps, but does not cancel an SDK call already in progress.

Real acceptance on this date passed the above entry and OpenD quote connection,
plus four demo-console pages using pre-2026 artifacts. The owned UI and OpenD
processes were closed afterwards. Operational state-file hashes were unchanged.
The R1E quote readiness probe now skips historical requests; R1D's ordinary
market snapshot keeps its existing history behavior. Service summaries only
report PASS for RUNNING with a HEALTHY watchdog.

The credential receiver and Yahoo maintenance callers now select the canonical
storage implementation through the existing repo parameter and shared resolver.
Seventeen identical development-source copies, four completed one-time tools
and one superseded local resolver have been retired. Caller tests remain in the
development workspace; original bytes and changes are in the consolidated
maintenance evidence directory, not a second source checkout.

Five clean checkouts with no unique commits were retired after source, registry,
process and scheduled-task reference checks. Their branches and commits remain
available; `worktree-closeout/retirement-decisions.json` in the same maintenance
directory records exact paths, decisions and recovery commands. The sixth
candidate, `rx-authority-durability-r1`, remains because task ownership/recovery
purpose is unresolved. Frozen source bindings and other worktrees remain intact.

## Repository organization (2026-09-23)

Unused historical source has been removed from the current working tree,
including the former `archive/research/` copy and retired FAST4/FAST5 code.
`docs/research/retired_sources.json` records each removed file's path, hash and
recovery path in commit `3d0783a8c864552273394358268292f6d389e99b`.
It is a file lookup catalog, not a new registry or a scientific status decision.
Retained current callers and their required dependencies remain available,
including FAST3's PIT foundation and the FAST6 data-provider modules.

The registry and lifecycle implementations now live in `scripts/maintenance/`;
their tests are under `tests/governance/`. New checkouts use these locations
directly and need no root aliases or generated wrappers. FAST3 navigation lives
in `fast3/README.md`; its retained compatibility commands live below `fast3/`.

`docs/research/README.md` remains a generated navigation view. The existing
`scripts/maintenance/research_inventory.py` refreshes the external branch CSV
and searches accepted identities, aliases, retained source names and retired
source metadata. Use `python -B -m scripts.maintenance.research_registry` for
the canonical registry CLI. Old scientific conclusions remain separate from
current identity status; discrepancies and missing registrations require review.
Deletion does not reopen research. Accepted registry state, external frozen
records, data and live state are unchanged by this repository cleanup.

## Maintaining agent guidance and official references (2026-10-01)

Keep root AGENTS.md as the short project entrypoint; retain detailed research
checks here, storage detail in STORAGE_LAYOUT.md and Anti-Bloat detail in its
existing policy. Global instructions apply general preferences. The C: chat
workspace entry routes this project's work to the D: authority; historical staged
copies and task plans do not become current policy. Only load references required
by the task. Complex multi-step work may use the existing external task record
with outcome, scope, milestones, decisions, validation and recovery steps; routine
edits do not require new permanent plans or contracts.

When changing guidance, check current callers, configured testpaths, actual
instruction discovery/override files, combined instruction size and destination
routing. Preserve unrelated working-tree edits and frozen bytes. Classify changes
under Anti-Bloat change control; weakening still needs explicit authorization.
Separate document consistency, actual instruction loading, executable interception,
research validity and live readiness in the report. A link is not automatically
loaded, and instruction text is not an operating-system or runtime enforcement
mechanism. Existing sessions may need a new run/chat to rebuild their instruction
chain; do not claim restart/loading validation from text search or model self-report.

Official OpenAI documentation consulted on 2026-10-01:

- [Custom instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md):
  global/project discovery, override precedence and the default 32 KiB combined
  instruction limit. Use the recognized AGENTS.md filename.
- [Codex best practices](https://learn.chatgpt.com/guides/best-practices):
  practical repository instructions, explicit completion criteria and verification.
- [Rethinking skills and prompts](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra):
  concise routing and task-specific reference loading rather than mandatory
  full-repository reading.
- [Using PLANS.md](https://developers.openai.com/cookbook/articles/codex_exec_plans):
  persistent, verifiable milestones for complex work; adapted to existing task
  records without introducing a second planning authority.
- [Optimizing LLM accuracy](https://developers.openai.com/api/docs/guides/optimizing-llm-accuracy)
  and [Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices):
  representative evaluation, retained holdout, scoped comparisons and logging.

These sources guide agent/document structure and general evaluation practice.
The `< 2026-01-01` boundary, 2026-only test set, A2 exposure, PIT/OOF/trial
controls and D: storage architecture are this project's existing or tightened
research constraints, not OpenAI-prescribed trading rules. No OpenAI Evals
service/API dependency is introduced by this documentation update.
