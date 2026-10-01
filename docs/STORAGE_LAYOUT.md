# Storage layout

`D:\us-tech-quant` contains code, config, tests and small manifests only. Runtime roots are configured by `config/storage_paths.json` and may be overridden by `USTQ_REPO_ROOT`, `USTQ_DATA_ROOT`, `USTQ_CACHE_ROOT`, `USTQ_DAILY_ROOT`, `USTQ_BACKTEST_ROOT`, `USTQ_RESULTS_ROOT`, `USTQ_ENVS_ROOT`, and `USTQ_PYTHON_EXE`.

Data retains published, canonical and PIT inputs; cache holds acquisition and rebuildable files; daily holds V22 daily output; backtests holds research runs; results holds readable reports; envs holds Python environments. No configured storage root may nest another or the repo.


## First-write routing

Resolve `config/storage_paths.json` through the existing
`scripts/common/storage_paths.py` / `.ps1` for the actual checkout before
creating an artifact. Record its purpose, stable strategy/run/task identity and
final resolved destination in the existing run/task record. Inspect active
`USTQ_*` overrides: an override changes a path, not access or data authority.
Do not call a writable-root initializer against all roots merely to check paths;
canonical data remains read-only.

| Artifact | Destination and existing owner |
| --- | --- |
| Maintained source, tests, small configs/manifests and small synthetic fixtures | Appropriate source/test directory in the selected checkout; use REPOSITORY_LAYOUT.md |
| Canonical raw/published/PIT data | `data_root`; writes require explicit data-management authorization |
| Model/checkpoint, OOF/prediction, ledger, run-owned derived research inputs and diagnostic charts/logs | `backtest_root`, under the existing experiment's identity; reuse `scripts/storage/backtest_run_manager.py` for new managed runs |
| Final readable report, delivery figures and governance/audit evidence | `results_root`; governance reports use `_maintenance/<task_id>/` |
| Rebuildable acquisition cache, scratch files, pytest temp/cache and package cache | `cache_root`; task-owned transient files use a bounded task subdirectory; shared rebuildable derived inputs use `cache_root/derived` and the existing `derived` contract |
| Daily state, recovery records, daily logs and current-chain outputs | `daily_root`, under the existing chain's lifecycle |
| Python environments and installed dependencies | `envs_root`; use the canonical interpreter, no repository-local `.venv` |
| New registered Git worktrees | `D:\us-tech-quant-worktrees`, from Anti-Bloat machine configuration |

Use the existing experiment manager's run_config/input_manifest and stable run
identity; do not create a parallel manager, registry or source-copy tree.
Historical accepted runs retain their recorded locations and freeze/lineage
contracts. Different old migration plans do not define new canonical subfolder
layouts, and a migration never creates an algorithm version or fresh holdout.
Do not execute historical source from a custody/source folder when its relative
output paths would write artifacts beside source.

Before writing, resolve the full destination (including junction/symlink targets
and `..` segments) and verify containment in the approved root for that purpose.
Being outside the repository alone is insufficient. Reuse
`scripts/storage/storage_r2a.py::assert_write_path` where applicable to
backtest/daily/derived output. The common `assert_safe_output_path` only rejects
repository-local writes; it does not establish purpose-specific containment.
Do not claim a Python helper or PowerShell resolver intercepts every possible
write. Missing destinations or access stop that write; continue independent work
without falling back to the C: chat workspace, repository, Desktop or an
unapproved root. Creating research products locally and migrating later is not
the default workflow.

Route logs with their owning run/chain/task. Use the existing task/run record and
one final report, not a permanent audit directory for each debug/retry. Cleanup
is limited to this task's proven transient, rebuildable files with no active
consumer or evidence/retention obligation; preserve frozen, failed-run and
unknown material. Never delete another worker's scratch files or inaccessible
residue. Governance updates do not authorize moving old data or rewriting frozen
paths/bytes. See [Anti-Bloat Policy](governance/ANTI_BLOAT_POLICY.md) for budgets,
retention and deletion gates.

The September 2026 SEC event originals, financial notes ZIPs and N-PORT ZIPs are staged under `D:\us-tech-quant-cold-archive\official_research\factor_sources_20260914` for later transfer to an external disk. Their former cache directories are NTFS junctions, so ordinary readers still use the recorded paths. The archive's `ARCHIVE_MANIFEST.json` lists the three relative directories, source counts and checksums, and the published tables kept hot under `D:\us-tech-quant-data`. The per-source official URLs, acquisition times, hashes, coverage and limitations are in `D:\us-tech-quant-results\US_TECH_QUANT_RESEARCH_REGISTRY\retired_artifacts.json`. Moving files to a different directory on D: does not increase free space. After copying and verifying the archive on an external disk, the D: archive root can become one junction to the external copy; the three cache junctions then keep working without changing their targets. The raw-source validators accept the resolved cold archive root; override it with `USTQ_OFFICIAL_RAW_ARCHIVE_ROOT` if the D: root junction is not retained.

Git worktrees use `D:\us-tech-quant-worktrees`, as configured by `configs/anti_bloat_policy.toml`. The old underscore spelling (`D:\us-tech-quant_worktrees`) was retired after its registered Harness worktrees were removed. `D:\us-tech-quant-external-data` remains a separate protected source for external inputs. These directories have different roles and should not be merged by moving files between them; see [Anti-Bloat Policy](governance/ANTI_BLOAT_POLICY.md) for retention and deletion checks.

Developer data queries, recovery, validation and stock onboarding: [DATA_LAYER.md](DATA_LAYER.md).
