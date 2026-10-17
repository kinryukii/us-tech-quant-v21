"""C10 sufficiency comparisons, binding frozen panels to existing selector evidence."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.common.storage_paths import assert_safe_output_path, resolve
from scripts.research.a2.evaluation import selector_evidence as evidence
from scripts.research.a2.evaluation import selector_algorithm_breadth_evidence as r5
from scripts.research.a2.evaluation import selector_horizon_evidence as c7
from scripts.research.a2.evaluation.selector_account_compare import pre2026, readj, score_path, sha

REPO = Path(__file__).resolve().parents[4]
RESEARCH_ID = "V24_C_SELECTOR_TRAINING_SUFFICIENCY_C10"
PARADIGMS = ("POINT_HGB", "BOUNDARY_HGB", "PAIRWISE_MLP", "LISTWISE_MLP", "RANK_XGB_NDCG")
LEGACY_STATE, FIXED_STATE, NESTED_STATE = ("LEGACY_40K_FIXED", "FULL_BALANCED_FIXED", "FULL_BALANCED_NESTED")


def role(paradigm, state):
    return f"C10_{paradigm}_{state}"


REFERENCES = (*[role(p, LEGACY_STATE) for p in PARADIGMS], "C10_RIDGE_LEGACY_40K_FIXED")
NEW_ROLES = (*[role(p, s) for p in PARADIGMS for s in (FIXED_STATE, NESTED_STATE)], "C10_RIDGE_FULL_BALANCED")
ALL_ROLES = (*REFERENCES, *NEW_ROLES)
TEST_SPECS = tuple(s for p in PARADIGMS for s in (
    dict(test_id=f"C10_{p}_DATA_SCALE", left=role(p, FIXED_STATE), right=role(p, LEGACY_STATE), kind="DATA_SCALE", paradigm=p),
    dict(test_id=f"C10_{p}_TRAINING_DEPTH", left=role(p, NESTED_STATE), right=role(p, FIXED_STATE), kind="TRAINING_DEPTH", paradigm=p),
    dict(test_id=role(p, NESTED_STATE), left=role(p, NESTED_STATE), right=evidence.RAW, kind="RAW_ENDPOINT", paradigm=p),
)) + (dict(test_id="C10_RIDGE_DATA_SCALE", left="C10_RIDGE_FULL_BALANCED",
          right="C10_RIDGE_LEGACY_40K_FIXED", kind="RIDGE_SANITY", paradigm="RIDGE"),)
TEST_IDS = tuple(s["test_id"] for s in TEST_SPECS)
YEARS, YEAR_COUNTS, PRIMARY, BOOT_METHOD, TARGET = c7.YEARS, c7.YEAR_COUNTS, c7.PRIMARY, c7.BOOT_METHOD, c7.TARGET


def validate_design(design):
    if not (design.get("official_freeze") is True and design.get("formal_freeze_applied") is True):
        raise ValueError("FORMAL_FREEZE_REQUIRED")
    if (design.get("research_id") != RESEARCH_ID or tuple(design.get("roles", ())) != ALL_ROLES
            or design.get("target") != TARGET or tuple(design.get("primary_eval_years", ())) != YEARS):
        raise ValueError("EXACT_SUFFICIENCY_ROLES_AND_UNIFORM_MEAN_REQUIRED")
    if (design.get("mechanism_research_eligible") is not True
            or design.get("strict_PIT_promotion_eligible") is not False
            or design.get("test2026_locked") is not True
            or design.get("new2026_estimation_authorized") is not False):
        raise ValueError("MECHANISM_ONLY_2026_LOCK_REQUIRED")
    ev = design["evaluation"]
    if (ev.get("primary") != PRIMARY or ev.get("common_mature_date_count") != 732
            or ev.get("year_counts") != YEAR_COUNTS or ev.get("exposure_namespace") != 149):
        raise ValueError("ORIGINAL_732_CLOCK_AND_149_EXPOSURE_REQUIRED")
    rule = ev["bootstrap"]
    if (rule.get("method") != BOOT_METHOD or rule.get("repeats") != 5000
            or rule.get("seed") != 20260928 or rule.get("confidence") != .95
            or rule.get("family_candidates") != 137):
        raise ValueError("ORIGINAL_SHARED_MAXT_RULE_REQUIRED")
    required = dict(pooled_edge_positive=True, year2025_edge_positive=True,
                    positive_years_min=2, simultaneous_lower_bound_gt_zero=True)
    if any(ev.get("inherited_selection_requirements", {}).get(k) != v for k, v in required.items()):
        raise ValueError("ORIGINAL_SELECTION_THRESHOLD_REQUIRED")
    if ev.get("test_specs") != list(TEST_SPECS):
        raise ValueError("ONLY_SIXTEEN_PREREGISTERED_SUFFICIENCY_COMPARISONS")
    legacy = ev["legacy"]
    numeric, exposure, failed = (legacy[k] for k in ("numeric_ids", "exposure_ids", "failed_or_untestable"))
    if (len(numeric) != 121 or len(set(numeric)) != 121
            or len(exposure) != 133 or len(set(exposure)) != 133 or len(failed) != 12
            or set(numeric) & set(failed) or set(numeric) | set(failed) != set(exposure)
            or set(exposure) & set(ALL_ROLES + TEST_IDS)):
        raise ValueError("CLOSED_121_NUMERIC_133_EXPOSURE_HISTORY_REQUIRED")
    return ev


def statistics(legacy_edges, new_edges, positions, calendar, rule, legacy_ids, failed=None):
    """Only comparison binding and support summaries; shared_max_t owns all math."""
    legacy_ids, failed = list(legacy_ids), dict(failed or {})
    calendar = pd.DatetimeIndex(calendar)
    if (len(legacy_ids) != 121 or len(set(legacy_ids)) != 121
            or list(legacy_edges.columns) != legacy_ids or legacy_edges.index.has_duplicates
            or not legacy_edges.index.equals(new_edges.index) or new_edges.columns.has_duplicates
            or not set(new_edges).issubset(TEST_IDS) or not set(failed).issubset(TEST_IDS)
            or set(new_edges) & set(failed) or not np.isfinite(legacy_edges.to_numpy(float)).all()
            or not np.isfinite(new_edges.to_numpy(float)).all()
            or calendar.hasnans or calendar.has_duplicates or not calendar.is_monotonic_increasing
            or (calendar >= pd.Timestamp("2026-01-01")).any()):
        raise ValueError("EXACT_FINITE_PRE2026_COMMON_CLOCK_REQUIRED")
    positions = np.asarray(positions)
    if (not np.issubdtype(positions.dtype, np.integer) or len(positions) != len(legacy_edges)
            or (positions < 0).any() or (positions >= len(calendar)).any()
            or not np.all(np.diff(positions) > 0) or not calendar[positions].equals(legacy_edges.index)):
        raise ValueError("ORIGINAL_CALENDAR_POSITIONS_REQUIRED")
    matrix = legacy_edges.copy()
    for tid in TEST_IDS:
        if tid in new_edges:
            matrix[tid] = new_edges[tid]
        else:
            failed.setdefault(tid, "INCOMPLETE_FROZEN_ROLE_OR_DEPENDENCY")
    ids = list(matrix)
    _, _, old_receipt, old_maxima = evidence.shared_max_t(legacy_edges.to_numpy(float), positions,
        [True] * 121, {**rule, "family_candidates": 121})
    lower, se, receipt, maxima = evidence.shared_max_t(matrix.to_numpy(float), positions,
        [True] * len(ids), {**rule, "family_candidates": len(ids)})
    if (receipt.get("status") != "COMPLETE" or old_receipt.get("status") != "COMPLETE"
            or receipt["shared_draw_sha256"] != old_receipt["shared_draw_sha256"]
            or len(maxima) != len(old_maxima) or np.any(maxima + 1e-12 < old_maxima)
            or receipt["critical_max_t"] + 1e-12 < old_receipt["critical_max_t"]):
        raise ValueError("JOINT_MAXT_MUST_NOT_LOWER_LEGACY_THRESHOLD")
    summaries = []
    for spec in TEST_SPECS:
        tid, complete = spec["test_id"], spec["test_id"] in matrix
        j = ids.index(tid) if complete else None
        yearly = {str(y): float(matrix.loc[matrix.index.year == y, tid].mean())
                  if complete and (matrix.index.year == y).any() else None for y in YEARS}
        pooled = float(matrix[tid].mean()) if complete else None
        conditions = dict(complete_oof=complete, all_three_years_present=all(v is not None for v in yearly.values()),
            pooled_positive=pooled is not None and pooled > 0,
            year2025_positive=yearly["2025"] is not None and yearly["2025"] > 0,
            two_of_three_years_positive=sum(v is not None and v > 0 for v in yearly.values()) >= 2,
            nonzero_bootstrap_se=bool(complete and np.isfinite(se[j]) and se[j] > evidence.SE_TOL),
            simultaneous_lower_positive=bool(complete and np.isfinite(lower[j]) and lower[j] > 0))
        summaries.append(dict(**spec, candidate_id=spec["left"], status="COMPLETE" if complete else "FAILED_UNTESTABLE",
            failure_reason=failed.get(tid), pooled_edge=pooled, year_edges=yearly,
            bootstrap_se=float(se[j]) if complete and np.isfinite(se[j]) else None,
            simultaneous_lower_95=float(lower[j]) if complete and np.isfinite(lower[j]) else None,
            research_support_conditions=conditions, supported=all(conditions.values()),
            strict_PIT_promotion_eligible=False, economic_promotion_allowed=False))
    receipt.update(exposure_namespace=149, new_exposure_tests=16, new_candidate_roles=11,
        exact_reused_references=6, legacy_exposure_namespace=133, numeric_complete_series=len(ids),
        legacy_numeric_complete_series=121, failed_series="exposure metadata only; no numeric zero placeholders",
        legacy_shared_draw_sha256=old_receipt["shared_draw_sha256"], legacy_critical_max_t=old_receipt["critical_max_t"],
        draw_wise_legacy_max_not_exceeded_downward=True,
        minimum_draw_wise_max_increment=float((maxima - old_maxima).min()),
        legacy_R2_reselected=False, legacy_R4_reselected=False, legacy_R5_reselected=False, legacy_C7_reselected=False)
    return matrix, summaries, receipt, maxima


def _legacy_identity(legacy, paths):
    design_path = r5._pinned(legacy["design"], paths, "backtest")
    assembly_path = r5._pinned(legacy["assembly"], paths, "backtest")
    design, assembly = readj(design_path), readj(assembly_path)
    ev = c7.validate_design(design)
    # Evidence is an immutable lineage pin. Never parse its mixed result body.
    prior_evidence = r5._pinned(legacy["evidence"], paths, "backtest")
    if (assembly_path.parent != design_path.parent
            or prior_evidence != design_path.parent / "diagnostics/selector_evidence/SELECTION_EVIDENCE.json"
            or Path(legacy["edge"]["path"]).resolve() != prior_evidence.parent / "PRIMARY_DAILY_EDGE.parquet"
            or Path(legacy["clock"]["path"]).resolve() != prior_evidence.parent / "COMMON_DATE_MATURITY.parquet"
            or assembly.get("complete_candidates") != list(c7.ROLES)
            or assembly.get("complete_fixed_references") != list(c7.ANCHORS)
            or assembly.get("failed_or_untestable") != {}
            or assembly.get("design_freeze_sha256") != legacy["design"]["sha256"]
            or legacy["numeric_ids"] != [*ev["legacy"]["numeric_ids"], *c7.TEST_IDS]
            or legacy["exposure_ids"] != [*ev["legacy"]["exposure_ids"], *c7.TEST_IDS]
            or legacy["failed_or_untestable"] != ev["legacy"]["failed_or_untestable"]):
        raise ValueError("CLOSED_C7_LINEAGE_NUMERIC_AND_EXPOSURE_IDENTITIES_CHANGED")


def dependency_failures(available, failed_roles):
    return {s["test_id"]: "DEPENDENCY_FAILED:" + "|".join(
        cid + ":" + failed_roles.get(cid, "INCOMPLETE_ROLE") for cid in (s["left"], s["right"]) if cid not in available)
        for s in TEST_SPECS if s["left"] not in available or s["right"] not in available}


def support_status(summaries):
    lookup = {s["test_id"]: s["supported"] for s in summaries}
    data = [p for p in PARADIGMS if lookup[f"C10_{p}_DATA_SCALE"]]
    depth = [p for p in PARADIGMS if lookup[f"C10_{p}_TRAINING_DEPTH"]]
    selectors = [role(p, NESTED_STATE) for p in PARADIGMS if lookup[role(p, NESTED_STATE)]]
    attributed = [p for p in PARADIGMS if p in depth and role(p, NESTED_STATE) in selectors]
    return dict(data_scale_supported=data, training_depth_supported=depth, selector_supported=selectors,
        depth_attribution=attributed, ridge_sanity_supported=lookup["C10_RIDGE_DATA_SCALE"])


def run(run_directory):
    root, paths = Path(run_directory).resolve(), resolve(REPO)
    assert_safe_output_path(root, kind="backtest", paths=paths)
    from scripts.research.a2.training import selector_training_sufficiency as training
    cfg, design = training.checked(root)
    ev, freeze_hash = validate_design(design), sha(root / "DESIGN_FREEZE.json")
    results, out = Path(cfg["results_directory"]).resolve(), root / "diagnostics/selector_evidence"
    assert_safe_output_path(results, kind="results", paths=paths)
    assert_safe_output_path(out, kind="backtest", paths=paths)
    if (results / "SELECTION_EVIDENCE.json").exists() or (out / "SELECTION_EVIDENCE.json").exists():
        raise FileExistsError("PRESERVE_EXISTING_SUFFICIENCY_EVIDENCE")
    assembly_path = root / "SCORE_ASSEMBLY.json"
    activation = readj(root / "EVALUATION_CODE_ACTIVATION.json")
    required_sources = (Path(__file__), Path(evidence.__file__), Path(r5.__file__), Path(c7.__file__),
                        REPO / "scripts/research/a2/evaluation/selector_account_compare.py")
    if (activation.get("design_freeze_sha256") != freeze_hash
            or activation.get("score_assembly_sha256") != sha(assembly_path)
            or any(activation.get("sources", {}).get(str(s)) != sha(s)
                   or design.get("sources", {}).get(str(s)) != sha(s) for s in required_sources)):
        raise ValueError("FROZEN_EVALUATION_AND_ASSEMBLY_ACTIVATION_REQUIRED")
    assembly = readj(assembly_path)
    complete, failed_roles = assembly["complete_candidates"], dict(assembly["failed_or_untestable"])
    if (len(set(complete)) != len(complete) or not set(complete).issubset(NEW_ROLES)
            or set(complete) & set(failed_roles) or set(complete) | set(failed_roles) != set(NEW_ROLES)
            or assembly.get("complete_fixed_references") != list(REFERENCES)
            or assembly.get("forecast2026_rows") != 0 or assembly.get("design_freeze_sha256") != freeze_hash):
        raise ValueError("EVERY_NEW_ROLE_AND_SIX_REUSED_REFERENCES_REQUIRE_BOUND_READINESS")
    legacy = ev["legacy"]
    _legacy_identity(legacy, paths)
    evidence.prove_label_boundary(r5._pinned(design["inputs"]["training"], paths, "results"), "target_end_date")
    clock, old_edges, edge_path, clock_path = r5._clock(legacy, paths)
    raw_path = score_path(root, evidence.RAW)
    evidence.prove_label_boundary(raw_path, "label_end_date", allow_null=True)
    reference, raw_hash = c7._bound_panel(root, evidence.RAW, assembly)
    labels = pre2026(raw_path, evidence.KEY + ["target", "label_end_date"], "signal_date")
    labels["signal_date"] = pd.to_datetime(labels.signal_date)
    if not labels.loc[labels.label_end_date.isna(), "target"].isna().all():
        raise ValueError("TARGET_WITH_UNKNOWN_LABEL_MATURITY")
    reference = reference.merge(labels, on=evidence.KEY, validate="one_to_one", how="left")
    calendar = pd.DatetimeIndex(clock.signal_date)
    if (len(reference) != assembly["common_rows"] or reference.signal_date.nunique() != assembly["common_dates"]
            or not pd.DatetimeIndex(sorted(reference.signal_date.unique())).equals(calendar)):
        raise ValueError("FULL_U_T_MUST_RETAIN_ORIGINAL_752_CALENDAR")
    arrays = {evidence.RAW: (reference.score.to_numpy(float), reference["rank"].to_numpy(float))}
    hashes, maturity_rows = {evidence.RAW: raw_hash}, []
    raw_selected = reference["rank"].le(20).to_numpy()
    mature, raw_maturity = evidence.maturity(reference, raw_selected)
    if not raw_maturity.loc[clock.included, "included"].all():
        raise ValueError("RAW_IMMATURE_ON_ORIGINAL_COMMON_DATE")
    for cid in (*REFERENCES, *complete):
        panel, digest = c7._bound_panel(root, cid, assembly)
        evidence.align(reference, panel)
        _, maturity = evidence.maturity(reference, raw_selected | panel["rank"].le(20).to_numpy())
        maturity["candidate_id"] = cid
        maturity_rows.append(maturity)
        if not maturity.loc[clock.included, "included"].all():
            if cid in REFERENCES:
                raise ValueError("FIXED_LEGACY_REFERENCE_IMMATURE_ON_ORIGINAL_COMMON_DATE:" + cid)
            failed_roles[cid] = "SELECTED_LABELS_IMMATURE_ON_ORIGINAL_COMMON_DATE_NO_SHRINK"
            continue
        arrays[cid], hashes[cid] = (panel.score.to_numpy(float), panel["rank"].to_numpy(float)), digest
    failed_tests = dependency_failures(arrays, failed_roles)
    common, diagnostics = clock.set_index("signal_date").included, []
    # Only preregistered comparisons. In particular, no FULL_FIXED-vs-Raw rows.
    for spec in TEST_SPECS:
        if spec["test_id"] not in failed_tests:
            scores, ranks = arrays[spec["left"]]
            diagnostics.extend(evidence.diagnose(spec["test_id"], reference, scores, ranks,
                arrays[spec["right"]][1], mature, common))
    daily = pd.DataFrame(diagnostics)
    new_edges = pd.DataFrame(index=old_edges.index)
    for tid in TEST_IDS:
        if tid not in failed_tests:
            rows = daily.loc[daily.candidate_id.eq(tid) & daily.common_mature_date]
            new_edges[tid] = rows.set_index("signal_date").replacement_edge.reindex(old_edges.index)
    matrix, summaries, bootstrap, maxima = statistics(old_edges, new_edges,
        np.flatnonzero(clock.included.to_numpy(bool)), calendar, ev["bootstrap"], legacy["numeric_ids"], failed_tests)
    supported = support_status(summaries)
    receipt = dict(schema="C_TRAINING_SUFFICIENCY_SELECTION_EVIDENCE_V1", status="MECHANISM_EVIDENCE_COMPLETE",
        research_id=RESEARCH_ID, mechanism_research_eligible=True, strict_PIT_promotion_eligible=False,
        financial_verified=False, economic_promotion_allowed=False, strict_PIT_production_upgrade=False,
        research_supported_roles=supported["selector_supported"], finalists=[],
        finalist_status="NO_PRODUCTION_PROMOTION_FROZEN_HISTORY_ONLY", **supported,
        design_freeze_sha256=freeze_hash, score_assembly_sha256=sha(assembly_path),
        evaluation_source_sha256=sha(Path(__file__)), score_sha256=hashes,
        tests=summaries, bootstrap=bootstrap, failed_roles=failed_roles, failed_tests=failed_tests,
        failed_or_untestable={**legacy["failed_or_untestable"], **failed_tests},
        exposure_namespace=149, exposure_roles=[*legacy["exposure_ids"], *TEST_IDS],
        exact_reused_references=list(REFERENCES), references_are_new_exposure=False,
        ridge_promotion_allowed=False, full_fixed_vs_raw_tests=False,
        comparison_policy="DATA_SCALE_AND_TRAINING_DEPTH_SEPARATE;DEPTH_ATTRIBUTION_REQUIRES_DEPTH_AND_RAW",
        weighting_limitation="full date-balanced training protocol; not isolated pure sample-count causality",
        unified_evaluation_target=TARGET, legacy_numeric_ids=legacy["numeric_ids"],
        legacy_exposure_roles=legacy["exposure_ids"], legacy_failed_or_untestable=legacy["failed_or_untestable"],
        legacy_R2_disposition="CLOSED_NO_RESELECTION_NO_PROMOTION", legacy_R4_disposition="CLOSED_NO_RESELECTION_NO_PROMOTION",
        legacy_R5_disposition="CLOSED_NO_RESELECTION_NO_PROMOTION", legacy_C7_disposition="CLOSED_NO_RESELECTION_NO_PROMOTION",
        legacy_daily_edge_sha256=sha(edge_path), legacy_common_clock_sha256=sha(clock_path),
        legacy_evidence_sha256=legacy["evidence"]["sha256"], label_source_sha256=design["inputs"]["training"]["sha256"],
        common_mature_dates=732, common_year_dates=YEAR_COUNTS, original_calendar_dates=752,
        excluded_dates=int((~clock.included).sum()), diagnostics_directory=str(out), run_directory=str(root),
        claim="Frozen-history training-sufficiency mechanism evidence; exposed development; no executable profit claim",
        test2026_locked=True, new2026_estimation_authorized=False, test2026_rows_read=0,
        test2026_rows_read_by_this_runner=0)
    out.mkdir(parents=True, exist_ok=True)
    clock.to_parquet(out / "COMMON_DATE_MATURITY.parquet", index=False)
    daily.to_parquet(out / "DAILY_DIAGNOSTICS.parquet", index=False)
    if len(daily):
        metrics = ["ic", "spearman_ic", "ndcg20", "truth_top20_recall", "top20_target_mean",
                   "precision_target_positive", "overlap20", "score_std", "score_iqr", "rank_migration_mean_absolute"]
        daily.assign(year=daily.signal_date.dt.year).groupby(["candidate_id", "year"])[metrics].mean().reindex(
            pd.MultiIndex.from_product([TEST_IDS, YEARS], names=["candidate_id", "year"])).reset_index().to_parquet(
                out / "YEAR_DIAGNOSTICS.parquet", index=False)
    if maturity_rows:
        pd.concat(maturity_rows, ignore_index=True).to_parquet(out / "ROLE_DATE_MATURITY.parquet", index=False)
    matrix.rename_axis("signal_date").reset_index().to_parquet(out / "PRIMARY_DAILY_EDGE.parquet", index=False)
    pd.DataFrame(dict(replicate=np.arange(len(maxima)), centered_standardized_max_t=maxima)).to_parquet(
        out / "BOOTSTRAP_MAXT.parquet", index=False)
    receipt["diagnostic_sha256"] = {p.name: sha(p) for p in out.glob("*.parquet")}
    evidence.putj(out / "SELECTION_EVIDENCE.json", receipt)
    evidence.putj(results / "SELECTION_EVIDENCE.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    print(run(args.run)["status"])
