"""Frozen auxiliary diagnostics and portfolio concentration, no fitted updates."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from risk_aux import AuxiliaryDiagnostics,FrozenRisk
from evaluate import DATA,QUALIFIED,forbid_fitting,write,sha

ROOT=Path(__file__).resolve().parent

def main():
    guard=forbid_fitting();records=[];seals=[]
    for year,stage in [(2025,'validation'),(2026,'final')]:
        source=DATA/'pre2026_joint_context.parquet' if year==2025 else QUALIFIED/'test_features_context.parquet'
        frame=pd.read_parquet(source)
        frame=frame.loc[frame.signal_date.dt.year.eq(year)].copy()
        aux=AuxiliaryDiagnostics(stage);pred=aux.predict(frame)
        out=pd.concat([frame[['signal_date','ticker']].reset_index(drop=True),pred.reset_index(drop=True)],axis=1)
        out.to_parquet(ROOT/f'STATE_DIAGNOSTICS_{year}.parquet',index=False)
        seals.append(dict(year=year,source_sha256=sha(source),rows=len(out),
            clusters=out.cluster.value_counts().sort_index().to_dict(),anomaly_rows=int(out.is_anomaly.sum())))
        risk=FrozenRisk(stage)
        for folder in sorted((ROOT/f'evaluation_{year}/cost_10').iterdir()):
            if not folder.is_dir():continue
            positions=pd.read_parquet(folder/'positions.parquet')
            for date,g in positions.groupby('date'):
                names=g.ticker.tolist();w=g.weight.fillna(0).to_numpy(float)
                cov=risk.covariance_for(names);factor=risk.covariance_for(names,factor=True)
                vals,vecs=np.linalg.eigh(cov)
                variance=float(w@cov@w)
                top=float(vals[-1]*(w@vecs[:,-1])**2) if len(vals) else 0.
                norm=w.sum()
                records.append(dict(year=year,policy=folder.name,date=date,names=len(g),
                    gross_weight=float(norm),effective_names=float(norm**2/(w@w)) if w@w>0 else 0.,
                    predicted_daily_vol=np.sqrt(max(0,variance)),factor_model_daily_vol=np.sqrt(max(0,float(w@factor@w))),
                    first_component_variance_share=top/variance if variance>0 else 0.,
                    unknown_risk_names=sum(t not in risk.lookup for t in names)))
    pd.DataFrame(records).to_csv(ROOT/'PORTFOLIO_RISK_DIAGNOSTICS.csv',index=False)
    assert guard['attempts']==0
    write(ROOT/'DIAGNOSTICS_RECEIPT.json',dict(status='COMPLETE',fit_attempts=guard['attempts'],
        sources=seals,portfolio_risk_rows=len(records),signal_use='description only; no exclusion or retuning'))

if __name__=='__main__':main()
