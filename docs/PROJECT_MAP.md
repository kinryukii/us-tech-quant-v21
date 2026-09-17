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

## Domain locations

| Domain | Evidence-backed status | Start here |
| --- | --- | --- |
| Research identity and anti-duplication | `ACTIVE` implementation; accepted registry head controls identity | `research_registry.py`, `config/research_registry.json`, `test_research_registry.py`; external metadata-only registry, aliases and accepted manifests |
| Research lifecycle and trials | `ACTIVE` Harness integration; per-task contracts remain scoped | `prospective_research_lifecycle.py`, `tests/governance/test_prospective_research_lifecycle.py`; existing receipts/trial records, no second registry |
| Storage routing and canonical data | `ACTIVE`; canonical data read-only | `config/storage_paths.json`, `scripts/common/storage_paths.py`, `scripts/common/storage_paths.ps1`, `docs/STORAGE_LAYOUT.md` |
| 13F PIT engineering | `ACTIVE` PIT utilities; individual experiments otherwise `UNKNOWN` | `scripts/v22/pit_13f_reconstruction_r1.py`, its callers/tests, and external lineage manifests |
| A / A2 alpha research | `ACTIVE` and `EXPERIMENTAL`; frozen identities only where a hash/contract says so | `scripts/v22/abcde_a2_*`, paired `test_*.py`, and, when present, `config/research_governance/alpha_registry.json` |
| A2 risk research | `ACTIVE`; R6 is a frozen prospective reference in current evidence | `scripts/v22/a2_stock_risk_r6.py`, `scripts/v22/a2_stock_risk_r10_r11_fast_track.py`, paired tests, and the risk registry when present |
| Execution / portfolio policy | `ACTIVE` research; adopted identities may be `FROZEN` | `scripts/v22/abcde_a2_r1c_execution_contract_freeze_r1.py`, `scripts/v22/abcde_a2_r4_portfolio_translation_using_hgb_incumbent.py`, and the execution registry when present |
| 2026 holdout | `EVALUATION_ONLY` and already exposed for A2 | `D:\us-tech-quant-results\A2_ALGORITHM_R2_2026_FROZEN_HOLDOUT\status.json`; protected content, not an ordinary-development read target; prior exposure blocks pristine-holdout reuse/optimization |
| Forward / prospective evaluation | `EVALUATION_ONLY`; no training/search/selection | `scripts/v22/forward_shadow/`, `config/research_governance/a2_forward_shadow_unified_r1.json`, and `docs/research_governance/` when present |
| FAST3 | `ACTIVE` implementation, currently synthetic-only; frozen confirmation remains unread | `fast3/state/FAST3_STATE.json`, `fast3/manifests/registries/FAST3_STAGE_REGISTRY.json`, `fast3/FAST3_STATUS.md` |
| FAST legacy/supersession | Mixed; use registries, not version names | `fast3/manifests/registries/`, `fast3/scripts/audit/build_fast3_inventory.py`, and compatibility/legacy mappings |
| Tests | `ACTIVE` existing pytest system | Paired `scripts/v*/test_*.py`, `fast3/tests/`, `tests/`, and `pytest.ini` |
| Anti-Bloat | `ACTIVE`; policy and thresholds are authoritative | `docs/governance/ANTI_BLOAT_POLICY.md`, `configs/anti_bloat_policy.toml`, `fast3/scripts/audit/run_fast3_guard.py` |
| Harness | `ACTIVE` repository guards and one-task control plane | `scripts/maintenance/harness_preflight.py`, `scripts/maintenance/harness_task.py`, paired tests, and root `AGENTS.md` |
| V21 daily/history | Mixed; do not assume obsolete | `docs/V21_ACTIVE_SYSTEM_REGISTRY.md`, `config/v21/active_chain_manifest.json`, and the V22 active/deprecated output manifest implementation |
| Results and evidence | Protected external evidence | `D:\us-tech-quant-results`, `D:\us-tech-quant-backtests`, `D:\us-tech-quant-daily`; never rewrite for ordinary development |

Broad `scripts/v22` contents are not collectively authoritative. Multiple versions
and experiments coexist. Locate a candidate with `rg`, inspect paired tests and
callers, then confirm status from a registry, manifest, freeze hash, or current
task contract. If those disagree or are missing, classify it `UNKNOWN`.

New A2 category work uses `scripts/research/a2/<category>/` and
`tests/research/a2/<category>/`; preserve protected older compatibility entrypoints.

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
  change under the existing identity; governance updates reopen nothing.
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

- Training and label maturity must be `< 2026-01-01` unless a future contract is
  explicitly human-authorized to change the boundary.
- Existing tracked guards include strict cutoff, target-maturity/purge, filing
  availability, and lookahead checks in the A2/13F modules listed above.
- 2026 A2 outcome evidence predates a later attempted pristine holdout contract.
  Treat further tuning against that evidence as overfitting risk. Frozen forward
  inference may continue only under its specific no-fit/no-search contract.
