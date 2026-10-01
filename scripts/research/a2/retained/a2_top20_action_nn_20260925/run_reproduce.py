"""Explicit optional rerun into a new empty directory; never changes frozen evidence."""
from __future__ import annotations

import argparse
from pathlib import Path

import safe_inputs
import train


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path, help="new empty output directory under this task")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    output = args.output.resolve()
    if root not in output.parents or output == root or (output.exists() and any(output.iterdir())):
        raise ValueError("OUTPUT_MUST_BE_NEW_EMPTY_TASK_CHILD")
    output.mkdir(parents=True, exist_ok=True)
    train.load_inputs = safe_inputs.load_inputs
    train.ROOT = output
    train.main()


if __name__ == "__main__":
    main()
