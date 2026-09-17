#!/usr/bin/env python
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT.parent / "fast4" / "src"))

from fast5.training import print_summary, run  # noqa: E402


if __name__ == "__main__":
    result, _, frozen_root = run()
    print_summary(result, frozen_root)
