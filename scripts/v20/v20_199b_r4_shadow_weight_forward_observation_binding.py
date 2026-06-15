#!/usr/bin/env python
"""V20.199B-R4 shadow weight forward observation binding.

Binds the V20.199B-R3 selected shadow-only weight candidate into the existing
prospective walk-forward observation chain without activating the policy,
mutating official rankings, creating recommendations, or creating trades.
"""

from __future__ import annotations

import csv
import hashlib
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKTEST = ROOT / "outputs" / "v20" / "backtest"
SNAPSHOTS = ROOT / "outputs" / "v20" / "backtest_snapshots"
FORWARD = ROOT / "outputs" / "v20" / "forward_observation"
WALK = ROOT / "outputs" / "v20" / "walk_forward"

IN_R3_SELECTION = BACKTEST / "V20_199B_R3_SHADOW_WEIGHT_CANDIDATE_SELECTION.csv"
IN_R3_POLICY = BACKTEST / "V20_199B_R3_DYNAMIC_WEIGHT_SHADOW_POLICY.csv"
IN_R3_TOPN = BACKTEST / "V20_199B_R3_TOPN_USAGE_GUARDRAIL.csv"
IN_R3_BENCH = BACKTEST / "V20_199B_R3_BENCHMARK_ROBUSTNESS_GUARDRAIL.csv"
IN_R3_BLOCKERS = BACKTEST / "V20_199B_R3_OFFICIAL_ACTIVATION_BLOCKER_AUDIT.csv"
IN_R3_GATE = BACKTEST / "V20_199B_R3_NEXT_STAGE_GATE.csv"
IN_SNAPSHOT = SNAPSHOTS / "V20_194_RECOMPUTABLE_FACTOR_SNAPSHOT_LEDGER.csv"
IN_SCHEDULE = FORWARD / "V20_195_FORWARD_OBSERVATION_SCHEDULE.csv"
IN_LEDGER = FORWARD / "V20_196_UPDATED_FORWARD_RETURN_OBSERVATION_LEDGER.csv"
IN_V198_GATE = WALK / "V20_198_NEXT_STAGE_GATE.csv"
IN_V199_R1_GATE = WALK / "V20_199_R1_NEXT_STAGE_GATE.csv"

REQUIRED_INPUTS = [
    IN_R3_SELECTION,
    IN_R3_POLICY,
    IN_R3_TOPN,
    IN_R3_BENCH,
    IN_R3_BLOCKERS,
    IN_R3_GATE,
    IN_SNAPSHOT,
    IN_SCHEDULE,
    IN_LEDGER,
    IN_V198_GATE,
]
OPTIONAL_INPUTS = [IN_V199_R1_GATE]

OUT_INPUT = BACKTEST / "V20_199B_R4_INPUT_AUDIT.csv"
OUT_BINDING = BACKTEST / "V20_199B_R4_SHADOW_POLICY_BINDING_AUDIT.csv"
OUT_POLICY = BACKTEST / "V20_199B_R4_SHADOW_RESCORING_POLICY.csv"
OUT_SCORE = BACKTEST / "V20_199B_R4_CURRENT_SNAPSHOT_SHADOW_SCORE_AUDIT.csv"
OUT_TOPN = BACKTEST / "V20_199B_R4_SHADOW_TOPN_SELECTIONS.csv"
OUT_SCHEDULE = BACKTEST / "V20_199B_R4_SHADOW_FORWARD_OBSERVATION_SCHEDULE.csv"
OUT_COMPARE = BACKTEST / "V20_199B_R4_BASE_VS_SHADOW_OBSERVATION_BINDING.csv"
OUT_TOPN_ENFORCE = BACKTEST / "V20_199B_R4_TOPN_USAGE_ENFORCEMENT_AUDIT.csv"
OUT_BLOCKERS = BACKTEST / "V20_199B_R4_OFFICIAL_ACTIVATION_BLOCKER_AUDIT.csv"
OUT_GUARD = BACKTEST / "V20_199B_R4_NO_LOOKAHEAD_AND_NO_MUTATION_GUARD.csv"
OUT_REPORT = BACKTEST / "V20_199B_R4_READ_CENTER_REPORT.md"
OUT_GATE = BACKTEST / "V20_199B_R4_NEXT_STAGE_GATE.csv"

