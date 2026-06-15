# US Tech Quant

Research pipeline for V20 current-market ranking, research-only daily conclusions, and forward outcome validation.

This repository does not create broker orders, real trade recommendations, official portfolio actions, or portfolio weight mutations. Current V20 outputs are research artifacts unless every official promotion gate passes.

## V20 Current Status

Current bootstrap final status:

`PARTIAL_PASS_CURRENT_DAILY_RESEARCH_READY_FORWARD_OUTCOME_PENDING`

Current daily research is ready in research-only mode. Official promotion remains blocked.

Key current statuses:

- `CURRENT_DAILY_RESEARCH_LANE`: `WARN`, research-only ready.
- `V20.55`: `WARN_V20_55_RESEARCH_ONLY_READY_PROMOTION_BLOCKED`.
- Daily conclusion mode: `RESEARCH_ONLY_DAILY_CONCLUSION_READY_OFFICIAL_PROMOTION_BLOCKED`.
- `V20.97`: `PASS_V20_97_DAILY_RUNNER_OBSERVATION_BRIDGE_REPAIRED`.
- `V20.96`: `WARN_V20_96_INSUFFICIENT_VALID_OBSERVATION_RUNS`.
- Research observation count: `1`.
- Required run count: `5`.
- Official promotion eligible count: `0`.
- `FORWARD_OUTCOME_VALIDATION_LANE`: `PENDING_FORWARD_TARGET_DATES`.
- Forward lane first failed stage: `V20.27`.
- Required forward target dates: `2026-06-13` through `2026-08-11`.
- Latest available cache date: `2026-06-12`.

## Two-Lane Architecture

### CURRENT_DAILY_RESEARCH_LANE

Purpose: current market refresh, current research ranking, operator review, research-only daily conclusion, and V20.55 daily one-click research runner output.

Current status: research-only ready. The lane is `WARN` because official promotion is blocked, not because the daily research observation failed.

Observation rule: `WARN_V20_55_RESEARCH_ONLY_READY_PROMOTION_BLOCKED` counts as a valid research-only daily observation for accumulation. It does not count as official-promotion eligible.

### FORWARD_OUTCOME_VALIDATION_LANE

Purpose: PIT-safe forward outcome and benchmark validation.

Current status: pending at `V20.27`.

Reason: PIT-safe forward outcome and benchmark target dates from `2026-06-13` through `2026-08-11` are not available in cache yet. The latest available cache date is `2026-06-12`.

This is an expected gating state, not a bug. It must not be bypassed with fabricated outcomes, fabricated benchmark values, or uncertified target-date data.

## Observation Semantics

`WARN_V20_55_RESEARCH_ONLY_READY_PROMOTION_BLOCKED` means:

- `research_observation_valid=TRUE`
- `official_promotion_eligible=FALSE`

`V20.97` bridges this research-only observation into V20.96 using lane-aware semantics.

`V20.96` currently warns because valid research observations are `1` and `required_run_count` is `5`. Do not mark V20.96 PASS until the required observation count is satisfied by real daily observations.

## Promotion Safety

Official promotion remains blocked.

Current safety invariants:

- No official recommendation is created.
- No portfolio weight mutation is created.
- No trade action is created.
- No broker execution is supported.
- `research_only=TRUE` is preserved.

Current promotion blockers:

- V20.27 pending forward target dates / active outcome benchmark staging.
- Missing promotion lineage sources: `V20.35-R2; V20.36; V20.37; V20.38; V20.39; V20.40; V20.41; V20.42`.
- Existing official-promotion blockers remain preserved.

## Daily Operator Runbook

Run the current-chain bootstrap and daily research sequence:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/v20/run_v20_current_chain_bootstrap_repair.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/v20/run_v20_55_daily_one_click_research_runner.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/v20/run_v20_97_daily_runner_observation_bridge_repair.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/v20/run_v20_96_multi_run_observation_accumulation_orchestrator.ps1
```

Expected current result:

- V20.55 may return `WARN_V20_55_RESEARCH_ONLY_READY_PROMOTION_BLOCKED`.
- V20.97 should bridge the V20.55 research-only observation.
- V20.96 should remain `WARN_V20_96_INSUFFICIENT_VALID_OBSERVATION_RUNS` until five valid research observations exist.
- Official promotion should remain blocked while V20.27 and promotion lineage blockers remain.

## How To Interpret Outputs

Primary current status artifacts:

- `outputs/v20/read_center/V20_CURRENT_DAILY_CONCLUSION.md`
- `outputs/v20/repair/V20_CURRENT_CHAIN_BOOTSTRAP_REPAIR_STATUS.csv`
- `outputs/v20/repair/V20_CURRENT_CHAIN_LANE_STATUS.csv`
- `outputs/v20/repair/V20_CURRENT_DAILY_RESEARCH_LANE_STATUS.csv`
- `outputs/v20/repair/V20_FORWARD_OUTCOME_VALIDATION_LANE_STATUS.csv`
- `outputs/v20/evidence/V20_CURRENT_DAILY_RUNNER_OBSERVATION_BRIDGE.csv`
- `outputs/v20/evidence/V20_CURRENT_MULTI_RUN_OBSERVATION_ACCUMULATION.csv`
- `outputs/v20/evidence/V20_CURRENT_MULTI_RUN_OBSERVATION_ACCUMULATION_SUMMARY.md`

Read `V20_CURRENT_DAILY_CONCLUSION.md` first for the daily conclusion mode and lane status. Use the lane status CSVs to distinguish current daily research readiness from forward outcome validation blockers. Use the V20.97 bridge and V20.96 accumulation artifacts to confirm research observation count and official-promotion eligibility count.

## Known Non-Bugs

- `V20.27` blocked / `PENDING_FORWARD_TARGET_DATES` is expected until PIT-safe future target dates exist.
- `V20.96` `WARN_V20_96_INSUFFICIENT_VALID_OBSERVATION_RUNS` is expected until research observation count reaches `5`.
- `V20.55` `WARN_V20_55_RESEARCH_ONLY_READY_PROMOTION_BLOCKED` is expected while official promotion remains blocked.
- Yahoo runtime unavailable may be handled through certified cache fallback when available. Do not describe certified cache fallback as a live refresh.

## Next Development Priorities

- Continue collecting daily research-only observations until V20.96 reaches `required_run_count=5`.
- Keep V20.27 pending until real PIT-safe forward target-date data becomes available, or authoritative local PIT-safe outcome/benchmark rows are imported with provenance.
- Repair missing promotion lineage sources: `V20.35-R2; V20.36; V20.37; V20.38; V20.39; V20.40; V20.41; V20.42`.
- After sufficient observations and lineage repairs, rerun promotion blocker decomposition.
- Do not open official promotion until all gates pass.

See `docs/V20_CURRENT_STATUS.md` for the short current-state runbook and status summary. See `docs/v20/V20_CURRENT_DEVELOPMENT_STATUS.md` for the current development status after V20.98 blocker tracing.
