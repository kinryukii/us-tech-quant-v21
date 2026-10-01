"""Read-only reuse of available runtime; new packages are local to this batch."""
from __future__ import annotations

import importlib
import importlib.metadata
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
REUSED_VENDOR = ROOT.parent / "a2_predict_then_optimize_20260928_r1" / "third_party"
LOCAL_VENDOR = ROOT / "vendor"


def bootstrap() -> dict:
    # Append instead of prepend: never shadow the working NumPy/sklearn runtime.
    for folder in (LOCAL_VENDOR, REUSED_VENDOR):
        if folder.is_dir() and str(folder) not in sys.path:
            sys.path.append(str(folder))
    modules = {}
    for name in ("numpy", "pandas", "scipy", "sklearn", "torch", "pyarrow", "joblib",
                 "xgboost", "lightgbm", "catboost", "interpret", "ngboost"):
        try:
            module = importlib.import_module(name)
            modules[name] = {"status": "AVAILABLE", "version": getattr(module, "__version__", None),
                             "origin": str(getattr(module, "__file__", ""))}
        except Exception as exc:
            modules[name] = {"status": "UNAVAILABLE", "exception": type(exc).__name__,
                             "message": str(exc)}
    return {"python": sys.version, "executable": sys.executable,
            "local_vendor": str(LOCAL_VENDOR), "reused_vendor": str(REUSED_VENDOR),
            "modules": modules}


if __name__ == "__main__":
    print(json.dumps(bootstrap(), ensure_ascii=False, indent=2), flush=True)
