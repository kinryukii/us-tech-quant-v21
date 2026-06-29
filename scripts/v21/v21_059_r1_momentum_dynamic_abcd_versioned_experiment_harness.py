#!/usr/bin/env python
"""Build research-only A0/A1/B/C current-ranking experiment variants."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Iterable


STAGE_ID = "V21.059-R1"
PASS_STATUS = "PASS_V21_059_R1_ABCD_EXPERIMENT_HARNESS_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_059_R1_ABCD_HARNESS_READY_WITH_LINEAGE_OR_DATA_WARN"
FAIL_A0 = "FAIL_V21_059_R1_A0_CONTROL_MUTATION_OR_RECOMPUTE"
FAIL_HARDCODED = "FAIL_V21_059_R1_HARDCODED_INCLUSION_VIOLATION"
FAIL_PRICE = "FAIL_V21_059_R1_LOCAL_PRICE_MISSING_RANKED"
FAIL_TQQQ = "FAIL_V21_059_R1_TQQQ_IPO_WATCH_POLICY_VIOLATION"
FAIL_MUTATION = "FAIL_V21_059_R1_FORBIDDEN_MUTATION_DETECTED"

OUT_REL = Path("outputs/v21/experiments/momentum_dynamic")
A0_REL = Path("outputs/v21/experiments/version_control/V21_056_R2_A0_CANONICAL_CONTROL_VIEW.csv")
R1_SNAPSHOT_REL = Path("outputs/v21/experiments/version_control/V21_056_R1_A0_LEDGER_SNAPSHOT.csv")
BASELINE_REL = Path("outputs/v18/candidates/V18_CURRENT_RANKED_CANDIDATES.csv")
DISCOVERY_REL = Path("outputs/v21/unified_pool/V21_057_R2_ALGORITHMIC_DISCOVERY_POOL.csv")
MOMENTUM_REL = Path("outputs/v21/momentum/V21_058_R4_REPAIRED_NEWLY_LISTED_MOMENTUM_LEDGER.csv")
R4_SUMMARY_REL = Path("outputs/v21/momentum/V21_058_R4_SUMMARY.json")

CONFIG_NAME = "V21_059_R1_VARIANT_CONFIGS.csv"
A0_NAME = "V21_059_R1_A0_CURRENT_TESTING_LOCKED_VIEW.csv"
A1_NAME = "V21_059_R1_A1_BASELINE_REPLAY_RANKING.csv"
B_NAME = "V21_059_R1_B_MOMENTUM_STATIC_RANKING.csv"
C_NAME = "V21_059_R1_C_MOMENTUM_DYNAMIC_RANKING.csv"
COMPONENTS_NAME = "V21_059_R1_VARIANT_SCORE_COMPONENTS.csv"
TOP20_NAME = "V21_059_R1_ABCD_TOP20_COMPARISON.csv"
TOP50_NAME = "V21_059_R1_ABCD_TOP50_COMPARISON.csv"
FORCED_NAME = "V21_059_R1_FORCED_TICKER_VARIANT_AUDIT.csv"
EXCLUSION_NAME = "V21_059_R1_VARIANT_EXCLUSION_AUDIT.csv"
LINEAGE_NAME = "V21_059_R1_LINEAGE_AUDIT.csv"
SUMMARY_NAME = "V21_059_R1_SUMMARY.json"

FORCED = ("MU", "SNDK", "DRAM", "SPCX", "USD", "SMH", "SOXX", "SOXL", "QQQ", "TQQQ", "SQQQ")
COMPONENT_FIELDS = [
    "ticker", "as_of_date", "variant_id", "instrument_type", "asset_class",
    "theme", "base_score", "base_score_source", "base_rank",
    "base_rank_source", "momentum_score", "momentum_score_source",
    "absolute_momentum_score", "relative_momentum_score",
    "momentum_acceleration_score", "trend_persistence_score",
    "exhaustion_risk_score", "momentum_state", "chase_permission",
    "risk_size_bucket", "static_momentum_weight", "dynamic_momentum_weight",
    "applied_momentum_weight", "final_shadow_score", "final_shadow_rank",
    "market_regime", "regime_fallback_used", "price_freshness_status",
    "newly_listed_policy_bucket", "local_history_gap_flag",
    "data_sufficiency_status", "eligible_for_variant_ranking",
    "variant_exclusion_reason", "entered_by_forced_audit_only",
    "price_available", "risk_off_confirmed", "research_only",
]


def clean(value: object) -> str:
    return str(value or "").strip()


def tf(value: object) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return "TRUE" if clean(value).upper() == "TRUE" else "FALSE"


def num(value: object) -> float | None:
    try:
        return float(clean(value))
    except ValueError:
        return None


def fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.10f}"


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.is_file() or path.stat().st_size == 0:
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def write_csv(path: Path, rows: Iterable[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                field: "TRUE" if row.get(field) is True else "FALSE" if row.get(field) is False
                else "" if row.get(field) is None else row.get(field, "")
                for field in fields
            })


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def row_count(path: Path) -> int:
    return len(read_csv(path)[0])


def protected_hashes(root: Path) -> dict[str, dict[str, str]]:
    groups = {"a0": {}, "official": {}, "real_book": {}, "broker": {}}
    for path in (root / A0_REL, root / R1_SNAPSHOT_REL):
        if path.is_file():
            groups["a0"][rel(root, path)] = sha(path)
    for base in (root / "outputs", root / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or root / OUT_REL in path.parents:
                continue
            text = rel(root, path).lower().replace("-", "_").replace(" ", "_")
            if "broker" in text:
                groups["broker"][rel(root, path)] = sha(path)
            elif "real_book" in text or "realbook" in text:
                groups["real_book"][rel(root, path)] = sha(path)
            elif "official" in text and any(token in text for token in ("rank", "weight", "recommend", "allocation")):
                groups["official"][rel(root, path)] = sha(path)
    return groups


def changed(before: dict[str, str], after: dict[str, str]) -> bool:
    return any(before.get(key) != after.get(key) for key in set(before) | set(after))


def rank_rows(rows: list[dict[str, object]], score_field: str = "final_shadow_score") -> list[dict[str, object]]:
    eligible = [row for row in rows if row["eligible_for_variant_ranking"] == "TRUE"]
    eligible.sort(key=lambda row: (-(num(row.get(score_field)) or -1), clean(row.get("ticker"))))
    for rank, row in enumerate(eligible, 1):
        row["final_shadow_rank"] = rank
    return eligible


def top_unique_a0(rows: list[dict[str, str]], limit: int) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in sorted(rows, key=lambda item: (num(item.get("rank")) or 10**9, clean(item.get("ticker")))):
        ticker = clean(row.get("ticker")).upper()
        rank = int(num(row.get("rank")) or 10**9)
        if ticker and ticker not in result:
            result[ticker] = rank
        if len(result) >= limit:
            break
    return result


def variant_map(rows: list[dict[str, object]], limit: int) -> dict[str, int]:
    return {
        clean(row.get("ticker")).upper(): int(num(row.get("final_shadow_rank")) or 0)
        for row in rows if (num(row.get("final_shadow_rank")) or 10**9) <= limit
    }


def comparison_rows(
    limit: int, a0: dict[str, int], a1: dict[str, int],
    b: dict[str, int], c: dict[str, int], momentum: dict[str, dict[str, str]],
) -> list[dict[str, object]]:
    tickers = sorted(set(a0) | set(a1) | set(b) | set(c))
    result = []
    for ticker in tickers:
        meta = momentum.get(ticker, {})
        result.append({
            "ticker": ticker, "in_a0_top20" if limit == 20 else "in_a0_top50": tf(ticker in a0),
            "in_a1_top20" if limit == 20 else "in_a1_top50": tf(ticker in a1),
            "in_b_top20" if limit == 20 else "in_b_top50": tf(ticker in b),
            "in_c_top20" if limit == 20 else "in_c_top50": tf(ticker in c),
            "rank_a0": a0.get(ticker, ""), "rank_a1": a1.get(ticker, ""),
            "rank_b": b.get(ticker, ""), "rank_c": c.get(ticker, ""),
            "instrument_type": meta.get("instrument_type", "STOCK"),
            "theme": meta.get("theme", ""), "momentum_state": meta.get("momentum_state", ""),
            "chase_permission": meta.get("chase_permission", ""),
            "risk_size_bucket": meta.get("risk_size_bucket", ""), "research_only": "TRUE",
        })
    return result


def run_stage(root: Path) -> dict[str, object]:
    root = root.resolve()
    out = root / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    before = protected_hashes(root)
    a0_rows, a0_fields = read_csv(root / A0_REL)
    baseline_rows, _ = read_csv(root / BASELINE_REL)
    momentum_rows, _ = read_csv(root / MOMENTUM_REL)
    discovery_rows, _ = read_csv(root / DISCOVERY_REL)
    momentum = {clean(row.get("ticker")).upper(): row for row in momentum_rows}
    discovery = {clean(row.get("ticker")).upper(): row for row in discovery_rows}
    baseline = {clean(row.get("ticker")).upper(): row for row in baseline_rows}
    regime_values = [clean(row.get("market_regime")).upper() for row in momentum_rows if clean(row.get("market_regime"))]
    market_regime = next((value for value in regime_values if value != "UNKNOWN"), "UNKNOWN")
    weight_map = {"RISK_OFF": .05, "NEUTRAL": .15, "RISK_ON": .25, "STRONG_RISK_ON": .35}
    dynamic_weight = weight_map.get(market_regime, .15)
    regime_fallback = market_regime not in weight_map

    a0_view = []
    for source in a0_rows:
        row = dict(source)
        row.update({
            "variant_id": "A0_CURRENT_TESTING_LOCKED", "frozen_control": "TRUE",
            "recomputed": "FALSE", "rank_score_lineage": "JOINED_FROM_CURRENT_V18_RANKING_SOURCE",
            "research_only": "TRUE",
        })
        a0_view.append(row)
    a0_output_fields = list(dict.fromkeys([*a0_fields, "frozen_control", "recomputed", "rank_score_lineage", "research_only"]))
    write_csv(out / A0_NAME, a0_view, a0_output_fields)

    configs = [
        {"variant_id": "A0_CURRENT_TESTING_LOCKED", "variant_description": "Frozen live-forward current testing control.", "uses_a0_frozen_control": "TRUE", "uses_baseline_replay": "FALSE", "uses_momentum_overlay": "FALSE", "momentum_weight_type": "NONE", "fixed_momentum_weight": "", "dynamic_weight_map": "", "market_regime_source": "", "research_only": "TRUE"},
        {"variant_id": "A1_BASELINE_REPLAY_CURRENT", "variant_description": "Current baseline replay from existing V18 ranking source.", "uses_a0_frozen_control": "FALSE", "uses_baseline_replay": "TRUE", "uses_momentum_overlay": "FALSE", "momentum_weight_type": "NONE", "fixed_momentum_weight": "0", "dynamic_weight_map": "", "market_regime_source": "", "research_only": "TRUE"},
        {"variant_id": "B_MOMENTUM_STATIC_R1", "variant_description": "Static 20% momentum overlay.", "uses_a0_frozen_control": "FALSE", "uses_baseline_replay": "TRUE", "uses_momentum_overlay": "TRUE", "momentum_weight_type": "STATIC", "fixed_momentum_weight": "0.20", "dynamic_weight_map": "", "market_regime_source": rel(root, root / MOMENTUM_REL), "research_only": "TRUE"},
        {"variant_id": "C_MOMENTUM_DYNAMIC_R1", "variant_description": "Regime-conditioned momentum overlay.", "uses_a0_frozen_control": "FALSE", "uses_baseline_replay": "TRUE", "uses_momentum_overlay": "TRUE", "momentum_weight_type": "DYNAMIC", "fixed_momentum_weight": "", "dynamic_weight_map": "RISK_OFF=0.05|NEUTRAL=0.15|RISK_ON=0.25|STRONG_RISK_ON=0.35|UNKNOWN=0.15", "market_regime_source": rel(root, root / MOMENTUM_REL), "research_only": "TRUE"},
    ]
    write_csv(out / CONFIG_NAME, configs, list(configs[0].keys()))

    components: list[dict[str, object]] = []
    exclusions: list[dict[str, object]] = []
    a1_fallback = False
    for ticker, base in baseline.items():
        score = num(base.get("composite_candidate_score"))
        rank = num(base.get("rank"))
        if score is not None:
            source = "CURRENT_RANKING_SCORE"
        elif rank is not None and baseline_rows:
            score = 100 * (len(baseline_rows) - rank + 1) / len(baseline_rows)
            source, a1_fallback = "RANK_NORMALIZED_FALLBACK", True
        else:
            source = "MISSING_NOT_DERIVED"
        meta = momentum.get(ticker, {})
        common = {
            "ticker": ticker, "as_of_date": clean(base.get("latest_price_date") or meta.get("as_of_date")),
            "instrument_type": clean(meta.get("instrument_type") or "STOCK"),
            "asset_class": clean(meta.get("asset_class") or "EQUITY"), "theme": clean(meta.get("theme")),
            "base_score": fmt(score), "base_score_source": source, "base_rank": clean(base.get("rank")),
            "base_rank_source": "CURRENT_V18_RANKING", "momentum_score": "",
            "momentum_score_source": "MISSING_NOT_ELIGIBLE",
            "absolute_momentum_score": clean(meta.get("absolute_momentum_score")),
            "relative_momentum_score": clean(meta.get("relative_momentum_score")),
            "momentum_acceleration_score": clean(meta.get("momentum_acceleration_score")),
            "trend_persistence_score": clean(meta.get("trend_persistence_score")),
            "exhaustion_risk_score": clean(meta.get("exhaustion_risk_score")),
            "momentum_state": clean(meta.get("momentum_state")),
            "chase_permission": clean(meta.get("chase_permission")),
            "risk_size_bucket": clean(meta.get("risk_size_bucket")),
            "market_regime": market_regime, "regime_fallback_used": tf(regime_fallback),
            "price_freshness_status": clean(meta.get("price_freshness_status")),
            "newly_listed_policy_bucket": clean(meta.get("repaired_r4_policy_bucket")),
            "local_history_gap_flag": tf(meta.get("local_history_gap_flag")),
            "data_sufficiency_status": clean(meta.get("data_sufficiency_status")),
            "entered_by_forced_audit_only": tf(meta.get("entered_by_forced_audit_only")),
            "price_available": tf(meta.get("price_available")),
            "risk_off_confirmed": tf(meta.get("risk_off_confirmed")), "research_only": "TRUE",
        }
        a1 = {
            **common, "variant_id": "A1_BASELINE_REPLAY_CURRENT",
            "static_momentum_weight": "0", "dynamic_momentum_weight": "0",
            "applied_momentum_weight": "0", "final_shadow_score": fmt(score),
            "eligible_for_variant_ranking": tf(score is not None),
            "variant_exclusion_reason": "" if score is not None else "MISSING_BASE_SCORE_AND_RANK",
        }
        components.append(a1)

        momentum_score = num(meta.get("final_momentum_score_for_r3"))
        scope = clean(meta.get("r4_score_scope"))
        forced_only = tf(meta.get("entered_by_forced_audit_only")) == "TRUE"
        price_ok = tf(meta.get("price_available")) == "TRUE"
        local_gap = clean(meta.get("repaired_r4_policy_bucket")) == "LOCAL_HISTORY_GAP_NOT_NEWLY_LISTED"
        comparable = scope in {"COMPARABLE_FULL_HISTORY", "COMPARABLE_LIMITED_HISTORY_WITH_RISK_CAP"}
        eligible = score is not None and momentum_score is not None and comparable and not forced_only and price_ok and not local_gap
        reasons = []
        if score is None:
            reasons.append("MISSING_BASE_SCORE_AND_RANK")
        if momentum_score is None:
            reasons.append("MISSING_MOMENTUM_SCORE")
        if not comparable:
            reasons.append("R4_POLICY_NOT_COMPARABLE_FOR_VARIANT")
        if forced_only:
            reasons.append("FORCED_AUDIT_ONLY")
        if not price_ok:
            reasons.append("LOCAL_PRICE_NOT_FOUND")
        if local_gap:
            reasons.append("LOCAL_HISTORY_GAP_INSUFFICIENT_FOR_VARIANT")
        mom_source = (
            "V21_058_R4_FULL_HISTORY_MOMENTUM" if scope == "COMPARABLE_FULL_HISTORY" and momentum_score is not None
            else "V21_058_R4_LIMITED_HISTORY_MOMENTUM" if scope == "COMPARABLE_LIMITED_HISTORY_WITH_RISK_CAP" and momentum_score is not None
            else "V21_058_R4_IPO_WATCH_SCORE" if scope == "SEPARATE_IPO_WATCH_BOARD_ONLY" and momentum_score is not None
            else "MISSING_DATA_INSUFFICIENT" if not price_ok or momentum_score is None
            else "MISSING_NOT_ELIGIBLE"
        )
        for variant_id, weight, static_weight, dynamic_value in (
            ("B_MOMENTUM_STATIC_R1", .20, .20, dynamic_weight),
            ("C_MOMENTUM_DYNAMIC_R1", dynamic_weight, .20, dynamic_weight),
        ):
            final_score = score * (1 - weight) + momentum_score * weight if eligible else None
            row = {
                **common, "variant_id": variant_id, "momentum_score": fmt(momentum_score),
                "momentum_score_source": mom_source, "static_momentum_weight": fmt(static_weight),
                "dynamic_momentum_weight": fmt(dynamic_value), "applied_momentum_weight": fmt(weight),
                "final_shadow_score": fmt(final_score), "eligible_for_variant_ranking": tf(eligible),
                "variant_exclusion_reason": "" if eligible else "|".join(dict.fromkeys(reasons)),
            }
            components.append(row)
            if not eligible:
                exclusions.append({
                    "ticker": ticker, "variant_id": variant_id,
                    "instrument_type": common["instrument_type"],
                    "base_score_available": tf(score is not None),
                    "momentum_score_available": tf(momentum_score is not None),
                    "price_available": tf(price_ok), "r4_score_scope": scope,
                    "newly_listed_policy_bucket": common["newly_listed_policy_bucket"],
                    "exclusion_reason": row["variant_exclusion_reason"], "research_only": "TRUE",
                })

    a1_rows = rank_rows([row for row in components if row["variant_id"] == "A1_BASELINE_REPLAY_CURRENT"])
    b_rows = rank_rows([row for row in components if row["variant_id"] == "B_MOMENTUM_STATIC_R1"])
    c_rows = rank_rows([row for row in components if row["variant_id"] == "C_MOMENTUM_DYNAMIC_R1"])
    write_csv(out / A1_NAME, a1_rows, COMPONENT_FIELDS)
    write_csv(out / B_NAME, b_rows, COMPONENT_FIELDS)
    write_csv(out / C_NAME, c_rows, COMPONENT_FIELDS)
    write_csv(out / COMPONENTS_NAME, components, COMPONENT_FIELDS)
    write_csv(out / EXCLUSION_NAME, exclusions, ["ticker", "variant_id", "instrument_type", "base_score_available", "momentum_score_available", "price_available", "r4_score_scope", "newly_listed_policy_bucket", "exclusion_reason", "research_only"])

    a0_20, a0_50 = top_unique_a0(a0_rows, 20), top_unique_a0(a0_rows, 50)
    a1_20, b_20, c_20 = variant_map(a1_rows, 20), variant_map(b_rows, 20), variant_map(c_rows, 20)
    a1_50, b_50, c_50 = variant_map(a1_rows, 50), variant_map(b_rows, 50), variant_map(c_rows, 50)
    top20 = comparison_rows(20, a0_20, a1_20, b_20, c_20, momentum)
    top50 = comparison_rows(50, a0_50, a1_50, b_50, c_50, momentum)
    write_csv(out / TOP20_NAME, top20, list(top20[0].keys()))
    write_csv(out / TOP50_NAME, top50, list(top50[0].keys()))

    a0_all = {clean(row.get("ticker")).upper(): int(num(row.get("rank")) or 0) for row in a0_rows}
    maps = {
        "a1": {clean(row["ticker"]): int(row["final_shadow_rank"]) for row in a1_rows},
        "b": {clean(row["ticker"]): int(row["final_shadow_rank"]) for row in b_rows},
        "c": {clean(row["ticker"]): int(row["final_shadow_rank"]) for row in c_rows},
    }
    component_lookup = {(clean(row["ticker"]), clean(row["variant_id"])): row for row in components}
    forced_rows = []
    for ticker in FORCED:
        b_comp = component_lookup.get((ticker, "B_MOMENTUM_STATIC_R1"), {})
        c_comp = component_lookup.get((ticker, "C_MOMENTUM_DYNAMIC_R1"), {})
        forced_only = tf(momentum.get(ticker, {}).get("entered_by_forced_audit_only")) == "TRUE"
        violation = forced_only and (ticker in maps["b"] or ticker in maps["c"])
        forced_rows.append({
            "ticker": ticker, "present_in_a0": tf(ticker in a0_all),
            "present_in_a1": tf(ticker in maps["a1"]), "present_in_b": tf(ticker in maps["b"]),
            "present_in_c": tf(ticker in maps["c"]), "rank_a0": a0_all.get(ticker, ""),
            "rank_a1": maps["a1"].get(ticker, ""), "rank_b": maps["b"].get(ticker, ""),
            "rank_c": maps["c"].get(ticker, ""), "eligible_for_b": b_comp.get("eligible_for_variant_ranking", "FALSE"),
            "eligible_for_c": c_comp.get("eligible_for_variant_ranking", "FALSE"),
            "score_source": b_comp.get("base_score_source", "MISSING_NOT_DERIVED"),
            "momentum_score_source": b_comp.get("momentum_score_source", "MISSING_DATA_INSUFFICIENT"),
            "exclusion_reason": b_comp.get("variant_exclusion_reason", "NOT_IN_BASELINE_SOURCE"),
            "hardcoded_inclusion_violation_flag": tf(violation), "research_only": "TRUE",
        })
    write_csv(out / FORCED_NAME, forced_rows, list(forced_rows[0].keys()))

    after = protected_hashes(root)
    a0_modified = changed(before["a0"], after["a0"])
    official_modified = changed(before["official"], after["official"])
    real_modified = changed(before["real_book"], after["real_book"])
    broker_modified = changed(before["broker"], after["broker"])
    lineage_sources = [
        ("a0_canonical_control", root / A0_REL, "JOINED_FROM_CURRENT_V18_RANKING_SOURCE"),
        ("a1_baseline_source", root / BASELINE_REL, "CURRENT_RANKING_SCORE"),
        ("v21_057_r2_discovery", root / DISCOVERY_REL, "READ_ONLY"),
        ("v21_058_r4_momentum", root / MOMENTUM_REL, "READ_ONLY"),
    ]
    lineage = [{
        "source_role": role, "source_path": rel(root, path), "row_count": row_count(path),
        "lineage_note": note, "a0_modified": tf(a0_modified),
        "official_ranking_or_weight_modified": tf(official_modified),
        "real_book_modified": tf(real_modified), "broker_modified": tf(broker_modified),
        "research_only": "TRUE",
    } for role, path, note in lineage_sources]
    write_csv(out / LINEAGE_NAME, lineage, list(lineage[0].keys()))

    hardcoded = sum(row["hardcoded_inclusion_violation_flag"] == "TRUE" for row in forced_rows)
    local_price_ranked = sum(
        row["price_available"] != "TRUE" for row in [*b_rows, *c_rows]
    )
    tqqq_violation = sum(
        clean(row.get("ticker")) == "TQQQ"
        and clean(row.get("newly_listed_policy_bucket")) in {"IPO_EARLY_MOMENTUM_WATCH", "TRUE_IPO_EARLY_WATCH"}
        for row in [*b_rows, *c_rows]
    )
    leveraged_full = sum(
        row["instrument_type"] == "LEVERAGED_LONG_ETF" and row["risk_size_bucket"] == "FULL_SIZE_ALLOWED"
        for row in [*b_rows, *c_rows]
    )
    inverse_bad = sum(
        row["instrument_type"] == "INVERSE_ETF" and row["risk_off_confirmed"] != "TRUE"
        and (row["chase_permission"] != "HEDGE_ONLY" or row["risk_size_bucket"] not in {"WATCH_ONLY", "BLOCKED"})
        for row in [*b_rows, *c_rows]
    )
    forced_missing = len(set(FORCED) - {row["ticker"] for row in forced_rows})
    a0_recomputed = False
    if a0_modified or a0_recomputed:
        final, decision = FAIL_A0, "STOP_AND_RESTORE_A0_CONTROL"
    elif official_modified or real_modified or broker_modified:
        final, decision = FAIL_MUTATION, "STOP_AND_RESTORE_FORBIDDEN_MUTATION"
    elif hardcoded:
        final, decision = FAIL_HARDCODED, "REPAIR_FORCED_INCLUSION_LOGIC"
    elif local_price_ranked:
        final, decision = FAIL_PRICE, "REPAIR_VARIANT_ELIGIBILITY_FILTERS"
    elif tqqq_violation:
        final, decision = FAIL_TQQQ, "REPAIR_LISTING_AGE_POLICY_PROPAGATION"
    elif a1_fallback or any(ticker not in maps["b"] for ticker in ("DRAM", "SPCX")):
        final, decision = PARTIAL_STATUS, "ABCD_HARNESS_READY_FOR_V21_060_WITH_DATA_OR_LINEAGE_WARN"
    else:
        final, decision = PASS_STATUS, "ABCD_VARIANT_HARNESS_READY_FOR_V21_060_BACKTEST_AND_FORWARD_LEDGER"
    summary = {
        "FINAL_STATUS": final, "DECISION": decision, "stage_id": STAGE_ID, "research_only": True,
        "a0_row_count": len(a0_view), "a1_row_count": len(a1_rows), "b_row_count": len(b_rows), "c_row_count": len(c_rows),
        "a0_top20_count": len(a0_20), "a1_top20_count": len(a1_20), "b_top20_count": len(b_20), "c_top20_count": len(c_20),
        "a0_recomputed": a0_recomputed, "a0_modified": a0_modified, "a1_fallback_used": a1_fallback,
        "market_regime": market_regime, "regime_fallback_used": regime_fallback,
        "b_static_momentum_weight": .20, "c_dynamic_momentum_weight": dynamic_weight,
        "b_eligible_count": len(b_rows), "c_eligible_count": len(c_rows),
        "b_excluded_count": sum(row["variant_id"] == "B_MOMENTUM_STATIC_R1" for row in exclusions),
        "c_excluded_count": sum(row["variant_id"] == "C_MOMENTUM_DYNAMIC_R1" for row in exclusions),
        "top20_overlap_a0_vs_a1": len(set(a0_20) & set(a1_20)),
        "top20_overlap_a1_vs_b": len(set(a1_20) & set(b_20)),
        "top20_overlap_a1_vs_c": len(set(a1_20) & set(c_20)),
        "top20_overlap_b_vs_c": len(set(b_20) & set(c_20)),
        "forced_audit_count": len(forced_rows), "forced_audit_missing_count": forced_missing,
        "hardcoded_inclusion_violation_count": hardcoded,
        "local_price_missing_ranked_violation_count": local_price_ranked,
        "tqqq_ipo_watch_violation_count": tqqq_violation,
        "leveraged_full_size_violation_count": leveraged_full,
        "inverse_non_hedge_violation_count": inverse_bad,
        "official_mutation_detected": official_modified, "real_book_mutation_detected": real_modified,
        "broker_mutation_detected": broker_modified,
        "next_recommended_stage": "V21.060_BACKTEST_AND_FORWARD_LEDGER" if final in {PASS_STATUS, PARTIAL_STATUS} else "REPAIR_V21_059_R1_HARNESS",
    }
    write_json(out / SUMMARY_NAME, summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    summary = run_stage(args.root)
    print(json.dumps(summary, indent=2))
    return 1 if clean(summary["FINAL_STATUS"]).startswith("FAIL_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
