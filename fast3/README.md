# FAST3

FAST3 is research-only investigation of point-in-time SOXX/QQQ signals and
real ETF execution mapping to SOXL/SOXS (and historical QQQ mappings). Its
independent root is `D:\us-tech-quant\fast3`; new work is numbered `FAST3-000`,
`FAST3-001`, and onward, not V22.

Current frozen historical evidence ends V22.080B with
`PREDICTABILITY_NOT_ECONOMICALLY_ACTIONABLE`: its Validation Top 5% lift was
1.36122855, while mean net return was -0.00196612 at 10bps and -0.00296612 at
20bps. Confirmation was not read. Later historical V22 experiments are kept
as immutable legacy evidence in the external result roots.

- Canonical input (read-only): `D:\us-tech-quant-data`.
- Research results (not moved): `D:\us-tech-quant-results\fast3_*`.
- Legacy source remains under `scripts/v22` where an exact historical path is
  needed; compatibility is isolated in `src/fast3/compatibility/legacy_v22.py`.
- Current audit reports are under `docs/reports/`; external formal results use
  `D:\us-tech-quant-results\fast3`.
- Tests: `python -m pytest fast3/tests/regression -q` plus the focused legacy
  tests named in the migration report.

No broker order, paper-broker order, live trading, official adoption, or order
generation is allowed. `LIVE_TRADING_ALLOWED=false`.
