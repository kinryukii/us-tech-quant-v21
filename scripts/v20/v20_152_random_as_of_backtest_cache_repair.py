#!/usr/bin/env python
"""V20.152 random-as-of backtest cache repair.

Rebuilds a research-only cache index from existing historical/as-of/backtest
artifacts. This stage audits and normalizes evidence that already exists; it
does not fabricate tickers, prices, benchmark returns, outcomes, or performance
claims, and it does not mutate V20.109-V20.151 upstream outputs.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
CONSOLIDATION = OUTPUTS / "consolidation"
EVIDENCE = OUTPUTS / "evidence"
EVIDENCE_COVERAGE = OUTPUTS / "evidence_coverage"
OBSERVATIONS = OUTPUTS / "observations"
OPS = OUTPUTS / "ops"
READ_CENTER = OUTPUTS / "read_center"
BACKTEST = OUTPUTS / "backtest"
INPUTS = ROOT / "inputs" / "v20"

IN_V151_GATE = OBSERVATIONS / "V20_151_FORWARD_OBSERVATION_GATE.csv"
IN_V151_ACCUMULATION = OBSERVATIONS / "V20_151_FORWARD_OBSERVATION_ACCUMULATION.csv"
IN_V151_SOURCE = OBSERVATIONS / "V20_151_FORWARD_OBSERVATION_SOURCE_AUDIT.csv"
IN_V151_ELIGIBILITY = OBSERVATIONS / "V20_151_FORWARD_OBSERVATION_ELIGIBILITY_AUDIT.csv"

OUT_CACHE = BACKTEST / "V20_152_RANDOM_AS_OF_BACKTEST_CACHE.csv"
OUT_GATE = BACKTEST / "V20_152_RANDOM_AS_OF_BACKTEST_CACHE_GATE.csv"
OUT_SOURCE_AUDIT = BACKTEST / "V20_152_RANDOM_AS_OF_SOURCE_AUDIT.csv"
OUT_ELIGIBILITY_AUDIT = BACKTEST / "V20_152_RANDOM_AS_OF_ELIGIBILITY_AUDIT.csv"
OUT_GAP_PLAN = BACKTEST / "V20_152_RANDOM_AS_OF_GAP_REPAIR_PLAN.csv"
REPORT = READ_CENTER / "V20_152_RANDOM_AS_OF_BACKTEST_CACHE_REPAIR_REPORT.md"

V151_ALLOWED_STATUSES = {
    "PARTIAL_PASS_V20_151_FORWARD_OBSERVATION_ACCUMULATION_WITH_PENDING_OUTCOMES_READY_FOR_V20_152",
    "PASS_V20_151_FORWARD_OBSERVATION_ACCUMULATION_READY_FOR_V20_152",
}
PASS_STATUS = "PASS_V20_152_RANDOM_AS_OF_BACKTEST_CACHE_READY_FOR_V20_153"
PARTIAL_STATUS = "PARTIAL_PASS_V20_152_RANDOM_AS_OF_BACKTEST_CACHE_WITH_GAPS_READY_FOR_V20_153"
WARN_STATUS = "WARN_V20_152_NO_USABLE_RANDOM_AS_OF_CACHE_FOUND"
BLOCKED_STATUS = "BLOCKED_V20_152_RANDOM_AS_OF_BACKTEST_CACHE_REPAIR"
MIN_DYNAMIC_ROWS_FOR_PASS = 10

DISCOVERY_ROOTS = [CONSOLIDATION, EVIDENCE, EVIDENCE_COVERAGE, OPS, INPUTS / "random_asof", INPUTS / "outcome_benchmark"]
TARGET_RE = re.compile(r"V20_(35(?:_R[12])?|82|84|85|86|87|88|89|90|91|92|93)", re.IGNORECASE)
WINDOW_RE = re.compile(r"(\d+)")
CURRENT_DATE = date(2026, 6, 14)

SAFETY_FIELDS = [
    "formal_activation_allowed",
    "promotion_ready",
    "official_recommendation_created",
    "official_ranking_mutated",
    "weight_mutated",
    "real_book_action_created",
    "trade_action_created",
    "broker_execution_supported",
    "performance_claim_created",
]
SAFETY = {field: "FALSE" for field in SAFETY_FIELDS}
COMMON = {
    **SAFETY,
    "research_only": "TRUE",
    "staging_review_only": "TRUE",
    "random_as_of_cache_repair_only": "TRUE",
    "audit_only": "TRUE",
}

CACHE_FIELDS = [
    "as_of_date",
    "forward_window",
    "source_artifact",
    "ticker_count",
    "benchmark_available",
    "outcome_available",
    "pit_safe",
    "usable_for_factor_ablation",
    "usable_for_dynamic_weight_research",
    "exclusion_reason",
    "evidence_quality",
    "data_freshness_status",
    *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id",
    "v20_151_gate_consumed",
    "v20_151_status",
    "v20_151_allowed_for_v20_152",
    "staging_review_allowed",
    *SAFETY_FIELDS,
    "source_artifact_count",
    "usable_source_artifact_count",
    "partial_source_artifact_count",
    "ineligible_source_artifact_count",
    "cache_row_count",
    "factor_ablation_usable_row_count",
    "dynamic_weight_usable_row_count",
    "gap_count",
    "no_ticker_rows_fabricated",
    "no_historical_prices_fabricated",
    "no_benchmark_returns_fabricated",
    "no_outcomes_fabricated",
    "no_performance_claim_created",
    "no_upstream_outputs_mutated",
    "v20_153_random_as_of_review_allowed",
    "next_recommended_action",
    "blocking_reason",
    "random_as_of_backtest_cache_status",
    "research_only",
    "staging_review_only",
    "random_as_of_cache_repair_only",
    "audit_only",
]
SOURCE_FIELDS = [
    "source_audit_id",
    "source_artifact",
    "source_stage",
    "artifact_role",
    "artifact_exists",
    "artifact_non_empty",
    "artifact_type",
    "row_count",
    "source_sha256",
    "date_evidence_count",
    "forward_window_evidence_count",
    "ticker_evidence_count",
    "benchmark_evidence_present",
    "outcome_evidence_present",
    "pit_evidence_present",
    "source_cache_status",
    "exclusion_reason",
    "evidence_quality",
    "data_freshness_status",
    *COMMON.keys(),
]
ELIGIBILITY_FIELDS = [
    "eligibility_audit_id",
    "as_of_date",
    "forward_window",
    "source_artifact",
    "ticker_count",
    "benchmark_available",
    "outcome_available",
    "pit_safe",
    "eligible_for_cache",
    "usable_for_factor_ablation",
    "usable_for_dynamic_weight_research",
    "eligibility_status",
    "exclusion_reason",
    "evidence_quality",
    "data_freshness_status",
    *COMMON.keys(),
]
GAP_FIELDS = [
    "gap_id",
    "source_artifact",
    "as_of_date",
    "forward_window",
    "gap_type",
    "gap_reason",
    "repair_action",
    "can_repair_without_new_market_data",
    "priority",
    *COMMON.keys(),
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def truthy(value: object) -> bool:
    return clean(value).upper() == "TRUE"


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
        return [{key: clean(value) for key, value in row.items()} for row in reader], list(reader.fieldnames or [])


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


def upstream_inputs() -> list[Path]:
    paths: list[Path] = []
    for root in [CONSOLIDATION, EVIDENCE, EVIDENCE_COVERAGE, OBSERVATIONS, OPS]:
        if root.exists():
            paths.extend(path for path in root.glob("V20_*") if path.is_file() and _stage_number(path.name) is not None and 109 <= _stage_number(path.name) <= 151)
    return sorted(set(paths))


def upstream_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in upstream_inputs() if path.exists()}


def _stage_number(name: str) -> int | None:
    match = re.match(r"V20_(\d+)", name.upper())
    return int(match.group(1)) if match else None


def discover_artifacts() -> list[Path]:
    paths: list[Path] = []
    for root in DISCOVERY_ROOTS:
        if root.exists():
            paths.extend(path for path in root.rglob("*") if path.is_file() and TARGET_RE.search(path.name))
    return sorted(set(paths), key=lambda path: rel(path))


def stage_for(path: Path) -> str:
    name = path.name.upper()
    match = TARGET_RE.search(name)
    return f"V20.{match.group(1).replace('_', '.')}" if match else "UNKNOWN"


def role_for(path: Path) -> str:
    name = path.name.upper()
    if "ROW_LEVEL_RETURNS" in name or "FORWARD_OUTCOME" in name or "MULTI_WINDOW_STRATEGY_EVIDENCE" in name:
        return "OUTCOME_BENCHMARK_EVIDENCE"
    if "BENCHMARK" in name:
        return "BENCHMARK_EVIDENCE"
    if "HISTORICAL" in name and ("CACHE" in name or "PRICE" in name):
        return "HISTORICAL_PRICE_CACHE"
    if "RANDOM_ASOF" in name or "RANDOM_AS_OF" in name:
        return "RANDOM_AS_OF_REFERENCE"
    if "EVIDENCE" in name:
        return "EVIDENCE_REFERENCE"
    if "MANIFEST" in name:
        return "MANIFEST_REFERENCE"
    return "REFERENCE_ARTIFACT"


def first_present(row: dict[str, str], fields: Iterable[str]) -> str:
    for field in fields:
        value = clean(row.get(field))
        if value:
            return value
    return ""


def date_from_row(row: dict[str, str]) -> str:
    return first_present(row, ["as_of_date", "signal_date", "price_date", "entry_price_date", "observation_date", "run_timestamp_utc"])[:10]


def window_from_row(row: dict[str, str], artifact_name: str = "") -> str:
    value = first_present(row, ["forward_window", "holding_window", "evaluation_window", "exit_rule"])
    if value:
        if value.lower().startswith("forward_"):
            match = WINDOW_RE.search(value)
            return f"{match.group(1)}d" if match else value
        return value
    match = re.search(r"FORWARD[_-]?(\d+)", artifact_name.upper())
    return f"{match.group(1)}d" if match else "UNKNOWN"


def ticker_from_row(row: dict[str, str]) -> str:
    return first_present(row, ["ticker", "symbol", "normalized_ticker", "ticker_or_candidate_id", "display_name_or_ticker", "benchmark_symbol"]).upper()


def value_present(row: dict[str, str], fields: Iterable[str]) -> bool:
    return any(clean(row.get(field)) not in {"", "NA", "N/A", "NONE", "NULL"} for field in fields)


def row_outcome_available(row: dict[str, str]) -> bool:
    if truthy(row.get("outcome_available")):
        return True
    status = first_present(row, ["outcome_attachment_status", "certification_status", "return_evidence_status"]).upper()
    if any(token in status for token in ["CERTIFIED", "ATTACHED", "PASS", "INCLUDED"]):
        return True
    return value_present(row, ["ticker_forward_return", "forward_return", "strategy_return", "exit_price", "ticker_outcome_price"])


def row_benchmark_available(row: dict[str, str]) -> bool:
    if truthy(row.get("benchmark_available")) or truthy(row.get("benchmark_data_available")):
        return True
    status = first_present(row, ["coverage_status", "return_evidence_status", "certification_status"]).upper()
    if ("BENCHMARK" in status and "INSUFFICIENT" not in status) or status == "PASS":
        return True
    return value_present(row, ["benchmark_return", "benchmark_forward_return", "spy_forward_return", "qqq_forward_return", "alpha_vs_benchmark", "excess_return"])


def row_pit_safe(row: dict[str, str], role: str) -> bool:
    if truthy(row.get("pit_safe")) or truthy(row.get("factor_asof_check_passed")):
        return True
    status = first_present(row, ["pit_safety_status", "certification_status"]).upper()
    if any(token in status for token in ["PASS", "PIT_SAFE", "CERTIFIED"]):
        return True
    if role in {"HISTORICAL_PRICE_CACHE", "OUTCOME_BENCHMARK_EVIDENCE"} and not truthy(row.get("future_factor_data_used")):
        return True
    return False


def evidence_quality(pit_safe: bool, outcome_available: bool, benchmark_available: bool, ticker_count: int) -> str:
    if pit_safe and outcome_available and benchmark_available and ticker_count > 0:
        return "HIGH"
    if pit_safe and ticker_count > 0 and (outcome_available or benchmark_available):
        return "MEDIUM"
    if ticker_count > 0:
        return "LOW"
    return "INSUFFICIENT"


def freshness_status(as_of_date: str) -> str:
    try:
        observed = datetime.strptime(as_of_date[:10], "%Y-%m-%d").date()
    except ValueError:
        return "UNKNOWN"
    age = (CURRENT_DATE - observed).days
    if age < 0:
        return "FUTURE_DATED_REVIEW_REQUIRED"
    if age <= 30:
        return "CURRENT_WITHIN_30D"
    return "HISTORICAL_REFERENCE"


def exclusion_reasons(ticker_count: int, benchmark_available: bool, outcome_available: bool, pit_safe: bool) -> list[str]:
    reasons: list[str] = []
    if ticker_count <= 0:
        reasons.append("NO_TICKER_EVIDENCE")
    if not pit_safe:
        reasons.append("PIT_SAFETY_NOT_ESTABLISHED")
    if not outcome_available:
        reasons.append("OUTCOME_EVIDENCE_MISSING")
    if not benchmark_available:
        reasons.append("BENCHMARK_EVIDENCE_MISSING")
    return reasons


def source_status(role: str, ticker_count: int, benchmark_present: bool, outcome_present: bool, pit_present: bool) -> str:
    if ticker_count > 0 and pit_present and benchmark_present and outcome_present:
        return "USABLE"
    if ticker_count > 0 or benchmark_present or outcome_present or role in {"MANIFEST_REFERENCE", "EVIDENCE_REFERENCE", "RANDOM_AS_OF_REFERENCE"}:
        return "PARTIAL"
    return "INELIGIBLE"


def aggregate_csv_artifact(path: Path, rows: list[dict[str, str]], role: str) -> tuple[list[dict[str, str]], dict[str, object]]:
    groups: dict[tuple[str, str], dict[str, object]] = {}
    artifact = rel(path)
    for row in rows:
        as_of = date_from_row(row) or "UNKNOWN"
        window = window_from_row(row, path.name)
        key = (as_of, window)
        group = groups.setdefault(key, {"tickers": set(), "benchmark": False, "outcome": False, "pit": False})
        ticker = ticker_from_row(row)
        if ticker:
            group["tickers"].add(ticker)  # type: ignore[union-attr]
        group["benchmark"] = bool(group["benchmark"]) or row_benchmark_available(row)
        group["outcome"] = bool(group["outcome"]) or row_outcome_available(row)
        group["pit"] = bool(group["pit"]) or row_pit_safe(row, role)

    cache_rows: list[dict[str, str]] = []
    all_tickers: set[str] = set()
    date_count = 0
    window_count = 0
    benchmark_present = False
    outcome_present = False
    pit_present = False
    for (as_of, window), group in sorted(groups.items()):
        tickers = group["tickers"]  # type: ignore[assignment]
        ticker_count = len(tickers)
        all_tickers.update(tickers)
        if as_of != "UNKNOWN":
            date_count += 1
        if window != "UNKNOWN":
            window_count += 1
        benchmark_available = bool(group["benchmark"])
        outcome_available = bool(group["outcome"])
        pit_safe = bool(group["pit"])
        benchmark_present = benchmark_present or benchmark_available
        outcome_present = outcome_present or outcome_available
        pit_present = pit_present or pit_safe
        reasons = exclusion_reasons(ticker_count, benchmark_available, outcome_available, pit_safe)
        usable_factor = ticker_count > 0 and pit_safe
        usable_dynamic = ticker_count > 0 and pit_safe and benchmark_available and outcome_available
        cache_rows.append({
            "as_of_date": as_of,
            "forward_window": window,
            "source_artifact": artifact,
            "ticker_count": str(ticker_count),
            "benchmark_available": tf(benchmark_available),
            "outcome_available": tf(outcome_available),
            "pit_safe": tf(pit_safe),
            "usable_for_factor_ablation": tf(usable_factor),
            "usable_for_dynamic_weight_research": tf(usable_dynamic),
            "exclusion_reason": "|".join(reasons),
            "evidence_quality": evidence_quality(pit_safe, outcome_available, benchmark_available, ticker_count),
            "data_freshness_status": freshness_status(as_of),
            **COMMON,
        })

    meta = {
        "date_count": date_count,
        "window_count": window_count,
        "ticker_count": len(all_tickers),
        "benchmark_present": benchmark_present,
        "outcome_present": outcome_present,
        "pit_present": pit_present,
    }
    return cache_rows, meta


def metadata_artifact_cache(path: Path, role: str) -> tuple[list[dict[str, str]], dict[str, object]]:
    artifact = rel(path)
    benchmark_present = "BENCHMARK" in path.name.upper()
    outcome_present = "EVIDENCE" in path.name.upper() and "GAP" not in path.name.upper()
    pit_present = role in {"MANIFEST_REFERENCE", "EVIDENCE_REFERENCE"}
    row = {
        "as_of_date": "UNKNOWN",
        "forward_window": "UNKNOWN",
        "source_artifact": artifact,
        "ticker_count": "0",
        "benchmark_available": tf(benchmark_present),
        "outcome_available": tf(outcome_present),
        "pit_safe": tf(pit_present),
        "usable_for_factor_ablation": "FALSE",
        "usable_for_dynamic_weight_research": "FALSE",
        "exclusion_reason": "REFERENCE_ARTIFACT_NOT_ROW_LEVEL_CACHE|NO_TICKER_EVIDENCE",
        "evidence_quality": "INSUFFICIENT",
        "data_freshness_status": "UNKNOWN",
        **COMMON,
    }
    meta = {
        "date_count": 0,
        "window_count": 0,
        "ticker_count": 0,
        "benchmark_present": benchmark_present,
        "outcome_present": outcome_present,
        "pit_present": pit_present,
    }
    return [row], meta


def audit_artifacts(paths: list[Path]) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    source_rows: list[dict[str, str]] = []
    cache_rows: list[dict[str, str]] = []
    eligibility_rows: list[dict[str, str]] = []
    for index, path in enumerate(paths, start=1):
        role = role_for(path)
        rows: list[dict[str, str]] = []
        fields: list[str] = []
        if path.suffix.lower() == ".csv":
            rows, fields = read_csv(path)
            artifact_cache, meta = aggregate_csv_artifact(path, rows, role) if rows else ([], {
                "date_count": 0,
                "window_count": 0,
                "ticker_count": 0,
                "benchmark_present": False,
                "outcome_present": False,
                "pit_present": False,
            })
        else:
            artifact_cache, meta = metadata_artifact_cache(path, role)
            if path.suffix.lower() == ".json":
                try:
                    json.loads(path.read_text(encoding="utf-8-sig"))
                except Exception:
                    meta["pit_present"] = False
        cache_rows.extend(artifact_cache)
        status = source_status(
            role,
            int(meta["ticker_count"]),
            bool(meta["benchmark_present"]),
            bool(meta["outcome_present"]),
            bool(meta["pit_present"]),
        )
        exclusion = "" if status == "USABLE" else "|".join(
            reason for reason in [
                "NO_ROW_LEVEL_CACHE_ROWS" if not artifact_cache else "",
                "NO_TICKER_EVIDENCE" if int(meta["ticker_count"]) == 0 else "",
                "OUTCOME_EVIDENCE_MISSING" if not bool(meta["outcome_present"]) else "",
                "BENCHMARK_EVIDENCE_MISSING" if not bool(meta["benchmark_present"]) else "",
                "PIT_SAFETY_NOT_ESTABLISHED" if not bool(meta["pit_present"]) else "",
            ]
            if reason
        )
        source_rows.append({
            "source_audit_id": f"V20_152_RANDOM_AS_OF_SOURCE_AUDIT_{index:03d}",
            "source_artifact": rel(path),
            "source_stage": stage_for(path),
            "artifact_role": role,
            "artifact_exists": "TRUE",
            "artifact_non_empty": tf(path.stat().st_size > 0),
            "artifact_type": path.suffix.lower().lstrip(".") or "unknown",
            "row_count": str(len(rows)) if path.suffix.lower() == ".csv" else "0",
            "source_sha256": sha_file(path),
            "date_evidence_count": str(meta["date_count"]),
            "forward_window_evidence_count": str(meta["window_count"]),
            "ticker_evidence_count": str(meta["ticker_count"]),
            "benchmark_evidence_present": tf(bool(meta["benchmark_present"])),
            "outcome_evidence_present": tf(bool(meta["outcome_present"])),
            "pit_evidence_present": tf(bool(meta["pit_present"])),
            "source_cache_status": status,
            "exclusion_reason": exclusion,
            "evidence_quality": evidence_quality(bool(meta["pit_present"]), bool(meta["outcome_present"]), bool(meta["benchmark_present"]), int(meta["ticker_count"])),
            "data_freshness_status": "HISTORICAL_REFERENCE" if status != "INELIGIBLE" else "UNKNOWN",
            **COMMON,
        })
        for cache in artifact_cache:
            eligible = cache["usable_for_factor_ablation"] == "TRUE" or cache["usable_for_dynamic_weight_research"] == "TRUE"
            eligibility_rows.append({
                "eligibility_audit_id": f"V20_152_RANDOM_AS_OF_ELIGIBILITY_AUDIT_{len(eligibility_rows)+1:04d}",
                "as_of_date": cache["as_of_date"],
                "forward_window": cache["forward_window"],
                "source_artifact": cache["source_artifact"],
                "ticker_count": cache["ticker_count"],
                "benchmark_available": cache["benchmark_available"],
                "outcome_available": cache["outcome_available"],
                "pit_safe": cache["pit_safe"],
                "eligible_for_cache": tf(eligible),
                "usable_for_factor_ablation": cache["usable_for_factor_ablation"],
                "usable_for_dynamic_weight_research": cache["usable_for_dynamic_weight_research"],
                "eligibility_status": "ELIGIBLE" if eligible else "INELIGIBLE",
                "exclusion_reason": cache["exclusion_reason"],
                "evidence_quality": cache["evidence_quality"],
                "data_freshness_status": cache["data_freshness_status"],
                **COMMON,
            })
        if not artifact_cache and fields == []:
            eligibility_rows.append({
                "eligibility_audit_id": f"V20_152_RANDOM_AS_OF_ELIGIBILITY_AUDIT_{len(eligibility_rows)+1:04d}",
                "as_of_date": "UNKNOWN",
                "forward_window": "UNKNOWN",
                "source_artifact": rel(path),
                "ticker_count": "0",
                "benchmark_available": "FALSE",
                "outcome_available": "FALSE",
                "pit_safe": "FALSE",
                "eligible_for_cache": "FALSE",
                "usable_for_factor_ablation": "FALSE",
                "usable_for_dynamic_weight_research": "FALSE",
                "eligibility_status": "INELIGIBLE",
                "exclusion_reason": "EMPTY_OR_UNREADABLE_ARTIFACT",
                "evidence_quality": "INSUFFICIENT",
                "data_freshness_status": "UNKNOWN",
                **COMMON,
            })
    return source_rows, cache_rows, eligibility_rows


def build_gap_plan(eligibility_rows: list[dict[str, str]], source_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    reason_actions = {
        "NO_TICKER_EVIDENCE": ("TICKER_EVIDENCE_GAP", "Bind an existing row-level ticker/as-of cache artifact; do not synthesize ticker rows."),
        "PIT_SAFETY_NOT_ESTABLISHED": ("PIT_SAFETY_GAP", "Attach existing point-in-time safety proof or exclude the artifact from dynamic research."),
        "OUTCOME_EVIDENCE_MISSING": ("OUTCOME_GAP", "Wait for or attach certified forward outcome evidence from existing local caches."),
        "BENCHMARK_EVIDENCE_MISSING": ("BENCHMARK_GAP", "Attach certified benchmark return evidence from existing local caches."),
        "REFERENCE_ARTIFACT_NOT_ROW_LEVEL_CACHE": ("REFERENCE_ONLY_GAP", "Use as lineage context only; locate its row-level source artifact."),
        "EMPTY_OR_UNREADABLE_ARTIFACT": ("SOURCE_READ_GAP", "Repair or replace the artifact export from its owning stage."),
    }
    for row in eligibility_rows:
        reasons = [reason for reason in row.get("exclusion_reason", "").split("|") if reason]
        if not reasons and row.get("usable_for_dynamic_weight_research") == "FALSE":
            reasons = ["INSUFFICIENT_DYNAMIC_WEIGHT_EVIDENCE"]
        for reason in reasons:
            gap_type, action = reason_actions.get(reason, ("CACHE_ELIGIBILITY_GAP", "Review source artifact and attach only existing certified evidence."))
            key = (row["source_artifact"], row["as_of_date"], row["forward_window"], gap_type)
            if key in seen:
                continue
            seen.add(key)
            gaps.append({
                "gap_id": f"V20_152_RANDOM_AS_OF_GAP_{len(gaps)+1:04d}",
                "source_artifact": row["source_artifact"],
                "as_of_date": row["as_of_date"],
                "forward_window": row["forward_window"],
                "gap_type": gap_type,
                "gap_reason": reason,
                "repair_action": action,
                "can_repair_without_new_market_data": tf(reason in {"REFERENCE_ARTIFACT_NOT_ROW_LEVEL_CACHE", "PIT_SAFETY_NOT_ESTABLISHED"}),
                "priority": "HIGH" if reason in {"OUTCOME_EVIDENCE_MISSING", "BENCHMARK_EVIDENCE_MISSING", "PIT_SAFETY_NOT_ESTABLISHED"} else "MEDIUM",
                **COMMON,
            })
    for source in source_rows:
        if source["source_cache_status"] == "INELIGIBLE" and source["source_artifact"] not in {gap["source_artifact"] for gap in gaps}:
            gaps.append({
                "gap_id": f"V20_152_RANDOM_AS_OF_GAP_{len(gaps)+1:04d}",
                "source_artifact": source["source_artifact"],
                "as_of_date": "UNKNOWN",
                "forward_window": "UNKNOWN",
                "gap_type": "SOURCE_INELIGIBLE_GAP",
                "gap_reason": source["exclusion_reason"] or "SOURCE_INELIGIBLE",
                "repair_action": "Use as audit context only unless the owning stage can export row-level as-of cache evidence.",
                "can_repair_without_new_market_data": "TRUE",
                "priority": "LOW",
                **COMMON,
            })
    return gaps


def safety_true_count(groups: list[list[dict[str, str]]]) -> int:
    count = 0
    for rows in groups:
        for row in rows:
            for field in SAFETY_FIELDS:
                if truthy(row.get(field)):
                    count += 1
    return count


def write_report(status: str, source_count: int, usable_sources: int, cache_count: int, dynamic_count: int, gap_count: int) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.152 Random-As-Of Backtest Cache Repair Report",
        "",
        f"- wrapper_status: {status}",
        f"- discovered_historical_artifact_count: {source_count}",
        f"- usable_source_artifact_count: {usable_sources}",
        f"- cache_row_count: {cache_count}",
        f"- dynamic_weight_usable_row_count: {dynamic_count}",
        f"- gap_count: {gap_count}",
        "- formal_activation_allowed: FALSE",
        "- promotion_ready: FALSE",
        "- performance_claim_created: FALSE",
        "",
        "This stage repairs the random-as-of cache index from existing artifacts only. It preserves research-only / staging-review-only mode and makes no official recommendation, ranking, weight, trade, broker, performance, ticker, price, benchmark, or outcome mutation.",
    ]) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    gate = {
        "gate_check_id": "V20_152_RANDOM_AS_OF_BACKTEST_CACHE_GATE_001",
        "v20_151_gate_consumed": "FALSE",
        "v20_151_status": "",
        "v20_151_allowed_for_v20_152": "FALSE",
        "staging_review_allowed": "FALSE",
        **SAFETY,
        "source_artifact_count": "0",
        "usable_source_artifact_count": "0",
        "partial_source_artifact_count": "0",
        "ineligible_source_artifact_count": "0",
        "cache_row_count": "0",
        "factor_ablation_usable_row_count": "0",
        "dynamic_weight_usable_row_count": "0",
        "gap_count": "0",
        "no_ticker_rows_fabricated": "TRUE",
        "no_historical_prices_fabricated": "TRUE",
        "no_benchmark_returns_fabricated": "TRUE",
        "no_outcomes_fabricated": "TRUE",
        "no_performance_claim_created": "TRUE",
        "no_upstream_outputs_mutated": "TRUE",
        "v20_153_random_as_of_review_allowed": "FALSE",
        "next_recommended_action": "V20.151_FORWARD_OBSERVATION_ACCUMULATION_REPAIR",
        "blocking_reason": reason,
        "random_as_of_backtest_cache_status": BLOCKED_STATUS,
        "research_only": "TRUE",
        "staging_review_only": "TRUE",
        "random_as_of_cache_repair_only": "TRUE",
        "audit_only": "TRUE",
    }
    write_csv(OUT_CACHE, CACHE_FIELDS, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_csv(OUT_SOURCE_AUDIT, SOURCE_FIELDS, [])
    write_csv(OUT_ELIGIBILITY_AUDIT, ELIGIBILITY_FIELDS, [])
    write_csv(OUT_GAP_PLAN, GAP_FIELDS, [])
    write_report(BLOCKED_STATUS, 0, 0, 0, 0, 0)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    before = upstream_hashes()
    required = [IN_V151_GATE, IN_V151_ACCUMULATION, IN_V151_SOURCE, IN_V151_ELIGIBILITY]
    missing = [path for path in required if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_OR_EMPTY_V20_151_OUTPUTS:" + ";".join(rel(path) for path in missing))

    v151_gate_rows, _ = read_csv(IN_V151_GATE)
    if not v151_gate_rows:
        return emit_blocked("EMPTY_V20_151_GATE")
    v151_gate = v151_gate_rows[0]
    v151_status = clean(v151_gate.get("forward_observation_accumulation_status"))
    v151_allowed = v151_status in V151_ALLOWED_STATUSES
    staging_allowed = truthy(v151_gate.get("staging_review_allowed"))
    formal_activation_allowed = truthy(v151_gate.get("formal_activation_allowed"))
    promotion_ready = truthy(v151_gate.get("promotion_ready"))
    if not (v151_allowed and staging_allowed and not formal_activation_allowed and not promotion_ready):
        return emit_blocked("V20_151_GATE_REQUIREMENTS_NOT_MET")

    artifacts = discover_artifacts()
    source_rows, cache_rows, eligibility_rows = audit_artifacts(artifacts)
    gap_rows = build_gap_plan(eligibility_rows, source_rows)

    usable_sources = sum(1 for row in source_rows if row["source_cache_status"] == "USABLE")
    partial_sources = sum(1 for row in source_rows if row["source_cache_status"] == "PARTIAL")
    ineligible_sources = sum(1 for row in source_rows if row["source_cache_status"] == "INELIGIBLE")
    factor_rows = sum(1 for row in cache_rows if row["usable_for_factor_ablation"] == "TRUE")
    dynamic_rows = sum(1 for row in cache_rows if row["usable_for_dynamic_weight_research"] == "TRUE")
    safety_count = safety_true_count([source_rows, cache_rows, eligibility_rows, gap_rows])
    after = upstream_hashes()
    upstream_mutated = before != after

    if safety_count or upstream_mutated:
        status = BLOCKED_STATUS
        blocking_reason = "SAFETY_OR_UPSTREAM_MUTATION_FAILURE"
    elif factor_rows == 0 and dynamic_rows == 0:
        status = WARN_STATUS
        blocking_reason = ""
    elif dynamic_rows >= MIN_DYNAMIC_ROWS_FOR_PASS and not gap_rows:
        status = PASS_STATUS
        blocking_reason = ""
    else:
        status = PARTIAL_STATUS
        blocking_reason = ""
    next_allowed = status in {PASS_STATUS, PARTIAL_STATUS}

    gate = {
        "gate_check_id": "V20_152_RANDOM_AS_OF_BACKTEST_CACHE_GATE_001",
        "v20_151_gate_consumed": "TRUE",
        "v20_151_status": v151_status,
        "v20_151_allowed_for_v20_152": tf(v151_allowed),
        "staging_review_allowed": "TRUE",
        **SAFETY,
        "source_artifact_count": str(len(source_rows)),
        "usable_source_artifact_count": str(usable_sources),
        "partial_source_artifact_count": str(partial_sources),
        "ineligible_source_artifact_count": str(ineligible_sources),
        "cache_row_count": str(len(cache_rows)),
        "factor_ablation_usable_row_count": str(factor_rows),
        "dynamic_weight_usable_row_count": str(dynamic_rows),
        "gap_count": str(len(gap_rows)),
        "no_ticker_rows_fabricated": "TRUE",
        "no_historical_prices_fabricated": "TRUE",
        "no_benchmark_returns_fabricated": "TRUE",
        "no_outcomes_fabricated": "TRUE",
        "no_performance_claim_created": "TRUE",
        "no_upstream_outputs_mutated": tf(not upstream_mutated),
        "v20_153_random_as_of_review_allowed": tf(next_allowed),
        "next_recommended_action": "V20.153_RANDOM_AS_OF_REVIEW" if next_allowed else "V20.152_RANDOM_AS_OF_BACKTEST_CACHE_REPAIR",
        "blocking_reason": blocking_reason,
        "random_as_of_backtest_cache_status": status,
        "research_only": "TRUE",
        "staging_review_only": "TRUE",
        "random_as_of_cache_repair_only": "TRUE",
        "audit_only": "TRUE",
    }

    write_csv(OUT_CACHE, CACHE_FIELDS, cache_rows)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_csv(OUT_SOURCE_AUDIT, SOURCE_FIELDS, source_rows)
    write_csv(OUT_ELIGIBILITY_AUDIT, ELIGIBILITY_FIELDS, eligibility_rows)
    write_csv(OUT_GAP_PLAN, GAP_FIELDS, gap_rows)
    write_report(status, len(source_rows), usable_sources, len(cache_rows), dynamic_rows, len(gap_rows))

    print(status)
    print("V20_151_GATE_CONSUMED=TRUE")
    print(f"V20_151_ALLOWED_FOR_V20_152={tf(v151_allowed)}")
    print("STAGING_REVIEW_ALLOWED=TRUE")
    print("FORMAL_ACTIVATION_ALLOWED=FALSE")
    print("PROMOTION_READY=FALSE")
    print(f"SOURCE_ARTIFACT_COUNT={len(source_rows)}")
    print(f"USABLE_SOURCE_ARTIFACT_COUNT={usable_sources}")
    print(f"PARTIAL_SOURCE_ARTIFACT_COUNT={partial_sources}")
    print(f"INELIGIBLE_SOURCE_ARTIFACT_COUNT={ineligible_sources}")
    print(f"CACHE_ROW_COUNT={len(cache_rows)}")
    print(f"FACTOR_ABLATION_USABLE_ROW_COUNT={factor_rows}")
    print(f"DYNAMIC_WEIGHT_USABLE_ROW_COUNT={dynamic_rows}")
    print(f"GAP_COUNT={len(gap_rows)}")
    print("TICKER_ROWS_FABRICATED=0")
    print("HISTORICAL_PRICES_FABRICATED=0")
    print("BENCHMARK_RETURNS_FABRICATED=0")
    print("OUTCOMES_FABRICATED=0")
    print("PERFORMANCE_CLAIM_CREATED=FALSE")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutated)}")
    print(f"SAFETY_TRUE_COUNT={safety_count}")
    print(f"V20_153_RANDOM_AS_OF_REVIEW_ALLOWED={tf(next_allowed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