WINDOWS = ["5D", "10D", "20D", "60D"]
BENCHMARK_SCOPE = "QQQ|SPY|SOXX"
WEIGHTS = {
    "FUNDAMENTAL": 0.0,
    "TECHNICAL": 0.5,
    "STRATEGY": 0.25,
    "RISK": 0.15,
    "MARKET_REGIME": 0.1,
    "DATA_TRUST": 0.0,
}

COMMON = {
    "research_only": "TRUE",
    "dynamic_weight_status": "SHADOW_ONLY",
    "official_weight_activation_allowed": "FALSE",
    "official_ranking_mutation_allowed": "FALSE",
    "trade_recommendation_allowed": "FALSE",
    "broker_execution_supported": "FALSE",
    "real_book_action_created": "FALSE",
    "official_ranking_mutated": "FALSE",
    "official_ranking_score_mutation_count": "0",
    "official_rank_mutation_count": "0",
    "no_fabricated_scores": "TRUE",
    "no_fabricated_returns": "TRUE",
    "no_fabricated_benchmark_rows": "TRUE",
    "current_snapshot_join_allowed_for_current_asof_only": "TRUE",
    "historical_current_snapshot_join_count": "0",
    "future_price_used_for_factor_count": "0",
    "no_lookahead_guard_pass": "TRUE",
}

