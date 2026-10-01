from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

P=Path(__file__).resolve().parent
LABEL={'joint_ridge':'Ridge','joint_elastic_net':'Elastic Net','joint_logistic':'Logistic','joint_hgb':'HGB','joint_quantile_risk':'Quantile risk','joint_mlp':'MLP'}
plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'figure.facecolor':'white'})
fig,axes=plt.subplots(1,3,figsize=(17,5.5),gridspec_kw={'width_ratios':[1.15,1,1]})
s=pd.read_csv(P/'member_disagreement_summary.csv');names=list(LABEL);m=np.eye(6)
for r in s.loc[s.metric.eq('jaccard')].itertuples():
 i=names.index(r.a);j=names.index(r.b);m[i,j]=m[j,i]=r.daily_mean
im=axes[0].imshow(m,cmap='Blues',vmin=0,vmax=1)
axes[0].set_xticks(range(6),[LABEL[n] for n in names],rotation=40,ha='right');axes[0].set_yticks(range(6),[LABEL[n] for n in names])
for i in range(6):
 for j in range(6):axes[0].text(j,i,f'{m[i,j]:.2f}',ha='center',va='center',color='white' if m[i,j]>.65 else '#20252b',fontsize=9)
axes[0].set_title('Common-account selection Jaccard\n2025, 248 dates')
r=pd.read_csv(P/'member_retention_summary.csv');pre=r.loc[r.metric.eq('attributed_average_pre_mass')].set_index('member').daily_mean.reindex(names)*100;post=r.loc[r.metric.eq('attributed_average_post_mass')].set_index('member').daily_mean.reindex(names)*100
axes[1].barh(range(6),post,color='#31688e',label='Retained after TOP20');axes[1].barh(range(6),pre-post,left=post,color='#e9a253',label='Truncated')
axes[1].set_yticks(range(6),[LABEL[n] for n in names]);axes[1].invert_yaxis();axes[1].set_xlabel('Daily mean attributed portfolio weight (pp)');axes[1].set_title('Where distinct member targets disappear\nWeight attributed as member target / 6');axes[1].legend(loc='lower right',fontsize=8)
a=pd.read_csv(P/'incremental_pairwise_error_relief.csv');a=a.loc[(a.year==2025)&a.reference.eq('ridge')];labs={'elastic_net':'Elastic Net','hgb':'HGB','stack_validation':'Validation stack'}
y=np.arange(len(a));means=a.all_daily_mean.to_numpy()*1e8;lo=a.all_ci95_low.to_numpy()*1e8;hi=a.all_ci95_high.to_numpy()*1e8
axes[2].errorbar(means,y,xerr=[means-lo,hi-means],fmt='o',color='#31688e',capsize=4);axes[2].axvline(0,color='#777',ls='--',lw=1);axes[2].set_yticks(y,[labs[n] for n in a.member]);axes[2].invert_yaxis();axes[2].set_xlabel('MSE improvement vs Ridge (bps squared)');axes[2].set_title('OOF incremental action utility error\nDate-clustered HAC 95% intervals')
fig.suptitle('Frozen-artifact complementarity diagnostics: disagreement is not established benefit',fontsize=15,y=1.02)
fig.tight_layout();fig.savefig(P/'complementarity_summary.png',dpi=170,bbox_inches='tight');fig.savefig(P/'complementarity_summary.pdf',bbox_inches='tight');plt.close(fig)
