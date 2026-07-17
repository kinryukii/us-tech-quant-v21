"""Single, validated storage-root resolver for USTQ runtime artifacts."""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

DEFAULTS = {"repo_root": r"D:\us-tech-quant", "data_root": r"D:\us-tech-quant-data", "cache_root": r"D:\us-tech-quant-cache", "daily_root": r"D:\us-tech-quant-daily", "backtest_root": r"D:\us-tech-quant-backtests", "results_root": r"D:\us-tech-quant-results", "envs_root": r"D:\us-tech-quant-envs"}
ENV = {key: "USTQ_" + key.upper() for key in DEFAULTS}

@dataclass(frozen=True)
class StoragePaths:
    repo_root: Path; data_root: Path; cache_root: Path; daily_root: Path
    backtest_root: Path; results_root: Path; envs_root: Path
    @property
    def python_exe(self) -> Path:
        value = os.environ.get("USTQ_PYTHON_EXE")
        if value: return Path(value).expanduser()
        preferred = self.envs_root / "daily-python312/Scripts/python.exe"
        return preferred if preferred.exists() else self.envs_root / ".venv/Scripts/python.exe"

def resolve(repo_root: Path | None = None, **overrides: str | Path | None) -> StoragePaths:
    repo = Path(repo_root or overrides.get("repo_root") or os.environ.get(ENV["repo_root"]) or DEFAULTS["repo_root"]).resolve()
    cfg_path = repo / "config/storage_paths.json"; cfg = {}
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    values = {}
    for key, default in DEFAULTS.items():
        value = overrides.get(key) or os.environ.get(ENV[key]) or cfg.get(key) or default
        values[key] = Path(value).expanduser().resolve()
    paths = StoragePaths(**values); validate(paths); return paths

def validate(paths: StoragePaths, require_writable: bool = False) -> None:
    roots = [paths.data_root, paths.cache_root, paths.daily_root, paths.backtest_root, paths.results_root, paths.envs_root]
    if len(set(roots)) != len(roots): raise ValueError("storage roots must be distinct")
    for root in roots:
        if root == paths.repo_root or paths.repo_root in root.parents or root in paths.repo_root.parents:
            raise ValueError(f"storage root must not nest repo_root: {root}")
    for root in roots:
        for other in roots:
            if root != other and root in other.parents: raise ValueError(f"storage roots must not nest: {root} / {other}")
    if require_writable:
        for root in roots:
            root.mkdir(parents=True, exist_ok=True)
            if not os.access(root, os.W_OK): raise PermissionError(root)
            if shutil.disk_usage(root).free < 1024 * 1024 * 1024: raise OSError(f"less than 1 GiB free at {root}")

def artifact_root(kind: str, paths: StoragePaths | None = None) -> Path:
    paths = paths or resolve()
    return {"data": paths.data_root, "cache": paths.cache_root, "daily": paths.daily_root, "backtest": paths.backtest_root, "results": paths.results_root}[kind]

def _paths() -> StoragePaths: return resolve()
def get_repo_root() -> Path: return _paths().repo_root
def get_data_root() -> Path: return _paths().data_root
def get_cache_root() -> Path: return _paths().cache_root
def get_daily_root() -> Path: return _paths().daily_root
def get_backtest_root() -> Path: return _paths().backtest_root
def get_results_root() -> Path: return _paths().results_root
def get_envs_root() -> Path: return _paths().envs_root
def get_python_executable() -> Path:
    p=_paths(); candidate=p.python_exe.resolve(strict=False)
    if p.repo_root in candidate.parents: raise ValueError("Python executable must be outside repo")
    return candidate
def _external(kind: str, *parts: str) -> Path:
    p=(artifact_root(kind,_paths()).joinpath(*parts)).resolve(strict=False); assert_path_outside_repo(p); return p
def resolve_data_path(*parts: str) -> Path: return _external('data',*parts)
def resolve_cache_path(*parts: str) -> Path: return _external('cache',*parts)
def resolve_daily_path(*parts: str) -> Path: return _external('daily',*parts)
def resolve_backtest_path(*parts: str) -> Path: return _external('backtest',*parts)
def resolve_results_path(*parts: str) -> Path: return _external('results',*parts)
def assert_path_outside_repo(path: Path) -> None:
    if _paths().repo_root in Path(path).resolve(strict=False).parents or Path(path).resolve(strict=False)==_paths().repo_root: raise ValueError(f"repo output rejected: {path}")
def assert_safe_output_path(path: Path) -> None: assert_path_outside_repo(path)
def ensure_external_roots() -> None: validate(_paths(),require_writable=True)
def describe_storage_configuration() -> dict[str,str]:
    p=_paths(); return {k:str(getattr(p,k)) for k in DEFAULTS}|{'python_executable':str(get_python_executable())}
