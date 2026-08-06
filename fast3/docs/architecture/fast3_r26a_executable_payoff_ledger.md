# FAST3 R26A executable payoff ledger

R26A has one immutable execution contract.  `entry_timestamp_et` is the
frozen R24/R25 PIT-safe label/entry anchor (R24 `prepare_cohort`), and the
horizon is exactly 24 hours.  For each candidate direction it maps family
direction to a long position in TQQQ, SQQQ, SOXL, or SOXS, then executes the
first legal canonical one-minute open strictly after the anchor and the first
legal canonical one-minute open at or after anchor plus 24 hours.  Each join
has a 15-minute maximum delay.

The builder reads only the six allowed candidate symbols and real canonical
ETF bars.  It performs vectorized as-of joins per action instrument and uses a
static range-query table for path MFE/MAE.  MFE/MAE, bar IDs, prices, exit
times, and payoff-validity fields are target diagnostics and are forbidden R26
features.  Invalid candidate/action rows remain in the ledger with a reason.

The sole frozen output is a compressed partitioned ledger with row, partition,
and global hashes.  It can be consumed only through R26's one-to-one
`candidate_id` payoff-loader boundary.
