"""Seal artifacts and render the bounded comparison report (no fitting)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from fit import OUT, SOURCE, FEATURES, SPECS, sha, write_json

MAIN = ("hgb", "ridge", "elastic_net", "mlp")
ALL = (*MAIN, "quantile_50_diagnostic")


def frame_hash(frame: pd.DataFrame) -> str:
    return hashlib.sha256(pd.util.hash_pandas_object(frame, index=False).to_numpy().tobytes()).hexdigest()


def main():
    matrix = pd.read_parquet(SOURCE / "A2/training_matrix.parquet").sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    ref = pd.read_parquet(SOURCE / "A2/oof_predictions.parquet").sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    ev = json.loads((OUT / "evaluation.json").read_text(encoding="utf-8"))
    original = joblib.load(SOURCE / "A2/final_full_pre2026_hgb.joblib")
    fresh = joblib.load(OUT / "hgb/final_full_pre2026.joblib")
    X = matrix.loc[:, FEATURES].to_numpy(float)
    final_delta = float(np.max(np.abs(original.predict(X) - fresh.predict(X))))
    assert final_delta == 0.0
    identity = {"training_matrix_sha256": sha(SOURCE / "A2/training_matrix.parquet"),
                "training_rows": len(matrix), "training_dates": matrix.signal_date.nunique(), "training_tickers": matrix.ticker.nunique(),
                "train_signal_min": str(matrix.signal_date.min().date()), "train_signal_max": str(matrix.signal_date.max().date()),
                "target_end_max": str(matrix.target_end_date.max().date()),
                "training_keys_sha256": frame_hash(matrix[["signal_date", "ticker"]]),
                "training_X_y_missing_count": int(matrix[[*FEATURES, "target"]].isna().sum().sum()),
                "training_X_y_sha256": frame_hash(matrix[[*FEATURES, "target"]]),
                "weight_contract": "all unit weights: original fit passed no sample_weight",
                "oof_keys_sha256": frame_hash(ref[["signal_date", "ticker"]]),
                "oof_rows": len(ref), "oof_dates": ref.signal_date.nunique(), "oof_tickers": ref.ticker.nunique(),
                "daily_dynamic_pool_source": str(SOURCE / "universe/daily_eligible_universe_membership.parquet"),
                "daily_dynamic_pool_sha256": sha(SOURCE / "universe/daily_eligible_universe_membership.parquet"),
                "final_hgb_old_sha256": sha(SOURCE / "A2/final_full_pre2026_hgb.joblib"),
                "final_hgb_new_prediction_max_abs_difference_on_training_matrix": final_delta,
                "original_portfolio_daily_sha256": sha(SOURCE / "A2/portfolio_daily.parquet"),
                "reconstructed_price_sha256": ev["price_sha256"],
                "hgb_old_nav_max_abs_difference": ev["methods"]["hgb"]["old_nav_max_abs_difference"]}
    identity["fold_identity"] = {}
    for stage, year in (("DEVELOPMENT", 2023), ("CONFIRMATION", 2024), ("FINAL", 2025)):
        first = ref.loc[ref.signal_date.dt.year.eq(year), "signal_date"].min()
        train = matrix.loc[matrix.signal_date.lt(f"{year}-01-01") & matrix.target_end_date.lt(first)]
        test = ref.loc[ref.signal_date.dt.year.eq(year)]
        identity["fold_identity"][stage] = {"train_rows": len(train), "train_dates": train.signal_date.nunique(),
            "train_tickers": train.ticker.nunique(), "train_key_sha256": frame_hash(train[["signal_date", "ticker"]]),
            "train_X_y_sha256": frame_hash(train[[*FEATURES, "target"]]),
            "evaluation_rows": len(test), "evaluation_dates": test.signal_date.nunique(),
            "evaluation_tickers": test.ticker.nunique(), "evaluation_key_sha256": frame_hash(test[["signal_date", "ticker"]])}
    write_json(OUT / "identity_audit.json", identity)
    rows = []
    for m in MAIN:
        pm = json.loads((OUT / m / "pre2026_metrics.json").read_text(encoding="utf-8"))
        for stage, p in pm.items():
            d = pd.read_parquet(OUT / m / "daily_prediction_metrics.parquet")
            year = {"DEVELOPMENT": 2023, "CONFIRMATION": 2024, "FINAL": 2025}[stage]
            dd = d.loc[d.signal_date.dt.year.eq(year)]
            rows.append({"method": m, "stage": stage, **p, "rank_ic_mean": float(dd.rank_ic.mean()), "top20_target_mean": float(dd.top20_mean_target.mean())})
    pd.DataFrame(rows).to_csv(OUT / "oof_stage_summary.csv", index=False)
    quantile = pd.read_parquet(OUT / "quantile_50_diagnostic/pre2026_oof.parquet")
    quantile = quantile.merge(ref[["signal_date", "ticker", "target"]], on=["signal_date", "ticker"], validate="one_to_one")
    quantile = quantile.loc[quantile.target.notna()]
    q_error = quantile.target.to_numpy(float) - quantile.prediction.to_numpy(float)
    write_json(OUT / "quantile_diagnostic.json", {"q": 0.5, "learning_object": "conditional median, not conditional mean",
         "labeled_rows": len(quantile), "pinball_loss": float(np.maximum(0.5 * q_error, -0.5 * q_error).mean()),
         "empirical_below_prediction_fraction": float(np.mean(q_error <= 0)),
         "trading_readout_status": "NOT_FROZEN; NO_STRATEGY_COMPARISON"})
    coverage = [
        ("HGB", "direct_comparison", "four new fits; exact numerical reproduction"),
        ("Ridge", "direct_comparison", "four new fits; train-only internal scaling disclosed"),
        ("Elastic Net", "direct_comparison", "four new fits; train-only internal scaling disclosed"),
        ("small MLP", "direct_comparison", "four new fits; train-only internal scaling disclosed"),
        ("other GBDT/XGB", "implementation_blocked", "fixed old XGBRegressor specification found; xgboost unavailable in current Python; no local wheel"),
        ("quantile regression", "named_estimator_variant", "q=0.5 diagnostic fitted four times; conditional median, no frozen trading readout"),
        ("distribution prediction", "undefined_estimator", "no existing compatible distribution family and conditional mean readout"),
        ("PCA plus return regression", "undefined_estimator", "no compatible named estimator/readout on original A2 panel"),
        ("cluster conditional regression", "undefined_estimator", "no compatible named estimator/readout on original A2 panel"),
        ("logistic regression", "incompatible", "requires a derived classification target"),
        ("factor risk/covariance", "incompatible", "estimates risk rather than original per-security return target"),
        ("constrained portfolio optimization", "incompatible", "changes frozen Top20 equal-weight policy"),
        ("standalone anomaly detection", "incompatible", "score is not the original continuous return target"),
        ("trading reinforcement learning", "incompatible", "requires new reward, state, and action policy"),
    ]
    pd.DataFrame(coverage, columns=["method", "status", "reason"]).to_csv(OUT / "method_coverage.csv", index=False)
    models = {}
    effective_params = {}
    for m in ALL:
        logs = json.loads((OUT / m / "fit_log.json").read_text(encoding="utf-8"))
        assert len(logs) == 4 and all(x["fit_count"] == 1 for x in logs)
        models[m] = {"spec": SPECS[m], "fits": [{"stage": x["stage"], "sha256": x["model_sha256"], "rows": x["train_rows"]} for x in logs],
                     "oof_sha256": sha(OUT / m / "pre2026_oof.parquet")}
        effective_params[m] = joblib.load(OUT / m / "final_full_pre2026.joblib").get_params(deep=True)
    write_json(OUT / "effective_model_parameters.json", effective_params)
    write_json(OUT / "pre2026_model_freeze.json", {"status": "FROZEN_BEFORE_ANY_2026_TEST", "models": models,
         "common_frozen_sha256": sha(OUT / "common_frozen.json"),
         "test2026": {"status": "NOT_RUN_END_DATE_UNBOUND", "reason": "Original A2 source/freeze has no explicit 2026 test endpoint; no current-data extension authorized"}})
    lines = ["# 原 A2 同条件学习方法重训：本批终态", "", "## 结果", "",
        "已在原 A2 32 特征、520,328 行连续标签矩阵上新拟合 HGB、Ridge、Elastic Net、小型 MLP。每种方法训练 2023/2024/2025 三折与最终 pre2026 模型，共 16 次主比较 fit；另以原 y 拟合 q=0.5 条件分位数 4 次，只做预测诊断。未读取 2026 经济结果，也未执行 2026 测试。", "",
        f"新 HGB 三折与原 OOF 的预测和排名逐行一致；最终模型在全部训练行的预测最大绝对差为 {final_delta:g}。原执行引擎重放的新 HGB 净值与冻结 A2 每日净值最大差为 {ev['methods']['hgb']['old_nav_max_abs_difference']:g}。序列化哈希差异不影响该数值复现。", "",
        "## 共同条件与差异", "",
        f"训练矩阵 SHA256 `{identity['training_matrix_sha256']}`，行数 {identity['training_rows']:,}、日期 {identity['training_dates']}、证券 {identity['training_tickers']}；信号 {identity['train_signal_min']} 至 {identity['train_signal_max']}，标签终点至 {identity['target_end_max']}。全部训练与评估特征有限、无缺失；样本权重同原 fit 为单位权重。评估池来自原每日动态 13F 成员清单，2023–2025 OOF 共 {identity['oof_rows']:,} 行、{identity['oof_dates']} 日、{identity['oof_tickers']} 证券。", "",
        "Ridge、Elastic Net 和 MLP 的 StandardScaler 位于各自学习器管线内部，每折仅在该折训练行拟合；原 HGB 输入及外部预处理没有变化。Ridge 参数借用先前同目标预登记；Elastic Net 与本批小型 MLP 为本批结果揭示前固定的单一规格，无搜索。完整参数及环境在 `common_frozen.json`。", "",
        "## 2023–2025 原时钟组合回放", "",
        "下表使用原执行函数、下一开盘、Top20 等权和原 10bp 成本公式。数值是已暴露历史 OOF，不是新的盲测或真实股东净收益；价格为原调整坐标。", "",
        "| 方法 | 年化复合收益 | 最大回撤 | 年化波动 | 累计换手 | 平均 Rank IC |", "|---|---:|---:|---:|---:|---:|"]
    for m in MAIN:
        e = ev["methods"][m]
        lines.append(f"| {m} | {e['cagr']:.2%} | {e['max_drawdown']:.2%} | {e['annualized_volatility']:.2%} | {e['total_turnover']:.2f} | {e['rank_ic_mean']:.4f} |")
    lines += ["", "逐折误差、TOP20 与原 A2 重合数、Rank IC 和原标签 TOP20 均值见 `oof_stage_summary.csv`；逐日选择、预测、持仓、交易和净值账本均已保存。q=0.5 分位数的 pinball 损失与覆盖率单列在 `quantile_diagnostic.json`，不参与收益策略胜负。各方法差异不能由单一收益指标决定。", "",
        "## 覆盖与待绑定对象", "", "逐项状态见 `method_coverage.csv`。XGB 有旧固定规格但当前 Python 无 xgboost 包且本地无 wheel，故未伪称已 fit。PCA、聚类条件回归和分布模型缺同目标固定估计器及读出；普通逻辑回归、风险模型、固定政策下的组合优化、单独异常检测及交易强化学习与严格替换条件不兼容。", "",
        "原 A2 冻结合同未指定 2026 测试终点。2026 测试需先绑定该终点及同版本全池特征、价格和执行输入；本批最终模型已在 `pre2026_model_freeze.json` 统一冻结，届时只允许 predict/transform。当前不报告 2026 结果。", "",
        "## 复现", "", "在本目录运行 `python fit.py hgb`、`python fit.py ridge`、`python fit.py elastic_net`、`python fit.py mlp`、`python fit.py quantile_50_diagnostic`，再运行 `python evaluate.py`、`python finalize.py`。这些命令会重新拟合，已保存产物可直接审阅。原数据与旧批次均只读。", ""]
    (OUT / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
