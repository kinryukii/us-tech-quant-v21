# FAST3-002 contract implementation report

FAST3-002 is a contract correctness stage, not an alpha result. The frozen
configuration hash is `72186180b40e0c4b866d482fd35033597334c89ba3ef2bca33da5ad2d637eead`.
It implements real ETF mappings, strict next-timestamp entry, next-bar-open as
the primary fill, a declared HLC3 proxy comparison, +3% net target, -1.5% gross
policy stop, 24-hour maximum hold, conservative stop-first same-bar ambiguity,
and explicit 10/20bps round-trip costs.

The primary portfolio accepts one position only and emits raw/deduped/accepted,
overlap/capital/conflict counters. It uses a stable event ID, rejects new
signals during an active 24-hour trade, and returns capital after exit. The
development-only nested splitter uses 1,440-minute purge plus 1,440-minute
embargo and train-fold-only scaler fitting. Confirmation timestamps fail closed.

Actual verification: all 28 new unit tests passed in 1.12 seconds. They cover
decision/entry timing, clocks and trade dates, ETF mapping/no 3x arithmetic,
costs, all exits, ambiguity, dedup/overlap/capital handling, purge/embargo,
train-only scaling, confirmation guard, label separation, and portfolio versus
overlap aggregation. The real-data smoke command completed with exit 0 and did
not train or select a model. The external canonical input was read only; no
data, results, broker order, or live-trading capability was created.

Unresolved: the fixed -1.5% stop is a transparent policy assumption, not an
optimized value; session taxonomy quality and multi-position sensitivity remain
future contract work. FAST3-003 is not started by this stage.
