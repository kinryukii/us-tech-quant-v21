# Daily storage maintenance

Run the daily entrypoint from the repo root: `./scripts/v22/run_v22_044_daily_single_entrypoint_freeze_and_guard_r1.ps1 -Execute`. Use `run_storage_maintenance_r1.ps1 -AllSafe` for audit, verified migration, cache-only retention DryRun and size reporting. Use `run_enforce_retention_policy_r1.ps1 -Execute` only for explicitly stale transient cache files. Reports are under `D:\us-tech-quant-results\storage_migration_r1`.
