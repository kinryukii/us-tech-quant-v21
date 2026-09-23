from __future__ import annotations

import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"

IN_V42_SECTION = CONSOLIDATION / "V20_42_DAILY_OPERATOR_REPORT_SECTION_MAP.csv"
IN_V42_FIELD = CONSOLIDATION / "V20_42_DAILY_OPERATOR_REPORT_FIELD_CONTRACT.csv"
IN_V42_DEP = CONSOLIDATION / "V20_42_DAILY_OPERATOR_REPORT_INPUT_DEPENDENCY_MAP.csv"
IN_V42_NEXT = CONSOLIDATION / "V20_42_DAILY_OPERATOR_REPORT_NEXT_STEP_DECISION.csv"
IN_V35_R2_TOP20 = CONSOLIDATION / "V20_35_R2_ASOF_TOP20_SELECTIONS.csv"
IN_V35_R2_RANKING = CONSOLIDATION / "V20_35_R2_ASOF_TECHNICAL_SCORE_AND_RANKING.csv"
IN_V35_R2_AVAIL = CONSOLIDATION / "V20_35_R2_ASOF_TECHNICAL_FACTOR_AVAILABILITY_SUMMARY.csv"
IN_V36_MASTER = CONSOLIDATION / "V20_36_ENTRY_STRATEGY_MASTER_MATRIX.csv"
IN_V37_FAMILY = CONSOLIDATION / "V20_37_ENTRY_STRATEGY_FAMILY_SUMMARY.csv"
IN_V37_FILL = CONSOLIDATION / "V20_37_ENTRY_STRATEGY_FILL_NO_FILL_SUMMARY.csv"
IN_V38_COVERAGE = CONSOLIDATION / "V20_38_FACTOR_COVERAGE_AND_QUALITY_AUDIT.csv"
IN_V38_STABILITY = CONSOLIDATION / "V20_38_FACTOR_STABILITY_AUDIT.csv"
IN_V39_ELIGIBLE = CONSOLIDATION / "V20_39_ELIGIBLE_SHADOW_FACTOR_UNIVERSE.csv"
IN_V39_WEIGHT_SETS = CONSOLIDATION / "V20_39_SHADOW_WEIGHT_CANDIDATE_SUMMARY.csv"
IN_V39_REGIME = CONSOLIDATION / "V20_39_MARKET_REGIME_CONDITIONAL_WEIGHTING_PLACEHOLDER.csv"
IN_V39_R1_COMPARE = CONSOLIDATION / "V20_39_R1_SHADOW_CANDIDATE_WEIGHT_SET_COMPARISON.csv"
IN_V39_R2_FAMILY = CONSOLIDATION / "V20_39_R2_SHADOW_ENTRY_STRATEGY_FAMILY_SUMMARY.csv"
IN_V40_POLICY = CONSOLIDATION / "V20_40_PORTFOLIO_POLICY_SUMMARY.csv"
IN_V40_RISK = CONSOLIDATION / "V20_40_PORTFOLIO_RISK_AND_CONCENTRATION_AUDIT.csv"
IN_V40_NEXT = CONSOLIDATION / "V20_40_NEXT_STEP_DECISION_SUMMARY.csv"
IN_V41_DECISION = CONSOLIDATION / "V20_41_FACTOR_PIT_EXPANSION_DECISION.csv"
IN_V41_COVERAGE = CONSOLIDATION / "V20_41_FACTOR_COVERAGE_BY_CATEGORY.csv"
IN_V41_SOURCE = CONSOLIDATION / "V20_41_REQUIRED_SOURCE_BACKLOG.csv"
IN_V41_NEXT = CONSOLIDATION / "V20_41_NEXT_STEP_DECISION_SUMMARY.csv"

OUT_MANIFEST = CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_DRY_RUN_MANIFEST.csv"
OUT_SOURCE = CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_SOURCE_STATUS.csv"
OUT_SECTION = CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_SECTION_STATUS.csv"
OUT_CANDIDATE = CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_CANDIDATE_RESEARCH_TABLE.csv"
OUT_FACTOR = CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_FACTOR_SUPPORT_SUMMARY.csv"
OUT_ENTRY = CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_ENTRY_STRATEGY_SUMMARY.csv"
OUT_SHADOW = CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_SHADOW_WEIGHTING_SUMMARY.csv"
OUT_PORTFOLIO = CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_PORTFOLIO_EVIDENCE_SUMMARY.csv"
OUT_RISK = CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_RISK_BLOCKER_SUMMARY.csv"
OUT_LINEAGE = CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_LINEAGE_FRESHNESS_SUMMARY.csv"
OUT_NEXT = CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_NEXT_STEP_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_43_VALIDATION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_43_DAILY_OPERATOR_REPORT_DRY_RUN_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_DAILY_OPERATOR_REPORT_DRY_RUN.md"
READ_FIRST = OPS / "V20_43_READ_FIRST.txt"

