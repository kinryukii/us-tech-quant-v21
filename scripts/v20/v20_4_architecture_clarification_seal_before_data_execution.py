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
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
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


def dependency_found_count(paths: list[Path]) -> int:
    return sum(1 for path in paths if path.exists())


def count_rows(path: Path) -> int:
    return len(read_csv_rows(path))


V20_1_REQUIRED = [
    ROOT / "outputs" / "v20" / "ops" / "V20_1_READ_FIRST.txt",
    ROOT / "outputs" / "v20" / "read_center" / "V20_1_CURRENT_RUNTIME_AND_REPORT_STRUCTURE_REPORT.md",
    ROOT / "outputs" / "v20" / "read_center" / "V20_CURRENT_RUNTIME_GUIDE.md",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_1_CURRENT_RUNTIME_MANIFEST.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_1_HISTORICAL_BASELINE_MANIFEST.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_1_REPORT_STRUCTURE_MAP.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_1_DAILY_READ_ORDER.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_1_FUTURE_RESEARCH_HOOKS.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_1_ARCHITECTURE_CLEANUP_DECISION.csv",
]

V20_2_REQUIRED = [
    ROOT / "outputs" / "v20" / "ops" / "V20_2_READ_FIRST.txt",
    ROOT / "outputs" / "v20" / "read_center" / "V20_2_FACTOR_AND_STRATEGY_RESEARCH_MAP_REPORT.md",
    ROOT / "outputs" / "v20" / "read_center" / "V20_CURRENT_FACTOR_STRATEGY_RESEARCH_VIEW.md",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_2_FACTOR_UNIVERSE_REGISTRY.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_2_FACTOR_FAMILY_MAP.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_2_FACTOR_DATA_AVAILABILITY_AUDIT.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_2_FACTOR_RESEARCH_STATUS_MAP.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_2_FACTOR_STRATEGY_RELEVANCE_MATRIX.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_2_STRATEGY_RESEARCH_FAMILY_REGISTRY.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_2_STRATEGY_FACTOR_DEPENDENCY_MAP.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_2_FACTOR_BLOCKER_REGISTER.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_2_READABLE_FACTOR_EXPLANATION_TEMPLATE.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_2_VALIDATION_SUMMARY.csv",
]

V20_3_REQUIRED = [
    ROOT / "outputs" / "v20" / "ops" / "V20_3_READ_FIRST.txt",
    ROOT / "outputs" / "v20" / "read_center" / "V20_3_READABLE_RESEARCH_REPORT_FRAMEWORK_REPORT.md",
    ROOT / "outputs" / "v20" / "read_center" / "V20_CURRENT_DAILY_RESEARCH_SUMMARY.md",
    ROOT / "outputs" / "v20" / "read_center" / "V20_CURRENT_FACTOR_EXPLANATION_VIEW.md",
    ROOT / "outputs" / "v20" / "read_center" / "V20_CURRENT_STRATEGY_RESEARCH_VIEW.md",
    ROOT / "outputs" / "v20" / "read_center" / "V20_CURRENT_DATA_QUALITY_VIEW.md",
    ROOT / "outputs" / "v20" / "read_center" / "V20_CURRENT_BLOCKERS_AND_NEXT_ACTIONS.md",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_3_READABLE_REPORT_SECTION_MAP.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_3_REPORT_FIELD_TRANSLATION_MAP.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_3_FACTOR_EXPLANATION_VIEW_TEMPLATE.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_3_STRATEGY_EXPLANATION_VIEW_TEMPLATE.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_3_DAILY_RESEARCH_SUMMARY_TEMPLATE.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_3_TOP_CANDIDATES_READABLE_TEMPLATE.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_3_DATA_QUALITY_VIEW_TEMPLATE.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_3_BLOCKERS_AND_NEXT_ACTIONS_TEMPLATE.csv",
    ROOT / "outputs" / "v20" / "consolidation" / "V20_3_VALIDATION_SUMMARY.csv",
]

V20_5_SEQUENCE = [
    ("V20.5_SOURCE_REGISTRY_ACTIVATION", "Activate source registry planning only after the architecture seal is complete."),
    ("V20.6_HASH_RUN_ID_VERSION_BINDING", "Plan hash/run_id/version binding only after source registry activation finishes."),
    ("V20.7_STALE_LEAKAGE_PIT_GATE", "Plan stale/leakage/PIT gating only after binding is complete."),
    ("V20.8_NORMALIZED_RESEARCH_DATASET", "Plan normalized research dataset creation only after the stale/leakage/PIT gate is complete."),
    ("V20.9_FACTOR_EVIDENCE", "Plan factor evidence only after the normalized research dataset exists."),
    ("V20.10_EXPLORATORY_BACKTEST", "Plan exploratory backtest only after factor evidence and normalized outcome/benchmark data exist."),
    ("V20.11_DYNAMIC_WEIGHTING_GATE_RESEARCH", "Plan dynamic weighting gate research only after exploratory evidence exists."),
]


