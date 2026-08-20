from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PATH = Path(r"D:\us-tech-quant\fast3\src\fast3\options\moomoo_option_acquisition_r2.py")
spec = importlib.util.spec_from_file_location("option_acquisition_r2_test", PATH)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m)


def test_deterministic_quality_and_read_only_contract() -> None:
    rows = [{"option_code": "US.X", "timestamp": "2026-01-01 10:00:00", "bid": 1, "ask": 2}, {"option_code": "US.X", "timestamp": "2026-01-01 10:00:00", "bid": 1, "ask": 2}]
    assert m.quality(rows, ["option_code", "timestamp"])["duplicate_rows"] == 1
    assert m.num("nan") is None
    source = PATH.read_text(encoding="utf-8")
    assert "OpenTradeContext" not in source
    assert "unlock_trade" not in source
    assert ".fit(" not in source
