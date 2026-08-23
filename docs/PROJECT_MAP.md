# Project map

This is the compact navigation map for the repository. It identifies where to
look; registries, manifests, hashes, and tests remain the status authorities.
Never classify an asset from its filename or apparent age alone.

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
| Storage routing and canonical data | `ACTIVE`; canonical data read-only | `config/storage_paths.json`, `scripts/common/storage_paths.py`, `scripts/common/storage_paths.ps1`, `docs/STORAGE_LAYOUT.md` |
| 13F PIT engineering | `ACTIVE` PIT utilities; individual experiments otherwise `UNKNOWN` | `scripts/v22/pit_13f_reconstruction_r1.py`, its callers/tests, and external lineage manifests |
| A / A2 alpha research | `ACTIVE` and `EXPERIMENTAL`; frozen identities only where a hash/contract says so | `scripts/v22/abcde_a2_*`, paired `test_*.py`, and, when present, `config/research_governance/alpha_registry.json` |
| A2 risk research | `ACTIVE`; R6 is a frozen prospective reference in current evidence | `scripts/v22/a2_stock_risk_r6.py`, `scripts/v22/a2_stock_risk_r10_r11_fast_track.py`, paired tests, and the risk registry when present |
| Execution / portfolio policy | `ACTIVE` research; adopted identities may be `FROZEN` | `scripts/v22/abcde_a2_r1c_execution_contract_freeze_r1.py`, `scripts/v22/abcde_a2_r4_portfolio_translation_using_hgb_incumbent.py`, and the execution registry when present |
| 2026 holdout | `EVALUATION_ONLY` and already exposed for A2 | `D:\us-tech-quant-results\A2_ALGORITHM_R2_2026_FROZEN_HOLDOUT\status.json`; it records prior exposure and blocks pristine-holdout reuse/optimization |
| Forward / prospective evaluation | `EVALUATION_ONLY`; no training/search/selection | `scripts/v22/forward_shadow/`, `config/research_governance/a2_forward_shadow_unified_r1.json`, and `docs/research_governance/` when present |
| FAST3 | `ACTIVE` implementation, currently synthetic-only; frozen confirmation remains unread | `fast3/state/FAST3_STATE.json`, `fast3/manifests/registries/FAST3_STAGE_REGISTRY.json`, `fast3/FAST3_STATUS.md` |
| FAST legacy/supersession | Mixed; use registries, not version names | `fast3/manifests/registries/`, `fast3/scripts/audit/build_fast3_inventory.py`, and compatibility/legacy mappings |
| Tests | `ACTIVE` existing pytest system | Paired `scripts/v*/test_*.py`, `fast3/tests/`, `tests/`, and `pytest.ini` |
| Anti-Bloat | `ACTIVE`; policy and thresholds are authoritative | `docs/governance/ANTI_BLOAT_POLICY.md`, `configs/anti_bloat_policy.toml`, `fast3/scripts/audit/run_fast3_guard.py` |
| Harness R1/R2 | `ACTIVE` repository guards and one-task control plane | `scripts/maintenance/harness_preflight.py`, `scripts/maintenance/harness_task.py`, paired tests, and root `AGENTS.md` |
| V21 daily/history | Mixed; do not assume obsolete | `docs/V21_ACTIVE_SYSTEM_REGISTRY.md`, `config/v21/active_chain_manifest.json`, and the V22 active/deprecated output manifest implementation |
| Results and evidence | Protected external evidence | `D:\us-tech-quant-results`, `D:\us-tech-quant-backtests`, `D:\us-tech-quant-daily`; never rewrite for ordinary development |

Broad `scripts/v22` contents are not collectively authoritative. Multiple versions
and experiments coexist. Locate a candidate with `rg`, inspect paired tests and
callers, then confirm status from a registry, manifest, freeze hash, or current
task contract. If those disagree or are missing, classify it `UNKNOWN`.

## Hard temporal facts

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

## Search and creation decision

1. `rg --files | rg -i '<concept>'`
2. `rg -n -i '<symbols-or-semantics>' scripts fast3 tests config docs`
3. Inspect callers, tests, configs, manifests, results pointers, and older versions.
4. Classify `AUTHORITATIVE / ACTIVE / FROZEN / SUPERSEDED / EXPERIMENTAL / UNKNOWN`.
5. Reuse or extend. Create only if no safe fit exists, a freeze prevents change,
   or clean separation is justified; report why reuse was insufficient.

Cheap preflight:

`& D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe scripts\maintenance\harness_preflight.py`

One bounded autonomous task:

`& D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe -B scripts\maintenance\harness_task.py start --goal "<bounded task>"`

No clearly authoritative, non-frozen shared A2 training/split entrypoint currently
owns every model fit. R1 cutoff and PIT helpers therefore remain centralized in
the preflight and research contracts; integrate them only when an authorized
shared entrypoint is identified, never by modifying a frozen A2 implementation.
