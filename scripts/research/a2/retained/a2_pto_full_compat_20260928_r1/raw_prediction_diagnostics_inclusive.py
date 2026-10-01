"""Retain existing extreme-return hints in a separate, immutable diagnostic."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
from common import ROOT, sha
import raw_prediction_diagnostics as raw

if __name__ == "__main__":
    raw.SOURCES[Path(__file__).name] = sha(Path(__file__))
    raw.main(exclude_source_extreme_warning=False, output_suffix="_INCLUSIVE_EXTREME_HINTS")
