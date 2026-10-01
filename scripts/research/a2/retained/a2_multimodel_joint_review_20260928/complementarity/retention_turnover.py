from analyze_predictions import *
from analyze_common_account import MEMBERS

def main():
    f=pd.read_parquet(OUT/'common_account_targets_2025.parquet');rows=[];turn=[]
    for date,g in f.groupby('signal_date',sort=True):
        c=g.current_weight.to_numpy();w=g[MEMBERS].to_numpy();pre=g.equal_pre_target.to_numpy();post=g.equal_post_target.to_numpy()
        turn.append(dict(signal_date=date,mean_member_turnover=float(np.abs(w-c[:,None]).sum()/6),equal_pre_turnover=float(np.abs(pre-c).sum()),equal_post_turnover=float(np.abs(post-c).sum()),opposing_actions_cancelled=float(np.abs(w-c[:,None]).sum()/6-np.abs(pre-c).sum()),top20_turnover_increment=float(np.abs(post-c).sum()-np.abs(pre-c).sum()),mixed_direction_names=int(g.mixed_buy_sell.sum()),positive_union=int((pre>1e-8).sum()),kept_names=int((post>1e-8).sum())))
        keep=g.equal_post_target.to_numpy()>1e-8
        for m in MEMBERS:
            target=g[m].to_numpy(); selected=target>1e-8;unique=selected & g.selection_votes.eq(1).to_numpy()
            rows.append(dict(signal_date=date,member=m,active_target=float(target.sum()),attributed_average_pre_mass=float(target.sum()/6),attributed_average_post_mass=float(target[keep].sum()/6),attributed_truncation_mass=float(target[~keep].sum()/6),selected_names=int(selected.sum()),selected_names_discarded=int((selected&~keep).sum()),unique_support_names=int(unique.sum()),unique_support_discarded=int((unique&~keep).sum()),target_turnover=float(np.abs(target-c).sum())))
    rd=pd.DataFrame(rows);td=pd.DataFrame(turn);rd.to_csv(OUT/'daily_member_retention.csv',index=False);td.to_csv(OUT/'daily_target_turnover.csv',index=False)
    rs=[]
    for m,g in rd.groupby('member'):
        for col in rd.columns.drop(['signal_date','member']):rs.append(dict(member=m,metric=col,**interval(g[col])))
    pd.DataFrame(rs).to_csv(OUT/'member_retention_summary.csv',index=False)
    ts=[dict(metric=col,**interval(td[col])) for col in td.columns.drop('signal_date')]
    pd.DataFrame(ts).to_csv(OUT/'target_turnover_summary.csv',index=False)
    # No data removal: catalog extreme-label contribution to the optional proxy comparison.
    sf=pd.read_parquet(OUT/'single_step_stock_utility_posthoc.parquet');risk=sf.y_next_open.abs()>.2
    pairs=[('equal_post_target','equal_pre_target'),('equal_post_target','joint_hgb'),('equal_post_target','joint_mlp')]
    er=[]
    for a,b in pairs:
        for label,mask in [('all',np.ones(len(sf),bool)),('abs_return_gt20pct',risk),('abs_return_le20pct',~risk)]:
            val=sf.loc[mask,a+'_proxy_utility']-sf.loc[mask,b+'_proxy_utility']
            d=pd.Series(val.values,index=sf.loc[mask,'signal_date']).groupby(level=0).sum().reindex(td.signal_date,fill_value=0)
            er.append(dict(a=a,b=b,group=label,stock_dates=int(mask.sum()),**interval(d)))
    pd.DataFrame(er).to_csv(OUT/'extreme_return_utility_contribution_posthoc.csv',index=False)
    print(pd.DataFrame(rs).query("metric in ['active_target','attributed_truncation_mass','selected_names_discarded']")[['member','metric','daily_mean']].to_string(index=False));print(pd.DataFrame(ts).to_string(index=False))

if __name__=='__main__':main()
