# A2 Forward Shadow Unified Runner R1

## Purpose and boundary

This runner is an inference-only control plane for the frozen Alpha, Risk, and
Execution prospective shadows. It resolves and verifies the registered
components, validates one exact target date, executes adapters into staging,
reconciles their outputs, and publishes an append-only daily transaction only
after every gate passes.

It does **not** train, fit, tune, select models, refresh canonical data, run a
historical backtest, place broker orders, or change A2, R6, or E5. Forward
shadow is not production trading or live deployment. E5 shadow output only
simulates the frozen execution overlay on forward data.

The current resolved roles are:

- Alpha: `A2_HGB`, `ALPHA_CHAMPION`, `FROZEN_CHAMPION`
- Risk: `R6_BAD_ASYMMETRY`, `RISK_CHAMPION`, `B_PROSPECTIVE_SUPPORTED`
- Execution: `E5_COMBINED_CONSERVATIVE`, `EXECUTION_CHAMPION`, `PREFERRED_PRE2026`

The runner reads these identities from the existing registries. It does not
copy or update champion declarations.

## Run state machine

```text
PREPARED -> STAGED -> VALIDATED -> COMMITTING -> COMMITTED
     |         |          |             |
     +---------+----------+-------------+
                 failure
                    |
        FAILED_PRE_COMMIT / FAILED_COMMIT / RECOVERY_REQUIRED
```

Windows cannot provide a database-level ACID transaction for several files.
R1 therefore implements a transactional filesystem protocol: close and fsync
temporary JSON, atomically replace individual files on the same volume, move
the validated staging directory once, verify hashes, and write `COMMIT.json`
last. Only a transaction with a valid final marker is authoritative.

## Preflight contract

One invocation processes exactly one `target_date`. The requested date must be
present in canonical data, be an eligible trading date, and have the exact
feature and universe snapshots. Partial or future dates fail closed. The
runner never falls back to an earlier date.

Production also requires an immutable canonical manifest, frozen component
identity, and materialized SHA-256 hashes. `UNKNOWN` is not treated as pass.
Canonical refresh is a separate operation and is disabled by default.

## Component adapter contract

Each `ShadowComponent` implements `prepare`, `validate_inputs`, `execute`,
`validate_output`, and `stage_payload`. Roles are `ALPHA`, `RISK`, and
`EXECUTION`. Adapters normalize existing frozen outputs; they must not copy or
reimplement model mathematics. R6 and E5 outputs declare the upstream Alpha
run, and E5 declares its upstream Risk run when applicable.

The supplied `SyntheticComponent` is fixture-only. Production adapter entries
remain `REQUIRED_AT_PRODUCTION` until authoritative bindings are reviewed.
Production additionally requires an exact-date immutable readiness JSON; it
never accepts the synthetic fixture or silently substitutes another date.

## Reconciliation and governance

All component outputs must use the same target date. Lineage IDs must equal the
current unified `run_id`. Security-set differences are reported explicitly;
the default policy rejects Risk or Execution securities absent from Alpha.
Allowed downstream filtering remains visible rather than being silently
dropped.

2026 inference, evaluation, and forward shadow are allowed. Training,
parameter or threshold search, model selection, and broker action are always
forbidden. Any adapter reporting such activity fails governance and prevents
commit. Manifests set `research_feedback_allowed=false` so shadow results do
not flow automatically into research selection.

## Append-only and duplicate semantics

The daily identity includes the exact date, canonical manifest hash, universe,
configuration hash, component IDs, freeze IDs, and artifact hashes. A file name
alone is never a duplicate key.

- Same date and identical immutable identity: `ALREADY_COMMITTED_IDENTICAL`;
  zero new rows are appended.
- Same date but different hash, model, or freeze: `CONFLICT_EXISTING_COMMIT`.
- Same date with staging or an incomplete published transaction:
  `RECOVERY_REQUIRED`.
- Overwrite, historical mutation, deletion, and silent replacement are
  forbidden.

## Recovery and locking

`resume` is allowed only when the staged identity exactly matches the date,
canonical hash, component hashes, config hash, and model identities. Changed
inputs return `RESUME_FORBIDDEN_INPUT_CHANGED`; start a separately reviewed new
run instead of altering the failed run.

The date lock records its owner PID, run ID, and creation time. A second active
owner is denied. Unknown or apparently stale locks are retained and return
`STALE_LOCK_REVIEW_REQUIRED`; R1 never deletes them automatically. Failed
production staging is retained as evidence.

## Daily manifest and hash chain

The final manifest records canonical and component identities, all output
hashes, reconciliation hash, governance firewalls, and the preceding daily
manifest SHA-256. The first committed day is explicitly a `GENESIS_MANIFEST`.
`validate-history-chain` checks predecessor hashes, duplicate dates, missing
predecessors, and non-committed manifests. It is a lightweight integrity chain,
not a blockchain and not a substitute for filesystem access control.

