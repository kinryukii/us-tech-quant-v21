"""Deterministic chronological CPCV and conservative robustness statistics."""
from __future__ import annotations

from itertools import combinations
import math
from typing import Any

import numpy as np
import pandas as pd


def not_computable(reason: str) -> str: return "NOT_COMPUTABLE:" + reason

def _normal_cdf(value: float) -> float: return .5 * (1.0 + math.erf(value / math.sqrt(2.0)))
def _normal_ppf(probability: float) -> float:
    # Acklam approximation; deterministic and dependency-free.
    if not 0 < probability < 1: raise ValueError("PROBABILITY_OUT_OF_RANGE")
    a=(-39.6968302866538,220.946098424521,-275.928510446969,138.357751867269,-30.6647980661472,2.50662827745924)
    b=(-54.4760987982241,161.585836858041,-155.698979859887,66.8013118877197,-13.2806815528857)
    c=(-.00778489400243029,-.322396458041136,-2.40075827716184,-2.54973253934373,4.37466414146497,2.93816398269878)
    d=(.00778469570904146,.32246712907004,2.445134137143,3.75440866190742)
    if probability < .02425:
        q=math.sqrt(-2*math.log(probability)); return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5])/((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if probability > .97575: return -_normal_ppf(1-probability)
    q=probability-.5; r=q*q; return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q/(((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)

def generate_cpcv_splits(events: pd.DataFrame, windows: list[dict[str, Any]], *, test_window_count: int, purge_minutes: int, embargo_minutes: int) -> list[dict[str, Any]]:
    required={"event_id","decision_timestamp_et","label_end_timestamp_et"}
    if required-set(events): raise ValueError("CPCV_EVENT_SCHEMA_INVALID")
    if test_window_count < 1 or test_window_count >= len(windows): raise ValueError("CPCV_TEST_WINDOW_COUNT_INVALID")
    x=events.copy(); x["decision_timestamp_et"]=pd.to_datetime(x.decision_timestamp_et,utc=True,errors="raise"); x["label_end_timestamp_et"]=pd.to_datetime(x.label_end_timestamp_et,utc=True,errors="raise")
    out=[]
    for number, group in enumerate(combinations(windows,test_window_count),1):
        starts=[pd.Timestamp(w["start"]) for w in group]; ends=[pd.Timestamp(w["end"]) for w in group]; start=min(starts); end=max(ends)
        test=x.loc[np.logical_or.reduce([(x.decision_timestamp_et>=pd.Timestamp(w["start"]))&(x.decision_timestamp_et<=pd.Timestamp(w["end"])) for w in group])].copy()
        before=x.loc[x.decision_timestamp_et<start].copy(); cutoff=start-pd.Timedelta(minutes=purge_minutes+embargo_minutes)
        train=before.loc[before.label_end_timestamp_et<cutoff].copy()
        purge_removed=int((before.label_end_timestamp_et>=start-pd.Timedelta(minutes=purge_minutes)).sum())
        embargo_removed=int(((before.label_end_timestamp_et>=cutoff)&(before.label_end_timestamp_et<start-pd.Timedelta(minutes=purge_minutes))).sum())
        overlap=int(train.event_id.isin(test.event_id).sum()); time_bad=int((train.decision_timestamp_et>=start-pd.Timedelta(minutes=embargo_minutes)).sum())
        out.append({"split_id":f"CPCV_{number:02d}","test_window_ids":[str(w["block_id"]) for w in group],"train_start":str(train.decision_timestamp_et.min()) if len(train) else None,"train_end":str(train.decision_timestamp_et.max()) if len(train) else None,"test_start":str(start),"test_end":str(end),"train_event_count":int(len(train)),"test_event_count":int(len(test)),"purge_removed_count":purge_removed,"embargo_removed_count":embargo_removed,"overlap_violation_count":overlap,"time_order_violation_count":time_bad})
    return out

def path_statistics(paths: pd.DataFrame, column: str) -> dict[str, Any]:
    values=pd.to_numeric(paths[column],errors="coerce").to_numpy(dtype=float)
    if len(values)==0: return {"positive_ratio":not_computable("EMPTY_CPCV_PATHS"),"median":not_computable("EMPTY_CPCV_PATHS"),"worst":not_computable("EMPTY_CPCV_PATHS")}
    if not np.isfinite(values).all(): raise ValueError("CPCV_PATH_NONFINITE_RETURN")
    return {"positive_ratio":float((values>0).mean()),"median":float(np.median(values)),"worst":float(values.min())}

def pbo(candidate_scores: pd.DataFrame) -> float | str:
    required={"candidate_id","split_id","score"}
    if required-set(candidate_scores): raise ValueError("PBO_SCHEMA_INVALID")
    pivot=candidate_scores.pivot(index="candidate_id",columns="split_id",values="score")
    if len(pivot)<2: return not_computable("INSUFFICIENT_REAL_CANDIDATES")
    if pivot.shape[1]<2 or pivot.isna().any().any(): return not_computable("INSUFFICIENT_COMPLETE_REAL_CANDIDATE_SPLITS")
    outcomes=[]; columns=list(pivot.columns)
    for chosen in combinations(columns,max(1,len(columns)//2)):
        held=[x for x in columns if x not in chosen]
        if not held: continue
        winner=pivot.loc[:,list(chosen)].mean(axis=1).idxmax(); ranks=pivot.loc[:,held].mean(axis=1).rank(method="average",ascending=True)
        relative=(ranks[winner]-.5)/len(ranks); outcomes.append(float(math.log(relative/(1-relative))<=0))
    return float(np.mean(outcomes)) if outcomes else not_computable("NO_PBO_PARTITIONS")

def probabilistic_sharpe(returns: list[float] | np.ndarray, *, benchmark_sharpe: float=0.0, frequency: str="trade") -> dict[str, Any]:
    x=np.asarray(returns,dtype=float)
    if len(x)<3: return {"value":not_computable("SHORT_RETURN_SERIES"),"frequency":frequency,"sample_size":int(len(x))}
    if not np.isfinite(x).all(): raise ValueError("NONFINITE_RETURNS")
    sigma=float(x.std(ddof=1))
    if sigma==0: return {"value":not_computable("ZERO_VARIANCE_RETURNS"),"frequency":frequency,"sample_size":int(len(x))}
    sr=float(x.mean()/sigma); centered=(x-x.mean())/sigma; skew=float(np.mean(centered**3)); kurt=float(np.mean(centered**4))
    denominator=1-skew*sr+((kurt-1)/4)*sr*sr
    if denominator<=0: return {"value":not_computable("INVALID_PSR_DENOMINATOR"),"frequency":frequency,"sample_size":int(len(x))}
    return {"value":float(_normal_cdf((sr-benchmark_sharpe)*math.sqrt(len(x)-1)/math.sqrt(denominator))),"observed_sharpe":sr,"benchmark_sharpe":benchmark_sharpe,"frequency":frequency,"sample_size":int(len(x)),"skew":skew,"kurtosis":kurt}

def deflated_sharpe(returns: list[float] | np.ndarray, *, attempted_models: int, attempted_configurations: int, attempted_seeds: int, frequency: str="trade") -> dict[str, Any]:
    if min(attempted_models,attempted_configurations,attempted_seeds)<1: return {"value":not_computable("REAL_TRIAL_COUNT_UNAVAILABLE"),"trial_count":not_computable("REAL_TRIAL_COUNT_UNAVAILABLE")}
    trials=attempted_models*attempted_configurations*attempted_seeds; x=np.asarray(returns,dtype=float)
    base=probabilistic_sharpe(x,frequency=frequency)
    if isinstance(base["value"],str): return {**base,"trial_count":trials}
    threshold=0.0 if trials==1 else _normal_ppf(1-1/trials)/math.sqrt(len(x)-1)
    out=probabilistic_sharpe(x,benchmark_sharpe=threshold,frequency=frequency)
    return {**out,"trial_count":trials,"deflated_benchmark_sharpe":threshold}

def monthly_concentration(returns: pd.DataFrame, *, timestamp_column: str, return_column: str) -> dict[str, Any]:
    if returns.empty: return {"best_month_contribution_ratio":not_computable("EMPTY_RETURNS"),"top_3_month_contribution_ratio":not_computable("EMPTY_RETURNS"),"profitable_month_ratio":not_computable("EMPTY_RETURNS")}
    x=returns.copy(); x[timestamp_column]=pd.to_datetime(x[timestamp_column],utc=True,errors="raise"); x[return_column]=pd.to_numeric(x[return_column],errors="raise")
    if not np.isfinite(x[return_column]).all(): raise ValueError("NONFINITE_RETURNS")
    months=x.groupby(x[timestamp_column].dt.to_period("M"))[return_column].sum(); positive=months[months>0]
    ratios=not_computable("NO_POSITIVE_MONTHLY_CONTRIBUTION") if positive.sum()<=0 else None
    return {"best_month_contribution_ratio":ratios if ratios else float(positive.max()/positive.sum()),"top_3_month_contribution_ratio":ratios if ratios else float(positive.nlargest(3).sum()/positive.sum()),"profitable_month_ratio":float((months>0).mean())}

def regime_concentration(returns: pd.DataFrame, *, regime_column: str, return_column: str) -> dict[str, Any]:
    if regime_column not in returns: return {"best_regime_contribution_ratio":not_computable("RELIABLE_REGIME_FIELD_NOT_AVAILABLE"),"top_3_regime_contribution_ratio":not_computable("RELIABLE_REGIME_FIELD_NOT_AVAILABLE")}
    x=returns.copy(); x[return_column]=pd.to_numeric(x[return_column],errors="raise"); groups=x.groupby(regime_column)[return_column].sum(); positive=groups[groups>0]
    if positive.sum()<=0: return {"best_regime_contribution_ratio":not_computable("NO_POSITIVE_REGIME_CONTRIBUTION"),"top_3_regime_contribution_ratio":not_computable("NO_POSITIVE_REGIME_CONTRIBUTION")}
    return {"best_regime_contribution_ratio":float(positive.max()/positive.sum()),"top_3_regime_contribution_ratio":float(positive.nlargest(3).sum()/positive.sum())}