STAGE_NAME = "V20.43_DAILY_OPERATOR_REPORT_DRY_RUN"
PASS_STATUS = "PASS_V20_43_DAILY_OPERATOR_REPORT_DRY_RUN"
BLOCKED_STATUS = "BLOCKED_V20_43_DAILY_OPERATOR_REPORT_DRY_RUN"


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


def source_status(stage: str, path: Path, rows: list[dict[str, str]], required: bool) -> dict[str, object]:
    exists = path.exists()
    return {
        "source_stage": stage,
        "source_file": rel(path),
        "source_exists": tf(exists),
        "row_count": len(rows),
        "required_for_dry_run": tf(required),
        "used_existing_output_only": "TRUE",
        "provider_refresh_executed": "FALSE",
        "new_return_computation_executed": "FALSE",
        "source_status": "AVAILABLE" if exists else ("MISSING_REQUIRED" if required else "MISSING_OPTIONAL"),
    }


def first_existing(row: dict[str, str], names: list[str]) -> str:
    for name in names:
        value = clean(row.get(name))
        if value:
            return value
    return ""


def numeric_summary(rows: list[dict[str, str]], field: str) -> tuple[int, str, str]:
    values = []
    for row in rows:
        try:
            values.append(float(clean(row.get(field))))
        except ValueError:
            continue
    if not values:
        return 0, "", ""
    return len(values), min(values), max(values)


def build_candidate_rows(top20: list[dict[str, str]], ranking: list[dict[str, str]]) -> list[dict[str, object]]:
    ranking_by_key = {
        (clean(row.get("signal_date")), clean(row.get("ticker"))): row
        for row in ranking
        if clean(row.get("signal_date")) and clean(row.get("ticker"))
    }
    rows = top20[:50] if top20 else ranking[:50]
    out = []
    for idx, row in enumerate(rows, start=1):
        signal_date = clean(row.get("signal_date"))
        ticker = clean(row.get("ticker"))
        rank_row = ranking_by_key.get((signal_date, ticker), {})
        score = first_existing(row, ["exploratory_technical_score", "technical_score", "asof_technical_score"]) or first_existing(rank_row, ["exploratory_technical_score", "technical_score", "asof_technical_score"])
        rank = first_existing(row, ["asof_technical_rank", "rank", "technical_rank"]) or first_existing(rank_row, ["asof_technical_rank", "rank", "technical_rank"]) or idx
        out.append({
            "display_order": idx,
            "ticker": ticker,
            "signal_date": signal_date,
            "research_rank": rank,
            "top_bucket": first_existing(row, ["top_bucket", "selection_bucket"]) or "Top20",
            "technical_score": score,
            "candidate_source_stage": "V20.35-R2",
            "factor_support_note": "Technical candidate from accepted random as-of research output.",
            "entry_strategy_note": "Entry strategy evidence is summarized separately; this row is not an entry instruction.",
            "portfolio_context_note": "Portfolio context is exploratory and non-official.",
            "official_recommendation": "FALSE",
            "trading_signal": "FALSE",
            "dry_run_only": "TRUE",
        })
    return out


