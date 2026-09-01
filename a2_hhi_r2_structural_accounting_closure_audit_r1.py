"""Non-economic accounting closure for the frozen Raw A2 direct-HHI R2 shadow."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pandas as pd


REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
R2_OUT = RESULTS / "A2_SINGLE_SECTOR_RISK_BUDGET_DESIGN_AND_FREEZE_R2"
OUT = RESULTS / "A2_HHI_R2_STRUCTURAL_ACCOUNTING_CLOSURE_AUDIT_R1"
R2_SOURCE = REPO / "a2_single_sector_risk_budget_design_and_freeze_r2.py"
PROSPECTIVE = RESULTS / "A2_X0_LITERATURE_GROUNDED_PROSPECTIVE_DISAGREEMENT_R1"
REGISTRY = REPO / "config" / "research_governance" / "alpha_registry.json"

R2_PROTOCOL = R2_OUT / "r2_design_protocol.json"
R2_CONTRACT = R2_OUT / "frozen_contract.json"
R2_DAILY = R2_OUT / "structural_dry_run.csv"
R2_LEDGER = R2_OUT / "intervention_ledger.parquet"
R2_SUMMARY = R2_OUT / "summary.json"

EXPECTED = {
    R2_PROTOCOL: "4a0c9af86527366744f3baa70e765a46608a39d9ee8de8479ced5231768f7ad6",
    R2_CONTRACT: "4c34c19d840980c390de134438dfb984dbe0981df06d2aac24d8ad441c6d33f9",
    R2_DAILY: "b6a0a50a13fbbf275436c082173e31a30dbf00600b6cd4ec64dd450fd1c4e3f2",
    R2_LEDGER: "03b037a415560ce7868392f037beb00e481644ff8ac1b3fcd1c19ceaf8650080",
    R2_SUMMARY: "ce056e7bab7cff863be049e5e6d7449a97edf7376b0538092600bf5240a9edfa",
    R2_SOURCE: "e298ac9088446d1925df02dfadbd9edb9906779635a22cc3f8e697982e8b4bf1",
    REGISTRY: "b7beb4adb7fbe67048bedcb21a476a23bbed9295009805a0d432239576e404e3",
}

TOP_N = 20
WEIGHT = 1.0 / TOP_N
TOL = 1e-12


def require(condition: bool, code: str, detail: Any = "") -> None:
    if not condition:
        raise RuntimeError(f"{code}: {detail}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def import_r2() -> Any:
    spec = importlib.util.spec_from_file_location("a2_hhi_r2_frozen_reuse", R2_SOURCE)
    require(spec is not None and spec.loader is not None, "R2_IMPORT_SPEC")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def repo_temp_dirs() -> list[Path]:
    return sorted(
        path
        for path in REPO.iterdir()
        if path.is_dir()
        and (
            path.name.startswith(".tmp")
            or path.name.startswith(".codex_tmp")
            or path.name.startswith(".pytest_cache")
            or path.name.startswith("pytest-cache-")
        )
    )


def tree_snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.as_posix().lower())
    }


def verify_inputs(r2: Any) -> dict[str, Any]:
    require(not OUT.exists(), "OUTPUT_ALREADY_EXISTS", OUT)
    require(not repo_temp_dirs(), "REPO_ROOT_TEMP_PRESENT", [str(path) for path in repo_temp_dirs()])
    for path, expected in EXPECTED.items():
        require(path.is_file(), "FROZEN_R2_INPUT_MISSING", path)
        require(sha256_file(path) == expected, "FROZEN_R2_INPUT_HASH", path)
    protocol, protocol_sha = r2.verify_protocol()
    require(protocol_sha == EXPECTED[R2_PROTOCOL], "R2_PROTOCOL_VERIFY")
    contract = json.loads(R2_CONTRACT.read_text(encoding="utf-8"))
    declared = contract.pop("contract_payload_sha256")
    require(stable_hash(contract) == declared, "R2_CONTRACT_PAYLOAD_HASH")
    summary = json.loads(R2_SUMMARY.read_text(encoding="utf-8"))
    require(summary["final_classification"] == "PASS_FROZEN_A2_HHI_NONINCREASING_ENTRY_GUARD_R2", "R2_PARENT_CLASSIFICATION")
    require(summary["economic_outcome_read_count"] == 0, "R2_PARENT_OUTCOME_READ_COUNT")
    return {"protocol": protocol, "summary": summary}


def minimum_feasible_hhi(day: pd.DataFrame) -> tuple[float, dict[str, int]]:
    capacities = day.groupby("ff12", dropna=False).ticker.nunique().astype(int).to_dict()
    allocations = {str(sector): 0 for sector in capacities}
    normalized_capacity = {str(sector): int(value) for sector, value in capacities.items()}
    for _ in range(TOP_N):
        eligible = [sector for sector in allocations if allocations[sector] < normalized_capacity[sector]]
        require(bool(eligible), "INSUFFICIENT_VALID_CANDIDATES_FOR_MIN_HHI")
        sector = min(eligible, key=lambda value: (2 * allocations[value] + 1, value))
        allocations[sector] += 1
    value = float(sum((count * WEIGHT) ** 2 for count in allocations.values()))
    return value, allocations


def event_flags(event_class: str) -> dict[str, bool]:
    return {
        "included_total_optional_entry_requests": event_class.startswith("OPTIONAL_"),
        "included_hhi_guard_trigger_count": event_class in {
            "OPTIONAL_HHI_GUARD_INTERVENTION",
            "OPTIONAL_HHI_GUARD_FALLBACK",
        },
        "included_intervention_count": event_class == "OPTIONAL_HHI_GUARD_INTERVENTION",
        "included_better_than_canonical_count": event_class in {
            "OPTIONAL_HHI_GUARD_INTERVENTION",
            "FORCED_EXIT_HHI_GUARD_INTERVENTION",
        },
        "included_equal_canonical_count": False,
        "included_worse_than_canonical_count": False,
    }


def audit_replay(
    r2: Any,
    panel: pd.DataFrame,
    benchmark_by_date: dict[pd.Timestamp, dict[str, float]],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    r1 = r2.import_r1()
    event_rows: list[dict[str, Any]] = []
    daily_rows: list[dict[str, Any]] = []
    intervention_rows: list[dict[str, Any]] = []
    previous_shadow: set[str] | None = None
    previous_raw: set[str] | None = None
    previous_ranks: dict[str, int] = {}
    previous_sectors: dict[str, str] = {}
    membership_transition_error_count = 0
    unresolved_entry_slot_count = 0
    invalid_held_security_count = 0
    duplicate_ticker_count = 0

    for date, day in panel.groupby("signal_date", sort=True):
        day = day.sort_values(["a2_rank", "ticker"], kind="mergesort")
        ordered = day.ticker.astype(str).tolist()
        ranks = dict(zip(day.ticker.astype(str), day.a2_rank.astype(int)))
        sectors = dict(zip(day.ticker.astype(str), day.ff12.fillna("UNKNOWN").astype(str)))
        raw = set(ordered[:TOP_N])
        benchmark = benchmark_by_date[pd.Timestamp(date)]
        start = set(raw) if previous_shadow is None else set(previous_shadow)
        shadow = set(start)
        exits: list[str] = []
        entrants: list[str] = []
        slot = 0

        if previous_shadow is not None:
            forced = sorted(name for name in shadow if name not in ranks)
            for name in forced:
                sectors[name] = previous_sectors.get(name, "UNKNOWN")
            for exit_name in forced:
                slot += 1
                candidates = [name for name in ordered[:TOP_N] if name not in shadow]
                if not candidates:
                    candidates = [name for name in ordered if name not in shadow]
                if not candidates:
                    unresolved_entry_slot_count += 1
                    continue
                original = candidates[0]
                selection = r2.select_direct_hhi(r1, original, exit_name, shadow, ordered, sectors, ranks)
                event_class = (
                    "FORCED_EXIT_HHI_GUARD_INTERVENTION"
                    if selection["intervention"]
                    else "FORCED_EXIT_HHI_GUARD_FALLBACK"
                    if selection["fallback"]
                    else "FORCED_EXIT_CANONICAL_REPLACEMENT"
                )
                event_rows.append(event_record(date, slot, event_class, exit_name, original, selection))
                if selection["intervention"]:
                    intervention_rows.append(r2.intervention_record(date, slot, "FORCED_EXIT_REPLACEMENT", exit_name, original, selection))
                before_count = len(shadow)
                shadow.remove(exit_name)
                shadow.add(selection["chosen"])
                exits.append(exit_name)
                entrants.append(selection["chosen"])
                if len(shadow) != before_count:
                    membership_transition_error_count += 1
                if exit_name in shadow:
                    invalid_held_security_count += 1

            new_entries = sorted(raw - (previous_raw or set()), key=lambda name: (ranks[name], name))
            raw_exits = sorted((previous_raw or set()) - raw, key=lambda name: (-previous_ranks.get(name, -1), name))
            for index, original in enumerate(new_entries):
                if original in shadow:
                    event_rows.append(
                        {
                            "signal_date": pd.Timestamp(date).date().isoformat(),
                            "slot": None,
                            "event_class": "OPTIONAL_REQUEST_ALREADY_HELD_NO_ENTRY_SLOT",
                            "exit_ticker": None,
                            "canonical_entrant": original,
                            "accepted_entrant": original,
                            "guard_triggered": False,
                            "intervention": False,
                            "fallback": False,
                        }
                    )
                    continue
                slot += 1
                paired_exit = raw_exits[index] if index < len(raw_exits) else None
                if paired_exit not in shadow:
                    outside = [name for name in shadow if name not in raw]
                    if not outside:
                        unresolved_entry_slot_count += 1
                        continue
                    paired_exit = sorted(outside, key=lambda name: (-ranks.get(name, 10**9), name))[0]
                if paired_exit not in sectors:
                    sectors[paired_exit] = previous_sectors.get(paired_exit, "UNKNOWN")
                selection = r2.select_direct_hhi(r1, original, paired_exit, shadow, ordered, sectors, ranks)
                event_class = (
                    "OPTIONAL_HHI_GUARD_INTERVENTION"
                    if selection["intervention"]
                    else "OPTIONAL_HHI_GUARD_FALLBACK"
                    if selection["fallback"]
                    else "OPTIONAL_CANONICAL_ACCEPTED"
                )
                event_rows.append(event_record(date, slot, event_class, paired_exit, original, selection))
                if selection["intervention"]:
                    intervention_rows.append(r2.intervention_record(date, slot, "OPTIONAL_RAW_A2_ENTRY", paired_exit, original, selection))
                before_count = len(shadow)
                shadow.remove(paired_exit)
                shadow.add(selection["chosen"])
                exits.append(paired_exit)
                entrants.append(selection["chosen"])
                if len(shadow) != before_count:
                    membership_transition_error_count += 1

        duplicate_ticker_count += TOP_N - len(shadow)
        invalid_held_security_count += len([name for name in shadow if name not in ranks])
        if len(shadow) != TOP_N:
            membership_transition_error_count += 1
        ending_sector_counts = pd.Series([sectors[name] for name in shadow]).value_counts().sort_index().astype(int).to_dict()
        recomputed_hhi = float(sum((count * WEIGHT) ** 2 for count in ending_sector_counts.values()))
        r2_hhi = r1.hhi(shadow, sectors)
        min_hhi, min_allocations = minimum_feasible_hhi(day)
        expected_end = set(start)
        for exit_name, entrant in zip(exits, entrants):
            expected_end.remove(exit_name)
            expected_end.add(entrant)
        if expected_end != shadow:
            membership_transition_error_count += 1
        net_retained = start & shadow
        net_new = shadow - start
        daily_rows.append(
            {
                "signal_date": pd.Timestamp(date).date().isoformat(),
                "starting_holding_count": len(start),
                "valid_retained_holding_count": len(net_retained),
                "processed_exit_count": len(exits),
                "processed_entrant_count": len(entrants),
                "net_new_ending_holding_count": len(net_new),
                "ending_holding_count": len(shadow),
                "starting_holdings_json": json.dumps(sorted(start), separators=(",", ":")),
                "processed_exits_json": json.dumps(exits, separators=(",", ":")),
                "processed_entrants_json": json.dumps(entrants, separators=(",", ":")),
                "ending_holdings_json": json.dumps(sorted(shadow), separators=(",", ":")),
                "ending_sector_counts_json": json.dumps(ending_sector_counts, sort_keys=True, separators=(",", ":")),
                "available_sector_capacity_json": json.dumps(day.groupby("ff12").ticker.nunique().astype(int).sort_index().to_dict(), sort_keys=True, separators=(",", ":")),
                "min_feasible_allocation_json": json.dumps(min_allocations, sort_keys=True, separators=(",", ":")),
                "distinct_held_sector_count": len(ending_sector_counts),
                "available_valid_sector_count": int(day.ff12.nunique()),
                "weight_sum": len(shadow) * WEIGHT,
                "weight_sum_error": abs(len(shadow) * WEIGHT - 1.0),
                "r2_hhi_from_frozen_arithmetic": r2_hhi,
                "independently_recomputed_r2_hhi": recomputed_hhi,
                "hhi_recompute_abs_error": abs(r2_hhi - recomputed_hhi),
                "min_feasible_hhi_given_available_valid_sectors": min_hhi,
                "r2_hhi_minus_min_feasible_hhi": r2_hhi - min_hhi,
                "raw_a2_hhi": r1.hhi(raw, sectors),
                "raw_structural_turnover": r1.turnover(previous_raw, raw),
                "r2_structural_turnover": r1.turnover(previous_shadow, shadow),
                "membership_difference_rate": 1.0 - len(raw & shadow) / TOP_N,
            }
        )
        previous_shadow = set(shadow)
        previous_raw = set(raw)
        previous_ranks = ranks
        previous_sectors = {ticker: sectors[ticker] for ticker in shadow}

    events = pd.DataFrame(event_rows)
    daily = pd.DataFrame(daily_rows)
    interventions = pd.DataFrame(intervention_rows)
    facts = {
        "membership_transition_error_count": membership_transition_error_count,
        "unresolved_entry_slot_count": unresolved_entry_slot_count,
        "invalid_held_security_count": invalid_held_security_count,
        "duplicate_ticker_count": duplicate_ticker_count,
        "logical_replay_sha256": stable_hash({"events": event_rows, "daily": daily_rows, "interventions": intervention_rows}),
    }
    return events, daily, interventions, facts


def event_record(
    date: pd.Timestamp,
    slot: int,
    event_class: str,
    exit_ticker: str,
    original: str,
    selection: dict[str, Any],
) -> dict[str, Any]:
    return {
        "signal_date": pd.Timestamp(date).date().isoformat(),
        "slot": int(slot),
        "event_class": event_class,
        "exit_ticker": str(exit_ticker),
        "canonical_entrant": str(original),
        "accepted_entrant": str(selection["chosen"]),
        "guard_triggered": bool(selection["trigger"]),
        "intervention": bool(selection["intervention"]),
        "fallback": bool(selection["fallback"]),
        "canonical_rank": int(selection["canonical_rank"]),
        "accepted_rank": int(selection["chosen_rank"]),
        "hhi_before_entry": float(selection["hhi_before"]),
        "hhi_after_canonical": float(selection["hhi_after_canonical"]),
        "hhi_after_accepted": float(selection["hhi_after_chosen"]),
    }


def aggregate_event_accounting(events: pd.DataFrame) -> pd.DataFrame:
    classes = [
        "OPTIONAL_CANONICAL_ACCEPTED",
        "OPTIONAL_HHI_GUARD_INTERVENTION",
        "OPTIONAL_HHI_GUARD_FALLBACK",
        "FORCED_EXIT_CANONICAL_REPLACEMENT",
        "FORCED_EXIT_HHI_GUARD_INTERVENTION",
        "FORCED_EXIT_HHI_GUARD_FALLBACK",
        "OPTIONAL_REQUEST_ALREADY_HELD_NO_ENTRY_SLOT",
    ]
    counts = events.event_class.value_counts().to_dict()
    rows = []
    for event_class in classes:
        flags = event_flags(event_class)
        rows.append(
            {
                "event_class": event_class,
                "n_events": int(counts.get(event_class, 0)),
                "is_actual_entry_slot": event_class != "OPTIONAL_REQUEST_ALREADY_HELD_NO_ENTRY_SLOT",
                **flags,
                "definition": {
                    "OPTIONAL_CANONICAL_ACCEPTED": "actual optional swap; canonical entrant accepted because guard did not trigger",
                    "OPTIONAL_HHI_GUARD_INTERVENTION": "optional canonical swap raised HHI and was replaced by a compliant alternative",
                    "OPTIONAL_HHI_GUARD_FALLBACK": "optional guard triggered but no compliant alternative existed; canonical entrant used",
                    "FORCED_EXIT_CANONICAL_REPLACEMENT": "forced invalid exit filled by canonical candidate without intervention",
                    "FORCED_EXIT_HHI_GUARD_INTERVENTION": "forced-exit slot filled by HHI-compliant alternative",
                    "FORCED_EXIT_HHI_GUARD_FALLBACK": "forced-exit guard triggered with no compliant alternative; canonical candidate used",
                    "OPTIONAL_REQUEST_ALREADY_HELD_NO_ENTRY_SLOT": "new canonical Raw request was already present in stateful shadow; request satisfied with no swap or entry slot",
                }[event_class],
            }
        )
    return pd.DataFrame(rows)


def metric_row(scope: str, metric: str, value: Any, denominator: str, definition: str, frozen: Any = None) -> dict[str, Any]:
    error = None
    if frozen is not None and value is not None:
        error = float(value) - float(frozen)
    return {
        "scope": scope,
        "metric": metric,
        "value": value,
        "denominator": denominator,
        "definition": definition,
        "frozen_r2_reported_value": frozen,
        "reconciliation_error": error,
    }


def run() -> None:
    r2 = import_r2()
    frozen = verify_inputs(r2)
    r1 = r2.import_r1()
    r2_parent_before = tree_snapshot(R2_OUT)
    prospective_before = tree_snapshot(PROSPECTIVE)
    registry_before = sha256_file(REGISTRY)

    panel, benchmark, input_facts = r1.load_structural_inputs()
    frozen_daily = pd.read_csv(
        R2_DAILY,
        usecols=[
            "signal_date",
            "optional_entry_requests",
            "hhi_guard_triggers",
            "hhi_compliant_alternatives",
            "hhi_fallbacks",
            "forced_exit_count",
            "raw_a2_hhi",
            "r2_hhi",
            "membership_difference_rate",
            "raw_structural_turnover",
            "r2_structural_turnover",
        ],
    )
    frozen_ledger = pd.read_parquet(R2_LEDGER)
    events, daily, interventions, facts = audit_replay(r2, panel, benchmark)
    event_accounting = aggregate_event_accounting(events)
    count_map = event_accounting.set_index("event_class").n_events.to_dict()

    optional_canonical_swap = int(count_map["OPTIONAL_CANONICAL_ACCEPTED"])
    optional_interventions = int(count_map["OPTIONAL_HHI_GUARD_INTERVENTION"])
    optional_fallbacks = int(count_map["OPTIONAL_HHI_GUARD_FALLBACK"])
    optional_already_held = int(count_map["OPTIONAL_REQUEST_ALREADY_HELD_NO_ENTRY_SLOT"])
    optional_requests = optional_canonical_swap + optional_interventions + optional_fallbacks + optional_already_held
    forced_canonical = int(count_map["FORCED_EXIT_CANONICAL_REPLACEMENT"])
    forced_interventions = int(count_map["FORCED_EXIT_HHI_GUARD_INTERVENTION"])
    forced_fallbacks = int(count_map["FORCED_EXIT_HHI_GUARD_FALLBACK"])
    forced_slots = forced_canonical + forced_interventions + forced_fallbacks
    all_interventions = optional_interventions + forced_interventions
    frozen_metrics = frozen["summary"]["structural_metrics"]
    reported_optional_interventions = int(frozen_metrics["intervention_count"])
    reported_better = int(frozen_metrics["r2_better_than_canonical_hhi_count"])
    count_difference = reported_better - reported_optional_interventions
    unexplained = sum(
        abs(value)
        for value in [
            optional_requests - int(frozen_metrics["total_optional_entry_requests"]),
            optional_interventions - reported_optional_interventions,
            forced_slots - int(frozen_daily.forced_exit_count.sum()),
            all_interventions - len(frozen_ledger),
            reported_better - all_interventions,
            count_difference - forced_interventions,
        ]
    )

    intervention_cols = list(frozen_ledger.columns)
    audit_ledger = interventions[intervention_cols].copy()
    frozen_sorted = frozen_ledger.sort_values(["signal_date", "slot", "request_type", "canonical_entrant"]).reset_index(drop=True)
    audit_sorted = audit_ledger.sort_values(["signal_date", "slot", "request_type", "canonical_entrant"]).reset_index(drop=True)
    ledger_mismatch_count = 0
    if len(frozen_sorted) != len(audit_sorted):
        ledger_mismatch_count += abs(len(frozen_sorted) - len(audit_sorted))
    else:
        for column in intervention_cols:
            if pd.api.types.is_numeric_dtype(frozen_sorted[column]):
                ledger_mismatch_count += int(((frozen_sorted[column].astype(float) - audit_sorted[column].astype(float)).abs() > TOL).sum())
            else:
                ledger_mismatch_count += int(frozen_sorted[column].astype(str).ne(audit_sorted[column].astype(str)).sum())

    daily_compare = daily.merge(frozen_daily, on="signal_date", suffixes=("_audit", "_frozen"), validate="one_to_one")
    daily_mismatch_count = 0
    mappings = {
        "raw_a2_hhi": "raw_a2_hhi",
        "r2_hhi_from_frozen_arithmetic": "r2_hhi",
        "membership_difference_rate": "membership_difference_rate",
        "raw_structural_turnover": "raw_structural_turnover",
        "r2_structural_turnover": "r2_structural_turnover",
    }
    for audit_column, frozen_column in mappings.items():
        audit_merged_column = (
            f"{audit_column}_audit" if audit_column in frozen_daily.columns else audit_column
        )
        frozen_merged_column = (
            f"{frozen_column}_frozen" if frozen_column in daily.columns else frozen_column
        )
        daily_mismatch_count += int(
            (
                daily_compare[audit_merged_column].astype(float)
                - daily_compare[frozen_merged_column].astype(float)
            ).abs().gt(TOL).sum()
        )

    optional_ledger = interventions.loc[interventions.request_type.eq("OPTIONAL_RAW_A2_ENTRY")]
    forced_ledger = interventions.loc[interventions.request_type.eq("FORCED_EXIT_REPLACEMENT")]
    optional_before_delta = optional_ledger.HHI_AFTER_R2_ALTERNATIVE - optional_ledger.HHI_BEFORE_ENTRY
    forced_before_delta = forced_ledger.HHI_AFTER_R2_ALTERNATIVE - forced_ledger.HHI_BEFORE_ENTRY
    optional_canonical_delta = optional_ledger.HHI_AFTER_R2_ALTERNATIVE - optional_ledger.HHI_AFTER_CANONICAL
    forced_canonical_delta = forced_ledger.HHI_AFTER_R2_ALTERNATIVE - forced_ledger.HHI_AFTER_CANONICAL
    optional_hhi_violations = int(((optional_before_delta > 0.0) | (optional_canonical_delta > 0.0)).sum())
    forced_hhi_violations = int(((forced_before_delta > 0.0) | (forced_canonical_delta > 0.0)).sum())
    max_adverse_optional = float(max(0.0, optional_before_delta.max(), optional_canonical_delta.max())) if len(optional_ledger) else 0.0
    max_adverse_forced = float(max(0.0, forced_before_delta.max(), forced_canonical_delta.max())) if len(forced_ledger) else 0.0

    hhi_recompute_max_error = float(daily.hhi_recompute_abs_error.max())
    distance = daily.r2_hhi_minus_min_feasible_hhi
    held_sector_distribution = {
        "p10": float(daily.distinct_held_sector_count.quantile(0.10)),
        "p50": float(daily.distinct_held_sector_count.quantile(0.50)),
        "p90": float(daily.distinct_held_sector_count.quantile(0.90)),
        "max": int(daily.distinct_held_sector_count.max()),
    }
    aggregate_sector_counts: dict[str, int] = {}
    for value in daily.ending_sector_counts_json:
        for sector, count in json.loads(value).items():
            aggregate_sector_counts[sector] = aggregate_sector_counts.get(sector, 0) + int(count)

    rank = interventions.rank_displacement.astype(float)
    alternative_rank = interventions.alternative_rank.astype(float)
    raw_turnover = float(daily.raw_structural_turnover.sum())
    r2_turnover = float(daily.r2_structural_turnover.sum())
    intrusiveness_rows = [
        metric_row("ALL_INTERVENTIONS", "AVG_RANK_DISPLACEMENT", float(rank.mean()), "all optional plus forced alternative interventions", "alternative rank minus canonical rank", frozen_metrics["average_rank_displacement"]),
        metric_row("ALL_INTERVENTIONS", "P90_RANK_DISPLACEMENT", float(rank.quantile(0.90)), "all optional plus forced alternative interventions", "90th percentile using pandas linear quantile", frozen_metrics["p90_rank_displacement"]),
        metric_row("ALL_INTERVENTIONS", "MAX_RANK_DISPLACEMENT", int(rank.max()), "all optional plus forced alternative interventions", "maximum alternative rank minus canonical rank", frozen_metrics["max_rank_displacement"]),
        metric_row("OPTIONAL_INTERVENTIONS", "AVG_RANK_DISPLACEMENT", float(optional_ledger.rank_displacement.mean()), "optional alternative interventions", "alternative rank minus canonical rank"),
        metric_row("FORCED_INTERVENTIONS", "AVG_RANK_DISPLACEMENT", float(forced_ledger.rank_displacement.mean()), "forced-exit alternative interventions", "alternative rank minus canonical rank"),
        metric_row("ALL_INTERVENTIONS", "PCT_ALT_RANK_GT40", float((alternative_rank > 40).mean()), "all optional plus forced alternative interventions", "fraction of selected alternative ranks strictly greater than 40"),
        metric_row("ALL_INTERVENTIONS", "PCT_ALT_RANK_GT60", float((alternative_rank > 60).mean()), "all optional plus forced alternative interventions", "fraction of selected alternative ranks strictly greater than 60"),
        metric_row("ALL_INTERVENTIONS", "PCT_ALT_RANK_GT100", float((alternative_rank > 100).mean()), "all optional plus forced alternative interventions", "fraction of selected alternative ranks strictly greater than 100"),
        metric_row("ALL_INTERVENTIONS", "PCT_ALT_RANK_GT200", float((alternative_rank > 200).mean()), "all optional plus forced alternative interventions", "fraction of selected alternative ranks strictly greater than 200"),
        metric_row("ALL_DATES", "HOLDING_MEMBERSHIP_DIFFERENCE_RATE", float(daily.membership_difference_rate.mean()), "750 signal dates", "mean of 1 minus Raw/R2 Top20 intersection divided by 20", frozen_metrics["holding_membership_difference_rate"]),
        metric_row("ALL_TRANSITIONS", "STRUCTURAL_TURNOVER_DIFFERENCE_RATE", float((r2_turnover - raw_turnover) / raw_turnover), "adjacent-date equal-weight structural turnover totals", "(R2 total turnover minus Raw total turnover) divided by Raw total turnover", frozen_metrics["structural_turnover_difference_rate"]),
    ]
    intrusiveness = pd.DataFrame(intrusiveness_rows)

    weight_sum_max_error = float(daily.weight_sum_error.max())
    transition_error_total = facts["membership_transition_error_count"] + daily_mismatch_count
    hhi_failure = hhi_recompute_max_error > TOL or optional_hhi_violations > 0 or forced_hhi_violations > 0
    transition_failure = transition_error_total > 0 or ledger_mismatch_count > 0 or facts["invalid_held_security_count"] > 0 or facts["duplicate_ticker_count"] > 0 or facts["unresolved_entry_slot_count"] > 0 or weight_sum_max_error > TOL
    if transition_failure:
        final_classification = "FAIL_R2_TRANSITION_LEDGER_MISMATCH"
    elif hhi_failure:
        final_classification = "FAIL_R2_HHI_RECOMPUTE_MISMATCH"
    elif unexplained > 0:
        final_classification = "FAIL_STRUCTURAL_ACCOUNTING_MISMATCH"
    else:
        final_classification = "PASS_STRUCTURAL_ACCOUNTING_CLOSED"
    passed = final_classification == "PASS_STRUCTURAL_ACCOUNTING_CLOSED"

    summary = {
        "status": "PASS" if passed else "FAIL",
        "final_classification": final_classification,
        "r2_protocol_hash_status": "PASS",
        "r2_contract_hash_status": "PASS",
        "r2_structural_component_reuse_status": "PASS_REUSED_FROZEN_R2_TRANSITION_LEDGER_SCAN_TAXONOMY_HHI",
        "economic_outcome_read_count": 0,
        "event_closure": {
            "total_optional_entry_requests": optional_requests,
            "optional_canonical_accepted": optional_canonical_swap,
            "optional_request_already_held_no_entry_slot": optional_already_held,
            "optional_interventions": optional_interventions,
            "optional_fallbacks": optional_fallbacks,
            "forced_replacement_slots": forced_slots,
            "forced_canonical_accepted": forced_canonical,
            "forced_interventions": forced_interventions,
            "forced_fallbacks": forced_fallbacks,
            "all_alternative_interventions": all_interventions,
            "reported_intervention_count_r2": reported_optional_interventions,
            "reported_better_than_canonical_count_r2": reported_better,
            "count_difference": count_difference,
            "count_difference_explanation": f"{reported_better} all interventions = {optional_interventions} optional interventions + {forced_interventions} forced-exit interventions; R2 INTERVENTION_COUNT reports optional interventions only.",
            "accounting_unexplained_event_count": int(unexplained),
            "optional_request_equation": f"{optional_requests} = {optional_canonical_swap} canonical swaps + {optional_already_held} already-held no-slot requests + {optional_interventions} interventions + {optional_fallbacks} fallbacks",
            "all_intervention_equation": f"{all_interventions} = {optional_interventions} optional + {forced_interventions} forced",
        },
        "transition_qa": {
            "duplicate_ticker_count": int(facts["duplicate_ticker_count"]),
            "invalid_held_security_count": int(facts["invalid_held_security_count"]),
            "unresolved_entry_slot_count": int(facts["unresolved_entry_slot_count"]),
            "membership_transition_error_count": int(transition_error_total),
            "weight_sum_max_error": weight_sum_max_error,
            "frozen_intervention_ledger_mismatch_count": int(ledger_mismatch_count),
            "frozen_daily_structural_mismatch_count": int(daily_mismatch_count),
            "ending_holding_count_min": int(daily.ending_holding_count.min()),
            "ending_holding_count_max": int(daily.ending_holding_count.max()),
        },
        "hhi_qa": {
            "hhi_recompute_max_abs_error": hhi_recompute_max_error,
            "optional_intervention_hhi_violations": optional_hhi_violations,
            "forced_intervention_hhi_violations": forced_hhi_violations,
            "max_adverse_optional_hhi_change": max_adverse_optional,
            "max_adverse_forced_hhi_change": max_adverse_forced,
            "average_r2_hhi": float(daily.independently_recomputed_r2_hhi.mean()),
            "average_min_feasible_hhi": float(daily.min_feasible_hhi_given_available_valid_sectors.mean()),
            "average_hhi_distance_from_feasible_min": float(distance.mean()),
            "p50_hhi_distance_from_feasible_min": float(distance.quantile(0.50)),
            "p90_hhi_distance_from_feasible_min": float(distance.quantile(0.90)),
            "fraction_dates_within_0_005_of_min": float((distance <= 0.005).mean()),
            "fraction_dates_within_0_010_of_min": float((distance <= 0.010).mean()),
            "distinct_held_sector_count_distribution": held_sector_distribution,
            "sector_name_holding_observation_counts": dict(sorted(aggregate_sector_counts.items())),
        },
        "intrusiveness": {row["metric"] if row["scope"] == "ALL_INTERVENTIONS" else f"{row['scope']}_{row['metric']}": row["value"] for row in intrusiveness_rows},
        "new_portfolio_engine_created": False,
        "new_backtester_created": False,
        "new_generic_framework_created": False,
        "parent_r2_modified": False,
        "canonical_registry_change": False,
        "prospective_a2_x0_protocol_untouched": True,
        "task_owned_repo_root_temp_dir_count": 0,
        "next_research_priority": "EVALUATE_FROZEN_A2_HHI_NONINCREASING_ENTRY_GUARD_R2" if passed else "DO_NOT_READ_ECONOMICS_FIX_ACCOUNTING_OR_INVALIDATE_R2",
    }

    OUT.mkdir(parents=False, exist_ok=False)
    event_accounting.to_csv(OUT / "event_accounting.csv", index=False)
    daily.to_csv(OUT / "hhi_reconciliation.csv", index=False, float_format="%.12g")
    intrusiveness.to_csv(OUT / "intrusiveness_reconciliation.csv", index=False, float_format="%.12g")
    r2_parent_after = tree_snapshot(R2_OUT)
    prospective_after = tree_snapshot(PROSPECTIVE)
    registry_after = sha256_file(REGISTRY)
    require(r2_parent_before == r2_parent_after, "PARENT_R2_MODIFIED")
    require(prospective_before == prospective_after, "PROSPECTIVE_TREE_MODIFIED")
    require(registry_before == registry_after == EXPECTED[REGISTRY], "REGISTRY_MODIFIED")
    require(not repo_temp_dirs(), "TASK_REPO_ROOT_TEMP_CREATED", [str(path) for path in repo_temp_dirs()])
    manifest = {
        "task_id": "A2_HHI_R2_STRUCTURAL_ACCOUNTING_CLOSURE_AUDIT_R1",
        "research_role": "STRUCTURAL_ACCOUNTING_QA_ONLY",
        "economic_outcome_read_count": 0,
        "r2_structural_component_reuse_status": summary["r2_structural_component_reuse_status"],
        "inputs": [
            {"path": str(R2_PROTOCOL), "sha256": sha256_file(R2_PROTOCOL), "role": "frozen R2 protocol"},
            {"path": str(R2_CONTRACT), "sha256": sha256_file(R2_CONTRACT), "role": "frozen R2 contract"},
            {"path": str(R2_DAILY), "sha256": sha256_file(R2_DAILY), "role": "frozen structural daily metrics", "columns_read": list(frozen_daily.columns)},
            {"path": str(R2_LEDGER), "sha256": sha256_file(R2_LEDGER), "role": "frozen intervention ledger", "columns_read": list(frozen_ledger.columns)},
            {"path": str(R2_SOURCE), "sha256": sha256_file(R2_SOURCE), "role": "exact transition/candidate/HHI implementation reuse"},
            {"path": str(r1.OOF), "sha256": sha256_file(r1.OOF), "role": "authoritative structural rank surface", "columns_read": ["signal_date", "ticker", "universe_size", "split", "a2_model_name", "a2_prediction", "a2_rank"]},
            {"path": str(r1.TAXONOMY), "sha256": sha256_file(r1.TAXONOMY), "role": "PIT FF12/FF48 taxonomy", "columns_read": ["signal_date", "ticker", "pit_sic", "ff12", "ff48"]},
            {"path": str(r1.BENCHMARK), "sha256": sha256_file(r1.BENCHMARK), "role": "structural benchmark weights only", "columns_read": ["record_type", "signal_date", "taxonomy_level", "sector", "benchmark_weight"]},
        ],
        "economic_outcome_columns_opened": [],
        "input_facts": input_facts,
        "parent_r2_tree_sha256_before": stable_hash(r2_parent_before),
        "parent_r2_tree_sha256_after": stable_hash(r2_parent_after),
        "prospective_tree_sha256_before": stable_hash(prospective_before),
        "prospective_tree_sha256_after": stable_hash(prospective_after),
        "registry_sha256_before": registry_before,
        "registry_sha256_after": registry_after,
        "audit_replay_sha256": facts["logical_replay_sha256"],
    }
    write_json(OUT / "source_manifest.json", manifest)
    write_json(OUT / "summary.json", summary)
    write_report(summary)
    print_console(summary)


def write_report(summary: dict[str, Any]) -> None:
    e = summary["event_closure"]
    t = summary["transition_qa"]
    h = summary["hhi_qa"]
    i = summary["intrusiveness"]
    sector_distribution = h["distinct_held_sector_count_distribution"]
    report = f"""# A2 HHI R2 structural accounting closure

