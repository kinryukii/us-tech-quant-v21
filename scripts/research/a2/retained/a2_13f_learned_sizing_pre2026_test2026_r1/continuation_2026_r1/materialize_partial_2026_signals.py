"""Frozen A2 inference only for dates supported by original raw+rehab inputs.

The full TEST_ASOF policy test is intentionally not run by this script.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
R1ROOT = Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1")
PRODUCER = R1ROOT / "scripts/run_rebuild.py"
R1 = Path(r"D:\us-tech-quant\scripts\v22\abcde_a2_r1_nonlinear_cross_sectional_modeling.py")
R0F1 = Path(r"D:\us-tech-quant\scripts\v22\fast_a2_r0f1_corporate_action_accounting_repair_and_exact_r4_rerun.py")
REHAB = Path(r"D:\us-tech-quant-cache\13f_pit_v1\a_a2_quarterly_13f_r1\rehab_factors.parquet")
STATUS = Path(r"D:\us-tech-quant-cache\13f_pit_v1\a_a2_quarterly_13f_r1\rehab_status.csv")
OLD_SURFACE = Path(r"D:\us-tech-quant-results\A2_PRE2026_RAW_MOOMOO_REHAB_BUILDER_R2\surface_manifest.json")
OLD_QFQ = Path(r"D:\us-tech-quant-data\moomoo\source\prices_qfq")
CANON = Path(r"D:\us-tech-quant-data\canonical\moomoo_ohlcv\snapshot_id=data_layer_20260911_99642e55d6185fe2402b")
LAST_RAW_DATE = pd.Timestamp("2026-08-14")


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main():
    producer = load("original_r1_producer_for_2026_only", PRODUCER)
    r1 = load("frozen_r1_features_for_2026_only", R1)
    r0f1 = load("frozen_r0f1_wolf_evidence", R0F1)
    producer.END_EXCLUSIVE = LAST_RAW_DATE + pd.Timedelta(days=1)
    wolf = [r for r in r0f1.frozen_evidence_records() if r["ticker"] == "WOLF"][0]
    pool = pd.read_csv(HERE / "QUARTER_POOL_PRICE_INVENTORY.csv")
    pool = pool.loc[pool.quarter.isin(["2025Q3", "2025Q4", "2026Q1"])].copy()
    code_ticker = pool[["moomoo_transport_code", "ticker"]].drop_duplicates()
    index, failures = producer.raw_file_index()
    assert not failures and code_ticker.groupby("moomoo_transport_code").ticker.nunique().max() == 1
    status = pd.read_csv(STATUS)
    good_rehab = set(status.loc[status.status.eq("PASS"), "code"])
    rehab = pd.read_parquet(REHAB)
    manifest = json.loads(OLD_SURFACE.read_text(encoding="utf-8"))
    frozen_codes = set(manifest["materialized_transport_codes"])
    old_last = []
    for part in manifest["partitions"]:
        requested = set(part["codes"]) & set(code_ticker.moomoo_transport_code)
        if requested:
            frame = pd.read_parquet(Path(manifest["surface_path"]) / part["relative_path"],
                                    filters=[("moomoo_transport_code", "in", sorted(requested))])
            old_last.append(frame.loc[pd.to_datetime(frame.trade_date).eq("2025-12-31"),
                                      ["moomoo_transport_code", "open", "close", "high", "low", "volume"]])
    old_boundary = pd.concat(old_last, ignore_index=True).set_index("moomoo_transport_code")
    prices = []
    errors = []
    boundary = []
    for n,row in enumerate(code_ticker.itertuples(index=False),1):
        code,ticker = row.moomoo_transport_code,row.ticker
        if code not in index:
            errors.append({"code":code,"ticker":ticker,"reason":"NO_ORIGINAL_RAW_FILE"});continue
        if code not in good_rehab:
            errors.append({"code":code,"ticker":ticker,"reason":"REHAB_STATUS_NOT_PASS"});continue
        try:
            raw = producer.load_raw_code(code, index[code])
            raw = raw.loc[raw.trade_date.le(LAST_RAW_DATE)]
            if raw.empty:
                errors.append({"code":code,"ticker":ticker,"reason":"NO_RAW_BEFORE_CUTOFF"});continue
            adjusted, _ = producer.adjusted_price_frame(code,ticker,raw,rehab,wolf)
            if code in frozen_codes and code in old_boundary.index:
                reference = old_boundary.loc[code]
                actual = adjusted.loc[adjusted.trade_date.eq("2025-12-31")]
                if len(actual) != 1:
                    raise RuntimeError("FROZEN_BOUNDARY_DATE_MISSING")
                max_error = max(abs(float(actual[c].iloc[0]) - float(reference[c])) for c in ("open","close","high","low","volume"))
                if max_error > 1e-9:
                    raise RuntimeError(f"FROZEN_BOUNDARY_MISMATCH:{max_error}")
                boundary.append({"code":code,"ticker":ticker,"max_abs_error":max_error})
            prices.append(adjusted.loc[adjusted.trade_date.ge("2025-06-01")])
        except Exception as exc:
            errors.append({"code":code,"ticker":ticker,"reason":type(exc).__name__+":"+str(exc)[:180]})
        if n%100==0:print(f"processed {n}/{len(code_ticker)}",flush=True)
    assert prices
    priced = pd.concat(prices,ignore_index=True).sort_values(["ticker","trade_date"],kind="mergesort")
    assert not priced.duplicated(["ticker","trade_date"]).any()
    priced.to_parquet(HERE / "PARTIAL_2026_ORIGINAL_REHAB_PRICES.parquet",index=False)
    pd.DataFrame(errors).to_csv(HERE / "PARTIAL_2026_PRICE_SOURCE_GAPS.csv",index=False)
    pd.DataFrame(boundary).to_csv(HERE / "PARTIAL_2026_PRICE_BOUNDARY.csv",index=False)
    old_calendar=[]
    for year in (2025,2026):
        frame=pd.read_parquet(OLD_QFQ / f"year={year}/prices.parquet",columns=["ticker","trade_date"])
        old_calendar.extend(pd.to_datetime(frame.loc[frame.ticker.eq("QQQ"),"trade_date"]).tolist())
    old_calendar=pd.DatetimeIndex(old_calendar).unique().sort_values()
    later=pd.read_csv(CANON / "canonical_moomoo_ohlcv_daily_qfq.csv",usecols=["ticker","date"])
    canonical_calendar=pd.DatetimeIndex(pd.to_datetime(later.loc[later.ticker.eq("QQQ"),"date"]).unique()).sort_values()
    overlap=old_calendar[old_calendar.le("2026-07-14") & old_calendar.ge("2025-06-01")]
    assert overlap.equals(canonical_calendar[canonical_calendar.isin(overlap)])
    calendar=canonical_calendar[canonical_calendar.ge("2025-06-01") & canonical_calendar.le(LAST_RAW_DATE)]
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
    dates=calendar[calendar.ge("2026-01-02")]
    timing=pd.read_parquet(R1ROOT / "universe/quarterly_universe_manifest.parquet")
    timing=timing.loc[timing.quarter.isin(["2025Q3","2025Q4","2026Q1"]),["quarter","effective_date"]].sort_values("effective_date")
    active=pd.merge_asof(pd.DataFrame({"signal_date":dates}),timing,left_on="signal_date",right_on="effective_date",direction="backward")
    assert active.quarter.notna().all()
    candidates=active.merge(pool[["quarter","ticker","moomoo_transport_code"]],on="quarter",validate="many_to_many")
    candidates=candidates.merge(status,on=["signal_date","ticker"],how="left",validate="one_to_one")
    candidates["final_eligible"]=candidates.lookback_eligible.fillna(False)&candidates.all_features_available.fillna(False)
    coverage=candidates.groupby(["signal_date","quarter"],as_index=False).agg(
        original_pool_count=("ticker","size"),price_feature_eligible_count=("final_eligible","sum"))
    coverage.to_csv(HERE / "PARTIAL_2026_A2_ELIGIBILITY.csv",index=False)
    eligible=candidates.loc[candidates.final_eligible,["signal_date","quarter","ticker","moomoo_transport_code"]]
    matrix=eligible.merge(features.drop(columns=["trade_date"]),on=["signal_date","ticker"],validate="one_to_one")
    matrix["universe_size"]=matrix.groupby("signal_date").ticker.transform("size").astype(np.int32)
    model=joblib.load(R1ROOT / "A2/final_full_pre2026_hgb.joblib")
    matrix["a2_prediction"]=model.predict(matrix.loc[:,r1.FEATURE_COLUMNS].to_numpy(float))
    matrix["a2_rank"]=r1._prediction_rank(matrix,"a2_prediction")
    top=matrix.loc[matrix.a2_rank.le(20),["signal_date","quarter","ticker","moomoo_transport_code","universe_size","a2_prediction","a2_rank"]].copy()
    assert top.groupby("signal_date").size().eq(20).all()
    top.to_parquet(HERE / "PARTIAL_2026_A2_TOP20_INPUT_ONLY.parquet",index=False)
    result={"status":"PARTIAL_FROZEN_A2_INFERENCE_NO_POLICY_TEST","signal_start":str(top.signal_date.min().date()),
            "signal_end":str(top.signal_date.max().date()),"signal_days":int(top.signal_date.nunique()),
            "covered_quarters":coverage.quarter.value_counts().to_dict(),
            "candidate_union_codes":int(len(code_ticker)),"priced_codes":int(priced.moomoo_transport_code.nunique()),
            "source_gap_codes":len(errors),"frozen_boundary_codes_exact":len(boundary),
            "eligible_count_min":int(coverage.price_feature_eligible_count.min()),
            "eligible_count_max":int(coverage.price_feature_eligible_count.max()),
            "model_fit_calls":0,"policy_outcomes_read":False,"formal_2026_reveals":0,
            "limit":"Partial signal inference stops at original raw cache last date; never a shortened formal policy test."}
    (HERE / "PARTIAL_2026_SIGNAL_AUDIT.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__=="__main__":
    main()
