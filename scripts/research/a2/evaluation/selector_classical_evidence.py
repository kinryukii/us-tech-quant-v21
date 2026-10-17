"""Thin C11 lineage, membership validation and cumulative selector evidence."""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

from scripts.research.a2.evaluation import selector_evidence as evidence
from scripts.research.a2.evaluation import selector_sufficiency_evidence as c10
from scripts.research.a2.evaluation.selector_account_compare import readj, score_panel, score_path, sha

RESEARCH_ID = "V24_C_SELECTOR_CLASSICAL_RISK_AND_STATISTICAL_BREADTH_C11"
A_ROLES = ("C11_A1_ALPHA_VOL", "C11_A2_ALPHA_DOWNSIDE", "C11_A3_ALPHA_DRAWDOWN",
           "C11_A4_ALPHA_RISK3", "C11_A5_ALPHA_RISK4", "C11_A6_TREND_RISK3",
           "C11_A7_TREND_RISK4", "C11_A8_PARETO_ALPHA_RISK")
B_ROLES = tuple("C11_B_" + k for k in ("DIAG", "SAMPLE_COV", "LW", "OAS", "CONSTANT_CORR",
                                     "EWMA", "PCA", "GARCH", "GJR_GARCH", "COV_ENSEMBLE"))
SANITY_ROLES = ("C11_SANITY_MIN_VOL", "C11_SANITY_RAW_TOP20")
ROLES = (*A_ROLES, *B_ROLES, *SANITY_ROLES)
RAW, YEARS, YEAR_COUNTS, PRIMARY, BOOT_METHOD, TARGET = (
    evidence.RAW, c10.YEARS, c10.YEAR_COUNTS, c10.PRIMARY, c10.BOOT_METHOD, c10.TARGET)
TIE_POLICY = "SCORE_DESC_RAW_RANK_ASC_UID_ASC"


def validate_design(design):
    if (design.get("official_freeze") is not True or design.get("formal_freeze_applied") is not True
            or design.get("research_id") != RESEARCH_ID or tuple(design.get("roles", ())) != ROLES
            or design.get("target") != TARGET or tuple(design.get("primary_eval_years", ())) != YEARS):
        raise ValueError("EXACT_FORMAL_CLASSICAL_FREEZE_REQUIRED")
    if (design.get("mechanism_research_eligible") is not True
            or design.get("strict_PIT_promotion_eligible") is not False
            or design.get("test2026_locked") is not True
            or design.get("new2026_estimation_authorized") is not False):
        raise ValueError("MECHANISM_ONLY_2026_LOCK_REQUIRED")
    ev = design["evaluation"]
    if (ev.get("primary") != PRIMARY or ev.get("common_mature_date_count") != 732
            or ev.get("year_counts") != YEAR_COUNTS or ev.get("exposure_namespace") != 169
            or ev.get("numeric_ceiling") != 157 or ev.get("original_calendar_dates") != 752
            or ev.get("sanity_diagnostic_only") is not True):
        raise ValueError("ORIGINAL_CLOCK_AND_CUMULATIVE_169_EXPOSURE_REQUIRED")
    _rule(ev["bootstrap"])
    required = dict(pooled_edge_positive=True, year2025_edge_positive=True,
                    positive_years_min=2, simultaneous_lower_bound_gt_zero=True)
    if any(ev.get("inherited_selection_requirements", {}).get(k) != v for k, v in required.items()):
        raise ValueError("ORIGINAL_SUPPORT_THRESHOLD_REQUIRED")
    old = ev["legacy"]
    numeric, exposure, failed = old["numeric_ids"], old["exposure_ids"], old["failed_or_untestable"]
    if (len(numeric) != 137 or len(set(numeric)) != 137 or len(exposure) != 149
            or len(set(exposure)) != 149 or len(failed) != 12
            or set(numeric) & set(failed) or set(numeric) | set(failed) != set(exposure)
            or set(exposure) & set(ROLES)):
        raise ValueError("CLOSED_137_NUMERIC_149_EXPOSURE_HISTORY_REQUIRED")
    return ev


def _rule(rule, synthetic=False):
    if (rule.get("method") != BOOT_METHOD or rule.get("seed") != 20260928
            or rule.get("confidence") != .95 or rule.get("family_candidates") != 157
            or (not synthetic and rule.get("repeats") != 5000)
            or not isinstance(rule.get("repeats"), int) or rule["repeats"] < 2):
        raise ValueError("ORIGINAL_SHARED_5000_MAXT_RULE_REQUIRED")


