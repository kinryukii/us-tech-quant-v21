# FAST3-003 final report

FAST3-003 completed architecture consolidation only. It did not train a model,
run a full backtest, access Confirmation, change the FAST3-002 configuration,
or enter FAST3-004. The FAST3-002 SHA256 remains
`72186180b40e0c4b866d482fd35033597334c89ba3ef2bca33da5ad2d637eead`.

## Structural result

The 18 explicit small-path move operations during this stage covered the FAST3-002
contract into `configs/contracts`; legacy prompts, authorizations, patch JSONs,
version map, old manifests, and small smoke outputs into `docs/legacy` or
`manifests/legacy`; the pre-refactor inventory into `manifests/stages`; and
three moved launcher targets into top-level `compatibility`. `MIGRATION_REPORT`
also moved to `docs/legacy`. `git mv` was attempted but Git could not create
`.git/index.lock`; explicit `Move-Item` completed the same safe paths without
touching Git index state. No file was removed; empty obsolete directories were
removed only after their contents had moved.

The one compatibility wrapper count remains 3. Their root entry scripts resolve
to actual target scripts. The legacy V22 engine and checkpoint paths remain in
place. A single legacy adapter records permitted legacy files and hashes them;
new FAST3 production/run code has zero direct `scripts.v22` imports and zero
`sys.path` hacks.

## Governance result

`FAST3_STATE.json`, stage/config/file registries, current directive, governance,
anti-bloat policy, limits, and five guard entry points were created. The Guard
checks the top-level/root whitelist, bloat/binaries/suffixes, state/status/
registry consistency, active legacy governance artifacts, direct legacy imports,
path hacks, and wrappers. A constructed binary fixture makes the bloat guard
violate; normal repository guard execution passes.

Final validation passed 38 FAST3 unit tests (including Guard cases), 4 retained
FAST3-001 regressions, and 17 legacy V22.080 regressions. The normal guard has
zero direct legacy imports, zero `sys.path` hacks, no active prompts,
authorizations, or patch-applied files, and three compatibility wrappers.

The user-mandated guard/registry/governance package exceeds an ordinary
12-file research-stage budget. `FAST3_003_MANIFEST.json` records
`ARCHITECTURE_EXCEPTION_REQUIRED=true`, constrained to those required files.

## Unresolved

The historical untracked/staged worktree prevents a clean commit partition and
Git index-lock permission prevented `git mv`; neither blocks current runtime
paths. FAST3-004 remains ineligible for automatic execution by this stage.

## Maintenance routing update

The maintenance safety inventory found a pre-existing dirty worktree (staged
FAST3 migration files plus unrelated untracked repository work), three Codex
processes, one Node process, and five PowerShell processes; no Python process
was running and no process was stopped. The frozen FAST3-002 canonical JSON
hash was recomputed as
`72186180b40e0c4b866d482fd35033597334c89ba3ef2bca33da5ad2d637eead`.

Eleven explicitly reviewed root FAST3/Codex maintenance candidates existed.
Four FAST3-only/inactive files were archived without overwrite: the two root
prompts to `docs/legacy/directives/repository_root`, the migration worklog to
`docs/legacy/maintenance`, and the unreferenced text diff artifact
`-tech-quant` to `docs/legacy/misc/unexpected_root_files`. `CODEX_GOAL.md`,
`CODEX_PLAN.md`, and `CODEX_STATUS.md` remain repository-canonical because
`AGENTS.md` actively requires them. The three approved root PowerShell wrappers
and `FAST3.md` remain. No archived root source remains at its former path.

Before migration, `.local_results/v22` contained 114 untracked FAST3 legacy
result files (15,855,706 bytes) and `outputs/v22` contained one untracked
V22.049 FAST3 summary (3,102 bytes). Each of the resulting 115 files was copied
to `D:\us-tech-quant-results\fast3\archive\legacy_v22`, checked for equal
size and SHA256, then its exact source directory was removed. No hash mismatch
and no non-FAST3 result move occurred. The two existing FAST3-002 smoke outputs
were independently hash-checked and promoted to
`D:\us-tech-quant-results\fast3\FAST3_002_EXECUTABLE_CONTRACT`; the external
results registry now contains one canonical FAST3-002 entry and the latest
pointer names it. Empty placeholder stage directories were intentionally not
created.

The production smoke runner now reads `FAST3_STATE.json` for the external
result root and rejects repository-internal output paths outside
`FAST3_TEST_MODE=1`. The Guard now enforces both frozen external roots, rejects
repository-local FAST3 result files, checks the external result registry and
canonical-result uniqueness, and blocks the archived root historical filenames
from reappearing. The affected V22.049 and V22.069--V22.079 legacy Python and
PowerShell recovery paths were changed only at their input/output-root boundary
to use `archive/legacy_v22`; their research logic and historical results were
not rerun or altered.

An external-root metadata-only check found eleven pre-existing FAST3
autoresearch directories outside the canonical root: `fast3_autoresearch`, its
four generation variants, and `fast3_v22_081` through `fast3_v22_086`. They may
contain consumed/frozen Confirmation artifacts. This task requires SHA256 before
moving but prohibits Confirmation access, so these directories were neither
hashed, opened, moved, nor relabeled. They are recorded in `FAST3_STATE.json` as
an unresolved archival boundary; this is the only reason the historical external
result consolidation is not complete.

Maintenance validation then completed with exit code 0: Python compile; 46
FAST3-002/003 and FAST3-001 focused tests; 17 V22.080 legacy regressions; the
full Guard (including external routing); SHA256 revalidation of all 117 moved
or promoted files; and PowerShell parsing/path-resolution checks for all three
root compatibility wrappers. A direct non-test invocation of the smoke runner
with a repository-internal output path failed as required with exit code 1
before market data loading.
