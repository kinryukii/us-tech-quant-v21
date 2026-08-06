"""Guardrails for the no-outcome, no-order prospective shadow runner."""
from __future__ import annotations

import os
import runpy
import sys
import uuid
from pathlib import Path

import pytest


def test_shadow_refuses_unfrozen_model_before_reading_input(monkeypatch):
    cache = Path(os.environ["FAST3_CACHE_ROOT"]) / f"r4_shadow_test_{uuid.uuid4().hex}"
    cache.mkdir(parents=True)
    script = Path(__file__).resolve().parents[2] / "scripts" / "run" / "fast3_r4_prospective_shadow_hard_r22.py"
    monkeypatch.setattr(sys, "argv", [str(script), "--frozen-root", str(cache / "frozen"),
        "--input-parquet", str(cache / "not_read.parquet"), "--output-root", str(cache / "output")])
    with pytest.raises(RuntimeError, match="PROSPECTIVE_MODEL_NOT_FROZEN"):
        runpy.run_path(str(script), run_name="__main__")
    assert not (cache / "output").exists()
