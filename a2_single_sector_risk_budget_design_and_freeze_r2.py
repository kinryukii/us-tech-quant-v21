"""Freeze and structurally validate Raw A2's direct-HHI entry guard R2."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pandas as pd


REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / "A2_SINGLE_SECTOR_RISK_BUDGET_DESIGN_AND_FREEZE_R2"
R1_OUT = RESULTS / "A2_SINGLE_SECTOR_RISK_BUDGET_DESIGN_AND_FREEZE_R1"
R1_SOURCE = REPO / "a2_single_sector_risk_budget_design_and_freeze_r1.py"
PARENT = RESULTS / "A2_BETA_SECTOR_RISK_CONTRIBUTION_AUDIT_R1"
PROSPECTIVE = RESULTS / "A2_X0_LITERATURE_GROUNDED_PROSPECTIVE_DISAGREEMENT_R1"
REGISTRY = REPO / "config" / "research_governance" / "alpha_registry.json"
POST_R1_SLEEVE = RESULTS / "A2_SECTOR_NEUTRAL_RELATIVE_VALUE_SLEEVE_R1" / "rv_contract.json"

R1_PRIOR_ART = R1_OUT / "anti_duplication_audit.json"
R1_CONTRACT = R1_OUT / "frozen_contract.json"
R1_SUMMARY = R1_OUT / "summary.json"
PARENT_PROTOCOL = PARENT / "risk_contribution_audit_protocol.json"
PROTOCOL = OUT / "r2_design_protocol.json"
FROZEN_CONTRACT = OUT / "frozen_contract.json"

EXPECTED = {
    R1_PRIOR_ART: "1212837c20c88ab617eef347816a398b2a56db2030a794d983057cdc8c6855dd",
    R1_CONTRACT: "cb1dc16985f24f6401624491ea6c283b5c90b37dad8188574dbbcdbdf56fa4b1",
    R1_SUMMARY: "7cdd359ef308fb267a76e0f92eb185b6c29092f943efd931ed764ef363dffce5",
    R1_SOURCE: "13c1591f9806e97439a8ca987b045d175f3623803e810e4dbf043e45d1fbde65",
    PARENT_PROTOCOL: "8384f59418142bfbb90d681231fc5bac78c48ad48f18f4ed29c65eca68363504",
    POST_R1_SLEEVE: "146af857798c21441b24a1106d32112878ffba43be289ac69098b9a4c070e9c8",
    REGISTRY: "b7beb4adb7fbe67048bedcb21a476a23bbed9295009805a0d432239576e404e3",
}

FROZEN_NAME = "A2_HHI_NONINCREASING_ENTRY_GUARD_SHADOW_R2"
RULE_FAMILY = "DIRECT_HHI_NONINCREASING_ENTRY_GUARD_R2"
TOP_N = 20
WEIGHT = 1.0 / TOP_N
NUMERICAL_VALIDATION_TOLERANCE = 1e-12


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


def import_r1() -> Any:
    spec = importlib.util.spec_from_file_location("a2_sector_r1_reuse", R1_SOURCE)
    require(spec is not None and spec.loader is not None, "R1_IMPORT_SPEC")
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


def verify_frozen_inputs(r1: Any) -> None:
    require(not repo_temp_dirs(), "REPO_ROOT_TEMP_PRESENT", [str(path) for path in repo_temp_dirs()])
    for path, expected in EXPECTED.items():
        require(path.is_file(), "FROZEN_INPUT_MISSING", path)
        require(sha256_file(path) == expected, "FROZEN_INPUT_HASH", path)
    r1.verify_inputs()
    summary = json.loads(R1_SUMMARY.read_text(encoding="utf-8"))
    require(summary["final_classification"] == "FAIL_STRUCTURAL_DEGENERACY", "R1_FAILURE_IDENTITY")
    require(summary["economic_outcome_read_count"] == 0, "R1_OUTCOME_READ_COUNT")


def protocol_payload(r1: Any) -> dict[str, Any]:
    prospective_hash, prospective_files = r1.tree_hash(PROSPECTIVE)
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "task_id": "A2_SINGLE_SECTOR_RISK_BUDGET_DESIGN_AND_FREEZE_R2",
        "research_role": ["DESIGN_AND_FREEZE_ONLY", "STRUCTURAL_VALIDATION_ONLY"],
        "frozen_name_if_pass": FROZEN_NAME,
        "rule_family": RULE_FAMILY,
        "parent_a2": {
            "alias": "A2_HGB",
            "model_sha256": "4f7eff07021bef084b0329dac8dabc31e9391c7c4945eb2955dc6c1339dcea0b",
            "portfolio": "TOP20_EQUAL_WEIGHT_LONG_ONLY",
            "ranking": "A2_SCORE_DESC_THEN_TICKER_ASC",
            "raw_a2_unchanged": True,
        },
        "parent_mechanism_audit": {
            "path": str(PARENT_PROTOCOL),
            "sha256": EXPECTED[PARENT_PROTOCOL],
            "beta_classification": "NO_SUPPORT_FOR_SIMPLE_BETA_BUDGET",
            "sector_classification": "PARTIAL_SUPPORT_FOR_SECTOR_RISK_BUDGET",
        },
        "r1_failed_design": {
            "prior_art_path": str(R1_PRIOR_ART),
            "prior_art_sha256": EXPECTED[R1_PRIOR_ART],
            "contract_path": str(R1_CONTRACT),
            "contract_sha256": EXPECTED[R1_CONTRACT],
            "classification": "FAIL_STRUCTURAL_DEGENERACY",
            "rule_family": "NO_NEW_ACTIVE_SECTOR_OVERWEIGHT_INCREASE_R1",
            "failure_reason": "R1 used active sector overweight as its decision predicate while structural acceptance required direct sector HHI; at least one selected alternative had adverse HHI change +0.025.",
            "outcome_read_count": 0,
            "artifacts_immutable": True,
        },
        "targeted_delta_audit": {
            "r1_prior_art_reused": True,
            "status": "PASS_NO_EXACT_R2_RULE",
            "exact_r2_rule_already_exists": False,
            "post_r1_lineage_checked": {
                "path": str(POST_R1_SLEEVE),
                "sha256": EXPECTED[POST_R1_SLEEVE],
                "classification": "DIFFERENT_CONTINUOUS_SECTOR_NEUTRAL_LONG_SHORT_PORTFOLIO_GEOMETRY",
            },
            "reuse": {
                "r1_transition_order": True,
                "r1_candidate_scan_logic": True,
                "r1_taxonomy": True,
                "r1_benchmark_logic": True,
                "r1_cost_logic": True,
            },
            "new_portfolio_engine_created": False,
            "new_risk_optimizer_created": False,
            "new_generic_risk_framework_created": False,
        },
        "hhi_definition": {
            "taxonomy": "authoritative PIT FF12; UNKNOWN explicit own category",
            "weights": "20 holdings at exactly 1/20 each",
            "formula": "sum_s(W_s^2)",
            "hhi_before_entry": "HHI of the full 20-name pre-swap shadow portfolio immediately before applying the paired exit/entry swap",
            "hhi_after_candidate": "HHI after removing the deterministic paired exit and adding the candidate at 1/20 weight",
            "reconciliation": "sector counts times 1/20 must reproduce every recorded HHI",
        },
        "entry_rule": {
            "canonical_candidate": "same canonical Raw A2 entrant and slot pairing produced by the R1 transition order",
            "guard_trigger": "HHI_AFTER_CANONICAL_ENTRY > HHI_BEFORE_ENTRY using ordinary floating-point comparison",
            "no_trigger_action": "accept canonical Raw A2 entrant without intervention",
            "candidate_scan": "authoritative same-date A2 rank ascending, ticker ascending; skip held/invalid names; do not truncate or expand the natural surface",
            "compliant_alternative": "first candidate for which HHI_AFTER_CANDIDATE <= HHI_BEFORE_ENTRY using exact ordinary floating-point comparison and no decision epsilon",
            "fallback": "if no compliant candidate exists, accept canonical Raw A2 entrant; never cash, shrink, or retain an invalid exit",
            "decision_variable": "SECTOR_HHI_ONLY",
            "numeric_sector_cap": None,
            "threshold": None,
            "optimization_parameter": None,
        },
        "state_transition": {
            "initialization": "copy canonical Raw A2 Top20 exactly on the first structurally processable date",
            "optional_entry_order": "reuse R1: current Raw entrants sorted by current rank then ticker",
            "exit_pairing": "reuse R1: prior Raw exits sorted by prior rank descending then ticker, paired positionally",
            "missing_paired_exit": "reuse R1: worst current-rank held name outside current Raw Top20, ticker ascending tie-break",
            "multiple_entries": "process sequentially using the shadow state produced by all earlier same-date slots",
            "forced_exits": "remove every invalid/absent held security first; apply the same HHI scan to its replacement and fall back to canonical candidate if necessary",
            "grandfathering": "no valid existing holding is sold solely for sector concentration",
            "execution_timing": "unchanged Raw A2 timing",
            "cost_convention": "unchanged 10 BPS one-way turnover; no cost/economic calculation in this task",
        },
        "structural_acceptance_gates": {
            "intervention_hhi_violation_count": 0,
            "max_adverse_intervention_hhi_change_lte": NUMERICAL_VALIDATION_TOLERANCE,
            "deterministic_replay": True,
            "no_transition_change_when_guard_not_triggered": True,
            "all_candidates_on_authoritative_surface": True,
            "forced_invalid_holdings_retained": 0,
            "identity_temporal_error_count": 0,
            "hhi_reconciliation_error_count": 0,
            "economic_outcome_read_count": 0,
            "fallback_rate_rejection_gate": None,
            "intervention_rate_rejection_gate": None,
            "rank_displacement_rejection_gate": None,
            "membership_difference_rejection_gate": None,
            "warning_only": "STRUCTURAL_INTRUSIVENESS_WARNING is true if maximum rank displacement exceeds one Top20 portfolio width; it is never a rejection gate",
        },
        "prohibitions": {
            "economic_outcome_read_count": 0,
            "parameter_search_count": 0,
            "beta_constraint_active": False,
            "rx_margin_active": False,
            "tail_control_active": False,
            "optimizer_active": False,
            "active_overweight_decision_input": False,
            "model_refit": False,
            "registry_change": False,
        },
        "future_evaluation": {
            "run_now": False,
            "comparison": ["RAW_A2", FROZEN_NAME],
            "same_authoritative_historical_exposed_windows": True,
            "evidence_label": "RETROSPECTIVE_EXPOSED_SHADOW_DIAGNOSTIC",
            "metrics": ["net return", "Sharpe", "volatility", "MaxDD", "turnover", "cost", "sector HHI", "P90 HHI", "max sector weight", "active overweight", "SPY beta", "QQQ beta", "SOXX beta", "within-sector selection"],
            "success_principle": "materially lower sector concentration while largely preserving the Raw A2 return engine; report tradeoffs without a scalar utility",
            "retuning_after_results_forbidden": True,
            "redesign_requires_r3": True,
        },
        "protected_state_at_freeze": {
            "prospective_tree_sha256": prospective_hash,
            "prospective_tree_file_count": prospective_files,
            "registry_sha256": sha256_file(REGISTRY),
        },
    }
    payload["protocol_payload_sha256"] = stable_hash(payload)
    return payload


def freeze_protocol() -> None:
    require(not OUT.exists(), "R2_OUTPUT_ALREADY_EXISTS", OUT)
    r1 = import_r1()
    verify_frozen_inputs(r1)
    OUT.mkdir(parents=False, exist_ok=False)
    delta = {
        "status": "PASS_NO_EXACT_R2_RULE",
        "r1_prior_art_reused": True,
        "r1_prior_art_path": str(R1_PRIOR_ART),
        "r1_prior_art_sha256": EXPECTED[R1_PRIOR_ART],
        "r1_contract_path": str(R1_CONTRACT),
        "r1_contract_sha256": EXPECTED[R1_CONTRACT],
        "r1_relevant_sector_rule_count": 13,
        "exact_r2_rule_already_exists": False,
        "post_r1_lineages": [{"path": str(POST_R1_SLEEVE), "sha256": EXPECTED[POST_R1_SLEEVE], "classification": "NOT_R2_DIFFERENT_CONTINUOUS_SECTOR_NEUTRAL_LONG_SHORT_GEOMETRY"}],
        "search_terms": ["HHI", "HHI_ENTRY", "HHI_GUARD", "CONCENTRATION_GUARD", "NONINCREASING_HHI", "MARGINAL_HHI", "sector_hhi"],
        "relevant_source_fingerprint_materially_changed": False,
        "completed_before_protocol_freeze": True,
    }
    write_json(OUT / "targeted_anti_duplication_delta.json", delta)
    write_json(PROTOCOL, protocol_payload(r1))
    print(f"R2_DESIGN_PROTOCOL_SHA256={sha256_file(PROTOCOL)}")


def verify_protocol() -> tuple[dict[str, Any], str]:
    require(PROTOCOL.is_file(), "R2_PROTOCOL_NOT_FROZEN")
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    declared = protocol.pop("protocol_payload_sha256")
    require(stable_hash(protocol) == declared, "R2_PROTOCOL_PAYLOAD_HASH")
    protocol["protocol_payload_sha256"] = declared
    require(protocol["rule_family"] == RULE_FAMILY, "R2_RULE_MUTATION")
    require(protocol["entry_rule"]["decision_variable"] == "SECTOR_HHI_ONLY", "R2_DECISION_MUTATION")
    require(protocol["prohibitions"]["economic_outcome_read_count"] == 0, "R2_OUTCOME_MUTATION")
    return protocol, sha256_file(PROTOCOL)


def hhi_from_counts(names: set[str], sectors: dict[str, str]) -> float:
    counts: dict[str, int] = {}
    for ticker in names:
        sector = sectors[ticker]
        counts[sector] = counts.get(sector, 0) + 1
    return float(sum((count * WEIGHT) ** 2 for count in counts.values()))


def select_direct_hhi(
    r1: Any,
    original: str,
    exit_name: str,
    holdings: set[str],
    ordered: list[str],
    sectors: dict[str, str],
    ranks: dict[str, int],
) -> dict[str, Any]:
    before = r1.hhi(holdings, sectors)
    canonical_holdings = (holdings - {exit_name}) | {original}
    after_canonical = r1.hhi(canonical_holdings, sectors)
    trigger = after_canonical > before
    result = {
        "chosen": original,
        "trigger": trigger,
        "intervention": False,
        "fallback": False,
        "hhi_before": before,
        "hhi_after_canonical": after_canonical,
        "hhi_after_chosen": after_canonical,
        "canonical_rank": int(ranks[original]),
        "chosen_rank": int(ranks[original]),
    }
    if not trigger:
        return result
    for candidate in ordered:
        if candidate in holdings or candidate == exit_name:
            continue
        after_candidate = r1.hhi((holdings - {exit_name}) | {candidate}, sectors)
        if after_candidate <= before:
            result.update(
                {
                    "chosen": candidate,
                    "intervention": candidate != original,
                    "hhi_after_chosen": after_candidate,
                    "chosen_rank": int(ranks[candidate]),
                }
            )
            return result
    result["fallback"] = True
    return result


def replay_r2(
    r1: Any,
    panel: pd.DataFrame,
    benchmark_by_date: dict[pd.Timestamp, dict[str, float]],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    daily: list[dict[str, Any]] = []
    interventions: list[dict[str, Any]] = []
    membership_records: list[tuple[str, tuple[str, ...]]] = []
    previous_shadow: set[str] | None = None
    previous_raw: set[str] | None = None
    previous_ranks: dict[str, int] = {}
    previous_sectors: dict[str, str] = {}
    no_trigger_change_count = 0
    off_surface_candidate_count = 0
    forced_invalid_retained_count = 0
    hhi_reconciliation_error_count = 0
    all_trigger_count = all_fallback_count = all_intervention_count = 0
    forced_trigger_count = forced_fallback_count = forced_intervention_count = 0

    for date, day in panel.groupby("signal_date", sort=True):
        day = day.sort_values(["a2_rank", "ticker"], kind="mergesort")
        ordered = day.ticker.astype(str).tolist()
        ranks = dict(zip(day.ticker.astype(str), day.a2_rank.astype(int)))
        sectors = dict(zip(day.ticker.astype(str), day.ff12.fillna("UNKNOWN").astype(str)))
        require(len(ordered) == len(set(ordered)) and len(ordered) > TOP_N, "DAILY_RANK_SURFACE", date)
        raw_ordered = ordered[:TOP_N]
        raw = set(raw_ordered)
        benchmark = benchmark_by_date.get(pd.Timestamp(date))
        require(benchmark is not None, "BENCHMARK_DATE_MISSING", date)

        optional_requests = optional_triggers = optional_alternatives = optional_fallbacks = 0
        actual_entry_slot = 0
        if previous_shadow is None:
            shadow = set(raw)
        else:
            shadow = set(previous_shadow)
            forced = sorted(name for name in shadow if name not in ranks)
            for name in forced:
                sectors[name] = previous_sectors.get(name, "UNKNOWN")
            for exit_name in forced:
                actual_entry_slot += 1
                candidates = [name for name in raw_ordered if name not in shadow]
                if not candidates:
                    candidates = [name for name in ordered if name not in shadow]
                require(bool(candidates), "FORCED_REPLACEMENT_CANDIDATE", date)
                original = candidates[0]
                selection = select_direct_hhi(
                    r1, original, exit_name, shadow, ordered, sectors, ranks
                )
                all_trigger_count += int(selection["trigger"])
                all_fallback_count += int(selection["fallback"])
                all_intervention_count += int(selection["intervention"])
                forced_trigger_count += int(selection["trigger"])
                forced_fallback_count += int(selection["fallback"])
                forced_intervention_count += int(selection["intervention"])
                if not selection["trigger"] and selection["chosen"] != original:
                    no_trigger_change_count += 1
                if selection["chosen"] not in ranks:
                    off_surface_candidate_count += 1
                if selection["intervention"]:
                    interventions.append(
                        intervention_record(
                            date,
                            actual_entry_slot,
                            "FORCED_EXIT_REPLACEMENT",
                            exit_name,
                            original,
                            selection,
                        )
                    )
                shadow.remove(exit_name)
                shadow.add(selection["chosen"])
                if exit_name in shadow:
                    forced_invalid_retained_count += 1

            new_entries = sorted(
                raw - (previous_raw or set()), key=lambda name: (ranks[name], name)
            )
            raw_exits = sorted(
                (previous_raw or set()) - raw,
                key=lambda name: (-previous_ranks.get(name, -1), name),
            )
            for index, original in enumerate(new_entries):
                optional_requests += 1
                if original in shadow:
                    continue
                actual_entry_slot += 1
                paired_exit = raw_exits[index] if index < len(raw_exits) else None
                if paired_exit not in shadow:
                    outside = [name for name in shadow if name not in raw]
                    require(bool(outside), "OPTIONAL_EXIT_CANDIDATE", {"date": str(date), "entrant": original})
                    paired_exit = sorted(
                        outside, key=lambda name: (-ranks.get(name, 10**9), name)
                    )[0]
                if paired_exit not in sectors:
                    sectors[paired_exit] = previous_sectors.get(paired_exit, "UNKNOWN")
                selection = select_direct_hhi(
                    r1, original, paired_exit, shadow, ordered, sectors, ranks
                )
                optional_triggers += int(selection["trigger"])
                optional_fallbacks += int(selection["fallback"])
                optional_alternatives += int(selection["intervention"])
                all_trigger_count += int(selection["trigger"])
                all_fallback_count += int(selection["fallback"])
                all_intervention_count += int(selection["intervention"])
                if not selection["trigger"] and selection["chosen"] != original:
                    no_trigger_change_count += 1
                if selection["chosen"] not in ranks:
                    off_surface_candidate_count += 1
                if selection["intervention"]:
                    interventions.append(
                        intervention_record(
                            date,
                            actual_entry_slot,
                            "OPTIONAL_RAW_A2_ENTRY",
                            paired_exit,
                            original,
                            selection,
                        )
                    )
                shadow.remove(paired_exit)
                shadow.add(selection["chosen"])

        require(len(shadow) == TOP_N and shadow.issubset(set(ordered)), "SHADOW_IDENTITY", date)
        raw_hhi = r1.hhi(raw, sectors)
        r2_hhi = r1.hhi(shadow, sectors)
        if abs(raw_hhi - hhi_from_counts(raw, sectors)) > NUMERICAL_VALIDATION_TOLERANCE:
            hhi_reconciliation_error_count += 1
        if abs(r2_hhi - hhi_from_counts(shadow, sectors)) > NUMERICAL_VALIDATION_TOLERANCE:
            hhi_reconciliation_error_count += 1
        row = {
            "signal_date": pd.Timestamp(date).date().isoformat(),
            "optional_entry_requests": optional_requests,
            "hhi_guard_triggers": optional_triggers,
            "hhi_compliant_alternatives": optional_alternatives,
            "hhi_fallbacks": optional_fallbacks,
            "forced_exit_count": len(forced) if previous_shadow is not None else 0,
            "raw_a2_hhi": raw_hhi,
            "r2_hhi": r2_hhi,
            "raw_a2_max_active_overweight": r1.max_active(raw, sectors, benchmark),
            "r2_max_active_overweight": r1.max_active(shadow, sectors, benchmark),
            "membership_difference_rate": 1.0 - len(raw & shadow) / TOP_N,
            "raw_structural_turnover": r1.turnover(previous_raw, raw),
            "r2_structural_turnover": r1.turnover(previous_shadow, shadow),
        }
        daily.append(row)
        membership_records.append((row["signal_date"], tuple(sorted(shadow))))
        previous_shadow = set(shadow)
        previous_raw = set(raw)
        previous_ranks = ranks
        previous_sectors = {ticker: sectors[ticker] for ticker in shadow}

    daily_frame = pd.DataFrame(daily)
    intervention_frame = pd.DataFrame(interventions)
    replay_hash = stable_hash(
        {
            "daily": daily,
            "interventions": interventions,
            "memberships": membership_records,
        }
    )
    facts = {
        "logical_replay_sha256": replay_hash,
        "no_trigger_change_count": no_trigger_change_count,
        "off_surface_candidate_count": off_surface_candidate_count,
        "forced_invalid_retained_count": forced_invalid_retained_count,
        "hhi_reconciliation_error_count": hhi_reconciliation_error_count,
        "all_trigger_count": all_trigger_count,
        "all_fallback_count": all_fallback_count,
        "all_intervention_count": all_intervention_count,
        "forced_trigger_count": forced_trigger_count,
        "forced_fallback_count": forced_fallback_count,
        "forced_intervention_count": forced_intervention_count,
        "initialization_exact": membership_records[0][1]
        == tuple(sorted(panel.loc[panel.signal_date.eq(panel.signal_date.min())].sort_values(["a2_rank", "ticker"]).head(TOP_N).ticker.astype(str))),
    }
    return daily_frame, intervention_frame, facts


def intervention_record(
    date: pd.Timestamp,
    slot: int,
    request_type: str,
    exit_ticker: str,
    original: str,
    selection: dict[str, Any],
) -> dict[str, Any]:
    return {
        "signal_date": pd.Timestamp(date).date().isoformat(),
        "slot": int(slot),
        "request_type": request_type,
        "exit_ticker": str(exit_ticker),
        "canonical_entrant": str(original),
        "alternative_entrant": str(selection["chosen"]),
        "canonical_rank": int(selection["canonical_rank"]),
        "alternative_rank": int(selection["chosen_rank"]),
        "rank_displacement": int(selection["chosen_rank"] - selection["canonical_rank"]),
        "HHI_BEFORE_ENTRY": float(selection["hhi_before"]),
        "HHI_AFTER_CANONICAL": float(selection["hhi_after_canonical"]),
        "HHI_AFTER_R2_ALTERNATIVE": float(selection["hhi_after_chosen"]),
        "alternative_minus_before": float(selection["hhi_after_chosen"] - selection["hhi_before"]),
        "alternative_minus_canonical": float(selection["hhi_after_chosen"] - selection["hhi_after_canonical"]),
    }


def build_frozen_contract(
    protocol: dict[str, Any],
    protocol_sha: str,
    validation: dict[str, Any],
    source_hashes: dict[str, str],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "frozen_name": FROZEN_NAME,
        "rule_family": RULE_FAMILY,
        "status": "FROZEN_RESEARCH_SHADOW_CONTRACT",
        "r2_design_protocol_path": str(PROTOCOL),
        "r2_design_protocol_sha256": protocol_sha,
        "parent_a2": protocol["parent_a2"],
        "parent_mechanism_audit": protocol["parent_mechanism_audit"],
        "r1_failed_design": protocol["r1_failed_design"],
        "targeted_delta_audit": protocol["targeted_delta_audit"],
        "hhi_definition": protocol["hhi_definition"],
        "entry_rule": protocol["entry_rule"],
        "state_transition": protocol["state_transition"],
        "prohibitions": protocol["prohibitions"],
        "future_evaluation": protocol["future_evaluation"],
        "source_hashes": source_hashes,
        "structural_validation": validation,
        "canonical_registry_change": False,
        "raw_a2_unchanged": True,
        "prospective_a2_x0_protocol_untouched": True,
    }
    payload["contract_payload_sha256"] = stable_hash(payload)
    return payload


def dry_run() -> None:
    r1 = import_r1()
    verify_frozen_inputs(r1)
    protocol, protocol_sha = verify_protocol()
    protected_before, protected_count = r1.tree_hash(PROSPECTIVE)
    registry_before = sha256_file(REGISTRY)
    require(
        protected_before == protocol["protected_state_at_freeze"]["prospective_tree_sha256"],
        "PROSPECTIVE_CHANGED_SINCE_PROTOCOL_FREEZE",
    )
    require(
        registry_before == protocol["protected_state_at_freeze"]["registry_sha256"],
        "REGISTRY_CHANGED_SINCE_PROTOCOL_FREEZE",
    )

    panel, benchmark, input_facts = r1.load_structural_inputs()
    first_daily, first_ledger, facts1 = replay_r2(r1, panel, benchmark)
    second_daily, second_ledger, facts2 = replay_r2(r1, panel, benchmark)
    deterministic = (
        facts1["logical_replay_sha256"] == facts2["logical_replay_sha256"]
        and first_daily.equals(second_daily)
        and first_ledger.equals(second_ledger)
    )

    optional_requests = int(first_daily.optional_entry_requests.sum())
    optional_triggers = int(first_daily.hhi_guard_triggers.sum())
    optional_alternatives = int(first_daily.hhi_compliant_alternatives.sum())
    optional_fallbacks = int(first_daily.hhi_fallbacks.sum())
    optional_ledger = first_ledger.loc[
        first_ledger.request_type.eq("OPTIONAL_RAW_A2_ENTRY")
    ] if not first_ledger.empty else first_ledger
    signed_adverse = (
        first_ledger.HHI_AFTER_R2_ALTERNATIVE - first_ledger.HHI_BEFORE_ENTRY
        if not first_ledger.empty
        else pd.Series(dtype=float)
    )
    violation_count = int((signed_adverse > 0.0).sum())
    max_adverse = float(max(0.0, signed_adverse.max())) if len(signed_adverse) else 0.0
    comparison = (
        first_ledger.HHI_AFTER_R2_ALTERNATIVE - first_ledger.HHI_AFTER_CANONICAL
        if not first_ledger.empty
        else pd.Series(dtype=float)
    )
    raw_turnover = float(first_daily.raw_structural_turnover.sum())
    r2_turnover = float(first_daily.r2_structural_turnover.sum())
    require(raw_turnover > 0.0, "RAW_TURNOVER_DENOMINATOR")
    displacement = first_ledger.rank_displacement.astype(float) if not first_ledger.empty else pd.Series(dtype=float)
    metrics = {
        "total_signal_dates": int(len(first_daily)),
        "total_optional_entry_requests": optional_requests,
        "hhi_guard_trigger_count": optional_triggers,
        "hhi_guard_trigger_share": float(optional_triggers / optional_requests) if optional_requests else 0.0,
        "hhi_compliant_alternative_count": optional_alternatives,
        "hhi_fallback_count": optional_fallbacks,
        "hhi_fallback_share_of_triggers": float(optional_fallbacks / optional_triggers) if optional_triggers else 0.0,
        "intervention_count": optional_alternatives,
        "intervention_share": float(optional_alternatives / optional_requests) if optional_requests else 0.0,
        "all_intervention_count_including_forced": int(len(first_ledger)),
        "forced_guard_trigger_count": int(facts1["forced_trigger_count"]),
        "forced_compliant_alternative_count": int(facts1["forced_intervention_count"]),
        "forced_fallback_count": int(facts1["forced_fallback_count"]),
        "average_canonical_entrant_rank": float(first_ledger.canonical_rank.mean()) if len(first_ledger) else None,
        "average_selected_alternative_rank": float(first_ledger.alternative_rank.mean()) if len(first_ledger) else None,
        "average_rank_displacement": float(displacement.mean()) if len(displacement) else None,
        "p90_rank_displacement": float(displacement.quantile(0.90)) if len(displacement) else None,
        "max_rank_displacement": int(displacement.max()) if len(displacement) else None,
        "average_raw_a2_hhi": float(first_daily.raw_a2_hhi.mean()),
        "average_r2_hhi": float(first_daily.r2_hhi.mean()),
        "p50_raw_a2_hhi": float(first_daily.raw_a2_hhi.quantile(0.50)),
        "p50_r2_hhi": float(first_daily.r2_hhi.quantile(0.50)),
        "p90_raw_a2_hhi": float(first_daily.raw_a2_hhi.quantile(0.90)),
        "p90_r2_hhi": float(first_daily.r2_hhi.quantile(0.90)),
        "max_raw_a2_hhi": float(first_daily.raw_a2_hhi.max()),
        "max_r2_hhi": float(first_daily.r2_hhi.max()),
        "average_active_overweight_raw": float(first_daily.raw_a2_max_active_overweight.mean()),
        "average_active_overweight_r2": float(first_daily.r2_max_active_overweight.mean()),
        "holding_membership_difference_rate": float(first_daily.membership_difference_rate.mean()),
        "maximum_daily_membership_difference_rate": float(first_daily.membership_difference_rate.max()),
        "structural_turnover_difference_rate": float((r2_turnover - raw_turnover) / raw_turnover),
        "raw_structural_turnover_total": raw_turnover,
        "r2_structural_turnover_total": r2_turnover,
        "intervention_hhi_violation_count": violation_count,
        "max_adverse_intervention_hhi_change": max_adverse,
        "max_signed_intervention_hhi_change": float(signed_adverse.max()) if len(signed_adverse) else 0.0,
        "r2_better_than_canonical_hhi_count": int((comparison < 0.0).sum()),
        "r2_equal_canonical_hhi_count": int((comparison == 0.0).sum()),
        "r2_worse_than_canonical_hhi_count": int((comparison > 0.0).sum()),
        "logical_replay_sha256": facts1["logical_replay_sha256"],
        "structural_intrusiveness_warning": bool(len(displacement) and displacement.max() > TOP_N),
    }
    gates = {
        "intervention_hhi_nonincreasing": violation_count == 0,
        "max_adverse_within_numerical_tolerance": max_adverse <= NUMERICAL_VALIDATION_TOLERANCE,
        "deterministic_transition": deterministic,
        "no_transition_change_when_guard_not_triggered": facts1["no_trigger_change_count"] == 0,
        "all_candidates_on_authoritative_surface": facts1["off_surface_candidate_count"] == 0,
        "forced_invalid_holdings_retained_zero": facts1["forced_invalid_retained_count"] == 0,
        "identity_and_initialization": bool(facts1["initialization_exact"]),
        "temporal_integrity": int(input_facts["taxonomy"]["future_filing_violation_count"]) == 0 and panel.signal_date.max() < pd.Timestamp("2026-01-01"),
        "hhi_arithmetic_reconciled": facts1["hhi_reconciliation_error_count"] == 0,
        "economic_outcome_read_count_zero": input_facts["economic_outcome_read_count"] == 0,
        "canonical_comparison_not_worse": metrics["r2_worse_than_canonical_hhi_count"] == 0,
    }
    if not deterministic:
        final_classification = "FAIL_NONDETERMINISTIC_TRANSITION"
    elif violation_count > 0 or max_adverse > NUMERICAL_VALIDATION_TOLERANCE:
        final_classification = "FAIL_HHI_INTERVENTION_VIOLATION"
    elif not all(gates.values()):
        final_classification = "FAIL_STRUCTURAL_DEGENERACY"
    else:
        final_classification = "PASS_FROZEN_A2_HHI_NONINCREASING_ENTRY_GUARD_R2"
    passed = final_classification.startswith("PASS_")

    first_daily.to_csv(OUT / "structural_dry_run.csv", index=False, float_format="%.12g")
    first_ledger.to_parquet(OUT / "intervention_ledger.parquet", index=False)
    protected_after, protected_count_after = r1.tree_hash(PROSPECTIVE)
    registry_after = sha256_file(REGISTRY)
    require((protected_before, protected_count) == (protected_after, protected_count_after), "PROSPECTIVE_TREE_CHANGED")
    require(registry_before == registry_after == EXPECTED[REGISTRY], "REGISTRY_CHANGED")
    require(not repo_temp_dirs(), "TASK_REPO_ROOT_TEMP_CREATED", [str(path) for path in repo_temp_dirs()])

    source_hashes = {
        "raw_a2_model": sha256_file(r1.MODEL),
        "authoritative_oof_ranking": sha256_file(r1.OOF),
        "pit_ff12_ff48_taxonomy": sha256_file(r1.TAXONOMY),
        "benchmark_sector_attribution": sha256_file(r1.BENCHMARK),
        "r1_transition_source": sha256_file(R1_SOURCE),
        "r1_failed_contract": sha256_file(R1_CONTRACT),
        "parent_risk_protocol": sha256_file(PARENT_PROTOCOL),
    }
    validation = {
        "status": "PASS" if passed else "FAIL",
        "classification": final_classification,
        "logical_replay_sha256": facts1["logical_replay_sha256"],
        "hard_gates": gates,
        "metrics_sha256": stable_hash(metrics),
        "intervention_ledger_logical_sha256": stable_hash(first_ledger.to_dict(orient="records")),
        "economic_outcome_read_count": 0,
    }
    contract_sha: str | None = None
    if passed:
        write_json(
            FROZEN_CONTRACT,
            build_frozen_contract(protocol, protocol_sha, validation, source_hashes),
        )
        contract_sha = sha256_file(FROZEN_CONTRACT)

    manifest = {
        "task_id": protocol["task_id"],
        "structural_only": True,
        "economic_outcome_read_count": 0,
        "source_hashes": source_hashes,
        "columns_opened": {
            str(r1.OOF): ["signal_date", "ticker", "universe_size", "split", "a2_model_name", "a2_prediction", "a2_rank"],
            str(r1.BENCHMARK): ["record_type", "signal_date", "taxonomy_level", "sector", "benchmark_weight"],
            str(r1.TAXONOMY): ["signal_date", "ticker", "pit_sic", "ff12", "ff48"],
            "economic_outcome_columns": [],
        },
        "derived_input_identity": input_facts,
        "protected_assets": {
            "prospective_tree_sha256_before": protected_before,
            "prospective_tree_sha256_after": protected_after,
            "prospective_tree_file_count": protected_count,
            "registry_sha256_before": registry_before,
            "registry_sha256_after": registry_after,
        },
        "task_owned_repo_root_temp_dir_count": 0,
    }
    write_json(OUT / "source_manifest.json", manifest)
    summary = {
        "status": "PASS" if passed else "FAIL",
        "final_classification": final_classification,
        "r2_design_protocol_sha256": protocol_sha,
        "r2_frozen_contract_sha256": contract_sha,
        "frozen_name": FROZEN_NAME,
        "rule_family": RULE_FAMILY,
        "r1_prior_art_reused": True,
        "targeted_delta_audit_status": "PASS_NO_EXACT_R2_RULE",
        "exact_r2_rule_already_exists": False,
        "reused_r1_transition_engine": True,
        "reused_r1_candidate_scan_logic": True,
        "reused_r1_taxonomy": True,
        "reused_r1_benchmark_logic": True,
        "reused_r1_cost_logic": True,
        "new_portfolio_engine_created": False,
        "new_risk_optimizer_created": False,
        "new_generic_risk_framework_created": False,
        "numeric_sector_cap_used": False,
        "parameter_search_count": 0,
        "decision_variable": "SECTOR_HHI",
        "beta_constraint_active": False,
        "rx_margin_active": False,
        "tail_control_active": False,
        "structural_metrics": metrics,
        "hard_gates": gates,
        "economic_outcome_read_count": 0,
        "canonical_registry_change": False,
        "raw_a2_unchanged": True,
        "prospective_a2_x0_protocol_untouched": True,
        "task_owned_repo_root_temp_dir_count": 0,
        "next_research_priority": "EVALUATE_FROZEN_A2_HHI_NONINCREASING_ENTRY_GUARD_R2" if passed else "REQUIRE_R3_FOR_ANY_REDESIGN",
    }
    write_json(OUT / "summary.json", summary)
    write_report(summary)
    print_console(summary)


def write_report(summary: dict[str, Any]) -> None:
    m = summary["structural_metrics"]
    report = f"""# A2 direct-HHI nonincreasing entry guard R2

