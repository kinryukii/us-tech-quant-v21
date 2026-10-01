"""Read-only original adjusted-price/32-feature prefix checks at four split boundaries."""
from __future__ import annotations
import importlib.util, json, sys
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
R3=Path(r'D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results\test2026\identity_feature_application_20260926_r3')
REBUILD=Path(r'D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\scripts\run_rebuild.py')
R1=Path(r'D:\us-tech-quant\scripts\v22\abcde_a2_r1_nonlinear_cross_sectional_modeling.py')
FACTORS=Path(r'D:\us-tech-quant-cache\13f_pit_v1\a_a2_quarterly_13f_r1\rehab_factors.parquet')

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    x=importlib.util.module_from_spec(spec);sys.modules[name]=x;spec.loader.exec_module(x);return x

rebuild=module('a2_rebuild_readonly_share',REBUILD)
r1=module('a2_r1_readonly_share',R1)
rebuild.END_EXCLUSIVE=pd.Timestamp('2026-09-25')
source=json.loads((R3/'CONSUMED_RAW_SOURCE_AUDIT.json').read_text(encoding='utf-8'))
events={'US.CVNA':'2026-05-08','US.SLMT':'2026-05-14','US.CRWD':'2026-07-02','US.BYND':'2026-08-14'}
out=[]
for code,ds in events.items():
    paths=[Path(x) for item in source if item['original_code']==code for x in item['paths']]
    assert paths,code
    raw=rebuild.load_raw_code(code,paths)
    rehab=pd.read_parquet(FACTORS,filters=[('code','==',code)])
    ticker=code[3:]
    full_price,full_audit=rebuild.adjusted_price_frame(code,ticker,raw,rehab,{})
    full_feature=r1.build_stock_state_features(full_price)
    date=pd.Timestamp(ds)
    boundary=[(date-pd.offsets.BDay(1)),date,(date+pd.offsets.BDay(1)),pd.Timestamp('2026-09-22')]
    available=set(full_price.trade_date)
    checks=[]
    for d in boundary:
        if d not in available: continue
        p_raw=raw.loc[raw.trade_date.le(d)].copy()
        p_rehab=rehab.loc[pd.to_datetime(rehab.ex_div_date).le(d)].copy()
        p_price,p_audit=rebuild.adjusted_price_frame(code,ticker,p_raw,p_rehab,{})
        p_feature=r1.build_stock_state_features(p_price)
        a=full_feature.loc[full_feature.trade_date.eq(d),list(r1.FEATURE_COLUMNS)]
        b=p_feature.loc[p_feature.trade_date.eq(d),list(r1.FEATURE_COLUMNS)]
        same=len(a)==len(b)==1 and np.array_equal(a.to_numpy(),b.to_numpy(),equal_nan=True)
        checks.append({'signal_date':str(d.date()),'full_vs_prefix_32_features_exact':bool(same),'prefix_event_count':sum(e['audit_kind']=='APPLIED_CORPORATE_ACTION' and pd.Timestamp(e['event_date']).year==2026 for e in p_audit)})
    applied=[x for x in full_audit if x['audit_kind']=='APPLIED_CORPORATE_ACTION' and pd.Timestamp(x['event_date'])==date]
    assert len(applied)==1 and applied[0]['share_event']
    out.append({'code':code,'event_date':ds,'factor_a':float(applied[0]['factor_a']),'factor_b':float(applied[0]['factor_b']),'share_event':True,'checks':checks,'all_prefix_exact':all(x['full_vs_prefix_32_features_exact'] for x in checks)})
(HERE/'SHARE_EVENT_PREFIX_CHECKS.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
print(json.dumps(out,indent=2))