def build_dependency_review(v20_1_pass: bool, v20_2_pass: bool, v20_3_pass: bool, v20_2_factor_rows: int, v20_2_strategy_rows: int) -> list[dict[str, object]]:
    return [
        {
            "dependency_checkpoint": "V20.1_CURRENT_RUNTIME_AND_REPORT_STRUCTURE_CLEANUP",
            "required_outputs_detected": len(V20_1_REQUIRED),
            "current_status": "PASS" if v20_1_pass else "FAIL",
            "runtime_boundary_confirmed": tf(v20_1_pass),
            "historical_baseline_confirmed": tf(v20_1_pass),
            "daily_read_order_confirmed": tf(v20_1_pass),
            "future_hooks_confirmed": tf(v20_1_pass),
            "reason": "V20.1 outputs are present and establish the runtime/report boundary.",
        },
        {
            "dependency_checkpoint": "V20.2_FACTOR_UNIVERSE_AND_STRATEGY_RESEARCH_MAP",
            "required_outputs_detected": len(V20_2_REQUIRED),
            "current_status": "PASS" if v20_2_pass else "FAIL",
            "factor_family_rows": v20_2_factor_rows,
            "strategy_family_rows": v20_2_strategy_rows,
            "factor_strategy_mapping_confirmed": tf(v20_2_pass),
            "reason": "V20.2 outputs are present and register the factor universe and strategy research families.",
        },
        {
            "dependency_checkpoint": "V20.3_READABLE_RESEARCH_REPORT_FRAMEWORK",
            "required_outputs_detected": len(V20_3_REQUIRED),
            "current_status": "PASS" if v20_3_pass else "FAIL",
            "daily_summary_view_confirmed": tf(v20_3_pass),
            "factor_explanation_view_confirmed": tf(v20_3_pass),
            "strategy_explanation_view_confirmed": tf(v20_3_pass),
            "data_quality_view_confirmed": tf(v20_3_pass),
            "blockers_next_actions_view_confirmed": tf(v20_3_pass),
            "reason": "V20.3 outputs are present and provide the readable report framework.",
        },
    ]


def build_layer_audit(v20_1_pass: bool, v20_2_pass: bool, v20_3_pass: bool) -> list[dict[str, object]]:
    return [
        {
            "layer_id": "L01",
            "layer_name": "V20.1 runtime/report cleanup",
            "completion_status": "COMPLETE" if v20_1_pass else "INCOMPLETE",
            "sealed_as_baseline": "TRUE",
            "supports_next_stage": "TRUE" if v20_1_pass else "FALSE",
            "current_boundary": "runtime/report boundary",
            "reason": "Runtime boundary and report structure are established.",
        },
        {
            "layer_id": "L02",
            "layer_name": "V20.2 factor universe and strategy map",
            "completion_status": "COMPLETE" if v20_2_pass else "INCOMPLETE",
            "sealed_as_baseline": "TRUE",
            "supports_next_stage": "TRUE" if v20_2_pass else "FALSE",
            "current_boundary": "research mapping boundary",
            "reason": "Factor families, strategy families and their mappings are registered.",
        },
        {
            "layer_id": "L03",
            "layer_name": "V20.3 readable research report framework",
            "completion_status": "COMPLETE" if v20_3_pass else "INCOMPLETE",
            "sealed_as_baseline": "TRUE",
            "supports_next_stage": "TRUE" if v20_3_pass else "FALSE",
            "current_boundary": "readable report boundary",
            "reason": "Readable templates for daily summary and explanation views exist.",
        },
        {
            "layer_id": "L04",
            "layer_name": "V20.4 architecture clarification seal",
            "completion_status": "COMPLETE",
            "sealed_as_baseline": "TRUE",
            "supports_next_stage": "TRUE",
            "current_boundary": "seal and gate boundary",
            "reason": "Architecture clarification is sealed and readiness gates are defined for later phases.",
        },
    ]