def build_factor_summary(v38_coverage: list[dict[str, str]], v38_stability: list[dict[str, str]], v41_coverage: list[dict[str, str]]) -> list[dict[str, object]]:
    stability = {clean(row.get("factor_name")): row for row in v38_stability}
    out = []
    for row in v38_coverage:
        factor_name = clean(row.get("factor_name"))
        st = stability.get(factor_name, {})
        out.append({
            "summary_type": "factor_evidence",
            "factor_category": "technical_or_risk",
            "factor_name": factor_name,
            "factor_count_or_rows": clean(row.get("row_count")),
            "available_value_count": clean(row.get("available_value_count")),
            "pit_backtest_eligible_now": clean(row.get("eligible_for_effectiveness_scoring")),
            "price_cache_computable": "TRUE",
            "historical_source_backfill_required": "FALSE",
            "blocked_non_pit_current_only": "FALSE",
            "stability_or_coverage_status": clean(st.get("stability_category")) or "V20_38_COVERAGE_ONLY",
            "readable_note": "Prior technical factor evidence available for readable dry-run reporting.",
        })
    for row in v41_coverage:
        out.append({
            "summary_type": "v20_41_category_coverage",
            "factor_category": clean(row.get("factor_category")),
            "factor_name": clean(row.get("factor_category")),
            "factor_count_or_rows": clean(row.get("factor_count")),
            "available_value_count": "",
            "pit_backtest_eligible_now": clean(row.get("pit_backtest_eligible_now_count")),
            "price_cache_computable": clean(row.get("price_cache_computable_count")),
            "historical_source_backfill_required": clean(row.get("historical_source_backfill_required_count")),
            "blocked_non_pit_current_only": clean(row.get("blocked_non_pit_current_only_count")),
            "stability_or_coverage_status": clean(row.get("coverage_status")),
            "readable_note": "V20.41 category-level PIT expansion coverage for daily operator context.",
        })
    return out


def build_entry_rows(v36_master: list[dict[str, str]], v37_family: list[dict[str, str]], v39_r2_family: list[dict[str, str]]) -> list[dict[str, object]]:
    family_counts = Counter(clean(row.get("strategy_family")) for row in v36_master if clean(row.get("strategy_family")))
    v37_by_family = {clean(row.get("strategy_family")): row for row in v37_family}
    r2_by_family = {clean(row.get("strategy_family")): row for row in v39_r2_family}
    out = []
    for family in sorted(family_counts):
        v37 = v37_by_family.get(family, {})
        r2 = r2_by_family.get(family, {})
        out.append({
            "strategy_family": family,
            "strategy_design_count": family_counts[family],
            "v37_evidence_rows": first_existing(v37, ["row_count", "entry_strategy_count", "portfolio_event_count"]),
            "v39_r2_evidence_rows": first_existing(r2, ["row_count", "entry_strategy_count", "portfolio_event_count"]),
            "fill_or_execution_note": "Uses prior exploratory evidence only; no entry instruction is created.",
            "readable_evidence_note": "Entry strategy family is available for dry-run research review.",
            "official_strategy_promoted": "FALSE",
            "trading_signal_created": "FALSE",
        })
    return out


def build_shadow_rows(v39_eligible: list[dict[str, str]], v39_weight_sets: list[dict[str, str]], v39_r1_compare: list[dict[str, str]]) -> list[dict[str, object]]:
    out = []
    out.append({
        "summary_id": "eligible_shadow_factor_universe",
        "source_stage": "V20.39",
        "row_count": len(v39_eligible),
        "evidence_summary": f"{len(v39_eligible)} factors were eligible for shadow weighting design.",
        "dry_run_interpretation": "Evidence is descriptive and does not execute dynamic weighting.",
        "dynamic_weighting_executed": "FALSE",
        "official_factor_weights_mutated": "FALSE",
    })
    out.append({
        "summary_id": "shadow_weight_candidate_sets",
        "source_stage": "V20.39",
        "row_count": len(v39_weight_sets),
        "evidence_summary": f"{len(v39_weight_sets)} candidate weight-set summary rows are available.",
        "dry_run_interpretation": "Weight sets remain shadow research evidence only.",
        "dynamic_weighting_executed": "FALSE",
        "official_factor_weights_mutated": "FALSE",
    })
    out.append({
        "summary_id": "shadow_recompute_comparison",
        "source_stage": "V20.39-R1",
        "row_count": len(v39_r1_compare),
        "evidence_summary": f"{len(v39_r1_compare)} shadow recompute comparison rows are available.",
        "dry_run_interpretation": "Comparison is cited as prior exploratory evidence only.",
        "dynamic_weighting_executed": "FALSE",
        "official_factor_weights_mutated": "FALSE",
    })
    return out


def build_portfolio_rows(v40_policy: list[dict[str, str]], v40_risk: list[dict[str, str]], v40_next: list[dict[str, str]]) -> list[dict[str, object]]:
    policy_count = len(v40_policy)
    risk_count = len(v40_risk)
    status = clean(v40_next[0].get("STATUS")) if v40_next else ""
    return [{
        "summary_id": "v20_40_portfolio_exploratory_evidence",
        "source_stage": "V20.40",
        "portfolio_policy_rows": policy_count,
        "risk_audit_rows": risk_count,
        "prior_stage_status": status,
        "evidence_summary": f"V20.40 passed with {policy_count} portfolio policy summary rows and {risk_count} risk audit rows.",
        "dry_run_interpretation": "Portfolio evidence is exploratory context, not a model approval or official portfolio instruction.",
        "portfolio_backtest_rerun": "FALSE",
        "new_return_computation_created": "FALSE",
    }]


