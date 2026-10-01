"""Fetch only QQQ missing sessions using the existing moomoo OpenD account."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "test2026_stage"


def main():
    sys.path.insert(0, str(HERE / "vendor"))
    import moomoo
    q = moomoo.OpenQuoteContext(host="127.0.0.1", port=18441)
    try:
        quota_before = q.get_history_kl_quota()
        ret, data, page = q.request_history_kline("US.QQQ", start="2026-07-15", end="2026-09-24",
            ktype=moomoo.KLType.K_DAY, autype=moomoo.AuType.QFQ, max_count=1000)
        if ret != moomoo.RET_OK:
            raise RuntimeError(f"QQQ_HISTORY_REQUEST_FAILED:{data}")
        pieces = [data]
        while page is not None:
            ret, data, page = q.request_history_kline("US.QQQ", start="2026-07-15", end="2026-09-24",
                ktype=moomoo.KLType.K_DAY, autype=moomoo.AuType.QFQ, max_count=1000, page_req_key=page)
            if ret != moomoo.RET_OK:
                raise RuntimeError(f"QQQ_HISTORY_PAGE_FAILED:{data}")
            pieces.append(data)
        quota_after = q.get_history_kl_quota()
    finally:
        q.close()
    frame = pd.concat(pieces, ignore_index=True)
    if frame.empty:
        raise RuntimeError("QQQ_HISTORY_EMPTY")
    frame["trade_date"] = pd.to_datetime(frame.time_key).dt.normalize()
    assert frame.trade_date.between("2026-07-15", "2026-09-24").all()
    assert not frame.duplicated("trade_date").any()
    assert np.isfinite(frame[["open", "close"]].to_numpy(float)).all()
    OUT.mkdir(exist_ok=True)
    frame.to_parquet(OUT / "qqq_2026_0715_0924_moomoo_qfq.parquet", index=False)
    metadata = {"source": "existing moomoo OpenD 127.0.0.1:18441",
        "request": "request_history_kline US.QQQ K_DAY QFQ 2026-07-15..2026-09-24",
        "fetch_utc": datetime.now(timezone.utc).isoformat(), "quota_before": repr(quota_before),
        "quota_after": repr(quota_after), "rows": len(frame),
        "first_date": str(frame.trade_date.min().date()), "last_date": str(frame.trade_date.max().date()),
        "older_QQQ_rows_replaced": 0}
    (OUT / "qqq_fetch_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata), flush=True)


if __name__ == "__main__":
    main()
