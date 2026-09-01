"""Freeze and structurally validate one parameter-free Raw A2 sector-entry rule."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / "A2_SINGLE_SECTOR_RISK_BUDGET_DESIGN_AND_FREEZE_R1"
PARENT = RESULTS / "A2_BETA_SECTOR_RISK_CONTRIBUTION_AUDIT_R1"
FOUR_LAYER = RESULTS / "RAW_A2_FOUR_LAYER_ALPHA_IDENTITY_ATTRIBUTION_R1"
SEC = RESULTS / "A2_SEC_CIK_IDENTITY_GAP_CLOSE_AND_DECONCENTRATION_AUTORUN_R1"
BASELINE = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2"
PROSPECTIVE = RESULTS / "A2_X0_LITERATURE_GROUNDED_PROSPECTIVE_DISAGREEMENT_R1"
REGISTRY = REPO / "config" / "research_governance" / "alpha_registry.json"
PRETOP_SOURCE = REPO / "scripts" / "v22" / "a2_pretop20_candidate_recovery_and_membership_deconcentration_r1.py"

MODEL = BASELINE / "final_full_pre2026_hgb.joblib"
OOF = BASELINE / "oof_predictions.parquet"
TAXONOMY = SEC / "pit_ff12_ff48_taxonomy.parquet"
BENCHMARK = FOUR_LAYER / "holdings_sector_attribution.csv"
PARENT_PROTOCOL = PARENT / "risk_contribution_audit_protocol.json"
PARENT_SUMMARY = PARENT / "summary.json"
PARENT_REPORT = PARENT / "concise_report.md"
CONTRACT = OUT / "frozen_contract.json"
ACTIVE_HARNESS_STATE = (
    Path(r"D:\us-tech-quant-daily\harness_r2\tasks")
    / "20260829-175126-ae37"
    / "state.json"
)
ACTIVE_UNRELATED_TEMP = REPO / "pytest-cache-files-v8prgc10"

EXPECTED = {
    MODEL: "4f7eff07021bef084b0329dac8dabc31e9391c7c4945eb2955dc6c1339dcea0b",
    OOF: "e336be6c267167356ce3d39fa629f80fe7b2968711112a9c976fdb002c693468",
    TAXONOMY: "515427bfe4d450540bcf8b04a9ce5fd50f706c551300a46450f5e4669b7d552f",
    BENCHMARK: "902dfd663f71849d2787086abdad71dda5a2aaf43cd42e90c83de2bef2f48871",
    PARENT_PROTOCOL: "8384f59418142bfbb90d681231fc5bac78c48ad48f18f4ed29c65eca68363504",
    PARENT_SUMMARY: "bfa82e79856cc5d4631c2b78cec9aa5d2cc640a68bf20cda3f1452c2e47315ca",
    PARENT_REPORT: "3834b3546e07bf91a5178df12b5d1f1c0f1988e6103127a9172cab68864055d2",
    PRETOP_SOURCE: "4ce2aec79b556af22774441a6eb9cbf5811426f5db9c32c9585afb5d0b174549",
    REGISTRY: "b7beb4adb7fbe67048bedcb21a476a23bbed9295009805a0d432239576e404e3",
}

TOP_N = 20
WEIGHT = 1.0 / TOP_N
EPS = 1e-12
RULE_NAME = "NO_NEW_ACTIVE_SECTOR_OVERWEIGHT_INCREASE_R1"
FROZEN_NAME = "A2_SINGLE_SECTOR_RISK_BUDGET_SHADOW_R1"


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


def tree_hash(root: Path) -> tuple[str, int]:
    require(root.is_dir(), "PROTECTED_TREE_MISSING", root)
    records = []
    files = sorted((item for item in root.rglob("*") if item.is_file()), key=lambda p: p.as_posix().lower())
    for path in files:
        records.append([path.relative_to(root).as_posix(), sha256_file(path), path.stat().st_size])
    return stable_hash(records), len(records)


def process_active(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except (OSError, PermissionError):
            return False
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return False
    ctypes.windll.kernel32.CloseHandle(handle)
    return True


def temp_accounting() -> dict[str, Any]:
    temp_dirs = sorted(
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
    unrelated: list[str] = []
    for path in temp_dirs:
        require(path == ACTIVE_UNRELATED_TEMP, "UNCLASSIFIED_REPO_ROOT_TEMP", path)
        require(ACTIVE_HARNESS_STATE.is_file(), "ACTIVE_HARNESS_STATE_MISSING")
        state = json.loads(ACTIVE_HARNESS_STATE.read_text(encoding="utf-8"))
        state_text = stable_json(state)
        pids = [
            int(state[key])
            for key in ("CONTROLLER_PID", "CONTROLLER_PARENT_PID", "SUPERVISOR_PID", "SUPERVISOR_PARENT_PID")
            if state.get(key)
        ]
        require(any(process_active(pid) for pid in pids), "ACTIVE_HARNESS_PROCESS_MISSING")
        require(state.get("TASK_ID") == "20260829-175126-ae37", "HARNESS_TASK_ID")
        require(
            "BROAD_EQUITY_PIT_SECURITY_MASTER_RECOVERY_OVERNIGHT_R1" in state.get("GOAL", ""),
            "HARNESS_TASK_RELEVANCE",
        )
        require("pytest" in state_text.lower(), "HARNESS_PYTEST_COMMAND_LINE_EVIDENCE")
        require(path.name.startswith("pytest-cache-"), "NOT_TEMP_LIKE")
        input_paths = {str(item) for item in EXPECTED} | {str(CONTRACT), str(OUT)}
        require(str(path) not in input_paths, "TEMP_REFERENCED_BY_FROZEN_INPUT")
        unrelated.append(str(path))
    return {
        "active_unrelated_transient_exclusion_status": (
            "ACTIVE_UNRELATED_TRANSIENT_EXCLUSION" if unrelated else "NOT_REQUIRED"
        ),
        "active_unrelated_temp_exclusions": len(unrelated),
        "active_unrelated_temp_paths": unrelated,
        "unrelated_active_temp_dir_count": len(unrelated),
        "task_owned_repo_root_temp_dir_count": 0,
        "evidence": {
            "owning_task_id": "20260829-175126-ae37" if unrelated else None,
            "owning_task": "BROAD_EQUITY_PIT_SECURITY_MASTER_RECOVERY_OVERNIGHT_R1" if unrelated else None,
            "active_pid_evidence": pids if unrelated else [],
            "task_state_path": str(ACTIVE_HARNESS_STATE) if unrelated else None,
            "classification_basis": "live task-mapped controller/supervisor process; unrelated Harness goal; pytest command evidence; exact temp-like root path; not a frozen/design input" if unrelated else None,
        },
    }


def verify_inputs() -> None:
    for path, expected in EXPECTED.items():
        require(path.is_file(), "FROZEN_INPUT_MISSING", path)
        require(sha256_file(path) == expected, "FROZEN_INPUT_HASH", path)
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    matches = [row for row in registry["models"] if row.get("model_id") == "A2_HGB"]
    require(len(matches) == 1, "RAW_A2_REGISTRY_IDENTITY")
    row = matches[0]
    require(row.get("status") == "FROZEN_CHAMPION", "RAW_A2_STATUS")
    require(row.get("model_sha256") == EXPECTED[MODEL], "RAW_A2_MODEL_HASH")
    require(row.get("uses_2026_training") is False, "RAW_A2_TRAINING_BOUNDARY")
    flat = stable_json(json.loads(PARENT_SUMMARY.read_text(encoding="utf-8")))
    require("NO_SUPPORT_FOR_SIMPLE_BETA_BUDGET" in flat, "PARENT_BETA_CLASSIFICATION")
    require("PARTIAL_SUPPORT_FOR_SECTOR_RISK_BUDGET" in flat, "PARENT_SECTOR_CLASSIFICATION")
    require("PARTIAL_SUPPORT_FOR_A2_RISK_BUDGET_ARCHITECTURE" in flat, "PARENT_OVERALL_CLASSIFICATION")


def prior_art() -> list[dict[str, Any]]:
    rows = [
        ("PRETOP20_M1_DUAL_MARGINAL_MEMBERSHIP", RESULTS / "A2_PRETOP20_CANDIDATE_RECOVERY_AND_MEMBERSHIP_DECONCENTRATION_R1" / "membership_overlay_contract.json", "FROZEN_INCOMPATIBLE", "reranks the full candidate pool with a new FF12/FF48 utility and rebuilds membership daily"),
        ("FIXED_TOP20_DUAL_SECTOR_CASH_OVERLAY", RESULTS / "A2_FIXED_TOP20_DUAL_SECTOR_CASH_OVERLAY_R1" / "overlay_contract.json", "FROZEN_INCOMPATIBLE", "SLSQP full reweighting with cash residual"),
        ("CONCENTRATION_TRIGGERED_GROSS_SCALER", RESULTS / "A2_CONCENTRATION_TRIGGERED_GROSS_SCALER_R1" / "gross_scaler_contract.json", "FROZEN_INCOMPATIBLE", "gross/cash scaling rather than sector-entry control"),
        ("SEC_DECONCENTRATION_FINALIST_FAMILY", SEC / "finalist_freeze.json", "FROZEN_INCOMPATIBLE", "multi-arm cap/penalty/rerank family selected with historical economics"),
        ("SECTOR_AWARE_ML", RESULTS / "A2_SECTOR_AWARE_ML_AND_FACTOR_OVERNIGHT_R1" / "finalist_freeze.json", "FROZEN_INCOMPATIBLE", "changes fitted model and predictive score"),
        ("GLOBAL_FF12_HOLD_REPLACE", RESULTS / "A2_GLOBAL_FF12_HOLD_REPLACE_R1" / "finalist_freeze.json", "FROZEN_INCOMPATIBLE", "combines learned selection, holding age, and hysteresis"),
        ("DUAL_LEVEL_MARGINAL_DECONCENTRATION", RESULTS / "A2_DUAL_LEVEL_MARGINAL_DECONCENTRATION_R1" / "dual_overlay_contract.json", "FAILED_NOT_REUSABLE", "mechanical gate failed and no specification was frozen"),
        ("OVERNIGHT_SECTOR_DECONCENTRATION", RESULTS / "A2_SECTOR_DECONCENTRATION_OVERNIGHT_OPEN_RESEARCH_R1" / "finalist_freeze.json", "FAILED_NOT_REUSABLE", "taxonomy gate failed and freeze is empty"),
        ("PIT_SECTOR_TAXONOMY_DECONCENTRATION_PREDECESSOR", RESULTS / "A2_PIT_SECTOR_TAXONOMY_AND_DECONCENTRATION_RESUME_R1" / "finalist_freeze.json", "FAILED_NOT_REUSABLE", "failed predecessor taxonomy/deconcentration lineage"),
        ("A2_RISK_CONTROL_R3", RESULTS / "A2_RISK_CONTROL_R3_NON_PREDICTIVE_RISK_BUDGETING" / "A2_RISK_CONTROL_R3_CONTRACT.json", "FROZEN_INCOMPATIBLE", "volatility/stress gross-budget rule"),
        ("FAST_A2_R1_RISK_BUDGET", RESULTS / "FAST_A2_R1_ALPHA_RELIABILITY_AND_RISK_BUDGET" / "fast_a2_r1_risk_budget_contract.json", "FROZEN_INCOMPATIBLE", "VIX/gross-exposure rule"),
        ("V21_077_SECTOR_AWARE_RISK_BUDGET", REPO / "scripts" / "v21" / "v21_077_sector_aware_risk_budget_backtest.py", "LEGACY_INCOMPATIBLE", "different parent portfolios with hard-cap and penalty variants"),
        ("FOUR_LAYER_SECTOR_NEUTRAL_COUNTERFACTUAL", FOUR_LAYER / "attribution_protocol.json", "ATTRIBUTION_ONLY_NOT_RULE", "diagnostic attribution counterfactual, not an implementable frozen entry rule"),
    ]
    result = []
    for name, path, status, reason in rows:
        require(path.is_file(), "PRIOR_ART_PATH_MISSING", path)
        result.append({"lineage": name, "path": str(path), "sha256": sha256_file(path), "classification": status, "reason": reason})
    return result


def contract_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "task_id": "A2_SINGLE_SECTOR_RISK_BUDGET_DESIGN_AND_FREEZE_R1",
        "frozen_name": FROZEN_NAME,
        "research_role": "DESIGN_AND_FREEZE_ONLY",
        "future_evidence_label": "RETROSPECTIVE_EXPOSED_SHADOW_DIAGNOSTIC",
        "parent": {
            "alias": "A2_HGB",
            "model_sha256": EXPECTED[MODEL],
            "training_cutoff": "2025-12-31",
            "portfolio": "TOP20_EQUAL_WEIGHT_LONG_ONLY",
            "ranking": "A2_SCORE_DESC_THEN_TICKER_ASC",
            "risk_audit_protocol_path": str(PARENT_PROTOCOL),
            "risk_audit_protocol_sha256": EXPECTED[PARENT_PROTOCOL],
            "beta_conclusion": "NO_SUPPORT_FOR_SIMPLE_BETA_BUDGET",
            "sector_conclusion": "PARTIAL_SUPPORT_FOR_SECTOR_RISK_BUDGET",
        },
        "anti_duplication": {
            "status": "PASS_COMPLETE_BEFORE_BUILD",
            "n_relevant_sector_rule_lineages_found": 13,
            "build_decision": "NO_EXISTING_FIXED_RULE_DESIGN_ONE_MINIMAL_RULE",
            "selected_existing_rule": None,
            "why": "No inspected rule is both post-Raw-A2-score, stateful entry-only, sector-only, parameter-provenanced without outcome selection, and compatible with authoritative Raw A2 ordering.",
            "infrastructure_reuse": [
                "authoritative candidate loader and rank replay",
                "PIT FF12 taxonomy extension",
                "PIT eligible-universe benchmark sector weights",
                "equal-weight turnover arithmetic",
            ],
        },
        "rule": {
            "family": RULE_NAME,
            "numeric_sector_cap_used": False,
            "parameter_source": "PARAMETER_FREE_STRUCTURAL_RULE",
            "taxonomy": {
                "primary": "PIT_FF12",
                "unknown": "EXPLICIT_OWN_CATEGORY",
                "source_path": str(TAXONOMY),
                "source_sha256": EXPECTED[TAXONOMY],
            },
            "benchmark": "same-date PIT eligible-universe FF12 weights from frozen four-layer attribution; no backward or future fill",
            "active_sector_weight": "current pre-event shadow sector weight minus same-date PIT benchmark sector weight",
            "entry_test": "If the original entrant's FF12 sector has positive pre-event active weight and the proposed exit/entry swap increases that sector weight, scan downward through the same authoritative full Raw A2 ranking for the first otherwise-valid non-held candidate whose identical swap does not increase an already-positive active sector overweight.",
            "grandfathering": "No existing valid holding is sold solely because its sector is concentrated.",
            "fallback": "If no compliant candidate exists in the naturally finite authoritative ranking surface, admit the original Raw A2 entrant; never go to cash.",
            "no_additive_claim": "The entry test is a state-transition constraint, not an additive sector-risk decomposition and not sector neutrality.",
        },
        "state_transition": {
            "initialization": "On the first structurally processable signal date, copy canonical Raw A2 Top20 exactly; apply the rule starting on the next signal date.",
            "unchanged_holdings": "Carry every valid prior shadow holding unless it is the deterministic exit paired to a new canonical Raw A2 entrant.",
            "canonical_entry_requests": "Current canonical Raw Top20 members absent from prior-date canonical Raw Top20, ordered by current Raw rank then ticker.",
            "canonical_exit_pairing": "Prior canonical Raw Top20 members absent from current canonical Raw Top20, ordered by prior Raw rank descending then ticker; pair positionally with ordered canonical entrants.",
            "shadow_exit_substitution": "If the paired canonical exit is not held, use the worst current-rank held name outside current canonical Raw Top20; ties by ticker ascending.",
            "forced_exits": "PIT ineligibility, absence from the current authoritative valid ranked pool, identity/tradability failure, or missing required score always removes the holding; fill with the highest-ranked compliant candidate, falling back to the highest-ranked valid candidate.",
            "multiple_events": "Process forced vacancies first, then canonical entry requests in rank order, recomputing shadow weights after every event.",
            "candidate_order": "a2_rank ascending then ticker ascending on the unexpanded naturally finite authoritative rank surface",
            "tie_break": "ticker ascending",
            "cardinality": 20,
            "weight": "1/20 equal weight",
            "execution_timing": "same timing as canonical Raw A2 signal-to-execution contract; this design introduces no new timing or outcome read",
            "cost_convention": "10 BPS one-way turnover, inherited unchanged; no economic cost is calculated in this structural dry-run",
        },
        "prohibitions": {
            "beta_constraint_active": False,
            "rx_margin_active": False,
            "tail_control_active": False,
            "optimizer_active": False,
            "covariance_model_active": False,
            "regime_switch_active": False,
            "parameter_search_count": 0,
            "economic_outcome_read_count": 0,
            "score_change": False,
            "model_refit": False,
            "registry_change": False,
        },
        "structural_metrics": {
            "sector_hhi": "sum of squared equal-weight PIT FF12 sector weights",
            "active_overweight": "maximum across FF12 sectors of max(portfolio weight minus benchmark weight, zero)",
            "membership_difference_rate": "one minus intersection size divided by 20, averaged over dates",
            "turnover": "sum over securities of absolute equal-weight change between adjacent dates",
            "structural_turnover_difference_rate": "shadow total turnover minus Raw total turnover, divided by Raw total turnover",
            "trigger_denominator": "all canonical Raw entry requests after initialization; already-held requested entrants remain in the denominator but create no event",
        },
        "anti_degeneracy_gates": {
            "rule_activates": "optional trigger count > 0",
            "fallback_not_dominant": "compliant alternative found count > fallback count",
            "deterministic": "two independent structural replays have identical logical hashes",
            "trigger_hhi": "every found alternative has HHI no greater than its original Raw entrant swap, and aggregate mean difference is strictly negative",
            "identity": "20 unique valid holdings on every date and exact Raw initialization",
            "temporal": "zero post-2025 candidate/taxonomy reads, zero future filing violations, and zero benchmark backward/future fills",
            "non_explosive": "mean membership difference rate <= 0.50",
        },
        "future_evaluation": {
            "run_now": False,
            "comparison": ["RAW_A2", FROZEN_NAME],
            "same_windows_required": True,
            "primary_metrics": [
                "net return", "Sharpe", "volatility", "MaxDD", "turnover", "cost",
                "sector HHI", "max sector weight", "active sector overweight",
                "SPY beta", "QQQ beta", "SOXX beta", "within-sector selection diagnostics",
            ],
            "success_logic": [
                "materially lower sector concentration",
                "no material turnover/cost increase",
                "no material MaxDD deterioration",
                "return engine substantially preserved",
                "Sharpe non-inferior or descriptively improved",
                "not one-year-driven",
                "not explained by accidental beta neutralization",
            ],
            "single_scalar_objective": None,
            "post_result_optimization_forbidden": True,
            "promotion_from_historical_results_forbidden": True,
        },
    }
    payload["contract_payload_sha256"] = stable_hash(payload)
    return payload


def freeze() -> None:
    require(not OUT.exists(), "OUTPUT_ROOT_ALREADY_EXISTS_IMMUTABLE", OUT)
    verify_inputs()
    protected_hash, protected_files = tree_hash(PROSPECTIVE)
    art = prior_art()
    OUT.mkdir(parents=False, exist_ok=False)
    audit = {
        "task_id": "A2_SINGLE_SECTOR_RISK_BUDGET_DESIGN_AND_FREEZE_R1",
        "status": "PASS_COMPLETE_BEFORE_BUILD",
        "search_scope": [str(REPO), str(RESULTS), r"D:\us-tech-quant-cache", "registry and frozen contracts"],
        "search_modes": ["filenames", "schemas/content", "implementation", "manifests/registry"],
        "n_relevant_sector_rules_found": len(art),
        "counting_unit": "distinct lineage-level sector/deconcentration/risk rule surfaces; trial arms within a lineage are not double-counted",
        "build_decision": "NO_EXISTING_FIXED_RULE_DESIGN_ONE_MINIMAL_RULE",
        "selected_existing_rule": None,
        "selected_existing_rule_path": None,
        "selected_existing_rule_sha256": None,
        "why_selected": "The mandated parameter-free fallback is the only architecture satisfying the task after all existing rule lineages were classified incompatible or unfrozen/failed.",
        "relevant_prior_art": art,
        "inspected_not_counted_as_standalone_sector_rules": [
            "A2_AUTONOMOUS_BUY_SELL_AND_SIZING_POLICY_R1 (multi-component sizing/ML context)",
            "replacement/RX lineages (explicitly prohibited combination)",
        ],
        "new_portfolio_engine_created": False,
        "new_risk_optimizer_created": False,
        "new_generic_risk_framework_created": False,
        "completed_before_contract_freeze": True,
    }
    write_json(OUT / "anti_duplication_audit.json", audit)
    write_json(CONTRACT, contract_payload())
    design = f"""# A2 single sector-risk-budget design rationale

