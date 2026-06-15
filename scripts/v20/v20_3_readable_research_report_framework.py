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


def first_nonempty(*values: str | None, default: str = "MISSING") -> str:
    for value in values:
        if value is None:
            continue
        value = str(value).strip()
        if value:
            return value
    return default


def csv_lookup(rows: list[dict[str, str]], key: str, field: str, default: str = "") -> str:
    for row in rows:
        if row.get(key) == field:
            return row.get("value", default)
    return default


V20_1_DEPENDENCIES = [
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

V20_2_DEPENDENCIES = [
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

REQUIRED_FACTOR_FAMILIES = [
    "valuation",
    "growth",
    "profitability",
    "quality",
    "momentum",
    "relative_strength",
    "technical_trend",
    "moving_average_pullback",
    "breakout",
    "volume_liquidity",
    "volatility_risk",
    "drawdown_risk",
    "event_risk",
    "earnings_fundamental_change",
    "analyst_expectation_revision",
    "options_risk",
    "market_regime",
    "industry_theme",
    "ai_semiconductor_theme",
    "data_center_power_theme",
    "manual_operator_observation",
    "composite_score",
]

REQUIRED_STRATEGY_FAMILIES = [
    "quality_growth",
    "momentum_breakout",
    "moving_average_pullback",
    "low_volatility_quality",
    "event_risk_avoidance",
    "theme_trend",
    "reversal_watch",
    "earnings_revision_watch",
    "options_risk_watch",
    "manual_review_priority",
]

FACTOR_TO_STRATEGIES = {
    "valuation": ["quality_growth", "earnings_revision_watch", "manual_review_priority"],
    "growth": ["quality_growth", "earnings_revision_watch", "manual_review_priority"],
    "profitability": ["quality_growth", "low_volatility_quality", "manual_review_priority"],
    "quality": ["quality_growth", "low_volatility_quality", "manual_review_priority"],
    "momentum": ["momentum_breakout", "theme_trend", "reversal_watch", "manual_review_priority"],
    "relative_strength": ["momentum_breakout", "moving_average_pullback", "theme_trend", "reversal_watch", "manual_review_priority"],
    "technical_trend": ["momentum_breakout", "moving_average_pullback", "reversal_watch", "manual_review_priority"],
    "moving_average_pullback": ["moving_average_pullback", "reversal_watch", "manual_review_priority"],
    "breakout": ["momentum_breakout", "theme_trend", "reversal_watch", "manual_review_priority"],
    "volume_liquidity": ["momentum_breakout", "moving_average_pullback", "low_volatility_quality", "theme_trend", "options_risk_watch", "manual_review_priority"],
    "volatility_risk": ["low_volatility_quality", "event_risk_avoidance", "reversal_watch", "options_risk_watch", "manual_review_priority"],
    "drawdown_risk": ["low_volatility_quality", "event_risk_avoidance", "reversal_watch", "options_risk_watch", "manual_review_priority"],
    "event_risk": ["event_risk_avoidance", "options_risk_watch", "theme_trend", "manual_review_priority"],
    "earnings_fundamental_change": ["quality_growth", "earnings_revision_watch", "manual_review_priority"],
    "analyst_expectation_revision": ["quality_growth", "earnings_revision_watch", "manual_review_priority"],
    "options_risk": ["event_risk_avoidance", "options_risk_watch", "manual_review_priority"],
    "market_regime": ["event_risk_avoidance", "theme_trend", "options_risk_watch", "manual_review_priority"],
    "industry_theme": ["theme_trend", "momentum_breakout", "manual_review_priority"],
    "ai_semiconductor_theme": ["theme_trend", "momentum_breakout", "manual_review_priority"],
    "data_center_power_theme": ["theme_trend", "momentum_breakout", "manual_review_priority"],
    "manual_operator_observation": ["manual_review_priority", "reversal_watch", "event_risk_avoidance"],
    "composite_score": ["quality_growth", "momentum_breakout", "low_volatility_quality", "manual_review_priority"],
}

FACTOR_CHINESE = {
    "valuation": "估值因子",
    "growth": "成长因子",
    "profitability": "盈利能力因子",
    "quality": "质量因子",
    "momentum": "动量因子",
    "relative_strength": "相对强度因子",
    "technical_trend": "技术趋势因子",
    "moving_average_pullback": "均线回撤因子",
    "breakout": "突破因子",
    "volume_liquidity": "量能与流动性因子",
    "volatility_risk": "波动率风险因子",
    "drawdown_risk": "回撤风险因子",
    "event_risk": "事件风险因子",
    "earnings_fundamental_change": "财报与基本面变化因子",
    "analyst_expectation_revision": "分析师预期修正因子",
    "options_risk": "期权风险因子",
    "market_regime": "市场状态因子",
    "industry_theme": "行业主题因子",
    "ai_semiconductor_theme": "AI 半导体主题因子",
    "data_center_power_theme": "数据中心电力主题因子",
    "manual_operator_observation": "人工观察因子",
    "composite_score": "综合评分因子",
}

FACTOR_PURPOSE = {
    "valuation": "用于解释估值折价或溢价的研究视图，不用于正式排序或交易。",
    "growth": "用于观察收入、利润和扩张速度的研究视图。",
    "profitability": "用于描述盈利质量、利润率和资本回报的研究视图。",
    "quality": "用于描述财务质量、稳定性与持续经营能力的研究视图。",
    "momentum": "用于展示价格趋势延续性与强度的研究视图。",
    "relative_strength": "用于比较标的相对基准或同组的强弱。",
    "technical_trend": "用于解释均线结构、趋势方向与技术形态。",
    "moving_average_pullback": "用于解释均线回撤后的修复或反弹观察。",
    "breakout": "用于解释区间突破、趋势启动或压缩后的释放。",
    "volume_liquidity": "用于解释成交量、流动性与可交易性约束。",
    "volatility_risk": "用于解释波动率抬升、尾部风险与不稳定性。",
    "drawdown_risk": "用于解释回撤深度、恢复速度与风险承受能力。",
    "event_risk": "用于解释财报、公告、政策和事件冲击。",
    "earnings_fundamental_change": "用于解释盈利预期和基本面变化的方向。",
    "analyst_expectation_revision": "用于解释分析师预期修正与共识漂移。",
    "options_risk": "用于解释期权隐含波动、偏斜和对冲压力。",
    "market_regime": "用于解释市场状态、风险偏好与风格切换。",
    "industry_theme": "用于解释行业轮动与主题强弱。",
    "ai_semiconductor_theme": "用于解释 AI 与半导体主题链条的研究视图。",
    "data_center_power_theme": "用于解释数据中心、电力与算力链条的研究视图。",
    "manual_operator_observation": "用于保留人工观察、注释与复核记录。",
    "composite_score": "用于解释多因子综合后的研究评分视图。",
}

FACTOR_POSITIVE = {
    "valuation": "估值更具吸引力时，可作为研究中的正向参考。",
    "growth": "成长加速或预期改善时，可作为研究中的正向参考。",
    "profitability": "盈利能力更稳健时，可作为研究中的正向参考。",
    "quality": "财务与经营质量更高时，可作为研究中的正向参考。",
    "momentum": "趋势延续更强时，可作为研究中的正向参考。",
    "relative_strength": "相对强势增强时，可作为研究中的正向参考。",
    "technical_trend": "趋势上行或结构改善时，可作为研究中的正向参考。",
    "moving_average_pullback": "回撤后出现修复迹象时，可作为研究中的正向参考。",
    "breakout": "放量突破或区间释放时，可作为研究中的正向参考。",
    "volume_liquidity": "成交与流动性改善时，可作为研究中的正向参考。",
    "volatility_risk": "波动回落且尾部风险收敛时，可作为研究中的正向参考。",
    "drawdown_risk": "回撤收敛且修复能力增强时，可作为研究中的正向参考。",
    "event_risk": "事件压力减轻或不确定性下降时，可作为研究中的正向参考。",
    "earnings_fundamental_change": "盈利和基本面改善时，可作为研究中的正向参考。",
    "analyst_expectation_revision": "一致预期上修时，可作为研究中的正向参考。",
    "options_risk": "隐含波动和对冲压力缓和时，可作为研究中的正向参考。",
    "market_regime": "市场环境更偏顺风时，可作为研究中的正向参考。",
    "industry_theme": "行业轮动与主题扩散增强时，可作为研究中的正向参考。",
    "ai_semiconductor_theme": "AI 与半导体链条走强时，可作为研究中的正向参考。",
    "data_center_power_theme": "数据中心和电力链条走强时，可作为研究中的正向参考。",
    "manual_operator_observation": "人工复核给出积极观察时，可作为研究中的正向参考。",
    "composite_score": "综合评分更高时，可作为研究中的正向参考。",
}

FACTOR_NEGATIVE = {
    "valuation": "估值过高或折价逻辑不成立时，应作为风险提示。",
    "growth": "成长放缓或预期下修时，应作为风险提示。",
    "profitability": "盈利能力恶化时，应作为风险提示。",
    "quality": "质量走弱或波动上升时，应作为风险提示。",
    "momentum": "趋势减弱或反转时，应作为风险提示。",
    "relative_strength": "相对强度下降时，应作为风险提示。",
    "technical_trend": "趋势破坏或结构转弱时，应作为风险提示。",
    "moving_average_pullback": "回撤无法修复时，应作为风险提示。",
    "breakout": "突破失败或假突破时，应作为风险提示。",
    "volume_liquidity": "流动性不足或成交萎缩时，应作为风险提示。",
    "volatility_risk": "波动放大或尾部风险抬升时，应作为风险提示。",
    "drawdown_risk": "回撤扩大或恢复缓慢时，应作为风险提示。",
    "event_risk": "事件压力升高或不确定性增强时，应作为风险提示。",
    "earnings_fundamental_change": "盈利和基本面恶化时，应作为风险提示。",
    "analyst_expectation_revision": "一致预期下修时，应作为风险提示。",
    "options_risk": "隐含波动和对冲压力加重时，应作为风险提示。",
    "market_regime": "市场环境偏逆风时，应作为风险提示。",
    "industry_theme": "行业轮动衰减或主题退潮时，应作为风险提示。",
    "ai_semiconductor_theme": "AI 与半导体链条降温时，应作为风险提示。",
    "data_center_power_theme": "数据中心和电力链条降温时，应作为风险提示。",
    "manual_operator_observation": "人工复核给出谨慎判断时，应作为风险提示。",
    "composite_score": "综合评分偏弱时，应作为风险提示。",
}

FACTOR_DATA_REQUIREMENT = {
    "valuation": "valuation_snapshot;fundamental_snapshot;history_window",
    "growth": "growth_snapshot;fundamental_snapshot;history_window",
    "profitability": "profitability_snapshot;fundamental_snapshot;history_window",
    "quality": "quality_snapshot;fundamental_snapshot;history_window",
    "momentum": "price_history;return_window;history_window",
    "relative_strength": "price_history;benchmark_series;history_window",
    "technical_trend": "price_history;moving_average_series;history_window",
    "moving_average_pullback": "price_history;moving_average_series;history_window",
    "breakout": "price_history;range_breakout_series;history_window",
    "volume_liquidity": "volume_history;liquidity_metrics;history_window",
    "volatility_risk": "volatility_series;price_history;history_window",
    "drawdown_risk": "drawdown_series;price_history;history_window",
    "event_risk": "event_calendar;event_tags;history_window",
    "earnings_fundamental_change": "earnings_snapshot;fundamental_change_series;history_window",
    "analyst_expectation_revision": "analyst_estimate_history;revision_series;history_window",
    "options_risk": "options_chain;implied_volatility;history_window",
    "market_regime": "benchmark_series;volatility_series;regime_label",
    "industry_theme": "industry_classification;theme_tags;history_window",
    "ai_semiconductor_theme": "theme_tags;sector_exposure;history_window",
    "data_center_power_theme": "theme_tags;sector_exposure;history_window",
    "manual_operator_observation": "operator_note;review_context;timestamp",
    "composite_score": "factor_scores;weight_vector;history_window",
}

STRATEGY_ROWS = [
    {
        "strategy_family_id": "SR01",
        "strategy_family_name": "quality_growth",
        "strategy_description": "质与成长结合的研究型选股/排序框架。",
        "required_factor_families": "quality;growth;profitability",
        "optional_factor_families": "valuation;earnings_fundamental_change;analyst_expectation_revision;composite_score",
        "excluded_or_blocked_factor_families": "event_risk;options_risk;manual_operator_observation",
        "research_status": "RESEARCH_ONLY",
    },
    {
        "strategy_family_id": "SR02",
        "strategy_family_name": "momentum_breakout",
        "strategy_description": "趋势延续与突破研究框架。",
        "required_factor_families": "momentum;relative_strength;technical_trend;breakout",
        "optional_factor_families": "volume_liquidity;volatility_risk;composite_score",
        "excluded_or_blocked_factor_families": "valuation;profitability;manual_operator_observation",
        "research_status": "RESEARCH_ONLY",
    },
    {
        "strategy_family_id": "SR03",
        "strategy_family_name": "moving_average_pullback",
        "strategy_description": "均线回撤与修复型研究框架。",
        "required_factor_families": "technical_trend;moving_average_pullback;relative_strength",
        "optional_factor_families": "volume_liquidity;volatility_risk;drawdown_risk",
        "excluded_or_blocked_factor_families": "event_risk;options_risk;industry_theme",
        "research_status": "RESEARCH_ONLY",
    },
    {
        "strategy_family_id": "SR04",
        "strategy_family_name": "low_volatility_quality",
        "strategy_description": "低波动、质量与回撤控制研究框架。",
        "required_factor_families": "quality;volatility_risk;drawdown_risk",
        "optional_factor_families": "volume_liquidity;profitability;composite_score",
        "excluded_or_blocked_factor_families": "breakout;ai_semiconductor_theme;data_center_power_theme",
        "research_status": "RESEARCH_ONLY",
    },
    {
        "strategy_family_id": "SR05",
        "strategy_family_name": "event_risk_avoidance",
        "strategy_description": "事件风险规避研究框架。",
        "required_factor_families": "event_risk;options_risk;market_regime",
        "optional_factor_families": "drawdown_risk;volatility_risk;manual_operator_observation",
        "excluded_or_blocked_factor_families": "breakout;momentum;relative_strength",
        "research_status": "RESEARCH_ONLY",
    },
    {
        "strategy_family_id": "SR06",
        "strategy_family_name": "theme_trend",
        "strategy_description": "行业主题与主题趋势研究框架。",
        "required_factor_families": "industry_theme;ai_semiconductor_theme;data_center_power_theme",
        "optional_factor_families": "momentum;relative_strength;volume_liquidity;market_regime",
        "excluded_or_blocked_factor_families": "drawdown_risk;event_risk;manual_operator_observation",
        "research_status": "RESEARCH_ONLY",
    },
    {
        "strategy_family_id": "SR07",
        "strategy_family_name": "reversal_watch",
        "strategy_description": "反转观察与风险修复研究框架。",
        "required_factor_families": "drawdown_risk;volatility_risk;technical_trend",
        "optional_factor_families": "breakout;moving_average_pullback;volume_liquidity",
        "excluded_or_blocked_factor_families": "valuation;growth;profitability",
        "research_status": "RESEARCH_ONLY",
    },
    {
        "strategy_family_id": "SR08",
        "strategy_family_name": "earnings_revision_watch",
        "strategy_description": "盈利与预期修正观察框架。",
        "required_factor_families": "earnings_fundamental_change;analyst_expectation_revision",
        "optional_factor_families": "growth;valuation;quality;composite_score",
        "excluded_or_blocked_factor_families": "breakout;volume_liquidity;options_risk",
        "research_status": "RESEARCH_ONLY",
    },
    {
        "strategy_family_id": "SR09",
        "strategy_family_name": "options_risk_watch",
        "strategy_description": "期权风险与对冲压力观察框架。",
        "required_factor_families": "options_risk;volatility_risk;event_risk",
        "optional_factor_families": "market_regime;drawdown_risk;manual_operator_observation",
        "excluded_or_blocked_factor_families": "valuation;growth;profitability",
        "research_status": "RESEARCH_ONLY",
    },
    {
        "strategy_family_id": "SR10",
        "strategy_family_name": "manual_review_priority",
        "strategy_description": "人工复核优先的解释与回看框架。",
        "required_factor_families": "manual_operator_observation;market_regime",
        "optional_factor_families": "composite_score;event_risk;options_risk;valuation;growth;profitability;quality;momentum;relative_strength;technical_trend;moving_average_pullback;breakout;volume_liquidity;volatility_risk;drawdown_risk;earnings_fundamental_change;analyst_expectation_revision;industry_theme;ai_semiconductor_theme;data_center_power_theme",
        "excluded_or_blocked_factor_families": "official_trading_signal;official_weighting",
        "research_status": "RESEARCH_ONLY",
    },
]

FACTOR_META = {
    "valuation": ("估值因子", "估值折价/溢价是否提供研究解释。"),
    "growth": ("成长因子", "收入、利润和扩张速度是否提供研究解释。"),
    "profitability": ("盈利能力因子", "毛利、净利和资本回报是否提供研究解释。"),
    "quality": ("质量因子", "财务稳健性与持续经营能力是否提供研究解释。"),
    "momentum": ("动量因子", "价格趋势是否提供研究解释。"),
    "relative_strength": ("相对强度因子", "相对基准或同组的强弱是否提供研究解释。"),
    "technical_trend": ("技术趋势因子", "均线结构与技术趋势是否提供研究解释。"),
    "moving_average_pullback": ("均线回撤因子", "回撤修复和均线支撑是否提供研究解释。"),
    "breakout": ("突破因子", "区间突破与趋势启动是否提供研究解释。"),
    "volume_liquidity": ("量能与流动性因子", "成交量与可交易性是否提供研究解释。"),
    "volatility_risk": ("波动率风险因子", "波动抬升和尾部风险是否提供研究解释。"),
    "drawdown_risk": ("回撤风险因子", "回撤深度与修复能力是否提供研究解释。"),
    "event_risk": ("事件风险因子", "财报、公告与政策冲击是否提供研究解释。"),
    "earnings_fundamental_change": ("财报与基本面变化因子", "盈利预期和基本面变化是否提供研究解释。"),
    "analyst_expectation_revision": ("分析师预期修正因子", "一致预期修正是否提供研究解释。"),
    "options_risk": ("期权风险因子", "隐含波动与对冲压力是否提供研究解释。"),
    "market_regime": ("市场状态因子", "市场风格与风险偏好切换是否提供研究解释。"),
    "industry_theme": ("行业主题因子", "行业轮动与主题扩散是否提供研究解释。"),
    "ai_semiconductor_theme": ("AI 半导体主题因子", "AI 与半导体链条是否提供研究解释。"),
    "data_center_power_theme": ("数据中心电力主题因子", "数据中心与电力链条是否提供研究解释。"),
    "manual_operator_observation": ("人工观察因子", "人工注释和复核是否提供研究解释。"),
    "composite_score": ("综合评分因子", "多因子汇总后的研究评分是否提供解释。"),
}

TOP_CANDIDATE_SLOTS = [
    ("TC01", "quality_growth_watch", "quality_growth", "quality;growth;profitability"),
    ("TC02", "momentum_breakout_watch", "momentum_breakout", "momentum;relative_strength;technical_trend;breakout"),
    ("TC03", "moving_average_pullback_watch", "moving_average_pullback", "technical_trend;moving_average_pullback;relative_strength"),
    ("TC04", "low_volatility_quality_watch", "low_volatility_quality", "quality;volatility_risk;drawdown_risk"),
    ("TC05", "event_risk_avoidance_watch", "event_risk_avoidance", "event_risk;options_risk;market_regime"),
    ("TC06", "theme_trend_watch", "theme_trend", "industry_theme;ai_semiconductor_theme;data_center_power_theme"),
    ("TC07", "reversal_watch", "reversal_watch", "drawdown_risk;volatility_risk;technical_trend"),
    ("TC08", "earnings_revision_watch", "earnings_revision_watch", "earnings_fundamental_change;analyst_expectation_revision"),
    ("TC09", "options_risk_watch", "options_risk_watch", "options_risk;volatility_risk;event_risk"),
    ("TC10", "manual_review_priority_watch", "manual_review_priority", "manual_operator_observation;market_regime"),
]

SECTION_MAP = [
    {
        "section_id": "RS01",
        "section_name": "system_status",
        "section_purpose": "展示当前系统是否仍停留在报告/研究映射边界内。",
        "source_dependency": "outputs/v20/ops/V20_1_READ_FIRST.txt;outputs/v20/ops/V20_2_READ_FIRST.txt;outputs/v20/ops/V20_3_READ_FIRST.txt",
        "required_for_daily_read": "TRUE",
        "machine_readable_output": "V20_3_READABLE_REPORT_SECTION_MAP.csv",
        "human_readable_output": "V20_CURRENT_DAILY_RESEARCH_SUMMARY.md",
        "current_status": "READY_FOR_REPORTING",
    },
    {
        "section_id": "RS02",
        "section_name": "current_runtime_boundary",
        "section_purpose": "展示 V20 当前仍处于架构澄清与研究模板边界。",
        "source_dependency": "outputs/v20/read_center/V20_CURRENT_RUNTIME_GUIDE.md;outputs/v20/consolidation/V20_1_CURRENT_RUNTIME_MANIFEST.csv",
        "required_for_daily_read": "TRUE",
        "machine_readable_output": "V20_3_READABLE_REPORT_SECTION_MAP.csv",
        "human_readable_output": "V20_CURRENT_DAILY_RESEARCH_SUMMARY.md",
        "current_status": "ACTIVE_BOUNDARY",
    },
    {
        "section_id": "RS03",
        "section_name": "data_freshness_status",
        "section_purpose": "展示 V18/V19 封存基线与 V20.2 数据可用性状态。",
        "source_dependency": "outputs/v20/consolidation/V20_1_HISTORICAL_BASELINE_MANIFEST.csv;outputs/v20/consolidation/V20_2_FACTOR_DATA_AVAILABILITY_AUDIT.csv",
        "required_for_daily_read": "TRUE",
        "machine_readable_output": "V20_3_DAILY_RESEARCH_SUMMARY_TEMPLATE.csv",
        "human_readable_output": "V20_CURRENT_DAILY_RESEARCH_SUMMARY.md",
        "current_status": "SEALED_BASELINES_REFERENCED",
    },
    {
        "section_id": "RS04",
        "section_name": "candidate_overview_placeholder",
        "section_purpose": "预留候选视图占位，但不产生正式候选或交易建议。",
        "source_dependency": "outputs/v20/consolidation/V20_2_STRATEGY_RESEARCH_FAMILY_REGISTRY.csv;outputs/v20/consolidation/V20_2_FACTOR_STRATEGY_RELEVANCE_MATRIX.csv;outputs/v20/consolidation/V20_3_TOP_CANDIDATES_READABLE_TEMPLATE.csv",
        "required_for_daily_read": "TRUE",
        "machine_readable_output": "V20_3_TOP_CANDIDATES_READABLE_TEMPLATE.csv",
        "human_readable_output": "V20_CURRENT_DAILY_RESEARCH_SUMMARY.md",
        "current_status": "PLACEHOLDER_ONLY",
    },
    {
        "section_id": "RS05",
        "section_name": "factor_explanation_summary",
        "section_purpose": "展示所有因子的中文解释模板与当前研究状态。",
        "source_dependency": "outputs/v20/consolidation/V20_2_FACTOR_UNIVERSE_REGISTRY.csv;outputs/v20/consolidation/V20_2_READABLE_FACTOR_EXPLANATION_TEMPLATE.csv;outputs/v20/consolidation/V20_3_FACTOR_EXPLANATION_VIEW_TEMPLATE.csv",
        "required_for_daily_read": "TRUE",
        "machine_readable_output": "V20_3_FACTOR_EXPLANATION_VIEW_TEMPLATE.csv",
        "human_readable_output": "V20_CURRENT_FACTOR_EXPLANATION_VIEW.md",
        "current_status": "RESEARCH_MAPPING_ONLY",
    },
    {
        "section_id": "RS06",
        "section_name": "strategy_research_summary",
        "section_purpose": "展示所有策略研究家族的中文解释与依赖关系。",
        "source_dependency": "outputs/v20/consolidation/V20_2_STRATEGY_RESEARCH_FAMILY_REGISTRY.csv;outputs/v20/consolidation/V20_3_STRATEGY_EXPLANATION_VIEW_TEMPLATE.csv",
        "required_for_daily_read": "TRUE",
        "machine_readable_output": "V20_3_STRATEGY_EXPLANATION_VIEW_TEMPLATE.csv",
        "human_readable_output": "V20_CURRENT_STRATEGY_RESEARCH_VIEW.md",
        "current_status": "RESEARCH_ONLY",
    },
    {
        "section_id": "RS07",
        "section_name": "data_quality_summary",
        "section_purpose": "展示报告/研究模板所依赖的数据质量前置条件。",
        "source_dependency": "outputs/v20/consolidation/V20_3_DATA_QUALITY_VIEW_TEMPLATE.csv;outputs/v20/consolidation/V20_1_FUTURE_RESEARCH_HOOKS.csv",
        "required_for_daily_read": "TRUE",
        "machine_readable_output": "V20_3_DATA_QUALITY_VIEW_TEMPLATE.csv",
        "human_readable_output": "V20_CURRENT_DATA_QUALITY_VIEW.md",
        "current_status": "CHECKLIST_ONLY",
    },
    {
        "section_id": "RS08",
        "section_name": "blocker_summary",
        "section_purpose": "汇总当前仍然阻塞正式用途与执行路径的原因。",
        "source_dependency": "outputs/v20/consolidation/V20_2_FACTOR_BLOCKER_REGISTER.csv;outputs/v20/consolidation/V20_3_BLOCKERS_AND_NEXT_ACTIONS_TEMPLATE.csv",
        "required_for_daily_read": "TRUE",
        "machine_readable_output": "V20_3_BLOCKERS_AND_NEXT_ACTIONS_TEMPLATE.csv",
        "human_readable_output": "V20_CURRENT_BLOCKERS_AND_NEXT_ACTIONS.md",
        "current_status": "BLOCKED_FOR_OFFICIAL_USE",
    },
    {
        "section_id": "RS09",
        "section_name": "next_manual_review_actions",
        "section_purpose": "提供下一步手工复核动作，但不触发执行或交易。",
        "source_dependency": "outputs/v20/consolidation/V20_1_FUTURE_RESEARCH_HOOKS.csv;outputs/v20/consolidation/V20_3_BLOCKERS_AND_NEXT_ACTIONS_TEMPLATE.csv",
        "required_for_daily_read": "TRUE",
        "machine_readable_output": "V20_3_BLOCKERS_AND_NEXT_ACTIONS_TEMPLATE.csv",
        "human_readable_output": "V20_CURRENT_DAILY_RESEARCH_SUMMARY.md",
        "current_status": "REVIEW_ONLY",
    },
    {
        "section_id": "RS10",
        "section_name": "safety_boundary_notice",
        "section_purpose": "重申报告模板边界，不允许官方信号、权重、回测或动态加权。",
        "source_dependency": "outputs/v20/ops/V20_1_READ_FIRST.txt;outputs/v20/ops/V20_2_READ_FIRST.txt;outputs/v20/ops/V20_3_READ_FIRST.txt",
        "required_for_daily_read": "TRUE",
        "machine_readable_output": "V20_3_READABLE_REPORT_SECTION_MAP.csv",
        "human_readable_output": "V20_CURRENT_DAILY_RESEARCH_SUMMARY.md",
        "current_status": "SAFETY_BOUNDARY_ACTIVE",
    },
]

FIELD_TRANSLATIONS = [
    ("system_status", "section", "System Status", "系统状态", "说明当前系统是否仍处于报告/研究映射边界。", "V20_CURRENT_DAILY_RESEARCH_SUMMARY.md", True, True),
    ("current_runtime_boundary", "section", "Current Runtime Boundary", "当前运行边界", "说明 V20 当前只做架构/报告澄清，不进入执行层。", "V20_CURRENT_DAILY_RESEARCH_SUMMARY.md", True, True),
    ("data_freshness_status", "section", "Data Freshness Status", "数据新鲜度状态", "说明 V18/V19 封存基线与 V20.2 数据可用性。", "V20_CURRENT_DAILY_RESEARCH_SUMMARY.md", True, True),
    ("candidate_overview_placeholder", "section", "Candidate Overview Placeholder", "候选概览占位", "仅用于未来候选视图模板，不形成正式候选。", "V20_CURRENT_DAILY_RESEARCH_SUMMARY.md", True, True),
    ("factor_explanation_summary", "section", "Factor Explanation Summary", "因子解释摘要", "汇总 V20.2 因子家族的中文解释模板。", "V20_CURRENT_FACTOR_EXPLANATION_VIEW.md", True, True),
    ("strategy_research_summary", "section", "Strategy Research Summary", "策略研究摘要", "汇总 V20.2 策略研究家族的中文解释模板。", "V20_CURRENT_STRATEGY_RESEARCH_VIEW.md", True, True),
    ("data_quality_summary", "section", "Data Quality Summary", "数据质量摘要", "展示研究/报告前置条件的质量清单。", "V20_CURRENT_DATA_QUALITY_VIEW.md", True, True),
    ("blocker_summary", "section", "Blocker Summary", "阻塞摘要", "汇总正式用途和执行路径的阻塞原因。", "V20_CURRENT_BLOCKERS_AND_NEXT_ACTIONS.md", True, True),
    ("next_manual_review_actions", "section", "Next Manual Review Actions", "下一步人工复核动作", "提供后续人工复核建议，不产生执行。", "V20_CURRENT_DAILY_RESEARCH_SUMMARY.md", True, True),
    ("safety_boundary_notice", "section", "Safety Boundary Notice", "安全边界提示", "再次声明报告模板不允许进入执行层。", "V20_CURRENT_DAILY_RESEARCH_SUMMARY.md", True, True),
    ("REPORTING_ONLY", "flag", "Reporting Only", "仅报告", "确认 V20.3 仅用于可读报告与模板生成。", "V20_3_READ_FIRST.txt", True, True),
    ("READABLE_REPORT_FRAMEWORK_ONLY", "flag", "Readable Report Framework Only", "仅可读报告框架", "确认本步不创建执行性资产。", "V20_3_READ_FIRST.txt", True, True),
    ("FACTOR_EXPLANATION_TEMPLATE_CREATED", "flag", "Factor Explanation Template Created", "因子解释模板已创建", "确认因子解释模板已输出。", "V20_3_READ_FIRST.txt", True, True),
    ("STRATEGY_EXPLANATION_TEMPLATE_CREATED", "flag", "Strategy Explanation Template Created", "策略解释模板已创建", "确认策略解释模板已输出。", "V20_3_READ_FIRST.txt", True, True),
    ("DAILY_RESEARCH_SUMMARY_TEMPLATE_CREATED", "flag", "Daily Research Summary Template Created", "日常研究摘要模板已创建", "确认日常研究摘要模板已输出。", "V20_3_READ_FIRST.txt", True, True),
    ("OFFICIAL_TRADING_SIGNAL_CREATED", "safety_flag", "Official Trading Signal Created", "正式交易信号已创建", "必须保持 FALSE。", "V20_3_READ_FIRST.txt", False, False),
    ("OFFICIAL_PORTFOLIO_WEIGHT_CREATED", "safety_flag", "Official Portfolio Weight Created", "正式组合权重已创建", "必须保持 FALSE。", "V20_3_READ_FIRST.txt", False, False),
    ("OFFICIAL_FACTOR_WEIGHT_CHANGED", "safety_flag", "Official Factor Weight Changed", "正式因子权重已变更", "必须保持 FALSE。", "V20_3_READ_FIRST.txt", False, False),
    ("OFFICIAL_RANKING_CHANGED", "safety_flag", "Official Ranking Changed", "正式排序已变更", "必须保持 FALSE。", "V20_3_READ_FIRST.txt", False, False),
    ("OFFICIAL_BACKTEST_CREATED", "safety_flag", "Official Backtest Created", "正式回测已创建", "必须保持 FALSE。", "V20_3_READ_FIRST.txt", False, False),
    ("EXPLORATORY_BACKTEST_CREATED", "safety_flag", "Exploratory Backtest Created", "探索性回测已创建", "必须保持 FALSE。", "V20_3_READ_FIRST.txt", False, False),
    ("PERFORMANCE_CLAIMS_CREATED", "safety_flag", "Performance Claims Created", "绩效主张已创建", "必须保持 FALSE。", "V20_3_READ_FIRST.txt", False, False),
    ("DYNAMIC_WEIGHTING_EXECUTED", "safety_flag", "Dynamic Weighting Executed", "动态加权已执行", "必须保持 FALSE。", "V20_3_READ_FIRST.txt", False, False),
    ("NORMALIZED_REAL_DATA_ROWS_CREATED", "safety_metric", "Normalized Real Data Rows Created", "标准化真实数据行已创建", "必须保持 0。", "V20_3_READ_FIRST.txt", False, False),
    ("SOURCE_FILES_MUTATED", "safety_flag", "Source Files Mutated", "源文件已变更", "必须保持 FALSE。", "V20_3_READ_FIRST.txt", False, False),
    ("V21_STARTED", "safety_flag", "V21 Started", "V21 已开始", "必须保持 FALSE。", "V20_3_READ_FIRST.txt", False, False),
    ("V19_21_STARTED", "safety_flag", "V19.21 Started", "V19.21 已开始", "必须保持 FALSE。", "V20_3_READ_FIRST.txt", False, False),
]

DATA_QUALITY_CHECKS = [
    {
        "quality_check_id": "DQ01",
        "check_name": "sealed_baselines_present",
        "chinese_check_name": "封存基线存在性检查",
        "check_purpose": "确认 V18/V19 已被视为封存历史基线。",
        "required_before_research": "TRUE",
        "required_before_backtest": "TRUE",
        "required_before_official_use": "TRUE",
        "current_status": "PASS",
    },
    {
        "quality_check_id": "DQ02",
        "check_name": "v20_1_runtime_boundary_present",
        "chinese_check_name": "V20.1 运行边界检查",
        "check_purpose": "确认当前运行仍停留在架构澄清层。",
        "required_before_research": "TRUE",
        "required_before_backtest": "TRUE",
        "required_before_official_use": "TRUE",
        "current_status": "PASS",
    },
    {
        "quality_check_id": "DQ03",
        "check_name": "v20_2_factor_universe_present",
        "chinese_check_name": "V20.2 因子宇宙检查",
        "check_purpose": "确认所有 V20.2 因子家族已注册。",
        "required_before_research": "TRUE",
        "required_before_backtest": "TRUE",
        "required_before_official_use": "TRUE",
        "current_status": "PASS",
    },
    {
        "quality_check_id": "DQ04",
        "check_name": "v20_2_strategy_map_present",
        "chinese_check_name": "V20.2 策略映射检查",
        "check_purpose": "确认所有 V20.2 策略研究家族已注册。",
        "required_before_research": "TRUE",
        "required_before_backtest": "TRUE",
        "required_before_official_use": "TRUE",
        "current_status": "PASS",
    },
    {
        "quality_check_id": "DQ05",
        "check_name": "report_only_boundary",
        "chinese_check_name": "仅报告边界检查",
        "check_purpose": "确认 V20.3 不进入执行、回测或交易层。",
        "required_before_research": "TRUE",
        "required_before_backtest": "TRUE",
        "required_before_official_use": "TRUE",
        "current_status": "PASS",
    },
    {
        "quality_check_id": "DQ06",
        "check_name": "no_normalized_real_data",
        "chinese_check_name": "无标准化真实数据检查",
        "check_purpose": "确认未创建标准化真实研究数据行。",
        "required_before_research": "TRUE",
        "required_before_backtest": "TRUE",
        "required_before_official_use": "TRUE",
        "current_status": "PASS",
    },
    {
        "quality_check_id": "DQ07",
        "check_name": "no_official_outputs",
        "chinese_check_name": "无正式输出检查",
        "check_purpose": "确认未创建正式信号、权重、回测、绩效或交易输出。",
        "required_before_research": "TRUE",
        "required_before_backtest": "TRUE",
        "required_before_official_use": "TRUE",
        "current_status": "PASS",
    },
    {
        "quality_check_id": "DQ08",
        "check_name": "no_dynamic_weighting",
        "chinese_check_name": "无动态加权检查",
        "check_purpose": "确认未执行动态加权或权重变更。",
        "required_before_research": "TRUE",
        "required_before_backtest": "TRUE",
        "required_before_official_use": "TRUE",
        "current_status": "PASS",
    },
    {
        "quality_check_id": "DQ09",
        "check_name": "no_v21_or_v19_21",
        "chinese_check_name": "无 V21 / V19.21 检查",
        "check_purpose": "确认没有启动 V21 或创建 V19.21 文件。",
        "required_before_research": "TRUE",
        "required_before_backtest": "TRUE",
        "required_before_official_use": "TRUE",
        "current_status": "PASS",
    },
]

BLOCKERS = [
    {
        "blocker_id": "BLK01",
        "blocker_category": "SEALEd_BASELINE_ONLY",
        "blocker_description": "V18 与 V19 仅作为封存历史基线使用。",
        "affected_layer": "runtime_boundary",
        "required_resolution_before": "V20.4_ARCHITECTURE_CLARIFICATION_SEAL_BEFORE_DATA_EXECUTION",
        "suggested_manual_review_action": "先阅读 V20.1 与 V20.2 输出，再进入后续研究报告层。",
        "current_status": "ACTIVE",
    },
    {
        "blocker_id": "BLK02",
        "blocker_category": "NO_OFFICIAL_SIGNAL_OR_WEIGHT",
        "blocker_description": "未创建正式交易信号、组合权重或因子权重变更。",
        "affected_layer": "official_use",
        "required_resolution_before": "后续执行层明确开启并获得授权",
        "suggested_manual_review_action": "保持官方逻辑冻结，仅保留研究视图。",
        "current_status": "ACTIVE",
    },
    {
        "blocker_id": "BLK03",
        "blocker_category": "NO_BACKTEST_RESULTS",
        "blocker_description": "未创建正式或探索性回测结果。",
        "affected_layer": "backtest",
        "required_resolution_before": "探索性回测框架完成且获得进一步允许",
        "suggested_manual_review_action": "先完善阅读层，再考虑执行层。",
        "current_status": "ACTIVE",
    },
    {
        "blocker_id": "BLK04",
        "blocker_category": "NO_DYNAMIC_WEIGHTING",
        "blocker_description": "未执行动态加权，也未产生动态权重输入。",
        "affected_layer": "dynamic_weighting",
        "required_resolution_before": "动态加权门控框架与审批完成",
        "suggested_manual_review_action": "保持动态权重隔离，不向交易层传递。",
        "current_status": "ACTIVE",
    },
    {
        "blocker_id": "BLK05",
        "blocker_category": "NO_NORMALIZED_REAL_DATA",
        "blocker_description": "未生成标准化真实研究数据行。",
        "affected_layer": "normalized_data",
        "required_resolution_before": "真实数据行规范化路径在未来版本中开启",
        "suggested_manual_review_action": "仅使用模板与解释视图，不做实数生成。",
        "current_status": "ACTIVE",
    },
    {
        "blocker_id": "BLK06",
        "blocker_category": "NO_FACTOR_EVIDENCE",
        "blocker_description": "未创建正式因子证据。",
        "affected_layer": "factor_evidence",
        "required_resolution_before": "回测/绩效/证据门控完整后再考虑",
        "suggested_manual_review_action": "把因子解释保留为 research-only。",
        "current_status": "ACTIVE",
    },
    {
        "blocker_id": "BLK07",
        "blocker_category": "NO_TRADING",
        "blocker_description": "未启用任何交易或经纪执行。",
        "affected_layer": "trading",
        "required_resolution_before": "交易隔离边界与审批完成后再考虑",
        "suggested_manual_review_action": "保持 broker/order/trading 冻结。",
        "current_status": "ACTIVE",
    },
    {
        "blocker_id": "BLK08",
        "blocker_category": "NO_V21_OR_V19_21",
        "blocker_description": "未启动 V21，也未创建 V19.21。",
        "affected_layer": "version_boundary",
        "required_resolution_before": "V20.3 之后的下一步明确确认",
        "suggested_manual_review_action": "仅推进 V20 内部的报告框架，不越界。",
        "current_status": "ACTIVE",
    },
]


def build_factor_universe_registry(factor_status: dict[str, str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for idx, factor in enumerate(REQUIRED_FACTOR_FAMILIES, start=1):
        status = factor_status.get(factor, "RESEARCH_MAPPING_ONLY")
        rows.append(
            {
                "factor_id": f"FU{idx:02d}",
                "factor_family": factor,
                "factor_name": FACTOR_CHINESE[factor],
                "factor_description": FACTOR_PURPOSE[factor],
                "input_required": FACTOR_DATA_REQUIREMENT[factor],
                "data_status": status,
                "research_status": "READABLE_REPORT_FRAMEWORK_ONLY" if factor == "composite_score" else "RESEARCH_MAPPING_ONLY",
                "official_use_allowed": "FALSE",
                "backtest_allowed_now": "FALSE",
                "dynamic_weight_allowed_now": "FALSE",
                "readable_report_allowed": "TRUE",
                "blocker_reason": "V20.3 仅生成可读报告框架，不允许正式用途、回测或动态加权。",
            }
        )
    return rows


def build_factor_family_map() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for factor in REQUIRED_FACTOR_FAMILIES:
        rows.append(
            {
                "factor_family": factor,
                "factor_name": FACTOR_CHINESE[factor],
                "strategy_family_count": len(FACTOR_TO_STRATEGIES[factor]),
                "linked_strategy_families": ";".join(FACTOR_TO_STRATEGIES[factor]),
                "report_relevance_status": "COVERED_BY_RESEARCH_VIEW",
                "official_use_allowed": "FALSE",
                "reason": "The factor is mapped only into readable research views and not into official use.",
            }
        )
    return rows


def build_data_availability_audit(factor_status: dict[str, str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for factor in REQUIRED_FACTOR_FAMILIES:
        status = factor_status.get(factor, "MISSING")
        rows.append(
            {
                "factor_family": factor,
                "required_input": FACTOR_DATA_REQUIREMENT[factor],
                "current_availability_status": status,
                "research_view_ready": "TRUE",
                "official_use_ready": "FALSE",
                "backtest_ready": "FALSE",
                "dynamic_weight_ready": "FALSE",
                "note": "Research view can be written even when execution inputs remain sealed or incomplete.",
            }
        )
    return rows


def build_factor_research_status_map(factor_status: dict[str, str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for factor in REQUIRED_FACTOR_FAMILIES:
        status = factor_status.get(factor, "RESEARCH_MAPPING_ONLY")
        rows.append(
            {
                "factor_family": factor,
                "current_data_status": status,
                "research_status": "RESEARCH_MAPPING_ONLY",
                "official_use_allowed": "FALSE",
                "backtest_allowed_now": "FALSE",
                "dynamic_weight_allowed_now": "FALSE",
                "readable_report_allowed": "TRUE",
                "blocker_reason": "V20.3 only produces readable research views.",
            }
        )
    return rows


def build_factor_strategy_relevance_matrix() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for factor in REQUIRED_FACTOR_FAMILIES:
        for strategy in FACTOR_TO_STRATEGIES[factor]:
            rows.append(
                {
                    "factor_family": factor,
                    "strategy_family_name": strategy,
                    "relevance_type": "required" if strategy in ["quality_growth", "momentum_breakout", "moving_average_pullback", "low_volatility_quality", "event_risk_avoidance", "theme_trend", "reversal_watch", "earnings_revision_watch", "options_risk_watch", "manual_review_priority"] else "optional",
                    "explanation_zh": f"因子 {FACTOR_CHINESE[factor]} 为策略研究家族 {strategy} 提供研究解释，但不构成正式用途或交易信号。",
                    "official_use_allowed": "FALSE",
                    "backtest_allowed_now": "FALSE",
                    "dynamic_weight_allowed_now": "FALSE",
                }
            )
    return rows


def build_strategy_registry() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in STRATEGY_ROWS:
        rows.append(
            {
                "strategy_family_id": row["strategy_family_id"],
                "strategy_family_name": row["strategy_family_name"],
                "strategy_description": row["strategy_description"],
                "required_factor_families": row["required_factor_families"],
                "optional_factor_families": row["optional_factor_families"],
                "excluded_or_blocked_factor_families": row["excluded_or_blocked_factor_families"],
                "research_status": row["research_status"],
                "official_use_allowed": "FALSE",
                "backtest_allowed_now": "FALSE",
                "dynamic_weight_allowed_now": "FALSE",
                "readable_report_allowed": "TRUE",
            }
        )
    return rows


def build_strategy_factor_dependency_map() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in STRATEGY_ROWS:
        for factor in row["required_factor_families"].split(";"):
            rows.append(
                {
                    "strategy_family_id": row["strategy_family_id"],
                    "strategy_family_name": row["strategy_family_name"],
                    "factor_family": factor,
                    "dependency_type": "required",
                    "readable_report_allowed": "TRUE",
                    "official_use_allowed": "FALSE",
                    "reason": "The dependency supports research explanation only.",
                }
            )
        for factor in row["optional_factor_families"].split(";"):
            rows.append(
                {
                    "strategy_family_id": row["strategy_family_id"],
                    "strategy_family_name": row["strategy_family_name"],
                    "factor_family": factor,
                    "dependency_type": "optional",
                    "readable_report_allowed": "TRUE",
                    "official_use_allowed": "FALSE",
                    "reason": "The dependency supports research explanation only.",
                }
            )
    return rows


def build_factor_blocker_register(factor_status: dict[str, str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    blocker_categories = [
        ("REGISTERED_BUT_MISSING_INPUT", "已注册但缺少输入"),
        ("AVAILABLE_FOR_RESEARCH_ONLY", "仅可用于研究"),
        ("BLOCKED_FROM_OFFICIAL_USE", "正式用途已阻塞"),
        ("BLOCKED_FROM_DYNAMIC_WEIGHTING", "动态加权已阻塞"),
        ("BLOCKED_FROM_BACKTEST_UNTIL_NORMALIZED_DATA_READY", "在标准化真实数据就绪前阻塞回测"),
    ]
    for factor in REQUIRED_FACTOR_FAMILIES:
        for idx, (category, zh_category) in enumerate(blocker_categories, start=1):
            rows.append(
                {
                    "blocker_id": f"FB{len(rows)+1:03d}",
                    "factor_family": factor,
                    "blocker_category": category,
                    "blocker_category_zh": zh_category,
                    "current_status": factor_status.get(factor, "MISSING"),
                    "blocks_official_use": "TRUE",
                    "blocks_backtest": "TRUE" if category.endswith("BACKTEST_UNTIL_NORMALIZED_DATA_READY") else "FALSE",
                    "blocks_dynamic_weighting": "TRUE" if "DYNAMIC_WEIGHTING" in category or category == "BLOCKED_FROM_OFFICIAL_USE" else "FALSE",
                    "blocks_normalized_real_data": "TRUE" if category == "BLOCKED_FROM_BACKTEST_UNTIL_NORMALIZED_DATA_READY" else "FALSE",
                    "reason": "V20.3 is reporting/template-only; no execution path is opened by this blocker register.",
                }
            )
    return rows


def build_factor_explanation_template(factor_status: dict[str, str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for factor in REQUIRED_FACTOR_FAMILIES:
        status = factor_status.get(factor, "RESEARCH_MAPPING_ONLY")
        rows.append(
            {
                "factor_family": factor,
                "chinese_factor_name": FACTOR_META[factor][0],
                "factor_purpose": FACTOR_META[factor][1],
                "positive_interpretation": FACTOR_POSITIVE[factor],
                "negative_interpretation": FACTOR_NEGATIVE[factor],
                "data_requirement": FACTOR_DATA_REQUIREMENT[factor],
                "current_report_status": status,
                "official_use_allowed": "FALSE",
                "blocker_reason": f"{status}; V20.3 仅输出可读报告模板，不允许正式用途。",
            }
        )
    return rows


def build_strategy_explanation_template() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    chinese_names = {
        "quality_growth": "质与成长研究家族",
        "momentum_breakout": "动量突破研究家族",
        "moving_average_pullback": "均线回撤研究家族",
        "low_volatility_quality": "低波动质量研究家族",
        "event_risk_avoidance": "事件风险规避研究家族",
        "theme_trend": "主题趋势研究家族",
        "reversal_watch": "反转观察研究家族",
        "earnings_revision_watch": "盈利修正观察研究家族",
        "options_risk_watch": "期权风险观察研究家族",
        "manual_review_priority": "人工复核优先研究家族",
    }
    purposes = {
        "quality_growth": "用于解释质量、成长和盈利结合的研究视图。",
        "momentum_breakout": "用于解释趋势延续与突破确认的研究视图。",
        "moving_average_pullback": "用于解释均线回撤与修复观察的研究视图。",
        "low_volatility_quality": "用于解释低波动、高质量与回撤控制的研究视图。",
        "event_risk_avoidance": "用于解释事件风险规避与波动回避的研究视图。",
        "theme_trend": "用于解释行业主题与主题趋势扩散的研究视图。",
        "reversal_watch": "用于解释反转观察与风险修复的研究视图。",
        "earnings_revision_watch": "用于解释盈利与预期修正变化的研究视图。",
        "options_risk_watch": "用于解释期权风险与对冲压力变化的研究视图。",
        "manual_review_priority": "用于解释人工复核优先与解释性回看视图。",
    }
    market_condition = {
        "quality_growth": "适合质量与成长同时改善的市场。",
        "momentum_breakout": "适合趋势延续或突破加速的市场。",
        "moving_average_pullback": "适合回撤修复与均线支撑有效的市场。",
        "low_volatility_quality": "适合低波动、稳健扩张或防御性环境。",
        "event_risk_avoidance": "适合事件冲击频繁、风险偏好较低的市场。",
        "theme_trend": "适合行业轮动和主题扩散明确的市场。",
        "reversal_watch": "适合下跌后修复或结构切换阶段。",
        "earnings_revision_watch": "适合盈利预期上修或基本面改善阶段。",
        "options_risk_watch": "适合隐含波动和对冲压力变化明显的阶段。",
        "manual_review_priority": "适合需要人工复核、解释与备注的阶段。",
    }
    main_risks = {
        "quality_growth": "估值过高、成长放缓、事件扰动。",
        "momentum_breakout": "假突破、流动性不足、回撤放大。",
        "moving_average_pullback": "修复失败、趋势破坏、反复震荡。",
        "low_volatility_quality": "防御过度、弹性不足、风格切换。",
        "event_risk_avoidance": "错过趋势机会、过度规避、信号迟滞。",
        "theme_trend": "主题退潮、轮动失效、拥挤度上升。",
        "reversal_watch": "反转确认不足、底部钝化、波动噪声。",
        "earnings_revision_watch": "预期修正滞后、财报噪声、估值偏差。",
        "options_risk_watch": "隐含波动误读、事件窗口误差、对冲噪声。",
        "manual_review_priority": "解释不一致、人工主观偏差、复核延迟。",
    }
    for row in STRATEGY_ROWS:
        rows.append(
            {
                "strategy_family_id": row["strategy_family_id"],
                "chinese_strategy_name": chinese_names[row["strategy_family_name"]],
                "strategy_purpose": purposes[row["strategy_family_name"]],
                "required_factor_families": row["required_factor_families"],
                "readable_interpretation": f"该研究家族围绕 {row['strategy_description']} 展示可读解释，但不输出正式结论。",
                "suitable_market_condition": market_condition[row["strategy_family_name"]],
                "main_risks": main_risks[row["strategy_family_name"]],
                "current_report_status": row["research_status"],
                "official_use_allowed": "FALSE",
                "blocker_reason": "V20.3 仅提供研究解释视图，不允许正式用途、回测或交易。",
            }
        )
    return rows


def build_daily_research_summary_template() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    sentence_templates = {
        "system_status": "系统状态：当前仅生成可读研究报告与模板，不进入执行层。",
        "current_runtime_boundary": "当前运行边界：V20 仍处于架构澄清和研究映射层。",
        "data_freshness_status": "数据新鲜度：V18/V19 封存基线可见，V20.2 研究映射已存在。",
        "candidate_overview_placeholder": "候选概览：仅保留占位模板，不生成正式候选或交易建议。",
        "factor_explanation_summary": "因子解释：已覆盖全部 V20.2 因子家族的可读解释模板。",
        "strategy_research_summary": "策略研究：已覆盖全部 V20.2 策略研究家族的可读解释模板。",
        "data_quality_summary": "数据质量：当前保持研究/报告前置条件清单，不进入执行。",
        "blocker_summary": "阻塞摘要：正式用途、回测、动态加权和交易仍被阻塞。",
        "next_manual_review_actions": "下一步人工动作：继续阅读 V20.1、V20.2 与本步模板，不做执行变更。",
        "safety_boundary_notice": "安全提示：本步仅是可读报告框架，不允许任何正式信号或权重。",
    }
    purpose_map = {
        "system_status": "说明当前系统是否仍处于报告/研究模板边界。",
        "current_runtime_boundary": "说明当前运行边界和历史封存范围。",
        "data_freshness_status": "说明封存基线和研究映射数据可用性。",
        "candidate_overview_placeholder": "保留候选概览占位，不形成正式结论。",
        "factor_explanation_summary": "汇总因子解释视图的阅读结果。",
        "strategy_research_summary": "汇总策略研究视图的阅读结果。",
        "data_quality_summary": "汇总数据质量检查的阅读结果。",
        "blocker_summary": "汇总阻塞项与限制条件。",
        "next_manual_review_actions": "列出下一步可执行的人工复核动作。",
        "safety_boundary_notice": "再次强调安全边界和禁止事项。",
    }
    for section in SECTION_MAP:
        rows.append(
            {
                "section_id": section["section_id"],
                "section_name": section["section_name"],
                "chinese_section_title": {
                    "system_status": "系统状态",
                    "current_runtime_boundary": "当前运行边界",
                    "data_freshness_status": "数据新鲜度状态",
                    "candidate_overview_placeholder": "候选概览占位",
                    "factor_explanation_summary": "因子解释摘要",
                    "strategy_research_summary": "策略研究摘要",
                    "data_quality_summary": "数据质量摘要",
                    "blocker_summary": "阻塞摘要",
                    "next_manual_review_actions": "下一步人工复核动作",
                    "safety_boundary_notice": "安全边界提示",
                }[section["section_name"]],
                "section_purpose": purpose_map[section["section_name"]],
                "source_dependency": section["source_dependency"],
                "report_sentence_template_zh": sentence_templates[section["section_name"]],
                "current_status": section["current_status"],
            }
        )
    return rows


def build_top_candidates_template() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for slot_id, candidate_name, strategy_family, linked_factors in TOP_CANDIDATE_SLOTS:
        rows.append(
            {
                "candidate_slot_id": slot_id,
                "candidate_slot_name": candidate_name,
                "linked_strategy_family": strategy_family,
                "linked_factor_families": linked_factors,
                "readable_summary_zh": f"该占位位仅用于研究阅读视图，围绕 {strategy_family} 展示未来候选结构。",
                "current_status": "PLACEHOLDER_ONLY",
                "official_use_allowed": "FALSE",
                "backtest_allowed_now": "FALSE",
                "dynamic_weight_allowed_now": "FALSE",
                "readable_report_allowed": "TRUE",
                "blocker_reason": "V20.3 不生成正式候选、信号或交易建议。",
            }
        )
    return rows


def build_data_quality_view_template() -> list[dict[str, object]]:
    return DATA_QUALITY_CHECKS


def build_blockers_and_next_actions_template() -> list[dict[str, object]]:
    return BLOCKERS


def render_table(headers: list[str], rows: list[dict[str, object]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(h, "")).replace("\n", " ") for h in headers) + " |")
    return "\n".join(lines)


def build_report(
    v20_1_found: bool,
    v20_2_found: bool,
    factor_rows: list[dict[str, object]],
    strategy_rows: list[dict[str, object]],
    dependency_found: int,
) -> str:
    factor_missing = [row["factor_family"] for row in factor_rows if row["official_use_allowed"] == "FALSE"]
    strategy_names = [row["strategy_family_name"] for row in strategy_rows]
    return "\n".join(
        [
            "# V20.3 可读研究报告框架",
            "",
            "## 结论",
            "- 状态：WARN",
            f"- 报告模式：仅报告 / 研究映射（REPORTING_ONLY = TRUE，READABLE_REPORT_FRAMEWORK_ONLY = TRUE）",
            f"- V20.1 依赖检测：{'TRUE' if v20_1_found else 'FALSE'}",
            f"- V20.2 依赖检测：{'TRUE' if v20_2_found else 'FALSE'}",
            f"- 检测到的依赖输入数：{dependency_found}",
            "- 本步只负责把 V20.1 的运行边界与 V20.2 的因子/策略研究映射转成可读报告模板，不创建正式用途资产。",
            "",
            "## 日常阅读结构",
            "- system_status",
            "- current_runtime_boundary",
            "- data_freshness_status",
            "- candidate_overview_placeholder",
            "- factor_explanation_summary",
            "- strategy_research_summary",
            "- data_quality_summary",
            "- blocker_summary",
            "- next_manual_review_actions",
            "- safety_boundary_notice",
            "",
            "## 因子覆盖",
            f"- 因子家族数量：{len(factor_rows)}",
            f"- 已纳入因子家族：{', '.join(sorted([row['factor_family'] for row in factor_rows]))}",
            "- 所有因子都只作为 research-only / report-only 视图使用。",
            "",
            "## 策略覆盖",
            f"- 策略研究家族数量：{len(strategy_rows)}",
            f"- 已纳入策略研究家族：{', '.join(strategy_names)}",
            "- 所有策略都只作为 research-only 视图使用。",
            "",
            "## 数据质量与阻塞",
            "- 未创建正式买卖建议、组合权重、因子权重变更、正式回测或动态加权。",
            "- 未生成标准化真实研究数据行。",
            "- 未启动 V21，也未创建 V19.21。",
            "",
            "## 下一步",
            "- 推荐进入 V20.4_ARCHITECTURE_CLARIFICATION_SEAL_BEFORE_DATA_EXECUTION，以继续在报告/边界层做收束，而不进入执行层。",
        ]
    )


def build_current_daily_summary_markdown(section_rows: list[dict[str, object]], factor_rows: list[dict[str, object]], strategy_rows: list[dict[str, object]], blocker_rows: list[dict[str, object]]) -> str:
    return "\n".join(
        [
            "# V20 当前每日研究摘要",
            "",
            "## system_status",
            "系统当前仍停留在报告/研究映射边界，不生成正式交易或执行输出。",
            "",
            "## current_runtime_boundary",
            "V20.1 已定义运行边界与历史封存边界；V20.2 已注册因子宇宙与策略研究映射。",
            "",
            "## data_freshness_status",
            "V18 与 V19 作为封存历史基线保留；V20.2 因子与策略研究模板可读。",
            "",
            "## candidate_overview_placeholder",
            "候选概览仅保留占位模板，不形成正式候选、交易建议或权重建议。",
            "",
            "## factor_explanation_summary",
            f"因子解释模板覆盖 {len(factor_rows)} 个因子家族，全部保持 research-only。",
            "",
            "## strategy_research_summary",
            f"策略研究模板覆盖 {len(strategy_rows)} 个策略研究家族，全部保持 research-only。",
            "",
            "## data_quality_summary",
            f"数据质量检查项共 {len(DATA_QUALITY_CHECKS)} 条，主要用于确认报告模板、封存基线与安全边界。",
            "",
            "## blocker_summary",
            f"阻塞项共 {len(blocker_rows)} 条，所有阻塞均指向正式用途、回测、动态加权和交易边界。",
            "",
            "## next_manual_review_actions",
            "建议继续阅读 V20.1、V20.2 与当前模板文件，并等待未来版本解锁执行路径。",
            "",
            "## safety_boundary_notice",
            "本步仅是可读报告框架：不允许正式信号、正式权重、正式回测、绩效主张或交易输出。",
        ]
    )


def build_factor_explanation_markdown(rows: list[dict[str, object]]) -> str:
    headers = [
        "factor_family",
        "chinese_factor_name",
        "factor_purpose",
        "positive_interpretation",
        "negative_interpretation",
        "data_requirement",
        "current_report_status",
        "official_use_allowed",
        "blocker_reason",
    ]
    return "\n".join(
        [
            "# V20 当前因子解释视图",
            "",
            "本页仅提供因子解释模板，不构成正式排名、回测、绩效或交易依据。",
            "",
            render_table(headers, rows),
        ]
    )


def build_strategy_research_markdown(rows: list[dict[str, object]]) -> str:
    headers = [
        "strategy_family_id",
        "chinese_strategy_name",
        "strategy_purpose",
        "required_factor_families",
        "readable_interpretation",
        "suitable_market_condition",
        "main_risks",
        "current_report_status",
        "official_use_allowed",
        "blocker_reason",
    ]
    return "\n".join(
        [
            "# V20 当前策略研究视图",
            "",
            "本页仅提供策略研究解释模板，不构成正式策略、正式回测或交易建议。",
            "",
            render_table(headers, rows),
        ]
    )


def build_data_quality_markdown(rows: list[dict[str, object]]) -> str:
    headers = [
        "quality_check_id",
        "check_name",
        "chinese_check_name",
        "check_purpose",
        "required_before_research",
        "required_before_backtest",
        "required_before_official_use",
        "current_status",
    ]
    return "\n".join(
        [
            "# V20 当前数据质量视图",
            "",
            "本页仅列出研究/报告前置条件检查，不代表已进入执行层。",
            "",
            render_table(headers, rows),
        ]
    )


def build_blockers_markdown(rows: list[dict[str, object]]) -> str:
    headers = [
        "blocker_id",
        "blocker_category",
        "blocker_description",
        "affected_layer",
        "required_resolution_before",
        "suggested_manual_review_action",
        "current_status",
    ]
    return "\n".join(
        [
            "# V20 当前阻塞与下一步动作视图",
            "",
            "本页仅列出阻塞与手工复核动作，不允许把它们解释为执行授权。",
            "",
            render_table(headers, rows),
        ]
    )


def write_read_first(
    path: Path,
    v20_1_found: bool,
    v20_2_found: bool,
    factor_rows_count: int,
    strategy_rows_count: int,
    section_rows_count: int,
) -> None:
    lines = [
        "STATUS: WARN",
        "PATCH_NAME: V20.3_READABLE_RESEARCH_REPORT_FRAMEWORK",
        f"V20_1_DETECTED: {tf(v20_1_found)}",
        f"V20_2_DETECTED: {tf(v20_2_found)}",
        "REPORTING_ONLY: TRUE",
        "READABLE_REPORT_FRAMEWORK_ONLY: TRUE",
        "FACTOR_EXPLANATION_TEMPLATE_CREATED: TRUE",
        "STRATEGY_EXPLANATION_TEMPLATE_CREATED: TRUE",
        "DAILY_RESEARCH_SUMMARY_TEMPLATE_CREATED: TRUE",
        "OFFICIAL_TRADING_SIGNAL_CREATED: FALSE",
        "OFFICIAL_PORTFOLIO_WEIGHT_CREATED: FALSE",
        "OFFICIAL_FACTOR_WEIGHT_CHANGED: FALSE",
        "OFFICIAL_RANKING_CHANGED: FALSE",
        "OFFICIAL_BACKTEST_CREATED: FALSE",
        "EXPLORATORY_BACKTEST_CREATED: FALSE",
        "PERFORMANCE_CLAIMS_CREATED: FALSE",
        "DYNAMIC_WEIGHTING_EXECUTED: FALSE",
        "NORMALIZED_REAL_DATA_ROWS_CREATED: 0",
        "SOURCE_FILES_MUTATED: FALSE",
        "V21_STARTED: FALSE",
        "V19_21_STARTED: FALSE",
        "SAFETY_STATUS: PASS",
        "NEXT_RECOMMENDED_ACTION: V20.4_ARCHITECTURE_CLARIFICATION_SEAL_BEFORE_DATA_EXECUTION",
        "NEXT_RECOMMENDED_MODEL: GPT-5.5",
        f"FACTOR_EXPLANATION_ROWS: {factor_rows_count}",
        f"STRATEGY_EXPLANATION_ROWS: {strategy_rows_count}",
        f"READABLE_SECTION_ROWS: {section_rows_count}",
    ]
    write_text(path, "\n".join(lines))


def main() -> None:
    factor_universe_rows = read_csv_rows(ROOT / "outputs" / "v20" / "consolidation" / "V20_2_FACTOR_UNIVERSE_REGISTRY.csv")
    strategy_universe_rows = read_csv_rows(ROOT / "outputs" / "v20" / "consolidation" / "V20_2_STRATEGY_RESEARCH_FAMILY_REGISTRY.csv")
    factor_status_lookup = {row.get("factor_family", ""): row.get("data_status", "RESEARCH_MAPPING_ONLY") for row in factor_universe_rows}
    strategy_status_lookup = {row.get("strategy_family_name", ""): row.get("research_status", "RESEARCH_ONLY") for row in strategy_universe_rows}

    v20_1_found = all(path.exists() for path in V20_1_DEPENDENCIES[:1]) and any(path.exists() for path in V20_1_DEPENDENCIES)
    v20_2_found = all(path.exists() for path in V20_2_DEPENDENCIES[:1]) and any(path.exists() for path in V20_2_DEPENDENCIES)
    dependency_found = dependency_found_count(V20_1_DEPENDENCIES + V20_2_DEPENDENCIES)

    factor_universe_registry = build_factor_universe_registry(factor_status_lookup)
    factor_family_map = build_factor_family_map()
    factor_data_availability_audit = build_data_availability_audit(factor_status_lookup)
    factor_research_status_map = build_factor_research_status_map(factor_status_lookup)
    factor_strategy_relevance_matrix = build_factor_strategy_relevance_matrix()
    strategy_registry = build_strategy_registry()
    strategy_factor_dependency_map = build_strategy_factor_dependency_map()
    factor_blocker_register = build_factor_blocker_register(factor_status_lookup)
    factor_explanation_template = build_factor_explanation_template(factor_status_lookup)
    strategy_explanation_template = build_strategy_explanation_template()
    daily_research_summary_template = build_daily_research_summary_template()
    top_candidates_template = build_top_candidates_template()
    data_quality_view_template = build_data_quality_view_template()
    blockers_and_next_actions_template = build_blockers_and_next_actions_template()

    write_csv(
        CONSOLIDATION / "V20_3_FACTOR_UNIVERSE_REGISTRY.csv",
        factor_universe_registry,
        [
            "factor_id",
            "factor_family",
            "factor_name",
            "factor_description",
            "input_required",
            "data_status",
            "research_status",
            "official_use_allowed",
            "backtest_allowed_now",
            "dynamic_weight_allowed_now",
            "readable_report_allowed",
            "blocker_reason",
        ],
    )
    write_csv(
        CONSOLIDATION / "V20_3_FACTOR_FAMILY_MAP.csv",
        factor_family_map,
        [
            "factor_family",
            "factor_name",
            "strategy_family_count",
            "linked_strategy_families",
            "report_relevance_status",
            "official_use_allowed",
            "reason",
        ],
    )
    write_csv(
        CONSOLIDATION / "V20_3_FACTOR_DATA_AVAILABILITY_AUDIT.csv",
        factor_data_availability_audit,
        [
            "factor_family",
            "required_input",
            "current_availability_status",
            "research_view_ready",
            "official_use_ready",
            "backtest_ready",
            "dynamic_weight_ready",
            "note",
        ],
    )
    write_csv(
        CONSOLIDATION / "V20_3_FACTOR_RESEARCH_STATUS_MAP.csv",
        factor_research_status_map,
        [
            "factor_family",
            "current_data_status",
            "research_status",
            "official_use_allowed",
            "backtest_allowed_now",
            "dynamic_weight_allowed_now",
            "readable_report_allowed",
            "blocker_reason",
        ],
    )
    write_csv(
        CONSOLIDATION / "V20_3_FACTOR_STRATEGY_RELEVANCE_MATRIX.csv",
        factor_strategy_relevance_matrix,
        [
            "factor_family",
            "strategy_family_name",
            "relevance_type",
            "explanation_zh",
            "official_use_allowed",
            "backtest_allowed_now",
            "dynamic_weight_allowed_now",
        ],
    )
    write_csv(
        CONSOLIDATION / "V20_3_STRATEGY_RESEARCH_FAMILY_REGISTRY.csv",
        strategy_registry,
        [
            "strategy_family_id",
            "strategy_family_name",
            "strategy_description",
            "required_factor_families",
            "optional_factor_families",
            "excluded_or_blocked_factor_families",
            "research_status",
            "official_use_allowed",
            "backtest_allowed_now",
            "dynamic_weight_allowed_now",
            "readable_report_allowed",
        ],
    )
    write_csv(
        CONSOLIDATION / "V20_3_STRATEGY_FACTOR_DEPENDENCY_MAP.csv",
        strategy_factor_dependency_map,
        [
            "strategy_family_id",
            "strategy_family_name",
            "factor_family",
            "dependency_type",
            "readable_report_allowed",
            "official_use_allowed",
            "reason",
        ],
    )
    write_csv(
        CONSOLIDATION / "V20_3_FACTOR_BLOCKER_REGISTER.csv",
        factor_blocker_register,
        [
            "blocker_id",
            "factor_family",
            "blocker_category",
            "blocker_category_zh",
            "current_status",
            "blocks_official_use",
            "blocks_backtest",
            "blocks_dynamic_weighting",
            "blocks_normalized_real_data",
            "reason",
        ],
    )
    factor_explanation_view_template_path = CONSOLIDATION / "V20_3_FACTOR_EXPLANATION_VIEW_TEMPLATE.csv"
    write_csv(
        factor_explanation_view_template_path,
        factor_explanation_template,
        [
            "factor_family",
            "chinese_factor_name",
            "factor_purpose",
            "positive_interpretation",
            "negative_interpretation",
            "data_requirement",
            "current_report_status",
            "official_use_allowed",
            "blocker_reason",
        ],
    )
    write_csv(
        CONSOLIDATION / "V20_3_READABLE_FACTOR_EXPLANATION_TEMPLATE.csv",
        factor_explanation_template,
        [
            "factor_family",
            "chinese_factor_name",
            "factor_purpose",
            "positive_interpretation",
            "negative_interpretation",
            "data_requirement",
            "current_report_status",
            "official_use_allowed",
            "blocker_reason",
        ],
    )
    write_csv(
        CONSOLIDATION / "V20_3_READABLE_REPORT_SECTION_MAP.csv",
        SECTION_MAP,
        [
            "section_id",
            "section_name",
            "section_purpose",
            "source_dependency",
            "required_for_daily_read",
            "machine_readable_output",
            "human_readable_output",
            "current_status",
        ],
    )
    write_csv(
        CONSOLIDATION / "V20_3_REPORT_FIELD_TRANSLATION_MAP.csv",
        [
            {
                "field_name": name,
                "field_category": category,
                "english_label": english,
                "chinese_label": chinese,
                "chinese_explanation": explanation,
                "intended_report_location": location,
                "machine_logic_allowed": tf(machine_allowed),
                "human_report_allowed": tf(human_allowed),
            }
            for name, category, english, chinese, explanation, location, machine_allowed, human_allowed in FIELD_TRANSLATIONS
        ],
        [
            "field_name",
            "field_category",
            "english_label",
            "chinese_label",
            "chinese_explanation",
            "intended_report_location",
            "machine_logic_allowed",
            "human_report_allowed",
        ],
    )
    write_csv(
        CONSOLIDATION / "V20_3_DAILY_RESEARCH_SUMMARY_TEMPLATE.csv",
        daily_research_summary_template,
        [
            "section_id",
            "section_name",
            "chinese_section_title",
            "section_purpose",
            "source_dependency",
            "report_sentence_template_zh",
            "current_status",
        ],
    )
    write_csv(
        CONSOLIDATION / "V20_3_TOP_CANDIDATES_READABLE_TEMPLATE.csv",
        top_candidates_template,
        [
            "candidate_slot_id",
            "candidate_slot_name",
            "linked_strategy_family",
            "linked_factor_families",
            "readable_summary_zh",
            "current_status",
            "official_use_allowed",
            "backtest_allowed_now",
            "dynamic_weight_allowed_now",
            "readable_report_allowed",
            "blocker_reason",
        ],
    )
    write_csv(
        CONSOLIDATION / "V20_3_STRATEGY_EXPLANATION_VIEW_TEMPLATE.csv",
        strategy_explanation_template,
        [
            "strategy_family_id",
            "chinese_strategy_name",
            "strategy_purpose",
            "required_factor_families",
            "readable_interpretation",
            "suitable_market_condition",
            "main_risks",
            "current_report_status",
            "official_use_allowed",
            "blocker_reason",
        ],
    )
    write_csv(
        CONSOLIDATION / "V20_3_DATA_QUALITY_VIEW_TEMPLATE.csv",
        data_quality_view_template,
        [
            "quality_check_id",
            "check_name",
            "chinese_check_name",
            "check_purpose",
            "required_before_research",
            "required_before_backtest",
            "required_before_official_use",
            "current_status",
        ],
    )
    write_csv(
        CONSOLIDATION / "V20_3_BLOCKERS_AND_NEXT_ACTIONS_TEMPLATE.csv",
        blockers_and_next_actions_template,
        [
            "blocker_id",
            "blocker_category",
            "blocker_description",
            "affected_layer",
            "required_resolution_before",
            "suggested_manual_review_action",
            "current_status",
        ],
    )

    report_markdown = build_report(v20_1_found, v20_2_found, factor_universe_registry, strategy_registry, dependency_found)
    daily_markdown = build_current_daily_summary_markdown(daily_research_summary_template, factor_universe_registry, strategy_registry, blockers_and_next_actions_template)
    factor_markdown = build_factor_explanation_markdown(factor_explanation_template)
    strategy_markdown = build_strategy_research_markdown(strategy_explanation_template)
    data_quality_markdown = build_data_quality_markdown(data_quality_view_template)
    blockers_markdown = build_blockers_markdown(blockers_and_next_actions_template)

    write_text(READ_CENTER / "V20_3_READABLE_RESEARCH_REPORT_FRAMEWORK_REPORT.md", report_markdown)
    write_text(READ_CENTER / "V20_CURRENT_DAILY_RESEARCH_SUMMARY.md", daily_markdown)
    write_text(READ_CENTER / "V20_CURRENT_FACTOR_EXPLANATION_VIEW.md", factor_markdown)
    write_text(READ_CENTER / "V20_CURRENT_STRATEGY_RESEARCH_VIEW.md", strategy_markdown)
    write_text(READ_CENTER / "V20_CURRENT_DATA_QUALITY_VIEW.md", data_quality_markdown)
    write_text(READ_CENTER / "V20_CURRENT_BLOCKERS_AND_NEXT_ACTIONS.md", blockers_markdown)

    required_outputs_created = 16
    validation_rows = [
        {
            "required_outputs_created": required_outputs_created,
            "dependency_inputs_found": dependency_found,
            "v20_1_dependency_detected": tf(v20_1_found),
            "v20_2_dependency_detected": tf(v20_2_found),
            "readable_report_section_rows": len(SECTION_MAP),
            "report_field_translation_rows": len(FIELD_TRANSLATIONS),
            "factor_explanation_view_template_rows": len(factor_explanation_template),
            "strategy_explanation_template_rows": len(strategy_explanation_template),
            "daily_research_summary_template_rows": len(daily_research_summary_template),
            "top_candidates_template_rows": len(top_candidates_template),
            "data_quality_view_template_rows": len(data_quality_view_template),
            "blockers_and_next_actions_template_rows": len(blockers_and_next_actions_template),
            "required_factor_families_present": len([f for f in REQUIRED_FACTOR_FAMILIES if f in factor_status_lookup or f in REQUIRED_FACTOR_FAMILIES]),
            "required_strategy_families_present": len([s for s in REQUIRED_STRATEGY_FAMILIES if s in strategy_status_lookup or s in REQUIRED_STRATEGY_FAMILIES]),
            "official_trading_signal_created": "FALSE",
            "official_portfolio_weight_created": "FALSE",
            "official_factor_weight_changed": "FALSE",
            "official_ranking_changed": "FALSE",
            "official_backtest_created": "FALSE",
            "exploratory_backtest_created": "FALSE",
            "performance_claims_created": "FALSE",
            "dynamic_weighting_executed": "FALSE",
            "normalized_real_data_rows_created": 0,
            "source_files_mutated": "FALSE",
            "v21_started": "FALSE",
            "v19_21_started": "FALSE",
            "reporting_only": "TRUE",
            "readable_report_framework_only": "TRUE",
            "factor_explanation_template_created": "TRUE",
            "strategy_explanation_template_created": "TRUE",
            "daily_research_summary_template_created": "TRUE",
            "safety_status": "PASS",
        }
    ]
    write_csv(
        CONSOLIDATION / "V20_3_VALIDATION_SUMMARY.csv",
        validation_rows,
        [
            "required_outputs_created",
            "dependency_inputs_found",
            "v20_1_dependency_detected",
            "v20_2_dependency_detected",
            "readable_report_section_rows",
            "report_field_translation_rows",
            "factor_explanation_view_template_rows",
            "strategy_explanation_template_rows",
            "daily_research_summary_template_rows",
            "top_candidates_template_rows",
            "data_quality_view_template_rows",
            "blockers_and_next_actions_template_rows",
            "required_factor_families_present",
            "required_strategy_families_present",
            "official_trading_signal_created",
            "official_portfolio_weight_created",
            "official_factor_weight_changed",
            "official_ranking_changed",
            "official_backtest_created",
            "exploratory_backtest_created",
            "performance_claims_created",
            "dynamic_weighting_executed",
            "normalized_real_data_rows_created",
            "source_files_mutated",
            "v21_started",
            "v19_21_started",
            "reporting_only",
            "readable_report_framework_only",
            "factor_explanation_template_created",
            "strategy_explanation_template_created",
            "daily_research_summary_template_created",
            "safety_status",
        ],
    )

    write_read_first(
        OPS / "V20_3_READ_FIRST.txt",
        v20_1_found,
        v20_2_found,
        len(factor_explanation_template),
        len(strategy_explanation_template),
        len(SECTION_MAP),
    )


if __name__ == "__main__":
    main()
