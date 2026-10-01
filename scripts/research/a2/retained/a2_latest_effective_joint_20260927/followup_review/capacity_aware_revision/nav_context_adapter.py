"""Versioned, fail-closed NAV context for the frozen joint account engine.

The original engine remains byte-for-byte unchanged.  The single source edit
adds an observable signal-close NAV to the policy callback's frame.attrs;
order execution, fees, accounting, and recorded outputs are untouched.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine.py"
ENGINE_SHA256 = "c3bf057173960920de8faa15d6aa6e2522b1c8e9eae6bb3b4e96c665a37b33ff"
BEFORE = 'valuation_status=status, unit="price_index_units")'
AFTER = ('valuation_status=status, unit="price_index_units",\n'
         '                                   signal_close_nav=float(nav))')


def _checked_source() -> str:
    raw = ENGINE.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != ENGINE_SHA256:
        raise RuntimeError(f"FROZEN_ENGINE_SHA_MISMATCH:{actual}")
    source = raw.decode("utf-8")
    if source.count(BEFORE) != 1 or source.count("frame.attrs.update(signal_date=date") != 1:
        raise RuntimeError("NAV_CONTEXT_INSERTION_POINT_CHANGED")
    return source.replace(BEFORE, AFTER, 1)


@lru_cache(maxsize=1)
def _compiled_engine() -> types.ModuleType:
    patched = _checked_source()
    name = "joint_capacity_nav_context_engine_v1"
    module = types.ModuleType(name)
    module.__file__ = str(ENGINE)
    module.__package__ = ""
    sys.modules[name] = module
    try:
        exec(compile(patched, f"{ENGINE}::nav_context_v1", "exec"), module.__dict__)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def get_engine() -> types.ModuleType:
    """Return original semantics plus a decision-time NAV callback attribute."""
    _checked_source()  # Recheck even after the compiled module is cached.
    return _compiled_engine()
