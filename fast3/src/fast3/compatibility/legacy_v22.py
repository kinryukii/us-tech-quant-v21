"""Explicit, deprecated read-only access to the preserved V22.080 modules."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
ALLOWED_LEGACY = {
    "v22_080a": REPO_ROOT / "scripts" / "v22" / "v22_080a_fast3_24h_one_percent_move_atlas_r1.py",
    "v22_080b": REPO_ROOT / "scripts" / "v22" / "v22_080b_fast3_one_percent_move_predictability_preflight_r1.py",
}


def legacy_hash(name: str) -> str:
    path = ALLOWED_LEGACY[name]
    if not path.is_file():
        raise FileNotFoundError(f"LEGACY_PATH_MISSING:{path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_allowed_legacy(name: str):
    """Load only a listed historical module; callers must not invoke its runner."""
    path = ALLOWED_LEGACY[name]
    legacy_hash(name)
    spec = importlib.util.spec_from_file_location(f"fast3_legacy_{name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"LEGACY_IMPORT_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
