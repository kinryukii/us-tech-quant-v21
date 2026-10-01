# A2 retained historical source

这里只保管已有研究的历史源码。原 run_id、原文件名、R1/R2 和冻结 bytes 保留是本次迁移的 custody 命名说明，不创建新实现家族，也不表示算法 promotion、研究重新开放或生产采用。迁移版本为 `a2_storage_alignment_20261001_r1`，导航角色是 STORAGE_FACT_ONLY。

请从 [最终版本导航](D:\us-tech-quant-results\_maintenance\a2_storage_alignment_20261001\VERSION_CATALOG.json) 和 [迁移报告](D:\us-tech-quant-results\_maintenance\a2_storage_alignment_20261001\REPORT.md) 查看实际 source/test/report/cache/envs/backtest 分类。历史测试保留在 `tests/research/a2/retained`；ROOT/WS capsule 在 D backtests，保留历史路径上下文。源码对 capsule 使用同 D hardlink，不改成文件 symlink；READONLY 只是误改保护，冻结仍以 SHA 为准，Git checkout 不保证 hardlink 拓扑。

不要从 repo retained 直接执行历史脚本。代码可能按 `__file__`、ROOT 或 WS 写旁路结果，旧 C/F 绝对路径以及旧 receipt 仍是冻结内容；D capsule 也不是自动重跑入口。已有 F 缺失、读取拒绝和前期研究限制不能靠本次迁移补齐或解除。新授权的实现须优先复用现有 A2 类别模块和既有 maintenance 入口，不复制这些 run 生成新版本 family。

- `a2_13f_conversation_training_summary_registry_20260926`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_13f_conversation_training_summary_registry_20260926`；`LOCAL_COMPATIBILITY_ACTIVE`。
- `a2_13f_learned_sizing_pre2026_test2026_r1`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_13f_learned_sizing_pre2026_test2026_r1`；`LOCAL_COMPATIBILITY_ACTIVE`。
- `a2_13f_research_adjudication_and_reuse_r1`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_13f_research_adjudication_and_reuse_r1`；`LOCAL_COMPATIBILITY_ACTIVE`。
- `a2_buy_sell_cash_multimodel_20260928`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_buy_sell_cash_multimodel_20260928`；`LOCAL_COMPATIBILITY_ACTIVE`。
- `a2_calibration_retest_20260929_r1`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_calibration_retest_20260929_r1`；`LOCAL_COMPATIBILITY_ACTIVE_WITH_ACCESS_EXCLUSIONS`。
- `a2_capacity_in_training_paired_20260927`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_capacity_in_training_paired_20260927`；`LOCAL_COMPATIBILITY_ACTIVE_WITH_ACCESS_EXCLUSIONS`。
- `a2_collaboration_methods_20260928_r1`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_collaboration_methods_20260928_r1`；`LOCAL_COMPATIBILITY_ACTIVE`。
- `a2_complete_suite_20260927`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_complete_suite_20260927`；`LOCAL_COMPATIBILITY_ACTIVE`。
- `a2_complete_suite_nearest_effective_20260927`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_complete_suite_nearest_effective_20260927`；`LOCAL_COMPATIBILITY_ACTIVE_WITH_ACCESS_EXCLUSIONS`。
- `a2_contextual_stacking_r1_20260928`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_contextual_stacking_r1_20260928`；`LOCAL_COMPATIBILITY_ACTIVE`。
- `a2_contextual_stacking_r1_retrospective_registry_20260928`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_contextual_stacking_r1_retrospective_registry_20260928`；`LOCAL_COMPATIBILITY_ACTIVE`。
- `a2_cooperative_fusion_20260928_9231`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_cooperative_fusion_20260928_9231`；`LOCAL_COMPATIBILITY_ACTIVE_WITH_ACCESS_EXCLUSIONS`。
- `a2_cross_year_explanation_audit_20260929`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_cross_year_explanation_audit_20260929`；`LOCAL_COMPATIBILITY_ACTIVE`。
- `a2_ensemble_attribution_20260928_r1`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_ensemble_attribution_20260928_r1`；`LOCAL_COMPATIBILITY_ACTIVE`。
- `a2_history_baseline_windows_20260929_r1`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_history_baseline_windows_20260929_r1`；`LOCAL_COMPATIBILITY_ACTIVE`。
- `a2_latest_effective_joint_20260927`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_latest_effective_joint_20260927`；`LOCAL_COMPATIBILITY_ACTIVE_WITH_ACCESS_EXCLUSIONS`。
- `a2_multimodel_joint_20260928`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_multimodel_joint_20260928`；`LOCAL_COMPATIBILITY_ACTIVE_WITH_ACCESS_EXCLUSIONS`。
- `a2_multimodel_joint_review_20260928`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_multimodel_joint_review_20260928`；`LOCAL_COMPATIBILITY_ACTIVE`。
- `a2_predict_then_optimize_20260928_r1`：历史外部 capsule `D:\us-tech-quant-backtests\a2_predict_then_optimize_20260928_r1`；`NINE_LOCAL_C_CHILD_VIEWS_ACTIVE_C_ROOT_HISTORICAL_STUB_AND_DENIED_CACHE_PRESERVED`。
- `a2_pto_full_compat_20260928_r1`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_pto_full_compat_20260928_r1`；`LOCAL_COMPATIBILITY_ACTIVE_WITH_ACCESS_EXCLUSIONS`。
- `a2_pto_full_compat_20260928_r2`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_pto_full_compat_20260928_r2`；`LOCAL_COMPATIBILITY_ACTIVE_WITH_ACCESS_EXCLUSIONS`。
- `a2_qualification_holdings_v1_20260927`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_qualification_holdings_v1_20260927`；`LOCAL_COMPATIBILITY_ACTIVE`。
- `a2_strict_method_retrain_20260926`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_strict_method_retrain_20260926`；`SOURCE_PRESERVED_UNREADABLE_DEPENDENCY`。
- `a2_task_training_handoff_registry_20260928_r1`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_task_training_handoff_registry_20260928_r1`；`LOCAL_COMPATIBILITY_ACTIVE`。
- `a2_top20_13f_sizing_pilot_r1`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_top20_13f_sizing_pilot_r1`；`LOCAL_COMPATIBILITY_ACTIVE_WITH_ACCESS_EXCLUSIONS`。
- `a2_top20_action_nn_20260925`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_top20_action_nn_20260925`；`LOCAL_COMPATIBILITY_ACTIVE`。
- `a2_top20_all_methods_20260925`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_top20_all_methods_20260925`；`LOCAL_COMPATIBILITY_ACTIVE`。
- `a2_top20_clock_retrain_r1_20260926`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_top20_clock_retrain_r1_20260926`；`LOCAL_COMPATIBILITY_ACTIVE`。
- `a2_top20_multimodel_selection_20260928_9231`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_top20_multimodel_selection_20260928_9231`；`LOCAL_COMPATIBILITY_ACTIVE_WITH_ACCESS_EXCLUSIONS`。
- `a2_top20_task_retrospective_20260928_9231`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\a2_top20_task_retrospective_20260928_9231`；`LOCAL_COMPATIBILITY_ACTIVE`。
- `original_A2_scores_common_account_reference_r1`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\original_A2_scores_common_account_reference_r1`；`LOCAL_COMPATIBILITY_ACTIVE`。
- `top20_multimethod_pre2026_test2026_r1`：历史外部 capsule `D:\us-tech-quant-backtests\a2_research\top20_multimethod_pre2026_test2026_r1`；`LOCAL_COMPATIBILITY_ACTIVE_WITH_ACCESS_EXCLUSIONS`。
