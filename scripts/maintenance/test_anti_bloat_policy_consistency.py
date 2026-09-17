from __future__ import annotations

import importlib.util
import json
import os
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "configs" / "anti_bloat_policy.toml"
GUARD_PATH = ROOT / "fast3" / "scripts" / "audit" / "run_fast3_guard.py"


def _load_policy() -> dict:
    with POLICY_PATH.open("rb") as handle:
        return tomllib.load(handle)


def _load_guard():
    spec = importlib.util.spec_from_file_location("anti_bloat_guard_contract", GUARD_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _path_key(value: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(value)))


def test_policy_toml_and_required_hard_gates() -> None:
    policy = _load_policy()
    repository = policy["repository"]

    assert policy["policy_version"] == "1.0"
    assert (
        repository["preferred_bytes"]
        < repository["required_maximum_bytes"]
        < repository["warning_bytes"]
        < repository["hard_fail_bytes"]
    )
    assert policy["forbid_repo_local_venv"] is True
    assert policy["canonical_data_default_read_only"] is True
    assert policy["fail_closed_on_unknown"] is True


def test_canonical_runtime_and_external_roots_are_outside_repository() -> None:
    policy = _load_policy()
    repository_root = Path(policy["repository"]["root"])
    runtime = Path(policy["runtime"]["canonical_python"])
    assert _path_key(runtime) != _path_key(repository_root)
    assert _path_key(repository_root) not in {
        _path_key(parent) for parent in runtime.parents
    }

    storage_policy = policy["storage"]
    assert storage_policy["worktrees_root"] == r"D:\us-tech-quant-worktrees"
    assert storage_policy["worktrees_root"] != r"D:\us-tech-quant_worktrees"
    storage_config_path = ROOT / storage_policy["runtime_paths_config"]
    storage_paths = json.loads(storage_config_path.read_text(encoding="utf-8"))
    external_roots = [
        Path(storage_paths[key])
        for key in storage_policy["required_external_root_keys"]
    ]
    external_roots.append(Path(storage_policy["worktrees_root"]))

    external_keys = {_path_key(path) for path in external_roots}
    assert len(external_keys) == len(external_roots)
    assert _path_key(repository_root) not in external_keys
    for external_root in external_roots:
        assert _path_key(repository_root) not in {
            _path_key(parent) for parent in external_root.parents
        }


def test_existing_guard_consumes_policy_thresholds() -> None:
    policy = _load_policy()
    guard = _load_guard()
    guard_policy = guard.repository_policy()
    repository = policy["repository"]

    assert guard.POLICY_PATH == POLICY_PATH
    for key in (
        "preferred_bytes",
        "required_maximum_bytes",
        "warning_bytes",
        "hard_fail_bytes",
        "new_file_surface_threshold_bytes",
        "individual_file_allowlist_threshold_bytes",
    ):
        assert guard_policy[key] == repository[key]
    assert guard_policy["forbid_repo_local_venv"] is True
