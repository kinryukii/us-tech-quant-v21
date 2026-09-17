# OPTIONS_EXPRESSION_PILOT_R1 — task design and trial draft

Frozen before this task's generated economic outputs: 2026-09-13. This document
fixes one exploratory specification, not an acceptance receipt. Human task
authorizes pre-2026 research development, never production or new subscriptions.
Base: preserve/pre-final-quarantine-dirty-20260905,
bd59a3b97b96a70bcf73a7dbcd0fff74b288ed51. Existing dirty files remain owned elsewhere.

## Reuse and authority

| Requirement | Existing implementation | Difference and disposition |
|---|---|---|
| Storage | scripts/common/storage_paths.py resolve | ACTIVE; directly reuse external roots |
| ATM/expiry | fast3/src/fast3/options/moomoo_option_shadow_r1.py choose_expiry, choose_atm_contract | Pure source; task-reviewed helper reuse, stricter R1 admission outside helper; no FAST3 strategy activation |
| Cash events | scripts/v22/r9a_trade_ledger.py TradeLedgerEvent, validate_ledger | Existing schema; adoption UNKNOWN; map option units to underlying-equivalent shares, add fees/cash invariants; no account engine |
| Costs | fast3/src/fast3/backtest/cost_model.py RoundTripCost | ETF return bps insufficient for option minimum fees; small order fee function required, explicit scenario only |
| Model mechanism example | scripts/v22/v22_037_r1_option_synthetic_iv_solver_research_only.py black_scholes_price | Reuse pure European formula only; no discover_input/run, no historical pricing or American Delta use |
| Calendar | scripts/v22/forward_shadow/trading_calendar.py | ACTIVE forward adapter uses regular close; use installed exchange_calendars XNYS schedule directly for historical/DST/early close; no new calendar rules |
| Opportunity provenance | scripts/research/a2/data/a2_authoritative_raw_top40_membership_checkpoint_r1.py | Existing checkpoint schema, no refit/import; source contains embedded historical metrics, reading stopped; timestamp/accepted isolated input binding not established |
| Registry/trials | prospective_research_lifecycle.py RESEARCH_SPEC_FIELDS/TRIAL_FIELDS; research_registry.py | Reuse field meanings; readers load entire snapshots/old ledger; no proven content-safe registration entry. Task draft only, no forged receipt or registry mutation |
| Old options | FAST3 option shadow/acquisition; FAST5 option pilot/data | UNKNOWN adoption, current feeds or model ranking, not same estimator. No revival, bulk discovery, new provider or model |
| Entry/exit/OOF | A2 autonomous buy/sell source and existing checkpoint | Other work preserved; OOF profiles unavailable through verified safe binding. Labels never represented as forecasts |

## One fixed contract

Raw A2 frozen ex-ante Top20 only; pre-2026 observations, planned exits and label
maturity. No universe change, fit, tuning, winner search, NAV or compounded cohorts.
R1 holding period is entry session +5 sessions (elapsed sessions, not inclusive
count). +20 stock sessions are separately labelled diagnostics. Fixed 45 calendar
day target / [30,60] admission, standard USD physically settled American equity
Call, multiplier 100, 100 identical underlying shares deliverable, unadjusted.
Select expiry then ATM using decision spot; ties ascending expiry/strike/id.
Require two full trading sessions after planned exit before last trade cutoff.

No historical timing metadata currently proves a real profile. Engineering uses
the synchronous profile: 09:45 America/New_York decision; intent +1 second;
first valid side BBO within next 60 seconds; +5 session 09:45 exit with +1 second
latency. Quotes at decision can select but cannot fill. Snapshot profile is not
implemented or silently substituted. A real source must prove this profile before
replay. Max event age at availability 2 seconds, underlying sync 1 second,
availability to execution event no greater than 2 seconds; ingested_at is audit
time (can be later). Units are contracts for options, shares for stocks. Require
whole order displayed size, reject otherwise; no daily-volume liquidity proxy.

All sizing is frozen at decision: analytical capital USD 10,000 per independent
opportunity (not claimed user balance), one integer Call if debit plus fee fits;
stock shares floor(capital/(decision ask plus per-share fee)), fee feasibility
checked; no margin. Common-funded Delta comparison holds 100*decision_delta
fractional shares, ANALYTICAL_ONLY; unavailable Delta => NOT_IDENTIFIABLE.
Historical provider Delta needs predecision timestamp/provenance/unit/style
validation; no pricing engine. Call and all stock arms retain unused cash at zero
interest. Fill debit above capital rejects without resizing or replenishment.
Fee scenario, not historical/account terms: option max(1 USD, .65 per contract)
per order; stock max(1 USD, .005 per share). Spread embedded via ask/bid;
additional fixed adverse sensitivity .10 USD/option unit, .01 USD/share, never
treated as a candidate. Report break-even incremental costs. Entry failure is
CASH (no open). Exit failure is HOLD/UNRESOLVED with cash and quantity retained;
corporate-action/expiry/settlement ambiguity stays unresolved, no stale sell or
invented zero. Mechanical expiration payoff helper is arithmetic-only.