## Result

**{summary['final_classification']}**

R2 changed only R1's candidate admissibility predicate. The state transition, canonical entrant/exit pairing, full authoritative rank scan, PIT FF12 taxonomy, benchmark reporting, equal weights, execution timing, and 10 bps one-way cost convention were reused. The decision variable is now direct portfolio FF12 HHI: intervention occurs only when the canonical swap raises HHI, and an alternative is admitted only when its swap HHI is no greater than the pre-swap 20-name HHI.

## Structural diagnostics

- Signal dates / optional requests: {m['total_signal_dates']} / {m['total_optional_entry_requests']}
- Optional guard triggers: {m['hhi_guard_trigger_count']} ({m['hhi_guard_trigger_share']:.2%})
- Optional interventions / fallbacks: {m['intervention_count']} / {m['hhi_fallback_count']}
- Mean rank displacement / P90 / maximum: {m['average_rank_displacement']:.3f} / {m['p90_rank_displacement']:.3f} / {m['max_rank_displacement']}
- Mean Raw / R2 HHI: {m['average_raw_a2_hhi']:.6f} / {m['average_r2_hhi']:.6f}
- P90 Raw / R2 HHI: {m['p90_raw_a2_hhi']:.6f} / {m['p90_r2_hhi']:.6f}
- Mean membership difference: {m['holding_membership_difference_rate']:.2%}
- Structural turnover difference: {m['structural_turnover_difference_rate']:.2%}
- Intrusiveness warning: {str(m['structural_intrusiveness_warning']).upper()} (warning only; no rejection threshold)

