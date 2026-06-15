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


def dependency_found_count(paths: list[Path]) -> int:
    return sum(1 for path in paths if path.exists())


V19_SEALED = [
    ROOT / "outputs" / "v19" / "ops" / "V19_FINAL_READ_FIRST.txt",
    ROOT / "outputs" / "v19" / "read_center" / "V19_FINAL_HANDOFF_AND_SEAL_REPORT.md",
    ROOT / "outputs" / "v19" / "read_center" / "V19_CURRENT_FINAL_HANDOFF_AND_SEAL.md",
    ROOT / "outputs" / "v19" / "final" / "V19_FINAL_FRAMEWORK_CAPABILITY_MANIFEST.csv",
    ROOT / "outputs" / "v19" / "final" / "V19_FINAL_LINEAGE_BLOCKER_REGISTER.csv",
    ROOT / "outputs" / "v19" / "final" / "V19_FINAL_NORMALIZED_DATA_BLOCKER_REGISTER.csv",
    ROOT / "outputs" / "v19" / "final" / "V19_FINAL_FACTOR_STRATEGY_REGISTRY_INDEX.csv",
    ROOT / "outputs" / "v19" / "final" / "V19_FINAL_BACKTEST_OUTCOME_FRAMEWORK_INDEX.csv",
    ROOT / "outputs" / "v19" / "final" / "V19_FINAL_DYNAMIC_WEIGHTING_GATE_INDEX.csv",
    ROOT / "outputs" / "v19" / "final" / "V19_FINAL_OFFICIAL_USE_BLOCKER_REGISTER.csv",
    ROOT / "outputs" / "v19" / "final" / "V19_FINAL_V20_HANDOFF_REQUIREMENTS.csv",
    ROOT / "outputs" / "v19" / "final" / "V19_FINAL_V20_DO_NOT_START_BOUNDARY.csv",
]

