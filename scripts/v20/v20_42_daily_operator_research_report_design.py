from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"

IN_V35_R2_TOP20 = CONSOLIDATION / "V20_35_R2_ASOF_TOP20_SELECTIONS.csv"
IN_V35_R2_NEXT = CONSOLIDATION / "V20_35_R2_NEXT_STEP_DECISION_SUMMARY.csv"
IN_V36_MASTER = CONSOLIDATION / "V20_36_ENTRY_STRATEGY_MASTER_MATRIX.csv"
IN_V36_NEXT = CONSOLIDATION / "V20_36_NEXT_STEP_DECISION_SUMMARY.csv"
IN_V37_FAMILY = CONSOLIDATION / "V20_37_ENTRY_STRATEGY_FAMILY_SUMMARY.csv"
IN_V37_NEXT = CONSOLIDATION / "V20_37_NEXT_STEP_DECISION_SUMMARY.csv"
IN_V38_COVERAGE = CONSOLIDATION / "V20_38_FACTOR_COVERAGE_AND_QUALITY_AUDIT.csv"
IN_V38_EFFECT = CONSOLIDATION / "V20_38_FACTOR_EFFECTIVENESS_METRICS.csv"
IN_V38_NEXT = CONSOLIDATION / "V20_38_NEXT_STEP_DECISION_SUMMARY.csv"
IN_V39_ELIGIBLE = CONSOLIDATION / "V20_39_ELIGIBLE_SHADOW_FACTOR_UNIVERSE.csv"
IN_V39_WEIGHT_SETS = CONSOLIDATION / "V20_39_SHADOW_WEIGHT_CANDIDATE_SETS.csv"
IN_V39_NEXT = CONSOLIDATION / "V20_39_NEXT_STEP_DECISION_SUMMARY.csv"
IN_V39_R1_SUMMARY = CONSOLIDATION / "V20_39_R1_SHADOW_CANDIDATE_WEIGHT_SET_COMPARISON.csv"
IN_V39_R1_NEXT = CONSOLIDATION / "V20_39_R1_NEXT_STEP_DECISION_SUMMARY.csv"
IN_V39_R2_FAMILY = CONSOLIDATION / "V20_39_R2_SHADOW_ENTRY_STRATEGY_FAMILY_SUMMARY.csv"
IN_V39_R2_NEXT = CONSOLIDATION / "V20_39_R2_NEXT_STEP_DECISION_SUMMARY.csv"
IN_V40_POLICY_SUM = CONSOLIDATION / "V20_40_PORTFOLIO_POLICY_SUMMARY.csv"
IN_V40_RISK = CONSOLIDATION / "V20_40_PORTFOLIO_RISK_AND_CONCENTRATION_AUDIT.csv"
IN_V40_NEXT = CONSOLIDATION / "V20_40_NEXT_STEP_DECISION_SUMMARY.csv"
IN_V41_DECISION = CONSOLIDATION / "V20_41_FACTOR_PIT_EXPANSION_DECISION.csv"
IN_V41_COVERAGE = CONSOLIDATION / "V20_41_FACTOR_COVERAGE_BY_CATEGORY.csv"
IN_V41_SOURCE = CONSOLIDATION / "V20_41_REQUIRED_SOURCE_BACKLOG.csv"
IN_V41_NEXT = CONSOLIDATION / "V20_41_NEXT_STEP_DECISION_SUMMARY.csv"

OUT_SECTION = CONSOLIDATION / "V20_42_DAILY_OPERATOR_REPORT_SECTION_MAP.csv"
OUT_FIELD = CONSOLIDATION / "V20_42_DAILY_OPERATOR_REPORT_FIELD_CONTRACT.csv"
OUT_DEP = CONSOLIDATION / "V20_42_DAILY_OPERATOR_REPORT_INPUT_DEPENDENCY_MAP.csv"
OUT_CANDIDATE = CONSOLIDATION / "V20_42_DAILY_OPERATOR_REPORT_CANDIDATE_TABLE_SCHEMA.csv"
OUT_FACTOR = CONSOLIDATION / "V20_42_DAILY_OPERATOR_REPORT_FACTOR_SUMMARY_SCHEMA.csv"
OUT_STRATEGY = CONSOLIDATION / "V20_42_DAILY_OPERATOR_REPORT_STRATEGY_SUMMARY_SCHEMA.csv"
OUT_RISK = CONSOLIDATION / "V20_42_DAILY_OPERATOR_REPORT_RISK_BLOCKER_SCHEMA.csv"
OUT_NEXT = CONSOLIDATION / "V20_42_DAILY_OPERATOR_REPORT_NEXT_STEP_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_42_VALIDATION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_42_DAILY_OPERATOR_RESEARCH_REPORT_DESIGN_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_DAILY_OPERATOR_RESEARCH_REPORT_DESIGN.md"
READ_FIRST = OPS / "V20_42_READ_FIRST.txt"

