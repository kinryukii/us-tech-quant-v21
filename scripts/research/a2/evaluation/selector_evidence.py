"""Frozen pure-selector evidence; selection-only, with no fitting or account claims."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.stats import rankdata
from scripts.common.storage_paths import resolve
from scripts.research.a2.evaluation.selector_account_compare import score_panel,pre2026,sha,readj

REPO=Path(__file__).resolve().parents[4]
RAW="RAW_A2_SCORE_IN_COMMON_13F_UNIVERSE"
KEY=["signal_date","security_uid"]
SE_TOL=1e-15

def putj(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,default=str,allow_nan=False)+"\n",encoding="utf-8")

def prove_label_boundary(path,end,allow_null=False):
    """Footer proof before target projection; null tails retain no target."""
    footer=pq.ParquetFile(path)
    for field in ("signal_date",end):
        position=footer.schema_arrow.get_field_index(field)
        if position<0:raise ValueError("LABEL_BOUNDARY_COLUMN_MISSING")
        for i in range(footer.num_row_groups):
            group=footer.metadata.row_group(i);stat=group.column(position).statistics
            if stat is None or stat.null_count is None:raise ValueError("UNKNOWN_LABEL_BOUNDARY")
            if allow_null and field==end and stat.null_count==group.num_rows:continue
            if (not stat.has_min_max or (not allow_null or field=="signal_date") and stat.null_count!=0
                or pd.isna(stat.max) or pd.Timestamp(stat.max)>=pd.Timestamp("2026-01-01")):
                raise ValueError("PHYSICAL_PRE2026_LABEL_BOUNDARY_NOT_PROVEN")

def validate_rank(panel):
    ordered=panel.sort_values(["signal_date","score","security_uid"],ascending=[True,False,True],kind="stable")
    expected=ordered.groupby("signal_date").cumcount()+1
    if not ordered["rank"].eq(expected).all():raise ValueError("FROZEN_SCORE_DESC_UID_TIE_RANK_REQUIRED")

def align(reference,panel):
    cols=KEY+["ticker","U_t_fingerprint"]
    if reference.duplicated(KEY).any() or panel.duplicated(KEY).any() or not panel[cols].equals(reference[cols]):
        raise ValueError("EXACT_FULL_COMMON_UID_TICKER_FINGERPRINT_KEYS_REQUIRED")

def maturity(reference,selected_union):
    end=pd.to_datetime(reference.label_end_date);y=reference.target.to_numpy(float)
    reasons=pd.DataFrame({"target_nonfinite":~np.isfinite(y),"label_end_missing":end.isna(),
        "label_not_pre2026":end.ge("2026-01-01"),"invalid_label_clock":end.le(reference.signal_date)})
    mature=~reasons.any(axis=1).to_numpy()
    rows=[]
    for date,index in reference.groupby("signal_date",sort=True).indices.items():
        chosen=index[selected_union[index]];bad=reasons.iloc[chosen].sum()
        rows.append(dict(signal_date=date,included=bool(mature[chosen].all()),
            selected_union_count=len(chosen),unavailable_selected_count=int((~mature[chosen]).sum()),
            reason="|".join(bad.index[bad.gt(0)]),**{k:int(v) for k,v in bad.items()}))
    return mature,pd.DataFrame(rows)

def replacement_edge(target,raw_selected,new_selected):
    if not np.isfinite(target[raw_selected|new_selected]).all():
        raise ValueError("SELECTED_LABELS_MUST_ALL_BE_MATURE")
    return float((target[new_selected&~raw_selected].sum()-target[raw_selected&~new_selected].sum())/20.)

def shared_max_t(edges,positions,complete,rule):
    """Fixed bootstrap-SE standardization, conditional recentering, shared draws."""
    x=np.asarray(edges,float);n,p=x.shape
    assert p==rule["family_candidates"]==53 and np.isfinite(x).all()
    assert len(positions)==n and np.all(np.diff(positions)>0) and len(complete)==p
    length=20;starts=np.array([i for i in range(n-length+1)
        if np.all(np.diff(positions[i:i+length])==1)],dtype=int)
    if n<length or not len(starts):
        return np.full(p,np.nan),np.full(p,np.nan),dict(status="INSUFFICIENT_CONTIGUOUS_COMMON_SESSIONS"),np.array([])
    rng=np.random.default_rng(rule["seed"]);b=rule["repeats"]
    offsets=rng.choice(starts,size=(b,(n+length-1)//length))
    draws=(offsets[:,:,None]+np.arange(length)).reshape(b,-1)[:,:n]
    centered=x-x.mean(axis=0);counts=np.zeros((b,n),dtype=float)
    for i,row in enumerate(draws):counts[i]=np.bincount(row,minlength=n)
    boot=counts@centered/n;boot-=boot.mean(axis=0)
    se=boot.std(axis=0,ddof=1);active=np.asarray(complete,bool)&np.isfinite(se)&(se>SE_TOL)
    maxima=(boot[:,active]/se[active]).max(axis=1) if active.any() else np.zeros(b)
    critical=float(np.quantile(maxima,rule["confidence"],method="higher"))
    lower=np.full(p,np.nan);lower[active]=x.mean(axis=0)[active]-critical*se[active]
    receipt=dict(status="COMPLETE",repeats=b,block_sessions=length,allowed_block_starts=len(starts),
        shared_draw_sha256=hashlib.sha256(draws.astype("<i8").tobytes()).hexdigest(),
        studentization="fixed bootstrap-SE plugin; no per-replicate SE refit",
        centering="sample-centered observations, then conditional bootstrap mean recentered per column",
        se_ddof=1,se_zero_tolerance=SE_TOL,quantile_method="higher",critical_max_t=critical,
        family_candidates=p,active_nonzero_se_columns=int(active.sum()),seed=rule["seed"],
        limitation="Approximate dependence-aware simultaneous evidence, not finite-sample coverage or future guarantee")
    return lower,se,receipt,maxima

def correlation(a,b):
    return float(np.corrcoef(a,b)[0,1]) if len(a)>1 and np.std(a)>0 and np.std(b)>0 else None

def diagnose(cid,reference,scores,ranks,raw_ranks,mature,common):
    records=[]
    for date,index in reference.groupby("signal_date",sort=True).indices.items():
        y=reference.target.to_numpy(float)[index];s=scores[index];r=ranks[index];rr=raw_ranks[index]
        valid=mature[index];chosen=r<=20;raw_chosen=rr<=20;n=len(index)
        whole=bool(valid.all());take=np.argsort(r,kind="stable")[:20]
        relevance=rankdata(y,method="average")/n if whole else None
        discounts=1/np.log2(np.arange(2,22))
        ndcg=float(np.dot(relevance[take],discounts)/np.dot(np.sort(relevance)[::-1][:20],discounts)) if whole else None
        truth=set(np.argsort(-y,kind="stable")[:20]) if whole else set()
        on_common=bool(common.loc[date]);edge=replacement_edge(y,raw_chosen,chosen) if on_common else None
        records.append(dict(candidate_id=cid,signal_date=date,common_mature_date=on_common,pool_rows=n,
            mature_pool_rows=int(valid.sum()),ic=correlation(s[valid],y[valid]),
            spearman_ic=correlation(rankdata(s[valid]),rankdata(y[valid])),ndcg20=ndcg,
            truth_top20_recall=float(len(set(take)&truth)/20) if whole else None,
            top20_target_mean=float(y[chosen].mean()) if on_common else None,
            precision_target_positive=float((y[chosen]>0).mean()) if on_common else None,
            replacement_edge=edge,overlap20=int((chosen&raw_chosen).sum()),
            entries=int((chosen&~raw_chosen).sum()),exits=int((raw_chosen&~chosen).sum()),
            rank_migration_mean_absolute=float(np.abs(r-rr).mean()),
            rank_migration_normalized=float(np.abs(r-rr).mean()/max(n-1,1)),
            score_std=float(s.std()),score_iqr=float(np.quantile(s,.75)-np.quantile(s,.25)),
            score_tie_excess_fraction=float((n-len(np.unique(s)))/n),name_hhi=20*.05**2))
    return records

def run(run_directory):
    root=Path(run_directory).resolve();paths=resolve(REPO)
    assert root.is_relative_to(paths.backtest_root)
    cfg=readj(root/"run_config.json");out=(root/"diagnostics/selector_evidence").resolve()
    results=Path(cfg["results_directory"]).resolve()
    assert out.is_relative_to(paths.backtest_root) and results.is_relative_to(paths.results_root)
    assert results==(paths.results_root/"V24/C_SELECTOR").resolve() and cfg["research_line"]=="C_SELECTOR"
    destination=results/"SELECTION_EVIDENCE.json"
    if destination.exists() or (out/"SELECTION_EVIDENCE.json").exists():raise FileExistsError("PRESERVE_EXISTING_SELECTION_EVIDENCE")
    freeze=root/"DESIGN_FREEZE.json";freeze_hash=sha(freeze)
    assert freeze_hash==readj(root/"DESIGN_FREEZE_SHA.json")["sha256"]==cfg["design_freeze_sha256"]
    design=readj(freeze);ids=design["candidates"];rule=design["selection_rule"];boot_rule=rule["bootstrap"]
    assert design["version"]=="V24" and design["line"]=="C_SELECTOR"
    assert len(ids)==len(set(ids))==53 and design["primary_eval_years"]==[2023,2024,2025]
    assert design["target"]=="MEAN_ER_3D_5D_10D_20D" and design["budget"]["max_finalists"]<=3
    assert boot_rule["method"]=="shared noncircular 20-session moving blocks; centered studentized one-sided maxT simultaneous lower"
    assert rule["primary"]=="TOP20_REPLACEMENT_EDGE=(sum matured labels entrants - sum matured labels exits)/20"
    assert boot_rule["repeats"]==5000 and boot_rule["confidence"]==.95 and boot_rule["family_candidates"]==53
    assert design["controls"]["top_k"]==20 and design["controls"]["target_weight"]==.05
    assert rule["positive_years_min"]==2 and rule["pooled_edge_positive"] and rule["year2025_edge_positive"]
    activation=readj(root/"EVALUATION_CODE_ACTIVATION.json")
    for source in [Path(__file__),REPO/"scripts/research/a2/evaluation/selector_account_compare.py",REPO/"scripts/research/a2/training/selector_challenge.py"]:
        assert activation["sources"][str(source)]==sha(source),"EVALUATION_SOURCE_NOT_ACTIVATED"
    assembly_path=root/"SCORE_ASSEMBLY.json"
    assert activation["score_assembly_sha256"]==sha(assembly_path),"SCORE_ASSEMBLY_NOT_ACTIVATED"
    assembly=readj(assembly_path);complete=assembly["complete_candidates"];failed=assembly["failed_or_untestable"]
    assert set(complete).isdisjoint(failed) and set(complete)|set(failed)==set(ids)
    assert len(complete)==len(set(complete)) and assembly["forecast2026_rows"]==0
    training=design["inputs"]["training"];assert sha(training["path"])==training["sha256"],"FROZEN_TARGET_SOURCE_CHANGED"
    prove_label_boundary(training["path"],"target_end_date")
    raw_path=root/f"predictions/scores_{RAW}_pre2026.parquet";prove_label_boundary(raw_path,"label_end_date",allow_null=True)
    reference,raw_hash=score_panel(root,RAW);validate_rank(reference)
    labels=pre2026(root/f"predictions/scores_{RAW}_pre2026.parquet",KEY+["target","label_end_date"],"signal_date")
    labels["signal_date"]=pd.to_datetime(labels.signal_date)
    assert labels.loc[labels.label_end_date.isna(),"target"].isna().all(),"TARGET_WITH_UNKNOWN_LABEL_MATURITY"
    reference=reference.merge(labels,on=KEY,validate="one_to_one",how="left")
    assert len(reference)==assembly["common_rows"] and reference.signal_date.nunique()==assembly["common_dates"]
    arrays={RAW:(reference.score.to_numpy(float),reference["rank"].to_numpy(float))}
    hashes={RAW:raw_hash};selected_union=reference["rank"].le(20).to_numpy(copy=True)
    for cid in complete:
        panel,digest=score_panel(root,cid);validate_rank(panel);align(reference,panel)
        arrays[cid]=(panel.score.to_numpy(float),panel["rank"].to_numpy(float))
        hashes[cid]=digest;selected_union|=panel["rank"].le(20).to_numpy()
    mature,dates=maturity(reference,selected_union);common=dates.set_index("signal_date").included
    daily=pd.DataFrame([row for cid,(scores,ranks) in arrays.items()
        for row in diagnose(cid,reference,scores,ranks,arrays[RAW][1],mature,common)])
    all_dates=pd.DatetimeIndex(dates.signal_date);included=dates.included.to_numpy(bool)
    matrix=np.zeros((int(included.sum()),53));edge_daily=daily.loc[daily.common_mature_date]
    for j,cid in enumerate(ids):
        if cid in complete:
            matrix[:,j]=edge_daily.loc[edge_daily.candidate_id.eq(cid)].set_index("signal_date").replacement_edge.reindex(all_dates[included]).to_numpy(float)
    lower,se,bootstrap,maxima=shared_max_t(matrix,np.flatnonzero(included),[cid in complete for cid in ids],boot_rule)
    summaries=[];year_array=all_dates[included].year
    for j,cid in enumerate(ids):
        yearly={str(y):float(matrix[year_array==y,j].mean()) if cid in complete and (year_array==y).any() else None for y in (2023,2024,2025)}
        pooled=float(matrix[:,j].mean()) if cid in complete and len(matrix) else None
        conditions=dict(complete_oof=cid in complete,all_three_years_present=all(v is not None for v in yearly.values()),
            pooled_positive=pooled is not None and pooled>0,year2025_positive=yearly["2025"] is not None and yearly["2025"]>0,
            two_of_three_years_positive=sum(v is not None and v>0 for v in yearly.values())>=2,
            nonzero_bootstrap_se=bool(np.isfinite(se[j]) and se[j]>SE_TOL),
            simultaneous_lower_positive=bool(np.isfinite(lower[j]) and lower[j]>0))
        summaries.append(dict(candidate_id=cid,status="COMPLETE" if cid in complete else "FAILED_UNTESTABLE",
            failure_reason=failed.get(cid),pooled_edge=pooled,year_edges=yearly,eligibility_conditions=conditions,
            bootstrap_se=float(se[j]) if np.isfinite(se[j]) else None,
            simultaneous_lower_95=float(lower[j]) if np.isfinite(lower[j]) else None,eligible=all(conditions.values())))
    eligible=sorted([v for v in summaries if v["eligible"]],key=lambda v:(-v["pooled_edge"],v["candidate_id"]))
    finalists=[v["candidate_id"] for v in eligible[:design["budget"]["max_finalists"]]]
    metrics=["ic","spearman_ic","ndcg20","truth_top20_recall","top20_target_mean","precision_target_positive"]
    diagnostic_summary=daily.assign(year=daily.signal_date.dt.year).groupby(["candidate_id","year"])[metrics].mean().reset_index()
    receipt=dict(status="FINALIST_SELECTION_ONLY" if finalists else "FINALIST_NONE",finalists=finalists,
        financial_verified=False,economic_promotion_allowed=False,indicative_profit_used=False,
        design_freeze_sha256=freeze_hash,evaluation_source_sha256=sha(Path(__file__)),
        score_assembly_sha256=sha(assembly_path),score_sha256=hashes,family_candidates=53,
        candidates=summaries,bootstrap=bootstrap,failed_columns="zero maxT matrix placeholders only; unmeasured report edges null",
        label_source_sha256=training["sha256"],label_boundary="source target_end and nullable score label_end physical pre2026 footers",common_mature_dates=int(included.sum()),
        common_year_dates={str(y):int((year_array==y).sum()) for y in (2023,2024,2025)},
        excluded_dates=int((~included).sum()),sector_status="UNAVAILABLE_NO_REGISTERED_PIT_MAPPING_USED",
        diagnostic_definitions={"ndcg20":"whole-pool mature labels; average target percentile rank, linear gain",
            "truth_top20":"whole-pool target descending with canonical UID ascending ties",
            "ic":"same mature whole-pool subset for all scores; undefined constant scores retained as null",
            "name_hhi":"20 equal positions at 0.05; score units are native and dispersion is diagnostic"},
        exposure=design["exposure"],claim="Frozen53-family exploratory/stability selection evidence; prior effective trials UNKNOWN; 2025 already exposed; no financial or independent holdout claim",
        diagnostics_directory=str(out),run_directory=str(root),test2026_rows_read=0)
    out.mkdir(parents=True,exist_ok=True);dates.to_parquet(out/"COMMON_DATE_MATURITY.parquet",index=False)
    daily.to_parquet(out/"DAILY_DIAGNOSTICS.parquet",index=False)
    diagnostic_summary.to_parquet(out/"YEAR_DIAGNOSTICS.parquet",index=False)
    pd.DataFrame(matrix,columns=ids,index=all_dates[included]).rename_axis("signal_date").reset_index().to_parquet(out/"PRIMARY_DAILY_EDGE.parquet",index=False)
    pd.DataFrame({"replicate":np.arange(len(maxima)),"centered_standardized_max_t":maxima}).to_parquet(out/"BOOTSTRAP_MAXT.parquet",index=False)
    receipt["diagnostic_sha256"]={p.name:sha(p) for p in out.glob("*.parquet")}
    putj(out/"SELECTION_EVIDENCE.json",receipt);putj(destination,receipt)
    return receipt
