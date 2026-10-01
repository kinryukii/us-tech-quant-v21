"""Export historical ensemble candidate rankings separately from actual positions."""
from pathlib import Path
import json
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parent
DATA=ROOT.parent/'a2_qualification_holdings_v1_20260927/data/test_features_context.parquet'

def main():
    panel=pd.read_parquet(DATA,columns=['signal_date','ticker','new_buy_eligible'])
    records=[]
    for name in ['ensemble_equal','ensemble_disagreement','ensemble_stacking']:
        folder=ROOT/'evaluation_2026/cost_10'/name
        raw=pd.read_parquet(folder/'raw_model_outputs.parquet')
        row=raw.sort_values('signal_date').iloc[-1]
        date=row.signal_date
        eligible=set(panel.loc[panel.signal_date.eq(date)&panel.new_buy_eligible,'ticker'])
        outputs=json.loads(row.raw_model_outputs_json)
        ranking=[]
        for ticker,values in outputs.items():
            if ticker not in eligible:continue
            scores=np.asarray(values['fused_action_values'],float)
            ranking.append(dict(policy=name,signal_date=date,ticker=ticker,
                ensemble_preference_score=float(scores[1:].max()-scores[0]),
                model_target_weight=float(values['chosen_weight']),
                positive_preference=bool(scores[1:].max()>scores[0]),
                qualification='historical verified-subset candidate; not certified full pool'))
        selected=sorted(ranking,key=lambda x:(-x['ensemble_preference_score'],x['ticker']))[:20]
        for i,value in enumerate(selected,1):value['rank']=i
        records+=selected
    result=pd.DataFrame(records)
    assert result.groupby('policy').size().eq(20).all()
    result.to_csv(ROOT/'ENSEMBLE_LAST_SIGNAL_TOP20_RANKINGS.csv',index=False)
    lines=['# 三种集成的历史末信号 TOP20','',
        '信号日2026-09-22；核验子池诊断。排名分数是集成偏好，不是预期收益率。TOP20候选排名与实际持仓分开：目标权重为0的证券没有被组合分配器买入。本文件不是当前推荐。','']
    for name,group in result.groupby('policy',sort=False):
        lines += [f'## {name}','','| 名次 | 股票 | 模型目标权重 | 正动作优势 |','|---:|---|---:|---|']
        lines += [f"| {r.rank} | {r.ticker} | {r.model_target_weight:.1%} | {'是' if r.positive_preference else '否'} |" for r in group.itertuples()]
        lines.append('')
    (ROOT/'TOP20_RANKINGS.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'rows':len(result),'signal_date':str(result.signal_date.max().date())}))

if __name__=='__main__':main()