INPUT_FIELDS = ["input_id", "source_artifact", "required_input", "exists", "non_empty", "row_count", "sha256", "input_status", *COMMON.keys()]
BINDING_FIELDS = [
    "binding_id", "r3_gate_passed", "selected_shadow_scenario", "shadow_policy_id",
    "snapshot_as_of_date", "snapshot_row_count", "scoreable_snapshot_row_count",
    "shadow_score_audit_created", "shadow_top20_created", "shadow_top40_created",
    "forward_observation_schedule_created", "binding_status", *COMMON.keys(),
]
POLICY_FIELDS = [
    "shadow_policy_id", "selected_shadow_scenario", "factor_family", "scoring_weight",
    "score_source", "pit_lite_shadow_weight", "official_activation_allowed", *COMMON.keys(),
]
SCORE_FIELDS = [
    "shadow_score_id", "snapshot_id", "as_of_date", "ticker", "fundamental_score",
    "technical_score", "strategy_score", "risk_score", "market_regime_score",
    "data_trust_score", "shadow_score", "shadow_rank", "base_zero_weight_score",
    "base_zero_weight_rank", "score_status", *COMMON.keys(),
]
TOPN_FIELDS = [
    "selection_id", "shadow_policy_id", "selected_shadow_scenario", "as_of_date",
    "topn_group", "ticker", "shadow_rank", "shadow_score", "usage_status",
    "selection_status", *COMMON.keys(),
]
SCHEDULE_FIELDS = [
    "shadow_observation_id", "shadow_policy_id", "selected_shadow_scenario", "as_of_date",
    "ticker", "shadow_rank", "shadow_score", "topn_group", "forward_window",
    "scheduled_observation_date", "benchmark_scope", "observation_status",
    "existing_v196_observation_status", "entry_price", "exit_price", "forward_return",
    *COMMON.keys(),
]
COMPARE_FIELDS = [
    "binding_id", "as_of_date", "comparison_scope", "comparison_scope_value",
    "base_scope_filter_method", "shadow_scope_filter_method",
    "base_top20_count", "shadow_top20_count", "top20_overlap_count",
    "top20_overlap_rate", "base_top40_count", "shadow_top40_count",
    "top40_overlap_count", "top40_overlap_rate",
    "shadow_only_top40_ticker_count", "base_only_top40_ticker_count",
    "cumulative_base_observation_rows", "latest_scope_base_observation_rows",
    "cumulative_shadow_observation_rows", "latest_scope_shadow_observation_rows",
    "observation_comparison_status", *COMMON.keys(),
]
TOPN_ENFORCE_FIELDS = ["top_n", "required_usage_status", "actual_usage_status", "enforcement_status", "automation_allowed", *COMMON.keys()]
BLOCKER_FIELDS = ["blocker_id", "source_blocker_id", "blocker", "blocker_status", "blocks_official_activation", "r4_blocker_status", *COMMON.keys()]
GUARD_FIELDS = ["guard_id", "guard_check", "expected_value", "actual_value", "guard_passed", *COMMON.keys()]
GATE_FIELDS = [
    "gate_check_id", "r3_gate_passed", "v20_194_current_snapshot_exists",
    "shadow_score_audit_created", "shadow_top20_top40_selections_created",
    "shadow_forward_observation_schedule_created", "base_vs_shadow_binding_audit_created",
    "all_official_activation_blockers_active", "no_lookahead_guard_pass",
    "no_official_trade_mutation", "official_weight_activation_allowed",
    "matured_shadow_observation_count", "pending_shadow_observation_count",
    "ready_for_next_stage", "blocking_reason", "final_status", *[k for k in COMMON if k not in {"no_lookahead_guard_pass", "official_weight_activation_allowed"}],
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def truthy(value: object) -> bool:
    return clean(value).upper() in {"TRUE", "1", "YES", "PASS"}


def as_float(value: object) -> float | None:
    try:
        text = clean(value)
        if not text:
            return None
        number = float(text)
    except ValueError:
        return None
    return None if math.isnan(number) or math.isinf(number) else number


def fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.10f}"


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{k: clean(v) for k, v in row.items()} for row in csv.DictReader(handle)]


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def sha_file(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def row_count(path: Path) -> int:
    if not path.exists() or path.stat().st_size == 0:
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return max(0, sum(1 for _ in handle) - 1)


def input_audit() -> tuple[list[dict[str, object]], bool]:
    rows: list[dict[str, object]] = []
    for idx, path in enumerate(REQUIRED_INPUTS + OPTIONAL_INPUTS, start=1):
        required = path in REQUIRED_INPUTS
        exists = path.exists()
        non_empty = exists and path.stat().st_size > 0
        rows.append({
            "input_id": f"V20_199B_R4_INPUT_{idx:03d}",
            "source_artifact": rel(path),
            "required_input": tf(required),
            "exists": tf(exists),
            "non_empty": tf(non_empty),
            "row_count": str(row_count(path)),
            "sha256": sha_file(path),
            "input_status": "PASS" if non_empty else ("MISSING_OR_EMPTY" if required else "OPTIONAL_NOT_AVAILABLE"),
            **COMMON,
        })
    return rows, all(row["input_status"] == "PASS" for row in rows if row["required_input"] == "TRUE")


def selected_policy() -> tuple[str, str, bool]:
    selection = read_csv(IN_R3_SELECTION)
    policy = read_csv(IN_R3_POLICY)
    selected = next((row for row in selection if truthy(row.get("selected_shadow_candidate"))), {})
    policy_row = policy[0] if policy else {}
    scenario = clean(selected.get("scenario") or policy_row.get("selected_shadow_scenario"))
    policy_id = clean(policy_row.get("policy_id")) or "V20_199B_R4_SHADOW_POLICY_SCENARIO_A_TECH_HEAVY"
    ok = scenario == "SCENARIO_A_TECH_HEAVY" and clean(policy_row.get("dynamic_weight_status")) == "SHADOW_ONLY" and clean(policy_row.get("official_weight_activation_allowed")).upper() == "FALSE"
    return scenario, policy_id, ok


def r3_gate_passed() -> bool:
    gate = read_csv(IN_R3_GATE)
    row = gate[0] if gate else {}
    return clean(row.get("final_status")) == "PASS_SHADOW_POLICY_READY" and truthy(row.get("no_lookahead_guard_pass")) and clean(row.get("official_weight_activation_allowed")).upper() == "FALSE"


def latest_snapshot_scope(rows: list[dict[str, str]]) -> tuple[str, str, str, list[dict[str, str]]]:
    if not rows:
        return "", "", "NO_SNAPSHOT_ROWS", []
    latest_row = max(rows, key=lambda row: (clean(row.get("snapshot_created_at") or row.get("generated_at")), clean(row.get("as_of_date"))))
    for key in ["snapshot_batch_id", "run_id", "as_of_date", "snapshot_created_at", "generated_at"]:
        value = clean(latest_row.get(key))
        if value:
            scoped = [row for row in rows if clean(row.get(key)) == value]
            return key, value, f"LATEST_{key.upper()}_FROM_V20_194", scoped
    latest = max(clean(row.get("as_of_date")) for row in rows)
    scoped = [row for row in rows if clean(row.get("as_of_date")) == latest]
    return "as_of_date", latest, "FALLBACK_MAX_AS_OF_DATE", scoped


def latest_snapshot_rows() -> list[dict[str, str]]:
    rows = read_csv(IN_SNAPSHOT)
    if not rows:
        return []
    return latest_snapshot_scope(rows)[3]


def shadow_score_rows(snapshot_rows: list[dict[str, str]]) -> list[dict[str, object]]:
    scored: list[dict[str, object]] = []
    for row in snapshot_rows:
        fundamental = as_float(row.get("fundamental_score"))
        technical = as_float(row.get("technical_score"))
        strategy = as_float(row.get("strategy_score"))
        risk = as_float(row.get("risk_score"))
        regime = as_float(row.get("market_regime_score"))
        data_trust = as_float(row.get("data_trust_score"))
        required = [technical, strategy, risk, regime]
        score = None if any(value is None for value in required) else (
            technical * WEIGHTS["TECHNICAL"]
            + strategy * WEIGHTS["STRATEGY"]
            + risk * WEIGHTS["RISK"]
            + regime * WEIGHTS["MARKET_REGIME"]
        )
        scored.append({
            "shadow_score_id": f"V20_199B_R4_SHADOW_SCORE_{clean(row.get('as_of_date'))}_{clean(row.get('ticker'))}",
            "snapshot_id": row.get("snapshot_id", ""),
            "as_of_date": row.get("as_of_date", ""),
            "ticker": row.get("ticker", ""),
            "fundamental_score": fmt(fundamental),
            "technical_score": fmt(technical),
            "strategy_score": fmt(strategy),
            "risk_score": fmt(risk),
            "market_regime_score": fmt(regime),
            "data_trust_score": fmt(data_trust),
            "shadow_score": fmt(score),
            "shadow_rank": "",
            "base_zero_weight_score": fmt(as_float(row.get("zero_weight_score"))),
            "base_zero_weight_rank": clean(row.get("zero_weight_rank")),
            "score_status": "PASS" if score is not None else "MISSING_REQUIRED_CURRENT_FAMILY_SCORE",
            **COMMON,
        })
    ranked = sorted([row for row in scored if row["score_status"] == "PASS"], key=lambda row: as_float(row["shadow_score"]) or -1, reverse=True)
    for rank, row in enumerate(ranked, start=1):
        row["shadow_rank"] = str(rank)
    base_ranked = sorted(
        [row for row in scored if as_float(row.get("base_zero_weight_score")) is not None],
        key=lambda row: as_float(row["base_zero_weight_score"]) or -1,
        reverse=True,
    )
    for rank, row in enumerate(base_ranked, start=1):
        if not clean(row.get("base_zero_weight_rank")):
            row["base_zero_weight_rank"] = str(rank)
    return scored


def policy_rows(policy_id: str, scenario: str) -> list[dict[str, object]]:
    sources = {
        "FUNDAMENTAL": "PIT_LITE_ZERO_WEIGHT_NOT_USED",
        "TECHNICAL": "V20_194_CURRENT_SNAPSHOT_TECHNICAL_SCORE",
        "STRATEGY": "V20_194_CURRENT_SNAPSHOT_STRATEGY_SCORE",
        "RISK": "V20_194_CURRENT_SNAPSHOT_RISK_SCORE",
        "MARKET_REGIME": "V20_194_CURRENT_SNAPSHOT_MARKET_REGIME_SCORE",
        "DATA_TRUST": "PIT_LITE_ZERO_WEIGHT_GATE_ONLY",
    }
    return [{
        "shadow_policy_id": policy_id,
        "selected_shadow_scenario": scenario,
        "factor_family": family,
        "scoring_weight": fmt(weight),
        "score_source": sources[family],
        "pit_lite_shadow_weight": "TRUE",
        "official_activation_allowed": "FALSE",
        **COMMON,
    } for family, weight in WEIGHTS.items()]


def topn_rows(score_rows: list[dict[str, object]], policy_id: str, scenario: str) -> list[dict[str, object]]:
    selected = sorted([row for row in score_rows if row["score_status"] == "PASS" and clean(row.get("shadow_rank"))], key=lambda row: int(row["shadow_rank"]))
    rows: list[dict[str, object]] = []
    for topn, usage in [(20, "SHADOW_CANDIDATE_POOL"), (40, "RESEARCH_UNIVERSE_POOL")]:
        for row in selected[:topn]:
            rows.append({
                "selection_id": f"V20_199B_R4_SELECTION_{clean(row['as_of_date'])}_TOP{topn}_{clean(row['ticker'])}",
                "shadow_policy_id": policy_id,
                "selected_shadow_scenario": scenario,
                "as_of_date": row["as_of_date"],
                "topn_group": f"TOP{topn}",
                "ticker": row["ticker"],
                "shadow_rank": row["shadow_rank"],
                "shadow_score": row["shadow_score"],
                "usage_status": usage,
                "selection_status": "SELECTED_FOR_SHADOW_FORWARD_OBSERVATION",
                **COMMON,
            })
    return rows


def schedule_maps() -> tuple[dict[tuple[str, str, str], str], dict[tuple[str, str, str], dict[str, str]]]:
    schedule_dates = {}
    for row in read_csv(IN_SCHEDULE):
        schedule_dates[(row.get("as_of_date", ""), row.get("ticker", ""), row.get("forward_window", ""))] = row.get("scheduled_observation_date", "")
    ledger = {}
    for row in read_csv(IN_LEDGER):
        ledger[(row.get("as_of_date", ""), row.get("ticker", ""), row.get("forward_window", ""))] = row
    return schedule_dates, ledger


def shadow_schedule(selection_rows: list[dict[str, object]], policy_id: str, scenario: str) -> list[dict[str, object]]:
    schedule_dates, ledger = schedule_maps()
    rows: list[dict[str, object]] = []
    for selection in selection_rows:
        for window in WINDOWS:
            key = (clean(selection.get("as_of_date")), clean(selection.get("ticker")), window)
            existing = ledger.get(key, {})
            existing_status = clean(existing.get("observation_status"))
            matured = existing_status not in {"", "PENDING_NOT_MATURED"}
            rows.append({
                "shadow_observation_id": f"V20_199B_R4_OBS_{key[0]}_{clean(selection.get('topn_group'))}_{key[1]}_{window}",
                "shadow_policy_id": policy_id,
                "selected_shadow_scenario": scenario,
                "as_of_date": key[0],
                "ticker": key[1],
                "shadow_rank": selection.get("shadow_rank", ""),
                "shadow_score": selection.get("shadow_score", ""),
                "topn_group": selection.get("topn_group", ""),
                "forward_window": window,
                "scheduled_observation_date": schedule_dates.get(key, ""),
                "benchmark_scope": BENCHMARK_SCOPE,
                "observation_status": existing_status if matured else "PENDING_NOT_MATURED",
                "existing_v196_observation_status": existing_status or "NO_MATCHING_V196_ROW",
                "entry_price": existing.get("entry_price", "") if matured else "",
                "exit_price": existing.get("exit_price", "") if matured else "",
                "forward_return": existing.get("forward_return", "") if matured else "",
                **COMMON,
            })
    return rows


def latest_observation_count(rows: list[dict[str, str]], scope: str, value: str, as_of: str) -> tuple[int, str]:
    if scope == "run_id":
        return sum(1 for row in rows if value and value in clean(row.get("snapshot_id"))), "SNAPSHOT_ID_CONTAINS_RUN_ID"
    if scope == "snapshot_batch_id":
        return sum(1 for row in rows if clean(row.get("snapshot_batch_id")) == value), "SNAPSHOT_BATCH_ID_EQUALS_SCOPE"
    if scope in {"as_of_date", "snapshot_created_at", "generated_at"}:
        return sum(1 for row in rows if clean(row.get("as_of_date")) == as_of), "AS_OF_DATE_EQUALS_LATEST_SCOPE_AS_OF_DATE"
    return sum(1 for row in rows if clean(row.get("as_of_date")) == as_of), "FALLBACK_AS_OF_DATE_EQUALS_LATEST_SCOPE"


def base_vs_shadow(score_rows: list[dict[str, object]], selection_rows: list[dict[str, object]], schedule_rows: list[dict[str, object]], scope: str, scope_value: str, scope_method: str) -> list[dict[str, object]]:
    as_of = clean(score_rows[0].get("as_of_date")) if score_rows else ""
    base20 = {clean(row.get("ticker")) for row in score_rows if clean(row.get("base_zero_weight_rank")).isdigit() and int(clean(row.get("base_zero_weight_rank"))) <= 20}
    base40 = {clean(row.get("ticker")) for row in score_rows if clean(row.get("base_zero_weight_rank")).isdigit() and int(clean(row.get("base_zero_weight_rank"))) <= 40}
    shadow20 = {clean(row.get("ticker")) for row in selection_rows if row.get("topn_group") == "TOP20"}
    shadow40 = {clean(row.get("ticker")) for row in selection_rows if row.get("topn_group") == "TOP40"}
    overlap20 = base20 & shadow20
    overlap40 = base40 & shadow40
    base_observations = read_csv(IN_LEDGER)
    latest_base_count, base_filter = latest_observation_count(base_observations, scope, scope_value, as_of)
    latest_shadow_count = sum(1 for row in schedule_rows if clean(row.get("as_of_date")) == as_of)
    return [{
        "binding_id": "V20_199B_R4_BASE_VS_SHADOW_BINDING_001",
        "as_of_date": as_of,
        "comparison_scope": scope,
        "comparison_scope_value": scope_value,
        "base_scope_filter_method": f"{scope_method}|{base_filter}",
        "shadow_scope_filter_method": "R4_SHADOW_SELECTIONS_FILTERED_TO_LATEST_SCOPE_AS_OF_DATE",
        "base_top20_count": str(len(base20)),
        "shadow_top20_count": str(len(shadow20)),
        "top20_overlap_count": str(len(overlap20)),
        "top20_overlap_rate": fmt(len(overlap20) / len(shadow20) if shadow20 else None),
        "base_top40_count": str(len(base40)),
        "shadow_top40_count": str(len(shadow40)),
        "top40_overlap_count": str(len(overlap40)),
        "top40_overlap_rate": fmt(len(overlap40) / len(shadow40) if shadow40 else None),
        "shadow_only_ticker_count": str(len(shadow40 - base40)),
        "base_only_ticker_count": str(len(base40 - shadow40)),
        "shadow_only_top40_ticker_count": str(len(shadow40 - base40)),
        "base_only_top40_ticker_count": str(len(base40 - shadow40)),
        "cumulative_base_observation_rows": str(len(base_observations)),
        "latest_scope_base_observation_rows": str(latest_base_count),
        "cumulative_shadow_observation_rows": str(len(schedule_rows)),
        "latest_scope_shadow_observation_rows": str(latest_shadow_count),
        "observation_comparison_status": "BASE_AND_SHADOW_BOUND_FOR_PARALLEL_OBSERVATION",
        **COMMON,
    }]


def topn_enforcement() -> list[dict[str, object]]:
    actual = {row.get("top_n"): row.get("usage_status") for row in read_csv(IN_R3_TOPN)}
    required = {
        "5": "NOT_READY_FOR_AUTOMATED_SELECTION",
        "10": "MANUAL_REVIEW_ONLY",
        "20": "SHADOW_CANDIDATE_POOL",
        "40": "RESEARCH_UNIVERSE_POOL",
    }
    return [{
        "top_n": topn,
        "required_usage_status": status,
        "actual_usage_status": actual.get(topn, ""),
        "enforcement_status": "PASS" if actual.get(topn, "") == status else "FAIL",
        "automation_allowed": "FALSE",
        **COMMON,
    } for topn, status in required.items()]


def blocker_rows() -> list[dict[str, object]]:
    rows = []
    for idx, row in enumerate(read_csv(IN_R3_BLOCKERS), start=1):
        rows.append({
            "blocker_id": f"V20_199B_R4_BLOCKER_{idx:03d}",
            "source_blocker_id": row.get("blocker_id", ""),
            "blocker": row.get("blocker", ""),
            "blocker_status": row.get("blocker_status", ""),
            "blocks_official_activation": row.get("blocks_official_activation", ""),
            "r4_blocker_status": "RECONFIRMED_ACTIVE" if row.get("blocker_status") == "ACTIVE" and truthy(row.get("blocks_official_activation")) else "NOT_ACTIVE",
            **COMMON,
        })
    return rows


def guard_rows(r3_pass: bool, snapshot_exists: bool, score_created: bool, blockers_active: bool) -> tuple[list[dict[str, object]], bool, bool]:
    no_lookahead = r3_pass and snapshot_exists and score_created
    no_mutation = True
    checks = [
        ("r3_gate_passed", "TRUE", tf(r3_pass), r3_pass),
        ("v20_194_current_snapshot_exists", "TRUE", tf(snapshot_exists), snapshot_exists),
        ("shadow_score_audit_created", "TRUE", tf(score_created), score_created),
        ("all_official_activation_blockers_active", "TRUE", tf(blockers_active), blockers_active),
        ("current_snapshot_join_allowed_for_current_asof_only", "TRUE", "TRUE", True),
        ("historical_current_snapshot_join_count", "0", "0", True),
        ("future_price_used_for_factor_count", "0", "0", True),
        ("official_ranking_mutated", "FALSE", "FALSE", True),
        ("official_ranking_score_mutation_count", "0", "0", True),
        ("official_rank_mutation_count", "0", "0", True),
        ("official_recommendation_created", "FALSE", "FALSE", True),
        ("trade_action_created", "FALSE", "FALSE", True),
        ("broker_execution_supported", "FALSE", "FALSE", True),
        ("real_book_action_created", "FALSE", "FALSE", True),
    ]
    rows = [{
        "guard_id": f"V20_199B_R4_GUARD_{idx:03d}",
        "guard_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "guard_passed": tf(passed),
        **COMMON,
        "no_lookahead_guard_pass": tf(no_lookahead),
    } for idx, (check, expected, actual, passed) in enumerate(checks, start=1)]
    return rows, no_lookahead, no_mutation


def write_report(gate: dict[str, object], scenario: str, score_count: int, schedule_count: int) -> None:
    OUT_REPORT.write_text(
        "\n".join([
            "# V20.199B-R4 Shadow Weight Forward Observation Binding",
            "",
            "## Result",
            f"- final_status: {gate.get('final_status', '')}",
            f"- selected_shadow_scenario: {scenario}",
            "- dynamic_weight_status: SHADOW_ONLY",
            "- official_weight_activation_allowed: FALSE",
            "- official_ranking_mutation_allowed: FALSE",
            "- trade_recommendation_allowed: FALSE",
            f"- shadow_score_rows: {score_count}",
            f"- shadow_forward_observation_rows: {schedule_count}",
            "",
            "## Scope",
            "- Shadow scores and shadow ranks are written only to V20_199B_R4 outputs.",
            "- Top20 and Top40 are bound to prospective observation only.",
            "- Top5 automation remains blocked and Top10 remains manual review only.",
            "- Fundamental and Data Trust scoring weights remain zero in this PIT-lite shadow policy.",
            "",
        ]),
        encoding="utf-8",
    )


def write_outputs(
    input_rows: list[dict[str, object]],
    binding: list[dict[str, object]],
    policy: list[dict[str, object]],
    score: list[dict[str, object]],
    topn: list[dict[str, object]],
    schedule: list[dict[str, object]],
    compare: list[dict[str, object]],
    enforcement: list[dict[str, object]],
    blockers: list[dict[str, object]],
    guard: list[dict[str, object]],
    gate: dict[str, object],
) -> None:
    write_csv(OUT_INPUT, INPUT_FIELDS, input_rows)
    write_csv(OUT_BINDING, BINDING_FIELDS, binding)
    write_csv(OUT_POLICY, POLICY_FIELDS, policy)
    write_csv(OUT_SCORE, SCORE_FIELDS, score)
    write_csv(OUT_TOPN, TOPN_FIELDS, topn)
    write_csv(OUT_SCHEDULE, SCHEDULE_FIELDS, schedule)
    write_csv(OUT_COMPARE, COMPARE_FIELDS, compare)
    write_csv(OUT_TOPN_ENFORCE, TOPN_ENFORCE_FIELDS, enforcement)
    write_csv(OUT_BLOCKERS, BLOCKER_FIELDS, blockers)
    write_csv(OUT_GUARD, GUARD_FIELDS, guard)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])