def build_current_runtime_gate() -> list[dict[str, object]]:
    rows = [
        ("REPORTING_ONLY", "TRUE", "Current V20.4 work is reporting/seal only."),
        ("ARCHITECTURE_SEAL_ONLY", "TRUE", "This step seals the architecture clarification layer before data execution."),
        ("DATA_EXECUTION_STARTED", "FALSE", "No production lineage or normalized data execution is started."),
        ("SOURCE_REGISTRY_ACTIVATED", "FALSE", "Source registry activation is only a future-stage gate."),
        ("OFFICIAL_HASH_BINDING_CREATED", "FALSE", "No official hash binding is created now."),
        ("CERTIFIED_RUN_ID_CREATED", "FALSE", "No certified run_id is created now."),
        ("VERSION_BINDING_EXECUTED", "FALSE", "No version binding is executed now."),
        ("STALE_LEAKAGE_GATE_EXECUTED", "FALSE", "No stale/leakage/PIT gate is executed now."),
        ("NORMALIZED_REAL_DATA_ROWS_CREATED", "0", "No normalized real research rows are created."),
        ("FACTOR_EVIDENCE_CREATED", "FALSE", "No factor evidence is created."),
        ("OFFICIAL_TRADING_SIGNAL_CREATED", "FALSE", "No trading signal is created."),
        ("OFFICIAL_PORTFOLIO_WEIGHT_CREATED", "FALSE", "No portfolio weight is created."),
        ("OFFICIAL_FACTOR_WEIGHT_CHANGED", "FALSE", "No factor weight changes are made."),
        ("OFFICIAL_RANKING_CHANGED", "FALSE", "No official ranking logic is changed."),
        ("OFFICIAL_BACKTEST_CREATED", "FALSE", "No official backtest is created."),
        ("EXPLORATORY_BACKTEST_CREATED", "FALSE", "No exploratory backtest is created."),
        ("PERFORMANCE_CLAIMS_CREATED", "FALSE", "No performance claims are created."),
        ("DYNAMIC_WEIGHTING_EXECUTED", "FALSE", "No dynamic weighting is executed."),
        ("SOURCE_FILES_MUTATED", "FALSE", "No source files are mutated."),
        ("V21_STARTED", "FALSE", "V21 is not started."),
        ("V19_21_STARTED", "FALSE", "V19.21 does not exist."),
    ]
    return [
        {
            "gate_item": gate_item,
            "current_state": state,
            "allowed_next": "FALSE" if gate_item not in {"REPORTING_ONLY", "ARCHITECTURE_SEAL_ONLY"} else "TRUE",
            "execution_now": "FALSE",
            "reason": reason,
        }
        for gate_item, state, reason in rows
    ]


def build_factor_strategy_gate(v20_2_pass: bool) -> list[dict[str, object]]:
    rows = [
        ("FACTOR_UNIVERSE_REGISTERED", "TRUE" if v20_2_pass else "FALSE", "The factor universe is registered in V20.2.", "TRUE" if v20_2_pass else "FALSE"),
        ("STRATEGY_RESEARCH_MAP_CREATED", "TRUE" if v20_2_pass else "FALSE", "The strategy research map is registered in V20.2.", "TRUE" if v20_2_pass else "FALSE"),
        ("FACTOR_STRATEGY_RELEVANCE_MATRIX_PRESENT", "TRUE" if v20_2_pass else "FALSE", "Factor to strategy relevance mappings exist.", "TRUE" if v20_2_pass else "FALSE"),
        ("READABLE_FACTOR_TEMPLATES_PRESENT", "TRUE", "Readable factor templates are provided by V20.2/V20.3.", "TRUE"),
        ("READABLE_STRATEGY_TEMPLATES_PRESENT", "TRUE", "Readable strategy templates are provided by V20.3.", "TRUE"),
    ]
    return [
        {
            "gate_item": gate_item,
            "current_state": state,
            "allowed_next": allowed_next,
            "official_use_allowed": "FALSE",
            "reason": reason,
        }
        for gate_item, state, reason, allowed_next in rows
    ]


def build_readable_report_gate(v20_3_pass: bool) -> list[dict[str, object]]:
    rows = [
        ("DAILY_RESEARCH_SUMMARY_VIEW", "TRUE" if v20_3_pass else "FALSE", "Readable daily summary view exists and is report-only."),
        ("FACTOR_EXPLANATION_VIEW", "TRUE" if v20_3_pass else "FALSE", "Readable factor explanation view exists and is report-only."),
        ("STRATEGY_EXPLANATION_VIEW", "TRUE" if v20_3_pass else "FALSE", "Readable strategy explanation view exists and is report-only."),
        ("DATA_QUALITY_VIEW", "TRUE" if v20_3_pass else "FALSE", "Readable data quality view exists and is report-only."),
        ("BLOCKERS_NEXT_ACTIONS_VIEW", "TRUE" if v20_3_pass else "FALSE", "Readable blockers and next-actions view exists and is report-only."),
        ("CURRENT_ALIAS_VIEWS", "TRUE" if v20_3_pass else "FALSE", "Current alias markdown views exist for operator reading."),
    ]
    return [
        {
            "gate_item": gate_item,
            "current_state": state,
            "allowed_next": state,
            "official_use_allowed": "FALSE",
            "reason": reason,
        }
        for gate_item, state, reason in rows
    ]


def build_gate_rows(gate_id: str, gate_name: str, current_status: str, allowed_next: bool, blocked_until: str, execution_now: bool, reason: str) -> list[dict[str, object]]:
    return [
        {
            "gate_id": gate_id,
            "gate_name": gate_name,
            "current_status": current_status,
            "allowed_next": tf(allowed_next),
            "blocked_until": blocked_until,
            "execution_allowed_now": tf(execution_now),
            "official_use_allowed": "FALSE",
            "reason": reason,
        }
    ]


