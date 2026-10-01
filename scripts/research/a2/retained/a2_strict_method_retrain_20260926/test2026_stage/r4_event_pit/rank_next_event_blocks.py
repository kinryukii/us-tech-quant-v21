"""Rank still-unproved event blocks without expanding the full candidate ledger."""
from pathlib import Path
import pandas as pd
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
R4 = HERE.parent / "r4_continuation" / "R4_FINAL_CANDIDATE_INPUT_GATE.parquet"
events = pd.read_csv(HERE / "ALL_1094_EVENT_PRIORITY.csv", parse_dates=["event_date"])
done = {("US.APD", "2026-01-02"), ("US.FERG", "2026-01-02"), ("US.AXP", "2026-01-02"), ("US.ROP", "2026-01-02"), ("US.PGR", "2026-01-02"),
        ("US.GEV", "2026-01-05"), ("US.JPM", "2026-01-06"), ("US.MA", "2026-01-09"), ("US.MRVL", "2026-01-09"), ("US.ORCL", "2026-01-09"), ("US.RLYB", "2026-02-06")}
rows=[]
for code, group in events.groupby("original_code", sort=False):
    dates=sorted(group.event_date.dropna().unique())
    for idx, day in enumerate(dates):
        day=pd.Timestamp(day)
        if (code, str(day.date())) in done:
            continue
        nxt=pd.Timestamp(dates[idx+1]) if idx+1<len(dates) else pd.Timestamp("2026-09-23")
        if day>=nxt: continue
        t=pq.read_table(R4, filters=[("moomoo_transport_code","==",code)], columns=["signal_date","final_input_gate"])
        x=t.to_pandas()
        x=x.loc[x.signal_date.ge(day)&x.signal_date.lt(nxt)]
        if len(x)==0: continue
        u=x.final_input_gate.astype(str).str.startswith("UNKNOWN")
        if not u.any(): continue
        erow=group.loc[group.event_date.eq(day)].iloc[0]
        rows.append({"original_code":code,"event_date":str(day.date()),"next_event_exclusive":str(nxt.date()),"interval_candidate_days":len(x),"interval_unknown_days":int(u.sum()),"factor_a":erow.factor_a,"factor_b":erow.factor_b,"cash_amount":erow.total_cash_div,"prior_raw_close":erow.prior_raw_close,"simple_cash_match":erow.simple_cash_floor_matches_vendor})
out=pd.DataFrame(rows).sort_values(["interval_unknown_days","original_code"],ascending=[False,True])
out.to_csv(HERE/"NEXT_UNPROVED_EVENT_BLOCK_PRIORITY.csv",index=False)
print(out.head(20).to_string(index=False))
