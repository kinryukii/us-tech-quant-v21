"""Resume feature eligibility and frozen A2 inference from saved qualified price segment."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
R1ROOT=Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1")
R1=Path(r"D:\us-tech-quant\scripts\v22\abcde_a2_r1_nonlinear_cross_sectional_modeling.py")
OLD_QFQ=Path(r"D:\us-tech-quant-data\moomoo\source\prices_qfq")
CANON=Path(r"D:\us-tech-quant-data\canonical\moomoo_ohlcv\snapshot_id=data_layer_20260911_99642e55d6185fe2402b")
PRICES=HERE/"PARTIAL_2026_ORIGINAL_REHAB_PRICES.parquet"


def main():
    spec=importlib.util.spec_from_file_location("frozen_r1_features_for_input_only",R1)
    r1=importlib.util.module_from_spec(spec);sys.modules[spec.name]=r1;spec.loader.exec_module(r1)
    priced=pd.read_parquet(PRICES)
    assert priced.trade_date.max()==pd.Timestamp("2026-08-14")
    failures=pd.read_csv(HERE/"PARTIAL_2026_PRICE_SOURCE_GAPS.csv")
    boundary=pd.read_csv(HERE/"PARTIAL_2026_PRICE_BOUNDARY.csv")
    assert boundary.max_abs_error.max()==0
    pool=pd.read_csv(HERE/"QUARTER_POOL_PRICE_INVENTORY.csv")
    pool=pool.loc[pool.quarter.isin(["2025Q3","2025Q4","2026Q1"])].copy()
    old_dates=[]
    for year in (2025,2026):
        frame=pd.read_parquet(OLD_QFQ/f"year={year}/prices.parquet",columns=["ticker","trade_date"])
        old_dates.extend(pd.to_datetime(frame.loc[frame.ticker.eq("QQQ"),"trade_date"]).tolist())
    old_calendar=pd.DatetimeIndex(old_dates).unique().sort_values()
    later=pd.read_csv(CANON/"canonical_moomoo_ohlcv_daily_qfq.csv",usecols=["ticker","date"])
    canonical_calendar=pd.DatetimeIndex(pd.to_datetime(later.loc[later.ticker.eq("QQQ"),"date"]).unique()).sort_values()
    overlap=old_calendar[(old_calendar<="2026-07-14")&(old_calendar>="2025-06-01")]
    assert overlap.equals(canonical_calendar[canonical_calendar.isin(overlap)])
    calendar=canonical_calendar[(canonical_calendar>="2025-06-01")&(canonical_calendar<="2026-08-14")]
    features=r1.build_stock_state_features(priced[["ticker","trade_date","close","volume"]])
    features["signal_date"]=features.trade_date
    position=pd.Series(np.arange(len(calendar)),index=calendar)
    features["calendar_position"]=features.signal_date.map(position)
    features["position_120_prior"]=features.groupby("ticker").calendar_position.shift(120)
    features["required_observations"]=features.groupby("ticker").cumcount()+1
    features["lookback_eligible"]=(features.required_observations.ge(121)&features.calendar_position.notna()&
                                  features.position_120_prior.notna()&
                                  features.calendar_position.sub(features.position_120_prior).eq(120))
    features["all_features_available"]=np.isfinite(features[list(r1.FEATURE_COLUMNS)].to_numpy(float)).all(axis=1)
    status=features[["signal_date","ticker","lookback_eligible","all_features_available","required_observations"]]
    dates=calendar[calendar>="2026-01-02"]
    timing=pd.read_parquet(R1ROOT/"universe/quarterly_universe_manifest.parquet")
    timing=timing.loc[timing.quarter.isin(["2025Q3","2025Q4","2026Q1"]),["quarter","effective_date"]].sort_values("effective_date")
    active=pd.merge_asof(pd.DataFrame({"signal_date":dates}),timing,left_on="signal_date",right_on="effective_date",direction="backward")
    assert active.quarter.notna().all()
    candidates=active.merge(pool[["quarter","ticker","moomoo_transport_code"]],on="quarter",validate="many_to_many")
    candidates=candidates.merge(status,on=["signal_date","ticker"],how="left",validate="one_to_one")
    candidates["final_eligible"]=candidates.lookback_eligible.fillna(False)&candidates.all_features_available.fillna(False)
    coverage=candidates.groupby(["signal_date","quarter"],as_index=False).agg(
        original_pool_count=("ticker","size"),price_feature_eligible_count=("final_eligible","sum"))
    coverage.to_csv(HERE/"PARTIAL_2026_A2_ELIGIBILITY.csv",index=False)
    eligible=candidates.loc[candidates.final_eligible,["signal_date","quarter","ticker","moomoo_transport_code"]]
    matrix=eligible.merge(features.drop(columns=["trade_date"]),on=["signal_date","ticker"],validate="one_to_one")
    matrix["universe_size"]=matrix.groupby("signal_date").ticker.transform("size").astype(np.int32)
    model_path=R1ROOT/"A2/final_full_pre2026_hgb.joblib"
    model=joblib.load(model_path)
    matrix["a2_prediction"]=model.predict(matrix.loc[:,r1.FEATURE_COLUMNS].to_numpy(float))
    matrix["a2_rank"]=r1._prediction_rank(matrix,"a2_prediction")
    top=matrix.loc[matrix.a2_rank.le(20),["signal_date","quarter","ticker","moomoo_transport_code","universe_size","a2_prediction","a2_rank"]].copy()
    assert top.groupby("signal_date").size().eq(20).all()
    top.to_parquet(HERE/"PARTIAL_2026_A2_TOP20_INPUT_ONLY.parquet",index=False)
    result={"status":"PARTIAL_FROZEN_A2_INFERENCE_NO_POLICY_TEST","signal_start":str(top.signal_date.min().date()),
            "signal_end":str(top.signal_date.max().date()),"signal_days":int(top.signal_date.nunique()),
            "covered_quarters":{str(k):int(v) for k,v in coverage.quarter.value_counts().items()},
            "candidate_union_codes":int(pool.moomoo_transport_code.nunique()),
            "priced_codes":int(priced.moomoo_transport_code.nunique()),
            "source_gap_codes":len(failures),"frozen_boundary_codes_exact":len(boundary),
            "eligible_count_min":int(coverage.price_feature_eligible_count.min()),
            "eligible_count_max":int(coverage.price_feature_eligible_count.max()),
            "price_source_sha256":hashlib.sha256(PRICES.read_bytes()).hexdigest(),
            "model_fit_calls":0,"policy_outcomes_read":False,"formal_2026_reveals":0,
            "limit":"Partial signal inference stops at original raw cache last date; never a shortened formal policy test."}
    (HERE/"PARTIAL_2026_SIGNAL_AUDIT.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2))


def subscription_input_only():
    """Re-score the fixed candidate pool after the new Raw inputs; never run policies."""
    spec=importlib.util.spec_from_file_location("frozen_r1_features_subscription",R1)
    r1=importlib.util.module_from_spec(spec);sys.modules[spec.name]=r1;spec.loader.exec_module(r1)
    sources=[
        HERE/"PARTIAL_2026_ORIGINAL_REHAB_PRICES.parquet",
        HERE/"REUSED_2026_ADJUSTED_PRICE_INPUT_ONLY.parquet",
        HERE/"SUBSCRIPTION_2026_ADJUSTED_PRICE_INPUT_ONLY.parquet",
    ]
    pieces=[]
    for priority,path in enumerate(sources):
        frame=pd.read_parquet(path)
        frame["trade_date"]=pd.to_datetime(frame.trade_date)
        frame["_source_priority"]=priority
        pieces.append(frame)
    priced=(pd.concat(pieces,ignore_index=True)
            .sort_values(["moomoo_transport_code","trade_date","_source_priority"],kind="mergesort")
            .drop_duplicates(["moomoo_transport_code","trade_date"],keep="last")
            .drop(columns="_source_priority"))
    assert not priced.duplicated(["ticker","trade_date"]).any()
    calendar_frame=pd.read_csv(HERE/"SUBSCRIPTION_US_TRADING_DAYS.csv")
    calendar=pd.DatetimeIndex(pd.to_datetime(calendar_frame.time).unique()).sort_values()
    calendar=calendar[calendar<=pd.Timestamp("2026-09-22")]
    assert priced.trade_date.max()<=pd.Timestamp("2026-09-22")
    features=r1.build_stock_state_features(priced[["ticker","trade_date","close","volume"]])
    features["signal_date"]=features.trade_date
    position=pd.Series(np.arange(len(calendar)),index=calendar)
    features["calendar_position"]=features.signal_date.map(position)
    features["position_120_prior"]=features.groupby("ticker").calendar_position.shift(120)
    features["required_observations"]=features.groupby("ticker").cumcount()+1
    features["lookback_eligible"]=(features.required_observations.ge(121)&features.calendar_position.notna()&
                                  features.position_120_prior.notna()&
                                  features.calendar_position.sub(features.position_120_prior).eq(120))
    features["all_features_available"]=np.isfinite(features[list(r1.FEATURE_COLUMNS)].to_numpy(float)).all(axis=1)
    status=features[["signal_date","ticker","lookback_eligible","all_features_available","required_observations"]]
    dates=calendar[calendar>=pd.Timestamp("2026-01-02")]
    timing=pd.read_parquet(R1ROOT/"universe/quarterly_universe_manifest.parquet")
    timing=timing.loc[timing.quarter.isin(["2025Q3","2025Q4","2026Q1"]),
                      ["quarter","effective_date"]].copy()
    timing=pd.concat([timing,pd.DataFrame([{"quarter":"2026Q2","effective_date":"2026-08-21"}])],
                     ignore_index=True)
    timing["effective_date"]=pd.to_datetime(timing.effective_date)
    timing=timing.sort_values("effective_date")
    active=pd.merge_asof(pd.DataFrame({"signal_date":dates}),timing,left_on="signal_date",
                         right_on="effective_date",direction="backward")
    assert active.quarter.notna().all()
    pool=pd.read_csv(HERE/"QUARTER_POOL_PRICE_INVENTORY.csv")
    pool=pool.loc[pool.quarter.isin(["2025Q3","2025Q4","2026Q1","2026Q2"])]
    candidates=active.merge(pool[["quarter","ticker","moomoo_transport_code"]],on="quarter",
                            validate="many_to_many")
    candidates=candidates.merge(status,on=["signal_date","ticker"],how="left",validate="one_to_one")
    candidates["input_status"]=np.where(candidates.lookback_eligible.isna(),"NO_LOCAL_PRICE_SOURCE",
                           np.where(candidates.lookback_eligible.eq(True)&
                                    candidates.all_features_available.eq(True),"LOCAL_FEATURE_READY",
                                    "LOCAL_HISTORY_OR_RULE_INELIGIBLE"))
    candidates.to_csv(HERE/"SUBSCRIPTION_PARTIAL_A2_ELIGIBILITY_INPUT_ONLY.csv",index=False)
    eligible=candidates.loc[candidates.input_status.eq("LOCAL_FEATURE_READY"),
                            ["signal_date","quarter","ticker","moomoo_transport_code"]]
    matrix=eligible.merge(features.drop(columns="trade_date"),on=["signal_date","ticker"],
                          validate="one_to_one")
    matrix["universe_size"]=matrix.groupby("signal_date").ticker.transform("size").astype(np.int32)
    model=joblib.load(R1ROOT/"A2/final_full_pre2026_hgb.joblib")
    matrix["a2_prediction"]=model.predict(matrix.loc[:,r1.FEATURE_COLUMNS].to_numpy(float))
    matrix["a2_rank"]=r1._prediction_rank(matrix,"a2_prediction")
    top=matrix.loc[matrix.a2_rank.le(20),
                   ["signal_date","quarter","ticker","moomoo_transport_code",
                    "universe_size","a2_prediction","a2_rank"]].copy()
    assert top.groupby("signal_date").size().eq(20).all()
    top.to_parquet(HERE/"SUBSCRIPTION_PARTIAL_2026_A2_TOP20_INPUT_ONLY.parquet",index=False)
    previous=pd.read_parquet(HERE/"REUSED_RAW_PARTIAL_2026_A2_TOP20_INPUT_ONLY.parquet")
    changes=[]
    for day in sorted(set(top.signal_date)&set(previous.signal_date)):
        now=set(top.loc[top.signal_date.eq(day),"ticker"])
        before=set(previous.loc[previous.signal_date.eq(day),"ticker"])
        changes.append({"signal_date":str(pd.Timestamp(day).date()),"changed":now!=before,
                        "added":"|".join(sorted(now-before)),"removed":"|".join(sorted(before-now))})
    pd.DataFrame(changes).to_csv(HERE/"SUBSCRIPTION_PARTIAL_TOP20_DELTA.csv",index=False)
    counts=candidates.groupby("input_status").size().to_dict()
    audit={"status":"PARTIAL_FROZEN_A2_INFERENCE_NO_POLICY_TEST",
           "signal_days":int(top.signal_date.nunique()),
           "signal_start":str(top.signal_date.min().date()),
           "signal_end":str(top.signal_date.max().date()),
           "quarter_days":{str(k):int(v) for k,v in top.groupby("quarter").signal_date.nunique().items()},
           "candidate_union_codes":int(pool.moomoo_transport_code.nunique()),
           "priced_union_codes":int(priced.moomoo_transport_code.nunique()),
           "candidate_day_input_status_counts":{str(k):int(v) for k,v in counts.items()},
           "old_overlap_days":len(changes),
           "changed_top20_days":sum(x["changed"] for x in changes),
           "all_days_full_pool_qualified":False,
           "fixed_test_asof":"2026-09-23T18:40:43Z",
           "model_fit_calls":0,"policy_outcomes_read":False,"formal_2026_reveals":0}
    (HERE/"SUBSCRIPTION_PARTIAL_A2_INFERENCE_AUDIT.json").write_text(
        json.dumps(audit,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(audit))


def remaining75_authority_input_only():
    """Apply evidenced identity intervals to the fixed pool, then infer without fitting."""
    spec=importlib.util.spec_from_file_location("frozen_r1_features_remaining75",R1)
    r1=importlib.util.module_from_spec(spec);sys.modules[spec.name]=r1;spec.loader.exec_module(r1)
    source_files=[
        HERE/"PARTIAL_2026_ORIGINAL_REHAB_PRICES.parquet",
        HERE/"REUSED_2026_ADJUSTED_PRICE_INPUT_ONLY.parquet",
        HERE/"SUBSCRIPTION_2026_ADJUSTED_PRICE_INPUT_ONLY.parquet",
        HERE/"AUTHORITY_ALIAS_ADJUSTED_PRICE_INPUT_ONLY.parquet",
        HERE/"OFFICIAL_COMMON_ALIAS_ADJUSTED_PRICE_INPUT_ONLY.parquet",
    ]
    aliases={
        "BGNE":("US.ONC","2025-01-02"),"BLDE":("US.SRTA","2025-08-29"),
        "BSIG":("US.AAMI","2025-01-02"),"AZNCF":("US.AZN","2026-02-02"),
        "LLYVB":("US.LLYVK","2025-12-16"),"MSTLW":("US.MS","2025-06-01"),
        "CBDY":("US.TGT","2025-06-01"),"GE.WI":("US.GE","2024-04-02"),
        "DTP":("US.DTE","2025-06-01"),"LILAB":("US.LILA","2025-06-01"),
    }
    pieces=[]
    for priority,path in enumerate(source_files):
        frame=pd.read_parquet(path)
        frame["trade_date"]=pd.to_datetime(frame.trade_date)
        if priority==3:
            # AZN ordinary-share line and LLYVK spun-off Series C need their own
            # proved continuity window; vendor backfill before it is not prewarm.
            frame=frame.loc[~(frame.ticker.eq("AZNCF")&frame.trade_date.lt("2026-02-02"))]
            frame=frame.loc[~(frame.ticker.eq("LLYVB")&frame.trade_date.lt("2025-12-16"))]
        frame["_priority"]=priority
        pieces.append(frame)
    priced=(pd.concat(pieces,ignore_index=True)
            .sort_values(["ticker","trade_date","_priority"],kind="mergesort")
            .drop_duplicates(["ticker","trade_date"],keep="last")
            .drop(columns="_priority"))
    assert not priced.duplicated(["ticker","trade_date"]).any()
    assert priced.trade_date.max()<=pd.Timestamp("2026-09-22")
    calendar=pd.DatetimeIndex(
        pd.to_datetime(pd.read_csv(HERE/"SUBSCRIPTION_US_TRADING_DAYS.csv").time).unique()).sort_values()
    calendar=calendar[calendar<=pd.Timestamp("2026-09-22")]
    features=r1.build_stock_state_features(priced[["ticker","trade_date","close","volume"]])
    features["signal_date"]=features.trade_date
    position=pd.Series(np.arange(len(calendar)),index=calendar)
    features["calendar_position"]=features.signal_date.map(position)
    features["position_120_prior"]=features.groupby("ticker").calendar_position.shift(120)
    features["required_observations"]=features.groupby("ticker").cumcount()+1
    features["lookback_eligible"]=(features.required_observations.ge(121)&
                                  features.calendar_position.notna()&
                                  features.position_120_prior.notna()&
                                  features.calendar_position.sub(features.position_120_prior).eq(120))
    features["all_features_available"]=np.isfinite(features[list(r1.FEATURE_COLUMNS)].to_numpy(float)).all(axis=1)
    status=features[["signal_date","ticker","lookback_eligible","all_features_available","required_observations"]]
    timing=pd.read_parquet(R1ROOT/"universe/quarterly_universe_manifest.parquet")
    timing=timing.loc[timing.quarter.isin(["2025Q3","2025Q4","2026Q1"]),
                      ["quarter","effective_date"]].copy()
    timing=pd.concat([timing,pd.DataFrame([{"quarter":"2026Q2","effective_date":"2026-08-21"}])],
                     ignore_index=True)
    timing["effective_date"]=pd.to_datetime(timing.effective_date)
    active=pd.merge_asof(
        pd.DataFrame({"signal_date":calendar[calendar>=pd.Timestamp("2026-01-02")]}),
        timing.sort_values("effective_date"),left_on="signal_date",
        right_on="effective_date",direction="backward")
    assert active.quarter.notna().all()
    pool=pd.read_csv(HERE/"QUARTER_POOL_PRICE_INVENTORY.csv")
    pool=pool.loc[pool.quarter.isin(["2025Q3","2025Q4","2026Q1","2026Q2"])]
    candidates=active.merge(pool[["quarter","ticker","moomoo_transport_code"]],
                            on="quarter",validate="many_to_many")
    candidates=candidates.merge(status,on=["signal_date","ticker"],how="left",
                                validate="one_to_one")
    candidates["daily_status"]=np.where(candidates.lookback_eligible.isna(),
        "UNKNOWN_NO_LOCAL_PRICE",np.where(candidates.lookback_eligible.eq(True)&
        candidates.all_features_available.eq(True),"PRICE_FEATURE_READY_INPUT_ONLY",
        "UNKNOWN_LOCAL_HISTORY_OR_FEATURE"))
    cases_root=Path(r"D:\us-tech-quant-results\massive_r3_remaining31_external_authority_r2\20260903T131804Z")
    uid_root=Path(r"D:\us-tech-quant-results\permanent_security_uid_authority_policy_r1\20260903T154404Z")
    authority=pd.read_csv(cases_root/"tables/external_identity_authority.csv",
                          dtype={"input_security_key":str})
    verified_bodies=0
    for row in authority.itertuples(index=False):
        paths=str(row.evidence_paths).split(";")
        hashes=str(row.evidence_sha256s).split(";")
        assert len(paths)==len(hashes)
        for path,want in zip(paths,hashes):
            assert hashlib.sha256((cases_root/path).read_bytes()).hexdigest()==want
            verified_bodies+=1
    closures=pd.read_csv(uid_root/"tables/lifecycle_uid_closures.csv",dtype={"cusip":str})
    ends=dict(zip(closures.ticker,closures.effective_end_exclusive))
    ends["NUVL"]="2026-07-15"
    targeted_closures={
        "IAS":("2025-12-24","https://www.sec.gov/Archives/edgar/data/1842718/000114036125046475/ef20061707_ex99-1.htm"),
        "SPNS":("2025-12-17","https://www.sec.gov/Archives/edgar/data/885740/000121390025122732/ea0269665-6k_sapiens.htm"),
        "EXAS":("2026-03-23","https://www.sec.gov/Archives/edgar/data/1124140/000119312526118700/d128802d8k.htm"),
        "COOP":("2025-10-01","https://www.sec.gov/Archives/edgar/data/933136/000095014225002623/eh250686104_8k.htm"),
        "VRNA":("2025-10-07","https://www.sec.gov/Archives/edgar/data/1657312/000110465925097318/tm2528100d1_8k.htm"),
        "IPG":("2025-11-28","https://www.sec.gov/Archives/edgar/data/51644/000119312525300704/d89931d8k.htm"),
        "K":("2025-12-11","https://www.sec.gov/Archives/edgar/data/55067/000119312525315130/d90636d8k.htm"),
        "HBI":("2025-12-02","https://www.sec.gov/Archives/edgar/data/1359841/000119312525303276/d848051d8k.htm"),
        "VMEO":("2025-11-24","https://www.sec.gov/Archives/edgar/data/1837686/000110465925115501/tm2532050d1_8k.htm"),
    }
    ends.update({ticker:end for ticker,(end,_) in targeted_closures.items()})
    for ticker,end in ends.items():
        mask=candidates.ticker.eq(ticker)&candidates.signal_date.ge(pd.Timestamp(end))
        candidates.loc[mask,"daily_status"]="PROVEN_LIFECYCLE_INELIGIBLE"
    # The CUSIP 530909308 Series C first traded on 2025-12-16 after the
    # split-off. Earlier namesake LLYVK history is a different issuer/issue.
    llyvk_first=calendar.get_loc(pd.Timestamp("2025-12-16"))
    llyvk_121st=calendar[llyvk_first+120]
    candidates.loc[candidates.ticker.eq("LLYVB") &
                   candidates.signal_date.lt(llyvk_121st),
                   "daily_status"]="PROVEN_ORIGINAL_121_INELIGIBLE"
    official_121_starts={
        "FPS":("34631F102","COM SHS CL A","2026-02-05",
               "https://www.sec.gov/Archives/edgar/data/2080126/000119312526043650/d23417dex991.htm"),
        "MANE":("922967104","COMMON STOCK","2026-02-04",
                "https://veradermics.gcs-web.com/static-files/2e01cff2-a884-4d1d-a167-7805968799c3"),
        "PAYP":("70450C101","SPONSORED ADS","2026-03-12",
                "https://www.sec.gov/Archives/edgar/data/2080845/000119312526130285/d40327dex991.htm"),
        "SUNB":("866966104","SHS","2026-03-02",
                "https://www.sec.gov/Archives/edgar/data/2083785/000119312526085376/d121042d8k.htm"),
    }
    official_121_audit=[{"ticker":"LLYVB","original_cusip":"530909308",
                         "original_share_class":"COM SHS SER C",
                         "first_trade":"2025-12-16",
                         "first_eligible_session":str(llyvk_121st.date()),
                         "official_source":"https://www.sec.gov/Archives/edgar/data/2078416/000110465925121239/tm2533349d1_ex99-1.htm"}]
    original_121_source=pd.read_parquet(R1ROOT/"universe/quarterly_universe_members.parquet")
    for ticker,(cusip,share_class,first_trade,_) in official_121_starts.items():
        source=original_121_source.loc[original_121_source.ticker.eq(ticker)&
                                         original_121_source.quarter.eq("2026Q1")]
        assert len(source) and set(source.cusip.astype(str))=={cusip}
        assert set(source.title_of_class.astype(str))=={share_class}
        first_index=calendar.get_loc(pd.Timestamp(first_trade))
        first_eligible=calendar[first_index+120]
        official_121_audit.append({"ticker":ticker,"original_cusip":cusip,
                                   "original_share_class":share_class,
                                   "first_trade":first_trade,
                                   "first_eligible_session":str(first_eligible.date()),
                                   "official_source":official_121_starts[ticker][3]})
        candidates.loc[candidates.ticker.eq(ticker)&
                       candidates.signal_date.lt(first_eligible),
                       "daily_status"]="PROVEN_ORIGINAL_121_INELIGIBLE"
    for ticker in ("AZNCF","LLYVB"):
        start=pd.Timestamp(aliases[ticker][1])
        mask=(candidates.ticker.eq(ticker)&candidates.signal_date.ge(start)&
              candidates.daily_status.ne("PRICE_FEATURE_READY_INPUT_ONLY")&
              candidates.daily_status.ne("PROVEN_ORIGINAL_121_INELIGIBLE"))
        candidates.loc[mask,"daily_status"]="UNKNOWN_IDENTITY_PREWARM"
    candidates["resolved_transport_code"]=candidates.ticker.map(
        {ticker:alias[0] for ticker,alias in aliases.items()}).fillna(candidates.moomoo_transport_code)
    eligible=candidates.loc[candidates.daily_status.eq("PRICE_FEATURE_READY_INPUT_ONLY"),
                            ["signal_date","quarter","ticker","moomoo_transport_code","resolved_transport_code"]]
    matrix=eligible.merge(features.drop(columns="trade_date"),on=["signal_date","ticker"],
                          validate="one_to_one")
    matrix["universe_size"]=matrix.groupby("signal_date").ticker.transform("size").astype(np.int32)
    model=joblib.load(R1ROOT/"A2/final_full_pre2026_hgb.joblib")
    matrix["a2_prediction"]=model.predict(matrix.loc[:,r1.FEATURE_COLUMNS].to_numpy(float))
    matrix["a2_rank"]=r1._prediction_rank(matrix,"a2_prediction")
    top=matrix.loc[matrix.a2_rank.le(20),
                   ["signal_date","quarter","ticker","moomoo_transport_code",
                    "resolved_transport_code","universe_size","a2_prediction","a2_rank"]].copy()
    assert top.groupby("signal_date").size().eq(20).all()
    top.to_parquet(HERE/"REMAINING75_PARTIAL_2026_A2_TOP20_INPUT_ONLY.parquet",index=False)
    previous=pd.read_parquet(HERE/"SUBSCRIPTION_PARTIAL_2026_A2_TOP20_INPUT_ONLY.parquet")
    changed=sum(set(top.loc[top.signal_date.eq(day),"ticker"])!=
                set(previous.loc[previous.signal_date.eq(day),"ticker"])
                for day in sorted(set(top.signal_date)&set(previous.signal_date)))
    original=pd.concat([
        pd.read_parquet(R1ROOT/"universe/quarterly_universe_members.parquet")
          .loc[lambda d:d.quarter.isin(["2025Q3","2025Q4","2026Q1"])],
        pd.read_parquet(HERE/"Q2_ORIGINAL24_INITIAL_CANDIDATES.parquet"),
    ],ignore_index=True)
    gap=pd.read_csv(HERE/"SUBSCRIPTION_REMAINING_ACTIVE_PRICE_GAPS.csv")
    source_index=pd.read_parquet(
        r"D:\us-tech-quant-results\13f_pit_v1\data\universe\security_identity_v17c_transport.parquet")
    prior_provider={}
    for receipt_name in ("SUBSCRIPTION_BATCH_RECEIPT.json",
                         "SUBSCRIPTION_TARGETED_RECEIPT.json"):
        receipt=json.loads((HERE/receipt_name).read_text(encoding="utf-8"))
        prior_provider.update({r["code"]:(r["status"],receipt_name)
                               for r in receipt["records"]})
    alias_audit=json.loads((HERE/"AUTHORITY_ALIAS_ADJUSTED_PRICE_AUDIT.json").read_text(encoding="utf-8"))
    alias_raw={x["original_ticker"]:x for x in alias_audit["records"]}
    common_audit=json.loads((HERE/"OFFICIAL_COMMON_ALIAS_ADJUSTED_PRICE_AUDIT.json").read_text(encoding="utf-8"))
    alias_raw.update({x["original_ticker"]:x for x in common_audit["records"]})
    def intervals(group):
        values=[]
        for state,chunk in group.sort_values("signal_date").groupby(
                (group.sort_values("signal_date").daily_status!=
                 group.sort_values("signal_date").daily_status.shift()).cumsum(),sort=False):
            values.append(f"{chunk.signal_date.min().date()}..{chunk.signal_date.max().date()}:{chunk.daily_status.iloc[0]}")
        return "|".join(values)
    records=[]
    for code,part in gap.groupby("code",sort=False):
        ticker=str(part.ticker.iloc[0])
        sub=candidates.loc[candidates.moomoo_transport_code.eq(code)].sort_values("signal_date")
        assert len(sub)
        original_rows=original.loc[original.moomoo_transport_code.eq(code)]
        cusips=sorted(set(original_rows.cusip.astype(str)))
        classes=sorted(set(original_rows.title_of_class.astype(str)))
        issuers=sorted(set(original_rows.issuer_name.astype(str)))
        case=authority.loc[authority.input_ticker.eq(ticker)]
        hit=len(case)==1 and set(cusips)=={str(case.iloc[0].input_security_key)}
        if len(case):
            assert hit, f"CASE_CUSIP_CONFLICT:{ticker}"
            ref=str(case.iloc[0].evidence_paths)
            ref_hash=str(case.iloc[0].evidence_sha256s)
            kind=str(case.iloc[0].authority_result_class)
            case_id=str(case.iloc[0].authority_candidate_id)
            share_check=str(case.iloc[0].condition_d_venue_and_class)
            earlier_ticker_cusip={
                "MSTLW":"https://www.sec.gov/Archives/edgar/data/1848433/000106299325002390/xslForm13F_X02/form13fInfoTable.xml",
                "CBDY":"https://www.sec.gov/Archives/edgar/data/714364/000071436425000003/xslForm13F_X02/Ogorek_Holdings_13F_2025Q1.xml",
            }
            if ticker in earlier_ticker_cusip:
                ref+=";"+earlier_ticker_cusip[ticker]
                ref_hash+=";WEB_OFFICIAL_NO_LOCAL_HASH"
        elif ticker=="NUVL":
            ref=("https://www.sec.gov/Archives/edgar/data/1861560/000119312526304126/d52896d8k.htm;"
                 "https://www.sec.gov/Archives/edgar/data/1861560/000119312526300297/d101813dsc14d9a.htm")
            ref_hash="WEB_OFFICIAL_NO_LOCAL_HASH"
            kind="TARGETED_OFFICIAL_LIFECYCLE"
            case_id=""
            share_check="CLASS_A_CUSIP_670703107_SOURCE"
        elif ticker in targeted_closures:
            ref=targeted_closures[ticker][1]
            ref_hash="WEB_OFFICIAL_NO_LOCAL_HASH"
            kind="TARGETED_OFFICIAL_LIFECYCLE"
            case_id=""
            share_check="ORIGINAL_13F_CUSIP_CLASS_AND_ISSUER_CLOSURE_MATCH"
        elif ticker=="GE.WI":
            ref=("https://www.ge.com/news/press-releases/ge-board-of-directors-approves-spin-off-of-ge-vernova-ge-vernova-and-ge-aerospace-to;"
                 "https://www.sec.gov/Archives/edgar/data/40545/000031506626001191/xslSCHEDULE_13G_X02/primary_doc.xml")
            ref_hash="WEB_OFFICIAL_NO_LOCAL_HASH"
            kind="TARGETED_OFFICIAL_TICKER_CONTINUITY"
            case_id=""
            share_check="CUSIP_369604301_GE_COMMON"
        elif ticker=="AVB":
            ref=("https://www.sec.gov/Archives/edgar/data/102909/000010290926000773/xslSCHEDULE_13G_X02/primary_doc.xml;"
                 "https://investors.avalonbay.com/sec-filings/all-sec-filings/content/0001104659-26-039983/0001104659-26-039983.pdf")
            ref_hash="WEB_OFFICIAL_NO_LOCAL_HASH"
            kind="TARGETED_OFFICIAL_ACTIVE_PRICE_GAP"
            case_id=""
            share_check="CUSIP_053484101_NYSE_AVB_COMMON"
        elif ticker=="DTP":
            ref=("https://www.sec.gov/Archives/edgar/data/936340/000119312519278848/d813800d424b2.htm;"
                 "https://investor.bankofamerica.com/regulatory-and-other-filings/all-sec-filings/content/0000070858-25-000229/0000070858-25-000229.pdf")
            ref_hash="WEB_OFFICIAL_NO_LOCAL_HASH"
            kind="TARGETED_OFFICIAL_COMMON_SHARE_TRANSPORT"
            case_id=""
            share_check="ORIGINAL_233331107_COM_IS_DTE_NOT_DTP_CORPORATE_UNITS"
        elif ticker=="LILAB":
            ref=("https://www.sec.gov/Archives/edgar/data/1712184/000119312521017828/d940947dsc13ga.htm;"
                 "https://www.sec.gov/Archives/edgar/data/1712184/000171218425000168/lila-20251010.htm")
            ref_hash="WEB_OFFICIAL_NO_LOCAL_HASH"
            kind="TARGETED_OFFICIAL_CLASS_A_TRANSPORT"
            case_id=""
            share_check="ORIGINAL_G9001E102_COM_CL_A_IS_LILA_NOT_LILAB_CLASS_B"
        else:
            ref=r"D:\us-tech-quant-results\13f_pit_v1\data\universe\security_identity_v17c_transport.parquet"
            ref_hash="LOCAL_INDEX_IDENTITY_ONLY"
            kind="NO_MATCHING_R31_CASE"
            case_id=""
            share_check="IDENTITY_INDEX_ONLY"
        index_rows=source_index.loc[source_index.ticker.eq(ticker)]
        if len(case)==0 and ticker not in ("NUVL","GE.WI"):
            assert set(cusips).issubset(set(index_rows.cusip.astype(str))),f"INDEX_CUSIP_CONFLICT:{ticker}"
        ready=int(sub.daily_status.eq("PRICE_FEATURE_READY_INPUT_ONLY").sum())
        exited=int(sub.daily_status.eq("PROVEN_LIFECYCLE_INELIGIBLE").sum())
        rule121=int(sub.daily_status.eq("PROVEN_ORIGINAL_121_INELIGIBLE").sum())
        unknown=len(sub)-ready-exited-rule121
        end=ends.get(ticker,"")
        possible_settlement=bool(end and sub.signal_date.min()<pd.Timestamp(end) and
                                 sub.signal_date.max()>=pd.Timestamp(end))
        if ticker in alias_raw:
            raw_first=alias_raw[ticker]["raw_first"];raw_last=alias_raw[ticker]["raw_last"]
        else:
            raw_first="";raw_last=str(part.raw_last_date.dropna().max()) if part.raw_last_date.notna().any() else ""
        records.append({
            "original_code":code,"original_ticker":ticker,"original_cusip":"|".join(cusips),
            "original_issuer_name":"|".join(issuers),
            "original_share_class":"|".join(classes),
            "active_quarters":"|".join(sorted(set(part.quarter))),
            "r31_case_id":case_id,"case_kind":kind,"cusip_match":bool(hit),
            "share_class_check":share_check,"evidence_refs":ref,"evidence_sha256s":ref_hash,
            "index_multiclass_transport_collision":len(set(index_rows.cusip.astype(str)))>1,
            "identity_index_cusip_class_rows":int(len(index_rows.loc[
                index_rows.cusip.astype(str).isin(cusips)&
                index_rows.title_of_class.astype(str).str.replace(r"\s+"," ",regex=True).str.strip().isin(
                    {c.strip() for c in classes})])),
            "prior_provider_status":prior_provider.get(code,("NOT_REQUESTED", ""))[0],
            "prior_provider_receipt":prior_provider.get(code,("", ""))[1],
            "identity_evidence_start":aliases[ticker][1] if ticker in aliases else "",
            "lifecycle_end_exclusive":end,
            "lifecycle_end_basis":(
                "CONSERVATIVE_NEXT_DAY_AFTER_2025_12_01_COMPLETED_MERGER" if ticker=="HBI"
                else "TARGETED_OFFICIAL_REPORT" if ticker in targeted_closures or ticker=="NUVL"
                else "R31_EFFECTIVE_DATED_UID_POLICY" if ticker in ends else ""),
            "correct_transport":aliases[ticker][0] if ticker in aliases else code,
            "transport_evidence_level":("OFFICIAL_CUSIP_CLASS_ALIAS" if ticker in ("DTP","LILAB","GE.WI")
                                       else "R31_UID_AUTHORITY" if ticker in aliases
                                       else "LIFECYCLE_ONLY" if ticker in ends
                                       else "LOCAL_IDENTITY_INDEX_ONLY"),
            "raw_first":raw_first,"raw_last":raw_last,
            "candidate_days":len(sub),"price_feature_ready_input_only_days":ready,
            "proven_lifecycle_ineligible_days":exited,"proven_121_ineligible_days":rule121,
            "unknown_days":unknown,
            "daily_status_intervals":intervals(sub),
            "still_needed_signal_dates":"|".join(str(x.date()) for x in
                sub.loc[~sub.daily_status.isin(
                    ["PRICE_FEATURE_READY_INPUT_ONLY","PROVEN_LIFECYCLE_INELIGIBLE",
                     "PROVEN_ORIGINAL_121_INELIGIBLE"]),"signal_date"]),
            "possible_held_settlement_dependency":possible_settlement,
            "candidate_comparison_resolved":unknown==0,
            "resolution_status":("CANDIDATE_RESOLVED_SETTLEMENT_CHECK_PENDING" if unknown==0 and possible_settlement
                                 else "CANDIDATE_RESOLVED_INPUT_VERSION_CHECK_PENDING" if unknown==0
                                 else "UNKNOWN_PRICE_OR_IDENTITY_PREWARM"),
        })
    resolution=pd.DataFrame(records).sort_values("original_code")
    assert len(resolution)==75 and resolution.original_code.nunique()==75
    resolution.to_csv(HERE/"REMAINING75_RESOLUTION.csv",index=False)
    unknown_mask=~candidates.daily_status.isin(
        ["PRICE_FEATURE_READY_INPUT_ONLY","PROVEN_LIFECYCLE_INELIGIBLE",
         "PROVEN_ORIGINAL_121_INELIGIBLE"])
    outside=candidates.loc[unknown_mask & ~candidates.moomoo_transport_code.isin(
        resolution.original_code)]
    outside_keys=[{"quarter":quarter,"ticker":ticker,"code":code,"daily_status":state,
                   "days":int(len(rows)),"first_date":str(rows.signal_date.min().date()),
                   "last_date":str(rows.signal_date.max().date()),
                   "official_121_source":official_121_starts[ticker][3] if ticker in official_121_starts else "",
                   "signal_dates":[str(x.date()) for x in rows.signal_date]}
                  for (quarter,ticker,code,state),rows in outside.groupby(
                      ["quarter","ticker","moomoo_transport_code","daily_status"],sort=True)]
    assert int(resolution.unknown_days.sum())+len(outside)==int(unknown_mask.sum())
    q2_unknown=sorted(candidates.loc[
        candidates.quarter.eq("2026Q2") &
        ~candidates.daily_status.isin(["PRICE_FEATURE_READY_INPUT_ONLY",
                                      "PROVEN_LIFECYCLE_INELIGIBLE",
                                      "PROVEN_ORIGINAL_121_INELIGIBLE"]),"ticker"].unique().tolist())
    unknown_by_day=candidates.groupby("signal_date").daily_status.apply(
        lambda s:int((~s.isin(["PRICE_FEATURE_READY_INPUT_ONLY",
                               "PROVEN_LIFECYCLE_INELIGIBLE",
                               "PROVEN_ORIGINAL_121_INELIGIBLE"])).sum()))
    midsummer=candidates.loc[candidates.signal_date.between(
        "2026-07-27","2026-08-20")].copy()
    mid_unknown=midsummer.loc[~midsummer.daily_status.isin(
        ["PRICE_FEATURE_READY_INPUT_ONLY","PROVEN_LIFECYCLE_INELIGIBLE",
         "PROVEN_ORIGINAL_121_INELIGIBLE"])]
    mid_daily=mid_unknown.groupby("signal_date").size()
    audit={"fixed_test_asof":"2026-09-23T18:40:43Z",
           "r31_case_name_and_original_cusip_matches":int(resolution.r31_case_id.ne("").sum()),
           "r31_source_bodies_hash_verified":verified_bodies,
           "targeted_non_r31_official_lifecycle_cases":len(targeted_closures)+1,
           "gap_codes":len(resolution),
           "candidate_resolved_codes":int(resolution.candidate_comparison_resolved.sum()),
           "candidate_resolved_r31_cases":int((resolution.r31_case_id.ne("") & resolution.candidate_comparison_resolved).sum()),
           "candidate_resolved_non_r31_codes":int((resolution.r31_case_id.eq("") & resolution.candidate_comparison_resolved).sum()),
           "fully_proven_lifecycle_ineligible_codes":int((resolution.proven_lifecycle_ineligible_days.eq(resolution.candidate_days)).sum()),
           "remaining_unknown_codes":int(resolution.unknown_days.gt(0).sum()),
           "remaining75_unknown_candidate_days":int(resolution.unknown_days.sum()),
           "outside_remaining75_unknown_candidate_days":int(len(outside)),
           "outside_remaining75_unknown_keys":outside_keys,
           "official_121_ineligibility_sources":official_121_audit,
           "candidate_state_complete_days_not_full_test_input":int(unknown_by_day.eq(0).sum()),
           "july27_aug20_separate_qualification":{
               "signal_days":int(midsummer.signal_date.nunique()),
               "remaining75_unknown_rows":int(mid_unknown.moomoo_transport_code.isin(
                   resolution.original_code).sum()),
               "outside75_unknown_rows":int((~mid_unknown.moomoo_transport_code.isin(
                   resolution.original_code)).sum()),
               "unknown_codes":sorted(mid_unknown.ticker.unique().tolist()),
               "daily_unknown_min":int(mid_daily.min()) if len(mid_daily) else 0,
               "daily_unknown_max":int(mid_daily.max()) if len(mid_daily) else 0,
               "pit_version_qualification":"ONLY_CONSUMED_EVENT_VERSIONS_NOT_YET_CERTIFIED_AT_TEST_ASOF",
               "accounting_settlement_qualification":"NOT_EVALUATED_NO_FORMAL_CONTINUOUS_PATH"},
           "q2_unknown_codes":q2_unknown,
           "fully_qualified_comparison_days":int(unknown_by_day.eq(0).sum()),
           "unknown_candidates_per_day_min":int(unknown_by_day.min()),
           "unknown_candidates_per_day_max":int(unknown_by_day.max()),
           "partial_inference_days":int(top.signal_date.nunique()),
           "changed_top20_days_vs_prior_local_cache":int(changed),
           "price_feature_ready_candidate_days":int(candidates.daily_status.eq("PRICE_FEATURE_READY_INPUT_ONLY").sum()),
           "proven_lifecycle_ineligible_candidate_days":int(candidates.daily_status.eq("PROVEN_LIFECYCLE_INELIGIBLE").sum()),
           "proven_121_ineligible_candidate_days":int(candidates.daily_status.eq("PROVEN_ORIGINAL_121_INELIGIBLE").sum()),
           "unknown_candidate_days":int(unknown_mask.sum()),
           "formal_2026_test_reveals":0,"a2_fit_calls":0,
           "limit":"Input-only evidence resolution; post-ASOF rehab versions and held exit accounting remain separate qualification gates."}
    (HERE/"REMAINING75_INPUT_AUDIT.json").write_text(json.dumps(audit,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(audit))


if __name__=="__main__":
    if "--remaining75" in sys.argv[1:]:
        remaining75_authority_input_only()
    elif "--subscription" in sys.argv[1:]:
        subscription_input_only()
    else:
        main()