STAGE_NAME = "V20.42_DAILY_OPERATOR_RESEARCH_REPORT_DESIGN"
PASS_STATUS = "PASS_V20_42_DAILY_OPERATOR_RESEARCH_REPORT_DESIGN"
BLOCKED_STATUS = "BLOCKED_V20_42_DAILY_OPERATOR_RESEARCH_REPORT_DESIGN"


def clean(value: object) -> str:
    return str(value or "").strip()


def upper(value: object) -> str:
    return clean(value).upper()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def as_int(value: object) -> int:
    try:
        return int(float(clean(value)))
    except ValueError:
        return 0


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def source_row(stage: str, path: Path, rows: list[dict[str, str]], required: bool = True) -> dict[str, object]:
    return {
        "source_stage": stage,
        "input_file": rel(path),
        "source_exists": tf(path.exists()),
        "row_count": len(rows),
        "required_for_report_design": tf(required),
        "used_for_return_computation": "FALSE",
        "provider_refresh_required": "FALSE",
        "dependency_status": "AVAILABLE" if path.exists() else ("MISSING_REQUIRED" if required else "MISSING_OPTIONAL"),
    }


def count_true(rows: list[dict[str, str]], field: str) -> int:
    return sum(1 for row in rows if upper(row.get(field)) == "TRUE")


def section_rows(metrics: dict[str, object]) -> list[dict[str, object]]:
    sections = [
        ("RUN_IDENTITY", "Run identity and report date", "run_metadata", "Shows report date, source stage, and design-only status."),
        ("RESEARCH_BOUNDARY", "Research-only boundary", "safety_flags", "States non-official scope before any evidence table."),
        ("MARKET_REGIME_PLACEHOLDER", "Market regime placeholder", "placeholder", "Reserved for future PIT-certified regime context."),
        ("BENCHMARK_CONTEXT_PLACEHOLDER", "Benchmark context placeholder for SPY/QQQ", "placeholder", "Reserved for SPY and QQQ context from accepted cache lineage."),
        ("CANDIDATE_UNIVERSE_SUMMARY", "Candidate universe summary", "summary", f"Summarizes candidate lineage including V20.35-R2 Top20 rows: {metrics['v35_r2_top20_rows']}."),
        ("TOP_CANDIDATE_RESEARCH_TABLE_DESIGN", "Top candidate research table design", "table_schema", "Defines readable candidate columns without creating a current recommendation."),
        ("FACTOR_SUPPORT_SUMMARY", "Factor support summary", "summary_schema", f"Uses V20.38/V20.41 factor evidence; PIT-ready candidates: {metrics['v41_pit_ready_count']}."),
        ("ENTRY_STRATEGY_EVIDENCE_SUMMARY", "Entry strategy evidence summary", "summary_schema", f"Uses V20.36/V20.37/V20.39-R2 strategy evidence rows: {metrics['v36_strategy_rows']}."),
        ("SHADOW_DYNAMIC_WEIGHTING_EVIDENCE_SUMMARY", "Shadow dynamic weighting evidence summary", "summary_schema", f"Uses V20.39 design evidence; candidate weight sets: {metrics['v39_weight_set_rows']}."),
        ("PORTFOLIO_EXPLORATORY_BACKTEST_EVIDENCE_SUMMARY", "Portfolio exploratory backtest evidence summary", "summary_schema", f"Uses V20.40 portfolio evidence; policy rows: {metrics['v40_policy_rows']}."),
        ("PIT_FACTOR_EXPANSION_STATUS", "PIT factor expansion status", "summary_schema", f"Uses V20.41 factor decision rows: {metrics['v41_decision_rows']}."),
        ("RISK_AND_BLOCKER_SUMMARY", "Risk and blocker summary", "risk_schema", f"Combines V20.40 risk rows and V20.41 backfill/source backlog rows: {metrics['v41_source_backlog_rows']}."),
        ("DATA_FRESHNESS_LINEAGE_LEAKAGE_STATUS", "Data freshness / lineage / leakage status", "gate_summary", "Surfaces source availability, PIT gate status, and formula mismatch counts."),
        ("HUMAN_READABLE_NEXT_STEP_DECISION", "Human-readable next-step decision", "decision_text", "Provides an operator-readable next-step classification without official output."),
        ("OFFICIAL_OUTPUT_PROHIBITION", "Explicit prohibition against official trading or recommendation output", "safety_flags", "Repeats that no official recommendation, signal, order, ranking, or weight mutation is created."),
    ]
    return [
        {
            "section_order": idx,
            "section_id": section_id,
            "section_title": title,
            "section_type": section_type,
            "design_status": "DESIGN_ONLY",
            "research_only": "TRUE",
            "official_output_allowed": "FALSE",
            "primary_content_contract": contract,
        }
        for idx, (section_id, title, section_type, contract) in enumerate(sections, start=1)
    ]


