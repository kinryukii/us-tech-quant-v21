# FAST3 migration report

## Completed batches

- Batch A moved 23 unambiguously FAST3-only prompts, authorizations, patch
  manifests, governance documents, and the agent specification into `fast3`.
- Batch B moved 3 root launchers into `fast3/scripts/launch/legacy/` and left
  3 root forwarding wrappers.
- Batch C added the inventory builder and FAST3-001 synthetic regressions.

`Move-Item` was used instead of `git mv` because every moved source was already
untracked before this task; `git mv` cannot preserve history that Git does not
have. The operation did not overwrite a destination. The rollback is the
explicit inverse move listed in `docs/reports/FAST3_000_MIGRATION_PLAN.md`.

## Retained paths

`scripts/v22/fast3_agent/`, V22.080 source/tests/runners, and all older V22
FAST3 research scripts remain as legacy implementation evidence. Their exact
paths occur in historical checkpoint resume commands and direct test imports.
The root shared files (`AGENTS.md`, `CODEX_GOAL.md`, `CODEX_PLAN.md`,
`CODEX_STATUS.md`, `pytest.ini`) remain; only live FAST3 documentation paths in
`AGENTS.md` and `CODEX_GOAL.md` were updated. Root `.bak` files remain untouched.

All ten retained `scripts/v22/run_fast3*.ps1` launchers that consumed moved
prompts or authorizations were updated to their new `fast3/docs/...` target.
Post-update PowerShell AST parsing passed and the old executable root-path
search returned 0 remaining references. Historical prose strings and immutable
resume commands may still name legacy V22 implementation paths; those paths
were intentionally retained, not broken migration references.

No canonical data, result directory, Git history, or user work was moved.
