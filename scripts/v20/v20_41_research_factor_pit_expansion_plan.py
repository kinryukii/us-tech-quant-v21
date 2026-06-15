from __future__ import annotations

import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"

IN_V3_REGISTRY = CONSOLIDATION / "V20_3_FACTOR_UNIVERSE_REGISTRY.csv"
IN_V3_FAMILY = CONSOLIDATION / "V20_3_FACTOR_FAMILY_MAP.csv"
IN_V36_STRATEGY = CONSOLIDATION / "V20_36_ENTRY_STRATEGY_MASTER_MATRIX.csv"
IN_V38_COVERAGE = CONSOLIDATION / "V20_38_FACTOR_COVERAGE_AND_QUALITY_AUDIT.csv"
IN_V38_CLASS = CONSOLIDATION / "V20_38_EXPLORATORY_FACTOR_REVIEW_CLASSIFICATION.csv"
IN_V38_BLOCKED = CONSOLIDATION / "V20_38_BLOCKED_NON_PIT_FACTOR_ENFORCEMENT.csv"
IN_V38_NEXT = CONSOLIDATION / "V20_38_NEXT_STEP_DECISION_SUMMARY.csv"
IN_V39_ELIGIBLE = CONSOLIDATION / "V20_39_ELIGIBLE_SHADOW_FACTOR_UNIVERSE.csv"
IN_V39_EXCLUDED = CONSOLIDATION / "V20_39_EXCLUDED_SHADOW_FACTOR_REGISTER.csv"
IN_V39_REGIME = CONSOLIDATION / "V20_39_MARKET_REGIME_CONDITIONAL_WEIGHTING_PLACEHOLDER.csv"
IN_V39_NEXT = CONSOLIDATION / "V20_39_NEXT_STEP_DECISION_SUMMARY.csv"
IN_V39_R1_NEXT = CONSOLIDATION / "V20_39_R1_NEXT_STEP_DECISION_SUMMARY.csv"
IN_V39_R2_NEXT = CONSOLIDATION / "V20_39_R2_NEXT_STEP_DECISION_SUMMARY.csv"
IN_V40_NEXT = CONSOLIDATION / "V20_40_NEXT_STEP_DECISION_SUMMARY.csv"

OUT_DECISION = CONSOLIDATION / "V20_41_FACTOR_PIT_EXPANSION_DECISION.csv"
OUT_COVERAGE = CONSOLIDATION / "V20_41_FACTOR_COVERAGE_BY_CATEGORY.csv"
OUT_PIT_READY = CONSOLIDATION / "V20_41_PIT_READY_FACTOR_CANDIDATES.csv"
OUT_PRICE = CONSOLIDATION / "V20_41_PRICE_DERIVED_FACTOR_CANDIDATES.csv"
OUT_BACKFILL = CONSOLIDATION / "V20_41_BACKFILL_REQUIRED_FACTOR_BACKLOG.csv"
OUT_BLOCKED = CONSOLIDATION / "V20_41_NON_PIT_BLOCKED_FACTOR_REGISTER.csv"
OUT_DYNAMIC = CONSOLIDATION / "V20_41_DYNAMIC_WEIGHTING_EXPANSION_CANDIDATES.csv"
OUT_SOURCE = CONSOLIDATION / "V20_41_REQUIRED_SOURCE_BACKLOG.csv"
OUT_NEXT = CONSOLIDATION / "V20_41_NEXT_STEP_DECISION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_41_RESEARCH_FACTOR_PIT_EXPANSION_PLAN_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_RESEARCH_FACTOR_PIT_EXPANSION_PLAN.md"
READ_FIRST = OPS / "V20_41_READ_FIRST.txt"