## Hard HHI validation

- Intervention violations: {m['intervention_hhi_violation_count']}
- Maximum adverse intervention HHI change: {m['max_adverse_intervention_hhi_change']:.12g}
- Better / equal / worse than canonical HHI: {m['r2_better_than_canonical_hhi_count']} / {m['r2_equal_canonical_hhi_count']} / {m['r2_worse_than_canonical_hhi_count']}
- Deterministic replay SHA-256: `{m['logical_replay_sha256']}`

No economic outcome column was opened. Raw A2, the canonical registry, R1 artifacts, and the protected A2/X0 prospective tree are unchanged. Any later economics must use the frozen `RETROSPECTIVE_EXPOSED_SHADOW_DIAGNOSTIC` comparison and may not retune R2 in place.
"""
    (OUT / "concise_report.md").write_text(report, encoding="utf-8")


def fmt(value: Any) -> str:
    if value is None:
        return "NOT_APPLICABLE"
    return f"{value:.12g}" if isinstance(value, float) else str(value)


def print_console(summary: dict[str, Any]) -> None:
    m = summary["structural_metrics"]
    lines = [
        "============================================================",
        "A2 HHI NONINCREASING ENTRY GUARD R2",
        "============================================================",
        f"STATUS={summary['status']}",
        "",
        f"R2_DESIGN_PROTOCOL_SHA256={summary['r2_design_protocol_sha256']}",
        "",
        "------------------------------------------------------------",
        "ANTI-DUPLICATION",
        "------------------------------------------------------------",
        "R1_PRIOR_ART_REUSED=TRUE",
        "TARGETED_DELTA_AUDIT_STATUS=PASS_NO_EXACT_R2_RULE",
        "EXACT_R2_RULE_ALREADY_EXISTS=FALSE",
        "",
        "REUSED_R1_TRANSITION_ENGINE=TRUE",
        "REUSED_R1_CANDIDATE_SCAN_LOGIC=TRUE",
        "REUSED_R1_TAXONOMY=TRUE",
        "",
        "NEW_PORTFOLIO_ENGINE_CREATED=FALSE",
        "NEW_RISK_OPTIMIZER_CREATED=FALSE",
        "NEW_GENERIC_RISK_FRAMEWORK_CREATED=FALSE",
        "",
        "------------------------------------------------------------",
        "RULE",
        "------------------------------------------------------------",
        f"FROZEN_NAME={FROZEN_NAME}",
        f"RULE_FAMILY={RULE_FAMILY}",
        "",
        "NUMERIC_SECTOR_CAP_USED=FALSE",
        "PARAMETER_SEARCH_COUNT=0",
        "",
        "DECISION_VARIABLE=SECTOR_HHI",
        "",
        "BETA_CONSTRAINT_ACTIVE=FALSE",
        "RX_MARGIN_ACTIVE=FALSE",
        "TAIL_CONTROL_ACTIVE=FALSE",
        "",
        "------------------------------------------------------------",
        "STRUCTURAL",
        "------------------------------------------------------------",
        f"TOTAL_SIGNAL_DATES={m['total_signal_dates']}",
        f"TOTAL_OPTIONAL_ENTRY_REQUESTS={m['total_optional_entry_requests']}",
        "",
        f"HHI_GUARD_TRIGGER_COUNT={m['hhi_guard_trigger_count']}",
        f"HHI_GUARD_TRIGGER_SHARE={fmt(m['hhi_guard_trigger_share'])}",
        "",
        f"HHI_COMPLIANT_ALTERNATIVE_COUNT={m['hhi_compliant_alternative_count']}",
        f"HHI_FALLBACK_COUNT={m['hhi_fallback_count']}",
        f"HHI_FALLBACK_SHARE_OF_TRIGGERS={fmt(m['hhi_fallback_share_of_triggers'])}",
        "",
        f"INTERVENTION_COUNT={m['intervention_count']}",
        f"INTERVENTION_SHARE={fmt(m['intervention_share'])}",
        "",
        f"AVG_RANK_DISPLACEMENT={fmt(m['average_rank_displacement'])}",
        f"P90_RANK_DISPLACEMENT={fmt(m['p90_rank_displacement'])}",
        f"MAX_RANK_DISPLACEMENT={fmt(m['max_rank_displacement'])}",
        "",
        f"AVG_RAW_A2_HHI={fmt(m['average_raw_a2_hhi'])}",
        f"AVG_R2_HHI={fmt(m['average_r2_hhi'])}",
        "",
        f"P90_RAW_A2_HHI={fmt(m['p90_raw_a2_hhi'])}",
        f"P90_R2_HHI={fmt(m['p90_r2_hhi'])}",
        "",
        f"HOLDING_MEMBERSHIP_DIFFERENCE_RATE={fmt(m['holding_membership_difference_rate'])}",
        f"STRUCTURAL_TURNOVER_DIFFERENCE_RATE={fmt(m['structural_turnover_difference_rate'])}",
        f"STRUCTURAL_INTRUSIVENESS_WARNING={str(m['structural_intrusiveness_warning']).upper()}",
        "",
        "------------------------------------------------------------",
        "HARD HHI VALIDATION",
        "------------------------------------------------------------",
        f"INTERVENTION_HHI_VIOLATION_COUNT={m['intervention_hhi_violation_count']}",
        f"MAX_ADVERSE_INTERVENTION_HHI_CHANGE={fmt(m['max_adverse_intervention_hhi_change'])}",
        "",
        f"R2_BETTER_THAN_CANONICAL_HHI_COUNT={m['r2_better_than_canonical_hhi_count']}",
        f"R2_EQUAL_CANONICAL_HHI_COUNT={m['r2_equal_canonical_hhi_count']}",
        f"R2_WORSE_THAN_CANONICAL_HHI_COUNT={m['r2_worse_than_canonical_hhi_count']}",
        "",
        "------------------------------------------------------------",
        "SAFETY",
        "------------------------------------------------------------",
        "ECONOMIC_OUTCOME_READ_COUNT=0",
        "",
        "BETA_CONSTRAINT_ACTIVE=FALSE",
        "RX_MARGIN_ACTIVE=FALSE",
        "TAIL_CONTROL_ACTIVE=FALSE",
        "",
        "CANONICAL_REGISTRY_CHANGE=FALSE",
        "RAW_A2_UNCHANGED=TRUE",
        "PROSPECTIVE_A2_X0_PROTOCOL_UNTOUCHED=TRUE",
        "",
        "TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT=0",
        "",
        "------------------------------------------------------------",
        "FREEZE",
        "------------------------------------------------------------",
        f"R2_FROZEN_CONTRACT_SHA256={summary['r2_frozen_contract_sha256'] or 'NOT_CREATED'}",
        "",
        f"FINAL_CLASSIFICATION={summary['final_classification']}",
        "",
        f"NEXT_RESEARCH_PRIORITY={summary['next_research_priority']}",
        "",
        f"ARTIFACT_DIR={OUT}",
        "============================================================",
    ]
    print("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["freeze", "dry-run"])
    args = parser.parse_args()
    if args.phase == "freeze":
        freeze_protocol()
    else:
        dry_run()


if __name__ == "__main__":
    main()
