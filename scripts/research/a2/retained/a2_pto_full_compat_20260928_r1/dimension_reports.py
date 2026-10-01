"""All methods, each component axis, matched descriptive effects."""
from common import *
from build_report import markdown,number,link

def main():
    out=ROOT/'analysis';receipt=json.loads((out/'ANALYSIS_RECEIPT.json').read_text(encoding='utf-8'))
    if not receipt['complete']:raise RuntimeError('COMPLETE_REGISTERED_ANALYSIS_REQUIRED')
    specs=[('预测器：固定其他维度，减Ridge','PREDICTOR_PAIRED_CONTRASTS.csv',['stream'],'point'),
        ('预测融合：同成员集合，减equal','FUSION_PAIRED_CONTRASTS.csv',['bundle','fusion'],'fusion'),
        ('风险：固定其他维度，减diagonal','RISK_PAIRED_CONTRASTS.csv',['risk'],'risk'),
        ('优化：固定其他维度，减mean_variance','OPTIMIZER_PAIRED_CONTRASTS.csv',['optimizer'],'opt'),
        ('目标融合：减target_equal','TARGET_FUSION_PAIRED_CONTRASTS.csv',['target_fusion'],'target')]
    delta=['delta_indicative_return','delta_indicative_max_drawdown','delta_mean_gross_exposure','delta_fees']
    tables={file:pd.read_csv(out/file) for _,file,_,_ in specs}
    for axis in AXES:
        lines=[f'# {axis}：按预测、融合、风险与优化组织的完整配对比较','',
            '全部既有注册方法，未选冠军拼接。格数是同其他维度配对的完整账户路径数量；资金账户独立不等于统计独立，格数与胜率不是重复试验样本量。收益/回撤/敞口差是比例的百分点；费用差为美元。回撤为负数，因此回撤差>0表示回撤变浅；费用差>0表示成本增加。正负比例排除小于1e-12的浮点差，零差仍在格数内。各指标仅在自身有限值支持上计算中位数；收益正负比例使用有限收益差。',
            '', '2025回放使用截至2024的阶段工件，但2025标签也用于最终截至2025的学习，因此2025不是整批最终工件的独立验证年。2026为1/2–9/24已暴露历史的资格子池诊断，正式全池BLOCKED_DATA，不能称盲测或认证股东总收益。账户内生状态不同，差分不单独证明模型因果能力。低暴露/高现金必须与回撤一起判断。']
        for year in [2025,2026]:
            lines+=['',f'## {year}']
            for title,file,dimensions,kind in specs:
                t=tables[file];t=t[t.year.eq(year)&t.axis.eq(axis)]
                if kind=='point':t=t[t.stream.isin(MEMBERS)]
                rows=[]
                for key,g in t.groupby(dimensions,dropna=False,sort=True):
                    key=key if isinstance(key,tuple) else (key,)
                    valid=g[np.isfinite(g.delta_indicative_return)]
                    supports=[int(np.isfinite(g[c]).sum()) for c in delta]
                    rows.append({'方法':' / '.join(str(x) for x in key),'配对格数':len(valid),
                        '有限支持收益/回撤/敞口/费用':' / '.join(str(n) for n in supports),
                        '缺失收益/回撤/敞口/费用':' / '.join(str(len(g)-n) for n in supports),
                        '收益差中位数':number(valid.delta_indicative_return.median(),True),
                        '收益正/负比例':number(valid.delta_indicative_return.gt(1e-12).mean(),True)+' / '+number(valid.delta_indicative_return.lt(-1e-12).mean(),True),
                        '回撤差中位数':number(g.loc[np.isfinite(g.delta_indicative_max_drawdown),'delta_indicative_max_drawdown'].median(),True),
                        '敞口差中位数':number(g.loc[np.isfinite(g.delta_mean_gross_exposure),'delta_mean_gross_exposure'].median(),True),
                        '费用差中位数USD':number(g.loc[np.isfinite(g.delta_fees),'delta_fees'].median())})
                lines+=['',f'### {title}','',markdown(pd.DataFrame(rows))]
        lines+=['',link('全部配对与非配对完整结果','analysis/ALL_STRATEGY_RESULTS.csv')+' · '+link('完整方案交互','analysis/LAYER_INTERACTIONS.csv')+' · '+link('同集合融合交互','analysis/FUSION_LAYER_INTERACTIONS.csv'),
            '', '本报告风险/优化配对包含目标融合，边际CSV的core网格不包含；两套支持总体不同。交互表保留参照方法造成的结构零，零比例不等于模型无交互。singleton/identity边际合并不同单成员，不能当同成员集合的融合消融。',
            '', '目标专家矩阵各自用同一融合账户的实际状态，单独保存目标贡献；本表目标融合比较的是独立完整账户。没有point13等权收益融合注册路线，因此不能用不同成员集合制造预测融合/目标融合的纯消融。']
        (out/f'COMPARISON_{axis.upper()}.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('ALL4_DIMENSION_REPORTS_READY',flush=True)

if __name__=='__main__':main()