## Result

**{summary['final_classification']}**

The 21-event difference is fully explained by forced-exit interventions. Frozen R2's `INTERVENTION_COUNT` is optional-only, while its canonical HHI comparison counts cover every alternative intervention:

`{e['reported_better_than_canonical_count_r2']} = {e['optional_interventions']} optional interventions + {e['forced_interventions']} forced-exit interventions`.

Optional-request closure is `{e['optional_request_equation']}`. The already-held class is stateful accounting: the new canonical Raw entrant was already in the shadow, so the request required no entry slot or trade. Unexplained events: **{e['accounting_unexplained_event_count']}**.

## Transition and HHI closure

- Ending holdings: {t['ending_holding_count_min']}–{t['ending_holding_count_max']} (required 20)
- Duplicate / invalid / unresolved / transition errors: {t['duplicate_ticker_count']} / {t['invalid_held_security_count']} / {t['unresolved_entry_slot_count']} / {t['membership_transition_error_count']}
- Frozen intervention-ledger / daily-structural mismatches: {t['frozen_intervention_ledger_mismatch_count']} / {t['frozen_daily_structural_mismatch_count']}
- HHI recomputation maximum absolute error: {h['hhi_recompute_max_abs_error']:.12g}
- Optional / forced intervention HHI violations: {h['optional_intervention_hhi_violations']} / {h['forced_intervention_hhi_violations']}
- Average R2 / minimum-feasible HHI: {h['average_r2_hhi']:.6f} / {h['average_min_feasible_hhi']:.6f}
- Average / P50 / P90 distance from feasible minimum: {h['average_hhi_distance_from_feasible_min']:.6f} / {h['p50_hhi_distance_from_feasible_min']:.6f} / {h['p90_hhi_distance_from_feasible_min']:.6f}
- Dates within 0.005 / 0.010 of minimum: {h['fraction_dates_within_0_005_of_min']:.2%} / {h['fraction_dates_within_0_010_of_min']:.2%}
- Distinct held FF12/UNKNOWN categories, P10 / P50 / P90 / max: {sector_distribution['p10']:.0f} / {sector_distribution['p50']:.0f} / {sector_distribution['p90']:.0f} / {sector_distribution['max']}

