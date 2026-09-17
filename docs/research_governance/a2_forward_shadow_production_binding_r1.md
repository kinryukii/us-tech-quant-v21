# A2 Forward Shadow Production Binding R1

## Scope

This layer binds the existing Unified Runner to verified frozen Alpha, Risk,
and Execution identities. It discovers and references artifacts; it does not
copy, modify, train, tune, select, infer, trade, refresh canonical data, or
migrate legacy shadow history.

R1A adds exact-date component entrypoints around the immutable artifacts. They
consume hash-verified input records, return the existing normalized component
schema, and rely on the Unified Runner for transactional staging. They never
append legacy or authoritative history directly.

## Authoritative identity

The binding manifest is
`config/research_governance/a2_forward_shadow_production_binding_r1.json`.
It records registry identity, freeze identity, ordered artifact references and
SHA-256 values, composite identity, runtime/entrypoint references, and approved
external roots. It never contains model bytes or synthetic hashes.

- Alpha: `A2_HGB`, freeze `A_A2_QUARTERLY_13F_CLEAN_BASELINE_R1`.
- Risk: `R6_BAD_ASYMMETRY`, freeze `R6_BAD_ASYMMETRY_FROZEN_REFERENCE`.
- Execution: `E5_COMBINED_CONSERVATIVE`, freeze
  `E5_COMBINED_CONSERVATIVE_FROZEN_REFERENCE`.

R6 and E5 identities require `PRE2026_ONLY`; 2026 evidence is prospective
evaluation evidence, not a source of model or rule selection.

## Adapter contract

Each adapter exposes:

- `component_id`, `component_role`, `freeze_id`, and `artifact_identity`;
- `validate_binding()` and `validate_runtime()`;
- `validate_target_date_inputs()`;
- `build_execution_plan()`.

Preflight calls only these methods. It never calls `prepare()`, `execute()`, or
any model-loading API. Execution is reachable only after exact-date readiness
contains immutable ALPHA/RISK/EXECUTION input references and all normal runner
gates pass.

## Exact-date readiness

`a2_forward_shadow_readiness_r1.py` performs read-only checks for the exact
requested date. It verifies the immutable binding, canonical pointer/manifest,
the forward-shadow calendar contract, the frozen 13F universe snapshot, feature
contract, and component-input hashes. It never falls back to a prior date and
never refreshes or repairs an input. `latest_completed_us_session` and
`canonical_lag_sessions` are informational and cannot mutate `target_date`.

Readiness output is an exclusive-created, timestamped JSON record under
`D:\us-tech-quant-results\a2-forward-shadow-readiness`, plus a SHA-256 sidecar.
No `latest.json` is authoritative. Unified preflight requires both the exact
record path and its expected SHA-256.

Read-only readiness command:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  'D:\us-tech-quant\scripts\v22\run_a2_forward_shadow_readiness_r1.ps1' `
  -TargetDate '2026-08-21'
```

Read-only unified preflight command:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  'D:\us-tech-quant\scripts\v22\run_a2_forward_shadow_unified_r1.ps1' `
  -TargetDate '2026-08-21' `
  -Mode 'Preflight' `
  -ReadinessJson '<immutable-readiness-json>' `
  -ReadinessSha256 '<verified-readiness-sha256>' `
  -StatusOutput '<new-external-status-json>'
```

## Production roots and legacy preservation

Future Unified staging and authoritative roots are separate external paths
under `D:\us-tech-quant-results\A2_FORWARD_SHADOW_UNIFIED_R1`. Existing Alpha,
R6, and E5 histories remain untouched and are only provenance references.
They are not backfilled into a fabricated genesis/hash chain.

## Governance firewall

The runner retains `require_frozen_hashes=true`, append-only operation,
overwrite prohibition, no canonical auto-refresh, and hard prohibitions on
training, parameter/threshold search, model selection, and broker action.
Forward shadow is prospective simulation, not production trading. Its output
cannot automatically feed training or selection.

## Fail-closed outcomes

Binding identity can pass while exact-date readiness fails. A missing canonical
date, missing component input, changed hash, or wrong registry
champion/role/freeze forbids production. Production remains unauthorized until
a fresh immutable readiness record and its hash pass all exact-date checks.
