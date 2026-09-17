# Anti-Bloat Policy

Policy-Version: 1.0
Status: ACTIVE
Initial-Date: 2026-08-17

## Purpose and authority

This policy makes the completed Strict Anti-Bloat R2 contract permanent. It
governs repository contents, storage routing, generated artifacts, deletion,
and end-of-task acceptance. `configs/anti_bloat_policy.toml` is the
machine-readable value source, and the existing FAST3 guard is the enforcement
entrypoint. Subsystem policies may tighten this contract but may not weaken it.

Functional `PASS` is impossible if any Anti-Bloat hard gate fails.

## Canonical storage architecture

The repository at `D:\us-tech-quant` is a lightweight code/control plane. It
contains source, tests, compact configuration, small manifests, and concise
documentation. Runtime routing remains defined by `config/storage_paths.json`.

| Responsibility | Canonical location | Default protection |
| --- | --- | --- |
| Source/control plane | `D:\us-tech-quant` | Lightweight, version-controlled |
| Canonical data | `D:\us-tech-quant-data` | Read-only |
| Environments | `D:\us-tech-quant-envs` | Active dependency |
| Results/evidence | `D:\us-tech-quant-results` | Preserve |
| Rebuildable and research cache | `D:\us-tech-quant-cache` | Classified before retention/deletion |
| Daily state/output | `D:\us-tech-quant-daily` | Active lifecycle state |
| Backtests | `D:\us-tech-quant-backtests` | Research evidence |
| External worktrees | `D:\us-tech-quant-worktrees` | Preserve active/dirty worktrees |

All approved external roots must be distinct from, and must not be nested in,
the repository root. Storage destination must be resolved before artifact
creation; creating locally and moving later is not the normal workflow.

The canonical Python runtime is
`D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe`.

## Repository size budget

- Preferred operating size: less than 157,286,400 bytes (150 MiB).
- Required maximum: less than 314,572,800 bytes (300 MiB). Reaching this
  threshold fails the repository budget gate.
- Warning threshold: 419,430,400 bytes (400 MiB).
- Hard-fail threshold: 524,288,000 bytes (500 MiB).

Unreadable paths must be surfaced. A reported readable size is a lower bound,
not permission to ignore unknown content. No functional pass may override the
required maximum or hard-fail state.

## Large-file policy

New files greater than 10,485,760 bytes trigger storage-surface review. Any
individual repository file greater than 26,214,400 bytes fails unless its exact
path is explicitly allowlisted with a documented architectural reason. Model
artifacts, checkpoints, predictions, OOF data, bulk daily archives, binary
datasets, and large reports must be written directly to an approved external
root. The allowlist is narrow, path-specific, and is not a general exemption.

## Environment policy

A repository-local `.venv` is forbidden. Environments and package caches must
live outside the repository. Project commands and validation use the canonical
runtime unless an explicitly approved workflow names another external runtime.
Environment removal requires active-reference and reconstruction checks.

## Data protection

Canonical data is read-only by default. Development, tests, audits, and cleanup
must not mutate or probe-write the canonical data root unless the user
explicitly authorizes a data-management operation. Derived data must carry
lineage and go to its approved external destination. A copied dataset is not a
substitute for an authoritative source.

## Results and evidence protection

Final reports, frozen artifacts, manifests, point-in-time/prospective evidence,
audit outputs, model-selection evidence, and Anti-Bloat evidence are
authoritative research records. Preserve them even when a run failed or was
superseded unless a deletion gate is conclusively satisfied. Name, age, or a
newer-looking run is not proof of obsolescence.

## Cache policy

Cache storage is external. A cache may be an active dependency or the only
remaining lineage record, so the word `cache` alone never authorizes deletion.
Removal requires proof that the content is rebuildable, its authoritative input
still exists, reconstruction is deterministic enough for the contract, and no
active consumer depends on it. Uncertain cache classification fails closed.

## Daily storage

Daily output, state, prerequisite lifecycle data, logs, and archives belong
under the external daily root. Current state and recovery-critical history are
protected active dependencies. Retention must be explicit, bounded, and must
preserve the records required to explain or resume the daily chain.

## Worktree policy

Before any worktree retention or removal decision, inspect Git registration,
lock state, branch/HEAD, dirty state, unique commits, and untracked files.
Active, dirty, locked, or uncertain worktrees are preserved. Future worktrees
that can create material content should use the external worktree root. Worktree
cleanup is never implied by an ordinary development or Anti-Bloat audit task.

## Backtest storage

Backtest inputs, ledgers, predictions, diagnostics, and reports belong under the
external backtest root with stable run identity and provenance. Do not copy
large backtest output into the repository. Backtest evidence is protected as
research evidence and is subject to the same deletion gates as results.

## Duplicate prevention

Choose one canonical destination and stable run identifier before writing.
Reuse manifests and registries rather than creating retry/final/patched file
families. Equal names or sizes do not prove duplication. Deletion as an exact
duplicate requires content identity plus proof that the retained copy is
authoritative, accessible, and covered by the required retention contract.