def validate_legacy(legacy, paths):
    """Only design/assembly metadata are parsed; result artifacts remain opaque."""
    pin = c10.r5._pinned
    design_path = pin(legacy["design"], paths, "backtest")
    assembly_path = pin(legacy["assembly"], paths, "backtest")
    old, assembly = readj(design_path), readj(assembly_path)
    ev = c10.validate_design(old)
    result = pin(legacy["evidence"], paths, "backtest")
    edge, clock = (pin(legacy[k], paths, "backtest") for k in ("edge", "clock"))
    if (assembly_path != design_path.parent / "SCORE_ASSEMBLY.json"
            or result != design_path.parent / "diagnostics/selector_evidence/SELECTION_EVIDENCE.json"
            or edge != result.parent / "PRIMARY_DAILY_EDGE.parquet"
            or clock != result.parent / "COMMON_DATE_MATURITY.parquet"
            or assembly.get("complete_candidates") != list(c10.NEW_ROLES)
            or assembly.get("complete_fixed_references") != list(c10.REFERENCES)
            or assembly.get("failed_or_untestable") != {}
            or assembly.get("design_freeze_sha256") != legacy["design"]["sha256"]
            or assembly.get("forecast2026_rows") != 0
            or legacy["numeric_ids"] != [*ev["legacy"]["numeric_ids"], *c10.TEST_IDS]
            or legacy["exposure_ids"] != [*ev["legacy"]["exposure_ids"], *c10.TEST_IDS]
            or legacy["failed_or_untestable"] != ev["legacy"]["failed_or_untestable"]
            or not old.get("sources") or legacy.get("sources") != old["sources"]):
        raise ValueError("CLOSED_C10_OPAQUE_LINEAGE_CHANGED")
    for filename, digest in legacy["sources"].items():
        p = Path(filename).resolve()
        if not p.is_relative_to(paths.repo_root.resolve()) or sha(p) != digest:
            raise ValueError("FROZEN_C10_SOURCE_PIN_CHANGED")
    return ev


def validate_panel(reference, panel, clock):
    """Formula scores stay unperturbed; Raw rank, then UID, break score ties."""
    if (reference.columns.has_duplicates or panel.columns.has_duplicates
            or clock.columns.has_duplicates or len(clock) != 752 or clock.signal_date.duplicated().any()
            or clock.included.isna().any() or not pd.api.types.is_bool_dtype(clock.included)):
        raise ValueError("ORIGINAL_FULL_CLOCK_AND_UNAMBIGUOUS_PANEL_REQUIRED")
    calendar = pd.DatetimeIndex(clock.signal_date)
    included = pd.DatetimeIndex(clock.loc[clock.included, "signal_date"])
    if (calendar.hasnans or not calendar.is_monotonic_increasing
            or (calendar >= pd.Timestamp("2026-01-01")).any()
            or len(included) != 732 or {str(y): int((included.year == y).sum()) for y in YEARS} != YEAR_COUNTS
            or not pd.DatetimeIndex(sorted(reference.signal_date.unique())).equals(calendar)):
        raise ValueError("DO_NOT_SHRINK_OR_CHANGE_ORIGINAL_732_752_CLOCK")
    evidence.align(reference, panel)
    if not np.isfinite(panel[["score", "rank"]].to_numpy(float)).all():
        raise ValueError("FINITE_FULL_U_SCORE_AND_RANK_REQUIRED")
    ordered = panel.assign(_raw_rank=reference["rank"].to_numpy()).sort_values(
        ["signal_date", "score", "_raw_rank", "security_uid"],
        ascending=[True, False, True, True], kind="stable")
    if not ordered["rank"].eq(ordered.groupby("signal_date").cumcount() + 1).all():
        raise ValueError("FROZEN_SCORE_RAW_RANK_UID_TIE_REQUIRED")
    if panel.candidate_id.eq(SANITY_ROLES[1]).any() and (
            not panel.candidate_id.eq(SANITY_ROLES[1]).all()
            or not np.array_equal(panel.score.to_numpy(), reference.score.to_numpy())
            or not np.array_equal(panel["rank"].to_numpy(), reference["rank"].to_numpy())):
        raise ValueError("RAW_SANITY_MUST_BE_EXACT_RAW_SCORE_AND_RANK")
    mature, rows = evidence.maturity(reference, reference["rank"].le(20).to_numpy() | panel["rank"].le(20).to_numpy())
    if not rows.set_index("signal_date").loc[included, "included"].all():
        raise ValueError("SELECTED_LABELS_IMMATURE_NO_COMMON_DATE_SHRINK")
    return mature, rows


def bound_panel(root, cid, assembly, reference, clock):
    """Reuse the generic full-U/rank reader, without the old score-UID tie rule."""
    path, binding = score_path(root, cid).resolve(), assembly["score_paths"][cid]
    if path != Path(binding["path"]).resolve() or sha(path) != binding["sha256"]:
        raise ValueError("ASSEMBLED_SCORE_BINDING_CHANGED")
    panel, digest = score_panel(root, cid)
    validate_panel(reference, panel, clock)
    return panel, digest