STAGE_NAME = "V20.41_RESEARCH_FACTOR_PIT_EXPANSION_PLAN"
PASS_STATUS = "PASS_V20_41_RESEARCH_FACTOR_PIT_EXPANSION_PLAN"
BLOCKED_STATUS = "BLOCKED_V20_41_RESEARCH_FACTOR_PIT_EXPANSION_PLAN"
REQUIRED_CATEGORIES = [
    "fundamental",
    "technical",
    "strategy",
    "risk",
    "market_regime",
    "data_trustworthiness",
]

TECHNICAL_FACTORS = {
    "momentum_5d": "momentum",
    "momentum_10d": "momentum",
    "momentum_20d": "momentum",
    "relative_strength_vs_spy_20d": "relative_strength",
    "relative_strength_vs_qqq_20d": "relative_strength",
    "ma10_position": "moving_average_pullback",
    "ma20_position": "moving_average_pullback",
    "ma50_position": "technical_trend",
    "pullback_quality": "moving_average_pullback",
    "breakout_20d": "breakout",
    "volatility_20d": "volatility_risk",
    "volume_trend_20d": "volume_liquidity",
    "rsi_14": "technical_trend",
    "macd_12_26": "technical_trend",
    "bollinger_price_position_20d": "technical_trend",
}

FAMILY_CATEGORY = {
    "valuation": "fundamental",
    "growth": "fundamental",
    "profitability": "fundamental",
    "quality": "fundamental",
    "earnings_fundamental_change": "fundamental",
    "analyst_expectation_revision": "fundamental",
    "momentum": "technical",
    "relative_strength": "technical",
    "technical_trend": "technical",
    "moving_average_pullback": "technical",
    "breakout": "technical",
    "volume_liquidity": "technical",
    "volatility_risk": "risk",
    "drawdown_risk": "risk",
    "event_risk": "risk",
    "options_risk": "risk",
    "market_regime": "market_regime",
    "industry_theme": "market_regime",
    "ai_semiconductor_theme": "market_regime",
}


def clean(v: object) -> str:
    return str(v or "").strip()


def upper(v: object) -> str:
    return clean(v).upper()


def tf(v: bool) -> str:
    return "TRUE" if v else "FALSE"


