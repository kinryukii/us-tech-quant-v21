"""Summarize saved fresh-fit receipts without retraining or selecting winners."""
from pathlib import Path
import hashlib,json

ROOT=Path(__file__).resolve().parent

def read(path):return json.loads((ROOT/path).read_text(encoding='utf-8'))
def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
    value=read('value_artifacts/FIT_RECEIPT.json')
    dev=read('development_value_artifacts/FIT_RECEIPT.json')
    neural=read('neural_artifacts/TRAIN_RECEIPT.json')
    neuraldev=read('development_neural_artifacts/TRAIN_RECEIPT.json')
    risk=[read(f'risk_artifacts/{s}/TRAIN_RECEIPT.json') for s in ['validation','final']]
    aux=[read(f'aux_artifacts/{s}/TRAIN_RECEIPT.json') for s in ['validation','final']]
    meta=[read(f'ensemble_artifacts/{s}_TRAIN_RECEIPT.json') for s in ['validation','final']]
    counts=dict(supervised_primary_fits=value['main_fit_calls']+dev['main_fit_calls'],
        supervised_numerical_continuations=value['total_fit_calls_including_numerical_repairs']+dev['total_fit_calls_including_numerical_repairs']-value['main_fit_calls']-dev['main_fit_calls'],
        supervised_scaler_fits=value['scaler_fit_calls']+dev['scaler_fit_calls'],
        neural_policy_fits=neural['fit_count']+neuraldev['fit_count'],
        optimizer_updates=neural['actual_parameter_updates']+neuraldev['actual_parameter_updates'],
        risk_estimator_fits=sum(v['estimator_fit_calls'] for v in risk),
        risk_pca_decompositions=sum(v['pca_decompositions'] for v in risk),
        auxiliary_estimator_fits=sum(v['estimator_fit_calls'] for v in aux),
        auxiliary_scaler_fits=sum(v['scaler_fit_calls'] for v in aux))
    counts['stacking_meta_fits']=sum(v['fit_calls'] for v in meta)
    contracts=[p for p in ROOT.rglob('*RECEIPT.json') if 'evaluation_' not in str(p)]
    registry={str(p.relative_to(ROOT)):sha(p) for p in sorted(contracts)}
    coverage=dict(status='FRESH_TRAINING_COMPLETE_WITH_DATA_LIMITATIONS',counts=counts,
        supervised_methods=['Ridge','ElasticNet','LogisticRegression','HGB','Q10','Q50','Q90'],
        neural_methods=['small MLP direct portfolio utility','REINFORCE two fixed seeds'],
        auxiliary_methods=['LedoitWolf covariance shrinkage','PCA five factors','KMeans five clusters','IsolationForest'],
        decision_method='cost-aware action scores and constrained TOP20 allocation',
        ensemble_methods=['equal-weight signed-rank blend','disagreement/downside blend','nonnegative Ridge stacking on temporal OOF'],
        stacking_coefficients={v['stage']:v['coefficients'] for v in meta},
        train_cutoff_exclusive='2026-01-01',test_fit_rows=0,hyperparameter_searches=0,
        untouched_holdout=False,full_13f_pool_certified=False,receipts_sha256=registry)
    (ROOT/'METHOD_COVERAGE.json').write_text(json.dumps(coverage,indent=2,ensure_ascii=False),encoding='utf-8')
    text=f'''# 新训练与集成方法覆盖\n\n本次重点是3种多模型融合，基础模型分别训练作为必要组件和单模型对照。完整原始13F全池测试尚未认证；所有已完成的训练均未使用2026数据。\n\n- 监督模型主拟合：{counts['supervised_primary_fits']}次，包含validation/final各7次及development的7次。\n- Elastic Net同目标数值续算：{counts['supervised_numerical_continuations']}次，无新alpha/L1率、无搜索。\n- 小MLP与RL策略新拟合：{counts['neural_policy_fits']}次，共{counts['optimizer_updates']:,}次参数更新。\n- 协方差收缩：{counts['risk_estimator_fits']}次；PCA因子分解：{counts['risk_pca_decompositions']}次。\n- 聚类/异常新拟合：{counts['auxiliary_estimator_fits']}次，辅助scaler {counts['auxiliary_scaler_fits']}次。\n\n## 时间外集成\n\n2024基础预测由截至2023年成熟标签训练的development模型生成；2025基础预测由截至2024年成熟标签训练的validation模型生成。第二层validation融合器只学习2024 OOF，供2025评估；最终融合器学习2024+2025 OOF，供2026评估。最终基础模型用截至2025年的成熟标签拟合。基础分数是效用、概率或神经策略偏好，融合先统一为保留正负号的动作优势排名，再组合或训练元模型。\n\n详细固定公式、参数和预算见ENSEMBLE_CONTRACT.md；真实OOF样本、元模型系数与收据见ensemble_artifacts。等权和分歧融合为固定规则，不伪计为训练拟合。各类预处理均按其训练阶段分别拟合。\n\n拟合终点：development信号2023-12-27、标签2023-12-29；validation信号2024-12-27、标签2024-12-31；final信号2025-12-29、标签2025-12-31。主监督阶段各13,333基础行展开199,995状态动作行，覆盖所有成熟日期；MLP/RL使用完整序列，最多20实际持仓，容量受限成交结果回馈下一状态。\n\n研究边界：固定预算只能限制新增过拟合机会，不能证明没有过拟合；已被观察的历史年份不能恢复成纯净盲测。近一期13F可用池、供应商到达时间、公司行动及价格坐标的限制详见REPORT.md与audit/INPUT_AUDIT.json。\n'''
    text+='\n元模型实际拟合：2次。六基础模型非负系数（rank尺度效用回归系数，非组合持仓比例）：\n\n'
    text+='| 基础模型 | 2025验证融合器 | 2026最终融合器 |\n|---|---:|---:|\n'
    for name,coef in meta[0]['coefficients'].items():
        text+=f"| {name} | {coef:.8f} | {meta[1]['coefficients'][name]:.8f} |\n"
    (ROOT/'TRAINING_SUMMARY.md').write_text(text,encoding='utf-8')
    print(json.dumps(counts))

if __name__=='__main__':main()
