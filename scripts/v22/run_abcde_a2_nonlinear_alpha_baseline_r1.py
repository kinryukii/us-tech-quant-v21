"""CLI entrypoint for the ABCDE A2-R0/R1 nonlinear baseline."""
from __future__ import annotations

import argparse
from pathlib import Path

from abcde_a2_nonlinear_alpha_baseline_r1 import DEFAULT_RESULTS_ROOT, print_core, run


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    args = parser.parse_args()
    summary = run(args.results_root)
    print_core(summary)
    return 2 if summary["PIT_AUDIT_STATUS"] == "FAIL_CLOSED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
