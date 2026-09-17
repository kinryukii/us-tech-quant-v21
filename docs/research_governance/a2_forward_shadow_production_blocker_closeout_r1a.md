# A2 Forward Shadow Production Blocker Closeout R1A

## Structural result

R1A closes the calendar-horizon and safe-entrypoint blockers without refreshing
data or running production inference. The three frozen economic identities are
unchanged. New code wraps them; it does not edit their source, thresholds,
feature equations, ranking rules, or model binaries.

## Trading calendar

`ForwardShadowTradingCalendarProvider` binds to the repository's frozen R26A2
NYSE full-day closure rules. The compact contract covers 2026-01-01 through
2027-12-31, contains 501 normal sessions, and pins both the source hash and the
deterministic session-list hash. Weekends and the NYSE holidays represented by
that source are non-sessions. Early closes remain eligible sessions; 16:00 ET is
used conservatively when reporting whether a session is complete.

Calendar metadata is operational provenance, not a model-freeze change. Future
daily manifests carry `trading_calendar_id` and `trading_calendar_sha256`.

## Exact-date input contract

Readiness may reference one immutable JSON input for each role:

```text
component_inputs:
  ALPHA: {path, sha256}
  RISK: {path, sha256}
  EXECUTION: {path, sha256}
```

Each record must name exactly the requested date. Alpha rows contain the frozen
A2 feature schema and security identity. Risk rows contain the frozen R6 feature
schema and exact Alpha run lineage. Execution rows contain the previous executed
Top20 state, prior Alpha ranks, and exact Alpha/Risk run lineage. A missing,
changed, or wrong-date record fails closed.

## Component behavior

- Alpha loads the verified A2 model, calls `predict`, and calls the frozen A2
  `_prediction_rank`; Top20 size is read from the frozen contract.
- Risk loads the verified R6 deploy artifact, uses its frozen feature list,
  model and pre-2026 reference distribution, and reads the intervention rule
  from the frozen R11 preregistration.
- Execution imports the hash-verified E5 source and directly calls
  `build_executed_targets("E5_COMBINED_CONSERVATIVE", ...)` over prior state and
  the requested date.

No adapter exposes fit, search, selection, broker, legacy append, canonical
write, or authoritative commit behavior. Component results are written only by
the existing Unified transaction staging protocol.

## Readiness time semantics

The generator accepts `as_of_timestamp` and an operator timezone. It reports
`latest_completed_us_session`, `target_session_completed`, and
`canonical_lag_sessions`. These fields are informational. `-TargetDate` remains
mandatory and is never replaced with the latest completed date.

Canonical readiness can legitimately remain `FAIL_CANONICAL_NOT_READY` after
this structural closeout. Data repair/refresh is a separate authorized task.
