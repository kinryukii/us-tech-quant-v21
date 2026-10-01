"""Inspect nine consumed share events one security block at a time."""
from pathlib import Path
import pandas as pd
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
R4 = HERE.parent / 'r4_continuation' / 'R4_FINAL_CANDIDATE_INPUT_GATE.parquet'
event_dates = {'US.BKNG':'2026-04-06','US.CVNA':'2026-05-08','US.KLAC':'2026-06-12','US.SLMT':'2026-05-14','US.CRWD':'2026-07-02','US.DD':'2026-06-24','US.HON':'2026-06-29','US.BYND':'2026-08-14'}
rows=[]
for code, day in event_dates.items():
    block=pq.read_table(R4,filters=[('moomoo_transport_code','==',code)]).to_pandas()
    block=block.loc[block.signal_date.ge(pd.Timestamp(day))].copy()
    if len(block)==0: continue
    checks=['raw_on_signal','rehab_pass','coordinate_match','lookback_121_eligible','has_32_finite','version_checked']
    row={'original_code':code,'event_date':day,'candidate_days':len(block),'first':str(block.signal_date.min().date()),'last':str(block.signal_date.max().date()),
         'cusips':'|'.join(sorted(block.cusip.dropna().unique())),'classes':'|'.join(sorted(block.title_of_class.dropna().unique()))}
    row.update({f'{c}_true':int(block[c].fillna(False).astype(bool).sum()) for c in checks})
    row['r4_unknown_pubtime']=int(block.final_input_gate.eq('UNKNOWN_CONSUMED_2026_EVENT_PUBLICATION_TIME').sum())
    row['first_consumed_2026_events']='|'.join(sorted(block.first_consumed_2026_event.dropna().astype(str).unique()))
    row['all_r4_gates']='|'.join(f'{k}:{v}' for k,v in block.final_input_gate.value_counts().items())
    row['multi_cusip_pending']=int(block.multi_cusip_transport_interval_pending.fillna(False).astype(bool).sum())
    row['lifecycle_ineligible']=int(block.proven_lifecycle_ineligible.fillna(False).astype(bool).sum())
    rows.append(row)
out=pd.DataFrame(rows)
out.to_csv(HERE/'SHARE_EVENT_BLOCK_DEPENDENCIES.csv',index=False)
print(out.to_string(index=False))
