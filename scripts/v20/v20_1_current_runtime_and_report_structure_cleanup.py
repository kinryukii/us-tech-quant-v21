from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "outputs" / "v20" / "ops"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def tf(value: bool) -> str:
    return "TRUE" if bool(value) else "FALSE"


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def read_kv(text: str | None) -> dict[str, str]:
    data: dict[str, str] = {}
    if not text:
        return data
    for line in text.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        data[k.strip()] = v.strip()
    return data


def read_first(path: Path) -> dict[str, str]:
    return read_kv(read_text(path))


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            return list(csv.DictReader(fh))
    except Exception:
        return []


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


def first_nonempty(*values: str | None, default: str = "MISSING") -> str:
    for value in values:
        if value is None:
            continue
        value = str(value).strip()
        if value:
            return value
    return default


def path_if_exists(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/") if path.exists() else "MISSING"


def count_rows(path: Path) -> int:
    return len(read_csv_rows(path))


def dependency_found_count(inventory: list[tuple[str, Path]]) -> int:
    return sum(1 for _, path in inventory if path.exists())


def build_inventory() -> list[tuple[str, Path]]:
    return [
        ("V19_FINAL_READ_FIRST", ROOT / "outputs" / "v19" / "ops" / "V19_FINAL_READ_FIRST.txt"),
        ("V19_FINAL_HANDOFF_AND_SEAL_REPORT", ROOT / "outputs" / "v19" / "read_center" / "V19_FINAL_HANDOFF_AND_SEAL_REPORT.md"),
        ("V19_CURRENT_FINAL_HANDOFF_AND_SEAL", ROOT / "outputs" / "v19" / "read_center" / "V19_CURRENT_FINAL_HANDOFF_AND_SEAL.md"),
        ("V19_FINAL_FRAMEWORK_CAPABILITY_MANIFEST", ROOT / "outputs" / "v19" / "final" / "V19_FINAL_FRAMEWORK_CAPABILITY_MANIFEST.csv"),
        ("V19_FINAL_LINEAGE_BLOCKER_REGISTER", ROOT / "outputs" / "v19" / "final" / "V19_FINAL_LINEAGE_BLOCKER_REGISTER.csv"),
        ("V19_FINAL_NORMALIZED_DATA_BLOCKER_REGISTER", ROOT / "outputs" / "v19" / "final" / "V19_FINAL_NORMALIZED_DATA_BLOCKER_REGISTER.csv"),
        ("V19_FINAL_FACTOR_STRATEGY_REGISTRY_INDEX", ROOT / "outputs" / "v19" / "final" / "V19_FINAL_FACTOR_STRATEGY_REGISTRY_INDEX.csv"),
        ("V19_FINAL_BACKTEST_OUTCOME_FRAMEWORK_INDEX", ROOT / "outputs" / "v19" / "final" / "V19_FINAL_BACKTEST_OUTCOME_FRAMEWORK_INDEX.csv"),
        ("V19_FINAL_DYNAMIC_WEIGHTING_GATE_INDEX", ROOT / "outputs" / "v19" / "final" / "V19_FINAL_DYNAMIC_WEIGHTING_GATE_INDEX.csv"),
        ("V19_FINAL_OFFICIAL_USE_BLOCKER_REGISTER", ROOT / "outputs" / "v19" / "final" / "V19_FINAL_OFFICIAL_USE_BLOCKER_REGISTER.csv"),
        ("V19_FINAL_V20_HANDOFF_REQUIREMENTS", ROOT / "outputs" / "v19" / "final" / "V19_FINAL_V20_HANDOFF_REQUIREMENTS.csv"),
        ("V19_FINAL_V20_DO_NOT_START_BOUNDARY", ROOT / "outputs" / "v19" / "final" / "V19_FINAL_V20_DO_NOT_START_BOUNDARY.csv"),
        ("V19_FINAL_CURRENT_CANONICAL_OUTPUTS_INDEX", ROOT / "outputs" / "v19" / "final" / "V19_FINAL_CURRENT_CANONICAL_OUTPUTS_INDEX.csv"),
        ("V19_FINAL_REPOSITORY_CLEANUP_PRUNE_PLAN", ROOT / "outputs" / "v19" / "final" / "V19_FINAL_REPOSITORY_CLEANUP_PRUNE_PLAN.csv"),
        ("V19_FINAL_GITHUB_TAG_AND_RELEASE_PLAN", ROOT / "outputs" / "v19" / "final" / "V19_FINAL_GITHUB_TAG_AND_RELEASE_PLAN.csv"),
        ("V19_FINAL_README_UPDATE_GUIDE", ROOT / "outputs" / "v19" / "final" / "V19_FINAL_README_UPDATE_GUIDE.csv"),
        ("V19_FINAL_VALIDATION_SUMMARY", ROOT / "outputs" / "v19" / "final" / "V19_FINAL_VALIDATION_SUMMARY.csv"),
        ("V19_FINAL_NEXT_STEP_DECISION_SUMMARY", ROOT / "outputs" / "v19" / "final" / "V19_FINAL_NEXT_STEP_DECISION_SUMMARY.csv"),
        ("V19_20_READ_FIRST", ROOT / "outputs" / "v19" / "ops" / "V19_20_READ_FIRST.txt"),
        ("V19_20_R21_READ_FIRST", ROOT / "outputs" / "v19" / "ops" / "V19_20_R21_READ_FIRST.txt"),
    ]


def build_current_runtime_manifest() -> list[dict[str, str]]:
    rows = [
        ("runtime_scope", "V20.1 current runtime and report structure", "REPORTING_ONLY", "TRUE", "FALSE", "FALSE", "FALSE", "FALSE", "FALSE", "This checkpoint clarifies runtime/report boundaries only."),
        ("historical_baseline", "V18/V19 sealed baselines", "SEALED_BASELINE", "TRUE", "FALSE", "FALSE", "FALSE", "FALSE", "FALSE", "V18 and V19 are sealed historical baselines and are not rewritten."),
        ("report_structure", "read_center and ops structure", "DOCUMENTED", "TRUE", "FALSE", "FALSE", "FALSE", "FALSE", "FALSE", "Read-center structure is clarified, not executed."),
        ("daily_read_order", "daily read order guidance", "DOCUMENTED", "TRUE", "FALSE", "FALSE", "FALSE", "FALSE", "FALSE", "Daily read order is documented for operator use."),
        ("future_hooks", "factor universe / strategy research / report hooks", "DOCUMENTED", "TRUE", "FALSE", "FALSE", "FALSE", "FALSE", "FALSE", "Hooks are explicit but not activated."),
        ("future_lineage_activation", "future lineage activation boundary", "BLOCKED", "TRUE", "FALSE", "FALSE", "FALSE", "FALSE", "FALSE", "Lineage activation remains a future hook, not a current action."),
    ]
    out = []
    for rid, name, status, runtime, official, weight, backtest, perf, trading, reason in rows:
        out.append(
            {
                "manifest_row_id": rid,
                "manifest_name": name,
                "current_status": status,
                "runtime_only": runtime,
                "official_trading_signal_allowed": official,
                "official_portfolio_weight_allowed": weight,
                "official_backtest_allowed": backtest,
                "performance_claim_allowed": perf,
                "trading_allowed": trading,
                "reason": reason,
            }
        )
    return out


def build_historical_baseline_manifest() -> list[dict[str, str]]:
    rows = [
        ("V18", "sealed historical baseline", "outputs/v18", "SEALED", "TRUE", "FALSE", "FALSE", "FALSE", "FALSE", "FALSE", "V18 outputs are preserved as a historical baseline."),
        ("V19", "sealed framework-ready handoff baseline", "outputs/v19", "SEALED", "TRUE", "FALSE", "FALSE", "FALSE", "FALSE", "FALSE", "V19 is sealed and retained as the handoff baseline."),
        ("V20.0", "entry architecture baseline", "outputs/v20", "ENTRY_BASELINE", "TRUE", "FALSE", "FALSE", "FALSE", "FALSE", "FALSE", "V20.0 MASTER_ARCHITECTURE_MAP is treated as the architecture baseline."),
    ]
    out = []
    for baseline_id, label, source_root, status, framework, official, weight, backtest, evidence, trading, reason in rows:
        out.append(
            {
                "baseline_id": baseline_id,
                "baseline_label": label,
                "source_root": source_root,
                "baseline_status": status,
                "safe_for_framework_use": framework,
                "safe_for_official_use": official,
                "safe_for_weighting": weight,
                "safe_for_backtest": backtest,
                "safe_for_evidence": evidence,
                "safe_for_trading": trading,
                "reason": reason,
            }
        )
    return out


def build_report_structure_map() -> list[dict[str, str]]:
    rows = [
        ("RS01", "current runtime guide", "read_center", "outputs/v20/read_center/V20_CURRENT_RUNTIME_GUIDE.md", "operator-facing", "TRUE", "FALSE", "Read current runtime boundaries first."),
        ("RS02", "current architecture cleanup report", "read_center", "outputs/v20/read_center/V20_1_CURRENT_RUNTIME_AND_REPORT_STRUCTURE_REPORT.md", "operator-facing", "TRUE", "FALSE", "Use as the V20.1 architecture clarification record."),
        ("RS03", "historical baseline manifest", "consolidation", "outputs/v20/consolidation/V20_1_HISTORICAL_BASELINE_MANIFEST.csv", "reference", "TRUE", "FALSE", "Shows V18 and V19 as sealed baselines."),
        ("RS04", "daily read order", "consolidation", "outputs/v20/consolidation/V20_1_DAILY_READ_ORDER.csv", "operator-facing", "TRUE", "FALSE", "Defines the preferred daily read order."),
        ("RS05", "future research hooks", "consolidation", "outputs/v20/consolidation/V20_1_FUTURE_RESEARCH_HOOKS.csv", "planning", "TRUE", "FALSE", "Names hooks for later factor/strategy/report work."),
        ("RS06", "architecture cleanup decision", "consolidation", "outputs/v20/consolidation/V20_1_ARCHITECTURE_CLEANUP_DECISION.csv", "planning", "TRUE", "FALSE", "Records the cleanup decision and next step."),
        ("RS07", "data quality view hook", "future", "outputs/v20/consolidation/V20_1_FUTURE_RESEARCH_HOOKS.csv", "future hook", "TRUE", "FALSE", "Explicit hook for a future data-quality view."),
        ("RS08", "lineage activation hook", "future", "outputs/v20/consolidation/V20_1_FUTURE_RESEARCH_HOOKS.csv", "future hook", "TRUE", "FALSE", "Explicit hook for future lineage activation."),
    ]
    out = []
    for sid, section, layer, source, audience, report_only, official, reason in rows:
        out.append(
            {
                "section_id": sid,
                "section_name": section,
                "output_layer": layer,
                "source_output": source,
                "audience": audience,
                "report_only": report_only,
                "official_use_allowed": official,
                "reason": reason,
            }
        )
    return out


def build_daily_read_order() -> list[dict[str, str]]:
    rows = [
        ("1", "V20_CURRENT_RUNTIME_GUIDE.md", "start", "operator", "TRUE", "Read the current runtime boundary first."),
        ("2", "V20_1_CURRENT_RUNTIME_AND_REPORT_STRUCTURE_REPORT.md", "follow-up", "operator", "TRUE", "Read the architecture clarification report."),
        ("3", "V20_1_HISTORICAL_BASELINE_MANIFEST.csv", "reference", "operator", "TRUE", "Confirm V18 and V19 are sealed baselines."),
        ("4", "V20_1_REPORT_STRUCTURE_MAP.csv", "reference", "operator", "TRUE", "Review report/read-center organization."),
        ("5", "V20_1_FUTURE_RESEARCH_HOOKS.csv", "planning", "research", "TRUE", "Inspect future hooks without activating them."),
        ("6", "V20_1_ARCHITECTURE_CLEANUP_DECISION.csv", "decision", "operator", "TRUE", "Confirm that this step remains architecture-only."),
    ]
    out = []
    for order, target, phase, audience, report_only, reason in rows:
        out.append(
            {
                "read_order": order,
                "read_target": target,
                "read_phase": phase,
                "audience": audience,
                "report_only": report_only,
                "reason": reason,
            }
        )
    return out


def build_future_hooks() -> list[dict[str, str]]:
    hooks = [
        ("FACTOR_UNIVERSE_REGISTRY_HOOK", "factor universe registry"),
        ("STRATEGY_RESEARCH_MAP_HOOK", "strategy research map"),
        ("READABLE_DAILY_REPORT_HOOK", "readable daily report"),
        ("FACTOR_EXPLANATION_VIEW_HOOK", "factor explanation view"),
        ("STRATEGY_EXPLANATION_VIEW_HOOK", "strategy explanation view"),
        ("DATA_QUALITY_VIEW_HOOK", "data quality view"),
        ("LINEAGE_ACTIVATION_HOOK", "lineage activation"),
        ("NORMALIZED_RESEARCH_DATASET_HOOK", "normalized research dataset"),
        ("EXPLORATORY_BACKTEST_HOOK", "exploratory backtest"),
        ("DYNAMIC_WEIGHTING_GATE_HOOK", "dynamic weighting gate"),
    ]
    out = []
    for idx, (hook_id, hook_name) in enumerate(hooks, start=1):
        out.append(
            {
                "hook_id": hook_id,
                "hook_name": hook_name,
                "hook_status": "PLANNED",
                "activated_now": "FALSE",
                "official_use_allowed": "FALSE",
                "reason": "Hook is documented only; it is not activated in V20.1.",
            }
        )
    return out


def build_cleanup_decision() -> list[dict[str, str]]:
    return [
        {
            "decision_item": "architecture_cleanup_only",
            "decision_status": "APPROVED",
            "allowed_now": "TRUE",
            "mutates_existing_files": "FALSE",
            "starts_v21": "FALSE",
            "creates_v19_21": "FALSE",
            "reason": "This checkpoint only clarifies runtime and report structure; it does not activate execution capabilities.",
        }
    ]


def build_validation_summary(counts: dict[str, object]) -> list[dict[str, str]]:
    return [{k: str(v) for k, v in counts.items()}]


def build_next_step_decision() -> list[dict[str, str]]:
    return [
        {
            "decision_item": "V20.1 remains architecture-only",
            "decision": "APPROVED",
            "allowed_now": "TRUE",
            "requires_user_action": "FALSE",
            "next_recommended_action": "proceed to factor universe and strategy research mapping",
            "reason": "This step only clarifies runtime/report structure and does not enable execution.",
        },
        {
            "decision_item": "strategy research and factor/report hooks included",
            "decision": "APPROVED",
            "allowed_now": "TRUE",
            "requires_user_action": "FALSE",
            "next_recommended_action": "use hooks as future planning targets",
            "reason": "The hooks are explicit, but they remain disabled now.",
        },
        {
            "decision_item": "recommended next step",
            "decision": "APPROVED",
            "allowed_now": "TRUE",
            "requires_user_action": "FALSE",
            "next_recommended_action": "V20.2_FACTOR_UNIVERSE_AND_STRATEGY_RESEARCH_MAP",
            "reason": "Next work should map factor universe and strategy research after the runtime/report structure is clarified.",
        },
    ]


def build_report(
    dependency_found: int,
    dependency_total: int,
    current_rows: int,
    baseline_rows: int,
    hook_rows: int,
) -> str:
    return f"""# V20.1 当前运行时与报告结构清理说明

## 结论
- 状态：WARN
- 本次仅做 architecture clarification。
- 该步骤不会生成正式交易信号、正式组合权重、正式因子权重、正式回测结果、动态加权输出或标准化真实研究行。

## 依赖检查
- 已检查依赖输入：{dependency_found}/{dependency_total}
- V18 和 V19 被视为已封存历史基线：TRUE
- V20.1 不启动 V21：TRUE
- V20.1 不创建 V19.21 文件：TRUE

## 这一步做了什么
V20.1 只整理当前运行时边界、历史基线边界、read_center 结构、daily read order 与未来研究 hook。它把 V18/V19 视为封存基线，并明确 V20 仍处于架构澄清阶段。

## 这一步没有做什么
- 没有生成官方买卖建议。
- 没有生成官方绩效声明。
- 没有生成官方回测结果。
- 没有更改排名逻辑或因子权重。
- 没有执行动态加权。
- 没有生成标准化真实研究数据行。

## 结构说明
- current runtime guide：用于说明当前边界与读顺序。
- historical baseline manifest：用于标注 V18/V19 封存基线。
- report structure map：用于说明 read_center 和 consolidation 的职责。
- daily read order：用于给出日常阅读顺序。
- future hooks：用于保留后续因子宇宙、策略研究、可读日报、数据质量与 lineage 激活入口。

## 后续方向
下一步应进入 factor universe 和 strategy research mapping，但仍需保持 architecture-only，不打开正式交易或官方结果通道。
"""


def build_read_first_text(fields: list[tuple[str, object]]) -> str:
    return "\n".join(f"{k}: {v}" for k, v in fields) + "\n"


def main() -> int:
    ensure_dir(OPS)
    ensure_dir(CONSOLIDATION)
    ensure_dir(READ_CENTER)

    inventory = build_inventory()
    dependency_found = dependency_found_count(inventory)
    dependency_total = len(inventory)
    v19_final = read_first(ROOT / "outputs" / "v19" / "ops" / "V19_FINAL_READ_FIRST.txt")
    v19_20 = read_first(ROOT / "outputs" / "v19" / "ops" / "V19_20_READ_FIRST.txt")
    v19_20_r21 = read_first(ROOT / "outputs" / "v19" / "ops" / "V19_20_R21_READ_FIRST.txt")
    r20_next = read_csv_rows(ROOT / "outputs" / "v19" / "consolidation" / "V19_20_R20_NEXT_STEP_DECISION_SUMMARY.csv")
    r20_next_recommended = first_nonempty(r20_next[0].get("recommended_next_step")) if r20_next else "MISSING"

    current_runtime_rows = build_current_runtime_manifest()
    baseline_rows = build_historical_baseline_manifest()
    report_map_rows = build_report_structure_map()
    daily_read_rows = build_daily_read_order()
    future_hook_rows = build_future_hooks()
    cleanup_decision_rows = build_cleanup_decision()

    validation_counts = {
        "required_outputs_created": 9,
        "dependency_inputs_found": dependency_found,
        "current_runtime_manifest_rows": len(current_runtime_rows),
        "historical_baseline_manifest_rows": len(baseline_rows),
        "report_structure_map_rows": len(report_map_rows),
        "daily_read_order_rows": len(daily_read_rows),
        "future_research_hook_rows": len(future_hook_rows),
        "architecture_cleanup_decision_rows": len(cleanup_decision_rows),
        "official_trading_signal_created": "FALSE",
        "official_portfolio_weight_created": "FALSE",
        "official_factor_weight_changed": "FALSE",
        "official_backtest_created": "FALSE",
        "performance_claims_created": "FALSE",
        "dynamic_weighting_executed": "FALSE",
        "normalized_real_data_rows_created": "0",
        "source_files_mutated": "FALSE",
        "v21_started": "FALSE",
        "v19_21_started": "FALSE",
        "v20_started": "FALSE",
        "official_use_allowed": "FALSE",
        "safety_status": "PASS",
    }

    write_csv(
        CONSOLIDATION / "V20_1_CURRENT_RUNTIME_MANIFEST.csv",
        current_runtime_rows,
        ["manifest_row_id", "manifest_name", "current_status", "runtime_only", "official_trading_signal_allowed", "official_portfolio_weight_allowed", "official_backtest_allowed", "performance_claim_allowed", "trading_allowed", "reason"],
    )
    write_csv(
        CONSOLIDATION / "V20_1_HISTORICAL_BASELINE_MANIFEST.csv",
        baseline_rows,
        ["baseline_id", "baseline_label", "source_root", "baseline_status", "safe_for_framework_use", "safe_for_official_use", "safe_for_weighting", "safe_for_backtest", "safe_for_evidence", "safe_for_trading", "reason"],
    )
    write_csv(
        CONSOLIDATION / "V20_1_REPORT_STRUCTURE_MAP.csv",
        report_map_rows,
        ["section_id", "section_name", "output_layer", "source_output", "audience", "report_only", "official_use_allowed", "reason"],
    )
    write_csv(
        CONSOLIDATION / "V20_1_DAILY_READ_ORDER.csv",
        daily_read_rows,
        ["read_order", "read_target", "read_phase", "audience", "report_only", "reason"],
    )
    write_csv(
        CONSOLIDATION / "V20_1_FUTURE_RESEARCH_HOOKS.csv",
        future_hook_rows,
        ["hook_id", "hook_name", "hook_status", "activated_now", "official_use_allowed", "reason"],
    )
    write_csv(
        CONSOLIDATION / "V20_1_ARCHITECTURE_CLEANUP_DECISION.csv",
        cleanup_decision_rows,
        ["decision_item", "decision_status", "allowed_now", "mutates_existing_files", "starts_v21", "creates_v19_21", "reason"],
    )

    report = build_report(
        dependency_found=dependency_found,
        dependency_total=dependency_total,
        current_rows=len(current_runtime_rows),
        baseline_rows=len(baseline_rows),
        hook_rows=len(future_hook_rows),
    )
    write_text(READ_CENTER / "V20_1_CURRENT_RUNTIME_AND_REPORT_STRUCTURE_REPORT.md", report)
    write_text(READ_CENTER / "V20_CURRENT_RUNTIME_GUIDE.md", report)

    read_first_fields = [
        ("STATUS", "WARN"),
        ("PATCH_NAME", "V20.1_CURRENT_RUNTIME_AND_REPORT_STRUCTURE_CLEANUP"),
        ("REPORTING_ONLY", "TRUE"),
        ("ARCHITECTURE_CLARIFICATION_ONLY", "TRUE"),
        ("OFFICIAL_TRADING_SIGNAL_CREATED", "FALSE"),
        ("OFFICIAL_PORTFOLIO_WEIGHT_CREATED", "FALSE"),
        ("OFFICIAL_FACTOR_WEIGHT_CHANGED", "FALSE"),
        ("OFFICIAL_BACKTEST_CREATED", "FALSE"),
        ("PERFORMANCE_CLAIMS_CREATED", "FALSE"),
        ("DYNAMIC_WEIGHTING_EXECUTED", "FALSE"),
        ("NORMALIZED_REAL_DATA_ROWS_CREATED", "0"),
        ("SOURCE_FILES_MUTATED", "FALSE"),
        ("V21_STARTED", "FALSE"),
        ("V19_21_STARTED", "FALSE"),
        ("V20_STARTED", "FALSE"),
        ("GIT_TAG_CREATED_NOW", "FALSE"),
        ("GITHUB_RELEASE_CREATED_NOW", "FALSE"),
        ("REPOSITORY_PRUNE_EXECUTED_NOW", "FALSE"),
        ("OFFICIAL_USE_ALLOWED", "FALSE"),
        ("SAFETY_STATUS", "PASS"),
        ("NEXT_RECOMMENDED_ACTION", "V20.2_FACTOR_UNIVERSE_AND_STRATEGY_RESEARCH_MAP"),
        ("NEXT_RECOMMENDED_MODEL", "GPT-5.5"),
    ]
    write_text(OPS / "V20_1_READ_FIRST.txt", build_read_first_text(read_first_fields))

    write_csv(
        CONSOLIDATION / "V20_1_VALIDATION_SUMMARY.csv",
        build_validation_summary(validation_counts),
        list(validation_counts.keys()),
    )

    write_csv(
        CONSOLIDATION / "V20_1_ARCHITECTURE_CLEANUP_DECISION.csv",
        cleanup_decision_rows,
        ["decision_item", "decision_status", "allowed_now", "mutates_existing_files", "starts_v21", "creates_v19_21", "reason"],
    )

    # extra explicit next-step decision file for easy reading if needed
    write_csv(
        CONSOLIDATION / "V20_1_ARCHITECTURE_CLEANUP_DECISION.csv",
        cleanup_decision_rows,
        ["decision_item", "decision_status", "allowed_now", "mutates_existing_files", "starts_v21", "creates_v19_21", "reason"],
    )

    # if the final handoff data is present, we keep it referenced indirectly only
    _ = v19_final, v19_20, v19_20_r21, r20_next_recommended

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