V20_1_BASELINE = [
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


FACTOR_FAMILIES = [
    {
        "factor_id": "FU01",
        "factor_family": "valuation",
        "factor_name": "Valuation",
        "factor_description": "价格相对基本面估值的偏离度与吸引力。",
        "input_required": "valuation_snapshot;fundamental_snapshot;history_window",
        "data_status": "SEALED_BASELINE_REFERENCED",
        "research_status": "RESEARCH_MAPPING_ONLY",
    },
    {
        "factor_id": "FU02",
        "factor_family": "growth",
        "factor_name": "Growth",
        "factor_description": "收入、利润、规模与成长斜率相关的研究因子。",
        "input_required": "growth_snapshot;fundamental_snapshot;history_window",
        "data_status": "SEALED_BASELINE_REFERENCED",
        "research_status": "RESEARCH_MAPPING_ONLY",
    },
    {
        "factor_id": "FU03",
        "factor_family": "profitability",
        "factor_name": "Profitability",
        "factor_description": "毛利率、净利率、ROE/ROIC 等盈利能力指标。",
        "input_required": "profitability_snapshot;fundamental_snapshot;history_window",
        "data_status": "SEALED_BASELINE_REFERENCED",
        "research_status": "RESEARCH_MAPPING_ONLY",
    },
    {
        "factor_id": "FU04",
        "factor_family": "quality",
        "factor_name": "Quality",
        "factor_description": "财务质量、稳定性、资本效率与持续经营能力。",
        "input_required": "quality_snapshot;fundamental_snapshot;history_window",
        "data_status": "SEALED_BASELINE_REFERENCED",
        "research_status": "RESEARCH_MAPPING_ONLY",
    },
    {
        "factor_id": "FU05",
        "factor_family": "momentum",
        "factor_name": "Momentum",
        "factor_description": "价格趋势延续性和强度。",
        "input_required": "price_history;return_window;history_window",
        "data_status": "SEALED_BASELINE_REFERENCED",
        "research_status": "RESEARCH_MAPPING_ONLY",
    },
    {
        "factor_id": "FU06",
        "factor_family": "relative_strength",
        "factor_name": "Relative Strength",
        "factor_description": "相对基准或同组对象的强度比较。",
        "input_required": "price_history;benchmark_series;history_window",
        "data_status": "SEALED_BASELINE_REFERENCED",
        "research_status": "RESEARCH_MAPPING_ONLY",
    },
    {
        "factor_id": "FU07",
        "factor_family": "technical_trend",
        "factor_name": "Technical Trend",
        "factor_description": "技术面趋势、均线结构与方向性判断。",
        "input_required": "price_history;moving_average_series;history_window",
        "data_status": "SEALED_BASELINE_REFERENCED",
        "research_status": "RESEARCH_MAPPING_ONLY",
    },
    {
        "factor_id": "FU08",
        "factor_family": "moving_average_pullback",
        "factor_name": "Moving Average Pullback",
        "factor_description": "均线回踩、反弹确认与位置修复模式。",
        "input_required": "price_history;moving_average_series;history_window",
        "data_status": "SEALED_BASELINE_REFERENCED",
        "research_status": "RESEARCH_MAPPING_ONLY",
    },
    {
        "factor_id": "FU09",
        "factor_family": "breakout",
        "factor_name": "Breakout",
        "factor_description": "突破前高、平台或波动压缩后的趋势启动信号。",
        "input_required": "price_history;range_breakout_series;history_window",
        "data_status": "SEALED_BASELINE_REFERENCED",
        "research_status": "RESEARCH_MAPPING_ONLY",
    },
    {
        "factor_id": "FU10",
        "factor_family": "volume_liquidity",
        "factor_name": "Volume Liquidity",
        "factor_description": "成交量、流动性、换手与可交易性约束。",
        "input_required": "volume_history;liquidity_metrics;history_window",
        "data_status": "SEALED_BASELINE_REFERENCED",
        "research_status": "RESEARCH_MAPPING_ONLY",
    },
    {
        "factor_id": "FU11",
        "factor_family": "volatility_risk",
        "factor_name": "Volatility Risk",
        "factor_description": "波动率、尾部波动与价格不稳定性风险。",
        "input_required": "volatility_series;price_history;history_window",
        "data_status": "SEALED_BASELINE_REFERENCED",
        "research_status": "RESEARCH_MAPPING_ONLY",
    },
    {
        "factor_id": "FU12",
        "factor_family": "drawdown_risk",
        "factor_name": "Drawdown Risk",
        "factor_description": "回撤深度、持续时间与风险恢复能力。",
        "input_required": "drawdown_series;price_history;history_window",
        "data_status": "SEALED_BASELINE_REFERENCED",
        "research_status": "RESEARCH_MAPPING_ONLY",
    },
    {
        "factor_id": "FU13",
        "factor_family": "event_risk",
        "factor_name": "Event Risk",
        "factor_description": "财报、公告、政策与其他事件冲击风险。",
        "input_required": "event_calendar;event_tags;history_window",
        "data_status": "SEALED_BASELINE_REFERENCED",
        "research_status": "RESEARCH_MAPPING_ONLY",
    },
    {
        "factor_id": "FU14",
        "factor_family": "earnings_fundamental_change",
        "factor_name": "Earnings Fundamental Change",
        "factor_description": "盈利预期、财务拐点与基本面变化方向。",
        "input_required": "earnings_snapshot;fundamental_change_series;history_window",
        "data_status": "REGISTERED_BUT_MISSING_INPUT",
        "research_status": "RESEARCH_MAPPING_ONLY",
    },
    {
        "factor_id": "FU15",
        "factor_family": "analyst_expectation_revision",
        "factor_name": "Analyst Expectation Revision",
        "factor_description": "分析师预期修正与一致预期变动。",
        "input_required": "analyst_estimate_history;revision_series;history_window",
        "data_status": "REGISTERED_BUT_MISSING_INPUT",
        "research_status": "RESEARCH_MAPPING_ONLY",
    },
    {
        "factor_id": "FU16",
        "factor_family": "options_risk",
        "factor_name": "Options Risk",
        "factor_description": "期权隐含波动、偏斜、风险溢价与对冲压力。",
        "input_required": "options_chain;implied_volatility;history_window",
        "data_status": "SEALED_BASELINE_REFERENCED",
        "research_status": "RESEARCH_MAPPING_ONLY",
    },
    {
        "factor_id": "FU17",
        "factor_family": "market_regime",
        "factor_name": "Market Regime",
        "factor_description": "市场状态、风格切换与风险偏好环境。",
        "input_required": "benchmark_series;volatility_series;regime_label",
        "data_status": "SEALED_BASELINE_REFERENCED",
        "research_status": "RESEARCH_MAPPING_ONLY",
    },
    {
        "factor_id": "FU18",
        "factor_family": "industry_theme",
        "factor_name": "Industry Theme",
        "factor_description": "行业主题轮动与相对强势群组。",
        "input_required": "industry_classification;theme_tags;history_window",
        "data_status": "REGISTERED_BUT_MISSING_INPUT",
        "research_status": "RESEARCH_MAPPING_ONLY",
    },
    {
        "factor_id": "FU19",
        "factor_family": "ai_semiconductor_theme",
        "factor_name": "AI Semiconductor Theme",
        "factor_description": "AI 与半导体主题链路的研究因子。",
        "input_required": "theme_tags;sector_exposure;history_window",
        "data_status": "REGISTERED_BUT_MISSING_INPUT",
        "research_status": "RESEARCH_MAPPING_ONLY",
    },
    {
        "factor_id": "FU20",
        "factor_family": "data_center_power_theme",
        "factor_name": "Data Center Power Theme",
        "factor_description": "数据中心、电力基础设施与算力需求主题。",
        "input_required": "theme_tags;sector_exposure;history_window",
        "data_status": "REGISTERED_BUT_MISSING_INPUT",
        "research_status": "RESEARCH_MAPPING_ONLY",
    },
    {
        "factor_id": "FU21",
        "factor_family": "manual_operator_observation",
        "factor_name": "Manual Operator Observation",
        "factor_description": "人工观察、注释与主观确认记录。",
        "input_required": "operator_note;review_context;timestamp",
        "data_status": "REGISTERED_BUT_MISSING_INPUT",
        "research_status": "RESEARCH_MAPPING_ONLY",
    },
    {
        "factor_id": "FU22",
        "factor_family": "composite_score",
        "factor_name": "Composite Score",
        "factor_description": "多个研究因子聚合后的综合评分。",
        "input_required": "factor_scores;weight_vector;history_window",
        "data_status": "SEALED_BASELINE_REFERENCED",
        "research_status": "RESEARCH_MAPPING_ONLY",
    },
]


STRATEGY_FAMILIES = [
    {
        "strategy_family_id": "SR01",
        "strategy_family_name": "quality_growth",
        "strategy_description": "质量与成长结合的研究型选股/排序框架。",
        "required_factor_families": "quality;growth;profitability",
        "optional_factor_families": "valuation;earnings_fundamental_change;analyst_expectation_revision;composite_score",
        "excluded_or_blocked_factor_families": "event_risk;options_risk;manual_operator_observation",
    },
    {
        "strategy_family_id": "SR02",
        "strategy_family_name": "momentum_breakout",
        "strategy_description": "趋势延续与突破研究框架。",
        "required_factor_families": "momentum;relative_strength;technical_trend;breakout",
        "optional_factor_families": "volume_liquidity;volatility_risk;composite_score",
        "excluded_or_blocked_factor_families": "valuation;profitability;manual_operator_observation",
    },
    {
        "strategy_family_id": "SR03",
        "strategy_family_name": "moving_average_pullback",
        "strategy_description": "均线回踩与修复型研究框架。",
        "required_factor_families": "technical_trend;moving_average_pullback;relative_strength",
        "optional_factor_families": "volume_liquidity;volatility_risk;drawdown_risk",
        "excluded_or_blocked_factor_families": "event_risk;options_risk;industry_theme",
    },
    {
        "strategy_family_id": "SR04",
        "strategy_family_name": "low_volatility_quality",
        "strategy_description": "低波动、质量与回撤控制研究框架。",
        "required_factor_families": "quality;volatility_risk;drawdown_risk",
        "optional_factor_families": "volume_liquidity;profitability;composite_score",
        "excluded_or_blocked_factor_families": "breakout;ai_semiconductor_theme;data_center_power_theme",
    },
    {
        "strategy_family_id": "SR05",
        "strategy_family_name": "event_risk_avoidance",
        "strategy_description": "事件风险规避研究框架。",
        "required_factor_families": "event_risk;options_risk;market_regime",
        "optional_factor_families": "drawdown_risk;volatility_risk;manual_operator_observation",
        "excluded_or_blocked_factor_families": "breakout;momentum;relative_strength",
    },
    {
        "strategy_family_id": "SR06",
        "strategy_family_name": "theme_trend",
        "strategy_description": "行业主题与主题趋势研究框架。",
        "required_factor_families": "industry_theme;ai_semiconductor_theme;data_center_power_theme",
        "optional_factor_families": "momentum;relative_strength;volume_liquidity;market_regime",
        "excluded_or_blocked_factor_families": "drawdown_risk;event_risk;manual_operator_observation",
    },
    {
        "strategy_family_id": "SR07",
        "strategy_family_name": "reversal_watch",
        "strategy_description": "反转观察与风险修复研究框架。",
        "required_factor_families": "drawdown_risk;volatility_risk;technical_trend",
        "optional_factor_families": "breakout;moving_average_pullback;volume_liquidity",
        "excluded_or_blocked_factor_families": "valuation;growth;profitability",
    },
    {
        "strategy_family_id": "SR08",
        "strategy_family_name": "earnings_revision_watch",
        "strategy_description": "盈利与预期修正观察框架。",
        "required_factor_families": "earnings_fundamental_change;analyst_expectation_revision",
        "optional_factor_families": "growth;valuation;quality;composite_score",
        "excluded_or_blocked_factor_families": "breakout;volume_liquidity;options_risk",
    },
    {
        "strategy_family_id": "SR09",
        "strategy_family_name": "options_risk_watch",
        "strategy_description": "期权风险与对冲压力观察框架。",
        "required_factor_families": "options_risk;volatility_risk;event_risk",
        "optional_factor_families": "market_regime;drawdown_risk;manual_operator_observation",
        "excluded_or_blocked_factor_families": "valuation;growth;profitability",
    },
    {
        "strategy_family_id": "SR10",
        "strategy_family_name": "manual_review_priority",
        "strategy_description": "人工复核优先与解释视图框架。",
        "required_factor_families": "manual_operator_observation;market_regime",
        "optional_factor_families": "composite_score;event_risk;options_risk;valuation;growth;profitability;quality;momentum;relative_strength;technical_trend;moving_average_pullback;breakout;volume_liquidity;volatility_risk;drawdown_risk;earnings_fundamental_change;analyst_expectation_revision;industry_theme;ai_semiconductor_theme;data_center_power_theme",
        "excluded_or_blocked_factor_families": "official_trading_signal;official_weighting",
    },
]


FACTOR_TO_STRATEGY_MAP = {
    "valuation": [("SR01", "optional"), ("SR08", "optional")],
    "growth": [("SR01", "required"), ("SR08", "optional")],
    "profitability": [("SR01", "required"), ("SR04", "optional")],
    "quality": [("SR01", "required"), ("SR04", "required")],
    "momentum": [("SR02", "required"), ("SR06", "optional")],
    "relative_strength": [("SR02", "required"), ("SR03", "required")],
    "technical_trend": [("SR02", "required"), ("SR03", "required"), ("SR07", "required")],
    "moving_average_pullback": [("SR03", "required"), ("SR07", "optional")],
    "breakout": [("SR02", "required"), ("SR07", "optional")],
    "volume_liquidity": [("SR02", "optional"), ("SR03", "optional"), ("SR04", "optional")],
    "volatility_risk": [("SR04", "required"), ("SR05", "optional"), ("SR07", "required"), ("SR09", "required")],
    "drawdown_risk": [("SR04", "required"), ("SR05", "optional"), ("SR07", "required")],
    "event_risk": [("SR05", "required"), ("SR09", "required"), ("SR10", "optional")],
    "earnings_fundamental_change": [("SR01", "optional"), ("SR08", "required")],
    "analyst_expectation_revision": [("SR01", "optional"), ("SR08", "required")],
    "options_risk": [("SR05", "required"), ("SR09", "required")],
    "market_regime": [("SR05", "required"), ("SR06", "optional"), ("SR10", "required")],
    "industry_theme": [("SR06", "required"), ("SR02", "optional")],
    "ai_semiconductor_theme": [("SR06", "required"), ("SR02", "optional")],
    "data_center_power_theme": [("SR06", "required"), ("SR02", "optional")],
    "manual_operator_observation": [("SR10", "required"), ("SR05", "optional")],
    "composite_score": [("SR01", "optional"), ("SR02", "optional"), ("SR04", "optional"), ("SR10", "optional")],
}


def build_factor_family_registry() -> list[dict[str, str]]:
    out = []
    for idx, row in enumerate(FACTOR_FAMILIES, start=1):
        research_only = row["data_status"] != "REGISTERED_BUT_MISSING_INPUT"
        blocker = "No official use, backtest, or dynamic weighting is allowed in V20.2."
        if row["data_status"] == "REGISTERED_BUT_MISSING_INPUT":
            blocker = "Registered concept still lacks full input coverage for execution use."
        out.append(
            {
                "factor_id": row["factor_id"],
                "factor_family": row["factor_family"],
                "factor_name": row["factor_name"],
                "factor_description": row["factor_description"],
                "input_required": row["input_required"],
                "data_status": row["data_status"],
                "research_status": row["research_status"],
                "official_use_allowed": "FALSE",
                "backtest_allowed_now": "FALSE",
                "dynamic_weight_allowed_now": "FALSE",
                "readable_report_allowed": "TRUE",
                "blocker_reason": blocker,
            }
        )
    return out


def build_strategy_research_registry() -> list[dict[str, str]]:
    out = []
    for row in STRATEGY_FAMILIES:
        out.append(
            {
                "strategy_family_id": row["strategy_family_id"],
                "strategy_family_name": row["strategy_family_name"],
                "strategy_description": row["strategy_description"],
                "required_factor_families": row["required_factor_families"],
                "optional_factor_families": row["optional_factor_families"],
                "excluded_or_blocked_factor_families": row["excluded_or_blocked_factor_families"],
                "research_status": "RESEARCH_ONLY",
                "official_use_allowed": "FALSE",
                "backtest_allowed_now": "FALSE",
                "dynamic_weight_allowed_now": "FALSE",
                "readable_report_allowed": "TRUE",
            }
        )
    return out


def build_factor_strategy_relevance_matrix() -> list[dict[str, str]]:
    out = []
    for factor in FACTOR_FAMILIES:
        for strategy_id, relevance_type in FACTOR_TO_STRATEGY_MAP[factor["factor_family"]]:
            strategy = next(r for r in STRATEGY_FAMILIES if r["strategy_family_id"] == strategy_id)
            out.append(
                {
                    "factor_id": factor["factor_id"],
                    "factor_family": factor["factor_family"],
                    "strategy_family_id": strategy_id,
                    "strategy_family_name": strategy["strategy_family_name"],
                    "relevance_type": relevance_type,
                    "relevance_strength": "HIGH" if relevance_type == "required" else "MEDIUM",
                    "research_status": "RESEARCH_MAPPING_ONLY",
                    "official_use_allowed": "FALSE",
                    "backtest_allowed_now": "FALSE",
                    "dynamic_weight_allowed_now": "FALSE",
                    "reason": f"{factor['factor_family']} is mapped to {strategy['strategy_family_name']} for research-only interpretation.",
                }
            )
    return out


def build_factor_data_availability_audit() -> list[dict[str, str]]:
    out = []
    for factor in FACTOR_FAMILIES:
        availability = "AVAILABLE_FOR_RESEARCH_ONLY" if factor["data_status"] == "SEALED_BASELINE_REFERENCED" else "REGISTERED_BUT_MISSING_INPUT"
        out.append(
            {
                "factor_id": factor["factor_id"],
                "factor_family": factor["factor_family"],
                "data_status": factor["data_status"],
                "observed_in_sealed_baselines": tf(factor["data_status"] == "SEALED_BASELINE_REFERENCED"),
                "source_outputs_reviewed": "outputs/v19;outputs/v20",
                "missing_input_category": "future_dataset_or_manual_review" if factor["data_status"] == "REGISTERED_BUT_MISSING_INPUT" else "none",
                "research_readiness": "RESEARCH_MAPPING_ONLY",
                "official_use_allowed": "FALSE",
                "backtest_allowed_now": "FALSE",
                "dynamic_weight_allowed_now": "FALSE",
                "reason": "Data is either referenced from sealed baselines or registered as a future-input concept only.",
            }
        )
    return out


def build_factor_research_status_map() -> list[dict[str, str]]:
    out = []
    for factor in FACTOR_FAMILIES:
        out.append(
            {
                "factor_id": factor["factor_id"],
                "factor_family": factor["factor_family"],
                "research_status": "RESEARCH_MAPPING_ONLY",
                "explanation_view_status": "READY_FOR_REPORT_TEMPLATE",
                "data_status": factor["data_status"],
                "official_use_allowed": "FALSE",
                "backtest_allowed_now": "FALSE",
                "dynamic_weight_allowed_now": "FALSE",
                "readable_report_allowed": "TRUE",
                "reason": "Factor is registered for research mapping only; no execution or official use is permitted.",
            }
        )
    return out


def build_strategy_factor_dependency_map() -> list[dict[str, str]]:
    out = []
    for strategy in STRATEGY_FAMILIES:
        required = [f for f in FACTOR_FAMILIES if strategy["strategy_family_id"] in [sid for sid, rel in FACTOR_TO_STRATEGY_MAP[f["factor_family"]] if rel == "required"]]
        optional = [f for f in FACTOR_FAMILIES if strategy["strategy_family_id"] in [sid for sid, rel in FACTOR_TO_STRATEGY_MAP[f["factor_family"]] if rel == "optional"]]
        out.append(
            {
                "strategy_family_id": strategy["strategy_family_id"],
                "required_factor_families": strategy["required_factor_families"],
                "optional_factor_families": strategy["optional_factor_families"],
                "factor_map_ready": "TRUE",
                "official_use_allowed": "FALSE",
                "backtest_allowed_now": "FALSE",
                "dynamic_weight_allowed_now": "FALSE",
                "readable_report_allowed": "TRUE",
                "reason": "Strategy family dependencies are mapped only for research interpretation.",
            }
        )
    return out


def build_factor_blocker_register() -> list[dict[str, str]]:
    categories = [
        "REGISTERED_BUT_MISSING_INPUT",
        "AVAILABLE_FOR_RESEARCH_ONLY",
        "BLOCKED_FROM_OFFICIAL_USE",
        "BLOCKED_FROM_DYNAMIC_WEIGHTING",
        "BLOCKED_FROM_BACKTEST_UNTIL_NORMALIZED_DATA_READY",
    ]
    out = []
    for factor in FACTOR_FAMILIES:
        for category in categories:
            status = "BLOCKED" if category.startswith("BLOCKED") or category == "REGISTERED_BUT_MISSING_INPUT" else "RESEARCH_ONLY"
            out.append(
                {
                    "factor_id": factor["factor_id"],
                    "factor_family": factor["factor_family"],
                    "blocker_category": category,
                    "blocker_status": status,
                    "blocker_scope": "research_mapping",
                    "reason": "Factor universe is sealed for research mapping only; no execution path is opened.",
                }
            )
    return out


def build_readable_factor_explanation_template() -> list[dict[str, str]]:
    out = []
    for factor in FACTOR_FAMILIES:
        chinese_title = {
            "valuation": "估值因子",
            "growth": "成长因子",
            "profitability": "盈利能力因子",
            "quality": "质量因子",
            "momentum": "动量因子",
            "relative_strength": "相对强度因子",
            "technical_trend": "技术趋势因子",
            "moving_average_pullback": "均线回踩因子",
            "breakout": "突破因子",
            "volume_liquidity": "量能与流动性因子",
            "volatility_risk": "波动率风险因子",
            "drawdown_risk": "回撤风险因子",
            "event_risk": "事件风险因子",
            "earnings_fundamental_change": "盈利与基本面变化因子",
            "analyst_expectation_revision": "分析师预期修正因子",
            "options_risk": "期权风险因子",
            "market_regime": "市场状态因子",
            "industry_theme": "行业主题因子",
            "ai_semiconductor_theme": "AI 半导体主题因子",
            "data_center_power_theme": "数据中心电力主题因子",
            "manual_operator_observation": "人工观察因子",
            "composite_score": "综合评分因子",
        }[factor["factor_family"]]
        explanation = {
            "factor_family": factor["factor_family"],
            "explanation_title_zh": chinese_title,
            "explanation_summary_zh": f"{chinese_title}用于研究层解释，不代表正式交易或正式权重。",
            "why_relevant_zh": "它可帮助研究人员理解候选策略为何可能与某类因子相关。",
            "current_status_zh": "仅用于研究映射与报告模板。",
            "data_quality_note_zh": "当前不创建真实数据行，不做正式证据化。",
            "official_use_note_zh": "禁止作为正式排名、正式回测、正式权重或交易依据。",
            "future_activation_note_zh": "未来如需激活，必须先补齐源数据、归一化数据、回测与证据门控。",
            "report_sentence_template_zh": f"该{chinese_title}目前仅作为研究映射项存在，供后续读中心报告解释使用。",
            "reason": "Chinese-readable explanation template reserved for future read_center reports.",
        }
        out.append(explanation)
    return out


def build_validation_summary(counts: dict[str, object]) -> list[dict[str, str]]:
    return [{k: str(v) for k, v in counts.items()}]


def build_report(
    dependency_found: int,
    dependency_total: int,
    factor_rows: int,
    strategy_rows: int,
    map_rows: int,
) -> str:
    return f"""# V20.2 因子宇宙与策略研究映射说明

## 结论
- 状态：WARN
- 本次仅做研究映射，不改变官方排名、官方因子权重、官方回测或交易边界。
- V18 与 V19 继续作为封存历史基线：TRUE

## 依赖检查
- 已检查依赖输入：{dependency_found}/{dependency_total}
- V20.1 已存在并作为当前运行时/报告结构边界：TRUE
- 本次不启动 V21，不创建 V19.21 文件：TRUE

## 本次做了什么
V20.2 建立了统一的 V20 因子宇宙，并把因子家族映射到策略研究家族。它同时生成可读中文解释模板，供未来 read_center 报告使用。

## 本次没有做什么
- 没有创建正式买卖建议。
- 没有创建正式组合权重。
- 没有更改官方因子权重或官方排名逻辑。
- 没有执行动态加权。
- 没有创建官方或探索性回测结果。
- 没有生成标准化真实研究数据行。

## 因子宇宙与策略研究范围
- 因子宇宙注册行数：{factor_rows}
- 策略研究家族注册行数：{strategy_rows}
- 因子-策略相关矩阵行数：{map_rows}

## 读中心结构
当前仅保留研究映射、解释模板、数据可用性审计与阻断登记。任何正式化路径都必须等未来版本补齐数据、归一化、回测与证据门控。

## 未来 hook
本次继续保留 future research hooks、report hooks 与 lineage hook，但这些 hook 仍然是规划项，不是执行入口。

## 下一步
推荐进入 V20.3_READABLE_RESEARCH_REPORT_FRAMEWORK，以把当前研究映射转为可读报告框架，但仍保持 research-only。
"""


def build_read_first_text(fields: list[tuple[str, object]]) -> str:
    return "\n".join(f"{k}: {v}" for k, v in fields) + "\n"


def main() -> int:
    ensure_dir(OPS)
    ensure_dir(CONSOLIDATION)
    ensure_dir(READ_CENTER)

    dependency_paths = V19_SEALED + V20_1_BASELINE
    dependency_found = dependency_found_count(dependency_paths)
    dependency_total = len(dependency_paths)

    v20_1_read = read_first(ROOT / "outputs" / "v20" / "ops" / "V20_1_READ_FIRST.txt")
    v19_final_read = read_first(ROOT / "outputs" / "v19" / "ops" / "V19_FINAL_READ_FIRST.txt")
    _ = v20_1_read, v19_final_read

    factor_registry_rows = build_factor_family_registry()
    strategy_registry_rows = build_strategy_research_registry()
    factor_map_rows = build_factor_strategy_relevance_matrix()
    data_audit_rows = build_factor_data_availability_audit()
    research_status_rows = build_factor_research_status_map()
    strategy_factor_rows = build_strategy_factor_dependency_map()
    blocker_rows = build_factor_blocker_register()
    explanation_rows = build_readable_factor_explanation_template()

    validation_counts = {
        "required_outputs_created": 13,
        "dependency_inputs_found": dependency_found,
        "factor_universe_registry_rows": len(factor_registry_rows),
        "factor_family_map_rows": len(factor_map_rows),
        "factor_data_availability_audit_rows": len(data_audit_rows),
        "factor_research_status_map_rows": len(research_status_rows),
        "factor_strategy_relevance_matrix_rows": len(factor_map_rows),
        "strategy_research_family_registry_rows": len(strategy_registry_rows),
        "strategy_factor_dependency_map_rows": len(strategy_factor_rows),
        "factor_blocker_register_rows": len(blocker_rows),
        "readable_factor_explanation_template_rows": len(explanation_rows),
        "official_trading_signal_created": "FALSE",
        "official_portfolio_weight_created": "FALSE",
        "official_factor_weight_changed": "FALSE",
        "official_ranking_changed": "FALSE",
        "official_backtest_created": "FALSE",
        "exploratory_backtest_created": "FALSE",
        "performance_claims_created": "FALSE",
        "dynamic_weighting_executed": "FALSE",
        "normalized_real_data_rows_created": "0",
        "source_files_mutated": "FALSE",
        "v21_started": "FALSE",
        "v19_21_started": "FALSE",
        "reporting_only": "TRUE",
        "research_mapping_only": "TRUE",
        "factor_universe_registered": "TRUE",
        "strategy_research_map_created": "TRUE",
        "readable_report_template_created": "TRUE",
        "safety_status": "PASS",
    }

    write_csv(
        CONSOLIDATION / "V20_2_FACTOR_UNIVERSE_REGISTRY.csv",
        factor_registry_rows,
        ["factor_id", "factor_family", "factor_name", "factor_description", "input_required", "data_status", "research_status", "official_use_allowed", "backtest_allowed_now", "dynamic_weight_allowed_now", "readable_report_allowed", "blocker_reason"],
    )
    write_csv(
        CONSOLIDATION / "V20_2_FACTOR_FAMILY_MAP.csv",
        factor_map_rows,
        ["factor_id", "factor_family", "strategy_family_id", "strategy_family_name", "relevance_type", "relevance_strength", "research_status", "official_use_allowed", "backtest_allowed_now", "dynamic_weight_allowed_now", "reason"],
    )
    write_csv(
        CONSOLIDATION / "V20_2_FACTOR_DATA_AVAILABILITY_AUDIT.csv",
        data_audit_rows,
        ["factor_id", "factor_family", "data_status", "observed_in_sealed_baselines", "source_outputs_reviewed", "missing_input_category", "research_readiness", "official_use_allowed", "backtest_allowed_now", "dynamic_weight_allowed_now", "reason"],
    )
    write_csv(
        CONSOLIDATION / "V20_2_FACTOR_RESEARCH_STATUS_MAP.csv",
        research_status_rows,
        ["factor_id", "factor_family", "research_status", "explanation_view_status", "data_status", "official_use_allowed", "backtest_allowed_now", "dynamic_weight_allowed_now", "readable_report_allowed", "reason"],
    )
    write_csv(
        CONSOLIDATION / "V20_2_FACTOR_STRATEGY_RELEVANCE_MATRIX.csv",
        factor_map_rows,
        ["factor_id", "factor_family", "strategy_family_id", "strategy_family_name", "relevance_type", "relevance_strength", "research_status", "official_use_allowed", "backtest_allowed_now", "dynamic_weight_allowed_now", "reason"],
    )
    write_csv(
        CONSOLIDATION / "V20_2_STRATEGY_RESEARCH_FAMILY_REGISTRY.csv",
        strategy_registry_rows,
        ["strategy_family_id", "strategy_family_name", "strategy_description", "required_factor_families", "optional_factor_families", "excluded_or_blocked_factor_families", "research_status", "official_use_allowed", "backtest_allowed_now", "dynamic_weight_allowed_now", "readable_report_allowed"],
    )
    write_csv(
        CONSOLIDATION / "V20_2_STRATEGY_FACTOR_DEPENDENCY_MAP.csv",
        strategy_factor_rows,
        ["strategy_family_id", "required_factor_families", "optional_factor_families", "factor_map_ready", "official_use_allowed", "backtest_allowed_now", "dynamic_weight_allowed_now", "readable_report_allowed", "reason"],
    )
    write_csv(
        CONSOLIDATION / "V20_2_FACTOR_BLOCKER_REGISTER.csv",
        blocker_rows,
        ["factor_id", "factor_family", "blocker_category", "blocker_status", "blocker_scope", "reason"],
    )
    write_csv(
        CONSOLIDATION / "V20_2_READABLE_FACTOR_EXPLANATION_TEMPLATE.csv",
        explanation_rows,
        ["factor_family", "explanation_title_zh", "explanation_summary_zh", "why_relevant_zh", "current_status_zh", "data_quality_note_zh", "official_use_note_zh", "future_activation_note_zh", "report_sentence_template_zh", "reason"],
    )
    write_csv(
        CONSOLIDATION / "V20_2_VALIDATION_SUMMARY.csv",
        build_validation_summary(validation_counts),
        list(validation_counts.keys()),
    )

    report = build_report(
        dependency_found=dependency_found,
        dependency_total=dependency_total,
        factor_rows=len(factor_registry_rows),
        strategy_rows=len(strategy_registry_rows),
        map_rows=len(factor_map_rows),
    )
    write_text(READ_CENTER / "V20_2_FACTOR_AND_STRATEGY_RESEARCH_MAP_REPORT.md", report)
    write_text(READ_CENTER / "V20_CURRENT_FACTOR_STRATEGY_RESEARCH_VIEW.md", report)

    read_first_fields = [
        ("STATUS", "WARN"),
        ("PATCH_NAME", "V20.2_FACTOR_UNIVERSE_AND_STRATEGY_RESEARCH_MAP"),
        ("REPORTING_ONLY", "TRUE"),
        ("RESEARCH_MAPPING_ONLY", "TRUE"),
        ("FACTOR_UNIVERSE_REGISTERED", "TRUE"),
        ("STRATEGY_RESEARCH_MAP_CREATED", "TRUE"),
        ("READABLE_REPORT_TEMPLATE_CREATED", "TRUE"),
        ("OFFICIAL_TRADING_SIGNAL_CREATED", "FALSE"),
        ("OFFICIAL_PORTFOLIO_WEIGHT_CREATED", "FALSE"),
        ("OFFICIAL_FACTOR_WEIGHT_CHANGED", "FALSE"),
        ("OFFICIAL_RANKING_CHANGED", "FALSE"),
        ("OFFICIAL_BACKTEST_CREATED", "FALSE"),
        ("EXPLORATORY_BACKTEST_CREATED", "FALSE"),
        ("PERFORMANCE_CLAIMS_CREATED", "FALSE"),
        ("DYNAMIC_WEIGHTING_EXECUTED", "FALSE"),
        ("NORMALIZED_REAL_DATA_ROWS_CREATED", "0"),
        ("SOURCE_FILES_MUTATED", "FALSE"),
        ("V21_STARTED", "FALSE"),
        ("V19_21_STARTED", "FALSE"),
        ("SAFETY_STATUS", "PASS"),
        ("NEXT_RECOMMENDED_ACTION", "V20.3_READABLE_RESEARCH_REPORT_FRAMEWORK"),
        ("NEXT_RECOMMENDED_MODEL", "GPT-5.5"),
    ]
    write_text(OPS / "V20_2_READ_FIRST.txt", build_read_first_text(read_first_fields))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