def statistics(legacy_edges, new_edges, positions, calendar, rule, legacy_ids, failed=None, *, synthetic=False):
    """Comparison summaries only; the existing shared_max_t owns bootstrap math."""
    _rule(rule, synthetic)
    legacy_ids, failed = list(legacy_ids), dict(failed or {})
    calendar = pd.DatetimeIndex(calendar)
    positions = np.asarray(positions)
    index = legacy_edges.index
    if (len(legacy_ids) != 137 or len(set(legacy_ids)) != 137 or list(legacy_edges) != legacy_ids
            or len(index) != 732 or index.has_duplicates or index.hasnans
            or {str(y): int((index.year == y).sum()) for y in YEARS} != YEAR_COUNTS
            or not index.equals(new_edges.index) or new_edges.columns.has_duplicates
            or not set(new_edges).issubset(ROLES) or not set(failed).issubset(ROLES)
            or set(new_edges) & set(failed) or set(legacy_ids) & set(ROLES)
            or not np.isfinite(legacy_edges.to_numpy(float)).all()
            or not np.isfinite(new_edges.to_numpy(float)).all()
            or len(calendar) != 752 or calendar.hasnans or calendar.has_duplicates
            or not calendar.is_monotonic_increasing or (calendar >= pd.Timestamp("2026-01-01")).any()):
        raise ValueError("EXACT_FINITE_PRE2026_COMMON_CLOCK_REQUIRED")
    if (not np.issubdtype(positions.dtype, np.integer) or len(positions) != len(index)
            or (positions < 0).any() or (positions >= len(calendar)).any()
            or not np.all(np.diff(positions) > 0) or not calendar[positions].equals(index)):
        raise ValueError("ORIGINAL_CALENDAR_POSITIONS_REQUIRED")
    if SANITY_ROLES[1] in new_edges and not new_edges[SANITY_ROLES[1]].eq(0.).all():
        raise ValueError("EXACT_RAW_SANITY_EDGE_MUST_BE_ZERO")
    matrix = legacy_edges.copy()
    for cid in ROLES:
        if cid in new_edges:
            matrix[cid] = new_edges[cid]
        else:
            failed.setdefault(cid, "UNTESTABLE_REQUIRED_STATE_OR_INPUT")
    ids = list(matrix)
    _, _, previous, old_max = evidence.shared_max_t(legacy_edges.to_numpy(float), positions,
        [True] * 137, {**rule, "family_candidates": 137})
    lower, se, receipt, maxima = evidence.shared_max_t(matrix.to_numpy(float), positions,
        [True] * len(ids), {**rule, "family_candidates": len(ids)})
    if (receipt.get("status") != "COMPLETE" or previous.get("status") != "COMPLETE"
            or receipt["shared_draw_sha256"] != previous["shared_draw_sha256"]
            or len(maxima) != len(old_max) or np.any(maxima + 1e-12 < old_max)
            or receipt["critical_max_t"] + 1e-12 < previous["critical_max_t"]):
        raise ValueError("JOINT_MAXT_MUST_NOT_LOWER_LEGACY_THRESHOLD")
    summaries = []
    for cid in ROLES:
        complete, diagnostic = cid in matrix, cid in SANITY_ROLES
        j = ids.index(cid) if complete else None
        yearly = {str(y): float(matrix.loc[index.year == y, cid].mean()) if complete else None for y in YEARS}
        pooled = float(matrix[cid].mean()) if complete else None
        conditions = dict(complete_oof=complete, pooled_positive=pooled is not None and pooled > 0,
            year2025_positive=yearly["2025"] is not None and yearly["2025"] > 0,
            two_of_three_years_positive=sum(v is not None and v > 0 for v in yearly.values()) >= 2,
            nonzero_bootstrap_se=bool(complete and np.isfinite(se[j]) and se[j] > evidence.SE_TOL),
            simultaneous_lower_positive=bool(complete and np.isfinite(lower[j]) and lower[j] > 0))
        supported = not diagnostic and all(conditions.values())
        summaries.append(dict(candidate_id=cid, status="COMPLETE" if complete else "FAILED_UNTESTABLE",
            failure_reason=failed.get(cid), pooled_edge=pooled, year_edges=yearly,
            bootstrap_se=float(se[j]) if complete and np.isfinite(se[j]) else None,
            simultaneous_lower_95=float(lower[j]) if complete and np.isfinite(lower[j]) else None,
            research_support_conditions=conditions, diagnostic_only=diagnostic, supported=supported,
            mechanism_status="MECHANISM_SUPPORTED" if supported else "NO_SUPPORT",
            strict_PIT_promotion_eligible=False, economic_promotion_allowed=False))
    receipt.update(exposure_namespace=169, new_exposure_roles=list(ROLES), numeric_ceiling=157,
        legacy_exposure_namespace=149, legacy_numeric_complete_series=137, numeric_complete_series=len(ids),
        failed_or_untestable=failed, failed_series="exposure metadata only; no numeric zero placeholders",
        legacy_shared_draw_sha256=previous["shared_draw_sha256"], legacy_critical_max_t=previous["critical_max_t"],
        minimum_draw_wise_max_increment=float((maxima - old_max).min()),
        draw_wise_legacy_max_not_exceeded_downward=True, legacy_C10_reselected=False,
        sanity_promotion_allowed=False, synthetic_validation_only=synthetic)
    return matrix, summaries, receipt, maxima
