# V20 Current Status

Status date: current repository state after the V20 lane-aware observation repair.

## Summary

- Bootstrap final status: `PARTIAL_PASS_CURRENT_DAILY_RESEARCH_READY_FORWARD_OUTCOME_PENDING`
- Current daily research lane: `WARN`, research-only ready
- V20.55: `WARN_V20_55_RESEARCH_ONLY_READY_PROMOTION_BLOCKED`
- Daily conclusion mode: `RESEARCH_ONLY_DAILY_CONCLUSION_READY_OFFICIAL_PROMOTION_BLOCKED`
- V20.97: `PASS_V20_97_DAILY_RUNNER_OBSERVATION_BRIDGE_REPAIRED`
- V20.96: `WARN_V20_96_INSUFFICIENT_VALID_OBSERVATION_RUNS`
- Research observation count: `1`
- Required run count: `5`
- Official promotion eligible count: `0`
- Forward outcome validation lane: `PENDING_FORWARD_TARGET_DATES`
- Forward lane first failed stage: `V20.27`
- Required forward target dates: `2026-06-13` through `2026-08-11`
- Latest available cache date: `2026-06-12`
- Official promotion: `BLOCKED`

## Lane Model

### CURRENT_DAILY_RESEARCH_LANE

This lane handles the current market refresh, current research ranking, operator review, research-only daily conclusion, and V20.55 daily one-click research runner.

Current state is research-only ready. The lane is `WARN` because official promotion remains blocked. `WARN_V20_55_RESEARCH_ONLY_READY_PROMOTION_BLOCKED` is a valid research-only daily observation.

Current observation semantics:

- `research_observation_valid=TRUE`
- `official_promotion_eligible=FALSE`
- `official_recommendation_created=FALSE`
- `weight_mutated=FALSE`
- `trade_action_created=FALSE`

### FORWARD_OUTCOME_VALIDATION_LANE

This lane handles PIT-safe forward outcome and benchmark validation.

Current state is `PENDING_FORWARD_TARGET_DATES` at `V20.27`.

Current V20.27 reason:

- `PIT_SAFE_FORWARD_OUTCOME_TARGET_DATES_NOT_AVAILABLE`
- `PIT_SAFE_FORWARD_BENCHMARK_TARGET_DATES_NOT_AVAILABLE`

The required target-date window is `2026-06-13` through `2026-08-11`. The latest available cache date is `2026-06-12`. This is expected and must not be bypassed.

## Promotion Safety

Official promotion remains blocked. The system must not fabricate forward outcomes, benchmark values, or PIT-safe certification.

No current V20 daily run creates:

- Official recommendation
- Portfolio weight mutation
- Trade action
- Broker execution

Remaining promotion blockers:

- V20.27 pending forward target dates / active outcome benchmark staging.
- Missing promotion lineage sources: `V20.35-R2; V20.36; V20.37; V20.38; V20.39; V20.40; V20.41; V20.42`.
- Existing official-promotion blockers remain preserved.

## Daily Operator Runbook

Use the actual wrapper names in this repository:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/v20/run_v20_current_chain_bootstrap_repair.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/v20/run_v20_55_daily_one_click_research_runner.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/v20/run_v20_97_daily_runner_observation_bridge_repair.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/v20/run_v20_96_multi_run_observation_accumulation_orchestrator.ps1
```

Expected interpretation:

- V20.55 WARN is acceptable when it is `WARN_V20_55_RESEARCH_ONLY_READY_PROMOTION_BLOCKED`.
- V20.97 PASS means the bridge recognized valid research-only observations.
- V20.96 WARN is expected until the valid research observation count reaches `5`.
- Official promotion remains blocked unless all promotion gates pass.

## How To Interpret Outputs

Read these artifacts in order:

1. `outputs/v20/read_center/V20_CURRENT_DAILY_CONCLUSION.md`
2. `outputs/v20/repair/V20_CURRENT_CHAIN_BOOTSTRAP_REPAIR_STATUS.csv`
3. `outputs/v20/repair/V20_CURRENT_CHAIN_LANE_STATUS.csv`
4. `outputs/v20/repair/V20_CURRENT_DAILY_RESEARCH_LANE_STATUS.csv`
5. `outputs/v20/repair/V20_FORWARD_OUTCOME_VALIDATION_LANE_STATUS.csv`
6. `outputs/v20/evidence/V20_CURRENT_DAILY_RUNNER_OBSERVATION_BRIDGE.csv`
7. `outputs/v20/evidence/V20_CURRENT_MULTI_RUN_OBSERVATION_ACCUMULATION.csv`
8. `outputs/v20/evidence/V20_CURRENT_MULTI_RUN_OBSERVATION_ACCUMULATION_SUMMARY.md`

The daily conclusion and lane status files explain why current research is ready while forward validation is pending. The bridge and accumulation files show whether the daily runner observation is valid for research accumulation and whether it is official-promotion eligible.

## Known Non-Bugs

- `V20.27` blocked / `PENDING_FORWARD_TARGET_DATES` is expected until PIT-safe future target dates exist.
- `V20.96` `WARN_V20_96_INSUFFICIENT_VALID_OBSERVATION_RUNS` is expected until research observation count reaches `5`.
- `V20.55` `WARN_V20_55_RESEARCH_ONLY_READY_PROMOTION_BLOCKED` is expected while promotion remains blocked.
- Yahoo runtime unavailable may be handled through certified cache fallback when available. Certified cache fallback is not a live refresh.

## Next Development Priorities

- Continue collecting daily research-only observations until V20.96 reaches `required_run_count=5`.
- Keep V20.27 pending until real PIT-safe forward target-date data becomes available, or authoritative local PIT-safe outcome/benchmark rows are imported with provenance.
- Repair missing promotion lineage sources: `V20.35-R2; V20.36; V20.37; V20.38; V20.39; V20.40; V20.41; V20.42`.
- After sufficient observations and lineage repairs, rerun promotion blocker decomposition.
- Do not open official promotion until all gates pass.
