# FAST3 GENERATION 2 — EXPLICIT NEW RESEARCH AUTHORIZATION

This is explicit authorization to start a new FAST3 research generation.

The prior V22.080/V22.080B generation is closed and must remain immutable:

- prior decision: PREDICTABILITY_NOT_ECONOMICALLY_ACTIONABLE
- prior status: FAIL_NO_ROBUST_EDGE
- prior Confirmation read count: 0
- prior Validation results must not be reused for tuning
- prior rejected candidate must not be silently relabeled as a new candidate
- prior output files and hashes must not be overwritten

Generation 2 is a new research generation, not a continuation or reopening of
the rejected frozen generation.

Before implementing anything:

1. Read:
   - AGENTS.md
   - docs/FAST3_AUTORESEARCH_AGENT_SPEC.md
   - CODEX_GOAL.md
   - CODEX_PLAN.md
   - CODEX_STATUS.md
   - all prior FAST3 split, window, experiment and checkpoint manifests

2. Audit and record every historical date/window that was previously used for:
   - feature development
   - model fitting
   - parameter selection
   - Validation
   - randomized OOS comparison
   - Confirmation, if any

3. Create a Generation 2 data-usage ledger classifying dates as:
   - PREVIOUSLY_USED_DEVELOPMENT
   - PREVIOUSLY_USED_VALIDATION
   - PREVIOUSLY_USED_RANDOMIZED_SELECTION
   - PREVIOUSLY_UNREAD_ELIGIBLE
   - PROSPECTIVE_ONLY
   - INELIGIBLE_OR_AMBIGUOUS

4. Freeze a new Generation 2 Development/Validation/Confirmation contract before
   examining Generation 2 economic results.

5. Do not choose split dates for favorable performance. Split boundaries must be
   determined only from chronology, sample sufficiency, label horizon, purge,
   embargo and prior-use status.

6. Never reuse prior V22.080B Validation as independent Validation or Confirmation.
   It may only be used as historical development evidence and must be explicitly
   tagged as previously exposed.

7. Generation 2 Confirmation must consist only of data that was genuinely unread
   during model and threshold selection. Keep:
   confirmation_read_count = 0
   until a fully frozen champion passes all pre-Confirmation gates.

8. If insufficient genuinely independent data exist, do not manufacture a split.
   Produce:
   FAIL_INSUFFICIENT_UNEXPOSED_DATA_FOR_GENERATION2
   with the exact earliest future date/sample requirement.

9. Generation 2 research priorities:
   - PIT and leakage audit
   - SOXX directional labels, including 15m/30m/60m/120m/RTH close
   - VIX factors only when timestamped PIT availability is verified
   - SOXX multiscale trend and volatility regime
   - QQQ relative strength and SOXX/QQQ ratio
   - volume and liquidity proxies
   - calibrated LONG/SHORT/FLAT abstention
   - linear baselines before compact nonlinear models
   - real SOXL/SOXS execution mapping
   - randomized chronological as-of OOS windows
   - cost, delay, perturbation and concentration stress tests

10. Each iteration must make one main research change and record:
    hypothesis, expected mechanism, changed component, frozen windows, tests,
    metrics, accept/reject/inconclusive decision and next action.

11. Continue autonomously through informative failed experiments. A challenger
    failure is not a terminal project failure. Select the next non-duplicative,
    highest-information-value hypothesis.

12. Stop only when:
    - no robust edge remains after the bounded registered Generation 2 program;
    - insufficient independent data make honest validation impossible;
    - Confirmation is read once and accepted/rejected;
    - a genuine resource/execution boundary is reached.

13. Never:
    - modify canonical data
    - read Confirmation during development
    - weaken gates after seeing results
    - optimize directly for the best backtest
    - generate real orders
    - claim unexecuted tests or backtests
    - overwrite Generation 1 evidence
    - repeat no-op resume turns

14. Preserve:
    broker_action_allowed=False
    live_trading_allowed=False
    official_adoption_allowed=False
    research_only=True

Generation 2 outputs must be written under:

D:\us-tech-quant-results\fast3_autoresearch_generation2

Begin actual repository inspection, split-exposure audit, implementation, tests
and research now. Do not merely summarize this authorization.
