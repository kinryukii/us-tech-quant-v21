# us-tech-quant-v21

Research-only US technology quant strategy system.

This repository contains a local, research-first quant workflow for US technology equities, ETFs, and DRAM-focused tactical planning.  
It is designed for daily research, factor experimentation, data-quality checks, forward validation, and strict no-broker-action governance.

> **Important:** This project is for research only. It does not provide financial advice, investment recommendations, broker execution, or official portfolio adoption.

---

## Current focus

The current active focus is:

- DRAM daily tactical planning chain
- Moomoo local-cache based data workflow
- Point-in-time / no-leakage validation
- Forward tracking and strategy comparison
- Compact output retention and repo size control
- Strict research-only execution gates

---

## Current daily entrypoint

The current recommended daily command is:

```powershell
cd D:\us-tech-quant
.\scripts\v21\run_v21_261_daily_chain_retention_enforcement_wiring_r1.ps1 -Execute