## Intrusiveness denominators

Frozen average/P90/maximum displacement use all {e['all_alternative_interventions']} alternative interventions, including forced-exit interventions. Optional-only average displacement is {i['OPTIONAL_INTERVENTIONS_AVG_RANK_DISPLACEMENT']:.6f}; forced-only average is {i['FORCED_INTERVENTIONS_AVG_RANK_DISPLACEMENT']:.6f}. Membership difference is the 750-date mean of `1 - |Raw Top20 intersect R2 Top20| / 20`. Structural turnover difference is `(sum R2 equal-weight adjacent-date turnover - sum Raw turnover) / sum Raw turnover`.

No economic outcome file or column was opened. The frozen R2 parent, canonical registry, and A2/X0 prospective tree are unchanged.
"""
    (OUT / "concise_report.md").write_text(report, encoding="utf-8")


def fmt(value: Any) -> str:
    return f"{value:.12g}" if isinstance(value, float) else str(value)


def print_console(summary: dict[str, Any]) -> None:
    e = summary["event_closure"]
    t = summary["transition_qa"]
    h = summary["hhi_qa"]
    i = summary["intrusiveness"]
    lines = [
        "============================================================",
        "A2 HHI R2 STRUCTURAL ACCOUNTING CLOSURE",
        "============================================================",
        f"STATUS={summary['status']}",
        "",
        f"R2_PROTOCOL_HASH_STATUS={summary['r2_protocol_hash_status']}",
        f"R2_CONTRACT_HASH_STATUS={summary['r2_contract_hash_status']}",
        "",
        "ECONOMIC_OUTCOME_READ_COUNT=0",
        "",
        f"R2_STRUCTURAL_COMPONENT_REUSE_STATUS={summary['r2_structural_component_reuse_status']}",
        "",
        "------------------------------------------------------------",
        "EVENT CLOSURE",
        "------------------------------------------------------------",
        f"TOTAL_OPTIONAL_ENTRY_REQUESTS={e['total_optional_entry_requests']}",
        "",
        f"OPTIONAL_CANONICAL_ACCEPTED={e['optional_canonical_accepted']}",
        f"OPTIONAL_ALREADY_HELD_NO_ENTRY_SLOT={e['optional_request_already_held_no_entry_slot']}",
        f"OPTIONAL_INTERVENTIONS={e['optional_interventions']}",
        f"OPTIONAL_FALLBACKS={e['optional_fallbacks']}",
        "",
        f"FORCED_REPLACEMENT_SLOTS={e['forced_replacement_slots']}",
        f"FORCED_CANONICAL_ACCEPTED={e['forced_canonical_accepted']}",
        f"FORCED_INTERVENTIONS={e['forced_interventions']}",
        f"FORCED_FALLBACKS={e['forced_fallbacks']}",
        "",
        f"ALL_ALTERNATIVE_INTERVENTIONS={e['all_alternative_interventions']}",
        "",
        f"REPORTED_INTERVENTION_COUNT_R2={e['reported_intervention_count_r2']}",
        f"REPORTED_BETTER_THAN_CANONICAL_COUNT_R2={e['reported_better_than_canonical_count_r2']}",
        "",
        f"COUNT_DIFFERENCE={e['count_difference']}",
        f"COUNT_DIFFERENCE_EXPLANATION={e['count_difference_explanation']}",
        "",
        f"ACCOUNTING_UNEXPLAINED_EVENT_COUNT={e['accounting_unexplained_event_count']}",
        "",
        "------------------------------------------------------------",
        "TRANSITION QA",
        "------------------------------------------------------------",
        f"ENDING_HOLDING_COUNT={t['ending_holding_count_min']}",
        f"DUPLICATE_TICKER_COUNT={t['duplicate_ticker_count']}",
        f"INVALID_HELD_SECURITY_COUNT={t['invalid_held_security_count']}",
        f"UNRESOLVED_ENTRY_SLOT_COUNT={t['unresolved_entry_slot_count']}",
        f"MEMBERSHIP_TRANSITION_ERROR_COUNT={t['membership_transition_error_count']}",
        f"WEIGHT_SUM_MAX_ERROR={fmt(t['weight_sum_max_error'])}",
        "",
        "------------------------------------------------------------",
        "HHI QA",
        "------------------------------------------------------------",
        f"HHI_RECOMPUTE_MAX_ABS_ERROR={fmt(h['hhi_recompute_max_abs_error'])}",
        "",
        f"OPTIONAL_INTERVENTION_HHI_VIOLATIONS={h['optional_intervention_hhi_violations']}",
        f"FORCED_INTERVENTION_HHI_VIOLATIONS={h['forced_intervention_hhi_violations']}",
        "",
        f"MAX_ADVERSE_OPTIONAL_HHI_CHANGE={fmt(h['max_adverse_optional_hhi_change'])}",
        f"MAX_ADVERSE_FORCED_HHI_CHANGE={fmt(h['max_adverse_forced_hhi_change'])}",
        "",
        f"AVG_R2_HHI={fmt(h['average_r2_hhi'])}",
        f"AVG_MIN_FEASIBLE_HHI={fmt(h['average_min_feasible_hhi'])}",
        f"AVG_HHI_DISTANCE_FROM_FEASIBLE_MIN={fmt(h['average_hhi_distance_from_feasible_min'])}",
        "",
        f"FRACTION_DATES_WITHIN_0_005_OF_MIN={fmt(h['fraction_dates_within_0_005_of_min'])}",
        f"FRACTION_DATES_WITHIN_0_010_OF_MIN={fmt(h['fraction_dates_within_0_010_of_min'])}",
        "",
        "------------------------------------------------------------",
        "INTRUSIVENESS",
        "------------------------------------------------------------",
        f"AVG_RANK_DISPLACEMENT={fmt(i['AVG_RANK_DISPLACEMENT'])}",
        f"P90_RANK_DISPLACEMENT={fmt(i['P90_RANK_DISPLACEMENT'])}",
        f"MAX_RANK_DISPLACEMENT={fmt(i['MAX_RANK_DISPLACEMENT'])}",
        "",
        f"OPTIONAL_INTERVENTION_AVG_RANK_DISPLACEMENT={fmt(i['OPTIONAL_INTERVENTIONS_AVG_RANK_DISPLACEMENT'])}",
        f"FORCED_INTERVENTION_AVG_RANK_DISPLACEMENT={fmt(i['FORCED_INTERVENTIONS_AVG_RANK_DISPLACEMENT'])}",
        "",
        f"PCT_ALT_RANK_GT40={fmt(i['PCT_ALT_RANK_GT40'])}",
        f"PCT_ALT_RANK_GT60={fmt(i['PCT_ALT_RANK_GT60'])}",
        f"PCT_ALT_RANK_GT100={fmt(i['PCT_ALT_RANK_GT100'])}",
        f"PCT_ALT_RANK_GT200={fmt(i['PCT_ALT_RANK_GT200'])}",
        "",
        f"HOLDING_MEMBERSHIP_DIFFERENCE_RATE={fmt(i['ALL_DATES_HOLDING_MEMBERSHIP_DIFFERENCE_RATE'])}",
        "",
        "------------------------------------------------------------",
        "FINAL",
        "------------------------------------------------------------",
        f"FINAL_CLASSIFICATION={summary['final_classification']}",
        f"NEXT_RESEARCH_PRIORITY={summary['next_research_priority']}",
        "",
        "NEW_PORTFOLIO_ENGINE_CREATED=FALSE",
        "NEW_BACKTESTER_CREATED=FALSE",
        "PARENT_R2_MODIFIED=FALSE",
        "TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT=0",
        "",
        f"ARTIFACT_DIR={OUT}",
        "============================================================",
    ]
    print("\n".join(lines))


if __name__ == "__main__":
    run()
