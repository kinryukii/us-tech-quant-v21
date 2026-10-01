from analyze_predictions import *

MEMBERS=['joint_ridge','joint_elastic_net','joint_logistic','joint_hgb','joint_quantile_risk','joint_mlp']

def main():
    path=OUT.parent/'cash_attribution/member_targets_2025.parquet'
    digest(path);digest(DATA);digest(OUT/'DIAGNOSTIC_SPEC.md');digest(Path(__file__))
    long=pd.read_parquet(path)
    assert set(long.member)==set(MEMBERS) and long.signal_date.dt.year.eq(2025).all()
    keys=['signal_date','ticker']
    meta=long.groupby(keys,sort=True).first().drop(columns=['member','member_target'])
    wide=long.pivot(index=keys,columns='member',values='member_target')[MEMBERS]
    assert len(long)==6*len(wide) and wide.notna().all().all()
    f=meta.join(wide).reset_index()
    assert np.allclose(f[MEMBERS].mean(axis=1),f.equal_pre_target,atol=1e-12)
    current=f.current_weight.to_numpy(); w=f[MEMBERS].to_numpy()
    votes=(w>1e-8).sum(axis=1); move=np.where(w-current[:,None]>1e-8,1,np.where(w-current[:,None]<-1e-8,-1,0))
    f['selection_votes']=votes; f['buy_votes']=(move==1).sum(axis=1);f['sell_votes']=(move==-1).sum(axis=1);f['unchanged_votes']=(move==0).sum(axis=1)
    f['mixed_buy_sell']=(f.buy_votes>0)&(f.sell_votes>0)
    f.to_parquet(OUT/'common_account_targets_2025.parquet',index=False)
    daily=[]; vote_daily=[]
    for date,g in f.groupby('signal_date',sort=True):
        cur=g.current_weight.to_numpy();mat=g[MEMBERS].to_numpy()
        for a,b in itertools.combinations(MEMBERS,2):
            wa=g[a].to_numpy();wb=g[b].to_numpy();sa=wa>1e-8;sb=wb>1e-8
            da=np.where(wa-cur>1e-8,1,np.where(wa-cur< -1e-8,-1,0));db=np.where(wb-cur>1e-8,1,np.where(wb-cur< -1e-8,-1,0))
            union=sa|sb; relevant=union|(cur>1e-8);count=int(relevant.sum())
            same=(da==db)&(da!=0);opp=da*db==-1;one=(da==0)^(db==0);neither=(da==0)&(db==0)
            daily.append(dict(signal_date=date,a=a,b=b,candidates=len(g),selected_union=int(union.sum()),selected_overlap=int((sa&sb).sum()),jaccard=float((sa&sb).sum()/union.sum()) if union.any() else 1.,target_l1=float(np.abs(wa-wb).sum()),relevant_stock_rows=count,same_buy_sell_fraction=float(same[relevant].mean()) if count else 0.,opposite_buy_sell_fraction=float(opp[relevant].mean()) if count else 0.,one_unchanged_fraction=float(one[relevant].mean()) if count else 0.,both_unchanged_fraction=float(neither[relevant].mean()) if count else 0.,opposite_stock_count=int(opp.sum())))
        for k in range(7):
            subset=g.loc[g.selection_votes.eq(k)]
            vote_daily.append(dict(signal_date=date,votes=k,names=len(subset),pre_mass=float(subset.equal_pre_target.sum()),post_mass=float(subset.equal_post_target.sum()),truncated_mass=float((subset.equal_pre_target-subset.equal_post_target).sum()),truncated_names=int(subset.top20_truncated.sum()),buy_sell_conflict_names=int(subset.mixed_buy_sell.sum())))
    dd=pd.DataFrame(daily); vd=pd.DataFrame(vote_daily)
    dd.to_csv(OUT/'daily_member_disagreement.csv',index=False);vd.to_csv(OUT/'daily_consensus_truncation.csv',index=False)
    summaries=[]
    for (a,b),g in dd.groupby(['a','b'],sort=False):
        for metric in ['jaccard','target_l1','same_buy_sell_fraction','opposite_buy_sell_fraction','one_unchanged_fraction','both_unchanged_fraction','opposite_stock_count']:
            summaries.append(dict(a=a,b=b,metric=metric,**interval(g[metric])))
    pd.DataFrame(summaries).to_csv(OUT/'member_disagreement_summary.csv',index=False)
    cv=[]
    for k,g in vd.groupby('votes'):
        for metric in ['names','pre_mass','post_mass','truncated_mass','truncated_names','buy_sell_conflict_names']:
            cv.append(dict(votes=int(k),metric=metric,**interval(g[metric])))
    pd.DataFrame(cv).to_csv(OUT/'consensus_truncation_summary.csv',index=False)
    source=pd.read_parquet(DATA,columns=['signal_date','ticker','label_end_date','y_next_open','realized_vol_20d','avg_dollar_volume_20d'])
    f=f.merge(source,on=keys,how='left',validate='one_to_one',indicator=True)
    valid=f._merge.eq('both')&f.label_end_date.notna()&f.label_end_date.lt('2026-01-01')&np.isfinite(f[['y_next_open','realized_vol_20d','avg_dollar_volume_20d']]).all(axis=1)&f.avg_dollar_volume_20d.gt(0)
    f.loc[~valid,keys+['current_weight','equal_pre_target','equal_post_target','label_end_date']].to_csv(OUT/'single_step_missing_labels.csv',index=False)
    covered=f.loc[valid].copy()
    current=covered.current_weight.to_numpy(float);adv=covered.avg_dollar_volume_20d.to_numpy(float);ret=covered.y_next_open.to_numpy(float);vol=covered.realized_vol_20d.to_numpy(float)
    utilities=[]
    for m in [*MEMBERS,'equal_pre_target','equal_post_target','current_weight']:
        target=covered[m].to_numpy(float); actual=np.where(target>current,current+np.minimum(target-current,.01*adv/1e6),target)
        gross=actual*ret;cost=.001*np.abs(actual-current);risk=2*vol**2*actual**2
        covered[m+'_proxy_utility']=gross-cost-risk
        temp=pd.DataFrame({'signal_date':covered.signal_date,'member':m,'gross':gross,'cost':cost,'risk_penalty':risk,'utility':gross-cost-risk,'capacity_limited_weight':np.maximum(target-actual,0)})
        utilities.append(temp.groupby(['signal_date','member'],as_index=False).sum())
    ud=pd.concat(utilities,ignore_index=True);ud.to_csv(OUT/'single_step_daily_utility_posthoc.csv',index=False)
    urows=[]
    for m,g in ud.groupby('member'):
        for metric in ['gross','cost','risk_penalty','utility','capacity_limited_weight']:
            urows.append(dict(member=m,metric=metric,**interval(g[metric])))
    pd.DataFrame(urows).to_csv(OUT/'single_step_utility_summary_posthoc.csv',index=False)
    u=ud.pivot(index='signal_date',columns='member',values='utility');up=[]
    for a,b in itertools.combinations(u.columns,2):
        diff=u[a]-u[b];up.append(dict(a=a,b=b,positive_means='a one-step utility higher than b; NOT path return',a_better_days=int((diff>0).sum()),**interval(diff)))
    pd.DataFrame(up).to_csv(OUT/'single_step_pairwise_utility_posthoc.csv',index=False)
    # Conflict utility is compared on the same covered stock-dates only, not independent observations.
    cr=[]
    for a,b in itertools.combinations(MEMBERS,2):
        da=covered[a]-covered.current_weight;db=covered[b]-covered.current_weight
        conflict=((da>1e-8)&(db< -1e-8))|((da< -1e-8)&(db>1e-8))
        if conflict.any():
            delta=covered.loc[conflict,a+'_proxy_utility']-covered.loc[conflict,b+'_proxy_utility']
            byday=pd.Series(delta.values,index=covered.loc[conflict,'signal_date']).groupby(level=0).sum().reindex(u.index,fill_value=0)
            cr.append(dict(a=a,b=b,conflict_stock_dates=int(conflict.sum()),**interval(byday)))
    pd.DataFrame(cr).to_csv(OUT/'conflicting_actions_utility_posthoc.csv',index=False)
    covered.to_parquet(OUT/'single_step_stock_utility_posthoc.parquet',index=False)
    coverage=dict(rows_total=len(f),rows_with_mature_2025_labels=int(valid.sum()),rows_missing=int((~valid).sum()),days_total=int(f.signal_date.nunique()),days_with_labels=int(covered.signal_date.nunique()),post_target_mass_coverage=float(f.loc[valid,'equal_post_target'].sum()/f.equal_post_target.sum()),current_mass_coverage=float(f.loc[valid,'current_weight'].sum()/f.current_weight.sum()),all_labels_max=str(covered.label_end_date.max()),returns_over_abs20pct=int((covered.y_next_open.abs()>.2).sum()))
    write('COMMON_ACCOUNT_AUDIT.json',dict(status='PASS',scope='frozen 2025 common account targets; single-step utility is post-hoc NOT a replay',coverage=coverage,input_sha256=HASHES,limitations=['Fixed nominal 1,000,000; no dynamic cash budgeting/whole-share ordering/open-price mismatch modeling','No collateral path, never cumulative annual return','Reserved holdings absent from member rows; common reserved exposure cancels in pair comparisons','Targets arise on equal-weight account path, not each standalone member account']))
    print(json.dumps(coverage,indent=2)); print(pd.DataFrame(summaries).query("metric in ['jaccard','opposite_buy_sell_fraction']")[['a','b','metric','daily_mean']].to_string(index=False))
    print(pd.DataFrame(urows).query("metric=='utility'").to_string(index=False))

if __name__=='__main__':main()
