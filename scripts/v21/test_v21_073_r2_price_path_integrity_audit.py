#!/usr/bin/env python
from __future__ import annotations
import importlib.util
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_073_r2_price_path_integrity_audit.py"
SPEC = importlib.util.spec_from_file_location("r2", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC); assert SPEC.loader; SPEC.loader.exec_module(MODULE)
if __name__ == "__main__":
    result = MODULE.run_stage(ROOT)
    assert result["pass_gate"] is True
    assert result["duplicate_count"] == 0
    assert result["missing_ohlc_count"] == 0
    assert result["pit_boundary_violation_count"] == 0
    print("PASS test_v21_073_r2_price_path_integrity_audit")
