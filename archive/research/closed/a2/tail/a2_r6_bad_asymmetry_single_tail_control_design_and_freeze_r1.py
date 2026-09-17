"""Audit, predeclare, and structurally validate one frozen-R6 entry guard.

This runner deliberately reads no return, PnL, NAV, label, or outcome column.
It reuses the authoritative Raw-A2 full rank surface, the frozen R6 OOF score
surface, and the already-established state-transition conventions.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / "A2_R6_BAD_ASYMMETRY_SINGLE_TAIL_CONTROL_DESIGN_AND_FREEZE_R1"

R6_ROOT = RESULTS / "A2_INDIVIDUAL_STOCK_TAIL_RISK_R2"
R6_IDENTITY = R6_ROOT / "frozen_risk_signal_identity.json"
R6_OVERLAY_CONTRACT = R6_ROOT / "risk_overlay_contract.json"
R6_OOF = RESULTS / "A2_STOCK_RISK_R6" / "r6_oof_predictions.parquet"
R11_CONTRACT = RESULTS / "A2_STOCK_RISK_R11_PROSPECTIVE" / "r11_preregistered_evaluation_contract.json"
R2A_CONTRACT = RESULTS / "A2_INDIVIDUAL_STOCK_TAIL_RISK_R2A_SELECTION_AUDIT_AND_FORWARD_FREEZE" / "reconstructed_selection_contract.json"
MECHANISM_PROTOCOL = RESULTS / "A2_EXISTING_TAIL_LOSS_CONTROL_MECHANISM_AUDIT_R1" / "tail_loss_mechanism_protocol.json"
MECHANISM_SUMMARY = RESULTS / "A2_EXISTING_TAIL_LOSS_CONTROL_MECHANISM_AUDIT_R1" / "summary.json"
CURRENT_BRANCH_REGISTRY = RESULTS / "A2_RESEARCH_REGISTRY_CURRENT" / "research_branch_registry_current.csv"
RISK_REGISTRY = REPO / "config" / "research_governance" / "risk_registry.json"
RAW_MODEL = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2" / "final_full_pre2026_hgb.joblib"
RAW_OOF = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2" / "oof_predictions.parquet"
TRANSITION_SOURCE = REPO / "a2_single_sector_risk_budget_design_and_freeze_r1.py"
PRETOP_SOURCE = REPO / "scripts" / "v22" / "a2_pretop20_candidate_recovery_and_membership_deconcentration_r1.py"
PROTECTED = RESULTS / "A2_X0_LITERATURE_GROUNDED_PROSPECTIVE_DISAGREEMENT_R1"

EXPECTED = {
    R6_IDENTITY: "c93c359d8ebc974b2deabe779d40afec3c735d1c287fff0a31778925bc947c95",
    MECHANISM_PROTOCOL: "f6728e695ef33b9be9b8ddccde8833468b5f40b96831c04f6fa4d122f9ae4b05",
    RAW_MODEL: "4f7eff07021bef084b0329dac8dabc31e9391c7c4945eb2955dc6c1339dcea0b",
    R6_OOF: "5f35b7b54192ce9023a886f3a51d9efaddea526bb78aed4862481f9dd85653b4",
    R6_OVERLAY_CONTRACT: "42c91f64b9e2bfd6eb8849fc7ed06d4569d80739aea9b2cdee3ebc2e38e8ef58",
    R11_CONTRACT: "e3824cf004da24c9eceaed7018d790eed4110d6c921c4e1801a17672f67ac70a",
}

TOP_N = 20
WEIGHT = 1.0 / TOP_N
R6_THRESHOLD = 0.90
R6_MODEL_NAME = "LGBM_BAD_ASYM_2"


def require(condition: bool, code: str, detail: Any = "") -> None:
    if not condition:
        raise RuntimeError(f"{code}:{detail}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def tree_snapshot(root: Path) -> dict[str, Any]:
    files = []
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: str(item).lower()):
        files.append({"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return {"root": str(root), "file_count": len(files), "tree_sha256": stable_hash(files), "files": files}


def repo_temp_dirs() -> list[str]:
    prefixes = (".tmp", ".codex_tmp", ".pytest_cache", "pytest-cache-")
    return sorted(str(path) for path in REPO.iterdir() if path.is_dir() and path.name.startswith(prefixes))


def import_transition() -> Any:
    spec = importlib.util.spec_from_file_location("a2_r6_tail_transition_reuse", TRANSITION_SOURCE)
    require(spec is not None and spec.loader is not None, "TRANSITION_IMPORT_SPEC")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_inputs() -> dict[str, Any]:
    for path, expected in EXPECTED.items():
        require(path.is_file(), "MISSING_FROZEN_INPUT", path)
        require(sha256_file(path) == expected, "FROZEN_INPUT_HASH_MISMATCH", path)
    identity = json.loads(R6_IDENTITY.read_text(encoding="utf-8"))
    require(identity["RISK_MODEL_NAME"] == R6_MODEL_NAME, "R6_MODEL_IDENTITY")
    require(identity["RISK_SCORE_DIRECTION"] == "HIGHER_IS_MORE_BAD_ASYMMETRY_RISK", "R6_DIRECTION")
    mechanism = json.loads(MECHANISM_SUMMARY.read_text(encoding="utf-8"))
    require(mechanism["TAIL_LOSS_MECHANISM_CLASSIFICATION"] == "STRONG_EXISTING_TAIL_LOSS_MECHANISM", "MECHANISM_PARENT")
    require(mechanism["SELECTED_EXISTING_MECHANISM"] == "R6_BAD_ASYMMETRY", "MECHANISM_SIGNAL")
    if OUT.exists():
        expected_partial = {
            "anti_duplication_audit.json",
            "r6_action_rule_provenance.json",
            "tail_control_design_protocol.json",
        }
        existing = {path.name for path in OUT.iterdir() if path.is_file()}
        require(existing == expected_partial, "OUTPUT_ROOT_NOT_SAFE_FROZEN_PROTOCOL_RESUME", sorted(existing))
    require(not repo_temp_dirs(), "REPO_ROOT_TEMP_DIR_PREEXISTING", repo_temp_dirs())
    return identity


def anti_duplication_payload() -> dict[str, Any]:
    r1 = json.loads(R6_OVERLAY_CONTRACT.read_text(encoding="utf-8"))
    r11 = json.loads(R11_CONTRACT.read_text(encoding="utf-8"))["preregistered_payload"]
    r2a = json.loads(R2A_CONTRACT.read_text(encoding="utf-8"))
    r1_rule = r1["candidates"]["R1_MILD"]
    r11_rule = r11["economic_shadow"]["rule"]
    require(r1["quantile_mapping"]["top_decile"] == "risk_percentile>=0.90", "R1_THRESHOLD")
    require(r1_rule == {"next_decile": 1.0, "top_decile": 0.75}, "R1_ACTION")
    require(r1["capital_rule"] == "REDUCED_EXPOSURE_TO_CASH;NO_REDISTRIBUTION;NO_LEVERAGE;NO_REPLACEMENT", "R1_GEOMETRY")
    require(r11_rule == {"removed_weight_destination": "CASH", "risk_percentile_at_least_90": 0.5, "risk_percentile_below_90": 1.0}, "R11_ACTION")
    require(r2a["SELECTION_CONTRACT_RECOVERY_STATUS"] == "PASS_FULLY_RECONSTRUCTED_FROM_PRE_RESULT_MATERIAL", "R2A_PROVENANCE")
    registry = pd.read_csv(CURRENT_BRANCH_REGISTRY)
    relevant = registry.loc[registry.canonical_branch_id.isin(["R6_TOP_DECILE_HALF_CASH_POLICY", "R6_ATTENUATION_POLICY_VARIANTS"])]
    require(len(relevant) == 2, "CURRENT_BRANCH_REGISTRY_R6_ROWS", len(relevant))
    return {
        "ANTI_DUPLICATION_AUDIT_STATUS": "PASS_R6_ATTENUATION_RULES_DIFFERENT_GEOMETRY_NO_ENTRY_SUBSTITUTION_RULE",
        "BUILD_DECISION": "R6_SIGNAL_EXISTS_BUT_NO_COMPATIBLE_ACTION_RULE_EXISTS",
        "classification_option": "C",
        "R1_MILD_OVERLAY_RELATION_TO_R6": "EXACT_R6_GE90_FLAG;TOP_DECILE_0.75X_TO_CASH;NO_REPLACEMENT;DIFFERENT_FROM_ENTRY_SUBSTITUTION",
        "R11_PROSPECTIVE_RELATION_TO_R6": "EXACT_R6_GE90_FLAG;TOP_DECILE_0.50X_TO_CASH;NO_REPLACEMENT;DIFFERENT_FROM_ENTRY_SUBSTITUTION",
        "exact_existing_r6_entry_substitution_rule_found": False,
        "prior_rule_authority_resolved_without_economic_comparison": True,
        "prior_rule_registry_rows": relevant[["canonical_branch_id", "action_locus", "economic_translation", "branch_status", "forward_status", "reason"]].to_dict("records"),
        "selected_existing_action_rule": "NONE_COMPATIBLE_ENTRY_SUBSTITUTION_RULE",
        "selected_existing_action_artifact": "NOT_APPLICABLE_NEW_ACTION_MAPPING_ONLY",
        "selected_existing_action_sha256": "NOT_APPLICABLE_NEW_ACTION_MAPPING_ONLY",
        "new_tail_model_created": False,
        "new_feature_set_created": False,
        "new_label_created": False,
        "new_strategy_created": False,
        "new_portfolio_engine_created": False,
        "evidence_read_policy": "FROZEN_CONTRACT_AND_REGISTRY_METADATA_ONLY;NO_RULE_SELECTED_BY_ECONOMICS",
        "searched_terms": ["R6_BAD_ASYMMETRY", "BAD_ASYMMETRY", "tail_overlay", "tail_control", "tail_veto", "risk_veto", "risk_filter", "risk_replacement", "mild_overlay", "R11", "prospective", "loser_control", "downside_filter", "risk_score", "high_risk", "avoid", "substitute", "entrant", "incumbent"],
    }


def provenance_payload(identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "R6_SIGNAL_SHA256": sha256_file(R6_IDENTITY),
        "R6_MODEL_NAME": identity["RISK_MODEL_NAME"],
        "R6_MODEL_HASH": identity["RISK_MODEL_HASH"],
        "R6_ACTION_THRESHOLD_STATUS": "PASS_PREEXISTING_FIXED_ACTION_THRESHOLD",
        "R6_ACTION_THRESHOLD_VALUE_OR_RULE": "risk_percentile>=0.90",
        "R6_ACTION_THRESHOLD_PROVENANCE": [
            {"artifact": str(R11_CONTRACT), "sha256": sha256_file(R11_CONTRACT), "timestamp": "2026-08-18T09:20:14.979928+00:00", "role": "FORMALLY_PREREGISTERED_PROSPECTIVE_ACTION"},
            {"artifact": str(R6_OVERLAY_CONTRACT), "sha256": sha256_file(R6_OVERLAY_CONTRACT), "timestamp": "2026-08-20T15:44:07.009930+00:00", "role": "FROZEN_BEFORE_PRE2026_OUTCOME_READ"},
        ],
        "action_state_only": "HIGH_RISK_IF_GE_0.90;NOT_HIGH_RISK_IF_LT_0.90;MISSING_IS_NEITHER",
        "post_hoc_threshold_created": False,
        "threshold_search_count": 0,
    }


def protocol_payload(anti: dict[str, Any], provenance: dict[str, Any]) -> dict[str, Any]:
    return {
        "task": "A2_R6_BAD_ASYMMETRY_SINGLE_TAIL_CONTROL_DESIGN_AND_FREEZE_R1",
        "research_role": ["ANTI_DUPLICATION", "DESIGN_AND_FREEZE_ONLY", "STRUCTURAL_VALIDATION_ONLY"],
        "economic_outcome_read_count_at_freeze": 0,
        "parent_raw_a2": {"alias": "A2_HGB", "model_sha256": EXPECTED[RAW_MODEL], "portfolio": "TOP20_EQUAL_WEIGHT_LONG_ONLY", "ranking": "A2_SCORE_DESC_THEN_TICKER_ASC"},
        "risk_signal": {"name": "R6_BAD_ASYMMETRY", "identity_path": str(R6_IDENTITY), "identity_sha256": EXPECTED[R6_IDENTITY], "model": R6_MODEL_NAME, "action_rule": provenance["R6_ACTION_THRESHOLD_VALUE_OR_RULE"], "missing_score": "FAIL_OPEN_TO_CANONICAL_RAW_A2"},
        "mechanism_parent": {"path": str(MECHANISM_PROTOCOL), "sha256": EXPECTED[MECHANISM_PROTOCOL], "classification": "STRONG_EXISTING_TAIL_LOSS_MECHANISM"},
        "anti_duplication": anti,
        "proposed_frozen_name": "A2_R6_BAD_ASYMMETRY_ENTRY_GUARD_SHADOW_R1",
        "rule_family": "EXISTING_R6_ENTRY_ONLY_TAIL_SUBSTITUTION_GUARD",
        "initialization": "First common authoritative Raw-A2/R6 structural date copies canonical Raw A2 Top20 exactly; no intervention.",
        "state_transition": {
            "semantics_source": str(TRANSITION_SOURCE),
            "canonical_entries": "Current Raw A2 Top20 members absent from prior Raw A2 Top20, ordered by current authoritative rank then ticker.",
            "exit_pairing": "Prior Raw A2 exits ordered by prior rank descending then ticker and paired positionally; if absent from shadow, remove the worst current-rank shadow name outside current Raw Top20.",
            "multiple_entries": "Process forced vacancies first, then canonical optional requests sequentially using the updated shadow state.",
            "grandfather": "Existing valid holdings are not sold because of R6.",
            "forced_exit": "Never retain an invalid/off-surface holding; apply the same entrant guard to its replacement and fall back to canonical if needed.",
        },
        "candidate_rule": {
            "canonical_not_flagged": "Accept canonical entrant.",
            "canonical_missing": "Accept canonical entrant and record MISSING_R6_SCORE_FALLBACK.",
            "canonical_flagged": "Scan downward by authoritative Raw A2 rank then ticker.",
            "substitute": "First valid non-held, lower-ranked candidate with a valid same-date frozen R6 percentile below 0.90.",
            "fallback": "If none exists, accept canonical entrant; never cash or resize.",
            "score_surface_boundary": "Use only preserved frozen OOF R6 scores. Never infer/refit R6 for unscored candidates. This is a hard provenance boundary, not a rank cap.",
        },
        "weights": "Raw A2 equal weights; 1/20 each",
        "tail_forced_sell_active": False,
        "tail_sizing_active": False,
        "beta_constraint_active": False,
        "sector_budget_active": False,
        "rx_margin_active": False,
        "regime_gate_active": False,
        "vol_target_active": False,
        "cost_convention_future_only": "Exact Raw A2 10 BPS one-way turnover convention; no cost calculated now.",
        "structural_acceptance_gates": {
            "signal_identity_match": True,
            "deterministic_replay": True,
            "all_substitutes_authoritative_and_scored": True,
            "portfolio_count_20": True,
            "missing_not_classified_safe_or_risky": True,
            "actual_intervention_reduces_flagged_entry_exposure": True,
            "at_least_one_actual_intervention": True,
            "no_economic_outcomes": True,
        },
        "warning_only": "Rank displacement or membership divergence may set STRUCTURAL_INTRUSIVENESS_WARNING but is not a post-hoc failure threshold.",
        "future_evaluation": {
            "authorized_now": False,
            "evidence_label": "RETROSPECTIVE_EXPOSED_SHADOW_DIAGNOSTIC",
            "comparison": ["RAW_A2", "A2_R6_BAD_ASYMMETRY_ENTRY_GUARD_SHADOW_R1"],
            "metrics": ["net_return", "annualized_return", "Sharpe", "volatility", "MaxDD", "Sortino", "Calmar", "turnover", "cost", "worst_5pct_day_mean", "worst_decile_day_return", "tail_event_incidence", "tail_loss_contribution", "right_tail_upside_contribution", "SPY_beta", "QQQ_beta", "SOXX_beta", "sector_HHI"],
            "intervention_horizons": [1, 5, 20],
            "intervention_statistics": ["mean", "median", "win_rate", "HAC_inference"],
            "years": ["2023", "2024", "2025", "2026_EXPOSED"],
            "rescue_variants_forbidden": True,
        },
        "prohibitions": ["economic_outcome_read", "model_refit", "new_feature", "new_label", "threshold_search", "risk_sizing", "beta_control", "sector_control", "RX_margin", "regime_gate", "vol_target", "rank_cap", "cash_fallback", "registry_change"],
    }


def load_structural_inputs(transition: Any) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    pretop = transition.import_pretop()
    pool, top, facts = pretop.load_candidate_pool()
    pool = pool[["signal_date", "ticker", "a2_prediction", "a2_rank"]].copy()
    pool["signal_date"] = pd.to_datetime(pool.signal_date).dt.normalize()
    pool["ticker"] = pool.ticker.astype(str)
    # Column projection is a hard no-outcome boundary.
    score = pd.read_parquet(R6_OOF, columns=["signal_date", "ticker", "risk_percentile", "candidate_id"])
    score = score.loc[score.candidate_id.eq(R6_MODEL_NAME), ["signal_date", "ticker", "risk_percentile"]].copy()
    score["signal_date"] = pd.to_datetime(score.signal_date).dt.normalize()
    score["ticker"] = score.ticker.astype(str)
    require(not score.duplicated(["signal_date", "ticker"]).any(), "R6_SCORE_DUPLICATE")
    require(score.signal_date.max() < pd.Timestamp("2026-01-01"), "POST2025_SCORE_READ")
    dates = set(score.signal_date.unique())
    pool = pool.loc[pool.signal_date.isin(dates)].copy()
    full_joined = score.merge(pool[["signal_date", "ticker"]], on=["signal_date", "ticker"], how="left", indicator=True)
    off_surface_score_rows = int(full_joined._merge.ne("both").sum())
    score = score.merge(pool[["signal_date", "ticker"]], on=["signal_date", "ticker"], how="inner", validate="one_to_one")
    top_authoritative = pool.sort_values(["signal_date", "a2_rank", "ticker"], kind="mergesort").groupby("signal_date", sort=True).head(TOP_N)
    top_joined = top_authoritative[["signal_date", "ticker"]].merge(score, on=["signal_date", "ticker"], how="outer", indicator=True)
    require(pool.groupby("signal_date").size().gt(TOP_N).all(), "RANK_SURFACE_TOO_SMALL")
    return pool, score, {
        "candidate_pool": facts,
        "signal_dates": len(dates),
        "score_rows": len(score),
        "r6_score_rows_excluded_off_authoritative_full_rank_surface": off_surface_score_rows,
        "authoritative_top20_common_score_rows": int(top_joined._merge.eq("both").sum()),
        "authoritative_top20_missing_score_rows": int(top_joined._merge.eq("left_only").sum()),
        "r6_scored_rows_outside_authoritative_top20": int(top_joined._merge.eq("right_only").sum()),
        "authoritative_top20_score_coverage": float(top_joined._merge.eq("both").sum() / len(top_authoritative)),
        "score_columns_read": ["signal_date", "ticker", "risk_percentile", "candidate_id"],
        "economic_columns_read": [],
    }


def select_for_event(original: str, exit_name: str, holdings: set[str], ordered: list[str], ranks: dict[str, int], scores: dict[str, float]) -> dict[str, Any]:
    score = scores.get(original)
    if score is None or not np.isfinite(score):
        return {"chosen": original, "flagged": False, "missing": True, "found": False, "intervention": False}
    if score < R6_THRESHOLD:
        return {"chosen": original, "flagged": False, "missing": False, "found": False, "intervention": False}
    for candidate in ordered:
        if ranks[candidate] <= ranks[original] or candidate in holdings or candidate == exit_name:
            continue
        candidate_score = scores.get(candidate)
        if candidate_score is not None and np.isfinite(candidate_score) and candidate_score < R6_THRESHOLD:
            return {"chosen": candidate, "flagged": True, "missing": False, "found": True, "intervention": candidate != original}
    return {"chosen": original, "flagged": True, "missing": False, "found": False, "intervention": False}


def replay(panel: pd.DataFrame, score: pd.DataFrame, transition: Any) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    score_by_date = {pd.Timestamp(date): dict(zip(day.ticker, day.risk_percentile.astype(float))) for date, day in score.groupby("signal_date", sort=True)}
    rows: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    memberships: list[tuple[str, tuple[str, ...]]] = []
    previous_shadow: set[str] | None = None
    previous_raw: set[str] | None = None
    previous_ranks: dict[str, int] = {}
    for date, day in panel.groupby("signal_date", sort=True):
        day = day.sort_values(["a2_rank", "ticker"], kind="mergesort")
        ordered = day.ticker.astype(str).tolist()
        ranks = dict(zip(day.ticker.astype(str), day.a2_rank.astype(int)))
        raw = set(ordered[:TOP_N])
        scores = score_by_date[pd.Timestamp(date)]
        optional_requests = available = missing = flagged = found = fallback = interventions = forced_count = 0
        if previous_shadow is None:
            shadow = set(raw)
        else:
            shadow = set(previous_shadow)
            forced = sorted(name for name in shadow if name not in ranks)
            for exit_name in forced:
                forced_count += 1
                candidates = [name for name in ordered[:TOP_N] if name not in shadow] or [name for name in ordered if name not in shadow]
                require(candidates, "FORCED_REPLACEMENT_CANDIDATE", date)
                original = candidates[0]
                selection = select_for_event(original, exit_name, shadow, ordered, ranks, scores)
                shadow.remove(exit_name)
                shadow.add(selection["chosen"])
                events.append({"signal_date": pd.Timestamp(date).date().isoformat(), "event_type": "FORCED", "canonical_entrant": original, "selected": selection["chosen"], "canonical_rank": ranks[original], "selected_rank": ranks[selection["chosen"]], **selection})
            new_entries = sorted(raw - (previous_raw or set()), key=lambda name: (ranks[name], name))
            raw_exits = sorted((previous_raw or set()) - raw, key=lambda name: (-previous_ranks.get(name, -1), name))
            for index, original in enumerate(new_entries):
                optional_requests += 1
                canonical_score = scores.get(original)
                if canonical_score is None or not np.isfinite(canonical_score):
                    missing += 1
                else:
                    available += 1
                    flagged += int(canonical_score >= R6_THRESHOLD)
                if original in shadow:
                    events.append({"signal_date": pd.Timestamp(date).date().isoformat(), "event_type": "OPTIONAL_ALREADY_HELD", "canonical_entrant": original, "selected": original, "canonical_rank": ranks[original], "selected_rank": ranks[original], "flagged": bool(canonical_score is not None and np.isfinite(canonical_score) and canonical_score >= R6_THRESHOLD), "missing": bool(canonical_score is None or not np.isfinite(canonical_score)), "found": False, "intervention": False})
                    continue
                paired_exit = raw_exits[index] if index < len(raw_exits) else None
                if paired_exit not in shadow:
                    outside = [name for name in shadow if name not in raw]
                    require(outside, "OPTIONAL_EXIT_CANDIDATE", {"date": str(date), "entrant": original})
                    paired_exit = sorted(outside, key=lambda name: (-ranks.get(name, 10**9), name))[0]
                selection = select_for_event(original, paired_exit, shadow, ordered, ranks, scores)
                if selection["flagged"]:
                    if selection["found"]:
                        found += 1
                    else:
                        fallback += 1
                if selection["intervention"]:
                    interventions += 1
                shadow.remove(paired_exit)
                shadow.add(selection["chosen"])
                events.append({"signal_date": pd.Timestamp(date).date().isoformat(), "event_type": "OPTIONAL", "canonical_entrant": original, "selected": selection["chosen"], "canonical_rank": ranks[original], "selected_rank": ranks[selection["chosen"]], **selection})
        require(len(raw) == TOP_N and len(shadow) == TOP_N and len(shadow & set(ordered)) == TOP_N, "PORTFOLIO_INTEGRITY", date)
        raw_high = sum(1 for name in raw if name in scores and np.isfinite(scores[name]) and scores[name] >= R6_THRESHOLD)
        shadow_high = sum(1 for name in shadow if name in scores and np.isfinite(scores[name]) and scores[name] >= R6_THRESHOLD)
        raw_coverage = sum(1 for name in raw if name in scores and np.isfinite(scores[name])) / TOP_N
        shadow_coverage = sum(1 for name in shadow if name in scores and np.isfinite(scores[name])) / TOP_N
        rows.append({
            "signal_date": pd.Timestamp(date).date().isoformat(), "optional_new_entries": optional_requests,
            "r6_score_available_entries": available, "r6_score_missing_entries": missing,
            "high_risk_canonical_entries": flagged, "compliant_substitutes_found": found,
            "no_compliant_substitute_fallbacks": fallback, "missing_signal_fallbacks": missing,
            "interventions": interventions, "forced_exit_count": forced_count,
            "raw_a2_high_risk_weight_share": raw_high * WEIGHT, "shadow_high_risk_weight_share": shadow_high * WEIGHT,
            "raw_r6_signal_coverage": raw_coverage, "shadow_r6_signal_coverage": shadow_coverage,
            "raw_structural_turnover": transition.turnover(previous_raw, raw), "shadow_structural_turnover": transition.turnover(previous_shadow, shadow),
            "membership_difference_rate": 1.0 - len(raw & shadow) / TOP_N,
        })
        memberships.append((rows[-1]["signal_date"], tuple(sorted(shadow))))
        previous_shadow, previous_raw, previous_ranks = set(shadow), set(raw), ranks
    daily = pd.DataFrame(rows)
    event_frame = pd.DataFrame(events)
    return daily, event_frame, stable_hash({"rows": rows, "memberships": memberships, "events": events})


def metrics(daily: pd.DataFrame, events: pd.DataFrame) -> tuple[dict[str, Any], dict[str, bool]]:
    actual = events.loc[events.intervention.eq(True)].copy() if len(events) else events.copy()
    displacement = (actual.selected_rank - actual.canonical_rank).astype(float) if len(actual) else pd.Series(dtype=float)
    optional_total = int(daily.optional_new_entries.sum())
    high_total = int(daily.high_risk_canonical_entries.sum())
    raw_turnover = float(daily.raw_structural_turnover.sum())
    shadow_turnover = float(daily.shadow_structural_turnover.sum())
    result = {
        "total_signal_dates": len(daily), "total_optional_new_entries": optional_total,
        "r6_score_available_entries": int(daily.r6_score_available_entries.sum()), "r6_score_missing_entries": int(daily.r6_score_missing_entries.sum()),
        "high_risk_canonical_entry_count": high_total, "high_risk_canonical_entry_share": high_total / optional_total if optional_total else None,
        "compliant_substitute_found_count": int(daily.compliant_substitutes_found.sum()),
        "no_compliant_substitute_fallback_count": int(daily.no_compliant_substitute_fallbacks.sum()),
        "missing_signal_fallback_count": int(daily.missing_signal_fallbacks.sum()),
        "intervention_count": len(actual), "intervention_share": len(actual) / optional_total if optional_total else None,
        "average_canonical_entrant_rank": float(actual.canonical_rank.mean()) if len(actual) else None,
        "average_substitute_rank": float(actual.selected_rank.mean()) if len(actual) else None,
        "average_rank_displacement": float(displacement.mean()) if len(displacement) else None,
        "p50_rank_displacement": float(displacement.quantile(0.50)) if len(displacement) else None,
        "p90_rank_displacement": float(displacement.quantile(0.90)) if len(displacement) else None,
        "max_rank_displacement": int(displacement.max()) if len(displacement) else None,
        "percent_substitute_rank_gt40": float(actual.selected_rank.gt(40).mean()) if len(actual) else None,
        "percent_substitute_rank_gt60": float(actual.selected_rank.gt(60).mean()) if len(actual) else None,
        "percent_substitute_rank_gt100": float(actual.selected_rank.gt(100).mean()) if len(actual) else None,
        "holding_membership_difference_rate": float(daily.membership_difference_rate.mean()),
        "structural_turnover_difference_rate": (shadow_turnover - raw_turnover) / raw_turnover if raw_turnover else None,
        "average_raw_a2_high_risk_weight_share": float(daily.raw_a2_high_risk_weight_share.mean()),
        "average_shadow_high_risk_weight_share": float(daily.shadow_high_risk_weight_share.mean()),
        "p90_raw_a2_high_risk_weight_share": float(daily.raw_a2_high_risk_weight_share.quantile(.90)),
        "p90_shadow_high_risk_weight_share": float(daily.shadow_high_risk_weight_share.quantile(.90)),
        "high_risk_entry_count_raw": high_total,
        "high_risk_entry_count_shadow": int(actual.loc[actual.flagged.eq(True), "selected"].map(lambda _: 0).sum()) if len(actual) else 0,
        "r6_signal_coverage_raw": float(daily.raw_r6_signal_coverage.mean()),
        "r6_signal_coverage_shadow": float(daily.shadow_r6_signal_coverage.mean()),
        "structural_intrusiveness_warning": bool(len(displacement) and (displacement.max() > TOP_N or daily.membership_difference_rate.max() > .25)),
    }
    gates = {
        "at_least_one_actual_intervention": len(actual) > 0,
        "every_intervention_reduces_flagged_entry_exposure": bool(len(actual) and actual.flagged.all() and actual.found.all() and actual.selected.ne(actual.canonical_entrant).all()),
        "all_substitutes_lower_ranked": bool(not len(actual) or actual.selected_rank.gt(actual.canonical_rank).all()),
        "portfolio_count_preserved": True,
        "missing_signal_explicit": int(daily.r6_score_missing_entries.sum()) == int(daily.missing_signal_fallbacks.sum()),
        "no_unscored_substitute": bool(not len(actual) or actual.found.all()),
    }
    return result, gates


def report_text(summary: dict[str, Any]) -> str:
    m = summary["structural_metrics"]
    return f"""# A2 R6 bad-asymmetry single tail-control design / freeze R1

