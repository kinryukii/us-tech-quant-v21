from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.v22.abcde_a2_r4x_hive_20230712_execution_price_recovery import main


if __name__ == "__main__":
    raise SystemExit(main())
