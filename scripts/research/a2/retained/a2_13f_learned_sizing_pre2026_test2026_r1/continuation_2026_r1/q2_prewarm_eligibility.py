"""Q2 initial-pool prewarm through last original raw price, before Q2 activation."""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
PRODUCER=Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\scripts\run_rebuild.py")
R1=Path(r"D:\us-tech-quant\scripts\v22\abcde_a2_r1_nonlinear_cross_sectional_modeling.py")
R0F1=Path(r"D:\us-tech-quant\scripts\v22\fast_a2_r0f1_corporate_action_accounting_repair_and_exact_r4_rerun.py")
REHAB=Path(r"D:\us-tech-quant-cache\13f_pit_v1\a_a2_quarterly_13f_r1\rehab_factors.parquet")
STATUS=Path(r"D:\us-tech-quant-cache\13f_pit_v1\a_a2_quarterly_13f_r1\rehab_status.csv")
CANON=Path(r"D:\us-tech-quant-data\canonical\moomoo_ohlcv\snapshot_id=data_layer_20260911_99642e55d6185fe2402b")


def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);sys.modules[name]=m;s.loader.exec_module(m);return m


def main():
    producer=load("q2_prewarm_original_producer",PRODUCER)
    r1=load("q2_prewarm_original_feature",R1)
    r0f1=load("q2_prewarm_wolf",R0F1)
    producer.END_EXCLUSIVE=pd.Timestamp("2026-08-15")
    wolf=[x for x in r0f1.frozen_evidence_records() if x["ticker"]=="WOLF"][0]
    inventory=pd.read_csv(HERE/"QUARTER_POOL_PRICE_INVENTORY.csv")
    prev=set(inventory.loc[inventory.quarter.isin(["2025Q3","2025Q4","2026Q1"]),"moomoo_transport_code"])
    q2=inventory.loc[inventory.quarter.eq("2026Q2"),["ticker","moomoo_transport_code"]].copy()
    q2_only=q2.loc[~q2.moomoo_transport_code.isin(prev)]
    assert len(q2_only)==50
    index,failures=producer.raw_file_index();assert not failures
    passing=set(pd.read_csv(STATUS).loc[lambda x:x.status.eq("PASS"),"code"])
    shaz_receipt=json.loads((HERE/"SHAZ_REHAB_RECEIPT.json").read_text(encoding="utf-8"))
    if shaz_receipt["status"]=="PASS" and shaz_receipt["row_count"]==0:
        passing.add("US.SHAZ")  # Confirmed no events by one original free-source request.
    rehab=pd.read_parquet(REHAB)
    prices=[];gaps=[]
    for row in q2_only.itertuples(index=False):
        code,ticker=row.moomoo_transport_code,row.ticker
        if code not in index:gaps.append({"code":code,"reason":"NO_ORIGINAL_RAW_FILE"});continue
        if code not in passing:gaps.append({"code":code,"reason":"REHAB_STATUS_NOT_PASS"});continue
        raw=producer.load_raw_code(code,index[code]);raw=raw.loc[raw.trade_date.le("2026-08-14")]
        adjusted,_=producer.adjusted_price_frame(code,ticker,raw,rehab,wolf)
        prices.append(adjusted.loc[adjusted.trade_date.ge("2025-06-01")])
    newer=pd.concat(prices,ignore_index=True) if prices else pd.DataFrame()
    newer.to_parquet(HERE/"Q2_ONLY_PREWARM_PRICES.parquet",index=False)
    older=pd.read_parquet(HERE/"PARTIAL_2026_ORIGINAL_REHAB_PRICES.parquet")
    both=pd.concat([older.loc[older.moomoo_transport_code.isin(set(q2.moomoo_transport_code))],newer],ignore_index=True)
    assert not both.duplicated(["ticker","trade_date"]).any()
    qqq=pd.read_csv(CANON/"canonical_moomoo_ohlcv_daily_qfq.csv",usecols=["ticker","date"])
    calendar=pd.DatetimeIndex(pd.to_datetime(qqq.loc[qqq.ticker.eq("QQQ"),"date"]).unique()).sort_values()
    calendar=calendar[(calendar>="2025-06-01")&(calendar<="2026-08-14")]
    f=r1.build_stock_state_features(both[["ticker","trade_date","close","volume"]])
    position=pd.Series(np.arange(len(calendar)),index=calendar)
    f["calendar_position"]=f.trade_date.map(position)
    f["position_120_prior"]=f.groupby("ticker").calendar_position.shift(120)
    f["required_observations"]=f.groupby("ticker").cumcount()+1
    f["lookback_eligible"]=(f.required_observations.ge(121)&f.calendar_position.notna()&
                            f.position_120_prior.notna()&f.calendar_position.sub(f.position_120_prior).eq(120))
    f["all_features_available"]=np.isfinite(f[list(r1.FEATURE_COLUMNS)].to_numpy(float)).all(axis=1)
    last=f.loc[f.trade_date.eq("2026-08-14"),["ticker","required_observations","lookback_eligible","all_features_available"]]
    q2=q2.merge(last,on="ticker",how="left",validate="one_to_one")
    q2["prewarm_status"]="NO_PRICE_ON_2026_08_14"
    q2.loc[q2.moomoo_transport_code.map(lambda x:x not in index),"prewarm_status"]="NO_ORIGINAL_RAW_FILE"
    q2.loc[q2.moomoo_transport_code.map(lambda x:x in index and x not in passing),"prewarm_status"]="REHAB_STATUS_NOT_PASS"
    q2.loc[q2.required_observations.notna()&~q2.lookback_eligible.fillna(False),"prewarm_status"]="LESS_THAN_121_CONTIGUOUS_SESSIONS"
    q2.loc[q2.lookback_eligible.fillna(False)&~q2.all_features_available.fillna(False),"prewarm_status"]="FEATURE_NOT_FINITE"
    q2.loc[q2.lookback_eligible.fillna(False)&q2.all_features_available.fillna(False),"prewarm_status"]="PREWARM_ELIGIBLE_ON_2026_08_14"
    q2.to_csv(HERE/"Q2_PREWARM_ELIGIBILITY_2026_08_14.csv",index=False)
    result={"status":"Q2_POOL_PREWARM_ONLY_NOT_ACTIVE_SIGNAL","q2_candidate_count":len(q2),
            "q2_only_codes":len(q2_only),"q2_only_price_codes_saved":int(newer.moomoo_transport_code.nunique()),
            "prewarm_status_counts":{str(k):int(v) for k,v in q2.prewarm_status.value_counts().items()},
            "raw_last_date":"2026-08-14","q2_activation":"2026-08-21","a2_scores_computed":0,
            "policy_outcomes_computed":0,"new_fits":0}
    (HERE/"Q2_PREWARM_AUDIT.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__=="__main__":main()