- FAST3 uses its own earlier Development/Confirmation boundary in
  `fast3/state/FAST3_STATE.json`; its Confirmation data is frozen and unread.
- Backtest success, synthetic validation, or prospective support does not grant
  broker action, official adoption, or production authorization.

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
- Harness reads its planner, worker and reviewer templates from
  `scripts/maintenance/harness_task.py`. These are active generated prompts, not
  separate authority to change the human goal or global hard boundaries. Edit
  the source when writable; do not patch old generated task records.
- Within FAST3, `fast3/docs/governance/FAST3_ANTI_BLOAT_POLICY.md` explicitly names
  `FAST3_CURRENT_STAGE_DIRECTIVE.md` as the sole current stage directive and
  `FAST3_GOVERNANCE.md` as its governance view. Stage applicability must still be
  checked against state and registry; an old stage title is not current approval.
- `fast3/docs/governance/FAST3_AUTONOMOUS_MASTER_DIRECTIVE.md` and
  `FAST3_AUTORESEARCH_AGENT_SPEC.md` are retained historical task specifications,
  not active project-wide authorization. They are not in the discovered Codex or
  Harness loading chain. Their old branch/path/full-chain instructions must not
  launch research, Confirmation access or promotion. Preserve original bytes and
  FAST3 inventory records; a generic inventory canonical flag is not acceptance
  of every historical task instruction. This map retires their execution role.
- `CODEX_GOAL.md`, `CODEX_PLAN.md`, `CODEX_STATUS.md` occur in inventory generator
  compatibility code but are absent at the project root and are not configured
  Codex fallbacks. Do not recreate them as parallel permanent governing files.
- `docs/research_governance/` contains domain contracts and historical task views.
  Read only the applicable authorized contract, not the whole directory. These
  domain views do not supersede accepted research identities or global gates.

## Harness entry and verification limits

Use `scripts/maintenance/harness_task.py` for one bounded human-authorized task.
Start with `start --goal "<bounded task>"`; observe with `status`, `inspect` or
`timeline`; control with `pause`, `resume`, `steer "<instruction>"`, `review`,
`stop`. Use the canonical Python runtime from root AGENTS.md. State is under the
resolved daily_root / `harness_r2`; worktrees use the configured external root.
No automatic merge, worktree deletion, research promotion or second task.
Pause/stop are cooperative; preserve active turns and independently legal work.

The existing `scripts/maintenance/harness_preflight.py` applies scope before
content reads. `--task-scope independent-code` covers documentation, maintenance
and independent code: Git/control metadata, source identities and repository
budget only. It skips research contracts, model artifacts, holdout outcomes and
the arbitrary changed-data temporal scan. Research checks are NOT_CHECKED for
that scope, not passed; research scope selection grants no content-read rights.
Use its `--json` option for a read-only check without starting a Harness task.
The paired preflight suite exercises real file-access interception, the Harness
caller and a negative control that detects removal of the scope boundary.

The cutoff/PIT helpers and source-literal scanner are limited checks, not a
universal data-access firewall. No accepted non-frozen shared A2 training/split
entrypoint currently covers every fit/selection step. The canonical registry and
lifecycle enforce identity/receipt rules at their own entrypoints; direct scripts
may bypass them. Validate affected readers and model pipelines under their own
authorization; do not infer repository-wide enforcement from synthetic PASS.


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
  All V20 Python implementations and tests remain. For a retired launcher,
  its retained Python counterpart is listed in `legacy-launcher-deletions.json`;
  running it remains subject to the applicable research/data authorization.
- Legacy V20/V21 source is not globally obsolete: current references and historical
  dependencies remain. Do not execute the broad retirement candidate plan as a
  cleanup command. Historical inventories retain their original meaning and bytes.
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
| A2 research development | `scripts/research/a2/<category>/`, existing `research_registry.py` and `prospective_research_lifecycle.py` | Locate the accepted identity and contract first. There is no single universally safe command for all research. Frozen experiments keep their source and bindings. |
| Read-only research presentation | `apps/demo_console/start.ps1` | Uses `envs_root/demo-console`; reads existing artifacts through its adapters. See that app's README for the authorized presentation scope. |
| R1E service and Dashboard V2 | `scripts/v22/start_v22_047_r1e_service.ps1`, `start_v22_047_r1e_ui.ps1`, `status_v22_047_r1e_service.ps1` | These and `install_v22_047_r1e_tasks.ps1` reuse `Get-UstqStoragePaths -RepoRoot`; task actions use external Python. A service start is not a unit test. |

Run the default core regressions **from the repository root with no test path**:

```powershell
Set-Location D:\us-tech-quant
& D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe -B -m pytest -q
```

`pytest.ini` lists individually reviewed synthetic storage/maintenance, preflight
read-boundary and R1D/R1E service test files.
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
unwritable. Full `test_harness_task.py` is not a default entry: review its broader
task/process/worktree operations before selecting it. No historical research
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
