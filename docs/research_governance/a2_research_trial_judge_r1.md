# A2 Research Trial Judge R1

This control plane evaluates completed trial summaries; it does not train models, rebuild data, run backtests, or read a live research ledger.

- **Champion:** the frozen, explicitly governed incumbent. A metric sort cannot replace it.
- **Challenger:** a family-matched research candidate that has not become champion.
- **Promotion:** an explicit state transition after pre-2026 validity, stability, prospective shadow evidence, and user authorization. R1 never auto-promotes.
- **Prospective:** evidence collected after the decision was frozen, without retrospective parameter or model selection.
- **Invalid:** evidence with temporal/PIT/lineage failure, missing mandatory governance metadata, or prohibited 2026 use.
- **Unstable:** legal evidence whose aggregate result lacks broad fold support, destroys winners, or is dominated by one period.

Alpha models, risk models, and execution overlays have separate registries and leaderboards. Their objectives are different, so an R6 risk metric or E5 execution result is not comparable to an A2 alpha metric.

Highest historical Sharpe is not the champion. A champion also requires correct lineage, temporal validity, multi-period support, acceptable damage, prospective evidence, and an authorized registry transition. **Aggregate outperformance is insufficient if it is driven by a single historical period.** The judge therefore reports both aggregate deltas and leave-one-period-out deltas.

Under the current governance contract, **2026 is evaluation-only**. Training, parameter/threshold search, and candidate selection using 2026 cause `E_INVALID`. Unknown 2026-use metadata also fails closed through `MISSING_REQUIRED_METADATA`.

Default scientific edge thresholds are `null`, which means `INFORMATIONAL_ONLY`; R1 does not invent a Sharpe or IC hurdle. A trial can reach `A_STABLE_CHALLENGER` only when explicitly preregistered predictive and economic deltas are supplied, all validity gates pass, common support is sufficient, and winner/drawdown gates are evaluated and acceptable. Even then, `PROMOTION_ELIGIBLE=false` in R1.

The immutable-ledger adapter accepts only completed outer-test rows (`inner_fold=""` in the current runner; `OUTER_TEST` is also supported). Use the frozen `09_pre2026_freeze/pre2026_trial_manifest.parquet`, not the live `03_model_search` ledger. The adapter verifies its hash against `pre2026_freeze_manifest.json` (or a generic immutable manifest), groups folds by model family, and requires explicit trial metadata plus authoritative benchmark summaries/folds. Missing candidate economic fold evidence is not reconstructed. The live ledger is never a test fixture.
