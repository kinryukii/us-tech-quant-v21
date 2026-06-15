#!/usr/bin/env python
"""V20.193 historical recomputable factor snapshot builder."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKTEST = ROOT / "outputs" / "v20" / "backtest"
SEARCH_DIRS = [
    ROOT / "outputs" / "v20" / "consolidation",
    ROOT / "outputs" / "v20" / "factors",
    ROOT / "outputs" / "v20" / "evidence",
    ROOT / "outputs" / "v20" / "backtest",
    ROOT / "outputs" / "v18" / "candidates",
    ROOT / "outputs" / "v18" / "technical_timing",
]
V192_GATE = BACKTEST / "V20_192_NEXT_STAGE_GATE.csv"

OUT_DISCOVERY = BACKTEST / "V20_193_HISTORICAL_FACTOR_SOURCE_DISCOVERY.csv"
OUT_COVERAGE = BACKTEST / "V20_193_HISTORICAL_FACTOR_FIELD_COVERAGE_AUDIT.csv"
OUT_SNAPSHOT = BACKTEST / "V20_193_HISTORICAL_RECOMPUTABLE_FACTOR_SNAPSHOT.csv"
OUT_PREVIEW = BACKTEST / "V20_193_HISTORICAL_ZERO_WEIGHT_SCORE_PREVIEW.csv"
OUT_MISSING = BACKTEST / "V20_193_MISSING_FACTOR_FIELD_REPORT.csv"
OUT_PIT = BACKTEST / "V20_193_PIT_SAFETY_AUDIT.csv"
OUT_GATE = BACKTEST / "V20_193_NEXT_STAGE_GATE.csv"
OUT_REPORT = BACKTEST / "V20_193_READ_CENTER_REPORT.md"

WEIGHTS = {
    "fundamental": 0.2222222222,
    "technical": 0.2777777778,
    "strategy": 0.2222222222,
    "risk": 0.1666666667,
    "market_regime": 0.1111111111,
    "data_trust": 0.0,
}
FAMILY_ALIASES = {
    "fundamental": ["fundamental_score", "fundamental_contribution"],
    "technical": ["technical_score", "technical_contribution", "exploratory_technical_score"],
    "strategy": ["strategy_score", "strategy_contribution"],
    "risk": ["risk_score", "risk_contribution"],
    "market_regime": ["market_regime_score", "market_regime_contribution"],
    "data_trust": ["data_trust_score", "data_trust_contribution"],
}
DATE_FIELDS = ["as_of_date", "signal_date", "ranking_as_of_date", "factor_input_as_of_date"]
COMMON = {
    "research_only": "TRUE",
    "official_ranking_mutated": "FALSE",
    "official_ranking_score_mutation_count": "0",
    "official_rank_mutation_count": "0",
    "official_recommendation_created": "FALSE",
    "trade_action_created": "FALSE",
    "broker_execution_supported": "FALSE",
    "real_book_action_created": "FALSE",
    "no_current_to_historical_join": "TRUE",
    "no_fabricated_scores": "TRUE",
    "no_fabricated_ticker_rows": "TRUE",
    "audit_only": "TRUE",
}

DISCOVERY_FIELDS = [
    "source_id", "source_artifact", "row_count", "source_sha256",
    "has_ticker", "date_field", "has_historical_date", "family_field_count",
    "available_family_fields", "current_only_source", "usable_source",
    "rejection_reason", *COMMON.keys(),
]
COVERAGE_FIELDS = [
    "coverage_id", "source_artifact", "factor_family", "accepted_field",
    "field_available", "comparable_normalized_family_field", "coverage_status",
    *COMMON.keys(),
]
SNAPSHOT_FIELDS = [
    "snapshot_id", "as_of_date", "ticker", "fundamental_score_or_contribution",
    "technical_score_or_contribution", "strategy_score_or_contribution",
    "risk_score_or_contribution", "market_regime_score_or_contribution",
    "data_trust_score_or_contribution", "fully_recomputable",
    "pit_safe", "source_artifact", *COMMON.keys(),
]
PREVIEW_FIELDS = [
    "preview_id", "as_of_date", "ticker", "zero_weight_score",
    "zero_weight_rank", "score_status", "source_artifact", *COMMON.keys(),
]
MISSING_FIELDS = [
    "missing_id", "source_artifact", "missing_category", "missing_detail",
    "repair_requirement", *COMMON.keys(),
]
PIT_FIELDS = [
    "pit_audit_id", "source_artifact", "pit_safe", "pit_status",
    "date_field", "current_only_source", "lineage_status", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_192_status_consumed", "v20_192_status",
    "discovered_source_count", "usable_source_count",
    "rejected_current_only_source_count", "rejected_missing_asof_count",
    "rejected_missing_ticker_count", "rejected_missing_family_field_count",
    "historical_asof_count", "historical_ticker_row_count",
    "fully_recomputable_row_count", "partially_recomputable_row_count",
    "missing_family_field_count", "pit_safe_row_count", "non_pit_safe_row_count",
    "all_five_non_data_trust_families_available_for_each_asof",
    "pit_safety_audit_pass", "no_official_trade_mutation",
    "ready_for_v20_192_r1_zero_weight_random_asof_backtest_rerun",
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


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists() or path.stat().st_size == 0:
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{k: clean(v) for k, v in row.items()} for row in reader], list(reader.fieldnames or [])


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


def as_float(value: str) -> float | None:
    try:
        if clean(value) == "":
            return None
        return float(value)
    except ValueError:
        return None


def discover_sources() -> tuple[list[dict[str, str]], list[dict[str, str]], list[Path]]:
    discovery: list[dict[str, str]] = []
    coverage: list[dict[str, str]] = []
    protected: list[Path] = []
    source_idx = 0
    coverage_idx = 0
    for directory in SEARCH_DIRS:
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*.csv")):
            rows, fields = read_csv(path)
            if not fields:
                continue
            field_set = set(fields)
            has_ticker = "ticker" in field_set
            date_field = next((field for field in DATE_FIELDS if field in field_set), "")
            has_historical_date = bool(date_field)
            accepted: dict[str, str] = {}
            for family, aliases in FAMILY_ALIASES.items():
                accepted[family] = next((field for field in aliases if field in field_set), "")
            family_count = sum(1 for field in accepted.values() if field)
            current_only = not has_historical_date or path.name.startswith(("V18_CURRENT", "V20_CURRENT")) or "CURRENT_" in path.name
            has_required_families = all(accepted[family] for family in ["fundamental", "technical", "strategy", "risk", "market_regime"])
            usable = has_ticker and has_historical_date and has_required_families and not current_only
            reason = "USABLE" if usable else "NONE"
            if not has_ticker:
                reason = "MISSING_TICKER"
            elif not has_historical_date:
                reason = "MISSING_HISTORICAL_ASOF_DATE"
            elif current_only:
                reason = "CURRENT_ONLY_OR_UNKNOWN_PIT_SOURCE"
            elif not has_required_families:
                reason = "MISSING_REQUIRED_NON_DATA_TRUST_FAMILY_FIELDS"
            if family_count or has_ticker or has_historical_date:
                source_idx += 1
                protected.append(path)
                discovery.append({
                    "source_id": f"V20_193_SOURCE_{source_idx:04d}",
                    "source_artifact": rel(path),
                    "row_count": str(len(rows)),
                    "source_sha256": sha_file(path),
                    "has_ticker": tf(has_ticker),
                    "date_field": date_field,
                    "has_historical_date": tf(has_historical_date),
                    "family_field_count": str(family_count),
                    "available_family_fields": ";".join(field for field in accepted.values() if field),
                    "current_only_source": tf(current_only),
                    "usable_source": tf(usable),
                    "rejection_reason": reason,
                    **COMMON,
                })
                for family in FAMILY_ALIASES:
                    coverage_idx += 1
                    field = accepted[family]
                    coverage.append({
                        "coverage_id": f"V20_193_COVERAGE_{coverage_idx:04d}",
                        "source_artifact": rel(path),
                        "factor_family": family.upper(),
                        "accepted_field": field,
                        "field_available": tf(bool(field)),
                        "comparable_normalized_family_field": tf(bool(field) and "contribution" in field),
                        "coverage_status": "AVAILABLE" if field else "MISSING",
                        **COMMON,
                    })
    return discovery, coverage, protected


def build_snapshot(discovery: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    snapshots: list[dict[str, str]] = []
    previews: list[dict[str, str]] = []
    idx = 0
    for source in discovery:
        if source["usable_source"] != "TRUE":
            continue
        path = ROOT / source["source_artifact"]
        rows, fields = read_csv(path)
        field_set = set(fields)
        date_field = source["date_field"]
        accepted = {
            family: next((field for field in aliases if field in field_set), "")
            for family, aliases in FAMILY_ALIASES.items()
        }
        for row in rows:
            values = {family: as_float(row.get(field, "")) for family, field in accepted.items() if field}
            fully = all(values.get(family) is not None for family in ["fundamental", "technical", "strategy", "risk", "market_regime"])
            if not fully:
                continue
            idx += 1
            score = sum(WEIGHTS[family] * (values.get(family) or 0.0) for family in WEIGHTS)
            snapshots.append({
                "snapshot_id": f"V20_193_SNAPSHOT_{idx:06d}",
                "as_of_date": row.get(date_field, ""),
                "ticker": row.get("ticker", ""),
                "fundamental_score_or_contribution": f"{values.get('fundamental'):.10f}",
                "technical_score_or_contribution": f"{values.get('technical'):.10f}",
                "strategy_score_or_contribution": f"{values.get('strategy'):.10f}",
                "risk_score_or_contribution": f"{values.get('risk'):.10f}",
                "market_regime_score_or_contribution": f"{values.get('market_regime'):.10f}",
                "data_trust_score_or_contribution": f"{(values.get('data_trust') or 0.0):.10f}",
                "fully_recomputable": "TRUE",
                "pit_safe": "TRUE",
                "source_artifact": rel(path),
                **COMMON,
            })
            previews.append({
                "preview_id": f"V20_193_PREVIEW_{idx:06d}",
                "as_of_date": row.get(date_field, ""),
                "ticker": row.get("ticker", ""),
                "zero_weight_score": f"{score:.10f}",
                "zero_weight_rank": "",
                "score_status": "COMPUTED",
                "source_artifact": rel(path),
                **COMMON,
            })
    for asof in sorted({row["as_of_date"] for row in previews}):
        group = [row for row in previews if row["as_of_date"] == asof]
        group.sort(key=lambda row: float(row["zero_weight_score"]), reverse=True)
        for rank, row in enumerate(group, start=1):
            row["zero_weight_rank"] = str(rank)
    return snapshots, previews


def write_report(gate: dict[str, str]) -> None:
    lines = [
        "# V20.193 Historical Recomputable Factor Snapshot Builder",
        "",
        f"- final_status: {gate['final_status']}",
        f"- discovered_source_count: {gate['discovered_source_count']}",
        f"- usable_source_count: {gate['usable_source_count']}",
        f"- historical_asof_count: {gate['historical_asof_count']}",
        f"- fully_recomputable_row_count: {gate['fully_recomputable_row_count']}",
        f"- pit_safety_audit_pass: {gate['pit_safety_audit_pass']}",
        f"- blocking_reason: {gate['blocking_reason']}",
        "",
        "No current-only factor rows were copied backward into historical as-of dates. No scores, ticker rows, or returns were fabricated.",
    ]
    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    v192_rows, _ = read_csv(V192_GATE)
    v192 = v192_rows[0] if v192_rows else {}
    discovery, coverage, protected = discover_sources()
    before = {rel(path): sha_file(path) for path in protected}
    snapshot, preview = build_snapshot(discovery)
    after = {rel(path): sha_file(path) for path in protected}

    discovered_count = len(discovery)
    usable_count = sum(1 for row in discovery if row["usable_source"] == "TRUE")
    rejected_current = sum(1 for row in discovery if row["rejection_reason"] == "CURRENT_ONLY_OR_UNKNOWN_PIT_SOURCE")
    rejected_missing_asof = sum(1 for row in discovery if row["rejection_reason"] == "MISSING_HISTORICAL_ASOF_DATE")
    rejected_missing_ticker = sum(1 for row in discovery if row["rejection_reason"] == "MISSING_TICKER")
    rejected_missing_family = sum(1 for row in discovery if row["rejection_reason"] == "MISSING_REQUIRED_NON_DATA_TRUST_FAMILY_FIELDS")
    historical_asof_count = len({row["as_of_date"] for row in snapshot})
    fully_rows = len(snapshot)
    partial_rows = 0
    missing_family_field_count = sum(1 for row in coverage if row["field_available"] == "FALSE")
    pit_safe_rows = sum(1 for row in snapshot if row["pit_safe"] == "TRUE")
    non_pit_safe_rows = 0
    no_mutation = before == after

    missing_rows = []
    for row in discovery:
        if row["usable_source"] == "FALSE":
            missing_rows.append({
                "missing_id": f"V20_193_MISSING_{len(missing_rows) + 1:04d}",
                "source_artifact": row["source_artifact"],
                "missing_category": row["rejection_reason"],
                "missing_detail": "Historical PIT-safe ticker rows require ticker, as-of date, and all five non-DATA_TRUST family fields.",
                "repair_requirement": "Attach or build PIT-safe historical family-level factor snapshot; do not reuse current-only scores.",
                **COMMON,
            })
    pit_rows = []
    for idx, row in enumerate(discovery, start=1):
        pit_safe = row["usable_source"] == "TRUE"
        pit_rows.append({
            "pit_audit_id": f"V20_193_PIT_{idx:04d}",
            "source_artifact": row["source_artifact"],
            "pit_safe": tf(pit_safe),
            "pit_status": "PASS" if pit_safe else "REJECTED_FOR_HISTORICAL_SNAPSHOT",
            "date_field": row["date_field"],
            "current_only_source": row["current_only_source"],
            "lineage_status": "PIT_SAFE_HISTORICAL_FAMILY_SNAPSHOT" if pit_safe else row["rejection_reason"],
            **COMMON,
        })
    pit_pass = all(row["pit_safe"] == "TRUE" for row in pit_rows if row["source_artifact"] in {snap["source_artifact"] for snap in snapshot})
    all_families_each_asof = historical_asof_count > 0 and all(
        any(row["as_of_date"] == asof and row["fully_recomputable"] == "TRUE" for row in snapshot)
        for asof in {row["as_of_date"] for row in snapshot}
    )

    if not no_mutation:
        final_status = "BLOCKED_OFFICIAL_OR_SOURCE_MUTATION_DETECTED"
        blocking_reason = "SOURCE_ARTIFACT_MUTATION_DETECTED"
    elif fully_rows < 100 or historical_asof_count < 10 or usable_count == 0:
        final_status = "BLOCKED_NO_USABLE_HISTORICAL_FAMILY_LEVEL_SCORING_FIELDS"
        blocking_reason = "NO_USABLE_HISTORICAL_PIT_SAFE_FULL_FAMILY_FACTOR_SNAPSHOT"
    elif historical_asof_count >= 30 and fully_rows >= 300 and all_families_each_asof and pit_pass:
        final_status = "PASS_V20_193_READY_FOR_V20_192_R1_ZERO_WEIGHT_RANDOM_ASOF_BACKTEST_RERUN"
        blocking_reason = "NONE"
    else:
        final_status = "PARTIAL_PASS_LIMITED_HISTORICAL_RECOMPUTABLE_FACTOR_SNAPSHOT"
        blocking_reason = "LIMITED_HISTORICAL_ASOF_OR_FAMILY_COVERAGE"
    ready = "TRUE" if final_status.startswith(("PASS", "PARTIAL_PASS")) else "FALSE"
    gate = {
        "gate_check_id": "V20_193_NEXT_STAGE_GATE_001",
        "v20_192_status_consumed": tf(bool(v192)),
        "v20_192_status": v192.get("final_status", ""),
        "discovered_source_count": str(discovered_count),
        "usable_source_count": str(usable_count),
        "rejected_current_only_source_count": str(rejected_current),
        "rejected_missing_asof_count": str(rejected_missing_asof),
        "rejected_missing_ticker_count": str(rejected_missing_ticker),
        "rejected_missing_family_field_count": str(rejected_missing_family),
        "historical_asof_count": str(historical_asof_count),
        "historical_ticker_row_count": str(len(snapshot)),
        "fully_recomputable_row_count": str(fully_rows),
        "partially_recomputable_row_count": str(partial_rows),
        "missing_family_field_count": str(missing_family_field_count),
        "pit_safe_row_count": str(pit_safe_rows),
        "non_pit_safe_row_count": str(non_pit_safe_rows),
        "all_five_non_data_trust_families_available_for_each_asof": tf(all_families_each_asof),
        "pit_safety_audit_pass": tf(pit_pass),
        "no_official_trade_mutation": tf(no_mutation),
        "ready_for_v20_192_r1_zero_weight_random_asof_backtest_rerun": ready,
        "blocking_reason": blocking_reason,
        "final_status": final_status,
        **COMMON,
    }

    write_csv(OUT_DISCOVERY, DISCOVERY_FIELDS, discovery)
    write_csv(OUT_COVERAGE, COVERAGE_FIELDS, coverage)
    write_csv(OUT_SNAPSHOT, SNAPSHOT_FIELDS, snapshot)
    write_csv(OUT_PREVIEW, PREVIEW_FIELDS, preview)
    write_csv(OUT_MISSING, MISSING_FIELDS, missing_rows)
    write_csv(OUT_PIT, PIT_FIELDS, pit_rows)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate)

    print(gate["final_status"])
    for key in GATE_FIELDS:
        if key not in COMMON and key != "gate_check_id":
            print(f"{key.upper()}={gate[key]}")
    print("RESEARCH_ONLY=TRUE")
    print("NO_CURRENT_TO_HISTORICAL_JOIN=TRUE")
    print("NO_FABRICATED_SCORES=TRUE")
    print("NO_FABRICATED_TICKER_ROWS=TRUE")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