def as_int(v: object) -> int:
    try:
        return int(float(clean(v)))
    except ValueError:
        return 0


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as h:
        reader = csv.DictReader(h)
        return [dict(r) for r in reader], list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as h:
        writer = csv.DictWriter(h, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({f: row.get(f, "") for f in fields})


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def source_status(path: Path, rows: list[dict[str, str]]) -> dict[str, object]:
    return {
        "source_file": rel(path),
        "source_exists": tf(path.exists()),
        "source_row_count": len(rows),
    }


def category_for_family(family: str, factor_name: str = "") -> str:
    if family in FAMILY_CATEGORY:
        return FAMILY_CATEGORY[family]
    if factor_name in TECHNICAL_FACTORS:
        fam = TECHNICAL_FACTORS[factor_name]
        return "risk" if fam == "volatility_risk" else "technical"
    return "data_trustworthiness"


def add_record(records: dict[str, dict[str, object]], key: str, updates: dict[str, object]) -> None:
    base = records.setdefault(key, {
        "factor_key": key,
        "factor_name": key,
        "factor_family": "",
        "factor_category": "",
        "source_stage": "",
        "source_input_required": "",
        "prior_evidence": "",
        "pit_backtest_eligible_now": "FALSE",
        "price_cache_computable": "FALSE",
        "historical_source_backfill_required": "FALSE",
        "blocked_non_pit_current_only": "FALSE",
        "future_dynamic_weighting_candidate": "FALSE",
        "official_recommendation_allowed": "FALSE",
        "official_factor_weight_mutation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "recommended_next_action": "",
        "decision_reason": "",
    })
    for k, v in updates.items():
        if clean(v) or not clean(base.get(k)):
            base[k] = v


def price_computable(input_required: str, family: str, category: str, factor_name: str) -> bool:
    tokens = input_required.lower()
    return (
        factor_name in TECHNICAL_FACTORS
        or category in {"technical", "strategy"}
        or "price_history" in tokens
        or "return_window" in tokens
        or "moving_average" in tokens
        or "volume_history" in tokens
        or "benchmark_series" in tokens
        or family in {"drawdown_risk", "volatility_risk", "market_regime"}
    )


def backfill_required(input_required: str, family: str, category: str, pit_ready: bool, price_ready: bool) -> bool:
    tokens = input_required.lower()
    source_terms = [
        "fundamental",
        "earnings",
        "analyst",
        "event",
        "options",
        "theme",
        "industry",
        "regime_label",
        "implied_volatility",
    ]
    if pit_ready:
        return False
    if category == "strategy":
        return False
    if any(t in tokens for t in source_terms):
        return True
    if category in {"fundamental", "market_regime", "risk", "data_trustworthiness"} and not price_ready:
        return True
    return False


def main() -> int:
    source_rows: list[dict[str, object]] = []
    v3_registry, _ = read_csv(IN_V3_REGISTRY)
    v3_family, _ = read_csv(IN_V3_FAMILY)
    v36_strategy, _ = read_csv(IN_V36_STRATEGY)
    v38_coverage, _ = read_csv(IN_V38_COVERAGE)
    v38_class, _ = read_csv(IN_V38_CLASS)
    v38_blocked, _ = read_csv(IN_V38_BLOCKED)
    v38_next, _ = read_csv(IN_V38_NEXT)
    v39_eligible, _ = read_csv(IN_V39_ELIGIBLE)
    v39_excluded, _ = read_csv(IN_V39_EXCLUDED)
    v39_regime, _ = read_csv(IN_V39_REGIME)
    v39_next, _ = read_csv(IN_V39_NEXT)
    v39_r1_next, _ = read_csv(IN_V39_R1_NEXT)
    v39_r2_next, _ = read_csv(IN_V39_R2_NEXT)
    v40_next, _ = read_csv(IN_V40_NEXT)
    for path, rows in [
        (IN_V3_REGISTRY, v3_registry),
        (IN_V3_FAMILY, v3_family),
        (IN_V36_STRATEGY, v36_strategy),
        (IN_V38_COVERAGE, v38_coverage),
        (IN_V38_CLASS, v38_class),
        (IN_V38_BLOCKED, v38_blocked),
        (IN_V38_NEXT, v38_next),
        (IN_V39_ELIGIBLE, v39_eligible),
        (IN_V39_EXCLUDED, v39_excluded),
        (IN_V39_REGIME, v39_regime),
        (IN_V39_NEXT, v39_next),
        (IN_V39_R1_NEXT, v39_r1_next),
        (IN_V39_R2_NEXT, v39_r2_next),
        (IN_V40_NEXT, v40_next),
    ]:
        source_rows.append(source_status(path, rows))

    v40 = v40_next[0] if v40_next else {}
    gate_ready = (
        upper(v40.get("STATUS")) == "PASS_V20_40_PORTFOLIO_LEVEL_EXPLORATORY_BACKTEST"
        and upper(v40.get("READY_FOR_RESEARCH_FACTOR_PIT_EXPANSION")) == "TRUE"
        and upper(v40.get("OFFICIAL_FACTOR_WEIGHTS_MUTATED")) == "FALSE"
        and upper(v40.get("OFFICIAL_DYNAMIC_WEIGHTING_STARTED")) == "FALSE"
        and upper(v40.get("READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION")) == "FALSE"
    )

    eligible_names = {
        clean(r.get("factor_name"))
        for r in v39_eligible
        if upper(r.get("eligible_for_shadow_weighting")) == "TRUE"
    }
    v38_names = {clean(r.get("factor_name")) for r in v38_coverage if clean(r.get("factor_name"))}
    blocked_names = {
        clean(r.get("blocked_dependency") or r.get("factor_name"))
        for r in [*v38_blocked, *v39_excluded]
        if clean(r.get("blocked_dependency") or r.get("factor_name"))
    }

    class_by_factor = {clean(r.get("factor_name")): r for r in v38_class}
    coverage_by_factor = {clean(r.get("factor_name")): r for r in v38_coverage}
    records: dict[str, dict[str, object]] = {}

    for row in v3_registry:
        family = clean(row.get("factor_family"))
        factor_id = clean(row.get("factor_id"))
        factor_name = clean(row.get("factor_name")) or family or factor_id
        key = family or factor_id or factor_name
        category = category_for_family(family, factor_name)
        inputs = clean(row.get("input_required"))
        price_ready = price_computable(inputs, family, category, factor_name)
        pit_ready = key in eligible_names or factor_name in eligible_names
        need_backfill = backfill_required(inputs, family, category, pit_ready, price_ready)
        add_record(records, key, {
            "factor_name": factor_name,
            "factor_family": family,
            "factor_category": category,
            "source_stage": "V20_3_FACTOR_UNIVERSE_REGISTRY",
            "source_input_required": inputs,
            "prior_evidence": clean(row.get("data_status")),
            "pit_backtest_eligible_now": tf(pit_ready),
            "price_cache_computable": tf(price_ready),
            "historical_source_backfill_required": tf(need_backfill),
            "blocked_non_pit_current_only": tf(key in blocked_names or upper(row.get("backtest_allowed_now")) != "TRUE"),
            "future_dynamic_weighting_candidate": tf(pit_ready or (price_ready and category in {"technical", "risk", "market_regime"})),
            "recommended_next_action": "attach_pit_historical_source_contract" if need_backfill else ("promote_to_research_pit_candidate_register" if pit_ready or price_ready else "keep_blocked_pending_source_definition"),
            "decision_reason": "V20.3 family registry mapped into V20.41 research-only PIT expansion taxonomy.",
        })

    for factor_name in sorted(v38_names | set(TECHNICAL_FACTORS)):
        family = TECHNICAL_FACTORS.get(factor_name, "technical")
        category = "risk" if family == "volatility_risk" else "technical"
        cov = coverage_by_factor.get(factor_name, {})
        cls = class_by_factor.get(factor_name, {})
        pit_ready = factor_name in eligible_names or upper(cov.get("eligible_for_effectiveness_scoring")) == "TRUE"
        add_record(records, factor_name, {
            "factor_name": factor_name,
            "factor_family": family,
            "factor_category": category,
            "source_stage": "V20_38/V20_39_TECHNICAL_FACTOR_EVIDENCE",
            "source_input_required": "historical_price_cache;asof_factor_recompute",
            "prior_evidence": clean(cls.get("exploratory_factor_review_class")) or "V20_38_TECHNICAL_EVIDENCE",
            "pit_backtest_eligible_now": tf(pit_ready),
            "price_cache_computable": "TRUE",
            "historical_source_backfill_required": "FALSE",
            "blocked_non_pit_current_only": "FALSE",
            "future_dynamic_weighting_candidate": tf(factor_name in eligible_names),
            "recommended_next_action": "retain_in_research_pit_ready_candidate_pool" if pit_ready else "recheck_sample_coverage_before_candidate_use",
            "decision_reason": "Technical factor already recomputed from historical cache in prior V20 research stages.",
        })

    for row in v36_strategy:
        strategy_id = clean(row.get("strategy_id"))
        if not strategy_id:
            continue
        eligible = upper(row.get("eligible_for_v20_37_execution")) == "TRUE"
        add_record(records, f"strategy::{strategy_id}", {
            "factor_name": strategy_id,
            "factor_family": clean(row.get("strategy_family")),
            "factor_category": "strategy",
            "source_stage": "V20_36_ENTRY_STRATEGY_MASTER_MATRIX",
            "source_input_required": "|".join([
                clean(row.get("required_price_fields")),
                clean(row.get("required_volume_fields")),
                clean(row.get("required_factor_fields")),
            ]).strip("|"),
            "prior_evidence": "V20_37/V20_39_R2 entry strategy exploratory backtest lineage",
            "pit_backtest_eligible_now": tf(eligible),
            "price_cache_computable": "TRUE",
            "historical_source_backfill_required": "FALSE",
            "blocked_non_pit_current_only": tf(not eligible),
            "future_dynamic_weighting_candidate": "TRUE",
            "recommended_next_action": "eligible_for_future_research_entry_policy_weighting_design" if eligible else "keep_strategy_blocked_until_pit_dependency_resolved",
            "decision_reason": "Entry strategy is classified as a research strategy factor family, not an official trading signal.",
        })

    for row in v39_regime:
        component = clean(row.get("regime_component"))
        if not component:
            continue
        status = clean(row.get("status"))
        blocked = "BLOCKED" in upper(status)
        add_record(records, f"market_regime::{component}", {
            "factor_name": component,
            "factor_family": "market_regime",
            "factor_category": "market_regime",
            "source_stage": "V20_39_MARKET_REGIME_PLACEHOLDER",
            "source_input_required": clean(row.get("required_source")),
            "prior_evidence": status,
            "pit_backtest_eligible_now": "FALSE",
            "price_cache_computable": tf(not blocked),
            "historical_source_backfill_required": tf(blocked),
            "blocked_non_pit_current_only": tf(blocked),
            "future_dynamic_weighting_candidate": tf(not blocked),
            "recommended_next_action": "define_pit_regime_source_contract_before_weighting_use",
            "decision_reason": clean(row.get("notes")) or "Market-regime component remains design-only.",
        })

    for key, source, reason in [
        ("data_trustworthiness::source_hash_lineage", "source_hash;run_id;file_hash", "Track source lineage before any expanded research backtest."),
        ("data_trustworthiness::stale_leakage_gate", "asof_date;source_date;pit_gate_result", "Keep PIT gates as required inputs for expanded factor families."),
        ("data_trustworthiness::formula_recheck", "formula_recheck_register", "Formula checks remain evidence factors for research-readiness decisions."),
        ("data_trustworthiness::historical_cache_coverage", "historical_price_cache_coverage", "Cache coverage is a gating factor, not a return computation."),
    ]:
        add_record(records, key, {
            "factor_name": key.split("::", 1)[1],
            "factor_family": "data_trustworthiness",
            "factor_category": "data_trustworthiness",
            "source_stage": "V20_41_RESEARCH_PLANNING",
            "source_input_required": source,
            "prior_evidence": "derived_from_prior_gate_outputs",
            "pit_backtest_eligible_now": "TRUE",
            "price_cache_computable": "FALSE",
            "historical_source_backfill_required": "FALSE",
            "blocked_non_pit_current_only": "FALSE",
            "future_dynamic_weighting_candidate": "FALSE",
            "recommended_next_action": "retain_as_required_gate_for_future_factor_expansion",
            "decision_reason": reason,
        })

    for blocked in sorted(blocked_names):
        category = "fundamental" if "fundamental" in blocked or "valuation" in blocked or "analyst" in blocked else "data_trustworthiness"
        add_record(records, f"blocked::{blocked}", {
            "factor_name": blocked,
            "factor_family": "blocked_non_pit_dependency",
            "factor_category": category,
            "source_stage": "V20_38/V20_39_BLOCKED_REGISTER",
            "source_input_required": "non_pit_or_current_only_dependency",
            "prior_evidence": "blocked_in_prior_v20_outputs",
            "pit_backtest_eligible_now": "FALSE",
            "price_cache_computable": "FALSE",
            "historical_source_backfill_required": "TRUE",
            "blocked_non_pit_current_only": "TRUE",
            "future_dynamic_weighting_candidate": "FALSE",
            "recommended_next_action": "do_not_use_until_pit_historical_source_exists",
            "decision_reason": "Prior V20 stage explicitly blocked this dependency from PIT historical research.",
        })

    decision_rows = sorted(records.values(), key=lambda r: (clean(r.get("factor_category")), clean(r.get("factor_key"))))
    for row in decision_rows:
        row["official_recommendation_allowed"] = "FALSE"
        row["official_factor_weight_mutation_allowed"] = "FALSE"
        row["official_ranking_mutation_allowed"] = "FALSE"

    category_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in decision_rows:
        cat = clean(row.get("factor_category")) or "data_trustworthiness"
        category_counts[cat]["factor_count"] += 1
        for field in [
            "pit_backtest_eligible_now",
            "price_cache_computable",
            "historical_source_backfill_required",
            "blocked_non_pit_current_only",
            "future_dynamic_weighting_candidate",
        ]:
            if upper(row.get(field)) == "TRUE":
                category_counts[cat][field] += 1
    coverage_rows = []
    for cat in REQUIRED_CATEGORIES:
        c = category_counts[cat]
        coverage_rows.append({
            "factor_category": cat,
            "factor_count": c["factor_count"],
            "pit_backtest_eligible_now_count": c["pit_backtest_eligible_now"],
            "price_cache_computable_count": c["price_cache_computable"],
            "historical_source_backfill_required_count": c["historical_source_backfill_required"],
            "blocked_non_pit_current_only_count": c["blocked_non_pit_current_only"],
            "future_dynamic_weighting_candidate_count": c["future_dynamic_weighting_candidate"],
            "official_recommendation_allowed_count": 0,
            "coverage_status": "COVERED" if c["factor_count"] else "MISSING",
        })

    pit_ready = [r for r in decision_rows if upper(r.get("pit_backtest_eligible_now")) == "TRUE"]
    price_rows = [r for r in decision_rows if upper(r.get("price_cache_computable")) == "TRUE"]
    backfill_rows = [r for r in decision_rows if upper(r.get("historical_source_backfill_required")) == "TRUE"]
    blocked_rows = [r for r in decision_rows if upper(r.get("blocked_non_pit_current_only")) == "TRUE"]
    dynamic_rows = [r for r in decision_rows if upper(r.get("future_dynamic_weighting_candidate")) == "TRUE"]

    source_backlog_rows = []
    for row in backfill_rows:
        source_backlog_rows.append({
            "factor_key": row.get("factor_key"),
            "factor_category": row.get("factor_category"),
            "required_source": row.get("source_input_required"),
            "source_need_type": "historical_pit_backfill_contract",
            "fetch_or_refresh_now": "FALSE",
            "allowed_current_stage_action": "planning_only",
            "official_use_allowed": "FALSE",
            "reason": row.get("decision_reason"),
        })

    leakage_blockers = 0
    formula_mismatches = 0
    for next_row in [*(v38_next[:1]), *(v39_next[:1]), *(v39_r1_next[:1]), *(v39_r2_next[:1]), *(v40_next[:1])]:
        leakage_blockers += as_int(next_row.get("LEAKAGE_BLOCKER_COUNT"))
        formula_mismatches += as_int(next_row.get("FORMULA_MISMATCH_COUNT"))

    status = PASS_STATUS if gate_ready and all(c["coverage_status"] == "COVERED" for c in coverage_rows) else BLOCKED_STATUS
    next_rows = [{
        "STAGE_NAME": STAGE_NAME,
        "STATUS": status,
        "V20_40_READY_FOR_RESEARCH_FACTOR_PIT_EXPANSION": clean(v40.get("READY_FOR_RESEARCH_FACTOR_PIT_EXPANSION")),
        "CATEGORY_COUNT": len(REQUIRED_CATEGORIES),
        "FACTOR_DECISION_ROWS": len(decision_rows),
        "PIT_READY_FACTOR_CANDIDATE_ROWS": len(pit_ready),
        "PRICE_DERIVED_FACTOR_CANDIDATE_ROWS": len(price_rows),
        "BACKFILL_REQUIRED_FACTOR_ROWS": len(backfill_rows),
        "NON_PIT_BLOCKED_FACTOR_ROWS": len(blocked_rows),
        "DYNAMIC_WEIGHTING_EXPANSION_CANDIDATE_ROWS": len(dynamic_rows),
        "REQUIRED_SOURCE_BACKLOG_ROWS": len(source_backlog_rows),
        "LEAKAGE_BLOCKER_COUNT": leakage_blockers,
        "FORMULA_MISMATCH_COUNT": formula_mismatches,
        "RESEARCH_ONLY": "TRUE",
        "OFFICIAL_RECOMMENDATION_CREATED": "FALSE",
        "TRADING_SIGNAL_CREATED": "FALSE",
        "BROKER_ORDER_PATH_CREATED": "FALSE",
        "OFFICIAL_RANKING_MUTATED": "FALSE",
        "OFFICIAL_FACTOR_WEIGHTS_MUTATED": "FALSE",
        "DYNAMIC_WEIGHTING_EXECUTED": "FALSE",
        "PORTFOLIO_BACKTEST_RERUN": "FALSE",
        "NEW_RETURN_COMPUTATION_CREATED": "FALSE",
        "PROVIDER_REFRESH_EXECUTED": "FALSE",
        "V21_OUTPUTS_CREATED": "FALSE",
        "V19_21_OUTPUTS_CREATED": "FALSE",
        "READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION": "FALSE",
        "READY_FOR_FUTURE_PIT_SOURCE_BACKFILL_PLANNING": "TRUE",
    }]

    decision_fields = [
        "factor_key",
        "factor_name",
        "factor_family",
        "factor_category",
        "source_stage",
        "source_input_required",
        "prior_evidence",
        "pit_backtest_eligible_now",
        "price_cache_computable",
        "historical_source_backfill_required",
        "blocked_non_pit_current_only",
        "future_dynamic_weighting_candidate",
        "official_recommendation_allowed",
        "official_factor_weight_mutation_allowed",
        "official_ranking_mutation_allowed",
        "recommended_next_action",
        "decision_reason",
    ]
    write_csv(OUT_DECISION, decision_rows, decision_fields)
    write_csv(OUT_COVERAGE, coverage_rows, [
        "factor_category",
        "factor_count",
        "pit_backtest_eligible_now_count",
        "price_cache_computable_count",
        "historical_source_backfill_required_count",
        "blocked_non_pit_current_only_count",
        "future_dynamic_weighting_candidate_count",
        "official_recommendation_allowed_count",
        "coverage_status",
    ])
    write_csv(OUT_PIT_READY, pit_ready, decision_fields)
    write_csv(OUT_PRICE, price_rows, decision_fields)
    write_csv(OUT_BACKFILL, backfill_rows, decision_fields)
    write_csv(OUT_BLOCKED, blocked_rows, decision_fields)
    write_csv(OUT_DYNAMIC, dynamic_rows, decision_fields)
    write_csv(OUT_SOURCE, source_backlog_rows, [
        "factor_key",
        "factor_category",
        "required_source",
        "source_need_type",
        "fetch_or_refresh_now",
        "allowed_current_stage_action",
        "official_use_allowed",
        "reason",
    ])
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    report = f"""# V20.41 Research Factor PIT Expansion Plan

Generated: {now}

Status: {status}

## Scope

This stage is research-only. It reads prior V20 registry and evidence outputs, classifies the factor expansion roadmap, and writes V20.41 planning registers only. It does not create official recommendations, trading signals, official rankings, official factor weights, dynamic weighting execution, portfolio backtests, or new return computations.

## Inputs Reviewed

| Source | Exists | Rows |
| --- | ---: | ---: |
"""
    for row in source_rows:
        report += f"| {row['source_file']} | {row['source_exists']} | {row['source_row_count']} |\n"
    report += f"""
## Category Coverage

| Category | Factors | PIT-ready | Price/cache computable | Backfill required | Non-PIT blocked | Dynamic candidates |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
"""
    for row in coverage_rows:
        report += (
            f"| {row['factor_category']} | {row['factor_count']} | "
            f"{row['pit_backtest_eligible_now_count']} | {row['price_cache_computable_count']} | "
            f"{row['historical_source_backfill_required_count']} | {row['blocked_non_pit_current_only_count']} | "
            f"{row['future_dynamic_weighting_candidate_count']} |\n"
        )
    report += f"""
## Decision Summary

- PIT/backtest eligible factor candidates: {len(pit_ready)}
- Technically computable from historical price/cache data: {len(price_rows)}
- Historical source backfill required: {len(backfill_rows)}
- Blocked due to non-PIT/current-only dependency: {len(blocked_rows)}
- Future dynamic-weighting expansion candidates: {len(dynamic_rows)}
- Official recommendation allowed now: 0

## Safety Flags

- RESEARCH_ONLY=TRUE
- OFFICIAL_RECOMMENDATION_CREATED=FALSE
- TRADING_SIGNAL_CREATED=FALSE
- BROKER_ORDER_PATH_CREATED=FALSE
- OFFICIAL_RANKING_MUTATED=FALSE
- OFFICIAL_FACTOR_WEIGHTS_MUTATED=FALSE
- DYNAMIC_WEIGHTING_EXECUTED=FALSE
- PORTFOLIO_BACKTEST_RERUN=FALSE
- NEW_RETURN_COMPUTATION_CREATED=FALSE
- PROVIDER_REFRESH_EXECUTED=FALSE
- V21_OUTPUTS_CREATED=FALSE
- V19_21_OUTPUTS_CREATED=FALSE
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)

    read_first = "\n".join([
        f"STAGE_NAME={STAGE_NAME}",
        f"STATUS={status}",
        "READ_FIRST_PURPOSE=Research-only PIT factor expansion planning after V20.40.",
        "RESEARCH_ONLY=TRUE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "TRADING_SIGNAL_CREATED=FALSE",
        "BROKER_ORDER_PATH_CREATED=FALSE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "OFFICIAL_FACTOR_WEIGHTS_MUTATED=FALSE",
        "DYNAMIC_WEIGHTING_EXECUTED=FALSE",
        "PORTFOLIO_BACKTEST_RERUN=FALSE",
        "NEW_RETURN_COMPUTATION_CREATED=FALSE",
        "PROVIDER_REFRESH_EXECUTED=FALSE",
        "HISTORICAL_SOURCE_BACKFILL_EXECUTED=FALSE",
        "PRIOR_ACCEPTED_OUTPUTS_MUTATED=FALSE",
        "V21_OUTPUTS_CREATED=FALSE",
        "V19_21_OUTPUTS_CREATED=FALSE",
        "READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION=FALSE",
        f"FACTOR_DECISION_ROWS={len(decision_rows)}",
        f"PIT_READY_FACTOR_CANDIDATE_ROWS={len(pit_ready)}",
        f"PRICE_DERIVED_FACTOR_CANDIDATE_ROWS={len(price_rows)}",
        f"BACKFILL_REQUIRED_FACTOR_ROWS={len(backfill_rows)}",
        f"NON_PIT_BLOCKED_FACTOR_ROWS={len(blocked_rows)}",
        f"DYNAMIC_WEIGHTING_EXPANSION_CANDIDATE_ROWS={len(dynamic_rows)}",
        f"REQUIRED_SOURCE_BACKLOG_ROWS={len(source_backlog_rows)}",
        "",
    ])
    write_text(READ_FIRST, read_first)

    print(status)
    print(f"FACTOR_DECISION_ROWS={len(decision_rows)}")
    print(f"READ_FIRST={rel(READ_FIRST)}")
    return 0 if status == PASS_STATUS else 1


if __name__ == "__main__":
    raise SystemExit(main())
