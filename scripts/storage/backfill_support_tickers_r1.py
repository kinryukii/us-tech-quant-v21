from pathlib import Path
import pandas as pd,json,hashlib,os
SRC=Path(r'D:\us-tech-quant-cache\market_data\moomoo\daily'); DST=Path(r'D:\us-tech-quant-data\stocks')
def sha(p):
 h=hashlib.sha256();
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
for t in ['SOXL','TQQQ']:
 d=DST/t; d.mkdir(parents=True,exist_ok=False); out={}
 for a in ['raw','qfq']:
  s=SRC/a/(t+'.csv'); f=pd.read_csv(s); f['date']=f.date.astype(str); f=f.sort_values('date'); assert not f.date.duplicated().any() and '2026-07-06' in set(f.date)
  p=d/f'daily_{a}.parquet'; tmp=p.with_suffix('.tmp'); f.to_parquet(tmp,index=False,compression='zstd'); os.replace(tmp,p); out[a]=(len(f),sha(p))
 d.joinpath('metadata.json').write_text(json.dumps({'ticker':t,'asset_type':'ETF','historical_support_ticker':True,'current_universe_member':False,'source_path':str(SRC),'source_snapshot_id':'market_data/moomoo/daily','source_sha256':sha(SRC/'qfq'/(t+'.csv')),'raw_row_count':out['raw'][0],'qfq_row_count':out['qfq'][0],'date_min':'2018-01-02','date_max':'2026-07-06','raw_file_sha256':out['raw'][1],'qfq_file_sha256':out['qfq'][1],'provenance_status':'LOCAL_MOOMOO_QFQ_RAW_VALIDATED'},indent=2)+'\n')