def field_contract_rows() -> list[dict[str, object]]:
    fields = [
        ("RUN_IDENTITY", "report_date", "date", "UTC report date or operator-selected report date", "required", "system/date metadata"),
        ("RUN_IDENTITY", "stage_name", "string", "V20.42 design stage name", "required", "V20.42"),
        ("RESEARCH_BOUNDARY", "research_only", "boolean", "Must be TRUE", "required", "V20.42 READ_FIRST"),
        ("RESEARCH_BOUNDARY", "official_output_allowed", "boolean", "Must be FALSE", "required", "V20.42 READ_FIRST"),
        ("MARKET_REGIME_PLACEHOLDER", "regime_label", "string", "Placeholder only until PIT regime source exists", "optional_future", "V20.39 placeholder"),
        ("BENCHMARK_CONTEXT_PLACEHOLDER", "spy_context", "string", "Placeholder for SPY context", "optional_future", "PIT benchmark cache"),
        ("BENCHMARK_CONTEXT_PLACEHOLDER", "qqq_context", "string", "Placeholder for QQQ context", "optional_future", "PIT benchmark cache"),
        ("CANDIDATE_UNIVERSE_SUMMARY", "candidate_universe_count", "integer", "Candidate count from accepted research lineage", "required", "V20.35-R2/V20.39-R1"),
        ("TOP_CANDIDATE_RESEARCH_TABLE_DESIGN", "candidate_rows", "table", "Research table schema, not a recommendation list", "required", "V20.42 schema"),
        ("FACTOR_SUPPORT_SUMMARY", "factor_support_rows", "table", "Factor availability and support summary", "required", "V20.38/V20.41"),
        ("ENTRY_STRATEGY_EVIDENCE_SUMMARY", "strategy_evidence_rows", "table", "Entry strategy evidence summary", "required", "V20.36/V20.37/V20.39-R2"),
        ("SHADOW_DYNAMIC_WEIGHTING_EVIDENCE_SUMMARY", "shadow_weight_rows", "table", "Shadow dynamic weighting design evidence", "required", "V20.39/V20.39-R1"),
        ("PORTFOLIO_EXPLORATORY_BACKTEST_EVIDENCE_SUMMARY", "portfolio_evidence_rows", "table", "Portfolio exploratory evidence summary", "required", "V20.40"),
        ("PIT_FACTOR_EXPANSION_STATUS", "pit_expansion_rows", "table", "PIT expansion status summary", "required", "V20.41"),
        ("RISK_AND_BLOCKER_SUMMARY", "risk_blocker_rows", "table", "Risk, blocker, and source backlog summary", "required", "V20.40/V20.41"),
        ("DATA_FRESHNESS_LINEAGE_LEAKAGE_STATUS", "lineage_gate_status", "table", "Input availability, PIT leakage, formula, and refresh status", "required", "V20 prior gates"),
        ("HUMAN_READABLE_NEXT_STEP_DECISION", "next_step_text", "string", "Plain-language next action for research workflow", "required", "V20.42 decision"),
        ("OFFICIAL_OUTPUT_PROHIBITION", "official_prohibition_flags", "table", "Explicit negative safety flags", "required", "V20.42 READ_FIRST"),
    ]
    return [
        {
            "section_id": section_id,
            "field_name": field_name,
            "field_type": field_type,
            "readable_description": description,
            "requirement_level": level,
            "source_contract": source,
            "may_create_official_output": "FALSE",
            "may_trigger_provider_refresh": "FALSE",
        }
        for section_id, field_name, field_type, description, level, source in fields
    ]