def build_risk_rows(v40_risk: list[dict[str, str]], v41_source: list[dict[str, str]], v41_decision: list[dict[str, str]]) -> list[dict[str, object]]:
    rows = []
    rows.append({
        "risk_blocker_id": "v20_40_portfolio_risk_audit",
        "source_stage": "V20.40",
        "risk_or_blocker_type": "portfolio_exploratory_risk",
        "row_count": len(v40_risk),
        "severity": "RESEARCH_REVIEW",
        "readable_summary": f"{len(v40_risk)} V20.40 risk/concentration rows available for operator review.",
        "required_future_action": "Review risk context before any future research renderer promotion.",
        "official_output_allowed": "FALSE",
    })
    rows.append({
        "risk_blocker_id": "v20_41_required_source_backlog",
        "source_stage": "V20.41",
        "risk_or_blocker_type": "pit_source_backfill",
        "row_count": len(v41_source),
        "severity": "BLOCKS_OFFICIAL_USE",
        "readable_summary": f"{len(v41_source)} PIT source backlog rows remain for future factor expansion.",
        "required_future_action": "Attach PIT-certified historical source contracts before official use.",
        "official_output_allowed": "FALSE",
    })
    blocked = [row for row in v41_decision if upper(row.get("blocked_non_pit_current_only")) == "TRUE"]
    rows.append({
        "risk_blocker_id": "v20_41_non_pit_blocked_factors",
        "source_stage": "V20.41",
        "risk_or_blocker_type": "non_pit_current_only_dependency",
        "row_count": len(blocked),
        "severity": "BLOCKS_OFFICIAL_USE",
        "readable_summary": f"{len(blocked)} factor decision rows remain blocked due to non-PIT/current-only dependency.",
        "required_future_action": "Do not use blocked factors until PIT-safe source history exists.",
        "official_output_allowed": "FALSE",
    })
    return rows


def build_lineage_rows(source_rows: list[dict[str, object]], next_rows: list[dict[str, str]]) -> list[dict[str, object]]:
    lineage = []
    for row in source_rows:
        lineage.append({
            "lineage_item": row["source_stage"],
            "source_file": row["source_file"],
            "source_exists": row["source_exists"],
            "row_count": row["row_count"],
            "freshness_status": "EXISTING_OUTPUT_USED",
            "provider_refresh_executed": "FALSE",
            "leakage_or_formula_status": "SEE_PRIOR_STAGE_GATES",
            "readable_note": "Dry run uses accepted local output only.",
        })
    for idx, row in enumerate(next_rows, start=1):
        if not row:
            continue
        lineage.append({
            "lineage_item": f"prior_next_step_{idx}",
            "source_file": "prior_next_step_summary",
            "source_exists": "TRUE",
            "row_count": 1,
            "freshness_status": "PRIOR_GATE_STATUS_READ",
            "provider_refresh_executed": "FALSE",
            "leakage_or_formula_status": f"leakage_blockers={clean(row.get('LEAKAGE_BLOCKER_COUNT')) or '0'}; formula_mismatches={clean(row.get('FORMULA_MISMATCH_COUNT')) or '0'}",
            "readable_note": clean(row.get("STATUS")) or "Prior stage status read.",
        })
    return lineage


def section_status_rows(sections: list[dict[str, str]], section_payload_counts: dict[str, int]) -> list[dict[str, object]]:
    out = []
    for row in sections:
        section_id = clean(row.get("section_id"))
        out.append({
            "section_order": clean(row.get("section_order")),
            "section_id": section_id,
            "section_title": clean(row.get("section_title")),
            "section_render_status": "RENDERED",
            "payload_row_count": section_payload_counts.get(section_id, 1),
            "dry_run_only": "TRUE",
            "research_only": "TRUE",
            "official_output_allowed": "FALSE",
            "render_note": "Rendered into V20.43 readable dry-run report.",
        })
    return out


def md_table(rows: list[dict[str, object]], columns: list[str], limit: int = 12) -> str:
    if not rows:
        return "_No rows available from accepted local outputs._\n"
    text = "| " + " | ".join(columns) + " |\n"
    text += "| " + " | ".join("---" for _ in columns) + " |\n"
    for row in rows[:limit]:
        text += "| " + " | ".join(clean(row.get(col)).replace("|", "/") for col in columns) + " |\n"
    if len(rows) > limit:
        text += f"\n_Showing {limit} of {len(rows)} rows._\n"
    return text


