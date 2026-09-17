#!/usr/bin/env python
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fast4.pipeline import print_summary, run  # noqa: E402


if __name__ == "__main__":
    summary = run()
    print_summary(summary)