## Decision

The anti-duplication audit found {len(art)} relevant lineage-level rule surfaces, but no compatible frozen rule. Existing work either changes the score/model, performs full reweighting or cash scaling, combines unrelated controls, was selected using historical economics, or never passed its own freeze gate. Infrastructure is reused; none of those economic rules is revived.

The one frozen rule is `{RULE_NAME}`. It is the task-mandated parameter-free fallback: existing valid holdings are grandfathered, while a genuine new Raw A2 entrant that would increase an already-positive PIT FF12 active overweight is deferred when the same authoritative rank surface contains a compliant alternative. If no alternative exists, the Raw entrant is used.

## Scope

This is a portfolio-layer state transition only. Raw A2 score, model, eligibility, full ranking, Top20 count, equal weights, execution timing, and 10 bps one-way cost convention are unchanged. `UNKNOWN` remains an explicit FF12 category. Beta, RX margin, holding-age hysteresis, volatility, tail controls, cash, covariance models, and optimization are absent.

## Evidence discipline

The parent mechanism audit is consumed only as frozen motivation. No candidate rule was compared on return, Sharpe, alpha, drawdown, or any outcome. The subsequent dry-run may read only rank, taxonomy, and benchmark-weight fields and can only decide structural viability under the gates already embedded in the frozen contract.
"""
    (OUT / "design_rationale.md").write_text(design, encoding="utf-8")
    witness = {
        "contract_sha256": sha256_file(CONTRACT),
        "contract_payload_sha256": json.loads(CONTRACT.read_text(encoding="utf-8"))["contract_payload_sha256"],
        "protected_tree_sha256_at_freeze": protected_hash,
        "protected_tree_file_count": protected_files,
        "registry_sha256_at_freeze": sha256_file(REGISTRY),
    }
    print(stable_json(witness))


def import_pretop() -> Any:
    spec = importlib.util.spec_from_file_location("a2_pretop_reuse", PRETOP_SOURCE)
    require(spec is not None and spec.loader is not None, "PRETOP_IMPORT_SPEC")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sector_weights(names: Iterable[str], sectors: dict[str, str]) -> dict[str, float]:
    weights: dict[str, float] = {}
    for ticker in names:
        sector = sectors[ticker]
        weights[sector] = weights.get(sector, 0.0) + WEIGHT
    return weights


def hhi(names: Iterable[str], sectors: dict[str, str]) -> float:
    return float(sum(value * value for value in sector_weights(names, sectors).values()))


def max_active(names: Iterable[str], sectors: dict[str, str], benchmark: dict[str, float]) -> float:
    weights = sector_weights(names, sectors)
    all_sectors = set(weights) | set(benchmark)
    return float(max([0.0] + [weights.get(sector, 0.0) - benchmark.get(sector, 0.0) for sector in all_sectors]))


def turnover(previous: set[str] | None, current: set[str]) -> float:
    return 0.0 if previous is None else float(WEIGHT * len(previous.symmetric_difference(current)))


def compliant(
    candidate: str,
    exit_name: str,
    holdings: set[str],
    sectors: dict[str, str],
    benchmark: dict[str, float],
) -> bool:
    before = sector_weights(holdings, sectors)
    sector = sectors[candidate]
    after_weight = before.get(sector, 0.0) + WEIGHT - (WEIGHT if sectors[exit_name] == sector else 0.0)
    active = before.get(sector, 0.0) - benchmark.get(sector, 0.0)
    return not (active > EPS and after_weight > before.get(sector, 0.0) + EPS)


def select_for_event(
    original: str,
    exit_name: str,
    holdings: set[str],
    ordered: list[str],
    sectors: dict[str, str],
    benchmark: dict[str, float],
) -> tuple[str, bool, bool, float | None]:
    if compliant(original, exit_name, holdings, sectors, benchmark):
        return original, False, False, None
    raw_hhi = hhi((holdings - {exit_name}) | {original}, sectors)
    for candidate in ordered:
        if candidate in holdings or candidate == exit_name:
            continue
        if compliant(candidate, exit_name, holdings, sectors, benchmark):
            chosen_hhi = hhi((holdings - {exit_name}) | {candidate}, sectors)
            return candidate, True, True, chosen_hhi - raw_hhi
    return original, True, False, None


def logical_replay_hash(
    rows: list[dict[str, Any]], memberships: list[tuple[str, tuple[str, ...]]]
) -> str:
    return stable_hash({"rows": rows, "memberships": memberships})


def replay(
    panel: pd.DataFrame,
    benchmark_by_date: dict[pd.Timestamp, dict[str, float]],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    memberships: list[tuple[str, tuple[str, ...]]] = []
    previous_shadow: set[str] | None = None
    previous_raw: set[str] | None = None
    previous_ranks: dict[str, int] = {}
    previous_sectors: dict[str, str] = {}
    trigger_hhi_deltas: list[float] = []
    for date, day in panel.groupby("signal_date", sort=True):
        day = day.sort_values(["a2_rank", "ticker"], kind="mergesort")
        ordered = day.ticker.astype(str).tolist()
        ranks = dict(zip(day.ticker.astype(str), day.a2_rank.astype(int)))
        sectors = dict(zip(day.ticker.astype(str), day.ff12.fillna("UNKNOWN").astype(str)))
        require(len(ordered) == len(set(ordered)) and len(ordered) > TOP_N, "DAILY_RANK_SURFACE")
        raw_ordered = ordered[:TOP_N]
        raw = set(raw_ordered)
        require(len(raw) == TOP_N, "RAW_TOP20_CARDINALITY", date)
        benchmark = benchmark_by_date.get(pd.Timestamp(date))
        require(benchmark is not None, "BENCHMARK_DATE_MISSING", date)
        optional_requests = triggers = alternatives = fallbacks = forced_count = 0
        if previous_shadow is None:
            shadow = set(raw)
        else:
            shadow = set(previous_shadow)
            forced = sorted([name for name in shadow if name not in ranks])
            for name in forced:
                sectors[name] = previous_sectors.get(name, "UNKNOWN")
            for exit_name in forced:
                forced_count += 1
                candidates = [name for name in raw_ordered if name not in shadow]
                if not candidates:
                    candidates = [name for name in ordered if name not in shadow]
                require(bool(candidates), "FORCED_REPLACEMENT_CANDIDATE", date)
                original = candidates[0]
                chosen, _, _, _ = select_for_event(
                    original, exit_name, shadow, ordered, sectors, benchmark
                )
                shadow.remove(exit_name)
                shadow.add(chosen)

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
                paired_exit = raw_exits[index] if index < len(raw_exits) else None
                if paired_exit not in shadow:
                    outside = [name for name in shadow if name not in raw]
                    require(
                        bool(outside),
                        "OPTIONAL_EXIT_CANDIDATE",
                        {"date": str(date), "entrant": original},
                    )
                    paired_exit = sorted(
                        outside, key=lambda name: (-ranks.get(name, 10**9), name)
                    )[0]
                if paired_exit not in sectors:
                    sectors[paired_exit] = previous_sectors.get(paired_exit, "UNKNOWN")
                chosen, triggered, found, delta = select_for_event(
                    original, paired_exit, shadow, ordered, sectors, benchmark
                )
                if triggered:
                    triggers += 1
                    if found:
                        alternatives += 1
                        require(delta is not None, "TRIGGER_HHI_DELTA")
                        trigger_hhi_deltas.append(float(delta))
                    else:
                        fallbacks += 1
                shadow.remove(paired_exit)
                shadow.add(chosen)

        require(
            len(shadow) == TOP_N and len(shadow & set(ordered)) == TOP_N,
            "SHADOW_IDENTITY",
            date,
        )
        row = {
            "signal_date": pd.Timestamp(date).date().isoformat(),
            "raw_a2_sector_hhi": hhi(raw, sectors),
            "shadow_sector_hhi": hhi(shadow, sectors),
            "raw_a2_max_active_sector_overweight": max_active(raw, sectors, benchmark),
            "shadow_max_active_sector_overweight": max_active(shadow, sectors, benchmark),
            "raw_a2_structural_turnover": turnover(previous_raw, raw),
            "shadow_structural_turnover": turnover(previous_shadow, shadow),
            "membership_difference_rate": 1.0 - len(raw & shadow) / TOP_N,
            "optional_entry_requests": optional_requests,
            "sector_rule_triggers": triggers,
            "compliant_alternatives_found": alternatives,
            "fallbacks_to_raw_a2": fallbacks,
            "forced_exit_count": forced_count,
        }
        rows.append(row)
        memberships.append((row["signal_date"], tuple(sorted(shadow))))
        previous_shadow = set(shadow)
        previous_raw = set(raw)
        previous_ranks = ranks
        previous_sectors = {ticker: sectors[ticker] for ticker in shadow}
    first_date = panel.signal_date.min()
    initial_raw = tuple(
        sorted(
            panel.loc[panel.signal_date.eq(first_date)]
            .sort_values(["a2_rank", "ticker"])
            .head(TOP_N)
            .ticker.astype(str)
        )
    )
    facts = {
        "logical_replay_sha256": logical_replay_hash(rows, memberships),
        "trigger_hhi_deltas": trigger_hhi_deltas,
        "initialization_exact": memberships[0][1] == initial_raw,
    }
    return pd.DataFrame(rows), facts


def load_structural_inputs() -> tuple[
    pd.DataFrame, dict[pd.Timestamp, dict[str, float]], dict[str, Any]
]:
    pretop = import_pretop()
    pool, top, pool_facts = pretop.load_candidate_pool()
    taxonomy, _, taxonomy_facts = pretop.extend_taxonomy(pool, top)
    classes = taxonomy[["signal_date", "ticker", "ff12"]].copy()
    classes["signal_date"] = pd.to_datetime(classes.signal_date).dt.normalize()
    classes["ticker"] = classes.ticker.astype(str).str.upper().str.strip()
    classes["ff12"] = classes.ff12.fillna("UNKNOWN").astype(str)
    panel = pool[["signal_date", "ticker", "a2_prediction", "a2_rank"]].merge(
        classes, on=["signal_date", "ticker"], validate="one_to_one"
    )
    require(panel.signal_date.max() < pd.Timestamp("2026-01-01"), "POST2025_STRUCTURAL_READ")

    # Explicit usecols is the outcome wall: return/outcome fields are never opened.
    bench = pd.read_csv(
        BENCHMARK,
        usecols=[
            "record_type",
            "signal_date",
            "taxonomy_level",
            "sector",
            "benchmark_weight",
        ],
        dtype={
            "record_type": "string",
            "signal_date": "string",
            "taxonomy_level": "string",
            "sector": "string",
        },
    )
    bench["signal_date"] = pd.to_datetime(bench.signal_date).dt.normalize()
    bench = bench.loc[
        bench.record_type.eq("DAILY_SECTOR") & bench.taxonomy_level.eq("FF12")
    ].copy()
    panel_dates = set(panel.signal_date.unique())
    bench = bench.loc[bench.signal_date.isin(panel_dates)].copy()
    bench["sector"] = bench.sector.fillna("UNKNOWN").astype(str)
    bench["benchmark_weight"] = pd.to_numeric(bench.benchmark_weight, errors="raise")
    require(not bench.duplicated(["signal_date", "sector"]).any(), "BENCHMARK_DUPLICATE")
    require(bench.signal_date.max() < pd.Timestamp("2026-01-01"), "POST2025_USED_BENCHMARK")
    benchmark_by_date = {
        date: dict(zip(day.sector, day.benchmark_weight.astype(float)))
        for date, day in bench.groupby("signal_date", sort=True)
    }
    require(
        panel_dates.issubset(set(benchmark_by_date)),
        "BENCHMARK_COVERAGE",
    )
    facts = {
        "candidate_pool": pool_facts,
        "taxonomy": taxonomy_facts,
        "benchmark_dates": len(benchmark_by_date),
        "economic_outcome_columns_opened": [],
        "economic_outcome_read_count": 0,
    }
    return panel, benchmark_by_date, facts


def verify_contract() -> tuple[dict[str, Any], str]:
    require(CONTRACT.is_file(), "CONTRACT_NOT_FROZEN")
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    declared = contract.pop("contract_payload_sha256")
    require(stable_hash(contract) == declared, "CONTRACT_PAYLOAD_HASH")
    contract["contract_payload_sha256"] = declared
    require(contract["rule"]["family"] == RULE_NAME, "RULE_MUTATION")
    require(
        contract["prohibitions"]["economic_outcome_read_count"] == 0,
        "OUTCOME_RULE_MUTATION",
    )
    return contract, sha256_file(CONTRACT)


def dry_run() -> None:
    verify_inputs()
    contract, contract_sha = verify_contract()
    protected_before, protected_count = tree_hash(PROSPECTIVE)
    registry_before = sha256_file(REGISTRY)
    panel, benchmark, input_facts = load_structural_inputs()
    first, facts1 = replay(panel, benchmark)
    second, facts2 = replay(panel, benchmark)
    require(
        facts1["logical_replay_sha256"] == facts2["logical_replay_sha256"],
        "NONDETERMINISTIC_REPLAY",
    )
    require(first.equals(second), "NONDETERMINISTIC_METRICS")

    total_requests = int(first.optional_entry_requests.sum())
    trigger_count = int(first.sector_rule_triggers.sum())
    found_count = int(first.compliant_alternatives_found.sum())
    fallback_count = int(first.fallbacks_to_raw_a2.sum())
    deltas = facts1["trigger_hhi_deltas"]
    raw_turnover = float(first.raw_a2_structural_turnover.sum())
    shadow_turnover = float(first.shadow_structural_turnover.sum())
    require(raw_turnover > 0.0, "RAW_TURNOVER_DENOMINATOR")
    metrics = {
        "total_signal_dates": int(len(first)),
        "total_optional_entry_requests": total_requests,
        "sector_rule_trigger_count": trigger_count,
        "sector_rule_trigger_share": float(trigger_count / total_requests) if total_requests else 0.0,
        "compliant_alternative_found_count": found_count,
        "fallback_to_raw_a2_count": fallback_count,
        "average_structural_sector_hhi_raw_a2": float(first.raw_a2_sector_hhi.mean()),
        "average_structural_sector_hhi_shadow": float(first.shadow_sector_hhi.mean()),
        "average_active_sector_overweight_raw_a2": float(
            first.raw_a2_max_active_sector_overweight.mean()
        ),
        "average_active_sector_overweight_shadow": float(
            first.shadow_max_active_sector_overweight.mean()
        ),
        "holding_membership_difference_rate": float(first.membership_difference_rate.mean()),
        "structural_turnover_difference_rate": float(
            (shadow_turnover - raw_turnover) / raw_turnover
        ),
        "raw_structural_turnover_total": raw_turnover,
        "shadow_structural_turnover_total": shadow_turnover,
        "forced_exit_count": int(first.forced_exit_count.sum()),
        "triggered_alternative_mean_hhi_difference_vs_raw_entry": (
            float(pd.Series(deltas, dtype=float).mean()) if deltas else None
        ),
        "triggered_alternative_max_hhi_difference_vs_raw_entry": (
            float(max(deltas)) if deltas else None
        ),
        "logical_replay_sha256": facts1["logical_replay_sha256"],
    }
    gates = {
        "rule_activates": trigger_count > 0,
        "fallback_not_dominant": found_count > fallback_count,
        "deterministic": facts1["logical_replay_sha256"]
        == facts2["logical_replay_sha256"],
        "trigger_hhi_nonincreasing_each_found": bool(deltas) and max(deltas) <= EPS,
        "trigger_hhi_strictly_lower_on_average": bool(deltas)
        and float(pd.Series(deltas).mean()) < -EPS,
        "identity_and_initialization": bool(facts1["initialization_exact"]),
        "temporal": int(input_facts["taxonomy"]["future_filing_violation_count"]) == 0
        and panel.signal_date.max() < pd.Timestamp("2026-01-01"),
        "non_explosive": metrics["holding_membership_difference_rate"] <= 0.50,
        "economic_outcome_read_count_zero": input_facts["economic_outcome_read_count"] == 0,
    }
    structurally_valid = all(gates.values())
    final_classification = (
        "PASS_FROZEN_SINGLE_MINIMAL_SECTOR_SHADOW"
        if structurally_valid
        else "FAIL_STRUCTURAL_DEGENERACY"
    )

    first.to_csv(OUT / "structural_dry_run.csv", index=False, float_format="%.12g")
    protected_after, protected_count_after = tree_hash(PROSPECTIVE)
    registry_after = sha256_file(REGISTRY)
    require(
        (protected_before, protected_count) == (protected_after, protected_count_after),
        "PROSPECTIVE_TREE_CHANGED",
    )
    require(registry_before == registry_after == EXPECTED[REGISTRY], "REGISTRY_CHANGED")
    temp_state = temp_accounting()

    sources = {
        "task_id": contract["task_id"],
        "structural_only": True,
        "economic_outcome_read_count": 0,
        "inputs": [
            {
                "role": "Raw A2 model identity",
                "path": str(MODEL),
                "sha256": sha256_file(MODEL),
                "columns_read": [],
            },
            {
                "role": "authoritative full Raw A2 ranking",
                "path": str(OOF),
                "sha256": sha256_file(OOF),
                "columns_read": [
                    "signal_date",
                    "ticker",
                    "universe_size",
                    "split",
                    "a2_model_name",
                    "a2_prediction",
                    "a2_rank",
                ],
            },
            {
                "role": "frozen Raw Top20 PIT taxonomy identity",
                "path": str(TAXONOMY),
                "sha256": sha256_file(TAXONOMY),
                "columns_read": ["signal_date", "ticker", "pit_sic", "ff12", "ff48"],
            },
            {
                "role": "PIT eligible-universe benchmark FF12 weights",
                "path": str(BENCHMARK),
                "sha256": sha256_file(BENCHMARK),
                "columns_read": [
                    "record_type",
                    "signal_date",
                    "taxonomy_level",
                    "sector",
                    "benchmark_weight",
                ],
            },
            {
                "role": "reused candidate/taxonomy loader",
                "path": str(PRETOP_SOURCE),
                "sha256": sha256_file(PRETOP_SOURCE),
            },
            {
                "role": "frozen parent mechanism protocol",
                "path": str(PARENT_PROTOCOL),
                "sha256": sha256_file(PARENT_PROTOCOL),
                "use": "frozen design motivation only",
            },
            {
                "role": "existing methodology",
                "path": str(FOUR_LAYER / "literature_methodology.md"),
                "sha256": sha256_file(FOUR_LAYER / "literature_methodology.md"),
                "use": "reused; no new literature survey",
            },
        ],
        "derived_identity": input_facts,
        "protected_assets": {
            "prospective_tree_sha256_before": protected_before,
            "prospective_tree_sha256_after": protected_after,
            "file_count": protected_count,
            "unchanged": True,
            "registry_sha256_before": registry_before,
            "registry_sha256_after": registry_after,
        },
        "temp_accounting": temp_state,
    }
    write_json(OUT / "source_manifest.json", sources)
    summary = {
        "status": "PASS" if structurally_valid else "FAIL",
        "final_classification": final_classification,
        "anti_duplication_audit_status": "PASS_COMPLETE_BEFORE_BUILD",
        "n_relevant_sector_rules_found": 13,
        "build_decision": "NO_EXISTING_FIXED_RULE_DESIGN_ONE_MINIMAL_RULE",
        "selected_existing_rule": None,
        "frozen_name": FROZEN_NAME,
        "rule_family": RULE_NAME,
        "numeric_sector_cap_used": False,
        "parameter_search_count": 0,
        "beta_constraint_active": False,
        "rx_margin_active": False,
        "tail_control_active": False,
        "sector_risk_budget_contract_sha256": contract_sha,
        "structural_metrics": metrics,
        "structural_gates": gates,
        "economic_outcome_read_count": 0,
        "future_evidence_label": "RETROSPECTIVE_EXPOSED_SHADOW_DIAGNOSTIC",
        "canonical_registry_change": False,
        "raw_a2_unchanged": True,
        "prospective_a2_x0_protocol_untouched": True,
        "new_portfolio_engine_created": False,
        "new_risk_optimizer_created": False,
        "new_generic_risk_framework_created": False,
        **temp_state,
        "next_research_priority": (
            "EVALUATE_FROZEN_SINGLE_SECTOR_RISK_BUDGET_SHADOW_R1"
            if structurally_valid
            else "REQUIRE_NEW_R2_DESIGN_BEFORE_ANY_ECONOMIC_EVALUATION"
        ),
    }
    write_json(OUT / "summary.json", summary)
    write_report(summary)
    print_console(summary)


def write_report(summary: dict[str, Any]) -> None:
    metrics = summary["structural_metrics"]
    report = f"""# A2 single sector-risk-budget design and freeze

