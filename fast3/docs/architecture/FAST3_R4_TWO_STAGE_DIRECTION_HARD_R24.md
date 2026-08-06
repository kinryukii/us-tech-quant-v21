# FAST3 R4 Two-Stage Direction — Hard Storage R2.4

This is one fixed, historical, non-prospective architecture study: R3-style
three-class `hgb_leaf7` versus fixed `EVENT/NO_EVENT` then `UP_FIRST/DOWN_FIRST`
`hgb_leaf7`. It preserves the R3 decision `STOP_NO_SIGNIFICANT_GAIN_OVER_LEGACY`.

The study validates the external R3 freeze (including its 20 ordered features,
three fixed interactions, and post-audit evidence). `AMBIGUOUS` labels are
excluded. Labels are the only future-path information; feature timestamps later
than decisions are rejected. Training is expanding-only, has a 24-hour purge
and 24-hour embargo, and fits preprocessing and all weights on each training
fold only.

Before fitting, eight deterministic 60-day blocks are hashed and frozen: four
development blocks at three seeds, then four non-prospective internal-holdout
blocks at five seeds. Development failure stops the holdout. Resume is allowed
only for a complete checkpoint with a matching source, cohort, feature,
schedule, model, threshold, ranking, and leakage-control fingerprint.

The fixed signal is `max(P_UP_FIRST, P_DOWN_FIRST)`, opportunity threshold
`0.60`, top fraction `0.05`, 24-hour horizon, 3% target and 10/20 bps costs.
Economic diagnostics enforce the single-account/single-position mapping
QQQ→TQQQ/SQQQ and SOXX→SOXL/SOXS. The five preregistered nulls are reported;
seeds are never treated as independent blocks. A historical pass freezes one
outcome-free research-shadow model only. It cannot place broker, paper, or live
orders. All run outputs are caller-supplied external roots; repository output
and `.local_results` are rejected.
