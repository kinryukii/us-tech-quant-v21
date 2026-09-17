# US Tech Quant v21

US Tech Quant is a research-first system for point-in-time U.S. equity data,
ranking, portfolio simulation, risk analysis, forward observation, and audited
research workflows. The repository is the lightweight code and control plane;
large datasets, caches, environments, results, daily state, and backtests live
under the external roots declared in `config/storage_paths.json`.

The default posture is research-only. A backtest, ranking, dashboard, or forward
observation does not authorize live trading, model promotion, or broker action.

The public project name remains **US Tech Quant v21**. Internal identifiers such
as `V22.xxx`, `A2`, and `FAST3` name pipeline or research revisions; they do not
change the public project version.

## What is in the repository

- `scripts/storage/`: canonical data catalog, read layer, manifests, snapshots,
  and explicit source refresh tools.
- `scripts/research/`: current A2 and FAST3 research implementations.
- `scripts/v21/` and `scripts/v22/`: retained compatibility entrypoints,
  operational components, and historical research modules. Version numbers alone
  do not establish which module is current.
- `apps/demo_console/`: read-only Streamlit research and portfolio presentation.
- `fast3/`, `fast4/`, `fast5/`, `fast6/`: bounded research families with their
  own contracts and tests.
- `tests/` plus paired `test_*.py` files: synthetic and scoped verification.
- `docs/PROJECT_MAP.md`: current navigation, status, and execution boundaries.
- `docs/governance/ANTI_BLOAT_POLICY.md`: repository and storage protections.

Accepted identities, manifests, hashes, registries, and paired tests are the
status authorities. Files under broad versioned directories can be active,
experimental, superseded, frozen, or unknown.

## Storage layout

The checked-in defaults are:

| Purpose | Path | Default posture |
| --- | --- | --- |
| Source and control plane | `D:\us-tech-quant` | Version controlled |
| Canonical data | `D:\us-tech-quant-data` | Read-only |
| Environments | `D:\us-tech-quant-envs` | External |
| Results and evidence | `D:\us-tech-quant-results` | Preserve |
| Rebuildable cache | `D:\us-tech-quant-cache` | Classified lifecycle |
| Daily state | `D:\us-tech-quant-daily` | Active lifecycle state |
| Backtests | `D:\us-tech-quant-backtests` | Research evidence |
| Worktrees | `D:\us-tech-quant-worktrees` | Preserve active/dirty trees |

Resolve paths through `scripts/common/storage_paths.py` or
`scripts/common/storage_paths.ps1`. Do not place environments, bulk market data,
model artifacts, predictions, or generated research results in this repository.

## Setup

The canonical Python runtime is:

```powershell
D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe
```

The reproducible package set is recorded in `requirements.lock.txt`. Runtime
paths are configured in `config/storage_paths.json`; provider credentials and
private account configuration remain local and must not be committed.

## Current daily research entrypoint

The current daily pointer selects V22.044, which delegates to the V22.040
orchestrator and retained V21 components:

```powershell
Set-Location D:\us-tech-quant
& .\scripts\v22\run_v22_044_daily_single_entrypoint_freeze_and_guard_r1.ps1 -Execute
```

This is a real data-dependent research workflow. Review its current pointer,
inputs, provider state, and authorization before execution. Running it is not a
normal installation or regression-test step.

## Data layer

Inspect catalog metadata without running acquisition:

```powershell
Set-Location D:\us-tech-quant
& D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe -B -m scripts.storage.manage_data status
```

Use `plan` to prepare an explicit acquisition request. Source-specific
`refresh_*.py` tools perform network or data mutations only when invoked with
their documented plan/execute arguments. `scripts/storage/storage_r2a.py` owns
the shared data-store implementation; legacy readers delegate to it where their
lineage contracts permit.

See `docs/DATA_LAYER.md` for catalog schemas, manifests, snapshots, provider
boundaries, and source-specific commands.

## Presentation demo

The Streamlit console presents existing recorded research artifacts through
read-only adapters. It does not train models, rerun strategies, connect to a
broker, or write authoritative economic data.

```powershell
Set-Location D:\us-tech-quant
& .\apps\demo_console\start.ps1 -Port 8504
```

Open <http://127.0.0.1:8504/?language=%E4%B8%AD%E6%96%87>. The launcher uses the
external `demo-console` environment and binds only to `127.0.0.1`. The detailed
presentation scope and evidence limits are in `apps/demo_console/README.md`.

## R1E service and dashboard

The R1E service and Dashboard V2 use these compatibility entrypoints:

```text
scripts/v22/start_v22_047_r1e_service.ps1
scripts/v22/start_v22_047_r1e_ui.ps1
scripts/v22/status_v22_047_r1e_service.ps1
scripts/v22/stop_v22_047_r1e_service.ps1
```

Their synthetic tests cover locks, process ownership, cancellation, restart,
connection failures, and fail-closed behavior. Starting the real service can
touch live provider and account surfaces, so it is separate from default tests
and requires the applicable runtime configuration and authorization.

## Research boundaries

- Training, fitting, calibration, preprocessing, feature/model/rule selection,
  and label maturity must be before `2026-01-01`, unless a later human-approved
  contract explicitly changes that boundary.
- 2026+ A2 evidence is evaluation-only and has already been exposed; it cannot be
  reused as a pristine holdout or as input to tuning, refitting, or winner
  selection.
- Information must be available by the decision timestamp. Missing PIT lineage,
  availability, revision, identity, or maturity evidence makes the dependent
  result untestable.
- Negative, no-incremental-value, and untestable outcomes are valid completed
  research results. Preserve failed trials and frozen evidence.
- Research outputs do not authorize broker execution or official adoption.

Read `AGENTS.md`, `docs/PROJECT_MAP.md`, and
`docs/governance/ANTI_BLOAT_POLICY.md` before material development or research.

## Testing

Run the reviewed default regression from the repository root:

```powershell
Set-Location D:\us-tech-quant
& D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe -B -m pytest -q
```

`pytest.ini` enumerates the reviewed synthetic storage, maintenance, preflight,
and R1D/R1E service suites. This default is intentionally not full-repository
coverage. Review imports, inputs, subprocesses, and output paths before selecting
additional historical or research tests; some versioned tests execute real stage
scripts and read or write external evidence.

Run the read-only independent-code preflight when appropriate:

```powershell
& D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe -B scripts\maintenance\harness_preflight.py --task-scope independent-code --json
```

That scope checks Git/control metadata, source identities, and repository budget.
Skipped research checks are `NOT_CHECKED`, not research clearance.

## Git and artifact hygiene

Before committing:

```powershell
git status --short
git diff --stat
git diff --check
```

Commit focused source, tests, compact configuration, manifests, and concise
documentation. Keep credentials, raw/provider data, caches, generated outputs,
model binaries, account exports, and temporary research artifacts out of Git.
Never use a broad cleanup command to remove evidence or unknown files; follow the
retention and Anti-Bloat gates first.

## Further documentation

- `docs/PROJECT_MAP.md` — current components, entrypoints, and boundaries.
- `docs/DATA_LAYER.md` — data catalog and acquisition architecture.
- `docs/STORAGE_LAYOUT.md` — canonical external path layout.
- `docs/governance/ANTI_BLOAT_POLICY.md` — repository budget and retention rules.
- `apps/demo_console/README.md` — demo capabilities, sources, and validation.
- `FAST3.md` — FAST3 compatibility and research notes.

This software is for quantitative research and audit. It does not provide
financial advice or guarantee investment performance.
