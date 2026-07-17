# Storage migration R1

Run `scripts\maintenance\run_migrate_storage_layout_r1.ps1 -DryRun` first, then `-Execute`. Every transfer is copied to a temporary file, size- and SHA256-verified, atomically promoted, then its source is removed. Same-hash collisions are recorded as `duplicate_identical`; differing collisions receive a hash suffix. Resume uses the recorded external manifest. Canonical/PIT, ledgers, ranking snapshots, PDF/ZIP and formal backtests are never retention-deleted.