## Safe validation commands

These commands use only the tiny static fixture and do not invoke production:

```powershell
& 'D:\us-tech-quant\scripts\v22\run_a2_forward_shadow_unified_r1.ps1' `
    -TargetDate '2026-08-21' -Mode 'ValidateFixture'
```

```powershell
& 'D:\us-tech-quant\scripts\v22\run_a2_forward_shadow_unified_r1.ps1' `
    -TargetDate '2026-08-21' -Mode 'DryRun' `
    -WorkspaceRoot 'D:\us-tech-quant-results\forward-shadow-r1-synthetic-test'
```

## Future production procedure

After authoritative production roots, readiness adapter, and all three legacy
component adapter factories have been configured and their hashes are
materialized:

1. Confirm canonical data readiness independently.
2. Run exact-date `Preflight`.
3. Run `Production` for the same date.
4. Require `COMMIT_STATUS=COMMITTED`.
5. Verify the final manifest hash and chain.
6. Optionally run read-only `Status`.

Never delete and rerun, overwrite a date, or edit a ledger or manifest by hand.

## Frozen prospective evidence operating program R1

Task: `FROZEN_PROSPECTIVE_EVIDENCE_OPERATING_PROGRAM_R1` (Track B).
This section clarifies the operational/reveal boundary; it does not activate a
policy, alter a freeze, or authorize economic access. The read-only monitor is
`scripts/research/a2/portfolio_control/prospective_operating.py`. Run from the
repository with the canonical external Python runtime:

```powershell
& D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe -B -m scripts.research.a2.portfolio_control.prospective_operating status
```

The monitor delegates RX issuance validation to the existing canonical lifecycle
implementation. It reads Raw A2's hash-bound governance contract and checks file
existence. It never runs a strategy, opens an economic ledger/state, records an
observation, schedules a worker, or reveals economics. Its metadata validation
success is not evidence-collection readiness. A missing/currently unverified
count is `UNKNOWN`, never inferred as zero from the registration-time attestation.

### Observation set and authority

| Object | Existing authority | Operating admission |
| --- | --- | --- |
| `RAW_A2` / full-pre2026 `A2_HGB` | `A2_THREE_ARM_POSTFREEZE_FORWARD_R1/forward_contract.json`; model SHA `4f7eff07021bef084b0329dac8dabc31e9391c7c4945eb2955dc6c1339dcea0b`; portfolio SHA `9d8a0d1aa7da8f6588addd9620207a82f328d2e0eab2ecced163cbe51656f881` | Frozen control and recorder exist; producer activation and safe current observation receipt are unverified. |
| `RX_MARGIN_R1` / `RX_MARGIN_RANGE_EXHAUSTION_LINEAGE` | Canonical issuance registration `2323f9fb713243c773febbd2df9e05ec7d543495e8948d2aa9bdf19d82e29c31`; activation manifest `21f102e493dd598241e4fba3680b58cd8433b283cf7b96dbd382d556f7bc8997` | Issued prospective authority; no accepted recorder/observation-path binding found. Recording readiness remains blocked. |
| Frozen R5 Range Exhaustion source/control | RX frozen contract references source fingerprint `569fc218d8b2751abbfd016d12523546a3babb06f7f84a6bce35e80cc0023a15` | Source identity only; no separate active observation arm is inferred. |

The sole RX issuance is in resolved results_root /
`US_TECH_QUANT_PROSPECTIVE_ACTIVATION_AUTHORITY_R1`. Its validator/config/calendar
live in the existing `rx-margin-r1-prospective-activation-r1` worktree; the main
worktree's older lifecycle is not substituted. No second registry is created.
RX frozen contract remains results_root /
`RANGE_EXHAUSTION_SCORE_MARGIN_OVERLAY_R1/frozen_contract.json`, SHA
`e9735b812549bd147a4fa311027f5d5cc0cedf06bbe29352c4cd564fa449832e`.

Raw freeze is `2026-08-23T08:41:53.231458+00:00`, first eligible execution session
`2026-08-24`; this is eligibility, not proof that a producer ran. Reuse its exact
after-close decision, next-session open execution, following-session open outcome,
top20 equal weights and frozen accounting/cost contract without changes. Inputs
remain the existing hash-bound exact-date `session_input.json` pointer under
daily_root / `current/A2_THREE_ARM_POSTFREEZE_FORWARD_R1`; missing PIT/identity/
calendar authority blocks that session and never permits fallback or backfill.

RX issued at `2026-09-04T18:48:34.399739Z`; first legal epoch is
`SIGNAL_2026-09-08__EXECUTION_2026-09-09`: signal/decision eligibility
`2026-09-08T21:00:00Z`, execution `2026-09-09T13:30:00Z`. Reuse the issued profile,
its lead-time rule and finite authoritative calendar. Do not extend the calendar
or infer an open epoch after coverage ends. RX's fixed 1.0 population-sigma veto
uses Range Exhaustion scores; it is not a Raw-A2-score threshold. The historical
simulator reference alone does not bind a forward accounting implementation.

The unified A2/R6/E5 triad and R2B `M0_A2_HGB` OUTER_2025 model (SHA `5554ca8a...`)
are distinct identities. R2B initialization/backfill, retrospective diagnostics,
and synthetic transactions are not new observations for this set. Existing S1,
gross-scaler, attenuation, XGB/blend, 13F/H5 or other candidates are not admitted
by this task. No economic result was used to determine admission.

### Operational access and economic evidence

Daily access is limited to typed authority/schema status, fixed identity hashes,
activation/decision/execution clocks, input/output existence, missing/stale input,
fixed rejection categories, deterministic execution/observation identity, and
failure/recovery linkage where the existing recorder actually supplies it.
Unimplemented fields remain UNKNOWN. Free-form exception text, events, holdings,
scores, prices, returns, NAV, contribution, cost realization and rankings are
excluded. In particular, Raw `status` reads mixed state/ledger; the old unified
full execution status may carry free-form errors; neither is a blind monitor.

Raw economic evidence stays at its existing `forward_ledger.csv` and
`forward_state.json` paths under results_root / `A2_THREE_ARM_POSTFREEZE_FORWARD_R1`.
They are protected economic records, not a claim of cryptographic or OS sealing.
RX has no accepted economic observation path in its issuance bundle: `UNKNOWN`.
Do not create an alternative economic store or map it to R2B/unified outputs.
The monitor offers no economic read/reveal command and does not dereference
economic artifact references. Repository-wide filesystem access enforcement has
not been established by this interface.

### Reveal contract

Raw retains its exact frozen milestones: **20 OPERATIONAL_ONLY; 60 EARLY_ECONOMIC;
120 FORMAL_FORWARD_REVIEW; 250 ANNUAL_SCALE_REVIEW**. Do not reset the counter or
change these epochs. An operational count is a count of distinct eligible
committed sessions, not rows, attempts, or statistically independent samples.
These milestone labels alone do not implement access approval or formal criteria.

RX has no frozen reveal schedule in the accepted activation. Minimal draft status:
`OWNER_APPROVAL_REQUIRED_BEFORE_ECONOMIC_REVEAL`. No new numeric/date schedule is
selected. Before its first economic reveal the owner must approve a concrete
schedule, authorized reader, evidence cutoff and descriptive scope without
inspecting sealed results. Daily operational monitoring is separate from a
scheduled descriptive reveal, which grants no tuning, selection or promotion.
Formal promote/reject evaluation additionally requires its own predeclared
benchmark, metric, maturity, costs and decision rules; none are chosen here.
No elapsed time, milestone or successful test automatically authorizes access.

### Contamination, failure and recovery

Preserve Raw's `EXPOSED_HISTORY_NOT_FORWARD` classification and all earlier A2
exposure. RX's historical zero-access freeze attestation is time-scoped and does
not erase subsequent retrospective access. R2B's existing
`forward_contamination_audit.json` is local to its own ledger, not a global clean
bill. No new contamination ledger is created. This task's access accounting is
in its single results_root report; any future actual reveal must be recorded in
the applicable existing receipt/trial mechanism before claiming untouched scope.

Reuse canonical recorder identity/locking/commit semantics. Identical retries
must contribute no additional observation; changed authority or configuration
must fail closed. A failed or incomplete session is not economic evidence.
Recovery must retain the original session/activation identity and failure link;
post-outcome reconstruction cannot manufacture an ex-ante decision. Missing
sessions and outages remain visible; they cannot be selectively removed.
The unified transaction protocol demonstrates these limited mechanics, but
does not supply RX activation binding. Raw rejects duplicate ledger sessions;
its multi-file state/manifest update is not an atomic transaction. Neither source
is modified or declared fully recovered by this operating contract.

### Required closure before collection can be accepted

The owner/deployment authority must identify the accepted existing RX recorder
and bind its policy/model/config, data authority, execution/accounting, activation
and observation/economic paths; establish the required source/control role;
and resolve Raw producer admission plus operational receipts. This is not a
request to change parameters or build another runner. Absent those identities,
this program remains operational-monitoring-only and collection readiness is
blocked. An approved reveal contract remains a separate owner decision.

Validation must use isolated synthetic fixtures and access interception. The
legacy Raw tests call real initialization, and some unified tests load real
registries before applying synthetic overrides; do not run them unchanged for
an outcome-free task. Do not launch Harness/preflight or real forward execution
to test this section. Program acceptance requires evidence at each layer;
document loading, synthetic protocol tests, economic validity, and live readiness
are separate claims. A forward session adds a fixed-scope record, not necessarily
one statistically independent sample.
The production command templates are included in the engineering handoff; they
must not be run until the required production bindings are authoritative.
