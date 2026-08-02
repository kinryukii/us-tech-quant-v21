# FAST3-002 executable ETF label and portfolio contract

Status: frozen before any FAST3-002 model result. This is a research-only
execution contract, not an order specification.

## Time and entry

`timestamp_et` is the logical trading clock and `timestamp_utc` is retained for
audit. A signal is produced only after its decision bar completes; its entry
must have a strictly later timestamp. Source `broker_trade_date` is retained as
provided and is never inferred from UTC date, including overnight/midnight bars.
Sessions are recorded from the source; the primary contract has no session
exception and therefore follows actual 24-hour ETF bars.

Two frozen modes are reported without performance selection:

- `MODE_A_NEXT_BAR_OPEN` (primary): next valid completed tradable ETF bar open.
- `MODE_B_NEXT_BAR_VWAP_PROXY`: next bar `(high + low + close) / 3`; research
  proxy only, never represented as a tick-level fill.

The trade universe is a fixed map: SOXX UP/DOWN -> SOXL/SOXS and QQQ UP/DOWN ->
TQQQ/SQQQ. Underlying return times three, post-hoc ETF choice, and a signal-bar
close fill are forbidden.

## Exit and cost

The primary fixed contract is 1,440 minutes, target **net** return +3.0%, and
fixed -1.5% gross stop. The stop is a policy assumption, frozen before smoke
data and not presented as an optimum. The target gross price is computed so the
target remains +3.0% after the named cost scenario. On an OHLC bar touching both
target and stop, stop first is mandatory and `exit_ambiguity=true`.

Exit priority is stop/target, optional session force exit (disabled in primary),
timeout at next valid bar open, then data-end last completed-bar close proxy.
MFE/MAE are diagnostic only; they are never used as exit prices.

Costs are total round-trip entry plus exit spread/slippage/fee proxies, split
equally across sides: 10bps = 5bps entry + 5bps exit; 20bps = 10bps + 10bps.
Every row carries `gross_return`, `entry_cost`, `exit_cost`, `total_cost`, and
`net_return`.

## Portfolio and labels

Primary simulation is one account, initial NAV 100,000, max one full-notional
position, no adds, no averaging, no leverage above 1x, and no new trade until
the recorded exit timestamp. Duplicate event IDs are deterministically deduped;
same-direction active signals are `OVERLAP`, opposite signals are `CONFLICT`,
and unavailable capital is `CAPITAL`. Extension multi-position portfolios are
not implemented or used in FAST3-002.

Three non-interchangeable labels are emitted:

1. `opportunity_label`: 1% diagnostic future-path movement.
2. `direction_label`: ETF close direction at the fixed observation horizon.
3. `executable_trade_label`: post-cost result of this exact entry/exit contract.

Economic evaluation uses only the third label. Every result includes the event,
both clocks, symbols/direction, prices, exit reason, returns/costs, MFE/MAE,
holding time, hit flags, ambiguity, capital availability, and acceptance/reason.

Confirmation begins `2025-02-08T00:00:00-05:00`; any input at or beyond it
raises `CONFIRMATION_PATH_FORBIDDEN`. Broker, live, and adoption flags are false.