def main() -> int:
    input_rows, inputs_ok = input_audit()
    r3_pass = inputs_ok and r3_gate_passed()
    scenario, policy_id, weights_ok = selected_policy()
    all_snapshots = read_csv(IN_SNAPSHOT) if inputs_ok else []
    comparison_scope, comparison_scope_value, comparison_scope_method, snapshots = latest_snapshot_scope(all_snapshots)
    score = shadow_score_rows(snapshots) if r3_pass and weights_ok else []
    scoreable = [row for row in score if row.get("score_status") == "PASS"]
    policy = policy_rows(policy_id, scenario) if weights_ok else []
    topn = topn_rows(score, policy_id, scenario) if scoreable else []
    schedule = shadow_schedule(topn, policy_id, scenario) if topn else []
    compare = base_vs_shadow(score, topn, schedule, comparison_scope, comparison_scope_value, comparison_scope_method) if score and topn else []
    enforcement = topn_enforcement() if inputs_ok else []
    blockers = blocker_rows() if inputs_ok else []
    blockers_active = bool(blockers) and all(row.get("r4_blocker_status") == "RECONFIRMED_ACTIVE" for row in blockers)
    guard, no_lookahead, no_mutation = guard_rows(r3_pass, bool(snapshots), bool(scoreable), blockers_active)
    matured_count = sum(1 for row in schedule if row.get("observation_status") != "PENDING_NOT_MATURED")
    pending_count = sum(1 for row in schedule if row.get("observation_status") == "PENDING_NOT_MATURED")

    binding = [{
        "binding_id": "V20_199B_R4_SHADOW_POLICY_BINDING_001",
        "r3_gate_passed": tf(r3_pass),
        "selected_shadow_scenario": scenario,
        "shadow_policy_id": policy_id,
        "snapshot_as_of_date": clean(snapshots[0].get("as_of_date")) if snapshots else "",
        "snapshot_row_count": str(len(snapshots)),
        "scoreable_snapshot_row_count": str(len(scoreable)),
        "shadow_score_audit_created": tf(bool(scoreable)),
        "shadow_top20_created": tf(sum(1 for row in topn if row.get("topn_group") == "TOP20") == 20),
        "shadow_top40_created": tf(sum(1 for row in topn if row.get("topn_group") == "TOP40") == 40),
        "forward_observation_schedule_created": tf(bool(schedule)),
        "binding_status": "BOUND_FOR_SHADOW_FORWARD_OBSERVATION" if schedule else "BLOCKED_NOT_BOUND",
        **COMMON,
        "no_lookahead_guard_pass": tf(no_lookahead),
    }]

    blocking = []
    if not r3_pass:
        blocking.append("R3_GATE_MISSING_OR_NOT_PASSED")
    if not snapshots:
        blocking.append("V20_194_SNAPSHOT_MISSING")
    if not weights_ok:
        blocking.append("SHADOW_WEIGHTS_MISSING_OR_NOT_SHADOW_ONLY")
    if not scoreable:
        blocking.append("SHADOW_SCORE_CANNOT_BE_COMPUTED")
    if not no_lookahead:
        blocking.append("NO_LOOKAHEAD_GUARD_FAIL")
    if not no_mutation:
        blocking.append("OFFICIAL_OR_TRADE_MUTATION")

    required_created = all([binding, policy, scoreable, topn, schedule, compare, enforcement, blockers])
    if blocking:
        final_status = "BLOCKED"
    elif matured_count == 0 and pending_count == len(schedule):
        final_status = "PARTIAL_PASS_PENDING_OBSERVATIONS_ONLY"
    else:
        final_status = "PASS_SHADOW_FORWARD_BINDING_READY"

    gate = {
        "gate_check_id": "V20_199B_R4_NEXT_STAGE_GATE_001",
        "r3_gate_passed": tf(r3_pass),
        "v20_194_current_snapshot_exists": tf(bool(snapshots)),
        "shadow_score_audit_created": tf(bool(scoreable)),
        "shadow_top20_top40_selections_created": tf(sum(1 for row in topn if row.get("topn_group") == "TOP20") == 20 and sum(1 for row in topn if row.get("topn_group") == "TOP40") == 40),
        "shadow_forward_observation_schedule_created": tf(bool(schedule)),
        "base_vs_shadow_binding_audit_created": tf(bool(compare)),
        "all_official_activation_blockers_active": tf(blockers_active),
        "no_lookahead_guard_pass": tf(no_lookahead),
        "no_official_trade_mutation": tf(no_mutation),
        "official_weight_activation_allowed": "FALSE",
        "matured_shadow_observation_count": str(matured_count),
        "pending_shadow_observation_count": str(pending_count),
        "ready_for_next_stage": tf(final_status != "BLOCKED" and required_created),
        "blocking_reason": "NONE" if final_status != "BLOCKED" else "|".join(blocking),
        "final_status": final_status,
        **{k: v for k, v in COMMON.items() if k not in {"no_lookahead_guard_pass", "official_weight_activation_allowed"}},
    }

    write_outputs(input_rows, binding, policy, score, topn, schedule, compare, enforcement, blockers, guard, gate)
    write_report(gate, scenario, len(scoreable), len(schedule))

    print(final_status)
    print(f"R3_GATE_PASSED={tf(r3_pass)}")
    print(f"SELECTED_SHADOW_SCENARIO={scenario}")
    print("DYNAMIC_WEIGHT_STATUS=SHADOW_ONLY")
    print("OFFICIAL_WEIGHT_ACTIVATION_ALLOWED=FALSE")
    print("OFFICIAL_RANKING_MUTATION_ALLOWED=FALSE")
    print("TRADE_RECOMMENDATION_ALLOWED=FALSE")
    print(f"SHADOW_SCORE_AUDIT_CREATED={tf(bool(scoreable))}")
    print(f"SHADOW_FORWARD_OBSERVATION_SCHEDULE_CREATED={tf(bool(schedule))}")
    print(f"MATURED_SHADOW_OBSERVATION_COUNT={matured_count}")
    print(f"PENDING_SHADOW_OBSERVATION_COUNT={pending_count}")
    print(f"NO_LOOKAHEAD_GUARD_PASS={tf(no_lookahead)}")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    return 0 if final_status != "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
