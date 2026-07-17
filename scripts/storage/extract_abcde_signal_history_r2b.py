"""Offline, immutable extraction of final ABCDE ranks from promoted legacy outputs."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
import pandas as pd
ROOT=Path(r'D:\us-tech-quant'); DEST=Path(r'D:\us-tech-quant-backtests\_strategy_signal_history\ABCDE_R1')
SOURCES=[ROOT/'outputs/v21/V21.233_MOOMOO_ONLY_ABCDE_RERUN_20260706_LOCKED/abcde_strategy_ranking_master.csv',ROOT/'outputs/v22/daily_research_archives/2026-07-08/V22.045_20260709T132433Z/raw/abcde/abcde_strategy_ranking_master.csv',ROOT/'outputs/v21/V21.233_MOOMOO_ONLY_ABCDE_RERUN/abcde_strategy_ranking_master.csv']
def sha(p):
 h=hashlib.sha256();
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def main():
 if DEST.exists(): raise SystemExit('refusing to overwrite compact signal history')
 rows=[]; prov=[]; excluded=[]
 for source in SOURCES:
  f=pd.read_csv(source); h=sha(source)
  for d,part in f.groupby(f['latest_date'].astype(str),sort=True):
   partial = len(part)==5 and part['ticker'].nunique()==1 and part['strategy_name'].nunique()==5
   if partial:
    for r in part.itertuples(index=False): excluded.append({'source_path':str(source),'research_date':d,'strategy_id':str(r.strategy_name),'ticker':str(r.ticker),'rank':int(r.rank),'score':r.score,'exclusion_class':'ARCHIVE_CARRYOVER_PARTIAL_DATE_RESIDUE','exclusion_reason':'ARCHIVE_CARRYOVER_PARTIAL_DATE_RESIDUE','canonical_source_for_date':'V21.233_MOOMOO_ONLY_ABCDE_RERUN_20260706_LOCKED','source_sha256':h})
    prov.append({'research_date':d,'source_path':str(source),'source_sha256':h,'row_count':len(part),'promotion_rule':'EXCLUDED_PARTIAL_DATE_RESIDUE','canonical_selected':False})
    continue
   for r in part.itertuples(index=False): rows.append({'research_date':d,'price_date':d,'strategy_id':str(r.strategy_name),'strategy_version':'V21.233_MOOMOO_ONLY_COMPACT_PROXY','ticker':str(r.ticker),'rank':int(r.rank),'score':r.score,'eligible':True,'universe_id':'V21.233_MOOMOO_ONLY','snapshot_id':str(r.source_snapshot_id),'run_id':source.parent.name,'data_trust_status':'MOOMOO_ONLY','warning_count':int(r.unavailable_component_count),'source_sha256':h,'source_legacy_path':str(source)})
   prov.append({'research_date':d,'source_path':str(source),'source_sha256':h,'row_count':len(part),'promotion_rule':'LOCKED' if 'LOCKED' in source.parent.name else 'OFFICIAL_V21_233_OR_DAILY_ARCHIVE_COMPLETE','canonical_selected':True})
 out=pd.DataFrame(rows)
 dup=out.duplicated(['research_date','strategy_id','ticker'],keep=False)
 if dup.any(): raise SystemExit('ambiguous duplicate rank key')
 DEST.mkdir(parents=True)
 out.to_parquet(DEST/'abcde_rank_history.parquet',index=False,engine='pyarrow',compression='zstd')
 out[['research_date','ticker','universe_id','eligible','snapshot_id']].drop_duplicates().to_parquet(DEST/'abcde_universe_history.parquet',index=False,engine='pyarrow',compression='zstd')
 pd.DataFrame(prov).to_parquet(DEST/'abcde_source_provenance.parquet',index=False,engine='pyarrow',compression='zstd')
 pd.DataFrame(excluded).to_parquet(DEST/'abcde_excluded_residual_rows.parquet',index=False,engine='pyarrow',compression='zstd')
 pd.DataFrame(prov).to_parquet(DEST/'abcde_canonical_selection_report.parquet',index=False,engine='pyarrow',compression='zstd')
 out[['research_date','strategy_id','ticker','rank','score']].to_parquet(DEST/'abcde_validation_baseline.parquet',index=False,engine='pyarrow',compression='zstd')
 meta={'strategy_ids':sorted(out.strategy_id.unique()),'row_count':len(out),'date_range':[out.research_date.min(),out.research_date.max()],'schema':list(out.columns),'broker_action_allowed':False,'official_adoption_allowed':False,'research_only':True}
 (DEST/'abcde_strategy_metadata.json').write_text(json.dumps(meta,indent=2)+'\n')
 (DEST/'abcde_signal_manifest.json').write_text(json.dumps({'sources':prov,'rank_history_sha256':sha(DEST/'abcde_rank_history.parquet'),'deduplication':'unique research_date/strategy_id/ticker; ambiguity fails','broker_action_allowed':False,'official_adoption_allowed':False,'research_only':True},indent=2)+'\n')
 print(json.dumps(meta))
if __name__=='__main__':main()
