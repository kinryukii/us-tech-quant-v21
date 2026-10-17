"""Single, validated storage-root resolver for USTQ runtime artifacts."""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

DEFAULTS = {"repo_root": r"D:\us-tech-quant", "data_root": r"D:\us-tech-quant-data", "cache_root": r"D:\us-tech-quant-cache", "daily_root": r"D:\us-tech-quant-daily", "backtest_root": r"D:\us-tech-quant-backtests", "results_root": r"D:\us-tech-quant-results", "envs_root": r"D:\us-tech-quant-envs"}
ENV = {key: "USTQ_" + key.upper() for key in DEFAULTS}
OUTPUT_KINDS = ("cache", "daily", "backtest", "results")

@dataclass(frozen=True)
class StoragePaths:
    repo_root: Path; data_root: Path; cache_root: Path; daily_root: Path
    backtest_root: Path; results_root: Path; envs_root: Path
    @property
    def python_exe(self) -> Path:
        value = os.environ.get("USTQ_PYTHON_EXE")
        if value: return Path(value).expanduser()
        return self.envs_root / "us-tech-quant-main/Scripts/python.exe"

def resolve(repo_root: Path | None = None, **overrides: str | Path | None) -> StoragePaths:
    repo = Path(repo_root or overrides.get("repo_root") or os.environ.get(ENV["repo_root"]) or DEFAULTS["repo_root"]).resolve()
    cfg_path = repo / "config/storage_paths.json"; cfg = {}
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    values = {}
    for key, default in DEFAULTS.items():
        value = overrides.get(key) or os.environ.get(ENV[key]) or cfg.get(key) or default
        values[key] = Path(value).expanduser().resolve()
    # The explicit checkout selects both the config and the returned repository.
    # A copied config (or inherited environment) may still name the old checkout.
    if repo_root is not None:
        values["repo_root"] = repo
    paths = StoragePaths(**values); validate(paths); return paths

def validate(paths: StoragePaths, require_writable: bool = False) -> None:
    # Callers may construct StoragePaths directly, so compare physical targets
    # here as well as in resolve(). This catches symlink/junction root aliases.
    repo = Path(paths.repo_root).expanduser().resolve()
    roots = [Path(getattr(paths, key)).expanduser().resolve() for key in DEFAULTS if key != "repo_root"]
    if len(set(roots)) != len(roots): raise ValueError("storage roots must be distinct")
    for root in roots:
        if root.is_relative_to(repo) or repo.is_relative_to(root):
            raise ValueError(f"storage root must not nest repo_root: {root}")
    for root in roots:
        for other in roots:
            if root != other and other.is_relative_to(root):
                raise ValueError(f"storage roots must not nest: {root} / {other}")
    if require_writable:
        # Data is read-only by default; installed environments are dependencies,
        # not writable artifact roots. Initialization does not authorize either.
        for kind in OUTPUT_KINDS:
            root = Path(getattr(paths, kind + "_root")).expanduser().resolve()
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
def official_raw_archive_root() -> Path:
    """Physical root for official originals staged for external storage."""
    return Path(os.environ.get("USTQ_OFFICIAL_RAW_ARCHIVE_ROOT", r"D:\us-tech-quant-cold-archive")).expanduser().resolve()

def is_authorized_official_raw_path(path: Path, cache_root: Path) -> bool:
    resolved = Path(path).resolve()
    return (resolved.is_relative_to(Path(cache_root).resolve())
            or resolved.is_relative_to(official_raw_archive_root()))
def get_daily_root() -> Path: return _paths().daily_root
def get_backtest_root() -> Path: return _paths().backtest_root
def get_results_root() -> Path: return _paths().results_root
def get_envs_root() -> Path: return _paths().envs_root
def get_python_executable() -> Path:
    p=_paths(); candidate=p.python_exe.resolve(strict=False)
    if candidate.is_relative_to(p.repo_root): raise ValueError("Python executable must be outside repo")
    return candidate
def _external(kind: str, *parts: str) -> Path:
    root = artifact_root(kind, _paths()).resolve()
    path = root.joinpath(*parts).resolve(strict=False)
    if not path.is_relative_to(root):
        raise ValueError(f"{kind} path must stay within its configured root: {path}")
    return path

def resolve_data_path(*parts: str) -> Path: return _external('data',*parts)
def resolve_cache_path(*parts: str) -> Path: return _external('cache',*parts)
def resolve_daily_path(*parts: str) -> Path: return _external('daily',*parts)
def resolve_backtest_path(*parts: str) -> Path: return _external('backtest',*parts)
def resolve_results_path(*parts: str) -> Path: return _external('results',*parts)
def assert_path_outside_repo(path: Path) -> None:
    if _paths().repo_root in Path(path).resolve(strict=False).parents or Path(path).resolve(strict=False)==_paths().repo_root: raise ValueError(f"repo output rejected: {path}")
def assert_safe_output_path(path: Path, *, kind: str | None = None, paths: StoragePaths | None = None) -> None:
    """Check physical output containment; kind pins the artifact's declared purpose.

    This is a caller guard, not a universal write interceptor or authorization
    for protected research evidence. Canonical data is never a default output.
    """
    paths = paths or _paths()
    validate(paths)
    resolved = Path(path).expanduser().resolve(strict=False)
    repo = Path(paths.repo_root).resolve()
    if resolved.is_relative_to(repo): raise ValueError(f"repo output rejected: {path}")
    if resolved.is_relative_to(Path(paths.data_root).resolve()):
        raise ValueError(f"canonical data output rejected: {path}")
    if kind is not None and kind not in OUTPUT_KINDS:
        raise ValueError(f"unsupported output kind: {kind}")
    kinds = (kind,) if kind is not None else OUTPUT_KINDS
    if not any(resolved.is_relative_to(artifact_root(item, paths).resolve()) for item in kinds):
        raise ValueError(f"output must stay within its configured {kind or 'artifact'} root: {path}")
def ensure_external_roots() -> None: validate(_paths(),require_writable=True)
def describe_storage_configuration() -> dict[str,str]:
    p=_paths(); return {k:str(getattr(p,k)) for k in DEFAULTS}|{'python_executable':str(get_python_executable())}
