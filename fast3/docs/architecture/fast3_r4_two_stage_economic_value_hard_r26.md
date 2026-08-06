# FAST3 R26: frozen asymmetric direction plus economic-value gate

R26 adds exactly one component to the frozen R25 asymmetric UP/DOWN direction
layer: a `Ridge(alpha=10.0, solver="lsqr", tol=1e-6)` economic-value head.
It must consume only R25 PIT-safe features and strictly chronological
out-of-fold direction probabilities.  R25 confidence (`0.6`) and margin
(`0.1`) are loaded from the hash-validated frozen candidate, never reselected.

The candidate thresholds are exactly `0.0000`, `0.0005`, `0.0010`, and
`0.0020` predicted net 10bps return.  Future outcome fields are excluded.

The frozen supplied R3 cohort lacks row-level executable payoff fields.  In
particular it does not contain `gross_return`, `target_hit`, or an actual exit
timestamp.  The R22/R25 economics fallback therefore fills a missing gross
return with zero, which is not an authoritative realised economic target.
R26 is consequently required to stop with
`STOP_R26_AUTHORITATIVE_ECONOMIC_TARGET_UNAVAILABLE`; it must not train a
proxy, open D3/D4 or H1-H4, or retire development blocks.