def table_schema(table_name: str, fields: list[tuple[str, str, str, str]]) -> list[dict[str, object]]:
    return [
        {
            "table_name": table_name,
            "column_order": idx,
            "column_name": name,
            "column_type": col_type,
            "column_description": desc,
            "required": required,
            "research_only": "TRUE",
            "official_recommendation_field": "FALSE",
        }
        for idx, (name, col_type, desc, required) in enumerate(fields, start=1)
    ]


def main() -> int:
    v35_top20, _ = read_csv(IN_V35_R2_TOP20)
    v35_next, _ = read_csv(IN_V35_R2_NEXT)
    v36_master, _ = read_csv(IN_V36_MASTER)
    v36_next, _ = read_csv(IN_V36_NEXT)
    v37_family, _ = read_csv(IN_V37_FAMILY)
    v37_next, _ = read_csv(IN_V37_NEXT)
    v38_coverage, _ = read_csv(IN_V38_COVERAGE)
    v38_effect, _ = read_csv(IN_V38_EFFECT)
    v38_next, _ = read_csv(IN_V38_NEXT)
    v39_eligible, _ = read_csv(IN_V39_ELIGIBLE)
    v39_weight_sets, _ = read_csv(IN_V39_WEIGHT_SETS)
    v39_next, _ = read_csv(IN_V39_NEXT)
    v39_r1_summary, _ = read_csv(IN_V39_R1_SUMMARY)
    v39_r1_next, _ = read_csv(IN_V39_R1_NEXT)
    v39_r2_family, _ = read_csv(IN_V39_R2_FAMILY)
    v39_r2_next, _ = read_csv(IN_V39_R2_NEXT)
    v40_policy, _ = read_csv(IN_V40_POLICY_SUM)
    v40_risk, _ = read_csv(IN_V40_RISK)
    v40_next, _ = read_csv(IN_V40_NEXT)
    v41_decision, _ = read_csv(IN_V41_DECISION)
    v41_coverage, _ = read_csv(IN_V41_COVERAGE)
    v41_source, _ = read_csv(IN_V41_SOURCE)
    v41_next, _ = read_csv(IN_V41_NEXT)

    dependency_rows = [
        source_row("V20.35-R2", IN_V35_R2_TOP20, v35_top20),
        source_row("V20.35-R2", IN_V35_R2_NEXT, v35_next),
        source_row("V20.36", IN_V36_MASTER, v36_master),
        source_row("V20.36", IN_V36_NEXT, v36_next),
        source_row("V20.37", IN_V37_FAMILY, v37_family),
        source_row("V20.37", IN_V37_NEXT, v37_next),
        source_row("V20.38", IN_V38_COVERAGE, v38_coverage),
        source_row("V20.38", IN_V38_EFFECT, v38_effect),
        source_row("V20.38", IN_V38_NEXT, v38_next),
        source_row("V20.39", IN_V39_ELIGIBLE, v39_eligible),
        source_row("V20.39", IN_V39_WEIGHT_SETS, v39_weight_sets),
        source_row("V20.39", IN_V39_NEXT, v39_next),
        source_row("V20.39-R1", IN_V39_R1_SUMMARY, v39_r1_summary),
        source_row("V20.39-R1", IN_V39_R1_NEXT, v39_r1_next),
        source_row("V20.39-R2", IN_V39_R2_FAMILY, v39_r2_family),
        source_row("V20.39-R2", IN_V39_R2_NEXT, v39_r2_next),
        source_row("V20.40", IN_V40_POLICY_SUM, v40_policy),
        source_row("V20.40", IN_V40_RISK, v40_risk),
        source_row("V20.40", IN_V40_NEXT, v40_next),
        source_row("V20.41", IN_V41_DECISION, v41_decision),
        source_row("V20.41", IN_V41_COVERAGE, v41_coverage),
        source_row("V20.41", IN_V41_SOURCE, v41_source),
        source_row("V20.41", IN_V41_NEXT, v41_next),
    ]
    required_missing = [row for row in dependency_rows if row["required_for_report_design"] == "TRUE" and row["source_exists"] != "TRUE"]

    v40 = v40_next[0] if v40_next else {}
    v41 = v41_next[0] if v41_next else {}
    gate_ready = (
        not required_missing
        and upper(v40.get("STATUS")) == "PASS_V20_40_PORTFOLIO_LEVEL_EXPLORATORY_BACKTEST"
        and upper(v40.get("READY_FOR_DAILY_OPERATOR_RESEARCH_REPORT_DESIGN")) == "TRUE"
        and upper(v41.get("STATUS")) == "PASS_V20_41_RESEARCH_FACTOR_PIT_EXPANSION_PLAN"
        and upper(v41.get("RESEARCH_ONLY")) == "TRUE"
        and upper(v41.get("READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION")) == "FALSE"
    )

    metrics = {
        "v35_r2_top20_rows": len(v35_top20),
        "v36_strategy_rows": len(v36_master),
        "v37_family_rows": len(v37_family),
        "v38_factor_rows": len(v38_coverage),
        "v39_weight_set_rows": len(v39_weight_sets),
        "v39_r1_summary_rows": len(v39_r1_summary),
        "v39_r2_family_rows": len(v39_r2_family),
        "v40_policy_rows": len(v40_policy),
        "v40_risk_rows": len(v40_risk),
        "v41_decision_rows": len(v41_decision),
        "v41_pit_ready_count": count_true(v41_decision, "pit_backtest_eligible_now"),
        "v41_price_cache_count": count_true(v41_decision, "price_cache_computable"),
        "v41_backfill_count": count_true(v41_decision, "historical_source_backfill_required"),
        "v41_blocked_count": count_true(v41_decision, "blocked_non_pit_current_only"),
        "v41_dynamic_candidate_count": count_true(v41_decision, "future_dynamic_weighting_candidate"),
        "v41_source_backlog_rows": len(v41_source),
    }

    sections = section_rows(metrics)
    fields = field_contract_rows()
    candidate_schema = table_schema("daily_operator_top_candidate_research_table", [
        ("display_rank", "integer", "Display-only research ordering within the report", "TRUE"),
        ("ticker", "string", "Ticker from accepted research candidate lineage", "TRUE"),
        ("signal_date", "date", "Historical or as-of signal date from accepted lineage", "TRUE"),
        ("candidate_source_stage", "string", "Prior V20 source stage", "TRUE"),
        ("top_bucket", "string", "Accepted exploratory bucket label", "FALSE"),
        ("technical_score_summary", "string", "Readable technical factor score summary", "FALSE"),
        ("factor_support_summary", "string", "Readable factor evidence summary", "FALSE"),
        ("entry_strategy_summary", "string", "Readable entry strategy evidence summary", "FALSE"),
        ("shadow_weighting_summary", "string", "Readable shadow weighting evidence summary", "FALSE"),
        ("portfolio_context_summary", "string", "Readable portfolio exploratory context", "FALSE"),
        ("risk_blocker_summary", "string", "Risk, blocker, and source caveats", "TRUE"),
        ("research_only_disclaimer", "string", "Explicit non-official label", "TRUE"),
    ])
    factor_schema = table_schema("daily_operator_factor_summary", [
        ("factor_category", "string", "V20.41 factor category", "TRUE"),
        ("factor_family", "string", "Factor family or source family", "TRUE"),
        ("pit_backtest_eligible_now", "boolean", "PIT/backtest eligibility from V20.41", "TRUE"),
        ("price_cache_computable", "boolean", "Computable from historical price/cache data", "TRUE"),
        ("historical_source_backfill_required", "boolean", "Whether PIT source backfill is required", "TRUE"),
        ("blocked_non_pit_current_only", "boolean", "Whether current-only dependency blocks use", "TRUE"),
        ("future_dynamic_weighting_candidate", "boolean", "Design-only future candidate flag", "TRUE"),
        ("readable_factor_note", "string", "Human-readable evidence note", "FALSE"),
    ])
    strategy_schema = table_schema("daily_operator_strategy_summary", [
        ("strategy_id", "string", "Entry strategy identifier", "TRUE"),
        ("strategy_family", "string", "Entry strategy family", "TRUE"),
        ("eligibility_status", "string", "Prior V20 eligibility status", "TRUE"),
        ("fill_policy_summary", "string", "No-fill and fallback policy", "FALSE"),
        ("risk_filter_summary", "string", "Risk filter notes", "FALSE"),
        ("evidence_source_stage", "string", "V20.36/V20.37/V20.39-R2 lineage", "TRUE"),
        ("readable_strategy_note", "string", "Human-readable strategy evidence note", "FALSE"),
    ])
    risk_schema = table_schema("daily_operator_risk_blocker_summary", [
        ("risk_blocker_id", "string", "Risk or blocker identifier", "TRUE"),
        ("source_stage", "string", "Prior V20 source stage", "TRUE"),
        ("severity", "string", "Design severity label", "TRUE"),
        ("pit_or_lineage_impact", "string", "Impact on PIT or lineage readiness", "TRUE"),
        ("required_source_or_action", "string", "Required future source or action", "FALSE"),
        ("official_output_allowed", "boolean", "Always FALSE in V20.42", "TRUE"),
    ])

    next_status = PASS_STATUS if gate_ready else BLOCKED_STATUS
    next_rows = [{
        "STAGE_NAME": STAGE_NAME,
        "STATUS": next_status,
        "V20_40_READY_FOR_DAILY_OPERATOR_RESEARCH_REPORT_DESIGN": clean(v40.get("READY_FOR_DAILY_OPERATOR_RESEARCH_REPORT_DESIGN")),
        "V20_41_STATUS": clean(v41.get("STATUS")),
        "SECTION_COUNT": len(sections),
        "FIELD_CONTRACT_ROWS": len(fields),
        "INPUT_DEPENDENCY_ROWS": len(dependency_rows),
        "CANDIDATE_TABLE_SCHEMA_ROWS": len(candidate_schema),
        "FACTOR_SUMMARY_SCHEMA_ROWS": len(factor_schema),
        "STRATEGY_SUMMARY_SCHEMA_ROWS": len(strategy_schema),
        "RISK_BLOCKER_SCHEMA_ROWS": len(risk_schema),
        "REQUIRED_INPUT_MISSING_COUNT": len(required_missing),
        "RESEARCH_ONLY": "TRUE",
        "DESIGN_ONLY": "TRUE",
        "OFFICIAL_RECOMMENDATION_CREATED": "FALSE",
        "BUY_SELL_TRIM_RECOMMENDATION_CREATED": "FALSE",
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
        "HUMAN_READABLE_NEXT_STEP": "Use this design to build a research-only operator report renderer after source freshness and PIT evidence remain passing.",
    }]

    validation_rows = [
        {"validation_check": "required_inputs_available", "result": "PASS" if not required_missing else "FAIL", "detail": f"missing_required_inputs={len(required_missing)}"},
        {"validation_check": "required_sections_defined", "result": "PASS" if len(sections) == 15 else "FAIL", "detail": f"section_count={len(sections)}"},
        {"validation_check": "research_only_boundary", "result": "PASS", "detail": "official output and execution flags are FALSE"},
        {"validation_check": "no_provider_refresh", "result": "PASS", "detail": "stage reads local V20 outputs only"},
        {"validation_check": "no_new_return_computation", "result": "PASS", "detail": "stage creates report schemas and summaries only"},
        {"validation_check": "v20_41_gate_ready", "result": "PASS" if upper(v41.get("STATUS")) == "PASS_V20_41_RESEARCH_FACTOR_PIT_EXPANSION_PLAN" else "FAIL", "detail": clean(v41.get("STATUS"))},
        {"validation_check": "stage_status", "result": "PASS" if next_status == PASS_STATUS else "FAIL", "detail": next_status},
    ]

    write_csv(OUT_SECTION, sections, [
        "section_order",
        "section_id",
        "section_title",
        "section_type",
        "design_status",
        "research_only",
        "official_output_allowed",
        "primary_content_contract",
    ])
    write_csv(OUT_FIELD, fields, [
        "section_id",
        "field_name",
        "field_type",
        "readable_description",
        "requirement_level",
        "source_contract",
        "may_create_official_output",
        "may_trigger_provider_refresh",
    ])
    write_csv(OUT_DEP, dependency_rows, [
        "source_stage",
        "input_file",
        "source_exists",
        "row_count",
        "required_for_report_design",
        "used_for_return_computation",
        "provider_refresh_required",
        "dependency_status",
    ])
    write_csv(OUT_CANDIDATE, candidate_schema, [
        "table_name",
        "column_order",
        "column_name",
        "column_type",
        "column_description",
        "required",
        "research_only",
        "official_recommendation_field",
    ])
    write_csv(OUT_FACTOR, factor_schema, [
        "table_name",
        "column_order",
        "column_name",
        "column_type",
        "column_description",
        "required",
        "research_only",
        "official_recommendation_field",
    ])
    write_csv(OUT_STRATEGY, strategy_schema, [
        "table_name",
        "column_order",
        "column_name",
        "column_type",
        "column_description",
        "required",
        "research_only",
        "official_recommendation_field",
    ])
    write_csv(OUT_RISK, risk_schema, [
        "table_name",
        "column_order",
        "column_name",
        "column_type",
        "column_description",
        "required",
        "research_only",
        "official_recommendation_field",
    ])
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))
    write_csv(OUT_VALIDATION, validation_rows, ["validation_check", "result", "detail"])

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    report = f"""# V20.42 Daily Operator Research Report Design

Generated: {now}

Status: {next_status}

## Purpose

V20.42 defines a readable daily operator research report framework using existing V20 outputs only. It is a design-only stage and does not create a rendered daily recommendation list, official ranking, signal file, order file, weight file, provider refresh, portfolio backtest, or new return computation.

## Required Sections

| Order | Section | Contract |
| ---: | --- | --- |
"""
    for row in sections:
        report += f"| {row['section_order']} | {row['section_title']} | {row['primary_content_contract']} |\n"
    report += f"""
## Evidence Counts

- V20.35-R2 Top20 rows: {metrics['v35_r2_top20_rows']}
- V20.36 strategy rows: {metrics['v36_strategy_rows']}
- V20.38 factor coverage rows: {metrics['v38_factor_rows']}
- V20.39 shadow weight set rows: {metrics['v39_weight_set_rows']}
- V20.40 portfolio policy rows: {metrics['v40_policy_rows']}
- V20.41 factor decision rows: {metrics['v41_decision_rows']}
- V20.41 PIT-ready factor rows: {metrics['v41_pit_ready_count']}
- V20.41 source backlog rows: {metrics['v41_source_backlog_rows']}

## Safety Boundary

- DESIGN_ONLY=TRUE
- RESEARCH_ONLY=TRUE
- OFFICIAL_RECOMMENDATION_CREATED=FALSE
- BUY_SELL_TRIM_RECOMMENDATION_CREATED=FALSE
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

## Human-Readable Next Step

Use this design to build a research-only operator report renderer after source freshness and PIT evidence remain passing. Official trading or recommendation output remains prohibited.
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)

    read_first = "\n".join([
        f"STAGE_NAME={STAGE_NAME}",
        f"STATUS={next_status}",
        "READ_FIRST_PURPOSE=Design-only daily operator research report framework after V20.41.",
        "DESIGN_ONLY=TRUE",
        "RESEARCH_ONLY=TRUE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "BUY_SELL_TRIM_RECOMMENDATION_CREATED=FALSE",
        "TRADING_SIGNAL_CREATED=FALSE",
        "BROKER_ORDER_PATH_CREATED=FALSE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "OFFICIAL_FACTOR_WEIGHTS_MUTATED=FALSE",
        "DYNAMIC_WEIGHTING_EXECUTED=FALSE",
        "PORTFOLIO_BACKTEST_RERUN=FALSE",
        "NEW_RETURN_COMPUTATION_CREATED=FALSE",
        "PROVIDER_REFRESH_EXECUTED=FALSE",
        "YFINANCE_REFRESH_EXECUTED=FALSE",
        "NETWORK_REFRESH_EXECUTED=FALSE",
        "PRIOR_ACCEPTED_OUTPUTS_MUTATED=FALSE",
        "V21_OUTPUTS_CREATED=FALSE",
        "V19_21_OUTPUTS_CREATED=FALSE",
        "READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION=FALSE",
        f"SECTION_COUNT={len(sections)}",
        f"FIELD_CONTRACT_ROWS={len(fields)}",
        f"INPUT_DEPENDENCY_ROWS={len(dependency_rows)}",
        f"REQUIRED_INPUT_MISSING_COUNT={len(required_missing)}",
        "",
    ])
    write_text(READ_FIRST, read_first)

    print(next_status)
    print(f"SECTION_COUNT={len(sections)}")
    print(f"READ_FIRST={rel(READ_FIRST)}")
    return 0 if next_status == PASS_STATUS else 1


if __name__ == "__main__":
    raise SystemExit(main())
