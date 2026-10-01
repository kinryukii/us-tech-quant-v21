"""Materialize only newly fetched fixed-pool raw codes with the frozen price builder."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd

HERE=Path(__file__).resolve().parent
PRODUCER=Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\scripts\run_rebuild.py")
R0F1=Path(r"D:\us-tech-quant\scripts\v22\fast_a2_r0f1_corporate_action_accounting_repair_and_exact_r4_rerun.py")
OLD_REHAB=Path(r"D:\us-tech-quant-cache\13f_pit_v1\a_a2_quarterly_13f_r1\rehab_factors.parquet")
OLD_STATUS=Path(r"D:\us-tech-quant-cache\13f_pit_v1\a_a2_quarterly_13f_r1\rehab_status.csv")
OLD_PARTIAL=HERE/"PARTIAL_2026_ORIGINAL_REHAB_PRICES.parquet"


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module


def main(subscription: bool = False):
    producer=load("original_price_builder_for_reused_raw",PRODUCER)
    r0f1=load("original_wolf_evidence_for_reused_raw",R0F1)
    producer.END_EXCLUSIVE=pd.Timestamp("2026-09-23")
    wolf=next(r for r in r0f1.frozen_evidence_records() if r["ticker"]=="WOLF")
    pool=pd.read_csv(HERE/"QUARTER_POOL_PRICE_INVENTORY.csv")
    mapping=pool[["moomoo_transport_code","ticker"]].drop_duplicates()
    assert mapping.groupby("moomoo_transport_code").ticker.nunique().max()==1
    mapping=dict(mapping.itertuples(index=False,name=None))
    old_status=pd.read_csv(OLD_STATUS)
    old_good=set(old_status.loc[old_status.status.eq("PASS"),"code"])
    new_status=pd.read_csv(HERE/"REHAB_NEW_OCCUPIED_ONLY"/"rehab_status.csv")
    new_good=set(new_status.loc[new_status.status.eq("PASS"),"code"])
    subscription_good=set()
    if subscription:
        sub_status=pd.read_csv(HERE/"REHAB_SUBSCRIPTION_ONLY"/"rehab_status.csv")
        subscription_good=set(sub_status.loc[sub_status.status.eq("PASS"),"code"])
    rehab=pd.concat([
        pd.read_parquet(OLD_REHAB).loc[lambda d:d.code.isin(old_good)],
        pd.read_parquet(HERE/"REHAB_NEW_OCCUPIED_ONLY"/"rehab_factors.parquet").loc[lambda d:d.code.isin(new_good)],
        *([pd.read_parquet(HERE/"REHAB_SUBSCRIPTION_ONLY"/"rehab_factors.parquet")
           .loc[lambda d:d.code.isin(subscription_good)]] if subscription else []),
    ],ignore_index=True)
    original_index,failures=producer.raw_file_index()
    assert not failures
    prior=pd.read_parquet(OLD_PARTIAL,columns=["moomoo_transport_code","trade_date","open","close","high","low","volume"])
    prior=prior.loc[pd.to_datetime(prior.trade_date).eq("2026-08-14")].set_index("moomoo_transport_code")
    files=(list(HERE.glob("SUBSCRIPTION_US_*_RAW_DAY_K_INPUT_ONLY.parquet")) if subscription else
           list(HERE.glob("REUSED_*_RAW_DAY_K.parquet"))+list(HERE.glob("PILOT_*_RAW_DAY_K.parquet")))
    outputs=[];audits=[]
    for n,path in enumerate(sorted(files),1):
        frame=pd.read_parquet(path)
        codes=set(frame.code.astype(str))
        if len(codes)!=1:
            audits.append({"path":str(path),"status":"MIXED_OR_NO_CODE"});continue
        code=next(iter(codes))
        if code not in mapping or code not in old_good|new_good|subscription_good:
            audits.append({"code":code,"status":"NO_POOL_MAPPING_OR_REHAB_PASS"});continue
        ticker=mapping[code]
        frame["trade_date"]=pd.to_datetime(frame.time_key).dt.normalize()
        raw=producer.load_raw_code(code,original_index[code]) if code in original_index else pd.DataFrame()
        has_original=not raw.empty
        if has_original:
            overlap=raw.merge(frame,on="trade_date",suffixes=("_old","_new"))
            if any((pd.to_numeric(overlap[f"{field}_old"])-pd.to_numeric(overlap[f"{field}_new"])).abs().gt(1e-9).any()
                   for field in ("open","close","high","low","volume")):
                audits.append({"code":code,"ticker":ticker,"status":"RAW_OVERLAP_CONFLICT"});continue
            raw=pd.concat([raw,frame],ignore_index=True).sort_values("trade_date",kind="mergesort").drop_duplicates("trade_date",keep="first")
        else:
            raw=frame.sort_values("trade_date",kind="mergesort").drop_duplicates("trade_date",keep="first")
        raw=raw.loc[raw.trade_date.le("2026-09-22")]
        try:
            adjusted,events=producer.adjusted_price_frame(code,ticker,raw,rehab,wolf)
            boundary=adjusted.loc[adjusted.trade_date.eq("2026-08-14")]
            if code in prior.index:
                reference=prior.loc[code]
                if len(boundary)!=1:
                    raise RuntimeError("OLD_AUG14_BOUNDARY_MISSING")
                boundary_error=max(abs(float(boundary[field].iloc[0])-float(reference[field]))
                                   for field in ("open","close","high","low","volume"))
                if boundary_error>1e-9:
                    raise RuntimeError(f"OLD_AUG14_BOUNDARY_MISMATCH:{boundary_error}")
            else:
                boundary_error=None
            extension=adjusted.loc[adjusted.trade_date.ge("2025-06-01")]
            if len(extension):
                outputs.append(extension)
            audits.append({"code":code,"ticker":ticker,
                           "status":"MATERIALIZED_INPUT_ONLY" if len(extension) else "NO_2025_PLUS_PRICE",
                           "original_raw_history_present":has_original,
                           "old_aug14_boundary_max_error":boundary_error,
                           "first_date":str(extension.trade_date.min().date()),
                           "last_date":str(extension.trade_date.max().date()),
                           "row_count":len(extension),"applied_event_count":len(events),
                           "rehab_source":"OLD" if code in old_good else "FETCHED_AFTER_TEST_ASOF"})
        except Exception as exc:
            audits.append({"code":code,"ticker":ticker,"status":"BUILD_OR_BOUNDARY_ERROR",
                           "error":f"{type(exc).__name__}:{str(exc)[:240]}"})
        if n%50==0:print(f"processed {n}/{len(files)}",flush=True)
    assert outputs
    stem="SUBSCRIPTION" if subscription else "REUSED"
    pd.concat(outputs,ignore_index=True).to_parquet(HERE/f"{stem}_2026_ADJUSTED_PRICE_INPUT_ONLY.parquet",index=False)
    (HERE/f"{stem}_2026_ADJUSTED_PRICE_AUDIT.json").write_text(json.dumps({
        "fixed_test_asof":"2026-09-23T18:40:43Z","raw_file_count":len(files),
        "materialized_codes":sum(x["status"]=="MATERIALIZED_INPUT_ONLY" for x in audits),
        "boundary_exact_codes":sum(x.get("old_aug14_boundary_max_error")==0 for x in audits),
        "records":audits,"limit":"Input-only continuation. New rehab fetched after TEST_ASOF has no historical publication timestamp; full-pool and QQQ gaps remain."
    },ensure_ascii=False,indent=2,default=str)+"\n",encoding="utf-8")
    print(json.dumps({"raw_files":len(files),"materialized_codes":len(outputs),
                      "boundary_exact":sum(x.get("old_aug14_boundary_max_error")==0 for x in audits)},ensure_ascii=False))


def authority_alias_input_only():
    """Apply the frozen builder to eight evidence-bound current transport codes."""
    producer=load("original_price_builder_for_authority_aliases",PRODUCER)
    r0f1=load("original_wolf_evidence_for_authority_aliases",R0F1)
    producer.END_EXCLUSIVE=pd.Timestamp("2026-09-23")
    wolf=next(r for r in r0f1.frozen_evidence_records() if r["ticker"]=="WOLF")
    expected={
        "US.ONC":("BGNE","07725L102","2025-01-02"),
        "US.SRTA":("BLDE","092667104","2025-08-29"),
        "US.AAMI":("BSIG","10948W103","2025-01-02"),
        "US.AZN":("AZNCF","G0593M107","2026-02-02"),
        "US.LLYVK":("LLYVB","530909308","2025-12-16"),
        "US.MS":("MSTLW","617446448","2026-08-04"),
        "US.TGT":("CBDY","87612E106","2026-05-29"),
        "US.GE":("GE.WI","369604301","2024-04-02"),
    }
    authority=pd.read_csv(
        r"D:\us-tech-quant-results\massive_r3_remaining31_external_authority_r2\20260903T131804Z\tables\external_identity_authority.csv",
        dtype={"input_security_key":str})
    original=pd.concat([
        pd.read_parquet(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\universe\quarterly_universe_members.parquet")
          .loc[lambda d:d.quarter.isin(["2025Q3","2025Q4","2026Q1"])],
        pd.read_parquet(HERE/"Q2_ORIGINAL24_INITIAL_CANDIDATES.parquet"),
    ],ignore_index=True)
    rehab=pd.read_parquet(HERE/"REHAB_AUTHORITY_ALIASES_ONLY"/"rehab_factors.parquet")
    status=pd.read_csv(HERE/"REHAB_AUTHORITY_ALIASES_ONLY"/"rehab_status.csv")
    assert set(status.loc[status.status.eq("PASS"),"code"])==set(expected)
    outputs=[];audits=[]
    for code,(ticker,cusip,identity_start) in expected.items():
        source=original.loc[original.ticker.eq(ticker)]
        assert len(source) and set(source.cusip.astype(str))=={cusip}
        if ticker!="GE.WI":
            case=authority.loc[authority.input_ticker.eq(ticker)]
            assert len(case)==1 and case.iloc[0].input_security_key==cusip
            assert case.iloc[0].provider_symbol==code.removeprefix("US.")
        path=HERE/f"SUBSCRIPTION_{code.replace('.','_')}_RAW_DAY_K_INPUT_ONLY.parquet"
        raw=pd.read_parquet(path)
        assert set(raw.code.astype(str))=={code}
        raw["trade_date"]=pd.to_datetime(raw.time_key).dt.normalize()
        raw=raw.loc[raw.trade_date.le("2026-09-22")].sort_values("trade_date")
        assert not raw.trade_date.duplicated().any()
        adjusted,events=producer.adjusted_price_frame(code,ticker,raw,rehab,wolf)
        allowed=adjusted.loc[adjusted.trade_date.ge("2025-06-01")].copy()
        outputs.append(allowed)
        audits.append({"code":code,"original_ticker":ticker,"original_cusip":cusip,
                       "identity_evidence_start":identity_start,
                       "raw_first":str(raw.trade_date.min().date()),
                       "raw_last":str(raw.trade_date.max().date()),
                       "adjusted_rows_from_2025_06":len(allowed),
                       "applied_event_count":len(events),
                       "status":"INPUT_ONLY_NOT_ASOF_VERSION_CERTIFIED"})
    pd.concat(outputs,ignore_index=True).to_parquet(
        HERE/"AUTHORITY_ALIAS_ADJUSTED_PRICE_INPUT_ONLY.parquet",index=False)
    (HERE/"AUTHORITY_ALIAS_ADJUSTED_PRICE_AUDIT.json").write_text(
        json.dumps({"fixed_test_asof":"2026-09-23T18:40:43Z",
                    "builder":"ORIGINAL_PIT_FORWARD_REHAB_INDEX",
                    "records":audits,
                    "limit":"Dates before identity evidence starts require independent identity proof; post-ASOF rehab version is not automatically PIT certified."},
                   ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"authority_codes":len(audits),
                      "adjusted_rows":sum(x["adjusted_rows_from_2025_06"] for x in audits)}))


def official_common_alias_input_only():
    """Use original price builder for two original-CUSIP-matched common-share transports."""
    producer=load("original_price_builder_for_common_aliases",PRODUCER)
    r0f1=load("original_wolf_evidence_for_common_aliases",R0F1)
    producer.END_EXCLUSIVE=pd.Timestamp("2026-09-23")
    wolf=next(r for r in r0f1.frozen_evidence_records() if r["ticker"]=="WOLF")
    expected={"US.DTE":("DTP","233331107","COM"),
              "US.LILA":("LILAB","G9001E102","COM CL A")}
    original=pd.read_parquet(
        r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\universe\quarterly_universe_members.parquet")
    original=original.loc[original.quarter.isin(["2025Q3","2025Q4","2026Q1"])]
    rehab=pd.read_parquet(HERE/"REHAB_OFFICIAL_COMMON_ALIASES_ONLY"/"rehab_factors.parquet")
    status=pd.read_csv(HERE/"REHAB_OFFICIAL_COMMON_ALIASES_ONLY"/"rehab_status.csv")
    assert set(status.loc[status.status.eq("PASS"),"code"])==set(expected)
    outputs=[];audits=[]
    for code,(ticker,cusip,share_class) in expected.items():
        source=original.loc[original.ticker.eq(ticker)]
        assert len(source) and set(source.cusip.astype(str))=={cusip}
        assert set(source.title_of_class.astype(str))=={share_class}
        raw=pd.read_parquet(HERE/f"SUBSCRIPTION_{code.replace('.','_')}_RAW_DAY_K_INPUT_ONLY.parquet")
        assert set(raw.code.astype(str))=={code}
        raw["trade_date"]=pd.to_datetime(raw.time_key).dt.normalize()
        raw=raw.loc[raw.trade_date.le("2026-09-22")].sort_values("trade_date")
        assert not raw.trade_date.duplicated().any()
        adjusted,events=producer.adjusted_price_frame(code,ticker,raw,rehab,wolf)
        allowed=adjusted.loc[adjusted.trade_date.ge("2025-06-01")].copy()
        outputs.append(allowed)
        audits.append({"code":code,"original_ticker":ticker,"original_cusip":cusip,
                       "original_share_class":share_class,
                       "raw_first":str(raw.trade_date.min().date()),
                       "raw_last":str(raw.trade_date.max().date()),
                       "adjusted_rows_from_2025_06":len(allowed),
                       "applied_event_count":len(events),
                       "applied_events":[{"source_event_date":str(pd.Timestamp(e["source_event_date"]).date()),
                                          "applied_session":str(pd.Timestamp(e["event_date"]).date()),
                                          "factor_a":e["factor_a"],"factor_b":e["factor_b"]}
                                         for e in events if e["audit_kind"]=="APPLIED_CORPORATE_ACTION"],
                       "status":"INPUT_ONLY_NOT_ASOF_VERSION_CERTIFIED"})
    pd.concat(outputs,ignore_index=True).to_parquet(
        HERE/"OFFICIAL_COMMON_ALIAS_ADJUSTED_PRICE_INPUT_ONLY.parquet",index=False)
    (HERE/"OFFICIAL_COMMON_ALIAS_ADJUSTED_PRICE_AUDIT.json").write_text(
        json.dumps({"fixed_test_asof":"2026-09-23T18:40:43Z",
                    "builder":"ORIGINAL_PIT_FORWARD_REHAB_INDEX","records":audits,
                    "limit":"Post-ASOF rehab version is not automatically PIT certified."},
                   ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"codes":len(audits),"rows":sum(x["adjusted_rows_from_2025_06"] for x in audits)}))


if __name__=="__main__":
    if "--authority-aliases" in sys.argv[1:]:
        authority_alias_input_only()
    elif "--official-common-aliases" in sys.argv[1:]:
        official_common_alias_input_only()
    else:
        main(subscription="--subscription" in sys.argv[1:])