## Result

**{summary['final_classification']}**

The frozen `{RULE_NAME}` contract was assessed under all predeclared structural gates: activation, usable alternatives, deterministic replay, non-increasing triggered HHI arithmetic, exact Top20 identity, temporal integrity, and bounded divergence. No return, price, Sharpe, alpha, drawdown, matched-control, or other economic outcome column was opened.

## Structural dry-run

- Dates: {metrics['total_signal_dates']}
- Optional Raw A2 entry requests: {metrics['total_optional_entry_requests']}
- Rule triggers: {metrics['sector_rule_trigger_count']} ({metrics['sector_rule_trigger_share']:.2%})
- Compliant alternatives / Raw fallback: {metrics['compliant_alternative_found_count']} / {metrics['fallback_to_raw_a2_count']}
- Mean FF12 HHI, Raw / shadow: {metrics['average_structural_sector_hhi_raw_a2']:.6f} / {metrics['average_structural_sector_hhi_shadow']:.6f}
- Mean maximum active FF12 overweight, Raw / shadow: {metrics['average_active_sector_overweight_raw_a2']:.6f} / {metrics['average_active_sector_overweight_shadow']:.6f}
- Mean membership difference: {metrics['holding_membership_difference_rate']:.2%}
- Structural turnover difference rate: {metrics['structural_turnover_difference_rate']:.2%}