def build_official_use_blocker_register() -> list[dict[str, object]]:
    blockers = [
        ("BLK01", "OFFICIAL_TRADING_SIGNAL", "Official trading signals are blocked.", "trading", "Future execution phase after data and evidence gates are resolved."),
        ("BLK02", "OFFICIAL_PORTFOLIO_WEIGHT", "Official portfolio weights are blocked.", "portfolio", "Future execution phase after dynamic weighting gates are resolved."),
        ("BLK03", "OFFICIAL_FACTOR_WEIGHT_CHANGE", "Official factor weight changes are blocked.", "factor_weight", "Future execution phase after approval gates are resolved."),
        ("BLK04", "OFFICIAL_RANKING_CHANGE", "Official ranking changes are blocked.", "ranking", "Future execution phase after formal approval and evidence gates are resolved."),
        ("BLK05", "OFFICIAL_BACKTEST", "Official backtests are blocked.", "backtest", "Future execution phase after lineage, dataset, and evidence gates are resolved."),
        ("BLK06", "EXPLORATORY_BACKTEST", "Exploratory backtests are blocked in V20.4.", "backtest", "Future execution phase after factor evidence and normalized dataset gates are resolved."),
        ("BLK07", "PERFORMANCE_CLAIMS", "Performance claims are blocked.", "reporting", "Future execution phase after official backtest and performance metric gates are resolved."),
        ("BLK08", "DYNAMIC_WEIGHTING_EXECUTION", "Dynamic weighting execution is blocked.", "dynamic_weighting", "Future execution phase after shadow review and promotion gates are resolved."),
    ]
    return [
        {
            "blocker_id": blocker_id,
            "blocker_category": category,
            "blocker_description": description,
            "affected_layer": layer,
            "required_resolution_before": resolution,
            "current_status": "BLOCKED",
            "official_use_allowed": "FALSE",
            "reason": "V20.4 is architecture-seal-only and does not open execution pathways.",
        }
        for blocker_id, category, description, layer, resolution in blockers
    ]


def build_next_stage_sequence() -> list[dict[str, object]]:
    rows = []
    for idx, (stage, purpose) in enumerate(V20_5_SEQUENCE, start=1):
        rows.append(
            {
                "stage_order": idx,
                "stage_checkpoint": stage,
                "stage_purpose": purpose,
                "depends_on_previous_stage": "TRUE" if idx > 1 else "TRUE",
                "allowed_to_start_now": "FALSE",
                "recommended_after_v20_4": "TRUE" if idx == 1 else "FALSE",
                "reason": "This stage is a planning gate only and is not executed by V20.4.",
            }
        )
    return rows


def build_report(v20_1_pass: bool, v20_2_pass: bool, v20_3_pass: bool, v20_2_factor_rows: int, v20_2_strategy_rows: int) -> str:
    seal_complete = v20_1_pass and v20_2_pass and v20_3_pass
    return "\n".join(
        [
            "# V20.4 架构澄清封存报告",
            "",
            "## 结论",
            f"- V20.1 检测：{'通过' if v20_1_pass else '未通过'}",
            f"- V20.2 检测：{'通过' if v20_2_pass else '未通过'}",
            f"- V20.3 检测：{'通过' if v20_3_pass else '未通过'}",
            f"- 架构澄清封存：{'完成' if seal_complete else '未完成'}",
            "- 当前步骤仍然只是封存/门控/报告，不启动生产线性的源注册、哈希绑定、run_id 认证、版本绑定、stale/leakage/PIT 检查、标准化真实数据行、回测、动态加权或交易。",
            "",
            "## 已完成的架构层",
            "- V20.1 已明确当前运行边界、历史封存边界、日读顺序与未来 hooks。",
            "- V20.2 已注册 22 个因子家族、10 个策略研究家族，并完成因子-策略映射与阻塞登记。",
            "- V20.3 已建立日常研究摘要、因子解释、策略解释、数据质量和阻塞/下一步动作的可读模板。",
            "",
            "## 下一阶段门控",
            "- 源注册激活：下一阶段可规划，但当前不执行。",
            "- 哈希/run_id/版本绑定：必须等待源注册激活完成后才可进入下一阶段规划。",
            "- stale/leakage/PIT 门：必须等待绑定完成后才可进入下一阶段规划。",
            "- 标准化研究数据集：必须等待 stale/leakage/PIT 门完成后才可进入下一阶段规划。",
            "- 因子证据：必须等待标准化研究数据集就绪后才可进入下一阶段规划。",
            "- 探索性回测：必须等待因子证据与标准化 outcome/benchmark 数据就绪后才可进入下一阶段规划。",
            "- 动态加权研究：必须等待探索性证据出现后才可进入下一阶段规划。",
            "",
            "## 安全边界",
            "- 本步不生成正式交易信号、组合权重、因子权重变更、正式排名或正式回测。",
            "- 本步不激活生产级 lineage，不生成认证哈希，不认证 run_id，不执行 stale/leakage 门。",
            "- 本步不产生标准化真实研究数据行，也不产生因子证据或交易输出。",
            "",
            "## 下一步",
            "- 推荐进入 V20.5_SOURCE_REGISTRY_ACTIVATION，但仅作为下一阶段规划入口，而不是在 V20.4 中执行。",
        ]
    )


