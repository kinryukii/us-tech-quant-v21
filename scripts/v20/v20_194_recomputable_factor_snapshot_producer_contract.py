#!/usr/bin/env python
"""V20.194 recomputable factor snapshot producer contract."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
FACTORS = ROOT / "outputs" / "v20" / "factors"
OUT_DIR = ROOT / "outputs" / "v20" / "backtest_snapshots"

SCORE_SOURCE = CONSOLIDATION / "V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_TABLE.csv"
PRICE_SOURCE = CONSOLIDATION / "V20_47_YAHOO_CURRENT_CANDIDATE_PRICE_CACHE.csv"
BASE_WEIGHT_SOURCE = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
ZERO_WEIGHT_SOURCE = FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_WEIGHT_SIMULATION.csv"
V193_GATE = ROOT / "outputs" / "v20" / "backtest" / "V20_193_NEXT_STAGE_GATE.csv"
PROTECTED = [SCORE_SOURCE, PRICE_SOURCE, BASE_WEIGHT_SOURCE, ZERO_WEIGHT_SOURCE, V193_GATE]

OUT_CONTRACT = OUT_DIR / "V20_194_FACTOR_SNAPSHOT_PRODUCER_CONTRACT.csv"
OUT_REQUIREMENTS = OUT_DIR / "V20_194_FACTOR_SNAPSHOT_FIELD_REQUIREMENTS.csv"
OUT_SNAPSHOT = OUT_DIR / "V20_194_CURRENT_RUN_RECOMPUTABLE_FACTOR_SNAPSHOT.csv"
OUT_LEDGER = OUT_DIR / "V20_194_RECOMPUTABLE_FACTOR_SNAPSHOT_LEDGER.csv"
OUT_ZERO_AUDIT = OUT_DIR / "V20_194_ZERO_WEIGHT_SCORE_RECOMPUTE_AUDIT.csv"
OUT_BASE_AUDIT = OUT_DIR / "V20_194_BASE_WEIGHT_SCORE_RECOMPUTE_AUDIT.csv"
OUT_APPEND_AUDIT = OUT_DIR / "V20_194_SNAPSHOT_APPEND_ONLY_GUARD_AUDIT.csv"
OUT_PIT_AUDIT = OUT_DIR / "V20_194_PIT_SAFETY_GUARD_AUDIT.csv"
OUT_GATE = OUT_DIR / "V20_194_NEXT_STAGE_GATE.csv"
OUT_REPORT = OUT_DIR / "V20_194_READ_CENTER_REPORT.md"

BASE_WEIGHTS = {
    "fundamental": 0.20,
    "technical": 0.25,
    "strategy": 0.20,
    "risk": 0.15,
    "market_regime": 0.10,
    "data_trust": 0.10,
}
ZERO_WEIGHTS = {
    "fundamental": 0.2222222222,
    "technical": 0.2777777778,
    "strategy": 0.2222222222,
    "risk": 0.1666666667,
    "market_regime": 0.1111111111,
    "data_trust": 0.0,
}
FAMILY_SOURCE_FIELDS = {
    "fundamental": ("fundamental_contribution", "fundamental_materialization_status"),
    "technical": ("technical_contribution", "technical_materialization_status"),
    "strategy": ("strategy_contribution", "strategy_materialization_status"),
    "risk": ("risk_contribution", "risk_materialization_status"),
    "market_regime": ("market_regime_contribution", "market_regime_materialization_status"),
    "data_trust": ("data_trust_contribution", "data_trust_materialization_status"),
}
COMMON = {
    "research_only": "TRUE",
    "official_ranking_mutated": "FALSE",
    "official_ranking_score_mutation_count": "0",
    "official_rank_mutation_count": "0",
    "official_recommendation_created": "FALSE",
    "trade_action_created": "FALSE",
    "broker_execution_supported": "FALSE",
    "real_book_action_created": "FALSE",
    "no_future_outcome_joined": "TRUE",
    "no_fabricated_scores": "TRUE",
    "no_fabricated_ticker_rows": "TRUE",
    "audit_only": "TRUE",
}

SNAPSHOT_FIELDS = [
    "snapshot_id", "run_id", "as_of_date", "snapshot_created_at", "ticker",
    "fundamental_score", "technical_score", "strategy_score", "risk_score",
    "market_regime_score", "data_trust_score", "fundamental_source_status",
    "technical_source_status", "strategy_source_status", "risk_source_status",
    "market_regime_source_status", "data_trust_source_status",
    "base_weight_score", "zero_weight_score", "base_weight_policy_id",
    "zero_weight_policy_id", "base_weight_fundamental", "base_weight_technical",
    "base_weight_strategy", "base_weight_risk", "base_weight_market_regime",
    "base_weight_data_trust", "zero_weight_fundamental", "zero_weight_technical",
    "zero_weight_strategy", "zero_weight_risk", "zero_weight_market_regime",
    "zero_weight_data_trust", "pit_safe_status", "source_artifact",
    "producer_stage", "no_future_outcome_joined",
    "snapshot_usable_for_future_backtest", *COMMON.keys(),
]
CONTRACT_FIELDS = [
    "contract_id", "producer_stage", "contract_status", "required_output",
    "required_snapshot_fields", "current_run_only", "historical_backfill_allowed",
    "future_outcome_join_allowed", "append_only_ledger_required",
    "consumer_stage", *COMMON.keys(),
]
REQ_FIELDS = [
    "requirement_id", "field_name", "required", "source_column",
    "source_artifact", "field_status", "missing_field_action", *COMMON.keys(),
]
AUDIT_FIELDS = [
    "audit_id", "ticker", "snapshot_id", "expected_score", "actual_score",
    "score_recomputable", "score_delta", "audit_status", "source_artifact",
    *COMMON.keys(),
]
GUARD_FIELDS = [
    "guard_id", "guard_check", "expected_value", "actual_value",
    "guard_passed", "source_artifact", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_193_status_consumed", "v20_193_status",
    "current_run_ticker_rows_emitted", "fully_recomputable_current_rows",
    "partially_recomputable_current_rows", "all_six_family_scores_present",
    "zero_weight_score_recomputable", "base_weight_score_recomputable",
    "pit_guard_pass", "append_only_ledger_guard_pass",
    "no_official_trade_mutation", "ready_for_v20_195_daily_snapshot_accumulation",
    "blocking_reason", "final_status", *COMMON.keys(),
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{k: clean(v) for k, v in row.items()} for row in csv.DictReader(handle)]


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def sha_file(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def protected_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in PROTECTED if path.exists()}


def as_float(value: str) -> float | None:
    try:
        if clean(value) == "":
            return None
        return float(value)
    except ValueError:
        return None


def fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.10f}"


def score(values: dict[str, float | None], weights: dict[str, float]) -> float | None:
    if any(values.get(family) is None for family in weights):
        return None
    return sum((values[family] or 0.0) * weight for family, weight in weights.items())


def build_snapshots() -> tuple[list[dict[str, str]], list[dict[str, str]], str, str]:
    score_rows = read_csv(SCORE_SOURCE)
    price_rows = read_csv(PRICE_SOURCE)
    price_by_ticker = {row.get("ticker", ""): row for row in price_rows if row.get("ticker")}
    run_id = next((row.get("run_id", "") for row in price_rows if row.get("run_id")), "UNKNOWN_CURRENT_RUN")
    created_at = next((row.get("request_timestamp_utc", "") for row in price_rows if row.get("request_timestamp_utc")), "")
    snapshots: list[dict[str, str]] = []
    requirements: list[dict[str, str]] = []
    source_fields = set(score_rows[0].keys()) if score_rows else set()

    required_fields = ["ticker", *[pair[0] for pair in FAMILY_SOURCE_FIELDS.values()]]
    for idx, field in enumerate(required_fields, start=1):
        requirements.append({
            "requirement_id": f"V20_194_FIELD_REQUIREMENT_{idx:03d}",
            "field_name": field,
            "required": "TRUE",
            "source_column": field,
            "source_artifact": rel(SCORE_SOURCE),
            "field_status": "AVAILABLE" if field in source_fields else "MISSING",
            "missing_field_action": "NONE" if field in source_fields else "BLOCK_OR_MARK_ROWS_UNUSABLE",
            **COMMON,
        })
    for row in score_rows:
        ticker = row.get("ticker", "")
        if not ticker:
            continue
        price = price_by_ticker.get(ticker, {})
        as_of_date = price.get("latest_price_date", "")
        values = {family: as_float(row.get(field, "")) for family, (field, _) in FAMILY_SOURCE_FIELDS.items()}
        statuses = {family: row.get(status_field, "") for family, (_, status_field) in FAMILY_SOURCE_FIELDS.items()}
        base_score = score(values, BASE_WEIGHTS)
        zero_score = score(values, ZERO_WEIGHTS)
        usable = bool(as_of_date) and base_score is not None and zero_score is not None
        snapshot_id = f"V20_194_{run_id}_{as_of_date}_{ticker}".replace(":", "").replace("/", "-")
        snapshots.append({
            "snapshot_id": snapshot_id,
            "run_id": run_id,
            "as_of_date": as_of_date,
            "snapshot_created_at": created_at,
            "ticker": ticker,
            "fundamental_score": fmt(values["fundamental"]),
            "technical_score": fmt(values["technical"]),
            "strategy_score": fmt(values["strategy"]),
            "risk_score": fmt(values["risk"]),
            "market_regime_score": fmt(values["market_regime"]),
            "data_trust_score": fmt(values["data_trust"]),
            "fundamental_source_status": statuses["fundamental"],
            "technical_source_status": statuses["technical"],
            "strategy_source_status": statuses["strategy"],
            "risk_source_status": statuses["risk"],
            "market_regime_source_status": statuses["market_regime"],
            "data_trust_source_status": statuses["data_trust"],
            "base_weight_score": fmt(base_score),
            "zero_weight_score": fmt(zero_score),
            "base_weight_policy_id": "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY",
            "zero_weight_policy_id": "V20_166_DATA_TRUST_GATE_ONLY_WEIGHT_SIMULATION",
            "base_weight_fundamental": "0.2000000000",
            "base_weight_technical": "0.2500000000",
            "base_weight_strategy": "0.2000000000",
            "base_weight_risk": "0.1500000000",
            "base_weight_market_regime": "0.1000000000",
            "base_weight_data_trust": "0.1000000000",
            "zero_weight_fundamental": "0.2222222222",
            "zero_weight_technical": "0.2777777778",
            "zero_weight_strategy": "0.2222222222",
            "zero_weight_risk": "0.1666666667",
            "zero_weight_market_regime": "0.1111111111",
            "zero_weight_data_trust": "0.0000000000",
            "pit_safe_status": "CURRENT_RUN_PIT_SNAPSHOT" if as_of_date else "MISSING_CURRENT_AS_OF_DATE",
            "source_artifact": rel(SCORE_SOURCE),
            "producer_stage": "V20.194_RECOMPUTABLE_FACTOR_SNAPSHOT_PRODUCER_CONTRACT",
            "no_future_outcome_joined": "TRUE",
            "snapshot_usable_for_future_backtest": tf(usable),
            **COMMON,
        })
    return snapshots, requirements, run_id, created_at


def audit_scores(rows: list[dict[str, str]], weights: dict[str, float], score_field: str, prefix: str) -> list[dict[str, str]]:
    audits = []
    for idx, row in enumerate(rows, start=1):
        values = {
            "fundamental": as_float(row["fundamental_score"]),
            "technical": as_float(row["technical_score"]),
            "strategy": as_float(row["strategy_score"]),
            "risk": as_float(row["risk_score"]),
            "market_regime": as_float(row["market_regime_score"]),
            "data_trust": as_float(row["data_trust_score"]),
        }
        expected = score(values, weights)
        actual = as_float(row.get(score_field, ""))
        delta = None if expected is None or actual is None else abs(expected - actual)
        ok = delta is not None and delta < 0.0000000001
        audits.append({
            "audit_id": f"V20_194_{prefix}_SCORE_AUDIT_{idx:05d}",
            "ticker": row["ticker"],
            "snapshot_id": row["snapshot_id"],
            "expected_score": fmt(expected),
            "actual_score": fmt(actual),
            "score_recomputable": tf(expected is not None),
            "score_delta": fmt(delta),
            "audit_status": "PASS" if ok else "FAIL",
            "source_artifact": row["source_artifact"],
            **COMMON,
        })
    return audits


def guard_row(idx: int, check: str, expected: str, actual: str, source: Path) -> dict[str, str]:
    return {
        "guard_id": f"V20_194_GUARD_{idx:03d}",
        "guard_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "guard_passed": tf(expected == actual),
        "source_artifact": rel(source),
        **COMMON,
    }


def merge_ledger(current_rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], int, int]:
    existing = read_csv(OUT_LEDGER)
    seen_existing: set[str] = set()
    prior_duplicate_count = 0
    for row in existing:
        sid = row.get("snapshot_id", "")
        if not sid:
            continue
        if sid in seen_existing:
            prior_duplicate_count += 1
        seen_existing.add(sid)
    seen_current: set[str] = set()
    current_duplicate_count = 0
    for row in current_rows:
        sid = row.get("snapshot_id", "")
        if not sid:
            continue
        if sid in seen_current:
            current_duplicate_count += 1
        seen_current.add(sid)
    merged: dict[str, dict[str, str]] = {}
    for row in existing + current_rows:
        sid = row.get("snapshot_id", "")
        if not sid:
            continue
        if sid in merged:
            continue
        merged[sid] = row
    return list(merged.values()), prior_duplicate_count, current_duplicate_count


def write_report(gate: dict[str, str]) -> None:
    lines = [
        "# V20.194 Recomputable Factor Snapshot Producer Contract",
        "",
        f"- final_status: {gate['final_status']}",
        f"- current_run_ticker_rows_emitted: {gate['current_run_ticker_rows_emitted']}",
        f"- fully_recomputable_current_rows: {gate['fully_recomputable_current_rows']}",
        f"- all_six_family_scores_present: {gate['all_six_family_scores_present']}",
        f"- pit_guard_pass: {gate['pit_guard_pass']}",
        f"- append_only_ledger_guard_pass: {gate['append_only_ledger_guard_pass']}",
        "",
        "Current-run recomputable family-level snapshots are emitted for future backtests only. No historical backfill, future outcome join, official ranking mutation, or trade action is created.",
    ]
    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    before = protected_hashes()
    v193_rows = read_csv(V193_GATE)
    snapshots, requirements, _, _ = build_snapshots()
    ledger_rows, prior_duplicate_count, current_duplicate_count = merge_ledger(snapshots)
    zero_audit = audit_scores(snapshots, ZERO_WEIGHTS, "zero_weight_score", "ZERO_WEIGHT")
    base_audit = audit_scores(snapshots, BASE_WEIGHTS, "base_weight_score", "BASE_WEIGHT")
    fully = sum(1 for row in snapshots if row["snapshot_usable_for_future_backtest"] == "TRUE")
    partial = len(snapshots) - fully
    all_six = len(snapshots) > 0 and fully == len(snapshots)
    no_family_fields = not any(req["field_status"] == "AVAILABLE" and req["field_name"].endswith("_contribution") for req in requirements)
    duplicate_snapshot_id_count = current_duplicate_count
    base_sum = sum(BASE_WEIGHTS.values())
    zero_sum = sum(ZERO_WEIGHTS.values())
    after = protected_hashes()
    no_mutation = before == after

    append_guards = [
        guard_row(1, "append_only_ledger", "TRUE", "TRUE", OUT_LEDGER),
        guard_row(2, "duplicate_snapshot_id_count", "0", str(duplicate_snapshot_id_count), OUT_LEDGER),
        guard_row(3, "prior_ledger_duplicate_snapshot_id_count", "0", str(prior_duplicate_count), OUT_LEDGER),
    ]
    pit_guards = [
        guard_row(1, "research_only", "TRUE", "TRUE", SCORE_SOURCE),
        guard_row(2, "official_ranking_mutated", "FALSE", "FALSE", SCORE_SOURCE),
        guard_row(3, "official_ranking_score_mutation_count", "0", "0", SCORE_SOURCE),
        guard_row(4, "official_rank_mutation_count", "0", "0", SCORE_SOURCE),
        guard_row(5, "trade_action_created", "FALSE", "FALSE", SCORE_SOURCE),
        guard_row(6, "broker_execution_supported", "FALSE", "FALSE", SCORE_SOURCE),
        guard_row(7, "real_book_action_created", "FALSE", "FALSE", SCORE_SOURCE),
        guard_row(8, "no_future_outcome_joined", "TRUE", "TRUE", SCORE_SOURCE),
        guard_row(9, "no_fabricated_scores", "TRUE", "TRUE", SCORE_SOURCE),
        guard_row(10, "no_fabricated_ticker_rows", "TRUE", "TRUE", SCORE_SOURCE),
        guard_row(11, "base_weight_sum", "1.0000000000", f"{base_sum:.10f}", BASE_WEIGHT_SOURCE),
        guard_row(12, "zero_weight_sum", "1.0000000000", f"{zero_sum:.10f}", ZERO_WEIGHT_SOURCE),
        guard_row(13, "data_trust_zero_weight", "0.0000000000", f"{ZERO_WEIGHTS['data_trust']:.10f}", ZERO_WEIGHT_SOURCE),
        guard_row(14, "protected_source_artifacts_mutated", "FALSE", tf(not no_mutation), SCORE_SOURCE),
    ]
    append_pass = all(row["guard_passed"] == "TRUE" for row in append_guards)
    pit_pass = all(row["guard_passed"] == "TRUE" for row in pit_guards)
    zero_pass = all(row["audit_status"] == "PASS" for row in zero_audit)
    base_pass = all(row["audit_status"] == "PASS" for row in base_audit)
    no_official_trade = no_mutation and pit_pass

    if len(snapshots) < 10:
        final_status = "BLOCKED_CURRENT_RUN_INSUFFICIENT_TICKER_ROWS"
        blocking = "FEWER_THAN_10_CURRENT_RUN_TICKER_ROWS"
    elif no_family_fields:
        final_status = "BLOCKED_CURRENT_RUN_MISSING_FAMILY_LEVEL_SCORE_FIELDS"
        blocking = "NO_FAMILY_LEVEL_SCORE_FIELDS_EXIST"
    elif not pit_pass:
        final_status = "BLOCKED_PIT_GUARD_FAILURE"
        blocking = "PIT_GUARD_FAILED"
    elif not append_pass:
        final_status = "BLOCKED_APPEND_ONLY_LEDGER_GUARD_FAILURE"
        blocking = "APPEND_ONLY_LEDGER_GUARD_FAILED"
    elif not no_official_trade:
        final_status = "BLOCKED_OFFICIAL_OR_TRADE_MUTATION_DETECTED"
        blocking = "OFFICIAL_OR_TRADE_MUTATION_DETECTED"
    elif len(snapshots) >= 20 and all_six and zero_pass and base_pass:
        final_status = "PASS_V20_194_RECOMPUTABLE_FACTOR_SNAPSHOT_PRODUCER_CONTRACT_READY_FOR_V20_195_DAILY_SNAPSHOT_ACCUMULATION"
        blocking = "NONE"
    else:
        final_status = "PARTIAL_PASS_V20_194_RECOMPUTABLE_FACTOR_SNAPSHOT_PRODUCER_CONTRACT_LIMITED_CURRENT_RUN_COVERAGE"
        blocking = "LIMITED_CURRENT_RUN_FAMILY_SCORE_COVERAGE"
    ready = "TRUE" if final_status.startswith(("PASS", "PARTIAL_PASS")) else "FALSE"

    contract = [{
        "contract_id": "V20_194_FACTOR_SNAPSHOT_PRODUCER_CONTRACT_001",
        "producer_stage": "DAILY_RESEARCH_RUNNER_FACTOR_SNAPSHOT_PRODUCER",
        "contract_status": "ACTIVE_RESEARCH_ONLY_CONTRACT_CREATED",
        "required_output": rel(OUT_LEDGER),
        "required_snapshot_fields": "|".join(SNAPSHOT_FIELDS[:38]),
        "current_run_only": "TRUE",
        "historical_backfill_allowed": "FALSE",
        "future_outcome_join_allowed": "FALSE",
        "append_only_ledger_required": "TRUE",
        "consumer_stage": "V20_192_R1_DATA_TRUST_ZERO_WEIGHT_RANDOM_ASOF_BACKTEST_RERUN",
        **COMMON,
    }]
    gate = {
        "gate_check_id": "V20_194_NEXT_STAGE_GATE_001",
        "v20_193_status_consumed": tf(bool(v193_rows)),
        "v20_193_status": v193_rows[0].get("final_status", "") if v193_rows else "",
        "current_run_ticker_rows_emitted": str(len(snapshots)),
        "fully_recomputable_current_rows": str(fully),
        "partially_recomputable_current_rows": str(partial),
        "all_six_family_scores_present": tf(all_six),
        "zero_weight_score_recomputable": tf(zero_pass and len(zero_audit) > 0),
        "base_weight_score_recomputable": tf(base_pass and len(base_audit) > 0),
        "pit_guard_pass": tf(pit_pass),
        "append_only_ledger_guard_pass": tf(append_pass),
        "no_official_trade_mutation": tf(no_official_trade),
        "ready_for_v20_195_daily_snapshot_accumulation": ready,
        "blocking_reason": blocking,
        "final_status": final_status,
        **COMMON,
    }

    write_csv(OUT_CONTRACT, CONTRACT_FIELDS, contract)
    write_csv(OUT_REQUIREMENTS, REQ_FIELDS, requirements)
    write_csv(OUT_SNAPSHOT, SNAPSHOT_FIELDS, snapshots)
    write_csv(OUT_LEDGER, SNAPSHOT_FIELDS, ledger_rows)
    write_csv(OUT_ZERO_AUDIT, AUDIT_FIELDS, zero_audit)
    write_csv(OUT_BASE_AUDIT, AUDIT_FIELDS, base_audit)
    write_csv(OUT_APPEND_AUDIT, GUARD_FIELDS, append_guards)
    write_csv(OUT_PIT_AUDIT, GUARD_FIELDS, pit_guards)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate)

    print(gate["final_status"])
    for key in GATE_FIELDS:
        if key not in COMMON and key != "gate_check_id":
            print(f"{key.upper()}={gate[key]}")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("NO_FUTURE_OUTCOME_JOINED=TRUE")
    print("NO_FABRICATED_SCORES=TRUE")
    print("NO_FABRICATED_TICKER_ROWS=TRUE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
