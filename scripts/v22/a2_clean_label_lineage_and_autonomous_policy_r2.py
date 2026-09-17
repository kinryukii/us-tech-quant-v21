from __future__ import annotations

"""Thin R2 entrypoint for the shared autonomous A2 policy engine."""

import os
import runpy
from pathlib import Path


os.environ["A2_AUTONOMOUS_POLICY_MODE"] = "R2"
SHARED_RUNNER = Path(__file__).with_name("a2_autonomous_buy_sell_and_sizing_policy_r1.py")
runpy.run_path(str(SHARED_RUNNER), run_name="__main__")