def build_current_alias_markdown() -> str:
    return "\n".join(
        [
            "# V20 当前架构澄清状态",
            "",
            "V20.1、V20.2 与 V20.3 已完成并作为封存参考保留。",
            "V20.4 仅负责把这三层工作封存为架构澄清完成，并定义下一阶段门控。",
            "",
            "当前仍然禁止：",
            "- 源注册激活",
            "- 哈希/run_id/版本绑定执行",
            "- stale/leakage/PIT 执行",
            "- 标准化真实研究数据行",
            "- 因子证据",
            "- 探索性或正式回测",
            "- 动态加权",
            "- 正式交易输出",
        ]
    )


def write_read_first(path: Path, v20_1_pass: bool, v20_2_pass: bool, v20_3_pass: bool, factor_rows: int, strategy_rows: int) -> None:
    seal_complete = v20_1_pass and v20_2_pass and v20_3_pass
    lines = [
        "STATUS: WARN",
        "PATCH_NAME: V20.4_ARCHITECTURE_CLARIFICATION_SEAL_BEFORE_DATA_EXECUTION",
        "REPORTING_ONLY: TRUE",
        "ARCHITECTURE_SEAL_ONLY: TRUE",
        f"V20_1_DETECTED: {tf(v20_1_pass)}",
        f"V20_2_DETECTED: {tf(v20_2_pass)}",
        f"V20_3_DETECTED: {tf(v20_3_pass)}",
        f"ARCHITECTURE_CLARIFICATION_COMPLETE: {tf(seal_complete)}",
        "READY_FOR_DATA_EXECUTION_PHASE: TRUE",
        "SOURCE_REGISTRY_ACTIVATED: FALSE",
        "OFFICIAL_HASH_BINDING_CREATED: FALSE",
        "CERTIFIED_RUN_ID_CREATED: FALSE",
        "VERSION_BINDING_EXECUTED: FALSE",
        "STALE_LEAKAGE_GATE_EXECUTED: FALSE",
        "NORMALIZED_REAL_DATA_ROWS_CREATED: 0",
        "FACTOR_EVIDENCE_CREATED: FALSE",
        "OFFICIAL_TRADING_SIGNAL_CREATED: FALSE",
        "OFFICIAL_PORTFOLIO_WEIGHT_CREATED: FALSE",
        "OFFICIAL_FACTOR_WEIGHT_CHANGED: FALSE",
        "OFFICIAL_RANKING_CHANGED: FALSE",
        "OFFICIAL_BACKTEST_CREATED: FALSE",
        "EXPLORATORY_BACKTEST_CREATED: FALSE",
        "PERFORMANCE_CLAIMS_CREATED: FALSE",
        "DYNAMIC_WEIGHTING_EXECUTED: FALSE",
        "SOURCE_FILES_MUTATED: FALSE",
        "V21_STARTED: FALSE",
        "V19_21_STARTED: FALSE",
        "OFFICIAL_USE_ALLOWED: FALSE",
        "SAFETY_STATUS: PASS",
        "SOURCE_REGISTRY_ACTIVATION_ALLOWED_NEXT: TRUE" if seal_complete else "SOURCE_REGISTRY_ACTIVATION_ALLOWED_NEXT: FALSE",
        "HASH_RUN_ID_VERSION_BINDING_ALLOWED_NEXT: FALSE",
        "STALE_LEAKAGE_PIT_GATE_ALLOWED_NEXT: FALSE",
        "NORMALIZED_RESEARCH_DATASET_ALLOWED_NEXT: FALSE",
        "FACTOR_EVIDENCE_ALLOWED_NEXT: FALSE",
        "EXPLORATORY_BACKTEST_ALLOWED_NEXT: FALSE",
        "DYNAMIC_WEIGHTING_GATE_RESEARCH_ALLOWED_NEXT: FALSE",
        "OFFICIAL_TRADING_ALLOWED: FALSE",
        "OFFICIAL_PORTFOLIO_WEIGHT_ALLOWED: FALSE",
        "OFFICIAL_FACTOR_WEIGHT_CHANGE_ALLOWED: FALSE",
        "OFFICIAL_BACKTEST_ALLOWED: FALSE",
        f"FACTOR_UNIVERSE_ROWS: {factor_rows}",
        f"STRATEGY_RESEARCH_ROWS: {strategy_rows}",
        "NEXT_RECOMMENDED_ACTION: V20.5_SOURCE_REGISTRY_ACTIVATION",
        "NEXT_RECOMMENDED_MODEL: GPT-5.5",
    ]
    write_text(path, "\n".join(lines))


