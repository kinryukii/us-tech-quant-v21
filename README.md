# us-tech-quant-v21

Research-only US technology quant strategy system.

## Current focus

V21 daily-frequency DRAM tactical planning chain.

## Latest DRAM daily chain

- V21.174_R1C: Auto DRAM daily OHLCV fetch/cache
- V21.176: Daily DRAM premarket trade plan
- V21.177: Daily DRAM plan ledger and staleness gate
- V21.177_R1A: Staleness semantic repair
- V21.178: Daily DRAM plan chain orchestrator
- V21.178_R1A: Execution-mode daily DRAM chain

## Policy

This repository is research-only.

- No broker action
- No official adoption without explicit approval
- No protected output mutation
- DRAM remains a manual/watchlist tactical anchor
- Daily-frequency planning only
- Intraday stage is diagnostic-only

## Validation example

```powershell
python -m pytest scripts\v21\test_v21_178_r1a_daily_dram_chain_execution_mode.py -q
powershell -ExecutionPolicy Bypass -File scripts\v21\run_v21_178_r1a_daily_dram_chain_execution_mode.ps1
```
