from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from fast5.option_pilot_r1 import main
if __name__ == "__main__": main()