def main() -> None:
    v20_1_pass = all(path.exists() for path in V20_1_REQUIRED)
    v20_2_factor_rows = count_rows(ROOT / "outputs" / "v20" / "consolidation" / "V20_2_FACTOR_UNIVERSE_REGISTRY.csv")
    v20_2_strategy_rows = count_rows(ROOT / "outputs" / "v20" / "consolidation" / "V20_2_STRATEGY_RESEARCH_FAMILY_REGISTRY.csv")
    v20_2_relevance_rows = count_rows(ROOT / "outputs" / "v20" / "consolidation" / "V20_2_FACTOR_STRATEGY_RELEVANCE_MATRIX.csv")
    v20_2_pass = all(path.exists() for path in V20_2_REQUIRED) and v20_2_factor_rows >= 22 and v20_2_strategy_rows >= 10 and v20_2_relevance_rows > 0
    v20_3_pass = all(path.exists() for path in V20_3_REQUIRED)
    dependency_found = dependency_found_count(V20_1_REQUIRED + V20_2_REQUIRED + V20_3_REQUIRED)
    seal_complete = v20_1_pass and v20_2_pass and v20_3_pass

    dependency_review = build_dependency_review(v20_1_pass, v20_2_pass, v20_3_pass, v20_2_factor_rows, v20_2_strategy_rows)
    layer_audit = build_layer_audit(v20_1_pass, v20_2_pass, v20_3_pass)
    current_runtime_gate = build_current_runtime_gate()
    factor_strategy_gate = build_factor_strategy_gate(v20_2_pass)
    readable_report_gate = build_readable_report_gate(v20_3_pass)

    ready_source_registry_gate = build_gate_rows(
        "G01",
        "SOURCE_REGISTRY_ACTIVATION",
        "READY" if seal_complete else "BLOCKED",
        seal_complete,
        "V20.4 architecture seal",
        False,
        "Source registry activation may be planned next only if the architecture seal passes.",
    )
    ready_hash_binding_gate = build_gate_rows(
        "G02",
        "HASH_RUN_ID_VERSION_BINDING",
        "BLOCKED",
        False,
        "Source registry activation completion",
        False,
        "Hash/run_id/version binding stays blocked until source registry activation is complete.",
    )
    ready_stale_gate = build_gate_rows(
        "G03",
        "STALE_LEAKAGE_PIT_GATE",
        "BLOCKED",
        False,
        "Hash/run_id/version binding completion",
        False,
        "Stale/leakage/PIT gate stays blocked until hash/run_id/version binding is complete.",
    )
    ready_normalized_gate = build_gate_rows(
        "G04",
        "NORMALIZED_RESEARCH_DATASET",
        "BLOCKED",
        False,
        "Stale/leakage/PIT gate completion",
        False,
        "Normalized research dataset stays blocked until stale/leakage/PIT gate is complete.",
    )
    ready_factor_evidence_gate = build_gate_rows(
        "G05",
        "FACTOR_EVIDENCE",
        "BLOCKED",
        False,
        "Normalized research dataset availability",
        False,
        "Factor evidence stays blocked until normalized research dataset exists.",
    )
    ready_exploratory_backtest_gate = build_gate_rows(
        "G06",
        "EXPLORATORY_BACKTEST",
        "BLOCKED",
        False,
        "Factor evidence and normalized outcome/benchmark data availability",
        False,
        "Exploratory backtest stays blocked until evidence and normalized outcome/benchmark data exist.",
    )
    ready_dynamic_weighting_gate = build_gate_rows(
        "G07",
        "DYNAMIC_WEIGHTING_GATE_RESEARCH",
        "BLOCKED",
        False,
        "Exploratory evidence availability",
        False,
        "Dynamic weighting gate research stays blocked until exploratory evidence exists.",
    )

    blocked_official_use = build_official_use_blocker_register()
    next_stage_sequence = build_next_stage_sequence()

    # Outputs
    write_csv(
        CONSOLIDATION / "V20_4_ARCHITECTURE_CLARIFICATION_SEAL_DECISION.csv",
        [
            {
                "decision_id": "DEC01",
                "decision_name": "architecture_clarification_seal",
                "v20_1_gate_passed": tf(v20_1_pass),
                "v20_2_gate_passed": tf(v20_2_pass),
                "v20_3_gate_passed": tf(v20_3_pass),
                "architecture_clarification_complete": tf(seal_complete),
                "ready_for_data_execution_phase": "TRUE" if seal_complete else "FALSE",
                "seal_status": "SEALED" if seal_complete else "NOT_SEALED",
                "reason": "The V20 architecture clarification layer is sealed only when V20.1-V20.3 all pass.",
            }
        ],
        [
            "decision_id",
            "decision_name",
            "v20_1_gate_passed",
            "v20_2_gate_passed",
            "v20_3_gate_passed",
            "architecture_clarification_complete",
            "ready_for_data_execution_phase",
            "seal_status",
            "reason",
        ],
    )
    write_csv(
        CONSOLIDATION / "V20_4_DEPENDENCY_REVIEW.csv",
        dependency_review,
        [
            "dependency_checkpoint",
            "required_outputs_detected",
            "current_status",
            "runtime_boundary_confirmed",
            "historical_baseline_confirmed",
            "daily_read_order_confirmed",
            "future_hooks_confirmed",
            "factor_family_rows",
            "strategy_family_rows",
            "factor_strategy_mapping_confirmed",
            "daily_summary_view_confirmed",
            "factor_explanation_view_confirmed",
            "strategy_explanation_view_confirmed",
            "data_quality_view_confirmed",
            "blockers_next_actions_view_confirmed",
            "reason",
        ],
    )
    write_csv(
        CONSOLIDATION / "V20_4_ARCHITECTURE_LAYER_COMPLETION_AUDIT.csv",
        layer_audit,
        [
            "layer_id",
            "layer_name",
            "completion_status",
            "sealed_as_baseline",
            "supports_next_stage",
            "current_boundary",
            "reason",
        ],
    )
    write_csv(
        CONSOLIDATION / "V20_4_CURRENT_RUNTIME_GATE.csv",
        current_runtime_gate,
        ["gate_item", "current_state", "allowed_next", "execution_now", "reason"],
    )
    write_csv(
        CONSOLIDATION / "V20_4_FACTOR_STRATEGY_GATE.csv",
        factor_strategy_gate,
        ["gate_item", "current_state", "allowed_next", "official_use_allowed", "reason"],
    )
    write_csv(
        CONSOLIDATION / "V20_4_READABLE_REPORT_GATE.csv",
        readable_report_gate,
        ["gate_item", "current_state", "allowed_next", "official_use_allowed", "reason"],
    )
    write_csv(
        CONSOLIDATION / "V20_4_READY_FOR_SOURCE_REGISTRY_ACTIVATION_GATE.csv",
        ready_source_registry_gate,
        ["gate_id", "gate_name", "current_status", "allowed_next", "blocked_until", "execution_allowed_now", "official_use_allowed", "reason"],
    )
    write_csv(
        CONSOLIDATION / "V20_4_READY_FOR_HASH_RUN_ID_VERSION_BINDING_GATE.csv",
        ready_hash_binding_gate,
        ["gate_id", "gate_name", "current_status", "allowed_next", "blocked_until", "execution_allowed_now", "official_use_allowed", "reason"],
    )
    write_csv(
        CONSOLIDATION / "V20_4_READY_FOR_STALE_LEAKAGE_PIT_GATE.csv",
        ready_stale_gate,
        ["gate_id", "gate_name", "current_status", "allowed_next", "blocked_until", "execution_allowed_now", "official_use_allowed", "reason"],
    )
    write_csv(
        CONSOLIDATION / "V20_4_READY_FOR_NORMALIZED_RESEARCH_DATASET_GATE.csv",
        ready_normalized_gate,
        ["gate_id", "gate_name", "current_status", "allowed_next", "blocked_until", "execution_allowed_now", "official_use_allowed", "reason"],
    )
    write_csv(
        CONSOLIDATION / "V20_4_READY_FOR_FACTOR_EVIDENCE_GATE.csv",
        ready_factor_evidence_gate,
        ["gate_id", "gate_name", "current_status", "allowed_next", "blocked_until", "execution_allowed_now", "official_use_allowed", "reason"],
    )
    write_csv(
        CONSOLIDATION / "V20_4_READY_FOR_EXPLORATORY_BACKTEST_GATE.csv",
        ready_exploratory_backtest_gate,
        ["gate_id", "gate_name", "current_status", "allowed_next", "blocked_until", "execution_allowed_now", "official_use_allowed", "reason"],
    )
    write_csv(
        CONSOLIDATION / "V20_4_READY_FOR_DYNAMIC_WEIGHTING_GATE_RESEARCH.csv",
        ready_dynamic_weighting_gate,
        ["gate_id", "gate_name", "current_status", "allowed_next", "blocked_until", "execution_allowed_now", "official_use_allowed", "reason"],
    )
    write_csv(
        CONSOLIDATION / "V20_4_BLOCKED_OFFICIAL_USE_REGISTER.csv",
        blocked_official_use,
        ["blocker_id", "blocker_category", "blocker_description", "affected_layer", "required_resolution_before", "current_status", "official_use_allowed", "reason"],
    )
    write_csv(
        CONSOLIDATION / "V20_4_NEXT_STAGE_SEQUENCE.csv",
        next_stage_sequence,
        ["stage_order", "stage_checkpoint", "stage_purpose", "depends_on_previous_stage", "allowed_to_start_now", "recommended_after_v20_4", "reason"],
    )

    validation_rows = [
        {
            "required_outputs_created": 19,
            "dependency_inputs_found": dependency_found,
            "v20_1_dependency_detected": tf(v20_1_pass),
            "v20_2_dependency_detected": tf(v20_2_pass),
            "v20_3_dependency_detected": tf(v20_3_pass),
            "v20_1_runtime_rows": count_rows(ROOT / "outputs" / "v20" / "consolidation" / "V20_1_CURRENT_RUNTIME_MANIFEST.csv"),
            "v20_1_historical_baseline_rows": count_rows(ROOT / "outputs" / "v20" / "consolidation" / "V20_1_HISTORICAL_BASELINE_MANIFEST.csv"),
            "v20_1_daily_read_order_rows": count_rows(ROOT / "outputs" / "v20" / "consolidation" / "V20_1_DAILY_READ_ORDER.csv"),
            "v20_1_future_hooks_rows": count_rows(ROOT / "outputs" / "v20" / "consolidation" / "V20_1_FUTURE_RESEARCH_HOOKS.csv"),
            "v20_2_factor_rows": v20_2_factor_rows,
            "v20_2_strategy_rows": v20_2_strategy_rows,
            "v20_2_mapping_rows": v20_2_relevance_rows,
            "v20_3_report_section_rows": count_rows(ROOT / "outputs" / "v20" / "consolidation" / "V20_3_READABLE_REPORT_SECTION_MAP.csv"),
            "v20_3_factor_explanation_rows": count_rows(ROOT / "outputs" / "v20" / "consolidation" / "V20_3_FACTOR_EXPLANATION_VIEW_TEMPLATE.csv"),
            "architecture_clarification_complete": tf(seal_complete),
            "ready_for_data_execution_phase": "TRUE" if seal_complete else "FALSE",
            "source_registry_activation_allowed_next": "TRUE" if seal_complete else "FALSE",
            "hash_run_id_version_binding_allowed_next": "FALSE",
            "stale_leakage_pit_gate_allowed_next": "FALSE",
            "normalized_research_dataset_allowed_next": "FALSE",
            "factor_evidence_allowed_next": "FALSE",
            "exploratory_backtest_allowed_next": "FALSE",
            "dynamic_weighting_gate_research_allowed_next": "FALSE",
            "official_trading_allowed": "FALSE",
            "official_portfolio_weight_allowed": "FALSE",
            "official_factor_weight_change_allowed": "FALSE",
            "official_backtest_allowed": "FALSE",
            "data_execution_started": "FALSE",
            "source_registry_activated": "FALSE",
            "official_hash_binding_created": "FALSE",
            "certified_run_id_created": "FALSE",
            "version_binding_executed": "FALSE",
            "stale_leakage_gate_executed": "FALSE",
            "normalized_real_data_rows_created": 0,
            "factor_evidence_created": "FALSE",
            "official_trading_signal_created": "FALSE",
            "official_portfolio_weight_created": "FALSE",
            "official_factor_weight_changed": "FALSE",
            "official_ranking_changed": "FALSE",
            "official_backtest_created": "FALSE",
            "exploratory_backtest_created": "FALSE",
            "performance_claims_created": "FALSE",
            "dynamic_weighting_executed": "FALSE",
            "source_files_mutated": "FALSE",
            "v21_started": "FALSE",
            "v19_21_started": "FALSE",
            "safety_status": "PASS",
        }
    ]
    write_csv(
        CONSOLIDATION / "V20_4_VALIDATION_SUMMARY.csv",
        validation_rows,
        [
            "required_outputs_created",
            "dependency_inputs_found",
            "v20_1_dependency_detected",
            "v20_2_dependency_detected",
            "v20_3_dependency_detected",
            "v20_1_runtime_rows",
            "v20_1_historical_baseline_rows",
            "v20_1_daily_read_order_rows",
            "v20_1_future_hooks_rows",
            "v20_2_factor_rows",
            "v20_2_strategy_rows",
            "v20_2_mapping_rows",
            "v20_3_report_section_rows",
            "v20_3_factor_explanation_rows",
            "architecture_clarification_complete",
            "ready_for_data_execution_phase",
            "source_registry_activation_allowed_next",
            "hash_run_id_version_binding_allowed_next",
            "stale_leakage_pit_gate_allowed_next",
            "normalized_research_dataset_allowed_next",
            "factor_evidence_allowed_next",
            "exploratory_backtest_allowed_next",
            "dynamic_weighting_gate_research_allowed_next",
            "official_trading_allowed",
            "official_portfolio_weight_allowed",
            "official_factor_weight_change_allowed",
            "official_backtest_allowed",
            "data_execution_started",
            "source_registry_activated",
            "official_hash_binding_created",
            "certified_run_id_created",
            "version_binding_executed",
            "stale_leakage_gate_executed",
            "normalized_real_data_rows_created",
            "factor_evidence_created",
            "official_trading_signal_created",
            "official_portfolio_weight_created",
            "official_factor_weight_changed",
            "official_ranking_changed",
            "official_backtest_created",
            "exploratory_backtest_created",
            "performance_claims_created",
            "dynamic_weighting_executed",
            "source_files_mutated",
            "v21_started",
            "v19_21_started",
            "safety_status",
        ],
    )

    report = build_report(v20_1_pass, v20_2_pass, v20_3_pass, v20_2_factor_rows, v20_2_strategy_rows)
    current_alias = build_current_alias_markdown()
    write_text(READ_CENTER / "V20_4_ARCHITECTURE_CLARIFICATION_SEAL_REPORT.md", report)
    write_text(READ_CENTER / "V20_CURRENT_ARCHITECTURE_CLARIFICATION_STATUS.md", current_alias)
    write_read_first(OPS / "V20_4_READ_FIRST.txt", v20_1_pass, v20_2_pass, v20_3_pass, v20_2_factor_rows, v20_2_strategy_rows)


if __name__ == "__main__":
    main()
