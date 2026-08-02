# FAST3-002 legacy versus executable label gap analysis

V22.080B labels whether a real underlying moves +/-1% first within 24 hours,
then separately evaluates a real ETF 3% target or timeout. FAST3-002 instead
creates a label from the same actual ETF entry, target/stop/timeout, cost, and
portfolio contract that will be evaluated. This removes the confirmed semantic
gap; it does not claim the new contract is profitable.

The read-only real-data smoke used 12 deterministic SOXX-UP signals from the
January 2024 SOXX/SOXL/SOXS partitions. Its legacy-proxy versus executable-label
disagreement was 0.0. That limited, directional sample is not representative
and does not overturn FAST3-001: the synthetic regression proves a 1% path can
miss the distinct ETF 3% economic target and be negative after cost.

The smoke also demonstrates the separate portfolio problem: 12 raw/deduped
signals became 6 accepted trades and 6 overlap rejections under the frozen
single-position contract. It recorded no capital or conflict rejections. Its
ending NAV was 90,775.90567653211 from an initial 100,000; this is not a
strategy conclusion because the signals are fixed smoke inputs and no model or
threshold was fitted or selected.
