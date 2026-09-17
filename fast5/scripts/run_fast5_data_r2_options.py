from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fast5.options_data_r2 import main
if __name__ == "__main__": main()
