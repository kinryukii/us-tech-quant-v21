#!/usr/bin/env python
from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fast4.r2_pipeline import finalize_checkpoint, print_summary, run  # noqa: E402


if __name__ == "__main__":
    checkpoint = os.environ.get("FAST4_R2_FINALIZE_CHECKPOINT", "").strip()
    result, frozen_root = finalize_checkpoint(checkpoint) if checkpoint else run()
    print_summary(result, frozen_root)