## Reuse before creation

Search for an existing implementation, configuration, runner, test, and policy
entrypoint before adding one. Extend the canonical implementation when its
responsibility already matches the task. A parallel framework requires a clear
architectural need and explicit integration/migration ownership.

## Source-code bloat

Prefer focused modules, shared helpers, parameterization, and extensions to
existing tests. Avoid copied runners, near-duplicate wrappers, generated source,
embedded datasets, repeated policy prose, and version-suffix file families.
This Markdown policy owns Anti-Bloat detail, the root TOML owns enforcement
values, and the existing guard owns enforcement. Root AGENTS.md owns agent
routing; domain/task rules cannot loosen this policy.

REUSE BEFORE BUILD. EXTEND BEFORE PARALLELIZE. MINIMUM SUFFICIENT CHANGE.
EVIDENCE BEFORE CLAIM. These apply to governance as well as application code.
Do not create a second registry, policy engine, identity/data authority, generic
orchestrator or wrapper stack for a routine fix. A necessary thin adapter must
explain why direct reuse is insufficient and retain one business implementation.

Do not make every debug output, draft or temporary result an immutable authority.
Reuse the existing task record, registry and final report rather than adding
per-debug permanent contracts, manifests, state machines or audit directories.
Preserve genuine frozen evidence and existing retention obligations. Before
retiring duplicate prose/code, check active references, callers, freeze contracts
and audit uses; file count and length alone do not justify removal.

### Immutable frozen legacy baseline

Pre-existing authoritative or frozen source debt may be registered only in the
canonical immutable legacy baseline. Every exception is bound to one exact
repository-relative file path, one exact SHA-256, and one exact violation rule.
The policy pins the baseline manifest hash, and the manifest pins the normalized
path/rule/content identity set that existed when the baseline was registered.
Path-only, directory, wildcard, regex-wide, and hash-free exceptions are
forbidden.

An exact match is reported transparently as frozen legacy debt and is not a
current violation. Any content change, rename, copy, new rule violation, or
path mismatch invalidates the exception and restores normal current
enforcement. New files receive no grandfathering. The baseline cannot change
budgets, permit new runtime path mutation, or permit repository-local result
writes.

## Deletion gates

Every candidate must be classified with evidence:

- Authoritative data, active dependencies, and research/archive evidence are
  protected.
- Rebuildable material may be eligible only after reconstruction and dependency
  proof.
- Exact duplicates may be eligible only after identity and retained-copy proof.
- Proven obsolete material may be eligible only with explicit scope and no
  retention obligation.
- Unknown or disputed material is preserved.

Deletion authority must come from the task or explicit user authorization.
Before deletion, resolve exact paths, confirm they are inside the authorized
root, record the evidence, and protect authoritative sources and retained
copies. Broad globs, inferred abandonment, age alone, and inaccessible paths do
not pass the gate.

## End-of-task audit

Material development ends with a proportional Anti-Bloat audit: check the
repository budget, newly surfaced large files, repository-local `.venv`, output
routing, evidence locations, parallel implementations, and guard/test status.
Report inaccessible paths and unmeasurable scope. Record model, backtest,
broker, deletion, and source-modification counts when the task contract asks
for them. A functional test pass cannot override a failed Anti-Bloat hard gate.

## Fail-closed behavior

When destination, ownership, lineage, retention, deletion safety, policy
meaning, or authorization is unknown, stop the risky operation and preserve the
item. Surface the uncertainty for review. Do not repair permissions, broaden
authority, silently add an allowlist entry, or reinterpret a hard gate as a
warning. Continue independent authorized work. Ordinary test failures get bounded
repair/retry; an unwritable unrelated cache may use an already-authorized external
cache root. Explicit access denial must not be bypassed through another path,
user, tool, permission change or privilege level. Incomplete accounting remains
reported as incomplete, never as a global budget PASS.

## Policy change control

Every proposed change is classified as one of:

- `TIGHTENING`: reduces limits or increases protection; may be proposed and
  applied within an authorized governance task.
- `CLARIFICATION`: explains existing intent without changing effective rights,
  limits, routing, or retention.
- `ARCHITECTURAL_UPDATE`: changes canonical structure or enforcement while
  preserving or strengthening protection; requires explicit task scope and
  migration/compatibility analysis.
- `EXCEPTION`: narrow, documented, time- or path-bounded relief that identifies
  owner, reason, evidence, and expiry/review condition.
- `WEAKENING`: reduces a protection, gate, or restriction.

Codex may propose every category. Codex must not automatically apply
`WEAKENING`, silently or otherwise. Weakening includes raising hard storage
limits, permitting repository-local virtual environments, weakening canonical
data protection, weakening evidence retention, weakening deletion gates, or
broadening delete authority. Any weakening requires explicit user
authorization. Change descriptions must state the classification and keep the
human policy, machine values, guard, and focused consistency test aligned.
