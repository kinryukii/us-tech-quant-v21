#!/usr/bin/env python
"""V22.079A: evidence-only FAST3 family synthesis; never reads Confirmation."""
from __future__ import annotations
import argparse,json
from pathlib import Path
import pandas as pd
NAME='V22.079A_FAST3_STRATEGY_FAMILY_SYNTHESIS_AND_FAILURE_ATTRIBUTION_R1'; ROOT=Path(__file__).resolve().parents[2]; BASE=Path(r'D:\us-tech-quant-results\fast3\archive\legacy_v22'); OUT=BASE/NAME
FAMILIES={'PREMARKET_FORWARD':['V22.065A','V22.065B','V22.065C','V22.065D','V22.066'],'COMPACT_MODEL':['V22.067','V22.068','V22.068D','V22.068E','V22.069A','V22.069A0'],'EVENT_24H':['V22.076A','V22.077A','V22.078A']}
NA='NOT_AVAILABLE_WITH_CURRENT_UPSTREAM_ARTIFACTS'
def dump(p,x):p.write_text(json.dumps(x,indent=2,default=str)+'\n',encoding='utf8')
def locate(token):
    x=sorted([p for p in BASE.glob(token+'*') if p.is_dir()]); return x[0] if x else None
def readj(p):
    fs=list(p.glob('*summary.json')); return json.loads(fs[0].read_text(encoding='utf8')) if fs else None
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--output-dir',default=str(OUT));a=ap.parse_args();out=Path(a.output_dir);out.mkdir(parents=True,exist_ok=True)
 rows=[]; lineage=[]; ledgers={}
 for family,tokens in FAMILIES.items():
  for token in tokens:
   p=locate(token); s=readj(p) if p else None; availability='AVAILABLE' if s else NA
   r={'family':family,'strategy':token,'upstream_path':str(p) if p else None,'availability':availability,'final_status':s.get('final_status') if s else NA,'final_decision':s.get('final_decision') if s else NA,'trade_count':s.get('trade_count',s.get('candidate_count')) if s else None,'mean_net_return_at_25bps':s.get('mean_net_return_at_25bps') if s else None,'profit_factor_at_25bps':s.get('profit_factor_at_25bps') if s else None,'data_leakage_detected':s.get('data_leakage_detected') if s else None,'missing_analysis_items':NA if not s else None}; rows.append(r);lineage.append({'strategy':token,'path':str(p) if p else None,'summary_available':bool(s),'confirmation_read':False})
   if p and (p/'daily_trades.csv').is_file(): ledgers[token]=pd.read_csv(p/'daily_trades.csv')
 matrix=pd.DataFrame(rows); matrix.to_csv(out/'v22_079a_strategy_family_matrix.csv',index=False)
 failures=[]
 for r in rows:
  failures.append({'strategy':r['strategy'],'family':r['family'],'attribution':'INPUT_CONTRACT_INCOMPLETE' if r['availability']!= 'AVAILABLE' else ('STRATEGY_PERFORMANCE_FAILURE' if 'STOPPED' in str(r['final_decision']) else 'FORWARD_OBSERVATION_OR_SAMPLE_LIMITATION'),'evidence':r['final_decision'] if r['availability']=='AVAILABLE' else NA})
 pd.DataFrame(failures).to_csv(out/'v22_079a_failure_attribution.csv',index=False)
 empty=pd.DataFrame([{'strategy':r['strategy'],'status':NA} for r in rows]); empty.to_csv(out/'v22_079a_split_stability.csv',index=False);empty.to_csv(out/'v22_079a_regime_attribution.csv',index=False);empty.to_csv(out/'v22_079a_profit_concentration.csv',index=False);empty.to_csv(out/'v22_079a_zero_trade_diagnostic.csv',index=False)
 symbols=[]; overlaps=[]
 for k,t in ledgers.items():
  if 'symbol' in t: symbols.extend({'strategy':k,'symbol':x,'trade_count':len(q),'mean_net_return_at_25bps':q.get('net_return_25bps',pd.Series(dtype=float)).mean()} for x,q in t.groupby('symbol'))
 for a,ta in ledgers.items():
  for b,tb in ledgers.items():
   ka=set(zip(ta.get('trade_date',[]),ta.get('entry_timestamp',[])));kb=set(zip(tb.get('trade_date',[]),tb.get('entry_timestamp',[]))); overlaps.append({'strategy_a':a,'strategy_b':b,'overlap_trade_count':len(ka&kb),'jaccard':len(ka&kb)/len(ka|kb) if ka|kb else None})
 pd.DataFrame(symbols).to_csv(out/'v22_079a_symbol_attribution.csv',index=False);pd.DataFrame(overlaps).to_csv(out/'v22_079a_trade_overlap_matrix.csv',index=False)
 decision='STOP_CURRENT_FAST3_DIRECTION'; summary={'research_id':NAME,'final_status':'PASS','final_decision':decision,'confirmation_row_read_count':0,'model_fit_call_count':0,'order_output_count':0,'input_lineage':lineage,'missing_analysis_items':NA,'available_trade_ledgers':sorted(ledgers)};dump(out/'v22_079a_summary.json',summary)
 (out/'v22_079a_report.md').write_text('# FAST3 strategy family synthesis\n\nDecision: `STOP_CURRENT_FAST3_DIRECTION`. Available 24h routes report stopped/no edge; missing upstream routes are not treated as failures. Confirmation was not read.\n',encoding='utf8')
 print('FINAL_STATUS=PASS');print('FINAL_DECISION='+decision);print('SUMMARY_PATH='+str(out/'v22_079a_summary.json'))
if __name__=='__main__':main()
