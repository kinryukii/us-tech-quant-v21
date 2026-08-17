# Project agent instructions

## MANDATORY ANTI-BLOAT GOVERNANCE

Before material development work, Codex must read
`docs/governance/ANTI_BLOAT_POLICY.md` and obey its active contract.

- The repository is a lightweight code/control plane; large generated artifacts belong directly in approved external roots.
- A repository-local `.venv` is forbidden; use the external canonical runtime.
- Canonical data is read-only by default, and authoritative research evidence must be preserved.
- Determine the storage destination before creating an artifact.
- If persistence or deletion safety is uncertain, fail closed and preserve the item.
- Reuse or extend existing implementations before creating parallel ones.
- Functional `PASS` is impossible when an Anti-Bloat hard gate fails.

Codex may propose Anti-Bloat governance changes, but must not silently weaken
the policy. Any weakening requires explicit user authorization.
