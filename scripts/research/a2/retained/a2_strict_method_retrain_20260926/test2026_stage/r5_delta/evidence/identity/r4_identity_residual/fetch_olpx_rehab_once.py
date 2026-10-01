"""One permitted-source OLPX rehab query, saved separately from frozen caches."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENDOR = HERE.parents[1] / "vendor"
sys.path.insert(0, str(VENDOR))
import moomoo  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    began = datetime.now(timezone.utc).isoformat()
    context = moomoo.OpenQuoteContext(host="127.0.0.1", port=18441)
    try:
        ret, data = context.get_rehab("US.OLPX")
    finally:
        context.close()
    receipt = {"code": "US.OLPX", "query_utc": began, "ret": int(ret),
               "status": "PASS" if ret == moomoo.RET_OK else "FAIL",
               "data_rows": int(len(data)) if ret == moomoo.RET_OK else None,
               "error": "" if ret == moomoo.RET_OK else str(data),
               "saved_after_test_asof": True,
               "historical_pit_approved_by_this_receipt": False}
    if ret == moomoo.RET_OK:
        path = HERE / "OLPX_REHAB_SINGLE_QUERY_20260927.parquet"
        data.to_parquet(path, index=False)
        receipt["saved_path"] = str(path)
        receipt["saved_sha256"] = sha(path)
        receipt["columns"] = list(data.columns)
    (HERE / "OLPX_REHAB_SINGLE_QUERY_RECEIPT.json").write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()
