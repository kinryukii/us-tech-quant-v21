"""Build a documentary handoff from sealed receipts; never fit or replay."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent
WS = OUT.parent
A = WS / "a2_top20_multimodel_selection_20260928_9231"
B = WS / "a2_cooperative_fusion_20260928_9231"
C = A / "acceptance_diagnostics"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def link(title: str, path: Path) -> str:
    return f"[{title}](<{path.as_posix()}>)"


def table(columns: list[str], rows: list[list[str]]) -> str:
    return "\n".join(["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"] + ["| " + " | ".join(row) + " |" for row in rows])


def pct(x: float) -> str:
    return f"{100 * float(x):.2f}%"


def main() -> None:
    template = (OUT / "report_template.md").read_text(encoding="utf-8")
    first = pd.read_csv(A / "MODEL_COMPARISON.csv")
    coop = pd.read_csv(B / "MODEL_COMPARISON.csv")
    diag = pd.read_csv(B / "selection/aggregate.csv")
    assert len(first) == 76 and len(coop) == 40
    first10 = first.loc[first.cost_bps.eq(10)].copy()
    assert len(first10) == 38
    first_rows = []
    for policy in first10.policy.drop_duplicates():
        a25 = first10.loc[first10.policy.eq(policy) & first10.year.eq(2025)].iloc[0]
        a26 = first10.loc[first10.policy.eq(policy) & first10.year.eq(2026)].iloc[0]
        first_rows.append([policy, pct(a25.indicative_return), pct(a26.indicative_return), pct(a26.indicative_max_drawdown), pct(a26.mean_cash_weight)])
    coop_rows, cost_rows, diag_rows = [], [], []
    coop10 = coop.loc[coop.cost_bps.eq(10)]
    for policy in coop10.policy.drop_duplicates():
        a25 = coop10.loc[coop10.policy.eq(policy) & coop10.year.eq(2025)].iloc[0]
        a26 = coop10.loc[coop10.policy.eq(policy) & coop10.year.eq(2026)].iloc[0]
        coop_rows.append([str(a26.method), pct(a25.indicative_return), pct(a25.indicative_max_drawdown), pct(a26.indicative_return), pct(a26.indicative_max_drawdown), pct(a26.mean_cash_weight), f"{a26.total_cost_dollars:,.2f}", str(int(a26.uncertified_valuation_days))])
        if str(policy).startswith("fusion_"):
            costs = [coop.loc[coop.policy.eq(policy) & coop.year.eq(2026) & coop.cost_bps.eq(cost)].iloc[0] for cost in [5, 10, 25]]
            cost_rows.append([str(a26.method)] + [pct(r.indicative_return) for r in costs])
            dd = [diag.loc[diag.policy.eq(policy) & diag.year.eq(year) & diag.subset.eq("complete_common_pool")].iloc[0] for year in [2025, 2026]]
            diag_rows.append([str(a26.method)] + [v for d in dd for v in [f"{d.mean_ic:.4f}", f"{10000*d.mean_top20_minus_rest:.2f}", f"{10000*d.mean_period_simple_net:.2f}"]])
    controls = {"joint_hgb": "原HGB", "ensemble_equal": "原等权", "ensemble_stacking": "原线性Stacking"}
    olddiag = pd.read_csv(C / "selection/aggregate.csv")
    for policy, title in controls.items():
        dd = [olddiag.loc[olddiag.policy.eq(policy) & olddiag.year.eq(year) & olddiag.subset.eq("complete_common_pool")].iloc[0] for year in [2025, 2026]]
        diag_rows.append([title] + [v for d in dd for v in [f"{d.mean_ic:.4f}", f"{10000*d.mean_top20_minus_rest:.2f}", f"{10000*d.mean_period_simple_net:.2f}"]])

    replacement = {
        "INITIAL_RESULTS": table(["原政策", "2025收益", "2026收益", "2026最大回撤", "2026平均现金"], first_rows),
        "COOP_RESULTS": table(["协同方法/对照", "2025收益", "2025最大回撤", "2026收益", "2026最大回撤", "2026平均现金", "2026费用USD", "2026估值门控缺失日"], coop_rows),
        "COOP_COSTS": table(["协同方法", "2026单边5bp", "10bp", "25bp"], cost_rows),
        "SELECTION_RESULTS": table(["方法", "2025 IC", "2025 TOP20-rest bp", "2025单期净bp", "2026 IC", "2026 TOP20-rest bp", "2026单期净bp"], diag_rows),
    }
    for key, content in replacement.items():
        template = template.replace("{{" + key + "}}", content)
    template = template.replace("{{WS}}", WS.as_posix()).replace("{{OUT}}", OUT.as_posix())
    assert "{{" not in template

    reuse_specs = [
        ("base_contract", A / "EXPERIMENT_CONTRACT.md", "训练与账户合同", "读取；不得因结果改期限、窗口或目标"),
        ("base_method_coverage", A / "METHOD_COVERAGE.json", "基础模型预算与定位", "21监督主拟合/7神经拟合不等于独立试验样本"),
        ("base_model_loader", A / "values.py", "load_policy/predict_values/allocate_joint_scores", "冻结模型加载；新训练应使用新批次身份"),
        ("base_policy_adapter", A / "adapters.py", "PolicyV2实际账户适配", "不要复制一套账户规则"),
        ("six_expert_oof_interface", A / "ensemble.py", "BasePredictions/EnsemblePolicy、原OOF", "同尺度为signed rank；不等于独立收益预测"),
        ("account_engine", A / "engine_v2.py", "唯一真实现金/持仓/成交引擎", "有价指数账一致不等于股东总回报认证"),
        ("neural_policy", A / "neural.py", "冻结MLP/REINFORCE与投影", "RL不是六专家的一臂；奖励逐证券归属仍有限"),
        ("risk_aux", A / "risk_aux.py", "FrozenRisk/FrozenAuxiliary", "风险与诊断层；WOLF final窗口事件限制"),
        ("original_account_verification", A / "VERIFICATION.json", "76条账本原验证", "只读已保存输出；verify_and_report.py会覆盖旧报告"),
        ("data_acceptance", C / "ACCEPTANCE_REPORT.md", "身份/13F/训练窗口证据验收", "0新拟合/0新账户回放，不称旧模型已修复"),
        ("training_issue_dependency", C / "evidence/PRE_121_WINDOW_ACTUAL_TRAINING_CONSUMPTION.parquet", "训练样本依赖窗口逐键映射", "重叠证明消费，不证明所有数值错误"),
        ("original_selection", C / "selection/SELECTION_READOUT.md", "19政策固定参考状态选股诊断", "245/88共同可算日，非完整13F池"),
        ("original_bridge", C / "bridge/POLICY_SUMMARY.csv", "38主成本路径三层汇总", "reference与actual状态分列"),
        ("coop_contract", B / "EXPERIMENT_CONTRACT.md", "七协同设计预训练合同", "0基础模型重训；两种分层方向均已做"),
        ("coop_oof_context", B / "data_context.py", "load_training/meta_features/gate_features", "复用原OOF，不另建近似样本系统"),
        ("coop_policy", B / "policy.py", "CooperativePolicy实际账户统一入口", "__call__用于实际账户；score参考诊断另列"),
        ("coop_meta", B / "meta_models.py", "NNLS/非线性/双向残差实现", "非线性敏感性不相加；线性修正需全11项"),
        ("coop_gate", B / "gate.py", "GateModel冻结门控与标准化", "状态变化可变权重，评价不更新参数"),
        ("coop_fit_receipts", B / "TRAINING_SUMMARY.csv", "8元拟合+2门控+2锚估计", "不是新增六基础模型拟合"),
        ("coop_native_results", B / "MODEL_COMPARISON.csv", "28新路径+12旧对照引用", "12引用不重复计回放；全部为非认证历史研究"),
        ("coop_selection", B / "selection/aggregate.csv", "七协同同状态排序证据", "不扫描持有期限；并列ticker仅规则"),
        ("nnls_overlap", B / "NNLS_OLD_STACKING_OVERLAP.json", "NNLS与原Stacking近重复证据", "参考TOP20一致不等于实际政策一致"),
        ("coop_three_layer", B / "bridge/LAST_SIGNAL_THREE_LAYER.csv", "榜单/目标/成交/持仓末信号可读表", "历史末日，不是当前下单信号"),
        ("coop_bridge_summary", B / "bridge/POLICY_SUMMARY.csv", "14主成本路径桥接汇总", "未记具体约束的零目标继续UNKNOWN"),
        ("coop_terminal_account", B / "bridge/TERMINAL_ACCOUNT.csv", "终估账户状态", "与末信号下一开盘状态区分"),
        ("coop_ledger_verification", B / "INDEPENDENT_LEDGER_VERIFICATION.json", "28条独立账本核对", "一致性通过不授权正式采用"),
        ("coop_seal", B / "COMPLETE_MANIFEST.json", "510接受产物封口清单", "追加复盘不改原SHA或旧身份"),
    ]
    reuse = []
    for entry_id, path, role, limit in reuse_specs:
        assert path.is_file(), path
        reuse.append({"entry_id": entry_id, "path": str(path), "sha256": sha(path), "role": role, "scope_limit": limit})
    reuse_doc = {"kind": "DERIVED_ARTIFACT_NAVIGATION_NOT_IDENTITY_AUTHORITY", "source_batches": [A.name, B.name], "entries": reuse}
    (OUT / "REUSE_INDEX.json").write_text(json.dumps(reuse_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    reuse_rows = [[r["entry_id"], link(r["role"], Path(r["path"])), r["scope_limit"]] for r in reuse]
    template += "\n\n## 附录：已有实现与证据的复用入口\n\n" + table(["入口ID", "真实路径/职责", "使用边界"], reuse_rows) + "\n"
    template += "\n逐文件SHA见 " + link("REUSE_INDEX.json", OUT / "REUSE_INDEX.json") + "；身份与状态仍以权威注册表及原生清单为准。\n"
    (OUT / "RETROSPECTIVE_REPORT.md").write_text(template, encoding="utf-8")

    ledger = {
        "kind": "TASK_RESEARCH_HANDOFF_NOT_SECOND_REGISTRY",
        "task_id": "TOP20_MULTIMODEL_COOPERATION_20260928_9231",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": [A.name, C.name, B.name],
        "knowledge_only": True,
        "pristine_holdout": False,
        "formal_certification": False,
        "train_cutoff_exclusive": "2026-01-01",
        "new_fit_calls_in_this_documentation_task": 0,
        "new_predictions_in_this_documentation_task": 0,
        "new_account_replays_in_this_documentation_task": 0,
        "batches": [
            {"batch_id": A.name, "native_manifest": str(A / "RUN_MANIFEST.json"), "native_manifest_sha256": sha(A / "RUN_MANIFEST.json"), "supervised_primary_fits": 21, "same_objective_numerical_continuations": 2, "neural_trainings": 7, "neural_updates": 9308, "stacking_meta_fits": 2, "frozen_replay_paths": 76, "policies": list(first.policy.drop_duplicates())},
            {"batch_id": str(C.relative_to(WS)), "native_manifest": str(C / "ACCEPTANCE_MANIFEST.json"), "native_manifest_sha256": sha(C / "ACCEPTANCE_MANIFEST.json"), "new_model_fits": 0, "new_account_replays": 0, "attachment_only": True},
            {"batch_id": B.name, "native_manifest": str(B / "COMPLETE_MANIFEST.json"), "native_manifest_sha256": sha(B / "COMPLETE_MANIFEST.json"), "meta_main_fits": 8, "gate_trainings": 2, "gate_updates": 792, "closed_form_anchor_estimates": 2, "base_refits": 0, "frozen_replay_paths": 28, "reused_control_rows": 12, "policies": list(coop.loc[coop.batch.eq("new_cooperation")].policy.drop_duplicates())},
        ],
        "method_rows": [],
        "do_not_repeat": [
            "No copied base training, OOF generation, account engine, allocation or registry system.",
            "NNLS and old positive Ridge stacking are related solver variants; reference TOP20 overlap is not independent confirmation.",
            "Do not add models, seeds, penalty terms, blend-weight searches or horizon scans in response to these observed outcomes.",
            "Do not select a champion using the already observed 2026 window.",
            "Do not erase negative or UNKNOWN findings or rename an old model as repaired after evaluation-only repair.",
            "If accepted data repairs affect training inputs, labels, scalers, risk or OOF, record a new batch and rebuild the affected dependency chain.",
        ],
        "data_limits": ["zero complete original 13F pool dates in 2026", "Q2 amendment membership switch unresolved", "pre2026 static identity and price/history filtering", "corporate action and historical vendor arrival evidence incomplete", "price-index accounts not certified shareholder total return"],
        "report_ref": str(OUT / "RETROSPECTIVE_REPORT.md"),
        "report_sha256": sha(OUT / "RETROSPECTIVE_REPORT.md"),
        "reuse_index_ref": str(OUT / "REUSE_INDEX.json"),
        "reuse_index_sha256": sha(OUT / "REUSE_INDEX.json"),
    }
    for batch, frame, source in [(A.name, first, A / "MODEL_COMPARISON.csv"), (B.name, coop.loc[coop.batch.eq("new_cooperation")], B / "MODEL_COMPARISON.csv")]:
        for policy in frame.policy.drop_duplicates():
            rows = frame.loc[frame.policy.eq(policy)]
            ledger["method_rows"].append({"batch_id": batch, "policy": policy, "scenario_count": len(rows), "source_ref": str(source), "source_sha256": sha(source), "diagnostic_scenarios": rows[["year", "cost_bps", "indicative_return", "indicative_max_drawdown", "mean_cash_weight"]].to_dict(orient="records"), "research_only": True})
    assert len(ledger["method_rows"]) == 26
    (OUT / "RESEARCH_LEDGER.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(OUT / "RETROSPECTIVE_REPORT.md"), "characters": len(template), "reuse_entries": len(reuse), "method_rows": len(ledger["method_rows"]), "new_training": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