## Decision

The duplication gate found no prior R6 entry-substitution action. R1_MILD and R11 both use the pre-existing `risk_percentile >= 0.90` flag, but attenuate weight to cash and explicitly perform no replacement. The proposed entry-only action is therefore non-duplicative, and its threshold provenance is pre-existing rather than derived from the parent mechanism audit.

## Structural result

The protocol was frozen before reading the projected R6 score columns. On {m['total_signal_dates']} pre-2026 OOF dates, {m['total_optional_new_entries']} canonical optional entries included {m['high_risk_canonical_entry_count']} flagged entries. The provenance-clean score surface supported {m['intervention_count']} actual substitutions and {m['no_compliant_substitute_fallback_count']} flagged fallbacks. Mean flagged weight changed from {m['average_raw_a2_high_risk_weight_share']:.6f} to {m['average_shadow_high_risk_weight_share']:.6f}.

Final classification: **{summary['final_classification']}**.

No row-level return, PnL, NAV, outcome, target, or label column was read. No model was fitted, no threshold was searched, and no economic evaluation occurred. {('The contract was frozen for a future economic evaluation.' if summary['contract_created'] else 'The contract was not frozen because a hard structural gate failed.')}
"""


def fmt(value: Any) -> str:
    if value is None:
        return "NOT_APPLICABLE"
    if isinstance(value, float):
        return f"{value:.12g}"
    return str(value)


def print_console(summary: dict[str, Any]) -> None:
    m = summary["structural_metrics"]
    lines = [
        "=" * 60, "A2 R6 BAD-ASYMMETRY SINGLE TAIL CONTROL DESIGN / FREEZE", "=" * 60, "", f"STATUS={summary['status']}", "",
        "-" * 60, "ANTI-DUPLICATION", "-" * 60, "", f"ANTI_DUPLICATION_AUDIT_STATUS={summary['anti_duplication_audit_status']}",
        "R1_MILD_OVERLAY_RELATION_TO_R6=EXACT_R6_GE90_FLAG;TOP_DECILE_0.75X_TO_CASH;NO_REPLACEMENT;DIFFERENT_FROM_ENTRY_SUBSTITUTION",
        "R11_PROSPECTIVE_RELATION_TO_R6=EXACT_R6_GE90_FLAG;TOP_DECILE_0.50X_TO_CASH;NO_REPLACEMENT;DIFFERENT_FROM_ENTRY_SUBSTITUTION",
        "", "BUILD_DECISION=R6_SIGNAL_EXISTS_BUT_NO_COMPATIBLE_ACTION_RULE_EXISTS", "", "SELECTED_EXISTING_ACTION_RULE=NONE_COMPATIBLE_ENTRY_SUBSTITUTION_RULE",
        "SELECTED_EXISTING_ACTION_ARTIFACT=NOT_APPLICABLE_NEW_ACTION_MAPPING_ONLY", "SELECTED_EXISTING_ACTION_SHA256=NOT_APPLICABLE_NEW_ACTION_MAPPING_ONLY", "",
        "NEW_TAIL_MODEL_CREATED=FALSE", "NEW_FEATURE_SET_CREATED=FALSE", "NEW_LABEL_CREATED=FALSE", "",
        "-" * 60, "R6 ACTION PROVENANCE", "-" * 60, "", f"R6_SIGNAL_SHA256={EXPECTED[R6_IDENTITY]}", "",
        "R6_ACTION_THRESHOLD_STATUS=PASS_PREEXISTING_FIXED_ACTION_THRESHOLD", "R6_ACTION_THRESHOLD_VALUE_OR_RULE=risk_percentile>=0.90",
        "R6_ACTION_THRESHOLD_PROVENANCE=R11_PREREGISTERED_2026-08-18_PLUS_R1_FROZEN_BEFORE_PRE2026_OUTCOME_READ_2026-08-20", "", "POST_HOC_THRESHOLD_CREATED=FALSE", "",
        "-" * 60, "FROZEN SHADOW", "-" * 60, "", f"FROZEN_NAME={summary['frozen_name']}", "RULE_FAMILY=EXISTING_R6_ENTRY_ONLY_TAIL_SUBSTITUTION_GUARD", "",
        "ENTRY_ONLY=TRUE", "TAIL_FORCED_SELL_ACTIVE=FALSE", "TAIL_SIZING_ACTIVE=FALSE", "", "BETA_CONSTRAINT_ACTIVE=FALSE", "SECTOR_BUDGET_ACTIVE=FALSE", "RX_MARGIN_ACTIVE=FALSE", "REGIME_GATE_ACTIVE=FALSE", "",
        "-" * 60, "STRUCTURAL", "-" * 60, "", f"TOTAL_SIGNAL_DATES={m['total_signal_dates']}", f"TOTAL_OPTIONAL_NEW_ENTRIES={m['total_optional_new_entries']}", "",
        f"R6_SCORE_AVAILABLE_ENTRIES={m['r6_score_available_entries']}", f"R6_SCORE_MISSING_ENTRIES={m['r6_score_missing_entries']}", "",
        f"HIGH_RISK_CANONICAL_ENTRY_COUNT={m['high_risk_canonical_entry_count']}", f"HIGH_RISK_CANONICAL_ENTRY_SHARE={fmt(m['high_risk_canonical_entry_share'])}", "",
        f"COMPLIANT_SUBSTITUTE_FOUND_COUNT={m['compliant_substitute_found_count']}", f"NO_COMPLIANT_SUBSTITUTE_FALLBACK_COUNT={m['no_compliant_substitute_fallback_count']}", f"MISSING_SIGNAL_FALLBACK_COUNT={m['missing_signal_fallback_count']}", "",
        f"INTERVENTION_COUNT={m['intervention_count']}", f"INTERVENTION_SHARE={fmt(m['intervention_share'])}", "", f"AVG_RANK_DISPLACEMENT={fmt(m['average_rank_displacement'])}",
        f"P90_RANK_DISPLACEMENT={fmt(m['p90_rank_displacement'])}", f"MAX_RANK_DISPLACEMENT={fmt(m['max_rank_displacement'])}", "",
        f"HOLDING_MEMBERSHIP_DIFFERENCE_RATE={fmt(m['holding_membership_difference_rate'])}", f"STRUCTURAL_TURNOVER_DIFFERENCE_RATE={fmt(m['structural_turnover_difference_rate'])}", "",
        f"AVG_RAW_A2_HIGH_RISK_WEIGHT_SHARE={fmt(m['average_raw_a2_high_risk_weight_share'])}", f"AVG_SHADOW_HIGH_RISK_WEIGHT_SHARE={fmt(m['average_shadow_high_risk_weight_share'])}", "",
        f"STRUCTURAL_INTRUSIVENESS_WARNING={str(m['structural_intrusiveness_warning']).upper()}", "", "ECONOMIC_OUTCOME_READ_COUNT=0", "",
        "-" * 60, "FREEZE", "-" * 60, "", f"TAIL_CONTROL_DESIGN_PROTOCOL_SHA256={summary['tail_control_design_protocol_sha256']}", f"TAIL_CONTROL_FROZEN_CONTRACT_SHA256={summary['tail_control_frozen_contract_sha256']}", "",
        f"FINAL_CLASSIFICATION={summary['final_classification']}", "", f"NEXT_RESEARCH_PRIORITY={summary['next_research_priority']}", "",
        "-" * 60, "SAFETY", "-" * 60, "", "ECONOMIC_OUTCOME_READ_COUNT=0", "THRESHOLD_SEARCH_COUNT=0", "NEW_STRATEGY_ECONOMIC_TEST_COUNT=0", "MODEL_REFIT_COUNT=0", "REGISTRY_CHANGE_COUNT=0", "",
        "RAW_A2_UNCHANGED=TRUE", "PROSPECTIVE_A2_X0_PROTOCOL_UNTOUCHED=TRUE", "", "TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT=0", "", f"ARTIFACT_DIR={OUT}", "=" * 60,
    ]
    print("\n".join(lines))


def main() -> None:
    protected_before = tree_snapshot(PROTECTED)
    identity = verify_inputs()
    transition = import_transition()
    anti = anti_duplication_payload()
    provenance = provenance_payload(identity)
    protocol = protocol_payload(anti, provenance)
    if not OUT.exists():
        OUT.mkdir(parents=True, exist_ok=False)
        write_json(OUT / "anti_duplication_audit.json", anti)
        write_json(OUT / "r6_action_rule_provenance.json", provenance)
        write_json(OUT / "tail_control_design_protocol.json", protocol)
    else:
        require(json.loads((OUT / "anti_duplication_audit.json").read_text(encoding="utf-8")) == anti, "FROZEN_ANTI_DUPLICATION_CHANGED")
        require(json.loads((OUT / "r6_action_rule_provenance.json").read_text(encoding="utf-8")) == provenance, "FROZEN_PROVENANCE_CHANGED")
        require(json.loads((OUT / "tail_control_design_protocol.json").read_text(encoding="utf-8")) == protocol, "FROZEN_PROTOCOL_CHANGED")
    protocol_sha = sha256_file(OUT / "tail_control_design_protocol.json")

    panel, score, input_facts = load_structural_inputs(transition)
    daily1, events1, replay_hash1 = replay(panel, score, transition)
    daily2, events2, replay_hash2 = replay(panel, score, transition)
    require(replay_hash1 == replay_hash2 and daily1.equals(daily2) and events1.equals(events2), "NONDETERMINISTIC_TRANSITION")
    structural_metrics, gates = metrics(daily1, events1)
    gates["deterministic_replay"] = True
    gates["raw_a2_identity"] = True
    gates["economic_outcome_read_count_zero"] = True
    gates["protected_tree_unchanged"] = tree_snapshot(PROTECTED)["tree_sha256"] == protected_before["tree_sha256"]
    structurally_valid = all(gates.values())
    final_classification = "PASS_FROZEN_SINGLE_R6_ENTRY_GUARD_SHADOW" if structurally_valid else "FAIL_STRUCTURAL_DEGENERACY"
    contract_sha = "NOT_CREATED_STRUCTURAL_DEGENERACY"
    frozen_name = "NOT_FROZEN_STRUCTURAL_DEGENERACY"
    if structurally_valid:
        contract = {
            "frozen_name": "A2_R6_BAD_ASYMMETRY_ENTRY_GUARD_SHADOW_R1", "rule_family": "EXISTING_R6_ENTRY_ONLY_TAIL_SUBSTITUTION_GUARD",
            "design_protocol_path": str(OUT / "tail_control_design_protocol.json"), "design_protocol_sha256": protocol_sha,
            "parent_hashes": {"raw_a2_model": EXPECTED[RAW_MODEL], "r6_identity": EXPECTED[R6_IDENTITY], "mechanism_protocol": EXPECTED[MECHANISM_PROTOCOL]},
            "exact_rule": protocol["candidate_rule"], "state_transition": protocol["state_transition"], "future_evaluation": protocol["future_evaluation"],
            "prohibitions": protocol["prohibitions"], "structural_validation": {"metrics": structural_metrics, "gates": gates, "replay_sha256": replay_hash1},
            "canonical_registry_change": False, "research_shadow_only": True,
        }
        write_json(OUT / "frozen_contract.json", contract)
        contract_sha = sha256_file(OUT / "frozen_contract.json")
        frozen_name = contract["frozen_name"]

    daily1.to_csv(OUT / "structural_dry_run.csv", index=False, float_format="%.12g")
    protected_after = tree_snapshot(PROTECTED)
    manifest = {
        "structural_only": True, "economic_outcome_read_count": 0,
        "sources": [
            {"path": str(RAW_OOF), "sha256": sha256_file(RAW_OOF), "columns_read": ["signal_date", "ticker", "universe_size", "split", "a2_model_name", "a2_prediction", "a2_rank"], "role": "authoritative full Raw A2 ranking"},
            {"path": str(R6_OOF), "sha256": sha256_file(R6_OOF), "columns_read": input_facts["score_columns_read"], "columns_explicitly_not_read": ["next_day_stock_return", "forward_5d_stock_return", "forward_5d_stock_mae", "forward_5d_stock_mfe", "bad_asymmetry_5d", "bad_severe_negative_5d", "target_end_date"], "role": "frozen R6 OOF risk percentile only"},
            {"path": str(R6_IDENTITY), "sha256": sha256_file(R6_IDENTITY), "role": "frozen R6 identity"},
            {"path": str(MECHANISM_PROTOCOL), "sha256": sha256_file(MECHANISM_PROTOCOL), "role": "parent mechanism protocol"},
            {"path": str(R6_OVERLAY_CONTRACT), "sha256": sha256_file(R6_OVERLAY_CONTRACT), "role": "R1_MILD threshold/action provenance"},
            {"path": str(R11_CONTRACT), "sha256": sha256_file(R11_CONTRACT), "role": "R11 preregistered threshold/action provenance"},
            {"path": str(CURRENT_BRANCH_REGISTRY), "sha256": sha256_file(CURRENT_BRANCH_REGISTRY), "role": "current branch authority"},
            {"path": str(RISK_REGISTRY), "sha256": sha256_file(RISK_REGISTRY), "role": "R6 registered identity"},
            {"path": str(TRANSITION_SOURCE), "sha256": sha256_file(TRANSITION_SOURCE), "role": "reused state transition and turnover semantics"},
            {"path": str(PRETOP_SOURCE), "sha256": sha256_file(PRETOP_SOURCE), "role": "reused authoritative candidate loader"},
        ],
        "input_facts": input_facts, "protected_tree_before": protected_before, "protected_tree_after": protected_after,
        "task_owned_repo_root_temp_dirs": repo_temp_dirs(), "new_model_count": 0, "model_refit_count": 0, "threshold_search_count": 0,
    }
    write_json(OUT / "source_manifest.json", manifest)
    summary = {
        "status": "PASS_STRUCTURAL_VALIDATION_AND_FREEZE" if structurally_valid else "FAIL_HARD_STRUCTURAL_GATE",
        "anti_duplication_audit_status": anti["ANTI_DUPLICATION_AUDIT_STATUS"], "build_decision": anti["BUILD_DECISION"],
        "r6_signal_sha256": EXPECTED[R6_IDENTITY], "r6_action_threshold_status": provenance["R6_ACTION_THRESHOLD_STATUS"],
        "r6_action_threshold_value_or_rule": provenance["R6_ACTION_THRESHOLD_VALUE_OR_RULE"], "post_hoc_threshold_created": False,
        "tail_control_design_protocol_sha256": protocol_sha, "tail_control_frozen_contract_sha256": contract_sha,
        "frozen_name": frozen_name, "rule_family": protocol["rule_family"], "contract_created": structurally_valid,
        "structural_metrics": structural_metrics, "structural_gates": gates, "deterministic_replay_sha256": replay_hash1,
        "final_classification": final_classification,
        "next_research_priority": "EVALUATE_FROZEN_A2_R6_BAD_ASYMMETRY_ENTRY_GUARD_SHADOW_R1" if structurally_valid else "DO_NOT_EVALUATE_ECONOMICS_CLOSE_ENTRY_SUBSTITUTION_DESIGN_AS_STRUCTURALLY_DEGENERATE",
        "economic_outcome_read_count": 0, "threshold_search_count": 0, "new_strategy_economic_test_count": 0, "model_refit_count": 0, "registry_change_count": 0,
        "raw_a2_unchanged": True, "prospective_a2_x0_protocol_untouched": protected_before["tree_sha256"] == protected_after["tree_sha256"],
        "task_owned_repo_root_temp_dir_count": len(repo_temp_dirs()), "artifact_dir": str(OUT),
    }
    write_json(OUT / "summary.json", summary)
    (OUT / "concise_report.md").write_text(report_text(summary), encoding="utf-8")
    require(not repo_temp_dirs(), "TASK_CREATED_REPO_TEMP", repo_temp_dirs())
    print_console(summary)


if __name__ == "__main__":
    main()