All opportunities retained; labels separate from decision structures. Stock path
labels require +5/+20 complete chronological same-clock marks and maturity;
return, quantiles, positive fraction, mark MFE/MAE, log-return realized volatility,
first positive mark session. They do not infer intraday extrema/trigger order.
No OOF conditioning without authentic provenance. No forward exit availability
filter in contract selection. Underlying price/identity/action gaps stop labels.

Primary estimator: per-opportunity Call net wealth minus equal-funded stock net
wealth, divided by shared initial capital; Delta-funded arm separate. Date-level
paired mean then equal-date mean; calendar session axis retains missing dates.
Moving blocks 20 sessions, 2000 replicates, seed 1729; exploratory percentile
95% interval only when >=40 sessions with observed pairs. Report rows/dates/UIDs,
coverage, unresolved and exclusions. No N_eff invention. Incomplete resolution
blocks economic verdict even if resolved pairs look attractive; no delta => no
claim of removing direction leverage. Shape/time/IV not separable from endpoint
quotes alone. Scenarios never answer real historical profitability.

Engineering scenario fixed before its first calculation: hypothetical S=100 to
103, K=100, IV=.4 to .1, time=45 to 38 calendar days, zero rate/dividend; use the
existing European formula. Ordered spot/time/IV changes are path-order dependent
illustration, not empirical attribution or validated American calibration.

## Boundaries, execution and stopping

Only approved isolated bytes may enter real readers. A filename, caller assertion,
cutoff filter or hash is not authority. Currently approved real input bindings:
none. CLI local branch must emit NOT_RUN with missing provenance/read boundary;
explicit unbound input must fail before open. Discovery may inspect bounded known
directory names/stat metadata; no recursive results-root census or mixed parquet
footer/data reads. Source constants unexpectedly exposed in Top40 code are
recorded as source-embedded historical performance, period not independently
verified; never used to choose this contract. A2 historical later exposure remains.
Actual global economic read counts UNKNOWN; no claim of restored holdout.

Provider budget frozen: zero economic requests until a history-only endpoint,
expired identity coverage and eligible opportunity binding are demonstrated;
then this R1 requires separate recorded bounded acquisition list, not defaults.
Moomoo official get-option-chain documents no expired chain support; market
snapshot and stock quote are current surfaces. No eligible request follows from
current account credentials; account capability remains UNKNOWN without safe probe.
No global config/permission modifications, SDK broker calls or account reads.

Trial draft: hypothesis_trials=1, feature_trials=0, model_trials=0,
hyperparameter_trials=0, portfolio_threshold_trials=0; historical holdout_peeks
UNKNOWN (not converted to integer zero). Training/validation/test roles: no fit,
all lawful real history exploratory, synthetic engineering only. No confirmation.
No registry receipt issued. Real execution blocked independently by input authority.
Negative closes template; incomplete data => NOT_IDENTIFIABLE; positive limited
evidence => exploratory only. Finish R1 after implementation/CLI/test/review, no R2.

Outputs use one results_root/OPTIONS_EXPRESSION_PILOT_R1 directory, one manifest,
separate evidence-domain CSVs, logs and final report. Synthetic rerun deterministic
and content-bound; no raw writes. Tests use authorized external cache/temp only.

## R1 input continuation (same research identity)

The continuation run configuration is fixed at external
`OPTIONS_EXPRESSION_PILOT_R1/continuation/run/run_config.json` before opening the
new signal/price payloads. It adds a separately labelled STOCK_DAILY_PATH using
the original frozen close-signal / next-session-open convention. The Call clock,
fees, template and estimand remain unchanged. No new registration receipt exists.
The accepted baseline contract pins its 46-entry artifact hash list; only the
necessary physically pre-2026 products are admitted. Source proof: original
run_rebuild.py build_active_ledger/build_prices_and_u_t and signals->reconstruct_path
write only pre-cutoff outputs. No mixed raw or rehab reconstruction is executed.
The two known isolated PIT price panels are missing. The frozen A2 position ledger
can supply a limited observation projection: nonstale same-date opening marks,
not original holdings/PnL replay. This coverage depends on future original holdings;
complete paths are conditional diagnostics. All Top20 rows and failed labels stay.
Inherited historical eligibility/CUSIP and checkpoint UID must agree; absent or
ambiguous historical identity is rejected without rebuilding the UID master.
The adapter reuses storage, XNYS sessions, path arithmetic and frozen date bootstrap.
It adds one bound reader and strict real-stock CLI mode, not a second engine.
All prior exposure remains, including renewed accidental source constant contact
and pre-2026 headline metrics encountered in the accepted baseline manifest.