def main() -> int:
    v42_section, _ = read_csv(IN_V42_SECTION)
    v42_field, _ = read_csv(IN_V42_FIELD)
    v42_dep, _ = read_csv(IN_V42_DEP)
    v42_next, _ = read_csv(IN_V42_NEXT)
    v35_top20, _ = read_csv(IN_V35_R2_TOP20)
    v35_ranking, _ = read_csv(IN_V35_R2_RANKING)
    v35_avail, _ = read_csv(IN_V35_R2_AVAIL)
    v36_master, _ = read_csv(IN_V36_MASTER)
    v37_family, _ = read_csv(IN_V37_FAMILY)
    v37_fill, _ = read_csv(IN_V37_FILL)
    v38_coverage, _ = read_csv(IN_V38_COVERAGE)
    v38_stability, _ = read_csv(IN_V38_STABILITY)
    v39_eligible, _ = read_csv(IN_V39_ELIGIBLE)
    v39_weight_sets, _ = read_csv(IN_V39_WEIGHT_SETS)
    v39_regime, _ = read_csv(IN_V39_REGIME)
    v39_r1_compare, _ = read_csv(IN_V39_R1_COMPARE)
    v39_r2_family, _ = read_csv(IN_V39_R2_FAMILY)
    v40_policy, _ = read_csv(IN_V40_POLICY)
    v40_risk, _ = read_csv(IN_V40_RISK)
    v40_next, _ = read_csv(IN_V40_NEXT)
    v41_decision, _ = read_csv(IN_V41_DECISION)
    v41_coverage, _ = read_csv(IN_V41_COVERAGE)
    v41_source, _ = read_csv(IN_V41_SOURCE)
    v41_next, _ = read_csv(IN_V41_NEXT)

    source_rows = [
        source_status("V20.42", IN_V42_SECTION, v42_section, True),
        source_status("V20.42", IN_V42_FIELD, v42_field, True),
        source_status("V20.42", IN_V42_DEP, v42_dep, True),
        source_status("V20.42", IN_V42_NEXT, v42_next, True),
        source_status("V20.35-R2", IN_V35_R2_TOP20, v35_top20, True),
        source_status("V20.35-R2", IN_V35_R2_RANKING, v35_ranking, True),
        source_status("V20.35-R2", IN_V35_R2_AVAIL, v35_avail, False),
        source_status("V20.36", IN_V36_MASTER, v36_master, True),
        source_status("V20.37", IN_V37_FAMILY, v37_family, True),
        source_status("V20.37", IN_V37_FILL, v37_fill, False),
        source_status("V20.38", IN_V38_COVERAGE, v38_coverage, True),
        source_status("V20.38", IN_V38_STABILITY, v38_stability, False),
        source_status("V20.39", IN_V39_ELIGIBLE, v39_eligible, True),
        source_status("V20.39", IN_V39_WEIGHT_SETS, v39_weight_sets, True),
        source_status("V20.39", IN_V39_REGIME, v39_regime, False),
        source_status("V20.39-R1", IN_V39_R1_COMPARE, v39_r1_compare, True),
        source_status("V20.39-R2", IN_V39_R2_FAMILY, v39_r2_family, True),
        source_status("V20.40", IN_V40_POLICY, v40_policy, True),
        source_status("V20.40", IN_V40_RISK, v40_risk, True),
        source_status("V20.40", IN_V40_NEXT, v40_next, True),
        source_status("V20.41", IN_V41_DECISION, v41_decision, True),
        source_status("V20.41", IN_V41_COVERAGE, v41_coverage, True),
        source_status("V20.41", IN_V41_SOURCE, v41_source, True),
        source_status("V20.41", IN_V41_NEXT, v41_next, True),
    ]
    missing_required = [row for row in source_rows if row["required_for_dry_run"] == "TRUE" and row["source_exists"] != "TRUE"]

    candidate_rows = build_candidate_rows(v35_top20, v35_ranking)
    factor_rows = build_factor_summary(v38_coverage, v38_stability, v41_coverage)
    entry_rows = build_entry_rows(v36_master, v37_family, v39_r2_family)
    shadow_rows = build_shadow_rows(v39_eligible, v39_weight_sets, v39_r1_compare)
    portfolio_rows = build_portfolio_rows(v40_policy, v40_risk, v40_next)
    risk_rows = build_risk_rows(v40_risk, v41_source, v41_decision)
    lineage_rows = build_lineage_rows(source_rows, [v40_next[0] if v40_next else {}, v41_next[0] if v41_next else {}, v42_next[0] if v42_next else {}])

    section_payload_counts = {
        "RUN_IDENTITY": 1,
        "RESEARCH_BOUNDARY": 1,
        "MARKET_REGIME_PLACEHOLDER": max(1, len(v39_regime)),
        "BENCHMARK_CONTEXT_PLACEHOLDER": 1,
        "CANDIDATE_UNIVERSE_SUMMARY": 1,
        "TOP_CANDIDATE_RESEARCH_TABLE_DESIGN": len(candidate_rows),
        "FACTOR_SUPPORT_SUMMARY": len(factor_rows),
        "ENTRY_STRATEGY_EVIDENCE_SUMMARY": len(entry_rows),
        "SHADOW_DYNAMIC_WEIGHTING_EVIDENCE_SUMMARY": len(shadow_rows),
        "PORTFOLIO_EXPLORATORY_BACKTEST_EVIDENCE_SUMMARY": len(portfolio_rows),
        "PIT_FACTOR_EXPANSION_STATUS": len(v41_coverage),
        "RISK_AND_BLOCKER_SUMMARY": len(risk_rows),
        "DATA_FRESHNESS_LINEAGE_LEAKAGE_STATUS": len(lineage_rows),
        "HUMAN_READABLE_NEXT_STEP_DECISION": 1,
        "OFFICIAL_OUTPUT_PROHIBITION": 1,
    }
    section_rows = section_status_rows(v42_section, section_payload_counts)

    v42 = v42_next[0] if v42_next else {}
    v41 = v41_next[0] if v41_next else {}
    gate_ready = (
        not missing_required
        and upper(v42.get("STATUS")) == "PASS_V20_42_DAILY_OPERATOR_RESEARCH_REPORT_DESIGN"
        and upper(v42.get("DESIGN_ONLY")) == "TRUE"
        and upper(v42.get("RESEARCH_ONLY")) == "TRUE"
        and upper(v42.get("READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION")) == "FALSE"
        and upper(v41.get("STATUS")) == "PASS_V20_41_RESEARCH_FACTOR_PIT_EXPANSION_PLAN"
        and len(v42_section) >= 15
    )
    status = PASS_STATUS if gate_ready else BLOCKED_STATUS
    now = datetime.now(timezone.utc)
    report_date = now.strftime("%Y-%m-%d")
    generated_at = now.strftime("%Y-%m-%d %H:%M:%SZ")

    manifest_rows = [{
        "STAGE_NAME": STAGE_NAME,
        "STATUS": status,
        "REPORT_DATE": report_date,
        "GENERATED_AT_UTC": generated_at,
        "SOURCE_STATUS_ROWS": len(source_rows),
        "SECTION_STATUS_ROWS": len(section_rows),
        "CANDIDATE_RESEARCH_ROWS": len(candidate_rows),
        "FACTOR_SUPPORT_ROWS": len(factor_rows),
        "ENTRY_STRATEGY_ROWS": len(entry_rows),
        "SHADOW_WEIGHTING_ROWS": len(shadow_rows),
        "PORTFOLIO_EVIDENCE_ROWS": len(portfolio_rows),
        "RISK_BLOCKER_ROWS": len(risk_rows),
        "LINEAGE_FRESHNESS_ROWS": len(lineage_rows),
        "MISSING_REQUIRED_SOURCE_COUNT": len(missing_required),
        "DRY_RUN_ONLY": "TRUE",
        "RESEARCH_ONLY": "TRUE",
        "USE_EXISTING_OUTPUTS_ONLY": "TRUE",
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
    }]
    next_rows = [{
        "STAGE_NAME": STAGE_NAME,
        "STATUS": status,
        "REPORT_DATE": report_date,
        "HUMAN_READABLE_NEXT_STEP": "Review the dry-run report for readability and operator usefulness; keep official trading and recommendation outputs prohibited.",
        "READY_FOR_V20_44_RESEARCH_REPORT_REVIEW_TESTS": "TRUE" if status == PASS_STATUS else "FALSE",
        "READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION": "FALSE",
        "DRY_RUN_ONLY": "TRUE",
        "RESEARCH_ONLY": "TRUE",
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
    }]
    validation_rows = [
        {"validation_check": "v20_42_design_available", "result": "PASS" if upper(v42.get("STATUS")) == "PASS_V20_42_DAILY_OPERATOR_RESEARCH_REPORT_DESIGN" else "FAIL", "detail": clean(v42.get("STATUS"))},
        {"validation_check": "required_sources_available", "result": "PASS" if not missing_required else "FAIL", "detail": f"missing_required_sources={len(missing_required)}"},
        {"validation_check": "required_sections_rendered", "result": "PASS" if len(section_rows) >= 15 else "FAIL", "detail": f"section_rows={len(section_rows)}"},
        {"validation_check": "candidate_table_created", "result": "PASS" if candidate_rows else "FAIL", "detail": f"candidate_rows={len(candidate_rows)}"},
        {"validation_check": "safety_boundary", "result": "PASS", "detail": "dry-run/research-only with official output flags FALSE"},
        {"validation_check": "no_provider_refresh", "result": "PASS", "detail": "existing local outputs only"},
        {"validation_check": "no_new_return_computation", "result": "PASS", "detail": "readable report rendering only"},
        {"validation_check": "stage_status", "result": "PASS" if status == PASS_STATUS else "FAIL", "detail": status},
    ]

    write_csv(OUT_MANIFEST, manifest_rows, list(manifest_rows[0].keys()))
    write_csv(OUT_SOURCE, source_rows, [
        "source_stage", "source_file", "source_exists", "row_count", "required_for_dry_run",
        "used_existing_output_only", "provider_refresh_executed", "new_return_computation_executed", "source_status",
    ])
    write_csv(OUT_SECTION, section_rows, [
        "section_order", "section_id", "section_title", "section_render_status", "payload_row_count",
        "dry_run_only", "research_only", "official_output_allowed", "render_note",
    ])
    write_csv(OUT_CANDIDATE, candidate_rows, [
        "display_order", "ticker", "signal_date", "research_rank", "top_bucket", "technical_score",
        "candidate_source_stage", "factor_support_note", "entry_strategy_note", "portfolio_context_note",
        "official_recommendation", "trading_signal", "dry_run_only",
    ])
    write_csv(OUT_FACTOR, factor_rows, [
        "summary_type", "factor_category", "factor_name", "factor_count_or_rows", "available_value_count",
        "pit_backtest_eligible_now", "price_cache_computable", "historical_source_backfill_required",
        "blocked_non_pit_current_only", "stability_or_coverage_status", "readable_note",
    ])
    write_csv(OUT_ENTRY, entry_rows, [
        "strategy_family", "strategy_design_count", "v37_evidence_rows", "v39_r2_evidence_rows",
        "fill_or_execution_note", "readable_evidence_note", "official_strategy_promoted", "trading_signal_created",
    ])
    write_csv(OUT_SHADOW, shadow_rows, [
        "summary_id", "source_stage", "row_count", "evidence_summary", "dry_run_interpretation",
        "dynamic_weighting_executed", "official_factor_weights_mutated",
    ])
    write_csv(OUT_PORTFOLIO, portfolio_rows, [
        "summary_id", "source_stage", "portfolio_policy_rows", "risk_audit_rows", "prior_stage_status",
        "evidence_summary", "dry_run_interpretation", "portfolio_backtest_rerun", "new_return_computation_created",
    ])
    write_csv(OUT_RISK, risk_rows, [
        "risk_blocker_id", "source_stage", "risk_or_blocker_type", "row_count", "severity",
        "readable_summary", "required_future_action", "official_output_allowed",
    ])
    write_csv(OUT_LINEAGE, lineage_rows, [
        "lineage_item", "source_file", "source_exists", "row_count", "freshness_status",
        "provider_refresh_executed", "leakage_or_formula_status", "readable_note",
    ])
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))
    write_csv(OUT_VALIDATION, validation_rows, ["validation_check", "result", "detail"])

    regime_summary = "Market regime remains placeholder/design-only."
    if v39_regime:
        statuses = Counter(clean(row.get("status")) for row in v39_regime)
        regime_summary = "; ".join(f"{key or 'UNSPECIFIED'}={value}" for key, value in sorted(statuses.items()))
    factor_counts = Counter(clean(row.get("factor_category")) for row in v41_decision)
    factor_count_text = ", ".join(f"{key or 'uncategorized'}={value}" for key, value in sorted(factor_counts.items()))

    report = f"""# V20.43 Daily Operator Report Dry Run

Report date: {report_date}
Generated: {generated_at}
Status: {status}

## 1. Run Identity And Report Date

- Stage: {STAGE_NAME}
- Report date: {report_date}
- Source design: V20.42 daily operator research report design
- Dry-run manifest rows: {len(manifest_rows)}

## 2. Research-Only / Dry-Run-Only Boundary

This report is a readable dry run for operator research review. It is not official, not a recommendation, not a trading signal, and not an order instruction. It uses existing V20 outputs only.

## 3. Market Regime Placeholder Or Available Regime Summary

{regime_summary}

## 4. Benchmark Context Placeholder For SPY/QQQ

SPY/QQQ benchmark context is reserved for a future PIT-safe report renderer. V20.43 does not fetch benchmark data and does not compute fresh returns.

## 5. Candidate Universe Summary

- V20.35-R2 Top20 rows available: {len(v35_top20)}
- V20.35-R2 ranking rows available: {len(v35_ranking)}
- Dry-run candidate table rows emitted: {len(candidate_rows)}
- Candidate rows are research display rows only.

## 6. Top Candidate Research Table

{md_table(candidate_rows, ["display_order", "ticker", "signal_date", "research_rank", "top_bucket", "technical_score"], 20)}

## 7. Factor Support Summary

- V20.38 factor coverage rows: {len(v38_coverage)}
- V20.41 factor decision rows: {len(v41_decision)}
- V20.41 factor categories: {factor_count_text}

{md_table(factor_rows, ["summary_type", "factor_category", "factor_name", "pit_backtest_eligible_now", "stability_or_coverage_status"], 12)}

## 8. Entry Strategy Evidence Summary

{md_table(entry_rows, ["strategy_family", "strategy_design_count", "v37_evidence_rows", "v39_r2_evidence_rows"], 12)}

## 9. Shadow Dynamic Weighting Evidence Summary

{md_table(shadow_rows, ["summary_id", "source_stage", "row_count", "dry_run_interpretation"], 10)}

## 10. Portfolio Exploratory Backtest Evidence Summary

{md_table(portfolio_rows, ["summary_id", "portfolio_policy_rows", "risk_audit_rows", "prior_stage_status"], 10)}

## 11. PIT Factor Expansion Status

- PIT-ready rows from V20.41: {sum(1 for row in v41_decision if upper(row.get("pit_backtest_eligible_now")) == "TRUE")}
- Price/cache-derived rows from V20.41: {sum(1 for row in v41_decision if upper(row.get("price_cache_computable")) == "TRUE")}
- Backfill-required rows from V20.41: {sum(1 for row in v41_decision if upper(row.get("historical_source_backfill_required")) == "TRUE")}
- Source backlog rows: {len(v41_source)}

## 12. Risk And Blocker Summary

{md_table(risk_rows, ["risk_blocker_id", "source_stage", "risk_or_blocker_type", "row_count", "severity"], 10)}

## 13. Data Freshness / Lineage / Leakage Status

{md_table(lineage_rows, ["lineage_item", "source_exists", "row_count", "freshness_status", "provider_refresh_executed"], 16)}

## 14. Human-Readable Next-Step Decision

Review the dry-run report for readability and operator usefulness; keep official trading and recommendation outputs prohibited.

## 15. Explicit Prohibition Against Official Trading/Recommendation Output

- DRY_RUN_ONLY=TRUE
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
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)

    read_first = "\n".join([
        f"STAGE_NAME={STAGE_NAME}",
        f"STATUS={status}",
        "READ_FIRST_PURPOSE=Dry-run-only readable daily operator research report generated from V20.42 design.",
        "DRY_RUN_ONLY=TRUE",
        "RESEARCH_ONLY=TRUE",
        "USE_EXISTING_OUTPUTS_ONLY=TRUE",
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
        f"REPORT_DATE={report_date}",
        f"CANDIDATE_RESEARCH_ROWS={len(candidate_rows)}",
        f"SECTION_STATUS_ROWS={len(section_rows)}",
        f"MISSING_REQUIRED_SOURCE_COUNT={len(missing_required)}",
        "",
    ])
    write_text(READ_FIRST, read_first)

    print(status)
    print(f"CANDIDATE_RESEARCH_ROWS={len(candidate_rows)}")
    print(f"READ_FIRST={rel(READ_FIRST)}")
    return 0 if status == PASS_STATUS else 1


if __name__ == "__main__":
    raise SystemExit(main())