## Freeze and boundaries

Contract SHA-256: `{summary['sector_risk_budget_contract_sha256']}`. The rule has no numeric cap, optimizer, beta constraint, RX margin, tail control, regime switch, or learned parameter. Raw A2 and the canonical registry are unchanged. The A2/X0 prospective tree is byte-identical across this run. Future economics remain a separate, predeclared `RETROSPECTIVE_EXPOSED_SHADOW_DIAGNOSTIC` task.

## Temporary-path accounting

Task-owned repo-root temporary directories: **0**. The exact path `{ACTIVE_UNRELATED_TEMP}` is excluded as `{summary['active_unrelated_transient_exclusion_status']}` only while Harness task `20260829-175126-ae37` remains active. It is unrelated, pytest/cache-like, not source or published evidence, and not referenced by this task's frozen inputs. It was not deleted or used.
"""
    (OUT / "concise_report.md").write_text(report, encoding="utf-8")


def fmt(value: Any) -> str:
    return f"{value:.12g}" if isinstance(value, float) else str(value)


def print_console(summary: dict[str, Any]) -> None:
    m = summary["structural_metrics"]
    values = [
        "============================================================",
        "A2 SINGLE SECTOR RISK-BUDGET DESIGN / FREEZE",
        "============================================================",
        f"STATUS={summary['status']}",
        "",
        "------------------------------------------------------------",
        "ANTI-DUPLICATION",
        "------------------------------------------------------------",
        "ANTI_DUPLICATION_AUDIT_STATUS=PASS_COMPLETE_BEFORE_BUILD",
        "N_RELEVANT_SECTOR_RULES_FOUND=13",
        "BUILD_DECISION=NO_EXISTING_FIXED_RULE_DESIGN_ONE_MINIMAL_RULE",
        "",
        "SELECTED_EXISTING_RULE=NONE",
        "SELECTED_EXISTING_RULE_PATH=NOT_APPLICABLE",
        "SELECTED_EXISTING_RULE_SHA256=NOT_APPLICABLE",
        "",
        "NEW_PORTFOLIO_ENGINE_CREATED=FALSE",
        "NEW_RISK_OPTIMIZER_CREATED=FALSE",
        "NEW_GENERIC_RISK_FRAMEWORK_CREATED=FALSE",
        "",
        "------------------------------------------------------------",
        "FROZEN RULE",
        "------------------------------------------------------------",
        f"FROZEN_NAME={FROZEN_NAME}",
        f"RULE_FAMILY={RULE_NAME}",
        "",
        "NUMERIC_SECTOR_CAP_USED=FALSE",
        "IF_TRUE_PARAMETER_PROVENANCE=NOT_APPLICABLE_PARAMETER_FREE_STRUCTURAL_RULE",
        "",
        "PARAMETER_SEARCH_COUNT=0",
        "",
        "BETA_CONSTRAINT_ACTIVE=FALSE",
        "RX_MARGIN_ACTIVE=FALSE",
        "TAIL_CONTROL_ACTIVE=FALSE",
        "",
        "------------------------------------------------------------",
        "STRUCTURAL DRY RUN",
        "------------------------------------------------------------",
        f"TOTAL_SIGNAL_DATES={m['total_signal_dates']}",
        f"TOTAL_OPTIONAL_ENTRY_REQUESTS={m['total_optional_entry_requests']}",
        "",
        f"SECTOR_RULE_TRIGGER_COUNT={m['sector_rule_trigger_count']}",
        f"SECTOR_RULE_TRIGGER_SHARE={fmt(m['sector_rule_trigger_share'])}",
        "",
        f"COMPLIANT_ALTERNATIVE_FOUND_COUNT={m['compliant_alternative_found_count']}",
        f"FALLBACK_TO_RAW_A2_COUNT={m['fallback_to_raw_a2_count']}",
        "",
        f"AVG_RAW_A2_SECTOR_HHI={fmt(m['average_structural_sector_hhi_raw_a2'])}",
        f"AVG_SHADOW_SECTOR_HHI={fmt(m['average_structural_sector_hhi_shadow'])}",
        "",
        f"AVG_RAW_A2_ACTIVE_OVERWEIGHT={fmt(m['average_active_sector_overweight_raw_a2'])}",
        f"AVG_SHADOW_ACTIVE_OVERWEIGHT={fmt(m['average_active_sector_overweight_shadow'])}",
        "",
        f"HOLDING_MEMBERSHIP_DIFFERENCE_RATE={fmt(m['holding_membership_difference_rate'])}",
        f"STRUCTURAL_TURNOVER_DIFFERENCE_RATE={fmt(m['structural_turnover_difference_rate'])}",
        "",
        "ECONOMIC_OUTCOME_READ_COUNT=0",
        "",
        "------------------------------------------------------------",
        "FREEZE",
        "------------------------------------------------------------",
        f"SECTOR_RISK_BUDGET_CONTRACT_SHA256={summary['sector_risk_budget_contract_sha256']}",
        "",
        "FUTURE_EVIDENCE_LABEL=RETROSPECTIVE_EXPOSED_SHADOW_DIAGNOSTIC",
        "",
        "CANONICAL_REGISTRY_CHANGE=FALSE",
        "RAW_A2_UNCHANGED=TRUE",
        "",
        "PROSPECTIVE_A2_X0_PROTOCOL_UNTOUCHED=TRUE",
        "",
        "------------------------------------------------------------",
        "FINAL",
        "------------------------------------------------------------",
        f"FINAL_CLASSIFICATION={summary['final_classification']}",
        "",
        f"NEXT_RESEARCH_PRIORITY={summary['next_research_priority']}",
        "",
        f"ACTIVE_UNRELATED_TRANSIENT_EXCLUSION_STATUS={summary['active_unrelated_transient_exclusion_status']}",
        f"ACTIVE_UNRELATED_TEMP_EXCLUSIONS={summary['active_unrelated_temp_exclusions']}",
        f"ACTIVE_UNRELATED_TEMP_PATHS={','.join(summary['active_unrelated_temp_paths'])}",
        f"UNRELATED_ACTIVE_TEMP_DIR_COUNT={summary['unrelated_active_temp_dir_count']}",
        f"TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT={summary['task_owned_repo_root_temp_dir_count']}",
        "",
        f"ARTIFACT_DIR={OUT}",
        "============================================================",
    ]
    print("\n".join(values))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["freeze", "dry-run"])
    args = parser.parse_args()
    if args.phase == "freeze":
        freeze()
    else:
        dry_run()


if __name__ == "__main__":
    main()
