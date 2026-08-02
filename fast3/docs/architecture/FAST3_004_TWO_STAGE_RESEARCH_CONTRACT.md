# FAST3-004 two-stage research contract

FAST3-004 is Development-only research architecture. It neither trains a final
model nor permits deployment, broker actions, orders, positions, or Confirmation
data access.

## Frozen dependencies

FAST3-002 remains authoritative: hash
`72186180b40e0c4b866d482fd35033597334c89ba3ef2bca33da5ad2d637eead`, next-bar
open, real SOXL/SOXS mapping, 24-hour maximum hold, +3% net target, -1.5% gross
stop, stop-first ambiguity rule, 10/20 bps round-trip surfaces, and one account
with one position. FAST3-004 does not replace executable labels or portfolio
acceptance; it only supplies fold-local scores to be evaluated through them.

## Stage A and Stage B

Stage A predicts `opportunity_target`, an executable-contract-derived research
target supplied by the input builder, with a fold-local score. The eligibility
rule is fixed before results: score >= 0.60. An ineligible event is `ABSTAIN`.

Stage B receives only events satisfying that fixed Stage A score rule, predicts
`direction_target` (UP=1, DOWN=0), and must subsequently be mapped to the real
SOXL/SOXS executable label path. A Stage A score never itself becomes a trade.

## Validation and controls

All input rows must have `feature_available_at_et <= decision_timestamp_et` and
must precede the Development boundary. The pipeline uses chronological outer and
inner `NestedPurgedWalkForward` folds with the frozen 1440-minute purge and
embargo. Candidate choice happens only inside outer training data. Every scaler
and estimator fit is written to an in-memory fit-call ledger; no final estimator
is saved.

The fixed bounded candidates for each stage are Dummy prior, logistic regression,
and compact histogram gradient boosting. No random K-fold, seed search, feature
selection, threshold optimization, or Confirmation access is allowed. Reports
must expose 10/20 bps results, single-account rejection counts, and concentration
by symbol/month/regime/side when a Development run is authorized.
