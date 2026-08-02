# FAST3-000 migration plan

Status: approved for the small, reversible batches below. This plan is based on
`fast3/manifests/FAST3_000_FILE_INVENTORY.json`, generated on 2026-08-02.

## Constraints and rollback

The worktree was already untracked/dirty before this task. No reset, clean,
stash, overwrite, data move, or result move is permitted. The planned FAST3
sources are untracked, so `git mv` cannot apply; each actual move is a recorded
`Move-Item`. A rollback is the inverse explicit `Move-Item` for each completed
line. No large data or result tree is in scope.

## Batch A — documents and manifests

| Source | Target | Operation | Compatibility / reference change |
|---|---|---|---|
| `CODEX_FAST3_OVERNIGHT_PROMPT.txt` | `fast3/docs/prompts/legacy/CODEX_FAST3_OVERNIGHT_PROMPT.txt` | `Move-Item` | none |
| `CODEX_FAST3_V22_081_PROMPT.txt` through `CODEX_FAST3_V22_086_PROMPT.txt` | `fast3/docs/prompts/legacy/<same name>` | `Move-Item` | none |
| `FAST3_V22_081_AUTHORIZATION.md` through `FAST3_V22_086_AUTHORIZATION.md` | `fast3/docs/authorizations/legacy/<same name>` | `Move-Item` | update shared FAST3 references |
| `FAST3_GENERATION2_AUTHORIZATION.md`, `FAST3_GENERATION3_AUTHORIZATION.md`, `FAST3_GENERATION3R2_AUTHORIZATION.md`, `FAST3_GENERATION3R3_AUTHORIZATION.md` | `fast3/docs/authorizations/legacy/generation/<same name>` | `Move-Item` | update shared FAST3 references |
| `FAST3_V22_083_PATCH_APPLIED.json` through `FAST3_V22_086_PATCH_APPLIED.json` | `fast3/manifests/patches/legacy/<same name>` | `Move-Item` | none |
| `FAST3_AUTONOMOUS_MASTER_DIRECTIVE.md` | `fast3/docs/governance/FAST3_AUTONOMOUS_MASTER_DIRECTIVE.md` | `Move-Item` | update `AGENTS.md`, `CODEX_GOAL.md`, `CODEX_PLAN.md`, and `CODEX_STATUS.md` references |
| `docs/FAST3_AUTORESEARCH_AGENT_SPEC.md` | `fast3/docs/governance/FAST3_AUTORESEARCH_AGENT_SPEC.md` | `Move-Item` | update `AGENTS.md` reference |

The three `docs/FAST3_GENERATION*AUTHORIZATION.md` files hash-identically to
the matching root files. They remain as one-line legacy location notices in
Batch A rather than a second incompatible copy. Backup files ending `.bak` are
not moved: their ownership and retention policy cannot be confirmed.

## Batch B — root launchers

| Source | Target | Operation | Compatibility |
|---|---|---|---|
| `run_fast3_overnight_autopilot.ps1` | `fast3/scripts/launch/legacy/run_fast3_overnight_autopilot.ps1` | `Move-Item` | root thin forwarding wrapper |
| `start_codex_fast3_full_chain.ps1` | `fast3/scripts/launch/legacy/start_codex_fast3_full_chain.ps1` | `Move-Item` | root thin forwarding wrapper |
| `start_codex_v22_080a.ps1` | `fast3/scripts/launch/legacy/start_codex_v22_080a.ps1` | `Move-Item` | root thin forwarding wrapper |

The wrappers only emit a deprecation notice, invoke the moved script with the
original arguments, and propagate `$LASTEXITCODE`.

## Batch C — inventory and audit tools

`fast3/scripts/audit/build_fast3_inventory.py` is new FAST3-000 code. It is
compiled and run in place. `fast3/tests/regression/` holds new synthetic
contract regressions; no historical test is moved in this batch.

## Batch D — explicitly deferred legacy-engine migration

`scripts/v22/fast3_agent/` (28 files) and `scripts/v22/run_fast3_*`,
`show_fast3_*`, and `stop_fast3_*` launchers remain in their existing locations
for this task. Exact resume commands emitted into immutable historical results,
direct test imports, and PowerShell launchers reference those paths. Moving
them safely requires generated Python export wrappers and updating only future
resume commands; that is a bounded follow-up after FAST3-002, not a cosmetic
rename. The dependency map records every known textual reference.

Legacy V22.049–V22.080 scripts/tests are similarly retained as immutable
historical implementation evidence. They are indexed by this migration rather
than being mass-moved into a new package.
