# FAST3-000 repository inventory

Generated from `fast3/scripts/audit/build_fast3_inventory.py` before the first
move. The immutable snapshot manifests are:

- `fast3/manifests/FAST3_000_FILE_INVENTORY.json` (835 matched files)
- `fast3/manifests/FAST3_000_DEPENDENCY_MAP.json` (835 dependency nodes)

The search covered the required FAST3/V22 identifiers, symbols, session terms,
predictability terms, frozen-validation/confirmation terminology, root files,
`scripts/v22`, `state`, documentation, and configuration text. Of 835 matches,
87 were initially classified as explicit migration candidates, 603 as runtime
entry candidates, 577 as files containing a frozen-contract term, and 401 as
files containing a result/status term. These are textual classifications, not
claims that every matched historical script belongs to the active package.

## Result roots and entry points

Canonical data is referenced by FAST3 as
`D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical` and was not moved.
Observed external result roots include `fast3_autoresearch`, Generation 2/3/3R2/3R3,
and V22.081–V22.086 roots under `D:\us-tech-quant-results`; none was moved.

V22.080A/B launchers remain at `scripts/v22/` as historical runners. The three
root launchers were moved under `fast3/scripts/launch/legacy/` and are forwarded
by root compatibility wrappers. `scripts/v22/fast3_agent/` remains in place by
the dependency decision recorded in the migration plan.

## Ownership decisions

Unambiguously FAST3-only prompts, authorizations, patch manifests, governance
documents, agent specification, and root launchers were moved in the audited
small batches. `AGENTS.md`, root `CODEX_*` state files, `pytest.ini`, and general
project files remain shared. Duplicate Generation 3 authorization copies in
`docs/` were verified hash-identical to the root originals before migration and
are retained as legacy compatibility copies. Backup `.bak` files remain at root
because their retention ownership is not certain.
