# Storage layout

`D:\us-tech-quant` contains code, config, tests and small manifests only. Runtime roots are configured by `config/storage_paths.json` and may be overridden by `USTQ_REPO_ROOT`, `USTQ_DATA_ROOT`, `USTQ_CACHE_ROOT`, `USTQ_DAILY_ROOT`, `USTQ_BACKTEST_ROOT`, `USTQ_RESULTS_ROOT`, `USTQ_ENVS_ROOT`, and `USTQ_PYTHON_EXE`.

Data retains raw/qfq/canonical/PIT; cache holds rebuildable files; daily holds V22 daily output; backtests holds research runs; results holds readable reports; envs holds Python environments. No root may nest another or the repo.
