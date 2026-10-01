"""One relevant original-pool stock probe of the existing moomoo history quota."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'vendor'))
import moomoo


def main():
    out=HERE/'test2026_stage'
    q=moomoo.OpenQuoteContext(host='127.0.0.1',port=18441)
    try:
        before=q.get_history_kl_quota()
        ret,data,page=q.request_history_kline('US.AAPL',start='2026-08-17',end='2026-09-24',ktype=moomoo.KLType.K_DAY,autype=moomoo.AuType.NONE,max_count=1000)
        if ret!=moomoo.RET_OK:
            raise RuntimeError(str(data))
        parts=[data]
        while page is not None:
            ret,data,page=q.request_history_kline('US.AAPL',start='2026-08-17',end='2026-09-24',ktype=moomoo.KLType.K_DAY,autype=moomoo.AuType.NONE,max_count=1000,page_req_key=page)
            if ret!=moomoo.RET_OK:
                raise RuntimeError(str(data))
            parts.append(data)
        after=q.get_history_kl_quota()
    finally:
        q.close()
    frame=pd.concat(parts,ignore_index=True)
    assert not frame.empty
    frame.to_parquet(out/'aapl_raw_2026_0817_0924_quota_probe.parquet',index=False)
    record={'source':'existing moomoo OpenD 127.0.0.1:18441','code':'US.AAPL',
            'reason':'AAPL is a member of original 2026Q1 active 13F pool',
            'request':'K_DAY AuType.NONE 2026-08-17..2026-09-24',
            'fetch_utc':datetime.now(timezone.utc).isoformat(),
            'quota_before':repr(before),'quota_after':repr(after),'rows':len(frame),
            'first_date':str(pd.to_datetime(frame.time_key).min().date()),
            'last_date':str(pd.to_datetime(frame.time_key).max().date()),
            'used_for_formal_ranking':False}
    (out/'aapl_raw_quota_probe.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    print(json.dumps(record),flush=True)


if __name__=='__main__':
    main()
