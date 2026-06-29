#!/usr/bin/env python
from __future__ import annotations
import importlib.util
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_073_r1_pit_daily_price_path_panel_builder.py"
SPEC = importlib.util.spec_from_file_location("r1", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC); assert SPEC.loader; SPEC.loader.exec_module(MODULE)
if __name__ == "__main__":
    result = MODULE.run_stage(ROOT)
    paths = pd.read_csv(ROOT / MODULE.OUT_REL / MODULE.PATH_NAME)
    assert result["pass_gate"] is True
    assert len(paths) == result["path_rows"]
    assert paths["forward_day_index"].between(1, 20).all()
    assert not paths["signal_generation_input_allowed"].any()
    print("PASS test_v21_073_r1_pit_daily_price_path_panel_builder")
