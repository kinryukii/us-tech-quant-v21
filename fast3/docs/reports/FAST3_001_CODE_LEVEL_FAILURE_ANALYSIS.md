# FAST3-001 code-level failure analysis

## Evidence and scope

This audit read V22.080A/B source, their focused tests, the stage summaries and
the V22.080B concentration/year CSVs. It did not rerun the multi-year research
or read Confirmation. The frozen artifacts independently confirm: 22,887
V22.080A events; real ETF mapping success 21,771/21,824 (99.7571%); 2%/3% ETF
hit rates 76.7075%/20.3574%; and V22.080B Validation Top-5 lift 1.36122855.
The real-ETF post-cost means are -0.0019661166 at 10bps and -0.0029661166 at
20bps, with zero positive annual groups and Confirmation reads = 0.

## Confirmed findings

| Severity | Type | Evidence | Actual impact | Minimal reproduction / repair |
|---|---|---|---|---|
| CRITICAL | research-design mismatch | `v22_080a...py:44-66` creates `EX_POST_MOVE_START` events from realised high/low paths. `v22_080b...py:119-124` labels first +/-1% underlying passage; `:143-155` instead scores a 3% real-ETF target or 24h timeout. | A label hit is not the economic event scored. The synthetic regression `test_one_percent_underlying_label_is_not_the_three_percent_etf_economic_target` proves a 1% opportunity can produce a 0% ETF gross and -10bps net result. Historical results would change if label/exit were unified. | FAST3-002 must freeze a single executable label: next tradable ETF entry, exits, costs, stop/timeout, and action before fitting. |
| CRITICAL | execution/portfolio contract gap | `v22_080b...py:139` selects 5% of every 5-minute grid; `:149-156` evaluates each row independently. No position/overlap/portfolio allocation state exists. | 22,609 selected Validation rows are conditional independent outcomes, not a feasible 24h holding portfolio. The synthetic regression proves two overlapping selections yield two outcomes. This does not invalidate the negative mean, but it prevents treating it as a deployable portfolio P&L. Historical portfolio conclusions would change after an overlap policy. | Define non-overlap/netting/capital allocation and evaluate equity-curve compounding with identical costs. |
| HIGH | selection validation weakness | `v22_080b...py:127-136` fits each candidate on all Development rows and scores the same rows to choose it. No nested split, purge, or embargo is applied inside model selection. | The observed negative Validation result remains valid, but development ranking is optimistically selected from highly overlapping 24h labels; it cannot establish robust generalization. A redesign changes historic candidate-selection results. | Nested chronological fitting with grouping by overlapping move family and explicit purge/embargo. |
| HIGH | objective mismatch | `v22_080b...py:134,141,190` optimizes/rules on target-first lift, AUC and Brier before only later rejecting economic means. | Actual validation demonstrates the mismatch: lift 1.3612 coexists with negative 10/20bps net means. No code bug is required for this failure; the objective is insufficient. | Select only on Development net expectancy, drawdown, turnover, coverage, concentration and cost/delay stress. |
| MEDIUM | missing calibration/threshold audit | `v22_080b...py:139` hard-codes Top 5%; `:200` writes calibration as `not_computed`. | Ranking may be useful without a profitable executable threshold; calibration and monotonic return-by-coverage were not established. No evidence supports retuning Validation. | Use Development-only calibration and pre-frozen coverage grid (0.5/1/2/5/10%). |
| MEDIUM | session taxonomy loss | `v22_080b...py:57` maps unrecognized sessions to code 4; actual `v22_080b_concentration.csv` has 8,920/22,609 rows with code 4 and only codes 1/4. | Required RTH/after-hours/overnight attribution cannot be made reliably from this output. The economic loss is not thereby explained. | Normalize audited source session vocabulary and fail closed or report unknown separately. |

Actual V22.080B directional/execution attribution is adverse in the main
semiconductor mappings: SOXL premarket/unknown means -0.002896/-0.000810 and
SOXS -0.003122/-0.004146. TQQQ is positive in its two reported cells but is a
different underlying mapping and does not rescue the aggregate. Year means are
negative in 2023, 2024, and 2025. The three fixed-seed 120-day windows are also
negative at 10bps: -0.00289719, -0.00113145, -0.00052811.

## Confirmed controls and excluded hypotheses

The code uses the next valid bar open (`:112`, `:119`), real ETF OHLC rather
than fixed 3x arithmetic (`:143-155`), at-or-after timestamp matching with a
one-minute tolerance (`:150-153`), and subtracts 10/20bps exactly once as
0.001/0.002 (`:154-155`). It rejects same-index underlying dual-barrier labels
(`:120`). Static inspection found no `shift(-`, `rolling(center=True)`, `bfill`,
or `merge_asof` in V22.080A/B. Confirmation is fail-closed (`:40-58`), and the
actual summary records zero reads. These controls do not solve the confirmed
label/economic mismatch.

The runner has no stop-loss path, so a same-bar stop/target ordering rule is
not implemented or exercised; this is a missing execution-contract element,
not a confirmed favourable ordering bug. No VIX, gap, trend/range, weekday,
quarter/month, holding-horizon, LONG/SHORT, or independently labelled
opportunity-direction report is emitted by V22.080B, so those explanations
remain **unresolved**, not disproven.

## Multiple testing / confirmation

V22.080B declared three model classes and chose by in-sample Development lift;
it recorded only three random Validation windows. Subsequent legacy V22.081–086
experiments constitute historical selection exposure, but this audit did not
infer a numerical overfitting probability from them. Confirmation remained
unread for V22.080B. There is no evidence here that Confirmation was used to
tune this stage.
