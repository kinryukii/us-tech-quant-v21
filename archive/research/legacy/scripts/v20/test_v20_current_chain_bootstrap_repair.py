from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPAIR = ROOT / "outputs" / "v20" / "repair"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
CONCLUSION = READ_CENTER / "V20_CURRENT_DAILY_CONCLUSION.md"

SUMMARY = REPAIR / "V20_CURRENT_CHAIN_BOOTSTRAP_REPAIR_SUMMARY.md"
STATUS = REPAIR / "V20_CURRENT_CHAIN_BOOTSTRAP_REPAIR_STATUS.csv"
MATRIX = REPAIR / "V20_CURRENT_CHAIN_DEPENDENCY_MATRIX.csv"
LANE_STATUS = REPAIR / "V20_CURRENT_CHAIN_LANE_STATUS.csv"
CURRENT_LANE_STATUS = REPAIR / "V20_CURRENT_DAILY_RESEARCH_LANE_STATUS.csv"
FORWARD_LANE_STATUS = REPAIR / "V20_FORWARD_OUTCOME_VALIDATION_LANE_STATUS.csv"
V55_REPORT = READ_CENTER / "V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER_REPORT.md"
V20_7V_SUMMARY = CONSOLIDATION / "V20_7V_VALIDATION_SUMMARY.csv"
V20_7V_STAGING = CONSOLIDATION / "V20_7V_ACTIVE_MARKET_SOURCE_STAGING.csv"
V20_7V_EXCLUDED = CONSOLIDATION / "V20_7V_EXCLUDED_TICKERS.csv"
V20_7V_SOURCE_AUDIT = CONSOLIDATION / "V20_7V_SOURCE_AUDIT.csv"
V20_7V_DIAGNOSTICS = CONSOLIDATION / "V20_7V_PRECHECK_DIAGNOSTICS.csv"
V20_16_GATE = CONSOLIDATION / "V20_16_GATE_DECISION.csv"
V20_16_DIAGNOSTICS = CONSOLIDATION / "V20_16_GATE_DECISION_DIAGNOSTICS.csv"
V20_16_SOURCE_AUDIT = CONSOLIDATION / "V20_16_SOURCE_AUDIT.csv"
V20_17_GATE = CONSOLIDATION / "V20_17_GATE_DECISION.csv"
V20_17_DIAGNOSTICS = CONSOLIDATION / "V20_17_GATE_DECISION_DIAGNOSTICS.csv"
V20_17_INPUT_PREP = CONSOLIDATION / "V20_17_BACKTEST_INPUT_PREPARATION.csv"
V20_17_BENCHMARK_PREP = CONSOLIDATION / "V20_17_BENCHMARK_PREPARATION.csv"
V20_17_SOURCE_AUDIT = CONSOLIDATION / "V20_17_SOURCE_AUDIT.csv"
POST_REFRESH_AUDIT = CONSOLIDATION / "V20_POST_REFRESH_RECOMPUTE_AUDIT.csv"
POST_REFRESH_STATUS = CONSOLIDATION / "V20_POST_REFRESH_RECOMPUTE_STATUS.csv"
SWEEP_STATUS = CONSOLIDATION / "V20_DOWNSTREAM_REPAIR_SWEEP_STATUS.csv"
SWEEP_AUDIT = CONSOLIDATION / "V20_DOWNSTREAM_REPAIR_SWEEP_AUDIT.csv"
SWEEP_BLOCKERS = CONSOLIDATION / "V20_DOWNSTREAM_REPAIR_SWEEP_BLOCKERS.csv"
V16_YAML = ROOT / "configs" / "v16" / "universe" / "us_full_second_stage_generated.yaml"
V16_STATUS = ROOT / "outputs" / "v16" / "universe" / "V16_SECOND_STAGE_UNIVERSE_REPAIR_STATUS.csv"
FACTOR_PACK = ROOT / "outputs" / "v18" / "factor_pack" / "V18_CURRENT_RAW105_FACTOR_PACK_RANKING.csv"
FACTOR_PACK_STATUS = ROOT / "outputs" / "v18" / "factor_pack" / "V18_CURRENT_RAW105_FACTOR_PACK_RANKING_REPAIR_STATUS.csv"
FACTOR_PACK_AUDIT = ROOT / "outputs" / "v18" / "factor_pack" / "V18_CURRENT_RAW105_FACTOR_PACK_RANKING_SOURCE_AUDIT.csv"
TECH_TIMING = ROOT / "outputs" / "v18" / "technical_timing" / "V18_6A_CURRENT_TECHNICAL_TIMING.csv"
TECH_TIMING_STATUS = ROOT / "outputs" / "v18" / "technical_timing" / "V18_6A_CURRENT_TECHNICAL_TIMING_REPAIR_STATUS.csv"
TECH_TIMING_AUDIT = ROOT / "outputs" / "v18" / "technical_timing" / "V18_6A_CURRENT_TECHNICAL_TIMING_SOURCE_AUDIT.csv"
RANKED_ALIAS = ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_RANKED_CANDIDATES.csv"
RANKED_ALIAS_AUDIT = ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_RANKED_CANDIDATES_ALIAS_AUDIT.csv"
RANKED_ALIAS_STATUS = ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_RANKED_CANDIDATES_ALIAS_STATUS.csv"
FULL_RANKED = ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_FULL_RANKED_CANDIDATES.csv"
FULL_RANKED_AUDIT = ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_FULL_RANKED_CANDIDATES_SOURCE_AUDIT.csv"
FULL_RANKED_STATUS = ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_FULL_RANKED_CANDIDATES_REPAIR_STATUS.csv"
MANUAL_ADDITIONS = ROOT / "state" / "v18" / "universe" / "V18_MANUAL_UNIVERSE_ADDITIONS.csv"
MANUAL_ADDITIONS_STATUS = ROOT / "outputs" / "v18" / "universe" / "V18_MANUAL_UNIVERSE_ADDITIONS_REPAIR_STATUS.csv"
MANUAL_ADDITIONS_AUDIT = ROOT / "outputs" / "v18" / "universe" / "V18_MANUAL_UNIVERSE_ADDITIONS_SOURCE_AUDIT.csv"

PROHIBITED_TRUE_FIELDS = {
    "OFFICIAL_RECOMMENDATION_CREATED",
    "OFFICIAL_RECOMMENDATION_GENERATOR",
    "BUY_SELL_HOLD_INSTRUCTIONS_CREATED",
    "BUY_SELL_TRIM_RECOMMENDATION_CREATED",
    "TRADING_SIGNAL_CREATED",
    "TRADING_SIGNAL_GENERATOR",
    "BROKER_ORDER_SYSTEM_CONNECTED",
    "BROKER_ORDER_PATH_CREATED",
    "BROKER_ORDER_EXECUTION_CODE_CREATED",
    "TRADES_EXECUTED",
    "OFFICIAL_RANKING_MUTATED",
    "OFFICIAL_FACTOR_WEIGHTS_MUTATED",
    "DYNAMIC_WEIGHTING_EXECUTED",
    "DYNAMIC_WEIGHTING_STARTED",
    "DYNAMIC_WEIGHTS_MUTATED",
    "V21_OUTPUTS_CREATED",
    "V19_21_OUTPUTS_CREATED",
}


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def read_csv_fields(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle).fieldnames or [])


def parse_summary(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def assert_no_forbidden_outputs() -> None:
    forbidden_roots = [
        ROOT / "outputs" / "v21",
        ROOT / "outputs" / "v19_21",
        ROOT / "outputs" / "v19" / "V19_21",
    ]
    for path in forbidden_roots:
        assert_true(not path.exists(), f"forbidden output path exists: {path}")


def assert_no_prohibited_true_flags() -> None:
    for path in CONSOLIDATION.glob("V20_*.csv"):
        try:
            rows = read_csv(path)
        except csv.Error:
            continue
        for row in rows:
            for key, value in row.items():
                if clean(key).upper() in PROHIBITED_TRUE_FIELDS:
                    assert_true(clean(value).upper() != "TRUE", f"{path} has prohibited TRUE flag {key}")

    for path in (ROOT / "outputs" / "v20" / "ops").glob("V20_*READ_FIRST*.txt"):
        for line in path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
            separator = "=" if "=" in line else ":" if ":" in line else ""
            if not separator:
                continue
            key, value = line.split(separator, 1)
            if clean(key).upper() in PROHIBITED_TRUE_FIELDS:
                assert_true(clean(value).upper() != "TRUE", f"{path} has prohibited TRUE flag {key}")


def main() -> int:
    assert_true(SUMMARY.exists() and SUMMARY.stat().st_size > 0, "repair summary must exist and be non-empty")
    assert_true(MATRIX.exists() and MATRIX.stat().st_size > 0, "dependency matrix must exist and be non-empty")
    assert_true(STATUS.exists() and STATUS.stat().st_size > 0, "repair status must exist and be non-empty")
    assert_true(LANE_STATUS.exists() and LANE_STATUS.stat().st_size > 0, "lane status must exist and be non-empty")
    assert_true(CURRENT_LANE_STATUS.exists() and CURRENT_LANE_STATUS.stat().st_size > 0, "current daily research lane status must exist and be non-empty")
    assert_true(FORWARD_LANE_STATUS.exists() and FORWARD_LANE_STATUS.stat().st_size > 0, "forward outcome validation lane status must exist and be non-empty")
    assert_true(V16_YAML.exists() and V16_YAML.stat().st_size > 0, "V16 second-stage YAML must exist and be non-empty")
    assert_true(V16_STATUS.exists() and V16_STATUS.stat().st_size > 0, "V16 repair status must exist and be non-empty")
    assert_true(FACTOR_PACK.exists() and FACTOR_PACK.stat().st_size > 0, "V18 current factor pack must exist and be non-empty")
    assert_true(FACTOR_PACK_STATUS.exists() and FACTOR_PACK_STATUS.stat().st_size > 0, "V18 current factor pack repair status must exist and be non-empty")
    assert_true(FACTOR_PACK_AUDIT.exists() and FACTOR_PACK_AUDIT.stat().st_size > 0, "V18 current factor pack source audit must exist and be non-empty")
    assert_true(TECH_TIMING.exists() and TECH_TIMING.stat().st_size > 0, "V18 current technical timing must exist and be non-empty")
    assert_true(TECH_TIMING_STATUS.exists() and TECH_TIMING_STATUS.stat().st_size > 0, "V18 current technical timing repair status must exist and be non-empty")
    assert_true(TECH_TIMING_AUDIT.exists() and TECH_TIMING_AUDIT.stat().st_size > 0, "V18 current technical timing source audit must exist and be non-empty")
    assert_true(RANKED_ALIAS.exists() and RANKED_ALIAS.stat().st_size > 0, "V18 current ranked candidates alias must exist and be non-empty")
    assert_true(RANKED_ALIAS_AUDIT.exists() and RANKED_ALIAS_AUDIT.stat().st_size > 0, "V18 ranked alias audit must exist and be non-empty")
    assert_true(RANKED_ALIAS_STATUS.exists() and RANKED_ALIAS_STATUS.stat().st_size > 0, "V18 ranked alias status must exist and be non-empty")
    assert_true(FULL_RANKED.exists() and FULL_RANKED.stat().st_size > 0, "V18 current full ranked candidates handoff must exist and be non-empty")
    assert_true(FULL_RANKED_AUDIT.exists() and FULL_RANKED_AUDIT.stat().st_size > 0, "V18 current full ranked source audit must exist and be non-empty")
    assert_true(FULL_RANKED_STATUS.exists() and FULL_RANKED_STATUS.stat().st_size > 0, "V18 current full ranked repair status must exist and be non-empty")
    assert_true(MANUAL_ADDITIONS.exists(), "V18 manual universe additions file must exist")
    assert_true(MANUAL_ADDITIONS_STATUS.exists() and MANUAL_ADDITIONS_STATUS.stat().st_size > 0, "V18 manual additions repair status must exist and be non-empty")
    assert_true(MANUAL_ADDITIONS_AUDIT.exists() and MANUAL_ADDITIONS_AUDIT.stat().st_size > 0, "V18 manual additions audit must exist and be non-empty")
    assert_true(V20_7V_SUMMARY.exists() and V20_7V_SUMMARY.stat().st_size > 0, "V20.7V validation summary must exist and be non-empty")
    assert_true(V20_7V_STAGING.exists() and V20_7V_STAGING.stat().st_size > 0, "V20.7V active market source staging must exist and be non-empty")
    assert_true(V20_7V_EXCLUDED.exists() and V20_7V_EXCLUDED.stat().st_size > 0, "V20.7V excluded tickers must exist and be non-empty when rows are quarantined")
    assert_true(V20_7V_SOURCE_AUDIT.exists() and V20_7V_SOURCE_AUDIT.stat().st_size > 0, "V20.7V source audit must exist and be non-empty")
    assert_true(V20_7V_DIAGNOSTICS.exists() and V20_7V_DIAGNOSTICS.stat().st_size > 0, "V20.7V diagnostics must exist and be non-empty")
    assert_true(V20_16_GATE.exists() and V20_16_GATE.stat().st_size > 0, "V20.16 gate decision must exist and be non-empty")
    assert_true(V20_16_DIAGNOSTICS.exists() and V20_16_DIAGNOSTICS.stat().st_size > 0, "V20.16 gate decision diagnostics must exist and be non-empty")
    assert_true(V20_16_SOURCE_AUDIT.exists() and V20_16_SOURCE_AUDIT.stat().st_size > 0, "V20.16 source audit must exist and be non-empty")
    assert_true(V20_17_GATE.exists() and V20_17_GATE.stat().st_size > 0, "V20.17 gate decision must exist and be non-empty")
    assert_true(V20_17_DIAGNOSTICS.exists() and V20_17_DIAGNOSTICS.stat().st_size > 0, "V20.17 gate decision diagnostics must exist and be non-empty")
    assert_true(V20_17_INPUT_PREP.exists() and V20_17_INPUT_PREP.stat().st_size > 0, "V20.17 backtest input preparation must exist and be non-empty")
    assert_true(V20_17_BENCHMARK_PREP.exists() and V20_17_BENCHMARK_PREP.stat().st_size > 0, "V20.17 benchmark preparation must exist and be non-empty")
    assert_true(V20_17_SOURCE_AUDIT.exists() and V20_17_SOURCE_AUDIT.stat().st_size > 0, "V20.17 source audit must exist and be non-empty")
    assert_true(POST_REFRESH_AUDIT.exists() and POST_REFRESH_AUDIT.stat().st_size > 0, "post-refresh recompute audit must exist and be non-empty")
    assert_true(POST_REFRESH_STATUS.exists() and POST_REFRESH_STATUS.stat().st_size > 0, "post-refresh recompute status must exist and be non-empty")
    assert_true(SWEEP_STATUS.exists() and SWEEP_STATUS.stat().st_size > 0, "downstream repair sweep status must exist and be non-empty")
    assert_true(SWEEP_AUDIT.exists() and SWEEP_AUDIT.stat().st_size > 0, "downstream repair sweep audit must exist and be non-empty")
    assert_true(SWEEP_BLOCKERS.exists() and SWEEP_BLOCKERS.stat().st_size > 0, "downstream repair sweep blockers must exist and be non-empty")
    assert_true(CONCLUSION.exists() and CONCLUSION.stat().st_size > 0, "daily conclusion must exist and be non-empty")

    matrix_rows = read_csv(MATRIX)
    status_rows = read_csv(STATUS)
    lane_rows = read_csv(LANE_STATUS)
    current_lane = read_csv(CURRENT_LANE_STATUS)[0]
    forward_lane = read_csv(FORWARD_LANE_STATUS)[0]
    v16_rows = read_csv(V16_STATUS)
    factor_rows = read_csv(FACTOR_PACK)
    factor_status_rows = read_csv(FACTOR_PACK_STATUS)
    tech_rows = read_csv(TECH_TIMING)
    tech_status_rows = read_csv(TECH_TIMING_STATUS)
    alias_rows = read_csv(RANKED_ALIAS)
    alias_audit_rows = read_csv(RANKED_ALIAS_AUDIT)
    alias_status_rows = read_csv(RANKED_ALIAS_STATUS)
    full_rows = read_csv(FULL_RANKED)
    full_audit_rows = read_csv(FULL_RANKED_AUDIT)
    full_status_rows = read_csv(FULL_RANKED_STATUS)
    manual_rows = read_csv(MANUAL_ADDITIONS)
    manual_status_rows = read_csv(MANUAL_ADDITIONS_STATUS)
    v20_7v_rows = read_csv(V20_7V_SUMMARY)
    v20_7v_staging_rows = read_csv(V20_7V_STAGING)
    v20_7v_excluded_rows = read_csv(V20_7V_EXCLUDED)
    v20_7v_diagnostic_rows = read_csv(V20_7V_DIAGNOSTICS)
    v20_16_rows = read_csv(V20_16_GATE)
    v20_16_diag_rows = read_csv(V20_16_DIAGNOSTICS)
    v20_17_rows = read_csv(V20_17_GATE)
    v20_17_benchmark_rows = read_csv(V20_17_BENCHMARK_PREP)
    post_refresh_rows = read_csv(POST_REFRESH_STATUS)
    post_refresh = post_refresh_rows[0]
    assert_true(clean(post_refresh.get("status")) == "PASS_V20_POST_REFRESH_RECOMPUTE_HANDOFF_COMPLETED", "post-refresh recompute handoff must complete when V20.47 is certified")
    if clean(post_refresh.get("v20_47_certification_status")) == "CERTIFIED_CACHE_FALLBACK_HANDOFF":
        assert_true(clean(post_refresh.get("v20_47_fallback_used")) == "TRUE", "certified cache fallback handoff must be explicit")
        assert_true(clean(post_refresh.get("v20_47_fallback_handoff_allowed")) == "TRUE", "certified cache fallback must be audit-approved before post-refresh recompute")
        assert_true(clean(post_refresh.get("v20_47_fallback_source_run_id")), "certified cache fallback must record source run id")
        assert_true(clean(post_refresh.get("v20_47_fallback_source_file")).endswith(".csv"), "certified cache fallback must record source file")
    assert_true(clean(post_refresh.get("v18_factor_pack_recomputed_after_v20_47")) == "TRUE", "factor pack must be recomputed after V20.47")
    assert_true(clean(post_refresh.get("v18_technical_timing_recomputed_after_v20_47")) == "TRUE", "technical timing must be recomputed after V20.47")
    assert_true(clean(post_refresh.get("v18_13b_rerun_after_v20_47")) == "TRUE", "V18.13B must rerun after V20.47")
    assert_true(clean(post_refresh.get("v18_full_ranked_rebuilt_after_v20_47")) == "TRUE", "full ranked candidates must rebuild after V20.47")
    assert_true(clean(post_refresh.get("v20_7v_used_post_refresh_artifacts")) == "TRUE", "V20.7V must use post-refresh artifacts")
    assert_true(clean(post_refresh.get("v20_7v_used_quarantine")) in {"TRUE", "FALSE"}, "post-refresh status must report whether V20.7V used quarantine")
    assert_true("2026-06-12" in clean(post_refresh.get("post_refresh_cache_latest_date_distribution")), "post-refresh cache distribution must include current latest cache date")
    assert_true(matrix_rows, "dependency matrix must have rows")
    assert_true(status_rows, "repair status must have rows")
    assert_true({row.get("lane_name") for row in lane_rows} == {"CURRENT_DAILY_RESEARCH_LANE", "FORWARD_OUTCOME_VALIDATION_LANE"}, "lane status must report current and forward lanes")
    assert_true(clean(current_lane.get("official_promotion_allowed")) == "FALSE", "current lane must not allow official promotion")
    assert_true(clean(current_lane.get("official_recommendation_created")) == "FALSE", "current lane must not create official recommendations")
    assert_true(clean(current_lane.get("weight_mutated")) == "FALSE", "current lane must not mutate weights")
    assert_true(clean(current_lane.get("trade_action_created")) == "FALSE", "current lane must not create trade actions")
    if clean(forward_lane.get("lane_status")) == "PENDING_FORWARD_TARGET_DATES":
        assert_true(clean(forward_lane.get("first_failed_stage")) == "V20.27", "forward pending lane must remain at V20.27")
        assert_true(clean(forward_lane.get("pending_forward_target_dates")) == "TRUE", "forward lane must report pending forward target dates")
        assert_true(clean(forward_lane.get("latest_available_cache_date")) == "2026-06-12", "forward lane must preserve latest available cache date")
        assert_true(clean(forward_lane.get("first_required_target_date")) == "2026-06-13", "forward lane must preserve first required target date")
        assert_true(clean(forward_lane.get("latest_required_target_date")) == "2026-08-11", "forward lane must preserve latest required target date")
        assert_true(clean(forward_lane.get("official_promotion_allowed")) == "FALSE", "pending forward lane must block promotion")
    assert_true(v16_rows[0].get("STATUS") == "PASS_V16_SECOND_STAGE_UNIVERSE_REPAIR", "V16 second-stage repair must pass before V18.13B")
    assert_true(factor_status_rows[0].get("STATUS") == "PASS_V18_CURRENT_RAW105_FACTOR_PACK_REPAIR", "V18 factor pack repair must pass before V18.13B")
    assert_true(tech_status_rows[0].get("STATUS") == "PASS_V18_CURRENT_TECHNICAL_TIMING_REPAIR", "V18 technical timing repair must pass before V18.13B")
    assert_true(alias_status_rows[0].get("alias_status") in {"WARN_ALIAS_CREATED_FROM_PARTIAL_V18_13B", "PASS_ALIAS_CREATED_FROM_FULL_V18_13B"}, "V18 ranked alias status must be explicit")
    assert_true(manual_status_rows[0].get("STATUS") in {"WARN_NO_MANUAL_UNIVERSE_ADDITIONS_EMPTY_FILE_CREATED", "PASS_MANUAL_UNIVERSE_ADDITIONS_FILE_PRESENT"}, "manual additions repair status must be explicit")
    assert_true(any(row.get("stage") in {"V16_SECOND_STAGE_UNIVERSE", "V16_SECOND_STAGE_UNIVERSE_REPAIR"} for row in status_rows), "repair status missing V16 stage")
    assert_true(any(row.get("stage") == "V18_CURRENT_RAW105_FACTOR_PACK_REPAIR" for row in status_rows), "repair status missing V18 factor pack stage")
    assert_true(any(row.get("stage") == "V18_CURRENT_TECHNICAL_TIMING_REPAIR" for row in status_rows), "repair status missing V18 technical timing stage")
    assert_true(any(row.get("stage") == "V18_CURRENT_RANKED_CANDIDATES_ALIAS_REPAIR" for row in status_rows), "repair status missing V18 ranked alias stage")
    assert_true(any(row.get("stage") == "V18_MANUAL_UNIVERSE_ADDITIONS_REPAIR" for row in status_rows), "repair status missing V18 manual additions stage")
    assert_true(any(row.get("stage") == "V18.35D_FULL_RANKED_CANDIDATES_REPAIR" for row in status_rows), "repair status missing V18 full ranked handoff repair stage")
    assert_true(factor_rows, "V18 current factor pack must contain rows")
    assert_true({"ticker", "factor_pack_score", "factor_pack_rank"}.issubset(factor_rows[0]), "V18 current factor pack missing required columns")
    tickers = [clean(row.get("ticker")).upper() for row in factor_rows]
    assert_true(len(tickers) == len(set(tickers)), "V18 current factor pack has duplicate tickers")
    assert_true(tech_rows, "V18 current technical timing must contain rows")
    assert_true({"ticker", "technical_timing_score", "technical_signal", "buy_zone_status", "trend_status"}.issubset(tech_rows[0]), "V18 current technical timing missing required columns")
    tech_tickers = [clean(row.get("ticker")).upper() for row in tech_rows]
    assert_true(len(tech_tickers) == len(set(tech_tickers)), "V18 current technical timing has duplicate tickers")
    assert_true(alias_rows, "V18 current ranked alias must contain rows")
    assert_true({"ticker", "rank", "composite_candidate_score"}.issubset(alias_rows[0]), "V18 current ranked alias missing required columns")
    assert_true(alias_audit_rows[0].get("source_file") == "outputs/v18/candidates/V18_13B_CURRENT_RANKED_CANDIDATES.csv", "alias audit must record V18.13B source")
    if alias_audit_rows[0].get("source_v18_13b_status") == "WARN_V18_13B_PARTIAL_RANK_READY":
        assert_true(alias_audit_rows[0].get("alias_status") == "WARN_ALIAS_CREATED_FROM_PARTIAL_V18_13B", "partial V18.13B must remain WARN alias")
    assert_true(full_rows, "V18 current full ranked handoff must contain rows")
    assert_true({"ticker", "rank", "composite_candidate_score", "latest_price_date", "latest_close"}.issubset(full_rows[0]), "V18 current full ranked handoff missing required columns")
    full_tickers = [clean(row.get("ticker")).upper() for row in full_rows]
    assert_true(len(full_tickers) == len(set(full_tickers)), "V18 current full ranked handoff has duplicate tickers")
    assert_true(full_audit_rows[0].get("source_file") == "outputs/v18/candidates/V18_CURRENT_RANKED_CANDIDATES.csv", "full ranked audit must record current ranked source")
    assert_true(full_status_rows[0].get("fabricated_ticker_rows") == "FALSE", "full ranked repair must not fabricate ticker rows")
    if alias_status_rows[0].get("alias_status") == "WARN_ALIAS_CREATED_FROM_PARTIAL_V18_13B":
        assert_true(full_status_rows[0].get("repair_status") == "WARN_V18_CURRENT_FULL_RANKED_CANDIDATES_FROM_PARTIAL_CURRENT_RANKING", "partial upstream status must remain WARN in full ranked repair")
    expected_manual_columns = {"ticker", "initial_tier", "source_tag", "company_name", "sector", "industry", "note"}
    assert_true(expected_manual_columns.issubset(set(read_csv_fields(MANUAL_ADDITIONS))), "manual additions schema missing required columns")
    if manual_status_rows[0].get("STATUS") == "WARN_NO_MANUAL_UNIVERSE_ADDITIONS_EMPTY_FILE_CREATED":
        assert_true(clean(manual_status_rows[0].get("manual_addition_row_count")) == "0", "empty manual additions repair must report zero rows")
    assert_true(v20_7v_rows, "V20.7V validation summary must have a row")
    v20_7v = v20_7v_rows[0]
    v20_7v_status = clean(v20_7v.get("status"))
    assert_true(v20_7v_status in {"PASS_V20_7V_ACTIVE_MARKET_SOURCE_STAGING_READY", "BLOCKED_V20_7V_PRECHECK_REVIEW_NEEDED"}, f"unexpected V20.7V status: {v20_7v_status}")
    expected_market_date = clean(v20_7v.get("expected_market_date"))
    observed_dist = clean(v20_7v.get("staging_latest_price_date_distribution"))
    missing_core = clean(v20_7v.get("missing_core_field_summary"))
    stale_count = int(clean(v20_7v.get("stale_ticker_count")) or "0")
    missing_price_count = int(clean(v20_7v.get("missing_latest_price_count")) or "0")
    eligible_count = int(clean(v20_7v.get("eligible_row_count")) or "0")
    excluded_count = int(clean(v20_7v.get("excluded_row_count")) or "0")
    assert_true(expected_market_date, "V20.7V must derive an expected market date from current inputs")
    assert_true(observed_dist, "V20.7V must report observed latest_price_date distribution")
    assert_true(eligible_count == len(v20_7v_staging_rows), "V20.7V eligible_row_count must match active staging rows")
    assert_true(excluded_count == len(v20_7v_excluded_rows), "V20.7V excluded_row_count must match excluded ticker rows")
    staging_tickers = {clean(row.get("ticker")).upper() for row in v20_7v_staging_rows}
    excluded_by_ticker = {clean(row.get("ticker")).upper(): row for row in v20_7v_excluded_rows}
    assert_true("BITF" not in staging_tickers, "BITF must not be present in active staging while stale/provider-failed")
    assert_true("TQQQ" not in staging_tickers, "TQQQ must not be present in active staging while missing composite score")
    assert_true("BITF" in excluded_by_ticker, "BITF must be quarantined when provider refresh failed and stale cache remains")
    assert_true("TQQQ" in excluded_by_ticker, "TQQQ must be quarantined when insufficient history prevents scoring")
    assert_true("STALE_PRICE_DATE_OR_PROVIDER_REFRESH_FAILED" in clean(excluded_by_ticker["BITF"].get("exclusion_reason")), "BITF exclusion reason must identify stale/provider failure")
    assert_true("empty_dataframe" in clean(excluded_by_ticker["BITF"].get("provider_failure_reason")), "BITF exclusion must preserve provider failure reason")
    assert_true("MISSING_COMPOSITE_CANDIDATE_SCORE_INSUFFICIENT_HISTORY" in clean(excluded_by_ticker["TQQQ"].get("exclusion_reason")), "TQQQ exclusion reason must identify missing score and insufficient history")
    tqqq_support = clean(excluded_by_ticker["TQQQ"].get("supporting_reason"))
    assert_true("lt_121" in tqqq_support and "price_history_rows_" in tqqq_support, "TQQQ exclusion must include factor insufficient-history reason")
    assert_true("lt_50" in tqqq_support and "price_history_rows_" in tqqq_support, "TQQQ exclusion must include technical insufficient-history reason")
    assert_true(all(clean(row.get("composite_candidate_score")) for row in v20_7v_staging_rows), "Active staging rows must not have missing composite_candidate_score")
    assert_true(all(clean(row.get("latest_price_date")) == expected_market_date for row in v20_7v_staging_rows), "Active staging rows must satisfy latest_price_date gate")
    assert_true(clean(v20_7v.get("no_dummy_price")) == "TRUE", "V20.7V must explicitly report no dummy prices")
    assert_true(clean(v20_7v.get("no_dummy_score")) == "TRUE", "V20.7V must explicitly report no dummy scores")
    assert_true(v20_16_rows and v20_16_diag_rows, "V20.16 gate and diagnostics must have rows")
    v20_16 = v20_16_rows[0]
    assert_true(clean(v20_16.get("consumed_v20_7v_status")) == "PASS_V20_7V_ACTIVE_MARKET_SOURCE_STAGING_READY", "V20.16 must consume current V20.7V PASS status")
    assert_true(clean(v20_16.get("consumed_active_market_source_staging_usable")) == "TRUE", "V20.16 must consume current V20.7V usable flag")
    assert_true(int(clean(v20_16.get("eligible_row_count")) or "0") == len(v20_7v_staging_rows), "V20.16 eligible row count must match current active staging")
    assert_true(clean(v20_16.get("excluded_rows_allowed_by_v20_16")) == "TRUE", "V20.16 must explicitly allow audited V20.7V exclusions within threshold")
    assert_true(clean(v20_16.get("consumed_current_v20_7v_outputs")) == "TRUE", "V20.16 must not consume stale pre-quarantine V20.7V outputs")
    assert_true(clean(v20_16.get("v20_16_gate_decision")) in {"TRUE", "FALSE"}, "V20.16 gate decision must be explicit")
    assert_true(v20_17_rows, "V20.17 gate must have a row")
    v20_17 = v20_17_rows[0]
    assert_true(clean(v20_17.get("consumed_v20_16_status")) == "PASS_V20_16_FACTOR_SCORE_REVIEW_OR_BACKTEST_READINESS_GATE", "V20.17 must consume current V20.16 PASS")
    assert_true(clean(v20_17.get("consumed_v20_7v_status")) == "PASS_V20_7V_ACTIVE_MARKET_SOURCE_STAGING_READY", "V20.17 must consume current V20.7V PASS")
    assert_true(int(clean(v20_17.get("active_staging_row_count")) or "0") == len(v20_7v_staging_rows), "V20.17 active staging count must match current V20.7V active staging")
    assert_true(clean(v20_17.get("consumed_current_v20_7v_active_staging")) == "TRUE", "V20.17 must not consume stale pre-quarantine active staging")
    assert_true(int(clean(v20_17.get("prepared_candidate_input_rows")) or "0") > 0, "V20.17 must prepare candidate input rows when passing")
    assert_true(int(clean(v20_17.get("prepared_benchmark_rows")) or "0") >= 2, "V20.17 must prepare certified benchmark anchor rows")
    assert_true(clean(v20_17.get("outcome_rows_available")) == "0", "V20.17 must not fake outcome rows")
    assert_true(all(clean(row.get("dummy_benchmark_rows_created")) != "TRUE" for row in read_csv(V20_17_INPUT_PREP)), "V20.17 must not create dummy benchmark rows")
    assert_true(all(clean(row.get("benchmark_values_created_now")) == "FALSE" for row in v20_17_benchmark_rows), "V20.17 must not create benchmark values/returns")
    if v20_7v_status == "PASS_V20_7V_ACTIVE_MARKET_SOURCE_STAGING_READY":
        assert_true(stale_count == 0, "V20.7V PASS requires zero stale tickers")
        assert_true(missing_price_count == 0, "V20.7V PASS requires zero missing latest prices")
        assert_true(missing_core in {"", "NONE"}, "V20.7V PASS requires no missing core fields")
        assert_true(observed_dist == f"{expected_market_date}={len(v20_7v_staging_rows)}", "V20.7V PASS requires clean expected market date distribution")
        assert_true(clean(v20_7v.get("active_market_source_staging_usable")) == "TRUE", "V20.7V PASS must mark active staging usable")
    else:
        assert_true(v20_7v_diagnostic_rows, "V20.7V blocked status must produce diagnostics")
        assert_true(stale_count > 0 or missing_price_count > 0 or missing_core not in {"", "NONE"}, "V20.7V blocked status must explain stale, missing price, or missing core fields")

    assert_no_forbidden_outputs()
    assert_no_prohibited_true_flags()

    summary_text = SUMMARY.read_text(encoding="utf-8-sig")
    conclusion_text = CONCLUSION.read_text(encoding="utf-8-sig")
    for token in ["research-only", "no official recommendation", "no broker execution", "final_chain_status"]:
        assert_true(token in conclusion_text.lower(), f"daily conclusion missing safety/status token: {token}")
    for token in [
        "executive status",
        "data freshness / market source",
        "market refresh diagnostics",
        "post-refresh recompute",
        "current ranking",
        "technical timing / buy-zone",
        "research conclusion",
        "remaining blockers",
        "safety",
        "daily_conclusion_mode:",
        "v20.7v status",
        "expected_market_date",
        "observed price date distribution",
        "missing core field summary",
        "provider/cache refresh status",
        "dominant failure reason",
        "stale-data blocker remains",
        "post_refresh_recompute_ran",
        "post_refresh_cache_latest_date_distribution",
        "eligible_row_count",
        "excluded_row_count",
        "excluded ticker examples",
        "v20_7v_used_quarantine",
        "v20.16 gate decision",
        "v20.16 failed condition list",
        "v20.17 gate decision",
        "v20.17 prepared candidate input rows",
        "v20.17 outcome rows available",
    ]:
        assert_true(token in conclusion_text.lower(), f"daily conclusion missing V20.7V diagnostic token: {token}")
    summary = parse_summary(summary_text)
    final_status = clean(summary.get("final_status")).upper()
    assert_true(final_status in {"PASS", "BLOCKED", "PARTIAL_PASS_CURRENT_DAILY_RESEARCH_READY_FORWARD_OUTCOME_PENDING"}, f"unexpected final_status: {final_status}")

    if final_status in {"PASS", "PARTIAL_PASS_CURRENT_DAILY_RESEARCH_READY_FORWARD_OUTCOME_PENDING"}:
        assert_true(V55_REPORT.exists(), "V20.55 report must exist when current lane is ready")
        report_text = V55_REPORT.read_text(encoding="utf-8-sig", errors="ignore")
        assert_true(
            ("PASS_V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER" in report_text)
            or ("WARN_V20_55_RESEARCH_ONLY_READY_PROMOTION_BLOCKED" in report_text),
            "V20.55 report must contain PASS or research-only WARN status when current lane is ready",
        )
    else:
        assert_true(clean(summary.get("first_failed_stage")), "blocked run must include first_failed_stage")
        assert_true(clean(summary.get("blocker_reason")), "blocked run must include blocker_reason")
        assert_true(
            "V18_CURRENT_FULL_RANKED_CANDIDATES.csv missing_required_file" not in clean(summary.get("blocker_reason")),
            "blocked run must move beyond the V18.35D -> V20.7V missing full ranked artifact blocker",
        )

    print("PASS_V20_CURRENT_CHAIN_BOOTSTRAP_REPAIR_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
